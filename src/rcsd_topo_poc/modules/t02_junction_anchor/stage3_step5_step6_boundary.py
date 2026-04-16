from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Step4RCSemanticsResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_success_snapshot_builder import (
    Stage3SuccessSnapshotBuildInputs,
    Stage3SuccessStep3SnapshotInputs,
    Stage3SuccessStep5SnapshotInputs,
    Stage3SuccessStep6SnapshotInputs,
    build_stage3_success_step_snapshot_inputs,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_success_step_result_builder import (
    Stage3SuccessContractStepSnapshotInputs,
)


@dataclass(frozen=True)
class Stage3Step5BaselineSnapshot:
    foreign_semantic_node_ids: tuple[str, ...] = ()
    foreign_road_arm_corridor_ids: tuple[str, ...] = ()
    foreign_rc_context_ids: tuple[str, ...] = ()
    acceptance_reason: str | None = None
    foreign_overlap_metric_m: float | None = None
    foreign_tail_length_m: float | None = None
    foreign_strip_extent_m: float | None = None
    foreign_overlap_zero_but_tail_present: bool | None = None
    single_sided_unrelated_opposite_lane_trim_applied: bool = False
    soft_excluded_rc_corridor_trim_applied: bool = False
    foreign_overlap_by_id: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Stage3Step6FinalStateSnapshot:
    primary_solved_geometry: Any | None = None
    geometry_established: bool = False
    max_selected_side_branch_covered_length_m: float | None = None
    selected_node_repair_attempted: bool = False
    selected_node_repair_applied: bool = False
    selected_node_repair_discarded_due_to_extra_roads: bool = False
    introduced_extra_local_road_ids: tuple[str, ...] = ()
    optimizer_events: tuple[str, ...] = ()
    late_single_sided_branch_cap_cleanup_applied: bool = False
    late_post_soft_overlap_trim_applied: bool = False
    late_final_foreign_residue_trim_applied: bool = False
    late_single_sided_partial_branch_strip_cleanup_applied: bool = False
    late_single_sided_corridor_mask_cleanup_applied: bool = False
    late_single_sided_tail_clip_cleanup_applied: bool = False
    polygon_aspect_ratio: float | None = None
    polygon_compactness: float | None = None
    polygon_bbox_fill_ratio: float | None = None
    uncovered_selected_endpoint_node_ids: tuple[str, ...] = ()
    foreign_semantic_node_ids: tuple[str, ...] = ()
    foreign_road_arm_corridor_ids: tuple[str, ...] = ()
    foreign_overlap_metric_m: float | None = None
    foreign_tail_length_m: float | None = None
    foreign_overlap_zero_but_tail_present: bool | None = None
    geometry_review_reason: str | None = None


def _sorted_ids(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(value)
                for value in values
                if value is not None and str(value).strip()
            }
        )
    )


def freeze_stage3_step5_baseline(
    *,
    foreign_semantic_node_ids: Iterable[str],
    foreign_road_arm_corridor_ids: Iterable[str],
    acceptance_reason: str | None,
    foreign_overlap_metric_m: float | None,
    foreign_tail_length_m: float | None,
    foreign_strip_extent_m: float | None,
    foreign_overlap_zero_but_tail_present: bool | None,
    single_sided_unrelated_opposite_lane_trim_applied: bool,
    soft_excluded_rc_corridor_trim_applied: bool,
    foreign_overlap_by_id: Mapping[str, float],
    foreign_rc_context_ids: Iterable[str] = (),
) -> Stage3Step5BaselineSnapshot:
    return Stage3Step5BaselineSnapshot(
        foreign_semantic_node_ids=_sorted_ids(foreign_semantic_node_ids),
        foreign_road_arm_corridor_ids=_sorted_ids(foreign_road_arm_corridor_ids),
        foreign_rc_context_ids=_sorted_ids(foreign_rc_context_ids),
        acceptance_reason=acceptance_reason,
        foreign_overlap_metric_m=foreign_overlap_metric_m,
        foreign_tail_length_m=foreign_tail_length_m,
        foreign_strip_extent_m=foreign_strip_extent_m,
        foreign_overlap_zero_but_tail_present=foreign_overlap_zero_but_tail_present,
        single_sided_unrelated_opposite_lane_trim_applied=(
            single_sided_unrelated_opposite_lane_trim_applied
        ),
        soft_excluded_rc_corridor_trim_applied=(
            soft_excluded_rc_corridor_trim_applied
        ),
        foreign_overlap_by_id=dict(foreign_overlap_by_id),
    )


def build_stage3_step6_final_state_snapshot(
    *,
    primary_solved_geometry: Any | None,
    geometry_established: bool,
    max_selected_side_branch_covered_length_m: float | None,
    selected_node_repair_attempted: bool,
    selected_node_repair_applied: bool,
    selected_node_repair_discarded_due_to_extra_roads: bool,
    introduced_extra_local_road_ids: Iterable[str],
    optimizer_events: Iterable[str],
    late_single_sided_branch_cap_cleanup_applied: bool,
    late_post_soft_overlap_trim_applied: bool,
    late_final_foreign_residue_trim_applied: bool,
    late_single_sided_partial_branch_strip_cleanup_applied: bool,
    late_single_sided_corridor_mask_cleanup_applied: bool,
    late_single_sided_tail_clip_cleanup_applied: bool,
    polygon_aspect_ratio: float | None,
    polygon_compactness: float | None,
    polygon_bbox_fill_ratio: float | None,
    uncovered_selected_endpoint_node_ids: Iterable[str],
    foreign_semantic_node_ids: Iterable[str],
    foreign_road_arm_corridor_ids: Iterable[str],
    foreign_overlap_metric_m: float | None,
    foreign_tail_length_m: float | None,
    foreign_overlap_zero_but_tail_present: bool | None,
    geometry_review_reason: str | None,
) -> Stage3Step6FinalStateSnapshot:
    return Stage3Step6FinalStateSnapshot(
        primary_solved_geometry=primary_solved_geometry,
        geometry_established=geometry_established,
        max_selected_side_branch_covered_length_m=(
            max_selected_side_branch_covered_length_m
        ),
        selected_node_repair_attempted=selected_node_repair_attempted,
        selected_node_repair_applied=selected_node_repair_applied,
        selected_node_repair_discarded_due_to_extra_roads=(
            selected_node_repair_discarded_due_to_extra_roads
        ),
        introduced_extra_local_road_ids=_sorted_ids(introduced_extra_local_road_ids),
        optimizer_events=tuple(
            str(event)
            for event in optimizer_events
            if event is not None and str(event).strip()
        ),
        late_single_sided_branch_cap_cleanup_applied=(
            late_single_sided_branch_cap_cleanup_applied
        ),
        late_post_soft_overlap_trim_applied=late_post_soft_overlap_trim_applied,
        late_final_foreign_residue_trim_applied=(
            late_final_foreign_residue_trim_applied
        ),
        late_single_sided_partial_branch_strip_cleanup_applied=(
            late_single_sided_partial_branch_strip_cleanup_applied
        ),
        late_single_sided_corridor_mask_cleanup_applied=(
            late_single_sided_corridor_mask_cleanup_applied
        ),
        late_single_sided_tail_clip_cleanup_applied=(
            late_single_sided_tail_clip_cleanup_applied
        ),
        polygon_aspect_ratio=polygon_aspect_ratio,
        polygon_compactness=polygon_compactness,
        polygon_bbox_fill_ratio=polygon_bbox_fill_ratio,
        uncovered_selected_endpoint_node_ids=_sorted_ids(
            uncovered_selected_endpoint_node_ids
        ),
        foreign_semantic_node_ids=_sorted_ids(foreign_semantic_node_ids),
        foreign_road_arm_corridor_ids=_sorted_ids(foreign_road_arm_corridor_ids),
        foreign_overlap_metric_m=foreign_overlap_metric_m,
        foreign_tail_length_m=foreign_tail_length_m,
        foreign_overlap_zero_but_tail_present=foreign_overlap_zero_but_tail_present,
        geometry_review_reason=geometry_review_reason,
    )


def build_stage3_step_snapshot_inputs_from_boundary(
    *,
    step3_inputs: Stage3SuccessStep3SnapshotInputs,
    step4_result: Stage3Step4RCSemanticsResult | None,
    step5_baseline: Stage3Step5BaselineSnapshot,
    step6_final_state: Stage3Step6FinalStateSnapshot,
) -> Stage3SuccessContractStepSnapshotInputs:
    return build_stage3_success_step_snapshot_inputs(
        Stage3SuccessSnapshotBuildInputs(
            step3=step3_inputs,
            step4_result=step4_result,
            step5=Stage3SuccessStep5SnapshotInputs(
                foreign_semantic_node_ids=step5_baseline.foreign_semantic_node_ids,
                foreign_road_arm_corridor_ids=(
                    step5_baseline.foreign_road_arm_corridor_ids
                ),
                foreign_rc_context_ids=step5_baseline.foreign_rc_context_ids,
                acceptance_reason=step5_baseline.acceptance_reason,
                foreign_overlap_metric_m=step5_baseline.foreign_overlap_metric_m,
                foreign_tail_length_m=step5_baseline.foreign_tail_length_m,
                foreign_strip_extent_m=step5_baseline.foreign_strip_extent_m,
                foreign_overlap_zero_but_tail_present=(
                    step5_baseline.foreign_overlap_zero_but_tail_present
                ),
                single_sided_unrelated_opposite_lane_trim_applied=(
                    step5_baseline.single_sided_unrelated_opposite_lane_trim_applied
                ),
                soft_excluded_rc_corridor_trim_applied=(
                    step5_baseline.soft_excluded_rc_corridor_trim_applied
                ),
                foreign_overlap_by_id=step5_baseline.foreign_overlap_by_id,
            ),
            step6=Stage3SuccessStep6SnapshotInputs(
                primary_solved_geometry=step6_final_state.primary_solved_geometry,
                geometry_established=step6_final_state.geometry_established,
                max_selected_side_branch_covered_length_m=(
                    step6_final_state.max_selected_side_branch_covered_length_m
                ),
                selected_node_repair_attempted=(
                    step6_final_state.selected_node_repair_attempted
                ),
                selected_node_repair_applied=step6_final_state.selected_node_repair_applied,
                selected_node_repair_discarded_due_to_extra_roads=(
                    step6_final_state.selected_node_repair_discarded_due_to_extra_roads
                ),
                introduced_extra_local_road_ids=(
                    step6_final_state.introduced_extra_local_road_ids
                ),
                optimizer_events=step6_final_state.optimizer_events,
                late_single_sided_branch_cap_cleanup_applied=(
                    step6_final_state.late_single_sided_branch_cap_cleanup_applied
                ),
                late_post_soft_overlap_trim_applied=(
                    step6_final_state.late_post_soft_overlap_trim_applied
                ),
                late_final_foreign_residue_trim_applied=(
                    step6_final_state.late_final_foreign_residue_trim_applied
                ),
                late_single_sided_partial_branch_strip_cleanup_applied=(
                    step6_final_state.late_single_sided_partial_branch_strip_cleanup_applied
                ),
                late_single_sided_corridor_mask_cleanup_applied=(
                    step6_final_state.late_single_sided_corridor_mask_cleanup_applied
                ),
                late_single_sided_tail_clip_cleanup_applied=(
                    step6_final_state.late_single_sided_tail_clip_cleanup_applied
                ),
                polygon_aspect_ratio=step6_final_state.polygon_aspect_ratio,
                polygon_compactness=step6_final_state.polygon_compactness,
                polygon_bbox_fill_ratio=step6_final_state.polygon_bbox_fill_ratio,
                uncovered_selected_endpoint_node_ids=(
                    step6_final_state.uncovered_selected_endpoint_node_ids
                ),
                foreign_semantic_node_ids=step6_final_state.foreign_semantic_node_ids,
                foreign_road_arm_corridor_ids=(
                    step6_final_state.foreign_road_arm_corridor_ids
                ),
                foreign_overlap_metric_m=step6_final_state.foreign_overlap_metric_m,
                foreign_tail_length_m=step6_final_state.foreign_tail_length_m,
                foreign_overlap_zero_but_tail_present=(
                    step6_final_state.foreign_overlap_zero_but_tail_present
                ),
                geometry_review_reason=step6_final_state.geometry_review_reason,
            ),
        )
    )
