from __future__ import annotations


import csv


import json


import sqlite3


import time


from dataclasses import dataclass


from decimal import Decimal, InvalidOperation


from pathlib import Path


from typing import Any


import fiona


import shapefile


from pyproj import CRS


from shapely import from_wkb


from shapely.geometry import shape


from shapely.geometry.base import BaseGeometry


from shapely.ops import unary_union


from shapely.prepared import prep


from shapely.strtree import STRtree


from shapely.validation import explain_validity


from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    GEOPACKAGE_SUFFIXES,
    TARGET_CRS,
    build_run_id,
    prefer_vector_input_path,
    transform_geometry_to_target,
    write_json,
)


from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg as write_gpkg_sqlite


ALLOWED_KIND2 = {"4", "8", "16", "64", "128", "2048"}


STEP1_HAS_EVD_EVIDENCE_TOLERANCE_M = 1.5


INTERSECTION_ID_FIELDS = ("id", "intersection_id", "intersectionid", "fid", "objectid", "OBJECTID")


PATCH_ID_FIELDS = ("patch_id", "patchid", "PATCH_ID", "PATCHID")


RELATION_EVIDENCE_FIELDNAMES = [
    "target_id",
    "representative_node_id",
    "relation_source",
    "relation_target_type",
    "matched_rcsdintersection_ids",
    "relation_state",
    "status_suggested",
    "base_id_candidate",
    "reason",
    "level",
    "is_highway",
    "swsd_point_x",
    "swsd_point_y",
    "rcsd_point_x",
    "rcsd_point_y",
]


SURFACE_CANDIDATE_FIELDNAMES = [
    "surface_candidate_id",
    "target_id",
    "mainnodeid",
    "representative_node_id",
    "source_module",
    "source_surface_type",
    "source_rcsdintersection_id",
    "source_surface_id",
    "matched_rcsdintersection_ids",
    "junction_type",
    "kind_2",
    "grade_2",
    "patch_id",
    "patch_id_source",
    "final_state",
    "anchor_reason",
    "base_id_candidate",
    "relation_state",
    "status_suggested",
    "level",
    "is_highway",
    "swsd_point_x",
    "swsd_point_y",
    "rcsd_point_x",
    "rcsd_point_y",
]


from . import runner as _facade


def T07StageArtifacts(*args: Any, **kwargs: Any) -> Any:
    return _facade.T07StageArtifacts(*args, **kwargs)


def _audit_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._audit_row(*args, **kwargs)


def _build_node_index(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_node_index(*args, **kwargs)


def _candidate_junction_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._candidate_junction_ids(*args, **kwargs)


def _elapsed_since(*args: Any, **kwargs: Any) -> Any:
    return _facade._elapsed_since(*args, **kwargs)


def _intersection_contains_rcsd_semantic_node(*args: Any, **kwargs: Any) -> Any:
    return _facade._intersection_contains_rcsd_semantic_node(*args, **kwargs)


def _kind2048_surface_assessment(*args: Any, **kwargs: Any) -> Any:
    return _facade._kind2048_surface_assessment(*args, **kwargs)


def _normalize_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._normalize_id(*args, **kwargs)


def _pipe_join_text(*args: Any, **kwargs: Any) -> Any:
    return _facade._pipe_join_text(*args, **kwargs)


def _read_intersections(*args: Any, **kwargs: Any) -> Any:
    return _facade._read_intersections(*args, **kwargs)


def _read_rcsd_semantic_node_records(*args: Any, **kwargs: Any) -> Any:
    return _facade._read_rcsd_semantic_node_records(*args, **kwargs)


def _read_vector_layer(*args: Any, **kwargs: Any) -> Any:
    return _facade._read_vector_layer(*args, **kwargs)


def _resolve_group(*args: Any, **kwargs: Any) -> Any:
    return _facade._resolve_group(*args, **kwargs)


def _stage_root(*args: Any, **kwargs: Any) -> Any:
    return _facade._stage_root(*args, **kwargs)


def _write_csv(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_csv(*args, **kwargs)


def _write_error_outputs(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_error_outputs(*args, **kwargs)


def _write_nodes(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_nodes(*args, **kwargs)


def _write_relation_evidence_json(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_relation_evidence_json(*args, **kwargs)


def _write_surface_candidate_gpkg(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_surface_candidate_gpkg(*args, **kwargs)


def run_t07_step2_anchor_recognition(
    *,
    nodes_path: str | Path,
    intersection_path: str | Path,
    out_root: str | Path,
    rcsdnode_path: str | Path | None = None,
    run_id: str | None = None,
    nodes_layer: str | None = None,
    intersection_layer: str | None = None,
    rcsdnode_layer: str | None = None,
    nodes_crs: str | None = None,
    intersection_crs: str | None = None,
    rcsdnode_crs: str | None = None,
) -> T07StageArtifacts:
    started_at = time.perf_counter()
    stage_timings: dict[str, float] = {}
    run_root, stage_root, resolved_run_id = _stage_root(out_root, run_id, "step2_anchor_recognition")
    stage_root.mkdir(parents=True, exist_ok=True)
    audit_rows: list[dict[str, Any]] = []

    stage_started = time.perf_counter()
    nodes_layer_data = _read_vector_layer(nodes_path, layer_name=nodes_layer, crs_override=nodes_crs, allow_null_geometry=True)
    intersection_layer_data = _read_vector_layer(
        intersection_path,
        layer_name=intersection_layer,
        crs_override=intersection_crs,
        allow_null_geometry=False,
    )
    rcsdnode_layer_data = (
        _read_vector_layer(
            rcsdnode_path,
            layer_name=rcsdnode_layer,
            crs_override=rcsdnode_crs,
            allow_null_geometry=True,
        )
        if rcsdnode_path is not None
        else None
    )
    stage_timings["read_inputs_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    intersections = _read_intersections(intersection_layer_data)
    intersection_by_id = {record.intersection_id: record for record in intersections}
    intersection_tree = STRtree([record.geometry for record in intersections])
    rcsdnode_records = _read_rcsd_semantic_node_records(rcsdnode_layer_data) if rcsdnode_layer_data is not None else []
    rcsdnode_tree = STRtree([record.geometry for record in rcsdnode_records]) if rcsdnode_records else None
    stage_timings["build_intersection_index_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    by_mainnodeid, singleton_by_id = _build_node_index(nodes_layer_data.features, audit_rows)
    junction_ids = _candidate_junction_ids(by_mainnodeid, singleton_by_id)
    stage_timings["prepare_semantic_junctions_seconds"] = _elapsed_since(stage_started)
    counts = {
        "semantic_junction_count": len(junction_ids),
        "stage2_candidate_count": 0,
        "anchor_yes_count": 0,
        "anchor_no_count": 0,
        "anchor_fail1_count": 0,
        "anchor_fail2_count": 0,
        "anchor_null_count": 0,
        "roundabout_reason_count": 0,
        "t_reason_count": 0,
        "rcsdintersection_no_rcsdnode_count": 0,
        "t_junction_surface_anchor_count": 0,
        "t_junction_surface_rejected_count": 0,
    }
    group_results: dict[str, dict[str, Any]] = {}
    intersection_to_junctions: dict[str, set[str]] = {}
    error1_rows: list[dict[str, Any]] = []
    error1_indexes: set[int] = set()
    error1_metadata: dict[int, dict[str, Any]] = {}
    node_hit_cache: dict[int, tuple[str, ...]] = {}

    stage_started = time.perf_counter()
    for junction_id in junction_ids:
        group = _resolve_group(junction_id, by_mainnodeid=by_mainnodeid, singleton_by_id=singleton_by_id)
        if group.representative is None:
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="error",
                    reason=group.reason or "representative_node_missing",
                    detail=group.detail or "representative node missing",
                    junction_id=junction_id,
                )
            )
            group_results[junction_id] = {"participates": False, "group": group}
            continue

        representative_props = nodes_layer_data.features[group.representative.output_index].properties
        representative_has_evd = _normalize_id(representative_props.get("has_evd"))
        kind_2 = _normalize_id(representative_props.get("kind_2"))
        if representative_has_evd != "yes" or kind_2 not in ALLOWED_KIND2:
            representative_props["is_anchor"] = None
            representative_props["anchor_reason"] = None
            counts["anchor_null_count"] += 1
            group_results[junction_id] = {"participates": False, "group": group, "intersection_ids": []}
            continue

        hit_intersection_ids: set[str] = set()
        for record in group.group_nodes:
            cached = node_hit_cache.get(record.output_index)
            if cached is None:
                indexes = intersection_tree.query(record.geometry, predicate="intersects")
                cached = tuple(sorted({intersections[int(index)].intersection_id for index in indexes}))
                node_hit_cache[record.output_index] = cached
            for intersection_id in cached:
                hit_intersection_ids.add(intersection_id)

        sorted_raw_hits = sorted(hit_intersection_ids)
        unconsumable_intersection_ids: list[str] = []
        if rcsdnode_tree is None:
            sorted_hits = sorted_raw_hits
        else:
            consumable_hits: list[str] = []
            for intersection_id in sorted_raw_hits:
                intersection_record = intersection_by_id.get(intersection_id)
                if intersection_record is None:
                    continue
                if _intersection_contains_rcsd_semantic_node(
                    intersection=intersection_record,
                    rcsdnode_tree=rcsdnode_tree,
                    rcsdnode_records=rcsdnode_records,
                ):
                    consumable_hits.append(intersection_id)
                else:
                    unconsumable_intersection_ids.append(intersection_id)
            sorted_hits = consumable_hits

        if kind_2 == "2048":
            assessment = _kind2048_surface_assessment(
                junction_id=junction_id,
                group=group,
                junction_ids=junction_ids,
                by_mainnodeid=by_mainnodeid,
                singleton_by_id=singleton_by_id,
                intersections=intersections,
                intersection_by_id=intersection_by_id,
                rcsdnode_tree=rcsdnode_tree,
                rcsdnode_records=rcsdnode_records,
            )
            if assessment["accepted"]:
                counts["stage2_candidate_count"] += 1
                counts["t_junction_surface_anchor_count"] += 1
                group_results[junction_id] = {
                    "participates": True,
                    "fail2_eligible": False,
                    "group": group,
                    "kind_2": kind_2,
                    "provisional_state": "yes",
                    "provisional_reason": None,
                    "intersection_ids": list(assessment.get("intersection_ids") or []),
                    "relation_state": "existing_rcsdintersection_matched",
                    "base_id_candidate": assessment.get("base_id_candidate"),
                }
                audit_rows.append(
                    _audit_row(
                        scope="semantic_junction",
                        status="accepted",
                        reason=assessment["reason"],
                        detail=assessment["detail"],
                        junction_id=junction_id,
                        node_id=group.representative.node_id,
                        intersection_ids=list(assessment.get("intersection_ids") or []),
                    )
                )
            else:
                representative_props["is_anchor"] = "no"
                representative_props["anchor_reason"] = None
                counts["anchor_no_count"] += 1
                counts["t_junction_surface_rejected_count"] += 1
                if assessment["reason"] == "t_junction_surface_no_rcsd_semantic_node":
                    counts["rcsdintersection_no_rcsdnode_count"] += 1
                group_results[junction_id] = {
                    "participates": False,
                    "fail2_eligible": False,
                    "group": group,
                    "kind_2": kind_2,
                    "intersection_ids": list(assessment.get("intersection_ids") or []),
                    "relation_state": assessment["reason"],
                    "base_id_candidate": _pipe_join_text(list(assessment.get("related_rcsd_semantic_ids") or [])) or None,
                }
                audit_rows.append(
                    _audit_row(
                        scope="semantic_junction",
                        status="skipped",
                        reason=assessment["reason"],
                        detail=assessment["detail"],
                        junction_id=junction_id,
                        node_id=group.representative.node_id,
                        intersection_ids=list(assessment.get("intersection_ids") or []),
                    )
                )
            continue
        if unconsumable_intersection_ids and not sorted_hits:
            counts["rcsdintersection_no_rcsdnode_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="skipped",
                    reason="rcsdintersection_no_rcsd_semantic_node",
                    detail="Matched RCSDIntersection surface contains no usable RCSDNode id/mainnodeid geometry; T07 Step2 leaves this SWSD junction for T03/T04 virtual anchoring.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    intersection_ids=unconsumable_intersection_ids,
                )
            )
        for intersection_id in sorted_hits:
            intersection_to_junctions.setdefault(intersection_id, set()).add(junction_id)

        if kind_2 in {"64", "128"}:
            representative_props["is_anchor"] = "no"
            representative_props["anchor_reason"] = None
            counts["anchor_no_count"] += 1
            group_results[junction_id] = {
                "participates": False,
                "fail2_eligible": True,
                "group": group,
                "kind_2": kind_2,
                "intersection_ids": sorted_hits,
            }
            continue

        counts["stage2_candidate_count"] += 1
        provisional_reason = None

        if not sorted_hits:
            provisional_state = "no"
            provisional_relation_state = (
                "rcsdintersection_no_rcsd_semantic_node" if unconsumable_intersection_ids else None
            )
        elif len(sorted_hits) == 1:
            provisional_state = "yes"
            provisional_relation_state = None
        elif len(group.group_nodes) == 1 or provisional_reason is not None:
            provisional_state = "yes"
            provisional_relation_state = None
        else:
            provisional_state = "fail1"
            provisional_relation_state = None
            involved_node_ids = [record.node_id for record in group.group_nodes]
            error1_rows.append(
                _audit_row(
                    scope="node_error_1",
                    status="error",
                    reason="multiple_intersections_for_group",
                    detail="One semantic junction group intersects more than one RCSDIntersection feature.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    intersection_ids=sorted_hits,
                    involved_node_ids=involved_node_ids,
                )
            )
            for record in group.group_nodes:
                error1_indexes.add(record.output_index)
                error1_metadata[record.output_index] = {
                    "error_type": "node_error_1",
                    "junction_id": junction_id,
                    "representative_node_id": group.representative.node_id,
                    "intersection_ids": ",".join(sorted_hits),
                }

        group_results[junction_id] = {
            "participates": True,
            "fail2_eligible": True,
            "group": group,
            "kind_2": kind_2,
            "provisional_state": provisional_state,
            "provisional_reason": provisional_reason if provisional_state == "yes" else None,
            "intersection_ids": sorted_hits if sorted_hits else unconsumable_intersection_ids,
            "relation_state": provisional_relation_state,
        }
    stage_timings["process_anchor_candidates_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    fail2_by_junction: dict[str, set[str]] = {}
    for intersection_id, linked_junction_ids in intersection_to_junctions.items():
        filtered = []
        for junction_id in sorted(linked_junction_ids):
            result = group_results.get(junction_id)
            if not result or not result.get("fail2_eligible"):
                continue
            if result.get("kind_2") == "1":
                continue
            filtered.append(junction_id)
        if len(filtered) <= 1:
            continue
        for junction_id in filtered:
            fail2_by_junction.setdefault(junction_id, set()).add(intersection_id)

    error2_rows: list[dict[str, Any]] = []
    error2_indexes: set[int] = set()
    error2_metadata: dict[int, dict[str, Any]] = {}
    for junction_id, intersection_ids in sorted(fail2_by_junction.items()):
        group = group_results[junction_id]["group"]
        involved_node_ids = [record.node_id for record in group.group_nodes]
        sorted_ids = sorted(intersection_ids)
        error2_rows.append(
            _audit_row(
                scope="node_error_2",
                status="error",
                reason="intersection_shared_by_multiple_groups",
                detail="One RCSDIntersection feature intersects more than one semantic junction group.",
                junction_id=junction_id,
                node_id=group.representative.node_id if group.representative else None,
                intersection_ids=sorted_ids,
                involved_node_ids=involved_node_ids,
            )
        )
        for record in group.group_nodes:
            error2_indexes.add(record.output_index)
            error2_metadata[record.output_index] = {
                "error_type": "node_error_2",
                "junction_id": junction_id,
                "representative_node_id": group.representative.node_id if group.representative else None,
                "intersection_ids": ",".join(sorted_ids),
            }

    for junction_id, result in group_results.items():
        if not result.get("participates") and junction_id not in fail2_by_junction:
            continue
        group = result["group"]
        representative_props = nodes_layer_data.features[group.representative.output_index].properties
        if junction_id in fail2_by_junction:
            final_state = "fail2"
            final_reason = None
            if not result.get("participates"):
                previous_state = _normalize_id(representative_props.get("is_anchor"))
                previous_reason = _normalize_id(representative_props.get("anchor_reason"))
                if previous_state == "yes":
                    counts["anchor_yes_count"] -= 1
                elif previous_state == "no":
                    counts["anchor_no_count"] -= 1
                if previous_reason == "t":
                    counts["t_reason_count"] -= 1
                elif previous_reason == "roundabout":
                    counts["roundabout_reason_count"] -= 1
        elif result["provisional_state"] == "fail1":
            final_state = "fail1"
            final_reason = None
        elif result["provisional_state"] == "yes":
            final_state = "yes"
            final_reason = result["provisional_reason"]
        else:
            final_state = "no"
            final_reason = None

        representative_props["is_anchor"] = final_state
        representative_props["anchor_reason"] = final_reason
        if final_state == "yes":
            counts["anchor_yes_count"] += 1
        elif final_state == "no":
            counts["anchor_no_count"] += 1
        elif final_state == "fail1":
            counts["anchor_fail1_count"] += 1
        elif final_state == "fail2":
            counts["anchor_fail2_count"] += 1
        if final_reason == "roundabout":
            counts["roundabout_reason_count"] += 1
        elif final_reason == "t":
            counts["t_reason_count"] += 1
    stage_timings["resolve_conflicts_seconds"] = _elapsed_since(stage_started)

    nodes_output_path = stage_root / "nodes.gpkg"
    summary_path = stage_root / "t07_step2_summary.json"
    audit_csv_path = stage_root / "t07_step2_audit.csv"
    audit_json_path = stage_root / "t07_step2_audit.json"
    perf_path = stage_root / "t07_step2_perf.json"
    node_error_1_path = stage_root / "node_error_1.gpkg"
    node_error_2_path = stage_root / "node_error_2.gpkg"
    relation_evidence_csv_path = stage_root / "t07_swsd_rcsd_relation_evidence.csv"
    relation_evidence_json_path = stage_root / "t07_swsd_rcsd_relation_evidence.json"
    surface_candidates_path = stage_root / "t07_rcsdintersection_anchor_surface.gpkg"

    stage_started = time.perf_counter()
    _write_nodes(nodes_output_path, nodes_layer_data.features)
    stage_timings["write_nodes_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    _write_error_outputs(
        vector_path=node_error_1_path,
        audit_csv_path=stage_root / "node_error_1_audit.csv",
        audit_json_path=stage_root / "node_error_1_audit.json",
        node_features=nodes_layer_data.features,
        feature_indexes=error1_indexes,
        metadata=error1_metadata,
        rows=error1_rows,
        run_id=resolved_run_id,
    )
    _write_error_outputs(
        vector_path=node_error_2_path,
        audit_csv_path=stage_root / "node_error_2_audit.csv",
        audit_json_path=stage_root / "node_error_2_audit.json",
        node_features=nodes_layer_data.features,
        feature_indexes=error2_indexes,
        metadata=error2_metadata,
        rows=error2_rows,
        run_id=resolved_run_id,
    )
    relation_evidence_rows = _write_relation_evidence_json(
        csv_path=relation_evidence_csv_path,
        json_path=relation_evidence_json_path,
        run_id=resolved_run_id,
        nodes_features=nodes_layer_data.features,
        group_results=group_results,
        junction_ids=junction_ids,
        intersection_by_id=intersection_by_id,
        fail2_by_junction=fail2_by_junction,
    )
    surface_candidate_rows = _write_surface_candidate_gpkg(
        path=surface_candidates_path,
        nodes_features=nodes_layer_data.features,
        group_results=group_results,
        junction_ids=junction_ids,
        intersection_by_id=intersection_by_id,
    )
    stage_timings["write_error_outputs_seconds"] = _elapsed_since(stage_started)
    summary = {
        "run_id": resolved_run_id,
        **counts,
        "input_paths": {
            "nodes": str(nodes_path),
            "intersection": str(intersection_path),
            "rcsdnode": str(rcsdnode_path) if rcsdnode_path is not None else None,
        },
        "output_paths": {
            "nodes": str(nodes_output_path),
            "node_error_1": str(node_error_1_path),
            "node_error_2": str(node_error_2_path),
            "t07_swsd_rcsd_relation_evidence_csv": str(relation_evidence_csv_path),
            "t07_swsd_rcsd_relation_evidence": str(relation_evidence_json_path),
            "t07_rcsdintersection_anchor_surface": str(surface_candidates_path),
        },
        "target_crs": TARGET_CRS.to_string(),
        "audit_count": len(audit_rows),
        "relation_evidence_row_count": len(relation_evidence_rows),
        "surface_candidate_count": len(surface_candidate_rows),
        "performance": {
            "elapsed_seconds": _elapsed_since(started_at),
            "stage_timings": stage_timings,
        },
    }
    stage_started = time.perf_counter()
    write_json(summary_path, summary)
    _write_csv(audit_csv_path, audit_rows, ["scope", "junction_id", "node_id", "status", "reason", "detail"])
    write_json(audit_json_path, {"run_id": resolved_run_id, "rows": audit_rows})
    stage_timings["write_audit_summary_seconds"] = _elapsed_since(stage_started)
    write_json(
        perf_path,
        {
            "run_id": resolved_run_id,
            "elapsed_sec": _elapsed_since(started_at),
            "stage_timings": stage_timings,
            **counts,
        },
    )
    return T07StageArtifacts(
        run_root,
        stage_root,
        nodes_output_path,
        summary_path,
        audit_csv_path,
        audit_json_path,
        perf_path,
        relation_evidence_csv_path=relation_evidence_csv_path,
        relation_evidence_json_path=relation_evidence_json_path,
        anchor_surface_path=surface_candidates_path,
    )
