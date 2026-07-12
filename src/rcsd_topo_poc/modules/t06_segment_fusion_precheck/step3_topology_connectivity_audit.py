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
from .step3_final_topology_metric import (
    annotate_final_frcsd_topology_rows,
    summarize_final_frcsd_topology,
)
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

from .step3_topology_connectivity_rows import (
    _segment_internal_rows,
    _segment_road_rows,
    _segment_junction_rows,
    _retained_swsd_endpoint_closure_rows,
    _patch_attachment_rows,
    _is_swsd_topology_supplement,
)

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
    coverage_cache: CoverageCache | None = None,
) -> list[dict[str, Any]]:
    node_index = _NodeIndex(frcsd_nodes, source_field_name=source_field_name)
    road_index = _RoadIndex(frcsd_roads, source_field_name=source_field_name)
    canonicalizer = NodeCanonicalizer.from_node_features(frcsd_nodes)
    final_graph = _DirectedRoadGraph(frcsd_roads, canonicalizer=canonicalizer)
    final_road_index = _RoadLineSpatialIndex(frcsd_roads)
    relation_props = [dict(row.get("properties") or {}) for row in segment_relation_rows]
    relation_by_segment = {str(props.get("swsd_segment_id")): props for props in relation_props}
    attachment_refs_by_node = _attachment_refs_by_swsd_node(
        advance_right_audit_rows,
        rcsd_source_value=rcsd_source_value,
    )
    if coverage_cache is None:
        coverage_cache = {}
    road_signature_cache: RoadSignatureCache = {}
    _prewarm_relation_coverage_cache(
        relation_props,
        road_index=road_index,
        coverage_cache=coverage_cache,
        signature_cache=road_signature_cache,
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
            final_road_index=final_road_index,
            final_graph=final_graph,
            canonicalizer=canonicalizer,
            rcsd_source_value=rcsd_source_value,
            swsd_source_value=swsd_source_value,
            attachment_refs_by_node=attachment_refs_by_node,
            coverage_cache=coverage_cache,
            road_signature_cache=road_signature_cache,
        )
    )
    rows.extend(
        _segment_road_rows(
            swsd_segments=swsd_segments,
            swsd_roads=swsd_roads or [],
            relation_props=relation_props,
            road_index=road_index,
            final_roads=frcsd_roads,
            final_road_index=final_road_index,
            final_graph=final_graph,
            canonicalizer=canonicalizer,
            rcsd_source_value=rcsd_source_value,
            swsd_source_value=swsd_source_value,
            attachment_refs_by_node=attachment_refs_by_node,
            coverage_cache=coverage_cache,
            road_signature_cache=road_signature_cache,
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
        _retained_swsd_endpoint_closure_rows(
            relation_props=relation_props,
            road_index=road_index,
            node_index=node_index,
            swsd_source_value=swsd_source_value,
            rcsd_source_value=rcsd_source_value,
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
    result = [row for row in rows if (row.get("properties") or {}).get("audit_status")]
    annotate_final_frcsd_topology_rows(result)
    return result


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
        road_lineage_id = str(
            props.get("t06_split_original_road_id")
            or props.get("source_road_id")
            or road_id
        )
        endpoint_ids = _road_endpoint_node_id_pair(road)
        endpoint_points = _road_endpoint_points(road)
        if len(endpoint_ids) < 2:
            continue
        try:
            accepted_native_boundary_node_ids = set(
                parse_id_list(props.get("t06_accepted_native_boundary_node_ids"), allow_empty=True)
            )
        except ParseError:
            accepted_native_boundary_node_ids = set()
        legacy_road_level_acceptance = (
            "t06_accepted_native_boundary_node_ids" not in props
            and bool(props.get("t06_accepted_native_boundary_leaf"))
        )
        segment_ids = selected_segment_ids_by_road.get(road_id, [])
        for index, node_id in enumerate(endpoint_ids[:2]):
            canonical_id = _canonicalize_node(canonicalizer, node_id)
            degree = node_degree.get(canonical_id, 0)
            status = "pass"
            reason = "advance_right_endpoint_connected_to_frcsd_network"
            owner = ""
            if degree <= 1:
                if node_id in accepted_native_boundary_node_ids or legacy_road_level_acceptance:
                    status = "warn"
                    reason = "advance_right_leaf_endpoint_accepted_native_rcsd_boundary"
                else:
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
                        "topology_road_lineage_id": road_lineage_id,
                        "topology_endpoint_index": index,
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
        retained_ids = set(_as_id_list(props.get("retained_detached_swsd_road_ids")))
        road_ids = [road_id for road_id in _as_id_list(props.get("frcsd_road_ids")) if road_id not in retained_ids]
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
        is_group_path_corridor = _is_group_path_corridor_relation(props)
        if swsd_derived_ids:
            status = "warn" if is_group_path_corridor else "fail"
            reason = (
                "group_path_corridor_contains_swsd_topology_supplement_review"
                if is_group_path_corridor
                else "formal_replacement_contains_swsd_topology_supplement"
            )
            owner = (
                "T06_step3_group_replacement_manual_audit"
                if is_group_path_corridor
                else "T06_step3_relation_source_boundary"
            )
        elif non_rcsd_ids:
            status = "warn" if is_group_path_corridor else "fail"
            reason = (
                "group_path_corridor_contains_retained_swsd_source_review"
                if is_group_path_corridor
                else "formal_replacement_contains_non_rcsd_source"
            )
            owner = (
                "T06_step3_group_replacement_manual_audit"
                if is_group_path_corridor
                else "T06_step3_relation_source_boundary"
            )
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
    annotate_final_frcsd_topology_rows(rows)
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
    counts["topology_audit_fail_row_count"] = counts["topology_connectivity_fail_count"]
    counts.update(summarize_final_frcsd_topology(rows))
    return counts
