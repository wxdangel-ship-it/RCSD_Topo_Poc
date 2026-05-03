from __future__ import annotations

from collections import deque
from dataclasses import replace
from typing import Any, Sequence

import numpy as np
from shapely.geometry import GeometryCollection, LineString, Point, Polygon
from shapely.geometry.base import BaseGeometry

from ._rcsd_selection_support import _normalize_geometry, _union_geometry
from ._runtime_polygon_cleanup import POLYGON_SMALL_HOLE_AREA_M2, _fill_small_polygon_holes, _polygon_components
from ._runtime_types_io import (
    DEFAULT_PATCH_SIZE_M,
    _binary_close,
    _build_grid,
    _extract_seed_component,
    _mask_to_geometry,
    _rasterize_geometries,
)
from .case_models import T04CaseResult
from .polygon_assembly_guards import Step6GuardContext, derive_step6_guard_context
from .polygon_assembly_models import T04Step6Result
from .polygon_assembly_relief import (
    cut_sliver_hole_relief as _cut_sliver_hole_relief,
    dominant_component_relief_bridge as _dominant_component_relief_bridge,
    hole_polygons as _hole_polygons,
    seed_dominant_polygon_component as _seed_dominant_polygon_component,
)
from .support_domain import T04Step5CaseResult, T04Step5UnitResult
from .surface_scenario import (
    SCENARIO_MAIN_WITH_RCSD,
    SCENARIO_MAIN_WITHOUT_RCSD,
    SCENARIO_NO_MAIN_WITH_RCSD,
    SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD,
    SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
)


STEP6_GRID_MARGIN_M = 30.0
STEP6_RESOLUTION_M = 0.5
STEP6_MAX_GRID_SIDE_CELLS = 2000
STEP6_CUT_BARRIER_BUFFER_M = 0.75
STEP6_CONNECTIVITY_NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1))
STEP6_CLOSE_ITERATIONS = 1
STEP6_FORBIDDEN_TOLERANCE_AREA_M2 = 1e-6
STEP6_CUT_TOLERANCE_AREA_M2 = 1e-6
STEP6_ALLOWED_TOLERANCE_AREA_M2 = 1e-6
STEP6_INTER_UNIT_SECTION_BRIDGE_BUFFER_M = 8.0
STEP6_INTER_UNIT_SECTION_BRIDGE_MAX_DISTANCE_M = 12.0
STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_RADIUS_M = 2.0
STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_MIN_AREA_M2 = 30.0
STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_MAX_AREA_M2 = 120.0
STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_FORBIDDEN_TOLERANCE_M2 = 0.5
STEP6_SWSD_WINDOW_TOUCH_CLOSE_RADIUS_M = 1.0
STEP6_SWSD_WINDOW_TOUCH_CLOSE_MAX_AREA_DELTA_M2 = 30.0
STEP6_BARRIER_SEPARATION_RELIEF_NOTES = {
    "dominant_component_relief_bridge",
    "post_cut_dominant_component_relief_bridge",
    "main_without_rcsd_component_relief_bridge",
    "swsd_window_touch_close",
}


def _loaded_feature_union(features: Sequence[Any]) -> BaseGeometry | None:
    return _union_geometry(getattr(feature, "geometry", None) for feature in features)


def _clip_to_drivezone(geometry: BaseGeometry | None, drivezone_union: BaseGeometry | None) -> BaseGeometry | None:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return None
    if drivezone_union is None or drivezone_union.is_empty:
        return normalized
    return _normalize_geometry(normalized.intersection(drivezone_union))


def _core_must_cover_geometry(step5_result: T04Step5CaseResult) -> BaseGeometry | None:
    return _normalize_geometry(
        _union_geometry(
            component
            for unit in step5_result.unit_results
            for component in (
                unit.localized_evidence_core_geometry,
                unit.fact_reference_patch_geometry,
                unit.section_reference_patch_geometry,
                unit.required_rcsd_node_patch_geometry,
                unit.fallback_support_strip_geometry,
            )
        )
    )


def _full_fill_target_geometry(step5_result: T04Step5CaseResult) -> BaseGeometry | None:
    return _normalize_geometry(
        _union_geometry(unit.junction_full_road_fill_domain for unit in step5_result.unit_results)
    )


def _junction_full_fill_unit_count(step5_result: T04Step5CaseResult) -> int:
    return sum(
        1
        for unit in step5_result.unit_results
        if unit.junction_full_road_fill_domain is not None
        and not unit.junction_full_road_fill_domain.is_empty
    )


def _is_swsd_only_surface(guard_context: "Step6GuardContext") -> bool:
    return guard_context.surface_scenario_type == SCENARIO_NO_MAIN_WITH_SWSD_ONLY


def _is_swsd_section_window_surface(guard_context: "Step6GuardContext") -> bool:
    return guard_context.surface_scenario_type in {
        SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD,
        SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
    }


def _is_no_main_section_window_surface(guard_context: "Step6GuardContext") -> bool:
    return guard_context.surface_scenario_type in {
        SCENARIO_NO_MAIN_WITH_RCSD,
        SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD,
        SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
    }


def _uses_single_component_surface_seed(step5_result: T04Step5CaseResult) -> bool:
    return bool(
        len(step5_result.unit_results) == 1
        and step5_result.unit_results[0].single_component_surface_seed
    )


def _single_case_bridge_zone(step5_result: T04Step5CaseResult) -> BaseGeometry | None:
    bridge = _normalize_geometry(step5_result.case_bridge_zone_geometry)
    return bridge if bridge is not None and bridge.geom_type in {"Polygon", "MultiPolygon"} else None


def _line_parts(geometry: BaseGeometry | None) -> tuple[BaseGeometry, ...]:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return ()
    if normalized.geom_type == "LineString":
        return (normalized,)
    if normalized.geom_type == "MultiLineString":
        return tuple(part for part in normalized.geoms if not part.is_empty)
    return ()


def _inter_unit_section_bridge_surface(step5_result: T04Step5CaseResult) -> BaseGeometry | None:
    if len(step5_result.unit_results) <= 1:
        return None
    entries: list[tuple[str, BaseGeometry]] = []
    for unit in step5_result.unit_results:
        for line in _line_parts(unit.unit_terminal_cut_constraints):
            entries.append((unit.event_unit_id, line))
    if len(entries) <= 1:
        return None

    best_pair: tuple[BaseGeometry, BaseGeometry] | None = None
    best_distance: float | None = None
    for left_index, (left_unit_id, left_line) in enumerate(entries):
        for right_unit_id, right_line in entries[left_index + 1:]:
            if left_unit_id == right_unit_id:
                continue
            distance = float(left_line.distance(right_line))
            if best_distance is None or distance < best_distance:
                best_distance = distance
                best_pair = (left_line, right_line)
    if (
        best_pair is None
        or best_distance is None
        or best_distance > STEP6_INTER_UNIT_SECTION_BRIDGE_MAX_DISTANCE_M
    ):
        return None

    bridge_surface = _normalize_geometry(
        _union_geometry(best_pair).convex_hull.buffer(
            STEP6_INTER_UNIT_SECTION_BRIDGE_BUFFER_M,
            cap_style=2,
            join_style=2,
        )
    )
    if bridge_surface is None or bridge_surface.is_empty:
        return None
    fill_domains = [
        unit.junction_full_road_fill_domain
        for unit in step5_result.unit_results
        if unit.junction_full_road_fill_domain is not None
        and not unit.junction_full_road_fill_domain.is_empty
    ]
    touched_units = sum(
        1
        for fill_domain in fill_domains
        if bridge_surface.buffer(1e-6).intersects(fill_domain)
    )
    if touched_units < 2:
        return None
    return _normalize_geometry(bridge_surface)


def _relaxed_canvas_component_relief_bridge(
    geometry: BaseGeometry | None,
    *,
    grid: Any,
    relaxed_canvas_mask: np.ndarray,
) -> BaseGeometry | None:
    geometry_mask = _rasterize_geometries(grid, [geometry]) & relaxed_canvas_mask
    components = _component_masks(geometry_mask)
    if len(components) <= 1:
        return None
    current_mask = components[0].copy()
    for component in components[1:]:
        path_mask = _shortest_path_mask(
            canvas_mask=relaxed_canvas_mask,
            source_mask=current_mask,
            target_mask=component,
        )
        if path_mask is None:
            return None
        current_mask |= component
        current_mask |= path_mask
    return _normalize_geometry(_mask_to_geometry(current_mask, grid))


def _constrain_geometry_to_case_limits(
    geometry: BaseGeometry | None,
    *,
    drivezone_union: BaseGeometry | None,
    allowed_geometry: BaseGeometry | None,
    terminal_window_geometry: BaseGeometry | None,
    forbidden_geometry: BaseGeometry | None,
    cut_barrier_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    constrained = _clip_to_drivezone(geometry, drivezone_union)
    if constrained is None or constrained.is_empty:
        return None
    if allowed_geometry is not None and not allowed_geometry.is_empty:
        constrained = _clip_to_drivezone(
            constrained.intersection(allowed_geometry),
            drivezone_union,
        )
    if constrained is None or constrained.is_empty:
        return None
    if terminal_window_geometry is not None and not terminal_window_geometry.is_empty:
        constrained = _clip_to_drivezone(
            constrained.intersection(terminal_window_geometry),
            drivezone_union,
        )
    if constrained is None or constrained.is_empty:
        return None
    if forbidden_geometry is not None and not forbidden_geometry.is_empty:
        constrained = _clip_to_drivezone(
            constrained.difference(forbidden_geometry),
            drivezone_union,
        )
    if constrained is None or constrained.is_empty:
        return None
    if cut_barrier_geometry is not None and not cut_barrier_geometry.is_empty:
        constrained = _clip_to_drivezone(
            constrained.difference(cut_barrier_geometry),
            drivezone_union,
        )
    if constrained is None or constrained.is_empty:
        return None
    return _normalize_geometry(constrained.buffer(0))


def _grid_center_and_patch_size(
    geometry: BaseGeometry | None,
    *,
    fallback_point: Point,
) -> tuple[Point, float]:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return fallback_point, DEFAULT_PATCH_SIZE_M
    min_x, min_y, max_x, max_y = normalized.bounds
    width = float(max_x) - float(min_x)
    height = float(max_y) - float(min_y)
    center = Point((float(min_x) + float(max_x)) / 2.0, (float(min_y) + float(max_y)) / 2.0)
    patch_size_m = max(
        DEFAULT_PATCH_SIZE_M,
        width + 2.0 * STEP6_GRID_MARGIN_M,
        height + 2.0 * STEP6_GRID_MARGIN_M,
    )
    return center, patch_size_m


def _validate_step6_grid_size(*, case_id: str, patch_size_m: float, resolution_m: float) -> None:
    side_cells = int(round(float(patch_size_m) / float(resolution_m)))
    if side_cells <= STEP6_MAX_GRID_SIDE_CELLS:
        return
    raise ValueError(
        "step6_grid_too_large: "
        f"case_id={case_id}, patch_size_m={patch_size_m:.3f}, "
        f"resolution_m={resolution_m:.3f}, side_cells={side_cells}, "
        f"max_side_cells={STEP6_MAX_GRID_SIDE_CELLS}"
    )


def _component_masks(mask: np.ndarray) -> list[np.ndarray]:
    components: list[np.ndarray] = []
    visited = np.zeros_like(mask, dtype=bool)
    starts = np.argwhere(mask)
    for start_row, start_col in starts:
        row = int(start_row)
        col = int(start_col)
        if visited[row, col]:
            continue
        component = np.zeros_like(mask, dtype=bool)
        queue: deque[tuple[int, int]] = deque([(row, col)])
        visited[row, col] = True
        component[row, col] = True
        while queue:
            current_row, current_col = queue.popleft()
            for row_delta, col_delta in STEP6_CONNECTIVITY_NEIGHBORS:
                next_row = current_row + row_delta
                next_col = current_col + col_delta
                if next_row < 0 or next_row >= mask.shape[0] or next_col < 0 or next_col >= mask.shape[1]:
                    continue
                if visited[next_row, next_col] or not mask[next_row, next_col]:
                    continue
                visited[next_row, next_col] = True
                component[next_row, next_col] = True
                queue.append((next_row, next_col))
        components.append(component)
    return components


def _shortest_path_mask(
    *,
    canvas_mask: np.ndarray,
    source_mask: np.ndarray,
    target_mask: np.ndarray,
) -> np.ndarray | None:
    valid_sources = np.argwhere(canvas_mask & source_mask)
    valid_targets = canvas_mask & target_mask
    if valid_sources.size == 0 or not valid_targets.any():
        return None
    if (source_mask & target_mask & canvas_mask).any():
        return source_mask & target_mask & canvas_mask

    visited = np.zeros_like(canvas_mask, dtype=bool)
    prev_row = np.full(canvas_mask.shape, -1, dtype=np.int32)
    prev_col = np.full(canvas_mask.shape, -1, dtype=np.int32)
    queue: deque[tuple[int, int]] = deque()
    for row, col in valid_sources:
        row_i = int(row)
        col_i = int(col)
        if visited[row_i, col_i]:
            continue
        visited[row_i, col_i] = True
        queue.append((row_i, col_i))

    end: tuple[int, int] | None = None
    while queue:
        row, col = queue.popleft()
        if valid_targets[row, col]:
            end = (row, col)
            break
        for row_delta, col_delta in STEP6_CONNECTIVITY_NEIGHBORS:
            next_row = row + row_delta
            next_col = col + col_delta
            if next_row < 0 or next_row >= canvas_mask.shape[0] or next_col < 0 or next_col >= canvas_mask.shape[1]:
                continue
            if visited[next_row, next_col] or not canvas_mask[next_row, next_col]:
                continue
            visited[next_row, next_col] = True
            prev_row[next_row, next_col] = row
            prev_col[next_row, next_col] = col
            queue.append((next_row, next_col))
    if end is None:
        return None

    path_mask = np.zeros_like(canvas_mask, dtype=bool)
    row, col = end
    while row >= 0 and col >= 0:
        path_mask[row, col] = True
        previous_row = int(prev_row[row, col])
        previous_col = int(prev_col[row, col])
        if previous_row < 0 or previous_col < 0:
            break
        row, col = previous_row, previous_col
    return path_mask


def _connect_hard_seed_components(
    *,
    canvas_mask: np.ndarray,
    hard_seed_mask: np.ndarray,
) -> tuple[np.ndarray, list[str]]:
    current_mask = hard_seed_mask.copy()
    notes: list[str] = []
    while True:
        # `current_mask` also contains the stitched corridor. If we only keep
        # `hard_seed_mask` here, the loop never observes the newly-added path
        # and can fail to converge.
        hard_components = _component_masks(current_mask)
        if len(hard_components) <= 1:
            break
        base_component = hard_components[0]
        best_path: np.ndarray | None = None
        best_cost: int | None = None
        for target_component in hard_components[1:]:
            path_mask = _shortest_path_mask(
                canvas_mask=canvas_mask,
                source_mask=base_component,
                target_mask=target_component,
            )
            if path_mask is None:
                continue
            cost = int(path_mask.sum())
            if best_cost is None or cost < best_cost:
                best_path = path_mask
                best_cost = cost
        if best_path is None:
            notes.append("hard_must_cover_disconnected")
            break
        current_mask |= best_path
    return current_mask, notes


def _connect_optional_seed_components(
    *,
    canvas_mask: np.ndarray,
    current_mask: np.ndarray,
    optional_seed_mask: np.ndarray,
) -> tuple[np.ndarray, list[str]]:
    notes: list[str] = []
    remaining_mask = optional_seed_mask & ~current_mask
    while remaining_mask.any():
        remaining_components = _component_masks(remaining_mask)
        best_path: np.ndarray | None = None
        best_component: np.ndarray | None = None
        best_cost: int | None = None
        for component in remaining_components:
            path_mask = _shortest_path_mask(
                canvas_mask=canvas_mask,
                source_mask=current_mask,
                target_mask=component,
            )
            if path_mask is None:
                continue
            cost = int(path_mask.sum())
            if best_cost is None or cost < best_cost:
                best_path = path_mask
                best_component = component
                best_cost = cost
        if best_path is None or best_component is None:
            notes.append("optional_seed_unreachable")
            break
        current_mask |= best_path
        current_mask |= best_component
        remaining_mask = optional_seed_mask & ~current_mask
    return current_mask, notes


def _hole_details(
    *,
    geometry: BaseGeometry | None,
    forbidden_geometry: BaseGeometry | None,
    allowed_geometry: BaseGeometry | None,
    cut_barrier_geometry: BaseGeometry | None = None,
) -> tuple[list[dict[str, Any]], BaseGeometry | None]:
    details: list[dict[str, Any]] = []
    hole_geometries: list[BaseGeometry] = []
    for index, hole in enumerate(_hole_polygons(geometry), start=1):
        forbidden_overlap = (
            0.0
            if forbidden_geometry is None or forbidden_geometry.is_empty
            else float(hole.intersection(forbidden_geometry).area)
        )
        hole_area = float(hole.area)
        allowed_overlap = (
            hole_area
            if allowed_geometry is None or allowed_geometry.is_empty
            else float(hole.intersection(allowed_geometry).area)
        )
        cut_overlap = (
            0.0
            if cut_barrier_geometry is None or cut_barrier_geometry.is_empty
            else float(hole.intersection(cut_barrier_geometry).area)
        )
        constraint_hole = hole_area > 0.0 and allowed_overlap / hole_area <= 0.5
        business_hole = bool(
            hole_area > 0.0
            and (
                forbidden_overlap / hole_area >= 0.5
                or cut_overlap / hole_area >= 0.5
                or constraint_hole
            )
        )
        details.append(
            {
                "hole_id": f"hole_{index:02d}",
                "area_m2": hole_area,
                "forbidden_overlap_area_m2": forbidden_overlap,
                "cut_overlap_area_m2": cut_overlap,
                "allowed_overlap_area_m2": allowed_overlap,
                "constraint_hole": constraint_hole,
                "business_hole": business_hole,
            }
        )
        hole_geometries.append(hole)
    return details, _normalize_geometry(_union_geometry(hole_geometries))


def _fill_unexpected_polygon_holes(
    geometry: BaseGeometry | None,
    *,
    forbidden_geometry: BaseGeometry | None,
    allowed_geometry: BaseGeometry | None = None,
    cut_barrier_geometry: BaseGeometry | None = None,
) -> BaseGeometry | None:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return None
    filled_polygons: list[Polygon] = []
    for polygon in _polygon_components(normalized):
        kept_interiors = []
        for ring in polygon.interiors:
            hole = Polygon(ring)
            if hole.is_empty:
                continue
            forbidden_overlap = (
                0.0
                if forbidden_geometry is None or forbidden_geometry.is_empty
                else float(hole.intersection(forbidden_geometry).area)
            )
            hole_area = float(hole.area)
            allowed_overlap = (
                hole_area
                if allowed_geometry is None or allowed_geometry.is_empty
                else float(hole.intersection(allowed_geometry).area)
            )
            cut_overlap = (
                0.0
                if cut_barrier_geometry is None or cut_barrier_geometry.is_empty
                else float(hole.intersection(cut_barrier_geometry).area)
            )
            if hole_area > 0.0 and forbidden_overlap / hole_area >= 0.5:
                kept_interiors.append(ring)
            elif hole_area > 0.0 and cut_overlap / hole_area >= 0.5:
                kept_interiors.append(ring)
            elif hole_area > 0.0 and allowed_overlap / hole_area <= 0.5:
                kept_interiors.append(ring)
        filled_polygons.append(Polygon(polygon.exterior, kept_interiors))
    return _normalize_geometry(_union_geometry(filled_polygons))


def _junction_full_fill_slit_relief(
    geometry: BaseGeometry | None,
    *,
    step5_result: T04Step5CaseResult,
    terminal_window_geometry: BaseGeometry | None,
    forbidden_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    if _junction_full_fill_unit_count(step5_result) < 2:
        return None
    normalized = _normalize_geometry(geometry)
    if normalized is None or normalized.is_empty:
        return None
    closed = _normalize_geometry(
        normalized.buffer(
            STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_RADIUS_M,
            join_style=2,
        ).buffer(
            -STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_RADIUS_M,
            join_style=2,
        )
    )
    if closed is None or closed.is_empty:
        return None
    closed = _constrain_geometry_to_case_limits(
        closed,
        drivezone_union=None,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=None,
        cut_barrier_geometry=None,
    )
    if closed is None or closed.is_empty:
        return None
    relief = _normalize_geometry(closed.difference(normalized))
    if relief is None or relief.is_empty:
        return None
    relief_area = float(relief.area)
    if (
        relief_area < STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_MIN_AREA_M2
        or relief_area > STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_MAX_AREA_M2
    ):
        return None
    forbidden_overlap = (
        0.0
        if forbidden_geometry is None or forbidden_geometry.is_empty
        else float(relief.intersection(forbidden_geometry).area)
    )
    if forbidden_overlap > STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_FORBIDDEN_TOLERANCE_M2:
        return None
    return relief


def _swsd_window_touch_close(
    geometry: BaseGeometry | None,
    *,
    step5_result: T04Step5CaseResult,
    hard_seed_geometry: BaseGeometry | None,
    terminal_window_geometry: BaseGeometry | None,
    forbidden_geometry: BaseGeometry | None,
    cut_barrier_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return None
    base_geometry = _normalize_geometry(_union_geometry([normalized, hard_seed_geometry]))
    if base_geometry is None:
        return None
    before_count = len(_polygon_components(base_geometry))
    if before_count <= 1:
        return None
    closed = _normalize_geometry(
        base_geometry.buffer(
            STEP6_SWSD_WINDOW_TOUCH_CLOSE_RADIUS_M,
            join_style=2,
        ).buffer(
            -STEP6_SWSD_WINDOW_TOUCH_CLOSE_RADIUS_M,
            join_style=2,
        )
    )
    if closed is None or closed.is_empty:
        return None
    closed = _normalize_geometry(_union_geometry([base_geometry, closed]))
    if closed is None or closed.is_empty:
        return None
    closed = _constrain_geometry_to_case_limits(
        closed,
        drivezone_union=None,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=forbidden_geometry,
        cut_barrier_geometry=cut_barrier_geometry,
    )
    if closed is None or closed.is_empty:
        return None
    if len(_polygon_components(closed)) >= before_count:
        return None
    area_delta = float(closed.difference(base_geometry).area)
    if area_delta > STEP6_SWSD_WINDOW_TOUCH_CLOSE_MAX_AREA_DELTA_M2:
        return None
    return closed


def _target_b_seed_geometry(step5_result: T04Step5CaseResult) -> BaseGeometry | None:
    return _union_geometry(
        unit.target_b_node_patch_geometry
        for unit in step5_result.unit_results
        if unit.target_b_node_patch_geometry is not None
    )


def _area_outside(container: BaseGeometry | None, geometry: BaseGeometry | None) -> float:
    normalized_geometry = _normalize_geometry(geometry)
    if normalized_geometry is None:
        return 0.0
    normalized_container = _normalize_geometry(container)
    if normalized_container is None:
        return float(getattr(normalized_geometry, "area", 0.0) or 0.0)
    return float(normalized_geometry.difference(normalized_container).area)


def _overlap_area(left: BaseGeometry | None, right: BaseGeometry | None) -> float:
    normalized_left = _normalize_geometry(left)
    normalized_right = _normalize_geometry(right)
    if normalized_left is None or normalized_right is None:
        return 0.0
    return float(normalized_left.intersection(normalized_right).area)


def _geometry_area(geometry: BaseGeometry | None) -> float:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return 0.0
    return float(getattr(normalized, "area", 0.0) or 0.0)


def _relief_constraint_audit_entry(
    *,
    relief_note: str,
    relief_geometry: BaseGeometry | None,
    before_allowed_geometry: BaseGeometry | None,
    after_allowed_geometry: BaseGeometry | None,
    before_forbidden_geometry: BaseGeometry | None,
    after_forbidden_geometry: BaseGeometry | None,
    before_cut_barrier_geometry: BaseGeometry | None,
    after_cut_barrier_geometry: BaseGeometry | None,
) -> dict[str, Any]:
    before_allowed_area = _geometry_area(before_allowed_geometry)
    after_allowed_area = _geometry_area(after_allowed_geometry)
    before_forbidden_area = _geometry_area(before_forbidden_geometry)
    after_forbidden_area = _geometry_area(after_forbidden_geometry)
    before_cut_area = _geometry_area(before_cut_barrier_geometry)
    after_cut_area = _geometry_area(after_cut_barrier_geometry)
    return {
        "relief_note": relief_note,
        "relief_area_m2": _geometry_area(relief_geometry),
        "allowed_growth_area_delta_m2": after_allowed_area - before_allowed_area,
        "forbidden_area_delta_m2": after_forbidden_area - before_forbidden_area,
        "cut_barrier_area_delta_m2": after_cut_area - before_cut_area,
        "allowed_growth_expanded": after_allowed_area > before_allowed_area + STEP6_ALLOWED_TOLERANCE_AREA_M2,
        "forbidden_domain_weakened": after_forbidden_area < before_forbidden_area - STEP6_FORBIDDEN_TOLERANCE_AREA_M2,
        "cut_barrier_weakened": after_cut_area < before_cut_area - STEP6_CUT_TOLERANCE_AREA_M2,
        "source": "step6_relief_constraint_change",
    }


def _doc_ids(values: Any) -> tuple[str, ...]:
    if not values:
        return ()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return tuple(result)


def _case_alignment_aggregate_doc(case_result: T04CaseResult) -> dict[str, Any]:
    getter = getattr(case_result, "case_alignment_aggregate_doc", None)
    if not callable(getter):
        return {}
    doc = getter()
    if isinstance(doc, dict):
        return doc
    return {}


def _case_alignment_review_reasons(
    case_alignment_aggregate: dict[str, Any],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    ambiguous_unit_ids = _doc_ids(case_alignment_aggregate.get("ambiguous_event_unit_ids"))
    review_reasons: list[str] = []
    if ambiguous_unit_ids:
        review_reasons.append("ambiguous_case_rcsd_alignment")
    return tuple(review_reasons), ambiguous_unit_ids


def _negative_mask_channel_overlap_audit(
    *,
    final_case_polygon: BaseGeometry | None,
    step5_result: T04Step5CaseResult,
    cut_barrier_geometry: BaseGeometry | None,
) -> dict[str, dict[str, Any]]:
    channels = {
        "unrelated_swsd": {
            "geometry": getattr(step5_result, "unrelated_swsd_mask_geometry", None),
            "applied_to_forbidden_domain": True,
            "tolerance_area_m2": STEP6_FORBIDDEN_TOLERANCE_AREA_M2,
        },
        "unrelated_rcsd": {
            "geometry": getattr(step5_result, "unrelated_rcsd_mask_geometry", None),
            "applied_to_forbidden_domain": True,
            "tolerance_area_m2": STEP6_FORBIDDEN_TOLERANCE_AREA_M2,
        },
        "divstrip_body": {
            "geometry": getattr(step5_result, "divstrip_body_mask_geometry", None),
            "applied_to_forbidden_domain": False,
            "tolerance_area_m2": STEP6_FORBIDDEN_TOLERANCE_AREA_M2,
        },
        "divstrip_void": {
            "geometry": getattr(step5_result, "divstrip_void_mask_geometry", None),
            "applied_to_forbidden_domain": True,
            "tolerance_area_m2": STEP6_FORBIDDEN_TOLERANCE_AREA_M2,
        },
        "forbidden_domain": {
            "geometry": getattr(step5_result, "case_forbidden_domain", None),
            "applied_to_forbidden_domain": True,
            "tolerance_area_m2": STEP6_FORBIDDEN_TOLERANCE_AREA_M2,
        },
        "terminal_cut": {
            "geometry": cut_barrier_geometry,
            "applied_to_forbidden_domain": True,
            "tolerance_area_m2": STEP6_CUT_TOLERANCE_AREA_M2,
        },
    }
    audit: dict[str, dict[str, Any]] = {}
    for channel_name, channel in channels.items():
        geometry = _normalize_geometry(channel["geometry"])
        overlap_area = _overlap_area(final_case_polygon, geometry)
        tolerance_area = float(channel["tolerance_area_m2"])
        audit[channel_name] = {
            "present": geometry is not None,
            "applied_to_forbidden_domain": bool(channel["applied_to_forbidden_domain"]),
            "overlap_area_m2": overlap_area,
            "tolerance_area_m2": tolerance_area,
            "ok": overlap_area <= tolerance_area,
        }
    return audit


def _fallback_support_geometry(step5_result: T04Step5CaseResult) -> BaseGeometry | None:
    return _normalize_geometry(
        _union_geometry(unit.fallback_support_strip_geometry for unit in step5_result.unit_results)
    )


def _unit_surface_count(step5_result: T04Step5CaseResult) -> int:
    return sum(
        1
        for unit in step5_result.unit_results
        if unit.unit_allowed_growth_domain is not None and not unit.unit_allowed_growth_domain.is_empty
    )


def _barrier_separated_case_surface_ok(
    *,
    final_case_polygon: BaseGeometry | None,
    assembly_canvas_geometry: BaseGeometry | None,
    component_count: int,
    guard_context: Step6GuardContext,
    post_checks: dict[str, Any],
    hard_must_cover_ok: bool,
    b_node_target_covered: bool,
    cut_violation: bool,
    unexpected_hole_count: int,
    case_alignment_review_reasons: tuple[str, ...],
    hard_connect_notes: tuple[str, ...],
) -> bool:
    if guard_context.no_surface_reference_guard:
        return False
    if final_case_polygon is None or final_case_polygon.is_empty or component_count <= 1:
        return False
    canvas_component_count = len(_polygon_components(assembly_canvas_geometry or GeometryCollection()))
    if canvas_component_count <= 1:
        return False
    required_checks = (
        "post_cleanup_allowed_growth_ok",
        "post_cleanup_forbidden_ok",
        "post_cleanup_terminal_cut_ok",
        "post_cleanup_lateral_limit_ok",
        "post_cleanup_negative_mask_ok",
        "post_cleanup_must_cover_ok",
    )
    if any(not bool(post_checks.get(check_name, True)) for check_name in required_checks):
        return False
    if guard_context.surface_scenario_type not in {
        SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD,
        SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
    } and not (set(hard_connect_notes) & STEP6_BARRIER_SEPARATION_RELIEF_NOTES):
        return False
    # 真实硬阻断举证：multi-component 只允许在 §1.4 A / B 两类路径下被标为 barrier-separated。
    # 必须配 bridge_negative_mask_crossing_detected = true 或某个 channel overlap > tolerance；
    # 否则按 INTERFACE_CONTRACT.md §3.7 第 336 行视为"普通多组件结果"，不允许该字段置 true。
    bridge_crossing_detected = bool(post_checks.get("bridge_negative_mask_crossing_detected", False))
    bridge_channel_overlaps = post_checks.get("bridge_negative_mask_channel_overlaps", {}) or {}
    real_bridge_overlap_area_m2 = sum(
        float((channel or {}).get("overlap_area_m2", 0.0) or 0.0)
        for channel in bridge_channel_overlaps.values()
    )
    if not bridge_crossing_detected and real_bridge_overlap_area_m2 <= STEP6_FORBIDDEN_TOLERANCE_AREA_M2:
        return False
    return bool(
        hard_must_cover_ok
        and b_node_target_covered
        and not cut_violation
        and unexpected_hole_count == 0
        and not case_alignment_review_reasons
    )


def check_post_cleanup_constraints(
    *,
    final_case_polygon: BaseGeometry | None,
    step5_result: T04Step5CaseResult,
    cut_barrier_geometry: BaseGeometry | None,
    hard_seed_geometry: BaseGeometry | None,
    guard_context: Step6GuardContext,
) -> dict[str, Any]:
    allowed_outside_area = _area_outside(step5_result.case_allowed_growth_domain, final_case_polygon)
    forbidden_overlap_area = _overlap_area(final_case_polygon, step5_result.case_forbidden_domain)
    terminal_cut_overlap_area = _overlap_area(final_case_polygon, cut_barrier_geometry)
    hard_seed_missing = _normalize_geometry(hard_seed_geometry) is None
    final_polygon = _normalize_geometry(final_case_polygon)
    must_cover_ok = bool(
        hard_seed_missing
        or (
            final_polygon is not None
            and final_polygon.buffer(1e-6).covers(hard_seed_geometry)
        )
    )
    divstrip_negative_overlap_area = _overlap_area(final_case_polygon, step5_result.divstrip_void_mask_geometry)
    negative_mask_channel_overlaps = _negative_mask_channel_overlap_audit(
        final_case_polygon=final_case_polygon,
        step5_result=step5_result,
        cut_barrier_geometry=cut_barrier_geometry,
    )
    negative_mask_conflict_channel_names = tuple(
        channel_name
        for channel_name, channel in negative_mask_channel_overlaps.items()
        if bool(channel["applied_to_forbidden_domain"]) and not bool(channel["ok"])
    )
    bridge_negative_mask_channel_overlaps = _negative_mask_channel_overlap_audit(
        final_case_polygon=step5_result.case_bridge_zone_geometry,
        step5_result=step5_result,
        cut_barrier_geometry=cut_barrier_geometry,
    )
    bridge_negative_mask_crossing_detected = any(
        not bool(bridge_negative_mask_channel_overlaps[channel]["ok"])
        for channel in ("unrelated_swsd", "unrelated_rcsd")
    )
    fallback_geometry = _fallback_support_geometry(step5_result)
    fallback_outside_allowed_area = _area_outside(step5_result.case_allowed_growth_domain, fallback_geometry)
    fallback_domain_contained = fallback_outside_allowed_area <= STEP6_ALLOWED_TOLERANCE_AREA_M2
    fallback_overexpansion_area = allowed_outside_area if guard_context.fallback_rcsdroad_localized else 0.0
    return {
        "post_cleanup_allowed_growth_ok": allowed_outside_area <= STEP6_ALLOWED_TOLERANCE_AREA_M2,
        "post_cleanup_forbidden_ok": forbidden_overlap_area <= STEP6_FORBIDDEN_TOLERANCE_AREA_M2,
        "post_cleanup_terminal_cut_ok": terminal_cut_overlap_area <= STEP6_CUT_TOLERANCE_AREA_M2,
        "post_cleanup_lateral_limit_ok": allowed_outside_area <= STEP6_ALLOWED_TOLERANCE_AREA_M2,
        "post_cleanup_negative_mask_ok": not negative_mask_conflict_channel_names,
        "post_cleanup_must_cover_ok": must_cover_ok,
        "post_cleanup_recheck_performed": True,
        "allowed_growth_outside_area_m2": allowed_outside_area,
        "terminal_cut_overlap_area_m2": terminal_cut_overlap_area,
        "lateral_limit_check_mode": "via_allowed_growth",
        "negative_mask_check_mode": "per_channel_negative_mask_overlap",
        "negative_mask_channel_overlaps": negative_mask_channel_overlaps,
        "negative_mask_conflict_channel_names": negative_mask_conflict_channel_names,
        "bridge_negative_mask_channel_overlaps": bridge_negative_mask_channel_overlaps,
        "bridge_negative_mask_crossing_detected": bridge_negative_mask_crossing_detected,
        "divstrip_negative_overlap_area_m2": divstrip_negative_overlap_area,
        "fallback_domain_contained_by_allowed_growth": fallback_domain_contained,
        "fallback_overexpansion_detected": bool(
            guard_context.fallback_rcsdroad_localized
            and fallback_overexpansion_area > STEP6_ALLOWED_TOLERANCE_AREA_M2
        ),
        "fallback_overexpansion_area_m2": fallback_overexpansion_area,
    }


def build_step6_polygon_assembly(
    case_result: T04CaseResult,
    step5_result: T04Step5CaseResult,
) -> T04Step6Result:
    guard_context = derive_step6_guard_context(step5_result)
    case_alignment_aggregate = _case_alignment_aggregate_doc(case_result)
    case_alignment_review_reasons, case_alignment_ambiguous_event_unit_ids = (
        _case_alignment_review_reasons(case_alignment_aggregate)
    )
    constraint_step5_result = step5_result
    unit_surface_count = _unit_surface_count(step5_result)
    if guard_context.no_surface_reference_guard:
        post_checks = check_post_cleanup_constraints(
            final_case_polygon=None,
            step5_result=step5_result,
            cut_barrier_geometry=None,
            hard_seed_geometry=None,
            guard_context=guard_context,
        )
        return T04Step6Result(
            case_id=case_result.case_spec.case_id,
            final_case_polygon=None,
            final_case_holes=None,
            final_case_cut_lines=_normalize_geometry(step5_result.case_terminal_cut_constraints),
            final_case_forbidden_overlap=None,
            assembly_canvas_geometry=None,
            hard_seed_geometry=None,
            weak_seed_geometry=None,
            component_count=0,
            hole_count=0,
            business_hole_count=0,
            unexpected_hole_count=0,
            hard_must_cover_ok=True,
            b_node_target_covered=True,
            forbidden_overlap_area_m2=0.0,
            cut_violation=False,
            assembly_state="assembly_failed",
            review_reasons=("no_surface_reference", *case_alignment_review_reasons),
            hard_connect_notes=(),
            optional_connect_notes=(),
            hole_details=(),
            **post_checks,
            case_alignment_review_reasons=case_alignment_review_reasons,
            case_alignment_ambiguous_event_unit_ids=case_alignment_ambiguous_event_unit_ids,
            surface_scenario_type=guard_context.surface_scenario_type,
            section_reference_source=guard_context.section_reference_source,
            surface_generation_mode=guard_context.surface_generation_mode,
            reference_point_present=guard_context.reference_point_present,
            surface_section_forward_m=guard_context.surface_section_forward_m,
            surface_section_backward_m=guard_context.surface_section_backward_m,
            surface_lateral_limit_m=guard_context.surface_lateral_limit_m,
            surface_scenario_missing=guard_context.surface_scenario_missing,
            no_surface_reference_guard=True,
            final_polygon_suppressed_by_no_surface_reference=True,
            no_virtual_reference_point_guard=guard_context.no_virtual_reference_point_guard,
            b_node_gate_applicable=False,
            b_node_gate_skip_reason="no_surface_reference",
            section_reference_window_covered=False,
            fallback_rcsdroad_ids=guard_context.fallback_rcsdroad_ids,
            fallback_rcsdroad_localized=guard_context.fallback_rcsdroad_localized,
            forbidden_domain_kept=guard_context.forbidden_domain_kept,
            divstrip_negative_mask_present=guard_context.divstrip_negative_mask_present,
            unit_surface_count=unit_surface_count,
            unit_surface_merge_performed=False,
            merge_mode="case_level_assembly",
            merged_case_surface_component_count=0,
            final_case_polygon_component_count=0,
            single_connected_case_surface_ok=False,
        )
    drivezone_union = _loaded_feature_union(case_result.case_bundle.drivezone_features)
    representative_point = case_result.case_bundle.representative_node.geometry
    assembly_source_geometry = _union_geometry(
        [
            step5_result.case_allowed_growth_domain,
            step5_result.case_must_cover_domain,
            step5_result.case_terminal_cut_constraints,
            step5_result.case_terminal_support_corridor_geometry,
            step5_result.case_bridge_zone_geometry,
        ]
    )
    grid_center, patch_size_m = _grid_center_and_patch_size(
        assembly_source_geometry,
        fallback_point=representative_point,
    )
    _validate_step6_grid_size(
        case_id=case_result.case_spec.case_id,
        patch_size_m=patch_size_m,
        resolution_m=STEP6_RESOLUTION_M,
    )
    grid = _build_grid(
        grid_center,
        patch_size_m=patch_size_m,
        resolution_m=STEP6_RESOLUTION_M,
    )

    allowed_mask = _rasterize_geometries(grid, [step5_result.case_allowed_growth_domain])
    terminal_window_geometry = step5_result.case_terminal_window_domain
    if (
        terminal_window_geometry is not None
        and not terminal_window_geometry.is_empty
        and step5_result.case_terminal_support_corridor_geometry is not None
        and not step5_result.case_terminal_support_corridor_geometry.is_empty
    ):
        terminal_window_geometry = _normalize_geometry(
            _union_geometry(
                [
                    terminal_window_geometry,
                    step5_result.case_terminal_support_corridor_geometry,
                ]
            )
        )
    if _is_swsd_section_window_surface(guard_context):
        terminal_window_geometry = _normalize_geometry(
            _union_geometry(
                [
                    terminal_window_geometry,
                    step5_result.case_allowed_growth_domain,
                    step5_result.case_must_cover_domain,
                ]
            )
        )
    forbidden_mask = _rasterize_geometries(grid, [step5_result.case_forbidden_domain])
    inter_unit_bridge_surface = _inter_unit_section_bridge_surface(step5_result)
    inter_unit_bridge_surface = _constrain_geometry_to_case_limits(
        inter_unit_bridge_surface,
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=None,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=None,
    )
    if inter_unit_bridge_surface is not None and not inter_unit_bridge_surface.is_empty:
        terminal_window_geometry = _normalize_geometry(
            _union_geometry([terminal_window_geometry, inter_unit_bridge_surface])
        )
    terminal_window_mask = (
        _rasterize_geometries(grid, [terminal_window_geometry])
        if terminal_window_geometry is not None and not terminal_window_geometry.is_empty
        else np.ones_like(allowed_mask, dtype=bool)
    )
    cut_barrier_geometry = None
    if step5_result.case_terminal_cut_constraints is not None and not step5_result.case_terminal_cut_constraints.is_empty:
        cut_barrier_geometry = step5_result.case_terminal_cut_constraints.buffer(
            STEP6_CUT_BARRIER_BUFFER_M,
            cap_style=2,
            join_style=2,
        )
        single_bridge_zone = _single_case_bridge_zone(step5_result)
        if single_bridge_zone is not None and not single_bridge_zone.is_empty:
            cut_barrier_geometry = _normalize_geometry(
                cut_barrier_geometry.difference(single_bridge_zone)
            )
        if inter_unit_bridge_surface is not None and not inter_unit_bridge_surface.is_empty:
            inter_unit_cut_relief = inter_unit_bridge_surface.buffer(
                STEP6_CUT_BARRIER_BUFFER_M,
                cap_style=2,
                join_style=2,
            )
            cut_barrier_geometry = _normalize_geometry(
                cut_barrier_geometry.difference(inter_unit_cut_relief)
            )
        if _is_swsd_section_window_surface(guard_context) and len(step5_result.unit_results) > 1:
            cut_barrier_geometry = _normalize_geometry(
                cut_barrier_geometry.difference(step5_result.case_allowed_growth_domain)
            )
    cut_mask = _rasterize_geometries(grid, [cut_barrier_geometry]) if cut_barrier_geometry is not None else np.zeros_like(allowed_mask, dtype=bool)
    assembly_canvas_mask = allowed_mask & terminal_window_mask & ~forbidden_mask & ~cut_mask
    # 连通性恢复（spec §1.4 / Bug-2 修复）：当 Step5 的 `case_allowed_growth_domain`
    # 是单连通 Polygon、但 0.5m 栅格化后被狭窄段切成多 component 时，做一次 1-iter
    # binary_close 把 ≤1m 的"假断开"缝合回去；再用 `allowed & terminal_window
    # & ~forbidden & ~cut` 重新裁剪，确保不会越过任何负向掩膜或 allowed_growth 范围。
    # 目的：让 SWSD-junction-window 与 RCSD-junction-window 等 narrow allowed_growth
    # 场景在 §1.4 barrier-aware grow 下产生天然单连通面；不影响真正被掩膜阻断的多 component。
    case_allowed_growth_domain = step5_result.case_allowed_growth_domain
    if (
        case_allowed_growth_domain is not None
        and not case_allowed_growth_domain.is_empty
        and case_allowed_growth_domain.geom_type == "Polygon"
        and assembly_canvas_mask.any()
    ):
        canvas_components_pre = _component_masks(assembly_canvas_mask)
        if len(canvas_components_pre) > 1:
            closed_mask = (
                _binary_close(assembly_canvas_mask, iterations=1)
                & allowed_mask
                & terminal_window_mask
                & ~forbidden_mask
                & ~cut_mask
            )
            if len(_component_masks(closed_mask)) < len(canvas_components_pre):
                assembly_canvas_mask = closed_mask
    assembly_canvas_geometry = _constrain_geometry_to_case_limits(
        _mask_to_geometry(assembly_canvas_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=constraint_step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )

    core_hard_seed_geometry = _core_must_cover_geometry(step5_result)
    case_must_requested_mask = _rasterize_geometries(grid, [step5_result.case_must_cover_domain])
    hard_seed_requested_mask = case_must_requested_mask
    bridge_requested_mask = _rasterize_geometries(grid, [_single_case_bridge_zone(step5_result)])
    inter_unit_bridge_requested_mask = _rasterize_geometries(grid, [inter_unit_bridge_surface])
    full_fill_target_geometry = _full_fill_target_geometry(step5_result)
    if full_fill_target_geometry is not None and not full_fill_target_geometry.is_empty:
        core_seed_requested_mask = _rasterize_geometries(grid, [core_hard_seed_geometry])
        full_fill_requested_mask = _rasterize_geometries(grid, [full_fill_target_geometry])
        full_fill_canvas_mask = full_fill_requested_mask & assembly_canvas_mask
        core_seed_canvas_mask = core_seed_requested_mask & assembly_canvas_mask
        if _is_swsd_section_window_surface(guard_context) or (
            _is_no_main_section_window_surface(guard_context)
            and not (full_fill_canvas_mask & core_seed_canvas_mask).any()
        ):
            effective_full_fill_mask = full_fill_canvas_mask
        else:
            effective_full_fill_mask = _extract_seed_component(
                full_fill_canvas_mask,
                core_seed_canvas_mask,
            )
        hard_seed_requested_mask = (
            core_seed_requested_mask
            | effective_full_fill_mask
            | bridge_requested_mask
            | inter_unit_bridge_requested_mask
        )
    hard_seed_mask = hard_seed_requested_mask & assembly_canvas_mask
    if inter_unit_bridge_requested_mask.any() and bridge_requested_mask.any():
        hard_seed_mask = _extract_seed_component(
            hard_seed_mask,
            bridge_requested_mask | inter_unit_bridge_requested_mask,
        )
    hard_seed_geometry = _constrain_geometry_to_case_limits(
        _mask_to_geometry(hard_seed_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )
    if _is_swsd_section_window_surface(guard_context):
        hard_seed_geometry = _constrain_geometry_to_case_limits(
            _normalize_geometry(
                _union_geometry([hard_seed_geometry, step5_result.case_must_cover_domain])
            ),
            drivezone_union=drivezone_union,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        hard_seed_mask = _rasterize_geometries(grid, [hard_seed_geometry]) & assembly_canvas_mask
    if _is_no_main_section_window_surface(guard_context) and not _is_swsd_section_window_surface(guard_context):
        hard_seed_geometry = _seed_dominant_polygon_component(
            hard_seed_geometry,
            core_hard_seed_geometry,
        )
        hard_seed_mask = _rasterize_geometries(grid, [hard_seed_geometry]) & assembly_canvas_mask
    if (
        inter_unit_bridge_surface is not None
        and not inter_unit_bridge_surface.is_empty
        and not _is_swsd_section_window_surface(guard_context)
    ):
        hard_seed_geometry = _seed_dominant_polygon_component(
            hard_seed_geometry,
            _union_geometry([step5_result.case_bridge_zone_geometry, inter_unit_bridge_surface]),
        )
        hard_seed_mask = _rasterize_geometries(grid, [hard_seed_geometry]) & assembly_canvas_mask
    single_component_surface_seed = _uses_single_component_surface_seed(step5_result)
    if single_component_surface_seed:
        hard_seed_geometry = _seed_dominant_polygon_component(
            hard_seed_geometry,
            core_hard_seed_geometry,
        )
        hard_seed_mask = _rasterize_geometries(grid, [hard_seed_geometry]) & assembly_canvas_mask
    target_b_seed_geometry = _target_b_seed_geometry(step5_result)
    target_b_requested_mask = _rasterize_geometries(grid, [target_b_seed_geometry])
    target_b_mask = target_b_requested_mask & assembly_canvas_mask
    target_b_effective_geometry = _constrain_geometry_to_case_limits(
        _mask_to_geometry(target_b_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )
    weak_seed_geometry = _union_geometry(
        [
            target_b_seed_geometry,
            step5_result.case_bridge_zone_geometry,
        ]
    )
    weak_seed_requested_mask = _rasterize_geometries(grid, [weak_seed_geometry])
    weak_seed_mask = weak_seed_requested_mask & assembly_canvas_mask
    weak_seed_effective_geometry = _constrain_geometry_to_case_limits(
        _mask_to_geometry(weak_seed_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )

    current_mask, hard_connect_notes = _connect_hard_seed_components(
        canvas_mask=assembly_canvas_mask,
        hard_seed_mask=hard_seed_mask,
    )
    current_mask, optional_connect_notes = _connect_optional_seed_components(
        canvas_mask=assembly_canvas_mask,
        current_mask=current_mask,
        optional_seed_mask=weak_seed_mask,
    )
    relief_constraint_audit_entries: list[dict[str, Any]] = []
    current_mask |= hard_seed_mask
    current_mask &= assembly_canvas_mask
    if current_mask.any():
        current_mask = _binary_close(current_mask, iterations=STEP6_CLOSE_ITERATIONS) & assembly_canvas_mask
    assembled_mask = (
        _extract_seed_component(assembly_canvas_mask, current_mask)
        if current_mask.any()
        else np.zeros_like(assembly_canvas_mask, dtype=bool)
    )

    final_case_polygon = _constrain_geometry_to_case_limits(
        _mask_to_geometry(assembled_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )
    if final_case_polygon is not None and not final_case_polygon.is_empty:
        final_case_polygon = _normalize_geometry(
            _fill_small_polygon_holes(
                final_case_polygon or GeometryCollection(),
                max_hole_area_m2=POLYGON_SMALL_HOLE_AREA_M2,
            )
        )
    cut_checked_polygon = final_case_polygon
    if final_case_polygon is not None and not final_case_polygon.is_empty:
        final_case_polygon = _fill_unexpected_polygon_holes(
            final_case_polygon,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
    if final_case_polygon is not None and not final_case_polygon.is_empty:
        final_case_polygon = _constrain_geometry_to_case_limits(
            final_case_polygon,
            drivezone_union=drivezone_union,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
    if (
        _is_swsd_section_window_surface(guard_context)
        and final_case_polygon is not None
        and not final_case_polygon.is_empty
        and hard_seed_geometry is not None
        and not hard_seed_geometry.is_empty
        and not final_case_polygon.buffer(1e-6).covers(hard_seed_geometry)
    ):
        final_case_polygon = _constrain_geometry_to_case_limits(
            _normalize_geometry(_union_geometry([final_case_polygon, hard_seed_geometry])),
            drivezone_union=drivezone_union,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
    if single_component_surface_seed:
        final_case_polygon = _seed_dominant_polygon_component(
            final_case_polygon,
            hard_seed_geometry,
        )
    if (
        inter_unit_bridge_surface is not None
        and not inter_unit_bridge_surface.is_empty
        and not _is_swsd_section_window_surface(guard_context)
    ):
        final_case_polygon = _seed_dominant_polygon_component(
            final_case_polygon,
            _union_geometry([step5_result.case_bridge_zone_geometry, inter_unit_bridge_surface]),
        )
        final_case_polygon = _fill_unexpected_polygon_holes(
            final_case_polygon,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        final_case_polygon = _constrain_geometry_to_case_limits(
            final_case_polygon,
            drivezone_union=drivezone_union,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
    if final_case_polygon is not None and not final_case_polygon.is_empty:
        final_case_polygon = _fill_unexpected_polygon_holes(
            final_case_polygon,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
    cut_checked_polygon = final_case_polygon
    if (
        guard_context.surface_scenario_type == SCENARIO_MAIN_WITH_RCSD
        and final_case_polygon is not None
        and not final_case_polygon.is_empty
    ):
        dominant_relief_bridge = _dominant_component_relief_bridge(
            final_case_polygon,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        if dominant_relief_bridge is not None and not dominant_relief_bridge.is_empty:
            before_forbidden_geometry = constraint_step5_result.case_forbidden_domain
            before_cut_barrier_geometry = cut_barrier_geometry
            relieved_forbidden_geometry = (
                None
                if before_forbidden_geometry is None
                else _normalize_geometry(
                    before_forbidden_geometry.difference(dominant_relief_bridge)
                )
            )
            constraint_step5_result = replace(
                constraint_step5_result,
                case_forbidden_domain=relieved_forbidden_geometry,
            )
            if cut_barrier_geometry is not None and not cut_barrier_geometry.is_empty:
                cut_barrier_geometry = _normalize_geometry(
                    cut_barrier_geometry.difference(dominant_relief_bridge)
                )
            relief_constraint_audit_entries.append(
                _relief_constraint_audit_entry(
                    relief_note="dominant_component_relief_bridge",
                    relief_geometry=dominant_relief_bridge,
                    before_allowed_geometry=step5_result.case_allowed_growth_domain,
                    after_allowed_geometry=step5_result.case_allowed_growth_domain,
                    before_forbidden_geometry=before_forbidden_geometry,
                    after_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                    before_cut_barrier_geometry=before_cut_barrier_geometry,
                    after_cut_barrier_geometry=cut_barrier_geometry,
                )
            )
            final_case_polygon = _constrain_geometry_to_case_limits(
                _normalize_geometry(_union_geometry([final_case_polygon, dominant_relief_bridge])),
                drivezone_union=drivezone_union,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                terminal_window_geometry=terminal_window_geometry,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            final_case_polygon = _fill_unexpected_polygon_holes(
                final_case_polygon,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            cut_checked_polygon = final_case_polygon
            hard_connect_notes.append("dominant_component_relief_bridge")

    if (
        guard_context.surface_scenario_type == SCENARIO_MAIN_WITH_RCSD
        and final_case_polygon is not None
        and not final_case_polygon.is_empty
    ):
        cut_sliver_relief = _cut_sliver_hole_relief(
            final_case_polygon,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        if cut_sliver_relief is not None and not cut_sliver_relief.is_empty:
            before_cut_barrier_geometry = cut_barrier_geometry
            if cut_barrier_geometry is not None and not cut_barrier_geometry.is_empty:
                cut_barrier_geometry = _normalize_geometry(cut_barrier_geometry.difference(cut_sliver_relief))
            relief_constraint_audit_entries.append(
                _relief_constraint_audit_entry(
                    relief_note="cut_sliver_hole_relief",
                    relief_geometry=cut_sliver_relief,
                    before_allowed_geometry=step5_result.case_allowed_growth_domain,
                    after_allowed_geometry=step5_result.case_allowed_growth_domain,
                    before_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                    after_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                    before_cut_barrier_geometry=before_cut_barrier_geometry,
                    after_cut_barrier_geometry=cut_barrier_geometry,
                )
            )
            final_case_polygon = _constrain_geometry_to_case_limits(
                _normalize_geometry(_union_geometry([final_case_polygon, cut_sliver_relief])),
                drivezone_union=drivezone_union,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                terminal_window_geometry=terminal_window_geometry,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            final_case_polygon = _fill_unexpected_polygon_holes(
                final_case_polygon,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            cut_checked_polygon = final_case_polygon
            hard_connect_notes.append("cut_sliver_hole_relief")

    if (
        guard_context.surface_scenario_type == SCENARIO_MAIN_WITH_RCSD
        and "dominant_component_relief_bridge" not in hard_connect_notes
        and final_case_polygon is not None
        and not final_case_polygon.is_empty
    ):
        dominant_relief_bridge = _dominant_component_relief_bridge(
            final_case_polygon,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        if dominant_relief_bridge is not None and not dominant_relief_bridge.is_empty:
            before_forbidden_geometry = constraint_step5_result.case_forbidden_domain
            before_cut_barrier_geometry = cut_barrier_geometry
            relieved_forbidden_geometry = (
                None
                if before_forbidden_geometry is None
                else _normalize_geometry(
                    before_forbidden_geometry.difference(dominant_relief_bridge)
                )
            )
            constraint_step5_result = replace(
                constraint_step5_result,
                case_forbidden_domain=relieved_forbidden_geometry,
            )
            if cut_barrier_geometry is not None and not cut_barrier_geometry.is_empty:
                cut_barrier_geometry = _normalize_geometry(
                    cut_barrier_geometry.difference(dominant_relief_bridge)
                )
            relief_constraint_audit_entries.append(
                _relief_constraint_audit_entry(
                    relief_note="post_cut_dominant_component_relief_bridge",
                    relief_geometry=dominant_relief_bridge,
                    before_allowed_geometry=step5_result.case_allowed_growth_domain,
                    after_allowed_geometry=step5_result.case_allowed_growth_domain,
                    before_forbidden_geometry=before_forbidden_geometry,
                    after_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                    before_cut_barrier_geometry=before_cut_barrier_geometry,
                    after_cut_barrier_geometry=cut_barrier_geometry,
                )
            )
            final_case_polygon = _constrain_geometry_to_case_limits(
                _normalize_geometry(_union_geometry([final_case_polygon, dominant_relief_bridge])),
                drivezone_union=drivezone_union,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                terminal_window_geometry=terminal_window_geometry,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            final_case_polygon = _fill_unexpected_polygon_holes(
                final_case_polygon,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            cut_checked_polygon = final_case_polygon
            hard_connect_notes.append("post_cut_dominant_component_relief_bridge")

    if final_case_polygon is not None and not final_case_polygon.is_empty:
        slit_relief = _junction_full_fill_slit_relief(
            final_case_polygon,
            step5_result=step5_result,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
        )
        if slit_relief is not None and not slit_relief.is_empty:
            before_cut_barrier_geometry = cut_barrier_geometry
            next_cut_barrier_geometry = cut_barrier_geometry
            if cut_barrier_geometry is not None and not cut_barrier_geometry.is_empty:
                next_cut_barrier_geometry = _normalize_geometry(cut_barrier_geometry.difference(slit_relief))
            relieved_polygon = _constrain_geometry_to_case_limits(
                _normalize_geometry(_union_geometry([final_case_polygon, slit_relief])),
                drivezone_union=drivezone_union,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                terminal_window_geometry=terminal_window_geometry,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                cut_barrier_geometry=next_cut_barrier_geometry,
            )
            relieved_polygon = _fill_unexpected_polygon_holes(
                relieved_polygon,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                cut_barrier_geometry=next_cut_barrier_geometry,
            )
            relief_preserves_must_cover = (
                hard_seed_geometry is None
                or hard_seed_geometry.is_empty
                or (
                    relieved_polygon is not None
                    and not relieved_polygon.is_empty
                    and relieved_polygon.buffer(1e-6).covers(hard_seed_geometry)
                )
            )
            if relief_preserves_must_cover:
                relief_constraint_audit_entries.append(
                    _relief_constraint_audit_entry(
                        relief_note="junction_full_fill_slit_relief",
                        relief_geometry=slit_relief,
                        before_allowed_geometry=step5_result.case_allowed_growth_domain,
                        after_allowed_geometry=step5_result.case_allowed_growth_domain,
                        before_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                        after_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                        before_cut_barrier_geometry=before_cut_barrier_geometry,
                        after_cut_barrier_geometry=next_cut_barrier_geometry,
                    )
                )
                cut_barrier_geometry = next_cut_barrier_geometry
                final_case_polygon = relieved_polygon
                cut_checked_polygon = final_case_polygon
                hard_connect_notes.append("junction_full_fill_slit_relief")

    if (
        _is_swsd_section_window_surface(guard_context)
        and final_case_polygon is not None
        and not final_case_polygon.is_empty
    ):
        closed_polygon = _swsd_window_touch_close(
            final_case_polygon,
            step5_result=step5_result,
            hard_seed_geometry=hard_seed_geometry,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        if closed_polygon is not None and not closed_polygon.is_empty:
            final_case_polygon = closed_polygon
            cut_checked_polygon = final_case_polygon
            hard_connect_notes.append("swsd_window_touch_close")

    component_count = len(_polygon_components(final_case_polygon or GeometryCollection()))
    if component_count > 1 and final_case_polygon is not None and not final_case_polygon.is_empty:
        late_relief_bridge: BaseGeometry | None = None
        late_relief_note = ""
        if guard_context.surface_scenario_type == SCENARIO_MAIN_WITH_RCSD:
            late_relief_bridge = _dominant_component_relief_bridge(
                final_case_polygon,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                terminal_window_geometry=terminal_window_geometry,
                cut_barrier_geometry=cut_barrier_geometry,
                use_terminal_window=False,
            )
            late_relief_note = "late_dominant_component_relief_bridge"
        elif guard_context.surface_scenario_type in {SCENARIO_MAIN_WITHOUT_RCSD, "main_evidence_without_rcsd"}:
            late_relief_bridge = _relaxed_canvas_component_relief_bridge(
                final_case_polygon,
                grid=grid,
                relaxed_canvas_mask=allowed_mask & ~forbidden_mask & ~cut_mask,
            )
            late_relief_note = "main_without_rcsd_component_relief_bridge"
        if late_relief_bridge is not None and not late_relief_bridge.is_empty:
            before_allowed_geometry = step5_result.case_allowed_growth_domain
            before_forbidden_geometry = constraint_step5_result.case_forbidden_domain
            before_cut_barrier_geometry = cut_barrier_geometry
            if guard_context.surface_scenario_type == SCENARIO_MAIN_WITHOUT_RCSD:
                relieved_allowed_geometry = _normalize_geometry(
                    _union_geometry([step5_result.case_allowed_growth_domain, late_relief_bridge])
                )
                step5_result = replace(step5_result, case_allowed_growth_domain=relieved_allowed_geometry)
                constraint_step5_result = replace(
                    constraint_step5_result,
                    case_allowed_growth_domain=relieved_allowed_geometry,
                )
                terminal_window_geometry = _normalize_geometry(
                    _union_geometry([terminal_window_geometry, late_relief_bridge])
                )
            relieved_forbidden_geometry = (
                None
                if constraint_step5_result.case_forbidden_domain is None
                else _normalize_geometry(
                    constraint_step5_result.case_forbidden_domain.difference(late_relief_bridge)
                )
            )
            constraint_step5_result = replace(
                constraint_step5_result,
                case_forbidden_domain=relieved_forbidden_geometry,
            )
            if cut_barrier_geometry is not None and not cut_barrier_geometry.is_empty:
                cut_barrier_geometry = _normalize_geometry(
                    cut_barrier_geometry.difference(late_relief_bridge)
                )
            relief_constraint_audit_entries.append(
                _relief_constraint_audit_entry(
                    relief_note=late_relief_note,
                    relief_geometry=late_relief_bridge,
                    before_allowed_geometry=before_allowed_geometry,
                    after_allowed_geometry=step5_result.case_allowed_growth_domain,
                    before_forbidden_geometry=before_forbidden_geometry,
                    after_forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                    before_cut_barrier_geometry=before_cut_barrier_geometry,
                    after_cut_barrier_geometry=cut_barrier_geometry,
                )
            )
            final_case_polygon = _constrain_geometry_to_case_limits(
                _normalize_geometry(_union_geometry([final_case_polygon, late_relief_bridge])),
                drivezone_union=drivezone_union,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                terminal_window_geometry=terminal_window_geometry,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            final_case_polygon = _fill_unexpected_polygon_holes(
                final_case_polygon,
                forbidden_geometry=constraint_step5_result.case_forbidden_domain,
                allowed_geometry=step5_result.case_allowed_growth_domain,
                cut_barrier_geometry=cut_barrier_geometry,
            )
            cut_checked_polygon = final_case_polygon
            hard_connect_notes.append(late_relief_note)
            component_count = len(_polygon_components(final_case_polygon or GeometryCollection()))

    if final_case_polygon is not None and not final_case_polygon.is_empty:
        final_case_polygon = _constrain_geometry_to_case_limits(
            final_case_polygon,
            drivezone_union=drivezone_union,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=constraint_step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
        cut_checked_polygon = final_case_polygon
        component_count = len(_polygon_components(final_case_polygon or GeometryCollection()))
    post_check_step5_result = constraint_step5_result
    hole_details, final_case_holes = _hole_details(
        geometry=final_case_polygon,
        forbidden_geometry=post_check_step5_result.case_forbidden_domain,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )
    business_hole_count = sum(1 for item in hole_details if bool(item["business_hole"]))
    unexpected_hole_count = sum(1 for item in hole_details if not bool(item["business_hole"]))
    final_case_forbidden_overlap = _normalize_geometry(
        None
        if final_case_polygon is None
        or final_case_polygon.is_empty
        or post_check_step5_result.case_forbidden_domain is None
        else final_case_polygon.intersection(post_check_step5_result.case_forbidden_domain)
    )
    forbidden_overlap_area_m2 = float(
        getattr(final_case_forbidden_overlap, "area", 0.0) or 0.0
    )
    cut_violation = False
    if cut_checked_polygon is not None and not cut_checked_polygon.is_empty and cut_barrier_geometry is not None:
        cut_violation = (
            float(cut_checked_polygon.intersection(cut_barrier_geometry).area)
            > STEP6_CUT_TOLERANCE_AREA_M2
        )

    hard_must_cover_ok = bool(
        final_case_polygon is not None
        and not final_case_polygon.is_empty
        and hard_seed_geometry is not None
        and final_case_polygon.buffer(1e-6).covers(hard_seed_geometry)
    )
    target_b_present = bool(
        target_b_effective_geometry is not None
        and not target_b_effective_geometry.is_empty
    )
    b_node_gate_applicable = True
    b_node_gate_skip_reason = ""
    if not target_b_present and _is_swsd_only_surface(guard_context):
        b_node_gate_applicable = False
        b_node_gate_skip_reason = "swsd_only_without_b_target"
    elif guard_context.surface_scenario_type == SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD:
        b_node_gate_applicable = False
        b_node_gate_skip_reason = "no_main_swsd_rcsdroad_fallback"

    b_node_target_covered = True
    if not b_node_gate_applicable:
        b_node_target_covered = True
    elif final_case_polygon is None or final_case_polygon.is_empty:
        b_node_target_covered = False
    elif target_b_present and not final_case_polygon.buffer(1e-6).covers(target_b_effective_geometry):
        b_node_target_covered = False
    section_reference_window_covered = True
    if _is_swsd_section_window_surface(guard_context):
        section_reference_window_covered = bool(
            final_case_polygon is not None
            and not final_case_polygon.is_empty
            and hard_seed_geometry is not None
            and not hard_seed_geometry.is_empty
            and final_case_polygon.buffer(1e-6).covers(hard_seed_geometry)
        )
    post_checks = check_post_cleanup_constraints(
        final_case_polygon=final_case_polygon,
        step5_result=post_check_step5_result,
        cut_barrier_geometry=cut_barrier_geometry,
        hard_seed_geometry=hard_seed_geometry,
        guard_context=guard_context,
    )
    hard_must_cover_ok = bool(post_checks["post_cleanup_must_cover_ok"])
    barrier_separated_case_surface_ok = _barrier_separated_case_surface_ok(
        final_case_polygon=final_case_polygon,
        assembly_canvas_geometry=assembly_canvas_geometry,
        component_count=component_count,
        guard_context=guard_context,
        post_checks=post_checks,
        hard_must_cover_ok=hard_must_cover_ok,
        b_node_target_covered=b_node_target_covered,
        cut_violation=cut_violation,
        unexpected_hole_count=unexpected_hole_count,
        case_alignment_review_reasons=case_alignment_review_reasons,
        hard_connect_notes=tuple(hard_connect_notes),
    )

    review_reasons: list[str] = []
    if final_case_polygon is None or final_case_polygon.is_empty:
        review_reasons.append("assembly_failed")
    if (
        component_count != 1
        and final_case_polygon is not None
        and not final_case_polygon.is_empty
    ):
        review_reasons.append("multi_component_result")
    if not hard_must_cover_ok:
        review_reasons.append("hard_must_cover_disconnected")
    if not bool(post_checks["post_cleanup_allowed_growth_ok"]):
        review_reasons.append("allowed_growth_conflict")
    if forbidden_overlap_area_m2 > STEP6_FORBIDDEN_TOLERANCE_AREA_M2:
        review_reasons.append("forbidden_conflict")
    if cut_violation:
        review_reasons.append("terminal_cut_conflict")
    if not bool(post_checks["post_cleanup_lateral_limit_ok"]):
        review_reasons.append("lateral_limit_conflict")
    if not bool(post_checks["post_cleanup_negative_mask_ok"]):
        review_reasons.append("negative_mask_conflict")
    if bool(post_checks["fallback_overexpansion_detected"]):
        review_reasons.append("fallback_overexpansion")
    if unexpected_hole_count > 0:
        review_reasons.append("unexpected_hole_present")
    if b_node_gate_applicable and not b_node_target_covered:
        review_reasons.append("b_node_not_covered")
    review_reasons.extend(case_alignment_review_reasons)
    review_reasons = list(dict.fromkeys(review_reasons))

    if not review_reasons:
        assembly_state = "assembled"
    elif all(reason == "b_node_not_covered" for reason in review_reasons):
        assembly_state = "assembled_with_review"
    else:
        assembly_state = "assembly_failed"

    return T04Step6Result(
        case_id=case_result.case_spec.case_id,
        final_case_polygon=final_case_polygon,
        final_case_holes=final_case_holes,
        final_case_cut_lines=_normalize_geometry(step5_result.case_terminal_cut_constraints),
        final_case_forbidden_overlap=final_case_forbidden_overlap,
        assembly_canvas_geometry=assembly_canvas_geometry,
        hard_seed_geometry=hard_seed_geometry,
        weak_seed_geometry=weak_seed_effective_geometry,
        component_count=component_count,
        hole_count=len(hole_details),
        business_hole_count=business_hole_count,
        unexpected_hole_count=unexpected_hole_count,
        hard_must_cover_ok=hard_must_cover_ok,
        b_node_target_covered=b_node_target_covered,
        b_node_gate_applicable=b_node_gate_applicable,
        b_node_gate_skip_reason=b_node_gate_skip_reason,
        section_reference_window_covered=section_reference_window_covered,
        forbidden_overlap_area_m2=forbidden_overlap_area_m2,
        cut_violation=cut_violation,
        assembly_state=assembly_state,
        review_reasons=tuple(review_reasons),
        hard_connect_notes=tuple(hard_connect_notes),
        optional_connect_notes=tuple(optional_connect_notes),
        hole_details=tuple(hole_details),
        relief_constraint_audit_entries=tuple(relief_constraint_audit_entries),
        **post_checks,
        case_alignment_review_reasons=case_alignment_review_reasons,
        case_alignment_ambiguous_event_unit_ids=case_alignment_ambiguous_event_unit_ids,
        surface_scenario_type=guard_context.surface_scenario_type,
        section_reference_source=guard_context.section_reference_source,
        surface_generation_mode=guard_context.surface_generation_mode,
        reference_point_present=guard_context.reference_point_present,
        surface_section_forward_m=guard_context.surface_section_forward_m,
        surface_section_backward_m=guard_context.surface_section_backward_m,
        surface_lateral_limit_m=guard_context.surface_lateral_limit_m,
        surface_scenario_missing=guard_context.surface_scenario_missing,
        no_surface_reference_guard=guard_context.no_surface_reference_guard,
        final_polygon_suppressed_by_no_surface_reference=False,
        no_virtual_reference_point_guard=guard_context.no_virtual_reference_point_guard,
        fallback_rcsdroad_ids=guard_context.fallback_rcsdroad_ids,
        fallback_rcsdroad_localized=guard_context.fallback_rcsdroad_localized,
        forbidden_domain_kept=guard_context.forbidden_domain_kept,
        divstrip_negative_mask_present=guard_context.divstrip_negative_mask_present,
        unit_surface_count=unit_surface_count,
        unit_surface_merge_performed=False,
        merge_mode="case_level_assembly",
        merged_case_surface_component_count=component_count,
        final_case_polygon_component_count=component_count,
        single_connected_case_surface_ok=component_count == 1,
        barrier_separated_case_surface_ok=barrier_separated_case_surface_ok,
    )


__all__ = [
    "Step6GuardContext",
    "T04Step6Result",
    "build_step6_polygon_assembly",
    "check_post_cleanup_constraints",
    "derive_step6_guard_context",
]
