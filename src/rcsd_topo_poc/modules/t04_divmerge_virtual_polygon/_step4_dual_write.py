from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable

from ._step4_arbiter_models import T04Step4Candidate, T04Step4CandidateLedger
from .case_models import T04EventUnitResult
from .rcsd_alignment import RCSD_ALIGNMENT_NONE


DEFAULT_FINAL_FIELDS_WRITTEN: tuple[str, ...] = (
    "selected_rcsdroad_ids",
    "selected_rcsdnode_ids",
    "required_rcsd_node",
    "required_rcsd_node_source",
    "positive_rcsd_present",
    "positive_rcsd_present_reason",
    "positive_rcsd_support_level",
    "positive_rcsd_consistency_level",
    "rcsd_alignment_type",
    "rcsd_selection_mode",
    "selected_evidence_summary",
    "selected_candidate_summary",
    "fact_reference_point",
    "review_materialized_point",
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _clean_tuple(values: Iterable[Any] | None) -> tuple[str, ...]:
    if not values:
        return ()
    result: list[str] = []
    for value in values:
        text = _clean_text(value)
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _main_evidence_type(event_unit: T04EventUnitResult) -> str:
    summary = dict(event_unit.selected_evidence_summary or event_unit.selected_candidate_summary or {})
    upper_kind = _clean_text(summary.get("upper_evidence_kind"))
    if upper_kind:
        return upper_kind
    candidate_scope = _clean_text(summary.get("candidate_scope"))
    if candidate_scope:
        return candidate_scope
    return _clean_text(event_unit.evidence_source) or "none"


def _candidate_base_id(event_unit: T04EventUnitResult, source_stage: str, candidate_id: str | None) -> str:
    if candidate_id:
        return _clean_text(candidate_id)
    summary = dict(event_unit.selected_evidence_summary or event_unit.selected_candidate_summary or {})
    summary_id = _clean_text(summary.get("candidate_id"))
    if summary_id:
        return summary_id
    return f"{event_unit.spec.event_unit_id}:{source_stage}"


def _source_audit_blob(event_unit: T04EventUnitResult, source_audit_blob: dict[str, Any] | None) -> dict[str, Any]:
    return {
        **dict(source_audit_blob or {}),
        "unit_snapshot": {
            "event_unit_id": event_unit.spec.event_unit_id,
            "selected_evidence_state": event_unit.selected_evidence_state,
            "evidence_source": event_unit.evidence_source,
            "position_source": event_unit.position_source,
            "positive_rcsd_present": event_unit.positive_rcsd_present,
            "required_rcsd_node": event_unit.required_rcsd_node,
            "rcsd_alignment_type": event_unit.rcsd_alignment_type,
            "rcsd_selection_mode": event_unit.rcsd_selection_mode,
            "selected_rcsdroad_ids": list(event_unit.selected_rcsdroad_ids),
            "selected_rcsdnode_ids": list(event_unit.selected_rcsdnode_ids),
            "selected_evidence_summary": dict(event_unit.selected_evidence_summary),
            "selected_candidate_summary": dict(event_unit.selected_candidate_summary),
        },
    }


def _caller_manifest_record(
    *,
    source_stage: str,
    ledger_candidate_id: str,
    unit_candidate_id: str,
    fields_written: tuple[str, ...],
) -> dict[str, Any]:
    frame = inspect.currentframe()
    caller = frame.f_back.f_back if frame is not None and frame.f_back is not None else None
    return {
        "file": "" if caller is None else Path(caller.f_code.co_filename).name,
        "line": 0 if caller is None else int(caller.f_lineno),
        "function": "" if caller is None else caller.f_code.co_name,
        "source_stage": source_stage,
        "candidate_id": ledger_candidate_id,
        "unit_candidate_id": unit_candidate_id,
        "fields_written": list(fields_written),
    }


def append_dual_write_candidate(
    event_unit: T04EventUnitResult,
    *,
    case_id: str,
    source_stage: str,
    fields_written: Iterable[str] = DEFAULT_FINAL_FIELDS_WRITTEN,
    candidate_id: str | None = None,
    source_audit_blob: dict[str, Any] | None = None,
    replacement_reason: str = "",
    reject_reason: str = "",
    conflict_flags: Iterable[str] | None = None,
) -> T04EventUnitResult:
    source_stage = _clean_text(source_stage)
    unit_candidate_id = _candidate_base_id(event_unit, source_stage, candidate_id)
    ledger = event_unit.step4_candidate_ledger or T04Step4CandidateLedger(
        unit_id=event_unit.spec.event_unit_id,
        case_id=case_id,
    )
    ledger_candidate_id = f"{unit_candidate_id}:{source_stage}:{len(ledger.candidates) + 1:02d}"
    written = _clean_tuple(fields_written) or DEFAULT_FINAL_FIELDS_WRITTEN
    candidate = T04Step4Candidate(
        candidate_id=ledger_candidate_id,
        source_stage=source_stage,
        evidence_type=_clean_text(event_unit.evidence_source),
        main_evidence_type=_main_evidence_type(event_unit),
        reference_point=event_unit.fact_reference_point,
        rcsd_alignment_type=_clean_text(event_unit.rcsd_alignment_type) or RCSD_ALIGNMENT_NONE,
        rcsdroad_ids=event_unit.selected_rcsdroad_ids,
        rcsdnode_ids=event_unit.selected_rcsdnode_ids,
        required_rcsd_node=event_unit.required_rcsd_node,
        support_level=event_unit.positive_rcsd_support_level,
        consistency_level=event_unit.positive_rcsd_consistency_level,
        conflict_flags=_clean_tuple(conflict_flags),
        reject_reason=reject_reason,
        replacement_reason=replacement_reason,
        source_audit_blob=_source_audit_blob(event_unit, source_audit_blob),
    )
    return replace(
        event_unit,
        step4_candidate_ledger=ledger.append(candidate),
        dual_write_manifest=(
            *event_unit.dual_write_manifest,
            _caller_manifest_record(
                source_stage=source_stage,
                ledger_candidate_id=ledger_candidate_id,
                unit_candidate_id=unit_candidate_id,
                fields_written=written,
            ),
        ),
    )


__all__ = ["DEFAULT_FINAL_FIELDS_WRITTEN", "append_dual_write_candidate"]
