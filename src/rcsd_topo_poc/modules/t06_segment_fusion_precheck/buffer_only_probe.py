from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .buffer_segment_extraction import BufferExtractionConfig
from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, normalize_id


@dataclass(frozen=True)
class BufferOnlyProbeResult:
    status: str
    candidate_pair_sets: list[list[str]]
    candidate_score: float
    geometry_overlap_ratio: float
    directionality_score: float
    connectivity_score: float
    shape_similarity_score: float
    candidate_road_ids: list[str]
    candidate_node_ids: list[str]
    candidate_component_count: int
    manual_review_required: bool
    repair_recommendation: str
    geometry: BaseGeometry | None
    notes: str


class BufferOnlyProbe:
    def __init__(self, *, rcsd_road_features: list[dict[str, Any]], rcsd_node_features: list[dict[str, Any]]) -> None:
        self.road_features = rcsd_road_features
        self.node_features = rcsd_node_features
        self.node_canonicalizer = NodeCanonicalizer.from_node_features(rcsd_node_features)
        self.node_points = _node_points(rcsd_node_features, self.node_canonicalizer)
        geometries: list[BaseGeometry] = []
        features: list[dict[str, Any]] = []
        for feature in rcsd_road_features:
            geometry = feature.get("geometry")
            if isinstance(geometry, BaseGeometry) and not geometry.is_empty:
                geometries.append(geometry)
                features.append(feature)
        self._road_geometries = geometries
        self._road_features = features
        self._road_tree = STRtree(geometries) if geometries else None

    def probe(
        self,
        *,
        segment_geometry: BaseGeometry | None,
        original_rcsd_pair_nodes: list[str],
        directionality: str,
        config: BufferExtractionConfig,
    ) -> BufferOnlyProbeResult:
        if segment_geometry is None or segment_geometry.is_empty:
            return _empty_probe("no_corridor", "missing_swsd_geometry")

        buffer_geometry = segment_geometry.buffer(config.buffer_distance_m)
        candidate_roads = self._candidate_roads(buffer_geometry, config)
        if not candidate_roads:
            return _empty_probe("no_corridor", "no RCSDRoad intersects the SWSD Segment buffer")

        edges = _road_edges(candidate_roads, self.node_canonicalizer)
        if not edges:
            return _empty_probe("corridor_found_with_topology_issue", "candidate RCSDRoad endpoints cannot form a semantic graph")

        components = _components(edges)
        scored = [
            _score_component(
                component_nodes=nodes,
                edges=edges,
                segment_geometry=segment_geometry,
                buffer_geometry=buffer_geometry,
                node_points=self.node_points,
                directionality=directionality,
                buffer_distance_m=config.buffer_distance_m,
            )
            for nodes in components
        ]
        scored = [item for item in scored if item["candidate_score"] > 0]
        if not scored:
            return _empty_probe("no_corridor", "candidate RCSDRoad geometry has no usable shape overlap")

        scored.sort(key=lambda item: item["candidate_score"], reverse=True)
        best = scored[0]
        second_score = float(scored[1]["candidate_score"]) if len(scored) > 1 else 0.0
        ambiguous = len(scored) > 1 and second_score >= float(best["candidate_score"]) - 0.08
        original_pair = _canonical_ids(original_rcsd_pair_nodes, self.node_canonicalizer)
        anchor_mismatch = len(original_pair) == 2 and set(original_pair) != set(best["candidate_pair"])
        fragmented = len(components) > 1 and _fragmented_shape_score(scored) > float(best["shape_similarity_score"]) + 0.2

        if ambiguous:
            status = "ambiguous_corridor"
        elif anchor_mismatch:
            status = "corridor_found_with_anchor_mismatch"
        elif fragmented:
            status = "corridor_found_with_topology_issue"
        else:
            status = "corridor_found"

        score = round(float(best["candidate_score"]), 4)
        manual_review_required = ambiguous or score < 0.85
        if status == "no_corridor":
            recommendation = "no_t06_repair"
        elif manual_review_required:
            recommendation = "manual_review_required"
        else:
            recommendation = "high_confidence_pair_anchor_candidate"

        pair_sets = [item["candidate_pair"] for item in scored[:3] if item["candidate_pair"]]
        return BufferOnlyProbeResult(
            status=status,
            candidate_pair_sets=pair_sets,
            candidate_score=score,
            geometry_overlap_ratio=round(float(best["geometry_overlap_ratio"]), 4),
            directionality_score=round(float(best["directionality_score"]), 4),
            connectivity_score=round(float(best["connectivity_score"]), 4),
            shape_similarity_score=round(float(best["shape_similarity_score"]), 4),
            candidate_road_ids=best["road_ids"],
            candidate_node_ids=best["node_ids"],
            candidate_component_count=len(components),
            manual_review_required=manual_review_required,
            repair_recommendation=recommendation,
            geometry=best["geometry"],
            notes="buffer-only probe is diagnostic only and does not overwrite T05 relation",
        )

    def _candidate_roads(self, buffer_geometry: BaseGeometry, config: BufferExtractionConfig) -> list[dict[str, Any]]:
        if self._road_tree is None:
            return []
        selected: list[dict[str, Any]] = []
        for index in self._road_tree.query(buffer_geometry):
            feature = self._road_features[int(index)]
            geometry = feature.get("geometry")
            if not isinstance(geometry, BaseGeometry) or geometry.is_empty or not geometry.intersects(buffer_geometry):
                continue
            length = float(geometry.length)
            overlap_length = float(geometry.intersection(buffer_geometry).length)
            ratio = overlap_length / length if length > 0 else 0.0
            if ratio >= config.min_road_overlap_ratio or overlap_length >= config.min_road_overlap_length_m:
                selected.append(feature)
        return selected


@dataclass(frozen=True)
class _ProbeEdge:
    road_id: str
    source: str
    target: str
    direction: int | None
    geometry: BaseGeometry | None


def _score_component(
    *,
    component_nodes: set[str],
    edges: list[_ProbeEdge],
    segment_geometry: BaseGeometry,
    buffer_geometry: BaseGeometry,
    node_points: dict[str, Point],
    directionality: str,
    buffer_distance_m: float,
) -> dict[str, Any]:
    component_edges = [edge for edge in edges if edge.source in component_nodes and edge.target in component_nodes]
    road_ids = _unique(edge.road_id for edge in component_edges)
    node_ids = sorted(component_nodes)
    geometry = _edge_geometry(component_edges)
    pair = _endpoint_pair(component_nodes, segment_geometry, node_points)
    geometry_overlap_ratio = _geometry_overlap_ratio(geometry, buffer_geometry)
    shape_similarity_score = _shape_similarity_score(segment_geometry, geometry, buffer_distance_m)
    connectivity_score = 1.0 if len(pair) == 2 else 0.25
    directionality_score = _directionality_score(component_edges, pair, directionality)
    candidate_score = (
        geometry_overlap_ratio * 0.35
        + shape_similarity_score * 0.35
        + connectivity_score * 0.2
        + directionality_score * 0.1
    )
    return {
        "candidate_pair": pair,
        "candidate_score": candidate_score,
        "geometry_overlap_ratio": geometry_overlap_ratio,
        "shape_similarity_score": shape_similarity_score,
        "connectivity_score": connectivity_score,
        "directionality_score": directionality_score,
        "road_ids": road_ids,
        "node_ids": node_ids,
        "geometry": geometry,
    }


def _node_points(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> dict[str, Point]:
    result: dict[str, Point] = {}
    for feature in features:
        props = dict(feature.get("properties") or {})
        geometry = feature.get("geometry")
        if not isinstance(geometry, Point):
            continue
        try:
            node_id = canonicalizer.canonicalize(props.get("id"))
        except ParseError:
            continue
        result.setdefault(node_id, geometry)
    return result


def _road_edges(features: list[dict[str, Any]], canonicalizer: NodeCanonicalizer) -> list[_ProbeEdge]:
    edges: list[_ProbeEdge] = []
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            road_id = normalize_id(_first_present(props, ["id", "road_id", "roadid"]))
            source = canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
            target = canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
        except (KeyError, ParseError):
            continue
        if source == target:
            continue
        direction = _coerce_int(props.get("direction"))
        geometry = feature.get("geometry")
        edges.append(_ProbeEdge(road_id, source, target, direction, geometry if isinstance(geometry, BaseGeometry) else None))
    return edges


def _components(edges: list[_ProbeEdge]) -> list[set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        adjacency[edge.source].add(edge.target)
        adjacency[edge.target].add(edge.source)
    components: list[set[str]] = []
    seen: set[str] = set()
    for node in adjacency:
        if node in seen:
            continue
        queue: deque[str] = deque([node])
        seen.add(node)
        component = {node}
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


def _endpoint_pair(component_nodes: set[str], segment_geometry: BaseGeometry, node_points: dict[str, Point]) -> list[str]:
    endpoint_points = _segment_endpoint_points(segment_geometry)
    if len(endpoint_points) != 2:
        return []
    available = [(node, point) for node, point in node_points.items() if node in component_nodes]
    if len(available) < 2:
        return []
    first = min(available, key=lambda item: item[1].distance(endpoint_points[0]))[0]
    second_candidates = [item for item in available if item[0] != first]
    if not second_candidates:
        return []
    second = min(second_candidates, key=lambda item: item[1].distance(endpoint_points[1]))[0]
    return [first, second]


def _segment_endpoint_points(geometry: BaseGeometry) -> list[Point]:
    if isinstance(geometry, LineString):
        coords = list(geometry.coords)
        if len(coords) >= 2:
            return [Point(coords[0]), Point(coords[-1])]
    boundary = geometry.boundary
    if hasattr(boundary, "geoms"):
        points = [item for item in boundary.geoms if isinstance(item, Point)]
        if len(points) >= 2:
            return [points[0], points[-1]]
    centroid = geometry.centroid
    return [centroid, centroid] if isinstance(centroid, Point) else []


def _directionality_score(edges: list[_ProbeEdge], pair: list[str], directionality: str) -> float:
    if len(pair) != 2:
        return 0.0
    adjacency: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        if edge.direction in {0, 1, 2}:
            adjacency[edge.source].add(edge.target)
        if edge.direction in {0, 1, 3}:
            adjacency[edge.target].add(edge.source)
    forward = _reachable(adjacency, pair[0], pair[1])
    reverse = _reachable(adjacency, pair[1], pair[0])
    if directionality == "dual":
        return 1.0 if forward and reverse else 0.5 if forward or reverse else 0.0
    if directionality == "single":
        return 1.0 if forward or reverse else 0.0
    return 0.5 if forward or reverse else 0.0


def _reachable(adjacency: dict[str, set[str]], source: str, target: str) -> bool:
    seen = {source}
    queue: deque[str] = deque([source])
    while queue:
        current = queue.popleft()
        if current == target:
            return True
        for nxt in adjacency.get(current, set()):
            if nxt in seen:
                continue
            seen.add(nxt)
            queue.append(nxt)
    return False


def _geometry_overlap_ratio(geometry: BaseGeometry, buffer_geometry: BaseGeometry) -> float:
    length = float(geometry.length) if not geometry.is_empty else 0.0
    if length <= 0:
        return 0.0
    return min(1.0, float(geometry.intersection(buffer_geometry).length) / length)


def _shape_similarity_score(segment_geometry: BaseGeometry, candidate_geometry: BaseGeometry, buffer_distance_m: float) -> float:
    segment_length = float(segment_geometry.length) if not segment_geometry.is_empty else 0.0
    if segment_length <= 0 or candidate_geometry.is_empty:
        return 0.0
    covered = float(segment_geometry.intersection(candidate_geometry.buffer(buffer_distance_m)).length)
    return min(1.0, covered / segment_length)


def _fragmented_shape_score(scored_components: list[dict[str, Any]]) -> float:
    return min(1.0, sum(float(item["shape_similarity_score"]) for item in scored_components))


def _edge_geometry(edges: list[_ProbeEdge]) -> BaseGeometry:
    geometries = [edge.geometry for edge in edges if edge.geometry is not None and not edge.geometry.is_empty]
    if not geometries:
        return LineString()
    return unary_union(geometries)


def _canonical_ids(values: list[str], canonicalizer: NodeCanonicalizer) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        try:
            canonical = canonicalizer.canonicalize(value)
        except ParseError:
            canonical = str(value)
        if canonical in seen:
            continue
        seen.add(canonical)
        result.append(canonical)
    return result


def _unique(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value)
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _first_present(props: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in props and props.get(name) is not None:
            return props[name]
    raise KeyError(names[0])


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _empty_probe(status: str, notes: str) -> BufferOnlyProbeResult:
    return BufferOnlyProbeResult(
        status=status,
        candidate_pair_sets=[],
        candidate_score=0.0,
        geometry_overlap_ratio=0.0,
        directionality_score=0.0,
        connectivity_score=0.0,
        shape_similarity_score=0.0,
        candidate_road_ids=[],
        candidate_node_ids=[],
        candidate_component_count=0,
        manual_review_required=False,
        repair_recommendation="no_t06_repair",
        geometry=None,
        notes=notes,
    )
