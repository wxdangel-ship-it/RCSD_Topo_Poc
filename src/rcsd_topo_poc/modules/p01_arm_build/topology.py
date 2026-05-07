from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import replace
from typing import Any

from rcsd_topo_poc.modules.p01_arm_build.io import normalise_id
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
    RoadRecord,
    ThroughDecisionAudit,
)


CONTINUE_STATUSES = {"simple_through", "t_mainline_through"}
RISK_STOP_TYPES = {"ambiguous_boundary", "patch_boundary", "loop_to_current_junction", "unresolved"}
LOCAL_CANDIDATE_ANGLE_TOLERANCE_DEG = 35.0
LOCAL_CANDIDATE_STUB_ANGLE_TOLERANCE_DEG = 25.0
LOCAL_CANDIDATE_STUB_MAX_HOPS = 1


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
) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
    groups, node_to_group = build_node_groups(nodes)
    target = normalise_id(junction_id)
    issues: list[str] = []
    if target in groups:
        return target, groups[target], tuple(issues)
    if target in nodes:
        group_id = node_to_group[target]
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
    return normalise_id(road.formway) in right_turn_formway_values


def _road_endpoint_groups(road: RoadRecord, nodes: dict[str, NodeRecord]) -> tuple[str, str]:
    return semantic_group_id(nodes.get(road.snodeid), road.snodeid), semantic_group_id(nodes.get(road.enodeid), road.enodeid)


def _incident_active_roads(
    *,
    group_id: str,
    roads: dict[str, RoadRecord],
    nodes: dict[str, NodeRecord],
    excluded_road_ids: set[str],
    current_internal_road_ids: set[str],
) -> tuple[str, ...]:
    incident: list[str] = []
    for road_id, road in roads.items():
        if road_id in excluded_road_ids or road_id in current_internal_road_ids:
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


def _local_stub_for_seed(
    *,
    seed_road: RoadRecord,
    base_angle: float,
    current_group_id: str,
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
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

        incident_ids = _incident_active_roads(
            group_id=group_id,
            roads=roads,
            nodes=nodes,
            excluded_road_ids=excluded_road_ids,
            current_internal_road_ids=internal_road_ids,
        )
        next_candidates = [road_id for road_id in incident_ids if road_id != previous_road_id]
        if len(incident_ids) <= 1:
            status = "dead_end"
            reason = "no_continuation_after_seed"
            outgoing_road_id = None
        elif len(incident_ids) == 2 and len(next_candidates) == 1:
            status = "simple_through"
            reason = "semantic_degree_2_passthrough"
            outgoing_road_id = next_candidates[0]
        else:
            status = "ambiguous_boundary" if len(incident_ids) == 3 else "semantic_boundary"
            reason = "t_junction_uncertain" if len(incident_ids) == 3 else "semantic_degree_ge_3_boundary"
            outgoing_road_id = None
            if len(incident_ids) == 3:
                _add_issue(trace_issues, "t_junction_uncertain", trace_id=trace_id, node_group_id=group_id)
                _add_issue(trace_issues, "ambiguous_boundary", trace_id=trace_id, node_group_id=group_id)

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
        risk_flags = tuple(sorted({flag for trace in arm_traces for flag in trace.issue_flags}))
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


def _build_final_arms(initial_arms: tuple[InitialArm, ...]) -> tuple[FinalArm, ...]:
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
                initial_arm={
                    "initial_arm_id": arm.initial_arm_id,
                    "member_road_ids": arm.member_road_ids,
                    "terminal_type": arm.terminal_type,
                    "terminal_junction_id": arm.terminal_junction_id,
                },
            )
        )
    return tuple(final_arms)


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
        )
        seed_items.append(
            {
                "road_id": road.road_id,
                "role": role,
                "angle": angle,
                "node_ids": tuple(sorted(set(node_pair) | set(stub_node_ids))),
                "stub_road_ids": stub_road_ids,
            }
        )

    groups: list[dict[str, Any]] = []
    for item in sorted(seed_items, key=lambda value: (float(value["angle"]), str(value["road_id"]))):
        best_index: int | None = None
        best_distance = LOCAL_CANDIDATE_ANGLE_TOLERANCE_DEG + 1.0
        for index, group in enumerate(groups):
            distance = _angular_distance(float(item["angle"]), float(group["mean_angle"]))
            if distance <= LOCAL_CANDIDATE_ANGLE_TOLERANCE_DEG and distance < best_distance:
                best_index = index
                best_distance = distance
        if best_index is None:
            groups.append({"items": [item], "mean_angle": float(item["angle"])})
        else:
            groups[best_index]["items"].append(item)
            angles = [float(seed_item["angle"]) for seed_item in groups[best_index]["items"]]
            groups[best_index]["mean_angle"] = _mean_angle(angles)

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
                grouping_reason="current_junction_seed_local_trend",
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
    local_arm_candidates: tuple[LocalArmCandidate, ...],
    traces: tuple[ArmTrace, ...],
    decisions: tuple[ThroughDecisionAudit, ...],
    issue_counts: dict[str, int],
) -> dict[str, Any]:
    decision_counts = Counter(decision.status for decision in decisions)
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
        "initial_arm_count": len(initial_arms),
        "final_arm_count": len(final_arms),
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
    ):
        return "P0"
    if (
        metrics["patch_boundary_count"] > 0
        or metrics["dead_end_count"] > 0
        or metrics["excluded_right_turn_road_count"] > max(3, metrics["seed_road_count"])
        or metrics["t_mainline_through_count"] > 4
        or metrics["t_side_terminal_count"] > 4
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
) -> DatasetBuildResult:
    groups, _ = build_node_groups(loaded.nodes)
    resolved_junction_id, member_node_ids, input_flags = resolve_junction_members(loaded.nodes, junction_id=junction_id)
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
    issues.extend(arm_issues)
    final_arms = _build_final_arms(initial_arms)
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
    )
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
        local_arm_candidates=local_arm_candidates,
        traces=assigned_traces,
        decisions=tuple(decisions),
        issue_counts=issue_counts,
    )
    return DatasetBuildResult(
        dataset=loaded.dataset,
        junction_id=junction_id,
        context=context,
        initial_arms=initial_arms,
        final_arms=final_arms,
        local_arm_candidates=local_arm_candidates,
        traces=assigned_traces,
        decisions=tuple(decisions),
        issue_report=issue_report,
        review_priority=review_priority_from_metrics(metrics),
        metrics=metrics,
    )
