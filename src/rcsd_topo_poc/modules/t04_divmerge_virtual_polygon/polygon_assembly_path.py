from __future__ import annotations

from typing import Any, Sequence

from shapely.geometry import GeometryCollection, Polygon
from shapely.geometry.base import BaseGeometry

from ._rcsd_selection_support import _normalize_geometry, _union_geometry
from ._runtime_polygon_cleanup import _polygon_components
from .case_models import T04CaseResult
from .polygon_assembly_guards import Step6GuardContext
from .polygon_assembly_raster import (
    STEP6_ALLOWED_TOLERANCE_AREA_M2,
    STEP6_BARRIER_SEPARATION_RELIEF_NOTES,
    STEP6_CUT_BARRIER_BUFFER_M,
    STEP6_CUT_TOLERANCE_AREA_M2,
    STEP6_FORBIDDEN_TOLERANCE_AREA_M2,
    STEP6_INTER_UNIT_SECTION_BRIDGE_BUFFER_M,
    STEP6_INTER_UNIT_SECTION_BRIDGE_MAX_DISTANCE_M,
    STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_FORBIDDEN_TOLERANCE_M2,
    STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_MAX_AREA_M2,
    STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_MIN_AREA_M2,
    STEP6_JUNCTION_FULL_FILL_SLIT_RELIEF_RADIUS_M,
    STEP6_SWSD_WINDOW_TOUCH_CLOSE_MAX_AREA_DELTA_M2,
    STEP6_SWSD_WINDOW_TOUCH_CLOSE_RADIUS_M,
)
from .polygon_assembly_relief import hole_polygons as _hole_polygons
from .support_domain import T04Step5CaseResult
from .surface_scenario import (
    SCENARIO_MAIN_WITHOUT_RCSD,
    SCENARIO_NO_MAIN_WITH_RCSD,
    SCENARIO_NO_MAIN_WITH_RCSDROAD_AND_SWSD,
    SCENARIO_NO_MAIN_WITH_SWSD_ONLY,
)

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



__all__ = [
    "_area_outside",
    "_barrier_separated_case_surface_ok",
    "_case_alignment_aggregate_doc",
    "_case_alignment_review_reasons",
    "_clip_to_drivezone",
    "_constrain_geometry_to_case_limits",
    "_core_must_cover_geometry",
    "_doc_ids",
    "_fallback_support_geometry",
    "_fill_unexpected_polygon_holes",
    "_full_fill_target_geometry",
    "_geometry_area",
    "_hole_details",
    "_inter_unit_section_bridge_surface",
    "_is_no_main_section_window_surface",
    "_is_swsd_only_surface",
    "_is_swsd_section_window_surface",
    "_junction_full_fill_slit_relief",
    "_junction_full_fill_unit_count",
    "_line_parts",
    "_loaded_feature_union",
    "_negative_mask_channel_overlap_audit",
    "_overlap_area",
    "_relief_constraint_audit_entry",
    "_single_case_bridge_zone",
    "_swsd_window_touch_close",
    "_target_b_seed_geometry",
    "_unit_surface_count",
    "_uses_single_component_surface_seed",
    "check_post_cleanup_constraints",
]
