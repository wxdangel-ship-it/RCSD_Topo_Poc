from __future__ import annotations

from dataclasses import replace
from typing import Any

from .case_models import T04CaseResult, T04EventUnitResult
from .step4_road_surface_fork_binding_cleanup import (
    _clear_unbound_surface_candidate,
    _retain_structure_only_surface_candidate,
)
from .step4_road_surface_fork_binding_divstrip import _restore_divstrip_primary_for_wide_surface_fork
from .step4_road_surface_fork_binding_forward import _bind_strong_rcsd_to_surface
from .step4_road_surface_fork_binding_promotions import (
    _promote_selected_surface_partial_rcsd,
    _promote_selected_surface_rcsd_junction_window,
)
from .step4_road_surface_fork_binding_recovery import _recover_surface_from_candidate
from .step4_road_surface_fork_geometry import _dedupe


def _replace_unit(case_result: T04CaseResult, unit_id: str, replacement: T04EventUnitResult) -> T04CaseResult:
    units = [replacement if unit.spec.event_unit_id == unit_id else unit for unit in case_result.event_units]
    state = "STEP4_OK"
    if any(unit.review_state == "STEP4_FAIL" for unit in units):
        state = "STEP4_FAIL"
    elif any(unit.review_state == "STEP4_REVIEW" for unit in units):
        state = "STEP4_REVIEW"
    reasons = _dedupe(reason for unit in units for reason in unit.all_review_reasons())
    return replace(case_result, event_units=units, case_review_state=state, case_review_reasons=reasons)

def _base_record(case_result: T04CaseResult, event_unit: T04EventUnitResult) -> dict[str, Any]:
    return {
        "case_id": case_result.case_spec.case_id,
        "unit_id": event_unit.spec.event_unit_id,
        "pre_state": event_unit.selected_evidence_state,
        "post_state": event_unit.selected_evidence_state,
        "pre_evidence_source": event_unit.evidence_source,
        "post_evidence_source": event_unit.evidence_source,
        "action": "skipped",
        "skip_reason": None,
        "required_rcsd_node": event_unit.required_rcsd_node,
        "positive_rcsd_consistency_level": event_unit.positive_rcsd_consistency_level,
    }

def apply_road_surface_fork_binding(
    case_results: list[T04CaseResult],
) -> tuple[list[T04CaseResult], dict[str, Any]]:
    updated_results = list(case_results)
    records: list[dict[str, Any]] = []
    applied_count = 0
    skipped_count = 0
    for case_index, case_result in enumerate(updated_results):
        current_case = case_result
        for event_unit in list(current_case.event_units):
            record = _base_record(current_case, event_unit)
            replacement, detail = _bind_strong_rcsd_to_surface(current_case, event_unit)
            if replacement is None:
                replacement, detail = _promote_selected_surface_rcsd_junction_window(
                    current_case,
                    event_unit,
                )
            if replacement is None:
                replacement, detail = _promote_selected_surface_partial_rcsd(current_case, event_unit)
            if replacement is None:
                replacement, detail = _recover_surface_from_candidate(current_case, event_unit)
            if replacement is None:
                replacement, detail = _retain_structure_only_surface_candidate(event_unit)
            if replacement is None:
                replacement, detail = _clear_unbound_surface_candidate(event_unit)
            if replacement is None:
                skipped_count += 1
                record["skip_reason"] = "skipped_no_surface_binding_candidate"
                records.append(record)
                continue
            divstrip_replacement, divstrip_detail = _restore_divstrip_primary_for_wide_surface_fork(
                current_case,
                event_unit,
                replacement,
                detail,
            )
            if divstrip_replacement is not None:
                replacement = divstrip_replacement
                detail = divstrip_detail
            applied_count += 1
            current_case = _replace_unit(current_case, event_unit.spec.event_unit_id, replacement)
            record.update(
                {
                    "post_state": replacement.selected_evidence_state,
                    "post_evidence_source": replacement.evidence_source,
                    "action": str(detail.get("action") if detail else "road_surface_fork_binding"),
                    "skip_reason": None,
                    "required_rcsd_node": replacement.required_rcsd_node,
                    "positive_rcsd_consistency_level": replacement.positive_rcsd_consistency_level,
                    "detail": dict(detail or {}),
                }
            )
            records.append(record)
        updated_results[case_index] = current_case
    return updated_results, {
        "scope": "t04_step4_road_surface_fork_binding",
        "applied_count": applied_count,
        "skipped_count": skipped_count,
        "records": records,
    }


__all__ = ["apply_road_surface_fork_binding"]
