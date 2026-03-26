from __future__ import annotations

import csv
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional, Union

import fiona
import shapefile
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    GEOPACKAGE_SUFFIXES,
    prefer_vector_input_path,
    write_vector as _write_vector,
)


TARGET_CRS = CRS.from_epsg(3857)
OFFICIAL_VECTOR_SUFFIX = ".gpkg"
GEOJSON_SUFFIXES = {".geojson", ".json"}
VECTOR_SUFFIXES = GEOJSON_SUFFIXES | GEOPACKAGE_SUFFIXES | {".shp"}


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


def _resolve_geopackage_layer_name(path: Path, layer_name: Optional[str]) -> str:
    if layer_name:
        return layer_name

    try:
        layers = list(fiona.listlayers(str(path)))
    except Exception as exc:
        raise ValueError(f"Failed to inspect GeoPackage layers for '{path}': {exc}") from exc

    if not layers:
        raise ValueError(f"GeoPackage '{path}' has no layers.")
    if len(layers) == 1:
        return layers[0]
    if path.stem in layers:
        return path.stem
    raise ValueError(f"GeoPackage '{path}' has multiple layers {layers}; layer name is required.")


def _resolve_geopackage_crs(path: Path, layer_name: str, crs_override: Optional[str]) -> tuple[CRS, str]:
    if crs_override:
        return CRS.from_user_input(crs_override), "override"

    try:
        with fiona.open(str(path), layer=layer_name) as src:
            if src.crs_wkt:
                return CRS.from_wkt(src.crs_wkt), "gpkg.crs_wkt"
            if src.crs:
                return CRS.from_user_input(src.crs), "gpkg.crs"
    except Exception as exc:
        raise ValueError(f"Failed to open GeoPackage '{path}' layer '{layer_name}': {exc}") from exc

    raise ValueError(f"GeoPackage '{path}' layer '{layer_name}' has no CRS and no CRS override was provided.")


def _transform_geometry(geometry: BaseGeometry, source_crs: CRS) -> BaseGeometry:
    if source_crs == TARGET_CRS:
        return geometry

    transformer = _get_transformer(source_crs.to_string())
    return shapely_transform(transformer.transform, geometry)


@lru_cache(maxsize=16)
def _get_transformer(source_crs_text: str) -> Transformer:
    return Transformer.from_crs(CRS.from_user_input(source_crs_text), TARGET_CRS, always_xy=True)


def read_vector_layer(
    path: Union[str, Path],
    *,
    layer_name: Optional[str] = None,
    crs_override: Optional[str] = None,
) -> LayerReadResult:
    layer_path = prefer_vector_input_path(Path(path))
    suffix = layer_path.suffix.lower()

    if not layer_path.is_file():
        raise ValueError(f"Input layer does not exist: {layer_path}")

    if suffix in GEOJSON_SUFFIXES:
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

    if suffix in GEOPACKAGE_SUFFIXES:
        resolved_layer_name = _resolve_geopackage_layer_name(layer_path, layer_name)
        source_crs, crs_source = _resolve_geopackage_crs(layer_path, resolved_layer_name, crs_override)
        features = []
        try:
            with fiona.open(str(layer_path), layer=resolved_layer_name) as src:
                for feature in src:
                    geometry_payload = feature.get("geometry")
                    if geometry_payload is None:
                        continue
                    features.append(
                        LayerFeature(
                            properties=dict(feature.get("properties") or {}),
                            geometry=_transform_geometry(shape(geometry_payload), source_crs),
                        )
                    )
        except Exception as exc:
            raise ValueError(f"Failed to read GeoPackage '{layer_path}' layer '{resolved_layer_name}': {exc}") from exc
        return LayerReadResult(features=features, source_crs=source_crs, crs_source=crs_source)

    raise ValueError(f"Unsupported vector format for '{layer_path}'. Expected Shp, GeoJSON, or GeoPackage.")


def read_vector_layers_parallel(
    *,
    first_path: Union[str, Path],
    second_path: Union[str, Path],
    first_layer: Optional[str] = None,
    second_layer: Optional[str] = None,
    first_crs: Optional[str] = None,
    second_crs: Optional[str] = None,
    max_workers: int = 2,
) -> tuple[LayerReadResult, LayerReadResult]:
    # Two independent vector-layer reads can safely share a small fixed pool.
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="t01-io") as executor:
        future_first = executor.submit(
            read_vector_layer,
            first_path,
            layer_name=first_layer,
            crs_override=first_crs,
        )
        future_second = executor.submit(
            read_vector_layer,
            second_path,
            layer_name=second_layer,
            crs_override=second_crs,
        )
        return future_first.result(), future_second.result()


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
    with out_path.open("w", encoding="utf-8") as fp:
        json.dump(_json_compatible(payload), fp, ensure_ascii=False, separators=(",", ":"))


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
    with out_path.open("w", encoding="utf-8") as fp:
        fp.write('{"type":"FeatureCollection","name":')
        json.dump(out_path.stem, fp, ensure_ascii=False, separators=(",", ":"))
        fp.write(',"crs":{"type":"name","properties":{"name":"EPSG:3857"}},"features":[')

        first = True
        for feature in features:
            geometry = feature.get("geometry")
            feature_payload = {
                "type": "Feature",
                "properties": _json_compatible(feature.get("properties") or {}),
                "geometry": mapping(geometry) if geometry is not None else None,
            }
            if not first:
                fp.write(",")
            json.dump(feature_payload, fp, ensure_ascii=False, separators=(",", ":"))
            first = False

        fp.write("]}")


def write_vector(path: Union[str, Path], features: Iterable[dict[str, Any]], *, layer_name: Optional[str] = None) -> None:
    _write_vector(
        Path(path),
        features,
        crs_text=TARGET_CRS.to_string(),
        layer_name=layer_name,
    )


def replace_vector_suffix(value: Union[str, Path], suffix: str = OFFICIAL_VECTOR_SUFFIX) -> str:
    path = Path(str(value))
    if path.suffix.lower() in VECTOR_SUFFIXES:
        return str(path.with_suffix(suffix))
    return str(path.with_name(path.name + suffix))


def first_existing_vector_path(base_dir: Union[str, Path], *relative_paths: str) -> Optional[Path]:
    root = Path(base_dir)
    for relative_path in relative_paths:
        candidate = root / relative_path
        candidates = [candidate]
        if candidate.suffix.lower() in VECTOR_SUFFIXES:
            stem = candidate.with_suffix("")
            candidates = [
                stem.with_suffix(".gpkg"),
                stem.with_suffix(".gpkt"),
                stem.with_suffix(".geojson"),
                stem.with_suffix(".json"),
                stem.with_suffix(".shp"),
            ]
        for resolved in candidates:
            if resolved.is_file():
                return resolved
    return None


def load_vector_feature_collection(
    path: Union[str, Path],
    *,
    layer_name: Optional[str] = None,
    crs_override: Optional[str] = None,
) -> dict[str, Any]:
    result = read_vector_layer(path, layer_name=layer_name, crs_override=crs_override)
    return {
        "type": "FeatureCollection",
        "name": Path(path).stem,
        "crs": {"type": "name", "properties": {"name": TARGET_CRS.to_string()}},
        "features": [
            {
                "type": "Feature",
                "properties": _json_compatible(feature.properties),
                "geometry": mapping(feature.geometry) if feature.geometry is not None else None,
            }
            for feature in result.features
        ],
    }
