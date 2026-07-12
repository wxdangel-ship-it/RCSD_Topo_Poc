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


from .step3_advance_right_support import (
    _node_mainnodeid_text,
    _coerce_id_value,
    _append_unique_segments,
    _road_endpoint_node_ids,
    _index_by_id,
    _feature_id,
    _safe_normalize,
    _parse_list,
    _id_sort_key,
    _connected_road_component,
    _trim_component_to_boundary_roads,
    _append_post_advance_right_roads_to_units,
    _node_to_road_ids,
    _has_incident_rcsd_road_in_mainnode_group,
    _mainnode_group_key,
    _mainnode_group_node_ids,
    _global_added_rcsd_road_ids,
    _is_rcsd_contract_road,
    _segments_touching_nodes,
    _road_ids_endpoint_nodes,
    _mixed_swsd_boundary_nodes,
    _snap_rcsd_component_to_retained_swsd,
    _nearest_selected_advance_midpoint,
    _nearest_preferred_rcsd_projection,
    _nearest_selected_rcsd_projection,
    _dedupe_midroad_split_points,
    _nearby_generated_projection_node_id,
    _split_rcsd_advance_road_at_existing_nodes,
    _replace_feature_by_id,
    _replace_rcsd_road_in_units,
    _feature_line,
    _road_endpoint_points,
    _snap_road_endpoints,
    _snap_road_node_to_point,
    _coord_with_snapped_xy,
    _new_post_advance_rcsd_node,
    _next_numeric_id,
    _canonical_road_endpoint_ids,
    _is_advance_right_rcsd_road,
    _is_advance_right_swsd_road,
)

from .step3_advance_right_common import (
    _empty_contract_stats,
    _units_by_junction,
    _detached_semantic_node_contexts,
    _swsd_attachment_node_contexts,
    _augment_swsd_attachment_node_contexts_from_incident_roads,
    _context_units,
    _unique_units,
    _selected_rcsd_road_ids,
    _selected_non_advance_rcsd_road_ids,
    _normalize_missing_swsd_mainnode,
    _snap_retained_swsd_node_to_point,
    _feature_point,
    _apply_contract_split_points,
    _retained_node_segments_by_node,
    _append_rcsd_road_to_units,
    _contract_audit_row,
    _unit_segment_ids,
    _generated_node_mainnode_id,
    _nearest_mapped_rcsd_node_projection,
    _nearby_relation_mainnode_id,
    _nearby_road_endpoint_mainnode_id,
    _mapped_rcsd_nodes_for_swsd_node,
    _assign_generated_node_relation_mainnode,
)

from .step3_advance_right_postprocess import (
    _retain_post_advance_right_swsd_carriers,
    _incident_segment_ids_by_node,
    _advance_right_touches_replaced_and_retained_segments,
    _apply_post_advance_right_attachments,
    _empty_post_advance_right_stats,
    _post_advance_right_bridge_roads,
    _post_advance_right_attached_roads,
    _post_advance_right_paired_advance_roads,
    _post_advance_road_crosses_retained_non_advance_swsd,
    _apply_post_advance_right_midroad_attachments,
    _apply_swsd_advance_carrier_rcsd_nodes,
)

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
    replacement_segment_ids = {str(getattr(unit, "segment_id", "")) for unit in passed_units}
    direct_node_contexts = _swsd_attachment_node_contexts(
        swsd_segments,
        set(units_by_c),
        replacement_segment_ids=replacement_segment_ids,
    )
    node_contexts = _augment_swsd_attachment_node_contexts_from_incident_roads(
        direct_node_contexts,
        swsd_segments=swsd_segments,
        swsd_roads=swsd_roads,
        replacement_c_ids=set(units_by_c),
        replacement_segment_ids=replacement_segment_ids,
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
            has_dedicated_advance_right_segment = (
                str(props.get("segment_type") or "") == "advance_right"
                or bool(road_segment_ids)
                and all(segment_id.startswith("advance_right_") for segment_id in road_segment_ids)
            )
            max_gap_m = (
                1.0
                if road_segment_ids
                and node_id in direct_node_contexts
                and not has_dedicated_advance_right_segment
                else RETAINED_SWSD_ATTACHMENT_MAX_GAP_M
            )
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
