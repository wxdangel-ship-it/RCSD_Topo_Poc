from __future__ import annotations

import json

from collections import defaultdict

from dataclasses import dataclass, field

from pathlib import Path

from typing import Any

from shapely.geometry import LineString, MultiLineString, Point

from shapely.ops import linemerge, unary_union

from .graph_builders import NodeCanonicalizer

from .io import prepare_run_roots, read_features, write_feature_triplet, write_json

from .parallel_output import FeatureTripletJob, publish_feature_triplets

from .parsing import ParseError, normalize_id, parse_id_list, parse_positive_int, unique_preserve_order

from .road_attributes import is_near_advance_right_turn_duplicate as _is_adv_dup

from .schemas import (
    STEP2_GROUP_REPLACEMENT_AUDIT_STEM,
    STEP2_REPLACEMENT_PLAN_STEM,
    STEP2_SPECIAL_JUNCTION_GROUPS_STEM,
    STEP3_ADDED_RCSD_NODES_STEM,
    STEP3_ADDED_RCSD_ROADS_STEM,
    STEP3_CHANGE_AUDIT_FIELDS,
    STEP3_DIR,
    STEP3_FRCSD_NODE_STEM,
    STEP3_FRCSD_ROAD_STEM,
    STEP3_ID_COLLISION_AUDIT_FIELDS,
    STEP3_ID_COLLISION_AUDIT_STEM,
    STEP3_JUNCTION_REBUILD_AUDIT_FIELDS,
    STEP3_JUNCTION_REBUILD_AUDIT_STEM,
    STEP3_REMOVED_SWSD_NODES_STEM,
    STEP3_REMOVED_SWSD_ROADS_STEM,
    STEP3_REPLACEMENT_UNIT_FIELDS,
    STEP3_REPLACEMENT_UNITS_STEM,
    STEP3_SUMMARY,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
    STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
    STEP3_UNREPLACED_RCSD_ROAD_FIELDS,
    STEP3_UNREPLACED_RCSD_ROADS_STEM,
    T06Step3Artifacts,
    feature,
)

from .step3_advance_right_contract import (
    RIGHT_ATTACH_AUDIT_FIELDS,
    RIGHT_ATTACH_AUDIT_STEM,
    _apply_post_advance_right_attachments,
    _is_advance_right_rcsd_road,
    _retain_post_advance_right_swsd_carriers,
    apply_junction_advance_right_contract,
    apply_retained_swsd_segment_attachment_contract,
)

from .step3_endpoint_nodes import ensure_added_rcsd_road_endpoint_nodes, ensure_retained_swsd_road_endpoint_nodes

from .step3_detached_carriers import retain_detached_junc_swsd_roads

from .step3_group_replacement import (
    apply_group_replacement_assignments,
    read_group_replacement_assignments,
    read_group_replacement_assignments_from_plan_rows,
)

from .step3_group_coverage_fallback import retain_group_coverage_fallback

from .step3_output_utils import (
    change_rows as _change_rows,
    feature_id_set as _feature_id_set,
    fieldnames as _fieldnames,
    id_collision_rows as _id_collision_rows,
    unreplaced_rcsd_road_rows as _unreplaced_rcsd_road_rows,
)

from .step3_relation_node_map import backfill_relation_node_maps_from_attachment_audit, sync_retained_swsd_carrier_mainnodes

from .step3_replacement_plan_reader import read_replacement_plan_rows as _read_replacement_plan_rows

from .step3_unreplaced_bridge_fallback import apply_unreplaced_second_degree_bridge_fallback

from .step3_special_junction_internal import apply_special_junction_internal_swsd_replacement as _apply_sji

from .step3_semantic_junction_groups import (
    SEMANTIC_JUNCTION_GROUP_FIELD,
    STEP3_SEMANTIC_JUNCTION_GROUP_FIELDS,
    STEP3_SEMANTIC_JUNCTION_GROUPS_STEM,
    build_semantic_junction_groups,
    downgrade_semantic_junction_topology_rows,
)

from .step3_rcsd_advance_right_closure import (
    RCSD_ADVANCE_RIGHT_CLOSURE_AUDIT_FIELDS,
    RCSD_ADVANCE_RIGHT_CLOSURE_AUDIT_STEM,
    apply_final_advance_right_endpoint_closure as _close_final_adv,
    apply_native_rcsd_advance_right_closure,
    append_advance_attachment_rcsd_nodes,
    final_swsd_road_endpoint_ids as _swsd_ep,
)

from .step3_topology_connectivity_audit import (
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
    build_topology_connectivity_audit_rows,
    summarize_topology_connectivity_audit,
)

from .step3_topology_supplement import (
    FORMAL_REPLACEMENT_CORRIDOR_UNAVAILABLE_REASON,
    MIXED_REPLACEMENT_REQUIRES_SWSD_CARRIER_REASON,
    append_junction_surface_release_risk,
    coverage_failed_after_junction_surface_release,
    exclude_retained_swsd_carriers_from_formal_replacements,
    junction_surface_by_node_id_from_features,
    junction_surface_mask_for_unit,
    materialize_topology_supplement_rcsd_roads,
    swsd_buffer_corridor_release_allows_coverage_gap,
)

INHERITED_NODE_FIELDS = ["kind", "grade", "kind_2", "grade_2", "closed_con"]

TS_MAX_RATIO = 0.05

TS_MIN_LEN_M = 20.0

from .step3_replacement_models import (
    ReplacementUnit,
)

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
    geometry = road.get("geometry")
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, MultiLineString):
        merged = linemerge(geometry)
        if isinstance(merged, LineString):
            geometry = merged
        else:
            geometry = max(geometry.geoms, key=lambda item: item.length)
    if not isinstance(geometry, LineString):
        return []
    coords = list(geometry.coords)
    if not coords:
        return []
    return [Point(coords[0]), Point(coords[-1])]

def _index_by_id(features: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in features:
        try:
            result.setdefault(_feature_id(item), item)
        except ParseError:
            continue
    return result

def _feature_id(feature_item: dict[str, Any]) -> str:
    return normalize_id((feature_item.get("properties") or {}).get("id"))

def _safe_normalize(value: Any) -> str:
    if value in (None, "", "None"):
        return ""
    try:
        if value != value:
            return ""
    except Exception:
        pass
    try:
        return normalize_id(value)
    except ParseError:
        return str(value)

def _coerce_id_value(node_id: str) -> Any:
    return int(node_id) if node_id.isdigit() else node_id

def _parse_list(value: Any) -> list[str]:
    try:
        return parse_id_list(value, allow_empty=True)
    except ParseError:
        return []

def _with_source(item: dict[str, Any], source_field_name: str, source_value: int) -> dict[str, Any]:
    props = dict(item.get("properties") or {})
    props[source_field_name] = source_value
    return feature(props, item.get("geometry"))

def _source_key(item: dict[str, Any], source_field_name: str) -> str:
    return str((item.get("properties") or {}).get(source_field_name))

def _replacement_unit_row(unit: ReplacementUnit) -> dict[str, Any]:
    return {
        "swsd_segment_id": unit.segment_id,
        "unit_status": unit.status,
        "unit_reason": unit.reason,
        "swsd_pair_nodes": unit.pair_nodes,
        "swsd_junc_nodes": unit.junc_nodes,
        "junc_kind2_exempt_nodes": unit.junc_kind2_exempt_nodes,
        "detached_junc_nodes": unit.detached_junc_nodes,
        "retained_detached_swsd_road_ids": unit.retained_detached_swsd_road_ids,
        "swsd_road_ids": unit.original_swsd_road_ids,
        "removed_swsd_road_ids": unit.swsd_road_ids if unit.status == "passed" else [],
        "removed_swsd_node_ids": unit.removed_swsd_node_ids,
        "rcsd_road_ids": unit.rcsd_road_ids,
        "rcsd_node_ids": unit.added_rcsd_node_ids,
        "rcsd_pair_nodes": unit.rcsd_pair_nodes,
        "rcsd_junc_nodes": unit.rcsd_junc_nodes,
        "junction_c_ids": unique_preserve_order([*unit.pair_nodes, *unit.junc_nodes]),
        "group_replacement_plan_ids": unit.group_replacement_plan_ids,
        "group_replacement_source_segment_ids": unit.group_replacement_source_segment_ids,
        "group_replacement_segment_ids": unit.group_replacement_segment_ids,
        "group_replacement_buffer_distances_m": unit.group_replacement_buffer_distances_m,
    }

def _feature_length(feature_item: dict[str, Any]) -> float:
    geometry = feature_item.get("geometry")
    if geometry is None or getattr(geometry, "is_empty", False):
        return 0.0
    return float(getattr(geometry, "length", 0.0) or 0.0)

def _round_length(value: float) -> float:
    return round(float(value), 3)

def _id_sort_key(value: str) -> tuple[int, int | str]:
    parsed = parse_positive_int(value)
    if parsed is not None:
        return (0, parsed)
    return (1, value)
