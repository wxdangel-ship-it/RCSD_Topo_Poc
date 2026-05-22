from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import fiona
from pyproj import CRS, Transformer
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform


PROCESS_CRS_TEXT = "EPSG:3857"
GPKG_SUFFIX = ".gpkg"
GEOJSON_SUFFIXES = frozenset({".geojson", ".json"})


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
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    records = [_prepare_record(feature) for feature in feature_list]
    schema = _build_schema(records, empty_fields=empty_fields, geometry_type=geometry_type)
    property_names = list(schema["properties"].keys())

    with fiona.open(
        str(output_path),
        mode="w",
        driver="GPKG",
        layer=layer_name or output_path.stem,
        schema=schema,
        crs=crs_text,
        encoding="utf-8",
    ) as sink:
        for record in records:
            sink.write(
                {
                    "type": "Feature",
                    "properties": {name: _get_property_case_insensitive(record["properties"], name) for name in property_names},
                    "geometry": _geometry_payload(record["geometry"]),
                }
            )

    return {"feature_count": len(records), "size_bytes": output_path.stat().st_size if output_path.exists() else 0}


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
    schema = _build_schema(records, empty_fields=empty_fields, geometry_type=geometry_type)
    property_names = list(schema["properties"].keys())

    with fiona.open(
        str(output_path),
        mode="w",
        driver="GeoJSON",
        schema=schema,
        crs=crs_text,
        encoding="utf-8",
    ) as sink:
        for record in records:
            sink.write(
                {
                    "type": "Feature",
                    "properties": {name: _get_property_case_insensitive(record["properties"], name) for name in property_names},
                    "geometry": _geometry_payload(record["geometry"]),
                }
            )

    return {"feature_count": len(records), "size_bytes": output_path.stat().st_size if output_path.exists() else 0}


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
