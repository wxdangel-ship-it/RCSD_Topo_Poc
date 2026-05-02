from __future__ import annotations

from typing import Any, Iterable, Sequence

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry

from ._rcsd_selection_support import _as_point, _normalize_geometry, _union_geometry
from ._runtime_types_io import ParsedRoad
from .case_models import T04CaseResult, T04EventUnitResult
from .support_domain_scenario import (
    STEP5_NEGATIVE_MASK_BUFFER_M,
    STEP5_SUPPORT_ROAD_BUFFER_M,
    STEP5_TERMINAL_AXIS_ANCHOR_TOLERANCE_M,
    STEP5_TERMINAL_CUT_WINDOW_MARGIN_M,
    STEP5_TERMINAL_MIN_ANCHOR_SPAN_M,
    STEP5_TERMINAL_WINDOW_FALLBACK_HALF_WIDTH_M,
    Step5SurfaceWindowConfig,
    derive_step5_surface_window_config,
)
from .surface_scenario import (
    SECTION_REFERENCE_NONE,
    SECTION_REFERENCE_POINT,
    SECTION_REFERENCE_POINT_AND_RCSD,
    SECTION_REFERENCE_RCSD,
    SECTION_REFERENCE_SWSD,
    classify_surface_scenario,
)


def _iter_polygon_parts(geometry: BaseGeometry | None) -> Iterable[Polygon]:
    if geometry is None or geometry.is_empty:
        return ()
    if isinstance(geometry, Polygon):
        return (geometry,)
    if isinstance(geometry, MultiPolygon):
        return tuple(part for part in geometry.geoms if not part.is_empty)
    return ()

def _clip_to_drivezone(geometry: BaseGeometry | None, drivezone_union: BaseGeometry | None) -> BaseGeometry | None:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return None
    if drivezone_union is None or drivezone_union.is_empty:
        return normalized
    return _normalize_geometry(normalized.intersection(drivezone_union))

def _geometry_summary(geometry: BaseGeometry | None) -> dict[str, Any]:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return {
            "present": False,
            "geometry_type": "",
            "area_m2": 0.0,
            "length_m": 0.0,
        }
    return {
        "present": True,
        "geometry_type": str(normalized.geom_type),
        "area_m2": float(getattr(normalized, "area", 0.0) or 0.0),
        "length_m": float(getattr(normalized, "length", 0.0) or 0.0),
    }


def _required_rcsd_anchor_point(unit_result: T04EventUnitResult) -> Point | None:
    for geometry in (
        getattr(unit_result, "required_rcsd_node_geometry", None),
        getattr(unit_result, "primary_main_rc_node_geometry", None),
        getattr(unit_result, "positive_rcsd_node_geometry", None),
    ):
        point = _as_point(geometry)
        if point is not None:
            return point
    return None


def _buffered_patch(
    geometry: BaseGeometry | None,
    *,
    radius_m: float,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    point = _as_point(geometry)
    if point is None:
        return None
    return _clip_to_drivezone(point.buffer(radius_m), drivezone_union)

def _surface_scenario_doc_for_unit(unit_result: T04EventUnitResult) -> tuple[dict[str, Any], bool]:
    surface_scenario_doc = getattr(unit_result, "surface_scenario_doc", None)
    if callable(surface_scenario_doc):
        return (dict(surface_scenario_doc()), False)
    scenario = classify_surface_scenario(
        evidence_source=getattr(unit_result, "evidence_source", ""),
        selected_evidence_summary=getattr(unit_result, "selected_evidence_summary", None),
        rcsd_selection_mode=getattr(unit_result, "rcsd_selection_mode", ""),
        required_rcsd_node=getattr(unit_result, "required_rcsd_node", None),
        first_hit_rcsdroad_ids=getattr(unit_result, "first_hit_rcsdroad_ids", None),
        selected_rcsdroad_ids=getattr(unit_result, "selected_rcsdroad_ids", None),
        positive_rcsd_audit=getattr(unit_result, "positive_rcsd_audit", None),
        fact_reference_point_present=getattr(unit_result, "fact_reference_point", None) is not None,
    )
    return (scenario.to_doc(), True)

def _step5_surface_window_config(unit_result: T04EventUnitResult) -> Step5SurfaceWindowConfig:
    scenario_doc, missing = _surface_scenario_doc_for_unit(unit_result)
    return derive_step5_surface_window_config(
        scenario_doc,
        surface_scenario_missing=missing,
    )

def _section_reference_anchor_point(
    unit_result: T04EventUnitResult,
    config: Step5SurfaceWindowConfig | None = None,
) -> Point | None:
    config = config or _step5_surface_window_config(unit_result)
    if config.reference_point_present:
        point = _as_point(getattr(unit_result, "fact_reference_point", None))
        if point is not None:
            return point
    if config.section_reference_source in {SECTION_REFERENCE_RCSD, SECTION_REFERENCE_POINT_AND_RCSD}:
        for geometry in (
            getattr(unit_result, "required_rcsd_node_geometry", None),
            getattr(unit_result, "positive_rcsd_node_geometry", None),
            getattr(unit_result, "primary_main_rc_node_geometry", None),
            getattr(unit_result, "local_rcsd_unit_geometry", None),
        ):
            point = _as_point(geometry)
            if point is not None:
                return point
    if config.section_reference_source == SECTION_REFERENCE_SWSD:
        unit_context = getattr(unit_result, "unit_context", None)
        representative_node = getattr(unit_context, "representative_node", None)
        for geometry in (
            getattr(unit_result, "review_materialized_point", None),
            getattr(unit_result, "fact_reference_point", None),
            getattr(representative_node, "geometry", None),
        ):
            point = _as_point(geometry)
            if point is not None:
                return point
    if config.section_reference_source == SECTION_REFERENCE_POINT:
        return _as_point(getattr(unit_result, "fact_reference_point", None))
    if config.surface_scenario_missing:
        return _as_point(getattr(unit_result, "fact_reference_point", None))
    return None

def _section_reference_seed_point(
    unit_result: T04EventUnitResult,
    config: Step5SurfaceWindowConfig,
) -> Point | None:
    if config.reference_point_present:
        return None
    for geometry in (
        getattr(unit_result, "review_materialized_point", None),
        getattr(unit_result, "fact_reference_point", None),
        _section_reference_anchor_point(unit_result, config),
    ):
        point = _as_point(geometry)
        if point is not None:
            return point
    return None

def _unit_axis_origin_point(unit_result: T04EventUnitResult) -> Point | None:
    bridge = unit_result.interpretation.legacy_step5_bridge
    bridge_origin = _as_point(bridge.event_origin_point)
    if bridge_origin is not None:
        return bridge_origin
    section_anchor = _section_reference_anchor_point(unit_result)
    if section_anchor is not None:
        return section_anchor
    return _as_point(unit_result.fact_reference_point)

def _road_buffer_union(
    roads: Sequence[ParsedRoad],
    *,
    buffer_m: float,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    geometries: list[BaseGeometry] = []
    for road in roads:
        geometry = getattr(road, "geometry", None)
        if geometry is None or geometry.is_empty:
            continue
        geometries.append(geometry.buffer(buffer_m, cap_style=2, join_style=2))
    return _clip_to_drivezone(_union_geometry(geometries), drivezone_union)

def _loaded_feature_union(features: Sequence[Any]) -> BaseGeometry | None:
    return _union_geometry(getattr(feature, "geometry", None) for feature in features)

def _divstrip_void_mask(
    case_result: T04CaseResult,
    *,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    void_geometries: list[BaseGeometry] = []
    for feature in case_result.case_bundle.divstrip_features:
        geometry = _normalize_geometry(getattr(feature, "geometry", None))
        for polygon in _iter_polygon_parts(geometry):
            for ring in polygon.interiors:
                void_geometries.append(Polygon(ring).buffer(STEP5_NEGATIVE_MASK_BUFFER_M))
    return _clip_to_drivezone(_union_geometry(void_geometries), drivezone_union)

def _normalize_vector(vector: tuple[float, float] | None) -> tuple[float, float] | None:
    if vector is None:
        return None
    vx = float(vector[0])
    vy = float(vector[1])
    length = (vx * vx + vy * vy) ** 0.5
    if length <= 1e-6:
        return None
    return (vx / length, vy / length)

def _vector_from_line(line: BaseGeometry | None) -> tuple[float, float] | None:
    geometry = getattr(line, "geometry", line)
    if geometry is None or geometry.is_empty:
        return None
    coords = list(getattr(geometry, "coords", []))
    if len(coords) < 2:
        return None
    start_x, start_y = coords[0]
    end_x, end_y = coords[-1]
    return _normalize_vector((float(end_x) - float(start_x), float(end_y) - float(start_y)))

def _vector_from_roads(roads: Sequence[ParsedRoad], origin_point: Point | None) -> tuple[float, float] | None:
    for road in roads:
        geometry = getattr(road, "geometry", None)
        if geometry is None or geometry.is_empty:
            continue
        coords = list(getattr(geometry, "coords", []))
        if len(coords) < 2:
            continue
        start = Point(coords[0])
        end = Point(coords[-1])
        if origin_point is not None and start.distance(origin_point) > end.distance(origin_point):
            coords = list(reversed(coords))
        start_x, start_y = coords[0]
        end_x, end_y = coords[-1]
        vector = _normalize_vector((float(end_x) - float(start_x), float(end_y) - float(start_y)))
        if vector is not None:
            return vector
    return None

def _event_axis_vector(unit_result: T04EventUnitResult) -> tuple[float, float] | None:
    bridge = unit_result.interpretation.legacy_step5_bridge
    vector = _normalize_vector(bridge.event_axis_unit_vector)
    if vector is not None:
        return vector
    vector = _vector_from_line(bridge.event_axis_centerline)
    if vector is not None:
        return vector
    return _vector_from_roads(
        tuple(bridge.selected_event_roads) or tuple(bridge.selected_roads),
        _unit_axis_origin_point(unit_result),
    )

def _line_geometry(geometry: BaseGeometry | None) -> LineString | None:
    normalized = _normalize_geometry(getattr(geometry, "geometry", geometry))
    if normalized is None:
        return None
    if isinstance(normalized, LineString):
        return normalized if normalized.length > 1e-6 else None
    if isinstance(normalized, MultiLineString):
        parts = [part for part in normalized.geoms if isinstance(part, LineString) and part.length > 1e-6]
        if not parts:
            return None
        return max(parts, key=lambda part: float(part.length))
    return None

def _ordered_line_by_origin(line: LineString | None, origin_point: Point | None) -> LineString | None:
    if line is None or origin_point is None:
        return line
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    start = Point(coords[0])
    end = Point(coords[-1])
    if start.distance(origin_point) <= end.distance(origin_point):
        return line
    return LineString(list(reversed(coords)))

def _ordered_line_by_semantic_anchors(
    line: LineString | None,
    *,
    start_point: Point,
    end_point: Point,
) -> LineString | None:
    if line is None:
        return None
    if float(line.project(start_point)) <= float(line.project(end_point)):
        return line
    return LineString(list(reversed(line.coords)))

def _semantic_anchor_axis_line(start_point: Point, end_point: Point) -> LineString | None:
    if start_point.distance(end_point) <= 1e-6:
        return None
    return LineString(
        [
            (float(start_point.x), float(start_point.y)),
            (float(end_point.x), float(end_point.y)),
        ]
    )

def _axis_line_supports_semantic_anchors(
    line: LineString,
    *,
    start_point: Point,
    end_point: Point,
) -> bool:
    if line.distance(start_point) > STEP5_TERMINAL_AXIS_ANCHOR_TOLERANCE_M:
        return False
    if line.distance(end_point) > STEP5_TERMINAL_AXIS_ANCHOR_TOLERANCE_M:
        return False
    projected_span = abs(float(line.project(end_point)) - float(line.project(start_point)))
    if projected_span <= STEP5_TERMINAL_MIN_ANCHOR_SPAN_M and start_point.distance(end_point) > STEP5_TERMINAL_MIN_ANCHOR_SPAN_M:
        return False
    return True

def _event_axis_line(unit_result: T04EventUnitResult) -> LineString | None:
    bridge = unit_result.interpretation.legacy_step5_bridge
    origin_point = _unit_axis_origin_point(unit_result)
    axis_line = _ordered_line_by_origin(_line_geometry(bridge.event_axis_centerline), origin_point)
    if axis_line is not None:
        return axis_line
    road_candidates = tuple(bridge.selected_event_roads) or tuple(bridge.selected_roads)
    candidate_lines = [
        _ordered_line_by_origin(_line_geometry(getattr(road, "geometry", None)), origin_point)
        for road in road_candidates
    ]
    candidate_lines = [line for line in candidate_lines if line is not None]
    if not candidate_lines:
        return None
    return max(candidate_lines, key=lambda line: float(line.length))

def _terminal_cut_semantic_anchors(unit_result: T04EventUnitResult) -> tuple[Point | None, Point | None]:
    config = _step5_surface_window_config(unit_result)
    reference_point = (
        _as_point(unit_result.fact_reference_point)
        if config.reference_point_present or config.surface_scenario_missing
        else _section_reference_seed_point(unit_result, config)
    )
    rcsd_point = _required_rcsd_anchor_point(unit_result)
    if reference_point is None or rcsd_point is None:
        return (None, None)
    kind_2 = unit_result.interpretation.kind_resolution.operational_kind_2
    if kind_2 == 16:
        return (rcsd_point, reference_point)
    return (reference_point, rcsd_point)

def _terminal_semantic_axis_line(unit_result: T04EventUnitResult) -> LineString | None:
    semantic_start_point, semantic_end_point = _terminal_cut_semantic_anchors(unit_result)
    if semantic_start_point is None or semantic_end_point is None:
        return None
    axis_line = _ordered_line_by_semantic_anchors(
        _event_axis_line(unit_result),
        start_point=semantic_start_point,
        end_point=semantic_end_point,
    )
    if axis_line is not None and _axis_line_supports_semantic_anchors(
        axis_line,
        start_point=semantic_start_point,
        end_point=semantic_end_point,
    ):
        return axis_line
    return _semantic_anchor_axis_line(semantic_start_point, semantic_end_point)

def _line_point_and_tangent(
    line: LineString,
    *,
    distance_m: float,
) -> tuple[Point | None, tuple[float, float] | None]:
    coords = list(line.coords)
    if len(coords) < 2:
        return (None, None)
    total_length = float(line.length)
    distance = float(distance_m)
    first_tangent = _normalize_vector(
        (float(coords[1][0]) - float(coords[0][0]), float(coords[1][1]) - float(coords[0][1]))
    )
    last_tangent = _normalize_vector(
        (
            float(coords[-1][0]) - float(coords[-2][0]),
            float(coords[-1][1]) - float(coords[-2][1]),
        )
    )
    if distance < 0.0:
        if first_tangent is None:
            return (None, None)
        point = Point(
            float(coords[0][0]) + float(first_tangent[0]) * distance,
            float(coords[0][1]) + float(first_tangent[1]) * distance,
        )
        return (point, first_tangent)
    if distance > total_length:
        if last_tangent is None:
            return (None, None)
        overflow = distance - total_length
        point = Point(
            float(coords[-1][0]) + float(last_tangent[0]) * overflow,
            float(coords[-1][1]) + float(last_tangent[1]) * overflow,
        )
        return (point, last_tangent)
    clamped_distance = min(max(distance, 0.0), total_length)
    if clamped_distance <= 1e-6:
        tangent = _normalize_vector(
            (float(coords[1][0]) - float(coords[0][0]), float(coords[1][1]) - float(coords[0][1]))
        )
        return (Point(coords[0]), tangent)
    if clamped_distance >= total_length - 1e-6:
        tangent = _normalize_vector(
            (
                float(coords[-1][0]) - float(coords[-2][0]),
                float(coords[-1][1]) - float(coords[-2][1]),
            )
        )
        return (Point(coords[-1]), tangent)
    travelled = 0.0
    for start_coord, end_coord in zip(coords[:-1], coords[1:]):
        segment = LineString([start_coord, end_coord])
        segment_length = float(segment.length)
        if segment_length <= 1e-9:
            continue
        if travelled + segment_length >= clamped_distance - 1e-9:
            tangent = _normalize_vector(
                (float(end_coord[0]) - float(start_coord[0]), float(end_coord[1]) - float(start_coord[1]))
            )
            return (Point(line.interpolate(clamped_distance)), tangent)
        travelled += segment_length
    tangent = _normalize_vector(
        (
            float(coords[-1][0]) - float(coords[-2][0]),
            float(coords[-1][1]) - float(coords[-2][1]),
        )
    )
    return (Point(line.interpolate(clamped_distance)), tangent)

def _line_window_centerline(
    line: LineString,
    *,
    start_distance_m: float,
    end_distance_m: float,
) -> LineString | None:
    start_distance = float(start_distance_m)
    end_distance = float(end_distance_m)
    if end_distance < start_distance:
        start_distance, end_distance = end_distance, start_distance
    if abs(end_distance - start_distance) <= 1e-6:
        return None
    start_point, _start_tangent = _line_point_and_tangent(line, distance_m=start_distance)
    end_point, _end_tangent = _line_point_and_tangent(line, distance_m=end_distance)
    if start_point is None or end_point is None:
        return None

    coords: list[tuple[float, float]] = [(float(start_point.x), float(start_point.y))]
    for coord in line.coords:
        point = Point(coord)
        projected = float(line.project(point))
        if start_distance + 1e-6 < projected < end_distance - 1e-6:
            coords.append((float(point.x), float(point.y)))
    coords.append((float(end_point.x), float(end_point.y)))

    deduped: list[tuple[float, float]] = []
    for coord in coords:
        if deduped and abs(deduped[-1][0] - coord[0]) <= 1e-6 and abs(deduped[-1][1] - coord[1]) <= 1e-6:
            continue
        deduped.append(coord)
    if len(deduped) < 2:
        return None
    return LineString(deduped)

def _terminal_window_half_width(drivezone_union: BaseGeometry | None) -> float:
    if drivezone_union is None or drivezone_union.is_empty:
        return STEP5_TERMINAL_WINDOW_FALLBACK_HALF_WIDTH_M
    min_x, min_y, max_x, max_y = drivezone_union.bounds
    diagonal = ((float(max_x) - float(min_x)) ** 2 + (float(max_y) - float(min_y)) ** 2) ** 0.5
    return max(
        diagonal + STEP5_TERMINAL_CUT_WINDOW_MARGIN_M,
        STEP5_TERMINAL_WINDOW_FALLBACK_HALF_WIDTH_M,
    )

def _terminal_axis_window_centerline(unit_result: T04EventUnitResult) -> LineString | None:
    axis_line = _terminal_semantic_axis_line(unit_result)
    semantic_start_point, semantic_end_point = _terminal_cut_semantic_anchors(unit_result)
    if axis_line is None or semantic_start_point is None or semantic_end_point is None:
        return None
    start_offset = float(axis_line.project(semantic_start_point)) - STEP5_TERMINAL_CUT_WINDOW_MARGIN_M
    end_offset = float(axis_line.project(semantic_end_point)) + STEP5_TERMINAL_CUT_WINDOW_MARGIN_M
    return _line_window_centerline(
        axis_line,
        start_distance_m=start_offset,
        end_distance_m=end_offset,
    )
