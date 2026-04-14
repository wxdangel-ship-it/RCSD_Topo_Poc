from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from rcsd_topo_poc.modules.t02_junction_anchor.stage3_audit_assembler import (
    STAGE3_EXECUTION_CONTRACT_VERSION,
    LegacyStage3AuditEnvelope,
    stage3_audit_record_dict,
    stage3_step7_acceptance_result_dict,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage3_review_contract import (
    Stage3OfficialReviewDecision,
    Stage3ReviewMetadata,
    stage3_official_review_decision_dict,
    stage3_review_metadata_dict,
)


@dataclass(frozen=True)
class Stage3OutputFilesPayload:
    virtual_intersection_polygon: str
    branch_evidence_json: str | None = None
    branch_evidence_geojson: str | None = None
    associated_rcsdroad: str | None = None
    associated_rcsdnode: str | None = None
    audit_csv: str | None = None
    audit_json: str | None = None
    rendered_map_png: str | None = None


@dataclass(frozen=True)
class Stage3SuccessOutputBundle:
    output_files: Stage3OutputFilesPayload
    status_doc: dict[str, Any]
    perf_doc: dict[str, Any]


@dataclass(frozen=True)
class Stage3FailureOutputBundle:
    output_files: Stage3OutputFilesPayload
    status_doc: dict[str, Any]
    perf_doc: dict[str, Any]


def build_stage3_output_files_payload(
    *,
    virtual_polygon_path: Path,
    branch_evidence_json_path: Path | None = None,
    branch_evidence_geojson_path: Path | None = None,
    associated_rcsdroad_path: Path | None = None,
    associated_rcsdnode_path: Path | None = None,
    audit_csv_path: Path | None = None,
    audit_json_path: Path | None = None,
    rendered_map_path: Path | None = None,
) -> Stage3OutputFilesPayload:
    return Stage3OutputFilesPayload(
        virtual_intersection_polygon=str(virtual_polygon_path),
        branch_evidence_json=(
            str(branch_evidence_json_path) if branch_evidence_json_path is not None else None
        ),
        branch_evidence_geojson=(
            str(branch_evidence_geojson_path) if branch_evidence_geojson_path is not None else None
        ),
        associated_rcsdroad=(
            str(associated_rcsdroad_path) if associated_rcsdroad_path is not None else None
        ),
        associated_rcsdnode=(
            str(associated_rcsdnode_path) if associated_rcsdnode_path is not None else None
        ),
        audit_csv=str(audit_csv_path) if audit_csv_path is not None else None,
        audit_json=str(audit_json_path) if audit_json_path is not None else None,
        rendered_map_png=str(rendered_map_path) if rendered_map_path is not None else None,
    )


def stage3_output_files_payload_dict(
    payload: Stage3OutputFilesPayload,
) -> dict[str, Any]:
    return {
        "virtual_intersection_polygon": payload.virtual_intersection_polygon,
        "branch_evidence_json": payload.branch_evidence_json,
        "branch_evidence_geojson": payload.branch_evidence_geojson,
        "associated_rcsdroad": payload.associated_rcsdroad,
        "associated_rcsdnode": payload.associated_rcsdnode,
        "audit_csv": payload.audit_csv,
        "audit_json": payload.audit_json,
        "virtual_intersection_polygon_gpkg": payload.virtual_intersection_polygon,
        "rendered_map_png": payload.rendered_map_png,
    }


def build_stage3_success_status_doc(
    *,
    run_id: str,
    business_match_class: str,
    business_match_reason: str | None,
    template_class: str,
    mainnodeid: str,
    representative_node_id: str,
    representative_kind: Any | None,
    representative_has_evd: Any | None,
    representative_is_anchor: Any | None,
    resolved_kind: Any | None,
    kind_source: str | None,
    kind_2: int | None,
    grade_2: int | None,
    counts: Mapping[str, Any],
    review_mode: bool,
    risks: list[str],
    patch: Mapping[str, Any],
    selected_positive_rc_groups: list[str],
    excluded_negative_rc_groups: list[str],
    single_sided_unrelated_opposite_lane_trim_applied: bool,
    soft_excluded_rc_corridor_trim_applied: bool,
    late_cleanup_flags: Mapping[str, bool],
    post_trim_non_target_tail_length_m: float,
    foreign_overlap_zero_but_tail_present: bool,
    review_metadata: Stage3ReviewMetadata,
    official_review_decision: Stage3OfficialReviewDecision,
    audit_envelope: LegacyStage3AuditEnvelope,
    output_files: Stage3OutputFilesPayload,
) -> dict[str, Any]:
    canonical_step7_result = audit_envelope.audit_record.step7
    return {
        "run_id": run_id,
        "success": canonical_step7_result.success,
        "flow_success": True,
        "business_outcome_class": canonical_step7_result.business_outcome_class,
        "acceptance_class": canonical_step7_result.acceptance_class,
        "acceptance_reason": canonical_step7_result.acceptance_reason,
        "business_match_class": business_match_class,
        "business_match_reason": business_match_reason,
        "template_class": template_class,
        "single_sided_unrelated_opposite_lane_trim_applied": single_sided_unrelated_opposite_lane_trim_applied,
        "soft_excluded_rc_corridor_trim_applied": soft_excluded_rc_corridor_trim_applied,
        **{key: bool(value) for key, value in late_cleanup_flags.items()},
        "post_trim_non_target_tail_length_m": post_trim_non_target_tail_length_m,
        "foreign_overlap_zero_but_tail_present": foreign_overlap_zero_but_tail_present,
        "mainnodeid": mainnodeid,
        "representative_node_id": representative_node_id,
        "representative_kind": representative_kind,
        "representative_has_evd": representative_has_evd,
        "representative_is_anchor": representative_is_anchor,
        "resolved_kind": resolved_kind,
        "kind_source": kind_source,
        "kind_2": kind_2,
        "grade_2": grade_2,
        "status": canonical_step7_result.status,
        "risks": risks,
        "counts": dict(counts),
        "review_mode": review_mode,
        **stage3_review_metadata_dict(review_metadata),
        **stage3_official_review_decision_dict(official_review_decision),
        "stage3_execution_contract_version": STAGE3_EXECUTION_CONTRACT_VERSION,
        "step7_result": stage3_step7_acceptance_result_dict(canonical_step7_result),
        "stage3_audit_record": stage3_audit_record_dict(audit_envelope.audit_record),
        "patch": dict(patch),
        "selected_positive_rc_groups": list(selected_positive_rc_groups),
        "excluded_negative_rc_groups": list(excluded_negative_rc_groups),
        "output_files": stage3_output_files_payload_dict(output_files),
    }


def build_stage3_failure_status_doc(
    *,
    run_id: str,
    mainnodeid: str,
    detail: str,
    counts: Mapping[str, Any],
    review_mode: bool,
    business_match_class: str,
    business_match_reason: str,
    representative_node_id: str | None,
    representative_kind: Any | None,
    representative_has_evd: Any | None,
    representative_is_anchor: Any | None,
    kind_2: int | None,
    grade_2: int | None,
    audit_envelope: LegacyStage3AuditEnvelope,
    output_files: Stage3OutputFilesPayload,
) -> dict[str, Any]:
    canonical_step7_result = audit_envelope.audit_record.step7
    return {
        "run_id": run_id,
        "success": canonical_step7_result.success,
        "flow_success": False,
        "business_outcome_class": canonical_step7_result.business_outcome_class,
        "acceptance_class": canonical_step7_result.acceptance_class,
        "acceptance_reason": canonical_step7_result.acceptance_reason,
        "business_match_class": business_match_class,
        "business_match_reason": business_match_reason,
        "mainnodeid": mainnodeid,
        "representative_node_id": representative_node_id,
        "representative_kind": representative_kind,
        "representative_has_evd": representative_has_evd,
        "representative_is_anchor": representative_is_anchor,
        "resolved_kind": None,
        "kind_source": None,
        "kind_2": kind_2,
        "grade_2": grade_2,
        "status": canonical_step7_result.status,
        "risks": [canonical_step7_result.acceptance_reason],
        "detail": detail,
        "counts": dict(counts),
        "review_mode": review_mode,
        **stage3_review_metadata_dict(audit_envelope.review_metadata),
        **stage3_official_review_decision_dict(audit_envelope.official_review_decision),
        "stage3_execution_contract_version": STAGE3_EXECUTION_CONTRACT_VERSION,
        "step7_result": stage3_step7_acceptance_result_dict(canonical_step7_result),
        "stage3_audit_record": stage3_audit_record_dict(audit_envelope.audit_record),
        "output_files": stage3_output_files_payload_dict(output_files),
    }


def build_stage3_perf_doc(
    *,
    run_id: str,
    success: bool,
    flow_success: bool,
    acceptance_class: str,
    business_outcome_class: str,
    acceptance_reason: str,
    business_match_class: str,
    business_match_reason: str,
    template_class: str,
    total_wall_time_sec: float,
    counts: Mapping[str, Any],
    stage_timings: Any,
    extra_fields: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    perf_doc = {
        "run_id": run_id,
        "success": success,
        "flow_success": flow_success,
        "business_outcome_class": business_outcome_class,
        "acceptance_class": acceptance_class,
        "acceptance_reason": acceptance_reason,
        "business_match_class": business_match_class,
        "business_match_reason": business_match_reason,
        "template_class": template_class,
        "total_wall_time_sec": round(total_wall_time_sec, 6),
        "counts": dict(counts),
        "stage_timings": list(stage_timings),
    }
    if extra_fields:
        perf_doc.update(extra_fields)
    return perf_doc


def build_stage3_success_output_bundle(
    *,
    run_id: str,
    business_match_class: str,
    business_match_reason: str | None,
    template_class: str,
    mainnodeid: str,
    representative_node_id: str,
    representative_kind: Any | None,
    representative_has_evd: Any | None,
    representative_is_anchor: Any | None,
    resolved_kind: Any | None,
    kind_source: str | None,
    kind_2: int | None,
    grade_2: int | None,
    counts: Mapping[str, Any],
    review_mode: bool,
    risks: list[str],
    patch: Mapping[str, Any],
    selected_positive_rc_groups: list[str],
    excluded_negative_rc_groups: list[str],
    single_sided_unrelated_opposite_lane_trim_applied: bool,
    soft_excluded_rc_corridor_trim_applied: bool,
    late_cleanup_flags: Mapping[str, bool],
    post_trim_non_target_tail_length_m: float,
    foreign_overlap_zero_but_tail_present: bool,
    review_metadata: Stage3ReviewMetadata,
    official_review_decision: Stage3OfficialReviewDecision,
    audit_envelope: LegacyStage3AuditEnvelope,
    virtual_polygon_path: Path,
    branch_evidence_json_path: Path | None,
    branch_evidence_geojson_path: Path | None,
    associated_rcsdroad_path: Path | None,
    associated_rcsdnode_path: Path | None,
    audit_csv_path: Path | None,
    audit_json_path: Path | None,
    rendered_map_path: Path | None,
    total_wall_time_sec: float,
    stage_timings: Any,
    perf_extra_fields: Mapping[str, Any] | None = None,
) -> Stage3SuccessOutputBundle:
    output_files = build_stage3_output_files_payload(
        virtual_polygon_path=virtual_polygon_path,
        branch_evidence_json_path=branch_evidence_json_path,
        branch_evidence_geojson_path=branch_evidence_geojson_path,
        associated_rcsdroad_path=associated_rcsdroad_path,
        associated_rcsdnode_path=associated_rcsdnode_path,
        audit_csv_path=audit_csv_path,
        audit_json_path=audit_json_path,
        rendered_map_path=rendered_map_path,
    )
    canonical_step7_result = audit_envelope.audit_record.step7
    status_doc = build_stage3_success_status_doc(
        run_id=run_id,
        business_match_class=business_match_class,
        business_match_reason=business_match_reason,
        template_class=template_class,
        mainnodeid=mainnodeid,
        representative_node_id=representative_node_id,
        representative_kind=representative_kind,
        representative_has_evd=representative_has_evd,
        representative_is_anchor=representative_is_anchor,
        resolved_kind=resolved_kind,
        kind_source=kind_source,
        kind_2=kind_2,
        grade_2=grade_2,
        counts=counts,
        review_mode=review_mode,
        risks=risks,
        patch=patch,
        selected_positive_rc_groups=selected_positive_rc_groups,
        excluded_negative_rc_groups=excluded_negative_rc_groups,
        single_sided_unrelated_opposite_lane_trim_applied=single_sided_unrelated_opposite_lane_trim_applied,
        soft_excluded_rc_corridor_trim_applied=soft_excluded_rc_corridor_trim_applied,
        late_cleanup_flags=late_cleanup_flags,
        post_trim_non_target_tail_length_m=post_trim_non_target_tail_length_m,
        foreign_overlap_zero_but_tail_present=foreign_overlap_zero_but_tail_present,
        review_metadata=review_metadata,
        official_review_decision=official_review_decision,
        audit_envelope=audit_envelope,
        output_files=output_files,
    )
    perf_doc = build_stage3_perf_doc(
        run_id=run_id,
        success=canonical_step7_result.success,
        flow_success=True,
        business_outcome_class=canonical_step7_result.business_outcome_class,
        acceptance_class=canonical_step7_result.acceptance_class,
        acceptance_reason=canonical_step7_result.acceptance_reason,
        business_match_class=business_match_class,
        business_match_reason=business_match_reason,
        template_class=template_class,
        total_wall_time_sec=total_wall_time_sec,
        counts=counts,
        stage_timings=stage_timings,
        extra_fields=perf_extra_fields,
    )
    return Stage3SuccessOutputBundle(
        output_files=output_files,
        status_doc=status_doc,
        perf_doc=perf_doc,
    )


def build_stage3_failure_output_bundle(
    *,
    run_id: str,
    mainnodeid: str,
    detail: str,
    counts: Mapping[str, Any],
    review_mode: bool,
    business_match_class: str,
    business_match_reason: str,
    representative_node_id: str | None,
    representative_kind: Any | None,
    representative_has_evd: Any | None,
    representative_is_anchor: Any | None,
    kind_2: int | None,
    grade_2: int | None,
    audit_envelope: LegacyStage3AuditEnvelope,
    virtual_polygon_path: Path,
    rendered_map_path: Path | None,
    template_class: str,
    total_wall_time_sec: float,
    stage_timings: Any,
    perf_extra_fields: Mapping[str, Any] | None = None,
) -> Stage3FailureOutputBundle:
    output_files = build_stage3_output_files_payload(
        virtual_polygon_path=virtual_polygon_path,
        rendered_map_path=rendered_map_path,
    )
    canonical_step7_result = audit_envelope.audit_record.step7
    status_doc = build_stage3_failure_status_doc(
        run_id=run_id,
        mainnodeid=mainnodeid,
        detail=detail,
        counts=counts,
        review_mode=review_mode,
        business_match_class=business_match_class,
        business_match_reason=business_match_reason,
        representative_node_id=representative_node_id,
        representative_kind=representative_kind,
        representative_has_evd=representative_has_evd,
        representative_is_anchor=representative_is_anchor,
        kind_2=kind_2,
        grade_2=grade_2,
        audit_envelope=audit_envelope,
        output_files=output_files,
    )
    perf_doc = build_stage3_perf_doc(
        run_id=run_id,
        success=canonical_step7_result.success,
        flow_success=False,
        business_outcome_class=canonical_step7_result.business_outcome_class,
        acceptance_class=canonical_step7_result.acceptance_class,
        acceptance_reason=canonical_step7_result.acceptance_reason,
        business_match_class=business_match_class,
        business_match_reason=business_match_reason,
        template_class=template_class,
        total_wall_time_sec=total_wall_time_sec,
        counts=counts,
        stage_timings=stage_timings,
        extra_fields=perf_extra_fields,
    )
    return Stage3FailureOutputBundle(
        output_files=output_files,
        status_doc=status_doc,
        perf_doc=perf_doc,
    )
