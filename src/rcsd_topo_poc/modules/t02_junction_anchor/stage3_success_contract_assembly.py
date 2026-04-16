from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_audit_assembler import (
    LegacyStage3AuditEnvelope,
    build_legacy_stage3_audit_envelope_from_step7_assembly,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Context,
    Stage3Step3LegalSpaceResult,
    Stage3Step4RCSemanticsResult,
    Stage3Step5ForeignModelResult,
    Stage3Step6GeometrySolveResult,
    Stage3Step7AcceptanceResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_contract import (
    Stage3OfficialReviewDecision,
    Stage3ReviewMetadata,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_success_step_result_builder import (
    Stage3SuccessContractIdentityInputs,
    Stage3SuccessContractStepSnapshotInputs,
    Stage3SuccessStepResults,
    build_stage3_success_step_results,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step7_acceptance import (
    Stage3Step7DecisionInputs,
    Stage3LegacyStep7Assembly,
    build_stage3_step7_assembly_from_results,
)


@dataclass(frozen=True)
class Stage3SuccessContractAssemblyInputs:
    context: Stage3Context
    final_decision_inputs: Stage3SuccessContractFinalDecisionInputs
    step3_result: Stage3Step3LegalSpaceResult
    step4_result: Stage3Step4RCSemanticsResult | None
    step5_result: Stage3Step5ForeignModelResult
    step6_result: Stage3Step6GeometrySolveResult


@dataclass(frozen=True)
class Stage3SuccessContractFinalDecisionInputs:
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


@dataclass(frozen=True)
class Stage3SuccessContractAssemblyOutputs:
    step3_result: Stage3Step3LegalSpaceResult
    step4_result: Stage3Step4RCSemanticsResult | None
    step5_result: Stage3Step5ForeignModelResult
    step6_result: Stage3Step6GeometrySolveResult
    step7_assembly: Stage3LegacyStep7Assembly
    canonical_step7_result: Stage3Step7AcceptanceResult
    legacy_stage3_audit_envelope: LegacyStage3AuditEnvelope
    review_metadata: Stage3ReviewMetadata
    official_review_decision: Stage3OfficialReviewDecision


def build_stage3_success_contract_assembly_inputs_from_results(
    *,
    step_results: Stage3SuccessStepResults,
    final_decision_inputs: Stage3SuccessContractFinalDecisionInputs,
) -> Stage3SuccessContractAssemblyInputs:
    return Stage3SuccessContractAssemblyInputs(
        context=step_results.context,
        final_decision_inputs=final_decision_inputs,
        step3_result=step_results.step3_result,
        step4_result=step_results.step4_result,
        step5_result=step_results.step5_result,
        step6_result=step_results.step6_result,
    )


def build_stage3_success_contract_assembly_inputs(
    *,
    identity_inputs: Stage3SuccessContractIdentityInputs,
    step_snapshot_inputs: Stage3SuccessContractStepSnapshotInputs,
    final_decision_inputs: Stage3SuccessContractFinalDecisionInputs,
) -> Stage3SuccessContractAssemblyInputs:
    return build_stage3_success_contract_assembly_inputs_from_results(
        step_results=build_stage3_success_step_results(
            identity_inputs=identity_inputs,
            step_snapshot_inputs=step_snapshot_inputs,
        ),
        final_decision_inputs=final_decision_inputs,
    )


def assemble_stage3_success_contracts(
    inputs: Stage3SuccessContractAssemblyInputs,
) -> Stage3SuccessContractAssemblyOutputs:
    step7_assembly = build_stage3_step7_assembly_from_results(
        context=inputs.context,
        step3_result=inputs.step3_result,
        step4_result=inputs.step4_result,
        step5_result=inputs.step5_result,
        step6_result=inputs.step6_result,
        decision_inputs=Stage3Step7DecisionInputs(
            success=inputs.final_decision_inputs.success,
            acceptance_class=inputs.final_decision_inputs.acceptance_class,
            acceptance_reason=inputs.final_decision_inputs.acceptance_reason,
            status=inputs.final_decision_inputs.status,
            representative_has_evd=inputs.final_decision_inputs.representative_has_evd,
            representative_is_anchor=inputs.final_decision_inputs.representative_is_anchor,
            representative_kind_2=inputs.final_decision_inputs.representative_kind_2,
            business_match_reason=inputs.final_decision_inputs.business_match_reason,
            single_sided_t_mouth_corridor_semantic_gap=(
                inputs.final_decision_inputs.single_sided_t_mouth_corridor_semantic_gap
            ),
            final_uncovered_selected_endpoint_node_count=(
                inputs.final_decision_inputs.final_uncovered_selected_endpoint_node_count
            ),
            selected_rc_node_count=inputs.final_decision_inputs.selected_rc_node_count,
            selected_rc_road_count=inputs.final_decision_inputs.selected_rc_road_count,
            polygon_support_rc_node_count=(
                inputs.final_decision_inputs.polygon_support_rc_node_count
            ),
            polygon_support_rc_road_count=(
                inputs.final_decision_inputs.polygon_support_rc_road_count
            ),
            invalid_rc_node_count=inputs.final_decision_inputs.invalid_rc_node_count,
            invalid_rc_road_count=inputs.final_decision_inputs.invalid_rc_road_count,
            drivezone_is_empty=inputs.final_decision_inputs.drivezone_is_empty,
            polygon_is_empty=inputs.final_decision_inputs.polygon_is_empty,
        ),
    )
    legacy_stage3_audit_envelope = (
        build_legacy_stage3_audit_envelope_from_step7_assembly(
            mainnodeid=inputs.context.normalized_mainnodeid,
            step7_assembly=step7_assembly,
            representative_has_evd=inputs.final_decision_inputs.representative_has_evd,
            representative_is_anchor=inputs.final_decision_inputs.representative_is_anchor,
            representative_kind_2=inputs.final_decision_inputs.representative_kind_2,
        )
    )
    return Stage3SuccessContractAssemblyOutputs(
        step3_result=inputs.step3_result,
        step4_result=inputs.step4_result,
        step5_result=inputs.step5_result,
        step6_result=inputs.step6_result,
        step7_assembly=step7_assembly,
        canonical_step7_result=legacy_stage3_audit_envelope.audit_record.step7,
        legacy_stage3_audit_envelope=legacy_stage3_audit_envelope,
        review_metadata=legacy_stage3_audit_envelope.review_metadata,
        official_review_decision=legacy_stage3_audit_envelope.official_review_decision,
    )
