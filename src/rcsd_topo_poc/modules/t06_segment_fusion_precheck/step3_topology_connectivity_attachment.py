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
def _valid_mainnode_id(node: dict[str, Any] | None) -> str:
    if node is None:
        return ""
    mainnode_id = _safe_text((node.get("properties") or {}).get("mainnodeid"))
    return "" if mainnode_id in {"", "0"} else mainnode_id


def _semantic_junction_group_id(node: dict[str, Any] | None) -> str:
    if node is None:
        return ""
    return _safe_text((node.get("properties") or {}).get("semantic_junction_group_id"))


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
