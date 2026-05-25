from __future__ import annotations

from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from typing import Any

from shapely.geometry import GeometryCollection, LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .graph_builders import Edge
from .parsing import ParseError, normalize_id
from .relation_mapping import RelationCheck


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
        required_nodes = _unique_ids([*relation.rcsd_pair_nodes, *relation.rcsd_junc_nodes])
        optional_nodes = _unique_ids(optional_allowed_rcsd_nodes)
        if segment_geometry is None or segment_geometry.is_empty:
            return _empty_result("missing_swsd_geometry", required_nodes, optional_nodes)

        buffer_geometry = segment_geometry.buffer(cfg.buffer_distance_m)
        candidate_nodes = _select_candidate_nodes(self.node_index.query(buffer_geometry), buffer_geometry)
        candidate_roads, excluded_roads = _select_candidate_roads(self.road_index.query(buffer_geometry), buffer_geometry, cfg)
        graph = _build_undirected_graph(candidate_roads)
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
                missing_required_nodes=missing,
                selected_component_id=None,
            )

        selected_nodes = components[selected]
        selected_edges = [edge for edge in graph.edges if edge.source in selected_nodes and edge.target in selected_nodes]
        retained_nodes, retained_edges = _prune_component(selected_nodes, selected_edges, set(required_nodes))
        semantic_nodes = all_relation_base_ids & selected_nodes
        allowed_nodes = set(required_nodes) | set(optional_nodes)
        inner_nodes = sorted((semantic_nodes & retained_nodes) - allowed_nodes)
        out_nodes = sorted((semantic_nodes - retained_nodes) - allowed_nodes)
        return _result(
            ok=bool(retained_edges),
            reason="passed" if retained_edges else "buffer_pruned_to_empty",
            required_nodes=required_nodes,
            optional_nodes=optional_nodes,
            candidate_roads=candidate_roads,
            candidate_nodes=candidate_nodes,
            retained_edges=retained_edges,
            excluded_roads=excluded_roads,
            retained_nodes=sorted(retained_nodes),
            inner_nodes=inner_nodes,
            out_nodes=out_nodes,
            missing_required_nodes=[],
            selected_component_id=selected,
        )


@dataclass
class _CandidateGraph:
    adjacency: dict[str, set[str]]
    edges: list[Edge]


def is_advance_right_turn_road(props: dict[str, Any], *, formway_bit: int = 128) -> bool:
    value = _parse_int(props.get("formway"))
    return value is not None and (value & formway_bit) != 0


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


def _build_undirected_graph(features: list[dict[str, Any]]) -> _CandidateGraph:
    adjacency: dict[str, set[str]] = defaultdict(set)
    edges: list[Edge] = []
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            road_id = normalize_id(_first_present(props, ["id", "road_id", "roadid"]))
            snode = normalize_id(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
            enode = normalize_id(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
        except (KeyError, ParseError):
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


def _prune_component(component_nodes: set[str], edges: list[Edge], required_nodes: set[str]) -> tuple[set[str], list[Edge]]:
    retained = set(component_nodes)
    changed = True
    while changed:
        changed = False
        degree = Counter()
        for edge in edges:
            if edge.source in retained and edge.target in retained:
                degree[edge.source] += 1
                degree[edge.target] += 1
        for node in list(retained):
            if node not in required_nodes and degree[node] <= 1:
                retained.remove(node)
                changed = True
    retained_edges = [edge for edge in edges if edge.source in retained and edge.target in retained]
    return retained, retained_edges


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


def _parse_int(value: Any) -> int | None:
    try:
        return int(float(str(value).strip()))
    except Exception:
        return None
