from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Step4RCSemanticsResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_success_step_result_builder import (
    Stage3SuccessContractStepSnapshotInputs,
)


@dataclass(frozen=True)
class Stage3SuccessStep3SnapshotInputs:
    legal_activity_space_geometry: Any | None
    allowed_drivezone_geometry: Any | None
    must_cover_group_node_ids: Iterable[str]
    single_sided_corridor_road_ids: Iterable[str]
    hard_boundary_road_ids: Iterable[str] = ()
    blockers: Iterable[str] = ()


@dataclass(frozen=True)
class Stage3SuccessStep5SnapshotInputs:
    foreign_semantic_node_ids: Iterable[str] = ()
    foreign_road_arm_corridor_ids: Iterable[str] = ()
    foreign_rc_context_ids: Iterable[str] = ()
    acceptance_reason: str | None = None
    foreign_overlap_metric_m: float | None = None
    foreign_tail_length_m: float | None = None
    foreign_strip_extent_m: float | None = None
    foreign_overlap_zero_but_tail_present: bool | None = None
    single_sided_unrelated_opposite_lane_trim_applied: bool = False
    soft_excluded_rc_corridor_trim_applied: bool = False
    foreign_overlap_by_id: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Stage3SuccessStep6SnapshotInputs:
    primary_solved_geometry: Any | None = None
    geometry_established: bool = False
    max_selected_side_branch_covered_length_m: float | None = None
    selected_node_repair_attempted: bool = False
    selected_node_repair_applied: bool = False
    selected_node_repair_discarded_due_to_extra_roads: bool = False
    introduced_extra_local_road_ids: Iterable[str] = ()
    optimizer_events: Iterable[str] = ()
    late_single_sided_branch_cap_cleanup_applied: bool = False
    late_post_soft_overlap_trim_applied: bool = False
    late_final_foreign_residue_trim_applied: bool = False
    late_single_sided_partial_branch_strip_cleanup_applied: bool = False
    late_single_sided_corridor_mask_cleanup_applied: bool = False
    late_single_sided_tail_clip_cleanup_applied: bool = False
    polygon_aspect_ratio: float | None = None
    polygon_compactness: float | None = None
    polygon_bbox_fill_ratio: float | None = None
    uncovered_selected_endpoint_node_ids: Iterable[str] = ()
    foreign_semantic_node_ids: Iterable[str] = ()
    foreign_road_arm_corridor_ids: Iterable[str] = ()
    foreign_overlap_metric_m: float | None = None
    foreign_tail_length_m: float | None = None
    foreign_overlap_zero_but_tail_present: bool | None = None
    geometry_review_reason: str | None = None


@dataclass(frozen=True)
class Stage3SuccessSnapshotBuildInputs:
    step3: Stage3SuccessStep3SnapshotInputs
    step4_result: Stage3Step4RCSemanticsResult | None
    step5: Stage3SuccessStep5SnapshotInputs
    step6: Stage3SuccessStep6SnapshotInputs


def build_stage3_success_step_snapshot_inputs(
    inputs: Stage3SuccessSnapshotBuildInputs,
) -> Stage3SuccessContractStepSnapshotInputs:
    return Stage3SuccessContractStepSnapshotInputs(
        step3_legal_activity_space_geometry=inputs.step3.legal_activity_space_geometry,
        step3_allowed_drivezone_geometry=inputs.step3.allowed_drivezone_geometry,
        step3_must_cover_group_node_ids=inputs.step3.must_cover_group_node_ids,
        step3_single_sided_corridor_road_ids=inputs.step3.single_sided_corridor_road_ids,
        step3_hard_boundary_road_ids=inputs.step3.hard_boundary_road_ids,
        step3_blockers=inputs.step3.blockers,
        step4_result=inputs.step4_result,
        step5_foreign_semantic_node_ids=inputs.step5.foreign_semantic_node_ids,
        step5_foreign_road_arm_corridor_ids=inputs.step5.foreign_road_arm_corridor_ids,
        step5_foreign_rc_context_ids=inputs.step5.foreign_rc_context_ids,
        step5_acceptance_reason=inputs.step5.acceptance_reason,
        step5_foreign_overlap_metric_m=inputs.step5.foreign_overlap_metric_m,
        step5_foreign_tail_length_m=inputs.step5.foreign_tail_length_m,
        step5_foreign_strip_extent_m=inputs.step5.foreign_strip_extent_m,
        step5_foreign_overlap_zero_but_tail_present=inputs.step5.foreign_overlap_zero_but_tail_present,
        step5_single_sided_unrelated_opposite_lane_trim_applied=(
            inputs.step5.single_sided_unrelated_opposite_lane_trim_applied
        ),
        step5_soft_excluded_rc_corridor_trim_applied=inputs.step5.soft_excluded_rc_corridor_trim_applied,
        step5_foreign_overlap_by_id=inputs.step5.foreign_overlap_by_id,
        step6_primary_solved_geometry=inputs.step6.primary_solved_geometry,
        step6_geometry_established=inputs.step6.geometry_established,
        step6_max_selected_side_branch_covered_length_m=inputs.step6.max_selected_side_branch_covered_length_m,
        step6_selected_node_repair_attempted=inputs.step6.selected_node_repair_attempted,
        step6_selected_node_repair_applied=inputs.step6.selected_node_repair_applied,
        step6_selected_node_repair_discarded_due_to_extra_roads=(
            inputs.step6.selected_node_repair_discarded_due_to_extra_roads
        ),
        step6_introduced_extra_local_road_ids=inputs.step6.introduced_extra_local_road_ids,
        step6_optimizer_events=inputs.step6.optimizer_events,
        step6_late_single_sided_branch_cap_cleanup_applied=(
            inputs.step6.late_single_sided_branch_cap_cleanup_applied
        ),
        step6_late_post_soft_overlap_trim_applied=inputs.step6.late_post_soft_overlap_trim_applied,
        step6_late_final_foreign_residue_trim_applied=inputs.step6.late_final_foreign_residue_trim_applied,
        step6_late_single_sided_partial_branch_strip_cleanup_applied=(
            inputs.step6.late_single_sided_partial_branch_strip_cleanup_applied
        ),
        step6_late_single_sided_corridor_mask_cleanup_applied=(
            inputs.step6.late_single_sided_corridor_mask_cleanup_applied
        ),
        step6_late_single_sided_tail_clip_cleanup_applied=(
            inputs.step6.late_single_sided_tail_clip_cleanup_applied
        ),
        step6_polygon_aspect_ratio=inputs.step6.polygon_aspect_ratio,
        step6_polygon_compactness=inputs.step6.polygon_compactness,
        step6_polygon_bbox_fill_ratio=inputs.step6.polygon_bbox_fill_ratio,
        step6_uncovered_selected_endpoint_node_ids=inputs.step6.uncovered_selected_endpoint_node_ids,
        step6_foreign_semantic_node_ids=inputs.step6.foreign_semantic_node_ids,
        step6_foreign_road_arm_corridor_ids=inputs.step6.foreign_road_arm_corridor_ids,
        step6_foreign_overlap_metric_m=inputs.step6.foreign_overlap_metric_m,
        step6_foreign_tail_length_m=inputs.step6.foreign_tail_length_m,
        step6_foreign_overlap_zero_but_tail_present=inputs.step6.foreign_overlap_zero_but_tail_present,
        step6_geometry_review_reason=inputs.step6.geometry_review_reason,
    )
