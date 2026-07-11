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
