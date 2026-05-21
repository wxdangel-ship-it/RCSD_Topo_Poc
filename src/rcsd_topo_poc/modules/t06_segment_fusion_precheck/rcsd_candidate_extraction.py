from __future__ import annotations

from dataclasses import dataclass

from .graph_builders import DirectedGraph, Edge, PathCandidate


@dataclass(frozen=True)
class RcsdCandidate:
    candidate_id: str
    directionality: str
    path: PathCandidate
    reverse_path: PathCandidate | None
    forward_reachable: bool
    reverse_reachable: bool

    @property
    def all_edges(self) -> list[Edge]:
        edges = list(self.path.edges)
        if self.reverse_path is not None:
            seen = {edge.edge_id for edge in edges}
            edges.extend(edge for edge in self.reverse_path.edges if edge.edge_id not in seen)
        return edges

    @property
    def road_ids(self) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for edge in self.all_edges:
            if edge.road_id not in seen:
                seen.add(edge.road_id)
                result.append(edge.road_id)
        return result


@dataclass(frozen=True)
class ExtractionResult:
    candidates: list[RcsdCandidate]
    reject_reason: str | None = None


def extract_rcsd_candidates(
    *,
    graph: DirectedGraph,
    source_node: str,
    target_node: str,
    swsd_directionality: str,
    max_candidates: int = 3,
) -> ExtractionResult:
    forward_paths = graph.find_paths(source_node, target_node, max_paths=max_candidates)
    reverse_paths = graph.find_paths(target_node, source_node, max_paths=1)
    forward_reachable = bool(forward_paths)
    reverse_reachable = bool(reverse_paths)

    if swsd_directionality == "dual":
        if not forward_reachable and not reverse_reachable:
            return ExtractionResult([], "rcsd_pair_not_connected")
        if not (forward_reachable and reverse_reachable):
            return ExtractionResult([], "rcsd_not_bidirectional_for_swsd_dual")
        reverse_path = reverse_paths[0]
        return ExtractionResult(
            [
                RcsdCandidate(
                    candidate_id=f"rcsd_candidate_{index}",
                    directionality="dual",
                    path=path,
                    reverse_path=reverse_path,
                    forward_reachable=True,
                    reverse_reachable=True,
                )
                for index, path in enumerate(forward_paths, start=1)
            ]
        )

    if not forward_reachable and reverse_reachable:
        return ExtractionResult([], "oneway_direction_mismatch")
    if not forward_reachable:
        return ExtractionResult([], "rcsd_directed_path_missing")
    if reverse_reachable:
        return ExtractionResult([], "directionality_mismatch_rcsd_bidirectional_for_swsd_oneway")
    return ExtractionResult(
        [
            RcsdCandidate(
                candidate_id=f"rcsd_candidate_{index}",
                directionality="single",
                path=path,
                reverse_path=None,
                forward_reachable=True,
                reverse_reachable=False,
            )
            for index, path in enumerate(forward_paths, start=1)
        ]
    )
