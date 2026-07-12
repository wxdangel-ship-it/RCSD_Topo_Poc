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
PAIR_ANCHOR_NOT_AUTHORITATIVE_REASON = "pair_anchor_mismatch_replacement_plan_anchor_not_authoritative"
JUNCTION_DIVERGENCE_REASON = "junction_alignment_between_replacement_plans_diverged"
POSTPLAN_ANCHOR_GATE_REASON = "postplan_anchor_gate_deferred_to_step3_topology"
POSTPLAN_PAIR_REPAIR_RECOMMENDATIONS = {
    "high_confidence_pair_anchor_candidate",
    "side_preserving_missing_pair_anchor_completion",
}
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
    _canonicalize_node_id,
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


def _apply_junction_alignment_plan_gate(
    rows: list[dict[str, Any]],
    *,
    swsd_segments: list[dict[str, Any]],
    swsd_nodes: list[dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
    relation_map: dict[str, RelationRecord],
) -> None:
    if not swsd_segments or not swsd_nodes or not rcsd_node_by_id:
        return
    swsd_node_by_id = _index_by_id(swsd_nodes)
    incident_segments_by_node = _incident_segments_by_swsd_node(swsd_segments)
    ready_segments = _ready_plan_segment_ids(rows)
    mappings_by_node: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    for row in rows:
        props = row.get("properties") or {}
        if not _is_replace_ready_plan(props):
            continue
        for swsd_node_id, rcsd_node_ids in _plan_node_mappings(props).items():
            for rcsd_node_id in rcsd_node_ids:
                mappings_by_node[swsd_node_id].append((props, rcsd_node_id))

    for swsd_node_id, mappings in mappings_by_node.items():
        incident_segments = incident_segments_by_node.get(swsd_node_id, [])
        has_retained_boundary = bool(incident_segments and any(segment_id not in ready_segments for segment_id in incident_segments))
        swsd_point = _feature_point(swsd_node_by_id.get(swsd_node_id))
        if swsd_point is not None:
            for props, rcsd_node_id in mappings:
                rcsd_point = _feature_point(rcsd_node_by_id.get(rcsd_node_id))
                if rcsd_point is None:
                    continue
                distance_m = float(swsd_point.distance(rcsd_point))
                if distance_m <= MAX_RETAINED_JUNCTION_ATTACHMENT_GAP_M:
                    continue
                if _allow_t05_relation_attachment_gap(
                    swsd_node_id=swsd_node_id,
                    rcsd_node_id=rcsd_node_id,
                    relation_map=relation_map,
                    rcsd_node_canonicalizer=rcsd_node_canonicalizer,
                ):
                    _mark_plan_row_risk(
                        props,
                        reason=RETAINED_JUNCTION_GATE_REASON,
                        risk_flag=RETAINED_JUNCTION_GATE_REASON,
                    )
                    _mark_plan_row_risk(
                        props,
                        reason="t05_relation_backed_retained_junction_attachment_gap",
                        risk_flag=T05_RELATION_JUNCTION_RELEASE_RISK,
                    )
                    _mark_plan_row_risk(
                        props,
                        reason="t05_relation_backed_retained_junction_attachment_gap_requires_manual_review",
                        risk_flag="manual_review_required",
                    )
                    continue
                if not has_retained_boundary:
                    continue
                if _allow_visual_manual_release_pair_attachment_gap(
                    props,
                    swsd_node_id=swsd_node_id,
                    distance_m=distance_m,
                ):
                    _mark_plan_row_risk(
                        props,
                        reason="visual_manual_release_pair_attachment_gap_requires_manual_review",
                        risk_flag="visual_manual_release_pair_attachment_gap_accepted",
                    )
                    continue
                if _allow_pair_anchor_repair_attachment_gap(
                    props,
                    swsd_node_id=swsd_node_id,
                    rcsd_node_id=rcsd_node_id,
                ):
                    _mark_plan_row_risk(
                        props,
                        reason="pair_anchor_repair_attachment_gap_requires_manual_review",
                        risk_flag="pair_anchor_repair_attachment_gap_accepted",
                    )
                    continue
                _block_plan_row(
                    props,
                    reason=RETAINED_JUNCTION_GATE_REASON,
                    risk_flag=RETAINED_JUNCTION_GATE_REASON,
                )

        _resolve_junction_alignment_buffer_corridor_outliers(
            mappings,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        )

        for left_index, (left_props, left_rcsd_node_id) in enumerate(mappings):
            if not _is_replace_ready_plan(left_props):
                continue
            left_point = _feature_point(rcsd_node_by_id.get(left_rcsd_node_id))
            if left_point is None:
                continue
            for right_props, right_rcsd_node_id in mappings[left_index + 1 :]:
                if not _is_replace_ready_plan(right_props):
                    continue
                if left_rcsd_node_id == right_rcsd_node_id:
                    continue
                left_canonical_node_id = _canonicalize_node_id(rcsd_node_canonicalizer, left_rcsd_node_id)
                right_canonical_node_id = _canonicalize_node_id(rcsd_node_canonicalizer, right_rcsd_node_id)
                if left_canonical_node_id and left_canonical_node_id == right_canonical_node_id:
                    _mark_plan_row_risk(
                        left_props,
                        reason="junction_alignment_between_replacement_plans_semantic_group_aligned",
                        risk_flag="junction_alignment_between_replacement_plans_semantic_group_aligned",
                    )
                    _mark_plan_row_risk(
                        right_props,
                        reason="junction_alignment_between_replacement_plans_semantic_group_aligned",
                        risk_flag="junction_alignment_between_replacement_plans_semantic_group_aligned",
                    )
                    continue
                right_point = _feature_point(rcsd_node_by_id.get(right_rcsd_node_id))
                if right_point is None:
                    continue
                if float(left_point.distance(right_point)) <= MAX_REPLACED_JUNCTION_MAPPING_DIVERGENCE_M:
                    continue
                if _mappings_connected_by_pair_anchor_bridge(
                    left_props,
                    left_rcsd_node_id,
                    right_props,
                    right_rcsd_node_id,
                    rcsd_road_by_id=rcsd_road_by_id,
                ):
                    _mark_plan_row_risk(
                        left_props,
                        reason="junction_alignment_between_replacement_plans_connected_by_pair_anchor_bridge",
                        risk_flag="junction_alignment_between_replacement_plans_connected_by_pair_anchor_bridge",
                    )
                    _mark_plan_row_risk(
                        right_props,
                        reason="junction_alignment_between_replacement_plans_connected_by_pair_anchor_bridge",
                        risk_flag="junction_alignment_between_replacement_plans_connected_by_pair_anchor_bridge",
                    )
                    continue
                left_pair_anchor_mismatch = _is_pair_anchor_mismatch_mapping(
                    left_props,
                    swsd_node_id=swsd_node_id,
                    rcsd_node_id=left_rcsd_node_id,
                )
                right_pair_anchor_mismatch = _is_pair_anchor_mismatch_mapping(
                    right_props,
                    swsd_node_id=swsd_node_id,
                    rcsd_node_id=right_rcsd_node_id,
                )
                if left_pair_anchor_mismatch or right_pair_anchor_mismatch:
                    if left_pair_anchor_mismatch:
                        _block_plan_row(
                            left_props,
                            reason="pair_anchor_mismatch_replacement_plan_anchor_not_authoritative",
                            risk_flag="pair_anchor_mismatch_replacement_plan_anchor_not_authoritative",
                        )
                    else:
                        _mark_plan_row_risk(
                            left_props,
                            reason="junction_alignment_peer_pair_anchor_mismatch_ignored",
                            risk_flag="junction_alignment_peer_pair_anchor_mismatch_ignored",
                        )
                    if right_pair_anchor_mismatch:
                        _block_plan_row(
                            right_props,
                            reason="pair_anchor_mismatch_replacement_plan_anchor_not_authoritative",
                            risk_flag="pair_anchor_mismatch_replacement_plan_anchor_not_authoritative",
                        )
                    else:
                        _mark_plan_row_risk(
                            right_props,
                            reason="junction_alignment_peer_pair_anchor_mismatch_ignored",
                            risk_flag="junction_alignment_peer_pair_anchor_mismatch_ignored",
                        )
                    continue
                _block_plan_row(
                    left_props,
                    reason="junction_alignment_between_replacement_plans_diverged",
                    risk_flag="junction_alignment_between_replacement_plans_diverged",
                )
                _block_plan_row(
                    right_props,
                    reason="junction_alignment_between_replacement_plans_diverged",
                    risk_flag="junction_alignment_between_replacement_plans_diverged",
                )


def _resolve_junction_alignment_buffer_corridor_outliers(
    mappings: list[tuple[dict[str, Any], str]],
    *,
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> None:
    canonical_groups: dict[str, list[tuple[dict[str, Any], str]]] = defaultdict(list)
    for props, rcsd_node_id in mappings:
        if not _is_replace_ready_plan(props):
            continue
        canonical_node_id = _canonicalize_node_id(rcsd_node_canonicalizer, rcsd_node_id)
        if canonical_node_id:
            canonical_groups[canonical_node_id].append((props, rcsd_node_id))
    if len(canonical_groups) < 2:
        return

    sizes = {canonical_node_id: len(group) for canonical_node_id, group in canonical_groups.items()}
    majority_size = max(sizes.values())
    majority_ids = [canonical_node_id for canonical_node_id, size in sizes.items() if size == majority_size]
    if majority_size < 2 or len(majority_ids) != 1:
        return

    majority_id = majority_ids[0]
    outlier_mappings = [
        item
        for canonical_node_id, group in canonical_groups.items()
        if canonical_node_id != majority_id
        for item in group
    ]
    if not outlier_mappings or not all(_is_buffer_corridor_alignment_outlier(props) for props, _node_id in outlier_mappings):
        return

    marked_majority: set[int] = set()
    for props, _node_id in canonical_groups[majority_id]:
        props_id = id(props)
        if props_id in marked_majority:
            continue
        marked_majority.add(props_id)
        _mark_plan_row_risk(
            props,
            reason="junction_alignment_buffer_corridor_outlier_ignored",
            risk_flag="junction_alignment_buffer_corridor_outlier_ignored",
        )

    blocked_outliers: set[int] = set()
    for props, _node_id in outlier_mappings:
        props_id = id(props)
        if props_id in blocked_outliers:
            continue
        blocked_outliers.add(props_id)
        _block_plan_row(
            props,
            reason="junction_alignment_outlier_buffer_corridor_plan",
            risk_flag="junction_alignment_outlier_buffer_corridor_plan",
        )


def _is_buffer_corridor_alignment_outlier(props: dict[str, Any]) -> bool:
    risk_flags = set(_parse_list(props.get("risk_flags")))
    return (
        str(props.get("replacement_strategy") or "") == "swsd_buffer_corridor_controlled_release"
        or str(props.get("geometry_buffer_coverage_issue") or "") == "retained_geometry_outside_swsd_buffer_scope"
        or "swsd_buffer_corridor_controlled_release" in risk_flags
    )


def _apply_group_member_plan_gate(rows: list[dict[str, Any]]) -> None:
    standard_props_by_segment: dict[str, dict[str, Any]] = {}
    ready_standard_owner_segments_by_road: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        props = row.get("properties") or {}
        if props.get("execution_scope") != "standard_segment":
            continue
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if segment_id:
            standard_props_by_segment.setdefault(segment_id, props)
        if segment_id and _is_replace_ready_plan(props):
            for road_id in _parse_list(props.get("rcsd_road_ids")):
                ready_standard_owner_segments_by_road[road_id].add(segment_id)
    if not standard_props_by_segment:
        return

    for row in rows:
        props = row.get("properties") or {}
        if props.get("execution_scope") != "path_corridor_group" or not _is_replace_ready_plan(props):
            continue
        group_segment_ids = set(_parse_list(props.get("group_segment_ids")))
        group_road_ids = set(_parse_list(props.get("rcsd_road_ids")))
        blocked_members: list[str] = []
        absorbed_members: list[str] = []
        inherited_risks: list[str] = []
        for segment_id in _parse_list(props.get("group_segment_ids")):
            standard_props = standard_props_by_segment.get(segment_id)
            if standard_props is None or _is_replace_ready_plan(standard_props):
                continue
            if _blocked_standard_member_absorbable_by_path_group(
                standard_props,
                group_segment_ids=group_segment_ids,
                group_road_ids=group_road_ids,
                ready_standard_owner_segments_by_road=ready_standard_owner_segments_by_road,
            ):
                absorbed_members.append(segment_id)
                continue
            blocked_members.append(segment_id)
            inherited_risks.extend(_parse_list(standard_props.get("risk_flags")))
        if absorbed_members:
            props["absorbed_group_member_segments"] = absorbed_members
            props["risk_flags"] = unique_preserve_order(
                [
                    *_parse_list(props.get("risk_flags")),
                    "group_member_visual_conflict_absorbed_by_path_corridor_group",
                ]
            )
            notes = str(props.get("notes") or "")
            suffix = f"absorbed_group_member_visual_conflict_segments={absorbed_members}"
            if suffix not in notes:
                props["notes"] = f"{notes}; {suffix}" if notes else suffix
        if not blocked_members:
            continue
        _block_plan_row(
            props,
            reason="group_member_replacement_plan_blocked",
            risk_flag="group_member_replacement_plan_blocked",
        )
        props["risk_flags"] = unique_preserve_order([*_parse_list(props.get("risk_flags")), *inherited_risks])
        notes = str(props.get("notes") or "")
        suffix = f"blocked_group_member_segments={blocked_members}"
        props["notes"] = f"{notes}; {suffix}" if notes else suffix


def _apply_postplan_anchor_gate(rows: list[dict[str, Any]]) -> None:
    """Downgrade a closed set of post-plan anchor blockers to Step3 audit risks."""
    ready_road_ids: set[str] = set()
    candidates: list[dict[str, Any]] = []
    allowed_reasons = {
        RETAINED_JUNCTION_GATE_REASON,
        PAIR_ANCHOR_NOT_AUTHORITATIVE_REASON,
        JUNCTION_DIVERGENCE_REASON,
    }
    for row in rows:
        props = row.get("properties") or {}
        if _is_replace_ready_plan(props) and props.get("execution_scope") in {"standard_segment", "path_corridor_group"}:
            ready_road_ids.update(_parse_list(props.get("rcsd_road_ids")))

    for row in rows:
        props = row.get("properties") or {}
        reason = str(props.get("source_reason") or "")
        if (
            props.get("plan_status") != "blocked"
            or props.get("execution_action") != "hold"
            or props.get("execution_scope") != "standard_segment"
            or props.get("source_artifact") != "t06_rcsd_segment_replaceable"
            or reason not in allowed_reasons
            or not _postplan_anchor_gate_complete(props)
        ):
            continue
        road_ids = set(_parse_list(props.get("rcsd_road_ids")))
        if road_ids & ready_road_ids:
            continue
        if reason == PAIR_ANCHOR_NOT_AUTHORITATIVE_REASON:
            recommendation = str(props.get("pair_anchor_repair_recommendation") or "")
            if recommendation not in POSTPLAN_PAIR_REPAIR_RECOMMENDATIONS:
                continue
            if _truthy(props.get("pair_anchor_repair_manual_review_required")):
                continue
        candidates.append(props)

    divergence_peers: dict[int, list[str]] = defaultdict(list)
    for index, left_props in enumerate(candidates):
        if left_props.get("source_reason") != JUNCTION_DIVERGENCE_REASON:
            continue
        left_roads = set(_parse_list(left_props.get("rcsd_road_ids")))
        for right_props in candidates[index + 1 :]:
            if right_props.get("source_reason") != JUNCTION_DIVERGENCE_REASON:
                continue
            if not left_roads.intersection(_parse_list(right_props.get("rcsd_road_ids"))):
                continue
            left_id = _safe_id(left_props.get("swsd_segment_id"))
            right_id = _safe_id(right_props.get("swsd_segment_id"))
            if right_id:
                divergence_peers[id(left_props)].append(right_id)
            if left_id:
                divergence_peers[id(right_props)].append(left_id)

    for props in candidates:
        original_reason = str(props.get("source_reason") or "")
        peer_segment_ids = unique_preserve_order(divergence_peers.get(id(props), []))
        if original_reason == JUNCTION_DIVERGENCE_REASON:
            if not peer_segment_ids:
                continue
            evidence = "blocked_junction_divergence_shared_rcsd_road"
        elif original_reason == PAIR_ANCHOR_NOT_AUTHORITATIVE_REASON:
            evidence = "failure_business_audit_high_confidence_pair_anchor_repair"
        else:
            evidence = "retained_junction_complete_anchor_no_ready_road_conflict"
        _release_postplan_anchor_gate(
            props,
            original_reason=original_reason,
            evidence=evidence,
            peer_segment_ids=peer_segment_ids,
        )


def _postplan_anchor_gate_complete(props: dict[str, Any]) -> bool:
    swsd_pair_nodes = _parse_list(props.get("swsd_pair_nodes"))
    rcsd_pair_nodes = _parse_list(props.get("rcsd_pair_nodes"))
    if len(swsd_pair_nodes) != 2 or len(rcsd_pair_nodes) != 2 or len(set(rcsd_pair_nodes)) != 2:
        return False
    if not _parse_list(props.get("rcsd_road_ids")):
        return False

    exempt_nodes = set(_parse_list(props.get("junc_kind2_exempt_nodes")))
    exempt_nodes.update(_parse_list(props.get("detached_junc_nodes")))
    exempt_nodes.update(_parse_list(props.get("dropped_junc_nodes")))
    optional_junc_nodes = _parse_list(props.get("optional_junc_nodes"))
    swsd_junc_nodes = optional_junc_nodes or _parse_list(props.get("swsd_junc_nodes"))
    required_junc_nodes = [node_id for node_id in swsd_junc_nodes if node_id not in exempt_nodes]
    # Anchor completeness is a relation fact.  The optional list only records
    # which mapped junctions participated in the buffer graph and may be a
    # strict subset even when every formal SWSD junction has an RCSD anchor.
    rcsd_junc_nodes = _parse_list(props.get("rcsd_junc_nodes"))
    return len(rcsd_junc_nodes) >= len(required_junc_nodes)


def _release_postplan_anchor_gate(
    props: dict[str, Any],
    *,
    original_reason: str,
    evidence: str,
    peer_segment_ids: list[str],
) -> None:
    props["plan_status"] = "ready"
    props["execution_action"] = "replace"
    props["source_reason"] = POSTPLAN_ANCHOR_GATE_REASON
    props["upstream_owner"] = "T06_step3_topology_connectivity_audit"
    props["postplan_anchor_gate_original_reason"] = original_reason
    props["postplan_anchor_gate_evidence"] = evidence
    props["postplan_anchor_gate_peer_segment_ids"] = peer_segment_ids
    props["risk_flags"] = unique_preserve_order(
        [
            *_parse_list(props.get("risk_flags")),
            original_reason,
            POSTPLAN_ANCHOR_GATE_REASON,
            evidence,
        ]
    )
    notes = str(props.get("notes") or "")
    blocked_suffix = f"blocked by {original_reason}"
    notes = "; ".join(part.strip() for part in notes.split(";") if part.strip() and part.strip() != blocked_suffix)
    release_note = f"postplan anchor gate released: evidence={evidence}; original_reason={original_reason}"
    props["notes"] = f"{notes}; {release_note}" if notes else release_note


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _blocked_standard_member_absorbable_by_path_group(
    standard_props: dict[str, Any],
    *,
    group_segment_ids: set[str],
    group_road_ids: set[str],
    ready_standard_owner_segments_by_road: dict[str, set[str]],
) -> bool:
    if not _is_visual_consistency_plan(standard_props):
        return False
    source_reason = str(standard_props.get("source_reason") or "")
    risk_flags = set(_parse_list(standard_props.get("risk_flags")))
    if source_reason == "visual_consistency_road_conflict_with_primary_replacement_plan":
        pass
    elif source_reason == "pair_anchor_mismatch_replacement_plan_anchor_not_authoritative":
        if "visual_consistency_same_path_group_member_conflict_accepted" not in risk_flags:
            return False
        if "no_formal_trunk_road_conflict" not in risk_flags:
            return False
    else:
        return False
    segment_id = _safe_id(standard_props.get("swsd_segment_id"))
    if not segment_id or segment_id not in group_segment_ids:
        return False
    member_road_ids = set(_parse_list(standard_props.get("rcsd_road_ids")))
    if not member_road_ids:
        return False
    for road_id in member_road_ids:
        owner_segments = ready_standard_owner_segments_by_road.get(road_id, set())
        if any(owner_segment not in group_segment_ids for owner_segment in owner_segments):
            return False
        if road_id not in group_road_ids and not owner_segments:
            return False
    return True


def _mappings_connected_by_pair_anchor_bridge(
    left_props: dict[str, Any],
    left_rcsd_node_id: str,
    right_props: dict[str, Any],
    right_rcsd_node_id: str,
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> bool:
    bridge_road_ids = unique_preserve_order(
        [
            *_parse_list(left_props.get("pair_anchor_bridge_road_ids")),
            *_parse_list(right_props.get("pair_anchor_bridge_road_ids")),
        ]
    )
    if not bridge_road_ids:
        return False
    expected = {_safe_id(left_rcsd_node_id), _safe_id(right_rcsd_node_id)}
    if len(expected) != 2:
        return False
    for road_id in bridge_road_ids:
        road = rcsd_road_by_id.get(road_id)
        props = dict(road.get("properties") or {}) if road is not None else {}
        endpoints = {_safe_id(props.get("snodeid")), _safe_id(props.get("enodeid"))}
        if expected.issubset(endpoints):
            return True
    return False


def _is_replace_ready_plan(props: dict[str, Any]) -> bool:
    return props.get("plan_status") == "ready" and props.get("execution_action") == "replace"


def _is_visual_consistency_plan(props: dict[str, Any]) -> bool:
    return str(props.get("replacement_strategy") or "") in VISUAL_CONSISTENCY_STRATEGIES


def _block_plan_row(props: dict[str, Any], *, reason: str, risk_flag: str) -> None:
    if props.get("plan_status") != "ready":
        return
    props["plan_status"] = "blocked"
    props["execution_action"] = "hold"
    props["source_reason"] = reason
    props["upstream_owner"] = "T06_step2_topology_connectivity_gate"
    props["risk_flags"] = unique_preserve_order([*_parse_list(props.get("risk_flags")), risk_flag])
    notes = str(props.get("notes") or "")
    suffix = f"blocked by {reason}"
    props["notes"] = f"{notes}; {suffix}" if notes else suffix

def _mark_visual_consistency_manual_audit_release(props: dict[str, Any], *, reason: str) -> None:
    if props.get("plan_status") != "ready":
        return
    props["source_reason"] = "visual_consistency_manual_audit_release"
    props["risk_flags"] = unique_preserve_order(
        [
            *_parse_list(props.get("risk_flags")),
            "visual_consistency_outside_manual_audit",
            "manual_review_required",
            "no_formal_trunk_road_conflict",
        ]
    )
    notes = str(props.get("notes") or "")
    suffix = f"manual audit release: {reason}"
    props["notes"] = f"{notes}; {suffix}" if notes else suffix
