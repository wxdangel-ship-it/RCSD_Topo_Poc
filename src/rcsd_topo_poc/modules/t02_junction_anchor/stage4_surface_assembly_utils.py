from __future__ import annotations

import math
from itertools import permutations
from typing import Any

from shapely.geometry import GeometryCollection, Point
from shapely.ops import linemerge, nearest_points, unary_union

from rcsd_topo_poc.modules.t02_junction_anchor.shared import normalize_id
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import ParsedNode, ParsedRoad

from .stage4_geometry_utils import *

def _build_selected_divstrip_component_surface_union(
    *,
    representative_node: ParsedNode,
    main_origin_point: Point,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    kind_2: int,
    road_branches,
    selected_branch_ids: set[str],
    multibranch_event_candidates: list[dict[str, Any]] | None,
    boundary_branch_a,
    boundary_branch_b,
    road_lookup: dict[str, ParsedRoad],
    divstrip_constraint_geometry,
    drivezone_union,
    parallel_centerline,
    resolution_m: float,
    cross_half_len_m: float,
    support_geometry=None,
    allow_extended_connector_span: bool = False,
) -> tuple[Any, list[dict[str, Any]]]:
    if (
        axis_centerline is None
        or axis_centerline.is_empty
        or axis_unit_vector is None
        or boundary_branch_a is None
        or boundary_branch_b is None
        or divstrip_constraint_geometry is None
        or divstrip_constraint_geometry.is_empty
    ):
        return GeometryCollection(), []

    selected_components = [
        component
        for component in _collect_polygon_components(divstrip_constraint_geometry)
        if component is not None and not component.is_empty
    ]
    if len(selected_components) <= 1:
        return GeometryCollection(), []

    scan_axis_unit_vector = _resolve_scan_axis_unit_vector(
        axis_unit_vector=axis_unit_vector,
        kind_2=kind_2,
    )
    if scan_axis_unit_vector is None:
        return GeometryCollection(), []

    localized_surfaces: list[Any] = []
    component_diags: list[dict[str, Any]] = []
    main_origin_xy = (float(main_origin_point.x), float(main_origin_point.y))
    built_component_axis_intervals_main: list[tuple[float, float]] = []

    main_branch_a_centerline = _resolve_branch_centerline(
        branch=boundary_branch_a,
        road_lookup=road_lookup,
        reference_point=main_origin_point,
    )
    main_branch_b_centerline = _resolve_branch_centerline(
        branch=boundary_branch_b,
        road_lookup=road_lookup,
        reference_point=main_origin_point,
    )

    valid_event_candidates: list[tuple[list[str], str, Any]] = []
    if multibranch_event_candidates:
        for candidate_index, candidate in enumerate(multibranch_event_candidates):
            raw_road_ids = [str(road_id) for road_id in candidate.get("road_ids", [])]
            road_ids = [
                road_id
                for road_id in raw_road_ids
                if road_id in road_lookup
                and road_lookup[road_id].geometry is not None
                and not road_lookup[road_id].geometry.is_empty
            ]
            if len(road_ids) < 2:
                continue
            road_union = unary_union([road_lookup[road_id].geometry for road_id in road_ids])
            if road_union.is_empty:
                continue
            valid_event_candidates.append((road_ids[:2], f"event_candidate_{candidate_index}", road_union))

    def _component_event_candidate_score(component_geometry, road_union) -> tuple[int, float, float, int]:
        buffered_union = road_union.buffer(
            max(DIVSTRIP_BRANCH_BUFFER_M * 1.5, 3.0),
            cap_style=2,
            join_style=2,
        )
        overlap_area = float(component_geometry.intersection(buffered_union).area)
        geometry_distance = float(component_geometry.distance(road_union))
        return (
            1 if buffered_union.intersects(component_geometry) else 0,
            overlap_area,
            -geometry_distance,
            0,
        )

    component_event_candidate_assignments: dict[int, tuple[list[str], str]] = {}
    if len(selected_components) > 1 and len(valid_event_candidates) >= len(selected_components):
        best_assignment = None
        best_assignment_key = None
        for candidate_indexes in permutations(range(len(valid_event_candidates)), len(selected_components)):
            score_hits = 0
            score_overlap = 0.0
            score_distance = 0.0
            for component_index, candidate_index in enumerate(candidate_indexes):
                _, _, road_union = valid_event_candidates[candidate_index]
                score = _component_event_candidate_score(selected_components[component_index], road_union)
                score_hits += int(score[0])
                score_overlap += float(score[1])
                score_distance += float(score[2])
            assignment_key = (score_hits, score_overlap, score_distance)
            if best_assignment_key is None or assignment_key > best_assignment_key:
                best_assignment_key = assignment_key
                best_assignment = candidate_indexes
        if best_assignment is not None:
            for component_index, candidate_index in enumerate(best_assignment):
                road_ids, source, _ = valid_event_candidates[candidate_index]
                component_event_candidate_assignments[int(component_index)] = (list(road_ids), str(source))

    def _pick_component_event_candidate(component_index: int, component_geometry) -> tuple[list[str], str] | None:
        assigned = component_event_candidate_assignments.get(int(component_index))
        if assigned is not None:
            return assigned
        if not valid_event_candidates:
            return None
        best_road_ids: list[str] | None = None
        best_source: str | None = None
        best_key = None
        for road_ids, source, road_union in valid_event_candidates:
            buffered_union = road_union.buffer(
                max(DIVSTRIP_BRANCH_BUFFER_M * 1.5, 3.0),
                cap_style=2,
                join_style=2,
            )
            overlap_area = float(component_geometry.intersection(buffered_union).area)
            geometry_distance = float(component_geometry.distance(road_union))
            pair_key = (
                1 if buffered_union.intersects(component_geometry) else 0,
                overlap_area,
                -geometry_distance,
                0,
            )
            if best_key is None or pair_key > best_key:
                best_key = pair_key
                best_road_ids = list(road_ids)
                best_source = str(source)
        if best_road_ids is None or best_source is None:
            return None
        return best_road_ids, best_source

    for component_index, component_geometry in enumerate(selected_components):
        component_focus_point = nearest_points(axis_centerline, component_geometry.representative_point())[0]
        component_scan_origin_point = component_focus_point
        component_boundary_source = "local_branch_pair"
        component_boundary_branch_a = None
        component_boundary_branch_b = None
        component_boundary_road_ids: list[str] | None = None
        component_branch_a_centerline = None
        component_branch_b_centerline = None

        component_event_candidate = _pick_component_event_candidate(component_index, component_geometry)
        if component_event_candidate is not None:
            component_boundary_road_ids, component_boundary_source = component_event_candidate
            component_branch_a_centerline = _resolve_centerline_from_road_ids(
                road_ids=[component_boundary_road_ids[0]],
                road_lookup=road_lookup,
                reference_point=component_focus_point,
            )
            component_branch_b_centerline = _resolve_centerline_from_road_ids(
                road_ids=[component_boundary_road_ids[1]],
                road_lookup=road_lookup,
                reference_point=component_focus_point,
            )

        if (
            component_branch_a_centerline is None
            or component_branch_a_centerline.is_empty
            or component_branch_b_centerline is None
            or component_branch_b_centerline.is_empty
        ):
            local_boundary_branch_a, local_boundary_branch_b = _pick_local_component_boundary_branches(
                road_branches=road_branches,
                selected_branch_ids=selected_branch_ids,
                kind_2=kind_2,
                road_lookup=road_lookup,
                reference_point=component_focus_point,
            )
            component_boundary_branch_a = local_boundary_branch_a or boundary_branch_a
            component_boundary_branch_b = local_boundary_branch_b or boundary_branch_b
            component_boundary_source = "local_branch_pair"
            component_boundary_road_ids = None
            component_branch_a_centerline = _resolve_branch_centerline(
                branch=component_boundary_branch_a,
                road_lookup=road_lookup,
                reference_point=component_focus_point,
            ) or main_branch_a_centerline
            component_branch_b_centerline = _resolve_branch_centerline(
                branch=component_boundary_branch_b,
                road_lookup=road_lookup,
                reference_point=component_focus_point,
            ) or main_branch_b_centerline
        if (
            component_branch_a_centerline is None
            or component_branch_a_centerline.is_empty
            or component_branch_b_centerline is None
            or component_branch_b_centerline.is_empty
        ):
            component_diags.append(
                {
                    "component_index": int(component_index),
                    "ok": False,
                    "reason": "component_branch_centerline_missing",
                }
            )
            continue

        component_reference = _resolve_event_reference_position(
            representative_node=representative_node,
            scan_origin_point=component_scan_origin_point,
            axis_centerline=axis_centerline,
            axis_unit_vector=axis_unit_vector,
            scan_axis_unit_vector=scan_axis_unit_vector,
            branch_a_centerline=component_branch_a_centerline,
            branch_b_centerline=component_branch_b_centerline,
            drivezone_union=drivezone_union,
            divstrip_constraint_geometry=component_geometry,
            event_anchor_geometry=component_geometry,
            cross_half_len_m=cross_half_len_m,
        )
        if str(component_reference["position_source"]) == "representative_axis_origin":
            component_diags.append(
                {
                    "component_index": int(component_index),
                    "ok": False,
                    "reason": "component_reference_unstable",
                }
            )
            continue
        component_origin_point = component_reference["origin_point"]
        component_origin_xy = (
            float(component_origin_point.x),
            float(component_origin_point.y),
        )
        local_offsets = _collect_axis_offsets_from_geometry(
            component_geometry,
            origin_xy=component_origin_xy,
            axis_unit_vector=axis_unit_vector,
        )
        if local_offsets:
            start_offset_m = max(
                -EVENT_COMPONENT_SURFACE_SPAN_CAP_M,
                min(float(min(local_offsets) - EVENT_SPAN_MARGIN_M), -EVENT_SPAN_DEFAULT_M),
            )
            end_offset_m = min(
                EVENT_COMPONENT_SURFACE_SPAN_CAP_M,
                max(float(max(local_offsets) + EVENT_SPAN_MARGIN_M), EVENT_SPAN_DEFAULT_M),
            )
        else:
            start_offset_m = -EVENT_SPAN_DEFAULT_M
            end_offset_m = EVENT_SPAN_DEFAULT_M

        component_surface_geometry, sample_count = _build_cross_section_surface_geometry(
            drivezone_union=drivezone_union,
            origin_point=component_origin_point,
            axis_unit_vector=axis_unit_vector,
            start_offset_m=start_offset_m,
            end_offset_m=end_offset_m,
            cross_half_len_m=cross_half_len_m,
            axis_centerline=axis_centerline,
            branch_a_centerline=component_branch_a_centerline,
            branch_b_centerline=component_branch_b_centerline,
            parallel_centerline=parallel_centerline,
            resolution_m=resolution_m,
            support_geometry=support_geometry,
        )
        component_diags.append(
                {
                    "component_index": int(component_index),
                    "ok": bool(component_surface_geometry is not None and not component_surface_geometry.is_empty),
                    "boundary_source": component_boundary_source,
                    "boundary_branch_ids": [
                        None if component_boundary_branch_a is None else component_boundary_branch_a.branch_id,
                        None if component_boundary_branch_b is None else component_boundary_branch_b.branch_id,
                    ],
                    "boundary_road_ids": component_boundary_road_ids,
                    "event_origin_source": component_reference["event_origin_source"],
                    "position_source": component_reference["position_source"],
                    "start_offset_m": float(start_offset_m),
                "end_offset_m": float(end_offset_m),
                "sample_count": int(sample_count),
            }
        )
        if component_surface_geometry is None or component_surface_geometry.is_empty:
            continue
        localized_surfaces.append(component_surface_geometry)
        component_surface_offsets_main = _collect_axis_offsets_from_geometry(
            component_surface_geometry,
            origin_xy=main_origin_xy,
            axis_unit_vector=axis_unit_vector,
        )
        component_surface_offsets_main = [
            float(offset)
            for offset in component_surface_offsets_main
            if math.isfinite(float(offset))
        ]
        if component_surface_offsets_main:
            built_component_axis_intervals_main.append(
                (
                    float(min(component_surface_offsets_main)),
                    float(max(component_surface_offsets_main)),
                )
            )

    if not localized_surfaces:
        return GeometryCollection(), component_diags

    if (
        main_branch_a_centerline is not None
        and not main_branch_a_centerline.is_empty
        and main_branch_b_centerline is not None
        and not main_branch_b_centerline.is_empty
        and len(built_component_axis_intervals_main) >= 2
    ):
        connector_span_limit_m = _resolve_selected_component_connector_span_limit_m(
            allow_extended_connector_span=allow_extended_connector_span,
        )
        sorted_intervals = sorted(
            built_component_axis_intervals_main,
            key=lambda item: (float(item[0]), float(item[1])),
        )
        connector_index = 0
        for previous_interval, next_interval in zip(sorted_intervals, sorted_intervals[1:]):
            connector_start_m = float(previous_interval[1] - EVENT_SPAN_MARGIN_M)
            connector_end_m = float(next_interval[0] + EVENT_SPAN_MARGIN_M)
            connector_span_m = float(connector_end_m - connector_start_m)
            if connector_span_m <= EVENT_SPAN_MARGIN_M * 2.0:
                continue
            if connector_span_m > float(connector_span_limit_m):
                component_diags.append(
                    {
                        "component_index": f"connector_{connector_index}",
                        "ok": False,
                        "reason": "connector_span_exceeds_limit",
                        "start_offset_m": float(connector_start_m),
                        "end_offset_m": float(connector_end_m),
                        "span_m": float(connector_span_m),
                        "span_limit_m": float(connector_span_limit_m),
                    }
                )
                connector_index += 1
                continue
            connector_surface_geometry, connector_sample_count = _build_cross_section_surface_geometry(
                drivezone_union=drivezone_union,
                origin_point=main_origin_point,
                axis_unit_vector=axis_unit_vector,
                start_offset_m=connector_start_m,
                end_offset_m=connector_end_m,
                cross_half_len_m=cross_half_len_m,
                axis_centerline=axis_centerline,
                branch_a_centerline=main_branch_a_centerline,
                branch_b_centerline=main_branch_b_centerline,
                parallel_centerline=parallel_centerline,
                resolution_m=resolution_m,
                support_geometry=support_geometry,
            )
            if connector_surface_geometry is None or connector_surface_geometry.is_empty:
                continue
            localized_surfaces.append(connector_surface_geometry)
            component_diags.append(
                {
                    "component_index": f"connector_{connector_index}",
                    "ok": True,
                    "start_offset_m": float(connector_start_m),
                    "end_offset_m": float(connector_end_m),
                    "sample_count": int(connector_sample_count),
                }
            )
            connector_index += 1

    return unary_union(localized_surfaces).intersection(drivezone_union).buffer(0), component_diags


def _build_group_node_fact_support_surface_union(
    *,
    representative_node: ParsedNode,
    group_nodes: list[ParsedNode],
    existing_surface_geometry,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    kind_2: int,
    road_branches,
    selected_branch_ids: set[str],
    road_lookup: dict[str, ParsedRoad],
    drivezone_union,
    parallel_centerline,
    resolution_m: float,
    cross_half_len_m: float,
) -> tuple[Any, list[dict[str, Any]]]:
    if (
        axis_centerline is None
        or axis_centerline.is_empty
        or axis_unit_vector is None
        or len(group_nodes) <= 1
    ):
        return GeometryCollection(), []

    scan_axis_unit_vector = _resolve_scan_axis_unit_vector(
        axis_unit_vector=axis_unit_vector,
        kind_2=kind_2,
    )
    if scan_axis_unit_vector is None:
        return GeometryCollection(), []

    localized_surfaces: list[Any] = []
    node_diags: list[dict[str, Any]] = []
    coverage_probe_radius_m = max(float(NODE_SEED_RADIUS_M), float(RC_NODE_SEED_RADIUS_M), 2.0)

    for group_node in group_nodes:
        if normalize_id(group_node.node_id) == normalize_id(representative_node.node_id):
            continue

        node_probe_geometry = group_node.geometry.buffer(coverage_probe_radius_m, join_style=2)
        if (
            existing_surface_geometry is not None
            and not existing_surface_geometry.is_empty
            and existing_surface_geometry.intersects(node_probe_geometry)
        ):
            continue

        local_boundary_branch_a, local_boundary_branch_b = _pick_local_component_boundary_branches(
            road_branches=road_branches,
            selected_branch_ids=selected_branch_ids,
            kind_2=kind_2,
            road_lookup=road_lookup,
            reference_point=group_node.geometry,
        )
        if local_boundary_branch_a is None or local_boundary_branch_b is None:
            node_diags.append(
                {
                    "component_index": f"fact_node_{group_node.node_id}",
                    "ok": False,
                    "reason": "group_node_boundary_unresolved",
                    "node_id": group_node.node_id,
                }
            )
            continue

        branch_a_centerline = _resolve_branch_centerline(
            branch=local_boundary_branch_a,
            road_lookup=road_lookup,
            reference_point=group_node.geometry,
        )
        branch_b_centerline = _resolve_branch_centerline(
            branch=local_boundary_branch_b,
            road_lookup=road_lookup,
            reference_point=group_node.geometry,
        )
        if (
            branch_a_centerline is None
            or branch_a_centerline.is_empty
            or branch_b_centerline is None
            or branch_b_centerline.is_empty
        ):
            node_diags.append(
                {
                    "component_index": f"fact_node_{group_node.node_id}",
                    "ok": False,
                    "reason": "group_node_centerline_missing",
                    "node_id": group_node.node_id,
                }
            )
            continue

        node_scan_origin_point, _ = nearest_points(axis_centerline, group_node.geometry)
        node_anchor_geometry = group_node.geometry.buffer(coverage_probe_radius_m, join_style=2)
        node_reference = _resolve_event_reference_position(
            representative_node=representative_node,
            scan_origin_point=node_scan_origin_point,
            axis_centerline=axis_centerline,
            axis_unit_vector=axis_unit_vector,
            scan_axis_unit_vector=scan_axis_unit_vector,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            drivezone_union=drivezone_union,
            divstrip_constraint_geometry=node_anchor_geometry,
            event_anchor_geometry=node_anchor_geometry,
            cross_half_len_m=cross_half_len_m,
        )
        node_origin_point = node_reference["origin_point"]
        node_origin_source = str(node_reference["event_origin_source"])
        node_position_source = str(node_reference["position_source"])
        if node_position_source == "representative_axis_origin":
            node_origin_point = node_scan_origin_point
            node_origin_source = "group_node_axis_projection"
            node_position_source = "group_node_axis_projection"

        local_support_roads = [
            road
            for road in road_lookup.values()
            if (
                normalize_id(road.snodeid) == normalize_id(group_node.node_id)
                or normalize_id(road.enodeid) == normalize_id(group_node.node_id)
            )
            and road.geometry is not None
            and not road.geometry.is_empty
        ]
        if not local_support_roads:
            local_support_roads = [
                road_lookup[road_id]
                for road_id in [*local_boundary_branch_a.road_ids, *local_boundary_branch_b.road_ids]
                if road_id in road_lookup
                and road_lookup[road_id].geometry is not None
                and not road_lookup[road_id].geometry.is_empty
            ]
        support_seed_parts = [node_anchor_geometry, *[road.geometry for road in local_support_roads]]
        support_seed_geometry = unary_union(
            [geometry for geometry in support_seed_parts if geometry is not None and not geometry.is_empty]
        )
        local_offsets = _collect_axis_offsets_from_geometry(
            support_seed_geometry,
            origin_xy=(float(node_origin_point.x), float(node_origin_point.y)),
            axis_unit_vector=axis_unit_vector,
        )
        if local_offsets:
            start_offset_m = max(
                -EVENT_COMPONENT_SURFACE_SPAN_CAP_M,
                min(float(min(local_offsets) - EVENT_SPAN_MARGIN_M), -EVENT_COMPLEX_MEMBER_SPAN_PAD_M),
            )
            end_offset_m = min(
                EVENT_COMPONENT_SURFACE_SPAN_CAP_M,
                max(float(max(local_offsets) + EVENT_SPAN_MARGIN_M), EVENT_COMPLEX_MEMBER_SPAN_PAD_M),
            )
        else:
            start_offset_m = -EVENT_COMPLEX_MEMBER_SPAN_PAD_M
            end_offset_m = EVENT_COMPLEX_MEMBER_SPAN_PAD_M

        local_support_geometry = unary_union(
            [
                road.geometry.buffer(
                    max(ROAD_BUFFER_M * 1.5, RC_ROAD_BUFFER_M * 1.25, 2.25),
                    cap_style=2,
                    join_style=2,
                )
                for road in local_support_roads
                if road.geometry is not None and not road.geometry.is_empty
            ]
        )
        fact_surface_geometry, sample_count = _build_cross_section_surface_geometry(
            drivezone_union=drivezone_union,
            origin_point=node_origin_point,
            axis_unit_vector=axis_unit_vector,
            start_offset_m=start_offset_m,
            end_offset_m=end_offset_m,
            cross_half_len_m=cross_half_len_m,
            axis_centerline=axis_centerline,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            parallel_centerline=parallel_centerline,
            resolution_m=resolution_m,
            support_geometry=local_support_geometry if not local_support_geometry.is_empty else None,
        )
        if (
            fact_surface_geometry is None
            or fact_surface_geometry.is_empty
            or not fact_surface_geometry.intersects(node_probe_geometry)
        ):
            node_diags.append(
                {
                    "component_index": f"fact_node_{group_node.node_id}",
                    "ok": False,
                    "reason": "group_node_fact_surface_missing",
                    "node_id": group_node.node_id,
                    "event_origin_source": node_origin_source,
                    "position_source": node_position_source,
                    "start_offset_m": float(start_offset_m),
                    "end_offset_m": float(end_offset_m),
                    "sample_count": int(sample_count),
                }
            )
            continue

        localized_surfaces.append(fact_surface_geometry)
        node_diags.append(
            {
                "component_index": f"fact_node_{group_node.node_id}",
                "ok": True,
                "node_id": group_node.node_id,
                "boundary_source": "group_node_local_support",
                "boundary_branch_ids": [
                    local_boundary_branch_a.branch_id,
                    local_boundary_branch_b.branch_id,
                ],
                "evidence_source": "group_node_local_fact",
                "event_origin_source": node_origin_source,
                "position_source": node_position_source,
                "start_offset_m": float(start_offset_m),
                "end_offset_m": float(end_offset_m),
                "sample_count": int(sample_count),
            }
        )

    if not localized_surfaces:
        return GeometryCollection(), node_diags
    return unary_union(localized_surfaces).intersection(drivezone_union).buffer(0), node_diags


def _resolve_centerline_from_road_ids(
    *,
    road_ids: list[str],
    road_lookup: dict[str, ParsedRoad],
    reference_point: Point,
):
    line_union = unary_union(
        [
            road_lookup[road_id].geometry
            for road_id in road_ids
            if road_id in road_lookup
            and road_lookup[road_id].geometry is not None
            and not road_lookup[road_id].geometry.is_empty
        ]
    )
    if line_union.is_empty:
        return None
    merged = line_union if getattr(line_union, "geom_type", None) == "LineString" else linemerge(line_union)
    line_components = [
        component
        for component in _explode_component_geometries(merged)
        if getattr(component, "geom_type", None) == "LineString" and not component.is_empty
    ]
    if not line_components:
        line_components = [
            component
            for component in _explode_component_geometries(line_union)
            if getattr(component, "geom_type", None) == "LineString" and not component.is_empty
        ]
    if not line_components:
        return None
    centerline = min(
        line_components,
        key=lambda component: (
            float(component.distance(reference_point)),
            -float(component.length),
        ),
    )
    coords = list(centerline.coords)
    if len(coords) < 2:
        return centerline
    start_point = Point(coords[0])
    end_point = Point(coords[-1])
    if end_point.distance(reference_point) < start_point.distance(reference_point):
        centerline = type(centerline)(coords[::-1])
    return centerline


def _select_multibranch_divstrip_geometry(
    *,
    divstrip_geometry,
    road_geometries: list[Any],
):
    if divstrip_geometry is None or divstrip_geometry.is_empty or not road_geometries:
        return GeometryCollection()
    road_union = unary_union([geometry for geometry in road_geometries if geometry is not None and not geometry.is_empty])
    if road_union.is_empty:
        return GeometryCollection()
    matched_components = [
        component
        for component in _collect_polygon_components(divstrip_geometry)
        if float(component.distance(road_union)) <= float(DIVSTRIP_EVENT_ROAD_LINK_DISTANCE_M)
    ]
    if matched_components:
        return unary_union(matched_components).buffer(0)
    nearest_component = min(
        _collect_polygon_components(divstrip_geometry),
        key=lambda component: float(component.distance(road_union)),
        default=None,
    )
    if nearest_component is None:
        return GeometryCollection()
    if float(nearest_component.distance(road_union)) <= float(DIVSTRIP_EVENT_BUFFER_M):
        return nearest_component.buffer(0)
    return GeometryCollection()


def _build_multibranch_candidate_lobe_geometry(
    *,
    candidate_road_ids: list[str],
    representative_node: ParsedNode,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    kind_2: int,
    drivezone_union,
    divstrip_geometry,
    road_lookup: dict[str, ParsedRoad],
    road_to_branch: dict[str, Any],
    road_branches_by_id: dict[str, Any],
    parallel_centerline,
    resolution_m: float,
    cross_half_len_m: float,
) -> tuple[Any, dict[str, Any]]:
    if axis_centerline is None or axis_centerline.is_empty or axis_unit_vector is None:
        return GeometryCollection(), {"ok": False, "reason": "missing_axis"}
    candidate_roads = [
        road_lookup[road_id]
        for road_id in candidate_road_ids
        if road_id in road_lookup
        and road_lookup[road_id].geometry is not None
        and not road_lookup[road_id].geometry.is_empty
    ]
    if len(candidate_roads) < 2:
        return GeometryCollection(), {"ok": False, "reason": "candidate_road_count_lt_2"}

    reference_point = representative_node.geometry
    provisional_branch_a_centerline = _resolve_centerline_from_road_ids(
        road_ids=[candidate_roads[0].road_id],
        road_lookup=road_lookup,
        reference_point=reference_point,
    )
    provisional_branch_b_centerline = _resolve_centerline_from_road_ids(
        road_ids=[candidate_roads[1].road_id],
        road_lookup=road_lookup,
        reference_point=reference_point,
    )
    if (
        provisional_branch_a_centerline is None
        or provisional_branch_a_centerline.is_empty
        or provisional_branch_b_centerline is None
        or provisional_branch_b_centerline.is_empty
    ):
        return GeometryCollection(), {"ok": False, "reason": "candidate_centerline_missing"}

    candidate_divstrip_geometry = _select_multibranch_divstrip_geometry(
        divstrip_geometry=divstrip_geometry,
        road_geometries=[road.geometry for road in candidate_roads],
    )
    event_anchor_geometry = (
        candidate_divstrip_geometry
        if candidate_divstrip_geometry is not None and not candidate_divstrip_geometry.is_empty
        else unary_union(
            [
                road.geometry.buffer(max(EVENT_ANCHOR_BUFFER_M, 2.0), cap_style=2, join_style=2)
                for road in candidate_roads
            ]
        ).buffer(0)
    )
    scan_origin_point, _ = nearest_points(axis_centerline, representative_node.geometry)
    candidate_reference = _resolve_event_reference_position(
        representative_node=representative_node,
        scan_origin_point=scan_origin_point,
        axis_centerline=axis_centerline,
        axis_unit_vector=axis_unit_vector,
        scan_axis_unit_vector=_resolve_scan_axis_unit_vector(axis_unit_vector=axis_unit_vector, kind_2=kind_2),
        branch_a_centerline=provisional_branch_a_centerline,
        branch_b_centerline=provisional_branch_b_centerline,
        drivezone_union=drivezone_union,
        divstrip_constraint_geometry=candidate_divstrip_geometry,
        event_anchor_geometry=event_anchor_geometry,
        cross_half_len_m=cross_half_len_m,
    )
    origin_point = candidate_reference["origin_point"]
    candidate_source_branch_ids = sorted(
        {
            road_to_branch[road_id].branch_id
            for road_id in candidate_road_ids
            if road_id in road_to_branch and road_to_branch[road_id] is not None
        }
    )
    branch_a_centerline = provisional_branch_a_centerline
    branch_b_centerline = provisional_branch_b_centerline
    if len(candidate_source_branch_ids) == 2:
        branch_a = road_branches_by_id.get(candidate_source_branch_ids[0])
        branch_b = road_branches_by_id.get(candidate_source_branch_ids[1])
        if branch_a is not None and branch_b is not None:
            branch_a_centerline = _resolve_branch_centerline(
                branch=branch_a,
                road_lookup=road_lookup,
                reference_point=origin_point,
            ) or provisional_branch_a_centerline
            branch_b_centerline = _resolve_branch_centerline(
                branch=branch_b,
                road_lookup=road_lookup,
                reference_point=origin_point,
            ) or provisional_branch_b_centerline
    local_axis_window_geometry = _build_axis_window_geometry(
        origin_point=origin_point,
        axis_unit_vector=axis_unit_vector,
        start_offset_m=-MULTIBRANCH_LOCAL_CONTEXT_WINDOW_M,
        end_offset_m=MULTIBRANCH_LOCAL_CONTEXT_WINDOW_M,
        cross_half_len_m=cross_half_len_m,
    )
    origin_xy = (float(origin_point.x), float(origin_point.y))
    candidate_offsets = _collect_axis_offsets_from_geometry(
        candidate_divstrip_geometry if candidate_divstrip_geometry is not None and not candidate_divstrip_geometry.is_empty else event_anchor_geometry,
        origin_xy=origin_xy,
        axis_unit_vector=axis_unit_vector,
        clip_geometry=local_axis_window_geometry,
    )
    for road in candidate_roads:
        candidate_offsets.extend(
            _collect_axis_offsets_from_geometry(
                road.geometry,
                origin_xy=origin_xy,
                axis_unit_vector=axis_unit_vector,
                clip_geometry=local_axis_window_geometry,
            )
        )
    if candidate_offsets:
        start_offset_m = max(
            -MULTIBRANCH_LOCAL_SPAN_MAX_M,
            min(float(min(candidate_offsets) - EVENT_SPAN_MARGIN_M), -EVENT_SPAN_DEFAULT_M),
        )
        end_offset_m = min(
            MULTIBRANCH_LOCAL_SPAN_MAX_M,
            max(float(max(candidate_offsets) + EVENT_SPAN_MARGIN_M), EVENT_SPAN_DEFAULT_M),
        )
    else:
        start_offset_m = -EVENT_SPAN_DEFAULT_M
        end_offset_m = EVENT_SPAN_DEFAULT_M
    support_geometry = unary_union(
        [
            road.geometry.buffer(max(ROAD_BUFFER_M * 1.5, RC_ROAD_BUFFER_M * 1.25, 2.25), cap_style=2, join_style=2)
            for road in candidate_roads
        ]
    )
    lobe_geometry, sample_count = _build_cross_section_surface_geometry(
        drivezone_union=drivezone_union,
        origin_point=origin_point,
        axis_unit_vector=axis_unit_vector,
        start_offset_m=start_offset_m,
        end_offset_m=end_offset_m,
        cross_half_len_m=cross_half_len_m,
        axis_centerline=axis_centerline,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
        parallel_centerline=parallel_centerline,
        resolution_m=resolution_m,
        support_geometry=support_geometry,
    )
    if candidate_divstrip_geometry is not None and not candidate_divstrip_geometry.is_empty and lobe_geometry is not None and not lobe_geometry.is_empty:
        lobe_geometry = lobe_geometry.difference(
            candidate_divstrip_geometry.buffer(DIVSTRIP_EXCLUSION_BUFFER_M, join_style=2)
        ).buffer(0)
    return lobe_geometry, {
        "ok": bool(lobe_geometry is not None and not lobe_geometry.is_empty),
        "candidate_road_ids": list(candidate_road_ids),
        "candidate_source_branch_ids": candidate_source_branch_ids,
        "candidate_origin_source": candidate_reference["event_origin_source"],
        "candidate_position_source": candidate_reference["position_source"],
        "candidate_start_offset_m": float(start_offset_m),
        "candidate_end_offset_m": float(end_offset_m),
        "sample_count": int(sample_count),
    }


def _build_complex_multibranch_lobe_union(
    *,
    multibranch_context: dict[str, Any],
    representative_node: ParsedNode,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    kind_2: int,
    drivezone_union,
    divstrip_geometry,
    road_lookup: dict[str, ParsedRoad],
    road_to_branch: dict[str, Any],
    road_branches_by_id: dict[str, Any],
    parallel_centerline,
    resolution_m: float,
    cross_half_len_m: float,
) -> tuple[Any, list[dict[str, Any]]]:
    candidate_specs: list[list[str]] = []
    seen_specs: set[tuple[str, ...]] = set()
    for road_ids in [
        multibranch_context.get("main_pair_item_ids", []),
        *[
            candidate.get("road_ids", [])
            for candidate in multibranch_context.get("event_candidates", [])[: max(0, MULTIBRANCH_EVENT_MAX_LOBES - 1)]
        ],
    ]:
        normalized_ids = tuple(sorted(str(road_id) for road_id in road_ids if road_id))
        if len(normalized_ids) < 2 or normalized_ids in seen_specs:
            continue
        seen_specs.add(normalized_ids)
        candidate_specs.append(list(normalized_ids))

    lobe_geometries: list[Any] = []
    lobe_diags: list[dict[str, Any]] = []
    for road_ids in candidate_specs:
        lobe_geometry, lobe_diag = _build_multibranch_candidate_lobe_geometry(
            candidate_road_ids=road_ids,
            representative_node=representative_node,
            axis_centerline=axis_centerline,
            axis_unit_vector=axis_unit_vector,
            kind_2=kind_2,
            drivezone_union=drivezone_union,
            divstrip_geometry=divstrip_geometry,
            road_lookup=road_lookup,
            road_to_branch=road_to_branch,
            road_branches_by_id=road_branches_by_id,
            parallel_centerline=parallel_centerline,
            resolution_m=resolution_m,
            cross_half_len_m=cross_half_len_m,
        )
        lobe_diags.append(lobe_diag)
        if lobe_geometry is None or lobe_geometry.is_empty:
            continue
        lobe_geometries.append(lobe_geometry)
    if not lobe_geometries:
        return GeometryCollection(), lobe_diags
    return unary_union(lobe_geometries).intersection(drivezone_union).buffer(0), lobe_diags

__all__ = [
    name for name, value in globals().items() if name.startswith('_') and callable(value)
]
