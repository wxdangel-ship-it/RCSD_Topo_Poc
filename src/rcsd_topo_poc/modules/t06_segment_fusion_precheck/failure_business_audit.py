from __future__ import annotations

from typing import Any

from .buffer_only_probe import BufferOnlyProbeResult


def buffer_only_probe_row(
    *,
    segment_id: str,
    pair_nodes: list[str],
    original_rcsd_pair_nodes: list[str],
    probe_result: BufferOnlyProbeResult,
    failure_business_category: str,
    source_reject_reason: str,
) -> dict[str, Any]:
    return {
        "swsd_segment_id": segment_id,
        "probe_status": "completed",
        "buffer_only_candidate_status": probe_result.status,
        "failure_business_category": failure_business_category,
        "original_pair_nodes": pair_nodes,
        "original_rcsd_pair_nodes": original_rcsd_pair_nodes,
        "candidate_rcsd_pair_node_sets": probe_result.candidate_pair_sets,
        "candidate_score": probe_result.candidate_score,
        "geometry_overlap_ratio": probe_result.geometry_overlap_ratio,
        "directionality_score": probe_result.directionality_score,
        "connectivity_score": probe_result.connectivity_score,
        "shape_similarity_score": probe_result.shape_similarity_score,
        "candidate_rcsd_road_ids": probe_result.candidate_road_ids,
        "candidate_rcsd_node_ids": probe_result.candidate_node_ids,
        "candidate_component_count": probe_result.candidate_component_count,
        "manual_review_required": probe_result.manual_review_required,
        "repair_recommendation": probe_result.repair_recommendation,
        "source_reject_reason": source_reject_reason,
        "notes": probe_result.notes,
    }


def repair_candidate_row(
    *,
    segment_id: str,
    pair_nodes: list[str],
    original_rcsd_pair_nodes: list[str],
    probe_result: BufferOnlyProbeResult,
    failure_business_category: str,
    source_reject_reason: str,
    pair_anchor_diagnostic: Any | None = None,
) -> dict[str, Any]:
    return {
        "swsd_segment_id": segment_id,
        "original_pair_nodes": pair_nodes,
        "original_rcsd_pair_nodes": original_rcsd_pair_nodes,
        "candidate_rcsd_pair_node_sets": probe_result.candidate_pair_sets,
        "candidate_score": probe_result.candidate_score,
        "geometry_overlap_ratio": probe_result.geometry_overlap_ratio,
        "directionality_score": probe_result.directionality_score,
        "connectivity_score": probe_result.connectivity_score,
        "shape_similarity_score": probe_result.shape_similarity_score,
        "manual_review_required": probe_result.manual_review_required,
        "repair_recommendation": probe_result.repair_recommendation,
        "buffer_only_candidate_status": probe_result.status,
        "failure_business_category": failure_business_category,
        "pair_anchor_error_swsd_nodes": getattr(pair_anchor_diagnostic, "error_swsd_pair_nodes", []),
        "pair_anchor_error_original_rcsd_nodes": getattr(pair_anchor_diagnostic, "error_original_rcsd_nodes", []),
        "pair_anchor_error_candidate_rcsd_nodes": getattr(pair_anchor_diagnostic, "error_candidate_rcsd_nodes", []),
        "pair_anchor_endpoint_cluster_nodes": getattr(pair_anchor_diagnostic, "endpoint_cluster_nodes", []),
        "pair_anchor_bridge_road_ids": getattr(pair_anchor_diagnostic, "endpoint_bridge_road_ids", []),
        "pair_anchor_bridge_length_m": getattr(pair_anchor_diagnostic, "endpoint_bridge_length_m", 0.0),
        "pair_anchor_diagnostic_source": getattr(pair_anchor_diagnostic, "diagnostic_source", ""),
        "pair_anchor_diagnostic_reason": getattr(pair_anchor_diagnostic, "diagnostic_reason", ""),
        "candidate_rcsd_road_ids": probe_result.candidate_road_ids,
        "candidate_rcsd_node_ids": probe_result.candidate_node_ids,
        "source_reject_reason": source_reject_reason,
    }


def failure_business_audit_row(
    *,
    segment_id: str,
    segment_outcome: str,
    reject_reason: str,
    scenario_type: str,
    failure_business_category: str,
    pair_nodes: list[str],
    junc_nodes: list[str],
    relation: Any,
    junc_audit: dict[str, Any] | None,
    probe_result: BufferOnlyProbeResult | None,
    root_cause_category: str | None,
    original_rcsd_pair_nodes: list[str] | None = None,
    pair_anchor_error_swsd_nodes: list[str] | None = None,
    pair_anchor_error_original_rcsd_nodes: list[str] | None = None,
    pair_anchor_error_candidate_rcsd_nodes: list[str] | None = None,
    pair_anchor_endpoint_cluster_nodes: list[list[str]] | None = None,
    pair_anchor_bridge_road_ids: list[str] | None = None,
    pair_anchor_bridge_length_m: float = 0.0,
    pair_anchor_diagnostic_source: str = "",
    pair_anchor_diagnostic_reason: str = "",
    adaptive_buffer_distance_m: float | None = None,
    adaptive_buffer_source_reason: str = "",
    adaptive_buffer_recommendation: str = "single_graph_first_longitudinal_retry",
) -> dict[str, Any]:
    junc_audit = junc_audit or {}
    candidate_pair_sets = probe_result.candidate_pair_sets if probe_result is not None else []
    original_pair = original_rcsd_pair_nodes if original_rcsd_pair_nodes is not None else relation.rcsd_pair_nodes
    manual_review_required = probe_result.manual_review_required if probe_result is not None else False
    repair_recommendation = probe_result.repair_recommendation if probe_result is not None else ""
    if (
        segment_outcome == "replaceable"
        and failure_business_category == "pair_anchor_mismatch"
        and reject_reason in {"missing_pair_relation", "invalid_pair_relation_status", "invalid_pair_base_id"}
        and repair_recommendation == "manual_review_required"
    ):
        manual_review_required = False
        repair_recommendation = "side_preserving_missing_pair_anchor_completion"
    if segment_outcome == "replaceable" and adaptive_buffer_distance_m is not None:
        manual_review_required = False
        repair_recommendation = adaptive_buffer_recommendation
    if segment_outcome == "rejected" and failure_business_category == "directionality_mismatch_fixable":
        manual_review_required = True
        repair_recommendation = "upstream_anchor_or_segment_grouping_required"
    auto_fix_candidate = segment_outcome == "replaceable" and (
        bool(junc_audit.get("dropped_junc_nodes"))
        or repair_recommendation
        in {
            "high_confidence_pair_anchor_candidate",
            "side_preserving_missing_pair_anchor_completion",
            "single_graph_first_longitudinal_retry",
            "adaptive_high_grade_single_buffer_retry",
            "adaptive_high_grade_dual_buffer_retry",
        }
    )
    return {
        "swsd_segment_id": segment_id,
        "segment_outcome": segment_outcome,
        "reject_reason": reject_reason,
        "scenario_type": scenario_type,
        "buffer_only_candidate_status": probe_result.status if probe_result is not None else "",
        "failure_business_category": failure_business_category,
        "auto_fix_candidate": auto_fix_candidate,
        "manual_review_required": manual_review_required,
        "repair_recommendation": repair_recommendation,
        "adaptive_buffer_status": "applied" if adaptive_buffer_distance_m is not None else "not_applied",
        "adaptive_buffer_distance_m": adaptive_buffer_distance_m,
        "adaptive_buffer_source_reason": adaptive_buffer_source_reason,
        "pair_anchor_error_swsd_nodes": pair_anchor_error_swsd_nodes or [],
        "pair_anchor_error_original_rcsd_nodes": pair_anchor_error_original_rcsd_nodes or [],
        "pair_anchor_error_candidate_rcsd_nodes": pair_anchor_error_candidate_rcsd_nodes or [],
        "pair_anchor_endpoint_cluster_nodes": pair_anchor_endpoint_cluster_nodes or [],
        "pair_anchor_bridge_road_ids": pair_anchor_bridge_road_ids or [],
        "pair_anchor_bridge_length_m": round(float(pair_anchor_bridge_length_m), 3),
        "pair_anchor_diagnostic_source": pair_anchor_diagnostic_source,
        "pair_anchor_diagnostic_reason": pair_anchor_diagnostic_reason,
        "swsd_pair_nodes": pair_nodes,
        "swsd_junc_nodes": junc_nodes,
        "original_rcsd_pair_nodes": original_pair,
        "rcsd_pair_nodes": relation.rcsd_pair_nodes,
        "rcsd_junc_nodes": relation.rcsd_junc_nodes,
        "required_rcsd_nodes": relation.rcsd_pair_nodes,
        "optional_junc_nodes": junc_audit.get("optional_junc_nodes", []),
        "optional_junc_rcsd_nodes": junc_audit.get("optional_junc_rcsd_nodes", []),
        "dropped_junc_nodes": junc_audit.get("dropped_junc_nodes", relation.failed_junc_nodes or []),
        "dropped_junc_relation_nodes": junc_audit.get("dropped_junc_relation_nodes", []),
        "lost_attach_road_ids": junc_audit.get("lost_attach_road_ids", []),
        "promoted_attach_road_ids": junc_audit.get("promoted_attach_road_ids", []),
        "blocked_attach_road_ids": junc_audit.get("blocked_attach_road_ids", []),
        "attach_promotion_status": junc_audit.get("attach_promotion_status", "not_applicable"),
        "attach_promotion_reason": junc_audit.get("attach_promotion_reason", ""),
        "isolated_attach_loss_count": junc_audit.get("isolated_attach_loss_count", len(relation.failed_junc_nodes or [])),
        "junc_attach_loss_reason": junc_audit.get("junc_attach_loss_reason", ""),
        "candidate_rcsd_pair_node_sets": candidate_pair_sets,
        "candidate_score": probe_result.candidate_score if probe_result is not None else 0.0,
        "geometry_overlap_ratio": probe_result.geometry_overlap_ratio if probe_result is not None else 0.0,
        "directionality_score": probe_result.directionality_score if probe_result is not None else 0.0,
        "connectivity_score": probe_result.connectivity_score if probe_result is not None else 0.0,
        "shape_similarity_score": probe_result.shape_similarity_score if probe_result is not None else 0.0,
        "root_cause_category": root_cause_category,
        "upstream_issue_owner": upstream_issue_owner(
            failure_business_category,
            segment_outcome=segment_outcome,
            reject_reason=reject_reason,
            root_cause_category=root_cause_category,
        ),
    }


def failure_business_category(
    reason: str,
    *,
    probe_result: BufferOnlyProbeResult,
    relation: Any,
    junc_audit: dict[str, Any] | None,
    diagnostic: dict[str, Any] | None,
) -> str:
    if reason == "rcsd_not_bidirectional_for_swsd_dual":
        return "directionality_mismatch_fixable"
    if reason == "rcsd_directed_path_missing":
        if probe_result.status == "ambiguous_corridor":
            return "multi_anchor_ambiguous"
        if probe_result.status == "corridor_found_with_anchor_mismatch":
            return "pair_anchor_mismatch"
        return "directionality_mismatch_fixable"
    if junc_audit and junc_audit.get("dropped_junc_nodes"):
        return junc_failure_business_category(junc_audit)
    if reason in {"missing_pair_relation", "invalid_pair_relation_status", "invalid_pair_base_id", "rcsd_pair_nodes_not_distinct"}:
        if probe_result.status in {"corridor_found", "corridor_found_with_anchor_mismatch", "ambiguous_corridor"}:
            return "pair_anchor_mismatch" if probe_result.status != "ambiguous_corridor" else "multi_anchor_ambiguous"
        return "rcsd_data_absent_or_insufficient"
    if probe_result.status == "no_corridor":
        return "rcsd_data_absent_or_insufficient"
    if probe_result.status == "ambiguous_corridor":
        return "multi_anchor_ambiguous"
    if probe_result.status == "corridor_found_with_anchor_mismatch":
        return "pair_anchor_mismatch"
    if reason in {
        "retained_geometry_outside_swsd_buffer_scope",
        "swsd_geometry_not_covered_by_retained_rcsd",
        "retained_geometry_outside_swsd_visual_consistency_scope",
        "swsd_visual_continuity_not_covered_by_retained_rcsd",
    }:
        return "geometry_shape_mismatch"
    root_cause = (diagnostic or {}).get("root_cause_category")
    if root_cause in {"full_rcsd_graph_required_nodes_disconnected", "buffer_candidate_required_nodes_disconnected", "full_rcsd_graph_missing_required_nodes"}:
        return "rcsd_graph_break_inside_buffer"
    if probe_result.status == "corridor_found_with_topology_issue":
        return "rcsd_graph_break_inside_buffer"
    return "pair_anchor_mismatch" if relation.rcsd_pair_nodes else "rcsd_data_absent_or_insufficient"


def junc_failure_business_category(junc_audit: dict[str, Any]) -> str:
    reason = str(junc_audit.get("junc_attach_loss_reason") or "")
    if "junc_relation_missing_or_invalid" in reason:
        return "junc_required_blocked"
    if "isolated_optional_junc_pruned" in reason:
        return "isolated_attach_loss_acceptable"
    return "junc_required_blocked"


def scenario_type(failure_business_category: str) -> str:
    return "A" if failure_business_category in {"rcsd_data_absent_or_insufficient", "evidence_slice_incomplete"} else "B"


def should_emit_repair_candidate(probe_result: BufferOnlyProbeResult) -> bool:
    return bool(probe_result.candidate_pair_sets) and probe_result.status != "no_corridor"


def upstream_issue_owner(
    failure_business_category: str,
    *,
    segment_outcome: str = "",
    reject_reason: str = "",
    root_cause_category: str | None = None,
) -> str:
    if failure_business_category in {"pair_anchor_mismatch", "multi_anchor_ambiguous", "junc_required_blocked"}:
        return "T05"
    if failure_business_category == "directionality_mismatch_fixable" and segment_outcome == "rejected":
        return "T03/T04/T05_or_T06_group_replacement"
    if failure_business_category == "rcsd_graph_break_inside_buffer":
        return "T04/T05/RCSDRoad"
    if failure_business_category == "rcsd_data_absent_or_insufficient":
        return "RCSD/evidence_slice"
    return "T06"


def business_audit_stats(
    failure_business_audit_rows: list[dict[str, Any]],
    replaceable_rows: list[dict[str, Any]],
    *,
    input_count: int,
) -> dict[str, Any]:
    props = [dict(row.get("properties") or {}) for row in failure_business_audit_rows]
    scenario_a = [item for item in props if item.get("scenario_type") == "A"]
    scenario_b_auto = [item for item in props if item.get("auto_fix_candidate")]
    scenario_b_manual = [item for item in props if item.get("manual_review_required")]
    pair_anchor = [item for item in props if item.get("failure_business_category") in {"pair_anchor_mismatch", "multi_anchor_ambiguous"}]
    pair_anchor_located = [item for item in pair_anchor if item.get("pair_anchor_error_swsd_nodes")]
    junc_blocked = [item for item in props if item.get("failure_business_category") in {"junc_required_blocked", "isolated_attach_loss_acceptable"}]
    rcsd_quality = [item for item in props if item.get("failure_business_category") == "rcsd_graph_break_inside_buffer"]
    manual_upper_bound = len(replaceable_rows) + len({str(item.get("swsd_segment_id")) for item in scenario_b_manual if item.get("swsd_segment_id")})
    return {
        "current_success_replacement_count": len(replaceable_rows),
        "scenario_a_count": len(scenario_a),
        "scenario_b_auto_lift_count": len(scenario_b_auto),
        "scenario_b_manual_review_count": len(scenario_b_manual),
        "pair_anchor_suspected_error_count": len(pair_anchor),
        "pair_anchor_error_located_count": len(pair_anchor_located),
        "junc_required_blocked_count": len(junc_blocked),
        "rcsdroad_quality_issue_count": len(rcsd_quality),
        "automatic_lift_estimated_replaceable_count": len(replaceable_rows),
        "automatic_lift_estimated_replaceable_rate": _safe_ratio(len(replaceable_rows), input_count),
        "manual_repair_theoretical_replaceable_upper_bound_count": min(input_count, manual_upper_bound),
        "manual_repair_theoretical_replaceable_upper_bound_rate": _safe_ratio(min(input_count, manual_upper_bound), input_count),
        "business_audit_stats": {
            "scenario_a": _business_scope_stats(scenario_a),
            "scenario_b_auto_lift": _business_scope_stats(scenario_b_auto),
            "scenario_b_manual_review": _business_scope_stats(scenario_b_manual),
            "pair_anchor_suspected_error": _business_scope_stats(pair_anchor),
            "pair_anchor_error_located": _business_scope_stats(pair_anchor_located),
            "junc_required_blocked": _business_scope_stats(junc_blocked),
            "rcsdroad_quality_issue": _business_scope_stats(rcsd_quality),
        },
    }


def _business_scope_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    swsd_segments: set[str] = set()
    swsd_nodes: set[str] = set()
    rcsd_nodes: set[str] = set()
    for row in rows:
        segment_id = row.get("swsd_segment_id")
        if segment_id:
            swsd_segments.add(str(segment_id))
        swsd_nodes.update(str(item) for item in (row.get("swsd_pair_nodes") or []))
        swsd_nodes.update(str(item) for item in (row.get("swsd_junc_nodes") or []))
        rcsd_nodes.update(str(item) for item in (row.get("original_rcsd_pair_nodes") or []))
        rcsd_nodes.update(str(item) for item in (row.get("rcsd_junc_nodes") or []))
        rcsd_nodes.update(str(item) for item in (row.get("optional_junc_rcsd_nodes") or []))
        for pair_set in row.get("candidate_rcsd_pair_node_sets") or []:
            rcsd_nodes.update(str(item) for item in pair_set)
    return {
        "occurrence_count": len(rows),
        "unique_swsd_segment_count": len(swsd_segments),
        "unique_swsd_semantic_node_count": len(swsd_nodes),
        "unique_rcsd_semantic_node_count": len(rcsd_nodes),
    }


def _safe_ratio(numerator: int, denominator: int) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0
