from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional, Union

import shapefile
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform


TARGET_CRS = CRS.from_epsg(3857)


@dataclass(frozen=True)
class LayerFeature:
    properties: dict[str, Any]
    geometry: BaseGeometry


@dataclass(frozen=True)
class LayerReadResult:
    features: list[LayerFeature]
    source_crs: CRS
    crs_source: str


def _resolve_geojson_crs(doc: dict[str, Any], crs_override: Optional[str]) -> tuple[CRS, str]:
    if crs_override:
        return CRS.from_user_input(crs_override), "override"

    crs_payload = doc.get("crs")
    if isinstance(crs_payload, dict):
        props = crs_payload.get("properties") or {}
        name = props.get("name")
        if name:
            return CRS.from_user_input(name), "geojson.crs"

    return CRS.from_epsg(4326), "geojson-default"


def _resolve_shapefile_crs(path: Path, crs_override: Optional[str]) -> tuple[CRS, str]:
    if crs_override:
        return CRS.from_user_input(crs_override), "override"

    prj_path = path.with_suffix(".prj")
    if prj_path.is_file():
        return CRS.from_wkt(prj_path.read_text(encoding="utf-8", errors="ignore")), "prj"

    raise ValueError(
        f"Shapefile '{path}' has no .prj and no CRS override was provided; cannot normalize to EPSG:3857."
    )


def _transform_geometry(geometry: BaseGeometry, source_crs: CRS) -> BaseGeometry:
    if source_crs == TARGET_CRS:
        return geometry

    transformer = Transformer.from_crs(source_crs, TARGET_CRS, always_xy=True)
    return shapely_transform(transformer.transform, geometry)


def read_vector_layer(
    path: Union[str, Path],
    *,
    layer_name: Optional[str] = None,
    crs_override: Optional[str] = None,
) -> LayerReadResult:
    del layer_name  # Reserved for future multi-layer support.

    layer_path = Path(path)
    suffix = layer_path.suffix.lower()

    if suffix in {".geojson", ".json"}:
        doc = json.loads(layer_path.read_text(encoding="utf-8"))
        source_crs, crs_source = _resolve_geojson_crs(doc, crs_override)
        features: list[LayerFeature] = []
        for feature in doc.get("features", []):
            geometry_payload = feature.get("geometry")
            if geometry_payload is None:
                continue
            features.append(
                LayerFeature(
                    properties=dict(feature.get("properties") or {}),
                    geometry=_transform_geometry(shape(geometry_payload), source_crs),
                )
            )
        return LayerReadResult(features=features, source_crs=source_crs, crs_source=crs_source)

    if suffix == ".shp":
        source_crs, crs_source = _resolve_shapefile_crs(layer_path, crs_override)
        reader = shapefile.Reader(str(layer_path))
        field_names = [field[0] for field in reader.fields[1:]]
        features = []
        for shape_record in reader.iterShapeRecords():
            props = dict(zip(field_names, list(shape_record.record)))
            features.append(
                LayerFeature(
                    properties=props,
                    geometry=_transform_geometry(shape(shape_record.shape.__geo_interface__), source_crs),
                )
            )
        return LayerReadResult(features=features, source_crs=source_crs, crs_source=crs_source)

    raise ValueError(f"Unsupported vector format for '{layer_path}'. Expected Shp or GeoJSON.")


def _json_compatible(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_compatible(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_compatible(v) for v in value]
    if isinstance(value, Path):
        return str(value)
    return value


def write_json(path: Union[str, Path], payload: Any) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(_json_compatible(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(path: Union[str, Path], rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _json_compatible(row.get(key)) for key in fieldnames})


def write_geojson(path: Union[str, Path], features: Iterable[dict[str, Any]]) -> None:
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

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
        "name": out_path.stem,
        "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
        "features": feature_items,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
