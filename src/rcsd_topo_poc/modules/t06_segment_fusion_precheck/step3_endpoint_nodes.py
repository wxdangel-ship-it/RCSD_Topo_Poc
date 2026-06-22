from __future__ import annotations

from typing import Any

from shapely.geometry import LineString, MultiLineString, Point
from shapely.ops import linemerge

from .parsing import ParseError, normalize_id, unique_preserve_order


def ensure_added_rcsd_road_endpoint_nodes(
    *,
    units: list[Any],
    rcsd_roads: list[dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
) -> dict[str, int]:
    generated_count = 0
    template = dict(next(iter(rcsd_node_by_id.values())).get("properties") or {}) if rcsd_node_by_id else {}
    unit_by_segment = {unit.segment_id: unit for unit in units}
    for road_id, segment_ids in list(added_road_to_segments.items()):
        road = rcsd_road_by_id.get(road_id)
        if road is None:
            continue
        endpoint_ids = _road_endpoint_node_ids(road)
        endpoint_points = _road_endpoint_points(road)
        for node_id, point in zip(endpoint_ids, endpoint_points):
            if node_id in rcsd_node_by_id:
                continue
            node_value = _coerce_id_value(node_id)
            node = _new_node(node_value=node_value, geometry=point, template=template)
            rcsd_nodes.append(node)
            rcsd_node_by_id[node_id] = node
            generated_count += 1
            for segment_id in segment_ids:
                unit = unit_by_segment.get(segment_id)
                if unit is not None:
                    unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, node_id])
    return {"generated_node_count": generated_count}


def ensure_retained_swsd_advance_endpoint_nodes(
    *,
    swsd_roads: list[dict[str, Any]],
    swsd_nodes: list[dict[str, Any]],
    swsd_node_by_id: dict[str, dict[str, Any]],
) -> dict[str, int]:
    return _ensure_retained_swsd_endpoint_nodes(
        swsd_roads=swsd_roads,
        swsd_nodes=swsd_nodes,
        swsd_node_by_id=swsd_node_by_id,
        advance_only=True,
        generated_reason="retained_swsd_advance_missing_endpoint_node",
    )


def ensure_retained_swsd_road_endpoint_nodes(
    *,
    swsd_roads: list[dict[str, Any]],
    swsd_nodes: list[dict[str, Any]],
    swsd_node_by_id: dict[str, dict[str, Any]],
) -> dict[str, int]:
    return _ensure_retained_swsd_endpoint_nodes(
        swsd_roads=swsd_roads,
        swsd_nodes=swsd_nodes,
        swsd_node_by_id=swsd_node_by_id,
        advance_only=False,
        generated_reason="retained_swsd_road_missing_endpoint_node",
    )


def _ensure_retained_swsd_endpoint_nodes(
    *,
    swsd_roads: list[dict[str, Any]],
    swsd_nodes: list[dict[str, Any]],
    swsd_node_by_id: dict[str, dict[str, Any]],
    advance_only: bool,
    generated_reason: str,
) -> dict[str, int]:
    generated_count = 0
    template = dict(next(iter(swsd_node_by_id.values())).get("properties") or {}) if swsd_node_by_id else {}
    for road in swsd_roads:
        if advance_only and not _is_advance_right(road):
            continue
        for node_id, point in zip(_road_endpoint_node_ids(road), _road_endpoint_points(road)):
            if node_id in swsd_node_by_id:
                continue
            node_value = _coerce_id_value(node_id)
            node = _new_node(node_value=node_value, geometry=point, template=template, generated_reason=generated_reason)
            swsd_nodes.append(node)
            swsd_node_by_id[node_id] = node
            generated_count += 1
    return {"generated_node_count": generated_count}


def post_advance_road_crosses_retained_swsd(
    road: dict[str, Any],
    retained_swsd_roads: list[dict[str, Any]],
    *,
    buffer_m: float = 1.0,
    min_covered_ratio: float = 0.2,
) -> bool:
    line = road.get("geometry")
    if line is None or line.is_empty or line.length <= 0:
        return False
    line_bounds = line.bounds
    for swsd_road in retained_swsd_roads:
        swsd_line = swsd_road.get("geometry")
        if swsd_line is None or swsd_line.is_empty:
            continue
        if not _expanded_bounds_intersect(line_bounds, swsd_line.bounds, buffer_m):
            continue
        if line.intersection(swsd_line.buffer(buffer_m)).length / line.length >= min_covered_ratio:
            return True
    return False


def _expanded_bounds_intersect(
    line_bounds: tuple[float, float, float, float],
    swsd_bounds: tuple[float, float, float, float],
    buffer_m: float,
) -> bool:
    return not (
        line_bounds[2] < swsd_bounds[0] - buffer_m
        or swsd_bounds[2] + buffer_m < line_bounds[0]
        or line_bounds[3] < swsd_bounds[1] - buffer_m
        or swsd_bounds[3] + buffer_m < line_bounds[1]
    )


def _road_endpoint_node_ids(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    result: list[str] = []
    for key in ("snodeid", "enodeid"):
        try:
            result.append(normalize_id(props.get(key)))
        except ParseError:
            continue
    return result


def _road_endpoint_points(road: dict[str, Any]) -> list[Point]:
    geometry = road.get("geometry")
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
        if isinstance(merged, LineString):
            geometry = merged
        else:
            geometry = max(geometry.geoms, key=lambda item: item.length)
    if not isinstance(geometry, LineString):
        return []
    coords = list(geometry.coords)
    if not coords:
        return []
    return [Point(coords[0]), Point(coords[-1])]


def _new_node(
    *,
    node_value: Any,
    geometry: Point,
    template: dict[str, Any],
    generated_reason: str = "selected_rcsd_road_missing_endpoint_node",
) -> dict[str, Any]:
    props = {key: None for key in template}
    if "source" in template:
        props["source"] = template.get("source")
    props.update(
        {
            "id": node_value,
            "mainnodeid": node_value,
            "t06_generated_reason": generated_reason,
        }
    )
    return {"properties": props, "geometry": geometry}


def _coerce_id_value(node_id: str) -> Any:
    return int(node_id) if node_id.isdigit() else node_id


def _is_advance_right(road: dict[str, Any]) -> bool:
    try:
        return bool(int((road.get("properties") or {}).get("formway") or 0) & 128)
    except (TypeError, ValueError):
        return False
