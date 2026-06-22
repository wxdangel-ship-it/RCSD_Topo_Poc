from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from .parsing import ParseError, parse_id_list, unique_preserve_order


RETAINED_SWSD_PEER_MAINNODE_MAX_GAP_M = 5.0


def backfill_relation_node_maps_from_attachment_audit(
    segment_relation_rows: list[dict[str, Any]],
    attachment_audit_rows: list[dict[str, Any]],
    *,
    frcsd_roads: list[dict[str, Any]] | None = None,
    source_field_name: str = "source",
    swsd_source_value: int = 2,
) -> dict[str, int]:
    attachment_node_ids = _attachment_node_ids_by_swsd_node(attachment_audit_rows)
    peer_node_ids = _peer_rcsd_node_ids_by_swsd_node(segment_relation_rows)
    retained_endpoint_nodes = _retained_topology_endpoint_nodes_by_segment(
        frcsd_roads or [],
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
    )
    stats = {
        "relation_node_map_backfilled_entry_count": 0,
        "relation_node_map_backfilled_row_count": 0,
    }
    if not attachment_node_ids and not peer_node_ids and not retained_endpoint_nodes:
        return stats

    for row in segment_relation_rows:
        props = row.get("properties") or {}
        segment_id = str(props.get("swsd_segment_id") or "")
        relation_status = str(props.get("relation_status") or "")
        risk_flags = _parse_id_list(props.get("risk_flags"))
        topology_supplement = (
            relation_status == "replaced+retained_swsd"
            and "retained_swsd_topology_supplement" in risk_flags
        )
        retained_nodes = retained_endpoint_nodes.get(segment_id, set())
        node_map = _node_map_entries(props.get("swsd_to_frcsd_node_map"))
        row_changed = False
        mapped_swsd_nodes = {str(entry.get("swsd_node_id") or "") for entry in node_map}
        for swsd_node_id in _parse_id_list(props.get("detached_junc_nodes")):
            if swsd_node_id in mapped_swsd_nodes:
                continue
            rcsd_node_ids = attachment_node_ids.get(swsd_node_id) or peer_node_ids.get(swsd_node_id, [])
            if not rcsd_node_ids:
                continue
            node_map.append(
                {
                    "swsd_node_id": swsd_node_id,
                    "frcsd_node_ids": rcsd_node_ids,
                    "node_role": "detached_junc_node",
                    "mapping_status": (
                        "attachment_mapped_detached"
                        if swsd_node_id in attachment_node_ids
                        else "peer_mapped_detached"
                    ),
                }
            )
            stats["relation_node_map_backfilled_entry_count"] += 1
            row_changed = True
        for entry in node_map:
            swsd_node_id = str(entry.get("swsd_node_id") or "")
            rcsd_node_ids = attachment_node_ids.get(swsd_node_id) or peer_node_ids.get(swsd_node_id, [])
            retained_topology_endpoint = topology_supplement and swsd_node_id in retained_nodes
            if (
                not rcsd_node_ids
                and not retained_topology_endpoint
            ):
                continue
            mapping_status = str(entry.get("mapping_status") or "")
            if mapping_status == "missing":
                if rcsd_node_ids:
                    entry["frcsd_node_ids"] = rcsd_node_ids
                    entry["mapping_status"] = (
                        "attachment_mapped" if swsd_node_id in attachment_node_ids else "peer_mapped"
                    )
                elif retained_topology_endpoint:
                    entry["frcsd_node_ids"] = [swsd_node_id]
                    entry["mapping_status"] = "identity_topology_supplement"
                else:
                    continue
            elif relation_status == "retained_swsd" and mapping_status.startswith("identity"):
                continue
            elif topology_supplement and mapping_status in {"mapped", "peer_mapped", "attachment_mapped"}:
                if rcsd_node_ids:
                    entry["frcsd_node_ids"] = rcsd_node_ids
                    entry["mapping_status"] = "attachment_mapped_topology_supplement"
                else:
                    continue
            else:
                continue
            stats["relation_node_map_backfilled_entry_count"] += 1
            row_changed = True
        if not row_changed:
            continue
        props["swsd_to_frcsd_node_map"] = node_map
        props["risk_flags"] = unique_preserve_order(
            [*_parse_id_list(props.get("risk_flags")), "attachment_backfilled_node_map"]
        )
        stats["relation_node_map_backfilled_row_count"] += 1
    return stats


def sync_retained_swsd_carrier_mainnodes(
    segment_relation_rows: list[dict[str, Any]],
    frcsd_roads: list[dict[str, Any]],
    frcsd_nodes: list[dict[str, Any]],
    *,
    source_field_name: str = "source",
    swsd_source_value: int = 2,
    rcsd_source_value: int = 1,
) -> dict[str, int]:
    road_by_key = {
        (_source_text((road.get("properties") or {}).get(source_field_name)), _safe_id((road.get("properties") or {}).get("id"))): road
        for road in frcsd_roads
    }
    node_by_key = {
        (_source_text((node.get("properties") or {}).get(source_field_name)), _safe_id((node.get("properties") or {}).get("id"))): node
        for node in frcsd_nodes
    }
    stats = {
        "retained_swsd_carrier_mainnode_candidate_count": 0,
        "retained_swsd_carrier_mainnode_synced_count": 0,
        "retained_swsd_carrier_mainnode_row_count": 0,
    }
    swsd_source = str(swsd_source_value)
    rcsd_source = str(rcsd_source_value)
    peer_rcsd_node_ids = _peer_rcsd_node_ids_by_swsd_node(segment_relation_rows, include_mixed=True)
    for row in segment_relation_rows:
        props = row.get("properties") or {}
        relation_status = str(props.get("relation_status") or "")
        if relation_status not in {"replaced+retained_swsd", "retained_swsd"}:
            continue
        retained_endpoint_nodes: set[str] = set()
        retained_road_ids = _parse_id_list(props.get("retained_detached_swsd_road_ids"))
        if relation_status == "retained_swsd":
            retained_road_ids = unique_preserve_order([*retained_road_ids, *_parse_id_list(props.get("frcsd_road_ids"))])
        for road_id in retained_road_ids:
            road = road_by_key.get((swsd_source, road_id))
            if road is None:
                continue
            road_props = road.get("properties") or {}
            retained_endpoint_nodes.update(
                node_id for node_id in (_safe_id(road_props.get("snodeid")), _safe_id(road_props.get("enodeid"))) if node_id
            )
        if not retained_endpoint_nodes:
            continue
        row_changed = False
        node_map = _node_map_entries(props.get("swsd_to_frcsd_node_map"))
        for entry in node_map:
            swsd_node_id = _safe_id(entry.get("swsd_node_id"))
            if swsd_node_id not in retained_endpoint_nodes:
                continue
            mapping_status = str(entry.get("mapping_status") or "")
            if mapping_status == "missing":
                continue
            rcsd_node_ids = _parse_id_list(entry.get("frcsd_node_ids"))
            if mapping_status.startswith("identity"):
                rcsd_node_ids = peer_rcsd_node_ids.get(swsd_node_id, [])
            swsd_node = node_by_key.get((swsd_source, swsd_node_id))
            if swsd_node is None:
                continue
            rcsd_nodes = [
                rcsd_node
                for rcsd_node_id in rcsd_node_ids
                for rcsd_node in [node_by_key.get((rcsd_source, rcsd_node_id))]
                if rcsd_node is not None
            ]
            if mapping_status.startswith("identity") and not _has_close_peer_node(
                swsd_node,
                rcsd_nodes,
                max_gap_m=RETAINED_SWSD_PEER_MAINNODE_MAX_GAP_M,
            ):
                continue
            target_mainnode_ids = unique_preserve_order(
                [
                    target
                    for rcsd_node in rcsd_nodes
                    for target in [_mainnode_or_id(rcsd_node) if rcsd_node is not None else ""]
                    if target
                ]
            )
            if len(target_mainnode_ids) != 1:
                continue
            target_mainnodeid = target_mainnode_ids[0]
            if not target_mainnodeid:
                continue
            stats["retained_swsd_carrier_mainnode_candidate_count"] += 1
            swsd_props = swsd_node.setdefault("properties", {})
            if _safe_id(swsd_props.get("mainnodeid")) == target_mainnodeid:
                continue
            swsd_props["mainnodeid"] = target_mainnodeid
            if mapping_status.startswith("identity"):
                entry["mapping_status"] = "identity_semantic_mainnode_synced"
            stats["retained_swsd_carrier_mainnode_synced_count"] += 1
            row_changed = True
        if not row_changed:
            continue
        props["swsd_to_frcsd_node_map"] = node_map
        props["risk_flags"] = unique_preserve_order(
            [*_parse_id_list(props.get("risk_flags")), "retained_swsd_carrier_mainnode_synced"]
        )
        stats["retained_swsd_carrier_mainnode_row_count"] += 1
    return stats


def _peer_rcsd_node_ids_by_swsd_node(rows: list[dict[str, Any]], *, include_mixed: bool = False) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        props = row.get("properties") or {}
        relation_status = str(props.get("relation_status") or "")
        if relation_status != "replaced" and not (include_mixed and "replaced" in relation_status):
            continue
        for entry in _node_map_entries(props.get("swsd_to_frcsd_node_map")):
            mapping_status = str(entry.get("mapping_status") or "")
            if mapping_status == "missing" or mapping_status.startswith("identity"):
                continue
            swsd_node_id = str(entry.get("swsd_node_id") or "")
            if not swsd_node_id:
                continue
            result[swsd_node_id] = unique_preserve_order(
                [*result[swsd_node_id], *_parse_id_list(entry.get("frcsd_node_ids"))]
            )
    return dict(result)


def _attachment_node_ids_by_swsd_node(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        props = dict(row.get("properties") or {})
        action = str(props.get("action") or "")
        if not action.startswith(("split_", "reuse_")):
            continue
        swsd_node_id = str(props.get("swsd_node_id") or "")
        rcsd_node_id = str(props.get("rcsd_node_id") or props.get("generated_rcsd_node_id") or "")
        if not swsd_node_id or not rcsd_node_id:
            continue
        result[swsd_node_id] = unique_preserve_order([*result[swsd_node_id], rcsd_node_id])
    return dict(result)


def _retained_topology_endpoint_nodes_by_segment(
    roads: list[dict[str, Any]],
    *,
    source_field_name: str,
    swsd_source_value: int,
) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for road in roads:
        props = dict(road.get("properties") or {})
        if str(props.get(source_field_name) or "") != str(swsd_source_value):
            continue
        for segment_id in _parse_id_list(props.get("segmentid")):
            for node_id in (props.get("snodeid"), props.get("enodeid")):
                node_id_text = str(node_id or "")
                if node_id_text:
                    result[segment_id].add(node_id_text)
    return dict(result)


def _node_map_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return [dict(item) for item in parsed if isinstance(item, dict)]
    return []


def _parse_id_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _safe_id(value: Any) -> str:
    return "" if value is None else str(value)


def _source_text(value: Any) -> str:
    return str(value or "")


def _mainnode_or_id(node: dict[str, Any]) -> str:
    props = node.get("properties") or {}
    return _safe_id(props.get("mainnodeid")) or _safe_id(props.get("id"))


def _has_close_peer_node(swsd_node: dict[str, Any], rcsd_nodes: list[dict[str, Any]], *, max_gap_m: float) -> bool:
    swsd_geometry = swsd_node.get("geometry")
    if swsd_geometry is None:
        return False
    for rcsd_node in rcsd_nodes:
        rcsd_geometry = rcsd_node.get("geometry")
        if rcsd_geometry is not None and swsd_geometry.distance(rcsd_geometry) <= max_gap_m:
            return True
    return False
