from __future__ import annotations

import heapq
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from .buffer_only_probe import BufferOnlyProbeResult
from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, normalize_id
from .relation_mapping import RelationCheck

MAX_ENDPOINT_CLUSTER_BRIDGE_M = 30.0


@dataclass(frozen=True)
class PairAnchorIssueDiagnostic:
    original_rcsd_pair_nodes: list[str]
    candidate_rcsd_pair_nodes: list[str]
    candidate_score: float
    error_swsd_pair_nodes: list[str]
    error_original_rcsd_nodes: list[str]
    error_candidate_rcsd_nodes: list[str]
    endpoint_cluster_nodes: list[list[str]]
    endpoint_bridge_road_ids: list[str]
    endpoint_bridge_length_m: float
    diagnostic_source: str
    diagnostic_reason: str


def build_pair_anchor_issue_diagnostic(
    *,
    probe_result: BufferOnlyProbeResult,
    relation: RelationCheck,
    failure_business_category: str,
    pair_nodes: list[str],
    rcsd_road_features: list[dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
    max_endpoint_bridge_m: float = MAX_ENDPOINT_CLUSTER_BRIDGE_M,
) -> PairAnchorIssueDiagnostic | None:
    if failure_business_category not in {"pair_anchor_mismatch", "multi_anchor_ambiguous"}:
        return None

    candidate_pairs = _valid_candidate_pairs(probe_result.candidate_pair_sets)
    if not candidate_pairs:
        return None
    candidate_pair = candidate_pairs[0]
    if len(candidate_pair) != 2 or len(set(candidate_pair)) != 2:
        return None

    graph = _road_graph(
        rcsd_road_features,
        candidate_road_ids=set(str(item) for item in probe_result.candidate_road_ids),
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    )
    original_by_side = _original_pair_nodes_by_side(relation.rcsd_pair_nodes, pair_nodes, relation.failed_pair_nodes or [])
    cluster_nodes, bridge_road_ids, bridge_length_m, cluster_ok = _endpoint_clusters(
        candidate_pairs=candidate_pairs,
        original_rcsd_pair_nodes_by_side=original_by_side,
        graph=graph,
        max_endpoint_bridge_m=max_endpoint_bridge_m,
    )
    error_swsd_nodes, error_original_nodes, error_candidate_nodes = _error_positions(
        pair_nodes=pair_nodes,
        original_by_side=original_by_side,
        candidate_pair=candidate_pair,
    )
    if cluster_ok:
        source = "buffer_only_endpoint_cluster"
        reason = "short_connected_endpoint_cluster"
    elif failure_business_category == "multi_anchor_ambiguous":
        source = "buffer_only_ambiguous_candidate_pair"
        reason = "multi_anchor_ambiguous"
    else:
        source = "buffer_only_candidate_pair"
        reason = "candidate_anchor_mismatch"
    return PairAnchorIssueDiagnostic(
        original_rcsd_pair_nodes=[str(item) for item in relation.rcsd_pair_nodes],
        candidate_rcsd_pair_nodes=candidate_pair,
        candidate_score=probe_result.candidate_score,
        error_swsd_pair_nodes=error_swsd_nodes,
        error_original_rcsd_nodes=error_original_nodes,
        error_candidate_rcsd_nodes=error_candidate_nodes,
        endpoint_cluster_nodes=cluster_nodes,
        endpoint_bridge_road_ids=_unique(bridge_road_ids),
        endpoint_bridge_length_m=round(bridge_length_m, 3),
        diagnostic_source=source,
        diagnostic_reason=reason,
    )


@dataclass(frozen=True)
class _RoadGraph:
    adjacency: dict[str, list[tuple[str, float, str]]]


def _valid_candidate_pairs(values: list[list[str]]) -> list[list[str]]:
    result: list[list[str]] = []
    seen: set[tuple[str, str]] = set()
    for value in values:
        pair = [str(item) for item in value]
        if len(pair) != 2 or len(set(pair)) != 2:
            continue
        key = (pair[0], pair[1])
        if key in seen:
            continue
        seen.add(key)
        result.append(pair)
    return result


def _road_graph(
    features: list[dict[str, Any]],
    *,
    candidate_road_ids: set[str],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> _RoadGraph:
    adjacency: dict[str, list[tuple[str, float, str]]] = defaultdict(list)
    for feature in features:
        props = dict(feature.get("properties") or {})
        try:
            road_id = normalize_id(_first_present(props, ["id", "road_id", "roadid"]))
            if candidate_road_ids and road_id not in candidate_road_ids:
                continue
            source = rcsd_node_canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
            target = rcsd_node_canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
        except (KeyError, ParseError):
            continue
        if source == target:
            continue
        geometry = feature.get("geometry")
        length = float(getattr(geometry, "length", 0.0) or 0.0) if geometry is not None else 0.0
        weight = max(length, 0.001)
        adjacency[source].append((target, weight, road_id))
        adjacency[target].append((source, weight, road_id))
    return _RoadGraph(adjacency=dict(adjacency))


def _original_pair_nodes_by_side(
    original_rcsd_pair_nodes: list[str],
    pair_nodes: list[str],
    failed_pair_nodes: list[str],
) -> list[str | None]:
    if len(original_rcsd_pair_nodes) == 2:
        return [str(original_rcsd_pair_nodes[0]), str(original_rcsd_pair_nodes[1])]
    if len(original_rcsd_pair_nodes) != 1 or len(pair_nodes) != 2:
        return [None, None]
    failed = set(str(item) for item in failed_pair_nodes)
    if str(pair_nodes[0]) in failed and str(pair_nodes[1]) not in failed:
        return [None, str(original_rcsd_pair_nodes[0])]
    return [str(original_rcsd_pair_nodes[0]), None]


def _endpoint_clusters(
    *,
    candidate_pairs: list[list[str]],
    original_rcsd_pair_nodes_by_side: list[str | None],
    graph: _RoadGraph,
    max_endpoint_bridge_m: float,
) -> tuple[list[list[str]], list[str], float, bool]:
    bridge_ids: list[str] = []
    bridge_length = 0.0
    clusters: list[list[str]] = []
    cluster_ok = False
    for side in (0, 1):
        representative = candidate_pairs[0][side]
        side_nodes = _unique(pair[side] for pair in candidate_pairs if len(pair) == 2)
        original_node = original_rcsd_pair_nodes_by_side[side] if side < len(original_rcsd_pair_nodes_by_side) else None
        if original_node and original_node not in side_nodes:
            side_nodes.append(original_node)
        accepted = [representative]
        for node in side_nodes:
            if node == representative:
                continue
            path = _short_bridge_path(graph, representative, node, max_endpoint_bridge_m)
            if path is None:
                continue
            path_ids, path_length = path
            accepted.append(node)
            bridge_ids.extend(path_ids)
            bridge_length += path_length
            cluster_ok = True
        clusters.append(_unique(accepted))
    if len(clusters) == 2 and set(clusters[0]) & set(clusters[1]):
        return clusters, _unique(bridge_ids), bridge_length, False
    return clusters, _unique(bridge_ids), bridge_length, cluster_ok


def _error_positions(
    *,
    pair_nodes: list[str],
    original_by_side: list[str | None],
    candidate_pair: list[str],
) -> tuple[list[str], list[str], list[str]]:
    error_swsd_nodes: list[str] = []
    error_original_nodes: list[str] = []
    error_candidate_nodes: list[str] = []
    for index, candidate_node in enumerate(candidate_pair):
        swsd_node = str(pair_nodes[index]) if index < len(pair_nodes) else f"pair_{index}"
        original_node = original_by_side[index] if index < len(original_by_side) else None
        if original_node == candidate_node:
            continue
        error_swsd_nodes.append(swsd_node)
        error_original_nodes.append(str(original_node) if original_node else "")
        error_candidate_nodes.append(candidate_node)
    return error_swsd_nodes, error_original_nodes, error_candidate_nodes


def _short_bridge_path(graph: _RoadGraph, source: str, target: str, max_length: float) -> tuple[list[str], float] | None:
    if source == target:
        return [], 0.0
    queue: list[tuple[float, int, str]] = []
    sequence = 0
    heapq.heappush(queue, (0.0, sequence, source))
    distances: dict[str, float] = {source: 0.0}
    previous: dict[str, tuple[str, str]] = {}
    while queue:
        distance, _seq, node = heapq.heappop(queue)
        if distance > max_length:
            continue
        if node == target:
            break
        if distance > distances.get(node, float("inf")):
            continue
        for neighbor, weight, road_id in graph.adjacency.get(node, []):
            next_distance = distance + weight
            if next_distance > max_length or next_distance >= distances.get(neighbor, float("inf")):
                continue
            distances[neighbor] = next_distance
            previous[neighbor] = (node, road_id)
            sequence += 1
            heapq.heappush(queue, (next_distance, sequence, neighbor))
    if target not in distances:
        return None
    road_ids: list[str] = []
    node = target
    while node != source:
        prev = previous.get(node)
        if prev is None:
            return None
        node, road_id = prev
        road_ids.append(road_id)
    road_ids.reverse()
    return road_ids, distances[target]


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
