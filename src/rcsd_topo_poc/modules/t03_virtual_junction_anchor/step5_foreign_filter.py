from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_models import AssociationContext, AssociationForeignResult


FOREIGN_MASK_NORMALIZATION_MODE = "road_like_1m_mask_in_step6"


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


def _graph_incident_roads(context: AssociationContext, node_id: str) -> list[str]:
    explicit = [
        road.road_id
        for road in context.step1_context.rcsd_roads
        if road.snodeid == node_id or road.enodeid == node_id
    ]
    return _sorted_ids(explicit)


def build_association_foreign_result(
    *,
    context: AssociationContext,
    active_rcsd_nodes: list,
    active_rcsd_roads: list,
    required_rcsdnode_ids: set[str],
    support_rcsdnode_ids: set[str],
    required_rcsdroad_ids: set[str],
    support_rcsdroad_ids: set[str],
    node_degree_map: dict[str, int],
) -> AssociationForeignResult:
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
    foreign_swsd_context_geometry = None
    foreign_rcsd_context_geometry = None

    return AssociationForeignResult(
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
            "foreign_swsd_group_ids": [],
            "foreign_swsd_road_ids": [],
            "selected_surface_foreign_protection_applied": False,
            "selected_surface_protection_buffer_m": 0.0,
            "foreign_swsd_context_area_before_selected_surface_protection_m2": 0.0,
            "foreign_swsd_context_area_after_selected_surface_protection_m2": 0.0,
            "ignored_outside_current_swsd_surface_swsd_road_ids": [],
            "ignored_outside_current_swsd_surface_foreign_group_ids": [],
            "selected_swsd_road_ids": list(context.selected_road_ids),
            "foreign_mask_normalization_mode": FOREIGN_MASK_NORMALIZATION_MODE,
            "hard_negative_mask_sources": ["excluded_rcsdroad_geometry"],
            "audit_only_node_sources": ["excluded_rcsdnode_ids", "true_foreign_rcsdnode_ids"],
        },
    )
