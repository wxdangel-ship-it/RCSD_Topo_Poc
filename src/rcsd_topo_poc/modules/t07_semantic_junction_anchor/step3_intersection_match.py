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


STEP3_SURFACE_KIND2 = {"4", "8", "16", "2048"}
STEP3_BACKFILL_KIND2 = {"4", "8", "16", "128", "2048"}
STEP3_SCOPE_KIND2 = STEP3_SURFACE_KIND2 | STEP3_BACKFILL_KIND2


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


def _relation_output_properties(record: RelationRecord) -> dict[str, Any]:
    properties = dict(record.properties)
    if record.target_id is not None:
        properties["target_id"] = record.target_id
    if record.base_id is not None:
        properties["base_id"] = record.base_id
    return properties


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
                        "properties": _relation_output_properties(record),
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
                "properties": _relation_output_properties(record),
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
    return [_canonicalize_relation_evidence_row(dict(row)) for row in rows if isinstance(row, dict)]


def _canonicalize_pipe_id_value(value: Any) -> Any:
    if value is None:
        return value
    text = str(value).strip()
    if not text:
        return value
    if "|" in text:
        parts = []
        for part in text.split("|"):
            normalized = _normalize_id(part)
            parts.append(normalized if normalized is not None else part.strip())
        return "|".join(parts)
    normalized = _normalize_id(value)
    if normalized is not None and normalized != text:
        return normalized
    return value


def _canonicalize_relation_evidence_row(row: dict[str, Any]) -> dict[str, Any]:
    for field_name in ("target_id", "representative_node_id"):
        if field_name not in row:
            continue
        normalized = _normalize_id(row.get(field_name))
        row[field_name] = normalized or ""
    if "base_id_candidate" in row:
        row["base_id_candidate"] = _canonicalize_pipe_id_value(row.get("base_id_candidate"))
    return row


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
        _canonicalize_gpkg_id_fields(
            output_path,
            layer_name=None,
            field_names=("target_id", "mainnodeid", "representative_node_id"),
        )
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


def _canonicalize_gpkg_id_fields(
    path: Path,
    *,
    layer_name: str | None,
    field_names: tuple[str, ...],
) -> None:
    resolved_layer = _resolve_gpkg_layer(path, layer_name)
    with sqlite3.connect(str(path)) as conn:
        columns = [str(row[1]) for row in conn.execute(f"PRAGMA table_info({_quote_identifier(resolved_layer)})")]
        resolved_fields = [
            field
            for field_name in field_names
            if (field := _field_name_case_insensitive(columns, field_name)) is not None
        ]
        if not resolved_fields:
            return
        select_sql = (
            "SELECT rowid, "
            + ", ".join(_quote_identifier(field) for field in resolved_fields)
            + " FROM "
            + _quote_identifier(resolved_layer)
        )
        update_sql = (
            "UPDATE "
            + _quote_identifier(resolved_layer)
            + " SET "
            + ", ".join(f"{_quote_identifier(field)} = ?" for field in resolved_fields)
            + " WHERE rowid = ?"
        )
        updates: list[tuple[Any, ...]] = []
        for row in conn.execute(select_sql):
            rowid = row[0]
            values = list(row[1:])
            next_values = []
            changed = False
            for value in values:
                normalized = _normalize_id(value)
                next_value = normalized if normalized is not None else value
                next_values.append(next_value)
                if normalized is not None and normalized != str(value).strip():
                    changed = True
            if changed:
                updates.append((*next_values, rowid))
        if updates:
            conn.executemany(update_sql, updates)


from .step3_pipeline import run_t07_step3_intersection_match
