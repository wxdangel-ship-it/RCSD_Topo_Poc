from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

from shapely.geometry import LineString, Point
from shapely.ops import substring, unary_union
from shapely.strtree import STRtree

from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order
from .road_attributes import is_advance_right_turn_road


TOPOLOGY_SUPPLEMENT_SPLIT_REASON = "topology_supplement_from_swsd"
MIXED_REPLACEMENT_REQUIRES_SWSD_CARRIER_REASON = "mixed_replacement_requires_swsd_carrier"
MIXED_ADVANCE_RIGHT_RETAINED_SPLIT_REASON = "mixed_advance_right_retained_swsd_side"
FORMAL_REPLACEMENT_CORRIDOR_UNAVAILABLE_REASON = "formal_replacement_corridor_coverage_unavailable"
GROUP_FORMAL_REPLACEMENT_CORRIDOR_UNAVAILABLE_REASON = "group_formal_replacement_corridor_coverage_unavailable"
SEGMENT_CORRIDOR_BUFFER_M = 15.0
SEGMENT_MAX_UNCOVERED_RATIO = 0.05
SEGMENT_MIN_UNCOVERED_LENGTH_M = 20.0
SURFACE_AWARE_FORMAL_CORRIDOR_BUFFER_M = 75.0
GROUP_SEGMENT_MAX_UNCOVERED_RATIO = 0.50
GROUP_SEGMENT_MIN_UNCOVERED_LENGTH_M = 20.0
EXISTING_ADVANCE_CORRIDOR_BUFFER_M = 5.0
EXISTING_ADVANCE_CORRIDOR_MIN_COVERAGE_RATIO = 0.85
T05_RELATION_JUNCTION_RELEASE_RISK = "junction_alignment_t05_relation_release"
SURFACE_AWARE_FORMAL_CORRIDOR_RELEASE_FLAGS = {
    "junction_alignment_surface_audit_release",
    T05_RELATION_JUNCTION_RELEASE_RISK,
}
SURFACE_AWARE_FORMAL_CORRIDOR_RELEASE_RISK_FLAGS = [
    "surface_aware_formal_corridor_release",
    "manual_review_required",
]
JUNCTION_SURFACE_COVERAGE_RELEASE_RISK_FLAGS = [
    "formal_corridor_gap_inside_anchored_junction_surface",
    "junction_surface_coverage_release",
    "manual_review_required",
]
FORMAL_REPLACEMENT_CORRIDOR_REVIEW_RISK_FLAGS = [
    "formal_replacement_corridor_coverage_review",
    FORMAL_REPLACEMENT_CORRIDOR_UNAVAILABLE_REASON,
    "manual_review_required",
]
SWSD_BUFFER_CORRIDOR_RELEASE_RISK = "swsd_buffer_corridor_controlled_release"


def _attachment_nodes_by_swsd_road_endpoint(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        props = dict(row.get("properties") or {})
        action = str(props.get("action") or "")
        if not action.startswith(("split_", "reuse_")):
            continue
        road_id = _safe_id(props.get("swsd_road_id") or props.get("swsd_advance_road_id"))
        swsd_node_id = _safe_id(props.get("swsd_node_id"))
        rcsd_node_id = _safe_id(props.get("rcsd_node_id") or props.get("generated_rcsd_node_id"))
        if road_id and swsd_node_id and rcsd_node_id and rcsd_node_id not in result[(road_id, swsd_node_id)]:
            result[(road_id, swsd_node_id)].append(rcsd_node_id)
    return dict(result)


def _replacement_segment_ids_by_swsd_road(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        props = dict(row.get("properties") or {})
        action = str(props.get("action") or "")
        if not action.startswith(("split_", "reuse_")):
            continue
        road_id = _safe_id(props.get("swsd_road_id") or props.get("swsd_advance_road_id"))
        if not road_id:
            continue
        for segment_id in _safe_id_list(props.get("replacement_segment_ids")):
            if segment_id not in result[road_id]:
                result[road_id].append(segment_id)
    return dict(result)


def _mapped_rcsd_node_id(
    road_id: str,
    swsd_node_id: str,
    attachment_nodes: dict[tuple[str, str], list[str]],
    swsd_node_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
) -> str | None:
    candidates = attachment_nodes.get((str(road_id), str(swsd_node_id)), [])
    if candidates:
        return candidates[0]
    node = swsd_node_by_id.get(str(swsd_node_id))
    mainnode_id = _safe_id((node.get("properties") or {}).get("mainnodeid")) if node else None
    return mainnode_id if mainnode_id in rcsd_node_by_id else None


def _topology_supplement_road(
    swsd_road: dict[str, Any],
    *,
    new_id: str,
    original_id: str,
    mapped_node_ids: list[str],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, Any] | None:
    line = _feature_line(swsd_road)
    if line is None or len(mapped_node_ids) < 2:
        return None
    start_point = _node_point(rcsd_node_by_id.get(mapped_node_ids[0]))
    end_point = _node_point(rcsd_node_by_id.get(mapped_node_ids[1]))
    if start_point is None or end_point is None:
        return None
    props = dict(deepcopy(swsd_road.get("properties") or {}))
    props.update(
        {
            "id": new_id,
            "snodeid": mapped_node_ids[0],
            "enodeid": mapped_node_ids[1],
            source_field_name: rcsd_source_value,
            "source_road_id": str(original_id),
            "t06_split_original_road_id": str(original_id),
            "t06_split_reason": TOPOLOGY_SUPPLEMENT_SPLIT_REASON,
        }
    )
    return {"properties": props, "geometry": _line_with_snapped_endpoints(line, start_point, end_point)}


def _line_with_snapped_endpoints(line: LineString, start_point: Point, end_point: Point) -> LineString:
    coords = list(line.coords)
    if not coords:
        return line
    coords[0] = _coord_with_xy(coords[0], start_point)
    coords[-1] = _coord_with_xy(coords[-1], end_point)
    return LineString(coords)


def _coord_with_xy(original: tuple[float, ...], point: Point) -> tuple[float, ...]:
    x, y = point.coords[0][:2]
    return (x, y) if len(original) <= 2 else (x, y, *original[2:])


def _road_endpoint_node_ids(road: dict[str, Any] | None) -> list[str]:
    props = dict((road or {}).get("properties") or {})
    return [_safe_id(value) for value in (props.get("snodeid"), props.get("enodeid")) if _safe_id(value)]


def _road_segment_ids(road: dict[str, Any] | None) -> list[str]:
    props = dict((road or {}).get("properties") or {})
    return parse_id_list(
        props.get("segmentid") or props.get("segment_id") or props.get("swsd_segment_id"),
        allow_empty=True,
    )


def _is_formal_unit_body_swsd_road(unit: Any, road: dict[str, Any] | None) -> bool:
    unit_segment_id = str(getattr(unit, "segment_id", "") or getattr(unit, "swsd_segment_id", ""))
    return bool(unit_segment_id and unit_segment_id in _road_segment_ids(road))


def _incident_segment_ids_by_node(roads: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for road in roads:
        segment_ids = _road_segment_ids(road)
        for node_id in _road_endpoint_node_ids(road):
            result[node_id] = unique_preserve_order([*result[node_id], *segment_ids])
    return dict(result)


def _is_mixed_advance_right_carrier(
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


def _can_use_existing_rcsd_advance_group_for_replaced_carrier(
    road: dict[str, Any],
    *,
    rcsd_advance_road_ids: list[str],
    replacement_segment_ids: set[str],
    incident_segments_by_node: dict[str, list[str]],
) -> bool:
    if not rcsd_advance_road_ids or _road_segment_ids(road):
        return False
    endpoint_segments = unique_preserve_order(
        segment_id
        for node_id in _road_endpoint_node_ids(road)
        for segment_id in incident_segments_by_node.get(node_id, [])
    )
    return bool(endpoint_segments) and all(segment_id in replacement_segment_ids for segment_id in endpoint_segments)


def _touches_detached_node(endpoints: list[str], detached_nodes: set[str]) -> bool:
    return bool(detached_nodes.intersection(endpoints))


def _feature_line(feature: dict[str, Any]) -> LineString | None:
    geometry = feature.get("geometry")
    return geometry if isinstance(geometry, LineString) else None


def _is_advance_right_road(road: dict[str, Any]) -> bool:
    return is_advance_right_turn_road(dict(road.get("properties") or {}))


def _is_existing_rcsd_advance_candidate(road: dict[str, Any]) -> bool:
    props = dict(road.get("properties") or {})
    return props.get("t06_split_reason") != TOPOLOGY_SUPPLEMENT_SPLIT_REASON and _is_advance_right_road(road)


def _is_side_attachment_swsd_road(road: dict[str, Any] | None) -> bool:
    props = dict((road or {}).get("properties") or {})
    return str(props.get("segment_build_source") or "") == "side_attachment_merge"


def _node_point(node: dict[str, Any] | None) -> Point | None:
    geometry = node.get("geometry") if node is not None else None
    return geometry if isinstance(geometry, Point) else None


def _next_generated_road_id(original_id: str, used_road_ids: set[str]) -> str:
    index = 1
    while True:
        candidate = f"{original_id}__t06toposupp_{index}"
        if candidate not in used_road_ids:
            return candidate
        index += 1


def _safe_id(value: Any) -> str | None:
    try:
        return normalize_id(value)
    except ParseError:
        return None


def _safe_surface_id(value: Any) -> str:
    try:
        return normalize_id(value)
    except ParseError:
        return ""


def _safe_id_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value)
    except ParseError:
        return []
