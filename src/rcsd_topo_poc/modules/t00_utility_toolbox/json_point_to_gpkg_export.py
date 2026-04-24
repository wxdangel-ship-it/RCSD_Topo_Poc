from __future__ import annotations

import json
import math
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from pyproj import CRS
from shapely import Point, to_wkb
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    announce,
    build_logger,
    build_run_id,
    close_logger,
    minimal_geometry_repair,
    normalize_runtime_path,
    remove_existing_output,
    write_json,
)


RUN_ID_PREFIX = "t00_tool10_json_point_export"
PROGRESS_INTERVAL = 50000
INPUT_SOURCE_CRS = CRS.from_epsg(4326)
GPKG_APPLICATION_ID = 0x47504B47
GPKG_USER_VERSION = 10300
GEOMETRY_COLUMN_NAME = "geom"
FID_COLUMN_NAME = "fid"
ALL_LAYER_NAME = "pickup_spots_all"
RECOMMENDED_LAYER_NAME = "pickup_spots_recommended"

FIELD_NAMES = [
    "source_crs",
    "spot_id",
    "name",
    "distance",
    "walk_distance",
    "is_recommend",
    "type",
    "link_id",
    "link_coors",
    "location",
    "origin_id",
    "is_nparking",
    "req_tid",
    "req_gd_id",
    "req_lon",
    "req_lat",
    "req_success",
    "req_db",
    "req_table_name",
    "cen_id",
    "cen_name",
    "cen_lon",
    "cen_lat",
    "cen_type",
    "adcode",
    "city_adcode",
    "province_adcode",
    "district_adcode",
    "selected_show_id",
    "card_style",
    "card_title",
    "had_recommend",
    "had_spot_image",
    "crawl_time",
]

FIELD_TYPES = {
    "source_crs": "TEXT",
    "spot_id": "TEXT",
    "name": "TEXT",
    "distance": "REAL",
    "walk_distance": "REAL",
    "is_recommend": "INTEGER",
    "type": "TEXT",
    "link_id": "TEXT",
    "link_coors": "TEXT",
    "location": "TEXT",
    "origin_id": "TEXT",
    "is_nparking": "INTEGER",
    "req_tid": "TEXT",
    "req_gd_id": "TEXT",
    "req_lon": "REAL",
    "req_lat": "REAL",
    "req_success": "INTEGER",
    "req_db": "TEXT",
    "req_table_name": "TEXT",
    "cen_id": "TEXT",
    "cen_name": "TEXT",
    "cen_lon": "REAL",
    "cen_lat": "REAL",
    "cen_type": "TEXT",
    "adcode": "TEXT",
    "city_adcode": "TEXT",
    "province_adcode": "TEXT",
    "district_adcode": "TEXT",
    "selected_show_id": "TEXT",
    "card_style": "TEXT",
    "card_title": "TEXT",
    "had_recommend": "INTEGER",
    "had_spot_image": "INTEGER",
    "crawl_time": "TEXT",
}


@dataclass(frozen=True)
class JsonPointToGpkgConfig:
    input_path: Path
    output_path: Path | None = None
    output_epsg: int = 4326
    max_output_features: int | None = None
    progress_interval: int = PROGRESS_INTERVAL
    run_id: str | None = None


@dataclass
class _LayerState:
    feature_count: int = 0
    bounds: tuple[float, float, float, float] | None = None


def _skip_whitespace(text: str, start: int = 0) -> int:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    return index


def _detect_input_format(path: Path) -> str:
    with path.open("r", encoding="utf-8") as fp:
        while True:
            chunk = fp.read(4096)
            if chunk == "":
                raise ValueError(f"input json file is empty: {path}")
            index = _skip_whitespace(chunk)
            if index >= len(chunk):
                continue
            first = chunk[index]
            if first == "[":
                return "json-array"
            if first == "{":
                return "ndjson"
            raise ValueError(f"unsupported json layout, first non-whitespace character is {first!r}")


def _iter_ndjson_records(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fp:
        for line_number, line in enumerate(fp, start=1):
            text = line.strip()
            if not text:
                continue
            if text.endswith(","):
                text = text[:-1].rstrip()
            payload = json.loads(text)
            if not isinstance(payload, dict):
                raise ValueError(f"NDJSON record at line {line_number} is not a JSON object")
            yield payload


def _iter_json_array_records(path: Path, *, chunk_size: int = 1024 * 1024) -> Iterator[dict[str, Any]]:
    decoder = json.JSONDecoder()
    with path.open("r", encoding="utf-8") as fp:
        buffer = ""
        position = 0
        started = False
        expecting_value = True

        while True:
            if position >= len(buffer):
                buffer = ""
                position = 0

            if position == len(buffer):
                chunk = fp.read(chunk_size)
                if chunk == "":
                    if not started:
                        raise ValueError("json array file ended before '['")
                    break
                buffer += chunk

            position = _skip_whitespace(buffer, position)
            if position >= len(buffer):
                continue

            if not started:
                if buffer[position] != "[":
                    raise ValueError("json array input must start with '['")
                started = True
                position += 1
                continue

            position = _skip_whitespace(buffer, position)
            if position >= len(buffer):
                continue

            current = buffer[position]
            if expecting_value and current == "]":
                return
            if not expecting_value and current == ",":
                expecting_value = True
                position += 1
                continue
            if not expecting_value and current == "]":
                return
            if not expecting_value:
                raise ValueError(f"unexpected token {current!r} while parsing json array")

            try:
                payload, end_position = decoder.raw_decode(buffer, position)
            except json.JSONDecodeError:
                chunk = fp.read(chunk_size)
                if chunk == "":
                    raise ValueError("unexpected EOF while parsing json array")
                buffer = buffer[position:] + chunk
                position = 0
                continue

            if not isinstance(payload, dict):
                raise ValueError("json array items must be JSON objects")

            yield payload
            position = end_position
            expecting_value = False


def _iter_records(path: Path, input_format: str) -> Iterator[dict[str, Any]]:
    if input_format == "ndjson":
        yield from _iter_ndjson_records(path)
        return
    if input_format == "json-array":
        yield from _iter_json_array_records(path)
        return
    raise ValueError(f"unsupported input_format: {input_format}")


def _scalar(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return None


def _as_bool_flag(value: Any) -> int | None:
    scalar_value = _scalar(value)
    if scalar_value is None:
        return None
    if isinstance(scalar_value, bool):
        return 1 if scalar_value else 0
    if isinstance(scalar_value, (int, float)):
        return 0 if scalar_value == 0 else 1
    normalized = scalar_value.strip().lower()
    if normalized in {"", "0", "false", "no", "n"}:
        return 0
    if normalized in {"1", "true", "yes", "y"}:
        return 1
    return 1


def _normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float, str, bytes)):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _nested_get(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = payload
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _extract_spot_lon_lat(spot: dict[str, Any]) -> tuple[float, float]:
    lon_value = spot.get("lon")
    lat_value = spot.get("lat")
    if lon_value is None or lat_value is None:
        raise ValueError("spot lon/lat not found")

    lon = float(str(lon_value))
    lat = float(str(lat_value))
    if not math.isfinite(lon) or not math.isfinite(lat):
        raise ValueError("spot lon/lat is not finite")
    if lon < -180.0 or lon > 180.0 or lat < -90.0 or lat > 90.0:
        raise ValueError("spot lon/lat outside EPSG:4326 range")
    return lon, lat


def _is_recommended_spot(spot: dict[str, Any]) -> bool:
    return _as_bool_flag(spot.get("isRecommend")) == 1


def _build_feature_properties(payload: dict[str, Any], spot: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    center = data.get("location") if isinstance(data.get("location"), dict) else {}
    card = data.get("card") if isinstance(data.get("card"), dict) else {}
    other_args = payload.get("other_args") if isinstance(payload.get("other_args"), dict) else {}

    return {
        "source_crs": "raw_lonlat_unconfirmed",
        "spot_id": _scalar(spot.get("id")) or _scalar(spot.get("spotId")),
        "name": _scalar(spot.get("name")),
        "distance": _scalar(spot.get("distance")),
        "walk_distance": _scalar(spot.get("walkDistance")),
        "is_recommend": _as_bool_flag(spot.get("isRecommend")),
        "type": _scalar(spot.get("type")),
        "link_id": _scalar(spot.get("linkId")),
        "link_coors": _scalar(spot.get("linkCoors")),
        "location": _scalar(spot.get("location")),
        "origin_id": _scalar(spot.get("originId")),
        "is_nparking": _as_bool_flag(spot.get("isNparking")),
        "req_tid": _scalar(payload.get("tid")),
        "req_gd_id": _scalar(payload.get("gd_id")),
        "req_lon": _scalar(payload.get("lon")),
        "req_lat": _scalar(payload.get("lat")),
        "req_success": _as_bool_flag(payload.get("success")),
        "req_db": _scalar(other_args.get("db")),
        "req_table_name": _scalar(other_args.get("table_name")),
        "cen_id": _scalar(center.get("id")) or _scalar(center.get("spotId")),
        "cen_name": _scalar(center.get("name")),
        "cen_lon": _scalar(center.get("lon")),
        "cen_lat": _scalar(center.get("lat")),
        "cen_type": _scalar(center.get("type")),
        "adcode": _scalar(center.get("adcode")),
        "city_adcode": _scalar(center.get("cityAdcode")),
        "province_adcode": _scalar(center.get("provinceAdcode")),
        "district_adcode": _scalar(center.get("districtAdcode")),
        "selected_show_id": _scalar(card.get("selectedShowId")),
        "card_style": _scalar(card.get("cardStyle")),
        "card_title": _scalar(card.get("title")),
        "had_recommend": _as_bool_flag(data.get("hadRecommend")),
        "had_spot_image": _as_bool_flag(data.get("hadSpotImage")),
        "crawl_time": _scalar(payload.get("crawl_time")),
    }


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


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
                INPUT_SOURCE_CRS.name,
                4326,
                "EPSG",
                4326,
                INPUT_SOURCE_CRS.to_wkt(),
                "longitude/latitude coordinates in decimal degrees on the WGS 84 spheroid",
            ),
        ],
    )


def _build_gpkg_geometry_blob(geometry: BaseGeometry, srs_id: int) -> bytes:
    wkb = to_wkb(geometry, hex=False, byte_order=1)
    flags = 1
    return b"GP" + bytes((0, flags)) + int(srs_id).to_bytes(4, "little", signed=True) + wkb


def _merge_bounds(
    current: tuple[float, float, float, float] | None,
    geometry: BaseGeometry,
) -> tuple[float, float, float, float]:
    min_x, min_y, max_x, max_y = (float(value) for value in geometry.bounds)
    if current is None:
        return min_x, min_y, max_x, max_y
    return (
        min(current[0], min_x),
        min(current[1], min_y),
        max(current[2], max_x),
        max(current[3], max_y),
    )


class _PointGpkgWriter:
    def __init__(self, output_path: Path, target_crs: CRS, layer_names: tuple[str, ...]) -> None:
        self.output_path = output_path
        self.target_crs = target_crs
        self.layer_names = layer_names
        self.conn: sqlite3.Connection | None = None
        self.srs_id: int | None = None
        self.layer_states = {layer_name: _LayerState() for layer_name in layer_names}

    def open(self) -> None:
        remove_existing_output(self.output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.output_path)
        _initialize_gpkg_metadata(self.conn)
        srs_id, organization, organization_coordsys_id, definition, srs_name = _srs_record(self.target_crs)
        self.srs_id = srs_id
        self.conn.execute(
            """
            INSERT OR REPLACE INTO gpkg_spatial_ref_sys (
                srs_name, srs_id, organization, organization_coordsys_id, definition, description
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (srs_name, srs_id, organization, organization_coordsys_id, definition, srs_name),
        )
        for layer_name in self.layer_names:
            self._create_layer(layer_name)

    def _create_layer(self, layer_name: str) -> None:
        assert self.conn is not None
        assert self.srs_id is not None
        column_defs = [f"{_quote_identifier(FID_COLUMN_NAME)} INTEGER PRIMARY KEY AUTOINCREMENT"]
        for field_name in FIELD_NAMES:
            column_defs.append(f"{_quote_identifier(field_name)} {FIELD_TYPES[field_name]}")
        column_defs.append(f"{_quote_identifier(GEOMETRY_COLUMN_NAME)} BLOB NOT NULL")
        self.conn.execute(f"CREATE TABLE {_quote_identifier(layer_name)} ({', '.join(column_defs)})")

        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        self.conn.execute(
            """
            INSERT INTO gpkg_contents (
                table_name, data_type, identifier, description, last_change,
                min_x, min_y, max_x, max_y, srs_id
            ) VALUES (?, 'features', ?, '', ?, NULL, NULL, NULL, NULL, ?)
            """,
            (layer_name, layer_name, now_iso, self.srs_id),
        )
        self.conn.execute(
            """
            INSERT INTO gpkg_geometry_columns (
                table_name, column_name, geometry_type_name, srs_id, z, m
            ) VALUES (?, ?, 'POINT', ?, 0, 0)
            """,
            (layer_name, GEOMETRY_COLUMN_NAME, self.srs_id),
        )

    def write_feature(self, layer_name: str, properties: dict[str, Any], geometry: BaseGeometry) -> None:
        assert self.conn is not None
        assert self.srs_id is not None
        insert_columns = list(FIELD_NAMES) + [GEOMETRY_COLUMN_NAME]
        placeholders = ", ".join("?" for _ in insert_columns)
        insert_sql = (
            f"INSERT INTO {_quote_identifier(layer_name)} "
            f"({', '.join(_quote_identifier(name) for name in insert_columns)}) VALUES ({placeholders})"
        )
        row_values = [_normalize_value(properties.get(field_name)) for field_name in FIELD_NAMES]
        row_values.append(_build_gpkg_geometry_blob(geometry, self.srs_id))
        self.conn.execute(insert_sql, row_values)

        state = self.layer_states[layer_name]
        state.feature_count += 1
        state.bounds = _merge_bounds(state.bounds, geometry)

    def finalize(self) -> dict[str, int]:
        assert self.conn is not None
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        for layer_name, state in self.layer_states.items():
            bounds = state.bounds
            self.conn.execute(
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
                    layer_name,
                ),
            )
        self.conn.commit()
        counts = {layer_name: state.feature_count for layer_name, state in self.layer_states.items()}
        self.conn.close()
        self.conn = None
        return counts

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None


def _should_report_progress(index: int, interval: int) -> bool:
    return index == 1 or index % interval == 0


def _default_output_path(input_path: Path) -> Path:
    return input_path.with_suffix(".gpkg")


def run_json_point_to_gpkg_export(config: JsonPointToGpkgConfig) -> dict[str, Any]:
    input_path = normalize_runtime_path(config.input_path).expanduser().resolve()
    output_path = (
        normalize_runtime_path(config.output_path).expanduser().resolve()
        if config.output_path is not None
        else _default_output_path(input_path)
    )
    output_dir = output_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = config.run_id or build_run_id(RUN_ID_PREFIX)
    log_path = output_dir / f"{run_id}.log"
    summary_path = output_dir / f"{run_id}_summary.json"
    logger = build_logger(log_path, run_id)
    output_crs = CRS.from_epsg(config.output_epsg)
    writer: _PointGpkgWriter | None = None

    summary: dict[str, Any] = {
        "run_id": run_id,
        "tool": "Tool10",
        "status": "started",
        "input_path": str(input_path),
        "output_path": str(output_path),
        "log_path": str(log_path),
        "summary_path": str(summary_path),
        "input_size_bytes": input_path.stat().st_size if input_path.exists() else None,
        "input_format": None,
        "input_record_count": 0,
        "spot_candidate_count": 0,
        "records_without_spots_count": 0,
        "output_feature_count": 0,
        "all_spot_output_count": 0,
        "recommended_spot_output_count": 0,
        "failed_spot_count": 0,
        "repaired_feature_count": 0,
        "source_crs": INPUT_SOURCE_CRS.to_string(),
        "output_crs": output_crs.to_string(),
        "no_crs_transform": True,
        "max_output_features": config.max_output_features,
        "stopped_by_export_limit": False,
        "layer_names": {
            "all": ALL_LAYER_NAME,
            "recommended": RECOMMENDED_LAYER_NAME,
        },
        "field_names": FIELD_NAMES,
        "field_name_mapping": {field_name: field_name for field_name in FIELD_NAMES},
        "coordinate_source_summary": {},
        "error_reason_summary": {},
        "blocking_reason": None,
        "notes": [
            "Tool10 writes one all-pickup output feature per data.spots candidate point.",
            "Recommended pickup points are duplicated into pickup_spots_recommended when isRecommend is truthy.",
            "Geometry is built only from spot lon/lat without CRS transformation.",
        ],
    }

    try:
        announce(logger, f"Tool10 json pickup point export started. input_path={input_path}")
        if not input_path.is_file():
            summary["status"] = "blocked"
            summary["blocking_reason"] = f"input json file does not exist: {input_path}"
            announce(logger, f"Tool10 blocked. reason={summary['blocking_reason']}")
            write_json(summary_path, summary)
            return summary

        announce(logger, "[Stage 1/4] Detect input format and prepare two GPKG layers.")
        input_format = _detect_input_format(input_path)
        summary["input_format"] = input_format
        writer = _PointGpkgWriter(
            output_path,
            output_crs,
            layer_names=(ALL_LAYER_NAME, RECOMMENDED_LAYER_NAME),
        )
        writer.open()

        error_reason_counter = Counter()
        coordinate_source_counter = Counter()
        input_record_count = 0
        spot_candidate_count = 0
        records_without_spots_count = 0
        all_spot_output_count = 0
        recommended_spot_output_count = 0
        failed_spot_count = 0
        repaired_feature_count = 0

        announce(
            logger,
            "[Stage 2/4] Stream records, expand data.spots, and write all/recommended pickup layers. "
            f"output_crs={output_crs.to_string()} input_format={input_format}",
        )
        stop_due_to_limit = False
        for record_index, payload in enumerate(_iter_records(input_path, input_format), start=1):
            input_record_count = record_index
            data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
            raw_spots = data.get("spots")
            if not isinstance(raw_spots, list) or len(raw_spots) == 0:
                records_without_spots_count += 1
                if _should_report_progress(record_index, config.progress_interval):
                    announce(
                        logger,
                        f"[Record {record_index}] all_spot_output_count={all_spot_output_count} "
                        f"recommended_spot_output_count={recommended_spot_output_count} "
                        f"failed_spot_count={failed_spot_count}",
                    )
                continue

            spot_candidate_count += sum(1 for spot in raw_spots if isinstance(spot, dict))
            for spot in raw_spots:
                if not isinstance(spot, dict):
                    continue
                try:
                    lon, lat = _extract_spot_lon_lat(spot)
                    coordinate_source_counter["data.spots.lon/lat"] += 1
                    geometry = Point(lon, lat)
                    if geometry.is_empty:
                        raise ValueError("geometry is empty")
                    if not geometry.is_valid:
                        repaired_geometry = minimal_geometry_repair(geometry)
                        if repaired_geometry is None:
                            raise ValueError("minimal repair failed")
                        geometry = repaired_geometry
                        repaired_feature_count += 1

                    properties = _build_feature_properties(payload, spot)
                    writer.write_feature(ALL_LAYER_NAME, properties, geometry)
                    all_spot_output_count += 1

                    if _is_recommended_spot(spot):
                        writer.write_feature(RECOMMENDED_LAYER_NAME, properties, geometry)
                        recommended_spot_output_count += 1

                    if (
                        config.max_output_features is not None
                        and all_spot_output_count >= config.max_output_features
                    ):
                        summary["stopped_by_export_limit"] = True
                        stop_due_to_limit = True
                        announce(
                            logger,
                            f"[Record {record_index}] reached export limit "
                            f"max_output_features={config.max_output_features}; stop streaming",
                        )
                        break
                except Exception as exc:
                    failed_spot_count += 1
                    error_reason_counter[str(exc)] += 1

            if stop_due_to_limit:
                break
            if _should_report_progress(record_index, config.progress_interval):
                announce(
                    logger,
                    f"[Record {record_index}] all_spot_output_count={all_spot_output_count} "
                    f"recommended_spot_output_count={recommended_spot_output_count} "
                    f"failed_spot_count={failed_spot_count}",
                )

        announce(logger, "[Stage 3/4] Finalize GPKG metadata and flush output.")
        layer_counts = writer.finalize()
        writer = None

        announce(logger, "[Stage 4/4] Write summary and finish Tool10.")
        summary["status"] = "completed"
        summary["input_record_count"] = input_record_count
        summary["spot_candidate_count"] = spot_candidate_count
        summary["records_without_spots_count"] = records_without_spots_count
        summary["output_feature_count"] = all_spot_output_count
        summary["all_spot_output_count"] = all_spot_output_count
        summary["recommended_spot_output_count"] = recommended_spot_output_count
        summary["failed_spot_count"] = failed_spot_count
        summary["repaired_feature_count"] = repaired_feature_count
        summary["layer_feature_counts"] = layer_counts
        summary["coordinate_source_summary"] = dict(coordinate_source_counter)
        summary["error_reason_summary"] = dict(error_reason_counter)
        write_json(summary_path, summary)
        announce(
            logger,
            "Tool10 json pickup point export finished. "
            f"input_record_count={input_record_count} all_spot_output_count={all_spot_output_count} "
            f"recommended_spot_output_count={recommended_spot_output_count} failed_spot_count={failed_spot_count}",
        )
        return summary
    except Exception as exc:
        summary["status"] = "failed"
        summary["blocking_reason"] = str(exc)
        write_json(summary_path, summary)
        raise
    finally:
        if writer is not None:
            writer.close()
        close_logger(logger)
