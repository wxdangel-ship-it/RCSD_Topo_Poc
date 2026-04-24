from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Iterable, Sequence

from shapely.geometry import LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from ._rcsd_selection_support import _as_point, _normalize_geometry, _union_geometry
from ._runtime_types_io import ParsedRoad
from .case_models import T04CaseResult, T04EventUnitResult


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
STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M = 20.0


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
    origin_point = _as_point(bridge.event_origin_point) or _as_point(unit_result.fact_reference_point)
    return _vector_from_roads(
        tuple(bridge.selected_event_roads) or tuple(bridge.selected_roads),
        origin_point,
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
    origin_point = _as_point(bridge.event_origin_point) or _as_point(unit_result.fact_reference_point)
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
    return _clip_to_drivezone(window_domain, drivezone_union)


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
    return bool(
        unit_result.evidence_source == "rcsd_anchored_reverse"
        and str(unit_result.required_rcsd_node or "").strip()
        and _as_point(unit_result.fact_reference_point) is not None
        and _as_point(unit_result.required_rcsd_node_geometry) is not None
    )


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
    axis_band = _build_junction_full_road_fill_axis_band(
        unit_result,
        drivezone_union=drivezone_union,
    )
    if axis_band is None:
        return None
    return _clip_to_drivezone(axis_band, drivezone_union)


def _build_fallback_support_strip(
    unit_result: T04EventUnitResult,
    *,
    drivezone_union: BaseGeometry | None,
) -> BaseGeometry | None:
    center_point = _as_point(unit_result.fact_reference_point)
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
) -> BaseGeometry | None:
    try:
        left_point, right_point = nearest_points(left, right)
    except Exception:
        return None
    if left_point is None or right_point is None:
        return None
    if left_point.distance(right_point) <= 1e-6:
        bridge = left_point.buffer(STEP5_BRIDGE_HALF_WIDTH_M)
    else:
        bridge = LineString([left_point, right_point]).buffer(
            STEP5_BRIDGE_HALF_WIDTH_M,
            cap_style=2,
            join_style=2,
        )
    if support_graph_geometry is not None and not support_graph_geometry.is_empty:
        bridge = bridge.intersection(
            support_graph_geometry.buffer(STEP5_SUPPORT_GRAPH_PAD_M)
        )
    return _clip_to_drivezone(bridge, drivezone_union)


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
    support_road_ids: tuple[str, ...] = ()
    support_event_road_ids: tuple[str, ...] = ()
    positive_rcsd_road_ids: tuple[str, ...] = ()
    positive_rcsd_node_ids: tuple[str, ...] = ()
    must_cover_components: dict[str, bool] = field(default_factory=dict)

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
            "surface_fill_mode": self.surface_fill_mode,
            "surface_fill_axis_half_width_m": self.surface_fill_axis_half_width_m,
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
            "surface_fill_mode": self.surface_fill_mode,
            "surface_fill_axis_half_width_m": self.surface_fill_axis_half_width_m,
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
) -> T04Step5UnitResult:
    bridge = unit_result.interpretation.legacy_step5_bridge
    localized_evidence_core_geometry = _clip_to_drivezone(
        unit_result.localized_evidence_core_geometry,
        drivezone_union,
    )
    fact_reference_patch_geometry = _buffered_patch(
        unit_result.fact_reference_point,
        radius_m=STEP5_POINT_PATCH_RADIUS_M,
        drivezone_union=drivezone_union,
    )
    full_road_fill_requested = _uses_junction_full_road_fill(unit_result)
    required_rcsd_node_patch_geometry = None
    if (
        (
            unit_result.positive_rcsd_consistency_level == "A"
            or full_road_fill_requested
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
    if (
        unit_result.evidence_source != "road_surface_fork"
        and (
            unit_result.positive_rcsd_consistency_level == "C"
            or (
                unit_result.positive_rcsd_consistency_level == "B"
                and unit_result.required_rcsd_node in {None, ""}
            )
        )
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
    surface_fill_mode = (
        "junction_full_road_fill"
        if junction_full_road_fill_domain is not None
        else "standard"
    )
    surface_fill_axis_half_width_m = (
        STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M
        if junction_full_road_fill_domain is not None
        else None
    )

    unit_must_cover_domain = _clip_to_drivezone(
        _union_geometry(
            [
                localized_evidence_core_geometry,
                fact_reference_patch_geometry,
                required_rcsd_node_patch_geometry,
                fallback_support_strip_geometry,
            ]
        ),
        drivezone_union,
    )
    unit_allowed_growth_domain = _clip_to_drivezone(
        _union_geometry(
            [
                unit_result.selected_candidate_region_geometry,
                unit_result.selected_component_union_geometry,
                unit_result.pair_local_structure_face_geometry,
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
        "fallback_support_strip_geometry": fallback_support_strip_geometry is not None,
        "target_b_node_patch_geometry": target_b_node_patch_geometry is not None,
    }
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
        support_road_ids=tuple(bridge.selected_road_ids),
        support_event_road_ids=tuple(bridge.selected_event_road_ids),
        positive_rcsd_road_ids=tuple(unit_result.selected_rcsdroad_ids),
        positive_rcsd_node_ids=tuple(unit_result.selected_rcsdnode_ids),
        must_cover_components=must_cover_components,
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
        localized_evidence_core_geometry = _clip_to_drivezone(
            event_unit.localized_evidence_core_geometry,
            drivezone_union,
        )
        required_rcsd_node_patch_geometry = None
        if (
            (
                event_unit.positive_rcsd_consistency_level == "A"
                or _uses_junction_full_road_fill(event_unit)
            )
            and event_unit.required_rcsd_node is not None
        ):
            required_rcsd_node_patch_geometry = _buffered_patch(
                event_unit.required_rcsd_node_geometry,
                radius_m=STEP5_REQUIRED_NODE_PATCH_RADIUS_M,
                drivezone_union=drivezone_union,
            )
        fallback_support_strip_geometry = None
        if (
            event_unit.evidence_source != "road_surface_fork"
            and (
                event_unit.positive_rcsd_consistency_level == "C"
                or (
                    event_unit.positive_rcsd_consistency_level == "B"
                    and event_unit.required_rcsd_node in {None, ""}
                )
            )
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
        _union_geometry(bridge_geometries),
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
        _union_geometry(unit.unit_terminal_window_domain for unit in unit_results),
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
    )


__all__ = [
    "T04Step5CaseResult",
    "T04Step5UnitResult",
    "build_step5_support_domain",
]
