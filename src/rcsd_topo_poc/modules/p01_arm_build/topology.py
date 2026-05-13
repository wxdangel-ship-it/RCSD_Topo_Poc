from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import replace
from typing import Any

from rcsd_topo_poc.modules.p01_arm_build.corridor import build_arm_corridor_evidence
from rcsd_topo_poc.modules.p01_arm_build.io import normalise_id
from rcsd_topo_poc.modules.p01_arm_build.final_arm_validation import build_final_arm_validation
from rcsd_topo_poc.modules.p01_arm_build.models import (
    ArmTrace,
    DatasetBuildResult,
    FinalArm,
    InitialArm,
    IssueReport,
    JunctionContext,
    LoadedDataset,
    LocalArmCandidate,
    NodeRecord,
    RawRoadNextRoad,
    RoadRecord,
    ThroughDecisionAudit,
)
from rcsd_topo_poc.modules.p01_arm_build.movement import build_movement_outputs
from rcsd_topo_poc.modules.p01_arm_build.special_roads import (
    build_advance_right_turn_relations,
    build_special_road_flag_index,
    is_advance_left_turn_road,
    is_advance_right_turn_road,
    road_ids_touching_nodes,
)
from rcsd_topo_poc.modules.p01_arm_build.trunk import build_trunk_for_arm


CONTINUE_STATUSES = {"simple_through", "t_mainline_through"}
RISK_STOP_TYPES = {"ambiguous_boundary", "patch_boundary", "loop_to_current_junction", "unresolved"}
LOCAL_CANDIDATE_SAME_ROLE_BUNDLE_TOLERANCE_DEG = 15.0
LOCAL_CANDIDATE_SAME_DIRECTION_PAIR_TOLERANCE_DEG = 18.0
LOCAL_CANDIDATE_OUTBOUND_TO_INBOUND_MAX_GAP_DEG = 80.0
LOCAL_CANDIDATE_STUB_ANGLE_TOLERANCE_DEG = 25.0
LOCAL_CANDIDATE_STUB_MAX_HOPS = 1
THROUGH_MAINLINE_MAX_ANGLE_DEG = 25.0
THROUGH_MAINLINE_MIN_MARGIN_DEG = 12.0
THROUGH_DEAD_END_TIE_BREAK_MAX_EXTRA_DEG = 5.0
NON_RISK_TRACE_FLAGS = {"right_turn_excluded"}


def valid_mainnodeid(value: str | None) -> str | None:
    text = normalise_id(value)
    if not text or text.lower() in {"0", "0.0", "none", "null", "nan"}:
        return None
    return text


def semantic_group_id(node: NodeRecord | None, fallback_node_id: str) -> str:
    if node is None:
        return normalise_id(fallback_node_id)
    return valid_mainnodeid(node.mainnodeid) or node.node_id


def build_node_groups(nodes: dict[str, NodeRecord]) -> tuple[dict[str, tuple[str, ...]], dict[str, str]]:
    groups: dict[str, list[str]] = defaultdict(list)
    node_to_group: dict[str, str] = {}
    for node_id, node in nodes.items():
        group_id = semantic_group_id(node, node_id)
        groups[group_id].append(node_id)
        node_to_group[node_id] = group_id
    return {group_id: tuple(sorted(members)) for group_id, members in groups.items()}, node_to_group


def resolve_junction_members(
    nodes: dict[str, NodeRecord],
    *,
    junction_id: str,
    dataset: str | None = None,
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    groups, node_to_group = build_node_groups(nodes)
    target = normalise_id(junction_id)
    issues: list[str] = []
    candidate_ids = [target]
    if dataset == "RCSD" and target.startswith("R") and len(target) > 1:
        candidate_ids.append(target[1:])
    if dataset == "FRCSD" and target.startswith("F") and len(target) > 1:
        candidate_ids.append(target[1:])
    for candidate_id in dict.fromkeys(candidate_ids):
        if candidate_id in groups:
            return candidate_id, groups[candidate_id], tuple(issues)
        if candidate_id in nodes:
            group_id = node_to_group[candidate_id]
            return group_id, groups[group_id], tuple(issues)
    issues.append("junction_member_nodes_not_found")
    return target, tuple(), tuple(issues)


def road_flow_flags_for_group(road: RoadRecord, member_node_ids: set[str]) -> tuple[bool, bool]:
    touches_snode = road.snodeid in member_node_ids
    touches_enode = road.enodeid in member_node_ids
    if not touches_snode and not touches_enode:
        return False, False
    if road.direction in {0, 1}:
        return True, True
    if touches_snode and touches_enode:
        return True, True
    if road.direction == 2:
        return touches_enode, touches_snode
    if road.direction == 3:
        return touches_snode, touches_enode
    return True, True


def seed_role_for_road(road: RoadRecord, member_node_ids: set[str]) -> str | None:
    inbound, outbound = road_flow_flags_for_group(road, member_node_ids)
    if inbound and outbound:
        return "bidirectional"
    if inbound:
        return "inbound"
    if outbound:
        return "outbound"
    return None


def _outside_node_for_seed(road: RoadRecord, member_node_ids: set[str]) -> str | None:
    snode_inside = road.snodeid in member_node_ids
    enode_inside = road.enodeid in member_node_ids
    if snode_inside and not enode_inside:
        return road.enodeid
    if enode_inside and not snode_inside:
        return road.snodeid
    return None


def _is_right_turn_road(road: RoadRecord, right_turn_formway_values: set[str]) -> bool:
    if not right_turn_formway_values or road.formway is None:
        return False
    if is_advance_right_turn_road(road):
        return False
    return normalise_id(road.formway) in right_turn_formway_values


def _advance_right_turn_enters_current_junction(road: RoadRecord, member_node_ids: set[str]) -> bool:
    role = seed_role_for_road(road, member_node_ids)
    return role in {"inbound", "bidirectional"}


def _road_endpoint_groups(road: RoadRecord, nodes: dict[str, NodeRecord]) -> tuple[str, str]:
    return semantic_group_id(nodes.get(road.snodeid), road.snodeid), semantic_group_id(nodes.get(road.enodeid), road.enodeid)


def _incident_active_roads(
    *,
    group_id: str,
    roads: dict[str, RoadRecord],
    nodes: dict[str, NodeRecord],
    excluded_road_ids: set[str],
    current_internal_road_ids: set[str],
    right_turn_formway_values: set[str] | None = None,
) -> tuple[str, ...]:
    incident: list[str] = []
    for road_id, road in roads.items():
        if road_id in excluded_road_ids or road_id in current_internal_road_ids:
            continue
        if is_advance_right_turn_road(road):
            continue
        if right_turn_formway_values and _is_right_turn_road(road, right_turn_formway_values):
            continue
        start_group, end_group = _road_endpoint_groups(road, nodes)
        if start_group == end_group:
            continue
        if group_id in {start_group, end_group}:
            incident.append(road_id)
    return tuple(sorted(incident))


def _other_group_for_road(road: RoadRecord, group_id: str, nodes: dict[str, NodeRecord]) -> str | None:
    start_group, end_group = _road_endpoint_groups(road, nodes)
    if start_group == group_id and end_group != group_id:
        return end_group
    if end_group == group_id and start_group != group_id:
        return start_group
    return None


def _entry_node_for_road_group(road: RoadRecord, group_id: str, nodes: dict[str, NodeRecord]) -> str | None:
    if semantic_group_id(nodes.get(road.snodeid), road.snodeid) == group_id:
        return road.snodeid
    if semantic_group_id(nodes.get(road.enodeid), road.enodeid) == group_id:
        return road.enodeid
    return None


def _entry_node_degree(
    *,
    group_id: str,
    previous_road_id: str,
    incident_ids: tuple[str, ...],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
) -> int:
    previous_road = roads.get(previous_road_id)
    if previous_road is None:
        return len(incident_ids)
    entry_node_id = _entry_node_for_road_group(previous_road, group_id, nodes)
    if entry_node_id is None:
        return len(incident_ids)
    return sum(1 for road_id in incident_ids if roads[road_id].snodeid == entry_node_id or roads[road_id].enodeid == entry_node_id)


def _entry_node_has_three_degree(
    *,
    group_id: str,
    previous_road_id: str,
    incident_ids: tuple[str, ...],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
) -> bool:
    return _entry_node_degree(
        group_id=group_id,
        previous_road_id=previous_road_id,
        incident_ids=incident_ids,
        nodes=nodes,
        roads=roads,
    ) >= 3


def _node_ids_for_group(group_id: str, groups: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    return groups.get(group_id, (group_id,))


def _node_xy(nodes: dict[str, NodeRecord], node_id: str) -> tuple[float, float] | None:
    node = nodes.get(node_id)
    if node is None or node.geometry is None or node.geometry.is_empty:
        return None
    center = node.geometry.centroid
    return float(center.x), float(center.y)


def _angle_from_xy(start: tuple[float, float], end: tuple[float, float]) -> float | None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    return math.degrees(math.atan2(dy, dx)) % 360.0


def _angular_distance(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _mean_angle(angles: list[float]) -> float:
    if not angles:
        return 0.0
    x = sum(math.cos(math.radians(angle)) for angle in angles)
    y = sum(math.sin(math.radians(angle)) for angle in angles)
    return math.degrees(math.atan2(y, x)) % 360.0


def _angular_spread(angles: list[float], mean_angle: float) -> float:
    if not angles:
        return 0.0
    return max(_angular_distance(angle, mean_angle) for angle in angles)


def _seed_trend_angle(
    road: RoadRecord,
    member_node_ids: set[str],
    nodes: dict[str, NodeRecord],
) -> tuple[float, tuple[str, str]] | None:
    snode_inside = road.snodeid in member_node_ids
    enode_inside = road.enodeid in member_node_ids
    if snode_inside and not enode_inside:
        inside_node_id, outside_node_id = road.snodeid, road.enodeid
    elif enode_inside and not snode_inside:
        inside_node_id, outside_node_id = road.enodeid, road.snodeid
    else:
        return None
    inside_xy = _node_xy(nodes, inside_node_id)
    outside_xy = _node_xy(nodes, outside_node_id)
    if inside_xy is None or outside_xy is None:
        return None
    angle = _angle_from_xy(inside_xy, outside_xy)
    if angle is None:
        return None
    return angle, (inside_node_id, outside_node_id)


def _road_trend_angle_from_group(
    road: RoadRecord,
    from_group_id: str,
    nodes: dict[str, NodeRecord],
) -> tuple[float, tuple[str, str]] | None:
    start_group, end_group = _road_endpoint_groups(road, nodes)
    if start_group == from_group_id and end_group != from_group_id:
        from_node_id, to_node_id = road.snodeid, road.enodeid
    elif end_group == from_group_id and start_group != from_group_id:
        from_node_id, to_node_id = road.enodeid, road.snodeid
    else:
        return None
    from_xy = _node_xy(nodes, from_node_id)
    to_xy = _node_xy(nodes, to_node_id)
    if from_xy is None or to_xy is None:
        return None
    angle = _angle_from_xy(from_xy, to_xy)
    if angle is None:
        return None
    return angle, (from_node_id, to_node_id)


def _road_trend_angle_to_group(
    road: RoadRecord,
    to_group_id: str,
    nodes: dict[str, NodeRecord],
) -> tuple[float, tuple[str, str]] | None:
    start_group, end_group = _road_endpoint_groups(road, nodes)
    if start_group == to_group_id and end_group != to_group_id:
        from_node_id, to_node_id = road.enodeid, road.snodeid
    elif end_group == to_group_id and start_group != to_group_id:
        from_node_id, to_node_id = road.snodeid, road.enodeid
    else:
        return None
    from_xy = _node_xy(nodes, from_node_id)
    to_xy = _node_xy(nodes, to_node_id)
    if from_xy is None or to_xy is None:
        return None
    angle = _angle_from_xy(from_xy, to_xy)
    if angle is None:
        return None
    return angle, (from_node_id, to_node_id)


def _local_stub_for_seed(
    *,
    seed_road: RoadRecord,
    base_angle: float,
    current_group_id: str,
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
    right_turn_formway_values: set[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    road_ids = [seed_road.road_id]
    node_ids = {seed_road.snodeid, seed_road.enodeid}
    group_id = _other_group_for_road(seed_road, current_group_id, nodes)
    previous_road_id = seed_road.road_id
    if group_id is None:
        return tuple(road_ids), tuple(sorted(node_ids))

    for _ in range(LOCAL_CANDIDATE_STUB_MAX_HOPS):
        incident_ids = _incident_active_roads(
            group_id=group_id,
            roads=roads,
            nodes=nodes,
            excluded_road_ids=excluded_road_ids,
            current_internal_road_ids=internal_road_ids,
            right_turn_formway_values=right_turn_formway_values,
        )
        next_candidates = [road_id for road_id in incident_ids if road_id != previous_road_id]
        if len(incident_ids) != 2 or len(next_candidates) != 1:
            break
        next_road = roads[next_candidates[0]]
        next_trend = _road_trend_angle_from_group(next_road, group_id, nodes)
        if next_trend is None:
            break
        next_angle, (from_node_id, to_node_id) = next_trend
        if _angular_distance(base_angle, next_angle) > LOCAL_CANDIDATE_STUB_ANGLE_TOLERANCE_DEG:
            break
        road_ids.append(next_road.road_id)
        node_ids.update((from_node_id, to_node_id))
        next_group_id = _other_group_for_road(next_road, group_id, nodes)
        if next_group_id is None or next_group_id == current_group_id:
            break
        previous_road_id = next_road.road_id
        group_id = next_group_id

    return tuple(road_ids), tuple(sorted(node_ids))


def _kind_values_for_group(group_id: str, groups: dict[str, tuple[str, ...]], nodes: dict[str, NodeRecord]) -> tuple[str, ...]:
    kinds = {
        normalise_id(nodes[node_id].kind)
        for node_id in _node_ids_for_group(group_id, groups)
        if node_id in nodes and normalise_id(nodes[node_id].kind)
    }
    return tuple(sorted(kinds))


def _kind_category(kind_values: tuple[str, ...]) -> str:
    if "2048" in kind_values:
        return "kind_2048"
    if "4" in kind_values:
        return "kind_4"
    return "kind_continue"


def _continuation_records(
    *,
    group_id: str,
    current_group_id: str,
    previous_road_id: str,
    incident_ids: tuple[str, ...],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
) -> tuple[list[dict[str, Any]], tuple[str, ...]]:
    incoming_trend = _road_trend_angle_to_group(roads[previous_road_id], group_id, nodes)
    incoming_angle = incoming_trend[0] if incoming_trend else None
    loop_road_ids: list[str] = []
    records: list[dict[str, Any]] = []
    for road_id in incident_ids:
        if road_id == previous_road_id:
            continue
        road = roads[road_id]
        next_group_id = _other_group_for_road(road, group_id, nodes)
        if next_group_id is None:
            continue
        if next_group_id == current_group_id:
            loop_road_ids.append(road_id)
            continue
        outgoing_trend = _road_trend_angle_from_group(road, group_id, nodes)
        outgoing_angle = outgoing_trend[0] if outgoing_trend else None
        angle_delta = (
            _angular_distance(incoming_angle, outgoing_angle)
            if incoming_angle is not None and outgoing_angle is not None
            else None
        )
        records.append(
            {
                "road_id": road_id,
                "next_group_id": next_group_id,
                "incoming_angle": incoming_angle,
                "outgoing_angle": outgoing_angle,
                "angle_delta": angle_delta,
            }
        )
    records.sort(key=lambda item: (float(item["angle_delta"]) if item["angle_delta"] is not None else 999.0, str(item["road_id"])))
    return records, tuple(sorted(loop_road_ids))


def _candidate_enters_one_hop_dead_end(
    record: dict[str, Any],
    *,
    current_group_id: str,
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
) -> bool:
    next_group_id = str(record["next_group_id"])
    road_id = str(record["road_id"])
    for candidate_id, candidate_road in roads.items():
        if candidate_id == road_id:
            continue
        start_group, end_group = _road_endpoint_groups(candidate_road, nodes)
        if start_group == end_group or next_group_id not in {start_group, end_group}:
            continue
        other_group_id = end_group if start_group == next_group_id else start_group
        if other_group_id != current_group_id:
            return False
    return True


def _mainline_record(
    records: list[dict[str, Any]],
    *,
    allow_parallel_pair: bool,
    current_group_id: str,
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
) -> dict[str, Any] | None:
    if not records:
        return None
    best = records[0]
    best_delta = best.get("angle_delta")
    if best_delta is None or float(best_delta) > THROUGH_MAINLINE_MAX_ANGLE_DEG:
        return None
    if _candidate_enters_one_hop_dead_end(best, current_group_id=current_group_id, nodes=nodes, roads=roads):
        for candidate in records[1:]:
            candidate_delta = candidate.get("angle_delta")
            if candidate_delta is None or float(candidate_delta) > THROUGH_MAINLINE_MAX_ANGLE_DEG:
                continue
            if float(candidate_delta) - float(best_delta) > THROUGH_DEAD_END_TIE_BREAK_MAX_EXTRA_DEG:
                break
            if not _candidate_enters_one_hop_dead_end(
                candidate,
                current_group_id=current_group_id,
                nodes=nodes,
                roads=roads,
            ):
                selected = dict(candidate)
                selected["tie_break"] = "near_parallel_non_dead_end_over_one_hop_dead_end"
                return selected
    if allow_parallel_pair or len(records) == 1:
        return best
    second_delta = records[1].get("angle_delta") if len(records) > 1 else None
    if second_delta is None or float(second_delta) - float(best_delta) >= THROUGH_MAINLINE_MIN_MARGIN_DEG:
        return best
    return None


def _decision_reason(
    base: str,
    *,
    kind_values: tuple[str, ...],
    selected: dict[str, Any] | None,
    excluded_right_turn_ids: tuple[str, ...],
    loop_road_ids: tuple[str, ...],
) -> str:
    parts = [base, f"kind={','.join(kind_values) or '<missing>'}"]
    if selected:
        delta = selected.get("angle_delta")
        delta_text = "unknown" if delta is None else f"{float(delta):.1f}"
        parts.append(f"selected={selected['road_id']}")
        parts.append(f"angle_delta={delta_text}")
        if selected.get("tie_break"):
            parts.append(f"tie_break={selected['tie_break']}")
    if excluded_right_turn_ids:
        parts.append("excluded_right_turn=" + ",".join(excluded_right_turn_ids))
    if loop_road_ids:
        parts.append("loop_candidates=" + ",".join(loop_road_ids))
    return "|".join(parts)


def _decide_through(
    *,
    group_id: str,
    current_group_id: str,
    previous_road_id: str,
    incident_ids: tuple[str, ...],
    excluded_right_turn_ids: tuple[str, ...],
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
) -> tuple[str, str, str | None]:
    kind_values = _kind_values_for_group(group_id, groups, nodes)
    kind_category = _kind_category(kind_values)
    records, loop_road_ids = _continuation_records(
        group_id=group_id,
        current_group_id=current_group_id,
        previous_road_id=previous_road_id,
        incident_ids=incident_ids,
        nodes=nodes,
        roads=roads,
    )
    if not records:
        status = "loop_to_current_junction" if loop_road_ids else "dead_end"
        reason = "only_loop_continuations" if loop_road_ids else "no_continuation_after_seed"
        return status, _decision_reason(reason, kind_values=kind_values, selected=None, excluded_right_turn_ids=excluded_right_turn_ids, loop_road_ids=loop_road_ids), None

    is_t_like_topology = len(incident_ids) >= 3 and len(records) <= 3
    allow_parallel_pair = kind_category == "kind_continue" or is_t_like_topology
    selected = _mainline_record(
        records,
        allow_parallel_pair=allow_parallel_pair,
        current_group_id=current_group_id,
        nodes=nodes,
        roads=roads,
    )

    if kind_category == "kind_2048":
        if selected:
            return (
                "t_mainline_through",
                _decision_reason("kind_2048_t_mainline_through", kind_values=kind_values, selected=selected, excluded_right_turn_ids=excluded_right_turn_ids, loop_road_ids=loop_road_ids),
                str(selected["road_id"]),
            )
        return "t_side_terminal", _decision_reason("kind_2048_t_side_terminal", kind_values=kind_values, selected=None, excluded_right_turn_ids=excluded_right_turn_ids, loop_road_ids=loop_road_ids), None

    if kind_category == "kind_4":
        has_three_degree = _entry_node_has_three_degree(
            group_id=group_id,
            previous_road_id=previous_road_id,
            incident_ids=incident_ids,
            nodes=nodes,
            roads=roads,
        )
        if is_t_like_topology and selected:
            return (
                "t_mainline_through",
                _decision_reason("kind_4_t_like_mainline_through", kind_values=kind_values, selected=selected, excluded_right_turn_ids=excluded_right_turn_ids, loop_road_ids=loop_road_ids),
                str(selected["road_id"]),
            )
        strict_selected = _mainline_record(
            records,
            allow_parallel_pair=False,
            current_group_id=current_group_id,
            nodes=nodes,
            roads=roads,
        )
        if len(incident_ids) >= 3 and strict_selected:
            return (
                "t_mainline_through",
                _decision_reason("kind_4_directional_t_mainline_through", kind_values=kind_values, selected=strict_selected, excluded_right_turn_ids=excluded_right_turn_ids, loop_road_ids=loop_road_ids),
                str(strict_selected["road_id"]),
            )
        if is_t_like_topology:
            return "t_side_terminal", _decision_reason("kind_4_t_like_side_terminal", kind_values=kind_values, selected=None, excluded_right_turn_ids=excluded_right_turn_ids, loop_road_ids=loop_road_ids), None
        if not has_three_degree and selected:
            return (
                "simple_through",
                _decision_reason("kind_4_non_three_degree_through", kind_values=kind_values, selected=selected, excluded_right_turn_ids=excluded_right_turn_ids, loop_road_ids=loop_road_ids),
                str(selected["road_id"]),
            )
        return "semantic_boundary", _decision_reason("kind_4_non_t_semantic_boundary", kind_values=kind_values, selected=None, excluded_right_turn_ids=excluded_right_turn_ids, loop_road_ids=loop_road_ids), None

    if len(records) == 1:
        selected = records[0]
        return (
            "simple_through",
            _decision_reason("kind_continue_single_continuation", kind_values=kind_values, selected=selected, excluded_right_turn_ids=excluded_right_turn_ids, loop_road_ids=loop_road_ids),
            str(selected["road_id"]),
        )
    if selected:
        return (
            "t_mainline_through",
            _decision_reason("kind_continue_directional_mainline", kind_values=kind_values, selected=selected, excluded_right_turn_ids=excluded_right_turn_ids, loop_road_ids=loop_road_ids),
            str(selected["road_id"]),
        )
    return "ambiguous_boundary", _decision_reason("kind_continue_no_unique_continuation", kind_values=kind_values, selected=None, excluded_right_turn_ids=excluded_right_turn_ids, loop_road_ids=loop_road_ids), None


def _add_issue(issues: list[dict[str, Any]], issue_type: str, **payload: Any) -> None:
    issues.append({"issue_type": issue_type, **payload})


def _build_trace(
    *,
    dataset: str,
    junction_id: str,
    trace_index: int,
    seed_road: RoadRecord,
    seed_role: str,
    current_group_id: str,
    current_member_node_ids: set[str],
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
    right_turn_formway_values: set[str],
) -> tuple[ArmTrace, tuple[ThroughDecisionAudit, ...], str | None, tuple[str, ...], tuple[dict[str, Any], ...]]:
    trace_id = f"{dataset.lower()}_{junction_id}_trace_{trace_index:04d}"
    traced_road_ids: list[str] = [seed_road.road_id]
    outside_node_id = _outside_node_for_seed(seed_road, current_member_node_ids)
    traced_node_ids: list[str] = []
    decisions: list[ThroughDecisionAudit] = []
    trace_issues: list[dict[str, Any]] = []
    status_refs: list[str] = []

    if outside_node_id is None:
        _add_issue(trace_issues, "seed_road_unassigned", road_id=seed_road.road_id, reason="seed_does_not_cross_current_junction")
        return (
            ArmTrace(
                dataset=dataset,
                current_junction_id=junction_id,
                trace_id=trace_id,
                seed_road_id=seed_road.road_id,
                seed_role=seed_role,
                traced_road_ids=tuple(traced_road_ids),
                traced_node_ids=tuple(traced_node_ids),
                through_decisions=tuple(status_refs),
                stop_type="unresolved",
                stop_reason="seed_does_not_cross_current_junction",
                assigned_initial_arm_id=None,
                issue_flags=("seed_road_unassigned",),
            ),
            tuple(decisions),
            None,
            tuple(),
            tuple(trace_issues),
        )

    if outside_node_id not in nodes:
        _add_issue(trace_issues, "patch_boundary", road_id=seed_road.road_id, missing_node_id=outside_node_id)
        return (
            ArmTrace(
                dataset=dataset,
                current_junction_id=junction_id,
                trace_id=trace_id,
                seed_road_id=seed_road.road_id,
                seed_role=seed_role,
                traced_road_ids=tuple(traced_road_ids),
                traced_node_ids=(outside_node_id,),
                through_decisions=tuple(status_refs),
                stop_type="patch_boundary",
                stop_reason="seed_outside_node_missing",
                assigned_initial_arm_id=None,
                issue_flags=("patch_boundary",),
            ),
            tuple(decisions),
            semantic_group_id(None, outside_node_id),
            (outside_node_id,),
            tuple(trace_issues),
        )

    group_id = semantic_group_id(nodes[outside_node_id], outside_node_id)
    previous_road_id = seed_road.road_id
    terminal_group_id: str | None = group_id
    max_steps = max(len(roads) + 2, 4)

    for _ in range(max_steps):
        traced_node_ids.extend(node_id for node_id in _node_ids_for_group(group_id, groups) if node_id not in traced_node_ids)
        if group_id == current_group_id:
            _add_issue(trace_issues, "loop_to_current_junction", trace_id=trace_id, node_group_id=group_id)
            return (
                ArmTrace(
                    dataset=dataset,
                    current_junction_id=junction_id,
                    trace_id=trace_id,
                    seed_road_id=seed_road.road_id,
                    seed_role=seed_role,
                    traced_road_ids=tuple(traced_road_ids),
                    traced_node_ids=tuple(traced_node_ids),
                    through_decisions=tuple(status_refs),
                    stop_type="loop_to_current_junction",
                    stop_reason="trace_returned_to_current_junction",
                    assigned_initial_arm_id=None,
                    issue_flags=("loop_to_current_junction",),
                ),
                tuple(decisions),
                group_id,
                _node_ids_for_group(group_id, groups),
                tuple(trace_issues),
            )

        kind_values = _kind_values_for_group(group_id, groups, nodes)
        raw_incident_ids = _incident_active_roads(
            group_id=group_id,
            roads=roads,
            nodes=nodes,
            excluded_road_ids=excluded_road_ids,
            current_internal_road_ids=internal_road_ids,
        )
        through_excluded_right_turn_ids = tuple(
            sorted(road_id for road_id in raw_incident_ids if _is_right_turn_road(roads[road_id], right_turn_formway_values))
        )
        for road_id in through_excluded_right_turn_ids:
            _add_issue(trace_issues, "right_turn_excluded", trace_id=trace_id, node_group_id=group_id, road_id=road_id, formway=roads[road_id].formway)
        incident_ids = tuple(road_id for road_id in raw_incident_ids if road_id not in set(through_excluded_right_turn_ids))
        status, reason, outgoing_road_id = _decide_through(
            group_id=group_id,
            current_group_id=current_group_id,
            previous_road_id=previous_road_id,
            incident_ids=incident_ids,
            excluded_right_turn_ids=through_excluded_right_turn_ids,
            groups=groups,
            nodes=nodes,
            roads=roads,
        )
        if status == "ambiguous_boundary":
            _add_issue(trace_issues, "t_junction_uncertain", trace_id=trace_id, node_group_id=group_id)
            _add_issue(trace_issues, "ambiguous_boundary", trace_id=trace_id, node_group_id=group_id)
        if status == "t_side_terminal":
            _add_issue(trace_issues, "t_side_terminal", trace_id=trace_id, node_group_id=group_id)

        decision = ThroughDecisionAudit(
            dataset=dataset,
            current_junction_id=junction_id,
            trace_id=trace_id,
            node_group_id=group_id,
            member_node_ids=_node_ids_for_group(group_id, groups),
            incoming_road_id=previous_road_id,
            outgoing_road_id=outgoing_road_id,
            status=status,
            decision_reason=reason,
            incident_road_ids=incident_ids,
        )
        decisions.append(decision)
        status_refs.append(status)

        if status not in CONTINUE_STATUSES:
            if status in {"ambiguous_boundary", "patch_boundary", "loop_to_current_junction"}:
                _add_issue(trace_issues, status, trace_id=trace_id, node_group_id=group_id)
            terminal_group_id = group_id
            return (
                ArmTrace(
                    dataset=dataset,
                    current_junction_id=junction_id,
                    trace_id=trace_id,
                    seed_road_id=seed_road.road_id,
                    seed_role=seed_role,
                    traced_road_ids=tuple(traced_road_ids),
                    traced_node_ids=tuple(traced_node_ids),
                    through_decisions=tuple(status_refs),
                    stop_type=status,
                    stop_reason=reason,
                    assigned_initial_arm_id=None,
                    issue_flags=tuple(sorted({issue["issue_type"] for issue in trace_issues})),
                ),
                tuple(decisions),
                terminal_group_id,
                _node_ids_for_group(group_id, groups),
                tuple(trace_issues),
            )

        next_road = roads[outgoing_road_id]
        next_group_id = _other_group_for_road(next_road, group_id, nodes)
        if next_group_id is None:
            _add_issue(trace_issues, "patch_boundary", trace_id=trace_id, road_id=next_road.road_id)
            terminal_group_id = group_id
            return (
                ArmTrace(
                    dataset=dataset,
                    current_junction_id=junction_id,
                    trace_id=trace_id,
                    seed_road_id=seed_road.road_id,
                    seed_role=seed_role,
                    traced_road_ids=tuple(traced_road_ids),
                    traced_node_ids=tuple(traced_node_ids),
                    through_decisions=tuple(status_refs),
                    stop_type="patch_boundary",
                    stop_reason="continuation_endpoint_missing",
                    assigned_initial_arm_id=None,
                    issue_flags=tuple(sorted({issue["issue_type"] for issue in trace_issues})),
                ),
                tuple(decisions),
                terminal_group_id,
                _node_ids_for_group(group_id, groups),
                tuple(trace_issues),
            )
        traced_road_ids.append(next_road.road_id)
        previous_road_id = next_road.road_id
        group_id = next_group_id
        terminal_group_id = group_id

    _add_issue(trace_issues, "loop_to_current_junction", trace_id=trace_id, reason="trace_step_limit_reached")
    return (
        ArmTrace(
            dataset=dataset,
            current_junction_id=junction_id,
            trace_id=trace_id,
            seed_road_id=seed_road.road_id,
            seed_role=seed_role,
            traced_road_ids=tuple(traced_road_ids),
            traced_node_ids=tuple(traced_node_ids),
            through_decisions=tuple(status_refs),
            stop_type="loop_to_current_junction",
            stop_reason="trace_step_limit_reached",
            assigned_initial_arm_id=None,
            issue_flags=("loop_to_current_junction",),
        ),
        tuple(decisions),
        terminal_group_id,
        _node_ids_for_group(terminal_group_id or "", groups),
        tuple(trace_issues),
    )


def _build_initial_arms(
    *,
    dataset: str,
    junction_id: str,
    traces: list[ArmTrace],
    trace_terminals: dict[str, tuple[str | None, tuple[str, ...]]],
) -> tuple[tuple[InitialArm, ...], tuple[ArmTrace, ...], list[dict[str, Any]]]:
    issues: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str | None], list[ArmTrace]] = defaultdict(list)
    for trace in traces:
        terminal_group_id, _ = trace_terminals.get(trace.trace_id, (None, tuple()))
        grouped[(trace.stop_type, terminal_group_id)].append(trace)

    arms: list[InitialArm] = []
    assigned_traces: list[ArmTrace] = []
    road_to_arm: dict[str, str] = {}
    for index, ((terminal_type, terminal_group_id), arm_traces) in enumerate(sorted(grouped.items(), key=lambda item: str(item[0])), start=1):
        arm_id = f"A{index}"
        member_road_ids = tuple(sorted({road_id for trace in arm_traces for road_id in trace.traced_road_ids}))
        seed_road_ids = tuple(sorted(trace.seed_road_id for trace in arm_traces))
        connector_road_ids = tuple(sorted(set(member_road_ids) - set(seed_road_ids)))
        inbound = tuple(sorted(trace.seed_road_id for trace in arm_traces if trace.seed_role == "inbound"))
        outbound = tuple(sorted(trace.seed_road_id for trace in arm_traces if trace.seed_role == "outbound"))
        bidirectional = tuple(sorted(trace.seed_road_id for trace in arm_traces if trace.seed_role == "bidirectional"))
        risk_flags = tuple(sorted({flag for trace in arm_traces for flag in trace.issue_flags if flag not in NON_RISK_TRACE_FLAGS}))
        build_status = "unstable" if terminal_type in RISK_STOP_TYPES or risk_flags else "stable"
        terminal_members = trace_terminals.get(arm_traces[0].trace_id, (None, tuple()))[1]
        arm = InitialArm(
            dataset=dataset,
            current_junction_id=junction_id,
            initial_arm_id=arm_id,
            terminal_type=terminal_type if terminal_type != "simple_through" else "neighbor_junction",
            terminal_junction_id=terminal_group_id,
            terminal_member_node_ids=terminal_members,
            member_road_ids=member_road_ids,
            seed_road_ids=seed_road_ids,
            connector_road_ids=connector_road_ids,
            inbound_member_road_ids=inbound,
            outbound_member_road_ids=outbound,
            bidirectional_member_road_ids=bidirectional,
            build_status=build_status,
            risk_flags=risk_flags,
        )
        arms.append(arm)
        for road_id in member_road_ids:
            if road_id in road_to_arm and road_to_arm[road_id] != arm_id:
                _add_issue(issues, "road_assigned_to_multiple_arms", road_id=road_id, arm_ids=[road_to_arm[road_id], arm_id])
            road_to_arm[road_id] = arm_id
        assigned_traces.extend(replace(trace, assigned_initial_arm_id=arm_id) for trace in arm_traces)
    return tuple(arms), tuple(sorted(assigned_traces, key=lambda trace: trace.trace_id)), issues


def _enrich_traces_with_special_fields(
    traces: tuple[ArmTrace, ...],
    roads: dict[str, RoadRecord],
) -> tuple[ArmTrace, ...]:
    enriched: list[ArmTrace] = []
    for trace in traces:
        advance_left_ids = tuple(
            sorted(road_id for road_id in trace.traced_road_ids if road_id in roads and is_advance_left_turn_road(roads[road_id]))
        )
        trunk_candidate_ids = tuple(
            sorted(
                road_id
                for road_id in trace.traced_road_ids
                if road_id in roads and not is_advance_left_turn_road(roads[road_id]) and not is_advance_right_turn_road(roads[road_id])
            )
        )
        enriched.append(
            replace(
                trace,
                advance_left_turn_road_ids_in_trace=advance_left_ids,
                trunk_candidate_road_ids=trunk_candidate_ids,
            )
        )
    return tuple(enriched)


def _enrich_initial_arms_with_trunk(
    initial_arms: tuple[InitialArm, ...],
    roads: dict[str, RoadRecord],
) -> tuple[InitialArm, ...]:
    enriched: list[InitialArm] = []
    for arm in initial_arms:
        trunk = build_trunk_for_arm(arm, roads)
        enriched.append(
            replace(
                arm,
                has_advance_left_turn=bool(trunk.advance_left_turn_road_ids),
                advance_left_turn_road_ids=trunk.advance_left_turn_road_ids,
                trunk_road_ids=trunk.trunk_road_ids,
                trunk_status=trunk.trunk_status,
                trunk_reason=trunk.trunk_reason,
                non_trunk_member_road_ids=trunk.non_trunk_member_road_ids,
            )
        )
    return tuple(enriched)


def _initial_to_final_arm_id(final_arms: tuple[FinalArm, ...]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for final_arm in final_arms:
        for initial_id in final_arm.source_initial_arm_ids:
            mapping[initial_id] = final_arm.final_arm_id
    return mapping


def _enrich_initial_arms_with_advance_right_relations(
    initial_arms: tuple[InitialArm, ...],
    initial_to_final_arm_id: dict[str, str],
    relations,
) -> tuple[InitialArm, ...]:
    enriched: list[InitialArm] = []
    for arm in initial_arms:
        final_id = initial_to_final_arm_id.get(arm.initial_arm_id)
        arm_relations = [relation for relation in relations if relation.from_arm_id == final_id]
        enriched.append(
            replace(
                arm,
                has_inbound_advance_right_turn=bool(arm_relations),
                advance_right_turn_relation_ids=tuple(sorted(relation.relation_id for relation in arm_relations)),
                advance_right_turn_target_arm_ids=tuple(sorted({relation.to_arm_id for relation in arm_relations if relation.to_arm_id})),
            )
        )
    return tuple(enriched)


def _initial_arm_final_payload(arm: InitialArm) -> dict[str, Any]:
    return {
        "initial_arm_id": arm.initial_arm_id,
        "member_road_ids": arm.member_road_ids,
        "seed_road_ids": arm.seed_road_ids,
        "connector_road_ids": arm.connector_road_ids,
        "inbound_member_road_ids": arm.inbound_member_road_ids,
        "outbound_member_road_ids": arm.outbound_member_road_ids,
        "bidirectional_member_road_ids": arm.bidirectional_member_road_ids,
        "terminal_type": arm.terminal_type,
        "terminal_junction_id": arm.terminal_junction_id,
        "has_advance_left_turn": arm.has_advance_left_turn,
        "advance_left_turn_road_ids": arm.advance_left_turn_road_ids,
        "trunk_road_ids": arm.trunk_road_ids,
        "trunk_status": arm.trunk_status,
        "trunk_reason": arm.trunk_reason,
        "non_trunk_member_road_ids": arm.non_trunk_member_road_ids,
        "has_inbound_advance_right_turn": arm.has_inbound_advance_right_turn,
        "advance_right_turn_relation_ids": arm.advance_right_turn_relation_ids,
        "advance_right_turn_target_arm_ids": arm.advance_right_turn_target_arm_ids,
    }


def _should_apply_local_candidate_fallback(
    initial_arms: tuple[InitialArm, ...],
    local_arm_candidates: tuple[LocalArmCandidate, ...],
) -> bool:
    if not local_arm_candidates or len(local_arm_candidates) >= len(initial_arms):
        return False
    initial_ids = {arm.initial_arm_id for arm in initial_arms}
    candidate_source_ids = {
        source_id
        for candidate in local_arm_candidates
        for source_id in candidate.source_initial_arm_ids
    }
    if not initial_ids or candidate_source_ids != initial_ids:
        return False
    return any(len(candidate.source_initial_arm_ids) > 1 for candidate in local_arm_candidates)


def _merged_trunk_status(source_arms: list[InitialArm]) -> tuple[str, str]:
    statuses = {arm.trunk_status for arm in source_arms}
    if len(statuses) == 1:
        status = next(iter(statuses))
        return status, "aggregated_from_single_trunk_status"
    if "ambiguous" in statuses:
        return "ambiguous", "aggregated_local_candidate_contains_ambiguous_trunk"
    if "complete_min_loop" in statuses:
        return "partial", "aggregated_local_candidate_mixed_trunk_status"
    if "partial" in statuses:
        return "partial", "aggregated_local_candidate_partial_trunk"
    return "none", "aggregated_local_candidate_no_trunk"


def _final_special_fields(source_arms: list[InitialArm]) -> dict[str, Any]:
    trunk_status, trunk_reason = _merged_trunk_status(source_arms)
    return {
        "has_advance_left_turn": any(arm.has_advance_left_turn for arm in source_arms),
        "advance_left_turn_road_ids": tuple(sorted({road_id for arm in source_arms for road_id in arm.advance_left_turn_road_ids})),
        "trunk_road_ids": tuple(sorted({road_id for arm in source_arms for road_id in arm.trunk_road_ids})),
        "trunk_status": trunk_status,
        "trunk_reason": trunk_reason,
        "non_trunk_member_road_ids": tuple(sorted({road_id for arm in source_arms for road_id in arm.non_trunk_member_road_ids})),
        "has_inbound_advance_right_turn": any(arm.has_inbound_advance_right_turn for arm in source_arms),
        "advance_right_turn_relation_ids": tuple(sorted({item for arm in source_arms for item in arm.advance_right_turn_relation_ids})),
        "advance_right_turn_target_arm_ids": tuple(sorted({item for arm in source_arms for item in arm.advance_right_turn_target_arm_ids})),
    }


def _build_final_arms(
    initial_arms: tuple[InitialArm, ...],
    local_arm_candidates: tuple[LocalArmCandidate, ...],
) -> tuple[FinalArm, ...]:
    initial_by_id = {arm.initial_arm_id: arm for arm in initial_arms}
    if _should_apply_local_candidate_fallback(initial_arms, local_arm_candidates):
        final_arms: list[FinalArm] = []
        for index, candidate in enumerate(local_arm_candidates, start=1):
            source_arms = [initial_by_id[arm_id] for arm_id in candidate.source_initial_arm_ids if arm_id in initial_by_id]
            member_road_ids = tuple(sorted({road_id for arm in source_arms for road_id in arm.member_road_ids}))
            seed_road_ids = tuple(sorted({road_id for arm in source_arms for road_id in arm.seed_road_ids}))
            connector_road_ids = tuple(sorted({road_id for arm in source_arms for road_id in arm.connector_road_ids}))
            inbound_road_ids = tuple(sorted({road_id for arm in source_arms for road_id in arm.inbound_member_road_ids}))
            outbound_road_ids = tuple(sorted({road_id for arm in source_arms for road_id in arm.outbound_member_road_ids}))
            bidirectional_road_ids = tuple(sorted({road_id for arm in source_arms for road_id in arm.bidirectional_member_road_ids}))
            final_arms.append(
                FinalArm(
                    dataset=candidate.dataset,
                    current_junction_id=candidate.current_junction_id,
                    final_arm_id=f"F{index}",
                    source_initial_arm_ids=candidate.source_initial_arm_ids,
                    merge_status="local_candidate_fallback",
                    merge_reason="current_junction_seed_local_trend_fragmentation_fallback",
                    initial_arm={
                        "local_arm_candidate_id": candidate.local_arm_candidate_id,
                        "member_road_ids": member_road_ids,
                        "seed_road_ids": seed_road_ids,
                        "connector_road_ids": connector_road_ids,
                        "inbound_member_road_ids": inbound_road_ids,
                        "outbound_member_road_ids": outbound_road_ids,
                        "bidirectional_member_road_ids": bidirectional_road_ids,
                        "local_stub_road_ids": candidate.local_stub_road_ids,
                        "source_initial_arms": [_initial_arm_final_payload(arm) for arm in source_arms],
                    },
                    **_final_special_fields(source_arms),
                )
            )
        return tuple(final_arms)

    final_arms: list[FinalArm] = []
    for arm in initial_arms:
        final_arms.append(
            FinalArm(
                dataset=arm.dataset,
                current_junction_id=arm.current_junction_id,
                final_arm_id=arm.initial_arm_id.replace("A", "F", 1),
                source_initial_arm_ids=(arm.initial_arm_id,),
                merge_status="not_applied",
                merge_reason="reserved_for_future_case_based_rules",
                initial_arm=_initial_arm_final_payload(arm),
                **_final_special_fields([arm]),
            )
        )
    return tuple(final_arms)


def _clockwise_delta(start_angle: float, end_angle: float) -> float:
    return (end_angle - start_angle) % 360.0


def _role_seed_bundles(seed_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bundles: list[dict[str, Any]] = []
    for item in sorted(seed_items, key=lambda value: (str(value["role"]), float(value["angle"]), str(value["road_id"]))):
        best_index: int | None = None
        best_distance = LOCAL_CANDIDATE_SAME_ROLE_BUNDLE_TOLERANCE_DEG + 1.0
        for index, bundle in enumerate(bundles):
            if bundle["role"] != item["role"]:
                continue
            distance = abs(float(item["angle"]) - float(bundle["mean_angle"]))
            if distance <= LOCAL_CANDIDATE_SAME_ROLE_BUNDLE_TOLERANCE_DEG and distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            bundles.append({"items": [item], "role": item["role"], "mean_angle": float(item["angle"])})
        else:
            bundles[best_index]["items"].append(item)
            bundles[best_index]["mean_angle"] = _mean_angle([float(seed_item["angle"]) for seed_item in bundles[best_index]["items"]])
    return bundles


def _directional_local_seed_groups(seed_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    bundles = _role_seed_bundles(seed_items)
    seed_groups: list[dict[str, Any]] = []
    used_bundle_ids: set[int] = set()

    bidirectional_bundles = [bundle for bundle in bundles if bundle["role"] == "bidirectional"]
    for bundle in sorted(bidirectional_bundles, key=lambda value: (float(value["mean_angle"]), str(value["items"][0]["road_id"]))):
        used_bundle_ids.add(id(bundle))
        seed_groups.append(
            {
                "items": list(bundle["items"]),
                "mean_angle": float(bundle["mean_angle"]),
                "grouping_reason": "bidirectional_seed_directional_corridor",
            }
        )

    outbound_bundles = sorted(
        [bundle for bundle in bundles if bundle["role"] == "outbound"],
        key=lambda value: (float(value["mean_angle"]), str(value["items"][0]["road_id"])),
    )
    inbound_bundles = sorted(
        [bundle for bundle in bundles if bundle["role"] == "inbound"],
        key=lambda value: (float(value["mean_angle"]), str(value["items"][0]["road_id"])),
    )
    for outbound in outbound_bundles:
        if id(outbound) in used_bundle_ids:
            continue
        same_direction_candidates = [
            (float(_angular_distance(float(outbound["mean_angle"]), float(inbound["mean_angle"]))), inbound)
            for inbound in inbound_bundles
            if id(inbound) not in used_bundle_ids
            and _angular_distance(float(outbound["mean_angle"]), float(inbound["mean_angle"])) <= LOCAL_CANDIDATE_SAME_DIRECTION_PAIR_TOLERANCE_DEG
        ]
        if not same_direction_candidates:
            continue
        selected_inbound = min(same_direction_candidates, key=lambda item: (item[0], str(item[1]["items"][0]["road_id"])))[1]
        items = list(outbound["items"]) + list(selected_inbound["items"])
        used_bundle_ids.add(id(outbound))
        used_bundle_ids.add(id(selected_inbound))
        seed_groups.append(
            {
                "items": items,
                "mean_angle": _mean_angle([float(item["angle"]) for item in items]),
                "grouping_reason": "same_direction_inbound_outbound_corridor",
            }
        )

    for outbound in outbound_bundles:
        if id(outbound) in used_bundle_ids:
            continue
        out_angle = float(outbound["mean_angle"])
        next_outbound_delta = min(
            (
                _clockwise_delta(out_angle, float(other["mean_angle"]))
                for other in outbound_bundles
                if other is not outbound and _clockwise_delta(out_angle, float(other["mean_angle"])) > 0.0
            ),
            default=360.0,
        )
        inbound_candidates: list[tuple[float, dict[str, Any]]] = []
        for inbound in inbound_bundles:
            if id(inbound) in used_bundle_ids:
                continue
            delta = _clockwise_delta(out_angle, float(inbound["mean_angle"]))
            if 0.0 < delta <= LOCAL_CANDIDATE_OUTBOUND_TO_INBOUND_MAX_GAP_DEG and delta < next_outbound_delta:
                inbound_candidates.append((delta, inbound))
        selected_inbound = min(inbound_candidates, key=lambda item: (item[0], str(item[1]["items"][0]["road_id"])))[1] if inbound_candidates else None
        items = list(outbound["items"])
        reason = "outbound_to_clockwise_inbound_directional_corridor"
        if selected_inbound is not None:
            items.extend(selected_inbound["items"])
            used_bundle_ids.add(id(selected_inbound))
        else:
            reason = "outbound_only_directional_corridor"
        used_bundle_ids.add(id(outbound))
        seed_groups.append({"items": items, "mean_angle": _mean_angle([float(item["angle"]) for item in items]), "grouping_reason": reason})

    for inbound in inbound_bundles:
        if id(inbound) in used_bundle_ids:
            continue
        used_bundle_ids.add(id(inbound))
        seed_groups.append(
            {
                "items": list(inbound["items"]),
                "mean_angle": float(inbound["mean_angle"]),
                "grouping_reason": "inbound_only_directional_corridor",
            }
        )

    return _merge_seed_groups_by_initial_arm(seed_items, seed_groups)


def _merge_seed_groups_by_initial_arm(seed_items: list[dict[str, Any]], seed_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    group_keys: list[set[str]] = []
    group_reasons: list[set[str]] = []
    for group in seed_groups:
        keys = {
            str(item.get("initial_arm_id") or f"road:{item['road_id']}")
            for item in group["items"]
        }
        merged_index: int | None = None
        for index, existing_keys in enumerate(group_keys):
            if keys & existing_keys:
                merged_index = index
                break
        if merged_index is None:
            group_keys.append(set(keys))
            group_reasons.append({str(group.get("grouping_reason", "current_junction_seed_directional_corridor"))})
        else:
            group_keys[merged_index].update(keys)
            group_reasons[merged_index].add(str(group.get("grouping_reason", "current_junction_seed_directional_corridor")))

    changed = True
    while changed:
        changed = False
        for left in range(len(group_keys)):
            for right in range(left + 1, len(group_keys)):
                if group_keys[left] & group_keys[right]:
                    group_keys[left].update(group_keys[right])
                    group_reasons[left].update(group_reasons[right])
                    del group_keys[right]
                    del group_reasons[right]
                    changed = True
                    break
            if changed:
                break

    item_by_key: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in seed_items:
        item_by_key[str(item.get("initial_arm_id") or f"road:{item['road_id']}")].append(item)

    groups: list[dict[str, Any]] = []
    for keys, reasons in zip(group_keys, group_reasons, strict=False):
        items_by_road: dict[str, dict[str, Any]] = {}
        for key in keys:
            for item in item_by_key.get(key, []):
                items_by_road[str(item["road_id"])] = item
        items = list(items_by_road.values())
        groups.append(
            {
                "items": items,
                "mean_angle": _mean_angle([float(item["angle"]) for item in items]),
                "grouping_reason": "+".join(sorted(reasons)),
            }
        )
    return sorted(groups, key=lambda value: (float(value["mean_angle"]), str(value["items"][0]["road_id"])))


def _build_local_arm_candidates(
    *,
    dataset: str,
    junction_id: str,
    current_group_id: str,
    current_member_node_ids: set[str],
    seed_roads: list[tuple[RoadRecord, str]],
    assigned_traces: tuple[ArmTrace, ...],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
    right_turn_formway_values: set[str],
) -> tuple[LocalArmCandidate, ...]:
    trace_by_seed = {trace.seed_road_id: trace for trace in assigned_traces}
    seed_items: list[dict[str, Any]] = []
    for road, role in seed_roads:
        trend = _seed_trend_angle(road, current_member_node_ids, nodes)
        if trend is None:
            continue
        angle, node_pair = trend
        stub_road_ids, stub_node_ids = _local_stub_for_seed(
            seed_road=road,
            base_angle=angle,
            current_group_id=current_group_id,
            nodes=nodes,
            roads=roads,
            excluded_road_ids=excluded_road_ids,
            internal_road_ids=internal_road_ids,
            right_turn_formway_values=right_turn_formway_values,
        )
        seed_items.append(
            {
                "road_id": road.road_id,
                "role": role,
                "angle": angle,
                "initial_arm_id": trace_by_seed[road.road_id].assigned_initial_arm_id if road.road_id in trace_by_seed else None,
                "node_ids": tuple(sorted(set(node_pair) | set(stub_node_ids))),
                "stub_road_ids": stub_road_ids,
            }
        )

    groups = _directional_local_seed_groups(seed_items)

    candidates: list[LocalArmCandidate] = []
    for index, group in enumerate(sorted(groups, key=lambda value: float(value["mean_angle"])), start=1):
        items = list(group["items"])
        seed_ids = tuple(sorted(str(item["road_id"]) for item in items))
        inbound = tuple(sorted(str(item["road_id"]) for item in items if item["role"] == "inbound"))
        outbound = tuple(sorted(str(item["road_id"]) for item in items if item["role"] == "outbound"))
        bidirectional = tuple(sorted(str(item["road_id"]) for item in items if item["role"] == "bidirectional"))
        stub_ids = tuple(sorted({road_id for item in items for road_id in item["stub_road_ids"]}))
        node_ids = tuple(sorted({node_id for item in items for node_id in item["node_ids"] if node_id in nodes}))
        initial_arm_ids = tuple(
            sorted(
                {
                    trace_by_seed[seed_id].assigned_initial_arm_id
                    for seed_id in seed_ids
                    if seed_id in trace_by_seed and trace_by_seed[seed_id].assigned_initial_arm_id
                }
            )
        )
        angles = [float(item["angle"]) for item in items]
        mean_angle = _mean_angle(angles)
        risk_flags: list[str] = []
        has_inbound = bool(inbound or bidirectional)
        has_outbound = bool(outbound or bidirectional)
        if len(seed_ids) == 1 and not bidirectional:
            risk_flags.append("single_seed_candidate")
        if not has_inbound:
            risk_flags.append("no_inbound_seed")
        if not has_outbound:
            risk_flags.append("no_outbound_seed")
        if len(initial_arm_ids) > 1:
            risk_flags.append("primary_trace_fragmented")
        candidates.append(
            LocalArmCandidate(
                dataset=dataset,
                current_junction_id=junction_id,
                local_arm_candidate_id=f"L{index}",
                source_seed_road_ids=seed_ids,
                source_initial_arm_ids=initial_arm_ids,
                local_stub_road_ids=stub_ids,
                inbound_seed_road_ids=inbound,
                outbound_seed_road_ids=outbound,
                bidirectional_seed_road_ids=bidirectional,
                member_node_ids=node_ids,
                trend_angle_deg=round(mean_angle, 3),
                angular_spread_deg=round(_angular_spread(angles, mean_angle), 3),
                grouping_reason=str(group.get("grouping_reason", "current_junction_seed_directional_corridor")),
                build_status="candidate_unstable" if risk_flags else "candidate",
                risk_flags=tuple(sorted(risk_flags)),
            )
        )
    return tuple(candidates)


def _metrics_for(
    *,
    context: JunctionContext,
    initial_arms: tuple[InitialArm, ...],
    final_arms: tuple[FinalArm, ...],
    validation_metrics: dict[str, int],
    arm_corridor_evidence: tuple[Any, ...],
    advance_right_turn_relation_count: int,
    local_arm_candidates: tuple[LocalArmCandidate, ...],
    traces: tuple[ArmTrace, ...],
    decisions: tuple[ThroughDecisionAudit, ...],
    issue_counts: dict[str, int],
) -> dict[str, Any]:
    decision_counts = Counter(decision.status for decision in decisions)
    trunk_counts = Counter(arm.trunk_status for arm in initial_arms)
    stable = sum(1 for arm in initial_arms if arm.build_status == "stable")
    unstable = sum(1 for arm in initial_arms if arm.build_status == "unstable")
    seed_count = (
        len(context.inbound_seed_road_ids)
        + len(context.outbound_seed_road_ids)
        + len(context.bidirectional_seed_road_ids)
    )
    return {
        "member_node_count": len(context.member_node_ids),
        "internal_road_count": len(context.internal_road_ids),
        "seed_road_count": seed_count,
        "excluded_right_turn_road_count": len(context.excluded_right_turn_road_ids),
        "advance_left_turn_road_count": len(context.advance_left_turn_road_ids),
        "advance_right_turn_road_count": len(context.advance_right_turn_road_ids),
        "advance_right_turn_relation_count": advance_right_turn_relation_count,
        "advance_right_turn_unresolved_count": issue_counts.get("advance_right_turn_target_arm_not_found", 0)
        + issue_counts.get("advance_right_turn_ambiguous", 0)
        + issue_counts.get("advance_right_turn_patch_boundary", 0)
        + issue_counts.get("advance_right_turn_loop", 0),
        "trunk_complete_count": trunk_counts.get("complete_min_loop", 0),
        "trunk_partial_count": trunk_counts.get("partial", 0),
        "trunk_none_count": trunk_counts.get("none", 0),
        "trunk_ambiguous_count": trunk_counts.get("ambiguous", 0),
        "formway_missing_count": len(context.formway_missing_road_ids),
        "formway_unparseable_count": len(context.formway_unparseable_road_ids),
        "initial_arm_count": len(initial_arms),
        "final_arm_count": len(final_arms),
        "final_arm_validation_count": validation_metrics.get("final_arm_validation_count", 0),
        "final_arm_validated_count": validation_metrics.get("final_arm_validated_count", 0),
        "final_arm_weak_validated_count": validation_metrics.get("final_arm_weak_validated_count", 0),
        "final_arm_unvalidated_count": validation_metrics.get("final_arm_unvalidated_count", 0),
        "final_arm_validation_conflict_count": validation_metrics.get("final_arm_validation_conflict_count", 0),
        "arm_corridor_evidence_count": len(arm_corridor_evidence),
        "arm_corridor_extended_count": sum(1 for item in arm_corridor_evidence if item.corridor_status == "extended"),
        "arm_corridor_seed_only_count": sum(1 for item in arm_corridor_evidence if item.corridor_status == "seed_only"),
        "arm_corridor_ambiguous_count": sum(1 for item in arm_corridor_evidence if item.corridor_status == "ambiguous"),
        "local_arm_candidate_count": len(local_arm_candidates),
        "local_arm_fragmentation_gap": max(0, len(initial_arms) - len(local_arm_candidates)),
        "stable_arm_count": stable,
        "partial_arm_count": sum(1 for arm in initial_arms if arm.terminal_type == "patch_boundary"),
        "unstable_arm_count": unstable,
        "ambiguous_trace_count": decision_counts.get("ambiguous_boundary", 0),
        "t_mainline_through_count": decision_counts.get("t_mainline_through", 0),
        "t_side_terminal_count": decision_counts.get("t_side_terminal", 0),
        "patch_boundary_count": decision_counts.get("patch_boundary", 0) + issue_counts.get("patch_boundary", 0),
        "dead_end_count": decision_counts.get("dead_end", 0),
        "loop_count": issue_counts.get("loop_to_current_junction", 0),
        "seed_unassigned_count": issue_counts.get("seed_road_unassigned", 0),
        "issue_count": sum(issue_counts.values()),
        "trace_count": len(traces),
    }


def review_priority_from_metrics(metrics: dict[str, Any]) -> str:
    if (
        metrics["stable_arm_count"] == 0
        or metrics["initial_arm_count"] < 2
        or metrics["ambiguous_trace_count"] > 0
        or metrics["loop_count"] > 0
        or metrics["seed_unassigned_count"] > 0
        or metrics["trunk_ambiguous_count"] > 0
        or metrics.get("final_arm_validation_conflict_count", 0) > 0
        or metrics["formway_unparseable_count"] > max(3, metrics["seed_road_count"])
        or metrics["advance_right_turn_unresolved_count"] > max(3, metrics["advance_right_turn_road_count"])
    ):
        return "P0"
    if (
        metrics["patch_boundary_count"] > 0
        or metrics["dead_end_count"] > 0
        or metrics["excluded_right_turn_road_count"] > max(3, metrics["seed_road_count"])
        or metrics["t_mainline_through_count"] > 4
        or metrics["t_side_terminal_count"] > 4
        or metrics["trunk_partial_count"] > 0
        or metrics["trunk_none_count"] > 0
        or metrics.get("final_arm_unvalidated_count", 0) > 0
        or metrics.get("final_arm_weak_validated_count", 0) > 0
        or metrics["advance_right_turn_unresolved_count"] > 0
        or metrics["formway_missing_count"] > 0
        or metrics.get("road_movement_unmapped_count", 0) > 0
        or metrics.get("trunk_correction_count", 0) > 0
        or metrics.get("trunk_correction_straight_evidence_missing_count", 0) > 0
    ):
        return "P1"
    if metrics["issue_count"] == 0:
        return "P2"
    return "P3"


def build_dataset_arm_result(
    loaded: LoadedDataset,
    *,
    junction_id: str,
    right_turn_formway_values: set[str],
    road_next_road_records: tuple[RawRoadNextRoad, ...] = tuple(),
    has_road_next_road_input: bool = False,
) -> DatasetBuildResult:
    groups, _ = build_node_groups(loaded.nodes)
    resolved_junction_id, member_node_ids, input_flags = resolve_junction_members(
        loaded.nodes,
        junction_id=junction_id,
        dataset=loaded.dataset,
    )
    member_set = set(member_node_ids)
    issues: list[dict[str, Any]] = []
    for flag in input_flags:
        _add_issue(issues, flag, junction_id=junction_id)

    if "formway" not in loaded.road_layer.schema_properties:
        _add_issue(issues, "right_turn_field_missing", dataset=loaded.dataset, roads_path=str(loaded.road_layer.path))

    internal_road_ids: list[str] = []
    inbound_seed_ids: list[str] = []
    outbound_seed_ids: list[str] = []
    bidirectional_seed_ids: list[str] = []
    excluded_right_turn_ids: list[str] = []
    seed_roads: list[tuple[RoadRecord, str]] = []

    for road in loaded.roads.values():
        snode_inside = road.snodeid in member_set
        enode_inside = road.enodeid in member_set
        if snode_inside and enode_inside:
            internal_road_ids.append(road.road_id)
            continue
        if not (snode_inside or enode_inside):
            continue
        if _is_right_turn_road(road, right_turn_formway_values):
            excluded_right_turn_ids.append(road.road_id)
            _add_issue(issues, "right_turn_excluded", road_id=road.road_id, formway=road.formway)
            continue
        role = seed_role_for_road(road, member_set)
        if is_advance_right_turn_road(road) and not _advance_right_turn_enters_current_junction(road, member_set):
            continue
        if role is None:
            _add_issue(issues, "seed_road_unassigned", road_id=road.road_id, reason="direction_not_parseable")
            continue
        if role == "inbound":
            inbound_seed_ids.append(road.road_id)
        elif role == "outbound":
            outbound_seed_ids.append(road.road_id)
        else:
            bidirectional_seed_ids.append(road.road_id)
        seed_roads.append((road, role))

    outside_seed_node_ids = {
        outside_node_id
        for road, _ in seed_roads
        for outside_node_id in [_outside_node_for_seed(road, member_set)]
        if outside_node_id
    }
    special_road_ids = road_ids_touching_nodes(loaded.roads, member_set) | road_ids_touching_nodes(loaded.roads, outside_seed_node_ids)
    special_index = build_special_road_flag_index(loaded.roads, special_road_ids)
    for road_id in special_index.formway_missing_road_ids:
        _add_issue(issues, "formway_missing", road_id=road_id)
    for road_id in special_index.formway_unparseable_road_ids:
        _add_issue(issues, "formway_unparseable", road_id=road_id, formway=loaded.roads[road_id].formway)
    arm_member_advance_right_turn_ids = {
        road.road_id for road, _role in seed_roads if is_advance_right_turn_road(road)
    }
    relation_advance_right_turn_ids = tuple(
        road_id
        for road_id in special_index.advance_right_turn_road_ids
        if road_id not in arm_member_advance_right_turn_ids
    )

    if not member_node_ids:
        _add_issue(issues, "junction_member_nodes_not_found", junction_id=junction_id)
    if not seed_roads and excluded_right_turn_ids:
        _add_issue(issues, "all_seed_roads_excluded", junction_id=junction_id)
    if not seed_roads and not excluded_right_turn_ids:
        _add_issue(issues, "seed_road_missing", junction_id=junction_id)
    if loaded.dataset == "RCSD" and not loaded.nodes:
        _add_issue(issues, "rcsd_structure_incomplete", junction_id=junction_id)
    if loaded.dataset == "FRCSD" and not loaded.nodes:
        _add_issue(issues, "frcsd_structure_incomplete", junction_id=junction_id)

    context = JunctionContext(
        dataset=loaded.dataset,
        junction_id=junction_id,
        member_node_ids=tuple(sorted(member_node_ids)),
        internal_road_ids=tuple(sorted(internal_road_ids)),
        inbound_seed_road_ids=tuple(sorted(inbound_seed_ids)),
        outbound_seed_road_ids=tuple(sorted(outbound_seed_ids)),
        bidirectional_seed_road_ids=tuple(sorted(bidirectional_seed_ids)),
        excluded_right_turn_road_ids=tuple(sorted(excluded_right_turn_ids)),
        advance_left_turn_road_ids=special_index.advance_left_turn_road_ids,
        advance_right_turn_road_ids=special_index.advance_right_turn_road_ids,
        formway_missing_road_ids=special_index.formway_missing_road_ids,
        formway_unparseable_road_ids=special_index.formway_unparseable_road_ids,
        special_formway_issue_flags=special_index.issue_flags,
        input_issue_flags=tuple(sorted(set(input_flags))),
    )

    traces: list[ArmTrace] = []
    decisions: list[ThroughDecisionAudit] = []
    trace_terminals: dict[str, tuple[str | None, tuple[str, ...]]] = {}
    for index, (road, role) in enumerate(seed_roads, start=1):
        trace, trace_decisions, terminal_group_id, terminal_members, trace_issues = _build_trace(
            dataset=loaded.dataset,
            junction_id=junction_id,
            trace_index=index,
            seed_road=road,
            seed_role=role,
            current_group_id=resolved_junction_id,
            current_member_node_ids=member_set,
            groups=groups,
            nodes=loaded.nodes,
            roads=loaded.roads,
            excluded_road_ids=set(excluded_right_turn_ids),
            internal_road_ids=set(internal_road_ids),
            right_turn_formway_values=right_turn_formway_values,
        )
        traces.append(trace)
        decisions.extend(trace_decisions)
        trace_terminals[trace.trace_id] = (terminal_group_id, terminal_members)
        issues.extend(trace_issues)

    initial_arms, assigned_traces, arm_issues = _build_initial_arms(
        dataset=loaded.dataset,
        junction_id=junction_id,
        traces=traces,
        trace_terminals=trace_terminals,
    )
    assigned_traces = _enrich_traces_with_special_fields(assigned_traces, loaded.roads)
    initial_arms = _enrich_initial_arms_with_trunk(initial_arms, loaded.roads)
    arm_advance_left_ids = tuple(sorted({road_id for arm in initial_arms for road_id in arm.advance_left_turn_road_ids}))
    context = replace(
        context,
        advance_left_turn_road_ids=arm_advance_left_ids,
    )
    issues.extend(arm_issues)
    local_arm_candidates = _build_local_arm_candidates(
        dataset=loaded.dataset,
        junction_id=junction_id,
        current_group_id=resolved_junction_id,
        current_member_node_ids=member_set,
        seed_roads=seed_roads,
        assigned_traces=assigned_traces,
        nodes=loaded.nodes,
        roads=loaded.roads,
        excluded_road_ids=set(excluded_right_turn_ids),
        internal_road_ids=set(internal_road_ids),
        right_turn_formway_values=right_turn_formway_values,
    )
    preliminary_final_arms = _build_final_arms(initial_arms, local_arm_candidates)
    initial_to_final = _initial_to_final_arm_id(preliminary_final_arms)
    advance_right_turn_relations, relation_issues = build_advance_right_turn_relations(
        dataset=loaded.dataset,
        junction_id=junction_id,
        advance_right_turn_road_ids=relation_advance_right_turn_ids,
        current_member_node_ids=member_set,
        roads=loaded.roads,
        nodes=loaded.nodes,
        initial_arms=initial_arms,
        initial_to_final_arm_id=initial_to_final,
    )
    issues.extend(relation_issues)
    initial_arms = _enrich_initial_arms_with_advance_right_relations(
        initial_arms,
        initial_to_final,
        advance_right_turn_relations,
    )
    final_arms = _build_final_arms(initial_arms, local_arm_candidates)
    validation_result = build_final_arm_validation(
        dataset=loaded.dataset,
        junction_id=junction_id,
        current_group_id=resolved_junction_id,
        groups=groups,
        nodes=loaded.nodes,
        roads=loaded.roads,
        initial_arms=initial_arms,
        final_arms=final_arms,
        traces=assigned_traces,
        excluded_road_ids=set(excluded_right_turn_ids),
        internal_road_ids=set(internal_road_ids),
    )
    final_arms = validation_result.final_arms
    issues.extend(validation_result.issues)
    arm_corridor_evidence = build_arm_corridor_evidence(
        dataset=loaded.dataset,
        junction_id=junction_id,
        current_member_node_ids=member_set,
        groups=groups,
        nodes=loaded.nodes,
        roads=loaded.roads,
        final_arms=final_arms,
        local_arm_candidates=local_arm_candidates,
    )
    for arm in initial_arms:
        for road_id in arm.member_road_ids:
            road = loaded.roads.get(road_id)
            if road and is_advance_right_turn_road(road) and road_id not in arm_member_advance_right_turn_ids:
                _add_issue(issues, "advance_right_turn_in_arm_member_error", arm_id=arm.initial_arm_id, road_id=road_id)
        for road_id in arm.trunk_road_ids:
            road = loaded.roads.get(road_id)
            if road and is_advance_left_turn_road(road):
                _add_issue(issues, "advance_left_turn_in_trunk_error", arm_id=arm.initial_arm_id, road_id=road_id)
        if arm.trunk_status in {"partial", "none"}:
            _add_issue(issues, "trunk_min_loop_not_found", arm_id=arm.initial_arm_id, trunk_status=arm.trunk_status)
        if arm.trunk_status == "ambiguous":
            _add_issue(issues, "trunk_min_loop_ambiguous", arm_id=arm.initial_arm_id)
    movement_result = build_movement_outputs(
        dataset=loaded.dataset,
        junction_id=junction_id,
        roads=loaded.roads,
        final_arms=final_arms,
        local_arm_candidates=local_arm_candidates,
        arm_corridor_evidence=arm_corridor_evidence,
        advance_right_turn_relations=advance_right_turn_relations,
        road_next_road_records=road_next_road_records,
        has_road_next_road_input=has_road_next_road_input,
    )
    issues.extend(movement_result.issues)
    issue_counts = dict(Counter(str(issue.get("issue_type")) for issue in issues))
    issue_report = IssueReport(
        dataset=loaded.dataset,
        current_junction_id=junction_id,
        issues=tuple(issues),
        issue_counts=issue_counts,
    )
    metrics = _metrics_for(
        context=context,
        initial_arms=initial_arms,
        final_arms=final_arms,
        validation_metrics=validation_result.metrics,
        arm_corridor_evidence=arm_corridor_evidence,
        advance_right_turn_relation_count=len(advance_right_turn_relations),
        local_arm_candidates=local_arm_candidates,
        traces=assigned_traces,
        decisions=tuple(decisions),
        issue_counts=issue_counts,
    )
    metrics.update(movement_result.metrics)
    return DatasetBuildResult(
        dataset=loaded.dataset,
        junction_id=junction_id,
        context=context,
        initial_arms=initial_arms,
        final_arms=final_arms,
        final_arm_validation=validation_result.validations,
        arm_corridor_evidence=arm_corridor_evidence,
        corrected_final_arms=movement_result.corrected_final_arms,
        advance_right_turn_relations=advance_right_turn_relations,
        road_movement_evidence=movement_result.road_movement_evidence,
        arm_movements=movement_result.arm_movements,
        arm_receiving_road_roles=movement_result.arm_receiving_road_roles,
        trunk_corrections=movement_result.trunk_corrections,
        local_arm_candidates=local_arm_candidates,
        traces=assigned_traces,
        decisions=tuple(decisions),
        issue_report=issue_report,
        review_priority=review_priority_from_metrics(metrics),
        metrics=metrics,
    )
