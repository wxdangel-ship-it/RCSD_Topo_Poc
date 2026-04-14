from __future__ import annotations

from dataclasses import dataclass

STATUS_STABLE = "stable"
STATUS_AMBIGUOUS_RC_MATCH = "ambiguous_rc_match"
STATUS_NO_VALID_RC_CONNECTION = "no_valid_rc_connection"
STATUS_WEAK_BRANCH_SUPPORT = "weak_branch_support"
TEMPLATE_CENTER_JUNCTION = "center_junction"
TEMPLATE_SINGLE_SIDED_T_MOUTH = "single_sided_t_mouth"


def _as_flag(value: bool, label: str) -> str | None:
    return label if value else None


@dataclass(frozen=True)
class Stage3Step6GeometryControllerInputs:
    template_class: str
    status: str
    geometry_established: bool
    step5_canonical_foreign_established: bool
    can_soft_exclude_outside_rc: bool
    rc_outside_drivezone_present: bool
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
    foreign_tail_length_m: float
    foreign_overlap_zero_but_tail_present: bool
    compound_center_applied: bool = False


@dataclass(frozen=True)
class Stage3Step6GeometryControllerDecision:
    geometry_review_reason: str | None
    residual_step5_blocking_foreign_required: bool = False
    final_validation_flags: tuple[str, ...] = ()


def derive_stage3_step6_geometry_controller_decision(
    inputs: Stage3Step6GeometryControllerInputs,
) -> Stage3Step6GeometryControllerDecision:
    flags: list[str] = [
        _as_flag(inputs.geometry_established, "geometry_established"),
        _as_flag(
            inputs.step5_canonical_foreign_established,
            "step5_canonical_foreign_established",
        ),
        _as_flag(inputs.compound_center_applied, "compound_center_applied"),
        (
            f"polygon_aspect_ratio={inputs.polygon_aspect_ratio:.3f}"
            if inputs.polygon_aspect_ratio is not None
            else None
        ),
        (
            f"polygon_compactness={inputs.polygon_compactness:.3f}"
            if inputs.polygon_compactness is not None
            else None
        ),
        (
            f"polygon_bbox_fill_ratio={inputs.polygon_bbox_fill_ratio:.3f}"
            if inputs.polygon_bbox_fill_ratio is not None
            else None
        ),
    ]

    if not inputs.geometry_established:
        return Stage3Step6GeometryControllerDecision(
            geometry_review_reason=None,
            final_validation_flags=tuple(sorted(flag for flag in flags if flag)),
        )

    if inputs.step5_canonical_foreign_established:
        flags.append("step6_geometry_review_deferred_to_step5")
        return Stage3Step6GeometryControllerDecision(
            geometry_review_reason=None,
            final_validation_flags=tuple(sorted(flag for flag in flags if flag)),
        )

    reason: str | None = None
    if inputs.status == STATUS_STABLE:
        if (
            inputs.template_class == TEMPLATE_SINGLE_SIDED_T_MOUTH
            and not inputs.single_sided_unrelated_opposite_lane_trim_applied
            and inputs.excluded_rc_road_count == 0
            and inputs.local_node_count >= 4
            and inputs.local_road_count >= 8
            and inputs.max_selected_side_branch_covered_length_m >= 8.0
            and inputs.max_nonmain_branch_polygon_length_m >= 8.0
            and inputs.polygon_compactness is not None
            and inputs.polygon_compactness <= 0.30
            and inputs.polygon_bbox_fill_ratio is not None
            and inputs.polygon_bbox_fill_ratio <= 0.35
        ):
            reason = "stable_single_sided_mouth_geometry_requires_review"
        elif inputs.compound_center_applied:
            reason = "stable_compound_center_requires_review"
        elif (
            inputs.max_target_group_foreign_semantic_road_overlap_m >= 10.0
            and inputs.effective_associated_rc_node_count < 4
        ):
            reason = "stable_overlap_requires_review"
        elif (
            inputs.associated_rc_node_count == 0
            and inputs.effective_associated_rc_node_count == 0
            and inputs.max_nonmain_branch_polygon_length_m <= 5.0
        ):
            reason = "stable_sparse_rc_context_requires_review"

    if (
        reason is None
        and inputs.rc_outside_drivezone_present
        and inputs.can_soft_exclude_outside_rc
    ):
        if (
            inputs.template_class == TEMPLATE_SINGLE_SIDED_T_MOUTH
            and inputs.max_target_group_foreign_semantic_road_overlap_m <= 1.0
            and inputs.associated_rc_road_count <= 2
            and inputs.effective_associated_rc_node_count == 0
            and inputs.polygon_aspect_ratio is not None
            and inputs.polygon_aspect_ratio <= 2.1
            and inputs.polygon_compactness is not None
            and inputs.polygon_compactness <= 0.30
        ):
            reason = "outside_rc_gap_requires_review"
        elif inputs.soft_excluded_rc_corridor_trim_applied:
            reason = "outside_rc_gap_requires_review"
        elif (
            inputs.status
            in {
                STATUS_STABLE,
                STATUS_AMBIGUOUS_RC_MATCH,
                STATUS_NO_VALID_RC_CONNECTION,
                STATUS_WEAK_BRANCH_SUPPORT,
            }
            and not (
                inputs.positive_rc_group_count >= 2
                and inputs.negative_rc_group_count == 0
            )
        ):
            reason = "outside_rc_gap_requires_review"

    residual_step5_blocking_foreign_required = bool(
        inputs.status == STATUS_STABLE
        and reason in {"stable_overlap_requires_review", "outside_rc_gap_requires_review"}
        and inputs.max_target_group_foreign_semantic_road_overlap_m >= 8.0
    )
    if residual_step5_blocking_foreign_required:
        flags.append("step6_residual_step5_blocking_foreign_required")

    if reason:
        flags.append(f"step6_geometry_review_reason={reason}")

    return Stage3Step6GeometryControllerDecision(
        geometry_review_reason=reason,
        residual_step5_blocking_foreign_required=(
            residual_step5_blocking_foreign_required
        ),
        final_validation_flags=tuple(sorted(flag for flag in flags if flag)),
    )
