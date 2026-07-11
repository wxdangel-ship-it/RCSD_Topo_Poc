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


from .replacement_plan_support import (
    _mark_plan_row_risk,
    _allow_t05_relation_attachment_gap,
    _incident_segments_by_swsd_node,
    _plan_node_mappings,
    _is_pair_anchor_mismatch_mapping,
    _feature_point,
    _ready_plan_segment_ids,
    _pair_anchor_bridges_by_segment,
    _pair_anchor_issues_by_segment,
    _props_by_segment,
    _visual_consistency_release_mode,
    _rcsd_corridor_stays_inside_swsd_buffer,
    _visual_consistency_plan_notes,
    _visual_release_pair_anchor_complete,
    _allow_visual_manual_release_pair_attachment_gap,
    _allow_pair_anchor_repair_attachment_gap,
    _has_high_visual_consistency_deviation,
    _visual_consistency_coverage_gate_failed,
    _coverage_metric,
    _reverse_pair_blockers,
    _blocker_for_pair,
    _pair_key,
    _hard_blocked_group_source_ids,
    _path_corridor_replacement_segment_ids,
    _problem_status,
    _is_same_rcsd_junction_non_replaceable,
    _upstream_directionality_status,
    _problem_owner,
    _recommended_module,
    _feedback_action,
    _replan_trigger,
    _problem_notes,
    _manual_review_required,
    _default_owner_for_reject,
    _index_by_id,
    _canonical_road_endpoint_ids,
    _parse_list,
    _parse_float_list,
    _coerce_float,
    _coerce_optional_float,
    _safe_id,
)
from .replacement_plan_visual_gate import _visual_outside_swsd_buffer_road_ids

def _standard_plan_rows(
    replaceable_rows: list[dict[str, Any]],
    *,
    reverse_blockers: dict[tuple[str, str], dict[str, str]],
    pair_anchor_bridges: dict[str, dict[str, Any]],
    pair_anchor_issues: dict[str, dict[str, list[str]]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
    swsd_geometry_by_segment: dict[str, Any],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in replaceable_rows:
        props = dict(row.get("properties") or {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if not segment_id:
            continue
        source_strategy = str(props.get("replacement_strategy") or "buffer_segment_extraction")
        coverage_issue = str(props.get("geometry_buffer_coverage_issue") or "")
        controlled_visual_release = coverage_issue == "retained_geometry_outside_swsd_visual_consistency_scope"
        post_replacement_coverage_review = coverage_issue in POST_REPLACEMENT_COVERAGE_REVIEW_ISSUES
        buffer_corridor_review = coverage_issue in BUFFER_CORRIDOR_REVIEW_ISSUES
        high_visual_deviation = controlled_visual_release and _has_high_visual_consistency_deviation(props)
        strategy = (
            "visual_consistency_controlled_release"
            if controlled_visual_release
            else "swsd_buffer_corridor_controlled_release" if buffer_corridor_review else source_strategy
        )
        pair_nodes = _parse_list(props.get("swsd_pair_nodes"))
        reverse_blocker = _blocker_for_pair(pair_nodes, reverse_blockers)
        bridge = pair_anchor_bridges.get(segment_id, {})
        pair_anchor_issue = pair_anchor_issues.get(segment_id, {})
        pair_anchor_bridge_road_ids = [
            road_id for road_id in _parse_list(bridge.get("road_ids")) if road_id in rcsd_road_by_id
        ]
        rcsd_road_ids = unique_preserve_order([*_parse_list(props.get("rcsd_road_ids")), *pair_anchor_bridge_road_ids])
        directionality_conflict_status = str(props.get("directionality_conflict_status") or "")
        directionality_conflict_action = str(props.get("directionality_conflict_action") or "")
        directionality_conflict_reason = str(props.get("directionality_conflict_reason") or "")
        buffer_distances = _parse_float_list(props.get("adaptive_buffer_distance_m"))
        buffer_distance_risk = bool(buffer_distances and max(buffer_distances) > MAX_FORMAL_REPLACEMENT_BUFFER_M)
        visual_coverage_manual_audit = controlled_visual_release and _visual_consistency_coverage_gate_failed(props)
        retained_node_ids = unique_preserve_order(
            [
                *_parse_list(props.get("retained_node_ids")),
                *_canonical_road_endpoint_ids(pair_anchor_bridge_road_ids, rcsd_road_by_id, rcsd_node_canonicalizer),
            ]
        )
        plan_status = "blocked" if reverse_blocker else "ready"
        action = "hold" if plan_status == "blocked" else "replace"
        if reverse_blocker:
            reason = reverse_blocker.get("reason", strategy)
        elif controlled_visual_release and (visual_coverage_manual_audit or high_visual_deviation):
            reason = "visual_consistency_manual_audit_release"
        elif buffer_distance_risk:
            reason = props.get("adaptive_buffer_source_reason") or (
                props.get("geometry_buffer_coverage_issue") if controlled_visual_release else strategy
            )
        else:
            reason = coverage_issue if post_replacement_coverage_review else strategy
        risk_flags = ["reverse_retained_swsd_pair_blocked"] if reverse_blocker else []
        if buffer_distance_risk:
            risk_flags.append("adaptive_buffer_exceeds_topology_connectivity_audit_threshold")
        if pair_anchor_bridge_road_ids:
            risk_flags.append("pair_anchor_bridge_roads_added")
        if directionality_conflict_status:
            risk_flags.append(directionality_conflict_status)
        if directionality_conflict_action:
            risk_flags.append(directionality_conflict_action)
        if post_replacement_coverage_review:
            risk_flags.extend([coverage_issue, "manual_review_required"])
            if buffer_corridor_review:
                risk_flags.append("swsd_buffer_corridor_controlled_release")
        if controlled_visual_release:
            risk_flags.extend(
                [
                    "visual_consistency_controlled_release",
                    "retained_geometry_outside_swsd_visual_consistency_scope",
                ]
            )
            if visual_coverage_manual_audit or high_visual_deviation:
                risk_flags.extend(["visual_consistency_outside_manual_audit", "manual_review_required"])
            if high_visual_deviation:
                risk_flags.append("visual_consistency_high_deviation")
        if reverse_blocker:
            notes = f"blocked by reverse retained SWSD segment {reverse_blocker['segment_id']}"
        else:
            if post_replacement_coverage_review:
                notes = "standard Step2 replaceable segment with retained RCSD visual consistency mismatch accepted as controlled release audit risk"
                if buffer_corridor_review:
                    notes = "standard Step2 replaceable segment with SWSD buffer coverage mismatch accepted as post-replacement manual audit risk"
                elif visual_coverage_manual_audit or high_visual_deviation:
                    notes = f"{notes}; visual consistency deviation requires manual review unless blocked by primary RCSDRoad conflict"
                outside_road_ids = _visual_outside_swsd_buffer_road_ids(
                    rcsd_road_ids,
                    swsd_geometry=swsd_geometry_by_segment.get(segment_id),
                    rcsd_road_by_id=rcsd_road_by_id,
                )
                if outside_road_ids:
                    notes = f"{notes}; visual_outside_swsd_buffer_road_ids={outside_road_ids}"
            else:
                notes = (
                    "standard Step2 replaceable segment with pair-anchor bridge roads"
                    if pair_anchor_bridge_road_ids
                    else "standard Step2 replaceable segment"
                )
            if buffer_distance_risk:
                notes = (
                    f"{notes}; adaptive buffer exceeds {MAX_FORMAL_REPLACEMENT_BUFFER_M:g}m "
                    "topology connectivity audit threshold; released as risk audit only"
                )
            if directionality_conflict_reason:
                notes = f"{notes}; {directionality_conflict_reason}"
        rows.append(
            feature(
                {
                    "replacement_plan_id": f"standard:{segment_id}",
                    "swsd_segment_id": segment_id,
                    "plan_status": plan_status,
                    "execution_action": action,
                    "execution_scope": "standard_segment",
                    "plan_owner": "T06_STEP2",
                    "upstream_owner": (
                        "T06_reverse_pair_consistency"
                        if reverse_blocker
                        else "T05_relation_consumed"
                    ),
                    "source_artifact": "t06_rcsd_segment_replaceable",
                    "source_reason": reason,
                    "replacement_strategy": strategy,
                    "special_junction_id": "",
                    "special_junction_type": "",
                    "swsd_sgrade": props.get("swsd_sgrade"),
                    "swsd_directionality": props.get("swsd_directionality"),
                    "swsd_pair_nodes": pair_nodes,
                    "swsd_junc_nodes": _parse_list(props.get("swsd_junc_nodes")),
                    "junc_kind2_exempt_nodes": _parse_list(props.get("junc_kind2_exempt_nodes")),
                    "detached_junc_nodes": _parse_list(props.get("detached_junc_nodes")),
                    "optional_junc_nodes": _parse_list(props.get("optional_junc_nodes")),
                    "optional_junc_rcsd_nodes": _parse_list(props.get("optional_junc_rcsd_nodes")),
                    "dropped_junc_nodes": _parse_list(props.get("dropped_junc_nodes")),
                    "dropped_junc_relation_nodes": _parse_list(props.get("dropped_junc_relation_nodes")),
                    "original_rcsd_pair_nodes": _parse_list(props.get("original_rcsd_pair_nodes")),
                    "rcsd_pair_nodes": _parse_list(props.get("rcsd_pair_nodes")),
                    "rcsd_junc_nodes": _parse_list(props.get("rcsd_junc_nodes")),
                    "pair_anchor_error_swsd_nodes": pair_anchor_issue.get("swsd_nodes", []),
                    "pair_anchor_error_original_rcsd_nodes": pair_anchor_issue.get("original_rcsd_nodes", []),
                    "pair_anchor_error_candidate_rcsd_nodes": pair_anchor_issue.get("candidate_rcsd_nodes", []),
                    "rcsd_road_ids": rcsd_road_ids,
                    "retained_node_ids": retained_node_ids,
                    "pair_anchor_bridge_road_ids": pair_anchor_bridge_road_ids,
                    "pair_anchor_bridge_length_m": bridge.get("length_m") if pair_anchor_bridge_road_ids else "",
                    "group_segment_ids": [segment_id],
                    "source_segment_ids": [segment_id],
                    "buffer_distances_m": buffer_distances,
                    "directionality_conflict_status": directionality_conflict_status,
                    "directionality_conflict_action": directionality_conflict_action,
                    "directionality_conflict_reason": directionality_conflict_reason,
                    "forward_rcsd_road_ids": _parse_list(props.get("forward_rcsd_road_ids")),
                    "bidirectional_rcsd_road_ids": _parse_list(props.get("bidirectional_rcsd_road_ids")),
                    "reverse_or_extra_rcsd_road_ids": _parse_list(props.get("reverse_or_extra_rcsd_road_ids")),
                    "geometry_buffer_coverage_issue": props.get("geometry_buffer_coverage_issue"),
                    "rcsd_outside_swsd_buffer_length_m": props.get("rcsd_outside_swsd_buffer_length_m"),
                    "rcsd_outside_swsd_buffer_ratio": props.get("rcsd_outside_swsd_buffer_ratio"),
                    "swsd_uncovered_by_rcsd_length_m": props.get("swsd_uncovered_by_rcsd_length_m"),
                    "swsd_uncovered_by_rcsd_ratio": props.get("swsd_uncovered_by_rcsd_ratio"),
                    "risk_flags": unique_preserve_order(risk_flags),
                    "notes": notes,
                },
                row.get("geometry"),
            )
        )
    return rows

def _group_replacement_plan_rows(
    group_rows: list[dict[str, Any]],
    *,
    failure_business_audit_by_segment: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
    formal_replaceable_segment_ids: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    hard_blocked_source_ids = _hard_blocked_group_source_ids(group_rows)
    for row in group_rows:
        props = dict(row.get("properties") or {})
        if props.get("group_probe_status") != "passed":
            continue
        if props.get("group_probe_repair_owner") != "T06_path_corridor_group_replacement":
            continue
        segment_id = _safe_id(props.get("swsd_segment_id"))
        blocked_segment_ids = set(_parse_list(props.get("path_corridor_blocked_segment_ids")))
        excluded_segment_ids = {
            *blocked_segment_ids,
            *hard_blocked_source_ids,
        }
        group_segment_ids = _path_corridor_replacement_segment_ids(props, excluded_segment_ids=excluded_segment_ids)
        rcsd_road_ids = _parse_list(props.get("group_probe_rcsd_road_ids"))
        if not segment_id or not rcsd_road_ids:
            continue
        audit_props = failure_business_audit_by_segment.get(segment_id, {})
        rcsd_junc_nodes = _parse_list(audit_props.get("optional_junc_rcsd_nodes")) or _parse_list(
            audit_props.get("rcsd_junc_nodes")
        )
        buffer_distances = _parse_float_list(props.get("group_probe_buffer_distance_m"))
        buffer_distance_risk = bool(buffer_distances and max(buffer_distances) > MAX_FORMAL_REPLACEMENT_BUFFER_M)
        source_blocked = segment_id in blocked_segment_ids
        source_not_formal = segment_id not in formal_replaceable_segment_ids
        risk_reasons = unique_preserve_order(
            [
                *([GROUP_SOURCE_BLOCKED_REASON] if source_blocked else []),
                *([GROUP_SOURCE_NOT_FORMAL_REPLACEABLE_REASON] if source_not_formal else []),
                *([GROUP_BUFFER_EXCEEDS_REASON] if buffer_distance_risk else []),
            ]
        )
        hold_reasons = []
        if source_blocked and not group_segment_ids:
            hold_reasons.append(GROUP_SOURCE_BLOCKED_REASON)
        plan_status = "blocked" if hold_reasons else "ready"
        action = "hold" if hold_reasons else "replace"
        reason = hold_reasons[0] if hold_reasons else props.get("group_probe_reason")
        notes = props.get("notes") or "path-corridor group replacement plan"
        if source_blocked:
            notes = f"{notes}; source segment is blocked in path-corridor audit and excluded from group action"
        if source_not_formal:
            notes = f"{notes}; source segment did not pass formal single-segment RCSD extraction"
        if buffer_distance_risk:
            notes = (
                f"{notes}; group probe buffer exceeds {MAX_FORMAL_REPLACEMENT_BUFFER_M:g}m "
                "topology connectivity audit threshold; released as risk audit only"
            )
        if hold_reasons:
            notes = f"{notes}; no eligible path-corridor group members remain after hard-gate filtering"
        rows.append(
            feature(
                {
                    "replacement_plan_id": f"group_path_corridor:{segment_id}",
                    "swsd_segment_id": segment_id,
                    "plan_status": plan_status,
                    "execution_action": action,
                    "execution_scope": "path_corridor_group",
                    "plan_owner": "T06_STEP2",
                    "upstream_owner": "T03/T04/T05_feedback_candidate",
                    "source_artifact": "t06_segment_group_replacement_audit",
                    "source_reason": reason,
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
                    "rcsd_junc_nodes": rcsd_junc_nodes,
                    "optional_junc_nodes": _parse_list(audit_props.get("optional_junc_nodes")),
                    "optional_junc_rcsd_nodes": _parse_list(audit_props.get("optional_junc_rcsd_nodes")),
                    "rcsd_road_ids": rcsd_road_ids,
                    "retained_node_ids": _canonical_road_endpoint_ids(rcsd_road_ids, rcsd_road_by_id, rcsd_node_canonicalizer),
                    "group_segment_ids": group_segment_ids,
                    "source_segment_ids": [segment_id],
                    "buffer_distances_m": buffer_distances,
                    "risk_flags": unique_preserve_order(
                        [
                            "group_path_corridor_replacement",
                            *risk_reasons,
                        ]
                    ),
                    "notes": notes,
                },
                row.get("geometry"),
            )
        )
    return rows


def _visual_consistency_repair_plan_rows(
    buffer_rejected_rows: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]],
    failure_business_audit_rows: list[dict[str, Any]],
    *,
    planned_segment_ids: set[str],
) -> list[dict[str, Any]]:
    rejected_by_segment = _props_by_segment(rejected_rows)
    audit_by_segment = _props_by_segment(failure_business_audit_rows)
    rows: list[dict[str, Any]] = []
    for row in buffer_rejected_rows:
        props = dict(row.get("properties") or {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if not segment_id or segment_id in planned_segment_ids:
            continue
        rejected_props = rejected_by_segment.get(segment_id, {})
        audit_props = audit_by_segment.get(segment_id, {})
        release_mode = _visual_consistency_release_mode(props, rejected_props, audit_props)
        if not release_mode:
            continue
        retained_road_ids = _parse_list(props.get("retained_rcsd_road_ids"))
        retained_node_ids = _parse_list(props.get("retained_node_ids"))
        if not retained_road_ids or not retained_node_ids:
            continue
        controlled_release = release_mode == "controlled_release"
        buffer_corridor_release = release_mode == "buffer_corridor_release"
        if controlled_release:
            strategy = "visual_consistency_controlled_release"
        elif buffer_corridor_release:
            strategy = "swsd_buffer_corridor_controlled_release"
        else:
            strategy = "visual_consistency_high_confidence_repair"
        risk_flags = [strategy]
        if controlled_release:
            risk_flags.append("retained_geometry_outside_swsd_visual_consistency_scope")
            if _has_high_visual_consistency_deviation(props):
                risk_flags.append("visual_consistency_high_deviation")
            if audit_props.get("manual_review_required"):
                risk_flags.append("manual_review_required")
        if buffer_corridor_release:
            risk_flags.extend(["swsd_geometry_not_covered_by_retained_rcsd", "manual_review_required"])
        rows.append(
            feature(
                {
                    "replacement_plan_id": f"visual_consistency:{segment_id}",
                    "swsd_segment_id": segment_id,
                    "plan_status": "ready",
                    "execution_action": "replace",
                    "execution_scope": "standard_segment",
                    "plan_owner": "T06_STEP2",
                    "upstream_owner": str(audit_props.get("upstream_issue_owner") or "T06_visual_consistency_repair"),
                    "source_artifact": "t06_rcsd_buffer_segment_rejected",
                    "source_reason": props.get("reject_reason"),
                    "replacement_strategy": strategy,
                    "special_junction_id": "",
                    "special_junction_type": "",
                    "swsd_sgrade": rejected_props.get("swsd_sgrade"),
                    "swsd_directionality": rejected_props.get("swsd_directionality"),
                    "swsd_pair_nodes": _parse_list(audit_props.get("swsd_pair_nodes")),
                    "swsd_junc_nodes": _parse_list(audit_props.get("swsd_junc_nodes")),
                    "junc_kind2_exempt_nodes": _parse_list(rejected_props.get("junc_kind2_exempt_nodes")),
                    "detached_junc_nodes": [],
                    "optional_junc_nodes": _parse_list(audit_props.get("optional_junc_nodes")),
                    "optional_junc_rcsd_nodes": _parse_list(audit_props.get("optional_junc_rcsd_nodes")),
                    "dropped_junc_nodes": _parse_list(audit_props.get("dropped_junc_nodes")),
                    "dropped_junc_relation_nodes": _parse_list(audit_props.get("dropped_junc_relation_nodes")),
                    "rcsd_pair_nodes": _parse_list(audit_props.get("rcsd_pair_nodes"))
                    or _parse_list(props.get("required_rcsd_nodes")),
                    "rcsd_junc_nodes": _parse_list(audit_props.get("rcsd_junc_nodes")),
                    "rcsd_road_ids": retained_road_ids,
                    "retained_node_ids": retained_node_ids,
                    "group_segment_ids": [segment_id],
                    "source_segment_ids": [segment_id],
                    "buffer_distances_m": [],
                    "geometry_buffer_coverage_issue": props.get("reject_reason"),
                    "rcsd_outside_swsd_buffer_length_m": props.get("rcsd_outside_swsd_buffer_length_m"),
                    "rcsd_outside_swsd_buffer_ratio": props.get("rcsd_outside_swsd_buffer_ratio"),
                    "swsd_uncovered_by_rcsd_length_m": props.get("swsd_uncovered_by_rcsd_length_m"),
                    "swsd_uncovered_by_rcsd_ratio": props.get("swsd_uncovered_by_rcsd_ratio"),
                    "risk_flags": unique_preserve_order(risk_flags),
                    "notes": _visual_consistency_plan_notes(
                        controlled_release=controlled_release,
                        buffer_corridor_release=buffer_corridor_release,
                    ),
                },
                row.get("geometry") or next(
                    (audit.get("geometry") for audit in failure_business_audit_rows if _safe_id((audit.get("properties") or {}).get("swsd_segment_id")) == segment_id),
                    None,
                ),
            )
        )
    return rows
