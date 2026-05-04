from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Mapping, Sequence

from shapely.geometry import GeometryCollection, Point
from shapely.ops import nearest_points, unary_union

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_step4_contracts import (
    Stage4EvidenceDecision,
    Stage4EventInterpretationResult,
    Stage4EventReference,
    Stage4LegacyStep5Bridge,
    Stage4LegacyStep5Readiness,
    Stage4ReverseTipDecision,
    resolve_stage4_continuous_chain_decision,
    wrap_stage4_divstrip_context,
    wrap_stage4_kind_resolution,
    wrap_stage4_multibranch_decision,
)
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import LoadedFeature, normalize_id
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import ParsedNode, ParsedRoad

from ._runtime_step4_geometry_core import *
from ._runtime_step4_geometry_base import *
from ._runtime_step2_local_context import _validate_drivezone_containment
from ._runtime_step3_topology_skeleton import _build_stage4_road_branches_for_member_nodes
from ._runtime_step4_surface import _resolve_centerline_from_road_ids


def _evaluate_primary_rcsdnode_tolerance(
    *,
    polygon_geometry,
    primary_main_rc_node: ParsedNode | None,
    representative_node: ParsedNode,
    road_branches,
    main_branch_ids: set[str],
    local_roads: list[ParsedRoad],
    selected_roads: list[ParsedRoad] | None,
    kind_2: int,
    drivezone_union,
    support_clip_geometry=None,
    preferred_trunk_branch_id: str | None = None,
) -> dict[str, Any]:
    tolerance_rule = (
        "diverge_main_seed_on_pre_trunk_le_20m"
        if kind_2 == 16
        else "merge_main_seed_on_post_trunk_le_20m"
    )
    if primary_main_rc_node is None:
        return {
            "trunk_branch_id": None,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "no_primary_main_rcsdnode",
            "rcsdnode_offset_m": None,
            "rcsdnode_lateral_dist_m": None,
            "reason": None,
            "extended_polygon_geometry": polygon_geometry,
            "covered": True,
        }

    trunk_branch, tolerance_rule = _resolve_rcsdnode_trunk_branch(
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        kind_2=kind_2,
        preferred_trunk_branch_id=preferred_trunk_branch_id,
    )
    if trunk_branch is None:
        return {
            "trunk_branch_id": None,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "trunk_unstable",
            "rcsdnode_offset_m": None,
            "rcsdnode_lateral_dist_m": None,
            "reason": REASON_TRUNK_BRANCH_UNSTABLE,
            "extended_polygon_geometry": polygon_geometry,
            "covered": False,
        }

    road_lookup = {road.road_id: road for road in local_roads}
    reference_point = representative_node.geometry
    trunk_centerline = _resolve_branch_centerline(
        branch=trunk_branch,
        road_lookup=road_lookup,
        reference_point=reference_point,
    )
    if trunk_centerline is None or trunk_centerline.is_empty:
        return {
            "trunk_branch_id": trunk_branch.branch_id,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "trunk_unstable",
            "rcsdnode_offset_m": None,
            "rcsdnode_lateral_dist_m": None,
            "reason": REASON_TRUNK_BRANCH_UNSTABLE,
            "extended_polygon_geometry": polygon_geometry,
            "covered": False,
        }

    event_source_point = representative_node.geometry
    if trunk_centerline.distance(event_source_point) > RCSDNODE_TRUNK_LATERAL_TOLERANCE_M:
        event_source_point = polygon_geometry.centroid
    event_ref_dist = float(trunk_centerline.project(event_source_point))
    node_dist = float(trunk_centerline.project(primary_main_rc_node.geometry))
    offset_m = float(node_dist - event_ref_dist)
    lateral_dist_m = float(primary_main_rc_node.geometry.distance(trunk_centerline))
    selected_roads_geometry = GeometryCollection()
    if selected_roads:
        selected_road_geometries = [
            road.geometry
            for road in selected_roads
            if road.geometry is not None and not road.geometry.is_empty
        ]
        if selected_road_geometries:
            selected_roads_geometry = unary_union(selected_road_geometries)

    if -1.0 <= offset_m <= RCSDNODE_TRUNK_WINDOW_M and polygon_geometry.buffer(0).covers(primary_main_rc_node.geometry):
        return {
            "trunk_branch_id": trunk_branch.branch_id,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "exact_cover",
            "rcsdnode_offset_m": offset_m,
            "rcsdnode_lateral_dist_m": lateral_dist_m,
            "reason": None,
            "extended_polygon_geometry": polygon_geometry,
            "covered": True,
        }

    polygon_gap_m = float(polygon_geometry.distance(primary_main_rc_node.geometry))
    selected_road_gap_m = (
        math.inf
        if selected_roads_geometry.is_empty
        else float(primary_main_rc_node.geometry.distance(selected_roads_geometry))
    )
    if (
        0.0 <= offset_m <= RCSDNODE_TRUNK_WINDOW_M
        and polygon_gap_m > 0.0
        and polygon_gap_m <= RCSDNODE_TRUNK_WINDOW_M + 5.0
        and selected_road_gap_m <= RCSDNODE_TRUNK_LATERAL_TOLERANCE_M
        and not selected_roads_geometry.is_empty
    ):
        corridor_buffer_m = max(
            RCSDNODE_TRUNK_LATERAL_TOLERANCE_M,
            float(selected_road_gap_m) + 1.5,
            float(RC_ROAD_BUFFER_M) * 1.25,
            2.5,
        )
        road_corridor = selected_roads_geometry.buffer(corridor_buffer_m, cap_style=2, join_style=2)
        if drivezone_union is not None and not drivezone_union.is_empty:
            road_corridor = road_corridor.intersection(drivezone_union).buffer(0)
        if support_clip_geometry is not None and not support_clip_geometry.is_empty:
            clipped_corridor = road_corridor.intersection(support_clip_geometry).buffer(0)
            if not clipped_corridor.is_empty:
                road_corridor = clipped_corridor
        node_patch_seed = primary_main_rc_node.geometry.buffer(
            max(float(RC_NODE_SEED_RADIUS_M), float(polygon_gap_m) + 1.5),
            join_style=2,
        )
        node_axis_unit_vector = _resolve_event_axis_unit_vector(
            axis_centerline=trunk_centerline,
            origin_point=primary_main_rc_node.geometry,
        )
        if node_axis_unit_vector is not None:
            node_axis_point = nearest_points(trunk_centerline, primary_main_rc_node.geometry)[0]
            node_cross_cap = _build_event_crossline(
                origin_point=node_axis_point,
                axis_unit_vector=node_axis_unit_vector,
                scan_dist_m=0.0,
                cross_half_len_m=max(
                    float(lateral_dist_m) + 2.0,
                    float(RC_ROAD_BUFFER_M) * 2.0,
                    4.0,
                ),
            ).buffer(
                max(float(RC_NODE_SEED_RADIUS_M), float(polygon_gap_m) + 1.5, 2.5),
                cap_style=2,
                join_style=2,
            )
            node_patch_seed = unary_union([node_patch_seed, node_cross_cap]).buffer(0)
        node_patch = road_corridor.intersection(node_patch_seed).buffer(0)
        if not node_patch.is_empty:
            extended_polygon_geometry = unary_union([polygon_geometry, node_patch]).buffer(0)
            if extended_polygon_geometry.buffer(0).covers(primary_main_rc_node.geometry):
                return {
                    "trunk_branch_id": trunk_branch.branch_id,
                    "rcsdnode_tolerance_rule": tolerance_rule,
                    "rcsdnode_tolerance_applied": True,
                    "rcsdnode_coverage_mode": "selected_road_corridor_tolerated",
                    "rcsdnode_offset_m": offset_m,
                    "rcsdnode_lateral_dist_m": lateral_dist_m,
                    "reason": None,
                    "extended_polygon_geometry": extended_polygon_geometry,
                    "covered": True,
                }

    if lateral_dist_m > RCSDNODE_TRUNK_LATERAL_TOLERANCE_M:
        return {
            "trunk_branch_id": trunk_branch.branch_id,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "off_trunk",
            "rcsdnode_offset_m": offset_m,
            "rcsdnode_lateral_dist_m": lateral_dist_m,
            "reason": REASON_RCSDNODE_MAIN_OFF_TRUNK,
            "extended_polygon_geometry": polygon_geometry,
            "covered": False,
        }

    if offset_m < -1.0:
        return {
            "trunk_branch_id": trunk_branch.branch_id,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "direction_invalid",
            "rcsdnode_offset_m": offset_m,
            "rcsdnode_lateral_dist_m": lateral_dist_m,
            "reason": REASON_RCSDNODE_MAIN_DIRECTION_INVALID,
            "extended_polygon_geometry": polygon_geometry,
            "covered": False,
        }

    if offset_m > RCSDNODE_TRUNK_WINDOW_M:
        return {
            "trunk_branch_id": trunk_branch.branch_id,
            "rcsdnode_tolerance_rule": tolerance_rule,
            "rcsdnode_tolerance_applied": False,
            "rcsdnode_coverage_mode": "out_of_window",
            "rcsdnode_offset_m": offset_m,
            "rcsdnode_lateral_dist_m": lateral_dist_m,
            "reason": REASON_RCSDNODE_MAIN_OUT_OF_WINDOW,
            "extended_polygon_geometry": polygon_geometry,
            "covered": False,
        }

    start_dist = max(0.0, min(event_ref_dist, node_dist))
    end_dist = min(float(trunk_centerline.length), max(event_ref_dist, node_dist))
    covered = True
    return {
        "trunk_branch_id": trunk_branch.branch_id,
        "rcsdnode_tolerance_rule": tolerance_rule,
        "rcsdnode_tolerance_applied": True,
        "rcsdnode_coverage_mode": "trunk_window_tolerated",
        "rcsdnode_offset_m": offset_m,
        "rcsdnode_lateral_dist_m": lateral_dist_m,
        "reason": None,
        "extended_polygon_geometry": polygon_geometry,
        "covered": covered,
    }


def _resolve_effective_target_rc_nodes(
    *,
    direct_target_rc_nodes: list[ParsedNode],
    primary_main_rc_node: ParsedNode | None,
    primary_rcsdnode_tolerance: dict[str, Any] | None,
) -> list[ParsedNode]:
    if direct_target_rc_nodes:
        return list(direct_target_rc_nodes)
    if primary_main_rc_node is None or primary_rcsdnode_tolerance is None:
        return []
    coverage_mode = str(primary_rcsdnode_tolerance.get("rcsdnode_coverage_mode") or "")
    if coverage_mode in {"exact_cover", "selected_road_corridor_tolerated", "trunk_window_tolerated"}:
        return [primary_main_rc_node]
    return []


def _maybe_reselect_inferred_primary_rcsdnode_by_exact_cover(
    *,
    primary_main_rc_node: ParsedNode | None,
    primary_rcsdnode_tolerance: dict[str, Any],
    representative_node: ParsedNode,
    selected_rcsd_nodes: list[ParsedNode],
    direct_target_rc_nodes: list[ParsedNode],
    rcsdnode_seed_mode: str,
    polygon_geometry,
    road_branches,
    main_branch_ids: set[str],
    local_roads: list[ParsedRoad],
    selected_roads: list[ParsedRoad] | None,
    kind_2: int,
    drivezone_union,
    support_clip_geometry=None,
    preferred_trunk_branch_id: str | None = None,
) -> tuple[ParsedNode | None, dict[str, Any]]:
    if primary_main_rc_node is None:
        return primary_main_rc_node, primary_rcsdnode_tolerance
    if direct_target_rc_nodes:
        return primary_main_rc_node, primary_rcsdnode_tolerance
    if rcsdnode_seed_mode != "inferred_local_trunk_window":
        return primary_main_rc_node, primary_rcsdnode_tolerance
    if str(primary_rcsdnode_tolerance.get("reason") or "") != REASON_RCSDNODE_MAIN_OFF_TRUNK:
        return primary_main_rc_node, primary_rcsdnode_tolerance

    best_candidate: ParsedNode | None = None
    best_tolerance: dict[str, Any] | None = None
    best_score: tuple[float, float] | None = None
    for candidate in selected_rcsd_nodes:
        if candidate.node_id == primary_main_rc_node.node_id:
            continue
        candidate_tolerance = _evaluate_primary_rcsdnode_tolerance(
            polygon_geometry=polygon_geometry,
            primary_main_rc_node=candidate,
            representative_node=representative_node,
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            local_roads=local_roads,
            selected_roads=selected_roads,
            kind_2=kind_2,
            drivezone_union=drivezone_union,
            support_clip_geometry=support_clip_geometry,
            preferred_trunk_branch_id=preferred_trunk_branch_id,
        )
        if str(candidate_tolerance.get("rcsdnode_coverage_mode") or "") != "exact_cover":
            continue
        distance_to_seed = float(candidate.geometry.distance(representative_node.geometry))
        lateral_dist_m = float(candidate_tolerance.get("rcsdnode_lateral_dist_m") or 0.0)
        score = (-distance_to_seed, -lateral_dist_m)
        if best_score is None or score > best_score:
            best_candidate = candidate
            best_tolerance = candidate_tolerance
            best_score = score

    if best_candidate is None or best_tolerance is None:
        return primary_main_rc_node, primary_rcsdnode_tolerance

    best_tolerance = dict(best_tolerance)
    best_tolerance.update(
        {
            "rcsdnode_reselected_exact_cover": True,
            "rcsdnode_reselected_from_node_id": primary_main_rc_node.node_id,
            "rcsdnode_reselected_to_node_id": best_candidate.node_id,
            "rcsdnode_reselected_reason": "inferred_seed_off_trunk_alternate_exact_cover",
        }
    )
    return best_candidate, best_tolerance


def _infer_primary_main_rc_node_from_local_context(
    *,
    local_rcsd_nodes: list[ParsedNode],
    selected_rcsd_roads: list[ParsedRoad],
    representative_node: ParsedNode,
    road_branches,
    main_branch_ids: set[str],
    local_roads: list[ParsedRoad],
    kind_2: int,
    preferred_trunk_branch_id: str | None = None,
) -> dict[str, Any]:
    tolerance_rule = (
        "diverge_main_seed_on_pre_trunk_le_20m"
        if kind_2 == 16
        else "merge_main_seed_on_post_trunk_le_20m"
    )
    if not local_rcsd_nodes:
        return {
            "primary_main_rc_node": None,
            "seed_mode": "no_local_rcsdnode",
            "seed_candidate_count": 0,
            "seed_endpoint_hit_count": 0,
            "seed_rule": tolerance_rule,
        }

    trunk_branch, tolerance_rule = _resolve_rcsdnode_trunk_branch(
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        kind_2=kind_2,
        preferred_trunk_branch_id=preferred_trunk_branch_id,
    )
    if trunk_branch is None:
        return {
            "primary_main_rc_node": None,
            "seed_mode": "trunk_unstable",
            "seed_candidate_count": 0,
            "seed_endpoint_hit_count": 0,
            "seed_rule": tolerance_rule,
        }

    trunk_centerline = _resolve_branch_centerline(
        branch=trunk_branch,
        road_lookup={road.road_id: road for road in local_roads},
        reference_point=representative_node.geometry,
    )
    if trunk_centerline is None or trunk_centerline.is_empty:
        return {
            "primary_main_rc_node": None,
            "seed_mode": "trunk_unstable",
            "seed_candidate_count": 0,
            "seed_endpoint_hit_count": 0,
            "seed_rule": tolerance_rule,
        }

    selected_endpoint_ids = {
        normalize_id(node_id)
        for road in selected_rcsd_roads
        for node_id in (road.snodeid, road.enodeid)
        if normalize_id(node_id) is not None
    }
    event_ref_dist = float(trunk_centerline.project(representative_node.geometry))
    candidates: list[tuple[tuple[Any, ...], ParsedNode]] = []
    endpoint_hit_count = 0
    for node in local_rcsd_nodes:
        lateral_dist_m = float(node.geometry.distance(trunk_centerline))
        offset_m = float(trunk_centerline.project(node.geometry) - event_ref_dist)
        node_id = normalize_id(node.node_id)
        endpoint_hit = node_id in selected_endpoint_ids
        if endpoint_hit:
            endpoint_hit_count += 1
        within_window = 0.0 <= offset_m <= RCSDNODE_TRUNK_WINDOW_M
        on_trunk = lateral_dist_m <= RCSDNODE_TRUNK_LATERAL_TOLERANCE_M
        distance_to_seed = float(node.geometry.distance(representative_node.geometry))
        candidates.append(
            (
                (
                    1 if within_window and on_trunk else 0,
                    1 if endpoint_hit else 0,
                    1 if on_trunk else 0,
                    -abs(min(max(offset_m, 0.0), RCSDNODE_TRUNK_WINDOW_M) - offset_m),
                    -lateral_dist_m,
                    -distance_to_seed,
                ),
                node,
            )
        )

    if not candidates:
        return {
            "primary_main_rc_node": None,
            "seed_mode": "no_local_rcsdnode",
            "seed_candidate_count": 0,
            "seed_endpoint_hit_count": endpoint_hit_count,
            "seed_rule": tolerance_rule,
        }

    candidates.sort(key=lambda item: item[0], reverse=True)
    primary_main_rc_node = candidates[0][1]
    return {
        "primary_main_rc_node": primary_main_rc_node,
        "seed_mode": "inferred_local_trunk_window",
        "seed_candidate_count": len(candidates),
        "seed_endpoint_hit_count": endpoint_hit_count,
        "seed_rule": tolerance_rule,
    }


def _pick_section_core_point(
    *,
    section_geometry,
    center_point: Point,
) -> Point | None:
    line_parts = _collect_line_parts(section_geometry)
    if line_parts:
        longest_part = max(line_parts, key=lambda item: float(item.length))
        point = longest_part.interpolate(0.5, normalized=True)
        return Point(float(point.x), float(point.y))
    if section_geometry is None or section_geometry.is_empty:
        return None
    if section_geometry.buffer(1e-6).covers(center_point):
        return Point(float(center_point.x), float(center_point.y))
    representative_point = section_geometry.representative_point()
    if representative_point is None or representative_point.is_empty:
        return None
    return Point(float(representative_point.x), float(representative_point.y))


def _materialize_divstrip_core_point(
    *,
    scan_origin_point: Point,
    scan_axis_unit_vector: tuple[float, float],
    scan_dist_m: float,
    cross_half_len_m: float,
    branch_a_centerline,
    branch_b_centerline,
    divstrip_geometry,
) -> Point | None:
    if divstrip_geometry is None or divstrip_geometry.is_empty:
        return None
    crossline = _build_event_crossline(
        origin_point=scan_origin_point,
        axis_unit_vector=scan_axis_unit_vector,
        scan_dist_m=float(scan_dist_m),
        cross_half_len_m=cross_half_len_m,
    )
    center_point = crossline.interpolate(0.5, normalized=True)
    found_segment, segment_diag = _build_between_branches_segment(
        crossline=crossline,
        center_point=center_point,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
    )
    probe_geometry = (
        found_segment
        if found_segment is not None and segment_diag["ok"]
        else crossline
    )
    section_geometry = probe_geometry.intersection(divstrip_geometry)
    core_point = _pick_section_core_point(
        section_geometry=section_geometry,
        center_point=center_point,
    )
    if core_point is not None:
        return core_point
    if divstrip_geometry.buffer(float(EVENT_REFERENCE_DIVSTRIP_TOL_M)).covers(center_point):
        return Point(float(center_point.x), float(center_point.y))
    return None


EVENT_REFERENCE_BRANCH_MIDDLE_TOL_M = 6.0
EVENT_REFERENCE_BRANCH_MIDDLE_SCAN_WINDOW_M = 4.0


def _materialize_reference_candidate(
    *,
    scan_origin_point: Point,
    scan_axis_unit_vector: tuple[float, float],
    chosen_s: float,
    position_source: str,
    split_pick_source: str,
    tip_s: float | None,
    first_divstrip_hit_s: float | None,
    drivezone_split_s: float | None,
    divstrip_ref_s: float | None,
    cross_half_len_m: float,
    branch_a_centerline,
    branch_b_centerline,
    selected_divstrip_geometry,
    drivezone_union,
    all_divstrip_geometry,
    step_m: float,
) -> dict[str, Any]:
    final_scan_s = float(chosen_s)
    chosen_point = None
    resolved_split_pick_source = str(split_pick_source)
    if str(position_source) == "divstrip_ref":
        divstrip_scan_candidates: list[tuple[float, str]] = []
        if (
            drivezone_split_s is not None
            and divstrip_ref_s is not None
            and abs(float(drivezone_split_s) - float(divstrip_ref_s)) <= float(EVENT_REFERENCE_MAX_OFFSET_M)
        ):
            divstrip_scan_candidates.append((float(drivezone_split_s), "split_guided"))
        body_center_s_value: float | None = None
        body_center_full_component = None
        if tip_s is not None:
            full_component_geometry = None
            if all_divstrip_geometry is not None and not all_divstrip_geometry.is_empty:
                tip_point_at_s = _point_from_axis_offset(
                    origin_point=scan_origin_point,
                    axis_unit_vector=scan_axis_unit_vector,
                    offset_m=float(tip_s),
                )
                tip_point_for_lookup = tip_point_at_s
                if (
                    selected_divstrip_geometry is not None
                    and not selected_divstrip_geometry.is_empty
                ):
                    try:
                        snapped = nearest_points(tip_point_at_s, selected_divstrip_geometry)[1]
                    except Exception:
                        snapped = tip_point_at_s
                    if snapped is not None and not snapped.is_empty:
                        tip_point_for_lookup = snapped
                full_polygon_components = _collect_polygon_components(all_divstrip_geometry)
                covering = [
                    component
                    for component in full_polygon_components
                    if component.buffer(1.0).covers(tip_point_for_lookup)
                ]
                if covering:
                    full_component_geometry = max(
                        covering,
                        key=lambda component: float(getattr(component, "area", 0.0) or 0.0),
                    )
                elif full_polygon_components:
                    full_component_geometry = min(
                        full_polygon_components,
                        key=lambda component: float(component.distance(tip_point_for_lookup)),
                    )
            centroid_source_geometry = (
                full_component_geometry
                if full_component_geometry is not None and not full_component_geometry.is_empty
                else selected_divstrip_geometry
            )
            if centroid_source_geometry is not None and not centroid_source_geometry.is_empty:
                try:
                    _component_centroid = centroid_source_geometry.centroid
                except Exception:
                    _component_centroid = None
                if _component_centroid is not None and not _component_centroid.is_empty:
                    projected_centroid_s = _project_point_to_axis(
                        _component_centroid,
                        origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
                        axis_unit_vector=scan_axis_unit_vector,
                    )
                    if (
                        projected_centroid_s is not None
                        and abs(float(projected_centroid_s) - float(tip_s)) > 1.5
                        and (
                            (float(tip_s) >= 0.0 and float(projected_centroid_s) >= 0.0)
                            or (float(tip_s) < 0.0 and float(projected_centroid_s) < 0.0)
                        )
                    ):
                        body_center_s_value = float(projected_centroid_s)
                        body_center_full_component = full_component_geometry
        if body_center_s_value is not None:
            divstrip_scan_candidates.append((body_center_s_value, "body_center"))
        if first_divstrip_hit_s is not None and tip_s is not None:
            divstrip_scan_candidates.append((0.5 * (float(first_divstrip_hit_s) + float(tip_s)), "core_mid"))
        if tip_s is not None:
            divstrip_scan_candidates.append((float(tip_s), "tip_projection"))
        if not divstrip_scan_candidates:
            divstrip_scan_candidates.append((float(final_scan_s), "chosen_s"))

        seen_scan_values: set[float] = set()
        for candidate_scan_s, candidate_label in divstrip_scan_candidates:
            rounded_scan_s = round(float(candidate_scan_s), 6)
            if rounded_scan_s in seen_scan_values:
                continue
            seen_scan_values.add(rounded_scan_s)
            candidate_divstrip_geometry = selected_divstrip_geometry
            if (
                candidate_label == "body_center"
                and body_center_full_component is not None
                and not body_center_full_component.is_empty
            ):
                candidate_divstrip_geometry = body_center_full_component
            candidate_point = _materialize_divstrip_core_point(
                scan_origin_point=scan_origin_point,
                scan_axis_unit_vector=scan_axis_unit_vector,
                scan_dist_m=float(candidate_scan_s),
                cross_half_len_m=cross_half_len_m,
                branch_a_centerline=branch_a_centerline,
                branch_b_centerline=branch_b_centerline,
                divstrip_geometry=candidate_divstrip_geometry,
            )
            if candidate_point is None and candidate_label == "body_center" and body_center_full_component is not None:
                axis_anchor_point = _point_from_axis_offset(
                    origin_point=scan_origin_point,
                    axis_unit_vector=scan_axis_unit_vector,
                    offset_m=float(candidate_scan_s),
                )
                if (
                    body_center_full_component is not None
                    and not body_center_full_component.is_empty
                    and axis_anchor_point is not None
                    and not axis_anchor_point.is_empty
                ):
                    if body_center_full_component.buffer(1e-6).covers(axis_anchor_point):
                        candidate_point = axis_anchor_point
                    else:
                        try:
                            candidate_point = nearest_points(
                                axis_anchor_point, body_center_full_component
                            )[1]
                        except Exception:
                            candidate_point = None
            if candidate_point is None:
                continue
            chosen_point = candidate_point
            final_scan_s = _project_point_to_axis(
                candidate_point,
                origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
                axis_unit_vector=scan_axis_unit_vector,
            )
            resolved_split_pick_source = f"{resolved_split_pick_source}_{candidate_label}_core_point"
            break
    else:
        window_lo, window_hi, target_s = _build_ref_window_toward_node(
            ref_s=float(chosen_s),
            window_m=float(EVENT_REFERENCE_HARD_WINDOW_M),
        )
        if float(chosen_s) >= 0.0:
            window_lo = float(max(0.0, window_lo))
            window_hi = float(max(0.0, window_hi))
            target_s = float(max(0.0, target_s))
        else:
            window_lo = float(min(0.0, window_lo))
            window_hi = float(min(0.0, window_hi))
            target_s = float(min(0.0, target_s))
        if window_hi + 1e-9 < window_lo:
            window_lo = float(chosen_s)
            window_hi = float(chosen_s)
            target_s = float(chosen_s)
        probe_step = min(float(EVENT_REFERENCE_PROBE_STEP_M), max(0.05, step_m))
        candidate_scan_values: list[float] = []
        cursor = float(window_lo)
        while cursor <= float(window_hi) + 1e-9:
            candidate_scan_values.append(float(max(window_lo, min(window_hi, cursor))))
            cursor += probe_step
        if not candidate_scan_values:
            candidate_scan_values = [float(max(window_lo, min(window_hi, float(chosen_s))))]
        target_in_window = float(max(window_lo, min(window_hi, float(target_s))))
        if all(abs(float(value) - target_in_window) > 1e-6 for value in candidate_scan_values):
            candidate_scan_values.append(float(target_in_window))

        def _probe_scan_candidates(scan_values: list[float]) -> list[dict[str, Any]]:
            hits: list[dict[str, Any]] = []
            for scan_value in scan_values:
                crossline = _build_event_crossline(
                    origin_point=scan_origin_point,
                    axis_unit_vector=scan_axis_unit_vector,
                    scan_dist_m=float(scan_value),
                    cross_half_len_m=cross_half_len_m,
                )
                pieces = _segment_drivezone_pieces(
                    segment=crossline,
                    drivezone_union=drivezone_union,
                    min_piece_len_m=0.5,
                )
                if not pieces:
                    continue
                center_point = Point(
                    float(scan_origin_point.x) + float(scan_axis_unit_vector[0]) * float(scan_value),
                    float(scan_origin_point.y) + float(scan_axis_unit_vector[1]) * float(scan_value),
                )
                center_s = float(crossline.project(center_point))
                piece_info: list[tuple[float, float, float]] = []
                for piece in pieces:
                    values: list[float] = []
                    for coord in list(piece.coords):
                        if len(coord) < 2:
                            continue
                        values.append(float(crossline.project(Point(float(coord[0]), float(coord[1])))))
                    if not values:
                        continue
                    start_s = float(min(values))
                    end_s = float(max(values))
                    piece_info.append((start_s, end_s, 0.5 * (start_s + end_s)))
                if not piece_info:
                    continue
                has_center_piece = any(float(item[0]) - 1e-6 <= center_s <= float(item[1]) + 1e-6 for item in piece_info)
                hits.append(
                    {
                        "s": float(scan_value),
                        "raw_count": int(len(pieces)),
                        "has_center_piece": bool(has_center_piece),
                    }
                )
            return hits

        candidate_hits = _probe_scan_candidates(candidate_scan_values)
        backtrack_single_hit = None
        if _is_drivezone_position_source(position_source) and not any(int(hit["raw_count"]) == 1 for hit in candidate_hits):
            backtrack_candidates = _build_drivezone_backtrack_candidates(
                ref_s=float(chosen_s),
                start_s=float(target_in_window),
                probe_step=float(probe_step),
                past_node_m=float(EVENT_REFERENCE_BACKTRACK_PAST_NODE_M),
            )
            backtrack_hits = _probe_scan_candidates(backtrack_candidates)
            for hit in backtrack_hits:
                if int(hit["raw_count"]) == 1 and bool(hit["has_center_piece"]):
                    backtrack_single_hit = hit
                    break
            if backtrack_single_hit is None:
                for hit in backtrack_hits:
                    if int(hit["raw_count"]) == 1:
                        backtrack_single_hit = hit
                        break
            candidate_hits.extend(backtrack_hits)

        if candidate_hits:
            if backtrack_single_hit is not None:
                final_scan_s = float(backtrack_single_hit["s"])
                resolved_split_pick_source = f"{resolved_split_pick_source}_backtrack_single_piece"
            else:
                best_hit = min(
                    candidate_hits,
                    key=lambda hit: (
                        0 if bool(hit["has_center_piece"]) else 1,
                        0 if int(hit["raw_count"]) == 1 else 1,
                        int(hit["raw_count"]),
                        abs(float(hit["s"]) - float(target_in_window)),
                    ),
                )
                final_scan_s = float(best_hit["s"])

    if chosen_point is None:
        chosen_point = _point_from_axis_offset(
            origin_point=scan_origin_point,
            axis_unit_vector=scan_axis_unit_vector,
            offset_m=float(final_scan_s),
        )
    if drivezone_union is not None and not drivezone_union.is_empty and not drivezone_union.buffer(0).covers(chosen_point):
        safe_geometry = GeometryCollection()
        if selected_divstrip_geometry is not None and not selected_divstrip_geometry.is_empty:
            safe_geometry = selected_divstrip_geometry.intersection(drivezone_union).buffer(0)
        if safe_geometry.is_empty and all_divstrip_geometry is not None and not all_divstrip_geometry.is_empty:
            safe_geometry = all_divstrip_geometry.intersection(drivezone_union).buffer(0)
        if safe_geometry.is_empty:
            safe_geometry = drivezone_union.buffer(0)
        snapped_point = nearest_points(chosen_point, safe_geometry)[1]
        chosen_point = snapped_point
        final_scan_s = _project_point_to_axis(
            snapped_point,
            origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
            axis_unit_vector=scan_axis_unit_vector,
        )
        resolved_split_pick_source = f"{resolved_split_pick_source}_drivezone_clip"
    return {
        "origin_point": chosen_point,
        "chosen_s_m": float(final_scan_s),
        "split_pick_source": str(resolved_split_pick_source),
    }



__all__ = [name for name in globals() if not name.startswith("__")]
