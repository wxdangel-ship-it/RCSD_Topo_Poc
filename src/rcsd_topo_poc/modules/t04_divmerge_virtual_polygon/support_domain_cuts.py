from __future__ import annotations

from typing import Any, Iterable, Sequence

from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry

from ._rcsd_selection_support import _as_point, _normalize_geometry, _union_geometry
from ._runtime_types_io import ParsedRoad
from .case_models import T04CaseResult, T04EventUnitResult
from .support_domain_common import (
    _clip_to_drivezone,
    _event_axis_line,
    _event_axis_vector,
    _line_point_and_tangent,
    _normalize_vector,
    _terminal_cut_semantic_anchors,
    _terminal_semantic_axis_line,
)
from .support_domain_scenario import STEP5_TERMINAL_CUT_HALF_WIDTH_M, STEP5_TERMINAL_CUT_WINDOW_MARGIN_M


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
