from __future__ import annotations

from collections import defaultdict
from typing import Any

from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge, substring

from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, normalize_id, parse_id_list, parse_positive_int, unique_preserve_order
from .road_attributes import is_advance_right_turn_road
from .schemas import feature
from .step3_endpoint_nodes import post_advance_road_crosses_retained_swsd


INHERITED_NODE_FIELDS = ["kind", "grade", "kind_2", "grade_2", "closed_con"]
ADVANCE_RIGHT_FORMWAY_BIT = 128
GENERATED_NODE_RELATION_MAINNODE_MAX_GAP_M = 10.0
GENERATED_NODE_ROAD_ENDPOINT_MAINNODE_MAX_DISTANCE_M = 6.0
RETAINED_SWSD_ATTACHMENT_MAX_GAP_M = 20.0
RETAINED_SWSD_MAPPED_NODE_MAX_GAP_M = 26.0
RETAINED_SWSD_SEMANTIC_NODE_MAX_GAP_M = 80.0
NON_ADVANCE_ROAD_PREFERENCE_MAX_EXTRA_GAP_M = 1.0
ADVANCE_RIGHT_SPLIT_POINT_DEDUPE_M = 1.0
RIGHT_ATTACH_AUDIT_STEM = "t06_step3_advance_right_attachment_audit"
RIGHT_ATTACH_AUDIT_FIELDS = [
    "junction_c_ids",
    "swsd_advance_road_id",
    "swsd_node_id",
    "retained_in_frcsd",
    "action",
    "action_reason",
    "swsd_node_mainnodeid_before",
    "swsd_node_mainnodeid_after",
    "rcsd_road_id",
    "rcsd_node_id",
    "generated_rcsd_node_id",
    "projected_gap_m",
    "replacement_segment_ids",
]


def apply_junction_advance_right_contract(
    units: list[Any],
    *,
    swsd_segments: list[dict[str, Any]],
    swsd_roads: list[dict[str, Any]],
    swsd_node_by_id: dict[str, dict[str, Any]],
    rcsd_roads: list[dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    retained_swsd_roads: list[dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
) -> dict[str, Any]:
    stats = _empty_contract_stats()
    passed_units = [unit for unit in units if getattr(unit, "status", "") == "passed"]
    if not passed_units:
        return stats

    units_by_c = _units_by_junction(passed_units)
    direct_node_contexts = _swsd_attachment_node_contexts(swsd_segments, set(units_by_c))
    node_contexts = _augment_swsd_attachment_node_contexts_from_incident_roads(
        direct_node_contexts,
        swsd_segments=swsd_segments,
        swsd_roads=swsd_roads,
        replacement_c_ids=set(units_by_c),
    )
    if not node_contexts:
        return stats

    retained_swsd_road_by_id = _index_by_id(retained_swsd_roads)
    retained_swsd_node_to_roads = _node_to_road_ids(retained_swsd_roads)
    retained_swsd_endpoint_ids = set(retained_swsd_node_to_roads)
    split_points_by_road: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)
    generated_nodes_by_id: dict[str, str] = {}
    generated_nodes_by_projection: dict[str, list[tuple[float, str]]] = defaultdict(list)
    next_node_id = _next_numeric_id(rcsd_node_by_id)

    for road in swsd_roads:
        if not _is_advance_right_swsd_road(road):
            continue
        road_id = _feature_id(road)
        endpoint_ids = _road_endpoint_node_ids(road)
        endpoint_points = _road_endpoint_points(road)
        endpoint_contexts = {
            node_id: node_contexts[node_id]
            for node_id in endpoint_ids
            if node_id in node_contexts
        }
        if not endpoint_contexts:
            continue
        stats["candidate_road_count"] += 1
        props = dict(road.get("properties") or {})
        road_segment_ids = _parse_list(props.get("segmentid") or props.get("segment_id") or props.get("swsd_segment_id"))
        retained_in_frcsd = road_id in retained_swsd_road_by_id
        if retained_in_frcsd:
            stats["retained_candidate_road_count"] += 1
        for node_id, point in zip(endpoint_ids, endpoint_points):
            c_ids = endpoint_contexts.get(node_id)
            if not c_ids:
                continue
            stats["candidate_endpoint_count"] += 1
            mainnode_before = _node_mainnodeid_text(swsd_node_by_id.get(node_id))
            if node_id in retained_swsd_endpoint_ids and _normalize_missing_swsd_mainnode(node_id, swsd_node_by_id.get(node_id)):
                stats["swsd_mainnode_normalized_node_count"] += 1
                stats["audit_rows"].append(
                    _contract_audit_row(
                        c_ids=c_ids,
                        road_id=road_id,
                        node_id=node_id,
                        retained_in_frcsd=retained_in_frcsd,
                        action="normalize_swsd_singleton_mainnode",
                        reason="advance_right_attachment_node_missing_mainnodeid",
                        mainnode_before=mainnode_before,
                        mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                        geometry=point,
                    )
                )
            if not retained_in_frcsd:
                stats["audit_rows"].append(
                    _contract_audit_row(
                        c_ids=c_ids,
                        road_id=road_id,
                        node_id=node_id,
                        retained_in_frcsd=False,
                        action="audit_removed_swsd_advance_endpoint",
                        reason="swsd_advance_removed_or_deduplicated_but_endpoint_retained",
                        mainnode_before=mainnode_before,
                        mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                        geometry=point,
                    )
                )
                continue
            context_units = _context_units(c_ids, units_by_c)
            selected_rcsd_road_ids = _selected_rcsd_road_ids(context_units, added_road_to_segments, rcsd_road_by_id)
            max_gap_m = 1.0 if road_segment_ids and node_id in direct_node_contexts else RETAINED_SWSD_ATTACHMENT_MAX_GAP_M
            match = _nearest_selected_rcsd_projection(
                point,
                selected_rcsd_road_ids=selected_rcsd_road_ids,
                rcsd_road_by_id=rcsd_road_by_id,
                max_gap_m=max_gap_m,
            )
            if match is None:
                mapped_node_match = _nearest_mapped_rcsd_node_projection(
                    node_id,
                    point,
                    context_units=context_units,
                    rcsd_node_by_id=rcsd_node_by_id,
                    max_gap_m=RETAINED_SWSD_SEMANTIC_NODE_MAX_GAP_M,
                )
                if mapped_node_match is not None:
                    rcsd_node_id, projected, gap_m = mapped_node_match
                    if _has_incident_rcsd_road_in_mainnode_group(
                        rcsd_node_id,
                        rcsd_road_by_id=rcsd_road_by_id,
                        rcsd_node_by_id=rcsd_node_by_id,
                        allowed_road_ids=set(added_road_to_segments),
                        excluded_road_ids=set(retained_swsd_road_by_id),
                    ):
                        _snap_retained_swsd_node_to_point(
                            node_id,
                            projected,
                            swsd_node_by_id=swsd_node_by_id,
                            retained_swsd_road_by_id=retained_swsd_road_by_id,
                            retained_swsd_node_to_roads=retained_swsd_node_to_roads,
                        )
                        stats["swsd_node_snapped_count"] += 1
                        for unit in context_units:
                            unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, rcsd_node_id])
                        stats["rcsd_endpoint_reused_count"] += 1
                        stats["audit_rows"].append(
                            _contract_audit_row(
                                c_ids=c_ids,
                                road_id=road_id,
                                node_id=node_id,
                                retained_in_frcsd=True,
                                action="reuse_existing_rcsd_node_for_swsd_advance",
                                reason="advance_right_endpoint_near_mapped_rcsd_node",
                                mainnode_before=mainnode_before,
                                mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                                rcsd_node_id=rcsd_node_id,
                                gap_m=gap_m,
                                replacement_segment_ids=_unit_segment_ids(context_units),
                                geometry=projected,
                            )
                        )
                        continue
                match = _nearest_preferred_rcsd_projection(
                    point,
                    selected_rcsd_road_ids=_global_added_rcsd_road_ids(
                        added_road_to_segments=added_road_to_segments,
                        rcsd_road_by_id=rcsd_road_by_id,
                        excluded_road_ids=set(retained_swsd_road_by_id),
                    ),
                    rcsd_road_by_id=rcsd_road_by_id,
                    max_gap_m=max_gap_m,
                )
            if match is None:
                stats["audit_rows"].append(
                    _contract_audit_row(
                        c_ids=c_ids,
                        road_id=road_id,
                        node_id=node_id,
                        retained_in_frcsd=True,
                        action="audit_no_safe_rcsd_projection",
                        reason=f"no_connected_rcsd_road_within_{max_gap_m:g}m",
                        mainnode_before=mainnode_before,
                        mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                        geometry=point,
                    )
                )
                continue
            rcsd_road_id, distance_m, projected, endpoint_node_id = match
            gap_m = round(float(point.distance(projected)), 3)
            _snap_retained_swsd_node_to_point(
                node_id,
                projected,
                swsd_node_by_id=swsd_node_by_id,
                retained_swsd_road_by_id=retained_swsd_road_by_id,
                retained_swsd_node_to_roads=retained_swsd_node_to_roads,
            )
            stats["swsd_node_snapped_count"] += 1
            if endpoint_node_id is not None:
                for unit in context_units:
                    unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, endpoint_node_id])
                stats["rcsd_endpoint_reused_count"] += 1
                stats["audit_rows"].append(
                    _contract_audit_row(
                        c_ids=c_ids,
                        road_id=road_id,
                        node_id=node_id,
                        retained_in_frcsd=True,
                        action="reuse_existing_rcsd_endpoint_node",
                        reason="advance_right_projection_near_selected_rcsd_endpoint",
                        mainnode_before=mainnode_before,
                        mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                        rcsd_road_id=rcsd_road_id,
                        rcsd_node_id=endpoint_node_id,
                        gap_m=gap_m,
                        replacement_segment_ids=_unit_segment_ids(context_units),
                        geometry=projected,
                    )
                )
                continue
            reusable_node_id = _nearby_generated_projection_node_id(
                generated_nodes_by_projection[rcsd_road_id],
                distance_m,
            )
            if reusable_node_id is not None:
                generated_node_id = reusable_node_id
            else:
                node_value = next_node_id if next_node_id is not None else f"t06_advnode_{stats['rcsd_node_generated_count'] + 1}"
                if next_node_id is not None:
                    next_node_id += 1
                generated_node_id = _safe_normalize(node_value)
                if generated_node_id not in rcsd_node_by_id:
                    relation_mainnode_id = _generated_node_mainnode_id(
                        node_id,
                        projected,
                        context_units=context_units,
                        rcsd_road_id=rcsd_road_id,
                        distance_m=distance_m,
                        rcsd_road_by_id=rcsd_road_by_id,
                        rcsd_node_by_id=rcsd_node_by_id,
                    )
                    node = _new_post_advance_rcsd_node(
                        node_value=node_value,
                        geometry=projected,
                        rcsd_node_by_id=rcsd_node_by_id,
                        swsd_node=swsd_node_by_id.get(node_id),
                        relation_mainnode_id=relation_mainnode_id,
                    )
                    rcsd_nodes.append(node)
                    rcsd_node_by_id[generated_node_id] = node
                    stats["rcsd_node_generated_count"] += 1
                generated_nodes_by_projection[rcsd_road_id].append((distance_m, generated_node_id))
            generated_nodes_by_id[generated_node_id] = road_id
            split_points_by_road[rcsd_road_id][generated_node_id] = (distance_m, generated_node_id)
            for unit in context_units:
                unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, generated_node_id])
            stats["audit_rows"].append(
                _contract_audit_row(
                    c_ids=c_ids,
                    road_id=road_id,
                    node_id=node_id,
                    retained_in_frcsd=True,
                    action="split_rcsd_road_for_swsd_advance",
                    reason="advance_right_projection_mid_selected_rcsd_road",
                    mainnode_before=mainnode_before,
                    mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                    rcsd_road_id=rcsd_road_id,
                    generated_node_id=generated_node_id,
                    gap_m=gap_m,
                    replacement_segment_ids=_unit_segment_ids(context_units),
                    geometry=projected,
                )
            )

    split_stats = _apply_contract_split_points(
        units,
        split_points_by_road=split_points_by_road,
        rcsd_roads=rcsd_roads,
        rcsd_road_by_id=rcsd_road_by_id,
        added_road_to_segments=added_road_to_segments,
    )
    stats.update(split_stats)
    return stats


def apply_retained_swsd_segment_attachment_contract(
    units: list[Any],
    *,
    swsd_segments: list[dict[str, Any]],
    swsd_roads: list[dict[str, Any]],
    swsd_node_by_id: dict[str, dict[str, Any]],
    rcsd_roads: list[dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    retained_swsd_roads: list[dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
    max_gap_m: float = RETAINED_SWSD_ATTACHMENT_MAX_GAP_M,
) -> dict[str, Any]:
    stats = _empty_contract_stats()
    # Retained non-advance SWSD roads must stay as original SWSD geometry/topology.
    # Advance-right migration is handled by apply_junction_advance_right_contract.
    return stats

    passed_units = [unit for unit in units if getattr(unit, "status", "") == "passed"]
    if not passed_units:
        return stats

    units_by_c = _units_by_junction(passed_units)
    node_contexts = {node_id: [node_id] for node_id in units_by_c}
    if not node_contexts:
        return stats

    retained_swsd_road_by_id = _index_by_id(retained_swsd_roads)
    retained_swsd_node_to_roads = _node_to_road_ids(retained_swsd_roads)
    split_points_by_road: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)
    generated_nodes_by_id: dict[str, str] = {}
    generated_node_by_swsd_node: dict[str, str] = {}
    generated_nodes_by_projection: dict[str, list[tuple[float, str]]] = defaultdict(list)
    next_node_id = _next_numeric_id(rcsd_node_by_id)

    for road in retained_swsd_roads:
        if _is_advance_right_swsd_road(road):
            continue
        road_id = _feature_id(road)
        if road_id not in retained_swsd_road_by_id:
            continue
        endpoint_ids = _road_endpoint_node_ids(road)
        endpoint_points = _road_endpoint_points(road)
        endpoint_contexts = {
            node_id: node_contexts[node_id]
            for node_id in endpoint_ids
            if node_id in node_contexts
        }
        if not endpoint_contexts:
            continue
        stats["candidate_road_count"] += 1
        stats["retained_candidate_road_count"] += 1
        for node_id, point in zip(endpoint_ids, endpoint_points):
            c_ids = endpoint_contexts.get(node_id)
            if not c_ids:
                continue
            stats["candidate_endpoint_count"] += 1
            mainnode_before = _node_mainnodeid_text(swsd_node_by_id.get(node_id))
            context_units = _context_units(c_ids, units_by_c)
            all_selected_rcsd_road_ids = _selected_rcsd_road_ids(context_units, added_road_to_segments, rcsd_road_by_id)
            match = _nearest_preferred_rcsd_projection(
                point,
                selected_rcsd_road_ids=all_selected_rcsd_road_ids,
                rcsd_road_by_id=rcsd_road_by_id,
                max_gap_m=max_gap_m,
            )
            if match is None:
                mapped_node_match = _nearest_mapped_rcsd_node_projection(
                    node_id,
                    point,
                    context_units=context_units,
                    rcsd_node_by_id=rcsd_node_by_id,
                    max_gap_m=RETAINED_SWSD_SEMANTIC_NODE_MAX_GAP_M,
                )
                if mapped_node_match is not None:
                    rcsd_node_id, projected, gap_m = mapped_node_match
                    if _has_incident_rcsd_road_in_mainnode_group(
                        rcsd_node_id,
                        rcsd_road_by_id=rcsd_road_by_id,
                        rcsd_node_by_id=rcsd_node_by_id,
                        allowed_road_ids=set(added_road_to_segments),
                        excluded_road_ids=set(retained_swsd_road_by_id),
                    ):
                        _snap_retained_swsd_node_to_point(
                            node_id,
                            projected,
                            swsd_node_by_id=swsd_node_by_id,
                            retained_swsd_road_by_id=retained_swsd_road_by_id,
                            retained_swsd_node_to_roads=retained_swsd_node_to_roads,
                        )
                        stats["swsd_node_snapped_count"] += 1
                        for unit in context_units:
                            unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, rcsd_node_id])
                        stats["rcsd_endpoint_reused_count"] += 1
                        action = "reuse_existing_rcsd_node_for_retained_swsd_segment"
                        reason = "retained_swsd_segment_endpoint_near_mapped_rcsd_node"
                        if gap_m > RETAINED_SWSD_MAPPED_NODE_MAX_GAP_M:
                            action = "reuse_semantic_rcsd_node_for_retained_swsd_segment"
                            reason = "retained_swsd_segment_endpoint_snapped_to_semantic_rcsd_node"
                        stats["audit_rows"].append(
                            _contract_audit_row(
                                c_ids=c_ids,
                                road_id=road_id,
                                node_id=node_id,
                                retained_in_frcsd=True,
                                action=action,
                                reason=reason,
                                mainnode_before=mainnode_before,
                                mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                                rcsd_node_id=rcsd_node_id,
                                gap_m=gap_m,
                                replacement_segment_ids=_unit_segment_ids(context_units),
                                geometry=projected,
                            )
                        )
                        continue
                match = _nearest_preferred_rcsd_projection(
                    point,
                    selected_rcsd_road_ids=_global_added_rcsd_road_ids(
                        added_road_to_segments=added_road_to_segments,
                        rcsd_road_by_id=rcsd_road_by_id,
                        excluded_road_ids=set(retained_swsd_road_by_id),
                    ),
                    rcsd_road_by_id=rcsd_road_by_id,
                    max_gap_m=max_gap_m,
                )
            if match is None:
                stats["audit_rows"].append(
                    _contract_audit_row(
                        c_ids=c_ids,
                        road_id=road_id,
                        node_id=node_id,
                        retained_in_frcsd=True,
                        action="audit_no_safe_rcsd_projection",
                        reason=f"no_connected_rcsd_road_within_{max_gap_m:g}m",
                        mainnode_before=mainnode_before,
                        mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                        geometry=point,
                    )
                )
                continue
            rcsd_road_id, distance_m, projected, endpoint_node_id = match
            gap_m = round(float(point.distance(projected)), 3)
            _snap_retained_swsd_node_to_point(
                node_id,
                projected,
                swsd_node_by_id=swsd_node_by_id,
                retained_swsd_road_by_id=retained_swsd_road_by_id,
                retained_swsd_node_to_roads=retained_swsd_node_to_roads,
            )
            stats["swsd_node_snapped_count"] += 1
            if endpoint_node_id is not None:
                for unit in context_units:
                    unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, endpoint_node_id])
                stats["rcsd_endpoint_reused_count"] += 1
                stats["audit_rows"].append(
                    _contract_audit_row(
                        c_ids=c_ids,
                        road_id=road_id,
                        node_id=node_id,
                        retained_in_frcsd=True,
                        action="reuse_existing_rcsd_endpoint_node_for_retained_swsd_segment",
                        reason="retained_swsd_segment_endpoint_near_selected_rcsd_endpoint",
                        mainnode_before=mainnode_before,
                        mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                        rcsd_road_id=rcsd_road_id,
                        rcsd_node_id=endpoint_node_id,
                        gap_m=gap_m,
                        replacement_segment_ids=_unit_segment_ids(context_units),
                        geometry=projected,
                    )
                )
                continue
            generated_node_id = generated_node_by_swsd_node.get(node_id)
            if generated_node_id is not None and generated_node_id in rcsd_node_by_id:
                relation_mainnode_id = _generated_node_mainnode_id(
                    node_id,
                    projected,
                    context_units=context_units,
                    rcsd_road_id=rcsd_road_id,
                    distance_m=distance_m,
                    rcsd_road_by_id=rcsd_road_by_id,
                    rcsd_node_by_id=rcsd_node_by_id,
                )
                _assign_generated_node_relation_mainnode(
                    generated_node_id,
                    relation_mainnode_id,
                    rcsd_node_by_id=rcsd_node_by_id,
                )
                split_points_by_road[rcsd_road_id][generated_node_id] = (distance_m, generated_node_id)
                for unit in context_units:
                    unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, generated_node_id])
                stats["audit_rows"].append(
                    _contract_audit_row(
                        c_ids=c_ids,
                        road_id=road_id,
                        node_id=node_id,
                        retained_in_frcsd=True,
                        action="reuse_generated_rcsd_node_for_retained_swsd_segment",
                        reason="retained_swsd_segment_endpoint_reuses_generated_rcsd_node",
                        mainnode_before=mainnode_before,
                        mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                        rcsd_road_id=rcsd_road_id,
                        generated_node_id=generated_node_id,
                        gap_m=gap_m,
                        replacement_segment_ids=_unit_segment_ids(context_units),
                        geometry=projected,
                    )
                )
                continue
            reusable_node_id = _nearby_generated_projection_node_id(
                generated_nodes_by_projection[rcsd_road_id],
                distance_m,
            )
            if reusable_node_id is not None:
                generated_node_id = reusable_node_id
            else:
                node_value = next_node_id if next_node_id is not None else f"t06_retnode_{stats['rcsd_node_generated_count'] + 1}"
                if next_node_id is not None:
                    next_node_id += 1
                generated_node_id = _safe_normalize(node_value)
                if generated_node_id not in rcsd_node_by_id:
                    relation_mainnode_id = _generated_node_mainnode_id(
                        node_id,
                        projected,
                        context_units=context_units,
                        rcsd_road_id=rcsd_road_id,
                        distance_m=distance_m,
                        rcsd_road_by_id=rcsd_road_by_id,
                        rcsd_node_by_id=rcsd_node_by_id,
                    )
                    node = _new_post_advance_rcsd_node(
                        node_value=node_value,
                        geometry=projected,
                        rcsd_node_by_id=rcsd_node_by_id,
                        swsd_node=swsd_node_by_id.get(node_id),
                        relation_mainnode_id=relation_mainnode_id,
                    )
                    rcsd_nodes.append(node)
                    rcsd_node_by_id[generated_node_id] = node
                    stats["rcsd_node_generated_count"] += 1
                generated_nodes_by_projection[rcsd_road_id].append((distance_m, generated_node_id))
            generated_nodes_by_id[generated_node_id] = road_id
            generated_node_by_swsd_node[node_id] = generated_node_id
            split_points_by_road[rcsd_road_id][generated_node_id] = (distance_m, generated_node_id)
            for unit in context_units:
                unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, generated_node_id])
            stats["audit_rows"].append(
                _contract_audit_row(
                    c_ids=c_ids,
                    road_id=road_id,
                    node_id=node_id,
                    retained_in_frcsd=True,
                    action="split_rcsd_road_for_retained_swsd_segment",
                    reason="retained_swsd_segment_endpoint_projects_to_mid_selected_rcsd_road",
                    mainnode_before=mainnode_before,
                    mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                    rcsd_road_id=rcsd_road_id,
                    generated_node_id=generated_node_id,
                    gap_m=gap_m,
                    replacement_segment_ids=_unit_segment_ids(context_units),
                    geometry=projected,
                )
            )

    attached_swsd_node_ids = {
        _safe_normalize((row.get("properties") or {}).get("swsd_node_id"))
        for row in stats["audit_rows"]
        if str((row.get("properties") or {}).get("action") or "").startswith(("split_", "reuse_"))
    }
    for node_id, c_ids in _detached_semantic_node_contexts(passed_units).items():
        if (
            node_id in retained_swsd_node_to_roads
            or node_id in generated_node_by_swsd_node
            or node_id in attached_swsd_node_ids
        ):
            continue
        point = _feature_point(swsd_node_by_id.get(node_id))
        if point is None:
            continue
        stats["candidate_endpoint_count"] += 1
        mainnode_before = _node_mainnodeid_text(swsd_node_by_id.get(node_id))
        context_units = _context_units(c_ids, units_by_c)
        selected_rcsd_road_ids = _selected_rcsd_road_ids(context_units, added_road_to_segments, rcsd_road_by_id)
        match = _nearest_preferred_rcsd_projection(
            point,
            selected_rcsd_road_ids=selected_rcsd_road_ids,
            rcsd_road_by_id=rcsd_road_by_id,
            max_gap_m=max_gap_m,
        )
        if match is None:
            mapped_node_match = _nearest_mapped_rcsd_node_projection(
                node_id,
                point,
                context_units=context_units,
                rcsd_node_by_id=rcsd_node_by_id,
                max_gap_m=RETAINED_SWSD_SEMANTIC_NODE_MAX_GAP_M,
            )
            if mapped_node_match is not None:
                rcsd_node_id, projected, gap_m = mapped_node_match
                _snap_retained_swsd_node_to_point(
                    node_id,
                    projected,
                    swsd_node_by_id=swsd_node_by_id,
                    retained_swsd_road_by_id=retained_swsd_road_by_id,
                    retained_swsd_node_to_roads=retained_swsd_node_to_roads,
                )
                stats["swsd_node_snapped_count"] += 1
                for unit in context_units:
                    unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, rcsd_node_id])
                stats["rcsd_endpoint_reused_count"] += 1
                stats["audit_rows"].append(
                    _contract_audit_row(
                        c_ids=c_ids,
                        road_id="",
                        node_id=node_id,
                        retained_in_frcsd=False,
                        action="reuse_semantic_rcsd_node_for_detached_swsd_node",
                        reason="detached_swsd_semantic_node_snapped_to_peer_rcsd_node",
                        mainnode_before=mainnode_before,
                        mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                        rcsd_node_id=rcsd_node_id,
                        gap_m=gap_m,
                        replacement_segment_ids=_unit_segment_ids(context_units),
                        geometry=projected,
                    )
                )
                continue
            match = _nearest_preferred_rcsd_projection(
                point,
                selected_rcsd_road_ids=_global_added_rcsd_road_ids(
                    added_road_to_segments=added_road_to_segments,
                    rcsd_road_by_id=rcsd_road_by_id,
                    excluded_road_ids=set(retained_swsd_road_by_id),
                ),
                rcsd_road_by_id=rcsd_road_by_id,
                max_gap_m=max_gap_m,
            )
        if match is None:
            stats["audit_rows"].append(
                _contract_audit_row(
                    c_ids=c_ids,
                    road_id="",
                    node_id=node_id,
                    retained_in_frcsd=False,
                    action="audit_no_safe_rcsd_projection",
                    reason=f"no_connected_rcsd_road_within_{max_gap_m:g}m_for_detached_swsd_semantic_node",
                    mainnode_before=mainnode_before,
                    mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                    replacement_segment_ids=_unit_segment_ids(context_units),
                    geometry=point,
                )
            )
            continue
        rcsd_road_id, distance_m, projected, endpoint_node_id = match
        gap_m = round(float(point.distance(projected)), 3)
        _snap_retained_swsd_node_to_point(
            node_id,
            projected,
            swsd_node_by_id=swsd_node_by_id,
            retained_swsd_road_by_id=retained_swsd_road_by_id,
            retained_swsd_node_to_roads=retained_swsd_node_to_roads,
        )
        stats["swsd_node_snapped_count"] += 1
        if endpoint_node_id is not None:
            for unit in context_units:
                unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, endpoint_node_id])
            stats["rcsd_endpoint_reused_count"] += 1
            stats["audit_rows"].append(
                _contract_audit_row(
                    c_ids=c_ids,
                    road_id="",
                    node_id=node_id,
                    retained_in_frcsd=False,
                    action="reuse_existing_rcsd_endpoint_node_for_detached_swsd_node",
                    reason="detached_swsd_semantic_node_near_selected_rcsd_endpoint",
                    mainnode_before=mainnode_before,
                    mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                    rcsd_road_id=rcsd_road_id,
                    rcsd_node_id=endpoint_node_id,
                    gap_m=gap_m,
                    replacement_segment_ids=_unit_segment_ids(context_units),
                    geometry=projected,
                )
            )
            continue
        node_value = next_node_id if next_node_id is not None else f"t06_retnode_{stats['rcsd_node_generated_count'] + 1}"
        if next_node_id is not None:
            next_node_id += 1
        generated_node_id = _safe_normalize(node_value)
        if generated_node_id not in rcsd_node_by_id:
            relation_mainnode_id = _generated_node_mainnode_id(
                node_id,
                projected,
                context_units=context_units,
                rcsd_road_id=rcsd_road_id,
                distance_m=distance_m,
                rcsd_road_by_id=rcsd_road_by_id,
                rcsd_node_by_id=rcsd_node_by_id,
            )
            node = _new_post_advance_rcsd_node(
                node_value=node_value,
                geometry=projected,
                rcsd_node_by_id=rcsd_node_by_id,
                swsd_node=swsd_node_by_id.get(node_id),
                relation_mainnode_id=relation_mainnode_id,
            )
            rcsd_nodes.append(node)
            rcsd_node_by_id[generated_node_id] = node
            stats["rcsd_node_generated_count"] += 1
        generated_node_by_swsd_node[node_id] = generated_node_id
        generated_nodes_by_projection[rcsd_road_id].append((distance_m, generated_node_id))
        split_points_by_road[rcsd_road_id][generated_node_id] = (distance_m, generated_node_id)
        for unit in context_units:
            unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, generated_node_id])
        stats["audit_rows"].append(
            _contract_audit_row(
                c_ids=c_ids,
                road_id="",
                node_id=node_id,
                retained_in_frcsd=False,
                action="split_rcsd_road_for_detached_swsd_node",
                reason="detached_swsd_semantic_node_projects_to_mid_selected_rcsd_road",
                mainnode_before=mainnode_before,
                mainnode_after=_node_mainnodeid_text(swsd_node_by_id.get(node_id)),
                rcsd_road_id=rcsd_road_id,
                generated_node_id=generated_node_id,
                gap_m=gap_m,
                replacement_segment_ids=_unit_segment_ids(context_units),
                geometry=projected,
            )
        )

    split_stats = _apply_contract_split_points(
        units,
        split_points_by_road=split_points_by_road,
        rcsd_roads=rcsd_roads,
        rcsd_road_by_id=rcsd_road_by_id,
        added_road_to_segments=added_road_to_segments,
    )
    stats.update(split_stats)
    return stats


def _empty_contract_stats() -> dict[str, Any]:
    return {
        "candidate_road_count": 0,
        "candidate_endpoint_count": 0,
        "retained_candidate_road_count": 0,
        "swsd_mainnode_normalized_node_count": 0,
        "swsd_node_snapped_count": 0,
        "rcsd_endpoint_reused_count": 0,
        "rcsd_node_generated_count": 0,
        "rcsd_split_original_road_count": 0,
        "rcsd_split_road_count": 0,
        "audit_rows": [],
    }


def _units_by_junction(units: list[Any]) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = defaultdict(list)
    for unit in units:
        for c_id in unique_preserve_order([*unit.pair_nodes, *unit.junc_nodes, *unit.detached_junc_nodes]):
            result[c_id].append(unit)
    return {key: _unique_units(value) for key, value in result.items()}


def _detached_semantic_node_contexts(units: list[Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        segment_id = str(getattr(unit, "segment_id", ""))
        if not segment_id:
            continue
        node_ids = list(getattr(unit, "detached_junc_nodes", []) or [])
        if getattr(unit, "retained_detached_swsd_road_ids", None):
            node_ids = unique_preserve_order(
                [*node_ids, *(getattr(unit, "junc_kind2_exempt_nodes", []) or [])]
            )
        for node_id in node_ids:
            result[str(node_id)] = unique_preserve_order([*result[str(node_id)], str(node_id)])
    return dict(result)


def _swsd_attachment_node_contexts(swsd_segments: list[dict[str, Any]], replacement_c_ids: set[str]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for segment in swsd_segments:
        props = dict(segment.get("properties") or {})
        segment_nodes = unique_preserve_order([*_parse_list(props.get("pair_nodes")), *_parse_list(props.get("junc_nodes"))])
        active_c_ids = [node_id for node_id in segment_nodes if node_id in replacement_c_ids]
        if not active_c_ids:
            continue
        for node_id in segment_nodes:
            result[node_id] = unique_preserve_order([*result[node_id], *active_c_ids])
    return dict(result)


def _augment_swsd_attachment_node_contexts_from_incident_roads(
    base_contexts: dict[str, list[str]],
    *,
    swsd_segments: list[dict[str, Any]],
    swsd_roads: list[dict[str, Any]],
    replacement_c_ids: set[str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for node_id, c_ids in base_contexts.items():
        result[node_id] = unique_preserve_order(c_ids)

    segment_contexts: dict[str, list[str]] = {}
    for segment in swsd_segments:
        props = dict(segment.get("properties") or {})
        segment_nodes = unique_preserve_order([*_parse_list(props.get("pair_nodes")), *_parse_list(props.get("junc_nodes"))])
        active_c_ids = [node_id for node_id in segment_nodes if node_id in replacement_c_ids]
        if active_c_ids:
            segment_contexts[_feature_id(segment)] = unique_preserve_order(active_c_ids)

    for road in swsd_roads:
        props = dict(road.get("properties") or {})
        active_c_ids: list[str] = []
        for segment_id in _parse_list(props.get("segmentid") or props.get("segment_id") or props.get("swsd_segment_id")):
            active_c_ids = unique_preserve_order([*active_c_ids, *segment_contexts.get(segment_id, [])])
        if not active_c_ids:
            continue
        for node_id in _road_endpoint_node_ids(road):
            result[node_id] = unique_preserve_order([*result[node_id], *active_c_ids])
    return dict(result)


def _context_units(c_ids: list[str], units_by_c: dict[str, list[Any]]) -> list[Any]:
    result: list[Any] = []
    for c_id in c_ids:
        result = _unique_units([*result, *units_by_c.get(c_id, [])])
    return result


def _unique_units(units: list[Any]) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for unit in units:
        key = str(getattr(unit, "segment_id", id(unit)))
        if key in seen:
            continue
        seen.add(key)
        result.append(unit)
    return result


def _selected_rcsd_road_ids(
    units: list[Any],
    added_road_to_segments: dict[str, list[str]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    result: list[str] = []
    for unit in units:
        for road_id in unit.rcsd_road_ids:
            if road_id in added_road_to_segments and road_id in rcsd_road_by_id:
                result.append(road_id)
    return unique_preserve_order(result)


def _selected_non_advance_rcsd_road_ids(
    units: list[Any],
    added_road_to_segments: dict[str, list[str]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    return [
        road_id
        for road_id in _selected_rcsd_road_ids(units, added_road_to_segments, rcsd_road_by_id)
        if not _is_advance_right_rcsd_road(rcsd_road_by_id[road_id])
    ]


def _normalize_missing_swsd_mainnode(node_id: str, node: dict[str, Any] | None) -> bool:
    if node is None:
        return False
    props = node.setdefault("properties", {})
    if parse_positive_int(props.get("mainnodeid")) is not None:
        return False
    props["mainnodeid"] = _coerce_id_value(node_id)
    return True


def _snap_retained_swsd_node_to_point(
    node_id: str,
    point: Point,
    *,
    swsd_node_by_id: dict[str, dict[str, Any]],
    retained_swsd_road_by_id: dict[str, dict[str, Any]],
    retained_swsd_node_to_roads: dict[str, list[str]],
    target_road_id: str | None = None,
    update_node_geometry: bool = True,
) -> None:
    node = swsd_node_by_id.get(node_id)
    if update_node_geometry and node is not None:
        node["geometry"] = point
    road_ids = (
        [target_road_id]
        if target_road_id is not None
        else retained_swsd_node_to_roads.get(node_id, [])
    )
    for road_id in road_ids:
        road = retained_swsd_road_by_id.get(road_id)
        if road is not None:
            _snap_road_endpoints(road, {node_id: point})


def _feature_point(feature_item: dict[str, Any] | None) -> Point | None:
    geometry = feature_item.get("geometry") if feature_item is not None else None
    return geometry if isinstance(geometry, Point) else None


def _apply_contract_split_points(
    units: list[Any],
    *,
    split_points_by_road: dict[str, dict[str, tuple[float, str]]],
    rcsd_roads: list[dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
) -> dict[str, int]:
    split_road_to_segments: dict[str, list[str]] = {}
    split_original_ids: set[str] = set()
    next_road_id = _next_numeric_id(rcsd_road_by_id)
    retained_node_segments = _retained_node_segments_by_node(units)
    for road_id in sorted(split_points_by_road, key=_id_sort_key):
        road = rcsd_road_by_id.get(road_id)
        if road is None:
            continue
        split_points = _dedupe_midroad_split_points(split_points_by_road[road_id].values())
        segment_ids = added_road_to_segments.pop(road_id, [])
        if not split_points or not segment_ids:
            continue
        replacement_ids: list[Any] | None = None
        if next_road_id is not None:
            replacement_ids = list(range(next_road_id, next_road_id + len(split_points) + 1))
            next_road_id += len(replacement_ids)
        split_roads = _split_rcsd_advance_road_at_existing_nodes(
            road,
            split_points=split_points,
            replacement_road_ids=replacement_ids,
            split_reason="junction_advance_right_attachment_contract",
        )
        if not split_roads:
            added_road_to_segments[road_id] = segment_ids
            continue
        split_original_ids.add(road_id)
        _replace_feature_by_id(rcsd_roads, road_id, split_roads)
        rcsd_road_by_id.pop(road_id, None)
        split_ids = [_feature_id(item) for item in split_roads]
        current_split_segments: dict[str, list[str]] = {}
        for split_road, split_id in zip(split_roads, split_ids):
            rcsd_road_by_id[split_id] = split_road
            split_segment_ids = list(segment_ids)
            for node_id in _road_endpoint_node_ids(split_road):
                split_segment_ids = unique_preserve_order(
                    [*split_segment_ids, *retained_node_segments.get(node_id, [])]
                )
            added_road_to_segments[split_id] = list(split_segment_ids)
            split_road_to_segments[split_id] = list(split_segment_ids)
            current_split_segments[split_id] = list(split_segment_ids)
        _replace_rcsd_road_in_units(units, road_id, split_ids)
        for split_id, segment_ids_for_split in current_split_segments.items():
            _append_rcsd_road_to_units(units, split_id, segment_ids_for_split)
    return {
        "rcsd_split_original_road_count": len(split_original_ids),
        "rcsd_split_road_count": len(split_road_to_segments),
    }


def _retained_node_segments_by_node(units: list[Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for unit in units:
        for node_id in getattr(unit, "retained_node_ids", []):
            result[str(node_id)] = unique_preserve_order([*result[str(node_id)], unit.segment_id])
    return dict(result)


def _append_rcsd_road_to_units(units: list[Any], road_id: str, segment_ids: list[str]) -> None:
    target_segments = set(segment_ids)
    if not target_segments:
        return
    for unit in units:
        if unit.segment_id in target_segments:
            unit.rcsd_road_ids = unique_preserve_order([*unit.rcsd_road_ids, road_id])


def _contract_audit_row(
    *,
    c_ids: list[str],
    road_id: str,
    node_id: str,
    retained_in_frcsd: bool,
    action: str,
    reason: str,
    mainnode_before: str | None,
    mainnode_after: str | None,
    rcsd_road_id: str | None = None,
    rcsd_node_id: str | None = None,
    generated_node_id: str | None = None,
    gap_m: float | None = None,
    replacement_segment_ids: list[str] | None = None,
    geometry: Any = None,
) -> dict[str, Any]:
    return feature(
        {
            "junction_c_ids": c_ids,
            "swsd_advance_road_id": road_id,
            "swsd_node_id": node_id,
            "retained_in_frcsd": retained_in_frcsd,
            "action": action,
            "action_reason": reason,
            "swsd_node_mainnodeid_before": mainnode_before,
            "swsd_node_mainnodeid_after": mainnode_after,
            "rcsd_road_id": rcsd_road_id,
            "rcsd_node_id": rcsd_node_id,
            "generated_rcsd_node_id": generated_node_id,
            "projected_gap_m": gap_m,
            "replacement_segment_ids": replacement_segment_ids or [],
        },
        geometry,
    )


def _unit_segment_ids(units: list[Any]) -> list[str]:
    return unique_preserve_order([unit.segment_id for unit in units])


def _generated_node_mainnode_id(
    swsd_node_id: str,
    point: Point,
    *,
    context_units: list[Any],
    rcsd_road_id: str,
    distance_m: float,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
) -> str | None:
    return _nearby_relation_mainnode_id(
        swsd_node_id,
        point,
        context_units=context_units,
        rcsd_node_by_id=rcsd_node_by_id,
    ) or _nearby_road_endpoint_mainnode_id(
        rcsd_road_id,
        distance_m,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
    )


def _nearest_mapped_rcsd_node_projection(
    swsd_node_id: str,
    point: Point,
    *,
    context_units: list[Any],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    max_gap_m: float = RETAINED_SWSD_MAPPED_NODE_MAX_GAP_M,
) -> tuple[str, Point, float] | None:
    best: tuple[float, str, Point] | None = None
    for rcsd_node_id in _mapped_rcsd_nodes_for_swsd_node(context_units, swsd_node_id):
        node = rcsd_node_by_id.get(rcsd_node_id)
        node_point = node.get("geometry") if node is not None else None
        if not isinstance(node_point, Point):
            continue
        gap_m = float(point.distance(node_point))
        if gap_m > max_gap_m:
            continue
        if best is None or gap_m < best[0]:
            best = (gap_m, rcsd_node_id, node_point)
    if best is None:
        return None
    return best[1], best[2], round(best[0], 3)


def _nearby_relation_mainnode_id(
    swsd_node_id: str,
    point: Point,
    *,
    context_units: list[Any],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    max_gap_m: float = GENERATED_NODE_RELATION_MAINNODE_MAX_GAP_M,
) -> str | None:
    best: tuple[float, str] | None = None
    for rcsd_node_id in _mapped_rcsd_nodes_for_swsd_node(context_units, swsd_node_id):
        node = rcsd_node_by_id.get(rcsd_node_id)
        node_point = node.get("geometry") if node is not None else None
        if not isinstance(node_point, Point):
            continue
        gap_m = float(point.distance(node_point))
        if gap_m > max_gap_m:
            continue
        mainnode_id = _node_mainnodeid_text(node)
        if not mainnode_id or mainnode_id == "0":
            mainnode_id = rcsd_node_id
        if best is None or gap_m < best[0]:
            best = (gap_m, mainnode_id)
    return best[1] if best is not None else None


def _nearby_road_endpoint_mainnode_id(
    rcsd_road_id: str,
    distance_m: float,
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    max_distance_m: float = GENERATED_NODE_ROAD_ENDPOINT_MAINNODE_MAX_DISTANCE_M,
) -> str | None:
    road = rcsd_road_by_id.get(rcsd_road_id)
    endpoints = _road_endpoint_node_ids(road) if road is not None else []
    if len(endpoints) < 2:
        return None
    line = _feature_line(road)
    if line is None or line.length <= 0:
        return None
    endpoint_id = ""
    if distance_m <= max_distance_m:
        endpoint_id = endpoints[0]
    elif line.length - distance_m <= max_distance_m:
        endpoint_id = endpoints[-1]
    if not endpoint_id:
        return None
    endpoint_node = rcsd_node_by_id.get(endpoint_id)
    mainnode_id = _node_mainnodeid_text(endpoint_node)
    if not mainnode_id or mainnode_id == "0":
        mainnode_id = endpoint_id
    return mainnode_id


def _mapped_rcsd_nodes_for_swsd_node(units: list[Any], swsd_node_id: str) -> list[str]:
    result: list[str] = []
    for unit in units:
        for source_node_id, rcsd_node_id in zip(getattr(unit, "pair_nodes", []), getattr(unit, "rcsd_pair_nodes", [])):
            if str(source_node_id) == str(swsd_node_id):
                result.append(str(rcsd_node_id))
        exempt_nodes = {str(node_id) for node_id in getattr(unit, "junc_kind2_exempt_nodes", [])}
        relation_junc_nodes = [
            str(node_id)
            for node_id in getattr(unit, "junc_nodes", [])
            if str(node_id) not in exempt_nodes
        ]
        for source_node_id, rcsd_node_id in zip(relation_junc_nodes, getattr(unit, "rcsd_junc_nodes", [])):
            if str(source_node_id) == str(swsd_node_id):
                result.append(str(rcsd_node_id))
        exempt_junc_nodes = [
            str(node_id)
            for node_id in getattr(unit, "junc_nodes", [])
            if str(node_id) in exempt_nodes
        ]
        optional_nodes = [str(node_id) for node_id in getattr(unit, "optional_allowed_rcsd_nodes", [])]
        if len(exempt_junc_nodes) == len(optional_nodes):
            for source_node_id, rcsd_node_id in zip(exempt_junc_nodes, optional_nodes):
                if str(source_node_id) == str(swsd_node_id):
                    result.append(str(rcsd_node_id))
    return unique_preserve_order(result)


def _assign_generated_node_relation_mainnode(
    generated_node_id: str,
    relation_mainnode_id: str | None,
    *,
    rcsd_node_by_id: dict[str, dict[str, Any]],
) -> None:
    if not relation_mainnode_id:
        return
    node = rcsd_node_by_id.get(generated_node_id)
    if node is None:
        return
    props = node.get("properties") or {}
    current_mainnode_id = _safe_normalize(props.get("mainnodeid") or generated_node_id)
    if current_mainnode_id != generated_node_id:
        return
    props["mainnodeid"] = _coerce_id_value(relation_mainnode_id)


def _node_mainnodeid_text(node: dict[str, Any] | None) -> str | None:
    if node is None:
        return None
    value = (node.get("properties") or {}).get("mainnodeid")
    if value in (None, ""):
        return None
    return _safe_normalize(value)


def _coerce_id_value(node_id: str) -> Any:
    return int(node_id) if node_id.isdigit() else node_id


def _append_unique_segments(target: list[str], segment_ids: list[str]) -> None:
    for segment_id in segment_ids:
        if segment_id not in target:
            target.append(segment_id)


def _road_endpoint_node_ids(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    result: list[str] = []
    for field in ("snodeid", "enodeid"):
        try:
            result.append(normalize_id(props.get(field)))
        except ParseError:
            continue
    return unique_preserve_order(result)


def _index_by_id(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in features:
        try:
            result.setdefault(_feature_id(item), item)
        except ParseError:
            continue
    return result


def _feature_id(feature_item: dict[str, Any]) -> str:
    return normalize_id((feature_item.get("properties") or {}).get("id"))


def _safe_normalize(value: Any) -> str:
    try:
        return normalize_id(value)
    except ParseError:
        return str(value)


def _parse_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _id_sort_key(value: str) -> tuple[int, int | str]:
    parsed = parse_positive_int(value)
    if parsed is not None:
        return (0, parsed)
    return (1, value)


def _retain_post_advance_right_swsd_carriers(
    units: list[ReplacementUnit],
    *,
    swsd_roads: list[dict[str, Any]],
    rcsd_roads: list[dict[str, Any]],
) -> dict[str, int]:
    swsd_road_by_id = _index_by_id(swsd_roads)
    rcsd_advance_geometries = [
        geometry
        for road in rcsd_roads
        if _is_advance_right_rcsd_road(road)
        for geometry in [_feature_line(road)]
        if geometry is not None
    ]
    retained_count = 0
    for unit in units:
        retained_count += sum(
            1
            for road_id in unit.retained_detached_swsd_road_ids
            if road_id in swsd_road_by_id and _is_advance_right_swsd_road(swsd_road_by_id[road_id])
        )
        retained: list[str] = []
        removed: list[str] = []
        for road_id in unit.swsd_road_ids:
            road = swsd_road_by_id.get(road_id)
            if road is None or not _is_advance_right_swsd_road(road):
                removed.append(road_id)
                continue
            geometry = _feature_line(road)
            has_near_rcsd_advance = (
                geometry is not None
                and any(geometry.distance(rcsd_geometry) <= 5.0 for rcsd_geometry in rcsd_advance_geometries)
            )
            if has_near_rcsd_advance:
                removed.append(road_id)
                continue
            retained.append(road_id)
        if retained:
            retained_count += len(retained)
            unit.retained_detached_swsd_road_ids = unique_preserve_order(
                [*unit.retained_detached_swsd_road_ids, *retained]
            )
            unit.swsd_road_ids = unique_preserve_order(removed)
    return {"retained_road_count": retained_count}


def _apply_post_advance_right_attachments(
    units: list[ReplacementUnit],
    *,
    rcsd_roads: list[dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    swsd_node_by_id: dict[str, dict[str, Any]],
    retained_swsd_roads: list[dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
    canonicalizer: NodeCanonicalizer,
) -> dict[str, int]:
    # Post expansion from RCSD advance-right components used RCSD as the clue,
    # which can introduce roads not supported by SWSD advance-right evidence.
    return _empty_post_advance_right_stats()

    initial_added_road_ids = set(added_road_to_segments)
    if not initial_added_road_ids:
        return _empty_post_advance_right_stats()

    node_to_roads = _node_to_road_ids(rcsd_roads)
    bridge_roads, component_count, mixed_component_count = _post_advance_right_bridge_roads(
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        retained_swsd_roads=retained_swsd_roads,
        node_to_roads=node_to_roads,
        initial_added_road_ids=initial_added_road_ids,
        added_road_to_segments=added_road_to_segments,
    )
    for road_id, segment_ids in bridge_roads.items():
        _append_unique_segments(added_road_to_segments[road_id], segment_ids)

    paired_advance_roads = _post_advance_right_paired_advance_roads(
        rcsd_road_by_id=rcsd_road_by_id,
        node_to_roads=node_to_roads,
        added_road_to_segments=added_road_to_segments,
        retained_swsd_roads=retained_swsd_roads,
    )
    for road_id, segment_ids in paired_advance_roads.items():
        _append_unique_segments(added_road_to_segments[road_id], segment_ids)

    attached_roads = _post_advance_right_attached_roads(
        rcsd_road_by_id=rcsd_road_by_id,
        node_to_roads=node_to_roads,
        added_road_to_segments=added_road_to_segments,
        retained_swsd_roads=retained_swsd_roads,
    )
    for road_id, segment_ids in attached_roads.items():
        _append_unique_segments(added_road_to_segments[road_id], segment_ids)

    post_added_roads = {**bridge_roads, **paired_advance_roads, **attached_roads}
    _append_post_advance_right_roads_to_units(
        units,
        road_to_segments=post_added_roads,
        rcsd_road_by_id=rcsd_road_by_id,
        canonicalizer=canonicalizer,
    )
    midroad_stats = _apply_post_advance_right_midroad_attachments(
        units,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        added_road_to_segments=added_road_to_segments,
        canonicalizer=canonicalizer,
    )
    swsd_carrier_stats = _apply_swsd_advance_carrier_rcsd_nodes(
        units,
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        swsd_node_by_id=swsd_node_by_id,
        retained_swsd_roads=retained_swsd_roads,
        added_road_to_segments=added_road_to_segments,
    )
    return {
        "added_road_count": len(post_added_roads),
        "component_count": component_count,
        "attached_road_count": len(attached_roads),
        "mixed_boundary_component_count": mixed_component_count,
        "paired_advance_road_count": len(paired_advance_roads),
        "midroad_split_original_road_count": midroad_stats["split_original_road_count"],
        "midroad_split_road_count": midroad_stats["split_road_count"],
        "midroad_attached_road_count": midroad_stats["attached_road_count"],
        "swsd_carrier_split_original_road_count": swsd_carrier_stats["split_original_road_count"],
        "swsd_carrier_split_road_count": swsd_carrier_stats["split_road_count"],
        "swsd_carrier_generated_node_count": swsd_carrier_stats["generated_node_count"],
        "swsd_carrier_snapped_node_count": swsd_carrier_stats["snapped_node_count"],
    }


def _empty_post_advance_right_stats() -> dict[str, int]:
    return {
        "added_road_count": 0,
        "component_count": 0,
        "attached_road_count": 0,
        "mixed_boundary_component_count": 0,
        "paired_advance_road_count": 0,
        "midroad_split_original_road_count": 0,
        "midroad_split_road_count": 0,
        "midroad_attached_road_count": 0,
        "swsd_carrier_split_original_road_count": 0,
        "swsd_carrier_split_road_count": 0,
        "swsd_carrier_generated_node_count": 0,
        "swsd_carrier_snapped_node_count": 0,
    }


def _post_advance_right_bridge_roads(
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    retained_swsd_roads: list[dict[str, Any]],
    node_to_roads: dict[str, list[str]],
    initial_added_road_ids: set[str],
    added_road_to_segments: dict[str, list[str]],
) -> tuple[dict[str, list[str]], int, int]:
    pending_road_ids = set(rcsd_road_by_id) - initial_added_road_ids
    visited: set[str] = set()
    result: dict[str, list[str]] = {}
    component_count = 0
    mixed_component_count = 0
    for road_id in sorted(pending_road_ids, key=_id_sort_key):
        if road_id in visited:
            continue
        component = _connected_road_component(
            road_id,
            candidate_road_ids=pending_road_ids,
            node_to_roads=node_to_roads,
            rcsd_road_by_id=rcsd_road_by_id,
        )
        visited.update(component)
        if not any(_is_advance_right_rcsd_road(rcsd_road_by_id[item]) for item in component):
            continue
        component_nodes = _road_ids_endpoint_nodes(component, rcsd_road_by_id)
        boundary_nodes = {
            node_id
            for node_id in component_nodes
            if any(incident in initial_added_road_ids for incident in node_to_roads.get(node_id, []))
        }
        mixed_boundary_nodes = _mixed_swsd_boundary_nodes(
            component,
            boundary_nodes=boundary_nodes,
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_by_id=rcsd_node_by_id,
            retained_swsd_roads=retained_swsd_roads,
        )
        if len(boundary_nodes) < 2 and not (boundary_nodes and mixed_boundary_nodes):
            continue
        retained_component = _trim_component_to_boundary_roads(
            component,
            boundary_nodes={*boundary_nodes, *mixed_boundary_nodes},
            rcsd_road_by_id=rcsd_road_by_id,
        )
        if not retained_component or not any(_is_advance_right_rcsd_road(rcsd_road_by_id[item]) for item in retained_component):
            continue
        segment_ids = _segments_touching_nodes(
            _road_ids_endpoint_nodes(retained_component, rcsd_road_by_id).intersection(boundary_nodes),
            node_to_roads=node_to_roads,
            added_road_to_segments=added_road_to_segments,
        )
        if not segment_ids:
            continue
        component_count += 1
        if mixed_boundary_nodes:
            mixed_component_count += 1
            _snap_rcsd_component_to_retained_swsd(
                retained_component,
                mixed_boundary_nodes=mixed_boundary_nodes,
                rcsd_road_by_id=rcsd_road_by_id,
                rcsd_node_by_id=rcsd_node_by_id,
                retained_swsd_roads=retained_swsd_roads,
            )
        for retained_road_id in sorted(retained_component, key=_id_sort_key):
            if post_advance_road_crosses_retained_swsd(rcsd_road_by_id[retained_road_id], retained_swsd_roads):
                continue
            result[retained_road_id] = segment_ids
    return result, component_count, mixed_component_count


def _post_advance_right_attached_roads(
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    node_to_roads: dict[str, list[str]],
    added_road_to_segments: dict[str, list[str]],
    retained_swsd_roads: list[dict[str, Any]],
) -> dict[str, list[str]]:
    added_road_ids = set(added_road_to_segments)
    added_node_ids = _road_ids_endpoint_nodes(added_road_ids, rcsd_road_by_id)
    added_advance_road_ids = {
        road_id
        for road_id in added_road_ids
        if road_id in rcsd_road_by_id and _is_advance_right_rcsd_road(rcsd_road_by_id[road_id])
    }
    advance_nodes = _road_ids_endpoint_nodes(added_advance_road_ids, rcsd_road_by_id)
    result: dict[str, list[str]] = {}
    for road_id in sorted(set(rcsd_road_by_id) - added_road_ids, key=_id_sort_key):
        road = rcsd_road_by_id[road_id]
        if _is_advance_right_rcsd_road(road):
            continue
        endpoints = set(_road_endpoint_node_ids(road))
        if not endpoints or not endpoints.issubset(added_node_ids):
            continue
        if not endpoints.intersection(advance_nodes):
            continue
        if not any(
            incident in added_advance_road_ids
            for node_id in endpoints
            for incident in node_to_roads.get(node_id, [])
        ):
            continue
        if post_advance_road_crosses_retained_swsd(road, retained_swsd_roads):
            continue
        segment_ids = _segments_touching_nodes(
            endpoints,
            node_to_roads=node_to_roads,
            added_road_to_segments=added_road_to_segments,
        )
        if segment_ids:
            result[road_id] = segment_ids
    return result


def _post_advance_right_paired_advance_roads(
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    node_to_roads: dict[str, list[str]],
    added_road_to_segments: dict[str, list[str]],
    retained_swsd_roads: list[dict[str, Any]],
) -> dict[str, list[str]]:
    added_road_ids = set(added_road_to_segments)
    added_advance_road_ids = {
        road_id
        for road_id in added_road_ids
        if road_id in rcsd_road_by_id and _is_advance_right_rcsd_road(rcsd_road_by_id[road_id])
    }
    if not added_advance_road_ids:
        return {}
    added_advance_nodes = _road_ids_endpoint_nodes(added_advance_road_ids, rcsd_road_by_id)
    result: dict[str, list[str]] = {}
    for road_id in sorted(set(rcsd_road_by_id) - added_road_ids, key=_id_sort_key):
        road = rcsd_road_by_id[road_id]
        if not _is_advance_right_rcsd_road(road):
            continue
        if _post_advance_road_crosses_retained_non_advance_swsd(road, retained_swsd_roads):
            continue
        shared_nodes = set(_road_endpoint_node_ids(road)).intersection(added_advance_nodes)
        if not shared_nodes:
            continue
        segment_ids = _segments_touching_nodes(
            shared_nodes,
            node_to_roads=node_to_roads,
            added_road_to_segments=added_road_to_segments,
        )
        if segment_ids:
            result[road_id] = segment_ids
    return result


def _post_advance_road_crosses_retained_non_advance_swsd(
    road: dict[str, Any],
    retained_swsd_roads: list[dict[str, Any]],
    *,
    buffer_m: float = 1.0,
    min_covered_ratio: float = 0.2,
) -> bool:
    line = _feature_line(road)
    if line is None or line.length <= 0:
        return False
    for swsd_road in retained_swsd_roads:
        if _is_advance_right_swsd_road(swsd_road):
            continue
        swsd_line = _feature_line(swsd_road)
        if swsd_line is None:
            continue
        if line.intersection(swsd_line.buffer(buffer_m)).length / line.length >= min_covered_ratio:
            return True
    return False


def _apply_post_advance_right_midroad_attachments(
    units: list[ReplacementUnit],
    *,
    rcsd_roads: list[dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
    canonicalizer: NodeCanonicalizer,
) -> dict[str, int]:
    selected_advance_ids = [
        road_id
        for road_id in sorted(added_road_to_segments, key=_id_sort_key)
        if road_id in rcsd_road_by_id and _is_advance_right_rcsd_road(rcsd_road_by_id[road_id])
    ]
    if not selected_advance_ids:
        return {"split_original_road_count": 0, "split_road_count": 0, "attached_road_count": 0}

    added_road_ids = set(added_road_to_segments)
    split_points_by_advance: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)
    attached_road_to_segments: dict[str, list[str]] = {}
    for road_id in sorted(set(rcsd_road_by_id) - added_road_ids, key=_id_sort_key):
        road = rcsd_road_by_id[road_id]
        if _is_advance_right_rcsd_road(road):
            continue
        endpoint_ids = _road_endpoint_node_ids(road)
        endpoint_points = _road_endpoint_points(road)
        for endpoint_id, endpoint_point in zip(endpoint_ids, endpoint_points):
            if endpoint_id not in rcsd_node_by_id:
                continue
            match = _nearest_selected_advance_midpoint(
                endpoint_point,
                selected_advance_ids=selected_advance_ids,
                rcsd_road_by_id=rcsd_road_by_id,
            )
            if match is None:
                continue
            advance_id, distance_m = match
            segment_ids = added_road_to_segments.get(advance_id, [])
            if not segment_ids:
                continue
            split_points_by_advance[advance_id][endpoint_id] = (distance_m, endpoint_id)
            attached_road_to_segments[road_id] = segment_ids
            break

    if not split_points_by_advance:
        return {"split_original_road_count": 0, "split_road_count": 0, "attached_road_count": 0}

    split_road_to_segments: dict[str, list[str]] = {}
    split_original_ids: set[str] = set()
    for advance_id in sorted(split_points_by_advance, key=_id_sort_key):
        road = rcsd_road_by_id.get(advance_id)
        line = _feature_line(road) if road is not None else None
        if road is None or line is None or line.length <= 0:
            continue
        split_points = _dedupe_midroad_split_points(split_points_by_advance[advance_id].values())
        if not split_points:
            continue
        segment_ids = added_road_to_segments.pop(advance_id, [])
        if not segment_ids:
            continue
        split_roads = _split_rcsd_advance_road_at_existing_nodes(
            road,
            split_points=split_points,
        )
        if not split_roads:
            added_road_to_segments[advance_id] = segment_ids
            continue
        split_original_ids.add(advance_id)
        _replace_feature_by_id(rcsd_roads, advance_id, split_roads)
        rcsd_road_by_id.pop(advance_id, None)
        for split_road in split_roads:
            split_id = _feature_id(split_road)
            rcsd_road_by_id[split_id] = split_road
            added_road_to_segments[split_id] = list(segment_ids)
            split_road_to_segments[split_id] = list(segment_ids)
        _replace_rcsd_road_in_units(units, advance_id, [_feature_id(item) for item in split_roads])

    for road_id, segment_ids in attached_road_to_segments.items():
        if road_id in added_road_to_segments:
            continue
        added_road_to_segments[road_id] = list(segment_ids)
    _append_post_advance_right_roads_to_units(
        units,
        road_to_segments={**split_road_to_segments, **attached_road_to_segments},
        rcsd_road_by_id=rcsd_road_by_id,
        canonicalizer=canonicalizer,
    )
    return {
        "split_original_road_count": len(split_original_ids),
        "split_road_count": len(split_road_to_segments),
        "attached_road_count": len(attached_road_to_segments),
    }


def _apply_swsd_advance_carrier_rcsd_nodes(
    units: list[ReplacementUnit],
    *,
    rcsd_roads: list[dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    swsd_node_by_id: dict[str, dict[str, Any]],
    retained_swsd_roads: list[dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
) -> dict[str, int]:
    retained_swsd_road_by_id = _index_by_id(retained_swsd_roads)
    split_points_by_road: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)
    generated_nodes_by_projection: dict[str, list[tuple[float, str]]] = defaultdict(list)
    generated_node_count = 0
    snapped_node_count = 0
    next_node_id = _next_numeric_id(rcsd_node_by_id)
    for unit in units:
        selected_rcsd_road_ids = [
            road_id
            for road_id in unit.rcsd_road_ids
            if road_id in added_road_to_segments
            and road_id in rcsd_road_by_id
            and not _is_advance_right_rcsd_road(rcsd_road_by_id[road_id])
        ]
        if not selected_rcsd_road_ids:
            continue
        for swsd_road_id in unit.retained_detached_swsd_road_ids:
            swsd_road = retained_swsd_road_by_id.get(swsd_road_id)
            if swsd_road is None or not _is_advance_right_swsd_road(swsd_road):
                continue
            for swsd_node_id, point in zip(_road_endpoint_node_ids(swsd_road), _road_endpoint_points(swsd_road)):
                match = _nearest_selected_rcsd_projection(
                    point,
                    selected_rcsd_road_ids=selected_rcsd_road_ids,
                    rcsd_road_by_id=rcsd_road_by_id,
                )
                if match is None:
                    continue
                rcsd_road_id, distance_m, projected, endpoint_node_id = match
                _snap_road_node_to_point(swsd_road, swsd_node_id, projected, swsd_node_by_id)
                if endpoint_node_id is not None:
                    unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, endpoint_node_id])
                    snapped_node_count += 1
                    continue
                reusable_node_id = _nearby_generated_projection_node_id(
                    generated_nodes_by_projection[rcsd_road_id],
                    distance_m,
                )
                if reusable_node_id is not None:
                    node_id = reusable_node_id
                else:
                    node_value = next_node_id if next_node_id is not None else f"t06_advnode_{generated_node_count + 1}"
                    if next_node_id is not None:
                        next_node_id += 1
                    node_id = _safe_normalize(node_value)
                    if node_id not in rcsd_node_by_id:
                        relation_mainnode_id = _generated_node_mainnode_id(
                            swsd_node_id,
                            projected,
                            context_units=[unit],
                            rcsd_road_id=rcsd_road_id,
                            distance_m=distance_m,
                            rcsd_road_by_id=rcsd_road_by_id,
                            rcsd_node_by_id=rcsd_node_by_id,
                        )
                        node = _new_post_advance_rcsd_node(
                            node_value=node_value,
                            geometry=projected,
                            rcsd_node_by_id=rcsd_node_by_id,
                            swsd_node=swsd_node_by_id.get(swsd_node_id),
                            relation_mainnode_id=relation_mainnode_id,
                        )
                        rcsd_nodes.append(node)
                        rcsd_node_by_id[node_id] = node
                        generated_node_count += 1
                    generated_nodes_by_projection[rcsd_road_id].append((distance_m, node_id))
                split_points_by_road[rcsd_road_id][node_id] = (distance_m, node_id)
                unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, node_id])

    split_road_to_segments: dict[str, list[str]] = {}
    split_original_ids: set[str] = set()
    next_road_id = _next_numeric_id(rcsd_road_by_id)
    for road_id in sorted(split_points_by_road, key=_id_sort_key):
        road = rcsd_road_by_id.get(road_id)
        if road is None:
            continue
        split_points = _dedupe_midroad_split_points(split_points_by_road[road_id].values())
        segment_ids = added_road_to_segments.pop(road_id, [])
        if not split_points or not segment_ids:
            continue
        replacement_ids: list[Any] | None = None
        if next_road_id is not None:
            replacement_ids = list(range(next_road_id, next_road_id + len(split_points) + 1))
            next_road_id += len(replacement_ids)
        split_roads = _split_rcsd_advance_road_at_existing_nodes(
            road,
            split_points=split_points,
            replacement_road_ids=replacement_ids,
            split_reason="post_advance_right_swsd_carrier_node",
        )
        if not split_roads:
            added_road_to_segments[road_id] = segment_ids
            continue
        split_original_ids.add(road_id)
        _replace_feature_by_id(rcsd_roads, road_id, split_roads)
        rcsd_road_by_id.pop(road_id, None)
        split_ids = [_feature_id(item) for item in split_roads]
        for split_road, split_id in zip(split_roads, split_ids):
            rcsd_road_by_id[split_id] = split_road
            added_road_to_segments[split_id] = list(segment_ids)
            split_road_to_segments[split_id] = list(segment_ids)
        _replace_rcsd_road_in_units(units, road_id, split_ids)
    return {
        "split_original_road_count": len(split_original_ids),
        "split_road_count": len(split_road_to_segments),
        "generated_node_count": generated_node_count,
        "snapped_node_count": snapped_node_count,
    }


def _connected_road_component(
    seed_road_id: str,
    *,
    candidate_road_ids: set[str],
    node_to_roads: dict[str, list[str]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> set[str]:
    component: set[str] = set()
    queue = [seed_road_id]
    while queue:
        road_id = queue.pop()
        if road_id in component:
            continue
        road = rcsd_road_by_id.get(road_id)
        if road is None:
            continue
        component.add(road_id)
        for node_id in _road_endpoint_node_ids(road):
            for next_road_id in node_to_roads.get(node_id, []):
                if next_road_id in candidate_road_ids and next_road_id not in component:
                    queue.append(next_road_id)
    return component


def _trim_component_to_boundary_roads(
    road_ids: set[str],
    *,
    boundary_nodes: set[str],
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> set[str]:
    retained = set(road_ids)
    while True:
        degrees: dict[str, int] = defaultdict(int)
        road_endpoints: dict[str, list[str]] = {}
        for road_id in retained:
            endpoints = _road_endpoint_node_ids(rcsd_road_by_id[road_id])
            road_endpoints[road_id] = endpoints
            for node_id in endpoints:
                degrees[node_id] += 1
        removable_nodes = {node_id for node_id, degree in degrees.items() if degree <= 1 and node_id not in boundary_nodes}
        if not removable_nodes:
            return retained
        next_retained = {
            road_id
            for road_id, endpoints in road_endpoints.items()
            if not removable_nodes.intersection(endpoints)
        }
        if next_retained == retained:
            return retained
        retained = next_retained


def _append_post_advance_right_roads_to_units(
    units: list[ReplacementUnit],
    *,
    road_to_segments: dict[str, list[str]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> None:
    if not road_to_segments:
        return
    unit_by_segment = {unit.segment_id: unit for unit in units if unit.status == "passed"}
    for road_id in sorted(road_to_segments, key=_id_sort_key):
        road = rcsd_road_by_id.get(road_id)
        if road is None:
            continue
        endpoint_semantic_ids = _canonical_road_endpoint_ids(road, canonicalizer)
        for segment_id in road_to_segments[road_id]:
            unit = unit_by_segment.get(segment_id)
            if unit is None:
                continue
            unit.rcsd_road_ids = unique_preserve_order([*unit.rcsd_road_ids, road_id])
            unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, *endpoint_semantic_ids])


def _node_to_road_ids(roads: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for road in roads:
        try:
            road_id = _feature_id(road)
        except ParseError:
            continue
        for node_id in _road_endpoint_node_ids(road):
            result[node_id].append(road_id)
    return {node_id: unique_preserve_order(road_ids) for node_id, road_ids in result.items()}


def _has_incident_rcsd_road_in_mainnode_group(
    node_id: str,
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    allowed_road_ids: set[str] | None = None,
    excluded_road_ids: set[str] | None = None,
) -> bool:
    allowed = allowed_road_ids
    excluded = excluded_road_ids or set()
    group_key = _mainnode_group_key(node_id, rcsd_node_by_id=rcsd_node_by_id)
    for candidate_id in _mainnode_group_node_ids(group_key, rcsd_node_by_id=rcsd_node_by_id):
        for road_id, road in rcsd_road_by_id.items():
            if allowed is not None and road_id not in allowed:
                continue
            if road_id in excluded:
                continue
            if not _is_rcsd_contract_road(road):
                continue
            if candidate_id in _road_endpoint_node_ids(road):
                return True
    return False


def _mainnode_group_key(node_id: str, *, rcsd_node_by_id: dict[str, dict[str, Any]]) -> str:
    node = rcsd_node_by_id.get(node_id)
    mainnode_id = _node_mainnodeid_text(node)
    if not mainnode_id or mainnode_id == "0":
        return node_id
    return mainnode_id


def _mainnode_group_node_ids(group_key: str, *, rcsd_node_by_id: dict[str, dict[str, Any]]) -> list[str]:
    result = [
        node_id
        for node_id in rcsd_node_by_id
        if _mainnode_group_key(node_id, rcsd_node_by_id=rcsd_node_by_id) == group_key
    ]
    return unique_preserve_order([group_key, *result])


def _global_added_rcsd_road_ids(
    *,
    added_road_to_segments: dict[str, list[str]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    excluded_road_ids: set[str] | None = None,
) -> list[str]:
    excluded = excluded_road_ids or set()
    return [
        road_id
        for road_id in sorted(added_road_to_segments, key=_id_sort_key)
        if road_id in rcsd_road_by_id
        and road_id not in excluded
        and _is_rcsd_contract_road(rcsd_road_by_id[road_id])
    ]


def _is_rcsd_contract_road(road: dict[str, Any]) -> bool:
    source = (road.get("properties") or {}).get("source")
    if source in (None, ""):
        return True
    return _safe_normalize(source) == "1"


def _segments_touching_nodes(
    node_ids: set[str],
    *,
    node_to_roads: dict[str, list[str]],
    added_road_to_segments: dict[str, list[str]],
) -> list[str]:
    segment_ids: list[str] = []
    for node_id in sorted(node_ids, key=_id_sort_key):
        for road_id in node_to_roads.get(node_id, []):
            _append_unique_segments(segment_ids, added_road_to_segments.get(road_id, []))
    return segment_ids


def _road_ids_endpoint_nodes(road_ids: set[str], rcsd_road_by_id: dict[str, dict[str, Any]]) -> set[str]:
    result: set[str] = set()
    for road_id in road_ids:
        road = rcsd_road_by_id.get(road_id)
        if road is not None:
            result.update(_road_endpoint_node_ids(road))
    return result


def _mixed_swsd_boundary_nodes(
    road_ids: set[str],
    *,
    boundary_nodes: set[str],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    retained_swsd_roads: list[dict[str, Any]],
) -> set[str]:
    retained_lines = [_feature_line(road) for road in retained_swsd_roads]
    retained_lines = [line for line in retained_lines if line is not None]
    if not retained_lines:
        return set()
    result: set[str] = set()
    for road_id in road_ids:
        road = rcsd_road_by_id.get(road_id)
        if road is None:
            continue
        for node_id, point in zip(_road_endpoint_node_ids(road), _road_endpoint_points(road)):
            if node_id in boundary_nodes:
                continue
            node_feature = rcsd_node_by_id.get(node_id)
            node_point = node_feature.get("geometry") if node_feature is not None else point
            if node_point is None:
                continue
            if any(node_point.distance(line) <= 5.0 for line in retained_lines):
                result.add(node_id)
    return result


def _snap_rcsd_component_to_retained_swsd(
    road_ids: set[str],
    *,
    mixed_boundary_nodes: set[str],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    retained_swsd_roads: list[dict[str, Any]],
) -> None:
    retained_lines = [_feature_line(road) for road in retained_swsd_roads]
    retained_lines = [line for line in retained_lines if line is not None]
    if not retained_lines:
        return
    snapped_points: dict[str, Point] = {}
    for node_id in mixed_boundary_nodes:
        node = rcsd_node_by_id.get(node_id)
        point = node.get("geometry") if node is not None else None
        if point is None:
            continue
        nearest_line = min(retained_lines, key=lambda line: line.distance(point))
        snapped = nearest_line.interpolate(nearest_line.project(point))
        if snapped.distance(point) > 5.0:
            continue
        snapped_points[node_id] = snapped
        node["geometry"] = snapped
    for road_id in road_ids:
        road = rcsd_road_by_id.get(road_id)
        if road is None:
            continue
        _snap_road_endpoints(road, snapped_points)


def _nearest_selected_advance_midpoint(
    point: Point,
    *,
    selected_advance_ids: list[str],
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> tuple[str, float] | None:
    best: tuple[float, str, float] | None = None
    for advance_id in selected_advance_ids:
        line = _feature_line(rcsd_road_by_id.get(advance_id))
        if line is None or line.length <= 0:
            continue
        distance_m = float(line.project(point))
        if distance_m <= 1.0 or line.length - distance_m <= 1.0:
            continue
        projected = line.interpolate(distance_m)
        gap = float(point.distance(projected))
        if gap > 1.0:
            continue
        if best is None or gap < best[0]:
            best = (gap, advance_id, distance_m)
    if best is None:
        return None
    return best[1], best[2]


def _nearest_preferred_rcsd_projection(
    point: Point,
    *,
    selected_rcsd_road_ids: list[str],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    max_gap_m: float,
) -> tuple[str, float, Point, str | None] | None:
    match = _nearest_selected_rcsd_projection(
        point,
        selected_rcsd_road_ids=selected_rcsd_road_ids,
        rcsd_road_by_id=rcsd_road_by_id,
        max_gap_m=max_gap_m,
    )
    if match is None:
        return None
    road_id, _distance_m, projected, _endpoint_node_id = match
    if not _is_advance_right_rcsd_road(rcsd_road_by_id[road_id]):
        return match

    non_advance_road_ids = [
        candidate_road_id
        for candidate_road_id in selected_rcsd_road_ids
        if candidate_road_id in rcsd_road_by_id and not _is_advance_right_rcsd_road(rcsd_road_by_id[candidate_road_id])
    ]
    non_advance_match = _nearest_selected_rcsd_projection(
        point,
        selected_rcsd_road_ids=non_advance_road_ids,
        rcsd_road_by_id=rcsd_road_by_id,
        max_gap_m=max_gap_m,
    )
    if non_advance_match is None:
        return match

    advance_gap = float(point.distance(projected))
    non_advance_gap = float(point.distance(non_advance_match[2]))
    if non_advance_gap <= advance_gap + NON_ADVANCE_ROAD_PREFERENCE_MAX_EXTRA_GAP_M:
        return non_advance_match
    return match


def _nearest_selected_rcsd_projection(
    point: Point,
    *,
    selected_rcsd_road_ids: list[str],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    max_gap_m: float = 1.0,
) -> tuple[str, float, Point, str | None] | None:
    best: tuple[float, str, float, Point, str | None] | None = None
    for road_id in selected_rcsd_road_ids:
        road = rcsd_road_by_id.get(road_id)
        line = _feature_line(road)
        if road is None or line is None or line.length <= 0:
            continue
        distance_m = float(line.project(point))
        projected = line.interpolate(distance_m)
        gap = float(point.distance(projected))
        if gap > max_gap_m:
            continue
        endpoint_node_id = None
        endpoints = _road_endpoint_node_ids(road)
        if len(endpoints) >= 2:
            if distance_m <= 1.0:
                endpoint_node_id = endpoints[0]
                projected = Point(line.coords[0][:2])
            elif line.length - distance_m <= 1.0:
                endpoint_node_id = endpoints[-1]
                projected = Point(line.coords[-1][:2])
        if best is None or gap < best[0]:
            best = (gap, road_id, distance_m, projected, endpoint_node_id)
    if best is None:
        return None
    return best[1], best[2], best[3], best[4]


def _dedupe_midroad_split_points(points: list[tuple[float, str]] | Any) -> list[tuple[float, str]]:
    result: list[tuple[float, str]] = []
    for distance_m, node_id in sorted(points, key=lambda item: (item[0], _id_sort_key(item[1]))):
        if distance_m <= 1.0:
            continue
        if result and abs(distance_m - result[-1][0]) < ADVANCE_RIGHT_SPLIT_POINT_DEDUPE_M:
            result[-1] = ((result[-1][0] + distance_m) / 2.0, min(result[-1][1], node_id, key=_id_sort_key))
            continue
        result.append((distance_m, node_id))
    return result


def _nearby_generated_projection_node_id(generated_nodes: list[tuple[float, str]], distance_m: float) -> str | None:
    for existing_distance_m, node_id in generated_nodes:
        if abs(distance_m - existing_distance_m) < ADVANCE_RIGHT_SPLIT_POINT_DEDUPE_M:
            return node_id
    return None


def _split_rcsd_advance_road_at_existing_nodes(
    road: dict[str, Any],
    *,
    split_points: list[tuple[float, str]],
    replacement_road_ids: list[Any] | None = None,
    split_reason: str = "post_advance_right_midroad_attachment",
) -> list[dict[str, Any]]:
    line = _feature_line(road)
    if line is None or line.length <= 0:
        return []
    original_id = _feature_id(road)
    endpoint_ids = _road_endpoint_node_ids(road)
    if len(endpoint_ids) < 2:
        return []
    valid_points = [(distance, node_id) for distance, node_id in split_points if 1.0 < distance < line.length - 1.0]
    if not valid_points:
        return []
    boundaries = [0.0, *[distance for distance, _node_id in valid_points], float(line.length)]
    node_boundaries = [endpoint_ids[0], *[node_id for _distance, node_id in valid_points], endpoint_ids[-1]]
    result: list[dict[str, Any]] = []
    for index in range(len(boundaries) - 1):
        start_m = boundaries[index]
        end_m = boundaries[index + 1]
        if end_m - start_m <= 1e-9:
            continue
        segment = substring(line, start_m, end_m)
        if segment is None or segment.is_empty or not isinstance(segment, LineString):
            continue
        props = dict(road.get("properties") or {})
        props["id"] = (
            replacement_road_ids[index]
            if replacement_road_ids is not None and index < len(replacement_road_ids)
            else f"{original_id}__t06advsplit_{index + 1}"
        )
        props["snodeid"] = node_boundaries[index]
        props["enodeid"] = node_boundaries[index + 1]
        props["t06_split_original_road_id"] = original_id
        props["t06_split_reason"] = split_reason
        result.append({"properties": props, "geometry": segment})
    return result


def _replace_feature_by_id(features: list[dict[str, Any]], original_id: str, replacements: list[dict[str, Any]]) -> None:
    for index, item in enumerate(list(features)):
        if _feature_id(item) == original_id:
            features[index:index + 1] = replacements
            return
    features.extend(replacements)


def _replace_rcsd_road_in_units(units: list[ReplacementUnit], original_id: str, replacement_ids: list[str]) -> None:
    for unit in units:
        if original_id not in unit.rcsd_road_ids:
            continue
        next_ids: list[str] = []
        for road_id in unit.rcsd_road_ids:
            if road_id == original_id:
                next_ids.extend(replacement_ids)
            else:
                next_ids.append(road_id)
        unit.rcsd_road_ids = unique_preserve_order(next_ids)


def _feature_line(feature_value: dict[str, Any] | None) -> LineString | None:
    if feature_value is None:
        return None
    geometry = feature_value.get("geometry")
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, LineString):
        return geometry
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
        if isinstance(merged, LineString):
            return merged
        parts = [item for item in geometry.geoms if isinstance(item, LineString)]
        return max(parts, key=lambda item: item.length) if parts else None
    if hasattr(geometry, "geoms"):
        parts = [item for item in geometry.geoms if isinstance(item, LineString)]
        return max(parts, key=lambda item: item.length) if parts else None
    return None


def _road_endpoint_points(road: dict[str, Any]) -> list[Point]:
    line = _feature_line(road)
    if line is None:
        return []
    coords = list(line.coords)
    if not coords:
        return []
    return [Point(coords[0]), Point(coords[-1])]


def _snap_road_endpoints(road: dict[str, Any], snapped_points: dict[str, Point]) -> None:
    endpoint_ids = _road_endpoint_node_ids(road)
    line = _feature_line(road)
    if line is None or len(endpoint_ids) < 2:
        return
    coords = list(line.coords)
    if not coords:
        return
    if endpoint_ids[0] in snapped_points:
        coords[0] = _coord_with_snapped_xy(coords[0], snapped_points[endpoint_ids[0]])
    if endpoint_ids[-1] in snapped_points:
        coords[-1] = _coord_with_snapped_xy(coords[-1], snapped_points[endpoint_ids[-1]])
    road["geometry"] = LineString(coords)


def _snap_road_node_to_point(
    road: dict[str, Any],
    node_id: str,
    point: Point,
    node_by_id: dict[str, dict[str, Any]],
) -> None:
    _snap_road_endpoints(road, {node_id: point})
    node = node_by_id.get(node_id)
    if node is not None:
        node["geometry"] = point


def _coord_with_snapped_xy(original: tuple[float, ...], snapped: Point) -> tuple[float, ...]:
    x, y = snapped.coords[0][:2]
    if len(original) <= 2:
        return (x, y)
    return (x, y, *original[2:])


def _new_post_advance_rcsd_node(
    *,
    node_value: Any,
    geometry: Point,
    rcsd_node_by_id: dict[str, dict[str, Any]],
    swsd_node: dict[str, Any] | None,
    relation_mainnode_id: str | None = None,
) -> dict[str, Any]:
    template = dict(next(iter(rcsd_node_by_id.values())).get("properties") or {}) if rcsd_node_by_id else {}
    props = {key: None for key in template}
    mainnode_value = _coerce_id_value(relation_mainnode_id) if relation_mainnode_id else node_value
    props.update({"id": node_value, "mainnodeid": mainnode_value, "t06_generated_reason": "post_advance_right_swsd_carrier_node"})
    if swsd_node is not None:
        swsd_props = dict(swsd_node.get("properties") or {})
        for field in INHERITED_NODE_FIELDS:
            if field in swsd_props:
                props[field] = swsd_props[field]
    return {"properties": props, "geometry": geometry}


def _next_numeric_id(items: dict[str, Any]) -> int | None:
    values: list[int] = []
    for item_id in items:
        text = str(item_id)
        if not text.isdigit():
            return None
        values.append(int(text))
    return max(values, default=0) + 1


def _canonical_road_endpoint_ids(road: dict[str, Any], canonicalizer: NodeCanonicalizer) -> list[str]:
    result: list[str] = []
    for node_id in _road_endpoint_node_ids(road):
        try:
            result.append(canonicalizer.canonicalize(node_id))
        except ParseError:
            result.append(node_id)
    return unique_preserve_order(result)


def _is_advance_right_rcsd_road(road: dict[str, Any]) -> bool:
    return is_advance_right_turn_road(dict(road.get("properties") or {}), formway_bit=ADVANCE_RIGHT_FORMWAY_BIT)


def _is_advance_right_swsd_road(road: dict[str, Any]) -> bool:
    return is_advance_right_turn_road(dict(road.get("properties") or {}), formway_bit=ADVANCE_RIGHT_FORMWAY_BIT)
