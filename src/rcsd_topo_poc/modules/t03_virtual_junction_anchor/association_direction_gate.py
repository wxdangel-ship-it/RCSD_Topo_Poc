from __future__ import annotations

import math
from collections.abc import Iterable

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPoint, MultiPolygon, Point
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_models import AssociationContext
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import NodeRecord, RoadRecord


ANGLE_CLUSTER_TOLERANCE_DEG = 25.0


def _iter_geometries(geometry: BaseGeometry | None) -> Iterable[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, (GeometryCollection, MultiPolygon, MultiLineString, MultiPoint)):
        for part in geometry.geoms:
            yield from _iter_geometries(part)
        return
    yield geometry


def _largest_line_string(geometry: BaseGeometry | None) -> LineString | None:
    parts = [
        part
        for part in _iter_geometries(geometry)
        if part.geom_type == "LineString" and getattr(part, "length", 0.0) > 0.0
    ]
    if not parts:
        return None
    return max(parts, key=lambda item: item.length)


def _point_like(geometry: BaseGeometry) -> Point:
    if isinstance(geometry, Point):
        return geometry
    point = geometry.representative_point()
    return point if isinstance(point, Point) else Point(point.coords[0])


def _angle_diff(lhs: float, rhs: float) -> float:
    diff = abs(lhs - rhs) % 180.0
    return min(diff, 180.0 - diff)


def _mean_axis_angle_deg(angles: Iterable[float]) -> float:
    sin_sum = 0.0
    cos_sum = 0.0
    count = 0
    for angle in angles:
        theta = math.radians((float(angle) % 180.0) * 2.0)
        sin_sum += math.sin(theta)
        cos_sum += math.cos(theta)
        count += 1
    if count == 0:
        return 0.0
    return (math.degrees(math.atan2(sin_sum, cos_sum)) / 2.0) % 180.0


def _local_line_angle_deg(line: BaseGeometry | None, point: Point, *, probe_m: float = 8.0) -> float | None:
    line_string = _largest_line_string(line)
    if line_string is None:
        return None
    distance = line_string.project(point)
    start = max(0.0, distance - probe_m)
    end = min(line_string.length, distance + probe_m)
    if end - start < 0.5:
        start = max(0.0, distance - 1.0)
        end = min(line_string.length, distance + 1.0)
    if end - start <= 1e-6:
        return None
    p0 = line_string.interpolate(start)
    p1 = line_string.interpolate(end)
    return math.degrees(math.atan2(p1.y - p0.y, p1.x - p0.x)) % 180.0


def _cluster_angles(angles: Iterable[float]) -> list[float]:
    clusters: list[list[float]] = []
    for angle in sorted(float(item) % 180.0 for item in angles):
        for cluster in clusters:
            if any(_angle_diff(angle, member) <= ANGLE_CLUSTER_TOLERANCE_DEG for member in cluster):
                cluster.append(angle)
                break
        else:
            clusters.append([angle])
    if len(clusters) > 1 and any(
        _angle_diff(member, other) <= ANGLE_CLUSTER_TOLERANCE_DEG
        for member in clusters[0]
        for other in clusters[-1]
    ):
        clusters[0].extend(clusters.pop())
    return sorted(_mean_axis_angle_deg(cluster) for cluster in clusters)


def _selected_direction_clusters(context: AssociationContext) -> list[float]:
    selected_ids = set(context.selected_road_ids)
    anchor = _point_like(context.step1_context.representative_node.geometry)
    angles = [
        angle
        for road in context.step1_context.roads
        if road.road_id in selected_ids
        if (angle := _local_line_angle_deg(road.geometry, anchor)) is not None
    ]
    return _cluster_angles(angles)


def _rcsd_group_direction_clusters(group_nodes: list[NodeRecord], candidate_roads: list[RoadRecord]) -> list[float]:
    group_node_ids = {node.node_id for node in group_nodes}
    angles: list[float] = []
    for node in group_nodes:
        anchor = _point_like(node.geometry)
        for road in candidate_roads:
            if road.snodeid not in group_node_ids and road.enodeid not in group_node_ids:
                continue
            angle = _local_line_angle_deg(road.geometry, anchor)
            if angle is not None:
                angles.append(angle)
    return _cluster_angles(angles)


def build_single_sided_direction_gate_audit(
    *,
    context: AssociationContext,
    group_nodes: list[NodeRecord],
    candidate_roads: list[RoadRecord],
) -> dict[str, object]:
    selected_clusters = _selected_direction_clusters(context)
    rcsd_clusters = _rcsd_group_direction_clusters(group_nodes, candidate_roads)
    matched_selected_count = sum(
        1
        for selected_angle in selected_clusters
        if any(_angle_diff(selected_angle, rcsd_angle) <= ANGLE_CLUSTER_TOLERANCE_DEG for rcsd_angle in rcsd_clusters)
    )
    required_selected_count = min(2, len(selected_clusters))
    return {
        "direction_gate_selected_clusters_deg": [round(item, 3) for item in selected_clusters],
        "direction_gate_rcsd_clusters_deg": [round(item, 3) for item in rcsd_clusters],
        "direction_gate_matched_selected_cluster_count": matched_selected_count,
        "direction_gate_required_selected_cluster_count": required_selected_count,
        "direction_gate_passed": matched_selected_count >= required_selected_count,
        "direction_gate_tolerance_deg": ANGLE_CLUSTER_TOLERANCE_DEG,
    }
