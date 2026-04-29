from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points, substring, unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import NodeRecord, RoadRecord
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step5_foreign_filter import build_association_foreign_result
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
    mainnodeid = None if node.mainnodeid in {None, "", "0"} else node.mainnodeid
    return str(mainnodeid or node.node_id)


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


def _evaluate_u_turn_trunk_at_group(
    *,
    group_id: str,
    member_node_ids: set[str],
    active_roads: list[RoadRecord],
    u_turn_road: RoadRecord,
) -> dict[str, Any]:
    incident_roads = _incident_group_roads(active_roads, member_node_ids)
    host_roads = [road for road in incident_roads if road.road_id != u_turn_road.road_id]
    audit: dict[str, Any] = {
        "group_id": group_id,
        "member_node_ids": _sorted_ids(member_node_ids),
        "effective_degree": len({road.road_id for road in incident_roads}),
        "host_rcsdroad_ids": _sorted_ids(road.road_id for road in host_roads),
    }
    if audit["effective_degree"] != 3:
        audit["structure_ok"] = False
        audit["reason"] = "endpoint_group_effective_degree_not_3"
        return audit
    if len(host_roads) != 2:
        audit["structure_ok"] = False
        audit["reason"] = "endpoint_group_host_pair_not_2"
        return audit

    host_tangents: list[tuple[str, tuple[float, float]]] = []
    for host_road in host_roads:
        node_id = _road_group_endpoint_node_id(host_road, member_node_ids)
        tangent = _line_tangent_at_node(host_road, node_id or "")
        if tangent is None:
            audit["structure_ok"] = False
            audit["reason"] = "endpoint_group_host_tangent_missing"
            return audit
        host_tangents.append((host_road.road_id, tangent))

    tangent_dot = _direction_dot(host_tangents[0][1], host_tangents[1][1])
    audit["host_pair_tangent_dot"] = round(tangent_dot, 6) if tangent_dot is not None else None
    if tangent_dot is None or tangent_dot > UTURN_TRUNK_PAIR_COLLINEAR_DOT_MAX:
        audit["structure_ok"] = False
        audit["reason"] = "endpoint_group_host_pair_not_collinear"
        return audit

    audit["structure_ok"] = True
    axis = _same_direction_vector_pair(host_tangents[0][1], host_tangents[1][1])
    audit["_axis_vector"] = axis

    flow_vectors = []
    flow_statuses: dict[str, str] = {}
    for host_road in host_roads:
        flow_vector, status = _host_road_flow_vector(host_road, member_node_ids)
        flow_statuses[host_road.road_id] = status
        flow_vectors.append(flow_vector)
    audit["host_direction_status_by_rcsdroad_id"] = flow_statuses
    if any(vector is None for vector in flow_vectors):
        audit["direction_status"] = "unavailable_or_untrusted"
        audit["_flow_vector"] = None
        return audit

    flow_dot = _direction_dot(flow_vectors[0], flow_vectors[1])
    audit["host_pair_flow_dot"] = round(flow_dot, 6) if flow_dot is not None else None
    if flow_dot is None or flow_dot < UTURN_TRUNK_AXIS_PARALLEL_DOT_MIN:
        audit["direction_status"] = "not_opposite"
        audit["_flow_vector"] = None
        return audit

    audit["direction_status"] = "trusted"
    audit["_flow_vector"] = _same_direction_vector_pair(flow_vectors[0], flow_vectors[1])
    return audit


def _evaluate_geometry_u_turn_candidate(
    *,
    road: RoadRecord,
    active_nodes: list[NodeRecord],
    active_roads: list[RoadRecord],
) -> dict[str, Any]:
    audit: dict[str, Any] = {
        "detection_mode": "geometry_fallback_no_formway",
        "formway": road.formway,
        "road_length_m": round(road.geometry.length, 6),
    }
    if road.geometry.length > UTURN_MAX_LENGTH_M:
        audit["candidate"] = False
        audit["reason"] = "road_too_long"
        return audit

    group_id_by_node_id, group_node_ids = _group_node_ids_by_group_id(active_nodes)
    endpoint_group_ids = [
        group_id_by_node_id.get(str(node_id))
        for node_id in (road.snodeid, road.enodeid)
        if node_id not in {None, ""}
    ]
    endpoint_group_ids = [group_id for group_id in endpoint_group_ids if group_id is not None]
    audit["endpoint_group_ids"] = endpoint_group_ids
    if len(endpoint_group_ids) != 2 or endpoint_group_ids[0] == endpoint_group_ids[1]:
        audit["candidate"] = False
        audit["reason"] = "road_does_not_connect_two_semantic_groups"
        return audit

    endpoint_audit = [
        _evaluate_u_turn_trunk_at_group(
            group_id=group_id,
            member_node_ids=group_node_ids[group_id],
            active_roads=active_roads,
            u_turn_road=road,
        )
        for group_id in endpoint_group_ids
    ]
    audit["endpoint_trunk_audit"] = [
        {key: value for key, value in row.items() if not key.startswith("_")}
        for row in endpoint_audit
    ]
    if not all(row.get("structure_ok") for row in endpoint_audit):
        audit["candidate"] = False
        audit["reason"] = "endpoint_trunk_structure_not_satisfied"
        return audit

    axis_dot = _direction_dot(endpoint_audit[0].get("_axis_vector"), endpoint_audit[1].get("_axis_vector"))
    axis_parallel_similarity = abs(axis_dot) if axis_dot is not None else None
    audit["trunk_axis_parallel_similarity"] = (
        round(axis_parallel_similarity, 6) if axis_parallel_similarity is not None else None
    )
    if axis_parallel_similarity is None or axis_parallel_similarity < UTURN_TRUNK_AXIS_PARALLEL_DOT_MIN:
        audit["candidate"] = False
        audit["reason"] = "endpoint_trunk_axes_not_parallel"
        return audit

    audit["candidate"] = True
    if any(row.get("direction_status") == "unavailable_or_untrusted" for row in endpoint_audit):
        audit["decision"] = "suspect_audit_only"
        audit["reason"] = "direction_unavailable_or_untrusted"
        return audit
    if any(row.get("direction_status") != "trusted" for row in endpoint_audit):
        audit["decision"] = "not_u_turn"
        audit["reason"] = "host_pair_direction_not_trusted"
        return audit

    flow_dot = _direction_dot(endpoint_audit[0].get("_flow_vector"), endpoint_audit[1].get("_flow_vector"))
    audit["trunk_flow_dot"] = round(flow_dot, 6) if flow_dot is not None else None
    if flow_dot is not None and flow_dot <= UTURN_TRUNK_FLOW_OPPOSITE_DOT_MAX:
        audit["decision"] = "qualified_u_turn"
        audit["reason"] = "effective_degree3_parallel_trunks_opposite_flow"
        return audit
    audit["decision"] = "not_u_turn"
    audit["reason"] = "trunk_flow_not_opposite"
    return audit


def _detect_u_turn_rcsdroads(
    active_rcsd_roads: list[RoadRecord],
    *,
    active_rcsd_nodes: list[NodeRecord],
    graph_rcsd_nodes: Iterable[NodeRecord] | None = None,
    graph_rcsd_roads: Iterable[RoadRecord] | None = None,
    same_path_protected_rcsdroad_ids: set[str] | None = None,
    same_path_terminal_rcsdnode_ids: set[str] | None = None,
) -> tuple[set[str], dict[str, dict[str, Any]], set[str], set[str], set[str]]:
    same_path_protected_rcsdroad_ids = same_path_protected_rcsdroad_ids or set()
    same_path_terminal_rcsdnode_ids = same_path_terminal_rcsdnode_ids or set()
    u_turn_ids: set[str] = set()
    candidate_ids: set[str] = set()
    rejected_by_same_path_ids: set[str] = set()
    suspect_ids: set[str] = set()
    audit_rows: dict[str, dict[str, Any]] = {}
    detection_mode = _u_turn_detection_mode(active_rcsd_roads)
    if detection_mode == "formway_bit":
        for road in active_rcsd_roads:
            formway_has_u_turn_bit = road.formway is not None and bool(road.formway & UTURN_FORMWAY_BIT)
            if not formway_has_u_turn_bit:
                continue
            candidate_ids.add(road.road_id)
            audit_rows[road.road_id] = {
                "detection_mode": detection_mode,
                "formway": road.formway,
                "u_turn_formway_bit": UTURN_FORMWAY_BIT,
                "road_length_m": round(road.geometry.length, 6),
                "endpoint_matches": [],
                "rejected_by_same_path_chain": False,
                "rejected_by_same_path_terminal": False,
            }
            u_turn_ids.add(road.road_id)
        return u_turn_ids, audit_rows, candidate_ids, rejected_by_same_path_ids, suspect_ids

    graph_nodes = list(graph_rcsd_nodes or active_rcsd_nodes)
    graph_roads = list(graph_rcsd_roads or active_rcsd_roads)
    active_node_ids = {node.node_id for node in active_rcsd_nodes}
    for road in active_rcsd_roads:
        audit_row = _evaluate_geometry_u_turn_candidate(
            road=road,
            active_nodes=active_rcsd_nodes,
            active_roads=active_rcsd_roads,
        )
        endpoint_node_ids = set(_endpoint_node_ids(road))
        missing_endpoint_node_ids = endpoint_node_ids - active_node_ids
        if not audit_row.get("candidate") and missing_endpoint_node_ids:
            graph_audit_row = _evaluate_geometry_u_turn_candidate(
                road=road,
                active_nodes=graph_nodes,
                active_roads=graph_roads,
            )
            if graph_audit_row.get("candidate"):
                graph_audit_row["graph_fallback_applied"] = True
                graph_audit_row["active_scope_reason"] = audit_row.get("reason")
                graph_audit_row["active_scope_missing_endpoint_node_ids"] = _sorted_ids(missing_endpoint_node_ids)
                audit_row = graph_audit_row
        if not audit_row.get("candidate"):
            continue
        candidate_ids.add(road.road_id)
        qualified_u_turn = audit_row.get("decision") == "qualified_u_turn"
        same_path_protected = road.road_id in same_path_protected_rcsdroad_ids
        same_path_override = qualified_u_turn
        audit_row["rejected_by_same_path_chain"] = same_path_protected and not same_path_override
        audit_row["rejected_by_same_path_terminal"] = any(
            node_id in same_path_terminal_rcsdnode_ids for node_id in _endpoint_node_ids(road)
        )
        audit_rows[road.road_id] = audit_row
        if same_path_protected and not same_path_override:
            rejected_by_same_path_ids.add(road.road_id)
            continue
        if audit_rows[road.road_id]["rejected_by_same_path_terminal"]:
            continue
        if audit_row.get("decision") == "qualified_u_turn":
            u_turn_ids.add(road.road_id)
        elif audit_row.get("decision") == "suspect_audit_only":
            suspect_ids.add(road.road_id)
    return u_turn_ids, audit_rows, candidate_ids, rejected_by_same_path_ids, suspect_ids


def _build_degree2_rcsdroad_chains(
    candidate_roads: list[RoadRecord],
    degree2_connector_candidate_node_ids: set[str],
) -> tuple[dict[str, str], dict[str, tuple[str, ...]]]:
    roads_by_id = {road.road_id: road for road in candidate_roads}
    if not roads_by_id:
        return {}, {}

    parent = {road_id: road_id for road_id in roads_by_id}

    def _find(road_id: str) -> str:
        while parent[road_id] != road_id:
            parent[road_id] = parent[parent[road_id]]
            road_id = parent[road_id]
        return road_id

    def _union(lhs: str, rhs: str) -> None:
        left_root = _find(lhs)
        right_root = _find(rhs)
        if left_root == right_root:
            return
        if left_root < right_root:
            parent[right_root] = left_root
        else:
            parent[left_root] = right_root

    incident_roads_by_node: dict[str, set[str]] = defaultdict(set)
    for road in candidate_roads:
        if road.snodeid in degree2_connector_candidate_node_ids:
            incident_roads_by_node[str(road.snodeid)].add(road.road_id)
        if road.enodeid in degree2_connector_candidate_node_ids:
            incident_roads_by_node[str(road.enodeid)].add(road.road_id)

    for road_ids in incident_roads_by_node.values():
        ordered_ids = _sorted_ids(road_ids)
        if len(ordered_ids) < 2:
            continue
        pivot = ordered_ids[0]
        for other_id in ordered_ids[1:]:
            _union(pivot, other_id)

    groups_by_root: dict[str, list[str]] = defaultdict(list)
    for road_id in roads_by_id:
        groups_by_root[_find(road_id)].append(road_id)

    chain_id_by_road_id: dict[str, str] = {}
    chain_members_by_chain_id: dict[str, tuple[str, ...]] = {}
    for member_ids in groups_by_root.values():
        ordered_ids = tuple(_sorted_ids(member_ids))
        chain_id = ordered_ids[0]
        chain_members_by_chain_id[chain_id] = ordered_ids
        for road_id in ordered_ids:
            chain_id_by_road_id[road_id] = chain_id
    return chain_id_by_road_id, chain_members_by_chain_id


def _build_same_path_chain_protection(
    *,
    candidate_roads: list[RoadRecord],
    candidate_node_ids: set[str],
    degree2_connector_candidate_node_ids: set[str],
) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]], set[str], set[str]]:
    chain_id_by_road_id, chain_members_by_chain_id = _build_degree2_rcsdroad_chains(
        candidate_roads,
        degree2_connector_candidate_node_ids,
    )
    incident_road_ids_by_node: dict[str, set[str]] = defaultdict(set)
    for road in candidate_roads:
        if road.snodeid not in {None, ""}:
            incident_road_ids_by_node[str(road.snodeid)].add(road.road_id)
        if road.enodeid not in {None, ""}:
            incident_road_ids_by_node[str(road.enodeid)].add(road.road_id)

    terminals_by_chain_id: dict[str, set[str]] = defaultdict(set)
    for node_id in candidate_node_ids - degree2_connector_candidate_node_ids:
        for road_id in incident_road_ids_by_node.get(node_id, set()):
            chain_id = chain_id_by_road_id.get(road_id)
            if chain_id is not None:
                terminals_by_chain_id[chain_id].add(node_id)

    protected_chain_members: dict[str, tuple[str, ...]] = {}
    protected_chain_terminals: dict[str, tuple[str, ...]] = {}
    protected_road_ids: set[str] = set()
    protected_terminal_node_ids: set[str] = set()
    for chain_id, member_ids in chain_members_by_chain_id.items():
        terminal_ids = terminals_by_chain_id.get(chain_id, set())
        if len(member_ids) <= 1 or len(terminal_ids) < 2:
            continue
        protected_chain_members[chain_id] = member_ids
        protected_chain_terminals[chain_id] = tuple(_sorted_ids(terminal_ids))
        protected_road_ids.update(member_ids)
        protected_terminal_node_ids.update(terminal_ids)
    return protected_chain_members, protected_chain_terminals, protected_road_ids, protected_terminal_node_ids


def _merge_same_path_chain_protection(
    target_members: dict[str, tuple[str, ...]],
    target_terminals: dict[str, tuple[str, ...]],
    target_road_ids: set[str],
    target_terminal_ids: set[str],
    *,
    source_members: dict[str, tuple[str, ...]],
    source_terminals: dict[str, tuple[str, ...]],
    source_road_ids: set[str],
    source_terminal_ids: set[str],
) -> None:
    for chain_id, member_ids in source_members.items():
        target_members[chain_id] = tuple(_sorted_ids(set(target_members.get(chain_id, ())) | set(member_ids)))
    for chain_id, terminal_ids in source_terminals.items():
        target_terminals[chain_id] = tuple(_sorted_ids(set(target_terminals.get(chain_id, ())) | set(terminal_ids)))
    target_road_ids.update(source_road_ids)
    target_terminal_ids.update(source_terminal_ids)


def _expand_rcsdroad_ids_via_degree2_chains(
    road_ids: Iterable[str],
    *,
    chain_id_by_road_id: dict[str, str],
    chain_members_by_chain_id: dict[str, tuple[str, ...]],
) -> set[str]:
    expanded_ids: set[str] = set()
    for road_id in road_ids:
        chain_id = chain_id_by_road_id.get(road_id, road_id)
        expanded_ids.update(chain_members_by_chain_id.get(chain_id, (road_id,)))
    return expanded_ids


def _collect_required_road_ids_for_nodes(
    *,
    required_nodes: list[NodeRecord],
    candidate_roads: list[RoadRecord],
    selected_corridor: BaseGeometry,
) -> set[str]:
    required_road_ids: set[str] = set()
    for node in required_nodes:
        for road in _incident_roads(candidate_roads, node):
            if not road.geometry.intersects(selected_corridor.buffer(REQUIRED_NODE_CORRIDOR_BUFFER_M)):
                continue
            required_road_ids.add(road.road_id)
    return required_road_ids


def _endpoint_node_ids(road: RoadRecord) -> tuple[str, ...]:
    return tuple(
        str(node_id)
        for node_id in (road.snodeid, road.enodeid)
        if node_id not in {None, ""}
    )


def _build_related_outside_scope_rcsdroad_ids(
    *,
    active_rcsd_nodes: list[NodeRecord],
    active_rcsd_roads: list[RoadRecord],
    required_rcsdroad_ids: set[str],
    candidate_rcsdnode_ids: set[str],
    allowed_space: BaseGeometry,
    node_degree_map: dict[str, int],
) -> tuple[set[str], dict[str, Any]]:
    if not required_rcsdroad_ids:
        return set(), {}
    allowed_scope = allowed_space.buffer(RCSD_ALLOWED_BUFFER_M)
    active_node_ids = {node.node_id for node in active_rcsd_nodes}
    nodes_by_id = {node.node_id: node for node in active_rcsd_nodes}
    incident_road_ids_by_node: dict[str, set[str]] = defaultdict(set)
    for road in active_rcsd_roads:
        for node_id in _endpoint_node_ids(road):
            incident_road_ids_by_node[node_id].add(road.road_id)

    outside_scope_ids: set[str] = set()
    audit_rows: dict[str, Any] = {}
    for road in active_rcsd_roads:
        if road.road_id in required_rcsdroad_ids:
            continue
        if road.geometry.intersects(allowed_scope):
            continue
        connector_matches = []
        endpoint_node_ids = set(_endpoint_node_ids(road))
        if not endpoint_node_ids or not endpoint_node_ids <= active_node_ids:
            continue
        for node_id in _sorted_ids(endpoint_node_ids):
            if node_degree_map.get(node_id, 0) != 2:
                continue
            node = nodes_by_id.get(node_id)
            if node is None:
                continue
            if node_id not in candidate_rcsdnode_ids and not node.geometry.intersects(allowed_scope):
                continue
            retained_incident_ids = _sorted_ids(
                incident_road_ids_by_node.get(node_id, set()) & required_rcsdroad_ids
            )
            if not retained_incident_ids:
                continue
            connector_matches.append(
                {
                    "connector_rcsdnode_id": node_id,
                    "retained_incident_rcsdroad_ids": retained_incident_ids,
                }
            )
        if not connector_matches:
            continue
        outside_scope_ids.add(road.road_id)
        audit_rows[road.road_id] = {
            "reason": "required_core_degree2_connector_one_hop_outside_step3_scope",
            "connector_matches": connector_matches,
        }
    return outside_scope_ids, audit_rows


def _build_related_rcsd_group_ids(
    *,
    active_rcsd_nodes: list[NodeRecord],
    active_rcsd_roads: list[RoadRecord],
    seed_rcsdnode_ids: set[str],
    related_rcsdroad_ids: set[str],
    node_degree_map: dict[str, int],
) -> tuple[set[str], set[str], dict[str, Any]]:
    related_node_ids = set(seed_rcsdnode_ids)
    if not related_rcsdroad_ids:
        return related_node_ids, set(), {}
    nodes_by_id = {node.node_id: node for node in active_rcsd_nodes}
    node_group_by_id = _compact_group_id_by_node(active_rcsd_nodes)
    group_node_ids: dict[str, set[str]] = defaultdict(set)
    for node in active_rcsd_nodes:
        group_node_ids[node_group_by_id[node.node_id]].add(node.node_id)

    incident_road_ids_by_group: dict[str, set[str]] = defaultdict(set)
    related_incident_road_ids_by_group: dict[str, set[str]] = defaultdict(set)
    for road in active_rcsd_roads:
        endpoint_group_ids = {
            node_group_by_id[node_id]
            for node_id in _endpoint_node_ids(road)
            if node_id in nodes_by_id
        }
        for group_id in endpoint_group_ids:
            incident_road_ids_by_group[group_id].add(road.road_id)
        if road.road_id not in related_rcsdroad_ids:
            continue
        for group_id in endpoint_group_ids:
            related_incident_road_ids_by_group[group_id].add(road.road_id)

    related_group_road_ids: set[str] = set()
    audit_rows: dict[str, Any] = {}
    for group_id, member_node_ids in group_node_ids.items():
        related_incident_road_ids = related_incident_road_ids_by_group.get(group_id, set())
        if len(member_node_ids) <= 1 or len(related_incident_road_ids) < 2:
            continue
        member_nodes = [nodes_by_id[node_id] for node_id in member_node_ids if node_id in nodes_by_id]
        group_span_m = _max_node_group_span_m(member_nodes)
        if group_span_m > COMPOSITE_RCSD_NODE_GROUP_MAX_SPAN_M:
            continue
        group_degrees = {
            int(node_degree_map.get(node_id, 0))
            for node_id in member_node_ids
            if node_id in node_degree_map
        }
        if group_degrees and max(group_degrees) == 2:
            continue
        group_incident_road_ids = incident_road_ids_by_group.get(group_id, set())
        related_node_ids.update(member_node_ids)
        related_group_road_ids.update(related_incident_road_ids)
        audit_rows[group_id] = {
            "reason": "multi_node_rcsd_semantic_group_incident_to_related_roads",
            "group_span_m": round(group_span_m, 6),
            "group_max_span_m": COMPOSITE_RCSD_NODE_GROUP_MAX_SPAN_M,
            "member_rcsdnode_ids": _sorted_ids(member_node_ids),
            "related_incident_rcsdroad_ids": _sorted_ids(related_incident_road_ids),
            "related_group_incident_rcsdroad_ids": _sorted_ids(related_incident_road_ids),
            "group_incident_rcsdroad_ids": _sorted_ids(group_incident_road_ids),
        }
    return related_node_ids, related_group_road_ids, audit_rows


def _select_single_sided_t_mouth_strong_nodes(
    *,
    context: AssociationContext,
    required_nodes: list[NodeRecord],
    selected_corridor: BaseGeometry,
) -> tuple[set[str], list[str], list[str]]:
    if context.template_result.template_class != "single_sided_t_mouth":
        return {node.node_id for node in required_nodes}, [], []
    if len(required_nodes) <= 2:
        strong_ids = _sorted_ids(node.node_id for node in required_nodes)
        return set(strong_ids), strong_ids, []

    horizontal_pair_ids = {
        str(item)
        for item in (context.step3_status_doc.get("single_sided_horizontal_pair_road_ids") or [])
        if item is not None and str(item) != ""
    }
    horizontal_geometry = _union_lines(
        road.geometry
        for road in context.step1_context.roads
        if road.road_id in horizontal_pair_ids
    )
    anchor_point = _point_like(context.step1_context.representative_node.geometry)

    def _score(node: NodeRecord) -> tuple[float, float, str]:
        reference_geometry = horizontal_geometry or selected_corridor
        return (
            float(node.geometry.distance(reference_geometry)),
            float(node.geometry.distance(anchor_point)),
            node.node_id,
        )

    ordered_nodes = sorted(required_nodes, key=_score)
    strong_ids = set(node.node_id for node in ordered_nodes[:2])
    overflow_ids = _sorted_ids(node.node_id for node in ordered_nodes[2:])
    return strong_ids, _sorted_ids(strong_ids), overflow_ids


def _apply_required_rcsdnode_template_gate(
    *,
    context: AssociationContext,
    required_node_ids: set[str],
    grouped_candidate_nodes: dict[str, list[NodeRecord]],
    node_degree_map: dict[str, int],
) -> tuple[set[str], dict[str, dict[str, Any]], list[str]]:
    gate_audit: dict[str, dict[str, Any]] = {}
    if not required_node_ids:
        return required_node_ids, gate_audit, []

    anchor_point = _point_like(context.step1_context.representative_node.geometry)
    current_swsd_surface = _clean_geometry(context.current_swsd_surface_geometry)
    current_swsd_scope = (
        current_swsd_surface.buffer(RCSD_ALLOWED_BUFFER_M) if current_swsd_surface is not None else None
    )
    allowed_space = _clean_geometry(context.step3_allowed_space_geometry)
    allowed_scope = allowed_space.buffer(RCSD_ALLOWED_BUFFER_M) if allowed_space is not None else None
    required_groups: dict[str, set[str]] = {}
    for group_id, group_nodes in grouped_candidate_nodes.items():
        group_required_ids = {node.node_id for node in group_nodes if node.node_id in required_node_ids}
        if not group_required_ids:
            continue
        required_groups[group_id] = group_required_ids
        group_span_m = _max_node_group_span_m(group_nodes)
        gate_audit[group_id] = {
            "member_rcsdnode_ids": _sorted_ids(node.node_id for node in group_nodes),
            "required_member_rcsdnode_ids": _sorted_ids(group_required_ids),
            "effective_degree": max((int(node_degree_map.get(node.node_id, 0)) for node in group_nodes), default=0),
            "group_span_m": round(group_span_m, 6),
            "group_max_span_m": COMPOSITE_RCSD_NODE_GROUP_MAX_SPAN_M,
            "compact_multi_node_semantic_group": len(group_nodes) > 1
            and group_span_m <= COMPOSITE_RCSD_NODE_GROUP_MAX_SPAN_M,
            "intersects_current_swsd_surface": bool(
                current_swsd_scope is not None and any(node.geometry.intersects(current_swsd_scope) for node in group_nodes)
            ),
            "intersects_allowed_space": bool(
                allowed_scope is not None and any(node.geometry.intersects(allowed_scope) for node in group_nodes)
            ),
            "min_distance_to_representative_m": round(
                min(float(node.geometry.distance(anchor_point)) for node in group_nodes),
                6,
            ),
            "gate_decision": "retained",
            "gate_reason": "required_semantic_core",
        }

    if not required_groups:
        return set(), gate_audit, _sorted_ids(required_node_ids)

    template_class = context.template_result.template_class
    if template_class == "center_junction":
        has_anchor_core = any(
            row["min_distance_to_representative_m"] <= CENTER_REQUIRED_CORE_ANCHOR_DISTANCE_M
            for row in gate_audit.values()
        )
        near_anchor_group_count = sum(
            1
            for row in gate_audit.values()
            if row["min_distance_to_representative_m"] <= CENTER_REQUIRED_CORE_PAIR_DISTANCE_M
        )
        has_compact_offset_core = any(
            row["compact_multi_node_semantic_group"]
            and row["effective_degree"] >= CENTER_COMPACT_OFFSET_CORE_MIN_DEGREE
            and row["min_distance_to_representative_m"] <= CENTER_COMPACT_OFFSET_CORE_DISTANCE_M
            for row in gate_audit.values()
        )
        if has_anchor_core or near_anchor_group_count >= 2 or has_compact_offset_core:
            for row in gate_audit.values():
                row["gate_reason"] = (
                    "center_required_core_has_anchor_local_or_compact_offset_semantic_group"
                )
            return required_node_ids, gate_audit, []
        for row in gate_audit.values():
            row["gate_decision"] = "dropped"
            row["gate_reason"] = "center_required_core_missing_anchor_local_semantic_group"
        return set(), gate_audit, _sorted_ids(required_node_ids)

    if template_class == "single_sided_t_mouth":
        has_required_pair = len(required_groups) >= 2
        has_anchor_singleton = any(
            not row["compact_multi_node_semantic_group"]
            and row["min_distance_to_representative_m"] <= SINGLE_SIDED_REQUIRED_CORE_ANCHOR_DISTANCE_M
            for row in gate_audit.values()
        )
        has_anchor_compact_group = any(
            row["compact_multi_node_semantic_group"]
            and row["min_distance_to_representative_m"] <= CENTER_REQUIRED_CORE_ANCHOR_DISTANCE_M
            for row in gate_audit.values()
        )
        has_allowed_only_compact_group = any(
            row["compact_multi_node_semantic_group"]
            and row["intersects_allowed_space"]
            and not row["intersects_current_swsd_surface"]
            for row in gate_audit.values()
        )
        if has_required_pair or has_anchor_singleton or has_anchor_compact_group or has_allowed_only_compact_group:
            for row in gate_audit.values():
                row["gate_reason"] = "single_sided_required_core_pair_anchor_or_allowed_only_compact_group"
            return required_node_ids, gate_audit, []
        for row in gate_audit.values():
            row["gate_decision"] = "dropped"
            row["gate_reason"] = "single_sided_required_core_missing_pair_anchor_or_allowed_only_compact_group"
        return set(), gate_audit, _sorted_ids(required_node_ids)

    return required_node_ids, gate_audit, []


def _clip_required_road(road: RoadRecord, allowed_space: BaseGeometry) -> BaseGeometry | None:
    return _extract_line_geometry(road.geometry.intersection(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M)))


def _shrink_hook_fragment(fragment: BaseGeometry, *, anchor_point: Point) -> BaseGeometry | None:
    line = _extract_line_geometry(fragment)
    if line is None:
        return None
    if line.length <= HOOK_SEGMENT_MAX_LENGTH_M:
        return line
    if line.geom_type == "MultiLineString":
        first = max(line.geoms, key=lambda item: item.length)
        line = _clean_geometry(first)
        if line is None:
            return None
    assert line.geom_type == "LineString"
    distance = line.project(anchor_point)
    start = max(0.0, distance - HOOK_SEGMENT_MAX_LENGTH_M / 2.0)
    end = min(line.length, distance + HOOK_SEGMENT_MAX_LENGTH_M / 2.0)
    return _clean_geometry(substring(line, start, end))


def _build_support_fragment(
    road: RoadRecord,
    *,
    allowed_space: BaseGeometry,
    selected_corridor: BaseGeometry,
    anchor_point: Point,
) -> BaseGeometry | None:
    allowed_fragment = road.geometry.intersection(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M))
    corridor_fragment = allowed_fragment.intersection(selected_corridor.buffer(SUPPORT_CORRIDOR_BUFFER_M))
    fragment = _extract_line_geometry(corridor_fragment) or _extract_line_geometry(allowed_fragment)
    if fragment is None:
        return None
    if fragment.length >= road.geometry.length * 0.95:
        fragment = _shrink_hook_fragment(fragment, anchor_point=anchor_point)
    return _clean_geometry(fragment)


def _parallel_support_duplicate(
    lhs: BaseGeometry | None,
    rhs: BaseGeometry | None,
    *,
    vertical_exit_geometry: BaseGeometry | None,
) -> bool:
    left = _largest_line_string(lhs)
    right = _largest_line_string(rhs)
    if left is None or right is None:
        return False
    if _line_direction_similarity(left, right) < PARALLEL_SUPPORT_DIRECTION_SIM:
        return False
    if vertical_exit_geometry is None or vertical_exit_geometry.is_empty:
        return False
    left_exit_distance = float(left.distance(vertical_exit_geometry))
    right_exit_distance = float(right.distance(vertical_exit_geometry))
    if left_exit_distance > PARALLEL_SUPPORT_MAX_EXIT_DISTANCE_M or right_exit_distance > PARALLEL_SUPPORT_MAX_EXIT_DISTANCE_M:
        return False
    left_exit_point = _nearest_exit_point(left, vertical_exit_geometry)
    right_exit_point = _nearest_exit_point(right, vertical_exit_geometry)
    if left_exit_point is None or right_exit_point is None:
        return False
    return float(left_exit_point.distance(right_exit_point)) <= PARALLEL_SUPPORT_EXIT_CLUSTER_M


def _prune_parallel_support_duplicates(
    *,
    context: AssociationContext,
    support_fragments_by_id: dict[str, BaseGeometry],
    anchor_point: Point,
    vertical_exit_geometry: BaseGeometry | None,
) -> tuple[dict[str, BaseGeometry], list[str]]:
    if context.template_result.template_class != "single_sided_t_mouth" or vertical_exit_geometry is None:
        return support_fragments_by_id, []
    road_ids = list(support_fragments_by_id.keys())
    if len(road_ids) <= 1:
        return support_fragments_by_id, []
    adjacency: dict[str, set[str]] = {road_id: set() for road_id in road_ids}
    for index, road_id in enumerate(road_ids):
        for other_id in road_ids[index + 1 :]:
            if _parallel_support_duplicate(
                support_fragments_by_id[road_id],
                support_fragments_by_id[other_id],
                vertical_exit_geometry=vertical_exit_geometry,
            ):
                adjacency[road_id].add(other_id)
                adjacency[other_id].add(road_id)
    visited: set[str] = set()
    dropped_ids: list[str] = []
    kept = dict(support_fragments_by_id)
    for road_id in road_ids:
        if road_id in visited:
            continue
        stack = [road_id]
        component: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(adjacency[current] - visited)
        if len(component) <= 1:
            continue

        def _score(item_id: str) -> tuple[float, float, str]:
            fragment = support_fragments_by_id[item_id]
            exit_distance = float(fragment.distance(vertical_exit_geometry))
            anchor_distance = float(fragment.distance(anchor_point))
            return (exit_distance, anchor_distance, item_id)

        winner = min(component, key=_score)
        for item_id in component:
            if item_id == winner:
                continue
            dropped_ids.append(item_id)
            kept.pop(item_id, None)
    return kept, _sorted_ids(dropped_ids)


def _group_support_fragments_by_degree2_chain(
    support_fragments_by_road_id: dict[str, BaseGeometry],
    *,
    chain_id_by_road_id: dict[str, str],
) -> dict[str, BaseGeometry]:
    grouped_fragments: dict[str, list[BaseGeometry]] = defaultdict(list)
    for road_id, fragment in support_fragments_by_road_id.items():
        chain_id = chain_id_by_road_id.get(road_id, road_id)
        grouped_fragments[chain_id].append(fragment)
    return {
        chain_id: _union_lines(fragments)
        for chain_id, fragments in grouped_fragments.items()
        if _union_lines(fragments) is not None
    }


def _visual_review_class(association_state: str, reason: str) -> str:
    if association_state == "established":
        return "V1 认可成功"
    if association_state == "review":
        if reason == "association_support_only":
            return "V2 业务正确但几何待修"
        return "V2 业务正确但几何待修"
    return "V5 明确失败"


def build_association_status_doc(case_result: AssociationCaseResult) -> dict[str, Any]:
    return {
        "case_id": case_result.case_id,
        "template_class": case_result.template_class,
        "association_class": case_result.association_class,
        "association_state": case_result.association_state,
        "association_established": case_result.association_established,
        "reason": case_result.reason,
        "visual_review_class": case_result.visual_review_class,
        "root_cause_layer": case_result.root_cause_layer,
        "root_cause_type": case_result.root_cause_type,
        "key_metrics": case_result.key_metrics,
        **case_result.extra_status_fields,
    }


def _empty_association_key_metrics() -> dict[str, Any]:
    return {
        "active_rcsdnode_count": 0,
        "active_rcsdroad_count": 0,
        "u_turn_rcsdroad_count": 0,
        "candidate_rcsdnode_count": 0,
        "candidate_rcsdroad_count": 0,
        "required_rcsdnode_count": 0,
        "required_rcsdroad_count": 0,
        "support_rcsdnode_count": 0,
        "support_rcsdroad_count": 0,
        "excluded_rcsdnode_count": 0,
        "excluded_rcsdroad_count": 0,
        "related_rcsdnode_count": 0,
        "related_rcsdroad_count": 0,
        "related_group_rcsdroad_count": 0,
        "related_outside_scope_rcsdroad_count": 0,
        "foreign_mask_source_rcsdroad_count": 0,
        "nonsemantic_connector_rcsdnode_count": 0,
        "true_foreign_rcsdnode_count": 0,
        "hook_zone_present": False,
        "hook_zone_area_m2": 0.0,
        "parallel_support_duplicate_drop_count": 0,
    }


def _build_gate_failure_case_result(
    *,
    context: AssociationContext,
    base_extra_fields: dict[str, Any],
    blocker: str,
    supported_template: bool,
    allowed_space_loaded: bool,
    current_swsd_surface_loaded: bool,
) -> AssociationCaseResult:
    empty_geometries = AssociationOutputGeometries(None, None, None, None, None, None, None, None, None)
    audit_doc = {
        "step3_prerequisite": {
            "step3_state": base_extra_fields.get("step3_state"),
            "step3_reason": base_extra_fields.get("step3_reason"),
            "step3_case_dir": base_extra_fields.get("step3_case_dir"),
            "selected_road_ids": list(base_extra_fields.get("selected_road_ids") or []),
            "step3_excluded_road_ids": list(base_extra_fields.get("step3_excluded_road_ids") or []),
            "supported_template": supported_template,
            "allowed_space_loaded": allowed_space_loaded,
            "current_swsd_surface_loaded": current_swsd_surface_loaded,
            "prerequisite_issues": list(context.prerequisite_issues),
        },
        "step4": {
            "association_class": "C",
            "association_executed": False,
            "association_reason": None,
            "association_blocker": blocker,
            "candidate_rcsdnode_ids": [],
            "candidate_rcsdroad_ids": [],
            "required_rcsdnode_ids": [],
            "required_rcsdroad_ids": [],
            "support_rcsdnode_ids": [],
            "support_rcsdroad_ids": [],
            "related_rcsdnode_ids": [],
            "related_rcsdroad_ids": [],
            "related_local_rcsdroad_ids": [],
            "related_group_rcsdroad_ids": [],
            "related_outside_scope_rcsdroad_ids": [],
            "related_outside_scope_rcsdroad_audit": {},
            "related_rcsdnode_group_audit": {},
            "degree2_merged_rcsdroad_groups": {},
            "degree2_connector_candidate_rcsdnode_ids": [],
            "parallel_support_duplicate_dropped_rcsdroad_ids": [],
            "hook_zone_shrunk_road_ids": [],
            "u_turn_rcsdroad_ids": [],
            "u_turn_rcsdroad_audit": {},
            "u_turn_candidate_rcsdroad_audit": {},
            "u_turn_candidate_rcsdroad_ids": [],
            "u_turn_suspect_rcsdroad_audit": {},
            "u_turn_suspect_rcsdroad_ids": [],
            "u_turn_rejected_by_same_path_chain_ids": [],
            "same_path_chain_protected_rcsdroad_ids": [],
            "same_path_chain_terminal_rcsdnode_ids": [],
            "same_path_rcsdroad_chain_groups": {},
            "same_path_rcsdroad_chain_terminal_groups": {},
            "t_mouth_strong_related_rcsdnode_ids": [],
            "t_mouth_strong_related_overflow_rcsdnode_ids": [],
            "required_rcsdnode_gate_dropped_ids": [],
            "required_rcsdnode_gate_audit": {},
        },
        "step5": {
            "association_class": "C",
            "association_executed": False,
            "association_reason": None,
            "association_blocker": blocker,
            "excluded_rcsdnode_ids": [],
            "excluded_rcsdroad_ids": [],
            "foreign_mask_source_rcsdroad_ids": [],
            "related_rcsdroad_ids": [],
            "foreign_swsd_group_ids": [],
            "foreign_swsd_road_ids": [],
            "nonsemantic_connector_rcsdnode_ids": [],
            "true_foreign_rcsdnode_ids": [],
        },
        "joint_phase": {
            "association_state": "not_established",
            "reason": blocker,
            "association_executed": False,
            "association_reason": None,
            "association_blocker": blocker,
            "rcsd_semantic_core_missing": False,
            "prerequisite_issues": list(context.prerequisite_issues),
        },
    }
    return AssociationCaseResult(
        case_id=context.step1_context.case_spec.case_id,
        template_class=context.template_result.template_class,
        association_class="C",
        association_state="not_established",
        association_established=False,
        reason=blocker,
        visual_review_class="V5 明确失败",
        root_cause_layer="association",
        root_cause_type=blocker,
        output_geometries=empty_geometries,
        key_metrics=_empty_association_key_metrics(),
        audit_doc=audit_doc,
        extra_status_fields={
            **base_extra_fields,
            "association_executed": False,
            "association_reason": None,
            "association_blocker": blocker,
            "rcsd_semantic_core_missing": False,
            "nonsemantic_connector_rcsdnode_ids": [],
            "true_foreign_rcsdnode_ids": [],
            "degree2_connector_candidate_rcsdnode_ids": [],
            "degree2_merged_rcsdroad_groups": {},
            "ignored_outside_current_swsd_surface_rcsdnode_ids": [],
            "ignored_outside_current_swsd_surface_rcsdroad_ids": [],
            "parallel_support_duplicate_dropped_rcsdroad_ids": [],
            "hook_zone_shrunk_road_ids": [],
            "u_turn_rcsdroad_ids": [],
            "u_turn_rcsdroad_audit": {},
            "u_turn_candidate_rcsdroad_audit": {},
            "u_turn_candidate_rcsdroad_ids": [],
            "u_turn_suspect_rcsdroad_audit": {},
            "u_turn_suspect_rcsdroad_ids": [],
            "u_turn_rejected_by_same_path_chain_ids": [],
            "same_path_chain_protected_rcsdroad_ids": [],
            "same_path_chain_terminal_rcsdnode_ids": [],
            "same_path_rcsdroad_chain_groups": {},
            "same_path_rcsdroad_chain_terminal_groups": {},
            "t_mouth_strong_related_rcsdnode_ids": [],
            "t_mouth_strong_related_overflow_rcsdnode_ids": [],
            "required_rcsdnode_gate_dropped_ids": [],
            "required_rcsdnode_gate_audit": {},
        },
    )


def build_association_case_result(context: AssociationContext) -> AssociationCaseResult:
    step1 = context.step1_context
    template_result = context.template_result
    step3_state = str(context.step3_status_doc.get("step3_state") or "")
    allowed_space = _clean_geometry(context.step3_allowed_space_geometry)
    current_swsd_surface = _clean_geometry(context.current_swsd_surface_geometry)
    base_extra_fields = {
        "step3_state": step3_state,
        "step3_reason": context.step3_status_doc.get("reason"),
        "step3_case_dir": str(context.step3_case_dir),
        "step3_run_root": str(context.step3_run_root),
        "selected_road_ids": list(context.selected_road_ids),
        "step3_excluded_road_ids": list(context.step3_excluded_road_ids),
        "u_turn_rcsdroad_ids": [],
        "required_rcsdnode_ids": [],
        "required_rcsdroad_ids": [],
        "support_rcsdnode_ids": [],
        "support_rcsdroad_ids": [],
        "excluded_rcsdnode_ids": [],
        "excluded_rcsdroad_ids": [],
        "related_rcsdnode_ids": [],
        "related_rcsdroad_ids": [],
        "related_local_rcsdroad_ids": [],
        "related_group_rcsdroad_ids": [],
        "related_outside_scope_rcsdroad_ids": [],
        "related_outside_scope_rcsdroad_audit": {},
        "related_rcsdnode_group_audit": {},
        "foreign_mask_source_rcsdroad_ids": [],
        "association_prerequisite_issues": list(context.prerequisite_issues),
        "association_executed": False,
        "association_reason": None,
        "association_blocker": None,
        "same_path_chain_protected_rcsdroad_ids": [],
        "same_path_chain_terminal_rcsdnode_ids": [],
        "same_path_rcsdroad_chain_groups": {},
        "same_path_rcsdroad_chain_terminal_groups": {},
        "u_turn_candidate_rcsdroad_ids": [],
        "u_turn_candidate_rcsdroad_audit": {},
        "u_turn_suspect_rcsdroad_ids": [],
        "u_turn_suspect_rcsdroad_audit": {},
        "u_turn_rejected_by_same_path_chain_ids": [],
        "t_mouth_strong_related_rcsdnode_ids": [],
        "t_mouth_strong_related_overflow_rcsdnode_ids": [],
        "required_rcsdnode_gate_dropped_ids": [],
        "required_rcsdnode_gate_audit": {},
    }
    if not template_result.supported:
        return _build_gate_failure_case_result(
            context=context,
            base_extra_fields=base_extra_fields,
            blocker="unsupported_template",
            supported_template=False,
            allowed_space_loaded=allowed_space is not None,
            current_swsd_surface_loaded=current_swsd_surface is not None,
        )
    if context.prerequisite_issues:
        return _build_gate_failure_case_result(
            context=context,
            base_extra_fields=base_extra_fields,
            blocker=context.prerequisite_issues[0],
            supported_template=True,
            allowed_space_loaded=allowed_space is not None,
            current_swsd_surface_loaded=current_swsd_surface is not None,
        )
    if step3_state not in {"established", "review"}:
        return _build_gate_failure_case_result(
            context=context,
            base_extra_fields=base_extra_fields,
            blocker="association_step3_not_established",
            supported_template=True,
            allowed_space_loaded=allowed_space is not None,
            current_swsd_surface_loaded=current_swsd_surface is not None,
        )

    selected_corridor = _build_selected_corridor(context)
    vertical_exit_geometry = _build_single_sided_vertical_exit_geometry(context)
    required_node_ids: set[str] = set()
    required_road_ids: set[str] = set()
    support_node_ids: set[str] = set()
    support_road_ids: set[str] = set()
    required_nodes: list[NodeRecord] = []
    required_roads: list[RoadRecord] = []
    support_roads: list[RoadRecord] = []
    support_fragments: list[BaseGeometry] = []
    hook_shrunk_road_ids: list[str] = []
    dropped_parallel_support_road_ids: list[str] = []
    anchor_point = _point_like(step1.representative_node.geometry)
    current_swsd_scope = current_swsd_surface.buffer(RCSD_ALLOWED_BUFFER_M)
    allowed_space_scope = allowed_space.buffer(RCSD_ALLOWED_BUFFER_M)
    active_rcsd_nodes = [
        node
        for node in step1.rcsd_nodes
        if node.geometry.intersects(current_swsd_scope) or node.geometry.intersects(allowed_space_scope)
    ]
    active_rcsd_roads_raw = [
        road
        for road in step1.rcsd_roads
        if road.geometry.intersects(current_swsd_scope)
    ]
    candidate_nodes_raw = [
        node for node in active_rcsd_nodes if node.geometry.intersects(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M))
    ]
    candidate_roads_raw = [
        road for road in active_rcsd_roads_raw if road.geometry.intersects(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M))
    ]
    raw_node_degree_map = _build_node_degree_map(
        active_rcsd_nodes,
        active_rcsd_roads_raw,
        graph_nodes=step1.rcsd_nodes,
        graph_roads=step1.rcsd_roads,
    )
    raw_degree2_connector_candidate_node_ids = {
        node.node_id
        for node in candidate_nodes_raw
        if raw_node_degree_map.get(node.node_id, 0) == 2
    }
    (
        same_path_chain_groups,
        same_path_chain_terminal_groups,
        same_path_protected_rcsdroad_ids,
        same_path_chain_terminal_rcsdnode_ids,
    ) = _build_same_path_chain_protection(
        candidate_roads=candidate_roads_raw,
        candidate_node_ids={node.node_id for node in candidate_nodes_raw},
        degree2_connector_candidate_node_ids=raw_degree2_connector_candidate_node_ids,
    )
    same_path_terminal_rejection_rcsdnode_ids = set(same_path_chain_terminal_rcsdnode_ids)
    (
        tentative_u_turn_rcsdroad_ids,
        _tentative_u_turn_rcsdroad_audit,
        _tentative_u_turn_candidate_rcsdroad_ids,
        _tentative_u_turn_rejected_by_same_path_chain_ids,
        _tentative_u_turn_suspect_rcsdroad_ids,
    ) = _detect_u_turn_rcsdroads(
        active_rcsd_roads_raw,
        active_rcsd_nodes=active_rcsd_nodes,
        graph_rcsd_nodes=step1.rcsd_nodes,
        graph_rcsd_roads=step1.rcsd_roads,
        same_path_protected_rcsdroad_ids=same_path_protected_rcsdroad_ids,
        same_path_terminal_rcsdnode_ids=same_path_terminal_rejection_rcsdnode_ids,
    )
    tentative_active_rcsd_roads = [
        road for road in active_rcsd_roads_raw if road.road_id not in tentative_u_turn_rcsdroad_ids
    ]
    tentative_node_degree_map = _build_node_degree_map(
        active_rcsd_nodes,
        tentative_active_rcsd_roads,
        graph_nodes=step1.rcsd_nodes,
        graph_roads=[
            road for road in step1.rcsd_roads if road.road_id not in tentative_u_turn_rcsdroad_ids
        ],
    )
    post_filter_degree2_connector_candidate_node_ids = {
        node.node_id
        for node in candidate_nodes_raw
        if tentative_node_degree_map.get(node.node_id, 0) == 2
    }
    (
        post_filter_same_path_chain_groups,
        post_filter_same_path_chain_terminal_groups,
        post_filter_same_path_protected_rcsdroad_ids,
        post_filter_same_path_chain_terminal_rcsdnode_ids,
    ) = _build_same_path_chain_protection(
        candidate_roads=active_rcsd_roads_raw,
        candidate_node_ids={node.node_id for node in active_rcsd_nodes},
        degree2_connector_candidate_node_ids=post_filter_degree2_connector_candidate_node_ids,
    )
    raw_post_filter_new_u_turn_candidate_protected_ids = (
        post_filter_same_path_protected_rcsdroad_ids
        & _tentative_u_turn_candidate_rcsdroad_ids
    ) - same_path_protected_rcsdroad_ids
    post_filter_new_u_turn_candidate_protected_ids = {
        road_id
        for road_id in raw_post_filter_new_u_turn_candidate_protected_ids
        if any(
            road_id in member_ids
            and len(set(member_ids) & _tentative_u_turn_candidate_rcsdroad_ids) >= 2
            for member_ids in post_filter_same_path_chain_groups.values()
        )
    }
    if post_filter_new_u_turn_candidate_protected_ids:
        post_filter_relevant_chain_ids = {
            chain_id
            for chain_id, member_ids in post_filter_same_path_chain_groups.items()
            if set(member_ids) & post_filter_new_u_turn_candidate_protected_ids
        }
        _merge_same_path_chain_protection(
            same_path_chain_groups,
            same_path_chain_terminal_groups,
            same_path_protected_rcsdroad_ids,
            same_path_chain_terminal_rcsdnode_ids,
            source_members={
                chain_id: post_filter_same_path_chain_groups[chain_id]
                for chain_id in post_filter_relevant_chain_ids
            },
            source_terminals={
                chain_id: post_filter_same_path_chain_terminal_groups[chain_id]
                for chain_id in post_filter_relevant_chain_ids
            },
            source_road_ids=post_filter_new_u_turn_candidate_protected_ids,
            source_terminal_ids={
                node_id
                for chain_id in post_filter_relevant_chain_ids
                for node_id in post_filter_same_path_chain_terminal_groups.get(chain_id, ())
            },
        )
    (
        u_turn_rcsdroad_ids,
        u_turn_rcsdroad_audit,
        u_turn_candidate_rcsdroad_ids,
        u_turn_rejected_by_same_path_chain_ids,
        u_turn_suspect_rcsdroad_ids,
    ) = _detect_u_turn_rcsdroads(
        active_rcsd_roads_raw,
        active_rcsd_nodes=active_rcsd_nodes,
        graph_rcsd_nodes=step1.rcsd_nodes,
        graph_rcsd_roads=step1.rcsd_roads,
        same_path_protected_rcsdroad_ids=same_path_protected_rcsdroad_ids,
        same_path_terminal_rcsdnode_ids=same_path_terminal_rejection_rcsdnode_ids,
    )
    active_rcsd_roads = [
        road for road in active_rcsd_roads_raw if road.road_id not in u_turn_rcsdroad_ids
    ]
    ignored_outside_current_swsd_surface_rcsdnode_ids = _sorted_ids(
        node.node_id for node in step1.rcsd_nodes if node.node_id not in {item.node_id for item in active_rcsd_nodes}
    )
    ignored_outside_current_swsd_surface_rcsdroad_ids = _sorted_ids(
        road.road_id for road in step1.rcsd_roads if road.road_id not in {item.road_id for item in active_rcsd_roads_raw}
    )

    node_degree_map = _build_node_degree_map(
        active_rcsd_nodes,
        active_rcsd_roads,
        graph_nodes=step1.rcsd_nodes,
        graph_roads=[road for road in step1.rcsd_roads if road.road_id not in u_turn_rcsdroad_ids],
    )

    candidate_nodes = [node for node in active_rcsd_nodes if node.geometry.intersects(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M))]
    candidate_roads = [road for road in active_rcsd_roads if road.geometry.intersects(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M))]
    active_degree2_connector_candidate_node_ids = {
        node.node_id
        for node in candidate_nodes
        if node_degree_map.get(node.node_id, 0) == 2
    }
    degree2_connector_candidate_node_ids = (
        raw_degree2_connector_candidate_node_ids | active_degree2_connector_candidate_node_ids
    ) - same_path_chain_terminal_rcsdnode_ids
    road_chain_id_by_road_id, road_chain_members_by_chain_id = _build_degree2_rcsdroad_chains(
        candidate_roads,
        degree2_connector_candidate_node_ids,
    )

    grouped_candidate_nodes: dict[str, list[NodeRecord]] = defaultdict(list)
    compact_group_id_by_node = _compact_group_id_by_node(active_rcsd_nodes)
    for node in candidate_nodes:
        grouped_candidate_nodes[compact_group_id_by_node.get(node.node_id, node.node_id)].append(node)

    for group_nodes in grouped_candidate_nodes.values():
        eligible_group_nodes = [
            node
            for node in group_nodes
            if node.node_id not in degree2_connector_candidate_node_ids
            and node_degree_map.get(node.node_id, 0) > 0
        ]
        required_min_degree = 1 if template_result.template_class == "single_sided_t_mouth" else 3
        eligible_group_nodes = [
            node
            for node in eligible_group_nodes
            if node_degree_map.get(node.node_id, 0) >= required_min_degree
        ]
        if not eligible_group_nodes:
            continue
        group_incident_roads: list[RoadRecord] = []
        for node in eligible_group_nodes:
            group_incident_roads.extend(_incident_roads(candidate_roads, node))
        group_incident_roads = list({road.road_id: road for road in group_incident_roads}.values())
        if not group_incident_roads:
            continue
        overlap_count = sum(1 for road in group_incident_roads if road.geometry.intersects(selected_corridor.buffer(REQUIRED_NODE_CORRIDOR_BUFFER_M)))
        if overlap_count <= 0 and not any(node.geometry.buffer(6.0).intersects(selected_corridor) for node in eligible_group_nodes):
            continue
        for node in eligible_group_nodes:
            required_node_ids.add(node.node_id)
            required_nodes.append(node)

    required_nodes = [node for node in candidate_nodes if node.node_id in required_node_ids]
    (
        required_node_ids,
        required_rcsdnode_gate_audit,
        required_rcsdnode_gate_dropped_ids,
    ) = _apply_required_rcsdnode_template_gate(
        context=context,
        required_node_ids=required_node_ids,
        grouped_candidate_nodes=grouped_candidate_nodes,
        node_degree_map=node_degree_map,
    )
    required_nodes = [node for node in candidate_nodes if node.node_id in required_node_ids]
    (
        required_node_ids,
        t_mouth_strong_related_rcsdnode_ids,
        t_mouth_strong_related_overflow_rcsdnode_ids,
    ) = _select_single_sided_t_mouth_strong_nodes(
        context=context,
        required_nodes=required_nodes,
        selected_corridor=selected_corridor,
    )
    required_nodes = [node for node in candidate_nodes if node.node_id in required_node_ids]
    single_sided_terminal_required_rcsdnode_ids: set[str] = set()
    single_sided_terminal_pruned_rcsdroad_ids: set[str] = set()
    overflow_node_ids = set(t_mouth_strong_related_overflow_rcsdnode_ids)
    has_isolated_overflow_group = any(
        bool({node.node_id for node in group_nodes} & overflow_node_ids)
        and not bool({node.node_id for node in group_nodes} & required_node_ids)
        for group_nodes in grouped_candidate_nodes.values()
    )
    if template_result.template_class == "single_sided_t_mouth" and has_isolated_overflow_group:
        anchor_local_node_ids = {
            node.node_id
            for node in required_nodes
            if node.geometry.distance(anchor_point) <= SINGLE_SIDED_REQUIRED_CORE_ANCHOR_DISTANCE_M
        }
        if anchor_local_node_ids:
            single_sided_terminal_required_rcsdnode_ids = {
                node.node_id
                for node in required_nodes
                if node.node_id not in anchor_local_node_ids
                and node.geometry.distance(anchor_point) > SINGLE_SIDED_REQUIRED_CORE_ANCHOR_DISTANCE_M * 2.0
            }
            required_node_ids -= single_sided_terminal_required_rcsdnode_ids
            single_sided_terminal_pruned_rcsdroad_ids = {
                road.road_id
                for road in candidate_roads
                if set(_endpoint_node_ids(road)) & single_sided_terminal_required_rcsdnode_ids
                and not set(_endpoint_node_ids(road)) & required_node_ids
            }
            t_mouth_strong_related_rcsdnode_ids = _sorted_ids(
                set(t_mouth_strong_related_rcsdnode_ids) - single_sided_terminal_required_rcsdnode_ids
            )
    for gate_row in required_rcsdnode_gate_audit.values():
        if gate_row.get("gate_decision") == "dropped":
            continue
        retained_member_ids = set(gate_row["required_member_rcsdnode_ids"]) & required_node_ids
        if retained_member_ids:
            gate_row["required_member_rcsdnode_ids"] = _sorted_ids(retained_member_ids)
            continue
        if set(gate_row["required_member_rcsdnode_ids"]) & single_sided_terminal_required_rcsdnode_ids:
            gate_row["gate_decision"] = "dropped"
            gate_row["gate_reason"] = "single_sided_remote_terminal_node_pruned_at_next_semantic_boundary"
            continue
        gate_row["gate_decision"] = "dropped"
        gate_row["gate_reason"] = "single_sided_t_mouth_overflow_after_strong_pair_selection"
    required_nodes = [node for node in candidate_nodes if node.node_id in required_node_ids]
    required_road_ids = _collect_required_road_ids_for_nodes(
        required_nodes=required_nodes,
        candidate_roads=candidate_roads,
        selected_corridor=selected_corridor,
    )
    if single_sided_terminal_required_rcsdnode_ids:
        road_by_id = {road.road_id: road for road in candidate_roads}
        for road_id in list(required_road_ids):
            endpoint_node_ids = set(_endpoint_node_ids(road_by_id[road_id]))
            if endpoint_node_ids & single_sided_terminal_required_rcsdnode_ids and not endpoint_node_ids & required_node_ids:
                required_road_ids.remove(road_id)
                single_sided_terminal_pruned_rcsdroad_ids.add(road_id)

    required_road_ids = _expand_rcsdroad_ids_via_degree2_chains(
        required_road_ids,
        chain_id_by_road_id=road_chain_id_by_road_id,
        chain_members_by_chain_id=road_chain_members_by_chain_id,
    )
    required_roads = [road for road in candidate_roads if road.road_id in required_road_ids]
    required_roads = list({road.road_id: road for road in required_roads}.values())

    support_fragments_by_road_id: dict[str, BaseGeometry] = {}
    for road in candidate_roads:
        if road.road_id in required_road_ids:
            continue
        if not road.geometry.intersects(selected_corridor.buffer(SUPPORT_CORRIDOR_BUFFER_M)):
            continue
        fragment = _build_support_fragment(
            road,
            allowed_space=allowed_space,
            selected_corridor=selected_corridor,
            anchor_point=anchor_point,
        )
        if fragment is None:
            continue
        if fragment.length < road.geometry.length * 0.95:
            hook_shrunk_road_ids.append(road.road_id)
        support_fragments_by_road_id[road.road_id] = fragment
    support_fragments_by_chain_id = _group_support_fragments_by_degree2_chain(
        support_fragments_by_road_id,
        chain_id_by_road_id=road_chain_id_by_road_id,
    )
    support_fragments_by_chain_id, dropped_parallel_support_chain_ids = _prune_parallel_support_duplicates(
        context=context,
        support_fragments_by_id=support_fragments_by_chain_id,
        anchor_point=anchor_point,
        vertical_exit_geometry=vertical_exit_geometry,
    )
    retained_support_chain_ids = set(support_fragments_by_chain_id.keys())
    support_road_ids = _expand_rcsdroad_ids_via_degree2_chains(
        (
            road_id
            for road_id, chain_id in road_chain_id_by_road_id.items()
            if chain_id in retained_support_chain_ids
        ),
        chain_id_by_road_id=road_chain_id_by_road_id,
        chain_members_by_chain_id=road_chain_members_by_chain_id,
    )
    support_road_ids -= required_road_ids
    dropped_parallel_support_road_ids = _sorted_ids(
        road_id
        for chain_id in dropped_parallel_support_chain_ids
        for road_id in road_chain_members_by_chain_id.get(chain_id, (chain_id,))
    )
    support_roads = [road for road in candidate_roads if road.road_id in support_road_ids]
    support_roads = list({road.road_id: road for road in support_roads}.values())
    support_fragments = [
        support_fragments_by_chain_id[chain_id]
        for chain_id in _sorted_ids(retained_support_chain_ids)
        if chain_id in support_fragments_by_chain_id
    ]
    if support_road_ids:
        hook_shrunk_road_ids = [road_id for road_id in hook_shrunk_road_ids if road_id in support_road_ids]

    if required_node_ids:
        association_class = "A"
    elif support_road_ids:
        association_class = "B"
    else:
        association_class = "C"
    association_reason = {
        "A": "required_rcsd_semantic_core_present",
        "B": "support_only_hook_zone",
        "C": "no_related_rcsd",
    }[association_class]

    for node in candidate_nodes:
        if node.node_id in required_node_ids:
            continue
        if node.node_id in t_mouth_strong_related_overflow_rcsdnode_ids:
            continue
        if node.node_id in degree2_connector_candidate_node_ids:
            continue
        if node_degree_map.get(node.node_id, 0) <= 0:
            continue
        if node.geometry.buffer(6.0).intersects(selected_corridor.buffer(SUPPORT_CORRIDOR_BUFFER_M)):
            support_node_ids.add(node.node_id)

    related_local_road_ids = set(required_road_ids)
    related_outside_scope_road_ids, related_outside_scope_road_audit = _build_related_outside_scope_rcsdroad_ids(
        active_rcsd_nodes=active_rcsd_nodes,
        active_rcsd_roads=active_rcsd_roads,
        required_rcsdroad_ids=set(required_road_ids),
        candidate_rcsdnode_ids={node.node_id for node in candidate_nodes},
        allowed_space=allowed_space,
        node_degree_map=node_degree_map,
    )
    related_road_ids = related_local_road_ids | related_outside_scope_road_ids
    related_node_ids, related_group_road_ids, related_rcsdnode_group_audit = _build_related_rcsd_group_ids(
        active_rcsd_nodes=active_rcsd_nodes,
        active_rcsd_roads=active_rcsd_roads,
        seed_rcsdnode_ids=set(required_node_ids),
        related_rcsdroad_ids=related_road_ids,
        node_degree_map=node_degree_map,
    )
    related_road_ids |= related_group_road_ids

    rcsd_semantic_core_missing = association_class == "B" and not required_node_ids
    foreign_result = build_association_foreign_result(
        context=context,
        active_rcsd_nodes=active_rcsd_nodes,
        active_rcsd_roads=active_rcsd_roads,
        required_rcsdnode_ids=required_node_ids,
        support_rcsdnode_ids=support_node_ids,
        required_rcsdroad_ids=required_road_ids,
        support_rcsdroad_ids=support_road_ids,
        related_rcsdnode_ids=related_node_ids,
        related_rcsdroad_ids=related_road_ids,
        node_degree_map=node_degree_map,
    )

    required_road_geometry = _union_lines(
        _clip_required_road(road, allowed_space) for road in required_roads
    )
    support_road_geometry = _union_lines(support_fragments)
    hook_zone_geometry = _clean_geometry(
        unary_union(
            [
                fragment.buffer(HOOK_ZONE_BUFFER_M, cap_style=2, join_style=2)
                for fragment in support_fragments
            ]
        )
    ) if support_fragments else None
    if hook_zone_geometry is not None:
        hook_zone_geometry = _clean_geometry(hook_zone_geometry.intersection(allowed_space.buffer(RCSD_ALLOWED_BUFFER_M)))

    if association_class == "B" and hook_zone_geometry is None:
        association_state = "not_established"
        reason = "association_missing_hook_zone"
    elif association_class == "B":
        association_state = "review"
        reason = "association_support_only"
    elif association_class == "C":
        association_state = "review" if step3_state == "review" else "established"
        reason = "association_upstream_step3_review" if step3_state == "review" else "association_no_related_rcsd"
    else:
        association_state = "review" if step3_state == "review" else "established"
        reason = "association_upstream_step3_review" if step3_state == "review" else "association_established"

    output_geometries = AssociationOutputGeometries(
        required_rcsdnode_geometry=_union_points(node.geometry for node in candidate_nodes if node.node_id in required_node_ids),
        required_rcsdroad_geometry=required_road_geometry,
        support_rcsdnode_geometry=_union_points(node.geometry for node in candidate_nodes if node.node_id in support_node_ids),
        support_rcsdroad_geometry=support_road_geometry,
        excluded_rcsdnode_geometry=foreign_result.excluded_rcsdnode_geometry,
        excluded_rcsdroad_geometry=foreign_result.excluded_rcsdroad_geometry,
        required_hook_zone_geometry=hook_zone_geometry,
        foreign_swsd_context_geometry=foreign_result.foreign_swsd_context_geometry,
        foreign_rcsd_context_geometry=foreign_result.foreign_rcsd_context_geometry,
        related_rcsdroad_geometry=_union_lines(
            road.geometry for road in active_rcsd_roads if road.road_id in related_road_ids
        ),
        u_turn_rcsdroad_geometry=_union_lines(
            road.geometry for road in active_rcsd_roads_raw if road.road_id in u_turn_rcsdroad_ids
        ),
    )

    key_metrics = {
        "active_rcsdnode_count": len(active_rcsd_nodes),
        "active_rcsdroad_count": len(active_rcsd_roads),
        "u_turn_rcsdroad_count": len(u_turn_rcsdroad_ids),
        "candidate_rcsdnode_count": len(candidate_nodes),
        "candidate_rcsdroad_count": len(candidate_roads),
        "required_rcsdnode_count": len(required_node_ids),
        "required_rcsdroad_count": len(required_road_ids),
        "support_rcsdnode_count": len(support_node_ids),
        "support_rcsdroad_count": len(support_road_ids),
        "excluded_rcsdnode_count": len(foreign_result.excluded_rcsdnode_ids),
        "excluded_rcsdroad_count": len(foreign_result.excluded_rcsdroad_ids),
        "related_rcsdnode_count": len(related_node_ids),
        "related_rcsdroad_count": len(related_road_ids),
        "related_group_rcsdroad_count": len(related_group_road_ids),
        "related_outside_scope_rcsdroad_count": len(related_outside_scope_road_ids),
        "foreign_mask_source_rcsdroad_count": len(foreign_result.excluded_rcsdroad_ids),
        "nonsemantic_connector_rcsdnode_count": len(foreign_result.nonsemantic_connector_rcsdnode_ids),
        "true_foreign_rcsdnode_count": len(foreign_result.true_foreign_rcsdnode_ids),
        "hook_zone_present": hook_zone_geometry is not None,
        "hook_zone_area_m2": round(hook_zone_geometry.area, 6) if hook_zone_geometry is not None else 0.0,
        "step3_allowed_area_m2": round(allowed_space.area, 6),
        "current_swsd_surface_area_m2": round(current_swsd_surface.area, 6),
        "parallel_support_duplicate_drop_count": len(dropped_parallel_support_road_ids),
    }
    audit_doc = {
        "step3_prerequisite": {
            "step3_state": step3_state,
            "step3_reason": context.step3_status_doc.get("reason"),
            "step3_case_dir": str(context.step3_case_dir),
            "selected_road_ids": list(context.selected_road_ids),
            "step3_excluded_road_ids": list(context.step3_excluded_road_ids),
        },
        "step4": {
            "association_class": association_class,
            "association_executed": True,
            "association_reason": association_reason,
            "association_blocker": None,
            "current_swsd_surface_area_m2": round(current_swsd_surface.area, 6),
            "active_rcsdnode_ids": [node.node_id for node in active_rcsd_nodes],
            "active_rcsdroad_ids_before_u_turn_filter": [road.road_id for road in active_rcsd_roads_raw],
            "active_rcsdroad_ids": [road.road_id for road in active_rcsd_roads],
            "u_turn_detection_mode": _u_turn_detection_mode(active_rcsd_roads_raw),
            "u_turn_formway_bit": UTURN_FORMWAY_BIT,
            "u_turn_rcsdroad_ids": _sorted_ids(u_turn_rcsdroad_ids),
            "u_turn_rcsdroad_audit": {
                road_id: u_turn_rcsdroad_audit[road_id]
                for road_id in _sorted_ids(u_turn_rcsdroad_ids)
            },
            "u_turn_candidate_rcsdroad_audit": {
                road_id: u_turn_rcsdroad_audit[road_id]
                for road_id in _sorted_ids(u_turn_candidate_rcsdroad_ids)
            },
            "u_turn_candidate_rcsdroad_ids": _sorted_ids(u_turn_candidate_rcsdroad_ids),
            "u_turn_suspect_rcsdroad_audit": {
                road_id: u_turn_rcsdroad_audit[road_id]
                for road_id in _sorted_ids(u_turn_suspect_rcsdroad_ids)
            },
            "u_turn_suspect_rcsdroad_ids": _sorted_ids(u_turn_suspect_rcsdroad_ids),
            "u_turn_rejected_by_same_path_chain_ids": _sorted_ids(u_turn_rejected_by_same_path_chain_ids),
            "same_path_chain_protected_rcsdroad_ids": _sorted_ids(same_path_protected_rcsdroad_ids),
            "same_path_chain_terminal_rcsdnode_ids": _sorted_ids(same_path_chain_terminal_rcsdnode_ids),
            "same_path_rcsdroad_chain_groups": {
                chain_id: list(member_ids)
                for chain_id, member_ids in sorted(same_path_chain_groups.items())
            },
            "same_path_rcsdroad_chain_terminal_groups": {
                chain_id: list(member_ids)
                for chain_id, member_ids in sorted(same_path_chain_terminal_groups.items())
            },
            "ignored_outside_current_swsd_surface_rcsdnode_ids": ignored_outside_current_swsd_surface_rcsdnode_ids,
            "ignored_outside_current_swsd_surface_rcsdroad_ids": ignored_outside_current_swsd_surface_rcsdroad_ids,
            "candidate_rcsdnode_ids": [node.node_id for node in candidate_nodes],
            "candidate_rcsdroad_ids": [road.road_id for road in candidate_roads],
            "required_rcsdnode_ids": _sorted_ids(required_node_ids),
            "required_rcsdroad_ids": _sorted_ids(required_road_ids),
            "support_rcsdnode_ids": _sorted_ids(support_node_ids),
            "support_rcsdroad_ids": _sorted_ids(support_road_ids),
            "related_rcsdnode_ids": _sorted_ids(related_node_ids),
            "related_rcsdroad_ids": _sorted_ids(related_road_ids),
            "related_local_rcsdroad_ids": _sorted_ids(related_local_road_ids),
            "related_group_rcsdroad_ids": _sorted_ids(related_group_road_ids),
            "related_outside_scope_rcsdroad_ids": _sorted_ids(related_outside_scope_road_ids),
            "related_outside_scope_rcsdroad_audit": {
                road_id: related_outside_scope_road_audit[road_id]
                for road_id in _sorted_ids(related_outside_scope_road_ids)
            },
            "related_rcsdnode_group_audit": {
                group_id: related_rcsdnode_group_audit[group_id]
                for group_id in _sorted_ids(related_rcsdnode_group_audit.keys())
            },
            "t_mouth_strong_related_rcsdnode_ids": t_mouth_strong_related_rcsdnode_ids,
            "t_mouth_strong_related_overflow_rcsdnode_ids": t_mouth_strong_related_overflow_rcsdnode_ids,
            "single_sided_terminal_required_rcsdnode_ids": _sorted_ids(single_sided_terminal_required_rcsdnode_ids),
            "single_sided_terminal_pruned_rcsdroad_ids": _sorted_ids(single_sided_terminal_pruned_rcsdroad_ids),
            "required_rcsdnode_gate_dropped_ids": required_rcsdnode_gate_dropped_ids,
            "required_rcsdnode_gate_audit": {
                group_id: required_rcsdnode_gate_audit[group_id]
                for group_id in _sorted_ids(required_rcsdnode_gate_audit.keys())
            },
            "single_sided_vertical_exit_selected_road_ids": [
                road_id
                for road_id in context.selected_road_ids
                if road_id not in {
                    str(item)
                    for item in (context.step3_status_doc.get("single_sided_horizontal_pair_road_ids") or [])
                    if item is not None and str(item) != ""
                }
            ],
            "parallel_support_duplicate_dropped_rcsdroad_ids": dropped_parallel_support_road_ids,
            "degree2_merged_rcsdroad_groups": {
                chain_id: list(member_ids)
                for chain_id, member_ids in sorted(road_chain_members_by_chain_id.items())
                if len(member_ids) > 1
            },
            "degree2_connector_candidate_rcsdnode_ids": _sorted_ids(degree2_connector_candidate_node_ids),
            "raw_degree2_connector_candidate_rcsdnode_ids": _sorted_ids(raw_degree2_connector_candidate_node_ids),
            "active_degree2_connector_candidate_rcsdnode_ids": _sorted_ids(active_degree2_connector_candidate_node_ids),
            "rcsdnode_degree_map": {node_id: int(node_degree_map.get(node_id, 0)) for node_id in _sorted_ids(node_degree_map.keys())},
            "raw_rcsdnode_degree_map": {node_id: int(raw_node_degree_map.get(node_id, 0)) for node_id in _sorted_ids(raw_node_degree_map.keys())},
            "hook_zone_shrunk_road_ids": _sorted_ids(hook_shrunk_road_ids),
            "grouped_candidate_node_ids": {
                group_id: [node.node_id for node in nodes]
                for group_id, nodes in sorted(grouped_candidate_nodes.items())
            },
        },
        "step5": {
            **foreign_result.audit_doc,
            "association_class": association_class,
            "association_executed": True,
            "association_reason": association_reason,
            "association_blocker": None,
        },
        "joint_phase": {
            "association_state": association_state,
            "reason": reason,
            "association_executed": True,
            "association_reason": association_reason,
            "association_blocker": None,
            "rcsd_semantic_core_missing": rcsd_semantic_core_missing,
            "allowed_space_area_m2": round(allowed_space.area, 6),
            "current_swsd_surface_area_m2": round(current_swsd_surface.area, 6),
        },
    }
    extra_status_fields = {
        **base_extra_fields,
        "current_swsd_surface_area_m2": round(current_swsd_surface.area, 6),
        "u_turn_rcsdroad_ids": audit_doc["step4"]["u_turn_rcsdroad_ids"],
        "required_rcsdnode_ids": audit_doc["step4"]["required_rcsdnode_ids"],
        "required_rcsdroad_ids": audit_doc["step4"]["required_rcsdroad_ids"],
        "support_rcsdnode_ids": audit_doc["step4"]["support_rcsdnode_ids"],
        "support_rcsdroad_ids": audit_doc["step4"]["support_rcsdroad_ids"],
        "excluded_rcsdnode_ids": list(foreign_result.excluded_rcsdnode_ids),
        "excluded_rcsdroad_ids": list(foreign_result.excluded_rcsdroad_ids),
        "related_rcsdnode_ids": audit_doc["step4"]["related_rcsdnode_ids"],
        "related_rcsdroad_ids": audit_doc["step4"]["related_rcsdroad_ids"],
        "related_local_rcsdroad_ids": audit_doc["step4"]["related_local_rcsdroad_ids"],
        "related_group_rcsdroad_ids": audit_doc["step4"]["related_group_rcsdroad_ids"],
        "related_outside_scope_rcsdroad_ids": audit_doc["step4"]["related_outside_scope_rcsdroad_ids"],
        "foreign_mask_source_rcsdroad_ids": list(foreign_result.excluded_rcsdroad_ids),
        "u_turn_detection_mode": audit_doc["step4"]["u_turn_detection_mode"],
        "u_turn_formway_bit": audit_doc["step4"]["u_turn_formway_bit"],
        "u_turn_candidate_rcsdroad_ids": audit_doc["step4"]["u_turn_candidate_rcsdroad_ids"],
        "u_turn_suspect_rcsdroad_ids": audit_doc["step4"]["u_turn_suspect_rcsdroad_ids"],
        "u_turn_rejected_by_same_path_chain_ids": audit_doc["step4"]["u_turn_rejected_by_same_path_chain_ids"],
        "same_path_chain_protected_rcsdroad_ids": audit_doc["step4"]["same_path_chain_protected_rcsdroad_ids"],
        "same_path_chain_terminal_rcsdnode_ids": audit_doc["step4"]["same_path_chain_terminal_rcsdnode_ids"],
        "same_path_rcsdroad_chain_groups": audit_doc["step4"]["same_path_rcsdroad_chain_groups"],
        "same_path_rcsdroad_chain_terminal_groups": audit_doc["step4"]["same_path_rcsdroad_chain_terminal_groups"],
        "t_mouth_strong_related_rcsdnode_ids": audit_doc["step4"]["t_mouth_strong_related_rcsdnode_ids"],
        "t_mouth_strong_related_overflow_rcsdnode_ids": audit_doc["step4"]["t_mouth_strong_related_overflow_rcsdnode_ids"],
        "single_sided_terminal_required_rcsdnode_ids": audit_doc["step4"][
            "single_sided_terminal_required_rcsdnode_ids"
        ],
        "single_sided_terminal_pruned_rcsdroad_ids": audit_doc["step4"][
            "single_sided_terminal_pruned_rcsdroad_ids"
        ],
        "required_rcsdnode_gate_dropped_ids": audit_doc["step4"]["required_rcsdnode_gate_dropped_ids"],
        "required_rcsdnode_gate_audit": audit_doc["step4"]["required_rcsdnode_gate_audit"],
        "association_executed": True,
        "association_reason": association_reason,
        "association_blocker": None,
        "rcsd_semantic_core_missing": rcsd_semantic_core_missing,
        "nonsemantic_connector_rcsdnode_ids": list(foreign_result.nonsemantic_connector_rcsdnode_ids),
        "true_foreign_rcsdnode_ids": list(foreign_result.true_foreign_rcsdnode_ids),
        "degree2_connector_candidate_rcsdnode_ids": audit_doc["step4"]["degree2_connector_candidate_rcsdnode_ids"],
        "degree2_merged_rcsdroad_groups": audit_doc["step4"]["degree2_merged_rcsdroad_groups"],
        "ignored_outside_current_swsd_surface_rcsdnode_ids": ignored_outside_current_swsd_surface_rcsdnode_ids,
        "ignored_outside_current_swsd_surface_rcsdroad_ids": ignored_outside_current_swsd_surface_rcsdroad_ids,
        "parallel_support_duplicate_dropped_rcsdroad_ids": dropped_parallel_support_road_ids,
        "hook_zone_shrunk_road_ids": audit_doc["step4"]["hook_zone_shrunk_road_ids"],
        "u_turn_rcsdroad_audit": audit_doc["step4"]["u_turn_rcsdroad_audit"],
        "u_turn_candidate_rcsdroad_audit": audit_doc["step4"]["u_turn_candidate_rcsdroad_audit"],
        "u_turn_suspect_rcsdroad_audit": audit_doc["step4"]["u_turn_suspect_rcsdroad_audit"],
        "related_outside_scope_rcsdroad_audit": audit_doc["step4"]["related_outside_scope_rcsdroad_audit"],
        "related_rcsdnode_group_audit": audit_doc["step4"]["related_rcsdnode_group_audit"],
    }
    return AssociationCaseResult(
        case_id=step1.case_spec.case_id,
        template_class=template_result.template_class,
        association_class=association_class,
        association_state=association_state,
        association_established=association_state == "established",
        reason=reason,
        visual_review_class=_visual_review_class(association_state, reason),
        root_cause_layer=None if association_state == "established" else "association",
        root_cause_type=None if association_state == "established" else reason,
        output_geometries=output_geometries,
        key_metrics=key_metrics,
        audit_doc=audit_doc,
        extra_status_fields=extra_status_fields,
    )
