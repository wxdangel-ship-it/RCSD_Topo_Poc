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

def _semantic_anchor_distance_m(aggregate: dict[str, Any]) -> float | None:
    value = aggregate.get("semantic_anchor_distance_m")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

def _has_bilateral_event_side_support(
    aggregate: dict[str, Any],
    *,
    expanded_road_ids: set[str] | None = None,
) -> bool:
    """判断 aggregate 是否具有真双侧 (event_side) 支持。

    `expanded_road_ids` 为 `_expand_raw_roads_with_semantic_endpoints` 在
    `rcsd_selection.resolve_positive_rcsd_selection` 中扩展进 raw_roads 的
    semantic-endpoint 道路集合。这些道路与当前 road_surface_fork 的局部主证据
    无几何邻接关系，仅由语义路口扩展拉入；它们贡献的 `event_side` 标签**不**
    应被视作 road_surface_fork 主证据自身的双侧支持，否则会让
    `_promote_selected_surface_rcsd_junction_window` 误触发
    `partial_b_rcsd_signal AND preserve_surface_main_evidence` 早返回 gate，
    把本应进入 `no_main_evidence_with_rcsd_junction` 的 case（如 788824）
    回归为 `main_evidence_with_rcsdroad_fallback + no_rcsd_alignment`。

    口径：当 `expanded_road_ids` 非空时，**忽略** aggregate 已聚合的
    `normalized_event_side_labels`，直接从 `role_assignments` 重新统计
    `event_side` 非 center 标签，并排除 `road_id ∈ expanded_road_ids` 的
    assignment。当 `expanded_road_ids` 为空 / None 时保持既有行为。
    """
    expanded_set = {str(road_id) for road_id in (expanded_road_ids or ()) if str(road_id)}
    if expanded_set:
        labels: set[str] = set()
    else:
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
        if expanded_set and str(assignment.get("road_id") or "").strip() in expanded_set:
            continue
        label = str(assignment.get("side_label") or "").strip().lower()
        if label and label != "center":
            labels.add(label)
    return len(labels) >= 2

def _has_exact_published_semantic_window(
    audit: dict[str, Any],
    aggregate: dict[str, Any],
) -> bool:
    if str(audit.get("published_rcsd_selection_mode") or "").strip() != "aggregated_a_exact_required_node_unit":
        return False
    if str(aggregate.get("decision_reason") or "").strip() != "role_mapping_exact_aggregated":
        return False
    if str(aggregate.get("consistency_level") or "").strip() != "A":
        return False
    published_roads = _dedupe(audit.get("published_rcsdroad_ids") or ())
    published_nodes = _dedupe(audit.get("published_rcsdnode_ids") or ())
    if len(published_roads) < 3 or not published_nodes:
        return False
    required_node = str(aggregate.get("required_node_id") or "").strip()
    if required_node and required_node not in set(published_nodes):
        return False
    selected_assignments = tuple(
        assignment
        for assignment in (audit.get("selected_unit_role_assignments") or ())
        if isinstance(assignment, dict)
        and str(assignment.get("road_id") or "").strip() in set(published_roads)
    )
    return bool(str(audit.get("aggregated_rcsd_unit_id") or "").strip() and selected_assignments)

def _event_unit_key(case_id: str, event_unit_id: str) -> str:
    return f"{case_id}/{event_unit_id}"

def _same_point_signature(event_unit: T04EventUnitResult) -> str:
    return str((event_unit.selected_evidence_summary or {}).get("point_signature") or "").strip()

def _is_stronger_same_point_owner(event_unit: T04EventUnitResult) -> bool:
    if event_unit.selected_evidence_state == "none":
        return False
    summary = dict(event_unit.selected_evidence_summary or {})
    evidence_source = str(event_unit.evidence_source or "").strip()
    candidate_scope = str(summary.get("candidate_scope") or "").strip()
    upper_kind = str(summary.get("upper_evidence_kind") or "").strip()
    return bool(
        evidence_source != "road_surface_fork"
        or candidate_scope == "divstrip_component"
        or upper_kind == "divstrip"
        or event_unit.required_rcsd_node
    )
def _weak_duplicate_point_surface_candidate(event_unit: T04EventUnitResult) -> bool:
    if event_unit.evidence_source != "road_surface_fork":
        return False
    if event_unit.required_rcsd_node:
        return False
    summary = dict(event_unit.selected_evidence_summary or {})
    if str(summary.get("candidate_scope") or "").strip() != "road_surface_fork":
        return False
    interpretation = event_unit.interpretation.to_audit_summary()
    decision = interpretation.get("evidence_decision")
    if not isinstance(decision, dict):
        decision = {}
    risk_signals = {
        str(item).strip()
        for item in interpretation.get("risk_signals") or ()
        if str(item).strip()
    }
    reason = str(
        event_unit.positive_rcsd_present_reason
        or (event_unit.positive_rcsd_audit or {}).get("positive_rcsd_present_reason")
        or ""
    ).strip()
    return bool(
        decision.get("fallback_used") is True
        or "fallback_to_weak_evidence" in risk_signals
        or reason == "road_surface_fork_partial_rcsd_support_only"
    )

def _duplicate_same_point_owner(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
) -> T04EventUnitResult | None:
    if not _weak_duplicate_point_surface_candidate(event_unit):
        return None
    point_signature = _same_point_signature(event_unit)
    if not point_signature:
        return None
    case_id = case_result.case_spec.case_id
    target_key = _event_unit_key(case_id, event_unit.spec.event_unit_id)
    conflict_component = (event_unit.conflict_audit or {}).get("same_case_evidence_component")
    if not isinstance(conflict_component, dict):
        return None
    if "hard_same_point_signature" not in {
        str(item).strip() for item in conflict_component.get("relations") or ()
    }:
        return None
    units_by_key = {
        _event_unit_key(case_id, unit.spec.event_unit_id): unit
        for unit in case_result.event_units
    }
    for edge in conflict_component.get("edge_details") or ():
        if not isinstance(edge, dict):
            continue
        relations = {str(item).strip() for item in edge.get("relations") or ()}
        if "hard_same_point_signature" not in relations:
            continue
        lhs = str(edge.get("lhs") or "").strip()
        rhs = str(edge.get("rhs") or "").strip()
        if target_key not in {lhs, rhs}:
            continue
        owner = units_by_key.get(rhs if lhs == target_key else lhs)
        if (
            owner is not None
            and _same_point_signature(owner) == point_signature
            and _is_stronger_same_point_owner(owner)
        ):
            return owner
    return None

def _direct_first_hit_fallback_roads(
    first_hit: tuple[str, ...],
    *,
    allowed_roads: tuple[str, ...] = (),
) -> tuple[str, ...]:
    allowed = set(_dedupe(allowed_roads))
    return _dedupe(road_id for road_id in first_hit if not allowed or road_id in allowed)

def _score_doc(score: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in (
        "road_id",
        "road_support_count",
        "unit_support_count",
        "support_mode",
        "support_scope",
    ):
        if key in score:
            result[key] = score.get(key)
    if score.get("support_branch_ids"):
        result["support_branch_ids"] = list(score.get("support_branch_ids") or ())
    for key in (
        "mean_supported_road_distance_m",
        "max_supported_road_distance_m",
        "min_road_distance_m",
        "max_unit_distance_m",
        "support_distance_threshold_m",
        "unit_distance_threshold_m",
        "max_direction_delta_deg",
    ):
        value = score.get(key)
        if value is not None:
            result[key] = round(float(value), 6)
    return result

def _direct_surface_fallback_roads(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
    first_hit: tuple[str, ...],
) -> tuple[tuple[str, ...], dict[str, Any]]:
    direct_first_hit = _direct_first_hit_fallback_roads(first_hit)
    score = _score_single_rcsdroad(case_result, event_unit)
    if score is None:
        return direct_first_hit, {
            "fallback_selection_mode": "direct_first_hit",
            "direct_first_hit_rcsdroad_ids": list(direct_first_hit),
        }
    road_id = str(score.get("road_id") or "").strip()
    if not road_id:
        return direct_first_hit, {
            "fallback_selection_mode": "direct_first_hit",
            "direct_first_hit_rcsdroad_ids": list(direct_first_hit),
        }
    mode = (
        "direct_first_hit_representative_confirmed"
        if road_id in set(direct_first_hit)
        else "representative_supported_single_rcsdroad"
    )
    return (road_id,), {
        "fallback_selection_mode": mode,
        "direct_first_hit_rcsdroad_ids": list(direct_first_hit),
        "representative_supported_rcsdroad_ids": [road_id],
        "representative_supported_score": _score_doc(score),
    }

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

def _published_member_unit_ids_for_selection(
    audit: dict[str, Any],
    *,
    local_unit_id: str | None,
    required_node: str | None,
) -> tuple[str, ...]:
    local_unit_text = str(local_unit_id or "").strip()
    if local_unit_text:
        return (local_unit_text,)
    required_node_text = str(required_node or "").strip()
    if not required_node_text:
        return ()
    for unit in audit.get("local_rcsd_units") or ():
        if not isinstance(unit, dict):
            continue
        unit_id = str(unit.get("unit_id") or "").strip()
        node_id = str(unit.get("node_id") or "").strip()
        if unit_id and node_id == required_node_text:
            return (unit_id,)
    return ()

def _with_unique_positive_rcsd_publish(
    audit: dict[str, Any],
    *,
    selected_roads: tuple[str, ...],
    selected_nodes: tuple[str, ...],
    local_unit_id: str | None,
    required_node: str | None,
    publish_mode: str,
) -> dict[str, Any]:
    updated = dict(audit)
    updated.update(
        {
            "published_rcsdroad_ids": list(_dedupe(selected_roads)),
            "published_rcsdnode_ids": list(_dedupe(selected_nodes)),
            "published_member_unit_ids": list(
                _published_member_unit_ids_for_selection(
                    audit,
                    local_unit_id=local_unit_id,
                    required_node=required_node,
                )
            ),
            "published_rcsd_selection_mode": publish_mode,
        }
    )
    return updated

def _downgrade_far_surface_rcsd_to_swsd_window(
    event_unit: T04EventUnitResult,
    entry: T04CandidateAuditEntry,
    *,
    case_id: str,
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
            "rcsd_consistency_result": "none",
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
    updated_entry = replace_step4_pre_arbiter_candidate(
        entry,
        candidate_summary=dict(summary),
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source="road_surface_fork",
        position_source=SWSD_JUNCTION_WINDOW_POSITION_SOURCE,
        rcsd_consistency_result="none",
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
    updated = replace_step4_pre_arbiter_candidate(
        event_unit,
        review_state="STEP4_REVIEW",
        review_reasons=review_reasons,
        evidence_source="road_surface_fork",
        position_source=SWSD_JUNCTION_WINDOW_POSITION_SOURCE,
        rcsd_consistency_result="none",
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
    return (
            append_dual_write_candidate(
                updated,
                case_id=case_id,
                source_stage="promotion",
                source_audit_blob=detail,
                replacement_reason=SWSD_JUNCTION_WINDOW_REASON,
        ),
        detail,
    )
