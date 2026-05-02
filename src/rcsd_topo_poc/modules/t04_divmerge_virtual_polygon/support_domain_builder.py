from __future__ import annotations

from shapely.geometry.base import BaseGeometry

from ._rcsd_selection_support import _normalize_geometry, _union_geometry
from .case_models import T04CaseResult, T04EventUnitResult
from .support_domain_bridges import (
    _case_level_rcsd_bridge_geometries,
    _has_case_level_rcsd_bridge_support,
    _multi_unit_full_fill_bridge_geometries,
    _nearest_bridge_patch,
)
from .support_domain_common import (
    _buffered_patch,
    _clip_to_drivezone,
    _divstrip_void_mask,
    _geometry_summary,
    _loaded_feature_union,
    _required_rcsd_anchor_point,
    _road_buffer_union,
    _section_reference_seed_point,
    _step5_surface_window_config,
)
from .support_domain_cuts import (
    _build_case_terminal_cut_constraints,
    _build_terminal_cut_constraints,
    _expanded_related_road_ids,
    _unique_roads,
)
from .support_domain_models import T04Step5CaseResult, T04Step5UnitResult
from .support_domain_scenario import (
    STEP5_B_NODE_TARGET_PATCH_RADIUS_M,
    STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M,
    STEP5_NEGATIVE_MASK_BUFFER_M,
    STEP5_POINT_PATCH_RADIUS_M,
    STEP5_REQUIRED_NODE_PATCH_RADIUS_M,
    STEP5_SUPPORT_ROAD_BUFFER_M,
    STEP5_SURFACE_LATERAL_LIMIT_M,
    STEP5_SURFACE_SECTION_BACKWARD_M,
    STEP5_SURFACE_SECTION_FORWARD_M,
)
from .support_domain_windows import (
    _build_fallback_support_strip,
    _build_junction_full_road_fill_axis_band,
    _build_junction_full_road_fill_domain,
    _build_terminal_support_corridor,
    _build_terminal_window_domain,
    _seed_connected_fill_domain,
    _should_build_fallback_support_strip,
    _single_surface_component_domain,
    _uses_junction_full_road_fill,
    _uses_junction_window,
)
from .surface_scenario import (
    SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
    SECTION_REFERENCE_NONE,
    SECTION_REFERENCE_POINT_AND_RCSD,
    SECTION_REFERENCE_RCSD,
)


_ACTIVE_RCSD_SECTION_REFERENCES = {
    SECTION_REFERENCE_POINT_AND_RCSD,
    SECTION_REFERENCE_RCSD,
}


def _active_rcsd_road_ids(
    unit_result: T04EventUnitResult,
    config,
) -> tuple[str, ...]:
    if config.section_reference_source in _ACTIVE_RCSD_SECTION_REFERENCES:
        return tuple(unit_result.selected_rcsdroad_ids)
    if config.fallback_rcsdroad_ids:
        return tuple(config.fallback_rcsdroad_ids)
    return ()


def _active_rcsd_node_ids(
    unit_result: T04EventUnitResult,
    config,
) -> tuple[str, ...]:
    if config.section_reference_source in _ACTIVE_RCSD_SECTION_REFERENCES:
        return tuple(unit_result.selected_rcsdnode_ids)
    return ()


def _mask_rcsd_road_ids(
    unit_result: T04EventUnitResult,
    config,
) -> tuple[str, ...]:
    ids = list(_active_rcsd_road_ids(unit_result, config))
    if config.section_reference_source == SECTION_REFERENCE_POINT_AND_RCSD:
        ids.extend(unit_result.pair_local_rcsd_road_ids)
    seen: set[str] = set()
    ordered: list[str] = []
    for road_id in ids:
        key = str(road_id).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return tuple(ordered)


def _active_required_rcsd_node_enabled(config) -> bool:
    return config.section_reference_source in _ACTIVE_RCSD_SECTION_REFERENCES


def _required_rcsd_patch_geometry(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    return _buffered_patch(
        _required_rcsd_anchor_point(unit_result),
        radius_m=STEP5_REQUIRED_NODE_PATCH_RADIUS_M,
        drivezone_union=drivezone_union,
    )


def _build_step5_unit_result(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
    case_external_forbidden_geometry: BaseGeometry | None,
    other_unit_core_occupancy_geometry: BaseGeometry | None,
    divstrip_negative_mask_present: bool,
) -> T04Step5UnitResult:
    bridge = unit_result.interpretation.legacy_step5_bridge
    config = _step5_surface_window_config(unit_result)
    if not config.entity_support_enabled:
        return T04Step5UnitResult(
            event_unit_id=unit_result.spec.event_unit_id,
            event_type=unit_result.spec.event_type,
            review_state=unit_result.review_state,
            positive_rcsd_consistency_level=unit_result.positive_rcsd_consistency_level,
            positive_rcsd_support_level=unit_result.positive_rcsd_support_level,
            required_rcsd_node=unit_result.required_rcsd_node,
            legacy_step5_ready=bool(unit_result.interpretation.legacy_step5_readiness.ready),
            legacy_step5_reasons=tuple(unit_result.interpretation.legacy_step5_readiness.reasons),
            localized_evidence_core_geometry=None,
            fact_reference_patch_geometry=None,
            required_rcsd_node_patch_geometry=None,
            target_b_node_patch_geometry=None,
            fallback_support_strip_geometry=None,
            axis_lateral_band_geometry=None,
            junction_full_road_fill_domain=None,
            unit_must_cover_domain=None,
            unit_allowed_growth_domain=None,
            unit_forbidden_domain=case_external_forbidden_geometry,
            unit_terminal_cut_constraints=None,
            unit_terminal_window_domain=None,
            terminal_support_corridor_geometry=None,
            surface_fill_mode="no_surface",
            surface_fill_axis_half_width_m=None,
            single_component_surface_seed=False,
            support_road_ids=tuple(bridge.selected_road_ids),
            support_event_road_ids=tuple(bridge.selected_event_road_ids),
            positive_rcsd_road_ids=_active_rcsd_road_ids(unit_result, config),
            positive_rcsd_node_ids=_active_rcsd_node_ids(unit_result, config),
            must_cover_components={
                "localized_evidence_core_geometry": False,
                "fact_reference_patch_geometry": False,
                "required_rcsd_node_patch_geometry": False,
                "junction_full_road_fill_domain": False,
                "fallback_support_strip_geometry": False,
                "target_b_node_patch_geometry": False,
            },
            surface_scenario_type=config.surface_scenario_type,
            section_reference_source=config.section_reference_source,
            surface_generation_mode=config.surface_generation_mode,
            reference_point_present=config.reference_point_present,
            surface_scenario_missing=config.surface_scenario_missing,
            support_domain_from_reference_kind=config.support_domain_from_reference_kind,
            surface_section_forward_m=config.surface_section_forward_m,
            surface_section_backward_m=config.surface_section_backward_m,
            surface_lateral_limit_m=config.surface_lateral_limit_m,
            fallback_rcsdroad_ids=config.fallback_rcsdroad_ids,
            fallback_local_window_m=config.fallback_local_window_m,
            fallback_support_strip_area_m2=0.0,
            fallback_rcsdroad_localized=False,
            no_virtual_reference_point_guard=config.no_virtual_reference_point_guard,
            divstrip_negative_mask_present=divstrip_negative_mask_present,
            forbidden_domain_kept=case_external_forbidden_geometry is not None,
        )
    localized_evidence_core_geometry = _clip_to_drivezone(
        unit_result.localized_evidence_core_geometry,
        drivezone_union,
    )
    fact_reference_patch_geometry = (
        _buffered_patch(
            unit_result.fact_reference_point,
            radius_m=STEP5_POINT_PATCH_RADIUS_M,
            drivezone_union=drivezone_union,
        )
        if config.reference_point_present or config.surface_scenario_missing
        else None
    )
    section_reference_patch_geometry = (
        _buffered_patch(
            _section_reference_seed_point(unit_result, config),
            radius_m=STEP5_POINT_PATCH_RADIUS_M,
            drivezone_union=drivezone_union,
        )
        if not config.reference_point_present
        and not config.surface_scenario_missing
        and config.section_reference_source != SECTION_REFERENCE_NONE
        else None
    )
    full_road_fill_requested = _uses_junction_full_road_fill(unit_result)
    junction_window_requested = _uses_junction_window(unit_result)
    required_rcsd_node_patch_geometry = None
    if (
        _active_required_rcsd_node_enabled(config)
        and
        (
            unit_result.positive_rcsd_consistency_level == "A"
            or full_road_fill_requested
            or junction_window_requested
        )
        and unit_result.required_rcsd_node is not None
    ):
        required_rcsd_node_patch_geometry = _required_rcsd_patch_geometry(
            unit_result,
            drivezone_union=drivezone_union,
        )
    target_b_node_patch_geometry = None
    if (
        _active_required_rcsd_node_enabled(config)
        and
        unit_result.positive_rcsd_consistency_level == "B"
        and unit_result.required_rcsd_node is not None
    ):
        target_b_node_patch_geometry = _buffered_patch(
            _required_rcsd_anchor_point(unit_result),
            radius_m=STEP5_B_NODE_TARGET_PATCH_RADIUS_M,
            drivezone_union=drivezone_union,
        )
    fallback_support_strip_geometry = None
    if _should_build_fallback_support_strip(
        unit_result,
        config=config,
        junction_window_requested=junction_window_requested,
    ):
        fallback_support_strip_geometry = _build_fallback_support_strip(
            unit_result,
            drivezone_union=drivezone_union,
        )
    terminal_support_corridor_geometry = _build_terminal_support_corridor(
        unit_result,
        drivezone_union=drivezone_union,
    )
    axis_lateral_band_geometry = _build_junction_full_road_fill_axis_band(
        unit_result,
        drivezone_union=drivezone_union,
    )
    junction_full_road_fill_domain = _build_junction_full_road_fill_domain(
        unit_result,
        drivezone_union=drivezone_union,
    )
    junction_full_road_fill_domain = _seed_connected_fill_domain(
        junction_full_road_fill_domain,
        [
            localized_evidence_core_geometry,
            fact_reference_patch_geometry,
            section_reference_patch_geometry,
            required_rcsd_node_patch_geometry,
            target_b_node_patch_geometry,
        ],
    )
    if junction_window_requested:
        localized_evidence_core_geometry = None
    surface_fill_mode = (
        "junction_window"
        if junction_window_requested and junction_full_road_fill_domain is not None
        else "junction_full_road_fill"
        if junction_full_road_fill_domain is not None
        else "standard"
    )
    surface_fill_axis_half_width_m = (
        STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M
        if junction_full_road_fill_domain is not None
        else None
    )
    single_component_surface_seed = (
        unit_result.evidence_source == "road_surface_fork"
        and junction_full_road_fill_domain is None
    )
    surface_growth_geometries = [
        unit_result.selected_candidate_region_geometry,
        unit_result.selected_component_union_geometry,
        unit_result.pair_local_structure_face_geometry,
    ]
    if junction_window_requested:
        surface_growth_geometries = []
    if single_component_surface_seed:
        surface_component = _single_surface_component_domain(
            _union_geometry(surface_growth_geometries),
            seed_geometries=[
                localized_evidence_core_geometry,
                fact_reference_patch_geometry,
            ],
            forbidden_geometry=case_external_forbidden_geometry,
            drivezone_union=drivezone_union,
        )
        if surface_component is not None:
            surface_growth_geometries = [surface_component]
            if localized_evidence_core_geometry is not None and not localized_evidence_core_geometry.is_empty:
                clipped_core = _normalize_geometry(
                    localized_evidence_core_geometry.intersection(surface_component)
                )
                if clipped_core is not None:
                    localized_evidence_core_geometry = clipped_core
            if fact_reference_patch_geometry is not None and not fact_reference_patch_geometry.is_empty:
                clipped_reference_patch = _normalize_geometry(
                    fact_reference_patch_geometry.intersection(surface_component)
                )
                if clipped_reference_patch is not None:
                    fact_reference_patch_geometry = clipped_reference_patch

    unit_must_cover_domain = _clip_to_drivezone(
        _union_geometry(
            [
                localized_evidence_core_geometry,
                fact_reference_patch_geometry,
                section_reference_patch_geometry,
                required_rcsd_node_patch_geometry,
                junction_full_road_fill_domain,
                fallback_support_strip_geometry,
            ]
        ),
        drivezone_union,
    )
    unit_allowed_growth_domain = _clip_to_drivezone(
        _union_geometry(
            [
                *surface_growth_geometries,
                fallback_support_strip_geometry,
                junction_full_road_fill_domain,
                terminal_support_corridor_geometry,
                target_b_node_patch_geometry,
                unit_must_cover_domain,
            ]
        ),
        drivezone_union,
    )
    other_unit_mask = None
    if other_unit_core_occupancy_geometry is not None and not other_unit_core_occupancy_geometry.is_empty:
        other_unit_mask = _clip_to_drivezone(
            other_unit_core_occupancy_geometry.buffer(STEP5_NEGATIVE_MASK_BUFFER_M),
            drivezone_union,
        )
    unit_forbidden_domain = _clip_to_drivezone(
        _union_geometry(
            [
                case_external_forbidden_geometry,
                other_unit_mask,
            ]
        ),
        drivezone_union,
    )
    unit_terminal_cut_constraints = (
        None
        if config.surface_scenario_type == SCENARIO_NO_MAIN_WITH_SWSD_ONLY
        else _build_terminal_cut_constraints(
            unit_result,
            drivezone_union=drivezone_union,
        )
    )
    unit_terminal_window_domain = _build_terminal_window_domain(
        unit_result,
        drivezone_union=drivezone_union,
    )
    must_cover_components = {
        "localized_evidence_core_geometry": localized_evidence_core_geometry is not None,
        "fact_reference_patch_geometry": fact_reference_patch_geometry is not None,
        "section_reference_patch_geometry": section_reference_patch_geometry is not None,
        "required_rcsd_node_patch_geometry": required_rcsd_node_patch_geometry is not None,
        "junction_full_road_fill_domain": junction_full_road_fill_domain is not None,
        "fallback_support_strip_geometry": fallback_support_strip_geometry is not None,
        "target_b_node_patch_geometry": target_b_node_patch_geometry is not None,
    }
    fallback_summary = _geometry_summary(fallback_support_strip_geometry)
    swsd_only_entity_support_domain = bool(
        config.surface_scenario_type == SCENARIO_NO_MAIN_WITH_SWSD_ONLY
        and junction_full_road_fill_domain is not None
        and not junction_full_road_fill_domain.is_empty
        and unit_must_cover_domain is not None
        and not unit_must_cover_domain.is_empty
        and unit_allowed_growth_domain is not None
        and not unit_allowed_growth_domain.is_empty
    )
    return T04Step5UnitResult(
        event_unit_id=unit_result.spec.event_unit_id,
        event_type=unit_result.spec.event_type,
        review_state=unit_result.review_state,
        positive_rcsd_consistency_level=unit_result.positive_rcsd_consistency_level,
        positive_rcsd_support_level=unit_result.positive_rcsd_support_level,
        required_rcsd_node=unit_result.required_rcsd_node,
        legacy_step5_ready=bool(unit_result.interpretation.legacy_step5_readiness.ready),
        legacy_step5_reasons=tuple(unit_result.interpretation.legacy_step5_readiness.reasons),
        localized_evidence_core_geometry=localized_evidence_core_geometry,
        fact_reference_patch_geometry=fact_reference_patch_geometry,
        required_rcsd_node_patch_geometry=required_rcsd_node_patch_geometry,
        target_b_node_patch_geometry=target_b_node_patch_geometry,
        fallback_support_strip_geometry=fallback_support_strip_geometry,
        axis_lateral_band_geometry=axis_lateral_band_geometry,
        section_reference_patch_geometry=section_reference_patch_geometry,
        junction_full_road_fill_domain=junction_full_road_fill_domain,
        unit_must_cover_domain=unit_must_cover_domain,
        unit_allowed_growth_domain=unit_allowed_growth_domain,
        unit_forbidden_domain=unit_forbidden_domain,
        unit_terminal_cut_constraints=unit_terminal_cut_constraints,
        unit_terminal_window_domain=unit_terminal_window_domain,
        terminal_support_corridor_geometry=terminal_support_corridor_geometry,
        surface_fill_mode=surface_fill_mode,
        surface_fill_axis_half_width_m=surface_fill_axis_half_width_m,
        single_component_surface_seed=single_component_surface_seed,
        support_road_ids=tuple(bridge.selected_road_ids),
        support_event_road_ids=tuple(bridge.selected_event_road_ids),
        positive_rcsd_road_ids=_active_rcsd_road_ids(unit_result, config),
        positive_rcsd_node_ids=_active_rcsd_node_ids(unit_result, config),
        must_cover_components=must_cover_components,
        surface_scenario_type=config.surface_scenario_type,
        section_reference_source=config.section_reference_source,
        surface_generation_mode=config.surface_generation_mode,
        reference_point_present=config.reference_point_present,
        surface_scenario_missing=config.surface_scenario_missing,
        support_domain_from_reference_kind=config.support_domain_from_reference_kind,
        surface_section_forward_m=config.surface_section_forward_m,
        surface_section_backward_m=config.surface_section_backward_m,
        surface_lateral_limit_m=config.surface_lateral_limit_m,
        fallback_rcsdroad_ids=config.fallback_rcsdroad_ids,
        fallback_local_window_m=config.fallback_local_window_m,
        fallback_support_strip_area_m2=float(fallback_summary["area_m2"]),
        fallback_rcsdroad_localized=bool(config.fallback_rcsdroad_ids and fallback_support_strip_geometry is not None),
        no_virtual_reference_point_guard=(
            config.no_virtual_reference_point_guard
            and (config.reference_point_present or fact_reference_patch_geometry is None)
        ),
        divstrip_negative_mask_present=divstrip_negative_mask_present,
        forbidden_domain_kept=case_external_forbidden_geometry is not None,
        swsd_only_entity_support_domain=swsd_only_entity_support_domain,
    )

def build_step5_support_domain(case_result: T04CaseResult) -> T04Step5CaseResult:
    drivezone_union = _loaded_feature_union(case_result.case_bundle.drivezone_features)
    surface_configs = {
        event_unit.spec.event_unit_id: _step5_surface_window_config(event_unit)
        for event_unit in case_result.event_units
    }
    external_support_roads = _unique_roads(
        road
        for event_unit in case_result.event_units
        for road in (
            *event_unit.interpretation.legacy_step5_bridge.selected_roads,
            *event_unit.interpretation.legacy_step5_bridge.selected_event_roads,
            *event_unit.interpretation.legacy_step5_bridge.complex_local_support_roads,
        )
    )
    seed_swsd_road_ids = {
        str(getattr(road, "road_id", "") or "").strip()
        for road in external_support_roads
        if str(getattr(road, "road_id", "") or "").strip()
    }
    seed_rcsd_road_ids: set[str] = set()
    expandable_rcsd_road_ids: set[str] = set()
    for event_unit in case_result.event_units:
        config = surface_configs[event_unit.spec.event_unit_id]
        mask_ids = {
            str(road_id)
            for road_id in _mask_rcsd_road_ids(event_unit, config)
            if str(road_id).strip()
        }
        seed_rcsd_road_ids.update(mask_ids)
        if config.section_reference_source == SECTION_REFERENCE_POINT_AND_RCSD and 0 < len(mask_ids) <= 4:
            expandable_rcsd_road_ids.update(mask_ids)
    current_semantic_node_ids = {
        str(node.node_id)
        for node in (case_result.case_bundle.representative_node, *case_result.case_bundle.group_nodes)
        if str(getattr(node, "node_id", "") or "").strip()
    }
    related_swsd_road_ids = _expanded_related_road_ids(
        seed_road_ids=seed_swsd_road_ids,
        roads=case_result.case_bundle.roads,
        current_semantic_node_ids=current_semantic_node_ids,
    )
    related_rcsd_road_ids = set(seed_rcsd_road_ids)
    if expandable_rcsd_road_ids:
        related_rcsd_road_ids.update(
            _expanded_related_road_ids(
                seed_road_ids=expandable_rcsd_road_ids,
                roads=case_result.case_bundle.rcsd_roads,
                current_semantic_node_ids=current_semantic_node_ids,
            )
        )
    unrelated_swsd_mask_geometry = _clip_to_drivezone(
        _union_geometry(
            road.geometry.buffer(STEP5_NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2)
            for road in case_result.case_bundle.roads
            if str(road.road_id) not in related_swsd_road_ids
        ),
        drivezone_union,
    )
    unrelated_rcsd_mask_geometry = _clip_to_drivezone(
        _union_geometry(
            road.geometry.buffer(STEP5_NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2)
            for road in case_result.case_bundle.rcsd_roads
            if str(road.road_id) not in related_rcsd_road_ids
        ),
        drivezone_union,
    )
    divstrip_void_mask_geometry = _divstrip_void_mask(
        case_result,
        drivezone_union=drivezone_union,
    )
    case_external_forbidden_geometry = _clip_to_drivezone(
        _union_geometry(
            [
                unrelated_swsd_mask_geometry,
                unrelated_rcsd_mask_geometry,
                divstrip_void_mask_geometry,
            ]
        ),
        drivezone_union,
    )
    unit_core_occupancies: dict[str, BaseGeometry | None] = {}
    precomputed_components: dict[str, dict[str, BaseGeometry | None]] = {}
    for event_unit in case_result.event_units:
        config = surface_configs[event_unit.spec.event_unit_id]
        junction_window_requested = _uses_junction_window(event_unit)
        localized_evidence_core_geometry = _clip_to_drivezone(
            None if junction_window_requested or not config.entity_support_enabled else event_unit.localized_evidence_core_geometry,
            drivezone_union,
        )
        required_rcsd_node_patch_geometry = None
        if (
            config.entity_support_enabled
            and _active_required_rcsd_node_enabled(config)
            and
            (
                event_unit.positive_rcsd_consistency_level == "A"
                or _uses_junction_full_road_fill(event_unit)
                or junction_window_requested
            )
            and event_unit.required_rcsd_node is not None
        ):
            required_rcsd_node_patch_geometry = _required_rcsd_patch_geometry(
                event_unit,
                drivezone_union=drivezone_union,
            )
        fallback_support_strip_geometry = None
        if _should_build_fallback_support_strip(
            event_unit,
            config=config,
            junction_window_requested=junction_window_requested,
        ):
            fallback_support_strip_geometry = _build_fallback_support_strip(
                event_unit,
                drivezone_union=drivezone_union,
            )
        unit_core_occupancies[event_unit.spec.event_unit_id] = _clip_to_drivezone(
            _union_geometry(
                [
                    localized_evidence_core_geometry,
                    required_rcsd_node_patch_geometry,
                    fallback_support_strip_geometry,
                ]
            ),
            drivezone_union,
        )
        precomputed_components[event_unit.spec.event_unit_id] = {
            "localized_evidence_core_geometry": localized_evidence_core_geometry,
            "required_rcsd_node_patch_geometry": required_rcsd_node_patch_geometry,
            "fallback_support_strip_geometry": fallback_support_strip_geometry,
        }

    unit_results: list[T04Step5UnitResult] = []
    for event_unit in case_result.event_units:
        other_core_geometry = _union_geometry(
            geometry
            for other_unit_id, geometry in unit_core_occupancies.items()
            if other_unit_id != event_unit.spec.event_unit_id
        )
        unit_results.append(
            _build_step5_unit_result(
                event_unit,
                drivezone_union=drivezone_union,
                case_external_forbidden_geometry=case_external_forbidden_geometry,
                other_unit_core_occupancy_geometry=other_core_geometry,
                divstrip_negative_mask_present=divstrip_void_mask_geometry is not None,
            )
        )

    base_case_must_cover_domain = _clip_to_drivezone(
        _union_geometry(unit.unit_must_cover_domain for unit in unit_results),
        drivezone_union,
    )
    base_allowed_geometries = [unit.unit_allowed_growth_domain for unit in unit_results]
    case_support_graph_geometry = _clip_to_drivezone(
        _union_geometry(
            [
                *base_allowed_geometries,
                _road_buffer_union(
                    external_support_roads,
                    buffer_m=STEP5_SUPPORT_ROAD_BUFFER_M,
                    drivezone_union=drivezone_union,
                ),
            ]
        ),
        drivezone_union,
    )
    full_fill_bridge_geometries = _multi_unit_full_fill_bridge_geometries(
        unit_results,
        support_graph_geometry=case_support_graph_geometry,
        drivezone_union=drivezone_union,
    )
    case_level_rcsd_bridge_geometries = _case_level_rcsd_bridge_geometries(
        unit_results,
        support_graph_geometry=case_support_graph_geometry,
        drivezone_union=drivezone_union,
    )
    case_must_cover_domain = _clip_to_drivezone(
        _union_geometry([base_case_must_cover_domain, *case_level_rcsd_bridge_geometries]),
        drivezone_union,
    )
    bridge_geometries: list[BaseGeometry] = []
    unit_allowed_non_empty = [
        unit.unit_allowed_growth_domain
        for unit in unit_results
        if unit.unit_allowed_growth_domain is not None and not unit.unit_allowed_growth_domain.is_empty
    ]
    if len(unit_allowed_non_empty) > 1:
        current_geometry = unit_allowed_non_empty[0]
        remaining = list(unit_allowed_non_empty[1:])
        while remaining:
            best_index = 0
            best_distance = float("inf")
            for index, candidate in enumerate(remaining):
                distance = float(current_geometry.distance(candidate))
                if distance < best_distance:
                    best_distance = distance
                    best_index = index
            candidate = remaining.pop(best_index)
            bridge_geometry = _nearest_bridge_patch(
                current_geometry,
                candidate,
                support_graph_geometry=case_support_graph_geometry,
                drivezone_union=drivezone_union,
            )
            if bridge_geometry is not None and not bridge_geometry.is_empty:
                bridge_geometries.append(bridge_geometry)
                current_geometry = _clip_to_drivezone(
                    _union_geometry([current_geometry, candidate, bridge_geometry]),
                    drivezone_union,
                ) or current_geometry
            else:
                current_geometry = _clip_to_drivezone(
                    _union_geometry([current_geometry, candidate]),
                    drivezone_union,
                ) or current_geometry
    case_bridge_zone_geometry = _clip_to_drivezone(
        _union_geometry(
            [*bridge_geometries, *full_fill_bridge_geometries, *case_level_rcsd_bridge_geometries]
        ),
        drivezone_union,
    )
    case_allowed_growth_domain = _clip_to_drivezone(
        _union_geometry(
            [
                *base_allowed_geometries,
                case_bridge_zone_geometry,
            ]
        ),
        drivezone_union,
    )
    case_forbidden_domain = case_external_forbidden_geometry
    case_terminal_cut_constraints = _build_case_terminal_cut_constraints(
        case_result,
        unit_results=unit_results,
        drivezone_union=drivezone_union,
    )
    case_terminal_window_domain = _clip_to_drivezone(
        _union_geometry(
            [
                *(unit.unit_terminal_window_domain for unit in unit_results),
                *full_fill_bridge_geometries,
                *case_level_rcsd_bridge_geometries,
                case_bridge_zone_geometry
                if _has_case_level_rcsd_bridge_support(unit_results)
                else None,
            ]
        ),
        drivezone_union,
    )
    case_terminal_support_corridor_geometry = _clip_to_drivezone(
        _union_geometry(unit.terminal_support_corridor_geometry for unit in unit_results),
        drivezone_union,
    )
    return T04Step5CaseResult(
        case_id=case_result.case_spec.case_id,
        unit_results=tuple(unit_results),
        case_must_cover_domain=case_must_cover_domain,
        case_allowed_growth_domain=case_allowed_growth_domain,
        case_forbidden_domain=case_forbidden_domain,
        case_terminal_cut_constraints=case_terminal_cut_constraints,
        case_terminal_window_domain=case_terminal_window_domain,
        case_terminal_support_corridor_geometry=case_terminal_support_corridor_geometry,
        case_bridge_zone_geometry=case_bridge_zone_geometry,
        case_support_graph_geometry=case_support_graph_geometry,
        unrelated_swsd_mask_geometry=unrelated_swsd_mask_geometry,
        unrelated_rcsd_mask_geometry=unrelated_rcsd_mask_geometry,
        divstrip_void_mask_geometry=divstrip_void_mask_geometry,
        drivezone_outside_enforced_by_allowed_domain=True,
        related_swsd_road_ids=tuple(sorted(related_swsd_road_ids)),
        related_rcsd_road_ids=tuple(sorted(related_rcsd_road_ids)),
        surface_section_forward_m=STEP5_SURFACE_SECTION_FORWARD_M,
        surface_section_backward_m=STEP5_SURFACE_SECTION_BACKWARD_M,
        surface_lateral_limit_m=STEP5_SURFACE_LATERAL_LIMIT_M,
        no_virtual_reference_point_guard=all(unit.no_virtual_reference_point_guard for unit in unit_results),
        forbidden_domain_kept=case_forbidden_domain is not None,
        divstrip_negative_mask_present=divstrip_void_mask_geometry is not None,
    )
