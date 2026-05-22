from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import fiona
from fiona.model import to_dict as fiona_to_dict
from fiona.transform import transform_geom
from pyproj import CRS, Transformer
from shapely import from_wkb, to_wkb
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform


PROCESS_CRS_TEXT = "EPSG:3857"
GPKG_SUFFIX = ".gpkg"
GEOJSON_SUFFIXES = frozenset({".geojson", ".json"})
GPKG_APPLICATION_ID = 0x47504B47
GPKG_USER_VERSION = 10300
GPKG_FID_COLUMN = "fid"
GPKG_GEOMETRY_COLUMN = "geom"
GPKG_BATCH_SIZE = 1000
STANDARD_WGS84_CRS = CRS.from_epsg(4326)


@dataclass(frozen=True)
class VectorFeature:
    properties: dict[str, Any]
    geometry: BaseGeometry


@dataclass(frozen=True)
class VectorReadResult:
    path: Path
    features: list[VectorFeature]
    source_crs: CRS
    output_crs: CRS
    crs_source: str
    field_names: tuple[str, ...]
    layer_name: str | None


def ensure_gpkg_path(path: str | Path, *, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved.suffix.lower() != GPKG_SUFFIX:
        raise ValueError(f"{label} must be a .gpkg path: {resolved}")
    return resolved


def ensure_shp_path(path: str | Path, *, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved.suffix.lower() != ".shp":
        raise ValueError(f"{label} must be a .shp path: {resolved}")
    return resolved


def ensure_geojson_path(path: str | Path, *, label: str) -> Path:
    resolved = Path(path).expanduser().resolve()
    if resolved.suffix.lower() not in GEOJSON_SUFFIXES:
        raise ValueError(f"{label} must be a .geojson or .json path: {resolved}")
    return resolved


def read_vector(
    path: str | Path,
    *,
    layer_name: str | None = None,
    default_crs_text: str | None = None,
    target_epsg: int | None = 3857,
) -> VectorReadResult:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise ValueError(f"Vector input does not exist: {resolved}")

    if resolved.suffix.lower() == GPKG_SUFFIX:
        fast_result = _try_read_gpkg_sqlite(
            resolved,
            layer_name=layer_name,
            default_crs_text=default_crs_text,
            target_epsg=target_epsg,
        )
        if fast_result is not None:
            return fast_result

    with fiona.open(str(resolved), layer=layer_name) as source:
        source_crs, crs_source = resolve_source_crs(
            path=resolved,
            default_crs_text=default_crs_text,
            crs_wkt=getattr(source, "crs_wkt", None),
            crs_mapping=getattr(source, "crs", None),
        )
        output_crs = CRS.from_epsg(target_epsg) if target_epsg is not None else source_crs
        field_names = tuple(str(key) for key in (source.schema.get("properties") or {}).keys())
        resolved_layer_name = getattr(source, "name", None) or layer_name
        features: list[VectorFeature] = []
        for index, feature in enumerate(source, start=1):
            geometry_payload = feature.get("geometry")
            if geometry_payload is None:
                raise ValueError(f"Feature {index} in {resolved} has no geometry")
            geometry = shape(geometry_payload)
            if geometry.is_empty:
                raise ValueError(f"Feature {index} in {resolved} has empty geometry")
            geometry = _transform_geometry(geometry, source_crs, output_crs)
            features.append(VectorFeature(properties=dict(feature.get("properties") or {}), geometry=geometry))

    return VectorReadResult(
        path=resolved,
        features=features,
        source_crs=source_crs,
        output_crs=output_crs,
        crs_source=crs_source,
        field_names=field_names,
        layer_name=resolved_layer_name,
    )


def write_gpkg(
    path: str | Path,
    features: Iterable[dict[str, Any]],
    *,
    crs_text: str,
    layer_name: str | None = None,
    empty_fields: Iterable[str] = (),
    geometry_type: str = "Unknown",
) -> dict[str, Any]:
    output_path = ensure_gpkg_path(path, label="GPKG output")
    feature_list = list(features)
    records = [_prepare_record(feature) for feature in feature_list]
    schema = _build_schema(records, empty_fields=empty_fields, geometry_type=geometry_type)
    return _write_gpkg_records_sqlite(
        output_path,
        records=records,
        crs=CRS.from_user_input(crs_text),
        layer_name=layer_name or output_path.stem,
        schema=schema,
    )


def write_geojson(
    path: str | Path,
    features: Iterable[dict[str, Any]],
    *,
    crs_text: str,
    empty_fields: Iterable[str] = (),
    geometry_type: str = "Unknown",
) -> dict[str, Any]:
    output_path = ensure_geojson_path(path, label="GeoJSON output")
    feature_list = list(features)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    records = [_prepare_record(feature) for feature in feature_list]
    property_names = list(_build_schema(records, empty_fields=empty_fields, geometry_type=geometry_type)["properties"].keys())
    with output_path.open("w", encoding="utf-8") as fp:
        fp.write('{"type":"FeatureCollection","name":')
        json.dump(output_path.stem, fp, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        fp.write(',"crs":{"type":"name","properties":{"name":')
        json.dump(crs_text, fp, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        fp.write('}},"features":[')
        first = True
        for record in records:
            if not first:
                fp.write(",")
            json.dump(
                {
                    "type": "Feature",
                    "properties": {
                        name: _get_property_case_insensitive(record["properties"], name)
                        for name in property_names
                    },
                    "geometry": _geometry_payload(record["geometry"]),
                },
                fp,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            first = False
        fp.write("]}")

    return {"feature_count": len(records), "size_bytes": output_path.stat().st_size if output_path.exists() else 0}


def write_gpkg_from_fiona_collection(
    path: str | Path,
    source: Any,
    *,
    source_crs: CRS,
    output_crs: CRS,
    layer_name: str,
    progress_callback: Any = None,
    progress_interval: int = 10000,
) -> dict[str, Any]:
    output_path = ensure_gpkg_path(path, label="GPKG output")
    schema = {
        "geometry": (source.schema or {}).get("geometry") or "Unknown",
        "properties": dict((source.schema or {}).get("properties") or {}),
    }
    return _write_gpkg_fiona_sqlite(
        output_path,
        source=source,
        source_crs=source_crs,
        output_crs=output_crs,
        layer_name=layer_name,
        schema=schema,
        progress_callback=progress_callback,
        progress_interval=progress_interval,
    )


def write_geojson_from_fiona_collection(
    path: str | Path,
    source: Any,
    *,
    source_crs: CRS,
    output_crs: CRS,
    layer_name: str,
    progress_callback: Any = None,
    progress_interval: int = 10000,
) -> dict[str, Any]:
    output_path = ensure_geojson_path(path, label="GeoJSON output")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    field_names = [str(name) for name in ((source.schema or {}).get("properties") or {}).keys()]
    feature_count = 0
    with output_path.open("w", encoding="utf-8") as fp:
        fp.write('{"type":"FeatureCollection","name":')
        json.dump(layer_name, fp, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        fp.write(',"crs":{"type":"name","properties":{"name":')
        json.dump(output_crs.to_string(), fp, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        fp.write('}},"features":[')
        first = True
        for feature_count, feature in enumerate(source, start=1):
            geometry_payload = feature.get("geometry")
            if geometry_payload is None:
                raise ValueError(f"Feature {feature_count} has no geometry")
            geometry_mapping = _fiona_geometry_payload(geometry_payload)
            if source_crs != output_crs:
                geometry_mapping = transform_geom(source_crs.to_string(), output_crs.to_string(), geometry_mapping)
                geometry_mapping = _plain_geometry_payload(geometry_mapping)
            if not first:
                fp.write(",")
            properties = dict(feature.get("properties") or {})
            json.dump(
                {
                    "type": "Feature",
                    "properties": {
                        field_name: _normalize_geojson_value(properties.get(field_name)) for field_name in field_names
                    },
                    "geometry": geometry_mapping,
                },
                fp,
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
            first = False
            if progress_callback is not None and progress_interval > 0 and feature_count % progress_interval == 0:
                progress_callback(f"[T08 IO] {output_path.name}: wrote {feature_count} GeoJSON feature(s)")
        fp.write("]}")
    return {"feature_count": feature_count, "size_bytes": output_path.stat().st_size if output_path.exists() else 0}


def resolve_field_name(features: list[VectorFeature], candidates: Iterable[str], label: str) -> str:
    for feature in features:
        resolved = resolve_case_insensitive_field_name(feature.properties, candidates)
        if resolved is not None:
            return resolved
    raise ValueError(f"Required field {list(candidates)} not found in {label}")


def resolve_case_insensitive_field_name(properties: dict[str, Any], candidates: Iterable[str]) -> str | None:
    lower_map = {str(key).lower(): str(key) for key in properties.keys()}
    for candidate in candidates:
        resolved = lower_map.get(candidate.lower())
        if resolved is not None:
            return resolved
    return None


def get_case_insensitive_property(
    properties: dict[str, Any],
    candidates: Iterable[str],
    *,
    preferred: str | None = None,
) -> Any:
    if preferred is not None and preferred in properties:
        return properties.get(preferred)
    resolved = resolve_case_insensitive_field_name(properties, candidates)
    if resolved is None:
        return None
    return properties.get(resolved)


def write_json(path: str | Path, payload: Any) -> None:
    output_path = Path(path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(to_plain(payload), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def to_plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): to_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, CRS):
        return value.to_string()
    if isinstance(value, BaseGeometry):
        return mapping(value)
    return value


def aggregate_bounds(geometries: Iterable[BaseGeometry]) -> list[float] | None:
    bounds_values = []
    for geometry in geometries:
        if geometry is None or geometry.is_empty:
            continue
        bounds_values.append([float(value) for value in geometry.bounds])
    if not bounds_values:
        return None
    return [
        min(bounds[0] for bounds in bounds_values),
        min(bounds[1] for bounds in bounds_values),
        max(bounds[2] for bounds in bounds_values),
        max(bounds[3] for bounds in bounds_values),
    ]


def _aggregate_bounds_from_values(bounds_values: Iterable[tuple[float, float, float, float]]) -> list[float] | None:
    values = list(bounds_values)
    if not values:
        return None
    return [
        min(bounds[0] for bounds in values),
        min(bounds[1] for bounds in values),
        max(bounds[2] for bounds in values),
        max(bounds[3] for bounds in values),
    ]


def unique_field_names(*groups: Iterable[str], extra: Iterable[str] = ()) -> list[str]:
    names: list[str] = []
    lower_seen: set[str] = set()
    for group in groups:
        for name in group:
            text = str(name)
            lower = text.lower()
            if lower not in lower_seen:
                lower_seen.add(lower)
                names.append(text)
    for name in extra:
        text = str(name)
        lower = text.lower()
        if lower not in lower_seen:
            lower_seen.add(lower)
            names.append(text)
    return names


def resolve_source_crs(
    *,
    path: Path,
    default_crs_text: str | None,
    crs_wkt: str | None,
    crs_mapping: Any,
) -> tuple[CRS, str]:
    if crs_wkt:
        return CRS.from_wkt(crs_wkt), "layer.crs_wkt"
    if crs_mapping:
        return CRS.from_user_input(crs_mapping), "layer.crs"
    if path.suffix.lower() == ".shp":
        prj_path = path.with_suffix(".prj")
        if prj_path.is_file():
            prj_text = prj_path.read_text(encoding="utf-8", errors="ignore").strip()
            if prj_text:
                return CRS.from_wkt(prj_text), "shapefile.prj"
    if default_crs_text:
        return CRS.from_user_input(default_crs_text), "default"
    raise ValueError(f"CRS not found and no default CRS configured: {path}")


def _try_read_gpkg_sqlite(
    path: Path,
    *,
    layer_name: str | None,
    default_crs_text: str | None,
    target_epsg: int | None,
) -> VectorReadResult | None:
    try:
        with sqlite3.connect(path) as conn:
            table_info = _resolve_gpkg_layer_info(conn, layer_name=layer_name)
            if table_info is None:
                return None
            table_name, geometry_column, srs_id = table_info
            columns = _gpkg_table_columns(conn, table_name=table_name, geometry_column=geometry_column)
            if columns is None:
                return None
            source_crs, crs_source = _resolve_gpkg_crs(
                conn,
                srs_id=srs_id,
                default_crs_text=default_crs_text,
            )
            output_crs = CRS.from_epsg(target_epsg) if target_epsg is not None else source_crs
            select_columns = [*columns, geometry_column]
            rows = conn.execute(
                f"SELECT {', '.join(_quote_identifier(column) for column in select_columns)} "
                f"FROM {_quote_identifier(table_name)}"
            )
            features: list[VectorFeature] = []
            for index, row in enumerate(rows, start=1):
                values = list(row)
                geometry_blob = values[-1]
                if geometry_blob is None:
                    raise ValueError(f"Feature {index} in {path} has no geometry")
                geometry = _geometry_from_gpkg_blob(geometry_blob)
                if geometry.is_empty:
                    raise ValueError(f"Feature {index} in {path} has empty geometry")
                geometry = _transform_geometry(geometry, source_crs, output_crs)
                features.append(
                    VectorFeature(
                        properties={column: values[column_index] for column_index, column in enumerate(columns)},
                        geometry=geometry,
                    )
                )
    except sqlite3.Error:
        return None

    return VectorReadResult(
        path=path,
        features=features,
        source_crs=source_crs,
        output_crs=output_crs,
        crs_source=crs_source,
        field_names=tuple(columns),
        layer_name=table_name,
    )


def _resolve_gpkg_layer_info(conn: sqlite3.Connection, *, layer_name: str | None) -> tuple[str, str, int] | None:
    if layer_name is None:
        row = conn.execute(
            """
            SELECT table_name, column_name, srs_id
            FROM gpkg_geometry_columns
            ORDER BY table_name
            LIMIT 1
            """
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT table_name, column_name, srs_id
            FROM gpkg_geometry_columns
            WHERE lower(table_name) = lower(?)
            LIMIT 1
            """,
            (layer_name,),
        ).fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1]), int(row[2])


def _gpkg_table_columns(
    conn: sqlite3.Connection,
    *,
    table_name: str,
    geometry_column: str,
) -> list[str] | None:
    rows = conn.execute(f"PRAGMA table_info({_quote_identifier(table_name)})").fetchall()
    if not rows:
        return None
    columns: list[str] = []
    geometry_lower = geometry_column.lower()
    for row in rows:
        name = str(row[1])
        is_pk = int(row[5] or 0) > 0
        if name.lower() == geometry_lower:
            continue
        if is_pk and name.lower() in {GPKG_FID_COLUMN, "ogc_fid"}:
            continue
        columns.append(name)
    return columns


def _resolve_gpkg_crs(
    conn: sqlite3.Connection,
    *,
    srs_id: int,
    default_crs_text: str | None,
) -> tuple[CRS, str]:
    row = conn.execute(
        """
        SELECT organization, organization_coordsys_id, definition, srs_name
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
            try:
                return CRS.from_user_input(definition), "gpkg_spatial_ref_sys"
            except Exception:
                pass
    if default_crs_text:
        return CRS.from_user_input(default_crs_text), "default"
    raise ValueError("GPKG CRS not found and no default CRS configured")


def _geometry_from_gpkg_blob(blob: Any) -> BaseGeometry:
    payload = bytes(blob)
    if len(payload) < 8 or payload[:2] != b"GP":
        return from_wkb(payload)
    flags = payload[3]
    envelope_code = (flags >> 1) & 0b111
    envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    offset = 8 + envelope_sizes.get(envelope_code, 0)
    return from_wkb(payload[offset:])


def _resolve_source_crs(
    *,
    path: Path,
    default_crs_text: str | None,
    crs_wkt: str | None,
    crs_mapping: Any,
) -> tuple[CRS, str]:
    return resolve_source_crs(
        path=path,
        default_crs_text=default_crs_text,
        crs_wkt=crs_wkt,
        crs_mapping=crs_mapping,
    )


def _transform_geometry(geometry: BaseGeometry, source_crs: CRS, output_crs: CRS) -> BaseGeometry:
    if source_crs == output_crs:
        return geometry
    transformer = Transformer.from_crs(source_crs, output_crs, always_xy=True)
    return shapely_transform(transformer.transform, geometry)


def _prepare_record(feature: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    lower_seen: set[str] = set()
    for key, value in (feature.get("properties") or {}).items():
        text = str(key)
        lower = text.lower()
        if lower in lower_seen:
            continue
        lower_seen.add(lower)
        properties[text] = _vector_property_value(value)
    return {
        "properties": properties,
        "geometry": feature.get("geometry"),
    }


def _build_schema(records: list[dict[str, Any]], *, empty_fields: Iterable[str], geometry_type: str) -> dict[str, Any]:
    field_order: list[str] = []
    field_types: dict[str, str] = {}
    lower_to_field: dict[str, str] = {}
    for record in records:
        for key, value in record["properties"].items():
            lower = str(key).lower()
            resolved_key = lower_to_field.get(lower)
            if resolved_key is None:
                lower_to_field[lower] = key
                resolved_key = key
                field_order.append(resolved_key)
            if resolved_key not in field_types and value is not None:
                field_types[resolved_key] = _vector_property_type(value)
    for key in empty_fields:
        text = str(key)
        lower = text.lower()
        if lower not in lower_to_field:
            lower_to_field[lower] = text
            field_order.append(text)
    for key in field_order:
        field_types.setdefault(key, "str")
    return {"geometry": geometry_type, "properties": {key: field_types[key] for key in field_order}}


def _vector_property_value(value: Any) -> Any:
    value = to_plain(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _get_property_case_insensitive(properties: dict[str, Any], name: str) -> Any:
    if name in properties:
        return properties.get(name)
    target = name.lower()
    for key, value in properties.items():
        if str(key).lower() == target:
            return value
    return None


def _vector_property_type(value: Any) -> str:
    if value is None:
        return "str"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int) and not isinstance(value, bool):
        return "int"
    if isinstance(value, float):
        return "float"
    return "str"


def _geometry_payload(geometry: Any) -> Any:
    if geometry is None:
        return None
    if isinstance(geometry, dict):
        return geometry
    return mapping(geometry)


def _fiona_geometry_payload(geometry: Any) -> dict[str, Any]:
    return _plain_geometry_payload(fiona_to_dict(geometry))


def _plain_geometry_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return to_plain(payload)
    if hasattr(payload, "__geo_interface__"):
        return to_plain(payload.__geo_interface__)
    if hasattr(payload, "items"):
        return to_plain(dict(payload))
    raise TypeError(f"Unsupported geometry payload: {type(payload).__name__}")


def _sanitize_layer_name(name: str) -> str:
    sanitized = re.sub(r"[^0-9A-Za-z_]+", "_", str(name)).strip("_")
    if not sanitized:
        sanitized = "layer"
    if sanitized[0].isdigit():
        sanitized = f"layer_{sanitized}"
    return sanitized


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def _normalize_sqlite_value(value: Any) -> Any:
    value = _vector_property_value(value)
    if isinstance(value, bool):
        return int(value)
    return value


def _normalize_geojson_value(value: Any) -> Any:
    value = to_plain(value)
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _infer_sqlite_type(values: Iterable[Any]) -> str:
    non_null = [value for value in values if value is not None]
    if not non_null:
        return "TEXT"
    if any(isinstance(value, bytes) for value in non_null):
        return "BLOB"
    if all(isinstance(value, bool) for value in non_null):
        return "INTEGER"
    if all(isinstance(value, int) and not isinstance(value, bool) for value in non_null):
        return "INTEGER"
    if all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in non_null):
        return "REAL" if any(isinstance(value, float) for value in non_null) else "INTEGER"
    return "TEXT"


def _sqlite_type_from_schema_type(schema_type: Any) -> str:
    text = str(schema_type or "").lower()
    if text.startswith("int"):
        return "INTEGER"
    if text.startswith("float") or text.startswith("real"):
        return "REAL"
    if text.startswith("bool"):
        return "INTEGER"
    if text.startswith("bytes") or text.startswith("binary"):
        return "BLOB"
    return "TEXT"


def _resolve_field_mapping_from_names(field_names: Iterable[str]) -> dict[str, str]:
    field_mapping: dict[str, str] = {}
    used_lower = {GPKG_FID_COLUMN.lower(), GPKG_GEOMETRY_COLUMN.lower()}
    for original_name in field_names:
        base_name = str(original_name).strip() or "field"
        candidate = base_name
        suffix_index = 1
        while candidate.lower() in used_lower:
            suffix_index += 1
            candidate = f"{base_name}_{suffix_index}"
        field_mapping[str(original_name)] = candidate
        used_lower.add(candidate.lower())
    return field_mapping


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
    conn.executemany(
        """
        INSERT INTO gpkg_spatial_ref_sys (
            srs_name, srs_id, organization, organization_coordsys_id, definition, description
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            ("Undefined Cartesian SRS", -1, "NONE", -1, "undefined", "undefined cartesian coordinate reference system"),
            ("Undefined Geographic SRS", 0, "NONE", 0, "undefined", "undefined geographic coordinate reference system"),
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
    flags = 1
    return b"GP" + bytes((0, flags)) + int(srs_id).to_bytes(4, "little", signed=True) + wkb


def _gpkg_geometry_type(geometry_types: set[str], fallback: str = "GEOMETRY") -> str:
    if not geometry_types:
        value = str(fallback or "GEOMETRY").upper()
        return "GEOMETRY" if value == "UNKNOWN" else value
    if len(geometry_types) == 1:
        return next(iter(geometry_types))
    return "GEOMETRY"


def _create_gpkg_table(
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
    has_z: bool,
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
        (table_name, GPKG_GEOMETRY_COLUMN, geometry_type_name, srs_id, 1 if has_z else 0),
    )


def _write_gpkg_records_sqlite(
    output_path: Path,
    *,
    records: list[dict[str, Any]],
    crs: CRS,
    layer_name: str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    table_name = _sanitize_layer_name(layer_name)
    field_names = list((schema.get("properties") or {}).keys())
    field_mapping = _resolve_field_mapping_from_names(field_names)
    field_types = {
        field_name: _sqlite_type_from_schema_type((schema.get("properties") or {}).get(field_name))
        for field_name in field_names
    }
    srs_id = _srs_record(crs)[0]
    geometry_types: set[str] = set()
    bounds_values: list[tuple[float, float, float, float]] = []
    has_z = False

    with sqlite3.connect(output_path) as conn:
        _initialize_gpkg_metadata(conn)
        insert_sql = _create_gpkg_table(conn, table_name=table_name, field_mapping=field_mapping, field_types=field_types)
        batch: list[list[Any]] = []
        for record_index, record in enumerate(records):
            geometry = record.get("geometry")
            if geometry is None:
                raise ValueError(f"Feature {record_index + 1} has no geometry")
            if isinstance(geometry, BaseGeometry):
                geometry_obj = geometry
            else:
                geometry_obj = shape(geometry)
            if geometry_obj.is_empty:
                raise ValueError(f"Feature {record_index + 1} has empty geometry")
            geometry_types.add(geometry_obj.geom_type.upper())
            bounds_values.append(tuple(float(value) for value in geometry_obj.bounds))
            has_z = has_z or bool(getattr(geometry_obj, "has_z", False))
            row_values = [
                _normalize_sqlite_value(_get_property_case_insensitive(record["properties"], field_name))
                for field_name in field_names
            ]
            row_values.append(_build_gpkg_geometry_blob(geometry_obj, srs_id))
            batch.append(row_values)
            if len(batch) >= GPKG_BATCH_SIZE:
                conn.executemany(insert_sql, batch)
                batch.clear()
        if batch:
            conn.executemany(insert_sql, batch)
        _insert_gpkg_metadata_rows(
            conn,
            table_name=table_name,
            crs=crs,
            bounds=_aggregate_bounds_from_values(bounds_values),
            geometry_type_name=_gpkg_geometry_type(geometry_types, str(schema.get("geometry") or "GEOMETRY")),
            has_z=has_z,
        )
        conn.commit()
    return {"feature_count": len(records), "size_bytes": output_path.stat().st_size if output_path.exists() else 0}


def _write_gpkg_fiona_sqlite(
    output_path: Path,
    *,
    source: Any,
    source_crs: CRS,
    output_crs: CRS,
    layer_name: str,
    schema: dict[str, Any],
    progress_callback: Any,
    progress_interval: int,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    table_name = _sanitize_layer_name(layer_name)
    field_names = [str(name) for name in (schema.get("properties") or {}).keys()]
    field_mapping = _resolve_field_mapping_from_names(field_names)
    field_types = {
        field_name: _sqlite_type_from_schema_type((schema.get("properties") or {}).get(field_name))
        for field_name in field_names
    }
    srs_id = _srs_record(output_crs)[0]
    geometry_types: set[str] = set()
    bounds_values: list[tuple[float, float, float, float]] = []
    has_z = False
    feature_count = 0

    with sqlite3.connect(output_path) as conn:
        _initialize_gpkg_metadata(conn)
        insert_sql = _create_gpkg_table(conn, table_name=table_name, field_mapping=field_mapping, field_types=field_types)
        batch: list[list[Any]] = []
        for feature_count, feature in enumerate(source, start=1):
            geometry_payload = feature.get("geometry")
            if geometry_payload is None:
                raise ValueError(f"Feature {feature_count} has no geometry")
            geometry_mapping = _fiona_geometry_payload(geometry_payload)
            if source_crs != output_crs:
                geometry_mapping = transform_geom(source_crs.to_string(), output_crs.to_string(), geometry_mapping)
                geometry_mapping = _plain_geometry_payload(geometry_mapping)
            geometry_obj = shape(geometry_mapping)
            if geometry_obj.is_empty:
                raise ValueError(f"Feature {feature_count} has empty geometry")
            geometry_types.add(geometry_obj.geom_type.upper())
            bounds_values.append(tuple(float(value) for value in geometry_obj.bounds))
            has_z = has_z or bool(getattr(geometry_obj, "has_z", False))
            properties = dict(feature.get("properties") or {})
            row_values = [_normalize_sqlite_value(properties.get(field_name)) for field_name in field_names]
            row_values.append(_build_gpkg_geometry_blob(geometry_obj, srs_id))
            batch.append(row_values)
            if len(batch) >= GPKG_BATCH_SIZE:
                conn.executemany(insert_sql, batch)
                batch.clear()
            if progress_callback is not None and progress_interval > 0 and feature_count % progress_interval == 0:
                progress_callback(f"[T08 IO] {output_path.name}: wrote {feature_count} GPKG feature(s)")
        if batch:
            conn.executemany(insert_sql, batch)
        _insert_gpkg_metadata_rows(
            conn,
            table_name=table_name,
            crs=output_crs,
            bounds=_aggregate_bounds_from_values(bounds_values),
            geometry_type_name=_gpkg_geometry_type(geometry_types, str(schema.get("geometry") or "GEOMETRY")),
            has_z=has_z,
        )
        conn.commit()
    return {"feature_count": feature_count, "size_bytes": output_path.stat().st_size if output_path.exists() else 0}
