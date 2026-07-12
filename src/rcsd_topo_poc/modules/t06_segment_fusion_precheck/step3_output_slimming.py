from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .io import write_json
from .schemas import STEP3_SUMMARY


DETAIL_METRICS_NAME = "t06_step3_detail_metrics.json"
OUTPUT_MANIFEST_NAME = "t06_step3_output_manifest.json"
COMPACT_SCHEMA_VERSION = "t06_step3_summary_compact_v1"

CORE_OUTPUT_KEYS = {
    "frcsd_road_gpkg",
    "frcsd_road_csv",
    "frcsd_node_gpkg",
    "frcsd_node_csv",
    "replacement_units_gpkg",
    "replacement_units_csv",
    "swsd_frcsd_segment_relation_gpkg",
    "swsd_frcsd_segment_relation_csv",
    "semantic_junction_groups_gpkg",
    "semantic_junction_groups_csv",
    "junction_rebuild_audit_gpkg",
    "junction_rebuild_audit_csv",
    "removed_swsd_roads_gpkg",
    "removed_swsd_roads_csv",
    "removed_swsd_nodes_gpkg",
    "removed_swsd_nodes_csv",
    "added_rcsd_roads_gpkg",
    "added_rcsd_roads_csv",
    "added_rcsd_nodes_gpkg",
    "added_rcsd_nodes_csv",
    "unreplaced_rcsd_roads_gpkg",
    "unreplaced_rcsd_roads_csv",
    "id_collision_audit_gpkg",
    "id_collision_audit_csv",
    "advance_right_attachment_audit_gpkg",
    "advance_right_attachment_audit_csv",
    "rcsd_advance_right_closure_audit_gpkg",
    "rcsd_advance_right_closure_audit_csv",
    "topology_connectivity_audit_gpkg",
    "topology_connectivity_audit_csv",
    "surface_topology_audit_gpkg",
    "surface_topology_summary_json",
    "surface_aware_plan_release_audit_json",
    "unreplaced_rcsd_attribution_gpkg",
    "unreplaced_rcsd_attribution_summary",
    "rcsd_road_ownership_gpkg",
    "rcsd_road_ownership_csv",
    "multi_segment_connectivity_group_gpkg",
    "multi_segment_connectivity_group_csv",
    "segment_construction_audit_gpkg",
    "segment_construction_audit_csv",
}

SUMMARY_OUTPUT_KEYS = {
    "frcsd_road_gpkg",
    "frcsd_node_gpkg",
    "swsd_frcsd_segment_relation_gpkg",
    "topology_connectivity_audit_gpkg",
    "topology_connectivity_audit_csv",
    "surface_topology_audit_gpkg",
    "surface_topology_summary_json",
    "surface_aware_plan_release_audit_json",
    "unreplaced_rcsd_attribution_gpkg",
    "unreplaced_rcsd_attribution_summary",
    "rcsd_road_ownership_gpkg",
    "multi_segment_connectivity_group_gpkg",
    "segment_construction_audit_gpkg",
}

COMPAT_TOP_LEVEL_KEYS = [
    "input_replaceable_count",
    "input_replacement_plan_count",
    "input_standard_replacement_plan_count",
    "replacement_plan_source",
    "replacement_unit_count",
    "replacement_unit_success_count",
    "replacement_unit_failure_count",
    "special_junction_internal_swsd_group_count",
    "special_junction_internal_swsd_removed_road_count",
    "removed_swsd_road_count",
    "removed_swsd_node_count",
    "added_rcsd_road_count",
    "added_rcsd_node_count",
    "junction_c_count",
    "road_id_collision_count",
    "node_id_collision_count",
    "frcsd_road_count",
    "frcsd_node_count",
    "segment_relation_count",
    "segment_relation_replaced_count",
    "segment_relation_mixed_count",
    "segment_relation_retained_swsd_count",
    "segment_relation_failed_count",
    "topology_connectivity_fail_count",
    "topology_connectivity_warn_count",
    "topology_connectivity_pass_count",
    "topology_audit_fail_row_count",
    "final_frcsd_topology_fail_row_count",
    "final_frcsd_topology_fail_count",
    "final_frcsd_segment_transition_fail_count",
    "final_frcsd_independent_attachment_fail_count",
    "surface_topology_fail_count",
    "surface_topology_pass_count",
    "surface_topology_status",
    "rcsd_unreplaced_attribution_count",
    "rcsd_unreplaced_attribution_length_m",
    "rcsd_unreplaced_attribution_by_class",
    "rcsd_unreplaced_final_attribution_by_class",
    "rcsd_unreplaced_final_attribution_by_confidence",
    "rcsd_unreplaced_ppt_attribution_by_class",
    "rcsd_road_total_count",
    "rcsd_road_used_count",
    "rcsd_road_used_length_m",
    "connectivity_group_count",
    "connectivity_group_used_count",
    "connectivity_rcsd_road_used_count",
    "reality_change_rcsd_road_count",
    "unresolved_exception_rcsd_road_count",
    "ownership_duplicate_count",
    "ownership_missing_count",
    "advance_right_segment_used_count",
    "advance_right_rcsd_road_used_count",
    "normal_segment_count",
    "normal_segment_replaceable_count",
    "normal_segment_replaced_count",
    "advance_right_segment_count",
]


def compact_step3_outputs(step_root: str | Path) -> dict[str, Any]:
    root = Path(step_root)
    summary_path = root / STEP3_SUMMARY
    if not summary_path.is_file():
        return {}
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return {}

    detail = _detail_payload(root, payload)
    detail_path = root / DETAIL_METRICS_NAME
    write_json(detail_path, detail)

    manifest_path = root / OUTPUT_MANIFEST_NAME
    compact = _compact_summary(
        payload=detail,
        detail_path=detail_path,
        manifest_path=manifest_path,
    )
    write_json(summary_path, compact)
    write_json(manifest_path, _output_manifest(root, payload))
    return compact


def retire_intermediate_step3_plan(candidate_path: Path | None, final_path: Path | None) -> bool:
    if candidate_path is None or final_path is None:
        return False
    if candidate_path == final_path or not candidate_path.exists():
        return False
    candidate_path.unlink()
    return True


def _detail_payload(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("summary_schema") != COMPACT_SCHEMA_VERSION:
        return payload
    detail_path = Path(str(payload.get("detail_metrics_json") or root / DETAIL_METRICS_NAME))
    if detail_path.is_file():
        detail = json.loads(detail_path.read_text(encoding="utf-8"))
        if isinstance(detail, dict):
            return _merge_compact_overlay(detail, payload)
    return payload


def _merge_compact_overlay(detail: dict[str, Any], compact: dict[str, Any]) -> dict[str, Any]:
    result = dict(detail)
    for key in COMPAT_TOP_LEVEL_KEYS:
        if key in compact:
            result[key] = compact[key]
    outputs = dict(result.get("outputs") or {})
    outputs.update(compact.get("outputs") or {})
    result["outputs"] = outputs
    if "surface_aware_plan_release" in compact:
        result["surface_aware_plan_release"] = compact["surface_aware_plan_release"]
    return result


def _compact_summary(*, payload: dict[str, Any], detail_path: Path, manifest_path: Path) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "summary_schema": COMPACT_SCHEMA_VERSION,
        "run_id": payload.get("run_id"),
        "status": _status(payload),
        "input_paths": payload.get("input_paths") or {},
        "params": payload.get("params") or {},
        "funnel": _section(payload, [
            "input_replaceable_count",
            "input_replacement_plan_count",
            "input_standard_replacement_plan_count",
            "replacement_plan_source",
            "replacement_unit_count",
            "replacement_unit_success_count",
            "replacement_unit_failure_count",
        ]),
        "final_frcsd": _section(payload, [
            "frcsd_road_count",
            "frcsd_node_count",
            "special_junction_internal_swsd_group_count",
            "special_junction_internal_swsd_removed_road_count",
            "removed_swsd_road_count",
            "removed_swsd_node_count",
            "added_rcsd_road_count",
            "added_rcsd_node_count",
            "unreplaced_rcsd_road_count",
            "unreplaced_rcsd_road_length_m",
        ]),
        "relation": _section(payload, [
            "segment_relation_count",
            "segment_relation_replaced_count",
            "segment_relation_retained_swsd_count",
            "segment_relation_failed_count",
            "relation_node_map_backfilled_entry_count",
            "relation_node_map_backfilled_row_count",
        ]),
        "topology": _topology_section(payload),
        "surface_topology": _scalar_prefixed_section(payload, "surface_topology_"),
        "advance_right": _advance_right_section(payload),
        "rcsd_unreplaced_attribution": _section(payload, [
            "rcsd_unreplaced_attribution_count",
            "rcsd_unreplaced_attribution_length_m",
            "rcsd_unreplaced_attribution_by_class",
            "rcsd_unreplaced_final_attribution_by_class",
            "rcsd_unreplaced_final_attribution_by_confidence",
            "rcsd_unreplaced_ppt_attribution_by_class",
        ]),
        "rcsd_road_ownership": _section(payload, [
            "rcsd_road_total_count",
            "rcsd_road_used_count",
            "rcsd_road_used_length_m",
            "connectivity_group_count",
            "connectivity_group_used_count",
            "connectivity_rcsd_road_used_count",
            "reality_change_rcsd_road_count",
            "unresolved_exception_rcsd_road_count",
            "ownership_duplicate_count",
            "ownership_missing_count",
            "advance_right_segment_used_count",
            "advance_right_rcsd_road_used_count",
        ]),
        "segment_construction": _section(payload, [
            "normal_segment_count",
            "normal_segment_replaceable_count",
            "normal_segment_replaced_count",
            "advance_right_segment_count",
            "segment_construction_class_counts",
        ]),
        "surface_aware_plan_release": _surface_release_section(payload),
        "outputs": _summary_outputs(payload),
        "detail_metrics_json": str(detail_path),
        "output_manifest_json": str(manifest_path),
        "output_policy": {
            "default_feature_json_outputs": "suppressed",
            "visual_layers": "gpkg",
            "tabular_audits": "csv",
            "detail_metrics": DETAIL_METRICS_NAME,
            "complete_output_paths": OUTPUT_MANIFEST_NAME,
        },
        "gis_topology_checks": payload.get("gis_topology_checks") or {},
    }
    for key in COMPAT_TOP_LEVEL_KEYS:
        if key in payload:
            compact[key] = payload[key]
    return compact


def _status(payload: dict[str, Any]) -> str:
    if int(payload.get("replacement_unit_failure_count") or 0) > 0:
        return "completed_with_failed_units"
    topology_fail_count = payload.get("final_frcsd_topology_fail_count")
    if topology_fail_count is None:
        topology_fail_count = payload.get("topology_connectivity_fail_count")
    if int(topology_fail_count or 0) > 0:
        return "completed_with_topology_failures"
    return "completed"


def _section(payload: dict[str, Any], keys: list[str]) -> dict[str, Any]:
    return {key: payload.get(key) for key in keys if key in payload}


def _prefixed_section(payload: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {key.removeprefix(prefix): value for key, value in payload.items() if key.startswith(prefix)}


def _scalar_prefixed_section(payload: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {
        key.removeprefix(prefix): value
        for key, value in payload.items()
        if key.startswith(prefix) and _is_summary_scalar(value)
    }


def _advance_right_section(payload: dict[str, Any]) -> dict[str, Any]:
    keys = [
        key
        for key in payload
        if key.startswith("advance_right_")
        or key.startswith("post_advance_right_")
        or key.startswith("rcsd_advance_right_")
    ]
    return {key: payload.get(key) for key in sorted(keys) if _is_summary_scalar(payload.get(key))}


def _topology_section(payload: dict[str, Any]) -> dict[str, Any]:
    result = {
        key.removeprefix("topology_connectivity_"): value
        for key, value in payload.items()
        if key.startswith("topology_connectivity_")
    }
    for key in (
        "topology_audit_fail_row_count",
        "final_frcsd_topology_fail_row_count",
        "final_frcsd_topology_fail_count",
        "final_frcsd_segment_transition_fail_count",
        "final_frcsd_independent_attachment_fail_count",
    ):
        if key in payload:
            result[key] = payload[key]
    return result


def _core_outputs(payload: dict[str, Any]) -> dict[str, str]:
    outputs = payload.get("outputs") or {}
    if not isinstance(outputs, dict):
        return {}
    return {key: str(value) for key, value in outputs.items() if key in CORE_OUTPUT_KEYS and value}


def _summary_outputs(payload: dict[str, Any]) -> dict[str, str]:
    outputs = payload.get("outputs") or {}
    if not isinstance(outputs, dict):
        return {}
    return {key: str(value) for key, value in outputs.items() if key in SUMMARY_OUTPUT_KEYS and value}


def _surface_release_section(payload: dict[str, Any]) -> dict[str, Any]:
    release = payload.get("surface_aware_plan_release") or {}
    if not isinstance(release, dict):
        return {}
    result = {
        key: value
        for key, value in release.items()
        if key.endswith("_count") or key in {"status", "full_step3_run_count", "extra_step3_run_count", "candidate_step3_run_count", "fallback_step3_run_count", "max_fallback_step3_run_count", "candidate_plan_retired"}
    }
    visual = release.get("visual_conflict_release") or {}
    if isinstance(visual, dict):
        result["visual_conflict_release"] = {
            key: value
            for key, value in visual.items()
            if key.endswith("_count")
        }
    return result


def _is_summary_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _output_manifest(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    outputs = payload.get("outputs") or {}
    output_by_path = {str(Path(str(value))): key for key, value in outputs.items()} if isinstance(outputs, dict) else {}
    files = []
    for path in sorted(root.glob("*")):
        if not path.is_file():
            continue
        output_key = output_by_path.get(str(path))
        files.append(
            {
                "path": str(path),
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "format": path.suffix.lower().lstrip("."),
                "output_key": output_key,
                "role": _artifact_role(path.name, output_key),
                "core": bool(output_key in CORE_OUTPUT_KEYS),
            }
        )
    return {
        "schema": "t06_step3_output_manifest_v1",
        "run_id": payload.get("run_id"),
        "file_count": len(files),
        "total_size_bytes": sum(int(item["size_bytes"]) for item in files),
        "files": files,
    }


def _artifact_role(name: str, output_key: str | None) -> str:
    if output_key in CORE_OUTPUT_KEYS:
        return "core"
    if name.endswith(".json") and "_replacement_plan_" in name:
        return "replay_plan"
    if name.endswith(".json"):
        return "summary_or_detail"
    if name.endswith(".gpkg"):
        return "visual_audit"
    if name.endswith(".csv"):
        return "table_audit"
    return "auxiliary"
