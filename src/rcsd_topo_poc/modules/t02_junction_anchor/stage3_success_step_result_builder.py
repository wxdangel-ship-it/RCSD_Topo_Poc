from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_context_builder import (
    Stage3LegacyContextInputs,
    build_stage3_context_from_legacy_inputs,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Context,
    Stage3Step3LegalSpaceResult,
    Stage3Step4RCSemanticsResult,
    Stage3Step5ForeignModelResult,
    Stage3Step6GeometrySolveResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step3_legal_space import (
    Stage3Step3LegalSpaceInputs,
    build_stage3_step3_legal_space_result,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step5_foreign_model import (
    Stage3Step5ForeignModelInputs,
    build_stage3_step5_foreign_model_result,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step6_geometry_solve import (
    Stage3Step6GeometrySolveInputs,
    build_stage3_step6_geometry_solve_result,
)


@dataclass(frozen=True)
class Stage3SuccessContractIdentityInputs:
    representative_node_id: str
    normalized_mainnodeid: str
    template_class: str
    representative_kind: Any | None = None
    representative_kind_2: int | None = None
    representative_grade_2: int | None = None
    semantic_junction_set: Iterable[str] = ()
    analysis_member_node_ids: Iterable[str] = ()
    group_node_ids: Iterable[str] = ()
    local_node_ids: Iterable[str] = ()
    local_road_ids: Iterable[str] = ()
    local_rc_node_ids: Iterable[str] = ()
    local_rc_road_ids: Iterable[str] = ()
    road_branch_ids: Iterable[str] = ()
    analysis_center_xy: tuple[float, float] | None = None


@dataclass(frozen=True)
class Stage3SuccessContractStepSnapshotInputs:
    step3_legal_activity_space_geometry: Any | None
    step3_allowed_drivezone_geometry: Any | None
    step3_must_cover_group_node_ids: Iterable[str]
    step3_single_sided_corridor_road_ids: Iterable[str]
    step3_hard_boundary_road_ids: Iterable[str] = ()
    step3_blockers: Iterable[str] = ()
    step4_result: Stage3Step4RCSemanticsResult | None = None
    step5_foreign_semantic_node_ids: Iterable[str] = ()
    step5_foreign_road_arm_corridor_ids: Iterable[str] = ()
    step5_foreign_rc_context_ids: Iterable[str] = ()
    step5_acceptance_reason: str | None = None
    step5_foreign_overlap_metric_m: float | None = None
    step5_foreign_tail_length_m: float | None = None
    step5_foreign_strip_extent_m: float | None = None
    step5_foreign_overlap_zero_but_tail_present: bool | None = None
    step5_single_sided_unrelated_opposite_lane_trim_applied: bool = False
    step5_soft_excluded_rc_corridor_trim_applied: bool = False
    step5_foreign_overlap_by_id: Mapping[str, float] = field(default_factory=dict)
    step6_primary_solved_geometry: Any | None = None
    step6_geometry_established: bool = False
    step6_max_selected_side_branch_covered_length_m: float | None = None
    step6_selected_node_repair_attempted: bool = False
    step6_selected_node_repair_applied: bool = False
    step6_selected_node_repair_discarded_due_to_extra_roads: bool = False
    step6_introduced_extra_local_road_ids: Iterable[str] = ()
    step6_optimizer_events: Iterable[str] = ()
    step6_late_single_sided_branch_cap_cleanup_applied: bool = False
    step6_late_post_soft_overlap_trim_applied: bool = False
    step6_late_final_foreign_residue_trim_applied: bool = False
    step6_late_single_sided_partial_branch_strip_cleanup_applied: bool = False
    step6_late_single_sided_corridor_mask_cleanup_applied: bool = False
    step6_late_single_sided_tail_clip_cleanup_applied: bool = False
    step6_polygon_aspect_ratio: float | None = None
    step6_polygon_compactness: float | None = None
    step6_polygon_bbox_fill_ratio: float | None = None
    step6_uncovered_selected_endpoint_node_ids: Iterable[str] = ()
    step6_foreign_semantic_node_ids: Iterable[str] = ()
    step6_foreign_road_arm_corridor_ids: Iterable[str] = ()
    step6_foreign_overlap_metric_m: float | None = None
    step6_foreign_tail_length_m: float | None = None
    step6_foreign_overlap_zero_but_tail_present: bool | None = None
    step6_geometry_review_reason: str | None = None


@dataclass(frozen=True)
class Stage3SuccessStepResults:
    context: Stage3Context
    step3_result: Stage3Step3LegalSpaceResult
    step4_result: Stage3Step4RCSemanticsResult | None
    step5_result: Stage3Step5ForeignModelResult
    step6_result: Stage3Step6GeometrySolveResult


def _collect_step6_optimizer_events(
    step_snapshot_inputs: Stage3SuccessContractStepSnapshotInputs,
) -> tuple[str, ...]:
    explicit_optimizer_events = tuple(
        str(event)
        for event in step_snapshot_inputs.step6_optimizer_events
        if event is not None and str(event).strip()
    )
    if explicit_optimizer_events:
        return explicit_optimizer_events
    return tuple(
        name
        for name, applied in (
            ("late_single_sided_branch_cap_cleanup_applied", step_snapshot_inputs.step6_late_single_sided_branch_cap_cleanup_applied),
            ("late_post_soft_overlap_trim_applied", step_snapshot_inputs.step6_late_post_soft_overlap_trim_applied),
            ("late_final_foreign_residue_trim_applied", step_snapshot_inputs.step6_late_final_foreign_residue_trim_applied),
            ("late_single_sided_partial_branch_strip_cleanup_applied", step_snapshot_inputs.step6_late_single_sided_partial_branch_strip_cleanup_applied),
            ("late_single_sided_corridor_mask_cleanup_applied", step_snapshot_inputs.step6_late_single_sided_corridor_mask_cleanup_applied),
            ("late_single_sided_tail_clip_cleanup_applied", step_snapshot_inputs.step6_late_single_sided_tail_clip_cleanup_applied),
        )
        if applied
    )


def build_stage3_success_step_results(
    *,
    identity_inputs: Stage3SuccessContractIdentityInputs,
    step_snapshot_inputs: Stage3SuccessContractStepSnapshotInputs,
) -> Stage3SuccessStepResults:
    return Stage3SuccessStepResults(
        context=build_stage3_context_from_legacy_inputs(
            Stage3LegacyContextInputs(
                representative_node_id=identity_inputs.representative_node_id,
                normalized_mainnodeid=identity_inputs.normalized_mainnodeid,
                template_class=identity_inputs.template_class,
                representative_kind=identity_inputs.representative_kind,
                representative_kind_2=identity_inputs.representative_kind_2,
                representative_grade_2=identity_inputs.representative_grade_2,
                semantic_junction_set=identity_inputs.semantic_junction_set,
                analysis_member_node_ids=identity_inputs.analysis_member_node_ids,
                group_node_ids=identity_inputs.group_node_ids,
                local_node_ids=identity_inputs.local_node_ids,
                local_road_ids=identity_inputs.local_road_ids,
                local_rc_node_ids=identity_inputs.local_rc_node_ids,
                local_rc_road_ids=identity_inputs.local_rc_road_ids,
                road_branch_ids=identity_inputs.road_branch_ids,
                analysis_center_xy=identity_inputs.analysis_center_xy,
            )
        ),
        step3_result=build_stage3_step3_legal_space_result(
            Stage3Step3LegalSpaceInputs(
                template_class=identity_inputs.template_class,
                legal_activity_space_geometry=(
                    step_snapshot_inputs.step3_legal_activity_space_geometry
                ),
                allowed_drivezone_geometry=(
                    step_snapshot_inputs.step3_allowed_drivezone_geometry
                ),
                must_cover_group_node_ids=(
                    step_snapshot_inputs.step3_must_cover_group_node_ids
                ),
                single_sided_corridor_road_ids=(
                    step_snapshot_inputs.step3_single_sided_corridor_road_ids
                ),
                hard_boundary_road_ids=step_snapshot_inputs.step3_hard_boundary_road_ids,
                step3_blockers=step_snapshot_inputs.step3_blockers,
            )
        ),
        step4_result=step_snapshot_inputs.step4_result,
        step5_result=build_stage3_step5_foreign_model_result(
            Stage3Step5ForeignModelInputs(
                foreign_semantic_node_ids=(
                    step_snapshot_inputs.step5_foreign_semantic_node_ids
                ),
                foreign_road_arm_corridor_ids=(
                    step_snapshot_inputs.step5_foreign_road_arm_corridor_ids
                ),
                foreign_rc_context_ids=(
                    step_snapshot_inputs.step5_foreign_rc_context_ids
                ),
                acceptance_reason=step_snapshot_inputs.step5_acceptance_reason,
                foreign_overlap_metric_m=(
                    step_snapshot_inputs.step5_foreign_overlap_metric_m
                ),
                foreign_tail_length_m=step_snapshot_inputs.step5_foreign_tail_length_m,
                foreign_strip_extent_m=(
                    step_snapshot_inputs.step5_foreign_strip_extent_m
                ),
                foreign_overlap_zero_but_tail_present=(
                    step_snapshot_inputs.step5_foreign_overlap_zero_but_tail_present
                ),
                single_sided_unrelated_opposite_lane_trim_applied=(
                    step_snapshot_inputs.step5_single_sided_unrelated_opposite_lane_trim_applied
                ),
                soft_excluded_rc_corridor_trim_applied=(
                    step_snapshot_inputs.step5_soft_excluded_rc_corridor_trim_applied
                ),
                foreign_overlap_by_id=step_snapshot_inputs.step5_foreign_overlap_by_id,
            )
        ),
        step6_result=build_stage3_step6_geometry_solve_result(
            Stage3Step6GeometrySolveInputs(
                primary_solved_geometry=step_snapshot_inputs.step6_primary_solved_geometry,
                geometry_established=step_snapshot_inputs.step6_geometry_established,
                max_selected_side_branch_covered_length_m=(
                    step_snapshot_inputs.step6_max_selected_side_branch_covered_length_m
                ),
                selected_node_repair_attempted=(
                    step_snapshot_inputs.step6_selected_node_repair_attempted
                ),
                selected_node_repair_applied=(
                    step_snapshot_inputs.step6_selected_node_repair_applied
                ),
                selected_node_repair_discarded_due_to_extra_roads=(
                    step_snapshot_inputs.step6_selected_node_repair_discarded_due_to_extra_roads
                ),
                introduced_extra_local_road_ids=(
                    step_snapshot_inputs.step6_introduced_extra_local_road_ids
                ),
                optimizer_events=_collect_step6_optimizer_events(step_snapshot_inputs),
                late_single_sided_branch_cap_cleanup_applied=(
                    step_snapshot_inputs.step6_late_single_sided_branch_cap_cleanup_applied
                ),
                late_post_soft_overlap_trim_applied=(
                    step_snapshot_inputs.step6_late_post_soft_overlap_trim_applied
                ),
                late_final_foreign_residue_trim_applied=(
                    step_snapshot_inputs.step6_late_final_foreign_residue_trim_applied
                ),
                late_single_sided_partial_branch_strip_cleanup_applied=(
                    step_snapshot_inputs.step6_late_single_sided_partial_branch_strip_cleanup_applied
                ),
                late_single_sided_corridor_mask_cleanup_applied=(
                    step_snapshot_inputs.step6_late_single_sided_corridor_mask_cleanup_applied
                ),
                late_single_sided_tail_clip_cleanup_applied=(
                    step_snapshot_inputs.step6_late_single_sided_tail_clip_cleanup_applied
                ),
                polygon_aspect_ratio=step_snapshot_inputs.step6_polygon_aspect_ratio,
                polygon_compactness=step_snapshot_inputs.step6_polygon_compactness,
                polygon_bbox_fill_ratio=step_snapshot_inputs.step6_polygon_bbox_fill_ratio,
                uncovered_selected_endpoint_node_ids=(
                    step_snapshot_inputs.step6_uncovered_selected_endpoint_node_ids
                ),
                foreign_semantic_node_ids=(
                    step_snapshot_inputs.step6_foreign_semantic_node_ids
                ),
                foreign_road_arm_corridor_ids=(
                    step_snapshot_inputs.step6_foreign_road_arm_corridor_ids
                ),
                foreign_overlap_metric_m=(
                    step_snapshot_inputs.step6_foreign_overlap_metric_m
                ),
                foreign_tail_length_m=step_snapshot_inputs.step6_foreign_tail_length_m,
                foreign_overlap_zero_but_tail_present=(
                    step_snapshot_inputs.step6_foreign_overlap_zero_but_tail_present
                ),
                geometry_review_reason=(
                    step_snapshot_inputs.step6_geometry_review_reason
                ),
            )
        ),
    )
