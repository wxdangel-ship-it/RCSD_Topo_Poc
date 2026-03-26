from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional

from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    Step1GraphContext,
    Step1StrategyExecution,
    StrategySpec,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_arbitration import (
    PairArbitrationDecision,
    PairArbitrationOption,
    PairArbitrationOutcome,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_release_utils import (
    _compact_validation_result_for_release,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_trunk_utils import (
    _geometry_length,
    _is_tjunction_support_anchor_node,
)


@dataclass(frozen=True)
class PairValidationResult:
    pair_id: str
    a_node_id: str
    b_node_id: str
    candidate_status: str
    validated_status: str
    reject_reason: Optional[str]
    trunk_mode: str
    trunk_found: bool
    counterclockwise_ok: bool
    left_turn_excluded_mode: str
    warning_codes: tuple[str, ...]
    candidate_channel_road_ids: tuple[str, ...]
    pruned_road_ids: tuple[str, ...]
    trunk_road_ids: tuple[str, ...]
    segment_road_ids: tuple[str, ...]
    residual_road_ids: tuple[str, ...]
    branch_cut_road_ids: tuple[str, ...]
    boundary_terminate_node_ids: tuple[str, ...]
    transition_same_dir_blocked: bool
    support_info: dict[str, Any]
    conflict_pair_id: Optional[str] = None
    single_pair_legal: bool = False
    arbitration_status: str = "unresolved"
    arbitration_component_id: str = ""
    arbitration_option_id: Optional[str] = None
    lose_reason: str = ""


@dataclass(frozen=True)
class Step2StrategyResult:
    strategy: StrategySpec
    segment_summary: dict[str, Any]
    output_files: list[str]
    validations: list[PairValidationResult]


def _road_length_index(context: Step1GraphContext) -> dict[str, float]:
    return {
        road_id: _geometry_length(road.geometry)
        for road_id, road in context.roads.items()
    }


def _road_node_index(road_endpoints: dict[str, tuple[str, str]]) -> dict[str, tuple[str, str]]:
    return {road_id: endpoints for road_id, endpoints in road_endpoints.items()}


def _arbitration_boundary_node_ids(
    execution: Step1StrategyExecution,
    *,
    hard_stop_node_ids: set[str],
) -> set[str]:
    return set(execution.seed_ids) | set(execution.terminate_ids) | set(hard_stop_node_ids)


def _arbitration_semantic_conflict_node_ids(context: Step1GraphContext) -> set[str]:
    result: set[str] = set()
    for semantic_node_id, node in context.semantic_nodes.items():
        if node.kind_2 in {4, 64, 2048} and node.grade_2 in {1, 2, 3}:
            result.add(semantic_node_id)
    return result


def _arbitration_strong_anchor_node_ids(context: Step1GraphContext) -> set[str]:
    result: set[str] = set()
    for semantic_node_id, node in context.semantic_nodes.items():
        cross_flag = int(node.raw_properties.get("cross_flag") or 0)
        if node.kind_2 in {4, 64, 2048} and node.grade_2 >= 2 and cross_flag >= 3:
            result.add(semantic_node_id)
    return result


def _arbitration_tjunction_anchor_node_ids(context: Step1GraphContext) -> set[str]:
    result: set[str] = set()
    for semantic_node_id, node in context.semantic_nodes.items():
        if _is_tjunction_support_anchor_node(node):
            result.add(semantic_node_id)
    return result


def _arbitration_weak_endpoint_node_ids(context: Step1GraphContext) -> set[str]:
    result: set[str] = set()
    for semantic_node_id, node in context.semantic_nodes.items():
        mainnodeid = node.raw_properties.get("mainnodeid")
        if mainnodeid in {None, ""} and len(node.member_node_ids) == 1:
            result.add(semantic_node_id)
    return result


def _pair_validation_from_option(
    option: PairArbitrationOption,
    *,
    decision: PairArbitrationDecision,
    conflict_pair_id: Optional[str],
    left_turn_excluded_mode: str,
    compact_release_payloads: bool,
) -> PairValidationResult:
    support_info = dict(option.support_info)
    support_info["arbitration"] = {
        "component_id": decision.component_id,
        "status": decision.arbitration_status,
        "selected_option_id": decision.selected_option_id,
        "endpoint_boundary_penalty": decision.endpoint_boundary_penalty,
        "strong_anchor_win_count": decision.strong_anchor_win_count,
        "corridor_naturalness_score": decision.corridor_naturalness_score,
        "contested_trunk_coverage_count": decision.contested_trunk_coverage_count,
        "contested_trunk_coverage_ratio": decision.contested_trunk_coverage_ratio,
        "pair_support_expansion_penalty": decision.pair_support_expansion_penalty,
        "internal_endpoint_penalty": decision.internal_endpoint_penalty,
        "body_connectivity_support": decision.body_connectivity_support,
        "semantic_conflict_penalty": decision.semantic_conflict_penalty,
        "lose_reason": decision.lose_reason,
    }
    result = PairValidationResult(
        pair_id=option.pair_id,
        a_node_id=option.a_node_id,
        b_node_id=option.b_node_id,
        candidate_status="candidate",
        validated_status="validated" if decision.arbitration_status == "win" else "rejected",
        reject_reason=None if decision.arbitration_status == "win" else decision.lose_reason,
        trunk_mode=option.trunk_mode,
        trunk_found=True,
        counterclockwise_ok=option.counterclockwise_ok,
        left_turn_excluded_mode=left_turn_excluded_mode,
        warning_codes=option.warning_codes,
        candidate_channel_road_ids=option.candidate_channel_road_ids,
        pruned_road_ids=option.pruned_road_ids,
        trunk_road_ids=option.trunk_road_ids,
        segment_road_ids=option.segment_road_ids if decision.arbitration_status == "win" else (),
        residual_road_ids=(),
        branch_cut_road_ids=option.branch_cut_road_ids,
        boundary_terminate_node_ids=option.boundary_terminate_node_ids,
        transition_same_dir_blocked=option.transition_same_dir_blocked,
        support_info=support_info,
        conflict_pair_id=conflict_pair_id,
        single_pair_legal=True,
        arbitration_status=decision.arbitration_status,
        arbitration_component_id=decision.component_id,
        arbitration_option_id=decision.selected_option_id,
        lose_reason=decision.lose_reason,
    )
    if compact_release_payloads and decision.arbitration_status != "win":
        result = _compact_validation_result_for_release(
            result,
            keep_tighten_fields=decision.arbitration_status == "win",
        )
    return result


def _single_pair_illegal_validation(
    validation: PairValidationResult,
    *,
    decision: PairArbitrationDecision,
    compact_release_payloads: bool,
) -> PairValidationResult:
    current = replace(
        validation,
        single_pair_legal=False,
        arbitration_status="lose",
        arbitration_component_id="",
        arbitration_option_id=None,
        lose_reason=decision.lose_reason,
    )
    support_info = dict(current.support_info)
    support_info["arbitration"] = {
        "component_id": "",
        "status": "lose",
        "selected_option_id": None,
        "endpoint_boundary_penalty": 0,
        "strong_anchor_win_count": 0,
        "corridor_naturalness_score": 0,
        "contested_trunk_coverage_count": 0,
        "contested_trunk_coverage_ratio": 0.0,
        "pair_support_expansion_penalty": 0,
        "internal_endpoint_penalty": 0,
        "body_connectivity_support": 0.0,
        "semantic_conflict_penalty": 0,
        "lose_reason": decision.lose_reason,
    }
    current = replace(current, support_info=support_info)
    if compact_release_payloads:
        current = _compact_validation_result_for_release(current, keep_tighten_fields=False)
    return current


def _empty_pair_arbitration_outcome() -> PairArbitrationOutcome:
    return PairArbitrationOutcome(
        selected_options_by_pair_id={},
        decisions=[],
        conflict_records=[],
        components=[],
    )


def _validation_road_count(
    road_ids: tuple[str, ...],
    support_info: dict[str, Any],
    count_key: str,
) -> int:
    value = support_info.get(count_key)
    if value is None:
        return len(road_ids)
    return int(value)
