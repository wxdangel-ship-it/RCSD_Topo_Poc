from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable

from shapely.geometry import GeometryCollection
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, unary_union

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step4_geometry_core import (
    PAIR_LOCAL_BRANCH_MAX_LENGTH_M,
    _node_source_kind_2,
    _resolve_branch_centerline,
    _resolve_event_axis_branch,
    _resolve_scan_axis_unit_vector,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step4_geometry_base import (
    _build_pair_local_slice_diagnostic,
    _pick_cross_section_boundary_branches,
    _resolve_event_axis_unit_vector,
    _resolve_event_cross_half_len,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.case_models import (
    T04CaseBundle,
    T04UnitContext,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.event_interpretation_shared import (
    _ExecutableBranchSet,
    _PreparedUnitInputs,
    _clip_geometry_to_scope,
    _filter_divstrip_features_to_scope,
    _filter_nodes_to_scope,
    _filter_roads_to_scope,
    _road_lookup,
    _safe_normalize_geometry,
    _stable_boundary_pair_signature,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.variant_ranking import (
    _pair_interval_variant_metrics_from_data,
)


DIVSTRIP_EVIDENCE_TIP_RADIUS_M = 8.0
PAIR_LOCAL_SCAN_STEP_M = 4.0
PAIR_LOCAL_SCAN_STOP_MISS_COUNT = 4
PAIR_LOCAL_SLICE_BUFFER_M = 2.5
PAIR_LOCAL_REGION_PAD_M = 4.0
PAIR_LOCAL_SCOPE_PAD_M = 10.0
PAIR_LOCAL_RCSD_SCOPE_PAD_M = 18.0
PAIR_LOCAL_THROAT_RADIUS_M = 10.0
NODE_FALLBACK_AXIS_POSITION_MAX_M = 1.0
NODE_FALLBACK_DISTANCE_MAX_M = 3.0
ROAD_SURFACE_FORK_SCOPE = "road_surface_fork"
STRUCTURE_BODY_THROAT_EXCLUSION_M = 8.0
MAX_CANDIDATES_PER_UNIT = 6
COMPLEX_SUBUNIT_SCOPE_RADIUS_M = 60.0
COMPLEX_SUBUNIT_ROAD_PAD_M = 10.0
COMPLEX_SUBUNIT_DIVSTRIP_PAD_M = 12.0
COMPLEX_SUBUNIT_RCSD_PAD_M = 18.0

HARD_DEGRADED_SCOPE_REASONS = {
    "pair_local_middle_missing",
}

def _dedupe_reason_list(values: Iterable[Any]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _degraded_scope_metadata(reasons: Iterable[Any]) -> tuple[str | None, str | None, bool]:
    deduped = _dedupe_reason_list(reasons)
    if not deduped:
        return None, None, False
    severity = "hard" if any(reason in HARD_DEGRADED_SCOPE_REASONS for reason in deduped) else "soft"
    return "|".join(deduped), severity, True

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
    slice_diagnostic_builder=None,
) -> _PreparedUnitInputs:
    build_slice_diagnostic = slice_diagnostic_builder or _build_pair_local_slice_diagnostic
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
    allowed_pair_branch_ids = tuple(str(branch_id) for branch_id in boundary_branch_ids)
    allowed_pair_road_ids = {
        str(road_id)
        for branch_id in allowed_pair_branch_ids
        for road_id in branch_road_memberships.get(str(branch_id), ())
    }
    event_branch_road_ids = {
        str(road_id)
        for branch_id in explicit_event_branch_ids
        for road_id in branch_road_memberships.get(str(branch_id), ())
    }
    branch_separation_threshold_m = max(
        float(PAIR_LOCAL_THROAT_RADIUS_M) * 2.0,
        float(event_cross_half_len_m) * 2.0,
    )
    branch_separation_values: list[float] = []
    pair_local_direction = "none"
    stop_reason: str | None = None
    intruding_road_ids: tuple[str, ...] = ()
    pair_replacement_road_ids: tuple[str, ...] = ()
    branch_separation_stop_triggered = False
    branch_separation_consecutive_exceed_count = 0

    def _build_slice_geometry_from_diag(diag: dict[str, Any]) -> BaseGeometry | None:
        segment = diag.get("segment")
        center_point = diag.get("center_point")
        if segment is None or center_point is None:
            return None
        if pair_scan_truncated_to_local and (
            not bool(diag.get("branch_a_crossline_hit"))
            or not bool(diag.get("branch_b_crossline_hit"))
        ):
            return None
        segment_length = float(diag.get("seg_len_m", 0.0) or 0.0)
        if segment_length <= 1e-3:
            slice_geometry = center_point.buffer(PAIR_LOCAL_SLICE_BUFFER_M, join_style=2)
        else:
            slice_geometry = segment.buffer(PAIR_LOCAL_SLICE_BUFFER_M, cap_style=2, join_style=2)
        if local_context.patch_drivezone_union is not None and not local_context.patch_drivezone_union.is_empty:
            slice_geometry = slice_geometry.intersection(local_context.patch_drivezone_union)
        return _safe_normalize_geometry(slice_geometry)

    def _scan_pair_local_direction(direction_sign: float) -> dict[str, Any]:
        local_slices: list[BaseGeometry] = []
        local_offsets: list[float] = []
        local_separations: list[float] = []
        miss_count = 0
        separation_exceed_streak = 0
        local_stop_reason: str | None = None
        local_intruding_road_ids: tuple[str, ...] = ()
        local_pair_replacement_road_ids: tuple[str, ...] = ()
        max_step_count = int(float(PAIR_LOCAL_BRANCH_MAX_LENGTH_M) // PAIR_LOCAL_SCAN_STEP_M)
        for step_index in range(1, max_step_count + 1):
            scan_s = float(direction_sign * step_index * PAIR_LOCAL_SCAN_STEP_M)
            diag = build_slice_diagnostic(
                origin_point=axis_origin_point,
                axis_unit_vector=scan_axis_unit_vector,
                scan_dist_m=scan_s,
                cross_half_len_m=float(event_cross_half_len_m),
                branch_a_centerline=branch_a_centerline,
                branch_b_centerline=branch_b_centerline,
                scoped_roads=list(scoped_roads),
                allowed_road_ids=set(allowed_pair_road_ids),
                event_road_ids=set(event_branch_road_ids),
                branch_separation_threshold_m=float(branch_separation_threshold_m),
                throat_radius_m=float(PAIR_LOCAL_THROAT_RADIUS_M),
            )
            step_stop_reason = str(diag.get("stop_reason") or "semantic_boundary_reached")
            slice_geometry = None
            if step_stop_reason == "ok":
                slice_geometry = _build_slice_geometry_from_diag(diag)
            if slice_geometry is not None:
                local_slices.append(slice_geometry)
                local_offsets.append(scan_s)
                local_separations.append(float(diag.get("seg_len_m", 0.0) or 0.0))
                miss_count = 0
                separation_exceed_streak = 0
                continue
            if step_stop_reason in {"pair_relation_replaced", "road_intrusion_between_branches"}:
                local_stop_reason = step_stop_reason
                local_intruding_road_ids = tuple(diag.get("intruding_road_ids") or ())
                local_pair_replacement_road_ids = tuple(diag.get("pair_replacement_road_ids") or ())
                break
            miss_count += 1
            if bool(diag.get("branch_separation_exceeded")):
                separation_exceed_streak += 1
            else:
                separation_exceed_streak = 0
            if (collected_slices or local_slices) and miss_count >= PAIR_LOCAL_SCAN_STOP_MISS_COUNT:
                if separation_exceed_streak >= PAIR_LOCAL_SCAN_STOP_MISS_COUNT:
                    local_stop_reason = "branch_separation_too_large"
                else:
                    local_stop_reason = step_stop_reason
                break
        if local_stop_reason is None and local_offsets:
            local_stop_reason = "max_branch_length_reached"
        return {
            "slices": local_slices,
            "offsets": local_offsets,
            "separations": local_separations,
            "stop_reason": local_stop_reason,
            "intruding_road_ids": local_intruding_road_ids,
            "pair_replacement_road_ids": local_pair_replacement_road_ids,
            "branch_separation_consecutive_exceed_count": separation_exceed_streak,
            "branch_separation_stop_triggered": local_stop_reason == "branch_separation_too_large",
        }

    initial_diag = None
    if (
        scan_axis_unit_vector is not None
        and branch_a_centerline is not None
        and not branch_a_centerline.is_empty
        and branch_b_centerline is not None
        and not branch_b_centerline.is_empty
    ):
        initial_diag = build_slice_diagnostic(
            origin_point=axis_origin_point,
            axis_unit_vector=scan_axis_unit_vector,
            scan_dist_m=0.0,
            cross_half_len_m=float(event_cross_half_len_m),
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            scoped_roads=list(scoped_roads),
            allowed_road_ids=set(allowed_pair_road_ids),
            event_road_ids=set(event_branch_road_ids),
            branch_separation_threshold_m=float(branch_separation_threshold_m),
            throat_radius_m=float(PAIR_LOCAL_THROAT_RADIUS_M),
        )
    initial_slice = (
        None
        if initial_diag is None or str(initial_diag.get("stop_reason") or "ok") != "ok"
        else _build_slice_geometry_from_diag(initial_diag)
    )
    if initial_diag is not None and str(initial_diag.get("stop_reason") or "ok") != "ok":
        stop_reason = str(initial_diag.get("stop_reason") or "")
        intruding_road_ids = tuple(initial_diag.get("intruding_road_ids") or ())
        pair_replacement_road_ids = tuple(initial_diag.get("pair_replacement_road_ids") or ())
        branch_separation_stop_triggered = stop_reason == "branch_separation_too_large"
    if initial_slice is not None:
        collected_slices.append(initial_slice)
        valid_offsets.append(0.0)
        branch_separation_values.append(float(initial_diag.get("seg_len_m", 0.0) or 0.0))
    forward_scan = (
        {
            "slices": [],
            "offsets": [],
            "separations": [],
            "stop_reason": None,
            "intruding_road_ids": (),
            "pair_replacement_road_ids": (),
            "branch_separation_consecutive_exceed_count": 0,
            "branch_separation_stop_triggered": False,
        }
        if scan_axis_unit_vector is None
        else _scan_pair_local_direction(1.0)
    )
    selected_scan = forward_scan
    if forward_scan["offsets"]:
        pair_local_direction = "forward"
    else:
        reverse_scan = (
            {
                "slices": [],
                "offsets": [],
                "separations": [],
                "stop_reason": None,
                "intruding_road_ids": (),
                "pair_replacement_road_ids": (),
                "branch_separation_consecutive_exceed_count": 0,
                "branch_separation_stop_triggered": False,
            }
            if scan_axis_unit_vector is None
            else _scan_pair_local_direction(-1.0)
        )
        if reverse_scan["offsets"]:
            selected_scan = reverse_scan
            pair_local_direction = "reverse_fallback"
        elif initial_slice is not None:
            pair_local_direction = "origin_only"
        stop_reason = selected_scan["stop_reason"] or reverse_scan["stop_reason"]
        intruding_road_ids = tuple(selected_scan["intruding_road_ids"] or reverse_scan["intruding_road_ids"])
        pair_replacement_road_ids = tuple(
            selected_scan["pair_replacement_road_ids"] or reverse_scan["pair_replacement_road_ids"]
        )
        branch_separation_consecutive_exceed_count = max(
            int(selected_scan["branch_separation_consecutive_exceed_count"]),
            int(reverse_scan["branch_separation_consecutive_exceed_count"]),
        )
        branch_separation_stop_triggered = bool(
            selected_scan["branch_separation_stop_triggered"] or reverse_scan["branch_separation_stop_triggered"]
        )
    if pair_local_direction == "none":
        stop_reason = stop_reason or selected_scan["stop_reason"]
        intruding_road_ids = tuple(selected_scan["intruding_road_ids"])
        pair_replacement_road_ids = tuple(selected_scan["pair_replacement_road_ids"])
        branch_separation_consecutive_exceed_count = int(
            selected_scan["branch_separation_consecutive_exceed_count"]
        )
        branch_separation_stop_triggered = bool(selected_scan["branch_separation_stop_triggered"])
    collected_slices.extend(selected_scan["slices"])
    valid_offsets.extend(selected_scan["offsets"])
    branch_separation_values.extend(float(item) for item in selected_scan["separations"])
    if stop_reason is None:
        stop_reason = selected_scan["stop_reason"]
    if not intruding_road_ids:
        intruding_road_ids = tuple(selected_scan["intruding_road_ids"])
    if not pair_replacement_road_ids:
        pair_replacement_road_ids = tuple(selected_scan["pair_replacement_road_ids"])
    if not branch_separation_consecutive_exceed_count:
        branch_separation_consecutive_exceed_count = int(
            selected_scan["branch_separation_consecutive_exceed_count"]
        )
    if not branch_separation_stop_triggered:
        branch_separation_stop_triggered = bool(selected_scan["branch_separation_stop_triggered"])

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
        stop_reason = stop_reason or "pair_local_middle_missing"
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
    )
    pair_local_scope_rcsd_nodes = _filter_nodes_to_scope(
        scoped_rcsd_nodes,
        scope_geometry=scope_geometry,
        pad_m=PAIR_LOCAL_RCSD_SCOPE_PAD_M,
    )
    if not pair_local_scope_rcsd_roads and not pair_local_scope_rcsd_nodes:
        pair_local_degraded_reasons.append("pair_local_scope_rcsd_empty")
    if pair_local_drivezone_union is not None and not pair_local_drivezone_union.is_empty:
        pair_local_drivezone_cover = pair_local_drivezone_union.buffer(0)
        contained_rcsd_roads = tuple(
            road
            for road in pair_local_scope_rcsd_roads
            if road.geometry is not None
            and not road.geometry.is_empty
            and pair_local_drivezone_cover.covers(road.geometry)
        )
        if len(contained_rcsd_roads) < len(pair_local_scope_rcsd_roads):
            pair_local_degraded_reasons.append("pair_local_scope_rcsd_outside_drivezone_filtered")
        pair_local_scope_rcsd_roads = contained_rcsd_roads
        contained_rcsd_nodes = tuple(
            node
            for node in pair_local_scope_rcsd_nodes
            if node.geometry is not None
            and not node.geometry.is_empty
            and pair_local_drivezone_cover.covers(node.geometry)
        )
        if len(contained_rcsd_nodes) < len(pair_local_scope_rcsd_nodes):
            pair_local_degraded_reasons.append("pair_local_scope_rcsdnode_outside_drivezone_filtered")
        pair_local_scope_rcsd_nodes = contained_rcsd_nodes
    if not pair_local_scope_rcsd_roads and not pair_local_scope_rcsd_nodes:
        pair_local_degraded_reasons.append("pair_local_scope_rcsd_empty")
    pair_local_scope_divstrip_features = _filter_divstrip_features_to_scope(
        scoped_divstrip_features,
        scope_geometry=scope_geometry,
        pad_m=PAIR_LOCAL_REGION_PAD_M,
    )
    pair_local_patch_size_m = float(local_context.patch_size_m)
    if pair_local_region_geometry is not None:
        minx, miny, maxx, maxy = pair_local_region_geometry.bounds
        pair_local_patch_size_m = max(float(maxx - minx), float(maxy - miny), float(PAIR_LOCAL_THROAT_RADIUS_M) * 2.0)
    degraded_scope_reason, degraded_scope_severity, degraded_scope_fallback_used = _degraded_scope_metadata(
        pair_local_degraded_reasons
    )
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
        "pair_local_direction": pair_local_direction,
        "pair_scan_truncated_to_local": bool(pair_scan_truncated_to_local),
        "degraded_reasons": list(dict.fromkeys(pair_local_degraded_reasons)),
        "degraded_scope_reason": degraded_scope_reason,
        "degraded_scope_severity": degraded_scope_severity,
        "degraded_scope_fallback_used": bool(degraded_scope_fallback_used),
        "valid_scan_offsets_m": [round(float(offset), 3) for offset in sorted(valid_offsets)],
        "branch_separation_mean_m": (
            None
            if not branch_separation_values
            else round(float(sum(branch_separation_values) / len(branch_separation_values)), 3)
        ),
        "branch_separation_max_m": (
            None if not branch_separation_values else round(float(max(branch_separation_values)), 3)
        ),
        "branch_separation_threshold_m": round(float(branch_separation_threshold_m), 3),
        "branch_separation_consecutive_exceed_count": int(branch_separation_consecutive_exceed_count),
        "branch_separation_stop_triggered": bool(branch_separation_stop_triggered),
        "stop_reason": stop_reason,
        "intruding_road_ids": list(intruding_road_ids),
        "pair_replacement_road_ids": list(pair_replacement_road_ids),
        "pair_local_rcsd_road_count": len(pair_local_scope_rcsd_roads),
        "pair_local_rcsd_node_count": len(pair_local_scope_rcsd_nodes),
        "pair_local_rcsd_empty": not pair_local_scope_rcsd_roads and not pair_local_scope_rcsd_nodes,
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
        degraded_scope_reason=degraded_scope_reason,
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
