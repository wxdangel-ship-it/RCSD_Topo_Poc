from __future__ import annotations

import math
from collections import Counter
from typing import Any, Mapping, Sequence

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry


ORDINARY_PLAN_ARM_COUNT = 2
ORDINARY_PLAN_ARM_BASE_FEATURE_DIM = 13
ORDINARY_PLAN_ARM_FEATURE_DIM = 22


def build_ordinary_plan_arm_rows(
    *,
    road_ids: Sequence[str],
    road_roles: Mapping[str, str],
    road_by_id: Mapping[str, Any],
    segment_geometry: BaseGeometry,
    node_points: Mapping[str, Point],
    pair_points: Sequence[Point],
) -> list[dict[str, Any]]:
    """Describe how a complete Road plan reaches the two frozen Segment arms."""
    selected = [
        road_by_id[road_id]
        for road_id in road_ids
        if road_id in road_by_id
    ]
    if not selected:
        return []
    arms = _two_arm_points(pair_points, segment_geometry)
    degrees = Counter(
        node_id
        for road in selected
        for node_id in (road.start_node_id, road.end_node_id)
    )
    endpoints: list[dict[str, Any]] = []
    for road in selected:
        start_point, end_point = _road_endpoint_points(
            road.geometry,
            node_points.get(road.start_node_id),
            node_points.get(road.end_node_id),
        )
        endpoints.extend(
            (
                {
                    "road_id": road.road_id,
                    "node_id": road.start_node_id,
                    "point": start_point,
                    "leaf": degrees[road.start_node_id] == 1,
                    "role": road_roles.get(road.road_id, ""),
                    "inward": _road_inward_vector(
                        road.geometry,
                        at_start=True,
                    ),
                },
                {
                    "road_id": road.road_id,
                    "node_id": road.end_node_id,
                    "point": end_point,
                    "leaf": degrees[road.end_node_id] == 1,
                    "role": road_roles.get(road.road_id, ""),
                    "inward": _road_inward_vector(
                        road.geometry,
                        at_start=False,
                    ),
                },
            )
        )
    rows: list[dict[str, Any]] = []
    for arm in arms:
        distances = sorted(
            (
                (float(arm.distance(endpoint["point"])), endpoint)
                for endpoint in endpoints
            ),
            key=lambda item: (
                item[0],
                str(item[1]["road_id"]),
                str(item[1]["node_id"]),
            ),
        )
        nearest_distance, nearest = distances[0]
        leaf_distances = [
            distance
            for distance, endpoint in distances
            if endpoint["leaf"]
        ]
        nearest_leaf_distance = (
            min(leaf_distances) if leaf_distances else nearest_distance
        )
        arm_inward = _segment_inward_vector(segment_geometry, arm)
        alignment = _cosine(arm_inward, nearest["inward"])
        values = (
            1.0,
            1.0,
            math.tanh(nearest_distance / 80.0),
            math.exp(-nearest_distance / 15.0),
            math.tanh(nearest_leaf_distance / 80.0),
            math.exp(-nearest_leaf_distance / 15.0),
            math.tanh(
                sum(distance <= 5.0 for distance, _ in distances) / 4.0
            ),
            math.tanh(
                sum(distance <= 15.0 for distance, _ in distances) / 4.0
            ),
            math.tanh(
                sum(distance <= 30.0 for distance, _ in distances) / 4.0
            ),
            float(nearest["leaf"]),
            alignment,
            abs(alignment),
            float(nearest["role"] == "MAIN"),
        )
        if len(values) != ORDINARY_PLAN_ARM_BASE_FEATURE_DIM:
            raise RuntimeError("ordinary arm feature dimension differs")
        rows.append(
            {
                "nearest_road_id": str(nearest["road_id"]),
                "nearest_node_id": str(nearest["node_id"]),
                "features": [float(value) for value in values],
            }
        )
    if len(rows) != ORDINARY_PLAN_ARM_COUNT:
        raise RuntimeError("ordinary plan must expose two Segment arms")
    return rows


def condition_ordinary_plan_arm_features(
    *,
    base_features: Sequence[Sequence[float]],
    nearest_road_ids: Sequence[str],
    nearest_node_ids: Sequence[str],
    arm_anchor_ids: Sequence[str],
    selected_road_ids: set[str],
    selected_node_ids: set[str],
    selected_road_ids_by_anchor: Mapping[str, set[str]],
    selected_node_ids_by_anchor: Mapping[str, set[str]],
) -> tuple[tuple[float, ...], ...]:
    if not (
        len(base_features)
        == len(nearest_road_ids)
        == len(nearest_node_ids)
        == len(arm_anchor_ids)
    ):
        raise ValueError("ordinary arm relation sidecars are misaligned")
    rows = []
    for features, road_id, node_id, anchor_id in zip(
        base_features,
        nearest_road_ids,
        nearest_node_ids,
        arm_anchor_ids,
        strict=True,
    ):
        if len(features) != ORDINARY_PLAN_ARM_BASE_FEATURE_DIM:
            raise ValueError("ordinary arm base feature dimension differs")
        road_selected = float(road_id in selected_road_ids)
        node_selected = float(node_id in selected_node_ids)
        local_roads = selected_road_ids_by_anchor.get(anchor_id, set())
        local_nodes = selected_node_ids_by_anchor.get(anchor_id, set())
        foreign_roads = set().union(
            *[
                values
                for key, values in selected_road_ids_by_anchor.items()
                if key != anchor_id
            ]
        ) if any(
            key != anchor_id for key in selected_road_ids_by_anchor
        ) else set()
        foreign_nodes = set().union(
            *[
                values
                for key, values in selected_node_ids_by_anchor.items()
                if key != anchor_id
            ]
        ) if any(
            key != anchor_id for key in selected_node_ids_by_anchor
        ) else set()
        local_road = float(road_id in local_roads)
        local_node = float(node_id in local_nodes)
        foreign_road = float(road_id in foreign_roads)
        foreign_node = float(node_id in foreign_nodes)
        values = (
            *features,
            road_selected,
            node_selected,
            float(bool(road_selected or node_selected)),
            local_road,
            local_node,
            float(bool(local_road or local_node)),
            foreign_road,
            foreign_node,
            float(bool(foreign_road or foreign_node)),
        )
        if len(values) != ORDINARY_PLAN_ARM_FEATURE_DIM:
            raise RuntimeError("ordinary arm conditioned dimension differs")
        rows.append(tuple(float(value) for value in values))
    return tuple(rows)


def _two_arm_points(
    pair_points: Sequence[Point],
    segment_geometry: BaseGeometry,
) -> tuple[Point, Point]:
    if len(pair_points) >= 2:
        return pair_points[0], pair_points[-1]
    endpoints = _line_endpoints(segment_geometry)
    if len(endpoints) < 2:
        raise ValueError("ordinary Segment has fewer than two arm points")
    if len(endpoints) == 2:
        return endpoints[0], endpoints[1]
    _, first, second = max(
        (
            (float(left.distance(right)), left, right)
            for left in endpoints
            for right in endpoints
        ),
        key=lambda item: item[0],
    )
    return first, second


def _road_endpoint_points(
    geometry: BaseGeometry,
    start_point: Point | None,
    end_point: Point | None,
) -> tuple[Point, Point]:
    endpoints = _line_endpoints(geometry)
    if len(endpoints) < 2 and (start_point is None or end_point is None):
        raise ValueError("ordinary Road member lacks endpoint geometry")
    return (
        start_point if start_point is not None else endpoints[0],
        end_point if end_point is not None else endpoints[-1],
    )


def _line_endpoints(geometry: BaseGeometry) -> list[Point]:
    lines = (
        [geometry]
        if isinstance(geometry, LineString)
        else [
            part
            for part in getattr(geometry, "geoms", ())
            if isinstance(part, LineString)
        ]
    )
    return [
        point
        for line in lines
        if len(line.coords) >= 2
        for point in (Point(line.coords[0]), Point(line.coords[-1]))
    ]


def _segment_inward_vector(
    geometry: BaseGeometry,
    arm: Point,
) -> tuple[float, float]:
    options = []
    for line in (
        [geometry]
        if isinstance(geometry, LineString)
        else getattr(geometry, "geoms", ())
    ):
        if not isinstance(line, LineString) or len(line.coords) < 2:
            continue
        start = Point(line.coords[0])
        end = Point(line.coords[-1])
        options.extend(
            (
                (
                    float(arm.distance(start)),
                    _vector(line.coords[0], line.coords[1]),
                ),
                (
                    float(arm.distance(end)),
                    _vector(line.coords[-1], line.coords[-2]),
                ),
            )
        )
    return min(options, key=lambda item: item[0])[1] if options else (0.0, 0.0)


def _road_inward_vector(
    geometry: BaseGeometry,
    *,
    at_start: bool,
) -> tuple[float, float]:
    lines = (
        [geometry]
        if isinstance(geometry, LineString)
        else [
            part
            for part in getattr(geometry, "geoms", ())
            if isinstance(part, LineString)
        ]
    )
    if not lines:
        return 0.0, 0.0
    line = max(lines, key=lambda item: item.length)
    if len(line.coords) < 2:
        return 0.0, 0.0
    return (
        _vector(line.coords[0], line.coords[1])
        if at_start
        else _vector(line.coords[-1], line.coords[-2])
    )


def _vector(
    first: Sequence[float],
    second: Sequence[float],
) -> tuple[float, float]:
    return float(second[0] - first[0]), float(second[1] - first[1])


def _cosine(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    first_norm = math.hypot(*first)
    second_norm = math.hypot(*second)
    if first_norm <= 1e-9 or second_norm <= 1e-9:
        return 0.0
    return max(
        -1.0,
        min(
            1.0,
            (first[0] * second[0] + first[1] * second[1])
            / (first_norm * second_norm),
        ),
    )


__all__ = [
    "ORDINARY_PLAN_ARM_BASE_FEATURE_DIM",
    "ORDINARY_PLAN_ARM_COUNT",
    "ORDINARY_PLAN_ARM_FEATURE_DIM",
    "build_ordinary_plan_arm_rows",
    "condition_ordinary_plan_arm_features",
]
