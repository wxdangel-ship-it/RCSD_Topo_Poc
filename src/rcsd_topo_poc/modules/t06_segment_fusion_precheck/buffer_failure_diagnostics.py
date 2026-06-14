from __future__ import annotations

from collections import defaultdict, deque
from typing import Any

from .buffer_segment_extraction import BufferExtractionConfig, BufferSegmentResult
from .graph_builders import NodeCanonicalizer
from .parsing import ParseError


def buffer_failure_diagnostic(
    *,
    result: BufferSegmentResult,
    directionality: str,
    rcsd_pair_nodes: list[str],
    rcsd_graph_edges: list[tuple[str, str, str, int | None]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> dict[str, Any]:
    required_nodes = canonical_rcsd_ids(result.required_rcsd_nodes, rcsd_node_canonicalizer)
    pair_nodes = canonical_rcsd_ids(rcsd_pair_nodes, rcsd_node_canonicalizer)
    directed_pair_nodes = canonical_rcsd_ids(result.directed_rcsd_pair_nodes, rcsd_node_canonicalizer)
    candidate_road_ids = set(result.candidate_road_ids)
    full_nodes, full_undirected, full_directed = _graph_views(rcsd_graph_edges)
    candidate_nodes, candidate_undirected, candidate_directed = _graph_views(rcsd_graph_edges, road_ids=candidate_road_ids)
    full_graph_status = _required_graph_status(required_nodes, full_nodes, full_undirected)
    candidate_graph_status = _required_graph_status(required_nodes, candidate_nodes, candidate_undirected)
    full_direction_status = _direction_status(
        directionality,
        full_directed,
        pair_nodes=pair_nodes,
        directed_pair_nodes=directed_pair_nodes,
    )
    candidate_direction_status = _direction_status(
        directionality,
        candidate_directed,
        pair_nodes=pair_nodes,
        directed_pair_nodes=directed_pair_nodes,
    )
    root_cause = _root_cause_category(
        result.reason,
        directionality=directionality,
        full_graph_status=full_graph_status,
        candidate_graph_status=candidate_graph_status,
        full_direction_status=full_direction_status,
        candidate_direction_status=candidate_direction_status,
    )
    return {
        "root_cause_category": root_cause,
        "full_graph_status": full_graph_status,
        "candidate_graph_status": candidate_graph_status,
        "directional_status": f"full={full_direction_status};candidate={candidate_direction_status}",
        "diagnostic_notes": _diagnostic_notes(root_cause),
    }


def canonical_rcsd_ids(values: list[str], canonicalizer: NodeCanonicalizer) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        try:
            node_id = canonicalizer.canonicalize(value)
        except ParseError:
            node_id = str(value)
        if node_id in seen:
            continue
        seen.add(node_id)
        result.append(node_id)
    return result


def buffer_failed_metric_name(result: BufferSegmentResult) -> str | None:
    if result.low_buffer_overlap_road_ids:
        return "retained_road_buffer_overlap_ratio"
    if result.geometry_buffer_coverage_issue:
        return "geometry_buffer_coverage"
    if result.unexpected_mapped_semantic_node_ids:
        return "unexpected_mapped_semantic_node_ids"
    if result.unexpected_endpoint_node_ids:
        return "unexpected_endpoint_node_ids"
    if result.reason in {"rcsd_not_bidirectional_for_swsd_dual", "rcsd_directed_path_missing"}:
        return "rcsd_pair_directionality"
    if result.out_node_ids:
        return "out_node_ids"
    if result.inner_node_ids:
        return "inner_node_ids"
    return None


def buffer_failed_metric_value(result: BufferSegmentResult) -> Any:
    if result.low_buffer_overlap_road_ids:
        return {
            "low_buffer_overlap_road_ids": result.low_buffer_overlap_road_ids,
            "min_retained_road_buffer_overlap_ratio": result.min_retained_road_buffer_overlap_ratio,
        }
    if result.geometry_buffer_coverage_issue:
        return {
            "geometry_buffer_coverage_issue": result.geometry_buffer_coverage_issue,
            "rcsd_outside_swsd_buffer_length_m": result.rcsd_outside_swsd_buffer_length_m,
            "rcsd_outside_swsd_buffer_ratio": result.rcsd_outside_swsd_buffer_ratio,
            "swsd_uncovered_by_rcsd_length_m": result.swsd_uncovered_by_rcsd_length_m,
            "swsd_uncovered_by_rcsd_ratio": result.swsd_uncovered_by_rcsd_ratio,
        }
    if result.unexpected_mapped_semantic_node_ids:
        return result.unexpected_mapped_semantic_node_ids
    if result.unexpected_endpoint_node_ids:
        return result.unexpected_endpoint_node_ids
    if result.reason in {"rcsd_not_bidirectional_for_swsd_dual", "rcsd_directed_path_missing"}:
        return result.directed_rcsd_pair_nodes or result.required_rcsd_nodes[:2]
    if result.out_node_ids:
        return result.out_node_ids
    if result.inner_node_ids:
        return result.inner_node_ids
    return None


def buffer_failed_threshold_value(result: BufferSegmentResult, config: BufferExtractionConfig) -> Any:
    if result.reason == "retained_road_buffer_overlap_insufficient":
        return config.min_road_overlap_ratio
    if result.reason in {"retained_geometry_outside_swsd_buffer_scope", "swsd_geometry_not_covered_by_retained_rcsd"}:
        return {
            "max_geometry_buffer_mismatch_ratio": config.max_geometry_buffer_mismatch_ratio,
            "min_geometry_buffer_mismatch_length_m": config.min_geometry_buffer_mismatch_length_m,
        }
    return None


def _graph_views(
    edges: list[tuple[str, str, str, int | None]],
    *,
    road_ids: set[str] | None = None,
) -> tuple[set[str], dict[str, set[str]], dict[str, set[str]]]:
    nodes: set[str] = set()
    undirected: dict[str, set[str]] = defaultdict(set)
    directed: dict[str, set[str]] = defaultdict(set)
    for road_id, source, target, direction in edges:
        if road_ids is not None and road_id not in road_ids:
            continue
        nodes.update([source, target])
        undirected[source].add(target)
        undirected[target].add(source)
        if direction in {0, 1, 2}:
            directed[source].add(target)
        if direction in {0, 1, 3}:
            directed[target].add(source)
    return nodes, dict(undirected), dict(directed)


def _required_graph_status(required_nodes: list[str], graph_nodes: set[str], adjacency: dict[str, set[str]]) -> str:
    missing = [node for node in required_nodes if node not in graph_nodes]
    if missing:
        return "missing_required_nodes"
    if _nodes_connected(adjacency, required_nodes):
        return "required_nodes_connected"
    return "required_nodes_disconnected"


def _direction_status(
    directionality: str,
    adjacency: dict[str, set[str]],
    *,
    pair_nodes: list[str],
    directed_pair_nodes: list[str],
) -> str:
    if directionality == "dual":
        if len(pair_nodes) != 2:
            return "pair_unavailable"
        forward = _directed_reachable(adjacency, pair_nodes[0], pair_nodes[1])
        reverse = _directed_reachable(adjacency, pair_nodes[1], pair_nodes[0])
        return _direction_pair_status(forward, reverse)
    if directionality == "single":
        effective = directed_pair_nodes if len(directed_pair_nodes) == 2 else pair_nodes
        if len(effective) != 2:
            return "directed_pair_unavailable"
        return "directed_path_present" if _directed_reachable(adjacency, effective[0], effective[1]) else "directed_path_missing"
    return "not_checked"


def _direction_pair_status(forward: bool, reverse: bool) -> str:
    if forward and reverse:
        return "bidirectional"
    if forward:
        return "forward_only"
    if reverse:
        return "reverse_only"
    return "no_directed_pair_path"


def _root_cause_category(
    reason: str,
    *,
    directionality: str,
    full_graph_status: str,
    candidate_graph_status: str,
    full_direction_status: str,
    candidate_direction_status: str,
) -> str:
    if reason in {"required_semantic_nodes_missing_from_buffer_graph", "required_semantic_nodes_not_connected_in_buffer"}:
        if full_graph_status == "missing_required_nodes":
            return "full_rcsd_graph_missing_required_nodes"
        if full_graph_status == "required_nodes_disconnected":
            return "full_rcsd_graph_required_nodes_disconnected"
        if candidate_graph_status == "missing_required_nodes":
            return "buffer_candidate_missing_required_nodes"
        if candidate_graph_status == "required_nodes_disconnected":
            return "buffer_candidate_required_nodes_disconnected"
        return "candidate_connected_but_pruned_by_hard_rules"
    if reason == "rcsd_not_bidirectional_for_swsd_dual":
        if directionality != "dual":
            return "directionality_rule_mismatch"
        if full_direction_status == "bidirectional" and candidate_direction_status != "bidirectional":
            return "buffer_candidate_missing_bidirectional_corridor"
        if full_direction_status in {"forward_only", "reverse_only"}:
            return "full_rcsd_graph_one_direction_only"
        if full_direction_status == "no_directed_pair_path":
            return "full_rcsd_graph_no_directed_pair_path"
        return "candidate_bidirectional_but_pruned_by_hard_rules"
    if reason == "rcsd_directed_path_missing":
        if directionality == "single":
            if full_direction_status == "directed_path_present" and candidate_direction_status != "directed_path_present":
                return "buffer_candidate_missing_directed_corridor"
            if full_direction_status == "directed_path_missing":
                return "full_rcsd_graph_missing_directed_path"
            return "candidate_directed_path_pruned_by_hard_rules"
        return "directed_pair_unavailable_or_degenerate"
    if reason == "buffer_pruned_to_empty":
        return "candidate_pruned_to_empty_by_hard_rules"
    if reason == "retained_road_buffer_overlap_insufficient":
        return "retained_road_outside_buffer_scope"
    if reason in {"retained_geometry_outside_swsd_buffer_scope", "swsd_geometry_not_covered_by_retained_rcsd"}:
        return "retained_geometry_buffer_coverage_mismatch"
    return "buffer_extraction_rule_rejected"


def _diagnostic_notes(root_cause_category: str) -> str:
    notes = {
        "full_rcsd_graph_missing_required_nodes": "required semantic nodes have no incident RCSDRoad in the full RCSD graph",
        "full_rcsd_graph_required_nodes_disconnected": "required semantic nodes are disconnected in the full RCSD graph",
        "buffer_candidate_missing_required_nodes": "required semantic nodes exist in the full graph but are missing from the 50m buffer candidate graph",
        "buffer_candidate_required_nodes_disconnected": "required semantic nodes exist in the 50m buffer graph but are not connected inside the candidate graph",
        "buffer_candidate_missing_bidirectional_corridor": "full RCSD graph is bidirectional, but the 50m buffer candidate graph misses at least one direction corridor",
        "full_rcsd_graph_one_direction_only": "dual SWSD Segment requires bidirectional RCSD, but the full RCSD graph has only one directed path",
        "full_rcsd_graph_no_directed_pair_path": "dual SWSD Segment requires bidirectional RCSD, but the full RCSD graph has no directed pair path",
        "buffer_candidate_missing_directed_corridor": "full RCSD graph has the directed path, but the 50m buffer candidate graph misses it",
        "full_rcsd_graph_missing_directed_path": "single SWSD Segment requires the inferred direction, but the full RCSD graph does not have that directed path",
        "candidate_pruned_to_empty_by_hard_rules": "candidate RCSD graph was removed by hard pruning rules",
        "candidate_connected_but_pruned_by_hard_rules": "candidate RCSD graph is connected before pruning but fails retained-graph hard rules",
        "candidate_bidirectional_but_pruned_by_hard_rules": "candidate RCSD graph is bidirectional before pruning but fails retained-graph hard rules",
        "candidate_directed_path_pruned_by_hard_rules": "candidate RCSD graph has the directed path before pruning but fails retained-graph hard rules",
        "retained_road_outside_buffer_scope": "retained RCSDRoad geometry has insufficient overlap with the SWSD Segment buffer",
        "retained_geometry_buffer_coverage_mismatch": "retained RCSD geometry and SWSD Segment geometry are not mutually covered by the configured buffer scope",
    }
    return notes.get(root_cause_category, "buffer-based RCSD Segment construction failed")


def _nodes_connected(adjacency: dict[str, set[str]], nodes: list[str]) -> bool:
    if not nodes:
        return True
    source = nodes[0]
    seen = {source}
    queue: deque[str] = deque([source])
    while queue:
        current = queue.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append(neighbor)
    return set(nodes).issubset(seen)


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
