from __future__ import annotations

import ast
from collections import defaultdict, deque
from typing import Any

from shapely.ops import unary_union

from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order
from .relation_mapping import RelationRecord
from .road_attributes import is_advance_right_turn_road
from .schemas import feature


MAX_FORMAL_REPLACEMENT_BUFFER_M = 75.0
GROUP_SOURCE_BLOCKED_REASON = "path_corridor_source_segment_blocked"
GROUP_SOURCE_NOT_FORMAL_REPLACEABLE_REASON = "path_corridor_source_segment_not_formal_replaceable"
GROUP_BUFFER_EXCEEDS_REASON = "group_probe_buffer_exceeds_topology_connectivity_audit_threshold"
MIN_VISUAL_REPAIR_GEOMETRY_OVERLAP_RATIO = 0.65
MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_RATIO = 0.1
MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_LENGTH_M = 20.0
MAX_CONTROLLED_VISUAL_HIGH_DEVIATION_RATIO = 0.5
MAX_RETAINED_JUNCTION_ATTACHMENT_GAP_M = 20.0
MAX_VISUAL_MANUAL_RELEASE_PAIR_ATTACHMENT_GAP_M = 25.0
MAX_REPLACED_JUNCTION_MAPPING_DIVERGENCE_M = 5.0
MAX_JUNCTION_LOCAL_CONFLICT_ROAD_M = 30.0
RETAINED_JUNCTION_GATE_REASON = "junction_alignment_to_retained_swsd_exceeds_topology_gate"
T05_RELATION_JUNCTION_RELEASE_RISK = "junction_alignment_t05_relation_release"
VISUAL_CONFLICT_SWSD_BUFFER_M = 5.0
VISUAL_CONFLICT_CORRIDOR_BUFFER_M = 15.0
MIN_VISUAL_CONFLICT_PRUNE_OUTSIDE_RATIO = 0.5
VISUAL_CONSISTENCY_STRATEGIES = {
    "visual_consistency_high_confidence_repair",
    "visual_consistency_controlled_release",
    "swsd_buffer_corridor_controlled_release",
}
BUFFER_CORRIDOR_REVIEW_ISSUES = {
    "retained_geometry_outside_swsd_buffer_scope",
    "swsd_geometry_not_covered_by_retained_rcsd",
}
POST_REPLACEMENT_COVERAGE_REVIEW_ISSUES = {
    *BUFFER_CORRIDOR_REVIEW_ISSUES,
    "retained_geometry_outside_swsd_visual_consistency_scope",
    "swsd_visual_continuity_not_covered_by_retained_rcsd",
}


def _mark_plan_row_risk(props: dict[str, Any], *, reason: str, risk_flag: str) -> None:
    if props.get("plan_status") != "ready":
        return
    props["risk_flags"] = unique_preserve_order([*_parse_list(props.get("risk_flags")), risk_flag])
    notes = str(props.get("notes") or "")
    suffix = f"risk: {reason}"
    if suffix in notes:
        return
    props["notes"] = f"{notes}; {suffix}" if notes else suffix


def _allow_t05_relation_attachment_gap(
    *,
    swsd_node_id: str,
    rcsd_node_id: str,
    relation_map: dict[str, RelationRecord],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> bool:
    relation = relation_map.get(swsd_node_id)
    if relation is None or relation.status != 0 or relation.base_id <= 0:
        return False
    try:
        relation_base_id = rcsd_node_canonicalizer.canonicalize(str(relation.base_id))
        candidate_node_id = rcsd_node_canonicalizer.canonicalize(rcsd_node_id)
    except ParseError:
        return False
    return relation_base_id == candidate_node_id


def _incident_segments_by_swsd_node(swsd_segments: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for segment in swsd_segments:
        props = dict(segment.get("properties") or {})
        segment_id = _safe_id(props.get("id") or props.get("swsd_segment_id"))
        if not segment_id:
            continue
        for node_id in unique_preserve_order([*_parse_list(props.get("pair_nodes")), *_parse_list(props.get("junc_nodes"))]):
            result[node_id] = unique_preserve_order([*result[node_id], segment_id])
    return dict(result)


def _plan_node_mappings(props: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for swsd_node_id, rcsd_node_id in zip(_parse_list(props.get("swsd_pair_nodes")), _parse_list(props.get("rcsd_pair_nodes"))):
        if swsd_node_id and rcsd_node_id:
            result[swsd_node_id] = unique_preserve_order([*result[swsd_node_id], rcsd_node_id])
    exempt_nodes = set(_parse_list(props.get("junc_kind2_exempt_nodes")))
    optional_junc_nodes = _parse_list(props.get("optional_junc_nodes"))
    dropped_junc_nodes = set(_parse_list(props.get("dropped_junc_nodes")))
    if optional_junc_nodes:
        swsd_junc_nodes = [node_id for node_id in optional_junc_nodes if node_id not in exempt_nodes and node_id not in dropped_junc_nodes]
    else:
        swsd_junc_nodes = [
            node_id
            for node_id in _parse_list(props.get("swsd_junc_nodes"))
            if node_id not in exempt_nodes and node_id not in dropped_junc_nodes
        ]
    rcsd_junc_nodes = _parse_list(props.get("optional_junc_rcsd_nodes")) or _parse_list(props.get("rcsd_junc_nodes"))
    for swsd_node_id, rcsd_node_id in zip(swsd_junc_nodes, rcsd_junc_nodes):
        if swsd_node_id and rcsd_node_id:
            result[swsd_node_id] = unique_preserve_order([*result[swsd_node_id], rcsd_node_id])
    return dict(result)


def _is_pair_anchor_mismatch_mapping(props: dict[str, Any], *, swsd_node_id: str, rcsd_node_id: str) -> bool:
    swsd_nodes = _parse_list(props.get("pair_anchor_error_swsd_nodes"))
    candidate_nodes = _parse_list(props.get("pair_anchor_error_candidate_rcsd_nodes"))
    if not swsd_nodes or not candidate_nodes:
        return False
    for error_swsd_node, candidate_rcsd_node in zip(swsd_nodes, candidate_nodes):
        if _safe_id(error_swsd_node) == _safe_id(swsd_node_id) and _safe_id(candidate_rcsd_node) == _safe_id(rcsd_node_id):
            return True
    return False


def _feature_point(feature_value: dict[str, Any] | None) -> Any:
    geometry = (feature_value or {}).get("geometry")
    if geometry is None or getattr(geometry, "is_empty", False):
        return None
    return geometry if getattr(geometry, "geom_type", "") == "Point" else None


def _ready_plan_segment_ids(replacement_plan_rows: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in replacement_plan_rows:
        props = dict(row.get("properties") or {})
        if props.get("plan_status") != "ready":
            continue
        result.update(segment_id for segment_id in _parse_list(props.get("group_segment_ids")) if segment_id)
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if segment_id:
            result.add(segment_id)
    return result


def _pair_anchor_bridges_by_segment(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        props = dict(row.get("properties") or {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        road_ids = _parse_list(props.get("pair_anchor_bridge_road_ids"))
        if not segment_id or not road_ids:
            continue
        result[segment_id] = {
            "road_ids": road_ids,
            "length_m": props.get("pair_anchor_bridge_length_m"),
        }
    return result


def _pair_anchor_issues_by_segment(rows: list[dict[str, Any]]) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = {}
    for row in rows:
        props = dict(row.get("properties") or {})
        if str(props.get("failure_business_category") or "") != "pair_anchor_mismatch":
            continue
        segment_id = _safe_id(props.get("swsd_segment_id"))
        swsd_nodes = _parse_list(props.get("pair_anchor_error_swsd_nodes"))
        candidate_nodes = _parse_list(props.get("pair_anchor_error_candidate_rcsd_nodes"))
        if not segment_id or not swsd_nodes or not candidate_nodes:
            continue
        result[segment_id] = {
            "swsd_nodes": swsd_nodes,
            "original_rcsd_nodes": _parse_list(props.get("pair_anchor_error_original_rcsd_nodes")),
            "candidate_rcsd_nodes": candidate_nodes,
        }
    return result


def _props_by_segment(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        props = dict(row.get("properties") or {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if segment_id:
            result.setdefault(segment_id, props)
    return result


def _visual_consistency_release_mode(
    buffer_props: dict[str, Any],
    rejected_props: dict[str, Any],
    audit_props: dict[str, Any],
) -> str:
    if buffer_props.get("reject_reason") not in {
        "swsd_geometry_not_covered_by_retained_rcsd",
        "retained_geometry_outside_swsd_visual_consistency_scope",
        "swsd_visual_continuity_not_covered_by_retained_rcsd",
    }:
        return ""
    if buffer_props.get("full_graph_status") != "required_nodes_connected":
        return ""
    if buffer_props.get("candidate_graph_status") != "required_nodes_connected":
        return ""
    directional_status = str(buffer_props.get("directional_status") or "")
    if "candidate=bidirectional" not in directional_status and "candidate=directed_path_present" not in directional_status:
        return ""
    if _parse_list(buffer_props.get("missing_required_node_ids")):
        return ""
    if _parse_list(buffer_props.get("unexpected_endpoint_node_ids")):
        return ""
    if _parse_list(buffer_props.get("unexpected_mapped_semantic_node_ids")):
        return ""
    if not _visual_release_pair_anchor_complete(buffer_props, audit_props):
        return ""

    reject_reason = str(buffer_props.get("reject_reason") or "")
    if reject_reason == "retained_geometry_outside_swsd_visual_consistency_scope":
        if _coerce_float(buffer_props.get("retained_road_count")) < 1:
            return ""
        swsd_uncovered_length = _coverage_metric(
            buffer_props,
            rejected_props,
            "swsd_uncovered_by_rcsd_length_m",
        )
        swsd_uncovered_ratio = _coverage_metric(
            buffer_props,
            rejected_props,
            "swsd_uncovered_by_rcsd_ratio",
        )
        if swsd_uncovered_length is None or swsd_uncovered_ratio is None:
            return ""
        return "controlled_release"

    buffer_corridor_release = reject_reason == "swsd_geometry_not_covered_by_retained_rcsd"
    if buffer_corridor_release and not _rcsd_corridor_stays_inside_swsd_buffer(buffer_props, rejected_props):
        return ""
    if buffer_corridor_release:
        return "buffer_corridor_release"
    if rejected_props.get("swsd_directionality") != "single":
        return ""
    if _coerce_float(buffer_props.get("retained_road_count")) < 2:
        return ""
    if audit_props.get("manual_review_required"):
        return ""
    if audit_props.get("repair_recommendation") != "high_confidence_pair_anchor_candidate":
        return ""
    geometry_overlap_ratio = _coerce_optional_float(audit_props.get("geometry_overlap_ratio"))
    if geometry_overlap_ratio is not None and geometry_overlap_ratio < MIN_VISUAL_REPAIR_GEOMETRY_OVERLAP_RATIO:
        return ""
    if _coerce_float(audit_props.get("candidate_score")) < 0.88:
        return ""
    if _coerce_float(audit_props.get("directionality_score")) < 1.0:
        return ""
    if _coerce_float(audit_props.get("connectivity_score")) < 1.0:
        return ""
    if _coerce_float(audit_props.get("shape_similarity_score")) < 1.0:
        return ""
    return "buffer_corridor_release" if buffer_corridor_release else "high_confidence_repair"


def _rcsd_corridor_stays_inside_swsd_buffer(buffer_props: dict[str, Any], rejected_props: dict[str, Any]) -> bool:
    outside_length = _coverage_metric(buffer_props, rejected_props, "rcsd_outside_swsd_buffer_length_m")
    outside_ratio = _coverage_metric(buffer_props, rejected_props, "rcsd_outside_swsd_buffer_ratio")
    if outside_length is None or outside_ratio is None:
        return False
    return outside_length <= 1e-6 and outside_ratio <= 1e-6


def _visual_consistency_plan_notes(*, controlled_release: bool, buffer_corridor_release: bool) -> str:
    if controlled_release:
        return "topology and directionality passed; retained RCSD visual consistency mismatch accepted as controlled release audit risk"
    if buffer_corridor_release:
        return "topology and directionality passed; retained RCSD corridor stays inside SWSD buffer; SWSD coverage gap accepted as controlled release audit risk"
    return "topology and directionality passed; visual consistency mismatch accepted by high-confidence T06 repair gate"


def _visual_release_pair_anchor_complete(buffer_props: dict[str, Any], audit_props: dict[str, Any]) -> bool:
    swsd_pair_nodes = _parse_list(audit_props.get("swsd_pair_nodes"))
    rcsd_pair_nodes = _parse_list(audit_props.get("rcsd_pair_nodes")) or _parse_list(buffer_props.get("required_rcsd_nodes"))
    return len(swsd_pair_nodes) >= 2 and len(rcsd_pair_nodes) >= 2


def _allow_visual_manual_release_pair_attachment_gap(
    props: dict[str, Any],
    *,
    swsd_node_id: str,
    distance_m: float,
) -> bool:
    if "visual_consistency_outside_manual_audit" not in _parse_list(props.get("risk_flags")):
        return False
    if swsd_node_id not in set(_parse_list(props.get("swsd_pair_nodes"))):
        return False
    return distance_m <= MAX_VISUAL_MANUAL_RELEASE_PAIR_ATTACHMENT_GAP_M


def _allow_pair_anchor_repair_attachment_gap(
    props: dict[str, Any],
    *,
    swsd_node_id: str,
    rcsd_node_id: str,
) -> bool:
    if props.get("execution_scope") != "standard_segment":
        return False
    existing_risk_flags = set(_parse_list(props.get("risk_flags")))
    if existing_risk_flags - {"pair_anchor_repair_attachment_gap_accepted"}:
        return False
    swsd_pair_nodes = set(_parse_list(props.get("swsd_pair_nodes")))
    if swsd_node_id not in swsd_pair_nodes:
        return False
    rcsd_pair_nodes = set(_parse_list(props.get("rcsd_pair_nodes")))
    if rcsd_node_id not in rcsd_pair_nodes:
        return False
    original_rcsd_pair_nodes = set(_parse_list(props.get("original_rcsd_pair_nodes")))
    if len(rcsd_pair_nodes) < 2 or len(original_rcsd_pair_nodes) >= len(rcsd_pair_nodes):
        return False
    pair_anchor_error_swsd_nodes = set(_parse_list(props.get("pair_anchor_error_swsd_nodes")))
    if pair_anchor_error_swsd_nodes != swsd_pair_nodes:
        return False
    candidate_nodes = set(_parse_list(props.get("pair_anchor_error_candidate_rcsd_nodes")))
    return rcsd_node_id in candidate_nodes or rcsd_node_id not in original_rcsd_pair_nodes


def _has_high_visual_consistency_deviation(props: dict[str, Any]) -> bool:
    return (
        _coerce_float(props.get("rcsd_outside_swsd_buffer_ratio")) >= MAX_CONTROLLED_VISUAL_HIGH_DEVIATION_RATIO
        or _coerce_float(props.get("swsd_uncovered_by_rcsd_ratio")) >= MAX_CONTROLLED_VISUAL_HIGH_DEVIATION_RATIO
    )


def _visual_consistency_coverage_gate_failed(props: dict[str, Any]) -> bool:
    swsd_uncovered_length = _coverage_metric(props, {}, "swsd_uncovered_by_rcsd_length_m")
    swsd_uncovered_ratio = _coverage_metric(props, {}, "swsd_uncovered_by_rcsd_ratio")
    if swsd_uncovered_length is None or swsd_uncovered_ratio is None:
        return False
    return (
        swsd_uncovered_length > MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_LENGTH_M
        or swsd_uncovered_ratio > MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_RATIO
    )


def _coverage_metric(buffer_props: dict[str, Any], rejected_props: dict[str, Any], name: str) -> float | None:
    direct = _coerce_optional_float(buffer_props.get(name))
    if direct is not None:
        return direct
    failed_metric_value = rejected_props.get("failed_metric_value")
    if isinstance(failed_metric_value, dict):
        return _coerce_optional_float(failed_metric_value.get(name))
    if isinstance(failed_metric_value, str) and failed_metric_value.strip():
        try:
            parsed = ast.literal_eval(failed_metric_value)
        except (SyntaxError, ValueError):
            return None
        if isinstance(parsed, dict):
            return _coerce_optional_float(parsed.get(name))
    return None


def _reverse_pair_blockers(
    rejected_rows: list[dict[str, Any]],
    failure_business_audit_rows: list[dict[str, Any]],
    *,
    replaceable_segment_ids: set[str],
) -> dict[tuple[str, str], dict[str, str]]:
    blockers: dict[tuple[str, str], dict[str, str]] = {}
    for row in [*failure_business_audit_rows, *rejected_rows]:
        props = dict(row.get("properties") or {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if segment_id in replaceable_segment_ids:
            continue
        pair = _pair_key(_parse_list(props.get("swsd_pair_nodes")) or _parse_list(props.get("failed_pair_nodes")))
        if not segment_id or pair is None:
            continue
        blockers[(pair[1], pair[0])] = {
            "segment_id": segment_id,
            "reason": str(props.get("reject_reason") or "reverse_retained_swsd_pair_consistency"),
        }
    return blockers


def _blocker_for_pair(pair_nodes: list[str], reverse_blockers: dict[tuple[str, str], dict[str, str]]) -> dict[str, str]:
    pair = _pair_key(pair_nodes)
    return reverse_blockers.get(pair, {}) if pair is not None else {}


def _pair_key(pair_nodes: list[str]) -> tuple[str, str] | None:
    if len(pair_nodes) != 2:
        return None
    return (str(pair_nodes[0]), str(pair_nodes[1]))


def _hard_blocked_group_source_ids(rows: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in rows:
        props = dict(row.get("properties") or {})
        if props.get("group_probe_status") != "passed":
            continue
        if props.get("group_probe_repair_owner") != "T06_path_corridor_group_replacement":
            continue
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if not segment_id:
            continue
        blocked_segment_ids = set(_parse_list(props.get("path_corridor_blocked_segment_ids")))
        if segment_id in blocked_segment_ids:
            result.add(segment_id)
    return result


def _path_corridor_replacement_segment_ids(
    props: dict[str, Any],
    *,
    excluded_segment_ids: set[str] | None = None,
) -> list[str]:
    group_segment_ids = _parse_list(props.get("path_corridor_group_segment_ids"))
    excluded_segment_ids = excluded_segment_ids or set(_parse_list(props.get("path_corridor_blocked_segment_ids")))
    return [segment_id for segment_id in group_segment_ids if segment_id not in excluded_segment_ids]


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


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _coerce_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


def _canonicalize_node_id(canonicalizer: NodeCanonicalizer, value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        return canonicalizer.canonicalize(value)
    except ParseError:
        return _safe_id(value)


def _safe_id(value: Any) -> str:
    try:
        return normalize_id(value)
    except ParseError:
        return ""
