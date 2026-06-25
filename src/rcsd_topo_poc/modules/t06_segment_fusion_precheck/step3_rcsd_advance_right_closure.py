from __future__ import annotations

from collections import defaultdict
from typing import Any

from shapely.geometry import LineString, Point
from shapely.ops import substring

from .graph_builders import NodeCanonicalizer
from .io import write_feature_triplet
from .parsing import ParseError, unique_preserve_order
from .road_attributes import is_advance_right_turn_road
from .schemas import feature
from .step3_advance_right_contract import (
    _apply_contract_split_points,
    _feature_id,
    _feature_line,
    _is_advance_right_rcsd_road,
    _nearest_preferred_rcsd_projection,
    _road_endpoint_node_ids,
)


RCSD_ADVANCE_RIGHT_CLOSURE_MAX_GAP_M = 20.0
RCSD_ADVANCE_RIGHT_ENDPOINT_REUSE_MAX_GAP_M = 1.0
RCSD_ADVANCE_RIGHT_RETAINED_SWSD_MAX_GAP_M = 20.0
RCSD_ADVANCE_RIGHT_RETAINED_SWSD_SPLIT_REASON = "rcsd_advance_right_retained_swsd_attachment"
FINAL_ADVANCE_RIGHT_CLOSURE_SPLIT_REASON = "final_advance_right_endpoint_attachment"
MIXED_ADVANCE_RIGHT_RETAINED_SPLIT_REASON = "mixed_advance_right_retained_swsd_side"
RCSD_ADVANCE_RIGHT_CLOSURE_AUDIT_STEM = "t06_step3_rcsd_advance_right_closure_audit"
RCSD_ADVANCE_RIGHT_CLOSURE_AUDIT_FIELDS = [
    "rcsd_advance_road_id",
    "rcsd_endpoint_node_id",
    "generated_swsd_node_id",
    "endpoint_index",
    "endpoint_degree",
    "audit_status",
    "action",
    "action_reason",
    "target_road_source",
    "target_rcsd_road_id",
    "target_swsd_road_id",
    "target_rcsd_node_id",
    "projected_gap_m",
    "replacement_segment_ids",
]


def write_rcsd_advance_right_closure_audit(step_root: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    return write_feature_triplet(
        step_root=step_root,
        stem=RCSD_ADVANCE_RIGHT_CLOSURE_AUDIT_STEM,
        features=rows,
        fieldnames=RCSD_ADVANCE_RIGHT_CLOSURE_AUDIT_FIELDS,
    )


def final_swsd_road_endpoint_ids(
    frcsd_roads: list[dict[str, Any]],
    source_field_name: str,
    swsd_source_value: int,
) -> set[str]:
    result: set[str] = set()
    for road in frcsd_roads:
        props = dict(road.get("properties") or {})
        if str(props.get(source_field_name) or "") != str(swsd_source_value):
            continue
        result.update(_road_endpoint_node_ids(road)[:2])
    return result


def apply_native_rcsd_advance_right_closure(
    units: list[Any],
    *,
    rcsd_roads: list[dict[str, Any]],
    rcsd_nodes: list[dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    rcsd_node_by_id: dict[str, dict[str, Any]],
    swsd_roads: list[dict[str, Any]] | None = None,
    swsd_nodes: list[dict[str, Any]] | None = None,
    swsd_road_by_id: dict[str, dict[str, Any]] | None = None,
    swsd_node_by_id: dict[str, dict[str, Any]] | None = None,
    retained_swsd_roads: list[dict[str, Any]] | None = None,
    added_road_to_segments: dict[str, list[str]],
    max_gap_m: float = RCSD_ADVANCE_RIGHT_CLOSURE_MAX_GAP_M,
) -> dict[str, Any]:
    selected_ids = [road_id for road_id in added_road_to_segments if road_id in rcsd_road_by_id]
    selected_set = set(selected_ids)
    canonicalizer = NodeCanonicalizer.from_node_features(rcsd_nodes)
    node_degree = _selected_canonical_node_degrees(
        selected_ids=selected_ids,
        rcsd_road_by_id=rcsd_road_by_id,
        canonicalizer=canonicalizer,
    )
    _add_mixed_retained_swsd_endpoint_degrees(
        node_degree,
        retained_swsd_roads=retained_swsd_roads or [],
        canonicalizer=canonicalizer,
    )
    split_points_by_road: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)
    swsd_split_points_by_road: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)
    audit_rows: list[dict[str, Any]] = []
    repaired_endpoint_count = 0
    failed_endpoint_count = 0
    generated_swsd_node_count = 0
    retained_swsd_road_by_id = {
        _feature_id(road): road
        for road in (retained_swsd_roads or [])
        if road is not None
    }
    swsd_node_id_seed = _next_numeric_id(swsd_node_by_id or {})

    for road_id in selected_ids:
        road = rcsd_road_by_id.get(road_id)
        if road is None or not _is_advance_right_rcsd_road(road):
            continue
        endpoint_ids = _road_endpoint_node_ids(road)
        endpoint_points = _road_endpoint_points(road)
        if len(endpoint_ids) < 2 or len(endpoint_points) < 2:
            continue
        for endpoint_index, (node_id, point) in enumerate(zip(endpoint_ids[:2], endpoint_points[:2])):
            canonical_id = _canonicalize(canonicalizer, node_id)
            degree = node_degree.get(canonical_id, 0)
            segment_ids = added_road_to_segments.get(road_id, [])
            if degree > 1:
                audit_rows.append(
                    _audit_row(
                        road_id=road_id,
                        node_id=node_id,
                        endpoint_index=endpoint_index,
                        status="pass",
                        action="verify_existing_rcsd_advance_endpoint",
                        reason="rcsd_advance_right_endpoint_already_connected",
                        degree=degree,
                        replacement_segment_ids=segment_ids,
                        geometry=point,
                    )
                )
                continue
            match = _nearest_preferred_rcsd_projection(
                point,
                selected_rcsd_road_ids=[candidate_id for candidate_id in selected_ids if candidate_id != road_id],
                rcsd_road_by_id=rcsd_road_by_id,
                max_gap_m=max_gap_m,
            )
            if match is None:
                swsd_match = _nearest_retained_swsd_projection(
                    point,
                    retained_swsd_road_by_id=retained_swsd_road_by_id,
                    max_gap_m=RCSD_ADVANCE_RIGHT_RETAINED_SWSD_MAX_GAP_M,
                )
                if (
                    swsd_match is not None
                    and swsd_roads is not None
                    and swsd_nodes is not None
                    and swsd_road_by_id is not None
                    and swsd_node_by_id is not None
                ):
                    target_swsd_road_id, swsd_distance_m, swsd_projected = swsd_match
                    swsd_node_id, swsd_node_id_seed, node_created = _ensure_swsd_attachment_node(
                        rcsd_node_id=node_id,
                        point=swsd_projected,
                        swsd_nodes=swsd_nodes,
                        swsd_node_by_id=swsd_node_by_id,
                        next_node_id=swsd_node_id_seed,
                    )
                    generated_swsd_node_count += int(node_created)
                    _set_cross_source_mainnode(node_id, swsd_node_id, rcsd_node_by_id, swsd_node_by_id)
                    _snap_advance_endpoint(
                        road,
                        endpoint_index=endpoint_index,
                        node_id=node_id,
                        point=swsd_projected,
                        rcsd_node_by_id=rcsd_node_by_id,
                    )
                    swsd_split_points_by_road[target_swsd_road_id][swsd_node_id] = (swsd_distance_m, swsd_node_id)
                    repaired_endpoint_count += 1
                    audit_rows.append(
                        _audit_row(
                            road_id=road_id,
                            node_id=node_id,
                            generated_swsd_node_id=swsd_node_id,
                            endpoint_index=endpoint_index,
                            status="repaired",
                            action="split_retained_swsd_road_for_rcsd_advance",
                            reason="rcsd_advance_right_leaf_endpoint_projected_to_retained_swsd_road",
                            degree=degree,
                            target_road_source="source_2",
                            target_swsd_road_id=target_swsd_road_id,
                            gap_m=round(float(point.distance(swsd_projected)), 3),
                            replacement_segment_ids=segment_ids,
                            geometry=swsd_projected,
                        )
                    )
                    continue
                failed_endpoint_count += 1
                audit_rows.append(
                    _audit_row(
                        road_id=road_id,
                        node_id=node_id,
                        endpoint_index=endpoint_index,
                        status="fail",
                        action="audit_no_safe_rcsd_projection",
                        reason="rcsd_advance_right_leaf_endpoint_has_no_safe_frcsd_projection",
                        degree=degree,
                        replacement_segment_ids=segment_ids,
                        geometry=point,
                    )
                )
                continue
            target_road_id, distance_m, projected, target_endpoint_node_id = match
            if target_road_id not in selected_set:
                continue
            gap_m = round(float(point.distance(projected)), 3)
            if target_endpoint_node_id and gap_m <= RCSD_ADVANCE_RIGHT_ENDPOINT_REUSE_MAX_GAP_M:
                _snap_advance_endpoint(
                    road,
                    endpoint_index=endpoint_index,
                    node_id=target_endpoint_node_id,
                    point=projected,
                    rcsd_node_by_id=rcsd_node_by_id,
                )
                action = "reuse_existing_rcsd_endpoint_node_for_rcsd_advance"
                reason = "rcsd_advance_right_leaf_endpoint_reused_selected_rcsd_endpoint"
            elif target_endpoint_node_id:
                swsd_match = _nearest_retained_swsd_projection(
                    point,
                    retained_swsd_road_by_id=retained_swsd_road_by_id,
                    max_gap_m=RCSD_ADVANCE_RIGHT_RETAINED_SWSD_MAX_GAP_M,
                )
                if (
                    swsd_match is not None
                    and swsd_roads is not None
                    and swsd_nodes is not None
                    and swsd_road_by_id is not None
                    and swsd_node_by_id is not None
                    and float(point.distance(swsd_match[2])) < gap_m
                ):
                    target_swsd_road_id, swsd_distance_m, swsd_projected = swsd_match
                    swsd_node_id, swsd_node_id_seed, node_created = _ensure_swsd_attachment_node(
                        rcsd_node_id=node_id,
                        point=swsd_projected,
                        swsd_nodes=swsd_nodes,
                        swsd_node_by_id=swsd_node_by_id,
                        next_node_id=swsd_node_id_seed,
                    )
                    generated_swsd_node_count += int(node_created)
                    _set_cross_source_mainnode(node_id, swsd_node_id, rcsd_node_by_id, swsd_node_by_id)
                    _snap_advance_endpoint(
                        road,
                        endpoint_index=endpoint_index,
                        node_id=node_id,
                        point=swsd_projected,
                        rcsd_node_by_id=rcsd_node_by_id,
                    )
                    swsd_split_points_by_road[target_swsd_road_id][swsd_node_id] = (swsd_distance_m, swsd_node_id)
                    repaired_endpoint_count += 1
                    audit_rows.append(
                        _audit_row(
                            road_id=road_id,
                            node_id=node_id,
                            generated_swsd_node_id=swsd_node_id,
                            endpoint_index=endpoint_index,
                            status="repaired",
                            action="split_retained_swsd_road_for_rcsd_advance",
                            reason="rcsd_advance_right_leaf_endpoint_preferred_retained_swsd_over_far_rcsd_endpoint",
                            degree=degree,
                            target_road_source="source_2",
                            target_swsd_road_id=target_swsd_road_id,
                            gap_m=round(float(point.distance(swsd_projected)), 3),
                            replacement_segment_ids=segment_ids,
                            geometry=swsd_projected,
                        )
                    )
                    continue
                failed_endpoint_count += 1
                audit_rows.append(
                    _audit_row(
                        road_id=road_id,
                        node_id=node_id,
                        endpoint_index=endpoint_index,
                        status="fail",
                        action="audit_no_safe_rcsd_projection",
                        reason="rcsd_advance_right_leaf_endpoint_projects_to_far_selected_rcsd_endpoint",
                        degree=degree,
                        target_road_source="source_1",
                        target_road_id=target_road_id,
                        target_node_id=target_endpoint_node_id,
                        gap_m=gap_m,
                        replacement_segment_ids=unique_preserve_order(
                            [*segment_ids, *added_road_to_segments.get(target_road_id, [])]
                        ),
                        geometry=projected,
                    )
                )
                continue
            else:
                _snap_advance_endpoint(
                    road,
                    endpoint_index=endpoint_index,
                    node_id=node_id,
                    point=projected,
                    rcsd_node_by_id=rcsd_node_by_id,
                )
                split_points_by_road[target_road_id][node_id] = (distance_m, node_id)
                _append_node_to_units(units, node_id, unique_preserve_order([*segment_ids, *added_road_to_segments.get(target_road_id, [])]))
                action = "split_selected_rcsd_road_for_rcsd_advance"
                reason = "rcsd_advance_right_leaf_endpoint_projected_to_mid_selected_rcsd_road"
            repaired_endpoint_count += 1
            audit_rows.append(
                _audit_row(
                    road_id=road_id,
                    node_id=node_id,
                    endpoint_index=endpoint_index,
                    status="repaired",
                    action=action,
                    reason=reason,
                    degree=degree,
                    target_road_source="source_1",
                    target_road_id=target_road_id,
                    target_node_id=target_endpoint_node_id,
                    gap_m=gap_m,
                    replacement_segment_ids=unique_preserve_order([*segment_ids, *added_road_to_segments.get(target_road_id, [])]),
                    geometry=projected,
                )
            )

    split_stats = _apply_contract_split_points(
        units,
        split_points_by_road=split_points_by_road,
        rcsd_roads=rcsd_roads,
        rcsd_road_by_id=rcsd_road_by_id,
        added_road_to_segments=added_road_to_segments,
    )
    swsd_split_stats = _apply_swsd_split_points(
        split_points_by_road=swsd_split_points_by_road,
        swsd_roads=swsd_roads or [],
        swsd_road_by_id=swsd_road_by_id or {},
        retained_swsd_roads=retained_swsd_roads or [],
    )
    return {
        "candidate_road_count": sum(1 for road_id in selected_ids if _is_advance_right_rcsd_road(rcsd_road_by_id.get(road_id, {}))),
        "repaired_endpoint_count": repaired_endpoint_count,
        "failed_endpoint_count": failed_endpoint_count,
        "split_original_road_count": split_stats["rcsd_split_original_road_count"],
        "split_road_count": split_stats["rcsd_split_road_count"],
        "retained_swsd_split_original_road_count": swsd_split_stats["split_original_road_count"],
        "retained_swsd_split_road_count": swsd_split_stats["split_road_count"],
        "generated_swsd_node_count": generated_swsd_node_count,
        "audit_rows": audit_rows,
    }


def apply_final_advance_right_endpoint_closure(
    frcsd_roads: list[dict[str, Any]],
    frcsd_nodes: list[dict[str, Any]],
    stats: dict[str, Any],
    units: list[Any],
    rcsd_roads: list[dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
    added_node_to_segments: dict[str, list[str]],
    source_field_name: str,
    rcsd_source_value: int,
    max_gap_m: float = RCSD_ADVANCE_RIGHT_CLOSURE_MAX_GAP_M,
) -> None:
    node_by_id = {_feature_id(node): node for node in frcsd_nodes}
    road_by_id = {_feature_id(road): road for road in frcsd_roads}
    canonicalizer = NodeCanonicalizer.from_node_features(frcsd_nodes)
    node_degree = _final_canonical_node_degrees(frcsd_roads, canonicalizer=canonicalizer)
    split_points_by_road: dict[str, dict[str, tuple[float, str]]] = defaultdict(dict)
    audit_rows: list[dict[str, Any]] = stats.setdefault("audit_rows", [])
    generated_node_seed = _next_numeric_id(node_by_id)
    repaired = 0
    failed = 0

    for road in list(frcsd_roads):
        props = dict(road.get("properties") or {})
        if not is_advance_right_turn_road(props):
            continue
        road_id = _feature_id(road)
        endpoint_ids = _road_endpoint_node_ids(road)
        endpoint_points = _road_endpoint_points(road)
        if len(endpoint_ids) < 2 or len(endpoint_points) < 2:
            continue
        for endpoint_index, (node_id, point) in enumerate(zip(endpoint_ids[:2], endpoint_points[:2])):
            degree = node_degree.get(_canonicalize(canonicalizer, node_id), 0)
            if degree > 1:
                continue
            match = _nearest_final_projection(
                point,
                source_road_id=road_id,
                frcsd_roads=frcsd_roads,
                max_gap_m=max_gap_m,
            )
            if match is None:
                failed += 1
                _mark_prior_endpoint_failures(
                    audit_rows,
                    road_id,
                    node_id,
                    status="superseded",
                    action="superseded_by_final_advance_right_closure",
                    reason="final_advance_right_endpoint_rechecked_after_native_projection_fail",
                )
                audit_rows.append(
                    _audit_row(
                        road_id=road_id,
                        node_id=node_id,
                        endpoint_index=endpoint_index,
                        status="fail",
                        action="audit_no_safe_final_projection",
                        reason="final_advance_right_leaf_endpoint_has_no_safe_frcsd_projection",
                        degree=degree,
                        replacement_segment_ids=[],
                        geometry=point,
                    )
                )
                continue
            target_road_id, distance_m, projected, target_endpoint_node_id = match
            target_road = road_by_id.get(target_road_id)
            target_props = dict(target_road.get("properties") or {}) if target_road else {}
            target_source = str(target_props.get(source_field_name) or "")
            replacement_segment_ids = added_road_to_segments.get(target_road_id, [])
            advance_source = str(props.get(source_field_name) or "")
            if (
                advance_source == str(rcsd_source_value)
                and target_source
                and target_source != str(rcsd_source_value)
                and not is_advance_right_turn_road(target_props)
            ):
                failed += 1
                audit_rows.append(
                    _audit_row(
                        road_id=road_id,
                        node_id=node_id,
                        endpoint_index=endpoint_index,
                        status="fail",
                        action="audit_retained_swsd_non_advance_target",
                        reason="final_rcsd_advance_right_endpoint_target_is_retained_swsd_non_advance_road",
                        degree=degree,
                        target_road_source=f"source_{target_source}",
                        target_swsd_road_id=target_road_id,
                        gap_m=round(float(point.distance(projected)), 3),
                        replacement_segment_ids=[],
                        geometry=point,
                    )
                )
                continue
            if target_endpoint_node_id:
                _set_final_mainnode(node_id, target_endpoint_node_id, node_by_id)
                split_node_id = target_endpoint_node_id
                action = "reuse_final_frcsd_endpoint_for_advance"
                reason = "final_advance_right_leaf_endpoint_reused_nearby_endpoint"
            else:
                split_node_id, generated_node_seed = _ensure_final_split_node(
                    advance_node_id=node_id,
                    target_source=target_source,
                    point=projected,
                    frcsd_nodes=frcsd_nodes,
                    node_by_id=node_by_id,
                    source_field_name=source_field_name,
                    next_node_id=generated_node_seed,
                )
                split_points_by_road[target_road_id][split_node_id] = (distance_m, split_node_id)
                action = "split_final_frcsd_road_for_advance"
                reason = "final_advance_right_leaf_endpoint_projected_to_mid_final_road"
            _set_final_mainnode(node_id, split_node_id, node_by_id)
            _snap_advance_endpoint(road, endpoint_index=endpoint_index, node_id=node_id, point=projected, rcsd_node_by_id=node_by_id)
            _mark_prior_endpoint_failures(
                audit_rows,
                road_id,
                node_id,
                status="repaired",
                action="superseded_by_final_advance_right_closure",
                reason="final_advance_right_endpoint_repaired_after_native_projection_fail",
            )
            _record_added_node_segments(
                split_node_id,
                target_road_id=target_road_id,
                added_node_to_segments=added_node_to_segments,
                added_road_to_segments=added_road_to_segments,
                target_source=target_source,
                rcsd_source_value=rcsd_source_value,
            )
            repaired += 1
            audit_rows.append(
                _audit_row(
                    road_id=road_id,
                    node_id=node_id,
                    generated_swsd_node_id=(split_node_id if split_node_id != node_id else None),
                    endpoint_index=endpoint_index,
                    status="repaired",
                    action=action,
                    reason=reason,
                    degree=degree,
                    target_road_source=f"source_{target_source}" if target_source else None,
                    target_road_id=target_road_id if target_source == str(rcsd_source_value) else None,
                    target_swsd_road_id=target_road_id if target_source and target_source != str(rcsd_source_value) else None,
                    target_node_id=target_endpoint_node_id,
                    gap_m=round(float(point.distance(projected)), 3),
                    replacement_segment_ids=replacement_segment_ids,
                    geometry=projected,
                )
            )

    split_stats = _apply_final_split_points(
        units=units,
        split_points_by_road=split_points_by_road,
        frcsd_roads=frcsd_roads,
        rcsd_roads=rcsd_roads,
        rcsd_road_by_id=rcsd_road_by_id,
        added_road_to_segments=added_road_to_segments,
        source_field_name=source_field_name,
        rcsd_source_value=rcsd_source_value,
    )
    _mark_connected_prior_failures(audit_rows, frcsd_roads=frcsd_roads, frcsd_nodes=frcsd_nodes)
    provenance_count = _annotate_final_road_segment_provenance(
        frcsd_roads,
        added_road_to_segments=added_road_to_segments,
    )
    stats["final_repaired_endpoint_count"] = repaired
    stats["final_failed_endpoint_count"] = failed
    stats["repaired_endpoint_count"] = int(stats.get("repaired_endpoint_count") or 0) + repaired
    stats["failed_endpoint_count"] = failed
    stats["final_split_original_road_count"] = split_stats["split_original_road_count"]
    stats["final_split_road_count"] = split_stats["split_road_count"]
    stats["final_road_segment_provenance_count"] = provenance_count


def _annotate_final_road_segment_provenance(
    frcsd_roads: list[dict[str, Any]],
    *,
    added_road_to_segments: dict[str, list[str]],
) -> int:
    annotated = 0
    for road in frcsd_roads:
        road_id = _feature_id(road)
        segment_ids = unique_preserve_order(added_road_to_segments.get(road_id, []))
        if not segment_ids:
            continue
        props = road.setdefault("properties", {})
        props["t06_swsd_segment_ids"] = segment_ids
        annotated += 1
    return annotated


def _mark_prior_endpoint_failures(
    audit_rows: list[dict[str, Any]],
    road_id: str,
    node_id: str,
    *,
    status: str,
    action: str,
    reason: str,
) -> None:
    for row in audit_rows:
        props = row.get("properties") or {}
        if props.get("audit_status") != "fail":
            continue
        if str(props.get("rcsd_advance_road_id")) != str(road_id):
            continue
        if str(props.get("rcsd_endpoint_node_id")) != str(node_id):
            continue
        props["audit_status"] = status
        props["action"] = action
        props["action_reason"] = reason


def _mark_connected_prior_failures(
    audit_rows: list[dict[str, Any]],
    *,
    frcsd_roads: list[dict[str, Any]],
    frcsd_nodes: list[dict[str, Any]],
) -> None:
    canonicalizer = NodeCanonicalizer.from_node_features(frcsd_nodes)
    node_degree = _final_canonical_node_degrees(frcsd_roads, canonicalizer=canonicalizer)
    for row in audit_rows:
        props = row.get("properties") or {}
        if props.get("audit_status") != "fail":
            continue
        node_id = str(props.get("rcsd_endpoint_node_id") or "")
        if not node_id:
            continue
        degree = node_degree.get(_canonicalize(canonicalizer, node_id), 0)
        if degree <= 1:
            continue
        props["audit_status"] = "repaired"
        props["action"] = "superseded_by_final_advance_right_closure"
        props["action_reason"] = "final_advance_right_endpoint_connected_after_final_closure"
        props["endpoint_degree"] = degree


def append_advance_attachment_rcsd_nodes(
    *,
    junctions: dict[str, Any],
    rcsd_roads: list[dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
    added_node_ids: set[str],
) -> None:
    for road in rcsd_roads:
        road_id = _feature_id(road)
        segment_ids = set(added_road_to_segments.get(road_id, []))
        if not segment_ids or not _is_advance_right_rcsd_road(road):
            continue
        endpoint_ids = _road_endpoint_node_ids(road)
        if len(endpoint_ids) < 2:
            continue
        endpoint_set = set(endpoint_ids)
        for state in junctions.values():
            if not segment_ids.intersection(state.replacement_segment_ids):
                continue
            junction_node_ids = set(state.added_rcsd_node_ids)
            if not endpoint_set.intersection(junction_node_ids):
                continue
            attachments = [
                node_id
                for node_id in endpoint_ids
                if node_id not in junction_node_ids and node_id in added_node_ids
            ]
            if attachments:
                state.advance_attachment_rcsd_node_ids = unique_preserve_order(
                    [*state.advance_attachment_rcsd_node_ids, *attachments]
                )


def _selected_canonical_node_degrees(
    *,
    selected_ids: list[str],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> dict[str, int]:
    degree: dict[str, int] = defaultdict(int)
    for road_id in selected_ids:
        road = rcsd_road_by_id.get(road_id)
        if road is None:
            continue
        for node_id in unique_preserve_order(_road_endpoint_node_ids(road)[:2]):
            degree[_canonicalize(canonicalizer, node_id)] += 1
    return dict(degree)


def _add_mixed_retained_swsd_endpoint_degrees(
    degree: dict[str, int],
    *,
    retained_swsd_roads: list[dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
) -> None:
    for road in retained_swsd_roads:
        props = dict(road.get("properties") or {})
        if props.get("t06_mixed_advance_right_split_reason") != MIXED_ADVANCE_RIGHT_RETAINED_SPLIT_REASON:
            continue
        for node_id in unique_preserve_order(_road_endpoint_node_ids(road)[:2]):
            canonical_id = _canonicalize(canonicalizer, node_id)
            degree[canonical_id] = int(degree.get(canonical_id) or 0) + 1


def _final_canonical_node_degrees(
    frcsd_roads: list[dict[str, Any]],
    *,
    canonicalizer: NodeCanonicalizer,
) -> dict[str, int]:
    degree: dict[str, int] = defaultdict(int)
    for road in frcsd_roads:
        for node_id in unique_preserve_order(_road_endpoint_node_ids(road)[:2]):
            degree[_canonicalize(canonicalizer, node_id)] += 1
    return dict(degree)


def _canonicalize(canonicalizer: NodeCanonicalizer, node_id: str) -> str:
    try:
        return canonicalizer.canonicalize(node_id)
    except ParseError:
        return str(node_id)


def _road_endpoint_points(road: dict[str, Any]) -> list[Point]:
    line = _feature_line(road)
    if line is None:
        return []
    coords = list(line.coords)
    if not coords:
        return []
    return [Point(coords[0]), Point(coords[-1])]


def _nearest_final_projection(
    point: Point,
    *,
    source_road_id: str,
    frcsd_roads: list[dict[str, Any]],
    max_gap_m: float,
) -> tuple[str, float, Point, str | None] | None:
    best: tuple[int, float, str, float, Point, str | None] | None = None
    for road in frcsd_roads:
        road_id = _feature_id(road)
        if road_id == source_road_id:
            continue
        line = _feature_line(road)
        if line is None or line.length <= 0:
            continue
        distance_m = float(line.project(point))
        projected = line.interpolate(distance_m)
        gap_m = float(point.distance(projected))
        if gap_m > max_gap_m:
            continue
        endpoint_ids = _road_endpoint_node_ids(road)
        target_endpoint_node_id: str | None = None
        if distance_m <= RCSD_ADVANCE_RIGHT_ENDPOINT_REUSE_MAX_GAP_M and endpoint_ids:
            target_endpoint_node_id = endpoint_ids[0]
        elif line.length - distance_m <= RCSD_ADVANCE_RIGHT_ENDPOINT_REUSE_MAX_GAP_M and len(endpoint_ids) >= 2:
            target_endpoint_node_id = endpoint_ids[1]
        elif distance_m <= 1.0 or line.length - distance_m <= 1.0:
            continue
        priority = 0 if is_advance_right_turn_road(dict(road.get("properties") or {})) else 1
        candidate = (priority, gap_m, road_id, distance_m, projected, target_endpoint_node_id)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        return None
    _priority, _gap_m, road_id, distance_m, projected, target_endpoint_node_id = best
    return road_id, distance_m, projected, target_endpoint_node_id


def _snap_advance_endpoint(
    road: dict[str, Any],
    *,
    endpoint_index: int,
    node_id: str,
    point: Point,
    rcsd_node_by_id: dict[str, dict[str, Any]],
) -> None:
    props = dict(road.get("properties") or {})
    endpoint_field = "snodeid" if endpoint_index == 0 else "enodeid"
    props[endpoint_field] = node_id
    road["properties"] = props
    line = _feature_line(road)
    if line is not None:
        coords = list(line.coords)
        if coords:
            target_index = 0 if endpoint_index == 0 else -1
            coords[target_index] = _coord_with_xy(coords[target_index], point)
            road["geometry"] = LineString(coords)
    node = rcsd_node_by_id.get(str(node_id))
    if node is not None:
        node["geometry"] = point


def _set_final_mainnode(node_a_id: str, node_b_id: str, node_by_id: dict[str, dict[str, Any]]) -> None:
    root = _node_mainnode_or_id(node_a_id, node_by_id) or _node_mainnode_or_id(node_b_id, node_by_id) or node_a_id
    for node_id in (node_a_id, node_b_id):
        node = node_by_id.get(str(node_id))
        if node is None:
            continue
        props = dict(node.get("properties") or {})
        props["mainnodeid"] = _coerce_id_value(root)
        node["properties"] = props


def _node_mainnode_or_id(node_id: str, node_by_id: dict[str, dict[str, Any]]) -> str:
    node = node_by_id.get(str(node_id))
    if node is None:
        return str(node_id)
    props = dict(node.get("properties") or {})
    mainnodeid = props.get("mainnodeid")
    if mainnodeid not in (None, "", 0, "0"):
        return str(mainnodeid)
    return str(node_id)


def _coerce_id_value(value: str) -> Any:
    text = str(value)
    return int(text) if text.isdigit() else text


def _ensure_final_split_node(
    *,
    advance_node_id: str,
    target_source: str,
    point: Point,
    frcsd_nodes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    source_field_name: str,
    next_node_id: int | None,
) -> tuple[str, int | None]:
    if target_source == _node_source_text(advance_node_id, node_by_id, source_field_name):
        node = node_by_id.get(str(advance_node_id))
        if node is not None:
            node["geometry"] = point
        return str(advance_node_id), next_node_id
    if next_node_id is not None:
        node_value: Any = next_node_id
        next_node_id += 1
    else:
        node_value = f"t06_final_advattach_{advance_node_id}"
    node_id = str(node_value)
    node = node_by_id.get(node_id)
    if node is not None:
        node["geometry"] = point
        return node_id, next_node_id
    template = dict(next(iter(node_by_id.values())).get("properties") or {}) if node_by_id else {}
    props = {key: None for key in template}
    props.update(
        {
            "id": node_value,
            "mainnodeid": _coerce_id_value(_node_mainnode_or_id(advance_node_id, node_by_id)),
            source_field_name: _coerce_id_value(target_source) if target_source else None,
            "t06_generated_reason": "final_advance_right_endpoint_attachment_node",
        }
    )
    node = {"properties": props, "geometry": point}
    frcsd_nodes.append(node)
    node_by_id[node_id] = node
    return node_id, next_node_id


def _node_source_text(node_id: str, node_by_id: dict[str, dict[str, Any]], source_field_name: str) -> str:
    node = node_by_id.get(str(node_id))
    if node is None:
        return ""
    return str((node.get("properties") or {}).get(source_field_name) or "")


def _record_added_node_segments(
    node_id: str,
    *,
    target_road_id: str,
    added_node_to_segments: dict[str, list[str]],
    added_road_to_segments: dict[str, list[str]],
    target_source: str,
    rcsd_source_value: int,
) -> None:
    if target_source != str(rcsd_source_value):
        return
    segment_ids = added_road_to_segments.get(target_road_id, [])
    if not segment_ids:
        return
    added_node_to_segments[node_id] = unique_preserve_order(
        [*added_node_to_segments.get(node_id, []), *segment_ids]
    )


def _coord_with_xy(original: tuple[float, ...], point: Point) -> tuple[float, ...]:
    x, y = point.coords[0][:2]
    if len(original) <= 2:
        return (x, y)
    return (x, y, *original[2:])


def _append_node_to_units(units: list[Any], node_id: str, segment_ids: list[str]) -> None:
    target_segments = set(segment_ids)
    for unit in units:
        if unit.segment_id in target_segments:
            unit.retained_node_ids = unique_preserve_order([*unit.retained_node_ids, node_id])


def _nearest_retained_swsd_projection(
    point: Point,
    *,
    retained_swsd_road_by_id: dict[str, dict[str, Any]],
    max_gap_m: float,
) -> tuple[str, float, Point] | None:
    best: tuple[int, float, str, float, Point] | None = None
    for road_id, road in retained_swsd_road_by_id.items():
        line = _feature_line(road)
        if line is None or line.length <= 0:
            continue
        distance_m = float(line.project(point))
        if distance_m <= 1.0 or line.length - distance_m <= 1.0:
            continue
        projected = line.interpolate(distance_m)
        gap_m = float(point.distance(projected))
        if gap_m > max_gap_m:
            continue
        priority = 0 if is_advance_right_turn_road(dict(road.get("properties") or {})) else 1
        candidate = (priority, gap_m, road_id, distance_m, projected)
        if best is None or candidate[:2] < best[:2]:
            best = candidate
    if best is None:
        return None
    return best[2], best[3], best[4]


def _ensure_swsd_attachment_node(
    *,
    rcsd_node_id: str,
    point: Point,
    swsd_nodes: list[dict[str, Any]],
    swsd_node_by_id: dict[str, dict[str, Any]],
    next_node_id: int | None,
) -> tuple[str, int | None, bool]:
    if next_node_id is not None:
        node_value: Any = next_node_id
        next_node_id += 1
    else:
        node_value = f"t06_swsd_advattach_{rcsd_node_id}"
    node_id = str(node_value)
    node = swsd_node_by_id.get(node_id)
    if node is not None:
        node["geometry"] = point
        return node_id, next_node_id, False
    template = dict(next(iter(swsd_node_by_id.values())).get("properties") or {}) if swsd_node_by_id else {}
    props = {key: None for key in template}
    props.update(
        {
            "id": node_value,
            "mainnodeid": rcsd_node_id,
            "source": 2,
            "t06_generated_reason": "rcsd_advance_right_retained_swsd_attachment_node",
        }
    )
    node = {"properties": props, "geometry": point}
    swsd_nodes.append(node)
    swsd_node_by_id[node_id] = node
    return node_id, next_node_id, True


def _set_cross_source_mainnode(
    rcsd_node_id: str,
    swsd_node_id: str,
    rcsd_node_by_id: dict[str, dict[str, Any]],
    swsd_node_by_id: dict[str, dict[str, Any]],
) -> None:
    mainnodeid = rcsd_node_id
    rcsd_node = rcsd_node_by_id.get(rcsd_node_id)
    if rcsd_node is not None:
        props = dict(rcsd_node.get("properties") or {})
        props["mainnodeid"] = mainnodeid
        rcsd_node["properties"] = props
    swsd_node = swsd_node_by_id.get(swsd_node_id)
    if swsd_node is not None:
        props = dict(swsd_node.get("properties") or {})
        props["mainnodeid"] = mainnodeid
        swsd_node["properties"] = props


def _apply_swsd_split_points(
    *,
    split_points_by_road: dict[str, dict[str, tuple[float, str]]],
    swsd_roads: list[dict[str, Any]],
    swsd_road_by_id: dict[str, dict[str, Any]],
    retained_swsd_roads: list[dict[str, Any]],
) -> dict[str, int]:
    split_original_ids: set[str] = set()
    split_road_count = 0
    for road_id in sorted(split_points_by_road):
        road = swsd_road_by_id.get(road_id)
        if road is None:
            continue
        split_roads = _split_road_at_nodes(
            road,
            split_points=split_points_by_road[road_id].values(),
            split_reason=RCSD_ADVANCE_RIGHT_RETAINED_SWSD_SPLIT_REASON,
        )
        if not split_roads:
            continue
        split_original_ids.add(road_id)
        split_road_count += len(split_roads)
        _replace_feature_by_id(swsd_roads, road_id, split_roads)
        _replace_feature_by_id(retained_swsd_roads, road_id, split_roads)
        swsd_road_by_id.pop(road_id, None)
        for split_road in split_roads:
            swsd_road_by_id[_feature_id(split_road)] = split_road
    return {
        "split_original_road_count": len(split_original_ids),
        "split_road_count": split_road_count,
    }


def _apply_final_split_points(
    *,
    units: list[Any],
    split_points_by_road: dict[str, dict[str, tuple[float, str]]],
    frcsd_roads: list[dict[str, Any]],
    rcsd_roads: list[dict[str, Any]],
    rcsd_road_by_id: dict[str, dict[str, Any]],
    added_road_to_segments: dict[str, list[str]],
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, int]:
    frcsd_road_by_id = {_feature_id(road): road for road in frcsd_roads}
    split_original_ids: set[str] = set()
    split_road_count = 0
    for road_id in sorted(split_points_by_road):
        road = frcsd_road_by_id.get(road_id)
        if road is None:
            continue
        split_roads = _split_road_at_nodes(
            road,
            split_points=split_points_by_road[road_id].values(),
            split_reason=FINAL_ADVANCE_RIGHT_CLOSURE_SPLIT_REASON,
        )
        if not split_roads:
            continue
        split_original_ids.add(road_id)
        split_road_count += len(split_roads)
        _replace_feature_by_id(frcsd_roads, road_id, split_roads)
        split_ids = [_feature_id(item) for item in split_roads]
        if str((road.get("properties") or {}).get(source_field_name) or "") == str(rcsd_source_value):
            _replace_feature_by_id(rcsd_roads, road_id, split_roads)
            rcsd_road_by_id.pop(road_id, None)
            for split_road in split_roads:
                rcsd_road_by_id[_feature_id(split_road)] = split_road
            segment_ids = added_road_to_segments.pop(road_id, [])
            if segment_ids:
                for split_id in split_ids:
                    added_road_to_segments[split_id] = list(segment_ids)
                _replace_rcsd_road_in_units(units, road_id, split_ids)
    return {
        "split_original_road_count": len(split_original_ids),
        "split_road_count": split_road_count,
    }


def _split_road_at_nodes(
    road: dict[str, Any],
    *,
    split_points: Any,
    split_reason: str,
) -> list[dict[str, Any]]:
    line = _feature_line(road)
    if line is None or line.length <= 0:
        return []
    endpoint_ids = _road_endpoint_node_ids(road)
    if len(endpoint_ids) < 2:
        return []
    valid_points = sorted(
        [
            (float(distance_m), str(node_id))
            for distance_m, node_id in split_points
            if 1.0 < float(distance_m) < line.length - 1.0
        ]
    )
    if not valid_points:
        return []
    original_id = _feature_id(road)
    boundaries = [0.0, *[distance for distance, _node_id in valid_points], float(line.length)]
    node_boundaries = [endpoint_ids[0], *[node_id for _distance, node_id in valid_points], endpoint_ids[-1]]
    result: list[dict[str, Any]] = []
    for index in range(len(boundaries) - 1):
        segment = substring(line, boundaries[index], boundaries[index + 1])
        if segment is None or segment.is_empty or not isinstance(segment, LineString):
            continue
        props = dict(road.get("properties") or {})
        suffix = "__t06finaladvsplit_" if split_reason == FINAL_ADVANCE_RIGHT_CLOSURE_SPLIT_REASON else "__t06swsdadvsplit_"
        props["id"] = f"{original_id}{suffix}{index + 1}"
        props["snodeid"] = node_boundaries[index]
        props["enodeid"] = node_boundaries[index + 1]
        props["t06_split_original_road_id"] = original_id
        props["t06_split_reason"] = split_reason
        result.append({"properties": props, "geometry": segment})
    return result


def _replace_rcsd_road_in_units(units: list[Any], original_id: str, replacement_ids: list[str]) -> None:
    for unit in units:
        if original_id not in unit.rcsd_road_ids:
            continue
        replaced: list[str] = []
        for road_id in unit.rcsd_road_ids:
            if road_id == original_id:
                replaced.extend(replacement_ids)
            else:
                replaced.append(road_id)
        unit.rcsd_road_ids = unique_preserve_order(replaced)


def _replace_feature_by_id(features: list[dict[str, Any]], original_id: str, replacements: list[dict[str, Any]]) -> None:
    for index, item in enumerate(list(features)):
        if _feature_id(item) == original_id:
            features[index:index + 1] = replacements
            return
    features.extend(replacements)


def _next_numeric_id(items: dict[str, Any]) -> int | None:
    values: list[int] = []
    for item_id in items:
        text = str(item_id)
        if not text.isdigit():
            return None
        values.append(int(text))
    return max(values, default=0) + 1


def _audit_row(
    *,
    road_id: str,
    node_id: str,
    generated_swsd_node_id: str | None = None,
    endpoint_index: int,
    status: str,
    action: str,
    reason: str,
    degree: int,
    replacement_segment_ids: list[str],
    target_road_source: str | None = None,
    target_road_id: str | None = None,
    target_swsd_road_id: str | None = None,
    target_node_id: str | None = None,
    gap_m: float | None = None,
    geometry: Any = None,
) -> dict[str, Any]:
    return feature(
        {
            "rcsd_advance_road_id": road_id,
            "rcsd_endpoint_node_id": node_id,
            "generated_swsd_node_id": generated_swsd_node_id,
            "endpoint_index": endpoint_index,
            "endpoint_degree": degree,
            "audit_status": status,
            "action": action,
            "action_reason": reason,
            "target_road_source": target_road_source,
            "target_rcsd_road_id": target_road_id,
            "target_swsd_road_id": target_swsd_road_id,
            "target_rcsd_node_id": target_node_id,
            "projected_gap_m": gap_m,
            "replacement_segment_ids": replacement_segment_ids,
        },
        geometry,
    )
