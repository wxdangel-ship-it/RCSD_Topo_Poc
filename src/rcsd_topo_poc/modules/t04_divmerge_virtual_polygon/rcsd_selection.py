from __future__ import annotations

from typing import Sequence

from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import ParsedNode, ParsedRoad
from ._rcsd_selection_support import (
    PositiveRcsdSelectionDecision,
    _AggregatedRcsdUnit,
    _LocalRcsdUnit,
    _as_point,
    _build_aggregated_rcsd_units,
    _build_candidate_scope_geometry,
    _expected_swsd_role_map,
    _first_hit_roads,
    _node_ids_for_roads,
    _node_lookup,
    _normalize_geometry,
    _normal_vector,
    _operational_event_type,
    _road_enters_candidate_scope,
    _road_lookup,
    _roads_by_node,
    _safe_id,
    _trace_path_to_node,
    _union_geometry,
    _unit_from_roads_and_node,
)

def resolve_positive_rcsd_selection(
    *,
    event_unit_id: str,
    operational_kind_hint: int | None,
    representative_node: ParsedNode,
    selected_evidence_region_geometry: BaseGeometry | None,
    fact_reference_point: BaseGeometry | None,
    pair_local_region_geometry: BaseGeometry | None,
    pair_local_middle_geometry: BaseGeometry | None,
    scoped_rcsd_roads: Sequence[ParsedRoad],
    scoped_rcsd_nodes: Sequence[ParsedNode],
    pair_local_scope_rcsd_roads: Sequence[ParsedRoad],
    pair_local_scope_rcsd_nodes: Sequence[ParsedNode],
    scoped_roads: Sequence[ParsedRoad],
    boundary_branch_ids: Sequence[str],
    preferred_axis_branch_id: str | None,
    scoped_input_branch_ids: Sequence[str],
    scoped_output_branch_ids: Sequence[str],
    branch_road_memberships: dict[str, Sequence[str]],
    axis_vector: tuple[float, float] | None,
) -> PositiveRcsdSelectionDecision:
    representative_point = _as_point(getattr(representative_node, "geometry", None))
    reference_point = _as_point(fact_reference_point)
    if representative_point is None:
        raise ValueError("representative_node.geometry is required for RCSD selection")

    event_type = _operational_event_type(operational_kind_hint)
    pair_local_seed_node_ids = {
        node_id
        for node in pair_local_scope_rcsd_nodes
        if (node_id := _safe_id(getattr(node, "node_id", None))) is not None
    }
    raw_roads_by_id = _road_lookup(pair_local_scope_rcsd_roads)
    if pair_local_seed_node_ids:
        for road in scoped_rcsd_roads:
            road_id = _safe_id(getattr(road, "road_id", None))
            if road_id is None or road_id in raw_roads_by_id:
                continue
            if { _safe_id(getattr(road, "snodeid", None)), _safe_id(getattr(road, "enodeid", None)) } & pair_local_seed_node_ids:
                raw_roads_by_id[road_id] = road
    raw_road_endpoint_node_ids = _node_ids_for_roads(raw_roads_by_id.keys(), raw_roads_by_id)
    raw_node_features: list[ParsedNode] = []
    seen_raw_node_ids: set[str] = set()
    for node in (*pair_local_scope_rcsd_nodes, *scoped_rcsd_nodes):
        node_id = _safe_id(getattr(node, "node_id", None))
        if node_id is None or node_id in seen_raw_node_ids:
            continue
        if node in pair_local_scope_rcsd_nodes or node_id in raw_road_endpoint_node_ids:
            raw_node_features.append(node)
            seen_raw_node_ids.add(node_id)
    actual_rcsd_node_ids = {
        node_id
        for node in raw_node_features
        if (node_id := _safe_id(getattr(node, "node_id", None))) is not None
    }
    raw_nodes_by_id = _node_lookup(raw_node_features, roads=raw_roads_by_id.values())
    raw_rcsd_road_ids = tuple(sorted(raw_roads_by_id))
    raw_rcsd_node_ids = tuple(sorted(actual_rcsd_node_ids))
    pair_local_rcsd_empty = not raw_rcsd_road_ids and not raw_rcsd_node_ids
    candidate_scope_geometry = _build_candidate_scope_geometry(
        representative_point=representative_point,
        fact_reference_point=reference_point,
        selected_evidence_region_geometry=selected_evidence_region_geometry,
        pair_local_middle_geometry=pair_local_middle_geometry,
        pair_local_region_geometry=pair_local_region_geometry,
    )
    if pair_local_rcsd_empty:
        return PositiveRcsdSelectionDecision(
            selected_rcsdroad_ids=(),
            selected_rcsdnode_ids=(),
            primary_main_rc_node_id=None,
            positive_rcsd_present=False,
            positive_rcsd_present_reason="pair_local_rcsd_empty",
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            rcsd_consistency_result="missing_positive_rcsd",
            required_rcsd_node=None,
            required_rcsd_node_source=None,
            pair_local_rcsd_empty=True,
            pair_local_rcsd_road_ids=raw_rcsd_road_ids,
            pair_local_rcsd_node_ids=raw_rcsd_node_ids,
            first_hit_rcsdroad_ids=(),
            local_rcsd_unit_id=None,
            local_rcsd_unit_kind=None,
            aggregated_rcsd_unit_id=None,
            aggregated_rcsd_unit_ids=(),
            axis_polarity_inverted=False,
            rcsd_selection_mode="pair_local_empty",
            rcsd_decision_reason="pair_local_rcsd_empty",
            positive_rcsd_geometry=None,
            positive_rcsd_road_geometry=None,
            positive_rcsd_node_geometry=None,
            primary_main_rc_node_geometry=None,
            required_rcsd_node_geometry=None,
            pair_local_rcsd_scope_geometry=candidate_scope_geometry,
            first_hit_rcsd_road_geometry=None,
            local_rcsd_unit_geometry=None,
            positive_rcsd_audit={
                "pair_local_rcsd_empty": True,
                "operational_event_type": event_type,
                "raw_observation_rcsdroad_ids": list(raw_rcsd_road_ids),
                "raw_observation_rcsdnode_ids": list(raw_rcsd_node_ids),
                "pair_local_rcsd_road_ids": list(raw_rcsd_road_ids),
                "pair_local_rcsd_node_ids": list(raw_rcsd_node_ids),
                "candidate_scope_rcsdroad_ids": [],
                "candidate_scope_rcsdnode_ids": [],
                "first_hit_rcsdroad_ids": [],
                "local_rcsd_units": [],
                "aggregated_rcsd_units": [],
                "positive_rcsd_present": False,
                "positive_rcsd_present_reason": "pair_local_rcsd_empty",
                "axis_polarity_inverted": False,
                "required_rcsd_node_source": None,
                "rcsd_role_map": {},
                "rcsd_decision_reason": "pair_local_rcsd_empty",
            },
        )

    axis_vector_tuple = None if axis_vector is None else (float(axis_vector[0]), float(axis_vector[1]))
    normal_vector = _normal_vector(axis_vector_tuple)
    expected_role_map = _expected_swsd_role_map(
        event_type=event_type,
        boundary_branch_ids=boundary_branch_ids,
        scoped_input_branch_ids=scoped_input_branch_ids,
        scoped_output_branch_ids=scoped_output_branch_ids,
        preferred_axis_branch_id=preferred_axis_branch_id,
        branch_road_memberships=branch_road_memberships,
        scoped_roads=scoped_roads,
        representative_point=representative_point,
        normal_vector=normal_vector,
    )

    raw_roads = list(raw_roads_by_id.values())
    roads_by_id = raw_roads_by_id
    node_points_by_id = dict(raw_nodes_by_id)
    first_hit_road_ids, _hit_points, first_hit_geometry = _first_hit_roads(
        roads=raw_roads,
        fact_reference_point=reference_point,
        axis_vector=axis_vector_tuple,
    )

    candidate_scope_road_ids = {
        road_id
        for road_id, road in roads_by_id.items()
        if _road_enters_candidate_scope(
            road,
            candidate_scope_geometry=candidate_scope_geometry,
            selected_evidence_region_geometry=selected_evidence_region_geometry,
            fact_reference_point=reference_point,
        )
    }
    candidate_scope_road_ids.update(first_hit_road_ids)
    roads_by_node_id = _roads_by_node(raw_roads)
    candidate_node_ids = _node_ids_for_roads(candidate_scope_road_ids or first_hit_road_ids, roads_by_id) & set(actual_rcsd_node_ids)
    if candidate_scope_geometry is not None:
        for node_id, geometry in node_points_by_id.items():
            if node_id not in actual_rcsd_node_ids:
                continue
            if candidate_scope_geometry.buffer(1e-6).covers(geometry):
                candidate_node_ids.add(node_id)
    pair_local_rcsd_road_ids = tuple(sorted(candidate_scope_road_ids))
    pair_local_rcsd_node_ids = tuple(sorted(candidate_node_ids))
    pair_local_rcsd_empty = not pair_local_rcsd_road_ids and not pair_local_rcsd_node_ids
    if pair_local_rcsd_empty:
        return PositiveRcsdSelectionDecision(
            selected_rcsdroad_ids=(),
            selected_rcsdnode_ids=(),
            primary_main_rc_node_id=None,
            positive_rcsd_present=False,
            positive_rcsd_present_reason="candidate_scope_empty",
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            rcsd_consistency_result="missing_positive_rcsd",
            required_rcsd_node=None,
            required_rcsd_node_source=None,
            pair_local_rcsd_empty=True,
            pair_local_rcsd_road_ids=(),
            pair_local_rcsd_node_ids=(),
            first_hit_rcsdroad_ids=tuple(first_hit_road_ids),
            local_rcsd_unit_id=None,
            local_rcsd_unit_kind=None,
            aggregated_rcsd_unit_id=None,
            aggregated_rcsd_unit_ids=(),
            axis_polarity_inverted=False,
            rcsd_selection_mode="pair_local_empty",
            rcsd_decision_reason="pair_local_rcsd_empty",
            positive_rcsd_geometry=None,
            positive_rcsd_road_geometry=None,
            positive_rcsd_node_geometry=None,
            primary_main_rc_node_geometry=None,
            required_rcsd_node_geometry=None,
            pair_local_rcsd_scope_geometry=candidate_scope_geometry,
            first_hit_rcsd_road_geometry=first_hit_geometry,
            local_rcsd_unit_geometry=None,
            positive_rcsd_audit={
                "pair_local_rcsd_empty": True,
                "operational_event_type": event_type,
                "raw_observation_rcsdroad_ids": list(raw_rcsd_road_ids),
                "raw_observation_rcsdnode_ids": list(raw_rcsd_node_ids),
                "pair_local_rcsd_road_ids": [],
                "pair_local_rcsd_node_ids": [],
                "candidate_scope_rcsdroad_ids": list(pair_local_rcsd_road_ids),
                "candidate_scope_rcsdnode_ids": list(pair_local_rcsd_node_ids),
                "first_hit_rcsdroad_ids": list(first_hit_road_ids),
                "local_rcsd_units": [],
                "aggregated_rcsd_units": [],
                "positive_rcsd_present": False,
                "positive_rcsd_present_reason": "candidate_scope_empty",
                "axis_polarity_inverted": False,
                "required_rcsd_node_source": None,
                "rcsd_role_map": expected_role_map,
                "rcsd_decision_reason": "pair_local_rcsd_empty",
            },
        )
    discussion_road_ids = set(candidate_scope_road_ids)
    for node_id in tuple(candidate_node_ids):
        discussion_road_ids.update(roads_by_node_id.get(node_id, set()))

    local_units: list[_LocalRcsdUnit] = []
    for node_id in sorted(candidate_node_ids):
        attached_road_ids = [
            road_id
            for road_id in sorted(roads_by_node_id.get(node_id, set()))
            if road_id in roads_by_id and (
                road_id in discussion_road_ids or road_id in set(first_hit_road_ids)
            )
        ]
        if len(attached_road_ids) < 2:
            continue
        unit = _unit_from_roads_and_node(
            unit_id=f"{event_unit_id}:node:{node_id}",
            unit_kind="node_centric",
            node_id=node_id,
            road_ids=attached_road_ids,
            roads_by_id=roads_by_id,
            node_points_by_id=node_points_by_id,
            actual_node_ids=set(actual_rcsd_node_ids),
            expected_role_map=expected_role_map,
            representative_point=representative_point,
            axis_vector=axis_vector_tuple,
            normal_vector=normal_vector,
            first_hit_road_ids=set(first_hit_road_ids),
        )
        local_units.append(unit)

    road_only_road_ids = tuple(sorted(discussion_road_ids or set(first_hit_road_ids)))
    if road_only_road_ids:
        local_units.append(
            _unit_from_roads_and_node(
                unit_id=f"{event_unit_id}:road_only:01",
                unit_kind="road_only",
                node_id=None,
                road_ids=road_only_road_ids,
                roads_by_id=roads_by_id,
                node_points_by_id=node_points_by_id,
                actual_node_ids=set(actual_rcsd_node_ids),
                expected_role_map=expected_role_map,
                representative_point=representative_point,
                axis_vector=axis_vector_tuple,
                normal_vector=normal_vector,
                first_hit_road_ids=set(first_hit_road_ids),
            )
        )

    if not local_units:
        return PositiveRcsdSelectionDecision(
            selected_rcsdroad_ids=(),
            selected_rcsdnode_ids=(),
            primary_main_rc_node_id=None,
            positive_rcsd_present=False,
            positive_rcsd_present_reason="local_rcsd_unit_not_constructed",
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            rcsd_consistency_result="missing_positive_rcsd",
            required_rcsd_node=None,
            required_rcsd_node_source=None,
            pair_local_rcsd_empty=False,
            pair_local_rcsd_road_ids=pair_local_rcsd_road_ids,
            pair_local_rcsd_node_ids=pair_local_rcsd_node_ids,
            first_hit_rcsdroad_ids=tuple(first_hit_road_ids),
            local_rcsd_unit_id=None,
            local_rcsd_unit_kind=None,
            aggregated_rcsd_unit_id=None,
            aggregated_rcsd_unit_ids=(),
            axis_polarity_inverted=False,
            rcsd_selection_mode="no_local_unit",
            rcsd_decision_reason="pair_local_rcsd_unit_not_constructed",
            positive_rcsd_geometry=None,
            positive_rcsd_road_geometry=None,
            positive_rcsd_node_geometry=None,
            primary_main_rc_node_geometry=None,
            required_rcsd_node_geometry=None,
            pair_local_rcsd_scope_geometry=candidate_scope_geometry,
            first_hit_rcsd_road_geometry=first_hit_geometry,
            local_rcsd_unit_geometry=None,
            positive_rcsd_audit={
                "pair_local_rcsd_empty": False,
                "operational_event_type": event_type,
                "raw_observation_rcsdroad_ids": list(raw_rcsd_road_ids),
                "raw_observation_rcsdnode_ids": list(raw_rcsd_node_ids),
                "pair_local_rcsd_road_ids": list(pair_local_rcsd_road_ids),
                "pair_local_rcsd_node_ids": list(pair_local_rcsd_node_ids),
                "candidate_scope_rcsdroad_ids": list(pair_local_rcsd_road_ids),
                "candidate_scope_rcsdnode_ids": list(pair_local_rcsd_node_ids),
                "first_hit_rcsdroad_ids": list(first_hit_road_ids),
                "local_rcsd_units": [],
                "aggregated_rcsd_units": [],
                "positive_rcsd_present": False,
                "positive_rcsd_present_reason": "local_rcsd_unit_not_constructed",
                "axis_polarity_inverted": False,
                "required_rcsd_node_source": None,
                "rcsd_role_map": expected_role_map,
                "rcsd_decision_reason": "pair_local_rcsd_unit_not_constructed",
            },
        )

    local_units.sort(key=lambda unit: unit.score, reverse=True)
    aggregated_units = _build_aggregated_rcsd_units(
        event_unit_id=event_unit_id,
        local_units=local_units,
        expected_role_map=expected_role_map,
        first_hit_road_ids=tuple(first_hit_road_ids),
        roads_by_id=roads_by_id,
        roads_by_node_id=roads_by_node_id,
        node_points_by_id=node_points_by_id,
        representative_point=representative_point,
    )
    if not aggregated_units:
        return PositiveRcsdSelectionDecision(
            selected_rcsdroad_ids=(),
            selected_rcsdnode_ids=(),
            primary_main_rc_node_id=None,
            positive_rcsd_present=False,
            positive_rcsd_present_reason="positive_rcsd_absent_after_local_units",
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            rcsd_consistency_result="missing_positive_rcsd",
            required_rcsd_node=None,
            required_rcsd_node_source=None,
            pair_local_rcsd_empty=False,
            pair_local_rcsd_road_ids=pair_local_rcsd_road_ids,
            pair_local_rcsd_node_ids=pair_local_rcsd_node_ids,
            first_hit_rcsdroad_ids=tuple(first_hit_road_ids),
            local_rcsd_unit_id=None,
            local_rcsd_unit_kind=None,
            aggregated_rcsd_unit_id=None,
            aggregated_rcsd_unit_ids=(),
            axis_polarity_inverted=False,
            rcsd_selection_mode="no_positive_present",
            rcsd_decision_reason="positive_rcsd_absent_after_local_units",
            positive_rcsd_geometry=None,
            positive_rcsd_road_geometry=None,
            positive_rcsd_node_geometry=None,
            primary_main_rc_node_geometry=None,
            required_rcsd_node_geometry=None,
            pair_local_rcsd_scope_geometry=candidate_scope_geometry,
            first_hit_rcsd_road_geometry=first_hit_geometry,
            local_rcsd_unit_geometry=None,
            positive_rcsd_audit={
                "pair_local_rcsd_empty": False,
                "operational_event_type": event_type,
                "raw_observation_rcsdroad_ids": list(raw_rcsd_road_ids),
                "raw_observation_rcsdnode_ids": list(raw_rcsd_node_ids),
                "pair_local_rcsd_road_ids": list(pair_local_rcsd_road_ids),
                "pair_local_rcsd_node_ids": list(pair_local_rcsd_node_ids),
                "candidate_scope_rcsdroad_ids": list(pair_local_rcsd_road_ids),
                "candidate_scope_rcsdnode_ids": list(pair_local_rcsd_node_ids),
                "first_hit_rcsdroad_ids": list(first_hit_road_ids),
                "local_rcsd_units": [unit.to_doc() for unit in local_units],
                "aggregated_rcsd_units": [],
                "positive_rcsd_present": False,
                "positive_rcsd_present_reason": "positive_rcsd_absent_after_local_units",
                "axis_polarity_inverted": False,
                "required_rcsd_node_source": None,
                "rcsd_role_map": expected_role_map,
                "rcsd_decision_reason": "positive_rcsd_absent_after_local_units",
            },
        )

    selected_aggregated = aggregated_units[0]
    selected_local_unit = next(
        (
            unit
            for unit in local_units
            if unit.unit_id == selected_aggregated.primary_local_unit_id
        ),
        local_units[0],
    )
    selected_road_ids = set(selected_aggregated.road_ids)
    if selected_aggregated.required_node_id is not None and first_hit_road_ids:
        for road_id in first_hit_road_ids:
            traced = _trace_path_to_node(
                start_road_id=road_id,
                target_node_id=selected_aggregated.required_node_id,
                roads_by_id=roads_by_id,
                roads_by_node_id=roads_by_node_id,
            )
            selected_road_ids.update(traced)
    selected_rcsd_roads = tuple(sorted(selected_road_ids))
    selected_rcsd_nodes = tuple(sorted({*selected_aggregated.node_ids} - {None}))
    selected_road_geometry = _union_geometry(
        roads_by_id[road_id].geometry
        for road_id in selected_rcsd_roads
        if road_id in roads_by_id
    )
    selected_node_geometry = _union_geometry(
        node_points_by_id[node_id]
        for node_id in selected_rcsd_nodes
        if node_id in node_points_by_id
    )
    selected_geometry = _union_geometry([selected_road_geometry, selected_node_geometry])
    primary_main_rc_node_id = selected_aggregated.primary_node_id
    primary_main_rc_node_geometry = None
    if primary_main_rc_node_id is not None and primary_main_rc_node_id in node_points_by_id:
        primary_main_rc_node_geometry = node_points_by_id[primary_main_rc_node_id]
    required_rcsd_node = selected_aggregated.required_node_id
    required_rcsd_node_geometry = None
    if required_rcsd_node is not None and required_rcsd_node in node_points_by_id:
        required_rcsd_node_geometry = node_points_by_id[required_rcsd_node]
    if selected_aggregated.consistency_level == "A":
        consistency_result = "positive_rcsd_strong_consistent"
    elif selected_aggregated.consistency_level == "B":
        consistency_result = "positive_rcsd_partial_consistent"
    else:
        consistency_result = "missing_positive_rcsd"
    selection_mode = "aggregated"
    if selected_local_unit.unit_kind:
        selection_mode = f"aggregated_{selected_local_unit.unit_kind}"
    if first_hit_road_ids:
        selection_mode = f"{selection_mode}_from_first_hit"
    return PositiveRcsdSelectionDecision(
        selected_rcsdroad_ids=selected_rcsd_roads,
        selected_rcsdnode_ids=selected_rcsd_nodes,
        primary_main_rc_node_id=primary_main_rc_node_id,
        positive_rcsd_present=selected_aggregated.positive_rcsd_present,
        positive_rcsd_present_reason=selected_aggregated.positive_rcsd_present_reason,
        positive_rcsd_support_level=selected_aggregated.support_level,
        positive_rcsd_consistency_level=selected_aggregated.consistency_level,
        rcsd_consistency_result=consistency_result,
        required_rcsd_node=required_rcsd_node,
        required_rcsd_node_source=selected_aggregated.required_node_source,
        pair_local_rcsd_empty=False,
        pair_local_rcsd_road_ids=pair_local_rcsd_road_ids,
        pair_local_rcsd_node_ids=pair_local_rcsd_node_ids,
        first_hit_rcsdroad_ids=tuple(first_hit_road_ids),
        local_rcsd_unit_id=selected_local_unit.unit_id,
        local_rcsd_unit_kind=selected_local_unit.unit_kind,
        aggregated_rcsd_unit_id=selected_aggregated.unit_id,
        aggregated_rcsd_unit_ids=selected_aggregated.member_unit_ids,
        axis_polarity_inverted=selected_aggregated.axis_polarity_inverted,
        rcsd_selection_mode=selection_mode,
        rcsd_decision_reason=selected_aggregated.decision_reason,
        positive_rcsd_geometry=selected_geometry,
        positive_rcsd_road_geometry=selected_road_geometry,
        positive_rcsd_node_geometry=selected_node_geometry,
        primary_main_rc_node_geometry=primary_main_rc_node_geometry,
        required_rcsd_node_geometry=required_rcsd_node_geometry,
        pair_local_rcsd_scope_geometry=candidate_scope_geometry,
        first_hit_rcsd_road_geometry=first_hit_geometry,
        local_rcsd_unit_geometry=selected_local_unit.geometry,
        positive_rcsd_audit={
            "pair_local_rcsd_empty": False,
            "operational_event_type": event_type,
            "raw_observation_rcsdroad_ids": list(raw_rcsd_road_ids),
            "raw_observation_rcsdnode_ids": list(raw_rcsd_node_ids),
            "pair_local_rcsd_road_ids": list(pair_local_rcsd_road_ids),
            "pair_local_rcsd_node_ids": list(pair_local_rcsd_node_ids),
            "candidate_scope_rcsdroad_ids": list(pair_local_rcsd_road_ids),
            "candidate_scope_rcsdnode_ids": list(pair_local_rcsd_node_ids),
            "first_hit_rcsdroad_ids": list(first_hit_road_ids),
            "local_rcsd_unit_id": selected_local_unit.unit_id,
            "local_rcsd_unit_kind": selected_local_unit.unit_kind,
            "aggregated_rcsd_unit_id": selected_aggregated.unit_id,
            "aggregated_rcsd_unit_ids": list(selected_aggregated.member_unit_ids),
            "rcsd_selection_mode": selection_mode,
            "positive_rcsd_present": selected_aggregated.positive_rcsd_present,
            "positive_rcsd_present_reason": selected_aggregated.positive_rcsd_present_reason,
            "axis_polarity_inverted": selected_aggregated.axis_polarity_inverted,
            "required_rcsd_node_source": selected_aggregated.required_node_source,
            "rcsd_decision_reason": selected_aggregated.decision_reason,
            "rcsd_role_map": expected_role_map,
            "selected_unit_role_assignments": list(selected_local_unit.role_assignments),
            "local_rcsd_units": [unit.to_doc() for unit in local_units],
            "aggregated_rcsd_units": [unit.to_doc() for unit in aggregated_units],
        },
    )
