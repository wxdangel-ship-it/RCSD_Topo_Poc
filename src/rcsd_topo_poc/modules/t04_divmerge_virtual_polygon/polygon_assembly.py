from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import numpy as np
from shapely.geometry import GeometryCollection, MultiPolygon, Point, Polygon
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
from .support_domain import T04Step5CaseResult, T04Step5UnitResult


STEP6_GRID_MARGIN_M = 30.0
STEP6_RESOLUTION_M = 0.5
STEP6_MAX_GRID_SIDE_CELLS = 2000
STEP6_CUT_BARRIER_BUFFER_M = 0.75
STEP6_CONNECTIVITY_NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1))
STEP6_CLOSE_ITERATIONS = 1
STEP6_FORBIDDEN_TOLERANCE_AREA_M2 = 1e-6
STEP6_CUT_TOLERANCE_AREA_M2 = 1e-6


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


def _loaded_feature_union(features: Sequence[Any]) -> BaseGeometry | None:
    return _union_geometry(getattr(feature, "geometry", None) for feature in features)


def _clip_to_drivezone(geometry: BaseGeometry | None, drivezone_union: BaseGeometry | None) -> BaseGeometry | None:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return None
    if drivezone_union is None or drivezone_union.is_empty:
        return normalized
    return _normalize_geometry(normalized.intersection(drivezone_union))


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


def _hole_polygons(geometry: BaseGeometry | None) -> list[Polygon]:
    holes: list[Polygon] = []
    for polygon in _polygon_components(geometry or GeometryCollection()):
        for ring in polygon.interiors:
            hole = Polygon(ring)
            if not hole.is_empty:
                holes.append(hole)
    return holes


def _hole_details(
    *,
    geometry: BaseGeometry | None,
    forbidden_geometry: BaseGeometry | None,
    allowed_geometry: BaseGeometry | None,
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
        constraint_hole = hole_area > 0.0 and allowed_overlap / hole_area <= 0.5
        business_hole = bool(
            hole_area > 0.0
            and (
                forbidden_overlap / hole_area >= 0.5
                or constraint_hole
            )
        )
        details.append(
            {
                "hole_id": f"hole_{index:02d}",
                "area_m2": hole_area,
                "forbidden_overlap_area_m2": forbidden_overlap,
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
            if hole_area > 0.0 and forbidden_overlap / hole_area >= 0.5:
                kept_interiors.append(ring)
        filled_polygons.append(Polygon(polygon.exterior, kept_interiors))
    return _normalize_geometry(_union_geometry(filled_polygons))


def _target_b_seed_geometry(step5_result: T04Step5CaseResult) -> BaseGeometry | None:
    return _union_geometry(
        unit.target_b_node_patch_geometry
        for unit in step5_result.unit_results
        if unit.target_b_node_patch_geometry is not None
    )


@dataclass(frozen=True)
class T04Step6Result:
    case_id: str
    final_case_polygon: BaseGeometry | None
    final_case_holes: BaseGeometry | None
    final_case_cut_lines: BaseGeometry | None
    final_case_forbidden_overlap: BaseGeometry | None
    assembly_canvas_geometry: BaseGeometry | None
    hard_seed_geometry: BaseGeometry | None
    weak_seed_geometry: BaseGeometry | None
    component_count: int
    hole_count: int
    business_hole_count: int
    unexpected_hole_count: int
    hard_must_cover_ok: bool
    b_node_target_covered: bool
    forbidden_overlap_area_m2: float
    cut_violation: bool
    assembly_state: str
    review_reasons: tuple[str, ...]
    hard_connect_notes: tuple[str, ...]
    optional_connect_notes: tuple[str, ...]
    hole_details: tuple[dict[str, Any], ...]

    def to_status_doc(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "assembly_state": self.assembly_state,
            "review_reasons": list(self.review_reasons),
            "component_count": self.component_count,
            "hole_count": self.hole_count,
            "business_hole_count": self.business_hole_count,
            "unexpected_hole_count": self.unexpected_hole_count,
            "hard_must_cover_ok": self.hard_must_cover_ok,
            "b_node_target_covered": self.b_node_target_covered,
            "forbidden_overlap_area_m2": self.forbidden_overlap_area_m2,
            "cut_violation": self.cut_violation,
            "final_case_polygon": _geometry_summary(self.final_case_polygon),
            "final_case_holes": _geometry_summary(self.final_case_holes),
            "final_case_cut_lines": _geometry_summary(self.final_case_cut_lines),
            "final_case_forbidden_overlap": _geometry_summary(self.final_case_forbidden_overlap),
        }

    def to_audit_doc(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "assembly_canvas_geometry": _geometry_summary(self.assembly_canvas_geometry),
            "hard_seed_geometry": _geometry_summary(self.hard_seed_geometry),
            "weak_seed_geometry": _geometry_summary(self.weak_seed_geometry),
            "hard_connect_notes": list(self.hard_connect_notes),
            "optional_connect_notes": list(self.optional_connect_notes),
            "hole_details": [dict(item) for item in self.hole_details],
        }


def build_step6_polygon_assembly(
    case_result: T04CaseResult,
    step5_result: T04Step5CaseResult,
) -> T04Step6Result:
    drivezone_union = _loaded_feature_union(case_result.case_bundle.drivezone_features)
    representative_point = case_result.case_bundle.representative_node.geometry
    assembly_source_geometry = _union_geometry(
        [
            step5_result.case_allowed_growth_domain,
            step5_result.case_must_cover_domain,
            step5_result.case_terminal_cut_constraints,
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
    terminal_window_mask = (
        _rasterize_geometries(grid, [terminal_window_geometry])
        if terminal_window_geometry is not None and not terminal_window_geometry.is_empty
        else np.ones_like(allowed_mask, dtype=bool)
    )
    forbidden_mask = _rasterize_geometries(grid, [step5_result.case_forbidden_domain])
    cut_barrier_geometry = None
    if step5_result.case_terminal_cut_constraints is not None and not step5_result.case_terminal_cut_constraints.is_empty:
        cut_barrier_geometry = step5_result.case_terminal_cut_constraints.buffer(
            STEP6_CUT_BARRIER_BUFFER_M,
            cap_style=2,
            join_style=2,
        )
    cut_mask = _rasterize_geometries(grid, [cut_barrier_geometry]) if cut_barrier_geometry is not None else np.zeros_like(allowed_mask, dtype=bool)
    assembly_canvas_mask = allowed_mask & terminal_window_mask & ~forbidden_mask & ~cut_mask
    assembly_canvas_geometry = _constrain_geometry_to_case_limits(
        _mask_to_geometry(assembly_canvas_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )

    hard_seed_requested_mask = _rasterize_geometries(grid, [step5_result.case_must_cover_domain])
    hard_seed_mask = hard_seed_requested_mask & assembly_canvas_mask
    hard_seed_geometry = _constrain_geometry_to_case_limits(
        _mask_to_geometry(hard_seed_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )
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
            forbidden_geometry=step5_result.case_forbidden_domain,
        )
    if final_case_polygon is not None and not final_case_polygon.is_empty:
        final_case_polygon = _constrain_geometry_to_case_limits(
            final_case_polygon,
            drivezone_union=drivezone_union,
            allowed_geometry=step5_result.case_allowed_growth_domain,
            terminal_window_geometry=terminal_window_geometry,
            forbidden_geometry=step5_result.case_forbidden_domain,
            cut_barrier_geometry=cut_barrier_geometry,
        )
    cut_checked_polygon = final_case_polygon

    component_count = len(_polygon_components(final_case_polygon or GeometryCollection()))
    hole_details, final_case_holes = _hole_details(
        geometry=final_case_polygon,
        forbidden_geometry=step5_result.case_forbidden_domain,
        allowed_geometry=step5_result.case_allowed_growth_domain,
    )
    business_hole_count = sum(1 for item in hole_details if bool(item["business_hole"]))
    unexpected_hole_count = sum(1 for item in hole_details if not bool(item["business_hole"]))
    final_case_forbidden_overlap = _normalize_geometry(
        None
        if final_case_polygon is None or final_case_polygon.is_empty or step5_result.case_forbidden_domain is None
        else final_case_polygon.intersection(step5_result.case_forbidden_domain)
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
    b_node_target_covered = True
    if final_case_polygon is None or final_case_polygon.is_empty:
        b_node_target_covered = False
    elif (
        target_b_effective_geometry is not None
        and not target_b_effective_geometry.is_empty
        and not final_case_polygon.buffer(1e-6).covers(target_b_effective_geometry)
    ):
        b_node_target_covered = False

    review_reasons: list[str] = []
    if final_case_polygon is None or final_case_polygon.is_empty:
        review_reasons.append("assembly_failed")
    if component_count != 1 and final_case_polygon is not None and not final_case_polygon.is_empty:
        review_reasons.append("multi_component_result")
    if not hard_must_cover_ok:
        review_reasons.append("hard_must_cover_disconnected")
    if forbidden_overlap_area_m2 > STEP6_FORBIDDEN_TOLERANCE_AREA_M2:
        review_reasons.append("forbidden_conflict")
    if cut_violation:
        review_reasons.append("terminal_cut_conflict")
    if unexpected_hole_count > 0:
        review_reasons.append("unexpected_hole_present")
    if not b_node_target_covered:
        review_reasons.append("b_node_not_covered")
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
        forbidden_overlap_area_m2=forbidden_overlap_area_m2,
        cut_violation=cut_violation,
        assembly_state=assembly_state,
        review_reasons=tuple(review_reasons),
        hard_connect_notes=tuple(hard_connect_notes),
        optional_connect_notes=tuple(optional_connect_notes),
        hole_details=tuple(hole_details),
    )


__all__ = [
    "T04Step6Result",
    "build_step6_polygon_assembly",
]
