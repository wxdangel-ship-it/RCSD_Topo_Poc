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
from .surface_scenario import (
    SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
    SCENARIO_NO_SURFACE_REFERENCE,
    SURFACE_MODE_NO_SURFACE,
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


def _core_must_cover_geometry(step5_result: T04Step5CaseResult) -> BaseGeometry | None:
    return _normalize_geometry(
        _union_geometry(
            component
            for unit in step5_result.unit_results
            for component in (
                unit.localized_evidence_core_geometry,
                unit.fact_reference_patch_geometry,
                unit.required_rcsd_node_patch_geometry,
                unit.fallback_support_strip_geometry,
            )
        )
    )


def _full_fill_target_geometry(step5_result: T04Step5CaseResult) -> BaseGeometry | None:
    return _normalize_geometry(
        _union_geometry(unit.junction_full_road_fill_domain for unit in step5_result.unit_results)
    )


def _is_swsd_only_surface(guard_context: "Step6GuardContext") -> bool:
    return guard_context.surface_scenario_type == SCENARIO_NO_MAIN_WITH_SWSD_ONLY


def _uses_single_component_surface_seed(step5_result: T04Step5CaseResult) -> bool:
    return bool(
        len(step5_result.unit_results) == 1
        and step5_result.unit_results[0].single_component_surface_seed
    )


def _seed_dominant_polygon_component(
    geometry: BaseGeometry | None,
    seed_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    normalized = _normalize_geometry(geometry)
    if normalized is None:
        return None
    parts = _polygon_components(normalized)
    if len(parts) <= 1:
        return normalized
    seed = _normalize_geometry(seed_geometry)
    if seed is None:
        return _normalize_geometry(max(parts, key=lambda part: float(part.area)))
    overlaps = [
        (
            float(part.intersection(seed).area),
            float(part.area),
            part,
        )
        for part in parts
    ]
    positive_overlaps = [item for item in overlaps if item[0] > 1e-6]
    if positive_overlaps:
        return _normalize_geometry(max(positive_overlaps, key=lambda item: (item[0], item[1]))[2])
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


def _merged_text(values: Iterable[Any], *, missing_value: str = "missing") -> str:
    texts: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in texts:
            texts.append(text)
    if not texts:
        return missing_value
    return texts[0] if len(texts) == 1 else "mixed"


def _step5_units_have_field(step5_result: T04Step5CaseResult, field_name: str) -> bool:
    return bool(step5_result.unit_results) and all(hasattr(unit, field_name) for unit in step5_result.unit_results)


@dataclass(frozen=True)
class Step6GuardContext:
    surface_scenario_type: str
    section_reference_source: str
    surface_generation_mode: str
    reference_point_present: bool
    surface_section_forward_m: float | None
    surface_section_backward_m: float | None
    surface_lateral_limit_m: float | None
    fallback_rcsdroad_ids: tuple[str, ...]
    fallback_rcsdroad_localized: bool
    no_virtual_reference_point_guard: bool
    forbidden_domain_kept: bool
    divstrip_negative_mask_present: bool
    surface_scenario_missing: bool
    no_surface_reference_guard: bool


def derive_step6_guard_context(step5_result: T04Step5CaseResult) -> Step6GuardContext:
    units = tuple(step5_result.unit_results)
    surface_scenario_missing = not (
        _step5_units_have_field(step5_result, "surface_scenario_type")
        and _step5_units_have_field(step5_result, "surface_generation_mode")
    )
    scenario_type = _merged_text(
        getattr(unit, "surface_scenario_type", "") for unit in units
    )
    generation_mode = _merged_text(
        getattr(unit, "surface_generation_mode", "") for unit in units
    )
    section_reference_source = _merged_text(
        getattr(unit, "section_reference_source", "") for unit in units
    )
    fallback_ids: list[str] = []
    for unit in units:
        for road_id in getattr(unit, "fallback_rcsdroad_ids", ()) or ():
            text = str(road_id or "").strip()
            if text and text not in fallback_ids:
                fallback_ids.append(text)
    explicit_no_surface_units = [
        unit
        for unit in units
        if str(getattr(unit, "surface_scenario_type", "") or "") == SCENARIO_NO_SURFACE_REFERENCE
        or str(getattr(unit, "surface_generation_mode", "") or "") == SURFACE_MODE_NO_SURFACE
    ]
    no_surface_reference_guard = bool(units) and len(explicit_no_surface_units) == len(units)
    return Step6GuardContext(
        surface_scenario_type=scenario_type,
        section_reference_source=section_reference_source,
        surface_generation_mode=generation_mode,
        reference_point_present=any(bool(getattr(unit, "reference_point_present", False)) for unit in units),
        surface_section_forward_m=getattr(step5_result, "surface_section_forward_m", None),
        surface_section_backward_m=getattr(step5_result, "surface_section_backward_m", None),
        surface_lateral_limit_m=getattr(step5_result, "surface_lateral_limit_m", None),
        fallback_rcsdroad_ids=tuple(fallback_ids),
        fallback_rcsdroad_localized=any(bool(getattr(unit, "fallback_rcsdroad_localized", False)) for unit in units),
        no_virtual_reference_point_guard=bool(getattr(step5_result, "no_virtual_reference_point_guard", True)),
        forbidden_domain_kept=bool(
            getattr(step5_result, "forbidden_domain_kept", False)
            or step5_result.case_forbidden_domain is not None
        ),
        divstrip_negative_mask_present=bool(
            getattr(step5_result, "divstrip_negative_mask_present", False)
            or step5_result.divstrip_void_mask_geometry is not None
        ),
        surface_scenario_missing=surface_scenario_missing,
        no_surface_reference_guard=no_surface_reference_guard,
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
    fallback_geometry = _fallback_support_geometry(step5_result)
    fallback_outside_allowed_area = _area_outside(step5_result.case_allowed_growth_domain, fallback_geometry)
    fallback_domain_contained = fallback_outside_allowed_area <= STEP6_ALLOWED_TOLERANCE_AREA_M2
    fallback_overexpansion_area = allowed_outside_area if guard_context.fallback_rcsdroad_localized else 0.0
    return {
        "post_cleanup_allowed_growth_ok": allowed_outside_area <= STEP6_ALLOWED_TOLERANCE_AREA_M2,
        "post_cleanup_forbidden_ok": forbidden_overlap_area <= STEP6_FORBIDDEN_TOLERANCE_AREA_M2,
        "post_cleanup_terminal_cut_ok": terminal_cut_overlap_area <= STEP6_CUT_TOLERANCE_AREA_M2,
        "post_cleanup_lateral_limit_ok": allowed_outside_area <= STEP6_ALLOWED_TOLERANCE_AREA_M2,
        "post_cleanup_must_cover_ok": must_cover_ok,
        "post_cleanup_recheck_performed": True,
        "allowed_growth_outside_area_m2": allowed_outside_area,
        "terminal_cut_overlap_area_m2": terminal_cut_overlap_area,
        "lateral_limit_check_mode": "via_allowed_growth",
        "negative_mask_check_mode": "total_forbidden_plus_divstrip_mask",
        "divstrip_negative_overlap_area_m2": divstrip_negative_overlap_area,
        "fallback_domain_contained_by_allowed_growth": fallback_domain_contained,
        "fallback_overexpansion_detected": bool(
            guard_context.fallback_rcsdroad_localized
            and fallback_overexpansion_area > STEP6_ALLOWED_TOLERANCE_AREA_M2
        ),
        "fallback_overexpansion_area_m2": fallback_overexpansion_area,
    }


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
    post_cleanup_allowed_growth_ok: bool = True
    post_cleanup_forbidden_ok: bool = True
    post_cleanup_terminal_cut_ok: bool = True
    post_cleanup_lateral_limit_ok: bool = True
    post_cleanup_must_cover_ok: bool = True
    post_cleanup_recheck_performed: bool = False
    surface_scenario_type: str = "missing"
    section_reference_source: str = "missing"
    surface_generation_mode: str = "missing"
    reference_point_present: bool = False
    surface_section_forward_m: float | None = None
    surface_section_backward_m: float | None = None
    surface_lateral_limit_m: float | None = None
    surface_scenario_missing: bool = True
    no_surface_reference_guard: bool = False
    final_polygon_suppressed_by_no_surface_reference: bool = False
    no_virtual_reference_point_guard: bool = True
    fallback_rcsdroad_ids: tuple[str, ...] = ()
    fallback_rcsdroad_localized: bool = False
    fallback_domain_contained_by_allowed_growth: bool = True
    fallback_overexpansion_detected: bool = False
    fallback_overexpansion_area_m2: float = 0.0
    lateral_limit_check_mode: str = "via_allowed_growth"
    negative_mask_check_mode: str = "total_forbidden_plus_divstrip_mask"
    forbidden_domain_kept: bool = False
    divstrip_negative_mask_present: bool = False
    divstrip_negative_overlap_area_m2: float = 0.0
    allowed_growth_outside_area_m2: float = 0.0
    terminal_cut_overlap_area_m2: float = 0.0
    unit_surface_count: int = 0
    unit_surface_merge_performed: bool = False
    merge_mode: str = "case_level_assembly"
    merged_case_surface_component_count: int = 0
    final_case_polygon_component_count: int = 0
    single_connected_case_surface_ok: bool = False
    b_node_gate_applicable: bool = True
    b_node_gate_skip_reason: str = ""
    section_reference_window_covered: bool = True

    def to_status_doc(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "assembly_state": self.assembly_state,
            "review_reasons": list(self.review_reasons),
            "surface_scenario_type": self.surface_scenario_type,
            "section_reference_source": self.section_reference_source,
            "surface_generation_mode": self.surface_generation_mode,
            "reference_point_present": self.reference_point_present,
            "surface_section_forward_m": self.surface_section_forward_m,
            "surface_section_backward_m": self.surface_section_backward_m,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
            "surface_scenario_missing": self.surface_scenario_missing,
            "no_surface_reference_guard": self.no_surface_reference_guard,
            "final_polygon_suppressed_by_no_surface_reference": self.final_polygon_suppressed_by_no_surface_reference,
            "no_virtual_reference_point_guard": self.no_virtual_reference_point_guard,
            "component_count": self.component_count,
            "hole_count": self.hole_count,
            "business_hole_count": self.business_hole_count,
            "unexpected_hole_count": self.unexpected_hole_count,
            "hard_must_cover_ok": self.hard_must_cover_ok,
            "b_node_target_covered": self.b_node_target_covered,
            "b_node_gate_applicable": self.b_node_gate_applicable,
            "b_node_gate_skip_reason": self.b_node_gate_skip_reason,
            "section_reference_window_covered": self.section_reference_window_covered,
            "forbidden_overlap_area_m2": self.forbidden_overlap_area_m2,
            "cut_violation": self.cut_violation,
            "post_cleanup_allowed_growth_ok": self.post_cleanup_allowed_growth_ok,
            "post_cleanup_forbidden_ok": self.post_cleanup_forbidden_ok,
            "post_cleanup_terminal_cut_ok": self.post_cleanup_terminal_cut_ok,
            "post_cleanup_lateral_limit_ok": self.post_cleanup_lateral_limit_ok,
            "post_cleanup_must_cover_ok": self.post_cleanup_must_cover_ok,
            "post_cleanup_recheck_performed": self.post_cleanup_recheck_performed,
            "lateral_limit_check_mode": self.lateral_limit_check_mode,
            "fallback_rcsdroad_ids": list(self.fallback_rcsdroad_ids),
            "fallback_rcsdroad_localized": self.fallback_rcsdroad_localized,
            "fallback_domain_contained_by_allowed_growth": self.fallback_domain_contained_by_allowed_growth,
            "fallback_overexpansion_detected": self.fallback_overexpansion_detected,
            "fallback_overexpansion_area_m2": self.fallback_overexpansion_area_m2,
            "divstrip_negative_mask_present": self.divstrip_negative_mask_present,
            "divstrip_negative_overlap_area_m2": self.divstrip_negative_overlap_area_m2,
            "forbidden_domain_kept": self.forbidden_domain_kept,
            "unit_surface_count": self.unit_surface_count,
            "unit_surface_merge_performed": self.unit_surface_merge_performed,
            "merge_mode": self.merge_mode,
            "merged_case_surface_component_count": self.merged_case_surface_component_count,
            "final_case_polygon_component_count": self.final_case_polygon_component_count,
            "single_connected_case_surface_ok": self.single_connected_case_surface_ok,
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
            "post_cleanup_allowed_growth_ok": self.post_cleanup_allowed_growth_ok,
            "post_cleanup_forbidden_ok": self.post_cleanup_forbidden_ok,
            "post_cleanup_terminal_cut_ok": self.post_cleanup_terminal_cut_ok,
            "post_cleanup_lateral_limit_ok": self.post_cleanup_lateral_limit_ok,
            "post_cleanup_must_cover_ok": self.post_cleanup_must_cover_ok,
            "post_cleanup_recheck_performed": self.post_cleanup_recheck_performed,
            "allowed_growth_outside_area_m2": self.allowed_growth_outside_area_m2,
            "terminal_cut_overlap_area_m2": self.terminal_cut_overlap_area_m2,
            "lateral_limit_check_mode": self.lateral_limit_check_mode,
            "negative_mask_check_mode": self.negative_mask_check_mode,
            "surface_scenario_type": self.surface_scenario_type,
            "section_reference_source": self.section_reference_source,
            "surface_generation_mode": self.surface_generation_mode,
            "surface_lateral_limit_m": self.surface_lateral_limit_m,
            "b_node_gate_applicable": self.b_node_gate_applicable,
            "b_node_gate_skip_reason": self.b_node_gate_skip_reason,
            "section_reference_window_covered": self.section_reference_window_covered,
            "surface_scenario_missing": self.surface_scenario_missing,
            "no_surface_reference_guard": self.no_surface_reference_guard,
            "final_polygon_suppressed_by_no_surface_reference": self.final_polygon_suppressed_by_no_surface_reference,
            "fallback_rcsdroad_ids": list(self.fallback_rcsdroad_ids),
            "fallback_rcsdroad_localized": self.fallback_rcsdroad_localized,
            "fallback_domain_contained_by_allowed_growth": self.fallback_domain_contained_by_allowed_growth,
            "fallback_overexpansion_detected": self.fallback_overexpansion_detected,
            "fallback_overexpansion_area_m2": self.fallback_overexpansion_area_m2,
            "divstrip_negative_mask_present": self.divstrip_negative_mask_present,
            "divstrip_negative_overlap_area_m2": self.divstrip_negative_overlap_area_m2,
            "forbidden_domain_kept": self.forbidden_domain_kept,
            "unit_surface_count": self.unit_surface_count,
            "unit_surface_merge_performed": self.unit_surface_merge_performed,
            "merge_mode": self.merge_mode,
            "merged_case_surface_component_count": self.merged_case_surface_component_count,
            "final_case_polygon_component_count": self.final_case_polygon_component_count,
            "single_connected_case_surface_ok": self.single_connected_case_surface_ok,
        }


def build_step6_polygon_assembly(
    case_result: T04CaseResult,
    step5_result: T04Step5CaseResult,
) -> T04Step6Result:
    guard_context = derive_step6_guard_context(step5_result)
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
            review_reasons=("no_surface_reference",),
            hard_connect_notes=(),
            optional_connect_notes=(),
            hole_details=(),
            **post_checks,
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

    core_hard_seed_geometry = _core_must_cover_geometry(step5_result)
    hard_seed_requested_mask = _rasterize_geometries(grid, [step5_result.case_must_cover_domain])
    full_fill_target_geometry = _full_fill_target_geometry(step5_result)
    if full_fill_target_geometry is not None and not full_fill_target_geometry.is_empty:
        core_seed_requested_mask = _rasterize_geometries(grid, [core_hard_seed_geometry])
        full_fill_requested_mask = _rasterize_geometries(grid, [full_fill_target_geometry])
        full_fill_canvas_mask = full_fill_requested_mask & assembly_canvas_mask
        core_seed_canvas_mask = core_seed_requested_mask & assembly_canvas_mask
        if _is_swsd_only_surface(guard_context) and not core_seed_canvas_mask.any():
            effective_full_fill_mask = full_fill_canvas_mask
        else:
            effective_full_fill_mask = _extract_seed_component(
                full_fill_canvas_mask,
                core_seed_canvas_mask,
            )
        hard_seed_requested_mask = core_seed_requested_mask | effective_full_fill_mask
    hard_seed_mask = hard_seed_requested_mask & assembly_canvas_mask
    hard_seed_geometry = _constrain_geometry_to_case_limits(
        _mask_to_geometry(hard_seed_mask, grid),
        drivezone_union=drivezone_union,
        allowed_geometry=step5_result.case_allowed_growth_domain,
        terminal_window_geometry=terminal_window_geometry,
        forbidden_geometry=step5_result.case_forbidden_domain,
        cut_barrier_geometry=cut_barrier_geometry,
    )
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
    if single_component_surface_seed:
        final_case_polygon = _seed_dominant_polygon_component(
            final_case_polygon,
            hard_seed_geometry,
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
    target_b_present = bool(
        target_b_effective_geometry is not None
        and not target_b_effective_geometry.is_empty
    )
    b_node_gate_applicable = True
    b_node_gate_skip_reason = ""
    if not target_b_present and _is_swsd_only_surface(guard_context):
        b_node_gate_applicable = False
        b_node_gate_skip_reason = "swsd_only_without_b_target"

    b_node_target_covered = True
    if not b_node_gate_applicable:
        b_node_target_covered = True
    elif final_case_polygon is None or final_case_polygon.is_empty:
        b_node_target_covered = False
    elif target_b_present and not final_case_polygon.buffer(1e-6).covers(target_b_effective_geometry):
        b_node_target_covered = False
    section_reference_window_covered = True
    if _is_swsd_only_surface(guard_context):
        section_reference_window_covered = bool(
            final_case_polygon is not None
            and not final_case_polygon.is_empty
            and hard_seed_geometry is not None
            and not hard_seed_geometry.is_empty
            and final_case_polygon.buffer(1e-6).covers(hard_seed_geometry)
        )
    post_checks = check_post_cleanup_constraints(
        final_case_polygon=final_case_polygon,
        step5_result=step5_result,
        cut_barrier_geometry=cut_barrier_geometry,
        hard_seed_geometry=hard_seed_geometry,
        guard_context=guard_context,
    )
    hard_must_cover_ok = bool(post_checks["post_cleanup_must_cover_ok"])

    review_reasons: list[str] = []
    if final_case_polygon is None or final_case_polygon.is_empty:
        review_reasons.append("assembly_failed")
    if component_count != 1 and final_case_polygon is not None and not final_case_polygon.is_empty:
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
    if bool(post_checks["fallback_overexpansion_detected"]):
        review_reasons.append("fallback_overexpansion")
    if unexpected_hole_count > 0:
        review_reasons.append("unexpected_hole_present")
    if b_node_gate_applicable and not b_node_target_covered:
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
        **post_checks,
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
    )


__all__ = [
    "Step6GuardContext",
    "T04Step6Result",
    "build_step6_polygon_assembly",
    "check_post_cleanup_constraints",
    "derive_step6_guard_context",
]
