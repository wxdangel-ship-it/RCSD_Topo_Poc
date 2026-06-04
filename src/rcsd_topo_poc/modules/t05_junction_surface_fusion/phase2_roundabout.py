from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .phase2_models import SwsdTargetContext


ROUNDABOUT_KIND_2 = 64
ROUNDABOUT_ROADTYPE = 8
ROUNDABOUT_BUFFER_M = 10.0


@dataclass(frozen=True)
class RoundaboutAggregation:
    target_id: str
    rcsdnode_ids: tuple[int, ...]
    rcsdroad_ids: tuple[int, ...]
    semantic_group_ids: tuple[int, ...]
    surface_count: int
    swsd_node_count: int
    reason: str = "kind_2_64_roundabout_connected_rcsd_junctions"


def build_roundabout_aggregations(
    *,
    contexts: list[SwsdTargetContext],
    surfaces: list[dict[str, Any]],
    swsd_nodes: list[dict[str, Any]],
    roads_by_id: dict[int, dict[str, Any]],
    rcsdnode_features_by_id: dict[int, dict[str, Any]],
    buffer_m: float = ROUNDABOUT_BUFFER_M,
) -> dict[str, RoundaboutAggregation]:
    surface_geometries = _valid_geometries(surfaces)
    if not surface_geometries:
        return {}
    surface_tree = STRtree(surface_geometries)
    swsd_nodes_by_target = _nodes_by_target(swsd_nodes)
    surface_props_by_target = _surface_props_by_target(surfaces)
    roadtype8_geometries, roadtype8_ids = _roadtype8_geometries(roads_by_id)
    if not roadtype8_geometries:
        return {}
    roadtype8_tree = STRtree(roadtype8_geometries)
    rcsd_groups = _rcsd_semantic_groups(rcsdnode_features_by_id)
    rcsd_node_geometries, rcsd_node_ids = _rcsd_node_geometries(rcsdnode_features_by_id)
    if not rcsd_node_geometries:
        return {}
    rcsd_node_tree = STRtree(rcsd_node_geometries)

    aggregations: dict[str, RoundaboutAggregation] = {}
    for context in contexts:
        swsd_group_nodes = swsd_nodes_by_target.get(context.target_id, [])
        if not _is_roundabout_target(
            context=context,
            swsd_nodes=swsd_group_nodes,
            surface_properties=surface_props_by_target.get(context.target_id, []),
        ):
            continue
        matched_surface_indexes = _surfaces_covering_all_nodes(
            swsd_group_nodes,
            surface_geometries=surface_geometries,
            surface_tree=surface_tree,
        )
        if not matched_surface_indexes:
            continue
        matched_surfaces = [surface_geometries[index] for index in sorted(matched_surface_indexes)]
        surface_union = unary_union(matched_surfaces)
        ring_road_ids = _ring_road_ids(
            surface_union=surface_union,
            road_geometries=roadtype8_geometries,
            road_ids=roadtype8_ids,
            road_tree=roadtype8_tree,
            buffer_m=buffer_m,
        )
        if not ring_road_ids:
            continue
        roundabout_surface = unary_union(
            [surface_union]
            + [
                roads_by_id[road_id]["geometry"].buffer(buffer_m)
                for road_id in ring_road_ids
                if _usable_geometry(roads_by_id[road_id].get("geometry"))
            ]
        )
        semantic_group_ids = _semantic_groups_inside_surface(
            roundabout_surface=roundabout_surface,
            rcsd_groups=rcsd_groups,
            rcsdnode_features_by_id=rcsdnode_features_by_id,
            rcsd_node_geometries=rcsd_node_geometries,
            rcsd_node_ids=rcsd_node_ids,
            rcsd_node_tree=rcsd_node_tree,
        )
        if len(semantic_group_ids) < 2:
            continue
        connected_group_ids, connecting_road_ids = _connected_roundabout_groups(
            semantic_group_ids=semantic_group_ids,
            ring_road_ids=ring_road_ids,
            roads_by_id=roads_by_id,
            rcsd_groups=rcsd_groups,
        )
        if len(connected_group_ids) < 2:
            continue
        node_ids = sorted({node_id for group_id in connected_group_ids for node_id in rcsd_groups[group_id]})
        aggregations[context.target_id] = RoundaboutAggregation(
            target_id=context.target_id,
            rcsdnode_ids=tuple(node_ids),
            rcsdroad_ids=tuple(connecting_road_ids),
            semantic_group_ids=tuple(connected_group_ids),
            surface_count=len(matched_surface_indexes),
            swsd_node_count=len(swsd_group_nodes),
        )
    return aggregations


def _surfaces_covering_all_nodes(
    nodes: list[dict[str, Any]],
    *,
    surface_geometries: list[BaseGeometry],
    surface_tree: STRtree,
) -> set[int]:
    if not nodes:
        return set()
    matched: set[int] = set()
    for node in nodes:
        point = _point_geometry(node.get("geometry"))
        if point is None:
            return set()
        candidate_indexes = [
            int(index)
            for index in surface_tree.query(point)
            if surface_geometries[int(index)].covers(point)
        ]
        if not candidate_indexes:
            return set()
        matched.update(candidate_indexes)
    return matched


def _ring_road_ids(
    *,
    surface_union: BaseGeometry,
    road_geometries: list[BaseGeometry],
    road_ids: list[int],
    road_tree: STRtree,
    buffer_m: float,
) -> list[int]:
    search_area = surface_union.buffer(buffer_m)
    ids: list[int] = []
    for index in road_tree.query(search_area):
        road_index = int(index)
        geometry = road_geometries[road_index]
        if geometry.intersects(search_area):
            ids.append(road_ids[road_index])
    return sorted(set(ids))


def _semantic_groups_inside_surface(
    *,
    roundabout_surface: BaseGeometry,
    rcsd_groups: dict[int, list[int]],
    rcsdnode_features_by_id: dict[int, dict[str, Any]],
    rcsd_node_geometries: list[BaseGeometry],
    rcsd_node_ids: list[int],
    rcsd_node_tree: STRtree,
) -> list[int]:
    candidate_groups = {
        _semantic_group_id(rcsdnode_features_by_id[node_id])
        for index in rcsd_node_tree.query(roundabout_surface)
        for node_id in [rcsd_node_ids[int(index)]]
        if roundabout_surface.covers(rcsd_node_geometries[int(index)])
    }
    result: list[int] = []
    for group_id in sorted(candidate_groups):
        node_ids = rcsd_groups.get(group_id, [])
        if node_ids and all(_feature_covered(rcsdnode_features_by_id.get(node_id), roundabout_surface) for node_id in node_ids):
            result.append(group_id)
    return result


def _connected_roundabout_groups(
    *,
    semantic_group_ids: list[int],
    ring_road_ids: list[int],
    roads_by_id: dict[int, dict[str, Any]],
    rcsd_groups: dict[int, list[int]],
) -> tuple[list[int], list[int]]:
    group_set = set(semantic_group_ids)
    node_to_group = {node_id: group_id for group_id, node_ids in rcsd_groups.items() for node_id in node_ids if group_id in group_set}
    adjacency: dict[int, set[int]] = defaultdict(set)
    edge_roads_by_group_pair: dict[tuple[int, int], set[int]] = defaultdict(set)
    for road_id in ring_road_ids:
        props = roads_by_id.get(road_id, {}).get("properties") or {}
        if _int_field_value(props, "roadtype") != ROUNDABOUT_ROADTYPE:
            continue
        start_group = node_to_group.get(_int_field_value(props, "snodeid"))
        end_group = node_to_group.get(_int_field_value(props, "enodeid"))
        if start_group is None or end_group is None or start_group == end_group:
            continue
        pair = tuple(sorted((start_group, end_group)))
        adjacency[start_group].add(end_group)
        adjacency[end_group].add(start_group)
        edge_roads_by_group_pair[pair].add(road_id)
    components: list[set[int]] = []
    seen: set[int] = set()
    for group_id in sorted(adjacency):
        if group_id in seen:
            continue
        component: set[int] = set()
        queue: deque[int] = deque([group_id])
        while queue:
            current = queue.popleft()
            if current in component:
                continue
            component.add(current)
            seen.add(current)
            queue.extend(sorted(adjacency[current] - component))
        if len(component) > 1:
            components.append(component)
    if not components:
        return [], []
    component = sorted(
        components,
        key=lambda item: (-len(item), min(item)),
    )[0]
    connecting_roads: set[int] = set()
    for pair, road_ids in edge_roads_by_group_pair.items():
        if pair[0] in component and pair[1] in component:
            connecting_roads.update(road_ids)
    return sorted(component), sorted(connecting_roads)


def _is_roundabout_target(
    *,
    context: SwsdTargetContext,
    swsd_nodes: list[dict[str, Any]],
    surface_properties: list[dict[str, Any]],
) -> bool:
    values: list[Any] = []
    values.extend(context.representative_properties.get(field) for field in ("kind_2", "kind"))
    for node in swsd_nodes:
        props = node.get("properties") or {}
        values.extend(_field_value(props, field) for field in ("kind_2", "kind"))
    for props in surface_properties:
        values.extend(_field_value(props, field) for field in ("kind_2", "kind"))
    return any(_int_value(value) == ROUNDABOUT_KIND_2 for value in values)


def _nodes_by_target(nodes: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for node in nodes:
        props = node.get("properties") or {}
        target_id = _text(_field_value(props, "mainnodeid") or _field_value(props, "id"))
        if target_id:
            result[target_id].append(node)
    return result


def _surface_props_by_target(surfaces: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for surface in surfaces:
        props = dict(surface.get("properties") or {})
        target_id = _text(_field_value(props, "mainnodeid"))
        if target_id:
            result[target_id].append(props)
    return result


def _valid_geometries(features: list[dict[str, Any]]) -> list[BaseGeometry]:
    return [feature["geometry"] for feature in features if _usable_geometry(feature.get("geometry"))]


def _roadtype8_geometries(roads_by_id: dict[int, dict[str, Any]]) -> tuple[list[BaseGeometry], list[int]]:
    geometries: list[BaseGeometry] = []
    ids: list[int] = []
    for road_id, feature in sorted(roads_by_id.items()):
        props = feature.get("properties") or {}
        geometry = feature.get("geometry")
        if _int_field_value(props, "roadtype") == ROUNDABOUT_ROADTYPE and _usable_geometry(geometry):
            ids.append(road_id)
            geometries.append(geometry)
    return geometries, ids


def _rcsd_semantic_groups(node_features_by_id: dict[int, dict[str, Any]]) -> dict[int, list[int]]:
    groups: dict[int, list[int]] = defaultdict(list)
    for node_id, feature in sorted(node_features_by_id.items()):
        group_id = _semantic_group_id(feature)
        groups[group_id].append(node_id)
    return groups


def _rcsd_node_geometries(node_features_by_id: dict[int, dict[str, Any]]) -> tuple[list[BaseGeometry], list[int]]:
    geometries: list[BaseGeometry] = []
    ids: list[int] = []
    for node_id, feature in sorted(node_features_by_id.items()):
        geometry = feature.get("geometry")
        if _usable_geometry(geometry):
            ids.append(node_id)
            geometries.append(geometry)
    return geometries, ids


def _feature_covered(feature: dict[str, Any] | None, geometry: BaseGeometry) -> bool:
    if not feature:
        return False
    point = _point_geometry(feature.get("geometry"))
    return point is not None and geometry.covers(point)


def _semantic_group_id(feature: dict[str, Any]) -> int:
    props = feature.get("properties") or {}
    mainnodeid = _int_field_value(props, "mainnodeid")
    if mainnodeid not in (None, 0, -1):
        return mainnodeid
    node_id = _int_field_value(props, "id")
    return int(node_id) if node_id is not None else 0


def _point_geometry(geometry: Any) -> Point | None:
    if geometry is None or getattr(geometry, "is_empty", True):
        return None
    if getattr(geometry, "geom_type", "") == "Point":
        return geometry
    return geometry.representative_point()


def _usable_geometry(geometry: Any) -> bool:
    return geometry is not None and not getattr(geometry, "is_empty", True)


def _field_value(properties: dict[str, Any], field_name: str) -> Any:
    for key, value in properties.items():
        if key.lower() == field_name:
            return value
    return None


def _int_field_value(properties: dict[str, Any], field_name: str) -> int | None:
    return _int_value(_field_value(properties, field_name))


def _int_value(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()
