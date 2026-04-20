from __future__ import annotations

from dataclasses import replace
from typing import Iterable

from shapely.geometry import GeometryCollection
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

from rcsd_topo_poc.modules.t02_junction_anchor.shared import normalize_id
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_geometry_utils import (
    _node_source_kind_2,
    _explode_component_geometries,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step4_event_interpretation import (
    _build_stage4_event_interpretation,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    _resolve_group,
)

from .admission import build_step1_admission
from .case_models import (
    T04CaseBundle,
    T04CaseResult,
    T04EventUnitResult,
    T04UnitContext,
)
from .event_units import build_event_unit_specs
from .local_context import build_step2_local_context
from .topology import build_step3_topology


DIVSTRIP_EVIDENCE_TIP_RADIUS_M = 8.0
SHARED_EVIDENCE_OVERLAP_AREA_M2 = 8.0
SHARED_EVIDENCE_OVERLAP_RATIO = 0.2
EVENT_REFERENCE_CONFLICT_TOL_M = 5.0
COMPLEX_SUBUNIT_SCOPE_RADIUS_M = 60.0
COMPLEX_SUBUNIT_ROAD_PAD_M = 10.0
COMPLEX_SUBUNIT_DIVSTRIP_PAD_M = 12.0
COMPLEX_SUBUNIT_RCSD_PAD_M = 18.0


def _singleton_group(node) -> tuple:
    return (node,)


def _seed_union(*, representative_node, group_nodes, local_context):
    seed_geometries: list[BaseGeometry] = [
        representative_node.geometry,
        *[node.geometry for node in group_nodes],
        *[node.geometry for node in local_context.exact_target_rc_nodes],
    ]
    return unary_union(seed_geometries)


def _prepare_unit_context(
    *,
    case_bundle: T04CaseBundle,
    representative_node_id: str,
    singleton_group: bool,
) -> T04UnitContext:
    representative_node = next(node for node in case_bundle.nodes if node.node_id == representative_node_id)
    if singleton_group:
        group_nodes = _singleton_group(representative_node)
    else:
        _resolved_rep, resolved_group_nodes = _resolve_group(
            mainnodeid=normalize_id(representative_node.mainnodeid or representative_node.node_id),
            nodes=list(case_bundle.nodes),
        )
        group_nodes = tuple(resolved_group_nodes)
    admission = build_step1_admission(representative_node=representative_node, group_nodes=group_nodes)
    local_context = build_step2_local_context(
        case_bundle=case_bundle,
        representative_node=representative_node,
        group_nodes=group_nodes,
    )
    topology_skeleton = build_step3_topology(
        representative_node=representative_node,
        group_nodes=group_nodes,
        local_context=local_context,
    )
    return T04UnitContext(
        representative_node=representative_node,
        group_nodes=group_nodes,
        admission=admission,
        local_context=local_context,
        topology_skeleton=topology_skeleton,
    )


def _filter_branch_scope(unit_context: T04UnitContext, selected_side_branch_ids: tuple[str, ...]):
    branch_result = unit_context.topology_skeleton.branch_result
    road_branches = list(branch_result.road_branches)
    if not selected_side_branch_ids:
        return road_branches, list(unit_context.local_context.patch_roads), set(branch_result.main_branch_ids)

    allowed_branch_ids = set(branch_result.main_branch_ids) | {str(item) for item in selected_side_branch_ids}
    filtered_branches = [
        branch
        for branch in road_branches
        if str(branch.branch_id) in allowed_branch_ids
    ]
    if len(filtered_branches) < 2:
        return road_branches, list(unit_context.local_context.patch_roads), set(branch_result.main_branch_ids)

    allowed_road_ids = {
        str(road_id)
        for branch in filtered_branches
        for road_id in branch.road_ids
    }
    filtered_roads = [
        road
        for road in unit_context.local_context.patch_roads
        if str(road.road_id) in allowed_road_ids
    ]
    return filtered_branches, filtered_roads, set(branch_result.main_branch_ids) & {
        str(branch.branch_id) for branch in filtered_branches
    }


def _positive_rcsd_geometry(geometries: Iterable[BaseGeometry | None]):
    valid = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not valid:
        return GeometryCollection()
    return unary_union(valid)


def _effective_complex_kind_hint(
    *,
    case_bundle: T04CaseBundle,
    unit_context: T04UnitContext,
    event_unit_spec,
):
    if event_unit_spec.split_mode != "complex_one_node_one_unit":
        return unit_context.representative_node, unit_context.admission.source_kind_2
    parent_kind_2 = _node_source_kind_2(case_bundle.representative_node)
    if parent_kind_2 is None:
        return unit_context.representative_node, unit_context.admission.source_kind_2
    if _node_source_kind_2(unit_context.representative_node) == parent_kind_2:
        return unit_context.representative_node, unit_context.admission.source_kind_2
    return replace(unit_context.representative_node, kind_2=parent_kind_2), parent_kind_2


def _materialize_event_reference_point(
    *,
    interpretation,
    selected_divstrip_geometry,
):
    point = interpretation.legacy_step5_bridge.event_origin_point
    if point is None or point.is_empty:
        return point
    if interpretation.event_reference.event_position_source != "divstrip_ref":
        return point
    preferred_geometry = selected_divstrip_geometry
    if preferred_geometry is None or preferred_geometry.is_empty:
        return point
    if preferred_geometry.buffer(1e-6).covers(point):
        return point
    snapped_point = nearest_points(point, preferred_geometry)[1]
    if snapped_point is None or snapped_point.is_empty:
        return point
    return snapped_point


def _materialize_selected_divstrip_geometry(
    *,
    interpretation,
    selected_divstrip_geometry,
    localized_divstrip_geometry,
):
    preferred_geometry = (
        localized_divstrip_geometry
        if localized_divstrip_geometry is not None and not localized_divstrip_geometry.is_empty
        else selected_divstrip_geometry
    )
    if preferred_geometry is None or preferred_geometry.is_empty:
        return preferred_geometry
    raw_point = interpretation.legacy_step5_bridge.event_origin_point
    if raw_point is None or raw_point.is_empty:
        return preferred_geometry
    polygon_components = [
        component
        for component in _explode_component_geometries(preferred_geometry)
        if getattr(component, "geom_type", None) == "Polygon" and not component.is_empty
    ]
    if polygon_components:
        covering_components = [
            component
            for component in polygon_components
            if component.buffer(1e-6).covers(raw_point)
        ]
        if covering_components:
            preferred_geometry = unary_union(covering_components).buffer(0)
        elif len(polygon_components) > 1:
            preferred_geometry = min(
                polygon_components,
                key=lambda component: float(component.distance(raw_point)),
            )
    support_point = (
        raw_point
        if preferred_geometry.buffer(1e-6).covers(raw_point)
        else nearest_points(raw_point, preferred_geometry)[1]
    )
    if support_point is None or support_point.is_empty:
        return preferred_geometry
    localized_tip_patch = preferred_geometry.intersection(
        support_point.buffer(DIVSTRIP_EVIDENCE_TIP_RADIUS_M, join_style=2)
    ).buffer(0)
    if localized_tip_patch is None or localized_tip_patch.is_empty:
        return preferred_geometry
    return localized_tip_patch


def _materialize_event_anchor_geometry(
    *,
    interpretation,
    selected_divstrip_geometry,
    drivezone_union,
):
    anchor_geometry = interpretation.legacy_step5_bridge.event_anchor_geometry
    if anchor_geometry is None or anchor_geometry.is_empty:
        return anchor_geometry
    if (
        not interpretation.continuous_chain_decision.sequential_ok
        or selected_divstrip_geometry is None
        or selected_divstrip_geometry.is_empty
        or anchor_geometry.intersects(selected_divstrip_geometry)
    ):
        return anchor_geometry
    coarse_anchor = selected_divstrip_geometry.buffer(1.5, join_style=2)
    if drivezone_union is not None and not drivezone_union.is_empty:
        coarse_anchor = coarse_anchor.intersection(drivezone_union).buffer(0)
    return coarse_anchor if coarse_anchor is not None and not coarse_anchor.is_empty else anchor_geometry


def _scope_complex_step4_inputs(
    *,
    event_unit_spec,
    unit_context: T04UnitContext,
    filtered_branches,
    filtered_roads,
):
    local_context = unit_context.local_context
    if event_unit_spec.split_mode != "complex_one_node_one_unit":
        return (
            filtered_branches,
            filtered_roads,
            list(local_context.local_rcsd_roads),
            list(local_context.local_rcsd_nodes),
            list(local_context.patch_divstrip_features),
        )

    scope_geometry = unit_context.representative_node.geometry.buffer(
        COMPLEX_SUBUNIT_SCOPE_RADIUS_M,
        join_style=2,
    )
    if local_context.patch_drivezone_union is not None and not local_context.patch_drivezone_union.is_empty:
        clipped_scope = scope_geometry.intersection(
            local_context.patch_drivezone_union.buffer(COMPLEX_SUBUNIT_ROAD_PAD_M, join_style=2)
        ).buffer(0)
        if clipped_scope is not None and not clipped_scope.is_empty:
            scope_geometry = clipped_scope

    road_scope = scope_geometry.buffer(COMPLEX_SUBUNIT_ROAD_PAD_M, join_style=2)
    divstrip_scope = scope_geometry.buffer(COMPLEX_SUBUNIT_DIVSTRIP_PAD_M, join_style=2)
    rcsd_scope = scope_geometry.buffer(COMPLEX_SUBUNIT_RCSD_PAD_M, join_style=2)

    scoped_roads = [
        road
        for road in filtered_roads
        if road.geometry is not None and not road.geometry.is_empty and road.geometry.intersects(road_scope)
    ]
    if len(scoped_roads) < 2:
        scoped_roads = list(filtered_roads)

    scoped_branch_ids = {
        str(branch.branch_id)
        for branch in filtered_branches
        if any(str(road_id) in {str(road.road_id) for road in scoped_roads} for road_id in branch.road_ids)
    }
    scoped_branches = [
        branch
        for branch in filtered_branches
        if str(branch.branch_id) in scoped_branch_ids
    ]
    if len(scoped_branches) < 2:
        scoped_branches = list(filtered_branches)

    scoped_rcsd_roads = [
        road
        for road in local_context.local_rcsd_roads
        if road.geometry is not None and not road.geometry.is_empty and road.geometry.intersects(rcsd_scope)
    ] or list(local_context.local_rcsd_roads)
    scoped_rcsd_nodes = [
        node
        for node in local_context.local_rcsd_nodes
        if node.geometry is not None and not node.geometry.is_empty and node.geometry.intersects(rcsd_scope)
    ] or list(local_context.local_rcsd_nodes)
    scoped_divstrip_features = [
        feature
        for feature in local_context.patch_divstrip_features
        if feature.geometry is not None and not feature.geometry.is_empty and feature.geometry.intersects(divstrip_scope)
    ] or list(local_context.patch_divstrip_features)

    return (
        scoped_branches,
        scoped_roads,
        scoped_rcsd_roads,
        scoped_rcsd_nodes,
        scoped_divstrip_features,
    )


def _build_unit_result(
    *,
    case_bundle: T04CaseBundle,
    unit_context: T04UnitContext,
    event_unit_spec,
) -> T04EventUnitResult:
    effective_representative_node, effective_source_kind_2 = _effective_complex_kind_hint(
        case_bundle=case_bundle,
        unit_context=unit_context,
        event_unit_spec=event_unit_spec,
    )
    filtered_branches, filtered_roads, main_branch_ids = _filter_branch_scope(
        unit_context,
        event_unit_spec.selected_side_branch_ids,
    )
    local_context = unit_context.local_context
    (
        scoped_branches,
        scoped_roads,
        scoped_rcsd_roads,
        scoped_rcsd_nodes,
        scoped_divstrip_features,
    ) = _scope_complex_step4_inputs(
        event_unit_spec=event_unit_spec,
        unit_context=unit_context,
        filtered_branches=filtered_branches,
        filtered_roads=filtered_roads,
    )
    interpretation = _build_stage4_event_interpretation(
        representative_node=effective_representative_node,
        representative_source_kind_2=effective_source_kind_2,
        mainnodeid_norm=unit_context.admission.mainnodeid,
        seed_union=_seed_union(
            representative_node=effective_representative_node,
            group_nodes=unit_context.group_nodes,
            local_context=local_context,
        ),
        group_nodes=list(unit_context.group_nodes),
        patch_size_m=float(local_context.patch_size_m),
        seed_center=local_context.seed_center,
        drivezone_union=local_context.patch_drivezone_union,
        local_roads=scoped_roads,
        local_rcsd_roads=scoped_rcsd_roads,
        local_rcsd_nodes=scoped_rcsd_nodes,
        local_divstrip_features=scoped_divstrip_features,
        road_branches=scoped_branches,
        main_branch_ids=main_branch_ids,
        member_node_ids=set(unit_context.topology_skeleton.branch_result.augmented_member_node_ids),
        direct_target_rc_nodes=list(local_context.direct_target_rc_nodes),
        exact_target_rc_nodes=list(local_context.exact_target_rc_nodes),
        primary_main_rc_node=local_context.primary_main_rc_node,
        rcsdnode_seed_mode=local_context.rcsdnode_seed_mode,
        chain_context=unit_context.topology_skeleton.chain_context.to_legacy_dict(),
    )
    bridge = interpretation.legacy_step5_bridge
    localized_divstrip_geometry = bridge.localized_divstrip_reference_geometry
    selected_divstrip_geometry = _materialize_selected_divstrip_geometry(
        interpretation=interpretation,
        selected_divstrip_geometry=bridge.divstrip_context.constraint_geometry,
        localized_divstrip_geometry=localized_divstrip_geometry,
    )
    event_anchor_geometry = _materialize_event_anchor_geometry(
        interpretation=interpretation,
        selected_divstrip_geometry=selected_divstrip_geometry,
        drivezone_union=local_context.patch_drivezone_union,
    )
    event_reference_point = _materialize_event_reference_point(
        interpretation=interpretation,
        selected_divstrip_geometry=selected_divstrip_geometry,
    )
    positive_rcsd_geometry = _positive_rcsd_geometry(
        [
            *[road.geometry for road in bridge.selected_rcsd_roads],
            *[node.geometry for node in bridge.selected_rcsd_nodes],
        ]
    )
    rcsd_consistency_result = "missing_positive_rcsd"
    if bridge.selected_rcsd_roads and bridge.effective_target_rc_nodes:
        rcsd_consistency_result = "positive_rcsd_consistent"
    elif bridge.selected_rcsd_roads:
        rcsd_consistency_result = "positive_rcsd_without_target_node"
    elif bridge.selected_rcsd_nodes:
        rcsd_consistency_result = "positive_rcsd_node_only"

    review_reasons: list[str] = list(interpretation.review_signals)
    fail_reasons: list[str] = list(interpretation.hard_rejection_signals)
    fail_reasons.extend(interpretation.legacy_step5_readiness.reasons)
    if bridge.event_origin_point is None:
        fail_reasons.append("missing_event_reference_point")
    if not bridge.selected_branch_ids:
        fail_reasons.append("selected_branch_ids_empty")
    if rcsd_consistency_result != "positive_rcsd_consistent":
        review_reasons.append(rcsd_consistency_result)
    if interpretation.evidence_decision.fallback_used:
        review_reasons.append("fallback_to_weak_evidence")

    if fail_reasons:
        review_state = "STEP4_FAIL"
        all_reasons = tuple(dict.fromkeys([*fail_reasons, *review_reasons]))
    elif review_reasons:
        review_state = "STEP4_REVIEW"
        all_reasons = tuple(dict.fromkeys(review_reasons))
    else:
        review_state = "STEP4_OK"
        all_reasons = ()

    return T04EventUnitResult(
        spec=event_unit_spec,
        unit_context=unit_context,
        interpretation=interpretation,
        review_state=review_state,
        review_reasons=all_reasons,
        evidence_source=interpretation.evidence_decision.primary_source,
        position_source=interpretation.event_reference.event_position_source,
        reverse_tip_used=interpretation.reverse_tip_decision.used,
        rcsd_consistency_result=rcsd_consistency_result,
        selected_divstrip_geometry=selected_divstrip_geometry,
        event_anchor_geometry=event_anchor_geometry,
        event_reference_point=event_reference_point,
        positive_rcsd_geometry=positive_rcsd_geometry,
        selected_branch_ids=tuple(bridge.selected_branch_ids),
        selected_event_branch_ids=tuple(bridge.selected_event_branch_ids),
        selected_component_ids=tuple(bridge.divstrip_context.selected_component_ids),
        event_axis_branch_id=bridge.event_axis_branch_id,
        event_chosen_s_m=interpretation.event_reference.event_chosen_s_m,
    )


def _apply_evidence_ownership_guards(
    event_units: list[T04EventUnitResult],
) -> list[T04EventUnitResult]:
    seen_geometries: list[tuple[str, BaseGeometry]] = []
    seen_component_ids: dict[str, list[str]] = {}
    seen_positions: dict[str, list[tuple[str, float]]] = {}
    guarded: list[T04EventUnitResult] = []
    for event_unit in event_units:
        extra_review_notes = list(event_unit.extra_review_notes)
        hard_fail = False
        current_geometry = event_unit.selected_divstrip_geometry
        conflict_unit_ids: set[str] = set()

        for component_id in event_unit.selected_component_ids:
            prior_units = seen_component_ids.get(str(component_id), [])
            if not prior_units:
                continue
            hard_fail = True
            for prior_unit_id in prior_units:
                conflict_unit_ids.add(prior_unit_id)
                extra_review_notes.append(f"shared_divstrip_component_with:{prior_unit_id}")

        axis_branch_id = None if event_unit.event_axis_branch_id is None else str(event_unit.event_axis_branch_id)
        chosen_s = None if event_unit.event_chosen_s_m is None else float(event_unit.event_chosen_s_m)
        if axis_branch_id is not None and chosen_s is not None:
            for prior_unit_id, prior_s in seen_positions.get(axis_branch_id, []):
                if abs(float(prior_s) - chosen_s) <= EVENT_REFERENCE_CONFLICT_TOL_M + 1e-9:
                    hard_fail = True
                    conflict_unit_ids.add(prior_unit_id)
                    extra_review_notes.append(f"shared_event_reference_with:{prior_unit_id}")

        if current_geometry is not None and not current_geometry.is_empty:
            current_area = float(getattr(current_geometry, "area", 0.0) or 0.0)
            for prior_unit_id, prior_geometry in seen_geometries:
                if prior_geometry is None or prior_geometry.is_empty:
                    continue
                overlap_geometry = current_geometry.intersection(prior_geometry).buffer(0)
                overlap_area = float(getattr(overlap_geometry, "area", 0.0) or 0.0)
                if overlap_area <= 1e-6:
                    continue
                prior_area = float(getattr(prior_geometry, "area", 0.0) or 0.0)
                smaller_area = min(current_area, prior_area)
                overlap_ratio = 0.0 if smaller_area <= 1e-6 else overlap_area / smaller_area
                if (
                    overlap_area >= SHARED_EVIDENCE_OVERLAP_AREA_M2
                    or overlap_ratio >= SHARED_EVIDENCE_OVERLAP_RATIO
                ):
                    hard_fail = True
                    conflict_unit_ids.add(prior_unit_id)
                    extra_review_notes.append(f"shared_event_core_segment_with:{prior_unit_id}")
            seen_geometries.append((event_unit.spec.event_unit_id, current_geometry))

        for component_id in event_unit.selected_component_ids:
            seen_component_ids.setdefault(str(component_id), []).append(event_unit.spec.event_unit_id)
        if axis_branch_id is not None and chosen_s is not None:
            seen_positions.setdefault(axis_branch_id, []).append((event_unit.spec.event_unit_id, chosen_s))

        if extra_review_notes:
            review_state = "STEP4_FAIL" if hard_fail or event_unit.review_state == "STEP4_OK" else event_unit.review_state
            guarded.append(
                replace(
                    event_unit,
                    review_state="STEP4_FAIL" if hard_fail else (review_state if review_state == "STEP4_FAIL" else "STEP4_REVIEW"),
                    extra_review_notes=tuple(extra_review_notes),
                )
            )
            continue
        guarded.append(event_unit)
    return guarded


def build_case_result(case_bundle: T04CaseBundle) -> T04CaseResult:
    admission = build_step1_admission(
        representative_node=case_bundle.representative_node,
        group_nodes=case_bundle.group_nodes,
    )
    base_context = _prepare_unit_context(
        case_bundle=case_bundle,
        representative_node_id=case_bundle.representative_node.node_id,
        singleton_group=False,
    )
    event_unit_specs = build_event_unit_specs(case_bundle=case_bundle, unit_context=base_context)
    unit_context_cache: dict[tuple[str, bool], T04UnitContext] = {
        (base_context.representative_node.node_id, False): base_context,
    }
    event_units: list[T04EventUnitResult] = []
    for event_unit_spec in event_unit_specs:
        singleton_group = event_unit_spec.split_mode == "complex_one_node_one_unit"
        cache_key = (event_unit_spec.representative_node_id, singleton_group)
        if cache_key not in unit_context_cache:
            unit_context_cache[cache_key] = _prepare_unit_context(
                case_bundle=case_bundle,
                representative_node_id=event_unit_spec.representative_node_id,
                singleton_group=singleton_group,
            )
        event_units.append(
            _build_unit_result(
                case_bundle=case_bundle,
                unit_context=unit_context_cache[cache_key],
                event_unit_spec=event_unit_spec,
            )
        )
    guarded_units = _apply_evidence_ownership_guards(event_units)
    case_review_state = "STEP4_OK"
    if any(unit.review_state == "STEP4_FAIL" for unit in guarded_units):
        case_review_state = "STEP4_FAIL"
    elif any(unit.review_state == "STEP4_REVIEW" for unit in guarded_units):
        case_review_state = "STEP4_REVIEW"
    case_review_reasons = tuple(
        dict.fromkeys(
            reason
            for unit in guarded_units
            for reason in unit.all_review_reasons()
        )
    )
    return T04CaseResult(
        case_spec=case_bundle.case_spec,
        case_bundle=case_bundle,
        admission=admission,
        base_context=base_context,
        event_units=guarded_units,
        case_review_state=case_review_state,
        case_review_reasons=case_review_reasons,
    )
