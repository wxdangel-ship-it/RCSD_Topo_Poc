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


def run_surface_topology_postprocess(
    *,
    step_root: str | Path,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    t07_surface_path: str | Path | None = None,
    t03_surface_path: str | Path | None = None,
    t04_surface_path: str | Path | None = None,
    t04_audit_path: str | Path | None = None,
    t05_surface_path: str | Path | None = None,
    source_field_name: str = "source",
    swsd_source_value: int = 2,
    rcsd_source_value: int = 1,
    apply_closure: bool = True,
) -> dict[str, Any]:
    resolved_step_root = Path(step_root)
    node_path = resolved_step_root / f"{STEP3_FRCSD_NODE_STEM}.gpkg"
    topology_path = resolved_step_root / f"{STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM}.gpkg"
    if not node_path.is_file() or not topology_path.is_file():
        return {"surface_topology_status": "skipped", "surface_topology_reason": "missing_step3_outputs"}

    node_features = read_features(node_path)
    node_fields = _fieldnames_from_gpkg(node_path)
    node_by_id = {_feature_id(feature): feature for feature in node_features}
    road_path = resolved_step_root / f"{STEP3_FRCSD_ROAD_STEM}.gpkg"
    road_features = read_features(road_path)
    road_fields = _fieldnames_from_gpkg(road_path)
    road_by_id = _road_features_by_id_from_features(road_features)
    swsd_roads = read_features(swsd_roads_path)
    node_patch_ids = _swsd_patch_ids_by_node(swsd_roads)
    surfaces = _load_surfaces(
        t07_surface_path=t07_surface_path,
        t03_surface_path=t03_surface_path,
        t04_surface_path=t04_surface_path,
        t05_surface_path=t05_surface_path,
    )
    t04_rejects = _load_t04_rejects(t04_audit_path)
    step2_junc_mappings = _load_step2_optional_junc_mappings(resolved_step_root)
    step2_dropped_junc_nodes = _load_step2_dropped_junc_nodes(resolved_step_root)

    audit_rows: list[dict[str, Any]] = []
    action_audit_rows: list[dict[str, Any]] = []
    closure_updates: list[str] = []
    relation_update_count = _apply_step2_plan_relation_node_map_updates(
        step_root=resolved_step_root,
        step2_junc_mappings=step2_junc_mappings,
        step2_dropped_junc_nodes=step2_dropped_junc_nodes,
    )
    if relation_update_count:
        _rebuild_topology_connectivity_audit(
            step_root=resolved_step_root,
            swsd_segment_path=swsd_segment_path,
            swsd_roads_path=swsd_roads_path,
            source_field_name=source_field_name,
            swsd_source_value=swsd_source_value,
            rcsd_source_value=rcsd_source_value,
        )
    materialized_updates: list[str] = []
    surface_paths: dict[str, Path] = {}
    for _iteration in range(3):
        relation_by_segment = _relation_props_by_segment(
            resolved_step_root / f"{STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM}.gpkg"
        )
        topology_audit = gpd.read_file(topology_path)
        road_by_id = _road_features_by_id_from_features(road_features)
        pass_rows, pass_closure_updates, pass_relation_updates, pass_materialized_updates = _build_surface_audit_rows(
            topology_audit=topology_audit,
            node_by_id=node_by_id,
            node_features=node_features,
            road_features=road_features,
            node_patch_ids=node_patch_ids,
            surfaces=surfaces,
            t04_rejects=t04_rejects,
            step2_junc_mappings=step2_junc_mappings,
            road_by_id=road_by_id,
            relation_by_segment=relation_by_segment,
            source_field_name=source_field_name,
            swsd_source_value=swsd_source_value,
            rcsd_source_value=rcsd_source_value,
            apply_closure=apply_closure,
        )
        action_audit_rows = _unique_surface_audit_rows(
            [
                *action_audit_rows,
                *[pass_row for pass_row in pass_rows if _is_surface_action_row(pass_row)],
            ]
        )
        audit_rows = [
            *action_audit_rows,
            *[pass_row for pass_row in pass_rows if not _is_surface_action_row(pass_row)],
        ]
        surface_paths = write_feature_triplet(
            step_root=resolved_step_root,
            stem=SURFACE_TOPOLOGY_AUDIT_STEM,
            features=audit_rows,
            fieldnames=SURFACE_TOPOLOGY_AUDIT_FIELDS,
        )
        pass_relation_update_count = 0
        if pass_relation_updates:
            pass_relation_update_count = _apply_relation_node_map_updates(
                step_root=resolved_step_root,
                updates=pass_relation_updates,
            )
        if not pass_closure_updates and not pass_relation_update_count and not pass_materialized_updates:
            break
        closure_updates = unique_preserve_order([*closure_updates, *pass_closure_updates])
        relation_update_count += pass_relation_update_count
        materialized_updates = unique_preserve_order([*materialized_updates, *pass_materialized_updates])
        write_feature_triplet(
            step_root=resolved_step_root,
            stem=STEP3_FRCSD_NODE_STEM,
            features=node_features,
            fieldnames=node_fields,
        )
        if pass_materialized_updates:
            write_feature_triplet(
                step_root=resolved_step_root,
                stem=STEP3_FRCSD_ROAD_STEM,
                features=road_features,
                fieldnames=road_fields,
            )
        _rebuild_topology_connectivity_audit(
            step_root=resolved_step_root,
            swsd_segment_path=swsd_segment_path,
            swsd_roads_path=swsd_roads_path,
            source_field_name=source_field_name,
            swsd_source_value=swsd_source_value,
            rcsd_source_value=rcsd_source_value,
        )
        if not pass_materialized_updates:
            break

    summary = _surface_summary(audit_rows)
    summary.update(
        {
            "surface_topology_status": "passed" if summary["surface_topology_fail_count"] == 0 else "failed",
            "surface_topology_closure_updated_node_count": len(closure_updates),
            "surface_topology_closure_updated_nodes": closure_updates,
            "surface_topology_relation_node_map_update_count": relation_update_count,
            "surface_topology_selected_replacement_midroad_materialized_count": len(materialized_updates),
            "surface_topology_selected_replacement_midroad_materialized_nodes": materialized_updates,
            "surface_topology_audit_outputs": {key: str(path) for key, path in surface_paths.items()},
        }
    )
    summary_path = resolved_step_root / SURFACE_TOPOLOGY_SUMMARY
    write_json(summary_path, summary)
    _merge_step3_summary(resolved_step_root, summary, summary_path)
    return summary


def _build_surface_audit_rows(
    *,
    topology_audit: gpd.GeoDataFrame,
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
    failed_junctions = topology_audit[
        (topology_audit["audit_layer"].astype(str) == "segment_junction_connectivity")
        & (topology_audit["audit_status"].astype(str) == "fail")
    ]
    for _, row in failed_junctions.iterrows():
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
    if float(candidate_point.distance(swsd_point)) > MAX_RELATION_MAPPED_BOUNDARY_1V1_DISTANCE_M:
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


def _apply_relation_node_map_updates(
    *,
    step_root: Path,
    updates: list[dict[str, Any]],
) -> int:
    relation_path = step_root / f"{STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM}.gpkg"
    if not relation_path.is_file():
        return 0
    relation_rows = read_features(relation_path)
    updated = 0
    for row in relation_rows:
        props = row.setdefault("properties", {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if str(props.get("relation_status") or "") == "retained_swsd":
            continue
        row_changed = False
        for update in updates:
            if _replace_relation_road_ids(props, update):
                row_changed = True
            if segment_id in set(update.get("swsd_segment_ids") or []) and _upsert_relation_node_map(props, update):
                row_changed = True
        if row_changed:
            updated += 1
    if updated:
        write_feature_triplet(
            step_root=step_root,
            stem=STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
            features=relation_rows,
            fieldnames=STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
        )
    return updated


def _replace_relation_road_ids(props: dict[str, Any], update: dict[str, Any]) -> bool:
    replacements = dict(update.get("road_replacements") or {})
    if not replacements:
        return False
    changed = False
    for field in ("frcsd_road_ids", "rcsd_road_ids"):
        road_ids = _parse_id_list(props.get(field))
        if not road_ids:
            continue
        next_ids: list[str] = []
        for road_id in road_ids:
            replacement_ids = _parse_id_list(replacements.get(road_id))
            if replacement_ids:
                next_ids.extend(replacement_ids)
                changed = True
            else:
                next_ids.append(road_id)
        if changed:
            props[field] = unique_preserve_order(next_ids)
    return changed


def _selected_midroad_node_ids(candidate: dict[str, Any] | None) -> list[str]:
    if candidate is None:
        return []
    node_infos = list(candidate.get("node_infos") or [candidate.get("node_info")])
    return unique_preserve_order(_safe_id((node_info or {}).get("id")) for node_info in node_infos)


def _upsert_relation_node_map(props: dict[str, Any], update: dict[str, Any]) -> bool:
    swsd_node_id = _safe_id(update.get("swsd_node_id"))
    rcsd_node_ids = unique_preserve_order(
        _parse_id_list(update.get("rcsd_node_ids")) or [_safe_id(update.get("rcsd_node_id"))]
    )
    if not swsd_node_id or not rcsd_node_ids:
        return False
    mapping_status = str(update.get("mapping_status") or "surface_1v1_fallback")
    risk_flag = str(update.get("risk_flag") or "surface_1v1_fallback_node_map")
    allow_existing_source1_remap = bool(update.get("allow_existing_source1_remap"))
    allowed_current_node_ids = set(_parse_id_list(update.get("allowed_current_node_ids")))
    entries = _node_map_entries(props.get("swsd_to_frcsd_node_map"))
    changed = False
    matched = False
    for entry in entries:
        if _safe_id(entry.get("swsd_node_id")) != swsd_node_id:
            continue
        matched = True
        current_ids = _parse_id_list(entry.get("frcsd_node_ids"))
        status = str(entry.get("mapping_status") or "")
        if current_ids == rcsd_node_ids:
            return False
        if current_ids and current_ids != [swsd_node_id] and status not in {"missing"}:
            if (
                not allow_existing_source1_remap
                or len(current_ids) != 1
                or current_ids[0] not in allowed_current_node_ids
            ):
                return False
        entry["frcsd_node_ids"] = rcsd_node_ids
        entry["mapping_status"] = mapping_status
        entry["node_role"] = entry.get("node_role") or "surface_1v1_fallback_node"
        changed = True
    if not matched:
        entries.append(
            {
                "swsd_node_id": swsd_node_id,
                "frcsd_node_ids": rcsd_node_ids,
                "node_role": "surface_1v1_fallback_node",
                "mapping_status": mapping_status,
            }
        )
        changed = True
    if changed:
        props["swsd_to_frcsd_node_map"] = entries
        risk_flags = unique_preserve_order([*_parse_id_list(props.get("risk_flags")), risk_flag])
        props["risk_flags"] = risk_flags
    return changed


def _node_map_entries(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if value in (None, ""):
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [dict(item) for item in parsed if isinstance(item, dict)]


def _rebuild_topology_connectivity_audit(
    *,
    step_root: Path,
    swsd_segment_path: str | Path,
    swsd_roads_path: str | Path,
    source_field_name: str,
    swsd_source_value: int,
    rcsd_source_value: int,
) -> None:
    swsd_segments = read_features(swsd_segment_path)
    swsd_roads = read_features(swsd_roads_path)
    frcsd_roads = read_features(step_root / "t06_frcsd_road.gpkg")
    frcsd_nodes = read_features(step_root / "t06_frcsd_node.gpkg")
    relation_rows = read_features(step_root / "t06_step3_swsd_frcsd_segment_relation.gpkg")
    advance_rows = read_features(step_root / "t06_step3_advance_right_attachment_audit.gpkg")
    rows = build_topology_connectivity_audit_rows(
        swsd_segments=swsd_segments,
        swsd_roads=swsd_roads,
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=relation_rows,
        advance_right_audit_rows=advance_rows,
        source_field_name=source_field_name,
        swsd_source_value=swsd_source_value,
        rcsd_source_value=rcsd_source_value,
    )
    write_feature_triplet(
        step_root=step_root,
        stem=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_STEM,
        features=rows,
        fieldnames=STEP3_TOPOLOGY_CONNECTIVITY_AUDIT_FIELDS,
    )
    summary_path = step_root / "t06_step3_summary.json"
    if summary_path.is_file():
        payload = json.loads(summary_path.read_text(encoding="utf-8"))
        payload.update(summarize_topology_connectivity_audit(rows))
        write_json(summary_path, payload)


def _is_surface_action_row(row: dict[str, Any]) -> bool:
    props = row.get("properties") or {}
    action = str(props.get("action") or "")
    return action != "no_auto_closure" or str(props.get("audit_status") or "") == "pass"


def _unique_surface_audit_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str]] = set()
    unique_rows: list[dict[str, Any]] = []
    for row in rows:
        props = row.get("properties") or {}
        key = (
            str(props.get("audit_layer") or ""),
            str(props.get("swsd_node_id") or ""),
            str(props.get("audit_reason") or ""),
            str(props.get("closure_mainnodeid") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows


def _surface_summary(rows: list[dict[str, Any]]) -> dict[str, int]:
    reasons = Counter(str((row.get("properties") or {}).get("audit_reason") or "") for row in rows)
    fail_count = sum(1 for row in rows if (row.get("properties") or {}).get("audit_status") == "fail")
    pass_count = sum(1 for row in rows if (row.get("properties") or {}).get("audit_status") == "pass")
    return {
        "surface_topology_audit_row_count": len(rows),
        "surface_topology_fail_count": fail_count,
        "surface_topology_pass_count": pass_count,
        "surface_topology_auto_closed_count": (
            reasons.get("auto_closed", 0)
            + reasons.get("auto_closed_surface_1v1", 0)
            + reasons.get("auto_closed_t04_patch_1v1", 0)
            + reasons.get("auto_closed_t04_rejected_node_1v1", 0)
            + reasons.get("auto_closed_step2_junc_1v1", 0)
            + reasons.get("auto_closed_existing_cross_source_1v1", 0)
            + reasons.get("auto_closed_surface_nearest_multi_candidate", 0)
            + reasons.get("auto_closed_selected_replacement_endpoint", 0)
            + reasons.get("auto_closed_selected_replacement_midroad", 0)
            + reasons.get("auto_closed_relation_mapped_boundary_1v1", 0)
        ),
        "surface_topology_surface_1v1_closed_count": reasons.get("auto_closed_surface_1v1", 0),
        "surface_topology_t04_patch_1v1_closed_count": reasons.get("auto_closed_t04_patch_1v1", 0),
        "surface_topology_t04_rejected_node_1v1_closed_count": reasons.get("auto_closed_t04_rejected_node_1v1", 0),
        "surface_topology_step2_junc_1v1_closed_count": reasons.get("auto_closed_step2_junc_1v1", 0),
        "surface_topology_existing_cross_source_1v1_closed_count": reasons.get("auto_closed_existing_cross_source_1v1", 0),
        "surface_topology_surface_nearest_multi_candidate_closed_count": reasons.get("auto_closed_surface_nearest_multi_candidate", 0),
        "surface_topology_selected_replacement_endpoint_closed_count": reasons.get("auto_closed_selected_replacement_endpoint", 0),
        "surface_topology_selected_replacement_midroad_closed_count": reasons.get("auto_closed_selected_replacement_midroad", 0),
        "surface_topology_relation_mapped_boundary_1v1_closed_count": reasons.get("auto_closed_relation_mapped_boundary_1v1", 0),
        "surface_topology_single_node_default_mapped_count": (
            reasons.get("auto_mapped_surface_1v1_single_node_default", 0)
            + reasons.get("auto_mapped_t04_rejected_node_1v1_single_node_default", 0)
            + reasons.get("auto_mapped_step2_junc_1v1_single_node_default", 0)
        ),
        "surface_topology_blocked_by_patch_conflict_count": reasons.get("blocked_by_patch_conflict", 0),
        "surface_topology_blocked_by_t04_reject_count": reasons.get("blocked_by_t04_reject", 0),
        "surface_topology_manual_review_count": sum(
            count for reason, count in reasons.items() if reason.startswith("manual_")
        ),
    }


def _merge_step3_summary(step_root: Path, summary: dict[str, Any], summary_path: Path) -> None:
    step3_summary_path = step_root / "t06_step3_summary.json"
    if not step3_summary_path.is_file():
        return
    payload = json.loads(step3_summary_path.read_text(encoding="utf-8"))
    payload.update(summary)
    outputs = dict(payload.get("outputs") or {})
    outputs["surface_topology_audit_gpkg"] = str(step_root / f"{SURFACE_TOPOLOGY_AUDIT_STEM}.gpkg")
    outputs["surface_topology_summary_json"] = str(summary_path)
    payload["outputs"] = outputs
    write_json(step3_summary_path, payload)


def _load_surfaces(
    *,
    t07_surface_path: str | Path | None,
    t03_surface_path: str | Path | None,
    t04_surface_path: str | Path | None,
    t05_surface_path: str | Path | None,
) -> dict[str, gpd.GeoDataFrame]:
    result: dict[str, gpd.GeoDataFrame] = {}
    for name, path in {
        "t05": t05_surface_path,
        "t07": t07_surface_path,
        "t04": t04_surface_path,
        "t03": t03_surface_path,
    }.items():
        if path and Path(path).is_file():
            result[name] = gpd.read_file(path)
    return result


def _load_t04_rejects(path: str | Path | None) -> dict[str, list[dict[str, str]]]:
    if not path or not Path(path).is_file():
        return {}
    result: dict[str, list[dict[str, str]]] = defaultdict(list)
    rows = gpd.read_file(path)
    for _, row in rows.iterrows():
        target = str(row.get("publish_target") or "")
        reject_reason = str(row.get("reject_reason") or "")
        if not target.startswith("rejected") and not reject_reason:
            continue
        payload = {
            "anchor_id": _safe_id(row.get("anchor_id")),
            "case_id": _safe_id(row.get("case_id")),
            "publish_target": target,
            "reject_reason": reject_reason,
            "reject_reason_detail": str(row.get("reject_reason_detail") or ""),
            "required_rcsd_node_ids": _parse_id_list(row.get("required_rcsd_node_ids")),
            "required_rcsd_node_count": _int_or_none(row.get("required_rcsd_node_count")),
            "hard_must_cover_ok": _bool_or_none(row.get("hard_must_cover_ok")),
            "post_cleanup_forbidden_ok": _bool_or_none(row.get("post_cleanup_forbidden_ok")),
            "post_cleanup_terminal_cut_ok": _bool_or_none(row.get("post_cleanup_terminal_cut_ok")),
            "post_cleanup_lateral_limit_ok": _bool_or_none(row.get("post_cleanup_lateral_limit_ok")),
            "post_cleanup_must_cover_ok": _bool_or_none(row.get("post_cleanup_must_cover_ok")),
            "forbidden_overlap": _bool_or_none(row.get("forbidden_overlap")),
            "cut_violation": _bool_or_none(row.get("cut_violation")),
            "fallback_overexpansion_detected": _bool_or_none(row.get("fallback_overexpansion_detected")),
        }
        for node_id in unique_preserve_order([payload["anchor_id"], payload["case_id"]]):
            if node_id:
                result[node_id].append(payload)
    return dict(result)


def _apply_step2_plan_relation_node_map_updates(
    *,
    step_root: Path,
    step2_junc_mappings: dict[tuple[str, str], list[str]],
    step2_dropped_junc_nodes: dict[str, list[str]],
) -> int:
    if not step2_junc_mappings and not step2_dropped_junc_nodes:
        return 0
    relation_path = step_root / f"{STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM}.gpkg"
    if not relation_path.is_file():
        return 0
    rows = read_features(relation_path)
    updated = 0
    for row in rows:
        props = row.setdefault("properties", {})
        if str(props.get("relation_status") or "") == "retained_swsd":
            continue
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if not segment_id:
            continue
        entries = _node_map_entries(props.get("swsd_to_frcsd_node_map"))
        changed = False
        for dropped_node_id in step2_dropped_junc_nodes.get(segment_id, []):
            changed = _set_relation_node_map_entry(
                entries,
                swsd_node_id=dropped_node_id,
                frcsd_node_ids=[dropped_node_id],
                node_role="dropped_junc_node",
                mapping_status="identity_dropped_junc_not_consumed",
            ) or changed
        for (mapping_segment_id, swsd_node_id), rcsd_node_ids in step2_junc_mappings.items():
            if mapping_segment_id != segment_id:
                continue
            changed = _set_relation_node_map_entry(
                entries,
                swsd_node_id=swsd_node_id,
                frcsd_node_ids=rcsd_node_ids,
                node_role="junc_node",
                mapping_status="step2_optional_junc_plan_map",
            ) or changed
        if not changed:
            continue
        props["swsd_to_frcsd_node_map"] = entries
        risk_flags = _parse_id_list(props.get("risk_flags"))
        if any(node_id in step2_dropped_junc_nodes.get(segment_id, []) for node_id in [e["swsd_node_id"] for e in entries]):
            risk_flags.append("dropped_junc_retained_swsd_node_map")
        if any(mapping_segment_id == segment_id for mapping_segment_id, _node_id in step2_junc_mappings):
            risk_flags.append("step2_optional_junc_plan_node_map")
        props["risk_flags"] = unique_preserve_order(risk_flags)
        updated += 1
    if updated:
        write_feature_triplet(
            step_root=step_root,
            stem=STEP3_SWSD_FRCSD_SEGMENT_RELATION_STEM,
            features=rows,
            fieldnames=STEP3_SWSD_FRCSD_SEGMENT_RELATION_FIELDS,
        )
    return updated


def _set_relation_node_map_entry(
    entries: list[dict[str, Any]],
    *,
    swsd_node_id: str,
    frcsd_node_ids: list[str],
    node_role: str,
    mapping_status: str,
) -> bool:
    swsd_node_id = _safe_id(swsd_node_id)
    frcsd_node_ids = unique_preserve_order(_safe_id(node_id) for node_id in frcsd_node_ids if _safe_id(node_id))
    if not swsd_node_id or not frcsd_node_ids:
        return False
    for entry in entries:
        if _safe_id(entry.get("swsd_node_id")) != swsd_node_id:
            continue
        if (
            _parse_id_list(entry.get("frcsd_node_ids")) == frcsd_node_ids
            and str(entry.get("mapping_status") or "") == mapping_status
            and str(entry.get("node_role") or "") == node_role
        ):
            return False
        entry["frcsd_node_ids"] = frcsd_node_ids
        entry["node_role"] = node_role
        entry["mapping_status"] = mapping_status
        return True
    entries.append(
        {
            "swsd_node_id": swsd_node_id,
            "frcsd_node_ids": frcsd_node_ids,
            "node_role": node_role,
            "mapping_status": mapping_status,
        }
    )
    return True


def _load_step2_optional_junc_mappings(step_root: Path) -> dict[tuple[str, str], list[str]]:
    result: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in _iter_step2_junc_rows(step_root):
        segment_id = _safe_id(row.get("swsd_segment_id"))
        if not segment_id:
            continue
        swsd_nodes = _parse_id_list(row.get("optional_junc_nodes"))
        rcsd_nodes = _parse_id_list(row.get("optional_junc_rcsd_nodes"))
        raw_rcsd_nodes = _parse_id_list(row.get("rcsd_junc_nodes"))
        if len(rcsd_nodes) != len(swsd_nodes) and len(raw_rcsd_nodes) == len(swsd_nodes):
            rcsd_nodes = raw_rcsd_nodes
        for swsd_node_id, rcsd_node_id in zip(swsd_nodes, rcsd_nodes):
            if not swsd_node_id or not rcsd_node_id:
                continue
            key = (segment_id, swsd_node_id)
            result[key] = unique_preserve_order([*result[key], rcsd_node_id])
    return dict(result)


def _load_step2_dropped_junc_nodes(step_root: Path) -> dict[str, list[str]]:
    result: dict[str, list[str]] = defaultdict(list)
    for row in _iter_step2_junc_rows(step_root):
        segment_id = _safe_id(row.get("swsd_segment_id"))
        if not segment_id:
            continue
        dropped_nodes = _parse_id_list(row.get("dropped_junc_nodes"))
        if dropped_nodes:
            result[segment_id] = unique_preserve_order([*result[segment_id], *dropped_nodes])
    return dict(result)


def _iter_step2_junc_rows(step_root: Path) -> list[dict[str, Any]]:
    for step2_root in _step2_junc_roots(step_root):
        for stem in (STEP2_REPLACEMENT_PLAN_STEM, STEP2_FAILURE_BUSINESS_AUDIT_STEM):
            for suffix in (".gpkg", ".csv"):
                path = step2_root / f"{stem}{suffix}"
                if path.is_file():
                    return _read_step2_junc_rows(path)
    return []


def _step2_junc_roots(step_root: Path) -> list[Path]:
    roots = [step_root.parent / "step2_extract_rcsd_segments"]
    summary_path = step_root / "t06_step3_summary.json"
    if summary_path.is_file():
        try:
            input_paths = json.loads(summary_path.read_text(encoding="utf-8")).get("input_paths") or {}
        except json.JSONDecodeError:
            input_paths = {}
        step2_replaceable = input_paths.get("step2_replaceable_path")
        if step2_replaceable:
            path = Path(step2_replaceable)
            if not path.is_absolute():
                path = Path.cwd() / path
            roots.append(path.parent)
    result: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        key = str(root.resolve()) if root.exists() else str(root)
        if key in seen:
            continue
        seen.add(key)
        result.append(root)
    return result


def _read_step2_junc_rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".gpkg":
        return [dict(row) for _, row in gpd.read_file(path).iterrows()]
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _road_features_by_id(path: Path) -> dict[str, list[dict[str, Any]]]:
    if not path.is_file():
        return {}
    return _road_features_by_id_from_features(read_features(path))


def _road_features_by_id_from_features(roads: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for road in roads:
        road_id = _safe_id((road.get("properties") or {}).get("id"))
        if road_id:
            result[road_id].append(road)
    return dict(result)


def _relation_props_by_segment(path: Path) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in read_features(path):
        props = dict(row.get("properties") or {})
        segment_id = _safe_id(props.get("swsd_segment_id"))
        if segment_id:
            result[segment_id] = props
    return result


def _swsd_patch_ids_by_node(swsd_roads: list[dict[str, Any]]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = defaultdict(set)
    for road in swsd_roads:
        props = dict(road.get("properties") or {})
        patch_ids = set(_patch_ids(props.get("patch_id") or props.get("patchid")))
        for node_id in [_safe_id(props.get("snodeid")), _safe_id(props.get("enodeid"))]:
            if node_id:
                result[node_id].update(patch_ids)
    return dict(result)


def _node_info(feature_item: dict[str, Any] | None, node_id: str, source_field_name: str) -> dict[str, Any]:
    props = dict((feature_item or {}).get("properties") or {})
    return {
        "id": node_id,
        "source": _safe_id(props.get(source_field_name)),
        "mainnodeid": _safe_id(props.get("mainnodeid")),
        "point": (feature_item or {}).get("geometry"),
    }


def _surface_hits(point: Any, surfaces: dict[str, gpd.GeoDataFrame]) -> list[dict[str, Any]]:
    if not isinstance(point, Point):
        return []
    hits: list[dict[str, Any]] = []
    for layer, rows in surfaces.items():
        try:
            candidates = rows.iloc[list(rows.sindex.query(point.buffer(0.01), predicate="intersects"))]
        except Exception:
            candidates = rows
        for _, row in candidates.iterrows():
            geometry = row.geometry
            if geometry is None or geometry.is_empty:
                continue
            if not geometry.intersects(point) and geometry.distance(point) > 1.0:
                continue
            hits.append(
                {
                    "layer": layer,
                    "id": _safe_id(
                        row.get("surface_id")
                        or row.get("id")
                        or row.get("anchor_id")
                        or row.get("mainnodeid")
                        or row.get("case_id")
                    ),
                    "patch_ids": _patch_ids(row.get("patch_id") or row.get("patchid")),
                    "candidate_node_ids": _surface_candidate_node_ids(layer, row),
                    "target_id": _safe_id(row.get("target_id")),
                    "representative_node_id": _safe_id(row.get("representative_node_id")),
                    "mainnodeid": _safe_id(row.get("mainnodeid")),
                    "anchor_id": _safe_id(row.get("anchor_id")),
                    "case_id": _safe_id(row.get("case_id")),
                    "final_state": str(row.get("final_state") or ""),
                    "relation_state": str(row.get("relation_state") or ""),
                }
            )
    return hits


def _surface_candidate_node_ids(layer: str, row: Any) -> list[str]:
    if layer != "t07":
        return []
    return unique_preserve_order(
        candidate_id
        for value in (
            row.get("base_id_candidate"),
            row.get("source_rcsdintersection_id"),
            row.get("matched_rcsdintersection_ids"),
            row.get("id"),
        )
        for candidate_id in _parse_id_list(value)
    )


def _closure_mainnodeid(source1_node: dict[str, Any], source2_nodes: list[dict[str, Any]]) -> str:
    mainnodeid = _safe_id(source1_node.get("mainnodeid"))
    if mainnodeid and mainnodeid != "0":
        return mainnodeid
    return _source2_default_mainnodeid(source2_nodes)


def _has_effective_mainnode(node: dict[str, Any]) -> bool:
    mainnodeid = _safe_id(node.get("mainnodeid"))
    return bool(mainnodeid and mainnodeid != "0")


def _can_resolve_closure_mainnode(source1_node: dict[str, Any], source2_nodes: list[dict[str, Any]]) -> bool:
    return _has_effective_mainnode(source1_node) or bool(_source2_default_mainnodeid(source2_nodes))


def _source2_default_mainnodeid(source2_nodes: list[dict[str, Any]]) -> str:
    mainnodeids = unique_preserve_order(
        mainnodeid
        for node in source2_nodes
        for mainnodeid in [_safe_id(node.get("mainnodeid"))]
        if mainnodeid and mainnodeid != "0"
    )
    return mainnodeids[0] if len(mainnodeids) == 1 else ""


def _fieldnames_from_gpkg(path: Path) -> list[str]:
    gdf = gpd.read_file(path, rows=0)
    return [column for column in gdf.columns if column != "geometry"]


def _feature_id(feature_item: dict[str, Any]) -> str:
    try:
        return normalize_id((feature_item.get("properties") or {}).get("id"))
    except Exception:
        return _safe_id((feature_item.get("properties") or {}).get("id"))


def _parse_id_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [_safe_id(item) for item in value if _safe_id(item)]
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, list):
            return [_safe_id(item) for item in parsed if _safe_id(item)]
    return [_safe_id(item) for item in text.replace("[", "").replace("]", "").replace('"', "").split(",") if _safe_id(item)]


def _patch_ids(value: Any) -> list[str]:
    return [item for item in _parse_id_list(value) if item not in {"0", "None", "nan"}]


def _safe_id(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        if value != value:
            return ""
    except Exception:
        pass
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _float_or_none(value: Any) -> float | None:
    try:
        if value in (None, "") or value != value:
            return None
        return float(value)
    except Exception:
        return None


def _int_or_none(value: Any) -> int | None:
    try:
        if value in (None, "") or value != value:
            return None
        return int(float(value))
    except Exception:
        return None


def _bool_or_none(value: Any) -> bool | None:
    if value in (None, ""):
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n"}:
        return False
    return None


def _distance_within(value: Any, threshold: float) -> bool:
    distance = _float_or_none(value)
    return distance is not None and distance <= threshold


def _points_geometry(points: list[Point]) -> Point | MultiPoint | None:
    if not points:
        return None
    if len(points) == 1:
        return points[0]
    return MultiPoint(points)
