from __future__ import annotations

from dataclasses import replace
from typing import Any

from .case_models import T04CandidateAuditEntry, T04EventUnitResult
from .step4_road_surface_fork_geometry import (
    ROAD_SURFACE_FORK_BINDING_REASON,
    ROAD_SURFACE_FORK_SCOPE,
    _as_float,
)
from .step4_road_surface_fork_rcsd import _junction_window_aggregate, _relaxed_primary_aggregate

DIVSTRIP_PRIMARY_WIDE_SURFACE_FORK_BRANCH_SEPARATION_M = 50.0
DIVSTRIP_PRIMARY_REFERENCE_WINDOW_HALF_LENGTH_M = 20.0
DIVSTRIP_PRIMARY_REFERENCE_WINDOW_HALF_WIDTH_M = 20.0
DIVSTRIP_PRIMARY_WIDE_SURFACE_FORK_REASON = "divstrip_primary_over_wide_road_surface_fork"


def _build_surface_summary(
    entry: T04CandidateAuditEntry,
    *,
    evidence_source: str,
    position_source: str,
    bind_detail: dict[str, Any],
) -> dict[str, Any]:
    summary = dict(entry.candidate_summary)
    summary.update(
        {
            "candidate_scope": ROAD_SURFACE_FORK_SCOPE,
            "selected_evidence_state": "found",
            "evidence_source": evidence_source,
            "position_source": position_source,
            "primary_eligible": True,
            "selection_status": "selected",
            "decision_reason": ROAD_SURFACE_FORK_BINDING_REASON,
            "road_surface_fork_binding": dict(bind_detail),
        }
    )
    return summary

def _candidate_entries_with_selection(
    entries: tuple[T04CandidateAuditEntry, ...],
    selected_entry: T04CandidateAuditEntry,
    selected_summary: dict[str, Any],
) -> tuple[T04CandidateAuditEntry, ...]:
    updated: list[T04CandidateAuditEntry] = []
    matched = False
    for entry in entries:
        if entry.candidate_id == selected_entry.candidate_id:
            matched = True
            updated.append(
                replace(
                    selected_entry,
                    selection_status="selected",
                    decision_reason=ROAD_SURFACE_FORK_BINDING_REASON,
                    candidate_summary=dict(selected_summary),
                    evidence_source=str(selected_summary.get("evidence_source") or entry.evidence_source),
                    position_source=str(selected_summary.get("position_source") or entry.position_source),
                    review_state="STEP4_REVIEW",
                    review_reasons=tuple(selected_summary.get("review_reasons") or entry.review_reasons),
                )
            )
        else:
            updated.append(entry)
    if not matched:
        updated.append(
            replace(
                selected_entry,
                selection_status="selected",
                decision_reason=ROAD_SURFACE_FORK_BINDING_REASON,
                candidate_summary=dict(selected_summary),
                evidence_source=str(selected_summary.get("evidence_source") or selected_entry.evidence_source),
                position_source=str(selected_summary.get("position_source") or selected_entry.position_source),
                review_state="STEP4_REVIEW",
                review_reasons=tuple(selected_summary.get("review_reasons") or selected_entry.review_reasons),
            )
        )
    return tuple(updated)

def _invalid_divstrip_removed(event_unit: T04EventUnitResult) -> bool:
    return any(
        entry.candidate_summary.get("degraded_reverse_divstrip_far_from_throat") is True
        for entry in event_unit.candidate_audit_entries
    )

def _degraded_divstrip_entry(event_unit: T04EventUnitResult) -> T04CandidateAuditEntry | None:
    entries: list[tuple[float, int, str, T04CandidateAuditEntry]] = []
    for entry in event_unit.candidate_audit_entries:
        summary = entry.candidate_summary
        if summary.get("degraded_reverse_divstrip_far_from_throat") is not True:
            continue
        if str(summary.get("upper_evidence_kind") or "") != "divstrip":
            continue
        if str(summary.get("candidate_scope") or "") != "divstrip_component":
            continue
        reference_distance = _as_float(summary.get("reference_distance_to_origin_m"))
        entries.append(
            (
                float("inf") if reference_distance is None else float(reference_distance),
                int(entry.pool_rank or 0),
                entry.candidate_id,
                entry,
            )
        )
    entries.sort(key=lambda item: item[:3])
    return entries[0][3] if entries else None

def _has_partial_rcsd_signal(event_unit: T04EventUnitResult) -> bool:
    return any(
        "positive_rcsd_partial_consistent" in str(reason or "")
        for reason in event_unit.all_review_reasons()
    )

def _has_non_semantic_partial_rcsd_signal(event_unit: T04EventUnitResult) -> bool:
    if not _has_partial_rcsd_signal(event_unit):
        return False
    audit = dict(event_unit.positive_rcsd_audit)
    if _junction_window_aggregate(audit) is not None:
        return False
    if _relaxed_primary_aggregate(audit) is not None:
        return False
    return any(
        isinstance(aggregate, dict)
        and str(aggregate.get("decision_reason") or "").strip() == "role_mapping_partial_aggregated"
        for aggregate in audit.get("aggregated_rcsd_units") or ()
    )

def _selected_surface_entry(event_unit: T04EventUnitResult) -> T04CandidateAuditEntry | None:
    if event_unit.selected_evidence_state == "none":
        return None
    if event_unit.evidence_source != "road_surface_fork":
        return None
    selected_id = str(
        event_unit.selected_candidate_summary.get("candidate_id")
        or event_unit.selected_evidence_summary.get("candidate_id")
        or ""
    ).strip()
    if not selected_id:
        return None
    for entry in event_unit.candidate_audit_entries:
        if entry.candidate_id == selected_id:
            return entry
    return None
