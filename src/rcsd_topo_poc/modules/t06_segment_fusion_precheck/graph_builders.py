from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry.base import BaseGeometry

from .parsing import ParseError, normalize_id, parse_id_list, parse_positive_int


@dataclass(frozen=True)
class Edge:
    edge_id: str
    road_id: str
    source: str
    target: str
    geometry: BaseGeometry | None
    properties: dict[str, Any]


@dataclass(frozen=True)
class NodeCanonicalizer:
    aliases: dict[str, str]
    semantic_node_ids: frozenset[str]

    @classmethod
    def from_node_features(cls, features: list[dict[str, Any]]) -> NodeCanonicalizer:
        aliases: dict[str, str] = {}
        semantic_node_ids: set[str] = set()
        for feature in features:
            props = dict(feature.get("properties") or {})
            try:
                node_id = normalize_id(props.get("id"))
            except ParseError:
                continue
            mainnodeid = parse_positive_int(props.get("mainnodeid"))
            canonical = str(mainnodeid) if mainnodeid is not None else node_id
            aliases.setdefault(node_id, canonical)
            subnode_ids = _parse_optional_id_list(props.get("subnodeid"))
            if mainnodeid is not None or subnode_ids or _is_semantic_node_kind(props):
                semantic_node_ids.add(canonical)
            for subnode_id in subnode_ids:
                aliases.setdefault(subnode_id, canonical)
        return cls(aliases=aliases, semantic_node_ids=frozenset(semantic_node_ids))

    def canonicalize(self, value: Any) -> str:
        node_id = normalize_id(value)
        return self.aliases.get(node_id, node_id)


def _parse_optional_id_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _is_semantic_node_kind(props: dict[str, Any]) -> bool:
    kind = parse_positive_int(props.get("kind_2"))
    if kind is None:
        kind = parse_positive_int(props.get("kind"))
    return kind is not None and kind > 0
