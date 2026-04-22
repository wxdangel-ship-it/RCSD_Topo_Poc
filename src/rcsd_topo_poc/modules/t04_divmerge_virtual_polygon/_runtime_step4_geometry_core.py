from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations, permutations
from typing import Any, Optional, Sequence

import numpy as np
from shapely.geometry import GeometryCollection, LineString, Point
from shapely.ops import linemerge, nearest_points, substring, unary_union

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import LoadedFeature, T02RunError, normalize_id
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import (
    BRANCH_MATCH_TOLERANCE_DEG,
    DEFAULT_PATCH_SIZE_M,
    DEFAULT_RESOLUTION_M,
    MAIN_AXIS_ANGLE_TOLERANCE_DEG,
    NODE_SEED_RADIUS_M,
    RC_NODE_SEED_RADIUS_M,
    RC_ROAD_BUFFER_M,
    ROAD_BUFFER_M,
    ParsedNode,
    ParsedRoad,
    _binary_close,
    _branch_candidate_from_center_proximity,
    _branch_candidate_from_road,
    _build_grid,
    _cluster_branch_candidates,
    _extract_seed_component,
    _mask_to_geometry,
    _rasterize_geometries,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_polygon_cleanup import (
    _regularize_virtual_polygon_geometry,
)


class Stage4RunError(T02RunError):
    pass


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
DIVSTRIP_COMPLEX_PAIR_DISTANCE_M = 180.0
DIVSTRIP_COMPLEX_PAIR_SEED_DISTANCE_M = 120.0
DIVSTRIP_KIND_POSITION_MARGIN_M = 2.0
EVENT_ANCHOR_BUFFER_M = 4.0
EVENT_SPAN_DEFAULT_M = 10.0
EVENT_SPAN_MAX_M = 120.0
EVENT_SPAN_MARGIN_M = 1.5
EVENT_SPAN_LOCAL_CONTEXT_PAD_M = 25.0
EVENT_COMPONENT_SURFACE_SPAN_CAP_M = 25.0
EVENT_COMPONENT_SIDE_CLIP_BUFFER_M = 10.0
EVENT_SIMPLE_COMPONENT_EXTRA_SPAN_PAD_M = 8.0
EVENT_COMPONENT_BRANCH_LOCAL_DISTANCE_M = 30.0
EVENT_COMPLEX_MEMBER_SPAN_PAD_M = 12.0
EVENT_SEMANTIC_BOUNDARY_PAD_M = 12.0
EVENT_SEMANTIC_BOUNDARY_AXIS_BUFFER_M = 14.0
EVENT_SEMANTIC_BOUNDARY_ROAD_BUFFER_M = 18.0
EVENT_NON_COMPLEX_EXTRA_SPAN_CAP_M = 18.0
EVENT_COMPLEX_EXTRA_SPAN_CAP_M = 16.0
EVENT_COMPLEX_LOCAL_SUPPORT_ROAD_DISTANCE_M = 6.0
EVENT_COMPLEX_SUPPORT_BRANCH_PROXIMITY_M = 18.0
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
CHAIN_CONTINUATION_MAX_TURN_DEG = 55.0
CHAIN_CONTINUATION_MIN_MARGIN_DEG = 8.0
EVENT_RCSD_RECENTER_SHIFT_MAX_M = 20.0
DEBUG_RENDER_PATCH_SIZE_M = 420.0
SIMPLE_FULL_FILL_PARALLEL_CLIP_AREA_RATIO_MAX = 0.25
EXPECTED_CHAIN_CONTOUR_PARALLEL_BUFFER_M = 2.0
EXPECTED_CHAIN_CONTOUR_SMOOTH_BUFFER_M = 0.9
EXPECTED_CHAIN_CONTOUR_AREA_KEEP_MIN_RATIO = 0.95
EXPECTED_CHAIN_CONTOUR_AREA_GAIN_MAX_RATIO = 1.35
SELECTED_SUPPORT_CORRIDOR_PARALLEL_RATIO_MIN = 0.30
EVENT_CROSS_HALF_LEN_FALLBACK_M = 60.0
EVENT_CROSS_HALF_LEN_MIN_M = 30.0
EVENT_CROSS_HALF_LEN_MAX_M = 130.0
EVENT_CROSS_HALF_LEN_AXIS_SAMPLE_WINDOW_M = 50.0
EVENT_CROSS_HALF_LEN_SIDE_MARGIN_M = 10.0
EVENT_CROSS_HALF_LEN_PATCH_SCALE_RATIO = 0.5
FULL_FILL_SPAN_HALF_MIN_M = 25.0
PARALLEL_ROAD_ANGLE_TOLERANCE_DEG = 18.0
PARALLEL_ROAD_MIN_OFFSET_M = 4.0
PARALLEL_ROAD_MAX_OFFSET_M = 80.0
PARALLEL_SIDE_SIGN_EPS_M = 1.5
PARALLEL_CENTERLINE_AXIS_WINDOW_M = 55.0
PARALLEL_CENTERLINE_REFERENCE_DISTANCE_M = 35.0
PARALLEL_SIDE_SIGN_MIN_WEIGHT = 0.05
PARALLEL_SIDE_SIGN_BALANCE_RATIO = 0.1
PARALLEL_SIDE_FALLBACK_REFERENCE_DISTANCE_M = 120.0
PARALLEL_SIDE_FALLBACK_BALANCE_RATIO = 0.03
CHAIN_CONTEXT_EVENT_SPAN_M = 200.0
MULTIBRANCH_AMBIGUITY_SCORE_MARGIN = 5.0
MULTIBRANCH_EVENT_MAX_LOBES = 2
MULTIBRANCH_LOCAL_CONTEXT_WINDOW_M = 36.0
MULTIBRANCH_LOCAL_SPAN_MAX_M = 28.0
MULTIBRANCH_SIDE_CLIP_BUFFER_M = 8.0
RCSDNODE_TRUNK_WINDOW_M = 20.0
RCSDNODE_TRUNK_LATERAL_TOLERANCE_M = 6.0
CHAIN_NEARBY_DISTANCE_M = CHAIN_CONTEXT_EVENT_SPAN_M
CHAIN_SEQUENCE_DISTANCE_M = CHAIN_CONTEXT_EVENT_SPAN_M

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


def _resolve_rcsdnode_trunk_branch(
    *,
    road_branches,
    main_branch_ids: set[str],
    kind_2: int,
    preferred_trunk_branch_id: str | None = None,
):
    trunk_branch, tolerance_rule = _resolve_trunk_branch(
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        kind_2=kind_2,
    )
    if trunk_branch is not None:
        return trunk_branch, tolerance_rule
    if preferred_trunk_branch_id:
        preferred_branch = next(
            (
                branch
                for branch in road_branches
                if branch.branch_id == preferred_trunk_branch_id and branch.branch_id in main_branch_ids
            ),
            None,
        )
        if preferred_branch is not None:
            return preferred_branch, tolerance_rule
    main_branches = [branch for branch in road_branches if branch.branch_id in main_branch_ids]
    if len(main_branches) == 1:
        return main_branches[0], tolerance_rule
    return None, tolerance_rule


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
    corridor_buffer_m = max(float(EVENT_ANCHOR_BUFFER_M), float(EVENT_SEMANTIC_BOUNDARY_ROAD_BUFFER_M) * 0.5)
    lhs_corridor = lhs_geometry.buffer(corridor_buffer_m, cap_style=2, join_style=2)
    rhs_corridor = rhs_geometry.buffer(corridor_buffer_m, cap_style=2, join_style=2)
    intersection_geometry = lhs_corridor.intersection(rhs_corridor).buffer(0)
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
    all_branch_ids = {branch.branch_id for branch in road_branches}
    explicit_event_branch_ids = set(event_branch_ids or ()) & all_branch_ids
    if explicit_event_branch_ids:
        candidate_branch_ids = set(explicit_event_branch_ids)
    else:
        candidate_branch_ids = {
            branch.branch_id
            for branch in road_branches
            if branch.branch_id not in main_branch_ids
        }
    if not candidate_branch_ids and explicit_event_branch_ids:
        candidate_branch_ids = set(explicit_event_branch_ids)
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

    if explicit_event_branch_ids:
        main_union_branch_ids = all_branch_ids - candidate_branch_ids
        if not main_union_branch_ids:
            main_union_branch_ids = set(main_branch_ids) - candidate_branch_ids
    else:
        main_union_branch_ids = set(main_branch_ids)

    main_union = _build_branch_union_geometry(
        local_roads=local_roads,
        branch_ids=main_union_branch_ids,
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
    allow_compound_pair_merge: bool = False,
    excluded_component_geometries: list[Any] | None = None,
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
    road_lookup = {road.road_id: road for road in local_roads}
    reference_point = (
        event_anchor_geometry.representative_point()
        if event_anchor_geometry is not None and not event_anchor_geometry.is_empty
        else seed_union.representative_point()
    )
    component_reference_segment = None
    reference_branch_candidates: list[tuple[float, int, Any]] = []
    for branch in road_branches:
        centerline = _resolve_branch_centerline(
            branch=branch,
            road_lookup=road_lookup,
            reference_point=reference_point,
        )
        if centerline is None or centerline.is_empty:
            continue
        reference_branch_candidates.append(
            (
                float(centerline.distance(reference_point)),
                1 if branch.branch_id in candidate_branch_ids else 0,
                branch,
            )
        )
    reference_branch_candidates.sort(key=lambda item: (float(item[0]), -int(item[1]), -_selected_branch_score(item[2])))
    reference_branches = [item[2] for item in reference_branch_candidates[:2]]
    reference_branch_a = reference_branches[0] if len(reference_branches) >= 1 else None
    reference_branch_b = reference_branches[1] if len(reference_branches) >= 2 else None
    if reference_branch_a is not None and reference_branch_b is not None:
        reference_centerline_a = _resolve_branch_centerline(
            branch=reference_branch_a,
            road_lookup=road_lookup,
            reference_point=reference_point,
        )
        reference_centerline_b = _resolve_branch_centerline(
            branch=reference_branch_b,
            road_lookup=road_lookup,
            reference_point=reference_point,
        )
        if (
            reference_centerline_a is not None
            and not reference_centerline_a.is_empty
            and reference_centerline_b is not None
            and not reference_centerline_b.is_empty
        ):
            point_a = nearest_points(reference_centerline_a, reference_point)[0]
            point_b = nearest_points(reference_centerline_b, reference_point)[0]
            if float(point_a.distance(point_b)) > 1e-6:
                component_reference_segment = LineString(
                    [
                        (float(point_a.x), float(point_a.y)),
                        (float(point_b.x), float(point_b.y)),
                    ]
                )

    valid_excluded_geometries = [
        geometry
        for geometry in (excluded_component_geometries or [])
        if geometry is not None and not geometry.is_empty
    ]

    def _component_is_excluded_by_prior_unit(component_geometry) -> bool:
        if not valid_excluded_geometries:
            return False
        component_area = float(getattr(component_geometry, "area", 0.0) or 0.0)
        for excluded_geometry in valid_excluded_geometries:
            try:
                overlap = component_geometry.intersection(excluded_geometry)
            except Exception:
                continue
            overlap_area = float(getattr(overlap, "area", 0.0) or 0.0)
            if overlap_area <= 1e-6:
                if float(component_geometry.distance(excluded_geometry)) > 0.5:
                    continue
            excluded_area = float(getattr(excluded_geometry, "area", 0.0) or 0.0)
            smaller_area = min(component_area, excluded_area)
            if smaller_area <= 1e-6:
                if float(component_geometry.distance(excluded_geometry)) <= 0.5:
                    return True
                continue
            overlap_ratio = overlap_area / smaller_area if smaller_area > 1e-6 else 0.0
            if overlap_area >= 4.0 or overlap_ratio >= 0.15:
                return True
            if (
                float(component_geometry.distance(excluded_geometry)) <= 0.25
                and overlap_ratio >= 0.05
            ):
                return True
        return False

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
        related_to_branch_middle, distance_to_branch_middle, branch_middle_overlap = _component_reference_overlap_metrics(
            component_geometry=component_geometry,
            reference_geometry=component_reference_segment,
            reference_buffer_m=max(float(DIVSTRIP_BRANCH_BUFFER_M), 2.0),
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
                    "distance_to_branch_middle": distance_to_branch_middle,
                    "related_to_branch_middle": related_to_branch_middle,
                    "branch_middle_overlap": branch_middle_overlap,
                    "component_area": float(getattr(component_geometry, "area", 0.0) or 0.0),
                    "is_excluded_by_prior_unit": _component_is_excluded_by_prior_unit(component_geometry),
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
    if allow_compound_pair_merge:
        branch_middle_components = [
            component
            for component in nearby_components
            if bool(component["related_to_branch_middle"]) or float(component["branch_middle_overlap"]) > 1e-6
        ]
        if branch_middle_components:
            candidate_components = branch_middle_components
        else:
            candidate_components = matched_components or road_nearby_components or nearby_components
        if valid_excluded_geometries and candidate_components and all(
            bool(component.get("is_excluded_by_prior_unit"))
            for component in candidate_components
        ):
            seen_candidate_ids: set[str] = {
                str(component["component_id"]) for component in candidate_components
            }
            broader_pool: list[dict[str, Any]] = []
            for component in [*matched_components, *road_nearby_components, *nearby_components]:
                cid = str(component["component_id"])
                if cid in seen_candidate_ids:
                    continue
                seen_candidate_ids.add(cid)
                broader_pool.append(component)
            broader_non_excluded = [
                component
                for component in broader_pool
                if not bool(component.get("is_excluded_by_prior_unit"))
            ]
            if broader_non_excluded:
                candidate_components = broader_non_excluded
    else:
        candidate_components = []
        seen_candidate_component_ids: set[str] = set()
        for component in [*matched_components, *anchor_preferred_components, *road_nearby_components, *nearby_components]:
            component_id = str(component["component_id"])
            if component_id in seen_candidate_component_ids:
                continue
            seen_candidate_component_ids.add(component_id)
            candidate_components.append(component)
    if valid_excluded_geometries and candidate_components:
        non_excluded_candidates = [
            component
            for component in candidate_components
            if not bool(component.get("is_excluded_by_prior_unit"))
        ]
        if non_excluded_candidates:
            candidate_components = non_excluded_candidates
    if allow_compound_pair_merge:
        has_branch_middle_signal = any(
            bool(component["related_to_branch_middle"]) or float(component["branch_middle_overlap"]) > 1e-6
            for component in candidate_components
        )
        large_component_area_threshold = max(
            80.0,
            0.35 * max(float(component["component_area"]) for component in candidate_components),
        )
        if has_branch_middle_signal:
            candidate_components.sort(
                key=lambda component: (
                    0 if component["related_to_branch_middle"] else 1,
                    float(component["distance_to_branch_middle"]),
                    -float(component["branch_middle_overlap"]),
                    0 if float(component["component_area"]) >= large_component_area_threshold else 1,
                    -float(component["component_area"]),
                    float(component["distance_to_event_anchor"]),
                    -len(component["matched_branch_ids"]),
                    -len(component["matched_all_branch_ids"]),
                    float(component["distance_to_roads"]),
                    float(component["distance_to_seed"]),
                ),
            )
        else:
            candidate_components.sort(
                key=lambda component: (
                    -len(component["matched_branch_ids"]),
                    -len(component["matched_all_branch_ids"]),
                    0 if float(component["component_area"]) >= large_component_area_threshold else 1,
                    -float(component["component_area"]),
                    float(component["distance_to_event_anchor"]),
                    float(component["distance_to_seed"]),
                    float(component["distance_to_roads"]),
                ),
            )
    else:
        large_component_area_threshold = max(
            80.0,
            0.35 * max(float(component["component_area"]) for component in candidate_components),
        )
        candidate_components.sort(
            key=lambda component: (
                0 if component["related_to_branch_middle"] else 1,
                float(component["distance_to_branch_middle"]),
                -float(component["branch_middle_overlap"]),
                -len(component["matched_branch_ids"]),
                -len(component["matched_all_branch_ids"]),
                0 if float(component["component_area"]) >= large_component_area_threshold else 1,
                -float(component["component_area"]),
                float(component["distance_to_event_anchor"]),
                float(component["distance_to_seed"]),
                float(component["distance_to_roads"]),
            ),
        )

    def _component_branch_ids(component: dict[str, Any]) -> set[str]:
        return set(component["matched_branch_ids"] or component["matched_all_branch_ids"])

    def _components_share_corridor(
        base_component: dict[str, Any],
        candidate_component: dict[str, Any],
    ) -> bool:
        base_branch_ids = _component_branch_ids(base_component)
        candidate_branch_ids = _component_branch_ids(candidate_component)
        base_corridor_geometry = unary_union(
            [
                geometry
                for branch_id, geometry in all_branch_geometry_lookup.items()
                if branch_id in base_branch_ids and geometry is not None and not geometry.is_empty
            ]
        )
        same_branch_corridor = bool(
            base_branch_ids
            and not base_corridor_geometry.is_empty
            and base_corridor_geometry.buffer(
                max(DIVSTRIP_REFERENCE_ROAD_BUFFER_M * 0.6, DIVSTRIP_BRANCH_BUFFER_M * 2.5),
                cap_style=2,
                join_style=2,
            ).intersects(candidate_component["geometry"])
            and float(candidate_component["distance_to_seed"]) <= float(DIVSTRIP_SEED_FALLBACK_DISTANCE_M)
        )
        same_corridor = (
            (
                base_branch_ids
                and candidate_branch_ids
                and bool(base_branch_ids & candidate_branch_ids)
            )
            or same_branch_corridor
            or (
                not base_branch_ids
                and float(candidate_component["distance_to_roads"]) <= DIVSTRIP_CONTEXT_ROAD_DISTANCE_M
            )
        )
        if not same_corridor:
            return False
        return float(candidate_component["geometry"].distance(base_component["geometry"])) <= float(
            DIVSTRIP_REFERENCE_ROAD_BUFFER_M + 6.0
        )

    compound_pair_components: list[dict[str, Any]] = []
    if allow_compound_pair_merge:
        best_compound_pair: tuple[dict[str, Any], dict[str, Any]] | None = None
        best_compound_pair_key: tuple[int, float, float, float] | None = None
        for first_component, second_component in combinations(candidate_components, 2):
            first_branch_ids = _component_branch_ids(first_component)
            second_branch_ids = _component_branch_ids(second_component)
            if not first_branch_ids or not second_branch_ids:
                continue
            if first_branch_ids & second_branch_ids:
                continue
            geometry_distance = float(first_component["geometry"].distance(second_component["geometry"]))
            if geometry_distance > float(DIVSTRIP_COMPLEX_PAIR_DISTANCE_M):
                continue
            if (
                float(first_component["distance_to_seed"]) > float(DIVSTRIP_COMPLEX_PAIR_SEED_DISTANCE_M)
                or float(second_component["distance_to_seed"]) > float(DIVSTRIP_COMPLEX_PAIR_SEED_DISTANCE_M)
            ):
                continue
            if (
                float(first_component["distance_to_roads"]) > float(DIVSTRIP_CONTEXT_ROAD_DISTANCE_M)
                or float(second_component["distance_to_roads"]) > float(DIVSTRIP_CONTEXT_ROAD_DISTANCE_M)
            ):
                continue
            pair_key = (
                len(first_branch_ids) + len(second_branch_ids),
                -float(first_component["distance_to_event_anchor"] + second_component["distance_to_event_anchor"]),
                -float(first_component["distance_to_roads"] + second_component["distance_to_roads"]),
                -geometry_distance,
            )
            if best_compound_pair_key is None or pair_key > best_compound_pair_key:
                best_compound_pair_key = pair_key
                best_compound_pair = (first_component, second_component)
        if best_compound_pair is not None:
            compound_pair_components = [best_compound_pair[0], best_compound_pair[1]]

    selected_components = list(compound_pair_components or [candidate_components[0]])
    ambiguous = False
    if len(candidate_components) > 1 and not compound_pair_components:
        first_component = candidate_components[0]
        second_component = candidate_components[1]
        first_branch_ids = _component_branch_ids(first_component)
        second_branch_ids = _component_branch_ids(second_component)
        same_corridor_pair = _components_share_corridor(first_component, second_component)
        opposite_compound_pair = (
            allow_compound_pair_merge
            and first_branch_ids
            and second_branch_ids
            and not bool(first_branch_ids & second_branch_ids)
            and float(first_component["distance_to_seed"]) <= float(DIVSTRIP_COMPLEX_PAIR_SEED_DISTANCE_M)
            and float(second_component["distance_to_seed"]) <= float(DIVSTRIP_COMPLEX_PAIR_SEED_DISTANCE_M)
            and float(first_component["distance_to_roads"]) <= float(DIVSTRIP_CONTEXT_ROAD_DISTANCE_M)
            and float(second_component["distance_to_roads"]) <= float(DIVSTRIP_CONTEXT_ROAD_DISTANCE_M)
            and float(first_component["geometry"].distance(second_component["geometry"])) <= float(
                DIVSTRIP_COMPLEX_PAIR_DISTANCE_M
            )
        )
        if opposite_compound_pair or (allow_compound_pair_merge and same_corridor_pair):
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
                if allow_compound_pair_merge:
                    selected_components = [first_component, second_component]
                else:
                    selected_components = [first_component]
                    ambiguous = False
    if not ambiguous and selected_components and allow_compound_pair_merge:
        merged_components = list(selected_components)
        merged_component_ids = {component["component_id"] for component in merged_components}
        for component in candidate_components:
            if component["component_id"] in merged_component_ids:
                continue
            if not any(
                _components_share_corridor(base_component, component)
                for base_component in merged_components
            ):
                continue
            merged_components.append(component)
            merged_component_ids.add(component["component_id"])
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

    selected_component_count = len(_collect_polygon_components(divstrip_constraint_geometry))
    seed_link_distance_m = (
        DIVSTRIP_COMPLEX_PAIR_SEED_DISTANCE_M
        if selected_component_count > 1
        else DIVSTRIP_SEED_FALLBACK_DISTANCE_M
    )
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
    if seed_union is not None and not seed_union.is_empty and seed_union.distance(divstrip_constraint_geometry) <= float(seed_link_distance_m):
        event_parts.append(seed_union.buffer(max(NODE_SEED_RADIUS_M * 1.5, RC_NODE_SEED_RADIUS_M * 1.2, 3.0)))
    event_window = unary_union(event_parts).intersection(drivezone_union).buffer(0)
    return event_window if not event_window.is_empty else GeometryCollection()


def _build_local_surface_clip_geometry(
    *,
    cross_section_surface_geometry,
    divstrip_event_window,
    divstrip_constraint_geometry,
    axis_window_geometry,
    drivezone_union,
    is_complex_junction: bool,
    multibranch_enabled: bool,
    selected_component_count: int,
    allow_full_axis_drivezone_fill: bool,
):
    if bool(allow_full_axis_drivezone_fill):
        clip_geometry = (
            axis_window_geometry
            if axis_window_geometry is not None and not axis_window_geometry.is_empty
            else GeometryCollection()
        )
        if not clip_geometry.is_empty and drivezone_union is not None and not drivezone_union.is_empty:
            clip_geometry = clip_geometry.intersection(drivezone_union).buffer(0)
        return clip_geometry if not clip_geometry.is_empty else GeometryCollection()

    prefer_divstrip_local_window = (
        bool(is_complex_junction)
        or bool(multibranch_enabled)
        or int(selected_component_count) > 1
    )
    source_geometries = (
        [divstrip_event_window, cross_section_surface_geometry]
        if prefer_divstrip_local_window
        else [cross_section_surface_geometry, divstrip_event_window]
    )
    if prefer_divstrip_local_window:
        localized_divstrip_clip = GeometryCollection()
        localized_intersection = GeometryCollection()
        if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty:
            localized_divstrip_clip = divstrip_constraint_geometry.buffer(
                max(float(DIVSTRIP_EVENT_BUFFER_M), float(EVENT_COMPONENT_SIDE_CLIP_BUFFER_M)),
                cap_style=2,
                join_style=2,
            )
            if divstrip_event_window is not None and not divstrip_event_window.is_empty:
                localized_divstrip_clip = localized_divstrip_clip.intersection(divstrip_event_window).buffer(0)
        localized_surface_clip = GeometryCollection()
        if cross_section_surface_geometry is not None and not cross_section_surface_geometry.is_empty:
            localized_surface_clip = cross_section_surface_geometry.buffer(
                max(1.5, min(float(EVENT_COMPONENT_SIDE_CLIP_BUFFER_M) * 0.25, 3.0)),
                cap_style=2,
                join_style=2,
            )
            if drivezone_union is not None and not drivezone_union.is_empty:
                localized_surface_clip = localized_surface_clip.intersection(drivezone_union).buffer(0)
        if (
            localized_divstrip_clip is not None
            and not localized_divstrip_clip.is_empty
            and localized_surface_clip is not None
            and not localized_surface_clip.is_empty
        ):
            localized_intersection = localized_divstrip_clip.intersection(localized_surface_clip).buffer(0)
            if int(selected_component_count) > 1:
                if not localized_intersection.is_empty:
                    clip_parts = [localized_intersection]
                else:
                    clip_parts = [localized_divstrip_clip]
            elif not localized_intersection.is_empty:
                clip_parts = [localized_intersection]
            else:
                clip_parts = [localized_divstrip_clip]
        else:
            clip_parts = [
                geometry
                for geometry in [localized_divstrip_clip, localized_surface_clip]
                if geometry is not None and not geometry.is_empty
            ]
        if not clip_parts:
            clip_parts = [
                geometry for geometry in [axis_window_geometry, cross_section_surface_geometry]
                if geometry is not None and not geometry.is_empty
            ]
    else:
        clip_parts = [
            geometry
            for geometry in source_geometries
            if geometry is not None and not geometry.is_empty
        ]
    if not clip_parts:
        return GeometryCollection()

    clip_geometry = unary_union(clip_parts)
    if drivezone_union is not None and not drivezone_union.is_empty:
        clip_geometry = clip_geometry.intersection(drivezone_union).buffer(0)
    if clip_geometry.is_empty:
        return GeometryCollection()

    clip_buffer_m = 0.0
    if not is_complex_junction and not multibranch_enabled and int(selected_component_count) <= 1:
        clip_buffer_m = max(float(EVENT_ANCHOR_BUFFER_M), float(ROAD_BUFFER_M), 2.5)
    elif is_complex_junction or multibranch_enabled or int(selected_component_count) > 1:
        clip_buffer_m = max(1.5, min(float(EVENT_COMPONENT_SIDE_CLIP_BUFFER_M) * 0.35, 3.0))

    if clip_buffer_m > 1e-6:
        buffered_geometry = clip_geometry.buffer(
            clip_buffer_m,
            cap_style=2,
            join_style=2,
        )
        if drivezone_union is not None and not drivezone_union.is_empty:
            buffered_geometry = buffered_geometry.intersection(drivezone_union).buffer(0)
        if not buffered_geometry.is_empty:
            clip_geometry = buffered_geometry
    return clip_geometry if not clip_geometry.is_empty else GeometryCollection()


def _resolve_selected_component_connector_span_limit_m(
    *,
    allow_extended_connector_span: bool,
) -> float:
    base_limit_m = float(MULTIBRANCH_LOCAL_CONTEXT_WINDOW_M) * 2.0
    if not bool(allow_extended_connector_span):
        return base_limit_m
    return max(base_limit_m, float(EVENT_REFERENCE_SCAN_MAX_M))


def _should_apply_selected_support_corridor(
    *,
    allow_full_axis_drivezone_fill: bool,
    parallel_competitor_present: bool,
    parallel_side_geometry,
    local_surface_clip_geometry,
) -> bool:
    if not bool(allow_full_axis_drivezone_fill) or bool(parallel_competitor_present):
        return False
    if (
        parallel_side_geometry is None
        or parallel_side_geometry.is_empty
        or local_surface_clip_geometry is None
        or local_surface_clip_geometry.is_empty
    ):
        return False
    local_surface_clip_area_m2 = float(local_surface_clip_geometry.area)
    if local_surface_clip_area_m2 <= 0.0:
        return False
    return (
        float(parallel_side_geometry.area) / local_surface_clip_area_m2
        >= SELECTED_SUPPORT_CORRIDOR_PARALLEL_RATIO_MIN
    )


def _build_selected_support_corridor_geometry(
    *,
    drivezone_union,
    clip_geometry,
    selected_support_union,
    event_anchor_geometry,
    support_buffer_m: float,
):
    if selected_support_union is None or selected_support_union.is_empty:
        return GeometryCollection()
    corridor_geometry = selected_support_union.buffer(
        support_buffer_m,
        cap_style=2,
        join_style=2,
    )
    if event_anchor_geometry is not None and not event_anchor_geometry.is_empty:
        corridor_geometry = corridor_geometry.union(
            event_anchor_geometry.buffer(
                max(EVENT_ANCHOR_BUFFER_M, ROAD_BUFFER_M),
                cap_style=2,
                join_style=2,
            )
        ).buffer(0)
    corridor_geometry = corridor_geometry.intersection(drivezone_union).buffer(0)
    if clip_geometry is not None and not clip_geometry.is_empty:
        corridor_geometry = corridor_geometry.intersection(clip_geometry).buffer(0)
    return corridor_geometry


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


def _resolve_event_axis_branch(
    *,
    road_branches,
    main_branch_ids: set[str],
    kind_2: int,
    preferred_axis_branch_id: str | None = None,
):
    if preferred_axis_branch_id is not None:
        for branch in road_branches:
            if str(branch.branch_id) == str(preferred_axis_branch_id):
                return branch
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


def _component_reference_overlap_metrics(
    *,
    component_geometry,
    reference_geometry,
    reference_buffer_m: float,
) -> tuple[bool, float, float]:
    if (
        component_geometry is None
        or component_geometry.is_empty
        or reference_geometry is None
        or reference_geometry.is_empty
    ):
        return False, math.inf, 0.0
    distance_to_reference = float(component_geometry.distance(reference_geometry))
    overlap_geometry = component_geometry.intersection(
        reference_geometry.buffer(max(0.1, float(reference_buffer_m)), cap_style=2, join_style=2)
    ).buffer(0)
    overlap_measure = 0.0
    if not overlap_geometry.is_empty:
        overlap_measure = float(getattr(overlap_geometry, "area", 0.0) or 0.0)
        if overlap_measure <= 1e-6:
            overlap_measure = float(getattr(overlap_geometry, "length", 0.0) or 0.0)
    return bool(overlap_measure > 1e-6 or distance_to_reference <= max(0.25, float(reference_buffer_m) * 0.35)), distance_to_reference, overlap_measure


def _pick_reference_s(
    *,
    divstrip_ref_s: float | None,
    divstrip_ref_source: str,
    drivezone_split_s: float | None,
    max_offset_m: float,
) -> tuple[float | None, str, str]:
    if divstrip_ref_s is not None:
        reference_s = float(divstrip_ref_s)
        return float(reference_s), "divstrip_ref", f"divstrip_{str(divstrip_ref_source)}_window"
    if drivezone_split_s is not None:
        return float(drivezone_split_s), "drivezone_split", "drivezone_split_window"
    return None, "none", "none"




__all__ = [name for name in globals() if not name.startswith("__")]
