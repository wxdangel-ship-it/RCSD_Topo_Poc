from __future__ import annotations

from collections import defaultdict
from typing import Any

from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order


SECOND_DEGREE_BRIDGE_RISK = "second_degree_unreplaced_rcsd_bridge_fallback"


def apply_unreplaced_second_degree_bridge_fallback(
    units: list[Any],
    *,
    rcsd_roads: list[dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
    added_road_to_segments: dict[str, list[str]],
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
    return stats


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
            if road_id not in unit.rcsd_road_ids:
                unit.rcsd_road_ids.append(road_id)
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
