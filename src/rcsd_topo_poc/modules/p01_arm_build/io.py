from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

import fiona
from fiona.errors import DriverError
from shapely.geometry import mapping, shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p01_arm_build.models import (
    DatasetInput,
    LoadedDataset,
    NodeRecord,
    RoadRecord,
    VectorLayer,
    to_plain,
)


def normalise_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def _normalise_properties(properties: Any) -> dict[str, Any]:
    return {str(k).lower(): v for k, v in dict(properties or {}).items()}


def _first_present(properties: dict[str, Any], names: Iterable[str]) -> Any:
    for name in names:
        key = name.lower()
        if key in properties:
            return properties[key]
    return None


def _layer_info(path: Path, feature_count: int, schema_properties: tuple[str, ...], src: Any) -> VectorLayer:
    return VectorLayer(
        path=path,
        crs=getattr(src, "crs", None),
        crs_wkt=getattr(src, "crs_wkt", None),
        schema_properties=schema_properties,
        feature_count=feature_count,
    )


def read_nodes(path: Path) -> tuple[dict[str, NodeRecord], VectorLayer]:
    nodes: dict[str, NodeRecord] = {}
    with fiona.open(path) as src:
        schema_properties = tuple(str(k).lower() for k in src.schema.get("properties", {}).keys())
        feature_count = 0
        for feature in src:
            feature_count += 1
            properties = _normalise_properties(feature.get("properties"))
            node_id = normalise_id(_first_present(properties, ("id", "nodeid", "node_id")))
            if not node_id:
                raise ValueError(f"Node feature without id in {path}")
            geometry = shape(feature["geometry"])
            mainnodeid = normalise_id(_first_present(properties, ("mainnodeid", "main_node_id"))) or None
            kind = normalise_id(_first_present(properties, ("kind", "kind_2"))) or None
            nodes[node_id] = NodeRecord(
                node_id=node_id,
                mainnodeid=mainnodeid,
                kind=kind,
                geometry=geometry,
                properties=properties,
            )
        layer = _layer_info(path, feature_count, schema_properties, src)
    return nodes, layer


def read_roads(path: Path) -> tuple[dict[str, RoadRecord], VectorLayer]:
    roads: dict[str, RoadRecord] = {}
    with fiona.open(path) as src:
        schema_properties = tuple(str(k).lower() for k in src.schema.get("properties", {}).keys())
        feature_count = 0
        for feature in src:
            feature_count += 1
            properties = _normalise_properties(feature.get("properties"))
            road_id = normalise_id(_first_present(properties, ("id", "roadid", "road_id")))
            snodeid = normalise_id(_first_present(properties, ("snodeid", "snode_id", "startnodeid")))
            enodeid = normalise_id(_first_present(properties, ("enodeid", "enode_id", "endnodeid")))
            if not road_id or not snodeid or not enodeid:
                raise ValueError(f"Road feature without id/snodeid/enodeid in {path}")
            direction_value = _first_present(properties, ("direction",))
            try:
                direction = int(direction_value) if direction_value is not None and str(direction_value).strip() != "" else None
            except (TypeError, ValueError):
                direction = None
            formway = normalise_id(_first_present(properties, ("formway",))) or None
            roads[road_id] = RoadRecord(
                road_id=road_id,
                snodeid=snodeid,
                enodeid=enodeid,
                direction=direction,
                formway=formway,
                geometry=shape(feature["geometry"]),
                properties=properties,
            )
        layer = _layer_info(path, feature_count, schema_properties, src)
    return roads, layer


def load_dataset(dataset_input: DatasetInput) -> LoadedDataset:
    nodes, node_layer = read_nodes(dataset_input.nodes_path)
    roads, road_layer = read_roads(dataset_input.roads_path)
    return LoadedDataset(
        dataset=dataset_input.dataset,
        nodes=nodes,
        roads=roads,
        node_layer=node_layer,
        road_layer=road_layer,
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_plain(payload), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def _string_properties(properties: dict[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in properties.items():
        if isinstance(value, (dict, list, tuple)):
            result[str(key)[:32]] = json.dumps(to_plain(value), ensure_ascii=False)
        elif value is None:
            result[str(key)[:32]] = ""
        else:
            result[str(key)[:32]] = str(value)
    return result


def _schema_for(records: list[tuple[BaseGeometry, dict[str, Any]]], geometry_type: str) -> dict[str, Any]:
    keys: set[str] = set()
    for _, properties in records:
        keys.update(str(key)[:32] for key in properties.keys())
    if not keys:
        keys.add("empty")
    return {
        "geometry": geometry_type,
        "properties": {key: "str:254" for key in sorted(keys)},
    }


def write_gpkg_layers(
    path: Path,
    *,
    layers: list[tuple[str, str, list[tuple[BaseGeometry, dict[str, Any]]]]],
    crs: Any,
    crs_wkt: str | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        try:
            path.unlink()
        except PermissionError as exc:
            raise RuntimeError(
                f"Cannot overwrite existing GPKG {path}. Close any GIS/viewer process using this file, "
                "delete the old output, or rerun with a new --run-id."
            ) from exc
    for layer_name, geometry_type, records in layers:
        schema = _schema_for(records, geometry_type)
        kwargs: dict[str, Any] = {
            "driver": "GPKG",
            "schema": schema,
            "layer": layer_name,
        }
        if crs_wkt:
            kwargs["crs_wkt"] = crs_wkt
        elif crs:
            kwargs["crs"] = crs
        try:
            with fiona.open(path, "w", **kwargs) as sink:
                for geometry, properties in records:
                    props = _string_properties(properties)
                    for key in schema["properties"]:
                        props.setdefault(key, "")
                    sink.write({"geometry": mapping(geometry), "properties": props})
        except DriverError as exc:
            raise RuntimeError(f"Failed to write GPKG layer {layer_name} at {path}: {exc}") from exc
