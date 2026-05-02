from __future__ import annotations

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from ._rcsd_selection_support import _as_point, _normalize_geometry, _union_geometry
from .case_models import T04EventUnitResult
from .support_domain_common import (
    _clip_to_drivezone,
    _event_axis_line,
    _event_axis_vector,
    _iter_polygon_parts,
    _line_geometry,
    _line_window_centerline,
    _ordered_line_by_origin,
    _required_rcsd_anchor_point,
    _section_reference_anchor_point,
    _section_reference_seed_point,
    _step5_surface_window_config,
    _terminal_axis_window_centerline,
    _terminal_window_half_width,
)
from .support_domain_scenario import (
    STEP5_FALLBACK_STRIP_HALF_LENGTH_M,
    STEP5_FALLBACK_STRIP_HALF_WIDTH_M,
    STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M,
    STEP5_JUNCTION_WINDOW_EVIDENCE_SOURCES,
    STEP5_JUNCTION_WINDOW_HALF_LENGTH_M,
    STEP5_SUPPORT_ROAD_BUFFER_M,
    Step5SurfaceWindowConfig,
)
from .surface_scenario import (
    SCENARIO_MAIN_WITH_RCSD,
    SECTION_REFERENCE_POINT_AND_RCSD,
    SECTION_REFERENCE_RCSD,
    SURFACE_MODE_RCSD_WINDOW,
    SURFACE_MODE_SWSD_WINDOW,
    SURFACE_MODE_SWSD_WITH_RCSDROAD,
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
    if window_centerline is None and _uses_junction_window(unit_result):
        anchor_point = _junction_window_anchor_point(unit_result)
        axis_line = _junction_window_axis_line(unit_result, anchor_point) if anchor_point is not None else None
        if axis_line is not None and anchor_point is not None:
            anchor_s = float(axis_line.project(anchor_point))
            window_centerline = _line_window_centerline(
                axis_line,
                start_distance_m=anchor_s - STEP5_JUNCTION_WINDOW_HALF_LENGTH_M,
                end_distance_m=anchor_s + STEP5_JUNCTION_WINDOW_HALF_LENGTH_M,
            )
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
    if "continuous_chain_review" in set(unit_result.all_review_reasons()):
        return False
    config = _step5_surface_window_config(unit_result)
    source = str(unit_result.evidence_source or "")
    if not config.reference_point_present and not config.surface_scenario_missing:
        if not (
            source == "rcsd_anchored_reverse"
            and config.section_reference_source == SECTION_REFERENCE_RCSD
        ):
            return False
        reference_point = _section_reference_seed_point(unit_result, config)
    else:
        reference_point = _as_point(unit_result.fact_reference_point)
    has_reference_and_rcsd_section = (
        config.surface_scenario_type == SCENARIO_MAIN_WITH_RCSD
        and config.section_reference_source == SECTION_REFERENCE_POINT_AND_RCSD
    )
    if has_reference_and_rcsd_section:
        return bool(
            str(unit_result.required_rcsd_node or "").strip()
            and reference_point is not None
            and _required_rcsd_anchor_point(unit_result) is not None
        )
    return bool(
        source in {"rcsd_anchored_reverse", "road_surface_fork", "multibranch_event"}
        and str(unit_result.required_rcsd_node or "").strip()
        and reference_point is not None
        and _required_rcsd_anchor_point(unit_result) is not None
    )

def _uses_junction_window(unit_result: T04EventUnitResult) -> bool:
    config = _step5_surface_window_config(unit_result)
    source = str(unit_result.evidence_source or "")
    if (
        source == "rcsd_anchored_reverse"
        and config.surface_generation_mode == SURFACE_MODE_RCSD_WINDOW
        and config.section_reference_source == SECTION_REFERENCE_RCSD
    ):
        return False
    if config.surface_generation_mode in {
        SURFACE_MODE_RCSD_WINDOW,
        SURFACE_MODE_SWSD_WINDOW,
        SURFACE_MODE_SWSD_WITH_RCSDROAD,
    }:
        return True
    return source in STEP5_JUNCTION_WINDOW_EVIDENCE_SOURCES

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
