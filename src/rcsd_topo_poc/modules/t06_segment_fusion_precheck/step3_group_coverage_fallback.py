from __future__ import annotations

from typing import Any

from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order
from .schemas import feature
from .step3_relation_node_map import sync_retained_swsd_carrier_mainnodes
from .step3_topology_connectivity_audit import build_topology_connectivity_audit_rows


GROUP_COVERAGE_FALLBACK_RISK = "group_path_corridor_local_coverage_retained_swsd"
GROUP_COVERAGE_FALLBACK_REASON = "group_path_corridor_local_coverage_retained_swsd"
GROUP_DIRECTIONALITY_FALLBACK_RISK = "group_path_corridor_directionality_retained_swsd"
GROUP_DIRECTIONALITY_FALLBACK_REASON = "group_path_corridor_directionality_retained_swsd"
GROUP_SOURCE_NOT_FORMAL_REPLACEABLE_REASON = "path_corridor_source_segment_not_formal_replaceable"
_GROUP_LOCAL_COVERAGE_REASON = "group_path_corridor_segment_local_coverage_review"
_GROUP_DIRECTIONALITY_REASON = "dual_segment_pair_nodes_not_bidirectional"
_GROUP_REPLACEMENT_RISK = "group_path_corridor_replacement"


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
    fallback_audit_relation_rows = _relation_rows_for_group_fallback_audit(
        segment_relation_rows,
        swsd_source_value=swsd_source_value,
    )
    audit_rows = build_topology_connectivity_audit_rows(
        swsd_segments=swsd_segments,
        swsd_roads=swsd_roads,
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=fallback_audit_relation_rows,
        advance_right_audit_rows=advance_right_audit_rows,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    relation_by_segment = {str((row.get("properties") or {}).get("swsd_segment_id") or ""): row for row in segment_relation_rows}
    fallback_reasons = _fallback_segment_reasons(audit_rows, relation_by_segment)
    if not fallback_reasons:
        return _stats([], [], [], split_sync_stats, {}, {})

    swsd_road_by_id = {_feature_id(road): road for road in swsd_roads}
    swsd_node_by_id = {_feature_id(node): node for node in swsd_nodes}
    final_roads = {(_source_key(road, source_field_name), _feature_id(road)): road for road in frcsd_roads}
    final_nodes = {(_source_key(node, source_field_name), _feature_id(node)): node for node in frcsd_nodes}
    unit_by_segment = {str(getattr(unit, "segment_id", "")): unit for unit in units}

    retained_roads: list[str] = []
    retained_nodes: list[str] = []
    retained_segments: list[str] = []
    blocked_missing_maps: list[str] = []
    source_not_formal_retained: list[str] = []
    for segment_id, fallback_reason in fallback_reasons.items():
        relation = relation_by_segment.get(segment_id)
        if relation is None:
            continue
        props = relation.setdefault("properties", {})
        road_ids = _ids(props.get("swsd_road_ids")) or _ids(props.get("removed_swsd_road_ids"))
        present_roads = [road_id for road_id in road_ids if road_id in swsd_road_by_id]
        if not present_roads:
            continue
        unit = unit_by_segment.get(segment_id)
        has_retained_endpoint_maps = _has_retained_endpoint_relation_maps(props, present_roads, swsd_road_by_id)
        if fallback_reason == GROUP_COVERAGE_FALLBACK_REASON and not has_retained_endpoint_maps:
            blocked_missing_maps.append(segment_id)
            continue
        if fallback_reason == GROUP_COVERAGE_FALLBACK_REASON and _unit_has_risk(
            unit, GROUP_SOURCE_NOT_FORMAL_REPLACEABLE_REASON
        ):
            segment_retained_nodes = _retain_swsd_features(
                segment_id,
                present_roads,
                swsd_road_by_id,
                swsd_node_by_id,
                final_roads,
                final_nodes,
                frcsd_roads,
                frcsd_nodes,
                removed_road_to_segments,
                removed_node_to_segments,
                source_field_name,
                swsd_source_value,
            )
            _release_unreferenced_rcsd_roads(
                segment_id,
                _ids(props.get("frcsd_road_ids")),
                segment_relation_rows,
                frcsd_roads,
                final_roads,
                source_field_name,
                rcsd_source_value,
            )
            _mark_unit_retained_swsd(unit, present_roads, segment_retained_nodes, GROUP_SOURCE_NOT_FORMAL_REPLACEABLE_REASON)
            _mark_relation_retained_swsd(
                props,
                present_roads,
                swsd_source_value,
                GROUP_SOURCE_NOT_FORMAL_REPLACEABLE_REASON,
            )
            source_not_formal_retained.append(segment_id)
            continue
        retained_segments.append(segment_id)
        segment_retained_nodes = _retain_swsd_features(
            segment_id,
            present_roads,
            swsd_road_by_id,
            swsd_node_by_id,
            final_roads,
            final_nodes,
            frcsd_roads,
            frcsd_nodes,
            removed_road_to_segments,
            removed_node_to_segments,
            source_field_name,
            swsd_source_value,
        )
        retained_roads.extend(present_roads)
        retained_nodes.extend(segment_retained_nodes)
        fallback_risk = _fallback_risk(fallback_reason)
        _mark_unit(unit_by_segment.get(segment_id), present_roads, segment_retained_nodes, fallback_risk)
        _mark_relation(props, present_roads, swsd_source_value, fallback_reason, fallback_risk)

    mainnode_sync_stats = sync_retained_swsd_carrier_mainnodes(
        segment_relation_rows,
        frcsd_roads,
        frcsd_nodes,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    source_not_formal_risk_pruned_count = _prune_source_not_formal_relation_risk(
        segment_relation_rows,
        source_not_formal_retained,
    )
    return _stats(
        retained_segments,
        retained_roads,
        retained_nodes,
        split_sync_stats,
        mainnode_sync_stats,
        fallback_reasons,
        blocked_missing_maps,
        source_not_formal_retained,
        source_not_formal_risk_pruned_count,
    )


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


def _relation_rows_for_group_fallback_audit(
    rows: list[dict[str, Any]],
    *,
    swsd_source_value: int,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    swsd_source = str(swsd_source_value)
    swsd_source_mix = f"source_{swsd_source}"
    for row in rows:
        props = dict(row.get("properties") or {})
        if _is_group_path_corridor_relation({"properties": props}):
            retained_ids = set(_ids(props.get("retained_detached_swsd_road_ids")))
            current_ids = _ids(props.get("frcsd_road_ids"))
            formal_ids = [road_id for road_id in current_ids if road_id not in retained_ids]
            if formal_ids != current_ids:
                props["frcsd_road_ids"] = formal_ids
                props["frcsd_road_source_values"] = [
                    int(value) if value.isdigit() else value
                    for value in unique_preserve_order(
                        [value for value in _ids(props.get("frcsd_road_source_values")) if value != swsd_source]
                    )
                ]
                props["source_mix"] = "+".join(
                    unique_preserve_order(
                        [value for value in _source_mix_values(props.get("source_mix")) if value != swsd_source_mix]
                    )
                )
        result.append(feature(props, row.get("geometry")))
    return result


def _fallback_segment_reasons(
    audit_rows: list[dict[str, Any]],
    relation_by_segment: dict[str, dict[str, Any]],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in audit_rows:
        props = row.get("properties") or {}
        if props.get("audit_layer") != "segment_internal_connectivity":
            continue
        segment_id = str(props.get("swsd_segment_id") or "")
        if not segment_id:
            continue
        relation = relation_by_segment.get(segment_id)
        if not _is_group_path_corridor_relation(relation):
            continue
        audit_reason = props.get("audit_reason")
        if audit_reason == _GROUP_LOCAL_COVERAGE_REASON:
            result.setdefault(segment_id, GROUP_COVERAGE_FALLBACK_REASON)
        elif audit_reason == _GROUP_DIRECTIONALITY_REASON:
            result.setdefault(segment_id, GROUP_DIRECTIONALITY_FALLBACK_REASON)
    return result


def _is_group_path_corridor_relation(relation: dict[str, Any] | None) -> bool:
    props = (relation or {}).get("properties") or {}
    return props.get("relation_reason") == _GROUP_REPLACEMENT_RISK or _GROUP_REPLACEMENT_RISK in _ids(props.get("risk_flags"))


def _fallback_risk(fallback_reason: str) -> str:
    if fallback_reason == GROUP_DIRECTIONALITY_FALLBACK_REASON:
        return GROUP_DIRECTIONALITY_FALLBACK_RISK
    return GROUP_COVERAGE_FALLBACK_RISK


def _has_retained_endpoint_relation_maps(
    props: dict[str, Any],
    retained_road_ids: list[str],
    swsd_road_by_id: dict[str, dict[str, Any]],
) -> bool:
    endpoint_nodes: list[str] = []
    for road_id in retained_road_ids:
        endpoint_nodes.extend(_road_endpoint_node_ids(swsd_road_by_id.get(road_id, {})))
    if not endpoint_nodes:
        return False
    return set(endpoint_nodes).issubset(_mapped_swsd_node_ids(props.get("swsd_to_frcsd_node_map")))


def _unit_has_risk(unit: Any | None, risk_flag: str) -> bool:
    if unit is None:
        return False
    return risk_flag in set(_ids(getattr(unit, "risk_flags", [])))


def _mapped_swsd_node_ids(value: Any) -> set[str]:
    if isinstance(value, str):
        try:
            value = parse_id_list(value, allow_empty=True)
        except ParseError:
            return set()
    result: set[str] = set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        node_id = _safe_id(item.get("swsd_node_id"))
        if node_id and _ids(item.get("frcsd_node_ids")):
            result.add(node_id)
    return result


def _retain_swsd_features(
    segment_id: str,
    present_roads: list[str],
    swsd_road_by_id: dict[str, dict[str, Any]],
    swsd_node_by_id: dict[str, dict[str, Any]],
    final_roads: dict[tuple[str, str], dict[str, Any]],
    final_nodes: dict[tuple[str, str], dict[str, Any]],
    frcsd_roads: list[dict[str, Any]],
    frcsd_nodes: list[dict[str, Any]],
    removed_road_to_segments: dict[str, list[str]],
    removed_node_to_segments: dict[str, list[str]],
    source_field_name: str,
    swsd_source_value: int,
) -> list[str]:
    retained_nodes: list[str] = []
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
        if road is None:
            continue
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
            if node is None:
                continue
            retained_nodes.append(node_id)
            removed_node_to_segments.pop(node_id, None)
    return unique_preserve_order(retained_nodes)


def _release_unreferenced_rcsd_roads(
    segment_id: str,
    rcsd_road_ids: list[str],
    segment_relation_rows: list[dict[str, Any]],
    frcsd_roads: list[dict[str, Any]],
    final_roads: dict[tuple[str, str], dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> None:
    if not rcsd_road_ids:
        return
    referenced_elsewhere = {
        road_id
        for row in segment_relation_rows
        if str((row.get("properties") or {}).get("swsd_segment_id") or "") != segment_id
        for road_id in _ids((row.get("properties") or {}).get("frcsd_road_ids"))
    }
    remove_row_ids: set[int] = set()
    for road_id in rcsd_road_ids:
        if road_id in referenced_elsewhere:
            continue
        key = (str(rcsd_source_value), road_id)
        row = final_roads.pop(key, None)
        if row is not None:
            remove_row_ids.add(id(row))
    if remove_row_ids:
        frcsd_roads[:] = [row for row in frcsd_roads if id(row) not in remove_row_ids]


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


def _mark_relation(
    props: dict[str, Any],
    retained_road_ids: list[str],
    swsd_source_value: int,
    fallback_reason: str,
    fallback_risk: str,
) -> None:
    retained = unique_preserve_order([*_ids(props.get("retained_detached_swsd_road_ids")), *retained_road_ids])
    props["retained_detached_swsd_road_ids"] = retained
    props["removed_swsd_road_ids"] = [road_id for road_id in _ids(props.get("removed_swsd_road_ids")) if road_id not in set(retained)]
    props["relation_reason"] = fallback_reason
    if fallback_reason == GROUP_DIRECTIONALITY_FALLBACK_REASON:
        props["frcsd_road_ids"] = retained
        props["frcsd_road_source_values"] = [swsd_source_value] if retained else []
        props["relation_status"] = "retained_swsd"
        props["source_mix"] = f"source_{swsd_source_value}" if retained else ""
        props["swsd_to_frcsd_node_map"] = _identity_pair_node_map(props)
        props["rcsd_pair_nodes"] = []
        props["rcsd_junc_nodes"] = []
    else:
        props["frcsd_road_ids"] = unique_preserve_order([*_ids(props.get("frcsd_road_ids")), *retained])
        props["frcsd_road_source_values"] = unique_preserve_order([*_ids(props.get("frcsd_road_source_values")), str(swsd_source_value)])
        props["relation_status"] = "replaced+retained_swsd"
        props["source_mix"] = "+".join(
            unique_preserve_order([*_source_mix_values(props.get("source_mix")), f"source_{swsd_source_value}"])
        )
    props["risk_flags"] = unique_preserve_order(
        [
            *_ids(props.get("risk_flags")),
            "retained_swsd_topology_supplement",
            "retained_swsd_excluded_from_formal_replacement",
            fallback_risk,
        ]
    )


def _mark_relation_retained_swsd(
    props: dict[str, Any],
    retained_road_ids: list[str],
    swsd_source_value: int,
    reason: str,
) -> None:
    retained = unique_preserve_order(retained_road_ids)
    props["retained_detached_swsd_road_ids"] = []
    props["removed_swsd_road_ids"] = []
    props["frcsd_road_ids"] = retained
    props["frcsd_road_source_values"] = [swsd_source_value] if retained else []
    props["relation_status"] = "retained_swsd"
    props["relation_reason"] = reason
    props["source_mix"] = f"source_{swsd_source_value}" if retained else ""
    props["swsd_to_frcsd_node_map"] = _identity_pair_node_map(props)
    props["rcsd_pair_nodes"] = []
    props["rcsd_junc_nodes"] = []
    props["risk_flags"] = unique_preserve_order([*_ids(props.get("risk_flags")), reason])


def _prune_source_not_formal_relation_risk(
    segment_relation_rows: list[dict[str, Any]],
    retained_segment_ids: list[str],
) -> int:
    retained_segment_set = set(retained_segment_ids)
    pruned_count = 0
    for row in segment_relation_rows:
        props = row.get("properties") or {}
        segment_id = str(props.get("swsd_segment_id") or "")
        if segment_id in retained_segment_set:
            continue
        risk_flags = _ids(props.get("risk_flags"))
        if GROUP_SOURCE_NOT_FORMAL_REPLACEABLE_REASON not in risk_flags:
            continue
        props["risk_flags"] = [
            risk_flag for risk_flag in risk_flags if risk_flag != GROUP_SOURCE_NOT_FORMAL_REPLACEABLE_REASON
        ]
        pruned_count += 1
    return pruned_count


def _identity_pair_node_map(props: dict[str, Any]) -> list[dict[str, Any]]:
    nodes = unique_preserve_order([*_ids(props.get("swsd_pair_nodes")), *_ids(props.get("swsd_junc_nodes"))])
    return [
        {
            "swsd_node_id": node_id,
            "frcsd_node_ids": [node_id],
            "node_role": "pair_node" if node_id in set(_ids(props.get("swsd_pair_nodes"))) else "junc_node",
            "mapping_status": "identity",
        }
        for node_id in nodes
    ]


def _mark_unit(unit: Any | None, retained_road_ids: list[str], retained_node_ids: list[str], fallback_risk: str) -> None:
    if unit is None:
        return
    retained_road_set = set(retained_road_ids)
    retained_node_set = set(retained_node_ids)
    unit.swsd_road_ids = [road_id for road_id in getattr(unit, "swsd_road_ids", []) if road_id not in retained_road_set]
    unit.removed_swsd_node_ids = [node_id for node_id in getattr(unit, "removed_swsd_node_ids", []) if node_id not in retained_node_set]
    unit.retained_detached_swsd_road_ids = unique_preserve_order(
        [*getattr(unit, "retained_detached_swsd_road_ids", []), *retained_road_ids]
    )
    unit.risk_flags = unique_preserve_order([*getattr(unit, "risk_flags", []), fallback_risk])


def _mark_unit_retained_swsd(unit: Any | None, retained_road_ids: list[str], retained_node_ids: list[str], reason: str) -> None:
    if unit is None:
        return
    unit.reason = reason
    unit.rcsd_road_ids = []
    unit.rcsd_node_ids = []
    unit.retained_node_ids = []
    unit.removed_swsd_node_ids = [node_id for node_id in getattr(unit, "removed_swsd_node_ids", []) if node_id not in set(retained_node_ids)]
    unit.retained_detached_swsd_road_ids = []
    unit.risk_flags = unique_preserve_order([*getattr(unit, "risk_flags", []), reason])


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
    mainnode_sync_stats: dict[str, int],
    fallback_reasons: dict[str, str],
    blocked_missing_maps: list[str] | None = None,
    source_not_formal_retained: list[str] | None = None,
    source_not_formal_risk_pruned_count: int = 0,
) -> dict[str, Any]:
    blocked_missing_maps = blocked_missing_maps or []
    source_not_formal_retained = source_not_formal_retained or []
    directionality_segments = [
        segment_id
        for segment_id in unique_preserve_order(segments)
        if fallback_reasons.get(segment_id) == GROUP_DIRECTIONALITY_FALLBACK_REASON
    ]
    return {
        "group_path_corridor_coverage_fallback_segment_count": len(unique_preserve_order(segments)),
        "group_path_corridor_coverage_fallback_swsd_road_count": len(unique_preserve_order(roads)),
        "group_path_corridor_coverage_fallback_swsd_node_count": len(unique_preserve_order(nodes)),
        "group_path_corridor_coverage_fallback_segments": unique_preserve_order(segments),
        "group_path_corridor_directionality_fallback_segment_count": len(directionality_segments),
        "group_path_corridor_directionality_fallback_segments": directionality_segments,
        "group_path_corridor_coverage_fallback_blocked_missing_relation_node_map_count": len(
            unique_preserve_order(blocked_missing_maps)
        ),
        "group_path_corridor_coverage_fallback_blocked_missing_relation_node_map_segments": unique_preserve_order(
            blocked_missing_maps
        ),
        "group_path_corridor_source_not_formal_retained_segment_count": len(
            unique_preserve_order(source_not_formal_retained)
        ),
        "group_path_corridor_source_not_formal_retained_segments": unique_preserve_order(source_not_formal_retained),
        "group_path_corridor_source_not_formal_relation_risk_pruned_count": source_not_formal_risk_pruned_count,
        **split_sync_stats,
        **{
            f"group_path_corridor_coverage_fallback_{key}": value
            for key, value in mainnode_sync_stats.items()
        },
    }
