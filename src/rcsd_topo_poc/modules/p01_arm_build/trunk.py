from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from rcsd_topo_poc.modules.p01_arm_build.models import InitialArm, RoadRecord
from rcsd_topo_poc.modules.p01_arm_build.special_roads import is_advance_left_turn_road, is_advance_right_turn_road


@dataclass(frozen=True)
class TrunkBuildResult:
    trunk_road_ids: tuple[str, ...]
    trunk_status: str
    trunk_reason: str
    non_trunk_member_road_ids: tuple[str, ...]
    advance_left_turn_road_ids: tuple[str, ...]


def _adjacency(candidate_ids: set[str], roads: dict[str, RoadRecord]) -> dict[str, tuple[tuple[str, str], ...]]:
    by_node: dict[str, list[tuple[str, str]]] = {}
    for road_id in candidate_ids:
        road = roads.get(road_id)
        if road is None:
            continue
        by_node.setdefault(road.snodeid, []).append((road.enodeid, road_id))
        by_node.setdefault(road.enodeid, []).append((road.snodeid, road_id))
    return {node_id: tuple(sorted(items)) for node_id, items in by_node.items()}


def _shortest_path(
    *,
    start_nodes: set[str],
    end_nodes: set[str],
    adjacency: dict[str, tuple[tuple[str, str], ...]],
    blocked_road_id: str | None = None,
) -> tuple[str, ...] | None:
    queue: deque[tuple[str, tuple[str, ...]]] = deque((node_id, tuple()) for node_id in sorted(start_nodes))
    visited = set(start_nodes)
    while queue:
        node_id, path = queue.popleft()
        if node_id in end_nodes and path:
            return path
        for next_node, road_id in adjacency.get(node_id, tuple()):
            if road_id == blocked_road_id:
                continue
            if next_node in visited:
                continue
            visited.add(next_node)
            queue.append((next_node, path + (road_id,)))
    return None


def _road_nodes(road_ids: set[str], roads: dict[str, RoadRecord]) -> set[str]:
    node_ids: set[str] = set()
    for road_id in road_ids:
        road = roads.get(road_id)
        if road:
            node_ids.update((road.snodeid, road.enodeid))
    return node_ids


def _seed_nodes(seed_ids: set[str], roads: dict[str, RoadRecord]) -> set[str]:
    return _road_nodes(seed_ids, roads)


def build_trunk_for_arm(
    arm: InitialArm,
    roads: dict[str, RoadRecord],
    *,
    additional_blocked_road_ids: set[str] | None = None,
) -> TrunkBuildResult:
    member_ids = set(arm.member_road_ids)
    advance_left_ids = {road_id for road_id in member_ids if road_id in roads and is_advance_left_turn_road(roads[road_id])}
    extra_blocked_ids = set(additional_blocked_road_ids or set())
    blocked_ids = {
        road_id
        for road_id in member_ids
        if road_id in roads and (is_advance_left_turn_road(roads[road_id]) or is_advance_right_turn_road(roads[road_id]))
    } | extra_blocked_ids
    candidate_ids = {road_id for road_id in member_ids if road_id not in blocked_ids and road_id in roads}
    if not candidate_ids:
        return TrunkBuildResult(
            trunk_road_ids=tuple(),
            trunk_status="none",
            trunk_reason="no_non_special_member_roads",
            non_trunk_member_road_ids=tuple(sorted(member_ids)),
            advance_left_turn_road_ids=tuple(sorted(advance_left_ids)),
        )

    inbound_ids = (set(arm.inbound_member_road_ids) | set(arm.bidirectional_member_road_ids)) & candidate_ids
    outbound_ids = (set(arm.outbound_member_road_ids) | set(arm.bidirectional_member_road_ids)) & candidate_ids
    adjacency = _adjacency(candidate_ids, roads)

    cycle_candidates: list[tuple[str, ...]] = []
    seed_union = inbound_ids | outbound_ids
    for road_id in sorted(seed_union):
        road = roads.get(road_id)
        if road is None:
            continue
        path = _shortest_path(
            start_nodes={road.snodeid},
            end_nodes={road.enodeid},
            adjacency=adjacency,
            blocked_road_id=road_id,
        )
        if path is None:
            continue
        cycle = tuple(sorted(set(path) | {road_id}))
        if cycle and (set(cycle) & inbound_ids) and (set(cycle) & outbound_ids):
            cycle_candidates.append(cycle)

    if cycle_candidates:
        min_size = min(len(item) for item in cycle_candidates)
        shortest = sorted({item for item in cycle_candidates if len(item) == min_size})
        if len(shortest) == 1:
            trunk_ids = shortest[0]
            return TrunkBuildResult(
                trunk_road_ids=trunk_ids,
                trunk_status="complete_min_loop",
                trunk_reason="unique_minimum_loop_between_inbound_and_outbound",
                non_trunk_member_road_ids=tuple(sorted(member_ids - set(trunk_ids))),
                advance_left_turn_road_ids=tuple(sorted(advance_left_ids)),
            )
        trunk_ids = tuple(sorted(set().union(*(set(item) for item in shortest))))
        return TrunkBuildResult(
            trunk_road_ids=trunk_ids,
            trunk_status="ambiguous",
            trunk_reason="multiple_equal_minimum_loops",
            non_trunk_member_road_ids=tuple(sorted(member_ids - set(trunk_ids))),
            advance_left_turn_road_ids=tuple(sorted(advance_left_ids)),
        )

    if inbound_ids and outbound_ids:
        path = _shortest_path(
            start_nodes=_seed_nodes(inbound_ids, roads),
            end_nodes=_seed_nodes(outbound_ids, roads),
            adjacency=adjacency,
        )
        if path:
            trunk_ids = tuple(sorted(set(path)))
            return TrunkBuildResult(
                trunk_road_ids=trunk_ids,
                trunk_status="partial",
                trunk_reason="main_chain_found_without_complete_loop",
                non_trunk_member_road_ids=tuple(sorted(member_ids - set(trunk_ids))),
                advance_left_turn_road_ids=tuple(sorted(advance_left_ids)),
            )

    local_seed_ids = set(arm.seed_road_ids) & candidate_ids
    if local_seed_ids:
        return TrunkBuildResult(
            trunk_road_ids=tuple(sorted(local_seed_ids)),
            trunk_status="partial",
            trunk_reason="local_non_special_seed_trunk_without_complete_loop",
            non_trunk_member_road_ids=tuple(sorted(member_ids - local_seed_ids)),
            advance_left_turn_road_ids=tuple(sorted(advance_left_ids)),
        )

    if len(candidate_ids) == 1:
        trunk_ids = tuple(sorted(candidate_ids))
        return TrunkBuildResult(
            trunk_road_ids=trunk_ids,
            trunk_status="partial",
            trunk_reason="single_non_special_member_road",
            non_trunk_member_road_ids=tuple(sorted(member_ids - set(trunk_ids))),
            advance_left_turn_road_ids=tuple(sorted(advance_left_ids)),
        )

    return TrunkBuildResult(
        trunk_road_ids=tuple(),
        trunk_status="none",
        trunk_reason="no_inbound_outbound_main_chain",
        non_trunk_member_road_ids=tuple(sorted(member_ids)),
        advance_left_turn_road_ids=tuple(sorted(advance_left_ids)),
    )
