from __future__ import annotations

from collections import defaultdict
from typing import Any

from .parsing import ParseError, normalize_id, parse_id_list, parse_positive_int, unique_preserve_order

COMPLEX_JUNCTION_KIND_2 = 128


def apply_special_junction_internal_swsd_replacement(
    groups: list[Any],
    passed_unit_ids: set[str],
    swsd_roads: list[dict[str, Any]],
    swsd_nodes: list[dict[str, Any]],
    removed_road_to_segments: dict[str, list[str]],
    removed_node_to_segments: dict[str, list[str]],
    added_road_to_segments: dict[str, list[str]],
) -> dict[str, int]:
    semantic_by_node, complex_ids = _swsd_semantic_index(swsd_nodes)
    if not complex_ids:
        return _stats()
    retained_endpoint_nodes = _retained_endpoint_nodes(swsd_roads, set(removed_road_to_segments))
    removed_roads = 0
    affected_groups = 0
    for group in groups:
        junction_id = _safe_id(getattr(group, "special_junction_id", ""))
        if junction_id not in complex_ids or not _has_rcsd_context(group):
            continue
        associated = unique_preserve_order(str(item) for item in getattr(group, "associated_segment_ids", []) if str(item) in passed_unit_ids)
        if not associated or set(associated) != set(getattr(group, "associated_segment_ids", [])):
            continue
        if not _has_added_rcsd_for_segments(added_road_to_segments, set(associated)):
            continue
        group_removed = 0
        for road in swsd_roads:
            road_id = _safe_id((road.get("properties") or {}).get("id"))
            if not road_id or road_id in removed_road_to_segments or _road_has_segment(road):
                continue
            endpoints = _road_endpoint_ids(road)
            if len(endpoints) != 2 or endpoints[0] == endpoints[1]:
                continue
            if {semantic_by_node.get(endpoints[0]), semantic_by_node.get(endpoints[1])} != {junction_id}:
                continue
            removed_road_to_segments[road_id] = list(associated)
            retained_endpoint_nodes = _retained_endpoint_nodes(swsd_roads, set(removed_road_to_segments))
            for node_id in endpoints:
                if node_id not in retained_endpoint_nodes:
                    removed_node_to_segments[node_id] = unique_preserve_order([*removed_node_to_segments.get(node_id, []), *associated])
            group_removed += 1
        if group_removed:
            removed_roads += group_removed
            affected_groups += 1
    return _stats(affected_groups, removed_roads)


def _swsd_semantic_index(nodes: list[dict[str, Any]]) -> tuple[dict[str, str], set[str]]:
    semantic_by_node: dict[str, str] = {}
    complex_ids: set[str] = set()
    for node in nodes:
        props = dict(node.get("properties") or {})
        node_id = _safe_id(props.get("id"))
        if not node_id:
            continue
        mainnode = parse_positive_int(props.get("mainnodeid"))
        semantic_id = str(mainnode) if mainnode is not None else node_id
        semantic_by_node[node_id] = semantic_id
        for subnode_id in _parse_ids(props.get("subnodeid")):
            semantic_by_node[subnode_id] = semantic_id
        if _coerce_int(props.get("kind_2")) == COMPLEX_JUNCTION_KIND_2:
            complex_ids.add(semantic_id)
    return semantic_by_node, complex_ids


def _has_rcsd_context(group: Any) -> bool:
    return bool(getattr(group, "rcsd_junction_node_ids", []) or getattr(group, "rcsd_junction_road_ids", []))


def _has_added_rcsd_for_segments(added_road_to_segments: dict[str, list[str]], segment_ids: set[str]) -> bool:
    return any(segment_ids.intersection(str(item) for item in segments) for segments in added_road_to_segments.values())


def _road_has_segment(road: dict[str, Any]) -> bool:
    value = (road.get("properties") or {}).get("segmentid")
    return value not in (None, "", "None")


def _road_endpoint_ids(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    return unique_preserve_order(_safe_id(props.get(name)) for name in ("snodeid", "enodeid") if _safe_id(props.get(name)))


def _retained_endpoint_nodes(roads: list[dict[str, Any]], removed_road_ids: set[str]) -> set[str]:
    result: set[str] = set()
    for road in roads:
        road_id = _safe_id((road.get("properties") or {}).get("id"))
        if not road_id or road_id in removed_road_ids:
            continue
        result.update(_road_endpoint_ids(road))
    return result


def _safe_id(value: Any) -> str:
    try:
        return normalize_id(value)
    except ParseError:
        return ""


def _parse_ids(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _coerce_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None


def _stats(group_count: int = 0, road_count: int = 0) -> dict[str, int]:
    return {
        "special_junction_internal_swsd_group_count": group_count,
        "special_junction_internal_swsd_removed_road_count": road_count,
    }
