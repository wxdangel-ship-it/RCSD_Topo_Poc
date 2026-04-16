from __future__ import annotations

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Step5ForeignModelResult,
    Stage3Step6GeometrySolveResult,
    build_stage3_context,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step7_acceptance import (
    Stage3PostAcceptanceGateInputs,
    Stage3Step7DecisionInputs,
    apply_stage3_post_acceptance_gates_from_inputs,
    build_stage3_step7_assembly_from_results,
)


def _context():
    return build_stage3_context(
        representative_node_id="584253",
        normalized_mainnodeid="584253",
        template_class="center_junction",
    )


def _decision_inputs(**overrides) -> Stage3Step7DecisionInputs:
    defaults = dict(
        success=False,
        acceptance_class="review_required",
        acceptance_reason="rc_gap_with_nonmain_branch_polygon_coverage",
        status="no_valid_rc_connection",
        representative_has_evd="yes",
        representative_is_anchor="no",
        representative_kind_2=4,
        business_match_reason="rcsd_partial_match",
        single_sided_t_mouth_corridor_semantic_gap=False,
        final_uncovered_selected_endpoint_node_count=0,
        selected_rc_node_count=0,
        selected_rc_road_count=0,
        polygon_support_rc_node_count=0,
        polygon_support_rc_road_count=0,
        invalid_rc_node_count=0,
        invalid_rc_road_count=0,
        drivezone_is_empty=False,
        polygon_is_empty=False,
    )
    defaults.update(overrides)
    return Stage3Step7DecisionInputs(**defaults)


def test_nonstable_center_cluster_prefers_step6_canonical_reason():
    assembly = build_stage3_step7_assembly_from_results(
        context=_context(),
        step3_result=None,
        step4_result=None,
        step5_result=None,
        step6_result=Stage3Step6GeometrySolveResult(
            geometry_established=True,
            geometry_review_reason="nonstable_center_junction_extreme_geometry_anomaly",
            optimizer_events=("bounded_regularization_applied",),
        ),
        decision_inputs=_decision_inputs(),
    )

    assert assembly.step7_result.acceptance_class == "review_required"
    assert assembly.step7_result.root_cause_layer == "step6"
    assert (
        assembly.step7_result.root_cause_type
        == "nonstable_center_junction_extreme_geometry_anomaly"
    )
    assert assembly.step7_result.visual_review_class.startswith("V2")
    assert "step6_cluster_canonical_result_selected" in assembly.step7_result.decision_basis
    assert "step6_cluster_delegacy_override_applied" in assembly.step7_result.decision_basis
    assert (
        "step6_cluster_path=center_junction_extreme_geometry_cluster"
        in assembly.step7_result.decision_basis
    )


def test_stable_compound_center_cluster_no_longer_relies_on_accepted_legacy_reason():
    assembly = build_stage3_step7_assembly_from_results(
        context=_context(),
        step3_result=None,
        step4_result=None,
        step5_result=None,
        step6_result=Stage3Step6GeometrySolveResult(
            geometry_established=True,
            geometry_review_reason="stable_compound_center_requires_review",
        ),
        decision_inputs=_decision_inputs(
            success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
        ),
    )

    assert assembly.step7_result.success is False
    assert assembly.step7_result.acceptance_class == "review_required"
    assert assembly.step7_result.root_cause_layer == "step6"
    assert (
        assembly.step7_result.root_cause_type
        == "stable_compound_center_requires_review"
    )
    assert assembly.step7_result.visual_review_class.startswith("V2")
    assert "step6_cluster_canonical_result_selected" in assembly.step7_result.decision_basis


def test_step5_canonical_foreign_still_has_priority_over_cluster_step6_reason():
    assembly = build_stage3_step7_assembly_from_results(
        context=_context(),
        step3_result=None,
        step4_result=None,
        step5_result=Stage3Step5ForeignModelResult(
            foreign_baseline_established=True,
            canonical_foreign_established=True,
            canonical_foreign_reason="foreign_outside_drivezone_soft_excluded",
            foreign_subtype="outside_drivezone_soft_excluded",
        ),
        step6_result=Stage3Step6GeometrySolveResult(
            geometry_established=True,
            geometry_review_reason="nonstable_center_junction_extreme_geometry_anomaly",
            optimizer_events=("bounded_regularization_applied",),
        ),
        decision_inputs=_decision_inputs(
            success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
        ),
    )

    assert assembly.step7_result.root_cause_layer == "step5"
    assert (
        assembly.step7_result.root_cause_type
        == "foreign_outside_drivezone_soft_excluded"
    )
    assert assembly.step7_result.acceptance_class == "rejected"
    assert "step5_result_selected" in assembly.step7_result.decision_basis


def test_post_gate_releases_center_soft_trim_small_residual_with_multi_rc_support():
    decision = apply_stage3_post_acceptance_gates_from_inputs(
        Stage3PostAcceptanceGateInputs(
            effect_success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
            template_class="center_junction",
            can_soft_exclude_outside_rc=True,
            rc_outside_drivezone_error=object(),
            max_target_group_foreign_semantic_road_overlap_m=1.95,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=0.0,
            min_invalid_rc_distance_to_center_m=8.0,
            associated_rc_road_count=4,
            associated_rc_node_count=4,
            effective_associated_rc_node_count=4,
            excluded_rc_road_count=2,
            positive_rc_group_count=2,
            negative_rc_group_count=0,
            local_node_count=3,
            local_road_count=6,
            polygon_aspect_ratio=5.0,
            polygon_compactness=0.22,
            polygon_bbox_fill_ratio=0.30,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=True,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            audit_rows=(),
        )
    )

    assert decision.effect_success is True
    assert decision.acceptance_class == "accepted"
    assert decision.acceptance_reason == "stable"


def test_post_gate_keeps_review_gap_for_center_soft_trim_small_residual_without_multi_rc_release_signature():
    decision = apply_stage3_post_acceptance_gates_from_inputs(
        Stage3PostAcceptanceGateInputs(
            effect_success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
            template_class="center_junction",
            can_soft_exclude_outside_rc=True,
            rc_outside_drivezone_error=object(),
            max_target_group_foreign_semantic_road_overlap_m=1.95,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=0.0,
            min_invalid_rc_distance_to_center_m=8.0,
            associated_rc_road_count=1,
            associated_rc_node_count=1,
            effective_associated_rc_node_count=1,
            excluded_rc_road_count=2,
            positive_rc_group_count=1,
            negative_rc_group_count=0,
            local_node_count=2,
            local_road_count=5,
            polygon_aspect_ratio=1.5,
            polygon_compactness=0.57,
            polygon_bbox_fill_ratio=0.51,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=True,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            audit_rows=(),
        )
    )

    assert decision.effect_success is False
    assert decision.acceptance_class == "review_required"
    assert decision.acceptance_reason == "outside_rc_gap_requires_review"


def test_post_gate_preserves_stable_accept_when_small_residual_foreign_has_no_dependency():
    decision = apply_stage3_post_acceptance_gates_from_inputs(
        Stage3PostAcceptanceGateInputs(
            effect_success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
            template_class="center_junction",
            can_soft_exclude_outside_rc=True,
            rc_outside_drivezone_error=object(),
            max_target_group_foreign_semantic_road_overlap_m=1.95,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=0.0,
            min_invalid_rc_distance_to_center_m=8.0,
            associated_rc_road_count=4,
            associated_rc_node_count=4,
            effective_associated_rc_node_count=4,
            excluded_rc_road_count=1,
            positive_rc_group_count=2,
            negative_rc_group_count=0,
            local_node_count=2,
            local_road_count=6,
            polygon_aspect_ratio=1.5,
            polygon_compactness=0.57,
            polygon_bbox_fill_ratio=0.51,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            audit_rows=(),
        )
    )

    assert decision.effect_success is True
    assert decision.acceptance_class == "accepted"
    assert decision.acceptance_reason == "stable"


def test_post_gate_keeps_high_overlap_foreign_blocking_for_a_cluster_signature():
    decision = apply_stage3_post_acceptance_gates_from_inputs(
        Stage3PostAcceptanceGateInputs(
            effect_success=True,
            acceptance_class="accepted",
            acceptance_reason="stable",
            status="stable",
            template_class="single_sided_t_mouth",
            can_soft_exclude_outside_rc=True,
            rc_outside_drivezone_error=object(),
            max_target_group_foreign_semantic_road_overlap_m=11.8,
            max_selected_side_branch_covered_length_m=0.0,
            max_nonmain_branch_polygon_length_m=4.0,
            min_invalid_rc_distance_to_center_m=8.0,
            associated_rc_road_count=2,
            associated_rc_node_count=2,
            effective_associated_rc_node_count=2,
            excluded_rc_road_count=0,
            positive_rc_group_count=1,
            negative_rc_group_count=1,
            local_node_count=2,
            local_road_count=4,
            polygon_aspect_ratio=1.5,
            polygon_compactness=0.23,
            polygon_bbox_fill_ratio=0.38,
            single_sided_unrelated_opposite_lane_trim_applied=False,
            soft_excluded_rc_corridor_trim_applied=False,
            post_trim_non_target_tail_length_m=0.0,
            foreign_overlap_zero_but_tail_present=False,
            audit_rows=(),
        )
    )

    assert decision.effect_success is False
    assert decision.acceptance_class == "review_required"
    assert decision.acceptance_reason == "foreign_outside_drivezone_soft_excluded"
