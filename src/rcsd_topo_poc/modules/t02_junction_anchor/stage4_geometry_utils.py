from __future__ import annotations

import math
from collections import defaultdict
from itertools import combinations, permutations
from typing import Any, Optional, Sequence

import numpy as np
from shapely.geometry import GeometryCollection, LineString, Point
from shapely.ops import linemerge, nearest_points, substring, unary_union

from rcsd_topo_poc.modules.t02_junction_anchor.shared import LoadedFeature, T02RunError, normalize_id
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
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
    allow_compound_pair_merge: bool = False,
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
    if allow_compound_pair_merge:
        candidate_components = anchor_preferred_components or matched_components or road_nearby_components or nearby_components
    else:
        candidate_components = []
        seen_candidate_component_ids: set[str] = set()
        for component in [*matched_components, *anchor_preferred_components, *road_nearby_components, *nearby_components]:
            component_id = str(component["component_id"])
            if component_id in seen_candidate_component_ids:
                continue
            seen_candidate_component_ids.add(component_id)
            candidate_components.append(component)
    if allow_compound_pair_merge:
        candidate_components.sort(
            key=lambda component: (
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
                float(component["distance_to_seed"]),
                float(component["distance_to_event_anchor"]),
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


def _collect_axis_lateral_offsets(
    geometry,
    *,
    origin_xy: tuple[float, float],
    axis_unit_vector: tuple[float, float],
    axis_window_m: float | None = None,
) -> list[float]:
    if geometry is None or geometry.is_empty:
        return []
    ux, uy = axis_unit_vector
    vx, vy = -uy, ux
    if axis_window_m is None or axis_window_m <= 1e-6:
        axis_window_m = None
    lateral_offsets: list[float] = []
    for item in _explode_component_geometries(geometry):
        geometry_type = getattr(item, "geom_type", None)
        if geometry_type == "Point":
            coordinates = [_coord_xy(item.coords[0])]
        elif geometry_type == "LineString":
            coordinates = list(item.coords)
        elif geometry_type == "Polygon":
            coordinates = list(item.exterior.coords)
            for ring in item.interiors:
                coordinates.extend(ring.coords)
        else:
            continue
        for x, y in (_coord_xy(coord) for coord in coordinates):
            dx = float(x) - float(origin_xy[0])
            dy = float(y) - float(origin_xy[1])
            axis_offset = dx * ux + dy * uy
            if axis_window_m is not None and abs(axis_offset) > float(axis_window_m):
                continue
            lateral_offsets.append(abs(dx * vx + dy * vy))
    return lateral_offsets


def _resolve_event_cross_half_len(
    *,
    origin_point: Point,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    event_anchor_geometry,
    branch_a_centerline,
    branch_b_centerline,
    selected_roads: list[ParsedRoad],
    selected_rcsd_roads: list[ParsedRoad],
    patch_size_m: float,
) -> float:
    if axis_unit_vector is None or axis_centerline is None or axis_centerline.is_empty:
        return float(EVENT_CROSS_HALF_LEN_FALLBACK_M)
    origin_xy = (float(origin_point.x), float(origin_point.y))
    axis_window_m = float(EVENT_CROSS_HALF_LEN_AXIS_SAMPLE_WINDOW_M)
    candidate_offsets: list[float] = []
    candidate_geometries = [
        event_anchor_geometry,
        branch_a_centerline,
        branch_b_centerline,
    ] + [road.geometry for road in selected_roads if road.geometry is not None and not road.geometry.is_empty]
    for road in selected_rcsd_roads:
        if road.geometry is not None and not road.geometry.is_empty:
            candidate_geometries.append(road.geometry)
    candidate_geometries = [geometry for geometry in candidate_geometries if geometry is not None and not geometry.is_empty]
    for geometry in candidate_geometries:
        candidate_offsets.extend(
            _collect_axis_lateral_offsets(
                geometry,
                origin_xy=origin_xy,
                axis_unit_vector=axis_unit_vector,
                axis_window_m=axis_window_m,
            )
        )

    max_lateral_offset = max(candidate_offsets) if candidate_offsets else None
    if max_lateral_offset is None:
        resolved_half_len = float(EVENT_CROSS_HALF_LEN_FALLBACK_M)
    else:
        resolved_half_len = float(max_lateral_offset + EVENT_CROSS_HALF_LEN_SIDE_MARGIN_M)
    resolved_half_len = max(float(EVENT_CROSS_HALF_LEN_MIN_M), min(float(EVENT_CROSS_HALF_LEN_MAX_M), resolved_half_len))
    patch_half_cap = max(
        float(EVENT_CROSS_HALF_LEN_MIN_M),
        min(float(EVENT_CROSS_HALF_LEN_MAX_M), float(patch_size_m) * float(EVENT_CROSS_HALF_LEN_PATCH_SCALE_RATIO)),
    )
    return float(min(resolved_half_len, patch_half_cap))


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


def _pick_local_component_boundary_branches(
    *,
    road_branches,
    selected_branch_ids: set[str],
    kind_2: int,
    road_lookup: dict[str, ParsedRoad],
    reference_point: Point,
):
    fallback_pair = _pick_cross_section_boundary_branches(
        road_branches=road_branches,
        selected_branch_ids=selected_branch_ids,
        kind_2=kind_2,
    )
    selected_branches = list(road_branches)
    if kind_2 == 8:
        directional_candidates = [branch for branch in selected_branches if branch.has_incoming_support]
    else:
        directional_candidates = [branch for branch in selected_branches if branch.has_outgoing_support]
    if len(directional_candidates) < 2:
        directional_candidates = list(selected_branches)
    if len(directional_candidates) < 2:
        return fallback_pair

    local_candidates: list[tuple[Any, float, int]] = []
    for branch in directional_candidates:
        centerline = _resolve_branch_centerline(
            branch=branch,
            road_lookup=road_lookup,
            reference_point=reference_point,
        )
        if centerline is None or centerline.is_empty:
            continue
        local_candidates.append(
            (
                branch,
                float(centerline.distance(reference_point)),
                1 if branch.branch_id in selected_branch_ids else 0,
            )
        )
    if len(local_candidates) < 2:
        return fallback_pair

    nearby_candidates = [
        item
        for item in local_candidates
        if float(item[1]) <= float(EVENT_COMPONENT_BRANCH_LOCAL_DISTANCE_M)
    ]
    if len(nearby_candidates) < 2:
        nearby_candidates = sorted(
            local_candidates,
            key=lambda item: (
                float(item[1]),
                -int(item[2]),
                -_selected_branch_score(item[0]),
            ),
        )[:5]

    best_pair = None
    best_key = None
    for (first_branch, first_dist, first_preferred), (second_branch, second_dist, second_preferred) in combinations(nearby_candidates, 2):
        pair_key = (
            -max(float(first_dist), float(second_dist)),
            -(float(first_dist) + float(second_dist)),
            int(first_preferred) + int(second_preferred),
            _branch_angle_gap_deg(first_branch, second_branch),
            _selected_branch_score(first_branch) + _selected_branch_score(second_branch),
        )
        if best_key is None or pair_key > best_key:
            best_key = pair_key
            best_pair = (first_branch, second_branch)
    if best_pair is None:
        return fallback_pair
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

def _build_axis_side_halfmask(
    *,
    grid,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    parallel_side_sign: int | None,
) -> np.ndarray | None:
    if axis_unit_vector is None or parallel_side_sign not in (-1, 1):
        return None
    ux, uy = axis_unit_vector
    vx, vy = -uy, ux
    lateral_offset = (grid.xx - float(origin_point.x)) * float(vx) + (grid.yy - float(origin_point.y)) * float(vy)
    side_mask = np.where(
        lateral_offset * float(parallel_side_sign) >= -float(PARALLEL_SIDE_SIGN_EPS_M),
        True,
        False,
    )
    return side_mask.astype(bool)


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
    midpoint_s = max(lo + 1e-6, min(hi - 1e-6, midpoint_s))
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
    if tip_s is not None and search_start - 1e-6 <= float(tip_s) <= search_end + 1e-6:
        divstrip_ref_s = float(tip_s)
        divstrip_ref_source = "tip_projection"
    elif first_divstrip_hit_s is not None:
        divstrip_ref_s = float(first_divstrip_hit_s)
        divstrip_ref_source = "first_hit"
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
        if support_geometry is None and drivezone_pieces:
            all_s_values: list[float] = []
            for piece in drivezone_pieces:
                for coord in list(piece.coords):
                    if len(coord) >= 2:
                        all_s_values.append(float(crossline.project(Point(float(coord[0]), float(coord[1])))))
            if all_s_values:
                full_start = crossline.interpolate(min(all_s_values))
                full_end = crossline.interpolate(max(all_s_values))
                clipped_line = LineString([
                    (float(full_start.x), float(full_start.y)),
                    (float(full_end.x), float(full_end.y)),
                ])
            else:
                clipped_line = None
        else:
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

__all__ = [
    name
    for name, value in globals().items()
    if name.isupper() or name == 'Stage4RunError' or (name.startswith('_') and callable(value))
]
