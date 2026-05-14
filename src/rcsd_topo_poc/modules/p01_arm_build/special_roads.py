from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from rcsd_topo_poc.modules.p01_arm_build.io import normalise_id
from rcsd_topo_poc.modules.p01_arm_build.models import AdvanceRightTurnRelation, InitialArm, NodeRecord, RoadRecord


ADVANCE_RIGHT_TURN_MASK = 1 << 7
ADVANCE_LEFT_TURN_MASK = 1 << 8


@dataclass(frozen=True)
class SpecialRoadFlagIndex:
    advance_left_turn_road_ids: tuple[str, ...]
    advance_right_turn_road_ids: tuple[str, ...]
    formway_missing_road_ids: tuple[str, ...]
    formway_unparseable_road_ids: tuple[str, ...]
    issue_flags: tuple[str, ...]


def parse_formway_int(value: Any) -> tuple[int | None, str | None]:
    text = normalise_id(value)
    if not text:
        return None, "missing"
    try:
        if "." in text:
            number = float(text)
            if number.is_integer():
                return int(number), None
            return None, "unparseable"
        return int(text, 0), None
    except (TypeError, ValueError):
        return None, "unparseable"


def formway_int_for_road(road: RoadRecord) -> int | None:
    value, error = parse_formway_int(road.formway)
    if error:
        return None
    return value


def is_advance_right_turn_road(road: RoadRecord) -> bool:
    value = formway_int_for_road(road)
    return value is not None and (value & ADVANCE_RIGHT_TURN_MASK) != 0


def is_advance_left_turn_road(road: RoadRecord) -> bool:
    value = formway_int_for_road(road)
    return value is not None and (value & ADVANCE_LEFT_TURN_MASK) != 0


def build_special_road_flag_index(
    roads: dict[str, RoadRecord],
    road_ids: set[str],
) -> SpecialRoadFlagIndex:
    advance_left: list[str] = []
    advance_right: list[str] = []
    missing: list[str] = []
    unparseable: list[str] = []
    for road_id in sorted(road_ids):
        road = roads.get(road_id)
        if road is None:
            continue
        value, error = parse_formway_int(road.formway)
        if error == "missing":
            missing.append(road_id)
            continue
        if error == "unparseable":
            unparseable.append(road_id)
            continue
        if value is not None and (value & ADVANCE_LEFT_TURN_MASK) != 0:
            advance_left.append(road_id)
        if value is not None and (value & ADVANCE_RIGHT_TURN_MASK) != 0:
            advance_right.append(road_id)

    flags: list[str] = []
    if missing:
        flags.append("formway_missing")
    if unparseable:
        flags.append("formway_unparseable")
    return SpecialRoadFlagIndex(
        advance_left_turn_road_ids=tuple(advance_left),
        advance_right_turn_road_ids=tuple(advance_right),
        formway_missing_road_ids=tuple(missing),
        formway_unparseable_road_ids=tuple(unparseable),
        issue_flags=tuple(flags),
    )


_ROAD_IDS_BY_NODE_CACHE: dict[tuple[int, int, str], dict[str, tuple[str, ...]]] = {}


def _roads_cache_key(roads: dict[str, RoadRecord]) -> tuple[int, int, str]:
    return (id(roads), len(roads), next(iter(roads), ""))


def _road_ids_by_node(roads: dict[str, RoadRecord]) -> dict[str, tuple[str, ...]]:
    cache_key = _roads_cache_key(roads)
    cached = _ROAD_IDS_BY_NODE_CACHE.get(cache_key)
    if cached is not None:
        return cached
    by_node: dict[str, list[str]] = {}
    for road in roads.values():
        by_node.setdefault(road.snodeid, []).append(road.road_id)
        by_node.setdefault(road.enodeid, []).append(road.road_id)
    indexed = {node_id: tuple(sorted(road_ids)) for node_id, road_ids in by_node.items()}
    _ROAD_IDS_BY_NODE_CACHE[cache_key] = indexed
    return indexed


def road_ids_touching_nodes(roads: dict[str, RoadRecord], node_ids: set[str]) -> set[str]:
    by_node = _road_ids_by_node(roads)
    return {road_id for node_id in node_ids for road_id in by_node.get(node_id, tuple())}


def _road_other_node(road: RoadRecord, node_id: str) -> str | None:
    if road.snodeid == node_id:
        return road.enodeid
    if road.enodeid == node_id:
        return road.snodeid
    return None


def _outside_node_for_current(road: RoadRecord, current_member_node_ids: set[str]) -> str | None:
    snode_inside = road.snodeid in current_member_node_ids
    enode_inside = road.enodeid in current_member_node_ids
    if snode_inside and not enode_inside:
        return road.enodeid
    if enode_inside and not snode_inside:
        return road.snodeid
    return None


def _current_touch_nodes(road: RoadRecord, current_member_node_ids: set[str]) -> set[str]:
    return {node_id for node_id in (road.snodeid, road.enodeid) if node_id in current_member_node_ids}


def _incident_by_node(roads: dict[str, RoadRecord]) -> dict[str, tuple[str, ...]]:
    by_node: dict[str, list[str]] = {}
    for road in roads.values():
        by_node.setdefault(road.snodeid, []).append(road.road_id)
        by_node.setdefault(road.enodeid, []).append(road.road_id)
    return {node_id: tuple(sorted(road_ids)) for node_id, road_ids in by_node.items()}


def _source_initial_arm_id(
    *,
    road: RoadRecord,
    arms: tuple[InitialArm, ...],
    roads: dict[str, RoadRecord],
    current_member_node_ids: set[str],
) -> str | None:
    touch_nodes = _current_touch_nodes(road, current_member_node_ids)
    matches: list[str] = []
    fallback: list[str] = []
    for arm in arms:
        inbound_ids = set(arm.inbound_member_road_ids) | set(arm.bidirectional_member_road_ids)
        if inbound_ids:
            fallback.append(arm.initial_arm_id)
        for inbound_id in inbound_ids:
            inbound_road = roads.get(inbound_id)
            if inbound_road and touch_nodes & _current_touch_nodes(inbound_road, current_member_node_ids):
                matches.append(arm.initial_arm_id)
                break
    unique = sorted(set(matches))
    if len(unique) == 1:
        return unique[0]
    fallback_unique = sorted(set(fallback))
    if not unique and len(fallback_unique) == 1:
        return fallback_unique[0]
    return None


def _target_initial_arm(
    *,
    start_node_id: str,
    start_road_id: str,
    arms: tuple[InitialArm, ...],
    roads: dict[str, RoadRecord],
    nodes: dict[str, NodeRecord],
    current_member_node_ids: set[str],
) -> tuple[str | None, tuple[str, ...], tuple[str, ...], str, str, tuple[str, ...]]:
    incident = _incident_by_node(roads)
    outbound_to_arm: dict[str, str] = {}
    member_to_arm: dict[str, str] = {}
    for arm in arms:
        for road_id in set(arm.outbound_member_road_ids) | set(arm.bidirectional_member_road_ids):
            outbound_to_arm[road_id] = arm.initial_arm_id
        for road_id in arm.member_road_ids:
            member_to_arm[road_id] = arm.initial_arm_id

    queue: deque[tuple[str, tuple[str, ...], tuple[str, ...]]] = deque([(start_node_id, (start_road_id,), (start_node_id,))])
    visited: set[tuple[str, str]] = set()
    partial: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []
    max_steps = max(len(roads) + 2, 4)
    best_depth: int | None = None
    resolved: list[tuple[str, tuple[str, ...], tuple[str, ...]]] = []

    while queue:
        node_id, trace_roads, trace_nodes = queue.popleft()
        if len(trace_roads) > max_steps:
            return None, trace_roads, trace_nodes, "loop", "advance_right_turn_step_limit_reached", ("advance_right_turn_loop",)
        if node_id in current_member_node_ids and node_id != start_node_id:
            return None, trace_roads, trace_nodes, "loop", "advance_right_turn_returned_to_current_junction", ("advance_right_turn_loop",)
        if node_id not in nodes:
            return None, trace_roads, trace_nodes, "patch_boundary", "advance_right_turn_node_missing", ("advance_right_turn_patch_boundary",)
        depth = len(trace_roads)
        if best_depth is not None and depth > best_depth:
            continue
        for road_id in incident.get(node_id, tuple()):
            if road_id == start_road_id or road_id in trace_roads:
                continue
            road = roads[road_id]
            if is_advance_right_turn_road(road):
                other = _road_other_node(road, node_id)
                if other is None:
                    continue
                key = (other, road_id)
                if key in visited:
                    continue
                visited.add(key)
                queue.append((other, trace_roads + (road_id,), trace_nodes + (other,)))
                continue
            if road_id in outbound_to_arm:
                best_depth = depth
                resolved.append((outbound_to_arm[road_id], trace_roads + (road_id,), trace_nodes))
                continue
            if road_id in member_to_arm:
                partial.append((member_to_arm[road_id], trace_roads + (road_id,), trace_nodes))
            other = _road_other_node(road, node_id)
            if other is None:
                continue
            key = (other, road_id)
            if key in visited:
                continue
            visited.add(key)
            queue.append((other, trace_roads + (road_id,), trace_nodes + (other,)))

    unique_targets = {item[0] for item in resolved}
    if len(unique_targets) == 1:
        target_id = sorted(unique_targets)[0]
        best = min((item for item in resolved if item[0] == target_id), key=lambda item: len(item[1]))
        return target_id, best[1], best[2], "resolved", "advance_right_turn_target_arm_resolved", tuple()
    if len(unique_targets) > 1:
        best = min(resolved, key=lambda item: len(item[1]))
        return None, best[1], best[2], "ambiguous", "advance_right_turn_multiple_target_arms", ("advance_right_turn_ambiguous",)

    partial_targets = {item[0] for item in partial}
    if len(partial_targets) == 1:
        target_id = sorted(partial_targets)[0]
        best = min((item for item in partial if item[0] == target_id), key=lambda item: len(item[1]))
        return target_id, best[1], best[2], "partial", "advance_right_turn_reached_target_member_only", tuple()
    if len(partial_targets) > 1:
        best = min(partial, key=lambda item: len(item[1]))
        return None, best[1], best[2], "ambiguous", "advance_right_turn_multiple_partial_targets", ("advance_right_turn_ambiguous",)

    return None, (start_road_id,), (start_node_id,), "target_arm_not_found", "advance_right_turn_target_arm_not_found", (
        "advance_right_turn_target_arm_not_found",
    )


def _make_relation(
    *,
    relation_id: str,
    dataset: str,
    junction_id: str,
    advance_right_turn_road_ids: tuple[str, ...],
    source_initial_id: str | None,
    target_initial_id: str | None,
    trace_roads: tuple[str, ...],
    trace_nodes: tuple[str, ...],
    status: str,
    reason: str,
    risk_flags: tuple[str, ...],
    arms_by_id: dict[str, InitialArm],
    initial_to_final_arm_id: dict[str, str],
) -> AdvanceRightTurnRelation:
    source_arm = arms_by_id.get(source_initial_id or "")
    target_arm = arms_by_id.get(target_initial_id or "")
    from_arm_id = initial_to_final_arm_id.get(source_initial_id or "")
    to_arm_id = initial_to_final_arm_id.get(target_initial_id or "")
    if source_initial_id is None:
        status = "ambiguous" if status == "resolved" else status
        reason = "advance_right_turn_source_arm_not_unique"
        risk_flags = tuple(sorted(set(risk_flags) | {"advance_right_turn_ambiguous"}))
    return AdvanceRightTurnRelation(
        relation_id=relation_id,
        dataset=dataset,
        current_junction_id=junction_id,
        from_arm_id=from_arm_id,
        from_inbound_road_ids=source_arm.inbound_member_road_ids if source_arm else tuple(),
        advance_right_turn_road_ids=advance_right_turn_road_ids,
        to_arm_id=to_arm_id,
        to_outbound_road_ids=tuple(sorted((target_arm.outbound_member_road_ids + target_arm.bidirectional_member_road_ids) if target_arm else tuple())),
        trace_road_ids=trace_roads,
        trace_node_ids=trace_nodes,
        trace_status=status,
        trace_reason=reason,
        confidence="high" if status == "resolved" else ("medium" if status == "partial" else "low"),
        risk_flags=tuple(sorted(set(risk_flags))),
    )


def _advance_right_turn_ids_in_trace(trace_roads: tuple[str, ...], roads: dict[str, RoadRecord]) -> tuple[str, ...]:
    return tuple(sorted({road_id for road_id in trace_roads if road_id in roads and is_advance_right_turn_road(roads[road_id])}))


def build_advance_right_turn_relations(
    *,
    dataset: str,
    junction_id: str,
    advance_right_turn_road_ids: tuple[str, ...],
    current_member_node_ids: set[str],
    roads: dict[str, RoadRecord],
    nodes: dict[str, NodeRecord],
    initial_arms: tuple[InitialArm, ...],
    initial_to_final_arm_id: dict[str, str],
) -> tuple[tuple[AdvanceRightTurnRelation, ...], tuple[dict[str, Any], ...]]:
    relations: list[AdvanceRightTurnRelation] = []
    issues: list[dict[str, Any]] = []
    arms_by_id = {arm.initial_arm_id: arm for arm in initial_arms}
    incident = _incident_by_node(roads)
    relation_index = 1
    covered_advance_right_road_ids: set[str] = set()

    for arm in initial_arms:
        source_seed_ids = tuple(
            sorted(
                road_id
                for road_id in set(arm.inbound_member_road_ids) | set(arm.bidirectional_member_road_ids)
                if road_id in roads and not is_advance_left_turn_road(roads[road_id]) and not is_advance_right_turn_road(roads[road_id])
            )
        )
        for seed_id in source_seed_ids:
            seed = roads.get(seed_id)
            if seed is None:
                continue
            outside_node_id = _outside_node_for_current(seed, current_member_node_ids)
            if outside_node_id is None:
                continue
            for road_id in incident.get(outside_node_id, tuple()):
                if road_id == seed_id or road_id not in advance_right_turn_road_ids:
                    continue
                road = roads.get(road_id)
                if road is None or not is_advance_right_turn_road(road):
                    continue
                if road_id in covered_advance_right_road_ids:
                    continue
                next_node_id = _road_other_node(road, outside_node_id)
                if next_node_id is None:
                    target_initial_id = None
                    trace_roads = (road_id,)
                    trace_nodes = (outside_node_id,)
                    status = "target_arm_not_found"
                    reason = "advance_right_turn_adjacent_endpoint_missing"
                    risk_flags = ("advance_right_turn_target_arm_not_found",)
                else:
                    target_initial_id, trace_roads, trace_nodes, status, reason, risk_flags = _target_initial_arm(
                        start_node_id=next_node_id,
                        start_road_id=road_id,
                        arms=initial_arms,
                        roads=roads,
                        nodes=nodes,
                        current_member_node_ids=current_member_node_ids,
                    )
                    trace_nodes = (outside_node_id,) + tuple(node_id for node_id in trace_nodes if node_id != outside_node_id)
                relation_advance_right_ids = _advance_right_turn_ids_in_trace(trace_roads, roads)
                if not relation_advance_right_ids:
                    relation_advance_right_ids = (road_id,)
                relation_id = f"{dataset.lower()}_{junction_id}_adv_r_{relation_index:04d}"
                relation_index += 1
                relation = _make_relation(
                    relation_id=relation_id,
                    dataset=dataset,
                    junction_id=junction_id,
                    advance_right_turn_road_ids=relation_advance_right_ids,
                    source_initial_id=arm.initial_arm_id,
                    target_initial_id=target_initial_id,
                    trace_roads=trace_roads,
                    trace_nodes=trace_nodes,
                    status=status,
                    reason=reason,
                    risk_flags=risk_flags,
                    arms_by_id=arms_by_id,
                    initial_to_final_arm_id=initial_to_final_arm_id,
                )
                relations.append(relation)
                covered_advance_right_road_ids.update(relation.advance_right_turn_road_ids)
                for flag in relation.risk_flags:
                    issues.append(
                        {
                            "issue_type": flag,
                            "relation_id": relation_id,
                            "road_id": ",".join(relation.advance_right_turn_road_ids),
                            "trace_status": relation.trace_status,
                            "trace_reason": relation.trace_reason,
                        }
                    )

    for road_id in advance_right_turn_road_ids:
        if road_id in covered_advance_right_road_ids:
            continue
        road = roads.get(road_id)
        if road is None:
            continue
        relation_id = f"{dataset.lower()}_{junction_id}_adv_r_{relation_index:04d}"
        relation_index += 1
        source_initial_id = _source_initial_arm_id(
            road=road,
            arms=initial_arms,
            roads=roads,
            current_member_node_ids=current_member_node_ids,
        )
        outside_node_id = _outside_node_for_current(road, current_member_node_ids)
        if outside_node_id is None:
            target_initial_id = None
            trace_roads = (road_id,)
            trace_nodes: tuple[str, ...] = tuple()
            status = "target_arm_not_found"
            reason = "advance_right_turn_does_not_leave_current_junction"
            risk_flags = ("advance_right_turn_target_arm_not_found",)
        else:
            target_initial_id, trace_roads, trace_nodes, status, reason, risk_flags = _target_initial_arm(
                start_node_id=outside_node_id,
                start_road_id=road_id,
                arms=initial_arms,
                roads=roads,
                nodes=nodes,
                current_member_node_ids=current_member_node_ids,
            )
        relation_advance_right_ids = _advance_right_turn_ids_in_trace(trace_roads, roads)
        if not relation_advance_right_ids:
            relation_advance_right_ids = (road_id,)
        from_arm_id = initial_to_final_arm_id.get(source_initial_id or "")
        relation = _make_relation(
            relation_id=relation_id,
            dataset=dataset,
            junction_id=junction_id,
            advance_right_turn_road_ids=relation_advance_right_ids,
            source_initial_id=source_initial_id if from_arm_id else None,
            target_initial_id=target_initial_id,
            trace_roads=trace_roads,
            trace_nodes=trace_nodes,
            status=status,
            reason=reason,
            risk_flags=risk_flags,
            arms_by_id=arms_by_id,
            initial_to_final_arm_id=initial_to_final_arm_id,
        )
        relations.append(relation)
        covered_advance_right_road_ids.update(relation.advance_right_turn_road_ids)
        for flag in relation.risk_flags:
            issues.append(
                {
                    "issue_type": flag,
                    "relation_id": relation_id,
                    "road_id": ",".join(relation.advance_right_turn_road_ids),
                    "trace_status": status,
                    "trace_reason": reason,
                }
            )
    return tuple(relations), tuple(issues)
