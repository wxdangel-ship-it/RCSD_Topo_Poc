from __future__ import annotations

from collections import deque
from typing import Any

import numpy as np
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from ._rcsd_selection_support import _normalize_geometry
from ._runtime_types_io import DEFAULT_PATCH_SIZE_M, _mask_to_geometry, _rasterize_geometries

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


__all__ = [
    "STEP6_ALLOWED_TOLERANCE_AREA_M2",
    "STEP6_BARRIER_SEPARATION_RELIEF_NOTES",
    "STEP6_CLOSE_ITERATIONS",
    "STEP6_CONNECTIVITY_NEIGHBORS",
    "STEP6_CUT_BARRIER_BUFFER_M",
    "STEP6_CUT_TOLERANCE_AREA_M2",
    "STEP6_FORBIDDEN_TOLERANCE_AREA_M2",
    "STEP6_GRID_MARGIN_M",
    "STEP6_INTER_UNIT_SECTION_BRIDGE_BUFFER_M",
    "STEP6_INTER_UNIT_SECTION_BRIDGE_MAX_DISTANCE_M",
    "STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_FORBIDDEN_TOLERANCE_M2",
    "STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_MAX_AREA_M2",
    "STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_MIN_AREA_M2",
    "STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_RADIUS_M",
    "STEP6_MAX_GRID_SIDE_CELLS",
    "STEP6_RESOLUTION_M",
    "STEP6_SWSD_WINDOW_TOUCH_CLOSE_MAX_AREA_DELTA_M2",
    "STEP6_SWSD_WINDOW_TOUCH_CLOSE_RADIUS_M",
    "_component_masks",
    "_connect_hard_seed_components",
    "_connect_optional_seed_components",
    "_grid_center_and_patch_size",
    "_relaxed_canvas_component_relief_bridge",
    "_shortest_path_mask",
    "_validate_step6_grid_size",
]
