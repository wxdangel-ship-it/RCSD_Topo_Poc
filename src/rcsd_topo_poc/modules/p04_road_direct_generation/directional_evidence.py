from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, substring, unary_union

from .directional_config import DirectionalRoadV2Config
from .geometry import canonical_id, tangent_vector


@dataclass(frozen=True)
class DirectionalEvidenceResult:
    directional_units: gpd.GeoDataFrame
    lane_segments: gpd.GeoDataFrame
    lane_group_members: gpd.GeoDataFrame
    anchors: gpd.GeoDataFrame
    cross_direction_quality_audit: gpd.GeoDataFrame
    support_intervals: gpd.GeoDataFrame
    summary: dict[str, Any]


def build_directional_evidence(
    parent_roads: gpd.GeoDataFrame,
    lane_segments: gpd.GeoDataFrame,
    lane_decisions: gpd.GeoDataFrame,
    lane_boundaries: gpd.GeoDataFrame,
    m2_candidates: gpd.GeoDataFrame,
    *,
    config: DirectionalRoadV2Config,
) -> DirectionalEvidenceResult:
    roads = parent_roads.copy().reset_index(drop=True)
    roads["swsd_unit_id"] = roads["swsd_unit_id"].map(canonical_id)
    parent_by_id = roads.set_index("swsd_unit_id", drop=False)
    m2_state = {
        canonical_id(row.swsd_unit_id): str(row.support_state)
        for row in m2_candidates.itertuples(index=False)
    }

    decisions = lane_decisions.copy()
    decisions["lane_id"] = decisions["lane_id"].map(canonical_id)
    decision_columns = [
        "lane_id",
        "left_boundary_ids",
        "right_boundary_ids",
        "left_boundary_id",
        "right_boundary_id",
        "width_median_m",
        "inferred_lane_width_m",
        "width_state",
    ]
    decision_columns = [column for column in decision_columns if column in decisions.columns]
    segments = lane_segments.copy().reset_index(drop=True)
    segments["lane_id"] = segments["lane_id"].map(canonical_id)
    segments["swsd_unit_id"] = segments["swsd_unit_id"].map(canonical_id)
    decision_columns = [
        column
        for column in decision_columns
        if column == "lane_id" or column not in segments.columns
    ]
    segments = segments.merge(
        decisions[decision_columns].drop_duplicates("lane_id"),
        on="lane_id",
        how="left",
    )
    segments["travel_side"] = segments.apply(
        lambda row: _travel_side(row.geometry, parent_by_id.loc[row.swsd_unit_id].geometry),
        axis=1,
    )
    segments["hard_geometry_eligible"] = (
        segments["evidence_quality_state"].astype(str)
        == config.hard_evidence_quality_state
    )

    boundaries = _prepare_boundaries(lane_boundaries)
    cross_direction_quality_audit = _cross_direction_quality_audit(
        roads,
        segments,
        boundaries,
        config=config,
    )
    collapsed_parent_ids = set(
        cross_direction_quality_audit.loc[
            ~cross_direction_quality_audit["anchor_gate_pass"].astype(bool),
            "parent_swsd_unit_id",
        ].astype(str)
    ) if not cross_direction_quality_audit.empty else set()
    segments["directional_geometry_quality_state"] = np.where(
        segments["hard_geometry_eligible"], "eligible", "upstream_quality_not_hard"
    )
    segments["directional_geometry_reason_codes"] = np.where(
        segments["hard_geometry_eligible"], "", "upstream_quality_not_hard_geometry"
    )
    collapse_mask = (
        segments["swsd_unit_id"].astype(str).isin(collapsed_parent_ids)
        & segments["hard_geometry_eligible"]
    )
    segments.loc[collapse_mask, "hard_geometry_eligible"] = False
    segments.loc[collapse_mask, "directional_geometry_quality_state"] = (
        "cross_direction_collapse_review"
    )
    segments.loc[collapse_mask, "directional_geometry_reason_codes"] = (
        "cross_direction_anchor_separation_below_width_relative_threshold"
    )

    hard_by_parent = {
        str(road_id): frame.copy()
        for road_id, frame in segments[segments["hard_geometry_eligible"]].groupby(
            "swsd_unit_id"
        )
    }
    unit_rows: list[dict[str, Any]] = []
    for road in roads.itertuples(index=False):
        parent_id = str(road.swsd_unit_id)
        original_direction = _coerce_int(getattr(road, "direction", None))
        has_hard_evidence = parent_id in hard_by_parent
        if has_hard_evidence and original_direction in {0, 1}:
            sides = ("forward", "reverse")
        elif has_hard_evidence and original_direction == 3:
            sides = ("reverse",)
        elif has_hard_evidence and original_direction == 2:
            sides = ("forward",)
        else:
            sides = ("sd_parent",)
        base = {
            key: value
            for key, value in road._asdict().items()
            if key != "geometry" and not key.startswith("_")
        }
        for side in sides:
            child_id = parent_id if side == "sd_parent" else f"{parent_id}:{side}"
            reverse = side == "reverse"
            unit_rows.append(
                {
                    **base,
                    "run_id": config.run_id,
                    "directional_road_id": child_id,
                    "parent_swsd_unit_id": parent_id,
                    "travel_side": side,
                    "road_representation": (
                        "sd_only_parent" if side == "sd_parent" else "directional_child"
                    ),
                    "original_direction": original_direction,
                    "direction": original_direction if side == "sd_parent" else 2,
                    "snode_id": _pick_endpoint(base, "enode_id", "enodeid")
                    if reverse
                    else _pick_endpoint(base, "snode_id", "snodeid"),
                    "enode_id": _pick_endpoint(base, "snode_id", "snodeid")
                    if reverse
                    else _pick_endpoint(base, "enode_id", "enodeid"),
                    "semantic_snode_id": _pick_endpoint(
                        base, "semantic_enode_id", "enode_id", "enodeid"
                    )
                    if reverse
                    else _pick_endpoint(
                        base, "semantic_snode_id", "snode_id", "snodeid"
                    ),
                    "semantic_enode_id": _pick_endpoint(
                        base, "semantic_snode_id", "snode_id", "snodeid"
                    )
                    if reverse
                    else _pick_endpoint(
                        base, "semantic_enode_id", "enode_id", "enodeid"
                    ),
                    "parent_support_state_m2": m2_state.get(parent_id, "unknown"),
                    "source_object_type": "SWSDRoad+DirectionalLaneGroup",
                    "source_object_ids": parent_id,
                    "decision": "directional_v2_candidate",
                    "reason_codes": (
                        "cross_direction_evidence_collapse_reverted_to_swsd_parent"
                        if side == "sd_parent" and parent_id in collapsed_parent_ids
                        else "pure_swsd_no_usable_evidence"
                        if side == "sd_parent"
                        else "swsd_directional_instantiation"
                    ),
                    "evidence_state": "directional_semantic_unit",
                    "input_manifest_ref": "p04_input_manifest.json",
                    "geometry": road.geometry,
                }
            )
    units = gpd.GeoDataFrame(unit_rows, geometry="geometry", crs=roads.crs)
    child_id_by_parent_side = {
        (str(row.parent_swsd_unit_id), str(row.travel_side)): str(row.directional_road_id)
        for row in units.itertuples(index=False)
    }
    segments["directional_road_id"] = segments.apply(
        lambda row: child_id_by_parent_side.get(
            (str(row.swsd_unit_id), str(row.travel_side)),
            str(row.swsd_unit_id)
            if str(row.swsd_unit_id) in collapsed_parent_ids
            else "",
        ),
        axis=1,
    )

    member_rows: list[dict[str, Any]] = []
    anchor_rows: list[dict[str, Any]] = []
    for unit in units.itertuples(index=False):
        child_id = str(unit.directional_road_id)
        if str(unit.travel_side) == "sd_parent":
            if str(unit.parent_swsd_unit_id) in collapsed_parent_ids:
                member_rows.extend(
                    _topology_only_member_rows(
                        segments[
                            segments["swsd_unit_id"].astype(str)
                            == str(unit.parent_swsd_unit_id)
                        ],
                        child_id=child_id,
                        parent_id=str(unit.parent_swsd_unit_id),
                        run_id=config.run_id,
                    )
                )
            continue
        group = segments[
            (segments["directional_road_id"] == child_id)
            & segments["hard_geometry_eligible"]
        ]
        soft = segments[
            (segments["directional_road_id"] == child_id)
            & ~segments["hard_geometry_eligible"]
        ]
        members, anchor = _build_lane_group(
            group,
            soft,
            unit.geometry,
            boundaries,
            child_id=child_id,
            parent_id=str(unit.parent_swsd_unit_id),
            travel_side=str(unit.travel_side),
            run_id=config.run_id,
        )
        member_rows.extend(members)
        if anchor is not None:
            anchor_rows.append(anchor)

    member_columns = [
        "run_id",
        "directional_road_id",
        "parent_swsd_unit_id",
        "travel_side",
        "lane_id",
        "evidence_quality_state",
        "geometry_role",
        "coverage_ratio",
        "median_lateral_offset_m",
        "lateral_rank",
        "center_rank_distance",
        "curvature_instability",
        "anchor_kind",
        "anchor_source_id",
        "reason_codes",
        "geometry",
    ]
    lane_group_members = gpd.GeoDataFrame(
        member_rows, columns=member_columns, geometry="geometry", crs=roads.crs
    )
    anchor_columns = [
        "run_id",
        "directional_road_id",
        "parent_swsd_unit_id",
        "travel_side",
        "anchor_kind",
        "anchor_source_id",
        "anchor_lane_count",
        "anchor_switch_count",
        "selection_reason",
        "geometry",
    ]
    anchors = gpd.GeoDataFrame(
        anchor_rows, columns=anchor_columns, geometry="geometry", crs=roads.crs
    )

    interval_rows: list[dict[str, Any]] = []
    support_by_child: dict[str, dict[str, Any]] = {}
    for unit in units.itertuples(index=False):
        child_id = str(unit.directional_road_id)
        hard = segments[
            (segments["directional_road_id"] == child_id)
            & segments["hard_geometry_eligible"]
        ]
        intervals, audit = _directional_support(
            unit.geometry,
            hard,
            child_id=child_id,
            parent_id=str(unit.parent_swsd_unit_id),
            travel_side=str(unit.travel_side),
            run_id=config.run_id,
            full_coverage_ratio=config.support_full_coverage_ratio,
            max_gap_m=config.support_max_gap_m,
            long_gap_review_m=config.long_sd_gap_review_m,
        )
        interval_rows.extend(intervals)
        support_by_child[child_id] = audit
    support_intervals = gpd.GeoDataFrame(
        interval_rows, geometry="geometry", crs=roads.crs
    )
    for key, value in (
        ("directional_support_state", "support_state"),
        ("support_reason", "support_reason"),
        ("support_coverage_ratio", "support_coverage_ratio"),
        ("support_length_m", "support_length_m"),
        ("gap_length_m", "gap_length_m"),
        ("max_gap_m", "max_gap_m"),
        ("source_lane_ids", "source_lane_ids"),
    ):
        units[key] = units["directional_road_id"].map(
            lambda child_id, field=value: support_by_child[str(child_id)][field]
        )
    units["sd_gap_ratio"] = units["gap_length_m"] / (
        units["support_length_m"] + units["gap_length_m"]
    ).replace(0.0, np.nan)
    units["sd_gap_ratio"] = units["sd_gap_ratio"].fillna(0.0)
    units["high_precision_claim_scope"] = units["directional_support_state"].map(
        {
            "hp_supported": "full_road",
            "partial_hp_supported": "supported_intervals_only",
            "sd_only": "none",
            "conflict_retained": "none",
        }
    ).fillna("none")
    units["sd_gap_risk_state"] = np.select(
        [
            (units["directional_support_state"] == "partial_hp_supported")
            & units["max_gap_m"].ge(config.long_sd_gap_review_m),
            units["directional_support_state"] == "partial_hp_supported",
            units["directional_support_state"] == "sd_only",
        ],
        ["long_sd_gap_review", "bounded_sd_gap", "all_sd"],
        default="no_sd_gap",
    )
    units["long_sd_gap_review_threshold_m"] = config.long_sd_gap_review_m
    cross_parent = (
        cross_direction_quality_audit.drop_duplicates("parent_swsd_unit_id")
        .set_index("parent_swsd_unit_id")
        if not cross_direction_quality_audit.empty
        else pd.DataFrame()
    )
    for target, source in (
        ("cross_direction_audit_state", "directional_quality_state"),
        ("cross_direction_anchor_median_separation_m", "anchor_median_separation_m"),
        ("cross_direction_anchor_p95_separation_m", "anchor_p95_separation_m"),
        ("cross_direction_reference_lane_width_m", "reference_lane_width_m"),
        ("cross_direction_required_min_separation_m", "required_min_separation_m"),
        ("cross_direction_anchor_gate_pass", "anchor_gate_pass"),
    ):
        mapping = cross_parent[source].to_dict() if not cross_parent.empty else {}
        units[target] = units["parent_swsd_unit_id"].map(mapping)
    units["anchor_kind"] = units["directional_road_id"].map(
        dict(zip(anchors.get("directional_road_id", []), anchors.get("anchor_kind", [])))
    )
    units["anchor_source_id"] = units["directional_road_id"].map(
        dict(zip(anchors.get("directional_road_id", []), anchors.get("anchor_source_id", [])))
    )

    summary = _summary(
        units,
        segments,
        lane_group_members,
        anchors,
        cross_direction_quality_audit,
        support_intervals,
    )
    return DirectionalEvidenceResult(
        directional_units=units,
        lane_segments=segments,
        lane_group_members=lane_group_members,
        anchors=anchors,
        cross_direction_quality_audit=cross_direction_quality_audit,
        support_intervals=support_intervals,
        summary=summary,
    )


def _cross_direction_quality_audit(
    roads: gpd.GeoDataFrame,
    segments: gpd.GeoDataFrame,
    boundaries: dict[str, Any],
    *,
    config: DirectionalRoadV2Config,
) -> gpd.GeoDataFrame:
    columns = [
        "run_id",
        "audit_pair_id",
        "parent_swsd_unit_id",
        "travel_side",
        "provisional_directional_road_id",
        "anchor_kind",
        "anchor_source_id",
        "anchor_median_separation_m",
        "anchor_p95_separation_m",
        "reference_lane_width_m",
        "required_min_separation_m",
        "anchor_gate_pass",
        "directional_quality_state",
        "reason_codes",
        "geometry",
    ]
    hard = segments[segments["hard_geometry_eligible"]]
    rows: list[dict[str, Any]] = []
    for road in roads.itertuples(index=False):
        parent_id = str(road.swsd_unit_id)
        if _coerce_int(getattr(road, "direction", None)) not in {0, 1}:
            continue
        frame = hard[hard["swsd_unit_id"].astype(str) == parent_id]
        sides = {
            side: frame[frame["travel_side"] == side]
            for side in ("forward", "reverse")
        }
        if any(side.empty for side in sides.values()):
            continue
        anchors: dict[str, dict[str, Any]] = {}
        for side, side_frame in sides.items():
            _, anchor = _build_lane_group(
                side_frame,
                segments.iloc[0:0],
                road.geometry,
                boundaries,
                child_id=f"{parent_id}:{side}:provisional",
                parent_id=parent_id,
                travel_side=side,
                run_id=config.run_id,
            )
            if anchor is not None:
                anchors[side] = anchor
        if set(anchors) != {"forward", "reverse"}:
            continue
        median, p95 = _symmetric_geometry_distance(
            anchors["forward"]["geometry"],
            anchors["reverse"]["geometry"],
            config.cross_direction_sample_spacing_m,
        )
        widths = [_median_lane_width(sides[side]) for side in ("forward", "reverse")]
        finite_widths = [value for value in widths if value is not None]
        reference_width = min(finite_widths) if finite_widths else None
        required = max(
            config.cross_direction_min_absolute_separation_m,
            config.cross_direction_min_lane_width_ratio * reference_width
            if reference_width is not None
            else 0.0,
        )
        passed = median >= required
        state = "directional_evidence_separated" if passed else "cross_direction_collapse_review"
        reason = (
            "cross_direction_anchor_separation_pass"
            if passed
            else "cross_direction_anchor_separation_below_width_relative_threshold"
        )
        for side in ("forward", "reverse"):
            anchor = anchors[side]
            rows.append(
                {
                    "run_id": config.run_id,
                    "audit_pair_id": f"{parent_id}:forward_reverse",
                    "parent_swsd_unit_id": parent_id,
                    "travel_side": side,
                    "provisional_directional_road_id": f"{parent_id}:{side}",
                    "anchor_kind": anchor["anchor_kind"],
                    "anchor_source_id": anchor["anchor_source_id"],
                    "anchor_median_separation_m": median,
                    "anchor_p95_separation_m": p95,
                    "reference_lane_width_m": reference_width,
                    "required_min_separation_m": required,
                    "anchor_gate_pass": passed,
                    "directional_quality_state": state,
                    "reason_codes": reason,
                    "geometry": anchor["geometry"],
                }
            )
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=roads.crs)


def _median_lane_width(frame: gpd.GeoDataFrame) -> float | None:
    for column in ("width_median_m", "inferred_lane_width_m"):
        if column not in frame.columns:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        values = values[np.isfinite(values) & values.gt(0.0)]
        if not values.empty:
            per_lane = frame.assign(_width=values).groupby("lane_id")["_width"].median()
            per_lane = per_lane[np.isfinite(per_lane) & per_lane.gt(0.0)]
            if not per_lane.empty:
                return float(per_lane.median())
    return None


def _symmetric_geometry_distance(
    first: Any,
    second: Any,
    spacing_m: float,
) -> tuple[float, float]:
    distances = [
        float(second.distance(point)) for point in _sample_geometry(first, spacing_m)
    ] + [float(first.distance(point)) for point in _sample_geometry(second, spacing_m)]
    if not distances:
        return float("inf"), float("inf")
    return float(np.median(distances)), float(np.percentile(distances, 95))


def _sample_geometry(geometry: Any, spacing_m: float) -> list[Point]:
    lines = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    points: list[Point] = []
    for line in lines:
        if line is None or line.is_empty or not hasattr(line, "interpolate"):
            continue
        count = max(3, int(math.ceil(float(line.length) / max(spacing_m, 1e-6))) + 1)
        points.extend(
            line.interpolate(float(distance))
            for distance in np.linspace(0.0, float(line.length), count)
        )
    return points


def _build_lane_group(
    hard: gpd.GeoDataFrame,
    soft: gpd.GeoDataFrame,
    reference: Any,
    boundaries: dict[str, Any],
    *,
    child_id: str,
    parent_id: str,
    travel_side: str,
    run_id: str,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if hard.empty:
        return _soft_member_rows(
            soft, child_id=child_id, parent_id=parent_id, travel_side=travel_side, run_id=run_id
        ), None
    stats: list[dict[str, Any]] = []
    for lane_id, frame in hard.groupby("lane_id"):
        offsets = [
            _signed_offset(reference, geometry.interpolate(fraction, normalized=True))
            for geometry in frame.geometry
            for fraction in (0.1, 0.5, 0.9)
            if geometry is not None and not geometry.is_empty
        ]
        coverage = _union_length(
            (float(row.road_start_m), float(row.road_end_m))
            for row in frame.itertuples(index=False)
        ) / max(float(reference.length), 1e-8)
        geometry = _merge_lines(frame.geometry)
        stats.append(
            {
                "lane_id": str(lane_id),
                "coverage_ratio": min(1.0, coverage),
                "median_lateral_offset_m": float(np.median(offsets)) if offsets else 0.0,
                "curvature_instability": _curvature_instability(geometry),
                "boundary_ids": _boundary_ids(frame),
                "geometry": geometry,
            }
        )
    stats.sort(key=lambda row: (row["median_lateral_offset_m"], row["lane_id"]))
    center = (len(stats) - 1) / 2.0
    for index, row in enumerate(stats):
        row["lateral_rank"] = index
        row["center_rank_distance"] = abs(index - center)

    anchor_kind = "lane"
    anchor_source_id: str
    anchor_geometry: Any
    anchor_lane_count = 1
    selection_reason: str
    max_coverage = max(row["coverage_ratio"] for row in stats)
    stable_pool = [
        row
        for row in stats
        if row["coverage_ratio"] >= max_coverage * 0.80 - 1e-8
    ]
    stable_center = (len(stable_pool) - 1) / 2.0
    central_indices = [
        int(math.floor(stable_center)),
        int(math.ceil(stable_center)),
    ]
    central = [stable_pool[index] for index in sorted(set(central_indices))]
    shared_boundary_ids = (
        central[0]["boundary_ids"] & central[1]["boundary_ids"]
        if len(central) == 2
        else set()
    )
    boundary_candidates = [
        (boundary_id, boundaries[boundary_id])
        for boundary_id in sorted(shared_boundary_ids)
        if boundary_id in boundaries
        and _boundary_anchor_valid(reference, boundaries[boundary_id], central)
    ]
    if boundary_candidates:
        anchor_source_id, anchor_geometry = max(
            boundary_candidates,
            key=lambda item: _projected_span(reference, item[1]),
        )
        anchor_kind = "lane_boundary"
        anchor_lane_count = 2
        selection_reason = "coverage_stable_even_lane_shared_central_boundary"
    else:
        selected = min(
            central,
            key=lambda row: (
                -row["coverage_ratio"],
                row["curvature_instability"],
                abs(row["median_lateral_offset_m"]),
                row["lane_id"],
            ),
        )
        anchor_source_id = selected["lane_id"]
        anchor_geometry = selected["geometry"]
        selection_reason = (
            "coverage_stable_odd_lane_central_lane"
            if len(central) == 1
            else "coverage_stable_even_lane_boundary_unavailable_central_lane"
        )

    member_rows = []
    for row in stats:
        is_anchor_lane = anchor_kind == "lane" and row["lane_id"] == anchor_source_id
        member_rows.append(
            {
                "run_id": run_id,
                "directional_road_id": child_id,
                "parent_swsd_unit_id": parent_id,
                "travel_side": travel_side,
                "lane_id": row["lane_id"],
                "evidence_quality_state": "usable",
                "geometry_role": "anchor" if is_anchor_lane else "hard_member",
                "coverage_ratio": row["coverage_ratio"],
                "median_lateral_offset_m": row["median_lateral_offset_m"],
                "lateral_rank": row["lateral_rank"],
                "center_rank_distance": row["center_rank_distance"],
                "curvature_instability": row["curvature_instability"],
                "anchor_kind": anchor_kind if is_anchor_lane else "",
                "anchor_source_id": anchor_source_id if is_anchor_lane else "",
                "reason_codes": "direction_compatible_usable_lane",
                "geometry": row["geometry"],
            }
        )
    member_rows.extend(
        _soft_member_rows(
            soft,
            child_id=child_id,
            parent_id=parent_id,
            travel_side=travel_side,
            run_id=run_id,
        )
    )
    return member_rows, {
        "run_id": run_id,
        "directional_road_id": child_id,
        "parent_swsd_unit_id": parent_id,
        "travel_side": travel_side,
        "anchor_kind": anchor_kind,
        "anchor_source_id": anchor_source_id,
        "anchor_lane_count": anchor_lane_count,
        "anchor_switch_count": 0,
        "selection_reason": selection_reason,
        "geometry": anchor_geometry,
    }


def _soft_member_rows(
    soft: gpd.GeoDataFrame,
    *,
    child_id: str,
    parent_id: str,
    travel_side: str,
    run_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lane_id, frame in soft.groupby("lane_id"):
        rows.append(
            {
                "run_id": run_id,
                "directional_road_id": child_id,
                "parent_swsd_unit_id": parent_id,
                "travel_side": travel_side,
                "lane_id": str(lane_id),
                "evidence_quality_state": ";".join(
                    sorted(set(frame["evidence_quality_state"].astype(str)))
                ),
                "geometry_role": "soft_review",
                "coverage_ratio": 0.0,
                "median_lateral_offset_m": None,
                "lateral_rank": None,
                "center_rank_distance": None,
                "curvature_instability": None,
                "anchor_kind": "",
                "anchor_source_id": "",
                "reason_codes": "quality_state_not_hard_geometry_anchor",
                "geometry": _merge_lines(frame.geometry),
            }
        )
    return rows


def _topology_only_member_rows(
    frame: gpd.GeoDataFrame,
    *,
    child_id: str,
    parent_id: str,
    run_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lane_id, lane_frame in frame.groupby("lane_id"):
        rows.append(
            {
                "run_id": run_id,
                "directional_road_id": child_id,
                "parent_swsd_unit_id": parent_id,
                "travel_side": ";".join(
                    sorted(set(lane_frame["travel_side"].astype(str)))
                ),
                "lane_id": str(lane_id),
                "evidence_quality_state": ";".join(
                    sorted(set(lane_frame["evidence_quality_state"].astype(str)))
                ),
                "geometry_role": "topology_only_review",
                "coverage_ratio": 0.0,
                "median_lateral_offset_m": None,
                "lateral_rank": None,
                "center_rank_distance": None,
                "curvature_instability": None,
                "anchor_kind": "",
                "anchor_source_id": "",
                "reason_codes": "cross_direction_collapse_lane_topo_lineage_only",
                "geometry": _merge_lines(lane_frame.geometry),
            }
        )
    return rows


def _directional_support(
    reference: Any,
    segments: gpd.GeoDataFrame,
    *,
    child_id: str,
    parent_id: str,
    travel_side: str,
    run_id: str,
    full_coverage_ratio: float,
    max_gap_m: float,
    long_gap_review_m: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    length = float(reference.length)
    merged = _merge_intervals(
        (
            float(row.road_start_m),
            float(row.road_end_m),
            str(row.lane_id),
            str(row.source_patch_ids),
        )
        for row in segments.itertuples(index=False)
    )
    gaps = _complement([(row["start_m"], row["end_m"]) for row in merged], length)
    support_length = sum(row["end_m"] - row["start_m"] for row in merged)
    coverage = support_length / length if length > 1e-8 else 0.0
    largest_gap = max((end - start for start, end in gaps), default=0.0)
    if not merged:
        support_state = "sd_only"
        reason = "no_direction_compatible_usable_lane"
    elif coverage >= full_coverage_ratio and largest_gap <= max_gap_m:
        support_state = "hp_supported"
        reason = "directional_full_longitudinal_support"
    else:
        support_state = "partial_hp_supported"
        reason = "directional_support_has_gap"
    partition = [
        {**row, "interval_state": "hp_supported"}
        for row in merged
    ] + [
        {
            "start_m": start,
            "end_m": end,
            "lane_ids": set(),
            "patch_ids": set(),
            "interval_state": "sd_gap",
        }
        for start, end in gaps
    ]
    rows = []
    reverse = travel_side == "reverse"
    for index, interval in enumerate(
        sorted(partition, key=lambda row: (row["start_m"], row["end_m"]))
    ):
        start = float(interval["start_m"])
        end = float(interval["end_m"])
        parent_start_fraction = start / length if length > 1e-8 else 0.0
        parent_end_fraction = end / length if length > 1e-8 else 1.0
        rows.append(
            {
                "run_id": run_id,
                "directional_road_id": child_id,
                "parent_swsd_unit_id": parent_id,
                "travel_side": travel_side,
                "interval_id": f"{child_id}:{index}",
                "interval_index": index,
                "interval_state": interval["interval_state"],
                "directional_support_state": support_state,
                "long_sd_gap_review_threshold_m": long_gap_review_m,
                "parent_start_m": start,
                "parent_end_m": end,
                "parent_start_fraction": parent_start_fraction,
                "parent_end_fraction": parent_end_fraction,
                "travel_start_fraction": 1.0 - parent_end_fraction if reverse else parent_start_fraction,
                "travel_end_fraction": 1.0 - parent_start_fraction if reverse else parent_end_fraction,
                "interval_length_m": end - start,
                "source_lane_ids": ";".join(sorted(interval["lane_ids"])),
                "source_patch_ids": ";".join(sorted(interval["patch_ids"])),
                "geometry_source": "directional_hp_pending"
                if interval["interval_state"] == "hp_supported"
                else "directional_sd_extrapolated_pending",
                "reason_codes": interval["interval_state"],
                "geometry": _line_part(reference, start, end),
            }
        )
    source_lane_ids = sorted(
        {lane_id for row in merged for lane_id in row["lane_ids"]}
    )
    return rows, {
        "support_state": support_state,
        "support_reason": reason,
        "support_coverage_ratio": coverage,
        "support_length_m": support_length,
        "gap_length_m": max(0.0, length - support_length),
        "max_gap_m": largest_gap,
        "source_lane_ids": ";".join(source_lane_ids),
    }


def _travel_side(line: Any, reference: Any) -> str:
    if line is None or line.is_empty:
        return "unknown"
    start = line.interpolate(0.0)
    end = line.interpolate(float(line.length))
    start_offset = float(reference.project(start))
    end_offset = float(reference.project(end))
    if abs(end_offset - start_offset) > 0.25:
        return "forward" if end_offset > start_offset else "reverse"
    lane_tangent = tangent_vector(line, float(line.length) / 2.0)
    road_offset = float(reference.project(line.interpolate(float(line.length) / 2.0)))
    road_tangent = tangent_vector(reference, road_offset)
    return "forward" if lane_tangent[0] * road_tangent[0] + lane_tangent[1] * road_tangent[1] >= 0 else "reverse"


def _signed_offset(reference: Any, point: Point) -> float:
    offset = float(reference.project(point))
    base = reference.interpolate(offset)
    tangent = tangent_vector(reference, offset)
    norm = math.hypot(*tangent)
    if norm <= 1e-12:
        return float(base.distance(point))
    vector = (float(point.x - base.x), float(point.y - base.y))
    return float((tangent[0] * vector[1] - tangent[1] * vector[0]) / norm)


def _prepare_boundaries(frame: gpd.GeoDataFrame) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {}
    id_column = next((column for column in ("Id", "id", "boundary_id") if column in frame.columns), None)
    if id_column is None:
        return {}
    grouped: dict[str, list[Any]] = {}
    for row in frame.itertuples(index=False):
        value = canonical_id(getattr(row, id_column))
        if value is not None and row.geometry is not None and not row.geometry.is_empty:
            grouped.setdefault(value, []).append(row.geometry)
    return {key: _merge_lines(values) for key, values in grouped.items()}


def _boundary_ids(frame: gpd.GeoDataFrame) -> set[str]:
    values: set[str] = set()
    for column in ("left_boundary_ids", "right_boundary_ids", "left_boundary_id", "right_boundary_id"):
        if column not in frame.columns:
            continue
        for raw in frame[column].dropna():
            for token in str(raw).replace(";", ",").split(","):
                value = canonical_id(token.strip())
                if value not in {None, "", "nan", "0"}:
                    values.add(value)
    return values


def _merge_lines(lines: Iterable[Any]) -> Any:
    valid = [line for line in lines if line is not None and not line.is_empty]
    if not valid:
        return LineString()
    if len(valid) == 1:
        return valid[0]
    merged = linemerge(unary_union(valid))
    return merged


def _projected_span(reference: Any, geometry: Any) -> float:
    if geometry is None or geometry.is_empty:
        return 0.0
    points = []
    geoms = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    for line in geoms:
        if hasattr(line, "coords") and len(line.coords):
            points.extend((Point(line.coords[0]), Point(line.coords[-1])))
    offsets = [float(reference.project(point)) for point in points]
    return max(offsets, default=0.0) - min(offsets, default=0.0)


def _boundary_anchor_valid(
    reference: Any,
    boundary: Any,
    central_lanes: list[dict[str, Any]],
) -> bool:
    if len(central_lanes) != 2 or boundary is None or boundary.is_empty:
        return False
    station_count = max(5, min(21, int(math.ceil(float(reference.length) / 10.0)) + 1))
    checked = 0
    between = 0
    for station in np.linspace(0.0, float(reference.length), station_count):
        point = reference.interpolate(float(station))
        boundary_offset = _nearest_offset(reference, float(station), point, boundary)
        lane_offsets = [
            _nearest_offset(reference, float(station), point, row["geometry"])
            for row in central_lanes
        ]
        if boundary_offset is None or any(value is None for value in lane_offsets):
            continue
        checked += 1
        lower, upper = sorted(float(value) for value in lane_offsets if value is not None)
        if lower - 0.75 <= boundary_offset <= upper + 0.75:
            between += 1
    return checked >= 3 and between / checked >= 0.70


def _nearest_offset(
    reference: Any,
    station: float,
    reference_point: Point,
    geometry: Any,
) -> float | None:
    lines = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    choices: list[tuple[float, Point]] = []
    for line in lines:
        if line is None or line.is_empty or not hasattr(line, "project"):
            continue
        nearest = line.interpolate(line.project(reference_point))
        distance = float(reference_point.distance(nearest))
        projected = float(reference.project(nearest))
        if distance <= 30.0 and abs(projected - station) <= 10.0:
            choices.append((distance, nearest))
    if not choices:
        return None
    _, nearest = min(choices, key=lambda item: item[0])
    tangent = tangent_vector(reference, station)
    norm = math.hypot(*tangent)
    if norm <= 1e-12:
        return float(reference_point.distance(nearest))
    vector = (float(nearest.x - reference_point.x), float(nearest.y - reference_point.y))
    return float((tangent[0] * vector[1] - tangent[1] * vector[0]) / norm)


def _curvature_instability(geometry: Any) -> float:
    if geometry is None or geometry.is_empty:
        return float("inf")
    geoms = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    values = []
    for line in geoms:
        if not hasattr(line, "coords") or len(line.coords) < 2:
            continue
        chord = Point(line.coords[0]).distance(Point(line.coords[-1]))
        values.append(max(0.0, float(line.length) / max(chord, 1e-8) - 1.0))
    return float(np.median(values)) if values else float("inf")


def _merge_intervals(values: Iterable[tuple[float, float, str, str]]) -> list[dict[str, Any]]:
    raw = sorted((min(start, end), max(start, end), lane, patch) for start, end, lane, patch in values)
    merged: list[dict[str, Any]] = []
    for start, end, lane_id, patch_id in raw:
        if end - start <= 1e-8:
            continue
        if not merged or start > merged[-1]["end_m"] + 1e-8:
            merged.append(
                {"start_m": start, "end_m": end, "lane_ids": {lane_id}, "patch_ids": {patch_id}}
            )
        else:
            merged[-1]["end_m"] = max(merged[-1]["end_m"], end)
            merged[-1]["lane_ids"].add(lane_id)
            merged[-1]["patch_ids"].add(patch_id)
    return merged


def _complement(intervals: list[tuple[float, float]], length: float) -> list[tuple[float, float]]:
    gaps: list[tuple[float, float]] = []
    cursor = 0.0
    for start, end in intervals:
        if start > cursor + 1e-8:
            gaps.append((cursor, start))
        cursor = max(cursor, end)
    if cursor < length - 1e-8:
        gaps.append((cursor, length))
    return gaps


def _union_length(values: Iterable[tuple[float, float]]) -> float:
    merged = _merge_intervals((start, end, "", "") for start, end in values)
    return sum(row["end_m"] - row["start_m"] for row in merged)


def _line_part(line: Any, start: float, end: float) -> Any:
    if end - start <= 1e-8:
        point = line.interpolate(start)
        return LineString([point, point])
    return substring(line, start, end)


def _pick_endpoint(values: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = canonical_id(values.get(key))
        if value not in {None, "nan"}:
            return value
    return None


def _coerce_int(value: Any) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _summary(
    units: gpd.GeoDataFrame,
    segments: gpd.GeoDataFrame,
    members: gpd.GeoDataFrame,
    anchors: gpd.GeoDataFrame,
    cross_direction_audit: gpd.GeoDataFrame,
    intervals: gpd.GeoDataFrame,
) -> dict[str, Any]:
    state_counts = Counter(units["directional_support_state"].astype(str))
    parent_count = int(units["parent_swsd_unit_id"].nunique())
    expanded = units[units["road_representation"] == "directional_child"]
    bidirectional_parent_counts = expanded.groupby("parent_swsd_unit_id").size()
    collapsed_parent_ids = set(
        cross_direction_audit.loc[
            ~cross_direction_audit["anchor_gate_pass"].astype(bool),
            "parent_swsd_unit_id",
        ].astype(str)
    ) if not cross_direction_audit.empty else set()
    return {
        "parent_road_count": parent_count,
        "directional_road_count": int(len(units)),
        "directional_child_count": int(len(expanded)),
        "pure_sd_parent_count": int((units["road_representation"] == "sd_only_parent").sum()),
        "expanded_bidirectional_parent_count": int((bidirectional_parent_counts == 2).sum()),
        "cross_direction_audited_parent_count": int(
            cross_direction_audit["parent_swsd_unit_id"].nunique()
            if not cross_direction_audit.empty
            else 0
        ),
        "cross_direction_collapse_parent_count": int(len(collapsed_parent_ids)),
        "cross_direction_downgraded_lane_segment_count": int(
            (
                segments["directional_geometry_quality_state"]
                == "cross_direction_collapse_review"
            ).sum()
        ),
        "published_cross_direction_collapse_count": int(
            expanded["parent_swsd_unit_id"].astype(str).isin(collapsed_parent_ids).sum()
        ),
        "long_sd_gap_review_count": int(
            (units["sd_gap_risk_state"] == "long_sd_gap_review").sum()
        ),
        "support_state_counts": {
            state: int(state_counts.get(state, 0))
            for state in ("hp_supported", "partial_hp_supported", "sd_only", "conflict_retained")
        },
        "travel_side_counts": dict(sorted(Counter(units["travel_side"]).items())),
        "hard_lane_segment_count": int(segments["hard_geometry_eligible"].sum()),
        "soft_lane_segment_count": int((~segments["hard_geometry_eligible"]).sum()),
        "hard_anchor_non_usable_count": int(
            (
                (members.get("geometry_role", pd.Series(dtype=str)) == "anchor")
                & (members.get("evidence_quality_state", pd.Series(dtype=str)) != "usable")
            ).sum()
        ),
        "anchor_count": int(len(anchors)),
        "anchor_kind_counts": dict(sorted(Counter(anchors.get("anchor_kind", [])).items())),
        "anchor_switch_count": int(anchors.get("anchor_switch_count", pd.Series(dtype=int)).sum()),
        "support_interval_count": int(len(intervals)),
        "non_sd_bidirectional_object_count": int(
            (
                (units["directional_support_state"] != "sd_only")
                & units["direction"].isin([0, 1])
            ).sum()
        ),
    }


__all__ = ["DirectionalEvidenceResult", "build_directional_evidence"]
