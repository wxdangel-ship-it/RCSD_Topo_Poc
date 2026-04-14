from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_success_contract_assembly import (
    Stage3SuccessContractFinalDecisionInputs,
)


@dataclass(frozen=True)
class Stage3SuccessDecisionBuildInputs:
    success: bool
    acceptance_class: str
    acceptance_reason: str
    status: str
    representative_has_evd: Any | None
    representative_is_anchor: Any | None
    representative_kind_2: Any | None
    business_match_reason: str | None
    single_sided_t_mouth_corridor_semantic_gap: bool
    final_uncovered_selected_endpoint_node_count: int
    selected_rc_node_count: int
    selected_rc_road_count: int
    polygon_support_rc_node_count: int
    polygon_support_rc_road_count: int
    invalid_rc_node_count: int
    invalid_rc_road_count: int
    drivezone_is_empty: bool
    polygon_is_empty: bool


def build_stage3_success_final_decision_inputs(
    inputs: Stage3SuccessDecisionBuildInputs,
) -> Stage3SuccessContractFinalDecisionInputs:
    return Stage3SuccessContractFinalDecisionInputs(
        success=inputs.success,
        acceptance_class=inputs.acceptance_class,
        acceptance_reason=inputs.acceptance_reason,
        status=inputs.status,
        representative_has_evd=inputs.representative_has_evd,
        representative_is_anchor=inputs.representative_is_anchor,
        representative_kind_2=inputs.representative_kind_2,
        business_match_reason=inputs.business_match_reason,
        single_sided_t_mouth_corridor_semantic_gap=(
            inputs.single_sided_t_mouth_corridor_semantic_gap
        ),
        final_uncovered_selected_endpoint_node_count=(
            inputs.final_uncovered_selected_endpoint_node_count
        ),
        selected_rc_node_count=inputs.selected_rc_node_count,
        selected_rc_road_count=inputs.selected_rc_road_count,
        polygon_support_rc_node_count=inputs.polygon_support_rc_node_count,
        polygon_support_rc_road_count=inputs.polygon_support_rc_road_count,
        invalid_rc_node_count=inputs.invalid_rc_node_count,
        invalid_rc_road_count=inputs.invalid_rc_road_count,
        drivezone_is_empty=inputs.drivezone_is_empty,
        polygon_is_empty=inputs.polygon_is_empty,
    )
