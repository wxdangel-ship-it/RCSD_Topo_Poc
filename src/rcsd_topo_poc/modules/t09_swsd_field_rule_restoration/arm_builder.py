from __future__ import annotations

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    SWSDSegmentInput,
    SWSDRoadInput,
    T09SwsdArm,
)


def build_swsd_arms(
    *,
    junction_id: str,
    member_node_ids: tuple[str, ...],
    roads: tuple[SWSDRoadInput, ...],
    segments: tuple[SWSDSegmentInput, ...] = tuple(),
) -> tuple[T09SwsdArm, ...]:
    member_set = set(member_node_ids)
    segment_by_road = _segment_index(segments, member_set)
    arms: list[T09SwsdArm] = []
    internal_roads = tuple(
        road.road_id for road in roads if road.snodeid in member_set and road.enodeid in member_set
    )

    for road in roads:
        snode_inside = road.snodeid in member_set
        enode_inside = road.enodeid in member_set
        if snode_inside == enode_inside:
            continue
        inbound, outbound = _road_roles_for_junction(road, snode_inside=snode_inside)
        segment_matches = segment_by_road.get(road.road_id, tuple())
        segment_ids = road.segment_ids or tuple(segment_id for segment_id, _ in segment_matches)
        terminal_node_id = road.enodeid if snode_inside else road.snodeid
        seed_tuple = (road.road_id,)
        risk_flags = tuple() if segment_ids else ("segment_membership_missing",)
        arms.append(
            T09SwsdArm(
                junction_id=junction_id,
                arm_id=f"{junction_id}:arm:{road.road_id}",
                member_node_ids=member_node_ids,
                internal_road_ids=internal_roads,
                seed_road_ids=seed_tuple,
                segment_ids=segment_ids,
                inbound_road_ids=seed_tuple if inbound else tuple(),
                outbound_road_ids=seed_tuple if outbound else tuple(),
                bidirectional_road_ids=seed_tuple if inbound and outbound else tuple(),
                approach_road_ids=seed_tuple if inbound else tuple(),
                exit_road_ids=seed_tuple if outbound else tuple(),
                trunk_road_ids=seed_tuple,
                advance_left_road_ids=seed_tuple if road.formway & 256 else tuple(),
                terminal_node_id=terminal_node_id,
                terminal_kind=_terminal_kind(segment_ids, segment_matches),
                risk_flags=risk_flags,
            )
        )
    return tuple(arms)


def _segment_index(
    segments: tuple[SWSDSegmentInput, ...],
    member_set: set[str],
) -> dict[str, tuple[tuple[str, str], ...]]:
    indexed: dict[str, list[tuple[str, str]]] = {}
    for segment in segments:
        membership_kind = _segment_membership_kind(segment, member_set)
        for road_id in segment.road_ids:
            indexed.setdefault(road_id, []).append((segment.segment_id, membership_kind))
    return {road_id: tuple(segment_ids) for road_id, segment_ids in indexed.items()}


def _segment_membership_kind(segment: SWSDSegmentInput, member_set: set[str]) -> str:
    if member_set.intersection(segment.junc_nodes):
        return "segment_junc_node"
    if member_set.intersection(segment.pair_nodes):
        return "segment_pair_node"
    return "segment_road_member"


def _terminal_kind(
    segment_ids: tuple[str, ...],
    segment_matches: tuple[tuple[str, str], ...],
) -> str:
    if not segment_ids:
        return "local_topology_fallback"
    kinds = {kind for _, kind in segment_matches}
    if "segment_junc_node" in kinds:
        return "segment_junc_node"
    if "segment_pair_node" in kinds:
        return "segment_pair_node"
    if segment_matches:
        return "segment_road_member"
    return "segment_reference"


def _road_roles_for_junction(road: SWSDRoadInput, *, snode_inside: bool) -> tuple[bool, bool]:
    if road.direction in {0, 1}:
        return True, True
    if road.direction == 2:
        return (not snode_inside, snode_inside)
    if road.direction == 3:
        return (snode_inside, not snode_inside)
    return False, False
