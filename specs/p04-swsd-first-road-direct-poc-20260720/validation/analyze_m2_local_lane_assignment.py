from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point, box
from shapely.ops import substring

from rcsd_topo_poc.modules.p04_road_direct_generation.geometry import (
    swsd_direction_delta_deg,
    tangent_vector,
)


POLICIES = {
    "viterbi_all_lanes": lambda lane: True,
    "viterbi_owner_not_insufficient": lambda lane: lane.owner_state != "insufficient_evidence",
    "viterbi_global_owner_accepted": lambda lane: lane.owner_state == "accepted",
    "viterbi_strict_accepted": lambda lane: lane.decision == "accepted",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Lane-local SWSD Road assignment for P04 M2.")
    parser.add_argument("--m1-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--analysis-crs", default="EPSG:32650")
    parser.add_argument("--sample-spacing-m", type=float, default=5.0)
    parser.add_argument("--search-radius-m", type=float, default=35.0)
    parser.add_argument("--max-distance-m", type=float, default=20.0)
    parser.add_argument("--max-direction-delta-deg", type=float, default=35.0)
    parser.add_argument("--candidate-limit", type=int, default=5)
    parser.add_argument("--adjacent-transition-penalty", type=float, default=3.0)
    parser.add_argument("--unrelated-transition-penalty", type=float, default=30.0)
    parser.add_argument("--full-coverage", type=float, default=0.95)
    parser.add_argument("--max-gap-m", type=float, default=10.0)
    parser.add_argument("--selected-policy", choices=tuple(POLICIES), default="viterbi_all_lanes")
    return parser.parse_args()


def canonical_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def memberships(value: Any) -> set[str]:
    return {item for item in re.split(r"[,;|\s]+", canonical_text(value)) if item}


def sample_offsets(length: float, spacing: float) -> np.ndarray:
    count = max(2, int(math.ceil(max(length, 0.0) / spacing)) + 1)
    return np.linspace(0.0, max(length, 0.0), count)


def road_nodes(row: pd.Series) -> set[str]:
    values = {
        canonical_text(row.get("snode_id")),
        canonical_text(row.get("enode_id")),
        canonical_text(row.get("semantic_snode_id")),
        canonical_text(row.get("semantic_enode_id")),
    }
    return {value for value in values if value and value.lower() != "nan"}


def prepare_roads(roads: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    prepared = roads.copy().reset_index(drop=True)
    prepared["swsd_unit_id"] = prepared["swsd_unit_id"].map(canonical_text)
    prepared["patch_membership_set"] = prepared["all_patch_ids"].map(memberships)
    prepared["node_set"] = prepared.apply(road_nodes, axis=1)
    return prepared


def is_adjacent(road_a: str, road_b: str, nodes_by_road: dict[str, set[str]]) -> bool:
    if road_a == road_b:
        return True
    return bool(nodes_by_road.get(road_a, set()) & nodes_by_road.get(road_b, set()))


def point_candidates(
    point: Point,
    lane_tangent: tuple[float, float],
    patch_id: str,
    roads: gpd.GeoDataFrame,
    *,
    search_radius_m: float,
    max_distance_m: float,
    max_direction_delta_deg: float,
    candidate_limit: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    query = box(*point.buffer(search_radius_m).bounds)
    for candidate_index in roads.sindex.query(query):
        road = roads.iloc[int(candidate_index)]
        if patch_id not in road["patch_membership_set"]:
            continue
        projection = float(road.geometry.project(point))
        nearest = road.geometry.interpolate(projection)
        distance = float(point.distance(nearest))
        if distance > max_distance_m:
            continue
        road_tangent = tangent_vector(road.geometry, projection)
        direction_delta = swsd_direction_delta_deg(
            lane_tangent,
            road_tangent,
            int(road["direction"]) if not pd.isna(road["direction"]) else None,
        )
        if direction_delta > max_direction_delta_deg:
            continue
        candidates.append(
            {
                "road_id": road["swsd_unit_id"],
                "road_projection_m": projection,
                "distance_m": distance,
                "direction_delta_deg": float(direction_delta),
                "emission_score": distance + 0.10 * float(direction_delta),
            }
        )
    candidates.sort(key=lambda row: (row["emission_score"], row["road_id"]))
    return candidates[:candidate_limit]


def viterbi_path(
    candidates_by_sample: list[list[dict[str, Any]]],
    nodes_by_road: dict[str, set[str]],
    *,
    adjacent_penalty: float,
    unrelated_penalty: float,
) -> list[dict[str, Any] | None]:
    if not candidates_by_sample:
        return []
    states = [candidates if candidates else [None] for candidates in candidates_by_sample]
    costs: list[dict[int, float]] = []
    back: list[dict[int, int | None]] = []
    for sample_index, sample_states in enumerate(states):
        current_costs: dict[int, float] = {}
        current_back: dict[int, int | None] = {}
        for current_index, current in enumerate(sample_states):
            emission = float(current["emission_score"]) if current is not None else 20.0
            if sample_index == 0:
                current_costs[current_index] = emission
                current_back[current_index] = None
                continue
            best_cost = math.inf
            best_previous: int | None = None
            for previous_index, previous in enumerate(states[sample_index - 1]):
                transition = transition_cost(
                    previous,
                    current,
                    nodes_by_road,
                    adjacent_penalty=adjacent_penalty,
                    unrelated_penalty=unrelated_penalty,
                )
                candidate_cost = costs[-1][previous_index] + transition + emission
                if candidate_cost < best_cost:
                    best_cost = candidate_cost
                    best_previous = previous_index
            current_costs[current_index] = best_cost
            current_back[current_index] = best_previous
        costs.append(current_costs)
        back.append(current_back)
    selected_index = min(costs[-1], key=costs[-1].get)
    selected: list[dict[str, Any] | None] = [None] * len(states)
    for sample_index in range(len(states) - 1, -1, -1):
        selected[sample_index] = states[sample_index][selected_index]
        previous_index = back[sample_index][selected_index]
        if previous_index is None:
            break
        selected_index = previous_index
    return selected


def transition_cost(
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
    nodes_by_road: dict[str, set[str]],
    *,
    adjacent_penalty: float,
    unrelated_penalty: float,
) -> float:
    if previous is None and current is None:
        return 0.0
    if previous is None or current is None:
        return adjacent_penalty
    previous_id = str(previous["road_id"])
    current_id = str(current["road_id"])
    if previous_id == current_id:
        return 0.0
    if is_adjacent(previous_id, current_id, nodes_by_road):
        return adjacent_penalty
    return unrelated_penalty


def analyze_lane(
    lane: Any,
    roads: gpd.GeoDataFrame,
    nodes_by_road: dict[str, set[str]],
    args: argparse.Namespace,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    offsets = sample_offsets(float(lane.geometry.length), args.sample_spacing_m)
    candidates_by_sample: list[list[dict[str, Any]]] = []
    for offset in offsets:
        point = lane.geometry.interpolate(float(offset))
        candidates_by_sample.append(
            point_candidates(
                point,
                tangent_vector(lane.geometry, float(offset)),
                canonical_text(lane.source_patch_ids),
                roads,
                search_radius_m=args.search_radius_m,
                max_distance_m=args.max_distance_m,
                max_direction_delta_deg=args.max_direction_delta_deg,
                candidate_limit=args.candidate_limit,
            )
        )
    path = viterbi_path(
        candidates_by_sample,
        nodes_by_road,
        adjacent_penalty=args.adjacent_transition_penalty,
        unrelated_penalty=args.unrelated_transition_penalty,
    )
    sample_rows: list[dict[str, Any]] = []
    for sample_index, (offset, candidates, selected) in enumerate(
        zip(offsets, candidates_by_sample, path, strict=True)
    ):
        point = lane.geometry.interpolate(float(offset))
        top_margin = (
            float(candidates[1]["emission_score"] - candidates[0]["emission_score"])
            if len(candidates) > 1
            else (9999.0 if candidates else None)
        )
        sample_rows.append(
            {
                "lane_id": canonical_text(lane.lane_id),
                "source_patch_ids": canonical_text(lane.source_patch_ids),
                "lane_decision": canonical_text(lane.decision),
                "lane_owner_state": canonical_text(lane.owner_state),
                "width_state": canonical_text(lane.width_state),
                "sample_index": sample_index,
                "lane_offset_m": float(offset),
                "candidate_count": len(candidates),
                "top_score_margin": top_margin,
                "assigned_road_id": selected["road_id"] if selected is not None else "",
                "assigned_road_projection_m": selected["road_projection_m"] if selected is not None else None,
                "assigned_distance_m": selected["distance_m"] if selected is not None else None,
                "assigned_direction_delta_deg": selected["direction_delta_deg"] if selected is not None else None,
                "assignment_state": "locally_supported" if selected is not None else "no_local_swsd_fit",
                "geometry": point,
            }
        )
    segment_rows: list[dict[str, Any]] = []
    run_start = 0
    while run_start < len(path):
        road_id = path[run_start]["road_id"] if path[run_start] is not None else ""
        run_end = run_start
        while run_end + 1 < len(path):
            next_id = path[run_end + 1]["road_id"] if path[run_end + 1] is not None else ""
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
            road_geometry = roads.loc[roads["swsd_unit_id"].eq(road_id), "geometry"].iloc[0]
            projection_values = [
                float(road_geometry.project(lane.geometry.interpolate(source_start))),
                float(road_geometry.project(lane.geometry.interpolate(source_end))),
                *[
                    float(path[index]["road_projection_m"])
                    for index in range(run_start, run_end + 1)
                    if path[index] is not None
                ],
            ]
            segment_rows.append(
                {
                    "lane_id": canonical_text(lane.lane_id),
                    "source_patch_ids": canonical_text(lane.source_patch_ids),
                    "lane_decision": canonical_text(lane.decision),
                    "lane_owner_state": canonical_text(lane.owner_state),
                    "width_state": canonical_text(lane.width_state),
                    "swsd_unit_id": road_id,
                    "source_start_m": source_start,
                    "source_end_m": source_end,
                    "source_length_m": source_end - source_start,
                    "road_start_m": min(projection_values),
                    "road_end_m": max(projection_values),
                    "sample_count": run_end - run_start + 1,
                    "assignment_method": "local_swsd_viterbi",
                    "geometry": substring(lane.geometry, source_start, source_end),
                }
            )
        run_start = run_end + 1
    return sample_rows, segment_rows


def merge_intervals(intervals: list[tuple[float, float]], length: float) -> list[tuple[float, float]]:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        start = max(0.0, min(length, float(start)))
        end = max(0.0, min(length, float(end)))
        if not merged or start > merged[-1][1] + 1e-8:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return [(start, end) for start, end in merged]


def road_support(
    roads: gpd.GeoDataFrame,
    segments: gpd.GeoDataFrame,
    lane_ids: set[str],
    *,
    full_coverage: float,
    max_gap_m: float,
) -> pd.DataFrame:
    scoped = segments[segments["lane_id"].isin(lane_ids)]
    by_road = {road_id: frame for road_id, frame in scoped.groupby("swsd_unit_id")}
    rows: list[dict[str, Any]] = []
    for road in roads.itertuples():
        road_id = canonical_text(road.swsd_unit_id)
        road_length = float(road.geometry.length)
        source = by_road.get(road_id)
        intervals = [] if source is None else list(zip(source["road_start_m"], source["road_end_m"]))
        support = merge_intervals(intervals, road_length)
        support_length = sum(end - start for start, end in support)
        gaps: list[tuple[float, float]] = []
        cursor = 0.0
        for start, end in support:
            if start > cursor + 1e-8:
                gaps.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < road_length - 1e-8:
            gaps.append((cursor, road_length))
        coverage = support_length / road_length if road_length > 1e-8 else 0.0
        max_gap = max((end - start for start, end in gaps), default=0.0)
        if not support:
            state = "sd_only"
        elif coverage >= full_coverage and max_gap <= max_gap_m:
            state = "hp_supported"
        else:
            state = "partial_hp_supported"
        rows.append(
            {
                "swsd_unit_id": road_id,
                "road_length_m": road_length,
                "lane_segment_count": 0 if source is None else int(len(source)),
                "source_lane_count": 0 if source is None else int(source["lane_id"].nunique()),
                "support_interval_count": len(support),
                "gap_interval_count": len(gaps),
                "support_length_m": support_length,
                "support_coverage_ratio": coverage,
                "max_gap_m": max_gap,
                "support_state": state,
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    run_root = args.m1_run.expanduser().resolve()
    output_dir = args.output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=False)
    lanes = gpd.read_file(run_root / "p04_lane_decisions.gpkg", layer="lane_decisions").to_crs(
        args.analysis_crs
    )
    roads = prepare_roads(
        gpd.read_file(run_root / "p04_swsd_skeleton.gpkg", layer="road_sections").to_crs(
            args.analysis_crs
        )
    )
    lanes["lane_id"] = lanes["lane_id"].map(canonical_text)
    nodes_by_road = dict(zip(roads["swsd_unit_id"], roads["node_set"], strict=True))

    sample_rows: list[dict[str, Any]] = []
    segment_rows: list[dict[str, Any]] = []
    for lane in lanes.itertuples():
        lane_samples, lane_segments = analyze_lane(lane, roads, nodes_by_road, args)
        sample_rows.extend(lane_samples)
        segment_rows.extend(lane_segments)
    samples = gpd.GeoDataFrame(sample_rows, geometry="geometry", crs=args.analysis_crs)
    segments = gpd.GeoDataFrame(segment_rows, geometry="geometry", crs=args.analysis_crs)
    samples.to_file(
        output_dir / "local_lane_assignment.gpkg",
        layer="lane_samples",
        driver="GPKG",
        index=False,
    )
    segments.to_file(
        output_dir / "local_lane_assignment.gpkg",
        layer="lane_segments",
        driver="GPKG",
        mode="a",
        index=False,
    )

    policy_rows: list[dict[str, Any]] = []
    selected_metrics: pd.DataFrame | None = None
    for policy_name, predicate in POLICIES.items():
        lane_ids = {canonical_text(lane.lane_id) for lane in lanes.itertuples() if predicate(lane)}
        metrics = road_support(
            roads,
            segments,
            lane_ids,
            full_coverage=args.full_coverage,
            max_gap_m=args.max_gap_m,
        )
        counts = Counter(metrics["support_state"])
        policy_rows.append(
            {
                "policy": policy_name,
                "lane_count": len(lane_ids),
                "road_with_evidence": int(metrics["source_lane_count"].gt(0).sum()),
                "hp_supported": counts["hp_supported"],
                "partial_hp_supported": counts["partial_hp_supported"],
                "sd_only": counts["sd_only"],
                "conflict_retained": 0,
                "road_total": int(len(metrics)),
                "coverage_p50_evidence_roads": float(
                    metrics.loc[metrics["source_lane_count"].gt(0), "support_coverage_ratio"].median()
                ),
                "coverage_p90_evidence_roads": float(
                    metrics.loc[
                        metrics["source_lane_count"].gt(0), "support_coverage_ratio"
                    ].quantile(0.90)
                ),
            }
        )
        metrics.to_csv(
            output_dir / f"road_support_{policy_name}.csv", index=False, encoding="utf-8-sig"
        )
        if policy_name == args.selected_policy:
            selected_metrics = metrics
    policies = pd.DataFrame(policy_rows)
    policies.to_csv(output_dir / "policy_comparison.csv", index=False, encoding="utf-8-sig")
    if selected_metrics is None:
        raise AssertionError("selected policy was not evaluated")

    road_count_per_lane = segments.groupby("lane_id")["swsd_unit_id"].nunique()
    unmatched = samples["assignment_state"].eq("no_local_swsd_fit")
    state_counts = Counter(selected_metrics["support_state"])
    summary = {
        "analysis_crs": args.analysis_crs,
        "parameters": {
            key: value
            for key, value in vars(args).items()
            if key not in {"m1_run", "output_dir"}
        },
        "road_count": int(len(roads)),
        "lane_count": int(len(lanes)),
        "sample_count": int(len(samples)),
        "assigned_sample_count": int((~unmatched).sum()),
        "unmatched_sample_count": int(unmatched.sum()),
        "unmatched_sample_ratio": float(unmatched.mean()),
        "lane_segment_count": int(len(segments)),
        "lanes_with_local_assignment": int(segments["lane_id"].nunique()),
        "lanes_contributing_to_multiple_swsd_roads": int(road_count_per_lane.gt(1).sum()),
        "max_swsd_roads_per_lane": int(road_count_per_lane.max()),
        "transition_counts": {
            "same_or_single": int((road_count_per_lane <= 1).sum()),
            "multiple": int(road_count_per_lane.gt(1).sum()),
        },
        "policy_comparison": policy_rows,
        "selected_policy": {
            "name": args.selected_policy,
            "support_state_counts": {
                "hp_supported": int(state_counts["hp_supported"]),
                "partial_hp_supported": int(state_counts["partial_hp_supported"]),
                "sd_only": int(state_counts["sd_only"]),
                "conflict_retained": 0,
            },
            "road_conservation": int(sum(state_counts.values())) == int(len(roads)),
        },
        "interpretation": [
            "Original Lane identity is preserved; only evidence segments have a unique SWSD Road owner.",
            "Width, Boundary, direction-review and LaneTopo anomalies remain QA and do not create Road conflict.",
            "Viterbi parameters are single-Case POC candidates and require visual and multi-Case validation.",
        ],
    }
    (output_dir / "analysis_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
