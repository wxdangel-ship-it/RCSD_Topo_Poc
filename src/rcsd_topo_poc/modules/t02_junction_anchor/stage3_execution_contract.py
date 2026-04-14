from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True, kw_only=True)
class Stage3Context:
    representative_node_id: str
    normalized_mainnodeid: str
    template_class: str
    representative_kind: Any | None = None
    representative_kind_2: int | None = None
    representative_grade_2: int | None = None
    semantic_junction_set: frozenset[str] = field(default_factory=frozenset)
    analysis_member_node_ids: frozenset[str] = field(default_factory=frozenset)
    group_node_ids: frozenset[str] = field(default_factory=frozenset)
    local_node_ids: frozenset[str] = field(default_factory=frozenset)
    local_road_ids: frozenset[str] = field(default_factory=frozenset)
    local_rc_node_ids: frozenset[str] = field(default_factory=frozenset)
    local_rc_road_ids: frozenset[str] = field(default_factory=frozenset)
    road_branch_ids: tuple[str, ...] = field(default_factory=tuple)
    analysis_center_xy: tuple[float, float] | None = None


@dataclass(frozen=True, kw_only=True)
class Stage3Step3LegalSpaceResult:
    template_class: str
    legal_activity_space_geometry: Any | None = None
    allowed_drivezone_geometry: Any | None = None
    must_cover_group_node_ids: frozenset[str] = field(default_factory=frozenset)
    hard_boundary_road_ids: frozenset[str] = field(default_factory=frozenset)
    single_sided_corridor_road_ids: frozenset[str] = field(default_factory=frozenset)
    step3_blockers: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class Stage3Step4RCSemanticsResult:
    required_rc_node_ids: frozenset[str] = field(default_factory=frozenset)
    required_rc_road_ids: frozenset[str] = field(default_factory=frozenset)
    support_rc_node_ids: frozenset[str] = field(default_factory=frozenset)
    support_rc_road_ids: frozenset[str] = field(default_factory=frozenset)
    excluded_rc_node_ids: frozenset[str] = field(default_factory=frozenset)
    excluded_rc_road_ids: frozenset[str] = field(default_factory=frozenset)
    review_excluded_rc_node_ids: frozenset[str] = field(default_factory=frozenset)
    review_excluded_rc_road_ids: frozenset[str] = field(default_factory=frozenset)
    selected_rc_endpoint_node_ids: frozenset[str] = field(default_factory=frozenset)
    hard_selected_endpoint_node_ids: frozenset[str] = field(default_factory=frozenset)
    uncovered_selected_endpoint_node_ids: frozenset[str] = field(default_factory=frozenset)
    selected_node_cover_repair_discarded_due_to_extra_roads: bool = False
    multi_node_selected_cover_repair_applied: bool = False
    stage3_rc_gap_records: tuple[str, ...] = field(default_factory=tuple)
    audit_facts: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class Stage3Step5ForeignModelResult:
    foreign_semantic_node_ids: frozenset[str] = field(default_factory=frozenset)
    foreign_road_arm_corridor_ids: frozenset[str] = field(default_factory=frozenset)
    foreign_rc_context_ids: frozenset[str] = field(default_factory=frozenset)
    foreign_trim_geometry: Any | None = None
    foreign_baseline_established: bool = False
    blocking_foreign_established: bool = False
    canonical_foreign_established: bool = False
    canonical_foreign_reason: str | None = None
    foreign_subtype: str | None = None
    foreign_overlap_metric_m: float | None = None
    foreign_tail_length_m: float | None = None
    foreign_strip_extent_m: float | None = None
    foreign_overlap_zero_but_tail_present: bool | None = None
    single_sided_unrelated_opposite_lane_trim_applied: bool = False
    soft_excluded_rc_corridor_trim_applied: bool = False
    foreign_tail_records: tuple[str, ...] = field(default_factory=tuple)
    foreign_overlap_records: tuple[str, ...] = field(default_factory=tuple)
    audit_facts: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class Stage3Step6GeometrySolveResult:
    seed_geometry: Any | None = None
    primary_solved_geometry: Any | None = None
    bounded_optimizer_geometry: Any | None = None
    geometry_established: bool = False
    geometry_review_reason: str | None = None
    residual_step5_blocking_foreign_required: bool = False
    max_selected_side_branch_covered_length_m: float | None = None
    polygon_aspect_ratio: float | None = None
    polygon_compactness: float | None = None
    polygon_bbox_fill_ratio: float | None = None
    selected_node_repair_attempted: bool = False
    selected_node_repair_applied: bool = False
    selected_node_repair_discarded_due_to_extra_roads: bool = False
    introduced_extra_local_road_ids: tuple[str, ...] = field(default_factory=tuple)
    remaining_uncovered_selected_endpoint_node_ids: frozenset[str] = field(default_factory=frozenset)
    remaining_foreign_semantic_node_ids: frozenset[str] = field(default_factory=frozenset)
    remaining_foreign_road_arm_corridor_ids: frozenset[str] = field(default_factory=frozenset)
    optimizer_events: tuple[str, ...] = field(default_factory=tuple)
    must_cover_validation: tuple[str, ...] = field(default_factory=tuple)
    foreign_exclusion_validation: tuple[str, ...] = field(default_factory=tuple)
    final_validation_flags: tuple[str, ...] = field(default_factory=tuple)
    foreign_overlap_metric_m: float | None = None
    foreign_tail_length_m: float | None = None
    foreign_overlap_zero_but_tail_present: bool | None = None
    geometry_problem_flags: tuple[str, ...] = field(default_factory=tuple)
    audit_facts: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class Stage3Step7AcceptanceResult:
    mainnodeid: str
    template_class: str
    status: str
    success: bool
    business_outcome_class: str
    acceptance_class: str
    acceptance_reason: str
    root_cause_layer: str | None
    root_cause_type: str | None
    visual_review_class: str
    step3_legal_space_established: bool = False
    step4_required_rc_established: bool = False
    step5_foreign_baseline_established: bool = False
    step5_foreign_exclusion_established: bool = False
    step5_foreign_subtype: str | None = None
    step5_canonical_reason: str | None = None
    step5_foreign_residual_present: bool = False
    step6_geometry_established: bool = False
    max_target_group_foreign_semantic_road_overlap_m: float | None = None
    max_selected_side_branch_covered_length_m: float | None = None
    post_trim_non_target_tail_length_m: float | None = None
    foreign_overlap_zero_but_tail_present: bool | None = None
    decision_basis: tuple[str, ...] = field(default_factory=tuple)
    blocking_step: str | None = None
    legacy_review_metadata_source: str = "legacy_fallback"
    audit_facts: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class Stage3AuditRecord:
    mainnodeid: str
    step7: Stage3Step7AcceptanceResult
    official_review_eligible: bool
    blocking_reason: str | None
    failure_bucket: str
    context: Stage3Context | None = None
    step3: Stage3Step3LegalSpaceResult | None = None
    step4: Stage3Step4RCSemanticsResult | None = None
    step5: Stage3Step5ForeignModelResult | None = None
    step6: Stage3Step6GeometrySolveResult | None = None


def build_stage3_context(
    *,
    representative_node_id: str,
    normalized_mainnodeid: str,
    template_class: str,
    representative_kind: Any | None = None,
    representative_kind_2: int | None = None,
    representative_grade_2: int | None = None,
    semantic_junction_set: Iterable[str] = (),
    analysis_member_node_ids: Iterable[str] = (),
    group_node_ids: Iterable[str] = (),
    local_node_ids: Iterable[str] = (),
    local_road_ids: Iterable[str] = (),
    local_rc_node_ids: Iterable[str] = (),
    local_rc_road_ids: Iterable[str] = (),
    road_branch_ids: Iterable[str] = (),
    analysis_center_xy: tuple[float, float] | None = None,
) -> Stage3Context:
    return Stage3Context(
        representative_node_id=representative_node_id,
        normalized_mainnodeid=normalized_mainnodeid,
        template_class=template_class,
        representative_kind=representative_kind,
        representative_kind_2=representative_kind_2,
        representative_grade_2=representative_grade_2,
        semantic_junction_set=frozenset(str(node_id) for node_id in semantic_junction_set),
        analysis_member_node_ids=frozenset(str(node_id) for node_id in analysis_member_node_ids),
        group_node_ids=frozenset(str(node_id) for node_id in group_node_ids),
        local_node_ids=frozenset(str(node_id) for node_id in local_node_ids),
        local_road_ids=frozenset(str(road_id) for road_id in local_road_ids),
        local_rc_node_ids=frozenset(str(node_id) for node_id in local_rc_node_ids),
        local_rc_road_ids=frozenset(str(road_id) for road_id in local_rc_road_ids),
        road_branch_ids=tuple(str(branch_id) for branch_id in road_branch_ids),
        analysis_center_xy=analysis_center_xy,
    )
