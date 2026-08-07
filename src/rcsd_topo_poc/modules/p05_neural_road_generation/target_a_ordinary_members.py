from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping, Sequence

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry


ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM = 24
ORDINARY_PLAN_MEMBER_FEATURE_DIM = 28


def build_ordinary_plan_member_rows(
    *,
    road_ids: Sequence[str],
    road_roles: Mapping[str, str],
    road_by_id: Mapping[str, Any],
    segment_geometry: BaseGeometry,
    raw_nodes: Mapping[str, Point],
    swsd_nodes: Mapping[str, Point],
    pair_node_ids: Sequence[str],
) -> list[dict[str, Any]]:
    """Build truth-free per-Road evidence for one complete ordinary plan."""
    selected = [
        road_by_id[road_id]
        for road_id in road_ids
        if road_id in road_by_id
    ]
    degrees: Counter[str] = Counter()
    for road in selected:
        degrees[str(road.start_node_id)] += 1
        degrees[str(road.end_node_id)] += 1
    pair_points = [
        swsd_nodes[node_id]
        for node_id in pair_node_ids
        if node_id in swsd_nodes
    ]
    source_point = pair_points[0] if pair_points else None
    target_point = pair_points[-1] if len(pair_points) > 1 else None
    segment_length = max(float(segment_geometry.length), 0.01)
    rows: list[dict[str, Any]] = []
    for road in selected:
        start_node_id = str(road.start_node_id)
        end_node_id = str(road.end_node_id)
        start_point, end_point = _road_endpoint_points(
            road.geometry,
            raw_nodes.get(start_node_id),
            raw_nodes.get(end_node_id),
        )
        source_start = _distance(source_point, start_point)
        source_end = _distance(source_point, end_point)
        target_start = _distance(target_point, start_point)
        target_end = _distance(target_point, end_point)
        forward_cost = source_start + target_end
        reverse_cost = source_end + target_start
        direction = int(road.direction)
        alignment = _alignment_cosine(
            source_point,
            target_point,
            start_point,
            end_point,
        )
        role = str(road_roles.get(str(road.road_id), "MAIN"))
        values = [
            float(role == "MAIN"),
            float(role == "INTERNAL_CONNECTOR"),
            float(direction == 1),
            float(direction == 2),
            float(direction == 3),
            float(direction not in {1, 2, 3}),
            math.tanh(max(int(road.function_class), 0) / 5.0),
            math.tanh(max(float(road.geometry.length), 0.0) / segment_length),
            math.tanh(
                float(road.geometry.distance(segment_geometry)) / 40.0
            ),
            math.tanh(source_start / 40.0),
            math.tanh(source_end / 40.0),
            math.tanh(target_start / 40.0),
            math.tanh(target_end / 40.0),
            math.tanh(min(source_start, source_end) / 40.0),
            math.tanh(min(target_start, target_end) / 40.0),
            math.tanh(forward_cost / 80.0),
            math.tanh(reverse_cost / 80.0),
            math.tanh((reverse_cost - forward_cost) / 40.0),
            math.tanh(degrees[start_node_id] / 4.0),
            math.tanh(degrees[end_node_id] / 4.0),
            float(degrees[start_node_id] == 1),
            float(degrees[end_node_id] == 1),
            abs(alignment),
            alignment,
        ]
        if len(values) != ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM:
            raise AssertionError("ordinary member base feature dimension differs")
        rows.append(
            {
                "road_id": str(road.road_id),
                "start_node_id": start_node_id,
                "end_node_id": end_node_id,
                "features": values,
            }
        )
    return rows


def condition_ordinary_plan_member_features(
    *,
    base_features: Sequence[Sequence[float]],
    road_ids: Sequence[str],
    endpoint_ids: Sequence[tuple[str, str]],
    selected_road_ids: set[str],
    selected_node_ids: set[str],
) -> tuple[tuple[float, ...], ...]:
    if (
        len(base_features) != len(road_ids)
        or len(base_features) != len(endpoint_ids)
    ):
        raise ValueError("ordinary member relation alignment differs")
    result: list[tuple[float, ...]] = []
    for features, road_id, (start_node_id, end_node_id) in zip(
        base_features,
        road_ids,
        endpoint_ids,
        strict=True,
    ):
        if len(features) != ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM:
            raise ValueError("ordinary member base feature dimension differs")
        start_selected = start_node_id in selected_node_ids
        end_selected = end_node_id in selected_node_ids
        values = (
            *[float(value) for value in features],
            float(road_id in selected_road_ids),
            float(start_selected),
            float(end_selected),
            float(start_selected or end_selected),
        )
        if len(values) != ORDINARY_PLAN_MEMBER_FEATURE_DIM:
            raise AssertionError("ordinary member feature dimension differs")
        result.append(tuple(values))
    return tuple(result)


def _road_endpoint_points(
    geometry: BaseGeometry,
    start_node: Point | None,
    end_node: Point | None,
) -> tuple[Point | None, Point | None]:
    coordinates = _line_endpoint_coordinates(geometry)
    start = start_node
    end = end_node
    if coordinates is not None:
        if start is None:
            start = Point(coordinates[0][:2])
        if end is None:
            end = Point(coordinates[1][:2])
    return start, end


def _line_endpoint_coordinates(
    geometry: BaseGeometry,
) -> tuple[tuple[float, ...], tuple[float, ...]] | None:
    if geometry.is_empty:
        return None
    if geometry.geom_type == "LineString":
        coordinates = list(geometry.coords)
        return (
            (coordinates[0], coordinates[-1])
            if len(coordinates) >= 2
            else None
        )
    if geometry.geom_type == "MultiLineString":
        parts = list(geometry.geoms)
        if not parts:
            return None
        first = list(parts[0].coords)
        last = list(parts[-1].coords)
        return (
            (first[0], last[-1])
            if first and last
            else None
        )
    return None


def _distance(first: Point | None, second: Point | None) -> float:
    if first is None or second is None:
        return 80.0
    return min(float(first.distance(second)), 320.0)


def _alignment_cosine(
    source: Point | None,
    target: Point | None,
    start: Point | None,
    end: Point | None,
) -> float:
    if any(value is None for value in (source, target, start, end)):
        return 0.0
    segment_x = float(target.x - source.x)
    segment_y = float(target.y - source.y)
    road_x = float(end.x - start.x)
    road_y = float(end.y - start.y)
    denominator = math.hypot(segment_x, segment_y) * math.hypot(
        road_x,
        road_y,
    )
    if denominator <= 1e-9:
        return 0.0
    return max(
        -1.0,
        min(
            1.0,
            (segment_x * road_x + segment_y * road_y) / denominator,
        ),
    )


__all__ = [
    "ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM",
    "ORDINARY_PLAN_MEMBER_FEATURE_DIM",
    "build_ordinary_plan_member_rows",
    "condition_ordinary_plan_member_features",
]
