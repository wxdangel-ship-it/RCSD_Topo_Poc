from __future__ import annotations

from dataclasses import replace
from typing import Any

from shapely.geometry.base import BaseGeometry

from .case_models import T04CandidateAuditEntry, T04CaseResult, T04EventUnitResult
from .step4_road_surface_fork_binding_forward import _bind_strong_rcsd_to_surface
from .step4_road_surface_fork_binding_promotions import _promote_relaxed_primary_rcsd_binding
from .step4_road_surface_fork_binding_shared import (
    _build_surface_summary,
    _candidate_entries_with_selection,
    _invalid_divstrip_removed,
)
from .step4_road_surface_fork_geometry import (
    ROAD_SURFACE_FORK_BINDING_REASON,
    ROAD_SURFACE_FORK_SCOPE,
    SURFACE_RECOVERY_MAX_REFERENCE_DISTANCE_M,
    SURFACE_RECOVERY_MIN_THROAT_RATIO,
    SURFACE_RECOVERY_THROAT_EXCLUSION_M,
    _as_float,
    _clean_surface_review_reasons,
    _dedupe,
    _largest_polygon_component,
    _seed_component_geometry,
)
from .step4_road_surface_fork_rcsd import _entry_uses_relaxed_rcsd


def _recoverable_surface_candidate(event_unit: T04EventUnitResult) -> T04CandidateAuditEntry | None:
    if event_unit.selected_evidence_state != "none":
        return None
    if not _invalid_divstrip_removed(event_unit):
        return None
    candidates: list[tuple[tuple[float, int, str], T04CandidateAuditEntry]] = []
    for entry in event_unit.candidate_audit_entries:
        summary = entry.candidate_summary
        if str(summary.get("upper_evidence_kind") or "") != "structure_face":
            continue
        scope = str(summary.get("candidate_scope") or "")
        if scope != ROAD_SURFACE_FORK_SCOPE:
            continue
        throat_ratio = _as_float(summary.get("throat_overlap_ratio")) or 0.0
        reference_distance = _as_float(summary.get("reference_distance_to_origin_m")) or 0.0
        if throat_ratio < SURFACE_RECOVERY_MIN_THROAT_RATIO:
            continue
        if reference_distance > SURFACE_RECOVERY_MAX_REFERENCE_DISTANCE_M:
            continue
        if entry.candidate_region_geometry is None or entry.candidate_region_geometry.is_empty:
            continue
        axis_position = _as_float(summary.get("axis_position_m")) or 0.0
        candidates.append(((reference_distance, entry.pool_rank, f"{axis_position:.3f}:{entry.candidate_id}"), entry))
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1] if candidates else None

def _structure_base_entry(event_unit: T04EventUnitResult) -> T04CandidateAuditEntry | None:
    for entry in event_unit.candidate_audit_entries:
        if str(entry.candidate_summary.get("upper_evidence_kind") or "") == "structure_face":
            return entry
    return None

def _derived_road_surface_geometry(event_unit: T04EventUnitResult) -> BaseGeometry | None:
    base_geometry = event_unit.pair_local_middle_geometry or event_unit.pair_local_structure_face_geometry
    if base_geometry is None or base_geometry.is_empty:
        return None
    surface_geometry = base_geometry
    throat_core = event_unit.pair_local_throat_core_geometry
    if throat_core is not None and not throat_core.is_empty:
        surface_geometry = surface_geometry.difference(
            throat_core.buffer(SURFACE_RECOVERY_THROAT_EXCLUSION_M, join_style=2)
        )
    surface_geometry = _largest_polygon_component(surface_geometry)
    if surface_geometry is None or surface_geometry.is_empty:
        surface_geometry = _largest_polygon_component(base_geometry)
    return surface_geometry if surface_geometry is not None and not surface_geometry.is_empty else None

def _recovered_surface_entry_from_domain(
    event_unit: T04EventUnitResult,
) -> T04CandidateAuditEntry | None:
    if event_unit.selected_evidence_state != "none":
        return None
    if not _invalid_divstrip_removed(event_unit):
        return None
    base_entry = _structure_base_entry(event_unit)
    if base_entry is None:
        return None
    surface_geometry = _derived_road_surface_geometry(event_unit)
    if surface_geometry is None:
        return None

    reference_point = surface_geometry.representative_point()
    base_summary = dict(base_entry.candidate_summary)
    event_unit_id = event_unit.spec.event_unit_id
    upper_id = str(
        base_summary.get("upper_evidence_object_id")
        or event_unit.pair_local_summary.get("region_id")
        or "pair_local_structure_face"
    )
    axis_signature = str(base_summary.get("axis_signature") or base_summary.get("axis_position_basis") or "")
    axis_position = _as_float(base_summary.get("axis_position_m"))
    point_signature = (
        f"{axis_signature}:surface:{axis_position:.1f}"
        if axis_signature and axis_position is not None
        else f"surface:{round(float(reference_point.x), 3)}:{round(float(reference_point.y), 3)}"
    )
    candidate_id = f"{event_unit_id}:structure:road_surface_fork:recovered"
    bind_detail = {
        "action": "recovered_road_surface_fork_from_pair_local_surface",
        "source_candidate_id": base_entry.candidate_id,
        "source_candidate_scope": str(base_summary.get("candidate_scope") or ""),
        "source_node_fallback_only": bool(base_summary.get("node_fallback_only")),
        "relaxed_rcsd_dropped": _entry_uses_relaxed_rcsd(base_entry),
    }
    summary = dict(base_summary)
    summary.update(
        {
            "candidate_id": candidate_id,
            "source_mode": "pair_local_structure_mode",
            "upper_evidence_kind": "structure_face",
            "upper_evidence_object_id": upper_id,
            "candidate_scope": ROAD_SURFACE_FORK_SCOPE,
            "local_region_id": f"{event_unit_id}:structure_face:{upper_id}:road_surface_fork_recovered",
            "ownership_signature": f"structure_face:{upper_id}:{event_unit_id}:road_surface_fork_recovered",
            "point_signature": point_signature,
            "axis_signature": axis_signature,
            "axis_position_basis": str(base_summary.get("axis_position_basis") or axis_signature),
            "axis_position_m": axis_position,
            "reference_distance_to_origin_m": None,
            "node_fallback_only": False,
            "primary_eligible": True,
            "selected_after_reselection": False,
            "review_state": "STEP4_REVIEW",
            "review_reasons": list(
                _dedupe(
                    [
                        *_clean_surface_review_reasons(base_entry.review_reasons),
                        ROAD_SURFACE_FORK_BINDING_REASON,
                    ]
                )
            ),
            "evidence_source": "road_surface_fork",
            "position_source": "road_surface_fork",
            "reverse_tip_used": False,
            "rcsd_consistency_result": "road_surface_fork_without_bound_target_rcsd",
            "positive_rcsd_present": False,
            "positive_rcsd_support_level": "no_support",
            "positive_rcsd_consistency_level": "C",
            "required_rcsd_node": None,
            "required_rcsd_node_source": None,
            "rcsd_selection_mode": "road_surface_fork_without_bound_target_rcsd",
            "rcsd_decision_reason": "road_surface_fork_without_bound_target_rcsd",
            "selected_evidence_state": "found",
            "decision_reason": ROAD_SURFACE_FORK_BINDING_REASON,
            "road_surface_fork_binding": bind_detail,
        }
    )
    return replace(
        base_entry,
        candidate_id=candidate_id,
        pool_rank=max(1, int(base_entry.pool_rank or 1)),
        priority_score=max(1000, int(base_entry.priority_score or 0)),
        selection_status="selected",
        decision_reason=ROAD_SURFACE_FORK_BINDING_REASON,
        candidate_summary=summary,
        review_state="STEP4_REVIEW",
        review_reasons=tuple(summary["review_reasons"]),
        evidence_source="road_surface_fork",
        position_source="road_surface_fork",
        reverse_tip_used=False,
        rcsd_consistency_result="road_surface_fork_without_bound_target_rcsd",
        positive_rcsd_support_level="no_support",
        positive_rcsd_consistency_level="C",
        required_rcsd_node=None,
        candidate_region_geometry=surface_geometry,
        fact_reference_point=reference_point,
        review_materialized_point=reference_point,
        localized_evidence_core_geometry=surface_geometry,
        selected_component_union_geometry=surface_geometry,
        selected_evidence_region_geometry=surface_geometry,
        first_hit_rcsdroad_ids=(),
        selected_rcsdroad_ids=(),
        selected_rcsdnode_ids=(),
        primary_main_rc_node_id=None,
        local_rcsd_unit_id=None,
        local_rcsd_unit_kind=None,
        aggregated_rcsd_unit_id=None,
        aggregated_rcsd_unit_ids=(),
        positive_rcsd_present=False,
        positive_rcsd_present_reason="road_surface_fork_without_bound_target_rcsd",
        rcsd_selection_mode="road_surface_fork_without_bound_target_rcsd",
        required_rcsd_node_source=None,
        event_axis_branch_id=base_entry.event_axis_branch_id or event_unit.event_axis_branch_id,
        event_chosen_s_m=axis_position,
        positive_rcsd_audit={
            **dict(base_entry.positive_rcsd_audit),
            "road_surface_fork_binding": bind_detail,
            "road_surface_fork_without_bound_target_rcsd": True,
            "rcsd_decision_reason": "road_surface_fork_without_bound_target_rcsd",
        },
        pair_local_rcsd_scope_geometry=None,
        first_hit_rcsd_road_geometry=None,
        local_rcsd_unit_geometry=None,
        positive_rcsd_geometry=None,
        positive_rcsd_road_geometry=None,
        positive_rcsd_node_geometry=None,
        primary_main_rc_node_geometry=None,
        required_rcsd_node_geometry=None,
    )

def _recover_surface_from_candidate(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    entry = _recoverable_surface_candidate(event_unit)
    if entry is None:
        entry = _recovered_surface_entry_from_domain(event_unit)
    if entry is None:
        return None, None
    existing_detail = entry.candidate_summary.get("road_surface_fork_binding")
    relaxed_rcsd = _entry_uses_relaxed_rcsd(entry) or (
        isinstance(existing_detail, dict)
        and bool(existing_detail.get("relaxed_rcsd_dropped"))
    )
    bind_detail = (
        dict(existing_detail)
        if isinstance(existing_detail, dict)
        else {
            "action": "recovered_road_surface_fork_after_invalid_divstrip",
            "candidate_id": entry.candidate_id,
            "relaxed_rcsd_dropped": relaxed_rcsd,
        }
    )
    review_reasons = _dedupe(
        [
            *_clean_surface_review_reasons(entry.review_reasons),
            ROAD_SURFACE_FORK_BINDING_REASON,
        ]
    )
    summary = _build_surface_summary(
        entry,
        evidence_source="road_surface_fork",
        position_source="road_surface_fork",
        bind_detail=bind_detail,
    )
    summary["review_reasons"] = list(review_reasons)
    summary["rcsd_decision_reason"] = (
        "road_surface_fork_without_bound_target_rcsd"
        if relaxed_rcsd
        else str(summary.get("rcsd_decision_reason") or "")
    )
    summary["positive_rcsd_present"] = False if relaxed_rcsd else bool(entry.positive_rcsd_present)
    summary["positive_rcsd_support_level"] = "no_support" if relaxed_rcsd else entry.positive_rcsd_support_level
    summary["positive_rcsd_consistency_level"] = "C" if relaxed_rcsd else entry.positive_rcsd_consistency_level
    summary["required_rcsd_node"] = None if relaxed_rcsd else entry.required_rcsd_node
    summary["required_rcsd_node_source"] = None if relaxed_rcsd else entry.required_rcsd_node_source

    updated_entries = _candidate_entries_with_selection(event_unit.candidate_audit_entries, entry, summary)
    updated_audit = dict(entry.positive_rcsd_audit)
    updated_audit["road_surface_fork_binding"] = bind_detail
    if relaxed_rcsd:
        updated_audit["road_surface_fork_without_bound_target_rcsd"] = True
        updated_audit["rcsd_decision_reason"] = "road_surface_fork_without_bound_target_rcsd"

    seed_geometry = entry.fact_reference_point or entry.review_materialized_point
    surface_geometry = _seed_component_geometry(
        entry.selected_evidence_region_geometry or entry.candidate_region_geometry,
        seed_geometry,
    )
    component_geometry = _seed_component_geometry(
        entry.selected_component_union_geometry or surface_geometry,
        seed_geometry,
    )
    core_geometry = _seed_component_geometry(
        entry.localized_evidence_core_geometry or surface_geometry,
        seed_geometry,
    )

    updated = replace(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source="road_surface_fork",
        position_source="road_surface_fork",
        reverse_tip_used=False,
        rcsd_consistency_result=(
            "road_surface_fork_without_bound_target_rcsd"
            if relaxed_rcsd
            else entry.rcsd_consistency_result
        ),
        selected_component_union_geometry=component_geometry,
        localized_evidence_core_geometry=core_geometry,
        selected_evidence_region_geometry=surface_geometry,
        selected_candidate_region=entry.selected_candidate_region or event_unit.selected_candidate_region,
        fact_reference_point=entry.fact_reference_point or event_unit.fact_reference_point,
        review_materialized_point=entry.review_materialized_point or entry.fact_reference_point or event_unit.review_materialized_point,
        selected_branch_ids=entry.selected_branch_ids,
        selected_event_branch_ids=entry.selected_event_branch_ids,
        selected_component_ids=entry.selected_component_ids,
        first_hit_rcsdroad_ids=() if relaxed_rcsd else entry.first_hit_rcsdroad_ids,
        selected_rcsdroad_ids=() if relaxed_rcsd else entry.selected_rcsdroad_ids,
        selected_rcsdnode_ids=() if relaxed_rcsd else entry.selected_rcsdnode_ids,
        primary_main_rc_node_id=None if relaxed_rcsd else entry.primary_main_rc_node_id,
        local_rcsd_unit_id=None if relaxed_rcsd else entry.local_rcsd_unit_id,
        local_rcsd_unit_kind=None if relaxed_rcsd else entry.local_rcsd_unit_kind,
        aggregated_rcsd_unit_id=None if relaxed_rcsd else entry.aggregated_rcsd_unit_id,
        aggregated_rcsd_unit_ids=() if relaxed_rcsd else entry.aggregated_rcsd_unit_ids,
        positive_rcsd_present=False if relaxed_rcsd else entry.positive_rcsd_present,
        positive_rcsd_present_reason=(
            "road_surface_fork_without_bound_target_rcsd"
            if relaxed_rcsd
            else entry.positive_rcsd_present_reason
        ),
        rcsd_selection_mode=(
            "road_surface_fork_without_bound_target_rcsd"
            if relaxed_rcsd
            else entry.rcsd_selection_mode
        ),
        positive_rcsd_support_level="no_support" if relaxed_rcsd else entry.positive_rcsd_support_level,
        positive_rcsd_consistency_level="C" if relaxed_rcsd else entry.positive_rcsd_consistency_level,
        required_rcsd_node=None if relaxed_rcsd else entry.required_rcsd_node,
        required_rcsd_node_source=None if relaxed_rcsd else entry.required_rcsd_node_source,
        event_axis_branch_id=entry.event_axis_branch_id or event_unit.event_axis_branch_id,
        event_chosen_s_m=entry.event_chosen_s_m or _as_float(summary.get("axis_position_m")),
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        candidate_audit_entries=updated_entries,
        extra_review_notes=(),
        conflict_resolution_action="road_surface_fork_binding",
        post_resolution_candidate_id=entry.candidate_id,
        resolution_reason=ROAD_SURFACE_FORK_BINDING_REASON,
    )
    promoted, promoted_detail = _bind_strong_rcsd_to_surface(case_result, updated)
    if promoted is not None:
        return promoted, promoted_detail
    allow_exact_primary_fallback = bool(
        bind_detail.get("source_node_fallback_only")
        or (
            isinstance(existing_detail, dict)
            and bool(existing_detail.get("source_node_fallback_only"))
        )
    )
    if relaxed_rcsd or allow_exact_primary_fallback:
        promoted, promoted_detail = _promote_relaxed_primary_rcsd_binding(
            case_result,
            updated,
            entry,
            bind_detail,
            allow_exact_primary_fallback=allow_exact_primary_fallback,
        )
        if promoted is not None:
            return promoted, promoted_detail
    return updated, bind_detail
