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
    _cached_boundary_buffer,
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

def _local_required_semantic_member_records(
    finalization_context: FinalizationContext,
    local_required_nodes: Iterable[NodeRecord],
) -> list[NodeRecord]:
    local_required_items = list(local_required_nodes)
    required_group_ids = {_semantic_group_id(node) for node in local_required_items}
    if not required_group_ids:
        return []
    gate_audit = finalization_context.association_case_result.extra_status_fields.get("required_rcsdnode_gate_audit") or {}
    related_group_audit = (
        finalization_context.association_case_result.extra_status_fields.get("related_rcsdnode_group_audit") or {}
    )
    terminal_group_ids = {
        str(group_id)
        for group_id, row in gate_audit.items()
        if row.get("gate_reason") == "single_sided_required_core_terminal_degree1_anchor_review"
    }
    overflow_ids = {
        str(node_id)
        for node_id in (
            finalization_context.association_case_result.extra_status_fields.get(
                "t_mouth_strong_related_overflow_rcsdnode_ids"
            )
            or []
        )
        if node_id is not None and str(node_id) != ""
    }
    local_required_ids = {node.node_id for node in local_required_items}
    step4_doc = finalization_context.association_case_result.audit_doc.get("step4") or {}
    candidate_ids = {
        str(node_id)
        for node_id in (step4_doc.get("candidate_rcsdnode_ids") or [])
        if node_id is not None and str(node_id) != ""
    }
    node_by_id = {
        str(node.node_id): node
        for node in finalization_context.association_context.step1_context.rcsd_nodes
    }
    seen_ids: set[str] = set()
    members: list[NodeRecord] = []

    def add_member_id(node_id: object, *, group_id: str) -> None:
        node_key = str(node_id)
        if node_key in seen_ids or node_key in overflow_ids:
            return
        if group_id in terminal_group_ids and node_key not in local_required_ids:
            return
        node = node_by_id.get(node_key)
        if node is None:
            return
        seen_ids.add(node_key)
        members.append(node)

    audited_group_ids: set[str] = set()
    for group_id, row in gate_audit.items():
        group_key = str(group_id)
        required_member_ids = {
            str(node_id)
            for node_id in (row.get("required_member_rcsdnode_ids") or [])
            if node_id is not None and str(node_id) != ""
        }
        if group_key not in required_group_ids and not (required_member_ids & local_required_ids):
            continue
        audited_group_ids.add(group_key)
        if group_key in terminal_group_ids:
            member_ids = required_member_ids
        else:
            member_ids = {
                str(node_id)
                for node_id in (row.get("member_rcsdnode_ids") or required_member_ids)
                if node_id is not None and str(node_id) != ""
            }
        for node_id in member_ids:
            add_member_id(node_id, group_id=group_key)

    for group_id, row in related_group_audit.items():
        group_key = str(group_id)
        if group_key in audited_group_ids:
            continue
        member_ids = {
            str(node_id)
            for node_id in (row.get("member_rcsdnode_ids") or [])
            if node_id is not None and str(node_id) != ""
        }
        if group_key not in required_group_ids and not (member_ids & local_required_ids):
            continue
        for node_id in member_ids:
            add_member_id(node_id, group_id=group_key)

    for node in finalization_context.association_context.step1_context.rcsd_nodes:
        if node.node_id not in candidate_ids and node.node_id not in local_required_ids:
            continue
        group_id = _semantic_group_id(node)
        if group_id in required_group_ids:
            add_member_id(node.node_id, group_id=group_id)

    for node in local_required_items:
        add_member_id(node.node_id, group_id=_semantic_group_id(node))
    return members

def _semantic_intra_rcsdnode_line_geometry(nodes: Iterable[NodeRecord]) -> BaseGeometry | None:
    groups: dict[str, list[NodeRecord]] = defaultdict(list)
    for node in nodes:
        groups[_semantic_group_id(node)].append(node)
    lines: list[LineString] = []
    for group_nodes in groups.values():
        for index, left in enumerate(group_nodes):
            left_point = left.geometry if isinstance(left.geometry, Point) else left.geometry.representative_point()
            for right in group_nodes[index + 1:]:
                right_point = right.geometry if isinstance(right.geometry, Point) else right.geometry.representative_point()
                if left_point.distance(right_point) <= 1e-6:
                    continue
                lines.append(LineString([(left_point.x, left_point.y), (right_point.x, right_point.y)]))
    return _union_geometries(lines)

def _semantic_intra_rcsdnode_line_count(nodes: Iterable[NodeRecord]) -> int:
    groups: dict[str, int] = defaultdict(int)
    for node in nodes:
        groups[_semantic_group_id(node)] += 1
    return sum(count * (count - 1) // 2 for count in groups.values())

def _selected_road_records(finalization_context: FinalizationContext) -> list[RoadRecord]:
    selected_ids = set(finalization_context.association_context.selected_road_ids)
    return [road for road in finalization_context.association_context.step1_context.roads if road.road_id in selected_ids]

def _single_sided_horizontal_pair_ids(finalization_context: FinalizationContext) -> set[str]:
    association_context = finalization_context.association_context
    if association_context.template_result.template_class != "single_sided_t_mouth":
        return set()
    return {
        str(item)
        for item in (association_context.step3_status_doc.get("single_sided_horizontal_pair_road_ids") or [])
        if item is not None and str(item) != ""
    }

def _required_road_records(finalization_context: FinalizationContext) -> list[RoadRecord]:
    step1 = finalization_context.association_context.step1_context
    required_ids = set(finalization_context.association_case_result.extra_status_fields.get("required_rcsdroad_ids") or [])
    return [road for road in step1.rcsd_roads if road.road_id in required_ids]

def _single_sided_vertical_exit_geometry(
    finalization_context: FinalizationContext,
    *,
    geometry_cache: _Step6GeometryCache | None = None,
) -> BaseGeometry | None:
    if geometry_cache is not None and geometry_cache.single_sided_vertical_exit_geometry_ready:
        return geometry_cache.single_sided_vertical_exit_geometry
    association_context = finalization_context.association_context
    if association_context.template_result.template_class != "single_sided_t_mouth":
        return None
    horizontal_pair_ids = _single_sided_horizontal_pair_ids(finalization_context)
    exit_geometries = [
        road.geometry
        for road in association_context.step1_context.roads
        if road.road_id in set(association_context.selected_road_ids) and road.road_id not in horizontal_pair_ids
    ]
    geometry = _union_geometries(exit_geometries)
    if geometry_cache is not None:
        geometry_cache.single_sided_vertical_exit_geometry = geometry
        geometry_cache.single_sided_vertical_exit_geometry_ready = True
    return geometry

def _allowed_space_tolerance_geometry(
    allowed_space: BaseGeometry | None,
    *,
    geometry_cache: _Step6GeometryCache | None,
) -> BaseGeometry | None:
    if allowed_space is None:
        return None
    if geometry_cache is not None and geometry_cache.allowed_space_tolerance_ready:
        return geometry_cache.allowed_space_tolerance_geometry
    geometry = _clean_geometry(allowed_space.buffer(LEGAL_SPACE_TOLERANCE_M))
    if geometry_cache is not None:
        geometry_cache.allowed_space_tolerance_geometry = geometry
        geometry_cache.allowed_space_tolerance_ready = True
    return geometry

def _local_required_node_records(
    finalization_context: FinalizationContext,
    boundary_geometry: BaseGeometry | None,
    *,
    geometry_cache: _Step6GeometryCache | None = None,
) -> list[NodeRecord]:
    boundary_buffer = _cached_boundary_buffer(
        boundary_geometry,
        NODE_COVER_TOLERANCE_M,
        geometry_cache=geometry_cache,
    )
    if boundary_buffer is None:
        return []
    return [
        node
        for node in _required_node_records(finalization_context)
        if boundary_buffer.intersects(node.geometry)
    ]

def _local_required_road_records(
    finalization_context: FinalizationContext,
    boundary_geometry: BaseGeometry | None,
    *,
    geometry_cache: _Step6GeometryCache | None = None,
) -> list[RoadRecord]:
    boundary_buffer = _cached_boundary_buffer(
        boundary_geometry,
        LINE_COVER_BUFFER_M,
        geometry_cache=geometry_cache,
    )
    if boundary_buffer is None:
        return []
    return [
        road
        for road in _required_road_records(finalization_context)
        if boundary_buffer.intersects(road.geometry)
    ]

def _local_required_road_geometry(
    finalization_context: FinalizationContext,
    boundary_geometry: BaseGeometry | None,
    *,
    geometry_cache: _Step6GeometryCache | None = None,
) -> BaseGeometry | None:
    boundary_buffer = _cached_boundary_buffer(
        boundary_geometry,
        LINE_COVER_BUFFER_M,
        geometry_cache=geometry_cache,
    )
    if boundary_buffer is None:
        return None
    required_geometry = _clean_geometry(
        finalization_context.association_case_result.output_geometries.required_rcsdroad_geometry
    )
    if required_geometry is None:
        return None
    return _clean_geometry(required_geometry.intersection(boundary_buffer))
