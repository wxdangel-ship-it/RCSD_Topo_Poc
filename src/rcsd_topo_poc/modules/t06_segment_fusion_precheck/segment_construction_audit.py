from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from .graph_builders import NodeCanonicalizer
from .io import read_features, write_feature_triplet, write_json
from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order
from .schemas import feature


SEGMENT_CONSTRUCTION_AUDIT_STEM = "t06_segment_construction_audit"
SIDE_ROAD_ONLY_REPLACEMENT_BLOCK_REASON = "retained_swsd_not_attached_side_road_only"
SEGMENT_CONSTRUCTION_AUDIT_FIELDS = [
    "swsd_segment_id",
    "pair_anchor_status",
    "junc_anchor_status",
    "main_corridor_status",
    "side_road_status",
    "construction_class",
    "step2_replaceable",
    "segment_replacement_status",
    "root_cause",
    "step1_reject_reasons",
    "step2_reject_reasons",
    "retained_side_road_ids",
    "risk_flags",
]


@dataclass(frozen=True)
class SegmentConstructionAuditOutputs:
    rows: list[dict[str, Any]]
    paths: dict[str, Path]
    summary: dict[str, Any]


def apply_side_road_only_replacement_gate(
    *,
    units: list[Any],
    segment_by_id: dict[str, dict[str, Any]],
    swsd_road_by_id: dict[str, dict[str, Any]],
    swsd_nodes: list[dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
) -> dict[str, Any]:
    """Only allow mixed Segment replacement when every retained SWSD Road is a proven side road."""
    canonicalizer = NodeCanonicalizer.from_node_features(swsd_nodes)
    candidate_segment_ids: list[str] = []
    allowed_segment_ids: list[str] = []
    blocked_segment_ids: list[str] = []
    blocked_retained_road_ids: set[str] = set()
    external_carrier_segment_ids: list[str] = []
    external_carrier_road_ids: set[str] = set()

    for unit in units:
        retained_ids = unique_preserve_order(
            normalize_id(road_id)
            for road_id in getattr(unit, "retained_detached_swsd_road_ids", [])
            if normalize_id(road_id)
        )
        if getattr(unit, "status", "") != "passed" or not retained_ids:
            continue
        segment_id = normalize_id(getattr(unit, "segment_id", ""))
        segment = segment_by_id.get(segment_id)
        segment_road_ids = set(
            _parse_ids(((segment or {}).get("properties") or {}).get("roads"))
        )
        formal_retained_ids = [road_id for road_id in retained_ids if road_id in segment_road_ids]
        external_carrier_ids = [road_id for road_id in retained_ids if road_id not in segment_road_ids]
        if external_carrier_ids:
            unit.external_retained_swsd_carrier_ids = unique_preserve_order(
                [
                    *getattr(unit, "external_retained_swsd_carrier_ids", []),
                    *external_carrier_ids,
                ]
            )
            unit.retained_detached_swsd_road_ids = formal_retained_ids
            unit.risk_flags = unique_preserve_order(
                [*getattr(unit, "risk_flags", []), "external_retained_swsd_carrier_excluded_from_segment_metric"]
            )
            external_carrier_segment_ids.append(segment_id)
            external_carrier_road_ids.update(external_carrier_ids)
        if not formal_retained_ids:
            continue
        candidate_segment_ids.append(segment_id)
        proven_ids = (
            _proven_side_road_ids(
                segment_props=(segment or {}).get("properties") or {},
                retained_road_ids=formal_retained_ids,
                swsd_road_by_id=swsd_road_by_id,
                canonicalizer=canonicalizer,
            )
            if segment is not None
            else set()
        )
        if set(formal_retained_ids).issubset(proven_ids):
            allowed_segment_ids.append(segment_id)
            continue

        unit.status = "failed"
        unit.reason = SIDE_ROAD_ONLY_REPLACEMENT_BLOCK_REASON
        unit.risk_flags = unique_preserve_order(
            [*getattr(unit, "risk_flags", []), SIDE_ROAD_ONLY_REPLACEMENT_BLOCK_REASON]
        )
        blocked_segment_ids.append(segment_id)
        blocked_retained_road_ids.update(set(formal_retained_ids) - proven_ids)

    blocked_set = set(blocked_segment_ids)
    if blocked_set:
        for road_id in list(added_road_to_segments):
            remaining = [
                segment_id
                for segment_id in added_road_to_segments[road_id]
                if segment_id not in blocked_set
            ]
            if remaining:
                added_road_to_segments[road_id] = unique_preserve_order(remaining)
            else:
                del added_road_to_segments[road_id]

    return {
        "candidate_mixed_segment_count": len(candidate_segment_ids),
        "allowed_side_road_only_segment_count": len(allowed_segment_ids),
        "blocked_non_side_segment_count": len(blocked_segment_ids),
        "candidate_segment_ids": candidate_segment_ids,
        "allowed_segment_ids": allowed_segment_ids,
        "blocked_segment_ids": blocked_segment_ids,
        "blocked_retained_road_ids": sorted(blocked_retained_road_ids),
        "external_carrier_segment_count": len(set(external_carrier_segment_ids)),
        "external_carrier_road_count": len(external_carrier_road_ids),
        "external_carrier_segment_ids": unique_preserve_order(external_carrier_segment_ids),
        "external_carrier_road_ids": sorted(external_carrier_road_ids),
    }


def build_and_write_segment_construction_audit(
    *,
    step_root: str | Path,
    swsd_segments: list[dict[str, Any]],
    swsd_roads: list[dict[str, Any]],
    swsd_nodes: list[dict[str, Any]],
    step1_rejected_rows: list[dict[str, Any]],
    step2_replaceable_rows: list[dict[str, Any]],
    step2_rejected_rows: list[dict[str, Any]],
    segment_relation_rows: list[dict[str, Any]],
) -> SegmentConstructionAuditOutputs:
    replaceable_ids = {
        _segment_id(row, "swsd_segment_id")
        for row in step2_replaceable_rows
        if _segment_id(row, "swsd_segment_id")
    }
    step1_rejects = _reject_reasons_by_segment(step1_rejected_rows)
    step2_rejects = _reject_reasons_by_segment(step2_rejected_rows)
    relation_by_segment = {
        _segment_id(row, "swsd_segment_id"): row
        for row in segment_relation_rows
        if _segment_id(row, "swsd_segment_id")
    }
    swsd_road_by_id = {
        _segment_id(row, "id"): row
        for row in swsd_roads
        if _segment_id(row, "id")
    }
    swsd_node_canonicalizer = NodeCanonicalizer.from_node_features(swsd_nodes)

    rows: list[dict[str, Any]] = []
    advance_right_segment_count = 0
    for segment in swsd_segments:
        segment_id = _segment_id(segment, "id")
        if not segment_id:
            continue
        segment_props = segment.get("properties") or {}
        if str(segment_props.get("segment_type") or "normal") == "advance_right":
            advance_right_segment_count += 1
            continue
        pair_nodes = set(_parse_ids(segment_props.get("pair_nodes")))
        junc_nodes = set(_parse_ids(segment_props.get("junc_nodes")))
        step1_reasons = step1_rejects.get(segment_id, [])
        step2_reasons = step2_rejects.get(segment_id, [])
        relation_props = (relation_by_segment.get(segment_id) or {}).get("properties") or {}
        relation_status = str(relation_props.get("relation_status") or "missing")
        relation_reason = str(relation_props.get("relation_reason") or "")
        is_replaceable = segment_id in replaceable_ids
        pair_status, junc_status = _anchor_statuses(
            is_replaceable=is_replaceable,
            pair_nodes=pair_nodes,
            junc_nodes=junc_nodes,
            step1_reasons=step1_reasons,
            step2_reasons=step2_reasons,
            step1_rows=step1_rejected_rows,
            step2_rows=step2_rejected_rows,
            segment_id=segment_id,
        )
        main_corridor_status = _main_corridor_status(is_replaceable, step2_reasons)
        retained_road_ids = _retained_candidate_roads(relation_props)
        proven_side_road_ids = _proven_side_road_ids(
            segment_props=segment_props,
            retained_road_ids=retained_road_ids,
            swsd_road_by_id=swsd_road_by_id,
            canonicalizer=swsd_node_canonicalizer,
        )
        retained_side_road_ids = [
            road_id for road_id in retained_road_ids if road_id in proven_side_road_ids
        ]
        if retained_road_ids and set(retained_road_ids).issubset(proven_side_road_ids):
            side_road_status = "missing"
        elif retained_road_ids:
            side_road_status = "unverified_retained_structure"
        else:
            side_road_status = "complete" if relation_status == "replaced" else "not_applicable"
        construction_class, class_risk = _construction_class(
            is_replaceable=is_replaceable,
            relation_status=relation_status,
            pair_status=pair_status,
            junc_status=junc_status,
            side_road_status=side_road_status,
        )
        root_cause = _root_cause(
            construction_class=construction_class,
            relation_status=relation_status,
            relation_reason=relation_reason,
            step1_reasons=step1_reasons,
            step2_reasons=step2_reasons,
            class_risk=class_risk,
        )
        rows.append(
            feature(
                {
                    "swsd_segment_id": segment_id,
                    "pair_anchor_status": pair_status,
                    "junc_anchor_status": junc_status,
                    "main_corridor_status": main_corridor_status,
                    "side_road_status": side_road_status,
                    "construction_class": construction_class,
                    "step2_replaceable": is_replaceable,
                    "segment_replacement_status": relation_status,
                    "root_cause": root_cause,
                    "step1_reject_reasons": step1_reasons,
                    "step2_reject_reasons": step2_reasons,
                    "retained_side_road_ids": retained_side_road_ids,
                    "risk_flags": [class_risk] if class_risk else [],
                },
                segment.get("geometry"),
            )
        )

    paths = write_feature_triplet(
        step_root=Path(step_root),
        stem=SEGMENT_CONSTRUCTION_AUDIT_STEM,
        features=rows,
        fieldnames=SEGMENT_CONSTRUCTION_AUDIT_FIELDS,
    )
    summary = {
        "normal_segment_count": len(rows),
        "normal_segment_replaceable_count": len(replaceable_ids),
        "normal_segment_replaced_count": sum(
            1
            for row in rows
            if (row.get("properties") or {}).get("step2_replaceable")
            and (row.get("properties") or {}).get("segment_replacement_status")
            in {"replaced", "replaced+retained_swsd"}
        ),
        "advance_right_segment_count": advance_right_segment_count,
        "segment_construction_class_counts": _value_counts(rows, "construction_class"),
    }
    return SegmentConstructionAuditOutputs(rows=rows, paths=paths, summary=summary)


def refresh_segment_construction_audit_after_surface(
    *,
    step_root: str | Path,
    summary_path: str | Path,
    swsd_segment_path: str | Path,
    swsd_segments: list[dict[str, Any]] | None = None,
    swsd_roads: list[dict[str, Any]] | None = None,
    swsd_nodes: list[dict[str, Any]] | None = None,
    step2_replaceable_rows: list[dict[str, Any]] | None = None,
    relation_rows: list[dict[str, Any]] | None = None,
) -> SegmentConstructionAuditOutputs | None:
    resolved_step_root = Path(step_root)
    resolved_summary_path = Path(summary_path)
    if not resolved_summary_path.is_file():
        return None
    summary_payload = json.loads(resolved_summary_path.read_text(encoding="utf-8"))
    run_root = resolved_step_root.parent
    summary_input_paths = summary_payload.get("input_paths") or {}
    swsd_roads_path = Path(str(summary_input_paths.get("swsd_roads_path") or ""))
    swsd_nodes_path = Path(str(summary_input_paths.get("swsd_nodes_path") or ""))
    paths = {
        "step1_rejected": run_root / "step1_identify_fusion_units" / "t06_swsd_segment_rejected.gpkg",
        "step2_replaceable": run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_replaceable.gpkg",
        "step2_rejected": run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_rejected.gpkg",
        "relation": resolved_step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg",
        "swsd_roads": swsd_roads_path,
        "swsd_nodes": swsd_nodes_path,
    }
    if not all(path.is_file() for path in paths.values()):
        return None
    outputs = build_and_write_segment_construction_audit(
        step_root=resolved_step_root,
        swsd_segments=swsd_segments if swsd_segments is not None else read_features(swsd_segment_path),
        swsd_roads=swsd_roads if swsd_roads is not None else read_features(paths["swsd_roads"]),
        swsd_nodes=swsd_nodes if swsd_nodes is not None else read_features(paths["swsd_nodes"]),
        step1_rejected_rows=read_features(paths["step1_rejected"]),
        step2_replaceable_rows=(
            step2_replaceable_rows
            if step2_replaceable_rows is not None
            else read_features(paths["step2_replaceable"])
        ),
        step2_rejected_rows=read_features(paths["step2_rejected"]),
        segment_relation_rows=relation_rows if relation_rows is not None else read_features(paths["relation"]),
    )
    summary_payload.update(outputs.summary)
    summary_outputs = dict(summary_payload.get("outputs") or {})
    summary_outputs.update(
        {f"segment_construction_audit_{key}": str(value) for key, value in outputs.paths.items()}
    )
    summary_payload["outputs"] = summary_outputs
    write_json(resolved_summary_path, summary_payload)
    return outputs


def _anchor_statuses(
    *,
    is_replaceable: bool,
    pair_nodes: set[str],
    junc_nodes: set[str],
    step1_reasons: list[str],
    step2_reasons: list[str],
    step1_rows: list[dict[str, Any]],
    step2_rows: list[dict[str, Any]],
    segment_id: str,
) -> tuple[str, str]:
    if is_replaceable:
        return "complete", "complete"
    reasons = [*step1_reasons, *step2_reasons]
    if any("pair" in reason for reason in reasons):
        return "incomplete", "not_evaluated"
    if any("junc" in reason for reason in reasons):
        return "complete", "incomplete"
    failed_nodes = set()
    for row in [*step1_rows, *step2_rows]:
        if _segment_id(row, "swsd_segment_id") != segment_id:
            continue
        props = row.get("properties") or {}
        failed_nodes.update(_parse_ids(props.get("failed_node_ids")))
        failed_nodes.update(_parse_ids(props.get("failed_pair_nodes")))
        failed_nodes.update(_parse_ids(props.get("failed_junc_nodes")))
    if failed_nodes & pair_nodes:
        return "incomplete", "not_evaluated"
    if failed_nodes & junc_nodes:
        return "complete", "incomplete"
    return "complete", "complete"


def _main_corridor_status(is_replaceable: bool, reasons: list[str]) -> str:
    if is_replaceable:
        return "complete"
    if any("direction" in reason or "bidirectional" in reason for reason in reasons):
        return "direction_failed"
    if any("connected" in reason or "path_missing" in reason for reason in reasons):
        return "disconnected"
    return "incomplete"


def _construction_class(
    *,
    is_replaceable: bool,
    relation_status: str,
    pair_status: str,
    junc_status: str,
    side_road_status: str,
) -> tuple[str, str]:
    if is_replaceable and relation_status == "replaced":
        return "2a_complete", ""
    if is_replaceable and relation_status == "replaced+retained_swsd" and side_road_status == "missing":
        return "2b_main_complete_side_missing", ""
    if is_replaceable and relation_status == "replaced+retained_swsd":
        return "2c_not_replaceable", "mixed_replacement_without_side_road_only_evidence"
    if pair_status != "complete":
        return "pair_incomplete", ""
    if junc_status != "complete":
        return "pair_only", ""
    return "2c_not_replaceable", ""


def _retained_candidate_roads(relation_props: dict[str, Any]) -> list[str]:
    detached = _parse_ids(relation_props.get("retained_detached_swsd_road_ids"))
    if detached:
        return detached
    risk_flags = set(_parse_ids(relation_props.get("risk_flags")))
    if "retained_swsd_topology_supplement" not in risk_flags:
        return []
    removed = set(_parse_ids(relation_props.get("removed_swsd_road_ids")))
    return [road_id for road_id in _parse_ids(relation_props.get("swsd_road_ids")) if road_id not in removed]


def _proven_side_road_ids(
    *,
    segment_props: dict[str, Any],
    retained_road_ids: list[str],
    swsd_road_by_id: dict[str, dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> set[str]:
    segment_id = normalize_id(segment_props.get("id"))
    provenance_side_road_ids = {
        road_id
        for road_id in retained_road_ids
        if road_id in swsd_road_by_id
        and str((swsd_road_by_id[road_id].get("properties") or {}).get("segment_build_source") or "")
        == "side_attachment_merge"
        and normalize_id(
            (swsd_road_by_id[road_id].get("properties") or {}).get(
                "side_attachment_merged_into_segmentid"
            )
        )
        == segment_id
    }
    pair_nodes = set(_parse_ids(segment_props.get("pair_nodes")))
    road_ids = [road_id for road_id in _parse_ids(segment_props.get("roads")) if road_id in swsd_road_by_id]
    if len(pair_nodes) != 2 or not road_ids:
        return provenance_side_road_ids
    edges: dict[str, tuple[str, str]] = {}
    for road_id in road_ids:
        props = swsd_road_by_id[road_id].get("properties") or {}
        try:
            edge = (
                canonicalizer.canonicalize(props.get("snodeid")),
                canonicalizer.canonicalize(props.get("enodeid")),
            )
        except ParseError:
            continue
        if edge[0] != edge[1]:
            edges[road_id] = edge
    if not pair_nodes.issubset({node_id for edge in edges.values() for node_id in edge}):
        return provenance_side_road_ids

    active = set(edges)
    side_road_ids: set[str] = set()
    while True:
        incident: dict[str, list[str]] = {}
        for road_id in active:
            for node_id in edges[road_id]:
                incident.setdefault(node_id, []).append(road_id)
        removable_nodes = [
            node_id
            for node_id, incident_road_ids in incident.items()
            if node_id not in pair_nodes and len(incident_road_ids) == 1
        ]
        if not removable_nodes:
            break
        removable_road_ids = {
            incident[node_id][0]
            for node_id in removable_nodes
            if incident[node_id][0] in active
        }
        if not removable_road_ids:
            break
        active.difference_update(removable_road_ids)
        side_road_ids.update(removable_road_ids)
    side_road_ids.update(
        _external_attached_side_road_ids(
            retained_road_ids=retained_road_ids,
            pair_nodes=pair_nodes,
            junc_nodes=set(_parse_ids(segment_props.get("junc_nodes"))),
            swsd_road_by_id=swsd_road_by_id,
            canonicalizer=canonicalizer,
        )
    )
    return side_road_ids | provenance_side_road_ids


def _external_attached_side_road_ids(
    *,
    retained_road_ids: list[str],
    pair_nodes: set[str],
    junc_nodes: set[str],
    swsd_road_by_id: dict[str, dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> set[str]:
    edges: dict[str, tuple[str, str]] = {}
    road_ids_by_node: dict[str, set[str]] = {}
    for road_id in retained_road_ids:
        road = swsd_road_by_id.get(road_id)
        if road is None:
            continue
        props = road.get("properties") or {}
        try:
            edge = (
                canonicalizer.canonicalize(props.get("snodeid")),
                canonicalizer.canonicalize(props.get("enodeid")),
            )
        except ParseError:
            continue
        if edge[0] == edge[1]:
            continue
        edges[road_id] = edge
        for node_id in edge:
            road_ids_by_node.setdefault(node_id, set()).add(road_id)

    pending = set(edges)
    proven: set[str] = set()
    while pending:
        seed = min(pending)
        pending.remove(seed)
        queue = [seed]
        component: set[str] = set()
        component_nodes: set[str] = set()
        while queue:
            road_id = queue.pop(0)
            component.add(road_id)
            component_nodes.update(edges[road_id])
            for node_id in edges[road_id]:
                for next_road_id in road_ids_by_node.get(node_id, set()):
                    if next_road_id in pending:
                        pending.remove(next_road_id)
                        queue.append(next_road_id)
        if len(component_nodes & junc_nodes) == 1 and not (component_nodes & pair_nodes):
            proven.update(component)
    return proven


def _root_cause(
    *,
    construction_class: str,
    relation_status: str,
    relation_reason: str,
    step1_reasons: list[str],
    step2_reasons: list[str],
    class_risk: str,
) -> str:
    if class_risk:
        return class_risk
    if construction_class in {"2a_complete", "2b_main_complete_side_missing"}:
        return relation_reason or construction_class
    reasons = unique_preserve_order([*step2_reasons, *step1_reasons, relation_reason])
    return ";".join(reason for reason in reasons if reason) or relation_status


def _reject_reasons_by_segment(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for row in rows:
        segment_id = _segment_id(row, "swsd_segment_id")
        if not segment_id:
            continue
        props = row.get("properties") or {}
        reason = str(props.get("reject_reason") or "").strip()
        if reason:
            result[segment_id] = unique_preserve_order([*result.get(segment_id, []), reason])
    return result


def _segment_id(row: dict[str, Any], field_name: str) -> str:
    try:
        return normalize_id((row.get("properties") or {}).get(field_name))
    except ParseError:
        return ""


def _parse_ids(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _value_counts(rows: list[dict[str, Any]], field_name: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for row in rows:
        value = str((row.get("properties") or {}).get(field_name) or "")
        result[value] = result.get(value, 0) + 1
    return result
