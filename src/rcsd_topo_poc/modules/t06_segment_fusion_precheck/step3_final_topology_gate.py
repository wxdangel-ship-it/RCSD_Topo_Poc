from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import read_features
from .parsing import parse_id_list, unique_preserve_order
from .step3_final_topology_metric import annotate_final_frcsd_topology_rows
from .step3_topology_connectivity_audit import STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM


FINAL_TOPOLOGY_HARD_GATE_REASON = "final_frcsd_topology_hard_gate_failed"
FINAL_TOPOLOGY_REPAIRABLE_CATEGORIES = {"segment_transition", "independent_attachment"}


def final_topology_gate_decision(
    step_root: Path,
    plan_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    path = step_root / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.gpkg"
    if not path.is_file():
        return _empty_gate_decision()
    audit_rows = read_features(path)
    annotate_final_frcsd_topology_rows(audit_rows)
    ready_plan_items = _ready_plan_items(plan_rows)
    plan_ids_by_segment: dict[str, set[str]] = {}
    plan_ids_by_rcsd_road: dict[str, set[str]] = {}
    for item in ready_plan_items:
        plan_id = item["plan_id"]
        for segment_id in item["segment_ids"]:
            plan_ids_by_segment.setdefault(segment_id, set()).add(plan_id)
        for road_id in item["rcsd_road_ids"]:
            plan_ids_by_rcsd_road.setdefault(road_id, set()).add(plan_id)

    rollback_plan_ids: set[str] = set()
    repairable: list[dict[str, Any]] = []
    inherited: list[dict[str, Any]] = []
    for row in audit_rows:
        props = dict(row.get("properties") or {})
        if not props.get("counts_in_final_frcsd_topology_fail"):
            continue
        category = str(props.get("final_topology_category") or "")
        source_mix = str(props.get("source_mix") or "")
        detail = {
            "category": category,
            "object_key": str(props.get("final_topology_object_key") or ""),
            "audit_layer": str(props.get("audit_layer") or ""),
            "audit_reason": str(props.get("audit_reason") or ""),
            "swsd_node_id": str(props.get("swsd_node_id") or ""),
            "swsd_segment_ids": _ids(props.get("swsd_segment_ids"))
            or _ids(props.get("swsd_segment_id")),
            "frcsd_road_id": str(props.get("frcsd_road_id") or ""),
            "topology_road_lineage_id": str(props.get("topology_road_lineage_id") or ""),
            "source_mix": source_mix,
            "mapped_plan_ids": [],
        }
        if category not in FINAL_TOPOLOGY_REPAIRABLE_CATEGORIES:
            inherited.append(detail)
            continue
        if category == "independent_attachment" and source_mix != "source_1":
            inherited.append(detail)
            continue

        mapped: set[str] = set()
        if category == "independent_attachment":
            lineage_id = detail["topology_road_lineage_id"] or detail["frcsd_road_id"]
            mapped.update(plan_ids_by_rcsd_road.get(lineage_id, set()))
        if not mapped:
            for segment_id in detail["swsd_segment_ids"]:
                mapped.update(plan_ids_by_segment.get(segment_id, set()))
        detail["mapped_plan_ids"] = sorted(mapped)
        rollback_plan_ids.update(mapped)
        repairable.append(detail)

    return {
        "repairable_failure_count": len(repairable),
        "mapped_failure_count": sum(1 for item in repairable if item["mapped_plan_ids"]),
        "unmapped_failure_count": sum(1 for item in repairable if not item["mapped_plan_ids"]),
        "inherited_failure_count": len(inherited),
        "rollback_plan_ids": sorted(rollback_plan_ids),
        "repairable_failures": repairable,
        "inherited_failures": inherited,
    }


def block_final_topology_gate_rows(
    rows: list[dict[str, Any]],
    rollback_plan_ids: set[str],
    *,
    failure_node_ids_by_plan_id: dict[str, set[str]] | None = None,
) -> list[dict[str, Any]]:
    result = [
        {"properties": dict(row.get("properties") or {}), "geometry": row.get("geometry")}
        for row in rows
    ]
    for row in result:
        props = row["properties"]
        if str(props.get("replacement_plan_id") or "") not in rollback_plan_ids:
            continue
        props["plan_status"] = "blocked"
        props["execution_action"] = "hold"
        props["source_reason"] = FINAL_TOPOLOGY_HARD_GATE_REASON
        props["upstream_owner"] = "T06_step3_final_topology_hard_gate"
        props["risk_flags"] = unique_preserve_order(
            [*_ids(props.get("risk_flags")), FINAL_TOPOLOGY_HARD_GATE_REASON]
        )
        props["final_topology_hard_gate_failure_node_ids"] = sorted(
            (failure_node_ids_by_plan_id or {}).get(str(props.get("replacement_plan_id") or ""), set())
        )
        notes = str(props.get("notes") or "")
        suffix = f"blocked by {FINAL_TOPOLOGY_HARD_GATE_REASON}"
        props["notes"] = f"{notes}; {suffix}" if notes else suffix
    return result


def topology_fail_keys(
    step_root: Path,
    *,
    read_rows=read_features,
) -> set[tuple[str, str, str, str, str]]:
    path = step_root / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.gpkg"
    if not path.is_file():
        return set()
    result: set[tuple[str, str, str, str, str]] = set()
    rows = read_rows(path)
    annotate_final_frcsd_topology_rows(rows)
    for row in rows:
        props = row.get("properties") or {}
        if not props.get("counts_in_final_frcsd_topology_fail"):
            continue
        audit_layer = str(props.get("audit_layer") or "")
        segment_ids = _ids(props.get("swsd_segment_ids"))
        segment_id = str(props.get("swsd_segment_id") or "")
        if not segment_id and segment_ids:
            segment_id = json.dumps(segment_ids, ensure_ascii=False)
        object_key = str(props.get("final_topology_object_key") or "")
        result.add(
            (
                audit_layer,
                segment_id,
                str(props.get("swsd_node_id") or ""),
                object_key,
                str(props.get("audit_reason") or ""),
            )
        )
    return result


def postplan_anchor_added_fail_keys(
    fail_keys: set[tuple[str, str, str, str, str]],
) -> set[tuple[str, str, str, str, str]]:
    return {item for item in fail_keys if item[0] != "advance_right_endpoint_connectivity"}


def rollback_items_for_plan_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for row in rows:
        props = row.get("properties") or {}
        plan_id = str(props.get("replacement_plan_id") or "")
        if not plan_id:
            continue
        items.append(
            {
                "plan_id": plan_id,
                "segment_id": str(props.get("swsd_segment_id") or ""),
                "group_segment_ids": _ids(props.get("group_segment_ids")),
            }
        )
    return items


def rollback_plan_ids_for_failed_segments(
    added_fail_keys: set[tuple[str, str, str, str, str]],
    released: list[dict[str, Any]],
    incident: dict[str, list[str]],
) -> set[str]:
    if not added_fail_keys:
        return set()
    failed_segments: set[str] = set()
    for _layer, segment_id, node_id, _road_id, _reason in added_fail_keys:
        segment_ids = _ids(segment_id)
        if segment_ids:
            failed_segments.update(segment_ids)
        elif segment_id:
            failed_segments.add(segment_id)
        if node_id and not (segment_ids or segment_id):
            failed_segments.update(incident.get(node_id, []))
    result: set[str] = set()
    for item in released:
        plan_id = str(item.get("plan_id") or "")
        if not plan_id:
            continue
        segment_ids = {str(item.get("segment_id") or ""), *_ids(item.get("group_segment_ids"))}
        segment_ids.discard("")
        if segment_ids.intersection(failed_segments):
            result.add(plan_id)
    return result


def fail_keys_after_plan_rollback(
    fail_keys: set[tuple[str, str, str, str, str]],
    released: list[dict[str, Any]],
    rollback_plan_ids: set[str],
    incident: dict[str, list[str]],
) -> set[tuple[str, str, str, str, str]]:
    if not fail_keys or not rollback_plan_ids:
        return set(fail_keys)
    retained: set[tuple[str, str, str, str, str]] = set()
    for fail_key in fail_keys:
        related_plan_ids = rollback_plan_ids_for_failed_segments({fail_key}, released, incident)
        if related_plan_ids.intersection(rollback_plan_ids):
            continue
        retained.add(fail_key)
    return retained


def _ready_plan_items(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        props = dict(row.get("properties") or {})
        plan_id = str(props.get("replacement_plan_id") or "")
        if (
            not plan_id
            or props.get("plan_status") != "ready"
            or props.get("execution_action") != "replace"
        ):
            continue
        segment_ids = _ids(props.get("group_segment_ids")) or _ids(props.get("swsd_segment_id"))
        result.append(
            {
                "plan_id": plan_id,
                "segment_ids": segment_ids,
                "rcsd_road_ids": _ids(props.get("rcsd_road_ids")),
            }
        )
    return result


def _empty_gate_decision() -> dict[str, Any]:
    return {
        "repairable_failure_count": 0,
        "mapped_failure_count": 0,
        "unmapped_failure_count": 0,
        "inherited_failure_count": 0,
        "rollback_plan_ids": [],
        "repairable_failures": [],
        "inherited_failures": [],
    }


def _ids(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except Exception:
        return []
