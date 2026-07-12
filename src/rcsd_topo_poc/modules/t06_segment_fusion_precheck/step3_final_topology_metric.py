from __future__ import annotations

import json
from typing import Any

from .parsing import ParseError, parse_id_list, unique_preserve_order


FINAL_TOPOLOGY_CATEGORY_SEGMENT_TRANSITION = "segment_transition"
FINAL_TOPOLOGY_CATEGORY_INDEPENDENT_ATTACHMENT = "independent_attachment"

_SEGMENT_INTERNAL_FINAL_REASONS = {
    "segment_pair_nodes_not_connected",
    "dual_segment_pair_nodes_not_bidirectional",
}
_SEGMENT_ROAD_FINAL_REASONS = {
    "segment_road_endpoints_not_connected",
    "segment_road_directed_path_missing",
}


def annotate_final_frcsd_topology_rows(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        props = row.get("properties") or {}
        lineage = str(
            props.get("topology_road_lineage_id")
            or props.get("frcsd_road_id")
            or props.get("swsd_road_id")
            or ""
        )
        props["topology_road_lineage_id"] = lineage
        props.setdefault("topology_endpoint_index", None)
        category, object_key = classify_final_frcsd_topology(props)
        props["final_topology_category"] = category
        props["final_topology_object_key"] = object_key
        props["counts_in_final_frcsd_topology_fail"] = bool(object_key)


def classify_final_frcsd_topology(props: dict[str, Any]) -> tuple[str, str]:
    if str(props.get("audit_status") or "") != "fail":
        return "", ""
    layer = str(props.get("audit_layer") or "")
    reason = str(props.get("audit_reason") or "")
    category = _final_topology_category(layer, reason)
    if not category:
        return "", ""
    return category, _final_topology_object_key(category, layer, reason, props)


def final_frcsd_topology_fail_keys(rows: list[dict[str, Any]]) -> set[str]:
    annotate_final_frcsd_topology_rows(rows)
    return {
        str((row.get("properties") or {}).get("final_topology_object_key") or "")
        for row in rows
        if (row.get("properties") or {}).get("counts_in_final_frcsd_topology_fail")
    } - {""}


def summarize_final_frcsd_topology(rows: list[dict[str, Any]]) -> dict[str, int]:
    annotate_final_frcsd_topology_rows(rows)
    keys_by_category: dict[str, set[str]] = {
        FINAL_TOPOLOGY_CATEGORY_SEGMENT_TRANSITION: set(),
        FINAL_TOPOLOGY_CATEGORY_INDEPENDENT_ATTACHMENT: set(),
    }
    counted_row_count = 0
    for row in rows:
        props = row.get("properties") or {}
        object_key = str(props.get("final_topology_object_key") or "")
        category = str(props.get("final_topology_category") or "")
        if not object_key or category not in keys_by_category:
            continue
        counted_row_count += 1
        keys_by_category[category].add(object_key)
    transition_count = len(keys_by_category[FINAL_TOPOLOGY_CATEGORY_SEGMENT_TRANSITION])
    attachment_count = len(keys_by_category[FINAL_TOPOLOGY_CATEGORY_INDEPENDENT_ATTACHMENT])
    return {
        "final_frcsd_topology_fail_row_count": counted_row_count,
        "final_frcsd_topology_fail_count": transition_count + attachment_count,
        "final_frcsd_segment_transition_fail_count": transition_count,
        "final_frcsd_independent_attachment_fail_count": attachment_count,
    }


def _final_topology_category(layer: str, reason: str) -> str:
    if layer == "final_road_node_integrity":
        return FINAL_TOPOLOGY_CATEGORY_INDEPENDENT_ATTACHMENT
    if layer == "segment_internal_connectivity" and reason in _SEGMENT_INTERNAL_FINAL_REASONS:
        return FINAL_TOPOLOGY_CATEGORY_SEGMENT_TRANSITION
    if layer == "segment_road_connectivity" and reason in _SEGMENT_ROAD_FINAL_REASONS:
        return FINAL_TOPOLOGY_CATEGORY_SEGMENT_TRANSITION
    if layer == "retained_swsd_endpoint_closure":
        return FINAL_TOPOLOGY_CATEGORY_SEGMENT_TRANSITION
    if layer == "segment_junction_connectivity" and reason == "junction_incident_segment_mapped_points_diverged":
        return FINAL_TOPOLOGY_CATEGORY_SEGMENT_TRANSITION
    if layer == "patch_road_attachment":
        return FINAL_TOPOLOGY_CATEGORY_INDEPENDENT_ATTACHMENT
    if layer == "advance_right_endpoint_connectivity" and reason == "advance_right_leaf_endpoint_unattached":
        return FINAL_TOPOLOGY_CATEGORY_INDEPENDENT_ATTACHMENT
    return ""


def _final_topology_object_key(
    category: str,
    layer: str,
    reason: str,
    props: dict[str, Any],
) -> str:
    segment_id = str(props.get("swsd_segment_id") or "")
    segment_ids = sorted(_ids(props.get("swsd_segment_ids")))
    swsd_node_id = str(props.get("swsd_node_id") or "")
    swsd_road_id = str(props.get("swsd_road_id") or "")
    road_lineage = str(
        props.get("topology_road_lineage_id")
        or props.get("frcsd_road_id")
        or swsd_road_id
        or ""
    )
    endpoint_index = _endpoint_index(props)
    if layer == "final_road_node_integrity":
        parts: list[Any] = [layer, road_lineage, reason]
    elif layer == "segment_internal_connectivity":
        parts = [layer, segment_id, reason]
    elif layer == "segment_road_connectivity":
        parts = [layer, segment_id, swsd_road_id, reason]
    elif layer == "retained_swsd_endpoint_closure":
        parts = [layer, segment_id, swsd_road_id, swsd_node_id, reason]
    elif layer == "segment_junction_connectivity":
        parts = [layer, swsd_node_id, segment_ids, reason]
    elif layer == "patch_road_attachment":
        parts = [layer, swsd_road_id, swsd_node_id, road_lineage, reason]
    elif layer == "advance_right_endpoint_connectivity":
        if road_lineage:
            parts = [layer, road_lineage, endpoint_index, reason]
        else:
            parts = [layer, segment_ids, endpoint_index, reason]
    else:
        parts = [layer, segment_id, swsd_node_id, road_lineage, reason]
    return f"{category}:" + json.dumps(parts, ensure_ascii=False, separators=(",", ":"))


def _endpoint_index(props: dict[str, Any]) -> int | str:
    value = props.get("topology_endpoint_index")
    if value is not None and value != "":
        try:
            return int(value)
        except (TypeError, ValueError):
            return str(value)
    action_reason = str(props.get("action_reason") or "")
    if action_reason.startswith("endpoint_index_"):
        suffix = action_reason.removeprefix("endpoint_index_")
        try:
            return int(suffix)
        except ValueError:
            return suffix
    node_ids = _ids(props.get("frcsd_node_ids"))
    return node_ids[0] if node_ids else ""


def _ids(value: Any) -> list[str]:
    try:
        return unique_preserve_order(parse_id_list(value))
    except (ParseError, TypeError, ValueError):
        if value is None or value == "":
            return []
        return [str(value)]
