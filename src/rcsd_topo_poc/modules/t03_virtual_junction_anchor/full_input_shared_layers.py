from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from numbers import Integral
from typing import Any

from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t00_utility_toolbox.common import sort_patch_key
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import (
    LayerFeature,
    read_vector_layer,
)


ALLOWED_KIND_2_VALUES = frozenset({4, 2048})


@dataclass(frozen=True)
class SpatialFeatureIndex:
    all_features: tuple[LayerFeature, ...]
    indexed_features: tuple[LayerFeature, ...]
    tree: STRtree | None
    geometry_to_feature: dict[int, LayerFeature]
    feature_order_by_object_id: dict[int, int]


@dataclass(frozen=True)
class SharedFullInputLayers:
    nodes: tuple[LayerFeature, ...]
    roads: tuple[LayerFeature, ...]
    drivezones: tuple[LayerFeature, ...]
    rcsd_roads: tuple[LayerFeature, ...]
    rcsd_nodes: tuple[LayerFeature, ...]
    node_spatial_index: SpatialFeatureIndex
    road_spatial_index: SpatialFeatureIndex
    drivezone_spatial_index: SpatialFeatureIndex
    rcsd_road_spatial_index: SpatialFeatureIndex
    rcsd_node_spatial_index: SpatialFeatureIndex
    node_id_to_feature: dict[str, LayerFeature]
    node_id_to_features: dict[str, tuple[LayerFeature, ...]]
    rcsd_node_id_to_feature: dict[str, LayerFeature]
    rcsd_node_id_to_features: dict[str, tuple[LayerFeature, ...]]
    mainnodeid_to_member_features: dict[str, tuple[LayerFeature, ...]]
    rcsd_mainnodeid_to_member_features: dict[str, tuple[LayerFeature, ...]]
    target_group_nodes_by_group_id: dict[str, tuple[LayerFeature, ...]]
    case_id_to_representative_feature: dict[str, LayerFeature]
    node_id_to_roads: dict[str, tuple[LayerFeature, ...]]
    rcsd_node_id_to_roads: dict[str, tuple[LayerFeature, ...]]


def stable_case_ids(case_ids: list[str]) -> list[str]:
    return sorted({str(case_id) for case_id in case_ids}, key=sort_patch_key)


def normalize_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def coerce_int(value: object) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def feature_id(feature: LayerFeature) -> str | None:
    return normalize_text(feature.properties.get("id"))


def feature_mainnodeid(feature: LayerFeature) -> str | None:
    return normalize_text(feature.properties.get("mainnodeid"))


def feature_snodeid(feature: LayerFeature) -> str | None:
    return normalize_text(feature.properties.get("snodeid"))


def feature_enodeid(feature: LayerFeature) -> str | None:
    return normalize_text(feature.properties.get("enodeid"))


def has_geometry(feature: LayerFeature) -> bool:
    geometry = feature.geometry
    return geometry is not None and not geometry.is_empty


def intersects(feature: LayerFeature, geometry: BaseGeometry) -> bool:
    return has_geometry(feature) and bool(feature.geometry.intersects(geometry))


def _build_spatial_index(features: tuple[LayerFeature, ...]) -> SpatialFeatureIndex:
    indexed_features = tuple(feature for feature in features if has_geometry(feature))
    indexed_geometries = tuple(feature.geometry for feature in indexed_features)
    return SpatialFeatureIndex(
        all_features=features,
        indexed_features=indexed_features,
        tree=STRtree(indexed_geometries) if indexed_geometries else None,
        geometry_to_feature={
            id(geometry): feature
            for geometry, feature in zip(indexed_geometries, indexed_features)
        },
        feature_order_by_object_id={
            id(feature): index for index, feature in enumerate(features)
        },
    )


def _query_index_candidates(
    spatial_index: SpatialFeatureIndex,
    window: BaseGeometry,
) -> tuple[LayerFeature, ...]:
    if spatial_index.tree is None:
        return ()
    raw_matches = spatial_index.tree.query(window)
    if len(raw_matches) == 0:
        return ()
    first = raw_matches[0]
    if isinstance(first, Integral):
        return tuple(
            spatial_index.indexed_features[int(index)]
            for index in raw_matches
        )
    return tuple(
        spatial_index.geometry_to_feature[id(geometry)]
        for geometry in raw_matches
    )


def _ordered_unique_features(
    candidates: list[LayerFeature],
    *,
    feature_order_by_object_id: dict[int, int],
) -> list[LayerFeature]:
    ordered_pairs: list[tuple[int, LayerFeature]] = []
    seen_object_ids: set[int] = set()
    for feature in candidates:
        object_id = id(feature)
        if object_id in seen_object_ids:
            continue
        seen_object_ids.add(object_id)
        ordered_pairs.append((feature_order_by_object_id[object_id], feature))
    ordered_pairs.sort(key=lambda item: item[0])
    return [feature for _, feature in ordered_pairs]


def _build_feature_lookup(
    features: tuple[LayerFeature, ...],
    *,
    key_getter,
) -> tuple[dict[str, LayerFeature], dict[str, tuple[LayerFeature, ...]]]:
    grouped: dict[str, list[LayerFeature]] = defaultdict(list)
    first_feature_by_key: dict[str, LayerFeature] = {}
    for feature in features:
        if not has_geometry(feature):
            continue
        key = key_getter(feature)
        if key is None:
            continue
        grouped[key].append(feature)
        first_feature_by_key.setdefault(key, feature)
    return (
        first_feature_by_key,
        {key: tuple(value) for key, value in grouped.items()},
    )


def _build_target_group_cache(
    nodes: tuple[LayerFeature, ...],
) -> tuple[dict[str, tuple[LayerFeature, ...]], dict[str, tuple[LayerFeature, ...]]]:
    grouped_by_mainnodeid: dict[str, list[LayerFeature]] = defaultdict(list)
    grouped_by_target_group_id: dict[str, list[LayerFeature]] = defaultdict(list)
    for feature in nodes:
        if not has_geometry(feature):
            continue
        mainnodeid = feature_mainnodeid(feature)
        node_id = feature_id(feature)
        if mainnodeid is not None:
            grouped_by_mainnodeid[mainnodeid].append(feature)
        target_group_id = mainnodeid or node_id
        if target_group_id is not None:
            grouped_by_target_group_id[target_group_id].append(feature)
    return (
        {key: tuple(value) for key, value in grouped_by_mainnodeid.items()},
        {key: tuple(value) for key, value in grouped_by_target_group_id.items()},
    )


def _build_representative_feature_cache(
    nodes: tuple[LayerFeature, ...],
) -> dict[str, LayerFeature]:
    representatives: dict[str, LayerFeature] = {}
    for feature in nodes:
        if not has_geometry(feature):
            continue
        node_id = feature_id(feature)
        if node_id is not None:
            representatives.setdefault(node_id, feature)
    for feature in nodes:
        if not has_geometry(feature):
            continue
        mainnodeid = feature_mainnodeid(feature)
        if mainnodeid is not None:
            representatives.setdefault(mainnodeid, feature)
    return representatives


def _build_road_adjacency(
    roads: tuple[LayerFeature, ...],
) -> dict[str, tuple[LayerFeature, ...]]:
    adjacency: dict[str, list[LayerFeature]] = defaultdict(list)
    for feature in roads:
        seen_node_ids: set[str] = set()
        for node_id in (feature_snodeid(feature), feature_enodeid(feature)):
            if node_id is None or node_id in seen_node_ids:
                continue
            seen_node_ids.add(node_id)
            adjacency[node_id].append(feature)
    return {
        node_id: tuple(node_roads)
        for node_id, node_roads in adjacency.items()
    }


def load_shared_nodes(*, nodes_path) -> tuple[LayerFeature, ...]:
    return tuple(read_vector_layer(nodes_path).features)


def load_shared_layers(
    *,
    nodes: tuple[LayerFeature, ...],
    roads_path,
    drivezone_path,
    rcsdroad_path,
    rcsdnode_path,
) -> SharedFullInputLayers:
    roads = tuple(read_vector_layer(roads_path).features)
    drivezones = tuple(read_vector_layer(drivezone_path).features)
    rcsd_roads = tuple(read_vector_layer(rcsdroad_path).features)
    rcsd_nodes = tuple(read_vector_layer(rcsdnode_path).features)
    node_id_to_feature, node_id_to_features = _build_feature_lookup(
        nodes,
        key_getter=feature_id,
    )
    rcsd_node_id_to_feature, rcsd_node_id_to_features = _build_feature_lookup(
        rcsd_nodes,
        key_getter=feature_id,
    )
    mainnodeid_to_member_features, target_group_nodes_by_group_id = _build_target_group_cache(nodes)
    rcsd_mainnodeid_to_member_features, _ = _build_target_group_cache(rcsd_nodes)
    return SharedFullInputLayers(
        nodes=nodes,
        roads=roads,
        drivezones=drivezones,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        node_spatial_index=_build_spatial_index(nodes),
        road_spatial_index=_build_spatial_index(roads),
        drivezone_spatial_index=_build_spatial_index(drivezones),
        rcsd_road_spatial_index=_build_spatial_index(rcsd_roads),
        rcsd_node_spatial_index=_build_spatial_index(rcsd_nodes),
        node_id_to_feature=node_id_to_feature,
        node_id_to_features=node_id_to_features,
        rcsd_node_id_to_feature=rcsd_node_id_to_feature,
        rcsd_node_id_to_features=rcsd_node_id_to_features,
        mainnodeid_to_member_features=mainnodeid_to_member_features,
        rcsd_mainnodeid_to_member_features=rcsd_mainnodeid_to_member_features,
        target_group_nodes_by_group_id=target_group_nodes_by_group_id,
        case_id_to_representative_feature=_build_representative_feature_cache(nodes),
        node_id_to_roads=_build_road_adjacency(roads),
        rcsd_node_id_to_roads=_build_road_adjacency(rcsd_roads),
    )


def is_auto_candidate(feature: LayerFeature) -> bool:
    node_id = feature_id(feature)
    mainnodeid = feature_mainnodeid(feature)
    kind_2 = coerce_int(feature.properties.get("kind_2"))
    has_evd = normalize_text(feature.properties.get("has_evd"))
    is_anchor = normalize_text(feature.properties.get("is_anchor"))
    is_representative = (mainnodeid is not None and node_id == mainnodeid) or (
        mainnodeid is None and node_id is not None
    )
    return (
        is_representative
        and has_evd == "yes"
        and is_anchor == "no"
        and kind_2 in ALLOWED_KIND_2_VALUES
    )


def discover_candidate_case_ids(nodes: tuple[LayerFeature, ...]) -> list[str]:
    discovered = []
    for feature in nodes:
        if not is_auto_candidate(feature):
            continue
        case_id = feature_mainnodeid(feature) or feature_id(feature)
        if case_id is not None:
            discovered.append(case_id)
    return stable_case_ids(discovered)


def resolve_representative_feature(
    nodes_or_shared_layers: tuple[LayerFeature, ...] | SharedFullInputLayers,
    case_id: str,
) -> LayerFeature:
    if isinstance(nodes_or_shared_layers, SharedFullInputLayers):
        representative_feature = nodes_or_shared_layers.case_id_to_representative_feature.get(case_id)
        if representative_feature is not None:
            return representative_feature
        nodes = nodes_or_shared_layers.nodes
    else:
        nodes = nodes_or_shared_layers
    for feature in nodes:
        if feature_id(feature) == case_id and has_geometry(feature):
            return feature
    for feature in nodes:
        if feature_mainnodeid(feature) == case_id and has_geometry(feature):
            return feature
    raise ValueError(f"representative node not found for case_id={case_id}")


def selection_window(
    representative_feature: LayerFeature,
    *,
    buffer_m: float,
    patch_size_m: float,
) -> BaseGeometry:
    geometry = representative_feature.geometry
    if geometry is None or geometry.is_empty:
        raise ValueError("representative node geometry is empty")
    min_x, min_y, max_x, max_y = geometry.bounds
    center_x = (min_x + max_x) / 2.0
    center_y = (min_y + max_y) / 2.0
    half_span = max(float(buffer_m or 0.0), float(patch_size_m or 0.0) / 2.0, 1.0)
    return box(center_x - half_span, center_y - half_span, center_x + half_span, center_y + half_span)


def collect_case_features(
    *,
    shared_layers: SharedFullInputLayers,
    case_id: str,
    buffer_m: float,
    patch_size_m: float,
) -> dict[str, list[LayerFeature] | BaseGeometry]:
    representative_feature = resolve_representative_feature(shared_layers, case_id)
    window = selection_window(
        representative_feature,
        buffer_m=buffer_m,
        patch_size_m=patch_size_m,
    )
    target_group_id = feature_mainnodeid(representative_feature) or case_id

    target_group_nodes = list(shared_layers.target_group_nodes_by_group_id.get(target_group_id, ()))
    if not target_group_nodes:
        target_group_nodes = [representative_feature]

    target_node_ids = {feature_id(feature) for feature in target_group_nodes if feature_id(feature) is not None}
    road_candidates: list[LayerFeature] = []
    for node_id in target_node_ids:
        road_candidates.extend(shared_layers.node_id_to_roads.get(node_id, ()))
    road_candidates.extend(
        feature
        for feature in _query_index_candidates(shared_layers.road_spatial_index, window)
        if intersects(feature, window)
    )
    selected_roads = _ordered_unique_features(
        road_candidates,
        feature_order_by_object_id=shared_layers.road_spatial_index.feature_order_by_object_id,
    )
    referenced_node_ids = {
        value
        for feature in selected_roads
        for value in (feature_snodeid(feature), feature_enodeid(feature))
        if value is not None
    }

    node_candidates: list[LayerFeature] = []
    for node_id in referenced_node_ids | target_node_ids:
        node_candidates.extend(shared_layers.node_id_to_features.get(node_id, ()))
    node_candidates.extend(target_group_nodes)
    node_candidates.extend(
        feature
        for feature in _query_index_candidates(shared_layers.node_spatial_index, window)
        if intersects(feature, window)
    )
    selected_nodes = _ordered_unique_features(
        node_candidates,
        feature_order_by_object_id=shared_layers.node_spatial_index.feature_order_by_object_id,
    )

    rcsd_node_candidates: list[LayerFeature] = []
    rcsd_node_candidates.extend(shared_layers.rcsd_mainnodeid_to_member_features.get(target_group_id, ()))
    rcsd_node_candidates.extend(shared_layers.rcsd_node_id_to_features.get(case_id, ()))
    rcsd_node_candidates.extend(
        feature
        for feature in _query_index_candidates(shared_layers.rcsd_node_spatial_index, window)
        if intersects(feature, window)
    )
    selected_rcsd_nodes = _ordered_unique_features(
        rcsd_node_candidates,
        feature_order_by_object_id=shared_layers.rcsd_node_spatial_index.feature_order_by_object_id,
    )
    selected_rcsd_node_ids = {
        feature_id(feature)
        for feature in selected_rcsd_nodes
        if feature_id(feature) is not None
    }
    rcsd_road_candidates: list[LayerFeature] = []
    for node_id in selected_rcsd_node_ids:
        rcsd_road_candidates.extend(shared_layers.rcsd_node_id_to_roads.get(node_id, ()))
    rcsd_road_candidates.extend(
        feature
        for feature in _query_index_candidates(shared_layers.rcsd_road_spatial_index, window)
        if intersects(feature, window)
    )
    selected_rcsd_roads = _ordered_unique_features(
        rcsd_road_candidates,
        feature_order_by_object_id=shared_layers.rcsd_road_spatial_index.feature_order_by_object_id,
    )

    selected_drivezones = _ordered_unique_features(
        [
            feature
            for feature in _query_index_candidates(shared_layers.drivezone_spatial_index, window)
            if intersects(feature, window)
        ],
        feature_order_by_object_id=shared_layers.drivezone_spatial_index.feature_order_by_object_id,
    )
    if not selected_drivezones:
        drivezone_candidates = list(shared_layers.drivezone_spatial_index.indexed_features)
        if not drivezone_candidates:
            raise ValueError(f"drivezone layer is empty for case_id={case_id}")
        representative_geometry = representative_feature.geometry
        assert representative_geometry is not None
        selected_drivezones = [
            min(
                drivezone_candidates,
                key=lambda feature: float(feature.geometry.distance(representative_geometry)),
            )
        ]

    return {
        "selection_window": window,
        "nodes": selected_nodes,
        "roads": selected_roads,
        "drivezones": selected_drivezones,
        "rcsd_roads": selected_rcsd_roads,
        "rcsd_nodes": selected_rcsd_nodes,
    }


def as_write_features(features: list[LayerFeature]) -> list[dict[str, Any]]:
    return [
        {
            "properties": dict(feature.properties),
            "geometry": feature.geometry,
        }
        for feature in features
    ]


__all__ = [
    "ALLOWED_KIND_2_VALUES",
    "SharedFullInputLayers",
    "as_write_features",
    "coerce_int",
    "collect_case_features",
    "discover_candidate_case_ids",
    "feature_enodeid",
    "feature_id",
    "feature_mainnodeid",
    "feature_snodeid",
    "has_geometry",
    "intersects",
    "is_auto_candidate",
    "load_shared_layers",
    "load_shared_nodes",
    "normalize_text",
    "resolve_representative_feature",
    "selection_window",
    "stable_case_ids",
]
