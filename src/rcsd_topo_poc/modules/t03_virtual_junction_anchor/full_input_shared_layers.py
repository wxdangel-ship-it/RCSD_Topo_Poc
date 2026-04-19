from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry import box
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t00_utility_toolbox.common import sort_patch_key
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import (
    LayerFeature,
    read_vector_layer,
)


ALLOWED_KIND_2_VALUES = frozenset({4, 2048})


@dataclass(frozen=True)
class SharedFullInputLayers:
    nodes: tuple[LayerFeature, ...]
    roads: tuple[LayerFeature, ...]
    drivezones: tuple[LayerFeature, ...]
    rcsd_roads: tuple[LayerFeature, ...]
    rcsd_nodes: tuple[LayerFeature, ...]


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
    return SharedFullInputLayers(
        nodes=nodes,
        roads=tuple(read_vector_layer(roads_path).features),
        drivezones=tuple(read_vector_layer(drivezone_path).features),
        rcsd_roads=tuple(read_vector_layer(rcsdroad_path).features),
        rcsd_nodes=tuple(read_vector_layer(rcsdnode_path).features),
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


def resolve_representative_feature(nodes: tuple[LayerFeature, ...], case_id: str) -> LayerFeature:
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
    representative_feature = resolve_representative_feature(shared_layers.nodes, case_id)
    window = selection_window(
        representative_feature,
        buffer_m=buffer_m,
        patch_size_m=patch_size_m,
    )
    target_group_id = feature_mainnodeid(representative_feature) or case_id

    target_group_nodes = [
        feature
        for feature in shared_layers.nodes
        if (feature_mainnodeid(feature) or feature_id(feature)) == target_group_id and has_geometry(feature)
    ]
    if not target_group_nodes:
        target_group_nodes = [representative_feature]

    target_node_ids = {feature_id(feature) for feature in target_group_nodes if feature_id(feature) is not None}
    selected_roads = [
        feature
        for feature in shared_layers.roads
        if (
            feature_snodeid(feature) in target_node_ids
            or feature_enodeid(feature) in target_node_ids
            or intersects(feature, window)
        )
    ]
    referenced_node_ids = {
        value
        for feature in selected_roads
        for value in (feature_snodeid(feature), feature_enodeid(feature))
        if value is not None
    }

    selected_nodes = []
    for feature in shared_layers.nodes:
        node_id = feature_id(feature)
        if node_id is None or not has_geometry(feature):
            continue
        if (
            node_id in referenced_node_ids
            or node_id in target_node_ids
            or feature_mainnodeid(feature) == target_group_id
            or intersects(feature, window)
        ):
            selected_nodes.append(feature)

    selected_rcsd_nodes = [
        feature
        for feature in shared_layers.rcsd_nodes
        if (
            has_geometry(feature)
            and (
                intersects(feature, window)
                or feature_mainnodeid(feature) == target_group_id
                or feature_id(feature) == case_id
            )
        )
    ]
    selected_rcsd_node_ids = {
        feature_id(feature)
        for feature in selected_rcsd_nodes
        if feature_id(feature) is not None
    }
    selected_rcsd_roads = [
        feature
        for feature in shared_layers.rcsd_roads
        if (
            feature_snodeid(feature) in selected_rcsd_node_ids
            or feature_enodeid(feature) in selected_rcsd_node_ids
            or intersects(feature, window)
        )
    ]

    selected_drivezones = [
        feature
        for feature in shared_layers.drivezones
        if intersects(feature, window)
    ]
    if not selected_drivezones:
        drivezone_candidates = [feature for feature in shared_layers.drivezones if has_geometry(feature)]
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
