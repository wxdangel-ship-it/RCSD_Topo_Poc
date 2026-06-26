from __future__ import annotations

from typing import Any

from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order
from .schemas import feature
from .step3_topology_connectivity_audit import build_topology_connectivity_audit_rows


GROUP_COVERAGE_FALLBACK_RISK = "group_path_corridor_local_coverage_retained_swsd"
GROUP_COVERAGE_FALLBACK_REASON = "group_path_corridor_local_coverage_retained_swsd"
_GROUP_LOCAL_COVERAGE_REASON = "group_path_corridor_segment_local_coverage_review"


def retain_group_coverage_fallback(
    *,
    units: list[Any],
    swsd_segments: list[dict[str, Any]],
    swsd_roads: list[dict[str, Any]],
    swsd_nodes: list[dict[str, Any]],
    frcsd_roads: list[dict[str, Any]],
    frcsd_nodes: list[dict[str, Any]],
    segment_relation_rows: list[dict[str, Any]],
    advance_right_audit_rows: list[dict[str, Any]],
    removed_road_to_segments: dict[str, list[str]],
    removed_node_to_segments: dict[str, list[str]],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
) -> dict[str, Any]:
    split_sync_stats = _sync_split_road_refs(
        frcsd_roads=frcsd_roads,
        segment_relation_rows=segment_relation_rows,
        units=units,
    )
    audit_rows = build_topology_connectivity_audit_rows(
        swsd_segments=swsd_segments,
        swsd_roads=swsd_roads,
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=segment_relation_rows,
        advance_right_audit_rows=advance_right_audit_rows,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    fallback_segments = _fallback_segment_ids(audit_rows)
    if not fallback_segments:
        return _stats([], [], [], split_sync_stats)

    swsd_road_by_id = {_feature_id(road): road for road in swsd_roads}
    swsd_node_by_id = {_feature_id(node): node for node in swsd_nodes}
    final_roads = {(_source_key(road, source_field_name), _feature_id(road)): road for road in frcsd_roads}
    final_nodes = {(_source_key(node, source_field_name), _feature_id(node)): node for node in frcsd_nodes}
    relation_by_segment = {str((row.get("properties") or {}).get("swsd_segment_id") or ""): row for row in segment_relation_rows}
    unit_by_segment = {str(getattr(unit, "segment_id", "")): unit for unit in units}

    retained_roads: list[str] = []
    retained_nodes: list[str] = []
    retained_segments: list[str] = []
    for segment_id in fallback_segments:
        relation = relation_by_segment.get(segment_id)
        if relation is None:
            continue
        props = relation.setdefault("properties", {})
        road_ids = _ids(props.get("swsd_road_ids")) or _ids(props.get("removed_swsd_road_ids"))
        present_roads = [road_id for road_id in road_ids if road_id in swsd_road_by_id]
        if not present_roads:
            continue
        retained_segments.append(segment_id)
        segment_retained_nodes: list[str] = []
        for road_id in present_roads:
            road = _ensure_feature(
                road_id,
                swsd_road_by_id,
                final_roads,
                frcsd_roads,
                source_field_name,
                swsd_source_value,
                segment_id,
            )
            if road is not None:
                retained_roads.append(road_id)
                removed_road_to_segments.pop(road_id, None)
                for node_id in _road_endpoint_node_ids(road):
                    node = _ensure_feature(
                        node_id,
                        swsd_node_by_id,
                        final_nodes,
                        frcsd_nodes,
                        source_field_name,
                        swsd_source_value,
                        segment_id,
                    )
                    if node is not None:
                        segment_retained_nodes.append(node_id)
                        retained_nodes.append(node_id)
                        removed_node_to_segments.pop(node_id, None)
        _mark_unit(unit_by_segment.get(segment_id), present_roads, segment_retained_nodes)
        _mark_relation(props, present_roads, swsd_source_value)

    return _stats(retained_segments, retained_roads, retained_nodes, split_sync_stats)


def _sync_split_road_refs(
    *,
    frcsd_roads: list[dict[str, Any]],
    segment_relation_rows: list[dict[str, Any]],
    units: list[Any],
) -> dict[str, int]:
    final_road_ids = {_feature_id(road) for road in frcsd_roads if _feature_id(road)}
    split_ids_by_original: dict[str, list[str]] = {}
    for road in frcsd_roads:
        props = road.get("properties") or {}
        original_id = _safe_id(props.get("t06_split_original_road_id"))
        road_id = _feature_id(road)
        if original_id and road_id:
            split_ids_by_original.setdefault(original_id, []).append(road_id)
    if not split_ids_by_original:
        return {
            "split_relation_road_reference_sync_count": 0,
            "split_unit_road_reference_sync_count": 0,
        }

    relation_sync_count = 0
    for row in segment_relation_rows:
        props = row.setdefault("properties", {})
        original_ids = _ids(props.get("frcsd_road_ids"))
        synced_ids = _replace_split_original_refs(original_ids, final_road_ids, split_ids_by_original)
        if synced_ids != original_ids:
            props["frcsd_road_ids"] = synced_ids
            relation_sync_count += 1

    unit_sync_count = 0
    for unit in units:
        original_ids = list(getattr(unit, "rcsd_road_ids", []) or [])
        synced_ids = _replace_split_original_refs(original_ids, final_road_ids, split_ids_by_original)
        if synced_ids != original_ids:
            unit.rcsd_road_ids = synced_ids
            unit_sync_count += 1

    return {
        "split_relation_road_reference_sync_count": relation_sync_count,
        "split_unit_road_reference_sync_count": unit_sync_count,
    }


def _replace_split_original_refs(
    road_ids: list[str],
    final_road_ids: set[str],
    split_ids_by_original: dict[str, list[str]],
) -> list[str]:
    synced: list[str] = []
    for road_id in road_ids:
        if road_id in final_road_ids:
            synced.append(road_id)
            continue
        split_ids = split_ids_by_original.get(road_id)
        if split_ids:
            synced.extend(split_ids)
        else:
            synced.append(road_id)
    return unique_preserve_order(synced)


def _fallback_segment_ids(audit_rows: list[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for row in audit_rows:
        props = row.get("properties") or {}
        if props.get("audit_layer") != "segment_internal_connectivity":
            continue
        if props.get("audit_reason") != _GROUP_LOCAL_COVERAGE_REASON:
            continue
        segment_id = str(props.get("swsd_segment_id") or "")
        if segment_id:
            result.append(segment_id)
    return unique_preserve_order(result)


def _ensure_feature(
    item_id: str,
    source_by_id: dict[str, dict[str, Any]],
    final_by_key: dict[tuple[str, str], dict[str, Any]],
    final_rows: list[dict[str, Any]],
    source_field_name: str,
    source_value: int,
    segment_id: str,
) -> dict[str, Any] | None:
    key = (str(source_value), item_id)
    existing = final_by_key.get(key)
    if existing is not None:
        _append_segment(existing, segment_id)
        return existing
    source = source_by_id.get(item_id)
    if source is None:
        return None
    row = _with_source(source, source_field_name, source_value, segment_id)
    final_rows.append(row)
    final_by_key[key] = row
    return row


def _mark_relation(props: dict[str, Any], retained_road_ids: list[str], swsd_source_value: int) -> None:
    retained = unique_preserve_order([*_ids(props.get("retained_detached_swsd_road_ids")), *retained_road_ids])
    props["retained_detached_swsd_road_ids"] = retained
    props["removed_swsd_road_ids"] = [road_id for road_id in _ids(props.get("removed_swsd_road_ids")) if road_id not in set(retained)]
    props["frcsd_road_ids"] = unique_preserve_order([*_ids(props.get("frcsd_road_ids")), *retained])
    props["frcsd_road_source_values"] = unique_preserve_order([*_ids(props.get("frcsd_road_source_values")), str(swsd_source_value)])
    props["relation_status"] = "replaced+retained_swsd"
    props["relation_reason"] = GROUP_COVERAGE_FALLBACK_REASON
    props["source_mix"] = "+".join(
        unique_preserve_order([*_source_mix_values(props.get("source_mix")), f"source_{swsd_source_value}"])
    )
    props["risk_flags"] = unique_preserve_order(
        [
            *_ids(props.get("risk_flags")),
            "retained_swsd_topology_supplement",
            "retained_swsd_excluded_from_formal_replacement",
            GROUP_COVERAGE_FALLBACK_RISK,
        ]
    )


def _mark_unit(unit: Any | None, retained_road_ids: list[str], retained_node_ids: list[str]) -> None:
    if unit is None:
        return
    retained_road_set = set(retained_road_ids)
    retained_node_set = set(retained_node_ids)
    unit.swsd_road_ids = [road_id for road_id in getattr(unit, "swsd_road_ids", []) if road_id not in retained_road_set]
    unit.removed_swsd_node_ids = [node_id for node_id in getattr(unit, "removed_swsd_node_ids", []) if node_id not in retained_node_set]
    unit.retained_detached_swsd_road_ids = unique_preserve_order(
        [*getattr(unit, "retained_detached_swsd_road_ids", []), *retained_road_ids]
    )
    unit.risk_flags = unique_preserve_order([*getattr(unit, "risk_flags", []), GROUP_COVERAGE_FALLBACK_RISK])


def _append_segment(row: dict[str, Any], segment_id: str) -> None:
    props = row.setdefault("properties", {})
    props["t06_swsd_segment_ids"] = unique_preserve_order([*_ids(props.get("t06_swsd_segment_ids")), segment_id])


def _with_source(item: dict[str, Any], source_field_name: str, source_value: int, segment_id: str) -> dict[str, Any]:
    props = dict(item.get("properties") or {})
    props[source_field_name] = source_value
    props["t06_swsd_segment_ids"] = unique_preserve_order([*_ids(props.get("t06_swsd_segment_ids")), segment_id])
    return feature(props, item.get("geometry"))


def _road_endpoint_node_ids(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    result: list[str] = []
    for field in ("snodeid", "enodeid"):
        value = _safe_id(props.get(field))
        if value:
            result.append(value)
    return unique_preserve_order(result)


def _feature_id(row: dict[str, Any]) -> str:
    return _safe_id((row.get("properties") or {}).get("id"))


def _source_key(row: dict[str, Any], source_field_name: str) -> str:
    return str((row.get("properties") or {}).get(source_field_name))


def _ids(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]
        text = str(value or "")
        if "+" in text:
            return [item for item in text.split("+") if item]
        return []


def _safe_id(value: Any) -> str:
    if value in (None, "", "None"):
        return ""
    try:
        return normalize_id(value)
    except ParseError:
        return str(value)


def _source_mix_values(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return [item for item in str(value or "").split("+") if item]


def _stats(
    segments: list[str],
    roads: list[str],
    nodes: list[str],
    split_sync_stats: dict[str, int],
) -> dict[str, Any]:
    return {
        "group_path_corridor_coverage_fallback_segment_count": len(unique_preserve_order(segments)),
        "group_path_corridor_coverage_fallback_swsd_road_count": len(unique_preserve_order(roads)),
        "group_path_corridor_coverage_fallback_swsd_node_count": len(unique_preserve_order(nodes)),
        "group_path_corridor_coverage_fallback_segments": unique_preserve_order(segments),
        **split_sync_stats,
    }
