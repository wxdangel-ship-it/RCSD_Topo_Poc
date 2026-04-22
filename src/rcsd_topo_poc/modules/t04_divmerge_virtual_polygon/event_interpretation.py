from __future__ import annotations

import inspect
from dataclasses import replace
from typing import Any, Iterable

from shapely.geometry import GeometryCollection
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

from rcsd_topo_poc.modules.t02_junction_anchor.shared import LoadedFeature, normalize_id
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_geometry_utils import (
    EVENT_REFERENCE_SCAN_MAX_M,
    _build_between_branches_segment,
    _build_event_crossline,
    _node_source_kind_2,
    _pick_cross_section_boundary_branches,
    _resolve_branch_centerline,
    _resolve_event_axis_branch,
    _resolve_event_axis_unit_vector,
    _resolve_event_cross_half_len,
    _resolve_scan_axis_unit_vector,
    _explode_component_geometries,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step4_event_interpretation import (
    _build_stage4_event_interpretation,
)
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    ParsedRoad,
    _resolve_group,
)

from .admission import build_step1_admission
from .case_models import (
    T04CaseBundle,
    T04CaseResult,
    T04EventUnitResult,
    T04UnitEnvelope,
    T04UnitContext,
)
from .event_units import build_event_unit_specs
from .event_interpretation_branch_variants import (
    _build_complex_executable_branch_variants,
    _build_direct_adjacency_branch_set,
)
from .event_interpretation_selection import (
    _apply_evidence_ownership_guards,
    _candidate_priority_score,
    _merge_candidate_evaluation,
    _rank_candidate_pool,
    _select_case_assignment,
)
from .event_interpretation_shared import (
    _CandidateEvaluation,
    _ExecutableBranchSet,
    _PreparedUnitInputs,
    _area_ratio,
    _clip_geometry_to_scope,
    _explode_polygon_geometries,
    _filter_divstrip_features_to_scope,
    _filter_nodes_to_scope,
    _filter_roads_to_scope,
    _geometry_present,
    _road_lookup,
    _safe_normalize_geometry,
    _stable_axis_position,
    _stable_axis_signature,
    _stable_boundary_pair_signature,
)
from .local_context import build_step2_local_context
from .topology import build_step3_topology
from .variant_ranking import (
    _pair_interval_variant_metrics_from_data,
    _prepared_variant_rank,
)


DIVSTRIP_EVIDENCE_TIP_RADIUS_M = 8.0
PAIR_LOCAL_SCAN_STEP_M = 4.0
PAIR_LOCAL_SCAN_STOP_MISS_COUNT = 4
PAIR_LOCAL_SLICE_BUFFER_M = 2.5
PAIR_LOCAL_REGION_PAD_M = 4.0
PAIR_LOCAL_SCOPE_PAD_M = 10.0
PAIR_LOCAL_RCSD_SCOPE_PAD_M = 18.0
PAIR_LOCAL_THROAT_RADIUS_M = 10.0
MAX_CANDIDATES_PER_UNIT = 6
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


def _unit_population_node_ids(*, unit_context: T04UnitContext, event_unit_spec):
    if event_unit_spec.split_mode == "complex_one_node_one_unit":
        return (unit_context.representative_node.node_id,)
    member_node_ids = tuple(str(node_id) for node_id in unit_context.topology_skeleton.branch_result.member_node_ids)
    if member_node_ids:
        return member_node_ids
    return tuple(node.node_id for node in unit_context.group_nodes)


def _context_augmented_node_ids(*, unit_context: T04UnitContext, unit_population_node_ids: tuple[str, ...]):
    unit_population_set = {str(node_id) for node_id in unit_population_node_ids}
    return tuple(
        str(node_id)
        for node_id in unit_context.topology_skeleton.branch_result.augmented_member_node_ids
        if str(node_id) not in unit_population_set
    )


def _boundary_branch_ids(
    *,
    event_unit_spec,
    scoped_branches,
    scoped_main_branch_ids: set[str],
):
    scoped_branch_ids = tuple(str(branch.branch_id) for branch in scoped_branches)
    scoped_branch_id_set = set(scoped_branch_ids)
    explicit_event_branch_ids = tuple(
        str(branch_id)
        for branch_id in event_unit_spec.selected_side_branch_ids
        if str(branch_id) in scoped_branch_id_set
    )
    if explicit_event_branch_ids:
        ordered_main_branch_ids = tuple(
            branch_id
            for branch_id in scoped_branch_ids
            if branch_id in scoped_main_branch_ids
        )
        return tuple(dict.fromkeys([*ordered_main_branch_ids, *explicit_event_branch_ids]))
    if len(scoped_branch_ids) <= 2:
        return scoped_branch_ids
    ordered_main_branch_ids = tuple(
        branch_id
        for branch_id in scoped_branch_ids
        if branch_id in scoped_main_branch_ids
    )
    if len(ordered_main_branch_ids) >= 2:
        return ordered_main_branch_ids[:2]
    return scoped_branch_ids[:2]


def _point_signature(
    *,
    point_geometry: BaseGeometry | None,
    event_axis_signature: str | None,
    axis_position_basis: str | None,
    axis_position_m: float | None,
    event_axis_branch_id: str | None,
    axis_origin_point: BaseGeometry | None,
    axis_unit_vector: tuple[float, float] | None,
) -> str:
    if point_geometry is None or point_geometry.is_empty:
        return ""
    point = point_geometry
    if getattr(point, "geom_type", None) != "Point":
        representative_point = point.representative_point()
        if representative_point is None or representative_point.is_empty:
            return ""
        point = representative_point
    if event_axis_signature is not None and axis_position_m is not None:
        if axis_position_basis and axis_position_basis != event_axis_signature:
            return f"{event_axis_signature}:{axis_position_basis}:{round(float(axis_position_m), 1)}"
        return f"{event_axis_signature}:{round(float(axis_position_m), 1)}"
    if (
        (event_axis_signature is not None or event_axis_branch_id is not None)
        and axis_origin_point is not None
        and not axis_origin_point.is_empty
        and axis_unit_vector is not None
    ):
        dx = float(point.x) - float(axis_origin_point.x)
        dy = float(point.y) - float(axis_origin_point.y)
        projection = dx * float(axis_unit_vector[0]) + dy * float(axis_unit_vector[1])
        axis_identity = event_axis_signature or event_axis_branch_id
        return f"{axis_identity}:{round(float(projection), 1)}"
    return f"{round(float(point.x), 1)}:{round(float(point.y), 1)}"


def _candidate_layer(
    *,
    region_geometry: BaseGeometry | None,
    reference_point: BaseGeometry | None,
    pair_middle_geometry: BaseGeometry | None,
    throat_core_geometry: BaseGeometry | None,
) -> tuple[int, float, float, str]:
    middle_ratio = _area_ratio(region_geometry, pair_middle_geometry)
    throat_ratio = _area_ratio(region_geometry, throat_core_geometry)
    point_in_middle = bool(
        _geometry_present(pair_middle_geometry)
        and reference_point is not None
        and not reference_point.is_empty
        and pair_middle_geometry.buffer(1e-6).covers(reference_point)
    )
    point_in_throat = bool(
        _geometry_present(throat_core_geometry)
        and reference_point is not None
        and not reference_point.is_empty
        and throat_core_geometry.buffer(1e-6).covers(reference_point)
    )
    if (point_in_throat or throat_ratio >= 0.35) and middle_ratio >= 0.6:
        return 1, middle_ratio, throat_ratio, "throat_core_plus_pair_middle"
    if point_in_middle or middle_ratio >= 0.45:
        return 2, middle_ratio, throat_ratio, "pair_middle_stable"
    return 3, middle_ratio, throat_ratio, "weak_edge_contact"


def _candidate_summary(
    *,
    candidate_id: str,
    source_mode: str,
    upper_evidence_kind: str,
    upper_evidence_object_id: str,
    local_region_id: str,
    region_geometry: BaseGeometry | None,
    reference_point: BaseGeometry | None,
    pair_middle_geometry: BaseGeometry | None,
    throat_core_geometry: BaseGeometry | None,
    event_axis_signature: str | None,
    axis_position_basis: str | None,
    axis_position_m: float | None,
    event_axis_branch_id: str | None,
    axis_origin_point: BaseGeometry | None,
    axis_unit_vector: tuple[float, float] | None,
) -> dict[str, Any]:
    layer, middle_ratio, throat_ratio, layer_reason = _candidate_layer(
        region_geometry=region_geometry,
        reference_point=reference_point,
        pair_middle_geometry=pair_middle_geometry,
        throat_core_geometry=throat_core_geometry,
    )
    point_signature = _point_signature(
        point_geometry=reference_point,
        event_axis_signature=event_axis_signature,
        axis_position_basis=axis_position_basis,
        axis_position_m=axis_position_m,
        event_axis_branch_id=event_axis_branch_id,
        axis_origin_point=axis_origin_point,
        axis_unit_vector=axis_unit_vector,
    )
    ownership_signature = f"{upper_evidence_kind}:{upper_evidence_object_id}:{local_region_id}"
    return {
        "candidate_id": candidate_id,
        "source_mode": source_mode,
        "upper_evidence_kind": upper_evidence_kind,
        "upper_evidence_object_id": upper_evidence_object_id,
        "local_region_id": local_region_id,
        "ownership_signature": ownership_signature,
        "point_signature": point_signature,
        "axis_signature": event_axis_signature or event_axis_branch_id or "",
        "axis_position_basis": axis_position_basis or "",
        "axis_position_m": axis_position_m,
        "layer": int(layer),
        "layer_label": f"Layer {int(layer)}",
        "layer_reason": layer_reason,
        "pair_middle_overlap_ratio": round(float(middle_ratio), 4),
        "throat_overlap_ratio": round(float(throat_ratio), 4),
        "primary_eligible": bool(layer in {1, 2}),
        "selected_after_reselection": False,
        "selection_rank": None,
    }


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
    branch_road_memberships: dict[str, tuple[str, ...]] | None = None,
    scope_branch_ids: tuple[str, ...] = (),
):
    local_context = unit_context.local_context
    if event_unit_spec.split_mode != "complex_one_node_one_unit":
        return (
            filtered_branches,
            filtered_roads,
            list(local_context.local_rcsd_roads),
            list(local_context.local_rcsd_nodes),
            list(local_context.patch_divstrip_features),
            None,
        )

    normalized_scope_branch_ids = tuple(str(branch_id) for branch_id in scope_branch_ids if str(branch_id))
    allowed_scope_road_ids = {
        str(road_id)
        for branch_id in normalized_scope_branch_ids
        for road_id in (branch_road_memberships or {}).get(str(branch_id), ())
        if str(road_id)
    }

    scope_seeds: list[BaseGeometry] = [
        unit_context.representative_node.geometry.buffer(
            COMPLEX_SUBUNIT_SCOPE_RADIUS_M,
            join_style=2,
        )
    ]
    road_seed_source = [
        road
        for road in filtered_roads
        if not allowed_scope_road_ids or str(road.road_id) in allowed_scope_road_ids
    ]
    road_lookup = _road_lookup(road_seed_source if road_seed_source else filtered_roads)
    for branch_id in normalized_scope_branch_ids:
        for road_id in (branch_road_memberships or {}).get(str(branch_id), ()):
            road = road_lookup.get(str(road_id))
            if road is None or road.geometry is None or road.geometry.is_empty:
                continue
            scope_seeds.append(
                road.geometry.buffer(COMPLEX_SUBUNIT_ROAD_PAD_M, cap_style=2, join_style=2)
            )
    scope_geometry = _safe_normalize_geometry(unary_union(scope_seeds))
    if scope_geometry is None:
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

    road_scope_source = (
        road_seed_source
        if road_seed_source
        else list(filtered_roads)
    )
    scoped_roads = [
        road
        for road in road_scope_source
        if road.geometry is not None and not road.geometry.is_empty and road.geometry.intersects(road_scope)
    ]
    degraded_scope_reasons: list[str] = []
    if len(scoped_roads) < 2 and len(road_scope_source) >= 2:
        degraded_scope_reasons.append("insufficient_local_scoped_roads")
        scoped_roads = list(road_scope_source)

    if normalized_scope_branch_ids:
        scoped_branches = list(filtered_branches)
    else:
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
            degraded_scope_reasons.append("insufficient_local_scoped_branches")
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
    if not [
        feature
        for feature in local_context.patch_divstrip_features
        if feature.geometry is not None and not feature.geometry.is_empty and feature.geometry.intersects(divstrip_scope)
    ]:
        degraded_scope_reasons.append("insufficient_local_scoped_divstrip")

    return (
        scoped_branches,
        scoped_roads,
        scoped_rcsd_roads,
        scoped_rcsd_nodes,
        scoped_divstrip_features,
        "|".join(degraded_scope_reasons) if degraded_scope_reasons else None,
    )


def _materialize_prepared_unit_inputs(
    *,
    case_bundle: T04CaseBundle,
    unit_context: T04UnitContext,
    event_unit_spec,
    effective_representative_node,
    effective_source_kind_2,
    filtered_branches,
    filtered_roads,
    main_branch_ids,
    executable_branch_set: _ExecutableBranchSet | None,
) -> _PreparedUnitInputs:
    if executable_branch_set is not None:
        filtered_branches = list(executable_branch_set.road_branches)
        main_branch_ids = set(executable_branch_set.main_branch_ids)
    local_context = unit_context.local_context
    geometry_road_lookup = _road_lookup(filtered_roads)
    (
        scoped_branches,
        scoped_roads,
        scoped_rcsd_roads,
        scoped_rcsd_nodes,
        scoped_divstrip_features,
        degraded_scope_reason,
    ) = _scope_complex_step4_inputs(
        event_unit_spec=event_unit_spec,
        unit_context=unit_context,
        filtered_branches=filtered_branches,
        filtered_roads=filtered_roads,
        branch_road_memberships=(
            None if executable_branch_set is None else executable_branch_set.branch_road_memberships
        ),
        scope_branch_ids=(
            ()
            if executable_branch_set is None
            else tuple(
                executable_branch_set.boundary_branch_ids
                or executable_branch_set.event_branch_ids
                or executable_branch_set.branch_ids
            )
        ),
    )
    scoped_branch_id_set = {str(branch.branch_id) for branch in scoped_branches}
    scoped_main_branch_ids = frozenset(
        str(branch_id)
        for branch_id in main_branch_ids
        if str(branch_id) in scoped_branch_id_set
    )
    unit_population_node_ids = _unit_population_node_ids(
        unit_context=unit_context,
        event_unit_spec=event_unit_spec,
    )
    context_augmented_node_ids = _context_augmented_node_ids(
        unit_context=unit_context,
        unit_population_node_ids=unit_population_node_ids,
    )
    if executable_branch_set is not None:
        explicit_event_branch_ids = tuple(
            branch_id
            for branch_id in executable_branch_set.event_branch_ids
            if branch_id in scoped_branch_id_set
        )
        boundary_branch_ids = tuple(
            branch_id
            for branch_id in executable_branch_set.boundary_branch_ids
            if branch_id in scoped_branch_id_set
        )
        scoped_input_branch_ids = tuple(
            branch_id
            for branch_id in executable_branch_set.input_branch_ids
            if branch_id in scoped_branch_id_set
        )
        scoped_output_branch_ids = tuple(
            branch_id
            for branch_id in executable_branch_set.output_branch_ids
            if branch_id in scoped_branch_id_set
        )
        branch_road_memberships = {
            branch_id: road_ids
            for branch_id, road_ids in executable_branch_set.branch_road_memberships.items()
            if branch_id in scoped_branch_id_set
        }
        branch_bridge_node_ids = {
            branch_id: node_ids
            for branch_id, node_ids in executable_branch_set.branch_bridge_node_ids.items()
            if branch_id in scoped_branch_id_set
        }
    else:
        explicit_event_branch_ids = tuple(str(branch_id) for branch_id in event_unit_spec.selected_side_branch_ids)
        boundary_branch_ids = _boundary_branch_ids(
            event_unit_spec=event_unit_spec,
            scoped_branches=scoped_branches,
            scoped_main_branch_ids=set(scoped_main_branch_ids),
        )
        scoped_input_branch_ids = tuple(
            str(branch.branch_id)
            for branch in scoped_branches
            if getattr(branch, "has_incoming_support", False)
        )
        scoped_output_branch_ids = tuple(
            str(branch.branch_id)
            for branch in scoped_branches
            if getattr(branch, "has_outgoing_support", False)
        )
        branch_road_memberships = {
            str(branch.branch_id): tuple(str(road_id) for road_id in branch.road_ids)
            for branch in scoped_branches
        }
        branch_bridge_node_ids = {}
    kind_hint = (
        executable_branch_set.operational_kind_hint
        if executable_branch_set is not None and executable_branch_set.operational_kind_hint in {8, 16}
        else (
            int(effective_source_kind_2)
            if effective_source_kind_2 in {8, 16}
            else (
                int(unit_context.admission.source_kind_2)
                if unit_context.admission.source_kind_2 in {8, 16}
                else 16
                )
        )
    )
    if (
        not explicit_event_branch_ids
        and event_unit_spec.split_mode == "one_case_one_unit"
        and len(scoped_branches) == 2
        and len(boundary_branch_ids) == 2
        and kind_hint in {8, 16}
    ):
        explicit_event_branch_ids = tuple(str(branch_id) for branch_id in boundary_branch_ids)
    pair_region_signature = _stable_boundary_pair_signature(
        boundary_branch_ids=tuple(boundary_branch_ids),
        branch_road_memberships=branch_road_memberships,
    )
    pair_interval_inside_count, _pair_interval_gap_x10 = _pair_interval_variant_metrics_from_data(
        boundary_branch_ids=tuple(boundary_branch_ids),
        scoped_branches=tuple(scoped_branches),
        branch_road_memberships=dict(branch_road_memberships),
        scoped_roads=tuple(filtered_roads),
        case_bundle=case_bundle,
        representative_node=effective_representative_node,
        mainnodeid=str(unit_context.admission.mainnodeid),
    )
    event_axis_branch = _resolve_event_axis_branch(
        road_branches=list(scoped_branches),
        main_branch_ids=set(scoped_main_branch_ids),
        kind_2=kind_hint,
    )
    preferred_axis_branch_id = None if event_axis_branch is None else str(event_axis_branch.branch_id)
    axis_origin_point = effective_representative_node.geometry
    axis_centerline = (
        None
        if event_axis_branch is None
        else _resolve_branch_centerline(
            branch=event_axis_branch,
            road_lookup=geometry_road_lookup,
            reference_point=effective_representative_node.geometry,
        )
    )
    if axis_centerline is not None and not axis_centerline.is_empty:
        axis_origin_point = nearest_points(axis_centerline, effective_representative_node.geometry)[0]
    axis_unit_vector = _resolve_event_axis_unit_vector(
        axis_centerline=axis_centerline,
        origin_point=axis_origin_point,
    )
    scan_axis_unit_vector = _resolve_scan_axis_unit_vector(
        axis_unit_vector=axis_unit_vector,
        kind_2=kind_hint,
    )
    boundary_branch_a, boundary_branch_b = _pick_cross_section_boundary_branches(
        road_branches=list(scoped_branches),
        selected_branch_ids=set(boundary_branch_ids),
        kind_2=kind_hint,
    )
    pair_scan_truncated_to_local = pair_interval_inside_count < len(boundary_branch_ids)
    branch_a_centerline = (
        None
        if boundary_branch_a is None
        else _resolve_branch_centerline(
            branch=boundary_branch_a,
            road_lookup=geometry_road_lookup,
            reference_point=axis_origin_point,
        )
    )
    branch_b_centerline = (
        None
        if boundary_branch_b is None
        else _resolve_branch_centerline(
            branch=boundary_branch_b,
            road_lookup=geometry_road_lookup,
            reference_point=axis_origin_point,
        )
    )
    event_cross_half_len_m = _resolve_event_cross_half_len(
        origin_point=axis_origin_point,
        axis_centerline=axis_centerline,
        axis_unit_vector=axis_unit_vector,
        event_anchor_geometry=effective_representative_node.geometry.buffer(2.0, join_style=2),
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
        selected_roads=list(scoped_roads),
        selected_rcsd_roads=list(scoped_rcsd_roads),
        patch_size_m=float(local_context.patch_size_m),
    )
    pair_local_degraded_reasons: list[str] = []
    if degraded_scope_reason:
        pair_local_degraded_reasons.extend(
            [item for item in str(degraded_scope_reason).split("|") if str(item).strip()]
        )
    collected_slices: list[BaseGeometry] = []
    valid_offsets: list[float] = []

    def _collect_pair_slice(scan_s: float) -> BaseGeometry | None:
        if (
            scan_axis_unit_vector is None
            or branch_a_centerline is None
            or branch_a_centerline.is_empty
            or branch_b_centerline is None
            or branch_b_centerline.is_empty
        ):
            return None
        crossline = _build_event_crossline(
            origin_point=axis_origin_point,
            axis_unit_vector=scan_axis_unit_vector,
            scan_dist_m=float(scan_s),
            cross_half_len_m=float(event_cross_half_len_m),
        )
        center_point = crossline.interpolate(0.5, normalized=True)
        segment, segment_diag = _build_between_branches_segment(
            crossline=crossline,
            center_point=center_point,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
        )
        if segment is None or not segment_diag["ok"]:
            return None
        if pair_scan_truncated_to_local and (
            not bool(segment_diag.get("branch_a_crossline_hit"))
            or not bool(segment_diag.get("branch_b_crossline_hit"))
        ):
            return None
        segment_length = float(segment_diag.get("seg_len_m", 0.0) or 0.0)
        if segment_length <= 1e-3:
            slice_geometry = center_point.buffer(PAIR_LOCAL_SLICE_BUFFER_M, join_style=2)
        else:
            slice_geometry = segment.buffer(PAIR_LOCAL_SLICE_BUFFER_M, cap_style=2, join_style=2)
        if local_context.patch_drivezone_union is not None and not local_context.patch_drivezone_union.is_empty:
            slice_geometry = slice_geometry.intersection(local_context.patch_drivezone_union)
        return _safe_normalize_geometry(slice_geometry)

    hard_limit_m = min(
        float(EVENT_REFERENCE_SCAN_MAX_M),
        max(float(PAIR_LOCAL_THROAT_RADIUS_M) * 2.0, float(local_context.patch_size_m) * 0.45),
    )
    initial_slice = _collect_pair_slice(0.0)
    if initial_slice is not None:
        collected_slices.append(initial_slice)
        valid_offsets.append(0.0)
    directional_collections: list[tuple[float, list[BaseGeometry], list[float]]] = []
    for direction in (1.0, -1.0):
        miss_count = 0
        direction_slices: list[BaseGeometry] = []
        direction_offsets: list[float] = []
        for step_index in range(1, int(hard_limit_m // PAIR_LOCAL_SCAN_STEP_M) + 1):
            scan_s = float(direction * step_index * PAIR_LOCAL_SCAN_STEP_M)
            slice_geometry = _collect_pair_slice(scan_s)
            if slice_geometry is None:
                miss_count += 1
                if (collected_slices or direction_slices) and miss_count >= PAIR_LOCAL_SCAN_STOP_MISS_COUNT:
                    break
                continue
            direction_slices.append(slice_geometry)
            direction_offsets.append(scan_s)
            miss_count = 0
        directional_collections.append((direction, direction_slices, direction_offsets))

    best_direction_slices: list[BaseGeometry] = []
    best_direction_offsets: list[float] = []
    best_direction_key: tuple[int, float, float] | None = None
    for _direction, direction_slices, direction_offsets in directional_collections:
        if not direction_slices:
            continue
        try:
            direction_area = float(
                getattr(
                    _safe_normalize_geometry(unary_union(direction_slices)),
                    "area",
                    0.0,
                )
                or 0.0
            )
        except Exception:
            direction_area = 0.0
        direction_key = (
            len(direction_offsets),
            direction_area,
            float(max(abs(offset) for offset in direction_offsets)),
        )
        if best_direction_key is None or direction_key > best_direction_key:
            best_direction_key = direction_key
            best_direction_slices = direction_slices
            best_direction_offsets = direction_offsets
    collected_slices.extend(best_direction_slices)
    valid_offsets.extend(best_direction_offsets)

    pair_local_middle_geometry = _safe_normalize_geometry(
        unary_union(collected_slices) if collected_slices else GeometryCollection()
    )
    pair_local_structure_face_geometry = (
        None
        if pair_local_middle_geometry is None
        else _safe_normalize_geometry(
            pair_local_middle_geometry.buffer(PAIR_LOCAL_SLICE_BUFFER_M, join_style=2)
        )
    )
    if (
        pair_local_structure_face_geometry is not None
        and local_context.patch_drivezone_union is not None
        and not local_context.patch_drivezone_union.is_empty
    ):
        pair_local_structure_face_geometry = _safe_normalize_geometry(
            pair_local_structure_face_geometry.intersection(local_context.patch_drivezone_union)
        )
    if pair_local_structure_face_geometry is None:
        pair_local_degraded_reasons.append("pair_local_middle_missing")
        fallback_parts: list[BaseGeometry] = []
        for geometry in (
            local_context.patch_drivezone_union,
            None if axis_centerline is None else axis_centerline.buffer(PAIR_LOCAL_SCOPE_PAD_M, cap_style=2, join_style=2),
            effective_representative_node.geometry.buffer(PAIR_LOCAL_SCOPE_PAD_M, join_style=2),
        ):
            if geometry is None or geometry.is_empty:
                continue
            fallback_parts.append(geometry)
        pair_local_structure_face_geometry = _safe_normalize_geometry(
            unary_union(fallback_parts) if fallback_parts else GeometryCollection()
        )
        pair_local_middle_geometry = (
            None
            if pair_local_structure_face_geometry is None
            else _safe_normalize_geometry(
                pair_local_structure_face_geometry.intersection(
                    axis_origin_point.buffer(PAIR_LOCAL_THROAT_RADIUS_M, join_style=2)
                )
            )
        )
        if pair_local_middle_geometry is None:
            pair_local_middle_geometry = pair_local_structure_face_geometry
    pair_local_region_geometry = (
        None
        if pair_local_structure_face_geometry is None
        else _safe_normalize_geometry(
            pair_local_structure_face_geometry.buffer(PAIR_LOCAL_REGION_PAD_M, join_style=2)
        )
    )
    if (
        pair_local_region_geometry is not None
        and local_context.patch_drivezone_union is not None
        and not local_context.patch_drivezone_union.is_empty
    ):
        pair_local_region_geometry = _safe_normalize_geometry(
            pair_local_region_geometry.intersection(local_context.patch_drivezone_union)
        )
    pair_local_throat_core_geometry = None
    if pair_local_structure_face_geometry is not None:
        pair_local_throat_core_geometry = _safe_normalize_geometry(
            pair_local_structure_face_geometry.intersection(
                axis_origin_point.buffer(PAIR_LOCAL_THROAT_RADIUS_M, join_style=2)
            )
        )
    if pair_local_throat_core_geometry is None and pair_local_region_geometry is not None:
        pair_local_throat_core_geometry = _safe_normalize_geometry(
            pair_local_region_geometry.intersection(
                axis_origin_point.buffer(PAIR_LOCAL_THROAT_RADIUS_M, join_style=2)
            )
        )
    scope_geometry = pair_local_region_geometry or pair_local_structure_face_geometry
    pair_local_drivezone_union = None
    if scope_geometry is not None:
        pair_local_drivezone_union = _clip_geometry_to_scope(
            local_context.patch_drivezone_union,
            scope_geometry=scope_geometry,
            pad_m=max(PAIR_LOCAL_SCOPE_PAD_M, PAIR_LOCAL_RCSD_SCOPE_PAD_M),
        )
    if pair_local_drivezone_union is None:
        pair_local_drivezone_union = local_context.patch_drivezone_union
    pair_local_scope_roads = _filter_roads_to_scope(
        scoped_roads,
        scope_geometry=scope_geometry,
        pad_m=PAIR_LOCAL_SCOPE_PAD_M,
    )
    if not pair_local_scope_roads:
        pair_local_scope_roads = tuple(scoped_roads)
        pair_local_degraded_reasons.append("pair_local_scope_roads_empty")
    pair_local_scope_rcsd_roads = _filter_roads_to_scope(
        scoped_rcsd_roads,
        scope_geometry=scope_geometry,
        pad_m=PAIR_LOCAL_RCSD_SCOPE_PAD_M,
    ) or tuple(scoped_rcsd_roads)
    pair_local_scope_rcsd_nodes = _filter_nodes_to_scope(
        scoped_rcsd_nodes,
        scope_geometry=scope_geometry,
        pad_m=PAIR_LOCAL_RCSD_SCOPE_PAD_M,
    ) or tuple(scoped_rcsd_nodes)
    if pair_local_drivezone_union is not None and not pair_local_drivezone_union.is_empty:
        contained_rcsd_roads = tuple(
            road
            for road in pair_local_scope_rcsd_roads
            if road.geometry is not None
            and not road.geometry.is_empty
            and pair_local_drivezone_union.buffer(0).covers(road.geometry)
        )
        if len(contained_rcsd_roads) < len(pair_local_scope_rcsd_roads):
            pair_local_degraded_reasons.append("pair_local_scope_rcsd_outside_drivezone_filtered")
        pair_local_scope_rcsd_roads = contained_rcsd_roads
    pair_local_scope_divstrip_features = _filter_divstrip_features_to_scope(
        scoped_divstrip_features,
        scope_geometry=scope_geometry,
        pad_m=PAIR_LOCAL_REGION_PAD_M,
    )
    pair_local_patch_size_m = float(local_context.patch_size_m)
    if pair_local_region_geometry is not None:
        minx, miny, maxx, maxy = pair_local_region_geometry.bounds
        pair_local_patch_size_m = max(float(maxx - minx), float(maxy - miny), float(PAIR_LOCAL_THROAT_RADIUS_M) * 2.0)
    pair_local_summary = {
        "region_id": (
            f"{event_unit_spec.event_unit_id}:{pair_region_signature}"
            if pair_region_signature
            else f"{event_unit_spec.event_unit_id}:{preferred_axis_branch_id or 'no_axis'}"
        ),
        "search_unit": "unit_local_branch_pair_region",
        "structure_space": "unit_local_structure_face",
        "branch_ids": [str(branch.branch_id) for branch in scoped_branches],
        "main_branch_ids": sorted(str(branch_id) for branch_id in scoped_main_branch_ids),
        "input_branch_ids": list(scoped_input_branch_ids),
        "output_branch_ids": list(scoped_output_branch_ids),
        "event_branch_ids": list(explicit_event_branch_ids),
        "boundary_branch_ids": list(boundary_branch_ids),
        "boundary_pair_signature": pair_region_signature,
        "event_axis_branch_id": preferred_axis_branch_id,
        "branch_road_memberships": {
            str(branch_id): list(road_ids)
            for branch_id, road_ids in branch_road_memberships.items()
        },
        "branch_bridge_node_ids": {
            str(branch_id): list(node_ids)
            for branch_id, node_ids in branch_bridge_node_ids.items()
        },
        "operational_kind_hint": kind_hint,
        "pair_scan_truncated_to_local": bool(pair_scan_truncated_to_local),
        "degraded_reasons": list(dict.fromkeys(pair_local_degraded_reasons)),
        "valid_scan_offsets_m": [round(float(offset), 3) for offset in sorted(valid_offsets)],
        "pair_local_region_area_m2": 0.0 if pair_local_region_geometry is None else round(float(pair_local_region_geometry.area), 3),
        "structure_face_area_m2": 0.0 if pair_local_structure_face_geometry is None else round(float(pair_local_structure_face_geometry.area), 3),
        "pair_local_middle_area_m2": 0.0 if pair_local_middle_geometry is None else round(float(pair_local_middle_geometry.area), 3),
        "throat_core_area_m2": 0.0 if pair_local_throat_core_geometry is None else round(float(pair_local_throat_core_geometry.area), 3),
    }
    return _PreparedUnitInputs(
        case_bundle=case_bundle,
        unit_context=unit_context,
        event_unit_spec=event_unit_spec,
        effective_representative_node=effective_representative_node,
        effective_source_kind_2=effective_source_kind_2,
        scoped_branches=tuple(scoped_branches),
        scoped_roads=tuple(scoped_roads),
        scoped_rcsd_roads=tuple(scoped_rcsd_roads),
        scoped_rcsd_nodes=tuple(scoped_rcsd_nodes),
        scoped_divstrip_features=tuple(scoped_divstrip_features),
        scoped_main_branch_ids=scoped_main_branch_ids,
        scoped_input_branch_ids=tuple(scoped_input_branch_ids),
        scoped_output_branch_ids=tuple(scoped_output_branch_ids),
        unit_population_node_ids=tuple(unit_population_node_ids),
        context_augmented_node_ids=tuple(context_augmented_node_ids),
        explicit_event_branch_ids=tuple(explicit_event_branch_ids),
        boundary_branch_ids=tuple(boundary_branch_ids),
        boundary_pair_signature=pair_region_signature,
        branch_road_memberships=dict(branch_road_memberships),
        branch_bridge_node_ids=dict(branch_bridge_node_ids),
        degraded_scope_reason=(
            "|".join(dict.fromkeys(pair_local_degraded_reasons))
            if pair_local_degraded_reasons
            else None
        ),
        pair_local_summary=pair_local_summary,
        pair_local_region_geometry=pair_local_region_geometry,
        pair_local_structure_face_geometry=pair_local_structure_face_geometry,
        pair_local_middle_geometry=pair_local_middle_geometry,
        pair_local_throat_core_geometry=pair_local_throat_core_geometry,
        pair_local_drivezone_union=pair_local_drivezone_union,
        pair_local_scope_roads=pair_local_scope_roads,
        pair_local_scope_rcsd_roads=pair_local_scope_rcsd_roads,
        pair_local_scope_rcsd_nodes=pair_local_scope_rcsd_nodes,
        pair_local_scope_divstrip_features=pair_local_scope_divstrip_features,
        pair_local_patch_size_m=pair_local_patch_size_m,
        preferred_axis_branch_id=preferred_axis_branch_id,
        pair_local_axis_origin_point=axis_origin_point,
        pair_local_axis_unit_vector=scan_axis_unit_vector,
        operational_kind_hint=kind_hint,
    )
def _prepare_unit_inputs(
    *,
    case_bundle: T04CaseBundle,
    unit_context: T04UnitContext,
    event_unit_spec,
) -> _PreparedUnitInputs:
    effective_representative_node, effective_source_kind_2 = _effective_complex_kind_hint(
        case_bundle=case_bundle,
        unit_context=unit_context,
        event_unit_spec=event_unit_spec,
    )
    filtered_branches, filtered_roads, main_branch_ids = _filter_branch_scope(
        unit_context,
        event_unit_spec.selected_side_branch_ids,
    )
    if event_unit_spec.split_mode == "one_case_one_unit" and len(filtered_branches) == 2:
        direct_adjacency_branch_set = _build_direct_adjacency_branch_set(
            unit_context=unit_context,
            filtered_roads=list(filtered_roads),
        )
        if direct_adjacency_branch_set is not None:
            return _materialize_prepared_unit_inputs(
                case_bundle=case_bundle,
                unit_context=unit_context,
                event_unit_spec=event_unit_spec,
                effective_representative_node=effective_representative_node,
                effective_source_kind_2=effective_source_kind_2,
                filtered_branches=list(filtered_branches),
                filtered_roads=list(filtered_roads),
                main_branch_ids=set(main_branch_ids),
                executable_branch_set=direct_adjacency_branch_set,
            )
    if event_unit_spec.split_mode == "complex_one_node_one_unit":
        executable_branch_variants = _build_complex_executable_branch_variants(
            unit_context=unit_context,
            filtered_roads=list(filtered_roads),
        )
        best_prepared: _PreparedUnitInputs | None = None
        best_rank: tuple[int, ...] | None = None
        for executable_branch_set in executable_branch_variants:
            prepared = _materialize_prepared_unit_inputs(
                case_bundle=case_bundle,
                unit_context=unit_context,
                event_unit_spec=event_unit_spec,
                effective_representative_node=effective_representative_node,
                effective_source_kind_2=effective_source_kind_2,
                filtered_branches=list(filtered_branches),
                filtered_roads=list(filtered_roads),
                main_branch_ids=set(main_branch_ids),
                executable_branch_set=executable_branch_set,
            )
            raw_candidates = _build_candidate_pool(prepared)
            evaluations = _rank_candidate_pool(
                [_evaluate_unit_candidate(prepared, candidate) for candidate in raw_candidates]
            )
            rank = _prepared_variant_rank(prepared, evaluations)
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_prepared = prepared
        if best_prepared is not None:
            return best_prepared
    return _materialize_prepared_unit_inputs(
        case_bundle=case_bundle,
        unit_context=unit_context,
        event_unit_spec=event_unit_spec,
        effective_representative_node=effective_representative_node,
        effective_source_kind_2=effective_source_kind_2,
        filtered_branches=list(filtered_branches),
        filtered_roads=list(filtered_roads),
        main_branch_ids=set(main_branch_ids),
        executable_branch_set=None,
    )


def _build_candidate_pool(prepared: _PreparedUnitInputs) -> list[dict[str, Any]]:
    pair_region = prepared.pair_local_region_geometry or prepared.pair_local_structure_face_geometry
    structure_face = prepared.pair_local_structure_face_geometry or pair_region
    throat_core = prepared.pair_local_throat_core_geometry
    pair_middle = prepared.pair_local_middle_geometry or structure_face
    axis_origin = prepared.pair_local_axis_origin_point or prepared.unit_context.representative_node.geometry
    axis_unit_vector = prepared.pair_local_axis_unit_vector
    axis_signature = _stable_axis_signature(
        prepared.preferred_axis_branch_id,
        prepared.branch_road_memberships,
    )
    case_road_lookup = _road_lookup(prepared.case_bundle.roads)
    candidates: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    def _append_candidate(
        *,
        candidate_id: str,
        source_mode: str,
        upper_evidence_kind: str,
        upper_evidence_object_id: str,
        region_geometry: BaseGeometry | None,
        feature_index: int,
        properties: dict[str, Any] | None,
        force_empty_divstrip: bool = False,
    ) -> None:
        normalized_region = _safe_normalize_geometry(region_geometry)
        if normalized_region is None:
            return
        try:
            reference_point = nearest_points(axis_origin, normalized_region)[1]
        except Exception:
            reference_point = normalized_region.representative_point()
        axis_position_basis, axis_position_m = _stable_axis_position(
            point_geometry=reference_point,
            branch_id=prepared.preferred_axis_branch_id,
            branch_road_memberships=prepared.branch_road_memberships,
            road_lookup=case_road_lookup,
        )
        local_region_id = f"{prepared.event_unit_spec.event_unit_id}:{upper_evidence_kind}:{upper_evidence_object_id}:{len(candidates) + 1:02d}"
        summary = _candidate_summary(
            candidate_id=candidate_id,
            source_mode=source_mode,
            upper_evidence_kind=upper_evidence_kind,
            upper_evidence_object_id=upper_evidence_object_id,
            local_region_id=local_region_id,
            region_geometry=normalized_region,
            reference_point=reference_point,
            pair_middle_geometry=pair_middle,
            throat_core_geometry=throat_core,
            event_axis_signature=axis_signature,
            axis_position_basis=axis_position_basis,
            axis_position_m=axis_position_m,
            event_axis_branch_id=prepared.preferred_axis_branch_id,
            axis_origin_point=axis_origin,
            axis_unit_vector=axis_unit_vector,
        )
        dedupe_key = (
            str(summary["upper_evidence_object_id"]),
            str(summary["point_signature"]),
            str(summary["layer"]),
        )
        if dedupe_key in seen_keys:
            return
        seen_keys.add(dedupe_key)
        synthetic_features: tuple[LoadedFeature, ...]
        if force_empty_divstrip:
            synthetic_features = ()
        else:
            synthetic_features = (
                LoadedFeature(
                    feature_index=int(feature_index),
                    properties={} if properties is None else dict(properties),
                    geometry=normalized_region,
                ),
            )
        candidates.append(
            {
                "summary": summary,
                "region_geometry": normalized_region,
                "divstrip_features": synthetic_features,
            }
        )

    for feature in prepared.pair_local_scope_divstrip_features:
        upper_id = str(feature.properties.get("id") or feature.feature_index)
        clipped_geometry = _clip_geometry_to_scope(
            feature.geometry,
            scope_geometry=pair_region,
            pad_m=0.0,
        )
        for index, component in enumerate(_explode_polygon_geometries(clipped_geometry), start=1):
            _append_candidate(
                candidate_id=f"{prepared.event_unit_spec.event_unit_id}:divstrip:{upper_id}:{index:02d}",
                source_mode="pair_local_divstrip",
                upper_evidence_kind="divstrip",
                upper_evidence_object_id=upper_id,
                region_geometry=component,
                feature_index=feature.feature_index,
                properties={
                    **dict(feature.properties),
                    "candidate_id": f"{prepared.event_unit_spec.event_unit_id}:divstrip:{upper_id}:{index:02d}",
                    "upper_evidence_object_id": upper_id,
                },
            )

    if throat_core is not None and not throat_core.is_empty:
        for index, component in enumerate(_explode_polygon_geometries(throat_core), start=1):
            _append_candidate(
                candidate_id=f"{prepared.event_unit_spec.event_unit_id}:structure:throat:{index:02d}",
                source_mode="pair_local_structure_mode",
                upper_evidence_kind="structure_face",
                upper_evidence_object_id=prepared.pair_local_summary["region_id"],
                region_geometry=component,
                feature_index=-1,
                properties={"candidate_scope": "throat_core"},
                force_empty_divstrip=True,
            )
    if structure_face is not None and not structure_face.is_empty:
        middle_region = pair_middle
        if throat_core is not None and not throat_core.is_empty:
            if middle_region is None or middle_region.is_empty:
                middle_region = throat_core
            elif not middle_region.buffer(1e-6).covers(prepared.unit_context.representative_node.geometry):
                middle_region = _safe_normalize_geometry(unary_union([middle_region, throat_core]))
        if middle_region is None or middle_region.is_empty:
            middle_region = structure_face
        _append_candidate(
            candidate_id=f"{prepared.event_unit_spec.event_unit_id}:structure:middle:01",
            source_mode="pair_local_structure_mode",
            upper_evidence_kind="structure_face",
            upper_evidence_object_id=prepared.pair_local_summary["region_id"],
            region_geometry=middle_region,
            feature_index=-2,
            properties={"candidate_scope": "pair_middle_structure_unit"},
            force_empty_divstrip=True,
        )
        if throat_core is not None and not throat_core.is_empty:
            edge_geometry = _safe_normalize_geometry(
                structure_face.difference(
                    throat_core.buffer(max(PAIR_LOCAL_REGION_PAD_M * 0.5, 1.0), join_style=2)
                )
            )
            if edge_geometry is not None:
                for index, component in enumerate(_explode_polygon_geometries(edge_geometry), start=1):
                    _append_candidate(
                        candidate_id=f"{prepared.event_unit_spec.event_unit_id}:structure:edge:{index:02d}",
                        source_mode="pair_local_structure_mode",
                        upper_evidence_kind="structure_face",
                        upper_evidence_object_id=prepared.pair_local_summary["region_id"],
                        region_geometry=component,
                        feature_index=-3,
                        properties={"candidate_scope": "edge_band"},
                        force_empty_divstrip=True,
                    )

    if not candidates:
        fallback_geometry = pair_region or prepared.unit_context.representative_node.geometry.buffer(
            PAIR_LOCAL_SCOPE_PAD_M,
            join_style=2,
        )
        _append_candidate(
            candidate_id=f"{prepared.event_unit_spec.event_unit_id}:structure:fallback:01",
            source_mode="pair_local_structure_mode",
            upper_evidence_kind="structure_face",
            upper_evidence_object_id=prepared.pair_local_summary["region_id"],
            region_geometry=fallback_geometry,
            feature_index=-9,
            properties={"candidate_scope": "fallback"},
            force_empty_divstrip=True,
        )

    ranked_candidates = sorted(
        candidates,
        key=lambda item: (
            int(item["summary"]["layer"]),
            -float(item["summary"]["pair_middle_overlap_ratio"]),
            -float(item["summary"]["throat_overlap_ratio"]),
            -float(getattr(item["region_geometry"], "area", 0.0) or 0.0),
            str(item["summary"]["candidate_id"]),
        ),
    )
    return ranked_candidates[:MAX_CANDIDATES_PER_UNIT]


def _build_unit_envelope(prepared: _PreparedUnitInputs) -> T04UnitEnvelope:
    return T04UnitEnvelope(
        topology_scope=(
            "single_node_event_input"
            if prepared.event_unit_spec.split_mode == "complex_one_node_one_unit"
            else (
                "multi_divmerge_case_input"
                if prepared.event_unit_spec.split_mode == "multi_divmerge_adjacent_pair"
                else "case_coordination"
            )
        ),
        unit_population_node_ids=tuple(prepared.unit_population_node_ids),
        context_augmented_node_ids=tuple(prepared.context_augmented_node_ids),
        branch_ids=tuple(str(branch.branch_id) for branch in prepared.scoped_branches),
        main_branch_ids=tuple(sorted(str(branch_id) for branch_id in prepared.scoped_main_branch_ids)),
        input_branch_ids=tuple(prepared.scoped_input_branch_ids),
        output_branch_ids=tuple(prepared.scoped_output_branch_ids),
        event_branch_ids=tuple(prepared.explicit_event_branch_ids),
        boundary_branch_ids=tuple(prepared.boundary_branch_ids),
        preferred_axis_branch_id=prepared.preferred_axis_branch_id,
        branch_road_memberships=dict(prepared.branch_road_memberships),
        branch_bridge_node_ids=dict(prepared.branch_bridge_node_ids),
        degraded_scope_reason=prepared.degraded_scope_reason,
    )


def _build_result_from_interpretation(
    *,
    prepared: _PreparedUnitInputs,
    interpretation,
    selected_candidate_summary: dict[str, Any],
    selected_candidate_region_geometry: BaseGeometry | None,
) -> T04EventUnitResult:
    bridge = interpretation.legacy_step5_bridge
    selected_component_union_geometry = bridge.divstrip_context.constraint_geometry
    localized_evidence_core_geometry = _materialize_selected_divstrip_geometry(
        interpretation=interpretation,
        selected_divstrip_geometry=selected_component_union_geometry,
        localized_divstrip_geometry=bridge.localized_divstrip_reference_geometry,
    )
    coarse_anchor_zone_geometry = _materialize_event_anchor_geometry(
        interpretation=interpretation,
        selected_divstrip_geometry=localized_evidence_core_geometry,
        drivezone_union=prepared.pair_local_drivezone_union,
    )
    fact_reference_point = bridge.event_origin_point
    review_materialized_point = _materialize_event_reference_point(
        interpretation=interpretation,
        selected_divstrip_geometry=localized_evidence_core_geometry,
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
    if prepared.degraded_scope_reason:
        review_reasons.append(f"degraded_scope:{prepared.degraded_scope_reason}")
    if fail_reasons:
        review_state = "STEP4_FAIL"
        all_reasons = tuple(dict.fromkeys([*fail_reasons, *review_reasons]))
    elif review_reasons:
        review_state = "STEP4_REVIEW"
        all_reasons = tuple(dict.fromkeys(review_reasons))
    else:
        review_state = "STEP4_OK"
        all_reasons = ()
    result = T04EventUnitResult(
        spec=prepared.event_unit_spec,
        unit_context=prepared.unit_context,
        unit_envelope=_build_unit_envelope(prepared),
        interpretation=interpretation,
        review_state=review_state,
        review_reasons=all_reasons,
        evidence_source=interpretation.evidence_decision.primary_source,
        position_source=interpretation.event_reference.event_position_source,
        reverse_tip_used=interpretation.reverse_tip_decision.used,
        rcsd_consistency_result=rcsd_consistency_result,
        selected_component_union_geometry=selected_component_union_geometry,
        localized_evidence_core_geometry=localized_evidence_core_geometry,
        coarse_anchor_zone_geometry=coarse_anchor_zone_geometry,
        pair_local_region_geometry=prepared.pair_local_region_geometry,
        pair_local_structure_face_geometry=prepared.pair_local_structure_face_geometry,
        pair_local_middle_geometry=prepared.pair_local_middle_geometry,
        pair_local_throat_core_geometry=prepared.pair_local_throat_core_geometry,
        selected_candidate_region_geometry=selected_candidate_region_geometry,
        fact_reference_point=fact_reference_point,
        review_materialized_point=review_materialized_point,
        positive_rcsd_geometry=positive_rcsd_geometry,
        selected_branch_ids=tuple(bridge.selected_branch_ids),
        selected_event_branch_ids=tuple(bridge.selected_event_branch_ids),
        selected_component_ids=tuple(bridge.divstrip_context.selected_component_ids),
        event_axis_branch_id=bridge.event_axis_branch_id,
        event_chosen_s_m=interpretation.event_reference.event_chosen_s_m,
        pair_local_summary=dict(prepared.pair_local_summary),
        selected_candidate_summary=dict(selected_candidate_summary),
    )
    if not bool(selected_candidate_summary.get("primary_eligible")):
        extra_review_notes = list(result.extra_review_notes)
        extra_review_notes.append("layer3_candidate_not_primary_eligible")
        result = replace(
            result,
            review_state="STEP4_REVIEW" if result.review_state == "STEP4_OK" else result.review_state,
            extra_review_notes=tuple(dict.fromkeys(extra_review_notes)),
        )
    return result


def _evaluate_unit_candidate(
    prepared: _PreparedUnitInputs,
    candidate: dict[str, Any],
) -> _CandidateEvaluation:
    local_context = prepared.unit_context.local_context
    direct_target_rc_nodes = _filter_nodes_to_scope(
        local_context.direct_target_rc_nodes,
        scope_geometry=prepared.pair_local_region_geometry,
        pad_m=PAIR_LOCAL_RCSD_SCOPE_PAD_M,
    ) or tuple(local_context.direct_target_rc_nodes)
    exact_target_rc_nodes = _filter_nodes_to_scope(
        local_context.exact_target_rc_nodes,
        scope_geometry=prepared.pair_local_region_geometry,
        pad_m=PAIR_LOCAL_RCSD_SCOPE_PAD_M,
    ) or tuple(local_context.exact_target_rc_nodes)
    primary_main_rc_node = local_context.primary_main_rc_node
    if primary_main_rc_node is not None:
        scoped_primary = _filter_nodes_to_scope(
            [primary_main_rc_node],
            scope_geometry=prepared.pair_local_region_geometry,
            pad_m=PAIR_LOCAL_RCSD_SCOPE_PAD_M,
        )
        primary_main_rc_node = scoped_primary[0] if scoped_primary else None
    interpretation_kwargs = {
        "representative_node": prepared.effective_representative_node,
        "representative_source_kind_2": prepared.effective_source_kind_2,
        "mainnodeid_norm": prepared.unit_context.admission.mainnodeid,
        "seed_union": _seed_union(
            representative_node=prepared.effective_representative_node,
            group_nodes=prepared.unit_context.group_nodes,
            local_context=local_context,
        ),
        "group_nodes": list(prepared.unit_context.group_nodes),
        "patch_size_m": float(prepared.pair_local_patch_size_m),
        "seed_center": local_context.seed_center,
        "drivezone_union": prepared.pair_local_drivezone_union,
        "local_roads": list(prepared.pair_local_scope_roads),
        "local_rcsd_roads": list(prepared.pair_local_scope_rcsd_roads),
        "local_rcsd_nodes": list(prepared.pair_local_scope_rcsd_nodes),
        "local_divstrip_features": list(candidate["divstrip_features"]),
        "road_branches": list(prepared.scoped_branches),
        "main_branch_ids": set(prepared.scoped_main_branch_ids),
        "member_node_ids": {str(node_id) for node_id in prepared.unit_population_node_ids},
        "direct_target_rc_nodes": list(direct_target_rc_nodes),
        "exact_target_rc_nodes": list(exact_target_rc_nodes),
        "primary_main_rc_node": primary_main_rc_node,
        "rcsdnode_seed_mode": local_context.rcsdnode_seed_mode,
        "chain_context": prepared.unit_context.topology_skeleton.chain_context.to_legacy_dict(),
        "event_branch_ids": set(prepared.explicit_event_branch_ids),
        "boundary_branch_ids": tuple(prepared.boundary_branch_ids),
        "preferred_axis_branch_id": prepared.preferred_axis_branch_id,
        "context_augmented_node_ids": set(prepared.context_augmented_node_ids),
        "degraded_scope_reason": prepared.degraded_scope_reason,
    }
    interpretation = _build_stage4_event_interpretation(
        **{
            key: value
            for key, value in interpretation_kwargs.items()
            if key in inspect.signature(_build_stage4_event_interpretation).parameters
        }
    )
    base_result = _build_result_from_interpretation(
        prepared=prepared,
        interpretation=interpretation,
        selected_candidate_summary=dict(candidate["summary"]),
        selected_candidate_region_geometry=candidate["region_geometry"],
    )
    merged_candidate_summary = _merge_candidate_evaluation(
        candidate["summary"],
        base_result,
    )
    result = replace(base_result, selected_candidate_summary=merged_candidate_summary)
    return _CandidateEvaluation(
        result=result,
        priority_score=_candidate_priority_score(merged_candidate_summary, result),
    )


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
    prepared_units: list[_PreparedUnitInputs] = []
    for event_unit_spec in event_unit_specs:
        singleton_group = event_unit_spec.split_mode == "complex_one_node_one_unit"
        cache_key = (event_unit_spec.representative_node_id, singleton_group)
        if cache_key not in unit_context_cache:
            unit_context_cache[cache_key] = _prepare_unit_context(
                case_bundle=case_bundle,
                representative_node_id=event_unit_spec.representative_node_id,
                singleton_group=singleton_group,
            )
        prepared_units.append(
            _prepare_unit_inputs(
                case_bundle=case_bundle,
                unit_context=unit_context_cache[cache_key],
                event_unit_spec=event_unit_spec,
            )
        )
    candidate_pools: list[list[_CandidateEvaluation]] = []
    for prepared in prepared_units:
        raw_candidates = _build_candidate_pool(prepared)
        evaluations = _rank_candidate_pool(
            [_evaluate_unit_candidate(prepared, candidate) for candidate in raw_candidates]
        )
        candidate_pools.append(evaluations)
    assignment_by_unit_index = _select_case_assignment(candidate_pools)

    event_units: list[T04EventUnitResult] = []
    for pool_index, evaluations in enumerate(candidate_pools):
        if not evaluations:
            continue
        selected_eval = assignment_by_unit_index[pool_index] or evaluations[0]
        selection_rank = next(
            (
                rank
                for rank, item in enumerate(evaluations, start=1)
                if item.result.selected_candidate_summary.get("candidate_id")
                == selected_eval.result.selected_candidate_summary.get("candidate_id")
            ),
            None,
        )
        alternative_candidates = tuple(
            dict(item.result.selected_candidate_summary)
            for item in evaluations
            if item.result.selected_candidate_summary.get("candidate_id")
            != selected_eval.result.selected_candidate_summary.get("candidate_id")
        )
        selected_candidate_summary = dict(selected_eval.result.selected_candidate_summary)
        selected_candidate_summary["selection_rank"] = selection_rank
        selected_candidate_summary["selected_after_reselection"] = bool(
            selection_rank is not None and selection_rank > 1
        )
        finalized_result = replace(
            selected_eval.result,
            selected_candidate_summary=selected_candidate_summary,
            alternative_candidate_summaries=alternative_candidates,
        )
        if assignment_by_unit_index[pool_index] is None:
            finalized_result = replace(
                finalized_result,
                review_state=(
                    "STEP4_REVIEW"
                    if finalized_result.review_state == "STEP4_OK"
                    else finalized_result.review_state
                ),
                extra_review_notes=tuple(
                    dict.fromkeys(
                        [*finalized_result.extra_review_notes, "no_independent_candidate_after_reselection"]
                    )
                ),
            )
        elif selection_rank is not None and selection_rank > 1:
            finalized_result = replace(
                finalized_result,
                extra_review_notes=tuple(
                    dict.fromkeys([*finalized_result.extra_review_notes, "reselected_within_case"])
                ),
            )
        event_units.append(finalized_result)
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
