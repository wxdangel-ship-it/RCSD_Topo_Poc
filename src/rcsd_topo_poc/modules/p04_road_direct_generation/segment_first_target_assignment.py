from __future__ import annotations

from dataclasses import dataclass
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

from .segment_first_skeleton import canonical_id


@dataclass(frozen=True)
class TargetAssignmentResult:
    assignments: gpd.GeoDataFrame
    rejections: gpd.GeoDataFrame
    audit: gpd.GeoDataFrame
    summary: dict[str, object]


def apply_target_segment_anchors(
    centers: gpd.GeoDataFrame,
    baseline_assignments: gpd.GeoDataFrame,
    baseline_rejections: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    anchors: gpd.GeoDataFrame,
    *,
    max_distance_m: float,
    max_angle_deg: float,
    run_id: str,
    protected_segment_ids: set[str] | None = None,
) -> TargetAssignmentResult:
    protected_segments = {
        canonical_id(value) for value in (protected_segment_ids or set())
    }
    if anchors.empty:
        return TargetAssignmentResult(
            baseline_assignments.copy(),
            baseline_rejections.copy(),
            _empty_audit(centers.crs),
            _summary(False, 0, 0, 0, 0, 0, 0),
        )

    anchor_lines = anchors.explode(index_parts=False).reset_index(drop=True)
    anchor_lines = anchor_lines[
        anchor_lines.geometry.notna()
        & ~anchor_lines.geometry.is_empty
        & anchor_lines.geom_type.eq("LineString")
    ].copy()
    if anchor_lines.empty:
        return TargetAssignmentResult(
            baseline_assignments.copy(),
            baseline_rejections.copy(),
            _empty_audit(centers.crs),
            _summary(False, 0, 0, 0, 0, 0, 0),
        )

    members = swsd_roads.copy()
    members["canonical_road_id"] = members["id"].map(canonical_id)
    members["canonical_segment_id"] = members["segmentid"].map(canonical_id)
    members_by_segment = {
        segment_id: group.copy()
        for segment_id, group in members.groupby("canonical_segment_id")
    }
    baseline_by_key = {
        str(row.patch_road_key): row
        for row in baseline_assignments.itertuples(index=False)
    }
    anchor_sindex = anchor_lines.sindex
    output_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    selected_keys: set[str] = set()
    confirmed = 0
    reassigned = 0
    promoted = 0
    ambiguous = 0
    protected = 0

    for center in centers.itertuples(index=False):
        key = str(center.patch_road_key)
        baseline = baseline_by_key.get(key)
        candidate = _target_candidate(
            center.geometry,
            anchor_lines,
            anchor_sindex,
            max_distance_m=max_distance_m,
            max_angle_deg=max_angle_deg,
            baseline_segment_id=(
                canonical_id(baseline.assigned_segment_id)
                if baseline is not None
                else ""
            ),
        )
        if candidate is None:
            if baseline is not None:
                output_rows.append(baseline._asdict())
            continue

        segment_id = str(candidate["segment_id"])
        baseline_segment = (
            canonical_id(baseline.assigned_segment_id)
            if baseline is not None
            else ""
        )
        if (
            baseline_segment in protected_segments
            and baseline_segment != segment_id
        ):
            output_rows.append(baseline._asdict())
            protected += 1
            continue
        member_id = _nearest_member_id(
            center.geometry,
            members_by_segment.get(segment_id),
        )
        if not member_id:
            if baseline is not None:
                output_rows.append(baseline._asdict())
            continue

        if baseline_segment == segment_id:
            state = "target_anchor_confirmed"
            confirmed += 1
        elif baseline is not None:
            state = "target_anchor_reassigned"
            reassigned += 1
        else:
            state = "target_anchor_promoted"
            promoted += 1
        if bool(candidate["ambiguous"]):
            ambiguous += 1

        row = center._asdict()
        row.update(
            {
                "run_id": run_id,
                "assigned_segment_id": segment_id,
                "target_swsd_road_id": member_id,
                "assignment_distance_m": float(candidate["distance_m"]),
                "assignment_angle_deg": float(candidate["angle_deg"]),
                "assignment_score": float(candidate["score"]),
                "assignment_margin": candidate["margin"],
                "carrier_role": (
                    str(baseline.carrier_role)
                    if baseline is not None
                    and baseline_segment == segment_id
                    and str(baseline.carrier_role) == "local_connector"
                    else "directional_corridor"
                ),
                "takeover_eligible": True,
                "assignment_state": state,
                "assignment_source": "t06_rcsd_segment_anchor",
                "target_anchor_source": str(candidate["anchor_source"]),
                "reason_codes": (
                    "target_anchor_ambiguous_deterministic_review"
                    if candidate["ambiguous"]
                    else "target_segment_anchor_supported"
                ),
            }
        )
        output_rows.append(row)
        selected_keys.add(key)
        audit_rows.append(
            {
                "run_id": run_id,
                "patch_road_key": key,
                "baseline_segment_id": baseline_segment,
                "assigned_segment_id": segment_id,
                "target_swsd_road_id": member_id,
                "assignment_state": state,
                "assignment_distance_m": float(candidate["distance_m"]),
                "assignment_angle_deg": float(candidate["angle_deg"]),
                "assignment_margin": candidate["margin"],
                "ambiguous_review": bool(candidate["ambiguous"]),
                "geometry_source": "patch_road_center",
                "geometry": center.geometry,
            }
        )

    assignments = gpd.GeoDataFrame(
        output_rows,
        geometry="geometry",
        crs=centers.crs,
    ).sort_values("patch_road_key", kind="stable").reset_index(drop=True)
    rejections = baseline_rejections[
        ~baseline_rejections["patch_road_key"].astype(str).isin(selected_keys)
    ].copy().reset_index(drop=True)
    audit = (
        gpd.GeoDataFrame(audit_rows, geometry="geometry", crs=centers.crs)
        if audit_rows
        else _empty_audit(centers.crs)
    )
    return TargetAssignmentResult(
        assignments,
        rejections,
        audit,
        _summary(
            True,
            confirmed,
            reassigned,
            promoted,
            ambiguous,
            int(audit["assigned_segment_id"].nunique()),
            protected,
        ),
    )


def _target_candidate(
    geometry: LineString,
    anchors: gpd.GeoDataFrame,
    sindex: object,
    *,
    max_distance_m: float,
    max_angle_deg: float,
    baseline_segment_id: str,
) -> dict[str, object] | None:
    by_segment: dict[str, tuple[float, float, float, pd.Series]] = {}
    for index in sindex.query(geometry.buffer(max_distance_m)):
        anchor = anchors.iloc[int(index)]
        distance = _sample_distance(geometry, anchor.geometry)
        angle = _local_angle_delta(geometry, anchor.geometry)
        if distance > max_distance_m or angle > max_angle_deg:
            continue
        score = distance + angle * 0.08
        segment_id = canonical_id(anchor["segment_id"])
        item = (score, distance, angle, anchor)
        current = by_segment.get(segment_id)
        if current is None or item[:3] < current[:3]:
            by_segment[segment_id] = item
    if not by_segment:
        return None
    ordered = sorted(
        (
            score,
            distance,
            angle,
            segment_id,
            anchor,
        )
        for segment_id, (score, distance, angle, anchor) in by_segment.items()
    )
    best = ordered[0]
    if baseline_segment_id:
        baseline_candidates = [item for item in ordered if item[3] == baseline_segment_id]
        if baseline_candidates and baseline_candidates[0][0] <= best[0] + 2.0:
            best = baseline_candidates[0]
    other_scores = [item[0] for item in ordered if item[3] != best[3]]
    margin = min(other_scores) - best[0] if other_scores else None
    return {
        "score": best[0],
        "distance_m": best[1],
        "angle_deg": best[2],
        "segment_id": best[3],
        "anchor_source": best[4].get("anchor_source", "t06_replaceability_geometry"),
        "margin": margin,
        "ambiguous": margin is not None and margin < 2.0,
    }


def _nearest_member_id(
    geometry: LineString,
    members: gpd.GeoDataFrame | None,
) -> str:
    if members is None or members.empty:
        return ""
    candidates = []
    for member in members.itertuples(index=False):
        distance = _sample_distance(geometry, member.geometry)
        angle = _local_angle_delta(geometry, member.geometry)
        candidates.append(
            (distance + angle * 0.08, distance, angle, member.canonical_road_id)
        )
    return str(min(candidates)[3])


def _sample_distance(source: LineString, target: LineString) -> float:
    samples = [
        source.interpolate(value, normalized=True)
        for value in np.linspace(0.1, 0.9, 5)
    ]
    return float(np.median([point.distance(target) for point in samples]))


def _local_angle_delta(source: LineString, target: LineString) -> float:
    source_bearing = _bearing_between(
        source.interpolate(0.4, normalized=True),
        source.interpolate(0.6, normalized=True),
    )
    midpoint = source.interpolate(0.5, normalized=True)
    measure = float(target.project(midpoint))
    delta = min(10.0, max(1.0, float(target.length) * 0.02))
    start = target.interpolate(max(0.0, measure - delta))
    end = target.interpolate(min(float(target.length), measure + delta))
    target_bearing = _bearing_between(start, end)
    difference = abs(source_bearing - target_bearing) % 180.0
    return min(difference, 180.0 - difference)


def _bearing_between(start: object, end: object) -> float:
    return math.degrees(math.atan2(end.y - start.y, end.x - start.x)) % 180.0


def _empty_audit(crs: object) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "run_id": pd.Series(dtype=str),
            "patch_road_key": pd.Series(dtype=str),
            "baseline_segment_id": pd.Series(dtype=str),
            "assigned_segment_id": pd.Series(dtype=str),
            "target_swsd_road_id": pd.Series(dtype=str),
            "assignment_state": pd.Series(dtype=str),
            "assignment_distance_m": pd.Series(dtype=float),
            "assignment_angle_deg": pd.Series(dtype=float),
            "assignment_margin": pd.Series(dtype=float),
            "ambiguous_review": pd.Series(dtype=bool),
            "geometry_source": pd.Series(dtype=str),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


def _summary(
    enabled: bool,
    confirmed: int,
    reassigned: int,
    promoted: int,
    ambiguous: int,
    segment_count: int,
    protected: int,
) -> dict[str, object]:
    return {
        "anchor_enabled": enabled,
        "confirmed_count": confirmed,
        "reassigned_count": reassigned,
        "promoted_count": promoted,
        "ambiguous_review_count": ambiguous,
        "anchored_segment_count": segment_count,
        "protected_assignment_count": protected,
    }


__all__ = ["TargetAssignmentResult", "apply_target_segment_anchors"]
