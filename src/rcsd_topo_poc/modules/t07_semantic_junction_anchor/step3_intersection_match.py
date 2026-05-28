from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import TARGET_CRS, write_json
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_io import write_relation_geojson_crs84
from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_models import RELATION_OUTPUT_CRS_NAME

from .runner import (
    LoadedFeature,
    T07RunError,
    _audit_row,
    _build_node_index,
    _candidate_junction_ids,
    _elapsed_since,
    _normalize_id,
    _read_vector_layer,
    _resolve_group,
    _stage_root,
    _write_csv,
    _write_nodes,
)


STEP3_KIND2 = {"4", "8", "16", "2048"}


@dataclass(frozen=True)
class T07Step3Artifacts:
    run_root: Path
    stage_root: Path
    nodes_path: Path
    intersection_match_tool7_path: Path
    summary_path: Path
    audit_csv_path: Path
    audit_json_path: Path
    perf_json_path: Path


@dataclass(frozen=True)
class RelationRecord:
    feature_index: int
    target_id: str
    base_id: str | None
    status: str | None
    feature: LoadedFeature


def _is_zero_id(value: str | None) -> bool:
    if value is None:
        return False
    try:
        return float(value) == 0
    except ValueError:
        return value == "0"


def _is_success_relation(record: RelationRecord) -> bool:
    return _is_zero_id(record.status) and record.base_id is not None and not _is_zero_id(record.base_id)


def _build_relations_by_target(
    relation_features: list[LoadedFeature],
    audit_rows: list[dict[str, Any]],
) -> tuple[dict[str, list[RelationRecord]], int]:
    relations_by_target: dict[str, list[RelationRecord]] = {}
    invalid_relation_count = 0
    for feature in relation_features:
        props = feature.properties
        target_id = _normalize_id(props.get("target_id"))
        base_id = _normalize_id(props.get("base_id"))
        status = _normalize_id(props.get("status"))
        if target_id is None:
            invalid_relation_count += 1
            audit_rows.append(
                _audit_row(
                    scope="intersection_match_all",
                    status="skipped",
                    reason="missing_target_id",
                    detail=f"relation feature[{feature.feature_index}] has no target_id.",
                    base_id=base_id,
                    relation_status=status,
                )
            )
            continue
        relations_by_target.setdefault(target_id, []).append(
            RelationRecord(
                feature_index=feature.feature_index,
                target_id=target_id,
                base_id=base_id,
                status=status,
                feature=feature,
            )
        )
    duplicate_count = 0
    for target_id, records in relations_by_target.items():
        if len(records) <= 1:
            continue
        duplicate_count += 1
        audit_rows.append(
            _audit_row(
                scope="intersection_match_all",
                status="error",
                reason="duplicate_target_id_relation",
                detail=f"target_id={target_id} appears {len(records)} times in intersection_match_all.",
                junction_id=target_id,
                target_id=target_id,
            )
        )
    return relations_by_target, invalid_relation_count + duplicate_count


def _build_rcsd_semantic_id_set(rcsdnode_features: list[LoadedFeature]) -> set[str]:
    rcsd_ids: set[str] = set()
    for feature in rcsdnode_features:
        props = feature.properties
        node_id = _normalize_id(props.get("id"))
        if node_id is not None and not _is_zero_id(node_id):
            rcsd_ids.add(node_id)
        mainnodeid = _normalize_id(props.get("mainnodeid"))
        if mainnodeid is not None and not _is_zero_id(mainnodeid):
            rcsd_ids.add(mainnodeid)
    if not rcsd_ids:
        raise T07RunError("missing_required_field", "RCSDNode input has no usable id or mainnodeid values.")
    return rcsd_ids


def _relation_feature_payload(record: RelationRecord) -> dict[str, Any]:
    return {
        "properties": dict(record.feature.properties),
        "geometry": record.feature.geometry,
    }


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

    stage_started = time.perf_counter()
    nodes_layer_data = _read_vector_layer(
        nodes_path,
        layer_name=nodes_layer,
        crs_override=nodes_crs,
        allow_null_geometry=True,
    )
    relation_layer_data = _read_vector_layer(
        intersection_match_all_path,
        crs_override=intersection_match_all_crs,
        allow_null_geometry=True,
    )
    rcsdnode_layer_data = _read_vector_layer(
        rcsdnode_path,
        layer_name=rcsdnode_layer,
        crs_override=rcsdnode_crs,
        allow_null_geometry=True,
    )
    stage_timings["read_inputs_seconds"] = _elapsed_since(stage_started)

    stage_started = time.perf_counter()
    by_mainnodeid, singleton_by_id = _build_node_index(nodes_layer_data.features, audit_rows)
    junction_ids = _candidate_junction_ids(by_mainnodeid, singleton_by_id)
    relations_by_target, invalid_relation_count = _build_relations_by_target(relation_layer_data.features, audit_rows)
    rcsd_semantic_ids = _build_rcsd_semantic_id_set(rcsdnode_layer_data.features)
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
        "representative_missing_count": 0,
        "invalid_relation_count": invalid_relation_count,
    }
    accepted_relations: list[RelationRecord] = []

    stage_started = time.perf_counter()
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
        if kind_2 not in STEP3_KIND2:
            counts["skipped_kind2_count"] += 1
            continue
        counts["step3_scope_kind2_count"] += 1

        if has_evd != "yes" or is_anchor not in {None, "no"}:
            counts["not_candidate_count"] += 1
            audit_rows.append(
                _audit_row(
                    scope="semantic_junction",
                    status="skipped",
                    reason="not_step3_candidate",
                    detail="Step3 only processes has_evd=yes and is_anchor NULL/no representatives.",
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
            continue

        relation_record = relation_records[0]
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

        representative_props["is_anchor"] = "yes"
        representative_props["anchor_reason"] = None
        accepted_relations.append(relation_record)
        counts["accepted_count"] += 1
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

    nodes_output_path = stage_root / "nodes.gpkg"
    relation_output_path = stage_root / "intersection_match_tool7.geojson"
    summary_path = stage_root / "t07_step3_summary.json"
    audit_csv_path = stage_root / "t07_step3_audit.csv"
    audit_json_path = stage_root / "t07_step3_audit.json"
    perf_path = stage_root / "t07_step3_perf.json"

    stage_started = time.perf_counter()
    _write_nodes(nodes_output_path, nodes_layer_data.features)
    write_relation_geojson_crs84(
        relation_output_path,
        (_relation_feature_payload(record) for record in accepted_relations),
    )
    stage_timings["write_outputs_seconds"] = _elapsed_since(stage_started)

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
            "intersection_match_tool7": str(relation_output_path),
        },
        "crs": {
            "process": TARGET_CRS.to_string(),
            "intersection_match_tool7": RELATION_OUTPUT_CRS_NAME,
        },
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
            **counts,
        },
    )

    return T07Step3Artifacts(
        run_root=run_root,
        stage_root=stage_root,
        nodes_path=nodes_output_path,
        intersection_match_tool7_path=relation_output_path,
        summary_path=summary_path,
        audit_csv_path=audit_csv_path,
        audit_json_path=audit_json_path,
        perf_json_path=perf_path,
    )
