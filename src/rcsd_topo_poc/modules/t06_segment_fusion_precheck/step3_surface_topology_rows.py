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

from .step3_surface_topology_selection import (
    _failed_junction_rows,
    _classify_surface_junction,
    _surface_1v1_fallback_node,
    _source_node_by_mainnode,
    _step2_optional_junc_fallback_node,
    _surface_nearest_multi_candidate_node,
    _selected_replacement_endpoint_fallback_node,
    _selected_replacement_midroad_projection,
    _select_midroad_projection_candidates,
    _new_midroad_node,
    _split_midroad_projection_road,
    _road_endpoint_ids,
    _feature_line,
    _next_split_road_ids,
    _next_generated_id,
    _next_numeric_id,
    _relation_mapped_boundary_fallback_node,
    _has_swsd_surface_hit,
    _is_t07_accepted_1v1_hit,
    _has_t04_patch_1v1_evidence,
    _t04_reject_node_1v1_fallback_node,
    _is_t04_reject_node_1v1_allowed,
)

def _build_surface_audit_rows(
    *,
    topology_audit: gpd.GeoDataFrame | list[dict[str, Any]],
    node_by_id: dict[str, dict[str, Any]],
    node_features: list[dict[str, Any]],
    road_features: list[dict[str, Any]],
    node_patch_ids: dict[str, set[str]],
    surfaces: dict[str, gpd.GeoDataFrame],
    t04_rejects: dict[str, list[dict[str, str]]],
    step2_junc_mappings: dict[tuple[str, str], list[str]],
    road_by_id: dict[str, list[dict[str, Any]]],
    relation_by_segment: dict[str, dict[str, Any]],
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
    apply_closure: bool,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    closure_updates: list[str] = []
    relation_updates: list[dict[str, Any]] = []
    materialized_updates: list[str] = []
    for row in _failed_junction_rows(topology_audit):
        swsd_node_id = _safe_id(row.get("swsd_node_id"))
        node_ids = _parse_id_list(row.get("frcsd_node_ids"))
        node_infos = [_node_info(node_by_id.get(node_id), node_id, source_field_name) for node_id in node_ids]
        surface_hits = [
            hit
            for info in node_infos
            for hit in _surface_hits(info.get("point"), surfaces)
        ]
        surface_patch_ids = sorted({patch_id for hit in surface_hits for patch_id in hit["patch_ids"]})
        swsd_patch_ids = sorted(node_patch_ids.get(swsd_node_id, set()))
        t04_rows = t04_rejects.get(swsd_node_id, [])
        source1_nodes = [info for info in node_infos if info.get("source") == str(rcsd_source_value)]
        source2_nodes = [info for info in node_infos if info.get("source") == str(swsd_source_value)]
        fallback_node = None
        surface_1v1_evidence = False
        t04_reject_node_1v1_evidence = False
        candidate_node = None if t04_rows else _surface_1v1_fallback_node(
            swsd_node_id=swsd_node_id,
            surface_hits=surface_hits,
            node_by_id=node_by_id,
            source_field_name=source_field_name,
            rcsd_source_value=rcsd_source_value,
        )
        if candidate_node is not None and source1_nodes:
            surface_1v1_evidence = (
                len(source1_nodes) == 1 and _safe_id(source1_nodes[0].get("id")) == _safe_id(candidate_node.get("id"))
            )
        elif candidate_node is not None:
            fallback_node = candidate_node
            surface_1v1_evidence = True
            if fallback_node is not None:
                node_infos.append(fallback_node)
                source1_nodes = [fallback_node]
        t04_reject_candidate = _t04_reject_node_1v1_fallback_node(
            t04_rows=t04_rows,
            source2_nodes=source2_nodes,
            node_by_id=node_by_id,
            source_field_name=source_field_name,
            rcsd_source_value=rcsd_source_value,
        )
        if t04_reject_candidate is not None and not source1_nodes:
            fallback_node = t04_reject_candidate
            t04_reject_node_1v1_evidence = True
            node_infos.append(fallback_node)
            source1_nodes = [fallback_node]
        elif t04_reject_candidate is not None and len(source1_nodes) == 1:
            t04_reject_node_1v1_evidence = _safe_id(source1_nodes[0].get("id")) == _safe_id(
                t04_reject_candidate.get("id")
            )
        step2_candidate = None if t04_rows else _step2_optional_junc_fallback_node(
            swsd_node_id=swsd_node_id,
            swsd_segment_ids=_parse_id_list(row.get("swsd_segment_ids")),
            step2_junc_mappings=step2_junc_mappings,
            node_by_id=node_by_id,
            source_field_name=source_field_name,
            rcsd_source_value=rcsd_source_value,
        )
        step2_junc_evidence = False
        if step2_candidate is not None and surface_hits and not source1_nodes:
            fallback_node = step2_candidate
            step2_junc_evidence = True
            node_infos.append(fallback_node)
            source1_nodes = [fallback_node]
        elif step2_candidate is not None and surface_hits and len(source1_nodes) == 1:
            step2_junc_evidence = _safe_id(source1_nodes[0].get("id")) == _safe_id(step2_candidate.get("id"))
        t04_patch_1v1_evidence = _has_t04_patch_1v1_evidence(
            swsd_node_id=swsd_node_id,
            swsd_patch_ids=swsd_patch_ids,
            surface_hits=surface_hits,
        ) and _distance_within(row.get("max_pairwise_distance_m"), MAX_T04_PATCH_1V1_DISTANCE_M)
        existing_cross_source_1v1_evidence = (
            bool(surface_hits)
            and len(source1_nodes) == 1
            and len(source2_nodes) == 1
            and _can_resolve_closure_mainnode(source1_nodes[0], source2_nodes)
            and _distance_within(row.get("max_pairwise_distance_m"), MAX_EXISTING_CROSS_SOURCE_1V1_DISTANCE_M)
        )
        surface_nearest_multi_candidate = None if t04_rows else _surface_nearest_multi_candidate_node(
            swsd_node_id=swsd_node_id,
            surface_hits=surface_hits,
            source1_nodes=source1_nodes,
            source2_nodes=source2_nodes,
        )
        surface_nearest_multi_candidate_evidence = surface_nearest_multi_candidate is not None
        selected_endpoint_candidate = None if t04_rows else _selected_replacement_endpoint_fallback_node(
            swsd_segment_ids=_parse_id_list(row.get("swsd_segment_ids")),
            source1_nodes=source1_nodes,
            source2_nodes=source2_nodes,
            road_by_id=road_by_id,
            relation_by_segment=relation_by_segment,
            node_by_id=node_by_id,
            source_field_name=source_field_name,
            rcsd_source_value=rcsd_source_value,
        )
        selected_endpoint_evidence = selected_endpoint_candidate is not None
        if selected_endpoint_candidate is not None:
            node_infos.append(selected_endpoint_candidate)
            source1_nodes = [selected_endpoint_candidate]
        selected_midroad_candidate = None if t04_rows else _selected_replacement_midroad_projection(
            swsd_segment_ids=_parse_id_list(row.get("swsd_segment_ids")),
            source1_nodes=source1_nodes,
            source2_nodes=source2_nodes,
            road_by_id=road_by_id,
            relation_by_segment=relation_by_segment,
            node_by_id=node_by_id,
            node_features=node_features,
            road_features=road_features,
            source_field_name=source_field_name,
            rcsd_source_value=rcsd_source_value,
        )
        selected_midroad_evidence = selected_midroad_candidate is not None
        if selected_midroad_candidate is not None:
            midroad_node_infos = list(
                selected_midroad_candidate.get("node_infos") or [selected_midroad_candidate["node_info"]]
            )
            node_infos.extend(midroad_node_infos)
            source1_nodes = midroad_node_infos
            materialized_updates.extend(_safe_id(node_info.get("id")) for node_info in midroad_node_infos)
        relation_mapped_candidate = None if t04_rows else _relation_mapped_boundary_fallback_node(
            swsd_node_id=swsd_node_id,
            swsd_segment_ids=_parse_id_list(row.get("swsd_segment_ids")),
            relation_by_segment=relation_by_segment,
            node_by_id=node_by_id,
            source2_nodes=source2_nodes,
            source_field_name=source_field_name,
            rcsd_source_value=rcsd_source_value,
        )
        relation_mapped_boundary_evidence = False
        if relation_mapped_candidate is not None and not source1_nodes:
            fallback_node = relation_mapped_candidate
            relation_mapped_boundary_evidence = True
            node_infos.append(fallback_node)
            source1_nodes = [fallback_node]
        elif relation_mapped_candidate is not None and len(source1_nodes) == 1:
            relation_mapped_boundary_evidence = _safe_id(source1_nodes[0].get("id")) == _safe_id(
                relation_mapped_candidate.get("id")
            )
        classification = _classify_surface_junction(
            swsd_patch_ids=swsd_patch_ids,
            surface_patch_ids=surface_patch_ids,
            surface_hits=surface_hits,
            t04_rows=t04_rows,
            source1_nodes=source1_nodes,
            source2_nodes=source2_nodes,
            has_surface_1v1_fallback=surface_1v1_evidence,
            has_t04_patch_1v1_evidence=t04_patch_1v1_evidence,
            has_t04_reject_node_1v1_evidence=t04_reject_node_1v1_evidence,
            has_step2_junc_1v1_evidence=step2_junc_evidence,
            has_existing_cross_source_1v1_evidence=existing_cross_source_1v1_evidence,
            has_surface_nearest_multi_candidate_evidence=surface_nearest_multi_candidate_evidence,
            has_selected_endpoint_evidence=selected_endpoint_evidence,
            has_selected_midroad_evidence=selected_midroad_evidence,
            has_relation_mapped_boundary_evidence=relation_mapped_boundary_evidence,
        )
        closure_mainnodeid = ""
        auto_classifications = {
            "auto_candidate",
            "auto_candidate_surface_1v1",
            "auto_candidate_t04_patch_1v1",
            "auto_candidate_t04_rejected_node_1v1",
            "auto_candidate_step2_junc_1v1",
            "auto_candidate_existing_cross_source_1v1",
            "auto_candidate_surface_nearest_multi_candidate",
            "auto_candidate_selected_replacement_endpoint",
            "auto_candidate_selected_replacement_midroad",
            "auto_candidate_relation_mapped_boundary_1v1",
        }
        if classification in auto_classifications and apply_closure:
            closure_source_node = (
                surface_nearest_multi_candidate
                if classification == "auto_candidate_surface_nearest_multi_candidate"
                else selected_endpoint_candidate
                if classification == "auto_candidate_selected_replacement_endpoint"
                else selected_midroad_candidate["node_info"]
                if classification == "auto_candidate_selected_replacement_midroad"
                else source1_nodes[0]
            )
            closure_mainnodeid = _closure_mainnodeid(closure_source_node, source2_nodes)
            if closure_mainnodeid:
                closure_node_ids: set[str] | None = None
                if classification == "auto_candidate_surface_nearest_multi_candidate":
                    closure_node_ids = {
                        _safe_id(surface_nearest_multi_candidate.get("id")),
                        *[_safe_id(info.get("id")) for info in source2_nodes],
                    }
                elif classification == "auto_candidate_selected_replacement_endpoint":
                    closure_node_ids = {
                        _safe_id(selected_endpoint_candidate.get("id")),
                        *[_safe_id(info.get("id")) for info in source2_nodes],
                    }
                elif classification == "auto_candidate_selected_replacement_midroad":
                    closure_node_ids = {
                        *_selected_midroad_node_ids(selected_midroad_candidate),
                        *[_safe_id(info.get("id")) for info in source2_nodes],
                    }
                for info in node_infos:
                    if closure_node_ids is not None and _safe_id(info.get("id")) not in closure_node_ids:
                        continue
                    feature = node_by_id.get(str(info["id"]))
                    if feature is None:
                        continue
                    props = feature.setdefault("properties", {})
                    if _safe_id(props.get("mainnodeid")) != closure_mainnodeid:
                        props["mainnodeid"] = closure_mainnodeid
                        closure_updates.append(str(info["id"]))
                if fallback_node is not None:
                    if t04_reject_node_1v1_evidence:
                        mapping_status = "t04_rejected_node_1v1_fallback"
                        risk_flag = "t04_rejected_node_1v1_fallback_node_map"
                    elif step2_junc_evidence:
                        mapping_status = "step2_junc_1v1_fallback"
                        risk_flag = "step2_junc_1v1_fallback_node_map"
                    else:
                        mapping_status = "surface_1v1_fallback"
                        risk_flag = "surface_1v1_fallback_node_map"
                    relation_updates.append(
                        {
                            "swsd_node_id": swsd_node_id,
                            "rcsd_node_id": _safe_id(fallback_node.get("id")),
                            "swsd_segment_ids": _parse_id_list(row.get("swsd_segment_ids")),
                            "mapping_status": mapping_status,
                            "risk_flag": risk_flag,
                        }
                    )
                    if t04_reject_node_1v1_evidence:
                        classification = "auto_closed_t04_rejected_node_1v1"
                    elif step2_junc_evidence:
                        classification = "auto_closed_step2_junc_1v1"
                    else:
                        classification = "auto_closed_surface_1v1"
                elif classification == "auto_candidate_surface_1v1":
                    classification = "auto_closed_surface_1v1"
                elif classification == "auto_candidate_t04_patch_1v1":
                    classification = "auto_closed_t04_patch_1v1"
                elif classification == "auto_candidate_t04_rejected_node_1v1":
                    classification = "auto_closed_t04_rejected_node_1v1"
                elif classification == "auto_candidate_step2_junc_1v1":
                    classification = "auto_closed_step2_junc_1v1"
                elif classification == "auto_candidate_existing_cross_source_1v1":
                    classification = "auto_closed_existing_cross_source_1v1"
                elif classification == "auto_candidate_surface_nearest_multi_candidate":
                    relation_updates.append(
                        {
                            "swsd_node_id": swsd_node_id,
                            "rcsd_node_id": _safe_id(surface_nearest_multi_candidate.get("id")),
                            "swsd_segment_ids": _parse_id_list(row.get("swsd_segment_ids")),
                            "mapping_status": "surface_nearest_multi_candidate_fallback",
                            "risk_flag": "surface_nearest_multi_candidate_node_map",
                            "allow_existing_source1_remap": True,
                            "allowed_current_node_ids": [
                                _safe_id(info.get("id")) for info in source1_nodes if _safe_id(info.get("id"))
                            ],
                        }
                    )
                    classification = "auto_closed_surface_nearest_multi_candidate"
                elif classification == "auto_candidate_selected_replacement_endpoint":
                    relation_updates.append(
                        {
                            "swsd_node_id": swsd_node_id,
                            "rcsd_node_id": _safe_id(selected_endpoint_candidate.get("id")),
                            "swsd_segment_ids": _parse_id_list(row.get("swsd_segment_ids")),
                            "mapping_status": "selected_replacement_endpoint_fallback",
                            "risk_flag": "selected_replacement_endpoint_fallback_node_map",
                        }
                    )
                    classification = "auto_closed_selected_replacement_endpoint"
                elif classification == "auto_candidate_selected_replacement_midroad":
                    selected_midroad_node_ids = _selected_midroad_node_ids(selected_midroad_candidate)
                    relation_updates.append(
                        {
                            "swsd_node_id": swsd_node_id,
                            "rcsd_node_id": selected_midroad_node_ids[0] if selected_midroad_node_ids else "",
                            "rcsd_node_ids": selected_midroad_node_ids,
                            "swsd_segment_ids": _parse_id_list(row.get("swsd_segment_ids")),
                            "mapping_status": "selected_replacement_midroad_projection",
                            "risk_flag": "selected_replacement_midroad_projection_node_map",
                            "road_replacements": selected_midroad_candidate["road_replacements"],
                        }
                    )
                    classification = "auto_closed_selected_replacement_midroad"
                elif classification == "auto_candidate_relation_mapped_boundary_1v1":
                    classification = "auto_closed_relation_mapped_boundary_1v1"
                else:
                    classification = "auto_closed"
            elif fallback_node is not None:
                if t04_reject_node_1v1_evidence:
                    mapping_status = "t04_rejected_node_1v1_single_node_default"
                    risk_flag = "t04_rejected_node_1v1_single_node_default_node_map"
                    classification = "auto_mapped_t04_rejected_node_1v1_single_node_default"
                elif step2_junc_evidence:
                    mapping_status = "step2_junc_1v1_single_node_default"
                    risk_flag = "step2_junc_1v1_single_node_default_node_map"
                    classification = "auto_mapped_step2_junc_1v1_single_node_default"
                else:
                    mapping_status = "surface_1v1_single_node_default"
                    risk_flag = "surface_1v1_single_node_default_node_map"
                    classification = "auto_mapped_surface_1v1_single_node_default"
                relation_updates.append(
                    {
                        "swsd_node_id": swsd_node_id,
                        "rcsd_node_id": _safe_id(fallback_node.get("id")),
                        "swsd_segment_ids": _parse_id_list(row.get("swsd_segment_ids")),
                        "mapping_status": mapping_status,
                        "risk_flag": risk_flag,
                    }
                )

        status = "pass" if classification in {"auto_closed", "auto_closed_surface_1v1", "auto_closed_t04_patch_1v1", "auto_closed_t04_rejected_node_1v1", "auto_closed_step2_junc_1v1", "auto_closed_existing_cross_source_1v1", "auto_closed_surface_nearest_multi_candidate", "auto_closed_selected_replacement_endpoint", "auto_closed_selected_replacement_midroad", "auto_closed_relation_mapped_boundary_1v1", "auto_mapped_surface_1v1_single_node_default", "auto_mapped_t04_rejected_node_1v1_single_node_default", "auto_mapped_step2_junc_1v1_single_node_default"} else "fail"
        surface_candidate_ids = unique_preserve_order(
            candidate_id for hit in surface_hits for candidate_id in hit.get("candidate_node_ids", [])
        )
        fallback_ids = []
        if fallback_node is not None:
            fallback_ids.append(_safe_id(fallback_node.get("id")))
        if selected_endpoint_candidate is not None:
            fallback_ids.append(_safe_id(selected_endpoint_candidate.get("id")))
        if selected_midroad_candidate is not None:
            fallback_ids.extend(_selected_midroad_node_ids(selected_midroad_candidate))
        rows.append(
            {
                "properties": {
                    "audit_layer": "surface_junction_topology",
                    "audit_status": status,
                    "audit_reason": classification,
                    "action": (
                        "mainnode_closure_applied"
                        if classification.startswith("auto_closed")
                        else "relation_node_map_updated"
                        if classification.startswith("auto_mapped")
                        else "no_auto_closure"
                    ),
                    "swsd_node_id": swsd_node_id,
                    "swsd_segment_ids": _parse_id_list(row.get("swsd_segment_ids")),
                    "frcsd_node_ids": unique_preserve_order([*node_ids, *fallback_ids]),
                    "swsd_patch_ids": swsd_patch_ids,
                    "surface_patch_ids": surface_patch_ids,
                    "surface_layers": unique_preserve_order(hit["layer"] for hit in surface_hits),
                    "surface_candidate_node_ids": surface_candidate_ids,
                    "t04_reject_reasons": unique_preserve_order(item["reject_reason"] for item in t04_rows),
                    "source1_node_count": len(source1_nodes),
                    "source2_node_count": len(source2_nodes),
                    "max_pairwise_distance_m": _float_or_none(row.get("max_pairwise_distance_m")),
                    "closure_mainnodeid": closure_mainnodeid,
                },
                "geometry": _points_geometry([info["point"] for info in node_infos if isinstance(info.get("point"), Point)]),
            }
        )
    return rows, unique_preserve_order(closure_updates), relation_updates, unique_preserve_order(materialized_updates)
