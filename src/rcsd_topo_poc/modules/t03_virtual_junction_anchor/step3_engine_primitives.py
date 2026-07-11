from __future__ import annotations

import heapq

import math

from dataclasses import dataclass, field

from hashlib import sha1

from collections import defaultdict, deque

from time import perf_counter

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

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import (
    RoadRecord,
    Step1Context,
    Step2TemplateResult,
    Step3CaseResult,
    Step3NegativeMasks,
)

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.id_utils import normalize_id

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.line_geometry import (
    endpoint_point,
    multipart_road_handling_fields,
    nearest_line,
    substring_from_endpoint,
)

ROAD_BUFFER_M = 8.0

NODE_BUFFER_M = 5.0

NEGATIVE_MASK_BUFFER_M = 1.0

STEP3_DISTANCE_CAP_M = 50.0

TARGET_NODE_COVER_TOLERANCE_M = 0.5

TARGET_NODE_INCIDENT_ROAD_COVER_TOLERANCE_M = 10.0

TARGET_COMPONENT_TOUCH_BUFFER_M = 1.0

SINGLE_SIDED_TARGET_DRIVEZONE_EDGE_TOUCH_M = 1.5

INTRUSION_AREA_TOLERANCE_M2 = 0.05

DRIVEZONE_OUTSIDE_AREA_TOLERANCE_M2 = 0.05

ADJACENT_REVERSE_MASK_LENGTH_M = 1.0

OPPOSITE_RC_ROAD_MAX_SWSD_GAP_M = 10.0

OPPOSITE_RC_ROAD_MAX_REFERENCE_DISTANCE_M = 35.0

OPPOSITE_RC_ROAD_MIN_DIRECTION_SIM = 0.85

OPPOSITE_RC_ROAD_MIN_REVERSE_DIRECTION_DOT = 0.85

OPPOSITE_RC_NODE_MAX_CORRIDOR_DISTANCE_M = 10.0

OPPOSITE_RC_ROAD_MAX_PROTECTED_OVERLAP_M = 3.0

RCSD_SEMANTIC_BRIDGE_MAX_TARGET_DISTANCE_M = 6.0

DIRECTION_MODE = "t02_direction_plus_bidirectional_junction_trace"

from .step3_engine_models import (
    _ReachableRoadPreparedRecord,
    _ReachableRoadPreparedSupport,
    _ReachableRoadSupportCaseCache,
)

def _sorted_string_key(values: Iterable[str] | None) -> tuple[str, ...] | None:
    if values is None:
        return None
    return tuple(sorted(normalized for value in values if (normalized := normalize_id(value)) is not None))

def _geometry_cache_token(geometry: BaseGeometry | None) -> str | None:
    if geometry is None or geometry.is_empty:
        return None
    return sha1(geometry.wkb).hexdigest()

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
    line = nearest_line(road.geometry, reference)
    if line is None:
        return (1.0, 0.0)
    coords = list(line.coords)
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
    line = nearest_line(geometry, _line_midpoint(geometry))
    if line is None:
        return (1.0, 0.0)
    coords = list(line.coords)
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
    line = nearest_line(road.geometry, reference)
    if line is None:
        return reference
    coords = list(line.coords)
    start = Point(coords[0])
    end = Point(coords[-1])
    offset = min(max(offset_m, 0.0), max(line.length, 0.0))
    if start.distance(reference) <= end.distance(reference):
        point = line.interpolate(offset)
    else:
        point = line.interpolate(max(line.length - offset, 0.0))
    return point if isinstance(point, Point) else _point_like(point)

def _road_pair_distance_trend_from_reference(
    first: RoadRecord,
    second: RoadRecord,
    reference: Point,
) -> float | None:
    first_line = nearest_line(first.geometry, reference)
    second_line = nearest_line(second.geometry, reference)
    if first_line is None or second_line is None:
        return None
    min_length = min(first_line.length, second_line.length)
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
        keep_len = max(0.0, cap_m - d_start)
        if piece := substring_from_endpoint(road.geometry, "start", keep_len):
            pieces.append(piece)
    if d_end <= cap_m and (road.enodeid, road.snodeid) in directed_pairs:
        keep_len = max(0.0, cap_m - d_end)
        if piece := substring_from_endpoint(road.geometry, "end", keep_len):
            pieces.append(piece)
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
