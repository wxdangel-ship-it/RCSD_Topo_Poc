from __future__ import annotations

from dataclasses import replace
from typing import Any

from shapely.geometry import Point

from .case_models import T04CandidateAuditEntry, T04CaseResult, T04EventUnitResult
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
    _dedupe,
    _node_geometries,
    _point_geometry,
    _road_geometries,
    _union_geometries,
)
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


def _semantic_anchor_distance_m(aggregate: dict[str, Any]) -> float | None:
    value = aggregate.get("semantic_anchor_distance_m")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _has_bilateral_event_side_support(aggregate: dict[str, Any]) -> bool:
    labels = {
        str(label).strip().lower()
        for label in aggregate.get("normalized_event_side_labels") or ()
        if str(label).strip().lower() not in {"", "center"}
    }
    if len(labels) >= 2:
        return True
    for assignment in aggregate.get("role_assignments") or ():
        if not isinstance(assignment, dict):
            continue
        if str(assignment.get("axis_side") or "").strip() != "event_side":
            continue
        label = str(assignment.get("side_label") or "").strip().lower()
        if label and label != "center":
            labels.add(label)
    return len(labels) >= 2

def _local_rcsd_unit_support(
    audit: dict[str, Any],
    *,
    local_unit_id: str | None,
    required_node: str,
) -> dict[str, Any] | None:
    for unit in audit.get("local_rcsd_units") or ():
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("unit_id") or "").strip()
        node_id = str(unit.get("node_id") or "").strip()
        if local_unit_id and unit_id == local_unit_id:
            return unit
        if required_node and node_id == required_node:
            return unit
    return None


def _downgrade_far_surface_rcsd_to_swsd_window(
    event_unit: T04EventUnitResult,
    entry: T04CandidateAuditEntry,
    *,
    aggregate: dict[str, Any],
    semantic_anchor_distance_m: float,
) -> tuple[T04EventUnitResult, dict[str, Any]]:
    selected_summary = _selected_surface_summary(event_unit)
    rcsd_mode = "swsd_junction_window_no_rcsd"
    detail = {
        "action": "downgraded_far_rcsd_junction_window_to_swsd",
        "candidate_id": entry.candidate_id,
        "aggregated_rcsd_unit_id": str(aggregate.get("unit_id") or ""),
        "semantic_anchor_distance_m": semantic_anchor_distance_m,
        "max_semantic_anchor_distance_m": RCSD_JUNCTION_WINDOW_MAX_SEMANTIC_ANCHOR_DISTANCE_M,
        "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M,
    }
    review_reasons = _dedupe(
        [
            *event_unit.all_review_reasons(),
            SWSD_JUNCTION_WINDOW_REASON,
            ROAD_SURFACE_FORK_BINDING_REASON,
        ]
    )
    summary = dict(selected_summary)
    summary.update(
        {
            "review_reasons": list(review_reasons),
            "selected_evidence_state": "found",
            "evidence_source": "road_surface_fork",
            "position_source": SWSD_JUNCTION_WINDOW_POSITION_SOURCE,
            "source_mode": "swsd_junction_window",
            "road_surface_fork_binding": detail,
            "rcsd_consistency_result": rcsd_mode,
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": rcsd_mode,
            "positive_rcsd_support_level": "no_support",
            "positive_rcsd_consistency_level": "C",
            "required_rcsd_node": None,
            "required_rcsd_node_source": None,
            "selected_rcsdroad_ids": [],
            "selected_rcsdnode_ids": [],
            "first_hit_rcsdroad_ids": [],
            "local_rcsd_unit_id": None,
            "local_rcsd_unit_kind": None,
            "aggregated_rcsd_unit_id": None,
            "aggregated_rcsd_unit_ids": [],
            "primary_main_rc_node": None,
            "primary_main_rc_node_id": None,
            "rcsd_selection_mode": rcsd_mode,
            "rcsd_decision_reason": rcsd_mode,
            "decision_reason": SWSD_JUNCTION_WINDOW_REASON,
            "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M,
        }
    )
    updated_audit = dict(event_unit.positive_rcsd_audit)
    updated_audit.update(
        {
            "road_surface_fork_binding": detail,
            "swsd_junction_window_no_rcsd": True,
            "positive_rcsd_present": False,
            "positive_rcsd_present_reason": rcsd_mode,
            "required_rcsd_node": None,
            "required_rcsd_node_source": None,
            "published_rcsdroad_ids": [],
            "published_rcsdnode_ids": [],
            "first_hit_rcsdroad_ids": [],
            "selected_unit_role_assignments": [],
            "aggregated_rcsd_unit_id": None,
            "aggregated_rcsd_unit_ids": [],
            "rcsd_selection_mode": rcsd_mode,
            "rcsd_decision_reason": rcsd_mode,
        }
    )
    updated_entry = replace(
        entry,
        candidate_summary=dict(summary),
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source="road_surface_fork",
        position_source=SWSD_JUNCTION_WINDOW_POSITION_SOURCE,
        rcsd_consistency_result=rcsd_mode,
        positive_rcsd_support_level="no_support",
        positive_rcsd_consistency_level="C",
        required_rcsd_node=None,
        fact_reference_point=None,
        review_materialized_point=None,
        localized_evidence_core_geometry=None,
        selected_component_union_geometry=None,
        selected_evidence_region_geometry=None,
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
        rcsd_selection_mode=rcsd_mode,
        required_rcsd_node_source=None,
        positive_rcsd_audit=updated_audit,
        pair_local_rcsd_scope_geometry=None,
        first_hit_rcsd_road_geometry=None,
        local_rcsd_unit_geometry=None,
        positive_rcsd_geometry=None,
        positive_rcsd_road_geometry=None,
        positive_rcsd_node_geometry=None,
        primary_main_rc_node_geometry=None,
        required_rcsd_node_geometry=None,
    )
    updated_entries = _candidate_entries_with_selection(
        event_unit.candidate_audit_entries,
        updated_entry,
        summary,
    )
    updated = replace(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source="road_surface_fork",
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
        post_required_rcsd_node=None,
        resolution_reason=SWSD_JUNCTION_WINDOW_REASON,
    )
    return updated, detail


def _promote_relaxed_primary_rcsd_binding(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    entry: T04CandidateAuditEntry,
    bind_detail: dict[str, Any],
    *,
    allow_exact_primary_fallback: bool = False,
    prefer_required_node: bool = False,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    audit = dict(entry.positive_rcsd_audit)
    aggregate = _relaxed_primary_aggregate(
        audit,
        allow_exact_primary_fallback=allow_exact_primary_fallback,
    )
    if aggregate is None:
        return None, None

    primary_node = str(aggregate.get("primary_node_id") or "").strip()
    aggregate_required_node = str(aggregate.get("required_node_id") or "").strip() or primary_node
    bound_node = aggregate_required_node if prefer_required_node else primary_node
    required_geometry = _point_geometry(case_result, bound_node)
    representative_geometry = getattr(event_unit.unit_context.representative_node, "geometry", None)
    if not isinstance(required_geometry, Point) or not isinstance(representative_geometry, Point):
        return None, None
    representative_distance = float(required_geometry.distance(representative_geometry))
    if representative_distance > RELAXED_PRIMARY_MAX_REPRESENTATIVE_DISTANCE_M:
        return None, None

    road_ids = _aggregate_ids(aggregate, "road_ids")
    node_ids = _aggregate_ids(aggregate, "node_ids")
    selected_roads = _dedupe(audit.get("published_rcsdroad_ids") or road_ids)
    selected_nodes = _dedupe(audit.get("published_rcsdnode_ids") or node_ids)
    first_hit = _first_hit_ids(audit)
    support_level = str(aggregate.get("support_level") or "secondary_support")
    consistency_level = str(aggregate.get("consistency_level") or "B")
    decision_reason = str(aggregate.get("decision_reason") or "")
    if allow_exact_primary_fallback and decision_reason == "role_mapping_exact_aggregated":
        consistency_level = "B"
        if support_level == "primary_support":
            support_level = "secondary_support"
    aggregate_id = str(aggregate.get("unit_id") or "").strip()
    local_unit_id = _local_unit_id_for_node(aggregate, bound_node)
    promoted_detail = dict(bind_detail)
    promoted_detail.update(
        {
            "action": str(
                bind_detail.get("promoted_action") or "recovered_road_surface_fork_with_relaxed_primary_rcsd"
            ),
            "relaxed_rcsd_dropped": False,
            "relaxed_primary_rcsd_promoted": True,
            "aggregated_rcsd_unit_id": aggregate_id,
            "required_rcsd_node": bound_node,
            "primary_node_id": primary_node,
            "original_required_node_id": aggregate_required_node or None,
            "required_node_source": RELAXED_PRIMARY_NODE_SOURCE,
            "bound_node_strategy": "aggregate_required_node" if prefer_required_node else "aggregate_primary_node",
            "representative_distance_m": round(representative_distance, 3),
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
            "road_surface_fork_binding": promoted_detail,
            "rcsd_consistency_result": "positive_rcsd_partial_consistent",
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": "road_surface_fork_relaxed_primary_rcsd_present",
            "positive_rcsd_support_level": support_level,
            "positive_rcsd_consistency_level": consistency_level,
            "required_rcsd_node": bound_node,
            "required_rcsd_node_source": RELAXED_PRIMARY_NODE_SOURCE,
            "selected_rcsdroad_ids": list(selected_roads),
            "selected_rcsdnode_ids": list(selected_nodes),
            "first_hit_rcsdroad_ids": list(first_hit),
            "local_rcsd_unit_id": local_unit_id,
            "local_rcsd_unit_kind": "node_centric",
            "aggregated_rcsd_unit_id": aggregate_id,
            "aggregated_rcsd_unit_ids": list(
                _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
            ),
            "primary_main_rc_node": primary_node,
            "primary_main_rc_node_id": primary_node,
            "rcsd_selection_mode": RELAXED_PRIMARY_BINDING_MODE,
            "rcsd_decision_reason": decision_reason,
        }
    )
    promoted_entry = replace(
        entry,
        candidate_summary=dict(summary),
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        rcsd_consistency_result="positive_rcsd_partial_consistent",
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        required_rcsd_node=bound_node,
        first_hit_rcsdroad_ids=first_hit,
        selected_rcsdroad_ids=selected_roads,
        selected_rcsdnode_ids=selected_nodes,
        primary_main_rc_node_id=primary_node,
        local_rcsd_unit_id=local_unit_id,
        local_rcsd_unit_kind="node_centric",
        aggregated_rcsd_unit_id=aggregate_id,
        aggregated_rcsd_unit_ids=tuple(
            _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
        ),
        positive_rcsd_present=True,
        positive_rcsd_present_reason="road_surface_fork_relaxed_primary_rcsd_present",
        rcsd_selection_mode=RELAXED_PRIMARY_BINDING_MODE,
        required_rcsd_node_source=RELAXED_PRIMARY_NODE_SOURCE,
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
        primary_main_rc_node_geometry=required_geometry,
        required_rcsd_node_geometry=required_geometry,
    )
    updated_entries = _candidate_entries_with_selection(
        event_unit.candidate_audit_entries,
        promoted_entry,
        summary,
    )
    updated_audit = dict(event_unit.positive_rcsd_audit)
    updated_audit.pop("road_surface_fork_without_bound_target_rcsd", None)
    updated_audit.update(
        {
            "road_surface_fork_binding": promoted_detail,
            "road_surface_fork_relaxed_primary_rcsd_binding": promoted_detail,
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": "road_surface_fork_relaxed_primary_rcsd_present",
            "required_rcsd_node_source": RELAXED_PRIMARY_NODE_SOURCE,
            "required_rcsd_node": bound_node,
            "rcsd_selection_mode": RELAXED_PRIMARY_BINDING_MODE,
            "rcsd_decision_reason": decision_reason,
        }
    )
    updated = replace(
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
        primary_main_rc_node_geometry=required_geometry,
        required_rcsd_node_geometry=required_geometry,
        first_hit_rcsdroad_ids=first_hit,
        selected_rcsdroad_ids=selected_roads,
        selected_rcsdnode_ids=selected_nodes,
        primary_main_rc_node_id=primary_node,
        local_rcsd_unit_id=local_unit_id,
        local_rcsd_unit_kind="node_centric",
        aggregated_rcsd_unit_id=aggregate_id,
        aggregated_rcsd_unit_ids=tuple(
            _dedupe(audit.get("aggregated_rcsd_unit_ids") or aggregate.get("member_unit_ids") or ())
        ),
        positive_rcsd_present=True,
        positive_rcsd_present_reason="road_surface_fork_relaxed_primary_rcsd_present",
        rcsd_selection_mode=RELAXED_PRIMARY_BINDING_MODE,
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        required_rcsd_node=bound_node,
        required_rcsd_node_source=RELAXED_PRIMARY_NODE_SOURCE,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        candidate_audit_entries=updated_entries,
        post_required_rcsd_node=bound_node,
    )
    return updated, promoted_detail

def _promote_selected_surface_rcsd_junction_window(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    if event_unit.selected_evidence_state == "none":
        return None, None
    if event_unit.evidence_source != "road_surface_fork":
        return None, None
    if event_unit.required_rcsd_node:
        return None, None
    entry = _selected_surface_entry(event_unit)
    if entry is None:
        return None, None
    audit = dict(event_unit.positive_rcsd_audit)
    aggregate = _junction_window_aggregate(audit)
    if aggregate is None:
        return None, None
    if _has_partial_rcsd_signal(event_unit) and str(aggregate.get("consistency_level") or "").strip().upper() == "B":
        return None, None
    semantic_anchor_distance = _semantic_anchor_distance_m(aggregate)
    if (
        semantic_anchor_distance is not None
        and semantic_anchor_distance > RCSD_JUNCTION_WINDOW_MAX_SEMANTIC_ANCHOR_DISTANCE_M
    ):
        return _downgrade_far_surface_rcsd_to_swsd_window(
            event_unit,
            entry,
            aggregate=aggregate,
            semantic_anchor_distance_m=semantic_anchor_distance,
        )
    selected_summary = _selected_surface_summary(event_unit)
    first_hit = _first_hit_ids(audit)
    if (
        str(aggregate.get("consistency_level") or "").strip() == "A"
        and len(first_hit) < 2
        and not _weak_structure_surface_window_candidate(selected_summary)
    ):
        return None, None
    primary_node = str(aggregate.get("primary_node_id") or "").strip()
    required_node = str(aggregate.get("required_node_id") or "").strip() or primary_node
    if not required_node:
        return None, None
    required_geometry = _point_geometry(case_result, required_node)
    if required_geometry is None:
        return None, None

    aggregate_id = str(aggregate.get("unit_id") or audit.get("aggregated_rcsd_unit_id") or "").strip()
    support_level = str(aggregate.get("support_level") or event_unit.positive_rcsd_support_level or "secondary_support")
    consistency_level = str(aggregate.get("consistency_level") or event_unit.positive_rcsd_consistency_level or "B")
    decision_reason = str(aggregate.get("decision_reason") or audit.get("rcsd_decision_reason") or "")
    local_unit_id = _local_unit_id_for_node(aggregate, required_node) or _local_unit_id_for_node(aggregate, primary_node)
    reference_point = event_unit.fact_reference_point if isinstance(event_unit.fact_reference_point, Point) else None
    if reference_point is None and isinstance(entry.fact_reference_point, Point):
        reference_point = entry.fact_reference_point
    review_point = event_unit.review_materialized_point if isinstance(event_unit.review_materialized_point, Point) else None
    if review_point is None:
        review_point = reference_point
    preserve_surface_main_evidence = bool(
        _has_bilateral_event_side_support(aggregate)
        and reference_point is not None
        and (
            event_unit.localized_evidence_core_geometry is not None
            or entry.localized_evidence_core_geometry is not None
            or event_unit.selected_component_union_geometry is not None
            or entry.selected_component_union_geometry is not None
        )
    )
    road_ids = _aggregate_ids(aggregate, "road_ids")
    node_ids = _aggregate_ids(aggregate, "node_ids")
    local_support = _local_rcsd_unit_support(
        audit,
        local_unit_id=local_unit_id,
        required_node=required_node,
    )
    if preserve_surface_main_evidence and local_support is not None:
        selected_roads = _dedupe(local_support.get("road_ids") or ())
        selected_nodes = _dedupe(local_support.get("node_ids") or ())
    else:
        selected_roads = _dedupe(audit.get("published_rcsdroad_ids") or road_ids)
        selected_nodes = _dedupe(audit.get("published_rcsdnode_ids") or node_ids)
    first_hit = tuple(road_id for road_id in first_hit if road_id in set(selected_roads))
    if _same_case_rcsd_claim_conflict(
        case_result,
        event_unit,
        aggregate_id=aggregate_id,
        required_node=required_node,
        primary_node=primary_node,
        selected_roads=selected_roads,
        selected_nodes=selected_nodes,
    ):
        return None, None
    evidence_source = "road_surface_fork" if preserve_surface_main_evidence else RCSD_JUNCTION_WINDOW_SOURCE
    position_source = (
        str(event_unit.position_source or entry.position_source or "road_surface_fork")
        if preserve_surface_main_evidence
        else RCSD_JUNCTION_WINDOW_POSITION_SOURCE
    )
    source_mode = (
        str(selected_summary.get("source_mode") or evidence_source)
        if preserve_surface_main_evidence
        else RCSD_JUNCTION_WINDOW_SOURCE
    )
    rcsd_selection_mode = (
        "road_surface_fork_rcsd_junction_local_unit_binding"
        if preserve_surface_main_evidence
        else RCSD_JUNCTION_WINDOW_SOURCE
    )
    rcsd_consistency_result = (
        "positive_rcsd_partial_consistent"
        if preserve_surface_main_evidence
        else RCSD_JUNCTION_WINDOW_SOURCE
    )
    positive_reason = (
        "road_surface_fork_rcsd_junction_local_unit_present"
        if preserve_surface_main_evidence
        else "rcsd_junction_window_forward_rcsd_present"
    )
    detail = {
        "action": "bound_selected_surface_to_rcsd_junction_window",
        "candidate_id": entry.candidate_id,
        "aggregated_rcsd_unit_id": aggregate_id,
        "required_rcsd_node": required_node,
        "primary_node_id": primary_node,
        "selected_rcsdroad_ids": list(selected_roads),
        "selected_rcsdnode_ids": list(selected_nodes),
        "first_hit_rcsdroad_ids": list(first_hit),
        "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M,
        "rcsd_decision_reason": decision_reason,
        "preserved_surface_main_evidence": preserve_surface_main_evidence,
        "selected_rcsd_scope": "required_node_local_unit" if preserve_surface_main_evidence else "published_aggregate",
        "aggregate_context_rcsdroad_ids": list(road_ids),
        "aggregate_context_rcsdnode_ids": list(node_ids),
    }
    review_reasons = _dedupe(
        [
            *event_unit.all_review_reasons(),
            "positive_rcsd_partial_consistent",
            RCSD_JUNCTION_WINDOW_REASON,
            *([ROAD_SURFACE_FORK_BINDING_REASON] if preserve_surface_main_evidence else []),
        ]
    )
    summary = dict(selected_summary)
    summary.update(
        {
            "review_reasons": list(review_reasons),
            "selected_evidence_state": "found",
            "evidence_source": evidence_source,
            "position_source": position_source,
            "source_mode": source_mode,
            "road_surface_fork_binding": detail,
            "rcsd_consistency_result": rcsd_consistency_result,
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": positive_reason,
            "positive_rcsd_support_level": support_level,
            "positive_rcsd_consistency_level": consistency_level,
            "required_rcsd_node": required_node,
            "required_rcsd_node_source": RCSD_JUNCTION_WINDOW_SOURCE,
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
            "rcsd_selection_mode": rcsd_selection_mode,
            "rcsd_decision_reason": decision_reason,
            "window_half_length_m": JUNCTION_WINDOW_HALF_LENGTH_M,
        }
    )
    updated_audit = dict(audit)
    updated_audit.pop("road_surface_fork_without_bound_target_rcsd", None)
    updated_audit.update(
        {
            "road_surface_fork_binding": detail,
            "rcsd_junction_window": detail,
            "positive_rcsd_present": True,
            "positive_rcsd_present_reason": positive_reason,
            "required_rcsd_node": required_node,
            "required_rcsd_node_source": RCSD_JUNCTION_WINDOW_SOURCE,
            "rcsd_selection_mode": rcsd_selection_mode,
            "rcsd_decision_reason": decision_reason,
        }
    )
    updated_entry = replace(
        entry,
        candidate_summary=dict(summary),
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source=evidence_source,
        position_source=position_source,
        rcsd_consistency_result=rcsd_consistency_result,
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        required_rcsd_node=required_node,
        fact_reference_point=reference_point if preserve_surface_main_evidence else required_geometry,
        review_materialized_point=review_point if preserve_surface_main_evidence else required_geometry,
        localized_evidence_core_geometry=(
            entry.localized_evidence_core_geometry if preserve_surface_main_evidence else None
        ),
        selected_component_union_geometry=(
            entry.selected_component_union_geometry if preserve_surface_main_evidence else None
        ),
        selected_evidence_region_geometry=(
            entry.selected_evidence_region_geometry if preserve_surface_main_evidence else None
        ),
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
        positive_rcsd_present_reason=positive_reason,
        rcsd_selection_mode=rcsd_selection_mode,
        required_rcsd_node_source=RCSD_JUNCTION_WINDOW_SOURCE,
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
        required_rcsd_node_geometry=required_geometry,
    )
    updated_entries = _candidate_entries_with_selection(
        event_unit.candidate_audit_entries,
        updated_entry,
        summary,
    )
    updated = replace(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source=evidence_source,
        position_source=position_source,
        rcsd_consistency_result=rcsd_consistency_result,
        selected_component_union_geometry=(
            event_unit.selected_component_union_geometry
            if preserve_surface_main_evidence
            else None
        ),
        localized_evidence_core_geometry=(
            event_unit.localized_evidence_core_geometry
            if preserve_surface_main_evidence
            else None
        ),
        selected_evidence_region_geometry=(
            event_unit.selected_evidence_region_geometry
            if preserve_surface_main_evidence
            else None
        ),
        fact_reference_point=reference_point if preserve_surface_main_evidence else required_geometry,
        review_materialized_point=review_point if preserve_surface_main_evidence else required_geometry,
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
        required_rcsd_node_geometry=required_geometry,
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
        positive_rcsd_present_reason=positive_reason,
        rcsd_selection_mode=rcsd_selection_mode,
        positive_rcsd_support_level=support_level,
        positive_rcsd_consistency_level=consistency_level,
        required_rcsd_node=required_node,
        required_rcsd_node_source=RCSD_JUNCTION_WINDOW_SOURCE,
        selected_candidate_summary=dict(summary),
        selected_evidence_summary=dict(summary),
        positive_rcsd_audit=updated_audit,
        candidate_audit_entries=updated_entries,
        conflict_resolution_action="road_surface_fork_binding",
        post_resolution_candidate_id=entry.candidate_id,
        post_required_rcsd_node=required_node,
        resolution_reason=RCSD_JUNCTION_WINDOW_REASON,
    )
    return updated, detail

def _promote_selected_surface_partial_rcsd(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
) -> tuple[T04EventUnitResult | None, dict[str, Any] | None]:
    if event_unit.selected_evidence_state == "none":
        return None, None
    if event_unit.evidence_source != "road_surface_fork":
        return None, None
    force_partial_support_only = bool(
        event_unit.required_rcsd_node
        and str(event_unit.positive_rcsd_consistency_level or "").strip().upper() == "B"
    )
    if event_unit.required_rcsd_node and not force_partial_support_only:
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
    if not force_partial_support_only:
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
        replace(
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
    updated_audit = dict(event_unit.positive_rcsd_audit)
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
    updated = replace(
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
    return updated, support_detail
