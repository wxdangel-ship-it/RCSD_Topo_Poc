from __future__ import annotations

import json
import logging
import math
import os
import re
import shapefile
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

from pyproj import CRS, Transformer
from shapely import make_valid
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform


TARGET_CRS = CRS.from_epsg(3857)
DEFAULT_GEOJSON_CRS = CRS.from_epsg(4326)
WEB_MERCATOR_MAX_ABS = 20037508.342789244
GEOGRAPHIC_RANGE_TOLERANCE = 1e-9
GEOPACKAGE_SUFFIXES = {".gpkg", ".gpkt"}


@dataclass(frozen=True)
class GeoJsonFeature:
    properties: dict[str, Any]
    geometry: BaseGeometry


@dataclass(frozen=True)
class GeoJsonReadResult:
    features: list[GeoJsonFeature]
    source_crs: CRS
    crs_source: str


def sort_patch_key(name: str) -> tuple[int, int | str]:
    stripped = name.strip()
    if stripped.isdigit():
        return (0, int(stripped))
    return (1, stripped)


def build_run_id(prefix: str, now: datetime | None = None) -> str:
    current = datetime.now() if now is None else now
    return f"{prefix}_{current.strftime('%Y%m%d_%H%M%S')}"


def list_patch_dirs(patch_all_root: Path) -> list[Path]:
    return sorted(
        [path for path in patch_all_root.iterdir() if path.is_dir() and path.name.isdigit()],
        key=lambda path: sort_patch_key(path.name),
    )


def remove_existing_output(path: Path) -> None:
    if path.exists():
        path.unlink()


def prefer_vector_input_path(path: Path) -> Path:
    resolved = normalize_runtime_path(path)
    suffix = resolved.suffix.lower()
    if suffix in GEOPACKAGE_SUFFIXES:
        return resolved
    for candidate_suffix in (".gpkg", ".gpkt"):
        candidate = resolved.with_suffix(candidate_suffix)
        if candidate.is_file():
            return candidate
    return resolved


def normalize_runtime_path(path: Path | str) -> Path:
    raw = str(path)
    if os.name == "nt":
        match = re.match(r"^[\\/]+mnt[\\/]+([a-zA-Z])[\\/](.*)$", raw)
        if match:
            drive_letter = match.group(1).upper()
            tail = match.group(2).replace("/", "\\")
            return Path(f"{drive_letter}:\\{tail}")
    else:
        match = re.match(r"^([a-zA-Z]):[\\/](.*)$", raw)
        if match:
            drive_letter = match.group(1).lower()
            tail = match.group(2).replace("\\", "/")
            return Path(f"/mnt/{drive_letter}/{tail}")
    return Path(path)


def build_logger(log_path: Path, logger_name: str) -> logging.Logger:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if logger.handlers:
        for existing_handler in list(logger.handlers):
            existing_handler.close()
            logger.removeHandler(existing_handler)

    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    return logger


def announce(logger: logging.Logger, message: str) -> None:
    print(message, flush=True)
    logger.info(message)


def close_logger(logger: logging.Logger) -> None:
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def resolve_geojson_crs(doc: dict[str, Any], default_crs_text: Optional[str]) -> tuple[CRS, str]:
    crs_payload = doc.get("crs")
    if isinstance(crs_payload, dict):
        props = crs_payload.get("properties") or {}
        name = props.get("name")
        if name:
            return CRS.from_user_input(name), "geojson.crs"

    if default_crs_text:
        return CRS.from_user_input(default_crs_text), "default"

    return DEFAULT_GEOJSON_CRS, "geojson-default"


@lru_cache(maxsize=64)
def _get_transformer(source_crs_text: str, target_crs_text: str) -> Transformer:
    return Transformer.from_crs(
        CRS.from_user_input(source_crs_text),
        CRS.from_user_input(target_crs_text),
        always_xy=True,
    )


def _finite_bounds(geometry: BaseGeometry | None, *, stage: str) -> tuple[float, float, float, float] | None:
    if geometry is None or geometry.is_empty:
        return None

    bounds = tuple(float(value) for value in geometry.bounds)
    if not all(math.isfinite(value) for value in bounds):
        raise ValueError(f"{stage} produced non-finite geometry bounds: {bounds}")
    return bounds


def _ensure_source_geometry_matches_crs(geometry: BaseGeometry, source_crs: CRS) -> None:
    bounds = _finite_bounds(geometry, stage=f"source geometry for {source_crs.to_string()}")
    if bounds is None or not source_crs.is_geographic:
        return

    min_x, min_y, max_x, max_y = bounds
    if (
        min_x < -180.0 - GEOGRAPHIC_RANGE_TOLERANCE
        or max_x > 180.0 + GEOGRAPHIC_RANGE_TOLERANCE
        or min_y < -90.0 - GEOGRAPHIC_RANGE_TOLERANCE
        or max_y > 90.0 + GEOGRAPHIC_RANGE_TOLERANCE
    ):
        raise ValueError(
            "source geometry bounds "
            f"{bounds} exceed the valid lon/lat range for geographic CRS {source_crs.to_string()}; "
            "likely missing or incorrect CRS metadata"
        )


def _ensure_geometry_in_target_extent(
    geometry: BaseGeometry | None,
    *,
    target_crs: CRS,
    stage: str,
) -> BaseGeometry | None:
    bounds = _finite_bounds(geometry, stage=stage)
    if bounds is None:
        return geometry

    if target_crs != TARGET_CRS:
        return geometry

    min_x, min_y, max_x, max_y = bounds
    limit = WEB_MERCATOR_MAX_ABS + 1.0
    if min_x < -limit or max_x > limit or min_y < -limit or max_y > limit:
        raise ValueError(f"{stage} produced geometry outside the valid EPSG:3857 extent: {bounds}")
    return geometry


def transform_geometry_to_target(geometry: BaseGeometry, source_crs: CRS, target_crs: CRS) -> BaseGeometry:
    _ensure_source_geometry_matches_crs(geometry, source_crs)

    if source_crs == target_crs:
        return _ensure_geometry_in_target_extent(
            geometry,
            target_crs=target_crs,
            stage=f"source geometry already declared as {target_crs.to_string()}",
        )

    transformer = _get_transformer(source_crs.to_string(), target_crs.to_string())
    transformed = shapely_transform(transformer.transform, geometry)
    return _ensure_geometry_in_target_extent(
        transformed,
        target_crs=target_crs,
        stage=f"geometry transformed from {source_crs.to_string()} to {target_crs.to_string()}",
    )


def transform_geometry_to_3857(geometry: BaseGeometry, source_crs: CRS) -> BaseGeometry:
    return transform_geometry_to_target(geometry, source_crs, TARGET_CRS)


def read_geojson_features(
    path: Path,
    *,
    default_crs_text: Optional[str],
    target_crs_text: Optional[str] = None,
) -> GeoJsonReadResult:
    doc = json.loads(path.read_text(encoding="utf-8"))
    source_crs, crs_source = resolve_geojson_crs(doc, default_crs_text)
    target_crs = TARGET_CRS if target_crs_text is None else CRS.from_user_input(target_crs_text)
    features: list[GeoJsonFeature] = []
    for feature in doc.get("features", []):
        geometry_payload = feature.get("geometry")
        if geometry_payload is None:
            continue
        geometry = transform_geometry_to_target(shape(geometry_payload), source_crs, target_crs)
        features.append(
            GeoJsonFeature(
                properties=dict(feature.get("properties") or {}),
                geometry=geometry,
            )
        )

    return GeoJsonReadResult(features=features, source_crs=source_crs, crs_source=crs_source)


def resolve_shapefile_crs(path: Path, default_crs_text: Optional[str]) -> tuple[CRS, str]:
    prj_path = path.with_suffix(".prj")
    if prj_path.is_file():
        prj_text = prj_path.read_text(encoding="utf-8", errors="ignore").strip()
        if prj_text:
            return CRS.from_wkt(prj_text), "shapefile.prj"

    if default_crs_text:
        return CRS.from_user_input(default_crs_text), "default"

    raise ValueError(f"CRS not found for shapefile and no default CRS configured: {path}")


def read_shapefile_features(
    path: Path,
    *,
    default_crs_text: Optional[str],
    target_crs_text: Optional[str] = None,
) -> GeoJsonReadResult:
    source_crs, crs_source = resolve_shapefile_crs(path, default_crs_text)
    target_crs = TARGET_CRS if target_crs_text is None else CRS.from_user_input(target_crs_text)
    reader = shapefile.Reader(str(path))
    field_names = [field[0] for field in reader.fields[1:]]

    features: list[GeoJsonFeature] = []
    for shape_record in reader.iterShapeRecords():
        geometry_payload = shape_record.shape.__geo_interface__
        geometry = transform_geometry_to_target(shape(geometry_payload), source_crs, target_crs)
        properties = {
            field_names[index]: shape_record.record[index]
            for index in range(len(field_names))
        }
        features.append(
            GeoJsonFeature(
                properties=properties,
                geometry=geometry,
            )
        )

    return GeoJsonReadResult(features=features, source_crs=source_crs, crs_source=crs_source)


def _collect_polygon_parts(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return list(geometry.geoms)
    if isinstance(geometry, GeometryCollection):
        parts: list[Polygon] = []
        for item in geometry.geoms:
            parts.extend(_collect_polygon_parts(item))
        return parts
    return []


def extract_polygonal(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None

    polygon_parts = [part for part in _collect_polygon_parts(geometry) if not part.is_empty]
    if not polygon_parts:
        return None
    if len(polygon_parts) == 1:
        return polygon_parts[0]
    return MultiPolygon(polygon_parts)


def minimal_repair(geometry: BaseGeometry | None) -> BaseGeometry | None:
    candidate = extract_polygonal(geometry)
    if candidate is None:
        return None
    candidate = _ensure_geometry_in_target_extent(
        candidate,
        target_crs=TARGET_CRS,
        stage="polygonal geometry before repair",
    )
    if candidate.is_valid:
        return candidate

    try:
        candidate = extract_polygonal(make_valid(candidate))
    except Exception:
        candidate = None

    if candidate is not None:
        candidate = _ensure_geometry_in_target_extent(
            candidate,
            target_crs=TARGET_CRS,
            stage="polygonal geometry after make_valid",
        )

    if candidate is not None and candidate.is_valid:
        return candidate

    if candidate is None:
        return None

    try:
        candidate = extract_polygonal(candidate.buffer(0))
    except Exception:
        candidate = None

    if candidate is None:
        return None

    candidate = _ensure_geometry_in_target_extent(
        candidate,
        target_crs=TARGET_CRS,
        stage="polygonal geometry after buffer(0)",
    )
    if candidate.is_empty or not candidate.is_valid:
        return None
    return candidate


def minimal_geometry_repair(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    if geometry.is_valid:
        return geometry

    try:
        candidate = make_valid(geometry)
    except Exception:
        return None

    if candidate is None or candidate.is_empty or not candidate.is_valid:
        return None
    return candidate


def simplify_polygonal(geometry: BaseGeometry | None, tolerance_meters: float) -> BaseGeometry | None:
    if geometry is None:
        return None
    simplified = geometry.simplify(tolerance_meters, preserve_topology=True)
    return minimal_repair(simplified)


def polygon_part_count(geometry: BaseGeometry | None) -> int:
    if geometry is None or geometry.is_empty:
        return 0
    if isinstance(geometry, Polygon):
        return 1
    if isinstance(geometry, MultiPolygon):
        return len(geometry.geoms)
    return len(_collect_polygon_parts(geometry))


def geometry_bounds(geometry: BaseGeometry | None) -> list[float] | None:
    bounds = _finite_bounds(geometry, stage="summary geometry")
    if bounds is None:
        return None
    return list(bounds)


def aggregate_bounds(geometries: Iterable[BaseGeometry]) -> list[float] | None:
    bounds_values = [geometry_bounds(geometry) for geometry in geometries]
    bounds_values = [bounds for bounds in bounds_values if bounds is not None]
    if not bounds_values:
        return None

    min_x = min(bounds[0] for bounds in bounds_values)
    min_y = min(bounds[1] for bounds in bounds_values)
    max_x = max(bounds[2] for bounds in bounds_values)
    max_y = max(bounds[3] for bounds in bounds_values)
    return [float(min_x), float(min_y), float(max_x), float(max_y)]


def resolve_case_insensitive_field_name(properties: dict[str, Any], candidates: Iterable[str]) -> str | None:
    lower_map = {str(key).lower(): str(key) for key in properties.keys()}
    for candidate in candidates:
        resolved = lower_map.get(candidate.lower())
        if resolved is not None:
            return resolved
    return None


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_compatible(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Counter):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    return value


def _vector_property_value(value: Any) -> Any:
    value = _json_compatible(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


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


def _prepare_vector_records(features: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for feature in features:
        geometry = feature.get("geometry")
        properties = {
            str(key): _vector_property_value(value)
            for key, value in (feature.get("properties") or {}).items()
        }
        prepared.append({"properties": properties, "geometry": geometry})
    return prepared


def _vector_geometry_payload(geometry: Any) -> Any:
    if geometry is None:
        return None
    if isinstance(geometry, dict):
        return geometry
    return mapping(geometry)


def _require_fiona() -> Any:
    try:
        import fiona
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "fiona is required only for GeoPackage export tools. Install fiona before writing .gpkg/.gpkt outputs."
        ) from exc
    return fiona


def _build_fiona_schema(records: list[dict[str, Any]]) -> dict[str, Any]:
    field_order: list[str] = []
    field_types: dict[str, str] = {}
    for record in records:
        for key, value in record["properties"].items():
            if key not in field_order:
                field_order.append(key)
            if key not in field_types and value is not None:
                field_types[key] = _vector_property_type(value)
    for key in field_order:
        field_types.setdefault(key, "str")
    return {
        "geometry": "Unknown",
        "properties": {key: field_types[key] for key in field_order},
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(_json_compatible(payload), fp, ensure_ascii=False, indent=2, allow_nan=False)


def write_geojson(path: Path, features: Iterable[dict[str, Any]], *, crs_text: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        fp.write('{"type":"FeatureCollection","name":')
        json.dump(path.stem, fp, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        fp.write(',"crs":{"type":"name","properties":{"name":')
        json.dump(crs_text or TARGET_CRS.to_string(), fp, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        fp.write('}},"features":[')

        first = True
        for feature in features:
            geometry = feature.get("geometry")
            feature_payload = {
                "type": "Feature",
                "properties": _json_compatible(feature.get("properties") or {}),
                "geometry": _vector_geometry_payload(geometry),
            }
            if not first:
                fp.write(",")
            json.dump(feature_payload, fp, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            first = False

        fp.write("]}")


def write_vector(
    path: Path,
    features: Iterable[dict[str, Any]],
    *,
    crs_text: str | None = None,
    layer_name: str | None = None,
) -> None:
    output_path = Path(path)
    suffix = output_path.suffix.lower()
    if suffix in {".geojson", ".json"}:
        write_geojson(output_path, features, crs_text=crs_text)
        return
    if suffix not in GEOPACKAGE_SUFFIXES:
        raise ValueError(f"Unsupported vector output format for '{output_path}'. Expected GeoJSON or GeoPackage.")

    records = _prepare_vector_records(features)
    schema = _build_fiona_schema(records)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    remove_existing_output(output_path)
    open_kwargs: dict[str, Any] = {
        "mode": "w",
        "driver": "GPKG",
        "layer": layer_name or output_path.stem,
        "schema": schema,
        "encoding": "utf-8",
    }
    if crs_text is not None:
        open_kwargs["crs"] = crs_text
    fiona = _require_fiona()
    with fiona.open(str(output_path), **open_kwargs) as sink:
        schema_property_names = list(schema["properties"].keys())
        for record in records:
            sink.write(
                {
                    "type": "Feature",
                    "properties": {
                        key: record["properties"].get(key)
                        for key in schema_property_names
                    },
                    "geometry": _vector_geometry_payload(record["geometry"]),
                }
            )
