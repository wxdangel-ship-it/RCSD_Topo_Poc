from __future__ import annotations

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


@dataclass(frozen=True)
class BufferExtractionConfig:
    buffer_distance_m: float = 50.0
    min_road_overlap_ratio: float = 0.2
    min_road_overlap_length_m: float = 1.0
    advance_right_formway_bit: int = 128


@dataclass(frozen=True)
class BufferSegmentResult:
    ok: bool
    reason: str
    required_rcsd_nodes: list[str]
    optional_allowed_rcsd_nodes: list[str]
    candidate_road_ids: list[str]
    candidate_node_ids: list[str]
    retained_road_ids: list[str]
    excluded_advance_right_turn_road_ids: list[str]
    retained_node_ids: list[str]
    inner_node_ids: list[str]
    out_node_ids: list[str]
    unexpected_endpoint_node_ids: list[str]
    missing_required_node_ids: list[str]
    selected_component_id: int | None
    candidate_road_count: int
    retained_road_count: int
    candidate_node_count: int
    retained_node_count: int
    geometry: BaseGeometry


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

    def extract(
        self,
        *,
        segment_geometry: BaseGeometry | None,
        relation: RelationCheck,
        optional_allowed_rcsd_nodes: list[str],
        all_relation_base_ids: set[str],
        config: BufferExtractionConfig | None = None,
    ) -> BufferSegmentResult:
        cfg = config or BufferExtractionConfig()
        pair_nodes = _canonical_ids(relation.rcsd_pair_nodes, self.node_canonicalizer)
        required_nodes = _canonical_ids([*relation.rcsd_pair_nodes, *relation.rcsd_junc_nodes], self.node_canonicalizer)
        optional_nodes = _canonical_ids(optional_allowed_rcsd_nodes, self.node_canonicalizer)
        relation_base_ids = set(_canonical_ids(list(all_relation_base_ids), self.node_canonicalizer))
        if segment_geometry is None or segment_geometry.is_empty:
            return _empty_result("missing_swsd_geometry", required_nodes, optional_nodes)

        buffer_geometry = segment_geometry.buffer(cfg.buffer_distance_m)
        candidate_nodes = _select_candidate_nodes(self.node_index.query(buffer_geometry), buffer_geometry)
        candidate_roads, excluded_roads = _select_candidate_roads(self.road_index.query(buffer_geometry), buffer_geometry, cfg)
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
                candidate_roads=candidate_roads,
                candidate_nodes=candidate_nodes,
                retained_edges=[],
                excluded_roads=excluded_roads,
                retained_nodes=[],
                inner_nodes=[],
                out_nodes=[],
                unexpected_endpoint_nodes=[],
                missing_required_nodes=missing,
                selected_component_id=None,
            )

        selected_nodes = components[selected]
        selected_edges = [edge for edge in graph.edges if edge.source in selected_nodes and edge.target in selected_nodes]
        semantic_nodes = relation_base_ids & selected_nodes
        allowed_nodes = set(required_nodes) | set(optional_nodes)
        pruned = _prune_component_seed_based(
            component_nodes=selected_nodes,
            edges=selected_edges,
            required_nodes=set(required_nodes),
            optional_nodes=set(optional_nodes),
            semantic_nodes=semantic_nodes,
        )
        ok, reason, unexpected_endpoint_nodes = _retained_status(pruned.retained_nodes, pruned.retained_edges, required_nodes, pair_nodes)
        return _result(
            ok=ok,
            reason=reason,
            required_nodes=required_nodes,
            optional_nodes=optional_nodes,
            candidate_roads=candidate_roads,
            candidate_nodes=candidate_nodes,
            retained_edges=pruned.retained_edges,
            excluded_roads=excluded_roads,
            retained_nodes=sorted(pruned.retained_nodes),
            inner_nodes=pruned.inner_nodes,
            out_nodes=pruned.out_nodes,
            unexpected_endpoint_nodes=unexpected_endpoint_nodes,
            missing_required_nodes=[],
            selected_component_id=selected,
        )


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


def _select_candidate_roads(
    features: list[dict[str, Any]], buffer_geometry: BaseGeometry, config: BufferExtractionConfig
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []
    for feature in features:
        props = dict(feature.get("properties") or {})
        geometry = feature.get("geometry")
        if not isinstance(geometry, BaseGeometry) or geometry.is_empty or not geometry.intersects(buffer_geometry):
            continue
        if is_advance_right_turn_road(props, formway_bit=config.advance_right_formway_bit):
            excluded.append(feature)
            continue
        overlap_length = float(geometry.intersection(buffer_geometry).length)
        road_length = float(geometry.length)
        ratio = overlap_length / road_length if road_length > 0 else 0.0
        if ratio >= config.min_road_overlap_ratio or overlap_length >= config.min_road_overlap_length_m or _endpoint_in_buffer(geometry, buffer_geometry):
            selected.append(feature)
    return selected, excluded


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
) -> _PrunedGraph:
    adjacency = _adjacency_from_edges(edges)
    allowed_nodes = (required_nodes | optional_nodes) & component_nodes
    extra_semantic_nodes = (semantic_nodes & component_nodes) - allowed_nodes
    inner_nodes: set[str] = set()
    out_nodes: set[str] = set()
    remove_nodes: set[str] = set()
    for group in _seed_groups(extra_semantic_nodes, adjacency, allowed_nodes):
        if group.leaves and group.leaves.issubset(allowed_nodes):
            inner_nodes.update(group.seed_nodes)
        else:
            out_nodes.update(group.seed_nodes)
            remove_nodes.update(group.scope_nodes)

    candidate_nodes = set(component_nodes) - remove_nodes
    candidate_edges = [edge for edge in edges if edge.source in candidate_nodes and edge.target in candidate_nodes]
    protected_nodes = (allowed_nodes | inner_nodes) & candidate_nodes
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


def _retained_status(retained_nodes: set[str], retained_edges: list[Edge], required_nodes: list[str], pair_nodes: list[str]) -> tuple[bool, str, list[str]]:
    if not retained_edges:
        return False, "buffer_pruned_to_empty", []
    if not set(required_nodes).issubset(retained_nodes) or not _required_nodes_connected(retained_edges, required_nodes):
        return False, "required_semantic_nodes_disconnected_after_pruning", []
    unexpected_endpoint_nodes = _unexpected_endpoint_nodes(retained_edges, pair_nodes)
    if unexpected_endpoint_nodes:
        return False, "unexpected_retained_endpoint_nodes", unexpected_endpoint_nodes
    return True, "passed", []


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
    candidate_roads: list[dict[str, Any]],
    candidate_nodes: list[dict[str, Any]],
    retained_edges: list[Edge],
    excluded_roads: list[dict[str, Any]],
    retained_nodes: list[str],
    inner_nodes: list[str],
    out_nodes: list[str],
    unexpected_endpoint_nodes: list[str],
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
        candidate_road_ids=candidate_road_ids,
        candidate_node_ids=candidate_node_ids,
        retained_road_ids=retained_road_ids,
        excluded_advance_right_turn_road_ids=_road_ids(excluded_roads),
        retained_node_ids=retained_nodes,
        inner_node_ids=inner_nodes,
        out_node_ids=out_nodes,
        unexpected_endpoint_node_ids=unexpected_endpoint_nodes or [],
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
        candidate_road_ids=[],
        candidate_node_ids=[],
        retained_road_ids=[],
        excluded_advance_right_turn_road_ids=[],
        retained_node_ids=[],
        inner_node_ids=[],
        out_node_ids=[],
        unexpected_endpoint_node_ids=[],
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
        try:
            road_id = normalize_id(_first_present(feature.get("properties") or {}, ["id", "road_id", "roadid"]))
        except (KeyError, ParseError):
            continue
        if road_id not in seen:
            seen.add(road_id)
            result.append(road_id)
    return result


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
