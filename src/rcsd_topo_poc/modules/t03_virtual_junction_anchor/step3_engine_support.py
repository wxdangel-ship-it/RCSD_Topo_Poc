from __future__ import annotations

import heapq

import math

from dataclasses import dataclass, field

from hashlib import sha1

from collections import defaultdict, deque

from time import perf_counter

from typing import Any, Iterable

from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
)

from shapely.geometry.base import BaseGeometry

from shapely.ops import substring, unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import (
    RoadRecord,
    Step1Context,
    Step2TemplateResult,
    Step3CaseResult,
    Step3NegativeMasks,
)

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.id_utils import normalize_id

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.line_geometry import (
    endpoint_point,
    multipart_road_handling_fields,
    nearest_line,
    substring_from_endpoint,
)

ROAD_BUFFER_M = 8.0

NODE_BUFFER_M = 5.0

NEGATIVE_MASK_BUFFER_M = 1.0

STEP3_DISTANCE_CAP_M = 50.0

TARGET_NODE_COVER_TOLERANCE_M = 0.5

TARGET_NODE_INCIDENT_ROAD_COVER_TOLERANCE_M = 10.0

TARGET_COMPONENT_TOUCH_BUFFER_M = 1.0

SINGLE_SIDED_TARGET_DRIVEZONE_EDGE_TOUCH_M = 1.5

INTRUSION_AREA_TOLERANCE_M2 = 0.05

DRIVEZONE_OUTSIDE_AREA_TOLERANCE_M2 = 0.05

ADJACENT_REVERSE_MASK_LENGTH_M = 1.0

OPPOSITE_RC_ROAD_MAX_SWSD_GAP_M = 10.0

OPPOSITE_RC_ROAD_MAX_REFERENCE_DISTANCE_M = 35.0

OPPOSITE_RC_ROAD_MIN_DIRECTION_SIM = 0.85

OPPOSITE_RC_ROAD_MIN_REVERSE_DIRECTION_DOT = 0.85

OPPOSITE_RC_NODE_MAX_CORRIDOR_DISTANCE_M = 10.0

OPPOSITE_RC_ROAD_MAX_PROTECTED_OVERLAP_M = 3.0

RCSD_SEMANTIC_BRIDGE_MAX_TARGET_DISTANCE_M = 6.0

DIRECTION_MODE = "t02_direction_plus_bidirectional_junction_trace"

from .step3_engine_models import (
    _ReachableRoadPreparedRecord,
    _ReachableRoadPreparedSupport,
    _ReachableRoadSupportCaseCache,
)

from .step3_engine_primitives import (
    _axis_similarity,
    _build_branch_frontier,
    _build_node_to_roads,
    _clean_geometry,
    _clip_line_to_hard_bounds,
    _clip_road_to_cap,
    _detect_shared_two_in_two_out_node,
    _directed_edge_pairs_from_t02_semantics,
    _extract_line_geometry,
    _extract_polygon_geometry,
    _geometry_axis_vector,
    _geometry_cache_token,
    _iter_geometries,
    _largest_line_string,
    _line_midpoint,
    _node_flow_counts,
    _node_group_lookup,
    _normalized_axis_vector,
    _other_endpoint,
    _point_along_road_from_reference,
    _point_like,
    _rcsd_opposite_fallback_fields,
    _road_flow_flags_for_group_like_t02,
    _road_pair_distance_trend_from_reference,
    _road_vector_from_reference,
    _rule_a_target_core_protection_fields,
    _rule_d_fallback_fields,
    _shared_two_in_two_out_closeout_fields,
    _single_sided_direction_resolution_fields,
    _sorted_string_key,
    _two_node_t_bridge_closeout_defaults,
    _vector_dot,
)

def _reverse_mask_strip_in_drivezone(
    road: RoadRecord,
    endpoint: str,
    drivezone_geometry: BaseGeometry,
) -> BaseGeometry | None:
    clipped_line = _largest_line_string(_extract_line_geometry(road.geometry.intersection(drivezone_geometry)))
    if clipped_line is None:
        return None
    original_endpoint = endpoint_point(road.geometry, endpoint)
    if original_endpoint is None:
        return None
    clipped_start = Point(clipped_line.coords[0])
    clipped_end = Point(clipped_line.coords[-1])
    clipped_endpoint = "start" if clipped_start.distance(original_endpoint) <= clipped_end.distance(original_endpoint) else "end"
    reverse_length = min(ADJACENT_REVERSE_MASK_LENGTH_M, clipped_line.length)
    if reverse_length <= 1e-6:
        return None
    if clipped_endpoint == "start":
        reverse_segment = substring(clipped_line, 0.0, reverse_length)
    else:
        reverse_segment = substring(clipped_line, max(0.0, clipped_line.length - reverse_length), clipped_line.length)
    reverse_line = _extract_line_geometry(reverse_segment)
    if reverse_line is None:
        return None
    reverse_mask = _clean_geometry(
        reverse_line.buffer(NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2).intersection(drivezone_geometry)
    )
    if reverse_mask is None:
        return None
    return reverse_mask

def _build_adjacent_junction_masks(
    context: Step1Context,
    *,
    adjacent_records: list[dict[str, Any]],
    additional_protection_geometry: BaseGeometry | None = None,
) -> tuple[BaseGeometry | None, list[dict[str, Any]], list[dict[str, Any]], set[str]]:
    geometries: list[BaseGeometry] = []
    road_lookup = {road.road_id: road for road in context.roads}
    target_protection = _clean_geometry(
        unary_union([node.geometry.buffer(NODE_BUFFER_M) for node in context.target_group.nodes])
    )
    if target_protection is not None and additional_protection_geometry is not None:
        target_protection = _extract_polygon_geometry(unary_union([target_protection, additional_protection_geometry]))
    elif target_protection is None:
        target_protection = additional_protection_geometry
    road_ids: set[str] = set()
    filtered_records: list[dict[str, Any]] = []
    suppressed_records: list[dict[str, Any]] = []
    for record in adjacent_records:
        road = road_lookup.get(record["road_id"])
        if road is None:
            continue
        strip = _reverse_mask_strip_in_drivezone(
            road,
            record["endpoint"],
            context.drivezone_geometry,
        )
        if strip is None:
            continue
        if target_protection is not None:
            overlap = strip.intersection(target_protection)
            overlap_area = 0.0 if overlap.is_empty else float(getattr(overlap, "area", 0.0))
            if overlap_area > INTRUSION_AREA_TOLERANCE_M2:
                suppressed_records.append(
                    {
                        **record,
                        "suppress_reason": "overlaps_target_core_or_bridge",
                        "overlap_area_m2": round(overlap_area, 6),
                    }
                )
                continue
            strip = _clean_geometry(strip.difference(target_protection))
            if strip is None:
                suppressed_records.append(
                    {
                        **record,
                        "suppress_reason": "emptied_by_target_core_or_bridge_protection",
                        "overlap_area_m2": round(overlap_area, 6),
                    }
                )
                continue
        geometries.append(strip)
        road_ids.add(road.road_id)
        filtered_records.append(record)
    return _clean_geometry(unary_union(geometries)) if geometries else None, filtered_records, suppressed_records, road_ids

def _build_two_node_t_bridge_support(
    context: Step1Context,
    *,
    blocker_geometry: BaseGeometry | None,
) -> tuple[BaseGeometry | None, dict[str, Any]]:
    target_nodes = tuple(sorted(context.target_group.nodes, key=lambda item: item.node_id))
    if len(target_nodes) != 2:
        return None, {
            "two_node_t_bridge_applied": False,
            "two_node_t_bridge_length_m": 0.0,
            "two_node_t_bridge_inside_drivezone_length_m": 0.0,
            "two_node_t_bridge_clipped_to_drivezone": False,
            "two_node_t_bridge_blocked": False,
            "two_node_t_bridge_reason": "target_group_is_not_two_node",
        }

    start_point = _point_like(target_nodes[0].geometry)
    end_point = _point_like(target_nodes[1].geometry)
    raw_line = LineString([start_point, end_point])
    bridge_length_m = float(raw_line.length)
    if bridge_length_m <= 1e-6:
        return None, {
            "two_node_t_bridge_applied": False,
            "two_node_t_bridge_length_m": 0.0,
            "two_node_t_bridge_inside_drivezone_length_m": 0.0,
            "two_node_t_bridge_clipped_to_drivezone": False,
            "two_node_t_bridge_blocked": False,
            "two_node_t_bridge_reason": "degenerate_target_nodes",
        }

    inside_drivezone_line = _extract_line_geometry(raw_line.intersection(context.drivezone_geometry))
    inside_drivezone_length_m = 0.0 if inside_drivezone_line is None else float(inside_drivezone_line.length)
    if inside_drivezone_line is None:
        return None, {
            "two_node_t_bridge_applied": False,
            "two_node_t_bridge_length_m": round(bridge_length_m, 6),
            "two_node_t_bridge_inside_drivezone_length_m": 0.0,
            "two_node_t_bridge_clipped_to_drivezone": True,
            "two_node_t_bridge_blocked": True,
            "two_node_t_bridge_reason": "bridge_outside_drivezone",
        }

    hard_bound_line = _clip_line_to_hard_bounds(
        inside_drivezone_line,
        drivezone_geometry=context.drivezone_geometry,
        blocker_geometry=blocker_geometry,
    )
    if hard_bound_line is None:
        return None, {
            "two_node_t_bridge_applied": False,
            "two_node_t_bridge_length_m": round(bridge_length_m, 6),
            "two_node_t_bridge_inside_drivezone_length_m": round(inside_drivezone_length_m, 6),
            "two_node_t_bridge_clipped_to_drivezone": abs(inside_drivezone_length_m - bridge_length_m) > 1e-6,
            "two_node_t_bridge_blocked": True,
            "two_node_t_bridge_reason": "bridge_blocked_by_hard_bounds",
        }

    bridge_support = _extract_polygon_geometry(
        hard_bound_line.buffer(ROAD_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
    )
    if blocker_geometry is not None and bridge_support is not None:
        bridge_support = _extract_polygon_geometry(bridge_support.difference(blocker_geometry))
    if bridge_support is None:
        return None, {
            "two_node_t_bridge_applied": False,
            "two_node_t_bridge_length_m": round(bridge_length_m, 6),
            "two_node_t_bridge_inside_drivezone_length_m": round(inside_drivezone_length_m, 6),
            "two_node_t_bridge_clipped_to_drivezone": abs(inside_drivezone_length_m - bridge_length_m) > 1e-6,
            "two_node_t_bridge_blocked": True,
            "two_node_t_bridge_reason": "bridge_buffer_clipped_to_empty",
        }

    return bridge_support, {
        "two_node_t_bridge_applied": True,
        "two_node_t_bridge_length_m": round(bridge_length_m, 6),
        "two_node_t_bridge_inside_drivezone_length_m": round(inside_drivezone_length_m, 6),
        "two_node_t_bridge_clipped_to_drivezone": abs(inside_drivezone_length_m - bridge_length_m) > 1e-6,
        "two_node_t_bridge_blocked": False,
        "two_node_t_bridge_reason": "bridge_applied",
    }

def _build_mst_edges(points: list[Point]) -> list[LineString]:
    if len(points) < 2:
        return []
    visited = {0}
    remaining = set(range(1, len(points)))
    edges: list[LineString] = []
    while remaining:
        best_pair: tuple[int, int] | None = None
        best_distance = math.inf
        for source_index in visited:
            for target_index in remaining:
                distance = points[source_index].distance(points[target_index])
                if distance < best_distance:
                    best_distance = distance
                    best_pair = (source_index, target_index)
        if best_pair is None:
            break
        source_index, target_index = best_pair
        edges.append(LineString([points[source_index], points[target_index]]))
        visited.add(target_index)
        remaining.remove(target_index)
    return edges

def _build_rcsd_semantic_bridge_support(
    context: Step1Context,
    *,
    blocker_geometry: BaseGeometry | None,
) -> tuple[BaseGeometry | None, list[dict[str, Any]]]:
    target_geometry = unary_union([_point_like(node.geometry) for node in context.target_group.nodes])
    groups: dict[str, list[Point]] = defaultdict(list)
    node_ids_by_group: dict[str, list[str]] = defaultdict(list)
    for node in context.rcsd_nodes:
        if node.mainnodeid in {None, "", "0"}:
            continue
        groups[str(node.mainnodeid)].append(_point_like(node.geometry))
        node_ids_by_group[str(node.mainnodeid)].append(node.node_id)

    geometries: list[BaseGeometry] = []
    records: list[dict[str, Any]] = []
    for group_id, points in groups.items():
        if len(points) < 2:
            continue
        node_ids = node_ids_by_group[group_id]
        for index, left in enumerate(points):
            for right_index in range(index + 1, len(points)):
                right = points[right_index]
                if left.distance(right) <= 1e-6:
                    continue
                line = LineString([left, right])
                distance_to_target = float(line.distance(target_geometry))
                if distance_to_target > RCSD_SEMANTIC_BRIDGE_MAX_TARGET_DISTANCE_M:
                    continue
                support = _extract_polygon_geometry(
                    line.buffer(NODE_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
                )
                if support is None:
                    continue
                if blocker_geometry is not None:
                    support = _extract_polygon_geometry(support.difference(blocker_geometry))
                    if support is None:
                        continue
                geometries.append(support)
                records.append(
                    {
                        "group_id": group_id,
                        "from_node_id": node_ids[index],
                        "to_node_id": node_ids[right_index],
                        "distance_to_target_m": round(distance_to_target, 6),
                        "line_length_m": round(line.length, 6),
                        "buffer_m": NODE_BUFFER_M,
                    }
                )
    return _extract_polygon_geometry(unary_union(geometries)) if geometries else None, records

def _build_foreign_mst_masks(context: Step1Context) -> tuple[BaseGeometry | None, list[dict[str, Any]]]:
    geometries: list[BaseGeometry] = []
    records: list[dict[str, Any]] = []
    for group in context.foreign_groups:
        if len(group.nodes) < 2:
            continue
        points = [_point_like(node.geometry) for node in group.nodes]
        mst_edges = _build_mst_edges(points)
        if not mst_edges:
            continue
        clipped = _extract_line_geometry(unary_union(mst_edges).intersection(context.drivezone_geometry))
        if clipped is None:
            continue
        mask = _clean_geometry(clipped.buffer(NEGATIVE_MASK_BUFFER_M))
        if mask is None:
            continue
        geometries.append(mask)
        records.append({"group_id": group.group_id, "node_count": len(group.nodes), "rule": "C"})
    return _clean_geometry(unary_union(geometries)) if geometries else None, records

def _build_candidate_roads_for_single_sided(
    context: Step1Context,
    *,
    protected_road_ids: set[str],
) -> tuple[set[str], set[str], bool, tuple[float, float] | None, dict[str, Any]]:
    def _partition_by_direction(direction: tuple[float, float]) -> tuple[set[str], set[str]]:
        vx, vy = direction
        allowed: set[str] = set()
        excluded: set[str] = set()
        for road in context.roads:
            if road.road_id in protected_road_ids:
                allowed.add(road.road_id)
                continue
            midpoint = _line_midpoint(road.geometry)
            dot = (midpoint.x - reference.x) * vx + (midpoint.y - reference.y) * vy
            if dot >= -2.0:
                allowed.add(road.road_id)
            else:
                excluded.add(road.road_id)
        return allowed, excluded

    def _detect_semantic_horizontal_pair(
        roads: list[RoadRecord],
        member_node_ids: set[str],
    ) -> dict[str, Any] | None:
        direct_target_roads = [road for road in roads if road.road_id in context.target_road_ids]
        candidate_pairs: list[dict[str, Any]] = []
        for incoming_road in direct_target_roads:
            incoming_support, outgoing_support = _road_flow_flags_for_group_like_t02(incoming_road, member_node_ids)
            if not incoming_support or outgoing_support:
                continue
            incoming_vector = _road_vector_from_reference(incoming_road, reference)
            for outgoing_road in direct_target_roads:
                if outgoing_road.road_id == incoming_road.road_id:
                    continue
                incoming_support_out, outgoing_support_out = _road_flow_flags_for_group_like_t02(
                    outgoing_road,
                    member_node_ids,
                )
                if incoming_support_out or not outgoing_support_out:
                    continue
                outgoing_vector = _road_vector_from_reference(outgoing_road, reference)
                if _axis_similarity(incoming_vector, outgoing_vector) < 0.95:
                    continue
                divergence = _road_pair_distance_trend_from_reference(incoming_road, outgoing_road, reference)
                if divergence is None or divergence <= 1.0:
                    continue
                candidate_pairs.append(
                    {
                        "horizontal_pair_road_ids": [incoming_road.road_id, outgoing_road.road_id],
                        "horizontal_pair_divergence_m": round(float(divergence), 6),
                        "direction": outgoing_vector,
                    }
                )
        if not candidate_pairs:
            return None
        candidate_pairs.sort(
            key=lambda item: (
                -item["horizontal_pair_divergence_m"],
                item["horizontal_pair_road_ids"],
            )
        )
        best_pair = candidate_pairs[0]
        return {
            "horizontal_pair_detected": True,
            "horizontal_pair_road_ids": best_pair["horizontal_pair_road_ids"],
            "horizontal_pair_divergence_m": best_pair["horizontal_pair_divergence_m"],
            "resolution_mode": "semantic_horizontal_pair",
            "direction": best_pair["direction"],
        }

    reference = _point_like(context.representative_node.geometry)
    candidate_roads = [
        road
        for road in context.roads
        if road.road_id in context.target_road_ids or road.geometry.distance(reference) <= 18.0
    ]
    if not candidate_roads:
        return (
            set(),
            {road.road_id for road in context.roads},
            True,
            None,
            {
                "horizontal_pair_detected": False,
                "horizontal_pair_road_ids": [],
                "horizontal_pair_divergence_m": None,
                "resolution_mode": "no_candidate_roads",
            },
        )
    member_node_ids = {node.node_id for node in context.target_group.nodes}
    semantic_horizontal_pair = _detect_semantic_horizontal_pair(candidate_roads, member_node_ids)
    if semantic_horizontal_pair is not None:
        allowed, excluded = _partition_by_direction(semantic_horizontal_pair["direction"])
        return (
            allowed,
            excluded,
            False,
            semantic_horizontal_pair["direction"],
            semantic_horizontal_pair,
        )
    candidate_vectors = [
        (_road_vector_from_reference(road, reference), road)
        for road in candidate_roads
    ]
    scored: list[dict[str, Any]] = []
    for (vx, vy), seed_road in candidate_vectors:
        axis_vector = _normalized_axis_vector((vx, vy))
        allowed, excluded = _partition_by_direction((vx, vy))
        score = float(len(allowed) * 10 - len(excluded))
        for road in context.roads:
            if road.road_id in allowed:
                midpoint = _line_midpoint(road.geometry)
                score += math.hypot(midpoint.x - reference.x, midpoint.y - reference.y) * 0.01

        axis_aligned_roads = [
            road
            for road in candidate_roads
            if _axis_similarity(_road_vector_from_reference(road, reference), axis_vector) >= 0.95
        ]
        incoming_axis_roads = [
            road for road in axis_aligned_roads if _road_flow_flags_for_group_like_t02(road, member_node_ids)[0]
        ]
        outgoing_axis_roads = [
            road for road in axis_aligned_roads if _road_flow_flags_for_group_like_t02(road, member_node_ids)[1]
        ]
        horizontal_pair_detected = any(
            incoming.road_id != outgoing.road_id
            for incoming in incoming_axis_roads
            for outgoing in outgoing_axis_roads
        )
        best_divergence = None
        for incoming in incoming_axis_roads:
            for outgoing in outgoing_axis_roads:
                if incoming.road_id == outgoing.road_id:
                    continue
                trend = _road_pair_distance_trend_from_reference(incoming, outgoing, reference)
                if trend is None:
                    continue
                best_divergence = trend if best_divergence is None else max(best_divergence, trend)
        if horizontal_pair_detected:
            score += 12.0
        if best_divergence is not None:
            score += max(-5.0, min(12.0, best_divergence * 0.5))

        scored.append(
            {
                "score": score,
                "allowed": allowed,
                "excluded": excluded,
                "direction": (vx, vy),
                "seed_road_id": seed_road.road_id,
                "axis_vector": axis_vector,
                "horizontal_pair_detected": horizontal_pair_detected,
                "best_divergence": best_divergence,
            }
        )
    scored.sort(key=lambda item: item["score"], reverse=True)
    top = scored[0]
    top_score = top["score"]
    ambiguous = False
    if len(scored) > 1:
        second = scored[1]
        close_in_score = abs(top_score - second["score"]) <= max(3.0, abs(top_score) * 0.15)
        same_partition = (
            top["allowed"] == second["allowed"]
            and top["excluded"] == second["excluded"]
        )
        same_axis = _axis_similarity(top["axis_vector"], second["axis_vector"]) >= 0.97
        semantically_equivalent = same_partition or (
            same_axis
            and top["horizontal_pair_detected"]
            and second["horizontal_pair_detected"]
        )
        ambiguous = close_in_score and not semantically_equivalent
    return (
        top["allowed"],
        top["excluded"],
        ambiguous,
        top["direction"],
        {
            "horizontal_pair_detected": False,
            "horizontal_pair_road_ids": [],
            "horizontal_pair_divergence_m": None,
            "resolution_mode": "score_fallback",
        },
    )
def _split_point_side(reference: Point, point: Point, direction: tuple[float, float]) -> float:
    vx, vy = direction
    return (point.x - reference.x) * vx + (point.y - reference.y) * vy

def _build_single_sided_exclusions(
    context: Step1Context,
    direction: tuple[float, float] | None,
    *,
    protected_node_ids: set[str],
) -> tuple[set[str], set[str]]:
    if direction is None:
        return set(), set()
    reference = _point_like(context.representative_node.geometry)
    target_group_id = context.target_group.group_id
    excluded_rc_road_ids: set[str] = set()
    excluded_rc_node_ids: set[str] = set()
    for road in context.rcsd_roads:
        midpoint = _line_midpoint(road.geometry)
        if _split_point_side(reference, midpoint, direction) < -2.0:
            excluded_rc_road_ids.add(road.road_id)
    for node in context.rcsd_nodes:
        if node.mainnodeid == target_group_id or node.node_id == context.representative_node.node_id:
            continue
        if node.node_id in protected_node_ids:
            continue
        point = _point_like(node.geometry)
        if _split_point_side(reference, point, direction) < -2.0:
            excluded_rc_node_ids.add(node.node_id)
    return excluded_rc_road_ids, excluded_rc_node_ids

def _filter_opposite_rc_road_ids(
    context: Step1Context,
    *,
    excluded_opposite_road_ids: set[str],
    candidate_rc_road_ids: set[str],
    protected_road_ids: set[str],
    forward_direction: tuple[float, float] | None,
    horizontal_pair_detected: bool,
) -> tuple[set[str], dict[str, Any]]:
    candidate_ids = sorted(candidate_rc_road_ids)
    if not candidate_rc_road_ids:
        return set(), {
            "enabled": False,
            "reason": "no_candidate_rcsd_opposite",
            "candidate_ids": [],
            "selected_ids": [],
            "suppressed_ids": [],
        }
    if not horizontal_pair_detected or forward_direction is None:
        return set(), {
            "enabled": False,
            "reason": "disabled_no_semantic_horizontal_pair",
            "candidate_ids": candidate_ids,
            "selected_ids": [],
            "suppressed_ids": candidate_ids,
        }
    if excluded_opposite_road_ids:
        return set(), {
            "enabled": False,
            "reason": "disabled_swsd_opposite_present",
            "candidate_ids": candidate_ids,
            "selected_ids": [],
            "suppressed_ids": candidate_ids,
        }
    reference = _point_like(context.representative_node.geometry)
    protected_roads = [road for road in context.roads if road.road_id in protected_road_ids]
    kept: set[str] = set()
    suppressed: set[str] = set()
    for rc_road in context.rcsd_roads:
        if rc_road.road_id not in candidate_rc_road_ids:
            continue
        if reference.distance(rc_road.geometry) > OPPOSITE_RC_ROAD_MAX_REFERENCE_DISTANCE_M:
            suppressed.add(rc_road.road_id)
            continue
        reverse_dot = -_vector_dot(_road_vector_from_reference(rc_road, reference), forward_direction)
        if reverse_dot < OPPOSITE_RC_ROAD_MIN_REVERSE_DIRECTION_DOT:
            suppressed.add(rc_road.road_id)
            continue
        blocker_mask = _clean_geometry(
            rc_road.geometry.buffer(NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
        )
        if blocker_mask is None:
            suppressed.add(rc_road.road_id)
            continue
        max_protected_overlap = 0.0
        for protected_road in protected_roads:
            overlap = protected_road.geometry.intersection(blocker_mask)
            max_protected_overlap = max(max_protected_overlap, float(getattr(overlap, "length", 0.0)))
        # RCSD corridor fallback only补SWSD opposite缺口; even in fallback mode it must not
        # materialize as a hard blocker when it rides on the current protected branch geometry.
        if max_protected_overlap > OPPOSITE_RC_ROAD_MAX_PROTECTED_OVERLAP_M:
            suppressed.add(rc_road.road_id)
            continue
        kept.add(rc_road.road_id)
    return kept, {
        "enabled": bool(kept),
        "reason": "enabled_missing_swsd_opposite" if kept else "disabled_no_reverse_rcsd_candidate",
        "candidate_ids": candidate_ids,
        "selected_ids": sorted(kept),
        "suppressed_ids": sorted(set(candidate_ids) - kept),
    }

def _filter_opposite_rc_node_ids(
    context: Step1Context,
    *,
    excluded_opposite_road_ids: set[str],
    filtered_rc_road_ids: set[str],
    candidate_rc_node_ids: set[str],
) -> set[str]:
    if not candidate_rc_node_ids:
        return set()
    corridor_geometries: list[BaseGeometry] = [
        road.geometry for road in context.roads if road.road_id in excluded_opposite_road_ids
    ]
    corridor_geometries.extend(
        road.geometry for road in context.rcsd_roads if road.road_id in filtered_rc_road_ids
    )
    if not corridor_geometries:
        return set()
    reference = _point_like(context.representative_node.geometry)
    corridor_union = unary_union(corridor_geometries)
    kept: set[str] = set()
    for node in context.rcsd_nodes:
        if node.node_id not in candidate_rc_node_ids:
            continue
        if reference.distance(node.geometry) > OPPOSITE_RC_ROAD_MAX_REFERENCE_DISTANCE_M:
            continue
        if node.geometry.distance(corridor_union) <= OPPOSITE_RC_NODE_MAX_CORRIDOR_DISTANCE_M:
            kept.add(node.node_id)
    return kept

def _build_single_sided_blockers(
    context: Step1Context,
    *,
    excluded_opposite_road_ids: set[str],
    excluded_opposite_rc_road_ids: set[str],
    excluded_opposite_rc_node_ids: set[str],
) -> tuple[BaseGeometry | None, list[dict[str, Any]], list[dict[str, Any]]]:
    geometries: list[BaseGeometry] = []
    records: list[dict[str, Any]] = []
    blocked_directions: list[dict[str, Any]] = []
    for road in context.roads:
        if road.road_id not in excluded_opposite_road_ids:
            continue
        local_mask = _clean_geometry(
            road.geometry.buffer(NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
        )
        if local_mask is None:
            continue
        geometries.append(local_mask)
        records.append({"road_id": road.road_id, "rule": "E", "mode": "opposite_road_buffer"})
        blocked_directions.append({"layer": "road", "object_id": road.road_id, "reason": "single_sided_opposite_road"})
    for road in context.rcsd_roads:
        if road.road_id not in excluded_opposite_rc_road_ids:
            continue
        local_mask = _clean_geometry(
            road.geometry.buffer(NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
        )
        if local_mask is None:
            continue
        geometries.append(local_mask)
        records.append({"road_id": road.road_id, "rule": "E", "mode": "opposite_corridor_buffer"})
        blocked_directions.append({"layer": "rcsdroad", "object_id": road.road_id, "reason": "single_sided_opposite_corridor"})
    for group in context.foreign_groups:
        for node in group.nodes:
            if node.node_id not in excluded_opposite_rc_node_ids:
                continue
            mask = _clean_geometry(_point_like(node.geometry).buffer(NEGATIVE_MASK_BUFFER_M).intersection(context.drivezone_geometry))
            if mask is None:
                continue
            geometries.append(mask)
            records.append({"node_id": node.node_id, "group_id": group.group_id, "rule": "E", "mode": "opposite_semantic_node"})
            blocked_directions.append(
                {"layer": "semantic_node", "object_id": node.node_id, "reason": "single_sided_opposite_semantic_node"}
            )
    return _clean_geometry(unary_union(geometries)) if geometries else None, records, blocked_directions

def _build_foreign_object_masks(
    context: Step1Context,
    *,
    frontier_candidate_road_ids: set[str],
    adjacent_cut_road_ids: set[str],
    excluded_road_ids: set[str],
    excluded_node_ids: set[str],
    protected_road_ids: set[str],
    protected_group_ids: set[str],
) -> tuple[BaseGeometry | None, list[dict[str, Any]], bool]:
    geometries: list[BaseGeometry] = []
    records: list[dict[str, Any]] = []
    node_fallback_used = False
    foreign_node_ids = {node.node_id for group in context.foreign_groups for node in group.nodes}
    masked_foreign_node_ids: set[str] = set(excluded_node_ids)
    for road in context.roads:
        if (
            road.road_id in frontier_candidate_road_ids
            or road.road_id in adjacent_cut_road_ids
            or road.road_id in excluded_road_ids
            or road.road_id in protected_road_ids
        ):
            continue
        local_mask = _clean_geometry(
            road.geometry.buffer(NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
        )
        if local_mask is None:
            continue
        geometries.append(local_mask)
        for endpoint_id in (road.snodeid, road.enodeid):
            if endpoint_id is not None and endpoint_id in foreign_node_ids:
                masked_foreign_node_ids.add(endpoint_id)
        records.append({"road_id": road.road_id, "rule": "B", "mode": "road_buffer"})
    for group in context.foreign_groups:
        if group.group_id in protected_group_ids:
            continue
        for node in group.nodes:
            if node.node_id in masked_foreign_node_ids:
                continue
            node_fallback_used = True
            mask = _clean_geometry(_point_like(node.geometry).buffer(NEGATIVE_MASK_BUFFER_M).intersection(context.drivezone_geometry))
            if mask is None:
                continue
            geometries.append(mask)
            records.append({"node_id": node.node_id, "group_id": group.group_id, "rule": "B", "mode": "node_fallback"})
    return _clean_geometry(unary_union(geometries)) if geometries else None, records, node_fallback_used

def _component_touching_target(geometry: BaseGeometry | None, target_geometry: BaseGeometry) -> BaseGeometry | None:
    cleaned = _extract_polygon_geometry(geometry)
    if cleaned is None:
        return None
    geoms: list[BaseGeometry]
    if isinstance(cleaned, MultiPolygon):
        geoms = list(cleaned.geoms)
    else:
        geoms = [cleaned]
    kept = [geom for geom in geoms if not geom.is_empty and geom.intersects(target_geometry)]
    if not kept:
        return None
    return _clean_geometry(unary_union(kept))

def _target_edge_touch_fields(
    *,
    enabled: bool = False,
    reason: str = "not_applicable",
    tolerance_m: float = TARGET_COMPONENT_TOUCH_BUFFER_M,
    target_drivezone_distances_m: list[float] | None = None,
) -> dict[str, Any]:
    return {
        "target_edge_touch_enabled": enabled,
        "target_edge_touch_reason": reason,
        "target_edge_touch_tolerance_m": round(tolerance_m, 6),
        "target_drivezone_distances_m": target_drivezone_distances_m or [],
    }

def _node_has_incident_drivezone_support(context: Step1Context, node: Any) -> bool:
    point = _point_like(node.geometry)
    for road in context.roads:
        if node.node_id not in {road.snodeid, road.enodeid}:
            continue
        drivezone_line = _extract_line_geometry(road.geometry.intersection(context.drivezone_geometry))
        if drivezone_line is None:
            continue
        if point.distance(drivezone_line) <= TARGET_NODE_INCIDENT_ROAD_COVER_TOLERANCE_M:
            return True
    return False

def _target_component_touch_reference(
    context: Step1Context,
    template_result: Step2TemplateResult,
) -> tuple[BaseGeometry, dict[str, Any]]:
    distances = [
        float(_point_like(node.geometry).distance(context.drivezone_geometry))
        for node in context.target_group.nodes
    ]
    rounded_distances = [round(distance, 6) for distance in distances]
    tolerance_m = TARGET_COMPONENT_TOUCH_BUFFER_M
    edge_fields = _target_edge_touch_fields(
        tolerance_m=tolerance_m,
        target_drivezone_distances_m=rounded_distances,
    )
    if template_result.template_class != "single_sided_t_mouth":
        return unary_union([node.geometry.buffer(tolerance_m) for node in context.target_group.nodes]), edge_fields
    if not distances or max(distances) <= TARGET_COMPONENT_TOUCH_BUFFER_M:
        edge_fields = _target_edge_touch_fields(
            reason="target_inside_default_touch",
            tolerance_m=tolerance_m,
            target_drivezone_distances_m=rounded_distances,
        )
        return unary_union([node.geometry.buffer(tolerance_m) for node in context.target_group.nodes]), edge_fields
    if max(distances) > SINGLE_SIDED_TARGET_DRIVEZONE_EDGE_TOUCH_M:
        edge_fields = _target_edge_touch_fields(
            reason="target_too_far_from_drivezone",
            tolerance_m=tolerance_m,
            target_drivezone_distances_m=rounded_distances,
        )
        return unary_union([node.geometry.buffer(tolerance_m) for node in context.target_group.nodes]), edge_fields
    if not all(_node_has_incident_drivezone_support(context, node) for node in context.target_group.nodes):
        edge_fields = _target_edge_touch_fields(
            reason="target_lacks_incident_drivezone_support",
            tolerance_m=tolerance_m,
            target_drivezone_distances_m=rounded_distances,
        )
        return unary_union([node.geometry.buffer(tolerance_m) for node in context.target_group.nodes]), edge_fields
    tolerance_m = SINGLE_SIDED_TARGET_DRIVEZONE_EDGE_TOUCH_M
    edge_fields = _target_edge_touch_fields(
        enabled=True,
        reason="single_sided_target_near_drivezone_with_incident_support",
        tolerance_m=tolerance_m,
        target_drivezone_distances_m=rounded_distances,
    )
    return unary_union([node.geometry.buffer(tolerance_m) for node in context.target_group.nodes]), edge_fields

def _node_has_incident_allowed_support(
    context: Step1Context,
    node: NodeRecord,
    allowed_space_geometry: BaseGeometry,
    *,
    selected_road_ids: set[str] | None = None,
) -> bool:
    point = _point_like(node.geometry)
    if point.distance(allowed_space_geometry) > TARGET_NODE_INCIDENT_ROAD_COVER_TOLERANCE_M:
        return False
    allowed_probe = allowed_space_geometry.buffer(TARGET_NODE_COVER_TOLERANCE_M)
    for road in context.roads:
        if selected_road_ids is not None and road.road_id not in selected_road_ids:
            continue
        if node.node_id not in {road.snodeid, road.enodeid}:
            continue
        supported_segment = road.geometry.intersection(allowed_probe)
        if supported_segment.is_empty:
            return True
        if point.distance(supported_segment) <= TARGET_NODE_INCIDENT_ROAD_COVER_TOLERANCE_M:
            return True
    return False

def _covered_node_ids(
    context: Step1Context,
    allowed_space_geometry: BaseGeometry | None,
    *,
    selected_road_ids: set[str] | None = None,
) -> list[str]:
    if allowed_space_geometry is None:
        return []
    cover_geometry = allowed_space_geometry.buffer(TARGET_NODE_COVER_TOLERANCE_M)
    covered_node_ids: list[str] = []
    for node in context.target_group.nodes:
        if cover_geometry.covers(node.geometry) or _node_has_incident_allowed_support(
            context,
            node,
            allowed_space_geometry,
            selected_road_ids=selected_road_ids,
        ):
            covered_node_ids.append(node.node_id)
    return covered_node_ids

def _has_negative_intrusion(geometry: BaseGeometry | None, negative_union: BaseGeometry | None) -> bool:
    if geometry is None or negative_union is None:
        return False
    intersection = geometry.intersection(negative_union)
    if intersection.is_empty:
        return False
    return float(getattr(intersection, "area", 0.0)) > INTRUSION_AREA_TOLERANCE_M2

def _drivezone_containment_metrics(
    geometry: BaseGeometry | None,
    drivezone_geometry: BaseGeometry,
) -> dict[str, Any]:
    if geometry is None or geometry.is_empty:
        return {
            "allowed_area_m2": 0.0,
            "allowed_inside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_ratio": 0.0,
            "drivezone_containment_passed": False,
        }
    allowed_area = float(getattr(geometry, "area", 0.0))
    inside = geometry.intersection(drivezone_geometry)
    outside = geometry.difference(drivezone_geometry)
    inside_area = 0.0 if inside.is_empty else float(getattr(inside, "area", 0.0))
    outside_area = 0.0 if outside.is_empty else float(getattr(outside, "area", 0.0))
    outside_ratio = 0.0 if allowed_area <= 0.0 else outside_area / allowed_area
    return {
        "allowed_area_m2": round(allowed_area, 6),
        "allowed_inside_drivezone_area_m2": round(inside_area, 6),
        "allowed_outside_drivezone_area_m2": round(outside_area, 6),
        "allowed_outside_drivezone_ratio": round(outside_ratio, 9),
        "drivezone_containment_passed": outside_area <= DRIVEZONE_OUTSIDE_AREA_TOLERANCE_M2,
    }

def _build_status_doc(case_result: Step3CaseResult) -> dict[str, Any]:
    return {
        "case_id": case_result.case_id,
        "template_class": case_result.template_class,
        "step3_state": case_result.step3_state,
        "step3_established": case_result.step3_established,
        "reason": case_result.reason,
        "visual_review_class": case_result.visual_review_class,
        "root_cause_layer": case_result.root_cause_layer,
        "root_cause_type": case_result.root_cause_type,
        "key_metrics": case_result.key_metrics,
        **case_result.extra_status_fields,
    }

def _review_visual_class(step3_state: str, review_signals: list[str], reason: str) -> str:
    if step3_state == "established":
        return "V1 认可成功"
    if step3_state == "review":
        if any(signal.startswith("required") for signal in review_signals):
            return "V3 漏包 required"
        return "V2 业务正确但几何待修"
    if "foreign" in reason or "opposite" in reason:
        return "V4 误包 foreign"
    return "V5 明确失败"

def _root_cause_layer(step3_state: str) -> str | None:
    if step3_state == "established":
        return None
    return "step3"

def _empty_audit_doc(
    context: Step1Context,
    *,
    reason: str,
    input_gate: dict[str, Any],
    opposite_side_guard_mode: str = "not_applicable",
    corridor_guard_status: str = "not_applicable",
) -> dict[str, Any]:
    rule_d_fallback_fields = _rule_d_fallback_fields()
    two_node_t_bridge_fields = _two_node_t_bridge_closeout_defaults()
    shared_two_in_two_out_fields = _shared_two_in_two_out_closeout_fields()
    rcsd_opposite_fallback = _rcsd_opposite_fallback_fields()
    return {
        "input_gate": input_gate,
        "rules": {key: {"passed": False, "reason": reason} for key in "ABCDEFGH"},
        "adjacent_junction_cuts": [],
        "foreign_object_masks": [],
        "foreign_mst_masks": [],
        "growth_limits": [],
        **rule_d_fallback_fields,
        "cleanup_dependency": False,
        "must_cover_result": {
            "covered_node_ids": [],
            "missing_node_ids": [node.node_id for node in context.target_group.nodes],
        },
        "blocked_directions": [],
        "review_signals": [],
        "direction_mode": DIRECTION_MODE,
        "growth_order": "hard_bound_first",
        "hard_bound_first": True,
        "post_growth_safety_only": True,
        "frontier_stop_reason": [],
        "selected_road_ids": [],
        "excluded_road_ids": [],
        "opposite_road_ids": [],
        "opposite_semantic_node_ids": [],
        "opposite_rcsdroad_ids": [],
        "opposite_side_guard_mode": opposite_side_guard_mode,
        "corridor_guard_status": corridor_guard_status,
        "opposite_side_guard_note": None,
        **rcsd_opposite_fallback,
        "hard_path_passed": False,
        "cleanup_preview_passed": False,
        "rescue_reason": None,
        "adjacent_junction_cut_suppressed": [],
        "adjacent_junction_cut_protection_applied": False,
        "adjacent_junction_cut_protection_reason": None,
        "allowed_area_m2": 0.0,
        "allowed_inside_drivezone_area_m2": 0.0,
        "allowed_outside_drivezone_area_m2": 0.0,
        "allowed_outside_drivezone_ratio": 0.0,
        "drivezone_containment_passed": False,
        **two_node_t_bridge_fields,
        **shared_two_in_two_out_fields,
    }

def _status_for_unsupported_template(context: Step1Context, template_result: Step2TemplateResult) -> Step3CaseResult:
    reason = template_result.reason or "unsupported_template"
    input_gate = {
        "passed": context.representative_node.has_evd == "yes" and context.representative_node.is_anchor in {None, "no"},
        "reason": None,
        "has_evd": context.representative_node.has_evd,
        "is_anchor": context.representative_node.is_anchor,
    }
    audit_doc = _empty_audit_doc(context, reason=reason, input_gate=input_gate)
    rule_d_fallback_fields = _rule_d_fallback_fields()
    two_node_t_bridge_fields = _two_node_t_bridge_closeout_defaults()
    shared_two_in_two_out_fields = _shared_two_in_two_out_closeout_fields()
    single_sided_direction_resolution = _single_sided_direction_resolution_fields()
    rcsd_opposite_fallback = _rcsd_opposite_fallback_fields()
    return Step3CaseResult(
        case_id=context.case_spec.case_id,
        template_class=template_result.template_class,
        step3_state="not_established",
        step3_established=False,
        reason=reason,
        visual_review_class="V5 明确失败",
        root_cause_layer="step2",
        root_cause_type=reason,
        allowed_space_geometry=None,
        allowed_drivezone_geometry=None,
        negative_masks=Step3NegativeMasks(None, None, None),
        key_metrics={"target_group_node_count": len(context.target_group.nodes), "supported": False},
        audit_doc=audit_doc,
        extra_status_fields={
            "representative_node_id": context.representative_node.node_id,
            "target_group_node_ids": [node.node_id for node in context.target_group.nodes],
            "foreign_group_ids": [group.group_id for group in context.foreign_groups],
            "selected_road_ids": [],
            "excluded_road_ids": [],
            "blocked_direction_reasons": [],
            "cleanup_dependency": False,
            "direction_mode": DIRECTION_MODE,
            **rule_d_fallback_fields,
            **single_sided_direction_resolution,
            **rcsd_opposite_fallback,
            "allowed_area_m2": 0.0,
            "allowed_inside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_ratio": 0.0,
            "drivezone_containment_passed": False,
            **two_node_t_bridge_fields,
            **shared_two_in_two_out_fields,
        },
    )

def _status_for_input_gate_failure(
    context: Step1Context,
    template_result: Step2TemplateResult,
    *,
    input_gate: dict[str, Any],
) -> Step3CaseResult:
    reason = "input_gate_failed"
    audit_doc = _empty_audit_doc(context, reason=reason, input_gate=input_gate)
    rule_d_fallback_fields = _rule_d_fallback_fields()
    two_node_t_bridge_fields = _two_node_t_bridge_closeout_defaults()
    shared_two_in_two_out_fields = _shared_two_in_two_out_closeout_fields()
    single_sided_direction_resolution = _single_sided_direction_resolution_fields()
    rcsd_opposite_fallback = _rcsd_opposite_fallback_fields()
    return Step3CaseResult(
        case_id=context.case_spec.case_id,
        template_class=template_result.template_class,
        step3_state="not_established",
        step3_established=False,
        reason=reason,
        visual_review_class="V5 明确失败",
        root_cause_layer="step1",
        root_cause_type=reason,
        allowed_space_geometry=None,
        allowed_drivezone_geometry=None,
        negative_masks=Step3NegativeMasks(None, None, None),
        key_metrics={"target_group_node_count": len(context.target_group.nodes)},
        audit_doc=audit_doc,
        extra_status_fields={
            "representative_node_id": context.representative_node.node_id,
            "target_group_node_ids": [node.node_id for node in context.target_group.nodes],
            "foreign_group_ids": [group.group_id for group in context.foreign_groups],
            "selected_road_ids": [],
            "excluded_road_ids": [],
            "blocked_direction_reasons": [],
            "cleanup_dependency": False,
            "direction_mode": DIRECTION_MODE,
            **rule_d_fallback_fields,
            **single_sided_direction_resolution,
            **rcsd_opposite_fallback,
            "allowed_area_m2": 0.0,
            "allowed_inside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_area_m2": 0.0,
            "allowed_outside_drivezone_ratio": 0.0,
            "drivezone_containment_passed": False,
            **two_node_t_bridge_fields,
            **shared_two_in_two_out_fields,
        },
    )
