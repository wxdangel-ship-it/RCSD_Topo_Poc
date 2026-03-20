from __future__ import annotations

import json
import logging
import math
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


@lru_cache(maxsize=16)
def _get_transformer(source_crs_text: str) -> Transformer:
    return Transformer.from_crs(CRS.from_user_input(source_crs_text), TARGET_CRS, always_xy=True)


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


def _ensure_geometry_in_3857_extent(geometry: BaseGeometry | None, *, stage: str) -> BaseGeometry | None:
    bounds = _finite_bounds(geometry, stage=stage)
    if bounds is None:
        return geometry

    min_x, min_y, max_x, max_y = bounds
    limit = WEB_MERCATOR_MAX_ABS + 1.0
    if min_x < -limit or max_x > limit or min_y < -limit or max_y > limit:
        raise ValueError(f"{stage} produced geometry outside the valid EPSG:3857 extent: {bounds}")
    return geometry


def transform_geometry_to_3857(geometry: BaseGeometry, source_crs: CRS) -> BaseGeometry:
    _ensure_source_geometry_matches_crs(geometry, source_crs)

    if source_crs == TARGET_CRS:
        return _ensure_geometry_in_3857_extent(
            geometry,
            stage="source geometry already declared as EPSG:3857",
        )

    transformer = _get_transformer(source_crs.to_string())
    transformed = shapely_transform(transformer.transform, geometry)
    return _ensure_geometry_in_3857_extent(
        transformed,
        stage=f"geometry transformed from {source_crs.to_string()} to {TARGET_CRS.to_string()}",
    )


def read_geojson_features(path: Path, *, default_crs_text: Optional[str]) -> GeoJsonReadResult:
    doc = json.loads(path.read_text(encoding="utf-8"))
    source_crs, crs_source = resolve_geojson_crs(doc, default_crs_text)
    features: list[GeoJsonFeature] = []
    for feature in doc.get("features", []):
        geometry_payload = feature.get("geometry")
        if geometry_payload is None:
            continue
        geometry = transform_geometry_to_3857(shape(geometry_payload), source_crs)
        features.append(
            GeoJsonFeature(
                properties=dict(feature.get("properties") or {}),
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
    candidate = _ensure_geometry_in_3857_extent(candidate, stage="polygonal geometry before repair")
    if candidate.is_valid:
        return candidate

    try:
        candidate = extract_polygonal(make_valid(candidate))
    except Exception:
        candidate = None

    if candidate is not None:
        candidate = _ensure_geometry_in_3857_extent(candidate, stage="polygonal geometry after make_valid")

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

    candidate = _ensure_geometry_in_3857_extent(candidate, stage="polygonal geometry after buffer(0)")
    if candidate.is_empty or not candidate.is_valid:
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


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        json.dump(_json_compatible(payload), fp, ensure_ascii=False, indent=2, allow_nan=False)


def write_geojson(path: Path, features: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    feature_items = []
    for feature in features:
        geometry = feature.get("geometry")
        feature_items.append(
            {
                "type": "Feature",
                "properties": _json_compatible(feature.get("properties") or {}),
                "geometry": mapping(geometry) if geometry is not None else None,
            }
        )

    payload = {
        "type": "FeatureCollection",
        "name": path.stem,
        "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
        "features": feature_items,
    }
    with path.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
