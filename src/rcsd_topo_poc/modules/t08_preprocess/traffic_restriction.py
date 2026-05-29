from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pyproj import CRS
from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t08_preprocess.output_naming import ensure_tool_output_name
from rcsd_topo_poc.modules.t08_preprocess.vector_io import (
    VectorFeature,
    aggregate_bounds,
    ensure_gpkg_path,
    read_vector,
    resolve_case_insensitive_field_name,
    resolve_field_name,
    write_gpkg,
    write_json,
)


ProgressCallback = Callable[[str], None]


@dataclass(frozen=True)
class T08TrafficRestrictionArtifacts:
    restriction_output: Path
    summary_output: Path


@dataclass(frozen=True)
class ConditionRecord:
    properties: dict[str, Any]


@dataclass(frozen=True)
class LayerAudit:
    path: Path
    layer_name: str | None
    feature_count: int | None
    source_crs: CRS | None
    crs_source: str


def run_t08_traffic_restriction(
    *,
    condition_gpkg: str | Path,
    swnode_gpkg: str | Path,
    swroad_gpkg: str | Path,
    restriction_output: str | Path,
    condition_layer: str | None = None,
    swnode_layer: str | None = None,
    swroad_layer: str | None = None,
    summary_output: str | Path | None = None,
    target_epsg: int = 3857,
    condition_default_crs_text: str | None = None,
    swnode_default_crs_text: str | None = None,
    swroad_default_crs_text: str | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_interval: int = 10000,
) -> T08TrafficRestrictionArtifacts:
    started = time.perf_counter()
    condition_path = ensure_gpkg_path(condition_gpkg, label="--condition-gpkg")
    swnode_path = ensure_gpkg_path(swnode_gpkg, label="--swnode-gpkg")
    swroad_path = ensure_gpkg_path(swroad_gpkg, label="--swroad-gpkg")
    output_path = ensure_tool_output_name(
        ensure_gpkg_path(restriction_output, label="--restriction-output"),
        tool_number=7,
        label="--restriction-output",
    )
    summary_path = (
        ensure_tool_output_name(summary_output, tool_number=7, label="--summary-output")
        if summary_output
        else output_path.with_name(f"{_strip_tool_suffix(output_path.stem, tool_number=7)}_summary_tool7.json")
    )

    _emit_progress(progress_callback, f"[T08 Tool7] start condition={condition_path} swroad={swroad_path}")
    read_started = time.perf_counter()
    condition_records, condition_fields, condition_table = _read_condition_records(
        condition_path,
        layer_name=condition_layer,
    )
    swroad_result = read_vector(
        swroad_path,
        layer_name=swroad_layer,
        default_crs_text=swroad_default_crs_text,
        target_epsg=target_epsg,
    )
    swnode_audit = _read_layer_audit(
        swnode_path,
        layer_name=swnode_layer,
        default_crs_text=swnode_default_crs_text,
    )
    read_seconds = _elapsed_since(read_started)

    cond_type_field = _resolve_condition_field(condition_fields, ["CondType"], "--condition-gpkg CondType")
    in_link_field = _resolve_condition_field(condition_fields, ["inLinkID"], "--condition-gpkg inLinkID")
    out_link_field = _resolve_condition_field(condition_fields, ["outLinkID"], "--condition-gpkg outLinkID")
    road_id_field = resolve_field_name(swroad_result.features, ["id", "linkid", "LinkID"], "swroad input")

    road_by_id = _index_roads(swroad_result.features, road_id_field=road_id_field)
    output_features: list[dict[str, Any]] = []
    cond_type_1_count = 0
    missing_road_count = 0
    invalid_geometry_count = 0
    for index, record in enumerate(condition_records, start=1):
        if not _is_cond_type_one(record.properties.get(cond_type_field)):
            continue
        cond_type_1_count += 1
        in_link_id = _normalize_id(record.properties.get(in_link_field))
        out_link_id = _normalize_id(record.properties.get(out_link_field))
        in_road = road_by_id.get(in_link_id or "")
        out_road = road_by_id.get(out_link_id or "")
        if in_road is None or out_road is None:
            missing_road_count += 1
            continue
        try:
            geometry = _restriction_geometry(in_road.geometry, out_road.geometry)
        except ValueError:
            invalid_geometry_count += 1
            continue
        output_features.append({"properties": dict(record.properties), "geometry": geometry})
        if _should_emit_progress(len(output_features), progress_interval):
            _emit_progress(progress_callback, f"[T08 Tool7] built {len(output_features)} restriction feature(s)")

    write_started = time.perf_counter()
    write_stats = write_gpkg(
        output_path,
        output_features,
        crs_text=f"EPSG:{target_epsg}",
        empty_fields=condition_fields,
        geometry_type="LineString",
    )
    write_seconds = _elapsed_since(write_started)
    elapsed_seconds = _elapsed_since(started)

    summary = {
        "tool": "T08 Tool7",
        "stage": "traffic_restriction",
        "target_epsg": target_epsg,
        "input_paths": {
            "condition_gpkg": condition_path,
            "swnode_gpkg": swnode_path,
            "swroad_gpkg": swroad_path,
        },
        "output_paths": {
            "restriction_output": output_path,
            "summary_output": summary_path,
        },
        "input_crs": {
            "condition": condition_default_crs_text,
            "condition_crs_source": "non_spatial_table_or_not_used",
            "swnode": swnode_audit.source_crs.to_string() if swnode_audit.source_crs else None,
            "swnode_crs_source": swnode_audit.crs_source,
            "swroad": swroad_result.source_crs.to_string(),
            "swroad_crs_source": swroad_result.crs_source,
        },
        "params": {
            "condition_layer": condition_layer,
            "swnode_layer": swnode_layer,
            "swroad_layer": swroad_layer,
            "condition_default_crs": condition_default_crs_text,
            "swnode_default_crs": swnode_default_crs_text,
            "swroad_default_crs": swroad_default_crs_text,
            "progress_interval": progress_interval,
        },
        "field_audit": {
            "condition_table": condition_table,
            "condition_fields": list(condition_fields),
            "cond_type_field": cond_type_field,
            "in_link_field": in_link_field,
            "out_link_field": out_link_field,
            "swroad_id_field": road_id_field,
        },
        "counts": {
            "condition_record_count": len(condition_records),
            "condition_cond_type_1_count": cond_type_1_count,
            "swnode_feature_count": swnode_audit.feature_count,
            "swroad_feature_count": len(swroad_result.features),
            "swroad_id_count": len(road_by_id),
            "missing_road_count": missing_road_count,
            "invalid_geometry_count": invalid_geometry_count,
            "restriction_feature_count": len(output_features),
        },
        "output_bounds": aggregate_bounds(feature["geometry"] for feature in output_features),
        "write_stats": write_stats,
        "performance": {
            "elapsed_seconds": round(elapsed_seconds, 6),
            "read_inputs_seconds": round(read_seconds, 6),
            "write_output_seconds": round(write_seconds, 6),
            "condition_records_per_second": _items_per_second(len(condition_records), elapsed_seconds),
        },
    }
    write_json(summary_path, summary)
    _emit_progress(
        progress_callback,
        f"[T08 Tool7] finished restrictions={len(output_features)} elapsed={elapsed_seconds:.2f}s summary={summary_path}",
    )
    return T08TrafficRestrictionArtifacts(restriction_output=output_path, summary_output=summary_path)


def _read_condition_records(path: Path, *, layer_name: str | None) -> tuple[list[ConditionRecord], tuple[str, ...], str]:
    with sqlite3.connect(path) as conn:
        table_name = _resolve_table_name(conn, path=path, layer_name=layer_name)
        geometry_columns = _geometry_columns(conn, table_name=table_name)
        columns = _table_columns(conn, table_name=table_name, geometry_columns=geometry_columns)
        rows = conn.execute(
            f"SELECT {', '.join(_quote_identifier(column) for column in columns)} FROM {_quote_identifier(table_name)}"
        )
        records = [
            ConditionRecord(properties={column: row[column_index] for column_index, column in enumerate(columns)})
            for row in rows
        ]
    return records, tuple(columns), table_name


def _read_layer_audit(path: Path, *, layer_name: str | None, default_crs_text: str | None) -> LayerAudit:
    with sqlite3.connect(path) as conn:
        table_info = _resolve_geometry_table_info(conn, path=path, layer_name=layer_name)
        if table_info is None:
            raise ValueError(f"GPKG spatial layer not found for audit input: {path}")
        table_name, _geometry_column, srs_id = table_info
        feature_count = int(conn.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table_name)}").fetchone()[0])
        source_crs, crs_source = _resolve_gpkg_crs(conn, srs_id=srs_id, default_crs_text=default_crs_text)
    return LayerAudit(
        path=path,
        layer_name=table_name,
        feature_count=feature_count,
        source_crs=source_crs,
        crs_source=crs_source,
    )


def _resolve_condition_field(field_names: tuple[str, ...], candidates: list[str], label: str) -> str:
    resolved = resolve_case_insensitive_field_name({field_name: None for field_name in field_names}, candidates)
    if resolved is not None:
        return resolved
    raise ValueError(f"Required field {candidates} not found in {label}")


def _index_roads(features: list[VectorFeature], *, road_id_field: str) -> dict[str, VectorFeature]:
    indexed: dict[str, VectorFeature] = {}
    for feature in features:
        road_id = _normalize_id(feature.properties.get(road_id_field))
        if road_id is not None and road_id not in indexed:
            indexed[road_id] = feature
    return indexed


def _restriction_geometry(in_geometry: BaseGeometry, out_geometry: BaseGeometry) -> LineString:
    in_coords = _line_coords(in_geometry)
    out_coords = _line_coords(out_geometry)
    if len(in_coords) < 2 or len(out_coords) < 2:
        raise ValueError("Road geometry must contain at least two coordinates")
    best: tuple[float, bool, bool] | None = None
    for in_at_start in (False, True):
        in_point = in_coords[0] if in_at_start else in_coords[-1]
        for out_at_start in (True, False):
            out_point = out_coords[0] if out_at_start else out_coords[-1]
            distance = _point_distance(in_point, out_point)
            candidate = (distance, in_at_start, out_at_start)
            if best is None or candidate < best:
                best = candidate
    if best is None:
        raise ValueError("Could not connect road geometries")
    _distance, in_at_start, out_at_start = best
    oriented_in = list(reversed(in_coords)) if in_at_start else list(in_coords)
    oriented_out = list(out_coords) if out_at_start else list(reversed(out_coords))
    coords = list(oriented_in)
    if _point_distance(coords[-1], oriented_out[0]) <= 1e-8:
        coords.extend(oriented_out[1:])
    else:
        coords.extend(oriented_out)
    if len(coords) < 2:
        raise ValueError("Restriction geometry contains fewer than two coordinates")
    return LineString(coords)


def _line_coords(geometry: BaseGeometry) -> list[tuple[float, float]]:
    if isinstance(geometry, LineString):
        return [(float(x), float(y)) for x, y, *_rest in geometry.coords]
    if isinstance(geometry, MultiLineString):
        parts = [part for part in geometry.geoms if not part.is_empty]
        if not parts:
            return []
        longest = max(parts, key=lambda part: float(part.length))
        return [(float(x), float(y)) for x, y, *_rest in longest.coords]
    if hasattr(geometry, "geoms"):
        lines = [part for part in geometry.geoms if isinstance(part, LineString) and not part.is_empty]
        if lines:
            longest = max(lines, key=lambda part: float(part.length))
            return [(float(x), float(y)) for x, y, *_rest in longest.coords]
    return []


def _resolve_table_name(conn: sqlite3.Connection, *, path: Path, layer_name: str | None) -> str:
    user_tables = _user_tables(conn)
    if not user_tables:
        raise ValueError(f"GPKG contains no user table: {path}")
    if layer_name:
        for table_name in user_tables:
            if table_name.lower() == layer_name.lower():
                return table_name
        raise ValueError(f"Layer/table '{layer_name}' not found in {path}")
    for table_name in user_tables:
        if table_name.lower() == path.stem.lower():
            return table_name
    if len(user_tables) == 1:
        return user_tables[0]
    raise ValueError(f"GPKG has multiple user tables {user_tables}; --condition-layer is required")


def _resolve_geometry_table_info(
    conn: sqlite3.Connection,
    *,
    path: Path,
    layer_name: str | None,
) -> tuple[str, str, int] | None:
    rows = conn.execute(
        """
        SELECT table_name, column_name, srs_id
        FROM gpkg_geometry_columns
        ORDER BY table_name
        """
    ).fetchall()
    if not rows:
        return None
    if layer_name:
        for table_name, column_name, srs_id in rows:
            if str(table_name).lower() == layer_name.lower():
                return str(table_name), str(column_name), int(srs_id)
        return None
    if len(rows) == 1:
        table_name, column_name, srs_id = rows[0]
        return str(table_name), str(column_name), int(srs_id)
    for table_name, column_name, srs_id in rows:
        if str(table_name).lower() == path.stem.lower():
            return str(table_name), str(column_name), int(srs_id)
    return None


def _user_tables(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name NOT LIKE 'sqlite_%'
          AND name NOT LIKE 'gpkg_%'
          AND name NOT LIKE 'rtree_%'
          AND name NOT LIKE 'idx_%'
          AND name != 'rtree'
        ORDER BY name
        """
    ).fetchall()
    return [str(row[0]) for row in rows]


def _geometry_columns(conn: sqlite3.Connection, *, table_name: str) -> set[str]:
    try:
        rows = conn.execute(
            """
            SELECT column_name
            FROM gpkg_geometry_columns
            WHERE lower(table_name) = lower(?)
            """,
            (table_name,),
        ).fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[0]).lower() for row in rows}


def _table_columns(conn: sqlite3.Connection, *, table_name: str, geometry_columns: set[str]) -> list[str]:
    rows = conn.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    columns: list[str] = []
    for row in rows:
        name = str(row[1])
        is_pk = int(row[5] or 0) > 0
        if name.lower() in geometry_columns:
            continue
        if is_pk and name.lower() in {"fid", "ogc_fid"}:
            continue
        columns.append(name)
    if not columns:
        raise ValueError(f"Condition table '{table_name}' contains no business fields")
    return columns


def _resolve_gpkg_crs(
    conn: sqlite3.Connection,
    *,
    srs_id: int,
    default_crs_text: str | None,
) -> tuple[CRS, str]:
    row = conn.execute(
        """
        SELECT organization, organization_coordsys_id, definition
        FROM gpkg_spatial_ref_sys
        WHERE srs_id = ?
        """,
        (srs_id,),
    ).fetchone()
    if row is not None:
        organization = str(row[0] or "").upper()
        coordsys_id = int(row[1]) if row[1] is not None else None
        definition = str(row[2] or "").strip()
        if organization == "EPSG" and coordsys_id and coordsys_id > 0:
            return CRS.from_epsg(coordsys_id), "gpkg_spatial_ref_sys"
        if definition and definition.lower() != "undefined":
            return CRS.from_user_input(definition), "gpkg_spatial_ref_sys"
    if default_crs_text:
        return CRS.from_user_input(default_crs_text), "default"
    raise ValueError("GPKG CRS not found and no default CRS configured")


def _is_cond_type_one(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return False
        try:
            return float(text) == 1.0
        except ValueError:
            return text == "1"
    try:
        return float(value) == 1.0
    except (TypeError, ValueError):
        return False


def _normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in {"null", "none", "nan"}:
            return None
        return text
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _point_distance(left: tuple[float, float], right: tuple[float, float]) -> float:
    return ((left[0] - right[0]) ** 2 + (left[1] - right[1]) ** 2) ** 0.5


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _strip_tool_suffix(stem: str, *, tool_number: int) -> str:
    suffix = f"_tool{tool_number}"
    return stem[: -len(suffix)] if stem.endswith(suffix) else stem


def _emit_progress(callback: ProgressCallback | None, message: str) -> None:
    if callback is not None:
        callback(message)


def _should_emit_progress(count: int, progress_interval: int) -> bool:
    return progress_interval > 0 and count > 0 and count % progress_interval == 0


def _elapsed_since(started: float) -> float:
    return max(0.0, time.perf_counter() - started)


def _items_per_second(count: int, seconds: float) -> float | None:
    if seconds <= 0:
        return None
    return round(float(count) / seconds, 6)
