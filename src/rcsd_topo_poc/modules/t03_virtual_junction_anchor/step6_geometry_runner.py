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

from .step6_geometry import (
    _build_directional_cut_geometry,
    _single_sided_horizontal_trace_decisions,
    _single_sided_strong_node_keep_geometry,
    _single_sided_trace_candidate_rcsdroad_records,
    _single_sided_trace_reachable_endpoint_nodes,
)

def _step6_failure_result(
    *,
    finalization_context: FinalizationContext,
    reason: str,
    primary_root_cause: str,
    secondary_root_cause: str,
    review_signals: Iterable[str] = (),
    output_geometries: Step6OutputGeometries | None = None,
    key_metrics: dict[str, Any] | None = None,
    audit_doc: dict[str, Any] | None = None,
    extra_status_fields: dict[str, Any] | None = None,
) -> Step6Result:
    return Step6Result(
        step6_state="not_established",
        geometry_established=False,
        problem_geometry=True,
        reason=reason,
        primary_root_cause=primary_root_cause,
        secondary_root_cause=secondary_root_cause,
        review_signals=tuple(review_signals),
        output_geometries=output_geometries
        or Step6OutputGeometries(
            polygon_seed_geometry=None,
            polygon_final_geometry=None,
            foreign_mask_geometry=None,
            must_cover_geometry=None,
        ),
        key_metrics=key_metrics or {},
        audit_doc=audit_doc or {},
        extra_status_fields=extra_status_fields or {},
    )

def build_step6_result(
    finalization_context: FinalizationContext,
    *,
    stage_timers: dict[str, float] | None = None,
    use_step6_geometry_cache: bool = True,
) -> Step6Result:
    association_context = finalization_context.association_context
    association_case_result = finalization_context.association_case_result
    step1 = association_context.step1_context
    template_class = association_case_result.template_class
    geometry_cache = _Step6GeometryCache() if use_step6_geometry_cache else None
    allowed_space = _clean_geometry(association_context.step3_allowed_space_geometry)
    if allowed_space is None:
        return _step6_failure_result(
            finalization_context=finalization_context,
            reason="step6_missing_allowed_space",
            primary_root_cause=PRIMARY_INFEASIBLE,
            secondary_root_cause=SECONDARY_STEP1_STEP3_CONFLICT,
        )
    if association_case_result.association_state == "not_established":
        return _step6_failure_result(
            finalization_context=finalization_context,
            reason="step6_blocked_by_association",
            primary_root_cause=PRIMARY_INFEASIBLE,
            secondary_root_cause=SECONDARY_STEP1_STEP3_CONFLICT,
            extra_status_fields={
                "association_reason": association_case_result.reason,
                "association_state": association_case_result.association_state,
            },
        )
    mask_prep_started_perf = perf_counter()
    allowed_space_tolerance_geometry = _allowed_space_tolerance_geometry(
        allowed_space,
        geometry_cache=geometry_cache,
    )
    target_cover_geometry = _point_buffers(step1.target_group.nodes, TARGET_NODE_BUFFER_M)
    step3_two_node_t_bridge_geometry = _step3_two_node_t_bridge_geometry(
        finalization_context,
        allowed_space,
    )
    target_node_connection_line_geometry = _target_node_connection_line_geometry(finalization_context)
    target_node_connection_required = step3_two_node_t_bridge_geometry is not None
    target_node_connection_bridge_geometry = (
        step3_two_node_t_bridge_geometry if target_node_connection_required else None
    )
    support_only_seam_bridge_geometry = _support_only_seam_bridge_geometry(
        finalization_context,
        allowed_space_tolerance_geometry,
        geometry_cache=geometry_cache,
    )
    foreign_mask_geometry, foreign_mask_sources = _build_foreign_mask_geometry(
        finalization_context,
        geometry_cache=geometry_cache,
    )
    _accumulate_stage_timer(stage_timers, "step6_mask_prep", perf_counter() - mask_prep_started_perf)

    directional_cut_started_perf = perf_counter()
    direction_clip_geometry, selected_road_core_geometry, directional_cut_branches = _build_directional_cut_geometry(
        finalization_context,
        allowed_space,
        geometry_cache=geometry_cache,
        step3_two_node_t_bridge_geometry=step3_two_node_t_bridge_geometry,
    )
    strong_node_keep_geometry = _single_sided_strong_node_keep_geometry(finalization_context)
    polygon_seed_geometry = _clean_geometry(
        allowed_space.intersection(direction_clip_geometry) if direction_clip_geometry is not None else None
    )
    target_connected_boundary_fallback_applied = False
    if (
        association_case_result.template_class == "single_sided_t_mouth"
        and _node_cover_ratio(step1.target_group.nodes, polygon_seed_geometry) < 1.0
    ):
        direction_clip_geometry, selected_road_core_geometry, directional_cut_branches = _build_directional_cut_geometry(
            finalization_context,
            allowed_space,
            geometry_cache=geometry_cache,
            step3_two_node_t_bridge_geometry=step3_two_node_t_bridge_geometry,
            force_preserve_single_sided_horizontal_pair=True,
        )
        polygon_seed_geometry = _clean_geometry(
            allowed_space.intersection(direction_clip_geometry) if direction_clip_geometry is not None else None
        )
        target_connected_boundary_fallback_applied = True
    if (
        association_case_result.template_class == "single_sided_t_mouth"
        and _node_cover_ratio(step1.target_group.nodes, polygon_seed_geometry) < 1.0
    ):
        direction_clip_geometry, selected_road_core_geometry, directional_cut_branches = _build_directional_cut_geometry(
            finalization_context,
            allowed_space,
            geometry_cache=geometry_cache,
            step3_two_node_t_bridge_geometry=step3_two_node_t_bridge_geometry,
            force_preserve_all_branches=True,
        )
        polygon_seed_geometry = _clean_geometry(
            allowed_space.intersection(direction_clip_geometry) if direction_clip_geometry is not None else None
        )
        target_connected_boundary_fallback_applied = True
    _accumulate_stage_timer(stage_timers, "step6_directional_cut", perf_counter() - directional_cut_started_perf)
    if polygon_seed_geometry is None:
        return _step6_failure_result(
            finalization_context=finalization_context,
            reason="step6_polygon_seed_empty",
            primary_root_cause=PRIMARY_SOLVER_FAILED,
            secondary_root_cause=SECONDARY_CLOSURE_FAILURE,
            output_geometries=Step6OutputGeometries(
                polygon_seed_geometry=None,
                polygon_final_geometry=None,
                foreign_mask_geometry=foreign_mask_geometry,
                must_cover_geometry=_union_geometries(
                    [
                        target_cover_geometry,
                        target_node_connection_bridge_geometry,
                        step3_two_node_t_bridge_geometry,
                    ]
                ),
            ),
        )

    finalize_started_perf = perf_counter()

    def _complete_step6_result(
        result: Step6Result,
        *,
        status_started_perf: float | None = None,
    ) -> Step6Result:
        if status_started_perf is not None:
            _accumulate_stage_timer(
                stage_timers,
                "step6_finalize_status",
                perf_counter() - status_started_perf,
            )
        _accumulate_stage_timer(stage_timers, "step6_finalize", perf_counter() - finalize_started_perf)
        return result

    cleanup_started_perf = perf_counter()
    direction_boundary_geometry = _union_geometries(
        [
            polygon_seed_geometry,
            target_node_connection_bridge_geometry,
            step3_two_node_t_bridge_geometry,
            support_only_seam_bridge_geometry,
        ]
    )
    local_required_nodes = _local_required_node_records(
        finalization_context,
        direction_boundary_geometry,
        geometry_cache=geometry_cache,
    )
    local_required_road_records = _local_required_road_records(
        finalization_context,
        direction_boundary_geometry,
        geometry_cache=geometry_cache,
    )
    local_required_road_geometry = _local_required_road_geometry(
        finalization_context,
        direction_boundary_geometry,
        geometry_cache=geometry_cache,
    )
    local_required_semantic_members = _local_required_semantic_member_records(
        finalization_context,
        local_required_nodes,
    )
    semantic_intra_line_geometry = _semantic_intra_rcsdnode_line_geometry(local_required_semantic_members)
    semantic_intra_line_cover_geometry = _cached_line_buffers(
        semantic_intra_line_geometry,
        SEMANTIC_INTRA_LINE_BUFFER_M,
        geometry_cache=geometry_cache,
    )
    if semantic_intra_line_cover_geometry is not None:
        direction_boundary_geometry = _union_geometries(
            [direction_boundary_geometry, semantic_intra_line_cover_geometry]
        )
    required_node_cover_geometry = _point_buffers(local_required_nodes, REQUIRED_NODE_BUFFER_M)
    required_road_cover_geometry = _cached_line_buffers(
        local_required_road_geometry,
        REQUIRED_ROAD_BUFFER_M,
        geometry_cache=geometry_cache,
    )
    must_cover_geometry = _union_geometries(
        [
            target_cover_geometry,
            target_node_connection_bridge_geometry,
            step3_two_node_t_bridge_geometry,
            support_only_seam_bridge_geometry,
            required_node_cover_geometry,
            required_road_cover_geometry,
            semantic_intra_line_cover_geometry,
        ]
    )
    anchor_geometries = [
        target_cover_geometry,
        target_node_connection_bridge_geometry,
        step3_two_node_t_bridge_geometry,
        support_only_seam_bridge_geometry,
        required_node_cover_geometry,
        required_road_cover_geometry,
        semantic_intra_line_cover_geometry,
    ]
    anchor_union_geometry = _union_geometries(anchor_geometries)
    anchor_keep_geometry = (
        _clean_geometry(anchor_union_geometry.buffer(NODE_COVER_TOLERANCE_M))
        if anchor_union_geometry is not None
        else None
    )

    raw_polygon = _clean_geometry(
        _union_geometries(
            [
                polygon_seed_geometry,
                target_cover_geometry,
                target_node_connection_bridge_geometry,
                step3_two_node_t_bridge_geometry,
                support_only_seam_bridge_geometry,
                required_node_cover_geometry,
                required_road_cover_geometry,
                semantic_intra_line_cover_geometry,
            ]
        )
    )
    raw_polygon = _clean_geometry(raw_polygon.intersection(allowed_space_tolerance_geometry))
    raw_polygon = _clean_geometry(raw_polygon.intersection(direction_boundary_geometry))
    raw_polygon = _retain_components_touching_keep_geometry(raw_polygon, anchor_keep_geometry)
    pre_cleanup_polygon = raw_polygon
    if raw_polygon is None:
        _accumulate_stage_timer(stage_timers, "step6_finalize_cleanup", perf_counter() - cleanup_started_perf)
        status_started_perf = perf_counter()
        return _complete_step6_result(
            _step6_failure_result(
                finalization_context=finalization_context,
                reason="step6_polygon_empty_after_legal_clip",
                primary_root_cause=PRIMARY_INFEASIBLE,
                secondary_root_cause=SECONDARY_STEP1_STEP3_CONFLICT,
                output_geometries=Step6OutputGeometries(
                    polygon_seed_geometry=polygon_seed_geometry,
                    polygon_final_geometry=None,
                    foreign_mask_geometry=foreign_mask_geometry,
                    must_cover_geometry=must_cover_geometry,
                ),
            ),
            status_started_perf=status_started_perf,
        )

    support_only_tiny_fragment_pruned = False
    final_polygon = raw_polygon
    if foreign_mask_geometry is not None:
        final_polygon = _clean_geometry(final_polygon.difference(foreign_mask_geometry))
        final_polygon = _retain_components_touching_keep_geometry(final_polygon, anchor_keep_geometry)
    final_polygon = _clean_geometry(final_polygon)
    if final_polygon is not None:
        final_polygon = _clean_geometry(
            final_polygon.buffer(FINAL_CLOSE_M).buffer(-FINAL_CLOSE_M)
        )
        final_polygon = _clean_geometry(final_polygon.intersection(allowed_space_tolerance_geometry))
        final_polygon = _clean_geometry(final_polygon.intersection(direction_boundary_geometry))
        final_polygon = _retain_components_touching_keep_geometry(final_polygon, anchor_keep_geometry)
    if final_polygon is not None and foreign_mask_geometry is not None:
        final_polygon = _clean_geometry(final_polygon.difference(foreign_mask_geometry))
        final_polygon = _retain_components_touching_keep_geometry(final_polygon, anchor_keep_geometry)
    if final_polygon is not None and semantic_intra_line_cover_geometry is not None:
        final_polygon = _clean_geometry(_union_geometries([final_polygon, semantic_intra_line_cover_geometry]))
        final_polygon = _clean_geometry(final_polygon.intersection(allowed_space_tolerance_geometry))
        final_polygon = _clean_geometry(final_polygon.intersection(direction_boundary_geometry))
        final_polygon = _retain_components_touching_keep_geometry(final_polygon, anchor_keep_geometry)
        if final_polygon is not None and foreign_mask_geometry is not None:
            final_polygon = _clean_geometry(final_polygon.difference(foreign_mask_geometry))
            final_polygon = _retain_components_touching_keep_geometry(final_polygon, anchor_keep_geometry)
    if final_polygon is not None:
        final_polygon, support_only_tiny_fragment_pruned = _prune_support_only_tiny_fragments(
            finalization_context,
            final_polygon,
            geometry_cache=geometry_cache,
        )
    _accumulate_stage_timer(stage_timers, "step6_finalize_cleanup", perf_counter() - cleanup_started_perf)

    validation_started_perf = perf_counter()
    final_node_cover_geometry = _cached_boundary_buffer(
        final_polygon,
        NODE_COVER_TOLERANCE_M,
        geometry_cache=geometry_cache,
    )
    raw_node_cover_geometry = _cached_boundary_buffer(
        pre_cleanup_polygon,
        NODE_COVER_TOLERANCE_M,
        geometry_cache=geometry_cache,
    )
    final_line_cover_geometry = _cached_boundary_buffer(
        final_polygon,
        LINE_COVER_BUFFER_M,
        geometry_cache=geometry_cache,
    )
    raw_line_cover_geometry = _cached_boundary_buffer(
        pre_cleanup_polygon,
        LINE_COVER_BUFFER_M,
        geometry_cache=geometry_cache,
    )
    target_node_cover_ratio = _target_node_cover_ratio_with_cover_geometry(
        finalization_context,
        final_node_cover_geometry,
    )
    selected_core_cover_ratio = _line_coverage_ratio_with_cover_geometry(
        selected_road_core_geometry,
        final_line_cover_geometry,
    )
    target_node_connection_cover_ratio = _line_coverage_ratio_with_cover_geometry(
        target_node_connection_line_geometry,
        final_line_cover_geometry,
    )
    required_rc_node_cover_ratio = _node_cover_ratio_with_cover_geometry(
        local_required_nodes,
        final_node_cover_geometry,
    )
    required_rc_line_cover_ratio = _line_coverage_ratio_with_cover_geometry(
        local_required_road_geometry,
        final_line_cover_geometry,
    )
    semantic_intra_line_cover_ratio = _line_coverage_ratio_with_cover_geometry(
        semantic_intra_line_geometry,
        final_polygon,
    )
    semantic_intra_line_cover_ok = semantic_intra_line_cover_ratio >= 0.999999
    semantic_junction_cover_ok = (
        target_node_cover_ratio >= 1.0
        and (
            not target_node_connection_required
            or target_node_connection_cover_ratio >= TARGET_NODE_CONNECTION_MIN_RATIO
        )
        and selected_core_cover_ratio >= SELECTED_ROAD_CORE_MIN_RATIO
        and semantic_intra_line_cover_ok
    )
    required_rc_cover_ok = (
        required_rc_node_cover_ratio >= 1.0
        and required_rc_line_cover_ratio >= LINE_COVER_MIN_RATIO
        and semantic_intra_line_cover_ok
    )
    legal_escape_area_m2 = 0.0
    direction_escape_area_m2 = 0.0
    if final_polygon is not None:
        legal_escape_area_m2 = final_polygon.difference(allowed_space_tolerance_geometry).area
        direction_escape_area_m2 = final_polygon.difference(direction_boundary_geometry).area
    within_legal_space_ok = bool(final_polygon is not None and legal_escape_area_m2 <= 1e-6)
    within_direction_boundary_ok = bool(final_polygon is not None and direction_escape_area_m2 <= 1e-6)
    foreign_overlap_area_m2 = 0.0
    if final_polygon is not None and foreign_mask_geometry is not None:
        foreign_overlap_area_m2 = final_polygon.intersection(foreign_mask_geometry).area
    foreign_exclusion_ok = foreign_overlap_area_m2 <= FOREIGN_OVERLAP_TOLERANCE_M2

    raw_target_cover_ratio = _target_node_cover_ratio_with_cover_geometry(
        finalization_context,
        raw_node_cover_geometry,
    )
    raw_required_rc_cover_ratio = _line_coverage_ratio_with_cover_geometry(
        local_required_road_geometry,
        raw_line_cover_geometry,
    )
    raw_target_node_connection_cover_ratio = _line_coverage_ratio_with_cover_geometry(
        target_node_connection_line_geometry,
        raw_line_cover_geometry,
    )
    review_signals: list[str] = []
    shape_metrics = _cached_shape_metrics(final_polygon, geometry_cache=geometry_cache)
    target_anchor_geometry = _target_anchor_geometry(finalization_context, geometry_cache=geometry_cache)
    component_target_distances_m = [
        polygon.distance(target_anchor_geometry)
        for polygon in _iter_polygons(final_polygon)
        if target_anchor_geometry is not None
    ]
    max_component_target_distance_m = max(component_target_distances_m, default=0.0)
    polygon_seed_metrics = _cached_shape_metrics(polygon_seed_geometry, geometry_cache=geometry_cache)
    pre_cleanup_metrics = _cached_shape_metrics(pre_cleanup_polygon, geometry_cache=geometry_cache)
    direction_clip_metrics = _cached_shape_metrics(direction_clip_geometry, geometry_cache=geometry_cache)
    bridge_metrics = _cached_shape_metrics(step3_two_node_t_bridge_geometry, geometry_cache=geometry_cache)
    target_node_connection_bridge_metrics = _cached_shape_metrics(
        target_node_connection_bridge_geometry,
        geometry_cache=geometry_cache,
    )
    support_only_seam_bridge_metrics = _cached_shape_metrics(
        support_only_seam_bridge_geometry,
        geometry_cache=geometry_cache,
    )
    if shape_metrics["hole_count"] > 0:
        review_signals.append("polygon_has_holes")
    if shape_metrics["component_count"] > 1:
        review_signals.append("polygon_multicomponent")
    pre_cleanup_foreign_overlap_area_m2 = 0.0
    if pre_cleanup_polygon is not None and foreign_mask_geometry is not None:
        pre_cleanup_foreign_overlap_area_m2 = pre_cleanup_polygon.intersection(foreign_mask_geometry).area
    _accumulate_stage_timer(stage_timers, "step6_finalize_validation", perf_counter() - validation_started_perf)

    base_audit_doc = {
        "inputs": {
            "template_class": template_class,
            "association_class": association_case_result.association_class,
            "association_state": association_case_result.association_state,
            "association_reason": association_case_result.reason,
            "step3_state": association_context.step3_status_doc.get("step3_state"),
            "selected_road_ids": list(association_context.selected_road_ids),
            "required_rcsdnode_ids": list(association_case_result.extra_status_fields.get("required_rcsdnode_ids") or []),
            "required_rcsdroad_ids": list(association_case_result.extra_status_fields.get("required_rcsdroad_ids") or []),
            "related_rcsdnode_ids": list(association_case_result.extra_status_fields.get("related_rcsdnode_ids") or []),
            "related_rcsdroad_ids": list(association_case_result.extra_status_fields.get("related_rcsdroad_ids") or []),
            "related_local_rcsdroad_ids": list(
                association_case_result.extra_status_fields.get("related_local_rcsdroad_ids") or []
            ),
            "related_group_rcsdroad_ids": list(
                association_case_result.extra_status_fields.get("related_group_rcsdroad_ids") or []
            ),
            "related_outside_scope_rcsdroad_ids": list(
                association_case_result.extra_status_fields.get("related_outside_scope_rcsdroad_ids") or []
            ),
            "t_mouth_strong_related_rcsdnode_ids": list(
                association_case_result.extra_status_fields.get("t_mouth_strong_related_rcsdnode_ids") or []
            ),
            "t_mouth_strong_related_overflow_rcsdnode_ids": list(
                association_case_result.extra_status_fields.get("t_mouth_strong_related_overflow_rcsdnode_ids") or []
            ),
            "local_required_rcsdnode_ids": [node.node_id for node in local_required_nodes],
            "local_required_rcsdroad_ids": [road.road_id for road in local_required_road_records],
            "support_rcsdroad_ids": list(association_case_result.extra_status_fields.get("support_rcsdroad_ids") or []),
            "excluded_rcsdroad_ids": list(association_case_result.extra_status_fields.get("excluded_rcsdroad_ids") or []),
            "foreign_mask_source_rcsdroad_ids": list(
                association_case_result.extra_status_fields.get("foreign_mask_source_rcsdroad_ids") or []
            ),
        },
        "assembly": {
            "geometry_mode": "directional_selected_road_cut",
            "polygon_seed_metrics": polygon_seed_metrics,
            "polygon_after_legal_clip_metrics": pre_cleanup_metrics,
            "polygon_final_metrics": shape_metrics,
            "direction_clip_metrics": direction_clip_metrics,
            "step3_two_node_t_bridge_inherited": step3_two_node_t_bridge_geometry is not None,
            "step3_two_node_t_bridge_metrics": bridge_metrics,
            "target_node_connection_bridge_applied": target_node_connection_bridge_geometry is not None,
            "target_node_connection_required": target_node_connection_required,
            "target_node_connection_bridge_buffer_m": STEP3_TWO_NODE_T_BRIDGE_BUFFER_M,
            "target_node_connection_bridge_metrics": target_node_connection_bridge_metrics,
            "target_node_connection_length_m": round(
                sum(line.length for line in _iter_lines(target_node_connection_line_geometry)),
                6,
            ),
            "single_sided_strong_node_keep_applied": strong_node_keep_geometry is not None,
            "single_sided_strong_node_keep_buffer_m": REQUIRED_NODE_BUFFER_M,
            "single_sided_strong_node_keep_metrics": _cached_shape_metrics(
                strong_node_keep_geometry,
                geometry_cache=geometry_cache,
            ),
            "support_only_seam_bridge_applied": support_only_seam_bridge_geometry is not None,
            "support_only_seam_bridge_buffer_m": SUPPORT_ONLY_SEAM_BRIDGE_BUFFER_M,
            "support_only_seam_bridge_metrics": support_only_seam_bridge_metrics,
            "support_only_tiny_fragment_pruned": support_only_tiny_fragment_pruned,
            "directional_cut_rule": {
                "mode": "directional_selected_road_cut",
                "cut_distance_m": DIRECTIONAL_CUT_DISTANCE_M,
                "branch_count": len(directional_cut_branches),
            },
            "directional_cut_branches": directional_cut_branches,
            "target_connected_boundary_fallback_applied": target_connected_boundary_fallback_applied,
            "direction_boundary_hard_cap_applied": True,
            "final_close_m": FINAL_CLOSE_M,
            "foreign_mask_buffer_m": FOREIGN_MASK_BUFFER_M,
            "foreign_mask_mode": "road_like_1m_mask",
            "foreign_mask_sources": foreign_mask_sources,
        },
        "validation": {
            "semantic_junction_cover_ok": semantic_junction_cover_ok,
            "target_node_cover_ratio": round(target_node_cover_ratio, 6),
            "target_node_connection_cover_ratio": round(target_node_connection_cover_ratio, 6),
            "target_node_connection_required": target_node_connection_required,
            "target_node_connection_min_ratio": TARGET_NODE_CONNECTION_MIN_RATIO,
            "selected_road_core_cover_ratio": round(selected_core_cover_ratio, 6),
            "required_rc_cover_ok": required_rc_cover_ok,
            "required_rc_node_cover_ratio": round(required_rc_node_cover_ratio, 6),
            "required_rc_line_cover_ratio": round(required_rc_line_cover_ratio, 6),
            "semantic_intra_rcsdnode_line_cover_ratio": round(semantic_intra_line_cover_ratio, 6),
            "semantic_intra_rcsdnode_line_cover_ok": semantic_intra_line_cover_ok,
            "semantic_intra_rcsdnode_line_count": _semantic_intra_rcsdnode_line_count(
                local_required_semantic_members
            ),
            "within_legal_space_ok": within_legal_space_ok,
            "within_direction_boundary_ok": within_direction_boundary_ok,
            "foreign_exclusion_ok": foreign_exclusion_ok,
            "foreign_overlap_area_m2": round(foreign_overlap_area_m2, 6),
            "max_component_target_distance_m": round(max_component_target_distance_m, 6),
            "raw_target_node_cover_ratio": round(raw_target_cover_ratio, 6),
            "raw_target_node_connection_cover_ratio": round(raw_target_node_connection_cover_ratio, 6),
            "raw_required_rc_line_cover_ratio": round(raw_required_rc_cover_ratio, 6),
            "required_rc_cover_mode": "local_required_rc_within_direction_boundary",
        },
    }
    output_geometries = Step6OutputGeometries(
        polygon_seed_geometry=polygon_seed_geometry,
        polygon_final_geometry=final_polygon,
        foreign_mask_geometry=foreign_mask_geometry,
        must_cover_geometry=must_cover_geometry,
    )
    key_metrics = {
        **shape_metrics,
        "target_node_cover_ratio": round(target_node_cover_ratio, 6),
        "target_node_connection_cover_ratio": round(target_node_connection_cover_ratio, 6),
        "target_node_connection_required": target_node_connection_required,
        "selected_road_core_cover_ratio": round(selected_core_cover_ratio, 6),
        "required_rc_node_cover_ratio": round(required_rc_node_cover_ratio, 6),
        "required_rc_line_cover_ratio": round(required_rc_line_cover_ratio, 6),
        "semantic_intra_rcsdnode_line_cover_ratio": round(semantic_intra_line_cover_ratio, 6),
        "foreign_overlap_area_m2": round(foreign_overlap_area_m2, 6),
        "max_component_target_distance_m": round(max_component_target_distance_m, 6),
    }
    extra_status_fields = {
        "semantic_junction_cover_ok": semantic_junction_cover_ok,
        "required_rc_cover_ok": required_rc_cover_ok,
        "within_legal_space_ok": within_legal_space_ok,
        "within_direction_boundary_ok": within_direction_boundary_ok,
        "foreign_exclusion_ok": foreign_exclusion_ok,
        "target_node_cover_ratio": round(target_node_cover_ratio, 6),
        "target_node_connection_cover_ratio": round(target_node_connection_cover_ratio, 6),
        "target_node_connection_required": target_node_connection_required,
        "selected_road_core_cover_ratio": round(selected_core_cover_ratio, 6),
        "required_rc_node_cover_ratio": round(required_rc_node_cover_ratio, 6),
        "required_rc_line_cover_ratio": round(required_rc_line_cover_ratio, 6),
        "semantic_intra_rcsdnode_line_cover_ratio": round(semantic_intra_line_cover_ratio, 6),
        "semantic_intra_rcsdnode_line_cover_ok": semantic_intra_line_cover_ok,
        "semantic_intra_rcsdnode_line_count": _semantic_intra_rcsdnode_line_count(
            local_required_semantic_members
        ),
        "foreign_overlap_area_m2": round(foreign_overlap_area_m2, 6),
        "max_component_target_distance_m": round(max_component_target_distance_m, 6),
        "required_rcsdnode_ids": list(association_case_result.extra_status_fields.get("required_rcsdnode_ids") or []),
        "required_rcsdroad_ids": list(association_case_result.extra_status_fields.get("required_rcsdroad_ids") or []),
        "support_rcsdnode_ids": list(association_case_result.extra_status_fields.get("support_rcsdnode_ids") or []),
        "support_rcsdroad_ids": list(association_case_result.extra_status_fields.get("support_rcsdroad_ids") or []),
        "related_rcsdnode_ids": list(association_case_result.extra_status_fields.get("related_rcsdnode_ids") or []),
        "related_rcsdroad_ids": list(association_case_result.extra_status_fields.get("related_rcsdroad_ids") or []),
        "related_local_rcsdroad_ids": list(association_case_result.extra_status_fields.get("related_local_rcsdroad_ids") or []),
        "related_group_rcsdroad_ids": list(
            association_case_result.extra_status_fields.get("related_group_rcsdroad_ids") or []
        ),
        "related_outside_scope_rcsdroad_ids": list(
            association_case_result.extra_status_fields.get("related_outside_scope_rcsdroad_ids") or []
        ),
        "local_required_rcsdnode_ids": [node.node_id for node in local_required_nodes],
        "local_required_rcsdroad_ids": [road.road_id for road in local_required_road_records],
        "foreign_mask_source_rcsdroad_ids": list(
            association_case_result.extra_status_fields.get("foreign_mask_source_rcsdroad_ids") or []
        ),
    }

    def _complete_failure_result(
        *,
        reason: str,
        primary_root_cause: str,
        secondary_root_cause: str,
        review_signals_for_result: Iterable[str] = (),
    ) -> Step6Result:
        status_started_perf = perf_counter()
        return _complete_step6_result(
            _step6_failure_result(
                finalization_context=finalization_context,
                reason=reason,
                primary_root_cause=primary_root_cause,
                secondary_root_cause=secondary_root_cause,
                review_signals=review_signals_for_result,
                output_geometries=output_geometries,
                key_metrics=key_metrics,
                audit_doc={
                    **base_audit_doc,
                    "decision": {
                        "reason": reason,
                        "primary_root_cause": primary_root_cause,
                        "secondary_root_cause": secondary_root_cause,
                    },
                },
                extra_status_fields=extra_status_fields,
            ),
            status_started_perf=status_started_perf,
        )

    if final_polygon is None:
        return _complete_failure_result(
            reason="step6_polygon_lost_after_cleanup",
            primary_root_cause=PRIMARY_SOLVER_FAILED,
            secondary_root_cause=SECONDARY_CLEANUP_OVERTRIM,
        )

    if not semantic_junction_cover_ok:
        secondary = (
            SECONDARY_CLEANUP_OVERTRIM
            if raw_target_cover_ratio >= 1.0
            and (
                not target_node_connection_required
                or raw_target_node_connection_cover_ratio >= TARGET_NODE_CONNECTION_MIN_RATIO
            )
            else SECONDARY_STEP1_STEP3_CONFLICT
        )
        primary = (
            PRIMARY_SOLVER_FAILED
            if secondary == SECONDARY_CLEANUP_OVERTRIM
            else PRIMARY_INFEASIBLE
        )
        return _complete_failure_result(
            reason="step6_semantic_junction_not_covered",
            primary_root_cause=primary,
            secondary_root_cause=secondary,
        )

    if not required_rc_cover_ok:
        secondary = (
            SECONDARY_CLEANUP_OVERTRIM
            if raw_required_rc_cover_ratio >= LINE_COVER_MIN_RATIO
            else SECONDARY_STAGE3_RC_GAP
        )
        primary = (
            PRIMARY_SOLVER_FAILED
            if secondary == SECONDARY_CLEANUP_OVERTRIM
            else PRIMARY_INFEASIBLE
        )
        return _complete_failure_result(
            reason="step6_required_rc_not_covered",
            primary_root_cause=primary,
            secondary_root_cause=secondary,
        )

    if not within_legal_space_ok:
        return _complete_failure_result(
            reason="step6_escaped_legal_space",
            primary_root_cause=PRIMARY_INFEASIBLE,
            secondary_root_cause=SECONDARY_STEP1_STEP3_CONFLICT,
        )

    if not foreign_exclusion_ok:
        secondary = (
            SECONDARY_FOREIGN_REINTRODUCED
            if pre_cleanup_foreign_overlap_area_m2 <= 1e-6
            else SECONDARY_FOREIGN_CONFLICT
        )
        return _complete_failure_result(
            reason="step6_foreign_intrusion_remains",
            primary_root_cause=PRIMARY_INFEASIBLE,
            secondary_root_cause=secondary,
        )

    severe_template_misfit = False
    severe_reason = None
    if template_class == "single_sided_t_mouth":
        # Boundary-first single-sided outputs can legitimately form two lobes.
        # Keep that as review-only unless the result is fragmented or too sparse
        # to represent a stable business geometry.
        component_count = int(shape_metrics["component_count"] or 0)
        compactness = shape_metrics["compactness"]
        aspect_ratio = shape_metrics["aspect_ratio"]
        bbox_fill_ratio = shape_metrics["bbox_fill_ratio"]
        support_only_fragmented = (
            association_case_result.reason == "association_support_only"
            and component_count >= 3
        )
        support_only_two_lobe_review = (
            association_case_result.reason == "association_support_only"
            and component_count == 2
            and max_component_target_distance_m <= SUPPORT_ONLY_SEAM_BRIDGE_BUFFER_M
            and (
                (
                    aspect_ratio is not None
                    and aspect_ratio >= 2.5
                    and bbox_fill_ratio is not None
                    and bbox_fill_ratio >= 0.4
                )
                or (
                    compactness is not None
                    and compactness >= 0.12
                    and bbox_fill_ratio is not None
                    and bbox_fill_ratio >= 0.11
                )
            )
            and semantic_junction_cover_ok
            and required_rc_cover_ok
            and within_legal_space_ok
            and within_direction_boundary_ok
            and foreign_exclusion_ok
        )
        severe_template_misfit = (
            support_only_fragmented
            or (
                not support_only_two_lobe_review
                and (
                    (compactness is not None and compactness < 0.12)
                    or (bbox_fill_ratio is not None and bbox_fill_ratio < 0.11)
                    or (component_count > 1 and compactness is not None and compactness < 0.16)
                )
            )
            or component_count > 3
        )
        severe_reason = "step6_single_sided_shape_artifact" if severe_template_misfit else None
    else:
        component_count = int(shape_metrics["component_count"] or 0)
        compactness = shape_metrics["compactness"]
        bbox_fill_ratio = shape_metrics["bbox_fill_ratio"]
        support_only_two_component_review = (
            association_case_result.reason == "association_support_only"
            and component_count == 2
            and max_component_target_distance_m <= SUPPORT_ONLY_SEAM_BRIDGE_BUFFER_M
            and compactness is not None
            and compactness >= 0.14
            and bbox_fill_ratio is not None
            and bbox_fill_ratio >= 0.12
            and semantic_junction_cover_ok
            and required_rc_cover_ok
            and within_legal_space_ok
            and within_direction_boundary_ok
            and foreign_exclusion_ok
        )
        severe_template_misfit = (
            (compactness is not None and compactness < 0.14)
            or (bbox_fill_ratio is not None and bbox_fill_ratio < 0.12)
            or (component_count > 1 and not support_only_two_component_review)
        )
        severe_reason = "step6_center_shape_artifact" if severe_template_misfit else None
    if severe_template_misfit:
        secondary = (
            SECONDARY_CLOSURE_FAILURE
            if shape_metrics["component_count"] > 1
            else SECONDARY_SHAPE_ARTIFACT
        )
        return _complete_failure_result(
            reason=severe_reason or "step6_shape_artifact",
            primary_root_cause=PRIMARY_SOLVER_FAILED,
            secondary_root_cause=secondary,
            review_signals_for_result=review_signals,
        )

    status_started_perf = perf_counter()
    return _complete_step6_result(
        Step6Result(
            step6_state="established",
            geometry_established=True,
            problem_geometry=bool(review_signals),
            reason="step6_geometry_established",
            primary_root_cause=None,
            secondary_root_cause=None,
            review_signals=tuple(review_signals),
            output_geometries=output_geometries,
            key_metrics=key_metrics,
            audit_doc={
                **base_audit_doc,
                "decision": {
                    "reason": "step6_geometry_established",
                    "primary_root_cause": None,
                    "secondary_root_cause": None,
                    "review_signals": list(review_signals),
                },
            },
            extra_status_fields=extra_status_fields,
        ),
        status_started_perf=status_started_perf,
    )

def build_step6_status_doc(finalization_context: FinalizationContext, step6_result: Step6Result) -> dict[str, Any]:
    association_case_result = finalization_context.association_case_result
    return {
        "case_id": finalization_context.association_context.step1_context.case_spec.case_id,
        "template_class": association_case_result.template_class,
        "association_class": association_case_result.association_class,
        "association_state": association_case_result.association_state,
        "step6_state": step6_result.step6_state,
        "geometry_established": step6_result.geometry_established,
        "problem_geometry": step6_result.problem_geometry,
        "reason": step6_result.reason,
        "primary_root_cause": step6_result.primary_root_cause,
        "secondary_root_cause": step6_result.secondary_root_cause,
        "review_signals": list(step6_result.review_signals),
        "key_metrics": step6_result.key_metrics,
        **step6_result.extra_status_fields,
    }
