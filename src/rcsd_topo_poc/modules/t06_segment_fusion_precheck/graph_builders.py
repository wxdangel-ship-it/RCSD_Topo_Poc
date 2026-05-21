from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from shapely.geometry import GeometryCollection
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .parsing import ParseError, normalize_id


@dataclass(frozen=True)
class Edge:
    edge_id: str
    road_id: str
    source: str
    target: str
    geometry: BaseGeometry | None
    properties: dict[str, Any]


@dataclass(frozen=True)
class PathCandidate:
    edges: list[Edge]

    @property
    def road_ids(self) -> list[str]:
        return [edge.road_id for edge in self.edges]

    @property
    def node_path(self) -> list[str]:
        if not self.edges:
            return []
        return [self.edges[0].source] + [edge.target for edge in self.edges]

    @property
    def geometry(self) -> BaseGeometry:
        geometries = [edge.geometry for edge in self.edges if edge.geometry is not None]
        if not geometries:
            return GeometryCollection()
        return unary_union(geometries)

    @property
    def length(self) -> float:
        return float(sum((edge.geometry.length if edge.geometry is not None else 0.0) for edge in self.edges))


class DirectedGraph:
    def __init__(self) -> None:
        self.adjacency: dict[str, list[Edge]] = defaultdict(list)
        self.invalid_rows: list[dict[str, Any]] = []

    def add_edge(self, edge: Edge) -> None:
        self.adjacency[edge.source].append(edge)

    def reachable(self, source: str, target: str) -> bool:
        return bool(self.find_paths(source, target, max_paths=1))

    def find_paths(self, source: str, target: str, *, max_paths: int = 3, max_depth: int = 40) -> list[PathCandidate]:
        source = normalize_id(source)
        target = normalize_id(target)
        queue: deque[tuple[str, list[Edge], set[str]]] = deque([(source, [], {source})])
        paths: list[PathCandidate] = []
        while queue and len(paths) < max_paths:
            node, edges, seen = queue.popleft()
            if len(edges) > max_depth:
                continue
            if node == target and edges:
                paths.append(PathCandidate(edges=edges))
                continue
            for edge in self.adjacency.get(node, []):
                if edge.target in seen:
                    continue
                queue.append((edge.target, edges + [edge], seen | {edge.target}))
        return paths


def build_road_graph(features: list[dict[str, Any]]) -> DirectedGraph:
    graph = DirectedGraph()
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            road_id = normalize_id(_first_present(props, ["id", "road_id", "roadid"]))
            snode = normalize_id(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
            enode = normalize_id(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
            direction = parse_direction(_first_present(props, ["direction"]))
        except (KeyError, ParseError, ValueError) as exc:
            graph.invalid_rows.append({"properties": props, "reason": str(exc)})
            continue
        geometry = feature.get("geometry")
        if direction in {"both", "forward"}:
            graph.add_edge(Edge(f"{road_id}:f", road_id, snode, enode, geometry, props))
        if direction in {"both", "reverse"}:
            graph.add_edge(Edge(f"{road_id}:r", road_id, enode, snode, geometry, props))
    return graph


def parse_direction(value: Any) -> str:
    text = str(value).strip()
    if text in {"0", "1"}:
        return "both"
    if text == "2":
        return "forward"
    if text == "3":
        return "reverse"
    raise ValueError(f"invalid direction: {value}")


def subset_road_features(features: list[dict[str, Any]], road_ids: list[str]) -> list[dict[str, Any]]:
    wanted = set(road_ids)
    selected: list[dict[str, Any]] = []
    for feature in features:
        try:
            road_id = normalize_id(_first_present(feature.get("properties") or {}, ["id", "road_id", "roadid"]))
        except (KeyError, ParseError):
            continue
        if road_id in wanted:
            selected.append(feature)
    return selected


def _first_present(props: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in props and props[name] not in (None, ""):
            return props[name]
    raise KeyError(f"missing field: {'/'.join(names)}")
