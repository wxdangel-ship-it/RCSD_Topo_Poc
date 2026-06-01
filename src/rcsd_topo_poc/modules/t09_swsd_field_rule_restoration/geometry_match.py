from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import SWSDRoadInput


MAX_GEOMETRY_MATCH_DISTANCE_M = 12.0
MAX_DIRECTION_DELTA_DEG = 35.0
MAX_RESTRICTION_INSIDE_DISTANCE_M = 15.0


@dataclass(frozen=True)
class DirectedGeometryMatch:
    road_id: str
    distance_m: float
    direction_delta_deg: float
    confidence: float
    method: str

    def audit(self) -> dict[str, float | str]:
        return {
            "road_id": self.road_id,
            "distance_m": round(self.distance_m, 3),
            "direction_delta_deg": round(self.direction_delta_deg, 3),
            "confidence": round(self.confidence, 3),
            "method": self.method,
        }


def match_restriction_endpoint_to_road(
    *,
    restriction_geometry: BaseGeometry | None,
    road: SWSDRoadInput,
    road_geometry: BaseGeometry | None,
    member_node_ids: tuple[str, ...],
    endpoint: Literal["start", "end"],
    road_role: Literal["approach", "exit"],
) -> DirectedGeometryMatch | None:
    source_line = _line_geometry(restriction_geometry)
    target_line = _line_geometry(road_geometry)
    if source_line is None or target_line is None:
        return None
    source_angle = _endpoint_angle(source_line, endpoint=endpoint)
    target_angle = _road_role_angle(road, target_line, set(member_node_ids), road_role=road_role)
    if source_angle is None or target_angle is None:
        return None
    point = Point(source_line.coords[0] if endpoint == "start" else source_line.coords[-1])
    distance = float(point.distance(target_line))
    delta = _angular_distance(source_angle, target_angle)
    if distance > MAX_GEOMETRY_MATCH_DISTANCE_M or delta > MAX_DIRECTION_DELTA_DEG:
        return None
    return DirectedGeometryMatch(
        road_id=road.road_id,
        distance_m=distance,
        direction_delta_deg=delta,
        confidence=_confidence(distance, delta),
        method=f"directed_geometry_{endpoint}_{road_role}",
    )


def match_arrow_to_approach_road(
    *,
    arrow_geometry: BaseGeometry | None,
    road: SWSDRoadInput,
    road_geometry: BaseGeometry | None,
    member_node_ids: tuple[str, ...],
) -> DirectedGeometryMatch | None:
    source_line = _line_geometry(arrow_geometry)
    target_line = _line_geometry(road_geometry)
    if source_line is None or target_line is None:
        return None
    source_angle = _endpoint_angle(source_line, endpoint="full")
    target_angle = _road_role_angle(road, target_line, set(member_node_ids), road_role="approach")
    if source_angle is None or target_angle is None:
        return None
    distance = float(source_line.distance(target_line))
    delta = _angular_distance(source_angle, target_angle)
    if distance > MAX_GEOMETRY_MATCH_DISTANCE_M or delta > MAX_DIRECTION_DELTA_DEG:
        return None
    return DirectedGeometryMatch(
        road_id=road.road_id,
        distance_m=distance,
        direction_delta_deg=delta,
        confidence=_confidence(distance, delta),
        method="directed_geometry_arrow_approach",
    )


def approach_arrow_endpoint_distance(
    *,
    arrow_geometry: BaseGeometry | None,
    road: SWSDRoadInput,
    road_geometry: BaseGeometry | None,
    member_node_ids: tuple[str, ...],
) -> float:
    source_line = _line_geometry(arrow_geometry)
    target_line = _line_geometry(road_geometry)
    inside = _road_inside_point(road, target_line, set(member_node_ids)) if target_line is not None else None
    if source_line is None or inside is None:
        return float("inf")
    return float(Point(source_line.coords[-1]).distance(inside))


def restriction_inside_endpoint_distance(
    *,
    restriction_geometry: BaseGeometry | None,
    from_road: SWSDRoadInput,
    from_road_geometry: BaseGeometry | None,
    from_member_node_ids: tuple[str, ...],
    to_road: SWSDRoadInput,
    to_road_geometry: BaseGeometry | None,
    to_member_node_ids: tuple[str, ...],
) -> float:
    source_line = _line_geometry(restriction_geometry)
    from_line = _line_geometry(from_road_geometry)
    to_line = _line_geometry(to_road_geometry)
    if source_line is None or from_line is None or to_line is None:
        return float("inf")
    from_inside = _road_inside_point(from_road, from_line, set(from_member_node_ids))
    to_inside = _road_inside_point(to_road, to_line, set(to_member_node_ids))
    if from_inside is None or to_inside is None:
        return float("inf")
    return max(float(source_line.distance(from_inside)), float(source_line.distance(to_inside)))


def _line_geometry(geometry: BaseGeometry | None) -> LineString | None:
    if isinstance(geometry, LineString) and len(geometry.coords) >= 2:
        return geometry
    if isinstance(geometry, MultiLineString):
        parts = [part for part in geometry.geoms if not part.is_empty and len(part.coords) >= 2]
        if parts:
            return max(parts, key=lambda part: float(part.length))
    return None


def _endpoint_angle(line: LineString, *, endpoint: Literal["start", "end", "full"]) -> float | None:
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    if endpoint == "start":
        start, end = coords[0], coords[1]
    elif endpoint == "end":
        start, end = coords[-2], coords[-1]
    else:
        start, end = coords[0], coords[-1]
    return _angle(start, end)


def _road_role_angle(
    road: SWSDRoadInput,
    geometry: LineString,
    member_node_ids: set[str],
    *,
    road_role: Literal["approach", "exit"],
) -> float | None:
    coords = list(geometry.coords)
    if len(coords) < 2:
        return None
    snode_inside = road.snodeid in member_node_ids
    enode_inside = road.enodeid in member_node_ids
    if road_role == "approach":
        if snode_inside and not enode_inside:
            return _angle(coords[-1], coords[0])
        if enode_inside and not snode_inside:
            return _angle(coords[0], coords[-1])
    if road_role == "exit":
        if snode_inside and not enode_inside:
            return _angle(coords[0], coords[-1])
        if enode_inside and not snode_inside:
            return _angle(coords[-1], coords[0])
    return None


def _road_inside_point(
    road: SWSDRoadInput,
    geometry: LineString,
    member_node_ids: set[str],
) -> Point | None:
    coords = list(geometry.coords)
    if road.snodeid in member_node_ids and road.enodeid not in member_node_ids:
        return Point(coords[0])
    if road.enodeid in member_node_ids and road.snodeid not in member_node_ids:
        return Point(coords[-1])
    return None


def _angle(start: tuple[float, ...], end: tuple[float, ...]) -> float | None:
    dx = float(end[0]) - float(start[0])
    dy = float(end[1]) - float(start[1])
    if abs(dx) <= 1e-9 and abs(dy) <= 1e-9:
        return None
    return math.degrees(math.atan2(dy, dx)) % 360.0


def _angular_distance(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def _confidence(distance: float, delta: float) -> float:
    distance_score = max(0.0, 1.0 - distance / MAX_GEOMETRY_MATCH_DISTANCE_M)
    angle_score = max(0.0, 1.0 - delta / MAX_DIRECTION_DELTA_DEG)
    return min(0.95, 0.55 + 0.25 * distance_score + 0.20 * angle_score)
