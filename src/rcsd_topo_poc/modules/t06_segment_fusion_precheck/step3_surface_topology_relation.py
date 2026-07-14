from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point
from shapely.ops import linemerge, substring

from .io import clear_read_features_cache, read_features, write_feature_triplet, write_json
from .parsing import normalize_id, unique_preserve_order
from .schemas import (
    STEP2_FAILURE_BUSINESS_AUDIT_STEM,
    STEP2_REPLACEMENT_PLAN_STEM,
    STEP3_FRCSD_NODE_STEM,
    STEP3_FRCSD_ROAD_STEM,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
)
from .step3_relation_node_map import sync_retained_swsd_carrier_mainnodes
from .step3_surface_runtime import Step3SurfaceRuntimeState
from .step3_authoritative_transition_closure import (
    _hard_gate_cascade_node_ids,
    apply_authoritative_transition_closure,
)
from .step3_topology_connectivity_audit import (
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
    build_surface_junction_connectivity_audit_rows,
    build_topology_connectivity_audit_rows,
    summarize_topology_connectivity_audit,
    transition_failure_node_ids_for_candidates,
)


SURFACE_TOPOLOGY_AUDIT_STEM = "t06_step3_surface_topology_audit"
SURFACE_TOPOLOGY_SUMMARY = "t06_step3_surface_topology_summary.json"
MAX_EXISTING_CROSS_SOURCE_1V1_DISTANCE_M = 20.0
MAX_T04_PATCH_1V1_DISTANCE_M = 20.0
MAX_RELATION_MAPPED_BOUNDARY_1V1_DISTANCE_M = 20.0
MAX_SURFACE_NEAREST_MULTI_CANDIDATE_DISTANCE_M = 5.0
MIN_SURFACE_NEAREST_MULTI_CANDIDATE_SEPARATION_M = 10.0
SURFACE_NEAREST_MULTI_CANDIDATE_LAYERS = {"t03", "t05"}
MAX_SELECTED_REPLACEMENT_ENDPOINT_DISTANCE_M = 5.0
MAX_SELECTED_REPLACEMENT_ENDPOINT_AMBIGUITY_M = 10.0
MAX_SELECTED_REPLACEMENT_MIDROAD_DISTANCE_M = 5.0
MIN_SELECTED_REPLACEMENT_MIDROAD_ENDPOINT_DISTANCE_M = 1.0
MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_CANDIDATES = 2
MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_GAP_SPREAD_M = 1.0
MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_PROJECTED_DISTANCE_M = 10.0
SELECTED_REPLACEMENT_MIDROAD_SPLIT_REASON = "surface_topology_selected_replacement_midroad"
SURFACE_TOPOLOGY_AUDIT_FIELDS = [
    "audit_layer",
    "audit_status",
    "audit_reason",
    "action",
    "swsd_node_id",
    "swsd_segment_ids",
    "frcsd_node_ids",
    "swsd_patch_ids",
    "surface_patch_ids",
    "surface_layers",
    "surface_candidate_node_ids",
    "t04_reject_reasons",
    "source1_node_count",
    "source2_node_count",
    "max_pairwise_distance_m",
    "closure_mainnodeid",
]


from .step3_surface_topology_support import (
    _load_surfaces,
    _load_t04_rejects,
    _load_step2_optional_junc_mappings,
    _load_step2_dropped_junc_nodes,
    _iter_step2_junc_rows,
    _step2_junc_roots,
    _read_step2_junc_rows,
    _road_features_by_id,
    _road_features_by_id_from_features,
    _relation_props_by_segment,
    _swsd_patch_ids_by_node,
    _node_info,
    _surface_hits,
    _surface_candidate_node_ids,
    _closure_mainnodeid,
    _has_effective_mainnode,
    _can_resolve_closure_mainnode,
    _source2_default_mainnodeid,
    _fieldnames_from_gpkg,
    _feature_id,
    _parse_id_list,
    _patch_ids,
    _safe_id,
    _float_or_none,
    _int_or_none,
    _bool_or_none,
    _distance_within,
    _points_geometry,
)

def _apply_step2_plan_relation_node_map_updates(
    *,
    step_root: Path,
    step2_junc_mappings: dict[tuple[str, str], list[str]],
    step2_dropped_junc_nodes: dict[str, list[str]],
    relation_rows: list[dict[str, Any]] | None = None,
) -> int:
    if not step2_junc_mappings and not step2_dropped_junc_nodes:
        return 0
    relation_path = step_root / f"{STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM}.gpkg"
    if relation_rows is None and not relation_path.is_file():
        return 0
    rows = relation_rows if relation_rows is not None else read_features(relation_path)
    updated = 0
    for row in rows:
        props = row.setdefault("properties", {})
        if str(props.get("relation_status") or "") == "retained_swsd":
            continue
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if not segment_id:
            continue
        entries = _node_map_entries(props.get("swsd_to_frcsd_node_map"))
        changed = False
        for dropped_node_id in step2_dropped_junc_nodes.get(segment_id, []):
            changed = _set_relation_node_map_entry(
                entries,
                swsd_node_id=dropped_node_id,
                frcsd_node_ids=[dropped_node_id],
                node_role="dropped_junc_node",
                mapping_status="identity_dropped_junc_not_consumed",
            ) or changed
        for (mapping_segment_id, swsd_node_id), rcsd_node_ids in step2_junc_mappings.items():
            if mapping_segment_id != segment_id:
                continue
            changed = _set_relation_node_map_entry(
                entries,
                swsd_node_id=swsd_node_id,
                frcsd_node_ids=rcsd_node_ids,
                node_role="junc_node",
                mapping_status="step2_optional_junc_plan_map",
            ) or changed
        if not changed:
            continue
        props["swsd_to_frcsd_node_map"] = entries
        risk_flags = _parse_id_list(props.get("risk_flags"))
        if any(node_id in step2_dropped_junc_nodes.get(segment_id, []) for node_id in [e["swsd_node_id"] for e in entries]):
            risk_flags.append("dropped_junc_retained_swsd_node_map")
        if any(mapping_segment_id == segment_id for mapping_segment_id, _node_id in step2_junc_mappings):
            risk_flags.append("step2_optional_junc_plan_node_map")
        props["risk_flags"] = unique_preserve_order(risk_flags)
        updated += 1
    if updated:
        write_feature_triplet(
            step_root=step_root,
            stem=STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
            features=rows,
            fieldnames=STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
        )
    return updated


def _set_relation_node_map_entry(
    entries: list[dict[str, Any]],
    *,
    swsd_node_id: str,
    frcsd_node_ids: list[str],
    node_role: str,
    mapping_status: str,
) -> bool:
    swsd_node_id = _safe_id(swsd_node_id)
    frcsd_node_ids = unique_preserve_order(_safe_id(node_id) for node_id in frcsd_node_ids if _safe_id(node_id))
    if not swsd_node_id or not frcsd_node_ids:
        return False
    for entry in entries:
        if _safe_id(entry.get("swsd_node_id")) != swsd_node_id:
            continue
        if (
            _parse_id_list(entry.get("frcsd_node_ids")) == frcsd_node_ids
            and str(entry.get("mapping_status") or "") == mapping_status
            and str(entry.get("node_role") or "") == node_role
        ):
            return False
        entry["frcsd_node_ids"] = frcsd_node_ids
        entry["node_role"] = node_role
        entry["mapping_status"] = mapping_status
        return True
    entries.append(
        {
            "swsd_node_id": swsd_node_id,
            "frcsd_node_ids": frcsd_node_ids,
            "node_role": node_role,
            "mapping_status": mapping_status,
        }
    )
    return True


def _apply_relation_node_map_updates(
    *,
    step_root: Path,
    updates: list[dict[str, Any]],
    relation_rows: list[dict[str, Any]] | None = None,
) -> int:
    relation_path = step_root / f"{STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM}.gpkg"
    if relation_rows is None and not relation_path.is_file():
        return 0
    relation_rows = relation_rows if relation_rows is not None else read_features(relation_path)
    updated = 0
    for row in relation_rows:
        props = row.setdefault("properties", {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if str(props.get("relation_status") or "") == "retained_swsd":
            continue
        row_changed = False
        for update in updates:
            if _replace_relation_road_ids(props, update):
                row_changed = True
            if segment_id in set(update.get("swsd_segment_ids") or []) and _upsert_relation_node_map(props, update):
                row_changed = True
        if row_changed:
            updated += 1
    if updated:
        write_feature_triplet(
            step_root=step_root,
            stem=STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
            features=relation_rows,
            fieldnames=STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
        )
    return updated


def _replace_relation_road_ids(props: dict[str, Any], update: dict[str, Any]) -> bool:
    replacements = dict(update.get("road_replacements") or {})
    if not replacements:
        return False
    changed = False
    for field in ("frcsd_road_ids", "rcsd_road_ids"):
        road_ids = _parse_id_list(props.get(field))
        if not road_ids:
            continue
        next_ids: list[str] = []
        for road_id in road_ids:
            replacement_ids = _parse_id_list(replacements.get(road_id))
            if replacement_ids:
                next_ids.extend(replacement_ids)
                changed = True
            else:
                next_ids.append(road_id)
        if changed:
            props[field] = unique_preserve_order(next_ids)
    return changed


def _selected_midroad_node_ids(candidate: dict[str, Any] | None) -> list[str]:
    if candidate is None:
        return []
    node_infos = list(candidate.get("node_infos") or [candidate.get("node_info")])
    return unique_preserve_order(_safe_id((node_info or {}).get("id")) for node_info in node_infos)


def _upsert_relation_node_map(props: dict[str, Any], update: dict[str, Any]) -> bool:
    swsd_node_id = _safe_id(update.get("swsd_node_id"))
    rcsd_node_ids = unique_preserve_order(
        _parse_id_list(update.get("rcsd_node_ids")) or [_safe_id(update.get("rcsd_node_id"))]
    )
    if not swsd_node_id or not rcsd_node_ids:
        return False
    mapping_status = str(update.get("mapping_status") or "surface_1v1_fallback")
    risk_flag = str(update.get("risk_flag") or "surface_1v1_fallback_node_map")
    allow_existing_source1_remap = bool(update.get("allow_existing_source1_remap"))
    allowed_current_node_ids = set(_parse_id_list(update.get("allowed_current_node_ids")))
    entries = _node_map_entries(props.get("swsd_to_frcsd_node_map"))
    changed = False
    matched = False
    for entry in entries:
        if _safe_id(entry.get("swsd_node_id")) != swsd_node_id:
            continue
        matched = True
        current_ids = _parse_id_list(entry.get("frcsd_node_ids"))
        status = str(entry.get("mapping_status") or "")
        if current_ids == rcsd_node_ids:
            return False
        if current_ids and current_ids != [swsd_node_id] and status not in {"missing"}:
            if (
                not allow_existing_source1_remap
                or len(current_ids) != 1
                or current_ids[0] not in allowed_current_node_ids
            ):
                return False
        entry["frcsd_node_ids"] = rcsd_node_ids
        entry["mapping_status"] = mapping_status
        entry["node_role"] = entry.get("node_role") or "surface_1v1_fallback_node"
        changed = True
    if not matched:
        entries.append(
            {
                "swsd_node_id": swsd_node_id,
                "frcsd_node_ids": rcsd_node_ids,
                "node_role": "surface_1v1_fallback_node",
                "mapping_status": mapping_status,
            }
        )
        changed = True
    if changed:
        props["swsd_to_frcsd_node_map"] = entries
        risk_flags = unique_preserve_order([*_parse_id_list(props.get("risk_flags")), risk_flag])
        props["risk_flags"] = risk_flags
    return changed


def _node_map_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if value in (None, ""):
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [dict(item) for item in parsed if isinstance(item, dict)]


def _rebuild_topology_connectivity_audit(
    *,
    step_root: Path,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
    coverage_cache: dict[Any, Any] | None = None,
    write_outputs: bool = True,
    runtime_state: Step3SurfaceRuntimeState | None = None,
    junction_only: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    swsd_segments = runtime_state.swsd_segments if runtime_state is not None else read_features(swsd_segment_path)
    swsd_roads = runtime_state.swsd_roads if runtime_state is not None else read_features(swsd_roads_path)
    road_path = step_root / "t06_frcsd_road.gpkg"
    node_path = step_root / "t06_frcsd_node.gpkg"
    relation_path = step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg"
    frcsd_roads = runtime_state.frcsd_roads if runtime_state is not None else read_features(road_path)
    frcsd_nodes = runtime_state.frcsd_nodes if runtime_state is not None else read_features(node_path)
    relation_rows = (
        runtime_state.segment_relation_rows
        if runtime_state is not None
        else read_features(relation_path)
    )
    advance_rows = (
        runtime_state.advance_right_audit_rows
        if runtime_state is not None
        else read_features(step_root / "t06_step3_advance_right_attachment_audit.gpkg")
    )
    retained_sync_stats = sync_retained_swsd_carrier_mainnodes(
        relation_rows,
        frcsd_roads,
        frcsd_nodes,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    try:
        cascade_node_ids = _hard_gate_cascade_node_ids(step_root)
        current_transition_node_ids = transition_failure_node_ids_for_candidates(
            candidate_node_ids=cascade_node_ids,
            swsd_segments=swsd_segments,
            swsd_roads=swsd_roads,
            frcsd_roads=frcsd_roads,
            frcsd_nodes=frcsd_nodes,
            segment_relation_rows=relation_rows,
            advance_right_audit_rows=advance_rows,
            source_field_name=source_field_name,
            swsd_source_value=swsd_source_value,
            rcsd_source_value=rcsd_source_value,
            coverage_cache=coverage_cache,
        )
        authoritative_stats = apply_authoritative_transition_closure(
            step_root=step_root,
            relation_rows=relation_rows,
            frcsd_nodes=frcsd_nodes,
            source_field_name=source_field_name,
            swsd_source_value=swsd_source_value,
            rcsd_source_value=rcsd_source_value,
            current_transition_node_ids=current_transition_node_ids,
        )
        if runtime_state is not None and authoritative_stats.get("audit_rows"):
            runtime_state.authoritative_transition_closure_rows = list(
                authoritative_stats["audit_rows"]
            )
        if (
            retained_sync_stats.get("retained_swsd_carrier_mainnode_row_count", 0) > 0
            or authoritative_stats.get("applied_node_count", 0) > 0
        ):
            write_feature_triplet(
                step_root=step_root,
                stem=STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
                features=relation_rows,
                fieldnames=STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
            )
            write_feature_triplet(
                step_root=step_root,
                stem=STEP3_FRCSD_NODE_STEM,
                features=frcsd_nodes,
                fieldnames=(
                    _runtime_fieldnames(frcsd_nodes)
                    if runtime_state is not None and not node_path.is_file()
                    else _fieldnames_from_gpkg(node_path)
                ),
            )
        if junction_only:
            rows = build_surface_junction_connectivity_audit_rows(
                swsd_segments=swsd_segments,
                frcsd_nodes=frcsd_nodes,
                segment_relation_rows=relation_rows,
                advance_right_audit_rows=advance_rows,
                source_field_name=source_field_name,
                swsd_source_value=swsd_source_value,
                rcsd_source_value=rcsd_source_value,
            )
        else:
            rows = build_topology_connectivity_audit_rows(
                swsd_segments=swsd_segments,
                swsd_roads=swsd_roads,
                frcsd_roads=frcsd_roads,
                frcsd_nodes=frcsd_nodes,
                segment_relation_rows=relation_rows,
                advance_right_audit_rows=advance_rows,
                source_field_name=source_field_name,
                swsd_source_value=swsd_source_value,
                rcsd_source_value=rcsd_source_value,
                coverage_cache=coverage_cache,
            )
    finally:
        if coverage_cache is not None:
            coverage_cache.clear()
        clear_read_features_cache()
    if write_outputs:
        _write_topology_connectivity_audit_rows(
            step_root,
            rows,
            {
                **retained_sync_stats,
                **{
                    f"authoritative_transition_{key}": value
                    for key, value in authoritative_stats.items()
                    if key != "audit_rows"
                },
            },
        )
    return rows, retained_sync_stats


def _runtime_fieldnames(features: list[dict[str, Any]]) -> list[str]:
    fieldnames: list[str] = []
    for feature_row in features:
        for field_name in (feature_row.get("properties") or {}):
            if field_name not in fieldnames:
                fieldnames.append(str(field_name))
    return fieldnames


def _write_topology_connectivity_audit_rows(
    step_root: Path,
    rows: list[dict[str, Any]],
    retained_sync_stats: dict[str, Any] | None = None,
) -> None:
    summary_path = step_root / "t06_step3_summary.json"
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        features=rows,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    )
    if summary_path.is_file():
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        payload.update(summarize_topology_connectivity_audit(rows))
        for key, value in (retained_sync_stats or {}).items():
            payload_key = f"surface_topology_{key}"
            payload[payload_key] = int(payload.get(payload_key, 0) or 0) + int(value or 0)
        write_json(summary_path, payload)


def _is_surface_action_row(row: dict[str, Any]) -> bool:
    props = row.get("properties") or {}
    action = str(props.get("action") or "")
    return action != "no_auto_closure" or str(props.get("audit_status") or "") == "pass"


def _unique_surface_audit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    unique_rows: list[dict[str, Any]] = []
    for row in rows:
        props = row.get("properties") or {}
        key = (
            str(props.get("audit_layer") or ""),
            str(props.get("swsd_node_id") or ""),
            str(props.get("audit_reason") or ""),
            str(props.get("closure_mainnodeid") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def _surface_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    reasons = Counter(str((row.get("properties") or {}).get("audit_reason") or "") for row in rows)
    fail_count = sum(1 for row in rows if (row.get("properties") or {}).get("audit_status") == "fail")
    pass_count = sum(1 for row in rows if (row.get("properties") or {}).get("audit_status") == "pass")
    return {
        "surface_topology_audit_row_count": len(rows),
        "surface_topology_fail_count": fail_count,
        "surface_topology_pass_count": pass_count,
        "surface_topology_auto_closed_count": (
            reasons.get("auto_closed", 0)
            + reasons.get("auto_closed_surface_1v1", 0)
            + reasons.get("auto_closed_t04_patch_1v1", 0)
            + reasons.get("auto_closed_t04_rejected_node_1v1", 0)
            + reasons.get("auto_closed_step2_junc_1v1", 0)
            + reasons.get("auto_closed_existing_cross_source_1v1", 0)
            + reasons.get("auto_closed_surface_nearest_multi_candidate", 0)
            + reasons.get("auto_closed_selected_replacement_endpoint", 0)
            + reasons.get("auto_closed_selected_replacement_midroad", 0)
            + reasons.get("auto_closed_relation_mapped_boundary_1v1", 0)
        ),
        "surface_topology_surface_1v1_closed_count": reasons.get("auto_closed_surface_1v1", 0),
        "surface_topology_t04_patch_1v1_closed_count": reasons.get("auto_closed_t04_patch_1v1", 0),
        "surface_topology_t04_rejected_node_1v1_closed_count": reasons.get("auto_closed_t04_rejected_node_1v1", 0),
        "surface_topology_step2_junc_1v1_closed_count": reasons.get("auto_closed_step2_junc_1v1", 0),
        "surface_topology_existing_cross_source_1v1_closed_count": reasons.get("auto_closed_existing_cross_source_1v1", 0),
        "surface_topology_surface_nearest_multi_candidate_closed_count": reasons.get("auto_closed_surface_nearest_multi_candidate", 0),
        "surface_topology_selected_replacement_endpoint_closed_count": reasons.get("auto_closed_selected_replacement_endpoint", 0),
        "surface_topology_selected_replacement_midroad_closed_count": reasons.get("auto_closed_selected_replacement_midroad", 0),
        "surface_topology_relation_mapped_boundary_1v1_closed_count": reasons.get("auto_closed_relation_mapped_boundary_1v1", 0),
        "surface_topology_single_node_default_mapped_count": (
            reasons.get("auto_mapped_surface_1v1_single_node_default", 0)
            + reasons.get("auto_mapped_t04_rejected_node_1v1_single_node_default", 0)
            + reasons.get("auto_mapped_step2_junc_1v1_single_node_default", 0)
        ),
        "surface_topology_blocked_by_patch_conflict_count": reasons.get("blocked_by_patch_conflict", 0),
        "surface_topology_blocked_by_t04_reject_count": reasons.get("blocked_by_t04_reject", 0),
        "surface_topology_manual_review_count": sum(
            count for reason, count in reasons.items() if reason.startswith("manual_")
        ),
    }


def _merge_step3_summary(step_root: Path, summary: dict[str, Any], summary_path: Path) -> None:
    step3_summary_path = step_root / "t06_step3_summary.json"
    if not step3_summary_path.is_file():
        return
    payload = json.loads(step3_summary_path.read_text(encoding="utf-8"))
    payload.update(summary)
    outputs = dict(payload.get("outputs") or {})
    outputs["surface_topology_audit_gpkg"] = str(step_root / f"{SURFACE_TOPOLOGY_AUDIT_STEM}.gpkg")
    outputs["surface_topology_summary_json"] = str(summary_path)
    payload["outputs"] = outputs
    write_json(step3_summary_path, payload)
