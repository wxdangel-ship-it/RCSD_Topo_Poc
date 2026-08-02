from __future__ import annotations

from typing import Any

from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


def _clean_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    if not geometry.is_valid:
        return None
    return geometry


def _iter_polygons(geometry: BaseGeometry | None):
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type == "Polygon":
        yield geometry
        return
    if hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            yield from _iter_polygons(part)


def _hole_polygons(geometry: BaseGeometry | None) -> list[Polygon]:
    return [
        Polygon(ring)
        for polygon in _iter_polygons(geometry)
        for ring in polygon.interiors
        if not Polygon(ring).is_empty
    ]


def regularize_surface_with_legal_edge_trace(
    *,
    surface: BaseGeometry | None,
    allowed_surface: BaseGeometry | None,
    direction_boundary: BaseGeometry | None,
    foreign_mask: BaseGeometry | None,
    smoothing_distance_m: float,
    permitted_hole_coverage_ratio: float = 0.999999,
) -> tuple[BaseGeometry | None, dict[str, Any]]:
    """Regularize only inside the already established legal Road-surface space.

    The operation never changes source geometry. It performs the existing
    round-buffer closing, clips the result to the legal/directional surface,
    and fills only holes whose full area is still permitted after the foreign
    mask. A MultiPolygon is preserved unless the permitted surface itself
    provides a real connection.
    """

    invalid_input_roles = [
        role
        for role, geometry in (
            ("surface", surface),
            ("allowed_surface", allowed_surface),
            ("direction_boundary", direction_boundary),
            ("foreign_mask", foreign_mask),
        )
        if geometry is not None
        and not geometry.is_empty
        and not geometry.is_valid
    ]
    if invalid_input_roles:
        return None, {
            "mode": "legal_road_surface_edge_trace",
            "applied": False,
            "reason": "invalid_input_geometry",
            "invalid_input_roles": invalid_input_roles,
            "smoothing_distance_m": smoothing_distance_m,
            "input_hole_count": 0,
            "filled_hole_count": 0,
            "retained_hole_count": 0,
            "hole_decisions": [],
            "silent_fix": False,
            "source_geometry_modified": False,
        }

    cleaned_surface = _clean_geometry(surface)
    permitted_surface = _clean_geometry(
        allowed_surface.intersection(direction_boundary)
        if allowed_surface is not None and direction_boundary is not None
        else None
    )
    if permitted_surface is not None and foreign_mask is not None:
        permitted_surface = _clean_geometry(permitted_surface.difference(foreign_mask))
    input_holes = _hole_polygons(cleaned_surface)
    if cleaned_surface is None or permitted_surface is None:
        return cleaned_surface, {
            "mode": "legal_road_surface_edge_trace",
            "applied": False,
            "reason": "surface_or_permitted_space_missing",
            "smoothing_distance_m": smoothing_distance_m,
            "input_hole_count": len(input_holes),
            "filled_hole_count": 0,
            "retained_hole_count": len(input_holes),
            "hole_decisions": [],
            "silent_fix": False,
            "source_geometry_modified": False,
        }

    regularized = cleaned_surface
    if smoothing_distance_m > 0:
        regularized = _clean_geometry(
            regularized.buffer(smoothing_distance_m).buffer(-smoothing_distance_m)
        )
    if regularized is not None:
        regularized = _clean_geometry(regularized.intersection(permitted_surface))
    if regularized is None:
        return None, {
            "mode": "legal_road_surface_edge_trace",
            "applied": False,
            "reason": "regularization_produced_invalid_or_empty_geometry",
            "invalid_input_roles": [],
            "smoothing_distance_m": smoothing_distance_m,
            "input_hole_count": len(input_holes),
            "filled_hole_count": 0,
            "retained_hole_count": len(input_holes),
            "hole_decisions": [],
            "silent_fix": False,
            "source_geometry_modified": False,
        }
    hole_decisions: list[dict[str, Any]] = []
    fill_geometries: list[BaseGeometry] = []
    for hole_index, hole in enumerate(_hole_polygons(regularized), start=1):
        hole_area_m2 = float(hole.area)
        permitted_area_m2 = float(hole.intersection(permitted_surface).area)
        coverage_ratio = (
            permitted_area_m2 / hole_area_m2 if hole_area_m2 > 0 else 0.0
        )
        fill = coverage_ratio >= permitted_hole_coverage_ratio
        if fill:
            fill_geometries.append(hole)
        hole_decisions.append(
            {
                "hole_index": hole_index,
                "hole_area_m2": round(hole_area_m2, 6),
                "permitted_area_m2": round(permitted_area_m2, 6),
                "permitted_coverage_ratio": round(coverage_ratio, 9),
                "decision": (
                    "fill_algorithmic_void_inside_permitted_surface"
                    if fill
                    else "retain_source_or_constraint_void"
                ),
            }
        )
    if fill_geometries:
        regularized = _clean_geometry(
            unary_union([regularized, *fill_geometries]).intersection(permitted_surface)
        )
    output_holes = _hole_polygons(regularized)
    return regularized, {
        "mode": "legal_road_surface_edge_trace",
        "applied": True,
        "reason": "regularized_within_frozen_legal_and_directional_surface",
        "smoothing_distance_m": smoothing_distance_m,
        "permitted_hole_coverage_ratio": permitted_hole_coverage_ratio,
        "input_hole_count": len(input_holes),
        "post_smoothing_hole_count": len(hole_decisions),
        "filled_hole_count": len(fill_geometries),
        "filled_hole_area_m2": round(sum(item.area for item in fill_geometries), 6),
        "retained_hole_count": len(output_holes),
        "hole_decisions": hole_decisions,
        "input_area_m2": round(cleaned_surface.area, 6),
        "output_area_m2": round(regularized.area, 6) if regularized is not None else 0.0,
        "component_count_before": sum(1 for _ in _iter_polygons(cleaned_surface)),
        "component_count_after": sum(1 for _ in _iter_polygons(regularized)),
        "forced_single_polygon": False,
        "silent_fix": False,
        "source_geometry_modified": False,
    }
