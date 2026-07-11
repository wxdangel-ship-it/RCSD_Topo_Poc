from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import geopandas as gpd
from shapely.geometry import LineString, MultiLineString, MultiPoint, Point
from shapely.ops import linemerge, substring

from .io import read_features, write_feature_triplet, write_json
from .parsing import normalize_id, unique_preserve_order
from .schemas import (
    STEP2_FAILURE_BUSINESS_AUDIT_STEM,
    STEP2_REPLACEMENT_PLAN_STEM,
    STEP3_FRCSD_NODE_STEM,
    STEP3_FRCSD_ROAD_STEM,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
)
from .step3_relation_node_map import sync_retained_swsd_carrier_mainnodes
from .step3_topology_connectivity_audit import (
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
    build_topology_connectivity_audit_rows,
    summarize_topology_connectivity_audit,
)


SURFACE_TOPOLOGY_AUDIT_STEM = "t06_step3_surface_topology_audit"
SURFACE_TOPOLOGY_SUMMARY = "t06_step3_surface_topology_summary.json"
MAX_EXISTING_CROSS_SOURCE_1V1_DISTANCE_M = 20.0
MAX_T04_PATCH_1V1_DISTANCE_M = 20.0
MAX_RELATION_MAPPED_BOUNDARY_1V1_DISTANCE_M = 20.0
MAX_SURFACE_NEAREST_MULTI_CANDIDATE_DISTANCE_M = 5.0
MIN_SURFACE_NEAREST_MULTI_CANDIDATE_SEPARATION_M = 10.0
SURFACE_NEAREST_MULTI_CANDIDATE_LAYERS = {"t03", "t05"}
MAX_SELECTED_REPLACEMENT_ENDPOINT_DISTANCE_M = 5.0
MAX_SELECTED_REPLACEMENT_ENDPOINT_AMBIGUITY_M = 10.0
MAX_SELECTED_REPLACEMENT_MIDROAD_DISTANCE_M = 5.0
MIN_SELECTED_REPLACEMENT_MIDROAD_ENDPOINT_DISTANCE_M = 1.0
MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_CANDIDATES = 2
MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_GAP_SPREAD_M = 1.0
MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_PROJECTED_DISTANCE_M = 10.0
SELECTED_REPLACEMENT_MIDROAD_SPLIT_REASON = "surface_topology_selected_replacement_midroad"
SURFACE_TOPOLOGY_AUDIT_FIELDS = [
    "audit_layer",
    "audit_status",
    "audit_reason",
    "action",
    "swsd_node_id",
    "swsd_segment_ids",
    "frcsd_node_ids",
    "swsd_patch_ids",
    "surface_patch_ids",
    "surface_layers",
    "surface_candidate_node_ids",
    "t04_reject_reasons",
    "source1_node_count",
    "source2_node_count",
    "max_pairwise_distance_m",
    "closure_mainnodeid",
]


from .step3_surface_topology_support import (
    _load_surfaces,
    _load_t04_rejects,
    _load_step2_optional_junc_mappings,
    _load_step2_dropped_junc_nodes,
    _iter_step2_junc_rows,
    _step2_junc_roots,
    _read_step2_junc_rows,
    _road_features_by_id,
    _road_features_by_id_from_features,
    _relation_props_by_segment,
    _swsd_patch_ids_by_node,
    _node_info,
    _surface_hits,
    _surface_candidate_node_ids,
    _closure_mainnodeid,
    _has_effective_mainnode,
    _can_resolve_closure_mainnode,
    _source2_default_mainnodeid,
    _fieldnames_from_gpkg,
    _feature_id,
    _parse_id_list,
    _patch_ids,
    _safe_id,
    _float_or_none,
    _int_or_none,
    _bool_or_none,
    _distance_within,
    _points_geometry,
)

from .step3_surface_topology_relation import (
    _apply_step2_plan_relation_node_map_updates,
    _set_relation_node_map_entry,
    _apply_relation_node_map_updates,
    _replace_relation_road_ids,
    _selected_midroad_node_ids,
    _upsert_relation_node_map,
    _node_map_entries,
    _rebuild_topology_connectivity_audit,
    _write_topology_connectivity_audit_rows,
    _is_surface_action_row,
    _unique_surface_audit_rows,
    _surface_summary,
    _merge_step3_summary,
)

def _failed_junction_rows(topology_audit: gpd.GeoDataFrame | list[dict[str, Any]]) -> list[Any]:
    if isinstance(topology_audit, list):
        return [
            dict(row.get("properties") or {})
            for row in topology_audit
            if str((row.get("properties") or {}).get("audit_layer") or "") == "segment_junction_connectivity"
            and str((row.get("properties") or {}).get("audit_status") or "") == "fail"
        ]
    failed_junctions = topology_audit[
        (topology_audit["audit_layer"].astype(str) == "segment_junction_connectivity")
        & (topology_audit["audit_status"].astype(str) == "fail")
    ]
    return [row for _, row in failed_junctions.iterrows()]


def _classify_surface_junction(
    *,
    swsd_patch_ids: list[str],
    surface_patch_ids: list[str],
    surface_hits: list[dict[str, Any]],
    t04_rows: list[dict[str, str]],
    source1_nodes: list[dict[str, Any]],
    source2_nodes: list[dict[str, Any]],
    has_surface_1v1_fallback: bool,
    has_t04_patch_1v1_evidence: bool,
    has_t04_reject_node_1v1_evidence: bool,
    has_step2_junc_1v1_evidence: bool,
    has_existing_cross_source_1v1_evidence: bool,
    has_surface_nearest_multi_candidate_evidence: bool,
    has_selected_endpoint_evidence: bool,
    has_selected_midroad_evidence: bool,
    has_relation_mapped_boundary_evidence: bool,
) -> str:
    patch_values = {patch_id for patch_id in [*swsd_patch_ids, *surface_patch_ids] if patch_id}
    if t04_rows:
        if has_t04_reject_node_1v1_evidence and len(source1_nodes) == 1 and source2_nodes and _can_resolve_closure_mainnode(source1_nodes[0], source2_nodes):
            return "auto_candidate_t04_rejected_node_1v1"
        return "blocked_by_t04_reject"
    if has_surface_1v1_fallback and source1_nodes and source2_nodes:
        return "auto_candidate_surface_1v1"
    if has_t04_patch_1v1_evidence and len(source1_nodes) == 1 and source2_nodes and _can_resolve_closure_mainnode(source1_nodes[0], source2_nodes):
        return "auto_candidate_t04_patch_1v1"
    if has_step2_junc_1v1_evidence and len(source1_nodes) == 1 and source2_nodes:
        return "auto_candidate_step2_junc_1v1"
    if has_relation_mapped_boundary_evidence and len(source1_nodes) == 1 and source2_nodes and _can_resolve_closure_mainnode(source1_nodes[0], source2_nodes):
        return "auto_candidate_relation_mapped_boundary_1v1"
    if has_selected_endpoint_evidence and len(source1_nodes) == 1 and source2_nodes:
        return "auto_candidate_selected_replacement_endpoint"
    if has_selected_midroad_evidence and source1_nodes and source2_nodes:
        return "auto_candidate_selected_replacement_midroad"
    if len(patch_values) > 1:
        if has_existing_cross_source_1v1_evidence:
            return "auto_candidate_existing_cross_source_1v1"
        return "blocked_by_patch_conflict"
    if has_surface_nearest_multi_candidate_evidence and len(source1_nodes) > 1 and source2_nodes:
        return "auto_candidate_surface_nearest_multi_candidate"
    if not source1_nodes or not source2_nodes:
        return "manual_missing_cross_source_ref"
    if not surface_hits:
        return "manual_no_surface_evidence"
    if len(source1_nodes) > 1:
        return "manual_multi_rcsd_candidate"
    if len(source1_nodes) == 1 and not _can_resolve_closure_mainnode(source1_nodes[0], source2_nodes):
        return "manual_single_node_default_requires_relation_evidence"
    return "auto_candidate"


def _surface_1v1_fallback_node(
    *,
    swsd_node_id: str,
    surface_hits: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, Any] | None:
    candidate_ids = unique_preserve_order(
        candidate_id
        for hit in surface_hits
        if _is_t07_accepted_1v1_hit(hit, swsd_node_id)
        for candidate_id in hit.get("candidate_node_ids", [])
    )
    valid_candidates: list[str] = []
    for candidate_id in candidate_ids:
        feature_item = node_by_id.get(candidate_id) or _source_node_by_mainnode(
            node_by_id=node_by_id,
            mainnodeid=candidate_id,
            source_field_name=source_field_name,
            source_value=rcsd_source_value,
        )
        if feature_item is None:
            continue
        props = dict(feature_item.get("properties") or {})
        if _safe_id(props.get(source_field_name)) == str(rcsd_source_value):
            valid_candidates.append(_feature_id(feature_item))
    if len(valid_candidates) != 1:
        return None
    return _node_info(node_by_id.get(valid_candidates[0]), valid_candidates[0], source_field_name)


def _source_node_by_mainnode(
    *,
    node_by_id: dict[str, dict[str, Any]],
    mainnodeid: str,
    source_field_name: str,
    source_value: int,
) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for item in node_by_id.values():
        props = dict(item.get("properties") or {})
        if _safe_id(props.get(source_field_name)) != str(source_value):
            continue
        if _safe_id(props.get("mainnodeid")) == mainnodeid:
            matches.append(item)
    return matches[0] if len(matches) == 1 else None


def _step2_optional_junc_fallback_node(
    *,
    swsd_node_id: str,
    swsd_segment_ids: list[str],
    step2_junc_mappings: dict[tuple[str, str], list[str]],
    node_by_id: dict[str, dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, Any] | None:
    candidate_ids = unique_preserve_order(
        candidate_id
        for segment_id in swsd_segment_ids
        for candidate_id in step2_junc_mappings.get((segment_id, swsd_node_id), [])
    )
    valid_candidates: list[str] = []
    for candidate_id in candidate_ids:
        feature_item = node_by_id.get(candidate_id)
        if feature_item is None:
            continue
        props = dict(feature_item.get("properties") or {})
        if _safe_id(props.get(source_field_name)) == str(rcsd_source_value):
            valid_candidates.append(candidate_id)
    if len(unique_preserve_order(valid_candidates)) != 1:
        return None
    return _node_info(node_by_id.get(valid_candidates[0]), valid_candidates[0], source_field_name)


def _surface_nearest_multi_candidate_node(
    *,
    swsd_node_id: str,
    surface_hits: list[dict[str, Any]],
    source1_nodes: list[dict[str, Any]],
    source2_nodes: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if len(source1_nodes) <= 1 or len(source2_nodes) != 1:
        return None
    if not _has_swsd_surface_hit(swsd_node_id, surface_hits):
        return None
    swsd_point = source2_nodes[0].get("point")
    if not isinstance(swsd_point, Point):
        return None
    distances: list[tuple[float, dict[str, Any]]] = []
    for node in source1_nodes:
        point = node.get("point")
        if not isinstance(point, Point):
            continue
        mainnodeid = _safe_id(node.get("mainnodeid"))
        if not mainnodeid or mainnodeid == "0":
            continue
        distances.append((float(point.distance(swsd_point)), node))
    if not distances:
        return None
    distances.sort(key=lambda item: item[0])
    nearest_distance, nearest_node = distances[0]
    if nearest_distance > MAX_SURFACE_NEAREST_MULTI_CANDIDATE_DISTANCE_M:
        return None
    if len(distances) > 1:
        second_distance = distances[1][0]
        if second_distance < nearest_distance + MIN_SURFACE_NEAREST_MULTI_CANDIDATE_SEPARATION_M:
            return None
    return nearest_node


def _selected_replacement_endpoint_fallback_node(
    *,
    swsd_segment_ids: list[str],
    source1_nodes: list[dict[str, Any]],
    source2_nodes: list[dict[str, Any]],
    road_by_id: dict[str, list[dict[str, Any]]],
    relation_by_segment: dict[str, dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, Any] | None:
    if source1_nodes or len(source2_nodes) != 1:
        return None
    swsd_point = source2_nodes[0].get("point")
    if not isinstance(swsd_point, Point):
        return None
    source2_default_mainnodeid = _source2_default_mainnodeid(source2_nodes)
    near_candidates: list[tuple[float, str, str]] = []
    ambiguity_mainnodes: set[str] = set()
    for segment_id in swsd_segment_ids:
        relation = relation_by_segment.get(segment_id)
        if not relation or str(relation.get("relation_status") or "") == "retained_swsd":
            continue
        for road_id in _parse_id_list(relation.get("frcsd_road_ids")):
            for road in road_by_id.get(road_id, []):
                road_props = dict(road.get("properties") or {})
                if _safe_id(road_props.get(source_field_name)) != str(rcsd_source_value):
                    continue
                for endpoint_id in [_safe_id(road_props.get("snodeid")), _safe_id(road_props.get("enodeid"))]:
                    feature_item = node_by_id.get(endpoint_id)
                    if feature_item is None:
                        continue
                    node_props = dict(feature_item.get("properties") or {})
                    if _safe_id(node_props.get(source_field_name)) != str(rcsd_source_value):
                        continue
                    mainnodeid = _safe_id(node_props.get("mainnodeid"))
                    if (not mainnodeid or mainnodeid == "0") and not source2_default_mainnodeid:
                        continue
                    candidate_root = mainnodeid if mainnodeid and mainnodeid != "0" else endpoint_id
                    point = feature_item.get("geometry")
                    if not isinstance(point, Point):
                        continue
                    distance = float(point.distance(swsd_point))
                    if distance <= MAX_SELECTED_REPLACEMENT_ENDPOINT_AMBIGUITY_M:
                        ambiguity_mainnodes.add(candidate_root)
                    if distance <= MAX_SELECTED_REPLACEMENT_ENDPOINT_DISTANCE_M:
                        near_candidates.append((distance, endpoint_id, candidate_root))
    if not near_candidates:
        return None
    near_mainnodes = {item[2] for item in near_candidates}
    if len(near_mainnodes) != 1 or ambiguity_mainnodes - near_mainnodes:
        return None
    _, node_id, _ = sorted(near_candidates, key=lambda item: item[0])[0]
    return _node_info(node_by_id.get(node_id), node_id, source_field_name)


def _selected_replacement_midroad_projection(
    *,
    swsd_segment_ids: list[str],
    source1_nodes: list[dict[str, Any]],
    source2_nodes: list[dict[str, Any]],
    road_by_id: dict[str, list[dict[str, Any]]],
    relation_by_segment: dict[str, dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    node_features: list[dict[str, Any]],
    road_features: list[dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, Any] | None:
    if source1_nodes or len(source2_nodes) != 1:
        return None
    swsd_point = source2_nodes[0].get("point")
    if not isinstance(swsd_point, Point):
        return None
    candidates: list[tuple[float, str, str, float, Point, dict[str, Any]]] = []
    for segment_id in swsd_segment_ids:
        relation = relation_by_segment.get(segment_id)
        if not relation or str(relation.get("relation_status") or "") == "retained_swsd":
            continue
        for road_id in _parse_id_list(relation.get("frcsd_road_ids")):
            for road in road_by_id.get(road_id, []):
                props = dict(road.get("properties") or {})
                if _safe_id(props.get(source_field_name)) != str(rcsd_source_value):
                    continue
                line = _feature_line(road)
                if line is None or line.length <= 0:
                    continue
                distance_m = float(line.project(swsd_point))
                if (
                    distance_m <= MIN_SELECTED_REPLACEMENT_MIDROAD_ENDPOINT_DISTANCE_M
                    or line.length - distance_m <= MIN_SELECTED_REPLACEMENT_MIDROAD_ENDPOINT_DISTANCE_M
                ):
                    continue
                projected = line.interpolate(distance_m)
                gap_m = float(swsd_point.distance(projected))
                if gap_m <= MAX_SELECTED_REPLACEMENT_MIDROAD_DISTANCE_M:
                    candidates.append((gap_m, segment_id, road_id, distance_m, projected, road))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    selected_candidates = _select_midroad_projection_candidates(candidates)
    if not selected_candidates:
        return None
    original_node_features = list(node_features)
    original_road_features = list(road_features)
    added_node_ids: list[str] = []
    node_infos: list[dict[str, Any]] = []
    road_replacements: dict[str, list[str]] = {}
    for _gap_m, _segment_id, road_id, distance_m, projected, road in selected_candidates:
        generated_node_id = _next_generated_id(node_by_id, prefix="t06_surfnode")
        node = _new_midroad_node(
            node_id=generated_node_id,
            point=projected,
            node_by_id=node_by_id,
            source_field_name=source_field_name,
            rcsd_source_value=rcsd_source_value,
        )
        split_road_ids = _split_midroad_projection_road(
            road=road,
            road_id=road_id,
            distance_m=distance_m,
            node_id=generated_node_id,
            road_features=road_features,
        )
        if not split_road_ids:
            node_features[:] = original_node_features
            road_features[:] = original_road_features
            for added_node_id in added_node_ids:
                node_by_id.pop(added_node_id, None)
            road_by_id.clear()
            road_by_id.update(_road_features_by_id_from_features(road_features))
            return None
        node_features.append(node)
        node_by_id[generated_node_id] = node
        added_node_ids.append(generated_node_id)
        node_infos.append(_node_info(node, generated_node_id, source_field_name))
        road_replacements[road_id] = split_road_ids
    road_by_id.clear()
    road_by_id.update(_road_features_by_id_from_features(road_features))
    return {
        "node_info": node_infos[0],
        "node_infos": node_infos,
        "road_replacements": road_replacements,
    }


def _select_midroad_projection_candidates(
    candidates: list[tuple[float, str, str, float, Point, dict[str, Any]]],
) -> list[tuple[float, str, str, float, Point, dict[str, Any]]]:
    nearest = candidates[0]
    near_candidates = [
        candidate
        for candidate in candidates
        if candidate[0] <= nearest[0] + MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_GAP_SPREAD_M
    ]
    if len(near_candidates) == 1:
        if len(candidates) > 1 and candidates[1][0] <= nearest[0] + MAX_SELECTED_REPLACEMENT_ENDPOINT_AMBIGUITY_M:
            return []
        return [nearest]
    if len(near_candidates) > MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_CANDIDATES:
        return []
    if len({candidate[1] for candidate in near_candidates}) != 1:
        return []
    projected_points = [candidate[4] for candidate in near_candidates]
    if any(
        float(left.distance(right)) > MAX_SELECTED_REPLACEMENT_MIDROAD_MULTI_PROJECTED_DISTANCE_M
        for index, left in enumerate(projected_points)
        for right in projected_points[index + 1 :]
    ):
        return []
    return near_candidates


def _new_midroad_node(
    *,
    node_id: str,
    point: Point,
    node_by_id: dict[str, dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, Any]:
    template = dict(next(iter(node_by_id.values())).get("properties") or {}) if node_by_id else {}
    props = {key: None for key in template}
    value = int(node_id) if node_id.isdigit() else node_id
    props.update(
        {
            "id": value,
            "mainnodeid": value,
            source_field_name: rcsd_source_value,
            "t06_generated_reason": SELECTED_REPLACEMENT_MIDROAD_SPLIT_REASON,
        }
    )
    return {"properties": props, "geometry": point}


def _split_midroad_projection_road(
    *,
    road: dict[str, Any],
    road_id: str,
    distance_m: float,
    node_id: str,
    road_features: list[dict[str, Any]],
) -> list[str]:
    line = _feature_line(road)
    if line is None or line.length <= 0:
        return []
    endpoints = _road_endpoint_ids(road)
    if len(endpoints) < 2:
        return []
    split_ids = _next_split_road_ids(road_features, road_id)
    boundaries = [(0.0, endpoints[0]), (distance_m, node_id), (float(line.length), endpoints[-1])]
    split_roads: list[dict[str, Any]] = []
    for index in range(2):
        start_m, start_node = boundaries[index]
        end_m, end_node = boundaries[index + 1]
        segment = substring(line, start_m, end_m)
        if segment is None or segment.is_empty or not isinstance(segment, LineString):
            return []
        props = dict(road.get("properties") or {})
        split_id = split_ids[index]
        props.update(
            {
                "id": int(split_id) if split_id.isdigit() else split_id,
                "snodeid": int(start_node) if start_node.isdigit() else start_node,
                "enodeid": int(end_node) if end_node.isdigit() else end_node,
                "t06_split_original_road_id": road_id,
                "t06_split_reason": SELECTED_REPLACEMENT_MIDROAD_SPLIT_REASON,
            }
        )
        split_roads.append({"properties": props, "geometry": segment})
    for index, item in enumerate(list(road_features)):
        if item is road:
            road_features[index:index + 1] = split_roads
            return split_ids
    for index, item in enumerate(list(road_features)):
        if _safe_id((item.get("properties") or {}).get("id")) == road_id:
            road_features[index:index + 1] = split_roads
            return split_ids
    return []


def _road_endpoint_ids(road: dict[str, Any]) -> list[str]:
    props = dict(road.get("properties") or {})
    return unique_preserve_order(
        node_id for node_id in [_safe_id(props.get("snodeid")), _safe_id(props.get("enodeid"))] if node_id
    )


def _feature_line(feature_item: dict[str, Any] | None) -> LineString | None:
    geometry = feature_item.get("geometry") if feature_item is not None else None
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
    return None


def _next_split_road_ids(road_features: list[dict[str, Any]], road_id: str) -> list[str]:
    next_numeric = _next_numeric_id(_safe_id((road.get("properties") or {}).get("id")) for road in road_features)
    if next_numeric is not None:
        return [str(next_numeric), str(next_numeric + 1)]
    used = {_safe_id((road.get("properties") or {}).get("id")) for road in road_features}
    result: list[str] = []
    index = 1
    while len(result) < 2:
        candidate = f"{road_id}__t06surfmid_{index}"
        index += 1
        if candidate in used:
            continue
        used.add(candidate)
        result.append(candidate)
    return result


def _next_generated_id(items: dict[str, Any], *, prefix: str) -> str:
    next_numeric = _next_numeric_id(items)
    if next_numeric is not None:
        return str(next_numeric)
    index = 1
    while f"{prefix}_{index}" in items:
        index += 1
    return f"{prefix}_{index}"


def _next_numeric_id(values: Any) -> int | None:
    parsed_values: list[int] = []
    for value in values:
        text = str(value)
        if not text.isdigit():
            return None
        parsed_values.append(int(text))
    return max(parsed_values, default=0) + 1


def _relation_mapped_boundary_fallback_node(
    *,
    swsd_node_id: str,
    swsd_segment_ids: list[str],
    relation_by_segment: dict[str, dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    source2_nodes: list[dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, Any] | None:
    if not swsd_node_id or len(source2_nodes) != 1:
        return None
    swsd_point = source2_nodes[0].get("point")
    if not isinstance(swsd_point, Point):
        return None
    has_retained_identity = False
    candidate_ids: list[str] = []
    for segment_id in swsd_segment_ids:
        relation = relation_by_segment.get(segment_id)
        if not relation:
            continue
        status = str(relation.get("relation_status") or "")
        entries = _node_map_entries(relation.get("swsd_to_frcsd_node_map"))
        matching_entries = [entry for entry in entries if _safe_id(entry.get("swsd_node_id")) == swsd_node_id]
        if status == "retained_swsd":
            has_retained_identity = has_retained_identity or any(
                _parse_id_list(entry.get("frcsd_node_ids")) == [swsd_node_id] for entry in matching_entries
            )
            continue
        for entry in matching_entries:
            entry_status = str(entry.get("mapping_status") or "")
            mapped_ids = _parse_id_list(entry.get("frcsd_node_ids"))
            if entry_status in {"", "missing", "identity"} or len(mapped_ids) != 1:
                continue
            mapped_id = mapped_ids[0]
            if mapped_id == swsd_node_id:
                continue
            candidate_ids.append(mapped_id)
    if not has_retained_identity:
        return None
    candidate_ids = unique_preserve_order(candidate_ids)
    if len(candidate_ids) != 1:
        return None
    candidate_id = candidate_ids[0]
    feature_item = node_by_id.get(candidate_id)
    if feature_item is None:
        return None
    props = dict(feature_item.get("properties") or {})
    if _safe_id(props.get(source_field_name)) != str(rcsd_source_value):
        return None
    candidate_point = feature_item.get("geometry")
    if not isinstance(candidate_point, Point):
        return None
    return _node_info(feature_item, candidate_id, source_field_name)


def _has_swsd_surface_hit(swsd_node_id: str, surface_hits: list[dict[str, Any]]) -> bool:
    for hit in surface_hits:
        if hit.get("layer") not in SURFACE_NEAREST_MULTI_CANDIDATE_LAYERS:
            continue
        if _safe_id(hit.get("mainnodeid")) == swsd_node_id:
            return True
    return False


def _is_t07_accepted_1v1_hit(hit: dict[str, Any], swsd_node_id: str) -> bool:
    if hit.get("layer") != "t07":
        return False
    if str(hit.get("final_state") or "") != "accepted":
        return False
    node_refs = {
        _safe_id(hit.get("target_id")),
        _safe_id(hit.get("representative_node_id")),
        _safe_id(hit.get("mainnodeid")),
    }
    if swsd_node_id not in node_refs:
        return False
    return len(hit.get("candidate_node_ids", [])) == 1


def _has_t04_patch_1v1_evidence(
    *,
    swsd_node_id: str,
    swsd_patch_ids: list[str],
    surface_hits: list[dict[str, Any]],
) -> bool:
    swsd_patch_set = {patch_id for patch_id in swsd_patch_ids if patch_id}
    if not swsd_patch_set:
        return False
    for hit in surface_hits:
        if hit.get("layer") != "t04":
            continue
        if str(hit.get("final_state") or "") != "accepted":
            continue
        hit_patch_ids = {patch_id for patch_id in hit.get("patch_ids", []) if patch_id}
        if not hit_patch_ids or not hit_patch_ids.issubset(swsd_patch_set):
            continue
        node_refs = {
            _safe_id(hit.get("anchor_id")),
            _safe_id(hit.get("case_id")),
            _safe_id(hit.get("mainnodeid")),
        }
        if swsd_node_id in node_refs:
            return True
    return False


def _t04_reject_node_1v1_fallback_node(
    *,
    t04_rows: list[dict[str, Any]],
    source2_nodes: list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    source_field_name: str,
    rcsd_source_value: int,
) -> dict[str, Any] | None:
    if not t04_rows or len(source2_nodes) != 1:
        return None
    swsd_point = source2_nodes[0].get("point")
    if not isinstance(swsd_point, Point):
        return None
    candidate_ids: list[str] = []
    for row in t04_rows:
        if not _is_t04_reject_node_1v1_allowed(row):
            continue
        required_ids = unique_preserve_order(_parse_id_list(row.get("required_rcsd_node_ids")))
        declared_count = _int_or_none(row.get("required_rcsd_node_count"))
        if declared_count is not None and declared_count != 1:
            continue
        if len(required_ids) != 1:
            continue
        candidate_ids.extend(required_ids)
    candidate_ids = unique_preserve_order(candidate_ids)
    if len(candidate_ids) != 1:
        return None
    candidate_id = candidate_ids[0]
    feature_item = node_by_id.get(candidate_id)
    if feature_item is None:
        return None
    props = dict(feature_item.get("properties") or {})
    if _safe_id(props.get(source_field_name)) != str(rcsd_source_value):
        return None
    point = feature_item.get("geometry")
    if not isinstance(point, Point):
        return None
    if float(point.distance(swsd_point)) > MAX_EXISTING_CROSS_SOURCE_1V1_DISTANCE_M:
        return None
    return _node_info(feature_item, candidate_id, source_field_name)


def _is_t04_reject_node_1v1_allowed(row: dict[str, Any]) -> bool:
    if str(row.get("reject_reason") or "") != "multi_component_result":
        return False
    for key in (
        "hard_must_cover_ok",
        "post_cleanup_forbidden_ok",
        "post_cleanup_terminal_cut_ok",
        "post_cleanup_lateral_limit_ok",
        "post_cleanup_must_cover_ok",
    ):
        if key in row and row[key] is False:
            return False
    for key in ("forbidden_overlap", "cut_violation", "fallback_overexpansion_detected"):
        if key in row and row[key] is True:
            return False
    return True
