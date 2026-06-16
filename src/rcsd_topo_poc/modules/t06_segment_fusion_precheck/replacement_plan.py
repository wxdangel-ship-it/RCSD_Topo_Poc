from __future__ import annotations

from collections import defaultdict
from typing import Any

from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order
from .schemas import feature


def build_replacement_plan_rows(
    *,
    replaceable_rows: list[dict[str, Any]],
    special_group_rows: list[dict[str, Any]],
    group_replacement_audit_rows: list[dict[str, Any]],
    rcsd_roads: list[dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> list[dict[str, Any]]:
    rcsd_road_by_id = _index_by_id(rcsd_roads)
    rows: list[dict[str, Any]] = []
    rows.extend(_standard_plan_rows(replaceable_rows))
    rows.extend(
        _group_replacement_plan_rows(
            group_replacement_audit_rows,
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        )
    )
    rows.extend(_special_group_plan_rows(special_group_rows))
    return rows


def build_problem_registry_rows(
    *,
    rejected_rows: list[dict[str, Any]],
    failure_business_audit_rows: list[dict[str, Any]],
    replacement_plan_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    covered_by_segment = _covered_plan_scopes_by_segment(replacement_plan_rows)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for audit in failure_business_audit_rows:
        props = dict(audit.get("properties") or {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if not segment_id:
            continue
        seen.add(segment_id)
        status = _problem_status(props, covered_by_segment.get(segment_id, []))
        owner = _problem_owner(props, status)
        rows.append(
            feature(
                {
                    "problem_id": f"problem:{segment_id}",
                    "swsd_segment_id": segment_id,
                    "problem_status": status,
                    "root_cause_category": props.get("root_cause_category"),
                    "failure_business_category": props.get("failure_business_category"),
                    "reject_reason": props.get("reject_reason"),
                    "upstream_issue_owner": owner,
                    "recommended_module": _recommended_module(owner),
                    "feedback_action": _feedback_action(status, owner),
                    "replan_trigger": _replan_trigger(status),
                    "swsd_pair_nodes": _parse_list(props.get("swsd_pair_nodes")),
                    "swsd_junc_nodes": _parse_list(props.get("swsd_junc_nodes")),
                    "rcsd_pair_nodes": _parse_list(props.get("rcsd_pair_nodes")),
                    "candidate_rcsd_pair_node_sets": props.get("candidate_rcsd_pair_node_sets") or [],
                    "pair_anchor_error_swsd_nodes": _parse_list(props.get("pair_anchor_error_swsd_nodes")),
                    "pair_anchor_error_original_rcsd_nodes": _parse_list(props.get("pair_anchor_error_original_rcsd_nodes")),
                    "pair_anchor_error_candidate_rcsd_nodes": _parse_list(props.get("pair_anchor_error_candidate_rcsd_nodes")),
                    "pair_anchor_endpoint_cluster_nodes": props.get("pair_anchor_endpoint_cluster_nodes") or [],
                    "pair_anchor_bridge_road_ids": _parse_list(props.get("pair_anchor_bridge_road_ids")),
                    "pair_anchor_bridge_length_m": props.get("pair_anchor_bridge_length_m"),
                    "pair_anchor_diagnostic_source": props.get("pair_anchor_diagnostic_source"),
                    "pair_anchor_diagnostic_reason": props.get("pair_anchor_diagnostic_reason"),
                    "evidence_artifacts": ["t06_rcsd_segment_failure_business_audit", *covered_by_segment.get(segment_id, [])],
                    "manual_review_required": _manual_review_required(status, props),
                    "notes": _problem_notes(status, covered_by_segment.get(segment_id, [])),
                },
                audit.get("geometry"),
            )
        )

    for rejected in rejected_rows:
        props = dict(rejected.get("properties") or {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if not segment_id or segment_id in seen:
            continue
        scopes = covered_by_segment.get(segment_id, [])
        status = "covered_by_replacement_plan" if scopes else "requires_upstream_iteration"
        owner = str(props.get("upstream_issue_owner") or _default_owner_for_reject(props.get("reject_reason")))
        rows.append(
            feature(
                {
                    "problem_id": f"problem:{segment_id}",
                    "swsd_segment_id": segment_id,
                    "problem_status": status,
                    "root_cause_category": props.get("root_cause_category"),
                    "failure_business_category": "",
                    "reject_reason": props.get("reject_reason"),
                    "upstream_issue_owner": owner,
                    "recommended_module": _recommended_module(owner),
                    "feedback_action": _feedback_action(status, owner),
                    "replan_trigger": _replan_trigger(status),
                    "swsd_pair_nodes": _parse_list(props.get("failed_pair_nodes")),
                    "swsd_junc_nodes": _parse_list(props.get("failed_junc_nodes")),
                    "rcsd_pair_nodes": [],
                    "candidate_rcsd_pair_node_sets": [],
                    "pair_anchor_error_swsd_nodes": [],
                    "pair_anchor_error_original_rcsd_nodes": [],
                    "pair_anchor_error_candidate_rcsd_nodes": [],
                    "pair_anchor_endpoint_cluster_nodes": [],
                    "pair_anchor_bridge_road_ids": [],
                    "pair_anchor_bridge_length_m": "",
                    "pair_anchor_diagnostic_source": "",
                    "pair_anchor_diagnostic_reason": "",
                    "evidence_artifacts": ["t06_rcsd_segment_rejected", *scopes],
                    "manual_review_required": status == "requires_upstream_iteration",
                    "notes": _problem_notes(status, scopes),
                },
                rejected.get("geometry"),
            )
        )

    return rows


def _standard_plan_rows(replaceable_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in replaceable_rows:
        props = dict(row.get("properties") or {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if not segment_id:
            continue
        strategy = str(props.get("replacement_strategy") or "buffer_segment_extraction")
        rows.append(
            feature(
                {
                    "replacement_plan_id": f"standard:{segment_id}",
                    "swsd_segment_id": segment_id,
                    "plan_status": "ready",
                    "execution_action": "replace",
                    "execution_scope": "standard_segment",
                    "plan_owner": "T06_STEP2",
                    "upstream_owner": "T05_relation_consumed",
                    "source_artifact": "t06_rcsd_segment_replaceable",
                    "source_reason": strategy,
                    "replacement_strategy": strategy,
                    "special_junction_id": "",
                    "special_junction_type": "",
                    "swsd_sgrade": props.get("swsd_sgrade"),
                    "swsd_directionality": props.get("swsd_directionality"),
                    "swsd_pair_nodes": _parse_list(props.get("swsd_pair_nodes")),
                    "swsd_junc_nodes": _parse_list(props.get("swsd_junc_nodes")),
                    "junc_kind2_exempt_nodes": _parse_list(props.get("junc_kind2_exempt_nodes")),
                    "detached_junc_nodes": _parse_list(props.get("detached_junc_nodes")),
                    "rcsd_pair_nodes": _parse_list(props.get("rcsd_pair_nodes")),
                    "rcsd_junc_nodes": _parse_list(props.get("rcsd_junc_nodes")),
                    "rcsd_road_ids": _parse_list(props.get("rcsd_road_ids")),
                    "retained_node_ids": _parse_list(props.get("retained_node_ids")),
                    "group_segment_ids": [segment_id],
                    "source_segment_ids": [segment_id],
                    "buffer_distances_m": _parse_float_list(props.get("adaptive_buffer_distance_m")),
                    "risk_flags": [],
                    "notes": "standard Step2 replaceable segment",
                },
                row.get("geometry"),
            )
        )
    return rows


def _group_replacement_plan_rows(
    group_rows: list[dict[str, Any]],
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in group_rows:
        props = dict(row.get("properties") or {})
        if props.get("group_probe_status") != "passed":
            continue
        if props.get("group_probe_repair_owner") != "T06_path_corridor_group_replacement":
            continue
        segment_id = _safe_id(props.get("swsd_segment_id"))
        group_segment_ids = _parse_list(props.get("path_corridor_group_segment_ids"))
        rcsd_road_ids = _parse_list(props.get("group_probe_rcsd_road_ids"))
        if not segment_id or not group_segment_ids or not rcsd_road_ids:
            continue
        rows.append(
            feature(
                {
                    "replacement_plan_id": f"group_path_corridor:{segment_id}",
                    "swsd_segment_id": segment_id,
                    "plan_status": "ready",
                    "execution_action": "replace",
                    "execution_scope": "path_corridor_group",
                    "plan_owner": "T06_STEP2",
                    "upstream_owner": "T03/T04/T05_feedback_candidate",
                    "source_artifact": "t06_segment_group_replacement_audit",
                    "source_reason": props.get("group_probe_reason"),
                    "replacement_strategy": "path_corridor_group_replacement",
                    "special_junction_id": "",
                    "special_junction_type": "",
                    "swsd_sgrade": props.get("swsd_sgrade"),
                    "swsd_directionality": props.get("swsd_directionality"),
                    "swsd_pair_nodes": _parse_list(props.get("swsd_pair_nodes")),
                    "swsd_junc_nodes": _parse_list(props.get("swsd_junc_nodes")),
                    "junc_kind2_exempt_nodes": [],
                    "detached_junc_nodes": [],
                    "rcsd_pair_nodes": _parse_list(props.get("rcsd_pair_nodes")),
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": rcsd_road_ids,
                    "retained_node_ids": _canonical_road_endpoint_ids(rcsd_road_ids, rcsd_road_by_id, rcsd_node_canonicalizer),
                    "group_segment_ids": group_segment_ids,
                    "source_segment_ids": [segment_id],
                    "buffer_distances_m": _parse_float_list(props.get("group_probe_buffer_distance_m")),
                    "risk_flags": ["group_path_corridor_replacement"],
                    "notes": props.get("notes") or "path-corridor group replacement plan",
                },
                row.get("geometry"),
            )
        )
    return rows


def _special_group_plan_rows(special_group_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in special_group_rows:
        props = dict(row.get("properties") or {})
        if props.get("gate_status") != "passed":
            continue
        junction_id = _safe_id(props.get("special_junction_id"))
        if not junction_id:
            continue
        rows.append(
            feature(
                {
                    "replacement_plan_id": f"special_junction:{junction_id}",
                    "swsd_segment_id": "",
                    "plan_status": "ready",
                    "execution_action": "include_context",
                    "execution_scope": "special_junction_group_internal",
                    "plan_owner": "T06_STEP2",
                    "upstream_owner": "T05_relation_consumed",
                    "source_artifact": "t06_special_junction_group_audit",
                    "source_reason": props.get("notes"),
                    "replacement_strategy": "special_junction_group_internal",
                    "special_junction_id": junction_id,
                    "special_junction_type": props.get("special_junction_type"),
                    "swsd_sgrade": "",
                    "swsd_directionality": "",
                    "swsd_pair_nodes": [],
                    "swsd_junc_nodes": [],
                    "junc_kind2_exempt_nodes": [],
                    "detached_junc_nodes": [],
                    "rcsd_pair_nodes": [props.get("rcsd_junction_id")] if props.get("rcsd_junction_id") else [],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": _parse_list(props.get("rcsd_junction_road_ids")),
                    "retained_node_ids": _parse_list(props.get("rcsd_junction_node_ids")),
                    "group_segment_ids": _parse_list(props.get("associated_segment_ids")),
                    "source_segment_ids": _parse_list(props.get("replaceable_segment_ids")),
                    "buffer_distances_m": [],
                    "risk_flags": ["special_junction_group_internal"],
                    "notes": "passed special junction group internal RCSD entities",
                },
                row.get("geometry"),
            )
        )
    return rows


def _covered_plan_scopes_by_segment(replacement_plan_rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for row in replacement_plan_rows:
        props = dict(row.get("properties") or {})
        if props.get("plan_status") != "ready":
            continue
        scope = str(props.get("execution_scope") or "")
        if scope not in {"standard_segment", "path_corridor_group"}:
            continue
        artifact = str(props.get("source_artifact") or "t06_segment_replacement_plan")
        segment_ids = _parse_list(props.get("group_segment_ids")) or [_safe_id(props.get("swsd_segment_id"))]
        for segment_id in segment_ids:
            if segment_id:
                result[segment_id].append(artifact)
    return {segment_id: unique_preserve_order(scopes) for segment_id, scopes in result.items()}


def _problem_status(props: dict[str, Any], covered_scopes: list[str]) -> str:
    if covered_scopes:
        return "covered_by_replacement_plan"
    if _is_same_rcsd_junction_non_replaceable(props):
        return "accepted_non_replaceable"
    upstream_directionality_status = _upstream_directionality_status(props)
    if upstream_directionality_status:
        return upstream_directionality_status
    if props.get("segment_outcome") == "replaceable":
        return "resolved_in_step2_plan"
    if props.get("auto_fix_candidate"):
        return "resolved_in_step2_plan"
    return "requires_upstream_iteration"


def _is_same_rcsd_junction_non_replaceable(props: dict[str, Any]) -> bool:
    if props.get("reject_reason") != "rcsd_pair_nodes_not_distinct":
        return False
    rcsd_pair_nodes = unique_preserve_order(_parse_list(props.get("rcsd_pair_nodes")))
    return len(rcsd_pair_nodes) == 1


def _upstream_directionality_status(props: dict[str, Any]) -> str:
    if props.get("reject_reason") != "rcsd_not_bidirectional_for_swsd_dual":
        return ""
    if props.get("failure_business_category") != "directionality_mismatch_fixable":
        return ""
    if props.get("root_cause_category") != "full_rcsd_graph_one_direction_only":
        return ""
    return "requires_upstream_side_group_or_rcsd_directionality_review"


def _problem_owner(props: dict[str, Any], status: str) -> str:
    if status == "accepted_non_replaceable":
        return "T06"
    if status == "requires_upstream_side_group_or_rcsd_directionality_review":
        return "T03/T04/T05_or_RCSD_directionality_review"
    return str(props.get("upstream_issue_owner") or "")


def _recommended_module(owner: str) -> str:
    if owner == "T05":
        return "T03/T04/T05"
    if owner == "T03/T04/T05_or_T06_group_replacement":
        return "T03/T04/T05"
    if owner == "T04/T05/RCSDRoad":
        return "T04/T05/T08_or_data_qc"
    if owner == "T03/T04/T05_or_RCSD_directionality_review":
        return "T03/T04/T05_or_RCSD_source_review"
    if owner == "RCSD/evidence_slice":
        return "data_slice_or_RCSSD_source_review"
    return owner or "T06"


def _feedback_action(status: str, owner: str) -> str:
    if status == "accepted_non_replaceable":
        return "record_as_t06_non_replaceable_no_upstream_rerun"
    if status == "resolved_in_step2_plan":
        return "preserve_current_plan_and_monitor_for_upstream_formalization"
    if status == "covered_by_replacement_plan":
        return "preserve_current_plan_and_feed_evidence_to_upstream_iteration"
    if owner == "T05":
        return "rerun_T03_T04_T05_relation_or_junctionization"
    if owner == "T03/T04/T05_or_T06_group_replacement":
        return "evaluate_T03_T04_virtual_surface_then_T05_relation_before_T06_fallback"
    if owner == "T03/T04/T05_or_RCSD_directionality_review":
        return "evaluate_T03_T04_T05_side_grouping_before_rcsd_directionality_data_review"
    if owner == "T04/T05/RCSDRoad":
        return "audit_upstream_virtual_surface_and_data_quality"
    if owner == "RCSD/evidence_slice":
        return "exclude_confirmed_crop_or_request_complete_source_data"
    return "review_T06_business_rule_or_manual_audit"


def _replan_trigger(status: str) -> str:
    if status in {"requires_upstream_iteration", "requires_upstream_side_group_or_rcsd_directionality_review"}:
        return "upstream_module_rerun_required"
    if status == "covered_by_replacement_plan":
        return "no_current_rerun_required_feedback_recorded"
    return "no_current_rerun_required"


def _problem_notes(status: str, scopes: list[str]) -> str:
    if status == "covered_by_replacement_plan":
        return "current Step2 replacement plan covers the segment; keep as regression guard while upstream owner is evaluated"
    if status == "accepted_non_replaceable":
        return "T05 relation collapses the SWSD pair to one RCSD semantic junction; no replaceable RCSD Segment can be constructed"
    if status == "requires_upstream_side_group_or_rcsd_directionality_review":
        return "dual SWSD Segment cannot be replaced by T06 single-segment fallback; evaluate upstream side-group junction aggregation first, then RCSD directionality/source data if no valid grouping exists"
    if status == "resolved_in_step2_plan":
        return "current Step2 standard plan resolved the issue under formal hard audits"
    return "not covered by current replacement plan"


def _manual_review_required(status: str, props: dict[str, Any]) -> bool:
    if status == "accepted_non_replaceable":
        return False
    return bool(props.get("manual_review_required"))


def _default_owner_for_reject(reason: Any) -> str:
    if reason in {"missing_pair_relation", "invalid_pair_relation_status", "invalid_pair_base_id"}:
        return "T05"
    if reason in {"rcsd_not_bidirectional_for_swsd_dual", "rcsd_directed_path_missing"}:
        return "T03/T04/T05_or_T06_group_replacement"
    return "T06"


def _index_by_id(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in features:
        props = dict(item.get("properties") or {})
        key = _safe_id(props.get("id"))
        if key:
            result[key] = item
    return result


def _canonical_road_endpoint_ids(
    road_ids: list[str],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> list[str]:
    result: list[str] = []
    for road_id in road_ids:
        road = rcsd_road_by_id.get(road_id)
        props = dict(road.get("properties") or {}) if road is not None else {}
        for field_name in ("snodeid", "enodeid"):
            try:
                result.append(rcsd_node_canonicalizer.canonicalize(props.get(field_name)))
            except ParseError:
                continue
    return unique_preserve_order(result)


def _parse_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _parse_float_list(value: Any) -> list[float]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        raw_values = value
    else:
        raw_values = [value]
    result: list[float] = []
    for item in raw_values:
        try:
            number = float(item)
        except (TypeError, ValueError):
            continue
        result.append(number)
    return sorted(set(result))


def _safe_id(value: Any) -> str:
    try:
        return normalize_id(value)
    except ParseError:
        return ""
