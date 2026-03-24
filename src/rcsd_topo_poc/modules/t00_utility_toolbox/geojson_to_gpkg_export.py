from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyproj import CRS
from shapely import to_wkb
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    aggregate_bounds,
    announce,
    build_logger,
    build_run_id,
    close_logger,
    minimal_geometry_repair,
    remove_existing_output,
    resolve_geojson_crs,
    write_json,
)


RUN_ID_PREFIX = "t00_tool7_geojson_to_gpkg"
PROGRESS_INTERVAL = 25
GPKG_APPLICATION_ID = 0x47504B47
GPKG_USER_VERSION = 10300
GEOMETRY_COLUMN_NAME = "geom"
FID_COLUMN_NAME = "fid"
STANDARD_WGS84_CRS = CRS.from_epsg(4326)


@dataclass(frozen=True)
class GeoJsonToGpkgDirectoryConfig:
    directory_path: Path
    default_input_crs_text: str | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class _PreparedFeature:
    geometry: BaseGeometry
    properties: dict[str, Any]


def _should_report_progress(index: int, total: int, interval: int = PROGRESS_INTERVAL) -> bool:
    return index == 1 or index == total or index % interval == 0


def _sanitize_layer_name(name: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z_]+", "_", name).strip("_")
    if not sanitized:
        sanitized = "layer"
    if sanitized[0].isdigit():
        sanitized = f"layer_{sanitized}"
    return sanitized


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str, bytes)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _infer_sqlite_type(values: list[Any]) -> str:
    non_null = [value for value in values if value is not None]
    if not non_null:
        return "TEXT"
    if any(isinstance(value, bytes) for value in non_null):
        return "BLOB"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in non_null):
        return "INTEGER"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in non_null):
        return "REAL" if any(isinstance(value, float) for value in non_null) else "INTEGER"
    return "TEXT"


def _resolve_field_mapping(features: list[_PreparedFeature]) -> dict[str, str]:
    field_mapping: dict[str, str] = {}
    used_lower = {FID_COLUMN_NAME.lower(), GEOMETRY_COLUMN_NAME.lower()}
    original_field_names: list[str] = []
    seen_original_fields: set[str] = set()
    for feature in features:
        for name in feature.properties.keys():
            if name not in seen_original_fields:
                original_field_names.append(name)
                seen_original_fields.add(name)

    for original_name in original_field_names:
        base_name = str(original_name).strip() or "field"
        candidate = base_name
        suffix_index = 1
        while candidate.lower() in used_lower:
            suffix_index += 1
            candidate = f"{base_name}_{suffix_index}"
        field_mapping[original_name] = candidate
        used_lower.add(candidate.lower())
    return field_mapping


def _detect_geometry_type_name(geometries: list[BaseGeometry]) -> str:
    type_names = {geometry.geom_type.upper() for geometry in geometries if geometry is not None and not geometry.is_empty}
    if not type_names:
        return "GEOMETRY"
    if len(type_names) == 1:
        return next(iter(type_names))
    return "GEOMETRY"


def _srs_record(crs: CRS) -> tuple[int, str, int, str, str]:
    epsg = crs.to_epsg()
    if epsg is not None:
        return epsg, "EPSG", epsg, crs.to_wkt(), crs.name
    return 999000, "NONE", 999000, crs.to_wkt(), crs.name or "custom"


def _initialize_gpkg_metadata(conn: sqlite3.Connection) -> None:
    conn.execute(f"PRAGMA application_id = {GPKG_APPLICATION_ID}")
    conn.execute(f"PRAGMA user_version = {GPKG_USER_VERSION}")
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

    conn.executemany(
        """
        INSERT INTO gpkg_spatial_ref_sys (
            srs_name, srs_id, organization, organization_coordsys_id, definition, description
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                "Undefined Cartesian SRS",
                -1,
                "NONE",
                -1,
                "undefined",
                "undefined cartesian coordinate reference system",
            ),
            (
                "Undefined Geographic SRS",
                0,
                "NONE",
                0,
                "undefined",
                "undefined geographic coordinate reference system",
            ),
            (
                STANDARD_WGS84_CRS.name,
                4326,
                "EPSG",
                4326,
                STANDARD_WGS84_CRS.to_wkt(),
                "longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid",
            ),
        ],
    )


def _build_gpkg_geometry_blob(geometry: BaseGeometry, srs_id: int) -> bytes:
    wkb = to_wkb(geometry, hex=False, byte_order=1)
    flags = 1  # little endian, standard binary, no envelope, non-empty
    return b"GP" + bytes((0, flags)) + int(srs_id).to_bytes(4, "little", signed=True) + wkb


def _write_single_gpkg(
    output_path: Path,
    *,
    table_name: str,
    crs: CRS,
    features: list[_PreparedFeature],
    field_mapping: dict[str, str],
) -> None:
    srs_id, organization, organization_coordsys_id, definition, srs_name = _srs_record(crs)
    geometry_type_name = _detect_geometry_type_name([feature.geometry for feature in features])
    has_z = 1 if any(feature.geometry.has_z for feature in features) else 0
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    bounds = aggregate_bounds([feature.geometry for feature in features])
    field_types = {
        original_name: _infer_sqlite_type([_normalize_value(feature.properties.get(original_name)) for feature in features])
        for original_name in field_mapping
    }

    remove_existing_output(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(output_path) as conn:
        _initialize_gpkg_metadata(conn)
        conn.execute(
            """
            INSERT OR REPLACE INTO gpkg_spatial_ref_sys (
                srs_name, srs_id, organization, organization_coordsys_id, definition, description
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (srs_name, srs_id, organization, organization_coordsys_id, definition, srs_name),
        )

        column_defs = [f"{_quote_identifier(FID_COLUMN_NAME)} INTEGER PRIMARY KEY AUTOINCREMENT"]
        for original_name, output_name in field_mapping.items():
            column_defs.append(f"{_quote_identifier(output_name)} {field_types[original_name]}")
        column_defs.append(f"{_quote_identifier(GEOMETRY_COLUMN_NAME)} BLOB")
        conn.execute(f"CREATE TABLE {_quote_identifier(table_name)} ({', '.join(column_defs)})")

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
            (table_name, GEOMETRY_COLUMN_NAME, geometry_type_name, srs_id, has_z),
        )

        insert_columns = [field_mapping[original_name] for original_name in field_mapping] + [GEOMETRY_COLUMN_NAME]
        placeholders = ", ".join("?" for _ in insert_columns)
        insert_sql = (
            f"INSERT INTO {_quote_identifier(table_name)} "
            f"({', '.join(_quote_identifier(name) for name in insert_columns)}) VALUES ({placeholders})"
        )

        for feature in features:
            row_values = [_normalize_value(feature.properties.get(original_name)) for original_name in field_mapping]
            row_values.append(_build_gpkg_geometry_blob(feature.geometry, srs_id))
            conn.execute(insert_sql, row_values)

        conn.commit()


def _convert_single_geojson_file(
    input_path: Path,
    output_path: Path,
    *,
    default_input_crs_text: str | None,
) -> dict[str, Any]:
    doc = json.loads(input_path.read_text(encoding="utf-8"))
    source_crs, crs_source = resolve_geojson_crs(doc, default_input_crs_text)
    input_features = doc.get("features", [])
    geometry_type_counter = Counter()
    error_reason_counter = Counter()
    failed_feature_indexes: list[int] = []
    repaired_feature_count = 0
    prepared_features: list[_PreparedFeature] = []

    for index, feature in enumerate(input_features, start=1):
        try:
            geometry_payload = feature.get("geometry")
            if geometry_payload is None:
                raise ValueError("missing geometry")

            raw_geometry = shape(geometry_payload)
            if raw_geometry.is_empty:
                raise ValueError("geometry is empty")

            repaired_geometry = raw_geometry
            if not raw_geometry.is_valid:
                repaired_geometry = minimal_geometry_repair(raw_geometry)
                if repaired_geometry is None:
                    raise ValueError("minimal repair failed")
                repaired_feature_count += 1

            geometry_type_counter[repaired_geometry.geom_type] += 1
            prepared_features.append(
                _PreparedFeature(
                    geometry=repaired_geometry,
                    properties=dict(feature.get("properties") or {}),
                )
            )
        except Exception as exc:
            failed_feature_indexes.append(index)
            error_reason_counter[str(exc)] += 1

    field_mapping = _resolve_field_mapping(prepared_features)
    table_name = _sanitize_layer_name(input_path.stem)
    _write_single_gpkg(
        output_path,
        table_name=table_name,
        crs=source_crs,
        features=prepared_features,
        field_mapping=field_mapping,
    )

    return {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "status": "completed",
        "source_crs": source_crs.to_string(),
        "crs_source": crs_source,
        "input_feature_count": len(input_features),
        "output_feature_count": len(prepared_features),
        "repaired_feature_count": repaired_feature_count,
        "failed_feature_count": len(failed_feature_indexes),
        "failed_feature_indexes": failed_feature_indexes,
        "geometry_type_summary": dict(geometry_type_counter),
        "error_reason_summary": dict(error_reason_counter),
        "field_names": list(field_mapping.keys()),
        "output_field_names": list(field_mapping.values()),
        "field_name_mapping": field_mapping,
        "output_table_name": table_name,
    }


def run_geojson_to_gpkg_directory_export(config: GeoJsonToGpkgDirectoryConfig) -> dict[str, Any]:
    directory_path = config.directory_path.expanduser().resolve()
    if not directory_path.is_dir():
        raise ValueError(f"directory does not exist or is not a directory: {directory_path}")

    run_id = config.run_id or build_run_id(RUN_ID_PREFIX)
    log_path = directory_path / f"{run_id}.log"
    summary_path = directory_path / f"{run_id}_summary.json"
    logger = build_logger(log_path, run_id)

    try:
        geojson_paths = sorted(
            [path for path in directory_path.iterdir() if path.is_file() and path.suffix.lower() == ".geojson"],
            key=lambda path: path.name.lower(),
        )
        total_file_count = len(geojson_paths)

        announce(logger, f"Tool7 GeoJSON to GPKG export started. directory_path={directory_path}")
        announce(logger, f"[Stage 1/3] Discover top-level GeoJSON files. geojson_file_count={total_file_count}")

        file_results: list[dict[str, Any]] = []
        error_reason_counter = Counter()
        converted_file_count = 0
        failed_file_count = 0
        total_input_feature_count = 0
        total_output_feature_count = 0

        announce(logger, "[Stage 2/3] Convert each top-level GeoJSON file into a sibling GPKG.")
        for index, input_path in enumerate(geojson_paths, start=1):
            output_path = input_path.with_suffix(".gpkg")
            announce(logger, f"[File {index}/{total_file_count}] start input_path={input_path.name}")
            try:
                file_summary = _convert_single_geojson_file(
                    input_path,
                    output_path,
                    default_input_crs_text=config.default_input_crs_text,
                )
                file_results.append(file_summary)
                converted_file_count += 1
                total_input_feature_count += int(file_summary["input_feature_count"])
                total_output_feature_count += int(file_summary["output_feature_count"])
                for reason, count in file_summary["error_reason_summary"].items():
                    error_reason_counter[reason] += count
                announce(
                    logger,
                    f"[File {index}/{total_file_count}] completed output_path={output_path.name} "
                    f"input_feature_count={file_summary['input_feature_count']} "
                    f"output_feature_count={file_summary['output_feature_count']}",
                )
            except Exception as exc:
                failed_file_count += 1
                error_reason_counter[str(exc)] += 1
                file_results.append(
                    {
                        "input_path": str(input_path),
                        "output_path": str(output_path),
                        "status": "failed",
                        "source_crs": None,
                        "crs_source": None,
                        "input_feature_count": 0,
                        "output_feature_count": 0,
                        "repaired_feature_count": 0,
                        "failed_feature_count": 0,
                        "failed_feature_indexes": [],
                        "geometry_type_summary": {},
                        "error_reason_summary": {str(exc): 1},
                        "field_names": [],
                        "output_field_names": [],
                        "field_name_mapping": {},
                        "output_table_name": _sanitize_layer_name(input_path.stem),
                    }
                )
                announce(
                    logger,
                    f"[File {index}/{total_file_count}] failed input_path={input_path.name} reason={exc}",
                )

        announce(logger, "[Stage 3/3] Write summary and finish Tool7.")
        summary = {
            "run_id": run_id,
            "tool": "Tool7",
            "directory_path": str(directory_path),
            "log_path": str(log_path),
            "summary_path": str(summary_path),
            "geojson_file_count": total_file_count,
            "converted_file_count": converted_file_count,
            "failed_file_count": failed_file_count,
            "total_input_feature_count": total_input_feature_count,
            "total_output_feature_count": total_output_feature_count,
            "file_results": file_results,
            "error_reason_summary": dict(error_reason_counter),
            "non_recursive_scan": True,
            "output_format": "GPKG",
        }
        write_json(summary_path, summary)
        announce(
            logger,
            "Tool7 GeoJSON to GPKG export finished. "
            f"geojson_file_count={total_file_count} converted_file_count={converted_file_count} "
            f"failed_file_count={failed_file_count}",
        )
        return summary
    finally:
        close_logger(logger)
