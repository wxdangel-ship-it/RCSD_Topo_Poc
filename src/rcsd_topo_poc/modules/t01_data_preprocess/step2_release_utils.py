from __future__ import annotations

from dataclasses import replace
from typing import Any

from rcsd_topo_poc.modules.t01_data_preprocess.step2_arbitration import (
    PairArbitrationOption,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import Step1StrategyExecution


def _compact_execution_for_validation(execution: Step1StrategyExecution) -> Step1StrategyExecution:
    return replace(
        execution,
        seed_eval={},
        terminate_eval={},
        through_node_ids=set(),
        search_seed_ids=[],
        through_seed_pruned_count=0,
        search_results={},
        search_event_counts={},
        search_event_samples=[],
    )


def _compact_branch_cut_info(info: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "road_id": info.get("road_id"),
        "cut_reason": info.get("cut_reason"),
    }
    for key in (
        "component_id",
        "conflicting_pair_ids",
        "terminate_node_ids",
        "support_barrier_node_ids",
    ):
        value = info.get(key)
        if value not in (None, (), [], {}):
            compact[key] = value
    return compact


def _compact_component_info(info: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "component_id": info.get("component_id"),
        "road_ids": info.get("road_ids", []),
        "attachment_node_ids": info.get("attachment_node_ids", []),
        "internal_support_attachment_node_ids": info.get(
            "internal_support_attachment_node_ids",
            [],
        ),
        "internal_t_support_attachment_node_ids": info.get(
            "internal_t_support_attachment_node_ids",
            [],
        ),
        "component_directionality": info.get("component_directionality"),
        "bidirectional_road_ids": info.get("bidirectional_road_ids", []),
        "attachment_flow_status": info.get("attachment_flow_status"),
        "attachment_direction_labels": info.get("attachment_direction_labels", []),
        "parallel_corridor_directionality": info.get("parallel_corridor_directionality"),
        "parallel_corridor_directions": info.get("parallel_corridor_directions", []),
        "hits_other_terminate": bool(info.get("hits_other_terminate")),
        "terminate_node_ids": info.get("terminate_node_ids", []),
        "contains_other_validated_trunk": bool(info.get("contains_other_validated_trunk")),
        "conflicting_pair_ids": info.get("conflicting_pair_ids", []),
        "blocked_by_transition_same_dir": bool(info.get("blocked_by_transition_same_dir")),
        "side_access_metric": info.get("side_access_metric"),
        "side_access_distance_m": info.get("side_access_distance_m"),
        "side_access_gate_passed": info.get("side_access_gate_passed"),
        "kept_as_segment_body": bool(info.get("kept_as_segment_body")),
        "moved_to_step3_residual": bool(info.get("moved_to_step3_residual")),
        "moved_to_branch_cut": bool(info.get("moved_to_branch_cut")),
        "decision_reason": info.get("decision_reason"),
    }
    if info.get("transition_block_infos"):
        compact["transition_block_infos"] = info["transition_block_infos"]
    return compact


def _compact_residual_info(info: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "road_id": info.get("road_id"),
        "component_id": info.get("component_id"),
        "residual_reason": info.get("residual_reason"),
        "blocked_by_transition_same_dir": bool(info.get("blocked_by_transition_same_dir")),
        "conflicting_pair_ids": info.get("conflicting_pair_ids", []),
        "terminate_node_ids": info.get("terminate_node_ids", []),
        "side_access_distance_m": info.get("side_access_distance_m"),
        "side_access_gate_passed": info.get("side_access_gate_passed"),
    }
    if info.get("hint_cut_reasons"):
        compact["hint_cut_reasons"] = info["hint_cut_reasons"]
    return compact


def _compact_support_info_for_release(
    support_info: dict[str, Any],
    *,
    keep_tighten_fields: bool,
) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    passthrough_keys = (
        "boundary_terminate_node_ids",
        "historical_boundary_node_ids",
        "trunk_signed_area",
        "trunk_mode",
        "bidirectional_minimal_loop",
        "semantic_node_group_closure",
        "dual_carriageway_separation_gate_limit_m",
        "dual_carriageway_max_separation_m",
        "candidate_channel_road_count",
        "pruned_road_count",
        "trunk_road_count",
        "segment_body_candidate_road_count",
        "segment_body_road_count",
        "residual_road_count",
        "branch_cut_road_count",
        "boundary_terminate_node_count",
    )
    for key in passthrough_keys:
        if key in support_info:
            compact[key] = support_info[key]

    branch_cut_infos = support_info.get("branch_cut_infos")
    if branch_cut_infos:
        compact["branch_cut_infos"] = [
            _compact_branch_cut_info(dict(info)) for info in branch_cut_infos
        ]

    if keep_tighten_fields:
        segment_candidate_road_ids = support_info.get("segment_body_candidate_road_ids")
        if segment_candidate_road_ids:
            compact["segment_body_candidate_road_ids"] = list(segment_candidate_road_ids)
        segment_candidate_cut_infos = support_info.get("segment_body_candidate_cut_infos")
        if segment_candidate_cut_infos:
            compact["segment_body_candidate_cut_infos"] = [
                _compact_branch_cut_info(dict(info)) for info in segment_candidate_cut_infos
            ]
    else:
        component_infos = support_info.get("non_trunk_components")
        if component_infos:
            compact["non_trunk_components"] = [
                _compact_component_info(dict(info)) for info in component_infos
            ]
        residual_infos = support_info.get("step3_residual_infos")
        if residual_infos:
            compact["step3_residual_infos"] = [
                _compact_residual_info(dict(info)) for info in residual_infos
            ]

    return compact


def _compact_validation_result_for_release(
    validation: Any,
    *,
    keep_tighten_fields: bool,
) -> Any:
    support_info = _compact_support_info_for_release(
        dict(validation.support_info),
        keep_tighten_fields=keep_tighten_fields,
    )
    support_info.setdefault("candidate_channel_road_count", len(validation.candidate_channel_road_ids))
    support_info.setdefault("pruned_road_count", len(validation.pruned_road_ids))
    support_info.setdefault("trunk_road_count", len(validation.trunk_road_ids))
    support_info.setdefault("segment_body_road_count", len(validation.segment_road_ids))
    support_info.setdefault("residual_road_count", len(validation.residual_road_ids))
    support_info.setdefault("branch_cut_road_count", len(validation.branch_cut_road_ids))
    support_info.setdefault("boundary_terminate_node_count", len(validation.boundary_terminate_node_ids))

    if keep_tighten_fields and validation.validated_status == "validated":
        pruned_road_ids = validation.pruned_road_ids
        trunk_road_ids = validation.trunk_road_ids
        segment_road_ids: tuple[str, ...] = ()
        residual_road_ids: tuple[str, ...] = ()
    elif validation.validated_status == "validated":
        pruned_road_ids = ()
        trunk_road_ids = validation.trunk_road_ids
        segment_road_ids = validation.segment_road_ids
        residual_road_ids = validation.residual_road_ids
    else:
        pruned_road_ids = ()
        trunk_road_ids = ()
        segment_road_ids = ()
        residual_road_ids = ()

    return replace(
        validation,
        candidate_channel_road_ids=(),
        pruned_road_ids=pruned_road_ids,
        trunk_road_ids=trunk_road_ids,
        segment_road_ids=segment_road_ids,
        residual_road_ids=residual_road_ids,
        branch_cut_road_ids=(),
        boundary_terminate_node_ids=(),
        support_info=support_info,
    )


def _compact_option_support_info_for_runtime(
    support_info: dict[str, Any],
    *,
    candidate_channel_road_count: int,
    pruned_road_count: int,
    trunk_road_count: int,
    segment_body_candidate_road_count: int,
    segment_body_road_count: int,
    branch_cut_road_count: int,
    boundary_terminate_node_count: int,
) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    passthrough_keys = (
        "boundary_terminate_node_ids",
        "trunk_signed_area",
        "trunk_mode",
        "bidirectional_minimal_loop",
        "semantic_node_group_closure",
        "dual_carriageway_separation_gate_limit_m",
        "dual_carriageway_max_separation_m",
        "endpoint_priority_grades",
    )
    for key in passthrough_keys:
        if key in support_info:
            compact[key] = support_info[key]

    if support_info.get("forward_path_road_ids"):
        compact["forward_path_road_ids"] = list(support_info["forward_path_road_ids"])
    if support_info.get("reverse_path_road_ids"):
        compact["reverse_path_road_ids"] = list(support_info["reverse_path_road_ids"])
    if support_info.get("pair_support_road_ids"):
        compact["pair_support_road_ids"] = list(support_info["pair_support_road_ids"])
    if support_info.get("branch_cut_infos"):
        compact["branch_cut_infos"] = [
            _compact_branch_cut_info(dict(info))
            for info in support_info["branch_cut_infos"]
        ]
    if support_info.get("segment_body_candidate_road_ids"):
        compact["segment_body_candidate_road_ids"] = list(
            support_info["segment_body_candidate_road_ids"]
        )
    if support_info.get("segment_body_candidate_cut_infos"):
        compact["segment_body_candidate_cut_infos"] = [
            _compact_branch_cut_info(dict(info))
            for info in support_info["segment_body_candidate_cut_infos"]
        ]
    if support_info.get("internal_parallel_trunk_swap_infos"):
        compact["internal_parallel_trunk_swap_infos"] = list(
            support_info["internal_parallel_trunk_swap_infos"]
        )

    compact["candidate_channel_road_count"] = candidate_channel_road_count
    compact["pruned_road_count"] = pruned_road_count
    compact["trunk_road_count"] = trunk_road_count
    compact["segment_body_candidate_road_count"] = segment_body_candidate_road_count
    compact["segment_body_road_count"] = segment_body_road_count
    compact["branch_cut_road_count"] = branch_cut_road_count
    compact["boundary_terminate_node_count"] = boundary_terminate_node_count
    return compact


def _compact_option_for_validation_runtime(option: PairArbitrationOption) -> PairArbitrationOption:
    return replace(
        option,
        support_info=_compact_option_support_info_for_runtime(
            dict(option.support_info),
            candidate_channel_road_count=len(option.candidate_channel_road_ids),
            pruned_road_count=len(option.pruned_road_ids),
            trunk_road_count=len(option.trunk_road_ids),
            segment_body_candidate_road_count=len(option.segment_candidate_road_ids),
            segment_body_road_count=len(option.segment_road_ids),
            branch_cut_road_count=len(option.branch_cut_road_ids),
            boundary_terminate_node_count=len(option.boundary_terminate_node_ids),
        ),
    )
