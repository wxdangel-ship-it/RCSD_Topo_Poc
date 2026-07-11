from __future__ import annotations


import json


import shutil


import sqlite3


import time


from collections import Counter, defaultdict


from dataclasses import dataclass


from pathlib import Path


from typing import Any


from pyproj import Transformer


from shapely.geometry import LineString, mapping, shape


from shapely.geometry.base import BaseGeometry


from shapely.strtree import STRtree


from shapely.ops import transform as shapely_transform


from rcsd_topo_poc.modules.t00_utility_toolbox.common import TARGET_CRS, prefer_vector_input_path, write_json


from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_models import RELATION_OUTPUT_CRS_NAME


from rcsd_topo_poc.modules.t08_preprocess.vector_io import ensure_gpkg_ogr_feature_count_metadata, write_gpkg


from .runner import (
    RELATION_EVIDENCE_FIELDNAMES,
    SURFACE_CANDIDATE_FIELDNAMES,
    T07RunError,
    _audit_row,
    _build_node_index,
    _candidate_junction_ids,
    _elapsed_since,
    _normalize_id,
    _point_xy,
    _read_vector_layer,
    _resolve_gpkg_crs,
    _resolve_gpkg_layer,
    _resolve_group,
    _stage_root,
    _value_or_minus_one,
    _write_csv,
    _write_nodes,
)


STEP3_SURFACE_KIND2 = {"4", "8", "16", "2048"}


STEP3_BACKFILL_KIND2 = {"4", "8", "16", "128", "2048"}


STEP3_SCOPE_KIND2 = STEP3_SURFACE_KIND2 | STEP3_BACKFILL_KIND2


RELATION_CARDINALITY_ERROR_FIELDS = [
    "error_type",
    "target_id",
    "base_id",
    "related_target_ids",
    "introduced_by_module",
    "source_modules",
    "source_case_ids",
    "scenes",
    "reasons",
]


RCSDNODE_ERROR_FIELDNAMES = [
    "error_type",
    "target_id",
    "surface_candidate_id",
    "source_rcsdintersection_id",
    "rcsd_semantic_id",
    "rcsd_node_id",
    "related_rcsd_semantic_ids",
]


from . import step3_intersection_match as _facade


def RCSDNodeRecord(*args: Any, **kwargs: Any) -> Any:
    return _facade.RCSDNodeRecord(*args, **kwargs)


def RelationRecord(*args: Any, **kwargs: Any) -> Any:
    return _facade.RelationRecord(*args, **kwargs)


def T07Step3Artifacts(*args: Any, **kwargs: Any) -> Any:
    return _facade.T07Step3Artifacts(*args, **kwargs)


def _build_rcsd_semantic_id_set(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_rcsd_semantic_id_set(*args, **kwargs)


def _build_relation_cardinality_errors_from_records(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_relation_cardinality_errors_from_records(*args, **kwargs)


def _build_relations_by_target(*args: Any, **kwargs: Any) -> Any:
    return _facade._build_relations_by_target(*args, **kwargs)


def _dedupe_relation_records(*args: Any, **kwargs: Any) -> Any:
    return _facade._dedupe_relation_records(*args, **kwargs)


def _is_success_relation(*args: Any, **kwargs: Any) -> Any:
    return _facade._is_success_relation(*args, **kwargs)


def _load_step2_relation_evidence_rows(*args: Any, **kwargs: Any) -> Any:
    return _facade._load_step2_relation_evidence_rows(*args, **kwargs)


def _one_to_many_target_ids(*args: Any, **kwargs: Any) -> Any:
    return _facade._one_to_many_target_ids(*args, **kwargs)


def _rcsdnode_records(*args: Any, **kwargs: Any) -> Any:
    return _facade._rcsdnode_records(*args, **kwargs)


def _read_relation_records(*args: Any, **kwargs: Any) -> Any:
    return _facade._read_relation_records(*args, **kwargs)


def _read_step2_surface_features(*args: Any, **kwargs: Any) -> Any:
    return _facade._read_step2_surface_features(*args, **kwargs)


def _relation_cardinality_summary(*args: Any, **kwargs: Any) -> Any:
    return _facade._relation_cardinality_summary(*args, **kwargs)


def _relation_record_from_step2_surface(*args: Any, **kwargs: Any) -> Any:
    return _facade._relation_record_from_step2_surface(*args, **kwargs)


def _representative_rcsdnode_by_semantic_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._representative_rcsdnode_by_semantic_id(*args, **kwargs)


def _sort_key(*args: Any, **kwargs: Any) -> Any:
    return _facade._sort_key(*args, **kwargs)


def _step2_surface_relation_evidence_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._step2_surface_relation_evidence_row(*args, **kwargs)


def _step3_relation_evidence_row(*args: Any, **kwargs: Any) -> Any:
    return _facade._step3_relation_evidence_row(*args, **kwargs)


def _surface_kind2(*args: Any, **kwargs: Any) -> Any:
    return _facade._surface_kind2(*args, **kwargs)


def _surface_target_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._surface_target_id(*args, **kwargs)


def _write_merged_relation_evidence_json(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_merged_relation_evidence_json(*args, **kwargs)


def _write_rcsdnode_error_output(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_rcsdnode_error_output(*args, **kwargs)


def _write_relation_output(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_relation_output(*args, **kwargs)


def _write_step3_anchor_surface(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_step3_anchor_surface(*args, **kwargs)


def _write_step3_nodes(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_step3_nodes(*args, **kwargs)


def run_t07_step3_intersection_match(
    *,
    nodes_path: str | Path,
    intersection_match_all_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    nodes_layer: str | None = None,
    rcsdnode_layer: str | None = None,
    nodes_crs: str | None = None,
    intersection_match_all_crs: str | None = None,
    rcsdnode_crs: str | None = None,
) -> T07Step3Artifacts:
    started_at = time.perf_counter()
    stage_timings: dict[str, float] = {}
    run_root, stage_root, resolved_run_id = _stage_root(out_root, run_id, "step3_intersection_match")
    stage_root.mkdir(parents=True, exist_ok=True)
    audit_rows: list[dict[str, Any]] = []

    read_inputs_started = time.perf_counter()
    stage_started = time.perf_counter()
    nodes_layer_data = _read_vector_layer(
        nodes_path,
        layer_name=nodes_layer,
        crs_override=nodes_crs,
        allow_null_geometry=True,
    )
    stage_timings["read_nodes_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    relation_records = _read_relation_records(
        intersection_match_all_path,
        crs_override=intersection_match_all_crs,
    )
    stage_timings["read_intersection_match_all_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    rcsdnode_layer_data = _read_vector_layer(
        rcsdnode_path,
        layer_name=rcsdnode_layer,
        crs_override=rcsdnode_crs,
        allow_null_geometry=True,
    )
    rcsdnode_properties = [dict(feature.properties) for feature in rcsdnode_layer_data.features]
    stage_timings["read_rcsdnode_ids_seconds"] = _elapsed_since(stage_started)
    stage_timings["read_inputs_seconds"] = _elapsed_since(read_inputs_started)

    stage_started = time.perf_counter()
    by_mainnodeid, singleton_by_id = _build_node_index(nodes_layer_data.features, audit_rows)
    junction_ids = _candidate_junction_ids(by_mainnodeid, singleton_by_id)
    relations_by_target, invalid_relation_count = _build_relations_by_target(relation_records, audit_rows)
    rcsd_semantic_ids = _build_rcsd_semantic_id_set(rcsdnode_properties)
    rcsdnode_records = _rcsdnode_records(rcsdnode_layer_data.features)
    rcsd_representatives = _representative_rcsdnode_by_semantic_id(rcsdnode_records)
    rcsd_geometries = [record.geometry for record in rcsdnode_records]
    rcsd_tree = STRtree(rcsd_geometries) if rcsd_geometries else None
    step2_relation_evidence_path = prefer_vector_input_path(Path(nodes_path)).parent / "t07_swsd_rcsd_relation_evidence.json"
    step2_relation_evidence_rows = _load_step2_relation_evidence_rows(step2_relation_evidence_path)
    step2_anchor_surface_path = prefer_vector_input_path(Path(nodes_path)).parent / "t07_rcsdintersection_anchor_surface.gpkg"
    step2_surface_features = _read_step2_surface_features(step2_anchor_surface_path)
    stage_timings["prepare_indices_seconds"] = _elapsed_since(stage_started)

    counts = {
        "semantic_junction_count": len(junction_ids),
        "step3_scope_kind2_count": 0,
        "candidate_count": 0,
        "accepted_count": 0,
        "not_candidate_count": 0,
        "skipped_kind2_count": 0,
        "relation_missing_count": 0,
        "relation_failure_count": 0,
        "relation_duplicate_count": 0,
        "rcsd_missing_count": 0,
        "step2_surface_1v1_relation_count": 0,
        "intersection_match_backfill_relation_count": 0,
        "step2_surface_no_rcsd_count": 0,
        "rcsdnode_error_surface_count": 0,
        "rcsdnode_error_count": 0,
        "already_linked_base_skip_count": 0,
        "representative_missing_count": 0,
        "invalid_relation_count": invalid_relation_count,
    }
    tentative_relations: list[RelationRecord] = []
    tentative_relation_evidence_rows: list[dict[str, Any]] = []
    rcsdnode_error_rows: list[dict[str, Any]] = []
    linked_base_ids: set[str] = set()

    stage_started = time.perf_counter()
    surface_features_by_target: dict[str, list[Any]] = defaultdict(list)
    for surface_feature in step2_surface_features:
        surface_props = dict(surface_feature.properties)
        target_id = _surface_target_id(surface_props)
        if target_id is None or _surface_kind2(surface_props) not in STEP3_SURFACE_KIND2:
            continue
        surface_features_by_target[target_id].append(surface_feature)

    for target_id, surface_features in sorted(surface_features_by_target.items(), key=lambda item: _sort_key(item[0])):
        if len(surface_features) != 1:
            audit_rows.append(
                _audit_row(
                    scope="step2_surface",
                    status="skipped",
                    reason="step2_surface_not_one_to_one",
                    detail="Step3 only builds direct relation from Step2 targets with exactly one RCSDIntersection surface.",
                    junction_id=target_id,
                    target_id=target_id,
                )
            )
            continue
        surface_feature = surface_features[0]
        surface_props = dict(surface_feature.properties)
        surface_geometry = surface_feature.geometry
        group = _resolve_group(target_id, by_mainnodeid=by_mainnodeid, singleton_by_id=singleton_by_id)
        if group.representative is None:
            audit_rows.append(
                _audit_row(
                    scope="step2_surface",
                    status="error",
                    reason=group.reason or "representative_node_missing",
                    detail=group.detail or "representative node missing for Step2 surface target",
                    junction_id=target_id,
                    target_id=target_id,
                )
            )
            continue
        representative_feature = nodes_layer_data.features[group.representative.output_index]
        representative_props = representative_feature.properties

        contained_records: list[RCSDNodeRecord] = []
        if surface_geometry is not None and rcsd_tree is not None:
            for index in rcsd_tree.query(surface_geometry, predicate="intersects"):
                record = rcsdnode_records[int(index)]
                if surface_geometry.covers(record.geometry):
                    contained_records.append(record)
        contained_semantic_ids = sorted({record.semantic_id for record in contained_records}, key=_sort_key)
        if not contained_semantic_ids:
            counts["step2_surface_no_rcsd_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="step2_surface",
                    status="skipped",
                    reason="step2_surface_no_rcsd_junction",
                    detail="Step2 RCSDIntersection surface contains no RCSD semantic junction in input RCSDNode.",
                    junction_id=target_id,
                    node_id=group.representative.node_id,
                    target_id=target_id,
                )
            )
            continue
        if len(contained_semantic_ids) > 1:
            counts["rcsdnode_error_surface_count"] += 1
            related_ids = "|".join(contained_semantic_ids)
            for semantic_id in contained_semantic_ids:
                error_record = rcsd_representatives.get(semantic_id)
                if error_record is None:
                    continue
                error_props = {
                    "error_type": "multiple_rcsd_junctions_in_step2_surface",
                    "target_id": target_id,
                    "surface_candidate_id": _normalize_id(surface_props.get("surface_candidate_id")) or "",
                    "source_rcsdintersection_id": _normalize_id(surface_props.get("source_rcsdintersection_id")) or "",
                    "rcsd_semantic_id": semantic_id,
                    "rcsd_node_id": error_record.node_id,
                    "related_rcsd_semantic_ids": related_ids,
                    "_geometry": error_record.geometry,
                }
                rcsdnode_error_rows.append(error_props)
            audit_rows.append(
                _audit_row(
                    scope="step2_surface",
                    status="error",
                    reason="multiple_rcsd_junctions_in_step2_surface",
                    detail="Step2 RCSDIntersection surface contains more than one RCSD semantic junction.",
                    junction_id=target_id,
                    node_id=group.representative.node_id,
                    target_id=target_id,
                    base_id=related_ids,
                    rcsd_exists=1,
                )
            )
            continue

        base_id = contained_semantic_ids[0]
        base_record = rcsd_representatives.get(base_id)
        if base_record is None:
            continue
        relation_record = _relation_record_from_step2_surface(
            feature_index=surface_feature.feature_index,
            surface_props=surface_props,
            surface_geometry=surface_geometry,
            base_record=base_record,
            representative_geometry=group.representative.geometry,
        )
        representative_props["is_anchor"] = "yes"
        representative_props["anchor_reason"] = None
        tentative_relations.append(relation_record)
        tentative_relation_evidence_rows.append(
            _step2_surface_relation_evidence_row(
                relation_record=relation_record,
                representative_node_id=group.representative.node_id,
                representative_props=representative_props,
                representative_geometry=group.representative.geometry,
                rcsd_geometry=base_record.geometry,
            )
        )
        linked_base_ids.add(base_id)
        counts["step2_surface_1v1_relation_count"] += 1
        audit_rows.append(
            _audit_row(
                scope="step2_surface",
                status="accepted",
                reason="step2_surface_1v1_rcsdnode_matched",
                detail="Step2 RCSDIntersection surface contains exactly one RCSD semantic junction.",
                junction_id=target_id,
                node_id=group.representative.node_id,
                target_id=target_id,
                base_id=base_id,
                rcsd_exists=1,
            )
        )

    for junction_id in junction_ids:
        group = _resolve_group(junction_id, by_mainnodeid=by_mainnodeid, singleton_by_id=singleton_by_id)
        if group.representative is None:
            counts["representative_missing_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="error",
                    reason=group.reason or "representative_node_missing",
                    detail=group.detail or "representative node missing",
                    junction_id=junction_id,
                )
            )
            continue

        representative_props = nodes_layer_data.features[group.representative.output_index].properties
        kind_2 = _normalize_id(representative_props.get("kind_2"))
        has_evd = _normalize_id(representative_props.get("has_evd"))
        is_anchor = _normalize_id(representative_props.get("is_anchor"))
        if kind_2 not in STEP3_SCOPE_KIND2:
            counts["skipped_kind2_count"] += 1
            continue
        counts["step3_scope_kind2_count"] += 1

        if kind_2 not in STEP3_BACKFILL_KIND2 or has_evd != "yes" or is_anchor != "no":
            counts["not_candidate_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="skipped",
                    reason="not_step3_candidate",
                    detail="Step3 T05 relation backfill only processes has_evd=yes and is_anchor=no representatives in kind_2 {4,8,16,128,2048}.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    kind_2=kind_2,
                    has_evd=has_evd,
                    is_anchor=is_anchor,
                )
            )
            continue

        counts["candidate_count"] += 1
        relation_records = relations_by_target.get(junction_id, [])
        if not relation_records:
            counts["relation_missing_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="skipped",
                    reason="relation_missing",
                    detail="candidate SWSD junction has no relation in intersection_match_all.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    kind_2=kind_2,
                    has_evd=has_evd,
                    is_anchor=is_anchor,
                    target_id=junction_id,
                )
            )
            continue
        if len(relation_records) > 1:
            counts["relation_duplicate_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="error",
                    reason="duplicate_target_id_relation",
                    detail="candidate SWSD junction has multiple relation rows; Step3 does not choose among them.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    kind_2=kind_2,
                    has_evd=has_evd,
                    is_anchor=is_anchor,
                    target_id=junction_id,
                )
            )

        for relation_record in relation_records:
            if not _is_success_relation(relation_record):
                counts["relation_failure_count"] += 1
                audit_rows.append(
                    _audit_row(
                        scope="semantic_junction",
                        status="skipped",
                        reason="relation_not_successful",
                        detail="intersection_match_all relation is not status=0 with a non-zero base_id.",
                        junction_id=junction_id,
                        node_id=group.representative.node_id,
                        kind_2=kind_2,
                        has_evd=has_evd,
                        is_anchor=is_anchor,
                        target_id=relation_record.target_id,
                        base_id=relation_record.base_id,
                        relation_status=relation_record.status,
                        rcsd_exists=0,
                    )
                )
                continue

            if relation_record.base_id not in rcsd_semantic_ids:
                counts["rcsd_missing_count"] += 1
                audit_rows.append(
                    _audit_row(
                        scope="semantic_junction",
                        status="skipped",
                        reason="rcsd_junction_missing",
                        detail="relation base_id is not present in input RCSDNode id/mainnodeid values.",
                        junction_id=junction_id,
                        node_id=group.representative.node_id,
                        kind_2=kind_2,
                        has_evd=has_evd,
                        is_anchor=is_anchor,
                        target_id=relation_record.target_id,
                        base_id=relation_record.base_id,
                        relation_status=relation_record.status,
                        rcsd_exists=0,
                    )
                )
                continue

            if relation_record.base_id in linked_base_ids:
                counts["already_linked_base_skip_count"] += 1
                audit_rows.append(
                    _audit_row(
                        scope="semantic_junction",
                        status="skipped",
                        reason="rcsd_junction_already_linked",
                        detail="relation base_id already has a Step3 relation built from Step2 one-to-one surface.",
                        junction_id=junction_id,
                        node_id=group.representative.node_id,
                        kind_2=kind_2,
                        has_evd=has_evd,
                        is_anchor=is_anchor,
                        target_id=relation_record.target_id,
                        base_id=relation_record.base_id,
                        relation_status=relation_record.status,
                        rcsd_exists=1,
                    )
                )
                continue

            representative_props["is_anchor"] = "yes"
            representative_props["anchor_reason"] = None
            tentative_relations.append(relation_record)
            tentative_relation_evidence_rows.append(
                _step3_relation_evidence_row(
                    relation_record=relation_record,
                    representative_node_id=group.representative.node_id,
                    representative_props=representative_props,
                    representative_geometry=group.representative.geometry,
                )
            )
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="accepted",
                    reason="t05_relation_rcsd_junction_exists",
                    detail="candidate SWSD junction has a successful T05 relation whose RCSD base_id exists in input RCSDNode.",
                    junction_id=junction_id,
                    node_id=group.representative.node_id,
                    kind_2=kind_2,
                    has_evd=has_evd,
                    is_anchor="yes",
                    target_id=relation_record.target_id,
                    base_id=relation_record.base_id,
                    relation_status=relation_record.status,
                    rcsd_exists=1,
                )
            )
    stage_timings["evaluate_candidates_seconds"] = _elapsed_since(stage_started)

    relation_cardinality_errors = _build_relation_cardinality_errors_from_records(tentative_relations)
    one_to_many_target_ids = _one_to_many_target_ids(relation_cardinality_errors)
    reset_node_ids: list[str] = []
    if one_to_many_target_ids:
        for target_id in sorted(one_to_many_target_ids, key=_sort_key):
            group = _resolve_group(target_id, by_mainnodeid=by_mainnodeid, singleton_by_id=singleton_by_id)
            if group.representative is not None:
                representative_props = nodes_layer_data.features[group.representative.output_index].properties
                representative_props["is_anchor"] = "no"
                representative_props["anchor_reason"] = None
                reset_node_ids.append(group.representative.node_id)
            audit_rows.append(
                _audit_row(
                    scope="relation_cardinality",
                    status="error",
                    reason="one_target_to_many_base_removed",
                    detail="Final Step3 relation has one SWSD semantic junction linked to multiple RCSD semantic junctions; all relations for this target were removed.",
                    junction_id=target_id,
                    target_id=target_id,
                )
            )

    accepted_relations = _dedupe_relation_records(
        [record for record in tentative_relations if record.target_id not in one_to_many_target_ids]
    )
    accepted_relation_evidence_rows = [
        row
        for row in tentative_relation_evidence_rows
        if _normalize_id(row.get("target_id")) not in one_to_many_target_ids
    ]
    newly_accepted_node_ids = sorted(
        {
            node_id
            for row in accepted_relation_evidence_rows
            if (node_id := _normalize_id(row.get("representative_node_id"))) is not None
            and _normalize_id(row.get("relation_source")) != "T07_STEP3_STEP2_SURFACE"
        },
        key=_sort_key,
    )
    node_anchor_updates = {node_id: "yes" for node_id in newly_accepted_node_ids}
    node_anchor_updates.update({node_id: "no" for node_id in reset_node_ids})
    counts["accepted_count"] = len(accepted_relations)
    counts["step2_surface_1v1_relation_count"] = sum(
        1 for record in accepted_relations if _normalize_id(record.properties.get("relation_source")) == "T07_STEP3_STEP2_SURFACE"
    )
    counts["intersection_match_backfill_relation_count"] = sum(
        1 for record in accepted_relations if _normalize_id(record.properties.get("relation_source")) != "T07_STEP3_STEP2_SURFACE"
    )
    counts["rcsdnode_error_count"] = len(rcsdnode_error_rows)
    counts["swsd_multi_rcsd_error_count"] = len(one_to_many_target_ids)
    relation_cardinality_counts = _relation_cardinality_summary(relation_cardinality_errors)

    nodes_output_path = stage_root / "nodes.gpkg"
    relation_output_path = stage_root / "intersection_match_t07.geojson"
    surface_output_path = stage_root / "t07_rcsdintersection_anchor_surface.gpkg"
    rcsdnode_error_path = stage_root / "RCSDNode_error.gpkg"
    relation_evidence_csv_path = stage_root / "t07_swsd_rcsd_relation_evidence.csv"
    relation_evidence_json_path = stage_root / "t07_swsd_rcsd_relation_evidence.json"
    relation_cardinality_errors_csv_path = stage_root / "relation_cardinality_errors.csv"
    relation_cardinality_errors_json_path = stage_root / "relation_cardinality_errors.json"
    summary_path = stage_root / "t07_step3_summary.json"
    audit_csv_path = stage_root / "t07_step3_audit.csv"
    audit_json_path = stage_root / "t07_step3_audit.json"
    perf_path = stage_root / "t07_step3_perf.json"

    write_outputs_started = time.perf_counter()
    stage_started = time.perf_counter()
    nodes_write_mode = _write_step3_nodes(
        output_path=nodes_output_path,
        features=nodes_layer_data.features,
        source_path=nodes_path,
        source_layer=nodes_layer,
        source_crs=nodes_crs,
        node_anchor_updates=node_anchor_updates,
    )
    stage_timings["write_nodes_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    _write_relation_output(relation_output_path, accepted_relations)
    stage_timings["write_relation_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    _write_rcsdnode_error_output(rcsdnode_error_path, rcsdnode_error_rows)
    stage_timings["write_rcsdnode_error_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    _write_csv(relation_cardinality_errors_csv_path, relation_cardinality_errors, RELATION_CARDINALITY_ERROR_FIELDS)
    write_json(
        relation_cardinality_errors_json_path,
        {
            "run_id": resolved_run_id,
            **relation_cardinality_counts,
            "fieldnames": RELATION_CARDINALITY_ERROR_FIELDS,
            "rows": relation_cardinality_errors,
        },
    )
    stage_timings["write_relation_cardinality_errors_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    step2_anchor_surface_path = prefer_vector_input_path(Path(nodes_path)).parent / "t07_rcsdintersection_anchor_surface.gpkg"
    surface_write_mode = _write_step3_anchor_surface(
        output_path=surface_output_path,
        step2_surface_path=step2_anchor_surface_path,
    )
    stage_timings["write_anchor_surface_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    merged_relation_evidence_rows, anchor_counts = _write_merged_relation_evidence_json(
        csv_path=relation_evidence_csv_path,
        json_path=relation_evidence_json_path,
        run_id=resolved_run_id,
        step2_evidence_path=step2_relation_evidence_path,
        step3_rows=accepted_relation_evidence_rows,
    )
    stage_timings["write_relation_evidence_seconds"] = _elapsed_since(stage_started)
    stage_timings["write_outputs_seconds"] = _elapsed_since(write_outputs_started)

    summary = {
        "run_id": resolved_run_id,
        **counts,
        "input_paths": {
            "nodes": str(nodes_path),
            "intersection_match_all": str(intersection_match_all_path),
            "rcsdnode": str(rcsdnode_path),
        },
        "output_paths": {
            "nodes": str(nodes_output_path),
            "intersection_match_t07": str(relation_output_path),
            "t07_rcsdintersection_anchor_surface": str(surface_output_path),
            "RCSDNode_error": str(rcsdnode_error_path),
            "t07_swsd_rcsd_relation_evidence_csv": str(relation_evidence_csv_path),
            "t07_swsd_rcsd_relation_evidence": str(relation_evidence_json_path),
            "relation_cardinality_errors_csv": str(relation_cardinality_errors_csv_path),
            "relation_cardinality_errors": str(relation_cardinality_errors_json_path),
        },
        "output_strategy": {
            "nodes_write_mode": nodes_write_mode,
            "anchor_surface_write_mode": surface_write_mode,
            "relation_write_mode": "raw_crs84" if all(record.geometry_mode == "raw_crs84" for record in accepted_relations) else "transform_to_crs84",
        },
        "crs": {
            "process": TARGET_CRS.to_string(),
            "intersection_match_t07": RELATION_OUTPUT_CRS_NAME,
        },
        "relation_evidence_row_count": len(merged_relation_evidence_rows),
        **anchor_counts,
        **relation_cardinality_counts,
        "audit_count": len(audit_rows),
        "performance": {
            "elapsed_seconds": _elapsed_since(started_at),
            "stage_timings": stage_timings,
        },
    }

    stage_started = time.perf_counter()
    write_json(summary_path, summary)
    _write_csv(
        audit_csv_path,
        audit_rows,
        [
            "scope",
            "junction_id",
            "node_id",
            "status",
            "reason",
            "detail",
            "kind_2",
            "has_evd",
            "is_anchor",
            "target_id",
            "base_id",
            "relation_status",
            "rcsd_exists",
        ],
    )
    write_json(audit_json_path, {"run_id": resolved_run_id, "rows": audit_rows})
    stage_timings["write_audit_summary_seconds"] = _elapsed_since(stage_started)
    write_json(
        perf_path,
        {
            "run_id": resolved_run_id,
            "elapsed_sec": _elapsed_since(started_at),
            "stage_timings": stage_timings,
            "nodes_write_mode": nodes_write_mode,
            **counts,
            **relation_cardinality_counts,
        },
    )

    return T07Step3Artifacts(
        run_root=run_root,
        stage_root=stage_root,
        nodes_path=nodes_output_path,
        intersection_match_t07_path=relation_output_path,
        anchor_surface_path=surface_output_path,
        rcsdnode_error_path=rcsdnode_error_path,
        relation_evidence_csv_path=relation_evidence_csv_path,
        relation_evidence_json_path=relation_evidence_json_path,
        relation_cardinality_errors_csv_path=relation_cardinality_errors_csv_path,
        relation_cardinality_errors_json_path=relation_cardinality_errors_json_path,
        summary_path=summary_path,
        audit_csv_path=audit_csv_path,
        audit_json_path=audit_json_path,
        perf_json_path=perf_path,
    )
