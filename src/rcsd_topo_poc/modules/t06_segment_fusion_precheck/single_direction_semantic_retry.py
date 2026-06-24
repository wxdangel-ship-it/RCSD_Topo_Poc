from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from typing import Any

from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, normalize_id
from .road_attributes import is_advance_right_turn_road


def semantic_endpoint_local_undirected_single_retry(
    *,
    buffer_extractor: Any,
    segment_geometry: Any,
    relation: Any,
    optional_allowed_rcsd_nodes: list[str],
    all_relation_base_ids: set[str],
    unexpected_relation_base_ids: set[str],
    directed_swsd_pair_nodes: list[str],
    directed_rcsd_pair_nodes: list[str],
    pair_nodes: list[str],
    road_ids: list[str],
    swsd_roads: dict[str, dict[str, Any]],
    swsd_node_canonicalizer: NodeCanonicalizer,
    special_swsd_junction_types: dict[str, str],
    config: Any,
) -> tuple[bool, Any | None, str]:
    if len(directed_swsd_pair_nodes) != 2 or len(directed_rcsd_pair_nodes) != 2:
        return False, None, ""
    if not _has_semantic_endpoint_subnode(
        pair_nodes=pair_nodes,
        road_ids=road_ids,
        swsd_roads=swsd_roads,
        swsd_node_canonicalizer=swsd_node_canonicalizer,
        special_swsd_junction_types=special_swsd_junction_types,
    ):
        return False, None, ""
    result = buffer_extractor.extract(
        segment_geometry=segment_geometry,
        relation=relation,
        optional_allowed_rcsd_nodes=optional_allowed_rcsd_nodes,
        all_relation_base_ids=all_relation_base_ids,
        unexpected_relation_base_ids=unexpected_relation_base_ids,
        directed_pair_nodes=[],
        require_directed_pair=False,
        require_bidirectional=False,
        config=config,
    )
    if not result.ok:
        return True, None, ""
    if not _retained_path_has_only_advance_right_direction_gaps(
        result=result,
        directed_rcsd_pair_nodes=directed_rcsd_pair_nodes,
        road_features=buffer_extractor.road_index.features,
        rcsd_node_canonicalizer=buffer_extractor.node_canonicalizer,
        formway_bit=int(getattr(config, "advance_right_formway_bit", 128) or 128),
    ):
        return True, None, ""
    return (
        True,
        replace(result, directed_rcsd_pair_nodes=list(directed_rcsd_pair_nodes)),
        "semantic_endpoint_local_undirected_corridor_release:rcsd_directed_path_missing",
    )


def _has_semantic_endpoint_subnode(
    *,
    pair_nodes: list[str],
    road_ids: list[str],
    swsd_roads: dict[str, dict[str, Any]],
    swsd_node_canonicalizer: NodeCanonicalizer,
    special_swsd_junction_types: dict[str, str],
) -> bool:
    canonical_pair_nodes = [_canonicalize(node_id, swsd_node_canonicalizer) for node_id in pair_nodes]
    if not any(node_id in special_swsd_junction_types for node_id in canonical_pair_nodes):
        return False
    pair_node_set = set(canonical_pair_nodes)
    for road_id in road_ids:
        road = swsd_roads.get(road_id)
        if road is None:
            continue
        endpoints = _raw_endpoints(road)
        if endpoints is None:
            continue
        for endpoint in endpoints:
            canonical = _canonicalize(endpoint, swsd_node_canonicalizer)
            if endpoint != canonical and canonical in pair_node_set:
                return True
    return False


def _canonicalize(node_id: str, canonicalizer: NodeCanonicalizer) -> str:
    try:
        return canonicalizer.canonicalize(node_id)
    except ParseError:
        return node_id


def _raw_endpoints(road: dict[str, Any]) -> tuple[str, str] | None:
    props = dict(road.get("properties") or {})
    try:
        return (
            normalize_id(_first_present(props, ["snodeid", "snode_id", "source", "from_node"])),
            normalize_id(_first_present(props, ["enodeid", "enode_id", "target", "to_node"])),
        )
    except (KeyError, ParseError):
        return None


def _retained_path_has_only_advance_right_direction_gaps(
    *,
    result: Any,
    directed_rcsd_pair_nodes: list[str],
    road_features: list[dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
    formway_bit: int,
) -> bool:
    if len(directed_rcsd_pair_nodes) != 2:
        return False
    retained = set(result.retained_road_ids)
    if not retained:
        return False
    roads = _road_index(road_features)
    path = _retained_path(
        retained,
        roads,
        source=directed_rcsd_pair_nodes[0],
        target=directed_rcsd_pair_nodes[1],
        rcsd_node_canonicalizer=rcsd_node_canonicalizer,
    )
    if not path:
        return False
    direction_gap_ids: list[str] = []
    for road_id, source, target in path:
        road = roads.get(road_id)
        if road is None:
            return False
        props = dict(road.get("properties") or {})
        endpoints = _canonical_road_endpoints(props, rcsd_node_canonicalizer)
        if endpoints is None:
            return False
        road_source, road_target = endpoints
        direction = _parse_direction(props.get("direction"))
        if _traversal_allowed_by_direction(source, target, road_source, road_target, direction):
            continue
        if not is_advance_right_turn_road(props, formway_bit=formway_bit):
            return False
        direction_gap_ids.append(road_id)
    return bool(direction_gap_ids)


def _road_index(road_features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for road in road_features:
        props = dict(road.get("properties") or {})
        try:
            result[normalize_id(_first_present(props, ["id", "road_id", "roadid"]))] = road
        except (KeyError, ParseError):
            continue
    return result


def _retained_path(
    retained_road_ids: set[str],
    roads: dict[str, dict[str, Any]],
    *,
    source: str,
    target: str,
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> list[tuple[str, str, str]]:
    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for road_id in retained_road_ids:
        road = roads.get(road_id)
        if road is None:
            continue
        endpoints = _canonical_road_endpoints(dict(road.get("properties") or {}), rcsd_node_canonicalizer)
        if endpoints is None:
            continue
        a, b = endpoints
        adjacency[a].append((b, road_id))
        adjacency[b].append((a, road_id))
    queue: list[tuple[str, list[tuple[str, str, str]]]] = [(source, [])]
    seen = {source}
    while queue:
        node, path = queue.pop(0)
        if node == target and path:
            return path
        for neighbor, road_id in adjacency.get(node, []):
            if neighbor in seen:
                continue
            seen.add(neighbor)
            queue.append((neighbor, [*path, (road_id, node, neighbor)]))
    return []


def _canonical_road_endpoints(
    props: dict[str, Any],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> tuple[str, str] | None:
    try:
        return (
            rcsd_node_canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"])),
            rcsd_node_canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"])),
        )
    except (KeyError, ParseError):
        return None


def _traversal_allowed_by_direction(
    source: str,
    target: str,
    road_source: str,
    road_target: str,
    direction: int | None,
) -> bool:
    if direction in {0, 1}:
        return True
    if direction == 2:
        return source == road_source and target == road_target
    if direction == 3:
        return source == road_target and target == road_source
    return False


def _parse_direction(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _first_present(props: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in props and props.get(name) is not None:
            return props[name]
    raise KeyError(names[0])
