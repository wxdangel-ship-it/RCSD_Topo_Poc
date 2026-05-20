from __future__ import annotations

from typing import Any

from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge

from .phase2_models import SplitPoint, SwsdTargetContext


def evidence_reference_point(row: dict[str, Any], *, mode: str, fallback: BaseGeometry) -> BaseGeometry | None:
    if mode == "fact":
        for x_name, y_name in (
            ("fact_reference_x", "fact_reference_y"),
            ("fact_reference_point_x", "fact_reference_point_y"),
            ("reference_point_x", "reference_point_y"),
        ):
            point = _point_from_pair(row.get(x_name), row.get(y_name))
            if point is not None:
                return point
        return None
    point = _point_from_pair(row.get("swsd_point_x"), row.get("swsd_point_y"))
    return point or fallback


def projection_points_for_decision(
    *,
    context: SwsdTargetContext,
    evidence_row: dict[str, Any],
    reference_mode: str,
) -> tuple[BaseGeometry, ...]:
    reference = evidence_reference_point(evidence_row, mode=reference_mode, fallback=context.point)
    if reference is None:
        return ()
    if reference_mode == "fact":
        return (reference,)
    if context.junction_type == "center_junction" and context.projection_points:
        return context.projection_points
    return (reference,)


def project_points_to_roads(
    *,
    road_ids: tuple[int, ...],
    roads_by_id: dict[int, dict[str, Any]],
    points: tuple[BaseGeometry, ...],
    junction_type: str,
) -> dict[int, list[SplitPoint]]:
    result: dict[int, list[SplitPoint]] = {}
    for road_id in road_ids:
        road_feature = roads_by_id.get(road_id)
        if road_feature is None:
            continue
        line = _as_line(road_feature.get("geometry"))
        if line is None or line.is_empty:
            continue
        distances = [float(line.project(_as_point(point))) for point in points if point is not None and not point.is_empty]
        if not distances:
            continue
        if junction_type == "center_junction" and len(distances) > 1:
            selected = [min(distances), max(distances)]
            if abs(selected[0] - selected[1]) < 1e-9:
                selected = [selected[0]]
        else:
            selected = [sum(distances) / len(distances)]
        result[road_id] = [
            SplitPoint(road_id=road_id, distance_m=distance, geometry=line.interpolate(distance))
            for distance in selected
        ]
    return result


def project_points_to_active_roads(
    *,
    source_road_ids: tuple[int, ...],
    roads_by_id: dict[int, dict[str, Any]],
    active_road_ids_by_source_id: dict[int, set[int]],
    points: tuple[BaseGeometry, ...],
    junction_type: str,
) -> dict[int, list[SplitPoint]]:
    distances_by_active_road: dict[int, list[float]] = {}
    usable_points = [point for point in points if point is not None and not point.is_empty]
    for source_road_id in source_road_ids:
        candidate_lines = _candidate_lines(
            source_road_id=source_road_id,
            roads_by_id=roads_by_id,
            active_road_ids_by_source_id=active_road_ids_by_source_id,
        )
        if not candidate_lines:
            continue
        for point in usable_points:
            projected_point = _as_point(point)
            active_road_id, line = min(
                candidate_lines,
                key=lambda item: item[1].distance(projected_point),
            )
            distances_by_active_road.setdefault(active_road_id, []).append(float(line.project(projected_point)))
    return {
        road_id: [
            SplitPoint(road_id=road_id, distance_m=distance, geometry=_as_line(roads_by_id[road_id]["geometry"]).interpolate(distance))
            for distance in _selected_distances(distances, junction_type)
        ]
        for road_id, distances in distances_by_active_road.items()
        if road_id in roads_by_id and _as_line(roads_by_id[road_id].get("geometry")) is not None
    }


def _candidate_lines(
    *,
    source_road_id: int,
    roads_by_id: dict[int, dict[str, Any]],
    active_road_ids_by_source_id: dict[int, set[int]],
) -> list[tuple[int, BaseGeometry]]:
    candidate_ids = sorted(active_road_ids_by_source_id.get(source_road_id) or {source_road_id})
    candidates: list[tuple[int, BaseGeometry]] = []
    for road_id in candidate_ids:
        road_feature = roads_by_id.get(road_id)
        if road_feature is None:
            continue
        line = _as_line(road_feature.get("geometry"))
        if line is None or line.is_empty:
            continue
        candidates.append((road_id, line))
    return candidates


def _selected_distances(distances: list[float], junction_type: str) -> list[float]:
    if not distances:
        return []
    if junction_type == "center_junction" and len(distances) > 1:
        selected = [min(distances), max(distances)]
        if abs(selected[0] - selected[1]) < 1e-9:
            return [selected[0]]
        return selected
    return [sum(distances) / len(distances)]


def _point_from_pair(x_value: Any, y_value: Any) -> Point | None:
    try:
        if x_value in (None, "") or y_value in (None, ""):
            return None
        return Point(float(x_value), float(y_value))
    except (TypeError, ValueError):
        return None


def _as_point(geometry: BaseGeometry) -> Point:
    return geometry if getattr(geometry, "geom_type", "") == "Point" else geometry.representative_point()


def _as_line(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None:
        return None
    if getattr(geometry, "geom_type", "") == "LineString":
        return geometry
    merged = linemerge(geometry)
    if getattr(merged, "geom_type", "") == "LineString":
        return merged
    if getattr(merged, "geoms", None):
        return max(merged.geoms, key=lambda item: item.length)
    return None
