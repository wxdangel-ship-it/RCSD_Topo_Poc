from __future__ import annotations

from typing import Any

from .parsing import ParseError, normalize_id, parse_positive_int
from .schemas import feature


def change_rows(items: dict[str, list[str]], entity_type: str, source_value: int, reason: str) -> list[dict[str, Any]]:
    return [
        feature(
            {
                "entity_id": entity_id,
                "entity_type": entity_type,
                "source": source_value,
                "reason": reason,
                "swsd_segment_ids": segment_ids,
            },
            None,
        )
        for entity_id, segment_ids in sorted(items.items(), key=lambda item: _id_sort_key(item[0]))
    ]


def unreplaced_rcsd_road_rows(
    *,
    rcsd_roads: list[dict[str, Any]],
    added_road_ids: set[str],
    source_value: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for road in rcsd_roads:
        try:
            road_id = _feature_id(road)
        except ParseError:
            continue
        if road_id in added_road_ids:
            continue
        props = dict(road.get("properties") or {})
        props.update(
            {
                "id": road_id,
                "replacement_status": "not_replaced",
                "audit_reason": "not_referenced_by_step2_replaceable_rcsd_segment",
                "source": source_value,
                "length_m": _round_length(_feature_length(road)),
            }
        )
        rows.append(feature(props, road.get("geometry")))
    return sorted(rows, key=lambda item: _id_sort_key(_feature_id(item)))


def feature_id_set(features: list[dict[str, Any]], source_field_name: str, source_value: int) -> set[str]:
    return {
        _feature_id(item)
        for item in features
        if (item.get("properties") or {}).get(source_field_name) == source_value
    }


def id_collision_rows(
    *,
    retained_swsd_road_ids: set[str],
    retained_swsd_node_ids: set[str],
    added_rcsd_road_ids: set[str],
    added_rcsd_node_ids: set[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entity_type, swsd_ids, rcsd_ids in (
        ("road", retained_swsd_road_ids, added_rcsd_road_ids),
        ("node", retained_swsd_node_ids, added_rcsd_node_ids),
    ):
        for entity_id in sorted(swsd_ids.intersection(rcsd_ids), key=_id_sort_key):
            rows.append(
                feature(
                    {
                        "entity_type": entity_type,
                        "entity_id": entity_id,
                        "swsd_present": True,
                        "rcsd_present": True,
                        "policy": "keep_original_ids_and_audit_with_source_field",
                    },
                    None,
                )
            )
    return rows


def fieldnames(features: list[dict[str, Any]], preferred: list[str]) -> list[str]:
    fields: list[str] = []
    for field_name in preferred:
        if field_name not in fields:
            fields.append(field_name)
    for item in features:
        for field_name in (item.get("properties") or {}).keys():
            if field_name not in fields:
                fields.append(field_name)
    return fields


def _feature_id(feature_item: dict[str, Any]) -> str:
    return normalize_id((feature_item.get("properties") or {}).get("id"))


def _feature_length(feature_item: dict[str, Any]) -> float:
    geometry = feature_item.get("geometry")
    if geometry is None or getattr(geometry, "is_empty", False):
        return 0.0
    return float(getattr(geometry, "length", 0.0) or 0.0)


def _round_length(value: float) -> float:
    return round(float(value), 3)


def _id_sort_key(value: str) -> tuple[int, int | str]:
    parsed = parse_positive_int(value)
    if parsed is not None:
        return (0, parsed)
    return (1, str(value))
