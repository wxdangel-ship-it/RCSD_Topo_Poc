from __future__ import annotations

from typing import Any, Iterable

from .case_models import T04CandidateAuditEntry, T04CaseResult
from .step4_road_surface_fork_geometry import (
    RELAXED_AGGREGATED_RCSD_REASONS,
    ROAD_SURFACE_FORK_SCOPE,
    SAME_CASE_RCSD_ROAD_OVERLAP_MIN_COUNT,
    SAME_CASE_RCSD_ROAD_OVERLAP_MIN_RATIO,
    STRUCTURE_ONLY_SURFACE_WINDOW_MAX_PAIR_MIDDLE_RATIO,
    _as_float,
    _dedupe,
)

def _strong_aggregated_unit(audit: dict[str, Any]) -> dict[str, Any] | None:
    for aggregate in audit.get("aggregated_rcsd_units") or ():
        if not isinstance(aggregate, dict):
            continue
        decision_reason = str(aggregate.get("decision_reason") or "").strip()
        if decision_reason in RELAXED_AGGREGATED_RCSD_REASONS:
            continue
        if decision_reason and decision_reason != "role_mapping_exact_aggregated":
            continue
        if str(aggregate.get("consistency_level") or "") != "A":
            continue
        if not str(aggregate.get("required_node_id") or "").strip():
            continue
        if not _has_bifurcation_role_support(aggregate):
            continue
        return aggregate
    return None


def _strong_road_surface_fork_aggregated_unit(audit: dict[str, Any]) -> dict[str, Any] | None:
    aggregate = _strong_aggregated_unit(audit)
    if aggregate is not None:
        return aggregate
    published_mode = str(audit.get("published_rcsd_selection_mode") or "").strip()
    if published_mode not in {
        "aggregated_a_exact_required_node_unit_with_trace",
        "aggregated_a_positive_node_units_with_trace",
    }:
        return None
    for aggregate in audit.get("aggregated_rcsd_units") or ():
        if not isinstance(aggregate, dict):
            continue
        decision_reason = str(aggregate.get("decision_reason") or "").strip()
        if decision_reason in RELAXED_AGGREGATED_RCSD_REASONS:
            continue
        if decision_reason and decision_reason != "role_mapping_exact_aggregated":
            continue
        if str(aggregate.get("consistency_level") or "") != "A":
            continue
        if not str(aggregate.get("required_node_id") or "").strip():
            continue
        if str(aggregate.get("required_node_source") or "").strip() != "aggregated_node_centric":
            continue
        event_side_roads = set(_aggregate_ids(aggregate, "event_side_road_ids"))
        axis_side_roads = set(_aggregate_ids(aggregate, "axis_side_road_ids"))
        if len(event_side_roads & axis_side_roads) > 1:
            continue
        if not _has_road_surface_fork_role_support(aggregate):
            continue
        return aggregate
    return None


def _has_bifurcation_role_support(aggregate: dict[str, Any]) -> bool:
    labels = {
        str(label or "").strip()
        for label in aggregate.get("normalized_event_side_labels") or aggregate.get("event_side_labels") or ()
        if str(label or "").strip()
    }
    if len(labels) < 2:
        return False
    first_hit_count = len(
        {
            str(item or "").strip()
            for item in aggregate.get("first_hit_rcsdroad_ids") or ()
            if str(item or "").strip()
        }
    )
    if first_hit_count >= 2:
        return True
    return len(
        {
            str(assignment.get("road_id") or "").strip()
            for assignment in aggregate.get("role_assignments") or ()
            if isinstance(assignment, dict)
            and bool(assignment.get("first_hit"))
            and str(assignment.get("road_id") or "").strip()
        }
    ) >= 2


def _has_road_surface_fork_role_support(aggregate: dict[str, Any]) -> bool:
    assignment_roles = {
        str(assignment.get("role") or "").strip()
        for assignment in aggregate.get("role_assignments") or ()
        if isinstance(assignment, dict) and str(assignment.get("role") or "").strip()
    }
    if {"entering", "exiting"}.issubset(assignment_roles):
        return True
    return bool(_aggregate_ids(aggregate, "event_side_road_ids")) and bool(
        _aggregate_ids(aggregate, "axis_side_road_ids")
    )


def _entry_uses_relaxed_rcsd(entry: T04CandidateAuditEntry) -> bool:
    summary = entry.candidate_summary
    return str(summary.get("rcsd_decision_reason") or "").strip() in RELAXED_AGGREGATED_RCSD_REASONS


def _first_hit_ids(audit: dict[str, Any]) -> tuple[str, ...]:
    return _dedupe(audit.get("first_hit_rcsdroad_ids") or ())


def _aggregate_ids(aggregate: dict[str, Any], key: str) -> tuple[str, ...]:
    return _dedupe(aggregate.get(key) or ())


def _aggregate_labels(aggregate: dict[str, Any]) -> set[str]:
    return {
        str(label or "").strip()
        for label in aggregate.get("normalized_event_side_labels") or aggregate.get("event_side_labels") or ()
        if str(label or "").strip()
    }


def _local_unit_id_for_node(aggregate: dict[str, Any], node_id: str) -> str | None:
    expected = f":node:{node_id}"
    for unit_id in aggregate.get("member_unit_ids") or ():
        text = str(unit_id or "").strip()
        if text.endswith(expected):
            return text
    return None


def _relaxed_primary_aggregate(
    audit: dict[str, Any],
    *,
    allow_exact_primary_fallback: bool = False,
) -> dict[str, Any] | None:
    first_hit_ids = set(_first_hit_ids(audit))
    for aggregate in audit.get("aggregated_rcsd_units") or ():
        if not isinstance(aggregate, dict):
            continue
        decision_reason = str(aggregate.get("decision_reason") or "").strip()
        primary_node = str(aggregate.get("primary_node_id") or "").strip()
        if not primary_node:
            continue
        aggregate_road_ids = set(_aggregate_ids(aggregate, "road_ids"))
        if first_hit_ids and not (first_hit_ids & aggregate_road_ids):
            continue
        consistency_level = str(aggregate.get("consistency_level") or "").strip()
        if decision_reason in RELAXED_AGGREGATED_RCSD_REASONS:
            if consistency_level != "B":
                continue
            if len(_aggregate_labels(aggregate)) < 2:
                continue
            return aggregate
        if (
            allow_exact_primary_fallback
            and decision_reason == "role_mapping_exact_aggregated"
            and consistency_level == "A"
        ):
            return aggregate
    return None


def _junction_window_aggregate(audit: dict[str, Any]) -> dict[str, Any] | None:
    aggregate = _strong_aggregated_unit(audit)
    if aggregate is not None:
        return aggregate
    aggregate = _relaxed_primary_aggregate(audit, allow_exact_primary_fallback=True)
    if aggregate is not None:
        return aggregate
    first_hit_ids = set(_first_hit_ids(audit))
    for aggregate in audit.get("aggregated_rcsd_units") or ():
        if not isinstance(aggregate, dict):
            continue
        primary_node = str(aggregate.get("primary_node_id") or "").strip()
        if not primary_node:
            continue
        consistency_level = str(aggregate.get("consistency_level") or "").strip()
        if consistency_level not in {"A", "B"}:
            continue
        aggregate_road_ids = set(_aggregate_ids(aggregate, "road_ids"))
        if first_hit_ids and not (first_hit_ids & aggregate_road_ids):
            continue
        return aggregate
    return None


def _selected_surface_summary(event_unit: T04EventUnitResult) -> dict[str, Any]:
    return dict(event_unit.selected_evidence_summary or event_unit.selected_candidate_summary or {})


def _weak_structure_surface_window_candidate(summary: dict[str, Any]) -> bool:
    if str(summary.get("candidate_scope") or "") != ROAD_SURFACE_FORK_SCOPE:
        return False
    pair_middle_ratio = _as_float(summary.get("pair_middle_overlap_ratio")) or 0.0
    return pair_middle_ratio <= STRUCTURE_ONLY_SURFACE_WINDOW_MAX_PAIR_MIDDLE_RATIO


def _same_case_rcsd_claim_conflict(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    *,
    aggregate_id: str,
    required_node: str,
    primary_node: str,
    selected_roads: Iterable[Any],
    selected_nodes: Iterable[Any],
) -> dict[str, Any] | None:
    candidate_roads = set(_dedupe(selected_roads))
    candidate_nodes = set(_dedupe([required_node, primary_node, *list(selected_nodes)]))
    candidate_aggregate_ids = set(_dedupe([aggregate_id]))
    current_unit_id = event_unit.spec.event_unit_id
    for other in case_result.event_units:
        if other.spec.event_unit_id == current_unit_id:
            continue
        other_required = str(other.required_rcsd_node or "").strip()
        other_nodes = set(_dedupe([other_required, *list(other.selected_rcsdnode_ids or ())]))
        node_overlap = candidate_nodes & other_nodes
        if other_required and node_overlap:
            return {
                "skip_reason": "skipped_same_case_rcsd_claim_conflict",
                "conflict_type": "rcsd_node_claim",
                "conflict_unit_id": other.spec.event_unit_id,
                "conflict_required_rcsd_node": other_required,
                "overlap_rcsdnode_ids": sorted(node_overlap),
            }
        other_aggregate_ids = set(
            _dedupe([other.aggregated_rcsd_unit_id, *list(other.aggregated_rcsd_unit_ids or ())])
        )
        aggregate_overlap = candidate_aggregate_ids & other_aggregate_ids
        if aggregate_overlap:
            return {
                "skip_reason": "skipped_same_case_rcsd_claim_conflict",
                "conflict_type": "aggregated_rcsd_unit",
                "conflict_unit_id": other.spec.event_unit_id,
                "overlap_aggregated_rcsd_unit_ids": sorted(aggregate_overlap),
            }
        other_roads = set(_dedupe(other.selected_rcsdroad_ids or ()))
        road_overlap = candidate_roads & other_roads
        if road_overlap:
            overlap_ratio = len(road_overlap) / max(1, min(len(candidate_roads), len(other_roads)))
            if (
                len(road_overlap) >= SAME_CASE_RCSD_ROAD_OVERLAP_MIN_COUNT
                and overlap_ratio >= SAME_CASE_RCSD_ROAD_OVERLAP_MIN_RATIO
            ):
                return {
                    "skip_reason": "skipped_same_case_rcsd_claim_conflict",
                    "conflict_type": "selected_rcsdroad_overlap",
                    "conflict_unit_id": other.spec.event_unit_id,
                    "overlap_ratio": round(overlap_ratio, 3),
                    "overlap_rcsdroad_ids": sorted(road_overlap),
                }
    return None
