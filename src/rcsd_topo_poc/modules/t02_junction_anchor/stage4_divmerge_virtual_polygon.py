from __future__ import annotations

import argparse
import json
import math
import shutil
import time
import tracemalloc
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
from pyproj import CRS
from shapely.geometry import GeometryCollection, LineString, Point
from shapely.ops import linemerge, nearest_points, substring, unary_union

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    TARGET_CRS,
    announce,
    build_logger,
    build_run_id,
    close_logger,
    write_json,
    write_vector,
)
from rcsd_topo_poc.modules.t02_junction_anchor.shared import (
    LoadedFeature,
    T02RunError,
    find_repo_root,
    normalize_id,
)
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
    _filter_loaded_features_to_patch,
    _filter_parsed_roads_to_patch,
    _load_layer_filtered,
    _mask_to_geometry,
    _parse_nodes,
    _parse_rc_nodes,
    _parse_roads,
    _rasterize_geometries,
    _regularize_virtual_polygon_geometry,
    _resolve_group,
    _resolve_current_patch_id_from_roads,
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
STATUS_COMPLEX_KIND_AMBIGUOUS = "complex_kind_ambiguous"
STAGE4_KIND_2_VALUES = {8, 16}
COMPLEX_JUNCTION_KIND = 128
DIVSTRIP_NEARBY_DISTANCE_M = 24.0
DIVSTRIP_BRANCH_BUFFER_M = 6.0
DIVSTRIP_EXCLUSION_BUFFER_M = 0.75
DIVSTRIP_CONTEXT_ROAD_DISTANCE_M = 12.0
DIVSTRIP_ROAD_NEARBY_DISTANCE_M = 2.5
DIVSTRIP_SEED_FALLBACK_DISTANCE_M = 48.0
DIVSTRIP_EVENT_BUFFER_M = 16.0
DIVSTRIP_EVENT_ROAD_LINK_DISTANCE_M = 14.0
DIVSTRIP_REFERENCE_ROAD_BUFFER_M = 28.0
DIVSTRIP_KIND_POSITION_MARGIN_M = 2.0
EVENT_ANCHOR_BUFFER_M = 4.0
EVENT_SPAN_DEFAULT_M = 10.0
EVENT_SPAN_MAX_M = 25.0
EVENT_SPAN_MARGIN_M = 1.5
EVENT_AXIS_TANGENT_SAMPLE_M = 3.0
EVENT_CROSSLINE_STEP_M = 1.0
EVENT_REFERENCE_SCAN_STEP_M = 1.0
EVENT_REFERENCE_SCAN_MAX_M = 140.0
EVENT_REFERENCE_DIVSTRIP_TOL_M = 2.5
EVENT_REFERENCE_MAX_OFFSET_M = 30.0
EVENT_REFERENCE_HARD_WINDOW_M = 1.0
EVENT_REFERENCE_PROBE_STEP_M = 0.25
EVENT_REFERENCE_BACKTRACK_PAST_NODE_M = 20.0
EVENT_REFERENCE_SEARCH_MARGIN_M = 20.0
EVENT_REFERENCE_SPLIT_EXTEND_M = 5.0
EVENT_REFERENCE_DIVSTRIP_TARGET_BY_SPLIT_MIN_S_M = 5.0
EVENT_RCSD_RECENTER_SHIFT_MAX_M = 20.0
PARALLEL_ROAD_ANGLE_TOLERANCE_DEG = 18.0
PARALLEL_ROAD_MIN_OFFSET_M = 4.0
PARALLEL_ROAD_MAX_OFFSET_M = 80.0
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
    rendered_map_path: Path | None = None
    status_doc: dict[str, Any] | None = None
    perf_doc: dict[str, Any] | None = None


def _cover_check(geometry, candidates: list[ParsedNode]) -> list[str]:
    cover = geometry.buffer(0)
    return [node.node_id for node in candidates if not cover.covers(node.geometry)]


def _selected_branch_score(branch) -> float:
    return float(branch.road_support_m + branch.drivezone_support_m + branch.rc_support_m)


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "nan"}:
        return None
    try:
        return int(text)
    except ValueError:
        try:
            parsed = float(text)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else None


def _node_source_kind(node: ParsedNode) -> int | None:
    return _coerce_optional_int(node.properties.get("kind"))


def _node_source_kind_2(node: ParsedNode) -> int | None:
    return node.kind_2 if node.kind_2 is not None else _coerce_optional_int(node.properties.get("kind_2"))


def _is_complex_stage4_node(node: ParsedNode) -> bool:
    source_kind = _node_source_kind(node)
    source_kind_2 = _node_source_kind_2(node)
    return source_kind == COMPLEX_JUNCTION_KIND or source_kind_2 == COMPLEX_JUNCTION_KIND


def _is_stage4_supported_node_kind(node: ParsedNode) -> bool:
    source_kind = _node_source_kind(node)
    source_kind_2 = _node_source_kind_2(node)
    return (
        source_kind_2 in STAGE4_KIND_2_VALUES
        or source_kind == COMPLEX_JUNCTION_KIND
        or source_kind_2 == COMPLEX_JUNCTION_KIND
    )


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
    coords = list(centerline.coords)
    oriented_by_branch = False
    if len(coords) >= 2:
        start_x, start_y = _coord_xy(coords[0])
        end_x, end_y = _coord_xy(coords[-1])
        line_vector = _normalize_axis_vector((end_x - start_x, end_y - start_y))
        branch_angle_deg = getattr(branch, "angle_deg", None)
        if line_vector is not None and branch_angle_deg is not None:
            angle_rad = math.radians(float(branch_angle_deg))
            branch_vector = (math.cos(angle_rad), math.sin(angle_rad))
            if float(line_vector[0]) * float(branch_vector[0]) + float(line_vector[1]) * float(branch_vector[1]) < 0.0:
                centerline = type(centerline)(coords[::-1])
                coords = list(centerline.coords)
            oriented_by_branch = True
    start_point = Point(centerline.coords[0])
    end_point = Point(centerline.coords[-1])
    if (not oriented_by_branch) and end_point.distance(reference_point) < start_point.distance(reference_point):
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
    covered = True
    return {
        "trunk_branch_id": trunk_branch.branch_id,
        "rcsdnode_tolerance_rule": tolerance_rule,
        "rcsdnode_tolerance_applied": True,
        "rcsdnode_coverage_mode": "trunk_window_tolerated",
        "rcsdnode_offset_m": offset_m,
        "rcsdnode_lateral_dist_m": lateral_dist_m,
        "reason": None,
        "extended_polygon_geometry": polygon_geometry,
        "covered": covered,
    }


def _resolve_effective_target_rc_nodes(
    *,
    direct_target_rc_nodes: list[ParsedNode],
    primary_main_rc_node: ParsedNode | None,
    primary_rcsdnode_tolerance: dict[str, Any] | None,
) -> list[ParsedNode]:
    if direct_target_rc_nodes:
        return list(direct_target_rc_nodes)
    if primary_main_rc_node is None or primary_rcsdnode_tolerance is None:
        return []
    coverage_mode = str(primary_rcsdnode_tolerance.get("rcsdnode_coverage_mode") or "")
    if coverage_mode in {"exact_cover", "trunk_window_tolerated"}:
        return [primary_main_rc_node]
    return []


def _infer_primary_main_rc_node_from_local_context(
    *,
    local_rcsd_nodes: list[ParsedNode],
    selected_rcsd_roads: list[ParsedRoad],
    representative_node: ParsedNode,
    road_branches,
    main_branch_ids: set[str],
    local_roads: list[ParsedRoad],
    kind_2: int,
) -> dict[str, Any]:
    tolerance_rule = (
        "diverge_main_seed_on_pre_trunk_le_20m"
        if kind_2 == 16
        else "merge_main_seed_on_post_trunk_le_20m"
    )
    if not local_rcsd_nodes:
        return {
            "primary_main_rc_node": None,
            "seed_mode": "no_local_rcsdnode",
            "seed_candidate_count": 0,
            "seed_endpoint_hit_count": 0,
            "seed_rule": tolerance_rule,
        }

    trunk_branch, tolerance_rule = _resolve_trunk_branch(
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        kind_2=kind_2,
    )
    if trunk_branch is None:
        return {
            "primary_main_rc_node": None,
            "seed_mode": "trunk_unstable",
            "seed_candidate_count": 0,
            "seed_endpoint_hit_count": 0,
            "seed_rule": tolerance_rule,
        }

    trunk_centerline = _resolve_branch_centerline(
        branch=trunk_branch,
        road_lookup={road.road_id: road for road in local_roads},
        reference_point=representative_node.geometry,
    )
    if trunk_centerline is None or trunk_centerline.is_empty:
        return {
            "primary_main_rc_node": None,
            "seed_mode": "trunk_unstable",
            "seed_candidate_count": 0,
            "seed_endpoint_hit_count": 0,
            "seed_rule": tolerance_rule,
        }

    selected_endpoint_ids = {
        normalize_id(node_id)
        for road in selected_rcsd_roads
        for node_id in (road.snodeid, road.enodeid)
        if normalize_id(node_id) is not None
    }
    event_ref_dist = float(trunk_centerline.project(representative_node.geometry))
    candidates: list[tuple[tuple[Any, ...], ParsedNode]] = []
    endpoint_hit_count = 0
    for node in local_rcsd_nodes:
        lateral_dist_m = float(node.geometry.distance(trunk_centerline))
        offset_m = float(trunk_centerline.project(node.geometry) - event_ref_dist)
        node_id = normalize_id(node.node_id)
        endpoint_hit = node_id in selected_endpoint_ids
        if endpoint_hit:
            endpoint_hit_count += 1
        within_window = 0.0 <= offset_m <= RCSDNODE_TRUNK_WINDOW_M
        on_trunk = lateral_dist_m <= RCSDNODE_TRUNK_LATERAL_TOLERANCE_M
        distance_to_seed = float(node.geometry.distance(representative_node.geometry))
        candidates.append(
            (
                (
                    1 if within_window and on_trunk else 0,
                    1 if endpoint_hit else 0,
                    1 if on_trunk else 0,
                    -abs(min(max(offset_m, 0.0), RCSDNODE_TRUNK_WINDOW_M) - offset_m),
                    -lateral_dist_m,
                    -distance_to_seed,
                ),
                node,
            )
        )

    if not candidates:
        return {
            "primary_main_rc_node": None,
            "seed_mode": "no_local_rcsdnode",
            "seed_candidate_count": 0,
            "seed_endpoint_hit_count": endpoint_hit_count,
            "seed_rule": tolerance_rule,
        }

    candidates.sort(key=lambda item: item[0], reverse=True)
    primary_main_rc_node = candidates[0][1]
    return {
        "primary_main_rc_node": primary_main_rc_node,
        "seed_mode": "inferred_local_trunk_window",
        "seed_candidate_count": len(candidates),
        "seed_endpoint_hit_count": endpoint_hit_count,
        "seed_rule": tolerance_rule,
    }


def _build_branch_union_geometry(
    *,
    local_roads: list[ParsedRoad],
    branch_ids: set[str],
    road_branches,
):
    road_ids = {
        road_id
        for branch in road_branches
        if branch.branch_id in branch_ids
        for road_id in branch.road_ids
    }
    geometries = [
        road.geometry
        for road in local_roads
        if road.road_id in road_ids and road.geometry is not None and not road.geometry.is_empty
    ]
    if not geometries:
        return GeometryCollection()
    return unary_union(geometries)


def _build_branch_pair_anchor_geometry(
    *,
    lhs_geometry,
    rhs_geometry,
    drivezone_union,
):
    if lhs_geometry is None or lhs_geometry.is_empty or rhs_geometry is None or rhs_geometry.is_empty:
        return GeometryCollection()
    intersection_geometry = lhs_geometry.intersection(rhs_geometry).buffer(0)
    if drivezone_union is not None and not drivezone_union.is_empty:
        intersection_geometry = intersection_geometry.intersection(drivezone_union).buffer(0)
    if not intersection_geometry.is_empty:
        return intersection_geometry

    try:
        lhs_point, rhs_point = nearest_points(lhs_geometry, rhs_geometry)
    except Exception:
        return GeometryCollection()
    midpoint = Point((lhs_point.x + rhs_point.x) / 2.0, (lhs_point.y + rhs_point.y) / 2.0)
    midpoint_geometry = midpoint.buffer(EVENT_ANCHOR_BUFFER_M)
    if drivezone_union is not None and not drivezone_union.is_empty:
        midpoint_geometry = midpoint_geometry.intersection(drivezone_union).buffer(0)
    return midpoint_geometry if not midpoint_geometry.is_empty else midpoint


def _estimate_event_anchor_geometry(
    *,
    local_roads: list[ParsedRoad],
    road_branches,
    main_branch_ids: set[str],
    drivezone_union,
    event_branch_ids: set[str] | None = None,
):
    candidate_branch_ids = {
        branch.branch_id
        for branch in road_branches
        if branch.branch_id not in main_branch_ids
    }
    if event_branch_ids:
        candidate_branch_ids &= set(event_branch_ids)
    if not candidate_branch_ids:
        candidate_branch_ids = {
            branch.branch_id
            for branch in road_branches
            if branch.branch_id not in main_branch_ids
        }
    if not candidate_branch_ids:
        main_pair_branches = [
            branch
            for branch in road_branches
            if branch.branch_id in main_branch_ids
        ]
        if len(main_pair_branches) < 2:
            return GeometryCollection()
        best_anchor = GeometryCollection()
        best_score: tuple[int, float] | None = None
        for lhs_branch, rhs_branch in combinations(main_pair_branches, 2):
            lhs_geometry = _build_branch_union_geometry(
                local_roads=local_roads,
                branch_ids={lhs_branch.branch_id},
                road_branches=road_branches,
            )
            rhs_geometry = _build_branch_union_geometry(
                local_roads=local_roads,
                branch_ids={rhs_branch.branch_id},
                road_branches=road_branches,
            )
            pair_anchor = _build_branch_pair_anchor_geometry(
                lhs_geometry=lhs_geometry,
                rhs_geometry=rhs_geometry,
                drivezone_union=drivezone_union,
            )
            if pair_anchor.is_empty:
                continue
            score = (
                1 if not lhs_geometry.intersection(rhs_geometry).is_empty else 0,
                -float(getattr(pair_anchor, "area", 0.0)),
            )
            if best_score is None or score > best_score:
                best_score = score
                best_anchor = pair_anchor
        return best_anchor

    main_union = _build_branch_union_geometry(
        local_roads=local_roads,
        branch_ids=main_branch_ids,
        road_branches=road_branches,
    )
    side_union = _build_branch_union_geometry(
        local_roads=local_roads,
        branch_ids=candidate_branch_ids,
        road_branches=road_branches,
    )
    if main_union.is_empty or side_union.is_empty:
        return GeometryCollection()

    return _build_branch_pair_anchor_geometry(
        lhs_geometry=main_union,
        rhs_geometry=side_union,
        drivezone_union=drivezone_union,
    )


def _analyze_divstrip_context(
    *,
    local_divstrip_features: list[Any],
    seed_union,
    road_branches,
    local_roads: list[ParsedRoad],
    main_branch_ids: set[str],
    drivezone_union,
    event_branch_ids: set[str] | None = None,
) -> dict[str, Any]:
    event_anchor_geometry = _estimate_event_anchor_geometry(
        local_roads=local_roads,
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        drivezone_union=drivezone_union,
        event_branch_ids=event_branch_ids,
    )
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
            "event_anchor_geometry": event_anchor_geometry,
        }

    union_geometry = unary_union(
        [feature.geometry for feature in local_divstrip_features if feature.geometry is not None and not feature.geometry.is_empty]
    )
    components = _explode_component_geometries(union_geometry)
    non_main_branches = [branch for branch in road_branches if branch.branch_id not in main_branch_ids]
    candidate_branch_ids = set(event_branch_ids or ())
    candidate_branches = [
        branch
        for branch in (non_main_branches or list(road_branches))
        if not candidate_branch_ids or branch.branch_id in candidate_branch_ids
    ] or (non_main_branches or list(road_branches))
    branch_geometry_lookup = {
        branch.branch_id: unary_union([road.geometry for road in local_roads if road.road_id in branch.road_ids])
        for branch in candidate_branches
    }
    all_branch_geometry_lookup = {
        branch.branch_id: unary_union([road.geometry for road in local_roads if road.road_id in branch.road_ids])
        for branch in road_branches
    }
    road_union = unary_union([road.geometry for road in local_roads if road.geometry is not None and not road.geometry.is_empty])

    nearby_components: list[dict[str, Any]] = []
    for component_index, component_geometry in enumerate(components):
        matched_branch_ids = sorted(
            branch_id
            for branch_id, branch_geometry in branch_geometry_lookup.items()
            if branch_geometry is not None
            and not branch_geometry.is_empty
            and branch_geometry.buffer(DIVSTRIP_BRANCH_BUFFER_M, cap_style=2, join_style=2).intersects(component_geometry)
        )
        matched_all_branch_ids = sorted(
            branch_id
            for branch_id, branch_geometry in all_branch_geometry_lookup.items()
            if branch_geometry is not None
            and not branch_geometry.is_empty
            and branch_geometry.buffer(DIVSTRIP_BRANCH_BUFFER_M, cap_style=2, join_style=2).intersects(component_geometry)
        )
        distance_to_seed = float(component_geometry.distance(seed_union))
        distance_to_roads = (
            math.inf
            if road_union is None or road_union.is_empty
            else float(component_geometry.distance(road_union))
        )
        distance_to_event_anchor = (
            math.inf
            if event_anchor_geometry is None or event_anchor_geometry.is_empty
            else float(component_geometry.distance(event_anchor_geometry))
        )
        if (
            matched_branch_ids
            or matched_all_branch_ids
            or distance_to_seed <= DIVSTRIP_NEARBY_DISTANCE_M
            or distance_to_event_anchor <= DIVSTRIP_NEARBY_DISTANCE_M
            or distance_to_roads <= DIVSTRIP_CONTEXT_ROAD_DISTANCE_M
            or (
                distance_to_roads <= DIVSTRIP_ROAD_NEARBY_DISTANCE_M
                and distance_to_seed <= DIVSTRIP_SEED_FALLBACK_DISTANCE_M
            )
        ):
            nearby_components.append(
                {
                    "component_id": f"divstrip_component_{component_index}",
                    "geometry": component_geometry,
                    "matched_branch_ids": matched_branch_ids,
                    "matched_all_branch_ids": matched_all_branch_ids,
                    "distance_to_seed": distance_to_seed,
                    "distance_to_roads": distance_to_roads,
                    "distance_to_event_anchor": distance_to_event_anchor,
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
            "event_anchor_geometry": event_anchor_geometry,
        }

    matched_components = [
        component
        for component in nearby_components
        if component["matched_branch_ids"] or component["matched_all_branch_ids"]
    ]
    anchor_preferred_components = [
        component
        for component in nearby_components
        if float(component["distance_to_event_anchor"])
        <= max(DIVSTRIP_REFERENCE_ROAD_BUFFER_M * 0.65, EVENT_ANCHOR_BUFFER_M * 3.0)
    ]
    road_nearby_components = [
        component
        for component in nearby_components
        if component["distance_to_roads"] <= DIVSTRIP_ROAD_NEARBY_DISTANCE_M
    ]
    candidate_components = anchor_preferred_components or matched_components or road_nearby_components or nearby_components
    candidate_components.sort(
        key=lambda component: (
            float(component["distance_to_event_anchor"]),
            -len(component["matched_branch_ids"]),
            -len(component["matched_all_branch_ids"]),
            float(component["distance_to_roads"]),
            float(component["distance_to_seed"]),
        ),
    )
    selected_components = [candidate_components[0]]
    ambiguous = False
    if len(candidate_components) > 1:
        first_component = candidate_components[0]
        second_component = candidate_components[1]
        first_branch_ids = set(first_component["matched_branch_ids"] or first_component["matched_all_branch_ids"])
        second_branch_ids = set(second_component["matched_branch_ids"] or second_component["matched_all_branch_ids"])
        first_corridor_geometry = unary_union(
            [
                geometry
                for branch_id, geometry in all_branch_geometry_lookup.items()
                if branch_id in first_branch_ids and geometry is not None and not geometry.is_empty
            ]
        )
        same_branch_corridor = bool(
            first_branch_ids
            and not first_corridor_geometry.is_empty
            and first_corridor_geometry.buffer(
                max(DIVSTRIP_REFERENCE_ROAD_BUFFER_M * 0.6, DIVSTRIP_BRANCH_BUFFER_M * 2.5),
                cap_style=2,
                join_style=2,
            ).intersects(second_component["geometry"])
            and float(second_component["distance_to_seed"]) <= float(DIVSTRIP_SEED_FALLBACK_DISTANCE_M)
        )
        same_corridor_pair = (
            (
                first_branch_ids
                and second_branch_ids
                and bool(first_branch_ids & second_branch_ids)
            )
            or same_branch_corridor
            or (
                not first_branch_ids
                and float(second_component["distance_to_roads"]) <= DIVSTRIP_CONTEXT_ROAD_DISTANCE_M
            )
        ) and float(second_component["geometry"].distance(first_component["geometry"])) <= float(
            DIVSTRIP_REFERENCE_ROAD_BUFFER_M + 6.0
        )
        if same_corridor_pair:
            selected_components = [first_component, second_component]
            ambiguous = False
        else:
            ambiguous = (
                len(first_component["matched_branch_ids"]) == len(second_component["matched_branch_ids"])
                and len(first_component["matched_all_branch_ids"]) == len(second_component["matched_all_branch_ids"])
                and abs(float(first_component["distance_to_event_anchor"]) - float(second_component["distance_to_event_anchor"])) <= 3.0
                and abs(float(first_component["distance_to_roads"]) - float(second_component["distance_to_roads"])) <= 1.0
                and abs(float(first_component["distance_to_seed"]) - float(second_component["distance_to_seed"])) <= 6.0
                and first_component["component_id"] != second_component["component_id"]
            )
            if (
                not ambiguous
                and len(matched_components) > 1
                and abs(float(first_component["distance_to_event_anchor"]) - float(second_component["distance_to_event_anchor"])) <= 8.0
                and abs(float(first_component["distance_to_roads"]) - float(second_component["distance_to_roads"])) <= 3.0
                and abs(float(first_component["distance_to_seed"]) - float(second_component["distance_to_seed"])) <= 12.0
            ):
                ambiguous = True
            if ambiguous:
                selected_components = [first_component, second_component]
    if not ambiguous and selected_components:
        primary_component = selected_components[0]
        primary_branch_ids = set(primary_component["matched_branch_ids"] or primary_component["matched_all_branch_ids"])
        primary_corridor_geometry = unary_union(
            [
                geometry
                for branch_id, geometry in all_branch_geometry_lookup.items()
                if branch_id in primary_branch_ids and geometry is not None and not geometry.is_empty
            ]
        )
        merged_components = [primary_component]
        for component in candidate_components[1:]:
            component_branch_ids = set(component["matched_branch_ids"] or component["matched_all_branch_ids"])
            same_branch_corridor = bool(
                primary_branch_ids
                and not primary_corridor_geometry.is_empty
                and primary_corridor_geometry.buffer(
                    max(DIVSTRIP_REFERENCE_ROAD_BUFFER_M * 0.6, DIVSTRIP_BRANCH_BUFFER_M * 2.5),
                    cap_style=2,
                    join_style=2,
                ).intersects(component["geometry"])
                and float(component["distance_to_seed"]) <= float(DIVSTRIP_SEED_FALLBACK_DISTANCE_M)
            )
            same_corridor = (
                (
                    primary_branch_ids
                    and component_branch_ids
                    and bool(primary_branch_ids & component_branch_ids)
                )
                or same_branch_corridor
                or (
                    not primary_branch_ids
                    and float(component["distance_to_roads"]) <= DIVSTRIP_CONTEXT_ROAD_DISTANCE_M
                )
            )
            if not same_corridor:
                continue
            if (
                float(component["geometry"].distance(primary_component["geometry"]))
                > float(DIVSTRIP_REFERENCE_ROAD_BUFFER_M + 6.0)
            ):
                continue
            merged_components.append(component)
        selected_components = merged_components
    selected_geometry = unary_union([component["geometry"] for component in selected_components])
    preferred_branch_ids = sorted(
        {
            branch_id
            for component in selected_components
            for branch_id in (component["matched_branch_ids"] or component["matched_all_branch_ids"])
        }
    )
    return {
        "present": True,
        "nearby": True,
        "component_count": len(components),
        "selected_component_ids": [component["component_id"] for component in selected_components],
        "constraint_geometry": GeometryCollection() if ambiguous else selected_geometry,
        "preferred_branch_ids": preferred_branch_ids,
        "ambiguous": ambiguous,
        "selection_mode": "divstrip_primary" if not ambiguous and not selected_geometry.is_empty else "roads_fallback",
        "evidence_source": "drivezone+divstrip+roads+rcsd+seed" if not ambiguous and not selected_geometry.is_empty else "drivezone+roads+rcsd+seed",
        "event_anchor_geometry": event_anchor_geometry,
    }


def _build_divstrip_event_window(
    *,
    divstrip_constraint_geometry,
    selected_roads: list[ParsedRoad],
    selected_rcsd_roads: list[ParsedRoad],
    seed_union,
    event_anchor_geometry,
    drivezone_union,
):
    if divstrip_constraint_geometry is None or divstrip_constraint_geometry.is_empty:
        return GeometryCollection()

    event_parts = [divstrip_constraint_geometry.buffer(DIVSTRIP_EVENT_BUFFER_M, join_style=2)]
    if event_anchor_geometry is not None and not event_anchor_geometry.is_empty:
        event_parts.append(event_anchor_geometry.buffer(EVENT_ANCHOR_BUFFER_M, join_style=2))
    linked_road_geometries = [
        road.geometry.buffer(max(ROAD_BUFFER_M, 1.75), cap_style=2, join_style=2)
        for road in [*selected_roads, *selected_rcsd_roads]
        if road.geometry is not None
        and not road.geometry.is_empty
        and road.geometry.distance(divstrip_constraint_geometry) <= DIVSTRIP_EVENT_ROAD_LINK_DISTANCE_M
    ]
    event_parts.extend(linked_road_geometries)
    if seed_union is not None and not seed_union.is_empty and seed_union.distance(divstrip_constraint_geometry) <= DIVSTRIP_SEED_FALLBACK_DISTANCE_M:
        event_parts.append(seed_union.buffer(max(NODE_SEED_RADIUS_M * 1.5, RC_NODE_SEED_RADIUS_M * 1.2, 3.0)))
    event_window = unary_union(event_parts).intersection(drivezone_union).buffer(0)
    return event_window if not event_window.is_empty else GeometryCollection()


def _localize_divstrip_reference_geometry(
    *,
    divstrip_constraint_geometry,
    selected_roads: list[ParsedRoad],
    event_anchor_geometry,
    representative_node: ParsedNode,
    drivezone_union,
):
    if divstrip_constraint_geometry is None or divstrip_constraint_geometry.is_empty:
        return GeometryCollection()

    focus_geometries = [
        road.geometry.buffer(DIVSTRIP_REFERENCE_ROAD_BUFFER_M, cap_style=2, join_style=2)
        for road in selected_roads
        if road.geometry is not None and not road.geometry.is_empty
    ]
    if event_anchor_geometry is not None and not event_anchor_geometry.is_empty:
        focus_geometries.append(
            event_anchor_geometry.buffer(max(EVENT_ANCHOR_BUFFER_M * 2.0, DIVSTRIP_REFERENCE_ROAD_BUFFER_M * 0.6), join_style=2)
        )
    focus_geometries.append(
        representative_node.geometry.buffer(max(EVENT_ANCHOR_BUFFER_M * 2.0, DIVSTRIP_REFERENCE_ROAD_BUFFER_M * 0.5))
    )
    focus_geometry = unary_union(focus_geometries).buffer(0)
    if drivezone_union is not None and not drivezone_union.is_empty:
        focus_geometry = focus_geometry.intersection(
            drivezone_union.buffer(max(EVENT_ANCHOR_BUFFER_M, ROAD_BUFFER_M), join_style=2)
        ).buffer(0)
    if focus_geometry.is_empty:
        return divstrip_constraint_geometry
    localized_geometry = divstrip_constraint_geometry.intersection(focus_geometry).buffer(0)
    if localized_geometry.is_empty:
        return divstrip_constraint_geometry
    return localized_geometry


def _clip_loaded_features_to_geometry(
    *,
    features: list[LoadedFeature],
    clip_geometry,
) -> list[LoadedFeature]:
    if clip_geometry is None or clip_geometry.is_empty:
        return []
    clipped_features: list[LoadedFeature] = []
    for feature in features:
        geometry = feature.geometry
        if geometry is None or geometry.is_empty:
            continue
        clipped_geometry = geometry.intersection(clip_geometry)
        if clipped_geometry.is_empty:
            continue
        clipped_features.append(
            LoadedFeature(
                feature_index=feature.feature_index,
                properties=dict(feature.properties),
                geometry=clipped_geometry,
            )
        )
    return clipped_features


def _normalize_axis_vector(vector: tuple[float, float]) -> tuple[float, float] | None:
    length = math.hypot(float(vector[0]), float(vector[1]))
    if length <= 1e-9:
        return None
    return (float(vector[0]) / length, float(vector[1]) / length)


def _project_xy_to_axis(
    x: float,
    y: float,
    *,
    origin_xy: tuple[float, float],
    axis_unit_vector: tuple[float, float],
) -> float:
    dx = float(x) - float(origin_xy[0])
    dy = float(y) - float(origin_xy[1])
    return dx * axis_unit_vector[0] + dy * axis_unit_vector[1]


def _coord_xy(coord: Any) -> tuple[float, float]:
    return (float(coord[0]), float(coord[1]))


def _project_point_to_axis(
    point: Point,
    *,
    origin_xy: tuple[float, float],
    axis_unit_vector: tuple[float, float],
) -> float:
    return _project_xy_to_axis(
        float(point.x),
        float(point.y),
        origin_xy=origin_xy,
        axis_unit_vector=axis_unit_vector,
    )


def _point_from_axis_offset(
    *,
    origin_point: Point,
    axis_unit_vector: tuple[float, float],
    offset_m: float,
) -> Point:
    return Point(
        float(origin_point.x) + float(axis_unit_vector[0]) * float(offset_m),
        float(origin_point.y) + float(axis_unit_vector[1]) * float(offset_m),
    )


def _resolve_event_axis_branch(
    *,
    road_branches,
    main_branch_ids: set[str],
    kind_2: int,
):
    trunk_branch, _ = _resolve_trunk_branch(
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        kind_2=kind_2,
    )
    if trunk_branch is not None:
        return trunk_branch
    for branch in road_branches:
        if branch.branch_id in main_branch_ids:
            return branch
    return road_branches[0] if road_branches else None


def _resolve_scan_axis_unit_vector(
    *,
    axis_unit_vector: tuple[float, float] | None,
    kind_2: int,
) -> tuple[float, float] | None:
    if axis_unit_vector is None:
        return None
    if kind_2 == 8:
        return (-float(axis_unit_vector[0]), -float(axis_unit_vector[1]))
    return axis_unit_vector


def _resolve_event_origin_point(
    *,
    representative_node: ParsedNode,
    event_anchor_geometry,
    divstrip_constraint_geometry,
    axis_centerline,
):
    source = "representative_node"
    reference_point = representative_node.geometry
    if event_anchor_geometry is not None and not event_anchor_geometry.is_empty:
        source = "event_anchor"
        reference_point = event_anchor_geometry.representative_point()
    elif divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty:
        source = "divstrip"
        reference_point = divstrip_constraint_geometry.representative_point()
    if axis_centerline is None or axis_centerline.is_empty:
        return reference_point, source
    axis_point, _ = nearest_points(axis_centerline, reference_point)
    return axis_point, f"{source}_snapped_to_axis"


def _collect_polygon_components(geometry) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    geometry_type = getattr(geometry, "geom_type", None)
    if geometry_type == "Polygon":
        return [geometry]
    if geometry_type in {"MultiPolygon", "GeometryCollection"}:
        parts: list[Any] = []
        for item in getattr(geometry, "geoms", []):
            parts.extend(_collect_polygon_components(item))
        return parts
    return [geometry]


def _collect_divstrip_vertices(geometry) -> list[tuple[float, float]]:
    if geometry is None or geometry.is_empty:
        return []
    geometry_type = getattr(geometry, "geom_type", None)
    if geometry_type == "Point":
        return [(float(geometry.x), float(geometry.y))]
    if geometry_type == "LineString":
        return [_coord_xy(coord) for coord in geometry.coords]
    if geometry_type == "Polygon":
        points = [_coord_xy(coord) for coord in geometry.exterior.coords]
        for ring in geometry.interiors:
            points.extend(_coord_xy(coord) for coord in ring.coords)
        return points
    if geometry_type in {"MultiLineString", "MultiPolygon", "GeometryCollection"}:
        points: list[tuple[float, float]] = []
        for item in getattr(geometry, "geoms", []):
            points.extend(_collect_divstrip_vertices(item))
        return points
    return []


def _tip_point_from_divstrip(
    *,
    divstrip_geometry,
    scan_axis_unit_vector: tuple[float, float],
    origin_point: Point,
) -> Point | None:
    if divstrip_geometry is None or divstrip_geometry.is_empty:
        return None
    ux, uy = _normalize_axis_vector(scan_axis_unit_vector) or scan_axis_unit_vector

    def _project_xy(x: float, y: float) -> float:
        return (float(x) - float(origin_point.x)) * float(ux) + (float(y) - float(origin_point.y)) * float(uy)

    target_geometry = divstrip_geometry
    components = _collect_polygon_components(divstrip_geometry)
    if components:
        ahead_components = []
        for component in components:
            representative_point = component.representative_point()
            projection = _project_xy(float(representative_point.x), float(representative_point.y))
            if projection >= -1e-6:
                ahead_components.append((projection, component))
        if ahead_components:
            target_geometry = min(ahead_components, key=lambda item: item[0])[1]
        else:
            target_geometry = max(
                (
                    (_project_xy(float(component.representative_point().x), float(component.representative_point().y)), component)
                    for component in components
                ),
                key=lambda item: item[0],
            )[1]

    vertices = _collect_divstrip_vertices(target_geometry)
    if not vertices:
        representative_point = target_geometry.representative_point()
        if representative_point is None or representative_point.is_empty:
            return None
        return Point(float(representative_point.x), float(representative_point.y))

    scores = [_project_xy(x, y) for x, y in vertices]
    non_negative = [score for score in scores if score >= -1e-6]
    if non_negative:
        target_score = min(non_negative)
        tip_points = [vertices[index] for index, score in enumerate(scores) if abs(score - target_score) <= 1e-6]
    else:
        target_score = max(scores)
        tip_points = [vertices[index] for index, score in enumerate(scores) if abs(score - target_score) <= 1e-6]
    if not tip_points:
        best_x, best_y = vertices[max(range(len(scores)), key=lambda index: scores[index])]
        return Point(float(best_x), float(best_y))
    unique_points = list(dict.fromkeys((float(x), float(y)) for x, y in tip_points))
    return Point(
        float(sum(x for x, _ in unique_points) / len(unique_points)),
        float(sum(y for _, y in unique_points) / len(unique_points)),
    )


def _pick_reference_s(
    *,
    divstrip_ref_s: float | None,
    divstrip_ref_source: str,
    drivezone_split_s: float | None,
    max_offset_m: float,
) -> tuple[float | None, str, str]:
    if divstrip_ref_s is not None:
        reference_s = float(divstrip_ref_s)
        if drivezone_split_s is not None and str(divstrip_ref_source) == "tip_projection":
            return float(drivezone_split_s), "drivezone_split", "drivezone_split_window_tip_projection_ignored"
        if (
            drivezone_split_s is not None
            and (abs(float(reference_s)) - abs(float(drivezone_split_s))) > float(max_offset_m)
        ):
            return float(drivezone_split_s), "drivezone_split", "drivezone_split_window_divstrip_far_ignored"
        return float(reference_s), "divstrip_ref", f"divstrip_{str(divstrip_ref_source)}_window"
    if drivezone_split_s is not None:
        return float(drivezone_split_s), "drivezone_split", "drivezone_split_window"
    return None, "none", "none"


def _is_drivezone_position_source(source: str | None) -> bool:
    return str(source or "").startswith("drivezone_split")


def _build_ref_window_away_from_node(*, ref_s: float, window_m: float) -> tuple[float, float, float]:
    window = max(0.0, float(window_m))
    reference_s = float(ref_s)
    sign = -1.0 if reference_s < 0.0 else 1.0
    far_s = reference_s + sign * window
    return float(min(reference_s, far_s)), float(max(reference_s, far_s)), float(far_s)


def _build_ref_window_toward_node(*, ref_s: float, window_m: float) -> tuple[float, float, float]:
    window = max(0.0, float(window_m))
    reference_s = float(ref_s)
    sign = -1.0 if reference_s < 0.0 else 1.0
    near_s = reference_s - sign * window
    return float(min(reference_s, near_s)), float(max(reference_s, near_s)), float(near_s)


def _build_drivezone_backtrack_candidates(
    *,
    ref_s: float,
    start_s: float,
    probe_step: float,
    past_node_m: float,
) -> list[float]:
    step = max(0.05, abs(float(probe_step)))
    past = max(0.0, float(past_node_m))
    sign = -1.0 if float(ref_s) < 0.0 else 1.0
    candidates: list[float] = []
    current_s = float(start_s) - sign * step
    while (current_s >= -1e-9) if sign > 0.0 else (current_s <= 1e-9):
        value = 0.0 if abs(float(current_s)) <= 1e-9 else float(current_s)
        candidates.append(float(value))
        if abs(float(value)) <= 1e-9:
            break
        current_s -= sign * step
    if past > 1e-9:
        current_s = -sign * step
        while abs(float(current_s)) <= past + 1e-9:
            candidates.append(float(current_s))
            current_s -= sign * step
        if not candidates or abs(float(candidates[-1])) < past - 1e-9:
            candidates.append(float(-sign * past))
    deduped: list[float] = []
    seen: set[float] = set()
    for value in candidates:
        rounded = round(float(value), 6)
        if rounded in seen:
            continue
        seen.add(rounded)
        deduped.append(float(value))
    return deduped


def _pick_divstrip_component_near_split(
    *,
    scan_origin_point: Point,
    scan_axis_unit_vector: tuple[float, float],
    split_s: float,
    cross_half_len_m: float,
    branch_a_centerline,
    branch_b_centerline,
    divstrip_components: list[Any],
) -> tuple[Any | None, float | None]:
    if not divstrip_components:
        return None, None
    split_crossline = _build_event_crossline(
        origin_point=scan_origin_point,
        axis_unit_vector=scan_axis_unit_vector,
        scan_dist_m=float(split_s),
        cross_half_len_m=float(cross_half_len_m),
    )
    split_center = split_crossline.interpolate(0.5, normalized=True)
    split_segment, split_diag = _build_between_branches_segment(
        crossline=split_crossline,
        center_point=split_center,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
    )
    reference_geometry = (
        split_segment
        if split_segment is not None and split_diag["ok"]
        else split_crossline
    )
    best_geometry = None
    best_key = None
    best_distance = None
    for component in divstrip_components:
        if component is None or component.is_empty:
            continue
        distance = float(reference_geometry.distance(component))
        tip_s = None
        tip_point = _tip_point_from_divstrip(
            divstrip_geometry=component,
            scan_axis_unit_vector=scan_axis_unit_vector,
            origin_point=scan_origin_point,
        )
        if tip_point is not None and not tip_point.is_empty:
            candidate_tip_s = _project_point_to_axis(
                tip_point,
                origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
                axis_unit_vector=scan_axis_unit_vector,
            )
            if math.isfinite(float(candidate_tip_s)):
                tip_s = float(candidate_tip_s)
        tip_delta = None if tip_s is None else float(tip_s) - float(split_s)
        forward_tip = tip_delta is not None and float(tip_delta) >= -float(EVENT_REFERENCE_HARD_WINDOW_M)
        component_key = (
            0 if forward_tip else 1,
            math.inf if tip_delta is None or not forward_tip else max(0.0, float(tip_delta)),
            float(distance),
            math.inf if tip_delta is None else abs(float(tip_delta)),
        )
        if best_key is None or component_key < best_key:
            best_key = component_key
            best_distance = distance
            best_geometry = component
    return best_geometry, best_distance


def _scan_first_divstrip_hit(
    *,
    scan_samples: list[tuple[float, Any]],
    divstrip_geometry,
    div_tol_m: float,
) -> tuple[float | None, float | None]:
    if divstrip_geometry is None or divstrip_geometry.is_empty:
        return None, None
    first_hit_s = None
    best_distance_m = None
    for scan_s, probe_geometry in scan_samples:
        if probe_geometry is None or probe_geometry.is_empty:
            continue
        distance = float(probe_geometry.distance(divstrip_geometry))
        if best_distance_m is None or distance < best_distance_m:
            best_distance_m = distance
        if first_hit_s is None and distance <= float(div_tol_m):
            first_hit_s = float(scan_s)
    return first_hit_s, best_distance_m


def _resolve_event_reference_point(
    *,
    representative_node: ParsedNode,
    axis_centerline,
    scan_origin_point: Point,
    scan_axis_unit_vector: tuple[float, float] | None,
    branch_a_centerline,
    branch_b_centerline,
    drivezone_union,
    divstrip_constraint_geometry,
    fallback_point: Point,
    fallback_source: str,
) -> dict[str, Any]:
    if (
        axis_centerline is None
        or axis_centerline.is_empty
        or scan_axis_unit_vector is None
        or branch_a_centerline is None
        or branch_a_centerline.is_empty
        or branch_b_centerline is None
        or branch_b_centerline.is_empty
    ):
        return {
            "event_point": fallback_point,
            "event_origin_source": fallback_source,
            "position_source": "fallback",
            "split_pick_source": "fallback_no_axis_or_boundary_branch",
            "tip_s_m": None,
            "first_divstrip_hit_dist_m": None,
            "s_drivezone_split_m": None,
            "s_chosen_m": None,
            "divstrip_ref_source": "none",
        }

    tip_point = _tip_point_from_divstrip(
        divstrip_geometry=divstrip_constraint_geometry,
        scan_axis_unit_vector=scan_axis_unit_vector,
        origin_point=scan_origin_point,
    )
    tip_s_m = None
    if tip_point is not None and not tip_point.is_empty:
        tip_s_candidate = _project_point_to_axis(
            tip_point,
            origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
            axis_unit_vector=scan_axis_unit_vector,
        )
        if -1e-6 <= float(tip_s_candidate) <= float(EVENT_REFERENCE_SCAN_MAX_M) + 1e-6:
            tip_s_m = float(max(0.0, tip_s_candidate))

    first_divstrip_hit_s = None
    drivezone_split_s = None
    drivezone_split_source = "none"
    drivezone_split_source = "none"
    step_m = max(EVENT_REFERENCE_SCAN_STEP_M, EVENT_CROSSLINE_STEP_M)
    scan_values = np.arange(0.0, float(EVENT_REFERENCE_SCAN_MAX_M) + step_m, step_m)
    cross_half_len_m = max(120.0, float(axis_centerline.length) * 0.5)
    for scan_dist_m in scan_values:
        crossline = _build_event_crossline(
            origin_point=scan_origin_point,
            axis_unit_vector=scan_axis_unit_vector,
            scan_dist_m=float(scan_dist_m),
            cross_half_len_m=cross_half_len_m,
        )
        center_point = crossline.interpolate(0.5, normalized=True)
        found_segment, segment_diag = _build_between_branches_segment(
            crossline=crossline,
            center_point=center_point,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
        )
        if found_segment is None or not segment_diag["ok"]:
            continue
        if drivezone_split_s is None:
            drivezone_pieces = _collect_line_parts(crossline.intersection(drivezone_union))
            if len(drivezone_pieces) >= 2:
                drivezone_split_s = float(scan_dist_m)
        if (
            first_divstrip_hit_s is None
            and divstrip_constraint_geometry is not None
            and not divstrip_constraint_geometry.is_empty
            and float(found_segment.distance(divstrip_constraint_geometry)) <= float(EVENT_REFERENCE_DIVSTRIP_TOL_M)
        ):
            first_divstrip_hit_s = float(scan_dist_m)
        if drivezone_split_s is not None and first_divstrip_hit_s is not None:
            break

    divstrip_ref_s = None
    divstrip_ref_source = "none"
    if first_divstrip_hit_s is not None:
        divstrip_ref_s = float(first_divstrip_hit_s)
        divstrip_ref_source = "first_hit"
    elif tip_s_m is not None:
        divstrip_ref_s = float(tip_s_m)
        divstrip_ref_source = "tip_projection"

    chosen_s, position_source, split_pick_source = _pick_reference_s(
        divstrip_ref_s=divstrip_ref_s,
        divstrip_ref_source=divstrip_ref_source,
        drivezone_split_s=drivezone_split_s,
        max_offset_m=EVENT_REFERENCE_MAX_OFFSET_M,
    )
    if chosen_s is None:
        return {
            "event_point": fallback_point,
            "event_origin_source": fallback_source,
            "position_source": "fallback",
            "split_pick_source": "fallback_no_reference_s",
            "tip_s_m": None if tip_s_m is None else float(tip_s_m),
            "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
            "s_drivezone_split_m": None if drivezone_split_s is None else float(drivezone_split_s),
            "s_chosen_m": None,
            "divstrip_ref_source": divstrip_ref_source,
        }

    chosen_point = Point(
        float(scan_origin_point.x) + float(scan_axis_unit_vector[0]) * float(chosen_s),
        float(scan_origin_point.y) + float(scan_axis_unit_vector[1]) * float(chosen_s),
    )
    return {
        "event_point": chosen_point,
        "event_origin_source": f"{position_source}_chosen_s",
        "position_source": position_source,
        "split_pick_source": split_pick_source,
        "tip_s_m": None if tip_s_m is None else float(tip_s_m),
        "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
        "s_drivezone_split_m": None if drivezone_split_s is None else float(drivezone_split_s),
        "s_chosen_m": float(chosen_s),
        "divstrip_ref_source": divstrip_ref_source,
    }


def _resolve_event_axis_unit_vector(
    *,
    axis_centerline,
    origin_point: Point,
) -> tuple[float, float] | None:
    if axis_centerline is None or axis_centerline.is_empty:
        return None
    centerline_length = float(axis_centerline.length)
    if centerline_length <= 1e-6:
        return None
    origin_dist = float(axis_centerline.project(origin_point))
    sample_half_span = min(EVENT_AXIS_TANGENT_SAMPLE_M, max(centerline_length / 4.0, 1.0))
    start_dist = max(0.0, origin_dist - sample_half_span)
    end_dist = min(centerline_length, origin_dist + sample_half_span)
    if end_dist - start_dist <= 1e-6:
        coords = list(axis_centerline.coords)
        if len(coords) < 2:
            return None
        return _normalize_axis_vector(
            (
                float(coords[-1][0]) - float(coords[0][0]),
                float(coords[-1][1]) - float(coords[0][1]),
            )
        )
    segment = substring(axis_centerline, start_dist, end_dist)
    segment_coords = []
    for geometry in _explode_component_geometries(segment):
        if getattr(geometry, "geom_type", None) == "LineString" and not geometry.is_empty:
            segment_coords = list(geometry.coords)
            if segment_coords:
                break
    if len(segment_coords) < 2:
        coords = list(axis_centerline.coords)
        if len(coords) < 2:
            return None
        segment_coords = coords
    return _normalize_axis_vector(
        (
            float(segment_coords[-1][0]) - float(segment_coords[0][0]),
            float(segment_coords[-1][1]) - float(segment_coords[0][1]),
        )
    )


def _collect_axis_offsets_from_geometry(
    geometry,
    *,
    origin_xy: tuple[float, float],
    axis_unit_vector: tuple[float, float],
    clip_geometry=None,
) -> list[float]:
    if geometry is None or geometry.is_empty:
        return []
    target_geometry = geometry if clip_geometry is None else geometry.intersection(clip_geometry)
    if target_geometry.is_empty:
        return []
    offsets: list[float] = []
    for part in _explode_component_geometries(target_geometry):
        geom_type = getattr(part, "geom_type", None)
        if geom_type == "Point":
            offsets.append(
                _project_point_to_axis(
                    part,
                    origin_xy=origin_xy,
                    axis_unit_vector=axis_unit_vector,
                )
            )
            continue
        if geom_type == "LineString":
            offsets.extend(
                _project_xy_to_axis(x, y, origin_xy=origin_xy, axis_unit_vector=axis_unit_vector)
                for x, y in (_coord_xy(coord) for coord in part.coords)
            )
            continue
        if geom_type == "Polygon":
            offsets.extend(
                _project_xy_to_axis(x, y, origin_xy=origin_xy, axis_unit_vector=axis_unit_vector)
                for x, y in (_coord_xy(coord) for coord in part.exterior.coords)
            )
    return offsets


def _resolve_event_span_window(
    *,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    selected_rcsd_nodes: list[ParsedNode],
    event_anchor_geometry,
    selected_roads_geometry=None,
    selected_rcsd_roads_geometry=None,
) -> dict[str, Any]:
    start_offset_m = -EVENT_SPAN_DEFAULT_M
    end_offset_m = EVENT_SPAN_DEFAULT_M
    if axis_unit_vector is None:
        return {
            "start_offset_m": start_offset_m,
            "end_offset_m": end_offset_m,
            "candidate_offset_count": 0,
            "expansion_source": "default_no_axis",
        }

    origin_xy = (float(origin_point.x), float(origin_point.y))
    candidate_offsets: list[float] = []
    for node in selected_rcsd_nodes:
        projected_offset = _project_point_to_axis(
            node.geometry,
            origin_xy=origin_xy,
            axis_unit_vector=axis_unit_vector,
        )
        if -EVENT_SPAN_MAX_M - EVENT_SPAN_MARGIN_M <= float(projected_offset) <= EVENT_SPAN_MAX_M + EVENT_SPAN_MARGIN_M:
            candidate_offsets.append(float(projected_offset))
    candidate_offsets.extend(
        _collect_axis_offsets_from_geometry(
            event_anchor_geometry,
            origin_xy=origin_xy,
            axis_unit_vector=axis_unit_vector,
        )
    )
    road_context_clip_geometry = None
    if event_anchor_geometry is not None and not event_anchor_geometry.is_empty:
        road_context_clip_geometry = event_anchor_geometry.buffer(
            EVENT_SPAN_MAX_M + EVENT_SPAN_MARGIN_M,
            cap_style=2,
            join_style=2,
        )
    candidate_offsets.extend(
        _collect_axis_offsets_from_geometry(
            selected_roads_geometry,
            origin_xy=origin_xy,
            axis_unit_vector=axis_unit_vector,
            clip_geometry=road_context_clip_geometry,
        )
    )
    candidate_offsets.extend(
        _collect_axis_offsets_from_geometry(
            selected_rcsd_roads_geometry,
            origin_xy=origin_xy,
            axis_unit_vector=axis_unit_vector,
            clip_geometry=road_context_clip_geometry,
        )
    )
    if candidate_offsets:
        start_offset_m = min(start_offset_m, min(candidate_offsets) - EVENT_SPAN_MARGIN_M)
        end_offset_m = max(end_offset_m, max(candidate_offsets) + EVENT_SPAN_MARGIN_M)
        expansion_source = "rcsd_or_divstrip_context"
    else:
        expansion_source = "default_span"
    start_offset_m = max(-EVENT_SPAN_MAX_M, start_offset_m)
    end_offset_m = min(EVENT_SPAN_MAX_M, end_offset_m)
    return {
        "start_offset_m": float(start_offset_m),
        "end_offset_m": float(end_offset_m),
        "candidate_offset_count": len(candidate_offsets),
        "expansion_source": expansion_source,
    }


def _build_axis_window_mask(
    *,
    grid,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    start_offset_m: float,
    end_offset_m: float,
) -> np.ndarray:
    if axis_unit_vector is None:
        return np.ones_like(grid.xx, dtype=bool)
    u_coords = (
        (grid.xx - float(origin_point.x)) * float(axis_unit_vector[0])
        + (grid.yy - float(origin_point.y)) * float(axis_unit_vector[1])
    )
    return (u_coords >= float(start_offset_m)) & (u_coords <= float(end_offset_m))


def _build_axis_window_geometry(
    *,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    start_offset_m: float,
    end_offset_m: float,
    cross_half_len_m: float,
):
    if axis_unit_vector is None:
        return GeometryCollection()
    ux, uy = axis_unit_vector
    vx, vy = -uy, ux
    sx = float(origin_point.x) + ux * float(start_offset_m)
    sy = float(origin_point.y) + uy * float(start_offset_m)
    ex = float(origin_point.x) + ux * float(end_offset_m)
    ey = float(origin_point.y) + uy * float(end_offset_m)
    half = float(cross_half_len_m)
    from shapely.geometry import Polygon

    return Polygon(
        [
            (sx + vx * half, sy + vy * half),
            (sx - vx * half, sy - vy * half),
            (ex - vx * half, ey - vy * half),
            (ex + vx * half, ey + vy * half),
        ]
    )


def _rebalance_event_origin_for_rcsd_targets(
    *,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    target_rc_nodes: list[ParsedNode],
) -> tuple[Point, dict[str, Any]]:
    if axis_unit_vector is None or not target_rc_nodes:
        return origin_point, {"applied": False, "shift_m": 0.0, "direction": "none", "target_count": len(target_rc_nodes)}

    offsets = [
        _project_point_to_axis(
            node.geometry,
            origin_xy=(float(origin_point.x), float(origin_point.y)),
            axis_unit_vector=axis_unit_vector,
        )
        for node in target_rc_nodes
    ]
    if not offsets:
        return origin_point, {"applied": False, "shift_m": 0.0, "direction": "none", "target_count": 0}

    positive_overflow = max(0.0, max(offsets) - EVENT_SPAN_MAX_M)
    negative_overflow = max(0.0, abs(min(offsets)) - EVENT_SPAN_MAX_M)
    shift_m = 0.0
    direction = "none"
    if positive_overflow > 1e-6 and negative_overflow <= 1e-6:
        shift_m = min(float(positive_overflow), float(EVENT_RCSD_RECENTER_SHIFT_MAX_M))
        direction = "forward"
    elif negative_overflow > 1e-6 and positive_overflow <= 1e-6:
        shift_m = -min(float(negative_overflow), float(EVENT_RCSD_RECENTER_SHIFT_MAX_M))
        direction = "backward"
    if abs(float(shift_m)) <= 1e-6:
        return origin_point, {
            "applied": False,
            "shift_m": 0.0,
            "direction": direction,
            "target_count": len(offsets),
        }
    shifted_point = _point_from_axis_offset(
        origin_point=origin_point,
        axis_unit_vector=axis_unit_vector,
        offset_m=float(shift_m),
    )
    return shifted_point, {
        "applied": True,
        "shift_m": float(shift_m),
        "direction": direction,
        "target_count": len(offsets),
        "max_offset_m": float(max(offsets)),
        "min_offset_m": float(min(offsets)),
    }


def _collect_line_parts(geometry) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    if getattr(geometry, "geom_type", None) == "LineString":
        return [geometry] if float(geometry.length) > 1e-6 else []
    parts: list[Any] = []
    for item in _explode_component_geometries(geometry):
        if getattr(item, "geom_type", None) == "LineString" and float(item.length) > 1e-6:
            parts.append(item)
    return parts


def _build_event_crossline(
    *,
    origin_point: Point,
    axis_unit_vector: tuple[float, float],
    scan_dist_m: float,
    cross_half_len_m: float,
) -> LineString:
    ux, uy = axis_unit_vector
    vx, vy = -uy, ux
    cx = float(origin_point.x) + ux * float(scan_dist_m)
    cy = float(origin_point.y) + uy * float(scan_dist_m)
    hx = float(cross_half_len_m) * vx
    hy = float(cross_half_len_m) * vy
    return LineString([(cx - hx, cy - hy), (cx + hx, cy + hy)])


def _pick_cross_section_boundary_branches(
    *,
    road_branches,
    selected_branch_ids: set[str],
    kind_2: int,
):
    selected_branches = [branch for branch in road_branches if branch.branch_id in selected_branch_ids]
    if not selected_branches:
        selected_branches = list(road_branches)
    if kind_2 == 8:
        directional_candidates = [branch for branch in selected_branches if branch.has_incoming_support]
    else:
        directional_candidates = [branch for branch in selected_branches if branch.has_outgoing_support]
    if len(directional_candidates) < 2:
        directional_candidates = list(selected_branches)
    if len(directional_candidates) < 2:
        return None, None
    best_pair = None
    best_key = None
    for first_branch, second_branch in combinations(directional_candidates, 2):
        pair_key = (
            _branch_angle_gap_deg(first_branch, second_branch),
            _selected_branch_score(first_branch) + _selected_branch_score(second_branch),
        )
        if best_key is None or pair_key > best_key:
            best_key = pair_key
            best_pair = (first_branch, second_branch)
    if best_pair is None:
        return None, None
    return best_pair


def _collect_crossline_projection_points(geometry, *, crossline: LineString, center_point: Point) -> list[Point]:
    if geometry is None or geometry.is_empty:
        return []
    geometry_type = getattr(geometry, "geom_type", None)
    if geometry_type == "Point":
        return [geometry]
    if geometry_type == "MultiPoint":
        return [item for item in geometry.geoms if item is not None and not item.is_empty]
    if geometry_type == "LineString":
        return [geometry.interpolate(float(geometry.project(center_point)))]
    if geometry_type == "MultiLineString":
        return [
            line.interpolate(float(line.project(center_point)))
            for line in geometry.geoms
            if line is not None and not line.is_empty
        ]
    if geometry_type == "GeometryCollection":
        points: list[Point] = []
        for item in geometry.geoms:
            points.extend(
                _collect_crossline_projection_points(
                    item,
                    crossline=crossline,
                    center_point=center_point,
                )
            )
        return points
    return []


def _pick_point_on_branch_centerline(
    *,
    branch_centerline,
    crossline: LineString,
    center_point: Point,
) -> tuple[Point, bool]:
    intersection_geometry = branch_centerline.intersection(crossline)
    candidates = _collect_crossline_projection_points(
        intersection_geometry,
        crossline=crossline,
        center_point=center_point,
    )
    if candidates:
        point = min(candidates, key=lambda item: float(item.distance(center_point)))
        return Point(float(point.x), float(point.y)), True
    branch_point, _ = nearest_points(branch_centerline, crossline)
    return Point(float(branch_point.x), float(branch_point.y)), False


def _build_between_branches_segment(
    *,
    crossline: LineString,
    center_point: Point,
    branch_a_centerline,
    branch_b_centerline,
) -> tuple[LineString | None, dict[str, Any]]:
    if (
        branch_a_centerline is None
        or branch_a_centerline.is_empty
        or branch_b_centerline is None
        or branch_b_centerline.is_empty
    ):
        return None, {
            "ok": False,
            "reason": "missing_branch_centerline",
            "branch_a_crossline_hit": False,
            "branch_b_crossline_hit": False,
        }
    point_a, branch_a_hit = _pick_point_on_branch_centerline(
        branch_centerline=branch_a_centerline,
        crossline=crossline,
        center_point=center_point,
    )
    point_b, branch_b_hit = _pick_point_on_branch_centerline(
        branch_centerline=branch_b_centerline,
        crossline=crossline,
        center_point=center_point,
    )
    segment = LineString([(float(point_a.x), float(point_a.y)), (float(point_b.x), float(point_b.y))])
    return segment, {
        "ok": True,
        "reason": "ok",
        "seg_len_m": float(segment.length),
        "pa_center_dist_m": float(point_a.distance(center_point)),
        "pb_center_dist_m": float(point_b.distance(center_point)),
        "branch_a_crossline_hit": bool(branch_a_hit),
        "branch_b_crossline_hit": bool(branch_b_hit),
    }


def _extend_line_to_half_len(
    *,
    line: LineString,
    half_len_m: float,
):
    if line is None or line.is_empty:
        return line
    coords = list(line.coords)
    if len(coords) < 2:
        return line
    start_x, start_y = _coord_xy(coords[0])
    end_x, end_y = _coord_xy(coords[-1])
    vector = _normalize_axis_vector((end_x - start_x, end_y - start_y))
    if vector is None:
        return line
    center_point = line.interpolate(0.5, normalized=True)
    ux, uy = vector
    half = max(0.1, float(half_len_m))
    return LineString(
        [
            (float(center_point.x) - ux * half, float(center_point.y) - uy * half),
            (float(center_point.x) + ux * half, float(center_point.y) + uy * half),
        ]
    )


def _segment_drivezone_pieces(
    *,
    segment: LineString,
    drivezone_union,
    min_piece_len_m: float = 0.5,
) -> list[Any]:
    pieces = _collect_line_parts(segment.intersection(drivezone_union))
    return [piece for piece in pieces if float(piece.length) >= float(min_piece_len_m)]


def _resolve_parallel_centerline(
    *,
    local_roads: list[ParsedRoad],
    selected_road_ids: set[str],
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    reference_point: Point,
):
    if axis_centerline is None or axis_centerline.is_empty or axis_unit_vector is None:
        return None
    ux, uy = axis_unit_vector

    def _road_axis_alignment(road_geometry) -> float | None:
        if road_geometry is None or road_geometry.is_empty:
            return None
        coords = list(road_geometry.coords)
        if len(coords) < 2:
            return None
        start_x, start_y = _coord_xy(coords[0])
        end_x, end_y = _coord_xy(coords[-1])
        road_vector = _normalize_axis_vector((end_x - start_x, end_y - start_y))
        if road_vector is None:
            return None
        dot = abs(float(road_vector[0]) * ux + float(road_vector[1]) * uy)
        dot = max(-1.0, min(1.0, dot))
        return math.degrees(math.acos(dot))

    candidates: list[tuple[tuple[float, float], Any]] = []
    for road in local_roads:
        if road.road_id in selected_road_ids:
            continue
        angle_diff = _road_axis_alignment(road.geometry)
        if angle_diff is None or angle_diff > PARALLEL_ROAD_ANGLE_TOLERANCE_DEG:
            continue
        distance_to_axis = float(road.geometry.distance(axis_centerline))
        if distance_to_axis < PARALLEL_ROAD_MIN_OFFSET_M or distance_to_axis > PARALLEL_ROAD_MAX_OFFSET_M:
            continue
        candidates.append(
            (
                (
                    distance_to_axis,
                    float(road.geometry.distance(reference_point)),
                    -float(road.geometry.length),
                ),
                road.geometry,
            )
        )
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def _clip_line_to_parallel_midline(
    *,
    line: LineString,
    crossline: LineString,
    axis_centerline,
    parallel_centerline,
):
    if (
        line is None
        or line.is_empty
        or axis_centerline is None
        or axis_centerline.is_empty
        or parallel_centerline is None
        or parallel_centerline.is_empty
    ):
        return line
    center_point = crossline.interpolate(0.5, normalized=True)
    axis_point, _ = nearest_points(axis_centerline, crossline)
    parallel_point, _ = nearest_points(parallel_centerline, crossline)
    axis_s = float(crossline.project(axis_point))
    parallel_s = float(crossline.project(parallel_point))
    if not math.isfinite(axis_s) or not math.isfinite(parallel_s):
        return line
    midpoint_s = 0.5 * (axis_s + parallel_s)
    line_coords = list(line.coords)
    if len(line_coords) < 2:
        return line
    start_s = float(crossline.project(Point(_coord_xy(line_coords[0]))))
    end_s = float(crossline.project(Point(_coord_xy(line_coords[-1]))))
    lo = min(start_s, end_s)
    hi = max(start_s, end_s)
    if midpoint_s <= lo + 1e-6 or midpoint_s >= hi - 1e-6:
        return line
    if axis_s <= parallel_s:
        clipped_lo, clipped_hi = lo, midpoint_s
    else:
        clipped_lo, clipped_hi = midpoint_s, hi
    start_point = crossline.interpolate(clipped_lo)
    end_point = crossline.interpolate(clipped_hi)
    return LineString([(float(start_point.x), float(start_point.y)), (float(end_point.x), float(end_point.y))])


def _resolve_event_reference_position(
    *,
    representative_node: ParsedNode,
    scan_origin_point: Point,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    scan_axis_unit_vector: tuple[float, float] | None,
    branch_a_centerline,
    branch_b_centerline,
    drivezone_union,
    divstrip_constraint_geometry,
    event_anchor_geometry,
    cross_half_len_m: float,
):
    if axis_centerline is None or axis_centerline.is_empty or axis_unit_vector is None or scan_axis_unit_vector is None:
        return {
            "origin_point": scan_origin_point,
            "event_origin_source": "representative_axis_origin",
            "position_source": "representative_axis_origin",
            "chosen_s_m": 0.0,
            "scan_origin_point": scan_origin_point,
            "tip_s_m": None,
            "first_divstrip_hit_s_m": None,
            "first_divstrip_hit_dist_m": None,
            "s_drivezone_split_m": None,
            "split_pick_source": "none",
            "divstrip_ref_source": "none",
            "divstrip_ref_offset_m": None,
        }

    origin_xy = (float(scan_origin_point.x), float(scan_origin_point.y))
    candidate_offsets = _collect_axis_offsets_from_geometry(
        divstrip_constraint_geometry if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty else event_anchor_geometry,
        origin_xy=origin_xy,
        axis_unit_vector=axis_unit_vector,
    )
    if candidate_offsets:
        search_start = max(-EVENT_REFERENCE_SCAN_MAX_M, min(candidate_offsets) - EVENT_REFERENCE_SEARCH_MARGIN_M)
        search_end = min(EVENT_REFERENCE_SCAN_MAX_M, max(candidate_offsets) + EVENT_REFERENCE_SEARCH_MARGIN_M)
    else:
        search_start = -EVENT_REFERENCE_SEARCH_MARGIN_M
        search_end = EVENT_REFERENCE_SEARCH_MARGIN_M
    if search_end - search_start <= 1e-6:
        search_start = min(search_start, -EVENT_REFERENCE_SEARCH_MARGIN_M)
        search_end = max(search_end, EVENT_REFERENCE_SEARCH_MARGIN_M)

    tip_s = None
    first_divstrip_hit_s = None
    s_drivezone_split = None
    scan_samples: list[tuple[float, LineString]] = []
    split_pick_source = "none"
    divstrip_ref_source = "none"
    divstrip_ref_offset_m = None

    tip_point = _tip_point_from_divstrip(
        divstrip_geometry=divstrip_constraint_geometry,
        scan_axis_unit_vector=scan_axis_unit_vector,
        origin_point=scan_origin_point,
    )
    if tip_point is not None and not tip_point.is_empty:
        tip_s = _project_point_to_axis(
            tip_point,
            origin_xy=origin_xy,
            axis_unit_vector=axis_unit_vector,
        )

    offset = float(search_start)
    while offset <= float(search_end) + 1e-6:
        crossline = _build_event_crossline(
            origin_point=scan_origin_point,
            axis_unit_vector=axis_unit_vector,
            scan_dist_m=offset,
            cross_half_len_m=cross_half_len_m,
        )
        center_point = crossline.interpolate(0.5, normalized=True)
        found_segment, segment_diag = _build_between_branches_segment(
            crossline=crossline,
            center_point=center_point,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
        )
        if found_segment is not None and segment_diag["ok"]:
            scan_samples.append((float(offset), found_segment))
            if (
                divstrip_constraint_geometry is not None
                and not divstrip_constraint_geometry.is_empty
                and first_divstrip_hit_s is None
                and float(found_segment.distance(divstrip_constraint_geometry)) <= EVENT_REFERENCE_DIVSTRIP_TOL_M
            ):
                first_divstrip_hit_s = float(offset)
            pieces = _segment_drivezone_pieces(
                segment=found_segment,
                drivezone_union=drivezone_union,
            )
            if len(pieces) < 2:
                extended_segment = _extend_line_to_half_len(
                    line=found_segment,
                    half_len_m=max(0.5 * float(found_segment.length) + EVENT_REFERENCE_SPLIT_EXTEND_M, 0.1),
                )
                pieces = _segment_drivezone_pieces(
                    segment=extended_segment,
                    drivezone_union=drivezone_union,
                )
            if s_drivezone_split is None and len(pieces) >= 2:
                s_drivezone_split = float(offset)
        offset += EVENT_REFERENCE_SCAN_STEP_M

    divstrip_components = _collect_polygon_components(divstrip_constraint_geometry)
    if (
        len(divstrip_components) > 1
        and s_drivezone_split is not None
        and abs(float(s_drivezone_split)) >= float(EVENT_REFERENCE_DIVSTRIP_TARGET_BY_SPLIT_MIN_S_M) - 1e-9
        and scan_samples
    ):
        split_crossline = _build_event_crossline(
            origin_point=scan_origin_point,
            axis_unit_vector=axis_unit_vector,
            scan_dist_m=float(s_drivezone_split),
            cross_half_len_m=cross_half_len_m,
        )
        split_center_point = split_crossline.interpolate(0.5, normalized=True)
        split_segment, split_segment_diag = _build_between_branches_segment(
            crossline=split_crossline,
            center_point=split_center_point,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
        )
        if split_segment is not None and split_segment_diag["ok"]:
            selected_component = min(
                divstrip_components,
                key=lambda component: float(split_segment.distance(component)),
            )
            for sample_s, sample_segment in scan_samples:
                if float(sample_segment.distance(selected_component)) <= EVENT_REFERENCE_DIVSTRIP_TOL_M:
                    first_divstrip_hit_s = float(sample_s)
                    break

    divstrip_ref_s = None
    if first_divstrip_hit_s is not None:
        divstrip_ref_s = float(first_divstrip_hit_s)
        divstrip_ref_source = "first_hit"
    elif tip_s is not None and search_start - 1e-6 <= float(tip_s) <= search_end + 1e-6:
        divstrip_ref_s = float(tip_s)
        divstrip_ref_source = "tip_projection"
    chosen_s, position_source, split_pick_source = _pick_reference_s(
        divstrip_ref_s=divstrip_ref_s,
        divstrip_ref_source=divstrip_ref_source,
        drivezone_split_s=s_drivezone_split,
        max_offset_m=EVENT_REFERENCE_MAX_OFFSET_M,
    )
    if chosen_s is None:
        chosen_s = 0.0
        position_source = "representative_axis_origin"
    if divstrip_ref_s is not None:
        divstrip_ref_offset_m = abs(float(chosen_s) - float(divstrip_ref_s))
    chosen_point = Point(
        float(scan_origin_point.x) + float(axis_unit_vector[0]) * float(chosen_s),
        float(scan_origin_point.y) + float(axis_unit_vector[1]) * float(chosen_s),
    )
    return {
        "origin_point": chosen_point,
        "event_origin_source": (
            "representative_axis_origin"
            if str(position_source) == "representative_axis_origin"
            else f"chosen_s_{position_source}"
        ),
        "position_source": str(position_source),
        "chosen_s_m": float(chosen_s),
        "scan_origin_point": scan_origin_point,
        "tip_s_m": None if tip_s is None else float(tip_s),
        "first_divstrip_hit_s_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
        "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
        "s_drivezone_split_m": None if s_drivezone_split is None else float(s_drivezone_split),
        "split_pick_source": str(split_pick_source),
        "divstrip_ref_source": str(divstrip_ref_source),
        "divstrip_ref_offset_m": None if divstrip_ref_offset_m is None else float(divstrip_ref_offset_m),
    }


def _build_continuous_line_from_crossline(
    *,
    crossline: LineString,
    pieces_raw: list[Any],
    center_point: Point,
    found_segment: LineString,
    drivezone_union,
    edge_pad_m: float,
    support_geometry=None,
):
    if not pieces_raw:
        return None
    center_s = float(crossline.project(center_point))
    piece_info: list[tuple[Any, float, float, float, float, float]] = []
    for piece in pieces_raw:
        values: list[float] = []
        for coord in list(piece.coords):
            if len(coord) < 2:
                continue
            values.append(float(crossline.project(Point(float(coord[0]), float(coord[1])))))
        if not values:
            continue
        s0 = float(min(values))
        s1 = float(max(values))
        overlap_len = 0.0
        support_distance = float("inf")
        if support_geometry is not None and not support_geometry.is_empty:
            overlap_geometry = piece.intersection(support_geometry)
            overlap_len = float(getattr(overlap_geometry, "length", 0.0))
            if overlap_len <= 1e-6:
                support_distance = float(piece.distance(support_geometry))
            else:
                support_distance = 0.0
        piece_info.append((piece, s0, s1, 0.5 * (s0 + s1), overlap_len, support_distance))
    if not piece_info:
        return None

    point_a = Point(float(found_segment.coords[0][0]), float(found_segment.coords[0][1]))
    point_b = Point(float(found_segment.coords[-1][0]), float(found_segment.coords[-1][1]))
    point_a_s = float(crossline.project(point_a))
    point_b_s = float(crossline.project(point_b))
    left_ref_s, right_ref_s = (
        (point_a_s, point_b_s)
        if point_a_s <= point_b_s
        else (point_b_s, point_a_s)
    )

    center_hits = [item for item in piece_info if float(item[1]) - 1e-6 <= center_s <= float(item[2]) + 1e-6]
    support_hits = [
        item
        for item in piece_info
        if float(item[4]) > 1e-6 or float(item[5]) <= max(float(edge_pad_m) * 2.0, 3.0)
    ]
    candidate_pool = support_hits or piece_info
    if center_hits:
        selected_piece = min(
            [item for item in center_hits if item in candidate_pool] or candidate_pool,
            key=lambda item: (
                0 if float(item[4]) > 1e-6 else 1,
                -float(item[4]),
                float(item[5]),
                abs(float(item[3]) - center_s),
                abs(float(item[3]) - 0.5 * (left_ref_s + right_ref_s)),
                -float(item[0].length),
            ),
        )
    else:
        selected_piece = min(
            candidate_pool,
            key=lambda item: (
                0 if float(item[4]) > 1e-6 else 1,
                -float(item[4]),
                float(item[5]),
                min(abs(center_s - float(item[1])), abs(center_s - float(item[2])), abs(center_s - float(item[3]))),
                abs(float(item[3]) - center_s),
                -float(item[0].length),
            ),
        )

    base_s0 = float(selected_piece[1])
    base_s1 = float(selected_piece[2])
    found_segment_hits_drivezone = bool(
        _segment_drivezone_pieces(
            segment=found_segment,
            drivezone_union=drivezone_union,
            min_piece_len_m=0.5,
        )
    )
    if not found_segment_hits_drivezone:
        span_start = base_s0
        span_end = base_s1
    else:
        span_start = max(base_s0, float(left_ref_s) - max(0.0, float(edge_pad_m)))
        span_end = min(base_s1, float(right_ref_s) + max(0.0, float(edge_pad_m)))
    span_start = max(base_s0, min(span_start, center_s))
    span_end = min(base_s1, max(span_end, center_s))
    if span_end - span_start <= 1e-6:
        span_start = base_s0
        span_end = base_s1

    edge_touch_tol_m = 0.1
    if drivezone_union is not None and not drivezone_union.is_empty:
        start_probe = crossline.interpolate(span_start)
        end_probe = crossline.interpolate(span_end)
        if float(start_probe.distance(drivezone_union.boundary)) > edge_touch_tol_m + 1e-9 and span_start > base_s0 + 1e-9:
            span_start = base_s0
        if float(end_probe.distance(drivezone_union.boundary)) > edge_touch_tol_m + 1e-9 and span_end < base_s1 - 1e-9:
            span_end = base_s1
    if span_end - span_start <= 1e-6:
        return None
    start_point = crossline.interpolate(span_start)
    end_point = crossline.interpolate(span_end)
    return LineString([(float(start_point.x), float(start_point.y)), (float(end_point.x), float(end_point.y))])


def _build_cross_section_surface_geometry(
    *,
    drivezone_union,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    start_offset_m: float,
    end_offset_m: float,
    cross_half_len_m: float,
    axis_centerline,
    branch_a_centerline,
    branch_b_centerline,
    parallel_centerline,
    resolution_m: float,
    support_geometry=None,
):
    if axis_unit_vector is None:
        return GeometryCollection(), 0
    step_m = max(EVENT_CROSSLINE_STEP_M, float(resolution_m))
    start_m = float(min(start_offset_m, end_offset_m))
    end_m = float(max(start_offset_m, end_offset_m))
    scan_values = [start_m]
    cursor = start_m + step_m
    while cursor < end_m - 1e-9:
        scan_values.append(float(cursor))
        cursor += step_m
    if abs(end_m - scan_values[-1]) > 1e-9:
        scan_values.append(end_m)
    strip_geometries: list[Any] = []
    for scan_dist_m in scan_values:
        crossline = _build_event_crossline(
            origin_point=origin_point,
            axis_unit_vector=axis_unit_vector,
            scan_dist_m=scan_dist_m,
            cross_half_len_m=cross_half_len_m,
        )
        center_point = crossline.interpolate(0.5, normalized=True)
        found_segment, segment_diag = _build_between_branches_segment(
            crossline=crossline,
            center_point=center_point,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
        )
        if found_segment is None or not segment_diag["ok"]:
            continue
        drivezone_pieces = _collect_line_parts(crossline.intersection(drivezone_union))
        clipped_line = _build_continuous_line_from_crossline(
            crossline=crossline,
            pieces_raw=drivezone_pieces,
            center_point=center_point,
            found_segment=found_segment,
            drivezone_union=drivezone_union,
            edge_pad_m=max(step_m * 0.5, resolution_m * 0.75),
            support_geometry=support_geometry,
        )
        if clipped_line is None:
            continue
        clipped_line = _clip_line_to_parallel_midline(
            line=clipped_line,
            crossline=crossline,
            axis_centerline=axis_centerline,
            parallel_centerline=parallel_centerline,
        )
        if clipped_line is None or clipped_line.is_empty or float(clipped_line.length) <= 1e-6:
            continue
        strip_geometries.append(
            clipped_line.buffer(max(step_m * 0.55, resolution_m * 0.9), cap_style=2, join_style=2)
        )
    if not strip_geometries:
        return GeometryCollection(), 0
    surface_geometry = unary_union(strip_geometries).intersection(drivezone_union).buffer(0)
    return surface_geometry, len(strip_geometries)


def _resolve_event_reference_point(
    *,
    representative_node: ParsedNode,
    event_anchor_geometry,
    divstrip_constraint_geometry,
    all_divstrip_geometry,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    kind_2: int,
    drivezone_union,
    branch_a_centerline,
    branch_b_centerline,
    cross_half_len_m: float,
    patch_size_m: float,
) -> dict[str, Any]:
    fallback_point, fallback_source = _resolve_event_origin_point(
        representative_node=representative_node,
        event_anchor_geometry=event_anchor_geometry,
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        axis_centerline=axis_centerline,
    )
    if axis_centerline is None or axis_centerline.is_empty or axis_unit_vector is None:
        return {
            "origin_point": fallback_point,
            "event_origin_source": fallback_source,
            "scan_origin_point": fallback_point,
            "scan_dir_label": "none",
            "chosen_s_m": None,
            "tip_s_m": None,
            "first_divstrip_hit_dist_m": None,
            "s_drivezone_split_m": None,
            "position_source": "fallback",
            "split_pick_source": "fallback_no_axis",
            "divstrip_ref_source": "none",
            "divstrip_ref_offset_m": None,
        }

    scan_origin_point, _ = nearest_points(axis_centerline, representative_node.geometry)
    base_scan_axis_unit_vector = _resolve_scan_axis_unit_vector(
        axis_unit_vector=axis_unit_vector,
        kind_2=kind_2,
    )
    if base_scan_axis_unit_vector is None:
        return {
            "origin_point": fallback_point,
            "event_origin_source": fallback_source,
            "scan_origin_point": scan_origin_point,
            "scan_dir_label": "none",
            "chosen_s_m": None,
            "tip_s_m": None,
            "first_divstrip_hit_dist_m": None,
            "s_drivezone_split_m": None,
            "position_source": "fallback",
            "split_pick_source": "fallback_no_scan_dir",
            "divstrip_ref_source": "none",
            "divstrip_ref_offset_m": None,
        }

    search_limit_m = min(
        float(EVENT_REFERENCE_SCAN_MAX_M),
        max(float(EVENT_SPAN_MAX_M * 2.0), float(patch_size_m) * 0.45),
    )
    step_m = max(float(EVENT_REFERENCE_SCAN_STEP_M), 0.5)
    scan_values = [0.0]
    cursor = step_m
    while cursor <= search_limit_m + 1e-9:
        scan_values.append(float(cursor))
        cursor += step_m

    selected_divstrip_geometry = (
        divstrip_constraint_geometry
        if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty
        else all_divstrip_geometry
    )

    def _tip_projection_for_scan(scan_vec: tuple[float, float] | None) -> float | None:
        if (
            scan_vec is None
            or selected_divstrip_geometry is None
            or selected_divstrip_geometry.is_empty
        ):
            return None
        tip_point = _tip_point_from_divstrip(
            divstrip_geometry=selected_divstrip_geometry,
            scan_axis_unit_vector=scan_vec,
            origin_point=scan_origin_point,
        )
        if tip_point is None or tip_point.is_empty:
            return None
        candidate_tip_s = _project_point_to_axis(
            tip_point,
            origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
            axis_unit_vector=scan_vec,
        )
        if 0.0 <= float(candidate_tip_s) <= float(search_limit_m) + 1e-9:
            return float(candidate_tip_s)
        return None

    divstrip_components = _collect_polygon_components(all_divstrip_geometry)
    scan_axis_unit_vector = base_scan_axis_unit_vector
    tip_s_forward = _tip_projection_for_scan(base_scan_axis_unit_vector)
    reverse_scan_axis_unit_vector = (
        -float(base_scan_axis_unit_vector[0]),
        -float(base_scan_axis_unit_vector[1]),
    )
    tip_s_reverse = _tip_projection_for_scan(reverse_scan_axis_unit_vector)
    tip_s = tip_s_forward
    if tip_s is None and tip_s_reverse is not None:
        scan_axis_unit_vector = reverse_scan_axis_unit_vector
        tip_s = tip_s_reverse
    elif tip_s is not None and tip_s_reverse is not None and float(tip_s_reverse) + 1e-6 < float(tip_s):
        scan_axis_unit_vector = reverse_scan_axis_unit_vector
        tip_s = tip_s_reverse

    first_divstrip_hit_s = None
    drivezone_split_s = None
    drivezone_split_source = "none"
    scan_samples: list[tuple[float, Any]] = []
    for scan_dist_m in scan_values:
        crossline = _build_event_crossline(
            origin_point=scan_origin_point,
            axis_unit_vector=scan_axis_unit_vector,
            scan_dist_m=scan_dist_m,
            cross_half_len_m=cross_half_len_m,
        )
        center_point = crossline.interpolate(0.5, normalized=True)
        found_segment, segment_diag = _build_between_branches_segment(
            crossline=crossline,
            center_point=center_point,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
        )
        probe_geometry = (
            found_segment
            if found_segment is not None and segment_diag["ok"]
            else crossline
        )
        scan_samples.append((float(scan_dist_m), probe_geometry))
        if drivezone_split_s is None and found_segment is not None and segment_diag["ok"]:
            drivezone_pieces = _segment_drivezone_pieces(
                segment=found_segment,
                drivezone_union=drivezone_union,
                min_piece_len_m=0.5,
            )
            if len(drivezone_pieces) >= 2:
                drivezone_split_s = float(scan_dist_m)
                drivezone_split_source = "between_branches"
            if drivezone_split_s is None:
                extended_segment = _extend_line_to_half_len(
                    line=found_segment,
                    half_len_m=max(0.5 * float(found_segment.length) + EVENT_REFERENCE_SPLIT_EXTEND_M, 0.1),
                )
                drivezone_pieces = _segment_drivezone_pieces(
                    segment=extended_segment,
                    drivezone_union=drivezone_union,
                    min_piece_len_m=0.5,
                )
                if len(drivezone_pieces) >= 2:
                    drivezone_split_s = float(scan_dist_m)
                    drivezone_split_source = "between_branches"
            if drivezone_split_s is None:
                drivezone_pieces = _segment_drivezone_pieces(
                    segment=crossline,
                    drivezone_union=drivezone_union,
                    min_piece_len_m=0.5,
                )
                if len(drivezone_pieces) >= 2:
                    drivezone_split_s = float(scan_dist_m)
                    drivezone_split_source = "full_crossline"
            if drivezone_split_s is not None and drivezone_split_source == "none":
                drivezone_split_s = float(scan_dist_m)
                drivezone_split_source = "between_branches"
        if (
            first_divstrip_hit_s is None
            and selected_divstrip_geometry is not None
            and not selected_divstrip_geometry.is_empty
            and float(probe_geometry.distance(selected_divstrip_geometry)) <= float(EVENT_REFERENCE_DIVSTRIP_TOL_M)
        ):
            first_divstrip_hit_s = float(scan_dist_m)

    if (
        drivezone_split_s is not None
        and len(divstrip_components) > 1
        and abs(float(drivezone_split_s)) >= 5.0 - 1e-9
    ):
        split_component, _split_component_distance = _pick_divstrip_component_near_split(
            scan_origin_point=scan_origin_point,
            scan_axis_unit_vector=scan_axis_unit_vector,
            split_s=float(drivezone_split_s),
            cross_half_len_m=cross_half_len_m,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            divstrip_components=divstrip_components,
        )
        if split_component is not None and not split_component.is_empty:
            selected_divstrip_geometry = split_component
            tip_point = _tip_point_from_divstrip(
                divstrip_geometry=selected_divstrip_geometry,
                scan_axis_unit_vector=scan_axis_unit_vector,
                origin_point=scan_origin_point,
            )
            tip_s = None
            if tip_point is not None and not tip_point.is_empty:
                candidate_tip_s = _project_point_to_axis(
                    tip_point,
                    origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
                    axis_unit_vector=scan_axis_unit_vector,
                )
                if 0.0 <= float(candidate_tip_s) <= float(search_limit_m) + 1e-9:
                    tip_s = float(candidate_tip_s)
            first_divstrip_hit_s, _best_divstrip_distance = _scan_first_divstrip_hit(
                scan_samples=scan_samples,
                divstrip_geometry=selected_divstrip_geometry,
                div_tol_m=float(EVENT_REFERENCE_DIVSTRIP_TOL_M),
            )

    divstrip_ref_s = None
    divstrip_ref_source = "none"
    if first_divstrip_hit_s is not None:
        divstrip_ref_s = float(first_divstrip_hit_s)
        divstrip_ref_source = "first_hit"
    elif tip_s is not None:
        divstrip_ref_s = float(tip_s)
        divstrip_ref_source = "tip_projection"

    if (
        drivezone_split_s is not None
        and drivezone_split_source == "full_crossline"
        and divstrip_ref_s is not None
        and abs(float(drivezone_split_s) - float(divstrip_ref_s)) > float(EVENT_REFERENCE_MAX_OFFSET_M)
    ):
        drivezone_split_s = None
        drivezone_split_source = "none"

    chosen_s, position_source, split_pick_source = _pick_reference_s(
        divstrip_ref_s=divstrip_ref_s,
        divstrip_ref_source=divstrip_ref_source,
        drivezone_split_s=drivezone_split_s,
        max_offset_m=float(EVENT_REFERENCE_MAX_OFFSET_M),
    )
    if chosen_s is None:
        reverse_scan_axis_unit_vector = (-float(scan_axis_unit_vector[0]), -float(scan_axis_unit_vector[1]))
        reverse_tip_s = None
        if selected_divstrip_geometry is not None and not selected_divstrip_geometry.is_empty:
            reverse_tip_point = _tip_point_from_divstrip(
                divstrip_geometry=selected_divstrip_geometry,
                scan_axis_unit_vector=reverse_scan_axis_unit_vector,
                origin_point=scan_origin_point,
            )
            if reverse_tip_point is not None and not reverse_tip_point.is_empty:
                candidate_reverse_tip_s = _project_point_to_axis(
                    reverse_tip_point,
                    origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
                    axis_unit_vector=scan_axis_unit_vector,
                )
                if -float(search_limit_m) - 1e-9 <= float(candidate_reverse_tip_s) <= 1e-9:
                    reverse_tip_s = float(candidate_reverse_tip_s)

        reverse_first_divstrip_hit_s = None
        reverse_drivezone_split_s = None
        for scan_dist_m in scan_values:
            reverse_scan_dist = -float(scan_dist_m)
            crossline = _build_event_crossline(
                origin_point=scan_origin_point,
                axis_unit_vector=scan_axis_unit_vector,
                scan_dist_m=reverse_scan_dist,
                cross_half_len_m=cross_half_len_m,
            )
            center_point = crossline.interpolate(0.5, normalized=True)
            found_segment, segment_diag = _build_between_branches_segment(
                crossline=crossline,
                center_point=center_point,
                branch_a_centerline=branch_a_centerline,
                branch_b_centerline=branch_b_centerline,
            )
            probe_geometry = (
                found_segment
                if found_segment is not None and segment_diag["ok"]
                else crossline
            )
            if reverse_drivezone_split_s is None and found_segment is not None and segment_diag["ok"]:
                drivezone_pieces = _segment_drivezone_pieces(
                    segment=found_segment,
                    drivezone_union=drivezone_union,
                    min_piece_len_m=0.5,
                )
                if len(drivezone_pieces) < 2:
                    extended_segment = _extend_line_to_half_len(
                        line=found_segment,
                        half_len_m=max(0.5 * float(found_segment.length) + EVENT_REFERENCE_SPLIT_EXTEND_M, 0.1),
                    )
                    drivezone_pieces = _segment_drivezone_pieces(
                        segment=extended_segment,
                        drivezone_union=drivezone_union,
                        min_piece_len_m=0.5,
                    )
                if len(drivezone_pieces) >= 2:
                    reverse_drivezone_split_s = reverse_scan_dist
            if (
                reverse_first_divstrip_hit_s is None
                and selected_divstrip_geometry is not None
                and not selected_divstrip_geometry.is_empty
                and float(probe_geometry.distance(selected_divstrip_geometry)) <= float(EVENT_REFERENCE_DIVSTRIP_TOL_M)
            ):
                reverse_first_divstrip_hit_s = reverse_scan_dist

        reverse_divstrip_ref_s = None
        reverse_divstrip_ref_source = "none"
        if reverse_first_divstrip_hit_s is not None:
            reverse_divstrip_ref_s = float(reverse_first_divstrip_hit_s)
            reverse_divstrip_ref_source = "first_hit"
        elif reverse_tip_s is not None:
            reverse_divstrip_ref_s = float(reverse_tip_s)
            reverse_divstrip_ref_source = "tip_projection"
        reverse_chosen_s, reverse_position_source, reverse_split_pick_source = _pick_reference_s(
            divstrip_ref_s=reverse_divstrip_ref_s,
            divstrip_ref_source=reverse_divstrip_ref_source,
            drivezone_split_s=reverse_drivezone_split_s,
            max_offset_m=float(EVENT_REFERENCE_MAX_OFFSET_M),
        )
        if reverse_chosen_s is not None:
            chosen_s = float(reverse_chosen_s)
            position_source = str(reverse_position_source)
            split_pick_source = f"reverse_{reverse_split_pick_source}"
            tip_s = None if reverse_tip_s is None else float(reverse_tip_s)
            first_divstrip_hit_s = (
                None if reverse_first_divstrip_hit_s is None else float(reverse_first_divstrip_hit_s)
            )
            drivezone_split_s = (
                None if reverse_drivezone_split_s is None else float(reverse_drivezone_split_s)
            )
            divstrip_ref_source = str(reverse_divstrip_ref_source)
    if chosen_s is None:
        return {
            "origin_point": fallback_point,
            "event_origin_source": fallback_source,
            "scan_origin_point": scan_origin_point,
            "scan_dir_label": "forward" if kind_2 == 16 else "backward",
            "chosen_s_m": None,
            "tip_s_m": None if tip_s is None else float(tip_s),
            "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
            "s_drivezone_split_m": None if drivezone_split_s is None else float(drivezone_split_s),
            "position_source": "fallback",
            "split_pick_source": f"{split_pick_source}_fallback",
            "divstrip_ref_source": str(divstrip_ref_source),
            "divstrip_ref_offset_m": None,
        }

    if _is_drivezone_position_source(position_source):
        window_lo, window_hi, target_s = _build_ref_window_toward_node(
            ref_s=float(chosen_s),
            window_m=float(EVENT_REFERENCE_HARD_WINDOW_M),
        )
        if float(chosen_s) >= 0.0:
            window_lo = float(max(0.0, window_lo))
            window_hi = float(max(0.0, window_hi))
            target_s = float(max(0.0, target_s))
        else:
            window_lo = float(min(0.0, window_lo))
            window_hi = float(min(0.0, window_hi))
            target_s = float(min(0.0, target_s))
        if window_hi + 1e-9 < window_lo:
            window_lo = float(chosen_s)
            window_hi = float(chosen_s)
            target_s = float(chosen_s)
    else:
        window_lo, window_hi, target_s = _build_ref_window_toward_node(
            ref_s=float(chosen_s),
            window_m=float(EVENT_REFERENCE_HARD_WINDOW_M),
        )
    probe_step = min(float(EVENT_REFERENCE_PROBE_STEP_M), max(0.05, step_m))
    candidate_scan_values: list[float] = []
    cursor = float(window_lo)
    while cursor <= float(window_hi) + 1e-9:
        candidate_scan_values.append(float(max(window_lo, min(window_hi, cursor))))
        cursor += probe_step
    if not candidate_scan_values:
        candidate_scan_values = [float(max(window_lo, min(window_hi, float(chosen_s))))]
    target_in_window = float(max(window_lo, min(window_hi, float(target_s))))
    if all(abs(float(value) - target_in_window) > 1e-6 for value in candidate_scan_values):
        candidate_scan_values.append(float(target_in_window))

    def _probe_scan_candidates(scan_values: list[float]) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for scan_value in scan_values:
            crossline = _build_event_crossline(
                origin_point=scan_origin_point,
                axis_unit_vector=scan_axis_unit_vector,
                scan_dist_m=float(scan_value),
                cross_half_len_m=cross_half_len_m,
            )
            pieces = _segment_drivezone_pieces(
                segment=crossline,
                drivezone_union=drivezone_union,
                min_piece_len_m=0.5,
            )
            if not pieces:
                continue
            center_point = Point(
                float(scan_origin_point.x) + float(scan_axis_unit_vector[0]) * float(scan_value),
                float(scan_origin_point.y) + float(scan_axis_unit_vector[1]) * float(scan_value),
            )
            center_s = float(crossline.project(center_point))
            piece_info: list[tuple[float, float, float]] = []
            for piece in pieces:
                values: list[float] = []
                for coord in list(piece.coords):
                    if len(coord) < 2:
                        continue
                    values.append(float(crossline.project(Point(float(coord[0]), float(coord[1])))))
                if not values:
                    continue
                start_s = float(min(values))
                end_s = float(max(values))
                piece_info.append((start_s, end_s, 0.5 * (start_s + end_s)))
            if not piece_info:
                continue
            has_center_piece = any(float(item[0]) - 1e-6 <= center_s <= float(item[1]) + 1e-6 for item in piece_info)
            hits.append(
                {
                    "s": float(scan_value),
                    "raw_count": int(len(pieces)),
                    "has_center_piece": bool(has_center_piece),
                }
            )
        return hits

    candidate_hits = _probe_scan_candidates(candidate_scan_values)
    backtrack_single_hit = None
    if _is_drivezone_position_source(position_source) and not any(int(hit["raw_count"]) == 1 for hit in candidate_hits):
        backtrack_candidates = _build_drivezone_backtrack_candidates(
            ref_s=float(chosen_s),
            start_s=float(target_in_window),
            probe_step=float(probe_step),
            past_node_m=float(EVENT_REFERENCE_BACKTRACK_PAST_NODE_M),
        )
        backtrack_hits = _probe_scan_candidates(backtrack_candidates)
        for hit in backtrack_hits:
            if int(hit["raw_count"]) == 1 and bool(hit["has_center_piece"]):
                backtrack_single_hit = hit
                break
        if backtrack_single_hit is None:
            for hit in backtrack_hits:
                if int(hit["raw_count"]) == 1:
                    backtrack_single_hit = hit
                    break
        candidate_hits.extend(backtrack_hits)

    if candidate_hits:
        if backtrack_single_hit is not None:
            final_scan_s = float(backtrack_single_hit["s"])
            split_pick_source = f"{split_pick_source}_backtrack_single_piece"
        else:
            best_hit = min(
                candidate_hits,
                key=lambda hit: (
                    0 if bool(hit["has_center_piece"]) else 1,
                    0 if int(hit["raw_count"]) == 1 else 1,
                    int(hit["raw_count"]),
                    abs(float(hit["s"]) - float(target_in_window)),
                ),
            )
            final_scan_s = float(best_hit["s"])
    else:
        final_scan_s = float(chosen_s)

    chosen_point = _point_from_axis_offset(
        origin_point=scan_origin_point,
        axis_unit_vector=scan_axis_unit_vector,
        offset_m=float(final_scan_s),
    )
    divstrip_ref_offset_m = (
        None
        if divstrip_ref_s is None
        else float(abs(float(final_scan_s) - float(divstrip_ref_s)))
    )
    return {
        "origin_point": chosen_point,
        "event_origin_source": f"chosen_s_{position_source}",
        "scan_origin_point": scan_origin_point,
        "scan_dir_label": "forward" if kind_2 == 16 else "backward",
        "chosen_s_m": float(final_scan_s),
        "tip_s_m": None if tip_s is None else float(tip_s),
        "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
        "s_drivezone_split_m": None if drivezone_split_s is None else float(drivezone_split_s),
        "position_source": str(position_source),
        "split_pick_source": str(split_pick_source),
        "divstrip_ref_source": str(divstrip_ref_source),
        "divstrip_ref_offset_m": divstrip_ref_offset_m,
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
    multibranch_enabled = len({item["source_branch_id"] for item in candidate_items if item["source_branch_id"] is not None}) > 2
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
        and _is_stage4_supported_node_kind(node)
        and normalize_id(node.node_id) == normalize_id(representative_id)
    )


def _stage4_chain_kind_2(node: ParsedNode) -> int | None:
    source_kind_2 = _node_source_kind_2(node)
    if source_kind_2 in STAGE4_KIND_2_VALUES or source_kind_2 == COMPLEX_JUNCTION_KIND:
        return source_kind_2
    if _node_source_kind(node) == COMPLEX_JUNCTION_KIND:
        return COMPLEX_JUNCTION_KIND
    return None


def _infer_operational_kind_2_from_divstrip_event(
    *,
    representative_node: ParsedNode,
    road_branches,
    local_roads: list[ParsedRoad],
    divstrip_context: dict[str, Any],
    chain_context: dict[str, Any],
) -> dict[str, Any] | None:
    divstrip_constraint_geometry = divstrip_context["constraint_geometry"]
    if (
        divstrip_constraint_geometry is None
        or divstrip_constraint_geometry.is_empty
        or not divstrip_context["nearby"]
        or divstrip_context["ambiguous"]
    ):
        return None

    event_reference_point = divstrip_constraint_geometry.centroid
    road_lookup = {road.road_id: road for road in local_roads}
    merge_score = 0.0
    diverge_score = 0.0
    merge_hits = 0
    diverge_hits = 0
    for branch in road_branches:
        centerline = _resolve_branch_centerline(
            branch=branch,
            road_lookup=road_lookup,
            reference_point=representative_node.geometry,
        )
        if centerline is None or centerline.is_empty:
            continue
        representative_dist = float(centerline.project(representative_node.geometry))
        event_dist = float(centerline.project(event_reference_point))
        branch_support = max(1.0, _selected_branch_score(branch))
        if branch.has_incoming_support:
            post_event_m = float(representative_dist - event_dist)
            if post_event_m >= DIVSTRIP_KIND_POSITION_MARGIN_M:
                merge_hits += 1
                merge_score += branch_support + min(post_event_m, 40.0)
        if branch.has_outgoing_support:
            pre_event_m = float(event_dist - representative_dist)
            if pre_event_m >= DIVSTRIP_KIND_POSITION_MARGIN_M:
                diverge_hits += 1
                diverge_score += branch_support + min(pre_event_m, 40.0)

    if chain_context["is_in_continuous_chain"] and chain_context["sequential_ok"]:
        if diverge_score > 0.0:
            diverge_score += 25.0
        if merge_score > 0.0:
            merge_score += 25.0

    if merge_score <= 0.0 and diverge_score <= 0.0:
        return None

    if merge_score > diverge_score:
        operational_kind_2 = 8
    elif diverge_score > merge_score:
        operational_kind_2 = 16
    elif merge_hits > diverge_hits:
        operational_kind_2 = 8
    elif diverge_hits > merge_hits:
        operational_kind_2 = 16
    else:
        operational_kind_2 = 16

    ambiguous = (
        abs(merge_score - diverge_score) <= MULTIBRANCH_AMBIGUITY_SCORE_MARGIN
        and merge_hits == diverge_hits
    )
    return {
        "operational_kind_2": operational_kind_2,
        "ambiguous": ambiguous,
        "kind_resolution_mode": (
            "continuous_chain_divstrip_event"
            if chain_context["is_in_continuous_chain"] and chain_context["sequential_ok"]
            else "divstrip_event_position"
        ),
        "merge_score": round(merge_score, 3),
        "diverge_score": round(diverge_score, 3),
        "merge_hits": merge_hits,
        "diverge_hits": diverge_hits,
    }


def _resolve_operational_kind_2(
    *,
    representative_node: ParsedNode,
    road_branches,
    main_branch_ids: set[str],
    preferred_branch_ids: set[str],
    local_roads: list[ParsedRoad],
    divstrip_context: dict[str, Any],
    chain_context: dict[str, Any],
) -> dict[str, Any]:
    source_kind = _node_source_kind(representative_node)
    source_kind_2 = _node_source_kind_2(representative_node)
    if source_kind_2 in STAGE4_KIND_2_VALUES:
        return {
            "source_kind": source_kind,
            "source_kind_2": source_kind_2,
            "operational_kind_2": int(source_kind_2),
            "complex_junction": False,
            "ambiguous": False,
            "kind_resolution_mode": "direct_kind_2",
            "merge_score": None,
            "diverge_score": None,
            "merge_hits": None,
            "diverge_hits": None,
        }
    divstrip_kind_resolution = None
    if len(road_branches) <= 2 or source_kind == COMPLEX_JUNCTION_KIND or source_kind_2 == COMPLEX_JUNCTION_KIND:
        divstrip_kind_resolution = _infer_operational_kind_2_from_divstrip_event(
            representative_node=representative_node,
            road_branches=road_branches,
            local_roads=local_roads,
            divstrip_context=divstrip_context,
            chain_context=chain_context,
        )
    if divstrip_kind_resolution is not None and not divstrip_kind_resolution["ambiguous"]:
        return {
            "source_kind": source_kind,
            "source_kind_2": source_kind_2,
            "operational_kind_2": divstrip_kind_resolution["operational_kind_2"],
            "complex_junction": source_kind == COMPLEX_JUNCTION_KIND or source_kind_2 == COMPLEX_JUNCTION_KIND,
            "ambiguous": False,
            "kind_resolution_mode": divstrip_kind_resolution["kind_resolution_mode"],
            "merge_score": divstrip_kind_resolution["merge_score"],
            "diverge_score": divstrip_kind_resolution["diverge_score"],
            "merge_hits": divstrip_kind_resolution["merge_hits"],
            "diverge_hits": divstrip_kind_resolution["diverge_hits"],
        }
    if source_kind != COMPLEX_JUNCTION_KIND and source_kind_2 != COMPLEX_JUNCTION_KIND:
        raise Stage4RunError(
            REASON_MAINNODEID_OUT_OF_SCOPE,
            (
                f"mainnodeid='{normalize_id(representative_node.mainnodeid or representative_node.node_id)}' "
                f"has unsupported kind={source_kind}, kind_2={source_kind_2}."
            ),
        )

    side_branches = [branch for branch in road_branches if branch.branch_id not in main_branch_ids]
    merge_score = 0.0
    diverge_score = 0.0
    merge_hits = 0
    diverge_hits = 0
    merge_preferred_hits = 0
    diverge_preferred_hits = 0
    for branch in side_branches:
        branch_score = max(1.0, _selected_branch_score(branch))
        if branch.has_incoming_support:
            merge_hits += 1
            merge_score += branch_score
            if branch.branch_id in preferred_branch_ids:
                merge_preferred_hits += 1
                merge_score += 100.0
        if branch.has_outgoing_support:
            diverge_hits += 1
            diverge_score += branch_score
            if branch.branch_id in preferred_branch_ids:
                diverge_preferred_hits += 1
                diverge_score += 100.0

    if merge_score > diverge_score:
        operational_kind_2 = 8
    elif diverge_score > merge_score:
        operational_kind_2 = 16
    elif merge_hits > diverge_hits:
        operational_kind_2 = 8
    elif diverge_hits > merge_hits:
        operational_kind_2 = 16
    elif merge_preferred_hits > diverge_preferred_hits:
        operational_kind_2 = 8
    else:
        operational_kind_2 = 16

    ambiguous = (
        not side_branches
        or (
            abs(merge_score - diverge_score) <= MULTIBRANCH_AMBIGUITY_SCORE_MARGIN
            and merge_hits == diverge_hits
            and merge_preferred_hits == diverge_preferred_hits
        )
    )
    return {
        "source_kind": source_kind,
        "source_kind_2": source_kind_2,
        "operational_kind_2": operational_kind_2,
        "complex_junction": True,
        "ambiguous": ambiguous,
        "kind_resolution_mode": "complex_branch_direction",
        "merge_score": round(merge_score, 3),
        "diverge_score": round(diverge_score, 3),
        "merge_hits": merge_hits,
        "diverge_hits": diverge_hits,
    }


def _build_continuous_chain_context(
    *,
    representative_node: ParsedNode,
    local_nodes: list[ParsedNode],
    enabled: bool = True,
) -> dict[str, Any]:
    representative_mainnodeid = normalize_id(representative_node.mainnodeid or representative_node.node_id)
    if not enabled:
        return {
            "chain_component_id": representative_mainnodeid,
            "related_mainnodeids": [],
            "is_in_continuous_chain": False,
            "chain_node_count": 1,
            "chain_node_offset_m": None,
            "sequential_ok": False,
            "related_seed_nodes": [],
        }

    representative_chain_kind_2 = _stage4_chain_kind_2(representative_node)
    chain_candidates: list[tuple[ParsedNode, float]] = []
    for candidate in local_nodes:
        if not _is_stage4_representative(candidate):
            continue
        candidate_mainnodeid = normalize_id(candidate.mainnodeid or candidate.node_id)
        if candidate_mainnodeid == representative_mainnodeid:
            continue
        candidate_chain_kind_2 = _stage4_chain_kind_2(candidate)
        if candidate_chain_kind_2 is None or representative_chain_kind_2 is None:
            continue
        offset_m = float(candidate.geometry.distance(representative_node.geometry))
        if offset_m <= CHAIN_NEARBY_DISTANCE_M:
            chain_candidates.append((candidate, offset_m))

    chain_candidates.sort(key=lambda item: item[1])
    related_mainnodeids = [normalize_id(candidate.mainnodeid or candidate.node_id) for candidate, _ in chain_candidates]
    nearest_offset_m = None if not chain_candidates else round(chain_candidates[0][1], 3)
    sequential_ok = any(
        offset_m <= CHAIN_SEQUENCE_DISTANCE_M and _stage4_chain_kind_2(candidate) != representative_chain_kind_2
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
    debug_render_root: Optional[Union[str, Path]] = None,
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
    rendered_maps_root = (
        Path(debug_render_root)
        if debug_render_root is not None
        else out_root_path.parent / "_rendered_maps"
    )
    rendered_map_path = rendered_maps_root / f"{normalize_id(mainnodeid) or 'unknown'}.png" if debug else None

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
        representative_source_kind = _node_source_kind(representative_node)
        representative_source_kind_2 = _node_source_kind_2(representative_node)
        representative_kind_2 = representative_source_kind_2
        representative_grade_2 = representative_node.grade_2
        if (
            representative_node.has_evd != "yes"
            or representative_node.is_anchor != "no"
            or not _is_stage4_supported_node_kind(representative_node)
        ):
            raise Stage4RunError(
                REASON_MAINNODEID_OUT_OF_SCOPE,
                (
                    f"mainnodeid='{mainnodeid_norm}' is out of scope: "
                    f"has_evd={representative_node.has_evd}, is_anchor={representative_node.is_anchor}, "
                    f"kind={representative_source_kind}, kind_2={representative_source_kind_2}."
                ),
            )

        current_patch_id = _resolve_current_patch_id_from_roads(group_nodes=group_nodes, roads=roads)
        filtered_roads = _filter_parsed_roads_to_patch(roads, patch_id=current_patch_id)
        filtered_drivezone_features = [
            feature
            for feature in _filter_loaded_features_to_patch(drivezone_layer_data.features, patch_id=current_patch_id)
            if feature.geometry is not None and not feature.geometry.is_empty
        ]

        direct_target_rc_nodes = [
            node
            for node in rcsd_nodes
            if node.mainnodeid == mainnodeid_norm or (node.mainnodeid is None and node.node_id == mainnodeid_norm)
        ]
        primary_main_rc_node = _pick_primary_main_rc_node(
            target_rc_nodes=direct_target_rc_nodes,
            mainnodeid_norm=mainnodeid_norm,
        )
        exact_target_rc_nodes = [
            node
            for node in direct_target_rc_nodes
            if primary_main_rc_node is None or normalize_id(node.node_id) != normalize_id(primary_main_rc_node.node_id)
        ]
        rcsdnode_seed_mode = "direct_mainnodeid_group" if direct_target_rc_nodes else "missing_direct_mainnodeid_group"

        drivezone_union = unary_union([feature.geometry for feature in filtered_drivezone_features])
        if drivezone_union.is_empty:
            raise Stage4RunError(REASON_MISSING_REQUIRED_FIELD, "DriveZone layer has no non-empty geometry.")

        if direct_target_rc_nodes:
            _validate_drivezone_containment(drivezone_union=drivezone_union, features=direct_target_rc_nodes, label="RCSDNode")

        seed_geometries = [representative_node.geometry, *[node.geometry for node in group_nodes], *[node.geometry for node in exact_target_rc_nodes]]
        seed_union = unary_union(seed_geometries)
        seed_center = seed_union.centroid if not seed_union.is_empty else representative_node.geometry
        farthest_seed_distance = max((float(Point(seed.x, seed.y).distance(seed_center)) for seed in [representative_node.geometry, *[node.geometry for node in group_nodes], *[node.geometry for node in exact_target_rc_nodes]]), default=0.0)
        patch_size_m = max(DEFAULT_PATCH_SIZE_M, 260.0, farthest_seed_distance * 2.0 + 60.0)
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
        local_roads = [road for road in filtered_roads if road.geometry.intersects(grid.patch_polygon)]
        local_rcsd_roads = [road for road in rcsd_roads if road.geometry.intersects(grid.patch_polygon)]
        local_rcsd_nodes = [node for node in rcsd_nodes if node.geometry.intersects(grid.patch_polygon)]
        raw_local_divstrip_features = [
            feature
            for feature in (
                []
                if divstripzone_layer_data is None
                else _filter_loaded_features_to_patch(divstripzone_layer_data.features, patch_id=current_patch_id)
            )
            if feature.geometry is not None and not feature.geometry.is_empty
        ]
        local_divstrip_features = _clip_loaded_features_to_geometry(
            features=raw_local_divstrip_features,
            clip_geometry=grid.patch_polygon,
        )
        counts["current_patch_id"] = current_patch_id
        counts["local_node_count"] = len(local_nodes)
        counts["local_road_count"] = len(local_roads)
        counts["local_rcsdroad_count"] = len(local_rcsd_roads)
        counts["local_rcsdnode_count"] = len(local_rcsd_nodes)
        counts["local_divstrip_feature_count"] = len(local_divstrip_features)
        local_divstrip_union = unary_union([feature.geometry for feature in local_divstrip_features]) if local_divstrip_features else GeometryCollection()

        chain_context = _build_continuous_chain_context(
            representative_node=representative_node,
            local_nodes=local_nodes,
            enabled=True,
        )
        member_node_ids = {node.node_id for node in group_nodes}
        _, _, road_branches = _build_road_branches_for_member_nodes(
            local_roads,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
        )
        if _is_complex_stage4_node(representative_node) and chain_context["related_mainnodeids"]:
            needs_augmented_complex_context = len(road_branches) < 2
            if not needs_augmented_complex_context:
                try:
                    _select_main_pair(road_branches)
                except Exception:
                    needs_augmented_complex_context = True
            if needs_augmented_complex_context:
                related_mainnodeids = {
                    normalize_id(mainnodeid)
                    for mainnodeid in chain_context["related_mainnodeids"]
                }
                augmented_member_node_ids = set(member_node_ids)
                augmented_member_node_ids.update(
                    node.node_id
                    for node in local_nodes
                    if normalize_id(node.mainnodeid or node.node_id) in related_mainnodeids
                )
                _, _, road_branches = _build_road_branches_for_member_nodes(
                    local_roads,
                    member_node_ids=augmented_member_node_ids,
                    drivezone_union=drivezone_union,
                )
                member_node_ids = augmented_member_node_ids
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
            drivezone_union=drivezone_union,
        )
        preferred_branch_ids = set(divstrip_context["preferred_branch_ids"])
        kind_resolution = _resolve_operational_kind_2(
            representative_node=representative_node,
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            preferred_branch_ids=preferred_branch_ids,
            local_roads=local_roads,
            divstrip_context=divstrip_context,
            chain_context=chain_context,
        )
        operational_kind_2 = kind_resolution["operational_kind_2"]
        multibranch_context = _resolve_multibranch_context(
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            preferred_branch_ids=preferred_branch_ids,
            kind_2=operational_kind_2,
            local_roads=local_roads,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
            divstrip_constraint_geometry=divstrip_context["constraint_geometry"],
        )
        forward_side_branches = _select_stage4_side_branches(
            road_branches,
            kind_2=operational_kind_2,
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
        selected_side_branches = (
            list(multibranch_context["selected_side_branches"])
            if multibranch_context["enabled"] and multibranch_context["selected_side_branches"]
            else list(forward_side_branches)
        )
        if reverse_tip_attempted:
            reverse_side_branches = _select_reverse_tip_side_branches(
                road_branches,
                kind_2=operational_kind_2,
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

        selected_event_branch_ids = (
            multibranch_context["selected_event_branch_ids"]
            if multibranch_context["enabled"] and multibranch_context["selected_event_branch_ids"]
            else sorted(branch.branch_id for branch in selected_side_branches)
        )
        refined_divstrip_context = _analyze_divstrip_context(
            local_divstrip_features=local_divstrip_features,
            seed_union=seed_union,
            road_branches=road_branches,
            local_roads=local_roads,
            main_branch_ids=main_branch_ids,
            drivezone_union=drivezone_union,
            event_branch_ids=set(selected_event_branch_ids),
        )
        if (
            refined_divstrip_context["nearby"]
            or refined_divstrip_context["ambiguous"]
            or refined_divstrip_context["selected_component_ids"]
        ):
            divstrip_context = refined_divstrip_context
            preferred_branch_ids = set(divstrip_context["preferred_branch_ids"])
        position_source_forward = divstrip_context["selection_mode"]
        position_source_final = (
            position_source_reverse
            if reverse_tip_used and position_source_reverse is not None
            else ("multibranch_event" if multibranch_context["enabled"] else position_source_forward)
        )
        selected_branch_ids = (
            sorted(multibranch_context["selected_event_source_branch_ids"])
            if multibranch_context["enabled"] and multibranch_context["selected_event_source_branch_ids"]
            else sorted(main_branch_ids | {branch.branch_id for branch in selected_side_branches})
        )

        selected_road_ids = sorted({road_id for branch in road_branches if branch.branch_id in selected_branch_ids for road_id in branch.road_ids})
        selected_event_road_ids = {
            road_id
            for branch in road_branches
            if branch.branch_id in set(selected_event_branch_ids)
            for road_id in branch.road_ids
        }
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
        rcsdroad_selection_mode = "angle_match"
        if not selected_rcsdroad_ids:
            nearby_rcsd_roads = [
                road
                for road in local_rcsd_roads
                if road.geometry.distance(seed_center) <= max(30.0, patch_size_m / 5.0)
            ]
            inside_nearby_rcsd_roads = [
                road
                for road in nearby_rcsd_roads
                if drivezone_union.buffer(0).covers(road.geometry)
            ]
            fallback_rcsd_roads = inside_nearby_rcsd_roads or nearby_rcsd_roads
            selected_rcsdroad_ids = {road.road_id for road in fallback_rcsd_roads}
            rcsdroad_selection_mode = (
                "fallback_nearby_inside_only"
                if inside_nearby_rcsd_roads
                else "fallback_nearby_any"
            )

        selected_roads = [road for road in local_roads if road.road_id in selected_road_ids]
        selected_event_roads = [road for road in local_roads if road.road_id in selected_event_road_ids]
        selected_rcsd_roads = [road for road in local_rcsd_roads if road.road_id in selected_rcsdroad_ids]
        selected_rcsd_buffer = unary_union(
            [
                road.geometry.buffer(max(1.5, RC_ROAD_BUFFER_M), cap_style=2, join_style=2)
                for road in selected_rcsd_roads
            ]
        )
        selected_rcsdnode_ids = {
            node.node_id
            for node in local_rcsd_nodes
            if node.mainnodeid == mainnodeid_norm
            or (
                selected_rcsd_roads
                and not selected_rcsd_buffer.is_empty
                and selected_rcsd_buffer.intersects(node.geometry)
            )
        }
        if primary_main_rc_node is None:
            inferred_rcsdnode_seed = _infer_primary_main_rc_node_from_local_context(
                local_rcsd_nodes=local_rcsd_nodes,
                selected_rcsd_roads=selected_rcsd_roads,
                representative_node=representative_node,
                road_branches=road_branches,
                main_branch_ids=main_branch_ids,
                local_roads=local_roads,
                kind_2=operational_kind_2,
            )
            if inferred_rcsdnode_seed["primary_main_rc_node"] is not None:
                primary_main_rc_node = inferred_rcsdnode_seed["primary_main_rc_node"]
                rcsdnode_seed_mode = inferred_rcsdnode_seed["seed_mode"]
        if primary_main_rc_node is not None:
            selected_rcsdnode_ids.add(primary_main_rc_node.node_id)
        if not selected_rcsdnode_ids:
            selected_rcsdnode_ids = {node.node_id for node in direct_target_rc_nodes}
        effective_target_rc_nodes: list[ParsedNode] = list(direct_target_rc_nodes)
        selected_rcsd_nodes = [node for node in local_rcsd_nodes if node.node_id in selected_rcsdnode_ids]
        if selected_rcsd_roads:
            _validate_drivezone_containment(drivezone_union=drivezone_union, features=selected_rcsd_roads, label="RCSDRoad")
        if selected_rcsd_nodes:
            _validate_drivezone_containment(drivezone_union=drivezone_union, features=selected_rcsd_nodes, label="RCSDNode")

        seed_support_geometries = [
            *[node.geometry.buffer(NODE_SEED_RADIUS_M) for node in group_nodes],
            *[node.geometry.buffer(RC_NODE_SEED_RADIUS_M) for node in exact_target_rc_nodes],
        ]
        if chain_context["sequential_ok"]:
            seed_support_geometries.extend(
                node.geometry.buffer(max(1.5, NODE_SEED_RADIUS_M * 0.6))
                for node in chain_context["related_seed_nodes"]
            )
        divstrip_constraint_geometry = divstrip_context["constraint_geometry"]
        event_anchor_geometry = divstrip_context["event_anchor_geometry"]
        localized_divstrip_reference_geometry = _localize_divstrip_reference_geometry(
            divstrip_constraint_geometry=divstrip_constraint_geometry,
            selected_roads=selected_roads,
            event_anchor_geometry=event_anchor_geometry,
            representative_node=representative_node,
            drivezone_union=drivezone_union,
        )
        event_axis_branch = _resolve_event_axis_branch(
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            kind_2=operational_kind_2,
        )
        event_axis_branch_id = None if event_axis_branch is None else event_axis_branch.branch_id
        event_axis_centerline = (
            None
            if event_axis_branch is None
            else _resolve_branch_centerline(
                branch=event_axis_branch,
                road_lookup={road.road_id: road for road in local_roads},
                    reference_point=event_anchor_geometry.centroid if event_anchor_geometry is not None and not event_anchor_geometry.is_empty else representative_node.geometry,
            )
        )
        provisional_event_origin = (
            representative_node.geometry
            if event_axis_centerline is None or event_axis_centerline.is_empty
            else nearest_points(event_axis_centerline, representative_node.geometry)[0]
        )
        initial_event_axis_unit_vector = _resolve_event_axis_unit_vector(
            axis_centerline=event_axis_centerline,
            origin_point=provisional_event_origin,
        )
        boundary_branch_a, boundary_branch_b = _pick_cross_section_boundary_branches(
            road_branches=road_branches,
            selected_branch_ids=set(selected_branch_ids),
            kind_2=operational_kind_2,
        )
        branch_a_centerline = (
            None
            if boundary_branch_a is None
            else _resolve_branch_centerline(
                branch=boundary_branch_a,
                road_lookup={road.road_id: road for road in local_roads},
                reference_point=provisional_event_origin,
            )
        )
        branch_b_centerline = (
            None
            if boundary_branch_b is None
            else _resolve_branch_centerline(
                branch=boundary_branch_b,
                road_lookup={road.road_id: road for road in local_roads},
                reference_point=provisional_event_origin,
            )
        )
        event_reference = _resolve_event_reference_point(
            representative_node=representative_node,
            event_anchor_geometry=event_anchor_geometry,
            divstrip_constraint_geometry=localized_divstrip_reference_geometry,
            all_divstrip_geometry=local_divstrip_union,
            axis_centerline=event_axis_centerline,
            axis_unit_vector=initial_event_axis_unit_vector,
            kind_2=operational_kind_2,
            drivezone_union=drivezone_union,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            cross_half_len_m=max(patch_size_m, DEFAULT_PATCH_SIZE_M),
            patch_size_m=patch_size_m,
        )
        event_origin_point = event_reference["origin_point"]
        event_origin_source = event_reference["event_origin_source"]
        event_axis_unit_vector = _resolve_event_axis_unit_vector(
            axis_centerline=event_axis_centerline,
            origin_point=event_origin_point,
        ) or initial_event_axis_unit_vector
        event_recenter = _rebalance_event_origin_for_rcsd_targets(
            origin_point=event_origin_point,
            axis_unit_vector=event_axis_unit_vector,
            target_rc_nodes=effective_target_rc_nodes,
        )
        if event_recenter[1]["applied"]:
            event_origin_point = event_recenter[0]
            event_origin_source = f"{event_origin_source}_recenter_{event_recenter[1]['direction']}"
            event_axis_unit_vector = _resolve_event_axis_unit_vector(
                axis_centerline=event_axis_centerline,
                origin_point=event_origin_point,
            ) or event_axis_unit_vector
        parallel_centerline = _resolve_parallel_centerline(
            local_roads=local_roads,
            selected_road_ids=set(selected_road_ids),
            axis_centerline=event_axis_centerline,
            axis_unit_vector=event_axis_unit_vector,
            reference_point=event_origin_point,
        )
        event_span_window = _resolve_event_span_window(
            origin_point=event_origin_point,
            axis_unit_vector=event_axis_unit_vector,
            selected_rcsd_nodes=selected_rcsd_nodes,
            event_anchor_geometry=event_anchor_geometry,
            selected_roads_geometry=unary_union(
                [road.geometry for road in selected_roads if road.geometry is not None and not road.geometry.is_empty]
            )
            if selected_roads
            else GeometryCollection(),
            selected_rcsd_roads_geometry=unary_union(
                [road.geometry for road in selected_rcsd_roads if road.geometry is not None and not road.geometry.is_empty]
            )
            if selected_rcsd_roads
            else GeometryCollection(),
        )
        if kind_resolution["complex_junction"] and chain_context["related_mainnodeids"]:
            chain_related_offsets: list[float] = []
            related_mainnodeids = set(chain_context["related_mainnodeids"])
            for candidate_node in local_nodes:
                candidate_mainnodeid = normalize_id(candidate_node.mainnodeid or candidate_node.node_id)
                if candidate_mainnodeid not in related_mainnodeids:
                    continue
                candidate_offset = _project_point_to_axis(
                    candidate_node.geometry,
                    origin_xy=(float(event_origin_point.x), float(event_origin_point.y)),
                    axis_unit_vector=event_axis_unit_vector,
                )
                if math.isfinite(float(candidate_offset)):
                    chain_related_offsets.append(float(candidate_offset))
            if chain_related_offsets:
                event_span_window["start_offset_m"] = float(
                    max(
                        -CHAIN_NEARBY_DISTANCE_M,
                        min(float(event_span_window["start_offset_m"]), min(chain_related_offsets) - EVENT_SPAN_MARGIN_M),
                    )
                )
                event_span_window["end_offset_m"] = float(
                    min(
                        CHAIN_NEARBY_DISTANCE_M,
                        max(float(event_span_window["end_offset_m"]), max(chain_related_offsets) + EVENT_SPAN_MARGIN_M),
                    )
                )
                event_span_window["candidate_offset_count"] = int(event_span_window["candidate_offset_count"]) + len(chain_related_offsets)
                event_span_window["expansion_source"] = "continuous_chain_context"
        axis_window_mask = _build_axis_window_mask(
            grid=grid,
            origin_point=event_origin_point,
            axis_unit_vector=event_axis_unit_vector,
            start_offset_m=event_span_window["start_offset_m"],
            end_offset_m=event_span_window["end_offset_m"],
        )
        axis_window_geometry = _build_axis_window_geometry(
            origin_point=event_origin_point,
            axis_unit_vector=event_axis_unit_vector,
            start_offset_m=event_span_window["start_offset_m"],
            end_offset_m=event_span_window["end_offset_m"],
            cross_half_len_m=max(patch_size_m, DEFAULT_PATCH_SIZE_M),
        )
        parallel_side_geometry = GeometryCollection()
        parallel_side_sample_count = 0
        if parallel_centerline is not None and not parallel_centerline.is_empty:
            parallel_side_geometry, parallel_side_sample_count = _build_cross_section_surface_geometry(
                drivezone_union=drivezone_union,
                origin_point=event_origin_point,
                axis_unit_vector=event_axis_unit_vector,
                start_offset_m=event_span_window["start_offset_m"],
                end_offset_m=event_span_window["end_offset_m"],
                cross_half_len_m=max(patch_size_m, DEFAULT_PATCH_SIZE_M),
                axis_centerline=event_axis_centerline,
                branch_a_centerline=branch_a_centerline,
                branch_b_centerline=branch_b_centerline,
                parallel_centerline=parallel_centerline,
                resolution_m=grid.resolution_m,
                support_geometry=None,
            )
            if parallel_side_geometry is not None and not parallel_side_geometry.is_empty:
                parallel_side_geometry = parallel_side_geometry.intersection(drivezone_union).buffer(0)
        parallel_side_mask = (
            None
            if parallel_side_geometry is None or parallel_side_geometry.is_empty
            else _rasterize_geometries(grid, [parallel_side_geometry]) & drivezone_mask
        )
        selected_event_road_support_union = unary_union(
            [
                road.geometry
                for road in selected_event_roads
                if road.geometry is not None and not road.geometry.is_empty
            ]
        )
        event_branch_support_geometries = [
            road.geometry
            for road in selected_event_roads
            if road.geometry is not None and not road.geometry.is_empty
        ]
        if selected_event_roads and not selected_event_road_support_union.is_empty:
            event_branch_support_geometries.extend(
                road.geometry
                for road in selected_rcsd_roads
                if road.geometry is not None
                and not road.geometry.is_empty
                and selected_event_road_support_union.buffer(
                    max(ROAD_BUFFER_M * 2.5, RC_ROAD_BUFFER_M * 2.0, 6.0),
                    cap_style=2,
                    join_style=2,
                ).intersects(road.geometry)
            )
        event_branch_support_union = unary_union(event_branch_support_geometries)
        event_side_drivezone_geometry = (
            GeometryCollection()
            if event_branch_support_union.is_empty
            else drivezone_union.intersection(
                event_branch_support_union.buffer(
                    max(ROAD_BUFFER_M * 2.8, RC_ROAD_BUFFER_M * 2.2, 7.5),
                    cap_style=2,
                    join_style=2,
                )
            ).intersection(axis_window_geometry).buffer(0)
        )
        if parallel_side_geometry is not None and not parallel_side_geometry.is_empty and event_side_drivezone_geometry is not None and not event_side_drivezone_geometry.is_empty:
            event_side_drivezone_geometry = event_side_drivezone_geometry.intersection(parallel_side_geometry).buffer(0)
        event_cross_section_support_geometry = unary_union(
            [
                road.geometry.buffer(max(ROAD_BUFFER_M * 1.5, RC_ROAD_BUFFER_M * 1.25, 2.25), cap_style=2, join_style=2)
                for road in [*selected_roads, *selected_rcsd_roads]
                if road.geometry is not None and not road.geometry.is_empty
            ]
        )
        cross_section_surface_geometry, cross_section_sample_count = _build_cross_section_surface_geometry(
            drivezone_union=drivezone_union,
            origin_point=event_origin_point,
            axis_unit_vector=event_axis_unit_vector,
            start_offset_m=event_span_window["start_offset_m"],
            end_offset_m=event_span_window["end_offset_m"],
            cross_half_len_m=max(patch_size_m, DEFAULT_PATCH_SIZE_M),
            axis_centerline=event_axis_centerline,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            parallel_centerline=parallel_centerline,
            resolution_m=grid.resolution_m,
            support_geometry=event_cross_section_support_geometry,
        )
        cross_section_surface_mask = (
            np.zeros_like(drivezone_mask, dtype=bool)
            if cross_section_surface_geometry.is_empty
            else _rasterize_geometries(grid, [cross_section_surface_geometry])
        )
        divstrip_event_window = _build_divstrip_event_window(
            divstrip_constraint_geometry=divstrip_constraint_geometry,
            selected_roads=selected_roads,
            selected_rcsd_roads=selected_rcsd_roads,
            seed_union=seed_union,
            event_anchor_geometry=event_anchor_geometry,
            drivezone_union=drivezone_union,
        )
        event_seed_geometries = [
            *[road.geometry.buffer(max(ROAD_BUFFER_M, 1.75), cap_style=2, join_style=2) for road in selected_roads],
            *[road.geometry.buffer(max(RC_ROAD_BUFFER_M, 1.75), cap_style=2, join_style=2) for road in selected_rcsd_roads],
            *[
                node.geometry.buffer(max(RC_NODE_SEED_RADIUS_M, 2.0), join_style=2)
                for node in selected_rcsd_nodes
            ],
        ]
        if event_anchor_geometry is not None and not event_anchor_geometry.is_empty:
            event_seed_geometries.append(
                event_anchor_geometry.buffer(max(EVENT_ANCHOR_BUFFER_M, 2.0), join_style=2)
            )
        event_seed_union = unary_union(
            [
                geometry
                for geometry in event_seed_geometries
                if geometry is not None and not geometry.is_empty
            ]
        )
        seed_mask = _rasterize_geometries(
            grid,
            event_seed_geometries or seed_support_geometries,
        )
        support_geometries = [
            *[road.geometry.buffer(ROAD_BUFFER_M, cap_style=2, join_style=2) for road in selected_roads],
            *[road.geometry.buffer(RC_ROAD_BUFFER_M, cap_style=2, join_style=2) for road in selected_rcsd_roads],
            *seed_support_geometries,
        ]
        support_mask = _rasterize_geometries(grid, support_geometries) & drivezone_mask
        if parallel_side_mask is not None:
            support_mask &= parallel_side_mask
        event_side_support_geometries = []
        if event_side_drivezone_geometry is not None and not event_side_drivezone_geometry.is_empty:
            event_side_support_geometries.append(event_side_drivezone_geometry)
        event_side_support_geometries.extend(
            road.geometry.buffer(max(ROAD_BUFFER_M * 1.8, RC_ROAD_BUFFER_M * 1.4, 2.5), cap_style=2, join_style=2)
            for road in [*selected_roads, *selected_rcsd_roads]
            if road.geometry is not None and not road.geometry.is_empty
        )
        event_side_support_mask = _rasterize_geometries(
            grid,
            event_side_support_geometries,
        ) & drivezone_mask
        if parallel_side_mask is not None:
            event_side_support_mask &= parallel_side_mask
        drivezone_component_mask = None
        if axis_window_mask.any():
            drivezone_component_mask = drivezone_mask & axis_window_mask
        elif divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty:
            drivezone_component_mask = drivezone_mask.copy()
        if drivezone_component_mask is not None:
            drivezone_component_mask = _binary_close(drivezone_component_mask, iterations=1)
        if drivezone_component_mask is not None and parallel_side_mask is not None:
            drivezone_component_mask &= parallel_side_mask
        if drivezone_component_mask is not None and not divstrip_event_window.is_empty:
            drivezone_component_mask |= (drivezone_mask & _rasterize_geometries(grid, [divstrip_event_window]))
            drivezone_component_mask = _binary_close(drivezone_component_mask, iterations=1)
            if parallel_side_mask is not None:
                drivezone_component_mask &= parallel_side_mask
        if drivezone_component_mask is not None and divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty:
            divstrip_mask = _rasterize_geometries(
                grid,
                [local_divstrip_union.buffer(DIVSTRIP_EXCLUSION_BUFFER_M, join_style=2)],
            )
            drivezone_component_mask &= ~divstrip_mask
        component_mask = (
            _extract_seed_component(drivezone_component_mask, seed_mask)
            if drivezone_component_mask is not None
            else np.zeros_like(drivezone_mask, dtype=bool)
        )
        if not component_mask.any():
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
                "Stage4 raster support could not form an event-connected component.",
            )
        clipping_mask = axis_window_mask.copy()
        if cross_section_surface_mask.any():
            clipping_mask &= (cross_section_surface_mask | event_side_support_mask | seed_mask)
        elif event_side_support_mask.any():
            clipping_mask &= (event_side_support_mask | seed_mask)
        clipped_component_mask = component_mask & clipping_mask
        if clipped_component_mask.any():
            reseeded_component_mask = _extract_seed_component(clipped_component_mask, seed_mask)
            component_mask = reseeded_component_mask if reseeded_component_mask.any() else clipped_component_mask

        polygon_geometry = _mask_to_geometry(component_mask, grid)
        if cross_section_surface_geometry is not None and not cross_section_surface_geometry.is_empty:
            polygon_geometry = unary_union(
                [
                    geometry
                    for geometry in [polygon_geometry, cross_section_surface_geometry, event_side_drivezone_geometry]
                    if geometry is not None and not geometry.is_empty
                ]
            ).buffer(0)
        polygon_geometry = _regularize_virtual_polygon_geometry(
            geometry=polygon_geometry,
            drivezone_union=drivezone_union,
            seed_geometry=(
                event_seed_union
                if event_seed_union is not None and not event_seed_union.is_empty
                else seed_union
            ),
        )
        if event_side_drivezone_geometry is not None and not event_side_drivezone_geometry.is_empty:
            polygon_geometry = polygon_geometry.union(event_side_drivezone_geometry).intersection(drivezone_union).buffer(0)
        selected_support_union = unary_union(
            [
                geometry
                for geometry in [*[road.geometry for road in selected_roads], *[road.geometry for road in selected_rcsd_roads]]
                if geometry is not None and not geometry.is_empty
            ]
        )
        if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty and drivezone_component_mask is None:
            event_guard_geometry = divstrip_context["event_anchor_geometry"]
            if event_guard_geometry is None or event_guard_geometry.is_empty:
                event_guard_geometry = selected_support_union if not selected_support_union.is_empty else seed_union
            clip_geometry = divstrip_constraint_geometry.buffer(DIVSTRIP_EXCLUSION_BUFFER_M, join_style=2).difference(
                event_guard_geometry.buffer(max(EVENT_ANCHOR_BUFFER_M, ROAD_BUFFER_M, RC_ROAD_BUFFER_M), join_style=2)
            )
            if not clip_geometry.is_empty:
                clipped_polygon = polygon_geometry.difference(clip_geometry).buffer(0)
                if not clipped_polygon.is_empty:
                    polygon_geometry = clipped_polygon
        if not divstrip_event_window.is_empty and drivezone_component_mask is None:
            clipped_polygon = polygon_geometry.intersection(divstrip_event_window).buffer(0)
            event_guard_geometry = divstrip_context["event_anchor_geometry"]
            if event_guard_geometry is None or event_guard_geometry.is_empty:
                event_guard_geometry = selected_support_union
            if (
                not clipped_polygon.is_empty
                and (
                    event_guard_geometry is None
                    or event_guard_geometry.is_empty
                    or clipped_polygon.intersects(event_guard_geometry.buffer(max(EVENT_ANCHOR_BUFFER_M, ROAD_BUFFER_M), join_style=2))
                )
            ):
                polygon_geometry = clipped_polygon
        if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty:
            polygon_without_divstrip = polygon_geometry.difference(
                local_divstrip_union.buffer(DIVSTRIP_EXCLUSION_BUFFER_M, join_style=2)
            ).buffer(0)
            if not polygon_without_divstrip.is_empty:
                polygon_geometry = polygon_without_divstrip
        if axis_window_geometry is not None and not axis_window_geometry.is_empty:
            clipped_polygon = polygon_geometry.intersection(axis_window_geometry).buffer(0)
            if not clipped_polygon.is_empty:
                polygon_geometry = clipped_polygon
        elif cross_section_surface_geometry is not None and not cross_section_surface_geometry.is_empty:
            clipped_polygon = polygon_geometry.intersection(cross_section_surface_geometry).buffer(0)
            if not clipped_polygon.is_empty:
                polygon_geometry = clipped_polygon
        if parallel_side_geometry is not None and not parallel_side_geometry.is_empty:
            clipped_polygon = polygon_geometry.intersection(parallel_side_geometry).buffer(0)
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
            kind_2=operational_kind_2,
            drivezone_union=drivezone_union,
        )
        polygon_geometry = primary_rcsdnode_tolerance["extended_polygon_geometry"]
        effective_target_rc_nodes = _resolve_effective_target_rc_nodes(
            direct_target_rc_nodes=direct_target_rc_nodes,
            primary_main_rc_node=primary_main_rc_node,
            primary_rcsdnode_tolerance=primary_rcsdnode_tolerance,
        )
        coverage_missing_ids = _cover_check(polygon_geometry, exact_target_rc_nodes)
        coverage_missing_ids = sorted(set(coverage_missing_ids))
        review_reasons: list[str] = []
        if multibranch_context["ambiguous"]:
            review_reasons.append(STATUS_MULTIBRANCH_EVENT_AMBIGUOUS)
        if divstrip_context["ambiguous"]:
            review_reasons.append(STATUS_DIVSTRIP_COMPONENT_AMBIGUOUS)
        if chain_context["is_in_continuous_chain"] and chain_context["sequential_ok"] and not kind_resolution["complex_junction"]:
            review_reasons.append(STATUS_CONTINUOUS_CHAIN_REVIEW)
        if kind_resolution["ambiguous"]:
            review_reasons.append(STATUS_COMPLEX_KIND_AMBIGUOUS)
        acceptance_class = "accepted" if not review_reasons else "review_required"
        acceptance_reason = "stable" if not review_reasons else review_reasons[0]
        success = acceptance_class == "accepted"

        counts["target_node_count"] = len(group_nodes)
        counts["target_rcsdnode_count"] = len(effective_target_rc_nodes)
        counts["selected_branch_count"] = len(selected_branch_ids)
        counts["selected_road_count"] = len(selected_roads)
        counts["selected_rcsdroad_count"] = len(selected_rcsd_roads)
        counts["selected_rcsdnode_count"] = len(selected_rcsdnode_ids)

        polygon_feature = {
            "properties": {
                "mainnodeid": mainnodeid_norm,
                "kind": representative_source_kind,
                "source_kind": representative_source_kind,
                "source_kind_2": representative_source_kind_2,
                "kind_2": operational_kind_2,
                "grade_2": representative_grade_2,
                "status": acceptance_reason,
                "acceptance_class": acceptance_class,
                "acceptance_reason": acceptance_reason,
                "target_node_count": len(group_nodes),
                "target_rcsdnode_count": len(effective_target_rc_nodes),
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
                "rcsdroad_selection_mode": rcsdroad_selection_mode,
                "complex_junction": int(kind_resolution["complex_junction"]),
                "kind_resolution_mode": kind_resolution["kind_resolution_mode"],
                "kind_resolution_ambiguous": int(kind_resolution["ambiguous"]),
                "multibranch_enabled": int(multibranch_context["enabled"]),
                "multibranch_n": int(multibranch_context["n"]),
                "event_candidate_count": int(multibranch_context["event_candidate_count"]),
                "selected_event_index": multibranch_context["selected_event_index"],
                "event_axis_branch_id": event_axis_branch_id,
                "event_origin_source": event_origin_source,
                "event_recenter_applied": int(event_recenter[1]["applied"]),
                "event_recenter_shift_m": event_recenter[1]["shift_m"],
                "event_recenter_direction": event_recenter[1]["direction"],
                "event_position_source": event_reference["position_source"],
                "event_split_pick_source": event_reference["split_pick_source"],
                "event_chosen_s_m": event_reference["chosen_s_m"],
                "event_tip_s_m": event_reference["tip_s_m"],
                "event_first_divstrip_hit_s_m": event_reference["first_divstrip_hit_dist_m"],
                "event_drivezone_split_s_m": event_reference["s_drivezone_split_m"],
                "event_span_start_m": event_span_window["start_offset_m"],
                "event_span_end_m": event_span_window["end_offset_m"],
                "cross_section_sample_count": cross_section_sample_count,
                "branches_used_count": len(selected_branch_ids),
                "reverse_tip_attempted": int(reverse_tip_attempted),
                "reverse_tip_used": int(reverse_tip_used),
                "is_in_continuous_chain": int(chain_context["is_in_continuous_chain"]),
                "chain_node_count": int(chain_context["chain_node_count"]),
                "rcsdnode_seed_mode": rcsdnode_seed_mode,
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
            kind_2=operational_kind_2,
            grade_2=representative_grade_2,
            target_node_ids=[node.node_id for node in group_nodes],
            linked_node_ids=[node.node_id for node in group_nodes],
            selected_branch_ids=selected_branch_ids,
            selected_road_ids=selected_road_ids,
            coverage_missing_ids=coverage_missing_ids,
        )
        node_link_doc.update(
            {
                "source_kind": representative_source_kind,
                "source_kind_2": representative_source_kind_2,
                "complex_junction": kind_resolution["complex_junction"],
                "kind_resolution_mode": kind_resolution["kind_resolution_mode"],
                "kind_resolution_ambiguous": kind_resolution["ambiguous"],
                "multibranch_enabled": multibranch_context["enabled"],
                "selected_event_branch_ids": selected_event_branch_ids,
                "event_axis_branch_id": event_axis_branch_id,
                "event_origin_source": event_origin_source,
                "event_recenter_applied": int(event_recenter[1]["applied"]),
                "event_recenter_shift_m": event_recenter[1]["shift_m"],
                "event_recenter_direction": event_recenter[1]["direction"],
                "event_position_source": event_reference["position_source"],
                "event_split_pick_source": event_reference["split_pick_source"],
                "event_chosen_s_m": event_reference["chosen_s_m"],
                "event_tip_s_m": event_reference["tip_s_m"],
                "event_first_divstrip_hit_s_m": event_reference["first_divstrip_hit_dist_m"],
                "event_drivezone_split_s_m": event_reference["s_drivezone_split_m"],
                "event_span_start_m": event_span_window["start_offset_m"],
                "event_span_end_m": event_span_window["end_offset_m"],
                "cross_section_sample_count": cross_section_sample_count,
                "branches_used_count": len(selected_branch_ids),
                "position_source_final": position_source_final,
                "related_mainnodeids": chain_context["related_mainnodeids"],
                "trunk_branch_id": primary_rcsdnode_tolerance["trunk_branch_id"],
                "rcsdroad_selection_mode": rcsdroad_selection_mode,
            }
        )
        rcsdnode_link_doc = _make_link_doc(
            mainnodeid=mainnodeid_norm,
            kind_2=operational_kind_2,
            grade_2=representative_grade_2,
            target_node_ids=[node.node_id for node in effective_target_rc_nodes],
            linked_node_ids=sorted(selected_rcsdnode_ids),
            selected_branch_ids=selected_branch_ids,
            selected_road_ids=sorted(selected_rcsdroad_ids),
            coverage_missing_ids=coverage_missing_ids,
        )
        rcsdnode_link_doc.update(
            {
                "source_kind": representative_source_kind,
                "source_kind_2": representative_source_kind_2,
                "complex_junction": kind_resolution["complex_junction"],
                "kind_resolution_mode": kind_resolution["kind_resolution_mode"],
                "kind_resolution_ambiguous": kind_resolution["ambiguous"],
                "multibranch_enabled": multibranch_context["enabled"],
                "selected_event_branch_ids": selected_event_branch_ids,
                "event_axis_branch_id": event_axis_branch_id,
                "event_origin_source": event_origin_source,
                "event_recenter_applied": int(event_recenter[1]["applied"]),
                "event_recenter_shift_m": event_recenter[1]["shift_m"],
                "event_recenter_direction": event_recenter[1]["direction"],
                "event_position_source": event_reference["position_source"],
                "event_split_pick_source": event_reference["split_pick_source"],
                "event_chosen_s_m": event_reference["chosen_s_m"],
                "event_tip_s_m": event_reference["tip_s_m"],
                "event_first_divstrip_hit_s_m": event_reference["first_divstrip_hit_dist_m"],
                "event_drivezone_split_s_m": event_reference["s_drivezone_split_m"],
                "event_span_start_m": event_span_window["start_offset_m"],
                "event_span_end_m": event_span_window["end_offset_m"],
                "cross_section_sample_count": cross_section_sample_count,
                "branches_used_count": len(selected_branch_ids),
                "position_source_final": position_source_final,
                "related_mainnodeids": chain_context["related_mainnodeids"],
                "trunk_branch_id": primary_rcsdnode_tolerance["trunk_branch_id"],
                "rcsdnode_seed_mode": rcsdnode_seed_mode,
                "rcsdroad_selection_mode": rcsdroad_selection_mode,
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
                local_divstrip_geometries=[feature.geometry for feature in local_divstrip_features],
                selected_divstrip_geometry=divstrip_context["constraint_geometry"],
            )
            if rendered_map_path is not None:
                rendered_map_path.parent.mkdir(parents=True, exist_ok=True)
                if rendered_map_path != debug_render_path:
                    shutil.copy2(debug_render_path, rendered_map_path)

        status_doc = {
            "run_id": resolved_run_id,
            "success": success,
            "flow_success": True,
            "acceptance_class": acceptance_class,
            "acceptance_reason": acceptance_reason,
            "mainnodeid": mainnodeid_norm,
            "kind": representative_source_kind,
            "source_kind": representative_source_kind,
            "source_kind_2": representative_source_kind_2,
            "kind_2": operational_kind_2,
            "grade_2": representative_grade_2,
            "counts": counts,
            "coverage_missing_ids": coverage_missing_ids,
            "review_reasons": review_reasons,
            "rcsdnode_seed_mode": rcsdnode_seed_mode,
            "rcsdroad_selection_mode": rcsdroad_selection_mode,
            "kind_resolution": {
                "complex_junction": kind_resolution["complex_junction"],
                "kind_resolution_mode": kind_resolution["kind_resolution_mode"],
                "kind_resolution_ambiguous": kind_resolution["ambiguous"],
                "merge_score": kind_resolution["merge_score"],
                "diverge_score": kind_resolution["diverge_score"],
                "merge_hits": kind_resolution["merge_hits"],
                "diverge_hits": kind_resolution["diverge_hits"],
            },
            "multibranch": {
                "multibranch_enabled": multibranch_context["enabled"],
                "multibranch_n": multibranch_context["n"],
                "event_candidate_count": multibranch_context["event_candidate_count"],
                "selected_event_index": multibranch_context["selected_event_index"],
                "selected_event_branch_ids": selected_event_branch_ids,
                "branches_used_count": len(selected_branch_ids),
                "event_axis_branch_id": event_axis_branch_id,
            "event_origin_source": event_origin_source,
            "event_recenter_applied": bool(event_recenter[1]["applied"]),
            "event_recenter_shift_m": event_recenter[1]["shift_m"],
            "event_recenter_direction": event_recenter[1]["direction"],
            "event_position_source": event_reference["position_source"],
            "event_split_pick_source": event_reference["split_pick_source"],
            "event_chosen_s_m": event_reference["chosen_s_m"],
                "event_tip_s_m": event_reference["tip_s_m"],
                "event_first_divstrip_hit_s_m": event_reference["first_divstrip_hit_dist_m"],
                "event_drivezone_split_s_m": event_reference["s_drivezone_split_m"],
                "event_span_start_m": event_span_window["start_offset_m"],
                "event_span_end_m": event_span_window["end_offset_m"],
            },
            "reverse_tip": {
                "reverse_tip_attempted": reverse_tip_attempted,
                "reverse_tip_used": reverse_tip_used,
                "reverse_trigger": reverse_trigger,
                "position_source_forward": position_source_forward,
                "position_source_reverse": position_source_reverse,
                "position_source_final": position_source_final,
            },
            "event_shape": {
                "event_axis_branch_id": event_axis_branch_id,
                "event_origin_source": event_origin_source,
                "event_position_source": event_reference["position_source"],
                "event_split_pick_source": event_reference["split_pick_source"],
                "event_chosen_s_m": event_reference["chosen_s_m"],
                "event_tip_s_m": event_reference["tip_s_m"],
                "event_first_divstrip_hit_s_m": event_reference["first_divstrip_hit_dist_m"],
                "event_drivezone_split_s_m": event_reference["s_drivezone_split_m"],
                "event_span_start_m": event_span_window["start_offset_m"],
                "event_span_end_m": event_span_window["end_offset_m"],
                "candidate_offset_count": event_span_window["candidate_offset_count"],
                "expansion_source": event_span_window["expansion_source"],
                "cross_section_sample_count": cross_section_sample_count,
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
                "rcsdroad_selection_mode": rcsdroad_selection_mode,
                "evidence_source": divstrip_context["evidence_source"],
            },
            "rcsdnode_tolerance": {
                "rcsdnode_seed_mode": rcsdnode_seed_mode,
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
                "rendered_map": str(rendered_map_path) if rendered_map_path is not None and rendered_map_path.is_file() else None,
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
                "rcsdroad_selection_mode": rcsdroad_selection_mode,
                "source_kind": representative_source_kind,
                "source_kind_2": representative_source_kind_2,
                "rcsdnode_seed_mode": rcsdnode_seed_mode,
                "complex_junction": kind_resolution["complex_junction"],
                "kind_resolution_mode": kind_resolution["kind_resolution_mode"],
                "kind_resolution_ambiguous": kind_resolution["ambiguous"],
                "merge_score": kind_resolution["merge_score"],
                "diverge_score": kind_resolution["diverge_score"],
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
                "event_axis_branch_id": event_axis_branch_id,
                "event_origin_source": event_origin_source,
                "event_span_start_m": event_span_window["start_offset_m"],
                "event_span_end_m": event_span_window["end_offset_m"],
                "cross_section_sample_count": cross_section_sample_count,
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
            rendered_map_path=rendered_map_path if rendered_map_path is not None and rendered_map_path.is_file() else None,
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
            "kind": representative_source_kind if "representative_source_kind" in locals() else None,
            "source_kind": representative_source_kind if "representative_source_kind" in locals() else None,
            "source_kind_2": representative_source_kind_2 if "representative_source_kind_2" in locals() else None,
            "status": exc.reason,
            "detail": exc.detail,
            "counts": counts,
            "output_files": {
                "stage4_virtual_polygon": str(virtual_polygon_path),
                "stage4_node_link": str(node_link_json_path),
                "stage4_rcsdnode_link": str(rcsdnode_link_json_path),
                "stage4_audit": str(audit_json_path),
                "stage4_debug": str(debug_dir) if debug_dir is not None else None,
                "rendered_map": str(rendered_map_path) if rendered_map_path is not None and rendered_map_path.is_file() else None,
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
            rendered_map_path=rendered_map_path if rendered_map_path is not None and rendered_map_path.is_file() else None,
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
        debug_render_root=getattr(args, "debug_render_root", None),
    )
    return 0 if artifacts.success else 2
