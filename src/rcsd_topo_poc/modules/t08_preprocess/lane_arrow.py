from __future__ import annotations

import sqlite3
import time
from collections import defaultdict
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
class T08LaneArrowArtifacts:
    arrow_output: Path
    summary_output: Path


@dataclass(frozen=True)
class LaneRecord:
    row_index: int
    properties: dict[str, Any]


@dataclass(frozen=True)
class LayerAudit:
    path: Path
    layer_name: str | None
    feature_count: int | None
    source_crs: CRS | None
    crs_source: str


@dataclass(frozen=True)
class RoadIndex:
    roads_by_id: dict[str, VectorFeature]
    duplicate_id_count: int


def run_t08_lane_arrow(
    *,
    lane_gpkg: str | Path,
    swnode_gpkg: str | Path,
    swroad_gpkg: str | Path,
    arrow_output: str | Path,
    lane_layer: str | None = None,
    swnode_layer: str | None = None,
    swroad_layer: str | None = None,
    summary_output: str | Path | None = None,
    target_epsg: int = 3857,
    swnode_default_crs_text: str | None = None,
    swroad_default_crs_text: str | None = None,
    progress_callback: ProgressCallback | None = None,
    progress_interval: int = 10000,
) -> T08LaneArrowArtifacts:
    started = time.perf_counter()
    lane_path = ensure_gpkg_path(lane_gpkg, label="--lane-gpkg")
    swnode_path = ensure_gpkg_path(swnode_gpkg, label="--swnode-gpkg")
    swroad_path = ensure_gpkg_path(swroad_gpkg, label="--swroad-gpkg")
    output_path = ensure_tool_output_name(
        ensure_gpkg_path(arrow_output, label="--arrow-output"),
        tool_number=8,
        label="--arrow-output",
    )
    summary_path = (
        ensure_tool_output_name(summary_output, tool_number=8, label="--summary-output")
        if summary_output
        else output_path.with_name(f"{_strip_tool_suffix(output_path.stem, tool_number=8)}_summary_tool8.json")
    )

    _emit_progress(progress_callback, f"[T08 Tool8] start lane={lane_path} swroad={swroad_path}")
    read_started = time.perf_counter()
    lane_records, lane_fields, lane_table = _read_lane_records(lane_path, layer_name=lane_layer)
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

    link_field = _resolve_lane_field(lane_fields, ["LinkID"], "--lane-gpkg LinkID")
    seq_field = _resolve_lane_field(lane_fields, ["Seq_Nm"], "--lane-gpkg Seq_Nm")
    arrow_field = _resolve_lane_field(lane_fields, ["Arrow_Dir"], "--lane-gpkg Arrow_Dir")
    lane_dir_field = _resolve_lane_field(lane_fields, ["Lane_Dir"], "--lane-gpkg Lane_Dir")
    road_id_field = resolve_field_name(swroad_result.features, ["id", "linkid", "LinkID"], "swroad input")
    road_direction_field = resolve_field_name(swroad_result.features, ["direction", "Direction"], "swroad input")
    road_index = _index_roads(swroad_result.features, road_id_field=road_id_field)

    lane_groups: dict[str, list[LaneRecord]] = defaultdict(list)
    missing_link_count = 0
    invalid_link_id_count = 0
    for record in lane_records:
        link_id = _normalize_id(record.properties.get(link_field))
        if link_id is None:
            invalid_link_id_count += 1
            continue
        if link_id not in road_index.roads_by_id:
            missing_link_count += 1
            continue
        lane_groups[link_id].append(record)

    output_features: list[dict[str, Any]] = []
    invalid_lane_dir_count = 0
    invalid_road_direction_count = 0
    invalid_geometry_count = 0
    empty_arrow_value_count = 0
    sequence_gap_group_count = 0
    multipart_geometry_count = 0
    for link_id, group_records in sorted(lane_groups.items(), key=lambda item: _group_sort_key(item[1])):
        sorted_records = sorted(group_records, key=lambda record: (_sequence_sort_value(record.properties.get(seq_field)), record.row_index))
        sequence_values = [_parse_int(record.properties.get(seq_field)) for record in sorted_records]
        valid_sequence_values = [value for value in sequence_values if value is not None]
        if valid_sequence_values and valid_sequence_values != list(range(1, len(valid_sequence_values) + 1)):
            sequence_gap_group_count += 1
        lane_index = 0
        road = road_index.roads_by_id[link_id]
        road_direction = _parse_int(road.properties.get(road_direction_field))
        if road_direction not in {0, 1, 2, 3}:
            invalid_road_direction_count += len(sorted_records)
            continue
        for record in sorted_records:
            lane_dir = _parse_int(record.properties.get(lane_dir_field))
            if lane_dir not in {2, 3}:
                invalid_lane_dir_count += 1
                continue
            arrow_values = _split_arrow_values(record.properties.get(arrow_field))
            if not arrow_values:
                empty_arrow_value_count += 1
                continue
            try:
                coords, was_multipart = _line_coords(road.geometry)
                if was_multipart:
                    multipart_geometry_count += 1
                oriented_coords = _orient_coords(coords, road_direction=road_direction, lane_dir=lane_dir)
            except ValueError:
                invalid_geometry_count += 1
                continue
            for arrow_value in arrow_values:
                lane_index += 1
                output_features.append(
                    {
                        "properties": {
                            "linkid": link_id,
                            "lane_index": lane_index,
                            "arrow": arrow_value,
                            "seq_nm": _parse_int(record.properties.get(seq_field)),
                            "lane_dir": lane_dir,
                            "source_arrow_dir": _normalize_text(record.properties.get(arrow_field)),
                        },
                        "geometry": LineString(oriented_coords),
                    }
                )
                if _should_emit_progress(len(output_features), progress_interval):
                    _emit_progress(progress_callback, f"[T08 Tool8] built {len(output_features)} arrow feature(s)")

    write_started = time.perf_counter()
    write_stats = write_gpkg(
        output_path,
        output_features,
        crs_text=f"EPSG:{target_epsg}",
        empty_fields=("linkid", "lane_index", "arrow", "seq_nm", "lane_dir", "source_arrow_dir"),
        geometry_type="LineString",
    )
    write_seconds = _elapsed_since(write_started)
    elapsed_seconds = _elapsed_since(started)

    summary = {
        "tool": "T08 Tool8",
        "stage": "lane_arrow",
        "target_epsg": target_epsg,
        "input_paths": {
            "lane_gpkg": lane_path,
            "swnode_gpkg": swnode_path,
            "swroad_gpkg": swroad_path,
        },
        "output_paths": {
            "arrow_output": output_path,
            "summary_output": summary_path,
        },
        "input_crs": {
            "lane": None,
            "lane_crs_source": "non_spatial_table_or_not_used",
            "swnode": swnode_audit.source_crs.to_string() if swnode_audit.source_crs else None,
            "swnode_crs_source": swnode_audit.crs_source,
            "swroad": swroad_result.source_crs.to_string(),
            "swroad_crs_source": swroad_result.crs_source,
        },
        "params": {
            "lane_layer": lane_layer,
            "swnode_layer": swnode_layer,
            "swroad_layer": swroad_layer,
            "swnode_default_crs": swnode_default_crs_text,
            "swroad_default_crs": swroad_default_crs_text,
            "progress_interval": progress_interval,
        },
        "field_audit": {
            "lane_table": lane_table,
            "lane_fields": list(lane_fields),
            "link_field": link_field,
            "seq_field": seq_field,
            "arrow_field": arrow_field,
            "lane_dir_field": lane_dir_field,
            "swroad_id_field": road_id_field,
            "swroad_direction_field": road_direction_field,
        },
        "counts": {
            "lane_record_count": len(lane_records),
            "lane_record_with_matching_link_count": sum(len(records) for records in lane_groups.values()),
            "lane_link_group_count": len(lane_groups),
            "swnode_feature_count": swnode_audit.feature_count,
            "swroad_feature_count": len(swroad_result.features),
            "swroad_id_count": len(road_index.roads_by_id),
            "duplicate_swroad_id_count": road_index.duplicate_id_count,
            "missing_link_count": missing_link_count,
            "invalid_link_id_count": invalid_link_id_count,
            "invalid_lane_dir_count": invalid_lane_dir_count,
            "invalid_road_direction_count": invalid_road_direction_count,
            "invalid_geometry_count": invalid_geometry_count,
            "empty_arrow_value_count": empty_arrow_value_count,
            "sequence_gap_group_count": sequence_gap_group_count,
            "multipart_geometry_count": multipart_geometry_count,
            "arrow_feature_count": len(output_features),
        },
        "output_bounds": aggregate_bounds(feature["geometry"] for feature in output_features),
        "write_stats": write_stats,
        "performance": {
            "elapsed_seconds": round(elapsed_seconds, 6),
            "read_inputs_seconds": round(read_seconds, 6),
            "write_output_seconds": round(write_seconds, 6),
            "lane_records_per_second": _items_per_second(len(lane_records), elapsed_seconds),
        },
    }
    write_json(summary_path, summary)
    _emit_progress(
        progress_callback,
        f"[T08 Tool8] finished arrows={len(output_features)} elapsed={elapsed_seconds:.2f}s summary={summary_path}",
    )
    return T08LaneArrowArtifacts(arrow_output=output_path, summary_output=summary_path)


def _read_lane_records(path: Path, *, layer_name: str | None) -> tuple[list[LaneRecord], tuple[str, ...], str]:
    with sqlite3.connect(path) as conn:
        table_name = _resolve_table_name(conn, path=path, layer_name=layer_name)
        geometry_columns = _geometry_columns(conn, table_name=table_name)
        columns = _table_columns(conn, table_name=table_name, geometry_columns=geometry_columns)
        rows = conn.execute(
            f"SELECT {', '.join(_quote_identifier(column) for column in columns)} FROM {_quote_identifier(table_name)}"
        )
        records = [
            LaneRecord(
                row_index=index,
                properties={column: row[column_index] for column_index, column in enumerate(columns)},
            )
            for index, row in enumerate(rows, start=1)
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


def _resolve_lane_field(field_names: tuple[str, ...], candidates: list[str], label: str) -> str:
    resolved = resolve_case_insensitive_field_name({field_name: None for field_name in field_names}, candidates)
    if resolved is not None:
        return resolved
    raise ValueError(f"Required field {candidates} not found in {label}")


def _index_roads(features: list[VectorFeature], *, road_id_field: str) -> RoadIndex:
    indexed: dict[str, VectorFeature] = {}
    duplicate_count = 0
    for feature in features:
        road_id = _normalize_id(feature.properties.get(road_id_field))
        if road_id is None:
            continue
        if road_id in indexed:
            duplicate_count += 1
            continue
        indexed[road_id] = feature
    return RoadIndex(roads_by_id=indexed, duplicate_id_count=duplicate_count)


def _line_coords(geometry: BaseGeometry) -> tuple[list[tuple[float, float]], bool]:
    if isinstance(geometry, LineString):
        coords = [(float(x), float(y)) for x, y, *_rest in geometry.coords]
        if len(coords) < 2:
            raise ValueError("Road geometry must contain at least two coordinates")
        return coords, False
    if isinstance(geometry, MultiLineString):
        parts = [part for part in geometry.geoms if not part.is_empty]
        if not parts:
            raise ValueError("Road geometry is empty")
        longest = max(parts, key=lambda part: float(part.length))
        coords = [(float(x), float(y)) for x, y, *_rest in longest.coords]
        if len(coords) < 2:
            raise ValueError("Road geometry must contain at least two coordinates")
        return coords, True
    if hasattr(geometry, "geoms"):
        lines = [part for part in geometry.geoms if isinstance(part, LineString) and not part.is_empty]
        if lines:
            longest = max(lines, key=lambda part: float(part.length))
            coords = [(float(x), float(y)) for x, y, *_rest in longest.coords]
            if len(coords) < 2:
                raise ValueError("Road geometry must contain at least two coordinates")
            return coords, True
    raise ValueError(f"Unsupported road geometry type: {geometry.geom_type}")


def _orient_coords(
    coords: list[tuple[float, float]],
    *,
    road_direction: int,
    lane_dir: int,
) -> list[tuple[float, float]]:
    if road_direction in {0, 1, 2}:
        reverse = lane_dir == 3
    elif road_direction == 3:
        reverse = lane_dir == 2
    else:
        raise ValueError(f"Unsupported road direction: {road_direction}")
    return list(reversed(coords)) if reverse else list(coords)


def _split_arrow_values(value: Any) -> list[str]:
    text = _normalize_text(value)
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


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


def _normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            number = float(text)
        except ValueError:
            return None
        if number.is_integer():
            return int(number)
    return None


def _sequence_sort_value(value: Any) -> tuple[int, int]:
    parsed = _parse_int(value)
    if parsed is None:
        return (1, 0)
    return (0, parsed)


def _group_sort_key(records: list[LaneRecord]) -> int:
    return min((record.row_index for record in records), default=0)


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
    raise ValueError(f"GPKG has multiple user tables {user_tables}; --lane-layer is required")


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
        raise ValueError(f"Lane table '{table_name}' contains no business fields")
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


__all__ = [
    "T08LaneArrowArtifacts",
    "run_t08_lane_arrow",
]
