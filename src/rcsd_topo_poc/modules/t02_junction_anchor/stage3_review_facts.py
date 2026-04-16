from __future__ import annotations

from dataclasses import dataclass


ROOT_CAUSE_LAYER_STEP3 = "step3"
ROOT_CAUSE_LAYER_STEP4 = "step4"
ROOT_CAUSE_LAYER_STEP5 = "step5"
ROOT_CAUSE_LAYER_STEP6 = "step6"
ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT = "frozen-constraints conflict"

VISUAL_REVIEW_V1 = "V1 认可成功"
VISUAL_REVIEW_V2 = "V2 业务正确但几何待修"
VISUAL_REVIEW_V3 = "V3 漏包 required"
VISUAL_REVIEW_V4 = "V4 误包 foreign"
VISUAL_REVIEW_V5 = "V5 明确失败"

BUSINESS_OUTCOME_SUCCESS = "success"
BUSINESS_OUTCOME_RISK = "risk"
BUSINESS_OUTCOME_FAILURE = "failure"


@dataclass(frozen=True)
class Stage3ReviewFields:
    root_cause_layer: str | None
    root_cause_type: str | None
    visual_review_class: str
    business_outcome_class: str


def business_outcome_from_visual_review_class(visual_review_class: str) -> str:
    if visual_review_class == VISUAL_REVIEW_V1:
        return BUSINESS_OUTCOME_SUCCESS
    if visual_review_class == VISUAL_REVIEW_V2:
        return BUSINESS_OUTCOME_RISK
    return BUSINESS_OUTCOME_FAILURE


def acceptance_class_from_business_outcome(business_outcome_class: str) -> str:
    if business_outcome_class == BUSINESS_OUTCOME_SUCCESS:
        return "accepted"
    if business_outcome_class == BUSINESS_OUTCOME_RISK:
        return "review_required"
    return "rejected"


def success_flag_from_business_outcome(business_outcome_class: str) -> bool:
    return business_outcome_class == BUSINESS_OUTCOME_SUCCESS


def derive_stage3_review_fields(
    *,
    success: bool,
    acceptance_class: str | None,
    acceptance_reason: str | None,
    status: str | None,
) -> Stage3ReviewFields:
    token = ((acceptance_reason or status) or "").lower()
    status_token = (status or "").lower()
    explicit_step6_review_tokens = {
        "nonstable_center_junction_extreme_geometry_anomaly",
        "stable_compound_center_requires_review",
        "stable_overlap_requires_review",
        "stable_single_sided_mouth_geometry_requires_review",
    }
    explicit_step4_review_tokens = {
        "outside_rc_gap_requires_review",
        "soft_overlap_requires_review",
        "stable_sparse_rc_context_requires_review",
    }
    has_required_rc_gap = any(
        key in token
        for key in (
            "stage3_rc_gap",
            "required_branch",
            "required_rc",
            "required rc",
            "required_handoff",
        )
    )
    has_foreign_intrusion = any(
        key in token
        for key in (
            "foreign",
            "opposite_lane",
            "intrusion",
            "outside_drivezone_soft_excluded",
            "foreign_semantic_road_overlap",
            "foreign_corridor_intrusion",
        )
    )
    if token.startswith("review_required_status:") or token.startswith("rejected_status:"):
        status_token = token.split(":", 1)[1]

    if any(
        key in token
        for key in (
            "mainnodeid",
            "missing_required_field",
            "invalid_crs",
            "representative_node_missing",
            "out_of_scope",
            "anchor_gate",
        )
    ):
        root_cause_layer = ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT
    elif token in explicit_step6_review_tokens:
        root_cause_layer = ROOT_CAUSE_LAYER_STEP6
    elif token in explicit_step4_review_tokens:
        root_cause_layer = ROOT_CAUSE_LAYER_STEP4
    elif has_foreign_intrusion:
        root_cause_layer = ROOT_CAUSE_LAYER_STEP5
    elif status_token in {"surface_only", "node_component_conflict"} or any(
        key in token
        for key in (
            "shape_artifact",
            "geometry_",
            "cleanup_",
            "template_misfit",
            "weak_main_direction",
            "stable_compound_center_requires_review",
            "stable_overlap_requires_review",
            "stable_single_sided_mouth_geometry_requires_review",
        )
    ):
        root_cause_layer = ROOT_CAUSE_LAYER_STEP6
    elif has_required_rc_gap or any(
        key in token
        for key in (
            "rc_gap",
            "rcsd_",
            "rc_context",
            "rc_group_semantic_gap",
            "sparse_rc_association",
            "outside_rc_gap_requires_review",
            "soft_overlap_requires_review",
            "stable_sparse_rc_context_requires_review",
        )
    ) or status_token in {
        "no_valid_rc_connection",
        "ambiguous_rc_match",
        "weak_branch_support",
    }:
        root_cause_layer = ROOT_CAUSE_LAYER_STEP4
    elif any(
        key in token
        for key in (
            "review_required_status",
            "rejected_status",
        )
    ):
        root_cause_layer = ROOT_CAUSE_LAYER_STEP6
    elif token:
        root_cause_layer = ROOT_CAUSE_LAYER_STEP3
    else:
        root_cause_layer = None

    if root_cause_layer == ROOT_CAUSE_LAYER_FROZEN_CONSTRAINTS_CONFLICT:
        visual_review_class = VISUAL_REVIEW_V5
    elif root_cause_layer == ROOT_CAUSE_LAYER_STEP5:
        visual_review_class = VISUAL_REVIEW_V4
    elif success and acceptance_class == "accepted" and status_token == "stable":
        visual_review_class = VISUAL_REVIEW_V1
    elif root_cause_layer == ROOT_CAUSE_LAYER_STEP4 and has_required_rc_gap:
        visual_review_class = VISUAL_REVIEW_V3
    elif acceptance_class == "review_required" or status_token in {
        "surface_only",
        "weak_branch_support",
        "ambiguous_rc_match",
        "no_valid_rc_connection",
        "node_component_conflict",
    }:
        visual_review_class = VISUAL_REVIEW_V2
    else:
        visual_review_class = VISUAL_REVIEW_V5

    return Stage3ReviewFields(
        root_cause_layer=root_cause_layer,
        root_cause_type=(acceptance_reason or status),
        visual_review_class=visual_review_class,
        business_outcome_class=business_outcome_from_visual_review_class(
            visual_review_class
        ),
    )
