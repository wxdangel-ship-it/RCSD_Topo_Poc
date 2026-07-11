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

def _retain_post_advance_right_swsd_carriers(
    units: list[ReplacementUnit],
    *,
    swsd_roads: list[dict[str, Any]],
    rcsd_roads: list[dict[str, Any]],
) -> dict[str, int]:
    swsd_road_by_id = _index_by_id(swsd_roads)
    replacement_segment_ids = {str(getattr(unit, "segment_id", "")) for unit in units if getattr(unit, "status", "") == "passed"}
    incident_segments_by_node = _incident_segment_ids_by_node(swsd_roads)
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
            is_mixed_carrier = _advance_right_touches_replaced_and_retained_segments(
                road,
                replacement_segment_ids=replacement_segment_ids,
                incident_segments_by_node=incident_segments_by_node,
            )
            if has_near_rcsd_advance and not is_mixed_carrier:
                removed.append(road_id)
                continue
            if is_mixed_carrier:
                road.setdefault("properties", {})["t06_mixed_advance_right_carrier"] = 1
            retained.append(road_id)
        if retained:
            retained_count += len(retained)
            unit.retained_detached_swsd_road_ids = unique_preserve_order(
                [*unit.retained_detached_swsd_road_ids, *retained]
            )
            unit.swsd_road_ids = unique_preserve_order(removed)
    return {"retained_road_count": retained_count}


def _incident_segment_ids_by_node(swsd_roads: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for road in swsd_roads:
        props = dict(road.get("properties") or {})
        segment_ids = _parse_list(props.get("segmentid") or props.get("segment_id") or props.get("swsd_segment_id"))
        for node_id in _road_endpoint_node_ids(road):
            result[node_id] = unique_preserve_order([*result[node_id], *segment_ids])
    return dict(result)


def _advance_right_touches_replaced_and_retained_segments(
    road: dict[str, Any],
    *,
    replacement_segment_ids: set[str],
    incident_segments_by_node: dict[str, list[str]],
) -> bool:
    endpoint_segments = [
        incident_segments_by_node.get(node_id, [])
        for node_id in _road_endpoint_node_ids(road)
    ]
    touches_replaced = any(segment_id in replacement_segment_ids for segments in endpoint_segments for segment_id in segments)
    touches_retained = any(segment_id not in replacement_segment_ids for segments in endpoint_segments for segment_id in segments)
    return touches_replaced and touches_retained


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
