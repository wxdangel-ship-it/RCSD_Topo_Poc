from __future__ import annotations

from dataclasses import dataclass

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_context_builder import (
    Stage3LegacyContextInputs,
    build_stage3_context_from_legacy_inputs,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Step3LegalSpaceResult,
    Stage3Step4RCSemanticsResult,
    Stage3Step5ForeignModelResult,
    Stage3Step6GeometrySolveResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step7_acceptance import (
    Stage3LegacyStep7Assembly,
    Stage3LegacyStep7Inputs,
    build_stage3_legacy_step7_assembly,
)


@dataclass(frozen=True)
class Stage3LegacyStep7ScalarInputs:
    success: bool
    acceptance_class: str
    acceptance_reason: str
    status: str
    representative_has_evd: str | None
    representative_is_anchor: str | None
    representative_kind_2: int | None
    business_match_reason: str | None
    single_sided_t_mouth_corridor_semantic_gap: bool
    final_uncovered_selected_endpoint_node_count: int
    single_sided_unrelated_opposite_lane_trim_applied: bool
    soft_excluded_rc_corridor_trim_applied: bool
    post_trim_non_target_tail_length_m: float
    foreign_overlap_zero_but_tail_present: bool
    selected_rc_node_count: int
    selected_rc_road_count: int
    polygon_support_rc_node_count: int
    polygon_support_rc_road_count: int
    invalid_rc_node_count: int
    invalid_rc_road_count: int
    drivezone_is_empty: bool
    polygon_is_empty: bool
    max_target_group_foreign_semantic_road_overlap_m: float
    max_selected_side_branch_covered_length_m: float
    max_nonmain_branch_polygon_length_m: float
    polygon_aspect_ratio: float | None
    polygon_compactness: float | None
    polygon_bbox_fill_ratio: float | None
    late_single_sided_branch_cap_cleanup_applied: bool = False
    late_post_soft_overlap_trim_applied: bool = False
    late_final_foreign_residue_trim_applied: bool = False
    late_single_sided_partial_branch_strip_cleanup_applied: bool = False
    late_single_sided_corridor_mask_cleanup_applied: bool = False
    late_single_sided_tail_clip_cleanup_applied: bool = False
    step6_optimizer_events: tuple[str, ...] = ()


def build_stage3_legacy_step7_assembly_from_settled_inputs(
    *,
    context_inputs: Stage3LegacyContextInputs,
    scalar_inputs: Stage3LegacyStep7ScalarInputs,
    step3_result: Stage3Step3LegalSpaceResult | None,
    step4_result: Stage3Step4RCSemanticsResult | None,
    step5_result: Stage3Step5ForeignModelResult | None,
    step6_result: Stage3Step6GeometrySolveResult | None,
) -> Stage3LegacyStep7Assembly:
    return build_stage3_legacy_step7_assembly(
        Stage3LegacyStep7Inputs(
            context=build_stage3_context_from_legacy_inputs(context_inputs),
            step3_result=step3_result,
            step4_result=step4_result,
            step5_result=step5_result,
            step6_result=step6_result,
            success=scalar_inputs.success,
            acceptance_class=scalar_inputs.acceptance_class,
            acceptance_reason=scalar_inputs.acceptance_reason,
            status=scalar_inputs.status,
            representative_has_evd=scalar_inputs.representative_has_evd,
            representative_is_anchor=scalar_inputs.representative_is_anchor,
            representative_kind_2=scalar_inputs.representative_kind_2,
            business_match_reason=scalar_inputs.business_match_reason,
            single_sided_t_mouth_corridor_semantic_gap=(
                scalar_inputs.single_sided_t_mouth_corridor_semantic_gap
            ),
            final_uncovered_selected_endpoint_node_count=(
                scalar_inputs.final_uncovered_selected_endpoint_node_count
            ),
            single_sided_unrelated_opposite_lane_trim_applied=(
                scalar_inputs.single_sided_unrelated_opposite_lane_trim_applied
            ),
            soft_excluded_rc_corridor_trim_applied=(
                scalar_inputs.soft_excluded_rc_corridor_trim_applied
            ),
            post_trim_non_target_tail_length_m=(
                scalar_inputs.post_trim_non_target_tail_length_m
            ),
            foreign_overlap_zero_but_tail_present=(
                scalar_inputs.foreign_overlap_zero_but_tail_present
            ),
            step6_optimizer_events=scalar_inputs.step6_optimizer_events,
            selected_rc_node_count=scalar_inputs.selected_rc_node_count,
            selected_rc_road_count=scalar_inputs.selected_rc_road_count,
            polygon_support_rc_node_count=scalar_inputs.polygon_support_rc_node_count,
            polygon_support_rc_road_count=scalar_inputs.polygon_support_rc_road_count,
            invalid_rc_node_count=scalar_inputs.invalid_rc_node_count,
            invalid_rc_road_count=scalar_inputs.invalid_rc_road_count,
            drivezone_is_empty=scalar_inputs.drivezone_is_empty,
            polygon_is_empty=scalar_inputs.polygon_is_empty,
            max_target_group_foreign_semantic_road_overlap_m=(
                scalar_inputs.max_target_group_foreign_semantic_road_overlap_m
            ),
            max_selected_side_branch_covered_length_m=(
                scalar_inputs.max_selected_side_branch_covered_length_m
            ),
            max_nonmain_branch_polygon_length_m=(
                scalar_inputs.max_nonmain_branch_polygon_length_m
            ),
            polygon_aspect_ratio=scalar_inputs.polygon_aspect_ratio,
            polygon_compactness=scalar_inputs.polygon_compactness,
            polygon_bbox_fill_ratio=scalar_inputs.polygon_bbox_fill_ratio,
        )
    )
