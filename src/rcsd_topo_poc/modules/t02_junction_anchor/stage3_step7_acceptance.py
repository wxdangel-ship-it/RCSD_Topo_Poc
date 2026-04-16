from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable, Sequence

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3Context,
    Stage3Step3LegalSpaceResult,
    Stage3Step4RCSemanticsResult,
    Stage3Step5ForeignModelResult,
    Stage3Step6GeometrySolveResult,
    Stage3Step7AcceptanceResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step5_foreign_model import (
    STEP5_SMALL_RESIDUAL_FOREIGN_OVERLAP_M,
    Stage3Step5ContractDecision,
    resolve_stage3_step5_contract_decision,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_facts import (
    BUSINESS_OUTCOME_FAILURE,
    BUSINESS_OUTCOME_RISK,
    ROOT_CAUSE_LAYER_STEP3,
    ROOT_CAUSE_LAYER_STEP4,
    ROOT_CAUSE_LAYER_STEP5,
    ROOT_CAUSE_LAYER_STEP6,
    VISUAL_REVIEW_V5,
    Stage3ReviewFields,
    acceptance_class_from_business_outcome,
    business_outcome_from_visual_review_class,
    derive_stage3_review_fields,
    success_flag_from_business_outcome,
)

TEMPLATE_GENERIC_JUNCTION = "generic_junction"
TEMPLATE_SINGLE_SIDED_T_MOUTH = "single_sided_t_mouth"
TEMPLATE_CENTER_JUNCTION = "center_junction"

STATUS_STABLE = "stable"
STATUS_SURFACE_ONLY = "surface_only"
STATUS_WEAK_BRANCH_SUPPORT = "weak_branch_support"
STATUS_AMBIGUOUS_RC_MATCH = "ambiguous_rc_match"
STATUS_NO_VALID_RC_CONNECTION = "no_valid_rc_connection"
STATUS_NODE_COMPONENT_CONFLICT = "node_component_conflict"
_STEP6_CLUSTER_CANONICAL_REASONS = {
    "nonstable_center_junction_extreme_geometry_anomaly": (
        "center_junction_extreme_geometry_cluster"
    ),
    "stable_compound_center_requires_review": (
        "center_junction_compound_center_cluster"
    ),
}


def _is_step5_small_residual_provenance_only_signature(
    *,
    max_target_group_foreign_semantic_road_overlap_m: float,
    single_sided_unrelated_opposite_lane_trim_applied: bool,
    post_trim_non_target_tail_length_m: float,
    foreign_overlap_zero_but_tail_present: bool,
) -> bool:
    return (
        max_target_group_foreign_semantic_road_overlap_m
        <= STEP5_SMALL_RESIDUAL_FOREIGN_OVERLAP_M
        and not single_sided_unrelated_opposite_lane_trim_applied
        and post_trim_non_target_tail_length_m <= 0.0
        and not foreign_overlap_zero_but_tail_present
    )


def _should_release_center_soft_excluded_small_residual_to_accepted(
    *,
    effect_success: bool,
    acceptance_class: str,
    acceptance_reason: str,
    template_class: str,
    step5_small_residual_provenance_only: bool,
    soft_excluded_rc_corridor_trim_applied: bool,
    associated_rc_road_count: int,
    excluded_rc_road_count: int,
    negative_rc_group_count: int,
    local_road_count: int,
    max_selected_side_branch_covered_length_m: float,
    max_nonmain_branch_polygon_length_m: float,
) -> bool:
    return (
        effect_success
        and acceptance_class == "accepted"
        and acceptance_reason == "stable"
        and template_class == TEMPLATE_CENTER_JUNCTION
        and step5_small_residual_provenance_only
        and soft_excluded_rc_corridor_trim_applied
        and associated_rc_road_count >= 2
        and excluded_rc_road_count >= 2
        and negative_rc_group_count == 0
        and local_road_count <= 6
        and max_selected_side_branch_covered_length_m <= 0.5
        and max_nonmain_branch_polygon_length_m <= 4.0
    )


@dataclass(frozen=True)
class Stage3LegacyStep7Inputs:
    context: Stage3Context
    step3_result: Stage3Step3LegalSpaceResult | None
    step4_result: Stage3Step4RCSemanticsResult | None
    step5_result: Stage3Step5ForeignModelResult | None
    step6_result: Stage3Step6GeometrySolveResult | None
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
    step6_optimizer_events: Iterable[str] = ()


@dataclass(frozen=True)
class Stage3Step7DecisionInputs:
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
    selected_rc_node_count: int
    selected_rc_road_count: int
    polygon_support_rc_node_count: int
    polygon_support_rc_road_count: int
    invalid_rc_node_count: int
    invalid_rc_road_count: int
    drivezone_is_empty: bool
    polygon_is_empty: bool


@dataclass(frozen=True)
class Stage3LegacyStep7DecisionInputs(Stage3Step7DecisionInputs):
    pass


@dataclass(frozen=True)
class Stage3AcceptanceHeuristicInputs:
    status: str
    review_mode: bool
    template_class: str
    max_selected_side_branch_covered_length_m: float
    max_nonmain_branch_polygon_length_m: float
    associated_rc_road_count: int
    polygon_support_rc_node_count: int
    polygon_support_rc_road_count: int
    min_invalid_rc_distance_to_center_m: float | None
    local_rc_road_count: int
    local_rc_node_count: int
    effective_local_rc_node_count: int | None
    local_road_count: int
    local_node_count: int
    connected_rc_group_count: int
    nonmain_branch_connected_rc_group_count: int
    negative_rc_group_count: int
    positive_rc_group_count: int
    road_branch_count: int | None
    has_structural_side_branch: bool
    max_nonmain_edge_branch_road_support_m: float
    max_nonmain_edge_branch_rc_support_m: float
    excluded_local_rc_road_count: int
    excluded_local_rc_node_count: int
    covered_extra_local_node_count: int
    covered_extra_local_road_count: int
    has_main_edge_only_branch: bool
    representative_kind_2: int | None
    effective_associated_rc_node_count: int
    associated_nonzero_mainnode_count: int
    final_selected_node_cover_repair_discarded_due_to_extra_roads: bool
    single_sided_t_mouth_corridor_pattern_detected: bool
    single_sided_t_mouth_corridor_semantic_gap: bool
    multi_node_selected_cover_repair_applied: bool
    final_uncovered_selected_endpoint_node_count: int
    single_sided_unrelated_opposite_lane_trim_applied: bool
    step4_result: Stage3Step4RCSemanticsResult | None = None


@dataclass(frozen=True)
class Stage3AcceptanceDecision:
    effect_success: bool
    acceptance_class: str
    acceptance_reason: str


@dataclass(frozen=True)
class Stage3PostAcceptanceGateInputs:
    effect_success: bool
    acceptance_class: str
    acceptance_reason: str
    status: str
    template_class: str
    can_soft_exclude_outside_rc: bool
    rc_outside_drivezone_error: Any | None
    max_target_group_foreign_semantic_road_overlap_m: float
    max_selected_side_branch_covered_length_m: float
    max_nonmain_branch_polygon_length_m: float
    min_invalid_rc_distance_to_center_m: float | None
    associated_rc_road_count: int
    associated_rc_node_count: int
    effective_associated_rc_node_count: int
    excluded_rc_road_count: int
    positive_rc_group_count: int
    negative_rc_group_count: int
    local_node_count: int
    local_road_count: int
    polygon_aspect_ratio: float | None
    polygon_compactness: float | None
    polygon_bbox_fill_ratio: float | None
    single_sided_unrelated_opposite_lane_trim_applied: bool
    soft_excluded_rc_corridor_trim_applied: bool
    post_trim_non_target_tail_length_m: float
    foreign_overlap_zero_but_tail_present: bool
    audit_rows: Sequence[dict[str, Any]]


def effect_success_acceptance(
    *,
    status: str,
    review_mode: bool,
    template_class: str = TEMPLATE_GENERIC_JUNCTION,
    max_selected_side_branch_covered_length_m: float,
    max_nonmain_branch_polygon_length_m: float,
    associated_rc_road_count: int,
    polygon_support_rc_node_count: int = 0,
    polygon_support_rc_road_count: int = 0,
    min_invalid_rc_distance_to_center_m: float | None,
    local_rc_road_count: int,
    local_rc_node_count: int,
    effective_local_rc_node_count: int | None = None,
    local_road_count: int,
    local_node_count: int,
    connected_rc_group_count: int,
    nonmain_branch_connected_rc_group_count: int,
    negative_rc_group_count: int,
    positive_rc_group_count: int = 0,
    road_branch_count: int | None = None,
    has_structural_side_branch: bool = True,
    max_nonmain_edge_branch_road_support_m: float = 0.0,
    max_nonmain_edge_branch_rc_support_m: float = 0.0,
    excluded_local_rc_road_count: int = 0,
    excluded_local_rc_node_count: int = 0,
    covered_extra_local_node_count: int = 0,
    covered_extra_local_road_count: int = 0,
    has_main_edge_only_branch: bool = False,
    representative_kind_2: int | None = None,
    effective_associated_rc_node_count: int = 0,
    associated_nonzero_mainnode_count: int = 0,
    final_selected_node_cover_repair_discarded_due_to_extra_roads: bool = False,
    single_sided_t_mouth_corridor_pattern_detected: bool = False,
    single_sided_t_mouth_corridor_semantic_gap: bool = False,
    multi_node_selected_cover_repair_applied: bool = False,
    final_uncovered_selected_endpoint_node_count: int = 0,
    single_sided_unrelated_opposite_lane_trim_applied: bool = False,
) -> tuple[bool, str, str]:
    if effective_local_rc_node_count is None:
        effective_local_rc_node_count = local_rc_node_count
    has_excluded_local_rc = (
        excluded_local_rc_road_count > 0
        or excluded_local_rc_node_count > 0
    )
    if covered_extra_local_node_count > 0 or covered_extra_local_road_count > 0:
        if status == STATUS_STABLE:
            return False, "review_required", "stable_with_foreign_swsd_intrusion"
        return False, "review_required", f"review_required_status:{status}"
    if status == STATUS_STABLE:
        if (
            template_class == TEMPLATE_SINGLE_SIDED_T_MOUTH
            and single_sided_t_mouth_corridor_semantic_gap
            and associated_nonzero_mainnode_count == 0
        ):
            if final_uncovered_selected_endpoint_node_count > 0:
                return False, "review_required", "stable_with_incomplete_t_mouth_rc_context"
        if (
            template_class == TEMPLATE_SINGLE_SIDED_T_MOUTH
            and positive_rc_group_count >= 2
            and negative_rc_group_count >= 1
            and associated_nonzero_mainnode_count == 0
            and associated_rc_road_count >= 3
            and effective_associated_rc_node_count >= 3
        ):
            return False, "review_required", "stable_with_rc_group_semantic_gap"
        if (
            template_class == TEMPLATE_SINGLE_SIDED_T_MOUTH
            and associated_rc_road_count <= 1
            and polygon_support_rc_node_count == 0
            and effective_associated_rc_node_count == 0
            and (
                max_nonmain_branch_polygon_length_m >= 20.0
                or final_selected_node_cover_repair_discarded_due_to_extra_roads
            )
        ):
            return False, "review_required", "stable_with_incomplete_t_mouth_rc_context"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_node_count == 0
            and effective_associated_rc_node_count == 0
            and local_rc_road_count >= 20
            and effective_local_rc_node_count >= 2
        ):
            return False, "review_required", "stable_with_sparse_rc_association_against_dense_local_rcsd_context"
        if (
            template_class == TEMPLATE_SINGLE_SIDED_T_MOUTH
            and not single_sided_unrelated_opposite_lane_trim_applied
            and has_excluded_local_rc
            and associated_rc_road_count >= 2
            and polygon_support_rc_road_count >= 2
            and polygon_support_rc_node_count <= 1
            and effective_local_rc_node_count == 0
            and effective_associated_rc_node_count == 0
            and associated_nonzero_mainnode_count == 0
            and max_nonmain_branch_polygon_length_m >= 10.0
            and max_selected_side_branch_covered_length_m <= 3.0
            and min_invalid_rc_distance_to_center_m is not None
            and min_invalid_rc_distance_to_center_m <= 8.0
        ):
            return False, "review_required", "stable_with_unrelated_opposite_lane_corridor"
        if has_main_edge_only_branch:
            return False, "review_required", "stable_with_weak_main_direction"
        return True, "accepted", "stable"
    if status == STATUS_SURFACE_ONLY:
        if (
            not has_excluded_local_rc
            and local_rc_road_count == 0
            and effective_local_rc_node_count == 0
        ):
            return False, "review_required", "surface_only_without_any_local_rcsd_data"
        if (
            connected_rc_group_count == 0
            and associated_rc_road_count == 0
            and polygon_support_rc_road_count == 0
        ):
            return False, "review_required", "surface_only_without_connected_local_rcsd_evidence"
        return False, "review_required", f"review_required_status:{status}"
    if status == STATUS_NO_VALID_RC_CONNECTION:
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and connected_rc_group_count == 1
            and nonmain_branch_connected_rc_group_count == 0
            and local_rc_road_count <= 4
            and local_rc_node_count <= 2
            and local_road_count <= 4
            and local_node_count <= 1
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
        ):
            return False, "review_required", "rc_gap_with_compact_local_mouth_geometry"
        if (
            connected_rc_group_count == 0
            and associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and effective_local_rc_node_count == 0
        ):
            return False, "review_required", "rc_gap_without_connected_local_rcsd_evidence"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and nonmain_branch_connected_rc_group_count == 0
            and effective_local_rc_node_count == 0
        ):
            return False, "review_required", "rc_gap_without_connected_local_rcsd_evidence"
        if (
            associated_rc_road_count == 0
            and polygon_support_rc_road_count == 0
            and positive_rc_group_count == 0
            and not has_structural_side_branch
            and effective_local_rc_node_count <= 1
            and local_road_count <= 10
            and local_node_count <= 4
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
        ):
            return False, "review_required", "rc_gap_with_compact_mainline_geometry"
        if (
            associated_rc_road_count == 0
            and polygon_support_rc_road_count == 0
            and positive_rc_group_count == 0
            and road_branch_count is not None
            and road_branch_count <= 3
            and not has_structural_side_branch
            and local_road_count <= 20
            and local_node_count <= 12
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m <= 8.0
            and max_nonmain_edge_branch_road_support_m <= 6.5
            and max_nonmain_edge_branch_rc_support_m <= 5.0
        ):
            return False, "review_required", "rc_gap_with_only_weak_unselected_edge_rc_groups"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and positive_rc_group_count == 1
            and connected_rc_group_count == 1
            and road_branch_count is not None
            and road_branch_count <= 2
            and not has_structural_side_branch
            and local_road_count <= 13
            and local_node_count <= 6
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
        ):
            return False, "review_required", "rc_gap_without_structural_side_branch"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and positive_rc_group_count == 1
            and connected_rc_group_count == 1
            and road_branch_count is not None
            and road_branch_count <= 3
            and not has_structural_side_branch
            and effective_local_rc_node_count <= 1
            and local_road_count <= 10
            and local_node_count <= 4
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
            and max_nonmain_edge_branch_road_support_m <= 40.0
            and max_nonmain_edge_branch_rc_support_m <= 85.0
        ):
            return False, "review_required", "rc_gap_with_compact_edge_rc_tail"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and positive_rc_group_count == 1
            and connected_rc_group_count == 1
            and road_branch_count is not None
            and road_branch_count <= 3
            and not has_structural_side_branch
            and effective_local_rc_node_count <= 1
            and local_road_count <= 12
            and local_node_count <= 5
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
            and max_nonmain_edge_branch_road_support_m <= 20.0
            and max_nonmain_edge_branch_rc_support_m <= 60.0
        ):
            return False, "review_required", "rc_gap_with_single_weak_edge_side_branch"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count == 0
            and positive_rc_group_count == 1
            and connected_rc_group_count == 1
            and road_branch_count is not None
            and road_branch_count <= 3
            and not has_structural_side_branch
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
            and max_nonmain_edge_branch_road_support_m >= 50.0
            and max_nonmain_edge_branch_road_support_m <= 90.0
            and max_nonmain_edge_branch_rc_support_m <= 5.0
        ):
            return False, "review_required", "rc_gap_with_long_weak_unselected_edge_branch"
        if max_nonmain_branch_polygon_length_m >= 4.0:
            return False, "review_required", "rc_gap_with_nonmain_branch_polygon_coverage"
        return False, "review_required", "rc_gap_without_substantive_nonmain_branch_coverage"
    if status == STATUS_NODE_COMPONENT_CONFLICT:
        return False, "review_required", f"review_required_status:{status}"
    if status == STATUS_WEAK_BRANCH_SUPPORT:
        if (
            covered_extra_local_node_count == 0
            and covered_extra_local_road_count == 0
            and associated_rc_road_count >= 1
            and polygon_support_rc_road_count >= 1
            and effective_local_rc_node_count <= 0
            and local_road_count <= 3
            and local_node_count <= 1
            and max_selected_side_branch_covered_length_m >= 12.0
            and max_nonmain_branch_polygon_length_m >= 10.0
        ):
            return False, "review_required", "weak_branch_supported_compact_t_shape"
        if (
            covered_extra_local_node_count == 0
            and covered_extra_local_road_count == 0
            and associated_rc_road_count >= 2
            and polygon_support_rc_road_count >= 2
            and effective_associated_rc_node_count >= 2
            and road_branch_count is not None
            and road_branch_count <= 3
            and max_selected_side_branch_covered_length_m >= 15.0
            and max_nonmain_branch_polygon_length_m >= 8.0
        ):
            return False, "review_required", "weak_branch_supported_rc_handoff_core"
        if (
            covered_extra_local_node_count == 0
            and covered_extra_local_road_count == 0
            and associated_rc_road_count >= 2
            and polygon_support_rc_road_count >= 2
            and effective_local_rc_node_count == 0
            and effective_associated_rc_node_count == 0
            and associated_nonzero_mainnode_count == 0
            and local_road_count <= 5
            and local_node_count <= 2
            and max_selected_side_branch_covered_length_m == 0.0
            and max_nonmain_branch_polygon_length_m == 0.0
        ):
            return False, "review_required", "weak_branch_supported_compact_outside_rc_core"
        if (
            covered_extra_local_node_count == 0
            and covered_extra_local_road_count == 0
            and associated_rc_road_count >= 2
            and polygon_support_rc_road_count >= 2
            and effective_local_rc_node_count >= 2
            and effective_associated_rc_node_count >= 2
            and associated_nonzero_mainnode_count >= 2
            and local_road_count <= 16
            and local_node_count <= 12
            and max_selected_side_branch_covered_length_m <= 4.0
            and max_nonmain_branch_polygon_length_m >= 8.0
            and max_nonmain_branch_polygon_length_m <= 10.0
        ):
            return False, "review_required", "weak_branch_supported_compact_near_center_outside_rc"
        return False, "review_required", f"review_required_status:{status}"
    if status == STATUS_AMBIGUOUS_RC_MATCH:
        if (
            associated_rc_road_count == 0
            and polygon_support_rc_road_count == 0
            and nonmain_branch_connected_rc_group_count == 0
            and max_selected_side_branch_covered_length_m >= 7.0
            and max_nonmain_branch_polygon_length_m >= 8.0
        ):
            return False, "review_required", "ambiguous_main_rc_gap_with_nonmain_branch_polygon_coverage"
        if (
            associated_rc_road_count <= 2
            and polygon_support_rc_road_count <= 1
            and connected_rc_group_count >= 2
            and nonmain_branch_connected_rc_group_count <= 1
            and negative_rc_group_count >= 1
            and road_branch_count is not None
            and road_branch_count <= 3
            and max_selected_side_branch_covered_length_m >= 7.0
            and max_nonmain_branch_polygon_length_m >= 8.0
        ):
            return False, "review_required", "ambiguous_main_rc_gap_with_compact_polygon"
        if (
            covered_extra_local_node_count == 0
            and covered_extra_local_road_count == 0
            and associated_rc_road_count <= 2
            and polygon_support_rc_road_count <= 2
            and positive_rc_group_count >= 1
            and negative_rc_group_count >= 1
            and effective_associated_rc_node_count == 0
            and representative_kind_2 in {4, 2048}
            and road_branch_count is not None
            and road_branch_count <= 3
            and local_road_count <= 24
            and local_node_count <= 12
            and max_selected_side_branch_covered_length_m >= 7.0
            and max_nonmain_branch_polygon_length_m >= 8.0
        ):
            return False, "review_required", "ambiguous_main_rc_gap_with_compact_polygon"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count <= 1
            and connected_rc_group_count >= 2
            and nonmain_branch_connected_rc_group_count <= 1
            and negative_rc_group_count >= 1
            and max_nonmain_branch_polygon_length_m >= 8.0
            and max_selected_side_branch_covered_length_m <= 2.0
        ):
            return False, "review_required", "ambiguous_main_rc_gap_with_compact_polygon"
        if (
            associated_rc_road_count <= 1
            and polygon_support_rc_road_count <= 1
            and positive_rc_group_count == 1
            and negative_rc_group_count >= 1
            and not has_structural_side_branch
            and local_road_count <= 7
            and local_node_count <= 3
            and max_nonmain_branch_polygon_length_m >= 4.0
            and max_selected_side_branch_covered_length_m <= 1.0
        ):
            return False, "review_required", "ambiguous_main_rc_gap_with_compact_supported_polygon"
        if (
            associated_rc_road_count == 2
            and polygon_support_rc_road_count >= associated_rc_road_count
            and positive_rc_group_count <= 2
            and negative_rc_group_count >= 1
            and local_road_count <= 6
            and local_node_count <= 4
            and max_selected_side_branch_covered_length_m >= 18.0
            and max_nonmain_branch_polygon_length_m >= 10.0
        ):
            return False, "review_required", "ambiguous_main_rc_gap_with_supported_branch_polygon_coverage"
        return False, "review_required", f"review_required_status:{status}"
    return False, "rejected", f"rejected_status:{status}"

def evaluate_stage3_acceptance_from_inputs(
    inputs: Stage3AcceptanceHeuristicInputs,
) -> Stage3AcceptanceDecision:
    step4_result = inputs.step4_result
    final_selected_node_cover_repair_discarded_due_to_extra_roads = (
        step4_result.selected_node_cover_repair_discarded_due_to_extra_roads
        if step4_result is not None
        else inputs.final_selected_node_cover_repair_discarded_due_to_extra_roads
    )
    multi_node_selected_cover_repair_applied = (
        step4_result.multi_node_selected_cover_repair_applied
        if step4_result is not None
        else inputs.multi_node_selected_cover_repair_applied
    )
    final_uncovered_selected_endpoint_node_count = (
        len(step4_result.uncovered_selected_endpoint_node_ids)
        if step4_result is not None
        else inputs.final_uncovered_selected_endpoint_node_count
    )
    effect_success, acceptance_class, acceptance_reason = effect_success_acceptance(
        status=inputs.status,
        review_mode=inputs.review_mode,
        template_class=inputs.template_class,
        max_selected_side_branch_covered_length_m=inputs.max_selected_side_branch_covered_length_m,
        max_nonmain_branch_polygon_length_m=inputs.max_nonmain_branch_polygon_length_m,
        associated_rc_road_count=inputs.associated_rc_road_count,
        polygon_support_rc_node_count=inputs.polygon_support_rc_node_count,
        polygon_support_rc_road_count=inputs.polygon_support_rc_road_count,
        min_invalid_rc_distance_to_center_m=inputs.min_invalid_rc_distance_to_center_m,
        local_rc_road_count=inputs.local_rc_road_count,
        local_rc_node_count=inputs.local_rc_node_count,
        effective_local_rc_node_count=inputs.effective_local_rc_node_count,
        local_road_count=inputs.local_road_count,
        local_node_count=inputs.local_node_count,
        connected_rc_group_count=inputs.connected_rc_group_count,
        nonmain_branch_connected_rc_group_count=inputs.nonmain_branch_connected_rc_group_count,
        negative_rc_group_count=inputs.negative_rc_group_count,
        positive_rc_group_count=inputs.positive_rc_group_count,
        road_branch_count=inputs.road_branch_count,
        has_structural_side_branch=inputs.has_structural_side_branch,
        max_nonmain_edge_branch_road_support_m=inputs.max_nonmain_edge_branch_road_support_m,
        max_nonmain_edge_branch_rc_support_m=inputs.max_nonmain_edge_branch_rc_support_m,
        excluded_local_rc_road_count=inputs.excluded_local_rc_road_count,
        excluded_local_rc_node_count=inputs.excluded_local_rc_node_count,
        covered_extra_local_node_count=inputs.covered_extra_local_node_count,
        covered_extra_local_road_count=inputs.covered_extra_local_road_count,
        has_main_edge_only_branch=inputs.has_main_edge_only_branch,
        representative_kind_2=inputs.representative_kind_2,
        effective_associated_rc_node_count=inputs.effective_associated_rc_node_count,
        associated_nonzero_mainnode_count=inputs.associated_nonzero_mainnode_count,
        final_selected_node_cover_repair_discarded_due_to_extra_roads=final_selected_node_cover_repair_discarded_due_to_extra_roads,
        single_sided_t_mouth_corridor_pattern_detected=inputs.single_sided_t_mouth_corridor_pattern_detected,
        single_sided_t_mouth_corridor_semantic_gap=inputs.single_sided_t_mouth_corridor_semantic_gap,
        multi_node_selected_cover_repair_applied=multi_node_selected_cover_repair_applied,
        final_uncovered_selected_endpoint_node_count=final_uncovered_selected_endpoint_node_count,
        single_sided_unrelated_opposite_lane_trim_applied=inputs.single_sided_unrelated_opposite_lane_trim_applied,
    )
    return Stage3AcceptanceDecision(
        effect_success=effect_success,
        acceptance_class=acceptance_class,
        acceptance_reason=acceptance_reason,
    )

def apply_stage3_post_acceptance_gates(
    *,
    effect_success: bool,
    acceptance_class: str,
    acceptance_reason: str,
    status: str,
    template_class: str,
    can_soft_exclude_outside_rc: bool,
    rc_outside_drivezone_error: Any | None,
    max_target_group_foreign_semantic_road_overlap_m: float,
    max_selected_side_branch_covered_length_m: float,
    max_nonmain_branch_polygon_length_m: float,
    min_invalid_rc_distance_to_center_m: float | None,
    associated_rc_road_count: int,
    associated_rc_node_count: int,
    effective_associated_rc_node_count: int,
    excluded_rc_road_count: int,
    positive_rc_group_count: int,
    negative_rc_group_count: int,
    local_node_count: int,
    local_road_count: int,
    polygon_aspect_ratio: float | None,
    polygon_compactness: float | None,
    polygon_bbox_fill_ratio: float | None,
    single_sided_unrelated_opposite_lane_trim_applied: bool,
    soft_excluded_rc_corridor_trim_applied: bool,
    post_trim_non_target_tail_length_m: float,
    foreign_overlap_zero_but_tail_present: bool,
    audit_rows: Sequence[dict[str, Any]],
) -> tuple[bool, str, str]:
    step5_small_residual_provenance_only = (
        _is_step5_small_residual_provenance_only_signature(
            max_target_group_foreign_semantic_road_overlap_m=(
                max_target_group_foreign_semantic_road_overlap_m
            ),
            single_sided_unrelated_opposite_lane_trim_applied=(
                single_sided_unrelated_opposite_lane_trim_applied
            ),
            post_trim_non_target_tail_length_m=post_trim_non_target_tail_length_m,
            foreign_overlap_zero_but_tail_present=(
                foreign_overlap_zero_but_tail_present
            ),
        )
    )
    if effect_success and acceptance_class == "accepted" and status == STATUS_STABLE:
        if (
            max_target_group_foreign_semantic_road_overlap_m >= 11.0
            and (
                (
                    polygon_aspect_ratio is not None
                    and polygon_aspect_ratio >= 4.5
                )
                or (
                    polygon_compactness is not None
                    and polygon_compactness <= 0.10
                    and polygon_bbox_fill_ratio is not None
                    and polygon_bbox_fill_ratio <= 0.20
                )
                or (
                    max_selected_side_branch_covered_length_m <= 0.5
                    and associated_rc_road_count <= 1
                    and effective_associated_rc_node_count <= 1
                )
            )
        ):
            return False, "review_required", "foreign_outside_drivezone_soft_excluded"

    if rc_outside_drivezone_error is not None and can_soft_exclude_outside_rc:
        if (
            template_class == TEMPLATE_SINGLE_SIDED_T_MOUTH
            and single_sided_unrelated_opposite_lane_trim_applied
            and foreign_overlap_zero_but_tail_present
            and post_trim_non_target_tail_length_m >= 1.5
        ):
            return False, "review_required", "foreign_tail_after_opposite_lane_trim"
        if _should_release_center_soft_excluded_small_residual_to_accepted(
            effect_success=effect_success,
            acceptance_class=acceptance_class,
            acceptance_reason=acceptance_reason,
            template_class=template_class,
            step5_small_residual_provenance_only=(
                step5_small_residual_provenance_only
            ),
            soft_excluded_rc_corridor_trim_applied=(
                soft_excluded_rc_corridor_trim_applied
            ),
            associated_rc_road_count=associated_rc_road_count,
            excluded_rc_road_count=excluded_rc_road_count,
            negative_rc_group_count=negative_rc_group_count,
            local_road_count=local_road_count,
            max_selected_side_branch_covered_length_m=(
                max_selected_side_branch_covered_length_m
            ),
            max_nonmain_branch_polygon_length_m=(
                max_nonmain_branch_polygon_length_m
            ),
        ):
            return effect_success, acceptance_class, acceptance_reason
        if (
            step5_small_residual_provenance_only
            and soft_excluded_rc_corridor_trim_applied
            and template_class == TEMPLATE_CENTER_JUNCTION
        ):
            return False, "review_required", "outside_rc_gap_requires_review"
        if (
            step5_small_residual_provenance_only
            and not soft_excluded_rc_corridor_trim_applied
            and effect_success
            and acceptance_class == "accepted"
            and acceptance_reason == "stable"
            and associated_rc_road_count >= 2
            and max_selected_side_branch_covered_length_m <= 0.5
        ):
            return effect_success, acceptance_class, acceptance_reason
        if soft_excluded_rc_corridor_trim_applied:
            if (
                local_road_count <= 6
                and min_invalid_rc_distance_to_center_m is not None
                and min_invalid_rc_distance_to_center_m >= 4.0
                and max_target_group_foreign_semantic_road_overlap_m >= 2.0
            ):
                return False, "review_required", "foreign_outside_drivezone_soft_excluded"
        strong_foreign_evidence = False
        if positive_rc_group_count >= 2 and negative_rc_group_count == 0:
            strong_foreign_evidence = True
        if (
            max_selected_side_branch_covered_length_m <= 2.5
            and (
                (polygon_aspect_ratio is not None and polygon_aspect_ratio >= 3.0)
                or associated_rc_road_count >= 2
                or max_target_group_foreign_semantic_road_overlap_m <= 1.0
            )
        ):
            strong_foreign_evidence = True
        if (
            max_nonmain_branch_polygon_length_m <= 0.5
            and max_target_group_foreign_semantic_road_overlap_m >= 8.5
        ):
            strong_foreign_evidence = True
        if (
            effective_associated_rc_node_count >= 3
            and max_target_group_foreign_semantic_road_overlap_m >= 10.0
        ):
            strong_foreign_evidence = True
        if (
            polygon_aspect_ratio is not None
            and polygon_aspect_ratio >= 4.0
            and associated_rc_road_count >= 2
        ):
            strong_foreign_evidence = True
        if (
            template_class == TEMPLATE_SINGLE_SIDED_T_MOUTH
            and polygon_compactness is not None
            and polygon_compactness <= 0.29
            and excluded_rc_road_count >= 2
            and effective_associated_rc_node_count <= 1
            and max_selected_side_branch_covered_length_m >= 7.5
            and max_nonmain_branch_polygon_length_m >= 10.0
        ):
            strong_foreign_evidence = True
        if (
            template_class == TEMPLATE_CENTER_JUNCTION
            and polygon_compactness is not None
            and polygon_bbox_fill_ratio is not None
            and polygon_compactness <= 0.36
            and polygon_bbox_fill_ratio <= 0.45
            and max_target_group_foreign_semantic_road_overlap_m >= 8.5
            and effective_associated_rc_node_count <= 1
            and max_selected_side_branch_covered_length_m <= 8.0
        ):
            strong_foreign_evidence = True
        if strong_foreign_evidence:
            return False, "review_required", "foreign_outside_drivezone_soft_excluded"

    for row in audit_rows:
        reason = str(row.get("reason") or "")
        detail = str(row.get("detail") or "").lower()
        if reason == STATUS_NODE_COMPONENT_CONFLICT and "foreign semantic roads" in detail:
            if status in {
                STATUS_AMBIGUOUS_RC_MATCH,
                STATUS_NO_VALID_RC_CONNECTION,
                STATUS_WEAK_BRANCH_SUPPORT,
            }:
                return False, "review_required", "soft_overlap_requires_review"
            return False, "review_required", "foreign_semantic_road_overlap"
        if "opposite lane" in detail or "foreign" in detail:
            return False, "review_required", "foreign_corridor_intrusion"

    return effect_success, acceptance_class, acceptance_reason

def apply_stage3_post_acceptance_gates_from_inputs(
    inputs: Stage3PostAcceptanceGateInputs,
) -> Stage3AcceptanceDecision:
    effect_success, acceptance_class, acceptance_reason = apply_stage3_post_acceptance_gates(
        effect_success=inputs.effect_success,
        acceptance_class=inputs.acceptance_class,
        acceptance_reason=inputs.acceptance_reason,
        status=inputs.status,
        template_class=inputs.template_class,
        can_soft_exclude_outside_rc=inputs.can_soft_exclude_outside_rc,
        rc_outside_drivezone_error=inputs.rc_outside_drivezone_error,
        max_target_group_foreign_semantic_road_overlap_m=inputs.max_target_group_foreign_semantic_road_overlap_m,
        max_selected_side_branch_covered_length_m=inputs.max_selected_side_branch_covered_length_m,
        max_nonmain_branch_polygon_length_m=inputs.max_nonmain_branch_polygon_length_m,
        min_invalid_rc_distance_to_center_m=inputs.min_invalid_rc_distance_to_center_m,
        associated_rc_road_count=inputs.associated_rc_road_count,
        associated_rc_node_count=inputs.associated_rc_node_count,
        effective_associated_rc_node_count=inputs.effective_associated_rc_node_count,
        excluded_rc_road_count=inputs.excluded_rc_road_count,
        positive_rc_group_count=inputs.positive_rc_group_count,
        negative_rc_group_count=inputs.negative_rc_group_count,
        local_node_count=inputs.local_node_count,
        local_road_count=inputs.local_road_count,
        polygon_aspect_ratio=inputs.polygon_aspect_ratio,
        polygon_compactness=inputs.polygon_compactness,
        polygon_bbox_fill_ratio=inputs.polygon_bbox_fill_ratio,
        single_sided_unrelated_opposite_lane_trim_applied=inputs.single_sided_unrelated_opposite_lane_trim_applied,
        soft_excluded_rc_corridor_trim_applied=inputs.soft_excluded_rc_corridor_trim_applied,
        post_trim_non_target_tail_length_m=inputs.post_trim_non_target_tail_length_m,
        foreign_overlap_zero_but_tail_present=inputs.foreign_overlap_zero_but_tail_present,
        audit_rows=inputs.audit_rows,
    )
    return Stage3AcceptanceDecision(
        effect_success=effect_success,
        acceptance_class=acceptance_class,
        acceptance_reason=acceptance_reason,
    )

def _step4_reason_from_result(
    step4_result: Stage3Step4RCSemanticsResult | None,
) -> str | None:
    if step4_result is None:
        return None
    if step4_result.review_excluded_rc_node_ids or step4_result.review_excluded_rc_road_ids:
        return "outside_rc_gap_requires_review"
    if step4_result.selected_node_cover_repair_discarded_due_to_extra_roads:
        return "stable_with_incomplete_t_mouth_rc_context"
    if (
        step4_result.uncovered_selected_endpoint_node_ids
        and any(
            "single_sided_t_mouth_corridor_semantic_gap" in signal
            for signal in step4_result.stage3_rc_gap_records
        )
    ):
        return "stable_with_incomplete_t_mouth_rc_context"
    if any(
        "review_rc_outside_drivezone_excluded" in signal
        for signal in step4_result.stage3_rc_gap_records
    ):
        return "outside_rc_gap_requires_review"
    return None


def _step3_reason_from_result(
    step3_result: Stage3Step3LegalSpaceResult | None,
) -> str | None:
    if step3_result is None or not step3_result.step3_blockers:
        return None
    return step3_result.step3_blockers[0]


def _derive_cluster_step6_review_fields(
    *,
    reason: str,
) -> Stage3ReviewFields:
    return Stage3ReviewFields(
        root_cause_layer=ROOT_CAUSE_LAYER_STEP6,
        root_cause_type=reason,
        visual_review_class="V2 业务正确但几何待修",
        business_outcome_class=BUSINESS_OUTCOME_RISK,
    )


@dataclass(frozen=True)
class Stage3LegacyStep7Assembly:
    context: Stage3Context
    step7_result: Stage3Step7AcceptanceResult
    step3_result: Stage3Step3LegalSpaceResult | None
    step4_result: Stage3Step4RCSemanticsResult | None
    step5_result: Stage3Step5ForeignModelResult | None
    step6_result: Stage3Step6GeometrySolveResult | None
    step3_signals: tuple[str, ...]
    step4_signals: tuple[str, ...]
    step5_signals: tuple[str, ...]
    step5_foreign_subtype: str | None
    step5_foreign_overlap_metric_m: float | None
    step5_foreign_tail_length_m: float | None
    step5_foreign_strip_extent_m: float | None
    step5_foreign_overlap_zero_but_tail_present: bool | None
    step6_optimizer_events: tuple[str, ...]
    step6_geometry_problem_flags: tuple[str, ...]


def build_stage3_failure_step7_result(
    *,
    mainnodeid: str,
    template_class: str,
    acceptance_reason: str,
    status: str | None = None,
    root_cause_layer: str | None = None,
    root_cause_type: str | None = None,
    visual_review_class: str | None = None,
    blocking_step: str | None = None,
    legacy_review_metadata_source: str = "failure_step7_result_builder_v3",
) -> Stage3Step7AcceptanceResult:
    resolved_status = status or acceptance_reason
    resolved_root_cause_layer = root_cause_layer or "frozen-constraints conflict"
    resolved_root_cause_type = root_cause_type or acceptance_reason or resolved_status
    resolved_visual_review_class = visual_review_class or VISUAL_REVIEW_V5
    return Stage3Step7AcceptanceResult(
        mainnodeid=mainnodeid,
        template_class=template_class,
        status=resolved_status,
        success=False,
        business_outcome_class=BUSINESS_OUTCOME_FAILURE,
        acceptance_class="rejected",
        acceptance_reason=acceptance_reason,
        root_cause_layer=resolved_root_cause_layer,
        root_cause_type=resolved_root_cause_type,
        visual_review_class=resolved_visual_review_class,
        step3_legal_space_established=False,
        step4_required_rc_established=False,
        step5_foreign_exclusion_established=False,
        step6_geometry_established=False,
        decision_basis=(
            "failure_step7_result_builder_v3",
            f"acceptance_reason={acceptance_reason}",
            f"status={resolved_status}",
            f"root_cause_layer={resolved_root_cause_layer}",
        ),
        blocking_step=blocking_step or resolved_root_cause_layer,
        legacy_review_metadata_source=legacy_review_metadata_source,
        audit_facts=(
            f"acceptance_reason={acceptance_reason}",
            f"status={resolved_status}",
            f"root_cause_layer={resolved_root_cause_layer}",
        ),
    )


def _normalize_step6_optimizer_events(
    *,
    step6_result: Stage3Step6GeometrySolveResult | None,
    inputs: Stage3LegacyStep7Inputs,
) -> list[str]:
    if step6_result is not None:
        return list(step6_result.optimizer_events)
    if inputs.step6_optimizer_events:
        return [
            str(event)
            for event in inputs.step6_optimizer_events
            if event is not None and str(event).strip()
        ]
    return []


def _build_stage3_legacy_step7_inputs_from_results(
    *,
    context: Stage3Context,
    step3_result: Stage3Step3LegalSpaceResult | None,
    step4_result: Stage3Step4RCSemanticsResult | None,
    step5_result: Stage3Step5ForeignModelResult | None,
    step6_result: Stage3Step6GeometrySolveResult | None,
    decision_inputs: Stage3Step7DecisionInputs,
    acceptance_class: str,
    acceptance_reason: str,
) -> Stage3LegacyStep7Inputs:
    return Stage3LegacyStep7Inputs(
        context=context,
        step3_result=step3_result,
        step4_result=step4_result,
        step5_result=step5_result,
        step6_result=step6_result,
        success=decision_inputs.success,
        acceptance_class=acceptance_class,
        acceptance_reason=acceptance_reason,
        status=decision_inputs.status,
        representative_has_evd=decision_inputs.representative_has_evd,
        representative_is_anchor=decision_inputs.representative_is_anchor,
        representative_kind_2=decision_inputs.representative_kind_2,
        business_match_reason=decision_inputs.business_match_reason,
        single_sided_t_mouth_corridor_semantic_gap=(
            decision_inputs.single_sided_t_mouth_corridor_semantic_gap
        ),
        final_uncovered_selected_endpoint_node_count=(
            decision_inputs.final_uncovered_selected_endpoint_node_count
        ),
        single_sided_unrelated_opposite_lane_trim_applied=(
            step5_result.single_sided_unrelated_opposite_lane_trim_applied
            if step5_result is not None
            else False
        ),
        soft_excluded_rc_corridor_trim_applied=(
            step5_result.soft_excluded_rc_corridor_trim_applied
            if step5_result is not None
            else False
        ),
        post_trim_non_target_tail_length_m=(
            float(step6_result.foreign_tail_length_m or 0.0)
            if step6_result is not None
            else float(step5_result.foreign_tail_length_m or 0.0)
            if step5_result is not None
            else 0.0
        ),
        foreign_overlap_zero_but_tail_present=(
            bool(step6_result.foreign_overlap_zero_but_tail_present)
            if step6_result is not None
            else bool(step5_result.foreign_overlap_zero_but_tail_present)
            if step5_result is not None
            else False
        ),
        step6_optimizer_events=(
            step6_result.optimizer_events if step6_result is not None else ()
        ),
        selected_rc_node_count=decision_inputs.selected_rc_node_count,
        selected_rc_road_count=decision_inputs.selected_rc_road_count,
        polygon_support_rc_node_count=decision_inputs.polygon_support_rc_node_count,
        polygon_support_rc_road_count=decision_inputs.polygon_support_rc_road_count,
        invalid_rc_node_count=decision_inputs.invalid_rc_node_count,
        invalid_rc_road_count=decision_inputs.invalid_rc_road_count,
        drivezone_is_empty=decision_inputs.drivezone_is_empty,
        polygon_is_empty=decision_inputs.polygon_is_empty,
        max_target_group_foreign_semantic_road_overlap_m=(
            float(step6_result.foreign_overlap_metric_m or 0.0)
            if step6_result is not None
            else float(step5_result.foreign_overlap_metric_m or 0.0)
            if step5_result is not None
            else 0.0
        ),
        max_selected_side_branch_covered_length_m=(
            float(step6_result.max_selected_side_branch_covered_length_m or 0.0)
            if step6_result is not None
            else 0.0
        ),
        max_nonmain_branch_polygon_length_m=(
            float(step5_result.foreign_strip_extent_m or 0.0)
            if step5_result is not None
            else 0.0
        ),
        polygon_aspect_ratio=(
            step6_result.polygon_aspect_ratio if step6_result is not None else None
        ),
        polygon_compactness=(
            step6_result.polygon_compactness if step6_result is not None else None
        ),
        polygon_bbox_fill_ratio=(
            step6_result.polygon_bbox_fill_ratio if step6_result is not None else None
        ),
    )


def build_stage3_step7_assembly_from_results(
    *,
    context: Stage3Context,
    step3_result: Stage3Step3LegalSpaceResult | None,
    step4_result: Stage3Step4RCSemanticsResult | None,
    step5_result: Stage3Step5ForeignModelResult | None,
    step6_result: Stage3Step6GeometrySolveResult | None,
    decision_inputs: Stage3Step7DecisionInputs,
) -> Stage3LegacyStep7Assembly:
    assembly = build_stage3_legacy_step7_assembly(
        _build_stage3_legacy_step7_inputs_from_results(
            context=context,
            step3_result=step3_result,
            step4_result=step4_result,
            step5_result=step5_result,
            step6_result=step6_result,
            decision_inputs=decision_inputs,
            acceptance_class=decision_inputs.acceptance_class,
            acceptance_reason=decision_inputs.acceptance_reason,
        )
    )
    if assembly.step7_result.legacy_review_metadata_source == "step7_results_verdict_v2":
        return assembly
    return replace(
        assembly,
        step7_result=replace(
            assembly.step7_result,
            legacy_review_metadata_source="step7_results_verdict_v2",
        ),
    )


def build_stage3_legacy_step7_assembly_from_results(
    *,
    context: Stage3Context,
    step3_result: Stage3Step3LegalSpaceResult | None,
    step4_result: Stage3Step4RCSemanticsResult | None,
    step5_result: Stage3Step5ForeignModelResult | None,
    step6_result: Stage3Step6GeometrySolveResult | None,
    decision_inputs: Stage3LegacyStep7DecisionInputs,
) -> Stage3LegacyStep7Assembly:
    return build_stage3_step7_assembly_from_results(
        context=context,
        step3_result=step3_result,
        step4_result=step4_result,
        step5_result=step5_result,
        step6_result=step6_result,
        decision_inputs=Stage3Step7DecisionInputs(
            success=decision_inputs.success,
            acceptance_class=decision_inputs.acceptance_class,
            acceptance_reason=decision_inputs.acceptance_reason,
            status=decision_inputs.status,
            representative_has_evd=decision_inputs.representative_has_evd,
            representative_is_anchor=decision_inputs.representative_is_anchor,
            representative_kind_2=decision_inputs.representative_kind_2,
            business_match_reason=decision_inputs.business_match_reason,
            single_sided_t_mouth_corridor_semantic_gap=(
                decision_inputs.single_sided_t_mouth_corridor_semantic_gap
            ),
            final_uncovered_selected_endpoint_node_count=(
                decision_inputs.final_uncovered_selected_endpoint_node_count
            ),
            selected_rc_node_count=decision_inputs.selected_rc_node_count,
            selected_rc_road_count=decision_inputs.selected_rc_road_count,
            polygon_support_rc_node_count=decision_inputs.polygon_support_rc_node_count,
            polygon_support_rc_road_count=decision_inputs.polygon_support_rc_road_count,
            invalid_rc_node_count=decision_inputs.invalid_rc_node_count,
            invalid_rc_road_count=decision_inputs.invalid_rc_road_count,
            drivezone_is_empty=decision_inputs.drivezone_is_empty,
            polygon_is_empty=decision_inputs.polygon_is_empty,
        ),
    )


def _resolve_stage3_step7_review_fields(
    *,
    inputs: Stage3LegacyStep7Inputs,
    step3_result: Stage3Step3LegalSpaceResult | None,
    step4_result: Stage3Step4RCSemanticsResult | None,
    step5_result: Stage3Step5ForeignModelResult | None,
    step6_result: Stage3Step6GeometrySolveResult | None,
) -> tuple[
    str,
    str,
    Stage3ReviewFields,
    list[str],
    list[str],
    list[str],
    list[str],
    list[str],
    Stage3Step5ContractDecision,
]:
    local_node_count = len(inputs.context.local_node_ids)
    local_road_count = len(inputs.context.local_road_ids)
    if step3_result is not None:
        step3_contract_signals = [signal for signal in step3_result.step3_blockers if signal]
        if step3_result.must_cover_group_node_ids:
            step3_contract_signals.append(
                f"must_cover_group_node_count={len(step3_result.must_cover_group_node_ids)}"
            )
        if step3_result.single_sided_corridor_road_ids:
            step3_contract_signals.append(
                "single_sided_corridor_road_count="
                f"{len(step3_result.single_sided_corridor_road_ids)}"
            )
        if step3_result.hard_boundary_road_ids:
            step3_contract_signals.append(
                f"hard_boundary_road_count={len(step3_result.hard_boundary_road_ids)}"
            )
    else:
        step3_contract_signals = []
        if inputs.drivezone_is_empty:
            step3_contract_signals.append("drivezone_empty")

    if step4_result is not None:
        step4_contract_signals = list(step4_result.audit_facts)
    else:
        step4_contract_signals = []
        if inputs.business_match_reason:
            step4_contract_signals.append(
                f"business_match_reason={inputs.business_match_reason}"
            )
        if inputs.single_sided_t_mouth_corridor_semantic_gap:
            step4_contract_signals.append("single_sided_t_mouth_corridor_semantic_gap")
        if inputs.final_uncovered_selected_endpoint_node_count > 0:
            step4_contract_signals.append(
                "final_uncovered_selected_endpoint_node_count="
                f"{inputs.final_uncovered_selected_endpoint_node_count}"
            )

    if step5_result is not None:
        step5_contract_signals = list(step5_result.audit_facts)
        if step5_result.foreign_baseline_established:
            step5_contract_signals.append("step5_baseline_established")
        if step5_result.foreign_subtype is not None:
            step5_contract_signals.append(
                f"step5_baseline_subtype={step5_result.foreign_subtype}"
            )
    else:
        step5_contract_signals = []
        if inputs.acceptance_reason:
            step5_contract_signals.append(str(inputs.acceptance_reason))
        if inputs.single_sided_unrelated_opposite_lane_trim_applied:
            step5_contract_signals.append(
                "single_sided_unrelated_opposite_lane_trim_applied"
            )
        if inputs.soft_excluded_rc_corridor_trim_applied:
            step5_contract_signals.append("soft_excluded_rc_corridor_trim_applied")
        if inputs.post_trim_non_target_tail_length_m > 0.0:
            step5_contract_signals.append(
                f"post_trim_non_target_tail_length_m={inputs.post_trim_non_target_tail_length_m:.3f}"
            )
        if inputs.foreign_overlap_zero_but_tail_present:
            step5_contract_signals.append("foreign_overlap_zero_but_tail_present")

    if step6_result is not None:
        step6_optimizer_events = list(step6_result.optimizer_events)
        step6_geometry_problem_flags = list(step6_result.geometry_problem_flags)
    else:
        step6_optimizer_events = _normalize_step6_optimizer_events(
            step6_result=step6_result,
            inputs=inputs,
        )
        step6_geometry_problem_flags = []
        if inputs.polygon_aspect_ratio is not None:
            step6_geometry_problem_flags.append(
                f"polygon_aspect_ratio={inputs.polygon_aspect_ratio:.3f}"
            )
        if inputs.polygon_compactness is not None:
            step6_geometry_problem_flags.append(
                f"polygon_compactness={inputs.polygon_compactness:.3f}"
            )
        if inputs.polygon_bbox_fill_ratio is not None:
            step6_geometry_problem_flags.append(
                f"polygon_bbox_fill_ratio={inputs.polygon_bbox_fill_ratio:.3f}"
            )

    explicit_layer: str | None = None
    explicit_reason: str | None = None
    review_fields_override: Stage3ReviewFields | None = None
    step5_contract_decision = resolve_stage3_step5_contract_decision(
        step5_result=step5_result,
        step6_result=step6_result,
    )
    step3_reason = _step3_reason_from_result(step3_result)
    if step3_reason is not None:
        explicit_layer = ROOT_CAUSE_LAYER_STEP3
        explicit_reason = step3_reason
        step3_contract_signals.append("step3_result_selected")
        step3_contract_signals.append("step3_result_override_applied")
    else:
        step5_residual_escalation_selected = (
            "step5_canonical_escalated_from_step6_residual_overlap"
            in step5_contract_decision.audit_facts
        )
        step6_residual_step5_blocking_selected = bool(
            step6_result is not None
            and step6_result.residual_step5_blocking_foreign_required
        )
        step5_selected = False
        if (
            step5_contract_decision.canonical_foreign_reason is not None
            and (
                not step5_residual_escalation_selected
                or step6_residual_step5_blocking_selected
            )
        ):
            explicit_layer = ROOT_CAUSE_LAYER_STEP5
            explicit_reason = step5_contract_decision.canonical_foreign_reason
            step5_contract_signals.append("step5_result_selected")
            step5_contract_signals.append("step5_result_override_applied")
            if step6_residual_step5_blocking_selected:
                step5_contract_signals.append(
                    "step5_result_selected_from_step6_blocking_residual"
                )
            if step5_contract_decision.residual_foreign_present:
                step5_contract_signals.append("step5_residual_foreign_present")
            step5_selected = True
        if not step5_selected:
            step6_reason = (
                step6_result.geometry_review_reason
                if step6_result is not None
                else None
            )
            step6_selected = False
            step6_cluster_name = _STEP6_CLUSTER_CANONICAL_REASONS.get(step6_reason)
            if step6_cluster_name is not None:
                explicit_layer = ROOT_CAUSE_LAYER_STEP6
                explicit_reason = step6_reason
                review_fields_override = _derive_cluster_step6_review_fields(
                    reason=step6_reason
                )
                step6_optimizer_events.append("step6_cluster_canonical_result_selected")
                step6_optimizer_events.append("step6_cluster_delegacy_override_applied")
                step6_optimizer_events.append(
                    f"step6_cluster_path={step6_cluster_name}"
                )
                step6_selected = True
            elif step6_reason:
                candidate_step6_review_fields = derive_stage3_review_fields(
                    success=False,
                    acceptance_class="review_required",
                    acceptance_reason=step6_reason,
                    status=inputs.status,
                )
                if (
                    candidate_step6_review_fields.root_cause_layer
                    == ROOT_CAUSE_LAYER_STEP6
                    and not success_flag_from_business_outcome(
                        candidate_step6_review_fields.business_outcome_class
                    )
                ):
                    explicit_layer = candidate_step6_review_fields.root_cause_layer
                    explicit_reason = step6_reason
                    step6_optimizer_events.append("step6_result_selected")
                    step6_optimizer_events.append("step6_result_override_applied")
                    step6_selected = True
            if not step6_selected:
                step4_reason = _step4_reason_from_result(step4_result)
                if step4_reason is not None:
                    explicit_layer = ROOT_CAUSE_LAYER_STEP4
                    explicit_reason = step4_reason
                    step4_contract_signals.append("step4_result_selected")
                    step4_contract_signals.append("step4_result_override_applied")

    if (
        step5_result is not None
        and step5_result.foreign_baseline_established
        and explicit_layer != ROOT_CAUSE_LAYER_STEP5
    ):
        step5_contract_signals.append("step5_baseline_retained_but_nonblocking")
    step5_contract_signals.extend(step5_contract_decision.audit_facts)

    legacy_review_acceptance_class = inputs.acceptance_class
    if explicit_layer is not None and legacy_review_acceptance_class == "accepted":
        legacy_review_acceptance_class = "review_required"
    effective_acceptance_reason = (
        explicit_reason if explicit_reason is not None else inputs.acceptance_reason
    )
    review_fields = (
        review_fields_override
        if review_fields_override is not None
        else derive_stage3_review_fields(
            success=inputs.success if explicit_layer is None else False,
            acceptance_class=legacy_review_acceptance_class,
            acceptance_reason=effective_acceptance_reason,
            status=inputs.status,
        )
    )
    if (
        review_fields_override is None
        and explicit_layer is not None
        and review_fields.root_cause_layer != explicit_layer
    ):
        review_fields = Stage3ReviewFields(
            root_cause_layer=explicit_layer,
            root_cause_type=effective_acceptance_reason or inputs.status,
            visual_review_class=review_fields.visual_review_class,
            business_outcome_class=business_outcome_from_visual_review_class(
                review_fields.visual_review_class
            ),
        )
    return (
        acceptance_class_from_business_outcome(review_fields.business_outcome_class),
        effective_acceptance_reason,
        review_fields,
        step3_contract_signals,
        step4_contract_signals,
        step5_contract_signals,
        step6_optimizer_events,
        step6_geometry_problem_flags,
        step5_contract_decision,
    )


def build_stage3_legacy_step7_assembly(
    inputs: Stage3LegacyStep7Inputs,
) -> Stage3LegacyStep7Assembly:
    step3_result = inputs.step3_result
    step4_result = inputs.step4_result
    step5_result = inputs.step5_result
    step6_result = inputs.step6_result
    (
        effective_acceptance_class,
        effective_acceptance_reason,
        review_fields,
        step3_contract_signals,
        step4_contract_signals,
        step5_contract_signals,
        step6_optimizer_events,
        step6_geometry_problem_flags,
        step5_contract_decision,
    ) = _resolve_stage3_step7_review_fields(
        inputs=inputs,
        step3_result=step3_result,
        step4_result=step4_result,
        step5_result=step5_result,
        step6_result=step6_result,
    )
    step7_audit_facts = tuple(
        sorted(
            {
                value
                for value in (
                    f"mainnodeid={inputs.context.normalized_mainnodeid}",
                    f"template_class={inputs.context.template_class}",
                    f"status={inputs.status}" if inputs.status else None,
                    (
                        f"acceptance_class={effective_acceptance_class}"
                        if effective_acceptance_class
                        else None
                    ),
                    (
                        f"acceptance_reason={effective_acceptance_reason}"
                        if effective_acceptance_reason
                        else None
                    ),
                    (
                        f"root_cause_layer={review_fields.root_cause_layer}"
                        if review_fields.root_cause_layer
                        else None
                    ),
                )
                if value
            }
        )
    )
    decision_basis = tuple(
        sorted(
            {
                value
                for value in (
                    (
                        f"root_cause_layer={review_fields.root_cause_layer}"
                        if review_fields.root_cause_layer
                        else None
                    ),
                    (
                        f"acceptance_reason={effective_acceptance_reason}"
                        if effective_acceptance_reason
                        else None
                    ),
                    *step3_contract_signals,
                    *step4_contract_signals,
                    *step5_contract_signals,
                    *step6_optimizer_events,
                    *step6_geometry_problem_flags,
                )
                if value
            }
        )
    )
    blocking_step = (
        review_fields.root_cause_layer
        if review_fields.root_cause_layer in {"step3", "step4", "step5", "step6"}
        else None
    )
    step7_result = Stage3Step7AcceptanceResult(
        mainnodeid=inputs.context.normalized_mainnodeid,
        template_class=inputs.context.template_class,
        status=str(inputs.status or ""),
        success=success_flag_from_business_outcome(
            review_fields.business_outcome_class
        ),
        business_outcome_class=review_fields.business_outcome_class,
        acceptance_class=str(effective_acceptance_class or ""),
        acceptance_reason=str(effective_acceptance_reason or inputs.status or ""),
        root_cause_layer=review_fields.root_cause_layer,
        root_cause_type=review_fields.root_cause_type,
        visual_review_class=review_fields.visual_review_class,
        step3_legal_space_established=(
            not bool(step3_result.step3_blockers)
            if step3_result is not None
            else not inputs.drivezone_is_empty
        ),
        step4_required_rc_established=(
            bool(
                step4_result.required_rc_node_ids
                or step4_result.required_rc_road_ids
                or step4_result.support_rc_node_ids
                or step4_result.support_rc_road_ids
                or step4_result.excluded_rc_node_ids
                or step4_result.excluded_rc_road_ids
                or step4_result.uncovered_selected_endpoint_node_ids
                or step4_result.selected_node_cover_repair_discarded_due_to_extra_roads
                or step4_result.multi_node_selected_cover_repair_applied
                or step4_result.stage3_rc_gap_records
            )
            if step4_result is not None
            else bool(
                inputs.selected_rc_node_count
                or inputs.selected_rc_road_count
                or inputs.polygon_support_rc_node_count
                or inputs.polygon_support_rc_road_count
                or inputs.invalid_rc_node_count
                or inputs.invalid_rc_road_count
            )
        ),
        step5_foreign_baseline_established=(
            step5_contract_decision.foreign_baseline_established
        ),
        step5_foreign_exclusion_established=(
            step5_contract_decision.canonical_foreign_established
        ),
        step5_foreign_subtype=step5_contract_decision.foreign_subtype,
        step5_canonical_reason=step5_contract_decision.canonical_foreign_reason,
        step5_foreign_residual_present=step5_contract_decision.residual_foreign_present,
        step6_geometry_established=(
            step6_result.geometry_established
            if step6_result is not None
            else not inputs.polygon_is_empty
        ),
        max_target_group_foreign_semantic_road_overlap_m=(
            step6_result.foreign_overlap_metric_m
            if step6_result is not None
            else step5_result.foreign_overlap_metric_m
            if step5_result is not None
            else inputs.max_target_group_foreign_semantic_road_overlap_m
        ),
        max_selected_side_branch_covered_length_m=(
            step6_result.max_selected_side_branch_covered_length_m
            if step6_result is not None
            else inputs.max_selected_side_branch_covered_length_m
        ),
        post_trim_non_target_tail_length_m=(
            step6_result.foreign_tail_length_m
            if step6_result is not None
            else step5_result.foreign_tail_length_m
            if step5_result is not None
            else inputs.post_trim_non_target_tail_length_m
        ),
        foreign_overlap_zero_but_tail_present=(
            step6_result.foreign_overlap_zero_but_tail_present
            if step6_result is not None
            else step5_result.foreign_overlap_zero_but_tail_present
            if step5_result is not None
            else inputs.foreign_overlap_zero_but_tail_present
        ),
        decision_basis=decision_basis,
        blocking_step=blocking_step,
        legacy_review_metadata_source="step7_acceptance_builder_v1",
        audit_facts=step7_audit_facts,
    )
    return Stage3LegacyStep7Assembly(
        context=inputs.context,
        step7_result=step7_result,
        step3_result=step3_result,
        step4_result=step4_result,
        step5_result=step5_result,
        step6_result=step6_result,
        step3_signals=tuple(sorted(set(step3_contract_signals))),
        step4_signals=tuple(sorted(set(step4_contract_signals))),
        step5_signals=tuple(sorted(set(step5_contract_signals))),
        step5_foreign_subtype=step5_contract_decision.foreign_subtype,
        step5_foreign_overlap_metric_m=(
            step5_result.foreign_overlap_metric_m
            if step5_result is not None
            else inputs.max_target_group_foreign_semantic_road_overlap_m
        ),
        step5_foreign_tail_length_m=(
            step5_result.foreign_tail_length_m
            if step5_result is not None
            else inputs.post_trim_non_target_tail_length_m
        ),
        step5_foreign_strip_extent_m=(
            step5_result.foreign_strip_extent_m
            if step5_result is not None
            else inputs.max_nonmain_branch_polygon_length_m
        ),
        step5_foreign_overlap_zero_but_tail_present=(
            step5_result.foreign_overlap_zero_but_tail_present
            if step5_result is not None
            else inputs.foreign_overlap_zero_but_tail_present
        ),
        step6_optimizer_events=tuple(sorted(set(step6_optimizer_events))),
        step6_geometry_problem_flags=tuple(sorted(set(step6_geometry_problem_flags))),
    )
