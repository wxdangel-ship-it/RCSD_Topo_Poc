from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import read_features
from .parsing import parse_id_list, unique_preserve_order
from .step3_semantic_junction_groups import (
    discover_intersection_match_path,
    valid_t05_relation_targets,
)

RETAINED_JUNCTION_GATE_REASON = "junction_alignment_to_retained_swsd_exceeds_topology_gate"
SURFACE_RELEASE_RISK = "junction_alignment_surface_audit_release"
SURFACE_RELEASE_ROLLBACK_REASON = "junction_alignment_surface_release_failed_topology_gate"
POSTPLAN_ANCHOR_GATE_RISK = "postplan_anchor_gate_deferred_to_step3_topology"
POSTPLAN_ANCHOR_ROLLBACK_REASON = "postplan_anchor_gate_failed_topology_gate"
SURFACE_RELEASE_PLAN_STEM = "t06_step3_surface_aware_replacement_plan"
SURFACE_RELEASE_AUDIT = "t06_step3_surface_aware_plan_release_audit.json"
VISUAL_CONFLICT_REASON = "visual_consistency_road_conflict_with_primary_replacement_plan"
VISUAL_CONFLICT_RELEASE_RISK = "visual_conflict_controlled_release"
VISUAL_CONFLICT_ROLLBACK_REASON = "visual_conflict_release_failed_topology_gate"
VISUAL_CONFLICT_UNCONDITIONAL_ROLLBACK_FAIL_REASONS = {
    ("segment_road_connectivity", "segment_road_directed_path_missing"),
    ("segment_road_connectivity", "segment_road_endpoints_not_connected"),
}
RETAINED_JUNCTION_ATTACHMENT_GAP_M = 20.0
OPTIONAL_JUNCTION_ANCHOR_RELEASE_MAX_GAP_M = 50.0
OPTIONAL_JUNCTION_ANCHOR_RELEASE_REASON = "auto_closed_step2_optional_junc_anchor"
T05_SEMANTIC_JUNCTION_RELEASE_REASON = "auto_closed_t05_semantic_junction_relation"
SURFACE_RELEASE_REASONS = {
    "auto_closed",
    "auto_closed_surface_1v1",
    "auto_closed_t04_patch_1v1",
    "auto_closed_step2_junc_1v1",
    "auto_closed_relation_mapped_boundary_1v1",
    "auto_closed_selected_replacement_endpoint",
    OPTIONAL_JUNCTION_ANCHOR_RELEASE_REASON,
    T05_SEMANTIC_JUNCTION_RELEASE_REASON,
}


def _surface_release_plan_rows(
    plan_rows: list[dict[str, Any]],
    *,
    step_root: Path,
    swsd_segment_path: str | Path,
    swsd_nodes_path: str | Path,
    rcsdnode_path: str | Path,
    incident_segments_by_node: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    surface_status = _surface_status_by_node(step_root)
    swsd_node_rows = read_features(swsd_nodes_path)
    swsd_points = _points_by_id(swsd_node_rows)
    swsd_fallback_points = _fallback_points_by_id(swsd_node_rows)
    swsd_anchor_nodes = _anchor_node_ids(swsd_node_rows)
    rcsd_node_rows = read_features(rcsdnode_path)
    rcsd_points = _points_by_id(rcsd_node_rows)
    rcsd_fallback_points = _fallback_points_by_id(rcsd_node_rows)
    t05_relation_by_target = _t05_relation_targets_for_step(step_root)
    rcsd_semantic_ids_by_node = _semantic_ids_by_node(rcsd_node_rows)
    incident = incident_segments_by_node
    if incident is None:
        incident = _incident_segments_by_node(read_features(swsd_segment_path))
    ready_segments = _ready_segment_ids(plan_rows)
    released: list[dict[str, Any]] = []
    rows = [{"properties": dict(row.get("properties") or {}), "geometry": row.get("geometry")} for row in plan_rows]
    for row in rows:
        props = row["properties"]
        if not _is_retained_junction_gate_plan(props):
            continue
        allow, triggers = _release_allowed(
            props,
            surface_status,
            swsd_points,
            rcsd_points,
            incident,
            ready_segments,
            swsd_anchor_nodes,
            swsd_fallback_points=swsd_fallback_points,
            rcsd_fallback_points=rcsd_fallback_points,
            t05_relation_by_target=t05_relation_by_target,
            rcsd_semantic_ids_by_node=rcsd_semantic_ids_by_node,
        )
        if not allow:
            continue
        _release_plan_row(props)
        released.append(
            {
                "plan_id": props.get("replacement_plan_id"),
                "segment_id": props.get("swsd_segment_id"),
                "scope": props.get("execution_scope"),
                "group_segment_ids": _ids(props.get("group_segment_ids")),
                "triggers": triggers,
            }
        )
    return rows, released


def _preplanned_surface_release_plan_rows(
    plan_rows: list[dict[str, Any]],
    *,
    step2_replaceable_path: str | Path,
    swsd_segment_path: str | Path,
    swsd_nodes_path: str | Path,
    rcsdnode_path: str | Path,
    incident_segments_by_node: dict[str, list[str]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    swsd_node_rows = read_features(swsd_nodes_path)
    swsd_points = _points_by_id(swsd_node_rows)
    swsd_fallback_points = _fallback_points_by_id(swsd_node_rows)
    swsd_anchor_nodes = _anchor_node_ids(swsd_node_rows)
    rcsd_node_rows = read_features(rcsdnode_path)
    rcsd_points = _points_by_id(rcsd_node_rows)
    rcsd_fallback_points = _fallback_points_by_id(rcsd_node_rows)
    relation_path = discover_intersection_match_path(step2_replaceable_path)
    t05_relation_by_target = valid_t05_relation_targets(relation_path) if relation_path else {}
    rcsd_semantic_ids_by_node = _semantic_ids_by_node(rcsd_node_rows)
    incident = incident_segments_by_node
    if incident is None:
        incident = _incident_segments_by_node(read_features(swsd_segment_path))
    ready_segments = _ready_segment_ids(plan_rows)
    released: list[dict[str, Any]] = []
    rows = [{"properties": dict(row.get("properties") or {}), "geometry": row.get("geometry")} for row in plan_rows]
    for row in rows:
        props = row["properties"]
        if not _is_retained_junction_gate_plan(props):
            continue
        allow, triggers = _release_allowed(
            props,
            {},
            swsd_points,
            rcsd_points,
            incident,
            ready_segments,
            swsd_anchor_nodes,
            swsd_fallback_points=swsd_fallback_points,
            rcsd_fallback_points=rcsd_fallback_points,
            t05_relation_by_target=t05_relation_by_target,
            rcsd_semantic_ids_by_node=rcsd_semantic_ids_by_node,
        )
        if not allow or not _preplanned_release_triggers_allowed(triggers):
            continue
        _release_plan_row(props)
        released.append(
            {
                "plan_id": props.get("replacement_plan_id"),
                "segment_id": props.get("swsd_segment_id"),
                "scope": props.get("execution_scope"),
                "group_segment_ids": _ids(props.get("group_segment_ids")),
                "triggers": triggers,
                "preplanned": True,
            }
        )
    return rows, released


def _preplanned_release_triggers_allowed(triggers: list[dict[str, Any]]) -> bool:
    allowed_reasons = {
        T05_SEMANTIC_JUNCTION_RELEASE_REASON,
        OPTIONAL_JUNCTION_ANCHOR_RELEASE_REASON,
        "auto_closed_selected_replacement_endpoint",
    }
    for trigger in triggers:
        status = trigger.get("surface_status")
        reason = status[1] if isinstance(status, list) and len(status) > 1 else None
        if reason not in allowed_reasons:
            return False
    return bool(triggers)


def _release_allowed(
    props: dict[str, Any],
    surface_status: dict[str, tuple[str, str, Any]],
    swsd_points: dict[str, Any],
    rcsd_points: dict[str, Any],
    incident: dict[str, list[str]],
    ready_segments: set[str],
    swsd_anchor_nodes: set[str] | None = None,
    swsd_fallback_points: dict[str, Any] | None = None,
    rcsd_fallback_points: dict[str, Any] | None = None,
    t05_relation_by_target: dict[str, str] | None = None,
    rcsd_semantic_ids_by_node: dict[str, set[str]] | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    scope = props.get("execution_scope")
    if scope and scope != "standard_segment":
        return False, []
    if not _is_retained_junction_gate_plan(props):
        return False, []
    swsd_anchor_nodes = swsd_anchor_nodes or set()
    t05_relation_by_target = t05_relation_by_target or {}
    rcsd_semantic_ids_by_node = rcsd_semantic_ids_by_node or {}
    triggers: list[dict[str, Any]] = []
    for swsd_node_id, rcsd_node_id in _plan_mappings(props):
        if not any(segment_id not in ready_segments for segment_id in incident.get(swsd_node_id, [])):
            continue
        trigger = _release_trigger_for_mapping(
            props,
            swsd_node_id=swsd_node_id,
            rcsd_node_id=rcsd_node_id,
            swsd_points=swsd_points,
            rcsd_points=rcsd_points,
            surface_status=surface_status,
            swsd_anchor_nodes=swsd_anchor_nodes,
            t05_relation_by_target=t05_relation_by_target,
            rcsd_semantic_ids_by_node=rcsd_semantic_ids_by_node,
        )
        if trigger is None:
            trigger = _release_trigger_for_mapping(
                props,
                swsd_node_id=swsd_node_id,
                rcsd_node_id=rcsd_node_id,
                swsd_points=swsd_fallback_points or {},
                rcsd_points=rcsd_fallback_points or {},
                surface_status=surface_status,
                swsd_anchor_nodes=swsd_anchor_nodes,
                point_source="mainnodeid_fallback",
                t05_relation_by_target=t05_relation_by_target,
                rcsd_semantic_ids_by_node=rcsd_semantic_ids_by_node,
            )
        if trigger is None:
            continue
        triggers.append(trigger)
    return bool(triggers) and all(item["ok"] for item in triggers), triggers


def _release_trigger_for_mapping(
    props: dict[str, Any],
    *,
    swsd_node_id: str,
    rcsd_node_id: str,
    swsd_points: dict[str, Any],
    rcsd_points: dict[str, Any],
    surface_status: dict[str, tuple[str, str, Any]],
    swsd_anchor_nodes: set[str],
    point_source: str | None = None,
    t05_relation_by_target: dict[str, str] | None = None,
    rcsd_semantic_ids_by_node: dict[str, set[str]] | None = None,
) -> dict[str, Any] | None:
    if swsd_node_id not in swsd_points or rcsd_node_id not in rcsd_points:
        return None
    distance_m = float(swsd_points[swsd_node_id].distance(rcsd_points[rcsd_node_id]))
    t05_release = _is_t05_semantic_relation_mapping(
        swsd_node_id,
        rcsd_node_id,
        t05_relation_by_target or {},
        rcsd_semantic_ids_by_node or {},
    )
    status = surface_status.get(swsd_node_id)
    if t05_release:
        ok = True
        release_status = ["pass", T05_SEMANTIC_JUNCTION_RELEASE_REASON, round(distance_m, 3)]
    elif distance_m <= RETAINED_JUNCTION_ATTACHMENT_GAP_M:
        return None
    elif status:
        ok = bool(status[0] == "pass" and status[1] in SURFACE_RELEASE_REASONS)
        release_status = list(status)
    elif _is_original_pair_endpoint_mapping(props, swsd_node_id, rcsd_node_id):
        ok = True
        release_status = ["pass", "auto_closed_selected_replacement_endpoint", round(distance_m, 3)]
    elif _is_optional_junc_anchor_mapping(props, swsd_node_id, rcsd_node_id, swsd_anchor_nodes, distance_m):
        ok = True
        release_status = ["pass", OPTIONAL_JUNCTION_ANCHOR_RELEASE_REASON, round(distance_m, 3)]
    else:
        ok = False
        release_status = None
    trigger = {
        "swsd_node_id": swsd_node_id,
        "rcsd_node_id": rcsd_node_id,
        "distance_m": round(distance_m, 3),
        "surface_status": release_status,
        "ok": ok,
    }
    if point_source:
        trigger["point_source"] = point_source
    return trigger


def _is_t05_semantic_relation_mapping(
    swsd_node_id: str,
    rcsd_node_id: str,
    t05_relation_by_target: dict[str, str],
    rcsd_semantic_ids_by_node: dict[str, set[str]],
) -> bool:
    base_id = t05_relation_by_target.get(swsd_node_id)
    if not base_id:
        return False
    semantic_ids = rcsd_semantic_ids_by_node.get(rcsd_node_id, {rcsd_node_id})
    return base_id in semantic_ids


def _is_retained_junction_gate_plan(props: dict[str, Any]) -> bool:
    return props.get("source_reason") == RETAINED_JUNCTION_GATE_REASON or RETAINED_JUNCTION_GATE_REASON in set(_ids(props.get("risk_flags")))


def _is_original_pair_endpoint_mapping(props: dict[str, Any], swsd_node_id: str, rcsd_node_id: str) -> bool:
    swsd_pair_nodes = _ids(props.get("swsd_pair_nodes"))
    original_rcsd_pair_nodes = _ids(props.get("original_rcsd_pair_nodes"))
    if len(swsd_pair_nodes) != len(original_rcsd_pair_nodes):
        return False
    return any(swsd_node_id == swsd and rcsd_node_id == rcsd for swsd, rcsd in zip(swsd_pair_nodes, original_rcsd_pair_nodes))


def _is_optional_junc_anchor_mapping(
    props: dict[str, Any],
    swsd_node_id: str,
    rcsd_node_id: str,
    swsd_anchor_nodes: set[str],
    distance_m: float,
) -> bool:
    if swsd_node_id not in swsd_anchor_nodes or distance_m > OPTIONAL_JUNCTION_ANCHOR_RELEASE_MAX_GAP_M:
        return False
    swsd_junc = _ids(props.get("optional_junc_nodes")) or _ids(props.get("swsd_junc_nodes"))
    rcsd_junc = _ids(props.get("optional_junc_rcsd_nodes")) or _ids(props.get("rcsd_junc_nodes"))
    return any(swsd_node_id == swsd and rcsd_node_id == rcsd for swsd, rcsd in zip(swsd_junc, rcsd_junc))


def _release_plan_row(props: dict[str, Any]) -> None:
    props["plan_status"] = "ready"
    props["execution_action"] = "replace"
    if props.get("execution_scope") == "path_corridor_group":
        props["source_reason"] = "passed"
    else:
        props["source_reason"] = props.get("replacement_strategy") or "buffer_segment_extraction"
    props["risk_flags"] = unique_preserve_order([*_ids(props.get("risk_flags")), RETAINED_JUNCTION_GATE_REASON, SURFACE_RELEASE_RISK])
    notes = str(props.get("notes") or "")
    notes = notes.replace(f"; blocked by {RETAINED_JUNCTION_GATE_REASON}", "")
    notes = notes.replace(f"blocked by {RETAINED_JUNCTION_GATE_REASON}", "")
    suffix = f"risk: {RETAINED_JUNCTION_GATE_REASON}; risk: {SURFACE_RELEASE_RISK}"
    props["notes"] = f"{notes.strip('; ')}; {suffix}" if notes.strip("; ") else suffix


def _surface_status_by_node(step_root: Path) -> dict[str, tuple[str, str, Any]]:
    path = step_root / "t06_step3_surface_topology_audit.gpkg"
    if not path.is_file():
        return {}
    result: dict[str, tuple[str, str, Any]] = {}
    for row in read_features(path):
        props = row.get("properties") or {}
        node_id = str(props.get("swsd_node_id") or "")
        if node_id:
            result[node_id] = (str(props.get("audit_status") or ""), str(props.get("audit_reason") or ""), props.get("max_pairwise_distance_m"))
    return result


def _t05_relation_targets_for_step(step_root: Path) -> dict[str, str]:
    step2_replaceable_path = _summary_input_path(step_root / "t06_step3_summary.json", "step2_replaceable_path")
    if step2_replaceable_path is None:
        return {}
    relation_path = discover_intersection_match_path(step2_replaceable_path)
    if relation_path is None:
        return {}
    return valid_t05_relation_targets(relation_path)


def _semantic_ids_by_node(rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for row in rows:
        exact_ids = _feature_exact_ids(row)
        if not exact_ids:
            continue
        node_id = exact_ids[0]
        result[node_id] = set(_feature_ids(row))
    return result


def _summary_input_path(summary_path: Path, key: str) -> Path | None:
    if not summary_path.is_file():
        return None
    value = (json.loads(summary_path.read_text(encoding="utf-8")).get("input_paths") or {}).get(key)
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path


def _points_by_id(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in rows:
        geom = row.get("geometry")
        if geom is None:
            continue
        for item_id in _feature_exact_ids(row):
            result[item_id] = geom
    for row in rows:
        geom = row.get("geometry")
        if geom is None:
            continue
        for item_id in _feature_fallback_ids(row):
            result.setdefault(item_id, geom)
    return result


def _fallback_points_by_id(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in rows:
        geom = row.get("geometry")
        if geom is None:
            continue
        for item_id in _feature_fallback_ids(row):
            result[item_id] = geom
    return result


def _incident_segments_by_node(segments: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for segment in segments:
        props = segment.get("properties") or {}
        segment_id = _feature_id(segment)
        for node_id in unique_preserve_order([*_ids(props.get("pair_nodes")), *_ids(props.get("junc_nodes"))]):
            result[node_id] = unique_preserve_order([*result.get(node_id, []), segment_id])
    return result


def _ready_segment_ids(rows: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in rows:
        props = row.get("properties") or {}
        if props.get("plan_status") != "ready":
            continue
        if props.get("execution_scope") == "path_corridor_group":
            result.update(_ids(props.get("group_segment_ids")))
        elif props.get("swsd_segment_id"):
            result.add(str(props.get("swsd_segment_id")))
    return result


def _plan_mappings(props: dict[str, Any]) -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for swsd_node_id, rcsd_node_id in zip(_ids(props.get("swsd_pair_nodes")), _ids(props.get("rcsd_pair_nodes"))):
        result.append((swsd_node_id, rcsd_node_id))
    swsd_junc = _ids(props.get("optional_junc_nodes")) or _ids(props.get("swsd_junc_nodes"))
    rcsd_junc = _ids(props.get("optional_junc_rcsd_nodes")) or _ids(props.get("rcsd_junc_nodes"))
    for swsd_node_id, rcsd_node_id in zip(swsd_junc, rcsd_junc):
        result.append((swsd_node_id, rcsd_node_id))
    return result


def _feature_id(feature: dict[str, Any]) -> str:
    ids = _feature_ids(feature)
    return ids[0] if ids else ""


def _feature_ids(feature: dict[str, Any]) -> list[str]:
    return unique_preserve_order([*_feature_exact_ids(feature), *_feature_fallback_ids(feature)])


def _feature_exact_ids(feature: dict[str, Any]) -> list[str]:
    props = feature.get("properties") or {}
    return unique_preserve_order(
        str(value)
        for value in (props.get("id"), props.get("node_id"), props.get("swsd_segment_id"))
        if value not in (None, "")
    )


def _feature_fallback_ids(feature: dict[str, Any]) -> list[str]:
    props = feature.get("properties") or {}
    return unique_preserve_order(
        str(value)
        for value in (props.get("mainnodeid"),)
        if value not in (None, "")
    )


def _anchor_node_ids(rows: list[dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for row in rows:
        props = row.get("properties") or {}
        if not _truthy_anchor(props.get("is_anchor")):
            continue
        result.update(_feature_ids(row))
    result.discard("")
    return result


def _truthy_anchor(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _ids(value: Any) -> list[str]:
    try:
        return parse_id_list(value)
    except Exception:
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        return []
