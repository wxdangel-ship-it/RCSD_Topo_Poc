from __future__ import annotations

from typing import Literal

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, substring

Endpoint = Literal["start", "end"]


def _line_parts(geometry: BaseGeometry | None) -> tuple[LineString, ...]:
    if geometry is None or geometry.is_empty:
        return ()
    if isinstance(geometry, LineString):
        return (geometry,) if geometry.length > 0.0 else ()
    parts: list[LineString] = []
    for part in getattr(geometry, "geoms", ()):
        parts.extend(_line_parts(part))
    return tuple(parts)


def line_part_count(geometry: BaseGeometry | None) -> int:
    return len(_line_parts(geometry))


def multipart_road_handling_fields(swsd_roads, rcsd_roads) -> dict:
    def _records(roads) -> list[dict]:
        records: list[dict] = []
        for road in roads:
            part_count = line_part_count(road.geometry)
            if part_count > 1:
                records.append({"road_id": road.road_id, "line_part_count": part_count})
        return sorted(records, key=lambda item: item["road_id"])

    return {
        "multipart_road_handling": {
            "strategy": "endpoint_or_reference_line_part_without_global_geometry_mutation",
            "swsd_roads": _records(swsd_roads),
            "rcsd_roads": _records(rcsd_roads),
        }
    }


def _reversed_line(line: LineString) -> LineString:
    return LineString(list(line.coords)[::-1])


def _oriented_to_endpoint(line: LineString, point: Point, endpoint: Endpoint) -> LineString:
    start = Point(line.coords[0])
    end = Point(line.coords[-1])
    if endpoint == "start":
        return line if start.distance(point) <= end.distance(point) else _reversed_line(line)
    return line if end.distance(point) <= start.distance(point) else _reversed_line(line)


def _single_merged_line(geometry: BaseGeometry | None) -> LineString | None:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, LineString):
        return geometry if geometry.length > 0.0 else None
    try:
        merged = linemerge(geometry)
    except (TypeError, ValueError):
        return None
    if isinstance(merged, LineString) and merged.length > 0.0:
        return merged
    return None


def endpoint_line(geometry: BaseGeometry | None, endpoint: Endpoint) -> LineString | None:
    parts = _line_parts(geometry)
    if not parts:
        return None
    endpoint_coord = parts[0].coords[0] if endpoint == "start" else parts[-1].coords[-1]
    endpoint_point = Point(endpoint_coord)
    merged = _single_merged_line(geometry)
    if merged is not None:
        return _oriented_to_endpoint(merged, endpoint_point, endpoint)
    part = parts[0] if endpoint == "start" else parts[-1]
    return _oriented_to_endpoint(part, endpoint_point, endpoint)


def nearest_line(geometry: BaseGeometry | None, reference: Point) -> LineString | None:
    merged = _single_merged_line(geometry)
    if merged is not None:
        return merged
    parts = _line_parts(geometry)
    if not parts:
        return None
    return min(
        parts,
        key=lambda line: min(
            Point(line.coords[0]).distance(reference),
            Point(line.coords[-1]).distance(reference),
        ),
    )


def endpoint_point(geometry: BaseGeometry | None, endpoint: Endpoint) -> Point | None:
    line = endpoint_line(geometry, endpoint)
    if line is None:
        return None
    coord = line.coords[0] if endpoint == "start" else line.coords[-1]
    return Point(coord)


def substring_from_endpoint(
    geometry: BaseGeometry | None,
    endpoint: Endpoint,
    keep_len: float,
) -> BaseGeometry | None:
    line = endpoint_line(geometry, endpoint)
    if line is None:
        return None
    length = float(line.length)
    keep = min(max(float(keep_len), 0.0), length)
    if keep <= 0.0:
        return None
    if endpoint == "start":
        return substring(line, 0.0, keep)
    return substring(line, max(0.0, length - keep), length)
