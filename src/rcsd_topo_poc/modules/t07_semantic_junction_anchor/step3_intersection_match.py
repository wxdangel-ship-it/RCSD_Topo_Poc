from __future__ import annotations

import json
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import TARGET_CRS, prefer_vector_input_path, write_json
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_io import write_relation_geojson_crs84
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_models import RELATION_OUTPUT_CRS_NAME
from rcsd_topo_poc.modules.t08_preprocess.vector_io import ensure_gpkg_ogr_feature_count_metadata

from .runner import (
    RELATION_EVIDENCE_FIELDNAMES,
    T07RunError,
    _audit_row,
    _build_node_index,
    _candidate_junction_ids,
    _elapsed_since,
    _normalize_id,
    _point_xy,
    _read_vector_layer,
    _resolve_gpkg_crs,
    _resolve_gpkg_layer,
    _resolve_group,
    _stage_root,
    _value_or_minus_one,
    _write_csv,
    _write_nodes,
)


STEP3_KIND2 = {"4", "8", "16", "2048"}


@dataclass(frozen=True)
class T07Step3Artifacts:
    run_root: Path
    stage_root: Path
    nodes_path: Path
    intersection_match_tool7_path: Path
    relation_evidence_json_path: Path
    summary_path: Path
    audit_csv_path: Path
    audit_json_path: Path
    perf_json_path: Path


@dataclass(frozen=True)
class RelationRecord:
    feature_index: int
    target_id: str | None
    base_id: str | None
    status: str | None
    properties: dict[str, Any]
    geometry: Any
    geometry_mode: str


def _is_zero_id(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return float(value) == 0
    except ValueError:
        return value == "0"


def _is_success_relation(record: RelationRecord) -> bool:
    return _is_zero_id(record.status) and record.base_id is not None and not _is_zero_id(record.base_id)


def _build_relations_by_target(
    relation_features: list[RelationRecord],
    audit_rows: list[dict[str, Any]],
) -> tuple[dict[str, list[RelationRecord]], int]:
    relations_by_target: dict[str, list[RelationRecord]] = {}
    invalid_relation_count = 0
    for record in relation_features:
        if record.target_id is None:
            invalid_relation_count += 1
            audit_rows.append(
                _audit_row(
                    scope="intersection_match_all",
                    status="skipped",
                    reason="missing_target_id",
                    detail=f"relation feature[{record.feature_index}] has no target_id.",
                    base_id=record.base_id,
                    relation_status=record.status,
                )
            )
            continue
        relations_by_target.setdefault(record.target_id, []).append(record)
    duplicate_count = 0
    for target_id, records in relations_by_target.items():
        if len(records) <= 1:
            continue
        duplicate_count += 1
        audit_rows.append(
            _audit_row(
                scope="intersection_match_all",
                status="error",
                reason="duplicate_target_id_relation",
                detail=f"target_id={target_id} appears {len(records)} times in intersection_match_all.",
                junction_id=target_id,
                target_id=target_id,
            )
        )
    return relations_by_target, invalid_relation_count + duplicate_count


def _build_rcsd_semantic_id_set(rcsdnode_properties: list[dict[str, Any]]) -> set[str]:
    rcsd_ids: set[str] = set()
    for props in rcsdnode_properties:
        node_id = _normalize_id(props.get("id"))
        if node_id is not None and not _is_zero_id(node_id):
            rcsd_ids.add(node_id)
        mainnodeid = _normalize_id(props.get("mainnodeid"))
        if mainnodeid is not None and not _is_zero_id(mainnodeid):
            rcsd_ids.add(mainnodeid)
    if not rcsd_ids:
        raise T07RunError("missing_required_field", "RCSDNode input has no usable id or mainnodeid values.")
    return rcsd_ids


def _relation_feature_payload(record: RelationRecord) -> dict[str, Any]:
    return {"properties": dict(record.properties), "geometry": record.geometry}


def _quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _field_name_case_insensitive(field_names: list[str], target: str) -> str | None:
    target_lower = target.lower()
    for field_name in field_names:
        if field_name.lower() == target_lower:
            return field_name
    return None


def _read_gpkg_property_rows(path: Path, layer_name: str | None) -> list[dict[str, Any]]:
    resolved_layer = _resolve_gpkg_layer(path, layer_name)
    with sqlite3.connect(str(path)) as conn:
        columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({_quote_identifier(resolved_layer)})")]
        wanted_columns = [
            column
            for column in (
                _field_name_case_insensitive(columns, "id"),
                _field_name_case_insensitive(columns, "mainnodeid"),
            )
            if column is not None
        ]
        if not wanted_columns:
            return []
        query = "SELECT " + ", ".join(_quote_identifier(column) for column in wanted_columns)
        query += " FROM " + _quote_identifier(resolved_layer)
        return [dict(zip(wanted_columns, row)) for row in conn.execute(query)]


def _read_geojson_property_rows(path: Path) -> list[dict[str, Any]]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [dict(feature.get("properties") or {}) for feature in doc.get("features", [])]


def _read_rcsdnode_properties(
    path: str | Path,
    *,
    layer_name: str | None,
    crs_override: str | None,
) -> list[dict[str, Any]]:
    layer_path = prefer_vector_input_path(Path(path))
    if not layer_path.is_file():
        raise T07RunError("missing_required_field", f"Input layer does not exist: {layer_path}")
    suffix = layer_path.suffix.lower()
    if suffix == ".gpkg":
        return _read_gpkg_property_rows(layer_path, layer_name)
    if suffix in {".geojson", ".json"}:
        return _read_geojson_property_rows(layer_path)
    return [
        dict(feature.properties)
        for feature in _read_vector_layer(
            layer_path,
            layer_name=layer_name,
            crs_override=crs_override,
            allow_null_geometry=True,
        ).features
    ]


def _geojson_crs_name(doc: dict[str, Any], crs_override: str | None) -> str | None:
    if crs_override:
        return crs_override
    crs_payload = doc.get("crs")
    if isinstance(crs_payload, dict):
        name = (crs_payload.get("properties") or {}).get("name")
        if name:
            return str(name)
    return None


def _is_crs84_name(crs_name: str | None) -> bool:
    if crs_name is None:
        return False
    normalized = crs_name.strip().upper()
    return normalized in {"CRS84", "OGC:CRS84", "URN:OGC:DEF:CRS:OGC:1.3:CRS84"}


def _read_relation_records(
    path: str | Path,
    *,
    crs_override: str | None,
) -> list[RelationRecord]:
    relation_path = prefer_vector_input_path(Path(path))
    if not relation_path.is_file():
        raise T07RunError("missing_required_field", f"Input layer does not exist: {relation_path}")

    if relation_path.suffix.lower() in {".geojson", ".json"}:
        doc = json.loads(relation_path.read_text(encoding="utf-8"))
        crs_name = _geojson_crs_name(doc, crs_override)
        if _is_crs84_name(crs_name):
            records = []
            for feature_index, feature in enumerate(doc.get("features", [])):
                props = dict(feature.get("properties") or {})
                records.append(
                    RelationRecord(
                        feature_index=feature_index,
                        target_id=_normalize_id(props.get("target_id")),
                        base_id=_normalize_id(props.get("base_id")),
                        status=_normalize_id(props.get("status")),
                        properties=props,
                        geometry=feature.get("geometry"),
                        geometry_mode="raw_crs84",
                    )
                )
            return records

    layer_data = _read_vector_layer(
        relation_path,
        crs_override=crs_override,
        allow_null_geometry=True,
    )
    return [
        RelationRecord(
            feature_index=feature.feature_index,
            target_id=_normalize_id(feature.properties.get("target_id")),
            base_id=_normalize_id(feature.properties.get("base_id")),
            status=_normalize_id(feature.properties.get("status")),
            properties=dict(feature.properties),
            geometry=feature.geometry,
            geometry_mode="process",
        )
        for feature in layer_data.features
    ]


def _write_relation_output(path: Path, records: list[RelationRecord]) -> None:
    if all(record.geometry_mode == "raw_crs84" for record in records):
        write_json(
            path,
            {
                "type": "FeatureCollection",
                "name": path.stem,
                "crs": {"type": "name", "properties": {"name": RELATION_OUTPUT_CRS_NAME}},
                "features": [
                    {
                        "type": "Feature",
                        "properties": dict(record.properties),
                        "geometry": record.geometry,
                    }
                    for record in records
                ],
            },
        )
        return
    write_relation_geojson_crs84(
        path,
        (_relation_feature_payload(record) for record in records),
    )


def _copy_update_gpkg_nodes(
    *,
    source_path: str | Path,
    output_path: Path,
    layer_name: str | None,
    crs_override: str | None,
    accepted_node_ids: list[str],
) -> bool:
    if crs_override is not None:
        return False
    source_gpkg = prefer_vector_input_path(Path(source_path))
    if source_gpkg.suffix.lower() != ".gpkg" or not source_gpkg.is_file():
        return False

    resolved_layer = _resolve_gpkg_layer(source_gpkg, layer_name)
    source_crs, _ = _resolve_gpkg_crs(source_gpkg, resolved_layer, None)
    if source_crs.to_epsg() != TARGET_CRS.to_epsg():
        return False

    with sqlite3.connect(str(source_gpkg)) as conn:
        columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({_quote_identifier(resolved_layer)})")]
    id_column = _field_name_case_insensitive(columns, "id")
    is_anchor_column = _field_name_case_insensitive(columns, "is_anchor")
    anchor_reason_column = _field_name_case_insensitive(columns, "anchor_reason")
    if id_column is None or is_anchor_column is None or anchor_reason_column is None:
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    shutil.copy2(source_gpkg, output_path)
    ensure_gpkg_ogr_feature_count_metadata(output_path, layer_name=resolved_layer)

    if not accepted_node_ids:
        return True

    with sqlite3.connect(str(output_path)) as conn:
        conn.executemany(
            "UPDATE "
            + _quote_identifier(resolved_layer)
            + " SET "
            + _quote_identifier(is_anchor_column)
            + " = ?, "
            + _quote_identifier(anchor_reason_column)
            + " = NULL WHERE "
            + _quote_identifier(id_column)
            + " = ?",
            [("yes", node_id) for node_id in accepted_node_ids],
        )
    return True


def _write_step3_nodes(
    *,
    output_path: Path,
    features: list[Any],
    source_path: str | Path,
    source_layer: str | None,
    source_crs: str | None,
    accepted_node_ids: list[str],
) -> str:
    if _copy_update_gpkg_nodes(
        source_path=source_path,
        output_path=output_path,
        layer_name=source_layer,
        crs_override=source_crs,
        accepted_node_ids=accepted_node_ids,
    ):
        return "copy_update_gpkg"
    _write_nodes(output_path, features)
    return "rewrite_gpkg"


def _load_step2_relation_evidence_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _step3_relation_evidence_row(
    *,
    relation_record: RelationRecord,
    representative_node_id: str,
    representative_props: dict[str, Any],
    representative_geometry: Any,
) -> dict[str, Any]:
    swsd_point_x, swsd_point_y = _point_xy(representative_geometry)
    relation_props = relation_record.properties
    level_value = relation_props.get("level") if relation_props.get("level") is not None else representative_props.get("grade")
    is_highway_value = relation_props.get("is_highway") if relation_props.get("is_highway") is not None else representative_props.get("closed_con")
    return {
        "target_id": relation_record.target_id or "",
        "representative_node_id": representative_node_id,
        "relation_source": "T07_STEP3_INTERSECTION_MATCH",
        "relation_target_type": "RCSDNode",
        "matched_rcsdintersection_ids": "",
        "relation_state": "intersection_match_tool7_matched",
        "status_suggested": 0,
        "base_id_candidate": relation_record.base_id or -1,
        "reason": "intersection_match_tool7_matched",
        "level": _value_or_minus_one(level_value),
        "is_highway": _value_or_minus_one(is_highway_value),
        "swsd_point_x": swsd_point_x,
        "swsd_point_y": swsd_point_y,
        "rcsd_point_x": "",
        "rcsd_point_y": "",
    }


def _write_merged_relation_evidence_json(
    *,
    path: Path,
    run_id: str,
    step2_evidence_path: Path,
    step3_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged_rows = _load_step2_relation_evidence_rows(step2_evidence_path)
    row_by_target = {_normalize_id(row.get("target_id")): index for index, row in enumerate(merged_rows)}
    for row in step3_rows:
        target_id = _normalize_id(row.get("target_id"))
        if target_id is None:
            continue
        existing_index = row_by_target.get(target_id)
        if existing_index is None:
            row_by_target[target_id] = len(merged_rows)
            merged_rows.append(row)
        else:
            merged_rows[existing_index] = row
    write_json(
        path,
        {
            "run_id": run_id,
            "target_crs": TARGET_CRS.to_string(),
            "row_count": len(merged_rows),
            "fieldnames": RELATION_EVIDENCE_FIELDNAMES,
            "merge_sources": {
                "step2_relation_evidence": str(step2_evidence_path) if step2_evidence_path.is_file() else None,
                "step3_intersection_match_tool7": "intersection_match_tool7.geojson",
            },
            "rows": merged_rows,
        },
    )
    return merged_rows


def run_t07_step3_intersection_match(
    *,
    nodes_path: str | Path,
    intersection_match_all_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    nodes_layer: str | None = None,
    rcsdnode_layer: str | None = None,
    nodes_crs: str | None = None,
    intersection_match_all_crs: str | None = None,
    rcsdnode_crs: str | None = None,
) -> T07Step3Artifacts:
    started_at = time.perf_counter()
    stage_timings: dict[str, float] = {}
    run_root, stage_root, resolved_run_id = _stage_root(out_root, run_id, "step3_intersection_match")
    stage_root.mkdir(parents=True, exist_ok=True)
    audit_rows: list[dict[str, Any]] = []

    read_inputs_started = time.perf_counter()
    stage_started = time.perf_counter()
    nodes_layer_data = _read_vector_layer(
        nodes_path,
        layer_name=nodes_layer,
        crs_override=nodes_crs,
        allow_null_geometry=True,
    )
    stage_timings["read_nodes_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    relation_records = _read_relation_records(
        intersection_match_all_path,
        crs_override=intersection_match_all_crs,
    )
    stage_timings["read_intersection_match_all_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    rcsdnode_properties = _read_rcsdnode_properties(
        rcsdnode_path,
        layer_name=rcsdnode_layer,
        crs_override=rcsdnode_crs,
    )
    stage_timings["read_rcsdnode_ids_seconds"] = _elapsed_since(stage_started)
    stage_timings["read_inputs_seconds"] = _elapsed_since(read_inputs_started)

    stage_started = time.perf_counter()
    by_mainnodeid, singleton_by_id = _build_node_index(nodes_layer_data.features, audit_rows)
    junction_ids = _candidate_junction_ids(by_mainnodeid, singleton_by_id)
    relations_by_target, invalid_relation_count = _build_relations_by_target(relation_records, audit_rows)
    rcsd_semantic_ids = _build_rcsd_semantic_id_set(rcsdnode_properties)
    stage_timings["prepare_indices_seconds"] = _elapsed_since(stage_started)

    counts = {
        "semantic_junction_count": len(junction_ids),
        "step3_scope_kind2_count": 0,
        "candidate_count": 0,
        "accepted_count": 0,
        "not_candidate_count": 0,
        "skipped_kind2_count": 0,
        "relation_missing_count": 0,
        "relation_failure_count": 0,
        "relation_duplicate_count": 0,
        "rcsd_missing_count": 0,
        "representative_missing_count": 0,
        "invalid_relation_count": invalid_relation_count,
    }
    accepted_relations: list[RelationRecord] = []
    accepted_node_ids: list[str] = []
    accepted_relation_evidence_rows: list[dict[str, Any]] = []

    stage_started = time.perf_counter()
    for junction_id in junction_ids:
        group = _resolve_group(junction_id, by_mainnodeid=by_mainnodeid, singleton_by_id=singleton_by_id)
        if group.representative is None:
            counts["representative_missing_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="error",
                    reason=group.reason or "representative_node_missing",
                    detail=group.detail or "representative node missing",
                    junction_id=junction_id,
                )
            )
            continue

        representative_props = nodes_layer_data.features[group.representative.output_index].properties
        kind_2 = _normalize_id(representative_props.get("kind_2"))
        has_evd = _normalize_id(representative_props.get("has_evd"))
        is_anchor = _normalize_id(representative_props.get("is_anchor"))
        if kind_2 not in STEP3_KIND2:
            counts["skipped_kind2_count"] += 1
            continue
        counts["step3_scope_kind2_count"] += 1

        if has_evd != "yes" or is_anchor != "no":
            counts["not_candidate_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="skipped",
                    reason="not_step3_candidate",
                    detail="Step3 only processes has_evd=yes and is_anchor=no representatives.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    kind_2=kind_2,
                    has_evd=has_evd,
                    is_anchor=is_anchor,
                )
            )
            continue

        counts["candidate_count"] += 1
        relation_records = relations_by_target.get(junction_id, [])
        if not relation_records:
            counts["relation_missing_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="skipped",
                    reason="relation_missing",
                    detail="candidate SWSD junction has no relation in intersection_match_all.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    kind_2=kind_2,
                    has_evd=has_evd,
                    is_anchor=is_anchor,
                    target_id=junction_id,
                )
            )
            continue
        if len(relation_records) > 1:
            counts["relation_duplicate_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="error",
                    reason="duplicate_target_id_relation",
                    detail="candidate SWSD junction has multiple relation rows; Step3 does not choose among them.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    kind_2=kind_2,
                    has_evd=has_evd,
                    is_anchor=is_anchor,
                    target_id=junction_id,
                )
            )
            continue

        relation_record = relation_records[0]
        if not _is_success_relation(relation_record):
            counts["relation_failure_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="skipped",
                    reason="relation_not_successful",
                    detail="intersection_match_all relation is not status=0 with a non-zero base_id.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    kind_2=kind_2,
                    has_evd=has_evd,
                    is_anchor=is_anchor,
                    target_id=relation_record.target_id,
                    base_id=relation_record.base_id,
                    relation_status=relation_record.status,
                    rcsd_exists=0,
                )
            )
            continue

        if relation_record.base_id not in rcsd_semantic_ids:
            counts["rcsd_missing_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="skipped",
                    reason="rcsd_junction_missing",
                    detail="relation base_id is not present in input RCSDNode id/mainnodeid values.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    kind_2=kind_2,
                    has_evd=has_evd,
                    is_anchor=is_anchor,
                    target_id=relation_record.target_id,
                    base_id=relation_record.base_id,
                    relation_status=relation_record.status,
                    rcsd_exists=0,
                )
            )
            continue

        representative_props["is_anchor"] = "yes"
        representative_props["anchor_reason"] = None
        accepted_relations.append(relation_record)
        accepted_node_ids.append(group.representative.node_id)
        accepted_relation_evidence_rows.append(
            _step3_relation_evidence_row(
                relation_record=relation_record,
                representative_node_id=group.representative.node_id,
                representative_props=representative_props,
                representative_geometry=group.representative.geometry,
            )
        )
        counts["accepted_count"] += 1
        audit_rows.append(
            _audit_row(
                scope="semantic_junction",
                status="accepted",
                reason="t05_relation_rcsd_junction_exists",
                detail="candidate SWSD junction has a successful T05 relation whose RCSD base_id exists in input RCSDNode.",
                junction_id=junction_id,
                node_id=group.representative.node_id,
                kind_2=kind_2,
                has_evd=has_evd,
                is_anchor="yes",
                target_id=relation_record.target_id,
                base_id=relation_record.base_id,
                relation_status=relation_record.status,
                rcsd_exists=1,
            )
        )
    stage_timings["evaluate_candidates_seconds"] = _elapsed_since(stage_started)

    nodes_output_path = stage_root / "nodes.gpkg"
    relation_output_path = stage_root / "intersection_match_tool7.geojson"
    relation_evidence_json_path = stage_root / "t07_swsd_rcsd_relation_evidence.json"
    summary_path = stage_root / "t07_step3_summary.json"
    audit_csv_path = stage_root / "t07_step3_audit.csv"
    audit_json_path = stage_root / "t07_step3_audit.json"
    perf_path = stage_root / "t07_step3_perf.json"

    stage_started = time.perf_counter()
    nodes_write_mode = _write_step3_nodes(
        output_path=nodes_output_path,
        features=nodes_layer_data.features,
        source_path=nodes_path,
        source_layer=nodes_layer,
        source_crs=nodes_crs,
        accepted_node_ids=accepted_node_ids,
    )
    _write_relation_output(relation_output_path, accepted_relations)
    step2_relation_evidence_path = prefer_vector_input_path(Path(nodes_path)).parent / "t07_swsd_rcsd_relation_evidence.json"
    merged_relation_evidence_rows = _write_merged_relation_evidence_json(
        path=relation_evidence_json_path,
        run_id=resolved_run_id,
        step2_evidence_path=step2_relation_evidence_path,
        step3_rows=accepted_relation_evidence_rows,
    )
    stage_timings["write_outputs_seconds"] = _elapsed_since(stage_started)

    summary = {
        "run_id": resolved_run_id,
        **counts,
        "input_paths": {
            "nodes": str(nodes_path),
            "intersection_match_all": str(intersection_match_all_path),
            "rcsdnode": str(rcsdnode_path),
        },
        "output_paths": {
            "nodes": str(nodes_output_path),
            "intersection_match_tool7": str(relation_output_path),
            "t07_swsd_rcsd_relation_evidence": str(relation_evidence_json_path),
        },
        "output_strategy": {
            "nodes_write_mode": nodes_write_mode,
            "relation_write_mode": "raw_crs84" if all(record.geometry_mode == "raw_crs84" for record in accepted_relations) else "transform_to_crs84",
        },
        "crs": {
            "process": TARGET_CRS.to_string(),
            "intersection_match_tool7": RELATION_OUTPUT_CRS_NAME,
        },
        "relation_evidence_row_count": len(merged_relation_evidence_rows),
        "audit_count": len(audit_rows),
        "performance": {
            "elapsed_seconds": _elapsed_since(started_at),
            "stage_timings": stage_timings,
        },
    }

    stage_started = time.perf_counter()
    write_json(summary_path, summary)
    _write_csv(
        audit_csv_path,
        audit_rows,
        [
            "scope",
            "junction_id",
            "node_id",
            "status",
            "reason",
            "detail",
            "kind_2",
            "has_evd",
            "is_anchor",
            "target_id",
            "base_id",
            "relation_status",
            "rcsd_exists",
        ],
    )
    write_json(audit_json_path, {"run_id": resolved_run_id, "rows": audit_rows})
    stage_timings["write_audit_summary_seconds"] = _elapsed_since(stage_started)
    write_json(
        perf_path,
        {
            "run_id": resolved_run_id,
            "elapsed_sec": _elapsed_since(started_at),
            "stage_timings": stage_timings,
            "nodes_write_mode": nodes_write_mode,
            **counts,
        },
    )

    return T07Step3Artifacts(
        run_root=run_root,
        stage_root=stage_root,
        nodes_path=nodes_output_path,
        intersection_match_tool7_path=relation_output_path,
        relation_evidence_json_path=relation_evidence_json_path,
        summary_path=summary_path,
        audit_csv_path=audit_csv_path,
        audit_json_path=audit_json_path,
        perf_json_path=perf_path,
    )
