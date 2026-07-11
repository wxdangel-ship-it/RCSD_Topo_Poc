from __future__ import annotations

from typing import Any, Optional, Union

from rcsd_topo_poc.modules.t01_data_preprocess import step2_segment_poc as _facade
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    PairRecord,
    Step1GraphContext,
    Step1StrategyExecution,
    TraversalEdge,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_arbitration import (
    PairArbitrationOption,
    PairArbitrationOutcome,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_runtime_utils import Step2ProgressCallback
from rcsd_topo_poc.modules.t01_data_preprocess.step2_validation_utils import PairValidationResult


def _alternative_trunk_only_road_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._alternative_trunk_only_road_ids(*args, **kwargs)


def _arbitration_boundary_node_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._arbitration_boundary_node_ids(*args, **kwargs)


def _arbitration_semantic_conflict_node_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._arbitration_semantic_conflict_node_ids(*args, **kwargs)


def _arbitration_strong_anchor_node_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._arbitration_strong_anchor_node_ids(*args, **kwargs)


def _arbitration_tjunction_anchor_node_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._arbitration_tjunction_anchor_node_ids(*args, **kwargs)


def _arbitration_weak_endpoint_node_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._arbitration_weak_endpoint_node_ids(*args, **kwargs)


def _build_candidate_channel(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_candidate_channel(*args, **kwargs)


def _build_segment_body_candidate_channel(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_segment_body_candidate_channel(*args, **kwargs)


def _collect_internal_boundary_nodes(*args: Any, **kwargs: Any) -> Any:
    return _facade._collect_internal_boundary_nodes(*args, **kwargs)


def _compact_validation_result_for_release(*args: Any, **kwargs: Any) -> Any:
    return _facade._compact_validation_result_for_release(*args, **kwargs)


def _emit_progress(*args: Any, **kwargs: Any) -> Any:
    return _facade._emit_progress(*args, **kwargs)


def _evaluate_trunk_choices(*args: Any, **kwargs: Any) -> Any:
    return _facade._evaluate_trunk_choices(*args, **kwargs)


def _expand_segment_body_allowed_road_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._expand_segment_body_allowed_road_ids(*args, **kwargs)


def _pair_endpoint_priority_grades(*args: Any, **kwargs: Any) -> Any:
    return _facade._pair_endpoint_priority_grades(*args, **kwargs)


def _pair_validation_from_option(*args: Any, **kwargs: Any) -> Any:
    return _facade._pair_validation_from_option(*args, **kwargs)


def _prune_candidate_channel(*args: Any, **kwargs: Any) -> Any:
    return _facade._prune_candidate_channel(*args, **kwargs)


def _refine_segment_roads(*args: Any, **kwargs: Any) -> Any:
    return _facade._refine_segment_roads(*args, **kwargs)


def _road_length_index(*args: Any, **kwargs: Any) -> Any:
    return _facade._road_length_index(*args, **kwargs)


def _road_node_index(*args: Any, **kwargs: Any) -> Any:
    return _facade._road_node_index(*args, **kwargs)


def _single_pair_illegal_validation(*args: Any, **kwargs: Any) -> Any:
    return _facade._single_pair_illegal_validation(*args, **kwargs)


def _sort_key(*args: Any, **kwargs: Any) -> Any:
    return _facade._sort_key(*args, **kwargs)


def _tighten_validated_segment_components(*args: Any, **kwargs: Any) -> Any:
    return _facade._tighten_validated_segment_components(*args, **kwargs)


def _trunk_candidate_counterclockwise_ok(*args: Any, **kwargs: Any) -> Any:
    return _facade._trunk_candidate_counterclockwise_ok(*args, **kwargs)


def _trunk_candidate_mode(*args: Any, **kwargs: Any) -> Any:
    return _facade._trunk_candidate_mode(*args, **kwargs)


def _validation_road_count(*args: Any, **kwargs: Any) -> Any:
    return _facade._validation_road_count(*args, **kwargs)


def _with_pair_kind_2_128_support_info(*args: Any, **kwargs: Any) -> Any:
    return _facade._with_pair_kind_2_128_support_info(*args, **kwargs)


def arbitrate_pair_options(*args: Any, **kwargs: Any) -> Any:
    return _facade.arbitrate_pair_options(*args, **kwargs)


def _validate_pair_candidates(
    execution: Step1StrategyExecution,
    *,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    undirected_adjacency: dict[str, tuple[TraversalEdge, ...]],
    formway_mode: str,
    left_turn_formway_bit: int,
    compact_release_payloads: bool = False,
    progress_callback: Optional[Step2ProgressCallback] = None,
    trace_validation_pair_ids: Optional[set[str]] = None,
    return_arbitration_outcome: bool = False,
) -> Union[list[PairValidationResult], tuple[list[PairValidationResult], PairArbitrationOutcome]]:
    terminate_ids = set(execution.terminate_ids)
    hard_stop_node_ids = set(execution.strategy.hard_stop_node_ids)
    boundary_node_ids = terminate_ids | hard_stop_node_ids
    validation_count = len(execution.pair_candidates)
    road_lengths = _road_length_index(context)
    road_to_node_ids = _road_node_index(road_endpoints)
    arbitration_boundary_node_ids = _arbitration_boundary_node_ids(
        execution,
        hard_stop_node_ids=hard_stop_node_ids,
    )
    weak_endpoint_node_ids = _arbitration_weak_endpoint_node_ids(context)
    semantic_conflict_node_ids = _arbitration_semantic_conflict_node_ids(context)
    strong_anchor_node_ids = _arbitration_strong_anchor_node_ids(context)
    tjunction_anchor_node_ids = _arbitration_tjunction_anchor_node_ids(context)
    trace_pair_ids = set(trace_validation_pair_ids or ())

    _emit_progress(progress_callback, "validation_started", validation_count=validation_count)

    def _emit_validation_pair_phase(
        *,
        pair_index: int,
        pair: PairRecord,
        phase: str,
        checkpoint: bool = False,
        **extra_payload: Any,
    ) -> None:
        payload = {
            "pair_index": pair_index,
            "validation_count": validation_count,
            "pair_id": pair.pair_id,
            "a_node_id": pair.a_node_id,
            "b_node_id": pair.b_node_id,
            "phase": phase,
            **extra_payload,
        }
        perf_trace_enabled = (
            pair_index <= _facade.VALIDATION_PHASE_TRACE_PAIR_LIMIT or pair.pair_id in trace_pair_ids
        )
        _emit_progress(
            progress_callback,
            "validation_pair_state",
            **payload,
            _perf_log=perf_trace_enabled,
            _stdout_log=False,
        )
        if checkpoint:
            _emit_progress(progress_callback, "validation_pair_checkpoint", **payload)

    illegal_validations_by_pair_id: dict[str, PairValidationResult] = {}
    options_by_pair_id: dict[str, list[PairArbitrationOption]] = {}

    for pair_index, pair in enumerate(execution.pair_candidates, start=1):
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="validation_pair_started",
        )
        if (
            pair_index == 1
            or pair_index == validation_count
            or pair_index % _facade.VALIDATION_PROGRESS_CHECKPOINT_INTERVAL == 0
        ):
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="validation_pair_started",
                checkpoint=True,
            )

        candidate_road_ids, boundary_terminate_ids = _build_candidate_channel(
            pair,
            undirected_adjacency=undirected_adjacency,
            boundary_node_ids=boundary_node_ids,
        )
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="candidate_channel_built",
            candidate_road_count=len(candidate_road_ids),
        )

        if not candidate_road_ids:
            illegal_validations_by_pair_id[pair.pair_id] = PairValidationResult(
                pair_id=pair.pair_id,
                a_node_id=pair.a_node_id,
                b_node_id=pair.b_node_id,
                candidate_status="candidate",
                validated_status="rejected",
                reject_reason="invalid_candidate_boundary",
                trunk_mode="none",
                trunk_found=False,
                counterclockwise_ok=False,
                left_turn_excluded_mode=formway_mode,
                warning_codes=(),
                candidate_channel_road_ids=(),
                pruned_road_ids=(),
                trunk_road_ids=(),
                segment_road_ids=(),
                residual_road_ids=(),
                branch_cut_road_ids=(),
                boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                transition_same_dir_blocked=False,
                support_info=_with_pair_kind_2_128_support_info(
                    pair,
                    {"boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key)},
                ),
            )
            continue

        pruned_road_ids, branch_cut_infos, disconnected_after_prune = _prune_candidate_channel(
            pair,
            candidate_road_ids=candidate_road_ids,
            road_endpoints=road_endpoints,
            terminate_ids=terminate_ids,
            hard_stop_node_ids=hard_stop_node_ids,
        )
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="prune_completed",
            candidate_road_count=len(candidate_road_ids),
            pruned_road_count=len(pruned_road_ids),
        )
        if disconnected_after_prune:
            illegal_validations_by_pair_id[pair.pair_id] = PairValidationResult(
                pair_id=pair.pair_id,
                a_node_id=pair.a_node_id,
                b_node_id=pair.b_node_id,
                candidate_status="candidate",
                validated_status="rejected",
                reject_reason="disconnected_after_prune",
                trunk_mode="none",
                trunk_found=False,
                counterclockwise_ok=False,
                left_turn_excluded_mode=formway_mode,
                warning_codes=(),
                candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                trunk_road_ids=(),
                segment_road_ids=(),
                residual_road_ids=(),
                branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                transition_same_dir_blocked=False,
                support_info=_with_pair_kind_2_128_support_info(
                    pair,
                    {
                        "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                        "branch_cut_infos": branch_cut_infos,
                        "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                        "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                    },
                ),
            )
            continue

        trunk_choices, reject_reason, warning_codes, trunk_gate_info = _evaluate_trunk_choices(
            pair,
            context=context,
            candidate_road_ids=candidate_road_ids,
            pruned_road_ids=pruned_road_ids,
            branch_cut_infos=branch_cut_infos,
            road_endpoints=road_endpoints,
            through_rule=execution.strategy.through_rule,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
        )
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="trunk_evaluated",
            validated_status="validated" if trunk_choices else "rejected",
            reject_reason="" if reject_reason is None else reject_reason,
            trunk_found=bool(trunk_choices),
        )
        if not trunk_choices:
            illegal_validations_by_pair_id[pair.pair_id] = PairValidationResult(
                pair_id=pair.pair_id,
                a_node_id=pair.a_node_id,
                b_node_id=pair.b_node_id,
                candidate_status="candidate",
                validated_status="rejected",
                reject_reason=reject_reason,
                trunk_mode="none",
                trunk_found=False,
                counterclockwise_ok=False,
                left_turn_excluded_mode=formway_mode,
                warning_codes=warning_codes,
                candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                trunk_road_ids=(),
                segment_road_ids=(),
                residual_road_ids=(),
                branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                transition_same_dir_blocked=False,
                support_info=_with_pair_kind_2_128_support_info(
                    pair,
                    {
                        "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                        "branch_cut_infos": branch_cut_infos,
                        "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                        "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                        **trunk_gate_info,
                    },
                ),
            )
            continue

        pair_options: list[PairArbitrationOption] = []
        pair_fallback_validation: Optional[PairValidationResult] = None
        endpoint_priority_grades = _pair_endpoint_priority_grades(pair, context=context)

        for zero_based_option_index, choice in enumerate(trunk_choices):
            option_index = zero_based_option_index + 1
            trunk_candidate = choice.candidate
            option_id = f"{pair.pair_id}::opt_{option_index:02d}"
            alternative_trunk_only_road_ids = _alternative_trunk_only_road_ids(
                trunk_choices,
                current_choice_index=zero_based_option_index,
            )
            internal_boundary_node_ids = _collect_internal_boundary_nodes(
                pair,
                candidate=trunk_candidate,
                blocked_node_ids=hard_stop_node_ids,
            )
            if internal_boundary_node_ids:
                pair_fallback_validation = PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason="historical_boundary_blocked",
                    trunk_mode="none",
                    trunk_found=False,
                    counterclockwise_ok=False,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=choice.warning_codes,
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=(),
                    segment_road_ids=(),
                    residual_road_ids=(),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    transition_same_dir_blocked=False,
                    support_info=_with_pair_kind_2_128_support_info(
                        pair,
                        {
                            "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                            "branch_cut_infos": branch_cut_infos,
                            "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                            "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                            "historical_boundary_node_ids": list(internal_boundary_node_ids),
                        },
                    ),
                )
                continue

            current_boundary_terminate_node_ids = _collect_internal_boundary_nodes(
                pair,
                candidate=trunk_candidate,
                blocked_node_ids=boundary_terminate_ids - hard_stop_node_ids,
            )
            if current_boundary_terminate_node_ids:
                pair_fallback_validation = PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason="current_terminate_blocked",
                    trunk_mode="none",
                    trunk_found=False,
                    counterclockwise_ok=False,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=choice.warning_codes,
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=(),
                    segment_road_ids=(),
                    residual_road_ids=(),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    transition_same_dir_blocked=False,
                    support_info=_with_pair_kind_2_128_support_info(
                        pair,
                        {
                            "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                            "branch_cut_infos": branch_cut_infos,
                            "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                            "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                            "current_terminate_node_ids": list(current_boundary_terminate_node_ids),
                        },
                    ),
                )
                continue

            trunk_mode = _trunk_candidate_mode(trunk_candidate)
            if trunk_mode in {
                "through_collapsed_corridor",
                "mirrored_one_sided_corridor",
                "kind2_128_local_corridor",
            }:
                segment_candidate_road_ids = trunk_candidate.road_ids
                segment_road_ids = trunk_candidate.road_ids
                segment_cut_infos: list[dict[str, Any]] = []
            else:
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_started",
                    trunk_found=True,
                    option_id=option_id,
                )
                segment_body_allowed_road_ids = _expand_segment_body_allowed_road_ids(
                    pruned_road_ids=pruned_road_ids,
                    branch_cut_infos=branch_cut_infos,
                    undirected_adjacency=undirected_adjacency,
                    boundary_node_ids=boundary_node_ids,
                    road_endpoints=road_endpoints,
                )
                if alternative_trunk_only_road_ids:
                    segment_body_allowed_road_ids -= alternative_trunk_only_road_ids
                segment_candidate_road_ids = _build_segment_body_candidate_channel(
                    pair,
                    trunk_road_ids=trunk_candidate.road_ids,
                    undirected_adjacency=undirected_adjacency,
                    boundary_node_ids=boundary_node_ids,
                    road_endpoints=road_endpoints,
                    allowed_road_ids=segment_body_allowed_road_ids,
                )
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_candidate_channel_built",
                    candidate_road_count=len(segment_candidate_road_ids),
                    trunk_found=True,
                    option_id=option_id,
                )
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_refine_started",
                    candidate_road_count=len(segment_candidate_road_ids),
                    trunk_found=True,
                    option_id=option_id,
                )
                segment_road_ids, segment_cut_infos = _refine_segment_roads(
                    pair,
                    context=context,
                    road_endpoints=road_endpoints,
                    pruned_road_ids=segment_candidate_road_ids,
                    trunk_road_ids=trunk_candidate.road_ids,
                    through_rule=execution.strategy.through_rule,
                )
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_refine_completed",
                    candidate_road_count=len(segment_candidate_road_ids),
                    segment_road_count=len(segment_road_ids),
                    trunk_found=True,
                    option_id=option_id,
                )
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_completed",
                    segment_road_count=len(segment_road_ids),
                    trunk_found=True,
                    option_id=option_id,
                )

            support_info = _with_pair_kind_2_128_support_info(
                pair,
                {
                    "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                    "branch_cut_infos": branch_cut_infos,
                    "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                    "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                    "pair_support_road_ids": sorted(
                        set(pair.forward_path_road_ids) | set(pair.reverse_path_road_ids),
                        key=_sort_key,
                    ),
                    "forward_path_road_ids": list(trunk_candidate.forward_path.road_ids),
                    "reverse_path_road_ids": list(trunk_candidate.reverse_path.road_ids),
                    "trunk_signed_area": trunk_candidate.signed_area,
                    "trunk_mode": trunk_mode,
                    "bidirectional_minimal_loop": trunk_candidate.is_bidirectional_minimal_loop,
                    "semantic_node_group_closure": trunk_candidate.is_semantic_node_group_closure,
                    "endpoint_priority_grades": list(endpoint_priority_grades),
                    **choice.support_info,
                    **trunk_gate_info,
                    "alternative_trunk_only_road_ids": sorted(alternative_trunk_only_road_ids, key=_sort_key),
                    "segment_body_candidate_road_ids": list(segment_candidate_road_ids),
                    "segment_body_candidate_cut_infos": segment_cut_infos,
                    "left_turn_road_ids": list(trunk_candidate.left_turn_road_ids),
                },
            )
            pair_options.append(
                PairArbitrationOption(
                    option_id=option_id,
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    trunk_mode=trunk_mode,
                    counterclockwise_ok=_trunk_candidate_counterclockwise_ok(trunk_candidate),
                    warning_codes=choice.warning_codes,
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=trunk_candidate.road_ids,
                    segment_candidate_road_ids=tuple(sorted(segment_candidate_road_ids, key=_sort_key)),
                    segment_road_ids=tuple(sorted(segment_road_ids, key=_sort_key)),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    transition_same_dir_blocked=False,
                    support_info=support_info,
                )
            )

        if pair_options:
            options_by_pair_id[pair.pair_id] = pair_options
            continue

        if pair_fallback_validation is None:
            pair_fallback_validation = PairValidationResult(
                pair_id=pair.pair_id,
                a_node_id=pair.a_node_id,
                b_node_id=pair.b_node_id,
                candidate_status="candidate",
                validated_status="rejected",
                reject_reason="no_valid_segment_body_option",
                trunk_mode="none",
                trunk_found=False,
                counterclockwise_ok=False,
                left_turn_excluded_mode=formway_mode,
                warning_codes=warning_codes,
                candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                trunk_road_ids=(),
                segment_road_ids=(),
                residual_road_ids=(),
                branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                transition_same_dir_blocked=False,
                support_info=_with_pair_kind_2_128_support_info(
                    pair,
                    {
                        "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                        "branch_cut_infos": branch_cut_infos,
                        "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                        "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                    },
                ),
            )
        illegal_validations_by_pair_id[pair.pair_id] = pair_fallback_validation

    _emit_progress(
        progress_callback,
        "same_stage_arbitration_started",
        legal_pair_count=len(options_by_pair_id),
        illegal_pair_count=len(illegal_validations_by_pair_id),
    )
    arbitration_outcome = arbitrate_pair_options(
        options_by_pair=options_by_pair_id,
        single_pair_illegal_pair_ids=set(illegal_validations_by_pair_id),
        road_lengths=road_lengths,
        road_to_node_ids=road_to_node_ids,
        weak_endpoint_node_ids=weak_endpoint_node_ids,
        boundary_node_ids=arbitration_boundary_node_ids,
        semantic_conflict_node_ids=semantic_conflict_node_ids,
        strong_anchor_node_ids=strong_anchor_node_ids,
        tjunction_anchor_node_ids=tjunction_anchor_node_ids,
    )
    _emit_progress(
        progress_callback,
        "same_stage_arbitration_completed",
        component_count=len(arbitration_outcome.components),
        winner_count=len(arbitration_outcome.selected_options_by_pair_id),
        loser_count=sum(1 for item in arbitration_outcome.decisions if item.arbitration_status == "lose"),
    )

    decision_by_pair_id = {decision.pair_id: decision for decision in arbitration_outcome.decisions}
    option_by_id = {
        option.option_id: option
        for options in options_by_pair_id.values()
        for option in options
    }
    winning_pair_ids = {
        decision.pair_id
        for decision in arbitration_outcome.decisions
        if decision.arbitration_status == "win"
    }
    conflict_pair_ids_by_loser: dict[str, str] = {}
    for record in arbitration_outcome.conflict_records:
        left_wins = record.pair_id in winning_pair_ids
        right_wins = record.conflict_pair_id in winning_pair_ids
        if left_wins and not right_wins:
            conflict_pair_ids_by_loser.setdefault(record.conflict_pair_id, record.pair_id)
        elif right_wins and not left_wins:
            conflict_pair_ids_by_loser.setdefault(record.pair_id, record.conflict_pair_id)

    provisional_results_by_pair_id: dict[str, PairValidationResult] = {}
    for pair_index, pair in enumerate(execution.pair_candidates, start=1):
        decision = decision_by_pair_id[pair.pair_id]
        if pair.pair_id in options_by_pair_id:
            selected_option = option_by_id[decision.selected_option_id or options_by_pair_id[pair.pair_id][0].option_id]
            result = _pair_validation_from_option(
                selected_option,
                decision=decision,
                conflict_pair_id=conflict_pair_ids_by_loser.get(pair.pair_id),
                left_turn_excluded_mode=formway_mode,
                compact_release_payloads=False,
            )
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="result_appended",
                validated_status=result.validated_status,
                reject_reason="" if result.reject_reason is None else result.reject_reason,
                trunk_found=result.trunk_found,
                segment_road_count=_validation_road_count(
                    result.segment_road_ids,
                    result.support_info,
                    "segment_body_road_count",
                ),
            )
            provisional_results_by_pair_id[pair.pair_id] = result
        else:
            result = _single_pair_illegal_validation(
                illegal_validations_by_pair_id[pair.pair_id],
                decision=decision,
                compact_release_payloads=False,
            )
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="result_appended",
                validated_status=result.validated_status,
                reject_reason="" if result.reject_reason is None else result.reject_reason,
                trunk_found=result.trunk_found,
            )
            provisional_results_by_pair_id[pair.pair_id] = result

    provisional_results = [provisional_results_by_pair_id[pair.pair_id] for pair in execution.pair_candidates]
    provisional_validated_pair_count = sum(
        1 for item in provisional_results if item.validated_status == "validated"
    )
    _emit_progress(
        progress_callback,
        "validation_tighten_started",
        validation_count=validation_count,
        validated_pair_count=provisional_validated_pair_count,
    )
    if provisional_validated_pair_count:
        validated_results = [item for item in provisional_results if item.validated_status == "validated"]
        tightened_validated = _tighten_validated_segment_components(
            validated_results,
            execution=execution,
            context=context,
            road_endpoints=road_endpoints,
        )
        if compact_release_payloads:
            tightened_validated = [
                _compact_validation_result_for_release(item, keep_tighten_fields=False)
                for item in tightened_validated
            ]
        tightened_by_pair_id = {item.pair_id: item for item in tightened_validated}
    else:
        tightened_by_pair_id = {}

    tightened = [tightened_by_pair_id.get(item.pair_id, item) for item in provisional_results]
    if compact_release_payloads:
        tightened = [
            _compact_validation_result_for_release(item, keep_tighten_fields=False)
            for item in tightened
        ]
    _emit_progress(
        progress_callback,
        "validation_tighten_completed",
        validation_count=len(tightened),
        validated_pair_count=sum(1 for item in tightened if item.validated_status == "validated"),
    )
    if return_arbitration_outcome:
        return tightened, arbitration_outcome
    return tightened
