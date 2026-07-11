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
    _mismatch_exceeds_threshold,
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

from .buffer_segment_graph import (
    _select_candidate_roads,
    _restore_required_corridor_advance_roads,
    _non_advance_endpoint_counts,
    _has_second_degree_non_advance_link,
    _selected_graph_satisfies_required_corridor,
    _feature_canonical_endpoints,
    _select_candidate_nodes,
    _build_undirected_graph,
    _connected_components,
    _select_component,
    _prune_component_seed_based,
    _seed_group_allowed_terminal_corridor_nodes,
    _seed_groups,
    _seed_group_leaves,
    _trim_unprotected_leaves,
    _include_reachable_optional_terminal_paths,
    _minimum_terminal_edge_paths,
    _shortest_edge_path,
    _best_undirected_ordered_anchor_path,
    _ordered_edge_path_covering_nodes,
    _shortest_anchor_edge_path,
    _shortest_directed_path_covering_nodes,
    _node_mask,
    _weighted_adjacency,
    _path_weight,
    _edge_weight,
    _path_reference_buffer,
    _off_reference_penalty,
    _edge_geometry_metrics,
    _bounds_intersect,
    _required_shortcut_penalty,
)

def _build_corridor_subgraph(
    edges: list[Edge],
    required_nodes: list[str],
    pair_nodes: list[str],
    directed_pair_nodes: list[str],
    *,
    reference_geometry: BaseGeometry | None,
    reference_buffer_geometry: BaseGeometry | None = None,
    reference_visual_buffer_geometry: BaseGeometry | None = None,
    max_mismatch_ratio: float = 0.1,
    min_mismatch_length_m: float = 20.0,
    max_visual_mismatch_ratio: float = 0.1,
    min_visual_mismatch_length_m: float = 20.0,
    require_directed_pair: bool,
    require_bidirectional: bool,
) -> list[Edge]:
    if require_directed_pair and len(pair_nodes) == 2:
        path = _ordered_edge_path_covering_nodes(
            edges,
            required_nodes,
            directed=True,
            reference_geometry=reference_geometry,
        )
        if path is None:
            return []
        return [edge for edge in edges if edge.edge_id in set(path)]

    selected_edge_ids: set[str] = set()
    ordered_path = _best_undirected_ordered_anchor_path(
        edges,
        required_nodes,
        reference_geometry=reference_geometry,
    )
    if ordered_path is not None:
        selected_edge_ids.update(ordered_path)

    if len(pair_nodes) == 2:
        source, target = pair_nodes
        if require_bidirectional:
            for path in (
                _shortest_edge_path(edges, source, target, directed=True, reference_geometry=reference_geometry, required_nodes=set(required_nodes)),
                _shortest_edge_path(edges, target, source, directed=True, reference_geometry=reference_geometry, required_nodes=set(required_nodes)),
            ):
                if path is not None:
                    selected_edge_ids.update(path)

    selected_edges = [edge for edge in edges if edge.edge_id in selected_edge_ids]
    if require_bidirectional:
        selected_edges = _include_internal_corridor_edges(
            edges,
            selected_edges,
            required_nodes=set(required_nodes),
            ordered_anchor_pairs=_ordered_anchor_pairs(required_nodes) if len(required_nodes) > 2 else set(),
            reference_buffer_geometry=reference_buffer_geometry,
            reference_visual_buffer_geometry=reference_visual_buffer_geometry,
            max_mismatch_ratio=max_mismatch_ratio,
            min_mismatch_length_m=min_mismatch_length_m,
            max_visual_mismatch_ratio=max_visual_mismatch_ratio,
            min_visual_mismatch_length_m=min_visual_mismatch_length_m,
        )
    return selected_edges


def _include_internal_corridor_edges(
    edges: list[Edge],
    selected_edges: list[Edge],
    *,
    required_nodes: set[str],
    ordered_anchor_pairs: set[frozenset[str]] | None = None,
    allowed_touch_nodes: set[str] | None = None,
    reference_buffer_geometry: BaseGeometry | None,
    reference_visual_buffer_geometry: BaseGeometry | None = None,
    max_mismatch_ratio: float,
    min_mismatch_length_m: float,
    max_visual_mismatch_ratio: float = 0.1,
    min_visual_mismatch_length_m: float = 20.0,
    allow_selected_required_pair_parallel_edges: bool = False,
    allow_retained_node_self_loop_edges: bool = False,
) -> list[Edge]:
    retained_nodes = _nodes_from_edges(selected_edges)
    selected_edge_ids = {edge.edge_id for edge in selected_edges}
    result = list(selected_edges)
    for edge in edges:
        if edge.edge_id in selected_edge_ids:
            continue
        if edge.source not in retained_nodes or edge.target not in retained_nodes:
            continue
        retained_self_loop = allow_retained_node_self_loop_edges and edge.source == edge.target
        if (
            allowed_touch_nodes is not None
            and edge.source not in allowed_touch_nodes
            and edge.target not in allowed_touch_nodes
            and not retained_self_loop
        ):
            continue
        if (
            edge.source in required_nodes
            and edge.target in required_nodes
            and frozenset((edge.source, edge.target)) not in (ordered_anchor_pairs or set())
            and not (
                allow_selected_required_pair_parallel_edges
                and _has_direction_compatible_selected_parallel_edge(edge, selected_edges)
            )
            and not retained_self_loop
        ):
            continue
        within_buffer_scope = _edge_within_buffer_scope(
            edge,
            reference_buffer_geometry=reference_buffer_geometry,
            max_mismatch_ratio=max_mismatch_ratio,
            min_mismatch_length_m=min_mismatch_length_m,
        )
        if not within_buffer_scope:
            continue
        if reference_visual_buffer_geometry is not None:
            within_visual_scope = (
                _edge_within_visual_gap_scope(
                    edge,
                    reference_buffer_geometry=reference_visual_buffer_geometry,
                    max_outside_length_m=min_visual_mismatch_length_m,
                )
                if retained_self_loop
                else _edge_within_buffer_scope(
                    edge,
                    reference_buffer_geometry=reference_visual_buffer_geometry,
                    max_mismatch_ratio=max_visual_mismatch_ratio,
                    min_mismatch_length_m=min_visual_mismatch_length_m,
                )
            )
            if not within_visual_scope:
                continue
        result.append(edge)
        selected_edge_ids.add(edge.edge_id)
    return result


def _has_direction_compatible_selected_parallel_edge(edge: Edge, selected_edges: list[Edge]) -> bool:
    edge_pair = frozenset((edge.source, edge.target))
    edge_travel = _directed_travel_pairs(edge)
    if not edge_travel:
        return False
    return any(
        frozenset((selected.source, selected.target)) == edge_pair
        and bool(edge_travel & _directed_travel_pairs(selected))
        for selected in selected_edges
    )
def _directed_travel_pairs(edge: Edge) -> set[tuple[str, str]]:
    direction = _coerce_int(edge.properties.get("direction")) if edge.properties else None
    pairs: set[tuple[str, str]] = set()
    if direction in {0, 1, 2}:
        pairs.add((edge.source, edge.target))
    if direction in {0, 1, 3}:
        pairs.add((edge.target, edge.source))
    return pairs


def _include_connected_corridor_supplement_edges(
    edges: list[Edge],
    selected_edges: list[Edge],
    *,
    required_nodes: set[str],
    optional_nodes: set[str],
    blocked_nodes: set[str],
    reference_geometry: BaseGeometry | None,
    require_optional_terminal: bool = False,
    allow_single_optional_boundary: bool = True,
) -> tuple[list[Edge], set[str]]:
    if reference_geometry is None or reference_geometry.is_empty or not selected_edges:
        return selected_edges, set()
    selected_edge_ids = {edge.edge_id for edge in selected_edges}
    retained_nodes = _nodes_from_edges(selected_edges)
    supplement_buffer = reference_geometry.buffer(CONNECTED_CORRIDOR_SUPPLEMENT_BUFFER_M)
    supplement_edges = [
        edge
        for edge in edges
        if edge.edge_id not in selected_edge_ids
        and not (edge.source in required_nodes and edge.target in required_nodes)
        and _edge_within_buffer_scope(
            edge,
            reference_buffer_geometry=supplement_buffer,
            max_mismatch_ratio=CONNECTED_CORRIDOR_SUPPLEMENT_MAX_OUTSIDE_RATIO,
            min_mismatch_length_m=CONNECTED_CORRIDOR_SUPPLEMENT_MAX_OUTSIDE_LENGTH_M,
        )
    ]
    if not supplement_edges:
        return selected_edges, set()

    supplement_ids: set[str] = set()
    allowed_endpoint_nodes: set[str] = set()
    supplement_components = _connected_components(_adjacency_from_edges(supplement_edges))
    for component in supplement_components:
        if component & blocked_nodes:
            continue
        if require_optional_terminal and not (component & optional_nodes):
            continue
        boundary_nodes = sorted(component & retained_nodes)
        if len(boundary_nodes) >= 2:
            component_edges = [
                edge for edge in supplement_edges if edge.source in component and edge.target in component
            ]
            for path in _minimum_terminal_edge_paths(component_edges, boundary_nodes, reference_geometry=reference_geometry):
                supplement_ids.update(path)
            continue
        if allow_single_optional_boundary and len(boundary_nodes) == 1 and component & optional_nodes:
            component_edges = [edge for edge in supplement_edges if edge.source in component and edge.target in component]
            if set(boundary_nodes) & optional_nodes:
                supplement_ids.update(edge.edge_id for edge in component_edges)
            else:
                terminals = [*boundary_nodes, *sorted(component & optional_nodes)]
                for path in _minimum_terminal_edge_paths(component_edges, terminals, reference_geometry=reference_geometry):
                    supplement_ids.update(path)
            allowed_endpoint_nodes.update(_leaf_nodes(component_edges) - retained_nodes - required_nodes - optional_nodes)
    if not supplement_ids:
        return selected_edges, set()

    result = list(selected_edges)
    for edge in edges:
        if edge.edge_id in supplement_ids and edge.edge_id not in selected_edge_ids:
            result.append(edge)
            selected_edge_ids.add(edge.edge_id)
    return result, allowed_endpoint_nodes


def _include_required_leaf_attach_edges(
    edges: list[Edge],
    selected_edges: list[Edge],
    *,
    required_nodes: set[str],
    pair_nodes: set[str],
    blocked_nodes: set[str],
    reference_buffer_geometry: BaseGeometry | None,
    max_mismatch_ratio: float,
    min_mismatch_length_m: float,
) -> tuple[list[Edge], set[str]]:
    if reference_buffer_geometry is None or reference_buffer_geometry.is_empty or not selected_edges:
        return selected_edges, set()
    retained_nodes = _nodes_from_edges(selected_edges)
    missing_required = required_nodes - retained_nodes - pair_nodes
    if not missing_required:
        return selected_edges, set()
    full_adjacency = _adjacency_from_edges(edges)
    leaf_required = {node_id for node_id in missing_required if len(full_adjacency.get(node_id, set())) <= 1}
    if not leaf_required:
        return selected_edges, set()

    selected_edge_ids = {edge.edge_id for edge in selected_edges}
    result = list(selected_edges)
    allowed_endpoint_nodes: set[str] = set()
    for edge in edges:
        if edge.edge_id in selected_edge_ids:
            continue
        leaf_nodes = {edge.source, edge.target} & leaf_required
        if not leaf_nodes:
            continue
        other_nodes = {edge.source, edge.target} - leaf_nodes
        if len(leaf_nodes) != 1 or len(other_nodes) != 1:
            continue
        other_node = next(iter(other_nodes))
        if other_node not in retained_nodes or other_node in blocked_nodes:
            continue
        if not _edge_within_buffer_scope(
            edge,
            reference_buffer_geometry=reference_buffer_geometry,
            max_mismatch_ratio=max_mismatch_ratio,
            min_mismatch_length_m=min_mismatch_length_m,
        ):
            continue
        result.append(edge)
        selected_edge_ids.add(edge.edge_id)
        retained_nodes.update((edge.source, edge.target))
        allowed_endpoint_nodes.update(leaf_nodes)
    return result, allowed_endpoint_nodes


def _include_visual_gap_candidate_components(
    edges: list[Edge],
    selected_edges: list[Edge],
    *,
    blocked_nodes: set[str],
    reference_geometry: BaseGeometry | None,
    reference_buffer_geometry: BaseGeometry | None,
    max_mismatch_ratio: float,
    min_mismatch_length_m: float,
) -> tuple[list[Edge], set[str]]:
    if (
        reference_geometry is None
        or reference_geometry.is_empty
        or reference_buffer_geometry is None
        or reference_buffer_geometry.is_empty
        or not selected_edges
    ):
        return selected_edges, set()
    retained_geometry = _edge_geometry(selected_edges)
    if retained_geometry.is_empty:
        return selected_edges, set()
    uncovered_geometry = reference_geometry.difference(retained_geometry.buffer(PATH_REFERENCE_BUFFER_M))
    uncovered_length = float(uncovered_geometry.length) if not uncovered_geometry.is_empty else 0.0
    reference_length = float(reference_geometry.length)
    uncovered_ratio = uncovered_length / reference_length if reference_length > 0 else 0.0
    if not _mismatch_exceeds_threshold(
        uncovered_length,
        uncovered_ratio,
        max_mismatch_ratio=max_mismatch_ratio,
        min_mismatch_length_m=min_mismatch_length_m,
    ):
        return selected_edges, set()

    selected_edge_ids = {edge.edge_id for edge in selected_edges}
    supplement_edges = [
        edge
        for edge in edges
        if edge.edge_id not in selected_edge_ids
        and edge.source not in blocked_nodes
        and edge.target not in blocked_nodes
        and _edge_within_visual_gap_scope(
            edge,
            reference_buffer_geometry=reference_buffer_geometry,
            max_outside_length_m=min_mismatch_length_m,
        )
    ]
    if not supplement_edges:
        return selected_edges, set()

    retained_nodes = _nodes_from_edges(selected_edges)
    supplement_ids: set[str] = set()
    allowed_endpoint_nodes: set[str] = set()
    for component in _connected_components(_adjacency_from_edges(supplement_edges)):
        if component & blocked_nodes or _component_touches_blocked_node(component, edges, blocked_nodes):
            continue
        component_edges = [edge for edge in supplement_edges if edge.source in component and edge.target in component]
        component_geometry = _edge_geometry(component_edges)
        if component_geometry.is_empty:
            continue
        covered_gap_length = float(component_geometry.buffer(PATH_REFERENCE_BUFFER_M).intersection(uncovered_geometry).length)
        if covered_gap_length < VISUAL_GAP_SUPPLEMENT_MIN_COVERAGE_M:
            continue
        if not component & retained_nodes and covered_gap_length < min_mismatch_length_m:
            continue
        supplement_ids.update(edge.edge_id for edge in component_edges)
        allowed_endpoint_nodes.update(_leaf_nodes(component_edges) - retained_nodes)
    if not supplement_ids:
        return selected_edges, set()

    result = list(selected_edges)
    for edge in edges:
        if edge.edge_id in supplement_ids and edge.edge_id not in selected_edge_ids:
            result.append(edge)
            selected_edge_ids.add(edge.edge_id)
    return result, allowed_endpoint_nodes


def _include_parallel_visual_corridor_edges(
    edges: list[Edge],
    selected_edges: list[Edge],
    *,
    required_nodes: set[str],
    directed_pair_nodes: list[str],
    require_directed_pair: bool,
    blocked_nodes: set[str],
    reference_geometry: BaseGeometry | None,
    reference_buffer_geometry: BaseGeometry | None,
    visual_buffer_distance_m: float | None,
    max_mismatch_ratio: float,
    min_mismatch_length_m: float,
) -> tuple[list[Edge], set[str]]:
    if (
        reference_geometry is None
        or reference_geometry.is_empty
        or reference_buffer_geometry is None
        or reference_buffer_geometry.is_empty
        or not selected_edges
        or visual_buffer_distance_m is None
    ):
        return selected_edges, set()
    retained_has_visual_gap = _retained_visual_gap_exceeds_threshold(
        selected_edges,
        reference_geometry=reference_geometry,
        visual_buffer_distance_m=visual_buffer_distance_m,
        max_mismatch_ratio=max_mismatch_ratio,
        min_mismatch_length_m=min_mismatch_length_m,
    )
    if not retained_has_visual_gap and not require_directed_pair:
        return selected_edges, set()
    selected_edge_ids = {edge.edge_id for edge in selected_edges}
    retained_nodes = _nodes_from_edges(selected_edges)
    supplement_edges = [
        edge
        for edge in edges
        if edge.edge_id not in selected_edge_ids
        and edge.source not in blocked_nodes
        and edge.target not in blocked_nodes
        and _edge_within_visual_gap_scope(
            edge,
            reference_buffer_geometry=reference_buffer_geometry,
            max_outside_length_m=min_mismatch_length_m,
        )
    ]
    if not supplement_edges:
        return selected_edges, set()

    supplement_ids: set[str] = set()
    allowed_endpoint_nodes: set[str] = set()
    for component in _connected_components(_adjacency_from_edges(supplement_edges)):
        if component & blocked_nodes or _component_touches_blocked_node(component, edges, blocked_nodes):
            continue
        boundary_nodes = sorted(component & retained_nodes)
        component_edges = [edge for edge in supplement_edges if edge.source in component and edge.target in component]
        if not component_edges:
            continue
        if require_directed_pair:
            path = _directed_parallel_corridor_path(
                component_edges,
                directed_pair_nodes=directed_pair_nodes,
                reference_geometry=reference_geometry,
            )
            if path is None:
                continue
            path_ids = set(path)
            path_edges = [edge for edge in component_edges if edge.edge_id in path_ids]
            if not retained_has_visual_gap and (
                len(path_edges) <= 1
                or not _path_sufficiently_covers_reference(path_edges, reference_geometry=reference_geometry)
            ):
                continue
            supplement_ids.update(path)
            path_nodes = _nodes_from_edges(path_edges)
            for edge in component_edges:
                if edge.edge_id in supplement_ids:
                    continue
                if _directed_edge_connects_boundary_to_path(edge, retained_nodes=retained_nodes, path_nodes=path_nodes):
                    supplement_ids.add(edge.edge_id)
            continue
        if len(boundary_nodes) < 2:
            continue
        if not (component & required_nodes):
            component_geometry = _edge_geometry(component_edges)
            if component_geometry.is_empty:
                continue
            covered_reference_length = float(component_geometry.buffer(PATH_REFERENCE_BUFFER_M).intersection(reference_geometry).length)
            if covered_reference_length < VISUAL_GAP_SUPPLEMENT_MIN_COVERAGE_M:
                continue
        for path in _minimum_terminal_edge_paths(component_edges, boundary_nodes, reference_geometry=reference_geometry):
            supplement_ids.update(path)
        allowed_endpoint_nodes.update(_leaf_nodes(component_edges) - retained_nodes - required_nodes)
    if not supplement_ids:
        return selected_edges, set()

    result = list(selected_edges)
    for edge in edges:
        if edge.edge_id in supplement_ids and edge.edge_id not in selected_edge_ids:
            result.append(edge)
            selected_edge_ids.add(edge.edge_id)
    return result, allowed_endpoint_nodes


def _retained_visual_gap_exceeds_threshold(
    selected_edges: list[Edge],
    *,
    reference_geometry: BaseGeometry,
    visual_buffer_distance_m: float,
    max_mismatch_ratio: float,
    min_mismatch_length_m: float,
) -> bool:
    retained_geometry = _edge_geometry(selected_edges)
    if retained_geometry.is_empty:
        return False
    reference_length = float(reference_geometry.length)
    if reference_length <= 0:
        return False
    uncovered_length = float(reference_geometry.difference(retained_geometry.buffer(visual_buffer_distance_m)).length)
    uncovered_ratio = uncovered_length / reference_length
    return _mismatch_exceeds_threshold(
        uncovered_length,
        uncovered_ratio,
        max_mismatch_ratio=max_mismatch_ratio,
        min_mismatch_length_m=min_mismatch_length_m,
    )

def _directed_parallel_corridor_path(
    edges: list[Edge],
    *,
    directed_pair_nodes: list[str],
    reference_geometry: BaseGeometry | None,
) -> list[str] | None:
    if len(directed_pair_nodes) != 2:
        return None
    source, target = directed_pair_nodes
    return _shortest_edge_path(
        edges,
        source,
        target,
        directed=True,
        reference_geometry=reference_geometry,
        required_nodes={source, target},
    )


def _path_sufficiently_covers_reference(edges: list[Edge], *, reference_geometry: BaseGeometry | None) -> bool:
    if reference_geometry is None or reference_geometry.is_empty:
        return False
    reference_length = float(reference_geometry.length)
    if reference_length <= 0:
        return False
    path_geometry = _edge_geometry(edges)
    if path_geometry.is_empty:
        return False
    covered_length = float(path_geometry.buffer(PATH_REFERENCE_BUFFER_M).intersection(reference_geometry).length)
    return covered_length / reference_length >= 0.9


def _directed_edge_connects_boundary_to_path(edge: Edge, *, retained_nodes: set[str], path_nodes: set[str]) -> bool:
    travel_pairs = _directed_travel_pairs(edge)
    if edge.source in retained_nodes and edge.target in path_nodes and (edge.source, edge.target) in travel_pairs:
        return True
    if edge.target in retained_nodes and edge.source in path_nodes and (edge.target, edge.source) in travel_pairs:
        return True
    return False


def _component_touches_blocked_node(component: set[str], edges: list[Edge], blocked_nodes: set[str]) -> bool:
    if not blocked_nodes:
        return False
    for edge in edges:
        source_blocked = edge.source in blocked_nodes
        target_blocked = edge.target in blocked_nodes
        if source_blocked and edge.target in component:
            return True
        if target_blocked and edge.source in component:
            return True
    return False


def _edge_within_visual_gap_scope(
    edge: Edge,
    *,
    reference_buffer_geometry: BaseGeometry | None,
    max_outside_length_m: float,
) -> bool:
    geometry = edge.geometry
    if reference_buffer_geometry is None or reference_buffer_geometry.is_empty or geometry is None or geometry.is_empty:
        return True
    length = float(geometry.length)
    if length <= 0:
        return True
    outside_length = float(geometry.difference(reference_buffer_geometry).length)
    outside_ratio = outside_length / length
    return (
        outside_length <= max_outside_length_m
        and outside_ratio <= VISUAL_GAP_SUPPLEMENT_MAX_OUTSIDE_RATIO
    )


def _visual_consistency_edges(edges: list[Edge]) -> list[Edge]:
    non_self_loop_edges = [edge for edge in edges if edge.source != edge.target]
    return non_self_loop_edges or edges


def _include_directed_semantic_junction_bridge_edges(
    edges: list[Edge],
    selected_edges: list[Edge],
    *,
    required_nodes: set[str],
    optional_nodes: set[str],
    pair_nodes: set[str],
    blocked_nodes: set[str],
    reference_geometry: BaseGeometry | None,
) -> list[Edge]:
    if reference_geometry is None or reference_geometry.is_empty or not selected_edges or not optional_nodes:
        return selected_edges
    selected_edge_ids = {edge.edge_id for edge in selected_edges}
    retained_nodes = _nodes_from_edges(selected_edges)
    supplement_buffer = reference_geometry.buffer(CONNECTED_CORRIDOR_SUPPLEMENT_BUFFER_M)
    supplement_edges = [
        edge
        for edge in edges
        if edge.edge_id not in selected_edge_ids
        and not (edge.source in required_nodes and edge.target in required_nodes)
        and _edge_within_buffer_scope(
            edge,
            reference_buffer_geometry=supplement_buffer,
            max_mismatch_ratio=CONNECTED_CORRIDOR_SUPPLEMENT_MAX_OUTSIDE_RATIO,
            min_mismatch_length_m=CONNECTED_CORRIDOR_SUPPLEMENT_MAX_OUTSIDE_LENGTH_M,
        )
    ]
    supplement_edges = [
        edge for edge in supplement_edges if edge.source not in blocked_nodes and edge.target not in blocked_nodes
    ]
    supplement_ids: set[str] = set()
    for component in _connected_components(_adjacency_from_edges(supplement_edges)):
        boundary_nodes = sorted(component & retained_nodes)
        boundary_node_set = set(boundary_nodes)
        if (
            len(boundary_nodes) < 2
            or not (boundary_node_set & optional_nodes)
            or not (boundary_node_set & pair_nodes)
        ):
            continue
        component_edges = [edge for edge in supplement_edges if edge.source in component and edge.target in component]
        for path in _minimum_terminal_edge_paths(component_edges, boundary_nodes, reference_geometry=reference_geometry):
            supplement_ids.update(path)
    if not supplement_ids:
        return selected_edges
    result = list(selected_edges)
    for edge in edges:
        if edge.edge_id in supplement_ids and edge.edge_id not in selected_edge_ids:
            result.append(edge)
            selected_edge_ids.add(edge.edge_id)
    return result


def _edge_within_buffer_scope(
    edge: Edge,
    *,
    reference_buffer_geometry: BaseGeometry | None,
    max_mismatch_ratio: float,
    min_mismatch_length_m: float,
) -> bool:
    geometry = edge.geometry
    if reference_buffer_geometry is None or reference_buffer_geometry.is_empty or geometry is None or geometry.is_empty:
        return True
    length = float(geometry.length)
    if length <= 0:
        return True
    outside_length = float(geometry.difference(reference_buffer_geometry).length)
    outside_ratio = outside_length / length
    return not _mismatch_exceeds_threshold(
        outside_length,
        outside_ratio,
        max_mismatch_ratio=max_mismatch_ratio,
        min_mismatch_length_m=min_mismatch_length_m,
    )
