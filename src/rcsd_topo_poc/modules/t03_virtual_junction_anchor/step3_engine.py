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

from .step3_engine_support import (
    _build_adjacent_junction_masks,
    _build_candidate_roads_for_single_sided,
    _build_foreign_mst_masks,
    _build_foreign_object_masks,
    _build_mst_edges,
    _build_rcsd_semantic_bridge_support,
    _build_single_sided_blockers,
    _build_single_sided_exclusions,
    _build_status_doc,
    _build_two_node_t_bridge_support,
    _component_touching_target,
    _covered_node_ids,
    _drivezone_containment_metrics,
    _empty_audit_doc,
    _filter_opposite_rc_node_ids,
    _filter_opposite_rc_road_ids,
    _has_negative_intrusion,
    _node_has_incident_allowed_support,
    _node_has_incident_drivezone_support,
    _reverse_mask_strip_in_drivezone,
    _review_visual_class,
    _root_cause_layer,
    _split_point_side,
    _status_for_input_gate_failure,
    _status_for_unsupported_template,
    _target_component_touch_reference,
    _target_edge_touch_fields,
)

def _accumulate_step3_stage_timer(
    stage_timers: dict[str, float] | None,
    key: str,
    elapsed_seconds: float,
) -> None:
    if stage_timers is None:
        return
    stage_timers[key] = round(float(stage_timers.get(key, 0.0)) + max(float(elapsed_seconds), 0.0), 6)

def _build_road_graph(
    roads: tuple[RoadRecord, ...],
    *,
    force_bidirectional_road_ids: set[str] | None = None,
) -> dict[str, list[tuple[str, float, RoadRecord]]]:
    graph: dict[str, list[tuple[str, float, RoadRecord]]] = defaultdict(list)
    force_bidirectional_road_ids = force_bidirectional_road_ids or set()
    for road in roads:
        if road.geometry.length <= 0.0:
            continue
        length = float(road.geometry.length)
        for source_node_id, target_node_id in _directed_edge_pairs_from_t02_semantics(
            road,
            force_bidirectional=road.road_id in force_bidirectional_road_ids,
        ):
            graph[source_node_id].append((target_node_id, length, road))
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

def _prepare_reachable_road_support(
    context: Step1Context,
    *,
    allowed_road_ids: set[str] | None = None,
    force_bidirectional_road_ids: set[str] | None = None,
    cap_m: float = STEP3_DISTANCE_CAP_M,
    case_cache: _ReachableRoadSupportCaseCache | None = None,
) -> _ReachableRoadPreparedSupport:
    allowed_key = _sorted_string_key(allowed_road_ids)
    force_key = _sorted_string_key(force_bidirectional_road_ids)
    prepared_key = (allowed_key, force_key, round(float(cap_m), 6))
    if case_cache is not None and prepared_key in case_cache.prepared_supports:
        return case_cache.prepared_supports[prepared_key]

    roads = tuple(road for road in context.roads if allowed_road_ids is None or road.road_id in allowed_road_ids)
    source_node_ids = {node.node_id for node in context.target_group.nodes}
    force_bidirectional_road_ids = force_bidirectional_road_ids or set()
    graph = _build_road_graph(roads, force_bidirectional_road_ids=force_bidirectional_road_ids)
    distances = _multi_source_dijkstra(graph, source_node_ids)

    prepared_records: list[_ReachableRoadPreparedRecord] = []
    for road in roads:
        clipped_to_cap = _clip_road_to_cap(
            road,
            distances,
            cap_m,
            force_bidirectional=road.road_id in force_bidirectional_road_ids,
        )
        if clipped_to_cap is None:
            continue
        drivezone_line = _extract_line_geometry(clipped_to_cap.intersection(context.drivezone_geometry))
        d_start = distances.get(road.snodeid or "", math.inf)
        d_end = distances.get(road.enodeid or "", math.inf)
        incoming_support, outgoing_support = _road_flow_flags_for_group_like_t02(road, source_node_ids)
        prepared_records.append(
            _ReachableRoadPreparedRecord(
                road=road,
                drivezone_line=drivezone_line,
                source_distance_start_m=d_start,
                source_distance_end_m=d_end,
                cap_hit=min(d_start, d_end) <= cap_m and max(d_start, d_end) > cap_m,
                incoming_support=incoming_support,
                outgoing_support=outgoing_support,
            )
        )

    base_target_core = _extract_polygon_geometry(unary_union([node.geometry.buffer(NODE_BUFFER_M) for node in context.target_group.nodes]))
    if base_target_core is not None:
        base_target_core = _extract_polygon_geometry(base_target_core.intersection(context.drivezone_geometry))

    prepared_support = _ReachableRoadPreparedSupport(
        prepared_records=tuple(prepared_records),
        base_target_core=base_target_core,
        template_road_filter_applied=allowed_road_ids is not None and len(roads) < len(context.roads),
    )
    if case_cache is not None:
        case_cache.prepared_supports[prepared_key] = prepared_support
    return prepared_support

def _build_reachable_road_support(
    context: Step1Context,
    *,
    allowed_road_ids: set[str] | None = None,
    blocker_geometry: BaseGeometry | None = None,
    force_bidirectional_road_ids: set[str] | None = None,
    cap_m: float = STEP3_DISTANCE_CAP_M,
    case_cache: _ReachableRoadSupportCaseCache | None = None,
) -> tuple[BaseGeometry | None, list[dict[str, Any]], set[str], list[str]]:
    force_bidirectional_road_ids = force_bidirectional_road_ids or set()
    prepared_support = _prepare_reachable_road_support(
        context,
        allowed_road_ids=allowed_road_ids,
        force_bidirectional_road_ids=force_bidirectional_road_ids,
        cap_m=cap_m,
        case_cache=case_cache,
    )
    result_key = (
        _sorted_string_key(allowed_road_ids),
        _geometry_cache_token(blocker_geometry),
        _sorted_string_key(force_bidirectional_road_ids),
        round(float(cap_m), 6),
    )
    if case_cache is not None and result_key in case_cache.result_cache:
        cached_geometry, cached_growth_limits, cached_selected_road_ids, cached_frontier_stop_reasons = case_cache.result_cache[result_key]
        return (
            cached_geometry,
            [dict(item) for item in cached_growth_limits],
            set(cached_selected_road_ids),
            list(cached_frontier_stop_reasons),
        )

    clipped_geometries: list[BaseGeometry] = []
    growth_limits: list[dict[str, Any]] = []
    selected_road_ids: set[str] = set()
    frontier_stop_reasons: set[str] = set()
    if prepared_support.template_road_filter_applied:
        frontier_stop_reasons.add("template_road_filter_applied")
    for prepared_record in prepared_support.prepared_records:
        road = prepared_record.road
        drivezone_line = prepared_record.drivezone_line
        if drivezone_line is None:
            frontier_stop_reasons.add("drivezone_boundary")
            continue
        hard_bound_line = _clip_line_to_hard_bounds(
            drivezone_line,
            drivezone_geometry=context.drivezone_geometry,
            blocker_geometry=blocker_geometry,
        )
        if blocker_geometry is not None:
            if hard_bound_line is None:
                frontier_stop_reasons.add("hard_blocker_applied")
                continue
            if abs(hard_bound_line.length - drivezone_line.length) > 1e-6:
                frontier_stop_reasons.add("hard_blocker_applied")
        else:
            hard_bound_line = drivezone_line
        if hard_bound_line is None:
            continue
        selected_road_ids.add(road.road_id)
        buffered_support = _extract_polygon_geometry(
            hard_bound_line.buffer(ROAD_BUFFER_M, cap_style=2, join_style=2).intersection(context.drivezone_geometry)
        )
        if blocker_geometry is not None and buffered_support is not None:
            buffered_support = _extract_polygon_geometry(buffered_support.difference(blocker_geometry))
        if buffered_support is None:
            frontier_stop_reasons.add("hard_blocker_applied" if blocker_geometry is not None else "drivezone_boundary")
            continue
        clipped_geometries.append(buffered_support)
        if prepared_record.cap_hit:
            frontier_stop_reasons.add("distance_cap_reached")
        growth_limits.append(
            {
                "road_id": road.road_id,
                "source_distance_start_m": (
                    None
                    if math.isinf(prepared_record.source_distance_start_m)
                    else round(prepared_record.source_distance_start_m, 3)
                ),
                "source_distance_end_m": (
                    None
                    if math.isinf(prepared_record.source_distance_end_m)
                    else round(prepared_record.source_distance_end_m, 3)
                ),
                "cap_m": cap_m,
                "cap_hit": bool(prepared_record.cap_hit),
                "incoming_support": prepared_record.incoming_support,
                "outgoing_support": prepared_record.outgoing_support,
            }
        )
    target_core = prepared_support.base_target_core
    if target_core is not None:
        if blocker_geometry is not None and target_core is not None:
            clipped_core = _extract_polygon_geometry(target_core.difference(blocker_geometry))
            if clipped_core is None:
                frontier_stop_reasons.add("target_core_blocked")
            target_core = clipped_core
    candidate_parts = [geometry for geometry in clipped_geometries if geometry is not None]
    if target_core is not None:
        candidate_parts.append(target_core)
    if not candidate_parts:
        result = (None, tuple(dict(item) for item in growth_limits), frozenset(selected_road_ids), tuple(sorted(frontier_stop_reasons)))
        if case_cache is not None:
            case_cache.result_cache[result_key] = result
        return None, [dict(item) for item in result[1]], set(result[2]), list(result[3])
    candidate = _extract_polygon_geometry(unary_union(candidate_parts))
    result = (
        candidate,
        tuple(dict(item) for item in growth_limits),
        frozenset(selected_road_ids),
        tuple(sorted(frontier_stop_reasons)),
    )
    if case_cache is not None:
        case_cache.result_cache[result_key] = result
    return candidate, [dict(item) for item in result[1]], set(result[2]), list(result[3])

def build_step3_case_result(
    context: Step1Context,
    template_result: Step2TemplateResult,
    *,
    stage_timers: dict[str, float] | None = None,
    use_reachable_support_cache: bool = True,
) -> Step3CaseResult:
    if not template_result.supported:
        return _status_for_unsupported_template(context, template_result)

    input_gate = {
        "passed": context.representative_node.has_evd == "yes" and context.representative_node.is_anchor in {None, "no"},
        "reason": None,
        "has_evd": context.representative_node.has_evd,
        "is_anchor": context.representative_node.is_anchor,
    }
    if not input_gate["passed"]:
        input_gate["reason"] = "input_gate_failed"
        return _status_for_input_gate_failure(context, template_result, input_gate=input_gate)

    reachable_support_case_cache = (
        _ReachableRoadSupportCaseCache()
        if use_reachable_support_cache
        else None
    )
    reference_target_geometry, target_edge_touch_fields = _target_component_touch_reference(context, template_result)
    base_allowed_road_ids: set[str] | None = None
    excluded_opposite_road_ids: set[str] = set()
    excluded_opposite_rc_road_ids: set[str] = set()
    excluded_opposite_rc_node_ids: set[str] = set()
    review_signals: list[str] = []
    opposite_side_guard_mode = "not_applicable"
    corridor_guard_status = "not_applicable"
    opposite_side_guard_note: str | None = None
    single_sided_direction_resolution = _single_sided_direction_resolution_fields()
    rcsd_opposite_fallback = _rcsd_opposite_fallback_fields()
    shared_two_in_two_out = _detect_shared_two_in_two_out_node(context)
    shared_through_node_ids = (
        {shared_two_in_two_out["node_id"]}
        if template_result.template_class == "single_sided_t_mouth"
        and shared_two_in_two_out["detected"]
        and shared_two_in_two_out["as_through_node"]
        and shared_two_in_two_out["node_id"] is not None
        else set()
    )
    bridge_protection_geometry, _bridge_preview_fields = _build_two_node_t_bridge_support(
        context,
        blocker_geometry=None,
    )
    rcsd_semantic_bridge_protection_geometry, rcsd_semantic_bridge_records = _build_rcsd_semantic_bridge_support(
        context,
        blocker_geometry=None,
    )
    bridge_protection_geometry = _extract_polygon_geometry(
        unary_union(
            [
                geometry
                for geometry in (bridge_protection_geometry, rcsd_semantic_bridge_protection_geometry)
                if geometry is not None
            ]
        )
    )
    branch_frontier_road_ids, junction_related_road_ids, adjacent_seed_records = _build_branch_frontier(
        context,
        through_node_ids=shared_through_node_ids,
    )
    adjacent_group_ids = {record["group_id"] for record in adjacent_seed_records}
    protected_group_ids = set(adjacent_group_ids)
    protected_group_ids.update(shared_through_node_ids)
    base_allowed_road_ids = set(branch_frontier_road_ids)

    if template_result.template_class == "single_sided_t_mouth":
        (
            single_sided_allowed_road_ids,
            excluded_opposite_road_ids,
            ambiguous,
            direction,
            single_sided_direction_resolution_raw,
        ) = _build_candidate_roads_for_single_sided(
            context,
            protected_road_ids=junction_related_road_ids,
        )
        single_sided_direction_resolution = _single_sided_direction_resolution_fields(
            single_sided_direction_resolution_raw
        )
        base_allowed_road_ids &= single_sided_allowed_road_ids
        candidate_opposite_rc_road_ids, candidate_opposite_rc_node_ids = _build_single_sided_exclusions(
            context,
            direction,
            protected_node_ids={node.node_id for node in context.target_group.nodes},
        )
        excluded_opposite_rc_road_ids, rcsd_opposite_fallback_raw = _filter_opposite_rc_road_ids(
            context,
            excluded_opposite_road_ids=excluded_opposite_road_ids,
            candidate_rc_road_ids=candidate_opposite_rc_road_ids,
            protected_road_ids=junction_related_road_ids,
            forward_direction=direction,
            horizontal_pair_detected=single_sided_direction_resolution["single_sided_horizontal_pair_detected"],
        )
        rcsd_opposite_fallback = _rcsd_opposite_fallback_fields(rcsd_opposite_fallback_raw)
        excluded_opposite_rc_node_ids = _filter_opposite_rc_node_ids(
            context,
            excluded_opposite_road_ids=excluded_opposite_road_ids,
            filtered_rc_road_ids=excluded_opposite_rc_road_ids,
            candidate_rc_node_ids=candidate_opposite_rc_node_ids,
        )
        opposite_side_guard_mode = "proxy_baseline"
        corridor_guard_status = (
            "hard_blocked_by_rcsdroad_mask" if excluded_opposite_rc_road_ids else "not_applicable"
        )
        opposite_side_guard_note = "road/semantic-node guard applied; near-corridor fallback only when SWSD opposite is missing."
        if ambiguous:
            review_signals.append("single_sided_direction_ambiguous")

    negative_masks_started_perf = perf_counter()
    adjacent_geometry, adjacent_records, adjacent_suppressed_records, adjacent_cut_road_ids = _build_adjacent_junction_masks(
        context,
        adjacent_records=adjacent_seed_records,
        additional_protection_geometry=bridge_protection_geometry,
    )
    foreign_mst_geometry, foreign_mst_records = _build_foreign_mst_masks(context)
    e_geometry, e_records, blocked_directions = _build_single_sided_blockers(
        context,
        excluded_opposite_road_ids=excluded_opposite_road_ids,
        excluded_opposite_rc_road_ids=excluded_opposite_rc_road_ids,
        excluded_opposite_rc_node_ids=excluded_opposite_rc_node_ids,
    )
    pre_blocker_union = _clean_geometry(
        unary_union([geometry for geometry in (adjacent_geometry, foreign_mst_geometry, e_geometry) if geometry is not None])
    )
    _accumulate_step3_stage_timer(
        stage_timers,
        "step3_negative_masks",
        perf_counter() - negative_masks_started_perf,
    )
    reachable_support_started_perf = perf_counter()
    pre_candidate_support, _pre_growth_limits, frontier_candidate_road_ids, _pre_frontier_stop_reason = _build_reachable_road_support(
        context,
        allowed_road_ids=base_allowed_road_ids,
        blocker_geometry=pre_blocker_union,
        force_bidirectional_road_ids=branch_frontier_road_ids,
        case_cache=reachable_support_case_cache,
    )
    _accumulate_step3_stage_timer(
        stage_timers,
        "step3_reachable_support",
        perf_counter() - reachable_support_started_perf,
    )
    negative_masks_started_perf = perf_counter()
    b_geometry, b_records, node_fallback_used = _build_foreign_object_masks(
        context,
        frontier_candidate_road_ids=frontier_candidate_road_ids,
        adjacent_cut_road_ids=adjacent_cut_road_ids,
        excluded_road_ids=excluded_opposite_road_ids,
        excluded_node_ids=excluded_opposite_rc_node_ids,
        protected_road_ids=junction_related_road_ids,
        protected_group_ids=protected_group_ids,
    )
    foreign_object_geometry = _clean_geometry(unary_union([geometry for geometry in (e_geometry, b_geometry) if geometry is not None]))
    foreign_object_records = [*e_records, *b_records]
    blocker_union = _clean_geometry(
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
    _accumulate_step3_stage_timer(
        stage_timers,
        "step3_negative_masks",
        perf_counter() - negative_masks_started_perf,
    )

    reachable_support_started_perf = perf_counter()
    hard_candidate_support_geometry, growth_limits, selected_road_ids, frontier_stop_reason = _build_reachable_road_support(
        context,
        allowed_road_ids=base_allowed_road_ids,
        blocker_geometry=blocker_union,
        force_bidirectional_road_ids=branch_frontier_road_ids,
        case_cache=reachable_support_case_cache,
    )
    _accumulate_step3_stage_timer(
        stage_timers,
        "step3_reachable_support",
        perf_counter() - reachable_support_started_perf,
    )
    bridge_hard_support, bridge_hard_fields = _build_two_node_t_bridge_support(
        context,
        blocker_geometry=blocker_union,
    )
    rcsd_semantic_bridge_hard_support, rcsd_semantic_bridge_hard_records = _build_rcsd_semantic_bridge_support(
        context,
        blocker_geometry=blocker_union,
    )
    hard_candidate_parts = [
        geometry
        for geometry in (
            hard_candidate_support_geometry,
            bridge_hard_support,
            rcsd_semantic_bridge_hard_support,
        )
        if geometry is not None
    ]
    hard_candidate_with_bridge = _extract_polygon_geometry(unary_union(hard_candidate_parts)) if hard_candidate_parts else None

    hard_path_validation_started_perf = perf_counter()
    hard_path_geometry = _component_touching_target(hard_candidate_with_bridge, reference_target_geometry)
    drivezone_metrics = _drivezone_containment_metrics(hard_path_geometry, context.drivezone_geometry)
    hard_intrusion = _has_negative_intrusion(hard_path_geometry, blocker_union)
    covered_node_ids = _covered_node_ids(
        context,
        hard_path_geometry,
        selected_road_ids=selected_road_ids,
    )
    target_node_ids = [node.node_id for node in context.target_group.nodes]
    missing_node_ids = [node_id for node_id in target_node_ids if node_id not in covered_node_ids]
    _accumulate_step3_stage_timer(
        stage_timers,
        "step3_hard_path_validation",
        perf_counter() - hard_path_validation_started_perf,
    )

    cleanup_preview_started_perf = perf_counter()
    cleanup_preview_source_geometry, _preview_growth_limits, _preview_selected_road_ids, _preview_frontier_stop_reason = _build_reachable_road_support(
        context,
        allowed_road_ids=base_allowed_road_ids,
        blocker_geometry=None,
        force_bidirectional_road_ids=branch_frontier_road_ids,
        case_cache=reachable_support_case_cache,
    )
    cleanup_preview_parts = [
        geometry
        for geometry in (
            cleanup_preview_source_geometry,
            bridge_protection_geometry,
            rcsd_semantic_bridge_protection_geometry,
        )
        if geometry is not None
    ]
    cleanup_preview_geometry = _extract_polygon_geometry(unary_union(cleanup_preview_parts)) if cleanup_preview_parts else None
    if cleanup_preview_geometry is not None and blocker_union is not None:
        cleanup_preview_geometry = _clean_geometry(cleanup_preview_geometry.difference(blocker_union))
    cleanup_preview_geometry = _component_touching_target(cleanup_preview_geometry, reference_target_geometry)
    cleanup_preview_drivezone_metrics = _drivezone_containment_metrics(cleanup_preview_geometry, context.drivezone_geometry)
    cleanup_preview_intrusion = _has_negative_intrusion(cleanup_preview_geometry, blocker_union)
    cleanup_preview_covered_node_ids = _covered_node_ids(
        context,
        cleanup_preview_geometry,
        selected_road_ids=_preview_selected_road_ids,
    )
    cleanup_preview_missing_node_ids = [
        node_id
        for node_id in target_node_ids
        if node_id not in cleanup_preview_covered_node_ids
    ]
    _accumulate_step3_stage_timer(
        stage_timers,
        "step3_cleanup_preview",
        perf_counter() - cleanup_preview_started_perf,
    )

    hard_path_passed = (
        hard_path_geometry is not None
        and drivezone_metrics["drivezone_containment_passed"]
        and not hard_intrusion
        and not missing_node_ids
    )
    cleanup_preview_passed = (
        cleanup_preview_geometry is not None
        and cleanup_preview_drivezone_metrics["drivezone_containment_passed"]
        and not cleanup_preview_intrusion
        and not cleanup_preview_missing_node_ids
    )
    rule_d_fallback_fields = _rule_d_fallback_fields(growth_limits=growth_limits)
    rule_a_protection_fields = _rule_a_target_core_protection_fields(adjacent_suppressed_records)
    shared_two_in_two_out_fields = _shared_two_in_two_out_closeout_fields(shared_two_in_two_out)
    cleanup_dependency = (not hard_path_passed) and cleanup_preview_passed
    opposite_side_intrusion = bool(selected_road_ids & excluded_opposite_road_ids)
    e_intrusion = _has_negative_intrusion(hard_path_geometry, e_geometry)
    reason = "step3_established"
    step3_state = "established"
    if cleanup_dependency:
        step3_state = "not_established"
        reason = "cleanup_dependency_required"
    elif hard_path_geometry is None:
        step3_state = "not_established"
        reason = "allowed_space_empty"
    elif not drivezone_metrics["drivezone_containment_passed"]:
        step3_state = "not_established"
        reason = "outside_drivezone_intrusion"
    elif missing_node_ids:
        step3_state = "not_established"
        reason = "must_cover_failed"
    elif opposite_side_intrusion or e_intrusion:
        step3_state = "not_established"
        reason = "single_sided_opposite_side_intrusion"
    elif hard_intrusion:
        step3_state = "not_established"
        reason = "negative_mask_intrusion"
    elif review_signals:
        step3_state = "review"
        reason = review_signals[0]

    blocked_direction_reasons = sorted({item["reason"] for item in blocked_directions})
    rules = {
        "A": {
            "passed": True,
            "count": len(adjacent_records),
            **rule_a_protection_fields,
        },
        "B": {"passed": True, "count": len(b_records), "node_fallback_used": node_fallback_used},
        "C": {"passed": True, "count": len(foreign_mst_records)},
        "D": {
            "passed": (
                hard_path_geometry is not None
                and drivezone_metrics["drivezone_containment_passed"]
                and not missing_node_ids
                and not opposite_side_intrusion
            ),
            "growth_limit_count": len(growth_limits),
            **rule_d_fallback_fields,
            "direction_mode": DIRECTION_MODE,
            **drivezone_metrics,
        },
        "E": {
            "passed": not opposite_side_intrusion and not e_intrusion,
            "blocked_count": len(blocked_directions),
            "template_only": template_result.template_class == "single_sided_t_mouth",
            "excluded_opposite_road_ids": sorted(excluded_opposite_road_ids),
            "excluded_opposite_rc_road_ids": sorted(excluded_opposite_rc_road_ids),
            "excluded_opposite_semantic_node_ids": sorted(excluded_opposite_rc_node_ids),
            "opposite_side_guard_mode": opposite_side_guard_mode,
            "corridor_guard_status": corridor_guard_status,
            "opposite_side_guard_note": opposite_side_guard_note,
            **rcsd_opposite_fallback,
        },
        "F": {
            "passed": not cleanup_dependency,
            "hard_path_passed": hard_path_passed,
            "cleanup_preview_passed": cleanup_preview_passed,
            "rescue_reason": "post_difference_preview_only" if cleanup_dependency else None,
        },
        "G": {
            "passed": not cleanup_dependency,
            "growth_after_hard_bounds_only": True,
            "growth_order": "hard_bound_first",
            "post_growth_safety_only": True,
        },
        "H": {"passed": True, "distance_cap_m": STEP3_DISTANCE_CAP_M},
    }
    audit_doc = {
        "input_gate": input_gate,
        "rules": rules,
        **multipart_road_handling_fields(context.roads, context.rcsd_roads),
        "adjacent_junction_cuts": adjacent_records,
        "adjacent_junction_cut_suppressed": adjacent_suppressed_records,
        "foreign_object_masks": foreign_object_records,
        "foreign_mst_masks": foreign_mst_records,
        "rcsd_semantic_bridge_records": rcsd_semantic_bridge_hard_records,
        "growth_limits": growth_limits,
        **rule_d_fallback_fields,
        "cleanup_dependency": cleanup_dependency,
        "must_cover_result": {
            "covered_node_ids": covered_node_ids,
            "missing_node_ids": missing_node_ids,
            "cleanup_preview_covered_node_ids": cleanup_preview_covered_node_ids,
            "cleanup_preview_missing_node_ids": cleanup_preview_missing_node_ids,
        },
        "blocked_directions": blocked_directions,
        "review_signals": review_signals,
        "direction_mode": DIRECTION_MODE,
        "growth_order": "hard_bound_first",
        "hard_bound_first": True,
        "post_growth_safety_only": True,
        "frontier_stop_reason": frontier_stop_reason,
        "selected_road_ids": sorted(selected_road_ids),
        "excluded_road_ids": sorted(excluded_opposite_road_ids),
        "opposite_road_ids": sorted(excluded_opposite_road_ids),
        "opposite_semantic_node_ids": sorted(excluded_opposite_rc_node_ids),
        "opposite_rcsdroad_ids": sorted(excluded_opposite_rc_road_ids),
        "opposite_side_guard_mode": opposite_side_guard_mode,
        "corridor_guard_status": corridor_guard_status,
        "opposite_side_guard_note": opposite_side_guard_note,
        **rcsd_opposite_fallback,
        **single_sided_direction_resolution,
        **target_edge_touch_fields,
        "hard_path_passed": hard_path_passed,
        "cleanup_preview_passed": cleanup_preview_passed,
        "rescue_reason": "post_difference_preview_only" if cleanup_dependency else None,
        "adjacent_junction_cut_protection_applied": rule_a_protection_fields["target_core_protection_applied"],
        "adjacent_junction_cut_protection_reason": rule_a_protection_fields["target_core_protection_reason"],
        **bridge_hard_fields,
        "rcsd_semantic_bridge_applied": bool(rcsd_semantic_bridge_hard_records),
        "rcsd_semantic_bridge_count": len(rcsd_semantic_bridge_hard_records),
        "rcsd_semantic_bridge_max_target_distance_m": RCSD_SEMANTIC_BRIDGE_MAX_TARGET_DISTANCE_M,
        **shared_two_in_two_out_fields,
        **drivezone_metrics,
    }
    key_metrics = {
        "target_group_node_count": len(context.target_group.nodes),
        "selected_road_count": len(selected_road_ids),
        "excluded_road_count": len(excluded_opposite_road_ids),
        "adjacent_cut_count": len(adjacent_records),
        "foreign_object_mask_count": len(foreign_object_records),
        "foreign_mst_mask_count": len(foreign_mst_records),
        "review_signal_count": len(review_signals),
        "cleanup_dependency": cleanup_dependency,
        "blocked_direction_count": len(blocked_directions),
        "rule_d_fallback_applied": rule_d_fallback_fields["rule_d_fallback_applied"],
        "rcsd_opposite_fallback_enabled": rcsd_opposite_fallback["rcsd_opposite_fallback_enabled"],
        "two_node_t_bridge_applied": bridge_hard_fields["two_node_t_bridge_applied"],
        "shared_two_in_two_out_as_through_node": shared_two_in_two_out_fields["shared_two_in_two_out_as_through_node"],
        "single_sided_horizontal_pair_detected": single_sided_direction_resolution["single_sided_horizontal_pair_detected"],
        "target_edge_touch_enabled": target_edge_touch_fields["target_edge_touch_enabled"],
        **drivezone_metrics,
    }
    visual_review_class = _review_visual_class(step3_state, review_signals, reason)
    return Step3CaseResult(
        case_id=context.case_spec.case_id,
        template_class=template_result.template_class,
        step3_state=step3_state,
        step3_established=step3_state == "established",
        reason=reason,
        visual_review_class=visual_review_class,
        root_cause_layer=_root_cause_layer(step3_state),
        root_cause_type=None if step3_state == "established" else reason,
        allowed_space_geometry=hard_path_geometry,
        allowed_drivezone_geometry=hard_candidate_with_bridge,
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
            "representative_node_id": context.representative_node.node_id,
            "target_group_node_ids": target_node_ids,
            "foreign_group_ids": [group.group_id for group in context.foreign_groups],
            "selected_road_ids": sorted(selected_road_ids),
            "excluded_road_ids": sorted(excluded_opposite_road_ids),
            "blocked_direction_reasons": blocked_direction_reasons,
            "cleanup_dependency": cleanup_dependency,
            "direction_mode": DIRECTION_MODE,
            **rule_d_fallback_fields,
            **bridge_hard_fields,
            "rcsd_semantic_bridge_applied": bool(rcsd_semantic_bridge_hard_records),
            "rcsd_semantic_bridge_count": len(rcsd_semantic_bridge_hard_records),
            "rcsd_semantic_bridge_max_target_distance_m": RCSD_SEMANTIC_BRIDGE_MAX_TARGET_DISTANCE_M,
            **shared_two_in_two_out_fields,
            **single_sided_direction_resolution,
            **target_edge_touch_fields,
            **rcsd_opposite_fallback,
            **drivezone_metrics,
            "visual_review_class": visual_review_class,
            "root_cause_layer": _root_cause_layer(step3_state),
            "root_cause_type": None if step3_state == "established" else reason,
        },
    )

def build_step3_status_doc(case_result: Step3CaseResult) -> dict[str, Any]:
    return _build_status_doc(case_result)
