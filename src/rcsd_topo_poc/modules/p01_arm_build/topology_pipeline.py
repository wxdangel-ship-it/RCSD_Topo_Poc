from __future__ import annotations


import math


from collections import Counter, defaultdict


from dataclasses import replace


from typing import Any, Callable


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


from . import topology as _facade


def _add_issue(*args: Any, **kwargs: Any) -> Any:
    return _facade._add_issue(*args, **kwargs)


def _advance_right_turn_enters_current_junction(*args: Any, **kwargs: Any) -> Any:
    return _facade._advance_right_turn_enters_current_junction(*args, **kwargs)


def _build_final_arms(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_final_arms(*args, **kwargs)


def _build_initial_arms(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_initial_arms(*args, **kwargs)


def _build_local_arm_candidates(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_local_arm_candidates(*args, **kwargs)


def _decide_through(*args: Any, **kwargs: Any) -> Any:
    return _facade._decide_through(*args, **kwargs)


def _enrich_initial_arms_with_advance_right_relations(*args: Any, **kwargs: Any) -> Any:
    return _facade._enrich_initial_arms_with_advance_right_relations(*args, **kwargs)


def _enrich_initial_arms_with_trunk(*args: Any, **kwargs: Any) -> Any:
    return _facade._enrich_initial_arms_with_trunk(*args, **kwargs)


def _enrich_traces_with_special_fields(*args: Any, **kwargs: Any) -> Any:
    return _facade._enrich_traces_with_special_fields(*args, **kwargs)


def _incident_active_roads(*args: Any, **kwargs: Any) -> Any:
    return _facade._incident_active_roads(*args, **kwargs)


def _initial_to_final_arm_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._initial_to_final_arm_id(*args, **kwargs)


def _is_right_turn_road(*args: Any, **kwargs: Any) -> Any:
    return _facade._is_right_turn_road(*args, **kwargs)


def _kind_values_for_group(*args: Any, **kwargs: Any) -> Any:
    return _facade._kind_values_for_group(*args, **kwargs)


def _metrics_for(*args: Any, **kwargs: Any) -> Any:
    return _facade._metrics_for(*args, **kwargs)


def _node_ids_for_group(*args: Any, **kwargs: Any) -> Any:
    return _facade._node_ids_for_group(*args, **kwargs)


def _other_group_for_road(*args: Any, **kwargs: Any) -> Any:
    return _facade._other_group_for_road(*args, **kwargs)


def _outside_node_for_seed(*args: Any, **kwargs: Any) -> Any:
    return _facade._outside_node_for_seed(*args, **kwargs)


def build_node_groups(*args: Any, **kwargs: Any) -> Any:
    return _facade.build_node_groups(*args, **kwargs)


def resolve_junction_members(*args: Any, **kwargs: Any) -> Any:
    return _facade.resolve_junction_members(*args, **kwargs)


def review_priority_from_metrics(*args: Any, **kwargs: Any) -> Any:
    return _facade.review_priority_from_metrics(*args, **kwargs)


def seed_role_for_road(*args: Any, **kwargs: Any) -> Any:
    return _facade.seed_role_for_road(*args, **kwargs)


def semantic_group_id(*args: Any, **kwargs: Any) -> Any:
    return _facade.semantic_group_id(*args, **kwargs)


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


def build_dataset_arm_result(
    loaded: LoadedDataset,
    *,
    junction_id: str,
    right_turn_formway_values: set[str],
    road_next_road_records: tuple[RawRoadNextRoad, ...] = tuple(),
    has_road_next_road_input: bool = False,
    progress: Callable[[str], None] | None = None,
) -> DatasetBuildResult:
    def _phase(message: str) -> None:
        if progress is not None:
            progress(message)

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

    for road_id in sorted(road_ids_touching_nodes(loaded.roads, member_set)):
        road = loaded.roads[road_id]
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
    _phase(
        "seed scan done "
        f"members={len(member_node_ids)} seeds={len(seed_roads)} internal={len(internal_road_ids)} "
        f"excluded_rt={len(excluded_right_turn_ids)}"
    )

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

    kind_distribution: dict[str, int] = {}
    for _member_node_id in member_node_ids:
        _node = loaded.nodes.get(_member_node_id)
        _kind_key = "null" if _node is None or _node.kind is None else str(_node.kind)
        kind_distribution[_kind_key] = kind_distribution.get(_kind_key, 0) + 1

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
        kind_distribution=dict(sorted(kind_distribution.items())),
    )

    traces: list[ArmTrace] = []
    decisions: list[ThroughDecisionAudit] = []
    trace_terminals: dict[str, tuple[str | None, tuple[str, ...]]] = {}
    _phase(f"trace start seeds={len(seed_roads)}")
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
    _phase(f"trace done traces={len(traces)} decisions={len(decisions)}")

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
    _phase(f"advance right done relations={len(advance_right_turn_relations)}")
    initial_arms = _enrich_initial_arms_with_advance_right_relations(
        initial_arms,
        initial_to_final,
        advance_right_turn_relations,
    )
    final_arms = _build_final_arms(initial_arms, local_arm_candidates)
    _phase(f"validation start final_arms={len(final_arms)}")
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
    _phase(
        "validation done "
        f"records={len(validation_result.validations)} conflicts={validation_result.metrics.get('final_arm_validation_conflict_count', 0)}"
    )
    _phase("corridor evidence start")
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
    _phase(f"corridor evidence done records={len(arm_corridor_evidence)}")
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
    _phase(f"movement start road_next_road={len(road_next_road_records)}")
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
    _phase(
        "movement done "
        f"evidence={len(movement_result.road_movement_evidence)} "
        f"skipped={movement_result.metrics.get('road_movement_out_of_scope_skipped_count', 0)}"
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
