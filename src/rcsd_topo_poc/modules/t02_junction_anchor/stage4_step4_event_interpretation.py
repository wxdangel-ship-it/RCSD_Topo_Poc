from __future__ import annotations

import math
from itertools import combinations
from typing import Any, Mapping, Sequence

from shapely.geometry import GeometryCollection, Point
from shapely.ops import nearest_points, unary_union

from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step4_contract import (
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
from rcsd_topo_poc.modules.t02_junction_anchor.shared import LoadedFeature, normalize_id
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import ParsedNode, ParsedRoad

from .stage4_geometry_utils import *
from .stage4_step2_local_context import _validate_drivezone_containment
from .stage4_step3_topology_skeleton import _build_stage4_road_branches_for_member_nodes
from .stage4_surface_assembly_utils import _resolve_centerline_from_road_ids

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


def _evaluate_branch_middle_gate(
    *,
    scan_origin_point: Point,
    scan_axis_unit_vector: tuple[float, float],
    candidate_point,
    candidate_scan_s: float,
    cross_half_len_m: float,
    branch_a_centerline,
    branch_b_centerline,
    divstrip_geometry,
) -> dict[str, Any]:
    if (
        candidate_point is None
        or candidate_point.is_empty
        or divstrip_geometry is None
        or divstrip_geometry.is_empty
    ):
        return {
            "valid": False,
            "signal": "event_reference_outside_branch_middle",
            "reason": "missing_candidate_or_divstrip",
            "point": candidate_point,
            "chosen_s_m": float(candidate_scan_s),
            "point_distance_m": math.inf,
            "component_distance_m": math.inf,
            "branch_middle_overlap": 0.0,
        }

    search_offsets = [0.0, -1.0, 1.0, -2.0, 2.0, -4.0, 4.0]
    best_result: dict[str, Any] | None = None
    for offset in search_offsets:
        if abs(float(offset)) > float(EVENT_REFERENCE_BRANCH_MIDDLE_SCAN_WINDOW_M) + 1e-9:
            continue
        scan_s = float(candidate_scan_s) + float(offset)
        probe_point = (
            candidate_point
            if abs(float(offset)) <= 1e-9
            else _materialize_divstrip_core_point(
                scan_origin_point=scan_origin_point,
                scan_axis_unit_vector=scan_axis_unit_vector,
                scan_dist_m=float(scan_s),
                cross_half_len_m=cross_half_len_m,
                branch_a_centerline=branch_a_centerline,
                branch_b_centerline=branch_b_centerline,
                divstrip_geometry=divstrip_geometry,
            )
        )
        if probe_point is None or probe_point.is_empty:
            continue
        crossline = _build_event_crossline(
            origin_point=scan_origin_point,
            axis_unit_vector=scan_axis_unit_vector,
            scan_dist_m=float(scan_s),
            cross_half_len_m=cross_half_len_m,
        )
        center_point = crossline.interpolate(0.5, normalized=True)
        found_segment, segment_diag = _build_between_branches_segment(
            crossline=crossline,
            center_point=center_point,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
        )
        if found_segment is None or not segment_diag["ok"]:
            continue
        point_distance_m = float(probe_point.distance(found_segment))
        component_related, component_distance_m, branch_middle_overlap = _component_reference_overlap_metrics(
            component_geometry=divstrip_geometry,
            reference_geometry=found_segment,
            reference_buffer_m=float(EVENT_REFERENCE_BRANCH_MIDDLE_TOL_M),
        )
        point_related = point_distance_m <= float(EVENT_REFERENCE_BRANCH_MIDDLE_TOL_M)
        valid = bool(
            point_related
            and (
                bool(component_related)
                or float(branch_middle_overlap) > 1e-6
                or float(component_distance_m) <= float(EVENT_REFERENCE_BRANCH_MIDDLE_TOL_M)
            )
        )
        score = (
            1 if valid else 0,
            1 if point_related else 0,
            1 if component_related else 0,
            float(branch_middle_overlap),
            -float(point_distance_m),
            -float(component_distance_m),
            -abs(float(offset)),
        )
        candidate_result = {
            "valid": valid,
            "signal": None if valid else "event_reference_outside_branch_middle",
            "reason": "branch_middle_gate_pass" if valid else "outside_branch_middle_tolerance",
            "point": probe_point,
            "chosen_s_m": _project_point_to_axis(
                probe_point,
                origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
                axis_unit_vector=scan_axis_unit_vector,
            ),
            "point_distance_m": float(point_distance_m),
            "component_distance_m": float(component_distance_m),
            "branch_middle_overlap": float(branch_middle_overlap),
            "_score": score,
        }
        if best_result is None or score > best_result["_score"]:
            best_result = candidate_result

    if best_result is None:
        return {
            "valid": False,
            "signal": "event_reference_outside_branch_middle",
            "reason": "missing_branch_middle_reference",
            "point": candidate_point,
            "chosen_s_m": float(candidate_scan_s),
            "point_distance_m": math.inf,
            "component_distance_m": math.inf,
            "branch_middle_overlap": 0.0,
        }
    best_result.pop("_score", None)
    return best_result


def _resolve_event_reference_point(
    *,
    representative_node: ParsedNode,
    event_anchor_geometry,
    divstrip_constraint_geometry,
    all_divstrip_geometry,
    axis_centerline,
    axis_unit_vector: tuple[float, float] | None,
    kind_2: int,
    drivezone_union,
    branch_a_centerline,
    branch_b_centerline,
    cross_half_len_m: float,
    patch_size_m: float,
    excluded_axis_s_values: list[float] | None = None,
    excluded_axis_tolerance_m: float = 5.0,
) -> dict[str, Any]:
    fallback_point, fallback_source = _resolve_event_origin_point(
        representative_node=representative_node,
        event_anchor_geometry=event_anchor_geometry,
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        axis_centerline=axis_centerline,
    )
    if axis_centerline is None or axis_centerline.is_empty or axis_unit_vector is None:
        return {
            "origin_point": fallback_point,
            "event_origin_source": fallback_source,
            "scan_origin_point": fallback_point,
            "scan_dir_label": "none",
            "chosen_s_m": None,
            "tip_s_m": None,
            "first_divstrip_hit_dist_m": None,
            "s_drivezone_split_m": None,
            "position_source": "fallback",
            "split_pick_source": "fallback_no_axis",
            "divstrip_ref_source": "none",
            "divstrip_ref_offset_m": None,
        }

    scan_origin_point, _ = nearest_points(axis_centerline, fallback_point)
    base_scan_axis_unit_vector = _resolve_scan_axis_unit_vector(
        axis_unit_vector=axis_unit_vector,
        kind_2=kind_2,
    )
    if base_scan_axis_unit_vector is None:
        return {
            "origin_point": fallback_point,
            "event_origin_source": fallback_source,
            "scan_origin_point": scan_origin_point,
            "scan_dir_label": "none",
            "chosen_s_m": None,
            "tip_s_m": None,
            "first_divstrip_hit_dist_m": None,
            "s_drivezone_split_m": None,
            "position_source": "fallback",
            "split_pick_source": "fallback_no_scan_dir",
            "divstrip_ref_source": "none",
            "divstrip_ref_offset_m": None,
        }

    search_limit_m = min(
        float(EVENT_REFERENCE_SCAN_MAX_M),
        max(float(EVENT_SPAN_MAX_M * 2.0), float(patch_size_m) * 0.45),
    )
    step_m = max(float(EVENT_REFERENCE_SCAN_STEP_M), 0.5)
    scan_values = [0.0]
    cursor = step_m
    while cursor <= search_limit_m + 1e-9:
        scan_values.append(float(cursor))
        cursor += step_m

    selected_divstrip_geometry = (
        divstrip_constraint_geometry
        if divstrip_constraint_geometry is not None and not divstrip_constraint_geometry.is_empty
        else all_divstrip_geometry
    )

    def _tip_projection_for_scan(scan_vec: tuple[float, float] | None) -> float | None:
        if (
            scan_vec is None
            or selected_divstrip_geometry is None
            or selected_divstrip_geometry.is_empty
        ):
            return None
        tip_point = _tip_point_from_divstrip(
            divstrip_geometry=selected_divstrip_geometry,
            scan_axis_unit_vector=scan_vec,
            origin_point=scan_origin_point,
        )
        if tip_point is None or tip_point.is_empty:
            return None
        candidate_tip_s = _project_point_to_axis(
            tip_point,
            origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
            axis_unit_vector=scan_vec,
        )
        if 0.0 <= float(candidate_tip_s) <= float(search_limit_m) + 1e-9:
            return float(candidate_tip_s)
        return None

    divstrip_components = _collect_polygon_components(all_divstrip_geometry)
    scan_axis_unit_vector = base_scan_axis_unit_vector
    tip_s_forward = _tip_projection_for_scan(base_scan_axis_unit_vector)
    tip_s = tip_s_forward

    first_divstrip_hit_s = None
    drivezone_split_s = None
    drivezone_split_source = "none"
    scan_samples: list[tuple[float, Any]] = []
    for scan_dist_m in scan_values:
        crossline = _build_event_crossline(
            origin_point=scan_origin_point,
            axis_unit_vector=scan_axis_unit_vector,
            scan_dist_m=scan_dist_m,
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
        scan_samples.append((float(scan_dist_m), probe_geometry))
        if drivezone_split_s is None and found_segment is not None and segment_diag["ok"]:
            drivezone_pieces = _segment_drivezone_pieces(
                segment=found_segment,
                drivezone_union=drivezone_union,
                min_piece_len_m=0.5,
            )
            if len(drivezone_pieces) >= 2:
                drivezone_split_s = float(scan_dist_m)
                drivezone_split_source = "between_branches"
            if drivezone_split_s is None:
                extended_segment = _extend_line_to_half_len(
                    line=found_segment,
                    half_len_m=max(0.5 * float(found_segment.length) + EVENT_REFERENCE_SPLIT_EXTEND_M, 0.1),
                )
                drivezone_pieces = _segment_drivezone_pieces(
                    segment=extended_segment,
                    drivezone_union=drivezone_union,
                    min_piece_len_m=0.5,
                )
                if len(drivezone_pieces) >= 2:
                    drivezone_split_s = float(scan_dist_m)
                    drivezone_split_source = "between_branches"
            if drivezone_split_s is None:
                drivezone_pieces = _segment_drivezone_pieces(
                    segment=crossline,
                    drivezone_union=drivezone_union,
                    min_piece_len_m=0.5,
                )
                if len(drivezone_pieces) >= 2:
                    drivezone_split_s = float(scan_dist_m)
                    drivezone_split_source = "full_crossline"
            if drivezone_split_s is not None and drivezone_split_source == "none":
                drivezone_split_s = float(scan_dist_m)
                drivezone_split_source = "between_branches"
        if (
            first_divstrip_hit_s is None
            and selected_divstrip_geometry is not None
            and not selected_divstrip_geometry.is_empty
            and float(probe_geometry.distance(selected_divstrip_geometry)) <= float(EVENT_REFERENCE_DIVSTRIP_TOL_M)
        ):
            first_divstrip_hit_s = float(scan_dist_m)

    if (
        drivezone_split_s is not None
        and len(divstrip_components) > 1
        and abs(float(drivezone_split_s)) >= 5.0 - 1e-9
    ):
        split_component, _split_component_distance = _pick_divstrip_component_near_split(
            scan_origin_point=scan_origin_point,
            scan_axis_unit_vector=scan_axis_unit_vector,
            split_s=float(drivezone_split_s),
            cross_half_len_m=cross_half_len_m,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            divstrip_components=divstrip_components,
        )
        if split_component is not None and not split_component.is_empty:
            selected_divstrip_geometry = split_component
            tip_point = _tip_point_from_divstrip(
                divstrip_geometry=selected_divstrip_geometry,
                scan_axis_unit_vector=scan_axis_unit_vector,
                origin_point=scan_origin_point,
            )
            tip_s = None
            if tip_point is not None and not tip_point.is_empty:
                candidate_tip_s = _project_point_to_axis(
                    tip_point,
                    origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
                    axis_unit_vector=scan_axis_unit_vector,
                )
                if 0.0 <= float(candidate_tip_s) <= float(search_limit_m) + 1e-9:
                    tip_s = float(candidate_tip_s)
            first_divstrip_hit_s, _best_divstrip_distance = _scan_first_divstrip_hit(
                scan_samples=scan_samples,
                divstrip_geometry=selected_divstrip_geometry,
                div_tol_m=float(EVENT_REFERENCE_DIVSTRIP_TOL_M),
            )

    divstrip_ref_s = None
    divstrip_ref_source = "none"
    if tip_s is not None:
        divstrip_ref_s = float(tip_s)
        divstrip_ref_source = "tip_projection"
    elif first_divstrip_hit_s is not None:
        divstrip_ref_s = float(first_divstrip_hit_s)
        divstrip_ref_source = "first_hit"

    if (
        drivezone_split_s is not None
        and drivezone_split_source == "full_crossline"
        and divstrip_ref_s is not None
        and abs(float(drivezone_split_s) - float(divstrip_ref_s)) > float(EVENT_REFERENCE_MAX_OFFSET_M)
    ):
        drivezone_split_s = None
        drivezone_split_source = "none"

    chosen_s, position_source, split_pick_source = _pick_reference_s(
        divstrip_ref_s=divstrip_ref_s,
        divstrip_ref_source=divstrip_ref_source,
        drivezone_split_s=drivezone_split_s,
        max_offset_m=float(EVENT_REFERENCE_MAX_OFFSET_M),
    )
    branch_middle_gate_signal: str | None = None
    branch_middle_gate_reason: str | None = None
    branch_middle_gate_phase: str | None = None
    force_reverse_probe = bool(
        divstrip_ref_s is None
        and selected_divstrip_geometry is not None
        and not selected_divstrip_geometry.is_empty
    )
    forward_drivezone_split_s = None if drivezone_split_s is None else float(drivezone_split_s)
    if force_reverse_probe:
        chosen_s = None
        position_source = "none"
        split_pick_source = "forward_divstrip_missing"
    resolved_candidate = None
    if chosen_s is not None:
        forward_candidate = _materialize_reference_candidate(
            scan_origin_point=scan_origin_point,
            scan_axis_unit_vector=scan_axis_unit_vector,
            chosen_s=float(chosen_s),
            position_source=str(position_source),
            split_pick_source=str(split_pick_source),
            tip_s=None if tip_s is None else float(tip_s),
            first_divstrip_hit_s=None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
            drivezone_split_s=None if drivezone_split_s is None else float(drivezone_split_s),
            divstrip_ref_s=None if divstrip_ref_s is None else float(divstrip_ref_s),
            cross_half_len_m=cross_half_len_m,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            selected_divstrip_geometry=selected_divstrip_geometry,
            drivezone_union=drivezone_union,
            all_divstrip_geometry=all_divstrip_geometry,
            step_m=step_m,
        )
        forward_gate = _evaluate_branch_middle_gate(
            scan_origin_point=scan_origin_point,
            scan_axis_unit_vector=scan_axis_unit_vector,
            candidate_point=forward_candidate["origin_point"],
            candidate_scan_s=float(forward_candidate["chosen_s_m"]),
            cross_half_len_m=cross_half_len_m,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            divstrip_geometry=selected_divstrip_geometry,
        )
        forward_axis_conflict = False
        if forward_gate["valid"] and excluded_axis_s_values:
            forward_chosen_s_value = float(forward_gate["chosen_s_m"])
            for prior_s in excluded_axis_s_values:
                if abs(float(prior_s) - forward_chosen_s_value) <= float(excluded_axis_tolerance_m) + 1e-9:
                    forward_axis_conflict = True
                    break
        if forward_gate["valid"] and not forward_axis_conflict:
            resolved_candidate = dict(forward_candidate)
            resolved_candidate["origin_point"] = forward_gate["point"]
            resolved_candidate["chosen_s_m"] = float(forward_gate["chosen_s_m"])
        else:
            if forward_axis_conflict:
                branch_middle_gate_signal = "event_reference_axis_conflict_with_prior_unit"
                branch_middle_gate_reason = "forward_axis_position_overlaps_prior_unit"
            else:
                branch_middle_gate_signal = str(forward_gate["signal"] or "event_reference_outside_branch_middle")
                branch_middle_gate_reason = str(forward_gate["reason"] or "outside_branch_middle_tolerance")
            branch_middle_gate_phase = "forward"
            chosen_s = None
            position_source = "none"
            split_pick_source = (
                f"{split_pick_source}_axis_conflict_with_prior_unit"
                if forward_axis_conflict
                else f"{split_pick_source}_outside_branch_middle"
            )
    if chosen_s is None:
        reverse_scan_axis_unit_vector = (-float(scan_axis_unit_vector[0]), -float(scan_axis_unit_vector[1]))
        reverse_tip_s = None
        if selected_divstrip_geometry is not None and not selected_divstrip_geometry.is_empty:
            reverse_tip_point = _tip_point_from_divstrip(
                divstrip_geometry=selected_divstrip_geometry,
                scan_axis_unit_vector=reverse_scan_axis_unit_vector,
                origin_point=scan_origin_point,
            )
            if reverse_tip_point is not None and not reverse_tip_point.is_empty:
                candidate_reverse_tip_s = _project_point_to_axis(
                    reverse_tip_point,
                    origin_xy=(float(scan_origin_point.x), float(scan_origin_point.y)),
                    axis_unit_vector=scan_axis_unit_vector,
                )
                if -float(search_limit_m) - 1e-9 <= float(candidate_reverse_tip_s) <= 1e-9:
                    reverse_tip_s = float(candidate_reverse_tip_s)

        reverse_first_divstrip_hit_s = None
        reverse_drivezone_split_s = None
        for scan_dist_m in scan_values:
            reverse_scan_dist = -float(scan_dist_m)
            crossline = _build_event_crossline(
                origin_point=scan_origin_point,
                axis_unit_vector=scan_axis_unit_vector,
                scan_dist_m=reverse_scan_dist,
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
            if reverse_drivezone_split_s is None and found_segment is not None and segment_diag["ok"]:
                drivezone_pieces = _segment_drivezone_pieces(
                    segment=found_segment,
                    drivezone_union=drivezone_union,
                    min_piece_len_m=0.5,
                )
                if len(drivezone_pieces) < 2:
                    extended_segment = _extend_line_to_half_len(
                        line=found_segment,
                        half_len_m=max(0.5 * float(found_segment.length) + EVENT_REFERENCE_SPLIT_EXTEND_M, 0.1),
                    )
                    drivezone_pieces = _segment_drivezone_pieces(
                        segment=extended_segment,
                        drivezone_union=drivezone_union,
                        min_piece_len_m=0.5,
                    )
                if len(drivezone_pieces) >= 2:
                    reverse_drivezone_split_s = reverse_scan_dist
            if (
                reverse_first_divstrip_hit_s is None
                and selected_divstrip_geometry is not None
                and not selected_divstrip_geometry.is_empty
                and float(probe_geometry.distance(selected_divstrip_geometry)) <= float(EVENT_REFERENCE_DIVSTRIP_TOL_M)
            ):
                reverse_first_divstrip_hit_s = reverse_scan_dist

        reverse_divstrip_ref_s = None
        reverse_divstrip_ref_source = "none"
        if reverse_tip_s is not None:
            reverse_divstrip_ref_s = float(reverse_tip_s)
            reverse_divstrip_ref_source = "tip_projection"
        elif reverse_first_divstrip_hit_s is not None:
            reverse_divstrip_ref_s = float(reverse_first_divstrip_hit_s)
            reverse_divstrip_ref_source = "first_hit"
        reverse_chosen_s, reverse_position_source, reverse_split_pick_source = _pick_reference_s(
            divstrip_ref_s=reverse_divstrip_ref_s,
            divstrip_ref_source=reverse_divstrip_ref_source,
            drivezone_split_s=reverse_drivezone_split_s,
            max_offset_m=float(EVENT_REFERENCE_MAX_OFFSET_M),
        )
        if reverse_chosen_s is not None:
            chosen_s = float(reverse_chosen_s)
            position_source = str(reverse_position_source)
            split_pick_source = f"reverse_{reverse_split_pick_source}"
            tip_s = None if reverse_tip_s is None else float(reverse_tip_s)
            first_divstrip_hit_s = (
                None if reverse_first_divstrip_hit_s is None else float(reverse_first_divstrip_hit_s)
            )
            drivezone_split_s = (
                None if reverse_drivezone_split_s is None else float(reverse_drivezone_split_s)
            )
            divstrip_ref_source = str(reverse_divstrip_ref_source)
            reverse_candidate = _materialize_reference_candidate(
                scan_origin_point=scan_origin_point,
                scan_axis_unit_vector=scan_axis_unit_vector,
                chosen_s=float(chosen_s),
                position_source=str(position_source),
                split_pick_source=str(split_pick_source),
                tip_s=None if tip_s is None else float(tip_s),
                first_divstrip_hit_s=None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
                drivezone_split_s=None if drivezone_split_s is None else float(drivezone_split_s),
                divstrip_ref_s=None if reverse_divstrip_ref_s is None else float(reverse_divstrip_ref_s),
                cross_half_len_m=cross_half_len_m,
                branch_a_centerline=branch_a_centerline,
                branch_b_centerline=branch_b_centerline,
                selected_divstrip_geometry=selected_divstrip_geometry,
                drivezone_union=drivezone_union,
                all_divstrip_geometry=all_divstrip_geometry,
                step_m=step_m,
            )
            reverse_gate = _evaluate_branch_middle_gate(
                scan_origin_point=scan_origin_point,
                scan_axis_unit_vector=scan_axis_unit_vector,
                candidate_point=reverse_candidate["origin_point"],
                candidate_scan_s=float(reverse_candidate["chosen_s_m"]),
                cross_half_len_m=cross_half_len_m,
                branch_a_centerline=branch_a_centerline,
                branch_b_centerline=branch_b_centerline,
                divstrip_geometry=selected_divstrip_geometry,
            )
            reverse_axis_conflict = False
            if reverse_gate["valid"] and excluded_axis_s_values:
                reverse_chosen_s_value = float(reverse_gate["chosen_s_m"])
                for prior_s in excluded_axis_s_values:
                    if abs(float(prior_s) - reverse_chosen_s_value) <= float(excluded_axis_tolerance_m) + 1e-9:
                        reverse_axis_conflict = True
                        break
            if reverse_gate["valid"] and not reverse_axis_conflict:
                resolved_candidate = dict(reverse_candidate)
                resolved_candidate["origin_point"] = reverse_gate["point"]
                resolved_candidate["chosen_s_m"] = float(reverse_gate["chosen_s_m"])
            else:
                chosen_s = None
                if reverse_axis_conflict:
                    branch_middle_gate_signal = "event_reference_axis_conflict_with_prior_unit"
                    branch_middle_gate_reason = "reverse_axis_position_overlaps_prior_unit"
                else:
                    branch_middle_gate_signal = str(reverse_gate["signal"] or "event_reference_outside_branch_middle")
                    branch_middle_gate_reason = str(reverse_gate["reason"] or "outside_branch_middle_tolerance")
                branch_middle_gate_phase = "reverse"
    if resolved_candidate is None and chosen_s is None and force_reverse_probe and forward_drivezone_split_s is not None:
        chosen_s = float(forward_drivezone_split_s)
        position_source = "drivezone_split"
        split_pick_source = "drivezone_split_window_after_reverse_probe"
        fallback_candidate = _materialize_reference_candidate(
            scan_origin_point=scan_origin_point,
            scan_axis_unit_vector=scan_axis_unit_vector,
            chosen_s=float(chosen_s),
            position_source=str(position_source),
            split_pick_source=str(split_pick_source),
            tip_s=None if tip_s is None else float(tip_s),
            first_divstrip_hit_s=None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
            drivezone_split_s=float(forward_drivezone_split_s),
            divstrip_ref_s=None if divstrip_ref_s is None else float(divstrip_ref_s),
            cross_half_len_m=cross_half_len_m,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            selected_divstrip_geometry=selected_divstrip_geometry,
            drivezone_union=drivezone_union,
            all_divstrip_geometry=all_divstrip_geometry,
            step_m=step_m,
        )
        fallback_gate = _evaluate_branch_middle_gate(
            scan_origin_point=scan_origin_point,
            scan_axis_unit_vector=scan_axis_unit_vector,
            candidate_point=fallback_candidate["origin_point"],
            candidate_scan_s=float(fallback_candidate["chosen_s_m"]),
            cross_half_len_m=cross_half_len_m,
            branch_a_centerline=branch_a_centerline,
            branch_b_centerline=branch_b_centerline,
            divstrip_geometry=selected_divstrip_geometry,
        )
        if fallback_gate["valid"]:
            resolved_candidate = dict(fallback_candidate)
            resolved_candidate["origin_point"] = fallback_gate["point"]
            resolved_candidate["chosen_s_m"] = float(fallback_gate["chosen_s_m"])
        else:
            chosen_s = None
            branch_middle_gate_signal = str(fallback_gate["signal"] or "event_reference_outside_branch_middle")
            branch_middle_gate_reason = str(fallback_gate["reason"] or "outside_branch_middle_tolerance")
            branch_middle_gate_phase = "fallback"
    if resolved_candidate is None:
        return {
            "origin_point": fallback_point,
            "event_origin_source": fallback_source,
            "scan_origin_point": scan_origin_point,
            "scan_dir_label": "forward" if kind_2 == 16 else "backward",
            "chosen_s_m": None,
            "tip_s_m": None if tip_s is None else float(tip_s),
            "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
            "s_drivezone_split_m": None if drivezone_split_s is None else float(drivezone_split_s),
            "position_source": "fallback",
            "split_pick_source": f"{split_pick_source}_fallback",
            "divstrip_ref_source": str(divstrip_ref_source),
            "divstrip_ref_offset_m": None,
            "branch_middle_gate_signal": branch_middle_gate_signal,
            "branch_middle_gate_reason": branch_middle_gate_reason,
            "branch_middle_gate_phase": branch_middle_gate_phase,
            "branch_middle_gate_passed": False,
        }
    final_scan_s = float(resolved_candidate["chosen_s_m"])
    chosen_point = resolved_candidate["origin_point"]
    split_pick_source = str(resolved_candidate["split_pick_source"])
    divstrip_ref_offset_m = (
        None
        if divstrip_ref_s is None
        else float(abs(float(final_scan_s) - float(divstrip_ref_s)))
    )
    return {
        "origin_point": chosen_point,
        "event_origin_source": f"chosen_s_{position_source}",
        "scan_origin_point": scan_origin_point,
        "scan_dir_label": "forward" if kind_2 == 16 else "backward",
        "chosen_s_m": float(final_scan_s),
        "tip_s_m": None if tip_s is None else float(tip_s),
        "first_divstrip_hit_dist_m": None if first_divstrip_hit_s is None else float(first_divstrip_hit_s),
        "s_drivezone_split_m": None if drivezone_split_s is None else float(drivezone_split_s),
        "position_source": str(position_source),
        "split_pick_source": str(split_pick_source),
        "divstrip_ref_source": str(divstrip_ref_source),
        "divstrip_ref_offset_m": divstrip_ref_offset_m,
        "branch_middle_gate_signal": branch_middle_gate_signal,
        "branch_middle_gate_reason": branch_middle_gate_reason,
        "branch_middle_gate_phase": branch_middle_gate_phase,
        "branch_middle_gate_passed": True,
    }


def _resolve_multibranch_context(
    *,
    road_branches,
    main_branch_ids: set[str],
    preferred_branch_ids: set[str],
    kind_2: int,
    local_roads: list[ParsedRoad],
    member_node_ids: set[str],
    drivezone_union,
    divstrip_constraint_geometry,
) -> dict[str, Any]:
    road_to_branch: dict[str, Any] = {}
    for branch in road_branches:
        for road_id in branch.road_ids:
            road_to_branch[road_id] = branch

    divstrip_geometry = None if divstrip_constraint_geometry is None or divstrip_constraint_geometry.is_empty else divstrip_constraint_geometry
    divstrip_probe_geometry = (
        None
        if divstrip_geometry is None
        else divstrip_geometry.buffer(DIVSTRIP_BRANCH_BUFFER_M, cap_style=2, join_style=2)
    )
    candidate_items: list[dict[str, Any]] = []
    for road in local_roads:
        candidate = _branch_candidate_from_road(
            road,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
        )
        if candidate is None:
            continue
        source_branch = road_to_branch.get(road.road_id)
        candidate_items.append(
            {
                "item_id": road.road_id,
                "source_branch_id": None if source_branch is None else source_branch.branch_id,
                "branch": source_branch,
                "angle_deg": float(candidate["angle_deg"]),
                "road_support_m": float(candidate["road_support_m"]),
                "has_incoming_support": bool(candidate["has_incoming_support"]),
                "has_outgoing_support": bool(candidate["has_outgoing_support"]),
                "divstrip_hit": bool(divstrip_probe_geometry is not None and road.geometry.intersects(divstrip_probe_geometry)),
                "divstrip_distance_m": (
                    math.inf
                    if divstrip_probe_geometry is None
                    else float(road.geometry.distance(divstrip_probe_geometry))
                ),
                "divstrip_overlap_m": (
                    0.0
                    if divstrip_probe_geometry is None
                    else float(road.geometry.intersection(divstrip_probe_geometry).length)
                ),
            }
        )

    best_main_pair_ids: tuple[str, str] | None = None
    best_main_pair_key: tuple[int, float, float] | None = None
    for first_item, second_item in combinations(candidate_items, 2):
        angle_gap = _branch_angle_gap_deg(first_item, second_item)
        if angle_gap < 180.0 - MAIN_AXIS_ANGLE_TOLERANCE_DEG:
            continue
        if not (first_item["has_incoming_support"] or second_item["has_incoming_support"]):
            continue
        if not (first_item["has_outgoing_support"] or second_item["has_outgoing_support"]):
            continue
        pair_key = (
            int(first_item["source_branch_id"] in main_branch_ids) + int(second_item["source_branch_id"] in main_branch_ids),
            -abs(180.0 - angle_gap),
            float(first_item["road_support_m"] + second_item["road_support_m"]),
        )
        if best_main_pair_key is None or pair_key > best_main_pair_key:
            best_main_pair_key = pair_key
            best_main_pair_ids = (str(first_item["item_id"]), str(second_item["item_id"]))

    main_pair_ids = set(best_main_pair_ids or ())
    candidate_items = [item for item in candidate_items if item["item_id"] not in main_pair_ids]
    multibranch_enabled = len({item["source_branch_id"] for item in candidate_items if item["source_branch_id"] is not None}) >= 2
    if not multibranch_enabled:
        return {
            "enabled": False,
            "n": len(candidate_items),
            "main_pair_item_ids": [] if best_main_pair_ids is None else list(best_main_pair_ids),
            "event_candidate_count": 0,
            "event_candidates": [],
            "selected_event_index": None,
            "selected_event_branch_ids": [],
            "selected_event_source_branch_ids": [],
            "selected_side_branches": [],
            "branches_used_count": 0,
            "ambiguous": False,
        }

    event_candidates: list[dict[str, Any]] = []
    for pair in combinations(candidate_items, 2):
        if pair[0]["source_branch_id"] == pair[1]["source_branch_id"]:
            continue
        pair_ids = sorted(str(item["item_id"]) for item in pair)
        pair_branches = [item["branch"] for item in pair if item["branch"] is not None]
        if len(pair_branches) != 2:
            continue
        preferred_hits = len({str(item["source_branch_id"]) for item in pair if item["source_branch_id"] is not None} & preferred_branch_ids)
        adjacency_gap = _branch_angle_gap_deg(pair[0], pair[1])
        divstrip_hit_count = sum(1 for item in pair if item["divstrip_hit"])
        divstrip_overlap_m = float(sum(item["divstrip_overlap_m"] for item in pair))
        divstrip_distance_m = float(min(item["divstrip_distance_m"] for item in pair))
        directional_hits = (
            sum(1 for item in pair if item["has_incoming_support"])
            if kind_2 == 8
            else sum(1 for item in pair if item["has_outgoing_support"])
        )
        score = (
            float(sum(item["road_support_m"] for item in pair))
            + preferred_hits * 100.0
            + divstrip_hit_count * 50.0
            + divstrip_overlap_m * 5.0
            + directional_hits * 25.0
            - adjacency_gap * 0.1
            - divstrip_distance_m * 0.25
        )
        event_candidates.append(
            {
                "road_ids": pair_ids,
                "branches": pair_branches,
                "source_branch_ids": sorted({branch.branch_id for branch in pair_branches}),
                "score": score,
                "preferred_hits": preferred_hits,
                "divstrip_hit_count": divstrip_hit_count,
                "divstrip_overlap_m": divstrip_overlap_m,
                "divstrip_distance_m": divstrip_distance_m,
                "directional_hits": directional_hits,
                "adjacency_gap": adjacency_gap,
            }
        )

    event_candidates.sort(
        key=lambda candidate: (
            candidate["preferred_hits"],
            candidate["divstrip_hit_count"],
            candidate["divstrip_overlap_m"],
            candidate["directional_hits"],
            candidate["score"],
            -candidate["divstrip_distance_m"],
            -candidate["adjacency_gap"],
        ),
        reverse=True,
    )
    top_candidate = event_candidates[0] if event_candidates else None
    if (
        len(event_candidates) == 1
        and top_candidate is not None
        and float(top_candidate["adjacency_gap"]) >= 180.0 - MAIN_AXIS_ANGLE_TOLERANCE_DEG
        and int(top_candidate["preferred_hits"]) <= 1
    ):
        return {
            "enabled": False,
            "n": len(candidate_items),
            "main_pair_item_ids": [] if best_main_pair_ids is None else list(best_main_pair_ids),
            "event_candidate_count": len(event_candidates),
            "event_candidates": [],
            "selected_event_index": None,
            "selected_event_branch_ids": [],
            "selected_event_source_branch_ids": [],
            "selected_side_branches": [],
            "branches_used_count": 0,
            "ambiguous": False,
        }
    ambiguous = False
    if len(event_candidates) > 1 and top_candidate is not None:
        second_candidate = event_candidates[1]
        ambiguous = (
            abs(float(top_candidate["score"]) - float(second_candidate["score"])) <= MULTIBRANCH_AMBIGUITY_SCORE_MARGIN
            and top_candidate["divstrip_hit_count"] == second_candidate["divstrip_hit_count"]
            and abs(float(top_candidate["divstrip_overlap_m"]) - float(second_candidate["divstrip_overlap_m"])) <= 1.0
            and top_candidate["directional_hits"] == second_candidate["directional_hits"]
            and {branch.branch_id for branch in top_candidate["branches"]} != {branch.branch_id for branch in second_candidate["branches"]}
            and top_candidate["road_ids"] != second_candidate["road_ids"]
        )
    return {
        "enabled": True,
        "n": len(candidate_items),
        "main_pair_item_ids": [] if best_main_pair_ids is None else list(best_main_pair_ids),
        "event_candidate_count": len(event_candidates),
        "event_candidates": [
            {
                "road_ids": list(candidate["road_ids"]),
                "source_branch_ids": list(candidate["source_branch_ids"]),
                "score": float(candidate["score"]),
                "preferred_hits": int(candidate["preferred_hits"]),
                "divstrip_hit_count": int(candidate["divstrip_hit_count"]),
                "divstrip_overlap_m": float(candidate["divstrip_overlap_m"]),
                "divstrip_distance_m": float(candidate["divstrip_distance_m"]),
                "directional_hits": int(candidate["directional_hits"]),
                "adjacency_gap": float(candidate["adjacency_gap"]),
            }
            for candidate in event_candidates
        ],
        "selected_event_index": 0 if top_candidate is not None else None,
        "selected_event_branch_ids": [] if top_candidate is None else list(top_candidate["road_ids"]),
        "selected_event_source_branch_ids": (
            []
            if top_candidate is None
            else list(top_candidate["source_branch_ids"])
        ),
        "selected_side_branches": [] if top_candidate is None else list(top_candidate["branches"]),
        "branches_used_count": 0 if top_candidate is None else len({branch.branch_id for branch in top_candidate["branches"]}),
        "ambiguous": ambiguous,
    }


def _is_stage4_representative(node: ParsedNode) -> bool:
    representative_id = node.mainnodeid or node.node_id
    return (
        node.has_evd == "yes"
        and node.is_anchor == "no"
        and _is_stage4_supported_node_kind(node)
        and normalize_id(node.node_id) == normalize_id(representative_id)
    )


def _stage4_chain_kind_2(node: ParsedNode) -> int | None:
    source_kind_2 = _node_source_kind_2(node)
    if source_kind_2 in STAGE4_KIND_2_VALUES or source_kind_2 == COMPLEX_JUNCTION_KIND:
        return source_kind_2
    if _node_source_kind(node) == COMPLEX_JUNCTION_KIND:
        return COMPLEX_JUNCTION_KIND
    return None


def _infer_operational_kind_2_from_divstrip_event(
    *,
    representative_node: ParsedNode,
    road_branches,
    local_roads: list[ParsedRoad],
    divstrip_context: dict[str, Any],
    chain_context: dict[str, Any],
) -> dict[str, Any] | None:
    divstrip_constraint_geometry = divstrip_context["constraint_geometry"]
    if (
        divstrip_constraint_geometry is None
        or divstrip_constraint_geometry.is_empty
        or not divstrip_context["nearby"]
        or divstrip_context["ambiguous"]
    ):
        return None

    event_reference_point = divstrip_constraint_geometry.centroid
    road_lookup = {road.road_id: road for road in local_roads}
    merge_score = 0.0
    diverge_score = 0.0
    merge_hits = 0
    diverge_hits = 0
    for branch in road_branches:
        centerline = _resolve_branch_centerline(
            branch=branch,
            road_lookup=road_lookup,
            reference_point=representative_node.geometry,
        )
        if centerline is None or centerline.is_empty:
            continue
        representative_dist = float(centerline.project(representative_node.geometry))
        event_dist = float(centerline.project(event_reference_point))
        branch_support = max(1.0, _selected_branch_score(branch))
        if branch.has_incoming_support:
            post_event_m = float(representative_dist - event_dist)
            if post_event_m >= DIVSTRIP_KIND_POSITION_MARGIN_M:
                merge_hits += 1
                merge_score += branch_support + min(post_event_m, 40.0)
        if branch.has_outgoing_support:
            pre_event_m = float(event_dist - representative_dist)
            if pre_event_m >= DIVSTRIP_KIND_POSITION_MARGIN_M:
                diverge_hits += 1
                diverge_score += branch_support + min(pre_event_m, 40.0)

    if chain_context["is_in_continuous_chain"] and chain_context["sequential_ok"]:
        if diverge_score > 0.0:
            diverge_score += 25.0
        if merge_score > 0.0:
            merge_score += 25.0

    if merge_score <= 0.0 and diverge_score <= 0.0:
        return None

    if merge_score > diverge_score:
        operational_kind_2 = 8
    elif diverge_score > merge_score:
        operational_kind_2 = 16
    elif merge_hits > diverge_hits:
        operational_kind_2 = 8
    elif diverge_hits > merge_hits:
        operational_kind_2 = 16
    else:
        operational_kind_2 = 16

    ambiguous = (
        abs(merge_score - diverge_score) <= MULTIBRANCH_AMBIGUITY_SCORE_MARGIN
        and merge_hits == diverge_hits
    )
    return {
        "operational_kind_2": operational_kind_2,
        "ambiguous": ambiguous,
        "kind_resolution_mode": (
            "continuous_chain_divstrip_event"
            if chain_context["is_in_continuous_chain"] and chain_context["sequential_ok"]
            else "divstrip_event_position"
        ),
        "merge_score": round(merge_score, 3),
        "diverge_score": round(diverge_score, 3),
        "merge_hits": merge_hits,
        "diverge_hits": diverge_hits,
    }


def _resolve_operational_kind_2(
    *,
    representative_node: ParsedNode,
    road_branches,
    main_branch_ids: set[str],
    preferred_branch_ids: set[str],
    local_roads: list[ParsedRoad],
    divstrip_context: dict[str, Any],
    chain_context: dict[str, Any],
    multibranch_context: dict[str, Any],
) -> dict[str, Any]:
    source_kind = _node_source_kind(representative_node)
    source_kind_2 = _node_source_kind_2(representative_node)
    if source_kind_2 in STAGE4_KIND_2_VALUES:
        return {
            "source_kind": source_kind,
            "source_kind_2": source_kind_2,
            "operational_kind_2": int(source_kind_2),
            "complex_junction": False,
            "ambiguous": False,
            "kind_resolution_mode": "direct_kind_2",
            "merge_score": None,
            "diverge_score": None,
            "merge_hits": None,
            "diverge_hits": None,
        }
    divstrip_kind_resolution = None
    if len(road_branches) <= 2 or source_kind == COMPLEX_JUNCTION_KIND or source_kind_2 == COMPLEX_JUNCTION_KIND:
        divstrip_kind_resolution = _infer_operational_kind_2_from_divstrip_event(
            representative_node=representative_node,
            road_branches=road_branches,
            local_roads=local_roads,
            divstrip_context=divstrip_context,
            chain_context=chain_context,
        )
    if divstrip_kind_resolution is not None and not divstrip_kind_resolution["ambiguous"]:
        return {
            "source_kind": source_kind,
            "source_kind_2": source_kind_2,
            "operational_kind_2": divstrip_kind_resolution["operational_kind_2"],
            "complex_junction": source_kind == COMPLEX_JUNCTION_KIND or source_kind_2 == COMPLEX_JUNCTION_KIND,
            "ambiguous": False,
            "kind_resolution_mode": divstrip_kind_resolution["kind_resolution_mode"],
            "merge_score": divstrip_kind_resolution["merge_score"],
            "diverge_score": divstrip_kind_resolution["diverge_score"],
            "merge_hits": divstrip_kind_resolution["merge_hits"],
            "diverge_hits": divstrip_kind_resolution["diverge_hits"],
        }
    if source_kind != COMPLEX_JUNCTION_KIND and source_kind_2 != COMPLEX_JUNCTION_KIND:
        raise Stage4RunError(
            REASON_MAINNODEID_OUT_OF_SCOPE,
            (
                f"mainnodeid='{normalize_id(representative_node.mainnodeid or representative_node.node_id)}' "
                f"has unsupported kind={source_kind}, kind_2={source_kind_2}."
            ),
        )

    side_branches = [branch for branch in road_branches if branch.branch_id not in main_branch_ids]
    preferred_complex_branches = [
        branch
        for branch in road_branches
        if branch.branch_id in preferred_branch_ids
    ]
    if not side_branches and len(preferred_complex_branches) == 1:
        preferred_branch = preferred_complex_branches[0]
        if preferred_branch.has_incoming_support and not preferred_branch.has_outgoing_support:
            return {
                "source_kind": source_kind,
                "source_kind_2": source_kind_2,
                "operational_kind_2": 8,
                "complex_junction": True,
                "ambiguous": False,
                "kind_resolution_mode": "complex_divstrip_preferred_branch",
                "merge_score": None if divstrip_kind_resolution is None else divstrip_kind_resolution["merge_score"],
                "diverge_score": None if divstrip_kind_resolution is None else divstrip_kind_resolution["diverge_score"],
                "merge_hits": None if divstrip_kind_resolution is None else divstrip_kind_resolution["merge_hits"],
                "diverge_hits": None if divstrip_kind_resolution is None else divstrip_kind_resolution["diverge_hits"],
            }
        if preferred_branch.has_outgoing_support and not preferred_branch.has_incoming_support:
            return {
                "source_kind": source_kind,
                "source_kind_2": source_kind_2,
                "operational_kind_2": 16,
                "complex_junction": True,
                "ambiguous": False,
                "kind_resolution_mode": "complex_divstrip_preferred_branch",
                "merge_score": None if divstrip_kind_resolution is None else divstrip_kind_resolution["merge_score"],
                "diverge_score": None if divstrip_kind_resolution is None else divstrip_kind_resolution["diverge_score"],
                "merge_hits": None if divstrip_kind_resolution is None else divstrip_kind_resolution["merge_hits"],
                "diverge_hits": None if divstrip_kind_resolution is None else divstrip_kind_resolution["diverge_hits"],
            }
    if (
        not side_branches
        and multibranch_context.get("enabled", False)
        and multibranch_context.get("selected_event_index") is not None
        and not multibranch_context.get("ambiguous", False)
    ):
        fallback_kind_2 = 16
        if divstrip_kind_resolution is not None:
            fallback_kind_2 = int(divstrip_kind_resolution["operational_kind_2"])
        return {
            "source_kind": source_kind,
            "source_kind_2": source_kind_2,
            "operational_kind_2": fallback_kind_2,
            "complex_junction": True,
            "ambiguous": False,
            "kind_resolution_mode": "complex_multibranch_event",
            "merge_score": None if divstrip_kind_resolution is None else divstrip_kind_resolution["merge_score"],
            "diverge_score": None if divstrip_kind_resolution is None else divstrip_kind_resolution["diverge_score"],
            "merge_hits": None if divstrip_kind_resolution is None else divstrip_kind_resolution["merge_hits"],
            "diverge_hits": None if divstrip_kind_resolution is None else divstrip_kind_resolution["diverge_hits"],
        }

    merge_score = 0.0
    diverge_score = 0.0
    merge_hits = 0
    diverge_hits = 0
    merge_preferred_hits = 0
    diverge_preferred_hits = 0
    for branch in side_branches:
        branch_score = max(1.0, _selected_branch_score(branch))
        if branch.has_incoming_support:
            merge_hits += 1
            merge_score += branch_score
            if branch.branch_id in preferred_branch_ids:
                merge_preferred_hits += 1
                merge_score += 100.0
        if branch.has_outgoing_support:
            diverge_hits += 1
            diverge_score += branch_score
            if branch.branch_id in preferred_branch_ids:
                diverge_preferred_hits += 1
                diverge_score += 100.0

    if merge_score > diverge_score:
        operational_kind_2 = 8
    elif diverge_score > merge_score:
        operational_kind_2 = 16
    elif merge_hits > diverge_hits:
        operational_kind_2 = 8
    elif diverge_hits > merge_hits:
        operational_kind_2 = 16
    elif merge_preferred_hits > diverge_preferred_hits:
        operational_kind_2 = 8
    else:
        operational_kind_2 = 16

    ambiguous = (
        not side_branches
        or (
            abs(merge_score - diverge_score) <= MULTIBRANCH_AMBIGUITY_SCORE_MARGIN
            and merge_hits == diverge_hits
            and merge_preferred_hits == diverge_preferred_hits
        )
    )
    return {
        "source_kind": source_kind,
        "source_kind_2": source_kind_2,
        "operational_kind_2": operational_kind_2,
        "complex_junction": True,
        "ambiguous": ambiguous,
        "kind_resolution_mode": "complex_branch_direction",
        "merge_score": round(merge_score, 3),
        "diverge_score": round(diverge_score, 3),
        "merge_hits": merge_hits,
        "diverge_hits": diverge_hits,
    }


def _build_continuous_chain_context(
    *,
    representative_node: ParsedNode,
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    enabled: bool = True,
) -> dict[str, Any]:
    representative_mainnodeid = normalize_id(representative_node.mainnodeid or representative_node.node_id)
    if not enabled:
        return {
            "chain_component_id": representative_mainnodeid,
            "related_mainnodeids": [],
            "is_in_continuous_chain": False,
            "chain_node_count": 1,
            "chain_node_offset_m": None,
            "sequential_ok": False,
            "related_seed_nodes": [],
        }

    chain_candidates, chain_trace = _chain_candidates_from_topology(
        representative_node_id=representative_node.node_id,
        representative_chain_kind_2=_stage4_chain_kind_2(representative_node),
        local_nodes=local_nodes,
        local_roads=local_roads,
        chain_span_limit_m=CHAIN_CONTEXT_EVENT_SPAN_M,
    )

    chain_candidates.sort(key=lambda item: item[1])
    related_mainnodeids = [normalize_id(candidate.mainnodeid or candidate.node_id) for candidate, _ in chain_candidates]
    nearest_offset_m = None if not chain_candidates else round(abs(chain_candidates[0][1]), 3)
    sequential_ok = any(
        abs(offset_m) <= CHAIN_SEQUENCE_DISTANCE_M
        for _, offset_m in chain_candidates
    )
    related_directions = [1 if offset_m >= 0.0 else -1 for _, offset_m in chain_candidates]
    has_forward_chain = any(sign > 0 for sign in related_directions)
    has_backward_chain = any(sign < 0 for sign in related_directions)
    chain_node_ids = [normalize_id(candidate.node_id) for candidate, _ in chain_candidates]
    chain_member_ids = [representative_mainnodeid, *related_mainnodeids]
    return {
        "chain_component_id": "__".join(sorted(chain_member_ids)) if len(chain_member_ids) > 1 else representative_mainnodeid,
        "related_mainnodeids": related_mainnodeids,
        "is_in_continuous_chain": bool(chain_candidates),
        "chain_node_count": 1 + len(chain_candidates),
        "chain_node_offset_m": nearest_offset_m,
        "sequential_ok": sequential_ok,
        "chain_bidirectional": has_forward_chain and has_backward_chain,
        "chain_node_ids": chain_node_ids,
        "chain_node_trace": chain_trace,
        "related_seed_nodes": [candidate for candidate, offset_m in chain_candidates if abs(offset_m) <= CHAIN_SEQUENCE_DISTANCE_M],
    }


def _build_stage4_interpretation_review_signals(
    *,
    divstrip_context: dict[str, Any],
    multibranch_context: dict[str, Any],
    kind_resolution: dict[str, Any],
    chain_context: dict[str, Any],
) -> tuple[str, ...]:
    review_signals: list[str] = []
    if bool(multibranch_context.get("ambiguous", False)):
        review_signals.append(STATUS_MULTIBRANCH_EVENT_AMBIGUOUS)
    if bool(divstrip_context.get("ambiguous", False)):
        review_signals.append(STATUS_DIVSTRIP_COMPONENT_AMBIGUOUS)
    if (
        bool(chain_context.get("is_in_continuous_chain", False))
        and bool(chain_context.get("sequential_ok", False))
        and not bool(kind_resolution.get("complex_junction", False))
        and bool(chain_context.get("chain_bidirectional", False))
    ):
        review_signals.append(STATUS_CONTINUOUS_CHAIN_REVIEW)
    if bool(kind_resolution.get("ambiguous", False)):
        review_signals.append(STATUS_COMPLEX_KIND_AMBIGUOUS)
    return tuple(review_signals)


def _build_stage4_interpretation_risk_signals(
    *,
    review_signals: tuple[str, ...],
    reverse_tip_used: bool,
    fallback_mode: str | None,
) -> tuple[str, ...]:
    risk_signals = list(review_signals)
    if reverse_tip_used:
        risk_signals.append("reverse_tip_used")
    if fallback_mode is not None:
        risk_signals.append("fallback_to_weak_evidence")
    return tuple(risk_signals)


def _evaluate_stage4_legacy_step5_readiness(
    *,
    selected_branch_ids: Sequence[str],
    event_reference: Mapping[str, Any],
) -> Stage4LegacyStep5Readiness:
    reasons: list[str] = []
    if not selected_branch_ids:
        reasons.append("selected_branch_ids_empty")
    if event_reference.get("origin_point") is None:
        reasons.append("missing_event_origin")
    return Stage4LegacyStep5Readiness(
        ready=not reasons,
        reasons=tuple(reasons),
    )


def _build_stage4_event_interpretation(
    *,
    representative_node: ParsedNode,
    representative_source_kind_2: int | None,
    mainnodeid_norm: str,
    seed_union,
    group_nodes: Sequence[ParsedNode],
    patch_size_m: float,
    seed_center,
    drivezone_union,
    local_roads: list[ParsedRoad],
    local_rcsd_roads: list[ParsedRoad],
    local_rcsd_nodes: list[ParsedNode],
    local_divstrip_features: list[LoadedFeature],
    road_branches: list[Any],
    main_branch_ids: set[str],
    member_node_ids: set[str],
    event_branch_ids: set[str] | None = None,
    boundary_branch_ids: Sequence[str] | None = None,
    preferred_axis_branch_id: str | None = None,
    context_augmented_node_ids: set[str] | None = None,
    degraded_scope_reason: str | None = None,
    direct_target_rc_nodes: list[ParsedNode],
    exact_target_rc_nodes: list[ParsedNode],
    primary_main_rc_node: ParsedNode | None,
    rcsdnode_seed_mode: str,
    chain_context: dict[str, Any],
    excluded_component_geometries: list[Any] | None = None,
    excluded_axis_positions: list[tuple[str, float]] | None = None,
) -> Stage4EventInterpretationResult:
    provisional_multibranch_kind_2 = (
        int(representative_source_kind_2)
        if representative_source_kind_2 in STAGE4_KIND_2_VALUES
        else 16
    )
    explicit_event_branch_ids = {
        str(branch_id)
        for branch_id in (event_branch_ids or set())
        if branch_id is not None
    }
    explicit_boundary_branch_ids = tuple(
        str(branch_id)
        for branch_id in (boundary_branch_ids or ())
        if branch_id is not None
    )
    divstrip_context_raw = _analyze_divstrip_context(
        local_divstrip_features=local_divstrip_features,
        seed_union=seed_union,
        road_branches=road_branches,
        local_roads=local_roads,
        main_branch_ids=main_branch_ids,
        drivezone_union=drivezone_union,
        event_branch_ids=explicit_event_branch_ids or None,
        allow_compound_pair_merge=_is_complex_stage4_node(representative_node) or len(group_nodes) > 1,
        excluded_component_geometries=excluded_component_geometries,
    )
    preferred_branch_ids = set(divstrip_context_raw["preferred_branch_ids"]) | explicit_event_branch_ids
    multibranch_context_raw = _resolve_multibranch_context(
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        preferred_branch_ids=preferred_branch_ids,
        kind_2=provisional_multibranch_kind_2,
        local_roads=local_roads,
        member_node_ids=member_node_ids,
        drivezone_union=drivezone_union,
        divstrip_constraint_geometry=divstrip_context_raw["constraint_geometry"],
    )
    kind_resolution_raw = _resolve_operational_kind_2(
        representative_node=representative_node,
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        preferred_branch_ids=preferred_branch_ids,
        local_roads=local_roads,
        divstrip_context=divstrip_context_raw,
        chain_context=chain_context,
        multibranch_context=multibranch_context_raw,
    )
    operational_kind_2 = kind_resolution_raw["operational_kind_2"]
    if operational_kind_2 != provisional_multibranch_kind_2:
        multibranch_context_raw = _resolve_multibranch_context(
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            preferred_branch_ids=preferred_branch_ids,
            kind_2=operational_kind_2,
            local_roads=local_roads,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
            divstrip_constraint_geometry=divstrip_context_raw["constraint_geometry"],
        )
    forward_side_branches = _select_stage4_side_branches(
        road_branches,
        kind_2=operational_kind_2,
        preferred_branch_ids=preferred_branch_ids,
    )
    position_source_forward = divstrip_context_raw["selection_mode"]
    reverse_trigger: str | None = None
    reverse_tip_attempted = False
    reverse_tip_used = False
    position_source_reverse: str | None = None
    reverse_side_branches: list[Any] = []
    if explicit_event_branch_ids:
        selected_side_branches = [
            branch for branch in road_branches if str(branch.branch_id) in explicit_event_branch_ids
        ]
    else:
        selected_side_branches = (
            list(multibranch_context_raw["selected_side_branches"])
            if multibranch_context_raw["enabled"] and multibranch_context_raw["selected_side_branches"]
            else list(forward_side_branches)
        )

    selected_event_branch_ids = (
        sorted(explicit_event_branch_ids)
        if explicit_event_branch_ids
        else (
            multibranch_context_raw["selected_event_branch_ids"]
            if multibranch_context_raw["enabled"] and multibranch_context_raw["selected_event_branch_ids"]
            else sorted(branch.branch_id for branch in selected_side_branches)
        )
    )
    refined_divstrip_context_raw = _analyze_divstrip_context(
        local_divstrip_features=local_divstrip_features,
        seed_union=seed_union,
        road_branches=road_branches,
        local_roads=local_roads,
        main_branch_ids=main_branch_ids,
        drivezone_union=drivezone_union,
        event_branch_ids=set(selected_event_branch_ids),
        allow_compound_pair_merge=kind_resolution_raw["complex_junction"] or len(group_nodes) > 1,
        excluded_component_geometries=excluded_component_geometries,
    )
    if (
        refined_divstrip_context_raw["nearby"]
        or refined_divstrip_context_raw["ambiguous"]
        or refined_divstrip_context_raw["selected_component_ids"]
    ):
        divstrip_context_raw = refined_divstrip_context_raw
        preferred_branch_ids = set(divstrip_context_raw["preferred_branch_ids"]) | explicit_event_branch_ids
    position_source_forward = divstrip_context_raw["selection_mode"]
    position_source_final = (
        position_source_reverse
        if reverse_tip_used and position_source_reverse is not None
        else ("multibranch_event" if multibranch_context_raw["enabled"] else position_source_forward)
    )
    selected_branch_ids = (
        list(explicit_boundary_branch_ids)
        if explicit_boundary_branch_ids
        else (
            sorted(multibranch_context_raw["selected_event_source_branch_ids"])
            if multibranch_context_raw["enabled"] and multibranch_context_raw["selected_event_source_branch_ids"]
            else sorted(main_branch_ids | {branch.branch_id for branch in selected_side_branches})
        )
    )
    selected_road_ids = sorted(
        {
            road_id
            for branch in road_branches
            if branch.branch_id in selected_branch_ids
            for road_id in branch.road_ids
        }
    )
    selected_event_road_ids = {
        road_id
        for branch in road_branches
        if branch.branch_id in set(selected_event_branch_ids)
        for road_id in branch.road_ids
    }
    selected_rcsdroad_ids: set[str] = set()
    _, _, rc_branches = _build_stage4_road_branches_for_member_nodes(
        local_rcsd_roads,
        member_node_ids=member_node_ids,
        drivezone_union=drivezone_union,
        include_internal_roads=False,
        support_center=None,
    )
    for rc_branch in rc_branches:
        for road_branch in road_branches:
            if road_branch.branch_id not in selected_branch_ids:
                continue
            angle_gap = abs(road_branch.angle_deg - rc_branch.angle_deg)
            wrapped_angle_gap = min(angle_gap, 360.0 - angle_gap)
            if angle_gap <= 35.0 or wrapped_angle_gap <= 35.0:
                selected_rcsdroad_ids.update(rc_branch.road_ids)
                break
    rcsdroad_selection_mode = "angle_match"
    if not selected_rcsdroad_ids:
        nearby_rcsd_roads = [
            road
            for road in local_rcsd_roads
            if road.geometry.distance(seed_center) <= max(30.0, patch_size_m / 5.0)
        ]
        inside_nearby_rcsd_roads = [
            road
            for road in nearby_rcsd_roads
            if drivezone_union.buffer(0).covers(road.geometry)
        ]
        fallback_rcsd_roads = inside_nearby_rcsd_roads or nearby_rcsd_roads
        selected_rcsdroad_ids = {road.road_id for road in fallback_rcsd_roads}
        rcsdroad_selection_mode = (
            "fallback_nearby_inside_only"
            if inside_nearby_rcsd_roads
            else "fallback_nearby_any"
        )

    selected_roads = [road for road in local_roads if road.road_id in selected_road_ids]
    selected_event_roads = [road for road in local_roads if road.road_id in selected_event_road_ids]
    selected_rcsd_roads = [road for road in local_rcsd_roads if road.road_id in selected_rcsdroad_ids]
    complex_local_support_roads: list[ParsedRoad] = []
    if kind_resolution_raw["complex_junction"] or len(group_nodes) > 1:
        complex_support_seed_union = unary_union(
            [
                *[node.geometry.buffer(NODE_SEED_RADIUS_M) for node in group_nodes],
                *[
                    node.geometry.buffer(max(1.5, NODE_SEED_RADIUS_M * 0.6))
                    for node in chain_context["related_seed_nodes"]
                ],
            ]
        )
        if complex_support_seed_union is not None and not complex_support_seed_union.is_empty:
            selected_road_id_set = set(selected_road_ids)
            complex_local_support_roads = [
                road
                for road in local_roads
                if road.road_id not in selected_road_id_set
                and road.geometry is not None
                and not road.geometry.is_empty
                and float(road.geometry.distance(complex_support_seed_union))
                <= EVENT_COMPLEX_LOCAL_SUPPORT_ROAD_DISTANCE_M
            ]
    selected_rcsd_buffer = unary_union(
        [
            road.geometry.buffer(max(1.5, RC_ROAD_BUFFER_M), cap_style=2, join_style=2)
            for road in selected_rcsd_roads
        ]
    )
    selected_rcsdnode_ids = {
        node.node_id
        for node in local_rcsd_nodes
        if node.mainnodeid == mainnodeid_norm
        or (
            selected_rcsd_roads
            and not selected_rcsd_buffer.is_empty
            and selected_rcsd_buffer.intersects(node.geometry)
        )
    }
    if primary_main_rc_node is None:
        inferred_rcsdnode_seed = _infer_primary_main_rc_node_from_local_context(
            local_rcsd_nodes=local_rcsd_nodes,
            selected_rcsd_roads=selected_rcsd_roads,
            representative_node=representative_node,
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            local_roads=local_roads,
            kind_2=operational_kind_2,
        )
        if inferred_rcsdnode_seed["primary_main_rc_node"] is not None:
            primary_main_rc_node = inferred_rcsdnode_seed["primary_main_rc_node"]
            rcsdnode_seed_mode = inferred_rcsdnode_seed["seed_mode"]
    if primary_main_rc_node is not None:
        selected_rcsdnode_ids.add(primary_main_rc_node.node_id)
    if not selected_rcsdnode_ids:
        selected_rcsdnode_ids = {node.node_id for node in direct_target_rc_nodes}
    effective_target_rc_nodes: list[ParsedNode] = list(direct_target_rc_nodes)
    selected_rcsd_nodes = [node for node in local_rcsd_nodes if node.node_id in selected_rcsdnode_ids]
    if selected_rcsd_roads:
        _validate_drivezone_containment(
            drivezone_union=drivezone_union,
            features=selected_rcsd_roads,
            label="RCSDRoad",
        )
    if selected_rcsd_nodes:
        _validate_drivezone_containment(
            drivezone_union=drivezone_union,
            features=selected_rcsd_nodes,
            label="RCSDNode",
        )

    seed_support_geometries = [
        *[node.geometry.buffer(NODE_SEED_RADIUS_M) for node in group_nodes],
        *[node.geometry.buffer(RC_NODE_SEED_RADIUS_M) for node in exact_target_rc_nodes],
    ]
    if chain_context["sequential_ok"]:
        seed_support_geometries.extend(
            node.geometry.buffer(max(1.5, NODE_SEED_RADIUS_M * 0.6))
            for node in chain_context["related_seed_nodes"]
        )
    divstrip_constraint_geometry = divstrip_context_raw["constraint_geometry"]
    event_anchor_geometry = divstrip_context_raw["event_anchor_geometry"]
    localized_divstrip_reference_geometry = _localize_divstrip_reference_geometry(
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        selected_roads=selected_roads,
        event_anchor_geometry=event_anchor_geometry,
        representative_node=representative_node,
        drivezone_union=drivezone_union,
    )
    event_axis_branch = _resolve_event_axis_branch(
        road_branches=road_branches,
        main_branch_ids=main_branch_ids,
        kind_2=operational_kind_2,
        preferred_axis_branch_id=preferred_axis_branch_id,
    )
    event_axis_branch_id = None if event_axis_branch is None else event_axis_branch.branch_id
    if (
        primary_main_rc_node is None
        and not direct_target_rc_nodes
        and event_axis_branch_id is not None
        and event_axis_branch_id not in selected_branch_ids
    ):
        inferred_rcsdnode_seed = _infer_primary_main_rc_node_from_local_context(
            local_rcsd_nodes=local_rcsd_nodes,
            selected_rcsd_roads=selected_rcsd_roads,
            representative_node=representative_node,
            road_branches=road_branches,
            main_branch_ids=main_branch_ids,
            local_roads=local_roads,
            kind_2=operational_kind_2,
            preferred_trunk_branch_id=event_axis_branch_id,
        )
        if inferred_rcsdnode_seed["primary_main_rc_node"] is not None:
            primary_main_rc_node = inferred_rcsdnode_seed["primary_main_rc_node"]
            rcsdnode_seed_mode = inferred_rcsdnode_seed["seed_mode"]
            selected_rcsdnode_ids.add(primary_main_rc_node.node_id)
            effective_target_rc_nodes = [primary_main_rc_node]
            if primary_main_rc_node.node_id not in {node.node_id for node in selected_rcsd_nodes}:
                _validate_drivezone_containment(
                    drivezone_union=drivezone_union,
                    features=[primary_main_rc_node],
                    label="RCSDNode",
                )
                selected_rcsd_nodes = [
                    node for node in local_rcsd_nodes if node.node_id in selected_rcsdnode_ids
                ]
    road_lookup = {road.road_id: road for road in local_roads}
    event_axis_centerline = (
        None
        if event_axis_branch is None
        else _resolve_branch_centerline(
            branch=event_axis_branch,
            road_lookup=road_lookup,
            reference_point=event_anchor_geometry.centroid
            if event_anchor_geometry is not None and not event_anchor_geometry.is_empty
            else representative_node.geometry,
        )
    )
    provisional_event_origin = (
        representative_node.geometry
        if event_axis_centerline is None or event_axis_centerline.is_empty
        else nearest_points(event_axis_centerline, representative_node.geometry)[0]
    )
    initial_event_axis_unit_vector = _resolve_event_axis_unit_vector(
        axis_centerline=event_axis_centerline,
        origin_point=provisional_event_origin,
    )
    cross_section_boundary_branch_ids = (
        set(explicit_boundary_branch_ids)
        if explicit_boundary_branch_ids
        else (
            set(main_branch_ids)
            if (
                kind_resolution_raw["complex_junction"]
                or multibranch_context_raw["enabled"]
                or len(divstrip_context_raw["selected_component_ids"]) > 1
            )
            else set(selected_branch_ids)
        )
    )
    boundary_branch_a, boundary_branch_b = _pick_cross_section_boundary_branches(
        road_branches=road_branches,
        selected_branch_ids=cross_section_boundary_branch_ids,
        kind_2=operational_kind_2,
    )
    if (
        not explicit_boundary_branch_ids
        and (boundary_branch_a is None or boundary_branch_b is None)
        and cross_section_boundary_branch_ids != set(selected_branch_ids)
    ):
        boundary_branch_a, boundary_branch_b = _pick_cross_section_boundary_branches(
            road_branches=road_branches,
            selected_branch_ids=set(selected_branch_ids),
            kind_2=operational_kind_2,
        )
    branch_a_centerline = (
        None
        if boundary_branch_a is None
        else _resolve_branch_centerline(
            branch=boundary_branch_a,
            road_lookup=road_lookup,
            reference_point=provisional_event_origin,
        )
    )
    branch_b_centerline = (
        None
        if boundary_branch_b is None
        else _resolve_branch_centerline(
            branch=boundary_branch_b,
            road_lookup=road_lookup,
            reference_point=provisional_event_origin,
        )
    )
    if (
        not explicit_boundary_branch_ids
        and (kind_resolution_raw["complex_junction"] or multibranch_context_raw["enabled"])
        and len(multibranch_context_raw.get("main_pair_item_ids", [])) >= 2
    ):
        main_pair_item_ids = [str(item_id) for item_id in multibranch_context_raw["main_pair_item_ids"][:2]]
        main_pair_branch_a_centerline = _resolve_centerline_from_road_ids(
            road_ids=[main_pair_item_ids[0]],
            road_lookup=road_lookup,
            reference_point=provisional_event_origin,
        )
        main_pair_branch_b_centerline = _resolve_centerline_from_road_ids(
            road_ids=[main_pair_item_ids[1]],
            road_lookup=road_lookup,
            reference_point=provisional_event_origin,
        )
        if (
            main_pair_branch_a_centerline is not None
            and not main_pair_branch_a_centerline.is_empty
            and main_pair_branch_b_centerline is not None
            and not main_pair_branch_b_centerline.is_empty
        ):
            branch_a_centerline = main_pair_branch_a_centerline
            branch_b_centerline = main_pair_branch_b_centerline
    event_cross_half_len_m = _resolve_event_cross_half_len(
        origin_point=provisional_event_origin,
        axis_centerline=event_axis_centerline,
        axis_unit_vector=initial_event_axis_unit_vector,
        event_anchor_geometry=event_anchor_geometry,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
        selected_roads=selected_roads,
        selected_rcsd_roads=selected_rcsd_roads,
        patch_size_m=patch_size_m,
    )
    excluded_axis_s_values: list[float] = []
    if excluded_axis_positions and event_axis_branch_id is not None:
        target_axis_id = str(event_axis_branch_id)
        for prior_axis_id, prior_s in excluded_axis_positions:
            if str(prior_axis_id) == target_axis_id:
                excluded_axis_s_values.append(float(prior_s))
    event_reference_raw = _resolve_event_reference_point(
        representative_node=representative_node,
        event_anchor_geometry=event_anchor_geometry,
        divstrip_constraint_geometry=localized_divstrip_reference_geometry,
        all_divstrip_geometry=unary_union(
            [feature.geometry for feature in local_divstrip_features if feature.geometry is not None and not feature.geometry.is_empty]
        ) if local_divstrip_features else GeometryCollection(),
        axis_centerline=event_axis_centerline,
        axis_unit_vector=initial_event_axis_unit_vector,
        kind_2=operational_kind_2,
        drivezone_union=drivezone_union,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
        cross_half_len_m=event_cross_half_len_m,
        patch_size_m=patch_size_m,
        excluded_axis_s_values=excluded_axis_s_values or None,
    )
    branch_middle_gate_signal = str(event_reference_raw.get("branch_middle_gate_signal") or "").strip() or None
    branch_middle_gate_passed = bool(event_reference_raw.get("branch_middle_gate_passed", True))
    hard_rejection_signals: list[str] = []
    strict_branch_middle_enforcement = bool(
        explicit_event_branch_ids
        or explicit_boundary_branch_ids
        or preferred_axis_branch_id is not None
        or degraded_scope_reason is not None
        or excluded_component_geometries
        or excluded_axis_positions
    )
    if str(event_reference_raw.get("split_pick_source") or "").startswith("reverse_"):
        reverse_tip_attempted = True
        reverse_tip_used = True
        if reverse_trigger is None:
            reverse_trigger = (
                "forward_reference_outside_branch_middle"
                if branch_middle_gate_signal == "event_reference_outside_branch_middle"
                else "forward_reference_unstable"
            )
        position_source_reverse = str(event_reference_raw.get("position_source") or "reverse_tip_divstrip")
    elif branch_middle_gate_signal == "event_reference_outside_branch_middle":
        reverse_tip_attempted = True
        if reverse_trigger is None:
            reverse_trigger = "forward_reference_outside_branch_middle"
    if branch_middle_gate_signal is not None and not branch_middle_gate_passed:
        # Keep legacy T02 behavior unless the caller explicitly opts into
        # unit-local branch-middle enforcement via the new Step4 inputs.
        if (
            branch_middle_gate_signal != "event_reference_outside_branch_middle"
            or strict_branch_middle_enforcement
        ):
            hard_rejection_signals.append(branch_middle_gate_signal)
    position_source_final = (
        position_source_reverse
        if reverse_tip_used and position_source_reverse is not None
        else ("multibranch_event" if multibranch_context_raw["enabled"] else position_source_forward)
    )
    event_origin_point = event_reference_raw["origin_point"]
    event_origin_source = event_reference_raw["event_origin_source"]
    event_axis_unit_vector = _resolve_event_axis_unit_vector(
        axis_centerline=event_axis_centerline,
        origin_point=event_origin_point,
    ) or initial_event_axis_unit_vector
    event_recenter = _rebalance_event_origin_for_rcsd_targets(
        origin_point=event_origin_point,
        axis_unit_vector=event_axis_unit_vector,
        target_rc_nodes=effective_target_rc_nodes,
    )
    if event_recenter[1]["applied"]:
        event_origin_point = event_recenter[0]
        event_origin_source = f"{event_origin_source}_recenter_{event_recenter[1]['direction']}"
        event_axis_unit_vector = _resolve_event_axis_unit_vector(
            axis_centerline=event_axis_centerline,
            origin_point=event_origin_point,
        ) or event_axis_unit_vector
    event_cross_half_len_m = _resolve_event_cross_half_len(
        origin_point=event_origin_point,
        axis_centerline=event_axis_centerline,
        axis_unit_vector=event_axis_unit_vector,
        event_anchor_geometry=event_anchor_geometry,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
        selected_roads=selected_roads,
        selected_rcsd_roads=selected_rcsd_roads,
        patch_size_m=patch_size_m,
    )

    fallback_mode: str | None = None
    if not divstrip_context_raw["nearby"]:
        fallback_mode = "weak_evidence_no_nearby_divstrip"
    elif divstrip_context_raw["selection_mode"] == "roads_fallback":
        fallback_mode = "roads_fallback"
    elif isinstance(position_source_final, str) and "fallback" in position_source_final:
        fallback_mode = position_source_final
    evidence_primary_source = (
        "reverse_tip_retry"
        if reverse_tip_used
        else (
            "multibranch_event"
            if multibranch_context_raw["enabled"]
            else ("divstrip_direct" if divstrip_context_raw["nearby"] else "conservative_fallback")
        )
    )
    review_signals = _build_stage4_interpretation_review_signals(
        divstrip_context=divstrip_context_raw,
        multibranch_context=multibranch_context_raw,
        kind_resolution=kind_resolution_raw,
        chain_context=chain_context,
    )
    if (
        branch_middle_gate_signal is not None
        and (
            branch_middle_gate_signal != "event_reference_outside_branch_middle"
            or strict_branch_middle_enforcement
        )
    ):
        review_signals = tuple([*review_signals, branch_middle_gate_signal])
    if degraded_scope_reason:
        review_signals = tuple([*review_signals, f"degraded_scope:{degraded_scope_reason}"])
    risk_signals = _build_stage4_interpretation_risk_signals(
        review_signals=review_signals,
        reverse_tip_used=reverse_tip_used,
        fallback_mode=fallback_mode,
    )
    divstrip_context = wrap_stage4_divstrip_context(divstrip_context_raw)
    multibranch_decision = wrap_stage4_multibranch_decision(multibranch_context_raw)
    kind_resolution = wrap_stage4_kind_resolution(kind_resolution_raw)
    continuous_chain_decision = resolve_stage4_continuous_chain_decision(
        chain_context=chain_context,
        kind_resolution=kind_resolution,
        review_signal=(
            STATUS_CONTINUOUS_CHAIN_REVIEW
            if STATUS_CONTINUOUS_CHAIN_REVIEW in review_signals
            else None
        ),
    )
    reverse_tip_decision = Stage4ReverseTipDecision(
        attempted=reverse_tip_attempted,
        used=reverse_tip_used,
        trigger=reverse_trigger,
        position_source_forward=position_source_forward,
        position_source_reverse=position_source_reverse,
        position_source_final=position_source_final,
        raw={
            "reverse_side_branch_ids": [branch.branch_id for branch in reverse_side_branches],
            "selected_side_branch_ids": [branch.branch_id for branch in selected_side_branches],
        },
    )
    event_reference = Stage4EventReference(
        event_axis_branch_id=event_axis_branch_id,
        event_origin_source=event_origin_source,
        event_position_source=str(event_reference_raw["position_source"]),
        event_split_pick_source=str(event_reference_raw["split_pick_source"]),
        event_chosen_s_m=event_reference_raw["chosen_s_m"],
        event_tip_s_m=event_reference_raw["tip_s_m"],
        event_first_divstrip_hit_s_m=event_reference_raw["first_divstrip_hit_dist_m"],
        event_drivezone_split_s_m=event_reference_raw["s_drivezone_split_m"],
        divstrip_ref_source=event_reference_raw.get("divstrip_ref_source"),
        divstrip_ref_offset_m=event_reference_raw.get("divstrip_ref_offset_m"),
        event_recenter_applied=bool(event_recenter[1]["applied"]),
        event_recenter_shift_m=event_recenter[1]["shift_m"],
        event_recenter_direction=event_recenter[1]["direction"],
        raw=dict(event_reference_raw),
    )
    evidence_decision = Stage4EvidenceDecision(
        primary_source=evidence_primary_source,
        selection_mode=position_source_final or divstrip_context.selection_mode,
        fallback_used=fallback_mode is not None,
        fallback_mode=fallback_mode,
        risk_signals=tuple(
            signal
            for signal in risk_signals
            if signal in {"reverse_tip_used", "fallback_to_weak_evidence"}
        ),
    )
    legacy_step5_bridge = Stage4LegacyStep5Bridge(
        divstrip_context=divstrip_context,
        multibranch_decision=multibranch_decision,
        kind_resolution=kind_resolution,
        selected_side_branches=tuple(selected_side_branches),
        selected_branch_ids=tuple(selected_branch_ids),
        selected_event_branch_ids=tuple(str(item) for item in selected_event_branch_ids),
        selected_road_ids=tuple(selected_road_ids),
        selected_event_road_ids=tuple(sorted(str(item) for item in selected_event_road_ids)),
        selected_rcsdroad_ids=tuple(sorted(str(item) for item in selected_rcsdroad_ids)),
        selected_rcsdnode_ids=tuple(sorted(str(item) for item in selected_rcsdnode_ids)),
        rcsdroad_selection_mode=rcsdroad_selection_mode,
        rcsdnode_seed_mode=rcsdnode_seed_mode,
        primary_main_rc_node=primary_main_rc_node,
        selected_roads=tuple(selected_roads),
        selected_event_roads=tuple(selected_event_roads),
        selected_rcsd_roads=tuple(selected_rcsd_roads),
        selected_rcsd_nodes=tuple(selected_rcsd_nodes),
        effective_target_rc_nodes=tuple(effective_target_rc_nodes),
        complex_local_support_roads=tuple(complex_local_support_roads),
        seed_support_geometries=tuple(seed_support_geometries),
        divstrip_constraint_geometry=divstrip_constraint_geometry,
        event_anchor_geometry=event_anchor_geometry,
        localized_divstrip_reference_geometry=localized_divstrip_reference_geometry,
        event_axis_branch=event_axis_branch,
        event_axis_branch_id=event_axis_branch_id,
        event_axis_centerline=event_axis_centerline,
        provisional_event_origin=provisional_event_origin,
        initial_event_axis_unit_vector=initial_event_axis_unit_vector,
        boundary_branch_a=boundary_branch_a,
        boundary_branch_b=boundary_branch_b,
        branch_a_centerline=branch_a_centerline,
        branch_b_centerline=branch_b_centerline,
        event_cross_half_len_m=event_cross_half_len_m,
        event_reference_raw=dict(event_reference_raw),
        event_origin_point=event_origin_point,
        event_origin_source=event_origin_source,
        event_axis_unit_vector=event_axis_unit_vector,
        event_recenter_applied=bool(event_recenter[1]["applied"]),
        event_recenter_shift_m=event_recenter[1]["shift_m"],
        event_recenter_direction=event_recenter[1]["direction"],
    )
    legacy_step5_readiness = _evaluate_stage4_legacy_step5_readiness(
        selected_branch_ids=selected_branch_ids,
        event_reference=event_reference_raw,
    )
    return Stage4EventInterpretationResult(
        representative_mainnodeid=normalize_id(representative_node.mainnodeid or representative_node.node_id),
        representative_node_id=representative_node.node_id,
        evidence_decision=evidence_decision,
        divstrip_context=divstrip_context,
        continuous_chain_decision=continuous_chain_decision,
        multibranch_decision=multibranch_decision,
        kind_resolution=kind_resolution,
        reverse_tip_decision=reverse_tip_decision,
        event_reference=event_reference,
        review_signals=review_signals,
        hard_rejection_signals=tuple(dict.fromkeys(hard_rejection_signals)),
        risk_signals=risk_signals,
        legacy_step5_bridge=legacy_step5_bridge,
        legacy_step5_readiness=legacy_step5_readiness,
    )
