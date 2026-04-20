from __future__ import annotations

from rcsd_topo_poc.modules.t02_junction_anchor.shared import normalize_id
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_geometry_utils import (
    COMPLEX_JUNCTION_KIND,
    _node_source_kind,
    _node_source_kind_2,
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
        return [
            T04EventUnitSpec(
                event_unit_id=f"node_{node_id}",
                event_type="complex_node",
                split_mode="complex_one_node_one_unit",
                representative_node_id=node_id,
                selected_side_branch_ids=(),
            )
            for node_id in candidate_node_ids
        ]

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
