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
    allowed_endpoint_nodes: set[str],
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
    unexpected_endpoint_nodes = _unexpected_endpoint_nodes(
        retained_edges,
        pair_nodes,
        allowed_endpoint_nodes=set(allowed_endpoint_nodes),
    )
    if unexpected_endpoint_nodes:
        return False, "unexpected_retained_endpoint_nodes", unexpected_endpoint_nodes
    return True, "passed", []


def _retained_buffer_overlap_issues(
    edges: list[Edge],
    buffer_geometry: BaseGeometry,
    min_overlap_ratio: float,
) -> tuple[list[str], float | None]:
    if buffer_geometry is None or buffer_geometry.is_empty:
        return [], None
    low_road_ids: list[str] = []
    seen: set[str] = set()
    ratios: list[float] = []
    for edge in edges:
        geometry = edge.geometry
        overlap_length = 0.0
        if geometry is None or geometry.is_empty:
            ratio = 0.0
        else:
            length = float(geometry.length)
            if length <= 0:
                continue
            overlap_length = float(geometry.intersection(buffer_geometry).length) if geometry.intersects(buffer_geometry) else 0.0
            ratio = overlap_length / length
        ratios.append(ratio)
        if overlap_length > 1e-9 or edge.road_id in seen:
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


def _unexpected_endpoint_nodes(edges: list[Edge], pair_nodes: list[str], *, allowed_endpoint_nodes: set[str] | None = None) -> list[str]:
    pair_node_set = set(pair_nodes)
    allowed = allowed_endpoint_nodes or set()
    adjacency = _adjacency_from_edges(edges)
    return sorted(node for node, neighbors in adjacency.items() if len(neighbors) <= 1 and node not in pair_node_set and node not in allowed)


def _leaf_nodes(edges: list[Edge]) -> set[str]:
    adjacency = _adjacency_from_edges(edges)
    return {node for node, neighbors in adjacency.items() if len(neighbors) <= 1}


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


def _ordered_required_rcsd_nodes(
    pair_nodes: list[str],
    junc_nodes: list[str],
    *,
    directed_nodes: list[str],
    require_directed_pair: bool,
) -> list[str]:
    if len(pair_nodes) != 2:
        return _unique_ids([*pair_nodes, *junc_nodes])
    if require_directed_pair and len(directed_nodes) == 2:
        if directed_nodes[0] == pair_nodes[1] and directed_nodes[1] == pair_nodes[0]:
            return _unique_ids([directed_nodes[0], *reversed(junc_nodes), directed_nodes[1]])
        return _unique_ids([directed_nodes[0], *junc_nodes, directed_nodes[1]])
    return _unique_ids([pair_nodes[0], *junc_nodes, pair_nodes[1]])


def _ordered_anchor_pairs(ordered_nodes: list[str]) -> set[frozenset[str]]:
    return {frozenset((source, target)) for source, target in zip(ordered_nodes, ordered_nodes[1:])}


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


def _mismatch_exceeds_threshold(
    mismatch_length: float,
    mismatch_ratio: float,
    *,
    max_mismatch_ratio: float,
    min_mismatch_length_m: float,
) -> bool:
    return mismatch_ratio > max_mismatch_ratio or mismatch_length > min_mismatch_length_m
