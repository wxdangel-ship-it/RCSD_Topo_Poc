from __future__ import annotations

from shapely.geometry import GeometryCollection
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step4_contract import Stage4EventInterpretationResult
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step5_step6_contract import (
    Stage4GeometryRiskSignals,
    Stage4GeometryState,
    Stage4LegacyStep7Bridge,
    Stage4PolygonAssemblyResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import _mask_to_geometry, _regularize_virtual_polygon_geometry

from .stage4_geometry_utils import *

def _is_expected_continuous_chain_multilobe_geometry(
    *,
    complex_junction: bool,
    continuous_chain_applied: bool,
    continuous_chain_present: bool,
    continuous_chain_sequential_ok: bool,
    component_mask_used_support_fallback: bool,
    parallel_competitor_present: bool,
    selected_component_surface_diags: Sequence[Mapping[str, Any]],
    complex_multibranch_lobe_diags: Sequence[Mapping[str, Any]],
) -> bool:
    if not complex_junction:
        return False
    if not continuous_chain_applied or not continuous_chain_present or not continuous_chain_sequential_ok:
        return False
    if component_mask_used_support_fallback or parallel_competitor_present:
        return False
    if any(str(item.get("component_index", "")).startswith("connector") for item in selected_component_surface_diags):
        return False
    valid_component_surfaces = [
        item
        for item in selected_component_surface_diags
        if item.get("component_index") != "connector" and bool(item.get("ok", False))
    ]
    if len(valid_component_surfaces) != 2:
        return False
    if any(not bool(item.get("ok", False)) for item in selected_component_surface_diags):
        return False
    valid_lobes = [item for item in complex_multibranch_lobe_diags if bool(item.get("ok", False))]
    if len(valid_lobes) != 2:
        return False
    if any(not bool(item.get("ok", False)) for item in complex_multibranch_lobe_diags):
        return False
    return True


def _resolve_preferred_polygon_clip_geometry(
    *,
    local_surface_clip_geometry,
    axis_window_geometry,
    cross_section_surface_geometry,
    expected_continuous_chain_multilobe_geometry: bool,
    prefer_cross_section_surface_geometry: bool = False,
) -> tuple[Any, str]:
    if (
        expected_continuous_chain_multilobe_geometry
        and local_surface_clip_geometry is not None
        and not local_surface_clip_geometry.is_empty
    ):
        return local_surface_clip_geometry, "local_surface_clip"
    if (
        (prefer_cross_section_surface_geometry or expected_continuous_chain_multilobe_geometry)
        and cross_section_surface_geometry is not None
        and not cross_section_surface_geometry.is_empty
    ):
        return cross_section_surface_geometry, "cross_section_surface"
    if local_surface_clip_geometry is not None and not local_surface_clip_geometry.is_empty:
        return local_surface_clip_geometry, "local_surface_clip"
    if axis_window_geometry is not None and not axis_window_geometry.is_empty:
        return axis_window_geometry, "axis_window"
    if cross_section_surface_geometry is not None and not cross_section_surface_geometry.is_empty:
        return cross_section_surface_geometry, "cross_section_surface"
    return GeometryCollection(), "none"


def _refine_expected_continuous_chain_polygon_contour(
    *,
    polygon_geometry,
    preferred_clip_geometry,
    parallel_side_geometry,
    drivezone_union,
) -> tuple[Any, bool]:
    if (
        polygon_geometry is None
        or polygon_geometry.is_empty
        or preferred_clip_geometry is None
        or preferred_clip_geometry.is_empty
    ):
        return polygon_geometry, False

    cleanup_clip_geometry = preferred_clip_geometry
    if parallel_side_geometry is not None and not parallel_side_geometry.is_empty:
        cleanup_clip_geometry = cleanup_clip_geometry.intersection(
            parallel_side_geometry.buffer(
                EXPECTED_CHAIN_CONTOUR_PARALLEL_BUFFER_M,
                cap_style=2,
                join_style=2,
            )
        ).buffer(0)
    cleanup_clip_geometry = cleanup_clip_geometry.intersection(drivezone_union).buffer(0)
    if cleanup_clip_geometry.is_empty:
        return polygon_geometry, False

    refined_candidate = polygon_geometry.convex_hull.intersection(cleanup_clip_geometry).buffer(0)
    if refined_candidate.is_empty:
        return polygon_geometry, False
    smoothed_candidate = (
        refined_candidate.buffer(
            EXPECTED_CHAIN_CONTOUR_SMOOTH_BUFFER_M,
            cap_style=1,
            join_style=1,
        )
        .buffer(
            -EXPECTED_CHAIN_CONTOUR_SMOOTH_BUFFER_M,
            cap_style=1,
            join_style=1,
        )
        .intersection(cleanup_clip_geometry)
        .buffer(0)
    )
    if smoothed_candidate is not None and not smoothed_candidate.is_empty:
        refined_candidate = smoothed_candidate

    current_area_m2 = float(polygon_geometry.area)
    refined_area_m2 = float(refined_candidate.area)
    if current_area_m2 > 0.0:
        if refined_area_m2 < current_area_m2 * EXPECTED_CHAIN_CONTOUR_AREA_KEEP_MIN_RATIO:
            return polygon_geometry, False
        if refined_area_m2 > current_area_m2 * EXPECTED_CHAIN_CONTOUR_AREA_GAIN_MAX_RATIO:
            return polygon_geometry, False

    return refined_candidate, True


def _build_stage4_polygon_assembly(
    *,
    grid,
    drivezone_union,
    seed_union,
    local_divstrip_union,
    step4_event_interpretation: Stage4EventInterpretationResult,
    step5_geometric_support_domain: Stage4GeometricSupportDomain,
) -> Stage4PolygonAssemblyResult:
    legacy_step5_bridge = step4_event_interpretation.legacy_step5_bridge
    kind_resolution = step4_event_interpretation.kind_resolution.to_legacy_dict()
    multibranch_context = step4_event_interpretation.multibranch_decision.to_legacy_dict()
    divstrip_context = legacy_step5_bridge.divstrip_context.to_legacy_dict()
    selected_roads = list(legacy_step5_bridge.selected_roads)
    selected_event_roads = list(legacy_step5_bridge.selected_event_roads)
    selected_rcsd_roads = list(legacy_step5_bridge.selected_rcsd_roads)
    divstrip_constraint_geometry = legacy_step5_bridge.divstrip_constraint_geometry
    event_anchor_geometry = legacy_step5_bridge.event_anchor_geometry

    surface_assembly = step5_geometric_support_domain.surface_assembly
    component_mask = step5_geometric_support_domain.component_mask
    axis_window_geometry = surface_assembly.axis_window_geometry
    cross_section_surface_geometry = surface_assembly.cross_section_surface_geometry
    event_side_drivezone_geometry = surface_assembly.event_side_drivezone_geometry
    divstrip_event_window = surface_assembly.divstrip_event_window
    local_surface_clip_geometry = surface_assembly.local_surface_clip_geometry
    parallel_side_geometry = surface_assembly.parallel_side_geometry
    allow_full_axis_drivezone_fill = surface_assembly.allow_full_axis_drivezone_fill
    divstrip_geometry_to_exclude = step5_geometric_support_domain.divstrip_geometry_to_exclude

    polygon_geometry = _mask_to_geometry(component_mask, grid)
    include_event_side_drivezone_in_polygon_union = not (
        kind_resolution["complex_junction"]
        or multibranch_context["enabled"]
        or len(divstrip_context["selected_component_ids"]) > 1
    )
    if cross_section_surface_geometry is not None and not cross_section_surface_geometry.is_empty:
        polygon_geometry = unary_union(
            [
                geometry
                for geometry in [
                    polygon_geometry,
                    cross_section_surface_geometry,
                    (
                        event_side_drivezone_geometry
                        if include_event_side_drivezone_in_polygon_union
                        else None
                    ),
                ]
                if geometry is not None and not geometry.is_empty
            ]
        ).buffer(0)
    polygon_geometry = _regularize_virtual_polygon_geometry(
        geometry=polygon_geometry,
        drivezone_union=drivezone_union,
        seed_geometry=(
            step5_geometric_support_domain.event_seed_union
            if step5_geometric_support_domain.event_seed_union is not None and not step5_geometric_support_domain.event_seed_union.is_empty
            else seed_union
        ),
    )
    regularized = True
    expected_continuous_chain_multilobe_geometry = _is_expected_continuous_chain_multilobe_geometry(
        complex_junction=step4_event_interpretation.kind_resolution.complex_junction,
        continuous_chain_applied=step4_event_interpretation.continuous_chain_decision.applied_to_event_interpretation,
        continuous_chain_present=step4_event_interpretation.continuous_chain_decision.is_in_continuous_chain,
        continuous_chain_sequential_ok=step4_event_interpretation.continuous_chain_decision.sequential_ok,
        component_mask_used_support_fallback=step5_geometric_support_domain.component_mask_used_support_fallback,
        parallel_competitor_present=step5_geometric_support_domain.exclusion_context.parallel_competitor_present,
        selected_component_surface_diags=surface_assembly.selected_component_surface_diags,
        complex_multibranch_lobe_diags=surface_assembly.complex_multibranch_lobe_diags,
    )
    successful_connector_count = sum(
        1
        for item in surface_assembly.selected_component_surface_diags
        if str(item.get("component_index", "")).startswith("connector") and bool(item.get("ok", False))
    )
    successful_non_connector_component_count = sum(
        1
        for item in surface_assembly.selected_component_surface_diags
        if not str(item.get("component_index", "")).startswith("connector") and bool(item.get("ok", False))
    )
    prefer_cross_section_surface_geometry = bool(
        step4_event_interpretation.kind_resolution.complex_junction
        and (
            successful_non_connector_component_count >= 3
        )
    )
    if (
        include_event_side_drivezone_in_polygon_union
        and event_side_drivezone_geometry is not None
        and not event_side_drivezone_geometry.is_empty
    ):
        polygon_geometry = polygon_geometry.union(event_side_drivezone_geometry).intersection(drivezone_union).buffer(0)
    selected_support_union = unary_union(
        [
            geometry
            for geometry in [*[road.geometry for road in selected_roads], *[road.geometry for road in selected_rcsd_roads]]
            if geometry is not None and not geometry.is_empty
        ]
    )
    divstrip_guard_clip_applied = False
    if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty and step5_geometric_support_domain.drivezone_component_mask is None:
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
                divstrip_guard_clip_applied = True
    divstrip_event_window_clip_applied = False
    if not divstrip_event_window.is_empty and step5_geometric_support_domain.drivezone_component_mask is None and not allow_full_axis_drivezone_fill:
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
            divstrip_event_window_clip_applied = True
    if divstrip_geometry_to_exclude is None or divstrip_geometry_to_exclude.is_empty:
        divstrip_geometry_to_exclude = local_divstrip_union
    divstrip_exclusion_applied = False
    if divstrip_geometry_to_exclude is not None and not divstrip_geometry_to_exclude.is_empty:
        polygon_without_divstrip = polygon_geometry.difference(
            divstrip_geometry_to_exclude.buffer(DIVSTRIP_EXCLUSION_BUFFER_M, join_style=2)
        ).buffer(0)
        if not polygon_without_divstrip.is_empty:
            polygon_geometry = polygon_without_divstrip
            divstrip_exclusion_applied = True
    preferred_clip_geometry, preferred_clip_mode = _resolve_preferred_polygon_clip_geometry(
        local_surface_clip_geometry=local_surface_clip_geometry,
        axis_window_geometry=axis_window_geometry,
        cross_section_surface_geometry=cross_section_surface_geometry,
        expected_continuous_chain_multilobe_geometry=expected_continuous_chain_multilobe_geometry,
        prefer_cross_section_surface_geometry=prefer_cross_section_surface_geometry,
    )
    preferred_clip_applied = False
    if preferred_clip_geometry is not None and not preferred_clip_geometry.is_empty:
        clipped_polygon = polygon_geometry.intersection(preferred_clip_geometry).buffer(0)
        if not clipped_polygon.is_empty:
            polygon_geometry = clipped_polygon
            preferred_clip_applied = True
    elif cross_section_surface_geometry is not None and not cross_section_surface_geometry.is_empty:
        clipped_polygon = polygon_geometry.intersection(cross_section_surface_geometry).buffer(0)
        if not clipped_polygon.is_empty:
            polygon_geometry = clipped_polygon
            preferred_clip_applied = True
    parallel_side_clip_applied = False
    parallel_side_clip_relaxed = False
    expected_chain_contour_refined = False
    if parallel_side_geometry is not None and not parallel_side_geometry.is_empty:
        local_surface_clip_area_m2 = (
            float(local_surface_clip_geometry.area)
            if local_surface_clip_geometry is not None and not local_surface_clip_geometry.is_empty
            else 0.0
        )
        parallel_side_area_m2 = float(parallel_side_geometry.area)
        relax_expected_multilobe_local_clip_parallel_clip = (
            expected_continuous_chain_multilobe_geometry
            and preferred_clip_mode == "local_surface_clip"
            and preferred_clip_geometry is not None
            and not preferred_clip_geometry.is_empty
            and not step5_geometric_support_domain.exclusion_context.parallel_competitor_present
        )
        relax_small_full_fill_parallel_clip = (
            allow_full_axis_drivezone_fill
            and not step5_geometric_support_domain.exclusion_context.parallel_competitor_present
            and local_surface_clip_area_m2 > 0.0
            and parallel_side_area_m2 / local_surface_clip_area_m2 <= SIMPLE_FULL_FILL_PARALLEL_CLIP_AREA_RATIO_MAX
        )
        relax_simple_continuous_chain_parallel_clip = (
            not allow_full_axis_drivezone_fill
            and step4_event_interpretation.multibranch_decision.enabled
            and step4_event_interpretation.continuous_chain_decision.applied_to_event_interpretation
            and step4_event_interpretation.kind_resolution.kind_resolution_mode == "continuous_chain_divstrip_event"
            and len(divstrip_context["selected_component_ids"]) == 2
            and not surface_assembly.multi_component_surface_applied
            and not surface_assembly.complex_multibranch_lobe_applied
            and not step5_geometric_support_domain.exclusion_context.parallel_competitor_present
        )
        if relax_simple_continuous_chain_parallel_clip or relax_expected_multilobe_local_clip_parallel_clip:
            cleanup_clip_geometry = (
                preferred_clip_geometry
                if preferred_clip_geometry is not None and not preferred_clip_geometry.is_empty
                else axis_window_geometry
            )
            if cleanup_clip_geometry is not None and not cleanup_clip_geometry.is_empty:
                smoothed_polygon = polygon_geometry.convex_hull.intersection(cleanup_clip_geometry).buffer(0)
                if not smoothed_polygon.is_empty and float(smoothed_polygon.area) >= float(polygon_geometry.area) * 0.9:
                    polygon_geometry = smoothed_polygon
            parallel_side_clip_relaxed = True
        elif relax_small_full_fill_parallel_clip:
            parallel_side_clip_relaxed = True
        else:
            clipped_polygon = polygon_geometry.intersection(parallel_side_geometry).buffer(0)
            if not clipped_polygon.is_empty:
                polygon_geometry = clipped_polygon
                parallel_side_clip_applied = True
    if (
        expected_continuous_chain_multilobe_geometry
        and parallel_side_clip_applied
        and preferred_clip_mode == "cross_section_surface"
        and not step5_geometric_support_domain.exclusion_context.parallel_competitor_present
    ):
        refined_polygon_geometry, expected_chain_contour_refined = _refine_expected_continuous_chain_polygon_contour(
            polygon_geometry=polygon_geometry,
            preferred_clip_geometry=preferred_clip_geometry,
            parallel_side_geometry=parallel_side_geometry,
            drivezone_union=drivezone_union,
        )
        if expected_chain_contour_refined:
            polygon_geometry = _regularize_virtual_polygon_geometry(
                geometry=refined_polygon_geometry,
                drivezone_union=drivezone_union,
                seed_geometry=(
                    step5_geometric_support_domain.event_seed_union
                    if step5_geometric_support_domain.event_seed_union is not None
                    and not step5_geometric_support_domain.event_seed_union.is_empty
                    else seed_union
                ),
            )
    full_fill_applied = False
    if (
        allow_full_axis_drivezone_fill
        and include_event_side_drivezone_in_polygon_union
        and event_side_drivezone_geometry is not None
        and not event_side_drivezone_geometry.is_empty
    ):
        full_fill_candidate = polygon_geometry.union(event_side_drivezone_geometry).intersection(drivezone_union).buffer(0)
        if divstrip_geometry_to_exclude is not None and not divstrip_geometry_to_exclude.is_empty:
            full_fill_candidate = full_fill_candidate.difference(
                divstrip_geometry_to_exclude.buffer(DIVSTRIP_EXCLUSION_BUFFER_M, join_style=2)
            ).buffer(0)
        if preferred_clip_geometry is not None and not preferred_clip_geometry.is_empty:
            full_fill_candidate = full_fill_candidate.intersection(preferred_clip_geometry).buffer(0)
        if not full_fill_candidate.is_empty:
            polygon_geometry = full_fill_candidate
            full_fill_applied = True
    if polygon_geometry.is_empty:
        raise Stage4RunError(
            REASON_MAIN_DIRECTION_UNSTABLE,
            "Stage4 regularized polygon is empty.",
        )
    selected_event_corridor_bridge_applied = False
    if (
        not allow_full_axis_drivezone_fill
        and not expected_continuous_chain_multilobe_geometry
        and (
            surface_assembly.multi_component_surface_applied
            or surface_assembly.complex_multibranch_lobe_applied
        )
    ):
        selected_event_union = unary_union(
            [
                geometry
                for geometry in [
                    step5_geometric_support_domain.selected_event_roads_geometry,
                    selected_support_union,
                    *[road.geometry for road in selected_event_roads if road.geometry is not None and not road.geometry.is_empty],
                ]
                if geometry is not None and not geometry.is_empty
            ]
        )
        if selected_event_union is not None and not selected_event_union.is_empty:
            complex_selected_event_corridor_geometry = _build_selected_support_corridor_geometry(
                drivezone_union=drivezone_union,
                clip_geometry=(
                    preferred_clip_geometry
                    if preferred_clip_geometry is not None and not preferred_clip_geometry.is_empty
                    else axis_window_geometry
                ),
                selected_support_union=selected_event_union,
                event_anchor_geometry=event_anchor_geometry,
                support_buffer_m=max(ROAD_BUFFER_M * 3.0, RC_ROAD_BUFFER_M * 2.4, 8.0),
            )
            if (
                complex_selected_event_corridor_geometry is not None
                and not complex_selected_event_corridor_geometry.is_empty
            ):
                merged_candidate = polygon_geometry.union(
                    complex_selected_event_corridor_geometry
                ).intersection(drivezone_union).buffer(0)
                if preferred_clip_geometry is not None and not preferred_clip_geometry.is_empty:
                    merged_candidate = merged_candidate.intersection(preferred_clip_geometry).buffer(0)
                if not merged_candidate.is_empty and float(merged_candidate.area) >= float(polygon_geometry.area) * 0.95:
                    polygon_geometry = _regularize_virtual_polygon_geometry(
                        geometry=merged_candidate,
                        drivezone_union=drivezone_union,
                        seed_geometry=(
                            step5_geometric_support_domain.event_seed_union
                            if step5_geometric_support_domain.event_seed_union is not None
                            and not step5_geometric_support_domain.event_seed_union.is_empty
                            else seed_union
                        ),
                    )
                    selected_event_corridor_bridge_applied = True
    if (
        expected_continuous_chain_multilobe_geometry
        and preferred_clip_mode == "cross_section_surface"
        and preferred_clip_geometry is not None
        and not preferred_clip_geometry.is_empty
    ):
        refined_polygon_geometry, final_expected_chain_contour_refined = _refine_expected_continuous_chain_polygon_contour(
            polygon_geometry=polygon_geometry,
            preferred_clip_geometry=preferred_clip_geometry,
            parallel_side_geometry=parallel_side_geometry,
            drivezone_union=drivezone_union,
        )
        if final_expected_chain_contour_refined:
            polygon_geometry = refined_polygon_geometry
    geometry_risk_signals: list[str] = []
    if step5_geometric_support_domain.component_mask_used_support_fallback:
        geometry_risk_signals.append("component_support_fallback")
    if step5_geometric_support_domain.component_mask_reseeded_after_clip:
        geometry_risk_signals.append("component_reseeded_after_clip")
    if surface_assembly.multi_component_surface_applied and not expected_continuous_chain_multilobe_geometry:
        geometry_risk_signals.append("multi_component_surface")
    if surface_assembly.complex_multibranch_lobe_applied and not expected_continuous_chain_multilobe_geometry:
        geometry_risk_signals.append("complex_multibranch_lobe")
    if surface_assembly.allow_full_axis_drivezone_fill:
        geometry_risk_signals.append("full_axis_drivezone_fill")
    if (
        step5_geometric_support_domain.exclusion_context.parallel_competitor_present
        or parallel_side_clip_applied
    ):
        geometry_risk_signals.append("parallel_side_split")
    if preferred_clip_mode == "cross_section_surface":
        geometry_risk_signals.append("cross_section_only_clip")
    geometry_state = Stage4GeometryState(
        "geometry_built_with_risk" if geometry_risk_signals else "geometry_built"
    )
    support_clip_geometry = (
        event_side_drivezone_geometry
        if event_side_drivezone_geometry is not None and not event_side_drivezone_geometry.is_empty
        else (
            parallel_side_geometry
            if parallel_side_geometry is not None and not parallel_side_geometry.is_empty
            else axis_window_geometry
        )
    )
    legacy_step7_bridge = Stage4LegacyStep7Bridge(
        ready=True,
        reasons=(),
        polygon_geometry=polygon_geometry,
        support_clip_geometry=support_clip_geometry,
        axis_window_geometry=axis_window_geometry,
        parallel_side_geometry=parallel_side_geometry,
        event_side_drivezone_geometry=event_side_drivezone_geometry,
        preferred_clip_geometry=preferred_clip_geometry,
        divstrip_geometry_to_exclude=divstrip_geometry_to_exclude,
    )
    return Stage4PolygonAssemblyResult(
        polygon_geometry=polygon_geometry,
        geometry_state=geometry_state,
        geometry_risk_signals=Stage4GeometryRiskSignals(tuple(geometry_risk_signals)),
        polygon_built=not polygon_geometry.is_empty,
        expected_continuous_chain_multilobe_geometry=expected_continuous_chain_multilobe_geometry,
        selected_event_corridor_bridge_applied=selected_event_corridor_bridge_applied,
        include_event_side_drivezone_in_polygon_union=include_event_side_drivezone_in_polygon_union,
        selected_support_present=not selected_support_union.is_empty,
        divstrip_guard_clip_applied=divstrip_guard_clip_applied,
        divstrip_event_window_clip_applied=divstrip_event_window_clip_applied,
        divstrip_exclusion_applied=divstrip_exclusion_applied,
        preferred_clip_mode=preferred_clip_mode,
        preferred_clip_applied=preferred_clip_applied,
        parallel_side_clip_applied=parallel_side_clip_applied,
        full_fill_applied=full_fill_applied,
        regularized=regularized,
        legacy_step7_bridge=legacy_step7_bridge,
    )

