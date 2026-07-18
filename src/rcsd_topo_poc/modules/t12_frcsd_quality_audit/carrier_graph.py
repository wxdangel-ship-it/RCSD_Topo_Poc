from __future__ import annotations

import ast
import heapq
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import (
    NodeCanonicalizer,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.parsing import (
    ParseError,
    normalize_id as t06_normalize_id,
)

from .models import AuditConfig, PathResult, T12ContractError


@dataclass(frozen=True)
class GraphEdge:
    road_id: str
    raw_start: str
    raw_end: str
    start: str
    end: str
    direction: int
    source: str
    length_m: float
    geometry: Any


@dataclass(frozen=True)
class GraphBundle:
    directed: dict[str, tuple[tuple[str, str, float], ...]]
    incoming: dict[str, tuple[tuple[str, str, float], ...]]
    undirected: dict[str, tuple[tuple[str, str, float], ...]]
    edges: dict[str, GraphEdge]

    @property
    def outgoing_nodes(self) -> frozenset[str]:
        return frozenset(self.directed)

    @property
    def incoming_nodes(self) -> frozenset[str]:
        return frozenset(self.incoming)


def normalize_id(value: Any) -> str:
    if value is None:
        return ""
    try:
        if bool(pd.isna(value)):
            return ""
    except (TypeError, ValueError):
        pass
    try:
        return t06_normalize_id(value)
    except ParseError:
        text = str(value).strip()
        if text.endswith(".0") and text[:-2].lstrip("-").isdigit():
            return text[:-2]
        return text


def parse_ids(value: Any) -> list[str]:
    if value is None:
        return []
    try:
        if bool(pd.isna(value)):
            return []
    except (TypeError, ValueError):
        pass
    if isinstance(value, (list, tuple, set)):
        return _unique(normalize_id(item) for item in value)
    text = str(value).strip()
    if not text:
        return []
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        parsed = text.replace("|", ",").split(",")
    if isinstance(parsed, (list, tuple, set)):
        return _unique(normalize_id(item) for item in parsed)
    return _unique([normalize_id(parsed)])


def field_name(frame: pd.DataFrame, *names: str) -> str:
    by_lower = {str(column).lower(): str(column) for column in frame.columns}
    for name in names:
        resolved = by_lower.get(name.lower())
        if resolved:
            return resolved
    raise T12ContractError(f"missing field {names}: {list(frame.columns)}")


def build_node_context(
    nodes: gpd.GeoDataFrame,
) -> tuple[NodeCanonicalizer, dict[str, tuple[str, ...]], dict[str, Any]]:
    node_id_field = field_name(nodes, "id")
    features: list[dict[str, Any]] = []
    raw_points: dict[str, Any] = {}
    for _, row in nodes.iterrows():
        properties = {
            str(column): row[column]
            for column in nodes.columns
            if str(column) != str(nodes.geometry.name)
        }
        properties.update(
            {
                str(column).lower(): row[column]
                for column in nodes.columns
                if str(column) != str(nodes.geometry.name)
            }
        )
        geometry = row.geometry
        features.append({"properties": properties, "geometry": geometry})
        raw_id = normalize_id(row[node_id_field])
        if raw_id and geometry is not None and not geometry.is_empty:
            raw_points[raw_id] = geometry
    canonicalizer = NodeCanonicalizer.from_node_features(features)
    groups: defaultdict[str, set[str]] = defaultdict(set)
    for raw_id in raw_points:
        groups[canonicalizer.canonicalize(raw_id)].add(raw_id)
    for raw_id, canonical_id in canonicalizer.aliases.items():
        groups[canonical_id].add(raw_id)
    return (
        canonicalizer,
        {key: tuple(sorted(values)) for key, values in groups.items()},
        raw_points,
    )


def build_graph(
    roads: gpd.GeoDataFrame,
    canonicalizer: NodeCanonicalizer,
) -> GraphBundle:
    road_id_field = field_name(roads, "id")
    start_field = field_name(roads, "snodeid")
    end_field = field_name(roads, "enodeid")
    direction_field = field_name(roads, "direction")
    source_field = _optional_field(roads, "source")
    directed: defaultdict[str, list[tuple[str, str, float]]] = defaultdict(list)
    incoming: defaultdict[str, list[tuple[str, str, float]]] = defaultdict(list)
    undirected: defaultdict[str, list[tuple[str, str, float]]] = defaultdict(list)
    edges: dict[str, GraphEdge] = {}
    for _, row in roads.iterrows():
        road_id = normalize_id(row[road_id_field])
        raw_start = normalize_id(row[start_field])
        raw_end = normalize_id(row[end_field])
        if not road_id or not raw_start or not raw_end:
            continue
        start = canonicalizer.canonicalize(raw_start)
        end = canonicalizer.canonicalize(raw_end)
        try:
            direction = int(float(row[direction_field]))
        except (TypeError, ValueError):
            direction = -1
        geometry = row.geometry
        length_m = float(geometry.length) if geometry is not None else math.inf
        edge = GraphEdge(
            road_id=road_id,
            raw_start=raw_start,
            raw_end=raw_end,
            start=start,
            end=end,
            direction=direction,
            source=normalize_id(row[source_field]) if source_field else "",
            length_m=length_m,
            geometry=geometry,
        )
        edges[road_id] = edge
        undirected[start].append((end, road_id, length_m))
        undirected[end].append((start, road_id, length_m))
        if direction in {0, 1, 2}:
            directed[start].append((end, road_id, length_m))
            incoming[end].append((start, road_id, length_m))
        if direction in {0, 1, 3}:
            directed[end].append((start, road_id, length_m))
            incoming[start].append((end, road_id, length_m))
    return GraphBundle(
        directed=_freeze_adjacency(directed),
        incoming=_freeze_adjacency(incoming),
        undirected=_freeze_adjacency(undirected),
        edges=edges,
    )


def shortest_path_between_sets(
    adjacency: Mapping[str, Iterable[tuple[str, str, float]]],
    starts: Iterable[str],
    targets: Iterable[str],
) -> PathResult | None:
    target_set = set(targets)
    shared = sorted(set(starts) & target_set)
    if shared:
        node_id = shared[0]
        return PathResult(
            start=node_id,
            end=node_id,
            node_ids=(node_id,),
            road_ids=(),
            length_m=0.0,
        )
    queue: list[tuple[float, str, str]] = []
    distance: dict[str, float] = {}
    previous: dict[str, tuple[str, str] | None] = {}
    origin: dict[str, str] = {}
    for start in sorted(set(starts)):
        distance[start] = 0.0
        previous[start] = None
        origin[start] = start
        heapq.heappush(queue, (0.0, start, start))
    selected = ""
    while queue:
        cost, _, node = heapq.heappop(queue)
        if not math.isclose(cost, distance.get(node, math.inf)):
            continue
        if node in target_set and cost > 0:
            selected = node
            break
        for neighbor, road_id, edge_length in adjacency.get(node, ()):
            candidate = cost + edge_length
            current = distance.get(neighbor, math.inf)
            if candidate > current or math.isclose(candidate, current):
                continue
            distance[neighbor] = candidate
            previous[neighbor] = (node, road_id)
            origin[neighbor] = origin[node]
            heapq.heappush(queue, (candidate, neighbor, neighbor))
    if not selected:
        return None
    nodes: list[str] = []
    roads: list[str] = []
    current_node = selected
    while True:
        nodes.append(current_node)
        step = previous[current_node]
        if step is None:
            break
        current_node, road_id = step
        roads.append(road_id)
    return PathResult(
        start=origin[selected],
        end=selected,
        node_ids=tuple(reversed(nodes)),
        road_ids=tuple(reversed(roads)),
        length_m=float(distance[selected]),
    )


def path_metrics(
    path: PathResult | None,
    edges: Mapping[str, GraphEdge],
    reference_geometry: Any,
    reference_length_m: float,
    config: AuditConfig,
) -> dict[str, Any]:
    if path is None:
        return {
            "exists": False,
            "road_ids": [],
            "length_m": None,
            "length_ratio": None,
            "max_corridor_distance_m": None,
            "accepted_equivalent_carrier": False,
        }
    max_distance = max(
        (
            _sample_max_distance(
                edges[road_id].geometry,
                reference_geometry,
                config.sample_spacing_m,
            )
            for road_id in path.road_ids
        ),
        default=0.0,
    )
    ratio = path.length_m / reference_length_m if reference_length_m > 0 else math.inf
    accepted = (
        ratio <= config.path_max_length_ratio
        and path.length_m - reference_length_m <= config.path_max_additive_m
        and max_distance <= config.path_max_corridor_distance_m
    )
    return {
        "exists": True,
        "start_portal": path.start,
        "end_portal": path.end,
        "road_ids": list(path.road_ids),
        "length_m": path.length_m,
        "length_ratio": ratio,
        "max_corridor_distance_m": max_distance,
        "accepted_equivalent_carrier": bool(accepted),
    }


def required_swsd_directions(
    segment_roads: gpd.GeoDataFrame,
    pair_nodes: list[str],
    swsd_canonicalizer: NodeCanonicalizer,
) -> list[str]:
    graph = build_graph(segment_roads, swsd_canonicalizer)
    pair = [swsd_canonicalizer.canonicalize(node_id) for node_id in pair_nodes]
    result: list[str] = []
    if shortest_path_between_sets(graph.directed, [pair[0]], [pair[1]]) is not None:
        result.append("pair0_to_pair1")
    if shortest_path_between_sets(graph.directed, [pair[1]], [pair[0]]) is not None:
        result.append("pair1_to_pair0")
    return result


def directional_swsd_carrier(
    direction: str,
    pair_nodes: list[str],
    segment_roads: gpd.GeoDataFrame,
    swsd_canonicalizer: NodeCanonicalizer,
    raw_node_points: Mapping[str, Any],
) -> dict[str, Any]:
    graph = build_graph(segment_roads, swsd_canonicalizer)
    source_index, target_index = (0, 1) if direction == "pair0_to_pair1" else (1, 0)
    source = swsd_canonicalizer.canonicalize(pair_nodes[source_index])
    target = swsd_canonicalizer.canonicalize(pair_nodes[target_index])
    path = shortest_path_between_sets(graph.directed, [source], [target])
    if path is None:
        raise T12ContractError(f"SWSD direction path missing: {direction} {pair_nodes}")
    first = graph.edges[path.road_ids[0]]
    last = graph.edges[path.road_ids[-1]]
    source_raw = _raw_endpoint(first, path.node_ids[0], swsd_canonicalizer)
    target_raw = _raw_endpoint(last, path.node_ids[-1], swsd_canonicalizer)
    if source_raw not in raw_node_points or target_raw not in raw_node_points:
        raise T12ContractError(
            f"SWSD carrier portal node geometry missing: {source_raw}, {target_raw}"
        )
    return {
        "direction": direction,
        "source_pair_id": pair_nodes[source_index],
        "target_pair_id": pair_nodes[target_index],
        "source_swsd_portal": source_raw,
        "target_swsd_portal": target_raw,
        "source_point": raw_node_points[source_raw],
        "target_point": raw_node_points[target_raw],
        "road_ids": list(path.road_ids),
        "length_m": path.length_m,
    }


def _raw_endpoint(
    edge: GraphEdge,
    canonical_id: str,
    canonicalizer: NodeCanonicalizer,
) -> str:
    if canonicalizer.canonicalize(edge.raw_start) == canonical_id:
        return edge.raw_start
    if canonicalizer.canonicalize(edge.raw_end) == canonical_id:
        return edge.raw_end
    raise T12ContractError(
        f"cannot locate raw portal for {canonical_id} on road {edge.road_id}"
    )


def _sample_max_distance(geometry: Any, reference: Any, spacing_m: float) -> float:
    if geometry is None or geometry.is_empty:
        return math.inf
    length = float(geometry.length)
    count = max(1, int(math.ceil(length / spacing_m)))
    points = [
        Point(geometry.interpolate(length * index / count))
        for index in range(count + 1)
    ]
    return max(float(point.distance(reference)) for point in points)


def _freeze_adjacency(
    adjacency: Mapping[str, list[tuple[str, str, float]]],
) -> dict[str, tuple[tuple[str, str, float], ...]]:
    return {
        node: tuple(sorted(values, key=lambda item: (item[0], item[1], item[2])))
        for node, values in adjacency.items()
    }


def _optional_field(frame: pd.DataFrame, name: str) -> str:
    try:
        return field_name(frame, name)
    except T12ContractError:
        return ""


def _unique(values: Iterable[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))
