from __future__ import annotations

from dataclasses import dataclass

from .graph_builders import build_road_graph, subset_road_features


@dataclass(frozen=True)
class DirectionInference:
    status: str
    source_node: str | None
    target_node: str | None
    reject_reason: str | None = None


def infer_swsd_oneway_direction(
    *,
    pair_nodes: list[str],
    segment_road_ids: list[str],
    swsd_road_features: list[dict],
) -> DirectionInference:
    if len(pair_nodes) != 2:
        return DirectionInference("missing", None, None, "missing_swsd_oneway_direction")
    if not segment_road_ids:
        return DirectionInference("missing", None, None, "missing_swsd_oneway_direction")
    road_features = subset_road_features(swsd_road_features, segment_road_ids)
    if not road_features:
        return DirectionInference("missing", None, None, "missing_swsd_oneway_direction")

    graph = build_road_graph(road_features)
    if graph.invalid_rows:
        return DirectionInference("missing", None, None, "missing_swsd_oneway_direction")

    first, second = pair_nodes
    first_to_second = graph.reachable(first, second)
    second_to_first = graph.reachable(second, first)
    if first_to_second and not second_to_first:
        return DirectionInference("unique", first, second)
    if second_to_first and not first_to_second:
        return DirectionInference("unique", second, first)
    if first_to_second and second_to_first:
        return DirectionInference("bidirectional_like", None, None, "swsd_oneway_body_bidirectional_like")
    return DirectionInference("disconnected", None, None, "swsd_oneway_body_not_connected")
