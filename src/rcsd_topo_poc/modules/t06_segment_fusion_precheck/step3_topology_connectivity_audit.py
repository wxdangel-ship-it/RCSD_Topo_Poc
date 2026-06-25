from __future__ import annotations

import json
from collections import defaultdict, deque
from itertools import combinations
from typing import Any

from shapely.geometry import LineString, MultiLineString, MultiPoint, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, unary_union

from .graph_builders import NodeCanonicalizer
from .parsing import ParseError, directionality_from_sgrade, normalize_id, parse_id_list, unique_preserve_order
from .road_attributes import is_advance_right_turn_road
from .schemas import feature
from .step3_topology_supplement import TOPOLOGY_SUPPLEMENT_SPLIT_REASON


STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM = "t06_step3_topology_connectivity_audit"
STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS = [
    "audit_layer",
    "audit_status",
    "audit_reason",
    "recommended_owner",
    "swsd_segment_id",
    "swsd_segment_ids",
    "swsd_node_id",
    "swsd_road_id",
    "frcsd_road_id",
    "frcsd_node_ids",
    "relation_status",
    "source_mix",
    "directionality",
    "pair_nodes",
    "path_forward",
    "path_reverse",
    "undirected_connected",
    "mapped_node_count",
    "missing_mapping_count",
    "max_pairwise_distance_m",
    "coverage_buffer_m",
    "uncovered_ratio",
    "uncovered_length_m",
    "corridor_buffer_m",
    "corridor_uncovered_ratio",
    "corridor_uncovered_length_m",
    "final_path_forward",
    "final_path_reverse",
    "final_undirected_connected",
    "final_corridor_uncovered_ratio",
    "final_corridor_uncovered_length_m",
    "projected_gap_m",
    "action",
    "action_reason",
]
TOPOLOGY_CONNECTIVITY_AUDIT_LAYERS = [
    "final_road_node_integrity",
    "formal_replacement_source_consistency",
    "segment_internal_connectivity",
    "segment_road_connectivity",
    "segment_junction_connectivity",
    "patch_road_attachment",
    "advance_right_endpoint_connectivity",
]
TOPOLOGY_CONNECTIVITY_AUDIT_STATUSES = ["pass", "warn", "fail"]

JUNCTION_WARN_DISTANCE_M = 1.0
JUNCTION_FAIL_DISTANCE_M = 5.0
ATTACHMENT_FAIL_DISTANCE_M = 1.0
SEGMENT_COVERAGE_BUFFER_M = 5.0
SEGMENT_ROAD_COVERAGE_BUFFER_M = 2.0
SEGMENT_CORRIDOR_BUFFER_M = 15.0
SEGMENT_MAX_UNCOVERED_RATIO = 0.05
SEGMENT_CORRIDOR_MANUAL_REVIEW_MAX_UNCOVERED_RATIO = 0.2
SEGMENT_MIN_UNCOVERED_LENGTH_M = 20.0
JUNCTION_SURFACE_COVERAGE_RELEASE_RISK = "junction_surface_coverage_release"


def build_topology_connectivity_audit_rows(
    *,
    swsd_segments: list[dict[str, Any]],
    frcsd_roads: list[dict[str, Any]],
    frcsd_nodes: list[dict[str, Any]],
    segment_relation_rows: list[dict[str, Any]],
    advance_right_audit_rows: list[dict[str, Any]],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
    swsd_roads: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    node_index = _NodeIndex(frcsd_nodes, source_field_name=source_field_name)
    road_index = _RoadIndex(frcsd_roads, source_field_name=source_field_name)
    canonicalizer = NodeCanonicalizer.from_node_features(frcsd_nodes)
    final_graph = _DirectedRoadGraph(frcsd_roads, canonicalizer=canonicalizer)
    relation_props = [dict(row.get("properties") or {}) for row in segment_relation_rows]
    relation_by_segment = {str(props.get("swsd_segment_id")): props for props in relation_props}
    attachment_refs_by_node = _attachment_refs_by_swsd_node(
        advance_right_audit_rows,
        rcsd_source_value=rcsd_source_value,
    )

    rows: list[dict[str, Any]] = []
    rows.extend(
        _final_road_node_integrity_rows(
            frcsd_roads=frcsd_roads,
            node_index=node_index,
            source_field_name=source_field_name,
            swsd_source_value=swsd_source_value,
        )
    )
    rows.extend(
        _formal_replacement_source_rows(
            relation_props=relation_props,
            road_index=road_index,
            rcsd_source_value=rcsd_source_value,
        )
    )
    rows.extend(
        _segment_internal_rows(
            swsd_segments=swsd_segments,
            relation_props=relation_props,
            road_index=road_index,
            final_roads=frcsd_roads,
            final_graph=final_graph,
            canonicalizer=canonicalizer,
            rcsd_source_value=rcsd_source_value,
            swsd_source_value=swsd_source_value,
            attachment_refs_by_node=attachment_refs_by_node,
        )
    )
    rows.extend(
        _segment_road_rows(
            swsd_segments=swsd_segments,
            swsd_roads=swsd_roads or [],
            relation_props=relation_props,
            road_index=road_index,
            final_roads=frcsd_roads,
            final_graph=final_graph,
            canonicalizer=canonicalizer,
            rcsd_source_value=rcsd_source_value,
            swsd_source_value=swsd_source_value,
            attachment_refs_by_node=attachment_refs_by_node,
        )
    )
    rows.extend(
        _segment_junction_rows(
            swsd_segments=swsd_segments,
            relation_by_segment=relation_by_segment,
            node_index=node_index,
            rcsd_source_value=rcsd_source_value,
            swsd_source_value=swsd_source_value,
            attachment_refs_by_node=attachment_refs_by_node,
        )
    )
    rows.extend(
        _patch_attachment_rows(
            advance_right_audit_rows=advance_right_audit_rows,
            node_index=node_index,
            road_index=road_index,
            swsd_source_value=swsd_source_value,
            rcsd_source_value=rcsd_source_value,
        )
    )
    rows.extend(
        _advance_right_endpoint_connectivity_rows(
            frcsd_roads=frcsd_roads,
            relation_props=relation_props,
            canonicalizer=canonicalizer,
            source_field_name=source_field_name,
            swsd_source_value=swsd_source_value,
        )
    )
    return [row for row in rows if (row.get("properties") or {}).get("audit_status")]


def _advance_right_endpoint_connectivity_rows(
    *,
    frcsd_roads: list[dict[str, Any]],
    relation_props: list[dict[str, Any]],
    canonicalizer: NodeCanonicalizer,
    source_field_name: str,
    swsd_source_value: int,
) -> list[dict[str, Any]]:
    selected_segment_ids_by_road = _selected_segment_ids_by_road(relation_props)
    node_degree = _final_canonical_node_degrees(frcsd_roads, canonicalizer=canonicalizer)
    rows: list[dict[str, Any]] = []
    for road in frcsd_roads:
        props = dict(road.get("properties") or {})
        if not is_advance_right_turn_road(props):
            continue
        road_id = _feature_id(road)
        endpoint_ids = _road_endpoint_node_id_pair(road)
        endpoint_points = _road_endpoint_points(road)
        if len(endpoint_ids) < 2:
            continue
        segment_ids = selected_segment_ids_by_road.get(road_id, [])
        for index, node_id in enumerate(endpoint_ids[:2]):
            canonical_id = _canonicalize_node(canonicalizer, node_id)
            degree = node_degree.get(canonical_id, 0)
            status = "pass"
            reason = "advance_right_endpoint_connected_to_frcsd_network"
            owner = ""
            if degree <= 1:
                status = "fail"
                reason = "advance_right_leaf_endpoint_unattached"
                owner = "T06_step3_advance_right_closure"
            rows.append(
                feature(
                    {
                        "audit_layer": "advance_right_endpoint_connectivity",
                        "audit_status": status,
                        "audit_reason": reason,
                        "recommended_owner": owner,
                        "swsd_segment_id": "",
                        "swsd_segment_ids": segment_ids,
                        "swsd_node_id": "",
                        "swsd_road_id": road_id if _source_text(props.get(source_field_name)) == str(swsd_source_value) else "",
                        "frcsd_road_id": road_id,
                        "frcsd_node_ids": [node_id],
                        "relation_status": "replaced" if segment_ids else "",
                        "source_mix": f"source_{_source_text(props.get(source_field_name))}" if props.get(source_field_name) is not None else "",
                        "directionality": f"road_direction_{_coerce_int(props.get('direction'))}",
                        "pair_nodes": endpoint_ids[:2],
                        "path_forward": None,
                        "path_reverse": None,
                        "undirected_connected": degree > 1,
                        "mapped_node_count": degree,
                        "missing_mapping_count": 0,
                        "max_pairwise_distance_m": None,
                        "coverage_buffer_m": None,
                        "uncovered_ratio": None,
                        "uncovered_length_m": None,
                        "corridor_buffer_m": None,
                        "corridor_uncovered_ratio": None,
                        "corridor_uncovered_length_m": None,
                        "final_path_forward": None,
                        "final_path_reverse": None,
                        "final_undirected_connected": degree > 1,
                        "final_corridor_uncovered_ratio": None,
                        "final_corridor_uncovered_length_m": None,
                        "projected_gap_m": None,
                        "action": "verify_final_advance_right_endpoint_connectivity",
                        "action_reason": f"endpoint_index_{index}",
                    },
                    endpoint_points[index] if index < len(endpoint_points) else None,
                )
            )
    return rows


def _selected_segment_ids_by_road(relation_props: list[dict[str, Any]]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for props in relation_props:
        if not str(props.get("relation_status") or "").startswith("replaced"):
            continue
        segment_id = str(props.get("swsd_segment_id") or "")
        if not segment_id:
            continue
        for road_id in _as_id_list(props.get("frcsd_road_ids")):
            result[road_id] = unique_preserve_order([*result[road_id], segment_id])
    return dict(result)


def _final_canonical_node_degrees(
    frcsd_roads: list[dict[str, Any]],
    *,
    canonicalizer: NodeCanonicalizer,
) -> dict[str, int]:
    result: dict[str, int] = defaultdict(int)
    for road in frcsd_roads:
        for node_id in unique_preserve_order(_road_endpoint_node_id_pair(road)[:2]):
            result[_canonicalize_node(canonicalizer, node_id)] += 1
    return dict(result)


def _canonicalize_node(canonicalizer: NodeCanonicalizer, node_id: str) -> str:
    try:
        return canonicalizer.canonicalize(node_id)
    except ParseError:
        return str(node_id)


def _formal_replacement_source_rows(
    *,
    relation_props: list[dict[str, Any]],
    road_index: "_RoadIndex",
    rcsd_source_value: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    rcsd_source = str(rcsd_source_value)
    for props in relation_props:
        relation_status = str(props.get("relation_status") or "")
        if not relation_status.startswith("replaced"):
            continue
        segment_id = str(props.get("swsd_segment_id") or "")
        road_ids = _as_id_list(props.get("frcsd_road_ids"))
        non_rcsd_ids: list[str] = []
        swsd_derived_ids: list[str] = []
        missing_ids: list[str] = []
        for road_id in road_ids:
            matches = road_index.roads_for_id(road_id)
            if not matches:
                if road_index.has_materialized_source_road(rcsd_source, road_id):
                    continue
                missing_ids.append(road_id)
                continue
            rcsd_matches = [road for source, road in matches if source == rcsd_source]
            if not rcsd_matches:
                non_rcsd_ids.append(road_id)
                continue
            if any(_is_swsd_topology_supplement(road) for road in rcsd_matches):
                swsd_derived_ids.append(road_id)
        status = "pass"
        reason = "formal_replacement_uses_rcsd_source_only"
        owner = ""
        if swsd_derived_ids:
            status = "fail"
            reason = "formal_replacement_contains_swsd_topology_supplement"
            owner = "T06_step3_relation_source_boundary"
        elif non_rcsd_ids:
            status = "fail"
            reason = "formal_replacement_contains_non_rcsd_source"
            owner = "T06_step3_relation_source_boundary"
        elif missing_ids:
            status = "fail"
            reason = "formal_replacement_road_missing_in_frcsd"
            owner = "T06_step3_segment_relation"
        rows.append(
            feature(
                {
                    "audit_layer": "formal_replacement_source_consistency",
                    "audit_status": status,
                    "audit_reason": reason,
                    "recommended_owner": owner,
                    "swsd_segment_id": segment_id,
                    "swsd_segment_ids": [segment_id] if segment_id else [],
                    "swsd_node_id": "",
                    "swsd_road_id": "",
                    "frcsd_road_id": unique_preserve_order([*swsd_derived_ids, *non_rcsd_ids, *missing_ids]),
                    "frcsd_node_ids": [],
                    "relation_status": relation_status,
                    "source_mix": str(props.get("source_mix") or ""),
                    "directionality": "",
                    "pair_nodes": [],
                    "path_forward": None,
                    "path_reverse": None,
                    "undirected_connected": None,
                    "mapped_node_count": None,
                    "missing_mapping_count": None,
                    "max_pairwise_distance_m": None,
                    "coverage_buffer_m": None,
                    "uncovered_ratio": None,
                    "uncovered_length_m": None,
                    "corridor_buffer_m": None,
                    "corridor_uncovered_ratio": None,
                    "corridor_uncovered_length_m": None,
                    "final_path_forward": None,
                    "final_path_reverse": None,
                    "final_undirected_connected": None,
                    "final_corridor_uncovered_ratio": None,
                    "final_corridor_uncovered_length_m": None,
                    "projected_gap_m": None,
                    "action": "",
                    "action_reason": "",
                },
                None,
            )
        )
    return rows


def _final_road_node_integrity_rows(
    *,
    frcsd_roads: list[dict[str, Any]],
    node_index: "_NodeIndex",
    source_field_name: str,
    swsd_source_value: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for road in frcsd_roads:
        props = dict(road.get("properties") or {})
        road_id = _feature_id(road)
        source = _source_text(props.get(source_field_name))
        endpoints = _road_endpoint_node_id_pair(road)
        endpoint_points = _road_endpoint_points(road)
        missing_endpoint_ids = [
            node_id for node_id in endpoints[:2] if node_index.exact_node(source, node_id) is None
        ]
        max_endpoint_distance = _max_endpoint_node_distance(
            source=source,
            endpoints=endpoints,
            endpoint_points=endpoint_points,
            node_index=node_index,
        )
        status = "pass"
        reason = "final_road_node_integrity_passed"
        owner = ""
        if len(endpoints) < 2:
            status = "fail"
            reason = "final_road_endpoint_id_missing"
            owner = "T06_step3_segment_replacement"
        elif missing_endpoint_ids:
            status = "fail"
            reason = "final_road_endpoint_node_missing"
            owner = "T06_step3_segment_replacement"
        elif max_endpoint_distance is not None and max_endpoint_distance > ATTACHMENT_FAIL_DISTANCE_M:
            status = "warn" if source == str(swsd_source_value) else "fail"
            reason = "final_road_endpoint_geometry_offset"
            owner = "upstream_swsd_baseline" if status == "warn" else "T06_step3_segment_replacement"
        rows.append(
            feature(
                {
                    "audit_layer": "final_road_node_integrity",
                    "audit_status": status,
                    "audit_reason": reason,
                    "recommended_owner": owner,
                    "swsd_segment_id": "",
                    "swsd_segment_ids": [],
                    "swsd_node_id": "",
                    "swsd_road_id": road_id if source == str(swsd_source_value) else "",
                    "frcsd_road_id": road_id,
                    "frcsd_node_ids": missing_endpoint_ids or endpoints[:2],
                    "relation_status": "",
                    "source_mix": f"source_{source}" if source else "",
                    "directionality": f"road_direction_{_coerce_int(props.get('direction'))}",
                    "pair_nodes": endpoints[:2],
                    "path_forward": None,
                    "path_reverse": None,
                    "undirected_connected": None,
                    "mapped_node_count": max(len(endpoints[:2]) - len(missing_endpoint_ids), 0),
                    "missing_mapping_count": len(missing_endpoint_ids),
                    "max_pairwise_distance_m": None,
                    "coverage_buffer_m": None,
                    "uncovered_ratio": None,
                    "uncovered_length_m": None,
                    "corridor_buffer_m": None,
                    "corridor_uncovered_ratio": None,
                    "corridor_uncovered_length_m": None,
                    "final_path_forward": None,
                    "final_path_reverse": None,
                    "final_undirected_connected": None,
                    "final_corridor_uncovered_ratio": None,
                    "final_corridor_uncovered_length_m": None,
                    "projected_gap_m": _round_length(max_endpoint_distance),
                    "action": "",
                    "action_reason": "",
                },
                road.get("geometry"),
            )
        )
    return rows


def summarize_topology_connectivity_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, Any] = {
        "topology_connectivity_audit_row_count": len(rows),
        "topology_connectivity_fail_count": 0,
        "topology_connectivity_warn_count": 0,
        "topology_connectivity_pass_count": 0,
    }
    for layer in TOPOLOGY_CONNECTIVITY_AUDIT_LAYERS:
        for status in TOPOLOGY_CONNECTIVITY_AUDIT_STATUSES:
            counts[f"topology_connectivity_{layer}_{status}_count"] = 0
    for row in rows:
        props = dict(row.get("properties") or {})
        layer = str(props.get("audit_layer") or "unknown")
        status = str(props.get("audit_status") or "unknown")
        counts[f"topology_connectivity_{layer}_{status}_count"] = (
            counts.get(f"topology_connectivity_{layer}_{status}_count", 0) + 1
        )
        if status == "fail":
            counts["topology_connectivity_fail_count"] += 1
        elif status == "warn":
            counts["topology_connectivity_warn_count"] += 1
        elif status == "pass":
            counts["topology_connectivity_pass_count"] += 1
    return counts


def _segment_internal_rows(
    *,
    swsd_segments: list[dict[str, Any]],
    relation_props: list[dict[str, Any]],
    road_index: "_RoadIndex",
    final_roads: list[dict[str, Any]],
    final_graph: "_DirectedRoadGraph",
    canonicalizer: NodeCanonicalizer,
    rcsd_source_value: int,
    swsd_source_value: int,
    attachment_refs_by_node: dict[str, list["_NodeRef"]],
) -> list[dict[str, Any]]:
    segment_by_id = {_feature_id(segment): segment for segment in swsd_segments}
    rows: list[dict[str, Any]] = []
    coverage_cache: dict[tuple[float, tuple[tuple[str, str], ...]], BaseGeometry] = {}
    for props in relation_props:
        segment_id = str(props.get("swsd_segment_id") or "")
        if not segment_id:
            continue
        segment = segment_by_id.get(segment_id)
        relation_status = str(props.get("relation_status") or "")
        is_group_path_corridor = _is_group_path_corridor_relation(props)
        directionality = directionality_from_sgrade((segment or {}).get("properties", {}).get("sgrade")) or "unknown"
        pair_nodes = _as_id_list(props.get("swsd_pair_nodes"))
        internal_attachment_refs = attachment_refs_by_node if relation_status != "retained_swsd" else {}
        retained_identity_refs = _retained_swsd_identity_refs_by_node(
            props,
            road_index=road_index,
            swsd_source_value=swsd_source_value,
        )
        selected_roads = _relation_roads(props, road_index)
        selected_road_ids = [_feature_id(road) for road in selected_roads]
        graph = _DirectedRoadGraph(selected_roads, canonicalizer=canonicalizer)
        mapped_pair_nodes = [
            _mapped_node_refs_for_swsd_node(
                props,
                pair_node,
                rcsd_source_value,
                swsd_source_value,
                attachment_refs_by_node=internal_attachment_refs,
                extra_refs_by_node=retained_identity_refs,
                prefer_attachment=False,
            )
            for pair_node in pair_nodes[:2]
        ]
        start_nodes = [canonicalizer.canonicalize(ref.node_id) for ref in mapped_pair_nodes[0]] if mapped_pair_nodes else []
        end_nodes = [canonicalizer.canonicalize(ref.node_id) for ref in mapped_pair_nodes[1]] if len(mapped_pair_nodes) > 1 else []
        path_forward = graph.reachable_any(start_nodes, end_nodes)
        path_reverse = graph.reachable_any(end_nodes, start_nodes)
        undirected_connected = graph.undirected_reachable_any(start_nodes, end_nodes)
        final_path_forward = final_graph.reachable_any(start_nodes, end_nodes)
        final_path_reverse = final_graph.reachable_any(end_nodes, start_nodes)
        final_undirected_connected = final_graph.undirected_reachable_any(start_nodes, end_nodes)
        uncovered_ratio, uncovered_length = _segment_uncovered_metrics(
            segment,
            selected_roads,
            buffer_m=SEGMENT_COVERAGE_BUFFER_M,
            coverage_cache=coverage_cache,
        )
        corridor_uncovered_ratio, corridor_uncovered_length = _segment_uncovered_metrics(
            segment,
            selected_roads,
            buffer_m=SEGMENT_CORRIDOR_BUFFER_M,
            coverage_cache=coverage_cache,
        )
        final_corridor_uncovered_ratio: float | None = None
        final_corridor_uncovered_length: float | None = None

        missing_mapping_count = sum(1 for refs in mapped_pair_nodes if not refs)
        strict_coverage_failed = _coverage_failed(uncovered_ratio, uncovered_length)
        corridor_coverage_failed = _coverage_failed(corridor_uncovered_ratio, corridor_uncovered_length)
        status = "pass"
        reason = "segment_internal_connectivity_passed"
        owner = ""
        if relation_status == "failed":
            status = "fail"
            reason = "segment_relation_failed"
            owner = "T06_step3_segment_replacement"
        elif len(pair_nodes) >= 2 and missing_mapping_count:
            status = "fail"
            reason = "segment_pair_node_mapping_missing"
            owner = "T06_step3_segment_replacement"
        elif len(pair_nodes) >= 2 and not undirected_connected:
            status = "fail" if relation_status != "retained_swsd" else "warn"
            reason = "segment_pair_nodes_not_connected"
            owner = "T06_step3_topology_connectivity"
            if status == "fail" and final_undirected_connected:
                status = "warn"
                reason = "segment_relation_road_scope_incomplete_but_final_graph_connected"
                owner = "T06_step3_segment_relation"
        elif directionality == "dual" and (not path_forward or not path_reverse):
            status = "fail" if relation_status != "retained_swsd" else "warn"
            reason = "dual_segment_pair_nodes_not_bidirectional"
            owner = "T06_step2_replacement_plan_or_step3_graph_selection"
            if status == "fail" and final_path_forward and final_path_reverse:
                status = "warn"
                reason = "segment_relation_road_scope_incomplete_but_final_graph_connected"
                owner = "T06_step3_segment_relation"
        elif corridor_coverage_failed and relation_status != "retained_swsd":
            final_corridor_uncovered_ratio, final_corridor_uncovered_length = _segment_nearby_uncovered_metrics(
                segment,
                final_roads,
                buffer_m=SEGMENT_CORRIDOR_BUFFER_M,
            )
            if is_group_path_corridor:
                status = "warn"
                reason = "group_path_corridor_segment_local_coverage_review"
                owner = "T06_step3_group_replacement_manual_audit"
            elif _coverage_manual_review(final_corridor_uncovered_ratio, final_corridor_uncovered_length):
                status = "warn"
                reason = "segment_corridor_coverage_manual_review_after_replacement"
                owner = "T06_step2_visual_consistency_review"
            else:
                status = "fail"
                reason = "segment_corridor_coverage_dropped_after_replacement"
                owner = "T06_step2_replacement_plan_or_group_selection"
            if status == "fail" and not _coverage_failed(final_corridor_uncovered_ratio, final_corridor_uncovered_length):
                status = "warn"
                reason = "segment_relation_road_scope_incomplete_but_final_corridor_preserved"
                owner = "T06_step3_segment_relation"
        elif corridor_coverage_failed:
            status = "warn"
            reason = "retained_swsd_segment_geometry_coverage_baseline_issue"
            owner = "upstream_swsd_baseline"
        elif strict_coverage_failed and relation_status != "retained_swsd":
            status = "warn"
            reason = "segment_strict_geometry_coverage_outside_5m"
            owner = "T06_step2_visual_consistency_review"
        elif strict_coverage_failed:
            status = "warn"
            reason = "retained_swsd_segment_strict_geometry_coverage_outside_5m"
            owner = "upstream_swsd_baseline"

        rows.append(
            feature(
                {
                    "audit_layer": "segment_internal_connectivity",
                    "audit_status": status,
                    "audit_reason": reason,
                    "recommended_owner": owner,
                    "swsd_segment_id": segment_id,
                    "swsd_segment_ids": [segment_id],
                    "swsd_node_id": "",
                    "swsd_road_id": "",
                    "frcsd_road_id": "",
                    "frcsd_node_ids": unique_preserve_order([ref.node_id for refs in mapped_pair_nodes for ref in refs]),
                    "relation_status": relation_status,
                    "source_mix": props.get("source_mix") or "",
                    "directionality": directionality,
                    "pair_nodes": pair_nodes,
                    "path_forward": path_forward,
                    "path_reverse": path_reverse,
                    "undirected_connected": undirected_connected,
                    "mapped_node_count": sum(len(refs) for refs in mapped_pair_nodes),
                    "missing_mapping_count": missing_mapping_count,
                    "max_pairwise_distance_m": None,
                    "coverage_buffer_m": SEGMENT_COVERAGE_BUFFER_M,
                    "uncovered_ratio": _round_ratio(uncovered_ratio),
                    "uncovered_length_m": _round_length(uncovered_length),
                    "corridor_buffer_m": SEGMENT_CORRIDOR_BUFFER_M,
                    "corridor_uncovered_ratio": _round_ratio(corridor_uncovered_ratio),
                    "corridor_uncovered_length_m": _round_length(corridor_uncovered_length),
                    "final_path_forward": final_path_forward,
                    "final_path_reverse": final_path_reverse,
                    "final_undirected_connected": final_undirected_connected,
                    "final_corridor_uncovered_ratio": _round_ratio(final_corridor_uncovered_ratio),
                    "final_corridor_uncovered_length_m": _round_length(final_corridor_uncovered_length),
                    "projected_gap_m": None,
                    "action": "",
                    "action_reason": "",
                },
                (segment or {}).get("geometry"),
            )
        )
    return rows


def _segment_road_rows(
    *,
    swsd_segments: list[dict[str, Any]],
    swsd_roads: list[dict[str, Any]],
    relation_props: list[dict[str, Any]],
    road_index: "_RoadIndex",
    final_roads: list[dict[str, Any]],
    final_graph: "_DirectedRoadGraph",
    canonicalizer: NodeCanonicalizer,
    rcsd_source_value: int,
    swsd_source_value: int,
    attachment_refs_by_node: dict[str, list["_NodeRef"]],
) -> list[dict[str, Any]]:
    segment_by_id = {_feature_id(segment): segment for segment in swsd_segments}
    swsd_road_by_id = {_feature_id(road): road for road in swsd_roads}
    rows: list[dict[str, Any]] = []
    coverage_cache: dict[tuple[float, tuple[tuple[str, str], ...]], BaseGeometry] = {}
    for props in relation_props:
        segment_id = str(props.get("swsd_segment_id") or "")
        segment = segment_by_id.get(segment_id)
        relation_status = str(props.get("relation_status") or "")
        if not segment_id or relation_status in {"", "failed", "retained_swsd"}:
            continue
        segment_props = dict((segment or {}).get("properties") or {})
        is_group_path_corridor = _is_group_path_corridor_relation(props)
        has_junction_surface_coverage_release = JUNCTION_SURFACE_COVERAGE_RELEASE_RISK in _as_id_list(props.get("risk_flags"))
        semantic_node_ids = set(unique_preserve_order([*_as_id_list(segment_props.get("pair_nodes")), *_as_id_list(segment_props.get("junc_nodes"))]))
        pair_node_ids = set(_as_id_list(props.get("swsd_pair_nodes")))
        selected_roads = _relation_roads(props, road_index)
        graph = _DirectedRoadGraph(selected_roads, canonicalizer=canonicalizer)
        retained_swsd_road_ids = _retained_swsd_relation_road_ids(
            props,
            road_index=road_index,
            swsd_source_value=swsd_source_value,
        )
        for swsd_road_id in _as_id_list(props.get("swsd_road_ids")) or _as_id_list((segment or {}).get("properties", {}).get("roads")):
            swsd_road = swsd_road_by_id.get(swsd_road_id)
            if swsd_road is None:
                continue
            endpoints = _road_endpoint_node_ids(swsd_road)
            if len(endpoints) < 2:
                continue
            if not all(endpoint in semantic_node_ids for endpoint in endpoints[:2]):
                continue
            if swsd_road_id in retained_swsd_road_ids:
                mapped_endpoint_refs = [[_NodeRef(str(swsd_source_value), endpoint)] for endpoint in endpoints[:2]]
            else:
                mapped_endpoint_refs = [
                    _mapped_node_refs_for_swsd_node(
                        props,
                        endpoint,
                        rcsd_source_value,
                        swsd_source_value,
                        attachment_refs_by_node=attachment_refs_by_node,
                        prefer_attachment=endpoint not in pair_node_ids,
                    )
                    for endpoint in endpoints[:2]
                ]
            start_nodes = [canonicalizer.canonicalize(ref.node_id) for ref in mapped_endpoint_refs[0]]
            end_nodes = [canonicalizer.canonicalize(ref.node_id) for ref in mapped_endpoint_refs[1]]
            path_forward = graph.reachable_any(start_nodes, end_nodes)
            path_reverse = graph.reachable_any(end_nodes, start_nodes)
            undirected_connected = graph.undirected_reachable_any(start_nodes, end_nodes)
            final_path_forward = final_graph.reachable_any(start_nodes, end_nodes)
            final_path_reverse = final_graph.reachable_any(end_nodes, start_nodes)
            final_undirected_connected = final_graph.undirected_reachable_any(start_nodes, end_nodes)
            uncovered_ratio, uncovered_length = _segment_uncovered_metrics(
                swsd_road,
                selected_roads,
                buffer_m=SEGMENT_ROAD_COVERAGE_BUFFER_M,
                coverage_cache=coverage_cache,
            )
            corridor_uncovered_ratio, corridor_uncovered_length = _segment_uncovered_metrics(
                swsd_road,
                selected_roads,
                buffer_m=SEGMENT_CORRIDOR_BUFFER_M,
                coverage_cache=coverage_cache,
            )
            final_corridor_uncovered_ratio: float | None = None
            final_corridor_uncovered_length: float | None = None
            missing_mapping_count = sum(1 for refs in mapped_endpoint_refs if not refs)
            strict_coverage_failed = _coverage_failed(uncovered_ratio, uncovered_length)
            corridor_coverage_failed = _coverage_failed(corridor_uncovered_ratio, corridor_uncovered_length)
            direction = _coerce_int((swsd_road.get("properties") or {}).get("direction"))
            directed_path_missing = _road_directed_path_missing(direction, path_forward, path_reverse, undirected_connected)
            status = "pass"
            reason = "segment_road_connectivity_passed"
            owner = ""
            action = ""
            action_reason = ""
            if missing_mapping_count:
                status = "warn" if is_group_path_corridor else "fail"
                reason = (
                    "group_path_corridor_road_endpoint_mapping_review"
                    if is_group_path_corridor
                    else "segment_road_endpoint_mapping_missing"
                )
                owner = "T06_step3_group_replacement_manual_audit" if is_group_path_corridor else "T06_step3_segment_relation"
            elif not undirected_connected:
                status = "fail"
                reason = "segment_road_endpoints_not_connected"
                owner = "T06_step2_replacement_plan_or_step3_graph_selection"
                if final_undirected_connected:
                    status = "warn"
                    reason = "segment_road_relation_scope_incomplete_but_final_graph_connected"
                    owner = "T06_step3_segment_relation"
            elif directed_path_missing:
                status = "fail"
                reason = "segment_road_directed_path_missing"
                owner = "T06_step2_replacement_plan_or_step3_graph_selection"
                final_directed_path_missing = _road_directed_path_missing(
                    direction,
                    final_path_forward,
                    final_path_reverse,
                    final_undirected_connected,
                )
                if not final_directed_path_missing:
                    status = "warn"
                    reason = "segment_road_relation_scope_incomplete_but_final_graph_connected"
                    owner = "T06_step3_segment_relation"
            elif corridor_coverage_failed:
                surface_release_review = has_junction_surface_coverage_release and not is_group_path_corridor
                status = "warn" if is_group_path_corridor or surface_release_review else "fail"
                reason = (
                    "group_path_corridor_road_local_coverage_review"
                    if is_group_path_corridor
                    else "segment_road_corridor_coverage_inside_junction_surface_review"
                    if surface_release_review
                    else "segment_road_corridor_coverage_dropped_after_replacement"
                )
                owner = (
                    "T06_step3_group_replacement_manual_audit"
                    if is_group_path_corridor
                    else "T06_manual_visual_geometry_review"
                    if surface_release_review
                    else "T06_step2_replacement_plan_or_group_selection"
                )
                if surface_release_review:
                    action = "manual_review_required"
                    action_reason = JUNCTION_SURFACE_COVERAGE_RELEASE_RISK
                final_corridor_uncovered_ratio, final_corridor_uncovered_length = _segment_nearby_uncovered_metrics(
                    swsd_road,
                    final_roads,
                    buffer_m=SEGMENT_CORRIDOR_BUFFER_M,
                )
                if not _coverage_failed(final_corridor_uncovered_ratio, final_corridor_uncovered_length):
                    status = "warn"
                    reason = "segment_road_relation_scope_incomplete_but_final_corridor_preserved"
                    owner = "T06_step3_segment_relation"
            elif strict_coverage_failed:
                status = "warn"
                reason = "segment_road_strict_geometry_coverage_outside_2m"
                owner = "T06_visual_geometry_review"
            rows.append(
                feature(
                    {
                        "audit_layer": "segment_road_connectivity",
                        "audit_status": status,
                        "audit_reason": reason,
                        "recommended_owner": owner,
                        "swsd_segment_id": segment_id,
                        "swsd_segment_ids": [segment_id],
                        "swsd_node_id": "",
                        "swsd_road_id": swsd_road_id,
                        "frcsd_road_id": "",
                        "frcsd_node_ids": unique_preserve_order(
                            [ref.node_id for refs in mapped_endpoint_refs for ref in refs]
                        ),
                        "relation_status": relation_status,
                        "source_mix": props.get("source_mix") or "",
                        "directionality": f"road_direction_{direction}",
                        "pair_nodes": endpoints[:2],
                        "path_forward": path_forward,
                        "path_reverse": path_reverse,
                        "undirected_connected": undirected_connected,
                        "mapped_node_count": sum(len(refs) for refs in mapped_endpoint_refs),
                        "missing_mapping_count": missing_mapping_count,
                        "max_pairwise_distance_m": None,
                        "coverage_buffer_m": SEGMENT_ROAD_COVERAGE_BUFFER_M,
                        "uncovered_ratio": _round_ratio(uncovered_ratio),
                        "uncovered_length_m": _round_length(uncovered_length),
                        "corridor_buffer_m": SEGMENT_CORRIDOR_BUFFER_M,
                        "corridor_uncovered_ratio": _round_ratio(corridor_uncovered_ratio),
                        "corridor_uncovered_length_m": _round_length(corridor_uncovered_length),
                        "final_path_forward": final_path_forward,
                        "final_path_reverse": final_path_reverse,
                        "final_undirected_connected": final_undirected_connected,
                        "final_corridor_uncovered_ratio": _round_ratio(final_corridor_uncovered_ratio),
                        "final_corridor_uncovered_length_m": _round_length(final_corridor_uncovered_length),
                        "projected_gap_m": None,
                        "action": action,
                        "action_reason": action_reason,
                    },
                    swsd_road.get("geometry"),
                )
            )
    return rows


def _segment_junction_rows(
    *,
    swsd_segments: list[dict[str, Any]],
    relation_by_segment: dict[str, dict[str, Any]],
    node_index: "_NodeIndex",
    rcsd_source_value: int,
    swsd_source_value: int,
    attachment_refs_by_node: dict[str, list["_NodeRef"]],
) -> list[dict[str, Any]]:
    incident_segments_by_node: dict[str, list[str]] = defaultdict(list)
    for segment in swsd_segments:
        segment_id = _feature_id(segment)
        props = dict(segment.get("properties") or {})
        for node_id in unique_preserve_order([*_as_id_list(props.get("pair_nodes")), *_as_id_list(props.get("junc_nodes"))]):
            incident_segments_by_node[node_id].append(segment_id)

    rows: list[dict[str, Any]] = []
    for swsd_node_id, segment_ids in sorted(incident_segments_by_node.items(), key=lambda item: _id_sort_key(item[0])):
        segment_ids = unique_preserve_order(segment_ids)
        if len(segment_ids) < 2:
            continue
        relation_segments = [relation_by_segment.get(segment_id) for segment_id in segment_ids]
        if not any(_is_replaced_relation(props) for props in relation_segments if props is not None):
            continue
        mapped_points: list[tuple[str, Point]] = []
        mapped_node_ids: list[str] = []
        mapped_mainnode_roots: list[str] = []
        missing_mapping_count = 0
        relation_statuses: list[str] = []
        source_mixes: list[str] = []
        for segment_id, props in zip(segment_ids, relation_segments):
            if props is None:
                missing_mapping_count += 1
                continue
            relation_statuses.append(str(props.get("relation_status") or ""))
            source_mixes.append(str(props.get("source_mix") or ""))
            refs = _mapped_node_refs_for_swsd_node(
                props,
                swsd_node_id,
                rcsd_source_value,
                swsd_source_value,
                attachment_refs_by_node=attachment_refs_by_node,
            )
            if not refs:
                missing_mapping_count += 1
                continue
            for ref in refs:
                point = node_index.point_for_ref(ref)
                mapped_node_ids.append(ref.node_id)
                mapped_mainnode_roots.append(node_index.mainnode_root_for_ref(ref) or ref.node_id)
                if point is not None:
                    mapped_points.append((ref.node_id, point))
        max_distance = _max_pairwise_distance([point for _, point in mapped_points])
        mainnode_roots = unique_preserve_order(mapped_mainnode_roots)
        mainnode_closed = not missing_mapping_count and len(mainnode_roots) == 1
        status = "pass"
        reason = "segment_junction_connectivity_preserved"
        owner = ""
        action = ""
        action_reason = ""
        if missing_mapping_count:
            status = "fail"
            reason = "junction_incident_segment_mapping_missing"
            owner = "T06_step3_segment_relation"
        elif mainnode_closed:
            action = "semantic_mainnode_closure_verified"
            action_reason = f"mainnode_root={mainnode_roots[0]}"
            if max_distance is not None and max_distance > JUNCTION_FAIL_DISTANCE_M:
                status = "warn"
                reason = "junction_incident_segment_mainnode_closed_but_geometry_diverged"
                owner = "T06_step3_surface_topology_audit"
            elif max_distance is not None and max_distance > JUNCTION_WARN_DISTANCE_M:
                status = "warn"
                reason = "junction_incident_segment_mainnode_closed_with_minor_offset"
                owner = "T06_step3_surface_topology_audit"
        elif max_distance is not None and max_distance > JUNCTION_FAIL_DISTANCE_M:
            status = "fail"
            reason = "junction_incident_segment_mapped_points_diverged"
            owner = "T06_step3_attachment_contract"
        elif max_distance is not None and max_distance > JUNCTION_WARN_DISTANCE_M:
            status = "warn"
            reason = "junction_incident_segment_mapped_points_not_coincident"
            owner = "T06_step3_attachment_contract"
        elif "source_1" in source_mixes and "source_2" in source_mixes:
            status = "warn"
            reason = "junction_incident_semantic_mainnode_not_closed"
            owner = "T06_step3_attachment_contract"
        rows.append(
            feature(
                {
                    "audit_layer": "segment_junction_connectivity",
                    "audit_status": status,
                    "audit_reason": reason,
                    "recommended_owner": owner,
                    "swsd_segment_id": "",
                    "swsd_segment_ids": segment_ids,
                    "swsd_node_id": swsd_node_id,
                    "swsd_road_id": "",
                    "frcsd_road_id": "",
                    "frcsd_node_ids": unique_preserve_order(mapped_node_ids),
                    "relation_status": "+".join(unique_preserve_order(relation_statuses)),
                    "source_mix": "+".join(unique_preserve_order(source_mixes)),
                    "directionality": "",
                    "pair_nodes": [],
                    "path_forward": None,
                    "path_reverse": None,
                    "undirected_connected": None,
                    "mapped_node_count": len(mapped_node_ids),
                    "missing_mapping_count": missing_mapping_count,
                    "max_pairwise_distance_m": _round_length(max_distance),
                    "coverage_buffer_m": None,
                    "uncovered_ratio": None,
                    "uncovered_length_m": None,
                    "corridor_buffer_m": None,
                    "corridor_uncovered_ratio": None,
                    "corridor_uncovered_length_m": None,
                    "final_path_forward": None,
                    "final_path_reverse": None,
                    "final_undirected_connected": None,
                    "final_corridor_uncovered_ratio": None,
                    "final_corridor_uncovered_length_m": None,
                    "projected_gap_m": None,
                    "action": action,
                    "action_reason": action_reason,
                },
                _points_geometry([point for _, point in mapped_points]),
            )
        )
    return rows


def _patch_attachment_rows(
    *,
    advance_right_audit_rows: list[dict[str, Any]],
    node_index: "_NodeIndex",
    road_index: "_RoadIndex",
    swsd_source_value: int,
    rcsd_source_value: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in advance_right_audit_rows:
        props = dict(row.get("properties") or {})
        action = str(props.get("action") or "")
        replacement_segment_ids = _as_id_list(props.get("replacement_segment_ids"))
        if not action:
            continue
        if action == "normalize_swsd_singleton_mainnode":
            status = "pass"
            reason = "advance_right_mainnode_normalized"
            owner = ""
        elif "no_safe_rcsd_projection" in action:
            if replacement_segment_ids:
                status = "fail"
                reason = "patch_road_endpoint_has_no_safe_frcsd_projection"
                owner = "T06_step3_attachment_contract"
            else:
                status = "warn"
                reason = "retained_patch_endpoint_without_replacement_context"
                owner = "upstream_swsd_baseline"
        elif action.startswith(("split_", "reuse_")):
            status, reason, owner = _attachment_status(
                props,
                node_index=node_index,
                road_index=road_index,
                swsd_source_value=swsd_source_value,
                rcsd_source_value=rcsd_source_value,
            )
        else:
            continue
        rows.append(
            feature(
                {
                    "audit_layer": "patch_road_attachment",
                    "audit_status": status,
                    "audit_reason": reason,
                    "recommended_owner": owner,
                    "swsd_segment_id": "",
                    "swsd_segment_ids": replacement_segment_ids,
                    "swsd_node_id": str(props.get("swsd_node_id") or ""),
                    "swsd_road_id": str(props.get("swsd_advance_road_id") or ""),
                    "frcsd_road_id": str(props.get("rcsd_road_id") or ""),
                    "frcsd_node_ids": unique_preserve_order(
                        [
                            node_id
                            for node_id in [
                                _safe_text(props.get("rcsd_node_id")),
                                _safe_text(props.get("generated_rcsd_node_id")),
                            ]
                            if node_id
                        ]
                    ),
                    "relation_status": "",
                    "source_mix": "source_1+source_2",
                    "directionality": "",
                    "pair_nodes": [],
                    "path_forward": None,
                    "path_reverse": None,
                    "undirected_connected": None,
                    "mapped_node_count": None,
                    "missing_mapping_count": None,
                    "max_pairwise_distance_m": None,
                    "coverage_buffer_m": None,
                    "uncovered_ratio": None,
                    "uncovered_length_m": None,
                    "corridor_buffer_m": None,
                    "corridor_uncovered_ratio": None,
                    "corridor_uncovered_length_m": None,
                    "final_path_forward": None,
                    "final_path_reverse": None,
                    "final_undirected_connected": None,
                    "final_corridor_uncovered_ratio": None,
                    "final_corridor_uncovered_length_m": None,
                    "projected_gap_m": _coerce_float(props.get("projected_gap_m")),
                    "action": action,
                    "action_reason": str(props.get("action_reason") or ""),
                },
                row.get("geometry"),
            )
        )
    return rows


def _is_swsd_topology_supplement(road: dict[str, Any]) -> bool:
    props = dict(road.get("properties") or {})
    return str(props.get("t06_split_reason") or "") == TOPOLOGY_SUPPLEMENT_SPLIT_REASON


def _attachment_status(
    props: dict[str, Any],
    *,
    node_index: "_NodeIndex",
    road_index: "_RoadIndex",
    swsd_source_value: int,
    rcsd_source_value: int,
) -> tuple[str, str, str]:
    swsd_node_id = _safe_text(props.get("swsd_node_id"))
    swsd_road_id = _safe_text(props.get("swsd_advance_road_id") or props.get("swsd_road_id"))
    rcsd_node_id = _safe_text(props.get("rcsd_node_id")) or _safe_text(props.get("generated_rcsd_node_id"))
    if not swsd_node_id or not rcsd_node_id:
        return "fail", "patch_attachment_node_id_missing", "T06_step3_attachment_contract"
    swsd_point = node_index.point_for_ref(_NodeRef(str(swsd_source_value), swsd_node_id))
    rcsd_point = node_index.point_for_ref(_NodeRef(str(rcsd_source_value), rcsd_node_id))
    action = str(props.get("action") or "")
    if "detached_swsd_node" in action:
        if rcsd_point is None:
            return "fail", "patch_attachment_node_missing_in_frcsd", "T06_step3_attachment_contract"
        if not _has_incident_road_in_mainnode_group(
            node_index,
            road_index,
            source=str(rcsd_source_value),
            node_id=rcsd_node_id,
        ):
            return "fail", "patch_attachment_rcsd_node_isolated", "T06_step3_attachment_contract"
        return "pass", "detached_semantic_node_connected_to_frcsd_node", ""
    if (
        swsd_point is None
        and rcsd_point is not None
        and swsd_road_id
        and road_index.has_materialized_source_road(str(rcsd_source_value), swsd_road_id)
        and _has_incident_road_in_mainnode_group(
            node_index,
            road_index,
            source=str(rcsd_source_value),
            node_id=rcsd_node_id,
        )
    ):
        return "pass", "patch_attachment_materialized_as_rcsd_topology_supplement", ""
    if (
        swsd_point is None
        and rcsd_point is not None
        and action.startswith(("split_rcsd_road_for_swsd_advance", "reuse_existing_rcsd_"))
        and _has_incident_road_in_mainnode_group(
            node_index,
            road_index,
            source=str(rcsd_source_value),
            node_id=rcsd_node_id,
        )
    ):
        return "pass", "patch_attachment_connected_to_frcsd_node", ""
    if swsd_point is None or rcsd_point is None:
        return "fail", "patch_attachment_node_missing_in_frcsd", "T06_step3_attachment_contract"
    if float(swsd_point.distance(rcsd_point)) > ATTACHMENT_FAIL_DISTANCE_M:
        return "fail", "patch_attachment_nodes_not_coincident", "T06_step3_attachment_contract"
    if not _has_incident_road_in_mainnode_group(
        node_index,
        road_index,
        source=str(rcsd_source_value),
        node_id=rcsd_node_id,
    ):
        return "fail", "patch_attachment_rcsd_node_isolated", "T06_step3_attachment_contract"
    swsd_mainnode = node_index.mainnode_root_for_ref(_NodeRef(str(swsd_source_value), swsd_node_id))
    rcsd_mainnode = node_index.mainnode_root_for_ref(_NodeRef(str(rcsd_source_value), rcsd_node_id))
    if swsd_mainnode and rcsd_mainnode and swsd_mainnode != rcsd_mainnode:
        if _swsd_mainnode_is_attached_to_alternate_rcsd(
            swsd_mainnode,
            swsd_point=swsd_point,
            node_index=node_index,
            road_index=road_index,
            rcsd_source_value=rcsd_source_value,
        ):
            return "warn", "patch_attachment_merged_to_alternate_rcsd_node", "T06_step3_attachment_contract"
        return "fail", "patch_attachment_mainnode_not_merged", "T06_step3_attachment_contract"
    return "pass", "patch_attachment_connected_to_frcsd_node", ""


def _swsd_mainnode_is_attached_to_alternate_rcsd(
    swsd_mainnode: str,
    *,
    swsd_point: Point,
    node_index: "_NodeIndex",
    road_index: "_RoadIndex",
    rcsd_source_value: int,
) -> bool:
    rcsd_source = str(rcsd_source_value)
    node = node_index.exact_node(rcsd_source, swsd_mainnode)
    if node is None:
        return False
    point = node.get("geometry")
    if not isinstance(point, Point):
        return False
    if float(swsd_point.distance(point)) > ATTACHMENT_FAIL_DISTANCE_M:
        return False
    return _has_incident_road_in_mainnode_group(
        node_index,
        road_index,
        source=rcsd_source,
        node_id=swsd_mainnode,
    )


def _has_incident_road_in_mainnode_group(
    node_index: "_NodeIndex",
    road_index: "_RoadIndex",
    *,
    source: str,
    node_id: str,
) -> bool:
    if road_index.has_incident_road(source, node_id):
        return True
    root_id = node_index.mainnode_root_for_ref(_NodeRef(source, node_id))
    if not root_id:
        return False
    for peer_node_id in node_index.node_ids_for_source(source):
        if not road_index.has_incident_road(source, peer_node_id):
            continue
        peer_root_id = node_index.mainnode_root_for_ref(_NodeRef(source, peer_node_id))
        if peer_root_id == root_id:
            return True
    return False


def _road_directed_path_missing(
    direction: int | None,
    path_forward: bool,
    path_reverse: bool,
    undirected_connected: bool,
) -> bool:
    if direction in {0, 1}:
        return not (path_forward and path_reverse)
    if direction == 2:
        return not path_forward
    if direction == 3:
        return not path_reverse
    return not undirected_connected


def _retained_swsd_relation_road_ids(
    props: dict[str, Any],
    *,
    road_index: "_RoadIndex",
    swsd_source_value: int,
) -> set[str]:
    result: set[str] = set()
    source = str(swsd_source_value)
    for road_id in _as_id_list(props.get("frcsd_road_ids")):
        if any(road_source == source for road_source, _road in road_index.roads_for_id(road_id)):
            result.add(road_id)
    for road_id in _as_id_list(props.get("retained_detached_swsd_road_ids")):
        if any(road_source == source for road_source, _road in road_index.roads_for_id(road_id)):
            result.add(road_id)
    return result


def _retained_swsd_identity_refs_by_node(
    props: dict[str, Any],
    *,
    road_index: "_RoadIndex",
    swsd_source_value: int,
) -> dict[str, list["_NodeRef"]]:
    result: dict[str, list[_NodeRef]] = defaultdict(list)
    source = str(swsd_source_value)
    for road_id in _retained_swsd_relation_road_ids(
        props,
        road_index=road_index,
        swsd_source_value=swsd_source_value,
    ):
        for road_source, road in road_index.roads_for_id(road_id):
            if road_source != source:
                continue
            for node_id in _road_endpoint_node_ids(road)[:2]:
                ref = _NodeRef(source, node_id)
                if ref not in result[node_id]:
                    result[node_id].append(ref)
    return dict(result)


def _relation_roads(props: dict[str, Any], road_index: "_RoadIndex") -> list[dict[str, Any]]:
    road_ids = _as_id_list(props.get("frcsd_road_ids"))
    source_values = {_source_text(value) for value in _as_id_list(props.get("frcsd_road_source_values"))}
    source_values.discard("")
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for road_id in road_ids:
        for source_value, road in road_index.roads_for_id(road_id):
            if source_values and source_value not in source_values:
                continue
            key = (source_value, road_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(road)
    return result


def _mapped_node_refs_for_swsd_node(
    props: dict[str, Any],
    swsd_node_id: str,
    rcsd_source_value: int,
    swsd_source_value: int,
    *,
    attachment_refs_by_node: dict[str, list["_NodeRef"]] | None = None,
    extra_refs_by_node: dict[str, list["_NodeRef"]] | None = None,
    prefer_attachment: bool = True,
) -> list["_NodeRef"]:
    refs: list[_NodeRef] = []
    attachment_refs = (attachment_refs_by_node or {}).get(swsd_node_id, [])
    if prefer_attachment:
        for ref in attachment_refs:
            if ref not in refs:
                refs.append(ref)
        if refs:
            for ref in (extra_refs_by_node or {}).get(swsd_node_id, []):
                if ref not in refs:
                    refs.append(ref)
            return refs
    for entry in _node_map_entries(props.get("swsd_to_frcsd_node_map")):
        if str(entry.get("swsd_node_id") or "") != swsd_node_id:
            continue
        status = str(entry.get("mapping_status") or "")
        source = str(swsd_source_value) if status.startswith("identity") else str(rcsd_source_value)
        for node_id in _as_id_list(entry.get("frcsd_node_ids")):
            ref = _NodeRef(source, node_id)
            if ref not in refs:
                refs.append(ref)
    for ref in (extra_refs_by_node or {}).get(swsd_node_id, []):
        if ref not in refs:
            refs.append(ref)
    if not refs:
        for ref in attachment_refs:
            if ref not in refs:
                refs.append(ref)
    return refs


def _attachment_refs_by_swsd_node(
    rows: list[dict[str, Any]],
    *,
    rcsd_source_value: int,
) -> dict[str, list["_NodeRef"]]:
    result: dict[str, list[_NodeRef]] = defaultdict(list)
    for row in rows:
        props = dict(row.get("properties") or {})
        action = str(props.get("action") or "")
        if not action.startswith(("split_", "reuse_")):
            continue
        swsd_node_id = _safe_text(props.get("swsd_node_id"))
        rcsd_node_id = _safe_text(props.get("rcsd_node_id")) or _safe_text(props.get("generated_rcsd_node_id"))
        if not swsd_node_id or not rcsd_node_id:
            continue
        refs = result[swsd_node_id]
        if not any(ref.node_id == rcsd_node_id and ref.source == str(rcsd_source_value) for ref in refs):
            refs.append(_NodeRef(str(rcsd_source_value), rcsd_node_id))
    return dict(result)


class _DirectedRoadGraph:
    def __init__(self, roads: list[dict[str, Any]], *, canonicalizer: NodeCanonicalizer) -> None:
        self.forward: dict[str, set[str]] = defaultdict(set)
        self.undirected: dict[str, set[str]] = defaultdict(set)
        for road in roads:
            endpoints = _road_endpoint_node_ids(road)
            if len(endpoints) < 2:
                continue
            source = canonicalizer.canonicalize(endpoints[0])
            target = canonicalizer.canonicalize(endpoints[-1])
            direction = _coerce_int((road.get("properties") or {}).get("direction"))
            if direction in {0, 1, 2}:
                self.forward[source].add(target)
            if direction in {0, 1, 3}:
                self.forward[target].add(source)
            self.undirected[source].add(target)
            self.undirected[target].add(source)

    def reachable_any(self, starts: list[str], targets: list[str]) -> bool:
        return _reachable_any(self.forward, starts, targets)

    def undirected_reachable_any(self, starts: list[str], targets: list[str]) -> bool:
        return _reachable_any(self.undirected, starts, targets)


class _RoadIndex:
    def __init__(self, roads: list[dict[str, Any]], *, source_field_name: str) -> None:
        self.by_id: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)
        self.incident_nodes: set[tuple[str, str]] = set()
        self.materialized_source_road_ids: set[tuple[str, str]] = set()
        for road in roads:
            road_id = _feature_id(road)
            props = dict(road.get("properties") or {})
            source = _source_text(props.get(source_field_name))
            self.by_id[road_id].append((source, road))
            for source_road_id in (_safe_text(props.get("source_road_id")), _safe_text(props.get("t06_split_original_road_id"))):
                if source_road_id:
                    self.materialized_source_road_ids.add((source, source_road_id))
            for node_id in _road_endpoint_node_ids(road):
                self.incident_nodes.add((source, node_id))

    def roads_for_id(self, road_id: str) -> list[tuple[str, dict[str, Any]]]:
        return self.by_id.get(str(road_id), [])

    def has_incident_road(self, source: str, node_id: str) -> bool:
        return (str(source), str(node_id)) in self.incident_nodes

    def has_materialized_source_road(self, source: str, source_road_id: str) -> bool:
        return (str(source), str(source_road_id)) in self.materialized_source_road_ids


class _NodeIndex:
    def __init__(self, nodes: list[dict[str, Any]], *, source_field_name: str) -> None:
        self.source_field_name = source_field_name
        self.by_source_id: dict[tuple[str, str], dict[str, Any]] = {}
        self.by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        canonicalizer = NodeCanonicalizer.from_node_features(nodes)
        self.by_source_canonical: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for node in nodes:
            node_id = _feature_id(node)
            source = _source_text((node.get("properties") or {}).get(source_field_name))
            self.by_source_id[(source, node_id)] = node
            self.by_id[node_id].append(node)
            try:
                self.by_source_canonical[(source, canonicalizer.canonicalize(node_id))].append(node)
            except ParseError:
                pass

    def node_for_ref(self, ref: "_NodeRef") -> dict[str, Any] | None:
        node = self.by_source_id.get((ref.source, ref.node_id))
        if node is None:
            candidates = self.by_source_canonical.get((ref.source, ref.node_id), [])
            node = candidates[0] if candidates else None
        if node is None:
            candidates = self.by_id.get(ref.node_id, [])
            node = candidates[0] if candidates else None
        return node

    def exact_node(self, source: str, node_id: str) -> dict[str, Any] | None:
        try:
            normalized_node_id = normalize_id(node_id)
        except ParseError:
            normalized_node_id = str(node_id)
        node = self.by_source_id.get((_source_text(source), normalized_node_id))
        if node is not None:
            return node
        candidates = self.by_id.get(normalized_node_id, [])
        return candidates[0] if len(candidates) == 1 else None

    def point_for_ref(self, ref: "_NodeRef") -> Point | None:
        node = self.node_for_ref(ref)
        geometry = node.get("geometry") if node is not None else None
        return geometry if isinstance(geometry, Point) else None

    def node_ids_for_source(self, source: str) -> list[str]:
        return [node_id for item_source, node_id in self.by_source_id if item_source == source]

    def mainnode_root_for_ref(self, ref: "_NodeRef") -> str | None:
        node = self.node_for_ref(ref)
        if node is None:
            return None
        current = _feature_id(node)
        source = _source_text((node.get("properties") or {}).get(self.source_field_name)) or ref.source
        seen: set[tuple[str, str]] = set()
        while current and (source, current) not in seen:
            seen.add((source, current))
            current_node = self.by_source_id.get((source, current))
            if current_node is None:
                candidates = self.by_id.get(current, [])
                current_node = candidates[0] if candidates else None
            if current_node is None:
                return current
            props = dict(current_node.get("properties") or {})
            source = _source_text(props.get(self.source_field_name)) or source
            next_id = _safe_text(props.get("mainnodeid"))
            if not next_id or next_id == "0" or next_id == current:
                return current
            current = next_id
        return current or None


class _NodeRef:
    def __init__(self, source: str, node_id: str) -> None:
        self.source = source
        self.node_id = node_id


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


def _segment_uncovered_metrics(
    segment: dict[str, Any] | None,
    roads: list[dict[str, Any]],
    *,
    buffer_m: float,
    coverage_cache: dict[tuple[float, tuple[tuple[str, str], ...]], BaseGeometry] | None = None,
) -> tuple[float | None, float | None]:
    segment_geometry = (segment or {}).get("geometry")
    if not isinstance(segment_geometry, BaseGeometry) or segment_geometry.is_empty or segment_geometry.length <= 0:
        return None, None
    buffered_roads = _buffered_road_union(roads, buffer_m=buffer_m, coverage_cache=coverage_cache)
    if buffered_roads is None:
        return 1.0, float(segment_geometry.length)
    uncovered = segment_geometry.difference(buffered_roads)
    length = float(uncovered.length)
    return length / float(segment_geometry.length), length


def _buffered_road_union(
    roads: list[dict[str, Any]],
    *,
    buffer_m: float,
    coverage_cache: dict[tuple[float, tuple[tuple[str, str], ...]], BaseGeometry] | None,
) -> BaseGeometry | None:
    key = _road_buffer_cache_key(roads, buffer_m=buffer_m)
    if coverage_cache is not None and key in coverage_cache:
        return coverage_cache[key]
    road_geometries = [
        line
        for road in roads
        for line in [_feature_line(road)]
        if line is not None and not line.is_empty
    ]
    if not road_geometries:
        return None
    buffered = unary_union(road_geometries).buffer(buffer_m)
    if coverage_cache is not None:
        coverage_cache[key] = buffered
    return buffered


def _road_buffer_cache_key(roads: list[dict[str, Any]], *, buffer_m: float) -> tuple[float, tuple[tuple[str, str], ...]]:
    return (
        float(buffer_m),
        tuple(
            sorted(
                (
                    _source_text((road.get("properties") or {}).get("source")),
                    _feature_id(road),
                )
                for road in roads
            )
        ),
    )


def _segment_nearby_uncovered_metrics(
    segment: dict[str, Any] | None,
    roads: list[dict[str, Any]],
    *,
    buffer_m: float,
) -> tuple[float | None, float | None]:
    segment_geometry = (segment or {}).get("geometry")
    if not isinstance(segment_geometry, BaseGeometry) or segment_geometry.is_empty or segment_geometry.length <= 0:
        return None, None
    search_geometry = segment_geometry.buffer(buffer_m)
    segment_bounds = search_geometry.bounds
    road_geometries: list[LineString] = []
    for road in roads:
        line = _feature_line(road)
        if line is None or line.is_empty:
            continue
        if not _bounds_intersect(segment_bounds, line.bounds):
            continue
        if line.intersects(search_geometry):
            road_geometries.append(line)
    if not road_geometries:
        return 1.0, float(segment_geometry.length)
    road_union = unary_union(road_geometries)
    uncovered = segment_geometry.difference(road_union.buffer(buffer_m))
    length = float(uncovered.length)
    return length / float(segment_geometry.length), length


def _coverage_failed(ratio: float | None, length: float | None) -> bool:
    if ratio is None or length is None:
        return False
    return ratio > SEGMENT_MAX_UNCOVERED_RATIO and length > SEGMENT_MIN_UNCOVERED_LENGTH_M


def _coverage_manual_review(ratio: float | None, length: float | None) -> bool:
    if ratio is None or length is None:
        return False
    return (
        ratio <= SEGMENT_CORRIDOR_MANUAL_REVIEW_MAX_UNCOVERED_RATIO
        and length > SEGMENT_MIN_UNCOVERED_LENGTH_M
    )


def _bounds_intersect(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])


def _reachable_any(graph: dict[str, set[str]], starts: list[str], targets: list[str]) -> bool:
    target_set = set(targets)
    if not starts or not target_set:
        return False
    queue = deque(starts)
    seen = set(starts)
    while queue:
        node = queue.popleft()
        if node in target_set:
            return True
        for next_node in graph.get(node, set()):
            if next_node in seen:
                continue
            seen.add(next_node)
            queue.append(next_node)
    return False


def _road_endpoint_node_ids(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    result: list[str] = []
    for field in ("snodeid", "enodeid"):
        try:
            result.append(normalize_id(props.get(field)))
        except ParseError:
            continue
    return unique_preserve_order(result)


def _road_endpoint_node_id_pair(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    result: list[str] = []
    for field in ("snodeid", "enodeid"):
        try:
            result.append(normalize_id(props.get(field)))
        except ParseError:
            continue
    return result


def _road_endpoint_points(road: dict[str, Any]) -> list[Point]:
    line = _feature_line(road)
    if line is None or line.is_empty:
        return []
    coords = list(line.coords)
    if not coords:
        return []
    return [Point(coords[0]), Point(coords[-1])]


def _max_endpoint_node_distance(
    *,
    source: str,
    endpoints: list[str],
    endpoint_points: list[Point],
    node_index: "_NodeIndex",
) -> float | None:
    distances: list[float] = []
    for node_id, endpoint_point in zip(endpoints[:2], endpoint_points[:2]):
        node = node_index.exact_node(source, node_id)
        geometry = node.get("geometry") if node is not None else None
        if isinstance(geometry, Point):
            distances.append(float(endpoint_point.distance(geometry)))
    return max(distances) if distances else None


def _feature_line(feature_value: dict[str, Any] | None) -> LineString | None:
    if feature_value is None:
        return None
    geometry = feature_value.get("geometry")
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, LineString):
        return geometry
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
        if isinstance(merged, LineString):
            return merged
        parts = [item for item in geometry.geoms if isinstance(item, LineString)]
        return max(parts, key=lambda item: item.length) if parts else None
    if hasattr(geometry, "geoms"):
        parts = [item for item in geometry.geoms if isinstance(item, LineString)]
        return max(parts, key=lambda item: item.length) if parts else None
    return None


def _as_id_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []


def _is_replaced_relation(props: dict[str, Any] | None) -> bool:
    if props is None:
        return False
    return str(props.get("relation_status") or "") != "retained_swsd"


def _is_group_path_corridor_relation(props: dict[str, Any]) -> bool:
    return (
        props.get("relation_reason") == "group_path_corridor_replacement"
        or "group_path_corridor_replacement" in _as_id_list(props.get("risk_flags"))
    )


def _max_pairwise_distance(points: list[Point]) -> float | None:
    if len(points) < 2:
        return 0.0 if points else None
    return max(float(a.distance(b)) for a, b in combinations(points, 2))


def _points_geometry(points: list[Point]) -> Point | MultiPoint | None:
    if not points:
        return None
    if len(points) == 1:
        return points[0]
    return MultiPoint(points)


def _feature_id(feature_item: dict[str, Any]) -> str:
    return normalize_id((feature_item.get("properties") or {}).get("id"))


def _source_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _safe_text(value: Any) -> str:
    if value in (None, "", "None"):
        return ""
    try:
        if value != value:
            return ""
    except Exception:
        pass
    return str(value)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        return round(float(value), 3)
    except (TypeError, ValueError):
        return None


def _round_length(value: float | None) -> float | None:
    return round(float(value), 3) if value is not None else None


def _round_ratio(value: float | None) -> float | None:
    return round(float(value), 6) if value is not None else None


def _id_sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)
