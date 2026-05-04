from __future__ import annotations


from dataclasses import replace
from typing import Any

import numpy as np
from shapely.geometry import GeometryCollection
from shapely.geometry.base import BaseGeometry

from ._rcsd_selection_support import _normalize_geometry, _union_geometry
from ._runtime_polygon_cleanup import POLYGON_SMALL_HOLE_AREA_M2, _fill_small_polygon_holes, _polygon_components
from ._runtime_types_io import (
    _binary_close,
    _build_grid,
    _extract_seed_component,
    _mask_to_geometry,
    _rasterize_geometries,
)
from .case_models import T04CaseResult
from .polygon_assembly_guards import Step6GuardContext, derive_step6_guard_context
from .polygon_assembly_models import T04Step6Result
from .polygon_assembly_path import (
    _barrier_separated_case_surface_ok,
    _case_alignment_aggregate_doc,
    _case_alignment_review_reasons,
    _constrain_geometry_to_case_limits,
    _core_must_cover_geometry,
    _fill_unexpected_polygon_holes,
    _full_fill_target_geometry,
    _hole_details,
    _inter_unit_section_bridge_surface,
    _is_no_main_section_window_surface,
    _is_swsd_only_surface,
    _is_swsd_section_window_surface,
    _junction_full_fill_slit_relief,
    _loaded_feature_union,
    _relief_constraint_audit_entry,
    _single_case_bridge_zone,
    _swsd_window_touch_close,
    _target_b_seed_geometry,
    _unit_surface_count,
    _uses_single_component_surface_seed,
    check_post_cleanup_constraints,
)
from .polygon_assembly_raster import (
    STEP6_ALLOWED_TOLERANCE_AREA_M2,
    STEP6_CLOSE_ITERATIONS,
    STEP6_CUT_BARRIER_BUFFER_M,
    STEP6_CUT_TOLERANCE_AREA_M2,
    STEP6_FORBIDDEN_TOLERANCE_AREA_M2,
    STEP6_GRID_MARGIN_M,
    STEP6_MAX_GRID_SIDE_CELLS,
    STEP6_RESOLUTION_M,
    _component_masks,
    _connect_hard_seed_components,
    _connect_optional_seed_components,
    _grid_center_and_patch_size,
    _relaxed_canvas_component_relief_bridge,
    _validate_step6_grid_size,
)
from .polygon_assembly_relief import (
    cut_sliver_hole_relief as _cut_sliver_hole_relief,
    dominant_component_relief_bridge as _dominant_component_relief_bridge,
    seed_dominant_polygon_component as _seed_dominant_polygon_component,
)
from .support_domain import T04Step5CaseResult
from .surface_scenario import (
    SCENARIO_MAIN_WITH_RCSD,
    SCENARIO_MAIN_WITHOUT_RCSD,
    SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD,
)

def build_step6_polygon_assembly(
    case_result: T04CaseResult,
    step5_result: T04Step5CaseResult,
) -> T04Step6Result:
    guard_context = derive_step6_guard_context(step5_result)
    case_alignment_aggregate = _case_alignment_aggregate_doc(case_result)
    case_alignment_review_reasons, case_alignment_ambiguous_event_unit_ids = (
        _case_alignment_review_reasons(case_alignment_aggregate)
    )
    constraint_step5_result = step5_result
    unit_surface_count = _unit_surface_count(step5_result)
    if guard_context.no_surface_reference_guard:
        post_checks = check_post_cleanup_constraints(
            final_case_polygon=None,
            step5_result=step5_result,
            cut_barrier_geometry=None,
            hard_seed_geometry=None,
            guard_context=guard_context,
        )
        return T04Step6Result(
            case_id=case_result.case_spec.case_id,
            final_case_polygon=None,
            final_case_holes=None,
            final_case_cut_lines=_normalize_geometry(step5_result.case_terminal_cut_constraints),
            final_case_forbidden_overlap=None,
            assembly_canvas_geometry=None,
            hard_seed_geometry=None,
            weak_seed_geometry=None,
            component_count=0,
            hole_count=0,
            business_hole_count=0,
            unexpected_hole_count=0,
            hard_must_cover_ok=True,
            b_node_target_covered=True,
            forbidden_overlap_area_m2=0.0,
            cut_violation=False,
            assembly_state="assembly_failed",
            review_reasons=("no_surface_reference", *case_alignment_review_reasons),
            hard_connect_notes=(),
            optional_connect_notes=(),
            hole_details=(),
            **post_checks,
            case_alignment_review_reasons=case_alignment_review_reasons,
            case_alignment_ambiguous_event_unit_ids=case_alignment_ambiguous_event_unit_ids,
            surface_scenario_type=guard_context.surface_scenario_type,
            section_reference_source=guard_context.section_reference_source,
            surface_generation_mode=guard_context.surface_generation_mode,
            reference_point_present=guard_context.reference_point_present,
            surface_section_forward_m=guard_context.surface_section_forward_m,
            surface_section_backward_m=guard_context.surface_section_backward_m,
            surface_lateral_limit_m=guard_context.surface_lateral_limit_m,
            surface_scenario_missing=guard_context.surface_scenario_missing,
            no_surface_reference_guard=True,
            final_polygon_suppressed_by_no_surface_reference=True,
            no_virtual_reference_point_guard=guard_context.no_virtual_reference_point_guard,
            b_node_gate_applicable=False,
            b_node_gate_skip_reason="no_surface_reference",
            section_reference_window_covered=False,
            fallback_rcsdroad_ids=guard_context.fallback_rcsdroad_ids,
            fallback_rcsdroad_localized=guard_context.fallback_rcsdroad_localized,
            forbidden_domain_kept=guard_context.forbidden_domain_kept,
            divstrip_negative_mask_present=guard_context.divstrip_negative_mask_present,
            unit_surface_count=unit_surface_count,
            unit_surface_merge_performed=False,
            merge_mode="case_level_assembly",
            merged_case_surface_component_count=0,
            final_case_polygon_component_count=0,
            single_connected_case_surface_ok=False,
        )
    drivezone_union = _loaded_feature_union(case_result.case_bundle.drivezone_features)
    representative_point = case_result.case_bundle.representative_node.geometry
    assembly_source_geometry = _union_geometry(
        [
            step5_result.case_allowed_growth_domain,
            step5_result.case_must_cover_domain,
            step5_result.case_terminal_cut_constraints,
            step5_result.case_terminal_support_corridor_geometry,
            step5_result.case_bridge_zone_geometry,
        ]
    )
    grid_center, patch_size_m = _grid_center_and_patch_size(
        assembly_source_geometry,
        fallback_point=representative_point,
    )
    _validate_step6_grid_size(
        case_id=case_result.case_spec.case_id,
        patch_size_m=patch_size_m,
        resolution_m=STEP6_RESOLUTION_M,
    )
    grid = _build_grid(
        grid_center,
        patch_size_m=patch_size_m,
        resolution_m=STEP6_RESOLUTION_M,
    )

    allowed_mask = _rasterize_geometries(grid, [step5_result.case_allowed_growth_domain])
    terminal_window_geometry = step5_result.case_terminal_window_domain
    if (
        terminal_window_geometry is not None
        and not terminal_window_geometry.is_empty
        and step5_result.case_terminal_support_corridor_geometry is not None
        and not step5_result.case_terminal_support_corridor_geometry.is_empty
    ):
        terminal_window_geometry = _normalize_geometry(
            _union_geometry(
                [
                    terminal_window_geometry,
                    step5_result.case_terminal_support_corridor_geometry,
                ]
            )
        )
    if _is_swsd_section_window_surface(guard_context):
        terminal_window_geometry = _normalize_geometry(
            _union_geometry(
                [
                    terminal_window_geometry,
                    step5_result.case_allowed_growth_domain,
                    step5_result.case_must_cover_domain,
                ]
            )
        )
    forbidden_mask = _rasterize_geometries(grid, [step5_result.case_forbidden_domain])
    inter_unit_bridge_surface = _inter_unit_section_bridge_surface(step5_result)
    inter_unit_bridge_surface = _constrain_geometry_to_case_limits(
        inter_unit_bridge_surface,
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=None,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=None,
    )
    if inter_unit_bridge_surface is not None and not inter_unit_bridge_surface.is_empty:
        terminal_window_geometry = _normalize_geometry(
            _union_geometry([terminal_window_geometry, inter_unit_bridge_surface])
        )
    terminal_window_mask = (
        _rasterize_geometries(grid, [terminal_window_geometry])
        if terminal_window_geometry is not None and not terminal_window_geometry.is_empty
        else np.ones_like(allowed_mask, dtype=bool)
    )
    cut_barrier_geometry = None
    if step5_result.case_terminal_cut_constraints is not None and not step5_result.case_terminal_cut_constraints.is_empty:
        cut_barrier_geometry = step5_result.case_terminal_cut_constraints.buffer(
            STEP6_CUT_BARRIER_BUFFER_M,
            cap_style=2,
            join_style=2,
        )
        single_bridge_zone = _single_case_bridge_zone(step5_result)
        if single_bridge_zone is not None and not single_bridge_zone.is_empty:
            cut_barrier_geometry = _normalize_geometry(
                cut_barrier_geometry.difference(single_bridge_zone)
            )
        if inter_unit_bridge_surface is not None and not inter_unit_bridge_surface.is_empty:
            inter_unit_cut_relief = inter_unit_bridge_surface.buffer(
                STEP6_CUT_BARRIER_BUFFER_M,
                cap_style=2,
                join_style=2,
            )
            cut_barrier_geometry = _normalize_geometry(
                cut_barrier_geometry.difference(inter_unit_cut_relief)
            )
        if _is_swsd_section_window_surface(guard_context) and len(step5_result.unit_results) > 1:
            cut_barrier_geometry = _normalize_geometry(
                cut_barrier_geometry.difference(step5_result.case_allowed_growth_domain)
            )
    cut_mask = _rasterize_geometries(grid, [cut_barrier_geometry]) if cut_barrier_geometry is not None else np.zeros_like(allowed_mask, dtype=bool)
    assembly_canvas_mask = allowed_mask & terminal_window_mask & ~forbidden_mask & ~cut_mask
    # 连通性恢复（spec §1.4 / Bug-2 修复）：当 Step5 的 `case_allowed_growth_domain`
    # 是单连通 Polygon、但 0.5m 栅格化后被狭窄段切成多 component 时，做一次 1-iter
    # binary_close 把 ≤1m 的"假断开"缝合回去；再用 `allowed & terminal_window
    # & ~forbidden & ~cut` 重新裁剪，确保不会越过任何负向掩膜或 allowed_growth 范围。
    # 目的：让 SWSD-junction-window 与 RCSD-junction-window 等 narrow allowed_growth
    # 场景在 §1.4 barrier-aware grow 下产生天然单连通面；不影响真正被掩膜阻断的多 component。
    case_allowed_growth_domain = step5_result.case_allowed_growth_domain
    if (
        case_allowed_growth_domain is not None
        and not case_allowed_growth_domain.is_empty
        and case_allowed_growth_domain.geom_type == "Polygon"
        and assembly_canvas_mask.any()
    ):
        canvas_components_pre = _component_masks(assembly_canvas_mask)
        if len(canvas_components_pre) > 1:
            closed_mask = (
                _binary_close(assembly_canvas_mask, iterations=1)
                & allowed_mask
                & terminal_window_mask
                & ~forbidden_mask
                & ~cut_mask
            )
            if len(_component_masks(closed_mask)) < len(canvas_components_pre):
                assembly_canvas_mask = closed_mask
    assembly_canvas_geometry = _constrain_geometry_to_case_limits(
        _mask_to_geometry(assembly_canvas_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=constraint_step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )

    core_hard_seed_geometry = _core_must_cover_geometry(step5_result)
    case_must_requested_mask = _rasterize_geometries(grid, [step5_result.case_must_cover_domain])
    hard_seed_requested_mask = case_must_requested_mask
    bridge_requested_mask = _rasterize_geometries(grid, [_single_case_bridge_zone(step5_result)])
    inter_unit_bridge_requested_mask = _rasterize_geometries(grid, [inter_unit_bridge_surface])
    full_fill_target_geometry = _full_fill_target_geometry(step5_result)
    if full_fill_target_geometry is not None and not full_fill_target_geometry.is_empty:
        core_seed_requested_mask = _rasterize_geometries(grid, [core_hard_seed_geometry])
        full_fill_requested_mask = _rasterize_geometries(grid, [full_fill_target_geometry])
        full_fill_canvas_mask = full_fill_requested_mask & assembly_canvas_mask
        core_seed_canvas_mask = core_seed_requested_mask & assembly_canvas_mask
        if _is_swsd_section_window_surface(guard_context) or (
            _is_no_main_section_window_surface(guard_context)
            and not (full_fill_canvas_mask & core_seed_canvas_mask).any()
        ):
            effective_full_fill_mask = full_fill_canvas_mask
        else:
            effective_full_fill_mask = _extract_seed_component(
                full_fill_canvas_mask,
                core_seed_canvas_mask,
            )
        hard_seed_requested_mask = (
            core_seed_requested_mask
            | effective_full_fill_mask
            | bridge_requested_mask
            | inter_unit_bridge_requested_mask
        )
    hard_seed_mask = hard_seed_requested_mask & assembly_canvas_mask
    if inter_unit_bridge_requested_mask.any() and bridge_requested_mask.any():
        hard_seed_mask = _extract_seed_component(
            hard_seed_mask,
            bridge_requested_mask | inter_unit_bridge_requested_mask,
        )
    hard_seed_geometry = _constrain_geometry_to_case_limits(
        _mask_to_geometry(hard_seed_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )
    if _is_swsd_section_window_surface(guard_context):
        hard_seed_geometry = _constrain_geometry_to_case_limits(
            _normalize_geometry(
                _union_geometry([hard_seed_geometry, step5_result.case_must_cover_domain])
            ),
            drivezone_union=drivezone_union,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        hard_seed_mask = _rasterize_geometries(grid, [hard_seed_geometry]) & assembly_canvas_mask
    if _is_no_main_section_window_surface(guard_context) and not _is_swsd_section_window_surface(guard_context):
        hard_seed_geometry = _seed_dominant_polygon_component(
            hard_seed_geometry,
            core_hard_seed_geometry,
        )
        hard_seed_mask = _rasterize_geometries(grid, [hard_seed_geometry]) & assembly_canvas_mask
    if (
        inter_unit_bridge_surface is not None
        and not inter_unit_bridge_surface.is_empty
        and not _is_swsd_section_window_surface(guard_context)
    ):
        hard_seed_geometry = _seed_dominant_polygon_component(
            hard_seed_geometry,
            _union_geometry([step5_result.case_bridge_zone_geometry, inter_unit_bridge_surface]),
        )
        hard_seed_mask = _rasterize_geometries(grid, [hard_seed_geometry]) & assembly_canvas_mask
    single_component_surface_seed = _uses_single_component_surface_seed(step5_result)
    if single_component_surface_seed:
        hard_seed_geometry = _seed_dominant_polygon_component(
            hard_seed_geometry,
            core_hard_seed_geometry,
        )
        hard_seed_mask = _rasterize_geometries(grid, [hard_seed_geometry]) & assembly_canvas_mask
    target_b_seed_geometry = _target_b_seed_geometry(step5_result)
    target_b_requested_mask = _rasterize_geometries(grid, [target_b_seed_geometry])
    target_b_mask = target_b_requested_mask & assembly_canvas_mask
    target_b_effective_geometry = _constrain_geometry_to_case_limits(
        _mask_to_geometry(target_b_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )
    weak_seed_geometry = _union_geometry(
        [
            target_b_seed_geometry,
            step5_result.case_bridge_zone_geometry,
        ]
    )
    weak_seed_requested_mask = _rasterize_geometries(grid, [weak_seed_geometry])
    weak_seed_mask = weak_seed_requested_mask & assembly_canvas_mask
    weak_seed_effective_geometry = _constrain_geometry_to_case_limits(
        _mask_to_geometry(weak_seed_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )

    current_mask, hard_connect_notes = _connect_hard_seed_components(
        canvas_mask=assembly_canvas_mask,
        hard_seed_mask=hard_seed_mask,
    )
    current_mask, optional_connect_notes = _connect_optional_seed_components(
        canvas_mask=assembly_canvas_mask,
        current_mask=current_mask,
        optional_seed_mask=weak_seed_mask,
    )
    relief_constraint_audit_entries: list[dict[str, Any]] = []
    current_mask |= hard_seed_mask
    current_mask &= assembly_canvas_mask
    if current_mask.any():
        current_mask = _binary_close(current_mask, iterations=STEP6_CLOSE_ITERATIONS) & assembly_canvas_mask
    assembled_mask = (
        _extract_seed_component(assembly_canvas_mask, current_mask)
        if current_mask.any()
        else np.zeros_like(assembly_canvas_mask, dtype=bool)
    )

    final_case_polygon = _constrain_geometry_to_case_limits(
        _mask_to_geometry(assembled_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )
    if final_case_polygon is not None and not final_case_polygon.is_empty:
        final_case_polygon = _normalize_geometry(
            _fill_small_polygon_holes(
                final_case_polygon or GeometryCollection(),
                max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
            )
        )
    cut_checked_polygon = final_case_polygon
    if final_case_polygon is not None and not final_case_polygon.is_empty:
        final_case_polygon = _fill_unexpected_polygon_holes(
            final_case_polygon,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
    if final_case_polygon is not None and not final_case_polygon.is_empty:
        final_case_polygon = _constrain_geometry_to_case_limits(
            final_case_polygon,
            drivezone_union=drivezone_union,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
    if (
        _is_swsd_section_window_surface(guard_context)
        and final_case_polygon is not None
        and not final_case_polygon.is_empty
        and hard_seed_geometry is not None
        and not hard_seed_geometry.is_empty
        and not final_case_polygon.buffer(1e-6).covers(hard_seed_geometry)
    ):
        final_case_polygon = _constrain_geometry_to_case_limits(
            _normalize_geometry(_union_geometry([final_case_polygon, hard_seed_geometry])),
            drivezone_union=drivezone_union,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
    if single_component_surface_seed:
        final_case_polygon = _seed_dominant_polygon_component(
            final_case_polygon,
            hard_seed_geometry,
        )
    if (
        inter_unit_bridge_surface is not None
        and not inter_unit_bridge_surface.is_empty
        and not _is_swsd_section_window_surface(guard_context)
    ):
        final_case_polygon = _seed_dominant_polygon_component(
            final_case_polygon,
            _union_geometry([step5_result.case_bridge_zone_geometry, inter_unit_bridge_surface]),
        )
        final_case_polygon = _fill_unexpected_polygon_holes(
            final_case_polygon,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        final_case_polygon = _constrain_geometry_to_case_limits(
            final_case_polygon,
            drivezone_union=drivezone_union,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
    if final_case_polygon is not None and not final_case_polygon.is_empty:
        final_case_polygon = _fill_unexpected_polygon_holes(
            final_case_polygon,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
    cut_checked_polygon = final_case_polygon
    if (
        guard_context.surface_scenario_type == SCENARIO_MAIN_WITH_RCSD
        and final_case_polygon is not None
        and not final_case_polygon.is_empty
    ):
        dominant_relief_bridge = _dominant_component_relief_bridge(
            final_case_polygon,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        if dominant_relief_bridge is not None and not dominant_relief_bridge.is_empty:
            before_forbidden_geometry = constraint_step5_result.case_forbidden_domain
            before_cut_barrier_geometry = cut_barrier_geometry
            relieved_forbidden_geometry = (
                None
                if before_forbidden_geometry is None
                else _normalize_geometry(
                    before_forbidden_geometry.difference(dominant_relief_bridge)
                )
            )
            constraint_step5_result = replace(
                constraint_step5_result,
                case_forbidden_domain=relieved_forbidden_geometry,
            )
            if cut_barrier_geometry is not None and not cut_barrier_geometry.is_empty:
                cut_barrier_geometry = _normalize_geometry(
                    cut_barrier_geometry.difference(dominant_relief_bridge)
                )
            relief_constraint_audit_entries.append(
                _relief_constraint_audit_entry(
                    relief_note="dominant_component_relief_bridge",
                    relief_geometry=dominant_relief_bridge,
                    before_allowed_geometry=step5_result.case_allowed_growth_domain,
                    after_allowed_geometry=step5_result.case_allowed_growth_domain,
                    before_forbidden_geometry=before_forbidden_geometry,
                    after_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                    before_cut_barrier_geometry=before_cut_barrier_geometry,
                    after_cut_barrier_geometry=cut_barrier_geometry,
                )
            )
            final_case_polygon = _constrain_geometry_to_case_limits(
                _normalize_geometry(_union_geometry([final_case_polygon, dominant_relief_bridge])),
                drivezone_union=drivezone_union,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                terminal_window_geometry=terminal_window_geometry,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            final_case_polygon = _fill_unexpected_polygon_holes(
                final_case_polygon,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            cut_checked_polygon = final_case_polygon
            hard_connect_notes.append("dominant_component_relief_bridge")

    if (
        guard_context.surface_scenario_type == SCENARIO_MAIN_WITH_RCSD
        and final_case_polygon is not None
        and not final_case_polygon.is_empty
    ):
        cut_sliver_relief = _cut_sliver_hole_relief(
            final_case_polygon,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        if cut_sliver_relief is not None and not cut_sliver_relief.is_empty:
            before_cut_barrier_geometry = cut_barrier_geometry
            if cut_barrier_geometry is not None and not cut_barrier_geometry.is_empty:
                cut_barrier_geometry = _normalize_geometry(cut_barrier_geometry.difference(cut_sliver_relief))
            relief_constraint_audit_entries.append(
                _relief_constraint_audit_entry(
                    relief_note="cut_sliver_hole_relief",
                    relief_geometry=cut_sliver_relief,
                    before_allowed_geometry=step5_result.case_allowed_growth_domain,
                    after_allowed_geometry=step5_result.case_allowed_growth_domain,
                    before_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                    after_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                    before_cut_barrier_geometry=before_cut_barrier_geometry,
                    after_cut_barrier_geometry=cut_barrier_geometry,
                )
            )
            final_case_polygon = _constrain_geometry_to_case_limits(
                _normalize_geometry(_union_geometry([final_case_polygon, cut_sliver_relief])),
                drivezone_union=drivezone_union,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                terminal_window_geometry=terminal_window_geometry,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            final_case_polygon = _fill_unexpected_polygon_holes(
                final_case_polygon,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            cut_checked_polygon = final_case_polygon
            hard_connect_notes.append("cut_sliver_hole_relief")

    if (
        guard_context.surface_scenario_type == SCENARIO_MAIN_WITH_RCSD
        and "dominant_component_relief_bridge" not in hard_connect_notes
        and final_case_polygon is not None
        and not final_case_polygon.is_empty
    ):
        dominant_relief_bridge = _dominant_component_relief_bridge(
            final_case_polygon,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        if dominant_relief_bridge is not None and not dominant_relief_bridge.is_empty:
            before_forbidden_geometry = constraint_step5_result.case_forbidden_domain
            before_cut_barrier_geometry = cut_barrier_geometry
            relieved_forbidden_geometry = (
                None
                if before_forbidden_geometry is None
                else _normalize_geometry(
                    before_forbidden_geometry.difference(dominant_relief_bridge)
                )
            )
            constraint_step5_result = replace(
                constraint_step5_result,
                case_forbidden_domain=relieved_forbidden_geometry,
            )
            if cut_barrier_geometry is not None and not cut_barrier_geometry.is_empty:
                cut_barrier_geometry = _normalize_geometry(
                    cut_barrier_geometry.difference(dominant_relief_bridge)
                )
            relief_constraint_audit_entries.append(
                _relief_constraint_audit_entry(
                    relief_note="post_cut_dominant_component_relief_bridge",
                    relief_geometry=dominant_relief_bridge,
                    before_allowed_geometry=step5_result.case_allowed_growth_domain,
                    after_allowed_geometry=step5_result.case_allowed_growth_domain,
                    before_forbidden_geometry=before_forbidden_geometry,
                    after_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                    before_cut_barrier_geometry=before_cut_barrier_geometry,
                    after_cut_barrier_geometry=cut_barrier_geometry,
                )
            )
            final_case_polygon = _constrain_geometry_to_case_limits(
                _normalize_geometry(_union_geometry([final_case_polygon, dominant_relief_bridge])),
                drivezone_union=drivezone_union,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                terminal_window_geometry=terminal_window_geometry,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            final_case_polygon = _fill_unexpected_polygon_holes(
                final_case_polygon,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            cut_checked_polygon = final_case_polygon
            hard_connect_notes.append("post_cut_dominant_component_relief_bridge")

    if final_case_polygon is not None and not final_case_polygon.is_empty:
        slit_relief = _junction_full_fill_slit_relief(
            final_case_polygon,
            step5_result=step5_result,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
        )
        if slit_relief is not None and not slit_relief.is_empty:
            before_cut_barrier_geometry = cut_barrier_geometry
            next_cut_barrier_geometry = cut_barrier_geometry
            if cut_barrier_geometry is not None and not cut_barrier_geometry.is_empty:
                next_cut_barrier_geometry = _normalize_geometry(cut_barrier_geometry.difference(slit_relief))
            relieved_polygon = _constrain_geometry_to_case_limits(
                _normalize_geometry(_union_geometry([final_case_polygon, slit_relief])),
                drivezone_union=drivezone_union,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                terminal_window_geometry=terminal_window_geometry,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                cut_barrier_geometry=next_cut_barrier_geometry,
            )
            relieved_polygon = _fill_unexpected_polygon_holes(
                relieved_polygon,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                cut_barrier_geometry=next_cut_barrier_geometry,
            )
            relief_preserves_must_cover = (
                hard_seed_geometry is None
                or hard_seed_geometry.is_empty
                or (
                    relieved_polygon is not None
                    and not relieved_polygon.is_empty
                    and relieved_polygon.buffer(1e-6).covers(hard_seed_geometry)
                )
            )
            if relief_preserves_must_cover:
                relief_constraint_audit_entries.append(
                    _relief_constraint_audit_entry(
                        relief_note="junction_full_fill_slit_relief",
                        relief_geometry=slit_relief,
                        before_allowed_geometry=step5_result.case_allowed_growth_domain,
                        after_allowed_geometry=step5_result.case_allowed_growth_domain,
                        before_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                        after_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                        before_cut_barrier_geometry=before_cut_barrier_geometry,
                        after_cut_barrier_geometry=next_cut_barrier_geometry,
                    )
                )
                cut_barrier_geometry = next_cut_barrier_geometry
                final_case_polygon = relieved_polygon
                cut_checked_polygon = final_case_polygon
                hard_connect_notes.append("junction_full_fill_slit_relief")

    if (
        _is_swsd_section_window_surface(guard_context)
        and final_case_polygon is not None
        and not final_case_polygon.is_empty
    ):
        closed_polygon = _swsd_window_touch_close(
            final_case_polygon,
            step5_result=step5_result,
            hard_seed_geometry=hard_seed_geometry,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        if closed_polygon is not None and not closed_polygon.is_empty:
            final_case_polygon = closed_polygon
            cut_checked_polygon = final_case_polygon
            hard_connect_notes.append("swsd_window_touch_close")

    component_count = len(_polygon_components(final_case_polygon or GeometryCollection()))
    if component_count > 1 and final_case_polygon is not None and not final_case_polygon.is_empty:
        late_relief_bridge: BaseGeometry | None = None
        late_relief_note = ""
        if guard_context.surface_scenario_type == SCENARIO_MAIN_WITH_RCSD:
            late_relief_bridge = _dominant_component_relief_bridge(
                final_case_polygon,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                terminal_window_geometry=terminal_window_geometry,
                cut_barrier_geometry=cut_barrier_geometry,
                use_terminal_window=False,
            )
            late_relief_note = "late_dominant_component_relief_bridge"
        elif guard_context.surface_scenario_type in {SCENARIO_MAIN_WITHOUT_RCSD, "main_evidence_without_rcsd"}:
            late_relief_bridge = _relaxed_canvas_component_relief_bridge(
                final_case_polygon,
                grid=grid,
                relaxed_canvas_mask=allowed_mask & ~forbidden_mask & ~cut_mask,
            )
            late_relief_note = "main_without_rcsd_component_relief_bridge"
        if late_relief_bridge is not None and not late_relief_bridge.is_empty:
            before_allowed_geometry = step5_result.case_allowed_growth_domain
            before_forbidden_geometry = constraint_step5_result.case_forbidden_domain
            before_cut_barrier_geometry = cut_barrier_geometry
            if guard_context.surface_scenario_type == SCENARIO_MAIN_WITHOUT_RCSD:
                relieved_allowed_geometry = _normalize_geometry(
                    _union_geometry([step5_result.case_allowed_growth_domain, late_relief_bridge])
                )
                step5_result = replace(step5_result, case_allowed_growth_domain=relieved_allowed_geometry)
                constraint_step5_result = replace(
                    constraint_step5_result,
                    case_allowed_growth_domain=relieved_allowed_geometry,
                )
                terminal_window_geometry = _normalize_geometry(
                    _union_geometry([terminal_window_geometry, late_relief_bridge])
                )
            relieved_forbidden_geometry = (
                None
                if constraint_step5_result.case_forbidden_domain is None
                else _normalize_geometry(
                    constraint_step5_result.case_forbidden_domain.difference(late_relief_bridge)
                )
            )
            constraint_step5_result = replace(
                constraint_step5_result,
                case_forbidden_domain=relieved_forbidden_geometry,
            )
            if cut_barrier_geometry is not None and not cut_barrier_geometry.is_empty:
                cut_barrier_geometry = _normalize_geometry(
                    cut_barrier_geometry.difference(late_relief_bridge)
                )
            relief_constraint_audit_entries.append(
                _relief_constraint_audit_entry(
                    relief_note=late_relief_note,
                    relief_geometry=late_relief_bridge,
                    before_allowed_geometry=before_allowed_geometry,
                    after_allowed_geometry=step5_result.case_allowed_growth_domain,
                    before_forbidden_geometry=before_forbidden_geometry,
                    after_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                    before_cut_barrier_geometry=before_cut_barrier_geometry,
                    after_cut_barrier_geometry=cut_barrier_geometry,
                )
            )
            final_case_polygon = _constrain_geometry_to_case_limits(
                _normalize_geometry(_union_geometry([final_case_polygon, late_relief_bridge])),
                drivezone_union=drivezone_union,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                terminal_window_geometry=terminal_window_geometry,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            final_case_polygon = _fill_unexpected_polygon_holes(
                final_case_polygon,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            cut_checked_polygon = final_case_polygon
            hard_connect_notes.append(late_relief_note)
            component_count = len(_polygon_components(final_case_polygon or GeometryCollection()))

    if final_case_polygon is not None and not final_case_polygon.is_empty:
        final_case_polygon = _constrain_geometry_to_case_limits(
            final_case_polygon,
            drivezone_union=drivezone_union,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        cut_checked_polygon = final_case_polygon
        component_count = len(_polygon_components(final_case_polygon or GeometryCollection()))
    post_check_step5_result = constraint_step5_result
    hole_details, final_case_holes = _hole_details(
        geometry=final_case_polygon,
        forbidden_geometry=post_check_step5_result.case_forbidden_domain,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )
    business_hole_count = sum(1 for item in hole_details if bool(item["business_hole"]))
    unexpected_hole_count = sum(1 for item in hole_details if not bool(item["business_hole"]))
    final_case_forbidden_overlap = _normalize_geometry(
        None
        if final_case_polygon is None
        or final_case_polygon.is_empty
        or post_check_step5_result.case_forbidden_domain is None
        else final_case_polygon.intersection(post_check_step5_result.case_forbidden_domain)
    )
    forbidden_overlap_area_m2 = float(
        getattr(final_case_forbidden_overlap, "area", 0.0) or 0.0
    )
    cut_violation = False
    if cut_checked_polygon is not None and not cut_checked_polygon.is_empty and cut_barrier_geometry is not None:
        cut_violation = (
            float(cut_checked_polygon.intersection(cut_barrier_geometry).area)
            > STEP6_CUT_TOLERANCE_AREA_M2
        )

    hard_must_cover_ok = bool(
        final_case_polygon is not None
        and not final_case_polygon.is_empty
        and hard_seed_geometry is not None
        and final_case_polygon.buffer(1e-6).covers(hard_seed_geometry)
    )
    target_b_present = bool(
        target_b_effective_geometry is not None
        and not target_b_effective_geometry.is_empty
    )
    b_node_gate_applicable = True
    b_node_gate_skip_reason = ""
    if not target_b_present and _is_swsd_only_surface(guard_context):
        b_node_gate_applicable = False
        b_node_gate_skip_reason = "swsd_only_without_b_target"
    elif guard_context.surface_scenario_type == SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD:
        b_node_gate_applicable = False
        b_node_gate_skip_reason = "no_main_swsd_rcsdroad_fallback"

    b_node_target_covered = True
    if not b_node_gate_applicable:
        b_node_target_covered = True
    elif final_case_polygon is None or final_case_polygon.is_empty:
        b_node_target_covered = False
    elif target_b_present and not final_case_polygon.buffer(1e-6).covers(target_b_effective_geometry):
        b_node_target_covered = False
    section_reference_window_covered = True
    if _is_swsd_section_window_surface(guard_context):
        section_reference_window_covered = bool(
            final_case_polygon is not None
            and not final_case_polygon.is_empty
            and hard_seed_geometry is not None
            and not hard_seed_geometry.is_empty
            and final_case_polygon.buffer(1e-6).covers(hard_seed_geometry)
        )
    post_checks = check_post_cleanup_constraints(
        final_case_polygon=final_case_polygon,
        step5_result=post_check_step5_result,
        cut_barrier_geometry=cut_barrier_geometry,
        hard_seed_geometry=hard_seed_geometry,
        guard_context=guard_context,
    )
    hard_must_cover_ok = bool(post_checks["post_cleanup_must_cover_ok"])
    barrier_separated_case_surface_ok = _barrier_separated_case_surface_ok(
        final_case_polygon=final_case_polygon,
        assembly_canvas_geometry=assembly_canvas_geometry,
        component_count=component_count,
        guard_context=guard_context,
        post_checks=post_checks,
        hard_must_cover_ok=hard_must_cover_ok,
        b_node_target_covered=b_node_target_covered,
        cut_violation=cut_violation,
        unexpected_hole_count=unexpected_hole_count,
        case_alignment_review_reasons=case_alignment_review_reasons,
        hard_connect_notes=tuple(hard_connect_notes),
    )

    review_reasons: list[str] = []
    if final_case_polygon is None or final_case_polygon.is_empty:
        review_reasons.append("assembly_failed")
    if (
        component_count != 1
        and final_case_polygon is not None
        and not final_case_polygon.is_empty
    ):
        review_reasons.append("multi_component_result")
    if not hard_must_cover_ok:
        review_reasons.append("hard_must_cover_disconnected")
    if not bool(post_checks["post_cleanup_allowed_growth_ok"]):
        review_reasons.append("allowed_growth_conflict")
    if forbidden_overlap_area_m2 > STEP6_FORBIDDEN_TOLERANCE_AREA_M2:
        review_reasons.append("forbidden_conflict")
    if cut_violation:
        review_reasons.append("terminal_cut_conflict")
    if not bool(post_checks["post_cleanup_lateral_limit_ok"]):
        review_reasons.append("lateral_limit_conflict")
    if not bool(post_checks["post_cleanup_negative_mask_ok"]):
        review_reasons.append("negative_mask_conflict")
    if bool(post_checks["fallback_overexpansion_detected"]):
        review_reasons.append("fallback_overexpansion")
    if unexpected_hole_count > 0:
        review_reasons.append("unexpected_hole_present")
    if b_node_gate_applicable and not b_node_target_covered:
        review_reasons.append("b_node_not_covered")
    review_reasons.extend(case_alignment_review_reasons)
    review_reasons = list(dict.fromkeys(review_reasons))

    if not review_reasons:
        assembly_state = "assembled"
    elif all(reason == "b_node_not_covered" for reason in review_reasons):
        assembly_state = "assembled_with_review"
    else:
        assembly_state = "assembly_failed"

    return T04Step6Result(
        case_id=case_result.case_spec.case_id,
        final_case_polygon=final_case_polygon,
        final_case_holes=final_case_holes,
        final_case_cut_lines=_normalize_geometry(step5_result.case_terminal_cut_constraints),
        final_case_forbidden_overlap=final_case_forbidden_overlap,
        assembly_canvas_geometry=assembly_canvas_geometry,
        hard_seed_geometry=hard_seed_geometry,
        weak_seed_geometry=weak_seed_effective_geometry,
        component_count=component_count,
        hole_count=len(hole_details),
        business_hole_count=business_hole_count,
        unexpected_hole_count=unexpected_hole_count,
        hard_must_cover_ok=hard_must_cover_ok,
        b_node_target_covered=b_node_target_covered,
        b_node_gate_applicable=b_node_gate_applicable,
        b_node_gate_skip_reason=b_node_gate_skip_reason,
        section_reference_window_covered=section_reference_window_covered,
        forbidden_overlap_area_m2=forbidden_overlap_area_m2,
        cut_violation=cut_violation,
        assembly_state=assembly_state,
        review_reasons=tuple(review_reasons),
        hard_connect_notes=tuple(hard_connect_notes),
        optional_connect_notes=tuple(optional_connect_notes),
        hole_details=tuple(hole_details),
        relief_constraint_audit_entries=tuple(relief_constraint_audit_entries),
        **post_checks,
        case_alignment_review_reasons=case_alignment_review_reasons,
        case_alignment_ambiguous_event_unit_ids=case_alignment_ambiguous_event_unit_ids,
        surface_scenario_type=guard_context.surface_scenario_type,
        section_reference_source=guard_context.section_reference_source,
        surface_generation_mode=guard_context.surface_generation_mode,
        reference_point_present=guard_context.reference_point_present,
        surface_section_forward_m=guard_context.surface_section_forward_m,
        surface_section_backward_m=guard_context.surface_section_backward_m,
        surface_lateral_limit_m=guard_context.surface_lateral_limit_m,
        surface_scenario_missing=guard_context.surface_scenario_missing,
        no_surface_reference_guard=guard_context.no_surface_reference_guard,
        final_polygon_suppressed_by_no_surface_reference=False,
        no_virtual_reference_point_guard=guard_context.no_virtual_reference_point_guard,
        fallback_rcsdroad_ids=guard_context.fallback_rcsdroad_ids,
        fallback_rcsdroad_localized=guard_context.fallback_rcsdroad_localized,
        forbidden_domain_kept=guard_context.forbidden_domain_kept,
        divstrip_negative_mask_present=guard_context.divstrip_negative_mask_present,
        unit_surface_count=unit_surface_count,
        unit_surface_merge_performed=False,
        merge_mode="case_level_assembly",
        merged_case_surface_component_count=component_count,
        final_case_polygon_component_count=component_count,
        single_connected_case_surface_ok=component_count == 1,
        barrier_separated_case_surface_ok=barrier_separated_case_surface_ok,
    )


__all__ = [
    "Step6GuardContext",
    "T04Step6Result",
    "build_step6_polygon_assembly",
    "check_post_cleanup_constraints",
    "derive_step6_guard_context",
]
