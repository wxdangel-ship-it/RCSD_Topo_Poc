from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_execution_contract import (
    Stage3AuditRecord,
    Stage3Context,
    Stage3Step7AcceptanceResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_context_builder import (
    build_minimal_stage3_context,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_contract import (
    Stage3OfficialReviewDecision,
    Stage3ReviewMetadata,
    canonicalize_stage3_step7_result_from_official_review_decision,
    stage3_official_review_decision_from_step7_result,
    stage3_review_metadata_from_step7_result,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_step7_acceptance import (
    Stage3LegacyStep7Assembly,
    build_stage3_failure_step7_result,
)


STAGE3_EXECUTION_CONTRACT_VERSION = "phase8-vclass-outcome-contract-v1"


@dataclass(frozen=True)
class LegacyStage3AuditEnvelope:
    review_metadata: Stage3ReviewMetadata
    official_review_decision: Stage3OfficialReviewDecision
    audit_record: Stage3AuditRecord


def _sorted_unique(values: Sequence[str] | None) -> tuple[str, ...]:
    if not values:
        return ()
    return tuple(sorted({str(value) for value in values if str(value).strip()}))


def _signal_metric(name: str, value: Any | None) -> str | None:
    if value is None:
        return None
    return f"{name}={value}"


def build_legacy_stage3_audit_envelope_from_step7_assembly(
    *,
    mainnodeid: str,
    step7_assembly: Stage3LegacyStep7Assembly,
    representative_has_evd: Any | None,
    representative_is_anchor: Any | None,
    representative_kind_2: Any | None,
) -> LegacyStage3AuditEnvelope:
    raw_step7_result = step7_assembly.step7_result
    step3_result = step7_assembly.step3_result
    step4_result = step7_assembly.step4_result
    step5_result = step7_assembly.step5_result
    step6_result = step7_assembly.step6_result
    official_review_decision = stage3_official_review_decision_from_step7_result(
        raw_step7_result,
        representative_has_evd=representative_has_evd,
        representative_is_anchor=representative_is_anchor,
        representative_kind_2=representative_kind_2,
    )
    step7_result = canonicalize_stage3_step7_result_from_official_review_decision(
        raw_step7_result,
        official_review_decision=official_review_decision,
    )
    review_metadata = stage3_review_metadata_from_step7_result(
        step7_result,
        official_review_decision=official_review_decision,
    )
    audit_record = Stage3AuditRecord(
        mainnodeid=mainnodeid,
        context=step7_assembly.context,
        step3=step3_result,
        step4=step4_result,
        step5=step5_result,
        step6=step6_result,
        step7=step7_result,
        official_review_eligible=official_review_decision.official_review_eligible,
        blocking_reason=official_review_decision.blocking_reason,
        failure_bucket=official_review_decision.failure_bucket,
    )
    return LegacyStage3AuditEnvelope(
        review_metadata=review_metadata,
        official_review_decision=official_review_decision,
        audit_record=audit_record,
    )


def build_stage3_failure_audit_envelope(
    *,
    mainnodeid: str,
    acceptance_reason: str,
    template_class: str = "",
    context: Stage3Context | None = None,
    status: str | None = None,
    representative_has_evd: Any | None = None,
    representative_is_anchor: Any | None = None,
    representative_kind_2: Any | None = None,
    step7_result: Stage3Step7AcceptanceResult | None = None,
) -> LegacyStage3AuditEnvelope:
    if step7_result is None:
        step7_result = build_stage3_failure_step7_result(
            mainnodeid=mainnodeid,
            template_class=template_class,
            acceptance_reason=acceptance_reason,
            status=status,
        )
    official_review_decision = stage3_official_review_decision_from_step7_result(
        step7_result,
        representative_has_evd=representative_has_evd,
        representative_is_anchor=representative_is_anchor,
        representative_kind_2=representative_kind_2,
    )
    step7_result = canonicalize_stage3_step7_result_from_official_review_decision(
        step7_result,
        official_review_decision=official_review_decision,
    )
    review_metadata = stage3_review_metadata_from_step7_result(
        step7_result,
        official_review_decision=official_review_decision,
    )
    return LegacyStage3AuditEnvelope(
        review_metadata=review_metadata,
        official_review_decision=official_review_decision,
        audit_record=Stage3AuditRecord(
            mainnodeid=mainnodeid,
            context=(
                context
                if context is not None
                else build_minimal_stage3_context(
                    representative_node_id=mainnodeid,
                    normalized_mainnodeid=mainnodeid,
                    template_class=template_class,
                    representative_kind_2=representative_kind_2,
                )
            ),
            step7=step7_result,
            official_review_eligible=official_review_decision.official_review_eligible,
            blocking_reason=official_review_decision.blocking_reason,
            failure_bucket=official_review_decision.failure_bucket,
            step3=None,
            step4=None,
            step5=None,
            step6=None,
        ),
    )


def stage3_step7_acceptance_result_dict(
    result: Stage3Step7AcceptanceResult,
) -> dict[str, Any]:
    return {
        "mainnodeid": result.mainnodeid,
        "template_class": result.template_class,
        "status": result.status,
        "success": result.success,
        "business_outcome_class": result.business_outcome_class,
        "acceptance_class": result.acceptance_class,
        "acceptance_reason": result.acceptance_reason,
        "root_cause_layer": result.root_cause_layer,
        "root_cause_type": result.root_cause_type,
        "visual_review_class": result.visual_review_class,
        "step3_legal_space_established": result.step3_legal_space_established,
        "step4_required_rc_established": result.step4_required_rc_established,
        "step5_foreign_baseline_established": result.step5_foreign_baseline_established,
        "step5_foreign_exclusion_established": result.step5_foreign_exclusion_established,
        "step5_foreign_subtype": result.step5_foreign_subtype,
        "step5_canonical_reason": result.step5_canonical_reason,
        "step5_foreign_residual_present": result.step5_foreign_residual_present,
        "step6_geometry_established": result.step6_geometry_established,
        "max_target_group_foreign_semantic_road_overlap_m": result.max_target_group_foreign_semantic_road_overlap_m,
        "max_selected_side_branch_covered_length_m": result.max_selected_side_branch_covered_length_m,
        "post_trim_non_target_tail_length_m": result.post_trim_non_target_tail_length_m,
        "foreign_overlap_zero_but_tail_present": result.foreign_overlap_zero_but_tail_present,
        "decision_basis": list(result.decision_basis),
        "blocking_step": result.blocking_step,
        "legacy_review_metadata_source": result.legacy_review_metadata_source,
        "audit_facts": list(result.audit_facts),
    }


def stage3_audit_record_dict(record: Stage3AuditRecord) -> dict[str, Any]:
    return {
        "mainnodeid": record.mainnodeid,
        "official_review_eligible": record.official_review_eligible,
        "blocking_reason": record.blocking_reason,
        "failure_bucket": record.failure_bucket,
        "context": (
            {
                "representative_node_id": record.context.representative_node_id,
                "normalized_mainnodeid": record.context.normalized_mainnodeid,
                "template_class": record.context.template_class,
                "representative_kind": record.context.representative_kind,
                "representative_kind_2": record.context.representative_kind_2,
                "representative_grade_2": record.context.representative_grade_2,
                "semantic_junction_set": list(record.context.semantic_junction_set),
                "analysis_member_node_ids": list(record.context.analysis_member_node_ids),
                "group_node_ids": list(record.context.group_node_ids),
                "local_node_ids": list(record.context.local_node_ids),
                "local_road_ids": list(record.context.local_road_ids),
                "local_rc_node_ids": list(record.context.local_rc_node_ids),
                "local_rc_road_ids": list(record.context.local_rc_road_ids),
                "road_branch_ids": list(record.context.road_branch_ids),
                "analysis_center_xy": list(record.context.analysis_center_xy)
                if record.context.analysis_center_xy is not None
                else None,
            }
            if record.context is not None
            else None
        ),
        "step3": (
            {
                "template_class": record.step3.template_class,
                "must_cover_group_node_ids": list(record.step3.must_cover_group_node_ids),
                "hard_boundary_road_ids": list(record.step3.hard_boundary_road_ids),
                "single_sided_corridor_road_ids": list(
                    record.step3.single_sided_corridor_road_ids
                ),
                "step3_blockers": list(record.step3.step3_blockers),
            }
            if record.step3 is not None
            else None
        ),
        "step4": (
            {
                "required_rc_node_ids": list(record.step4.required_rc_node_ids),
                "required_rc_road_ids": list(record.step4.required_rc_road_ids),
                "support_rc_node_ids": list(record.step4.support_rc_node_ids),
                "support_rc_road_ids": list(record.step4.support_rc_road_ids),
                "excluded_rc_node_ids": list(record.step4.excluded_rc_node_ids),
                "excluded_rc_road_ids": list(record.step4.excluded_rc_road_ids),
                "selected_rc_endpoint_node_ids": list(record.step4.selected_rc_endpoint_node_ids),
                "hard_selected_endpoint_node_ids": list(record.step4.hard_selected_endpoint_node_ids),
                "uncovered_selected_endpoint_node_ids": list(
                    record.step4.uncovered_selected_endpoint_node_ids
                ),
                "selected_node_cover_repair_discarded_due_to_extra_roads": (
                    record.step4.selected_node_cover_repair_discarded_due_to_extra_roads
                ),
                "multi_node_selected_cover_repair_applied": (
                    record.step4.multi_node_selected_cover_repair_applied
                ),
                "stage3_rc_gap_records": list(record.step4.stage3_rc_gap_records),
                "audit_facts": list(record.step4.audit_facts),
            }
            if record.step4 is not None
            else None
        ),
        "step5": (
            {
                "foreign_semantic_node_ids": list(record.step5.foreign_semantic_node_ids),
                "foreign_road_arm_corridor_ids": list(record.step5.foreign_road_arm_corridor_ids),
                "foreign_rc_context_ids": list(record.step5.foreign_rc_context_ids),
                "foreign_baseline_established": record.step5.foreign_baseline_established,
                "blocking_foreign_established": record.step5.blocking_foreign_established,
                "canonical_foreign_established": record.step5.canonical_foreign_established,
                "canonical_foreign_reason": record.step5.canonical_foreign_reason,
                "foreign_subtype": record.step5.foreign_subtype,
                "foreign_overlap_metric_m": record.step5.foreign_overlap_metric_m,
                "foreign_tail_length_m": record.step5.foreign_tail_length_m,
                "foreign_strip_extent_m": record.step5.foreign_strip_extent_m,
                "foreign_overlap_zero_but_tail_present": record.step5.foreign_overlap_zero_but_tail_present,
                "single_sided_unrelated_opposite_lane_trim_applied": (
                    record.step5.single_sided_unrelated_opposite_lane_trim_applied
                ),
                "soft_excluded_rc_corridor_trim_applied": (
                    record.step5.soft_excluded_rc_corridor_trim_applied
                ),
                "foreign_tail_records": list(record.step5.foreign_tail_records),
                "foreign_overlap_records": list(record.step5.foreign_overlap_records),
                "audit_facts": list(record.step5.audit_facts),
            }
            if record.step5 is not None
            else None
        ),
        "step6": (
            {
                "geometry_established": record.step6.geometry_established,
                "geometry_review_reason": record.step6.geometry_review_reason,
                "max_selected_side_branch_covered_length_m": (
                    record.step6.max_selected_side_branch_covered_length_m
                ),
                "polygon_aspect_ratio": record.step6.polygon_aspect_ratio,
                "polygon_compactness": record.step6.polygon_compactness,
                "polygon_bbox_fill_ratio": record.step6.polygon_bbox_fill_ratio,
                "selected_node_repair_attempted": record.step6.selected_node_repair_attempted,
                "selected_node_repair_applied": record.step6.selected_node_repair_applied,
                "selected_node_repair_discarded_due_to_extra_roads": (
                    record.step6.selected_node_repair_discarded_due_to_extra_roads
                ),
                "introduced_extra_local_road_ids": list(
                    record.step6.introduced_extra_local_road_ids
                ),
                "remaining_uncovered_selected_endpoint_node_ids": list(
                    record.step6.remaining_uncovered_selected_endpoint_node_ids
                ),
                "remaining_foreign_semantic_node_ids": list(
                    record.step6.remaining_foreign_semantic_node_ids
                ),
                "remaining_foreign_road_arm_corridor_ids": list(
                    record.step6.remaining_foreign_road_arm_corridor_ids
                ),
                "optimizer_events": list(record.step6.optimizer_events),
                "must_cover_validation": list(record.step6.must_cover_validation),
                "foreign_exclusion_validation": list(record.step6.foreign_exclusion_validation),
                "foreign_overlap_metric_m": record.step6.foreign_overlap_metric_m,
                "foreign_tail_length_m": record.step6.foreign_tail_length_m,
                "foreign_overlap_zero_but_tail_present": (
                    record.step6.foreign_overlap_zero_but_tail_present
                ),
                "geometry_problem_flags": list(record.step6.geometry_problem_flags),
                "audit_facts": list(record.step6.audit_facts),
            }
            if record.step6 is not None
            else None
        ),
        "step7": stage3_step7_acceptance_result_dict(record.step7),
    }
