from __future__ import annotations

import heapq
from dataclasses import replace
from statistics import median
from typing import Any, Iterable, Sequence

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, nearest_points, unary_union

from .case_models import T04CandidateAuditEntry, T04CaseResult, T04EventUnitResult
from ._step4_dual_write import append_dual_write_candidate
from .event_interpretation_selection import (
    EVENT_REFERENCE_CONFLICT_TOL_M,
    SHARED_EVIDENCE_OVERLAP_AREA_M2,
    SHARED_EVIDENCE_OVERLAP_RATIO,
)

from .step4_rcsd_anchored_reverse_graph import *

def _summary_with_anchor(
    base_summary: dict[str, Any],
    *,
    state: str,
    evidence_source: str,
    position_source: str,
    s_rcsd_anchored: float,
    axis_context: dict[str, Any],
    aggregate_id: str,
    mother: T04CandidateAuditEntry,
    recovered: T04CandidateAuditEntry | None,
) -> dict[str, Any]:
    summary = dict(base_summary)
    if not str(summary.get("candidate_id") or "").strip():
        summary.update(
            {
                "candidate_id": f"{mother.candidate_id}:rcsd_anchored",
                "source_mode": "rcsd_anchored_reverse",
                "upper_evidence_kind": "rcsd_anchor",
                "upper_evidence_object_id": aggregate_id,
                "candidate_scope": "rcsd_anchored_axis_projection",
                "local_region_id": f"{mother.candidate_id}:rcsd_anchored",
                "ownership_signature": f"rcsd_anchor:{aggregate_id}:{mother.candidate_id}",
                "layer": 2,
                "layer_label": "Layer 2",
                "layer_reason": "rcsd_anchored_fallback",
            }
        )
    axis_signature = str(axis_context.get("axis_signature") or axis_context.get("axis_branch_id") or "")
    summary.update(
        {
            "selected_evidence_state": state,
            "evidence_source": evidence_source,
            "position_source": position_source,
            "axis_signature": axis_signature,
            "axis_position_basis": axis_signature,
            "axis_position_m": round(float(s_rcsd_anchored), 3),
            "point_signature": f"{axis_signature}:{round(float(s_rcsd_anchored), 1)}" if axis_signature else "",
            "aggregated_rcsd_unit_id": aggregate_id,
            "positive_rcsd_present": True,
            "positive_rcsd_support_level": mother.positive_rcsd_support_level,
            "positive_rcsd_consistency_level": mother.positive_rcsd_consistency_level,
            "first_hit_rcsdroad_ids": list(mother.first_hit_rcsdroad_ids),
            "required_rcsd_node": mother.required_rcsd_node,
            "required_rcsd_node_source": mother.required_rcsd_node_source,
            "rcsd_anchored_reverse_recovered_evidence": recovered is not None,
        }
    )
    return summary


def _update_interpretation(
    event_unit: T04EventUnitResult,
    *,
    axis_branch_id: str,
    s_rcsd_anchored: float,
    anchor_point: Point | None,
    reference_point: Point | None,
    reference_origin_point: Point | None,
    reference_mode: str,
    fallback_used: bool,
) -> Any:
    interpretation = event_unit.interpretation
    event_reference = replace(
        interpretation.event_reference,
        event_axis_branch_id=axis_branch_id,
        event_origin_source="rcsd_anchored_axis_projection",
        event_position_source="rcsd_anchored_axis_projection",
        event_split_pick_source="rcsd_anchored_reverse",
        event_chosen_s_m=round(float(s_rcsd_anchored), 3),
        raw={
            **dict(interpretation.event_reference.raw),
            "event_axis_branch_id": axis_branch_id,
            "event_origin_source": "rcsd_anchored_axis_projection",
            "position_source": "rcsd_anchored_axis_projection",
            "chosen_s_m": round(float(s_rcsd_anchored), 3),
            "reference_point_mode": reference_mode,
        },
    )
    evidence_decision = replace(
        interpretation.evidence_decision,
        primary_source="rcsd_anchored_reverse",
        selection_mode="rcsd_anchored_reverse",
        fallback_used=fallback_used,
        fallback_mode="rcsd_anchored" if fallback_used else interpretation.evidence_decision.fallback_mode,
        risk_signals=_dedupe([*interpretation.evidence_decision.risk_signals, RCSD_ANCHORED_RISK_SIGNAL]),
    )
    bridge = replace(
        interpretation.legacy_step5_bridge,
        event_axis_branch_id=axis_branch_id,
        event_reference_raw={
            **dict(interpretation.legacy_step5_bridge.event_reference_raw),
            "event_axis_branch_id": axis_branch_id,
            "event_origin_source": "rcsd_anchored_axis_projection",
            "position_source": "rcsd_anchored_axis_projection",
            "chosen_s_m": round(float(s_rcsd_anchored), 3),
            "reference_point_mode": reference_mode,
        },
        event_origin_point=reference_origin_point or anchor_point or interpretation.legacy_step5_bridge.event_origin_point,
        event_origin_source="rcsd_anchored_axis_projection",
    )
    return replace(
        interpretation,
        evidence_decision=evidence_decision,
        event_reference=event_reference,
        legacy_step5_bridge=bridge,
        risk_signals=_dedupe([*interpretation.risk_signals, RCSD_ANCHORED_RISK_SIGNAL]),
    )


def _apply_reverse_to_unit(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    *,
    mother: T04CandidateAuditEntry,
    aggregate_id: str,
    road_ids: set[str],
    node_ids: set[str],
    axis_context: dict[str, Any],
    node_samples_s: list[float],
    road_samples_s: list[float],
) -> tuple[T04EventUnitResult, dict[str, Any]]:
    samples = [*node_samples_s, *road_samples_s]
    s_rcsd_anchored = round(float(median(samples)), 3)
    anchor_point = _axis_point_at_s(axis_context, s_rcsd_anchored)
    reference_point, reference_s, reference_mode = _reverse_reference_point(
        case_result,
        event_unit=event_unit,
        mother=mother,
        road_ids=road_ids,
        axis_context=axis_context,
        s_rcsd_anchored=s_rcsd_anchored,
        anchor_point=anchor_point,
    )
    reference_origin_point = _axis_point_at_s(axis_context, reference_s) or reference_point
    drivezone = _drivezone_union(case_result)
    continuation = _terminal_continuation_expansion(
        case_result,
        event_unit,
        mother=mother,
        axis_context=axis_context,
        drivezone=drivezone,
    )
    selected_rcsdroad_ids = _dedupe([*mother.selected_rcsdroad_ids, *continuation.get("road_ids", [])])
    selected_rcsdnode_ids = _dedupe([*mother.selected_rcsdnode_ids, *continuation.get("node_ids", [])])
    selected_rcsdroad_ids, selected_rcsdnode_ids, prune_detail = _prune_aggregated_node_centric_reverse_roads(
        case_result,
        mother,
        selected_rcsdroad_ids,
        selected_rcsdnode_ids,
    )
    positive_rcsd_road_geometry = _rcsd_road_geometry(case_result, selected_rcsdroad_ids)
    positive_rcsd_node_geometry = _rcsd_node_geometry(case_result, selected_rcsdnode_ids)
    positive_rcsd_geometry = _union_geometry([positive_rcsd_road_geometry, positive_rcsd_node_geometry])
    recovered = _recover_evidence(event_unit.candidate_audit_entries, s_rcsd_anchored=s_rcsd_anchored)
    fallback_used = recovered is None
    if recovered is None:
        evidence_patch = _clip_to_drivezone(
            None if anchor_point is None else anchor_point.buffer(RCSD_ANCHORED_FALLBACK_PATCH_RADIUS_M, join_style=2),
            drivezone,
        )
        component_geometry = evidence_patch
        core_geometry = evidence_patch
        evidence_region_geometry = evidence_patch
        base_summary: dict[str, Any] = {}
        post_state = "rcsd_anchored"
    else:
        component_geometry = recovered.selected_component_union_geometry or recovered.candidate_region_geometry
        core_geometry = recovered.localized_evidence_core_geometry or recovered.candidate_region_geometry
        evidence_region_geometry = recovered.selected_evidence_region_geometry or recovered.candidate_region_geometry
        base_summary = dict(recovered.candidate_summary)
        post_state = "found"

    summary = _summary_with_anchor(
        base_summary,
        state=post_state,
        evidence_source="rcsd_anchored_reverse",
        position_source="rcsd_anchored_axis_projection",
        s_rcsd_anchored=s_rcsd_anchored,
        axis_context=axis_context,
        aggregate_id=aggregate_id,
        mother=mother,
        recovered=recovered,
    )
    summary.update(
        {
            "selected_rcsdroad_ids": list(selected_rcsdroad_ids),
            "selected_rcsdnode_ids": list(selected_rcsdnode_ids),
            "terminal_continuation_expansion": continuation,
            "rcsd_anchored_reverse_prune": prune_detail,
        }
    )
    updated_interpretation = _update_interpretation(
        event_unit,
        axis_branch_id=str(axis_context["axis_branch_id"]),
        s_rcsd_anchored=s_rcsd_anchored,
        anchor_point=anchor_point,
        reference_point=reference_point,
        reference_origin_point=reference_origin_point,
        reference_mode=reference_mode,
        fallback_used=fallback_used,
    )
    review_reasons = _dedupe(
        [
            reason
            for reason in event_unit.all_review_reasons()
            if str(reason) not in _EVIDENCE_MISSING_REASONS
        ]
        + [RCSD_ANCHORED_REVIEW_REASON]
    )
    updated_positive_audit = {
        **dict(mother.positive_rcsd_audit),
        "published_rcsdroad_ids": list(selected_rcsdroad_ids),
        "published_rcsdnode_ids": list(selected_rcsdnode_ids),
        "terminal_continuation_expansion": continuation,
        "rcsd_anchored_reverse_prune": prune_detail,
        "rcsd_anchored_reverse": {
            "used": True,
            "s_rcsd_anchored": s_rcsd_anchored,
            "sample_count": len(samples),
            "evidence_recovered": recovered is not None,
            "recovered_candidate_id": None if recovered is None else recovered.candidate_id,
            "reference_point_mode": reference_mode,
            "reference_point_axis_s": round(float(reference_s), 3),
            "terminal_continuation_expansion": continuation,
            "prune": prune_detail,
        },
    }
    updated = replace(
        event_unit,
        interpretation=updated_interpretation,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        extra_review_notes=(),
        evidence_source="rcsd_anchored_reverse",
        position_source="rcsd_anchored_axis_projection",
        reverse_tip_used=False,
        rcsd_consistency_result=mother.rcsd_consistency_result,
        selected_component_union_geometry=component_geometry,
        localized_evidence_core_geometry=core_geometry,
        coarse_anchor_zone_geometry=_clip_to_drivezone(
            None if anchor_point is None else anchor_point.buffer(max(RCSD_ANCHORED_FALLBACK_PATCH_RADIUS_M, 6.0), join_style=2),
            drivezone,
        ),
        selected_evidence_region_geometry=evidence_region_geometry,
        fact_reference_point=reference_point,
        review_materialized_point=reference_point,
        pair_local_rcsd_scope_geometry=mother.pair_local_rcsd_scope_geometry,
        first_hit_rcsd_road_geometry=mother.first_hit_rcsd_road_geometry,
        local_rcsd_unit_geometry=mother.local_rcsd_unit_geometry,
        positive_rcsd_geometry=positive_rcsd_geometry,
        positive_rcsd_road_geometry=positive_rcsd_road_geometry,
        positive_rcsd_node_geometry=positive_rcsd_node_geometry,
        primary_main_rc_node_geometry=mother.primary_main_rc_node_geometry,
        required_rcsd_node_geometry=mother.required_rcsd_node_geometry,
        selected_branch_ids=mother.selected_branch_ids,
        selected_event_branch_ids=mother.selected_event_branch_ids,
        selected_component_ids=mother.selected_component_ids,
        pair_local_rcsd_road_ids=mother.pair_local_rcsd_road_ids,
        pair_local_rcsd_node_ids=mother.pair_local_rcsd_node_ids,
        first_hit_rcsdroad_ids=mother.first_hit_rcsdroad_ids,
        selected_rcsdroad_ids=selected_rcsdroad_ids,
        selected_rcsdnode_ids=selected_rcsdnode_ids,
        primary_main_rc_node_id=mother.primary_main_rc_node_id,
        local_rcsd_unit_id=mother.local_rcsd_unit_id,
        local_rcsd_unit_kind=mother.local_rcsd_unit_kind,
        aggregated_rcsd_unit_id=aggregate_id,
        aggregated_rcsd_unit_ids=mother.aggregated_rcsd_unit_ids,
        positive_rcsd_present=True,
        positive_rcsd_present_reason=mother.positive_rcsd_present_reason,
        axis_polarity_inverted=mother.axis_polarity_inverted,
        rcsd_selection_mode=f"rcsd_anchored_reverse:{mother.rcsd_selection_mode}",
        pair_local_rcsd_empty=False,
        positive_rcsd_support_level=mother.positive_rcsd_support_level,
        positive_rcsd_consistency_level=mother.positive_rcsd_consistency_level,
        required_rcsd_node=mother.required_rcsd_node,
        required_rcsd_node_source=mother.required_rcsd_node_source,
        event_axis_branch_id=str(axis_context["axis_branch_id"]),
        event_chosen_s_m=s_rcsd_anchored,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_positive_audit,
        conflict_resolution_action="rcsd_anchored_reverse",
        post_resolution_candidate_id=str(summary.get("candidate_id") or ""),
        post_required_rcsd_node=str(mother.required_rcsd_node or ""),
        resolution_reason=RCSD_ANCHORED_REVIEW_REASON,
    )
    detail = {
        "s_rcsd_anchored": s_rcsd_anchored,
        "evidence_recovered": recovered is not None,
        "recovered_candidate_id": None if recovered is None else recovered.candidate_id,
        "post_selected_evidence_state": updated.selected_evidence_state,
        "reference_point_mode": reference_mode,
        "reference_point_axis_s": round(float(reference_s), 3),
        "terminal_continuation_expansion": continuation,
    }
    return (
        append_dual_write_candidate(
            updated,
            case_id=case_result.case_spec.case_id,
            source_stage="anchored_reverse",
            source_audit_blob=detail,
            replacement_reason=RCSD_ANCHORED_REVIEW_REASON,
        ),
        detail,
    )


def _record_base(case_result: T04CaseResult, event_unit: T04EventUnitResult) -> dict[str, Any]:
    return {
        "case_id": case_result.case_spec.case_id,
        "unit_id": event_unit.spec.event_unit_id,
        "mother_candidate_id": None,
        "mother_candidate_node_fallback_only": None,
        "mother_candidate_pool_rank": None,
        "mother_axis_position_m": None,
        "axis_branch_id": None,
        "node_samples_s": [],
        "road_samples_s": [],
        "sample_count": 0,
        "sample_kind_counts": {"node": 0, "road": 0},
        "aggregated_rcsd_unit_id": None,
        "pre_state": event_unit.selected_evidence_state,
        "post_state": event_unit.selected_evidence_state,
        "skip_reason": None,
    }


def _replace_unit(case_result: T04CaseResult, unit_id: str, replacement: T04EventUnitResult) -> T04CaseResult:
    units = [replacement if unit.spec.event_unit_id == unit_id else unit for unit in case_result.event_units]
    state = "STEP4_OK"
    if any(unit.review_state == "STEP4_FAIL" for unit in units):
        state = "STEP4_FAIL"
    elif any(unit.review_state == "STEP4_REVIEW" for unit in units):
        state = "STEP4_REVIEW"
    reasons = _dedupe(reason for unit in units for reason in unit.all_review_reasons())
    return replace(case_result, event_units=units, case_review_state=state, case_review_reasons=reasons)


def _find_unit(case_result: T04CaseResult, unit_id: str) -> T04EventUnitResult:
    for unit in case_result.event_units:
        if unit.spec.event_unit_id == unit_id:
            return unit
    raise KeyError(unit_id)


def _post_conflict_recheck(
    case_results: list[T04CaseResult],
    records: list[dict[str, Any]],
    originals: dict[tuple[str, str], T04EventUnitResult],
) -> list[T04CaseResult]:
    case_by_id = {case.case_spec.case_id: case for case in case_results}
    for record in records:
        original_key = (str(record["case_id"]), str(record["unit_id"]))
        if original_key not in originals or record.get("post_state") not in {"found", "rcsd_anchored"}:
            continue
        case_id = str(record["case_id"])
        unit_id = str(record["unit_id"])
        current = _find_unit(case_by_id[case_id], unit_id)
        conflict_detail = None
        current_summary = current.selected_evidence_summary
        for other_case in case_results:
            for other in other_case.event_units:
                if other_case.case_spec.case_id == case_id and other.spec.event_unit_id == unit_id:
                    continue
                if other_case.case_spec.case_id == case_id:
                    continue
                if _rcsd_claim_conflicts(
                    current,
                    other,
                    aggregate_id=str(current.aggregated_rcsd_unit_id or ""),
                    road_ids=set(current.selected_rcsdroad_ids),
                    node_ids=set(current.selected_rcsdnode_ids),
                    same_case=False,
                ):
                    conflict_detail = {
                        "scope": "cross_case_rcsd_claim",
                        "other_case_id": other_case.case_spec.case_id,
                        "other_unit_id": other.spec.event_unit_id,
                    }
                    break
                if _evidence_conflicts(
                    other,
                    summary=current_summary,
                    component_geometry=current.selected_component_union_geometry,
                    core_geometry=current.localized_evidence_core_geometry,
                    same_case=False,
                ):
                    conflict_detail = {
                        "scope": "cross_case_evidence",
                        "other_case_id": other_case.case_spec.case_id,
                        "other_unit_id": other.spec.event_unit_id,
                    }
                    break
            if conflict_detail is not None:
                break
        if conflict_detail is None:
            record["post_reverse_conflict_recheck"] = "passed"
            continue
        original = originals[(case_id, unit_id)]
        case_by_id[case_id] = _replace_unit(case_by_id[case_id], unit_id, original)
        record["post_reverse_conflict_recheck"] = "failed"
        record["post_reverse_conflict_detail"] = conflict_detail
        record["skip_reason"] = "skipped_post_reverse_conflict_recheck"
        record["post_state"] = original.selected_evidence_state
    return [case_by_id[case.case_spec.case_id] for case in case_results]


def apply_rcsd_anchored_reverse_lookup(
    case_results: list[T04CaseResult],
) -> tuple[list[T04CaseResult], dict[str, Any]]:
    updated_cases: list[T04CaseResult] = []
    records: list[dict[str, Any]] = []
    originals: dict[tuple[str, str], T04EventUnitResult] = {}

    for case_result in case_results:
        updated_case = case_result
        for event_unit in case_result.event_units:
            record = _record_base(case_result, event_unit)
            records.append(record)
            if event_unit.selected_evidence_state != "none":
                record["skip_reason"] = "skipped_selected_evidence_present"
                continue
            mother_candidates = _rank_mother_candidates(event_unit.candidate_audit_entries)
            if not mother_candidates:
                record["skip_reason"] = "skipped_missing_aggregated_rcsd_unit"
                continue
            axis = _axis_context(case_result, event_unit)
            if not axis.get("axis_branch_id") or axis.get("axis_line") is None:
                record["skip_reason"] = "skipped_missing_axis_branch"
                continue
            mother = mother_candidates[0]
            aggregate_id, road_ids, node_ids = _cluster_ids(mother)
            record.update(
                {
                    "mother_candidate_id": mother.candidate_id,
                    "mother_candidate_node_fallback_only": bool(mother.candidate_summary.get("node_fallback_only")),
                    "mother_candidate_pool_rank": mother.pool_rank,
                    "mother_axis_position_m": _candidate_axis_position(mother),
                    "axis_branch_id": axis.get("axis_branch_id"),
                    "aggregated_rcsd_unit_id": aggregate_id,
                    "reverse_search_domain": {
                        "domain_type": "axis_driven_reverse_search_domain",
                        "event_type": event_unit.spec.event_type,
                        "axis_branch_id": axis.get("axis_branch_id"),
                        "unit_population_node_ids": list(event_unit.unit_envelope.unit_population_node_ids),
                        "step2_local_rcsdroad_count": len(case_result.case_bundle.rcsd_roads),
                        "step2_local_rcsdnode_count": len(case_result.case_bundle.rcsd_nodes),
                    },
                }
            )
            if not aggregate_id:
                record["skip_reason"] = "skipped_missing_aggregated_rcsd_unit"
                continue
            same_case_rcsd_conflict = any(
                _rcsd_claim_conflicts(
                    event_unit,
                    other,
                    aggregate_id=aggregate_id,
                    road_ids=road_ids,
                    node_ids=node_ids,
                    same_case=True,
                )
                for other in updated_case.event_units
                if other.spec.event_unit_id != event_unit.spec.event_unit_id
            )
            if same_case_rcsd_conflict:
                record["skip_reason"] = "skipped_same_case_rcsd_claim_conflict"
                continue
            node_samples, road_samples = _rcsd_anchor_samples(
                case_result,
                road_ids=road_ids,
                node_ids=node_ids,
                axis_context=axis,
            )
            sample_count = len(node_samples) + len(road_samples)
            record.update(
                {
                    "node_samples_s": node_samples,
                    "road_samples_s": road_samples,
                    "sample_count": sample_count,
                    "sample_kind_counts": {"node": len(node_samples), "road": len(road_samples)},
                }
            )
            if sample_count < MIN_RCSD_ANCHOR_SAMPLE_COUNT:
                record["skip_reason"] = "skipped_insufficient_rcsd_samples"
                continue
            updated_unit, detail = _apply_reverse_to_unit(
                case_result,
                event_unit,
                mother=mother,
                aggregate_id=aggregate_id,
                road_ids=road_ids,
                node_ids=node_ids,
                axis_context=axis,
                node_samples_s=node_samples,
                road_samples_s=road_samples,
            )
            same_case_evidence_conflict = any(
                _evidence_conflicts(
                    other,
                    summary=updated_unit.selected_evidence_summary,
                    component_geometry=updated_unit.selected_component_union_geometry,
                    core_geometry=updated_unit.localized_evidence_core_geometry,
                    same_case=True,
                )
                for other in updated_case.event_units
                if other.spec.event_unit_id != updated_unit.spec.event_unit_id
            )
            if same_case_evidence_conflict:
                record["skip_reason"] = "skipped_same_case_evidence_conflict"
                continue
            originals[(case_result.case_spec.case_id, event_unit.spec.event_unit_id)] = event_unit
            updated_case = _replace_unit(updated_case, event_unit.spec.event_unit_id, updated_unit)
            record.update(detail)
            record["post_state"] = updated_unit.selected_evidence_state
            record["skip_reason"] = None
        updated_cases.append(updated_case)

    updated_cases = _post_conflict_recheck(updated_cases, records, originals)
    applied_records = [item for item in records if item.get("skip_reason") is None and item.get("post_state") != item.get("pre_state")]
    return (
        updated_cases,
        {
            "scope": "t04_step4_rcsd_anchored_reverse",
            "triggered_count": len(applied_records),
            "skipped_count": len(records) - len(applied_records),
            "records": records,
        },
    )


__all__ = ["apply_rcsd_anchored_reverse_lookup"]
