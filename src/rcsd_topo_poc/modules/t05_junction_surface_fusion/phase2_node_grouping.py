from __future__ import annotations

from typing import Any

from shapely.geometry.base import BaseGeometry


def choose_primary_node_id(
    node_ids: list[int],
    *,
    nodes_by_id: dict[int, dict[str, Any]],
    reference_point: BaseGeometry,
    preferred_ids: list[int] | None = None,
) -> int:
    candidates = [node_id for node_id in (preferred_ids or []) if node_id in node_ids]
    if not candidates:
        candidates = list(node_ids)
    return min(candidates, key=lambda node_id: (_distance_to_reference(nodes_by_id.get(node_id), reference_point), node_id))


def apply_mainnodeid_grouping(
    *,
    node_ids: list[int],
    primary_node_id: int,
    node_features_by_id: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(node_ids) <= 1:
        return []
    updated: list[dict[str, Any]] = []
    for node_id in node_ids:
        feature = node_features_by_id.get(node_id)
        if feature is None:
            continue
        props = feature.setdefault("properties", {})
        props[_mainnodeid_field(props)] = primary_node_id
        updated.append(feature)
    return updated


def canonical_mainnode_id(node_id: int, node_features_by_id: dict[int, dict[str, Any]]) -> int:
    feature = node_features_by_id.get(node_id)
    if feature is None:
        return node_id
    props = feature.get("properties") or {}
    mainnodeid = _int_value(_field_value(props, "mainnodeid"))
    if mainnodeid in (None, 0, -1):
        return node_id
    if mainnodeid not in node_features_by_id:
        return node_id
    return mainnodeid


def canonical_mainnode_ids(node_ids: list[int], node_features_by_id: dict[int, dict[str, Any]]) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    for node_id in node_ids:
        canonical_id = canonical_mainnode_id(node_id, node_features_by_id)
        if canonical_id in seen:
            continue
        seen.add(canonical_id)
        ordered.append(canonical_id)
    return ordered


def generated_node_kind(swsd_properties: dict[str, Any]) -> tuple[Any, str]:
    if swsd_properties.get("kind") not in (None, ""):
        return swsd_properties.get("kind"), "swsd_kind"
    if swsd_properties.get("kind_2") not in (None, ""):
        return swsd_properties.get("kind_2"), "swsd_kind_2"
    return None, "missing"


def _distance_to_reference(feature: dict[str, Any] | None, reference_point: BaseGeometry) -> float:
    if feature is None or feature.get("geometry") is None:
        return float("inf")
    return float(feature["geometry"].distance(reference_point))


def _mainnodeid_field(properties: dict[str, Any]) -> str:
    for key in properties:
        if key.lower() == "mainnodeid":
            return key
    return "mainnodeid"


def _field_value(properties: dict[str, Any], field_name: str) -> Any:
    for key, value in properties.items():
        if key.lower() == field_name.lower():
            return value
    return None


def _int_value(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
