from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Iterable, Mapping, Sequence

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from ._rcsd_selection_support import _as_point, _normalize_geometry, _union_geometry
from ._runtime_types_io import ParsedRoad
from .case_models import T04CaseResult, T04EventUnitResult
from .surface_scenario import (
    SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
    SCENARIO_NO_SURFACE_REFERENCE,
    SECTION_REFERENCE_NONE,
    SECTION_REFERENCE_POINT,
    SECTION_REFERENCE_POINT_AND_RCSD,
    SECTION_REFERENCE_RCSD,
    SECTION_REFERENCE_SWSD,
    SURFACE_MODE_NO_SURFACE,
    SURFACE_MODE_RCSD_WINDOW,
    SURFACE_MODE_SWSD_WINDOW,
    SURFACE_MODE_SWSD_WITH_RCSDROAD,
    classify_surface_scenario,
)


STEP5_POINT_PATCH_RADIUS_M = 2.5
STEP5_REQUIRED_NODE_PATCH_RADIUS_M = 2.5
STEP5_B_NODE_TARGET_PATCH_RADIUS_M = 2.5
STEP5_FALLBACK_STRIP_HALF_LENGTH_M = 20.0
STEP5_FALLBACK_STRIP_HALF_WIDTH_M = 3.0
STEP5_SUPPORT_ROAD_BUFFER_M = 6.0
STEP5_BRIDGE_HALF_WIDTH_M = 3.0
STEP5_NEGATIVE_MASK_BUFFER_M = 1.0
STEP5_TERMINAL_CUT_HALF_WIDTH_M = 12.0
STEP5_TERMINAL_CUT_WINDOW_MARGIN_M = 20.0
STEP5_SUPPORT_GRAPH_PAD_M = 2.0
STEP5_TERMINAL_WINDOW_FALLBACK_HALF_WIDTH_M = 240.0
STEP5_TERMINAL_AXIS_ANCHOR_TOLERANCE_M = 15.0
STEP5_TERMINAL_MIN_ANCHOR_SPAN_M = 1.0
STEP5_JUNCTION_WINDOW_HALF_LENGTH_M = 20.0
STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M = 20.0
STEP5_FULL_FILL_BRIDGE_MAX_DISTANCE_M = 8.0
STEP5_FULL_FILL_BRIDGE_MAX_EXISTING_OVERLAP_M2 = 25.0
STEP5_SURFACE_SECTION_FORWARD_M = 20.0
STEP5_SURFACE_SECTION_BACKWARD_M = 20.0
STEP5_SURFACE_LATERAL_LIMIT_M = 20.0
STEP5_JUNCTION_WINDOW_EVIDENCE_SOURCES = {
    "swsd_junction_window",
    "rcsd_junction_window",
}


@dataclass(frozen=True)
class Step5SurfaceWindowConfig:
    surface_scenario_type: str
    section_reference_source: str
    surface_generation_mode: str
    reference_point_present: bool
    has_main_evidence: bool
    surface_scenario_missing: bool
    support_domain_from_reference_kind: str
    fallback_rcsdroad_ids: tuple[str, ...]
    fallback_local_window_m: float | None
    fallback_rcsdroad_localized: bool
    no_virtual_reference_point_guard: bool
    surface_section_forward_m: float = STEP5_SURFACE_SECTION_FORWARD_M
    surface_section_backward_m: float = STEP5_SURFACE_SECTION_BACKWARD_M
    surface_lateral_limit_m: float = STEP5_SURFACE_LATERAL_LIMIT_M

    @property
    def entity_support_enabled(self) -> bool:
        return (
            self.surface_scenario_type != SCENARIO_NO_SURFACE_REFERENCE
            and self.section_reference_source != SECTION_REFERENCE_NONE
            and self.surface_generation_mode != SURFACE_MODE_NO_SURFACE
        )

    def to_doc(self) -> dict[str, Any]:
        return {
            "surface_scenario_type": self.surface_scenario_type,
            "section_reference_source": self.section_reference_source,
            "surface_generation_mode": self.surface_generation_mode,
            "reference_point_present": self.reference_point_present,
            "has_main_evidence": self.has_main_evidence,
            "surface_scenario_missing": self.surface_scenario_missing,
            "support_domain_from_reference_kind": self.support_domain_from_reference_kind,
            "fallback_rcsdroad_ids": list(self.fallback_rcsdroad_ids),
            "fallback_local_window_m": self.fallback_local_window_m,
            "fallback_rcsdroad_localized": self.fallback_rcsdroad_localized,
            "no_virtual_reference_point_guard": self.no_virtual_reference_point_guard,
            "surface_section_forward_m": self.surface_section_forward_m,
            "surface_section_backward_m": self.surface_section_backward_m,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
        }


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _clean_ids(values: Sequence[Any] | None) -> tuple[str, ...]:
    if not values:
        return ()
    ids: list[str] = []
    for value in values:
        text = _clean_text(value)
        if text and text not in ids:
            ids.append(text)
    return tuple(ids)


def derive_step5_surface_window_config(
    surface_scenario: Mapping[str, Any] | None,
    *,
    surface_scenario_missing: bool = False,
) -> Step5SurfaceWindowConfig:
    scenario_doc = dict(surface_scenario or {})
    scenario_type = _clean_text(
        scenario_doc.get("surface_scenario_type"),
        SCENARIO_NO_SURFACE_REFERENCE,
    )
    section_reference_source = _clean_text(
        scenario_doc.get("section_reference_source"),
        SECTION_REFERENCE_NONE,
    )
    surface_generation_mode = _clean_text(
        scenario_doc.get("surface_generation_mode"),
        SURFACE_MODE_NO_SURFACE,
    )
    has_main_evidence = bool(scenario_doc.get("has_main_evidence", False))
    reference_point_present = bool(scenario_doc.get("reference_point_present", False))
    fallback_rcsdroad_ids = _clean_ids(scenario_doc.get("fallback_rcsdroad_ids"))
    no_virtual_reference_point_guard = not (reference_point_present and not has_main_evidence)
    fallback_rcsdroad_localized = (
        bool(fallback_rcsdroad_ids)
        and scenario_type != SCENARIO_NO_SURFACE_REFERENCE
        and surface_generation_mode != SURFACE_MODE_NO_SURFACE
    )
    return Step5SurfaceWindowConfig(
        surface_scenario_type=scenario_type,
        section_reference_source=section_reference_source,
        surface_generation_mode=surface_generation_mode,
        reference_point_present=reference_point_present,
        has_main_evidence=has_main_evidence,
        surface_scenario_missing=surface_scenario_missing,
        support_domain_from_reference_kind=section_reference_source,
        fallback_rcsdroad_ids=fallback_rcsdroad_ids,
        fallback_local_window_m=STEP5_JUNCTION_WINDOW_HALF_LENGTH_M if fallback_rcsdroad_ids else None,
        fallback_rcsdroad_localized=fallback_rcsdroad_localized,
        no_virtual_reference_point_guard=no_virtual_reference_point_guard,
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
    if not config.reference_point_present and not config.surface_scenario_missing:
        return (None, None)
    reference_point = _as_point(unit_result.fact_reference_point)
    rcsd_point = _as_point(unit_result.required_rcsd_node_geometry)
    if rcsd_point is None:
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


def _road_surface_fork_candidate_domain(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    if str(getattr(unit_result, "evidence_source", "") or "") != "road_surface_fork":
        return None
    if str(unit_result.positive_rcsd_consistency_level or "") != "A":
        return None
    surface_domain = _clip_to_drivezone(
        unit_result.selected_candidate_region_geometry,
        drivezone_union,
    )
    if surface_domain is None or surface_domain.is_empty:
        return None
    reference_point = _as_point(unit_result.fact_reference_point)
    required_node_point = _as_point(unit_result.required_rcsd_node_geometry)
    if reference_point is None or required_node_point is None:
        return None
    if not surface_domain.buffer(1e-6).covers(reference_point):
        return None
    if not surface_domain.buffer(1e-6).covers(required_node_point):
        return None
    window_centerline = _terminal_axis_window_centerline(unit_result)
    if window_centerline is None:
        return None
    window_domain = window_centerline.buffer(
        _terminal_window_half_width(drivezone_union),
        cap_style=2,
        join_style=2,
    )
    return _clip_to_drivezone(
        surface_domain.intersection(window_domain),
        drivezone_union,
    )


def _build_terminal_window_domain(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    window_centerline = _terminal_axis_window_centerline(unit_result)
    if window_centerline is None:
        return None
    window_domain = window_centerline.buffer(
        _terminal_window_half_width(drivezone_union),
        cap_style=2,
        join_style=2,
    )
    return _clip_to_drivezone(
        _union_geometry(
            [
                window_domain,
                _road_surface_fork_candidate_domain(
                    unit_result,
                    drivezone_union=drivezone_union,
                ),
            ]
        ),
        drivezone_union,
    )


def _build_terminal_support_corridor(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    window_centerline = _terminal_axis_window_centerline(unit_result)
    if window_centerline is None:
        return None
    return _clip_to_drivezone(
        window_centerline.buffer(
            STEP5_SUPPORT_ROAD_BUFFER_M,
            cap_style=2,
            join_style=2,
        ),
        drivezone_union,
    )


def _uses_junction_full_road_fill(unit_result: T04EventUnitResult) -> bool:
    config = _step5_surface_window_config(unit_result)
    if not config.reference_point_present and not config.surface_scenario_missing:
        return False
    source = str(unit_result.evidence_source or "")
    return bool(
        source in {"rcsd_anchored_reverse", "road_surface_fork", "multibranch_event"}
        and str(unit_result.required_rcsd_node or "").strip()
        and _as_point(unit_result.fact_reference_point) is not None
        and _as_point(unit_result.required_rcsd_node_geometry) is not None
    )


def _uses_junction_window(unit_result: T04EventUnitResult) -> bool:
    config = _step5_surface_window_config(unit_result)
    if config.surface_generation_mode in {
        SURFACE_MODE_RCSD_WINDOW,
        SURFACE_MODE_SWSD_WINDOW,
        SURFACE_MODE_SWSD_WITH_RCSDROAD,
    }:
        return True
    return str(unit_result.evidence_source or "") in STEP5_JUNCTION_WINDOW_EVIDENCE_SOURCES


def _junction_window_anchor_point(unit_result: T04EventUnitResult) -> Point | None:
    config = _step5_surface_window_config(unit_result)
    point = _section_reference_anchor_point(unit_result, config)
    if point is not None:
        return point
    source = str(unit_result.evidence_source or "")
    if source == "rcsd_junction_window":
        point = _as_point(unit_result.required_rcsd_node_geometry)
        if point is not None:
            return point
    point = _as_point(unit_result.fact_reference_point)
    if point is not None:
        return point
    representative = getattr(unit_result.unit_context.representative_node, "geometry", None)
    return _as_point(representative)


def _junction_window_axis_line(unit_result: T04EventUnitResult, anchor_point: Point) -> LineString | None:
    axis_line = None
    config = _step5_surface_window_config(unit_result)
    if (
        str(unit_result.evidence_source or "") == "rcsd_junction_window"
        or config.section_reference_source == SECTION_REFERENCE_RCSD
    ):
        axis_line = _ordered_line_by_origin(
            _line_geometry(unit_result.positive_rcsd_road_geometry)
            or _line_geometry(unit_result.local_rcsd_unit_geometry),
            anchor_point,
        )
    if axis_line is None:
        axis_line = _event_axis_line(unit_result)
    if axis_line is not None:
        return _ordered_line_by_origin(axis_line, anchor_point)
    axis_vector = _event_axis_vector(unit_result)
    if axis_vector is None:
        return None
    dx = float(axis_vector[0]) * STEP5_JUNCTION_WINDOW_HALF_LENGTH_M
    dy = float(axis_vector[1]) * STEP5_JUNCTION_WINDOW_HALF_LENGTH_M
    return LineString(
        [
            (float(anchor_point.x) - dx, float(anchor_point.y) - dy),
            (float(anchor_point.x) + dx, float(anchor_point.y) + dy),
        ]
    )


def _build_junction_window_domain(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    if not _uses_junction_window(unit_result):
        return None
    anchor_point = _junction_window_anchor_point(unit_result)
    if anchor_point is None:
        return None
    axis_line = _junction_window_axis_line(unit_result, anchor_point)
    if axis_line is None:
        return None
    anchor_s = float(axis_line.project(anchor_point))
    window_centerline = _line_window_centerline(
        axis_line,
        start_distance_m=anchor_s - STEP5_JUNCTION_WINDOW_HALF_LENGTH_M,
        end_distance_m=anchor_s + STEP5_JUNCTION_WINDOW_HALF_LENGTH_M,
    )
    if window_centerline is None:
        return None
    window_domain = window_centerline.buffer(
        STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M,
        cap_style=2,
        join_style=2,
    )
    return _clip_to_drivezone(window_domain, drivezone_union)


def _build_junction_full_road_fill_axis_band(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    if not _uses_junction_full_road_fill(unit_result):
        return None
    window_centerline = _terminal_axis_window_centerline(unit_result)
    if window_centerline is None:
        return None
    axis_band = window_centerline.buffer(
        STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M,
        cap_style=2,
        join_style=2,
    )
    return _clip_to_drivezone(axis_band, drivezone_union)


def _build_junction_full_road_fill_domain(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    junction_window_domain = _build_junction_window_domain(
        unit_result,
        drivezone_union=drivezone_union,
    )
    if junction_window_domain is not None and not junction_window_domain.is_empty:
        return junction_window_domain
    surface_domain = _road_surface_fork_candidate_domain(
        unit_result,
        drivezone_union=drivezone_union,
    )
    if surface_domain is not None and not surface_domain.is_empty:
        return surface_domain
    axis_band = _build_junction_full_road_fill_axis_band(
        unit_result,
        drivezone_union=drivezone_union,
    )
    if axis_band is None:
        return None
    return _clip_to_drivezone(axis_band, drivezone_union)


def _seed_connected_fill_domain(
    fill_domain: BaseGeometry | None,
    seed_geometries: Iterable[BaseGeometry | None],
) -> BaseGeometry | None:
    normalized = _normalize_geometry(fill_domain)
    if normalized is None:
        return None
    seed = _normalize_geometry(_union_geometry(seed_geometries))
    if seed is None:
        return normalized
    parts = list(_iter_polygon_parts(normalized))
    if not parts:
        return normalized
    connected = [
        part
        for part in parts
        if part.buffer(1e-6).intersects(seed)
    ]
    if not connected:
        connected = [min(parts, key=lambda part: float(part.distance(seed)))]
    return _normalize_geometry(_union_geometry(connected))


def _single_surface_component_domain(
    geometry: BaseGeometry | None,
    *,
    seed_geometries: Iterable[BaseGeometry | None],
    forbidden_geometry: BaseGeometry | None,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    normalized = _clip_to_drivezone(geometry, drivezone_union)
    if normalized is None:
        return None
    if forbidden_geometry is not None and not forbidden_geometry.is_empty:
        normalized = _clip_to_drivezone(
            normalized.difference(forbidden_geometry),
            drivezone_union,
        )
    if normalized is None:
        return None
    parts = list(_iter_polygon_parts(normalized))
    if not parts:
        return normalized
    seed = _normalize_geometry(_union_geometry(seed_geometries))
    if seed is None:
        return _normalize_geometry(max(parts, key=lambda part: float(part.area)))
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


def _build_fallback_support_strip(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    config = _step5_surface_window_config(unit_result)
    center_point = _section_reference_anchor_point(unit_result, config)
    axis_vector = _event_axis_vector(unit_result)
    if center_point is None or axis_vector is None:
        return None
    dx = float(axis_vector[0]) * STEP5_FALLBACK_STRIP_HALF_LENGTH_M
    dy = float(axis_vector[1]) * STEP5_FALLBACK_STRIP_HALF_LENGTH_M
    centerline = LineString(
        [
            (float(center_point.x) - dx, float(center_point.y) - dy),
            (float(center_point.x) + dx, float(center_point.y) + dy),
        ]
    )
    strip = centerline.buffer(
        STEP5_FALLBACK_STRIP_HALF_WIDTH_M,
        cap_style=2,
        join_style=2,
    )
    return _clip_to_drivezone(strip, drivezone_union)


def _should_build_fallback_support_strip(
    unit_result: T04EventUnitResult,
    *,
    config: Step5SurfaceWindowConfig,
    junction_window_requested: bool,
) -> bool:
    if not config.entity_support_enabled:
        return False
    if config.fallback_rcsdroad_ids:
        return True
    return bool(
        unit_result.evidence_source != "road_surface_fork"
        and not junction_window_requested
        and (
            unit_result.positive_rcsd_consistency_level == "C"
            or (
                unit_result.positive_rcsd_consistency_level == "B"
                and unit_result.required_rcsd_node in {None, ""}
            )
        )
    )


def _unique_roads(roads: Iterable[ParsedRoad]) -> tuple[ParsedRoad, ...]:
    deduped: dict[str, ParsedRoad] = {}
    for road in roads:
        road_id = str(getattr(road, "road_id", "") or "").strip()
        if not road_id or road_id in deduped:
            continue
        deduped[road_id] = road
    return tuple(deduped.values())


def _road_endpoint_node_ids(road: ParsedRoad) -> tuple[str, str]:
    return (
        str(getattr(road, "snodeid", "") or "").strip(),
        str(getattr(road, "enodeid", "") or "").strip(),
    )


def _road_lookup(roads: Iterable[ParsedRoad]) -> dict[str, ParsedRoad]:
    return {
        road_id: road
        for road in roads
        if (road_id := str(getattr(road, "road_id", "") or "").strip())
    }


def _roads_by_node(roads: Iterable[ParsedRoad]) -> dict[str, set[str]]:
    mapping: dict[str, set[str]] = {}
    for road in roads:
        road_id = str(getattr(road, "road_id", "") or "").strip()
        if not road_id:
            continue
        for node_id in _road_endpoint_node_ids(road):
            if not node_id:
                continue
            mapping.setdefault(node_id, set()).add(road_id)
    return mapping


def _expanded_related_road_ids(
    *,
    seed_road_ids: Iterable[str],
    roads: Sequence[ParsedRoad],
    current_semantic_node_ids: Iterable[str],
) -> set[str]:
    roads_by_id = _road_lookup(roads)
    roads_by_node = _roads_by_node(roads)
    current_nodes = {str(node_id) for node_id in current_semantic_node_ids if str(node_id)}
    queue = [str(road_id) for road_id in seed_road_ids if str(road_id) in roads_by_id]
    related: set[str] = set()
    while queue:
        road_id = queue.pop(0)
        if road_id in related:
            continue
        road = roads_by_id.get(road_id)
        if road is None:
            continue
        related.add(road_id)
        for node_id in _road_endpoint_node_ids(road):
            if not node_id:
                continue
            incident_road_ids = roads_by_node.get(node_id, set())
            if node_id not in current_nodes and len(incident_road_ids) != 2:
                continue
            for next_road_id in sorted(incident_road_ids):
                if next_road_id not in related:
                    queue.append(next_road_id)
    return related


def _road_terminal_point_and_tangent(
    road: ParsedRoad,
    *,
    origin_point: Point | None,
) -> tuple[Point | None, tuple[float, float] | None]:
    geometry = getattr(road, "geometry", None)
    if geometry is None or geometry.is_empty:
        return (None, None)
    coords = list(getattr(geometry, "coords", []))
    if len(coords) < 2:
        return (None, None)
    start = Point(coords[0])
    end = Point(coords[-1])
    use_end = True
    if origin_point is not None:
        use_end = end.distance(origin_point) >= start.distance(origin_point)
    if use_end:
        terminal = end
        neighbor = Point(coords[-2])
    else:
        terminal = start
        neighbor = Point(coords[1])
    tangent = _normalize_vector((float(terminal.x) - float(neighbor.x), float(terminal.y) - float(neighbor.y)))
    return (terminal, tangent)


def _build_terminal_cut_constraints_from_road_terminals(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    bridge = unit_result.interpretation.legacy_step5_bridge
    origin_point = _as_point(bridge.event_origin_point) or _as_point(unit_result.fact_reference_point)
    roads = _unique_roads(tuple(bridge.selected_event_roads) or tuple(bridge.selected_roads))
    cut_lines: list[BaseGeometry] = []
    seen_keys: set[tuple[int, int, int, int]] = set()
    for road in roads:
        terminal_point, tangent = _road_terminal_point_and_tangent(road, origin_point=origin_point)
        if terminal_point is None or tangent is None:
            continue
        normal = (-float(tangent[1]), float(tangent[0]))
        dx = float(normal[0]) * STEP5_TERMINAL_CUT_HALF_WIDTH_M
        dy = float(normal[1]) * STEP5_TERMINAL_CUT_HALF_WIDTH_M
        line = LineString(
            [
                (float(terminal_point.x) - dx, float(terminal_point.y) - dy),
                (float(terminal_point.x) + dx, float(terminal_point.y) + dy),
            ]
        )
        clipped = _clip_to_drivezone(line, drivezone_union)
        if clipped is None or clipped.is_empty:
            continue
        key = tuple(int(round(value * 1000.0)) for value in clipped.bounds)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        cut_lines.append(clipped)
    return _normalize_geometry(_union_geometry(cut_lines))


def _build_terminal_cut_constraints(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    axis_line = _terminal_semantic_axis_line(unit_result)
    semantic_start_point, semantic_end_point = _terminal_cut_semantic_anchors(unit_result)
    if axis_line is None or semantic_start_point is None or semantic_end_point is None:
        return _build_terminal_cut_constraints_from_road_terminals(
            unit_result,
            drivezone_union=drivezone_union,
        )
    start_offset = float(axis_line.project(semantic_start_point)) - STEP5_TERMINAL_CUT_WINDOW_MARGIN_M
    end_offset = float(axis_line.project(semantic_end_point)) + STEP5_TERMINAL_CUT_WINDOW_MARGIN_M
    half_width = STEP5_TERMINAL_CUT_HALF_WIDTH_M
    cut_lines: list[BaseGeometry] = []
    seen_keys: set[tuple[int, int, int, int]] = set()
    for offset in (start_offset, end_offset):
        cut_point, tangent = _line_point_and_tangent(axis_line, distance_m=offset)
        if cut_point is None or tangent is None:
            continue
        normal = (-float(tangent[1]), float(tangent[0]))
        dx = float(normal[0]) * half_width
        dy = float(normal[1]) * half_width
        line = LineString(
            [
                (float(cut_point.x) - dx, float(cut_point.y) - dy),
                (float(cut_point.x) + dx, float(cut_point.y) + dy),
            ]
        )
        clipped = _clip_to_drivezone(line, drivezone_union)
        if clipped is None or clipped.is_empty:
            continue
        key = tuple(int(round(value * 1000.0)) for value in clipped.bounds)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        cut_lines.append(clipped)
    if cut_lines:
        return _normalize_geometry(_union_geometry(cut_lines))
    return _build_terminal_cut_constraints_from_road_terminals(
        unit_result,
        drivezone_union=drivezone_union,
    )


def _iter_line_parts(geometry: BaseGeometry | None) -> Iterable[LineString]:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return ()
    if isinstance(normalized, LineString):
        return (normalized,)
    if isinstance(normalized, MultiLineString):
        return tuple(part for part in normalized.geoms if isinstance(part, LineString) and not part.is_empty)
    return ()


def _terminal_cut_group_key(unit_result: T04EventUnitResult) -> str:
    bridge = unit_result.interpretation.legacy_step5_bridge
    branch_id = str(getattr(bridge, "event_axis_branch_id", "") or "").strip()
    if branch_id:
        return f"axis_branch:{branch_id}"
    axis_vector = _event_axis_vector(unit_result)
    if axis_vector is not None:
        vx, vy = float(axis_vector[0]), float(axis_vector[1])
        if vx < 0.0 or (abs(vx) <= 1e-6 and vy < 0.0):
            vx, vy = -vx, -vy
        return f"axis_vector:{vx:.2f}:{vy:.2f}"
    return f"event_unit:{unit_result.spec.event_unit_id}"


def _filter_internal_case_cut_lines(
    cut_lines: Sequence[BaseGeometry],
    *,
    unit_results: Sequence[T04Step5UnitResult],
) -> tuple[BaseGeometry, ...]:
    if len(cut_lines) <= 2 or len(unit_results) <= 1:
        return tuple(cut_lines)
    full_fill_geometry = _normalize_geometry(
        _union_geometry(unit.junction_full_road_fill_domain for unit in unit_results)
    )
    if full_fill_geometry is None or full_fill_geometry.is_empty:
        return tuple(cut_lines)
    kept: list[BaseGeometry] = []
    for cut_line in cut_lines:
        cut_length = float(getattr(cut_line, "length", 0.0) or 0.0)
        if cut_length <= 1e-6:
            continue
        inside_length = float(cut_line.intersection(full_fill_geometry).length)
        if inside_length / cut_length >= 0.8:
            continue
        kept.append(cut_line)
    if len(kept) < 2:
        return tuple(cut_lines)
    return tuple(kept)


def _build_case_terminal_cut_constraints(
    case_result: T04CaseResult,
    *,
    unit_results: Sequence[T04Step5UnitResult],
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    step5_unit_by_id = {unit.event_unit_id: unit for unit in unit_results}
    grouped_entries: dict[str, dict[str, Any]] = {}
    for event_unit in case_result.event_units:
        step5_unit = step5_unit_by_id.get(event_unit.spec.event_unit_id)
        if step5_unit is None:
            continue
        cut_lines = tuple(_iter_line_parts(step5_unit.unit_terminal_cut_constraints))
        if not cut_lines:
            continue
        group_key = _terminal_cut_group_key(event_unit)
        group_entry = grouped_entries.setdefault(group_key, {"axis_line": None, "cuts": []})
        axis_line = _event_axis_line(event_unit)
        if axis_line is not None:
            existing_axis = group_entry.get("axis_line")
            if existing_axis is None or float(axis_line.length) > float(existing_axis.length):
                group_entry["axis_line"] = axis_line
        for cut_line in cut_lines:
            group_entry["cuts"].append(cut_line)

    selected_lines: list[BaseGeometry] = []
    seen_keys: set[tuple[int, int, int, int]] = set()
    for group_entry in grouped_entries.values():
        cut_lines = list(group_entry.get("cuts", []))
        if not cut_lines:
            continue
        axis_line = group_entry.get("axis_line")
        if axis_line is not None and len(cut_lines) > 2:
            cut_lines.sort(key=lambda line: float(axis_line.project(line.centroid)))
            candidate_lines = [cut_lines[0], cut_lines[-1]]
        else:
            candidate_lines = cut_lines
        for cut_line in candidate_lines:
            clipped = _clip_to_drivezone(cut_line, drivezone_union)
            if clipped is None or clipped.is_empty:
                continue
            key = tuple(int(round(value * 1000.0)) for value in clipped.bounds)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            selected_lines.append(clipped)

    selected_lines = list(
        _filter_internal_case_cut_lines(
            selected_lines,
            unit_results=unit_results,
        )
    )
    if selected_lines:
        return _normalize_geometry(_union_geometry(selected_lines))
    return _clip_to_drivezone(
        _union_geometry(unit.unit_terminal_cut_constraints for unit in unit_results),
        drivezone_union,
    )


def _geometry_or_empty_members(geometries: Iterable[BaseGeometry | None]) -> tuple[BaseGeometry, ...]:
    return tuple(
        geometry
        for geometry in (_normalize_geometry(item) for item in geometries)
        if geometry is not None
    )


def _nearest_bridge_patch(
    left: BaseGeometry,
    right: BaseGeometry,
    *,
    support_graph_geometry: BaseGeometry | None,
    drivezone_union: BaseGeometry | None,
    half_width_m: float = STEP5_BRIDGE_HALF_WIDTH_M,
    support_graph_pad_m: float = STEP5_SUPPORT_GRAPH_PAD_M,
) -> BaseGeometry | None:
    try:
        left_point, right_point = nearest_points(left, right)
    except Exception:
        return None
    if left_point is None or right_point is None:
        return None
    if left_point.distance(right_point) <= 1e-6:
        bridge = left_point.buffer(float(half_width_m))
    else:
        bridge = LineString([left_point, right_point]).buffer(
            float(half_width_m),
            cap_style=2,
            join_style=2,
        )
    if support_graph_geometry is not None and not support_graph_geometry.is_empty:
        bridge = bridge.intersection(
            support_graph_geometry.buffer(float(support_graph_pad_m))
        )
    return _clip_to_drivezone(bridge, drivezone_union)


def _multi_unit_full_fill_bridge_geometries(
    unit_results: Sequence[T04Step5UnitResult],
    *,
    support_graph_geometry: BaseGeometry | None,
    drivezone_union: BaseGeometry | None,
) -> list[BaseGeometry]:
    full_fill_geometries = [
        unit.junction_full_road_fill_domain
        for unit in unit_results
        if unit.junction_full_road_fill_domain is not None
        and not unit.junction_full_road_fill_domain.is_empty
    ]
    if len(full_fill_geometries) <= 1:
        return []

    bridges: list[BaseGeometry] = []
    current_geometry = full_fill_geometries[0]
    remaining = list(full_fill_geometries[1:])
    while remaining:
        best_index = 0
        best_distance = float("inf")
        for index, candidate in enumerate(remaining):
            distance = float(current_geometry.distance(candidate))
            if distance < best_distance:
                best_distance = distance
                best_index = index
        candidate = remaining.pop(best_index)
        overlap_area = float(current_geometry.intersection(candidate).area)
        if (
            best_distance <= STEP5_FULL_FILL_BRIDGE_MAX_DISTANCE_M
            and overlap_area < STEP5_FULL_FILL_BRIDGE_MAX_EXISTING_OVERLAP_M2
        ):
            bridge_geometry = _nearest_bridge_patch(
                current_geometry,
                candidate,
                support_graph_geometry=support_graph_geometry,
                drivezone_union=drivezone_union,
                half_width_m=STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M,
                support_graph_pad_m=STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M,
            )
            if bridge_geometry is not None and not bridge_geometry.is_empty:
                bridges.append(bridge_geometry)
        current_geometry = _clip_to_drivezone(
            _union_geometry([current_geometry, candidate, *bridges]),
            drivezone_union,
        ) or current_geometry
    return bridges


@dataclass(frozen=True)
class T04Step5UnitResult:
    event_unit_id: str
    event_type: str
    review_state: str
    positive_rcsd_consistency_level: str
    positive_rcsd_support_level: str
    required_rcsd_node: str | None
    legacy_step5_ready: bool
    legacy_step5_reasons: tuple[str, ...]
    localized_evidence_core_geometry: BaseGeometry | None
    fact_reference_patch_geometry: BaseGeometry | None
    required_rcsd_node_patch_geometry: BaseGeometry | None
    target_b_node_patch_geometry: BaseGeometry | None
    fallback_support_strip_geometry: BaseGeometry | None
    unit_must_cover_domain: BaseGeometry | None
    unit_allowed_growth_domain: BaseGeometry | None
    unit_forbidden_domain: BaseGeometry | None
    unit_terminal_cut_constraints: BaseGeometry | None
    unit_terminal_window_domain: BaseGeometry | None
    terminal_support_corridor_geometry: BaseGeometry | None
    axis_lateral_band_geometry: BaseGeometry | None = None
    junction_full_road_fill_domain: BaseGeometry | None = None
    surface_fill_mode: str = "standard"
    surface_fill_axis_half_width_m: float | None = None
    single_component_surface_seed: bool = False
    support_road_ids: tuple[str, ...] = ()
    support_event_road_ids: tuple[str, ...] = ()
    positive_rcsd_road_ids: tuple[str, ...] = ()
    positive_rcsd_node_ids: tuple[str, ...] = ()
    must_cover_components: dict[str, bool] = field(default_factory=dict)
    surface_scenario_type: str = SCENARIO_NO_SURFACE_REFERENCE
    section_reference_source: str = SECTION_REFERENCE_NONE
    surface_generation_mode: str = SURFACE_MODE_NO_SURFACE
    reference_point_present: bool = False
    surface_scenario_missing: bool = False
    support_domain_from_reference_kind: str = SECTION_REFERENCE_NONE
    surface_section_forward_m: float = STEP5_SURFACE_SECTION_FORWARD_M
    surface_section_backward_m: float = STEP5_SURFACE_SECTION_BACKWARD_M
    surface_lateral_limit_m: float = STEP5_SURFACE_LATERAL_LIMIT_M
    fallback_rcsdroad_ids: tuple[str, ...] = ()
    fallback_local_window_m: float | None = None
    fallback_support_strip_area_m2: float = 0.0
    fallback_rcsdroad_localized: bool = False
    no_virtual_reference_point_guard: bool = True
    divstrip_negative_mask_present: bool = False
    forbidden_domain_kept: bool = False
    swsd_only_entity_support_domain: bool = False

    def to_status_doc(self) -> dict[str, Any]:
        return {
            "event_unit_id": self.event_unit_id,
            "event_type": self.event_type,
            "review_state": self.review_state,
            "positive_rcsd_support_level": self.positive_rcsd_support_level,
            "positive_rcsd_consistency_level": self.positive_rcsd_consistency_level,
            "required_rcsd_node": self.required_rcsd_node,
            "legacy_step5_readiness": {
                "ready": self.legacy_step5_ready,
                "reasons": list(self.legacy_step5_reasons),
            },
            "surface_scenario_type": self.surface_scenario_type,
            "section_reference_source": self.section_reference_source,
            "surface_generation_mode": self.surface_generation_mode,
            "reference_point_present": self.reference_point_present,
            "surface_scenario_missing": self.surface_scenario_missing,
            "surface_section_forward_m": self.surface_section_forward_m,
            "surface_section_backward_m": self.surface_section_backward_m,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
            "support_domain_from_reference_kind": self.support_domain_from_reference_kind,
            "fallback_rcsdroad_ids": list(self.fallback_rcsdroad_ids),
            "fallback_local_window_m": self.fallback_local_window_m,
            "fallback_support_strip_area_m2": self.fallback_support_strip_area_m2,
            "fallback_rcsdroad_localized": self.fallback_rcsdroad_localized,
            "no_virtual_reference_point_guard": self.no_virtual_reference_point_guard,
            "divstrip_negative_mask_present": self.divstrip_negative_mask_present,
            "forbidden_domain_kept": self.forbidden_domain_kept,
            "swsd_only_entity_support_domain": self.swsd_only_entity_support_domain,
            "surface_fill_mode": self.surface_fill_mode,
            "surface_fill_axis_half_width_m": self.surface_fill_axis_half_width_m,
            "single_component_surface_seed": self.single_component_surface_seed,
            "must_cover_components": dict(self.must_cover_components),
            "unit_must_cover_domain": _geometry_summary(self.unit_must_cover_domain),
            "unit_allowed_growth_domain": _geometry_summary(self.unit_allowed_growth_domain),
            "unit_forbidden_domain": _geometry_summary(self.unit_forbidden_domain),
            "unit_terminal_cut_constraints": _geometry_summary(self.unit_terminal_cut_constraints),
            "unit_terminal_window_domain": _geometry_summary(self.unit_terminal_window_domain),
            "axis_lateral_band_geometry": _geometry_summary(self.axis_lateral_band_geometry),
            "junction_full_road_fill_domain": _geometry_summary(self.junction_full_road_fill_domain),
            "localized_evidence_core_geometry": _geometry_summary(self.localized_evidence_core_geometry),
            "fact_reference_patch_geometry": _geometry_summary(self.fact_reference_patch_geometry),
            "required_rcsd_node_patch_geometry": _geometry_summary(self.required_rcsd_node_patch_geometry),
            "target_b_node_patch_geometry": _geometry_summary(self.target_b_node_patch_geometry),
            "fallback_support_strip_geometry": _geometry_summary(self.fallback_support_strip_geometry),
            "terminal_support_corridor_geometry": _geometry_summary(self.terminal_support_corridor_geometry),
        }

    def to_audit_doc(self) -> dict[str, Any]:
        return {
            "event_unit_id": self.event_unit_id,
            "support_road_ids": list(self.support_road_ids),
            "support_event_road_ids": list(self.support_event_road_ids),
            "positive_rcsd_road_ids": list(self.positive_rcsd_road_ids),
            "positive_rcsd_node_ids": list(self.positive_rcsd_node_ids),
            "surface_scenario_type": self.surface_scenario_type,
            "section_reference_source": self.section_reference_source,
            "surface_generation_mode": self.surface_generation_mode,
            "reference_point_present": self.reference_point_present,
            "surface_scenario_missing": self.surface_scenario_missing,
            "surface_section_forward_m": self.surface_section_forward_m,
            "surface_section_backward_m": self.surface_section_backward_m,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
            "support_domain_from_reference_kind": self.support_domain_from_reference_kind,
            "fallback_rcsdroad_ids": list(self.fallback_rcsdroad_ids),
            "fallback_local_window_m": self.fallback_local_window_m,
            "fallback_support_strip_area_m2": self.fallback_support_strip_area_m2,
            "fallback_rcsdroad_localized": self.fallback_rcsdroad_localized,
            "no_virtual_reference_point_guard": self.no_virtual_reference_point_guard,
            "divstrip_negative_mask_present": self.divstrip_negative_mask_present,
            "forbidden_domain_kept": self.forbidden_domain_kept,
            "swsd_only_entity_support_domain": self.swsd_only_entity_support_domain,
            "surface_fill_mode": self.surface_fill_mode,
            "surface_fill_axis_half_width_m": self.surface_fill_axis_half_width_m,
            "single_component_surface_seed": self.single_component_surface_seed,
            "must_cover_components": dict(self.must_cover_components),
            "unit_terminal_window_domain": _geometry_summary(self.unit_terminal_window_domain),
            "axis_lateral_band_geometry": _geometry_summary(self.axis_lateral_band_geometry),
            "junction_full_road_fill_domain": _geometry_summary(self.junction_full_road_fill_domain),
            "terminal_support_corridor_geometry": _geometry_summary(self.terminal_support_corridor_geometry),
        }


@dataclass(frozen=True)
class T04Step5CaseResult:
    case_id: str
    unit_results: tuple[T04Step5UnitResult, ...]
    case_must_cover_domain: BaseGeometry | None
    case_allowed_growth_domain: BaseGeometry | None
    case_forbidden_domain: BaseGeometry | None
    case_terminal_cut_constraints: BaseGeometry | None
    case_terminal_window_domain: BaseGeometry | None
    case_terminal_support_corridor_geometry: BaseGeometry | None
    case_bridge_zone_geometry: BaseGeometry | None
    case_support_graph_geometry: BaseGeometry | None
    unrelated_swsd_mask_geometry: BaseGeometry | None
    unrelated_rcsd_mask_geometry: BaseGeometry | None
    divstrip_void_mask_geometry: BaseGeometry | None
    drivezone_outside_enforced_by_allowed_domain: bool
    related_swsd_road_ids: tuple[str, ...] = ()
    related_rcsd_road_ids: tuple[str, ...] = ()
    surface_section_forward_m: float = STEP5_SURFACE_SECTION_FORWARD_M
    surface_section_backward_m: float = STEP5_SURFACE_SECTION_BACKWARD_M
    surface_lateral_limit_m: float = STEP5_SURFACE_LATERAL_LIMIT_M
    no_virtual_reference_point_guard: bool = True
    forbidden_domain_kept: bool = False
    divstrip_negative_mask_present: bool = False

    def unit_result_by_id(self, event_unit_id: str) -> T04Step5UnitResult:
        for unit_result in self.unit_results:
            if unit_result.event_unit_id == event_unit_id:
                return unit_result
        raise KeyError(event_unit_id)

    def to_status_doc(self) -> dict[str, Any]:
        ready_count = sum(1 for unit in self.unit_results if unit.legacy_step5_ready)
        return {
            "case_id": self.case_id,
            "unit_count": len(self.unit_results),
            "legacy_step5_ready_unit_count": ready_count,
            "surface_section_forward_m": self.surface_section_forward_m,
            "surface_section_backward_m": self.surface_section_backward_m,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
            "no_virtual_reference_point_guard": self.no_virtual_reference_point_guard,
            "forbidden_domain_kept": self.forbidden_domain_kept,
            "divstrip_negative_mask_present": self.divstrip_negative_mask_present,
            "case_must_cover_domain": _geometry_summary(self.case_must_cover_domain),
            "case_allowed_growth_domain": _geometry_summary(self.case_allowed_growth_domain),
            "case_forbidden_domain": _geometry_summary(self.case_forbidden_domain),
            "case_terminal_cut_constraints": _geometry_summary(self.case_terminal_cut_constraints),
            "case_terminal_window_domain": _geometry_summary(self.case_terminal_window_domain),
            "case_terminal_support_corridor_geometry": _geometry_summary(self.case_terminal_support_corridor_geometry),
            "case_bridge_zone_geometry": _geometry_summary(self.case_bridge_zone_geometry),
            "unit_results": [unit.to_status_doc() for unit in self.unit_results],
        }

    def to_audit_doc(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "drivezone_outside_enforced_by_allowed_domain": self.drivezone_outside_enforced_by_allowed_domain,
            "surface_section_forward_m": self.surface_section_forward_m,
            "surface_section_backward_m": self.surface_section_backward_m,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
            "no_virtual_reference_point_guard": self.no_virtual_reference_point_guard,
            "forbidden_domain_kept": self.forbidden_domain_kept,
            "divstrip_negative_mask_present": self.divstrip_negative_mask_present,
            "case_support_graph_geometry": _geometry_summary(self.case_support_graph_geometry),
            "unrelated_swsd_mask_geometry": _geometry_summary(self.unrelated_swsd_mask_geometry),
            "unrelated_rcsd_mask_geometry": _geometry_summary(self.unrelated_rcsd_mask_geometry),
            "divstrip_void_mask_geometry": _geometry_summary(self.divstrip_void_mask_geometry),
            "case_terminal_window_domain": _geometry_summary(self.case_terminal_window_domain),
            "case_terminal_support_corridor_geometry": _geometry_summary(self.case_terminal_support_corridor_geometry),
            "related_swsd_road_ids": list(self.related_swsd_road_ids),
            "related_rcsd_road_ids": list(self.related_rcsd_road_ids),
            "unit_results": [unit.to_audit_doc() for unit in self.unit_results],
        }

    def to_vector_features(self) -> list[dict[str, Any]]:
        features: list[dict[str, Any]] = []

        def append_feature(
            *,
            scope: str,
            event_unit_id: str,
            domain_role: str,
            component_role: str,
            geometry: BaseGeometry | None,
        ) -> None:
            normalized = _normalize_geometry(geometry)
            if normalized is None:
                return
            features.append(
                {
                    "properties": {
                        "case_id": self.case_id,
                        "scope": scope,
                        "event_unit_id": event_unit_id,
                        "domain_role": domain_role,
                        "component_role": component_role,
                    },
                    "geometry": normalized,
                }
            )

        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_must_cover_domain",
            component_role="case_must_cover_domain",
            geometry=self.case_must_cover_domain,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_allowed_growth_domain",
            component_role="case_allowed_growth_domain",
            geometry=self.case_allowed_growth_domain,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_forbidden_domain",
            component_role="case_forbidden_domain",
            geometry=self.case_forbidden_domain,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_terminal_cut_constraints",
            component_role="case_terminal_cut_constraints",
            geometry=self.case_terminal_cut_constraints,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_terminal_window_domain",
            component_role="case_terminal_window_domain",
            geometry=self.case_terminal_window_domain,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_allowed_growth_domain",
            component_role="case_terminal_support_corridor_geometry",
            geometry=self.case_terminal_support_corridor_geometry,
        )
        append_feature(
            scope="case",
            event_unit_id="",
            domain_role="case_allowed_growth_domain",
            component_role="case_bridge_zone_geometry",
            geometry=self.case_bridge_zone_geometry,
        )

        for unit in self.unit_results:
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_must_cover_domain",
                component_role="unit_must_cover_domain",
                geometry=unit.unit_must_cover_domain,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_allowed_growth_domain",
                component_role="unit_allowed_growth_domain",
                geometry=unit.unit_allowed_growth_domain,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_forbidden_domain",
                component_role="unit_forbidden_domain",
                geometry=unit.unit_forbidden_domain,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_terminal_cut_constraints",
                component_role="unit_terminal_cut_constraints",
                geometry=unit.unit_terminal_cut_constraints,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_terminal_window_domain",
                component_role="unit_terminal_window_domain",
                geometry=unit.unit_terminal_window_domain,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_allowed_growth_domain",
                component_role="axis_lateral_band_geometry",
                geometry=unit.axis_lateral_band_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_allowed_growth_domain",
                component_role="junction_full_road_fill_domain",
                geometry=unit.junction_full_road_fill_domain,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_allowed_growth_domain",
                component_role="terminal_support_corridor_geometry",
                geometry=unit.terminal_support_corridor_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_must_cover_domain",
                component_role="localized_evidence_core_geometry",
                geometry=unit.localized_evidence_core_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_must_cover_domain",
                component_role="fact_reference_patch_geometry",
                geometry=unit.fact_reference_patch_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_must_cover_domain",
                component_role="required_rcsd_node_patch_geometry",
                geometry=unit.required_rcsd_node_patch_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_allowed_growth_domain",
                component_role="target_b_node_patch_geometry",
                geometry=unit.target_b_node_patch_geometry,
            )
            append_feature(
                scope="unit",
                event_unit_id=unit.event_unit_id,
                domain_role="unit_must_cover_domain",
                component_role="fallback_support_strip_geometry",
                geometry=unit.fallback_support_strip_geometry,
            )
        return features


def _build_step5_unit_result(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
    case_external_forbidden_geometry: BaseGeometry | None,
    other_unit_core_occupancy_geometry: BaseGeometry | None,
    divstrip_negative_mask_present: bool,
) -> T04Step5UnitResult:
    bridge = unit_result.interpretation.legacy_step5_bridge
    config = _step5_surface_window_config(unit_result)
    if not config.entity_support_enabled:
        return T04Step5UnitResult(
            event_unit_id=unit_result.spec.event_unit_id,
            event_type=unit_result.spec.event_type,
            review_state=unit_result.review_state,
            positive_rcsd_consistency_level=unit_result.positive_rcsd_consistency_level,
            positive_rcsd_support_level=unit_result.positive_rcsd_support_level,
            required_rcsd_node=unit_result.required_rcsd_node,
            legacy_step5_ready=bool(unit_result.interpretation.legacy_step5_readiness.ready),
            legacy_step5_reasons=tuple(unit_result.interpretation.legacy_step5_readiness.reasons),
            localized_evidence_core_geometry=None,
            fact_reference_patch_geometry=None,
            required_rcsd_node_patch_geometry=None,
            target_b_node_patch_geometry=None,
            fallback_support_strip_geometry=None,
            axis_lateral_band_geometry=None,
            junction_full_road_fill_domain=None,
            unit_must_cover_domain=None,
            unit_allowed_growth_domain=None,
            unit_forbidden_domain=case_external_forbidden_geometry,
            unit_terminal_cut_constraints=None,
            unit_terminal_window_domain=None,
            terminal_support_corridor_geometry=None,
            surface_fill_mode="no_surface",
            surface_fill_axis_half_width_m=None,
            single_component_surface_seed=False,
            support_road_ids=tuple(bridge.selected_road_ids),
            support_event_road_ids=tuple(bridge.selected_event_road_ids),
            positive_rcsd_road_ids=tuple(unit_result.selected_rcsdroad_ids),
            positive_rcsd_node_ids=tuple(unit_result.selected_rcsdnode_ids),
            must_cover_components={
                "localized_evidence_core_geometry": False,
                "fact_reference_patch_geometry": False,
                "required_rcsd_node_patch_geometry": False,
                "junction_full_road_fill_domain": False,
                "fallback_support_strip_geometry": False,
                "target_b_node_patch_geometry": False,
            },
            surface_scenario_type=config.surface_scenario_type,
            section_reference_source=config.section_reference_source,
            surface_generation_mode=config.surface_generation_mode,
            reference_point_present=config.reference_point_present,
            surface_scenario_missing=config.surface_scenario_missing,
            support_domain_from_reference_kind=config.support_domain_from_reference_kind,
            surface_section_forward_m=config.surface_section_forward_m,
            surface_section_backward_m=config.surface_section_backward_m,
            surface_lateral_limit_m=config.surface_lateral_limit_m,
            fallback_rcsdroad_ids=config.fallback_rcsdroad_ids,
            fallback_local_window_m=config.fallback_local_window_m,
            fallback_support_strip_area_m2=0.0,
            fallback_rcsdroad_localized=False,
            no_virtual_reference_point_guard=config.no_virtual_reference_point_guard,
            divstrip_negative_mask_present=divstrip_negative_mask_present,
            forbidden_domain_kept=case_external_forbidden_geometry is not None,
        )
    localized_evidence_core_geometry = _clip_to_drivezone(
        unit_result.localized_evidence_core_geometry,
        drivezone_union,
    )
    fact_reference_patch_geometry = (
        _buffered_patch(
            unit_result.fact_reference_point,
            radius_m=STEP5_POINT_PATCH_RADIUS_M,
            drivezone_union=drivezone_union,
        )
        if config.reference_point_present or config.surface_scenario_missing
        else None
    )
    full_road_fill_requested = _uses_junction_full_road_fill(unit_result)
    junction_window_requested = _uses_junction_window(unit_result)
    required_rcsd_node_patch_geometry = None
    if (
        (
            unit_result.positive_rcsd_consistency_level == "A"
            or full_road_fill_requested
            or junction_window_requested
        )
        and unit_result.required_rcsd_node is not None
    ):
        required_rcsd_node_patch_geometry = _buffered_patch(
            unit_result.required_rcsd_node_geometry,
            radius_m=STEP5_REQUIRED_NODE_PATCH_RADIUS_M,
            drivezone_union=drivezone_union,
        )
    target_b_node_patch_geometry = None
    if (
        unit_result.positive_rcsd_consistency_level == "B"
        and unit_result.required_rcsd_node is not None
    ):
        target_b_node_patch_geometry = _buffered_patch(
            unit_result.required_rcsd_node_geometry,
            radius_m=STEP5_B_NODE_TARGET_PATCH_RADIUS_M,
            drivezone_union=drivezone_union,
        )
    fallback_support_strip_geometry = None
    if _should_build_fallback_support_strip(
        unit_result,
        config=config,
        junction_window_requested=junction_window_requested,
    ):
        fallback_support_strip_geometry = _build_fallback_support_strip(
            unit_result,
            drivezone_union=drivezone_union,
        )
    terminal_support_corridor_geometry = _build_terminal_support_corridor(
        unit_result,
        drivezone_union=drivezone_union,
    )
    axis_lateral_band_geometry = _build_junction_full_road_fill_axis_band(
        unit_result,
        drivezone_union=drivezone_union,
    )
    junction_full_road_fill_domain = _build_junction_full_road_fill_domain(
        unit_result,
        drivezone_union=drivezone_union,
    )
    junction_full_road_fill_domain = _seed_connected_fill_domain(
        junction_full_road_fill_domain,
        [
            localized_evidence_core_geometry,
            fact_reference_patch_geometry,
            required_rcsd_node_patch_geometry,
            target_b_node_patch_geometry,
        ],
    )
    if junction_window_requested:
        localized_evidence_core_geometry = None
    surface_fill_mode = (
        "junction_window"
        if junction_window_requested and junction_full_road_fill_domain is not None
        else "junction_full_road_fill"
        if junction_full_road_fill_domain is not None
        else "standard"
    )
    surface_fill_axis_half_width_m = (
        STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M
        if junction_full_road_fill_domain is not None
        else None
    )
    single_component_surface_seed = (
        unit_result.evidence_source == "road_surface_fork"
        and junction_full_road_fill_domain is None
    )
    surface_growth_geometries = [
        unit_result.selected_candidate_region_geometry,
        unit_result.selected_component_union_geometry,
        unit_result.pair_local_structure_face_geometry,
    ]
    if junction_window_requested:
        surface_growth_geometries = []
    if single_component_surface_seed:
        surface_component = _single_surface_component_domain(
            _union_geometry(surface_growth_geometries),
            seed_geometries=[
                localized_evidence_core_geometry,
                fact_reference_patch_geometry,
            ],
            forbidden_geometry=case_external_forbidden_geometry,
            drivezone_union=drivezone_union,
        )
        if surface_component is not None:
            surface_growth_geometries = [surface_component]
            if localized_evidence_core_geometry is not None and not localized_evidence_core_geometry.is_empty:
                clipped_core = _normalize_geometry(
                    localized_evidence_core_geometry.intersection(surface_component)
                )
                if clipped_core is not None:
                    localized_evidence_core_geometry = clipped_core
            if fact_reference_patch_geometry is not None and not fact_reference_patch_geometry.is_empty:
                clipped_reference_patch = _normalize_geometry(
                    fact_reference_patch_geometry.intersection(surface_component)
                )
                if clipped_reference_patch is not None:
                    fact_reference_patch_geometry = clipped_reference_patch

    unit_must_cover_domain = _clip_to_drivezone(
        _union_geometry(
            [
                localized_evidence_core_geometry,
                fact_reference_patch_geometry,
                required_rcsd_node_patch_geometry,
                junction_full_road_fill_domain,
                fallback_support_strip_geometry,
            ]
        ),
        drivezone_union,
    )
    unit_allowed_growth_domain = _clip_to_drivezone(
        _union_geometry(
            [
                *surface_growth_geometries,
                fallback_support_strip_geometry,
                junction_full_road_fill_domain,
                terminal_support_corridor_geometry,
                target_b_node_patch_geometry,
                unit_must_cover_domain,
            ]
        ),
        drivezone_union,
    )
    other_unit_mask = None
    if other_unit_core_occupancy_geometry is not None and not other_unit_core_occupancy_geometry.is_empty:
        other_unit_mask = _clip_to_drivezone(
            other_unit_core_occupancy_geometry.buffer(STEP5_NEGATIVE_MASK_BUFFER_M),
            drivezone_union,
        )
    unit_forbidden_domain = _clip_to_drivezone(
        _union_geometry(
            [
                case_external_forbidden_geometry,
                other_unit_mask,
            ]
        ),
        drivezone_union,
    )
    unit_terminal_cut_constraints = _build_terminal_cut_constraints(
        unit_result,
        drivezone_union=drivezone_union,
    )
    unit_terminal_window_domain = _build_terminal_window_domain(
        unit_result,
        drivezone_union=drivezone_union,
    )
    must_cover_components = {
        "localized_evidence_core_geometry": localized_evidence_core_geometry is not None,
        "fact_reference_patch_geometry": fact_reference_patch_geometry is not None,
        "required_rcsd_node_patch_geometry": required_rcsd_node_patch_geometry is not None,
        "junction_full_road_fill_domain": junction_full_road_fill_domain is not None,
        "fallback_support_strip_geometry": fallback_support_strip_geometry is not None,
        "target_b_node_patch_geometry": target_b_node_patch_geometry is not None,
    }
    fallback_summary = _geometry_summary(fallback_support_strip_geometry)
    swsd_only_entity_support_domain = bool(
        config.surface_scenario_type == SCENARIO_NO_MAIN_WITH_SWSD_ONLY
        and junction_full_road_fill_domain is not None
        and not junction_full_road_fill_domain.is_empty
        and unit_must_cover_domain is not None
        and not unit_must_cover_domain.is_empty
        and unit_allowed_growth_domain is not None
        and not unit_allowed_growth_domain.is_empty
    )
    return T04Step5UnitResult(
        event_unit_id=unit_result.spec.event_unit_id,
        event_type=unit_result.spec.event_type,
        review_state=unit_result.review_state,
        positive_rcsd_consistency_level=unit_result.positive_rcsd_consistency_level,
        positive_rcsd_support_level=unit_result.positive_rcsd_support_level,
        required_rcsd_node=unit_result.required_rcsd_node,
        legacy_step5_ready=bool(unit_result.interpretation.legacy_step5_readiness.ready),
        legacy_step5_reasons=tuple(unit_result.interpretation.legacy_step5_readiness.reasons),
        localized_evidence_core_geometry=localized_evidence_core_geometry,
        fact_reference_patch_geometry=fact_reference_patch_geometry,
        required_rcsd_node_patch_geometry=required_rcsd_node_patch_geometry,
        target_b_node_patch_geometry=target_b_node_patch_geometry,
        fallback_support_strip_geometry=fallback_support_strip_geometry,
        axis_lateral_band_geometry=axis_lateral_band_geometry,
        junction_full_road_fill_domain=junction_full_road_fill_domain,
        unit_must_cover_domain=unit_must_cover_domain,
        unit_allowed_growth_domain=unit_allowed_growth_domain,
        unit_forbidden_domain=unit_forbidden_domain,
        unit_terminal_cut_constraints=unit_terminal_cut_constraints,
        unit_terminal_window_domain=unit_terminal_window_domain,
        terminal_support_corridor_geometry=terminal_support_corridor_geometry,
        surface_fill_mode=surface_fill_mode,
        surface_fill_axis_half_width_m=surface_fill_axis_half_width_m,
        single_component_surface_seed=single_component_surface_seed,
        support_road_ids=tuple(bridge.selected_road_ids),
        support_event_road_ids=tuple(bridge.selected_event_road_ids),
        positive_rcsd_road_ids=tuple(unit_result.selected_rcsdroad_ids),
        positive_rcsd_node_ids=tuple(unit_result.selected_rcsdnode_ids),
        must_cover_components=must_cover_components,
        surface_scenario_type=config.surface_scenario_type,
        section_reference_source=config.section_reference_source,
        surface_generation_mode=config.surface_generation_mode,
        reference_point_present=config.reference_point_present,
        surface_scenario_missing=config.surface_scenario_missing,
        support_domain_from_reference_kind=config.support_domain_from_reference_kind,
        surface_section_forward_m=config.surface_section_forward_m,
        surface_section_backward_m=config.surface_section_backward_m,
        surface_lateral_limit_m=config.surface_lateral_limit_m,
        fallback_rcsdroad_ids=config.fallback_rcsdroad_ids,
        fallback_local_window_m=config.fallback_local_window_m,
        fallback_support_strip_area_m2=float(fallback_summary["area_m2"]),
        fallback_rcsdroad_localized=bool(config.fallback_rcsdroad_ids and fallback_support_strip_geometry is not None),
        no_virtual_reference_point_guard=(
            config.no_virtual_reference_point_guard
            and (config.reference_point_present or fact_reference_patch_geometry is None)
        ),
        divstrip_negative_mask_present=divstrip_negative_mask_present,
        forbidden_domain_kept=case_external_forbidden_geometry is not None,
        swsd_only_entity_support_domain=swsd_only_entity_support_domain,
    )


def build_step5_support_domain(case_result: T04CaseResult) -> T04Step5CaseResult:
    drivezone_union = _loaded_feature_union(case_result.case_bundle.drivezone_features)
    external_support_roads = _unique_roads(
        road
        for event_unit in case_result.event_units
        for road in (
            *event_unit.interpretation.legacy_step5_bridge.selected_roads,
            *event_unit.interpretation.legacy_step5_bridge.selected_event_roads,
            *event_unit.interpretation.legacy_step5_bridge.complex_local_support_roads,
        )
    )
    seed_swsd_road_ids = {
        str(getattr(road, "road_id", "") or "").strip()
        for road in external_support_roads
        if str(getattr(road, "road_id", "") or "").strip()
    }
    seed_rcsd_road_ids = {
        str(road_id)
        for event_unit in case_result.event_units
        for road_id in (
            tuple(event_unit.selected_rcsdroad_ids)
            + tuple(event_unit.pair_local_rcsd_road_ids)
        )
        if str(road_id).strip()
    }
    current_semantic_node_ids = {
        str(node.node_id)
        for node in (case_result.case_bundle.representative_node, *case_result.case_bundle.group_nodes)
        if str(getattr(node, "node_id", "") or "").strip()
    }
    related_swsd_road_ids = _expanded_related_road_ids(
        seed_road_ids=seed_swsd_road_ids,
        roads=case_result.case_bundle.roads,
        current_semantic_node_ids=current_semantic_node_ids,
    )
    related_rcsd_road_ids = _expanded_related_road_ids(
        seed_road_ids=seed_rcsd_road_ids,
        roads=case_result.case_bundle.rcsd_roads,
        current_semantic_node_ids=current_semantic_node_ids,
    )
    unrelated_swsd_mask_geometry = _clip_to_drivezone(
        _union_geometry(
            road.geometry.buffer(STEP5_NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2)
            for road in case_result.case_bundle.roads
            if str(road.road_id) not in related_swsd_road_ids
        ),
        drivezone_union,
    )
    unrelated_rcsd_mask_geometry = _clip_to_drivezone(
        _union_geometry(
            road.geometry.buffer(STEP5_NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2)
            for road in case_result.case_bundle.rcsd_roads
            if str(road.road_id) not in related_rcsd_road_ids
        ),
        drivezone_union,
    )
    divstrip_void_mask_geometry = _divstrip_void_mask(
        case_result,
        drivezone_union=drivezone_union,
    )
    case_external_forbidden_geometry = _clip_to_drivezone(
        _union_geometry(
            [
                unrelated_swsd_mask_geometry,
                unrelated_rcsd_mask_geometry,
                divstrip_void_mask_geometry,
            ]
        ),
        drivezone_union,
    )
    unit_core_occupancies: dict[str, BaseGeometry | None] = {}
    precomputed_components: dict[str, dict[str, BaseGeometry | None]] = {}
    for event_unit in case_result.event_units:
        config = _step5_surface_window_config(event_unit)
        junction_window_requested = _uses_junction_window(event_unit)
        localized_evidence_core_geometry = _clip_to_drivezone(
            None if junction_window_requested or not config.entity_support_enabled else event_unit.localized_evidence_core_geometry,
            drivezone_union,
        )
        required_rcsd_node_patch_geometry = None
        if (
            config.entity_support_enabled
            and
            (
                event_unit.positive_rcsd_consistency_level == "A"
                or _uses_junction_full_road_fill(event_unit)
                or junction_window_requested
            )
            and event_unit.required_rcsd_node is not None
        ):
            required_rcsd_node_patch_geometry = _buffered_patch(
                event_unit.required_rcsd_node_geometry,
                radius_m=STEP5_REQUIRED_NODE_PATCH_RADIUS_M,
                drivezone_union=drivezone_union,
            )
        fallback_support_strip_geometry = None
        if _should_build_fallback_support_strip(
            event_unit,
            config=config,
            junction_window_requested=junction_window_requested,
        ):
            fallback_support_strip_geometry = _build_fallback_support_strip(
                event_unit,
                drivezone_union=drivezone_union,
            )
        unit_core_occupancies[event_unit.spec.event_unit_id] = _clip_to_drivezone(
            _union_geometry(
                [
                    localized_evidence_core_geometry,
                    required_rcsd_node_patch_geometry,
                    fallback_support_strip_geometry,
                ]
            ),
            drivezone_union,
        )
        precomputed_components[event_unit.spec.event_unit_id] = {
            "localized_evidence_core_geometry": localized_evidence_core_geometry,
            "required_rcsd_node_patch_geometry": required_rcsd_node_patch_geometry,
            "fallback_support_strip_geometry": fallback_support_strip_geometry,
        }

    unit_results: list[T04Step5UnitResult] = []
    for event_unit in case_result.event_units:
        other_core_geometry = _union_geometry(
            geometry
            for other_unit_id, geometry in unit_core_occupancies.items()
            if other_unit_id != event_unit.spec.event_unit_id
        )
        unit_results.append(
            _build_step5_unit_result(
                event_unit,
                drivezone_union=drivezone_union,
                case_external_forbidden_geometry=case_external_forbidden_geometry,
                other_unit_core_occupancy_geometry=other_core_geometry,
                divstrip_negative_mask_present=divstrip_void_mask_geometry is not None,
            )
        )

    case_must_cover_domain = _clip_to_drivezone(
        _union_geometry(unit.unit_must_cover_domain for unit in unit_results),
        drivezone_union,
    )
    base_allowed_geometries = [unit.unit_allowed_growth_domain for unit in unit_results]
    case_support_graph_geometry = _clip_to_drivezone(
        _union_geometry(
            [
                *base_allowed_geometries,
                _road_buffer_union(
                    external_support_roads,
                    buffer_m=STEP5_SUPPORT_ROAD_BUFFER_M,
                    drivezone_union=drivezone_union,
                ),
            ]
        ),
        drivezone_union,
    )
    full_fill_bridge_geometries = _multi_unit_full_fill_bridge_geometries(
        unit_results,
        support_graph_geometry=case_support_graph_geometry,
        drivezone_union=drivezone_union,
    )
    bridge_geometries: list[BaseGeometry] = []
    unit_allowed_non_empty = [
        unit.unit_allowed_growth_domain
        for unit in unit_results
        if unit.unit_allowed_growth_domain is not None and not unit.unit_allowed_growth_domain.is_empty
    ]
    if len(unit_allowed_non_empty) > 1:
        current_geometry = unit_allowed_non_empty[0]
        remaining = list(unit_allowed_non_empty[1:])
        while remaining:
            best_index = 0
            best_distance = float("inf")
            for index, candidate in enumerate(remaining):
                distance = float(current_geometry.distance(candidate))
                if distance < best_distance:
                    best_distance = distance
                    best_index = index
            candidate = remaining.pop(best_index)
            bridge_geometry = _nearest_bridge_patch(
                current_geometry,
                candidate,
                support_graph_geometry=case_support_graph_geometry,
                drivezone_union=drivezone_union,
            )
            if bridge_geometry is not None and not bridge_geometry.is_empty:
                bridge_geometries.append(bridge_geometry)
                current_geometry = _clip_to_drivezone(
                    _union_geometry([current_geometry, candidate, bridge_geometry]),
                    drivezone_union,
                ) or current_geometry
            else:
                current_geometry = _clip_to_drivezone(
                    _union_geometry([current_geometry, candidate]),
                    drivezone_union,
                ) or current_geometry
    case_bridge_zone_geometry = _clip_to_drivezone(
        _union_geometry([*bridge_geometries, *full_fill_bridge_geometries]),
        drivezone_union,
    )
    case_allowed_growth_domain = _clip_to_drivezone(
        _union_geometry(
            [
                *base_allowed_geometries,
                case_bridge_zone_geometry,
            ]
        ),
        drivezone_union,
    )
    case_forbidden_domain = case_external_forbidden_geometry
    case_terminal_cut_constraints = _build_case_terminal_cut_constraints(
        case_result,
        unit_results=unit_results,
        drivezone_union=drivezone_union,
    )
    case_terminal_window_domain = _clip_to_drivezone(
        _union_geometry(
            [
                *(unit.unit_terminal_window_domain for unit in unit_results),
                *full_fill_bridge_geometries,
            ]
        ),
        drivezone_union,
    )
    case_terminal_support_corridor_geometry = _clip_to_drivezone(
        _union_geometry(unit.terminal_support_corridor_geometry for unit in unit_results),
        drivezone_union,
    )
    return T04Step5CaseResult(
        case_id=case_result.case_spec.case_id,
        unit_results=tuple(unit_results),
        case_must_cover_domain=case_must_cover_domain,
        case_allowed_growth_domain=case_allowed_growth_domain,
        case_forbidden_domain=case_forbidden_domain,
        case_terminal_cut_constraints=case_terminal_cut_constraints,
        case_terminal_window_domain=case_terminal_window_domain,
        case_terminal_support_corridor_geometry=case_terminal_support_corridor_geometry,
        case_bridge_zone_geometry=case_bridge_zone_geometry,
        case_support_graph_geometry=case_support_graph_geometry,
        unrelated_swsd_mask_geometry=unrelated_swsd_mask_geometry,
        unrelated_rcsd_mask_geometry=unrelated_rcsd_mask_geometry,
        divstrip_void_mask_geometry=divstrip_void_mask_geometry,
        drivezone_outside_enforced_by_allowed_domain=True,
        related_swsd_road_ids=tuple(sorted(related_swsd_road_ids)),
        related_rcsd_road_ids=tuple(sorted(related_rcsd_road_ids)),
        surface_section_forward_m=STEP5_SURFACE_SECTION_FORWARD_M,
        surface_section_backward_m=STEP5_SURFACE_SECTION_BACKWARD_M,
        surface_lateral_limit_m=STEP5_SURFACE_LATERAL_LIMIT_M,
        no_virtual_reference_point_guard=all(unit.no_virtual_reference_point_guard for unit in unit_results),
        forbidden_domain_kept=case_forbidden_domain is not None,
        divstrip_negative_mask_present=divstrip_void_mask_geometry is not None,
    )


__all__ = [
    "Step5SurfaceWindowConfig",
    "T04Step5CaseResult",
    "T04Step5UnitResult",
    "build_step5_support_domain",
    "derive_step5_surface_window_config",
]
