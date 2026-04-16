from __future__ import annotations

import math
from typing import Any

import numpy as np
from shapely.geometry import GeometryCollection, Point
from shapely.ops import nearest_points, unary_union

from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step5_step6_contract import (
    Stage4ExclusionGeometryContext,
    Stage4GeometricSupportDomain,
    Stage4SpanWindow,
    Stage4SurfaceAssemblyResult,
)
from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step4_contract import Stage4EventInterpretationResult
from rcsd_topo_poc.modules.t02_junction_anchor.shared import normalize_id
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import ParsedNode, ParsedRoad, _mask_to_geometry

from .stage4_geometry_utils import *
from .stage4_surface_assembly_utils import *

def _collect_axis_offsets_from_geometry(
    geometry,
    *,
    origin_xy: tuple[float, float],
    axis_unit_vector: tuple[float, float],
    clip_geometry=None,
) -> list[float]:
    if geometry is None or geometry.is_empty:
        return []
    target_geometry = geometry if clip_geometry is None else geometry.intersection(clip_geometry)
    if target_geometry.is_empty:
        return []
    offsets: list[float] = []
    for part in _explode_component_geometries(target_geometry):
        geom_type = getattr(part, "geom_type", None)
        if geom_type == "Point":
            offsets.append(
                _project_point_to_axis(
                    part,
                    origin_xy=origin_xy,
                    axis_unit_vector=axis_unit_vector,
                )
            )
            continue
        if geom_type == "LineString":
            offsets.extend(
                _project_xy_to_axis(x, y, origin_xy=origin_xy, axis_unit_vector=axis_unit_vector)
                for x, y in (_coord_xy(coord) for coord in part.coords)
            )
            continue
        if geom_type == "Polygon":
            offsets.extend(
                _project_xy_to_axis(x, y, origin_xy=origin_xy, axis_unit_vector=axis_unit_vector)
                for x, y in (_coord_xy(coord) for coord in part.exterior.coords)
            )
    return offsets


def _resolve_event_span_window(
    *,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    selected_rcsd_nodes: list[ParsedNode],
    event_anchor_geometry,
    selected_roads_geometry=None,
    selected_event_roads_geometry=None,
    selected_rcsd_roads_geometry=None,
    span_limit_m: float | None = None,
) -> dict[str, Any]:
    if span_limit_m is None or float(span_limit_m) <= 0:
        span_limit_m = EVENT_SPAN_MAX_M
    else:
        span_limit_m = float(span_limit_m)
    start_offset_m = -EVENT_SPAN_DEFAULT_M
    end_offset_m = EVENT_SPAN_DEFAULT_M
    if axis_unit_vector is None:
        return {
            "start_offset_m": max(-span_limit_m, start_offset_m),
            "end_offset_m": min(span_limit_m, end_offset_m),
            "candidate_offset_count": 0,
            "expansion_source": "default_no_axis",
        }

    origin_xy = (float(origin_point.x), float(origin_point.y))
    candidate_offsets: list[float] = []
    rcsd_node_offsets: list[float] = []
    for node in selected_rcsd_nodes:
        projected_offset = _project_point_to_axis(
            node.geometry,
            origin_xy=origin_xy,
            axis_unit_vector=axis_unit_vector,
        )
        if -EVENT_SPAN_MAX_M - EVENT_SPAN_MARGIN_M <= float(projected_offset) <= EVENT_SPAN_MAX_M + EVENT_SPAN_MARGIN_M:
            rcsd_node_offsets.append(float(projected_offset))
    candidate_offsets.extend(rcsd_node_offsets)

    if rcsd_node_offsets:
        local_context_start_m = max(
            -span_limit_m,
            min(-EVENT_SPAN_DEFAULT_M, min(rcsd_node_offsets) - EVENT_SPAN_LOCAL_CONTEXT_PAD_M),
        )
        local_context_end_m = min(
            span_limit_m,
            max(EVENT_SPAN_DEFAULT_M, max(rcsd_node_offsets) + EVENT_SPAN_LOCAL_CONTEXT_PAD_M),
        )
    else:
        local_context_start_m = max(-span_limit_m, -EVENT_SPAN_LOCAL_CONTEXT_PAD_M)
        local_context_end_m = min(span_limit_m, EVENT_SPAN_LOCAL_CONTEXT_PAD_M)

    def _filter_local_context_offsets(offsets: list[float]) -> list[float]:
        return [
            float(offset)
            for offset in offsets
            if math.isfinite(float(offset))
            and float(local_context_start_m) - EVENT_SPAN_MARGIN_M
            <= float(offset)
            <= float(local_context_end_m) + EVENT_SPAN_MARGIN_M
        ]

    candidate_offsets.extend(
        _filter_local_context_offsets(
            _collect_axis_offsets_from_geometry(
                event_anchor_geometry,
                origin_xy=origin_xy,
                axis_unit_vector=axis_unit_vector,
            )
        )
    )
    road_context_clip_geometry = None
    if event_anchor_geometry is not None and not event_anchor_geometry.is_empty:
        road_context_clip_geometry = event_anchor_geometry.buffer(
            EVENT_SPAN_MAX_M + EVENT_SPAN_MARGIN_M,
            cap_style=2,
            join_style=2,
        )
    event_span_roads_geometry = (
        selected_event_roads_geometry
        if selected_event_roads_geometry is not None and not selected_event_roads_geometry.is_empty
        else selected_roads_geometry
    )
    if event_span_roads_geometry is not None:
        candidate_offsets.extend(
            _filter_local_context_offsets(
                _collect_axis_offsets_from_geometry(
                    event_span_roads_geometry,
                    origin_xy=origin_xy,
                    axis_unit_vector=axis_unit_vector,
                    clip_geometry=road_context_clip_geometry,
                )
            )
        )
    candidate_offsets.extend(
        _filter_local_context_offsets(
            _collect_axis_offsets_from_geometry(
                selected_rcsd_roads_geometry,
                origin_xy=origin_xy,
                axis_unit_vector=axis_unit_vector,
                clip_geometry=road_context_clip_geometry,
            )
        )
    )
    if candidate_offsets:
        start_offset_m = min(start_offset_m, min(candidate_offsets) - EVENT_SPAN_MARGIN_M)
        end_offset_m = max(end_offset_m, max(candidate_offsets) + EVENT_SPAN_MARGIN_M)
        expansion_source = "rcsd_or_divstrip_context"
    else:
        expansion_source = "default_span"
    start_offset_m = max(-span_limit_m, start_offset_m)
    end_offset_m = min(span_limit_m, end_offset_m)
    return {
        "start_offset_m": float(start_offset_m),
        "end_offset_m": float(end_offset_m),
        "candidate_offset_count": len(candidate_offsets),
        "expansion_source": expansion_source,
    }


def _is_semantic_boundary_representative(node: ParsedNode) -> bool:
    representative_id = normalize_id(node.mainnodeid or node.node_id)
    source_kind = _node_source_kind(node)
    source_kind_2 = _node_source_kind_2(node)
    has_semantic_marker = any(
        value not in {None, 0, 1}
        for value in (source_kind, source_kind_2)
    )
    return (
        representative_id is not None
        and normalize_id(node.node_id) == representative_id
        and has_semantic_marker
    )


def _refine_event_span_window_by_semantic_context(
    *,
    event_span_window: dict[str, Any],
    candidate_nodes: list[ParsedNode],
    semantic_member_nodes: list[ParsedNode],
    group_nodes: list[ParsedNode],
    representative_node: ParsedNode,
    related_mainnodeids: list[str],
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    axis_centerline,
    event_anchor_geometry,
    selected_roads: list[ParsedRoad],
    include_complex_members: bool,
) -> dict[str, Any]:
    if axis_unit_vector is None:
        return event_span_window

    original_start = float(event_span_window["start_offset_m"])
    original_end = float(event_span_window["end_offset_m"])
    protected_offsets: list[float] = [0.0]
    origin_xy = (float(origin_point.x), float(origin_point.y))
    protected_offsets.extend(
        [
            float(offset)
            for offset in _collect_axis_offsets_from_geometry(
                event_anchor_geometry,
                origin_xy=origin_xy,
                axis_unit_vector=axis_unit_vector,
            )
            if math.isfinite(float(offset))
            and float(original_start) - EVENT_SPAN_MARGIN_M
            <= float(offset)
            <= float(original_end) + EVENT_SPAN_MARGIN_M
        ]
    )

    included_mainnodeids = {
        normalize_id(representative_node.mainnodeid or representative_node.node_id)
    }
    included_mainnodeids.update(
        normalize_id(mainnodeid)
        for mainnodeid in related_mainnodeids
        if normalize_id(mainnodeid) is not None
    )
    included_mainnodeids.discard(None)

    semantic_member_offsets: list[float] = []
    if include_complex_members:
        seen_member_node_ids: set[str] = set()
        for node in semantic_member_nodes:
            if node.node_id in seen_member_node_ids:
                continue
            seen_member_node_ids.add(node.node_id)
            projected_offset = _project_point_to_axis(
                node.geometry,
                origin_xy=origin_xy,
                axis_unit_vector=axis_unit_vector,
            )
            if math.isfinite(float(projected_offset)):
                semantic_member_offsets.append(float(projected_offset))
        if semantic_member_offsets:
            protected_offsets.append(min(semantic_member_offsets) - EVENT_COMPLEX_MEMBER_SPAN_PAD_M)
            protected_offsets.append(max(semantic_member_offsets) + EVENT_COMPLEX_MEMBER_SPAN_PAD_M)

    if not protected_offsets:
        return event_span_window

    protected_start = float(min(protected_offsets) - EVENT_SPAN_MARGIN_M)
    protected_end = float(max(protected_offsets) + EVENT_SPAN_MARGIN_M)
    refined_start = min(original_start, protected_start)
    refined_end = max(original_end, protected_end)

    corridor_geometries: list[Any] = []
    if axis_centerline is not None and not axis_centerline.is_empty:
        corridor_geometries.append(
            axis_centerline.buffer(
                EVENT_SEMANTIC_BOUNDARY_AXIS_BUFFER_M,
                cap_style=2,
                join_style=2,
            )
        )
    selected_road_geometries = [
        road.geometry
        for road in selected_roads
        if road.geometry is not None and not road.geometry.is_empty
    ]
    if selected_road_geometries:
        corridor_geometries.append(
            unary_union(selected_road_geometries).buffer(
                EVENT_SEMANTIC_BOUNDARY_ROAD_BUFFER_M,
                cap_style=2,
                join_style=2,
            )
        )
    corridor_geometry = unary_union(corridor_geometries) if corridor_geometries else GeometryCollection()

    previous_boundary_offset_m = None
    next_boundary_offset_m = None
    for node in candidate_nodes:
        if not _is_semantic_boundary_representative(node):
            continue
        node_mainnodeid = normalize_id(node.mainnodeid or node.node_id)
        if node_mainnodeid in included_mainnodeids:
            continue
        if corridor_geometry is not None and not corridor_geometry.is_empty and not corridor_geometry.intersects(node.geometry):
            continue
        projected_offset = _project_point_to_axis(
            node.geometry,
            origin_xy=origin_xy,
            axis_unit_vector=axis_unit_vector,
        )
        if not math.isfinite(float(projected_offset)):
            continue
        projected_offset = float(projected_offset)
        if projected_offset < protected_start - 1e-6:
            if previous_boundary_offset_m is None or projected_offset > float(previous_boundary_offset_m):
                previous_boundary_offset_m = projected_offset
        elif projected_offset > protected_end + 1e-6:
            if next_boundary_offset_m is None or projected_offset < float(next_boundary_offset_m):
                next_boundary_offset_m = projected_offset

    if previous_boundary_offset_m is not None:
        refined_start = max(refined_start, float(previous_boundary_offset_m) + EVENT_SEMANTIC_BOUNDARY_PAD_M)
    if next_boundary_offset_m is not None:
        refined_end = min(refined_end, float(next_boundary_offset_m) - EVENT_SEMANTIC_BOUNDARY_PAD_M)

    extra_span_cap_m = (
        EVENT_COMPLEX_EXTRA_SPAN_CAP_M
        if include_complex_members
        else EVENT_NON_COMPLEX_EXTRA_SPAN_CAP_M
    )
    refined_start = max(refined_start, protected_start - float(extra_span_cap_m))
    refined_end = min(refined_end, protected_end + float(extra_span_cap_m))

    refined_start = max(-CHAIN_CONTEXT_EVENT_SPAN_M, refined_start)
    refined_end = min(CHAIN_CONTEXT_EVENT_SPAN_M, refined_end)
    refined_start = min(refined_start, protected_start)
    refined_end = max(refined_end, protected_end)

    if refined_end - refined_start <= EVENT_SPAN_MARGIN_M * 2.0:
        return event_span_window

    refined_window = dict(event_span_window)
    refined_window["start_offset_m"] = float(refined_start)
    refined_window["end_offset_m"] = float(refined_end)
    refined_window["semantic_protected_start_m"] = float(protected_start)
    refined_window["semantic_protected_end_m"] = float(protected_end)
    refined_window["semantic_member_count"] = len(semantic_member_offsets)
    refined_window["semantic_prev_boundary_offset_m"] = (
        None if previous_boundary_offset_m is None else float(previous_boundary_offset_m)
    )
    refined_window["semantic_next_boundary_offset_m"] = (
        None if next_boundary_offset_m is None else float(next_boundary_offset_m)
    )
    if refined_start != original_start or refined_end != original_end:
        refined_window["expansion_source"] = "semantic_context_refined"
    return refined_window


def _clip_simple_event_span_window_by_divstrip_context(
    *,
    event_span_window: dict[str, Any],
    divstrip_constraint_geometry,
    direct_target_rc_nodes: list[ParsedNode],
    selected_roads: list[ParsedRoad] | None,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    selected_component_count: int,
    is_complex_junction: bool,
    event_split_pick_source: str | None = None,
) -> dict[str, Any]:
    if (
        axis_unit_vector is None
        or is_complex_junction
        or int(selected_component_count) != 1
        or divstrip_constraint_geometry is None
        or divstrip_constraint_geometry.is_empty
    ):
        return event_span_window

    origin_xy = (float(origin_point.x), float(origin_point.y))
    component_offsets = [
        float(offset)
        for offset in _collect_axis_offsets_from_geometry(
            divstrip_constraint_geometry,
            origin_xy=origin_xy,
            axis_unit_vector=axis_unit_vector,
        )
        if math.isfinite(float(offset))
    ]
    if not component_offsets:
        return event_span_window

    protected_start = float(
        event_span_window.get("semantic_protected_start_m", event_span_window["start_offset_m"])
    )
    protected_end = float(
        event_span_window.get("semantic_protected_end_m", event_span_window["end_offset_m"])
    )
    current_start = float(event_span_window["start_offset_m"])
    current_end = float(event_span_window["end_offset_m"])

    local_start = float(min(component_offsets) - EVENT_SPAN_MARGIN_M)
    local_end = float(max(component_offsets) + EVENT_SPAN_MARGIN_M)

    target_offsets = [
        float(
            _project_point_to_axis(
                node.geometry,
                origin_xy=origin_xy,
                axis_unit_vector=axis_unit_vector,
            )
        )
        for node in direct_target_rc_nodes
        if node.geometry is not None and not node.geometry.is_empty
    ]
    target_offsets = [offset for offset in target_offsets if math.isfinite(float(offset))]
    if target_offsets:
        local_start = min(local_start, float(min(target_offsets) - EVENT_SPAN_MARGIN_M))
        local_end = max(local_end, float(max(target_offsets) + EVENT_SPAN_MARGIN_M))

    selected_road_geometries = [
        road.geometry
        for road in (selected_roads or [])
        if road.geometry is not None and not road.geometry.is_empty
    ]
    if selected_road_geometries:
        selected_road_offsets = [
            float(offset)
            for offset in _collect_axis_offsets_from_geometry(
                unary_union(selected_road_geometries),
                origin_xy=origin_xy,
                axis_unit_vector=axis_unit_vector,
            )
            if (
                math.isfinite(float(offset))
                and float(local_start) - float(EVENT_SPAN_LOCAL_CONTEXT_PAD_M)
                <= float(offset)
                <= float(local_end) + float(EVENT_SPAN_LOCAL_CONTEXT_PAD_M)
            )
        ]
        if selected_road_offsets:
            local_start = min(local_start, float(min(selected_road_offsets) - EVENT_SPAN_MARGIN_M))
            local_end = max(local_end, float(max(selected_road_offsets) + EVENT_SPAN_MARGIN_M))

    component_extra_span_pad_m = float(EVENT_SIMPLE_COMPONENT_EXTRA_SPAN_PAD_M)
    if (
        not target_offsets
        and str(event_split_pick_source) == "divstrip_first_hit_window"
    ):
        component_extra_span_pad_m = max(component_extra_span_pad_m, 16.0)

    clipped_start = max(current_start, local_start - component_extra_span_pad_m)
    clipped_end = min(current_end, local_end + component_extra_span_pad_m)
    clipped_start = min(clipped_start, protected_start)
    clipped_end = max(clipped_end, protected_end)

    if clipped_end - clipped_start <= EVENT_SPAN_MARGIN_M * 2.0:
        return event_span_window
    if (
        abs(float(clipped_start) - current_start) <= 1e-6
        and abs(float(clipped_end) - current_end) <= 1e-6
    ):
        return event_span_window

    clipped_window = dict(event_span_window)
    clipped_window["start_offset_m"] = float(clipped_start)
    clipped_window["end_offset_m"] = float(clipped_end)
    clipped_window["expansion_source"] = "simple_divstrip_clipped"
    return clipped_window


def _refine_complex_event_span_window_by_divstrip_context(
    *,
    event_span_window: dict[str, Any],
    divstrip_constraint_geometry,
    selected_roads_geometry,
    selected_event_roads_geometry,
    selected_rcsd_roads_geometry,
    origin_point: Point,
    axis_unit_vector: tuple[float, float] | None,
    selected_component_count: int,
    is_complex_junction: bool,
) -> dict[str, Any]:
    if (
        axis_unit_vector is None
        or not is_complex_junction
        or int(selected_component_count) <= 1
        or divstrip_constraint_geometry is None
        or divstrip_constraint_geometry.is_empty
    ):
        return event_span_window

    origin_xy = (float(origin_point.x), float(origin_point.y))
    component_offsets: list[float] = []
    component_local_span_cap_m = max(
        float(EVENT_SPAN_DEFAULT_M),
        float(EVENT_COMPONENT_SIDE_CLIP_BUFFER_M) * 2.0,
        12.0,
    )
    selected_components = [
        component
        for component in _collect_polygon_components(divstrip_constraint_geometry)
        if component is not None and not component.is_empty
    ]
    for component_geometry in selected_components:
        component_repr = component_geometry.representative_point()
        if component_repr is None or component_repr.is_empty:
            continue
        component_center_offset = _project_point_to_axis(
            component_repr,
            origin_xy=origin_xy,
            axis_unit_vector=axis_unit_vector,
        )
        if not math.isfinite(float(component_center_offset)):
            continue
        component_local_offsets = [
            float(offset)
            for offset in _collect_axis_offsets_from_geometry(
                component_geometry,
                origin_xy=(float(component_repr.x), float(component_repr.y)),
                axis_unit_vector=axis_unit_vector,
            )
            if math.isfinite(float(offset))
        ]
        if component_local_offsets:
            component_offsets.extend(
                [
                    float(component_center_offset)
                    + max(float(min(component_local_offsets)), -component_local_span_cap_m),
                    float(component_center_offset)
                    + min(float(max(component_local_offsets)), component_local_span_cap_m),
                ]
            )
        else:
            component_offsets.extend(
                [
                    float(component_center_offset) - component_local_span_cap_m,
                    float(component_center_offset) + component_local_span_cap_m,
                ]
            )
    if not component_offsets:
        component_offsets = [
            float(offset)
            for offset in _collect_axis_offsets_from_geometry(
                divstrip_constraint_geometry,
                origin_xy=origin_xy,
                axis_unit_vector=axis_unit_vector,
            )
            if math.isfinite(float(offset))
        ]
    if not component_offsets:
        return event_span_window

    component_min_offset = float(min(component_offsets))
    component_max_offset = float(max(component_offsets))
    context_start = float(component_min_offset - EVENT_SPAN_MARGIN_M)
    context_end = float(component_max_offset + EVENT_SPAN_MARGIN_M)
    local_context_start = float(context_start - EVENT_SPAN_LOCAL_CONTEXT_PAD_M)
    local_context_end = float(context_end + EVENT_SPAN_LOCAL_CONTEXT_PAD_M)

    def _filter_context_offsets(offsets: list[float]) -> list[float]:
        return [
            float(offset)
            for offset in offsets
            if (
                math.isfinite(float(offset))
                and float(local_context_start) - EVENT_SPAN_MARGIN_M
                <= float(offset)
                <= float(local_context_end) + EVENT_SPAN_MARGIN_M
            )
        ]

    def _collect_context_offsets(geometry) -> list[float]:
        return _filter_context_offsets(
            _collect_axis_offsets_from_geometry(
                geometry,
                origin_xy=origin_xy,
                axis_unit_vector=axis_unit_vector,
            )
        )

    candidate_offsets = list(component_offsets)
    contextual_min_offset = float(component_min_offset)
    contextual_max_offset = float(component_max_offset)

    road_context_clip_geometry = divstrip_constraint_geometry.buffer(
        max(
            float(EVENT_SPAN_LOCAL_CONTEXT_PAD_M),
            float(EVENT_COMPONENT_SIDE_CLIP_BUFFER_M) * 2.0,
            12.0,
        ),
        cap_style=2,
        join_style=2,
    )
    road_context_geometries = [
        selected_event_roads_geometry
        if selected_event_roads_geometry is not None and not selected_event_roads_geometry.is_empty
        else selected_roads_geometry,
        selected_rcsd_roads_geometry,
    ]
    road_context_offsets: list[float] = []
    for road_context_geometry in road_context_geometries:
        if road_context_geometry is None or road_context_geometry.is_empty:
            continue
        road_context_offsets.extend(
            _filter_context_offsets(
                _collect_axis_offsets_from_geometry(
                    road_context_geometry,
                    origin_xy=origin_xy,
                    axis_unit_vector=axis_unit_vector,
                    clip_geometry=road_context_clip_geometry,
                )
            )
        )
    if road_context_offsets:
        candidate_offsets.extend(road_context_offsets)
        contextual_min_offset = min(contextual_min_offset, float(min(road_context_offsets)))
        contextual_max_offset = max(contextual_max_offset, float(max(road_context_offsets)))

    if not candidate_offsets:
        return event_span_window

    extra_pad_m = max(float(EVENT_ANCHOR_BUFFER_M) * 1.5, float(EVENT_SPAN_MARGIN_M), 6.0)
    component_context_extend_cap_m = max(extra_pad_m, float(EVENT_SPAN_LOCAL_CONTEXT_PAD_M), 12.0)
    refined_start = max(
        -CHAIN_CONTEXT_EVENT_SPAN_M,
        float(min(candidate_offsets) - extra_pad_m),
        float(contextual_min_offset - component_context_extend_cap_m),
    )
    refined_end = min(
        CHAIN_CONTEXT_EVENT_SPAN_M,
        float(max(candidate_offsets) + extra_pad_m),
        float(contextual_max_offset + component_context_extend_cap_m),
    )
    if refined_end - refined_start <= EVENT_SPAN_MARGIN_M * 2.0:
        return event_span_window

    refined_window = dict(event_span_window)
    refined_window["start_offset_m"] = float(refined_start)
    refined_window["end_offset_m"] = float(refined_end)
    refined_window["semantic_protected_start_m"] = float(refined_start)
    refined_window["semantic_protected_end_m"] = float(refined_end)
    refined_window["expansion_source"] = "complex_divstrip_component_context"
    return refined_window

def _resolve_parallel_centerline_candidate(
    *,
    local_roads: list[ParsedRoad],
    selected_road_ids: set[str],
    excluded_road_ids: set[str] | None = None,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    reference_point: Point,
    parallel_side_sign: int | None = None,
):
    if axis_centerline is None or axis_centerline.is_empty or axis_unit_vector is None:
        return None, None
    ux, uy = axis_unit_vector
    parallel_side_sign_value = int(parallel_side_sign) if parallel_side_sign in (-1, 1) else None
    axis_reference_s = float(axis_centerline.project(reference_point))

    def _signed_side(road_geometry) -> int | None:
        if road_geometry is None or road_geometry.is_empty:
            return None
        try:
            axis_nearest_point, road_nearest_point = nearest_points(axis_centerline, road_geometry)
        except Exception:
            return None
        dx = float(road_nearest_point.x) - float(axis_nearest_point.x)
        dy = float(road_nearest_point.y) - float(axis_nearest_point.y)
        side = float(ux) * float(dy) - float(uy) * float(dx)
        if abs(float(side)) <= float(PARALLEL_SIDE_SIGN_EPS_M):
            return None
        return 1 if side > 0 else -1

    def _road_axis_alignment(road_geometry) -> float | None:
        if road_geometry is None or road_geometry.is_empty:
            return None
        coords = list(road_geometry.coords)
        if len(coords) < 2:
            return None
        start_x, start_y = _coord_xy(coords[0])
        end_x, end_y = _coord_xy(coords[-1])
        road_vector = _normalize_axis_vector((end_x - start_x, end_y - start_y))
        if road_vector is None:
            return None
        dot = abs(float(road_vector[0]) * ux + float(road_vector[1]) * uy)
        dot = max(-1.0, min(1.0, dot))
        return math.degrees(math.acos(dot))

    candidates: list[tuple[tuple[float, float, float, float], str, Any]] = []
    candidates_within_side: list[tuple[tuple[float, float, float, float], str, Any]] = []
    excluded_road_ids = {str(road_id) for road_id in (excluded_road_ids or set())}
    for road in local_roads:
        if road.road_id in selected_road_ids or road.road_id in excluded_road_ids:
            continue
        angle_diff = _road_axis_alignment(road.geometry)
        if angle_diff is None or angle_diff > PARALLEL_ROAD_ANGLE_TOLERANCE_DEG:
            continue
        try:
            axis_nearest_point, road_nearest_point = nearest_points(axis_centerline, road.geometry)
        except Exception:
            continue
        axis_s = float(axis_centerline.project(axis_nearest_point))
        if abs(axis_s - axis_reference_s) > PARALLEL_CENTERLINE_AXIS_WINDOW_M:
            continue
        distance_to_axis = float(road_nearest_point.distance(axis_nearest_point))
        if distance_to_axis < PARALLEL_ROAD_MIN_OFFSET_M or distance_to_axis > PARALLEL_ROAD_MAX_OFFSET_M:
            continue
        candidate_side = _signed_side(road.geometry)
        candidate = (
            (
                distance_to_axis,
                abs(axis_s - axis_reference_s),
                float(road.geometry.distance(reference_point)),
                -float(road.geometry.length),
            ),
            str(road.road_id),
            road.geometry,
        )
        candidates.append(candidate)
        if parallel_side_sign_value is not None and candidate_side == parallel_side_sign_value:
            candidates_within_side.append(candidate)
        elif parallel_side_sign_value is None:
            candidates_within_side.append(candidate)

    if parallel_side_sign_value is not None and candidates_within_side:
        candidates = candidates_within_side
    if not candidates:
        return None, None
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1], candidates[0][2]


def _resolve_parallel_centerline(
    *,
    local_roads: list[ParsedRoad],
    selected_road_ids: set[str],
    excluded_road_ids: set[str] | None = None,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    reference_point: Point,
    parallel_side_sign: int | None = None,
):
    return _resolve_parallel_centerline_candidate(
        local_roads=local_roads,
        selected_road_ids=selected_road_ids,
        excluded_road_ids=excluded_road_ids,
        axis_centerline=axis_centerline,
        axis_unit_vector=axis_unit_vector,
        reference_point=reference_point,
        parallel_side_sign=parallel_side_sign,
    )[1]


def _collect_parallel_excluded_road_ids(
    *,
    local_roads: list[ParsedRoad],
    selected_road_ids: set[str],
    member_node_ids: set[str],
    semantic_boundary_node_ids: set[str] | None,
    event_anchor_geometry,
    divstrip_constraint_geometry,
    reference_geometries: list[Any],
) -> set[str]:
    excluded_road_ids = {str(road_id) for road_id in selected_road_ids}
    normalized_member_node_ids = {
        normalize_id(node_id)
        for node_id in member_node_ids
        if normalize_id(node_id) is not None
    }
    normalized_semantic_boundary_node_ids = {
        normalize_id(node_id)
        for node_id in (semantic_boundary_node_ids or set())
        if normalize_id(node_id) is not None
    }
    guard_geometries = [
        geometry
        for geometry in [
            event_anchor_geometry,
            divstrip_constraint_geometry,
            *reference_geometries,
        ]
        if geometry is not None and not geometry.is_empty
    ]
    guard_geometry = unary_union(guard_geometries) if guard_geometries else GeometryCollection()
    if guard_geometry is not None and not guard_geometry.is_empty:
        guard_geometry = guard_geometry.buffer(
            max(2.5, ROAD_BUFFER_M * 1.25, RC_ROAD_BUFFER_M),
            cap_style=2,
            join_style=2,
        )

    for road in local_roads:
        if road.road_id in excluded_road_ids:
            continue
        snodeid = normalize_id(road.snodeid)
        enodeid = normalize_id(road.enodeid)
        if snodeid in normalized_member_node_ids or enodeid in normalized_member_node_ids:
            excluded_road_ids.add(str(road.road_id))
            continue
        if snodeid in normalized_semantic_boundary_node_ids or enodeid in normalized_semantic_boundary_node_ids:
            excluded_road_ids.add(str(road.road_id))
            continue
        if (
            guard_geometry is not None
            and not guard_geometry.is_empty
            and road.geometry is not None
            and not road.geometry.is_empty
            and road.geometry.intersects(guard_geometry)
        ):
            excluded_road_ids.add(str(road.road_id))
    return excluded_road_ids


def _resolve_parallel_side_sign(
    *,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    reference_geometries: list[Any],
) -> int | None:
    if axis_centerline is None or axis_centerline.is_empty or axis_unit_vector is None:
        return None
    ux, uy = axis_unit_vector
    positive_weight = 0.0
    negative_weight = 0.0
    for geometry in reference_geometries:
        if geometry is None or geometry.is_empty:
            continue
        try:
            axis_nearest_point, road_nearest_point = nearest_points(axis_centerline, geometry)
        except Exception:
            continue
        axis_distance = float(axis_centerline.distance(geometry))
        if axis_distance > PARALLEL_CENTERLINE_REFERENCE_DISTANCE_M:
            continue
        dx = float(road_nearest_point.x) - float(axis_nearest_point.x)
        dy = float(road_nearest_point.y) - float(axis_nearest_point.y)
        side = float(ux) * float(dy) - float(uy) * float(dx)
        if abs(float(side)) <= float(PARALLEL_SIDE_SIGN_EPS_M):
            continue
        side_weight = (
            (abs(side) / max(float(PARALLEL_CENTERLINE_REFERENCE_DISTANCE_M), 1.0))
            * (1.0 - axis_distance / max(float(PARALLEL_CENTERLINE_REFERENCE_DISTANCE_M), 1.0))
        )
        if side_weight < float(PARALLEL_SIDE_SIGN_MIN_WEIGHT):
            continue
        if side > 0:
            positive_weight += side_weight
        else:
            negative_weight += side_weight
    total_weight = float(positive_weight + negative_weight)
    if total_weight <= 0.0:
        return None
    balance_ratio = abs(positive_weight - negative_weight) / total_weight
    if balance_ratio < PARALLEL_SIDE_SIGN_BALANCE_RATIO:
        return None
    return 1 if positive_weight > negative_weight else -1


def _resolve_parallel_side_sign_fallback(
    *,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    reference_geometries: list[Any],
) -> int | None:
    if axis_centerline is None or axis_centerline.is_empty or axis_unit_vector is None:
        return None
    ux, uy = axis_unit_vector
    best_abs_side = 0.0
    best_side: int | None = None
    positive_weight = 0.0
    negative_weight = 0.0
    for geometry in reference_geometries:
        if geometry is None or geometry.is_empty:
            continue
        try:
            axis_nearest_point, road_nearest_point = nearest_points(axis_centerline, geometry)
        except Exception:
            continue
        axis_distance = float(axis_centerline.distance(geometry))
        if axis_distance > float(PARALLEL_SIDE_FALLBACK_REFERENCE_DISTANCE_M):
            continue
        dx = float(road_nearest_point.x) - float(axis_nearest_point.x)
        dy = float(road_nearest_point.y) - float(axis_nearest_point.y)
        side = float(ux) * float(dy) - float(uy) * float(dx)
        if abs(float(side)) <= float(PARALLEL_SIDE_SIGN_EPS_M):
            continue
        # 1m越近权重越大，尽量偏向离 axis 更近的实体道路。
        side_weight = 1.0 / (1.0 + max(float(axis_distance), 0.0))
        if side_weight <= 0.0:
            continue
        side_abs = abs(float(side_weight))
        if side_abs > best_abs_side:
            best_abs_side = side_abs
            best_side = 1 if float(side) > 0.0 else -1
        if side > 0:
            positive_weight += side_weight
        else:
            negative_weight += side_weight
    total_weight = float(positive_weight + negative_weight)
    if total_weight <= 0.0:
        return best_side
    balance_ratio = abs(positive_weight - negative_weight) / total_weight
    if total_weight > 0.0 and balance_ratio < float(PARALLEL_SIDE_FALLBACK_BALANCE_RATIO):
        if best_side is not None:
            return best_side
        return None
    return 1 if positive_weight > negative_weight else -1

def _build_stage4_geometric_support_domain(
    *,
    representative_node: ParsedNode,
    candidate_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    local_divstrip_union,
    drivezone_union,
    drivezone_mask: np.ndarray,
    grid,
    seed_union,
    member_node_ids: set[str],
    group_nodes: list[ParsedNode],
    chain_context: dict[str, Any],
    road_branches: list[dict[str, Any]],
    road_branches_by_id: dict[str, dict[str, Any]],
    road_to_branch: dict[str, dict[str, Any]],
    step4_event_interpretation: Stage4EventInterpretationResult,
    direct_target_rc_nodes: list[ParsedNode],
) -> Stage4GeometricSupportDomain:
    legacy_step5_bridge = step4_event_interpretation.legacy_step5_bridge
    divstrip_context = legacy_step5_bridge.divstrip_context.to_legacy_dict()
    multibranch_context = step4_event_interpretation.multibranch_decision.to_legacy_dict()
    kind_resolution = step4_event_interpretation.kind_resolution.to_legacy_dict()
    operational_kind_2 = step4_event_interpretation.kind_resolution.operational_kind_2
    selected_branch_ids = list(legacy_step5_bridge.selected_branch_ids)
    selected_roads = list(legacy_step5_bridge.selected_roads)
    selected_event_roads = list(legacy_step5_bridge.selected_event_roads)
    selected_rcsd_roads = list(legacy_step5_bridge.selected_rcsd_roads)
    selected_rcsd_nodes = list(legacy_step5_bridge.selected_rcsd_nodes)
    complex_local_support_roads = list(legacy_step5_bridge.complex_local_support_roads)
    seed_support_geometries = list(legacy_step5_bridge.seed_support_geometries)
    divstrip_constraint_geometry = legacy_step5_bridge.divstrip_constraint_geometry
    event_anchor_geometry = legacy_step5_bridge.event_anchor_geometry
    event_axis_centerline = legacy_step5_bridge.event_axis_centerline
    boundary_branch_a = legacy_step5_bridge.boundary_branch_a
    boundary_branch_b = legacy_step5_bridge.boundary_branch_b
    branch_a_centerline = legacy_step5_bridge.branch_a_centerline
    branch_b_centerline = legacy_step5_bridge.branch_b_centerline
    event_cross_half_len_m = legacy_step5_bridge.event_cross_half_len_m
    event_reference = dict(legacy_step5_bridge.event_reference_raw)
    event_origin_point = legacy_step5_bridge.event_origin_point
    event_axis_unit_vector = legacy_step5_bridge.event_axis_unit_vector

    parallel_side_reference_geometries = [
        road.geometry
        for road in selected_event_roads
        if road.geometry is not None and not road.geometry.is_empty
    ]
    if not parallel_side_reference_geometries:
        parallel_side_reference_geometries = [
            road.geometry
            for road in selected_roads
            if road.geometry is not None and not road.geometry.is_empty
        ] or [
            road.geometry
            for road in selected_rcsd_roads
            if road.geometry is not None and not road.geometry.is_empty
        ]
    parallel_side_reference_geometries += [
        road.geometry
        for road in selected_rcsd_roads
        if road.geometry is not None
        and not road.geometry.is_empty
        and road.geometry not in parallel_side_reference_geometries
    ]
    other_semantic_boundary_node_ids = {
        node.node_id
        for node in local_nodes
        if _is_semantic_boundary_representative(node)
        and normalize_id(node.mainnodeid or node.node_id) not in {
            normalize_id(representative_node.mainnodeid or representative_node.node_id),
            *{
                normalize_id(mainnodeid)
                for mainnodeid in chain_context.get("related_mainnodeids", ())
                if normalize_id(mainnodeid) is not None
            },
        }
    }
    parallel_excluded_road_ids = _collect_parallel_excluded_road_ids(
        local_roads=local_roads,
        selected_road_ids=set(legacy_step5_bridge.selected_road_ids),
        member_node_ids=member_node_ids,
        semantic_boundary_node_ids=other_semantic_boundary_node_ids,
        event_anchor_geometry=event_anchor_geometry,
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        reference_geometries=parallel_side_reference_geometries,
    )
    parallel_side_sign = _resolve_parallel_side_sign(
        axis_centerline=event_axis_centerline,
        axis_unit_vector=event_axis_unit_vector,
        reference_geometries=parallel_side_reference_geometries,
    )
    if parallel_side_sign is None:
        parallel_side_sign = _resolve_parallel_side_sign_fallback(
            axis_centerline=event_axis_centerline,
            axis_unit_vector=event_axis_unit_vector,
            reference_geometries=parallel_side_reference_geometries,
        )
    parallel_centerline_road_id, parallel_centerline = _resolve_parallel_centerline_candidate(
        local_roads=local_roads,
        selected_road_ids=set(legacy_step5_bridge.selected_road_ids),
        excluded_road_ids=parallel_excluded_road_ids,
        axis_centerline=event_axis_centerline,
        axis_unit_vector=event_axis_unit_vector,
        reference_point=event_origin_point,
        parallel_side_sign=parallel_side_sign,
    )
    has_parallel_competitor = parallel_centerline is not None and not parallel_centerline.is_empty
    selected_roads_geometry = (
        unary_union([road.geometry for road in selected_roads if road.geometry is not None and not road.geometry.is_empty])
        if selected_roads
        else GeometryCollection()
    )
    selected_event_roads_geometry = (
        unary_union([road.geometry for road in selected_event_roads if road.geometry is not None and not road.geometry.is_empty])
        if selected_event_roads
        else GeometryCollection()
    )
    selected_rcsd_roads_geometry = (
        unary_union([road.geometry for road in selected_rcsd_roads if road.geometry is not None and not road.geometry.is_empty])
        if selected_rcsd_roads
        else GeometryCollection()
    )
    selected_support_union = unary_union(
        [
            geometry
            for geometry in [*[road.geometry for road in selected_roads], *[road.geometry for road in selected_rcsd_roads]]
            if geometry is not None and not geometry.is_empty
        ]
    )
    event_span_window_base = _resolve_event_span_window(
        origin_point=event_origin_point,
        axis_unit_vector=event_axis_unit_vector,
        selected_rcsd_nodes=direct_target_rc_nodes,
        event_anchor_geometry=event_anchor_geometry,
        selected_roads_geometry=selected_roads_geometry,
        selected_event_roads_geometry=selected_event_roads_geometry,
        selected_rcsd_roads_geometry=selected_rcsd_roads_geometry,
    )
    event_span_window = dict(event_span_window_base)
    if (
        kind_resolution["complex_junction"]
        and chain_context["sequential_ok"]
        and chain_context["related_seed_nodes"]
        and len(divstrip_context["selected_component_ids"]) <= 1
    ):
        chain_related_offsets: list[float] = []
        for candidate_node in chain_context["related_seed_nodes"]:
            candidate_offset = _project_point_to_axis(
                candidate_node.geometry,
                origin_xy=(float(event_origin_point.x), float(event_origin_point.y)),
                axis_unit_vector=event_axis_unit_vector,
            )
            if math.isfinite(float(candidate_offset)):
                chain_related_offsets.append(float(candidate_offset))
        if chain_related_offsets:
            event_min_offset = float(min(chain_related_offsets))
            event_max_offset = float(max(chain_related_offsets))
            event_span_window["start_offset_m"] = float(
                max(
                    -CHAIN_CONTEXT_EVENT_SPAN_M,
                    min(
                        float(event_span_window["start_offset_m"]),
                        event_min_offset - EVENT_SPAN_MARGIN_M,
                    ),
                )
            )
            event_span_window["end_offset_m"] = float(
                min(
                    CHAIN_CONTEXT_EVENT_SPAN_M,
                    max(
                        float(event_span_window["end_offset_m"]),
                        event_max_offset + EVENT_SPAN_MARGIN_M,
                    ),
                )
            )
            event_span_window["candidate_offset_count"] = int(event_span_window["candidate_offset_count"]) + len(chain_related_offsets)
            event_span_window["expansion_source"] = "continuous_chain_context"
    event_span_window_after_chain = dict(event_span_window)
    event_span_window = _refine_event_span_window_by_semantic_context(
        event_span_window=event_span_window,
        candidate_nodes=candidate_nodes,
        semantic_member_nodes=[
            *group_nodes,
            *(
                chain_context["related_seed_nodes"]
                if kind_resolution["complex_junction"] and len(divstrip_context["selected_component_ids"]) <= 1
                else []
            ),
        ],
        group_nodes=group_nodes,
        representative_node=representative_node,
        related_mainnodeids=(
            chain_context["related_mainnodeids"]
            if kind_resolution["complex_junction"]
            else []
        ),
        origin_point=event_origin_point,
        axis_unit_vector=event_axis_unit_vector,
        axis_centerline=event_axis_centerline,
        event_anchor_geometry=event_anchor_geometry,
        selected_roads=selected_roads,
        include_complex_members=kind_resolution["complex_junction"] or len(group_nodes) > 1,
    )
    event_span_window_after_semantic = dict(event_span_window)
    event_span_window = _refine_complex_event_span_window_by_divstrip_context(
        event_span_window=event_span_window,
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        selected_roads_geometry=selected_roads_geometry,
        selected_event_roads_geometry=selected_event_roads_geometry,
        selected_rcsd_roads_geometry=selected_rcsd_roads_geometry,
        origin_point=event_origin_point,
        axis_unit_vector=event_axis_unit_vector,
        selected_component_count=len(divstrip_context["selected_component_ids"]),
        is_complex_junction=kind_resolution["complex_junction"] or len(group_nodes) > 1,
    )
    event_span_window_after_divstrip_complex = dict(event_span_window)
    event_span_window = _clip_simple_event_span_window_by_divstrip_context(
        event_span_window=event_span_window,
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        direct_target_rc_nodes=direct_target_rc_nodes,
        selected_roads=selected_roads,
        origin_point=event_origin_point,
        axis_unit_vector=event_axis_unit_vector,
        selected_component_count=len(divstrip_context["selected_component_ids"]),
        is_complex_junction=kind_resolution["complex_junction"] or len(group_nodes) > 1,
        event_split_pick_source=event_reference["split_pick_source"],
    )
    event_span_window_final = dict(event_span_window)
    axis_window_mask = _build_axis_window_mask(
        grid=grid,
        origin_point=event_origin_point,
        axis_unit_vector=event_axis_unit_vector,
        start_offset_m=event_span_window["start_offset_m"],
        end_offset_m=event_span_window["end_offset_m"],
    )
    axis_window_geometry = _build_axis_window_geometry(
        origin_point=event_origin_point,
        axis_unit_vector=event_axis_unit_vector,
        start_offset_m=event_span_window["start_offset_m"],
        end_offset_m=event_span_window["end_offset_m"],
        cross_half_len_m=event_cross_half_len_m,
    )
    parallel_side_mask = None
    if parallel_side_sign in (-1, 1) and len(parallel_excluded_road_ids) > 0:
        parallel_side_mask = _build_axis_side_halfmask(
            grid=grid,
            origin_point=event_origin_point,
            axis_unit_vector=event_axis_unit_vector,
            parallel_side_sign=parallel_side_sign,
        )
        if parallel_side_mask is not None and axis_window_mask is not None:
            parallel_side_mask = parallel_side_mask & axis_window_mask
    parallel_side_geometry = GeometryCollection()
    parallel_side_sample_count = 0
    if parallel_centerline is not None and not parallel_centerline.is_empty:
        parallel_side_geometry, parallel_side_sample_count = _build_cross_section_surface_geometry(
            drivezone_union=drivezone_union,
            origin_point=event_origin_point,
            axis_unit_vector=event_axis_unit_vector,
            start_offset_m=event_span_window["start_offset_m"],
            end_offset_m=event_span_window["end_offset_m"],
            cross_half_len_m=event_cross_half_len_m,
            axis_centerline=event_axis_centerline,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            parallel_centerline=parallel_centerline,
            resolution_m=grid.resolution_m,
            support_geometry=None,
        )
        if parallel_side_geometry is not None and not parallel_side_geometry.is_empty:
            parallel_side_geometry = parallel_side_geometry.intersection(drivezone_union).buffer(0)
    if parallel_side_geometry is not None and not parallel_side_geometry.is_empty:
        parallel_side_mask = _rasterize_geometries(grid, [parallel_side_geometry]) & drivezone_mask
    elif parallel_side_mask is not None and parallel_side_mask.any():
        parallel_side_mask = parallel_side_mask & drivezone_mask
        parallel_side_geometry = _mask_to_geometry(parallel_side_mask, grid)
    selected_event_road_support_union = unary_union(
        [
            road.geometry
            for road in selected_event_roads
            if road.geometry is not None and not road.geometry.is_empty
        ]
    )
    event_branch_support_geometries = [
        road.geometry
        for road in selected_event_roads
        if road.geometry is not None and not road.geometry.is_empty
    ]
    event_branch_support_geometries.extend(
        road.geometry
        for road in complex_local_support_roads
        if road.geometry is not None and not road.geometry.is_empty
    )
    if selected_event_roads and not selected_event_road_support_union.is_empty:
        event_branch_support_geometries.extend(
            road.geometry
            for road in selected_rcsd_roads
            if road.geometry is not None
            and not road.geometry.is_empty
            and selected_event_road_support_union.buffer(
                max(ROAD_BUFFER_M * 2.5, RC_ROAD_BUFFER_M * 2.0, 6.0),
                cap_style=2,
                join_style=2,
            ).intersects(road.geometry)
        )
    event_branch_support_union = unary_union(event_branch_support_geometries)
    event_side_drivezone_buffer_m = max(ROAD_BUFFER_M * 2.8, RC_ROAD_BUFFER_M * 2.2, 7.5)
    if kind_resolution["complex_junction"] and len(divstrip_context["selected_component_ids"]) > 1:
        event_side_drivezone_buffer_m = max(event_side_drivezone_buffer_m, 18.0)
    event_side_clip_geometry = axis_window_geometry
    if kind_resolution["complex_junction"] and len(divstrip_context["selected_component_ids"]) > 1:
        event_side_clip_geometry = None
    allow_full_axis_drivezone_fill = (
        not kind_resolution["complex_junction"]
        and not multibranch_context["enabled"]
        and len(divstrip_context["selected_component_ids"]) <= 1
        and not has_parallel_competitor
        and event_side_clip_geometry is not None
        and not event_side_clip_geometry.is_empty
    )
    full_fill_start_offset_m = float(event_span_window["start_offset_m"])
    full_fill_end_offset_m = float(event_span_window["end_offset_m"])
    if allow_full_axis_drivezone_fill:
        full_fill_start_offset_m = min(full_fill_start_offset_m, -FULL_FILL_SPAN_HALF_MIN_M)
        full_fill_end_offset_m = max(full_fill_end_offset_m, FULL_FILL_SPAN_HALF_MIN_M)
        _sem_prev = event_span_window.get("semantic_prev_boundary_offset_m")
        _sem_next = event_span_window.get("semantic_next_boundary_offset_m")
        if _sem_prev is not None:
            full_fill_start_offset_m = max(full_fill_start_offset_m, float(_sem_prev))
        if _sem_next is not None:
            full_fill_end_offset_m = min(full_fill_end_offset_m, float(_sem_next))
        wide_axis_window = _build_axis_window_geometry(
            origin_point=event_origin_point,
            axis_unit_vector=event_axis_unit_vector,
            start_offset_m=full_fill_start_offset_m,
            end_offset_m=full_fill_end_offset_m,
            cross_half_len_m=max(event_cross_half_len_m, EVENT_CROSS_HALF_LEN_MAX_M * 2.0),
        )
        if not wide_axis_window.is_empty:
            event_side_clip_geometry = wide_axis_window
    event_side_drivezone_geometry = (
        drivezone_union.intersection(event_side_clip_geometry).buffer(0)
        if allow_full_axis_drivezone_fill
        else (
            GeometryCollection()
            if event_branch_support_union.is_empty
            else drivezone_union.intersection(
                event_branch_support_union.buffer(
                    event_side_drivezone_buffer_m,
                    cap_style=2,
                    join_style=2,
                )
            ).buffer(0)
        )
    )
    if event_side_clip_geometry is not None and not event_side_clip_geometry.is_empty and event_side_drivezone_geometry is not None and not event_side_drivezone_geometry.is_empty:
        event_side_drivezone_geometry = event_side_drivezone_geometry.intersection(event_side_clip_geometry).buffer(0)
    if parallel_side_geometry is not None and not parallel_side_geometry.is_empty and event_side_drivezone_geometry is not None and not event_side_drivezone_geometry.is_empty:
        event_side_drivezone_geometry = event_side_drivezone_geometry.intersection(parallel_side_geometry).buffer(0)
    event_cross_section_support_geometry = unary_union(
        [
            road.geometry.buffer(max(ROAD_BUFFER_M * 1.5, RC_ROAD_BUFFER_M * 1.25, 2.25), cap_style=2, join_style=2)
            for road in [*selected_roads, *selected_rcsd_roads, *complex_local_support_roads]
            if road.geometry is not None and not road.geometry.is_empty
        ]
    )
    cross_section_support_geometry = (
        None
        if (
            allow_full_axis_drivezone_fill
            or kind_resolution["complex_junction"]
            or multibranch_context["enabled"]
            or len(divstrip_context["selected_component_ids"]) > 1
        )
        else event_cross_section_support_geometry
    )
    full_fill_cross_half_len_m = (
        max(event_cross_half_len_m, EVENT_CROSS_HALF_LEN_MAX_M * 2.0)
        if allow_full_axis_drivezone_fill
        else event_cross_half_len_m
    )
    cross_section_surface_geometry, cross_section_sample_count = _build_cross_section_surface_geometry(
        drivezone_union=drivezone_union,
        origin_point=event_origin_point,
        axis_unit_vector=event_axis_unit_vector,
        start_offset_m=full_fill_start_offset_m if allow_full_axis_drivezone_fill else event_span_window["start_offset_m"],
        end_offset_m=full_fill_end_offset_m if allow_full_axis_drivezone_fill else event_span_window["end_offset_m"],
        cross_half_len_m=full_fill_cross_half_len_m,
        axis_centerline=event_axis_centerline,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
        parallel_centerline=parallel_centerline,
        resolution_m=grid.resolution_m,
        support_geometry=cross_section_support_geometry,
    )
    selected_component_offsets_on_axis = _collect_axis_offsets_from_geometry(
        divstrip_constraint_geometry,
        origin_xy=(float(event_origin_point.x), float(event_origin_point.y)),
        axis_unit_vector=event_axis_unit_vector,
    )
    selected_component_exceeds_event_span = bool(selected_component_offsets_on_axis) and (
        min(selected_component_offsets_on_axis) < float(event_span_window["start_offset_m"]) - 5.0
        or max(selected_component_offsets_on_axis) > float(event_span_window["end_offset_m"]) + 5.0
    )
    selected_component_force_surface = (
        multibranch_context["enabled"]
        and kind_resolution["complex_junction"]
        and len(divstrip_context["selected_component_ids"]) == 2
    )
    selected_component_surface_diags: list[dict[str, Any]] = []
    component_side_clip_buffer_m = float(EVENT_COMPONENT_SIDE_CLIP_BUFFER_M)
    if kind_resolution["complex_junction"] and multibranch_context["enabled"]:
        component_side_clip_buffer_m = min(component_side_clip_buffer_m, 6.0)
    if (
        len(divstrip_context["selected_component_ids"]) > 1
        and (
            selected_component_exceeds_event_span
            or selected_component_force_surface
            or kind_resolution["complex_junction"]
            or chain_context["sequential_ok"]
            or len(group_nodes) > 1
        )
    ):
        selected_component_surface_geometry, selected_component_surface_diags = _build_selected_divstrip_component_surface_union(
            representative_node=representative_node,
            main_origin_point=event_origin_point,
            axis_centerline=event_axis_centerline,
            axis_unit_vector=event_axis_unit_vector,
            kind_2=operational_kind_2,
            road_branches=road_branches,
            selected_branch_ids=set(selected_branch_ids),
            multibranch_event_candidates=multibranch_context.get("event_candidates"),
            boundary_branch_a=boundary_branch_a,
            boundary_branch_b=boundary_branch_b,
            road_lookup={road.road_id: road for road in local_roads},
            divstrip_constraint_geometry=divstrip_constraint_geometry,
            drivezone_union=drivezone_union,
            parallel_centerline=parallel_centerline,
            resolution_m=grid.resolution_m,
            cross_half_len_m=event_cross_half_len_m,
            support_geometry=event_cross_section_support_geometry,
            allow_extended_connector_span=bool(
                kind_resolution["complex_junction"]
                and len(group_nodes) > 1
                and len(divstrip_context["selected_component_ids"]) == 2
            ),
        )
        if selected_component_surface_geometry is not None and not selected_component_surface_geometry.is_empty:
            if cross_section_surface_geometry is None or cross_section_surface_geometry.is_empty:
                cross_section_surface_geometry = selected_component_surface_geometry
            cross_section_sample_count = max(
                int(cross_section_sample_count),
                int(
                    sum(
                        int(item.get("sample_count", 0))
                        for item in selected_component_surface_diags
                        if bool(item.get("ok", False))
                    )
                ),
            )
    multi_component_surface_applied = bool(
        selected_component_surface_diags
        and any(
            bool(item.get("ok", False)) and item.get("component_index") != "connector"
            for item in selected_component_surface_diags
        )
    )
    selected_component_surface_ok_count = sum(
        1
        for item in selected_component_surface_diags
        if item.get("component_index") != "connector" and bool(item.get("ok", False))
    )
    prefer_component_surface_only_for_complex_case = bool(
        kind_resolution["complex_junction"]
        and len(divstrip_context["selected_component_ids"]) > 1
        and selected_component_surface_ok_count >= len(divstrip_context["selected_component_ids"])
        and not (
            multibranch_context["enabled"]
            and step4_event_interpretation.continuous_chain_decision.applied_to_event_interpretation
            and step4_event_interpretation.continuous_chain_decision.is_in_continuous_chain
            and step4_event_interpretation.continuous_chain_decision.sequential_ok
        )
    )
    if multi_component_surface_applied and cross_section_surface_geometry is not None and not cross_section_surface_geometry.is_empty:
        component_axis_window_geometry = cross_section_surface_geometry.buffer(
            component_side_clip_buffer_m,
            cap_style=2,
            join_style=2,
        ).intersection(drivezone_union).buffer(0)
        if not component_axis_window_geometry.is_empty:
            axis_window_geometry = (
                component_axis_window_geometry
                if axis_window_geometry is None or axis_window_geometry.is_empty
                else unary_union([axis_window_geometry, component_axis_window_geometry]).intersection(drivezone_union).buffer(0)
            )
            axis_window_mask = (
                axis_window_mask | _rasterize_geometries(grid, [component_axis_window_geometry])
            ) & drivezone_mask
            if parallel_side_geometry is not None and not parallel_side_geometry.is_empty:
                parallel_side_geometry = parallel_side_geometry.union(cross_section_surface_geometry).intersection(drivezone_union).buffer(0)
            if parallel_side_mask is not None:
                parallel_side_mask = (
                    parallel_side_mask | _rasterize_geometries(grid, [cross_section_surface_geometry])
                ) & drivezone_mask
    complex_multibranch_lobe_geometry = GeometryCollection()
    complex_multibranch_lobe_diags: list[dict[str, Any]] = []
    if (
        kind_resolution["complex_junction"]
        and multibranch_context["enabled"]
        and len(divstrip_context["selected_component_ids"]) > 1
    ):
        complex_multibranch_lobe_geometry, complex_multibranch_lobe_diags = _build_complex_multibranch_lobe_union(
            multibranch_context=multibranch_context,
            representative_node=representative_node,
            axis_centerline=event_axis_centerline,
            axis_unit_vector=event_axis_unit_vector,
            kind_2=operational_kind_2,
            drivezone_union=drivezone_union,
            divstrip_geometry=divstrip_constraint_geometry,
            road_lookup={road.road_id: road for road in local_roads},
            road_to_branch=road_to_branch,
            road_branches_by_id=road_branches_by_id,
            parallel_centerline=parallel_centerline,
            resolution_m=grid.resolution_m,
            cross_half_len_m=event_cross_half_len_m,
        )
        if (
            complex_multibranch_lobe_geometry is not None
            and not complex_multibranch_lobe_geometry.is_empty
            and not prefer_component_surface_only_for_complex_case
        ):
            if cross_section_surface_geometry is None or cross_section_surface_geometry.is_empty:
                cross_section_surface_geometry = complex_multibranch_lobe_geometry
            cross_section_sample_count = max(
                int(cross_section_sample_count),
                int(
                    sum(
                        int(item.get("sample_count", 0))
                        for item in complex_multibranch_lobe_diags
                        if bool(item.get("ok", False))
                    )
                ),
            )
            lobe_axis_window_geometry = complex_multibranch_lobe_geometry.buffer(
                component_side_clip_buffer_m,
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union).buffer(0)
            if not lobe_axis_window_geometry.is_empty:
                axis_window_geometry = (
                    lobe_axis_window_geometry
                    if axis_window_geometry is None or axis_window_geometry.is_empty
                    else unary_union([axis_window_geometry, lobe_axis_window_geometry]).intersection(drivezone_union).buffer(0)
                )
                axis_window_mask = (
                    axis_window_mask | _rasterize_geometries(grid, [lobe_axis_window_geometry])
                ) & drivezone_mask
            if parallel_side_geometry is not None and not parallel_side_geometry.is_empty:
                parallel_side_geometry = (
                    parallel_side_geometry.union(complex_multibranch_lobe_geometry)
                    .intersection(drivezone_union)
                    .buffer(0)
                )
            if parallel_side_mask is not None:
                parallel_side_mask = (
                    parallel_side_mask | _rasterize_geometries(grid, [complex_multibranch_lobe_geometry])
                ) & drivezone_mask
    group_node_fact_surface_diags: list[dict[str, Any]] = []
    if (
        kind_resolution["complex_junction"]
        and len(group_nodes) > 1
        and event_axis_centerline is not None
        and not event_axis_centerline.is_empty
        and event_axis_unit_vector is not None
    ):
        group_node_fact_surface_geometry, group_node_fact_surface_diags = _build_group_node_fact_support_surface_union(
            representative_node=representative_node,
            group_nodes=group_nodes,
            existing_surface_geometry=cross_section_surface_geometry,
            axis_centerline=event_axis_centerline,
            axis_unit_vector=event_axis_unit_vector,
            kind_2=operational_kind_2,
            road_branches=road_branches,
            selected_branch_ids=set(selected_branch_ids),
            road_lookup={road.road_id: road for road in local_roads},
            drivezone_union=drivezone_union,
            parallel_centerline=parallel_centerline,
            resolution_m=grid.resolution_m,
            cross_half_len_m=event_cross_half_len_m,
        )
        if group_node_fact_surface_diags:
            selected_component_surface_diags.extend(group_node_fact_surface_diags)
        if group_node_fact_surface_geometry is not None and not group_node_fact_surface_geometry.is_empty:
            cross_section_surface_geometry = (
                group_node_fact_surface_geometry
                if cross_section_surface_geometry is None or cross_section_surface_geometry.is_empty
                else unary_union([cross_section_surface_geometry, group_node_fact_surface_geometry])
                .intersection(drivezone_union)
                .buffer(0)
            )
            cross_section_sample_count = max(
                int(cross_section_sample_count),
                int(
                    sum(
                        int(item.get("sample_count", 0))
                        for item in group_node_fact_surface_diags
                        if bool(item.get("ok", False))
                    )
                ),
            )
            group_axis_window_geometry = group_node_fact_surface_geometry.buffer(
                component_side_clip_buffer_m,
                cap_style=2,
                join_style=2,
            ).intersection(drivezone_union).buffer(0)
            if not group_axis_window_geometry.is_empty:
                axis_window_geometry = (
                    group_axis_window_geometry
                    if axis_window_geometry is None or axis_window_geometry.is_empty
                    else unary_union([axis_window_geometry, group_axis_window_geometry])
                    .intersection(drivezone_union)
                    .buffer(0)
                )
                axis_window_mask = (
                    axis_window_mask | _rasterize_geometries(grid, [group_axis_window_geometry])
                ) & drivezone_mask
            if parallel_side_geometry is not None and not parallel_side_geometry.is_empty:
                parallel_side_geometry = (
                    parallel_side_geometry.union(group_node_fact_surface_geometry)
                    .intersection(drivezone_union)
                    .buffer(0)
                )
            if parallel_side_mask is not None:
                parallel_side_mask = (
                    parallel_side_mask | _rasterize_geometries(grid, [group_node_fact_surface_geometry])
                ) & drivezone_mask
    if (
        len(divstrip_context["selected_component_ids"]) > 1
        and cross_section_surface_geometry is not None
        and not cross_section_surface_geometry.is_empty
        and event_side_drivezone_geometry is not None
        and not event_side_drivezone_geometry.is_empty
    ):
        clipped_event_side_geometry = event_side_drivezone_geometry.intersection(
            cross_section_surface_geometry.buffer(
                component_side_clip_buffer_m,
                cap_style=2,
                join_style=2,
            )
        ).buffer(0)
        if not clipped_event_side_geometry.is_empty:
            event_side_drivezone_geometry = clipped_event_side_geometry
    cross_section_surface_mask = (
        np.zeros_like(drivezone_mask, dtype=bool)
        if cross_section_surface_geometry.is_empty
        else _rasterize_geometries(grid, [cross_section_surface_geometry])
    )
    divstrip_event_window = _build_divstrip_event_window(
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        selected_roads=selected_roads,
        selected_rcsd_roads=selected_rcsd_roads,
        seed_union=seed_union,
        event_anchor_geometry=event_anchor_geometry,
        drivezone_union=drivezone_union,
    )
    local_surface_clip_geometry = _build_local_surface_clip_geometry(
        cross_section_surface_geometry=cross_section_surface_geometry,
        divstrip_event_window=divstrip_event_window,
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        axis_window_geometry=event_side_clip_geometry if allow_full_axis_drivezone_fill else axis_window_geometry,
        drivezone_union=drivezone_union,
        is_complex_junction=bool(kind_resolution["complex_junction"]),
        multibranch_enabled=bool(multibranch_context["enabled"]),
        selected_component_count=len(divstrip_context["selected_component_ids"]),
        allow_full_axis_drivezone_fill=bool(allow_full_axis_drivezone_fill),
    )
    if (
        local_surface_clip_geometry is not None
        and not local_surface_clip_geometry.is_empty
        and event_side_drivezone_geometry is not None
        and not event_side_drivezone_geometry.is_empty
    ):
        clipped_event_side_geometry = event_side_drivezone_geometry.intersection(
            local_surface_clip_geometry
        ).buffer(0)
        if not clipped_event_side_geometry.is_empty:
            event_side_drivezone_geometry = clipped_event_side_geometry
    selected_support_corridor_geometry = GeometryCollection()
    selected_support_corridor_applied = False
    if _should_apply_selected_support_corridor(
        allow_full_axis_drivezone_fill=bool(allow_full_axis_drivezone_fill),
        parallel_competitor_present=bool(has_parallel_competitor),
        parallel_side_geometry=parallel_side_geometry,
        local_surface_clip_geometry=local_surface_clip_geometry,
    ):
        selected_support_corridor_geometry = _build_selected_support_corridor_geometry(
            drivezone_union=drivezone_union,
            clip_geometry=(
                local_surface_clip_geometry
                if local_surface_clip_geometry is not None and not local_surface_clip_geometry.is_empty
                else event_side_clip_geometry
            ),
            selected_support_union=selected_support_union,
            event_anchor_geometry=event_anchor_geometry,
            support_buffer_m=max(event_side_drivezone_buffer_m, ROAD_BUFFER_M * 2.8, RC_ROAD_BUFFER_M * 2.2, 8.0),
        )
        if not selected_support_corridor_geometry.is_empty:
            if local_surface_clip_geometry is not None and not local_surface_clip_geometry.is_empty:
                clipped_local_surface_geometry = local_surface_clip_geometry.intersection(
                    selected_support_corridor_geometry
                ).buffer(0)
                if not clipped_local_surface_geometry.is_empty:
                    local_surface_clip_geometry = clipped_local_surface_geometry
            if event_side_drivezone_geometry is not None and not event_side_drivezone_geometry.is_empty:
                clipped_event_side_geometry = event_side_drivezone_geometry.intersection(
                    selected_support_corridor_geometry
                ).buffer(0)
                if not clipped_event_side_geometry.is_empty:
                    event_side_drivezone_geometry = clipped_event_side_geometry
            parallel_side_geometry = GeometryCollection()
            parallel_side_mask = None
            parallel_side_sample_count = 0
            selected_support_corridor_applied = True
    event_seed_geometries = [
        *[road.geometry.buffer(max(ROAD_BUFFER_M, 1.75), cap_style=2, join_style=2) for road in selected_roads],
        *[road.geometry.buffer(max(RC_ROAD_BUFFER_M, 1.75), cap_style=2, join_style=2) for road in selected_rcsd_roads],
        *[
            node.geometry.buffer(max(RC_NODE_SEED_RADIUS_M, 2.0), join_style=2)
            for node in selected_rcsd_nodes
        ],
    ]
    if event_anchor_geometry is not None and not event_anchor_geometry.is_empty:
        event_seed_geometries.append(
            event_anchor_geometry.buffer(max(EVENT_ANCHOR_BUFFER_M, 2.0), join_style=2)
        )
    event_seed_union = unary_union(
        [
            geometry
            for geometry in event_seed_geometries
            if geometry is not None and not geometry.is_empty
        ]
    )
    seed_mask = _rasterize_geometries(
        grid,
        event_seed_geometries or seed_support_geometries,
    )
    support_geometries = [
        *[road.geometry.buffer(ROAD_BUFFER_M, cap_style=2, join_style=2) for road in selected_roads],
        *[road.geometry.buffer(RC_ROAD_BUFFER_M, cap_style=2, join_style=2) for road in selected_rcsd_roads],
        *seed_support_geometries,
    ]
    support_mask = _rasterize_geometries(grid, support_geometries) & drivezone_mask
    if parallel_side_mask is not None:
        support_mask &= parallel_side_mask
    event_side_support_geometries = []
    if event_side_drivezone_geometry is not None and not event_side_drivezone_geometry.is_empty:
        event_side_support_geometries.append(event_side_drivezone_geometry)
    event_side_support_geometries.extend(
        road.geometry.buffer(max(ROAD_BUFFER_M * 1.8, RC_ROAD_BUFFER_M * 1.4, 2.5), cap_style=2, join_style=2)
        for road in [*selected_roads, *selected_rcsd_roads]
        if road.geometry is not None and not road.geometry.is_empty
    )
    event_side_support_mask = _rasterize_geometries(
        grid,
        event_side_support_geometries,
    ) & drivezone_mask
    if parallel_side_mask is not None:
        event_side_support_mask &= parallel_side_mask
    drivezone_component_mask = None
    if axis_window_mask.any():
        drivezone_component_mask = drivezone_mask & axis_window_mask
    elif divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty:
        drivezone_component_mask = drivezone_mask.copy()
    if drivezone_component_mask is not None:
        drivezone_component_mask = _binary_close(drivezone_component_mask, iterations=1)
    if drivezone_component_mask is not None and parallel_side_mask is not None:
        drivezone_component_mask &= parallel_side_mask
    if drivezone_component_mask is not None and not divstrip_event_window.is_empty:
        drivezone_component_mask |= (drivezone_mask & _rasterize_geometries(grid, [divstrip_event_window]))
        drivezone_component_mask = _binary_close(drivezone_component_mask, iterations=1)
        if parallel_side_mask is not None:
            drivezone_component_mask &= parallel_side_mask
    divstrip_exclusion_geometry = (
        divstrip_constraint_geometry
        if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty
        else local_divstrip_union
    )
    if drivezone_component_mask is not None and divstrip_exclusion_geometry is not None and not divstrip_exclusion_geometry.is_empty:
        divstrip_mask = _rasterize_geometries(
            grid,
            [divstrip_exclusion_geometry.buffer(DIVSTRIP_EXCLUSION_BUFFER_M, join_style=2)],
        )
        drivezone_component_mask &= ~divstrip_mask
    component_mask = (
        _extract_seed_component(drivezone_component_mask, seed_mask)
        if drivezone_component_mask is not None
        else np.zeros_like(drivezone_mask, dtype=bool)
    )
    component_mask_used_support_fallback = False
    if not component_mask.any():
        component_mask_used_support_fallback = True
        if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty:
            divstrip_mask = _rasterize_geometries(
                grid,
                [divstrip_constraint_geometry.buffer(DIVSTRIP_EXCLUSION_BUFFER_M, join_style=2)],
            )
            support_mask = support_mask & ~(divstrip_mask & ~seed_mask)
        support_mask = _binary_close(support_mask, iterations=1)
        component_mask = _extract_seed_component(support_mask, seed_mask)
    if not component_mask.any():
        raise Stage4RunError(
            REASON_MAIN_DIRECTION_UNSTABLE,
            "Stage4 raster support could not form an event-connected component.",
        )
    clipping_mask = axis_window_mask.copy()
    if not allow_full_axis_drivezone_fill:
        if cross_section_surface_mask.any():
            clipping_mask &= (cross_section_surface_mask | event_side_support_mask | seed_mask)
        elif event_side_support_mask.any():
            clipping_mask &= (event_side_support_mask | seed_mask)
    clipped_component_mask = component_mask & clipping_mask
    component_mask_reseeded_after_clip = False
    if clipped_component_mask.any():
        reseeded_component_mask = _extract_seed_component(clipped_component_mask, seed_mask)
        component_mask = reseeded_component_mask if reseeded_component_mask.any() else clipped_component_mask
        component_mask_reseeded_after_clip = True

    span_window = Stage4SpanWindow(
        base=dict(event_span_window_base),
        after_chain=event_span_window_after_chain,
        after_semantic=event_span_window_after_semantic,
        after_divstrip_complex=event_span_window_after_divstrip_complex,
        after_divstrip_simple=event_span_window_final,
        final=event_span_window_final,
    )
    preferred_clip_mode = (
        "local_surface_clip"
        if local_surface_clip_geometry is not None and not local_surface_clip_geometry.is_empty
        else ("axis_window" if axis_window_geometry is not None and not axis_window_geometry.is_empty else "none")
    )
    event_side_clip_mode = (
        "selected_support_corridor"
        if selected_support_corridor_applied
        else (
            "full_axis_drivezone_fill"
            if allow_full_axis_drivezone_fill
            else ("branch_support_buffer" if not event_branch_support_union.is_empty else "axis_window")
        )
    )
    exclusion_context = Stage4ExclusionGeometryContext(
        source_priority=("rcsd", "swsd", "road_geometry"),
        parallel_excluded_road_ids=tuple(sorted(str(item) for item in parallel_excluded_road_ids)),
        parallel_side_sign=parallel_side_sign,
        parallel_centerline_road_id=parallel_centerline_road_id,
        parallel_competitor_present=has_parallel_competitor,
        selected_support_corridor_applied=selected_support_corridor_applied,
        divstrip_exclusion_source=(
            "selected_component"
            if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty
            else ("local_divstrip_union" if local_divstrip_union is not None and not local_divstrip_union.is_empty else "none")
        ),
        divstrip_event_window_present=not divstrip_event_window.is_empty,
        local_surface_clip_present=local_surface_clip_geometry is not None and not local_surface_clip_geometry.is_empty,
        geometry_window_clamped=(
            float(event_span_window_base["start_offset_m"]) != float(event_span_window_final["start_offset_m"])
            or float(event_span_window_base["end_offset_m"]) != float(event_span_window_final["end_offset_m"])
        ),
        negative_exclusion_applied=bool(
            parallel_excluded_road_ids
            or (
                divstrip_exclusion_geometry is not None
                and not divstrip_exclusion_geometry.is_empty
            )
            or (
                local_surface_clip_geometry is not None
                and not local_surface_clip_geometry.is_empty
            )
        ),
        preferred_clip_mode=preferred_clip_mode,
        event_side_clip_mode=event_side_clip_mode,
        raw={
            "event_branch_support_count": len(event_branch_support_geometries),
            "parallel_reference_geometry_count": len(parallel_side_reference_geometries),
            "selected_support_corridor_area_m2": (
                float(selected_support_corridor_geometry.area)
                if selected_support_corridor_geometry is not None and not selected_support_corridor_geometry.is_empty
                else 0.0
            ),
        },
    )
    surface_assembly = Stage4SurfaceAssemblyResult(
        axis_window_geometry=axis_window_geometry,
        parallel_side_geometry=parallel_side_geometry,
        selected_support_corridor_geometry=selected_support_corridor_geometry,
        event_side_drivezone_geometry=event_side_drivezone_geometry,
        cross_section_surface_geometry=cross_section_surface_geometry,
        divstrip_event_window=divstrip_event_window,
        local_surface_clip_geometry=local_surface_clip_geometry,
        event_side_clip_geometry=event_side_clip_geometry,
        cross_section_sample_count=int(cross_section_sample_count),
        parallel_side_sample_count=int(parallel_side_sample_count),
        allow_full_axis_drivezone_fill=bool(allow_full_axis_drivezone_fill),
        selected_support_corridor_applied=selected_support_corridor_applied,
        full_fill_start_offset_m=float(full_fill_start_offset_m),
        full_fill_end_offset_m=float(full_fill_end_offset_m),
        component_side_clip_buffer_m=float(component_side_clip_buffer_m),
        cross_section_support_mode=(
            "none" if cross_section_support_geometry is None else "branch_support_buffer"
        ),
        selected_component_surface_diags=tuple(dict(item) for item in selected_component_surface_diags),
        complex_multibranch_lobe_diags=tuple(dict(item) for item in complex_multibranch_lobe_diags),
        multi_component_surface_applied=multi_component_surface_applied,
        complex_multibranch_lobe_applied=bool(
            complex_multibranch_lobe_diags
            and any(bool(item.get("ok", False)) for item in complex_multibranch_lobe_diags)
        ),
    )
    return Stage4GeometricSupportDomain(
        span_window=span_window,
        exclusion_context=exclusion_context,
        surface_assembly=surface_assembly,
        selected_roads_geometry=selected_roads_geometry,
        selected_event_roads_geometry=selected_event_roads_geometry,
        selected_rcsd_roads_geometry=selected_rcsd_roads_geometry,
        event_seed_union=event_seed_union,
        axis_window_mask=axis_window_mask,
        parallel_side_mask=parallel_side_mask,
        cross_section_surface_mask=cross_section_surface_mask,
        seed_mask=seed_mask,
        support_mask=support_mask,
        event_side_support_mask=event_side_support_mask,
        drivezone_component_mask=drivezone_component_mask,
        component_mask=component_mask,
        divstrip_geometry_to_exclude=divstrip_exclusion_geometry,
        event_side_support_geometry_count=len(event_side_support_geometries),
        component_mask_used_support_fallback=component_mask_used_support_fallback,
        component_mask_reseeded_after_clip=component_mask_reseeded_after_clip,
        component_mask_clipped=bool(clipped_component_mask.any()),
    )
