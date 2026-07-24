from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

from .config import MilestoneOneConfig
from .geometry import (
    canonical_id,
    dominant_id,
    quantile_or_none,
    sample_distances,
    swsd_direction_delta_deg,
    tangent_vector,
    undirected_angle_deg,
)


@dataclass(frozen=True)
class AssignmentResult:
    candidates: gpd.GeoDataFrame
    boundary_samples: gpd.GeoDataFrame
    decisions: gpd.GeoDataFrame
    summary: dict[str, Any]


def build_lane_assignments(
    lanes: gpd.GeoDataFrame,
    boundaries: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    drivezones: gpd.GeoDataFrame,
    divstrips: gpd.GeoDataFrame,
    lane_next: pd.DataFrame,
    reference_lanes: gpd.GeoDataFrame,
    *,
    config: MilestoneOneConfig,
) -> AssignmentResult:
    prepared_lanes = lanes.copy()
    prepared_lanes["lane_id"] = prepared_lanes["Id"].map(canonical_id)
    prepared_lanes["old_road_id"] = prepared_lanes["RoadId"].map(canonical_id)
    prepared_boundaries = boundaries.copy()
    prepared_boundaries["boundary_id"] = prepared_boundaries["Id"].map(canonical_id)

    topology = _topology_metrics(lane_next, reference_lanes)
    swsd_index = swsd_roads.sindex
    boundary_by_patch = {
        patch_id: frame.reset_index(drop=True)
        for patch_id, frame in prepared_boundaries.groupby("patch_id")
    }
    boundary_indexes = {patch_id: frame.sindex for patch_id, frame in boundary_by_patch.items()}
    drivezone_by_patch = _geometry_union_by_patch(drivezones)
    divstrip_by_patch = _geometry_union_by_patch(divstrips)

    candidate_records: list[dict[str, Any]] = []
    sample_records: list[dict[str, Any]] = []
    decision_records: list[dict[str, Any]] = []

    for lane in prepared_lanes.itertuples():
        lane_samples = sample_distances(
            lane.geometry,
            spacing_m=config.lane_sample_spacing_m,
            min_samples=config.lane_min_samples,
            max_samples=config.lane_max_samples,
        )
        owner_metrics = _owner_candidates(
            lane.geometry,
            lane.patch_id,
            lane_samples,
            swsd_roads,
            swsd_index,
            config=config,
        )
        top = owner_metrics[0] if owner_metrics else None
        second = owner_metrics[1] if len(owner_metrics) > 1 else None
        owner_margin = (
            float(second["owner_score"] - top["owner_score"])
            if top is not None and second is not None
            else (9999.0 if top is not None else None)
        )
        owner_state, owner_reasons = classify_owner(top, owner_margin, config=config)

        for rank, metrics in enumerate(owner_metrics[: config.owner_candidate_limit], start=1):
            candidate_records.append(
                {
                    "run_id": config.run_id,
                    "source_patch_ids": lane.patch_id,
                    "source_object_type": "Lane",
                    "source_object_ids": lane.lane_id,
                    "swsd_unit_id": metrics["swsd_unit_id"],
                    "candidate_rank": rank,
                    **metrics,
                    "owner_score_margin": owner_margin if rank == 1 else None,
                    "decision": owner_state if rank == 1 else "candidate",
                    "reason_codes": ";".join(owner_reasons) if rank == 1 else "lower_rank_candidate",
                    "evidence_state": "owner_candidate",
                    "input_manifest_ref": "p04_input_manifest.json",
                    "evidence_quality_state": _evidence_quality_state(owner_state),
                    "geometry": lane.geometry,
                }
            )

        owner_geometry = top["road_geometry"] if top is not None else None
        width = _boundary_width_evidence(
            lane,
            lane_samples,
            boundary_by_patch.get(lane.patch_id),
            boundary_indexes.get(lane.patch_id),
            drivezone_by_patch.get(lane.patch_id),
            divstrip_by_patch.get(lane.patch_id),
            owner_geometry,
            config=config,
        )
        sample_records.extend(width.pop("sample_records"))
        width_state, width_reasons = classify_width(width, config=config)
        drivezone_coverage = float(width["drivezone_coverage"])
        decision, combined_reasons = combine_decision(
            owner_state,
            owner_reasons,
            width_state,
            width_reasons,
            drivezone_coverage=drivezone_coverage,
            config=config,
        )
        topo = topology.get(lane.lane_id, {})
        decision_records.append(
            {
                "run_id": config.run_id,
                "source_patch_ids": lane.patch_id,
                "source_object_type": "Lane",
                "source_object_ids": lane.lane_id,
                "lane_id": lane.lane_id,
                "old_road_id": lane.old_road_id,
                "swsd_unit_id": top["swsd_unit_id"] if top is not None else None,
                "decision": decision,
                "reason_codes": ";".join(combined_reasons),
                "evidence_state": "lane_evidence_assignment",
                "input_manifest_ref": "p04_input_manifest.json",
                "evidence_quality_state": _evidence_quality_state(decision),
                "owner_state": owner_state,
                "owner_candidate_count": len(owner_metrics),
                "owner_score": top["owner_score"] if top is not None else None,
                "owner_score_margin": owner_margin,
                "owner_distance_p50_m": top["distance_p50_m"] if top is not None else None,
                "owner_distance_p90_m": top["distance_p90_m"] if top is not None else None,
                "owner_direction_delta_deg": top["direction_delta_deg"] if top is not None else None,
                "width_state": width_state,
                "left_boundary_id": width["left_boundary_id"],
                "right_boundary_id": width["right_boundary_id"],
                "left_boundary_ids": width["left_boundary_ids"],
                "right_boundary_ids": width["right_boundary_ids"],
                "inferred_lane_width_m": width["width_median_m"],
                "width_sample_coverage": width["bilateral_coverage"],
                "left_boundary_coverage": width["left_coverage"],
                "right_boundary_coverage": width["right_coverage"],
                "width_p10_m": width["width_p10_m"],
                "width_median_m": width["width_median_m"],
                "width_p90_m": width["width_p90_m"],
                "width_variation_m": width["width_variation_m"],
                "drivezone_coverage": drivezone_coverage,
                "divstrip_overlap_ratio": width["divstrip_overlap_ratio"],
                "boundary_corridor_check": "accepted_owner_35m" if owner_state == "accepted" else "local_geometry_only",
                "lane_next_in_count": topo.get("lane_next_in_count", 0),
                "lane_next_out_count": topo.get("lane_next_out_count", 0),
                "reference_from_count": topo.get("reference_from_count", 0),
                "reference_to_count": topo.get("reference_to_count", 0),
                "reference_flow_sum": topo.get("reference_flow_sum", 0.0),
                "is_intersection_in_lane": bool(getattr(lane, "IsIntersectionInLane", False)),
                "is_intersection_out_lane": bool(getattr(lane, "IsIntersectionOutLane", False)),
                "geometry": lane.geometry,
            }
        )

    candidates = gpd.GeoDataFrame(candidate_records, geometry="geometry", crs=lanes.crs)
    if not candidates.empty and "road_geometry" in candidates.columns:
        candidates = candidates.drop(columns=["road_geometry"])
    boundary_samples = gpd.GeoDataFrame(sample_records, geometry="geometry", crs=lanes.crs)
    decisions = gpd.GeoDataFrame(decision_records, geometry="geometry", crs=lanes.crs)
    summary = _assignment_summary(decisions, candidates)
    return AssignmentResult(
        candidates=candidates,
        boundary_samples=boundary_samples,
        decisions=decisions,
        summary=summary,
    )


def classify_owner(
    top: dict[str, Any] | None,
    margin: float | None,
    *,
    config: MilestoneOneConfig,
) -> tuple[str, list[str]]:
    if top is None:
        return "insufficient_evidence", ["no_swsd_owner_candidate"]
    reasons: list[str] = []
    p90 = float(top["distance_p90_m"])
    direction = float(top["direction_delta_deg"])
    if p90 > config.owner_review_max_p90_distance_m:
        return "insufficient_evidence", ["owner_distance_beyond_review_radius"]
    if direction > config.owner_review_max_direction_delta_deg:
        return "insufficient_evidence", ["owner_direction_beyond_review_angle"]
    if p90 > config.owner_max_p90_distance_m:
        reasons.append("owner_distance_requires_review")
    if direction > config.owner_max_direction_delta_deg:
        reasons.append("owner_direction_requires_review")
    if margin is None or margin < config.owner_min_score_margin:
        reasons.append("owner_score_margin_below_min")
    if reasons:
        return "review_required", reasons
    return "accepted", ["owner_unique_supported"]


def classify_width(
    evidence: dict[str, Any],
    *,
    config: MilestoneOneConfig,
) -> tuple[str, list[str]]:
    coverage = float(evidence["bilateral_coverage"])
    median = evidence["width_median_m"]
    variation = evidence["width_variation_m"]
    if median is None or coverage < config.width_min_review_coverage:
        return "insufficient_evidence", ["boundary_bilateral_insufficient"]
    if coverage < config.width_min_bilateral_coverage:
        return "partial", ["boundary_bilateral_partial"]
    if median < config.width_narrow_candidate_m:
        return "narrow_candidate", ["width_narrow_candidate"]
    if median > config.width_wide_candidate_m:
        return "wide_or_boundary_gap", ["width_wide_or_boundary_gap"]
    if variation is not None and variation > config.width_max_p90_p10_variation_m:
        return "unstable", ["width_unstable"]
    return "nominal", ["width_nominal"]


def combine_decision(
    owner_state: str,
    owner_reasons: list[str],
    width_state: str,
    width_reasons: list[str],
    *,
    drivezone_coverage: float,
    config: MilestoneOneConfig,
) -> tuple[str, list[str]]:
    reasons = [*owner_reasons, *width_reasons]
    if drivezone_coverage < config.drivezone_min_coverage:
        reasons.append("lane_outside_drivezone_fix")
    if owner_state == "insufficient_evidence" or width_state == "insufficient_evidence":
        return "insufficient_evidence", reasons
    if owner_state == "review_required" or width_state != "nominal":
        return "review_required", reasons
    if drivezone_coverage < config.drivezone_min_coverage:
        return "review_required", reasons
    return "accepted", reasons


def _owner_candidates(
    lane_geometry: Any,
    patch_id: str,
    lane_samples: tuple[float, ...],
    swsd_roads: gpd.GeoDataFrame,
    swsd_index: Any,
    *,
    config: MilestoneOneConfig,
) -> list[dict[str, Any]]:
    query_geometry = box(*lane_geometry.buffer(config.owner_search_radius_m).bounds)
    candidate_indexes = swsd_index.query(query_geometry)
    records: list[dict[str, Any]] = []
    for candidate_index in candidate_indexes:
        road = swsd_roads.iloc[int(candidate_index)]
        membership = road["patch_membership"]
        if patch_id not in membership:
            continue
        distances: list[float] = []
        direction_deltas: list[float] = []
        for lane_distance in lane_samples:
            point = lane_geometry.interpolate(lane_distance)
            road_distance = float(road.geometry.project(point))
            distances.append(float(point.distance(road.geometry)))
            lane_tangent = tangent_vector(lane_geometry, lane_distance)
            road_tangent = tangent_vector(road.geometry, road_distance)
            direction_deltas.append(
                swsd_direction_delta_deg(lane_tangent, road_tangent, _coerce_int(road.get("direction")))
            )
        distance_p50 = float(np.median(distances))
        distance_p90 = float(np.quantile(distances, 0.9))
        direction_delta = float(np.median(direction_deltas))
        score = distance_p50 + 0.25 * distance_p90 + 0.10 * direction_delta
        records.append(
            {
                "swsd_unit_id": road["swsd_unit_id"],
                "owner_score": score,
                "distance_p50_m": distance_p50,
                "distance_p90_m": distance_p90,
                "direction_delta_deg": direction_delta,
                "swsd_direction": _coerce_int(road.get("direction")),
                "road_geometry": road.geometry,
            }
        )
    records.sort(key=lambda row: (row["owner_score"], row["swsd_unit_id"]))
    return records


def _boundary_width_evidence(
    lane: Any,
    lane_samples: tuple[float, ...],
    boundaries: gpd.GeoDataFrame | None,
    boundary_index: Any,
    drivezone: Any,
    divstrip: Any,
    owner_geometry: Any,
    *,
    config: MilestoneOneConfig,
) -> dict[str, Any]:
    left_ids: list[str] = []
    right_ids: list[str] = []
    widths: list[float] = []
    drivezone_hits = 0
    sample_records: list[dict[str, Any]] = []
    for sample_index, lane_distance in enumerate(lane_samples):
        point = lane.geometry.interpolate(lane_distance)
        lane_tangent = tangent_vector(lane.geometry, lane_distance)
        best: dict[str, tuple[float, str, float] | None] = {"left": None, "right": None}
        if boundaries is not None and boundary_index is not None:
            search = box(*point.buffer(config.boundary_search_radius_m).bounds)
            for candidate_index in boundary_index.query(search):
                boundary = boundaries.iloc[int(candidate_index)]
                projected = float(boundary.geometry.project(point))
                nearest = boundary.geometry.interpolate(projected)
                distance = float(point.distance(nearest))
                if distance < 0.05 or distance > config.boundary_search_radius_m:
                    continue
                boundary_tangent = tangent_vector(boundary.geometry, projected)
                direction_delta = undirected_angle_deg(lane_tangent, boundary_tangent)
                if direction_delta > config.boundary_max_direction_delta_deg:
                    continue
                if owner_geometry is not None and nearest.distance(owner_geometry) > config.boundary_owner_corridor_radius_m:
                    continue
                cross = lane_tangent[0] * (nearest.y - point.y) - lane_tangent[1] * (nearest.x - point.x)
                side = "left" if cross > 0 else "right"
                candidate = (distance, boundary["boundary_id"], direction_delta)
                if best[side] is None or candidate[0] < best[side][0]:
                    best[side] = candidate
        left = best["left"]
        right = best["right"]
        if left is not None:
            left_ids.append(left[1])
        if right is not None:
            right_ids.append(right[1])
        width = None
        if left is not None and right is not None:
            width = float(left[0] + right[0])
            widths.append(width)
        inside_drivezone = bool(drivezone is not None and drivezone.buffer(0.05).covers(point))
        drivezone_hits += int(inside_drivezone)
        inside_divstrip = bool(divstrip is not None and divstrip.covers(point))
        sample_records.append(
            {
                "run_id": config.run_id,
                "source_patch_ids": lane.patch_id,
                "source_object_type": "LaneBoundarySample",
                "source_object_ids": lane.lane_id,
                "lane_id": lane.lane_id,
                "sample_index": sample_index,
                "sample_offset_m": lane_distance,
                "left_boundary_id": left[1] if left is not None else None,
                "right_boundary_id": right[1] if right is not None else None,
                "left_distance_m": left[0] if left is not None else None,
                "right_distance_m": right[0] if right is not None else None,
                "left_direction_delta_deg": left[2] if left is not None else None,
                "right_direction_delta_deg": right[2] if right is not None else None,
                "inferred_width_m": width,
                "inside_drivezone_fix": inside_drivezone,
                "inside_divstripzone_fix": inside_divstrip,
                "swsd_unit_id": None,
                "decision": "observed_sample",
                "reason_codes": "bilateral" if width is not None else "unilateral_or_missing",
                "evidence_state": "boundary_projection",
                "input_manifest_ref": "p04_input_manifest.json",
                "evidence_quality_state": "usable" if width is not None else "insufficient",
                "geometry": point,
            }
        )
    width_p10 = quantile_or_none(widths, 0.1)
    width_median = quantile_or_none(widths, 0.5)
    width_p90 = quantile_or_none(widths, 0.9)
    divstrip_overlap = 0.0
    if divstrip is not None and lane.geometry.length > 0:
        divstrip_overlap = float(lane.geometry.intersection(divstrip).length / lane.geometry.length)
    return {
        "left_boundary_id": dominant_id(left_ids),
        "right_boundary_id": dominant_id(right_ids),
        "left_boundary_ids": ",".join(sorted(set(left_ids))),
        "right_boundary_ids": ",".join(sorted(set(right_ids))),
        "left_coverage": len(left_ids) / len(lane_samples),
        "right_coverage": len(right_ids) / len(lane_samples),
        "bilateral_coverage": len(widths) / len(lane_samples),
        "width_p10_m": width_p10,
        "width_median_m": width_median,
        "width_p90_m": width_p90,
        "width_variation_m": (
            float(width_p90 - width_p10) if width_p10 is not None and width_p90 is not None else None
        ),
        "drivezone_coverage": drivezone_hits / len(lane_samples),
        "divstrip_overlap_ratio": divstrip_overlap,
        "sample_records": sample_records,
    }


def _topology_metrics(
    lane_next: pd.DataFrame,
    reference_lanes: gpd.GeoDataFrame,
) -> dict[str, dict[str, Any]]:
    metrics: dict[str, dict[str, Any]] = {}

    def ensure(lane_id: str | None) -> dict[str, Any] | None:
        if lane_id is None:
            return None
        return metrics.setdefault(
            lane_id,
            {
                "lane_next_in_count": 0,
                "lane_next_out_count": 0,
                "reference_from_count": 0,
                "reference_to_count": 0,
                "reference_flow_sum": 0.0,
            },
        )

    for row in lane_next.itertuples():
        source = ensure(canonical_id(row.LaneId))
        target = ensure(canonical_id(row.NextLaneId))
        if source is not None:
            source["lane_next_out_count"] += 1
        if target is not None:
            target["lane_next_in_count"] += 1
    for row in reference_lanes.itertuples():
        source = ensure(canonical_id(row.FromLaneId))
        target = ensure(canonical_id(row.ToLaneId))
        flow = _coerce_float(getattr(row, "FlowNum", 0.0))
        if source is not None:
            source["reference_from_count"] += 1
            source["reference_flow_sum"] += flow
        if target is not None:
            target["reference_to_count"] += 1
            target["reference_flow_sum"] += flow
    return metrics


def _geometry_union_by_patch(frame: gpd.GeoDataFrame) -> dict[str, Any]:
    return {
        patch_id: group.geometry.union_all()
        for patch_id, group in frame.groupby("patch_id")
        if not group.empty
    }


def _assignment_summary(
    decisions: gpd.GeoDataFrame,
    candidates: gpd.GeoDataFrame,
) -> dict[str, Any]:
    accepted = decisions[decisions["decision"] == "accepted"]
    missing_accepted_owner = int(accepted["swsd_unit_id"].isna().sum())
    return {
        "lane_count": len(decisions),
        "decision_counts": decisions["decision"].value_counts(dropna=False).to_dict(),
        "owner_state_counts": decisions["owner_state"].value_counts(dropna=False).to_dict(),
        "width_state_counts": decisions["width_state"].value_counts(dropna=False).to_dict(),
        "accepted_lane_count": len(accepted),
        "accepted_missing_owner_count": missing_accepted_owner,
        "candidate_row_count": len(candidates),
        "bilateral_full_coverage_count": int((decisions["width_sample_coverage"] == 1.0).sum()),
        "bilateral_insufficient_count": int(
            (decisions["width_state"] == "insufficient_evidence").sum()
        ),
        "narrow_candidate_count": int((decisions["width_state"] == "narrow_candidate").sum()),
        "wide_or_boundary_gap_count": int(
            (decisions["width_state"] == "wide_or_boundary_gap").sum()
        ),
        "unstable_width_count": int((decisions["width_state"] == "unstable").sum()),
        "owner_uniqueness_gate_pass": missing_accepted_owner == 0,
        "decision_coverage_gate_pass": bool(decisions["decision"].notna().all()),
    }


def _evidence_quality_state(decision: str) -> str:
    if decision == "accepted":
        return "usable"
    if decision == "review_required":
        return "review"
    return "insufficient"


def _coerce_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float:
    if value is None or pd.isna(value):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = [
    "AssignmentResult",
    "build_lane_assignments",
    "classify_owner",
    "classify_width",
    "combine_decision",
]
