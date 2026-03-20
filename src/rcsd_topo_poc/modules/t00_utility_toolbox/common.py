from __future__ import annotations

import json
import logging
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


def transform_geometry_to_3857(geometry: BaseGeometry, source_crs: CRS) -> BaseGeometry:
    if source_crs == TARGET_CRS:
        return geometry

    transformer = _get_transformer(source_crs.to_string())
    return shapely_transform(transformer.transform, geometry)


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
    if candidate.is_valid:
        return candidate

    try:
        candidate = extract_polygonal(make_valid(candidate))
    except Exception:
        candidate = None

    if candidate is not None and candidate.is_valid:
        return candidate

    if candidate is None:
        return None

    try:
        candidate = extract_polygonal(candidate.buffer(0))
    except Exception:
        candidate = None

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
    if geometry is None or geometry.is_empty:
        return None
    return [float(value) for value in geometry.bounds]


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
        json.dump(_json_compatible(payload), fp, ensure_ascii=False, indent=2)


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
        json.dump(payload, fp, ensure_ascii=False, separators=(",", ":"))
