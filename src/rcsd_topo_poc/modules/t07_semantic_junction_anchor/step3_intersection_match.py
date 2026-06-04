from __future__ import annotations

import json
import shutil
import sqlite3
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyproj import Transformer
from shapely.geometry import LineString, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree
from shapely.ops import transform as shapely_transform

from rcsd_topo_poc.modules.t00_utility_toolbox.common import TARGET_CRS, prefer_vector_input_path, write_json
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_models import RELATION_OUTPUT_CRS_NAME
from rcsd_topo_poc.modules.t08_preprocess.vector_io import ensure_gpkg_ogr_feature_count_metadata, write_gpkg

from .runner import (
    RELATION_EVIDENCE_FIELDNAMES,
    SURFACE_CANDIDATE_FIELDNAMES,
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
    intersection_match_t07_path: Path
    anchor_surface_path: Path
    rcsdnode_error_path: Path
    relation_evidence_csv_path: Path
    relation_evidence_json_path: Path
    relation_cardinality_errors_csv_path: Path
    relation_cardinality_errors_json_path: Path
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


@dataclass(frozen=True)
class RCSDNodeRecord:
    node_id: str
    semantic_id: str
    properties: dict[str, Any]
    geometry: Any


RELATION_CARDINALITY_ERROR_FIELDS = [
    "error_type",
    "target_id",
    "base_id",
    "related_target_ids",
    "introduced_by_module",
    "source_modules",
    "source_case_ids",
    "scenes",
    "reasons",
]

RCSDNODE_ERROR_FIELDNAMES = [
    "error_type",
    "target_id",
    "surface_candidate_id",
    "source_rcsdintersection_id",
    "rcsd_semantic_id",
    "rcsd_node_id",
    "related_rcsd_semantic_ids",
]


def _is_zero_id(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return float(value) == 0
    except ValueError:
        return value == "0"


def _is_success_relation(record: RelationRecord) -> bool:
    return _is_zero_id(record.status) and record.base_id is not None and not _is_zero_id(record.base_id)


def _sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, value)


def _parts(value: Any) -> set[str]:
    return {part for part in str(value or "").replace(",", "|").split("|") if part}


def _record_parts(record: RelationRecord, keys: tuple[str, ...]) -> set[str]:
    result: set[str] = set()
    for key in keys:
        result.update(_parts(record.properties.get(key)))
    return result


def _relation_cardinality_error_row(
    *,
    error_type: str,
    target_ids: list[str],
    base_ids: list[str],
    records: list[RelationRecord],
) -> dict[str, str]:
    source_modules: set[str] = set()
    source_case_ids: set[str] = set()
    scenes: set[str] = set()
    reasons: set[str] = {error_type}
    for record in records:
        source_modules.update(_record_parts(record, ("source_module", "source_modules", "relation_source")))
        source_case_ids.update(_record_parts(record, ("source_case_id", "source_case_ids", "case_id")))
        scenes.update(_record_parts(record, ("scene", "scenes", "relation_state")))
        reasons.update(_record_parts(record, ("reason", "reasons", "relation_state")))
    source_module_text = "|".join(sorted(source_modules, key=_sort_key))
    return {
        "error_type": error_type,
        "target_id": "|".join(target_ids),
        "base_id": "|".join(base_ids),
        "related_target_ids": "|".join(target_ids),
        "introduced_by_module": source_module_text or "T05_INTERSECTION_MATCH_ALL",
        "source_modules": source_module_text,
        "source_case_ids": "|".join(sorted(source_case_ids, key=_sort_key)),
        "scenes": "|".join(sorted(scenes, key=_sort_key)),
        "reasons": "|".join(sorted(reasons, key=_sort_key)),
    }


def _build_relation_cardinality_errors(
    *,
    relations_by_target: dict[str, list[RelationRecord]],
    candidate_target_ids: set[str],
) -> list[dict[str, str]]:
    records = [
        record
        for target_id in candidate_target_ids
        for record in relations_by_target.get(target_id, [])
        if _is_success_relation(record)
    ]
    return _build_relation_cardinality_errors_from_records(records)


def _build_relation_cardinality_errors_from_records(records: list[RelationRecord]) -> list[dict[str, str]]:
    target_to_base: dict[str, set[str]] = defaultdict(set)
    base_to_target: dict[str, set[str]] = defaultdict(set)
    target_counter: Counter[str] = Counter()
    records_by_target: dict[str, list[RelationRecord]] = defaultdict(list)
    records_by_base: dict[str, list[RelationRecord]] = defaultdict(list)

    for record in records:
        if not _is_success_relation(record) or record.target_id is None or record.base_id is None:
            continue
        target_counter[record.target_id] += 1
        target_to_base[record.target_id].add(record.base_id)
        base_to_target[record.base_id].add(record.target_id)
        records_by_target[record.target_id].append(record)
        records_by_base[record.base_id].append(record)

    errors: list[dict[str, str]] = []
    for target_id, base_ids in sorted(target_to_base.items(), key=lambda item: _sort_key(item[0])):
        if len(base_ids) <= 1:
            continue
        errors.append(
            _relation_cardinality_error_row(
                error_type="one_target_to_many_base",
                target_ids=[target_id],
                base_ids=sorted(base_ids, key=_sort_key),
                records=records_by_target[target_id],
            )
        )
    for base_id, target_ids in sorted(base_to_target.items(), key=lambda item: _sort_key(item[0])):
        if len(target_ids) <= 1:
            continue
        sorted_target_ids = sorted(target_ids, key=_sort_key)
        errors.append(
            _relation_cardinality_error_row(
                error_type="many_target_to_one_base",
                target_ids=sorted_target_ids,
                base_ids=[base_id],
                records=records_by_base[base_id],
            )
        )
    for target_id, count in sorted(target_counter.items(), key=lambda item: _sort_key(item[0])):
        if count <= 1:
            continue
        row = _relation_cardinality_error_row(
            error_type="duplicate_target_rows",
            target_ids=[target_id],
            base_ids=sorted(target_to_base.get(target_id, set()), key=_sort_key),
            records=records_by_target[target_id],
        )
        row["reasons"] = "|".join(
            sorted({*row["reasons"].split("|"), f"target_id duplicated {count} success rows"} - {""}, key=_sort_key)
        )
        errors.append(row)
    return errors


def _relation_cardinality_summary(error_rows: list[dict[str, str]]) -> dict[str, Any]:
    counts = Counter(row.get("error_type", "") for row in error_rows)
    return {
        "relation_cardinality_error_count": len(error_rows),
        "one_target_to_many_base_count": int(counts["one_target_to_many_base"]),
        "many_target_to_one_base_count": int(counts["many_target_to_one_base"]),
        "duplicate_target_rows_count": int(counts["duplicate_target_rows"]),
        "relation_cardinality_passed": not error_rows,
    }


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


def _rcsd_semantic_id(props: dict[str, Any]) -> str | None:
    mainnodeid = _normalize_id(props.get("mainnodeid"))
    if mainnodeid is not None and not _is_zero_id(mainnodeid):
        return mainnodeid
    node_id = _normalize_id(props.get("id"))
    if node_id is not None and not _is_zero_id(node_id):
        return node_id
    return None


def _rcsdnode_records(features: list[Any]) -> list[RCSDNodeRecord]:
    records: list[RCSDNodeRecord] = []
    for feature in features:
        props = dict(feature.properties)
        semantic_id = _rcsd_semantic_id(props)
        node_id = _normalize_id(props.get("id"))
        if semantic_id is None or node_id is None or feature.geometry is None:
            continue
        records.append(
            RCSDNodeRecord(
                node_id=node_id,
                semantic_id=semantic_id,
                properties=props,
                geometry=feature.geometry,
            )
        )
    return records


def _representative_rcsdnode_by_semantic_id(records: list[RCSDNodeRecord]) -> dict[str, RCSDNodeRecord]:
    grouped: dict[str, list[RCSDNodeRecord]] = defaultdict(list)
    for record in records:
        grouped[record.semantic_id].append(record)
    representatives: dict[str, RCSDNodeRecord] = {}
    for semantic_id, group_records in grouped.items():
        exact = [record for record in group_records if record.node_id == semantic_id]
        representatives[semantic_id] = sorted(exact or group_records, key=lambda item: _sort_key(item.node_id))[0]
    return representatives


def _read_step2_surface_features(path: Path) -> list[Any]:
    if not path.is_file():
        return []
    return _read_vector_layer(path, allow_null_geometry=True).features


def _surface_target_id(props: dict[str, Any]) -> str | None:
    return _normalize_id(props.get("target_id") or props.get("mainnodeid"))


def _surface_kind2(props: dict[str, Any]) -> str | None:
    return _normalize_id(props.get("kind_2"))


def _line_between_geometries(start_geometry: Any, end_geometry: Any) -> LineString:
    start_x, start_y = _point_xy(start_geometry)
    end_x, end_y = _point_xy(end_geometry)
    return LineString([(float(start_x), float(start_y)), (float(end_x), float(end_y))])


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

    transformer = Transformer.from_crs(TARGET_CRS, "EPSG:4326", always_xy=True)
    features = []
    for record in records:
        geometry = record.geometry
        if geometry is not None and record.geometry_mode != "raw_crs84":
            geometry_obj = geometry if isinstance(geometry, BaseGeometry) else shape(geometry)
            geometry = mapping(shapely_transform(transformer.transform, geometry_obj))
        elif isinstance(geometry, BaseGeometry):
            geometry = mapping(geometry)
        features.append(
            {
                "type": "Feature",
                "properties": dict(record.properties),
                "geometry": geometry,
            }
        )
    write_json(
        path,
        {
            "type": "FeatureCollection",
            "name": path.stem,
            "crs": {"type": "name", "properties": {"name": RELATION_OUTPUT_CRS_NAME}},
            "features": features,
        },
    )


def _write_rcsdnode_error_output(path: Path, rows: list[dict[str, Any]]) -> None:
    write_gpkg(
        path,
        (
            {
                "properties": {field: row.get(field, "") for field in RCSDNODE_ERROR_FIELDNAMES},
                "geometry": row.get("_geometry"),
            }
            for row in rows
            if row.get("_geometry") is not None
        ),
        crs_text=TARGET_CRS.to_string(),
        empty_fields=RCSDNODE_ERROR_FIELDNAMES,
        geometry_type="Point",
    )


def _relation_record_from_step2_surface(
    *,
    feature_index: int,
    surface_props: dict[str, Any],
    surface_geometry: Any,
    base_record: RCSDNodeRecord,
    representative_geometry: Any,
) -> RelationRecord:
    target_id = _surface_target_id(surface_props) or ""
    level_value = surface_props.get("level") if surface_props.get("level") is not None else surface_props.get("grade")
    is_highway_value = surface_props.get("is_highway") if surface_props.get("is_highway") is not None else surface_props.get("closed_con")
    return RelationRecord(
        feature_index=feature_index,
        target_id=target_id,
        base_id=base_record.semantic_id,
        status="0",
        properties={
            "target_id": target_id,
            "base_id": base_record.semantic_id,
            "status": 0,
            "level": _value_or_minus_one(level_value),
            "is_highway": _value_or_minus_one(is_highway_value),
            "relation_source": "T07_STEP3_STEP2_SURFACE",
        },
        geometry=_line_between_geometries(representative_geometry or surface_geometry, base_record.geometry),
        geometry_mode="process",
    )


def _step2_surface_relation_evidence_row(
    *,
    relation_record: RelationRecord,
    representative_node_id: str,
    representative_props: dict[str, Any],
    representative_geometry: Any,
    rcsd_geometry: Any,
) -> dict[str, Any]:
    swsd_point_x, swsd_point_y = _point_xy(representative_geometry)
    rcsd_point_x, rcsd_point_y = _point_xy(rcsd_geometry)
    return {
        "target_id": relation_record.target_id or "",
        "representative_node_id": representative_node_id,
        "relation_source": "T07_STEP3_STEP2_SURFACE",
        "relation_target_type": "RCSDNode",
        "matched_rcsdintersection_ids": "",
        "relation_state": "step2_surface_1v1_rcsdnode_matched",
        "status_suggested": 0,
        "base_id_candidate": relation_record.base_id or -1,
        "reason": "step2_surface_1v1_rcsdnode_matched",
        "level": _value_or_minus_one(representative_props.get("grade")),
        "is_highway": _value_or_minus_one(representative_props.get("closed_con")),
        "swsd_point_x": swsd_point_x,
        "swsd_point_y": swsd_point_y,
        "rcsd_point_x": rcsd_point_x,
        "rcsd_point_y": rcsd_point_y,
    }


def _one_to_many_target_ids(error_rows: list[dict[str, str]]) -> set[str]:
    return {
        target_id
        for row in error_rows
        if row.get("error_type") == "one_target_to_many_base"
        for target_id in _parts(row.get("target_id"))
    }


def _dedupe_relation_records(records: list[RelationRecord]) -> list[RelationRecord]:
    seen: set[tuple[str | None, str | None]] = set()
    deduped: list[RelationRecord] = []
    for record in records:
        key = (record.target_id, record.base_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _copy_update_gpkg_nodes(
    *,
    source_path: str | Path,
    output_path: Path,
    layer_name: str | None,
    crs_override: str | None,
    node_anchor_updates: dict[str, str],
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

    if not node_anchor_updates:
        return True

    with sqlite3.connect(str(output_path)) as conn:
        table_identifier = _quote_identifier(resolved_layer)
        id_identifier = _quote_identifier(id_column)
        id_expr = f"{table_identifier}.{id_identifier}"
        conn.execute("CREATE TEMP TABLE t07_node_anchor_updates(node_id TEXT PRIMARY KEY, is_anchor TEXT)")
        conn.executemany(
            "INSERT OR REPLACE INTO t07_node_anchor_updates(node_id, is_anchor) VALUES (?, ?)",
            sorted(node_anchor_updates.items(), key=lambda item: _sort_key(item[0])),
        )
        conn.execute(
            "UPDATE "
            + table_identifier
            + " SET "
            + _quote_identifier(is_anchor_column)
            + " = ("
            + "SELECT updates.is_anchor FROM t07_node_anchor_updates AS updates "
            + "WHERE updates.node_id = "
            + id_expr
            + " OR updates.node_id = CAST("
            + id_expr
            + " AS TEXT) LIMIT 1), "
            + _quote_identifier(anchor_reason_column)
            + " = NULL WHERE EXISTS ("
            + "SELECT 1 FROM t07_node_anchor_updates AS updates "
            + "WHERE updates.node_id = "
            + id_expr
            + " OR updates.node_id = CAST("
            + id_expr
            + " AS TEXT))"
        )
    return True


def _write_step3_nodes(
    *,
    output_path: Path,
    features: list[Any],
    source_path: str | Path,
    source_layer: str | None,
    source_crs: str | None,
    node_anchor_updates: dict[str, str],
) -> str:
    if _copy_update_gpkg_nodes(
        source_path=source_path,
        output_path=output_path,
        layer_name=source_layer,
        crs_override=source_crs,
        node_anchor_updates=node_anchor_updates,
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


def _step2_one_to_one_surface_base_ids(rows: list[dict[str, Any]]) -> set[str]:
    base_ids: set[str] = set()
    for row in rows:
        if _normalize_id(row.get("relation_source")) != "T07_STEP2":
            continue
        if _normalize_id(row.get("relation_state")) != "existing_rcsdintersection_matched":
            continue
        if _normalize_id(row.get("status_suggested")) != "0":
            continue
        row_base_ids = [
            base_id
            for base_id in sorted(_parts(row.get("base_id_candidate")), key=_sort_key)
            if base_id not in {"-1"} and not _is_zero_id(base_id)
        ]
        if len(row_base_ids) == 1:
            base_ids.add(row_base_ids[0])
    return base_ids


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
        "relation_state": "intersection_match_t07_matched",
        "status_suggested": 0,
        "base_id_candidate": relation_record.base_id or -1,
        "reason": "intersection_match_t07_matched",
        "level": _value_or_minus_one(level_value),
        "is_highway": _value_or_minus_one(is_highway_value),
        "swsd_point_x": swsd_point_x,
        "swsd_point_y": swsd_point_y,
        "rcsd_point_x": "",
        "rcsd_point_y": "",
    }


def _write_merged_relation_evidence_json(
    *,
    csv_path: Path,
    json_path: Path,
    run_id: str,
    step2_evidence_path: Path,
    step3_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    merged_rows = _load_step2_relation_evidence_rows(step2_evidence_path)
    step2_anchor_count = sum(
        1
        for row in merged_rows
        if _normalize_id(row.get("relation_source")) == "T07_STEP2"
        and _normalize_id(row.get("status_suggested")) == "0"
    )
    step3_anchor_count = len(step3_rows)
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
    _write_csv(csv_path, merged_rows, RELATION_EVIDENCE_FIELDNAMES)
    write_json(
        json_path,
        {
            "run_id": run_id,
            "target_crs": TARGET_CRS.to_string(),
            "row_count": len(merged_rows),
            "fieldnames": RELATION_EVIDENCE_FIELDNAMES,
            "anchor_counts": {
                "step2_anchor_count": step2_anchor_count,
                "step3_anchor_count": step3_anchor_count,
                "total_anchor_count": step2_anchor_count + step3_anchor_count,
            },
            "merge_sources": {
                "step2_relation_evidence": str(step2_evidence_path) if step2_evidence_path.is_file() else None,
                "step3_intersection_match_t07": "intersection_match_t07.geojson",
            },
            "rows": merged_rows,
        },
    )
    return merged_rows, {
        "step2_anchor_count": step2_anchor_count,
        "step3_anchor_count": step3_anchor_count,
        "total_anchor_count": step2_anchor_count + step3_anchor_count,
    }


def _write_step3_anchor_surface(
    *,
    output_path: Path,
    step2_surface_path: Path,
) -> str:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if step2_surface_path.is_file():
        if output_path.exists():
            output_path.unlink()
        shutil.copy2(step2_surface_path, output_path)
        return "copy_step2_surface"
    from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg

    write_gpkg(
        output_path,
        [],
        crs_text=TARGET_CRS.to_string(),
        empty_fields=SURFACE_CANDIDATE_FIELDNAMES,
        geometry_type="Polygon",
    )
    return "empty_surface_no_step2_source"


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
    rcsdnode_layer_data = _read_vector_layer(
        rcsdnode_path,
        layer_name=rcsdnode_layer,
        crs_override=rcsdnode_crs,
        allow_null_geometry=True,
    )
    rcsdnode_properties = [dict(feature.properties) for feature in rcsdnode_layer_data.features]
    stage_timings["read_rcsdnode_ids_seconds"] = _elapsed_since(stage_started)
    stage_timings["read_inputs_seconds"] = _elapsed_since(read_inputs_started)

    stage_started = time.perf_counter()
    by_mainnodeid, singleton_by_id = _build_node_index(nodes_layer_data.features, audit_rows)
    junction_ids = _candidate_junction_ids(by_mainnodeid, singleton_by_id)
    relations_by_target, invalid_relation_count = _build_relations_by_target(relation_records, audit_rows)
    rcsd_semantic_ids = _build_rcsd_semantic_id_set(rcsdnode_properties)
    rcsdnode_records = _rcsdnode_records(rcsdnode_layer_data.features)
    rcsd_representatives = _representative_rcsdnode_by_semantic_id(rcsdnode_records)
    rcsd_geometries = [record.geometry for record in rcsdnode_records]
    rcsd_tree = STRtree(rcsd_geometries) if rcsd_geometries else None
    step2_relation_evidence_path = prefer_vector_input_path(Path(nodes_path)).parent / "t07_swsd_rcsd_relation_evidence.json"
    step2_relation_evidence_rows = _load_step2_relation_evidence_rows(step2_relation_evidence_path)
    step2_anchor_surface_path = prefer_vector_input_path(Path(nodes_path)).parent / "t07_rcsdintersection_anchor_surface.gpkg"
    step2_surface_features = _read_step2_surface_features(step2_anchor_surface_path)
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
        "step2_surface_1v1_relation_count": 0,
        "intersection_match_backfill_relation_count": 0,
        "step2_surface_no_rcsd_count": 0,
        "rcsdnode_error_surface_count": 0,
        "rcsdnode_error_count": 0,
        "already_linked_base_skip_count": 0,
        "representative_missing_count": 0,
        "invalid_relation_count": invalid_relation_count,
    }
    tentative_relations: list[RelationRecord] = []
    tentative_relation_evidence_rows: list[dict[str, Any]] = []
    rcsdnode_error_rows: list[dict[str, Any]] = []
    linked_base_ids: set[str] = set()

    stage_started = time.perf_counter()
    surface_features_by_target: dict[str, list[Any]] = defaultdict(list)
    for surface_feature in step2_surface_features:
        surface_props = dict(surface_feature.properties)
        target_id = _surface_target_id(surface_props)
        if target_id is None or _surface_kind2(surface_props) not in STEP3_KIND2:
            continue
        surface_features_by_target[target_id].append(surface_feature)

    for target_id, surface_features in sorted(surface_features_by_target.items(), key=lambda item: _sort_key(item[0])):
        if len(surface_features) != 1:
            audit_rows.append(
                _audit_row(
                    scope="step2_surface",
                    status="skipped",
                    reason="step2_surface_not_one_to_one",
                    detail="Step3 only builds direct relation from Step2 targets with exactly one RCSDIntersection surface.",
                    junction_id=target_id,
                    target_id=target_id,
                )
            )
            continue
        surface_feature = surface_features[0]
        surface_props = dict(surface_feature.properties)
        surface_geometry = surface_feature.geometry
        group = _resolve_group(target_id, by_mainnodeid=by_mainnodeid, singleton_by_id=singleton_by_id)
        if group.representative is None:
            audit_rows.append(
                _audit_row(
                    scope="step2_surface",
                    status="error",
                    reason=group.reason or "representative_node_missing",
                    detail=group.detail or "representative node missing for Step2 surface target",
                    junction_id=target_id,
                    target_id=target_id,
                )
            )
            continue
        representative_feature = nodes_layer_data.features[group.representative.output_index]
        representative_props = representative_feature.properties

        contained_records: list[RCSDNodeRecord] = []
        if surface_geometry is not None and rcsd_tree is not None:
            for index in rcsd_tree.query(surface_geometry, predicate="intersects"):
                record = rcsdnode_records[int(index)]
                if surface_geometry.covers(record.geometry):
                    contained_records.append(record)
        contained_semantic_ids = sorted({record.semantic_id for record in contained_records}, key=_sort_key)
        if not contained_semantic_ids:
            counts["step2_surface_no_rcsd_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="step2_surface",
                    status="skipped",
                    reason="step2_surface_no_rcsd_junction",
                    detail="Step2 RCSDIntersection surface contains no RCSD semantic junction in input RCSDNode.",
                    junction_id=target_id,
                    node_id=group.representative.node_id,
                    target_id=target_id,
                )
            )
            continue
        if len(contained_semantic_ids) > 1:
            counts["rcsdnode_error_surface_count"] += 1
            related_ids = "|".join(contained_semantic_ids)
            for semantic_id in contained_semantic_ids:
                error_record = rcsd_representatives.get(semantic_id)
                if error_record is None:
                    continue
                error_props = {
                    "error_type": "multiple_rcsd_junctions_in_step2_surface",
                    "target_id": target_id,
                    "surface_candidate_id": _normalize_id(surface_props.get("surface_candidate_id")) or "",
                    "source_rcsdintersection_id": _normalize_id(surface_props.get("source_rcsdintersection_id")) or "",
                    "rcsd_semantic_id": semantic_id,
                    "rcsd_node_id": error_record.node_id,
                    "related_rcsd_semantic_ids": related_ids,
                    "_geometry": error_record.geometry,
                }
                rcsdnode_error_rows.append(error_props)
            audit_rows.append(
                _audit_row(
                    scope="step2_surface",
                    status="error",
                    reason="multiple_rcsd_junctions_in_step2_surface",
                    detail="Step2 RCSDIntersection surface contains more than one RCSD semantic junction.",
                    junction_id=target_id,
                    node_id=group.representative.node_id,
                    target_id=target_id,
                    base_id=related_ids,
                    rcsd_exists=1,
                )
            )
            continue

        base_id = contained_semantic_ids[0]
        base_record = rcsd_representatives.get(base_id)
        if base_record is None:
            continue
        relation_record = _relation_record_from_step2_surface(
            feature_index=surface_feature.feature_index,
            surface_props=surface_props,
            surface_geometry=surface_geometry,
            base_record=base_record,
            representative_geometry=group.representative.geometry,
        )
        representative_props["is_anchor"] = "yes"
        representative_props["anchor_reason"] = None
        tentative_relations.append(relation_record)
        tentative_relation_evidence_rows.append(
            _step2_surface_relation_evidence_row(
                relation_record=relation_record,
                representative_node_id=group.representative.node_id,
                representative_props=representative_props,
                representative_geometry=group.representative.geometry,
                rcsd_geometry=base_record.geometry,
            )
        )
        linked_base_ids.add(base_id)
        counts["step2_surface_1v1_relation_count"] += 1
        audit_rows.append(
            _audit_row(
                scope="step2_surface",
                status="accepted",
                reason="step2_surface_1v1_rcsdnode_matched",
                detail="Step2 RCSDIntersection surface contains exactly one RCSD semantic junction.",
                junction_id=target_id,
                node_id=group.representative.node_id,
                target_id=target_id,
                base_id=base_id,
                rcsd_exists=1,
            )
        )

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

        for relation_record in relation_records:
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

            if relation_record.base_id in linked_base_ids:
                counts["already_linked_base_skip_count"] += 1
                audit_rows.append(
                    _audit_row(
                        scope="semantic_junction",
                        status="skipped",
                        reason="rcsd_junction_already_linked",
                        detail="relation base_id already has a Step3 relation built from Step2 one-to-one surface.",
                        junction_id=junction_id,
                        node_id=group.representative.node_id,
                        kind_2=kind_2,
                        has_evd=has_evd,
                        is_anchor=is_anchor,
                        target_id=relation_record.target_id,
                        base_id=relation_record.base_id,
                        relation_status=relation_record.status,
                        rcsd_exists=1,
                    )
                )
                continue

            representative_props["is_anchor"] = "yes"
            representative_props["anchor_reason"] = None
            tentative_relations.append(relation_record)
            tentative_relation_evidence_rows.append(
                _step3_relation_evidence_row(
                    relation_record=relation_record,
                    representative_node_id=group.representative.node_id,
                    representative_props=representative_props,
                    representative_geometry=group.representative.geometry,
                )
            )
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

    relation_cardinality_errors = _build_relation_cardinality_errors_from_records(tentative_relations)
    one_to_many_target_ids = _one_to_many_target_ids(relation_cardinality_errors)
    reset_node_ids: list[str] = []
    if one_to_many_target_ids:
        for target_id in sorted(one_to_many_target_ids, key=_sort_key):
            group = _resolve_group(target_id, by_mainnodeid=by_mainnodeid, singleton_by_id=singleton_by_id)
            if group.representative is not None:
                representative_props = nodes_layer_data.features[group.representative.output_index].properties
                representative_props["is_anchor"] = "no"
                representative_props["anchor_reason"] = None
                reset_node_ids.append(group.representative.node_id)
            audit_rows.append(
                _audit_row(
                    scope="relation_cardinality",
                    status="error",
                    reason="one_target_to_many_base_removed",
                    detail="Final Step3 relation has one SWSD semantic junction linked to multiple RCSD semantic junctions; all relations for this target were removed.",
                    junction_id=target_id,
                    target_id=target_id,
                )
            )

    accepted_relations = _dedupe_relation_records(
        [record for record in tentative_relations if record.target_id not in one_to_many_target_ids]
    )
    accepted_relation_evidence_rows = [
        row
        for row in tentative_relation_evidence_rows
        if _normalize_id(row.get("target_id")) not in one_to_many_target_ids
    ]
    newly_accepted_node_ids = sorted(
        {
            node_id
            for row in accepted_relation_evidence_rows
            if (node_id := _normalize_id(row.get("representative_node_id"))) is not None
            and _normalize_id(row.get("relation_source")) != "T07_STEP3_STEP2_SURFACE"
        },
        key=_sort_key,
    )
    node_anchor_updates = {node_id: "yes" for node_id in newly_accepted_node_ids}
    node_anchor_updates.update({node_id: "no" for node_id in reset_node_ids})
    counts["accepted_count"] = len(accepted_relations)
    counts["step2_surface_1v1_relation_count"] = sum(
        1 for record in accepted_relations if _normalize_id(record.properties.get("relation_source")) == "T07_STEP3_STEP2_SURFACE"
    )
    counts["intersection_match_backfill_relation_count"] = sum(
        1 for record in accepted_relations if _normalize_id(record.properties.get("relation_source")) != "T07_STEP3_STEP2_SURFACE"
    )
    counts["rcsdnode_error_count"] = len(rcsdnode_error_rows)
    counts["swsd_multi_rcsd_error_count"] = len(one_to_many_target_ids)
    relation_cardinality_counts = _relation_cardinality_summary(relation_cardinality_errors)

    nodes_output_path = stage_root / "nodes.gpkg"
    relation_output_path = stage_root / "intersection_match_t07.geojson"
    surface_output_path = stage_root / "t07_rcsdintersection_anchor_surface.gpkg"
    rcsdnode_error_path = stage_root / "RCSDNode_error.gpkg"
    relation_evidence_csv_path = stage_root / "t07_swsd_rcsd_relation_evidence.csv"
    relation_evidence_json_path = stage_root / "t07_swsd_rcsd_relation_evidence.json"
    relation_cardinality_errors_csv_path = stage_root / "relation_cardinality_errors.csv"
    relation_cardinality_errors_json_path = stage_root / "relation_cardinality_errors.json"
    summary_path = stage_root / "t07_step3_summary.json"
    audit_csv_path = stage_root / "t07_step3_audit.csv"
    audit_json_path = stage_root / "t07_step3_audit.json"
    perf_path = stage_root / "t07_step3_perf.json"

    write_outputs_started = time.perf_counter()
    stage_started = time.perf_counter()
    nodes_write_mode = _write_step3_nodes(
        output_path=nodes_output_path,
        features=nodes_layer_data.features,
        source_path=nodes_path,
        source_layer=nodes_layer,
        source_crs=nodes_crs,
        node_anchor_updates=node_anchor_updates,
    )
    stage_timings["write_nodes_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    _write_relation_output(relation_output_path, accepted_relations)
    stage_timings["write_relation_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    _write_rcsdnode_error_output(rcsdnode_error_path, rcsdnode_error_rows)
    stage_timings["write_rcsdnode_error_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    _write_csv(relation_cardinality_errors_csv_path, relation_cardinality_errors, RELATION_CARDINALITY_ERROR_FIELDS)
    write_json(
        relation_cardinality_errors_json_path,
        {
            "run_id": resolved_run_id,
            **relation_cardinality_counts,
            "fieldnames": RELATION_CARDINALITY_ERROR_FIELDS,
            "rows": relation_cardinality_errors,
        },
    )
    stage_timings["write_relation_cardinality_errors_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    step2_anchor_surface_path = prefer_vector_input_path(Path(nodes_path)).parent / "t07_rcsdintersection_anchor_surface.gpkg"
    surface_write_mode = _write_step3_anchor_surface(
        output_path=surface_output_path,
        step2_surface_path=step2_anchor_surface_path,
    )
    stage_timings["write_anchor_surface_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    merged_relation_evidence_rows, anchor_counts = _write_merged_relation_evidence_json(
        csv_path=relation_evidence_csv_path,
        json_path=relation_evidence_json_path,
        run_id=resolved_run_id,
        step2_evidence_path=step2_relation_evidence_path,
        step3_rows=accepted_relation_evidence_rows,
    )
    stage_timings["write_relation_evidence_seconds"] = _elapsed_since(stage_started)
    stage_timings["write_outputs_seconds"] = _elapsed_since(write_outputs_started)

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
            "intersection_match_t07": str(relation_output_path),
            "t07_rcsdintersection_anchor_surface": str(surface_output_path),
            "RCSDNode_error": str(rcsdnode_error_path),
            "t07_swsd_rcsd_relation_evidence_csv": str(relation_evidence_csv_path),
            "t07_swsd_rcsd_relation_evidence": str(relation_evidence_json_path),
            "relation_cardinality_errors_csv": str(relation_cardinality_errors_csv_path),
            "relation_cardinality_errors": str(relation_cardinality_errors_json_path),
        },
        "output_strategy": {
            "nodes_write_mode": nodes_write_mode,
            "anchor_surface_write_mode": surface_write_mode,
            "relation_write_mode": "raw_crs84" if all(record.geometry_mode == "raw_crs84" for record in accepted_relations) else "transform_to_crs84",
        },
        "crs": {
            "process": TARGET_CRS.to_string(),
            "intersection_match_t07": RELATION_OUTPUT_CRS_NAME,
        },
        "relation_evidence_row_count": len(merged_relation_evidence_rows),
        **anchor_counts,
        **relation_cardinality_counts,
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
            **relation_cardinality_counts,
        },
    )

    return T07Step3Artifacts(
        run_root=run_root,
        stage_root=stage_root,
        nodes_path=nodes_output_path,
        intersection_match_t07_path=relation_output_path,
        anchor_surface_path=surface_output_path,
        rcsdnode_error_path=rcsdnode_error_path,
        relation_evidence_csv_path=relation_evidence_csv_path,
        relation_evidence_json_path=relation_evidence_json_path,
        relation_cardinality_errors_csv_path=relation_cardinality_errors_csv_path,
        relation_cardinality_errors_json_path=relation_cardinality_errors_json_path,
        summary_path=summary_path,
        audit_csv_path=audit_csv_path,
        audit_json_path=audit_json_path,
        perf_json_path=perf_path,
    )
