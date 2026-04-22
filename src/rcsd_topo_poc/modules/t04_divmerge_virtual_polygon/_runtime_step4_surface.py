from __future__ import annotations

from shapely.geometry import Point
from shapely.ops import linemerge, unary_union

from ._runtime_types_io import ParsedRoad
from ._runtime_step4_geometry_core import _explode_component_geometries

def _resolve_centerline_from_road_ids(
    *,
    road_ids: list[str],
    road_lookup: dict[str, ParsedRoad],
    reference_point: Point,
):
    line_union = unary_union(
        [
            road_lookup[road_id].geometry
            for road_id in road_ids
            if road_id in road_lookup
            and road_lookup[road_id].geometry is not None
            and not road_lookup[road_id].geometry.is_empty
        ]
    )
    if line_union.is_empty:
        return None
    merged = line_union if getattr(line_union, "geom_type", None) == "LineString" else linemerge(line_union)
    line_components = [
        component
        for component in _explode_component_geometries(merged)
        if getattr(component, "geom_type", None) == "LineString" and not component.is_empty
    ]
    if not line_components:
        line_components = [
            component
            for component in _explode_component_geometries(line_union)
            if getattr(component, "geom_type", None) == "LineString" and not component.is_empty
        ]
    if not line_components:
        return None
    centerline = min(
        line_components,
        key=lambda component: (
            float(component.distance(reference_point)),
            -float(component.length),
        ),
    )
    coords = list(centerline.coords)
    if len(coords) < 2:
        return centerline
    start_point = Point(coords[0])
    end_point = Point(coords[-1])
    if end_point.distance(reference_point) < start_point.distance(reference_point):
        centerline = type(centerline)(coords[::-1])
    return centerline


__all__ = [name for name in globals() if not name.startswith("__")]
