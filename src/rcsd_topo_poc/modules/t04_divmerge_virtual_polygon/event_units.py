from __future__ import annotations

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import normalize_id
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step4_geometry_core import (
    COMPLEX_JUNCTION_KIND,
    _node_source_kind,
    _node_source_kind_2,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import (
    _branch_candidate_from_road,
)

from .case_models import T04EventUnitSpec, T04UnitContext


def _branch_angle(branch) -> float:
    angle = float(getattr(branch, "angle_deg", 0.0) or 0.0)
    while angle < 0.0:
        angle += 360.0
    while angle >= 360.0:
        angle -= 360.0
    return angle


def _sorted_side_branches(unit_context: T04UnitContext):
    main_branch_ids = set(unit_context.topology_skeleton.branch_result.main_branch_ids)
    side_branches = [
        branch
        for branch in unit_context.topology_skeleton.branch_result.road_branches
        if str(branch.branch_id) not in main_branch_ids
    ]
    return sorted(side_branches, key=lambda branch: (_branch_angle(branch), str(branch.branch_id)))


def _is_complex_unit_member_node(*, node, mainnodeid: str) -> bool:
    return (
        node.has_evd == "yes"
        and node.is_anchor == "no"
        and normalize_id(node.mainnodeid or node.node_id) == normalize_id(mainnodeid)
    )


def _complex_drivezone(unit_context: T04UnitContext):
    return (
        unit_context.local_context.patch_drivezone_union
        if unit_context.local_context.patch_drivezone_union is not None
        else unit_context.local_context.drivezone_union
    )


def _complex_seed_branch_rows(*, unit_context: T04UnitContext, node_id: str):
    drivezone_union = _complex_drivezone(unit_context)
    if drivezone_union is None or drivezone_union.is_empty:
        return ()
    rows: list[tuple[float, str, bool, bool]] = []
    for road in unit_context.local_context.patch_roads:
        if str(road.snodeid) != str(node_id) and str(road.enodeid) != str(node_id):
            continue
        candidate = _branch_candidate_from_road(
            road,
            member_node_ids={str(node_id)},
            drivezone_union=drivezone_union,
        )
        if candidate is None:
            continue
        rows.append(
            (
                float(candidate["angle_deg"]),
                str(road.road_id),
                bool(candidate["has_incoming_support"]),
                bool(candidate["has_outgoing_support"]),
            )
        )
    rows.sort(key=lambda item: (float(item[0]), item[1]))
    return tuple(
        (f"road_{index}", incoming, outgoing)
        for index, (_angle, _road_id, incoming, outgoing) in enumerate(rows, start=1)
    )


def _complex_adjacent_event_pairs(*, unit_context: T04UnitContext, node_id: str) -> tuple[tuple[str, str], ...]:
    branch_rows = _complex_seed_branch_rows(unit_context=unit_context, node_id=node_id)
    if len(branch_rows) < 3:
        return ()
    branch_order = tuple(branch_id for branch_id, _incoming, _outgoing in branch_rows)
    input_branch_ids = tuple(branch_id for branch_id, incoming, _outgoing in branch_rows if incoming)
    output_branch_ids = tuple(branch_id for branch_id, _incoming, outgoing in branch_rows if outgoing)
    if len(input_branch_ids) >= 2 and len(output_branch_ids) == 1:
        event_branch_ids = input_branch_ids
        axis_branch_id = output_branch_ids[0]
    elif len(output_branch_ids) >= 2 and len(input_branch_ids) == 1:
        event_branch_ids = output_branch_ids
        axis_branch_id = input_branch_ids[0]
    else:
        return ()
    event_branch_set = set(event_branch_ids)
    if axis_branch_id in branch_order:
        axis_index = branch_order.index(axis_branch_id)
        ordered = branch_order[axis_index + 1 :] + branch_order[:axis_index]
    else:
        ordered = branch_order
    ordered_event_branches = tuple(branch_id for branch_id in ordered if branch_id in event_branch_set)
    if len(ordered_event_branches) <= 2:
        return (tuple(ordered_event_branches),) if len(ordered_event_branches) == 2 else ()
    return tuple(
        (ordered_event_branches[index], ordered_event_branches[index + 1])
        for index in range(len(ordered_event_branches) - 1)
    )


def _complex_node_specs(*, unit_context: T04UnitContext, node_id: str) -> list[T04EventUnitSpec]:
    adjacent_pairs = _complex_adjacent_event_pairs(unit_context=unit_context, node_id=node_id)
    if len(adjacent_pairs) <= 1:
        return [
            T04EventUnitSpec(
                event_unit_id=f"node_{node_id}",
                event_type="complex_node",
                split_mode="complex_one_node_one_unit",
                representative_node_id=node_id,
                selected_side_branch_ids=(),
            )
        ]
    specs: list[T04EventUnitSpec] = []
    for index, pair in enumerate(adjacent_pairs, start=1):
        unit_id = f"node_{node_id}" if index == 1 else f"node_{node_id}__pair_{index:02d}"
        specs.append(
            T04EventUnitSpec(
                event_unit_id=unit_id,
                event_type="complex_node",
                split_mode="complex_one_node_one_unit",
                representative_node_id=node_id,
                selected_side_branch_ids=tuple(pair),
            )
        )
    return specs


def build_event_unit_specs(
    *,
    case_bundle,
    unit_context: T04UnitContext,
) -> list[T04EventUnitSpec]:
    representative_node = unit_context.representative_node
    source_kind = _node_source_kind(representative_node)
    source_kind_2 = _node_source_kind_2(representative_node)
    is_complex = source_kind == COMPLEX_JUNCTION_KIND or source_kind_2 == COMPLEX_JUNCTION_KIND

    if is_complex:
        candidate_node_ids: list[str] = []
        seen_node_ids: set[str] = set()
        node_lookup = {item.node_id: item for item in case_bundle.nodes}
        member_node_ids = list(unit_context.topology_skeleton.branch_result.member_node_ids)
        if not member_node_ids:
            member_node_ids = [node.node_id for node in unit_context.group_nodes]
        for node_id in member_node_ids:
            node = node_lookup.get(node_id)
            if node is None or not _is_complex_unit_member_node(node=node, mainnodeid=unit_context.mainnodeid):
                continue
            if node.node_id in seen_node_ids:
                continue
            seen_node_ids.add(node.node_id)
            candidate_node_ids.append(node.node_id)
        if representative_node.node_id not in seen_node_ids:
            candidate_node_ids.insert(0, representative_node.node_id)
        specs: list[T04EventUnitSpec] = []
        for node_id in candidate_node_ids:
            specs.extend(_complex_node_specs(unit_context=unit_context, node_id=node_id))
        return specs

    side_branches = _sorted_side_branches(unit_context)
    if len(side_branches) <= 1:
        return [
            T04EventUnitSpec(
                event_unit_id="event_unit_01",
                event_type="simple",
                split_mode="one_case_one_unit",
                representative_node_id=representative_node.node_id,
                selected_side_branch_ids=tuple(str(branch.branch_id) for branch in side_branches),
            )
        ]

    pairs: list[tuple[str, str]] = []
    for index, branch in enumerate(side_branches):
        next_branch = side_branches[(index + 1) % len(side_branches)]
        pair = tuple(sorted((str(branch.branch_id), str(next_branch.branch_id))))
        if pair in pairs:
            continue
        pairs.append(pair)

    return [
        T04EventUnitSpec(
            event_unit_id=f"event_unit_{index:02d}",
            event_type="adjacent_side_pair",
            split_mode="multi_divmerge_adjacent_pair",
            representative_node_id=representative_node.node_id,
            selected_side_branch_ids=pair,
        )
        for index, pair in enumerate(pairs, start=1)
    ]
