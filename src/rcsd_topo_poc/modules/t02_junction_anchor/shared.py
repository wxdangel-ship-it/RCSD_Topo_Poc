from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

import fiona
import shapefile
from pyproj import CRS
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    GEOPACKAGE_SUFFIXES,
    TARGET_CRS,
    prefer_vector_input_path,
    transform_geometry_to_target,
)


class T02RunError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class LoadedFeature:
    feature_index: int
    properties: dict[str, Any]
    geometry: BaseGeometry | None


@dataclass(frozen=True)
class LoadedLayer:
    features: list[LoadedFeature]
    source_crs: CRS
    crs_source: str


@dataclass(frozen=True)
class NodeRecord:
    feature_index: int
    output_index: int
    node_id: str
    mainnodeid: str | None
    geometry: BaseGeometry


@dataclass(frozen=True)
class ResolvedJunctionGroup:
    junction_id: str
    group_nodes: list[Any]
    representative: Any | None
    resolution_mode: str
    reason: str | None
    detail: str | None


def find_repo_root(start: Path) -> Optional[Path]:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "docs").is_dir():
            return candidate
    return None


def normalize_id(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value.is_integer():
            return str(int(value))
        return str(value)
    text = str(value).strip()
    if not text:
        return None
    if text.lower() in {"null", "none", "nan"}:
        return None
    return text


def audit_row(
    *,
    scope: str,
    status: str,
    reason: str,
    detail: str,
    segment_id: str | None = None,
    junction_id: str | None = None,
    **extra_fields: Any,
) -> dict[str, Any]:
    payload = {
        "scope": scope,
        "segment_id": segment_id,
        "junction_id": junction_id,
        "status": status,
        "reason": reason,
        "detail": detail,
    }
    payload.update(extra_fields)
    return payload


def _load_json(path: Path, *, error_cls: type[T02RunError]) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise error_cls("invalid_crs_or_unprojectable", f"Failed to read GeoJSON '{path}': {exc}") from exc


def _resolve_geojson_crs_strict(
    doc: dict[str, Any],
    crs_override: Optional[str],
    *,
    error_cls: type[T02RunError],
) -> tuple[CRS, str]:
    if crs_override:
        try:
            return CRS.from_user_input(crs_override), "override"
        except Exception as exc:
            raise error_cls(
                "invalid_crs_or_unprojectable",
                f"Invalid CRS override '{crs_override}': {exc}",
            ) from exc

    crs_payload = doc.get("crs")
    if isinstance(crs_payload, dict):
        props = crs_payload.get("properties") or {}
        name = props.get("name")
        if name:
            try:
                return CRS.from_user_input(name), "geojson.crs"
            except Exception as exc:
                raise error_cls(
                    "invalid_crs_or_unprojectable",
                    f"Invalid GeoJSON CRS '{name}': {exc}",
                ) from exc

    raise error_cls(
        "invalid_crs_or_unprojectable",
        "GeoJSON is missing CRS metadata and no CRS override was provided.",
    )


def _resolve_shapefile_crs_strict(
    path: Path,
    crs_override: Optional[str],
    *,
    error_cls: type[T02RunError],
) -> tuple[CRS, str]:
    if crs_override:
        try:
            return CRS.from_user_input(crs_override), "override"
        except Exception as exc:
            raise error_cls(
                "invalid_crs_or_unprojectable",
                f"Invalid CRS override '{crs_override}': {exc}",
            ) from exc

    prj_path = path.with_suffix(".prj")
    if prj_path.is_file():
        try:
            return CRS.from_wkt(prj_path.read_text(encoding="utf-8", errors="ignore")), "shapefile.prj"
        except Exception as exc:
            raise error_cls(
                "invalid_crs_or_unprojectable",
                f"Failed to parse shapefile .prj for '{path}': {exc}",
            ) from exc

    raise error_cls(
        "invalid_crs_or_unprojectable",
        f"Shapefile '{path}' has no .prj and no CRS override was provided.",
    )


def _resolve_geopackage_layer_name(
    path: Path,
    layer_name: Optional[str],
    *,
    error_cls: type[T02RunError],
) -> str:
    if layer_name:
        return layer_name
    try:
        layers = list(fiona.listlayers(str(path)))
    except Exception as exc:
        raise error_cls(
            "missing_required_field",
            f"Failed to inspect GeoPackage layers for '{path}': {exc}",
        ) from exc
    if not layers:
        raise error_cls("missing_required_field", f"GeoPackage '{path}' has no layers.")
    if len(layers) == 1:
        return layers[0]
    if path.stem in layers:
        return path.stem
    raise error_cls(
        "missing_required_field",
        f"GeoPackage '{path}' has multiple layers {layers}; layer name is required.",
    )


def _resolve_geopackage_crs_strict(
    path: Path,
    layer_name: str,
    crs_override: Optional[str],
    *,
    error_cls: type[T02RunError],
) -> tuple[CRS, str]:
    if crs_override:
        try:
            return CRS.from_user_input(crs_override), "override"
        except Exception as exc:
            raise error_cls(
                "invalid_crs_or_unprojectable",
                f"Invalid CRS override '{crs_override}': {exc}",
            ) from exc
    try:
        with fiona.open(str(path), layer=layer_name) as src:
            if src.crs_wkt:
                return CRS.from_wkt(src.crs_wkt), "gpkg.crs_wkt"
            if src.crs:
                return CRS.from_user_input(src.crs), "gpkg.crs"
    except Exception as exc:
        raise error_cls(
            "invalid_crs_or_unprojectable",
            f"Failed to open GeoPackage '{path}' layer '{layer_name}': {exc}",
        ) from exc
    raise error_cls(
        "invalid_crs_or_unprojectable",
        f"GeoPackage '{path}' layer '{layer_name}' has no CRS and no CRS override was provided.",
    )


def _transform_geometry(
    geometry: BaseGeometry | None,
    *,
    source_crs: CRS,
    layer_label: str,
    feature_index: int,
    error_cls: type[T02RunError],
) -> BaseGeometry | None:
    if geometry is None:
        return None
    try:
        return transform_geometry_to_target(geometry, source_crs, TARGET_CRS)
    except Exception as exc:
        raise error_cls(
            "invalid_crs_or_unprojectable",
            f"{layer_label} feature[{feature_index}] failed to transform to EPSG:3857: {exc}",
        ) from exc


def read_vector_layer_strict(
    path: Union[str, Path],
    *,
    layer_name: Optional[str] = None,
    crs_override: Optional[str] = None,
    allow_null_geometry: bool,
    error_cls: type[T02RunError] = T02RunError,
) -> LoadedLayer:
    layer_path = prefer_vector_input_path(Path(path))
    if not layer_path.is_file():
        raise error_cls(
            "missing_required_field",
            f"Input layer does not exist: {layer_path}",
        )

    suffix = layer_path.suffix.lower()
    if suffix in {".geojson", ".json"}:
        doc = _load_json(layer_path, error_cls=error_cls)
        source_crs, crs_source = _resolve_geojson_crs_strict(doc, crs_override, error_cls=error_cls)
        features: list[LoadedFeature] = []
        for feature_index, feature in enumerate(doc.get("features", [])):
            geometry_payload = feature.get("geometry")
            if geometry_payload is None and not allow_null_geometry:
                raise error_cls(
                    "missing_required_field",
                    f"{layer_path} feature[{feature_index}] is missing geometry.",
                )
            geometry = None if geometry_payload is None else _transform_geometry(
                shape(geometry_payload),
                source_crs=source_crs,
                layer_label=str(layer_path),
                feature_index=feature_index,
                error_cls=error_cls,
            )
            features.append(
                LoadedFeature(
                    feature_index=feature_index,
                    properties=dict(feature.get("properties") or {}),
                    geometry=geometry,
                )
            )
        return LoadedLayer(features=features, source_crs=source_crs, crs_source=crs_source)

    if suffix == ".shp":
        source_crs, crs_source = _resolve_shapefile_crs_strict(layer_path, crs_override, error_cls=error_cls)
        try:
            reader = shapefile.Reader(str(layer_path))
        except Exception as exc:
            raise error_cls(
                "invalid_crs_or_unprojectable",
                f"Failed to read shapefile '{layer_path}': {exc}",
            ) from exc

        field_names = [field[0] for field in reader.fields[1:]]
        features: list[LoadedFeature] = []
        for feature_index, shape_record in enumerate(reader.iterShapeRecords()):
            geometry_payload = shape_record.shape.__geo_interface__
            geometry = _transform_geometry(
                shape(geometry_payload),
                source_crs=source_crs,
                layer_label=str(layer_path),
                feature_index=feature_index,
                error_cls=error_cls,
            )
            features.append(
                LoadedFeature(
                    feature_index=feature_index,
                    properties=dict(zip(field_names, list(shape_record.record))),
                    geometry=geometry,
                )
            )
        return LoadedLayer(features=features, source_crs=source_crs, crs_source=crs_source)

    if suffix in GEOPACKAGE_SUFFIXES:
        resolved_layer_name = _resolve_geopackage_layer_name(layer_path, layer_name, error_cls=error_cls)
        source_crs, crs_source = _resolve_geopackage_crs_strict(
            layer_path,
            resolved_layer_name,
            crs_override,
            error_cls=error_cls,
        )
        try:
            with fiona.open(str(layer_path), layer=resolved_layer_name) as src:
                features: list[LoadedFeature] = []
                for feature_index, feature in enumerate(src):
                    geometry_payload = feature.get("geometry")
                    if geometry_payload is None and not allow_null_geometry:
                        raise error_cls(
                            "missing_required_field",
                            f"{layer_path} layer '{resolved_layer_name}' feature[{feature_index}] is missing geometry.",
                        )
                    geometry = None if geometry_payload is None else _transform_geometry(
                        shape(geometry_payload),
                        source_crs=source_crs,
                        layer_label=f"{layer_path}:{resolved_layer_name}",
                        feature_index=feature_index,
                        error_cls=error_cls,
                    )
                    features.append(
                        LoadedFeature(
                            feature_index=feature_index,
                            properties=dict(feature.get("properties") or {}),
                            geometry=geometry,
                        )
                    )
        except T02RunError:
            raise
        except Exception as exc:
            raise error_cls(
                "invalid_crs_or_unprojectable",
                f"Failed to read GeoPackage '{layer_path}' layer '{resolved_layer_name}': {exc}",
            ) from exc
        return LoadedLayer(features=features, source_crs=source_crs, crs_source=crs_source)

    raise error_cls(
        "missing_required_field",
        f"Unsupported vector format for '{layer_path}'. Expected GeoJSON, Shapefile, or GeoPackage.",
    )


def resolve_junction_group(
    junction_id: str,
    *,
    nodes_by_mainnodeid: dict[str, list[Any]],
    singleton_nodes_by_id: dict[str, list[Any]],
    representative_missing_reason: str,
    junction_not_found_reason: str,
) -> ResolvedJunctionGroup:
    group_nodes = nodes_by_mainnodeid.get(junction_id)
    if group_nodes:
        representatives = [record for record in group_nodes if getattr(record, "node_id", None) == junction_id]
        if not representatives:
            return ResolvedJunctionGroup(
                junction_id=junction_id,
                group_nodes=list(group_nodes),
                representative=None,
                resolution_mode="mainnode_group",
                reason=representative_missing_reason,
                detail=(
                    f"junction_id='{junction_id}' matched mainnodeid group but no node with id == junction_id exists."
                ),
            )
        return ResolvedJunctionGroup(
            junction_id=junction_id,
            group_nodes=list(group_nodes),
            representative=representatives[0],
            resolution_mode="mainnode_group",
            reason=None,
            detail=None,
        )

    singleton_candidates = singleton_nodes_by_id.get(junction_id) or []
    if singleton_candidates:
        representative = singleton_candidates[0]
        return ResolvedJunctionGroup(
            junction_id=junction_id,
            group_nodes=[representative],
            representative=representative,
            resolution_mode="single_node_fallback",
            reason=None,
            detail=None,
        )

    return ResolvedJunctionGroup(
        junction_id=junction_id,
        group_nodes=[],
        representative=None,
        resolution_mode="not_found",
        reason=junction_not_found_reason,
        detail=f"junction_id='{junction_id}' has neither mainnodeid group nor singleton fallback node.",
    )


def collect_semantic_junction_ids(
    *,
    nodes_by_mainnodeid: dict[str, list[Any]],
    singleton_nodes_by_id: dict[str, list[Any]],
    nodes_features: list[Any],
) -> list[str]:
    semantic_junction_ids: list[str] = []
    candidate_ids = sorted(set(nodes_by_mainnodeid.keys()) | set(singleton_nodes_by_id.keys()))
    for junction_id in candidate_ids:
        group_nodes = nodes_by_mainnodeid.get(junction_id) or singleton_nodes_by_id.get(junction_id) or []
        if any(
            normalize_id(nodes_features[getattr(record, "output_index")].properties.get("kind_2")) not in {None, "0"}
            for record in group_nodes
        ):
            semantic_junction_ids.append(junction_id)
    return semantic_junction_ids
