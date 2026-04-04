from __future__ import annotations

import argparse
import json
import math
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
from pyproj import CRS
from shapely.geometry import GeometryCollection, Point
from shapely.ops import linemerge, substring, unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    TARGET_CRS,
    announce,
    build_logger,
    build_run_id,
    close_logger,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t02_junction_anchor.shared import T02RunError, find_repo_root, normalize_id
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    DEFAULT_PATCH_SIZE_M,
    DEFAULT_RESOLUTION_M,
    MAIN_AXIS_ANGLE_TOLERANCE_DEG,
    ROAD_BUFFER_M,
    RC_NODE_SEED_RADIUS_M,
    RC_ROAD_BUFFER_M,
    NODE_SEED_RADIUS_M,
    ParsedNode,
    ParsedRoad,
    _binary_close,
    _branch_candidate_from_road,
    _build_debug_focus_geometry,
    _build_grid,
    _build_road_branches_for_member_nodes,
    _extract_seed_component,
    _load_layer_filtered,
    _mask_to_geometry,
    _parse_nodes,
    _parse_rc_nodes,
    _parse_roads,
    _rasterize_geometries,
    _regularize_virtual_polygon_geometry,
    _resolve_group,
    _select_main_pair,
    _write_debug_rendered_map,
)


REASON_MISSING_REQUIRED_FIELD = "missing_required_field"
REASON_INVALID_CRS_OR_UNPROJECTABLE = "invalid_crs_or_unprojectable"
REASON_MAINNODEID_NOT_FOUND = "mainnodeid_not_found"
REASON_MAINNODEID_OUT_OF_SCOPE = "mainnodeid_out_of_scope"
REASON_MAIN_DIRECTION_UNSTABLE = "main_direction_unstable"
REASON_RCS_OUTSIDE_DRIVEZONE = "rcsd_outside_drivezone"
REASON_COVERAGE_INCOMPLETE = "coverage_incomplete"
REASON_TRUNK_BRANCH_UNSTABLE = "trunk_branch_unstable"
REASON_RCSDNODE_MAIN_OFF_TRUNK = "rcsdnode_main_off_trunk"
REASON_RCSDNODE_MAIN_OUT_OF_WINDOW = "rcsdnode_main_out_of_window"
REASON_RCSDNODE_MAIN_DIRECTION_INVALID = "rcsdnode_main_direction_invalid"
STATUS_DIVSTRIP_NOT_NEARBY = "divstrip_not_nearby"
STATUS_DIVSTRIP_COMPONENT_AMBIGUOUS = "divstrip_component_ambiguous"
STATUS_MULTIBRANCH_EVENT_AMBIGUOUS = "multibranch_event_ambiguous"
STATUS_CONTINUOUS_CHAIN_REVIEW = "continuous_chain_review"
STAGE4_KIND_2_VALUES = {8, 16}
DIVSTRIP_NEARBY_DISTANCE_M = 24.0
DIVSTRIP_BRANCH_BUFFER_M = 6.0
DIVSTRIP_EXCLUSION_BUFFER_M = 0.75
MULTIBRANCH_AMBIGUITY_SCORE_MARGIN = 5.0
CHAIN_NEARBY_DISTANCE_M = 65.0
CHAIN_SEQUENCE_DISTANCE_M = 40.0
RCSDNODE_TRUNK_WINDOW_M = 20.0
RCSDNODE_TRUNK_LATERAL_TOLERANCE_M = 6.0


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _tracemalloc_stats() -> dict[str, int]:
    if not tracemalloc.is_tracing():
        return {
            "python_tracemalloc_current_bytes": 0,
            "python_tracemalloc_peak_bytes": 0,
        }
    current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    return {
        "python_tracemalloc_current_bytes": current_bytes,
        "python_tracemalloc_peak_bytes": peak_bytes,
    }


def _resolve_out_root(
    *,
    out_root: Optional[Union[str, Path]],
    run_id: Optional[str],
    cwd: Optional[Path] = None,
) -> tuple[Path, str]:
    resolved_run_id = run_id or build_run_id("t02_stage4_divmerge_virtual_polygon")
    if out_root is not None:
        return Path(out_root) / resolved_run_id, resolved_run_id

    repo_root = find_repo_root(cwd or Path.cwd())
    if repo_root is None:
        raise Stage4RunError(
            REASON_MISSING_REQUIRED_FIELD,
            "Cannot infer default out_root because repo root was not found; please pass --out-root.",
        )
    return repo_root / "outputs" / "_work" / "t02_stage4_divmerge_virtual_polygon" / resolved_run_id, resolved_run_id


def _write_progress_snapshot(
    *,
    out_path: Path,
    run_id: str,
    status: str,
    current_stage: str | None,
    message: str,
    counts: dict[str, Any],
) -> None:
    write_json(
        out_path,
        {
            "run_id": run_id,
            "status": status,
            "updated_at": _now_text(),
            "current_stage": current_stage,
            "message": message,
            "counts": counts,
            **_tracemalloc_stats(),
        },
    )


def _record_perf_marker(
    *,
    out_path: Path,
    run_id: str,
    stage: str,
    elapsed_sec: float,
    counts: dict[str, Any],
    note: str | None = None,
) -> None:
    marker = {
        "event": "stage_marker",
        "run_id": run_id,
        "at": _now_text(),
        "stage": stage,
        "elapsed_sec": round(elapsed_sec, 6),
        "counts": counts,
        **_tracemalloc_stats(),
    }
    if note is not None:
        marker["note"] = note
    _append_jsonl(out_path, marker)


class Stage4RunError(T02RunError):
    pass


@dataclass(frozen=True)
class Stage4Artifacts:
    success: bool
    out_root: Path
    virtual_polygon_path: Path
    node_link_json_path: Path
    rcsdnode_link_json_path: Path
    audit_json_path: Path
    status_path: Path
    log_path: Path
    progress_path: Path
    perf_json_path: Path
    perf_markers_path: Path
    debug_dir: Path | None = None
    status_doc: dict[str, Any] | None = None
    perf_doc: dict[str, Any] | None = None


def _cover_check(geometry, candidates: list[ParsedNode]) -> list[str]:
    cover = geometry.buffer(0)
    return [node.node_id for node in candidates if not cover.covers(node.geometry)]


def _selected_branch_score(branch) -> float:
    return float(branch.road_support_m + branch.drivezone_support_m + branch.rc_support_m)


def _branch_angle_gap_deg(lhs, rhs) -> float:
    lhs_angle = lhs["angle_deg"] if isinstance(lhs, dict) else lhs.angle_deg
    rhs_angle = rhs["angle_deg"] if isinstance(rhs, dict) else rhs.angle_deg
    raw_gap = abs(float(lhs_angle) - float(rhs_angle))
    return min(raw_gap, 360.0 - raw_gap)


def _branch_selection_quality(branches: list[Any], preferred_branch_ids: set[str]) -> tuple[int, float]:
    branch_ids = {branch.branch_id for branch in branches}
    return (
        len(branch_ids & preferred_branch_ids),
        float(sum(_selected_branch_score(branch) for branch in branches)),
    )


def _select_stage4_side_branches(
    road_branches,
    *,
    kind_2: int,
    preferred_branch_ids: set[str] | None = None,
) -> list[Any]:
    selected = [branch for branch in road_branches if not branch.is_main_direction]
    if kind_2 == 8:
        selected = [branch for branch in selected if branch.has_incoming_support or not branch.has_outgoing_support]
    else:
        selected = [branch for branch in selected if branch.has_outgoing_support or not branch.has_incoming_support]
    if not selected:
        selected = [branch for branch in road_branches if not branch.is_main_direction]
    preferred = preferred_branch_ids or set()
    selected.sort(
        key=lambda branch: (
            1 if branch.branch_id in preferred else 0,
            _selected_branch_score(branch),
        ),
        reverse=True,
    )
    return selected[:2]


def _select_reverse_tip_side_branches(
    road_branches,
    *,
    kind_2: int,
    preferred_branch_ids: set[str],
) -> list[Any]:
    selected = [branch for branch in road_branches if not branch.is_main_direction]
    if kind_2 == 8:
        selected = [branch for branch in selected if branch.has_outgoing_support or not branch.has_incoming_support]
    else:
        selected = [branch for branch in selected if branch.has_incoming_support or not branch.has_outgoing_support]
    if not selected:
        selected = [branch for branch in road_branches if not branch.is_main_direction]
    selected.sort(
        key=lambda branch: (
            1 if branch.branch_id in preferred_branch_ids else 0,
            _selected_branch_score(branch),
        ),
        reverse=True,
    )
    return selected[:2]


def _load_layer(
    path: Union[str, Path],
    *,
    layer_name: Optional[str],
    crs_override: Optional[str],
    allow_null_geometry: bool,
    query_geometry: Any | None = None,
) -> Any:
    try:
        return _load_layer_filtered(
            path,
            layer_name=layer_name,
            crs_override=crs_override,
            allow_null_geometry=allow_null_geometry,
            query_geometry=query_geometry,
        )
    except Exception as exc:
        if hasattr(exc, "reason") and hasattr(exc, "detail"):
            raise Stage4RunError(getattr(exc, "reason"), getattr(exc, "detail")) from exc
        raise Stage4RunError(REASON_INVALID_CRS_OR_UNPROJECTABLE, str(exc)) from exc


def _validate_drivezone_containment(
    *,
    drivezone_union,
    features: list[Any],
    label: str,
) -> list[str]:
    outside_ids: list[str] = []
    drivezone_cover = drivezone_union.buffer(0)
    for feature in features:
        feature_id = normalize_id(feature.node_id if hasattr(feature, "node_id") else getattr(feature, "road_id", None))
        if feature.geometry is None or feature.geometry.is_empty:
            continue
        if drivezone_cover.covers(feature.geometry):
            continue
        outside_ids.append(feature_id or "unknown")
    if outside_ids:
        raise Stage4RunError(
            REASON_RCS_OUTSIDE_DRIVEZONE,
            f"{label} features are outside DriveZone: {','.join(sorted(set(outside_ids)))}",
        )
    return outside_ids


def _make_link_doc(
    *,
    mainnodeid: str,
    kind_2: int,
    grade_2: int | None,
    target_node_ids: list[str],
    linked_node_ids: list[str],
    selected_branch_ids: list[str],
    selected_road_ids: list[str],
    coverage_missing_ids: list[str],
) -> dict[str, Any]:
    return {
        "mainnodeid": mainnodeid,
        "kind_2": kind_2,
        "grade_2": grade_2,
        "target_node_ids": target_node_ids,
        "linked_node_ids": linked_node_ids,
        "selected_branch_ids": selected_branch_ids,
        "selected_road_ids": selected_road_ids,
        "coverage_missing_ids": coverage_missing_ids,
    }


def _explode_component_geometries(geometry) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    if hasattr(geometry, "geoms"):
        exploded: list[Any] = []
        for item in geometry.geoms:
            exploded.extend(_explode_component_geometries(item))
        return exploded
    return [geometry]


def _pick_primary_main_rc_node(
    *,
    target_rc_nodes: list[ParsedNode],
    mainnodeid_norm: str,
) -> ParsedNode | None:
    for node in target_rc_nodes:
        if normalize_id(node.node_id) == mainnodeid_norm:
            return node
    for node in target_rc_nodes:
        if node.mainnodeid == mainnodeid_norm:
            return node
    return target_rc_nodes[0] if target_rc_nodes else None


def _resolve_trunk_branch(
    *,
    road_branches,
    main_branch_ids: set[str],
    kind_2: int,
):
    main_branches = [branch for branch in road_branches if branch.branch_id in main_branch_ids]
    if kind_2 == 16:
        trunk_candidates = [branch for branch in main_branches if branch.has_incoming_support]
        tolerance_rule = "diverge_main_seed_on_pre_trunk_le_20m"
    else:
        trunk_candidates = [branch for branch in main_branches if branch.has_outgoing_support]
        tolerance_rule = "merge_main_seed_on_post_trunk_le_20m"
    if len(trunk_candidates) != 1:
        return None, tolerance_rule
    return trunk_candidates[0], tolerance_rule


def _resolve_branch_centerline(
    *,
    branch,
    road_lookup: dict[str, ParsedRoad],
    reference_point: Point,
):
    line_union = unary_union(
        [
            road_lookup[road_id].geometry
            for road_id in branch.road_ids
            if road_id in road_lookup and road_lookup[road_id].geometry is not None and not road_lookup[road_id].geometry.is_empty
        ]
    )
    if line_union.is_empty:
        return None
    merged = line_union if getattr(line_union, "geom_type", None) == "LineString" else linemerge(line_union)
    line_components = [
        component
        for component in _explode_component_geometries(merged)
        if getattr(component, "geom_type", None) == "LineString" and not component.is_empty
    ]
    if not line_components:
        line_components = [
            component
            for component in _explode_component_geometries(line_union)
            if getattr(component, "geom_type", None) == "LineString" and not component.is_empty
        ]
    if not line_components:
        return None
    centerline = min(
        line_components,
        key=lambda component: (
            float(component.distance(reference_point)),
            -float(component.length),
        ),
    )
    start_point = Point(centerline.coords[0])
    end_point = Point(centerline.coords[-1])
    if end_point.distance(reference_point) < start_point.distance(reference_point):
        centerline = type(centerline)(list(centerline.coords)[::-1])
    return centerline


def _evaluate_primary_rcsdnode_tolerance(
    *,
    polygon_geometry,
    primary_main_rc_node: ParsedNode | None,
    representative_node: ParsedNode,
    road_branches,
    main_branch_ids: set[str],
    local_roads: list[ParsedRoad],
    kind_2: int,
    drivezone_union,
) -> dict[str, Any]:
    tolerance_rule = (
        "diverge_main_seed_on_pre_trunk_le_20m"
        if kind_2 == 16
        else "merge_main_seed_on_post_trunk_le_20m"
    )
    if primary_main_rc_node is None:
        return {
            "trunk_branch_id": None,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "no_primary_main_rcsdnode",
            "rcsdnode_offset_m": None,
            "rcsdnode_lateral_dist_m": None,
            "reason": None,
            "extended_polygon_geometry": polygon_geometry,
            "covered": True,
        }

    trunk_branch, tolerance_rule = _resolve_trunk_branch(
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        kind_2=kind_2,
    )
    if trunk_branch is None:
        return {
            "trunk_branch_id": None,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "trunk_unstable",
            "rcsdnode_offset_m": None,
            "rcsdnode_lateral_dist_m": None,
            "reason": REASON_TRUNK_BRANCH_UNSTABLE,
            "extended_polygon_geometry": polygon_geometry,
            "covered": False,
        }

    road_lookup = {road.road_id: road for road in local_roads}
    reference_point = representative_node.geometry
    trunk_centerline = _resolve_branch_centerline(
        branch=trunk_branch,
        road_lookup=road_lookup,
        reference_point=reference_point,
    )
    if trunk_centerline is None or trunk_centerline.is_empty:
        return {
            "trunk_branch_id": trunk_branch.branch_id,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "trunk_unstable",
            "rcsdnode_offset_m": None,
            "rcsdnode_lateral_dist_m": None,
            "reason": REASON_TRUNK_BRANCH_UNSTABLE,
            "extended_polygon_geometry": polygon_geometry,
            "covered": False,
        }

    event_source_point = representative_node.geometry
    if trunk_centerline.distance(event_source_point) > RCSDNODE_TRUNK_LATERAL_TOLERANCE_M:
        event_source_point = polygon_geometry.centroid
    event_ref_dist = float(trunk_centerline.project(event_source_point))
    node_dist = float(trunk_centerline.project(primary_main_rc_node.geometry))
    offset_m = float(node_dist - event_ref_dist)
    lateral_dist_m = float(primary_main_rc_node.geometry.distance(trunk_centerline))

    if lateral_dist_m > RCSDNODE_TRUNK_LATERAL_TOLERANCE_M:
        return {
            "trunk_branch_id": trunk_branch.branch_id,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "off_trunk",
            "rcsdnode_offset_m": offset_m,
            "rcsdnode_lateral_dist_m": lateral_dist_m,
            "reason": REASON_RCSDNODE_MAIN_OFF_TRUNK,
            "extended_polygon_geometry": polygon_geometry,
            "covered": False,
        }

    if offset_m < -1.0:
        return {
            "trunk_branch_id": trunk_branch.branch_id,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "direction_invalid",
            "rcsdnode_offset_m": offset_m,
            "rcsdnode_lateral_dist_m": lateral_dist_m,
            "reason": REASON_RCSDNODE_MAIN_DIRECTION_INVALID,
            "extended_polygon_geometry": polygon_geometry,
            "covered": False,
        }

    if offset_m > RCSDNODE_TRUNK_WINDOW_M:
        return {
            "trunk_branch_id": trunk_branch.branch_id,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "out_of_window",
            "rcsdnode_offset_m": offset_m,
            "rcsdnode_lateral_dist_m": lateral_dist_m,
            "reason": REASON_RCSDNODE_MAIN_OUT_OF_WINDOW,
            "extended_polygon_geometry": polygon_geometry,
            "covered": False,
        }

    if polygon_geometry.buffer(0).covers(primary_main_rc_node.geometry):
        return {
            "trunk_branch_id": trunk_branch.branch_id,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "exact_cover",
            "rcsdnode_offset_m": offset_m,
            "rcsdnode_lateral_dist_m": lateral_dist_m,
            "reason": None,
            "extended_polygon_geometry": polygon_geometry,
            "covered": True,
        }

    start_dist = max(0.0, min(event_ref_dist, node_dist))
    end_dist = min(float(trunk_centerline.length), max(event_ref_dist, node_dist))
    corridor_width = max(ROAD_BUFFER_M, RC_NODE_SEED_RADIUS_M * 2.0, lateral_dist_m + 1.0)
    corridor_geometry = substring(trunk_centerline, start_dist, end_dist).buffer(
        corridor_width,
        cap_style=2,
        join_style=2,
    )
    extended_polygon = polygon_geometry.union(
        corridor_geometry.union(primary_main_rc_node.geometry.buffer(RC_NODE_SEED_RADIUS_M))
    ).intersection(drivezone_union).buffer(0)
    covered = extended_polygon.buffer(0).covers(primary_main_rc_node.geometry)
    return {
        "trunk_branch_id": trunk_branch.branch_id,
        "rcsdnode_tolerance_rule": tolerance_rule,
        "rcsdnode_tolerance_applied": covered,
        "rcsdnode_coverage_mode": "trunk_tolerance_extension" if covered else "trunk_tolerance_failed",
        "rcsdnode_offset_m": offset_m,
        "rcsdnode_lateral_dist_m": lateral_dist_m,
        "reason": None if covered else REASON_COVERAGE_INCOMPLETE,
        "extended_polygon_geometry": extended_polygon if covered else polygon_geometry,
        "covered": covered,
    }


def _analyze_divstrip_context(
    *,
    local_divstrip_features: list[Any],
    seed_union,
    road_branches,
    local_roads: list[ParsedRoad],
    main_branch_ids: set[str],
) -> dict[str, Any]:
    if not local_divstrip_features:
        return {
            "present": False,
            "nearby": False,
            "component_count": 0,
            "selected_component_ids": [],
            "constraint_geometry": GeometryCollection(),
            "preferred_branch_ids": [],
            "ambiguous": False,
            "selection_mode": "roads_fallback",
            "evidence_source": "drivezone+roads+rcsd+seed",
        }

    union_geometry = unary_union(
        [feature.geometry for feature in local_divstrip_features if feature.geometry is not None and not feature.geometry.is_empty]
    )
    components = _explode_component_geometries(union_geometry)
    non_main_branches = [branch for branch in road_branches if branch.branch_id not in main_branch_ids]
    branch_geometry_lookup = {
        branch.branch_id: unary_union([road.geometry for road in local_roads if road.road_id in branch.road_ids])
        for branch in non_main_branches
    }

    nearby_components: list[dict[str, Any]] = []
    for component_index, component_geometry in enumerate(components):
        matched_branch_ids = sorted(
            branch_id
            for branch_id, branch_geometry in branch_geometry_lookup.items()
            if branch_geometry is not None
            and not branch_geometry.is_empty
            and branch_geometry.buffer(DIVSTRIP_BRANCH_BUFFER_M, cap_style=2, join_style=2).intersects(component_geometry)
        )
        distance_to_seed = float(component_geometry.distance(seed_union))
        if matched_branch_ids or distance_to_seed <= DIVSTRIP_NEARBY_DISTANCE_M:
            nearby_components.append(
                {
                    "component_id": f"divstrip_component_{component_index}",
                    "geometry": component_geometry,
                    "matched_branch_ids": matched_branch_ids,
                    "distance_to_seed": distance_to_seed,
                }
            )

    if not nearby_components:
        return {
            "present": True,
            "nearby": False,
            "component_count": len(components),
            "selected_component_ids": [],
            "constraint_geometry": GeometryCollection(),
            "preferred_branch_ids": [],
            "ambiguous": False,
            "selection_mode": "roads_fallback",
            "evidence_source": "drivezone+roads+rcsd+seed",
        }

    matched_components = [component for component in nearby_components if component["matched_branch_ids"]]
    selected_components = matched_components or [min(nearby_components, key=lambda component: component["distance_to_seed"])]
    selected_geometry = unary_union([component["geometry"] for component in selected_components])
    ambiguous = len(selected_components) > 1
    preferred_branch_ids = sorted({branch_id for component in selected_components for branch_id in component["matched_branch_ids"]})
    return {
        "present": True,
        "nearby": True,
        "component_count": len(components),
        "selected_component_ids": [component["component_id"] for component in selected_components],
        "constraint_geometry": GeometryCollection() if ambiguous else selected_geometry,
        "preferred_branch_ids": preferred_branch_ids,
        "ambiguous": ambiguous,
        "selection_mode": "divstrip_primary" if preferred_branch_ids and not ambiguous else "roads_fallback",
        "evidence_source": "drivezone+divstrip+roads+rcsd+seed" if preferred_branch_ids and not ambiguous else "drivezone+roads+rcsd+seed",
    }


def _resolve_multibranch_context(
    *,
    road_branches,
    main_branch_ids: set[str],
    preferred_branch_ids: set[str],
    kind_2: int,
    local_roads: list[ParsedRoad],
    member_node_ids: set[str],
    drivezone_union,
    divstrip_constraint_geometry,
) -> dict[str, Any]:
    road_to_branch: dict[str, Any] = {}
    for branch in road_branches:
        for road_id in branch.road_ids:
            road_to_branch[road_id] = branch

    divstrip_geometry = None if divstrip_constraint_geometry is None or divstrip_constraint_geometry.is_empty else divstrip_constraint_geometry
    divstrip_probe_geometry = (
        None
        if divstrip_geometry is None
        else divstrip_geometry.buffer(DIVSTRIP_BRANCH_BUFFER_M, cap_style=2, join_style=2)
    )
    candidate_items: list[dict[str, Any]] = []
    for road in local_roads:
        candidate = _branch_candidate_from_road(
            road,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
        )
        if candidate is None:
            continue
        source_branch = road_to_branch.get(road.road_id)
        candidate_items.append(
            {
                "item_id": road.road_id,
                "source_branch_id": None if source_branch is None else source_branch.branch_id,
                "branch": source_branch,
                "angle_deg": float(candidate["angle_deg"]),
                "road_support_m": float(candidate["road_support_m"]),
                "has_incoming_support": bool(candidate["has_incoming_support"]),
                "has_outgoing_support": bool(candidate["has_outgoing_support"]),
                "divstrip_hit": bool(divstrip_probe_geometry is not None and road.geometry.intersects(divstrip_probe_geometry)),
                "divstrip_distance_m": (
                    math.inf
                    if divstrip_probe_geometry is None
                    else float(road.geometry.distance(divstrip_probe_geometry))
                ),
                "divstrip_overlap_m": (
                    0.0
                    if divstrip_probe_geometry is None
                    else float(road.geometry.intersection(divstrip_probe_geometry).length)
                ),
            }
        )

    best_main_pair_ids: tuple[str, str] | None = None
    best_main_pair_key: tuple[int, float, float] | None = None
    for first_item, second_item in combinations(candidate_items, 2):
        angle_gap = _branch_angle_gap_deg(first_item, second_item)
        if angle_gap < 180.0 - MAIN_AXIS_ANGLE_TOLERANCE_DEG:
            continue
        if not (first_item["has_incoming_support"] or second_item["has_incoming_support"]):
            continue
        if not (first_item["has_outgoing_support"] or second_item["has_outgoing_support"]):
            continue
        pair_key = (
            int(first_item["source_branch_id"] in main_branch_ids) + int(second_item["source_branch_id"] in main_branch_ids),
            -abs(180.0 - angle_gap),
            float(first_item["road_support_m"] + second_item["road_support_m"]),
        )
        if best_main_pair_key is None or pair_key > best_main_pair_key:
            best_main_pair_key = pair_key
            best_main_pair_ids = (str(first_item["item_id"]), str(second_item["item_id"]))

    main_pair_ids = set(best_main_pair_ids or ())
    candidate_items = [item for item in candidate_items if item["item_id"] not in main_pair_ids]
    multibranch_enabled = len(candidate_items) > 2
    if not multibranch_enabled:
        return {
            "enabled": False,
            "n": len(candidate_items),
            "event_candidate_count": 0,
            "selected_event_index": None,
            "selected_event_branch_ids": [],
            "selected_event_source_branch_ids": [],
            "selected_side_branches": [],
            "branches_used_count": 0,
            "ambiguous": False,
        }

    event_candidates: list[dict[str, Any]] = []
    for pair in combinations(candidate_items, 2):
        if pair[0]["source_branch_id"] == pair[1]["source_branch_id"]:
            continue
        pair_ids = sorted(str(item["item_id"]) for item in pair)
        pair_branches = [item["branch"] for item in pair if item["branch"] is not None]
        if len(pair_branches) != 2:
            continue
        preferred_hits = len({str(item["source_branch_id"]) for item in pair if item["source_branch_id"] is not None} & preferred_branch_ids)
        adjacency_gap = _branch_angle_gap_deg(pair[0], pair[1])
        divstrip_hit_count = sum(1 for item in pair if item["divstrip_hit"])
        divstrip_overlap_m = float(sum(item["divstrip_overlap_m"] for item in pair))
        divstrip_distance_m = float(min(item["divstrip_distance_m"] for item in pair))
        directional_hits = (
            sum(1 for item in pair if item["has_incoming_support"])
            if kind_2 == 8
            else sum(1 for item in pair if item["has_outgoing_support"])
        )
        score = (
            float(sum(item["road_support_m"] for item in pair))
            + preferred_hits * 100.0
            + divstrip_hit_count * 50.0
            + divstrip_overlap_m * 5.0
            + directional_hits * 25.0
            - adjacency_gap * 0.1
            - divstrip_distance_m * 0.25
        )
        event_candidates.append(
            {
                "branch_ids": pair_ids,
                "branches": pair_branches,
                "score": score,
                "preferred_hits": preferred_hits,
                "divstrip_hit_count": divstrip_hit_count,
                "divstrip_overlap_m": divstrip_overlap_m,
                "divstrip_distance_m": divstrip_distance_m,
                "directional_hits": directional_hits,
                "adjacency_gap": adjacency_gap,
            }
        )

    event_candidates.sort(
        key=lambda candidate: (
            candidate["preferred_hits"],
            candidate["divstrip_hit_count"],
            candidate["divstrip_overlap_m"],
            candidate["directional_hits"],
            candidate["score"],
            -candidate["divstrip_distance_m"],
            -candidate["adjacency_gap"],
        ),
        reverse=True,
    )
    top_candidate = event_candidates[0] if event_candidates else None
    ambiguous = False
    if len(event_candidates) > 1 and top_candidate is not None:
        second_candidate = event_candidates[1]
        ambiguous = (
            abs(float(top_candidate["score"]) - float(second_candidate["score"])) <= MULTIBRANCH_AMBIGUITY_SCORE_MARGIN
            and top_candidate["divstrip_hit_count"] == second_candidate["divstrip_hit_count"]
            and abs(float(top_candidate["divstrip_overlap_m"]) - float(second_candidate["divstrip_overlap_m"])) <= 1.0
            and top_candidate["directional_hits"] == second_candidate["directional_hits"]
            and {branch.branch_id for branch in top_candidate["branches"]} != {branch.branch_id for branch in second_candidate["branches"]}
            and top_candidate["branch_ids"] != second_candidate["branch_ids"]
        )
    return {
        "enabled": True,
        "n": len(candidate_items),
        "event_candidate_count": len(event_candidates),
        "selected_event_index": 0 if top_candidate is not None else None,
        "selected_event_branch_ids": [] if top_candidate is None else list(top_candidate["branch_ids"]),
        "selected_event_source_branch_ids": (
            []
            if top_candidate is None
            else sorted({branch.branch_id for branch in top_candidate["branches"]})
        ),
        "selected_side_branches": [] if top_candidate is None else list(top_candidate["branches"]),
        "branches_used_count": 0 if top_candidate is None else len({branch.branch_id for branch in top_candidate["branches"]}),
        "ambiguous": ambiguous,
    }


def _is_stage4_representative(node: ParsedNode) -> bool:
    representative_id = node.mainnodeid or node.node_id
    return (
        node.has_evd == "yes"
        and node.is_anchor == "no"
        and node.kind_2 in STAGE4_KIND_2_VALUES
        and normalize_id(node.node_id) == normalize_id(representative_id)
    )


def _build_continuous_chain_context(
    *,
    representative_node: ParsedNode,
    local_nodes: list[ParsedNode],
) -> dict[str, Any]:
    representative_mainnodeid = normalize_id(representative_node.mainnodeid or representative_node.node_id)
    chain_candidates: list[tuple[ParsedNode, float]] = []
    for candidate in local_nodes:
        if not _is_stage4_representative(candidate):
            continue
        candidate_mainnodeid = normalize_id(candidate.mainnodeid or candidate.node_id)
        if candidate_mainnodeid == representative_mainnodeid:
            continue
        offset_m = float(candidate.geometry.distance(representative_node.geometry))
        if offset_m <= CHAIN_NEARBY_DISTANCE_M:
            chain_candidates.append((candidate, offset_m))

    chain_candidates.sort(key=lambda item: item[1])
    related_mainnodeids = [normalize_id(candidate.mainnodeid or candidate.node_id) for candidate, _ in chain_candidates]
    nearest_offset_m = None if not chain_candidates else round(chain_candidates[0][1], 3)
    sequential_ok = any(
        offset_m <= CHAIN_SEQUENCE_DISTANCE_M and candidate.kind_2 != representative_node.kind_2
        for candidate, offset_m in chain_candidates
    )
    chain_member_ids = [representative_mainnodeid, *related_mainnodeids]
    return {
        "chain_component_id": "__".join(sorted(chain_member_ids)) if len(chain_member_ids) > 1 else representative_mainnodeid,
        "related_mainnodeids": related_mainnodeids,
        "is_in_continuous_chain": bool(chain_candidates),
        "chain_node_count": 1 + len(chain_candidates),
        "chain_node_offset_m": nearest_offset_m,
        "sequential_ok": sequential_ok,
        "related_seed_nodes": [candidate for candidate, offset_m in chain_candidates if offset_m <= CHAIN_SEQUENCE_DISTANCE_M],
    }


def run_t02_stage4_divmerge_virtual_polygon(
    *,
    nodes_path: Union[str, Path],
    roads_path: Union[str, Path],
    drivezone_path: Union[str, Path],
    divstripzone_path: Optional[Union[str, Path]] = None,
    rcsdroad_path: Union[str, Path],
    rcsdnode_path: Union[str, Path],
    mainnodeid: Union[str, int],
    out_root: Optional[Union[str, Path]] = None,
    run_id: Optional[str] = None,
    nodes_layer: Optional[str] = None,
    roads_layer: Optional[str] = None,
    drivezone_layer: Optional[str] = None,
    divstripzone_layer: Optional[str] = None,
    rcsdroad_layer: Optional[str] = None,
    rcsdnode_layer: Optional[str] = None,
    nodes_crs: Optional[str] = None,
    roads_crs: Optional[str] = None,
    drivezone_crs: Optional[str] = None,
    divstripzone_crs: Optional[str] = None,
    rcsdroad_crs: Optional[str] = None,
    rcsdnode_crs: Optional[str] = None,
    debug: bool = False,
    trace_memory: bool = True,
) -> Stage4Artifacts:
    if trace_memory and not tracemalloc.is_tracing():
        tracemalloc.start()

    started_at = time.perf_counter()
    out_root_path, resolved_run_id = _resolve_out_root(out_root=out_root, run_id=run_id)
    out_root_path.mkdir(parents=True, exist_ok=True)

    virtual_polygon_path = out_root_path / "stage4_virtual_polygon.gpkg"
    node_link_json_path = out_root_path / "stage4_node_link.json"
    rcsdnode_link_json_path = out_root_path / "stage4_rcsdnode_link.json"
    audit_json_path = out_root_path / "stage4_audit.json"
    status_path = out_root_path / "stage4_status.json"
    log_path = out_root_path / "stage4_divmerge_virtual_polygon.log"
    progress_path = out_root_path / "stage4_progress.json"
    perf_json_path = out_root_path / "stage4_perf.json"
    perf_markers_path = out_root_path / "stage4_perf_markers.jsonl"
    debug_dir = out_root_path / "stage4_debug" if debug else None
    debug_render_path = debug_dir / f"{normalize_id(mainnodeid) or 'unknown'}.png" if debug_dir is not None else None

    logger = build_logger(log_path, f"t02_stage4_divmerge_virtual_polygon.{resolved_run_id}")
    counts: dict[str, Any] = {
        "mainnodeid": normalize_id(mainnodeid),
        "node_feature_count": 0,
        "road_feature_count": 0,
        "drivezone_feature_count": 0,
        "divstripzone_feature_count": 0,
        "rcsdroad_feature_count": 0,
        "rcsdnode_feature_count": 0,
        "target_node_count": 0,
        "target_rcsdnode_count": 0,
        "selected_branch_count": 0,
        "selected_road_count": 0,
        "selected_rcsdroad_count": 0,
        "selected_rcsdnode_count": 0,
        "audit_count": 0,
    }
    audit_rows: list[dict[str, Any]] = []
    stage_timings: list[dict[str, Any]] = []

    def _snapshot(status: str, current_stage: str | None, message: str) -> None:
        counts["audit_count"] = len(audit_rows)
        _write_progress_snapshot(
            out_path=progress_path,
            run_id=resolved_run_id,
            status=status,
            current_stage=current_stage,
            message=message,
            counts=dict(counts),
        )

    def _mark(stage_name: str, started_at_stage: float, note: str | None = None) -> None:
        elapsed_sec = time.perf_counter() - started_at_stage
        stage_timings.append(
            {
                "stage": stage_name,
                "elapsed_sec": round(elapsed_sec, 6),
                **_tracemalloc_stats(),
            }
        )
        _record_perf_marker(
            out_path=perf_markers_path,
            run_id=resolved_run_id,
            stage=stage_name,
            elapsed_sec=elapsed_sec,
            counts=dict(counts),
            note=note,
        )

    def _write_link_json(path: Path, payload: dict[str, Any]) -> None:
        write_json(path, payload)

    try:
        _snapshot("running", "bootstrap", "Stage4 bootstrap started.")
        announce(logger, f"[T02-Stage4] start run_id={resolved_run_id}")

        load_started_at = time.perf_counter()
        nodes_layer_data = _load_layer(
            nodes_path,
            layer_name=nodes_layer,
            crs_override=nodes_crs,
            allow_null_geometry=False,
        )
        roads_layer_data = _load_layer(
            roads_path,
            layer_name=roads_layer,
            crs_override=roads_crs,
            allow_null_geometry=False,
        )
        drivezone_layer_data = _load_layer(
            drivezone_path,
            layer_name=drivezone_layer,
            crs_override=drivezone_crs,
            allow_null_geometry=False,
        )
        rcsdroad_layer_data = _load_layer(
            rcsdroad_path,
            layer_name=rcsdroad_layer,
            crs_override=rcsdroad_crs,
            allow_null_geometry=False,
        )
        rcsdnode_layer_data = _load_layer(
            rcsdnode_path,
            layer_name=rcsdnode_layer,
            crs_override=rcsdnode_crs,
            allow_null_geometry=False,
        )
        counts["node_feature_count"] = len(nodes_layer_data.features)
        counts["road_feature_count"] = len(roads_layer_data.features)
        counts["drivezone_feature_count"] = len(drivezone_layer_data.features)
        counts["rcsdroad_feature_count"] = len(rcsdroad_layer_data.features)
        counts["rcsdnode_feature_count"] = len(rcsdnode_layer_data.features)
        _snapshot("running", "inputs_loaded", "Input layers loaded and projected to EPSG:3857.")
        _mark("inputs_loaded", load_started_at)

        nodes = _parse_nodes(nodes_layer_data, require_anchor_fields=True)
        roads = _parse_roads(roads_layer_data, label="Road")
        rcsd_roads = _parse_roads(rcsdroad_layer_data, label="RCSDRoad")
        rcsd_nodes = _parse_rc_nodes(rcsdnode_layer_data)

        mainnodeid_norm = normalize_id(mainnodeid)
        if mainnodeid_norm is None:
            raise Stage4RunError(REASON_MAINNODEID_NOT_FOUND, "mainnodeid is empty.")

        target_group = _resolve_group(mainnodeid=mainnodeid_norm, nodes=nodes)
        representative_node, group_nodes = target_group
        representative_kind_2 = representative_node.kind_2
        representative_grade_2 = representative_node.grade_2
        if representative_node.has_evd != "yes" or representative_node.is_anchor != "no" or representative_kind_2 not in STAGE4_KIND_2_VALUES:
            raise Stage4RunError(
                REASON_MAINNODEID_OUT_OF_SCOPE,
                (
                    f"mainnodeid='{mainnodeid_norm}' is out of scope: "
                    f"has_evd={representative_node.has_evd}, is_anchor={representative_node.is_anchor}, "
                    f"kind_2={representative_kind_2}."
                ),
            )

        target_rc_nodes = [
            node
            for node in rcsd_nodes
            if node.mainnodeid == mainnodeid_norm or (node.mainnodeid is None and node.node_id == mainnodeid_norm)
        ]
        if not target_rc_nodes:
            raise Stage4RunError(
                REASON_MAINNODEID_NOT_FOUND,
                f"RCSDNode has no seed group for mainnodeid='{mainnodeid_norm}'.",
            )
        primary_main_rc_node = _pick_primary_main_rc_node(
            target_rc_nodes=target_rc_nodes,
            mainnodeid_norm=mainnodeid_norm,
        )
        exact_target_rc_nodes = [
            node
            for node in target_rc_nodes
            if primary_main_rc_node is None or normalize_id(node.node_id) != normalize_id(primary_main_rc_node.node_id)
        ]

        drivezone_union = unary_union([feature.geometry for feature in drivezone_layer_data.features if feature.geometry is not None and not feature.geometry.is_empty])
        if drivezone_union.is_empty:
            raise Stage4RunError(REASON_MISSING_REQUIRED_FIELD, "DriveZone layer has no non-empty geometry.")

        _validate_drivezone_containment(drivezone_union=drivezone_union, features=rcsd_roads, label="RCSDRoad")
        _validate_drivezone_containment(drivezone_union=drivezone_union, features=rcsd_nodes, label="RCSDNode")

        seed_geometries = [representative_node.geometry, *[node.geometry for node in group_nodes], *[node.geometry for node in exact_target_rc_nodes]]
        seed_union = unary_union(seed_geometries)
        seed_center = seed_union.centroid if not seed_union.is_empty else representative_node.geometry
        farthest_seed_distance = max((float(Point(seed.x, seed.y).distance(seed_center)) for seed in [representative_node.geometry, *[node.geometry for node in group_nodes], *[node.geometry for node in exact_target_rc_nodes]]), default=0.0)
        patch_size_m = max(DEFAULT_PATCH_SIZE_M, farthest_seed_distance * 2.0 + 60.0)
        grid = _build_grid(seed_center, patch_size_m=patch_size_m, resolution_m=DEFAULT_RESOLUTION_M)
        drivezone_mask = _rasterize_geometries(grid, [drivezone_union])
        divstripzone_layer_data = None
        if divstripzone_path is not None:
            divstripzone_layer_data = _load_layer(
                divstripzone_path,
                layer_name=divstripzone_layer,
                crs_override=divstripzone_crs,
                allow_null_geometry=False,
                query_geometry=grid.patch_polygon,
            )
            counts["divstripzone_feature_count"] = len(divstripzone_layer_data.features)

        local_nodes = [node for node in nodes if node.geometry.intersects(grid.patch_polygon)]
        local_roads = [road for road in roads if road.geometry.intersects(grid.patch_polygon)]
        local_rcsd_roads = [road for road in rcsd_roads if road.geometry.intersects(grid.patch_polygon)]
        local_rcsd_nodes = [node for node in rcsd_nodes if node.geometry.intersects(grid.patch_polygon)]
        local_divstrip_features = [
            feature
            for feature in ([] if divstripzone_layer_data is None else divstripzone_layer_data.features)
            if feature.geometry is not None and not feature.geometry.is_empty
        ]

        member_node_ids = {node.node_id for node in group_nodes}
        _, _, road_branches = _build_road_branches_for_member_nodes(
            local_roads,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
        )
        if len(road_branches) < 2:
            raise Stage4RunError(
                REASON_MAIN_DIRECTION_UNSTABLE,
                "Need at least two incident road branches to identify a stable Stage4 face.",
            )
        main_branch_ids = set(_select_main_pair(road_branches))
        divstrip_context = _analyze_divstrip_context(
            local_divstrip_features=local_divstrip_features,
            seed_union=seed_union,
            road_branches=road_branches,
            local_roads=local_roads,
            main_branch_ids=main_branch_ids,
        )
        preferred_branch_ids = set(divstrip_context["preferred_branch_ids"])
        multibranch_context = _resolve_multibranch_context(
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            preferred_branch_ids=preferred_branch_ids,
            kind_2=representative_kind_2 or 0,
            local_roads=local_roads,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
            divstrip_constraint_geometry=divstrip_context["constraint_geometry"],
        )
        chain_context = _build_continuous_chain_context(
            representative_node=representative_node,
            local_nodes=local_nodes,
        )
        forward_side_branches = _select_stage4_side_branches(
            road_branches,
            kind_2=representative_kind_2 or 0,
            preferred_branch_ids=preferred_branch_ids,
        )
        forward_branch_ids = {branch.branch_id for branch in forward_side_branches}
        position_source_forward = divstrip_context["selection_mode"]
        reverse_trigger: str | None = None
        if not multibranch_context["enabled"]:
            if preferred_branch_ids and not (forward_branch_ids & preferred_branch_ids):
                reverse_trigger = "forward_divstrip_mismatch"
            elif not divstrip_context["nearby"]:
                reverse_trigger = "divstrip_not_nearby"

        reverse_tip_attempted = reverse_trigger is not None
        reverse_tip_used = False
        position_source_reverse: str | None = None
        reverse_side_branches: list[Any] = []
        selected_side_branches = list(multibranch_context["selected_side_branches"]) if multibranch_context["enabled"] else list(forward_side_branches)
        if reverse_tip_attempted:
            reverse_side_branches = _select_reverse_tip_side_branches(
                road_branches,
                kind_2=representative_kind_2 or 0,
                preferred_branch_ids=preferred_branch_ids,
            )
            position_source_reverse = "reverse_tip_divstrip" if ({branch.branch_id for branch in reverse_side_branches} & preferred_branch_ids) else "reverse_tip_roads"
            if (
                {branch.branch_id for branch in reverse_side_branches} != forward_branch_ids
                and _branch_selection_quality(reverse_side_branches, preferred_branch_ids)
                > _branch_selection_quality(forward_side_branches, preferred_branch_ids)
            ):
                reverse_tip_used = True
                selected_side_branches = list(reverse_side_branches)

        position_source_final = (
            position_source_reverse
            if reverse_tip_used and position_source_reverse is not None
            else ("multibranch_event" if multibranch_context["enabled"] else position_source_forward)
        )
        selected_event_branch_ids = (
            multibranch_context["selected_event_branch_ids"]
            if multibranch_context["enabled"]
            else sorted(branch.branch_id for branch in selected_side_branches)
        )
        selected_branch_ids = (
            sorted(multibranch_context["selected_event_source_branch_ids"])
            if multibranch_context["enabled"]
            else sorted(main_branch_ids | {branch.branch_id for branch in selected_side_branches})
        )

        selected_road_ids = sorted({road_id for branch in road_branches if branch.branch_id in selected_branch_ids for road_id in branch.road_ids})
        selected_rcsdroad_ids: set[str] = set()
        _, _, rc_branches = _build_road_branches_for_member_nodes(
            local_rcsd_roads,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
        )
        for rc_branch in rc_branches:
            for road_branch in road_branches:
                if road_branch.branch_id not in selected_branch_ids:
                    continue
                if abs(road_branch.angle_deg - rc_branch.angle_deg) <= 35.0 or min(abs(road_branch.angle_deg - rc_branch.angle_deg), 360.0 - abs(road_branch.angle_deg - rc_branch.angle_deg)) <= 35.0:
                    selected_rcsdroad_ids.update(rc_branch.road_ids)
                    break
        if not selected_rcsdroad_ids:
            selected_rcsdroad_ids = {road.road_id for road in local_rcsd_roads if road.geometry.distance(seed_center) <= max(30.0, patch_size_m / 5.0)}

        selected_roads = [road for road in local_roads if road.road_id in selected_road_ids]
        selected_rcsd_roads = [road for road in local_rcsd_roads if road.road_id in selected_rcsdroad_ids]
        selected_rcsdnode_ids = {
            node.node_id
            for node in local_rcsd_nodes
            if node.mainnodeid == mainnodeid_norm or node.node_id in {road.snodeid for road in selected_rcsd_roads} | {road.enodeid for road in selected_rcsd_roads}
        }
        if not selected_rcsdnode_ids:
            selected_rcsdnode_ids = {node.node_id for node in target_rc_nodes}

        seed_support_geometries = [
            *[node.geometry.buffer(NODE_SEED_RADIUS_M) for node in group_nodes],
            *[node.geometry.buffer(RC_NODE_SEED_RADIUS_M) for node in exact_target_rc_nodes],
        ]
        if chain_context["sequential_ok"]:
            seed_support_geometries.extend(
                node.geometry.buffer(max(1.5, NODE_SEED_RADIUS_M * 0.6))
                for node in chain_context["related_seed_nodes"]
            )
        support_geometries = [
            *[road.geometry.buffer(ROAD_BUFFER_M, cap_style=2, join_style=2) for road in selected_roads],
            *[road.geometry.buffer(RC_ROAD_BUFFER_M, cap_style=2, join_style=2) for road in selected_rcsd_roads],
            *seed_support_geometries,
        ]
        seed_mask = _rasterize_geometries(
            grid,
            seed_support_geometries,
        )
        support_mask = _rasterize_geometries(grid, support_geometries) & drivezone_mask
        divstrip_constraint_geometry = divstrip_context["constraint_geometry"]
        if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty:
            divstrip_mask = _rasterize_geometries(
                grid,
                [divstrip_constraint_geometry.buffer(DIVSTRIP_EXCLUSION_BUFFER_M, join_style=2)],
            )
            support_mask = support_mask & ~(divstrip_mask & ~seed_mask)
        support_mask = _binary_close(support_mask, iterations=1)
        component_mask = _extract_seed_component(support_mask, seed_mask)
        if not component_mask.any():
            raise Stage4RunError(
                REASON_MAIN_DIRECTION_UNSTABLE,
                "Stage4 raster support could not form a seed-connected component.",
            )

        polygon_geometry = _mask_to_geometry(component_mask, grid)
        polygon_geometry = _regularize_virtual_polygon_geometry(
            geometry=polygon_geometry,
            drivezone_union=drivezone_union,
            seed_geometry=seed_union,
        )
        if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty:
            clip_geometry = divstrip_constraint_geometry.buffer(DIVSTRIP_EXCLUSION_BUFFER_M, join_style=2).difference(
                seed_union.buffer(max(NODE_SEED_RADIUS_M, RC_NODE_SEED_RADIUS_M))
            )
            if not clip_geometry.is_empty:
                clipped_polygon = polygon_geometry.difference(clip_geometry).buffer(0)
                if not clipped_polygon.is_empty:
                    polygon_geometry = clipped_polygon
        if polygon_geometry.is_empty:
            raise Stage4RunError(
                REASON_MAIN_DIRECTION_UNSTABLE,
                "Stage4 regularized polygon is empty.",
            )

        primary_rcsdnode_tolerance = _evaluate_primary_rcsdnode_tolerance(
            polygon_geometry=polygon_geometry,
            primary_main_rc_node=primary_main_rc_node,
            representative_node=representative_node,
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            local_roads=local_roads,
            kind_2=representative_kind_2 or 0,
            drivezone_union=drivezone_union,
        )
        polygon_geometry = primary_rcsdnode_tolerance["extended_polygon_geometry"]
        coverage_missing_ids = _cover_check(polygon_geometry, [*group_nodes, *exact_target_rc_nodes])
        primary_main_rc_node_id = None if primary_main_rc_node is None else normalize_id(primary_main_rc_node.node_id)
        if primary_main_rc_node_id is not None and not primary_rcsdnode_tolerance["covered"]:
            coverage_missing_ids.append(primary_main_rc_node_id)
        coverage_missing_ids = sorted(set(coverage_missing_ids))
        review_reasons: list[str] = []
        if primary_rcsdnode_tolerance["reason"] is not None:
            review_reasons.append(primary_rcsdnode_tolerance["reason"])
        if multibranch_context["ambiguous"]:
            review_reasons.append(STATUS_MULTIBRANCH_EVENT_AMBIGUOUS)
        if not divstrip_context["nearby"] and divstripzone_path is not None:
            review_reasons.append(STATUS_DIVSTRIP_NOT_NEARBY)
        if divstrip_context["ambiguous"]:
            review_reasons.append(STATUS_DIVSTRIP_COMPONENT_AMBIGUOUS)
        if chain_context["is_in_continuous_chain"] and chain_context["sequential_ok"]:
            review_reasons.append(STATUS_CONTINUOUS_CHAIN_REVIEW)
        if coverage_missing_ids:
            review_reasons.append(REASON_COVERAGE_INCOMPLETE)
        acceptance_class = "accepted" if not review_reasons else "review_required"
        acceptance_reason = "stable" if not review_reasons else review_reasons[0]
        success = acceptance_class == "accepted"

        counts["target_node_count"] = len(group_nodes)
        counts["target_rcsdnode_count"] = len(target_rc_nodes)
        counts["selected_branch_count"] = len(selected_branch_ids)
        counts["selected_road_count"] = len(selected_roads)
        counts["selected_rcsdroad_count"] = len(selected_rcsd_roads)
        counts["selected_rcsdnode_count"] = len(selected_rcsdnode_ids)

        polygon_feature = {
            "properties": {
                "mainnodeid": mainnodeid_norm,
                "kind_2": representative_kind_2,
                "grade_2": representative_grade_2,
                "status": acceptance_reason,
                "acceptance_class": acceptance_class,
                "acceptance_reason": acceptance_reason,
                "target_node_count": len(group_nodes),
                "target_rcsdnode_count": len(target_rc_nodes),
                "selected_branch_count": len(selected_branch_ids),
                "selected_road_count": len(selected_roads),
                "selected_rcsdroad_count": len(selected_rcsd_roads),
                "selected_rcsdnode_count": len(selected_rcsdnode_ids),
                "coverage_missing_count": len(coverage_missing_ids),
                "divstrip_present": int(divstrip_context["present"]),
                "divstrip_nearby": int(divstrip_context["nearby"]),
                "divstrip_component_count": int(divstrip_context["component_count"]),
                "evidence_source": divstrip_context["evidence_source"],
                "selection_mode": divstrip_context["selection_mode"],
                "multibranch_enabled": int(multibranch_context["enabled"]),
                "multibranch_n": int(multibranch_context["n"]),
                "event_candidate_count": int(multibranch_context["event_candidate_count"]),
                "selected_event_index": multibranch_context["selected_event_index"],
                "branches_used_count": len(selected_branch_ids),
                "reverse_tip_attempted": int(reverse_tip_attempted),
                "reverse_tip_used": int(reverse_tip_used),
                "is_in_continuous_chain": int(chain_context["is_in_continuous_chain"]),
                "chain_node_count": int(chain_context["chain_node_count"]),
                "trunk_branch_id": primary_rcsdnode_tolerance["trunk_branch_id"],
                "rcsdnode_tolerance_applied": int(primary_rcsdnode_tolerance["rcsdnode_tolerance_applied"]),
                "rcsdnode_offset_m": primary_rcsdnode_tolerance["rcsdnode_offset_m"],
                "rcsdnode_lateral_dist_m": primary_rcsdnode_tolerance["rcsdnode_lateral_dist_m"],
            },
            "geometry": polygon_geometry,
        }
        write_vector(virtual_polygon_path, [polygon_feature], crs_text=TARGET_CRS.to_string())

        node_link_doc = _make_link_doc(
            mainnodeid=mainnodeid_norm,
            kind_2=representative_kind_2 or 0,
            grade_2=representative_grade_2,
            target_node_ids=[node.node_id for node in group_nodes],
            linked_node_ids=[node.node_id for node in group_nodes],
            selected_branch_ids=selected_branch_ids,
            selected_road_ids=selected_road_ids,
            coverage_missing_ids=coverage_missing_ids,
        )
        node_link_doc.update(
            {
                "multibranch_enabled": multibranch_context["enabled"],
                "selected_event_branch_ids": selected_event_branch_ids,
                "branches_used_count": len(selected_branch_ids),
                "position_source_final": position_source_final,
                "related_mainnodeids": chain_context["related_mainnodeids"],
                "trunk_branch_id": primary_rcsdnode_tolerance["trunk_branch_id"],
            }
        )
        rcsdnode_link_doc = _make_link_doc(
            mainnodeid=mainnodeid_norm,
            kind_2=representative_kind_2 or 0,
            grade_2=representative_grade_2,
            target_node_ids=[node.node_id for node in target_rc_nodes],
            linked_node_ids=sorted(selected_rcsdnode_ids),
            selected_branch_ids=selected_branch_ids,
            selected_road_ids=sorted(selected_rcsdroad_ids),
            coverage_missing_ids=coverage_missing_ids,
        )
        rcsdnode_link_doc.update(
            {
                "multibranch_enabled": multibranch_context["enabled"],
                "selected_event_branch_ids": selected_event_branch_ids,
                "branches_used_count": len(selected_branch_ids),
                "position_source_final": position_source_final,
                "related_mainnodeids": chain_context["related_mainnodeids"],
                "trunk_branch_id": primary_rcsdnode_tolerance["trunk_branch_id"],
                "rcsdnode_tolerance_rule": primary_rcsdnode_tolerance["rcsdnode_tolerance_rule"],
                "rcsdnode_tolerance_applied": primary_rcsdnode_tolerance["rcsdnode_tolerance_applied"],
                "rcsdnode_coverage_mode": primary_rcsdnode_tolerance["rcsdnode_coverage_mode"],
                "rcsdnode_offset_m": primary_rcsdnode_tolerance["rcsdnode_offset_m"],
                "rcsdnode_lateral_dist_m": primary_rcsdnode_tolerance["rcsdnode_lateral_dist_m"],
            }
        )
        _write_link_json(node_link_json_path, node_link_doc)
        _write_link_json(rcsdnode_link_json_path, rcsdnode_link_doc)

        if debug and debug_render_path is not None:
            debug_dir = debug_render_path.parent
            debug_dir.mkdir(parents=True, exist_ok=True)
            _write_debug_rendered_map(
                out_path=debug_render_path,
                grid=grid,
                drivezone_mask=drivezone_mask,
                polygon_geometry=polygon_geometry,
                representative_node=representative_node,
                group_nodes=group_nodes,
                local_nodes=local_nodes,
                local_roads=local_roads,
                local_rc_nodes=local_rcsd_nodes,
                local_rc_roads=local_rcsd_roads,
                selected_rc_roads=selected_rcsd_roads,
                selected_rc_node_ids=selected_rcsdnode_ids,
                excluded_rc_road_ids={local_road.road_id for local_road in local_rcsd_roads if local_road.road_id not in selected_rcsdroad_ids},
                excluded_rc_node_ids={node.node_id for node in local_rcsd_nodes if node.node_id not in selected_rcsdnode_ids},
                failure_reason=None if acceptance_class == "accepted" else acceptance_reason,
            )

        status_doc = {
            "run_id": resolved_run_id,
            "success": success,
            "flow_success": True,
            "acceptance_class": acceptance_class,
            "acceptance_reason": acceptance_reason,
            "mainnodeid": mainnodeid_norm,
            "kind_2": representative_kind_2,
            "grade_2": representative_grade_2,
            "counts": counts,
            "coverage_missing_ids": coverage_missing_ids,
            "review_reasons": review_reasons,
            "multibranch": {
                "multibranch_enabled": multibranch_context["enabled"],
                "multibranch_n": multibranch_context["n"],
                "event_candidate_count": multibranch_context["event_candidate_count"],
                "selected_event_index": multibranch_context["selected_event_index"],
                "selected_event_branch_ids": selected_event_branch_ids,
                "branches_used_count": len(selected_branch_ids),
            },
            "reverse_tip": {
                "reverse_tip_attempted": reverse_tip_attempted,
                "reverse_tip_used": reverse_tip_used,
                "reverse_trigger": reverse_trigger,
                "position_source_forward": position_source_forward,
                "position_source_reverse": position_source_reverse,
                "position_source_final": position_source_final,
            },
            "continuous_chain": {
                "chain_component_id": chain_context["chain_component_id"],
                "related_mainnodeids": chain_context["related_mainnodeids"],
                "is_in_continuous_chain": chain_context["is_in_continuous_chain"],
                "chain_node_count": chain_context["chain_node_count"],
                "chain_node_offset_m": chain_context["chain_node_offset_m"],
                "sequential_ok": chain_context["sequential_ok"],
            },
            "divstrip": {
                "divstrip_present": divstrip_context["present"],
                "divstrip_nearby": divstrip_context["nearby"],
                "divstrip_component_count": divstrip_context["component_count"],
                "divstrip_component_selected": divstrip_context["selected_component_ids"],
                "selection_mode": divstrip_context["selection_mode"],
                "evidence_source": divstrip_context["evidence_source"],
            },
            "rcsdnode_tolerance": {
                "trunk_branch_id": primary_rcsdnode_tolerance["trunk_branch_id"],
                "rcsdnode_tolerance_rule": primary_rcsdnode_tolerance["rcsdnode_tolerance_rule"],
                "rcsdnode_tolerance_applied": primary_rcsdnode_tolerance["rcsdnode_tolerance_applied"],
                "rcsdnode_coverage_mode": primary_rcsdnode_tolerance["rcsdnode_coverage_mode"],
                "rcsdnode_offset_m": primary_rcsdnode_tolerance["rcsdnode_offset_m"],
                "rcsdnode_lateral_dist_m": primary_rcsdnode_tolerance["rcsdnode_lateral_dist_m"],
            },
            "output_files": {
                "stage4_virtual_polygon": str(virtual_polygon_path),
                "stage4_node_link": str(node_link_json_path),
                "stage4_rcsdnode_link": str(rcsdnode_link_json_path),
                "stage4_audit": str(audit_json_path),
                "stage4_debug": str(debug_dir) if debug_dir is not None else None,
            },
        }
        audit_rows.append(
            {
                "scope": "stage4_divmerge_virtual_polygon",
                "status": "warning" if review_reasons else "info",
                "reason": acceptance_reason,
                "detail": (
                    "Coverage incomplete for selected node/RCSDNode seed(s)."
                    if coverage_missing_ids
                    else (
                        "Stage4 polygon requires manual review because DivStripZone evidence is missing or ambiguous."
                        if review_reasons
                        else "Stage4 polygon accepted."
                    )
                ),
                "coverage_missing_ids": coverage_missing_ids,
                "review_reasons": review_reasons,
                "divstrip_present": divstrip_context["present"],
                "divstrip_nearby": divstrip_context["nearby"],
                "divstrip_component_count": divstrip_context["component_count"],
                "divstrip_component_selected": divstrip_context["selected_component_ids"],
                "selection_mode": divstrip_context["selection_mode"],
                "evidence_source": divstrip_context["evidence_source"],
                "trunk_branch_id": primary_rcsdnode_tolerance["trunk_branch_id"],
                "rcsdnode_tolerance_rule": primary_rcsdnode_tolerance["rcsdnode_tolerance_rule"],
                "rcsdnode_tolerance_applied": primary_rcsdnode_tolerance["rcsdnode_tolerance_applied"],
                "rcsdnode_coverage_mode": primary_rcsdnode_tolerance["rcsdnode_coverage_mode"],
                "rcsdnode_offset_m": primary_rcsdnode_tolerance["rcsdnode_offset_m"],
                "rcsdnode_lateral_dist_m": primary_rcsdnode_tolerance["rcsdnode_lateral_dist_m"],
                "multibranch_enabled": multibranch_context["enabled"],
                "multibranch_n": multibranch_context["n"],
                "event_candidate_count": multibranch_context["event_candidate_count"],
                "selected_event_index": multibranch_context["selected_event_index"],
                "selected_event_branch_ids": selected_event_branch_ids,
                "branches_used_count": len(selected_branch_ids),
                "reverse_tip_attempted": reverse_tip_attempted,
                "reverse_tip_used": reverse_tip_used,
                "reverse_trigger": reverse_trigger,
                "position_source_forward": position_source_forward,
                "position_source_reverse": position_source_reverse,
                "position_source_final": position_source_final,
                "chain_component_id": chain_context["chain_component_id"],
                "related_mainnodeids": chain_context["related_mainnodeids"],
                "is_in_continuous_chain": chain_context["is_in_continuous_chain"],
                "chain_node_count": chain_context["chain_node_count"],
                "chain_node_offset_m": chain_context["chain_node_offset_m"],
                "sequential_ok": chain_context["sequential_ok"],
            }
        )
        write_json(audit_json_path, {"run_id": resolved_run_id, "audit_count": len(audit_rows), "rows": audit_rows})
        write_json(status_path, status_doc)
        _snapshot("success" if success else "completed_with_review_required_result", "complete", "Stage4 completed.")

        perf_doc = {
            "run_id": resolved_run_id,
            "success": success,
            "flow_success": True,
            "acceptance_class": acceptance_class,
            "acceptance_reason": acceptance_reason,
            "counts": counts,
            "stage_timings": stage_timings,
            "total_wall_time_sec": round(time.perf_counter() - started_at, 6),
            **_tracemalloc_stats(),
        }
        write_json(perf_json_path, perf_doc)
        announce(
            logger,
            (
                "[T02-Stage4] complete "
                f"acceptance_class={acceptance_class} selected_road_count={counts['selected_road_count']} "
                f"selected_rcsdroad_count={counts['selected_rcsdroad_count']} out_root={out_root_path}"
            ),
        )
        return Stage4Artifacts(
            success=success,
            out_root=out_root_path,
            virtual_polygon_path=virtual_polygon_path,
            node_link_json_path=node_link_json_path,
            rcsdnode_link_json_path=rcsdnode_link_json_path,
            audit_json_path=audit_json_path,
            status_path=status_path,
            log_path=log_path,
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_markers_path=perf_markers_path,
            debug_dir=debug_dir,
            status_doc=status_doc,
            perf_doc=perf_doc,
        )
    except Stage4RunError as exc:
        audit_rows.append(
            {
                "scope": "stage4_divmerge_virtual_polygon",
                "status": "failed",
                "reason": exc.reason,
                "detail": exc.detail,
                "mainnodeid": normalize_id(mainnodeid),
            }
        )
        counts["audit_count"] = len(audit_rows)
        _snapshot("failed", "failed", exc.detail)
        write_json(audit_json_path, {"run_id": resolved_run_id, "audit_count": len(audit_rows), "rows": audit_rows})
        status_doc = {
            "run_id": resolved_run_id,
            "success": False,
            "flow_success": False,
            "acceptance_class": "rejected",
            "acceptance_reason": exc.reason,
            "mainnodeid": normalize_id(mainnodeid),
            "status": exc.reason,
            "detail": exc.detail,
            "counts": counts,
            "output_files": {
                "stage4_virtual_polygon": str(virtual_polygon_path),
                "stage4_node_link": str(node_link_json_path),
                "stage4_rcsdnode_link": str(rcsdnode_link_json_path),
                "stage4_audit": str(audit_json_path),
                "stage4_debug": str(debug_dir) if debug_dir is not None else None,
            },
        }
        perf_doc = {
            "run_id": resolved_run_id,
            "success": False,
            "flow_success": False,
            "acceptance_class": "rejected",
            "acceptance_reason": exc.reason,
            "counts": counts,
            "stage_timings": stage_timings,
            "total_wall_time_sec": round(time.perf_counter() - started_at, 6),
            **_tracemalloc_stats(),
        }
        write_json(status_path, status_doc)
        write_json(perf_json_path, perf_doc)
        announce(logger, f"[T02-Stage4] failed reason={exc.reason} detail={exc.detail}")
        return Stage4Artifacts(
            success=False,
            out_root=out_root_path,
            virtual_polygon_path=virtual_polygon_path,
            node_link_json_path=node_link_json_path,
            rcsdnode_link_json_path=rcsdnode_link_json_path,
            audit_json_path=audit_json_path,
            status_path=status_path,
            log_path=log_path,
            progress_path=progress_path,
            perf_json_path=perf_json_path,
            perf_markers_path=perf_markers_path,
            debug_dir=debug_dir,
            status_doc=status_doc,
            perf_doc=perf_doc,
        )
    finally:
        close_logger(logger)
        if trace_memory:
            tracemalloc.stop()


def run_t02_stage4_divmerge_virtual_polygon_cli(args: argparse.Namespace) -> int:
    artifacts = run_t02_stage4_divmerge_virtual_polygon(
        nodes_path=args.nodes_path,
        roads_path=args.roads_path,
        drivezone_path=args.drivezone_path,
        divstripzone_path=args.divstripzone_path,
        rcsdroad_path=args.rcsdroad_path,
        rcsdnode_path=args.rcsdnode_path,
        mainnodeid=args.mainnodeid,
        out_root=args.out_root,
        run_id=args.run_id,
        nodes_layer=args.nodes_layer,
        roads_layer=args.roads_layer,
        drivezone_layer=args.drivezone_layer,
        divstripzone_layer=args.divstripzone_layer,
        rcsdroad_layer=args.rcsdroad_layer,
        rcsdnode_layer=args.rcsdnode_layer,
        nodes_crs=args.nodes_crs,
        roads_crs=args.roads_crs,
        drivezone_crs=args.drivezone_crs,
        divstripzone_crs=args.divstripzone_crs,
        rcsdroad_crs=args.rcsdroad_crs,
        rcsdnode_crs=args.rcsdnode_crs,
        debug=args.debug,
    )
    return 0 if artifacts.success else 2
