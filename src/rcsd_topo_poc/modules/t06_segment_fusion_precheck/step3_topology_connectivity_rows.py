from __future__ import annotations

import json
import hashlib
from collections import defaultdict, deque
from itertools import combinations
from typing import Any

from shapely import buffer as vectorized_buffer
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge, unary_union
from shapely.strtree import STRtree

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
    "final_topology_category",
    "final_topology_object_key",
    "counts_in_final_frcsd_topology_fail",
    "topology_road_lineage_id",
    "topology_endpoint_index",
]
TOPOLOGY_CONNECTIVITY_AUDIT_LAYERS = [
    "final_road_node_integrity",
    "formal_replacement_source_consistency",
    "segment_internal_connectivity",
    "segment_road_connectivity",
    "retained_swsd_endpoint_closure",
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
SWSD_BUFFER_CORRIDOR_RELEASE_RISK = "swsd_buffer_corridor_controlled_release"
CoverageCacheKey = tuple[float, tuple[tuple[str, str, str], ...]]
CoverageCache = dict[CoverageCacheKey, BaseGeometry]
RoadSignature = tuple[tuple[str, str, str], ...]
RoadSignatureCache = dict[tuple[int, ...], tuple[tuple[dict[str, Any], ...], RoadSignature]]


from .step3_topology_connectivity_support import (
    _DirectedRoadGraph,
    _RoadIndex,
    _RoadLineSpatialIndex,
    _NodeIndex,
    _NodeRef,
    _node_map_entries,
    _segment_uncovered_metrics,
    _buffered_road_union,
    _prewarm_relation_coverage_cache,
    _road_buffer_cache_key,
    _road_signature,
    _feature_line_digest,
    _segment_nearby_uncovered_metrics,
    _coverage_failed,
    _coverage_manual_review,
    _bounds_intersect,
    _reachable_any,
    _road_endpoint_node_ids,
    _road_endpoint_node_id_pair,
    _road_endpoint_points,
    _max_endpoint_node_distance,
    _feature_line,
    _as_id_list,
    _is_replaced_relation,
    _is_group_path_corridor_relation,
    _max_pairwise_distance,
    _points_geometry,
    _feature_id,
    _source_text,
    _safe_text,
    _coerce_int,
    _coerce_float,
    _round_length,
    _round_ratio,
    _id_sort_key,
    _relation_roads,
)

from .step3_topology_connectivity_attachment import (
    _attachment_status,
    _swsd_mainnode_is_attached_to_alternate_rcsd,
    _has_incident_road_in_mainnode_group,
    _road_directed_path_missing,
    _retained_swsd_relation_road_ids,
    _retained_swsd_identity_refs_by_node,
    _valid_mainnode_id,
    _semantic_junction_group_id,
    _mapped_node_refs_for_swsd_node,
    _attachment_refs_by_swsd_node,
)

def _segment_internal_rows(
    *,
    swsd_segments: list[dict[str, Any]],
    relation_props: list[dict[str, Any]],
    road_index: "_RoadIndex",
    final_roads: list[dict[str, Any]],
    final_road_index: "_RoadLineSpatialIndex",
    final_graph: "_DirectedRoadGraph",
    canonicalizer: NodeCanonicalizer,
    rcsd_source_value: int,
    swsd_source_value: int,
    attachment_refs_by_node: dict[str, list["_NodeRef"]],
    coverage_cache: CoverageCache,
    road_signature_cache: RoadSignatureCache,
) -> list[dict[str, Any]]:
    segment_by_id = {_feature_id(segment): segment for segment in swsd_segments}
    rows: list[dict[str, Any]] = []
    for props in relation_props:
        segment_id = str(props.get("swsd_segment_id") or "")
        if not segment_id:
            continue
        segment = segment_by_id.get(segment_id)
        relation_status = str(props.get("relation_status") or "")
        is_group_path_corridor = _is_group_path_corridor_relation(props)
        is_swsd_buffer_corridor_release = SWSD_BUFFER_CORRIDOR_RELEASE_RISK in _as_id_list(props.get("risk_flags"))
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
            road_signature_cache=road_signature_cache,
        )
        corridor_uncovered_ratio, corridor_uncovered_length = _segment_uncovered_metrics(
            segment,
            selected_roads,
            buffer_m=SEGMENT_CORRIDOR_BUFFER_M,
            coverage_cache=coverage_cache,
            road_signature_cache=road_signature_cache,
        )
        final_corridor_uncovered_ratio: float | None = None
        final_corridor_uncovered_length: float | None = None

        missing_mapping_count = sum(1 for refs in mapped_pair_nodes if not refs)
        strict_coverage_failed = _coverage_failed(uncovered_ratio, uncovered_length)
        corridor_coverage_failed = _coverage_failed(corridor_uncovered_ratio, corridor_uncovered_length)
        status = "pass"
        reason = "segment_internal_connectivity_passed"
        owner = ""
        action = ""
        action_reason = ""
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
                road_spatial_index=final_road_index,
            )
            if is_group_path_corridor:
                status = "warn"
                reason = "group_path_corridor_segment_local_coverage_review"
                owner = "T06_step3_group_replacement_manual_audit"
            elif is_swsd_buffer_corridor_release:
                status = "warn"
                reason = "swsd_buffer_corridor_coverage_manual_review_after_replacement"
                owner = "T06_manual_visual_geometry_review"
                action = "manual_review_required"
                action_reason = SWSD_BUFFER_CORRIDOR_RELEASE_RISK
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
                    "action": action,
                    "action_reason": action_reason,
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
    final_road_index: "_RoadLineSpatialIndex",
    final_graph: "_DirectedRoadGraph",
    canonicalizer: NodeCanonicalizer,
    rcsd_source_value: int,
    swsd_source_value: int,
    attachment_refs_by_node: dict[str, list["_NodeRef"]],
    coverage_cache: CoverageCache,
    road_signature_cache: RoadSignatureCache,
) -> list[dict[str, Any]]:
    segment_by_id = {_feature_id(segment): segment for segment in swsd_segments}
    swsd_road_by_id = {_feature_id(road): road for road in swsd_roads}
    rows: list[dict[str, Any]] = []
    for props in relation_props:
        segment_id = str(props.get("swsd_segment_id") or "")
        segment = segment_by_id.get(segment_id)
        relation_status = str(props.get("relation_status") or "")
        if not segment_id or relation_status in {"", "failed", "retained_swsd"}:
            continue
        segment_props = dict((segment or {}).get("properties") or {})
        is_group_path_corridor = _is_group_path_corridor_relation(props)
        risk_flags = _as_id_list(props.get("risk_flags"))
        has_junction_surface_coverage_release = JUNCTION_SURFACE_COVERAGE_RELEASE_RISK in risk_flags
        is_swsd_buffer_corridor_release = SWSD_BUFFER_CORRIDOR_RELEASE_RISK in risk_flags
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
                road_signature_cache=road_signature_cache,
            )
            corridor_uncovered_ratio, corridor_uncovered_length = _segment_uncovered_metrics(
                swsd_road,
                selected_roads,
                buffer_m=SEGMENT_CORRIDOR_BUFFER_M,
                coverage_cache=coverage_cache,
                road_signature_cache=road_signature_cache,
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
                status = "warn" if is_group_path_corridor else "fail"
                reason = (
                    "group_path_corridor_road_endpoint_connectivity_review"
                    if is_group_path_corridor
                    else "segment_road_endpoints_not_connected"
                )
                owner = (
                    "T06_step3_group_replacement_manual_audit"
                    if is_group_path_corridor
                    else "T06_step2_replacement_plan_or_step3_graph_selection"
                )
                if final_undirected_connected:
                    status = "warn"
                    reason = "segment_road_relation_scope_incomplete_but_final_graph_connected"
                    owner = "T06_step3_segment_relation"
            elif directed_path_missing:
                status = "warn" if is_group_path_corridor else "fail"
                reason = (
                    "group_path_corridor_road_directionality_review"
                    if is_group_path_corridor
                    else "segment_road_directed_path_missing"
                )
                owner = (
                    "T06_step3_group_replacement_manual_audit"
                    if is_group_path_corridor
                    else "T06_step2_replacement_plan_or_step3_graph_selection"
                )
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
                buffer_corridor_release_review = is_swsd_buffer_corridor_release and not is_group_path_corridor
                status = "warn" if is_group_path_corridor or surface_release_review or buffer_corridor_release_review else "fail"
                reason = (
                    "group_path_corridor_road_local_coverage_review"
                    if is_group_path_corridor
                    else "segment_road_corridor_coverage_inside_junction_surface_review"
                    if surface_release_review
                    else "swsd_buffer_corridor_road_coverage_manual_review_after_replacement"
                    if buffer_corridor_release_review
                    else "segment_road_corridor_coverage_dropped_after_replacement"
                )
                owner = (
                    "T06_step3_group_replacement_manual_audit"
                    if is_group_path_corridor
                    else "T06_manual_visual_geometry_review"
                    if surface_release_review or buffer_corridor_release_review
                    else "T06_step2_replacement_plan_or_group_selection"
                )
                if surface_release_review or buffer_corridor_release_review:
                    action = "manual_review_required"
                    action_reason = (
                        JUNCTION_SURFACE_COVERAGE_RELEASE_RISK
                        if surface_release_review
                        else SWSD_BUFFER_CORRIDOR_RELEASE_RISK
                    )
                final_corridor_uncovered_ratio, final_corridor_uncovered_length = _segment_nearby_uncovered_metrics(
                    swsd_road,
                    final_roads,
                    buffer_m=SEGMENT_CORRIDOR_BUFFER_M,
                    road_spatial_index=final_road_index,
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


def _retained_swsd_endpoint_closure_rows(
    *,
    relation_props: list[dict[str, Any]],
    road_index: "_RoadIndex",
    node_index: "_NodeIndex",
    swsd_source_value: int,
    rcsd_source_value: int,
) -> list[dict[str, Any]]:
    swsd_source = str(swsd_source_value)
    rcsd_source = str(rcsd_source_value)
    rows: list[dict[str, Any]] = []
    for props in relation_props:
        relation_status = str(props.get("relation_status") or "")
        if relation_status != "replaced+retained_swsd":
            continue
        segment_id = str(props.get("swsd_segment_id") or "")
        if not segment_id:
            continue
        retained_road_ids = _as_id_list(props.get("retained_detached_swsd_road_ids"))
        if not retained_road_ids:
            continue
        for road_id in retained_road_ids:
            for road_source, road in road_index.roads_for_id(road_id):
                if road_source != swsd_source:
                    continue
                endpoint_ids = _road_endpoint_node_id_pair(road)
                endpoint_points = _road_endpoint_points(road)
                for index, swsd_node_id in enumerate(endpoint_ids[:2]):
                    swsd_ref = _NodeRef(swsd_source, swsd_node_id)
                    swsd_node = node_index.exact_node(swsd_source, swsd_node_id)
                    mapped_refs = [
                        ref
                        for ref in _mapped_node_refs_for_swsd_node(
                            props,
                            swsd_node_id,
                            rcsd_source_value,
                            swsd_source_value,
                        )
                        if ref.source == rcsd_source
                    ]
                    mapped_node_ids = unique_preserve_order([ref.node_id for ref in mapped_refs])
                    mapped_mainnode_roots = unique_preserve_order(
                        [
                            root
                            for ref in mapped_refs
                            for root in [node_index.mainnode_root_for_ref(ref)]
                            if root
                        ]
                    )
                    mapped_semantic_groups = unique_preserve_order(
                        [
                            group_id
                            for ref in mapped_refs
                            for group_id in [_semantic_junction_group_id(node_index.node_for_ref(ref))]
                            if group_id
                        ]
                    )
                    swsd_mainnode = _valid_mainnode_id(swsd_node)
                    swsd_mainnode_root = node_index.mainnode_root_for_ref(swsd_ref) if swsd_mainnode else ""
                    swsd_semantic_group = _semantic_junction_group_id(swsd_node)
                    has_swsd_semantic_group = bool(swsd_semantic_group)
                    semantic_group_matches = bool(
                        swsd_semantic_group and swsd_semantic_group in set(mapped_semantic_groups)
                    )
                    status = "pass"
                    reason = "retained_swsd_endpoint_mainnode_closed_to_mapped_rcsd"
                    owner = ""
                    if swsd_node is None:
                        status = "fail"
                        reason = "retained_swsd_endpoint_node_missing_in_final"
                    elif not mapped_refs:
                        status = "warn"
                        reason = "retained_swsd_endpoint_without_rcsd_mapping_review"
                    elif not mapped_mainnode_roots:
                        status = "fail"
                        reason = "retained_swsd_endpoint_mapped_rcsd_mainnode_missing"
                    elif not swsd_mainnode:
                        status = "fail"
                        reason = (
                            "semantic_group_only_mainnode_not_closed"
                            if has_swsd_semantic_group
                            else "retained_swsd_endpoint_mainnode_blank"
                        )
                    elif swsd_mainnode not in mapped_mainnode_roots and swsd_mainnode_root not in mapped_mainnode_roots:
                        status = "fail"
                        reason = (
                            "semantic_group_matches_but_mainnode_mismatch"
                            if semantic_group_matches
                            else "retained_swsd_endpoint_mainnode_mismatch"
                        )
                    if status == "fail":
                        owner = "T06_step3_retained_swsd_endpoint_closure"
                    elif status == "warn":
                        owner = "T06_step3_retained_swsd_endpoint_closure_review"
                    rows.append(
                        feature(
                            {
                                "audit_layer": "retained_swsd_endpoint_closure",
                                "audit_status": status,
                                "audit_reason": reason,
                                "recommended_owner": owner,
                                "swsd_segment_id": segment_id,
                                "swsd_segment_ids": [segment_id],
                                "swsd_node_id": swsd_node_id,
                                "swsd_road_id": road_id,
                                "frcsd_road_id": "",
                                "frcsd_node_ids": mapped_node_ids,
                                "relation_status": relation_status,
                                "source_mix": props.get("source_mix") or "",
                                "directionality": f"road_endpoint_{index}",
                                "pair_nodes": endpoint_ids[:2],
                                "path_forward": None,
                                "path_reverse": None,
                                "undirected_connected": None,
                                "mapped_node_count": len(mapped_refs),
                                "missing_mapping_count": 0 if mapped_refs else 1,
                                "max_pairwise_distance_m": None,
                                "coverage_buffer_m": None,
                                "uncovered_ratio": None,
                                "uncovered_length_m": None,
                                "corridor_buffer_m": None,
                                "corridor_uncovered_ratio": None,
                                "corridor_uncovered_length_m": None,
                                "final_path_forward": None,
                                "final_path_reverse": None,
                                "final_undirected_connected": status == "pass",
                                "final_corridor_uncovered_ratio": None,
                                "final_corridor_uncovered_length_m": None,
                                "projected_gap_m": None,
                                "action": "verify_retained_swsd_endpoint_mainnode_closure",
                                "action_reason": "+".join(mapped_mainnode_roots),
                            },
                            endpoint_points[index] if index < len(endpoint_points) else node_index.point_for_ref(swsd_ref),
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
