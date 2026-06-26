from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .parsing import ParseError, normalize_id


def build_step3_report_metrics(
    *,
    swsd_roads: list[dict[str, Any]],
    frcsd_roads: list[dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
    removed_road_to_segments: Mapping[str, Sequence[str]],
    removed_node_to_segments: Mapping[str, Sequence[str]],
    added_road_to_segments: Mapping[str, Sequence[str]],
    added_node_to_segments: Mapping[str, Sequence[str]],
    unreplaced_rcsd_road_rows: list[dict[str, Any]],
    segment_relation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    swsd_road_by_id = {_feature_id(road): road for road in swsd_roads}
    replaced_swsd_road_ids = set(removed_road_to_segments) & set(swsd_road_by_id)
    denominator_length = sum(_feature_length(road) for road in swsd_road_by_id.values())
    replaced_length = sum(_feature_length(swsd_road_by_id[road_id]) for road_id in replaced_swsd_road_ids)
    final_rcsd_road_by_id = {
        _feature_id(road): road
        for road in frcsd_roads
        if str((road.get("properties") or {}).get(source_field_name)) == str(rcsd_source_value)
    }
    added_rcsd_road_ids = set(added_road_to_segments)
    rcsd_added_length = sum(
        _feature_length(final_rcsd_road_by_id[road_id])
        for road_id in added_rcsd_road_ids
        if road_id in final_rcsd_road_by_id
    )
    relation_statuses = [str((row.get("properties") or {}).get("relation_status") or "") for row in segment_relation_rows]
    replaced_count = relation_statuses.count("replaced")
    replaced_retained_count = relation_statuses.count("replaced+retained_swsd")
    replacement_success_count = replaced_count + replaced_retained_count
    relation_total = len(segment_relation_rows)
    swsd_road_denominator_count = len(swsd_road_by_id)
    swsd_road_replaced_count = len(replaced_swsd_road_ids)
    return {
        "removed_swsd_road_count": len(removed_road_to_segments),
        "removed_swsd_node_count": len(removed_node_to_segments),
        "added_rcsd_road_count": len(added_road_to_segments),
        "added_rcsd_node_count": len(added_node_to_segments),
        "unreplaced_rcsd_road_count": len(unreplaced_rcsd_road_rows),
        "unreplaced_rcsd_road_length_m": _round_length(sum(_feature_length(row) for row in unreplaced_rcsd_road_rows)),
        "segment_relation_count": relation_total,
        "segment_relation_replaced_count": replaced_count,
        "segment_relation_replaced_retained_swsd_count": replaced_retained_count,
        "segment_relation_retained_swsd_count": relation_statuses.count("retained_swsd"),
        "segment_relation_failed_count": relation_statuses.count("failed"),
        "segment_replacement_success_count": replacement_success_count,
        "segment_replacement_success_rate": _rate(replacement_success_count, relation_total),
        "segment_retained_swsd_count": relation_statuses.count("retained_swsd"),
        "segment_failed_count": relation_statuses.count("failed"),
        "swsd_road_denominator_count": swsd_road_denominator_count,
        "swsd_road_replaced_count": swsd_road_replaced_count,
        "swsd_road_retained_count": max(swsd_road_denominator_count - swsd_road_replaced_count, 0),
        "rcsd_road_added_count": len(added_road_to_segments),
        "road_replacement_rate": _rate(swsd_road_replaced_count, swsd_road_denominator_count),
        "swsd_length_denominator_m": _round_length(denominator_length),
        "swsd_length_replaced_m": _round_length(replaced_length),
        "swsd_length_retained_m": _round_length(max(denominator_length - replaced_length, 0.0)),
        "rcsd_length_added_m": _round_length(rcsd_added_length),
        "length_replacement_rate": _rate(replaced_length, denominator_length),
    }


def _feature_id(feature_item: dict[str, Any]) -> str:
    try:
        return normalize_id((feature_item.get("properties") or {}).get("id"))
    except ParseError:
        return str((feature_item.get("properties") or {}).get("id") or "")


def _feature_length(feature_item: dict[str, Any]) -> float:
    geometry = feature_item.get("geometry")
    if geometry is None or getattr(geometry, "is_empty", False):
        return 0.0
    return float(getattr(geometry, "length", 0.0) or 0.0)


def _round_length(value: float) -> float:
    return round(float(value), 3)


def _rate(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round(float(numerator) / float(denominator), 6)
