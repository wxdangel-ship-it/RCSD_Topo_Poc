from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import read_features, write_json
from .parsing import parse_id_list, unique_preserve_order
from .step3_segment_replacement import T06Step3Artifacts, run_t06_step3_segment_replacement
from .step3_topology_connectivity_audit import STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM
from .step3_surface_topology_audit import run_surface_topology_postprocess


RETAINED_JUNCTION_GATE_REASON = "junction_alignment_to_retained_swsd_exceeds_topology_gate"
SURFACE_RELEASE_RISK = "junction_alignment_surface_audit_release"
SURFACE_RELEASE_ROLLBACK_REASON = "junction_alignment_surface_release_failed_topology_gate"
SURFACE_RELEASE_PLAN_STEM = "t06_step3_surface_aware_replacement_plan"
SURFACE_RELEASE_AUDIT = "t06_step3_surface_aware_plan_release_audit.json"
RETAINED_JUNCTION_ATTACHMENT_GAP_M = 20.0
OPTIONAL_JUNCTION_ANCHOR_RELEASE_MAX_GAP_M = 50.0
OPTIONAL_JUNCTION_ANCHOR_RELEASE_REASON = "auto_closed_step2_optional_junc_anchor"
SURFACE_RELEASE_REASONS = {
    "auto_closed_surface_1v1",
    "auto_closed_t04_patch_1v1",
    "auto_closed_step2_junc_1v1",
    "auto_closed_relation_mapped_boundary_1v1",
    "auto_closed_selected_replacement_endpoint",
    OPTIONAL_JUNCTION_ANCHOR_RELEASE_REASON,
}


def run_surface_aware_step3_segment_replacement(
    *,
    step2_replaceable_path: str | Path,
    step2_special_junction_group_audit_path: str | Path | None,
    step2_group_replacement_audit_path: str | Path | None,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    swsd_nodes_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str | None,
    surface_inputs: dict[str, Path | None],
    surface_topology_closure: bool,
    progress: bool,
) -> tuple[T06Step3Artifacts, dict[str, Any] | None]:
    artifacts = _run_step3(
        step2_replaceable_path=step2_replaceable_path,
        step2_special_junction_group_audit_path=step2_special_junction_group_audit_path,
        step2_group_replacement_audit_path=step2_group_replacement_audit_path,
        step2_replacement_plan_path=None,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        swsd_nodes_path=swsd_nodes_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id=run_id,
        progress=progress,
    )
    surface_summary = _run_surface(
        artifacts,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        surface_inputs=surface_inputs,
        surface_topology_closure=surface_topology_closure,
    )
    if not any(surface_inputs.values()):
        return artifacts, surface_summary

    original_plan_path = _summary_input_path(artifacts.summary_path, "step2_replacement_plan_path")
    if original_plan_path is None or not original_plan_path.is_file():
        _write_release_audit(artifacts.step_root, {"status": "skipped", "reason": "missing_replacement_plan"})
        return artifacts, surface_summary

    baseline_fail_keys = _topology_fail_keys(artifacts.step_root)
    external_baseline_root = _external_baseline_step3_root(step2_replaceable_path, artifacts.step_root)
    external_baseline_fail_keys = _topology_fail_keys(external_baseline_root) if external_baseline_root else set()
    plan_rows = read_features(original_plan_path)
    release_rows, released = _surface_release_plan_rows(
        plan_rows,
        step_root=artifacts.step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_nodes_path=swsd_nodes_path,
        rcsdnode_path=rcsdnode_path,
    )
    if not released:
        _write_release_audit(
            artifacts.step_root,
            {
                "status": "no_release",
                "baseline_fail_count": len(baseline_fail_keys),
                "external_baseline_fail_count": len(external_baseline_fail_keys) if external_baseline_root else None,
                "released_count": 0,
            },
        )
        return artifacts, surface_summary

    released_plan = _write_plan_json(artifacts.step_root, release_rows, "candidate")
    artifacts = _run_step3(
        step2_replaceable_path=step2_replaceable_path,
        step2_special_junction_group_audit_path=step2_special_junction_group_audit_path,
        step2_group_replacement_audit_path=step2_group_replacement_audit_path,
        step2_replacement_plan_path=released_plan,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        swsd_nodes_path=swsd_nodes_path,
        rcsdroad_path=rcsdroad_path,
        rcsdnode_path=rcsdnode_path,
        out_root=out_root,
        run_id=run_id,
        progress=progress,
    )
    surface_summary = _run_surface(
        artifacts,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        surface_inputs=surface_inputs,
        surface_topology_closure=surface_topology_closure,
    )
    added_fail_keys = _topology_fail_keys(artifacts.step_root) - baseline_fail_keys
    rollback_plan_ids = _rollback_plan_ids(added_fail_keys, released, swsd_segment_path)
    if rollback_plan_ids:
        final_rows = _rollback_release_rows(release_rows, rollback_plan_ids)
        final_plan = _write_plan_json(artifacts.step_root, final_rows, "topology_safe")
        artifacts = _run_step3(
            step2_replaceable_path=step2_replaceable_path,
            step2_special_junction_group_audit_path=step2_special_junction_group_audit_path,
            step2_group_replacement_audit_path=step2_group_replacement_audit_path,
            step2_replacement_plan_path=final_plan,
            swsd_segment_path=swsd_segment_path,
            swsd_roads_path=swsd_roads_path,
            swsd_nodes_path=swsd_nodes_path,
            rcsdroad_path=rcsdroad_path,
            rcsdnode_path=rcsdnode_path,
            out_root=out_root,
            run_id=run_id,
            progress=progress,
        )
        surface_summary = _run_surface(
            artifacts,
            swsd_segment_path=swsd_segment_path,
            swsd_roads_path=swsd_roads_path,
            surface_inputs=surface_inputs,
            surface_topology_closure=surface_topology_closure,
        )

    final_fail_keys = _topology_fail_keys(artifacts.step_root)
    external_added_fail_keys = final_fail_keys - external_baseline_fail_keys if external_baseline_root else set()
    audit = {
        "status": "applied_with_external_topology_regression" if external_added_fail_keys else "applied",
        "baseline_fail_count": len(baseline_fail_keys),
        "candidate_added_fail_count": len(added_fail_keys),
        "final_fail_count": len(final_fail_keys),
        "final_added_fail_count": len(final_fail_keys - baseline_fail_keys),
        "external_baseline_path": str(external_baseline_root) if external_baseline_root else None,
        "external_baseline_fail_count": len(external_baseline_fail_keys) if external_baseline_root else None,
        "external_final_added_fail_count": len(external_added_fail_keys),
        "external_final_added_fail_keys": [list(item) for item in sorted(external_added_fail_keys)],
        "released_count": len(released),
        "rolled_back_count": len(rollback_plan_ids),
        "released": released,
        "rolled_back_plan_ids": sorted(rollback_plan_ids),
    }
    _write_release_audit(artifacts.step_root, audit)
    _merge_release_summary(artifacts.summary_path, audit)
    return artifacts, surface_summary


def _run_step3(**kwargs: Any) -> T06Step3Artifacts:
    return run_t06_step3_segment_replacement(**kwargs)


def _run_surface(
    artifacts: T06Step3Artifacts,
    *,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    surface_inputs: dict[str, Path | None],
    surface_topology_closure: bool,
) -> dict[str, Any] | None:
    if not any(surface_inputs.values()):
        return None
    return run_surface_topology_postprocess(
        step_root=artifacts.step_root,
        swsd_segment_path=swsd_segment_path,
        swsd_roads_path=swsd_roads_path,
        t07_surface_path=surface_inputs.get("t07_surface_path"),
        t03_surface_path=surface_inputs.get("t03_surface_path"),
        t04_surface_path=surface_inputs.get("t04_surface_path"),
        t04_audit_path=surface_inputs.get("t04_audit_path"),
        t05_surface_path=surface_inputs.get("t05_surface_path"),
        apply_closure=surface_topology_closure,
    )


def _surface_release_plan_rows(
    plan_rows: list[dict[str, Any]],
    *,
    step_root: Path,
    swsd_segment_path: str | Path,
    swsd_nodes_path: str | Path,
    rcsdnode_path: str | Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    surface_status = _surface_status_by_node(step_root)
    swsd_node_rows = read_features(swsd_nodes_path)
    swsd_points = _points_by_id(swsd_node_rows)
    swsd_anchor_nodes = _anchor_node_ids(swsd_node_rows)
    rcsd_points = _points_by_id(read_features(rcsdnode_path))
    incident = _incident_segments_by_node(read_features(swsd_segment_path))
    ready_segments = _ready_segment_ids(plan_rows)
    released: list[dict[str, Any]] = []
    rows = [{"properties": dict(row.get("properties") or {}), "geometry": row.get("geometry")} for row in plan_rows]
    for row in rows:
        props = row["properties"]
        if props.get("source_reason") != RETAINED_JUNCTION_GATE_REASON:
            continue
        allow, triggers = _release_allowed(
            props,
            surface_status,
            swsd_points,
            rcsd_points,
            incident,
            ready_segments,
            swsd_anchor_nodes,
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


def _release_allowed(
    props: dict[str, Any],
    surface_status: dict[str, tuple[str, str, Any]],
    swsd_points: dict[str, Any],
    rcsd_points: dict[str, Any],
    incident: dict[str, list[str]],
    ready_segments: set[str],
    swsd_anchor_nodes: set[str] | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    if not _is_retained_junction_gate_plan(props):
        return False, []
    swsd_anchor_nodes = swsd_anchor_nodes or set()
    triggers: list[dict[str, Any]] = []
    for swsd_node_id, rcsd_node_id in _plan_mappings(props):
        if swsd_node_id not in swsd_points or rcsd_node_id not in rcsd_points:
            continue
        if not any(segment_id not in ready_segments for segment_id in incident.get(swsd_node_id, [])):
            continue
        distance_m = float(swsd_points[swsd_node_id].distance(rcsd_points[rcsd_node_id]))
        if distance_m <= RETAINED_JUNCTION_ATTACHMENT_GAP_M:
            continue
        status = surface_status.get(swsd_node_id)
        if status:
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
        triggers.append(
            {
                "swsd_node_id": swsd_node_id,
                "rcsd_node_id": rcsd_node_id,
                "distance_m": round(distance_m, 3),
                "surface_status": release_status,
                "ok": ok,
            }
        )
    return bool(triggers) and all(item["ok"] for item in triggers), triggers


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


def _rollback_release_rows(rows: list[dict[str, Any]], rollback_plan_ids: set[str]) -> list[dict[str, Any]]:
    for row in rows:
        props = row.get("properties") or {}
        if str(props.get("replacement_plan_id") or "") not in rollback_plan_ids:
            continue
        props["plan_status"] = "blocked"
        props["execution_action"] = "hold"
        props["source_reason"] = SURFACE_RELEASE_ROLLBACK_REASON
        props["risk_flags"] = unique_preserve_order([*_ids(props.get("risk_flags")), SURFACE_RELEASE_ROLLBACK_REASON])
        notes = str(props.get("notes") or "")
        suffix = f"blocked by {SURFACE_RELEASE_ROLLBACK_REASON}"
        props["notes"] = f"{notes}; {suffix}" if notes else suffix
    return rows


def _rollback_plan_ids(
    added_fail_keys: set[tuple[str, str, str, str, str]],
    released: list[dict[str, Any]],
    swsd_segment_path: str | Path,
) -> set[str]:
    incident = _incident_segments_by_node(read_features(swsd_segment_path))
    return _rollback_plan_ids_for_failed_segments(added_fail_keys, released, incident)


def _rollback_plan_ids_for_failed_segments(
    added_fail_keys: set[tuple[str, str, str, str, str]],
    released: list[dict[str, Any]],
    incident: dict[str, list[str]],
) -> set[str]:
    if not added_fail_keys:
        return set()
    failed_segments: set[str] = set()
    for _layer, segment_id, node_id, _road_id, _reason in added_fail_keys:
        if segment_id:
            failed_segments.add(segment_id)
        if node_id:
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


def _topology_fail_keys(step_root: Path) -> set[tuple[str, str, str, str, str]]:
    path = step_root / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.gpkg"
    if not path.is_file():
        return set()
    result: set[tuple[str, str, str, str, str]] = set()
    for row in read_features(path):
        props = row.get("properties") or {}
        if props.get("audit_status") != "fail":
            continue
        result.add(
            (
                str(props.get("audit_layer") or ""),
                str(props.get("swsd_segment_id") or ""),
                str(props.get("swsd_node_id") or ""),
                str(props.get("frcsd_road_id") or ""),
                str(props.get("audit_reason") or ""),
            )
        )
    return result


def _write_plan_json(step_root: Path, rows: list[dict[str, Any]], label: str) -> Path:
    path = step_root / f"{SURFACE_RELEASE_PLAN_STEM}_{label}.json"
    write_json(path, {"row_count": len(rows), "features": rows})
    return path


def _write_release_audit(step_root: Path, payload: dict[str, Any]) -> None:
    write_json(step_root / SURFACE_RELEASE_AUDIT, payload)


def _merge_release_summary(summary_path: Path, audit: dict[str, Any]) -> None:
    if not summary_path.is_file():
        return
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    payload["surface_aware_plan_release"] = audit
    outputs = dict(payload.get("outputs") or {})
    outputs["surface_aware_plan_release_audit_json"] = str(summary_path.parent / SURFACE_RELEASE_AUDIT)
    payload["outputs"] = outputs
    write_json(summary_path, payload)


def _summary_input_path(summary_path: Path, key: str) -> Path | None:
    if not summary_path.is_file():
        return None
    value = (json.loads(summary_path.read_text(encoding="utf-8")).get("input_paths") or {}).get(key)
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else Path.cwd() / path


def _external_baseline_step3_root(step2_replaceable_path: str | Path, current_step_root: Path) -> Path | None:
    step2_root = Path(step2_replaceable_path).resolve().parent
    run_root = step2_root.parent
    candidate = run_root / "step3_segment_replacement"
    if candidate.resolve() == current_step_root.resolve():
        return None
    path = candidate / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.gpkg"
    return candidate if path.is_file() else None


def _points_by_id(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for row in rows:
        geom = row.get("geometry")
        if geom is None:
            continue
        for item_id in _feature_ids(row):
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
    props = feature.get("properties") or {}
    return unique_preserve_order(
        str(value)
        for value in (props.get("id"), props.get("node_id"), props.get("mainnodeid"), props.get("swsd_segment_id"))
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
