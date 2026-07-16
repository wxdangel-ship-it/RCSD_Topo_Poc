from __future__ import annotations

from collections import defaultdict
from typing import Any

from shapely.geometry import shape

from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order


SECOND_DEGREE_BRIDGE_RISK = "second_degree_unreplaced_rcsd_bridge_fallback"
GEOMETRY_COMPONENT_RISK = "geometry_matched_unreplaced_rcsd_component_fallback"
GEOMETRY_COMPONENT_BUFFER_M = 20.0
GEOMETRY_COMPONENT_MAX_DISTANCE_M = 3.0
GEOMETRY_COMPONENT_MIN_COVER_RATIO = 0.99


def apply_unreplaced_second_degree_bridge_fallback(
    units: list[Any],
    *,
    rcsd_roads: list[dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
    added_road_to_segments: dict[str, list[str]],
    blocked_road_ids: set[str] | None = None,
    replacement_plan_rows: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    stats = {
        "second_degree_bridge_candidate_component_count": 0,
        "second_degree_bridge_added_group_count": 0,
        "second_degree_bridge_added_road_count": 0,
        "second_degree_bridge_added_segment_count": 0,
        "second_degree_bridge_blocked_non_linear_component_count": 0,
        "second_degree_bridge_blocked_open_endpoint_count": 0,
        "second_degree_bridge_blocked_single_boundary_road_count": 0,
        "second_degree_bridge_blocked_anchor_endpoint_count": 0,
        "second_degree_bridge_blocked_ambiguous_segment_count": 0,
    }
    edges = _road_edges(rcsd_roads, canonicalizer)
    added_before = set(added_road_to_segments)
    unadded_edges = {road_id: edge for road_id, edge in edges.items() if road_id not in added_before}
    if not unadded_edges:
        return stats

    incident_segments_by_node = _incident_segments_by_node(edges, added_road_to_segments)
    unit_by_segment = {
        str(unit.segment_id): unit
        for unit in units
        if getattr(unit, "status", "passed") == "passed"
    }
    touched_segments: set[str] = set()
    for component in _connected_unadded_components(unadded_edges):
        stats["second_degree_bridge_candidate_component_count"] += 1
        terminal_nodes = _linear_component_terminal_nodes(component["degree"])
        if terminal_nodes is None:
            added_direct_count = _apply_direct_bridge_roads_from_non_linear_component(
                component["road_ids"],
                edges=edges,
                incident_segments_by_node=incident_segments_by_node,
                unit_by_segment=unit_by_segment,
                canonicalizer=canonicalizer,
                added_road_to_segments=added_road_to_segments,
                touched_segments=touched_segments,
                stats=stats,
            )
            if not added_direct_count:
                stats["second_degree_bridge_blocked_non_linear_component_count"] += 1
            continue
        candidate_segment_ids, has_open_endpoint, has_single_boundary, has_anchor_endpoint, has_ambiguous_endpoint = _candidate_terminal_segments(
            terminal_nodes,
            incident_segments_by_node,
            unit_by_segment,
            canonicalizer,
        )
        if has_open_endpoint:
            stats["second_degree_bridge_blocked_open_endpoint_count"] += 1
            continue
        if has_single_boundary:
            stats["second_degree_bridge_blocked_single_boundary_road_count"] += 1
            continue
        if has_anchor_endpoint:
            stats["second_degree_bridge_blocked_anchor_endpoint_count"] += 1
            continue
        if has_ambiguous_endpoint or not candidate_segment_ids:
            stats["second_degree_bridge_blocked_ambiguous_segment_count"] += 1
            continue
        _add_bridge_roads_to_segments(
            component["road_ids"],
            candidate_segment_ids,
            unit_by_segment=unit_by_segment,
            added_road_to_segments=added_road_to_segments,
            touched_segments=touched_segments,
        )
        stats["second_degree_bridge_added_group_count"] += 1
        stats["second_degree_bridge_added_road_count"] += len(component["road_ids"])
    stats["second_degree_bridge_added_segment_count"] = len(touched_segments)
    stats.update(
        _apply_geometry_matched_component_fallback(
            units,
            rcsd_roads=rcsd_roads,
            canonicalizer=canonicalizer,
            added_road_to_segments=added_road_to_segments,
            blocked_road_ids=_blocked_road_ids(blocked_road_ids, replacement_plan_rows),
        )
    )
    return stats


def _apply_geometry_matched_component_fallback(
    units: list[Any],
    *,
    rcsd_roads: list[dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
    added_road_to_segments: dict[str, list[str]],
    blocked_road_ids: set[str] | None,
) -> dict[str, int]:
    stats = {
        "geometry_component_candidate_road_count": 0,
        "geometry_component_added_group_count": 0,
        "geometry_component_added_road_count": 0,
        "geometry_component_added_segment_count": 0,
        "geometry_component_blocked_open_component_count": 0,
        "geometry_component_blocked_non_linear_component_count": 0,
        "geometry_component_blocked_existing_boundary_count": 0,
    }
    edges = _road_edges(rcsd_roads, canonicalizer)
    road_by_id = _road_by_id(rcsd_roads)
    unit_by_segment: dict[str, Any] = {}
    unit_geometry_by_segment: dict[str, Any] = {}
    for unit in units:
        unit_geometry = _as_geometry(getattr(unit, "geometry", None))
        if getattr(unit, "status", "passed") != "passed" or unit_geometry is None:
            continue
        segment_id = str(unit.segment_id)
        unit_by_segment[segment_id] = unit
        unit_geometry_by_segment[segment_id] = unit_geometry
    if not edges or not unit_by_segment:
        return stats

    incident_segments_by_node = _incident_segments_by_node(edges, added_road_to_segments)
    unit_nodes_by_segment = _unit_nodes_by_segment(unit_by_segment, edges, canonicalizer)
    road_ids_by_node = _road_ids_by_node(edges)
    scope_nodes_by_segment = _scope_nodes_by_segment(incident_segments_by_node, unit_nodes_by_segment)
    added_road_ids = set(added_road_to_segments) | set(blocked_road_ids or [])
    candidate_road_ids: set[str] = set()
    touched_segments: set[str] = set()

    for segment_id, unit in unit_by_segment.items():
        unit_geometry = unit_geometry_by_segment[segment_id]
        candidate_edges = _geometry_matched_edges_reachable_from_scope(
            edges=edges,
            road_by_id=road_by_id,
            road_ids_by_node=road_ids_by_node,
            scope_nodes=scope_nodes_by_segment.get(segment_id, set()),
            unit_geometry=unit_geometry,
            added_road_ids=added_road_ids,
        )
        candidate_road_ids.update(candidate_edges)
        for component in _connected_unadded_components(candidate_edges):
            terminal_nodes = _linear_component_terminal_nodes(component["degree"])
            if terminal_nodes is None:
                stats["geometry_component_blocked_non_linear_component_count"] += 1
                continue
            if not all(
                _terminal_matches_unit_scope(
                    terminal_node,
                    segment_id=segment_id,
                    incident_segments_by_node=incident_segments_by_node,
                    unit_nodes_by_segment=unit_nodes_by_segment,
                )
                for terminal_node in terminal_nodes
            ):
                stats["geometry_component_blocked_open_component_count"] += 1
                continue
            if _has_existing_direct_boundary_road(
                terminal_nodes,
                segment_id=segment_id,
                edges=edges,
                added_road_to_segments=added_road_to_segments,
            ):
                stats["geometry_component_blocked_existing_boundary_count"] += 1
                continue
            _add_geometry_component_to_unit(
                component["road_ids"],
                segment_id,
                unit=unit,
                added_road_to_segments=added_road_to_segments,
                touched_segments=touched_segments,
            )
            added_road_ids.update(component["road_ids"])
            stats["geometry_component_added_group_count"] += 1
            stats["geometry_component_added_road_count"] += len(component["road_ids"])

    stats["geometry_component_candidate_road_count"] = len(candidate_road_ids)
    stats["geometry_component_added_segment_count"] = len(touched_segments)
    return stats


def _blocked_road_ids(
    explicit_road_ids: set[str] | None,
    replacement_plan_rows: list[dict[str, Any]] | None,
) -> set[str]:
    result = set(explicit_road_ids or [])
    for row in replacement_plan_rows or []:
        props = row.get("properties") or {}
        if props.get("plan_status") == "blocked":
            result.update(_parse_list(props.get("rcsd_road_ids")))
    return result


def _geometry_matched_edges_reachable_from_scope(
    *,
    edges: dict[str, tuple[str, str]],
    road_by_id: dict[str, dict[str, Any]],
    road_ids_by_node: dict[str, list[str]],
    scope_nodes: set[str],
    unit_geometry: Any,
    added_road_ids: set[str],
) -> dict[str, tuple[str, str]]:
    if not scope_nodes:
        return {}
    unit_buffer_cache: list[Any] = []
    pending: list[str] = []
    seen: set[str] = set()
    for node_id in scope_nodes:
        for road_id in road_ids_by_node.get(node_id, []):
            if road_id in added_road_ids or road_id in seen:
                continue
            seen.add(road_id)
            pending.append(road_id)

    result: dict[str, tuple[str, str]] = {}
    while pending:
        road_id = pending.pop(0)
        if road_id in added_road_ids:
            continue
        edge = edges.get(road_id)
        if edge is None or not _road_geometry_matches_unit(
            road_by_id.get(road_id),
            unit_geometry,
            unit_buffer_cache=unit_buffer_cache,
        ):
            continue
        result[road_id] = edge
        for node_id in edge:
            for next_road_id in road_ids_by_node.get(node_id, []):
                if next_road_id in added_road_ids or next_road_id in seen:
                    continue
                seen.add(next_road_id)
                pending.append(next_road_id)
    return result


def _road_geometry_matches_unit(
    road: dict[str, Any] | None,
    unit_geometry: Any,
    *,
    unit_buffer_cache: list[Any] | None = None,
) -> bool:
    if road is None:
        return False
    road_geometry = _as_geometry(road.get("geometry"))
    unit_geometry = _as_geometry(unit_geometry)
    if road_geometry is None or unit_geometry is None:
        return False
    road_length = float(getattr(road_geometry, "length", 0.0) or 0.0)
    if road_length <= 0.0:
        return False
    if float(road_geometry.distance(unit_geometry)) > GEOMETRY_COMPONENT_MAX_DISTANCE_M:
        return False
    try:
        if unit_buffer_cache is None:
            buffered_unit = unit_geometry.buffer(GEOMETRY_COMPONENT_BUFFER_M)
        else:
            if not unit_buffer_cache:
                unit_buffer_cache.append(unit_geometry.buffer(GEOMETRY_COMPONENT_BUFFER_M))
            buffered_unit = unit_buffer_cache[0]
        covered_length = float(road_geometry.intersection(buffered_unit).length)
    except Exception:
        return False
    return covered_length / road_length >= GEOMETRY_COMPONENT_MIN_COVER_RATIO


def _road_by_id(roads: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for road in roads:
        try:
            result[_feature_id(road)] = road
        except ParseError:
            continue
    return result


def _as_geometry(value: Any) -> Any:
    if _is_geometry(value):
        return value
    if isinstance(value, dict):
        try:
            geometry = shape(value)
        except Exception:
            return None
        return geometry if _is_geometry(geometry) else None
    return None


def _is_geometry(geometry: Any) -> bool:
    return (
        geometry is not None
        and hasattr(geometry, "distance")
        and hasattr(geometry, "buffer")
        and hasattr(geometry, "intersection")
        and not bool(getattr(geometry, "is_empty", False))
    )


def _road_ids_by_node(edges: dict[str, tuple[str, str]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for road_id, edge in edges.items():
        for node_id in edge:
            result[node_id].append(road_id)
    return result


def _scope_nodes_by_segment(
    incident_segments_by_node: dict[str, dict[str, list[str]]],
    unit_nodes_by_segment: dict[str, set[str]],
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for node_id, by_segment in incident_segments_by_node.items():
        for segment_id in by_segment:
            result[str(segment_id)].add(node_id)
    for segment_id, node_ids in unit_nodes_by_segment.items():
        result[str(segment_id)].update(node_ids)
    return dict(result)


def _unit_nodes_by_segment(
    unit_by_segment: dict[str, Any],
    edges: dict[str, tuple[str, str]],
    canonicalizer: NodeCanonicalizer,
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    for segment_id, unit in unit_by_segment.items():
        nodes: set[str] = set()
        for attr in ("rcsd_pair_nodes", "rcsd_junc_nodes", "retained_node_ids", "optional_allowed_rcsd_nodes"):
            for node_id in _parse_list(getattr(unit, attr, [])):
                try:
                    nodes.add(canonicalizer.canonicalize(node_id))
                except ParseError:
                    continue
        for road_id in _parse_list(getattr(unit, "rcsd_road_ids", [])):
            edge = edges.get(road_id)
            if edge is not None:
                nodes.update(edge)
        result[segment_id] = nodes
    return result


def _terminal_matches_unit_scope(
    terminal_node: str,
    *,
    segment_id: str,
    incident_segments_by_node: dict[str, dict[str, list[str]]],
    unit_nodes_by_segment: dict[str, set[str]],
) -> bool:
    return bool(incident_segments_by_node.get(terminal_node, {}).get(segment_id)) or terminal_node in unit_nodes_by_segment.get(segment_id, set())


def _has_existing_direct_boundary_road(
    terminal_nodes: list[str],
    *,
    segment_id: str,
    edges: dict[str, tuple[str, str]],
    added_road_to_segments: dict[str, list[str]],
) -> bool:
    terminal_set = set(terminal_nodes)
    for road_id, segment_ids in added_road_to_segments.items():
        if segment_id not in segment_ids:
            continue
        edge = edges.get(road_id)
        if edge is not None and set(edge) == terminal_set:
            return True
    return False


def _add_geometry_component_to_unit(
    road_ids: list[str],
    segment_id: str,
    *,
    unit: Any,
    added_road_to_segments: dict[str, list[str]],
    touched_segments: set[str],
) -> None:
    for road_id in road_ids:
        segment_list = added_road_to_segments.setdefault(road_id, [])
        if segment_id not in segment_list:
            segment_list.append(segment_id)
    unit.risk_flags = unique_preserve_order([*getattr(unit, "risk_flags", []), GEOMETRY_COMPONENT_RISK])
    touched_segments.add(segment_id)


def _apply_direct_bridge_roads_from_non_linear_component(
    road_ids: list[str],
    *,
    edges: dict[str, tuple[str, str]],
    incident_segments_by_node: dict[str, dict[str, list[str]]],
    unit_by_segment: dict[str, Any],
    canonicalizer: NodeCanonicalizer,
    added_road_to_segments: dict[str, list[str]],
    touched_segments: set[str],
    stats: dict[str, int],
) -> int:
    added_count = 0
    for road_id in road_ids:
        edge = edges.get(road_id)
        if edge is None:
            continue
        candidate_segment_ids, has_open_endpoint, has_single_boundary, has_anchor_endpoint, has_ambiguous_endpoint = (
            _candidate_terminal_segments(
                list(edge),
                incident_segments_by_node,
                unit_by_segment,
                canonicalizer,
            )
        )
        if has_open_endpoint or has_single_boundary or has_anchor_endpoint or has_ambiguous_endpoint or not candidate_segment_ids:
            continue
        _add_bridge_roads_to_segments(
            [road_id],
            candidate_segment_ids,
            unit_by_segment=unit_by_segment,
            added_road_to_segments=added_road_to_segments,
            touched_segments=touched_segments,
        )
        stats["second_degree_bridge_added_group_count"] += 1
        stats["second_degree_bridge_added_road_count"] += 1
        added_count += 1
    return added_count


def _add_bridge_roads_to_segments(
    road_ids: list[str],
    segment_ids: list[str],
    *,
    unit_by_segment: dict[str, Any],
    added_road_to_segments: dict[str, list[str]],
    touched_segments: set[str],
) -> None:
    for segment_id in segment_ids:
        unit = unit_by_segment[segment_id]
        for road_id in road_ids:
            segment_list = added_road_to_segments.setdefault(road_id, [])
            if segment_id not in segment_list:
                segment_list.append(segment_id)
        unit.risk_flags = unique_preserve_order([*getattr(unit, "risk_flags", []), SECOND_DEGREE_BRIDGE_RISK])
        touched_segments.add(segment_id)


def _road_edges(
    roads: list[dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for road in roads:
        try:
            road_id = _feature_id(road)
            endpoints = _canonical_endpoint_pair(road, canonicalizer)
        except ParseError:
            continue
        if endpoints is None or endpoints[0] == endpoints[1]:
            continue
        result[road_id] = endpoints
    return result


def _canonical_endpoint_pair(
    road: dict[str, Any],
    canonicalizer: NodeCanonicalizer,
) -> tuple[str, str] | None:
    props = dict(road.get("properties") or {})
    nodes: list[str] = []
    for field in ("snodeid", "enodeid"):
        nodes.append(canonicalizer.canonicalize(props.get(field)))
    return (nodes[0], nodes[1]) if len(nodes) == 2 else None


def _incident_segments_by_node(
    edges: dict[str, tuple[str, str]],
    added_road_to_segments: dict[str, list[str]],
) -> dict[str, dict[str, list[str]]]:
    result: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for road_id, segment_ids in added_road_to_segments.items():
        edge = edges.get(road_id)
        if edge is None:
            continue
        for node_id in edge:
            for segment_id in segment_ids:
                if road_id not in result[node_id][str(segment_id)]:
                    result[node_id][str(segment_id)].append(road_id)
    return result


def _connected_unadded_components(
    edges: dict[str, tuple[str, str]],
) -> list[dict[str, Any]]:
    road_ids_by_node: dict[str, list[str]] = defaultdict(list)
    for road_id, edge in edges.items():
        for node_id in edge:
            road_ids_by_node[node_id].append(road_id)
    pending = set(edges)
    components: list[dict[str, Any]] = []
    for seed in list(edges):
        if seed not in pending:
            continue
        pending.remove(seed)
        queue = [seed]
        road_ids: list[str] = []
        degree: dict[str, int] = defaultdict(int)
        while queue:
            road_id = queue.pop(0)
            road_ids.append(road_id)
            for node_id in edges[road_id]:
                degree[node_id] += 1
                for next_road_id in road_ids_by_node[node_id]:
                    if next_road_id in pending:
                        pending.remove(next_road_id)
                        queue.append(next_road_id)
        components.append({"road_ids": road_ids, "degree": dict(degree)})
    return components


def _linear_component_terminal_nodes(degree: dict[str, int]) -> list[str] | None:
    if any(value > 2 for value in degree.values()):
        return None
    terminals = [node_id for node_id, value in degree.items() if value == 1]
    return terminals if len(terminals) == 2 else None


def _candidate_terminal_segments(
    terminal_nodes: list[str],
    incident_segments_by_node: dict[str, dict[str, list[str]]],
    unit_by_segment: dict[str, Any],
    canonicalizer: NodeCanonicalizer,
) -> tuple[list[str], bool, bool, bool, bool]:
    left, right = terminal_nodes
    left_candidates, left_open, left_anchor, left_ambiguous = _eligible_terminal_segments(
        left,
        incident_segments_by_node,
        unit_by_segment,
        canonicalizer,
    )
    right_candidates, right_open, right_anchor, right_ambiguous = _eligible_terminal_segments(
        right,
        incident_segments_by_node,
        unit_by_segment,
        canonicalizer,
    )
    if left_open or right_open:
        return [], True, False, False, False
    if left_anchor or right_anchor:
        return [], False, False, True, False
    if left_ambiguous or right_ambiguous or not left_candidates or not right_candidates:
        return [], False, False, False, True
    candidate_segment_ids = unique_preserve_order([*left_candidates, *right_candidates])
    if (
        left_candidates == right_candidates
        and len(_terminal_boundary_roads(left, right, left_candidates[0], incident_segments_by_node)) < 2
    ):
        return [], False, True, False, False
    return candidate_segment_ids, False, False, False, False


def _eligible_terminal_segments(
    terminal_node: str,
    incident_segments_by_node: dict[str, dict[str, list[str]]],
    unit_by_segment: dict[str, Any],
    canonicalizer: NodeCanonicalizer,
) -> tuple[list[str], bool, bool, bool]:
    by_segment = incident_segments_by_node.get(terminal_node, {})
    if not by_segment:
        return [], True, False, False
    road_to_segments: dict[str, list[str]] = defaultdict(list)
    anchor_blocked = False
    for segment_id in sorted(by_segment):
        unit = unit_by_segment.get(segment_id)
        if unit is None:
            continue
        if _touches_protected_unit_anchor(unit, terminal_node, canonicalizer):
            anchor_blocked = True
            continue
        for road_id in by_segment[segment_id]:
            if segment_id not in road_to_segments[road_id]:
                road_to_segments[road_id].append(segment_id)
    if not road_to_segments:
        return [], False, bool(anchor_blocked), False
    single_boundary_segments = unique_preserve_order(
        segments[0] for road_id, segments in sorted(road_to_segments.items()) if len(segments) == 1
    )
    if len(single_boundary_segments) == 1:
        return single_boundary_segments, False, False, False
    if len(single_boundary_segments) > 1:
        return [], False, False, True
    eligible = unique_preserve_order(
        segment_id
        for road_id, segments in sorted(road_to_segments.items())
        for segment_id in segments
    )
    if len(eligible) > 1:
        return [], False, False, True
    return eligible, False, bool(anchor_blocked and not eligible), False


def _terminal_boundary_roads(
    left: str,
    right: str,
    segment_id: str,
    incident_segments_by_node: dict[str, dict[str, list[str]]],
) -> set[str]:
    return set(incident_segments_by_node.get(left, {}).get(segment_id, [])) | set(
        incident_segments_by_node.get(right, {}).get(segment_id, [])
    )


def _touches_protected_unit_anchor(
    unit: Any,
    terminal_node: str,
    canonicalizer: NodeCanonicalizer,
) -> bool:
    protected = _canonical_unit_anchor_nodes(unit, canonicalizer)
    return terminal_node in protected


def _canonical_unit_anchor_nodes(unit: Any, canonicalizer: NodeCanonicalizer) -> set[str]:
    result: set[str] = set()
    for attr in ("rcsd_pair_nodes", "rcsd_junc_nodes"):
        for node_id in _parse_list(getattr(unit, attr, [])):
            try:
                result.add(canonicalizer.canonicalize(node_id))
            except ParseError:
                continue
    return result


def _feature_id(feature: dict[str, Any]) -> str:
    return normalize_id((feature.get("properties") or {}).get("id"))


def _parse_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []
