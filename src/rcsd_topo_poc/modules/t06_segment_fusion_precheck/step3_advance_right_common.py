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


def _swsd_attachment_node_contexts(
    swsd_segments: list[dict[str, Any]],
    replacement_c_ids: set[str],
    *,
    replacement_segment_ids: set[str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for segment in swsd_segments:
        if _feature_id(segment) not in replacement_segment_ids:
            continue
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
    replacement_segment_ids: set[str],
) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for node_id, c_ids in base_contexts.items():
        result[node_id] = unique_preserve_order(c_ids)

    segment_contexts: dict[str, list[str]] = {}
    for segment in swsd_segments:
        segment_id = _feature_id(segment)
        if segment_id not in replacement_segment_ids:
            continue
        props = dict(segment.get("properties") or {})
        segment_nodes = unique_preserve_order([*_parse_list(props.get("pair_nodes")), *_parse_list(props.get("junc_nodes"))])
        active_c_ids = [node_id for node_id in segment_nodes if node_id in replacement_c_ids]
        if active_c_ids:
            segment_contexts[segment_id] = unique_preserve_order(active_c_ids)

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
    replacements_by_road_id: dict[str, list[dict[str, Any]]] = {}
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
        replacements_by_road_id[road_id] = split_roads
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
    _replace_features_by_id(rcsd_roads, replacements_by_road_id)
    return {
        "rcsd_split_original_road_count": len(split_original_ids),
        "rcsd_split_road_count": len(split_road_to_segments),
    }


def _replace_features_by_id(
    features: list[dict[str, Any]],
    replacements_by_id: dict[str, list[dict[str, Any]]],
) -> None:
    if not replacements_by_id:
        return
    remaining = dict(replacements_by_id)
    replaced: list[dict[str, Any]] = []
    for item in features:
        replacements = remaining.pop(_feature_id(item), None)
        if replacements is None:
            replaced.append(item)
        else:
            replaced.extend(replacements)
    for replacements in remaining.values():
        replaced.extend(replacements)
    features[:] = replaced


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
