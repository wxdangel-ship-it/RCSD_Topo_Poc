from __future__ import annotations

from dataclasses import dataclass

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Context,
    Stage3Step3LegalSpaceResult,
    Stage3Step4RCSemanticsResult,
    Stage3Step5ForeignModelResult,
    Stage3Step6GeometrySolveResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step6_geometry_controller import (
    Stage3Step6GeometryControllerDecision,
    Stage3Step6GeometryControllerInputs,
    derive_stage3_step6_geometry_controller_decision,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step6_geometry_solve import (
    Stage3Step6GeometrySolveInputs,
    build_stage3_step6_geometry_solve_result,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_success_contract_assembly import (
    Stage3SuccessContractAssemblyInputs,
    Stage3SuccessContractAssemblyOutputs,
    Stage3SuccessContractFinalDecisionInputs,
    assemble_stage3_success_contracts,
)


@dataclass(frozen=True)
class Stage3TerminalContractInputs:
    context: Stage3Context
    step3_result: Stage3Step3LegalSpaceResult
    step4_result: Stage3Step4RCSemanticsResult | None
    step5_result: Stage3Step5ForeignModelResult
    step6_controller_inputs: Stage3Step6GeometryControllerInputs
    step6_solve_seed_inputs: Stage3Step6TerminalSolveSeedInputs
    final_decision_inputs: Stage3SuccessContractFinalDecisionInputs


@dataclass(frozen=True)
class Stage3Step6TerminalSolveSeedInputs:
    primary_solved_geometry: object | None
    geometry_established: bool
    max_selected_side_branch_covered_length_m: float | None
    selected_node_repair_attempted: bool
    selected_node_repair_applied: bool
    selected_node_repair_discarded_due_to_extra_roads: bool
    introduced_extra_local_road_ids: tuple[str, ...] | list[str] | set[str]
    optimizer_events: tuple[str, ...] | list[str]
    late_single_sided_branch_cap_cleanup_applied: bool = False
    late_post_soft_overlap_trim_applied: bool = False
    late_final_foreign_residue_trim_applied: bool = False
    late_single_sided_partial_branch_strip_cleanup_applied: bool = False
    late_single_sided_corridor_mask_cleanup_applied: bool = False
    late_single_sided_tail_clip_cleanup_applied: bool = False
    polygon_aspect_ratio: float | None = None
    polygon_compactness: float | None = None
    polygon_bbox_fill_ratio: float | None = None
    uncovered_selected_endpoint_node_ids: tuple[str, ...] | list[str] | set[str] = ()
    foreign_semantic_node_ids: tuple[str, ...] | list[str] | set[str] = ()
    foreign_road_arm_corridor_ids: tuple[str, ...] | list[str] | set[str] = ()
    foreign_overlap_metric_m: float | None = None
    foreign_tail_length_m: float | None = None
    foreign_overlap_zero_but_tail_present: bool | None = None


@dataclass(frozen=True)
class Stage3TerminalContractOutputs:
    step6_controller_decision: Stage3Step6GeometryControllerDecision
    step6_result: Stage3Step6GeometrySolveResult
    success_contracts: Stage3SuccessContractAssemblyOutputs


def build_stage3_terminal_contracts(
    inputs: Stage3TerminalContractInputs,
) -> Stage3TerminalContractOutputs:
    step6_controller_decision = derive_stage3_step6_geometry_controller_decision(
        inputs.step6_controller_inputs
    )
    step6_result = build_stage3_step6_geometry_solve_result(
        Stage3Step6GeometrySolveInputs(
            primary_solved_geometry=inputs.step6_solve_seed_inputs.primary_solved_geometry,
            geometry_established=inputs.step6_solve_seed_inputs.geometry_established,
            residual_step5_blocking_foreign_required=(
                step6_controller_decision.residual_step5_blocking_foreign_required
            ),
            max_selected_side_branch_covered_length_m=(
                inputs.step6_solve_seed_inputs.max_selected_side_branch_covered_length_m
            ),
            selected_node_repair_attempted=(
                inputs.step6_solve_seed_inputs.selected_node_repair_attempted
            ),
            selected_node_repair_applied=(
                inputs.step6_solve_seed_inputs.selected_node_repair_applied
            ),
            selected_node_repair_discarded_due_to_extra_roads=(
                inputs.step6_solve_seed_inputs.selected_node_repair_discarded_due_to_extra_roads
            ),
            introduced_extra_local_road_ids=(
                inputs.step6_solve_seed_inputs.introduced_extra_local_road_ids
            ),
            optimizer_events=inputs.step6_solve_seed_inputs.optimizer_events,
            late_single_sided_branch_cap_cleanup_applied=(
                inputs.step6_solve_seed_inputs.late_single_sided_branch_cap_cleanup_applied
            ),
            late_post_soft_overlap_trim_applied=(
                inputs.step6_solve_seed_inputs.late_post_soft_overlap_trim_applied
            ),
            late_final_foreign_residue_trim_applied=(
                inputs.step6_solve_seed_inputs.late_final_foreign_residue_trim_applied
            ),
            late_single_sided_partial_branch_strip_cleanup_applied=(
                inputs.step6_solve_seed_inputs.late_single_sided_partial_branch_strip_cleanup_applied
            ),
            late_single_sided_corridor_mask_cleanup_applied=(
                inputs.step6_solve_seed_inputs.late_single_sided_corridor_mask_cleanup_applied
            ),
            late_single_sided_tail_clip_cleanup_applied=(
                inputs.step6_solve_seed_inputs.late_single_sided_tail_clip_cleanup_applied
            ),
            polygon_aspect_ratio=inputs.step6_solve_seed_inputs.polygon_aspect_ratio,
            polygon_compactness=inputs.step6_solve_seed_inputs.polygon_compactness,
            polygon_bbox_fill_ratio=inputs.step6_solve_seed_inputs.polygon_bbox_fill_ratio,
            uncovered_selected_endpoint_node_ids=(
                inputs.step6_solve_seed_inputs.uncovered_selected_endpoint_node_ids
            ),
            foreign_semantic_node_ids=(
                inputs.step6_solve_seed_inputs.foreign_semantic_node_ids
            ),
            foreign_road_arm_corridor_ids=(
                inputs.step6_solve_seed_inputs.foreign_road_arm_corridor_ids
            ),
            foreign_overlap_metric_m=inputs.step6_solve_seed_inputs.foreign_overlap_metric_m,
            foreign_tail_length_m=inputs.step6_solve_seed_inputs.foreign_tail_length_m,
            foreign_overlap_zero_but_tail_present=(
                inputs.step6_solve_seed_inputs.foreign_overlap_zero_but_tail_present
            ),
            geometry_review_reason=step6_controller_decision.geometry_review_reason,
            final_validation_flags=step6_controller_decision.final_validation_flags,
        )
    )
    success_contracts = assemble_stage3_success_contracts(
        Stage3SuccessContractAssemblyInputs(
            context=inputs.context,
            final_decision_inputs=inputs.final_decision_inputs,
            step3_result=inputs.step3_result,
            step4_result=inputs.step4_result,
            step5_result=inputs.step5_result,
            step6_result=step6_result,
        )
    )
    return Stage3TerminalContractOutputs(
        step6_controller_decision=step6_controller_decision,
        step6_result=step6_result,
        success_contracts=success_contracts,
    )
