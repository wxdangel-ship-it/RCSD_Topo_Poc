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
