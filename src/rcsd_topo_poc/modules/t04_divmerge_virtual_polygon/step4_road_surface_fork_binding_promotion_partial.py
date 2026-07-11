from __future__ import annotations

from dataclasses import replace

from typing import Any

from shapely.geometry import Point

from .case_models import T04CandidateAuditEntry, T04CaseResult, T04EventUnitResult

from ._step4_dual_write import append_dual_write_candidate, replace_step4_pre_arbiter_candidate

from .rcsd_alignment import (
    RCSD_ALIGNMENT_NONE,
    RCSD_ALIGNMENT_ROAD_ONLY,
    rcsd_alignment_type_from_selection,
)

from .step4_road_surface_fork_binding_shared import (
    _candidate_entries_with_selection,
    _has_partial_rcsd_signal,
    _selected_surface_entry,
)

from .step4_road_surface_fork_geometry import (
    JUNCTION_WINDOW_HALF_LENGTH_M,
    RCSD_JUNCTION_WINDOW_POSITION_SOURCE,
    RCSD_JUNCTION_WINDOW_REASON,
    RCSD_JUNCTION_WINDOW_SOURCE,
    RELAXED_PRIMARY_BINDING_MODE,
    RELAXED_PRIMARY_MAX_REPRESENTATIVE_DISTANCE_M,
    RELAXED_PRIMARY_NODE_SOURCE,
    ROAD_SURFACE_FORK_BINDING_REASON,
    SWSD_JUNCTION_WINDOW_POSITION_SOURCE,
    SWSD_JUNCTION_WINDOW_REASON,
    SWSD_JUNCTION_WINDOW_SOURCE,
    _dedupe,
    _node_geometries,
    _point_geometry,
    _road_geometries,
    _union_geometries,
)

from .step4_road_surface_fork_binding_swsd_rcsdroad import _score_single_rcsdroad

from .step4_road_surface_fork_rcsd import (
    _aggregate_ids,
    _first_hit_ids,
    _junction_window_aggregate,
    _local_unit_id_for_node,
    _relaxed_primary_aggregate,
    _same_case_rcsd_claim_conflict,
    _selected_surface_summary,
    _weak_structure_surface_window_candidate,
)

RCSD_JUNCTION_WINDOW_MAX_SEMANTIC_ANCHOR_DISTANCE_M = 60.0

DUPLICATE_POINT_SURFACE_DEMOTION_REASON = "duplicate_point_surface_demoted_to_swsd_rcsdroad"

DUPLICATE_POINT_SURFACE_DEMOTION_ACTION = (
    "demoted_duplicate_point_road_surface_fork_to_swsd_rcsdroad"
)

PARTIAL_SURFACE_DIRECT_FALLBACK_REASON = "road_surface_fork_direct_rcsdroad_fallback_only"

PARTIAL_SURFACE_DIRECT_FALLBACK_ACTION = (
    "retained_road_surface_fork_with_direct_rcsdroad_fallback_only"
)

from .step4_road_surface_fork_binding_promotion_base import (
    _direct_first_hit_fallback_roads,
    _direct_surface_fallback_roads,
    _downgrade_far_surface_rcsd_to_swsd_window,
    _duplicate_same_point_owner,
    _event_unit_key,
    _has_bilateral_event_side_support,
    _has_exact_published_semantic_window,
    _is_stronger_same_point_owner,
    _local_rcsd_unit_support,
    _published_member_unit_ids_for_selection,
    _same_point_signature,
    _score_doc,
    _semantic_anchor_distance_m,
    _weak_duplicate_point_surface_candidate,
    _with_unique_positive_rcsd_publish,
)

from .step4_road_surface_fork_binding_promotion_relaxed import (
    _promote_relaxed_primary_rcsd_binding,
    _promote_selected_surface_rcsd_junction_window,
)

def _demote_duplicate_point_surface_to_swsd_rcsdroad(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    entry: T04CandidateAuditEntry,
    *,
    aggregate_id: str,
    primary_node: str | None,
    selected_roads: tuple[str, ...],
    selected_nodes: tuple[str, ...],
    first_hit: tuple[str, ...],
    duplicate_owner: T04EventUnitResult,
    decision_reason: str,
) -> tuple[T04EventUnitResult, dict[str, Any]]:
    fallback_roads = _direct_first_hit_fallback_roads(first_hit, allowed_roads=selected_roads)
    fallback_first_hit = fallback_roads
    rcsd_mode = DUPLICATE_POINT_SURFACE_DEMOTION_REASON
    detail = {
        "action": DUPLICATE_POINT_SURFACE_DEMOTION_ACTION,
        "reason": DUPLICATE_POINT_SURFACE_DEMOTION_REASON,
        "candidate_id": entry.candidate_id,
        "duplicate_point_signature": _same_point_signature(event_unit),
        "duplicate_owner_unit_id": duplicate_owner.spec.event_unit_id,
        "duplicate_owner_evidence_source": duplicate_owner.evidence_source,
        "duplicate_owner_required_rcsd_node": duplicate_owner.required_rcsd_node,
        "aggregated_rcsd_unit_id": aggregate_id,
        "primary_node_id": primary_node,
        "demoted_rcsdroad_ids": list(selected_roads),
        "demoted_rcsdnode_ids": list(selected_nodes),
        "fallback_rcsdroad_ids": list(fallback_roads),
        "rcsd_decision_reason": decision_reason,
    }
    review_reasons = _dedupe(
        [
            *event_unit.all_review_reasons(),
            DUPLICATE_POINT_SURFACE_DEMOTION_REASON,
            SWSD_JUNCTION_WINDOW_REASON,
            ROAD_SURFACE_FORK_BINDING_REASON,
        ]
    )
    summary = dict(event_unit.selected_candidate_summary)
    summary.update(
        {
            "review_reasons": list(review_reasons),
            "road_surface_fork_binding": detail,
            "selected_evidence_state": "found",
            "evidence_source": SWSD_JUNCTION_WINDOW_SOURCE,
            "position_source": SWSD_JUNCTION_WINDOW_POSITION_SOURCE,
            "source_mode": SWSD_JUNCTION_WINDOW_SOURCE,
            "rcsd_consistency_result": "none",
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": rcsd_mode,
            "positive_rcsd_support_level": "no_support",
            "positive_rcsd_consistency_level": "C",
            "required_rcsd_node": None,
            "required_rcsd_node_source": None,
            "selected_rcsdroad_ids": [],
            "selected_rcsdnode_ids": [],
            "first_hit_rcsdroad_ids": list(fallback_first_hit),
            "fallback_rcsdroad_ids": list(fallback_roads),
            "local_rcsd_unit_id": None,
            "local_rcsd_unit_kind": None,
            "aggregated_rcsd_unit_id": None,
            "aggregated_rcsd_unit_ids": [],
            "primary_main_rc_node": None,
            "primary_main_rc_node_id": None,
            "rcsd_alignment_type": RCSD_ALIGNMENT_ROAD_ONLY,
            "rcsd_selection_mode": rcsd_mode,
            "rcsd_decision_reason": rcsd_mode,
            "decision_reason": DUPLICATE_POINT_SURFACE_DEMOTION_REASON,
            "duplicate_point_owner_unit_id": duplicate_owner.spec.event_unit_id,
            "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M,
        }
    )
    updated_audit = dict(event_unit.positive_rcsd_audit)
    updated_audit.pop("road_surface_fork_without_bound_target_rcsd", None)
    updated_audit.update(
        {
            "road_surface_fork_binding": detail,
            DUPLICATE_POINT_SURFACE_DEMOTION_REASON: detail,
            "swsd_junction_window_no_rcsd": True,
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": rcsd_mode,
            "positive_rcsd_support_level": "no_support",
            "positive_rcsd_consistency_level": "C",
            "required_rcsd_node": None,
            "required_rcsd_node_source": None,
            "published_rcsdroad_ids": list(fallback_roads),
            "published_rcsdnode_ids": [],
            "published_member_unit_ids": [],
            "published_rcsd_selection_mode": DUPLICATE_POINT_SURFACE_DEMOTION_REASON,
            "first_hit_rcsdroad_ids": list(fallback_first_hit),
            "selected_unit_role_assignments": [],
            "local_rcsd_unit_id": None,
            "local_rcsd_unit_kind": None,
            "aggregated_rcsd_unit_id": None,
            "aggregated_rcsd_unit_ids": [],
            "rcsd_alignment_type": RCSD_ALIGNMENT_NONE,
            "rcsd_selection_mode": rcsd_mode,
            "rcsd_decision_reason": rcsd_mode,
        }
    )
    updated_entry = replace_step4_pre_arbiter_candidate(
        entry,
        candidate_summary=dict(summary),
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source=SWSD_JUNCTION_WINDOW_SOURCE,
        position_source=SWSD_JUNCTION_WINDOW_POSITION_SOURCE,
        rcsd_consistency_result="none",
        positive_rcsd_support_level="no_support",
        positive_rcsd_consistency_level="C",
        rcsd_alignment_type=RCSD_ALIGNMENT_ROAD_ONLY,
        required_rcsd_node=None,
        fact_reference_point=None,
        review_materialized_point=None,
        localized_evidence_core_geometry=None,
        selected_component_union_geometry=None,
        selected_evidence_region_geometry=None,
        first_hit_rcsdroad_ids=fallback_first_hit,
        selected_rcsdroad_ids=(),
        selected_rcsdnode_ids=(),
        primary_main_rc_node_id=None,
        local_rcsd_unit_id=None,
        local_rcsd_unit_kind=None,
        aggregated_rcsd_unit_id=None,
        aggregated_rcsd_unit_ids=(),
        positive_rcsd_present=False,
        positive_rcsd_present_reason=rcsd_mode,
        rcsd_selection_mode=rcsd_mode,
        required_rcsd_node_source=None,
        positive_rcsd_audit=updated_audit,
        pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
        first_hit_rcsd_road_geometry=_road_geometries(case_result, fallback_first_hit),
        local_rcsd_unit_geometry=_road_geometries(case_result, fallback_roads),
        positive_rcsd_geometry=_road_geometries(case_result, fallback_roads),
        positive_rcsd_road_geometry=_road_geometries(case_result, fallback_roads),
        positive_rcsd_node_geometry=None,
        rcsdroad_only_chain=None,
        primary_main_rc_node_geometry=None,
        required_rcsd_node_geometry=None,
    )
    updated_entries = _candidate_entries_with_selection(
        event_unit.candidate_audit_entries,
        updated_entry,
        summary,
    )
    updated = replace_step4_pre_arbiter_candidate(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source=SWSD_JUNCTION_WINDOW_SOURCE,
        position_source=SWSD_JUNCTION_WINDOW_POSITION_SOURCE,
        rcsd_consistency_result="none",
        selected_component_union_geometry=None,
        localized_evidence_core_geometry=None,
        selected_evidence_region_geometry=None,
        fact_reference_point=None,
        review_materialized_point=None,
        pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
        first_hit_rcsd_road_geometry=_road_geometries(case_result, fallback_first_hit),
        local_rcsd_unit_geometry=_road_geometries(case_result, fallback_roads),
        positive_rcsd_geometry=_road_geometries(case_result, fallback_roads),
        positive_rcsd_road_geometry=_road_geometries(case_result, fallback_roads),
        positive_rcsd_node_geometry=None,
        primary_main_rc_node_geometry=None,
        required_rcsd_node_geometry=None,
        first_hit_rcsdroad_ids=fallback_first_hit,
        selected_rcsdroad_ids=(),
        selected_rcsdnode_ids=(),
        primary_main_rc_node_id=None,
        local_rcsd_unit_id=None,
        local_rcsd_unit_kind=None,
        aggregated_rcsd_unit_id=None,
        aggregated_rcsd_unit_ids=(),
        positive_rcsd_present=False,
        positive_rcsd_present_reason=rcsd_mode,
        rcsd_alignment_type=RCSD_ALIGNMENT_ROAD_ONLY,
        rcsd_selection_mode=rcsd_mode,
        positive_rcsd_support_level="no_support",
        positive_rcsd_consistency_level="C",
        required_rcsd_node=None,
        required_rcsd_node_source=None,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        rcsdroad_only_chain=None,
        surface_scenario_published=False,
        candidate_audit_entries=updated_entries,
        conflict_resolution_action="road_surface_fork_binding",
        post_resolution_candidate_id=entry.candidate_id,
        post_required_rcsd_node=None,
        resolution_reason=DUPLICATE_POINT_SURFACE_DEMOTION_REASON,
    )
    return (
        append_dual_write_candidate(
            updated,
            case_id=case_result.case_spec.case_id,
            source_stage="promotion",
            source_audit_blob=detail,
            replacement_reason=DUPLICATE_POINT_SURFACE_DEMOTION_REASON,
        ),
        detail,
    )
def _retain_surface_direct_rcsdroad_fallback_only(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    entry: T04CandidateAuditEntry,
    *,
    aggregate_id: str,
    primary_node: str | None,
    selected_roads: tuple[str, ...],
    selected_nodes: tuple[str, ...],
    first_hit: tuple[str, ...],
    decision_reason: str,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    fallback_roads, fallback_selection = _direct_surface_fallback_roads(case_result, event_unit, first_hit)
    if not fallback_roads:
        return None, None
    support_detail = {
        "action": PARTIAL_SURFACE_DIRECT_FALLBACK_ACTION,
        "promoted_action": "bound_selected_road_surface_fork_with_relaxed_required_rcsd",
        "candidate_id": entry.candidate_id,
        "candidate_scope": str(entry.candidate_summary.get("candidate_scope") or ""),
        "selected_surface_existing": True,
        "partial_rcsd_support_only": True,
        "published_as_fallback_only": True,
        "aggregated_rcsd_unit_id": aggregate_id,
        "primary_node_id": primary_node,
        "required_rcsd_node": None,
        **fallback_selection,
        "demoted_aggregate_rcsdroad_ids": list(selected_roads),
        "demoted_aggregate_rcsdnode_ids": list(selected_nodes),
        "rcsd_decision_reason": decision_reason,
    }
    review_reasons = _dedupe(
        [
            *event_unit.all_review_reasons(),
            PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
            ROAD_SURFACE_FORK_BINDING_REASON,
        ]
    )
    summary = dict(event_unit.selected_candidate_summary)
    summary.update(
        {
            "review_reasons": list(review_reasons),
            "road_surface_fork_binding": support_detail,
            "rcsd_consistency_result": "none",
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
            "positive_rcsd_support_level": "no_support",
            "positive_rcsd_consistency_level": "C",
            "required_rcsd_node": None,
            "required_rcsd_node_source": None,
            "selected_rcsdroad_ids": [],
            "selected_rcsdnode_ids": [],
            "first_hit_rcsdroad_ids": list(fallback_roads),
            "fallback_rcsdroad_ids": list(fallback_roads),
            "local_rcsd_unit_id": None,
            "local_rcsd_unit_kind": None,
            "aggregated_rcsd_unit_id": None,
            "aggregated_rcsd_unit_ids": [],
            "primary_main_rc_node": None,
            "primary_main_rc_node_id": None,
            "rcsd_alignment_type": RCSD_ALIGNMENT_ROAD_ONLY,
            "rcsd_selection_mode": PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
            "rcsd_decision_reason": PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
        }
    )
    updated_audit = dict(event_unit.positive_rcsd_audit)
    updated_audit.pop("road_surface_fork_without_bound_target_rcsd", None)
    updated_audit.update(
        {
            "road_surface_fork_binding": support_detail,
            PARTIAL_SURFACE_DIRECT_FALLBACK_REASON: support_detail,
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
            "positive_rcsd_support_level": "no_support",
            "positive_rcsd_consistency_level": "C",
            "required_rcsd_node_source": None,
            "required_rcsd_node": None,
            "published_rcsdroad_ids": list(fallback_roads),
            "published_rcsdnode_ids": [],
            "published_member_unit_ids": [],
            "published_rcsd_selection_mode": PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
            "first_hit_rcsdroad_ids": list(fallback_roads),
            "selected_unit_role_assignments": [
                assignment
                for assignment in updated_audit.get("selected_unit_role_assignments") or ()
                if isinstance(assignment, dict)
                and str(assignment.get("road_id") or "").strip() in set(fallback_roads)
            ],
            "local_rcsd_unit_id": None,
            "local_rcsd_unit_kind": None,
            "aggregated_rcsd_unit_id": None,
            "aggregated_rcsd_unit_ids": [],
            "rcsd_alignment_type": RCSD_ALIGNMENT_ROAD_ONLY,
            "rcsd_selection_mode": PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
            "rcsd_decision_reason": PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
        }
    )
    updated_entries = _candidate_entries_with_selection(
        event_unit.candidate_audit_entries,
        replace_step4_pre_arbiter_candidate(
            entry,
            candidate_summary=dict(summary),
            review_state="STEP4_REVIEW",
            review_reasons=review_reasons,
            rcsd_consistency_result="none",
            positive_rcsd_support_level="no_support",
            positive_rcsd_consistency_level="C",
            required_rcsd_node=None,
            first_hit_rcsdroad_ids=fallback_roads,
            selected_rcsdroad_ids=fallback_roads,
            selected_rcsdnode_ids=(),
            primary_main_rc_node_id=None,
            rcsd_alignment_type=RCSD_ALIGNMENT_ROAD_ONLY,
            local_rcsd_unit_id=None,
            local_rcsd_unit_kind=None,
            aggregated_rcsd_unit_id=None,
            aggregated_rcsd_unit_ids=(),
            positive_rcsd_present=False,
            positive_rcsd_present_reason=PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
            rcsd_selection_mode=PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
            required_rcsd_node_source=None,
            positive_rcsd_audit=updated_audit,
            pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
            first_hit_rcsd_road_geometry=_road_geometries(case_result, fallback_roads),
            local_rcsd_unit_geometry=_road_geometries(case_result, fallback_roads),
            positive_rcsd_geometry=_road_geometries(case_result, fallback_roads),
            positive_rcsd_road_geometry=_road_geometries(case_result, fallback_roads),
            positive_rcsd_node_geometry=None,
            rcsdroad_only_chain=None,
            primary_main_rc_node_geometry=None,
            required_rcsd_node_geometry=None,
        ),
        summary,
    )
    updated = replace_step4_pre_arbiter_candidate(
        event_unit,
        review_reasons=review_reasons,
        rcsd_consistency_result="none",
        pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
        first_hit_rcsd_road_geometry=_road_geometries(case_result, fallback_roads),
        local_rcsd_unit_geometry=_road_geometries(case_result, fallback_roads),
        positive_rcsd_geometry=_road_geometries(case_result, fallback_roads),
        positive_rcsd_road_geometry=_road_geometries(case_result, fallback_roads),
        positive_rcsd_node_geometry=None,
        primary_main_rc_node_geometry=None,
        required_rcsd_node_geometry=None,
        first_hit_rcsdroad_ids=fallback_roads,
        selected_rcsdroad_ids=fallback_roads,
        selected_rcsdnode_ids=(),
        primary_main_rc_node_id=None,
        rcsd_alignment_type=RCSD_ALIGNMENT_ROAD_ONLY,
        local_rcsd_unit_id=None,
        local_rcsd_unit_kind=None,
        aggregated_rcsd_unit_id=None,
        aggregated_rcsd_unit_ids=(),
        positive_rcsd_present=False,
        positive_rcsd_present_reason=PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
        rcsd_selection_mode=PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
        positive_rcsd_support_level="no_support",
        positive_rcsd_consistency_level="C",
        required_rcsd_node=None,
        required_rcsd_node_source=None,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        rcsdroad_only_chain=None,
        surface_scenario_published=False,
        candidate_audit_entries=updated_entries,
        conflict_resolution_action="road_surface_fork_binding",
        post_resolution_candidate_id=entry.candidate_id,
        post_required_rcsd_node=None,
        resolution_reason=PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
    )
    return (
        append_dual_write_candidate(
            updated,
            case_id=case_result.case_spec.case_id,
            source_stage="promotion",
            source_audit_blob=support_detail,
            replacement_reason=PARTIAL_SURFACE_DIRECT_FALLBACK_REASON,
        ),
        support_detail,
    )

def _promote_selected_surface_partial_rcsd(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    if event_unit.selected_evidence_state == "none":
        return None, None
    if event_unit.evidence_source != "road_surface_fork":
        return None, None
    if event_unit.required_rcsd_node:
        return None, None
    if not _has_partial_rcsd_signal(event_unit):
        return None, None
    entry = _selected_surface_entry(event_unit)
    if entry is None:
        return None, None
    bind_detail = {
        "action": "bound_selected_road_surface_fork_with_relaxed_required_rcsd",
        "promoted_action": "bound_selected_road_surface_fork_with_relaxed_required_rcsd",
        "candidate_id": entry.candidate_id,
        "candidate_scope": str(entry.candidate_summary.get("candidate_scope") or ""),
        "selected_surface_existing": True,
        "relaxed_rcsd_dropped": False,
    }
    promoted, promoted_detail = _promote_relaxed_primary_rcsd_binding(
        case_result,
        event_unit,
        entry,
        bind_detail,
        prefer_required_node=True,
    )
    if promoted is not None:
        return promoted, promoted_detail

    audit = dict(entry.positive_rcsd_audit)
    aggregate = _relaxed_primary_aggregate(audit)
    if aggregate is None:
        return None, None
    primary_node = str(aggregate.get("primary_node_id") or "").strip() or None
    road_ids = _aggregate_ids(aggregate, "road_ids")
    node_ids = _aggregate_ids(aggregate, "node_ids")
    selected_roads = _dedupe(audit.get("published_rcsdroad_ids") or road_ids)
    selected_nodes = _dedupe(audit.get("published_rcsdnode_ids") or node_ids)
    first_hit = _first_hit_ids(audit)
    support_level = str(aggregate.get("support_level") or "secondary_support")
    consistency_level = str(aggregate.get("consistency_level") or "B")
    decision_reason = str(aggregate.get("decision_reason") or "")
    aggregate_id = str(aggregate.get("unit_id") or "").strip()
    local_unit_id = _local_unit_id_for_node(aggregate, primary_node or "")
    duplicate_owner = _duplicate_same_point_owner(case_result, event_unit)
    if duplicate_owner is not None and selected_roads:
        return _demote_duplicate_point_surface_to_swsd_rcsdroad(
            case_result,
            event_unit,
            entry,
            aggregate_id=aggregate_id,
            primary_node=primary_node,
            selected_roads=selected_roads,
            selected_nodes=selected_nodes,
            first_hit=first_hit,
            duplicate_owner=duplicate_owner,
            decision_reason=decision_reason,
        )
    fallback_only, fallback_detail = _retain_surface_direct_rcsdroad_fallback_only(
        case_result,
        event_unit,
        entry,
        aggregate_id=aggregate_id,
        primary_node=primary_node,
        selected_roads=selected_roads,
        selected_nodes=selected_nodes,
        first_hit=first_hit,
        decision_reason=decision_reason,
    )
    if fallback_only is not None:
        return fallback_only, fallback_detail
    support_detail = dict(bind_detail)
    support_detail.update(
        {
            "action": "bound_selected_road_surface_fork_partial_rcsd_support_only",
            "partial_rcsd_support_only": True,
            "aggregated_rcsd_unit_id": aggregate_id,
            "primary_node_id": primary_node,
            "required_rcsd_node": None,
            "rcsd_decision_reason": decision_reason,
        }
    )
    updated_audit = _with_unique_positive_rcsd_publish(
        event_unit.positive_rcsd_audit,
        selected_roads=selected_roads,
        selected_nodes=selected_nodes,
        local_unit_id=local_unit_id,
        required_node=None,
        publish_mode="road_surface_fork_partial_rcsd_support_only",
    )
    updated_audit.pop("road_surface_fork_without_bound_target_rcsd", None)
    updated_audit.update(
        {
            "road_surface_fork_binding": support_detail,
            "road_surface_fork_partial_rcsd_support_only": support_detail,
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": "road_surface_fork_partial_rcsd_support_only",
            "required_rcsd_node_source": None,
            "required_rcsd_node": None,
            "rcsd_selection_mode": "road_surface_fork_partial_rcsd_support_only",
            "rcsd_decision_reason": decision_reason,
        }
    )
    review_reasons = _dedupe(
        [
            *event_unit.all_review_reasons(),
            "positive_rcsd_partial_consistent",
            ROAD_SURFACE_FORK_BINDING_REASON,
        ]
    )
    summary = dict(event_unit.selected_candidate_summary)
    summary.update(
        {
            "review_reasons": list(review_reasons),
            "road_surface_fork_binding": support_detail,
            "rcsd_consistency_result": "positive_rcsd_partial_consistent",
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": "road_surface_fork_partial_rcsd_support_only",
            "positive_rcsd_support_level": support_level,
            "positive_rcsd_consistency_level": consistency_level,
            "required_rcsd_node": None,
            "required_rcsd_node_source": None,
            "selected_rcsdroad_ids": list(selected_roads),
            "selected_rcsdnode_ids": list(selected_nodes),
            "first_hit_rcsdroad_ids": list(first_hit),
            "local_rcsd_unit_id": local_unit_id,
            "local_rcsd_unit_kind": "node_centric" if local_unit_id else None,
            "aggregated_rcsd_unit_id": aggregate_id,
            "aggregated_rcsd_unit_ids": list(
                _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
            ),
            "primary_main_rc_node": primary_node,
            "primary_main_rc_node_id": primary_node,
            "rcsd_selection_mode": "road_surface_fork_partial_rcsd_support_only",
            "rcsd_decision_reason": decision_reason,
        }
    )
    updated_entries = _candidate_entries_with_selection(
        event_unit.candidate_audit_entries,
        replace_step4_pre_arbiter_candidate(
            entry,
            candidate_summary=dict(summary),
            review_state="STEP4_REVIEW",
            review_reasons=review_reasons,
            rcsd_consistency_result="positive_rcsd_partial_consistent",
            positive_rcsd_support_level=support_level,
            positive_rcsd_consistency_level=consistency_level,
            required_rcsd_node=None,
            first_hit_rcsdroad_ids=first_hit,
            selected_rcsdroad_ids=selected_roads,
            selected_rcsdnode_ids=selected_nodes,
            primary_main_rc_node_id=primary_node,
            local_rcsd_unit_id=local_unit_id,
            local_rcsd_unit_kind="node_centric" if local_unit_id else None,
            aggregated_rcsd_unit_id=aggregate_id,
            aggregated_rcsd_unit_ids=tuple(
                _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
            ),
            positive_rcsd_present=True,
            positive_rcsd_present_reason="road_surface_fork_partial_rcsd_support_only",
            rcsd_selection_mode="road_surface_fork_partial_rcsd_support_only",
            required_rcsd_node_source=None,
            positive_rcsd_audit=updated_audit,
            pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
            first_hit_rcsd_road_geometry=_road_geometries(case_result, first_hit),
            local_rcsd_unit_geometry=_road_geometries(case_result, selected_roads),
            positive_rcsd_geometry=_union_geometries(
                [
                    _road_geometries(case_result, selected_roads),
                    _node_geometries(case_result, selected_nodes),
                ]
            ),
            positive_rcsd_road_geometry=_road_geometries(case_result, selected_roads),
            positive_rcsd_node_geometry=_node_geometries(case_result, selected_nodes),
            primary_main_rc_node_geometry=_point_geometry(case_result, primary_node),
            required_rcsd_node_geometry=None,
        ),
        summary,
    )
    updated = replace_step4_pre_arbiter_candidate(
        event_unit,
        review_reasons=review_reasons,
        rcsd_consistency_result="positive_rcsd_partial_consistent",
        pair_local_rcsd_scope_geometry=_road_geometries(case_result, event_unit.pair_local_rcsd_road_ids),
        first_hit_rcsd_road_geometry=_road_geometries(case_result, first_hit),
        local_rcsd_unit_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_geometry=_union_geometries(
            [
                _road_geometries(case_result, selected_roads),
                _node_geometries(case_result, selected_nodes),
            ]
        ),
        positive_rcsd_road_geometry=_road_geometries(case_result, selected_roads),
        positive_rcsd_node_geometry=_node_geometries(case_result, selected_nodes),
        primary_main_rc_node_geometry=_point_geometry(case_result, primary_node),
        required_rcsd_node_geometry=None,
        first_hit_rcsdroad_ids=first_hit,
        selected_rcsdroad_ids=selected_roads,
        selected_rcsdnode_ids=selected_nodes,
        primary_main_rc_node_id=primary_node,
        local_rcsd_unit_id=local_unit_id,
        local_rcsd_unit_kind="node_centric" if local_unit_id else None,
        aggregated_rcsd_unit_id=aggregate_id,
        aggregated_rcsd_unit_ids=tuple(
            _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
        ),
        positive_rcsd_present=True,
        positive_rcsd_present_reason="road_surface_fork_partial_rcsd_support_only",
        rcsd_selection_mode="road_surface_fork_partial_rcsd_support_only",
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        required_rcsd_node=None,
        required_rcsd_node_source=None,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        candidate_audit_entries=updated_entries,
    )
    return (
        append_dual_write_candidate(
            updated,
            case_id=case_result.case_spec.case_id,
            source_stage="promotion",
            source_audit_blob=support_detail,
            replacement_reason="road_surface_fork_partial_rcsd_support_only",
        ),
        support_detail,
    )
