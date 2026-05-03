from __future__ import annotations

from shapely.geometry import GeometryCollection, LineString, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from ._rcsd_selection_support import _normalize_geometry, _union_geometry
from ._runtime_polygon_cleanup import _polygon_components


STEP6_DOMINANT_COMPONENT_RELIEF_MIN_RATIO = 0.75
STEP6_DOMINANT_COMPONENT_RELIEF_MAX_DISTANCE_M = 22.0
STEP6_DOMINANT_COMPONENT_RELIEF_BUFFER_M = 4.0
STEP6_CUT_SLIVER_HOLE_RELIEF_MAX_AREA_M2 = 80.0
STEP6_CUT_SLIVER_HOLE_RELIEF_MIN_CUT_RATIO = 0.5
STEP6_CUT_SLIVER_HOLE_RELIEF_MIN_ALLOWED_RATIO = 0.9
STEP6_FORBIDDEN_TOLERANCE_AREA_M2 = 1e-6


def seed_dominant_polygon_component(
    geometry: BaseGeometry | None,
    seed_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return None
    parts = _polygon_components(normalized)
    if len(parts) <= 1:
        return normalized
    seed = _normalize_geometry(seed_geometry)
    if seed is None:
        return _normalize_geometry(max(parts, key=lambda part: float(part.area)))
    overlaps = [
        (
            float(part.intersection(seed).area),
            float(part.area),
            part,
        )
        for part in parts
    ]
    positive_overlaps = [item for item in overlaps if item[0] > 1e-6]
    if positive_overlaps:
        return _normalize_geometry(max(positive_overlaps, key=lambda item: (item[0], item[1]))[2])
    touching = [
        part
        for part in parts
        if part.buffer(1e-6).intersects(seed)
    ]
    if touching:
        return _normalize_geometry(max(touching, key=lambda part: float(part.area)))
    return _normalize_geometry(
        min(parts, key=lambda part: (float(part.distance(seed)), -float(part.area)))
    )


def dominant_component_relief_bridge(
    geometry: BaseGeometry | None,
    *,
    allowed_geometry: BaseGeometry | None,
    terminal_window_geometry: BaseGeometry | None,
    cut_barrier_geometry: BaseGeometry | None,
    min_ratio: float = STEP6_DOMINANT_COMPONENT_RELIEF_MIN_RATIO,
    max_distance_m: float = STEP6_DOMINANT_COMPONENT_RELIEF_MAX_DISTANCE_M,
    use_terminal_window: bool = True,
) -> BaseGeometry | None:
    _ = cut_barrier_geometry
    parts = sorted(_polygon_components(geometry or GeometryCollection()), key=lambda part: float(part.area), reverse=True)
    if len(parts) <= 1:
        return None
    total_area = sum(float(part.area) for part in parts)
    if total_area <= 0.0 or float(parts[0].area) / total_area < min_ratio:
        return None
    current = parts[0]
    bridges: list[BaseGeometry] = []
    for part in parts[1:]:
        distance = float(current.distance(part))
        if distance > max_distance_m:
            return None
        start, end = nearest_points(current, part)
        if distance <= 1e-6:
            bridge = start.buffer(STEP6_DOMINANT_COMPONENT_RELIEF_BUFFER_M)
        else:
            bridge = LineString([start, end]).buffer(
                STEP6_DOMINANT_COMPONENT_RELIEF_BUFFER_M,
                cap_style=2,
                join_style=2,
            )
        if allowed_geometry is not None and not allowed_geometry.is_empty:
            bridge = bridge.intersection(allowed_geometry)
        if use_terminal_window and terminal_window_geometry is not None and not terminal_window_geometry.is_empty:
            bridge = bridge.intersection(terminal_window_geometry)
        bridge = _normalize_geometry(bridge)
        if bridge is None or bridge.is_empty:
            return None
        bridges.append(bridge)
        current = _normalize_geometry(_union_geometry([current, part, bridge])) or current
    return _normalize_geometry(_union_geometry(bridges))


def hole_polygons(geometry: BaseGeometry | None) -> list[Polygon]:
    holes: list[Polygon] = []
    for polygon in _polygon_components(geometry or GeometryCollection()):
        for ring in polygon.interiors:
            hole = Polygon(ring)
            if not hole.is_empty:
                holes.append(hole)
    return holes


def cut_sliver_hole_relief(
    geometry: BaseGeometry | None,
    *,
    forbidden_geometry: BaseGeometry | None,
    allowed_geometry: BaseGeometry | None,
    cut_barrier_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    relief_holes: list[BaseGeometry] = []
    if cut_barrier_geometry is None or cut_barrier_geometry.is_empty:
        return None
    for hole in hole_polygons(geometry):
        hole_area = float(hole.area)
        if hole_area <= 0.0 or hole_area > STEP6_CUT_SLIVER_HOLE_RELIEF_MAX_AREA_M2:
            continue
        forbidden_overlap = (
            0.0
            if forbidden_geometry is None or forbidden_geometry.is_empty
            else float(hole.intersection(forbidden_geometry).area)
        )
        allowed_overlap = (
            hole_area
            if allowed_geometry is None or allowed_geometry.is_empty
            else float(hole.intersection(allowed_geometry).area)
        )
        cut_overlap = float(hole.intersection(cut_barrier_geometry).area)
        if forbidden_overlap > STEP6_FORBIDDEN_TOLERANCE_AREA_M2:
            continue
        if cut_overlap / hole_area < STEP6_CUT_SLIVER_HOLE_RELIEF_MIN_CUT_RATIO:
            continue
        if allowed_overlap / hole_area < STEP6_CUT_SLIVER_HOLE_RELIEF_MIN_ALLOWED_RATIO:
            continue
        relief_holes.append(hole)
    return _normalize_geometry(_union_geometry(relief_holes))


__all__ = [
    "cut_sliver_hole_relief",
    "dominant_component_relief_bridge",
    "hole_polygons",
    "seed_dominant_polygon_component",
]
