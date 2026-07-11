from __future__ import annotations

from collections import defaultdict, deque

from collections.abc import Iterable

from dataclasses import dataclass, field

from time import perf_counter

from typing import Any

from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from shapely.geometry.base import BaseGeometry

from shapely.ops import nearest_points, substring, unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import NodeRecord, RoadRecord

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import (
    Step6OutputGeometries,
    Step6Result,
    FinalizationContext,
)

TARGET_NODE_BUFFER_M = 5.5

SUPPORT_ONLY_SEAM_BRIDGE_BUFFER_M = 9.0

SUPPORT_ONLY_TINY_FRAGMENT_MAX_AREA_M2 = 12.0

SUPPORT_ONLY_DOMINANT_COMPONENT_MIN_RATIO = 0.95

REQUIRED_NODE_BUFFER_M = 5.5

REQUIRED_ROAD_BUFFER_M = 6.0

SEMANTIC_INTRA_LINE_BUFFER_M = 5.5

FOREIGN_MASK_BUFFER_M = 1.0

LEGAL_SPACE_TOLERANCE_M = 0.6

NODE_COVER_TOLERANCE_M = 1.0

TARGET_NODE_INCIDENT_ROAD_COVER_TOLERANCE_M = 10.0

LINE_COVER_BUFFER_M = 2.0

LINE_COVER_MIN_RATIO = 0.68

SELECTED_ROAD_CORE_MIN_RATIO = 0.45

TARGET_NODE_CONNECTION_MIN_RATIO = 0.98

FOREIGN_OVERLAP_TOLERANCE_M2 = 0.05

FINAL_CLOSE_M = 1.6

DIRECTIONAL_CUT_DISTANCE_M = 20.0

DIRECTIONAL_WINDOW_MIN_HALF_WIDTH_M = 60.0

DIRECTIONAL_WINDOW_EXTENSION_FACTOR = 2.0

STEP3_TWO_NODE_T_BRIDGE_BUFFER_M = 8.0

CENTER_TWO_NODE_T_BRIDGE_MAX_LENGTH_M = 90.0

BRANCH_CLIP_HALF_WIDTH_M = 10.0

BRANCH_SPECIAL_CLIP_HALF_WIDTH_M = 6.0

BRANCH_CLIP_CENTER_RADIUS_M = 14.0

BRANCH_TRIM_HALF_WIDTH_M = 6.0

BRANCH_SPECIAL_TRIM_HALF_WIDTH_M = 4.0

SINGLE_SIDED_HORIZONTAL_EXTENSION_M = 5.0

SINGLE_SIDED_HORIZONTAL_ALIGNMENT_TOLERANCE_M = 8.0

SINGLE_SIDED_HORIZONTAL_MIN_REQUIRED_NODE_COUNT = 2

PRIMARY_INFEASIBLE = "infeasible_under_frozen_constraints"

PRIMARY_SOLVER_FAILED = "geometry_solver_failed"

SECONDARY_STEP1_STEP3_CONFLICT = "step1_step3_conflict"

SECONDARY_STAGE3_RC_GAP = "stage3_rc_gap"

SECONDARY_FOREIGN_CONFLICT = "foreign_exclusion_conflict"

SECONDARY_TEMPLATE_MISFIT = "template_misfit"

SECONDARY_CLOSURE_FAILURE = "geometry_closure_failure"

SECONDARY_CLEANUP_OVERTRIM = "cleanup_overtrim"

SECONDARY_CLEANUP_UNDERTRIM = "cleanup_undertrim"

SECONDARY_FOREIGN_REINTRODUCED = "foreign_reintroduced_by_cleanup"

SECONDARY_SHAPE_ARTIFACT = "shape_artifact_failure"

from .step6_geometry_models import (
    _DirectionalBranchWindow,
    _SingleSidedHorizontalTraceDecision,
    _Step6GeometryCache,
)

from .step6_geometry_primitives import (
    _accumulate_stage_timer,
    _as_linestring,
    _branch_local_overrun_mask,
    _branch_local_sector_geometry,
    _build_foreign_mask_geometry,
    _cached_line_buffers,
    _cached_shape_metrics,
    _clean_geometry,
    _component_count,
    _contiguous_allowed_prefix,
    _directional_window_half_width,
    _geometry_cache_token,
    _half_plane_keep_polygon,
    _hole_count,
    _iter_geometries,
    _iter_lines,
    _iter_polygons,
    _line_buffers,
    _line_coverage_ratio,
    _line_coverage_ratio_with_cover_geometry,
    _node_cover_ratio,
    _node_cover_ratio_with_cover_geometry,
    _point_buffers,
    _point_on_line,
    _prune_support_only_tiny_fragments,
    _required_node_records,
    _retain_components_touching_keep_geometry,
    _reverse_line,
    _road_core_cover_ratio,
    _road_directional_branches,
    _road_union,
    _semantic_group_id,
    _shape_metrics,
    _sorted_ids,
    _step3_two_node_t_bridge_geometry,
    _substring_line,
    _support_only_seam_bridge_geometry,
    _target_anchor_geometry,
    _target_node_connection_line_geometry,
    _target_node_cover_ratio_with_cover_geometry,
    _target_node_has_incident_polygon_support,
    _union_geometries,
    _unit_direction_at_distance,
)

from .step6_geometry_context import (
    _allowed_space_tolerance_geometry,
    _cached_boundary_buffer,
    _local_required_node_records,
    _local_required_road_geometry,
    _local_required_road_records,
    _local_required_semantic_member_records,
    _required_road_records,
    _selected_road_records,
    _semantic_intra_rcsdnode_line_count,
    _semantic_intra_rcsdnode_line_geometry,
    _single_sided_horizontal_pair_ids,
    _single_sided_vertical_exit_geometry,
)

def _single_sided_trace_candidate_rcsdroad_records(
    finalization_context: FinalizationContext,
) -> list[RoadRecord]:
    association_context = finalization_context.association_context
    current_swsd_surface = _clean_geometry(association_context.current_swsd_surface_geometry)
    allowed_space = _clean_geometry(association_context.step3_allowed_space_geometry)
    if current_swsd_surface is None or allowed_space is None:
        return []
    u_turn_ids = set(finalization_context.association_case_result.extra_status_fields.get("u_turn_rcsdroad_ids") or [])
    return [
        road
        for road in association_context.step1_context.rcsd_roads
        if road.road_id not in u_turn_ids
        and road.geometry.intersects(current_swsd_surface.buffer(FOREIGN_MASK_BUFFER_M))
        and road.geometry.intersects(allowed_space.buffer(FOREIGN_MASK_BUFFER_M))
    ]

def _single_sided_trace_reachable_endpoint_nodes(
    finalization_context: FinalizationContext,
    candidate_roads: list[RoadRecord],
    *,
    geometry_cache: _Step6GeometryCache | None = None,
) -> tuple[tuple[str, ...], tuple[str, ...], list[NodeRecord]]:
    vertical_exit_geometry = _single_sided_vertical_exit_geometry(
        finalization_context,
        geometry_cache=geometry_cache,
    )
    if vertical_exit_geometry is None or vertical_exit_geometry.is_empty:
        return (), (), []

    roads_by_id = {road.road_id: road for road in candidate_roads}
    vertical_seed_ids = tuple(
        _sorted_ids(
            road.road_id
            for road in candidate_roads
            if road.geometry.intersects(vertical_exit_geometry.buffer(SINGLE_SIDED_HORIZONTAL_ALIGNMENT_TOLERANCE_M))
        )
    )
    if not vertical_seed_ids:
        return (), (), []

    node_to_roads: dict[str, set[str]] = defaultdict(set)
    for road in candidate_roads:
        if road.snodeid not in {None, ""}:
            node_to_roads[str(road.snodeid)].add(road.road_id)
        if road.enodeid not in {None, ""}:
            node_to_roads[str(road.enodeid)].add(road.road_id)

    road_adjacency: dict[str, set[str]] = defaultdict(set)
    for road_ids in node_to_roads.values():
        for road_id in road_ids:
            road_adjacency[road_id].update(road_ids - {road_id})

    reachable_ids: set[str] = set(vertical_seed_ids)
    queue: deque[str] = deque(vertical_seed_ids)
    while queue:
        road_id = queue.popleft()
        for other_id in road_adjacency.get(road_id, set()):
            if other_id in reachable_ids:
                continue
            reachable_ids.add(other_id)
            queue.append(other_id)

    endpoint_node_ids = {
        node_id
        for road_id in reachable_ids
        for node_id in [roads_by_id[road_id].snodeid, roads_by_id[road_id].enodeid]
        if node_id not in {None, ""}
    }
    endpoint_nodes = [
        node
        for node in finalization_context.association_context.step1_context.rcsd_nodes
        if node.node_id in endpoint_node_ids
    ]
    return vertical_seed_ids, tuple(_sorted_ids(reachable_ids)), endpoint_nodes

def _single_sided_horizontal_trace_decisions(
    finalization_context: FinalizationContext,
    allowed_space: BaseGeometry | None,
    *,
    allowed_space_tolerance_geometry: BaseGeometry | None = None,
    geometry_cache: _Step6GeometryCache | None = None,
) -> dict[tuple[str, int], _SingleSidedHorizontalTraceDecision]:
    if geometry_cache is not None and geometry_cache.single_sided_trace_decisions_ready:
        return geometry_cache.single_sided_trace_decisions
    association_case_result = finalization_context.association_case_result
    if association_case_result.template_class != "single_sided_t_mouth":
        return {}
    if association_case_result.association_class != "A":
        return {}
    if allowed_space is None:
        return {}

    horizontal_pair_ids = _single_sided_horizontal_pair_ids(finalization_context)
    if len(horizontal_pair_ids) < 2:
        return {}

    candidate_roads = _single_sided_trace_candidate_rcsdroad_records(finalization_context)
    vertical_seed_ids, traced_road_ids, endpoint_nodes = _single_sided_trace_reachable_endpoint_nodes(
        finalization_context,
        candidate_roads,
        geometry_cache=geometry_cache,
    )
    if not vertical_seed_ids or not traced_road_ids or not endpoint_nodes:
        return {}
    connector_endpoint_node_ids = set(
        association_case_result.extra_status_fields.get("degree2_connector_candidate_rcsdnode_ids") or []
    ) | set(association_case_result.extra_status_fields.get("nonsemantic_connector_rcsdnode_ids") or [])
    remote_terminal_node_ids = set(
        association_case_result.extra_status_fields.get("single_sided_terminal_required_rcsdnode_ids") or []
    )
    excluded_trace_endpoint_node_ids = set(connector_endpoint_node_ids)
    if remote_terminal_node_ids:
        excluded_trace_endpoint_node_ids.update(
            association_case_result.extra_status_fields.get("t_mouth_strong_related_overflow_rcsdnode_ids") or []
        )
        excluded_trace_endpoint_node_ids.update(remote_terminal_node_ids)
    endpoint_nodes = [
        node for node in endpoint_nodes if node.node_id not in excluded_trace_endpoint_node_ids
    ]
    if not endpoint_nodes:
        return {}

    selected_roads = _selected_road_records(finalization_context)
    anchor_geometry = _target_anchor_geometry(finalization_context, geometry_cache=geometry_cache)

    def _build_branch_hits(
        candidate_endpoint_nodes: list[NodeRecord],
    ) -> dict[tuple[str, int], list[tuple[NodeRecord, float]]]:
        hits_by_branch: dict[tuple[str, int], list[tuple[NodeRecord, float]]] = {}
        for road in selected_roads:
            if road.road_id not in horizontal_pair_ids:
                continue
            for branch_index, branch_geometry, _anchor_distance in _road_directional_branches(road, anchor_geometry):
                allowed_prefix = _contiguous_allowed_prefix(
                    branch_geometry,
                    allowed_space,
                    allowed_space_tolerance_geometry=allowed_space_tolerance_geometry,
                )
                if allowed_prefix is None or allowed_prefix.length <= 1e-6:
                    continue
                hits: list[tuple[NodeRecord, float]] = []
                for node in candidate_endpoint_nodes:
                    if allowed_prefix.distance(node.geometry) > SINGLE_SIDED_HORIZONTAL_ALIGNMENT_TOLERANCE_M:
                        continue
                    nearest_point = nearest_points(node.geometry, allowed_prefix)[1]
                    projection_distance = allowed_prefix.project(nearest_point)
                    if projection_distance <= NODE_COVER_TOLERANCE_M:
                        continue
                    hits.append((node, projection_distance))
                hits_by_branch[(road.road_id, branch_index)] = hits
        return hits_by_branch

    strong_related_rcsdnode_ids = set(
        association_case_result.extra_status_fields.get("t_mouth_strong_related_rcsdnode_ids") or []
    )
    branch_hits = _build_branch_hits(endpoint_nodes)
    if strong_related_rcsdnode_ids:
        strong_endpoint_nodes = [
            node
            for node in endpoint_nodes
            if node.node_id in strong_related_rcsdnode_ids
        ]
        strong_branch_hits = _build_branch_hits(strong_endpoint_nodes)
        strong_hit_road_ids = {
            road_id
            for (road_id, _branch_index), hits in strong_branch_hits.items()
            if hits
        }
        strong_hits_preserve_full_extent = True
        for branch_key, hits in branch_hits.items():
            if not hits:
                continue
            strong_hits = strong_branch_hits.get(branch_key) or []
            if not strong_hits:
                strong_hits_preserve_full_extent = False
                break
            full_extent = max(projection_distance for _node, projection_distance in hits)
            strong_extent = max(projection_distance for _node, projection_distance in strong_hits)
            if strong_extent + 1e-6 < full_extent:
                strong_hits_preserve_full_extent = False
                break
        if len(strong_hit_road_ids) >= 2 and strong_hits_preserve_full_extent:
            branch_hits = strong_branch_hits

    hit_road_ids = {
        road_id
        for (road_id, _branch_index), hits in branch_hits.items()
        if hits
    }
    pair_complete = len(hit_road_ids) >= 2
    decision_map: dict[tuple[str, int], _SingleSidedHorizontalTraceDecision] = {}
    for (road_id, branch_index), hits in branch_hits.items():
        if not pair_complete or not hits:
            decision_map[(road_id, branch_index)] = _SingleSidedHorizontalTraceDecision(
                road_id=road_id,
                branch_index=branch_index,
                trace_status="trace_pair_incomplete" if not pair_complete else "no_trace",
                vertical_seed_rcsdroad_ids=vertical_seed_ids,
                traced_rcsdroad_ids=traced_road_ids,
                traced_rcsdnode_ids=(),
                semantic_extent_m=None,
                requested_cut_length_m=None,
                apply_special_rule=False,
            )
            continue
        semantic_extent = max(projection_distance for _node, projection_distance in hits)
        requested_length = max(
            DIRECTIONAL_CUT_DISTANCE_M,
            semantic_extent + SINGLE_SIDED_HORIZONTAL_EXTENSION_M,
        )
        apply_special_rule = requested_length > DIRECTIONAL_CUT_DISTANCE_M + 1e-6
        decision_map[(road_id, branch_index)] = _SingleSidedHorizontalTraceDecision(
            road_id=road_id,
            branch_index=branch_index,
            trace_status=(
                "trace_selected_semantic_plus_5m"
                if apply_special_rule
                else "trace_at_or_below_20m"
            ),
            vertical_seed_rcsdroad_ids=vertical_seed_ids,
            traced_rcsdroad_ids=traced_road_ids,
            traced_rcsdnode_ids=tuple(
                _sorted_ids(node.node_id for node, _projection_distance in hits)
            ),
            semantic_extent_m=round(semantic_extent, 6),
            requested_cut_length_m=round(requested_length, 6),
            apply_special_rule=apply_special_rule,
        )
    if geometry_cache is not None:
        geometry_cache.single_sided_trace_decisions = decision_map
        geometry_cache.single_sided_trace_decisions_ready = True
    return decision_map

def _single_sided_strong_node_keep_geometry(
    finalization_context: FinalizationContext,
) -> BaseGeometry | None:
    association_case_result = finalization_context.association_case_result
    if (
        association_case_result.template_class != "single_sided_t_mouth"
        or association_case_result.association_class != "A"
    ):
        return None
    strong_node_ids = set(association_case_result.extra_status_fields.get("t_mouth_strong_related_rcsdnode_ids") or [])
    if not strong_node_ids:
        return None
    return _point_buffers(
        (
            node
            for node in finalization_context.association_context.step1_context.rcsd_nodes
            if node.node_id in strong_node_ids
        ),
        REQUIRED_NODE_BUFFER_M,
    )

def _build_directional_cut_geometry(
    finalization_context: FinalizationContext,
    allowed_space: BaseGeometry | None,
    *,
    geometry_cache: _Step6GeometryCache | None = None,
    step3_two_node_t_bridge_geometry: BaseGeometry | None = None,
    force_preserve_single_sided_horizontal_pair: bool = False,
    force_preserve_all_branches: bool = False,
) -> tuple[BaseGeometry | None, BaseGeometry | None, list[dict[str, Any]]]:
    cache_key = (
        bool(force_preserve_single_sided_horizontal_pair),
        bool(force_preserve_all_branches),
    )
    if geometry_cache is not None and cache_key in geometry_cache.directional_cut_cache:
        return geometry_cache.directional_cut_cache[cache_key]
    selected_roads = _selected_road_records(finalization_context)
    if not selected_roads:
        return None, None, []
    anchor_geometry = _target_anchor_geometry(finalization_context, geometry_cache=geometry_cache)
    clip_extent = _directional_window_half_width(allowed_space) * DIRECTIONAL_WINDOW_EXTENSION_FACTOR
    target_road_ids = set(finalization_context.association_context.step1_context.target_road_ids)
    single_sided_horizontal_pair_ids = _single_sided_horizontal_pair_ids(finalization_context)
    allowed_space_tolerance_geometry = _allowed_space_tolerance_geometry(
        allowed_space,
        geometry_cache=geometry_cache,
    )
    single_sided_trace_decisions = _single_sided_horizontal_trace_decisions(
        finalization_context,
        allowed_space,
        allowed_space_tolerance_geometry=allowed_space_tolerance_geometry,
        geometry_cache=geometry_cache,
    )
    branch_windows: list[_DirectionalBranchWindow] = []
    branch_decisions: dict[tuple[str, int], _SingleSidedHorizontalTraceDecision] = {}
    keep_geometries: list[BaseGeometry] = []
    trim_geometries: list[BaseGeometry] = []

    for road in selected_roads:
        for branch_index, branch_geometry, anchor_distance in _road_directional_branches(road, anchor_geometry):
            allowed_prefix = _contiguous_allowed_prefix(
                branch_geometry,
                allowed_space,
                allowed_space_tolerance_geometry=allowed_space_tolerance_geometry,
            )
            available_length = allowed_prefix.length if allowed_prefix is not None else 0.0
            trace_decision = single_sided_trace_decisions.get((road.road_id, branch_index))
            branch_decisions[(road.road_id, branch_index)] = trace_decision
            special_cut_length = (
                trace_decision.requested_cut_length_m
                if trace_decision is not None and trace_decision.apply_special_rule
                else None
            )
            special_rule_applied = bool(
                trace_decision is not None and trace_decision.apply_special_rule
            )
            semantic_extent = (
                trace_decision.semantic_extent_m
                if trace_decision is not None
                else None
            )
            force_preserve_horizontal_branch = (
                force_preserve_single_sided_horizontal_pair
                and road.road_id in single_sided_horizontal_pair_ids
            )
            force_preserve_branch = force_preserve_all_branches or force_preserve_horizontal_branch
            target_cut_length = (
                special_cut_length if special_cut_length is not None else DIRECTIONAL_CUT_DISTANCE_M
            )
            preserve_candidate_boundary = force_preserve_branch or (
                available_length < target_cut_length - 1e-6
            )
            cut_length = min(target_cut_length, available_length)
            if force_preserve_branch:
                cut_length = available_length
            core_geometry = _substring_line(allowed_prefix, 0.0, cut_length) if allowed_prefix is not None else None
            clip_geometry = None
            if allowed_prefix is not None and cut_length > 1e-6:
                branch_half_width = (
                    BRANCH_SPECIAL_CLIP_HALF_WIDTH_M
                    if special_rule_applied
                    else BRANCH_CLIP_HALF_WIDTH_M
                )
                local_sector_geometry = _branch_local_sector_geometry(
                    allowed_prefix,
                    branch_half_width,
                    allowed_space,
                )
                if preserve_candidate_boundary:
                    clip_geometry = local_sector_geometry
                else:
                    cut_half_plane = _half_plane_keep_polygon(allowed_prefix, cut_length, clip_extent)
                    clip_geometry = _clean_geometry(
                        local_sector_geometry.intersection(cut_half_plane)
                        if local_sector_geometry is not None and cut_half_plane is not None
                        else local_sector_geometry
                    )
                if clip_geometry is not None:
                    keep_geometries.append(clip_geometry)
                trim_geometry = _branch_local_overrun_mask(
                    allowed_prefix,
                    available_length,
                    cut_length,
                    (
                        BRANCH_SPECIAL_TRIM_HALF_WIDTH_M
                        if special_rule_applied
                        else BRANCH_TRIM_HALF_WIDTH_M
                    ),
                    allowed_space,
                )
                if trim_geometry is not None:
                    trim_geometries.append(trim_geometry)
            branch_windows.append(
                _DirectionalBranchWindow(
                    road_id=road.road_id,
                    branch_index=branch_index,
                    anchor_distance_m=round(anchor_distance, 6),
                    available_length_m=round(available_length, 6),
                    cut_length_m=round(cut_length, 6),
                    preserve_candidate_boundary=preserve_candidate_boundary,
                    special_rule_applied=special_rule_applied,
                    semantic_extent_m=round(semantic_extent, 6) if semantic_extent is not None else None,
                    core_geometry=core_geometry if road.road_id in target_road_ids else None,
                    clip_geometry=clip_geometry,
                )
            )

    direction_clip_geometry = _union_geometries(keep_geometries)
    if direction_clip_geometry is not None and trim_geometries:
        direction_clip_geometry = _clean_geometry(
            direction_clip_geometry.difference(_union_geometries(trim_geometries))
        )
    bridge_geometry = step3_two_node_t_bridge_geometry
    if bridge_geometry is None:
        bridge_geometry = _step3_two_node_t_bridge_geometry(finalization_context, allowed_space)
    if bridge_geometry is not None:
        direction_clip_geometry = _union_geometries([direction_clip_geometry, bridge_geometry])
    strong_node_keep_geometry = _single_sided_strong_node_keep_geometry(finalization_context)
    if strong_node_keep_geometry is not None:
        direction_clip_geometry = _union_geometries([direction_clip_geometry, strong_node_keep_geometry])
    selected_core_geometry = _union_geometries(
        branch.core_geometry for branch in branch_windows if branch.core_geometry is not None
    )
    audit_rows = [
        {
            "road_id": branch.road_id,
            "branch_index": branch.branch_index,
            "anchor_distance_m": branch.anchor_distance_m,
            "available_length_m": branch.available_length_m,
            "cut_length_m": branch.cut_length_m,
            "preserve_candidate_boundary": branch.preserve_candidate_boundary,
            "special_rule_applied": branch.special_rule_applied,
            "semantic_extent_m": branch.semantic_extent_m,
            "trace_status": (
                branch_decisions[(branch.road_id, branch.branch_index)].trace_status
                if branch_decisions.get((branch.road_id, branch.branch_index)) is not None
                else "no_trace"
            ),
            "trace_vertical_seed_rcsdroad_ids": (
                list(branch_decisions[(branch.road_id, branch.branch_index)].vertical_seed_rcsdroad_ids)
                if branch_decisions.get((branch.road_id, branch.branch_index)) is not None
                else []
            ),
            "trace_traced_rcsdroad_ids": (
                list(branch_decisions[(branch.road_id, branch.branch_index)].traced_rcsdroad_ids)
                if branch_decisions.get((branch.road_id, branch.branch_index)) is not None
                else []
            ),
            "trace_traced_rcsdnode_ids": (
                list(branch_decisions[(branch.road_id, branch.branch_index)].traced_rcsdnode_ids)
                if branch_decisions.get((branch.road_id, branch.branch_index)) is not None
                else []
            ),
            "window_mode": (
                "target_connected_preserve_candidate_boundary"
                if force_preserve_all_branches
                else
                "single_sided_target_connected_preserve_candidate_boundary"
                if force_preserve_single_sided_horizontal_pair and branch.road_id in single_sided_horizontal_pair_ids
                else
                "single_sided_preserve_candidate_boundary"
                if branch.special_rule_applied and branch.preserve_candidate_boundary
                else "single_sided_semantic_plus_5m"
                if branch.special_rule_applied
                else "preserve_candidate_boundary"
                if branch.preserve_candidate_boundary
                else "cut_at_20m"
            ),
        }
        for branch in branch_windows
    ]
    result = (direction_clip_geometry, selected_core_geometry, audit_rows)
    if geometry_cache is not None:
        geometry_cache.directional_cut_cache[cache_key] = result
    return result

def build_step6_result(
    finalization_context: FinalizationContext,
    *,
    stage_timers: dict[str, float] | None = None,
    use_step6_geometry_cache: bool = True,
) -> Step6Result:
    from .step6_geometry_runner import build_step6_result as _impl

    return _impl(
        finalization_context,
        stage_timers=stage_timers,
        use_step6_geometry_cache=use_step6_geometry_cache,
    )


def build_step6_status_doc(
    finalization_context: FinalizationContext,
    step6_result: Step6Result,
) -> dict[str, Any]:
    from .step6_geometry_runner import build_step6_status_doc as _impl

    return _impl(finalization_context, step6_result)
