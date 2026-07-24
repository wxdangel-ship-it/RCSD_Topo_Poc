from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, box
from shapely.ops import substring

from .geometry import canonical_id, parse_patch_membership, swsd_direction_delta_deg, tangent_vector
from .road_config import MilestoneTwoConfig


@dataclass(frozen=True)
class RoadEvidenceResult:
    lane_samples: gpd.GeoDataFrame
    lane_segments: gpd.GeoDataFrame
    support_intervals: gpd.GeoDataFrame
    road_audit: pd.DataFrame
    quality_flags: pd.DataFrame
    summary: dict[str, Any]


def build_road_evidence(
    lane_decisions: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    lane_topology: gpd.GeoDataFrame,
    *,
    config: MilestoneTwoConfig,
    credible_conflict_road_ids: set[str] | None = None,
) -> RoadEvidenceResult:
    roads = _prepare_roads(swsd_roads)
    lanes = lane_decisions.copy().reset_index(drop=True)
    lanes["lane_id"] = lanes["lane_id"].map(canonical_id)
    nodes_by_road = dict(zip(roads["swsd_unit_id"], roads["_semantic_nodes"], strict=True))

    sample_rows: list[dict[str, Any]] = []
    segment_rows: list[dict[str, Any]] = []
    transition_flags: list[dict[str, Any]] = []
    for lane in lanes.itertuples():
        samples, segments, flags = _assign_lane_segments(
            lane,
            roads,
            nodes_by_road,
            config=config,
        )
        sample_rows.extend(samples)
        segment_rows.extend(segments)
        transition_flags.extend(flags)

    lane_samples = gpd.GeoDataFrame(sample_rows, geometry="geometry", crs=lanes.crs)
    lane_segments = gpd.GeoDataFrame(segment_rows, geometry="geometry", crs=lanes.crs)
    support_intervals, road_audit = build_support_intervals(
        roads,
        lane_segments,
        run_id=config.run_id,
        full_coverage_ratio=config.support_full_coverage_ratio,
        max_gap_m=config.support_max_gap_m,
        credible_conflict_road_ids=credible_conflict_road_ids or set(),
    )
    quality_flags = build_quality_flags(
        lanes,
        lane_topology,
        lane_samples,
        transition_flags,
        run_id=config.run_id,
    )
    summary = _build_summary(
        lanes,
        roads,
        lane_samples,
        lane_segments,
        support_intervals,
        road_audit,
        quality_flags,
    )
    return RoadEvidenceResult(
        lane_samples=lane_samples,
        lane_segments=lane_segments,
        support_intervals=support_intervals,
        road_audit=road_audit,
        quality_flags=quality_flags,
        summary=summary,
    )


def build_support_intervals(
    roads: gpd.GeoDataFrame,
    lane_segments: gpd.GeoDataFrame,
    *,
    run_id: str,
    full_coverage_ratio: float,
    max_gap_m: float,
    credible_conflict_road_ids: set[str],
) -> tuple[gpd.GeoDataFrame, pd.DataFrame]:
    road_frame = _prepare_roads(roads)
    by_road = {
        str(road_id): frame.reset_index(drop=True)
        for road_id, frame in lane_segments.groupby("swsd_unit_id")
    }
    interval_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    for road in road_frame.itertuples():
        road_id = str(road.swsd_unit_id)
        road_length = float(road.geometry.length)
        segments = by_road.get(road_id)
        support = _merge_segment_intervals(segments, road_length)
        gaps = _complement([(row["start_m"], row["end_m"]) for row in support], road_length)
        support_length = sum(row["end_m"] - row["start_m"] for row in support)
        coverage = support_length / road_length if road_length > 1e-8 else 0.0
        gap_lengths = [end - start for start, end in gaps]
        largest_gap = max(gap_lengths, default=0.0)
        conflict = road_id in credible_conflict_road_ids
        if conflict:
            support_state = "conflict_retained"
            support_reason = "credible_structure_conflict_retained"
        elif not support:
            support_state = "sd_only"
            support_reason = "no_local_lane_evidence"
        elif coverage >= full_coverage_ratio and largest_gap <= max_gap_m:
            support_state = "hp_supported"
            support_reason = "full_longitudinal_support"
        else:
            support_state = "partial_hp_supported"
            support_reason = "longitudinal_support_has_gap"

        all_lane_ids = sorted(
            {
                lane_id
                for interval in support
                for lane_id in str(interval["source_lane_ids"]).split(";")
                if lane_id
            }
        )
        all_patch_ids = sorted(
            {
                patch_id
                for interval in support
                for patch_id in str(interval["source_patch_ids"]).split(";")
                if patch_id
            }
        )
        evidence_quality_state = (
            _road_evidence_quality(segments) if support else "insufficient"
        )
        audit_rows.append(
            {
                "run_id": run_id,
                "swsd_unit_id": road_id,
                "road_length_m": road_length,
                "lane_segment_count": 0 if segments is None else int(len(segments)),
                "source_lane_count": len(all_lane_ids),
                "source_lane_ids": ";".join(all_lane_ids),
                "source_patch_ids": ";".join(all_patch_ids),
                "support_interval_count": len(support),
                "gap_interval_count": len(gaps),
                "support_length_m": support_length,
                "gap_length_m": max(0.0, road_length - support_length),
                "support_coverage_ratio": coverage,
                "max_gap_m": largest_gap,
                "support_state": support_state,
                "support_reason": support_reason,
                "evidence_quality_state": evidence_quality_state,
            }
        )
        partition = [
            {
                **row,
                "interval_state": "hp_supported",
                "geometry_source": "hp_fitted_pending",
            }
            for row in support
        ]
        partition.extend(
            {
                "start_m": start,
                "end_m": end,
                "source_lane_ids": "",
                "source_patch_ids": "",
                "min_fit_weight": None,
                "interval_state": "sd_gap",
                "geometry_source": "swsd_retained",
            }
            for start, end in gaps
        )
        for interval_index, interval in enumerate(
            sorted(partition, key=lambda row: (row["start_m"], row["end_m"]))
        ):
            start = float(interval["start_m"])
            end = float(interval["end_m"])
            interval_state = (
                "conflict_retained" if conflict and interval["interval_state"] == "hp_supported" else interval["interval_state"]
            )
            geometry_source = (
                "conflict_retained" if interval_state == "conflict_retained" else interval["geometry_source"]
            )
            interval_rows.append(
                {
                    "run_id": run_id,
                    "source_patch_ids": interval["source_patch_ids"],
                    "source_object_type": "LaneEvidenceSegment" if interval["source_lane_ids"] else "SWSDRoad",
                    "source_object_ids": interval["source_lane_ids"] or road_id,
                    "swsd_unit_id": road_id,
                    "interval_id": f"{road_id}:{interval_index}",
                    "interval_index": interval_index,
                    "interval_state": interval_state,
                    "start_m": start,
                    "end_m": end,
                    "start_fraction": start / road_length if road_length > 1e-8 else 0.0,
                    "end_fraction": end / road_length if road_length > 1e-8 else 1.0,
                    "interval_length_m": end - start,
                    "source_lane_ids": interval["source_lane_ids"],
                    "min_fit_weight": interval["min_fit_weight"],
                    "geometry_source": geometry_source,
                    "decision": "candidate_interval",
                    "reason_codes": interval_state,
                    "evidence_state": "road_support_interval",
                    "input_manifest_ref": "p04_input_manifest.json",
                    "geometry": _line_part(road.geometry, start, end),
                }
            )
    intervals = gpd.GeoDataFrame(interval_rows, geometry="geometry", crs=road_frame.crs)
    return intervals, pd.DataFrame(audit_rows)


def classify_support_state(
    *,
    has_support: bool,
    coverage_ratio: float,
    max_gap_m: float,
    full_coverage_ratio: float,
    full_max_gap_m: float,
    credible_structure_conflict: bool,
) -> str:
    if credible_structure_conflict:
        return "conflict_retained"
    if not has_support:
        return "sd_only"
    if coverage_ratio >= full_coverage_ratio and max_gap_m <= full_max_gap_m:
        return "hp_supported"
    return "partial_hp_supported"


def build_quality_flags(
    lanes: gpd.GeoDataFrame,
    lane_topology: gpd.GeoDataFrame,
    lane_samples: gpd.GeoDataFrame,
    transition_flags: list[dict[str, Any]],
    *,
    run_id: str,
) -> pd.DataFrame:
    flags: list[dict[str, Any]] = []
    width_categories = {
        "narrow_candidate": "narrow_lane",
        "wide_or_boundary_gap": "wide_or_boundary_gap",
        "unstable": "width_unstable",
        "partial": "boundary_partial",
        "insufficient_evidence": "boundary_insufficient",
    }
    for lane in lanes.itertuples():
        lane_id = str(lane.lane_id)
        patch_id = str(lane.source_patch_ids)
        width_state = str(lane.width_state)
        if width_state in width_categories:
            flags.append(
                _quality_row(
                    run_id,
                    "Lane",
                    lane_id,
                    patch_id,
                    width_categories[width_state],
                    "review" if width_state != "insufficient_evidence" else "insufficient",
                    width_state,
                    canonical_id(lane.swsd_unit_id),
                )
            )
        if str(lane.owner_state) != "accepted":
            flags.append(
                _quality_row(
                    run_id,
                    "Lane",
                    lane_id,
                    patch_id,
                    f"primary_owner_{lane.owner_state}",
                    "review" if str(lane.owner_state) == "review_required" else "insufficient",
                    str(lane.reason_codes),
                    canonical_id(lane.swsd_unit_id),
                )
            )
        if float(lane.drivezone_coverage) < 0.80:
            flags.append(
                _quality_row(
                    run_id,
                    "Lane",
                    lane_id,
                    patch_id,
                    "road_surface_low_coverage",
                    "review",
                    "lane_outside_drivezone_fix",
                    canonical_id(lane.swsd_unit_id),
                )
            )

    topology_categories = {
        "cross_owner_shared_node_review": "cross_road_direction_review",
        "cross_owner_semantic_unconnected_review": "cross_road_semantic_node_anomaly",
    }
    for link in lane_topology.itertuples():
        state = str(link.lane_topo_state)
        if state not in topology_categories:
            continue
        flags.append(
            _quality_row(
                run_id,
                "LaneNextLane",
                str(link.link_id),
                str(link.source_patch_ids),
                topology_categories[state],
                "review",
                state,
                f"{link.source_owner}->{link.target_owner}",
            )
        )

    unmatched = lane_samples[lane_samples["assignment_state"] == "no_local_swsd_fit"]
    for lane_id, group in unmatched.groupby("lane_id"):
        flags.append(
            _quality_row(
                run_id,
                "LaneSample",
                str(lane_id),
                ";".join(sorted(group["source_patch_ids"].astype(str).unique())),
                "local_swsd_fit_missing",
                "review",
                f"unmatched_sample_count={len(group)}",
                "",
            )
        )
    flags.extend(transition_flags)
    for index, row in enumerate(flags):
        row["flag_id"] = f"Q{index + 1:06d}"
    columns = [
        "run_id",
        "flag_id",
        "source_object_type",
        "source_object_id",
        "source_patch_ids",
        "quality_category",
        "evidence_quality_state",
        "reason_codes",
        "related_swsd_unit_ids",
        "road_conflict_effect",
    ]
    return pd.DataFrame(flags, columns=columns)


def _assign_lane_segments(
    lane: Any,
    roads: gpd.GeoDataFrame,
    nodes_by_road: dict[str, set[str]],
    *,
    config: MilestoneTwoConfig,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    offsets = _sample_offsets(float(lane.geometry.length), config.lane_segment_sample_spacing_m)
    candidate_sets: list[list[dict[str, Any]]] = []
    patch_id = str(lane.source_patch_ids)
    for offset in offsets:
        point = lane.geometry.interpolate(float(offset))
        candidate_sets.append(
            _point_candidates(
                point,
                tangent_vector(lane.geometry, float(offset)),
                patch_id,
                roads,
                config=config,
            )
        )
    path = _viterbi_path(candidate_sets, nodes_by_road, config=config)
    sample_rows = _sample_records(lane, offsets, candidate_sets, path, config.run_id)
    segment_rows = _segment_records(lane, offsets, path, roads, config.run_id)
    transition_flags = _transition_quality_flags(segment_rows, nodes_by_road, config.run_id)
    return sample_rows, segment_rows, transition_flags


def _point_candidates(
    point: Point,
    lane_tangent: tuple[float, float],
    patch_id: str,
    roads: gpd.GeoDataFrame,
    *,
    config: MilestoneTwoConfig,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    query = box(*point.buffer(config.lane_segment_search_radius_m).bounds)
    for candidate_index in roads.sindex.query(query):
        road = roads.iloc[int(candidate_index)]
        if patch_id not in road["_patch_membership"]:
            continue
        road_offset = float(road.geometry.project(point))
        distance = float(point.distance(road.geometry.interpolate(road_offset)))
        if distance > config.lane_segment_max_distance_m:
            continue
        direction_delta = swsd_direction_delta_deg(
            lane_tangent,
            tangent_vector(road.geometry, road_offset),
            _coerce_int(road.get("direction")),
        )
        if direction_delta > config.lane_segment_max_direction_delta_deg:
            continue
        candidates.append(
            {
                "road_id": str(road["swsd_unit_id"]),
                "road_offset_m": road_offset,
                "distance_m": distance,
                "direction_delta_deg": float(direction_delta),
                "emission_score": distance + 0.10 * float(direction_delta),
            }
        )
    candidates.sort(key=lambda row: (row["emission_score"], row["road_id"]))
    return candidates[: config.lane_segment_candidate_limit]


def _viterbi_path(
    candidate_sets: list[list[dict[str, Any]]],
    nodes_by_road: dict[str, set[str]],
    *,
    config: MilestoneTwoConfig,
) -> list[dict[str, Any] | None]:
    states = [candidates if candidates else [None] for candidates in candidate_sets]
    costs: list[dict[int, float]] = []
    backs: list[dict[int, int | None]] = []
    for sample_index, sample_states in enumerate(states):
        current_costs: dict[int, float] = {}
        current_backs: dict[int, int | None] = {}
        for current_index, current in enumerate(sample_states):
            emission = 20.0 if current is None else float(current["emission_score"])
            if sample_index == 0:
                current_costs[current_index] = emission
                current_backs[current_index] = None
                continue
            choices: list[tuple[float, int]] = []
            for previous_index, previous in enumerate(states[sample_index - 1]):
                transition = _transition_cost(previous, current, nodes_by_road, config=config)
                choices.append((costs[-1][previous_index] + transition + emission, previous_index))
            current_costs[current_index], current_backs[current_index] = min(choices)
        costs.append(current_costs)
        backs.append(current_backs)
    if not states:
        return []
    selected_index = min(costs[-1], key=costs[-1].get)
    selected: list[dict[str, Any] | None] = [None] * len(states)
    for sample_index in range(len(states) - 1, -1, -1):
        selected[sample_index] = states[sample_index][selected_index]
        previous_index = backs[sample_index][selected_index]
        if previous_index is None:
            break
        selected_index = previous_index
    return selected


def _transition_cost(
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
    nodes_by_road: dict[str, set[str]],
    *,
    config: MilestoneTwoConfig,
) -> float:
    if previous is None and current is None:
        return 0.0
    if previous is None or current is None:
        return config.lane_segment_adjacent_transition_penalty
    previous_id = str(previous["road_id"])
    current_id = str(current["road_id"])
    if previous_id == current_id:
        return 0.0
    if nodes_by_road.get(previous_id, set()) & nodes_by_road.get(current_id, set()):
        return config.lane_segment_adjacent_transition_penalty
    return config.lane_segment_unrelated_transition_penalty


def _sample_records(
    lane: Any,
    offsets: np.ndarray,
    candidate_sets: list[list[dict[str, Any]]],
    path: list[dict[str, Any] | None],
    run_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sample_index, (offset, candidates, selected) in enumerate(
        zip(offsets, candidate_sets, path, strict=True)
    ):
        rows.append(
            {
                "run_id": run_id,
                "lane_id": str(lane.lane_id),
                "source_patch_ids": str(lane.source_patch_ids),
                "sample_index": sample_index,
                "lane_offset_m": float(offset),
                "candidate_count": len(candidates),
                "top_score_margin": (
                    float(candidates[1]["emission_score"] - candidates[0]["emission_score"])
                    if len(candidates) > 1
                    else (9999.0 if candidates else None)
                ),
                "assigned_road_id": "" if selected is None else selected["road_id"],
                "assigned_road_offset_m": None if selected is None else selected["road_offset_m"],
                "assigned_distance_m": None if selected is None else selected["distance_m"],
                "assigned_direction_delta_deg": None if selected is None else selected["direction_delta_deg"],
                "assignment_state": "no_local_swsd_fit" if selected is None else "locally_supported",
                "evidence_quality_state": "insufficient" if selected is None else _lane_quality_state(lane),
                "geometry": lane.geometry.interpolate(float(offset)),
            }
        )
    return rows


def _segment_records(
    lane: Any,
    offsets: np.ndarray,
    path: list[dict[str, Any] | None],
    roads: gpd.GeoDataFrame,
    run_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    run_start = 0
    while run_start < len(path):
        road_id = "" if path[run_start] is None else str(path[run_start]["road_id"])
        run_end = run_start
        while run_end + 1 < len(path):
            next_id = "" if path[run_end + 1] is None else str(path[run_end + 1]["road_id"])
            if next_id != road_id:
                break
            run_end += 1
        if road_id:
            source_start = 0.0 if run_start == 0 else float((offsets[run_start - 1] + offsets[run_start]) / 2.0)
            source_end = (
                float(lane.geometry.length)
                if run_end == len(path) - 1
                else float((offsets[run_end] + offsets[run_end + 1]) / 2.0)
            )
            road_geometry = roads.loc[roads["swsd_unit_id"] == road_id, "geometry"].iloc[0]
            projections = [
                float(road_geometry.project(lane.geometry.interpolate(source_start))),
                float(road_geometry.project(lane.geometry.interpolate(source_end))),
                *[
                    float(path[index]["road_offset_m"])
                    for index in range(run_start, run_end + 1)
                    if path[index] is not None
                ],
            ]
            quality_state = _lane_quality_state(lane)
            rows.append(
                {
                    "run_id": run_id,
                    "source_patch_ids": str(lane.source_patch_ids),
                    "source_object_type": "Lane",
                    "source_object_ids": str(lane.lane_id),
                    "lane_id": str(lane.lane_id),
                    "swsd_unit_id": road_id,
                    "source_start_m": source_start,
                    "source_end_m": source_end,
                    "source_length_m": source_end - source_start,
                    "road_start_m": min(projections),
                    "road_end_m": max(projections),
                    "sample_count": run_end - run_start + 1,
                    "assignment_method": "local_swsd_viterbi",
                    "whole_lane_primary_owner": canonical_id(lane.swsd_unit_id),
                    "whole_lane_owner_state": str(lane.owner_state),
                    "width_state": str(lane.width_state),
                    "evidence_quality_state": quality_state,
                    "fit_weight": _fit_weight(lane),
                    "decision": "accepted_segment",
                    "reason_codes": "local_distance_direction_graph_fit",
                    "evidence_state": "lane_evidence_segment",
                    "input_manifest_ref": "p04_input_manifest.json",
                    "geometry": _line_part(lane.geometry, source_start, source_end),
                }
            )
        run_start = run_end + 1
    return rows


def _transition_quality_flags(
    segments: list[dict[str, Any]],
    nodes_by_road: dict[str, set[str]],
    run_id: str,
) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for previous, current in zip(segments, segments[1:]):
        previous_id = str(previous["swsd_unit_id"])
        current_id = str(current["swsd_unit_id"])
        if nodes_by_road.get(previous_id, set()) & nodes_by_road.get(current_id, set()):
            continue
        flags.append(
            _quality_row(
                run_id,
                "LaneEvidenceTransition",
                str(current["lane_id"]),
                str(current["source_patch_ids"]),
                "local_assignment_unconnected_transition",
                "review",
                f"{previous_id}->{current_id}",
                f"{previous_id};{current_id}",
            )
        )
    return flags


def _merge_segment_intervals(
    segments: gpd.GeoDataFrame | None,
    road_length: float,
) -> list[dict[str, Any]]:
    if segments is None or segments.empty:
        return []
    raw = sorted(
        (
            max(0.0, min(road_length, float(row.road_start_m))),
            max(0.0, min(road_length, float(row.road_end_m))),
            str(row.lane_id),
            str(row.source_patch_ids),
            float(row.fit_weight),
        )
        for row in segments.itertuples()
        if float(row.road_end_m) >= float(row.road_start_m)
    )
    merged: list[dict[str, Any]] = []
    for start, end, lane_id, patch_id, weight in raw:
        if end - start <= 1e-8:
            continue
        if not merged or start > merged[-1]["end_m"] + 1e-8:
            merged.append(
                {
                    "start_m": start,
                    "end_m": end,
                    "lane_ids": {lane_id},
                    "patch_ids": {patch_id},
                    "weights": [weight],
                }
            )
        else:
            merged[-1]["end_m"] = max(merged[-1]["end_m"], end)
            merged[-1]["lane_ids"].add(lane_id)
            merged[-1]["patch_ids"].add(patch_id)
            merged[-1]["weights"].append(weight)
    return [
        {
            "start_m": row["start_m"],
            "end_m": row["end_m"],
            "source_lane_ids": ";".join(sorted(row["lane_ids"])),
            "source_patch_ids": ";".join(sorted(row["patch_ids"])),
            "min_fit_weight": min(row["weights"]),
        }
        for row in merged
    ]


def _complement(intervals: Iterable[tuple[float, float]], road_length: float) -> list[tuple[float, float]]:
    gaps: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in intervals:
        if start > cursor + 1e-8:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < road_length - 1e-8:
        gaps.append((cursor, road_length))
    return gaps


def _prepare_roads(roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    prepared = roads.copy().reset_index(drop=True)
    prepared["swsd_unit_id"] = prepared["swsd_unit_id"].map(canonical_id)
    if "all_patch_ids" in prepared.columns:
        prepared["_patch_membership"] = prepared["all_patch_ids"].map(parse_patch_membership)
    elif "patch_id" in prepared.columns:
        prepared["_patch_membership"] = prepared["patch_id"].map(parse_patch_membership)
    else:
        prepared["_patch_membership"] = [frozenset() for _ in range(len(prepared))]
    prepared["_semantic_nodes"] = prepared.apply(_semantic_nodes, axis=1)
    return prepared


def _semantic_nodes(row: pd.Series) -> set[str]:
    values = {
        canonical_id(row.get("semantic_snode_id")),
        canonical_id(row.get("semantic_enode_id")),
        canonical_id(row.get("snode_id")),
        canonical_id(row.get("enode_id")),
    }
    return {value for value in values if value is not None}


def _quality_row(
    run_id: str,
    source_type: str,
    source_id: str,
    patch_ids: str,
    category: str,
    state: str,
    reason: str,
    related_roads: str | None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "source_object_type": source_type,
        "source_object_id": source_id,
        "source_patch_ids": patch_ids,
        "quality_category": category,
        "evidence_quality_state": state,
        "reason_codes": reason,
        "related_swsd_unit_ids": related_roads or "",
        "road_conflict_effect": "none_input_quality_only",
    }


def _lane_quality_state(lane: Any) -> str:
    if str(lane.owner_state) == "insufficient_evidence":
        return "insufficient"
    if str(lane.decision) == "accepted":
        return "usable"
    return "review"


def _fit_weight(lane: Any) -> float:
    if str(lane.decision) == "accepted":
        return 1.0
    if str(lane.owner_state) == "accepted":
        return 0.85
    if str(lane.owner_state) == "review_required":
        return 0.70
    return 0.55


def _road_evidence_quality(segments: gpd.GeoDataFrame | None) -> str:
    if segments is None or segments.empty:
        return "insufficient"
    states = set(segments["evidence_quality_state"].astype(str))
    if states == {"usable"}:
        return "clean"
    return "qa_flagged"


def _sample_offsets(length: float, spacing: float) -> np.ndarray:
    count = max(2, int(math.ceil(max(length, 0.0) / spacing)) + 1)
    return np.linspace(0.0, max(length, 0.0), count)


def _line_part(line: Any, start: float, end: float) -> Any:
    if end - start <= 1e-8:
        point = line.interpolate(start)
        return LineString([point, point])
    return substring(line, start, end)


def _coerce_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_summary(
    lanes: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    samples: gpd.GeoDataFrame,
    segments: gpd.GeoDataFrame,
    intervals: gpd.GeoDataFrame,
    road_audit: pd.DataFrame,
    quality_flags: pd.DataFrame,
) -> dict[str, Any]:
    state_counts = Counter(road_audit["support_state"])
    interval_length = intervals.groupby("swsd_unit_id")["interval_length_m"].sum()
    road_length = road_audit.set_index("swsd_unit_id")["road_length_m"]
    length_delta = interval_length.reindex(road_length.index, fill_value=0.0) - road_length
    assigned = samples["assignment_state"] == "locally_supported"
    road_count_per_lane = segments.groupby("lane_id")["swsd_unit_id"].nunique()
    category_counts = Counter(quality_flags["quality_category"])
    return {
        "lane_count": int(len(lanes)),
        "road_count": int(len(roads)),
        "lane_sample_count": int(len(samples)),
        "assigned_lane_sample_count": int(assigned.sum()),
        "unmatched_lane_sample_count": int((~assigned).sum()),
        "assigned_lane_sample_ratio": float(assigned.mean()),
        "lane_evidence_segment_count": int(len(segments)),
        "lane_with_segment_count": int(segments["lane_id"].nunique()),
        "lane_contributing_multiple_road_count": int(road_count_per_lane.gt(1).sum()),
        "max_road_per_lane": int(road_count_per_lane.max()),
        "road_with_evidence_count": int(road_audit["source_lane_count"].gt(0).sum()),
        "support_state_counts": {
            state: int(state_counts[state])
            for state in (
                "hp_supported",
                "partial_hp_supported",
                "sd_only",
                "conflict_retained",
            )
        },
        "road_conservation_gate_pass": int(sum(state_counts.values())) == int(len(roads)),
        "interval_partition_gate_pass": bool(length_delta.abs().max() <= 1e-6),
        "interval_partition_max_abs_delta_m": float(length_delta.abs().max()),
        "quality_flag_count": int(len(quality_flags)),
        "quality_category_counts": dict(sorted(category_counts.items())),
        "known_quality_counts": {
            "narrow_lane": int(category_counts["narrow_lane"]),
            "wide_or_boundary_gap": int(category_counts["wide_or_boundary_gap"]),
            "width_unstable": int(category_counts["width_unstable"]),
            "cross_road_direction_review": int(category_counts["cross_road_direction_review"]),
            "cross_road_semantic_node_anomaly": int(
                category_counts["cross_road_semantic_node_anomaly"]
            ),
            "patch_5417631180197930_boundary_insufficient": int(
                (
                    (quality_flags["quality_category"] == "boundary_insufficient")
                    & quality_flags["source_patch_ids"].astype(str).eq("5417631180197930")
                ).sum()
            ),
        },
        "quality_flag_direct_road_conflict_count": int(
            (quality_flags["road_conflict_effect"] != "none_input_quality_only").sum()
        ),
    }


__all__ = [
    "RoadEvidenceResult",
    "build_quality_flags",
    "build_road_evidence",
    "build_support_intervals",
    "classify_support_state",
]
