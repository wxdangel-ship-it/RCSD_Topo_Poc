from __future__ import annotations

import heapq
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from shapely.geometry import GeometryCollection, LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .graph_builders import Edge, NodeCanonicalizer
from .parsing import ParseError, normalize_id
from .relation_mapping import RelationCheck
from .road_attributes import is_advance_right_turn_road


PATH_REFERENCE_BUFFER_M = 15.0
PATH_OFF_REFERENCE_PENALTY_MULTIPLIER = 6.0
CONNECTED_CORRIDOR_SUPPLEMENT_BUFFER_M = PATH_REFERENCE_BUFFER_M
CONNECTED_CORRIDOR_SUPPLEMENT_MAX_OUTSIDE_RATIO = 0.1
CONNECTED_CORRIDOR_SUPPLEMENT_MAX_OUTSIDE_LENGTH_M = 20.0
VISUAL_GAP_SUPPLEMENT_MAX_OUTSIDE_RATIO = 0.25
VISUAL_GAP_SUPPLEMENT_MIN_COVERAGE_M = 1.0


from .buffer_segment_models import (
    BufferExtractionConfig,
    BufferSegmentResult,
    _CandidateContext,
    _GeometryMetrics,
    _CandidateGraph,
    _SeedGroup,
    _PrunedGraph,
    _GeometryCoverageStatus,
    _GEOMETRY_METRICS_CACHE,
    _PATH_REFERENCE_BUFFER_CACHE,
)

from .buffer_segment_results import (
    _nodes_from_edges,
    _retained_status,
    _retained_buffer_overlap_issues,
    _retained_geometry_buffer_coverage_status,
    _visual_consistency_status,
    _is_soft_visual_consistency_issue,
    _unexpected_endpoint_nodes,
    _leaf_nodes,
    _required_nodes_connected,
    _pair_nodes_bidirectionally_reachable,
    _pair_nodes_reachable_in_order,
    _ordered_required_rcsd_nodes,
    _ordered_anchor_pairs,
    _effective_directed_pair_nodes,
    _directed_adjacency_from_edges,
    _directed_reachable,
    _coerce_int,
    _adjacency_from_edges,
    _result,
    _empty_result,
    _edge_geometry,
    _road_ids,
    _feature_road_id,
    _node_ids,
    _unique_ids,
    _canonical_ids,
    _endpoint_in_buffer,
    _first_present,
)

def _select_candidate_roads(
    features: list[dict[str, Any]],
    buffer_geometry: BaseGeometry,
    config: BufferExtractionConfig,
    *,
    node_canonicalizer: NodeCanonicalizer,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    spatial_candidates: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for feature in features:
        props = dict(feature.get("properties") or {})
        geometry = feature.get("geometry")
        if not isinstance(geometry, BaseGeometry) or geometry.is_empty or not geometry.intersects(buffer_geometry):
            continue
        overlap_length = float(geometry.intersection(buffer_geometry).length)
        road_length = float(geometry.length)
        ratio = overlap_length / road_length if road_length > 0 else 0.0
        if ratio >= config.min_road_overlap_ratio or overlap_length >= config.min_road_overlap_length_m or _endpoint_in_buffer(geometry, buffer_geometry):
            spatial_candidates.append(feature)
    non_advance_roads = [
        feature
        for feature in spatial_candidates
        if not is_advance_right_turn_road(dict(feature.get("properties") or {}), formway_bit=config.advance_right_formway_bit)
    ]
    non_advance_endpoint_counts = _non_advance_endpoint_counts(non_advance_roads, node_canonicalizer=node_canonicalizer)
    for feature in spatial_candidates:
        props = dict(feature.get("properties") or {})
        if not is_advance_right_turn_road(props, formway_bit=config.advance_right_formway_bit):
            selected.append(feature)
            continue
        if _has_second_degree_non_advance_link(feature, non_advance_endpoint_counts, node_canonicalizer=node_canonicalizer):
            selected.append(feature)
        else:
            excluded.append(feature)
    return selected, excluded


def _restore_required_corridor_advance_roads(
    *,
    selected_roads: list[dict[str, Any]],
    excluded_roads: list[dict[str, Any]],
    required_nodes: list[str],
    pair_nodes: list[str],
    directed_pair_nodes: list[str],
    require_directed_pair: bool,
    require_bidirectional: bool,
    node_canonicalizer: NodeCanonicalizer,
    reference_geometry: BaseGeometry | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not excluded_roads or len(set(required_nodes)) < 2:
        return selected_roads, excluded_roads
    selected_graph = _build_undirected_graph(selected_roads, node_canonicalizer=node_canonicalizer)
    if _selected_graph_satisfies_required_corridor(
        selected_graph.edges,
        required_nodes,
        pair_nodes=pair_nodes,
        directed_pair_nodes=directed_pair_nodes,
        require_directed_pair=require_directed_pair,
        require_bidirectional=require_bidirectional,
        reference_geometry=reference_geometry,
    ):
        return selected_roads, excluded_roads

    combined_roads = [*selected_roads, *excluded_roads]
    combined_graph = _build_undirected_graph(combined_roads, node_canonicalizer=node_canonicalizer)
    components = _connected_components(combined_graph.adjacency)
    selected_component = _select_component(components, required_nodes)
    if selected_component is None:
        return selected_roads, excluded_roads

    component_nodes = components[selected_component]
    component_edges = [
        edge for edge in combined_graph.edges if edge.source in component_nodes and edge.target in component_nodes
    ]
    if require_directed_pair and len(directed_pair_nodes) == 2:
        corridor_path = _ordered_edge_path_covering_nodes(
            component_edges,
            required_nodes,
            directed=True,
            reference_geometry=reference_geometry,
        )
        corridor_edge_ids = set(corridor_path or [])
        if corridor_path is None:
            corridor_edge_ids = {edge.edge_id for edge in component_edges}
    else:
        ordered_path = _best_undirected_ordered_anchor_path(
            component_edges,
            required_nodes,
            reference_geometry=reference_geometry,
        )
        corridor_edge_ids = set(ordered_path or [])
        if require_bidirectional and len(pair_nodes) == 2:
            source, target = pair_nodes
            for path in (
                _shortest_edge_path(
                    component_edges,
                    source,
                    target,
                    directed=True,
                    reference_geometry=reference_geometry,
                    required_nodes=set(required_nodes),
                ),
                _shortest_edge_path(
                    component_edges,
                    target,
                    source,
                    directed=True,
                    reference_geometry=reference_geometry,
                    required_nodes=set(required_nodes),
                ),
            ):
                if path is not None:
                    corridor_edge_ids.update(path)
    excluded_road_ids = {road_id for road_id in (_feature_road_id(feature) for feature in excluded_roads) if road_id is not None}
    restored_road_ids = {
        edge.road_id for edge in component_edges if edge.edge_id in corridor_edge_ids and edge.road_id in excluded_road_ids
    }
    if not restored_road_ids:
        return selected_roads, excluded_roads

    restored_roads: list[dict[str, Any]] = []
    remaining_excluded: list[dict[str, Any]] = []
    for feature in excluded_roads:
        road_id = _feature_road_id(feature)
        if road_id in restored_road_ids:
            restored_roads.append(feature)
        else:
            remaining_excluded.append(feature)
    return [*selected_roads, *restored_roads], remaining_excluded


def _non_advance_endpoint_counts(features: list[dict[str, Any]], *, node_canonicalizer: NodeCanonicalizer) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for feature in features:
        endpoints = _feature_canonical_endpoints(feature, node_canonicalizer=node_canonicalizer)
        if endpoints is None:
            continue
        source, target = endpoints
        counts[source] += 1
        counts[target] += 1
    return dict(counts)


def _has_second_degree_non_advance_link(
    feature: dict[str, Any],
    non_advance_endpoint_counts: dict[str, int],
    *,
    node_canonicalizer: NodeCanonicalizer,
) -> bool:
    endpoints = _feature_canonical_endpoints(feature, node_canonicalizer=node_canonicalizer)
    if endpoints is None:
        return False
    source, target = endpoints
    if source == target:
        return False
    return non_advance_endpoint_counts.get(source, 0) > 0 and non_advance_endpoint_counts.get(target, 0) > 0


def _selected_graph_satisfies_required_corridor(
    edges: list[Edge],
    required_nodes: list[str],
    *,
    pair_nodes: list[str],
    directed_pair_nodes: list[str],
    require_directed_pair: bool,
    require_bidirectional: bool,
    reference_geometry: BaseGeometry | None,
) -> bool:
    components = _connected_components(_adjacency_from_edges(edges))
    if _select_component(components, required_nodes) is None:
        return False
    ordered_path = _best_undirected_ordered_anchor_path(
        edges,
        required_nodes,
        reference_geometry=reference_geometry,
    )
    if ordered_path is None:
        return False
    if require_bidirectional:
        return _pair_nodes_bidirectionally_reachable(edges, pair_nodes)
    if not require_directed_pair:
        return True
    if len(directed_pair_nodes) != 2:
        return False
    return (
        _ordered_edge_path_covering_nodes(
            edges,
            required_nodes,
            directed=True,
            reference_geometry=reference_geometry,
        )
        is not None
    )


def _feature_canonical_endpoints(feature: dict[str, Any], *, node_canonicalizer: NodeCanonicalizer) -> tuple[str, str] | None:
    props = dict(feature.get("properties") or {})
    try:
        source = node_canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
        target = node_canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
    except (KeyError, ParseError):
        return None
    return source, target


def _select_candidate_nodes(features: list[dict[str, Any]], buffer_geometry: BaseGeometry) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for feature in features:
        geometry = feature.get("geometry")
        if isinstance(geometry, BaseGeometry) and not geometry.is_empty and buffer_geometry.covers(geometry):
            selected.append(feature)
    return selected


def _build_undirected_graph(features: list[dict[str, Any]], *, node_canonicalizer: NodeCanonicalizer) -> _CandidateGraph:
    adjacency: dict[str, set[str]] = defaultdict(set)
    edges: list[Edge] = []
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            road_id = normalize_id(_first_present(props, ["id", "road_id", "roadid"]))
            snode = node_canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
            enode = node_canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
        except (KeyError, ParseError):
            continue
        geometry = feature.get("geometry")
        edge = Edge(f"{road_id}:u", road_id, snode, enode, geometry if isinstance(geometry, BaseGeometry) else None, props)
        edges.append(edge)
        if snode == enode:
            adjacency.setdefault(snode, set())
            continue
        adjacency[snode].add(enode)
        adjacency[enode].add(snode)
    return _CandidateGraph(adjacency=dict(adjacency), edges=edges)


def _connected_components(adjacency: dict[str, set[str]]) -> list[set[str]]:
    components: list[set[str]] = []
    seen: set[str] = set()
    for node in adjacency:
        if node in seen:
            continue
        queue: deque[str] = deque([node])
        component = {node}
        seen.add(node)
        while queue:
            current = queue.popleft()
            for nxt in adjacency.get(current, set()):
                if nxt in seen:
                    continue
                seen.add(nxt)
                component.add(nxt)
                queue.append(nxt)
        components.append(component)
    return components


def _select_component(components: list[set[str]], required_nodes: list[str]) -> int | None:
    required = set(required_nodes)
    for index, component in enumerate(components):
        if required.issubset(component):
            return index
    return None


def _prune_component_seed_based(
    *,
    component_nodes: set[str],
    edges: list[Edge],
    required_nodes: set[str],
    optional_nodes: set[str],
    protected_optional_nodes: set[str],
    semantic_nodes: set[str],
    pair_nodes: list[str],
    directed_pair_nodes: list[str],
    require_directed_pair: bool,
    require_bidirectional: bool,
    reference_geometry: BaseGeometry | None,
) -> _PrunedGraph:
    adjacency = _adjacency_from_edges(edges)
    _ = optional_nodes
    allowed_nodes = (required_nodes | protected_optional_nodes) & component_nodes
    extra_semantic_nodes = (semantic_nodes & component_nodes) - allowed_nodes
    corridor_edge_ids = {
        edge_id
        for path in _minimum_terminal_edge_paths(edges, sorted(required_nodes), reference_geometry=reference_geometry)
        for edge_id in path
    }
    if len(pair_nodes) == 2:
        source, target = pair_nodes
        if require_bidirectional:
            for path in (
                _shortest_edge_path(edges, source, target, directed=True, reference_geometry=reference_geometry, required_nodes=required_nodes),
                _shortest_edge_path(edges, target, source, directed=True, reference_geometry=reference_geometry, required_nodes=required_nodes),
            ):
                if path is not None:
                    corridor_edge_ids.update(path)
        elif require_directed_pair:
            directed_source, directed_target = _effective_directed_pair_nodes(pair_nodes, directed_pair_nodes)
            path = _shortest_directed_path_covering_nodes(
                edges,
                directed_source,
                directed_target,
                sorted(required_nodes),
                reference_geometry=reference_geometry,
            )
            if path is not None:
                corridor_edge_ids.update(path)
    corridor_nodes = _nodes_from_edges(edge for edge in edges if edge.edge_id in corridor_edge_ids)
    inner_nodes: set[str] = set()
    out_nodes: set[str] = set()
    remove_nodes: set[str] = set()
    for group in _seed_groups(extra_semantic_nodes, adjacency, allowed_nodes):
        if group.leaves and group.leaves.issubset(allowed_nodes):
            inner_nodes.update(group.seed_nodes)
        elif len(group.leaves & protected_optional_nodes) >= 2:
            group_corridor_nodes = _seed_group_allowed_terminal_corridor_nodes(
                group,
                edges,
                terminal_nodes=protected_optional_nodes,
                reference_geometry=reference_geometry,
            )
            group_corridor_nodes.update(corridor_nodes & group.scope_nodes)
            inner_nodes.update(group.seed_nodes & group_corridor_nodes)
            out_nodes.update(group.seed_nodes - group_corridor_nodes)
            remove_nodes.update(group.scope_nodes - group_corridor_nodes)
        else:
            inner_nodes.update(group.seed_nodes & corridor_nodes)
            out_nodes.update(group.seed_nodes - corridor_nodes)
            remove_nodes.update(group.scope_nodes - corridor_nodes)

    candidate_nodes = set(component_nodes) - remove_nodes
    candidate_edges = [edge for edge in edges if edge.source in candidate_nodes and edge.target in candidate_nodes]
    protected_nodes = (allowed_nodes | inner_nodes | corridor_nodes) & candidate_nodes
    retained_nodes = _trim_unprotected_leaves(candidate_nodes, candidate_edges, protected_nodes)
    retained_edges = [edge for edge in candidate_edges if edge.source in retained_nodes and edge.target in retained_nodes]
    return _PrunedGraph(
        retained_nodes=retained_nodes,
        retained_edges=retained_edges,
        inner_nodes=sorted(inner_nodes & retained_nodes),
        out_nodes=sorted(out_nodes),
    )


def _seed_group_allowed_terminal_corridor_nodes(
    group: _SeedGroup,
    edges: list[Edge],
    *,
    terminal_nodes: set[str],
    reference_geometry: BaseGeometry | None,
) -> set[str]:
    allowed_leaves = sorted(group.leaves & terminal_nodes)
    if len(allowed_leaves) < 2:
        return set()
    scope_with_boundaries = group.scope_nodes | set(allowed_leaves)
    group_edges = [edge for edge in edges if edge.source in scope_with_boundaries and edge.target in scope_with_boundaries]
    selected_edge_ids = {
        edge_id
        for path in _minimum_terminal_edge_paths(group_edges, allowed_leaves, reference_geometry=reference_geometry)
        for edge_id in path
    }
    return _nodes_from_edges(edge for edge in group_edges if edge.edge_id in selected_edge_ids) - set(allowed_leaves)


def _seed_groups(extra_semantic_nodes: set[str], adjacency: dict[str, set[str]], allowed_nodes: set[str]) -> list[_SeedGroup]:
    groups: list[_SeedGroup] = []
    visited_extra: set[str] = set()
    for seed in sorted(extra_semantic_nodes):
        if seed in visited_extra:
            continue
        queue: deque[str] = deque([seed])
        scope_nodes = {seed}
        seed_nodes = {seed}
        while queue:
            node = queue.popleft()
            for neighbor in adjacency.get(node, set()):
                if neighbor in allowed_nodes or neighbor in scope_nodes:
                    continue
                scope_nodes.add(neighbor)
                queue.append(neighbor)
                if neighbor in extra_semantic_nodes:
                    seed_nodes.add(neighbor)
        visited_extra.update(seed_nodes)
        groups.append(_SeedGroup(seed_nodes=seed_nodes, scope_nodes=scope_nodes, leaves=_seed_group_leaves(scope_nodes, adjacency, allowed_nodes)))
    return groups


def _seed_group_leaves(scope_nodes: set[str], adjacency: dict[str, set[str]], allowed_nodes: set[str]) -> set[str]:
    leaves: set[str] = set()
    for node in scope_nodes:
        neighbors = adjacency.get(node, set())
        if len(neighbors) <= 1:
            leaves.add(node)
        leaves.update(neighbor for neighbor in neighbors if neighbor in allowed_nodes)
    return leaves


def _trim_unprotected_leaves(component_nodes: set[str], edges: list[Edge], protected_nodes: set[str]) -> set[str]:
    retained = set(component_nodes)
    changed = True
    while changed:
        changed = False
        adjacency = _adjacency_from_edges(edge for edge in edges if edge.source in retained and edge.target in retained)
        for node in list(retained):
            if node not in protected_nodes and len(adjacency.get(node, set())) <= 1:
                retained.remove(node)
                changed = True
    return retained


def _include_reachable_optional_terminal_paths(
    edges: list[Edge],
    selected_edges: list[Edge],
    *,
    optional_nodes: set[str],
    reference_geometry: BaseGeometry | None,
) -> list[Edge]:
    if not optional_nodes or not selected_edges:
        return selected_edges
    selected_ids = {edge.edge_id for edge in selected_edges}
    selected_nodes = _nodes_from_edges(selected_edges)
    graph_nodes = _nodes_from_edges(edges)
    for optional_node in sorted(optional_nodes & graph_nodes):
        if optional_node in selected_nodes:
            continue
        best_path: list[str] | None = None
        best_weight = float("inf")
        for target in sorted(selected_nodes):
            path = _shortest_edge_path(
                edges,
                optional_node,
                target,
                directed=False,
                reference_geometry=reference_geometry,
                required_nodes=set(),
            )
            if path is None:
                continue
            weight = _path_weight(edges, path, reference_geometry=reference_geometry, required_nodes=set())
            if weight < best_weight:
                best_weight = weight
                best_path = path
        if best_path is None:
            continue
        selected_ids.update(best_path)
        selected_nodes = _nodes_from_edges(edge for edge in edges if edge.edge_id in selected_ids)
    return [edge for edge in edges if edge.edge_id in selected_ids]


def _minimum_terminal_edge_paths(edges: list[Edge], terminals: list[str], *, reference_geometry: BaseGeometry | None) -> list[list[str]]:
    graph_nodes = _nodes_from_edges(edges)
    unique_terminals: list[str] = []
    seen: set[str] = set()
    for terminal in terminals:
        if terminal in graph_nodes and terminal not in seen:
            seen.add(terminal)
            unique_terminals.append(terminal)
    if len(unique_terminals) < 2:
        return []

    pair_paths: list[tuple[float, str, str, list[str]]] = []
    for index, source in enumerate(unique_terminals):
        for target in unique_terminals[index + 1 :]:
            path = _shortest_edge_path(edges, source, target, directed=False, reference_geometry=reference_geometry, required_nodes=set(terminals))
            if path is None:
                continue
            pair_paths.append((_path_weight(edges, path, reference_geometry=reference_geometry, required_nodes=set(terminals)), source, target, path))

    parent = {terminal: terminal for terminal in unique_terminals}

    def find(node: str) -> str:
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    selected: list[list[str]] = []
    for _distance, source, target, path in sorted(pair_paths):
        source_root = find(source)
        target_root = find(target)
        if source_root == target_root:
            continue
        parent[source_root] = target_root
        selected.append(path)
        if len(selected) == len(unique_terminals) - 1:
            break
    return selected


def _shortest_edge_path(
    edges: list[Edge],
    source: str,
    target: str,
    *,
    directed: bool,
    reference_geometry: BaseGeometry | None,
    required_nodes: set[str],
) -> list[str] | None:
    adjacency = _weighted_adjacency(edges, directed=directed, reference_geometry=reference_geometry, required_nodes=required_nodes)
    queue: list[tuple[float, int, str]] = []
    sequence = 0
    heapq.heappush(queue, (0.0, sequence, source))
    distances: dict[str, float] = {source: 0.0}
    previous: dict[str, tuple[str, str]] = {}
    while queue:
        distance, _sequence, node = heapq.heappop(queue)
        if distance > distances.get(node, float("inf")):
            continue
        if node == target:
            break
        for neighbor, weight, edge_id in adjacency.get(node, []):
            next_distance = distance + weight
            if next_distance >= distances.get(neighbor, float("inf")):
                continue
            distances[neighbor] = next_distance
            previous[neighbor] = (node, edge_id)
            sequence += 1
            heapq.heappush(queue, (next_distance, sequence, neighbor))
    if target not in distances:
        return None

    path: list[str] = []
    node = target
    while node != source:
        prev = previous.get(node)
        if prev is None:
            return None
        node, edge_id = prev
        path.append(edge_id)
    path.reverse()
    return path


def _best_undirected_ordered_anchor_path(
    edges: list[Edge],
    ordered_nodes: list[str],
    *,
    reference_geometry: BaseGeometry | None,
) -> list[str] | None:
    forward = _ordered_edge_path_covering_nodes(
        edges,
        ordered_nodes,
        directed=False,
        reference_geometry=reference_geometry,
    )
    reverse = _ordered_edge_path_covering_nodes(
        edges,
        list(reversed(ordered_nodes)),
        directed=False,
        reference_geometry=reference_geometry,
    )
    candidates = [path for path in (forward, reverse) if path is not None]
    if not candidates:
        return None
    required = set(ordered_nodes)
    return min(candidates, key=lambda path: _path_weight(edges, path, reference_geometry=reference_geometry, required_nodes=required))


def _ordered_edge_path_covering_nodes(
    edges: list[Edge],
    ordered_nodes: list[str],
    *,
    directed: bool,
    reference_geometry: BaseGeometry | None,
) -> list[str] | None:
    anchors = _unique_ids(ordered_nodes)
    graph_nodes = _nodes_from_edges(edges)
    if any(anchor not in graph_nodes for anchor in anchors):
        return None
    if len(anchors) < 2:
        return []
    required = set(anchors)
    result: list[str] = []
    for source, target in zip(anchors, anchors[1:]):
        path = _shortest_anchor_edge_path(
            edges,
            source,
            target,
            directed=directed,
            reference_geometry=reference_geometry,
            required_nodes=required,
            blocked_intermediate_nodes=required - {source, target},
        )
        if path is None:
            return None
        result.extend(path)
    return result


def _shortest_anchor_edge_path(
    edges: list[Edge],
    source: str,
    target: str,
    *,
    directed: bool,
    reference_geometry: BaseGeometry | None,
    required_nodes: set[str],
    blocked_intermediate_nodes: set[str],
) -> list[str] | None:
    adjacency = _weighted_adjacency(edges, directed=directed, reference_geometry=reference_geometry, required_nodes=required_nodes)
    queue: list[tuple[float, int, str]] = []
    sequence = 0
    heapq.heappush(queue, (0.0, sequence, source))
    distances: dict[str, float] = {source: 0.0}
    previous: dict[str, tuple[str, str]] = {}
    while queue:
        distance, _sequence, node = heapq.heappop(queue)
        if distance > distances.get(node, float("inf")):
            continue
        if node == target:
            break
        for neighbor, weight, edge_id in adjacency.get(node, []):
            if neighbor in blocked_intermediate_nodes:
                continue
            next_distance = distance + weight
            if next_distance >= distances.get(neighbor, float("inf")):
                continue
            distances[neighbor] = next_distance
            previous[neighbor] = (node, edge_id)
            sequence += 1
            heapq.heappush(queue, (next_distance, sequence, neighbor))
    if target not in distances:
        return None

    path: list[str] = []
    node = target
    while node != source:
        prev = previous.get(node)
        if prev is None:
            return None
        node, edge_id = prev
        path.append(edge_id)
    path.reverse()
    return path


def _shortest_directed_path_covering_nodes(
    edges: list[Edge],
    source: str,
    target: str,
    required_nodes: list[str],
    *,
    reference_geometry: BaseGeometry | None,
) -> list[str] | None:
    graph_nodes = _nodes_from_edges(edges)
    terminals: list[str] = []
    seen_terminals: set[str] = set()
    for node in required_nodes:
        if node not in graph_nodes or node in seen_terminals:
            continue
        seen_terminals.add(node)
        terminals.append(node)
    if source not in graph_nodes or target not in graph_nodes or len(terminals) < len(set(required_nodes)):
        return None

    terminal_index = {node: index for index, node in enumerate(terminals)}
    all_mask = (1 << len(terminals)) - 1
    start_mask = _node_mask(source, terminal_index)
    adjacency = _weighted_adjacency(edges, directed=True, reference_geometry=reference_geometry, required_nodes=set(required_nodes))
    queue: list[tuple[float, int, str, int]] = []
    sequence = 0
    heapq.heappush(queue, (0.0, sequence, source, start_mask))
    distances: dict[tuple[str, int], float] = {(source, start_mask): 0.0}
    previous: dict[tuple[str, int], tuple[str, int, str]] = {}
    goal: tuple[str, int] | None = None

    while queue:
        distance, _sequence, node, mask = heapq.heappop(queue)
        state = (node, mask)
        if distance > distances.get(state, float("inf")):
            continue
        if node == target and mask == all_mask:
            goal = state
            break
        for neighbor, weight, edge_id in adjacency.get(node, []):
            next_mask = mask | _node_mask(neighbor, terminal_index)
            next_state = (neighbor, next_mask)
            next_distance = distance + weight
            if next_distance >= distances.get(next_state, float("inf")):
                continue
            distances[next_state] = next_distance
            previous[next_state] = (node, mask, edge_id)
            sequence += 1
            heapq.heappush(queue, (next_distance, sequence, neighbor, next_mask))

    if goal is None:
        return None

    path: list[str] = []
    state = goal
    while state != (source, start_mask):
        prev = previous.get(state)
        if prev is None:
            return None
        prev_node, prev_mask, edge_id = prev
        path.append(edge_id)
        state = (prev_node, prev_mask)
    path.reverse()
    return path


def _node_mask(node: str, terminal_index: dict[str, int]) -> int:
    index = terminal_index.get(node)
    if index is None:
        return 0
    return 1 << index


def _weighted_adjacency(
    edges: list[Edge],
    *,
    directed: bool,
    reference_geometry: BaseGeometry | None,
    required_nodes: set[str],
) -> dict[str, list[tuple[str, float, str]]]:
    adjacency: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    reference_geometry_empty = reference_geometry is None or reference_geometry.is_empty
    reference_buffer_geometry = _path_reference_buffer(reference_geometry)
    reference_buffer_bounds = reference_buffer_geometry.bounds if reference_buffer_geometry is not None else None
    for edge in edges:
        weight = _edge_weight(
            edge,
            reference_geometry=reference_geometry,
            reference_geometry_empty=reference_geometry_empty,
            reference_buffer_geometry=reference_buffer_geometry,
            reference_buffer_bounds=reference_buffer_bounds,
            required_nodes=required_nodes,
        )
        if not directed:
            adjacency[edge.source].append((edge.target, weight, edge.edge_id))
            adjacency[edge.target].append((edge.source, weight, edge.edge_id))
            continue
        direction = _coerce_int(edge.properties.get("direction")) if edge.properties else None
        if direction in {0, 1, 2}:
            adjacency[edge.source].append((edge.target, weight, edge.edge_id))
        if direction in {0, 1, 3}:
            adjacency[edge.target].append((edge.source, weight, edge.edge_id))
    return dict(adjacency)


def _path_weight(edges: list[Edge], path: list[str], *, reference_geometry: BaseGeometry | None, required_nodes: set[str]) -> float:
    reference_geometry_empty = reference_geometry is None or reference_geometry.is_empty
    reference_buffer_geometry = _path_reference_buffer(reference_geometry)
    reference_buffer_bounds = reference_buffer_geometry.bounds if reference_buffer_geometry is not None else None
    weights = {
        edge.edge_id: _edge_weight(
            edge,
            reference_geometry=reference_geometry,
            reference_geometry_empty=reference_geometry_empty,
            reference_buffer_geometry=reference_buffer_geometry,
            reference_buffer_bounds=reference_buffer_bounds,
            required_nodes=required_nodes,
        )
        for edge in edges
    }
    return sum(weights.get(edge_id, 1.0) for edge_id in path)


def _edge_weight(
    edge: Edge,
    *,
    reference_geometry: BaseGeometry | None,
    reference_geometry_empty: bool,
    reference_buffer_geometry: BaseGeometry | None,
    reference_buffer_bounds: tuple[float, float, float, float] | None,
    required_nodes: set[str],
) -> float:
    metrics = _edge_geometry_metrics(edge)
    length = 1.0
    if metrics is not None and not metrics.is_empty:
        length = max(metrics.length, 1.0)
    if reference_geometry_empty:
        return length
    shortcut_penalty = _required_shortcut_penalty(edge, length, reference_geometry, required_nodes)
    off_reference_penalty = _off_reference_penalty(edge, length, reference_buffer_geometry, reference_buffer_bounds, metrics)
    return length + shortcut_penalty + off_reference_penalty


def _path_reference_buffer(reference_geometry: BaseGeometry | None) -> BaseGeometry | None:
    if reference_geometry is None or reference_geometry.is_empty:
        return None
    key = id(reference_geometry)
    cached = _PATH_REFERENCE_BUFFER_CACHE.get(key)
    if cached is not None and cached[0] is reference_geometry:
        return cached[1]
    buffered = reference_geometry.buffer(PATH_REFERENCE_BUFFER_M)
    if len(_PATH_REFERENCE_BUFFER_CACHE) >= 8192:
        _PATH_REFERENCE_BUFFER_CACHE.clear()
    _PATH_REFERENCE_BUFFER_CACHE[key] = (reference_geometry, buffered)
    return buffered


def _off_reference_penalty(
    edge: Edge,
    length: float,
    reference_buffer_geometry: BaseGeometry | None,
    reference_buffer_bounds: tuple[float, float, float, float] | None,
    metrics: _GeometryMetrics | None,
) -> float:
    if reference_buffer_geometry is None or edge.geometry is None or metrics is None or metrics.is_empty:
        return 0.0
    if reference_buffer_bounds is not None and metrics.bounds is not None and not _bounds_intersect(metrics.bounds, reference_buffer_bounds):
        return length * PATH_OFF_REFERENCE_PENALTY_MULTIPLIER
    inside_length = float(edge.geometry.intersection(reference_buffer_geometry).length)
    off_reference_length = max(0.0, length - inside_length)
    return off_reference_length * PATH_OFF_REFERENCE_PENALTY_MULTIPLIER


def _edge_geometry_metrics(edge: Edge) -> _GeometryMetrics | None:
    geometry = edge.geometry
    if geometry is None:
        return None
    key = id(geometry)
    cached = _GEOMETRY_METRICS_CACHE.get(key)
    if cached is not None and cached[0] is geometry:
        return cached[1]
    is_empty = bool(geometry.is_empty)
    metrics = _GeometryMetrics(
        is_empty=is_empty,
        length=0.0 if is_empty else float(geometry.length),
        bounds=None if is_empty else geometry.bounds,
    )
    _GEOMETRY_METRICS_CACHE[key] = (geometry, metrics)
    return metrics


def _bounds_intersect(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return not (left[2] < right[0] or right[2] < left[0] or left[3] < right[1] or right[3] < left[1])


def _required_shortcut_penalty(edge: Edge, length: float, reference_geometry: BaseGeometry, required_nodes: set[str]) -> float:
    if edge.source not in required_nodes or edge.target not in required_nodes:
        return 0.0
    if not required_nodes or length >= max(8.0, float(reference_geometry.length) * 0.08):
        return 0.0
    return max(10000.0, float(reference_geometry.length) * 100.0)
