from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step45_models import Step45Context, Step45ForeignResult


FOREIGN_ROAD_BUFFER_M = 4.0
FOREIGN_NODE_BUFFER_M = 5.0
FOREIGN_CONTEXT_MARGIN_M = 30.0


def _sorted_ids(values: Iterable[str]) -> list[str]:
    return sorted(set(values), key=lambda item: (0, int(item)) if item.isdigit() else (1, item))


def _clean_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, GeometryCollection):
        cleaned = [_clean_geometry(part) for part in geometry.geoms]
        cleaned = [part for part in cleaned if part is not None and not part.is_empty]
        if not cleaned:
            return None
        merged = unary_union(cleaned)
        return None if merged.is_empty else merged
    if isinstance(geometry, (Point, MultiPoint, LineString, MultiLineString)):
        return geometry if not geometry.is_empty else None
    cleaned = geometry.buffer(0)
    return None if cleaned.is_empty else cleaned


def _iter_geometries(geometry: BaseGeometry | None) -> Iterable[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, (GeometryCollection, MultiPolygon, MultiLineString, MultiPoint)):
        for part in geometry.geoms:
            yield from _iter_geometries(part)
        return
    yield geometry


def _union_lines(geometries: Iterable[BaseGeometry]) -> BaseGeometry | None:
    parts = [
        part
        for geometry in geometries
        for part in _iter_geometries(geometry)
        if part.geom_type == "LineString" and getattr(part, "length", 0.0) > 0.0
    ]
    if not parts:
        return None
    return _clean_geometry(unary_union(parts))


def _union_points(geometries: Iterable[BaseGeometry]) -> BaseGeometry | None:
    parts = [
        part
        for geometry in geometries
        for part in _iter_geometries(geometry)
        if part.geom_type == "Point"
    ]
    if not parts:
        return None
    return _clean_geometry(unary_union(parts))


def _buffer_union(geometries: Iterable[BaseGeometry], distance_m: float) -> BaseGeometry | None:
    parts = []
    for geometry in geometries:
        for part in _iter_geometries(geometry):
            buffered = part.buffer(distance_m, cap_style=2, join_style=2)
            if not buffered.is_empty:
                parts.append(buffered)
    if not parts:
        return None
    return _clean_geometry(unary_union(parts))


def _graph_incident_roads(context: Step45Context, node_id: str) -> list[str]:
    explicit = [
        road.road_id
        for road in context.step1_context.rcsd_roads
        if road.snodeid == node_id or road.enodeid == node_id
    ]
    return _sorted_ids(explicit)


def build_step45_foreign_result(
    *,
    context: Step45Context,
    active_rcsd_nodes: list,
    active_rcsd_roads: list,
    required_rcsdnode_ids: set[str],
    support_rcsdnode_ids: set[str],
    required_rcsdroad_ids: set[str],
    support_rcsdroad_ids: set[str],
    node_degree_map: dict[str, int],
) -> Step45ForeignResult:
    step1 = context.step1_context
    excluded_nodes = [
        node
        for node in active_rcsd_nodes
        if node.node_id not in required_rcsdnode_ids and node.node_id not in support_rcsdnode_ids
    ]
    excluded_roads = [
        road
        for road in active_rcsd_roads
        if road.road_id not in required_rcsdroad_ids and road.road_id not in support_rcsdroad_ids
    ]
    retained_rcsdroad_ids = set(required_rcsdroad_ids) | set(support_rcsdroad_ids)
    nonsemantic_connector_nodes = []
    true_foreign_nodes = []
    connector_incident_retained_road_ids: dict[str, list[str]] = {}
    for node in excluded_nodes:
        incident_road_ids = _graph_incident_roads(context, node.node_id)
        retained_incident_road_ids = _sorted_ids(
            road_id for road_id in incident_road_ids if road_id in retained_rcsdroad_ids
        )
        if node_degree_map.get(node.node_id, 0) == 2 and retained_incident_road_ids:
            nonsemantic_connector_nodes.append(node)
            connector_incident_retained_road_ids[node.node_id] = retained_incident_road_ids
            continue
        true_foreign_nodes.append(node)
    current_surface = context.current_swsd_surface_geometry
    local_patch = _clean_geometry(
        unary_union(
            [
                step1.representative_node.geometry.buffer(18.0),
                current_surface if current_surface is not None else step1.representative_node.geometry.buffer(FOREIGN_CONTEXT_MARGIN_M),
            ]
        )
    )

    foreign_swsd_parts: list[BaseGeometry] = []
    selected_road_ids = set(context.selected_road_ids)
    active_foreign_swsd_road_ids: list[str] = []
    ignored_outside_current_swsd_surface_swsd_road_ids: list[str] = []
    for road in step1.roads:
        if road.road_id in selected_road_ids:
            continue
        if current_surface is not None and not road.geometry.intersects(current_surface.buffer(0.5)):
            ignored_outside_current_swsd_surface_swsd_road_ids.append(road.road_id)
            continue
        if local_patch is not None and not road.geometry.intersects(local_patch.buffer(FOREIGN_CONTEXT_MARGIN_M)):
            continue
        active_foreign_swsd_road_ids.append(road.road_id)
        foreign_swsd_parts.append(road.geometry.buffer(FOREIGN_ROAD_BUFFER_M, cap_style=2, join_style=2))
    active_foreign_swsd_group_ids: list[str] = []
    ignored_outside_current_swsd_surface_group_ids: list[str] = []
    for group in step1.foreign_groups:
        group_active = False
        for node in group.nodes:
            if current_surface is not None and not node.geometry.intersects(current_surface.buffer(0.5)):
                continue
            if local_patch is not None and not node.geometry.intersects(local_patch.buffer(FOREIGN_CONTEXT_MARGIN_M)):
                continue
            group_active = True
            foreign_swsd_parts.append(node.geometry.buffer(FOREIGN_NODE_BUFFER_M))
        if group_active:
            active_foreign_swsd_group_ids.append(group.group_id)
        else:
            ignored_outside_current_swsd_surface_group_ids.append(group.group_id)
    foreign_swsd_context_geometry = _clean_geometry(unary_union(foreign_swsd_parts)) if foreign_swsd_parts else None
    if foreign_swsd_context_geometry is not None and local_patch is not None:
        foreign_swsd_context_geometry = _clean_geometry(foreign_swsd_context_geometry.intersection(local_patch.buffer(FOREIGN_CONTEXT_MARGIN_M)))

    foreign_rc_parts = [road.geometry.buffer(FOREIGN_ROAD_BUFFER_M, cap_style=2, join_style=2) for road in excluded_roads]
    foreign_rc_parts.extend(node.geometry.buffer(FOREIGN_NODE_BUFFER_M) for node in true_foreign_nodes)
    foreign_rcsd_context_geometry = _clean_geometry(unary_union(foreign_rc_parts)) if foreign_rc_parts else None
    if foreign_rcsd_context_geometry is not None and local_patch is not None:
        foreign_rcsd_context_geometry = _clean_geometry(foreign_rcsd_context_geometry.intersection(local_patch.buffer(FOREIGN_CONTEXT_MARGIN_M)))

    return Step45ForeignResult(
        excluded_rcsdnode_ids=tuple(_sorted_ids(node.node_id for node in excluded_nodes)),
        excluded_rcsdroad_ids=tuple(_sorted_ids(road.road_id for road in excluded_roads)),
        nonsemantic_connector_rcsdnode_ids=tuple(_sorted_ids(node.node_id for node in nonsemantic_connector_nodes)),
        true_foreign_rcsdnode_ids=tuple(_sorted_ids(node.node_id for node in true_foreign_nodes)),
        excluded_rcsdnode_geometry=_union_points(node.geometry for node in excluded_nodes),
        excluded_rcsdroad_geometry=_union_lines(road.geometry for road in excluded_roads),
        foreign_swsd_context_geometry=foreign_swsd_context_geometry,
        foreign_rcsd_context_geometry=foreign_rcsd_context_geometry,
        audit_doc={
            "excluded_rcsdnode_ids": _sorted_ids(node.node_id for node in excluded_nodes),
            "excluded_rcsdroad_ids": _sorted_ids(road.road_id for road in excluded_roads),
            "nonsemantic_connector_rcsdnode_ids": _sorted_ids(node.node_id for node in nonsemantic_connector_nodes),
            "true_foreign_rcsdnode_ids": _sorted_ids(node.node_id for node in true_foreign_nodes),
            "connector_incident_retained_rcsdroad_ids": connector_incident_retained_road_ids,
            "foreign_swsd_group_ids": _sorted_ids(active_foreign_swsd_group_ids),
            "foreign_swsd_road_ids": _sorted_ids(active_foreign_swsd_road_ids),
            "ignored_outside_current_swsd_surface_swsd_road_ids": _sorted_ids(ignored_outside_current_swsd_surface_swsd_road_ids),
            "ignored_outside_current_swsd_surface_foreign_group_ids": _sorted_ids(ignored_outside_current_swsd_surface_group_ids),
            "selected_swsd_road_ids": list(context.selected_road_ids),
        },
    )
