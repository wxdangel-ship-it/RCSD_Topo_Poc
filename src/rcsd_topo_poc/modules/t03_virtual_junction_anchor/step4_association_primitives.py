from __future__ import annotations

from collections import defaultdict

from collections.abc import Iterable

from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point

from shapely.geometry.base import BaseGeometry

from shapely.ops import nearest_points, substring, unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import NodeRecord, RoadRecord

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.id_utils import normalize_id, stable_id_key

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step5_foreign_filter import build_association_foreign_result

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_direction_gate import (
    build_single_sided_direction_gate_audit,
)

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_models import (
    AssociationCaseResult,
    AssociationContext,
    AssociationOutputGeometries,
)

RCSD_ALLOWED_BUFFER_M = 1.0

SELECTED_CORRIDOR_BUFFER_M = 10.0

REQUIRED_NODE_CORRIDOR_BUFFER_M = 12.0

SUPPORT_CORRIDOR_BUFFER_M = 14.0

HOOK_SEGMENT_MAX_LENGTH_M = 24.0

HOOK_ZONE_BUFFER_M = 4.0

INCIDENT_NODE_DISTANCE_M = 6.0

CENTER_REQUIRED_CORE_ANCHOR_DISTANCE_M = 8.0

CENTER_REQUIRED_CORE_PAIR_DISTANCE_M = 12.0

CENTER_COMPACT_OFFSET_CORE_DISTANCE_M = 14.0

CENTER_COMPACT_OFFSET_CORE_MIN_DEGREE = 4

SINGLE_SIDED_REQUIRED_CORE_ANCHOR_DISTANCE_M = 18.0

PARALLEL_SUPPORT_DIRECTION_SIM = 0.94

PARALLEL_SUPPORT_MAX_EXIT_DISTANCE_M = 8.0

PARALLEL_SUPPORT_EXIT_CLUSTER_M = 45.0

UTURN_MAX_LENGTH_M = 60.0

UTURN_OPPOSITE_DIRECTION_DOT_MAX = -0.92

UTURN_FORMWAY_BIT = 1024

UTURN_TRUNK_PAIR_COLLINEAR_DOT_MAX = -0.92

UTURN_TRUNK_AXIS_PARALLEL_DOT_MIN = 0.94

UTURN_TRUNK_FLOW_OPPOSITE_DOT_MAX = -0.92

COMPOSITE_RCSD_NODE_GROUP_MAX_SPAN_M = 9.0

def _u_turn_detection_mode(active_rcsd_roads: Iterable[RoadRecord]) -> str:
    return (
        "formway_bit"
        if any(road.formway is not None for road in active_rcsd_roads)
        else "geometry_fallback_no_formway"
    )

def _sorted_ids(values: Iterable[str]) -> list[str]:
    ids = [normalized for value in values if (normalized := normalize_id(value)) is not None]
    return sorted(set(ids), key=stable_id_key)

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

def _extract_line_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    parts = [
        part
        for part in _iter_geometries(geometry)
        if part.geom_type == "LineString" and getattr(part, "length", 0.0) > 0.0
    ]
    if not parts:
        return None
    return _clean_geometry(unary_union(parts))

def _largest_line_string(geometry: BaseGeometry | None) -> LineString | None:
    line = _extract_line_geometry(geometry)
    if line is None:
        return None
    if line.geom_type == "LineString":
        return line
    if line.geom_type == "MultiLineString":
        longest = max(line.geoms, key=lambda item: item.length, default=None)
        return longest if isinstance(longest, LineString) else None
    return None

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

def _point_like(geometry: BaseGeometry) -> Point:
    if isinstance(geometry, Point):
        return geometry
    point = geometry.representative_point()
    return point if isinstance(point, Point) else Point(point.coords[0])

def _line_direction_similarity(lhs: BaseGeometry | None, rhs: BaseGeometry | None) -> float:
    left = _largest_line_string(lhs)
    right = _largest_line_string(rhs)
    if left is None or right is None or left.length <= 0.0 or right.length <= 0.0:
        return 0.0
    l0, l1 = Point(left.coords[0]), Point(left.coords[-1])
    r0, r1 = Point(right.coords[0]), Point(right.coords[-1])
    ldx, ldy = l1.x - l0.x, l1.y - l0.y
    rdx, rdy = r1.x - r0.x, r1.y - r0.y
    lnorm = (ldx * ldx + ldy * ldy) ** 0.5
    rnorm = (rdx * rdx + rdy * rdy) ** 0.5
    if lnorm <= 0.0 or rnorm <= 0.0:
        return 0.0
    return abs((ldx * rdx + ldy * rdy) / (lnorm * rnorm))

def _line_tangent_at_node(road: RoadRecord, node_id: str) -> tuple[float, float] | None:
    line = _largest_line_string(_clean_geometry(road.geometry))
    if line is None:
        return None
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    if str(road.snodeid) == str(node_id):
        p0 = coords[0]
        p1 = coords[min(1, len(coords) - 1)]
    elif str(road.enodeid) == str(node_id):
        p0 = coords[-1]
        p1 = coords[max(0, len(coords) - 2)]
    else:
        return None
    dx = p1[0] - p0[0]
    dy = p1[1] - p0[1]
    norm = (dx * dx + dy * dy) ** 0.5
    if norm <= 1e-6:
        return None
    return dx / norm, dy / norm

def _direction_dot(lhs: tuple[float, float] | None, rhs: tuple[float, float] | None) -> float | None:
    if lhs is None or rhs is None:
        return None
    return lhs[0] * rhs[0] + lhs[1] * rhs[1]

def _negate_vector(vector: tuple[float, float] | None) -> tuple[float, float] | None:
    if vector is None:
        return None
    return -vector[0], -vector[1]

def _normalize_vector(x_value: float, y_value: float) -> tuple[float, float] | None:
    norm = (x_value * x_value + y_value * y_value) ** 0.5
    if norm <= 1e-6:
        return None
    return x_value / norm, y_value / norm

def _same_direction_vector_pair(
    lhs: tuple[float, float] | None,
    rhs: tuple[float, float] | None,
) -> tuple[float, float] | None:
    dot = _direction_dot(lhs, rhs)
    if lhs is None or rhs is None or dot is None:
        return None
    if dot < 0.0:
        rhs = _negate_vector(rhs)
    if rhs is None:
        return None
    return _normalize_vector(lhs[0] + rhs[0], lhs[1] + rhs[1])

def _nearest_exit_point(geometry: BaseGeometry | None, vertical_exit_geometry: BaseGeometry | None) -> Point | None:
    if geometry is None or geometry.is_empty or vertical_exit_geometry is None or vertical_exit_geometry.is_empty:
        return None
    _source, exit_point = nearest_points(geometry, vertical_exit_geometry)
    return exit_point if isinstance(exit_point, Point) else Point(exit_point.coords[0])

def _normalize_group_id(node: NodeRecord) -> str:
    mainnodeid = None if node.mainnodeid in {None, "", "0"} else normalize_id(node.mainnodeid)
    return normalize_id(mainnodeid or node.node_id) or str(node.node_id)

def _max_node_group_span_m(nodes: Iterable[NodeRecord]) -> float:
    node_list = list(nodes)
    max_distance = 0.0
    for index, node in enumerate(node_list):
        for other in node_list[index + 1:]:
            max_distance = max(max_distance, float(node.geometry.distance(other.geometry)))
    return max_distance

def _compact_group_id_by_node(nodes: Iterable[NodeRecord]) -> dict[str, str]:
    raw_groups: dict[str, list[NodeRecord]] = defaultdict(list)
    for node in nodes:
        raw_groups[_normalize_group_id(node)].append(node)

    group_id_by_node: dict[str, str] = {}
    for raw_group_id, group_nodes in raw_groups.items():
        compact = (
            len(group_nodes) > 1
            and _max_node_group_span_m(group_nodes) <= COMPOSITE_RCSD_NODE_GROUP_MAX_SPAN_M
        )
        for node in group_nodes:
            group_id_by_node[node.node_id] = raw_group_id if compact else node.node_id
    return group_id_by_node

def _build_selected_corridor(context: AssociationContext) -> BaseGeometry:
    roads = [road.geometry.buffer(SELECTED_CORRIDOR_BUFFER_M, cap_style=2, join_style=2) for road in context.step1_context.roads if road.road_id in set(context.selected_road_ids)]
    if not roads:
        return context.step1_context.representative_node.geometry.buffer(REQUIRED_NODE_CORRIDOR_BUFFER_M)
    return unary_union(roads)

def _build_single_sided_vertical_exit_geometry(context: AssociationContext) -> BaseGeometry | None:
    if context.template_result.template_class != "single_sided_t_mouth":
        return None
    horizontal_pair_ids = {
        str(item)
        for item in (context.step3_status_doc.get("single_sided_horizontal_pair_road_ids") or [])
        if item is not None and str(item) != ""
    }
    exit_roads = [
        road.geometry
        for road in context.step1_context.roads
        if road.road_id in set(context.selected_road_ids) and road.road_id not in horizontal_pair_ids
    ]
    if not exit_roads:
        return None
    return _extract_line_geometry(unary_union(exit_roads))

def _incident_roads(candidate_roads: list[RoadRecord], node: NodeRecord) -> list[RoadRecord]:
    matches = []
    for road in candidate_roads:
        if road.snodeid == node.node_id or road.enodeid == node.node_id:
            matches.append(road)
            continue
        if road.geometry.distance(node.geometry) <= INCIDENT_NODE_DISTANCE_M:
            matches.append(road)
    return matches

def _graph_incident_roads(all_roads: Iterable[RoadRecord], node: NodeRecord) -> list[RoadRecord]:
    explicit = [
        road
        for road in all_roads
        if road.snodeid == node.node_id or road.enodeid == node.node_id
    ]
    if explicit:
        return list({road.road_id: road for road in explicit}.values())
    return _incident_roads(list(all_roads), node)

def _build_node_degree_map(
    active_nodes: list[NodeRecord],
    active_roads: list[RoadRecord],
    *,
    graph_nodes: Iterable[NodeRecord] | None = None,
    graph_roads: Iterable[RoadRecord] | None = None,
) -> dict[str, int]:
    graph_node_list = list(graph_nodes or active_nodes)
    graph_road_list = list(graph_roads or active_roads)
    node_group_by_id = _compact_group_id_by_node(graph_node_list)
    group_node_ids: dict[str, set[str]] = defaultdict(set)
    for node in graph_node_list:
        group_node_ids[node_group_by_id[node.node_id]].add(node.node_id)

    incident_road_ids_by_group: dict[str, set[str]] = defaultdict(set)
    for road in graph_road_list:
        endpoint_groups = {
            node_group_by_id[node_id]
            for node_id in (str(road.snodeid or ""), str(road.enodeid or ""))
            if node_id in node_group_by_id
        }
        for group_id in endpoint_groups:
            endpoint_node_ids = {str(road.snodeid or ""), str(road.enodeid or "")}
            if endpoint_node_ids and endpoint_node_ids <= group_node_ids[group_id]:
                continue
            incident_road_ids_by_group[group_id].add(road.road_id)

    return {
        node.node_id: len(incident_road_ids_by_group.get(node_group_by_id[node.node_id], set()))
        for node in active_nodes
        if node.node_id in node_group_by_id
    }

def _road_flow_flags_for_group(road: RoadRecord, member_node_ids: set[str]) -> tuple[bool, bool]:
    touches_snode = road.snodeid in member_node_ids
    touches_enode = road.enodeid in member_node_ids
    if not touches_snode and not touches_enode:
        return False, False
    if road.direction in {0, 1}:
        return True, True
    if touches_snode and touches_enode:
        return True, True
    if road.direction == 2:
        return touches_enode, touches_snode
    if road.direction == 3:
        return touches_snode, touches_enode
    return False, False

def _group_node_ids_by_group_id(active_nodes: list[NodeRecord]) -> tuple[dict[str, str], dict[str, set[str]]]:
    group_id_by_node_id = _compact_group_id_by_node(active_nodes)
    group_node_ids: dict[str, set[str]] = defaultdict(set)
    for node in active_nodes:
        group_node_ids[group_id_by_node_id[node.node_id]].add(node.node_id)
    return group_id_by_node_id, group_node_ids

def _road_touches_group_externally(road: RoadRecord, member_node_ids: set[str]) -> bool:
    endpoint_ids = {str(node_id) for node_id in (road.snodeid, road.enodeid) if node_id not in {None, ""}}
    if not endpoint_ids or not (endpoint_ids & member_node_ids):
        return False
    return not endpoint_ids <= member_node_ids

def _road_group_endpoint_node_id(road: RoadRecord, member_node_ids: set[str]) -> str | None:
    if road.snodeid in member_node_ids:
        return str(road.snodeid)
    if road.enodeid in member_node_ids:
        return str(road.enodeid)
    return None

def _incident_group_roads(
    roads: list[RoadRecord],
    member_node_ids: set[str],
    *,
    exclude_road_id: str | None = None,
) -> list[RoadRecord]:
    return [
        road
        for road in roads
        if road.road_id != exclude_road_id and _road_touches_group_externally(road, member_node_ids)
    ]

def _host_road_flow_vector(
    road: RoadRecord,
    member_node_ids: set[str],
) -> tuple[tuple[float, float] | None, str]:
    if road.direction not in {2, 3}:
        return None, "direction_unavailable_or_untrusted"
    node_id = _road_group_endpoint_node_id(road, member_node_ids)
    if node_id is None:
        return None, "missing_group_endpoint"
    tangent = _line_tangent_at_node(road, node_id)
    if tangent is None:
        return None, "missing_tangent"
    incoming, outgoing = _road_flow_flags_for_group(road, member_node_ids)
    if incoming == outgoing:
        return None, "ambiguous_group_flow"
    if outgoing:
        return tangent, "trusted"
    return _negate_vector(tangent), "trusted"
