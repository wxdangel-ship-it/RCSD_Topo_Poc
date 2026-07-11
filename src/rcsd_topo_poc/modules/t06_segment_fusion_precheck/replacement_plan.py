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

from .replacement_plan_rows import (
    _standard_plan_rows,
    _group_replacement_plan_rows,
    _visual_consistency_repair_plan_rows,
)

from .replacement_plan_visual_gate import (
    _apply_visual_consistency_road_conflict_gate,
    _is_same_path_group_member_owner,
    _prunable_primary_body_conflict_ids,
    _is_clear_primary_body_conflict,
    _plan_safe_after_road_prune,
    _plan_pair_nodes_connected,
    _plan_corridor_covered,
    _prune_plan_roads,
    _plan_retained_node_ids,
    _geometry_by_segment_id,
    _visual_outside_swsd_buffer_road_ids,
    _is_prunable_junction_local_conflict,
    _is_junction_local_conflict_road,
    _canonicalize_node_id,
    _apply_visual_consistency_high_deviation_gate,
    _apply_visual_consistency_coverage_gate,
)

from .replacement_plan_junction_gate import (
    _special_group_plan_rows,
    _covered_plan_scopes_by_segment,
    _apply_junction_alignment_plan_gate,
    _resolve_junction_alignment_buffer_corridor_outliers,
    _is_buffer_corridor_alignment_outlier,
    _apply_group_member_plan_gate,
    _blocked_standard_member_absorbable_by_path_group,
    _mappings_connected_by_pair_anchor_bridge,
    _is_replace_ready_plan,
    _is_visual_consistency_plan,
    _block_plan_row,
    _mark_visual_consistency_manual_audit_release,
)

def build_replacement_plan_rows(
    *,
    replaceable_rows: list[dict[str, Any]],
    rejected_rows: list[dict[str, Any]] | None = None,
    buffer_rejected_rows: list[dict[str, Any]] | None = None,
    failure_business_audit_rows: list[dict[str, Any]] | None = None,
    special_group_rows: list[dict[str, Any]],
    group_replacement_audit_rows: list[dict[str, Any]],
    rcsd_roads: list[dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
    swsd_segments: list[dict[str, Any]] | None = None,
    swsd_nodes: list[dict[str, Any]] | None = None,
    rcsd_nodes: list[dict[str, Any]] | None = None,
    relation_map: dict[str, RelationRecord] | None = None,
) -> list[dict[str, Any]]:
    rcsd_road_by_id = _index_by_id(rcsd_roads)
    rcsd_node_by_id = _index_by_id(rcsd_nodes or [])
    replaceable_segment_ids = {_safe_id((row.get("properties") or {}).get("swsd_segment_id")) for row in replaceable_rows}
    pair_anchor_bridges = _pair_anchor_bridges_by_segment(failure_business_audit_rows or [])
    pair_anchor_issues = _pair_anchor_issues_by_segment(failure_business_audit_rows or [])
    reverse_blockers = _reverse_pair_blockers(
        rejected_rows or [],
        failure_business_audit_rows or [],
        replaceable_segment_ids=replaceable_segment_ids,
    )
    rows: list[dict[str, Any]] = []
    rows.extend(
        _standard_plan_rows(
            replaceable_rows,
            reverse_blockers=reverse_blockers,
            pair_anchor_bridges=pair_anchor_bridges,
            pair_anchor_issues=pair_anchor_issues,
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
            swsd_geometry_by_segment=_geometry_by_segment_id(swsd_segments or []),
        )
    )
    rows.extend(
        _group_replacement_plan_rows(
            group_replacement_audit_rows,
            failure_business_audit_by_segment=_props_by_segment(failure_business_audit_rows or []),
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
            formal_replaceable_segment_ids=replaceable_segment_ids,
        )
    )
    rows.extend(
        _visual_consistency_repair_plan_rows(
            buffer_rejected_rows or [],
            rejected_rows or [],
            failure_business_audit_rows or [],
            planned_segment_ids=_ready_plan_segment_ids(rows),
        )
    )
    rows.extend(_special_group_plan_rows(special_group_rows))
    _apply_visual_consistency_road_conflict_gate(
        rows,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        swsd_segments=swsd_segments or [],
    )
    _apply_visual_consistency_high_deviation_gate(rows)
    _apply_visual_consistency_coverage_gate(rows)
    for _ in range(2):
        _apply_junction_alignment_plan_gate(
            rows,
            swsd_segments=swsd_segments or [],
            swsd_nodes=swsd_nodes or [],
            rcsd_node_by_id=rcsd_node_by_id,
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
            relation_map=relation_map or {},
        )
        _apply_group_member_plan_gate(rows)
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
