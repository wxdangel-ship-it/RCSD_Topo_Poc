from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from numbers import Integral
from pathlib import Path
from typing import Any

from shapely.geometry import GeometryCollection
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t00_utility_toolbox.common import TARGET_CRS, sort_patch_key
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import (
    LoadedFeature,
    LoadedLayer,
    normalize_id,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import (
    ParsedNode,
    ParsedRoad,
    _coerce_int,
    _load_layer_filtered,
    _parse_nodes,
    _parse_rc_nodes,
    _parse_roads,
    _resolve_group,
)


T04_ALLOWED_KIND_2_VALUES = frozenset({8, 16, 128})


@dataclass(frozen=True)
class FeatureSpatialIndex:
    indexed_items: tuple[Any, ...]
    tree: STRtree | None
    geometry_to_item: dict[int, Any]


@dataclass(frozen=True)
class T04SharedFullInputLayers:
    node_layer: LoadedLayer
    road_layer: LoadedLayer
    drivezone_layer: LoadedLayer
    divstripzone_layer: LoadedLayer
    rcsdroad_layer: LoadedLayer
    rcsdnode_layer: LoadedLayer
    nodes: tuple[ParsedNode, ...]
    roads: tuple[ParsedRoad, ...]
    drivezone_features: tuple[LoadedFeature, ...]
    divstrip_features: tuple[LoadedFeature, ...]
    rcsd_roads: tuple[ParsedRoad, ...]
    rcsd_nodes: tuple[ParsedNode, ...]
    node_index: FeatureSpatialIndex
    road_index: FeatureSpatialIndex
    drivezone_index: FeatureSpatialIndex
    divstrip_index: FeatureSpatialIndex
    rcsdroad_index: FeatureSpatialIndex
    rcsdnode_index: FeatureSpatialIndex
    node_id_to_roads: dict[str, tuple[ParsedRoad, ...]]
    rcsd_node_id_to_roads: dict[str, tuple[ParsedRoad, ...]]

    def layer_manifest(self) -> dict[str, Any]:
        return {
            "target_crs": str(TARGET_CRS),
            "layers": {
                "nodes": _layer_summary(self.node_layer, len(self.nodes)),
                "roads": _layer_summary(self.road_layer, len(self.roads)),
                "drivezone": _layer_summary(self.drivezone_layer, len(self.drivezone_features)),
                "divstripzone": _layer_summary(self.divstripzone_layer, len(self.divstrip_features)),
                "rcsdroad": _layer_summary(self.rcsdroad_layer, len(self.rcsd_roads)),
                "rcsdnode": _layer_summary(self.rcsdnode_layer, len(self.rcsd_nodes)),
            },
            "spatial_indexes": {
                "nodes": len(self.node_index.indexed_items),
                "roads": len(self.road_index.indexed_items),
                "drivezone": len(self.drivezone_index.indexed_items),
                "divstripzone": len(self.divstrip_index.indexed_items),
                "rcsdroad": len(self.rcsdroad_index.indexed_items),
                "rcsdnode": len(self.rcsdnode_index.indexed_items),
            },
        }


def normalize_text(value: object) -> str | None:
    return normalize_id(value)


def stable_case_ids(case_ids: list[str]) -> list[str]:
    return sorted({str(case_id) for case_id in case_ids}, key=sort_patch_key)


def _layer_summary(layer: LoadedLayer, parsed_count: int) -> dict[str, Any]:
    return {
        "feature_count": len(layer.features),
        "parsed_count": int(parsed_count),
        "source_crs": str(layer.source_crs),
        "crs_source": layer.crs_source,
        "target_crs": str(TARGET_CRS),
    }


def _build_spatial_index(items: tuple[Any, ...]) -> FeatureSpatialIndex:
    indexed = tuple(
        item
        for item in items
        if getattr(item, "geometry", None) is not None and not item.geometry.is_empty
    )
    geoms = tuple(item.geometry for item in indexed)
    return FeatureSpatialIndex(
        indexed_items=indexed,
        tree=STRtree(geoms) if geoms else None,
        geometry_to_item={id(geom): item for geom, item in zip(geoms, indexed)},
    )


def query_spatial_index(index: FeatureSpatialIndex, window: BaseGeometry) -> tuple[Any, ...]:
    if index.tree is None or window is None or window.is_empty:
        return ()
    raw = index.tree.query(window)
    if len(raw) == 0:
        return ()
    first = raw[0]
    if isinstance(first, Integral):
        return tuple(
            item
            for item in (index.indexed_items[int(value)] for value in raw)
            if item.geometry is not None and item.geometry.intersects(window)
        )
    return tuple(
        item
        for item in (index.geometry_to_item[id(geom)] for geom in raw)
        if item.geometry is not None and item.geometry.intersects(window)
    )


def _build_road_adjacency(roads: tuple[ParsedRoad, ...]) -> dict[str, tuple[ParsedRoad, ...]]:
    grouped: dict[str, list[ParsedRoad]] = defaultdict(list)
    for road in roads:
        grouped[road.snodeid].append(road)
        grouped[road.enodeid].append(road)
    return {key: tuple(value) for key, value in grouped.items()}


def _load_layer(path: str | Path, *, layer_name: str | None, crs_override: str | None) -> LoadedLayer:
    return _load_layer_filtered(
        path,
        layer_name=layer_name,
        crs_override=crs_override,
        allow_null_geometry=False,
    )


def load_shared_full_input_layers(
    *,
    nodes_path: str | Path,
    roads_path: str | Path,
    drivezone_path: str | Path,
    divstripzone_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    nodes_layer: str | None = None,
    roads_layer: str | None = None,
    drivezone_layer: str | None = None,
    divstripzone_layer: str | None = None,
    rcsdroad_layer: str | None = None,
    rcsdnode_layer: str | None = None,
    nodes_crs: str | None = None,
    roads_crs: str | None = None,
    drivezone_crs: str | None = None,
    divstripzone_crs: str | None = None,
    rcsdroad_crs: str | None = None,
    rcsdnode_crs: str | None = None,
) -> T04SharedFullInputLayers:
    node_layer_data = _load_layer(nodes_path, layer_name=nodes_layer, crs_override=nodes_crs)
    road_layer_data = _load_layer(roads_path, layer_name=roads_layer, crs_override=roads_crs)
    drivezone_layer_data = _load_layer(drivezone_path, layer_name=drivezone_layer, crs_override=drivezone_crs)
    divstripzone_layer_data = _load_layer(divstripzone_path, layer_name=divstripzone_layer, crs_override=divstripzone_crs)
    rcsdroad_layer_data = _load_layer(rcsdroad_path, layer_name=rcsdroad_layer, crs_override=rcsdroad_crs)
    rcsdnode_layer_data = _load_layer(rcsdnode_path, layer_name=rcsdnode_layer, crs_override=rcsdnode_crs)

    nodes = tuple(_parse_nodes(node_layer_data, require_anchor_fields=True))
    roads = tuple(_parse_roads(road_layer_data, label="Road"))
    rcsd_roads = tuple(_parse_roads(rcsdroad_layer_data, label="RCSDRoad"))
    rcsd_nodes = tuple(_parse_rc_nodes(rcsdnode_layer_data))
    drivezones = tuple(drivezone_layer_data.features)
    divstrips = tuple(divstripzone_layer_data.features)
    return T04SharedFullInputLayers(
        node_layer=node_layer_data,
        road_layer=road_layer_data,
        drivezone_layer=drivezone_layer_data,
        divstripzone_layer=divstripzone_layer_data,
        rcsdroad_layer=rcsdroad_layer_data,
        rcsdnode_layer=rcsdnode_layer_data,
        nodes=nodes,
        roads=roads,
        drivezone_features=drivezones,
        divstrip_features=divstrips,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        node_index=_build_spatial_index(nodes),
        road_index=_build_spatial_index(roads),
        drivezone_index=_build_spatial_index(drivezones),
        divstrip_index=_build_spatial_index(divstrips),
        rcsdroad_index=_build_spatial_index(rcsd_roads),
        rcsdnode_index=_build_spatial_index(rcsd_nodes),
        node_id_to_roads=_build_road_adjacency(roads),
        rcsd_node_id_to_roads=_build_road_adjacency(rcsd_roads),
    )


def _is_representative_candidate(node: ParsedNode) -> bool:
    node_id = normalize_text(node.node_id)
    mainnodeid = normalize_text(node.mainnodeid)
    if node_id is None:
        return False
    return (mainnodeid is not None and node_id == mainnodeid) or mainnodeid is None


def discover_candidate_case_ids(layers: T04SharedFullInputLayers) -> list[str]:
    case_ids: list[str] = []
    for node in layers.nodes:
        node_id = normalize_text(node.node_id)
        mainnodeid = normalize_text(node.mainnodeid)
        kind = _coerce_int(node.kind)
        if (
            node_id is not None
            and _is_representative_candidate(node)
            and normalize_text(node.has_evd) == "yes"
            and normalize_text(node.is_anchor) == "no"
            and (node.kind_2 in T04_ALLOWED_KIND_2_VALUES or kind == 128)
        ):
            case_ids.append(mainnodeid or node_id)
    return stable_case_ids(case_ids)


def select_candidate_case_ids(
    *,
    discovered_case_ids: list[str],
    max_cases: int | None,
) -> list[str]:
    ordered = stable_case_ids(discovered_case_ids)
    return ordered[:max_cases] if max_cases is not None else ordered


def _ordered_by_feature_index(items: tuple[Any, ...]) -> tuple[Any, ...]:
    return tuple(sorted(items, key=lambda item: getattr(item, "feature_index", 0)))


def collect_case_features(
    *,
    layers: T04SharedFullInputLayers,
    case_id: str,
    local_query_buffer_m: float,
) -> dict[str, Any]:
    representative, group_nodes = _resolve_group(mainnodeid=str(case_id), nodes=list(layers.nodes))
    member_ids = {node.node_id for node in group_nodes}
    seed_roads = tuple(
        road
        for node_id in member_ids
        for road in layers.node_id_to_roads.get(node_id, ())
    )
    seed_geometries = [node.geometry for node in group_nodes]
    seed_geometries.extend(road.geometry for road in seed_roads if road.geometry is not None and not road.geometry.is_empty)
    seed = unary_union(seed_geometries) if seed_geometries else representative.geometry
    if seed is None or seed.is_empty:
        seed = GeometryCollection()
    selection_window = seed.buffer(max(float(local_query_buffer_m), 1.0), join_style=2)
    selected_nodes = {
        item.node_id: item
        for item in query_spatial_index(layers.node_index, selection_window)
        if isinstance(item, ParsedNode)
    }
    for node in group_nodes:
        selected_nodes[node.node_id] = node
    selected_roads = {
        item.road_id: item
        for item in query_spatial_index(layers.road_index, selection_window)
        if isinstance(item, ParsedRoad)
    }
    for road in seed_roads:
        selected_roads[road.road_id] = road
    selected_rcsd_roads = {
        item.road_id: item
        for item in query_spatial_index(layers.rcsdroad_index, selection_window)
        if isinstance(item, ParsedRoad)
    }
    selected_rcsd_nodes = {
        item.node_id: item
        for item in query_spatial_index(layers.rcsdnode_index, selection_window)
        if isinstance(item, ParsedNode)
    }
    drivezones = _ordered_by_feature_index(query_spatial_index(layers.drivezone_index, selection_window))
    divstrips = _ordered_by_feature_index(query_spatial_index(layers.divstrip_index, selection_window))
    return {
        "representative_node": representative,
        "group_nodes": tuple(group_nodes),
        "selection_window": selection_window,
        "nodes": _ordered_by_feature_index(tuple(selected_nodes.values())),
        "roads": _ordered_by_feature_index(tuple(selected_roads.values())),
        "drivezone_features": drivezones,
        "divstrip_features": divstrips,
        "rcsd_roads": _ordered_by_feature_index(tuple(selected_rcsd_roads.values())),
        "rcsd_nodes": _ordered_by_feature_index(tuple(selected_rcsd_nodes.values())),
        "selected_counts": {
            "nodes": len(selected_nodes),
            "roads": len(selected_roads),
            "drivezone": len(drivezones),
            "divstripzone": len(divstrips),
            "rcsdroad": len(selected_rcsd_roads),
            "rcsdnode": len(selected_rcsd_nodes),
        },
    }


__all__ = [
    "T04SharedFullInputLayers",
    "collect_case_features",
    "discover_candidate_case_ids",
    "load_shared_full_input_layers",
    "normalize_text",
    "select_candidate_case_ids",
    "stable_case_ids",
]
