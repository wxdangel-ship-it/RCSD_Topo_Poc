from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, normalize_id
from .relation_mapping import RelationRecord


@dataclass(frozen=True)
class RelationBaseIndex:
    all_base_ids: frozenset[str]
    target_to_base: dict[str, str]
    targets_by_base: dict[str, frozenset[str]]

    @classmethod
    def from_relation_map(cls, relation_map: dict[str, RelationRecord]) -> RelationBaseIndex:
        target_to_base: dict[str, str] = {}
        targets_by_base_mutable: dict[str, set[str]] = {}
        for target_id, relation in relation_map.items():
            if relation.status != 0 or relation.base_id <= 0:
                continue
            base_id = str(relation.base_id)
            target_to_base[target_id] = base_id
            targets_by_base_mutable.setdefault(base_id, set()).add(target_id)
        return cls(
            all_base_ids=frozenset(targets_by_base_mutable),
            target_to_base=target_to_base,
            targets_by_base={base_id: frozenset(targets) for base_id, targets in targets_by_base_mutable.items()},
        )

    def unexpected_for(self, allowed_node_ids: list[str]) -> set[str]:
        allowed = set(allowed_node_ids)
        result = set(self.all_base_ids)
        for node_id in allowed:
            base_id = self.target_to_base.get(node_id)
            if base_id is None:
                continue
            if self.targets_by_base.get(base_id, frozenset()).issubset(allowed):
                result.discard(base_id)
        return result


@dataclass(frozen=True)
class _IncidentRoadIndex:
    roads_by_node: dict[str, tuple[str, ...]]
    road_rank: dict[str, int]


_INCIDENT_ROAD_INDEX_CACHE: dict[tuple[int, int], _IncidentRoadIndex] = {}


def lost_attach_road_ids(
    *,
    dropped_relation_nodes: list[str],
    buffer_result: Any,
    rcsd_roads: list[dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> list[str]:
    if not dropped_relation_nodes:
        return []
    index = _incident_index(rcsd_roads, rcsd_node_canonicalizer)
    candidate_ids = set(buffer_result.candidate_road_ids)
    retained_ids = set(buffer_result.retained_road_ids)
    seen: set[str] = set()
    result: list[str] = []
    for node_id in dropped_relation_nodes:
        for road_id in index.roads_by_node.get(node_id, ()):
            if road_id in seen or road_id not in candidate_ids or road_id in retained_ids:
                continue
            seen.add(road_id)
            result.append(road_id)
    result.sort(key=lambda road_id: index.road_rank.get(road_id, len(index.road_rank)))
    return result


def _incident_index(
    rcsd_roads: list[dict[str, Any]],
    rcsd_node_canonicalizer: NodeCanonicalizer,
) -> _IncidentRoadIndex:
    key = (id(rcsd_roads), id(rcsd_node_canonicalizer))
    cached = _INCIDENT_ROAD_INDEX_CACHE.get(key)
    if cached is not None:
        return cached
    by_node_mutable: dict[str, list[str]] = {}
    road_rank: dict[str, int] = {}
    for rank, road in enumerate(rcsd_roads):
        props = dict(road.get("properties") or {})
        try:
            road_id = normalize_id(_first_present(props, ["id", "road_id", "roadid"]))
            source = rcsd_node_canonicalizer.canonicalize(_first_present(props, ["snodeid", "snode_id", "source", "from_node"]))
            target = rcsd_node_canonicalizer.canonicalize(_first_present(props, ["enodeid", "enode_id", "target", "to_node"]))
        except (KeyError, ParseError):
            continue
        road_rank.setdefault(road_id, rank)
        by_node_mutable.setdefault(source, []).append(road_id)
        by_node_mutable.setdefault(target, []).append(road_id)
    index = _IncidentRoadIndex(
        roads_by_node={node_id: tuple(road_ids) for node_id, road_ids in by_node_mutable.items()},
        road_rank=road_rank,
    )
    _INCIDENT_ROAD_INDEX_CACHE[key] = index
    return index


def _first_present(props: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in props and props.get(name) is not None:
            return props[name]
    raise KeyError(names[0])
