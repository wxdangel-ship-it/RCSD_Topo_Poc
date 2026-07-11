from __future__ import annotations

import json
import math
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from pyproj import CRS
from shapely import to_wkb
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry


GPKG_APPLICATION_ID = 0x47504B47
GPKG_USER_VERSION = 10300
GPKG_FID_COLUMN = "fid"
GPKG_GEOMETRY_COLUMN = "geom"
GPKG_OGR_CONTENTS_TABLE = "gpkg_ogr_contents"
GPKG_BATCH_SIZE = 1000
GPKG_IN_MEMORY_PUBLISH_MAX_RECORDS = 64


def write_gpkg_fast(
    path: Path,
    features: Iterable[dict[str, Any]],
    *,
    crs_text: str,
    layer_name: str | None = None,
) -> dict[str, Any]:
    output_path = Path(path)
    records = [_prepare_record(feature) for feature in features]
    schema = _build_schema(records)
    return _write_records(
        output_path,
        records=records,
        crs=CRS.from_user_input(crs_text),
        layer_name=layer_name or output_path.stem,
        schema=schema,
    )


def _prepare_record(feature: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    lower_seen: set[str] = set()
    for key, value in (feature.get("properties") or {}).items():
        text = str(key)
        lower = text.lower()
        if lower in lower_seen:
            continue
        lower_seen.add(lower)
        properties[text] = _property_value(value)
    return {"properties": properties, "geometry": feature.get("geometry")}


def _build_schema(records: list[dict[str, Any]]) -> dict[str, str]:
    field_order: list[str] = []
    lower_to_field: dict[str, str] = {}
    values_by_field: dict[str, list[Any]] = {}
    for record in records:
        for key, value in record["properties"].items():
            lower = key.lower()
            field_name = lower_to_field.get(lower)
            if field_name is None:
                lower_to_field[lower] = key
                field_name = key
                field_order.append(field_name)
                values_by_field[field_name] = []
            values_by_field[field_name].append(value)
    return {field_name: _sqlite_type(values_by_field[field_name]) for field_name in field_order}


def _write_records(
    output_path: Path,
    *,
    records: list[dict[str, Any]],
    crs: CRS,
    layer_name: str,
    schema: dict[str, str],
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _remove_existing_gpkg(output_path)

    table_name = _sanitize_layer_name(layer_name)
    field_mapping = _field_mapping(schema.keys())
    srs_id = _srs_record(crs)[0]
    geometry_types: set[str] = set()
    bounds_values: list[tuple[float, float, float, float]] = []
    z_dimensions: set[bool] = set()
    batch: list[list[Any]] = []
    for record_index, record in enumerate(records, start=1):
        geometry = _geometry_object(record.get("geometry"), record_index=record_index)
        geometry_types.add(geometry.geom_type.upper())
        bounds_values.append(tuple(float(value) for value in geometry.bounds))
        z_dimensions.add(bool(getattr(geometry, "has_z", False)))
        row_values = [
            _sqlite_value(record["properties"].get(original_name))
            for original_name in field_mapping
        ]
        row_values.append(_build_gpkg_geometry_blob(geometry, srs_id))
        batch.append(row_values)

    bounds = _aggregate_bounds(bounds_values)
    geometry_type_name = _geometry_type_name(geometry_types)
    z_mode = _geometry_z_mode(geometry_type_name, z_dimensions)
    publish_from_memory = len(records) <= GPKG_IN_MEMORY_PUBLISH_MAX_RECORDS
    if publish_from_memory:
        _publish_small_records_from_template(
            output_path,
            batch=batch,
            crs=crs,
            table_name=table_name,
            field_mapping=field_mapping,
            schema=schema,
            bounds=bounds,
            geometry_type_name=geometry_type_name,
            z_mode=z_mode,
        )
        return {
            "feature_count": len(records),
            "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
        }

    with sqlite3.connect(str(output_path)) as conn:
        _initialize_gpkg_metadata(conn)
        insert_sql = _create_feature_table(
            conn,
            table_name=table_name,
            field_mapping=field_mapping,
            field_types=schema,
        )
        if batch:
            for offset in range(0, len(batch), GPKG_BATCH_SIZE):
                conn.executemany(insert_sql, batch[offset : offset + GPKG_BATCH_SIZE])

        _insert_gpkg_metadata_rows(
            conn,
            table_name=table_name,
            crs=crs,
            bounds=bounds,
            geometry_type_name=geometry_type_name,
            z_mode=z_mode,
            feature_count=len(records),
        )
        conn.commit()

    return {
        "feature_count": len(records),
        "size_bytes": output_path.stat().st_size if output_path.exists() else 0,
    }


def _publish_small_records_from_template(
    output_path: Path,
    *,
    batch: list[list[Any]],
    crs: CRS,
    table_name: str,
    field_mapping: dict[str, str],
    schema: dict[str, str],
    bounds: list[float] | None,
    geometry_type_name: str,
    z_mode: int,
) -> None:
    template_bytes = _small_gpkg_template_bytes(
        crs.to_wkt(),
        table_name,
        tuple(field_mapping.items()),
        tuple(schema.items()),
        geometry_type_name,
        z_mode,
    )
    output_path.write_bytes(template_bytes)
    insert_sql = _feature_insert_sql(table_name=table_name, field_mapping=field_mapping)
    with sqlite3.connect(str(output_path)) as conn:
        conn.execute("PRAGMA synchronous = OFF")
        if batch:
            conn.executemany(insert_sql, batch)
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        conn.execute(
            """
            UPDATE gpkg_contents
            SET last_change = ?, min_x = ?, min_y = ?, max_x = ?, max_y = ?
            WHERE table_name = ?
            """,
            (
                now_iso,
                bounds[0] if bounds else None,
                bounds[1] if bounds else None,
                bounds[2] if bounds else None,
                bounds[3] if bounds else None,
                table_name,
            ),
        )
        conn.commit()


@lru_cache(maxsize=128)
def _small_gpkg_template_bytes(
    crs_wkt: str,
    table_name: str,
    field_mapping_items: tuple[tuple[str, str], ...],
    schema_items: tuple[tuple[str, str], ...],
    geometry_type_name: str,
    z_mode: int,
) -> bytes:
    crs = CRS.from_wkt(crs_wkt)
    field_mapping = dict(field_mapping_items)
    schema = dict(schema_items)
    with tempfile.TemporaryDirectory(prefix="rcsd_gpkg_template_") as temp_dir:
        template_path = Path(temp_dir) / "template.gpkg"
        conn = sqlite3.connect(str(template_path))
        try:
            _initialize_gpkg_metadata(conn)
            _create_feature_table(
                conn,
                table_name=table_name,
                field_mapping=field_mapping,
                field_types=schema,
            )
            _insert_gpkg_metadata_rows(
                conn,
                table_name=table_name,
                crs=crs,
                bounds=None,
                geometry_type_name=geometry_type_name,
                z_mode=z_mode,
                feature_count=0,
            )
            conn.commit()
        finally:
            conn.close()
        return template_path.read_bytes()


def _remove_existing_gpkg(path: Path) -> None:
    for candidate in (path, path.with_name(f"{path.name}-wal"), path.with_name(f"{path.name}-shm"), path.with_name(f"{path.name}-journal")):
        if candidate.exists():
            candidate.unlink()


def _geometry_object(geometry: Any, *, record_index: int) -> BaseGeometry:
    if geometry is None:
        raise ValueError(f"Feature {record_index} has no geometry")
    geometry_obj = geometry if isinstance(geometry, BaseGeometry) else shape(geometry)
    if geometry_obj.is_empty:
        raise ValueError(f"Feature {record_index} has empty geometry")
    return geometry_obj


def _property_value(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (list, tuple, set)):
        return json.dumps([_json_plain(item) for item in value], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if isinstance(value, dict):
        return json.dumps(_json_plain(value), ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return str(value)


def _json_plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return str(value)


def _sqlite_value(value: Any) -> Any:
    value = _property_value(value)
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _sqlite_type(values: Iterable[Any]) -> str:
    non_null = [value for value in values if value is not None]
    if not non_null:
        return "TEXT"
    if all(isinstance(value, bool) for value in non_null):
        return "BOOLEAN"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in non_null):
        return "INTEGER"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in non_null):
        return "REAL" if any(isinstance(value, float) for value in non_null) else "INTEGER"
    return "TEXT"


def _sanitize_layer_name(name: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z_]+", "_", str(name)).strip("_")
    if not sanitized:
        sanitized = "layer"
    if sanitized[0].isdigit():
        sanitized = f"layer_{sanitized}"
    return sanitized


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _quote_sql_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _field_mapping(field_names: Iterable[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    used_lower = {GPKG_FID_COLUMN.lower(), GPKG_GEOMETRY_COLUMN.lower()}
    for original_name in field_names:
        base_name = str(original_name).strip() or "field"
        candidate = base_name
        suffix_index = 1
        while candidate.lower() in used_lower:
            suffix_index += 1
            candidate = f"{base_name}_{suffix_index}"
        mapping[str(original_name)] = candidate
        used_lower.add(candidate.lower())
    return mapping


def _srs_record(crs: CRS) -> tuple[int, str, int, str, str]:
    epsg = crs.to_epsg()
    if epsg is not None:
        return epsg, "EPSG", epsg, crs.to_wkt(), crs.name
    return 999000, "NONE", 999000, crs.to_wkt(), crs.name or "custom"


def _initialize_gpkg_metadata(conn: sqlite3.Connection) -> None:
    conn.execute(f"PRAGMA application_id = {GPKG_APPLICATION_ID}")
    conn.execute(f"PRAGMA user_version = {GPKG_USER_VERSION}")
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute(
        """
        CREATE TABLE gpkg_spatial_ref_sys (
            srs_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL PRIMARY KEY,
            organization TEXT NOT NULL,
            organization_coordsys_id INTEGER NOT NULL,
            definition TEXT NOT NULL,
            description TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE gpkg_contents (
            table_name TEXT NOT NULL PRIMARY KEY,
            data_type TEXT NOT NULL,
            identifier TEXT UNIQUE,
            description TEXT DEFAULT '',
            last_change DATETIME NOT NULL,
            min_x DOUBLE,
            min_y DOUBLE,
            max_x DOUBLE,
            max_y DOUBLE,
            srs_id INTEGER
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE gpkg_geometry_columns (
            table_name TEXT NOT NULL,
            column_name TEXT NOT NULL,
            geometry_type_name TEXT NOT NULL,
            srs_id INTEGER NOT NULL,
            z TINYINT NOT NULL,
            m TINYINT NOT NULL,
            PRIMARY KEY (table_name, column_name)
        )
        """
    )
    _ensure_gpkg_ogr_contents_table(conn)
    conn.executemany(
        """
        INSERT INTO gpkg_spatial_ref_sys (
            srs_name, srs_id, organization, organization_coordsys_id, definition, description
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("Undefined Cartesian SRS", -1, "NONE", -1, "undefined", "undefined cartesian coordinate reference system"),
            ("Undefined Geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic coordinate reference system"),
            ("WGS 84", 4326, "EPSG", 4326, CRS.from_epsg(4326).to_wkt(), "longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid"),
        ],
    )


def _create_feature_table(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    field_mapping: dict[str, str],
    field_types: dict[str, str],
) -> str:
    column_defs = [f"{_quote_identifier(GPKG_FID_COLUMN)} INTEGER PRIMARY KEY AUTOINCREMENT"]
    for original_name, output_name in field_mapping.items():
        column_defs.append(f"{_quote_identifier(output_name)} {field_types.get(original_name, 'TEXT')}")
    column_defs.append(f"{_quote_identifier(GPKG_GEOMETRY_COLUMN)} BLOB")
    conn.execute(f"CREATE TABLE {_quote_identifier(table_name)} ({', '.join(column_defs)})")
    return _feature_insert_sql(table_name=table_name, field_mapping=field_mapping)


def _feature_insert_sql(*, table_name: str, field_mapping: dict[str, str]) -> str:
    insert_columns = [field_mapping[original_name] for original_name in field_mapping] + [GPKG_GEOMETRY_COLUMN]
    placeholders = ", ".join("?" for _ in insert_columns)
    return (
        f"INSERT INTO {_quote_identifier(table_name)} "
        f"({', '.join(_quote_identifier(name) for name in insert_columns)}) VALUES ({placeholders})"
    )


def _insert_gpkg_metadata_rows(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    crs: CRS,
    bounds: list[float] | None,
    geometry_type_name: str,
    z_mode: int,
    feature_count: int,
) -> None:
    srs_id, organization, organization_coordsys_id, definition, srs_name = _srs_record(crs)
    conn.execute(
        """
        INSERT OR REPLACE INTO gpkg_spatial_ref_sys (
            srs_name, srs_id, organization, organization_coordsys_id, definition, description
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (srs_name, srs_id, organization, organization_coordsys_id, definition, srs_name),
    )
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    conn.execute(
        """
        INSERT INTO gpkg_contents (
            table_name, data_type, identifier, description, last_change,
            min_x, min_y, max_x, max_y, srs_id
        ) VALUES (?, 'features', ?, '', ?, ?, ?, ?, ?, ?)
        """,
        (
            table_name,
            table_name,
            now_iso,
            bounds[0] if bounds else None,
            bounds[1] if bounds else None,
            bounds[2] if bounds else None,
            bounds[3] if bounds else None,
            srs_id,
        ),
    )
    conn.execute(
        """
        INSERT INTO gpkg_geometry_columns (
            table_name, column_name, geometry_type_name, srs_id, z, m
        ) VALUES (?, ?, ?, ?, ?, 0)
        """,
        (table_name, GPKG_GEOMETRY_COLUMN, geometry_type_name, srs_id, z_mode),
    )
    _insert_gpkg_ogr_feature_count(conn, table_name=table_name, feature_count=feature_count)


def _ensure_gpkg_ogr_contents_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {GPKG_OGR_CONTENTS_TABLE} (
            table_name TEXT NOT NULL PRIMARY KEY,
            feature_count INTEGER DEFAULT NULL
        )
        """
    )


def _insert_gpkg_ogr_feature_count(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    feature_count: int,
) -> None:
    conn.execute(
        f"""
        INSERT OR REPLACE INTO {GPKG_OGR_CONTENTS_TABLE} (table_name, feature_count)
        VALUES (?, ?)
        """,
        (table_name, int(feature_count)),
    )
    trigger_suffix = _sanitize_layer_name(table_name)
    table_identifier = _quote_identifier(table_name)
    table_literal = _quote_sql_literal(table_name)
    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS {_quote_identifier(f"trigger_insert_feature_count_{trigger_suffix}")}
        AFTER INSERT ON {table_identifier}
        BEGIN
            UPDATE {GPKG_OGR_CONTENTS_TABLE}
            SET feature_count = feature_count + 1
            WHERE table_name = {table_literal};
        END
        """
    )
    conn.execute(
        f"""
        CREATE TRIGGER IF NOT EXISTS {_quote_identifier(f"trigger_delete_feature_count_{trigger_suffix}")}
        AFTER DELETE ON {table_identifier}
        BEGIN
            UPDATE {GPKG_OGR_CONTENTS_TABLE}
            SET feature_count = feature_count - 1
            WHERE table_name = {table_literal};
        END
        """
    )


def _build_gpkg_geometry_blob(geometry: BaseGeometry, srs_id: int) -> bytes:
    wkb = to_wkb(geometry, hex=False, byte_order=1)
    flags = 1
    return b"GP" + bytes((0, flags)) + int(srs_id).to_bytes(4, "little", signed=True) + wkb


def _geometry_type_name(geometry_types: set[str]) -> str:
    if len(geometry_types) == 1:
        return next(iter(geometry_types))
    return "GEOMETRY"


def _geometry_z_mode(geometry_type_name: str, z_dimensions: set[bool]) -> int:
    if True not in z_dimensions:
        return 0
    if geometry_type_name == "GEOMETRY" or False in z_dimensions:
        return 2
    return 1


def _aggregate_bounds(bounds_values: list[tuple[float, float, float, float]]) -> list[float] | None:
    if not bounds_values:
        return None
    return [
        min(bounds[0] for bounds in bounds_values),
        min(bounds[1] for bounds in bounds_values),
        max(bounds[2] for bounds in bounds_values),
        max(bounds[3] for bounds in bounds_values),
    ]
