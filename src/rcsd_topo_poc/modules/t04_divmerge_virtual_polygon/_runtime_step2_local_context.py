from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

from shapely.geometry import GeometryCollection, Point
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step23_contracts import (
    Stage4LocalContext,
    Stage4NegativeExclusionContext,
    Stage4RecallWindow,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import LoadedFeature, normalize_id
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import (
    DEFAULT_PATCH_SIZE_M,
    DEFAULT_RESOLUTION_M,
    ParsedNode,
    ParsedRoad,
    _build_grid,
    _load_layer_filtered,
    _patch_ids_from_properties,
    _rasterize_geometries,
    _resolve_current_patch_id_from_roads,
)

from ._runtime_step4_geometry_core import *
from ._runtime_step4_geometry_base import *

def _matches_stage4_patch_membership(properties: dict[str, Any], *, patch_id: str | None) -> bool:
    if patch_id is None:
        return True
    return patch_id in _patch_ids_from_properties(properties)


def _filter_stage4_roads_to_patch_membership(
    roads: list[ParsedRoad],
    *,
    patch_id: str | None,
) -> list[ParsedRoad]:
    if patch_id is None:
        return list(roads)
    return [road for road in roads if _matches_stage4_patch_membership(road.properties, patch_id=patch_id)]


def _filter_stage4_features_to_patch_membership(
    features: list[LoadedFeature],
    *,
    patch_id: str | None,
) -> list[LoadedFeature]:
    if patch_id is None:
        return list(features)
    return [feature for feature in features if _matches_stage4_patch_membership(feature.properties, patch_id=patch_id)]


def _build_stage4_negative_exclusion_context(
    *,
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    local_rcsd_nodes: list[ParsedNode],
    local_rcsd_roads: list[ParsedRoad],
    group_nodes: list[ParsedNode],
    direct_target_rc_nodes: list[ParsedNode],
) -> Stage4NegativeExclusionContext:
    member_node_ids = {node.node_id for node in group_nodes}
    direct_target_rc_node_ids = {node.node_id for node in direct_target_rc_nodes}
    positive_swsd_road_ids = {
        road.road_id
        for road in local_roads
        if road.snodeid in member_node_ids or road.enodeid in member_node_ids
    }
    return Stage4NegativeExclusionContext(
        source_priority=("rcsd", "swsd", "road_geometry"),
        rcsd_nodes=tuple(
            node for node in local_rcsd_nodes if node.node_id not in direct_target_rc_node_ids
        ),
        rcsd_roads=tuple(local_rcsd_roads),
        swsd_nodes=tuple(node for node in local_nodes if node.node_id not in member_node_ids),
        swsd_roads=tuple(road for road in local_roads if road.road_id not in positive_swsd_road_ids),
        road_geometry_only_ids=tuple(
            sorted(road.road_id for road in local_roads if road.road_id not in positive_swsd_road_ids)
        ),
        notes=(
            "step2_provisional_negative_exclusion_context",
            "final_geometric_exclusion_deferred_to_step5",
        ),
    )


def _build_stage4_local_context(
    *,
    representative_node: ParsedNode,
    group_nodes: list[ParsedNode],
    nodes: list[ParsedNode],
    roads: list[ParsedRoad],
    drivezone_features: list[LoadedFeature],
    rcsd_roads: list[ParsedRoad],
    rcsd_nodes: list[ParsedNode],
    preloaded_divstrip_features: list[LoadedFeature] | None = None,
    divstripzone_path: Optional[Union[str, Path]] = None,
    divstripzone_layer: Optional[str] = None,
    divstripzone_crs: Optional[str] = None,
) -> Stage4LocalContext:
    recall_window = Stage4RecallWindow()
    current_patch_id = _resolve_current_patch_id_from_roads(group_nodes=group_nodes, roads=roads)
    direct_target_rc_nodes = [
        node
        for node in rcsd_nodes
        if node.mainnodeid == normalize_id(representative_node.mainnodeid or representative_node.node_id)
        or (
            node.mainnodeid is None
            and node.node_id == normalize_id(representative_node.mainnodeid or representative_node.node_id)
        )
    ]
    primary_main_rc_node = _pick_primary_main_rc_node(
        target_rc_nodes=direct_target_rc_nodes,
        mainnodeid_norm=normalize_id(representative_node.mainnodeid or representative_node.node_id),
    )
    exact_target_rc_nodes = [
        node
        for node in direct_target_rc_nodes
        if primary_main_rc_node is None or normalize_id(node.node_id) != normalize_id(primary_main_rc_node.node_id)
    ]
    rcsdnode_seed_mode = "direct_mainnodeid_group" if direct_target_rc_nodes else "missing_direct_mainnodeid_group"

    seed_geometries = [
        representative_node.geometry,
        *[node.geometry for node in group_nodes],
        *[node.geometry for node in exact_target_rc_nodes],
    ]
    seed_union = unary_union(seed_geometries)
    seed_center = seed_union.centroid if not seed_union.is_empty else representative_node.geometry
    farthest_seed_distance = max(
        (
            float(Point(seed.x, seed.y).distance(seed_center))
            for seed in [representative_node.geometry, *[node.geometry for node in group_nodes], *[node.geometry for node in exact_target_rc_nodes]]
        ),
        default=0.0,
    )
    patch_size_m = max(DEFAULT_PATCH_SIZE_M, 260.0, farthest_seed_distance * 2.0 + 60.0)
    grid = _build_grid(seed_center, patch_size_m=patch_size_m, resolution_m=DEFAULT_RESOLUTION_M)
    scene_drivezone_features = [
        feature
        for feature in drivezone_features
        if feature.geometry is not None
        and not feature.geometry.is_empty
        and feature.geometry.intersects(grid.patch_polygon)
    ]
    if not scene_drivezone_features:
        scene_drivezone_features = [
            feature
            for feature in drivezone_features
            if feature.geometry is not None and not feature.geometry.is_empty
        ]
    drivezone_union = unary_union([feature.geometry for feature in scene_drivezone_features])
    if drivezone_union.is_empty:
        raise Stage4RunError(REASON_MISSING_REQUIRED_FIELD, "DriveZone layer has no non-empty geometry.")
    if direct_target_rc_nodes:
        _validate_drivezone_containment(
            drivezone_union=drivezone_union,
            features=direct_target_rc_nodes,
            label="RCSDNode",
        )
    drivezone_mask = _rasterize_geometries(grid, [drivezone_union])

    scene_roads = [road for road in roads if road.geometry.intersects(grid.patch_polygon)]
    patch_filtered_scene_roads = _filter_stage4_roads_to_patch_membership(scene_roads, patch_id=current_patch_id)
    local_roads = scene_roads
    patch_roads = patch_filtered_scene_roads if patch_filtered_scene_roads else scene_roads
    local_nodes = [node for node in nodes if node.geometry.intersects(grid.patch_polygon)]
    local_rcsd_roads = [road for road in rcsd_roads if road.geometry.intersects(grid.patch_polygon)]
    local_rcsd_nodes = [node for node in rcsd_nodes if node.geometry.intersects(grid.patch_polygon)]
    legacy_drivezone_features = [
        feature
        for feature in _filter_stage4_features_to_patch_membership(drivezone_features, patch_id=current_patch_id)
        if feature.geometry is not None and not feature.geometry.is_empty
    ]
    legacy_drivezone_union = (
        unary_union([feature.geometry for feature in legacy_drivezone_features])
        if legacy_drivezone_features
        else drivezone_union
    )
    legacy_drivezone_mask = _rasterize_geometries(grid, [legacy_drivezone_union])
    divstripzone_layer_data = None
    if preloaded_divstrip_features is not None:
        raw_divstrip_features = list(preloaded_divstrip_features)
    elif divstripzone_path is not None:
        divstripzone_layer_data = _load_layer(
            divstripzone_path,
            layer_name=divstripzone_layer,
            crs_override=divstripzone_crs,
            allow_null_geometry=False,
            query_geometry=grid.patch_polygon,
        )
        raw_divstrip_features = list(divstripzone_layer_data.features)
    else:
        raw_divstrip_features = []
    raw_local_divstrip_features = [
        feature
        for feature in raw_divstrip_features
        if feature.geometry is not None and not feature.geometry.is_empty
        and feature.geometry.intersects(grid.patch_polygon)
    ]
    clipped_local_divstrip_features = _clip_loaded_features_to_geometry(
        features=raw_local_divstrip_features,
        clip_geometry=grid.patch_polygon,
    )
    local_divstrip_features = _explode_loaded_polygon_features(
        features=clipped_local_divstrip_features,
    )
    patch_local_divstrip_features = [
        feature
        for feature in local_divstrip_features
        if _matches_stage4_patch_membership(feature.properties, patch_id=current_patch_id)
    ]
    patch_divstrip_features = (
        patch_local_divstrip_features if patch_local_divstrip_features else local_divstrip_features
    )
    local_divstrip_union = (
        unary_union([feature.geometry for feature in local_divstrip_features])
        if local_divstrip_features
        else GeometryCollection()
    )
    patch_divstrip_union = (
        unary_union([feature.geometry for feature in patch_divstrip_features])
        if patch_divstrip_features
        else GeometryCollection()
    )
    negative_exclusion_context = _build_stage4_negative_exclusion_context(
        local_nodes=local_nodes,
        local_roads=local_roads,
        local_rcsd_nodes=local_rcsd_nodes,
        local_rcsd_roads=local_rcsd_roads,
        group_nodes=group_nodes,
        direct_target_rc_nodes=direct_target_rc_nodes,
    )
    return Stage4LocalContext(
        current_patch_id=current_patch_id,
        representative_node_id=representative_node.node_id,
        group_node_ids=tuple(node.node_id for node in group_nodes),
        direct_target_rc_nodes=tuple(direct_target_rc_nodes),
        exact_target_rc_nodes=tuple(exact_target_rc_nodes),
        primary_main_rc_node=primary_main_rc_node,
        rcsdnode_seed_mode=rcsdnode_seed_mode,
        patch_size_m=patch_size_m,
        seed_center=seed_center,
        grid=grid,
        drivezone_union=drivezone_union,
        drivezone_mask=drivezone_mask,
        scene_drivezone_feature_count=len(scene_drivezone_features),
        scene_road_count=len(scene_roads),
        local_nodes=tuple(local_nodes),
        local_roads=tuple(local_roads),
        local_rcsd_nodes=tuple(local_rcsd_nodes),
        local_rcsd_roads=tuple(local_rcsd_roads),
        local_divstrip_features=tuple(local_divstrip_features),
        queried_divstrip_feature_count=len(local_divstrip_features),
        local_divstrip_union=local_divstrip_union,
        patch_drivezone_union=legacy_drivezone_union,
        patch_drivezone_mask=legacy_drivezone_mask,
        patch_roads=tuple(patch_roads),
        patch_divstrip_features=tuple(patch_divstrip_features),
        patch_divstrip_union=patch_divstrip_union,
        recall_window=recall_window,
        negative_exclusion_context=negative_exclusion_context,
    )

def _load_layer(
    path: Union[str, Path],
    *,
    layer_name: Optional[str],
    crs_override: Optional[str],
    allow_null_geometry: bool,
    query_geometry: Any | None = None,
) -> Any:
    try:
        return _load_layer_filtered(
            path,
            layer_name=layer_name,
            crs_override=crs_override,
            allow_null_geometry=allow_null_geometry,
            query_geometry=query_geometry,
        )
    except Exception as exc:
        if hasattr(exc, "reason") and hasattr(exc, "detail"):
            raise Stage4RunError(getattr(exc, "reason"), getattr(exc, "detail")) from exc
        raise Stage4RunError(REASON_INVALID_CRS_OR_UNPROJECTABLE, str(exc)) from exc


def _validate_drivezone_containment(
    *,
    drivezone_union,
    features: list[Any],
    label: str,
) -> list[str]:
    outside_ids: list[str] = []
    drivezone_cover = drivezone_union.buffer(0)
    for feature in features:
        feature_id = normalize_id(feature.node_id if hasattr(feature, "node_id") else getattr(feature, "road_id", None))
        if feature.geometry is None or feature.geometry.is_empty:
            continue
        if drivezone_cover.covers(feature.geometry):
            continue
        outside_ids.append(feature_id or "unknown")
    if outside_ids:
        raise Stage4RunError(
            REASON_RCS_OUTSIDE_DRIVEZONE,
            f"{label} features are outside DriveZone: {','.join(sorted(set(outside_ids)))}",
        )
    return outside_ids

def _clip_loaded_features_to_geometry(
    *,
    features: list[LoadedFeature],
    clip_geometry,
) -> list[LoadedFeature]:
    if clip_geometry is None or clip_geometry.is_empty:
        return []
    clipped_features: list[LoadedFeature] = []
    for feature in features:
        geometry = feature.geometry
        if geometry is None or geometry.is_empty:
            continue
        clipped_geometry = geometry.intersection(clip_geometry)
        if clipped_geometry.is_empty:
            continue
        clipped_features.append(
            LoadedFeature(
                feature_index=feature.feature_index,
                properties=dict(feature.properties),
                geometry=clipped_geometry,
            )
        )
    return clipped_features


def _explode_loaded_polygon_features(
    *,
    features: list[LoadedFeature],
) -> list[LoadedFeature]:
    exploded_features: list[LoadedFeature] = []
    for feature in features:
        geometry = feature.geometry
        if geometry is None or geometry.is_empty:
            continue
        component_geometries = [
            component
            for component in _explode_component_geometries(geometry)
            if getattr(component, "geom_type", None) == "Polygon"
            and not component.is_empty
            and float(getattr(component, "area", 0.0) or 0.0) > 1e-6
        ]
        if not component_geometries:
            continue
        if len(component_geometries) == 1:
            exploded_features.append(
                LoadedFeature(
                    feature_index=feature.feature_index,
                    properties=dict(feature.properties),
                    geometry=component_geometries[0],
                )
            )
            continue
        source_properties = dict(feature.properties)
        source_properties.setdefault("source_feature_index", feature.feature_index)
        for component_index, component_geometry in enumerate(component_geometries):
            component_properties = dict(source_properties)
            component_properties["exploded_component_index"] = component_index
            exploded_features.append(
                LoadedFeature(
                    feature_index=feature.feature_index,
                    properties=component_properties,
                    geometry=component_geometry,
                )
            )
    return exploded_features
