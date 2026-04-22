from __future__ import annotations

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry


POLYGON_SMALL_HOLE_AREA_M2 = 18.0
POLYGON_FINAL_COMPONENT_MIN_AREA_M2 = 1.0
POLYGON_FINAL_SMOOTH_M = 1.0


def _fill_small_polygon_holes(
    geometry: BaseGeometry,
    *,
    max_hole_area_m2: float,
) -> BaseGeometry:
    if geometry.is_empty:
        return geometry

    if isinstance(geometry, Polygon):
        kept_interiors = [
            ring.coords
            for ring in geometry.interiors
            if Polygon(ring).area > max_hole_area_m2
        ]
        return Polygon(geometry.exterior.coords, kept_interiors)

    if isinstance(geometry, MultiPolygon):
        return MultiPolygon(
            [
                polygon
                for polygon in (
                    _fill_small_polygon_holes(part, max_hole_area_m2=max_hole_area_m2)
                    for part in geometry.geoms
                )
                if isinstance(polygon, Polygon) and not polygon.is_empty
            ]
        )

    return geometry


def _remove_all_polygon_holes(geometry: BaseGeometry) -> BaseGeometry:
    if geometry.is_empty:
        return geometry

    if isinstance(geometry, Polygon):
        return Polygon(geometry.exterior.coords)

    if isinstance(geometry, MultiPolygon):
        polygons = [
            Polygon(polygon.exterior.coords)
            for polygon in geometry.geoms
            if not polygon.is_empty
        ]
        if not polygons:
            return GeometryCollection()
        if len(polygons) == 1:
            return polygons[0]
        return MultiPolygon(polygons)

    return geometry


def _polygon_components(geometry: BaseGeometry) -> list[Polygon]:
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return [polygon for polygon in geometry.geoms if not polygon.is_empty]
    return []


def _select_seed_connected_polygon(
    *,
    geometry: BaseGeometry,
    seed_geometry: BaseGeometry,
) -> BaseGeometry:
    components = [
        component
        for component in _polygon_components(geometry)
        if component.area > POLYGON_FINAL_COMPONENT_MIN_AREA_M2
    ]
    if not components:
        return GeometryCollection()

    seeded_components = [component for component in components if component.intersects(seed_geometry)]
    if seeded_components:
        selected = max(seeded_components, key=lambda component: component.area)
    else:
        selected = min(
            components,
            key=lambda component: (component.distance(seed_geometry), -component.area),
        )
    return selected.buffer(0)


def _regularize_virtual_polygon_geometry(
    *,
    geometry: BaseGeometry,
    drivezone_union: BaseGeometry,
    seed_geometry: BaseGeometry,
) -> BaseGeometry:
    if geometry.is_empty:
        return geometry

    regularized = geometry.intersection(drivezone_union)
    if regularized.is_empty:
        return regularized

    regularized = regularized.buffer(0)
    regularized = _fill_small_polygon_holes(
        regularized,
        max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
    )
    regularized = regularized.buffer(POLYGON_FINAL_SMOOTH_M, join_style=1).buffer(
        -POLYGON_FINAL_SMOOTH_M,
        join_style=1,
    )
    regularized = regularized.intersection(drivezone_union)
    if regularized.is_empty:
        return regularized
    regularized = regularized.buffer(0)
    regularized = _fill_small_polygon_holes(
        regularized,
        max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
    )
    regularized = _remove_all_polygon_holes(regularized)
    regularized = _select_seed_connected_polygon(
        geometry=regularized,
        seed_geometry=seed_geometry,
    )
    return regularized.intersection(drivezone_union).buffer(0) if not regularized.is_empty else regularized


__all__ = [name for name in globals() if not name.startswith("__")]
