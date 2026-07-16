from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import read_features, write_feature_triplet
from .parsing import ParseError, parse_id_list, unique_preserve_order
from .schemas import feature
from .step3_replacement_plan_reader import (
    is_deferred_replacement_plan,
    read_replacement_plan_rows,
)
from .step3_semantic_junction_groups import discover_intersection_match_path, valid_t05_relation_targets


AUTHORITATIVE_TRANSITION_CLOSURE_STEM = "t06_step3_authoritative_transition_closure_audit"
AUTHORITATIVE_TRANSITION_CLOSURE_FIELDS = [
    "swsd_node_id",
    "t05_base_id",
    "anchor_root_id",
    "replaced_segment_ids",
    "replaced_mapped_node_ids",
    "replaced_mapped_root_ids",
    "retained_segment_ids",
    "source2_node_ids",
    "max_gap_m",
    "audit_status",
    "action",
    "action_reason",
]
AUTHORITATIVE_TRANSITION_MAX_GAP_M = 12.0
AUTHORITATIVE_TRANSITION_RISK = "authoritative_t05_transition_mainnode_synced"
_PATCH_BLOCK_REASONS = {
    "blocked_by_patch_conflict",
    "blocked_by_t04_reject",
    "blocked_by_t04_patch_conflict",
}


def apply_authoritative_transition_closure(
    *,
    step_root: Path,
    relation_rows: list[dict[str, Any]],
    frcsd_nodes: list[dict[str, Any]],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
    current_transition_node_ids: set[str] | None = None,
    max_gap_m: float = AUTHORITATIVE_TRANSITION_MAX_GAP_M,
    surface_audit_rows: list[dict[str, Any]] | None = None,
    write_outputs: bool = True,
) -> dict[str, Any]:
    formal_transition_node_ids = (
        current_transition_node_ids
        if current_transition_node_ids is not None
        else _formal_transition_node_ids(step_root)
    )
    transition_node_ids = formal_transition_node_ids & _hard_gate_cascade_node_ids(step_root)
    blocked_node_ids = _patch_blocked_surface_node_ids(
        step_root,
        rows=surface_audit_rows,
    )
    t05_targets = _t05_targets_for_step(step_root)
    stats = sync_authoritative_transition_mainnodes(
        relation_rows=relation_rows,
        frcsd_nodes=frcsd_nodes,
        transition_node_ids=transition_node_ids,
        patch_blocked_node_ids=blocked_node_ids,
        t05_targets=t05_targets,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
        max_gap_m=max_gap_m,
    )
    if write_outputs:
        write_feature_triplet(
            step_root=step_root,
            stem=AUTHORITATIVE_TRANSITION_CLOSURE_STEM,
            features=stats["audit_rows"],
            fieldnames=AUTHORITATIVE_TRANSITION_CLOSURE_FIELDS,
        )
    return stats


def sync_authoritative_transition_mainnodes(
    *,
    relation_rows: list[dict[str, Any]],
    frcsd_nodes: list[dict[str, Any]],
    transition_node_ids: set[str],
    patch_blocked_node_ids: set[str],
    t05_targets: dict[str, str],
    source_field_name: str = "source",
    swsd_source_value: int = 2,
    rcsd_source_value: int = 1,
    max_gap_m: float = AUTHORITATIVE_TRANSITION_MAX_GAP_M,
) -> dict[str, Any]:
    swsd_source = str(swsd_source_value)
    rcsd_source = str(rcsd_source_value)
    node_by_key = {
        (_source_text((node.get("properties") or {}).get(source_field_name)), _safe_id((node.get("properties") or {}).get("id"))): node
        for node in frcsd_nodes
    }
    root_by_node_id = {
        node_id: _mainnode_or_id(node)
        for (source, node_id), node in node_by_key.items()
        if source == rcsd_source
    }
    relation_by_node = _relation_evidence_by_swsd_node(relation_rows, root_by_node_id=root_by_node_id)
    audit_rows: list[dict[str, Any]] = []
    applied_node_count = 0
    updated_relation_row_count = 0
    updated_source2_node_count = 0
    updated_source1_node_count = 0

    for swsd_node_id in sorted(transition_node_ids, key=_id_sort_key):
        evidence = relation_by_node.get(swsd_node_id, {})
        replaced_segment_ids = sorted(evidence.get("replaced_segment_ids", set()))
        retained_segment_ids = sorted(evidence.get("retained_segment_ids", set()))
        mapped_node_ids = sorted(evidence.get("replaced_mapped_node_ids", set()))
        mapped_root_ids = sorted(evidence.get("replaced_mapped_root_ids", set()))
        base_id = str(t05_targets.get(swsd_node_id) or "")
        anchor_node = node_by_key.get((rcsd_source, base_id))
        anchor_root = root_by_node_id.get(base_id, base_id)
        source2_node = node_by_key.get((swsd_source, swsd_node_id))
        status = "skipped"
        action = "audit_authoritative_transition_closure"
        reason = "authoritative_transition_evidence_incomplete"
        gap_m: float | None = None

        if swsd_node_id in patch_blocked_node_ids:
            reason = "surface_patch_or_t04_conflict_blocks_authoritative_closure"
        elif not base_id or anchor_node is None:
            reason = "t05_authoritative_base_missing_from_final_rcsd"
        elif not replaced_segment_ids or not mapped_root_ids:
            reason = "no_remaining_replaced_relation_mapping"
        elif mapped_root_ids != [anchor_root]:
            reason = "remaining_replaced_mappings_disagree_with_t05_authoritative_root"
        elif source2_node is None:
            reason = "swsd_transition_node_missing_from_final_nodes"
        else:
            gap_m = _geometry_gap(source2_node, anchor_node)
            if gap_m is None:
                reason = "transition_node_geometry_missing"
            elif gap_m > max_gap_m:
                reason = "t05_authoritative_transition_gap_exceeds_limit"
            else:
                source2_props = source2_node.setdefault("properties", {})
                if _safe_id(source2_props.get("mainnodeid")) != anchor_root:
                    source2_props["mainnodeid"] = _coerce_id(anchor_root)
                    updated_source2_node_count += 1
                anchor_props = anchor_node.setdefault("properties", {})
                if _safe_id(anchor_props.get("mainnodeid")) in {"", "0"}:
                    anchor_props["mainnodeid"] = _coerce_id(anchor_root)
                    updated_source1_node_count += 1
                changed_rows = _mark_retained_relation_entries(
                    relation_rows,
                    swsd_node_id=swsd_node_id,
                    anchor_root=anchor_root,
                )
                updated_relation_row_count += changed_rows
                applied_node_count += 1
                status = "applied"
                action = "sync_retained_transition_to_t05_authoritative_mainnode"
                reason = "remaining_replaced_mappings_uniquely_match_t05_authoritative_root"

        audit_rows.append(
            feature(
                {
                    "swsd_node_id": swsd_node_id,
                    "t05_base_id": base_id,
                    "anchor_root_id": anchor_root,
                    "replaced_segment_ids": replaced_segment_ids,
                    "replaced_mapped_node_ids": mapped_node_ids,
                    "replaced_mapped_root_ids": mapped_root_ids,
                    "retained_segment_ids": retained_segment_ids,
                    "source2_node_ids": [swsd_node_id] if source2_node is not None else [],
                    "max_gap_m": round(gap_m, 3) if gap_m is not None else None,
                    "audit_status": status,
                    "action": action,
                    "action_reason": reason,
                },
                source2_node.get("geometry") if source2_node is not None else None,
            )
        )

    return {
        "candidate_node_count": len(transition_node_ids),
        "applied_node_count": applied_node_count,
        "updated_relation_row_count": updated_relation_row_count,
        "updated_source2_node_count": updated_source2_node_count,
        "updated_source1_node_count": updated_source1_node_count,
        "audit_rows": audit_rows,
    }


def _relation_evidence_by_swsd_node(
    relation_rows: list[dict[str, Any]],
    *,
    root_by_node_id: dict[str, str],
) -> dict[str, dict[str, set[str]]]:
    result: dict[str, dict[str, set[str]]] = {}
    for row in relation_rows:
        props = dict(row.get("properties") or {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        relation_status = str(props.get("relation_status") or "")
        for entry in _node_map_entries(props.get("swsd_to_frcsd_node_map")):
            swsd_node_id = _safe_id(entry.get("swsd_node_id"))
            if not swsd_node_id:
                continue
            state = result.setdefault(
                swsd_node_id,
                {
                    "replaced_segment_ids": set(),
                    "retained_segment_ids": set(),
                    "replaced_mapped_node_ids": set(),
                    "replaced_mapped_root_ids": set(),
                },
            )
            if "replaced" in relation_status:
                state["replaced_segment_ids"].add(segment_id)
                mapping_status = str(entry.get("mapping_status") or "")
                if mapping_status != "missing" and not mapping_status.startswith("identity"):
                    for node_id in _ids(entry.get("frcsd_node_ids")):
                        state["replaced_mapped_node_ids"].add(node_id)
                        state["replaced_mapped_root_ids"].add(root_by_node_id.get(node_id, node_id))
            elif relation_status == "retained_swsd":
                state["retained_segment_ids"].add(segment_id)
    return result


def _mark_retained_relation_entries(
    relation_rows: list[dict[str, Any]],
    *,
    swsd_node_id: str,
    anchor_root: str,
) -> int:
    changed_rows = 0
    for row in relation_rows:
        props = row.setdefault("properties", {})
        if str(props.get("relation_status") or "") != "retained_swsd":
            continue
        entries = _node_map_entries(props.get("swsd_to_frcsd_node_map"))
        row_changed = False
        for entry in entries:
            if _safe_id(entry.get("swsd_node_id")) != swsd_node_id:
                continue
            entry["mapping_status"] = "identity_authoritative_t05_mainnode_synced"
            row_changed = True
        if not row_changed:
            continue
        props["swsd_to_frcsd_node_map"] = entries
        props["risk_flags"] = unique_preserve_order([*_ids(props.get("risk_flags")), AUTHORITATIVE_TRANSITION_RISK])
        changed_rows += 1
    return changed_rows


def _formal_transition_node_ids(step_root: Path) -> set[str]:
    path = step_root / "t06_step3_topology_connectivity_audit.gpkg"
    if not path.is_file():
        return set()
    result = set()
    for row in read_features(path):
        props = dict(row.get("properties") or {})
        if not props.get("counts_in_final_frcsd_topology_fail"):
            continue
        if str(props.get("final_topology_category") or "") != "segment_transition":
            continue
        node_id = _safe_id(props.get("swsd_node_id"))
        if node_id:
            result.add(node_id)
    return result


def _hard_gate_cascade_node_ids(step_root: Path) -> set[str]:
    summary_path = step_root / "t06_step3_summary.json"
    if not summary_path.is_file():
        return set()
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    plan_value = (summary.get("input_paths") or {}).get("step2_replacement_plan_path")
    if not plan_value:
        return set()
    plan_path = Path(plan_value)
    if "final_topology_hard_gate_" not in plan_path.name:
        return set()
    if not plan_path.is_file() and not is_deferred_replacement_plan(plan_path):
        return set()
    incident_node_ids: set[str] = set()
    direct_failure_node_ids: set[str] = set()
    for row in read_replacement_plan_rows(plan_path):
        props = dict(row.get("properties") or {})
        risk_flags = set(_ids(props.get("risk_flags")))
        if (
            str(props.get("source_reason") or "") != "final_frcsd_topology_hard_gate_failed"
            and "final_frcsd_topology_hard_gate_failed" not in risk_flags
        ):
            continue
        for field_name in ("swsd_pair_nodes", "swsd_junc_nodes"):
            incident_node_ids.update(_ids(props.get(field_name)))
        direct_failure_node_ids.update(_ids(props.get("final_topology_hard_gate_failure_node_ids")))
    return incident_node_ids - direct_failure_node_ids


def _patch_blocked_surface_node_ids(
    step_root: Path,
    *,
    rows: list[dict[str, Any]] | None = None,
) -> set[str]:
    path = step_root / "t06_step3_surface_topology_audit.gpkg"
    if rows is None and not path.is_file():
        return set()
    result = set()
    for row in rows if rows is not None else read_features(path):
        props = dict(row.get("properties") or {})
        reason = str(props.get("audit_reason") or "")
        if reason not in _PATCH_BLOCK_REASONS and "patch_conflict" not in reason and "t04_reject" not in reason:
            continue
        node_id = _safe_id(props.get("swsd_node_id"))
        if node_id:
            result.add(node_id)
    return result


def _t05_targets_for_step(step_root: Path) -> dict[str, str]:
    summary_path = step_root / "t06_step3_summary.json"
    if not summary_path.is_file():
        return {}
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    step2_path = (payload.get("input_paths") or {}).get("step2_replaceable_path")
    if not step2_path:
        return {}
    relation_path = discover_intersection_match_path(Path(step2_path))
    return valid_t05_relation_targets(relation_path) if relation_path is not None else {}


def _node_map_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except Exception:
        return []
    return [dict(item) for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _ids(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _mainnode_or_id(node: dict[str, Any]) -> str:
    props = dict(node.get("properties") or {})
    mainnode = _safe_id(props.get("mainnodeid"))
    return mainnode if mainnode not in {"", "0"} else _safe_id(props.get("id"))


def _geometry_gap(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    left_geometry = left.get("geometry")
    right_geometry = right.get("geometry")
    if left_geometry is None or right_geometry is None:
        return None
    return float(left_geometry.distance(right_geometry))


def _source_text(value: Any) -> str:
    text = str(value or "")
    return text[:-2] if text.endswith(".0") else text


def _safe_id(value: Any) -> str:
    if value in (None, ""):
        return ""
    text = str(value)
    return text[:-2] if text.endswith(".0") else text


def _coerce_id(value: str) -> Any:
    return int(value) if value.isdigit() else value


def _id_sort_key(value: str) -> tuple[int, Any]:
    return (0, int(value)) if value.isdigit() else (1, value)
