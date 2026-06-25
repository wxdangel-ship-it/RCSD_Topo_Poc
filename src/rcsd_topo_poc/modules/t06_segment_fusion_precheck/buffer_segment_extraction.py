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


@dataclass(frozen=True)
class BufferExtractionConfig:
    buffer_distance_m: float = 50.0
    min_road_overlap_ratio: float = 0.2
    min_road_overlap_length_m: float = 1.0
    advance_right_formway_bit: int = 128
    max_geometry_buffer_mismatch_ratio: float = 0.1
    min_geometry_buffer_mismatch_length_m: float = 20.0
    visual_consistency_buffer_distance_m: float | None = 15.0
    max_visual_consistency_mismatch_ratio: float = 0.1
    min_visual_consistency_mismatch_length_m: float = 20.0


@dataclass(frozen=True)
class BufferSegmentResult:
    ok: bool
    reason: str
    required_rcsd_nodes: list[str]
    optional_allowed_rcsd_nodes: list[str]
    directed_rcsd_pair_nodes: list[str]
    candidate_road_ids: list[str]
    candidate_node_ids: list[str]
    retained_road_ids: list[str]
    excluded_advance_right_turn_road_ids: list[str]
    retained_node_ids: list[str]
    inner_node_ids: list[str]
    out_node_ids: list[str]
    unexpected_endpoint_node_ids: list[str]
    unexpected_mapped_semantic_node_ids: list[str]
    low_buffer_overlap_road_ids: list[str]
    min_retained_road_buffer_overlap_ratio: float | None
    geometry_buffer_coverage_issue: str | None
    rcsd_outside_swsd_buffer_length_m: float
    rcsd_outside_swsd_buffer_ratio: float
    swsd_uncovered_by_rcsd_length_m: float
    swsd_uncovered_by_rcsd_ratio: float
    missing_required_node_ids: list[str]
    selected_component_id: int | None
    candidate_road_count: int
    retained_road_count: int
    candidate_node_count: int
    retained_node_count: int
    geometry: BaseGeometry


@dataclass(frozen=True)
class _CandidateContext:
    source_geometry: BaseGeometry
    buffer_geometry: BaseGeometry
    candidate_nodes: list[dict[str, Any]]
    candidate_roads: list[dict[str, Any]]
    excluded_roads: list[dict[str, Any]]


class SpatialFeatureIndex:
    def __init__(self, features: list[dict[str, Any]]) -> None:
        self.features: list[dict[str, Any]] = []
        self.geometries: list[BaseGeometry] = []
        for feature in features:
            geometry = feature.get("geometry")
            if isinstance(geometry, BaseGeometry) and not geometry.is_empty:
                self.features.append(feature)
                self.geometries.append(geometry)
        self.tree = STRtree(self.geometries) if self.geometries else None

    def query(self, geometry: BaseGeometry) -> list[dict[str, Any]]:
        if self.tree is None:
            return []
        return [self.features[int(index)] for index in self.tree.query(geometry)]


class BufferSegmentExtractor:
    def __init__(self, *, rcsd_road_features: list[dict[str, Any]], rcsd_node_features: list[dict[str, Any]]) -> None:
        self.road_index = SpatialFeatureIndex(rcsd_road_features)
        self.node_index = SpatialFeatureIndex(rcsd_node_features)
        self.node_canonicalizer = NodeCanonicalizer.from_node_features(rcsd_node_features)
        self._candidate_cache: dict[tuple[int, float, float, float, int], _CandidateContext] = {}

    def extract(
        self,
        *,
        segment_geometry: BaseGeometry | None,
        relation: RelationCheck,
        optional_allowed_rcsd_nodes: list[str],
        all_relation_base_ids: set[str],
        unexpected_relation_base_ids: set[str] | None = None,
        directed_pair_nodes: list[str] | None = None,
        require_directed_pair: bool = False,
        require_bidirectional: bool = False,
        config: BufferExtractionConfig | None = None,
    ) -> BufferSegmentResult:
        cfg = config or BufferExtractionConfig()
        pair_nodes = _canonical_ids(relation.rcsd_pair_nodes, self.node_canonicalizer)
        directed_nodes = _effective_directed_pair_nodes(pair_nodes, _canonical_ids(directed_pair_nodes or [], self.node_canonicalizer))
        required_nodes = pair_nodes
        optional_nodes = _canonical_ids([*relation.rcsd_junc_nodes, *optional_allowed_rcsd_nodes], self.node_canonicalizer)
        relation_base_ids = set(_canonical_ids(list(all_relation_base_ids), self.node_canonicalizer))
        unexpected_base_ids = (
            set(_canonical_ids(list(unexpected_relation_base_ids or set()), self.node_canonicalizer))
            - set(required_nodes)
            - set(optional_nodes)
        )
        if segment_geometry is None or segment_geometry.is_empty:
            return _empty_result("missing_swsd_geometry", required_nodes, optional_nodes)

        candidate_context = self._candidate_context(segment_geometry, cfg)
        buffer_geometry = candidate_context.buffer_geometry
        candidate_nodes = list(candidate_context.candidate_nodes)
        candidate_roads = list(candidate_context.candidate_roads)
        excluded_roads = list(candidate_context.excluded_roads)
        candidate_roads, excluded_roads = _restore_required_corridor_advance_roads(
            selected_roads=candidate_roads,
            excluded_roads=excluded_roads,
            required_nodes=required_nodes,
            pair_nodes=pair_nodes,
            directed_pair_nodes=directed_nodes,
            require_directed_pair=require_directed_pair,
            require_bidirectional=require_bidirectional,
            node_canonicalizer=self.node_canonicalizer,
            reference_geometry=segment_geometry,
        )
        graph = _build_undirected_graph(candidate_roads, node_canonicalizer=self.node_canonicalizer)
        components = _connected_components(graph.adjacency)
        selected = _select_component(components, required_nodes)
        if selected is None:
            graph_nodes = set(graph.adjacency)
            missing = [node for node in required_nodes if node not in graph_nodes]
            reason = "required_semantic_nodes_missing_from_buffer_graph" if missing else "required_semantic_nodes_not_connected_in_buffer"
            return _result(
                ok=False,
                reason=reason,
                required_nodes=required_nodes,
                optional_nodes=optional_nodes,
                directed_nodes=directed_nodes if require_directed_pair else [],
                candidate_roads=candidate_roads,
                candidate_nodes=candidate_nodes,
                retained_edges=[],
                excluded_roads=excluded_roads,
                retained_nodes=[],
                inner_nodes=[],
                out_nodes=[],
                unexpected_endpoint_nodes=[],
                unexpected_mapped_semantic_nodes=[],
                missing_required_nodes=missing,
                selected_component_id=None,
            )

        selected_nodes = components[selected]
        selected_edges = [edge for edge in graph.edges if edge.source in selected_nodes and edge.target in selected_nodes]
        semantic_nodes = (relation_base_ids | set(self.node_canonicalizer.semantic_node_ids)) & selected_nodes
        allowed_nodes = set(required_nodes) | set(optional_nodes)
        pruned = _prune_component_seed_based(
            component_nodes=selected_nodes,
            edges=selected_edges,
            required_nodes=set(required_nodes),
            optional_nodes=set(optional_nodes),
            semantic_nodes=semantic_nodes,
            pair_nodes=pair_nodes,
            directed_pair_nodes=directed_nodes,
            require_directed_pair=require_directed_pair,
            require_bidirectional=require_bidirectional,
            reference_geometry=segment_geometry,
        )
        corridor_edges = _build_corridor_subgraph(
            pruned.retained_edges,
            required_nodes,
            pair_nodes,
            directed_nodes,
            reference_geometry=segment_geometry,
            reference_buffer_geometry=buffer_geometry,
            max_mismatch_ratio=cfg.max_geometry_buffer_mismatch_ratio,
            min_mismatch_length_m=cfg.min_geometry_buffer_mismatch_length_m,
            require_directed_pair=require_directed_pair,
            require_bidirectional=require_bidirectional,
        )
        corridor_nodes = _nodes_from_edges(corridor_edges)
        unexpected_mapped_semantic_nodes = sorted((unexpected_base_ids - set(pruned.inner_nodes)) & corridor_nodes)
        ok, reason, unexpected_endpoint_nodes = _retained_status(
            corridor_nodes,
            corridor_edges,
            required_nodes,
            pair_nodes,
            directed_nodes,
            unexpected_mapped_semantic_nodes=unexpected_mapped_semantic_nodes,
            require_directed_pair=require_directed_pair,
            require_bidirectional=require_bidirectional,
        )
        low_overlap_road_ids, min_overlap_ratio = _retained_buffer_overlap_issues(
            corridor_edges,
            buffer_geometry,
            cfg.min_road_overlap_ratio,
        )
        if ok and low_overlap_road_ids:
            ok = False
            reason = "retained_road_buffer_overlap_insufficient"
        coverage_status = _retained_geometry_buffer_coverage_status(
            corridor_edges,
            segment_geometry,
            buffer_geometry,
            buffer_distance_m=cfg.buffer_distance_m,
            max_mismatch_ratio=cfg.max_geometry_buffer_mismatch_ratio,
            min_mismatch_length_m=cfg.min_geometry_buffer_mismatch_length_m,
        )
        visual_buffer_distance = cfg.visual_consistency_buffer_distance_m
        soft_visual_consistency_issue = False
        if (
            ok
            and coverage_status.issue is None
            and visual_buffer_distance is not None
            and 0 < visual_buffer_distance < cfg.buffer_distance_m
        ):
            visual_status = _retained_geometry_buffer_coverage_status(
                corridor_edges,
                segment_geometry,
                segment_geometry.buffer(visual_buffer_distance),
                buffer_distance_m=visual_buffer_distance,
                max_mismatch_ratio=cfg.max_visual_consistency_mismatch_ratio,
                min_mismatch_length_m=cfg.min_visual_consistency_mismatch_length_m,
            )
            if visual_status.issue is not None:
                coverage_status = _visual_consistency_status(visual_status)
                soft_visual_consistency_issue = _is_soft_visual_consistency_issue(coverage_status)
        if ok and coverage_status.issue is not None and not soft_visual_consistency_issue:
            ok = False
            reason = coverage_status.issue
        return _result(
            ok=ok,
            reason=reason,
            required_nodes=required_nodes,
            optional_nodes=optional_nodes,
            directed_nodes=directed_nodes if require_directed_pair else [],
            candidate_roads=candidate_roads,
            candidate_nodes=candidate_nodes,
            retained_edges=corridor_edges,
            excluded_roads=excluded_roads,
            retained_nodes=sorted(corridor_nodes),
            inner_nodes=sorted(set(pruned.inner_nodes) & corridor_nodes),
            out_nodes=pruned.out_nodes,
            unexpected_endpoint_nodes=unexpected_endpoint_nodes,
            unexpected_mapped_semantic_nodes=unexpected_mapped_semantic_nodes,
            low_overlap_road_ids=low_overlap_road_ids,
            min_overlap_ratio=min_overlap_ratio,
            coverage_status=coverage_status,
            missing_required_nodes=[],
            selected_component_id=selected,
        )

    def _candidate_context(self, segment_geometry: BaseGeometry, cfg: BufferExtractionConfig) -> _CandidateContext:
        key = (
            id(segment_geometry),
            cfg.buffer_distance_m,
            cfg.min_road_overlap_ratio,
            cfg.min_road_overlap_length_m,
            cfg.advance_right_formway_bit,
        )
        cached = self._candidate_cache.get(key)
        if cached is not None and cached.source_geometry is segment_geometry:
            return cached
        buffer_geometry = segment_geometry.buffer(cfg.buffer_distance_m)
        candidate_nodes = _select_candidate_nodes(self.node_index.query(buffer_geometry), buffer_geometry)
        candidate_roads, excluded_roads = _select_candidate_roads(
            self.road_index.query(buffer_geometry),
            buffer_geometry,
            cfg,
            node_canonicalizer=self.node_canonicalizer,
        )
        if len(self._candidate_cache) >= 512:
            self._candidate_cache.clear()
        context = _CandidateContext(
            source_geometry=segment_geometry,
            buffer_geometry=buffer_geometry,
            candidate_nodes=candidate_nodes,
            candidate_roads=candidate_roads,
            excluded_roads=excluded_roads,
        )
        self._candidate_cache[key] = context
        return context


@dataclass
class _CandidateGraph:
    adjacency: dict[str, set[str]]
    edges: list[Edge]


@dataclass(frozen=True)
class _SeedGroup:
    seed_nodes: set[str]
    scope_nodes: set[str]
    leaves: set[str]


@dataclass(frozen=True)
class _PrunedGraph:
    retained_nodes: set[str]
    retained_edges: list[Edge]
    inner_nodes: list[str]
    out_nodes: list[str]


@dataclass(frozen=True)
class _GeometryCoverageStatus:
    issue: str | None
    rcsd_outside_length_m: float
    rcsd_outside_ratio: float
    swsd_uncovered_length_m: float
    swsd_uncovered_ratio: float


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
        corridor_path = _shortest_directed_path_covering_nodes(
            component_edges,
            directed_pair_nodes[0],
            directed_pair_nodes[1],
            required_nodes,
            reference_geometry=reference_geometry,
        )
        corridor_edge_ids = set(corridor_path or [])
        if corridor_path is None:
            corridor_edge_ids = {edge.edge_id for edge in component_edges}
    else:
        corridor_edge_ids = {
            edge_id
            for path in _minimum_terminal_edge_paths(component_edges, required_nodes, reference_geometry=reference_geometry)
            for edge_id in path
        }
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
    if require_bidirectional:
        return _pair_nodes_bidirectionally_reachable(edges, pair_nodes)
    if not require_directed_pair:
        return True
    if len(directed_pair_nodes) != 2:
        return False
    return (
        _shortest_directed_path_covering_nodes(
            edges,
            directed_pair_nodes[0],
            directed_pair_nodes[1],
            required_nodes,
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
        if snode == enode:
            continue
        geometry = feature.get("geometry")
        edge = Edge(f"{road_id}:u", road_id, snode, enode, geometry if isinstance(geometry, BaseGeometry) else None, props)
        edges.append(edge)
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
    semantic_nodes: set[str],
    pair_nodes: list[str],
    directed_pair_nodes: list[str],
    require_directed_pair: bool,
    require_bidirectional: bool,
    reference_geometry: BaseGeometry | None,
) -> _PrunedGraph:
    adjacency = _adjacency_from_edges(edges)
    allowed_nodes = required_nodes & component_nodes
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


def _build_corridor_subgraph(
    edges: list[Edge],
    required_nodes: list[str],
    pair_nodes: list[str],
    directed_pair_nodes: list[str],
    *,
    reference_geometry: BaseGeometry | None,
    reference_buffer_geometry: BaseGeometry | None = None,
    max_mismatch_ratio: float = 0.1,
    min_mismatch_length_m: float = 20.0,
    require_directed_pair: bool,
    require_bidirectional: bool,
) -> list[Edge]:
    if require_directed_pair and len(pair_nodes) == 2:
        source, target = _effective_directed_pair_nodes(pair_nodes, directed_pair_nodes)
        path = _shortest_directed_path_covering_nodes(
            edges,
            source,
            target,
            required_nodes,
            reference_geometry=reference_geometry,
        )
        if path is None:
            return []
        return [edge for edge in edges if edge.edge_id in set(path)]

    selected_edge_ids: set[str] = set()
    for path in _minimum_terminal_edge_paths(edges, required_nodes, reference_geometry=reference_geometry):
        selected_edge_ids.update(path)

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
            reference_buffer_geometry=reference_buffer_geometry,
            max_mismatch_ratio=max_mismatch_ratio,
            min_mismatch_length_m=min_mismatch_length_m,
        )
    return selected_edges


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
    reference_buffer_geometry = _path_reference_buffer(reference_geometry)
    for edge in edges:
        weight = _edge_weight(
            edge,
            reference_geometry=reference_geometry,
            reference_buffer_geometry=reference_buffer_geometry,
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
    reference_buffer_geometry = _path_reference_buffer(reference_geometry)
    weights = {
        edge.edge_id: _edge_weight(
            edge,
            reference_geometry=reference_geometry,
            reference_buffer_geometry=reference_buffer_geometry,
            required_nodes=required_nodes,
        )
        for edge in edges
    }
    return sum(weights.get(edge_id, 1.0) for edge_id in path)


def _edge_weight(
    edge: Edge,
    *,
    reference_geometry: BaseGeometry | None,
    reference_buffer_geometry: BaseGeometry | None,
    required_nodes: set[str],
) -> float:
    length = 1.0
    if edge.geometry is not None and not edge.geometry.is_empty:
        length = max(float(edge.geometry.length), 1.0)
    if reference_geometry is None or reference_geometry.is_empty:
        return length
    shortcut_penalty = _required_shortcut_penalty(edge, length, reference_geometry, required_nodes)
    off_reference_penalty = _off_reference_penalty(edge, length, reference_buffer_geometry)
    return length + shortcut_penalty + off_reference_penalty


def _path_reference_buffer(reference_geometry: BaseGeometry | None) -> BaseGeometry | None:
    if reference_geometry is None or reference_geometry.is_empty:
        return None
    return reference_geometry.buffer(PATH_REFERENCE_BUFFER_M)


def _off_reference_penalty(edge: Edge, length: float, reference_buffer_geometry: BaseGeometry | None) -> float:
    if reference_buffer_geometry is None or edge.geometry is None or edge.geometry.is_empty:
        return 0.0
    inside_length = float(edge.geometry.intersection(reference_buffer_geometry).length)
    off_reference_length = max(0.0, length - inside_length)
    return off_reference_length * PATH_OFF_REFERENCE_PENALTY_MULTIPLIER


def _required_shortcut_penalty(edge: Edge, length: float, reference_geometry: BaseGeometry, required_nodes: set[str]) -> float:
    if edge.source not in required_nodes or edge.target not in required_nodes:
        return 0.0
    if not required_nodes or length >= max(8.0, float(reference_geometry.length) * 0.08):
        return 0.0
    return max(10000.0, float(reference_geometry.length) * 100.0)


def _include_internal_corridor_edges(
    edges: list[Edge],
    selected_edges: list[Edge],
    *,
    required_nodes: set[str],
    reference_buffer_geometry: BaseGeometry | None,
    max_mismatch_ratio: float,
    min_mismatch_length_m: float,
) -> list[Edge]:
    retained_nodes = _nodes_from_edges(selected_edges)
    selected_edge_ids = {edge.edge_id for edge in selected_edges}
    result = list(selected_edges)
    for edge in edges:
        if edge.edge_id in selected_edge_ids:
            continue
        if edge.source not in retained_nodes or edge.target not in retained_nodes:
            continue
        if edge.source in required_nodes and edge.target in required_nodes:
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


def _mismatch_exceeds_threshold(
    mismatch_length: float,
    mismatch_ratio: float,
    *,
    max_mismatch_ratio: float,
    min_mismatch_length_m: float,
) -> bool:
    return mismatch_ratio > max_mismatch_ratio or mismatch_length > min_mismatch_length_m


def _nodes_from_edges(edges: list[Edge]) -> set[str]:
    nodes: set[str] = set()
    for edge in edges:
        nodes.add(edge.source)
        nodes.add(edge.target)
    return nodes


def _retained_status(
    retained_nodes: set[str],
    retained_edges: list[Edge],
    required_nodes: list[str],
    pair_nodes: list[str],
    directed_pair_nodes: list[str],
    *,
    unexpected_mapped_semantic_nodes: list[str],
    require_directed_pair: bool,
    require_bidirectional: bool,
) -> tuple[bool, str, list[str]]:
    if not retained_edges:
        if require_directed_pair:
            return False, "rcsd_directed_path_missing", []
        return False, "buffer_pruned_to_empty", []
    if require_directed_pair and not _pair_nodes_reachable_in_order(retained_edges, _effective_directed_pair_nodes(pair_nodes, directed_pair_nodes)):
        return False, "rcsd_directed_path_missing", []
    if not set(required_nodes).issubset(retained_nodes) or not _required_nodes_connected(retained_edges, required_nodes):
        if require_directed_pair:
            return False, "rcsd_directed_path_missing", []
        return False, "required_semantic_nodes_disconnected_after_pruning", []
    if unexpected_mapped_semantic_nodes:
        return False, "unexpected_mapped_semantic_nodes", []
    if require_bidirectional and not _pair_nodes_bidirectionally_reachable(retained_edges, pair_nodes):
        return False, "rcsd_not_bidirectional_for_swsd_dual", []
    unexpected_endpoint_nodes = _unexpected_endpoint_nodes(retained_edges, pair_nodes)
    if unexpected_endpoint_nodes:
        return False, "unexpected_retained_endpoint_nodes", unexpected_endpoint_nodes
    return True, "passed", []


def _retained_buffer_overlap_issues(
    edges: list[Edge],
    buffer_geometry: BaseGeometry,
    min_overlap_ratio: float,
) -> tuple[list[str], float | None]:
    if min_overlap_ratio <= 0:
        return [], None
    low_road_ids: list[str] = []
    seen: set[str] = set()
    ratios: list[float] = []
    for edge in edges:
        geometry = edge.geometry
        if geometry is None or geometry.is_empty:
            ratio = 0.0
        else:
            length = float(geometry.length)
            if length <= 0:
                continue
            overlap_length = float(geometry.intersection(buffer_geometry).length) if geometry.intersects(buffer_geometry) else 0.0
            ratio = overlap_length / length
        ratios.append(ratio)
        if ratio + 1e-9 >= min_overlap_ratio or edge.road_id in seen:
            continue
        seen.add(edge.road_id)
        low_road_ids.append(edge.road_id)
    return low_road_ids, min(ratios) if ratios else None


def _retained_geometry_buffer_coverage_status(
    edges: list[Edge],
    segment_geometry: BaseGeometry,
    swsd_buffer_geometry: BaseGeometry,
    *,
    buffer_distance_m: float,
    max_mismatch_ratio: float,
    min_mismatch_length_m: float,
) -> _GeometryCoverageStatus:
    retained_geometry = _edge_geometry(edges)
    retained_length = float(retained_geometry.length) if not retained_geometry.is_empty else 0.0
    segment_length = float(segment_geometry.length) if not segment_geometry.is_empty else 0.0
    rcsd_outside_length = (
        float(retained_geometry.difference(swsd_buffer_geometry).length)
        if retained_length > 0
        else 0.0
    )
    swsd_uncovered_length = (
        float(segment_geometry.difference(retained_geometry.buffer(buffer_distance_m)).length)
        if retained_length > 0 and segment_length > 0
        else 0.0
    )
    rcsd_outside_ratio = rcsd_outside_length / retained_length if retained_length > 0 else 0.0
    swsd_uncovered_ratio = swsd_uncovered_length / segment_length if segment_length > 0 else 0.0
    issue = None
    if _mismatch_exceeds_threshold(
        rcsd_outside_length,
        rcsd_outside_ratio,
        max_mismatch_ratio=max_mismatch_ratio,
        min_mismatch_length_m=min_mismatch_length_m,
    ):
        issue = "retained_geometry_outside_swsd_buffer_scope"
    elif _mismatch_exceeds_threshold(
        swsd_uncovered_length,
        swsd_uncovered_ratio,
        max_mismatch_ratio=max_mismatch_ratio,
        min_mismatch_length_m=min_mismatch_length_m,
    ):
        issue = "swsd_geometry_not_covered_by_retained_rcsd"
    return _GeometryCoverageStatus(
        issue=issue,
        rcsd_outside_length_m=rcsd_outside_length,
        rcsd_outside_ratio=rcsd_outside_ratio,
        swsd_uncovered_length_m=swsd_uncovered_length,
        swsd_uncovered_ratio=swsd_uncovered_ratio,
    )


def _visual_consistency_status(status: _GeometryCoverageStatus) -> _GeometryCoverageStatus:
    issue = status.issue
    if issue == "retained_geometry_outside_swsd_buffer_scope":
        issue = "retained_geometry_outside_swsd_visual_consistency_scope"
    elif issue == "swsd_geometry_not_covered_by_retained_rcsd":
        issue = "swsd_visual_continuity_not_covered_by_retained_rcsd"
    return _GeometryCoverageStatus(
        issue=issue,
        rcsd_outside_length_m=status.rcsd_outside_length_m,
        rcsd_outside_ratio=status.rcsd_outside_ratio,
        swsd_uncovered_length_m=status.swsd_uncovered_length_m,
        swsd_uncovered_ratio=status.swsd_uncovered_ratio,
    )


def _is_soft_visual_consistency_issue(status: _GeometryCoverageStatus) -> bool:
    return status.issue in {
        "retained_geometry_outside_swsd_visual_consistency_scope",
        "swsd_visual_continuity_not_covered_by_retained_rcsd",
    }


def _unexpected_endpoint_nodes(edges: list[Edge], pair_nodes: list[str]) -> list[str]:
    pair_node_set = set(pair_nodes)
    adjacency = _adjacency_from_edges(edges)
    return sorted(node for node, neighbors in adjacency.items() if len(neighbors) <= 1 and node not in pair_node_set)


def _required_nodes_connected(edges: list[Edge], required_nodes: list[str]) -> bool:
    if not required_nodes:
        return True
    adjacency = _adjacency_from_edges(edges)
    source = required_nodes[0]
    seen = {source}
    queue: deque[str] = deque([source])
    while queue:
        node = queue.popleft()
        for neighbor in adjacency.get(node, set()):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(neighbor)
    return set(required_nodes).issubset(seen)


def _pair_nodes_bidirectionally_reachable(edges: list[Edge], pair_nodes: list[str]) -> bool:
    if len(pair_nodes) != 2:
        return False
    source, target = pair_nodes
    adjacency = _directed_adjacency_from_edges(edges)
    return _directed_reachable(adjacency, source, target) and _directed_reachable(adjacency, target, source)


def _pair_nodes_reachable_in_order(edges: list[Edge], pair_nodes: list[str]) -> bool:
    if len(pair_nodes) != 2:
        return False
    source, target = pair_nodes
    adjacency = _directed_adjacency_from_edges(edges)
    return _directed_reachable(adjacency, source, target)


def _effective_directed_pair_nodes(pair_nodes: list[str], directed_pair_nodes: list[str]) -> list[str]:
    if len(directed_pair_nodes) == 2:
        return directed_pair_nodes
    if len(pair_nodes) == 2:
        return pair_nodes
    return []


def _directed_adjacency_from_edges(edges: list[Edge]) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        direction = _coerce_int(edge.properties.get("direction")) if edge.properties else None
        if direction in {0, 1, 2}:
            adjacency[edge.source].add(edge.target)
        if direction in {0, 1, 3}:
            adjacency[edge.target].add(edge.source)
    return dict(adjacency)


def _directed_reachable(adjacency: dict[str, set[str]], source: str, target: str) -> bool:
    seen = {source}
    queue: deque[str] = deque([source])
    while queue:
        node = queue.popleft()
        if node == target:
            return True
        for neighbor in adjacency.get(node, set()):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(neighbor)
    return False


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _adjacency_from_edges(edges: Any) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)
    return dict(adjacency)


def _result(
    *,
    ok: bool,
    reason: str,
    required_nodes: list[str],
    optional_nodes: list[str],
    directed_nodes: list[str],
    candidate_roads: list[dict[str, Any]],
    candidate_nodes: list[dict[str, Any]],
    retained_edges: list[Edge],
    excluded_roads: list[dict[str, Any]],
    retained_nodes: list[str],
    inner_nodes: list[str],
    out_nodes: list[str],
    unexpected_endpoint_nodes: list[str],
    unexpected_mapped_semantic_nodes: list[str],
    low_overlap_road_ids: list[str] | None = None,
    min_overlap_ratio: float | None = None,
    coverage_status: _GeometryCoverageStatus | None = None,
    missing_required_nodes: list[str],
    selected_component_id: int | None,
) -> BufferSegmentResult:
    retained_road_ids = _unique_ids(edge.road_id for edge in retained_edges)
    retained_geometry = _edge_geometry(retained_edges)
    candidate_road_ids = _road_ids(candidate_roads)
    candidate_node_ids = _node_ids(candidate_nodes)
    return BufferSegmentResult(
        ok=ok,
        reason=reason,
        required_rcsd_nodes=required_nodes,
        optional_allowed_rcsd_nodes=optional_nodes,
        directed_rcsd_pair_nodes=directed_nodes,
        candidate_road_ids=candidate_road_ids,
        candidate_node_ids=candidate_node_ids,
        retained_road_ids=retained_road_ids,
        excluded_advance_right_turn_road_ids=_road_ids(excluded_roads),
        retained_node_ids=retained_nodes,
        inner_node_ids=inner_nodes,
        out_node_ids=out_nodes,
        unexpected_endpoint_node_ids=unexpected_endpoint_nodes or [],
        unexpected_mapped_semantic_node_ids=unexpected_mapped_semantic_nodes or [],
        low_buffer_overlap_road_ids=low_overlap_road_ids or [],
        min_retained_road_buffer_overlap_ratio=min_overlap_ratio,
        geometry_buffer_coverage_issue=coverage_status.issue if coverage_status else None,
        rcsd_outside_swsd_buffer_length_m=coverage_status.rcsd_outside_length_m if coverage_status else 0.0,
        rcsd_outside_swsd_buffer_ratio=coverage_status.rcsd_outside_ratio if coverage_status else 0.0,
        swsd_uncovered_by_rcsd_length_m=coverage_status.swsd_uncovered_length_m if coverage_status else 0.0,
        swsd_uncovered_by_rcsd_ratio=coverage_status.swsd_uncovered_ratio if coverage_status else 0.0,
        missing_required_node_ids=missing_required_nodes,
        selected_component_id=selected_component_id,
        candidate_road_count=len(candidate_road_ids),
        retained_road_count=len(retained_road_ids),
        candidate_node_count=len(candidate_node_ids),
        retained_node_count=len(retained_nodes),
        geometry=retained_geometry,
    )


def _empty_result(reason: str, required_nodes: list[str], optional_nodes: list[str]) -> BufferSegmentResult:
    return BufferSegmentResult(
        ok=False,
        reason=reason,
        required_rcsd_nodes=required_nodes,
        optional_allowed_rcsd_nodes=optional_nodes,
        directed_rcsd_pair_nodes=[],
        candidate_road_ids=[],
        candidate_node_ids=[],
        retained_road_ids=[],
        excluded_advance_right_turn_road_ids=[],
        retained_node_ids=[],
        inner_node_ids=[],
        out_node_ids=[],
        unexpected_endpoint_node_ids=[],
        unexpected_mapped_semantic_node_ids=[],
        low_buffer_overlap_road_ids=[],
        min_retained_road_buffer_overlap_ratio=None,
        geometry_buffer_coverage_issue=None,
        rcsd_outside_swsd_buffer_length_m=0.0,
        rcsd_outside_swsd_buffer_ratio=0.0,
        swsd_uncovered_by_rcsd_length_m=0.0,
        swsd_uncovered_by_rcsd_ratio=0.0,
        missing_required_node_ids=list(required_nodes),
        selected_component_id=None,
        candidate_road_count=0,
        retained_road_count=0,
        candidate_node_count=0,
        retained_node_count=0,
        geometry=GeometryCollection(),
    )


def _edge_geometry(edges: list[Edge]) -> BaseGeometry:
    geometries = [edge.geometry for edge in edges if edge.geometry is not None]
    if not geometries:
        return GeometryCollection()
    return unary_union(geometries)


def _road_ids(features: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for feature in features:
        road_id = _feature_road_id(feature)
        if road_id is None:
            continue
        if road_id not in seen:
            seen.add(road_id)
            result.append(road_id)
    return result


def _feature_road_id(feature: dict[str, Any]) -> str | None:
    try:
        return normalize_id(_first_present(feature.get("properties") or {}, ["id", "road_id", "roadid"]))
    except (KeyError, ParseError):
        return None


def _node_ids(features: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for feature in features:
        try:
            node_id = normalize_id(_first_present(feature.get("properties") or {}, ["id", "node_id", "nodeid"]))
        except (KeyError, ParseError):
            continue
        if node_id not in seen:
            seen.add(node_id)
            result.append(node_id)
    return result


def _unique_ids(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _canonical_ids(values: list[str], node_canonicalizer: NodeCanonicalizer) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        try:
            text = node_canonicalizer.canonicalize(value)
        except ParseError:
            continue
        if text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _endpoint_in_buffer(geometry: BaseGeometry, buffer_geometry: BaseGeometry) -> bool:
    if isinstance(geometry, LineString):
        coords = list(geometry.coords)
    else:
        coords = list(geometry.boundary.coords) if hasattr(geometry.boundary, "coords") else []
    if not coords:
        return False
    return buffer_geometry.covers(Point(coords[0])) or buffer_geometry.covers(Point(coords[-1]))


def _first_present(props: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in props and props[name] not in (None, ""):
            return props[name]
    raise KeyError(f"missing field: {'/'.join(names)}")
