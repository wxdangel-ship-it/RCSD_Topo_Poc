from __future__ import annotations

from typing import Any, Iterable

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .case_models import T04CaseResult, T04EventUnitResult

ROAD_SURFACE_FORK_BINDING_REASON = "road_surface_fork_binding_used"
UNBOUND_ROAD_SURFACE_FORK_REASON = "unbound_road_surface_fork_without_bifurcation_rcsd"
STRUCTURE_ONLY_SURFACE_REASON = "road_surface_fork_structure_only_used"
SWSD_JUNCTION_WINDOW_REASON = "swsd_junction_window_no_rcsd_used"
RCSD_JUNCTION_WINDOW_REASON = "rcsd_junction_window_used"
ROAD_SURFACE_FORK_SCOPE = "road_surface_fork"
THROAT_CORE_SCOPE = "throat_core"
SWSD_JUNCTION_WINDOW_SOURCE = "swsd_junction_window"
RCSD_JUNCTION_WINDOW_SOURCE = "rcsd_junction_window"
SWSD_JUNCTION_WINDOW_POSITION_SOURCE = "swsd_junction_window_axis_projection"
RCSD_JUNCTION_WINDOW_POSITION_SOURCE = "rcsd_junction_window_axis_projection"
JUNCTION_WINDOW_HALF_LENGTH_M = 20.0
RELAXED_AGGREGATED_RCSD_REASONS = {
    "role_mapping_partial_relaxed_aggregated",
}
RELAXED_PRIMARY_BINDING_MODE = "road_surface_fork_relaxed_primary_rcsd_binding"
RELAXED_PRIMARY_NODE_SOURCE = "road_surface_fork_relaxed_primary_rcsd"
RELAXED_PRIMARY_MAX_REPRESENTATIVE_DISTANCE_M = 20.0
SURFACE_RECOVERY_MIN_THROAT_RATIO = 0.8
SURFACE_RECOVERY_MAX_REFERENCE_DISTANCE_M = 10.0
SURFACE_RECOVERY_THROAT_EXCLUSION_M = 0.0
STRUCTURE_ONLY_SURFACE_MIN_AXIS_POSITION_M = 12.0
STRUCTURE_ONLY_SURFACE_MIN_PAIR_MIDDLE_RATIO = 0.05
STRUCTURE_ONLY_SURFACE_WINDOW_MAX_PAIR_MIDDLE_RATIO = 0.10
SAME_CASE_RCSD_ROAD_OVERLAP_MIN_COUNT = 2
SAME_CASE_RCSD_ROAD_OVERLAP_MIN_RATIO = 0.5
SURFACE_FORK_REFERENCE_SURFACE_TOLERANCE_M = 3.0
SURFACE_FORK_APEX_MIN_ORIGIN_DISTANCE_M = 25.0
SURFACE_FORK_APEX_MIN_BRANCH_SEPARATION_M = 10.0
SURFACE_FORK_APEX_MAX_MIDLINE_DISTANCE_M = 6.0
SURFACE_FORK_APEX_MAX_MIDLINE_SEPARATION_RATIO = 0.5
SURFACE_FORK_APEX_MIN_TRANSVERSE_ALIGNMENT = 0.7

def _dedupe(items: Iterable[Any]) -> tuple[str, ...]:
    values: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        values.append(text)
    return tuple(values)


def _clean_surface_review_reasons(items: Iterable[Any]) -> tuple[str, ...]:
    dropped = {
        "event_reference_outside_branch_middle",
        "fallback_to_weak_evidence",
        "node_fallback_candidate_not_primary_eligible",
        "no_selected_evidence_after_reselection",
        "missing_positive_rcsd",
    }
    return _dedupe(reason for reason in items if str(reason or "") not in dropped)


def _feature_geometry_by_id(features: Iterable[Any], feature_id: str, id_attr: str) -> BaseGeometry | None:
    text = str(feature_id or "").strip()
    if not text:
        return None
    for feature in features:
        if str(getattr(feature, id_attr, "") or "") == text:
            geometry = getattr(feature, "geometry", None)
            if geometry is not None and not geometry.is_empty:
                return geometry
    return None


def _union_geometries(geometries: Iterable[BaseGeometry | None]) -> BaseGeometry | None:
    parts = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not parts:
        return None
    try:
        merged = unary_union(parts)
    except Exception:
        merged = parts[0]
    if merged is None or merged.is_empty:
        return None
    return merged


def _polygon_parts(geometry: BaseGeometry | None) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty]
    return []


def _seed_component_geometry(
    geometry: BaseGeometry | None,
    seed_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    parts = _polygon_parts(geometry)
    if not parts:
        return geometry
    if seed_geometry is None or seed_geometry.is_empty:
        return max(parts, key=lambda part: float(part.area))
    touching = [part for part in parts if part.buffer(1e-6).intersects(seed_geometry)]
    if touching:
        return max(touching, key=lambda part: float(part.area))
    return min(parts, key=lambda part: (float(part.distance(seed_geometry)), -float(part.area)))


def _largest_polygon_component(geometry: BaseGeometry | None) -> BaseGeometry | None:
    parts = _polygon_parts(geometry)
    if not parts:
        return geometry
    return max(parts, key=lambda part: float(part.area))


def _road_geometries(case_result: T04CaseResult, road_ids: Iterable[str]) -> BaseGeometry | None:
    return _union_geometries(
        _feature_geometry_by_id(case_result.case_bundle.rcsd_roads, road_id, "road_id")
        for road_id in road_ids
    )


def _node_geometries(case_result: T04CaseResult, node_ids: Iterable[str]) -> BaseGeometry | None:
    return _union_geometries(
        _feature_geometry_by_id(case_result.case_bundle.rcsd_nodes, node_id, "node_id")
        for node_id in node_ids
    )


def _swsd_road_line(case_result: T04CaseResult, road_id: str) -> LineString | None:
    geometry = _feature_geometry_by_id(case_result.case_bundle.roads, road_id, "road_id")
    if isinstance(geometry, LineString) and not geometry.is_empty and geometry.length > 1e-6:
        return geometry
    return None


def _ordered_line_from_point(line: LineString, origin: Point) -> LineString:
    coords = list(line.coords)
    if not coords:
        return line
    first = Point(coords[0])
    last = Point(coords[-1])
    if last.distance(origin) < first.distance(origin):
        coords = list(reversed(coords))
    return LineString(coords)


def _boundary_pair_road_ids(event_unit: T04EventUnitResult) -> tuple[str, str] | None:
    summaries = (
        event_unit.selected_candidate_summary,
        event_unit.selected_evidence_summary,
        event_unit.pair_local_summary,
    )
    for summary in summaries:
        signature = str((summary or {}).get("boundary_pair_signature") or "").strip()
        if not signature:
            continue
        parts = tuple(part.strip() for part in signature.split("__") if part.strip())
        if len(parts) == 2:
            return parts[0], parts[1]
    return None


def _road_surface_reference_domain(event_unit: T04EventUnitResult) -> BaseGeometry | None:
    return (
        event_unit.selected_candidate_region_geometry
        or event_unit.pair_local_region_geometry
        or event_unit.pair_local_structure_face_geometry
        or event_unit.selected_evidence_region_geometry
    )


def _surface_fork_boundary_apex_point(
    surface_domain: BaseGeometry,
    *,
    ordered_a: LineString,
    ordered_b: LineString,
    origin: Point,
) -> tuple[Point | None, dict[str, Any]]:
    candidates: list[tuple[tuple[float, float, float], Point, dict[str, Any]]] = []
    for polygon_index, polygon in enumerate(_polygon_parts(surface_domain)):
        coords = list(polygon.exterior.coords)
        if len(coords) < 2:
            continue
        for segment_index, (start, end) in enumerate(zip(coords[:-1], coords[1:])):
            seg_x = float(end[0]) - float(start[0])
            seg_y = float(end[1]) - float(start[1])
            seg_len = (seg_x * seg_x + seg_y * seg_y) ** 0.5
            if seg_len <= 1e-6:
                continue
            midpoint = Point(
                (float(start[0]) + float(end[0])) / 2.0,
                (float(start[1]) + float(end[1])) / 2.0,
            )
            origin_distance = float(midpoint.distance(origin))
            if origin_distance < SURFACE_FORK_APEX_MIN_ORIGIN_DISTANCE_M:
                continue
            sample_distance = min(
                max(0.0, (float(ordered_a.project(midpoint)) + float(ordered_b.project(midpoint))) / 2.0),
                float(ordered_a.length),
                float(ordered_b.length),
            )
            point_a = ordered_a.interpolate(sample_distance)
            point_b = ordered_b.interpolate(sample_distance)
            branch_separation = float(point_a.distance(point_b))
            if branch_separation < SURFACE_FORK_APEX_MIN_BRANCH_SEPARATION_M:
                continue
            pair_midpoint = Point(
                (float(point_a.x) + float(point_b.x)) / 2.0,
                (float(point_a.y) + float(point_b.y)) / 2.0,
            )
            midline_distance = float(midpoint.distance(pair_midpoint))
            max_midline_distance = max(
                SURFACE_FORK_APEX_MAX_MIDLINE_DISTANCE_M,
                branch_separation * SURFACE_FORK_APEX_MAX_MIDLINE_SEPARATION_RATIO,
            )
            if midline_distance > max_midline_distance:
                continue
            sep_x = float(point_b.x) - float(point_a.x)
            sep_y = float(point_b.y) - float(point_a.y)
            sep_len = (sep_x * sep_x + sep_y * sep_y) ** 0.5
            if sep_len <= 1e-6:
                continue
            transverse_alignment = abs((seg_x * sep_x + seg_y * sep_y) / (seg_len * sep_len))
            if transverse_alignment < SURFACE_FORK_APEX_MIN_TRANSVERSE_ALIGNMENT:
                continue
            detail = {
                "road_surface_fork_reference_point_mode": "road_surface_fork_boundary_apex",
                "road_surface_fork_reference_distance_m": round(origin_distance, 3),
                "road_surface_fork_reference_sample_s_m": round(sample_distance, 3),
                "road_surface_fork_branch_separation_m": round(branch_separation, 3),
                "road_surface_fork_apex_midline_distance_m": round(midline_distance, 3),
                "road_surface_fork_apex_transverse_alignment": round(transverse_alignment, 3),
                "road_surface_fork_apex_polygon_index": polygon_index,
                "road_surface_fork_apex_segment_index": segment_index,
            }
            score = (sample_distance, midline_distance, -transverse_alignment)
            candidates.append((score, midpoint, detail))
    if not candidates:
        return None, {"road_surface_fork_reference_point_mode": "boundary_apex_unavailable"}
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1], candidates[0][2]


def _road_surface_fork_reference_point(
    case_result: T04CaseResult,
    event_unit: T04EventUnitResult,
) -> tuple[Point | None, dict[str, Any]]:
    surface_domain = _road_surface_reference_domain(event_unit)
    origin = event_unit.fact_reference_point or getattr(event_unit.unit_context.representative_node, "geometry", None)
    if surface_domain is None or surface_domain.is_empty or not isinstance(origin, Point):
        return None, {"road_surface_fork_reference_point_mode": "unavailable"}
    seed_point = surface_domain.representative_point()
    boundary_pair = _boundary_pair_road_ids(event_unit)
    if boundary_pair is None:
        return seed_point, {
            "road_surface_fork_reference_point_mode": "surface_representative_point",
            "road_surface_fork_reference_distance_m": round(float(seed_point.distance(origin)), 3),
        }

    line_a = _swsd_road_line(case_result, boundary_pair[0])
    line_b = _swsd_road_line(case_result, boundary_pair[1])
    if line_a is None or line_b is None:
        return seed_point, {
            "road_surface_fork_reference_point_mode": "surface_representative_point",
            "road_surface_fork_reference_distance_m": round(float(seed_point.distance(origin)), 3),
            "boundary_pair_road_ids": list(boundary_pair),
        }

    ordered_a = _ordered_line_from_point(line_a, origin)
    ordered_b = _ordered_line_from_point(line_b, origin)
    apex_point, apex_detail = _surface_fork_boundary_apex_point(
        surface_domain,
        ordered_a=ordered_a,
        ordered_b=ordered_b,
        origin=origin,
    )
    if apex_point is not None:
        apex_detail["boundary_pair_road_ids"] = list(boundary_pair)
        apex_detail["road_surface_fork_seed_point_xy"] = [
            round(float(seed_point.x), 3),
            round(float(seed_point.y), 3),
        ]
        return apex_point, apex_detail

    sample_distance = min(
        max(0.0, (float(ordered_a.project(seed_point)) + float(ordered_b.project(seed_point))) / 2.0),
        float(ordered_a.length),
        float(ordered_b.length),
    )
    point_a = ordered_a.interpolate(sample_distance)
    point_b = ordered_b.interpolate(sample_distance)
    midpoint = Point((float(point_a.x) + float(point_b.x)) / 2.0, (float(point_a.y) + float(point_b.y)) / 2.0)
    if not surface_domain.buffer(SURFACE_FORK_REFERENCE_SURFACE_TOLERANCE_M, join_style=2).covers(midpoint):
        midpoint = seed_point
    return midpoint, {
        "road_surface_fork_reference_point_mode": "boundary_pair_surface_midpoint_fallback",
        "boundary_pair_road_ids": list(boundary_pair),
        "road_surface_fork_reference_distance_m": round(float(midpoint.distance(origin)), 3),
        "road_surface_fork_reference_sample_s_m": round(sample_distance, 3),
        "road_surface_fork_branch_separation_m": round(float(point_a.distance(point_b)), 3),
        "road_surface_fork_seed_point_xy": [round(float(seed_point.x), 3), round(float(seed_point.y), 3)],
    }


def _point_geometry(case_result: T04CaseResult, node_id: str | None) -> Point | None:
    geometry = _feature_geometry_by_id(case_result.case_bundle.rcsd_nodes, str(node_id or ""), "node_id")
    return geometry if isinstance(geometry, Point) else None


def _as_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None

