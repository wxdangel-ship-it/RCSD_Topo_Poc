from __future__ import annotations

import heapq
import math
from collections import defaultdict, deque
from typing import Any, Iterable

from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
)
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring, unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.models import (
    RoadRecord,
    Step1Context,
    Step2TemplateResult,
    Step3CaseResult,
    Step3NegativeMasks,
)


ROAD_BUFFER_M = 8.0
NODE_BUFFER_M = 5.0
NEGATIVE_MASK_BUFFER_M = 1.0
STEP3_DISTANCE_CAP_M = 50.0
INTRUSION_AREA_TOLERANCE_M2 = 0.05
DRIVEZONE_OUTSIDE_AREA_TOLERANCE_M2 = 0.05
ADJACENT_REVERSE_MASK_LENGTH_M = 1.0
OPPOSITE_RC_ROAD_MAX_SWSD_GAP_M = 10.0
OPPOSITE_RC_ROAD_MAX_REFERENCE_DISTANCE_M = 35.0
OPPOSITE_RC_ROAD_MIN_DIRECTION_SIM = 0.85
OPPOSITE_RC_ROAD_MIN_REVERSE_DIRECTION_DOT = 0.85
OPPOSITE_RC_NODE_MAX_CORRIDOR_DISTANCE_M = 10.0
OPPOSITE_RC_ROAD_MAX_PROTECTED_OVERLAP_M = 3.0
DIRECTION_MODE = "t02_direction_plus_bidirectional_junction_trace"


def _rule_d_fallback_fields(*, growth_limits: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    fallback_applied = any(bool(item.get("cap_hit")) for item in (growth_limits or []))
    return {
        "rule_d_fallback_applied": fallback_applied,
        "rule_d_fallback_distance_m": STEP3_DISTANCE_CAP_M if fallback_applied else None,
        "rule_d_fallback_reason": "no_earlier_boundary_found" if fallback_applied else None,
    }


def _two_node_t_bridge_closeout_defaults() -> dict[str, Any]:
    return {
        "two_node_t_bridge_applied": False,
        "two_node_t_bridge_length_m": 0.0,
        "two_node_t_bridge_inside_drivezone_length_m": 0.0,
        "two_node_t_bridge_clipped_to_drivezone": False,
        "two_node_t_bridge_blocked": False,
        "two_node_t_bridge_reason": "not_applicable",
        "double_node_bridge_in_allowed_space": False,
    }


def _shared_two_in_two_out_closeout_fields(shared_two_in_two_out: dict[str, Any] | None = None) -> dict[str, Any]:
    shared_two_in_two_out = shared_two_in_two_out or {}
    return {
        "shared_two_in_two_out_node_detected": bool(shared_two_in_two_out.get("detected", False)),
        "shared_two_in_two_out_node_id": shared_two_in_two_out.get("node_id"),
        "shared_two_in_two_out_as_through_node": bool(shared_two_in_two_out.get("as_through_node", False)),
        "frontier_interruption_skipped_by_two_in_two_out": bool(
            shared_two_in_two_out.get("frontier_interruption_skipped", False)
        ),
        "through_node_shared_2in2out": bool(shared_two_in_two_out.get("as_through_node", False)),
        "through_node_break_suppressed": bool(shared_two_in_two_out.get("frontier_interruption_skipped", False)),
    }


def _rule_a_target_core_protection_fields(adjacent_suppressed_records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "suppressed_count": len(adjacent_suppressed_records),
        "target_core_protection_applied": bool(adjacent_suppressed_records),
        "target_core_protection_reason": (
            "target_core_or_bridge_overlap" if adjacent_suppressed_records else None
        ),
    }


def _single_sided_direction_resolution_fields(
    resolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolution = resolution or {}
    pair_road_ids = resolution.get("horizontal_pair_road_ids") or []
    return {
        "single_sided_horizontal_pair_detected": bool(resolution.get("horizontal_pair_detected", False)),
        "single_sided_horizontal_pair_road_ids": sorted(pair_road_ids),
        "single_sided_horizontal_pair_divergence_m": resolution.get("horizontal_pair_divergence_m"),
        "single_sided_direction_resolution_mode": resolution.get("resolution_mode"),
    }


def _rcsd_opposite_fallback_fields(fields: dict[str, Any] | None = None) -> dict[str, Any]:
    fields = fields or {}
    return {
        "rcsd_opposite_fallback_enabled": bool(fields.get("enabled", False)),
        "rcsd_opposite_fallback_reason": fields.get("reason"),
        "rcsd_opposite_fallback_candidate_ids": sorted(fields.get("candidate_ids", [])),
        "rcsd_opposite_fallback_selected_ids": sorted(fields.get("selected_ids", [])),
        "rcsd_opposite_fallback_suppressed_ids": sorted(fields.get("suppressed_ids", [])),
    }


def _clean_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, GeometryCollection):
        cleaned_parts = [
            cleaned
            for part in geometry.geoms
            if (cleaned := _clean_geometry(part)) is not None and not cleaned.is_empty
        ]
        if not cleaned_parts:
            return None
        merged = unary_union(cleaned_parts)
        return None if merged.is_empty else merged
    if isinstance(geometry, (Point, MultiPoint, LineString, MultiLineString)):
        return None if geometry.is_empty else geometry
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
    line_parts = [
        part
        for part in _iter_geometries(geometry)
        if part.geom_type == "LineString" and getattr(part, "length", 0.0) > 0.0
    ]
    if not line_parts:
        return None
    return _clean_geometry(unary_union(line_parts))


def _extract_polygon_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    polygon_parts = [
        part
        for part in _iter_geometries(geometry)
        if part.geom_type == "Polygon" and getattr(part, "area", 0.0) > 0.0
    ]
    if not polygon_parts:
        return None
    return _clean_geometry(unary_union(polygon_parts))


def _line_midpoint(geometry: BaseGeometry) -> Point:
    if geometry.length <= 0.0:
        centroid = geometry.centroid
        return centroid if isinstance(centroid, Point) else centroid.representative_point()
    return geometry.interpolate(geometry.length / 2.0)


def _point_like(geometry: BaseGeometry) -> Point:
    if isinstance(geometry, Point):
        return geometry
    point = geometry.representative_point()
    return point if isinstance(point, Point) else Point(point.coords[0])


def _road_vector_from_reference(road: RoadRecord, reference: Point) -> tuple[float, float]:
    coords = list(road.geometry.coords)
    start = Point(coords[0])
    end = Point(coords[-1])
    if start.distance(reference) <= end.distance(reference):
        near, far = start, end
    else:
        near, far = end, start
    vx = far.x - near.x
    vy = far.y - near.y
    norm = math.hypot(vx, vy)
    if norm <= 1e-6:
        return (1.0, 0.0)
    return (vx / norm, vy / norm)


def _geometry_axis_vector(geometry: BaseGeometry) -> tuple[float, float]:
    coords = list(geometry.coords)
    if len(coords) < 2:
        return (1.0, 0.0)
    start_x, start_y = float(coords[0][0]), float(coords[0][1])
    end_x, end_y = float(coords[-1][0]), float(coords[-1][1])
    vx = end_x - start_x
    vy = end_y - start_y
    norm = math.hypot(vx, vy)
    if norm <= 1e-6:
        return (1.0, 0.0)
    return (vx / norm, vy / norm)


def _axis_similarity(left: tuple[float, float], right: tuple[float, float]) -> float:
    return abs(left[0] * right[0] + left[1] * right[1])


def _vector_dot(left: tuple[float, float], right: tuple[float, float]) -> float:
    return left[0] * right[0] + left[1] * right[1]


def _normalized_axis_vector(vector: tuple[float, float]) -> tuple[float, float]:
    vx, vy = vector
    if vx < -1e-6 or (abs(vx) <= 1e-6 and vy < 0):
        return (-vx, -vy)
    return (vx, vy)


def _point_along_road_from_reference(
    road: RoadRecord,
    reference: Point,
    offset_m: float,
) -> Point:
    coords = list(road.geometry.coords)
    start = Point(coords[0])
    end = Point(coords[-1])
    offset = min(max(offset_m, 0.0), max(road.geometry.length, 0.0))
    if start.distance(reference) <= end.distance(reference):
        point = road.geometry.interpolate(offset)
    else:
        point = road.geometry.interpolate(max(road.geometry.length - offset, 0.0))
    return point if isinstance(point, Point) else _point_like(point)


def _road_pair_distance_trend_from_reference(
    first: RoadRecord,
    second: RoadRecord,
    reference: Point,
) -> float | None:
    min_length = min(first.geometry.length, second.geometry.length)
    if min_length <= 2.0:
        return None
    near_offset = min(5.0, max(1.0, min_length * 0.2))
    far_offset = min(20.0, max(near_offset + 1.0, min_length * 0.7))
    if far_offset <= near_offset + 1e-6:
        return None
    near_first = _point_along_road_from_reference(first, reference, near_offset)
    near_second = _point_along_road_from_reference(second, reference, near_offset)
    far_first = _point_along_road_from_reference(first, reference, far_offset)
    far_second = _point_along_road_from_reference(second, reference, far_offset)
    near_distance = float(near_first.distance(near_second))
    far_distance = float(far_first.distance(far_second))
    return far_distance - near_distance


def _road_flow_flags_for_group_like_t02(road: RoadRecord, member_node_ids: set[str]) -> tuple[bool, bool]:
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


def _directed_edge_pairs_from_t02_semantics(
    road: RoadRecord,
    *,
    force_bidirectional: bool = False,
) -> tuple[tuple[str, str], ...]:
    if road.snodeid is None or road.enodeid is None:
        return ()
    if force_bidirectional or road.direction in {0, 1} or road.snodeid == road.enodeid:
        return ((road.snodeid, road.enodeid), (road.enodeid, road.snodeid))
    if road.direction == 2:
        return ((road.snodeid, road.enodeid),)
    if road.direction == 3:
        return ((road.enodeid, road.snodeid),)
    return ()


def _build_road_graph(
    roads: tuple[RoadRecord, ...],
    *,
    force_bidirectional_road_ids: set[str] | None = None,
) -> dict[str, list[tuple[str, float, RoadRecord]]]:
    graph: dict[str, list[tuple[str, float, RoadRecord]]] = defaultdict(list)
    force_bidirectional_road_ids = force_bidirectional_road_ids or set()
    for road in roads:
        if road.geometry.length <= 0.0:
            continue
        length = float(road.geometry.length)
        for source_node_id, target_node_id in _directed_edge_pairs_from_t02_semantics(
            road,
            force_bidirectional=road.road_id in force_bidirectional_road_ids,
        ):
            graph[source_node_id].append((target_node_id, length, road))
    return graph


def _multi_source_dijkstra(
    graph: dict[str, list[tuple[str, float, RoadRecord]]],
    source_node_ids: set[str],
) -> dict[str, float]:
    distances = {node_id: 0.0 for node_id in source_node_ids}
    heap: list[tuple[float, str]] = [(0.0, node_id) for node_id in source_node_ids]
    heapq.heapify(heap)
    while heap:
        current_dist, node_id = heapq.heappop(heap)
        if current_dist > distances.get(node_id, math.inf):
            continue
        for next_node_id, edge_length, _road in graph.get(node_id, ()):
            next_dist = current_dist + edge_length
            if next_dist + 1e-6 < distances.get(next_node_id, math.inf):
                distances[next_node_id] = next_dist
                heapq.heappush(heap, (next_dist, next_node_id))
    return distances


def _clip_road_to_cap(
    road: RoadRecord,
    distances: dict[str, float],
    cap_m: float,
    *,
    force_bidirectional: bool = False,
) -> BaseGeometry | None:
    if road.snodeid is None or road.enodeid is None:
        return None
    directed_pairs = set(_directed_edge_pairs_from_t02_semantics(road, force_bidirectional=force_bidirectional))
    d_start = distances.get(road.snodeid, math.inf)
    d_end = distances.get(road.enodeid, math.inf)
    if d_start > cap_m and d_end > cap_m:
        return None
    pieces: list[BaseGeometry] = []
    if d_start <= cap_m and (road.snodeid, road.enodeid) in directed_pairs:
        keep_len = min(road.geometry.length, max(0.0, cap_m - d_start))
        pieces.append(substring(road.geometry, 0.0, keep_len))
    if d_end <= cap_m and (road.enodeid, road.snodeid) in directed_pairs:
        keep_len = min(road.geometry.length, max(0.0, cap_m - d_end))
        pieces.append(substring(road.geometry, max(0.0, road.geometry.length - keep_len), road.geometry.length))
    if not pieces:
        return None
    return _extract_line_geometry(unary_union(pieces))


def _clip_line_to_hard_bounds(
    geometry: BaseGeometry | None,
    *,
    drivezone_geometry: BaseGeometry,
    blocker_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    clipped = _extract_line_geometry(geometry.intersection(drivezone_geometry))
    if clipped is None:
        return None
    if blocker_geometry is None:
        return clipped
    return _extract_line_geometry(clipped.difference(blocker_geometry))


def _largest_line_string(geometry: BaseGeometry | None) -> LineString | None:
    line_parts = [
        part
        for part in _iter_geometries(geometry)
        if isinstance(part, LineString) and getattr(part, "length", 0.0) > 0.0
    ]
    if not line_parts:
        return None
    return max(line_parts, key=lambda item: item.length)


def _node_group_lookup(context: Step1Context) -> dict[str, str]:
    return {node.node_id: (node.mainnodeid or node.node_id) for node in context.all_nodes}


def _build_node_to_roads(roads: tuple[RoadRecord, ...]) -> dict[str, list[RoadRecord]]:
    mapping: dict[str, list[RoadRecord]] = defaultdict(list)
    for road in roads:
        if road.snodeid is not None:
            mapping[road.snodeid].append(road)
        if road.enodeid is not None and road.enodeid != road.snodeid:
            mapping[road.enodeid].append(road)
    return mapping


def _node_flow_counts(node_id: str, roads: tuple[RoadRecord, ...]) -> tuple[int, int]:
    incoming = 0
    outgoing = 0
    for road in roads:
        if road.snodeid != node_id and road.enodeid != node_id:
            continue
        if road.direction in {0, 1}:
            incoming += 1
            outgoing += 1
            continue
        if road.direction == 2:
            if road.snodeid == node_id:
                outgoing += 1
            if road.enodeid == node_id:
                incoming += 1
            continue
        if road.direction == 3:
            if road.snodeid == node_id:
                incoming += 1
            if road.enodeid == node_id:
                outgoing += 1
    return incoming, outgoing


def _detect_shared_two_in_two_out_node(context: Step1Context) -> dict[str, Any]:
    target_nodes = tuple(sorted(context.target_group.nodes, key=lambda item: item.node_id))
    if len(target_nodes) != 2:
        return {
            "detected": False,
            "node_id": None,
            "as_through_node": False,
            "frontier_interruption_skipped": False,
            "reason": "target_group_is_not_two_node",
        }

    target_node_ids = {node.node_id for node in target_nodes}
    shared_candidates: dict[str, set[str]] = defaultdict(set)
    for road in context.roads:
        if road.road_id not in context.target_road_ids:
            continue
        if road.snodeid in target_node_ids and road.enodeid not in target_node_ids and road.enodeid is not None:
            shared_candidates[road.enodeid].add(road.snodeid)
        if road.enodeid in target_node_ids and road.snodeid not in target_node_ids and road.snodeid is not None:
            shared_candidates[road.snodeid].add(road.enodeid)

    valid_candidates: list[tuple[float, str]] = []
    for node_id, touched_target_nodes in shared_candidates.items():
        if len(touched_target_nodes) < 2:
            continue
        incoming, outgoing = _node_flow_counts(node_id, context.roads)
        if incoming != 2 or outgoing != 2:
            continue
        node_geometry = None
        for node in context.all_nodes:
            if node.node_id == node_id:
                node_geometry = _point_like(node.geometry)
                break
        if node_geometry is None:
            continue
        reference = _point_like(context.representative_node.geometry)
        valid_candidates.append((reference.distance(node_geometry), node_id))

    if not valid_candidates:
        return {
            "detected": False,
            "node_id": None,
            "as_through_node": False,
            "frontier_interruption_skipped": False,
            "reason": "shared_two_in_two_out_node_not_found",
        }

    valid_candidates.sort(key=lambda item: (item[0], item[1]))
    return {
        "detected": True,
        "node_id": valid_candidates[0][1],
        "as_through_node": True,
        "frontier_interruption_skipped": True,
        "reason": "shared_two_in_two_out_node_detected",
    }


def _other_endpoint(road: RoadRecord, node_id: str) -> tuple[str | None, str | None]:
    if road.snodeid == node_id:
        return road.enodeid, "end"
    if road.enodeid == node_id:
        return road.snodeid, "start"
    return None, None


def _build_branch_frontier(
    context: Step1Context,
    *,
    through_node_ids: set[str] | None = None,
) -> tuple[set[str], set[str], list[dict[str, Any]]]:
    through_node_ids = through_node_ids or set()
    target_group_id = context.target_group.group_id
    target_node_ids = {node.node_id for node in context.target_group.nodes}
    node_group_lookup = _node_group_lookup(context)
    node_to_roads = _build_node_to_roads(context.roads)
    road_lookup = {road.road_id: road for road in context.roads}

    branch_frontier_road_ids: set[str] = set()
    adjacent_records: list[dict[str, Any]] = []
    adjacent_seen: set[tuple[str, str, str]] = set()

    queue: deque[str] = deque(sorted(target_node_ids))
    visited_nodes: set[str] = set(target_node_ids)
    while queue:
        node_id = queue.popleft()
        for road in node_to_roads.get(node_id, []):
            other_node_id, endpoint_name = _other_endpoint(road, node_id)
            if other_node_id is None or endpoint_name is None:
                continue
            branch_frontier_road_ids.add(road.road_id)
            other_group_id = node_group_lookup.get(other_node_id)
            if other_group_id is None:
                if other_node_id not in visited_nodes:
                    visited_nodes.add(other_node_id)
                    queue.append(other_node_id)
                continue
            if other_node_id in through_node_ids:
                if other_node_id not in visited_nodes:
                    visited_nodes.add(other_node_id)
                    queue.append(other_node_id)
                continue
            if other_group_id == target_group_id:
                if other_node_id not in visited_nodes:
                    visited_nodes.add(other_node_id)
                    queue.append(other_node_id)
                continue
            key = (road.road_id, endpoint_name, other_group_id)
            if key in adjacent_seen:
                continue
            adjacent_seen.add(key)
            adjacent_records.append(
                {
                    "group_id": other_group_id,
                    "road_id": road.road_id,
                    "endpoint": endpoint_name,
                    "rule": "A",
                }
            )

    related_road_ids = set(branch_frontier_road_ids)
    for road_id in list(branch_frontier_road_ids):
        road = road_lookup[road_id]
        for node_id in (road.snodeid, road.enodeid):
            if node_id is None:
                continue
            for neighbor in node_to_roads.get(node_id, []):
                related_road_ids.add(neighbor.road_id)
    return branch_frontier_road_ids, related_road_ids, adjacent_records


def _reverse_mask_strip_in_drivezone(
    road: RoadRecord,
    endpoint: str,
    drivezone_geometry: BaseGeometry,
) -> BaseGeometry | None:
    clipped_line = _largest_line_string(_extract_line_geometry(road.geometry.intersection(drivezone_geometry)))
    if clipped_line is None:
        return None
    original_coords = list(road.geometry.coords)
    if len(original_coords) < 2:
        return None
    original_endpoint = Point(original_coords[0] if endpoint == "start" else original_coords[-1])
    clipped_start = Point(clipped_line.coords[0])
    clipped_end = Point(clipped_line.coords[-1])
    clipped_endpoint = "start" if clipped_start.distance(original_endpoint) <= clipped_end.distance(original_endpoint) else "end"
    reverse_length = min(ADJACENT_REVERSE_MASK_LENGTH_M, clipped_line.length)
    if reverse_length <= 1e-6:
        return None
    if clipped_endpoint == "start":
        reverse_segment = substring(clipped_line, 0.0, reverse_length)
    else:
        reverse_segment = substring(clipped_line, max(0.0, clipped_line.length - reverse_length), clipped_line.length)
    reverse_line = _extract_line_geometry(reverse_segment)
    if reverse_line is None:
        return None
    reverse_mask = _clean_geometry(
        reverse_line.buffer(NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2).intersection(drivezone_geometry)
    )
    if reverse_mask is None:
        return None
    return reverse_mask


def _build_adjacent_junction_masks(
    context: Step1Context,
    *,
    adjacent_records: list[dict[str, Any]],
    additional_protection_geometry: BaseGeometry | None = None,
) -> tuple[BaseGeometry | None, list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    geometries: list[BaseGeometry] = []
    road_lookup = {road.road_id: road for road in context.roads}
    target_protection = _clean_geometry(
        unary_union([node.geometry.buffer(NODE_BUFFER_M) for node in context.target_group.nodes])
    )
    if target_protection is not None and additional_protection_geometry is not None:
        target_protection = _extract_polygon_geometry(unary_union([target_protection, additional_protection_geometry]))
    elif target_protection is None:
        target_protection = additional_protection_geometry
    road_ids: set[str] = set()
    filtered_records: list[dict[str, Any]] = []
    suppressed_records: list[dict[str, Any]] = []
    for record in adjacent_records:
        road = road_lookup.get(record["road_id"])
        if road is None:
            continue
        strip = _reverse_mask_strip_in_drivezone(
            road,
            record["endpoint"],
            context.drivezone_geometry,
        )
        if strip is None:
            continue
        if target_protection is not None:
            overlap = strip.intersection(target_protection)
            overlap_area = 0.0 if overlap.is_empty else float(getattr(overlap, "area", 0.0))
            if overlap_area > INTRUSION_AREA_TOLERANCE_M2:
                suppressed_records.append(
                    {
                        **record,
                        "suppress_reason": "overlaps_target_core_or_bridge",
                        "overlap_area_m2": round(overlap_area, 6),
                    }
                )
                continue
            strip = _clean_geometry(strip.difference(target_protection))
            if strip is None:
                suppressed_records.append(
                    {
                        **record,
                        "suppress_reason": "emptied_by_target_core_or_bridge_protection",
                        "overlap_area_m2": round(overlap_area, 6),
                    }
                )
                continue
        geometries.append(strip)
        road_ids.add(road.road_id)
        filtered_records.append(record)
    return _clean_geometry(unary_union(geometries)) if geometries else None, filtered_records, suppressed_records, road_ids


def _build_two_node_t_bridge_support(
    context: Step1Context,
    *,
    blocker_geometry: BaseGeometry | None,
) -> tuple[BaseGeometry | None, dict[str, Any]]:
    target_nodes = tuple(sorted(context.target_group.nodes, key=lambda item: item.node_id))
    if len(target_nodes) != 2:
        return None, {
            "two_node_t_bridge_applied": False,
            "two_node_t_bridge_length_m": 0.0,
            "two_node_t_bridge_inside_drivezone_length_m": 0.0,
            "two_node_t_bridge_clipped_to_drivezone": False,
            "two_node_t_bridge_blocked": False,
            "two_node_t_bridge_reason": "target_group_is_not_two_node",
        }

    start_point = _point_like(target_nodes[0].geometry)
    end_point = _point_like(target_nodes[1].geometry)
    raw_line = LineString([start_point, end_point])
    bridge_length_m = float(raw_line.length)
    if bridge_length_m <= 1e-6:
        return None, {
            "two_node_t_bridge_applied": False,
            "two_node_t_bridge_length_m": 0.0,
            "two_node_t_bridge_inside_drivezone_length_m": 0.0,
            "two_node_t_bridge_clipped_to_drivezone": False,
            "two_node_t_bridge_blocked": False,
            "two_node_t_bridge_reason": "degenerate_target_nodes",
        }

    inside_drivezone_line = _extract_line_geometry(raw_line.intersection(context.drivezone_geometry))
    inside_drivezone_length_m = 0.0 if inside_drivezone_line is None else float(inside_drivezone_line.length)
    if inside_drivezone_line is None:
        return None, {
            "two_node_t_bridge_applied": False,
            "two_node_t_bridge_length_m": round(bridge_length_m, 6),
            "two_node_t_bridge_inside_drivezone_length_m": 0.0,
            "two_node_t_bridge_clipped_to_drivezone": True,
            "two_node_t_bridge_blocked": True,
            "two_node_t_bridge_reason": "bridge_outside_drivezone",
        }

    hard_bound_line = _clip_line_to_hard_bounds(
        inside_drivezone_line,
        drivezone_geometry=context.drivezone_geometry,
        blocker_geometry=blocker_geometry,
    )
    if hard_bound_line is None:
        return None, {
            "two_node_t_bridge_applied": False,
            "two_node_t_bridge_length_m": round(bridge_length_m, 6),
            "two_node_t_bridge_inside_drivezone_length_m": round(inside_drivezone_length_m, 6),
            "two_node_t_bridge_clipped_to_drivezone": abs(inside_drivezone_length_m - bridge_length_m) > 1e-6,
            "two_node_t_bridge_blocked": True,
            "two_node_t_bridge_reason": "bridge_blocked_by_hard_bounds",
        }

    bridge_support = _extract_polygon_geometry(
        hard_bound_line.buffer(ROAD_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
    )
    if blocker_geometry is not None and bridge_support is not None:
        bridge_support = _extract_polygon_geometry(bridge_support.difference(blocker_geometry))
    if bridge_support is None:
        return None, {
            "two_node_t_bridge_applied": False,
            "two_node_t_bridge_length_m": round(bridge_length_m, 6),
            "two_node_t_bridge_inside_drivezone_length_m": round(inside_drivezone_length_m, 6),
            "two_node_t_bridge_clipped_to_drivezone": abs(inside_drivezone_length_m - bridge_length_m) > 1e-6,
            "two_node_t_bridge_blocked": True,
            "two_node_t_bridge_reason": "bridge_buffer_clipped_to_empty",
        }

    return bridge_support, {
        "two_node_t_bridge_applied": True,
        "two_node_t_bridge_length_m": round(bridge_length_m, 6),
        "two_node_t_bridge_inside_drivezone_length_m": round(inside_drivezone_length_m, 6),
        "two_node_t_bridge_clipped_to_drivezone": abs(inside_drivezone_length_m - bridge_length_m) > 1e-6,
        "two_node_t_bridge_blocked": False,
        "two_node_t_bridge_reason": "bridge_applied",
    }


def _build_mst_edges(points: list[Point]) -> list[LineString]:
    if len(points) < 2:
        return []
    visited = {0}
    remaining = set(range(1, len(points)))
    edges: list[LineString] = []
    while remaining:
        best_pair: tuple[int, int] | None = None
        best_distance = math.inf
        for source_index in visited:
            for target_index in remaining:
                distance = points[source_index].distance(points[target_index])
                if distance < best_distance:
                    best_distance = distance
                    best_pair = (source_index, target_index)
        if best_pair is None:
            break
        source_index, target_index = best_pair
        edges.append(LineString([points[source_index], points[target_index]]))
        visited.add(target_index)
        remaining.remove(target_index)
    return edges


def _build_foreign_mst_masks(context: Step1Context) -> tuple[BaseGeometry | None, list[dict[str, Any]]]:
    geometries: list[BaseGeometry] = []
    records: list[dict[str, Any]] = []
    for group in context.foreign_groups:
        if len(group.nodes) < 2:
            continue
        points = [_point_like(node.geometry) for node in group.nodes]
        mst_edges = _build_mst_edges(points)
        if not mst_edges:
            continue
        clipped = _extract_line_geometry(unary_union(mst_edges).intersection(context.drivezone_geometry))
        if clipped is None:
            continue
        mask = _clean_geometry(clipped.buffer(NEGATIVE_MASK_BUFFER_M))
        if mask is None:
            continue
        geometries.append(mask)
        records.append({"group_id": group.group_id, "node_count": len(group.nodes), "rule": "C"})
    return _clean_geometry(unary_union(geometries)) if geometries else None, records


def _build_candidate_roads_for_single_sided(
    context: Step1Context,
    *,
    protected_road_ids: set[str],
) -> tuple[set[str], set[str], bool, tuple[float, float] | None, dict[str, Any]]:
    def _partition_by_direction(direction: tuple[float, float]) -> tuple[set[str], set[str]]:
        vx, vy = direction
        allowed: set[str] = set()
        excluded: set[str] = set()
        for road in context.roads:
            if road.road_id in protected_road_ids:
                allowed.add(road.road_id)
                continue
            midpoint = _line_midpoint(road.geometry)
            dot = (midpoint.x - reference.x) * vx + (midpoint.y - reference.y) * vy
            if dot >= -2.0:
                allowed.add(road.road_id)
            else:
                excluded.add(road.road_id)
        return allowed, excluded

    def _detect_semantic_horizontal_pair(
        roads: list[RoadRecord],
        member_node_ids: set[str],
    ) -> dict[str, Any] | None:
        direct_target_roads = [road for road in roads if road.road_id in context.target_road_ids]
        candidate_pairs: list[dict[str, Any]] = []
        for incoming_road in direct_target_roads:
            incoming_support, outgoing_support = _road_flow_flags_for_group_like_t02(incoming_road, member_node_ids)
            if not incoming_support or outgoing_support:
                continue
            incoming_vector = _road_vector_from_reference(incoming_road, reference)
            for outgoing_road in direct_target_roads:
                if outgoing_road.road_id == incoming_road.road_id:
                    continue
                incoming_support_out, outgoing_support_out = _road_flow_flags_for_group_like_t02(
                    outgoing_road,
                    member_node_ids,
                )
                if incoming_support_out or not outgoing_support_out:
                    continue
                outgoing_vector = _road_vector_from_reference(outgoing_road, reference)
                if _axis_similarity(incoming_vector, outgoing_vector) < 0.95:
                    continue
                divergence = _road_pair_distance_trend_from_reference(incoming_road, outgoing_road, reference)
                if divergence is None or divergence <= 1.0:
                    continue
                candidate_pairs.append(
                    {
                        "horizontal_pair_road_ids": [incoming_road.road_id, outgoing_road.road_id],
                        "horizontal_pair_divergence_m": round(float(divergence), 6),
                        "direction": outgoing_vector,
                    }
                )
        if not candidate_pairs:
            return None
        candidate_pairs.sort(
            key=lambda item: (
                -item["horizontal_pair_divergence_m"],
                item["horizontal_pair_road_ids"],
            )
        )
        best_pair = candidate_pairs[0]
        return {
            "horizontal_pair_detected": True,
            "horizontal_pair_road_ids": best_pair["horizontal_pair_road_ids"],
            "horizontal_pair_divergence_m": best_pair["horizontal_pair_divergence_m"],
            "resolution_mode": "semantic_horizontal_pair",
            "direction": best_pair["direction"],
        }

    reference = _point_like(context.representative_node.geometry)
    candidate_roads = [
        road
        for road in context.roads
        if road.road_id in context.target_road_ids or road.geometry.distance(reference) <= 18.0
    ]
    if not candidate_roads:
        return (
            set(),
            {road.road_id for road in context.roads},
            True,
            None,
            {
                "horizontal_pair_detected": False,
                "horizontal_pair_road_ids": [],
                "horizontal_pair_divergence_m": None,
                "resolution_mode": "no_candidate_roads",
            },
        )
    member_node_ids = {node.node_id for node in context.target_group.nodes}
    semantic_horizontal_pair = _detect_semantic_horizontal_pair(candidate_roads, member_node_ids)
    if semantic_horizontal_pair is not None:
        allowed, excluded = _partition_by_direction(semantic_horizontal_pair["direction"])
        return (
            allowed,
            excluded,
            False,
            semantic_horizontal_pair["direction"],
            semantic_horizontal_pair,
        )
    candidate_vectors = [
        (_road_vector_from_reference(road, reference), road)
        for road in candidate_roads
    ]
    scored: list[dict[str, Any]] = []
    for (vx, vy), seed_road in candidate_vectors:
        axis_vector = _normalized_axis_vector((vx, vy))
        allowed, excluded = _partition_by_direction((vx, vy))
        score = float(len(allowed) * 10 - len(excluded))
        for road in context.roads:
            if road.road_id in allowed:
                midpoint = _line_midpoint(road.geometry)
                score += math.hypot(midpoint.x - reference.x, midpoint.y - reference.y) * 0.01

        axis_aligned_roads = [
            road
            for road in candidate_roads
            if _axis_similarity(_road_vector_from_reference(road, reference), axis_vector) >= 0.95
        ]
        incoming_axis_roads = [
            road for road in axis_aligned_roads if _road_flow_flags_for_group_like_t02(road, member_node_ids)[0]
        ]
        outgoing_axis_roads = [
            road for road in axis_aligned_roads if _road_flow_flags_for_group_like_t02(road, member_node_ids)[1]
        ]
        horizontal_pair_detected = any(
            incoming.road_id != outgoing.road_id
            for incoming in incoming_axis_roads
            for outgoing in outgoing_axis_roads
        )
        best_divergence = None
        for incoming in incoming_axis_roads:
            for outgoing in outgoing_axis_roads:
                if incoming.road_id == outgoing.road_id:
                    continue
                trend = _road_pair_distance_trend_from_reference(incoming, outgoing, reference)
                if trend is None:
                    continue
                best_divergence = trend if best_divergence is None else max(best_divergence, trend)
        if horizontal_pair_detected:
            score += 12.0
        if best_divergence is not None:
            score += max(-5.0, min(12.0, best_divergence * 0.5))

        scored.append(
            {
                "score": score,
                "allowed": allowed,
                "excluded": excluded,
                "direction": (vx, vy),
                "seed_road_id": seed_road.road_id,
                "axis_vector": axis_vector,
                "horizontal_pair_detected": horizontal_pair_detected,
                "best_divergence": best_divergence,
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    top = scored[0]
    top_score = top["score"]
    ambiguous = False
    if len(scored) > 1:
        second = scored[1]
        close_in_score = abs(top_score - second["score"]) <= max(3.0, abs(top_score) * 0.15)
        same_partition = (
            top["allowed"] == second["allowed"]
            and top["excluded"] == second["excluded"]
        )
        same_axis = _axis_similarity(top["axis_vector"], second["axis_vector"]) >= 0.97
        semantically_equivalent = same_partition or (
            same_axis
            and top["horizontal_pair_detected"]
            and second["horizontal_pair_detected"]
        )
        ambiguous = close_in_score and not semantically_equivalent
    return (
        top["allowed"],
        top["excluded"],
        ambiguous,
        top["direction"],
        {
            "horizontal_pair_detected": False,
            "horizontal_pair_road_ids": [],
            "horizontal_pair_divergence_m": None,
            "resolution_mode": "score_fallback",
        },
    )


def _split_point_side(reference: Point, point: Point, direction: tuple[float, float]) -> float:
    vx, vy = direction
    return (point.x - reference.x) * vx + (point.y - reference.y) * vy


def _build_single_sided_exclusions(
    context: Step1Context,
    direction: tuple[float, float] | None,
    *,
    protected_node_ids: set[str],
) -> tuple[set[str], set[str]]:
    if direction is None:
        return set(), set()
    reference = _point_like(context.representative_node.geometry)
    target_group_id = context.target_group.group_id
    excluded_rc_road_ids: set[str] = set()
    excluded_rc_node_ids: set[str] = set()
    for road in context.rcsd_roads:
        midpoint = _line_midpoint(road.geometry)
        if _split_point_side(reference, midpoint, direction) < -2.0:
            excluded_rc_road_ids.add(road.road_id)
    for node in context.rcsd_nodes:
        if node.mainnodeid == target_group_id or node.node_id == context.representative_node.node_id:
            continue
        if node.node_id in protected_node_ids:
            continue
        point = _point_like(node.geometry)
        if _split_point_side(reference, point, direction) < -2.0:
            excluded_rc_node_ids.add(node.node_id)
    return excluded_rc_road_ids, excluded_rc_node_ids


def _filter_opposite_rc_road_ids(
    context: Step1Context,
    *,
    excluded_opposite_road_ids: set[str],
    candidate_rc_road_ids: set[str],
    protected_road_ids: set[str],
    forward_direction: tuple[float, float] | None,
    horizontal_pair_detected: bool,
) -> tuple[set[str], dict[str, Any]]:
    candidate_ids = sorted(candidate_rc_road_ids)
    if not candidate_rc_road_ids:
        return set(), {
            "enabled": False,
            "reason": "no_candidate_rcsd_opposite",
            "candidate_ids": [],
            "selected_ids": [],
            "suppressed_ids": [],
        }
    if not horizontal_pair_detected or forward_direction is None:
        return set(), {
            "enabled": False,
            "reason": "disabled_no_semantic_horizontal_pair",
            "candidate_ids": candidate_ids,
            "selected_ids": [],
            "suppressed_ids": candidate_ids,
        }
    if excluded_opposite_road_ids:
        return set(), {
            "enabled": False,
            "reason": "disabled_swsd_opposite_present",
            "candidate_ids": candidate_ids,
            "selected_ids": [],
            "suppressed_ids": candidate_ids,
        }
    reference = _point_like(context.representative_node.geometry)
    protected_roads = [road for road in context.roads if road.road_id in protected_road_ids]
    kept: set[str] = set()
    suppressed: set[str] = set()
    for rc_road in context.rcsd_roads:
        if rc_road.road_id not in candidate_rc_road_ids:
            continue
        if reference.distance(rc_road.geometry) > OPPOSITE_RC_ROAD_MAX_REFERENCE_DISTANCE_M:
            suppressed.add(rc_road.road_id)
            continue
        reverse_dot = -_vector_dot(_road_vector_from_reference(rc_road, reference), forward_direction)
        if reverse_dot < OPPOSITE_RC_ROAD_MIN_REVERSE_DIRECTION_DOT:
            suppressed.add(rc_road.road_id)
            continue
        blocker_mask = _clean_geometry(
            rc_road.geometry.buffer(NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
        )
        if blocker_mask is None:
            suppressed.add(rc_road.road_id)
            continue
        max_protected_overlap = 0.0
        for protected_road in protected_roads:
            overlap = protected_road.geometry.intersection(blocker_mask)
            max_protected_overlap = max(max_protected_overlap, float(getattr(overlap, "length", 0.0)))
        # RCSD corridor fallback only补SWSD opposite缺口; even in fallback mode it must not
        # materialize as a hard blocker when it rides on the current protected branch geometry.
        if max_protected_overlap > OPPOSITE_RC_ROAD_MAX_PROTECTED_OVERLAP_M:
            suppressed.add(rc_road.road_id)
            continue
        kept.add(rc_road.road_id)
    return kept, {
        "enabled": bool(kept),
        "reason": "enabled_missing_swsd_opposite" if kept else "disabled_no_reverse_rcsd_candidate",
        "candidate_ids": candidate_ids,
        "selected_ids": sorted(kept),
        "suppressed_ids": sorted(set(candidate_ids) - kept),
    }


def _filter_opposite_rc_node_ids(
    context: Step1Context,
    *,
    excluded_opposite_road_ids: set[str],
    filtered_rc_road_ids: set[str],
    candidate_rc_node_ids: set[str],
) -> set[str]:
    if not candidate_rc_node_ids:
        return set()
    corridor_geometries: list[BaseGeometry] = [
        road.geometry for road in context.roads if road.road_id in excluded_opposite_road_ids
    ]
    corridor_geometries.extend(
        road.geometry for road in context.rcsd_roads if road.road_id in filtered_rc_road_ids
    )
    if not corridor_geometries:
        return set()
    reference = _point_like(context.representative_node.geometry)
    corridor_union = unary_union(corridor_geometries)
    kept: set[str] = set()
    for node in context.rcsd_nodes:
        if node.node_id not in candidate_rc_node_ids:
            continue
        if reference.distance(node.geometry) > OPPOSITE_RC_ROAD_MAX_REFERENCE_DISTANCE_M:
            continue
        if node.geometry.distance(corridor_union) <= OPPOSITE_RC_NODE_MAX_CORRIDOR_DISTANCE_M:
            kept.add(node.node_id)
    return kept


def _build_single_sided_blockers(
    context: Step1Context,
    *,
    excluded_opposite_road_ids: set[str],
    excluded_opposite_rc_road_ids: set[str],
    excluded_opposite_rc_node_ids: set[str],
) -> tuple[BaseGeometry | None, list[dict[str, Any]], list[dict[str, Any]]]:
    geometries: list[BaseGeometry] = []
    records: list[dict[str, Any]] = []
    blocked_directions: list[dict[str, Any]] = []
    for road in context.roads:
        if road.road_id not in excluded_opposite_road_ids:
            continue
        local_mask = _clean_geometry(
            road.geometry.buffer(NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
        )
        if local_mask is None:
            continue
        geometries.append(local_mask)
        records.append({"road_id": road.road_id, "rule": "E", "mode": "opposite_road_buffer"})
        blocked_directions.append({"layer": "road", "object_id": road.road_id, "reason": "single_sided_opposite_road"})
    for road in context.rcsd_roads:
        if road.road_id not in excluded_opposite_rc_road_ids:
            continue
        local_mask = _clean_geometry(
            road.geometry.buffer(NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
        )
        if local_mask is None:
            continue
        geometries.append(local_mask)
        records.append({"road_id": road.road_id, "rule": "E", "mode": "opposite_corridor_buffer"})
        blocked_directions.append({"layer": "rcsdroad", "object_id": road.road_id, "reason": "single_sided_opposite_corridor"})
    for group in context.foreign_groups:
        for node in group.nodes:
            if node.node_id not in excluded_opposite_rc_node_ids:
                continue
            mask = _clean_geometry(_point_like(node.geometry).buffer(NEGATIVE_MASK_BUFFER_M).intersection(context.drivezone_geometry))
            if mask is None:
                continue
            geometries.append(mask)
            records.append({"node_id": node.node_id, "group_id": group.group_id, "rule": "E", "mode": "opposite_semantic_node"})
            blocked_directions.append(
                {"layer": "semantic_node", "object_id": node.node_id, "reason": "single_sided_opposite_semantic_node"}
            )
    return _clean_geometry(unary_union(geometries)) if geometries else None, records, blocked_directions


def _build_reachable_road_support(
    context: Step1Context,
    *,
    allowed_road_ids: set[str] | None = None,
    blocker_geometry: BaseGeometry | None = None,
    force_bidirectional_road_ids: set[str] | None = None,
    cap_m: float = STEP3_DISTANCE_CAP_M,
) -> tuple[BaseGeometry | None, list[dict[str, Any]], set[str], list[str]]:
    roads = tuple(road for road in context.roads if allowed_road_ids is None or road.road_id in allowed_road_ids)
    source_node_ids = {node.node_id for node in context.target_group.nodes}
    force_bidirectional_road_ids = force_bidirectional_road_ids or set()
    graph = _build_road_graph(roads, force_bidirectional_road_ids=force_bidirectional_road_ids)
    distances = _multi_source_dijkstra(graph, source_node_ids)
    clipped_geometries: list[BaseGeometry] = []
    growth_limits: list[dict[str, Any]] = []
    selected_road_ids: set[str] = set()
    frontier_stop_reasons: set[str] = set()
    if allowed_road_ids is not None and len(roads) < len(context.roads):
        frontier_stop_reasons.add("template_road_filter_applied")
    for road in roads:
        clipped_to_cap = _clip_road_to_cap(
            road,
            distances,
            cap_m,
            force_bidirectional=road.road_id in force_bidirectional_road_ids,
        )
        if clipped_to_cap is None:
            continue
        drivezone_line = _extract_line_geometry(clipped_to_cap.intersection(context.drivezone_geometry))
        if drivezone_line is None:
            frontier_stop_reasons.add("drivezone_boundary")
            continue
        hard_bound_line = _clip_line_to_hard_bounds(
            drivezone_line,
            drivezone_geometry=context.drivezone_geometry,
            blocker_geometry=blocker_geometry,
        )
        if blocker_geometry is not None:
            if hard_bound_line is None:
                frontier_stop_reasons.add("hard_blocker_applied")
                continue
            if abs(hard_bound_line.length - drivezone_line.length) > 1e-6:
                frontier_stop_reasons.add("hard_blocker_applied")
        else:
            hard_bound_line = drivezone_line
        if hard_bound_line is None:
            continue
        selected_road_ids.add(road.road_id)
        buffered_support = _extract_polygon_geometry(
            hard_bound_line.buffer(ROAD_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
        )
        if blocker_geometry is not None and buffered_support is not None:
            buffered_support = _extract_polygon_geometry(buffered_support.difference(blocker_geometry))
        if buffered_support is None:
            frontier_stop_reasons.add("hard_blocker_applied" if blocker_geometry is not None else "drivezone_boundary")
            continue
        clipped_geometries.append(buffered_support)
        d_start = distances.get(road.snodeid or "", math.inf)
        d_end = distances.get(road.enodeid or "", math.inf)
        cap_hit = min(d_start, d_end) <= cap_m and max(d_start, d_end) > cap_m
        if cap_hit:
            frontier_stop_reasons.add("distance_cap_reached")
        growth_limits.append(
            {
                "road_id": road.road_id,
                "source_distance_start_m": None if math.isinf(d_start) else round(d_start, 3),
                "source_distance_end_m": None if math.isinf(d_end) else round(d_end, 3),
                "cap_m": cap_m,
                "cap_hit": bool(cap_hit),
                "incoming_support": _road_flow_flags_for_group_like_t02(road, source_node_ids)[0],
                "outgoing_support": _road_flow_flags_for_group_like_t02(road, source_node_ids)[1],
            }
        )
    target_core = _extract_polygon_geometry(unary_union([node.geometry.buffer(NODE_BUFFER_M) for node in context.target_group.nodes]))
    if target_core is not None:
        target_core = _extract_polygon_geometry(target_core.intersection(context.drivezone_geometry))
        if blocker_geometry is not None and target_core is not None:
            clipped_core = _extract_polygon_geometry(target_core.difference(blocker_geometry))
            if clipped_core is None:
                frontier_stop_reasons.add("target_core_blocked")
            target_core = clipped_core
    candidate_parts = [geometry for geometry in clipped_geometries if geometry is not None]
    if target_core is not None:
        candidate_parts.append(target_core)
    if not candidate_parts:
        return None, growth_limits, selected_road_ids, sorted(frontier_stop_reasons)
    candidate = _extract_polygon_geometry(unary_union(candidate_parts))
    return candidate, growth_limits, selected_road_ids, sorted(frontier_stop_reasons)


def _build_foreign_object_masks(
    context: Step1Context,
    *,
    frontier_candidate_road_ids: set[str],
    adjacent_cut_road_ids: set[str],
    excluded_road_ids: set[str],
    excluded_node_ids: set[str],
    protected_road_ids: set[str],
    protected_group_ids: set[str],
) -> tuple[BaseGeometry | None, list[dict[str, Any]], bool]:
    geometries: list[BaseGeometry] = []
    records: list[dict[str, Any]] = []
    node_fallback_used = False
    foreign_node_ids = {node.node_id for group in context.foreign_groups for node in group.nodes}
    masked_foreign_node_ids: set[str] = set(excluded_node_ids)
    for road in context.roads:
        if (
            road.road_id in frontier_candidate_road_ids
            or road.road_id in adjacent_cut_road_ids
            or road.road_id in excluded_road_ids
            or road.road_id in protected_road_ids
        ):
            continue
        local_mask = _clean_geometry(
            road.geometry.buffer(NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
        )
        if local_mask is None:
            continue
        geometries.append(local_mask)
        for endpoint_id in (road.snodeid, road.enodeid):
            if endpoint_id is not None and endpoint_id in foreign_node_ids:
                masked_foreign_node_ids.add(endpoint_id)
        records.append({"road_id": road.road_id, "rule": "B", "mode": "road_buffer"})
    for group in context.foreign_groups:
        if group.group_id in protected_group_ids:
            continue
        for node in group.nodes:
            if node.node_id in masked_foreign_node_ids:
                continue
            node_fallback_used = True
            mask = _clean_geometry(_point_like(node.geometry).buffer(NEGATIVE_MASK_BUFFER_M).intersection(context.drivezone_geometry))
            if mask is None:
                continue
            geometries.append(mask)
            records.append({"node_id": node.node_id, "group_id": group.group_id, "rule": "B", "mode": "node_fallback"})
    return _clean_geometry(unary_union(geometries)) if geometries else None, records, node_fallback_used


def _component_touching_target(geometry: BaseGeometry | None, target_geometry: BaseGeometry) -> BaseGeometry | None:
    cleaned = _extract_polygon_geometry(geometry)
    if cleaned is None:
        return None
    geoms: list[BaseGeometry]
    if isinstance(cleaned, MultiPolygon):
        geoms = list(cleaned.geoms)
    else:
        geoms = [cleaned]
    kept = [geom for geom in geoms if not geom.is_empty and geom.intersects(target_geometry)]
    if not kept:
        return None
    return _clean_geometry(unary_union(kept))


def _covered_node_ids(context: Step1Context, allowed_space_geometry: BaseGeometry | None) -> list[str]:
    if allowed_space_geometry is None:
        return []
    return [
        node.node_id
        for node in context.target_group.nodes
        if allowed_space_geometry.buffer(0.5).covers(node.geometry)
    ]


def _has_negative_intrusion(geometry: BaseGeometry | None, negative_union: BaseGeometry | None) -> bool:
    if geometry is None or negative_union is None:
        return False
    intersection = geometry.intersection(negative_union)
    if intersection.is_empty:
        return False
    return float(getattr(intersection, "area", 0.0)) > INTRUSION_AREA_TOLERANCE_M2


def _drivezone_containment_metrics(
    geometry: BaseGeometry | None,
    drivezone_geometry: BaseGeometry,
) -> dict[str, Any]:
    if geometry is None or geometry.is_empty:
        return {
            "allowed_area_m2": 0.0,
            "allowed_inside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_ratio": 0.0,
            "drivezone_containment_passed": False,
        }
    allowed_area = float(getattr(geometry, "area", 0.0))
    inside = geometry.intersection(drivezone_geometry)
    outside = geometry.difference(drivezone_geometry)
    inside_area = 0.0 if inside.is_empty else float(getattr(inside, "area", 0.0))
    outside_area = 0.0 if outside.is_empty else float(getattr(outside, "area", 0.0))
    outside_ratio = 0.0 if allowed_area <= 0.0 else outside_area / allowed_area
    return {
        "allowed_area_m2": round(allowed_area, 6),
        "allowed_inside_drivezone_area_m2": round(inside_area, 6),
        "allowed_outside_drivezone_area_m2": round(outside_area, 6),
        "allowed_outside_drivezone_ratio": round(outside_ratio, 9),
        "drivezone_containment_passed": outside_area <= DRIVEZONE_OUTSIDE_AREA_TOLERANCE_M2,
    }


def _build_status_doc(case_result: Step3CaseResult) -> dict[str, Any]:
    return {
        "case_id": case_result.case_id,
        "template_class": case_result.template_class,
        "step3_state": case_result.step3_state,
        "step3_established": case_result.step3_established,
        "reason": case_result.reason,
        "visual_review_class": case_result.visual_review_class,
        "root_cause_layer": case_result.root_cause_layer,
        "root_cause_type": case_result.root_cause_type,
        "key_metrics": case_result.key_metrics,
        **case_result.extra_status_fields,
    }


def _review_visual_class(step3_state: str, review_signals: list[str], reason: str) -> str:
    if step3_state == "established":
        return "V1 认可成功"
    if step3_state == "review":
        if any(signal.startswith("required") for signal in review_signals):
            return "V3 漏包 required"
        return "V2 业务正确但几何待修"
    if "foreign" in reason or "opposite" in reason:
        return "V4 误包 foreign"
    return "V5 明确失败"


def _root_cause_layer(step3_state: str) -> str | None:
    if step3_state == "established":
        return None
    return "step3"


def _empty_audit_doc(
    context: Step1Context,
    *,
    reason: str,
    input_gate: dict[str, Any],
    opposite_side_guard_mode: str = "not_applicable",
    corridor_guard_status: str = "not_applicable",
) -> dict[str, Any]:
    rule_d_fallback_fields = _rule_d_fallback_fields()
    two_node_t_bridge_fields = _two_node_t_bridge_closeout_defaults()
    shared_two_in_two_out_fields = _shared_two_in_two_out_closeout_fields()
    rcsd_opposite_fallback = _rcsd_opposite_fallback_fields()
    return {
        "input_gate": input_gate,
        "rules": {key: {"passed": False, "reason": reason} for key in "ABCDEFGH"},
        "adjacent_junction_cuts": [],
        "foreign_object_masks": [],
        "foreign_mst_masks": [],
        "growth_limits": [],
        **rule_d_fallback_fields,
        "cleanup_dependency": False,
        "must_cover_result": {
            "covered_node_ids": [],
            "missing_node_ids": [node.node_id for node in context.target_group.nodes],
        },
        "blocked_directions": [],
        "review_signals": [],
        "direction_mode": DIRECTION_MODE,
        "growth_order": "hard_bound_first",
        "hard_bound_first": True,
        "post_growth_safety_only": True,
        "frontier_stop_reason": [],
        "selected_road_ids": [],
        "excluded_road_ids": [],
        "opposite_road_ids": [],
        "opposite_semantic_node_ids": [],
        "opposite_rcsdroad_ids": [],
        "opposite_side_guard_mode": opposite_side_guard_mode,
        "corridor_guard_status": corridor_guard_status,
        "opposite_side_guard_note": None,
        **rcsd_opposite_fallback,
        "hard_path_passed": False,
        "cleanup_preview_passed": False,
        "rescue_reason": None,
        "adjacent_junction_cut_suppressed": [],
        "adjacent_junction_cut_protection_applied": False,
        "adjacent_junction_cut_protection_reason": None,
        "allowed_area_m2": 0.0,
        "allowed_inside_drivezone_area_m2": 0.0,
        "allowed_outside_drivezone_area_m2": 0.0,
        "allowed_outside_drivezone_ratio": 0.0,
        "drivezone_containment_passed": False,
        **two_node_t_bridge_fields,
        **shared_two_in_two_out_fields,
    }


def _status_for_unsupported_template(context: Step1Context, template_result: Step2TemplateResult) -> Step3CaseResult:
    reason = template_result.reason or "unsupported_template"
    input_gate = {
        "passed": context.representative_node.has_evd == "yes" and context.representative_node.is_anchor in {None, "no"},
        "reason": None,
        "has_evd": context.representative_node.has_evd,
        "is_anchor": context.representative_node.is_anchor,
    }
    audit_doc = _empty_audit_doc(context, reason=reason, input_gate=input_gate)
    rule_d_fallback_fields = _rule_d_fallback_fields()
    two_node_t_bridge_fields = _two_node_t_bridge_closeout_defaults()
    shared_two_in_two_out_fields = _shared_two_in_two_out_closeout_fields()
    single_sided_direction_resolution = _single_sided_direction_resolution_fields()
    rcsd_opposite_fallback = _rcsd_opposite_fallback_fields()
    return Step3CaseResult(
        case_id=context.case_spec.case_id,
        template_class=template_result.template_class,
        step3_state="not_established",
        step3_established=False,
        reason=reason,
        visual_review_class="V5 明确失败",
        root_cause_layer="step2",
        root_cause_type=reason,
        allowed_space_geometry=None,
        allowed_drivezone_geometry=None,
        negative_masks=Step3NegativeMasks(None, None, None),
        key_metrics={"target_group_node_count": len(context.target_group.nodes), "supported": False},
        audit_doc=audit_doc,
        extra_status_fields={
            "representative_node_id": context.representative_node.node_id,
            "target_group_node_ids": [node.node_id for node in context.target_group.nodes],
            "foreign_group_ids": [group.group_id for group in context.foreign_groups],
            "selected_road_ids": [],
            "excluded_road_ids": [],
            "blocked_direction_reasons": [],
            "cleanup_dependency": False,
            "direction_mode": DIRECTION_MODE,
            **rule_d_fallback_fields,
            **single_sided_direction_resolution,
            **rcsd_opposite_fallback,
            "allowed_area_m2": 0.0,
            "allowed_inside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_ratio": 0.0,
            "drivezone_containment_passed": False,
            **two_node_t_bridge_fields,
            **shared_two_in_two_out_fields,
        },
    )


def _status_for_input_gate_failure(
    context: Step1Context,
    template_result: Step2TemplateResult,
    *,
    input_gate: dict[str, Any],
) -> Step3CaseResult:
    reason = "input_gate_failed"
    audit_doc = _empty_audit_doc(context, reason=reason, input_gate=input_gate)
    rule_d_fallback_fields = _rule_d_fallback_fields()
    two_node_t_bridge_fields = _two_node_t_bridge_closeout_defaults()
    shared_two_in_two_out_fields = _shared_two_in_two_out_closeout_fields()
    single_sided_direction_resolution = _single_sided_direction_resolution_fields()
    rcsd_opposite_fallback = _rcsd_opposite_fallback_fields()
    return Step3CaseResult(
        case_id=context.case_spec.case_id,
        template_class=template_result.template_class,
        step3_state="not_established",
        step3_established=False,
        reason=reason,
        visual_review_class="V5 明确失败",
        root_cause_layer="step1",
        root_cause_type=reason,
        allowed_space_geometry=None,
        allowed_drivezone_geometry=None,
        negative_masks=Step3NegativeMasks(None, None, None),
        key_metrics={"target_group_node_count": len(context.target_group.nodes)},
        audit_doc=audit_doc,
        extra_status_fields={
            "representative_node_id": context.representative_node.node_id,
            "target_group_node_ids": [node.node_id for node in context.target_group.nodes],
            "foreign_group_ids": [group.group_id for group in context.foreign_groups],
            "selected_road_ids": [],
            "excluded_road_ids": [],
            "blocked_direction_reasons": [],
            "cleanup_dependency": False,
            "direction_mode": DIRECTION_MODE,
            **rule_d_fallback_fields,
            **single_sided_direction_resolution,
            **rcsd_opposite_fallback,
            "allowed_area_m2": 0.0,
            "allowed_inside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_ratio": 0.0,
            "drivezone_containment_passed": False,
            **two_node_t_bridge_fields,
            **shared_two_in_two_out_fields,
        },
    )


def build_step3_case_result(context: Step1Context, template_result: Step2TemplateResult) -> Step3CaseResult:
    if not template_result.supported:
        return _status_for_unsupported_template(context, template_result)

    input_gate = {
        "passed": context.representative_node.has_evd == "yes" and context.representative_node.is_anchor in {None, "no"},
        "reason": None,
        "has_evd": context.representative_node.has_evd,
        "is_anchor": context.representative_node.is_anchor,
    }
    if not input_gate["passed"]:
        input_gate["reason"] = "input_gate_failed"
        return _status_for_input_gate_failure(context, template_result, input_gate=input_gate)

    reference_target_geometry = unary_union([node.geometry.buffer(1.0) for node in context.target_group.nodes])
    base_allowed_road_ids: set[str] | None = None
    excluded_opposite_road_ids: set[str] = set()
    excluded_opposite_rc_road_ids: set[str] = set()
    excluded_opposite_rc_node_ids: set[str] = set()
    review_signals: list[str] = []
    opposite_side_guard_mode = "not_applicable"
    corridor_guard_status = "not_applicable"
    opposite_side_guard_note: str | None = None
    single_sided_direction_resolution = _single_sided_direction_resolution_fields()
    rcsd_opposite_fallback = _rcsd_opposite_fallback_fields()
    shared_two_in_two_out = _detect_shared_two_in_two_out_node(context)
    shared_through_node_ids = (
        {shared_two_in_two_out["node_id"]}
        if template_result.template_class == "single_sided_t_mouth"
        and shared_two_in_two_out["detected"]
        and shared_two_in_two_out["as_through_node"]
        and shared_two_in_two_out["node_id"] is not None
        else set()
    )
    bridge_protection_geometry, _bridge_preview_fields = _build_two_node_t_bridge_support(
        context,
        blocker_geometry=None,
    )
    branch_frontier_road_ids, junction_related_road_ids, adjacent_seed_records = _build_branch_frontier(
        context,
        through_node_ids=shared_through_node_ids,
    )
    adjacent_group_ids = {record["group_id"] for record in adjacent_seed_records}
    protected_group_ids = set(adjacent_group_ids)
    protected_group_ids.update(shared_through_node_ids)
    base_allowed_road_ids = set(branch_frontier_road_ids)

    if template_result.template_class == "single_sided_t_mouth":
        (
            single_sided_allowed_road_ids,
            excluded_opposite_road_ids,
            ambiguous,
            direction,
            single_sided_direction_resolution_raw,
        ) = _build_candidate_roads_for_single_sided(
            context,
            protected_road_ids=junction_related_road_ids,
        )
        single_sided_direction_resolution = _single_sided_direction_resolution_fields(
            single_sided_direction_resolution_raw
        )
        base_allowed_road_ids &= single_sided_allowed_road_ids
        candidate_opposite_rc_road_ids, candidate_opposite_rc_node_ids = _build_single_sided_exclusions(
            context,
            direction,
            protected_node_ids={node.node_id for node in context.target_group.nodes},
        )
        excluded_opposite_rc_road_ids, rcsd_opposite_fallback_raw = _filter_opposite_rc_road_ids(
            context,
            excluded_opposite_road_ids=excluded_opposite_road_ids,
            candidate_rc_road_ids=candidate_opposite_rc_road_ids,
            protected_road_ids=junction_related_road_ids,
            forward_direction=direction,
            horizontal_pair_detected=single_sided_direction_resolution["single_sided_horizontal_pair_detected"],
        )
        rcsd_opposite_fallback = _rcsd_opposite_fallback_fields(rcsd_opposite_fallback_raw)
        excluded_opposite_rc_node_ids = _filter_opposite_rc_node_ids(
            context,
            excluded_opposite_road_ids=excluded_opposite_road_ids,
            filtered_rc_road_ids=excluded_opposite_rc_road_ids,
            candidate_rc_node_ids=candidate_opposite_rc_node_ids,
        )
        opposite_side_guard_mode = "proxy_baseline"
        corridor_guard_status = (
            "hard_blocked_by_rcsdroad_mask" if excluded_opposite_rc_road_ids else "not_applicable"
        )
        opposite_side_guard_note = "road/semantic-node guard applied; near-corridor fallback only when SWSD opposite is missing."
        if ambiguous:
            review_signals.append("single_sided_direction_ambiguous")

    adjacent_geometry, adjacent_records, adjacent_suppressed_records, adjacent_cut_road_ids = _build_adjacent_junction_masks(
        context,
        adjacent_records=adjacent_seed_records,
        additional_protection_geometry=bridge_protection_geometry,
    )
    foreign_mst_geometry, foreign_mst_records = _build_foreign_mst_masks(context)
    e_geometry, e_records, blocked_directions = _build_single_sided_blockers(
        context,
        excluded_opposite_road_ids=excluded_opposite_road_ids,
        excluded_opposite_rc_road_ids=excluded_opposite_rc_road_ids,
        excluded_opposite_rc_node_ids=excluded_opposite_rc_node_ids,
    )
    pre_blocker_union = _clean_geometry(
        unary_union([geometry for geometry in (adjacent_geometry, foreign_mst_geometry, e_geometry) if geometry is not None])
    )
    pre_candidate_support, _pre_growth_limits, frontier_candidate_road_ids, _pre_frontier_stop_reason = _build_reachable_road_support(
        context,
        allowed_road_ids=base_allowed_road_ids,
        blocker_geometry=pre_blocker_union,
        force_bidirectional_road_ids=branch_frontier_road_ids,
    )
    b_geometry, b_records, node_fallback_used = _build_foreign_object_masks(
        context,
        frontier_candidate_road_ids=frontier_candidate_road_ids,
        adjacent_cut_road_ids=adjacent_cut_road_ids,
        excluded_road_ids=excluded_opposite_road_ids,
        excluded_node_ids=excluded_opposite_rc_node_ids,
        protected_road_ids=junction_related_road_ids,
        protected_group_ids=protected_group_ids,
    )
    foreign_object_geometry = _clean_geometry(unary_union([geometry for geometry in (e_geometry, b_geometry) if geometry is not None]))
    foreign_object_records = [*e_records, *b_records]
    blocker_union = _clean_geometry(
        unary_union(
            [
                geometry
                for geometry in (
                    adjacent_geometry,
                    foreign_object_geometry,
                    foreign_mst_geometry,
                )
                if geometry is not None
            ]
        )
    )

    hard_candidate_support_geometry, growth_limits, selected_road_ids, frontier_stop_reason = _build_reachable_road_support(
        context,
        allowed_road_ids=base_allowed_road_ids,
        blocker_geometry=blocker_union,
        force_bidirectional_road_ids=branch_frontier_road_ids,
    )
    bridge_hard_support, bridge_hard_fields = _build_two_node_t_bridge_support(
        context,
        blocker_geometry=blocker_union,
    )
    hard_candidate_parts = [geometry for geometry in (hard_candidate_support_geometry, bridge_hard_support) if geometry is not None]
    hard_candidate_with_bridge = _extract_polygon_geometry(unary_union(hard_candidate_parts)) if hard_candidate_parts else None

    hard_path_geometry = _component_touching_target(hard_candidate_with_bridge, reference_target_geometry)
    drivezone_metrics = _drivezone_containment_metrics(hard_path_geometry, context.drivezone_geometry)
    hard_intrusion = _has_negative_intrusion(hard_path_geometry, blocker_union)
    covered_node_ids = _covered_node_ids(context, hard_path_geometry)
    target_node_ids = [node.node_id for node in context.target_group.nodes]
    missing_node_ids = [node_id for node_id in target_node_ids if node_id not in covered_node_ids]

    cleanup_preview_source_geometry, _preview_growth_limits, _preview_selected_road_ids, _preview_frontier_stop_reason = _build_reachable_road_support(
        context,
        allowed_road_ids=base_allowed_road_ids,
        blocker_geometry=None,
        force_bidirectional_road_ids=branch_frontier_road_ids,
    )
    cleanup_preview_parts = [
        geometry
        for geometry in (cleanup_preview_source_geometry, bridge_protection_geometry)
        if geometry is not None
    ]
    cleanup_preview_geometry = _extract_polygon_geometry(unary_union(cleanup_preview_parts)) if cleanup_preview_parts else None
    if cleanup_preview_geometry is not None and blocker_union is not None:
        cleanup_preview_geometry = _clean_geometry(cleanup_preview_geometry.difference(blocker_union))
    cleanup_preview_geometry = _component_touching_target(cleanup_preview_geometry, reference_target_geometry)
    cleanup_preview_drivezone_metrics = _drivezone_containment_metrics(cleanup_preview_geometry, context.drivezone_geometry)
    cleanup_preview_intrusion = _has_negative_intrusion(cleanup_preview_geometry, blocker_union)
    cleanup_preview_covered_node_ids = _covered_node_ids(context, cleanup_preview_geometry)
    cleanup_preview_missing_node_ids = [
        node_id
        for node_id in target_node_ids
        if node_id not in cleanup_preview_covered_node_ids
    ]

    hard_path_passed = (
        hard_path_geometry is not None
        and drivezone_metrics["drivezone_containment_passed"]
        and not hard_intrusion
        and not missing_node_ids
    )
    cleanup_preview_passed = (
        cleanup_preview_geometry is not None
        and cleanup_preview_drivezone_metrics["drivezone_containment_passed"]
        and not cleanup_preview_intrusion
        and not cleanup_preview_missing_node_ids
    )
    rule_d_fallback_fields = _rule_d_fallback_fields(growth_limits=growth_limits)
    rule_a_protection_fields = _rule_a_target_core_protection_fields(adjacent_suppressed_records)
    shared_two_in_two_out_fields = _shared_two_in_two_out_closeout_fields(shared_two_in_two_out)
    cleanup_dependency = (not hard_path_passed) and cleanup_preview_passed
    opposite_side_intrusion = bool(selected_road_ids & excluded_opposite_road_ids)
    e_intrusion = _has_negative_intrusion(hard_path_geometry, e_geometry)
    reason = "step3_established"
    step3_state = "established"
    if cleanup_dependency:
        step3_state = "not_established"
        reason = "cleanup_dependency_required"
    elif hard_path_geometry is None:
        step3_state = "not_established"
        reason = "allowed_space_empty"
    elif not drivezone_metrics["drivezone_containment_passed"]:
        step3_state = "not_established"
        reason = "outside_drivezone_intrusion"
    elif missing_node_ids:
        step3_state = "not_established"
        reason = "must_cover_failed"
    elif opposite_side_intrusion or e_intrusion:
        step3_state = "not_established"
        reason = "single_sided_opposite_side_intrusion"
    elif hard_intrusion:
        step3_state = "not_established"
        reason = "negative_mask_intrusion"
    elif review_signals:
        step3_state = "review"
        reason = review_signals[0]

    blocked_direction_reasons = sorted({item["reason"] for item in blocked_directions})
    rules = {
        "A": {
            "passed": True,
            "count": len(adjacent_records),
            **rule_a_protection_fields,
        },
        "B": {"passed": True, "count": len(b_records), "node_fallback_used": node_fallback_used},
        "C": {"passed": True, "count": len(foreign_mst_records)},
        "D": {
            "passed": (
                hard_path_geometry is not None
                and drivezone_metrics["drivezone_containment_passed"]
                and not missing_node_ids
                and not opposite_side_intrusion
            ),
            "growth_limit_count": len(growth_limits),
            **rule_d_fallback_fields,
            "direction_mode": DIRECTION_MODE,
            **drivezone_metrics,
        },
        "E": {
            "passed": not opposite_side_intrusion and not e_intrusion,
            "blocked_count": len(blocked_directions),
            "template_only": template_result.template_class == "single_sided_t_mouth",
            "excluded_opposite_road_ids": sorted(excluded_opposite_road_ids),
            "excluded_opposite_rc_road_ids": sorted(excluded_opposite_rc_road_ids),
            "excluded_opposite_semantic_node_ids": sorted(excluded_opposite_rc_node_ids),
            "opposite_side_guard_mode": opposite_side_guard_mode,
            "corridor_guard_status": corridor_guard_status,
            "opposite_side_guard_note": opposite_side_guard_note,
            **rcsd_opposite_fallback,
        },
        "F": {
            "passed": not cleanup_dependency,
            "hard_path_passed": hard_path_passed,
            "cleanup_preview_passed": cleanup_preview_passed,
            "rescue_reason": "post_difference_preview_only" if cleanup_dependency else None,
        },
        "G": {
            "passed": not cleanup_dependency,
            "growth_after_hard_bounds_only": True,
            "growth_order": "hard_bound_first",
            "post_growth_safety_only": True,
        },
        "H": {"passed": True, "distance_cap_m": STEP3_DISTANCE_CAP_M},
    }
    audit_doc = {
        "input_gate": input_gate,
        "rules": rules,
        "adjacent_junction_cuts": adjacent_records,
        "adjacent_junction_cut_suppressed": adjacent_suppressed_records,
        "foreign_object_masks": foreign_object_records,
        "foreign_mst_masks": foreign_mst_records,
        "growth_limits": growth_limits,
        **rule_d_fallback_fields,
        "cleanup_dependency": cleanup_dependency,
        "must_cover_result": {
            "covered_node_ids": covered_node_ids,
            "missing_node_ids": missing_node_ids,
            "cleanup_preview_covered_node_ids": cleanup_preview_covered_node_ids,
            "cleanup_preview_missing_node_ids": cleanup_preview_missing_node_ids,
        },
        "blocked_directions": blocked_directions,
        "review_signals": review_signals,
        "direction_mode": DIRECTION_MODE,
        "growth_order": "hard_bound_first",
        "hard_bound_first": True,
        "post_growth_safety_only": True,
        "frontier_stop_reason": frontier_stop_reason,
        "selected_road_ids": sorted(selected_road_ids),
        "excluded_road_ids": sorted(excluded_opposite_road_ids),
        "opposite_road_ids": sorted(excluded_opposite_road_ids),
        "opposite_semantic_node_ids": sorted(excluded_opposite_rc_node_ids),
        "opposite_rcsdroad_ids": sorted(excluded_opposite_rc_road_ids),
        "opposite_side_guard_mode": opposite_side_guard_mode,
        "corridor_guard_status": corridor_guard_status,
        "opposite_side_guard_note": opposite_side_guard_note,
        **rcsd_opposite_fallback,
        **single_sided_direction_resolution,
        "hard_path_passed": hard_path_passed,
        "cleanup_preview_passed": cleanup_preview_passed,
        "rescue_reason": "post_difference_preview_only" if cleanup_dependency else None,
        "adjacent_junction_cut_protection_applied": rule_a_protection_fields["target_core_protection_applied"],
        "adjacent_junction_cut_protection_reason": rule_a_protection_fields["target_core_protection_reason"],
        **bridge_hard_fields,
        **shared_two_in_two_out_fields,
        **drivezone_metrics,
    }
    key_metrics = {
        "target_group_node_count": len(context.target_group.nodes),
        "selected_road_count": len(selected_road_ids),
        "excluded_road_count": len(excluded_opposite_road_ids),
        "adjacent_cut_count": len(adjacent_records),
        "foreign_object_mask_count": len(foreign_object_records),
        "foreign_mst_mask_count": len(foreign_mst_records),
        "review_signal_count": len(review_signals),
        "cleanup_dependency": cleanup_dependency,
        "blocked_direction_count": len(blocked_directions),
        "rule_d_fallback_applied": rule_d_fallback_fields["rule_d_fallback_applied"],
        "rcsd_opposite_fallback_enabled": rcsd_opposite_fallback["rcsd_opposite_fallback_enabled"],
        "two_node_t_bridge_applied": bridge_hard_fields["two_node_t_bridge_applied"],
        "shared_two_in_two_out_as_through_node": shared_two_in_two_out_fields["shared_two_in_two_out_as_through_node"],
        "single_sided_horizontal_pair_detected": single_sided_direction_resolution["single_sided_horizontal_pair_detected"],
        **drivezone_metrics,
    }
    visual_review_class = _review_visual_class(step3_state, review_signals, reason)
    return Step3CaseResult(
        case_id=context.case_spec.case_id,
        template_class=template_result.template_class,
        step3_state=step3_state,
        step3_established=step3_state == "established",
        reason=reason,
        visual_review_class=visual_review_class,
        root_cause_layer=_root_cause_layer(step3_state),
        root_cause_type=None if step3_state == "established" else reason,
        allowed_space_geometry=hard_path_geometry,
        allowed_drivezone_geometry=hard_candidate_with_bridge,
        negative_masks=Step3NegativeMasks(
            adjacent_junction_geometry=adjacent_geometry,
            foreign_objects_geometry=foreign_object_geometry,
            foreign_mst_geometry=foreign_mst_geometry,
            adjacent_junction_records=tuple(adjacent_records),
            foreign_object_records=tuple(foreign_object_records),
            foreign_mst_records=tuple(foreign_mst_records),
        ),
        key_metrics=key_metrics,
        audit_doc=audit_doc,
        review_signals=tuple(review_signals),
        blocked_directions=tuple(blocked_directions),
        extra_status_fields={
            "representative_node_id": context.representative_node.node_id,
            "target_group_node_ids": target_node_ids,
            "foreign_group_ids": [group.group_id for group in context.foreign_groups],
            "selected_road_ids": sorted(selected_road_ids),
            "excluded_road_ids": sorted(excluded_opposite_road_ids),
            "blocked_direction_reasons": blocked_direction_reasons,
            "cleanup_dependency": cleanup_dependency,
            "direction_mode": DIRECTION_MODE,
            **rule_d_fallback_fields,
            **bridge_hard_fields,
            **shared_two_in_two_out_fields,
            **single_sided_direction_resolution,
            **rcsd_opposite_fallback,
            **drivezone_metrics,
            "visual_review_class": visual_review_class,
            "root_cause_layer": _root_cause_layer(step3_state),
            "root_cause_type": None if step3_state == "established" else reason,
        },
    )


def build_step3_status_doc(case_result: Step3CaseResult) -> dict[str, Any]:
    return _build_status_doc(case_result)
