from __future__ import annotations

from typing import Any, Optional

from . import step2_trunk_utils as _core
from .step2_trunk_utils import (
    DirectedPath,
    KIND2_128_LOCALIZED_SEARCH_MAX_EXPANDED_STATES,
    KIND2_128_LOCALIZED_SEARCH_MAX_FRONTIER_SIZE,
    KIND2_128_LOCALIZED_SEARCH_MIN_NODE_COUNT,
    KIND2_128_LOCALIZED_SEARCH_MIN_PRUNED_ROAD_COUNT,
    KIND2_128_LOCAL_CORRIDOR_TERMINAL_MIN_NODE_COUNT,
    KIND2_128_LOCAL_CORRIDOR_TERMINAL_MIN_ROAD_COUNT,
    PairRecord,
    RoadRecord,
    STEP5C_STRATEGY_ID,
    Step1GraphContext,
    ThroughRuleSpec,
    TrunkCandidate,
    _PathSearchBudget,
    _TrunkEvaluationChoice,
    _best_dual_separation_failure,
    _build_filtered_directed_adjacency,
    _collect_trunk_candidates,
    _dedupe_trunk_candidates,
    _dual_carriageway_separation_m,
    _dual_separation_gate_limit_m,
    _dual_separation_support_info,
    _geometry_length,
    _pair_support_seed_candidates,
    _prefer_bidirectional_minimal_loop_candidates,
    _prefer_pair_support_aligned_minimal_candidates,
    _prefer_same_endpoint_direct_bidirectional_candidates,
    _road_matches_any_formway_bits,
    _road_matches_formway_bit,
    _sort_key,
    _split_bidirectional_minimal_loop_lasso_candidates,
    _split_counterclockwise_mixed_kind_wedge_candidates,
    _split_dual_separation_candidates,
    _split_internal_turn_angle_candidates,
    _split_pair_support_near_gate_candidates,
    internal_turn_angle_gate_info,
)


def _enumerate_simple_paths(*args: Any, **kwargs: Any):
    return _core._enumerate_simple_paths(*args, **kwargs)


def _split_tjunction_vertical_tracking_candidates(*args: Any, **kwargs: Any):
    return _core._split_tjunction_vertical_tracking_candidates(*args, **kwargs)

def _kind_2_128_localized_search_enabled(
    pair: PairRecord,
    *,
    pruned_road_ids: set[str],
) -> bool:
    return (
        len(pair.kind_2_128_node_ids) >= KIND2_128_LOCALIZED_SEARCH_MIN_NODE_COUNT
        and len(pruned_road_ids) >= KIND2_128_LOCALIZED_SEARCH_MIN_PRUNED_ROAD_COUNT
    )

def _new_kind_2_128_search_budget(phase: str, *, enabled: bool) -> Optional[_PathSearchBudget]:
    if not enabled:
        return None
    return _PathSearchBudget(
        phase=phase,
        max_expanded_states=KIND2_128_LOCALIZED_SEARCH_MAX_EXPANDED_STATES,
        max_frontier_size=KIND2_128_LOCALIZED_SEARCH_MAX_FRONTIER_SIZE,
    )


def _trunk_search_budget_audit(
    *,
    pair: PairRecord,
    candidate_road_ids: set[str],
    pruned_road_ids: set[str],
    budgets: tuple[Optional[_PathSearchBudget], ...],
    localized_search_enabled: bool,
) -> Optional[dict[str, Any]]:
    budget_records: list[dict[str, Any]] = []
    exhausted = False
    for budget in budgets:
        if budget is None:
            continue
        exhausted = exhausted or budget.exhausted
        budget_records.append(
            {
                "phase": budget.phase,
                "expanded_states": budget.expanded_states,
                "max_expanded_states": budget.max_expanded_states,
                "max_frontier_size": budget.max_frontier_size,
                "max_observed_frontier_size": budget.max_observed_frontier_size,
                "exhausted": budget.exhausted,
                "exhausted_reason": budget.exhausted_reason,
            }
        )

    if not exhausted:
        return None

    return {
        "trunk_search_budget_exceeded": True,
        "kind_2_128_localized_search_enabled": localized_search_enabled,
        "kind_2_128_localized_search_min_node_count": KIND2_128_LOCALIZED_SEARCH_MIN_NODE_COUNT,
        "kind_2_128_localized_search_min_pruned_road_count": (
            KIND2_128_LOCALIZED_SEARCH_MIN_PRUNED_ROAD_COUNT
        ),
        "kind_2_128_count": len(pair.kind_2_128_node_ids),
        "candidate_road_count": len(candidate_road_ids),
        "pruned_road_count": len(pruned_road_ids),
        "path_search_budgets": budget_records,
    }


def _pair_support_directed_path(
    *,
    node_ids: tuple[str, ...],
    road_ids: tuple[str, ...],
    roads: dict[str, RoadRecord],
) -> Optional[DirectedPath]:
    if len(node_ids) != len(road_ids) + 1:
        return None
    total_length = 0.0
    for road_id in road_ids:
        road = roads.get(road_id)
        if road is None:
            return None
        total_length += _geometry_length(road.geometry)
    return DirectedPath(node_ids=node_ids, road_ids=road_ids, total_length=total_length)


def _kind_2_128_local_corridor_support_info(candidate: TrunkCandidate) -> dict[str, Any]:
    return {
        **_dual_separation_support_info(candidate),
        "kind_2_128_local_corridor": True,
        "kind_2_128_local_corridor_road_count": len(candidate.road_ids),
        "kind_2_128_local_corridor_forward_road_count": len(candidate.forward_path.road_ids),
        "kind_2_128_local_corridor_reverse_road_count": len(candidate.reverse_path.road_ids),
    }


def _kind_2_128_local_corridor_is_terminal(pair: PairRecord, candidate: TrunkCandidate) -> bool:
    return (
        len(pair.kind_2_128_node_ids) >= KIND2_128_LOCAL_CORRIDOR_TERMINAL_MIN_NODE_COUNT
        and len(candidate.road_ids) >= KIND2_128_LOCAL_CORRIDOR_TERMINAL_MIN_ROAD_COUNT
    )


def _evaluate_kind_2_128_local_corridor(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    pruned_road_ids: set[str],
    formway_mode: str,
    left_turn_formway_bit: int,
) -> tuple[Optional[TrunkCandidate], tuple[str, ...]]:
    if not pair.kind_2_128_node_ids:
        return None, ()

    support_road_ids = tuple(sorted(set(pair.forward_path_road_ids + pair.reverse_path_road_ids), key=_sort_key))
    if not support_road_ids:
        return None, ()
    if any(road_id not in pruned_road_ids for road_id in support_road_ids):
        return None, ()

    forward_path = _pair_support_directed_path(
        node_ids=tuple(pair.forward_path_node_ids),
        road_ids=tuple(pair.forward_path_road_ids),
        roads=context.roads,
    )
    reverse_path = _pair_support_directed_path(
        node_ids=tuple(pair.reverse_path_node_ids),
        road_ids=tuple(pair.reverse_path_road_ids),
        roads=context.roads,
    )
    if forward_path is None or reverse_path is None:
        return None, ()

    left_turn_road_ids = tuple(
        road_id for road_id in support_road_ids if _road_matches_formway_bit(context.roads[road_id], left_turn_formway_bit)
    )
    warnings: tuple[str, ...] = ()
    if formway_mode == "audit_only" and left_turn_road_ids:
        warnings = ("formway_unreliable_warning",)

    return (
        TrunkCandidate(
            forward_path=forward_path,
            reverse_path=reverse_path,
            road_ids=support_road_ids,
            signed_area=0.0,
            total_length=forward_path.total_length + reverse_path.total_length,
            left_turn_road_ids=left_turn_road_ids,
            max_dual_carriageway_separation_m=_dual_carriageway_separation_m(
                forward_path=forward_path,
                reverse_path=reverse_path,
                roads=context.roads,
            ),
            is_kind2_128_local_corridor=True,
        ),
        warnings,
    )


def _evaluate_kind_2_128_local_corridor_choices(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    pruned_road_ids: set[str],
    formway_mode: str,
    left_turn_formway_bit: int,
) -> Optional[tuple[list[_TrunkEvaluationChoice], Optional[str], tuple[str, ...], dict[str, Any]]]:
    candidate, warnings = _evaluate_kind_2_128_local_corridor(
        pair,
        context=context,
        pruned_road_ids=pruned_road_ids,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
    )
    if candidate is None:
        return None

    dual_gate_limit_m = _dual_separation_gate_limit_m(pair, context)
    terminal_local_corridor = _kind_2_128_local_corridor_is_terminal(pair, candidate)
    support_info = {
        **_kind_2_128_local_corridor_support_info(candidate),
        **_dual_separation_support_info(candidate, gate_limit_m=dual_gate_limit_m),
        "kind_2_128_local_corridor_terminal": terminal_local_corridor,
        "kind_2_128_local_corridor_terminal_min_node_count": (
            KIND2_128_LOCAL_CORRIDOR_TERMINAL_MIN_NODE_COUNT
        ),
        "kind_2_128_local_corridor_terminal_min_road_count": (
            KIND2_128_LOCAL_CORRIDOR_TERMINAL_MIN_ROAD_COUNT
        ),
    }
    if formway_mode == "strict" and candidate.left_turn_road_ids:
        if not terminal_local_corridor:
            return None
        return [], "left_turn_only_polluted_trunk", (), {
            **support_info,
            "left_turn_road_ids": list(candidate.left_turn_road_ids),
        }

    passed_candidates, failed_candidates = _split_dual_separation_candidates(
        [candidate],
        gate_limit_m=dual_gate_limit_m,
    )
    passed_candidates, tjunction_blocked = _split_tjunction_vertical_tracking_candidates(
        pair,
        candidates=passed_candidates,
        context=context,
    )
    passed_candidates, lasso_blocked = _split_bidirectional_minimal_loop_lasso_candidates(
        pair,
        candidates=passed_candidates,
    )
    passed_candidates, mixed_kind_wedge_blocked = _split_counterclockwise_mixed_kind_wedge_candidates(
        pair,
        candidates=passed_candidates,
        context=context,
    )
    passed_candidates, internal_turn_blocked = _split_internal_turn_angle_candidates(
        candidates=passed_candidates,
        context=context,
        road_endpoints={road_id: (road.snodeid, road.enodeid) for road_id, road in context.roads.items()},
        exclude_formway_bits_any=(),
    )
    if passed_candidates:
        choice = _TrunkEvaluationChoice(
            candidate=passed_candidates[0],
            warning_codes=warnings,
            support_info=support_info,
        )
        return [choice], None, warnings, support_info
    if tjunction_blocked:
        if not terminal_local_corridor:
            return None
        return [], "t_junction_vertical_tracking", (), {
            **support_info,
            **tjunction_blocked[0][1],
        }
    if lasso_blocked:
        if not terminal_local_corridor:
            return None
        return [], "bidirectional_minimal_loop_lasso", (), {
            **support_info,
            **lasso_blocked[0][1],
        }
    if mixed_kind_wedge_blocked:
        if not terminal_local_corridor:
            return None
        return [], "counterclockwise_mixed_kind_wedge", (), {
            **support_info,
            **mixed_kind_wedge_blocked[0][1],
        }
    if internal_turn_blocked:
        if not terminal_local_corridor:
            return None
        return [], "internal_turn_angle_conflict", (), {
            **support_info,
            **internal_turn_blocked[0][1],
        }
    if failed_candidates:
        if not terminal_local_corridor:
            return None
        return [], "dual_carriageway_separation_exceeded", (), support_info
    return [], "no_valid_trunk", (), support_info


def _evaluate_trunk_choices(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    candidate_road_ids: set[str],
    pruned_road_ids: set[str],
    branch_cut_infos: list[dict[str, Any]],
    road_endpoints: dict[str, tuple[str, str]],
    through_rule: ThroughRuleSpec,
    formway_mode: str,
    left_turn_formway_bit: int,
) -> tuple[list[_TrunkEvaluationChoice], Optional[str], tuple[str, ...], dict[str, Any]]:
    dual_gate_limit_m = _dual_separation_gate_limit_m(pair, context)
    collapsed_candidate: Optional[TrunkCandidate] = None
    collapsed_warnings: tuple[str, ...] = ()
    collapsed_failed_candidate: Optional[TrunkCandidate] = None
    if pair.through_node_ids:
        collapsed_candidate, collapsed_warnings = _evaluate_through_collapsed_corridor(
            pair,
            context=context,
            pruned_road_ids=pruned_road_ids,
            road_endpoints=road_endpoints,
            through_rule=through_rule,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
        )
        if (
            collapsed_candidate is not None
            and collapsed_candidate.max_dual_carriageway_separation_m > dual_gate_limit_m
        ):
            collapsed_failed_candidate = collapsed_candidate
            collapsed_candidate = None
            collapsed_warnings = ("dual_carriageway_separation_exceeded",)
    mirrored_candidate: Optional[TrunkCandidate] = None
    mirrored_warnings: tuple[str, ...] = ()
    if collapsed_candidate is None:
        mirrored_candidate, mirrored_warnings = _evaluate_step5c_mirrored_one_sided_corridor(
            pair,
            context=context,
            pruned_road_ids=pruned_road_ids,
            road_endpoints=road_endpoints,
            through_rule=through_rule,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
        )

    if collapsed_candidate is not None:
        collapsed_turn_gate = internal_turn_angle_gate_info(
            collapsed_candidate,
            context=context,
            road_endpoints=road_endpoints,
            exclude_formway_bits_any=through_rule.incident_degree_exclude_formway_bits_any,
        )
        if collapsed_turn_gate is not None:
            return [], "internal_turn_angle_conflict", (), {
                **_dual_separation_support_info(collapsed_candidate, gate_limit_m=dual_gate_limit_m),
                **collapsed_turn_gate,
            }
        return [
            _TrunkEvaluationChoice(
                candidate=collapsed_candidate,
                warning_codes=collapsed_warnings,
                support_info=_dual_separation_support_info(collapsed_candidate, gate_limit_m=dual_gate_limit_m),
            )
        ], None, collapsed_warnings, _dual_separation_support_info(
            collapsed_candidate,
            gate_limit_m=dual_gate_limit_m,
        )
    if mirrored_candidate is not None:
        mirrored_turn_gate = internal_turn_angle_gate_info(
            mirrored_candidate,
            context=context,
            road_endpoints=road_endpoints,
            exclude_formway_bits_any=through_rule.incident_degree_exclude_formway_bits_any,
        )
        if mirrored_turn_gate is not None:
            return [], "internal_turn_angle_conflict", (), {
                **_dual_separation_support_info(mirrored_candidate, gate_limit_m=dual_gate_limit_m),
                **mirrored_turn_gate,
            }
        return [
            _TrunkEvaluationChoice(
                candidate=mirrored_candidate,
                warning_codes=mirrored_warnings,
                support_info=_dual_separation_support_info(mirrored_candidate, gate_limit_m=dual_gate_limit_m),
            )
        ], None, mirrored_warnings, _dual_separation_support_info(
            mirrored_candidate,
            gate_limit_m=dual_gate_limit_m,
        )

    kind2_128_local_corridor_result = _evaluate_kind_2_128_local_corridor_choices(
        pair,
        context=context,
        pruned_road_ids=pruned_road_ids,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
    )
    if kind2_128_local_corridor_result is not None:
        return kind2_128_local_corridor_result

    localized_search_enabled = _kind_2_128_localized_search_enabled(
        pair,
        pruned_road_ids=pruned_road_ids,
    )
    base_forward_budget = _new_kind_2_128_search_budget(
        "base_forward_paths",
        enabled=localized_search_enabled,
    )
    base_reverse_budget = _new_kind_2_128_search_budget(
        "base_reverse_paths",
        enabled=localized_search_enabled,
    )
    base_adjacency = _build_filtered_directed_adjacency(
        context.roads,
        road_endpoints=road_endpoints,
        allowed_road_ids=pruned_road_ids,
        exclude_left_turn=False,
        left_turn_formway_bit=left_turn_formway_bit,
        exclude_formway_bits_any=through_rule.incident_degree_exclude_formway_bits_any,
    )
    base_forward_paths = _enumerate_simple_paths(
        adjacency=base_adjacency,
        roads=context.roads,
        start_node_id=pair.a_node_id,
        end_node_id=pair.b_node_id,
        physical_to_semantic=context.physical_to_semantic,
        budget=base_forward_budget,
    )
    base_reverse_paths = _enumerate_simple_paths(
        adjacency=base_adjacency,
        roads=context.roads,
        start_node_id=pair.b_node_id,
        end_node_id=pair.a_node_id,
        physical_to_semantic=context.physical_to_semantic,
        budget=base_reverse_budget,
    )
    base_candidates, base_clockwise_only = _collect_trunk_candidates(
        forward_paths=base_forward_paths,
        reverse_paths=base_reverse_paths,
        roads=context.roads,
        road_endpoints=road_endpoints,
        left_turn_formway_bit=left_turn_formway_bit,
        allow_bidirectional_overlap=True,
    )
    base_candidates = _dedupe_trunk_candidates(
        _pair_support_seed_candidates(
            pair,
            context=context,
            roads=context.roads,
            road_endpoints=road_endpoints,
            pruned_road_ids=pruned_road_ids,
            left_turn_formway_bit=left_turn_formway_bit,
        )
        + base_candidates
    )

    if formway_mode == "strict":
        strict_forward_budget = _new_kind_2_128_search_budget(
            "strict_forward_paths",
            enabled=localized_search_enabled,
        )
        strict_reverse_budget = _new_kind_2_128_search_budget(
            "strict_reverse_paths",
            enabled=localized_search_enabled,
        )
        strict_adjacency = _build_filtered_directed_adjacency(
            context.roads,
            road_endpoints=road_endpoints,
            allowed_road_ids=pruned_road_ids,
            exclude_left_turn=True,
            left_turn_formway_bit=left_turn_formway_bit,
            exclude_formway_bits_any=through_rule.incident_degree_exclude_formway_bits_any,
        )
        strict_forward_paths = _enumerate_simple_paths(
            adjacency=strict_adjacency,
            roads=context.roads,
            start_node_id=pair.a_node_id,
            end_node_id=pair.b_node_id,
            physical_to_semantic=context.physical_to_semantic,
            budget=strict_forward_budget,
        )
        strict_reverse_paths = _enumerate_simple_paths(
            adjacency=strict_adjacency,
            roads=context.roads,
            start_node_id=pair.b_node_id,
            end_node_id=pair.a_node_id,
            physical_to_semantic=context.physical_to_semantic,
            budget=strict_reverse_budget,
        )
        strict_candidates, strict_clockwise_only = _collect_trunk_candidates(
            forward_paths=strict_forward_paths,
            reverse_paths=strict_reverse_paths,
            roads=context.roads,
            road_endpoints=road_endpoints,
            left_turn_formway_bit=left_turn_formway_bit,
            allow_bidirectional_overlap=True,
        )
        strict_candidates = _dedupe_trunk_candidates(
            _pair_support_seed_candidates(
                pair,
                context=context,
                roads=context.roads,
                road_endpoints=road_endpoints,
                pruned_road_ids=pruned_road_ids,
                left_turn_formway_bit=left_turn_formway_bit,
            )
            + strict_candidates
        )
        strict_passed_candidates, strict_failed_candidates = _split_dual_separation_candidates(
            strict_candidates,
            gate_limit_m=dual_gate_limit_m,
        )
        base_passed_candidates, base_failed_candidates = _split_dual_separation_candidates(
            base_candidates,
            gate_limit_m=dual_gate_limit_m,
        )
        strict_near_gate_candidates, strict_failed_candidates = _split_pair_support_near_gate_candidates(
            pair, strict_failed_candidates, gate_limit_m=dual_gate_limit_m
        )
        base_near_gate_candidates, base_failed_candidates = _split_pair_support_near_gate_candidates(
            pair, base_failed_candidates, gate_limit_m=dual_gate_limit_m
        )
        strict_passed_candidates += strict_near_gate_candidates
        base_passed_candidates += base_near_gate_candidates
        strict_passed_candidates = _prefer_same_endpoint_direct_bidirectional_candidates(
            pair,
            candidates=strict_passed_candidates,
            roads=context.roads,
        )
        strict_passed_candidates = _prefer_pair_support_aligned_minimal_candidates(
            pair,
            candidates=strict_passed_candidates,
        )
        base_passed_candidates = _prefer_same_endpoint_direct_bidirectional_candidates(
            pair,
            candidates=base_passed_candidates,
            roads=context.roads,
        )
        base_passed_candidates = _prefer_pair_support_aligned_minimal_candidates(
            pair,
            candidates=base_passed_candidates,
        )
        strict_passed_candidates = _prefer_bidirectional_minimal_loop_candidates(strict_passed_candidates)
        base_passed_candidates = _prefer_bidirectional_minimal_loop_candidates(base_passed_candidates)
        strict_passed_candidates, strict_tjunction_blocked = _split_tjunction_vertical_tracking_candidates(
            pair,
            candidates=strict_passed_candidates,
            context=context,
        )
        base_passed_candidates, base_tjunction_blocked = _split_tjunction_vertical_tracking_candidates(
            pair,
            candidates=base_passed_candidates,
            context=context,
        )
        strict_passed_candidates, strict_lasso_blocked = _split_bidirectional_minimal_loop_lasso_candidates(
            pair,
            candidates=strict_passed_candidates,
        )
        base_passed_candidates, base_lasso_blocked = _split_bidirectional_minimal_loop_lasso_candidates(
            pair,
            candidates=base_passed_candidates,
        )
        strict_passed_candidates, strict_mixed_kind_wedge_blocked = _split_counterclockwise_mixed_kind_wedge_candidates(
            pair,
            candidates=strict_passed_candidates,
            context=context,
        )
        base_passed_candidates, base_mixed_kind_wedge_blocked = _split_counterclockwise_mixed_kind_wedge_candidates(
            pair,
            candidates=base_passed_candidates,
            context=context,
        )
        strict_passed_candidates, strict_internal_turn_blocked = _split_internal_turn_angle_candidates(
            candidates=strict_passed_candidates,
            context=context,
            road_endpoints=road_endpoints,
            exclude_formway_bits_any=through_rule.incident_degree_exclude_formway_bits_any,
        )
        base_passed_candidates, base_internal_turn_blocked = _split_internal_turn_angle_candidates(
            candidates=base_passed_candidates,
            context=context,
            road_endpoints=road_endpoints,
            exclude_formway_bits_any=through_rule.incident_degree_exclude_formway_bits_any,
        )
        if strict_passed_candidates:
            choices = [
                _TrunkEvaluationChoice(
                    candidate=candidate,
                    warning_codes=(),
                    support_info=_dual_separation_support_info(candidate, gate_limit_m=dual_gate_limit_m),
                )
                for candidate in strict_passed_candidates
            ]
            return choices, None, (), choices[0].support_info
        budget_audit = _trunk_search_budget_audit(
            pair=pair,
            candidate_road_ids=candidate_road_ids,
            pruned_road_ids=pruned_road_ids,
            budgets=(base_forward_budget, base_reverse_budget, strict_forward_budget, strict_reverse_budget),
            localized_search_enabled=localized_search_enabled,
        )
        if budget_audit is not None:
            return [], "trunk_search_budget_exceeded", (), {
                **_dual_separation_support_info(None, gate_limit_m=dual_gate_limit_m),
                **budget_audit,
            }
        if base_passed_candidates:
            return [], "left_turn_only_polluted_trunk", (), _dual_separation_support_info(
                base_passed_candidates[0],
                gate_limit_m=dual_gate_limit_m,
            )
        if strict_tjunction_blocked or base_tjunction_blocked:
            support_info = (strict_tjunction_blocked or base_tjunction_blocked)[0][1]
            return [], "t_junction_vertical_tracking", (), support_info
        if strict_lasso_blocked or base_lasso_blocked:
            support_info = (strict_lasso_blocked or base_lasso_blocked)[0][1]
            return [], "bidirectional_minimal_loop_lasso", (), support_info
        if strict_mixed_kind_wedge_blocked or base_mixed_kind_wedge_blocked:
            support_info = (strict_mixed_kind_wedge_blocked or base_mixed_kind_wedge_blocked)[0][1]
            return [], "counterclockwise_mixed_kind_wedge", (), support_info
        if strict_internal_turn_blocked or base_internal_turn_blocked:
            support_info = (strict_internal_turn_blocked or base_internal_turn_blocked)[0][1]
            return [], "internal_turn_angle_conflict", (), support_info
        if strict_failed_candidates or base_failed_candidates or collapsed_failed_candidate is not None:
            failure_candidate = _best_dual_separation_failure(
                strict_failed_candidates
                or base_failed_candidates
                or ([collapsed_failed_candidate] if collapsed_failed_candidate else [])
            )
            return [], "dual_carriageway_separation_exceeded", (), _dual_separation_support_info(
                failure_candidate,
                gate_limit_m=dual_gate_limit_m,
            )
        if strict_clockwise_only or base_clockwise_only:
            return [], "only_clockwise_loop", (), _dual_separation_support_info(
                None,
                gate_limit_m=dual_gate_limit_m,
            )
        return [], "no_valid_trunk", (), _dual_separation_support_info(None, gate_limit_m=dual_gate_limit_m)

    base_passed_candidates, base_failed_candidates = _split_dual_separation_candidates(
        base_candidates,
        gate_limit_m=dual_gate_limit_m,
    )
    base_near_gate_candidates, base_failed_candidates = _split_pair_support_near_gate_candidates(
        pair, base_failed_candidates, gate_limit_m=dual_gate_limit_m
    )
    base_passed_candidates += base_near_gate_candidates
    base_passed_candidates = _prefer_same_endpoint_direct_bidirectional_candidates(
        pair,
        candidates=base_passed_candidates,
        roads=context.roads,
    )
    base_passed_candidates = _prefer_pair_support_aligned_minimal_candidates(
        pair,
        candidates=base_passed_candidates,
    )
    base_passed_candidates = _prefer_bidirectional_minimal_loop_candidates(base_passed_candidates)
    base_passed_candidates, base_tjunction_blocked = _split_tjunction_vertical_tracking_candidates(
        pair,
        candidates=base_passed_candidates,
        context=context,
    )
    base_passed_candidates, base_lasso_blocked = _split_bidirectional_minimal_loop_lasso_candidates(
        pair,
        candidates=base_passed_candidates,
    )
    base_passed_candidates, base_mixed_kind_wedge_blocked = _split_counterclockwise_mixed_kind_wedge_candidates(
        pair,
        candidates=base_passed_candidates,
        context=context,
    )
    base_passed_candidates, base_internal_turn_blocked = _split_internal_turn_angle_candidates(
        candidates=base_passed_candidates,
        context=context,
        road_endpoints=road_endpoints,
        exclude_formway_bits_any=through_rule.incident_degree_exclude_formway_bits_any,
    )
    if not base_passed_candidates:
        budget_audit = _trunk_search_budget_audit(
            pair=pair,
            candidate_road_ids=candidate_road_ids,
            pruned_road_ids=pruned_road_ids,
            budgets=(base_forward_budget, base_reverse_budget),
            localized_search_enabled=localized_search_enabled,
        )
        if budget_audit is not None:
            return [], "trunk_search_budget_exceeded", (), {
                **_dual_separation_support_info(None, gate_limit_m=dual_gate_limit_m),
                **budget_audit,
            }
        if base_tjunction_blocked:
            return [], "t_junction_vertical_tracking", (), base_tjunction_blocked[0][1]
        if base_lasso_blocked:
            return [], "bidirectional_minimal_loop_lasso", (), base_lasso_blocked[0][1]
        if base_mixed_kind_wedge_blocked:
            return [], "counterclockwise_mixed_kind_wedge", (), base_mixed_kind_wedge_blocked[0][1]
        if base_internal_turn_blocked:
            return [], "internal_turn_angle_conflict", (), base_internal_turn_blocked[0][1]
        if base_failed_candidates or collapsed_failed_candidate is not None:
            failure_candidate = _best_dual_separation_failure(
                base_failed_candidates or ([collapsed_failed_candidate] if collapsed_failed_candidate else [])
            )
            return [], "dual_carriageway_separation_exceeded", (), _dual_separation_support_info(
                failure_candidate,
                gate_limit_m=dual_gate_limit_m,
            )
        if base_clockwise_only:
            return [], "only_clockwise_loop", (), _dual_separation_support_info(None, gate_limit_m=dual_gate_limit_m)
        return [], "no_valid_trunk", (), _dual_separation_support_info(None, gate_limit_m=dual_gate_limit_m)

    warnings: tuple[str, ...] = ()
    choices = [
        _TrunkEvaluationChoice(
            candidate=candidate,
            warning_codes=("formway_unreliable_warning",) if formway_mode == "audit_only" and candidate.left_turn_road_ids else (),
            support_info=_dual_separation_support_info(candidate, gate_limit_m=dual_gate_limit_m),
        )
        for candidate in base_passed_candidates
    ]
    if choices:
        warnings = choices[0].warning_codes
    return choices, None, warnings, choices[0].support_info


def _evaluate_trunk(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    candidate_road_ids: set[str],
    pruned_road_ids: set[str],
    branch_cut_infos: list[dict[str, Any]],
    road_endpoints: dict[str, tuple[str, str]],
    through_rule: ThroughRuleSpec,
    formway_mode: str,
    left_turn_formway_bit: int,
) -> tuple[Optional[TrunkCandidate], Optional[str], tuple[str, ...], dict[str, Any]]:
    choices, reject_reason, warning_codes, support_info = _evaluate_trunk_choices(
        pair,
        context=context,
        candidate_road_ids=candidate_road_ids,
        pruned_road_ids=pruned_road_ids,
        branch_cut_infos=branch_cut_infos,
        road_endpoints=road_endpoints,
        through_rule=through_rule,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
    )
    if not choices:
        return None, reject_reason, warning_codes, support_info
    first_choice = choices[0]
    return first_choice.candidate, reject_reason, first_choice.warning_codes, first_choice.support_info


def _alternative_trunk_only_road_ids(
    trunk_choices: list[_TrunkEvaluationChoice],
    *,
    current_choice_index: int,
) -> set[str]:
    if len(trunk_choices) <= 1:
        return set()
    current_road_ids = set(trunk_choices[current_choice_index].candidate.road_ids)
    alternative_road_ids: set[str] = set()
    for index, choice in enumerate(trunk_choices):
        if index == current_choice_index:
            continue
        alternative_road_ids.update(choice.candidate.road_ids)
    return alternative_road_ids - current_road_ids


def _evaluate_through_collapsed_corridor(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    pruned_road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
    through_rule: ThroughRuleSpec,
    formway_mode: str,
    left_turn_formway_bit: int,
) -> tuple[Optional[TrunkCandidate], tuple[str, ...]]:
    if not pair.through_node_ids:
        return None, ()
    if through_rule.incident_road_degree_eq is None:
        return None, ()

    support_road_ids = tuple(sorted(set(pair.forward_path_road_ids + pair.reverse_path_road_ids), key=_sort_key))
    if not support_road_ids:
        return None, ()
    if any(road_id not in pruned_road_ids for road_id in support_road_ids):
        return None, ()
    if pair.forward_path_node_ids != tuple(reversed(pair.reverse_path_node_ids)):
        return None, ()
    if pair.forward_path_road_ids != tuple(reversed(pair.reverse_path_road_ids)):
        return None, ()

    for node_id in pair.through_node_ids:
        retained_degree = 0
        for road_id in pruned_road_ids:
            endpoints = road_endpoints.get(road_id)
            if endpoints is None or node_id not in endpoints:
                continue
            road = context.roads[road_id]
            if _road_matches_any_formway_bits(road, through_rule.incident_degree_exclude_formway_bits_any):
                continue
            retained_degree += 1
        if retained_degree != through_rule.incident_road_degree_eq:
            return None, ()

    if formway_mode == "strict":
        if any(_road_matches_formway_bit(context.roads[road_id], left_turn_formway_bit) for road_id in support_road_ids):
            return None, ()
        filtered_support_road_ids = support_road_ids
        warnings: tuple[str, ...] = ()
    else:
        filtered_support_road_ids = support_road_ids
        warnings = ()
        if formway_mode == "audit_only" and any(
            _road_matches_formway_bit(context.roads[road_id], left_turn_formway_bit) for road_id in support_road_ids
        ):
            warnings = ("formway_unreliable_warning",)

    support_adjacency = _build_filtered_directed_adjacency(
        context.roads,
        road_endpoints=road_endpoints,
        allowed_road_ids=set(filtered_support_road_ids),
        exclude_left_turn=formway_mode == "strict",
        left_turn_formway_bit=left_turn_formway_bit,
        exclude_formway_bits_any=through_rule.incident_degree_exclude_formway_bits_any,
    )
    forward_paths = _enumerate_simple_paths(
        adjacency=support_adjacency,
        roads=context.roads,
        start_node_id=pair.a_node_id,
        end_node_id=pair.b_node_id,
        physical_to_semantic=context.physical_to_semantic,
        max_paths=1,
        max_depth=max(4, len(pair.forward_path_node_ids) + 1),
    )
    reverse_paths = _enumerate_simple_paths(
        adjacency=support_adjacency,
        roads=context.roads,
        start_node_id=pair.b_node_id,
        end_node_id=pair.a_node_id,
        physical_to_semantic=context.physical_to_semantic,
        max_paths=1,
        max_depth=max(4, len(pair.reverse_path_node_ids) + 1),
    )
    if not forward_paths or not reverse_paths:
        return None, ()

    forward_path = forward_paths[0]
    reverse_path = reverse_paths[0]
    if tuple(sorted(set(forward_path.road_ids + reverse_path.road_ids), key=_sort_key)) != support_road_ids:
        return None, ()

    return (
        TrunkCandidate(
            forward_path=forward_path,
            reverse_path=reverse_path,
            road_ids=support_road_ids,
            signed_area=0.0,
            total_length=forward_path.total_length + reverse_path.total_length,
            left_turn_road_ids=tuple(
                road_id
                for road_id in support_road_ids
                if _road_matches_formway_bit(context.roads[road_id], left_turn_formway_bit)
            ),
            max_dual_carriageway_separation_m=0.0,
            is_through_collapsed_corridor=True,
        ),
        warnings,
    )


def _evaluate_step5c_mirrored_one_sided_corridor(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    pruned_road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
    through_rule: ThroughRuleSpec,
    formway_mode: str,
    left_turn_formway_bit: int,
) -> tuple[Optional[TrunkCandidate], tuple[str, ...]]:
    if pair.strategy_id != STEP5C_STRATEGY_ID:
        return None, ()
    if not pair.used_mirrored_reverse_confirm_fallback:
        return None, ()
    if not pair.through_node_ids:
        return None, ()
    if through_rule.incident_road_degree_eq is None:
        return None, ()

    support_road_ids = tuple(sorted(set(pair.forward_path_road_ids + pair.reverse_path_road_ids), key=_sort_key))
    if not support_road_ids:
        return None, ()
    if any(road_id not in pruned_road_ids for road_id in support_road_ids):
        return None, ()
    if pair.forward_path_node_ids != tuple(reversed(pair.reverse_path_node_ids)):
        return None, ()
    if pair.forward_path_road_ids != tuple(reversed(pair.reverse_path_road_ids)):
        return None, ()

    for node_id in pair.through_node_ids:
        retained_degree = 0
        for road_id in pruned_road_ids:
            endpoints = road_endpoints.get(road_id)
            if endpoints is None or node_id not in endpoints:
                continue
            road = context.roads[road_id]
            if _road_matches_any_formway_bits(road, through_rule.incident_degree_exclude_formway_bits_any):
                continue
            retained_degree += 1
        if retained_degree != through_rule.incident_road_degree_eq:
            return None, ()

    if formway_mode == "strict":
        if any(_road_matches_formway_bit(context.roads[road_id], left_turn_formway_bit) for road_id in support_road_ids):
            return None, ()
        filtered_support_road_ids = support_road_ids
        warnings: tuple[str, ...] = ()
    else:
        filtered_support_road_ids = support_road_ids
        warnings = ()
        if formway_mode == "audit_only" and any(
            _road_matches_formway_bit(context.roads[road_id], left_turn_formway_bit) for road_id in support_road_ids
        ):
            warnings = ("formway_unreliable_warning",)

    support_adjacency = _build_filtered_directed_adjacency(
        context.roads,
        road_endpoints=road_endpoints,
        allowed_road_ids=set(filtered_support_road_ids),
        exclude_left_turn=formway_mode == "strict",
        left_turn_formway_bit=left_turn_formway_bit,
        exclude_formway_bits_any=through_rule.incident_degree_exclude_formway_bits_any,
    )
    forward_paths = _enumerate_simple_paths(
        adjacency=support_adjacency,
        roads=context.roads,
        start_node_id=pair.a_node_id,
        end_node_id=pair.b_node_id,
        physical_to_semantic=context.physical_to_semantic,
        max_paths=1,
        max_depth=max(4, len(pair.forward_path_node_ids) + 1),
    )
    reverse_paths = _enumerate_simple_paths(
        adjacency=support_adjacency,
        roads=context.roads,
        start_node_id=pair.b_node_id,
        end_node_id=pair.a_node_id,
        physical_to_semantic=context.physical_to_semantic,
        max_paths=1,
        max_depth=max(4, len(pair.reverse_path_node_ids) + 1),
    )
    if not forward_paths and not reverse_paths:
        return None, ()
    actual_path = forward_paths[0] if forward_paths else reverse_paths[0]
    if tuple(sorted(set(actual_path.road_ids), key=_sort_key)) != support_road_ids:
        return None, ()
    forward_path = DirectedPath(
        node_ids=tuple(pair.forward_path_node_ids),
        road_ids=tuple(pair.forward_path_road_ids),
        total_length=actual_path.total_length,
    )
    reverse_path = DirectedPath(
        node_ids=tuple(pair.reverse_path_node_ids),
        road_ids=tuple(pair.reverse_path_road_ids),
        total_length=actual_path.total_length,
    )

    return (
        TrunkCandidate(
            forward_path=forward_path,
            reverse_path=reverse_path,
            road_ids=support_road_ids,
            signed_area=0.0,
            total_length=forward_path.total_length + reverse_path.total_length,
            left_turn_road_ids=tuple(
                road_id
                for road_id in support_road_ids
                if _road_matches_formway_bit(context.roads[road_id], left_turn_formway_bit)
            ),
            max_dual_carriageway_separation_m=0.0,
            is_mirrored_one_sided_corridor=True,
        ),
        warnings,
    )
