from __future__ import annotations

import ast
from collections import defaultdict
from typing import Any

from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order
from .schemas import feature


MAX_FORMAL_REPLACEMENT_BUFFER_M = 75.0
MIN_VISUAL_REPAIR_GEOMETRY_OVERLAP_RATIO = 0.65
MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_RATIO = 0.1
MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_LENGTH_M = 20.0
MAX_CONTROLLED_VISUAL_HIGH_DEVIATION_RATIO = 0.5
MAX_RETAINED_JUNCTION_ATTACHMENT_GAP_M = 20.0
MAX_REPLACED_JUNCTION_MAPPING_DIVERGENCE_M = 5.0
VISUAL_CONSISTENCY_STRATEGIES = {
    "visual_consistency_high_confidence_repair",
    "visual_consistency_controlled_release",
}


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
) -> list[dict[str, Any]]:
    rcsd_road_by_id = _index_by_id(rcsd_roads)
    rcsd_node_by_id = _index_by_id(rcsd_nodes or [])
    replaceable_segment_ids = {_safe_id((row.get("properties") or {}).get("swsd_segment_id")) for row in replaceable_rows}
    pair_anchor_bridges = _pair_anchor_bridges_by_segment(failure_business_audit_rows or [])
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
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
        )
    )
    rows.extend(
        _group_replacement_plan_rows(
            group_replacement_audit_rows,
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_canonicalizer=rcsd_node_canonicalizer,
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
    _apply_visual_consistency_road_conflict_gate(rows)
    _apply_visual_consistency_high_deviation_gate(rows)
    _apply_visual_consistency_coverage_gate(rows)
    for _ in range(2):
        _apply_junction_alignment_plan_gate(
            rows,
            swsd_segments=swsd_segments or [],
            swsd_nodes=swsd_nodes or [],
            rcsd_node_by_id=rcsd_node_by_id,
            rcsd_road_by_id=rcsd_road_by_id,
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


def _standard_plan_rows(
    replaceable_rows: list[dict[str, Any]],
    *,
    reverse_blockers: dict[tuple[str, str], dict[str, str]],
    pair_anchor_bridges: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in replaceable_rows:
        props = dict(row.get("properties") or {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if not segment_id:
            continue
        source_strategy = str(props.get("replacement_strategy") or "buffer_segment_extraction")
        controlled_visual_release = props.get("geometry_buffer_coverage_issue") == "retained_geometry_outside_swsd_visual_consistency_scope"
        high_visual_deviation = controlled_visual_release and _has_high_visual_consistency_deviation(props)
        strategy = "visual_consistency_controlled_release" if controlled_visual_release else source_strategy
        pair_nodes = _parse_list(props.get("swsd_pair_nodes"))
        reverse_blocker = _blocker_for_pair(pair_nodes, reverse_blockers)
        bridge = pair_anchor_bridges.get(segment_id, {})
        pair_anchor_bridge_road_ids = [
            road_id for road_id in _parse_list(bridge.get("road_ids")) if road_id in rcsd_road_by_id
        ]
        rcsd_road_ids = unique_preserve_order([*_parse_list(props.get("rcsd_road_ids")), *pair_anchor_bridge_road_ids])
        buffer_distances = _parse_float_list(props.get("adaptive_buffer_distance_m"))
        buffer_distance_blocked = bool(buffer_distances and max(buffer_distances) > MAX_FORMAL_REPLACEMENT_BUFFER_M)
        visual_coverage_blocked = controlled_visual_release and _visual_consistency_coverage_gate_failed(props)
        retained_node_ids = unique_preserve_order(
            [
                *_parse_list(props.get("retained_node_ids")),
                *_canonical_road_endpoint_ids(pair_anchor_bridge_road_ids, rcsd_road_by_id, rcsd_node_canonicalizer),
            ]
        )
        plan_status = "blocked" if reverse_blocker or buffer_distance_blocked or visual_coverage_blocked else "ready"
        action = "hold" if plan_status == "blocked" else "replace"
        if reverse_blocker:
            reason = reverse_blocker.get("reason", strategy)
        elif buffer_distance_blocked:
            reason = "adaptive_buffer_exceeds_topology_connectivity_gate"
        elif visual_coverage_blocked:
            reason = "visual_consistency_release_exceeds_formal_replacement_corridor_gate"
        else:
            reason = props.get("geometry_buffer_coverage_issue") if controlled_visual_release else strategy
        risk_flags = ["reverse_retained_swsd_pair_blocked"] if reverse_blocker else []
        if buffer_distance_blocked:
            risk_flags.append("adaptive_buffer_exceeds_topology_connectivity_gate")
        if visual_coverage_blocked:
            risk_flags.append("visual_consistency_release_exceeds_formal_replacement_corridor_gate")
        if pair_anchor_bridge_road_ids:
            risk_flags.append("pair_anchor_bridge_roads_added")
        if controlled_visual_release:
            risk_flags.extend(
                [
                    "visual_consistency_controlled_release",
                    "retained_geometry_outside_swsd_visual_consistency_scope",
                ]
            )
            if high_visual_deviation:
                risk_flags.append("visual_consistency_high_deviation")
        if reverse_blocker:
            notes = f"blocked by reverse retained SWSD segment {reverse_blocker['segment_id']}"
        elif buffer_distance_blocked:
            notes = (
                f"blocked because adaptive buffer exceeds {MAX_FORMAL_REPLACEMENT_BUFFER_M:g}m "
                "topology connectivity gate"
            )
        elif visual_coverage_blocked:
            notes = (
                "blocked because controlled visual release exceeds formal replacement corridor "
                "coverage gate"
            )
        else:
            if controlled_visual_release:
                notes = "standard Step2 replaceable segment with retained RCSD visual consistency mismatch accepted as controlled release audit risk"
                if high_visual_deviation:
                    notes = f"{notes}; high visual deviation requires manual review unless blocked by primary RCSDRoad conflict"
            else:
                notes = (
                    "standard Step2 replaceable segment with pair-anchor bridge roads"
                    if pair_anchor_bridge_road_ids
                    else "standard Step2 replaceable segment"
                )
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
                        else (
                            "T06_step2_topology_connectivity_gate"
                            if buffer_distance_blocked
                            else "T05_relation_consumed"
                        )
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
                    "rcsd_pair_nodes": _parse_list(props.get("rcsd_pair_nodes")),
                    "rcsd_junc_nodes": _parse_list(props.get("rcsd_junc_nodes")),
                    "rcsd_road_ids": rcsd_road_ids,
                    "retained_node_ids": retained_node_ids,
                    "pair_anchor_bridge_road_ids": pair_anchor_bridge_road_ids,
                    "pair_anchor_bridge_length_m": bridge.get("length_m") if pair_anchor_bridge_road_ids else "",
                    "group_segment_ids": [segment_id],
                    "source_segment_ids": [segment_id],
                    "buffer_distances_m": buffer_distances,
                    "risk_flags": risk_flags,
                    "notes": notes,
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
        group_segment_ids = _path_corridor_replacement_segment_ids(props)
        rcsd_road_ids = _parse_list(props.get("group_probe_rcsd_road_ids"))
        if not segment_id or not group_segment_ids or not rcsd_road_ids:
            continue
        buffer_distances = _parse_float_list(props.get("group_probe_buffer_distance_m"))
        buffer_distance_blocked = bool(buffer_distances and max(buffer_distances) > MAX_FORMAL_REPLACEMENT_BUFFER_M)
        rows.append(
            feature(
                {
                    "replacement_plan_id": f"group_path_corridor:{segment_id}",
                    "swsd_segment_id": segment_id,
                    "plan_status": "blocked" if buffer_distance_blocked else "ready",
                    "execution_action": "hold" if buffer_distance_blocked else "replace",
                    "execution_scope": "path_corridor_group",
                    "plan_owner": "T06_STEP2",
                    "upstream_owner": (
                        "T06_step2_topology_connectivity_gate"
                        if buffer_distance_blocked
                        else "T03/T04/T05_feedback_candidate"
                    ),
                    "source_artifact": "t06_segment_group_replacement_audit",
                    "source_reason": (
                        "group_probe_buffer_exceeds_topology_connectivity_gate"
                        if buffer_distance_blocked
                        else props.get("group_probe_reason")
                    ),
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
                    "buffer_distances_m": buffer_distances,
                    "risk_flags": unique_preserve_order(
                        [
                            "group_path_corridor_replacement",
                            *(
                                ["group_probe_buffer_exceeds_topology_connectivity_gate"]
                                if buffer_distance_blocked
                                else []
                            ),
                        ]
                    ),
                    "notes": (
                        f"blocked because group probe buffer exceeds {MAX_FORMAL_REPLACEMENT_BUFFER_M:g}m "
                        "topology connectivity gate"
                        if buffer_distance_blocked
                        else props.get("notes") or "path-corridor group replacement plan"
                    ),
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
        strategy = "visual_consistency_controlled_release" if controlled_release else "visual_consistency_high_confidence_repair"
        risk_flags = [strategy]
        if controlled_release:
            risk_flags.append("retained_geometry_outside_swsd_visual_consistency_scope")
            if _has_high_visual_consistency_deviation(props):
                risk_flags.append("visual_consistency_high_deviation")
            if audit_props.get("manual_review_required"):
                risk_flags.append("manual_review_required")
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
                    "rcsd_pair_nodes": _parse_list(audit_props.get("rcsd_pair_nodes"))
                    or _parse_list(props.get("required_rcsd_nodes")),
                    "rcsd_junc_nodes": _parse_list(audit_props.get("rcsd_junc_nodes")),
                    "rcsd_road_ids": retained_road_ids,
                    "retained_node_ids": retained_node_ids,
                    "group_segment_ids": [segment_id],
                    "source_segment_ids": [segment_id],
                    "buffer_distances_m": [],
                    "risk_flags": unique_preserve_order(risk_flags),
                    "notes": (
                        "topology and directionality passed; retained RCSD visual consistency mismatch accepted as controlled release audit risk"
                        if controlled_release
                        else "topology and directionality passed; visual consistency mismatch accepted by high-confidence T06 repair gate"
                    ),
                },
                row.get("geometry") or next(
                    (audit.get("geometry") for audit in failure_business_audit_rows if _safe_id((audit.get("properties") or {}).get("swsd_segment_id")) == segment_id),
                    None,
                ),
            )
        )
    return rows


def _apply_visual_consistency_road_conflict_gate(rows: list[dict[str, Any]]) -> None:
    primary_road_owner: dict[str, str] = {}
    for row in rows:
        props = row.get("properties") or {}
        if not _is_replace_ready_plan(props) or _is_visual_consistency_plan(props):
            continue
        if props.get("execution_scope") not in {"standard_segment", "path_corridor_group"}:
            continue
        plan_id = str(props.get("replacement_plan_id") or props.get("swsd_segment_id") or "")
        for road_id in _parse_list(props.get("rcsd_road_ids")):
            primary_road_owner.setdefault(road_id, plan_id)
    if not primary_road_owner:
        return

    for row in rows:
        props = row.get("properties") or {}
        if not _is_replace_ready_plan(props) or not _is_visual_consistency_plan(props):
            continue
        conflict_road_ids = [road_id for road_id in _parse_list(props.get("rcsd_road_ids")) if road_id in primary_road_owner]
        if not conflict_road_ids:
            continue
        _block_plan_row(
            props,
            reason="visual_consistency_road_conflict_with_primary_replacement_plan",
            risk_flag="visual_consistency_road_conflict_with_primary_replacement_plan",
        )
        notes = str(props.get("notes") or "")
        suffix = f"conflict_rcsd_road_ids={conflict_road_ids}"
        props["notes"] = f"{notes}; {suffix}" if notes else suffix


def _apply_visual_consistency_high_deviation_gate(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        props = row.get("properties") or {}
        if not _is_replace_ready_plan(props) or not _is_visual_consistency_plan(props):
            continue
        if "visual_consistency_high_deviation" not in _parse_list(props.get("risk_flags")):
            continue
        _block_plan_row(
            props,
            reason="visual_consistency_high_deviation_requires_manual_review",
            risk_flag="visual_consistency_high_deviation_requires_manual_review",
        )


def _apply_visual_consistency_coverage_gate(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        props = row.get("properties") or {}
        if not _is_replace_ready_plan(props) or props.get("replacement_strategy") != "visual_consistency_controlled_release":
            continue
        swsd_uncovered_length = _coverage_metric(props, {}, "swsd_uncovered_by_rcsd_length_m")
        swsd_uncovered_ratio = _coverage_metric(props, {}, "swsd_uncovered_by_rcsd_ratio")
        if swsd_uncovered_length is None or swsd_uncovered_ratio is None:
            continue
        if (
            swsd_uncovered_length <= MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_LENGTH_M
            and swsd_uncovered_ratio <= MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_RATIO
        ):
            continue
        _block_plan_row(
            props,
            reason="visual_consistency_release_exceeds_formal_replacement_corridor_gate",
            risk_flag="visual_consistency_release_exceeds_formal_replacement_corridor_gate",
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
        if incident_segments and any(segment_id not in ready_segments for segment_id in incident_segments):
            swsd_point = _feature_point(swsd_node_by_id.get(swsd_node_id))
            if swsd_point is not None:
                for props, rcsd_node_id in mappings:
                    rcsd_point = _feature_point(rcsd_node_by_id.get(rcsd_node_id))
                    if rcsd_point is None:
                        continue
                    if float(swsd_point.distance(rcsd_point)) > MAX_RETAINED_JUNCTION_ATTACHMENT_GAP_M:
                        _block_plan_row(
                            props,
                            reason="junction_alignment_to_retained_swsd_exceeds_topology_gate",
                            risk_flag="junction_alignment_to_retained_swsd_exceeds_topology_gate",
                        )

        for left_index, (left_props, left_rcsd_node_id) in enumerate(mappings):
            left_point = _feature_point(rcsd_node_by_id.get(left_rcsd_node_id))
            if left_point is None:
                continue
            for right_props, right_rcsd_node_id in mappings[left_index + 1 :]:
                if left_rcsd_node_id == right_rcsd_node_id:
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


def _apply_group_member_plan_gate(rows: list[dict[str, Any]]) -> None:
    standard_props_by_segment: dict[str, dict[str, Any]] = {}
    for row in rows:
        props = row.get("properties") or {}
        if props.get("execution_scope") != "standard_segment":
            continue
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if segment_id:
            standard_props_by_segment.setdefault(segment_id, props)
    if not standard_props_by_segment:
        return

    for row in rows:
        props = row.get("properties") or {}
        if props.get("execution_scope") != "path_corridor_group" or not _is_replace_ready_plan(props):
            continue
        blocked_members: list[str] = []
        inherited_risks: list[str] = []
        for segment_id in _parse_list(props.get("group_segment_ids")):
            standard_props = standard_props_by_segment.get(segment_id)
            if standard_props is None or _is_replace_ready_plan(standard_props):
                continue
            blocked_members.append(segment_id)
            inherited_risks.extend(_parse_list(standard_props.get("risk_flags")))
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


def _mark_plan_row_risk(props: dict[str, Any], *, reason: str, risk_flag: str) -> None:
    if props.get("plan_status") != "ready":
        return
    props["risk_flags"] = unique_preserve_order([*_parse_list(props.get("risk_flags")), risk_flag])
    notes = str(props.get("notes") or "")
    suffix = f"risk: {reason}"
    props["notes"] = f"{notes}; {suffix}" if notes else suffix


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
    swsd_junc_nodes = [node_id for node_id in _parse_list(props.get("swsd_junc_nodes")) if node_id not in exempt_nodes]
    for swsd_node_id, rcsd_node_id in zip(swsd_junc_nodes, _parse_list(props.get("rcsd_junc_nodes"))):
        if swsd_node_id and rcsd_node_id:
            result[swsd_node_id] = unique_preserve_order([*result[swsd_node_id], rcsd_node_id])
    return dict(result)


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

    if buffer_props.get("reject_reason") == "retained_geometry_outside_swsd_visual_consistency_scope":
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
        if (
            swsd_uncovered_length > MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_LENGTH_M
            or swsd_uncovered_ratio > MAX_CONTROLLED_VISUAL_SWSD_UNCOVERED_RATIO
        ):
            return ""
        return "controlled_release"

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
    return "high_confidence_repair"


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


def _path_corridor_replacement_segment_ids(props: dict[str, Any]) -> list[str]:
    group_segment_ids = _parse_list(props.get("path_corridor_group_segment_ids"))
    blocked_segment_ids = set(_parse_list(props.get("path_corridor_blocked_segment_ids")))
    return [segment_id for segment_id in group_segment_ids if segment_id not in blocked_segment_ids]


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


def _safe_id(value: Any) -> str:
    try:
        return normalize_id(value)
    except ParseError:
        return ""
