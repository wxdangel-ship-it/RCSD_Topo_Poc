from __future__ import annotations

from math import ceil, hypot
from typing import Any, Iterable, Optional

from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, substring


def geometry_length(geometry: BaseGeometry) -> float:
    return float(geometry.length) if geometry is not None else 0.0


def geometry_coords(geometry: BaseGeometry) -> list[tuple[float, float]]:
    if geometry.geom_type == "LineString":
        return [(float(x), float(y)) for x, y in geometry.coords]

    merged = linemerge(geometry)
    if merged.geom_type == "LineString":
        return [(float(x), float(y)) for x, y in merged.coords]

    coords: list[tuple[float, float]] = []
    for part in merged.geoms:
        part_coords = [(float(x), float(y)) for x, y in part.coords]
        if not coords:
            coords.extend(part_coords)
            continue
        if coords[-1] == part_coords[0]:
            coords.extend(part_coords[1:])
        else:
            coords.extend(part_coords)
    return coords


def line_geometry_from_coords(coords: list[tuple[float, float]]) -> Optional[BaseGeometry]:
    if len(coords) < 2:
        return None
    return LineString(coords)


def line_geometry_from_road_ids(
    road_ids: tuple[str, ...],
    *,
    roads: dict[str, Any],
) -> Optional[BaseGeometry]:
    parts: list[LineString] = []
    for road_id in road_ids:
        coords = geometry_coords(roads[road_id].geometry)
        if len(coords) < 2:
            continue
        parts.append(LineString(coords))
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return MultiLineString(parts)


def max_nearest_distance_m(
    source_geometry: Optional[BaseGeometry],
    target_geometry: Optional[BaseGeometry],
) -> Optional[float]:
    if source_geometry is None or target_geometry is None:
        return None
    if source_geometry.is_empty or target_geometry.is_empty:
        return None
    return float(source_geometry.hausdorff_distance(target_geometry))


def trimmed_line_body_geometry(
    geometry: Optional[BaseGeometry],
    *,
    trim_m: float,
) -> Optional[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return geometry
    line = line_geometry_from_coords(geometry_coords(geometry))
    if line is None:
        return geometry
    length_m = geometry_length(line)
    if length_m <= trim_m * 2.0:
        return line
    return substring(line, trim_m, length_m - trim_m)


def iter_sample_points(
    geometry: Optional[BaseGeometry],
    *,
    sample_step_m: float,
) -> Iterable[Point]:
    if geometry is None or geometry.is_empty:
        return

    if isinstance(geometry, LineString):
        parts = (geometry,)
    elif isinstance(geometry, MultiLineString):
        parts = tuple(part for part in geometry.geoms if not part.is_empty)
    else:
        return

    for part in parts:
        coords = geometry_coords(part)
        if len(coords) < 2:
            continue
        for start, end in zip(coords, coords[1:]):
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            segment_length = hypot(dx, dy)
            if segment_length <= 0.0:
                continue
            sample_count = max(3, ceil(segment_length / sample_step_m) + 1)
            for sample_index in range(sample_count):
                fraction = sample_index / (sample_count - 1)
                yield Point(start[0] + dx * fraction, start[1] + dy * fraction)


def max_sampled_distance_m(
    source_geometry: Optional[BaseGeometry],
    target_geometry: Optional[BaseGeometry],
    *,
    sample_step_m: float,
) -> Optional[float]:
    if source_geometry is None or target_geometry is None:
        return None
    if source_geometry.is_empty or target_geometry.is_empty:
        return None

    max_distance_m: Optional[float] = None
    for sample_point in iter_sample_points(source_geometry, sample_step_m=sample_step_m):
        distance_m = float(sample_point.distance(target_geometry))
        if max_distance_m is None or distance_m > max_distance_m:
            max_distance_m = distance_m
    return max_distance_m
