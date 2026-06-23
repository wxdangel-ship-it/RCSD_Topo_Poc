from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any

from shapely.geometry import LineString, Point
from shapely.ops import substring, unary_union

from .parsing import ParseError, normalize_id, parse_id_list, unique_preserve_order
from .road_attributes import is_advance_right_turn_road


TOPOLOGY_SUPPLEMENT_SPLIT_REASON = "topology_supplement_from_swsd"
MIXED_REPLACEMENT_REQUIRES_SWSD_CARRIER_REASON = "mixed_replacement_requires_swsd_carrier"
MIXED_ADVANCE_RIGHT_RETAINED_SPLIT_REASON = "mixed_advance_right_retained_swsd_side"
FORMAL_REPLACEMENT_CORRIDOR_UNAVAILABLE_REASON = "formal_replacement_corridor_coverage_unavailable"
SEGMENT_CORRIDOR_BUFFER_M = 15.0
SEGMENT_MAX_UNCOVERED_RATIO = 0.05
SEGMENT_MIN_UNCOVERED_LENGTH_M = 20.0
EXISTING_ADVANCE_CORRIDOR_BUFFER_M = 5.0
EXISTING_ADVANCE_CORRIDOR_MIN_COVERAGE_RATIO = 0.85


def exclude_retained_swsd_carriers_from_formal_replacements(
    units: list[Any],
    *,
    added_road_to_segments: dict[str, list[str]],
    removed_road_to_segments: dict[str, list[str]],
    swsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> dict[str, int]:
    stats = {
        "excluded_road_count": 0,
        "deactivated_segment_count": 0,
        "deactivated_swsd_road_count": 0,
        "corridor_unavailable_segment_count": 0,
        "duplicate_unsegmented_advance_right_road_count": 0,
    }
    deactivated_segment_ids: set[str] = set()
    for unit in units:
        corridor_unavailable = _unit_corridor_coverage_unavailable(
            unit,
            swsd_road_by_id=swsd_road_by_id,
            rcsd_road_by_id=rcsd_road_by_id,
        )
        if not corridor_unavailable:
            continue
        stats["deactivated_segment_count"] += 1
        stats["corridor_unavailable_segment_count"] += 1
        unit.status = "failed"
        unit.reason = FORMAL_REPLACEMENT_CORRIDOR_UNAVAILABLE_REASON
        deactivated_segment_ids.add(str(getattr(unit, "segment_id", "")))
    if deactivated_segment_ids:
        for road_id, segment_ids in list(added_road_to_segments.items()):
            kept = [segment_id for segment_id in segment_ids if segment_id not in deactivated_segment_ids]
            if kept:
                added_road_to_segments[road_id] = kept
            else:
                del added_road_to_segments[road_id]
    extra_removed = _exclude_duplicate_unsegmented_advance_right_roads(
        added_road_to_segments=added_road_to_segments,
        removed_road_to_segments=removed_road_to_segments,
        swsd_road_by_id=swsd_road_by_id,
        rcsd_road_by_id=rcsd_road_by_id,
    )
    stats["duplicate_unsegmented_advance_right_road_count"] = len(extra_removed)
    stats["extra_removed_road_to_segments"] = extra_removed
    removed_road_to_segments.update(extra_removed)
    return stats


def _exclude_duplicate_unsegmented_advance_right_roads(
    *,
    added_road_to_segments: dict[str, list[str]],
    removed_road_to_segments: dict[str, list[str]],
    swsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    overlap_ratio_threshold: float = 0.5,
) -> dict[str, list[str]]:
    selected_geometries = [
        geometry
        for road in rcsd_road_by_id.values()
        for geometry in [_feature_line(road)]
        if geometry is not None
    ]
    if not selected_geometries:
        return {}
    selected_corridor = unary_union(selected_geometries).buffer(1.0)
    excluded: dict[str, list[str]] = {}
    for road_id, road in swsd_road_by_id.items():
        if road_id in removed_road_to_segments or not _is_advance_right_road(road):
            continue
        props = dict(road.get("properties") or {})
        if _road_segment_ids(road):
            continue
        line = _feature_line(road)
        if line is None or line.length <= 0:
            continue
        if _is_marked_mixed_advance_right_carrier(road):
            continue
        matching_rcsd_advance_ids = _matching_existing_rcsd_advance_road_ids(
            road,
            rcsd_road_by_id=rcsd_road_by_id,
        )
        matching_rcsd_covers = bool(matching_rcsd_advance_ids) and _is_covered_by_existing_rcsd_advance_corridor(
            road,
            rcsd_road_by_id=rcsd_road_by_id,
            selected_road_ids=matching_rcsd_advance_ids,
        )
        if not matching_rcsd_covers:
            props["t06_mixed_advance_right_carrier"] = 1
            road["properties"] = props
            continue
        if float(line.intersection(selected_corridor).length) / float(line.length) < overlap_ratio_threshold:
            continue
        excluded[road_id] = ["t06_duplicate_unsegmented_advance_right"]
    return excluded


def _unit_corridor_coverage_unavailable(
    unit: Any,
    *,
    swsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
) -> bool:
    unit_roads = [rcsd_road_by_id[road_id] for road_id in getattr(unit, "rcsd_road_ids", []) if road_id in rcsd_road_by_id]
    semantic_nodes = set(
        unique_preserve_order(
            [
                *(getattr(unit, "pair_nodes", []) or []),
                *(getattr(unit, "junc_nodes", []) or []),
                *(getattr(unit, "detached_junc_nodes", []) or []),
            ]
        )
    )
    if not unit_roads or not semantic_nodes:
        return False
    swsd_road_ids = [
        *(getattr(unit, "swsd_road_ids", []) or []),
        *(getattr(unit, "retained_detached_swsd_road_ids", []) or []),
    ]
    for road_id in swsd_road_ids:
        swsd_road = swsd_road_by_id.get(str(road_id))
        if _is_side_attachment_swsd_road(swsd_road):
            continue
        endpoints = _road_endpoint_node_ids(swsd_road)
        if len(endpoints) < 2 or not all(endpoint in semantic_nodes for endpoint in endpoints[:2]):
            continue
        if not _corridor_coverage_failed(swsd_road, unit_roads):
            continue
        return True
    return False


def _corridor_coverage_failed(swsd_road: dict[str, Any] | None, rcsd_roads: list[dict[str, Any]]) -> bool:
    line = _feature_line(swsd_road) if swsd_road is not None else None
    if line is None or line.length <= 0:
        return False
    geometries = [
        geometry
        for road in rcsd_roads
        for geometry in [_feature_line(road)]
        if geometry is not None
    ]
    if not geometries:
        return True
    uncovered = line.difference(unary_union(geometries).buffer(SEGMENT_CORRIDOR_BUFFER_M))
    uncovered_length = float(uncovered.length)
    uncovered_ratio = uncovered_length / float(line.length)
    return uncovered_ratio > SEGMENT_MAX_UNCOVERED_RATIO and uncovered_length > SEGMENT_MIN_UNCOVERED_LENGTH_M


def materialize_topology_supplement_rcsd_roads(
    units: list[Any],
    *,
    swsd_road_by_id: dict[str, dict[str, Any]],
    swsd_node_by_id: dict[str, dict[str, Any]],
    rcsd_roads: list[dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    attachment_audit_rows: list[dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
    source_field_name: str,
    rcsd_source_value: int,
    retained_swsd_roads: list[dict[str, Any]] | None = None,
) -> dict[str, int]:
    attachment_nodes = _attachment_nodes_by_swsd_road_endpoint(attachment_audit_rows)
    attachment_segment_ids = _replacement_segment_ids_by_swsd_road(attachment_audit_rows)
    units_by_segment = {str(getattr(unit, "segment_id", "")): unit for unit in units}
    incident_segments_by_node = _incident_segment_ids_by_node(swsd_road_by_id.values())
    replacement_segment_ids = set(units_by_segment)
    used_road_ids = set(swsd_road_by_id) | set(rcsd_road_by_id)
    stats = {
        "candidate_road_count": 0,
        "materialized_road_count": 0,
        "missing_attachment_node_count": 0,
        "detached_carrier_preserved_count": 0,
        "non_advance_carrier_preserved_count": 0,
        "reused_existing_rcsd_advance_count": 0,
        "recovered_undercovered_mixed_advance_right_count": 0,
        "mixed_advance_right_boundary_split_count": 0,
        "mixed_advance_right_retained_side_rcsd_excluded_count": 0,
    }
    materialized_source_road_ids: set[str] = set()
    mixed_boundary_split_source_road_ids: set[str] = set()
    recovered_count = _recover_undercovered_mixed_advance_right_carriers(
        units,
        swsd_road_by_id=swsd_road_by_id,
        rcsd_road_by_id=rcsd_road_by_id,
        attachment_segment_ids=attachment_segment_ids,
    )
    stats["recovered_undercovered_mixed_advance_right_count"] = recovered_count
    for unit in units:
        retained_ids = list(getattr(unit, "retained_detached_swsd_road_ids", []) or [])
        if not retained_ids:
            continue
        detached_nodes = set(getattr(unit, "detached_junc_nodes", []) or [])
        materialized_original_ids: list[str] = []
        materialized_rcsd_ids: list[str] = []
        still_retained: list[str] = []
        for road_id in retained_ids:
            road = swsd_road_by_id.get(str(road_id))
            endpoints = _road_endpoint_node_ids(road)
            if road is None or _touches_detached_node(endpoints, detached_nodes):
                still_retained.append(road_id)
                if road is not None:
                    stats["detached_carrier_preserved_count"] += 1
                continue
            if not _is_advance_right_road(road):
                still_retained.append(road_id)
                stats["non_advance_carrier_preserved_count"] += 1
                continue
            stats["candidate_road_count"] += 1
            existing_rcsd_advance_ids = _matching_existing_rcsd_advance_road_ids(
                road,
                rcsd_road_by_id=rcsd_road_by_id,
            )
            use_replaced_rcsd_group = _can_use_existing_rcsd_advance_group_for_replaced_carrier(
                road,
                rcsd_advance_road_ids=existing_rcsd_advance_ids,
                replacement_segment_ids=replacement_segment_ids,
                incident_segments_by_node=incident_segments_by_node,
            )
            if existing_rcsd_advance_ids:
                split_rcsd_advance_ids = _split_mixed_advance_right_retained_side(
                    road,
                    rcsd_advance_road_ids=existing_rcsd_advance_ids,
                    replacement_segment_ids=replacement_segment_ids,
                    incident_segments_by_node=incident_segments_by_node,
                    rcsd_road_by_id=rcsd_road_by_id,
                    rcsd_node_by_id=rcsd_node_by_id,
                )
                if split_rcsd_advance_ids:
                    for rcsd_road_id in split_rcsd_advance_ids:
                        added_road_to_segments[rcsd_road_id] = unique_preserve_order(
                            [*added_road_to_segments.get(rcsd_road_id, []), getattr(unit, "segment_id", "")]
                        )
                    unit.rcsd_road_ids = unique_preserve_order([*unit.rcsd_road_ids, *split_rcsd_advance_ids])
                    if str(road_id) not in mixed_boundary_split_source_road_ids:
                        mixed_boundary_split_source_road_ids.add(str(road_id))
                        stats["mixed_advance_right_boundary_split_count"] += 1
                        stats["mixed_advance_right_retained_side_rcsd_excluded_count"] += max(
                            0, len(existing_rcsd_advance_ids) - len(split_rcsd_advance_ids)
                        )
                    stats["reused_existing_rcsd_advance_count"] += len(split_rcsd_advance_ids)
                    continue
                if _is_undercovered_mixed_advance_right_carrier(
                    road,
                    rcsd_road_by_id=rcsd_road_by_id,
                    selected_road_ids=unit.rcsd_road_ids,
                ) and not use_replaced_rcsd_group:
                    still_retained.append(road_id)
                    road.setdefault("properties", {})["t06_mixed_advance_right_carrier"] = 1
                    unit.rcsd_road_ids = unique_preserve_order([*unit.rcsd_road_ids, *existing_rcsd_advance_ids])
                    for rcsd_road_id in existing_rcsd_advance_ids:
                        added_road_to_segments[rcsd_road_id] = unique_preserve_order(
                            [*added_road_to_segments.get(rcsd_road_id, []), getattr(unit, "segment_id", "")]
                        )
                    stats["reused_existing_rcsd_advance_count"] += len(existing_rcsd_advance_ids)
                    continue
                if use_replaced_rcsd_group:
                    road.setdefault("properties", {}).pop("t06_mixed_advance_right_carrier", None)
                _reuse_existing_rcsd_advance_roads(
                    unit,
                    road_id=road_id,
                    rcsd_road_ids=existing_rcsd_advance_ids,
                    added_road_to_segments=added_road_to_segments,
                )
                materialized_original_ids.append(road_id)
                materialized_source_road_ids.add(str(road_id))
                stats["reused_existing_rcsd_advance_count"] += len(existing_rcsd_advance_ids)
                continue
            if _is_undercovered_mixed_advance_right_carrier(
                road,
                rcsd_road_by_id=rcsd_road_by_id,
                selected_road_ids=unit.rcsd_road_ids,
            ) and not use_replaced_rcsd_group:
                still_retained.append(road_id)
                continue
            mapped_nodes = [
                _mapped_rcsd_node_id(road_id, endpoint, attachment_nodes, swsd_node_by_id, rcsd_node_by_id)
                for endpoint in endpoints[:2]
            ]
            if len(mapped_nodes) < 2 or not all(mapped_nodes):
                still_retained.append(road_id)
                stats["missing_attachment_node_count"] += 1
                continue
            new_id = _next_generated_road_id(road_id, used_road_ids)
            new_road = _topology_supplement_road(
                road,
                new_id=new_id,
                original_id=road_id,
                mapped_node_ids=[str(mapped_nodes[0]), str(mapped_nodes[1])],
                rcsd_node_by_id=rcsd_node_by_id,
                source_field_name=source_field_name,
                rcsd_source_value=rcsd_source_value,
            )
            if new_road is None:
                still_retained.append(road_id)
                stats["missing_attachment_node_count"] += 1
                continue
            rcsd_roads.append(new_road)
            rcsd_road_by_id[new_id] = new_road
            added_road_to_segments[new_id] = unique_preserve_order(
                [*added_road_to_segments.get(new_id, []), getattr(unit, "segment_id", "")]
            )
            materialized_original_ids.append(road_id)
            materialized_rcsd_ids.append(new_id)
            materialized_source_road_ids.add(str(road_id))
            used_road_ids.add(new_id)
        if materialized_rcsd_ids:
            unit.swsd_road_ids = unique_preserve_order([*unit.swsd_road_ids, *materialized_original_ids])
            stats["materialized_road_count"] += len(materialized_rcsd_ids)
        unit.retained_detached_swsd_road_ids = unique_preserve_order(still_retained)
    if retained_swsd_roads:
        for road in retained_swsd_roads:
            road_id = _safe_id((road.get("properties") or {}).get("id"))
            if not road_id or road_id in materialized_source_road_ids or not _is_advance_right_road(road):
                continue
            segment_ids = [segment_id for segment_id in attachment_segment_ids.get(road_id, []) if segment_id in units_by_segment]
            if not segment_ids:
                continue
            endpoints = _road_endpoint_node_ids(road)
            is_attachment_carrier = not _road_segment_ids(road)
            is_mixed_carrier = _is_mixed_advance_right_carrier(
                road,
                replacement_segment_ids=replacement_segment_ids,
                incident_segments_by_node=incident_segments_by_node,
            )
            existing_rcsd_advance_ids = _matching_existing_rcsd_advance_road_ids(
                road,
                rcsd_road_by_id=rcsd_road_by_id,
            )
            use_replaced_rcsd_group = _can_use_existing_rcsd_advance_group_for_replaced_carrier(
                road,
                rcsd_advance_road_ids=existing_rcsd_advance_ids,
                replacement_segment_ids=replacement_segment_ids,
                incident_segments_by_node=incident_segments_by_node,
            )
            selected_unit_rcsd_road_ids = unique_preserve_order(
                road_id
                for segment_id in segment_ids
                for road_id in getattr(units_by_segment[segment_id], "rcsd_road_ids", [])
            )
            selected_existing_rcsd_advance_ids = [
                road_id
                for road_id in existing_rcsd_advance_ids
                if road_id in selected_unit_rcsd_road_ids
            ]
            coverage_rcsd_advance_ids = (
                selected_existing_rcsd_advance_ids
                if selected_existing_rcsd_advance_ids
                else existing_rcsd_advance_ids
            )
            attachment_endpoint_count = len(
                {
                    endpoint
                    for endpoint in endpoints[:2]
                    if attachment_nodes.get((road_id, endpoint))
                }
            )
            preserve_multi_endpoint_carrier = (
                is_attachment_carrier
                and attachment_endpoint_count >= 2
                and len(segment_ids) > 1
            )
            keep_mixed_carrier = (
                not use_replaced_rcsd_group
                and bool(coverage_rcsd_advance_ids)
                and (is_mixed_carrier or is_attachment_carrier)
                and (
                    preserve_multi_endpoint_carrier
                    or not _is_covered_by_existing_rcsd_advance_corridor(
                        road,
                        rcsd_road_by_id=rcsd_road_by_id,
                        selected_road_ids=coverage_rcsd_advance_ids,
                    )
                )
            )
            split_mixed_rcsd_advance_ids: list[str] = []
            if is_mixed_carrier and existing_rcsd_advance_ids:
                split_mixed_rcsd_advance_ids = _split_mixed_advance_right_retained_side(
                    road,
                    rcsd_advance_road_ids=existing_rcsd_advance_ids,
                    replacement_segment_ids=replacement_segment_ids,
                    incident_segments_by_node=incident_segments_by_node,
                    rcsd_road_by_id=rcsd_road_by_id,
                    rcsd_node_by_id=rcsd_node_by_id,
                )
            if keep_mixed_carrier:
                road.setdefault("properties", {})["t06_mixed_advance_right_carrier"] = 1
            elif use_replaced_rcsd_group:
                road.setdefault("properties", {}).pop("t06_mixed_advance_right_carrier", None)
            stats["candidate_road_count"] += 1
            if existing_rcsd_advance_ids:
                selected_rcsd_ids = split_mixed_rcsd_advance_ids or existing_rcsd_advance_ids
                for segment_id in segment_ids:
                    unit = units_by_segment[segment_id]
                    if split_mixed_rcsd_advance_ids:
                        pass
                    elif keep_mixed_carrier:
                        unit.retained_detached_swsd_road_ids = unique_preserve_order(
                            [*unit.retained_detached_swsd_road_ids, road_id]
                        )
                    else:
                        unit.swsd_road_ids = unique_preserve_order([*unit.swsd_road_ids, road_id])
                    unit.rcsd_road_ids = unique_preserve_order([*unit.rcsd_road_ids, *selected_rcsd_ids])
                for rcsd_road_id in selected_rcsd_ids:
                    added_road_to_segments[rcsd_road_id] = unique_preserve_order(
                        [*added_road_to_segments.get(rcsd_road_id, []), *segment_ids]
                    )
                if split_mixed_rcsd_advance_ids and str(road_id) not in mixed_boundary_split_source_road_ids:
                    mixed_boundary_split_source_road_ids.add(str(road_id))
                    stats["mixed_advance_right_boundary_split_count"] += 1
                    stats["mixed_advance_right_retained_side_rcsd_excluded_count"] += max(
                        0, len(existing_rcsd_advance_ids) - len(split_mixed_rcsd_advance_ids)
                    )
                stats["reused_existing_rcsd_advance_count"] += len(selected_rcsd_ids)
                continue
            if keep_mixed_carrier:
                for segment_id in segment_ids:
                    unit = units_by_segment[segment_id]
                    unit.retained_detached_swsd_road_ids = unique_preserve_order(
                        [*unit.retained_detached_swsd_road_ids, road_id]
                    )
                continue
            mapped_nodes = [
                _mapped_rcsd_node_id(road_id, endpoint, attachment_nodes, swsd_node_by_id, rcsd_node_by_id)
                for endpoint in endpoints[:2]
            ]
            if len(mapped_nodes) < 2 or not all(mapped_nodes):
                stats["missing_attachment_node_count"] += 1
                continue
            new_id = _next_generated_road_id(road_id, used_road_ids)
            new_road = _topology_supplement_road(
                road,
                new_id=new_id,
                original_id=road_id,
                mapped_node_ids=[str(mapped_nodes[0]), str(mapped_nodes[1])],
                rcsd_node_by_id=rcsd_node_by_id,
                source_field_name=source_field_name,
                rcsd_source_value=rcsd_source_value,
            )
            if new_road is None:
                stats["missing_attachment_node_count"] += 1
                continue
            rcsd_roads.append(new_road)
            rcsd_road_by_id[new_id] = new_road
            added_road_to_segments[new_id] = unique_preserve_order([*added_road_to_segments.get(new_id, []), *segment_ids])
            for segment_id in segment_ids:
                unit = units_by_segment[segment_id]
                unit.swsd_road_ids = unique_preserve_order([*unit.swsd_road_ids, road_id])
            stats["materialized_road_count"] += 1
            materialized_source_road_ids.add(road_id)
            used_road_ids.add(new_id)
    return stats


def _recover_undercovered_mixed_advance_right_carriers(
    units: list[Any],
    *,
    swsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    attachment_segment_ids: dict[str, list[str]],
) -> int:
    recovered_count = 0
    for unit in units:
        kept_swsd_road_ids: list[str] = []
        recovered_road_ids: list[str] = []
        unit_segment_id = str(getattr(unit, "segment_id", ""))
        for road_id in getattr(unit, "swsd_road_ids", []) or []:
            road = swsd_road_by_id.get(str(road_id))
            if (
                road is None
                or not _is_advance_right_road(road)
                or _road_segment_ids(road)
                or unit_segment_id not in attachment_segment_ids.get(str(road_id), [])
                or _is_covered_by_existing_rcsd_advance_corridor(
                    road,
                    rcsd_road_by_id=rcsd_road_by_id,
                    selected_road_ids=getattr(unit, "rcsd_road_ids", []),
                )
            ):
                kept_swsd_road_ids.append(road_id)
                continue
            road.setdefault("properties", {})["t06_mixed_advance_right_carrier"] = 1
            recovered_road_ids.append(str(road_id))
        if not recovered_road_ids:
            continue
        unit.swsd_road_ids = unique_preserve_order(kept_swsd_road_ids)
        unit.retained_detached_swsd_road_ids = unique_preserve_order(
            [*getattr(unit, "retained_detached_swsd_road_ids", []), *recovered_road_ids]
        )
        recovered_count += len(recovered_road_ids)
    return recovered_count


def _is_undercovered_mixed_advance_right_carrier(
    road: dict[str, Any],
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    selected_road_ids: list[str] | None = None,
) -> bool:
    return _is_marked_mixed_advance_right_carrier(road) and not _is_covered_by_existing_rcsd_advance_corridor(
        road,
        rcsd_road_by_id=rcsd_road_by_id,
        selected_road_ids=selected_road_ids,
    )


def _is_marked_mixed_advance_right_carrier(road: dict[str, Any]) -> bool:
    props = dict(road.get("properties") or {})
    return str(props.get("t06_mixed_advance_right_carrier") or "").lower() in {"1", "true", "yes"}


def _split_mixed_advance_right_retained_side(
    road: dict[str, Any],
    *,
    rcsd_advance_road_ids: list[str],
    replacement_segment_ids: set[str],
    incident_segments_by_node: dict[str, list[str]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    props = road.setdefault("properties", {})
    if props.get("t06_mixed_advance_right_split_reason") == MIXED_ADVANCE_RIGHT_RETAINED_SPLIT_REASON:
        return _safe_id_list(props.get("t06_mixed_advance_right_rcsd_road_ids"))
    if (
        not rcsd_advance_road_ids
        or _road_segment_ids(road)
        or not _is_mixed_advance_right_carrier(
            road,
            replacement_segment_ids=replacement_segment_ids,
            incident_segments_by_node=incident_segments_by_node,
        )
    ):
        return []
    line = _feature_line(road)
    endpoints = _road_endpoint_node_ids(road)
    if line is None or line.length <= 0 or len(endpoints) < 2:
        return []
    retained_endpoint_indexes = [
        index
        for index, node_id in enumerate(endpoints[:2])
        if _endpoint_replacement_role(
            node_id,
            replacement_segment_ids=replacement_segment_ids,
            incident_segments_by_node=incident_segments_by_node,
        )
        == "retained"
    ]
    if len(retained_endpoint_indexes) != 1:
        return []
    retained_index = retained_endpoint_indexes[0]
    other_endpoint = endpoints[1 - retained_index]
    if _endpoint_replacement_role(
        other_endpoint,
        replacement_segment_ids=replacement_segment_ids,
        incident_segments_by_node=incident_segments_by_node,
    ) not in {"replaced", "mixed"}:
        return []
    boundary_node_id, boundary_point, boundary_measure = _nearest_rcsd_advance_boundary_node(
        line,
        retained_index=retained_index,
        rcsd_advance_road_ids=rcsd_advance_road_ids,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
    )
    if boundary_node_id is None or boundary_point is None or boundary_measure is None:
        return []
    replaced_side_rcsd_ids = _filter_replaced_side_rcsd_advance_ids(
        line,
        retained_index=retained_index,
        boundary_measure=boundary_measure,
        rcsd_advance_road_ids=rcsd_advance_road_ids,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
    )
    if not replaced_side_rcsd_ids:
        return []
    retained_line = _retained_side_subline(line, retained_index=retained_index, boundary_measure=boundary_measure)
    if retained_line is None or retained_line.length <= 0:
        return []
    retained_line = _snap_retained_side_boundary(retained_line, retained_index=retained_index, boundary_point=boundary_point)
    if retained_index == 0:
        props["enodeid"] = boundary_node_id
    else:
        props["snodeid"] = boundary_node_id
    props["t06_mixed_advance_right_carrier"] = 1
    props["t06_mixed_advance_right_split_reason"] = MIXED_ADVANCE_RIGHT_RETAINED_SPLIT_REASON
    props["t06_mixed_advance_right_boundary_node_id"] = boundary_node_id
    props["t06_mixed_advance_right_retained_endpoint_id"] = endpoints[retained_index]
    props["t06_mixed_advance_right_replaced_endpoint_id"] = other_endpoint
    props["t06_mixed_advance_right_rcsd_road_ids"] = replaced_side_rcsd_ids
    props["t06_mixed_advance_right_excluded_rcsd_road_ids"] = [
        road_id for road_id in unique_preserve_order(rcsd_advance_road_ids) if road_id not in set(replaced_side_rcsd_ids)
    ]
    road["geometry"] = retained_line
    return replaced_side_rcsd_ids


def _filter_replaced_side_rcsd_advance_ids(
    line: LineString,
    *,
    retained_index: int,
    boundary_measure: float,
    rcsd_advance_road_ids: list[str],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
) -> list[str]:
    result: list[str] = []
    epsilon = 0.01
    for road_id in unique_preserve_order(rcsd_advance_road_ids):
        measures = _rcsd_road_endpoint_measures_on_line(
            line,
            road_id=road_id,
            rcsd_road_by_id=rcsd_road_by_id,
            rcsd_node_by_id=rcsd_node_by_id,
        )
        if not measures:
            continue
        if retained_index == 0:
            if max(measures) > boundary_measure + epsilon:
                result.append(road_id)
        elif min(measures) < boundary_measure - epsilon:
            result.append(road_id)
    return result


def _rcsd_road_endpoint_measures_on_line(
    line: LineString,
    *,
    road_id: str,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
) -> list[float]:
    road = rcsd_road_by_id.get(str(road_id))
    candidate_line = _feature_line(road) if road is not None else None
    points = [
        point
        for node_id in _road_endpoint_node_ids(road)
        for point in [_node_point(rcsd_node_by_id.get(node_id))]
        if point is not None
    ]
    if not points and candidate_line is not None and len(candidate_line.coords) >= 2:
        points = [Point(candidate_line.coords[0][:2]), Point(candidate_line.coords[-1][:2])]
    return [float(line.project(point)) for point in points]


def _endpoint_replacement_role(
    node_id: str,
    *,
    replacement_segment_ids: set[str],
    incident_segments_by_node: dict[str, list[str]],
) -> str:
    segment_ids = incident_segments_by_node.get(node_id, [])
    touches_replaced = any(segment_id in replacement_segment_ids for segment_id in segment_ids)
    touches_retained = any(segment_id not in replacement_segment_ids for segment_id in segment_ids)
    if touches_replaced and touches_retained:
        return "mixed"
    if touches_replaced:
        return "replaced"
    if touches_retained:
        return "retained"
    return "none"


def _nearest_rcsd_advance_boundary_node(
    line: LineString,
    *,
    retained_index: int,
    rcsd_advance_road_ids: list[str],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
) -> tuple[str | None, Point | None, float | None]:
    retained_measure = 0.0 if retained_index == 0 else float(line.length)
    candidates: list[tuple[float, str, Point, float]] = []
    for road_id in rcsd_advance_road_ids:
        rcsd_road = rcsd_road_by_id.get(str(road_id))
        for node_id in _road_endpoint_node_ids(rcsd_road):
            point = _node_point(rcsd_node_by_id.get(node_id))
            if point is None:
                continue
            measure = float(line.project(point))
            if measure <= 0.0 or measure >= float(line.length):
                continue
            candidates.append((abs(measure - retained_measure), node_id, point, measure))
    if not candidates:
        return None, None, None
    _distance, node_id, point, measure = min(candidates, key=lambda item: item[0])
    return node_id, point, measure


def _retained_side_subline(line: LineString, *, retained_index: int, boundary_measure: float) -> LineString | None:
    try:
        retained_line = (
            substring(line, 0.0, boundary_measure)
            if retained_index == 0
            else substring(line, boundary_measure, float(line.length))
        )
    except Exception:
        return None
    return retained_line if isinstance(retained_line, LineString) else None


def _snap_retained_side_boundary(line: LineString, *, retained_index: int, boundary_point: Point) -> LineString:
    coords = list(line.coords)
    if not coords:
        return line
    if retained_index == 0:
        coords[-1] = _coord_with_xy(coords[-1], boundary_point)
    else:
        coords[0] = _coord_with_xy(coords[0], boundary_point)
    return LineString(coords)


def _reuse_existing_rcsd_advance_roads(
    unit: Any,
    *,
    road_id: str,
    rcsd_road_ids: list[str],
    added_road_to_segments: dict[str, list[str]],
) -> None:
    segment_id = str(getattr(unit, "segment_id", ""))
    unit.swsd_road_ids = unique_preserve_order([*unit.swsd_road_ids, road_id])
    unit.rcsd_road_ids = unique_preserve_order([*unit.rcsd_road_ids, *rcsd_road_ids])
    for rcsd_road_id in rcsd_road_ids:
        added_road_to_segments[rcsd_road_id] = unique_preserve_order(
            [*added_road_to_segments.get(rcsd_road_id, []), segment_id]
        )


def _matching_existing_rcsd_advance_road_ids(
    swsd_road: dict[str, Any],
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    buffer_m: float = 1.0,
    overlap_ratio_threshold: float = 0.2,
) -> list[str]:
    line = _feature_line(swsd_road)
    if line is None or line.length <= 0:
        return []
    result: list[str] = []
    corridor_candidates: list[tuple[str, LineString]] = []
    for rcsd_road_id, rcsd_road in rcsd_road_by_id.items():
        props = dict(rcsd_road.get("properties") or {})
        if props.get("t06_split_reason") == TOPOLOGY_SUPPLEMENT_SPLIT_REASON:
            continue
        if not _is_advance_right_road(rcsd_road):
            continue
        rcsd_line = _feature_line(rcsd_road)
        if rcsd_line is None or rcsd_line.length <= 0:
            continue
        if line.distance(rcsd_line) <= EXISTING_ADVANCE_CORRIDOR_BUFFER_M:
            corridor_candidates.append((str(rcsd_road_id), rcsd_line))
        if line.distance(rcsd_line) <= buffer_m:
            swsd_overlap = line.intersection(rcsd_line.buffer(buffer_m, cap_style=2)).length / line.length
            rcsd_overlap = rcsd_line.intersection(line.buffer(buffer_m, cap_style=2)).length / rcsd_line.length
            if max(float(swsd_overlap), float(rcsd_overlap)) >= overlap_ratio_threshold:
                result.append(str(rcsd_road_id))
    if result:
        return _expand_connected_existing_rcsd_advance_road_ids(
            swsd_road,
            rcsd_road_by_id=rcsd_road_by_id,
            seed_road_ids=unique_preserve_order(result),
        )
    if not corridor_candidates:
        return []
    corridor = unary_union([candidate_line for _, candidate_line in corridor_candidates])
    covered_ratio = line.intersection(
        corridor.buffer(EXISTING_ADVANCE_CORRIDOR_BUFFER_M, cap_style=2)
    ).length / line.length
    if float(covered_ratio) < EXISTING_ADVANCE_CORRIDOR_MIN_COVERAGE_RATIO:
        return []
    return _expand_connected_existing_rcsd_advance_road_ids(
        swsd_road,
        rcsd_road_by_id=rcsd_road_by_id,
        seed_road_ids=unique_preserve_order(
            road_id
            for road_id, candidate_line in corridor_candidates
            if candidate_line.intersection(line.buffer(EXISTING_ADVANCE_CORRIDOR_BUFFER_M, cap_style=2)).length > 0
        ),
    )


def _expand_connected_existing_rcsd_advance_road_ids(
    swsd_road: dict[str, Any],
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    seed_road_ids: list[str],
) -> list[str]:
    line = _feature_line(swsd_road)
    if line is None or not seed_road_ids:
        return unique_preserve_order(seed_road_ids)
    node_to_roads: dict[str, list[str]] = defaultdict(list)
    for road_id, road in rcsd_road_by_id.items():
        props = dict(road.get("properties") or {})
        if props.get("t06_split_reason") == TOPOLOGY_SUPPLEMENT_SPLIT_REASON:
            continue
        if not _is_advance_right_road(road):
            continue
        for node_id in _road_endpoint_node_ids(road):
            node_to_roads[node_id].append(str(road_id))
    result = unique_preserve_order(seed_road_ids)
    visited = set(result)
    queue = list(result)
    while queue:
        road_id = queue.pop(0)
        road = rcsd_road_by_id.get(road_id)
        if road is None:
            continue
        for node_id in _road_endpoint_node_ids(road):
            for candidate_id in node_to_roads.get(node_id, []):
                if candidate_id in visited:
                    continue
                candidate = rcsd_road_by_id.get(candidate_id)
                candidate_line = _feature_line(candidate) if candidate is not None else None
                if candidate_line is None or line.distance(candidate_line) > EXISTING_ADVANCE_CORRIDOR_BUFFER_M:
                    continue
                visited.add(candidate_id)
                result.append(candidate_id)
                queue.append(candidate_id)
    return result


def _is_covered_by_existing_rcsd_advance_corridor(
    swsd_road: dict[str, Any],
    *,
    rcsd_road_by_id: dict[str, dict[str, Any]],
    selected_road_ids: list[str] | None = None,
) -> bool:
    line = _feature_line(swsd_road)
    if line is None or line.length <= 0:
        return False
    selected = {str(road_id) for road_id in selected_road_ids or []}
    candidates: list[LineString] = []
    for rcsd_road_id, rcsd_road in rcsd_road_by_id.items():
        if selected and str(rcsd_road_id) not in selected:
            continue
        props = dict(rcsd_road.get("properties") or {})
        if props.get("t06_split_reason") == TOPOLOGY_SUPPLEMENT_SPLIT_REASON:
            continue
        if not _is_advance_right_road(rcsd_road):
            continue
        candidate = _feature_line(rcsd_road)
        if candidate is None or candidate.length <= 0:
            continue
        if line.distance(candidate) <= EXISTING_ADVANCE_CORRIDOR_BUFFER_M:
            candidates.append(candidate)
    if not candidates:
        return False
    corridor = unary_union(candidates).buffer(EXISTING_ADVANCE_CORRIDOR_BUFFER_M, cap_style=2)
    covered_ratio = float(line.intersection(corridor).length) / float(line.length)
    return covered_ratio >= EXISTING_ADVANCE_CORRIDOR_MIN_COVERAGE_RATIO


def _attachment_nodes_by_swsd_road_endpoint(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in rows:
        props = dict(row.get("properties") or {})
        action = str(props.get("action") or "")
        if not action.startswith(("split_", "reuse_")):
            continue
        road_id = _safe_id(props.get("swsd_road_id") or props.get("swsd_advance_road_id"))
        swsd_node_id = _safe_id(props.get("swsd_node_id"))
        rcsd_node_id = _safe_id(props.get("rcsd_node_id") or props.get("generated_rcsd_node_id"))
        if road_id and swsd_node_id and rcsd_node_id and rcsd_node_id not in result[(road_id, swsd_node_id)]:
            result[(road_id, swsd_node_id)].append(rcsd_node_id)
    return dict(result)


def _replacement_segment_ids_by_swsd_road(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        props = dict(row.get("properties") or {})
        action = str(props.get("action") or "")
        if not action.startswith(("split_", "reuse_")):
            continue
        road_id = _safe_id(props.get("swsd_road_id") or props.get("swsd_advance_road_id"))
        if not road_id:
            continue
        for segment_id in _safe_id_list(props.get("replacement_segment_ids")):
            if segment_id not in result[road_id]:
                result[road_id].append(segment_id)
    return dict(result)


def _mapped_rcsd_node_id(
    road_id: str,
    swsd_node_id: str,
    attachment_nodes: dict[tuple[str, str], list[str]],
    swsd_node_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
) -> str | None:
    candidates = attachment_nodes.get((str(road_id), str(swsd_node_id)), [])
    if candidates:
        return candidates[0]
    node = swsd_node_by_id.get(str(swsd_node_id))
    mainnode_id = _safe_id((node.get("properties") or {}).get("mainnodeid")) if node else None
    return mainnode_id if mainnode_id in rcsd_node_by_id else None


def _topology_supplement_road(
    swsd_road: dict[str, Any],
    *,
    new_id: str,
    original_id: str,
    mapped_node_ids: list[str],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, Any] | None:
    line = _feature_line(swsd_road)
    if line is None or len(mapped_node_ids) < 2:
        return None
    start_point = _node_point(rcsd_node_by_id.get(mapped_node_ids[0]))
    end_point = _node_point(rcsd_node_by_id.get(mapped_node_ids[1]))
    if start_point is None or end_point is None:
        return None
    props = dict(deepcopy(swsd_road.get("properties") or {}))
    props.update(
        {
            "id": new_id,
            "snodeid": mapped_node_ids[0],
            "enodeid": mapped_node_ids[1],
            source_field_name: rcsd_source_value,
            "source_road_id": str(original_id),
            "t06_split_original_road_id": str(original_id),
            "t06_split_reason": TOPOLOGY_SUPPLEMENT_SPLIT_REASON,
        }
    )
    return {"properties": props, "geometry": _line_with_snapped_endpoints(line, start_point, end_point)}


def _line_with_snapped_endpoints(line: LineString, start_point: Point, end_point: Point) -> LineString:
    coords = list(line.coords)
    if not coords:
        return line
    coords[0] = _coord_with_xy(coords[0], start_point)
    coords[-1] = _coord_with_xy(coords[-1], end_point)
    return LineString(coords)


def _coord_with_xy(original: tuple[float, ...], point: Point) -> tuple[float, ...]:
    x, y = point.coords[0][:2]
    return (x, y) if len(original) <= 2 else (x, y, *original[2:])


def _road_endpoint_node_ids(road: dict[str, Any] | None) -> list[str]:
    props = dict((road or {}).get("properties") or {})
    return [_safe_id(value) for value in (props.get("snodeid"), props.get("enodeid")) if _safe_id(value)]


def _road_segment_ids(road: dict[str, Any] | None) -> list[str]:
    props = dict((road or {}).get("properties") or {})
    return parse_id_list(
        props.get("segmentid") or props.get("segment_id") or props.get("swsd_segment_id"),
        allow_empty=True,
    )


def _incident_segment_ids_by_node(roads: Any) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for road in roads:
        segment_ids = _road_segment_ids(road)
        for node_id in _road_endpoint_node_ids(road):
            result[node_id] = unique_preserve_order([*result[node_id], *segment_ids])
    return dict(result)


def _is_mixed_advance_right_carrier(
    road: dict[str, Any],
    *,
    replacement_segment_ids: set[str],
    incident_segments_by_node: dict[str, list[str]],
) -> bool:
    endpoint_segments = [
        incident_segments_by_node.get(node_id, [])
        for node_id in _road_endpoint_node_ids(road)
    ]
    touches_replaced = any(segment_id in replacement_segment_ids for segments in endpoint_segments for segment_id in segments)
    touches_retained = any(segment_id not in replacement_segment_ids for segments in endpoint_segments for segment_id in segments)
    return touches_replaced and touches_retained


def _can_use_existing_rcsd_advance_group_for_replaced_carrier(
    road: dict[str, Any],
    *,
    rcsd_advance_road_ids: list[str],
    replacement_segment_ids: set[str],
    incident_segments_by_node: dict[str, list[str]],
) -> bool:
    if not rcsd_advance_road_ids or _road_segment_ids(road):
        return False
    endpoint_segments = unique_preserve_order(
        segment_id
        for node_id in _road_endpoint_node_ids(road)
        for segment_id in incident_segments_by_node.get(node_id, [])
    )
    return bool(endpoint_segments) and all(segment_id in replacement_segment_ids for segment_id in endpoint_segments)


def _touches_detached_node(endpoints: list[str], detached_nodes: set[str]) -> bool:
    return bool(detached_nodes.intersection(endpoints))


def _feature_line(feature: dict[str, Any]) -> LineString | None:
    geometry = feature.get("geometry")
    return geometry if isinstance(geometry, LineString) else None


def _is_advance_right_road(road: dict[str, Any]) -> bool:
    return is_advance_right_turn_road(dict(road.get("properties") or {}))


def _is_side_attachment_swsd_road(road: dict[str, Any] | None) -> bool:
    props = dict((road or {}).get("properties") or {})
    return str(props.get("segment_build_source") or "") == "side_attachment_merge"


def _node_point(node: dict[str, Any] | None) -> Point | None:
    geometry = node.get("geometry") if node is not None else None
    return geometry if isinstance(geometry, Point) else None


def _next_generated_road_id(original_id: str, used_road_ids: set[str]) -> str:
    index = 1
    while True:
        candidate = f"{original_id}__t06toposupp_{index}"
        if candidate not in used_road_ids:
            return candidate
        index += 1


def _safe_id(value: Any) -> str | None:
    try:
        return normalize_id(value)
    except ParseError:
        return None


def _safe_id_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value)
    except ParseError:
        return []
