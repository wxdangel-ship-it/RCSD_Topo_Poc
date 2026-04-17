from __future__ import annotations

import heapq
import math
from collections import defaultdict
from typing import Any

from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import substring, unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.models import (
    RoadRecord,
    SemanticGroup,
    Step1Context,
    Step2TemplateResult,
    Step3CaseResult,
    Step3NegativeMasks,
)


ROAD_BUFFER_M = 8.0
NODE_BUFFER_M = 5.0
NEGATIVE_MASK_BUFFER_M = 1.0
STEP3_DISTANCE_CAP_M = 50.0


def _clean_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None:
        return None
    if geometry.is_empty:
        return None
    cleaned = geometry.buffer(0)
    if cleaned.is_empty:
        return None
    return cleaned


def _line_midpoint(geometry: BaseGeometry) -> Point:
    if geometry.length <= 0.0:
        centroid = geometry.centroid
        return centroid if isinstance(centroid, Point) else centroid.representative_point()
    return geometry.interpolate(geometry.length / 2.0)


def _point_like(geometry: BaseGeometry) -> Point:
    if isinstance(geometry, Point):
        return geometry
    point = geometry.representative_point()
    return point if isinstance(point, Point) else Point(point.coords[0])


def _road_vector_from_reference(road: RoadRecord, reference: Point) -> tuple[float, float]:
    coords = list(road.geometry.coords)
    start = Point(coords[0])
    end = Point(coords[-1])
    if start.distance(reference) <= end.distance(reference):
        near, far = start, end
    else:
        near, far = end, start
    vx = far.x - near.x
    vy = far.y - near.y
    norm = math.hypot(vx, vy)
    if norm <= 1e-6:
        return (1.0, 0.0)
    return (vx / norm, vy / norm)


def _build_road_graph(roads: tuple[RoadRecord, ...]) -> dict[str, list[tuple[str, float, RoadRecord]]]:
    graph: dict[str, list[tuple[str, float, RoadRecord]]] = defaultdict(list)
    for road in roads:
        if road.snodeid is None or road.enodeid is None or road.geometry.length <= 0.0:
            continue
        length = float(road.geometry.length)
        graph[road.snodeid].append((road.enodeid, length, road))
        graph[road.enodeid].append((road.snodeid, length, road))
    return graph


def _multi_source_dijkstra(
    graph: dict[str, list[tuple[str, float, RoadRecord]]],
    source_node_ids: set[str],
) -> dict[str, float]:
    distances = {node_id: 0.0 for node_id in source_node_ids}
    heap: list[tuple[float, str]] = [(0.0, node_id) for node_id in source_node_ids]
    heapq.heapify(heap)
    while heap:
        current_dist, node_id = heapq.heappop(heap)
        if current_dist > distances.get(node_id, math.inf):
            continue
        for next_node_id, edge_length, _road in graph.get(node_id, ()):
            next_dist = current_dist + edge_length
            if next_dist + 1e-6 < distances.get(next_node_id, math.inf):
                distances[next_node_id] = next_dist
                heapq.heappush(heap, (next_dist, next_node_id))
    return distances


def _clip_road_to_cap(road: RoadRecord, distances: dict[str, float], cap_m: float) -> BaseGeometry | None:
    if road.snodeid is None or road.enodeid is None:
        return None
    d_start = distances.get(road.snodeid, math.inf)
    d_end = distances.get(road.enodeid, math.inf)
    if d_start > cap_m and d_end > cap_m:
        return None
    pieces: list[BaseGeometry] = []
    if d_start <= cap_m:
        keep_len = min(road.geometry.length, max(0.0, cap_m - d_start))
        pieces.append(substring(road.geometry, 0.0, keep_len))
    if d_end <= cap_m:
        keep_len = min(road.geometry.length, max(0.0, cap_m - d_end))
        pieces.append(substring(road.geometry, max(0.0, road.geometry.length - keep_len), road.geometry.length))
    if not pieces:
        return None
    return _clean_geometry(unary_union(pieces))


def _perpendicular_cut_strip(road: RoadRecord, endpoint: str) -> BaseGeometry | None:
    coords = list(road.geometry.coords)
    if len(coords) < 2:
        return None
    if endpoint == "start":
        p0 = Point(coords[0])
        p1 = Point(coords[1])
        offset_base = road.geometry.interpolate(min(NEGATIVE_MASK_BUFFER_M, road.geometry.length))
    else:
        p0 = Point(coords[-1])
        p1 = Point(coords[-2])
        offset_base = road.geometry.interpolate(max(0.0, road.geometry.length - NEGATIVE_MASK_BUFFER_M))
    vx = offset_base.x - p0.x
    vy = offset_base.y - p0.y
    norm = math.hypot(vx, vy)
    if norm <= 1e-6:
        vx = p0.x - p1.x
        vy = p0.y - p1.y
        norm = math.hypot(vx, vy)
    if norm <= 1e-6:
        return None
    vx /= norm
    vy /= norm
    nx = -vy
    ny = vx
    half_width = 6.0
    depth = 2.5
    cx = offset_base.x
    cy = offset_base.y
    polygon = Polygon(
        [
            (cx - nx * half_width - vx * depth, cy - ny * half_width - vy * depth),
            (cx + nx * half_width - vx * depth, cy + ny * half_width - vy * depth),
            (cx + nx * half_width + vx * depth, cy + ny * half_width + vy * depth),
            (cx - nx * half_width + vx * depth, cy - ny * half_width + vy * depth),
        ]
    )
    return _clean_geometry(polygon)


def _build_adjacent_junction_masks(
    context: Step1Context,
    distances: dict[str, float],
) -> tuple[BaseGeometry | None, list[dict[str, Any]], set[str]]:
    target_group_id = context.target_group.group_id
    geometries: list[BaseGeometry] = []
    records: list[dict[str, Any]] = []
    road_ids: set[str] = set()
    foreign_group_lookup = {
        node.node_id: group.group_id
        for group in context.foreign_groups
        for node in group.nodes
    }
    for road in context.roads:
        if road.snodeid is None or road.enodeid is None:
            continue
        endpoints = {
            "start": road.snodeid,
            "end": road.enodeid,
        }
        for endpoint_name, node_id in endpoints.items():
            group_id = foreign_group_lookup.get(node_id)
            if group_id is None or group_id == target_group_id:
                continue
            strip = _perpendicular_cut_strip(road, endpoint_name)
            if strip is None:
                continue
            clipped = _clean_geometry(strip.intersection(context.drivezone_geometry))
            if clipped is None:
                continue
            geometries.append(clipped)
            road_ids.add(road.road_id)
            records.append(
                {
                    "group_id": group_id,
                    "road_id": road.road_id,
                    "endpoint": endpoint_name,
                    "rule": "A",
                }
            )
    return _clean_geometry(unary_union(geometries)) if geometries else None, records, road_ids


def _build_mst_edges(points: list[Point]) -> list[LineString]:
    if len(points) < 2:
        return []
    visited = {0}
    remaining = set(range(1, len(points)))
    edges: list[LineString] = []
    while remaining:
        best_pair: tuple[int, int] | None = None
        best_distance = math.inf
        for src in visited:
            for dst in remaining:
                distance = points[src].distance(points[dst])
                if distance < best_distance:
                    best_distance = distance
                    best_pair = (src, dst)
        if best_pair is None:
            break
        src, dst = best_pair
        edges.append(LineString([points[src], points[dst]]))
        visited.add(dst)
        remaining.remove(dst)
    return edges


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
        clipped = _clean_geometry(unary_union(mst_edges).intersection(context.drivezone_geometry))
        if clipped is None:
            continue
        mask = _clean_geometry(clipped.buffer(NEGATIVE_MASK_BUFFER_M))
        if mask is None:
            continue
        geometries.append(mask)
        records.append(
            {
                "group_id": group.group_id,
                "node_count": len(group.nodes),
                "rule": "C",
            }
        )
    return _clean_geometry(unary_union(geometries)) if geometries else None, records


def _build_candidate_roads_for_single_sided(context: Step1Context) -> tuple[set[str], set[str], bool, tuple[float, float] | None]:
    reference = _point_like(context.representative_node.geometry)
    candidate_roads = [
        road
        for road in context.roads
        if road.road_id in context.target_road_ids or road.geometry.distance(reference) <= 18.0
    ]
    if not candidate_roads:
        return set(), {road.road_id for road in context.roads}, True, None
    direction_vectors = [_road_vector_from_reference(road, reference) for road in candidate_roads]
    scored: list[tuple[float, set[str], set[str], tuple[float, float]]] = []
    for vx, vy in direction_vectors:
        allowed: set[str] = set()
        excluded: set[str] = set()
        for road in context.roads:
            midpoint = _line_midpoint(road.geometry)
            dot = (midpoint.x - reference.x) * vx + (midpoint.y - reference.y) * vy
            if road.road_id in context.target_road_ids or dot >= -2.0:
                allowed.add(road.road_id)
            else:
                excluded.add(road.road_id)
        score = float(len(allowed) * 10 - len(excluded))
        for road in context.roads:
            if road.road_id in allowed:
                midpoint = _line_midpoint(road.geometry)
                score += math.hypot(midpoint.x - reference.x, midpoint.y - reference.y) * 0.01
        scored.append((score, allowed, excluded, (vx, vy)))
    scored.sort(key=lambda item: item[0], reverse=True)
    top_score = scored[0][0]
    ambiguous = len(scored) > 1 and abs(top_score - scored[1][0]) <= max(3.0, abs(top_score) * 0.15)
    return scored[0][1], scored[0][2], ambiguous, scored[0][3]


def _split_point_side(reference: Point, point: Point, direction: tuple[float, float]) -> float:
    vx, vy = direction
    return (point.x - reference.x) * vx + (point.y - reference.y) * vy


def _build_single_sided_exclusions(
    context: Step1Context,
    direction: tuple[float, float] | None,
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
        point = _point_like(node.geometry)
        if _split_point_side(reference, point, direction) < -2.0:
            excluded_rc_node_ids.add(node.node_id)
    return excluded_rc_road_ids, excluded_rc_node_ids


def _build_reachable_road_support(
    context: Step1Context,
    *,
    allowed_road_ids: set[str] | None = None,
    cap_m: float = STEP3_DISTANCE_CAP_M,
) -> tuple[BaseGeometry | None, list[dict[str, Any]], set[str]]:
    roads = tuple(
        road
        for road in context.roads
        if allowed_road_ids is None or road.road_id in allowed_road_ids
    )
    graph = _build_road_graph(roads)
    source_node_ids = {node.node_id for node in context.target_group.nodes}
    distances = _multi_source_dijkstra(graph, source_node_ids)
    clipped_geometries: list[BaseGeometry] = []
    growth_limits: list[dict[str, Any]] = []
    selected_road_ids: set[str] = set()
    for road in roads:
        clipped = _clip_road_to_cap(road, distances, cap_m)
        if clipped is None:
            continue
        selected_road_ids.add(road.road_id)
        clipped_geometries.append(clipped.buffer(ROAD_BUFFER_M, cap_style=2, join_style=2))
        d_start = distances.get(road.snodeid or "", math.inf)
        d_end = distances.get(road.enodeid or "", math.inf)
        cap_hit = min(d_start, d_end) <= cap_m and max(d_start, d_end) > cap_m
        growth_limits.append(
            {
                "road_id": road.road_id,
                "source_distance_start_m": None if math.isinf(d_start) else round(d_start, 3),
                "source_distance_end_m": None if math.isinf(d_end) else round(d_end, 3),
                "cap_m": cap_m,
                "cap_hit": bool(cap_hit),
            }
        )
    base = unary_union(clipped_geometries) if clipped_geometries else GeometryCollection()
    core = unary_union([node.geometry.buffer(NODE_BUFFER_M) for node in context.target_group.nodes])
    candidate = _clean_geometry(unary_union([base, core]).intersection(context.drivezone_geometry))
    return candidate, growth_limits, selected_road_ids


def _build_foreign_object_masks(
    context: Step1Context,
    *,
    selected_road_ids: set[str],
    adjacent_cut_road_ids: set[str],
    excluded_opposite_road_ids: set[str],
    excluded_opposite_rc_road_ids: set[str],
    excluded_opposite_rc_node_ids: set[str],
) -> tuple[BaseGeometry | None, list[dict[str, Any]], bool, list[dict[str, Any]]]:
    geometries: list[BaseGeometry] = []
    records: list[dict[str, Any]] = []
    node_fallback_used = False
    blocked_directions: list[dict[str, Any]] = []
    foreign_node_ids = {
        node.node_id
        for group in context.foreign_groups
        for node in group.nodes
    }
    masked_foreign_node_ids: set[str] = set()
    for road in context.roads:
        if road.road_id in selected_road_ids or road.road_id in adjacent_cut_road_ids:
            continue
        local_mask = _clean_geometry(road.geometry.buffer(NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry))
        if local_mask is None:
            continue
        geometries.append(local_mask)
        for endpoint_id in (road.snodeid, road.enodeid):
            if endpoint_id is not None and endpoint_id in foreign_node_ids:
                masked_foreign_node_ids.add(endpoint_id)
        rule = "E" if road.road_id in excluded_opposite_road_ids else "B"
        records.append({"road_id": road.road_id, "rule": rule, "mode": "road_buffer"})
        if road.road_id in excluded_opposite_road_ids:
            blocked_directions.append({"layer": "road", "object_id": road.road_id, "reason": "single_sided_opposite_side"})
    for road in context.rcsd_roads:
        if road.road_id not in excluded_opposite_rc_road_ids:
            continue
        local_mask = _clean_geometry(road.geometry.buffer(NEGATIVE_MASK_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry))
        if local_mask is None:
            continue
        geometries.append(local_mask)
        records.append({"road_id": road.road_id, "rule": "E", "mode": "rcsdroad_buffer"})
        blocked_directions.append({"layer": "rcsdroad", "object_id": road.road_id, "reason": "single_sided_opposite_corridor"})
    for group in context.foreign_groups:
        for node in group.nodes:
            point = _point_like(node.geometry)
            if node.node_id in excluded_opposite_rc_node_ids:
                mask = _clean_geometry(point.buffer(NEGATIVE_MASK_BUFFER_M).intersection(context.drivezone_geometry))
                if mask is not None:
                    geometries.append(mask)
                    records.append({"node_id": node.node_id, "group_id": group.group_id, "rule": "E", "mode": "opposite_semantic_node"})
                    blocked_directions.append({"layer": "semantic_node", "object_id": node.node_id, "reason": "single_sided_opposite_semantic_node"})
                continue
            if node.node_id in masked_foreign_node_ids:
                continue
            node_fallback_used = True
            mask = _clean_geometry(point.buffer(NEGATIVE_MASK_BUFFER_M).intersection(context.drivezone_geometry))
            if mask is None:
                continue
            geometries.append(mask)
            records.append({"node_id": node.node_id, "group_id": group.group_id, "rule": "B", "mode": "node_fallback"})
    return _clean_geometry(unary_union(geometries)) if geometries else None, records, node_fallback_used, blocked_directions


def _component_touching_target(geometry: BaseGeometry | None, target_geometry: BaseGeometry) -> BaseGeometry | None:
    cleaned = _clean_geometry(geometry)
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


def _status_for_unsupported_template(context: Step1Context, template_result: Step2TemplateResult) -> Step3CaseResult:
    reason = template_result.reason or "unsupported_template"
    audit_doc = {
        "rules": {key: {"passed": False, "reason": reason} for key in "ABCDEFGH"},
        "adjacent_junction_cuts": [],
        "foreign_object_masks": [],
        "foreign_mst_masks": [],
        "growth_limits": [],
        "cleanup_dependency": False,
        "must_cover_result": {"covered_node_ids": [], "missing_node_ids": [node.node_id for node in context.target_group.nodes]},
        "blocked_directions": [],
        "review_signals": [],
    }
    visual_review_class = "V5 明确失败"
    return Step3CaseResult(
        case_id=context.case_spec.case_id,
        template_class=template_result.template_class,
        step3_state="not_established",
        step3_established=False,
        reason=reason,
        visual_review_class=visual_review_class,
        root_cause_layer="step2",
        root_cause_type=reason,
        allowed_space_geometry=None,
        allowed_drivezone_geometry=None,
        negative_masks=Step3NegativeMasks(None, None, None),
        key_metrics={"target_group_node_count": len(context.target_group.nodes), "supported": False},
        audit_doc=audit_doc,
    )


def build_step3_case_result(context: Step1Context, template_result: Step2TemplateResult) -> Step3CaseResult:
    if not template_result.supported:
        return _status_for_unsupported_template(context, template_result)
    if context.representative_node.has_evd != "yes" or context.representative_node.is_anchor not in {None, "no"}:
        reason = "input_gate_failed"
        audit_doc = {
            "rules": {key: {"passed": False, "reason": reason} for key in "ABCDEFGH"},
            "adjacent_junction_cuts": [],
            "foreign_object_masks": [],
            "foreign_mst_masks": [],
            "growth_limits": [],
            "cleanup_dependency": False,
            "must_cover_result": {"covered_node_ids": [], "missing_node_ids": [node.node_id for node in context.target_group.nodes]},
            "blocked_directions": [],
            "review_signals": [],
        }
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
        )

    reference_target_geometry = unary_union([node.geometry.buffer(1.0) for node in context.target_group.nodes])
    base_allowed_road_ids: set[str] | None = None
    excluded_opposite_road_ids: set[str] = set()
    excluded_opposite_rc_road_ids: set[str] = set()
    excluded_opposite_rc_node_ids: set[str] = set()
    review_signals: list[str] = []
    if template_result.template_class == "single_sided_t_mouth":
        base_allowed_road_ids, excluded_opposite_road_ids, ambiguous, direction = _build_candidate_roads_for_single_sided(context)
        excluded_opposite_rc_road_ids, excluded_opposite_rc_node_ids = _build_single_sided_exclusions(context, direction)
        if ambiguous:
            review_signals.append("single_sided_direction_ambiguous")

    candidate_support_geometry, growth_limits, selected_road_ids = _build_reachable_road_support(
        context,
        allowed_road_ids=base_allowed_road_ids,
    )
    graph = _build_road_graph(context.roads)
    distances = _multi_source_dijkstra(graph, {node.node_id for node in context.target_group.nodes})
    adjacent_geometry, adjacent_records, adjacent_cut_road_ids = _build_adjacent_junction_masks(context, distances)
    foreign_mst_geometry, foreign_mst_records = _build_foreign_mst_masks(context)
    foreign_object_geometry, foreign_object_records, node_fallback_used, blocked_directions = _build_foreign_object_masks(
        context,
        selected_road_ids=selected_road_ids,
        adjacent_cut_road_ids=adjacent_cut_road_ids,
        excluded_opposite_road_ids=excluded_opposite_road_ids,
        excluded_opposite_rc_road_ids=excluded_opposite_rc_road_ids,
        excluded_opposite_rc_node_ids=excluded_opposite_rc_node_ids,
    )
    negative_union = _clean_geometry(
        unary_union(
            [
                geometry
                for geometry in (
                    adjacent_geometry,
                    foreign_object_geometry,
                    foreign_mst_geometry,
                )
                if geometry is not None
            ]
        )
    )
    if node_fallback_used:
        review_signals.append("rule_b_node_fallback")
    if any(bool(item["cap_hit"]) for item in growth_limits):
        review_signals.append("rule_d_50m_cap_used")

    raw_allowed = candidate_support_geometry
    if raw_allowed is not None and negative_union is not None:
        raw_allowed = _clean_geometry(raw_allowed.difference(negative_union))
    allowed_space_geometry = _component_touching_target(raw_allowed, reference_target_geometry)
    target_node_ids = [node.node_id for node in context.target_group.nodes]
    covered_node_ids = [
        node.node_id
        for node in context.target_group.nodes
        if allowed_space_geometry is not None and allowed_space_geometry.buffer(0.5).covers(node.geometry)
    ]
    missing_node_ids = [node_id for node_id in target_node_ids if node_id not in covered_node_ids]
    cleanup_dependency = False

    rules = {
        "A": {"passed": True, "count": len(adjacent_records)},
        "B": {"passed": True, "count": len(foreign_object_records), "node_fallback_used": node_fallback_used},
        "C": {"passed": True, "count": len(foreign_mst_records)},
        "D": {"passed": allowed_space_geometry is not None, "growth_limit_count": len(growth_limits)},
        "E": {
            "passed": True,
            "blocked_count": len(blocked_directions),
            "template_only": template_result.template_class == "single_sided_t_mouth",
            "excluded_opposite_road_ids": sorted(excluded_opposite_road_ids),
            "excluded_opposite_rc_road_ids": sorted(excluded_opposite_rc_road_ids),
            "excluded_opposite_semantic_node_ids": sorted(excluded_opposite_rc_node_ids),
            "lane_guard_status": "proxied_by_road_and_semantic_node_masks",
            "corridor_guard_status": "proxied_by_rcsdroad_masks",
        },
        "F": {"passed": not cleanup_dependency},
        "G": {"passed": True, "growth_after_hard_bounds_only": True},
        "H": {"passed": True, "distance_cap_m": STEP3_DISTANCE_CAP_M},
    }

    reason = "step3_established"
    step3_state = "established"
    if allowed_space_geometry is None:
        step3_state = "not_established"
        reason = "allowed_space_empty"
    elif missing_node_ids:
        step3_state = "not_established"
        reason = "must_cover_failed"
    elif template_result.template_class == "single_sided_t_mouth" and excluded_opposite_road_ids and any(
        road_id in excluded_opposite_road_ids for road_id in selected_road_ids
    ):
        step3_state = "not_established"
        reason = "single_sided_opposite_side_intrusion"
        rules["E"]["passed"] = False
    elif negative_union is not None and allowed_space_geometry.intersects(negative_union):
        step3_state = "not_established"
        reason = "negative_mask_intrusion"
    elif review_signals:
        step3_state = "review"
        reason = review_signals[0]

    if step3_state == "not_established":
        rules["D"]["passed"] = False
    visual_review_class = _review_visual_class(step3_state, review_signals, reason)
    audit_doc = {
        "rules": rules,
        "adjacent_junction_cuts": adjacent_records,
        "foreign_object_masks": foreign_object_records,
        "foreign_mst_masks": foreign_mst_records,
        "growth_limits": growth_limits,
        "cleanup_dependency": cleanup_dependency,
        "must_cover_result": {
            "covered_node_ids": covered_node_ids,
            "missing_node_ids": missing_node_ids,
        },
        "blocked_directions": blocked_directions,
        "review_signals": review_signals,
    }
    key_metrics = {
        "target_group_node_count": len(context.target_group.nodes),
        "selected_road_count": len(selected_road_ids),
        "adjacent_cut_count": len(adjacent_records),
        "foreign_object_mask_count": len(foreign_object_records),
        "foreign_mst_mask_count": len(foreign_mst_records),
        "review_signal_count": len(review_signals),
    }
    return Step3CaseResult(
        case_id=context.case_spec.case_id,
        template_class=template_result.template_class,
        step3_state=step3_state,
        step3_established=step3_state == "established",
        reason=reason,
        visual_review_class=visual_review_class,
        root_cause_layer=_root_cause_layer(step3_state),
        root_cause_type=None if step3_state == "established" else reason,
        allowed_space_geometry=allowed_space_geometry,
        allowed_drivezone_geometry=candidate_support_geometry,
        negative_masks=Step3NegativeMasks(
            adjacent_junction_geometry=adjacent_geometry,
            foreign_objects_geometry=foreign_object_geometry,
            foreign_mst_geometry=foreign_mst_geometry,
            adjacent_junction_records=tuple(adjacent_records),
            foreign_object_records=tuple(foreign_object_records),
            foreign_mst_records=tuple(foreign_mst_records),
        ),
        key_metrics=key_metrics,
        audit_doc=audit_doc,
        review_signals=tuple(review_signals),
        blocked_directions=tuple(blocked_directions),
        extra_status_fields={
            "visual_review_class": visual_review_class,
            "root_cause_layer": _root_cause_layer(step3_state),
            "root_cause_type": None if step3_state == "established" else reason,
        },
    )


def build_step3_status_doc(case_result: Step3CaseResult) -> dict[str, Any]:
    return _build_status_doc(case_result)
