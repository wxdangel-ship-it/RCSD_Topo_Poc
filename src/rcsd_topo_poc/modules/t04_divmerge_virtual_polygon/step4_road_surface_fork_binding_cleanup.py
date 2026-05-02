from __future__ import annotations

from dataclasses import replace
from typing import Any

from .case_models import T04EventUnitResult
from .step4_road_surface_fork_binding_shared import (
    _candidate_entries_with_selection,
    _has_non_semantic_partial_rcsd_signal,
    _has_partial_rcsd_signal,
    _selected_surface_entry,
)
from .step4_road_surface_fork_geometry import (
    JUNCTION_WINDOW_HALF_LENGTH_M,
    ROAD_SURFACE_FORK_SCOPE,
    STRUCTURE_ONLY_SURFACE_MIN_AXIS_POSITION_M,
    STRUCTURE_ONLY_SURFACE_MIN_PAIR_MIDDLE_RATIO,
    STRUCTURE_ONLY_SURFACE_REASON,
    SURFACE_RECOVERY_MIN_THROAT_RATIO,
    SWSD_JUNCTION_WINDOW_POSITION_SOURCE,
    SWSD_JUNCTION_WINDOW_REASON,
    SWSD_JUNCTION_WINDOW_SOURCE,
    UNBOUND_ROAD_SURFACE_FORK_REASON,
    _as_float,
    _dedupe,
)
from .step4_road_surface_fork_rcsd import _weak_structure_surface_window_candidate


def _stable_structure_only_surface_summary(summary: dict[str, Any]) -> bool:
    if str(summary.get("candidate_scope") or "") != ROAD_SURFACE_FORK_SCOPE:
        return False
    if not bool(summary.get("primary_eligible")):
        return False
    if bool(summary.get("node_fallback_only")):
        return False
    axis_position = abs(_as_float(summary.get("axis_position_m")) or 0.0)
    if axis_position < STRUCTURE_ONLY_SURFACE_MIN_AXIS_POSITION_M:
        return False
    throat_ratio = _as_float(summary.get("throat_overlap_ratio")) or 0.0
    pair_middle_ratio = _as_float(summary.get("pair_middle_overlap_ratio")) or 0.0
    return (
        throat_ratio >= SURFACE_RECOVERY_MIN_THROAT_RATIO
        and pair_middle_ratio >= STRUCTURE_ONLY_SURFACE_MIN_PAIR_MIDDLE_RATIO
    )

def _retain_structure_only_surface_candidate(
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    if event_unit.selected_evidence_state == "none":
        return None, None
    if event_unit.evidence_source != "road_surface_fork":
        return None, None
    if event_unit.required_rcsd_node:
        return None, None
    non_semantic_partial_rcsd = _has_non_semantic_partial_rcsd_signal(event_unit)
    if event_unit.positive_rcsd_present and not non_semantic_partial_rcsd:
        return None, None
    if _has_partial_rcsd_signal(event_unit) and not non_semantic_partial_rcsd:
        return None, None
    selected_summary = dict(event_unit.selected_evidence_summary or event_unit.selected_candidate_summary or {})
    if selected_summary.get("road_surface_fork_binding"):
        return None, None
    if not _stable_structure_only_surface_summary(selected_summary):
        return None, None
    entry = _selected_surface_entry(event_unit)
    if entry is None:
        return None, None

    use_swsd_window = _weak_structure_surface_window_candidate(selected_summary) or non_semantic_partial_rcsd
    evidence_source = SWSD_JUNCTION_WINDOW_SOURCE if use_swsd_window else "road_surface_fork"
    position_source = (
        SWSD_JUNCTION_WINDOW_POSITION_SOURCE
        if use_swsd_window
        else str(event_unit.position_source or "road_surface_fork")
    )
    rcsd_mode = (
        "swsd_junction_window_no_rcsd"
        if use_swsd_window
        else "road_surface_fork_structure_only_no_rcsd"
    )
    reason = SWSD_JUNCTION_WINDOW_REASON if use_swsd_window else STRUCTURE_ONLY_SURFACE_REASON
    detail = {
        "action": (
            "kept_swsd_junction_window_no_rcsd"
            if use_swsd_window
            else "kept_structure_only_road_surface_fork"
        ),
        "reason": reason,
        "candidate_id": entry.candidate_id,
        "axis_position_m": _as_float(selected_summary.get("axis_position_m")),
        "pair_middle_overlap_ratio": _as_float(selected_summary.get("pair_middle_overlap_ratio")),
        "throat_overlap_ratio": _as_float(selected_summary.get("throat_overlap_ratio")),
        "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M if use_swsd_window else None,
    }
    review_reasons = _dedupe([*event_unit.all_review_reasons(), reason])
    summary = dict(selected_summary)
    summary.update(
        {
            "review_reasons": list(review_reasons),
            "road_surface_fork_binding": detail,
            "selected_evidence_state": "found",
            "evidence_source": evidence_source,
            "position_source": position_source,
            "source_mode": evidence_source,
            "rcsd_consistency_result": rcsd_mode,
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": rcsd_mode,
            "positive_rcsd_support_level": "no_support",
            "positive_rcsd_consistency_level": "C",
            "required_rcsd_node": None,
            "required_rcsd_node_source": None,
            "rcsd_selection_mode": rcsd_mode,
            "rcsd_decision_reason": rcsd_mode,
            "decision_reason": reason,
            "selection_status": "selected",
            "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M if use_swsd_window else None,
        }
    )
    updated_entries = _candidate_entries_with_selection(
        event_unit.candidate_audit_entries,
        replace(
            entry,
            candidate_summary=dict(summary),
            review_state="STEP4_REVIEW",
            review_reasons=review_reasons,
            evidence_source=evidence_source,
            position_source=position_source,
            rcsd_consistency_result=rcsd_mode,
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            required_rcsd_node=None,
            positive_rcsd_present=False,
            positive_rcsd_present_reason=rcsd_mode,
            rcsd_selection_mode=rcsd_mode,
            required_rcsd_node_source=None,
            localized_evidence_core_geometry=None if use_swsd_window else entry.localized_evidence_core_geometry,
            selected_component_union_geometry=None if use_swsd_window else entry.selected_component_union_geometry,
            selected_evidence_region_geometry=None if use_swsd_window else entry.selected_evidence_region_geometry,
        ),
        summary,
    )
    updated_audit = dict(event_unit.positive_rcsd_audit)
    updated_audit.update(
        {
            "road_surface_fork_binding": detail,
            "road_surface_fork_structure_only_no_rcsd": True,
            "swsd_junction_window_no_rcsd": use_swsd_window,
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": rcsd_mode,
            "rcsd_selection_mode": rcsd_mode,
            "rcsd_decision_reason": rcsd_mode,
        }
    )
    updated = replace(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source=evidence_source,
        position_source=position_source,
        rcsd_consistency_result=rcsd_mode,
        selected_component_union_geometry=None if use_swsd_window else event_unit.selected_component_union_geometry,
        localized_evidence_core_geometry=None if use_swsd_window else event_unit.localized_evidence_core_geometry,
        selected_evidence_region_geometry=None if use_swsd_window else event_unit.selected_evidence_region_geometry,
        positive_rcsd_present=False,
        positive_rcsd_present_reason=rcsd_mode,
        rcsd_selection_mode=rcsd_mode,
        positive_rcsd_support_level="no_support",
        positive_rcsd_consistency_level="C",
        required_rcsd_node=None,
        required_rcsd_node_source=None,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        candidate_audit_entries=updated_entries,
        conflict_resolution_action="road_surface_fork_binding",
        post_resolution_candidate_id=entry.candidate_id,
        resolution_reason=reason,
    )
    return updated, detail

def _clear_unbound_surface_candidate(
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    if event_unit.selected_evidence_state == "none":
        return None, None
    if event_unit.evidence_source != "road_surface_fork":
        return None, None
    if event_unit.required_rcsd_node:
        return None, None
    selected_summary = dict(event_unit.selected_evidence_summary or {})
    if selected_summary.get("road_surface_fork_binding"):
        return None, None
    if bool(selected_summary.get("node_fallback_only")):
        return None, None
    if any(
        "pair_local_scope_rcsdnode_outside_drivezone_filtered" in str(reason or "")
        for reason in event_unit.all_review_reasons()
    ):
        return None, None
    if _has_partial_rcsd_signal(event_unit):
        return None, None

    entry = _selected_surface_entry(event_unit)
    pair_local_summary = dict(event_unit.pair_local_summary or {})
    if (
        entry is not None
        and bool(pair_local_summary.get("pair_local_rcsd_empty"))
        and _weak_structure_surface_window_candidate(selected_summary)
    ):
        detail = {
            "action": "converted_unbound_road_surface_fork_to_swsd_junction_window",
            "reason": SWSD_JUNCTION_WINDOW_REASON,
            "candidate_id": entry.candidate_id,
            "pair_local_rcsd_empty": True,
            "pair_middle_overlap_ratio": _as_float(selected_summary.get("pair_middle_overlap_ratio")),
            "throat_overlap_ratio": _as_float(selected_summary.get("throat_overlap_ratio")),
            "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M,
        }
        rcsd_mode = "swsd_junction_window_no_rcsd"
        review_reasons = _dedupe(
            [
                *event_unit.all_review_reasons(),
                SWSD_JUNCTION_WINDOW_REASON,
            ]
        )
        summary = dict(selected_summary)
        summary.update(
            {
                "review_reasons": list(review_reasons),
                "road_surface_fork_binding": detail,
                "selected_evidence_state": "found",
                "evidence_source": SWSD_JUNCTION_WINDOW_SOURCE,
                "position_source": SWSD_JUNCTION_WINDOW_POSITION_SOURCE,
                "source_mode": SWSD_JUNCTION_WINDOW_SOURCE,
                "rcsd_consistency_result": rcsd_mode,
                "positive_rcsd_present": False,
                "positive_rcsd_present_reason": rcsd_mode,
                "positive_rcsd_support_level": "no_support",
                "positive_rcsd_consistency_level": "C",
                "required_rcsd_node": None,
                "required_rcsd_node_source": None,
                "rcsd_selection_mode": rcsd_mode,
                "rcsd_decision_reason": rcsd_mode,
                "decision_reason": SWSD_JUNCTION_WINDOW_REASON,
                "selection_status": "selected",
                "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M,
            }
        )
        updated_entries = _candidate_entries_with_selection(
            event_unit.candidate_audit_entries,
            replace(
                entry,
                candidate_summary=dict(summary),
                review_state="STEP4_REVIEW",
                review_reasons=review_reasons,
                evidence_source=SWSD_JUNCTION_WINDOW_SOURCE,
                position_source=SWSD_JUNCTION_WINDOW_POSITION_SOURCE,
                rcsd_consistency_result=rcsd_mode,
                positive_rcsd_support_level="no_support",
                positive_rcsd_consistency_level="C",
                required_rcsd_node=None,
                positive_rcsd_present=False,
                positive_rcsd_present_reason=rcsd_mode,
                rcsd_selection_mode=rcsd_mode,
                required_rcsd_node_source=None,
                localized_evidence_core_geometry=None,
                selected_component_union_geometry=None,
                selected_evidence_region_geometry=None,
            ),
            summary,
        )
        updated_audit = dict(event_unit.positive_rcsd_audit)
        updated_audit.update(
            {
                "road_surface_fork_binding": detail,
                "swsd_junction_window_no_rcsd": True,
                "positive_rcsd_present": False,
                "positive_rcsd_present_reason": rcsd_mode,
                "rcsd_selection_mode": rcsd_mode,
                "rcsd_decision_reason": rcsd_mode,
            }
        )
        updated = replace(
            event_unit,
            review_state="STEP4_REVIEW",
            review_reasons=review_reasons,
            evidence_source=SWSD_JUNCTION_WINDOW_SOURCE,
            position_source=SWSD_JUNCTION_WINDOW_POSITION_SOURCE,
            rcsd_consistency_result=rcsd_mode,
            selected_component_union_geometry=None,
            localized_evidence_core_geometry=None,
            selected_evidence_region_geometry=None,
            fact_reference_point=None,
            review_materialized_point=None,
            pair_local_rcsd_scope_geometry=None,
            first_hit_rcsd_road_geometry=None,
            local_rcsd_unit_geometry=None,
            positive_rcsd_geometry=None,
            positive_rcsd_road_geometry=None,
            positive_rcsd_node_geometry=None,
            primary_main_rc_node_geometry=None,
            required_rcsd_node_geometry=None,
            first_hit_rcsdroad_ids=(),
            selected_rcsdroad_ids=(),
            selected_rcsdnode_ids=(),
            primary_main_rc_node_id=None,
            local_rcsd_unit_id=None,
            local_rcsd_unit_kind=None,
            aggregated_rcsd_unit_id=None,
            aggregated_rcsd_unit_ids=(),
            positive_rcsd_present=False,
            positive_rcsd_present_reason=rcsd_mode,
            axis_polarity_inverted=False,
            rcsd_selection_mode=rcsd_mode,
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            required_rcsd_node=None,
            required_rcsd_node_source=None,
            selected_candidate_summary=dict(summary),
            selected_evidence_summary=dict(summary),
            positive_rcsd_audit=updated_audit,
            candidate_audit_entries=updated_entries,
            conflict_resolution_action="road_surface_fork_binding",
            post_resolution_candidate_id=entry.candidate_id,
            resolution_reason=SWSD_JUNCTION_WINDOW_REASON,
        )
        return updated, detail

    detail = {
        "action": "cleared_unbound_road_surface_fork",
        "reason": UNBOUND_ROAD_SURFACE_FORK_REASON,
        "candidate_id": str(selected_summary.get("candidate_id") or ""),
    }
    review_reasons = _dedupe(
        [
            *event_unit.all_review_reasons(),
            UNBOUND_ROAD_SURFACE_FORK_REASON,
            "no_selected_evidence_after_reselection",
        ]
    )
    empty_summary = {
        "candidate_id": "",
        "selected_evidence_state": "none",
        "evidence_source": "none",
        "position_source": "none",
        "selection_status": "rejected",
        "decision_reason": UNBOUND_ROAD_SURFACE_FORK_REASON,
        "review_state": "STEP4_REVIEW",
        "review_reasons": list(review_reasons),
    }
    updated_audit = dict(event_unit.positive_rcsd_audit)
    updated_audit.update(
        {
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": UNBOUND_ROAD_SURFACE_FORK_REASON,
            "rcsd_decision_reason": UNBOUND_ROAD_SURFACE_FORK_REASON,
            "unbound_road_surface_fork_without_bifurcation_rcsd": True,
        }
    )
    updated = replace(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source="none",
        position_source="none",
        reverse_tip_used=False,
        rcsd_consistency_result=UNBOUND_ROAD_SURFACE_FORK_REASON,
        selected_component_union_geometry=None,
        localized_evidence_core_geometry=None,
        coarse_anchor_zone_geometry=None,
        selected_evidence_region_geometry=None,
        fact_reference_point=None,
        review_materialized_point=None,
        pair_local_rcsd_scope_geometry=None,
        first_hit_rcsd_road_geometry=None,
        local_rcsd_unit_geometry=None,
        positive_rcsd_geometry=None,
        positive_rcsd_road_geometry=None,
        positive_rcsd_node_geometry=None,
        primary_main_rc_node_geometry=None,
        required_rcsd_node_geometry=None,
        selected_branch_ids=(),
        selected_event_branch_ids=(),
        selected_component_ids=(),
        first_hit_rcsdroad_ids=(),
        selected_rcsdroad_ids=(),
        selected_rcsdnode_ids=(),
        primary_main_rc_node_id=None,
        local_rcsd_unit_id=None,
        local_rcsd_unit_kind=None,
        aggregated_rcsd_unit_id=None,
        aggregated_rcsd_unit_ids=(),
        positive_rcsd_present=False,
        positive_rcsd_present_reason=UNBOUND_ROAD_SURFACE_FORK_REASON,
        axis_polarity_inverted=False,
        rcsd_selection_mode=UNBOUND_ROAD_SURFACE_FORK_REASON,
        positive_rcsd_support_level="no_support",
        positive_rcsd_consistency_level="C",
        required_rcsd_node=None,
        required_rcsd_node_source=None,
        event_axis_branch_id=None,
        event_chosen_s_m=None,
        selected_candidate_summary=dict(empty_summary),
        selected_evidence_summary=dict(empty_summary),
        positive_rcsd_audit=updated_audit,
        extra_review_notes=(),
        conflict_resolution_action="road_surface_fork_binding",
        post_resolution_candidate_id="",
        resolution_reason=UNBOUND_ROAD_SURFACE_FORK_REASON,
    )
    return updated, detail
