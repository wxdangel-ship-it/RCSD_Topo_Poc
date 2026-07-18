from __future__ import annotations

import argparse
import ast
import csv
import json
import os
import subprocess
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import (
    T10_MODULE_ID,
    T10_T08_POLICY,
    T10_V1_CHAIN,
    T10_V1_CHAIN_WITH_T12,
)
from .segment_noop_handoffs import try_segment_no_candidate_handoff as _seg_noop
from .upstream_feedback import write_t10_upstream_feedback
from .case_runner_t11 import run_t11_stage as _run_t11
from .case_runner_t12 import run_t12_stage as _run_t12


T10_E2E_STAGE_ORDER = (
    "t01",
    "t07",
    "t03",
    "t04",
    "t05",
    "t06_step12",
    "t06_step3",
    "t11",
    "t09_step12",
    "t09_step3",
)

T10_E2E_STAGE_ORDER_WITH_T12 = (
    "t01",
    "t07",
    "t03",
    "t04",
    "t05",
    "t06_step12",
    "t06_step3",
    "t11",
    "t12",
    "t09_step12",
    "t09_step3",
)

T10_E2E_STAGE_MODULES = {
    "t01": "t01_data_preprocess",
    "t07": "t07_semantic_junction_anchor",
    "t03": "t03_virtual_junction_anchor",
    "t04": "t04_divmerge_virtual_polygon",
    "t05": "t05_junction_surface_fusion",
    "t07_step3": "t07_semantic_junction_anchor",
    "t06_step12": "t06_segment_fusion_precheck",
    "t06_step3": "t06_segment_fusion_precheck",
    "t12": "t12_frcsd_quality_audit",
    "t11": "t11_manual_relation_review",
    "t09_step12": "t09_swsd_field_rule_restoration",
    "t09_step3": "t09_swsd_field_rule_restoration",
}

T10_T06_VISUAL_CHECK_SCHEMA_VERSION = "2026-06-20.t06_visual_check.v1"

T10_T06_VISUAL_CHECK_FIELDNAMES = (
    "case_id",
    "status",
    "case_run_dir",
    "t06_run_root",
    "t01_segment_gpkg",
    "t01_roads_gpkg",
    "t07_nodes_gpkg",
    "t07_surface_gpkg",
    "t03_surface_gpkg",
    "t04_surface_gpkg",
    "t04_audit_gpkg",
    "t05_junction_surface_gpkg",
    "t06_rcsd_segment_replaceable_gpkg",
    "t06_segment_replacement_plan_gpkg",
    "t06_segment_replacement_problem_registry_gpkg",
    "t06_frcsd_road_gpkg",
    "t06_frcsd_node_gpkg",
    "t06_segment_relation_gpkg",
    "t06_topology_connectivity_audit_gpkg",
    "t06_surface_topology_audit_gpkg",
    "step2_replaceable_count",
    "step2_replacement_plan_count",
    "step2_replacement_plan_ready_count",
    "step2_problem_registry_count",
    "step2_rejected_count",
    "step3_replacement_unit_success_count",
    "step3_replacement_unit_failure_count",
    "step3_removed_swsd_road_count",
    "step3_added_rcsd_road_count",
    "step3_frcsd_road_count",
    "step3_frcsd_node_count",
    "crs_status",
    "crs_values",
    "missing_visual_layer_count",
    "missing_visual_layers",
    "advance_right_count",
    "advance_right_rcsd_count",
    "advance_right_swsd_count",
    "swsd_advance_duplicate_ge20pct_count",
    "advance_endpoint_missing_road_count",
    "all_endpoint_missing_road_count",
    "spatial_check_status",
    "spatial_check_error",
)

T10_T06_VISUAL_LAYER_ROLES = {
    "t01_segment_gpkg": "SWSD Segment source layer for baseline overlay.",
    "t01_roads_gpkg": "SWSD Road source layer before T06 replacement.",
    "t07_nodes_gpkg": "T07 Step2 SWSD nodes layer; final T06 handoff is T04 nodes.",
    "t07_surface_gpkg": "T07 semantic junction surface for F-RCSD anchor review.",
    "t03_surface_gpkg": "T03 virtual intersection surface for visual overlay.",
    "t04_surface_gpkg": "T04 divmerge virtual surface for grade-separated anchor review.",
    "t04_audit_gpkg": "T04 surface audit; rejected rows block non-1:1 closure.",
    "t05_junction_surface_gpkg": "T05 fused junction surface consumed by T06 surface topology closure.",
    "t06_rcsd_segment_replaceable_gpkg": "T06 Step2 replaceable RCSD segment evidence.",
    "t06_segment_replacement_plan_gpkg": "T06 Step2 formal replacement plan.",
    "t06_segment_replacement_problem_registry_gpkg": "T06 Step2 retained or blocked Segment reasons.",
    "t06_frcsd_road_gpkg": "T06 Step3 final F-RCSD Road layer for visual overlay.",
    "t06_frcsd_node_gpkg": "T06 Step3 final F-RCSD Node layer for endpoint attachment checks.",
    "t06_segment_relation_gpkg": "T06 Step3 SWSD Segment to F-RCSD relation evidence.",
    "t06_topology_connectivity_audit_gpkg": "T06 Step3 final topology connectivity hard-gate audit.",
    "t06_surface_topology_audit_gpkg": "T06 Step3 surface-assisted junction closure audit.",
}


@dataclass(frozen=True)
class T10E2ECaseRunArtifacts:
    run_root: Path
    manifest_json: Path
    summary_json: Path
    case_manifest_paths: tuple[Path, ...]
    t06_funnel_paths: tuple[Path, ...]
    upstream_feedback_summary_json: Path
    upstream_feedback_segments_csv: Path
    upstream_feedback_relation_summary_json: Path
    upstream_feedback_relations_csv: Path
    upstream_side_group_candidates_csv: Path
    upstream_side_group_endpoint_candidates_csv: Path
    upstream_pair_anchor_endpoint_clusters_csv: Path
    t06_visual_check_summary_json: Path
    t06_visual_check_summary_csv: Path


from .case_runner_pipeline import (
    run_t10_e2e_cases_from_package,
    _run_t10_e2e_feedback_iterations_from_package,
    main,
    _run_one_case,
    _run_stage,
    _run_t01,
    _run_t07,
    _run_t03,
    _run_t04,
    _run_t05,
    _run_t07_step3,
    _run_t06_step12,
    _run_t06_step3,
    _run_t09_step12,
    _run_t09_step3,
)


def _execute_command(
    stage_id: str,
    stage_dir: Path,
    repo_root: Path,
    command: list[str],
    env_overrides: Mapping[str, str],
    inputs: Mapping[str, Path | None],
) -> dict[str, Any]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    log_path = stage_dir / "stdout.log"
    env = _command_env(repo_root, env_overrides)
    started = time.perf_counter()
    started_at = _now_text()
    with log_path.open("w", encoding="utf-8") as fp:
        fp.write("[T10] command=" + " ".join(command) + "\n")
        fp.flush()
        proc = subprocess.run(command, cwd=repo_root, env=env, stdout=fp, stderr=subprocess.STDOUT, text=True)
    ended_at = _now_text()
    duration = round(time.perf_counter() - started, 6)
    status = "passed" if proc.returncode == 0 else "failed"
    return {
        "stage_id": stage_id,
        "stage": stage_id,
        "module_id": T10_E2E_STAGE_MODULES[stage_id],
        "status": status,
        "return_code": proc.returncode,
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "duration_seconds": duration,
        "cwd": str(repo_root),
        "command": command,
        "env_overrides": dict(env_overrides),
        "inputs": _paths_payload(inputs),
        "stdout_log": str(log_path),
        "stdout_tail": _tail(log_path),
    }


def _write_t06_funnel(
    *,
    case_run_dir: Path,
    case_id: str,
    handoffs: Mapping[str, str],
    stage_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    t06_run_root = _path_from(handoffs.get("t06_run_root"))
    summary = build_t10_t06_funnel_summary(
        case_id=case_id,
        t06_run_root=t06_run_root,
        stage_records=stage_records,
        handoffs=handoffs,
    )
    json_path = case_run_dir / "t10_t06_funnel.json"
    csv_path = case_run_dir / "t10_t06_funnel.csv"
    md_path = case_run_dir / "t10_t06_funnel.md"
    _write_json(json_path, summary)
    _write_funnel_csv(csv_path, summary)
    _write_funnel_md(md_path, summary)
    return {"json_path": json_path, "csv_path": csv_path, "md_path": md_path, "summary": summary}


def _write_t06_visual_check_summary(
    *,
    run_root: Path,
    case_results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [_build_t06_visual_check_row(case_result) for case_result in case_results]
    json_path = run_root / "t10_t06_visual_check_summary.json"
    csv_path = run_root / "t10_t06_visual_check_summary.csv"
    payload = {
        "schema_version": T10_T06_VISUAL_CHECK_SCHEMA_VERSION,
        "generated_at_utc": _now_text(),
        "run_root": str(run_root),
        "case_count": len(rows),
        "fieldnames": list(T10_T06_VISUAL_CHECK_FIELDNAMES),
        "visual_layer_roles": T10_T06_VISUAL_LAYER_ROLES,
        "qa": {
            "crs_and_transform": "Each listed visual layer is read with explicit CRS metadata; spatial metrics are evaluated in EPSG:3857.",
            "topology_silent_fix": False,
            "geometry_semantics": "The summary indexes visual overlay layers and reports endpoint or duplicate evidence; it does not modify geometry.",
            "audit_traceability": "Every row records the case run directory and the exact T01/T06 GPKG paths used for inspection.",
            "performance_verifiability": "The summary records per-case counts and spatial check status; T10 run summary keeps total duration.",
        },
        "rows": rows,
    }
    _write_json(json_path, payload)
    _write_visual_check_csv(csv_path, rows)
    return {
        "schema_version": T10_T06_VISUAL_CHECK_SCHEMA_VERSION,
        "json_path": json_path,
        "csv_path": csv_path,
        "rows": rows,
    }


def _build_t06_visual_check_row(case_result: Mapping[str, Any]) -> dict[str, Any]:
    case_id = str(case_result.get("case_id") or "")
    case_run_dir = _case_run_dir_from_result(case_result)
    t06_run_root = case_run_dir / "t06_step12" / "t06" if case_run_dir else None
    step2_root = t06_run_root / "step2_extract_rcsd_segments" if t06_run_root else None
    step3_root = t06_run_root / "step3_segment_replacement" if t06_run_root else None
    step2 = _read_json_if_file(step2_root / "t06_step2_summary.json" if step2_root else None)
    step3 = _read_json_if_file(step3_root / "t06_step3_summary.json" if step3_root else None)
    visual_paths = _t06_visual_paths(case_run_dir=case_run_dir, t06_run_root=t06_run_root)
    missing_layers = [key for key, path in visual_paths.items() if not path.is_file()]
    row: dict[str, Any] = {
        "case_id": case_id,
        "status": str(case_result.get("overall_status") or case_result.get("status") or ""),
        "case_run_dir": str(case_run_dir) if case_run_dir else "",
        "t06_run_root": str(t06_run_root) if t06_run_root and t06_run_root.exists() else "",
        "step2_replaceable_count": step2.get("replaceable_count", ""),
        "step2_replacement_plan_count": step2.get("replacement_plan_count", ""),
        "step2_replacement_plan_ready_count": step2.get("replacement_plan_ready_count", ""),
        "step2_problem_registry_count": step2.get("problem_registry_count", ""),
        "step2_rejected_count": step2.get("rejected_count", ""),
        "step3_replacement_unit_success_count": step3.get("replacement_unit_success_count", ""),
        "step3_replacement_unit_failure_count": step3.get("replacement_unit_failure_count", ""),
        "step3_removed_swsd_road_count": step3.get("removed_swsd_road_count", ""),
        "step3_added_rcsd_road_count": step3.get("added_rcsd_road_count", ""),
        "step3_frcsd_road_count": step3.get("frcsd_road_count", ""),
        "step3_frcsd_node_count": step3.get("frcsd_node_count", ""),
        "crs_status": "not_run",
        "crs_values": "",
        "missing_visual_layer_count": len(missing_layers),
        "missing_visual_layers": "|".join(missing_layers),
        "advance_right_count": "",
        "advance_right_rcsd_count": "",
        "advance_right_swsd_count": "",
        "swsd_advance_duplicate_ge20pct_count": "",
        "advance_endpoint_missing_road_count": "",
        "all_endpoint_missing_road_count": "",
        "spatial_check_status": "not_run",
        "spatial_check_error": "",
    }
    for key, path in visual_paths.items():
        row[key] = str(path) if path.is_file() else ""
    row.update(_t06_visual_spatial_metrics(visual_paths))
    return row


def _case_run_dir_from_result(case_result: Mapping[str, Any]) -> Path | None:
    raw_dir = str(case_result.get("case_run_dir") or "").strip()
    if raw_dir:
        return Path(raw_dir).expanduser().resolve()
    raw_summary = str(case_result.get("case_run_summary_path") or "").strip()
    if raw_summary:
        return Path(raw_summary).expanduser().resolve().parent
    return None


def _t06_visual_paths(*, case_run_dir: Path | None, t06_run_root: Path | None) -> dict[str, Path]:
    empty = Path("")
    if case_run_dir is None or t06_run_root is None:
        return {key: empty for key in T10_T06_VISUAL_LAYER_ROLES}
    step2_root = t06_run_root / "step2_extract_rcsd_segments"
    step3_root = t06_run_root / "step3_segment_replacement"
    return {
        "t01_segment_gpkg": case_run_dir / "t01" / "segment.gpkg",
        "t01_roads_gpkg": case_run_dir / "t01" / "roads.gpkg",
        "t07_nodes_gpkg": case_run_dir / "t07" / "t07" / "step2_anchor_recognition" / "nodes.gpkg",
        "t07_surface_gpkg": case_run_dir
        / "t07"
        / "t07"
        / "step2_anchor_recognition"
        / "t07_rcsdintersection_anchor_surface.gpkg",
        "t03_surface_gpkg": case_run_dir / "t03" / "t03" / "virtual_intersection_polygons.gpkg",
        "t04_surface_gpkg": case_run_dir / "t04" / "t04" / "divmerge_virtual_anchor_surface.gpkg",
        "t04_audit_gpkg": case_run_dir / "t04" / "t04" / "divmerge_virtual_anchor_surface_audit.gpkg",
        "t05_junction_surface_gpkg": case_run_dir / "t05" / "t05_phase1" / "junction_anchor_surface.gpkg",
        "t06_rcsd_segment_replaceable_gpkg": step2_root / "t06_rcsd_segment_replaceable.gpkg",
        "t06_segment_replacement_plan_gpkg": step2_root / "t06_segment_replacement_plan.gpkg",
        "t06_segment_replacement_problem_registry_gpkg": step2_root
        / "t06_segment_replacement_problem_registry.gpkg",
        "t06_frcsd_road_gpkg": step3_root / "t06_frcsd_road.gpkg",
        "t06_frcsd_node_gpkg": step3_root / "t06_frcsd_node.gpkg",
        "t06_segment_relation_gpkg": step3_root / "t06_step3_swsd_frcsd_segment_relation.gpkg",
        "t06_topology_connectivity_audit_gpkg": step3_root / "t06_step3_topology_connectivity_audit.gpkg",
        "t06_surface_topology_audit_gpkg": step3_root / "t06_step3_surface_topology_audit.gpkg",
    }


def _t06_visual_spatial_metrics(visual_paths: Mapping[str, Path]) -> dict[str, Any]:
    existing_paths = {key: path for key, path in visual_paths.items() if path.is_file()}
    if not existing_paths:
        return {}
    try:
        from rcsd_topo_poc.modules.t06_segment_fusion_precheck.road_attributes import (
            is_advance_right_turn_road,
            is_near_advance_right_turn_duplicate,
        )
        from rcsd_topo_poc.modules.t08_preprocess.vector_io import read_vector
    except Exception as exc:  # noqa: BLE001 - summary must remain best-effort.
        return {"spatial_check_status": "error", "spatial_check_error": f"import_error:{type(exc).__name__}:{exc}"}

    crs_values: dict[str, str] = {}
    spatial_status = "passed"
    spatial_error = ""
    try:
        for key, path in existing_paths.items():
            crs_values[key] = _vector_source_crs_text(path)
        road_path = existing_paths.get("t06_frcsd_road_gpkg")
        node_path = existing_paths.get("t06_frcsd_node_gpkg")
        if road_path is None or node_path is None:
            spatial_status = "missing_required_layers"
            return {
                "crs_status": _crs_status(crs_values),
                "crs_values": json.dumps(crs_values, ensure_ascii=False, sort_keys=True),
                "spatial_check_status": spatial_status,
                "spatial_check_error": spatial_error,
            }
        roads = read_vector(road_path, target_epsg=3857).features
        nodes = read_vector(node_path, target_epsg=3857).features
        node_ids = {_id_text(feature.properties.get("id")) for feature in nodes}
        advance_features = [
            feature for feature in roads if is_advance_right_turn_road(dict(feature.properties))
        ]
        rcsd_advance_geometries = [
            feature.geometry
            for feature in advance_features
            if _source_text(feature.properties.get("source")) == "1"
        ]
        swsd_advance_features = [
            feature
            for feature in advance_features
            if _source_text(feature.properties.get("source")) == "2"
        ]
        duplicate_count = sum(
            1
            for feature in swsd_advance_features
            if is_near_advance_right_turn_duplicate(
                dict(feature.properties),
                feature.geometry,
                rcsd_advance_geometries,
                min_covered_ratio=0.2,
            )
        )
        advance_missing = sum(1 for feature in advance_features if _road_endpoint_missing(feature.properties, node_ids))
        all_missing = sum(1 for feature in roads if _road_endpoint_missing(feature.properties, node_ids))
        return {
            "crs_status": _crs_status(crs_values),
            "crs_values": json.dumps(crs_values, ensure_ascii=False, sort_keys=True),
            "advance_right_count": len(advance_features),
            "advance_right_rcsd_count": len(rcsd_advance_geometries),
            "advance_right_swsd_count": len(swsd_advance_features),
            "swsd_advance_duplicate_ge20pct_count": duplicate_count,
            "advance_endpoint_missing_road_count": advance_missing,
            "all_endpoint_missing_road_count": all_missing,
            "spatial_check_status": spatial_status,
            "spatial_check_error": spatial_error,
        }
    except Exception as exc:  # noqa: BLE001 - visual summary must not hide runner outputs.
        return {
            "crs_status": _crs_status(crs_values),
            "crs_values": json.dumps(crs_values, ensure_ascii=False, sort_keys=True),
            "spatial_check_status": "error",
            "spatial_check_error": f"{type(exc).__name__}:{exc}",
        }


def build_t10_t06_funnel_summary(
    *,
    case_id: str,
    t06_run_root: Path | None,
    stage_records: Sequence[Mapping[str, Any]],
    handoffs: Mapping[str, str],
) -> dict[str, Any]:
    step1_summary_path = t06_run_root / "step1_identify_fusion_units" / "t06_step1_summary.json" if t06_run_root else None
    step2_summary_path = t06_run_root / "step2_extract_rcsd_segments" / "t06_step2_summary.json" if t06_run_root else None
    step3_summary_path = t06_run_root / "step3_segment_replacement" / "t06_step3_summary.json" if t06_run_root else None
    step1 = _read_json_if_file(step1_summary_path)
    step2 = _read_json_if_file(step2_summary_path)
    step3 = _read_json_if_file(step3_summary_path)
    rows = [
        _metric("T06 Step1", "input_segment_count", step1.get("input_segment_count")),
        _metric("T06 Step1", "evd_candidate_count", step1.get("evd_candidate_count")),
        _metric("T06 Step1", "swsd_candidate_count", step1.get("swsd_candidate_count")),
        _metric("T06 Step1", "final_fusion_unit_count", step1.get("final_fusion_unit_count")),
        _metric("T06 Step1", "swsd_final_fusion_unit_count", step1.get("swsd_final_fusion_unit_count")),
        _metric("T06 Step2", "input_fusion_unit_count", step2.get("input_fusion_unit_count")),
        _metric("T06 Step2", "rcsd_candidate_count", step2.get("rcsd_candidate_count")),
        _metric("T06 Step2", "replaceable_count", step2.get("replaceable_count")),
        _metric("T06 Step2", "replacement_plan_count", step2.get("replacement_plan_count")),
        _metric("T06 Step2", "replacement_plan_ready_count", step2.get("replacement_plan_ready_count")),
        _metric("T06 Step2", "problem_registry_count", step2.get("problem_registry_count")),
        _metric("T06 Step2", "rejected_count", step2.get("rejected_count")),
        _metric("T06 Step2", "buffer_segment_count", step2.get("buffer_segment_count")),
        _metric("T06 Step2", "buffer_rejected_count", step2.get("buffer_rejected_count")),
        _metric("T06 Step3", "input_replaceable_count", step3.get("input_replaceable_count")),
        _metric("T06 Step3", "input_replacement_plan_count", step3.get("input_replacement_plan_count")),
        _metric("T06 Step3", "input_standard_replacement_plan_count", step3.get("input_standard_replacement_plan_count")),
        _metric("T06 Step3", "replacement_unit_success_count", step3.get("replacement_unit_success_count")),
        _metric("T06 Step3", "replacement_unit_failure_count", step3.get("replacement_unit_failure_count")),
        _metric("T06 Step3", "removed_swsd_road_count", step3.get("removed_swsd_road_count")),
        _metric("T06 Step3", "removed_swsd_node_count", step3.get("removed_swsd_node_count")),
        _metric("T06 Step3", "added_rcsd_road_count", step3.get("added_rcsd_road_count")),
        _metric("T06 Step3", "added_rcsd_node_count", step3.get("added_rcsd_node_count")),
        _metric("T06 Step3", "frcsd_road_count", step3.get("frcsd_road_count")),
        _metric("T06 Step3", "frcsd_node_count", step3.get("frcsd_node_count")),
        _metric("T06 Step3", "segment_relation_count", step3.get("segment_relation_count")),
    ]
    return {
        "case_id": case_id,
        "status": _t06_status(stage_records, step1, step2, step3),
        "t06_run_root": str(t06_run_root) if t06_run_root else "",
        "summary_paths": {
            "step1": str(step1_summary_path) if step1_summary_path else "",
            "step2": str(step2_summary_path) if step2_summary_path else "",
            "step3": str(step3_summary_path) if step3_summary_path else "",
        },
        "metrics": rows,
        "reject_reason_counts": {
            "step1": step1.get("reject_reason_counts", {}),
            "step2": step2.get("reject_reason_counts", {}),
            "step2_buffer": step2.get("buffer_reject_reason_counts", {}),
        },
        "replacement_quality": {
            "replacement_plan_source": step3.get("replacement_plan_source"),
            "replacement_plan_scope_counts": step2.get("replacement_plan_scope_counts", {}),
            "problem_registry_status_counts": step2.get("problem_registry_status_counts", {}),
            "road_id_collision_count": step3.get("road_id_collision_count"),
            "node_id_collision_count": step3.get("node_id_collision_count"),
            "junction_c_count": step3.get("junction_c_count"),
            "segment_relation_replaced_count": step3.get("segment_relation_replaced_count"),
            "segment_relation_retained_swsd_count": step3.get("segment_relation_retained_swsd_count"),
            "segment_relation_failed_count": step3.get("segment_relation_failed_count"),
        },
        "handoffs": {
            key: handoffs.get(key, "")
            for key in (
                "t01_segment",
                "t01_roads",
                "t07_nodes",
                "t03_nodes",
                "t04_nodes",
                "final_swsd_nodes",
                "t05_intersection_match_all",
                "t05_rcsdroad_out",
                "t05_rcsdnode_out",
                "t06_frcsd_road",
                "t06_frcsd_node",
                "t06_swsd_frcsd_segment_relation",
            )
        },
    }


def _discover_case_dirs(*, package_root: Path, case_ids: Sequence[str] | None) -> list[Path]:
    wanted = {_safe_case_id(str(case_id)) for case_id in (case_ids or []) if str(case_id).strip()}
    candidates_root = package_root / "cases"
    if candidates_root.is_dir():
        case_dirs = _manifest_case_dirs(candidates_root)
    elif (package_root / "t10_case_evidence_manifest.json").is_file():
        case_dirs = [package_root]
    else:
        case_dirs = _manifest_case_dirs(package_root)
    if wanted:
        case_dirs = [path for path in case_dirs if _safe_case_id(path.name) in wanted]
    return case_dirs


def _manifest_case_dirs(root: Path) -> list[Path]:
    return [path for path in sorted(root.iterdir()) if path.is_dir() and (path / "t10_case_evidence_manifest.json").is_file()]


def _external_input_paths(*, case_manifest: Mapping[str, Any], case_dir: Path) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for entry in case_manifest.get("included_external_inputs") or []:
        if not isinstance(entry, Mapping):
            continue
        slot = str(entry.get("slot") or "").strip()
        if not slot:
            continue
        package_path = str(entry.get("package_path") or "").strip()
        source_path = str(entry.get("source_path") or "").strip()
        if package_path:
            paths[slot] = (case_dir / package_path).resolve()
        elif source_path:
            paths[slot] = Path(source_path).expanduser().resolve()
    return paths


def _t10_stage_order(run_t12: bool) -> tuple[str, ...]:
    return T10_E2E_STAGE_ORDER_WITH_T12 if run_t12 else T10_E2E_STAGE_ORDER


def _stage_limit(
    stop_after: str | None,
    stage_order: Sequence[str] | None = None,
) -> int:
    active_order = tuple(stage_order or T10_E2E_STAGE_ORDER)
    if not stop_after:
        return len(active_order)
    normalized = str(stop_after).strip()
    if normalized not in active_order:
        raise ValueError(f"stop_after must be one of {', '.join(active_order)}.")
    return active_order.index(normalized) + 1


def _compare_feedback_iteration_outputs(
    *,
    baseline_run_root: Path,
    final_run_root: Path,
) -> dict[str, Any]:
    baseline_replaced = _replaced_segment_ids(baseline_run_root)
    final_replaced = _replaced_segment_ids(final_run_root)
    baseline_plan = _replacement_plan_segment_ids(baseline_run_root)
    final_plan = _replacement_plan_segment_ids(final_run_root)
    return {
        "baseline_run_root": str(baseline_run_root),
        "final_run_root": str(final_run_root),
        "baseline_replaced_segment_count": len(baseline_replaced),
        "final_replaced_segment_count": len(final_replaced),
        "added_replaced_segment_ids": sorted(final_replaced - baseline_replaced),
        "removed_replaced_segment_ids": sorted(baseline_replaced - final_replaced),
        "baseline_replacement_plan_segment_count": len(baseline_plan),
        "final_replacement_plan_segment_count": len(final_plan),
        "added_replacement_plan_segment_ids": sorted(final_plan - baseline_plan),
        "removed_replacement_plan_segment_ids": sorted(baseline_plan - final_plan),
    }


def _same_side_group_endpoint_candidates(left: Path, right: Path) -> bool:
    _left_rows, left_keys, _left_fields = _candidate_rows_with_keys(left)
    _right_rows, right_keys, _right_fields = _candidate_rows_with_keys(right)
    return left_keys == right_keys


def _next_cumulative_feedback_file(*, current: Path | None, new: Path, out_path: Path) -> tuple[Path | None, bool]:
    if current is None:
        return new, True
    return _write_merged_side_group_endpoint_candidates(current, new, out_path)


def _write_auto_consumable_pair_anchor_clusters(source: Path, out_path: Path) -> tuple[Path | None, int]:
    rows = _read_csv_rows(source)
    fieldnames = _csv_fieldnames(source)
    auto_rows = [
        row
        for row in rows
        if str(row.get("auto_consumable_by_t05") or "").strip().lower() in {"1", "true", "yes", "y"}
    ]
    if not auto_rows:
        return None, 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for row in auto_rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return out_path, len(auto_rows)


def _write_merged_side_group_endpoint_candidates(existing: Path, new: Path, out_path: Path) -> tuple[Path, bool]:
    existing_rows, existing_keys, existing_fields = _candidate_rows_with_keys(existing)
    new_rows, new_keys, new_fields = _candidate_rows_with_keys(new)
    merged_by_key = dict(existing_rows)
    for key, row in new_rows.items():
        merged_by_key.setdefault(key, row)
    merged_keys = set(merged_by_key)
    if merged_keys == existing_keys:
        return existing, False
    fieldnames = _merged_fieldnames(existing_fields, new_fields)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(merged_by_key):
            row = merged_by_key[key]
            writer.writerow({field: row.get(field, "") for field in fieldnames})
    return out_path, True


def _candidate_rows_for_convergence(path: Path) -> list[dict[str, str]]:
    rows, _keys, _fields = _candidate_rows_with_keys(path)
    return [rows[key] for key in sorted(rows)]


def _candidate_rows_with_keys(path: Path) -> tuple[dict[str, dict[str, str]], set[str], list[str]]:
    if not path.is_file():
        return {}, set(), []
    rows: dict[str, dict[str, str]] = {}
    fieldnames: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        fieldnames = [field for field in (reader.fieldnames or []) if field]
        for raw in reader:
            row = {str(key): str(value or "") for key, value in raw.items() if key}
            key = _candidate_business_key(row)
            rows.setdefault(key, row)
    return rows, set(rows), fieldnames


def _csv_fieldnames(path: Path) -> list[str]:
    with path.open(newline="", encoding="utf-8-sig") as fp:
        reader = csv.DictReader(fp)
        return [field for field in (reader.fieldnames or []) if field]


def _candidate_business_key(row: Mapping[str, Any]) -> str:
    comparable = {
        str(key): str(value or "")
        for key, value in row.items()
        if key and key != "problem_registry_path"
    }
    return json.dumps(comparable, ensure_ascii=False, sort_keys=True)


def _merged_fieldnames(left: Sequence[str], right: Sequence[str]) -> list[str]:
    fields: list[str] = []
    for field in [*left, *right]:
        if field and field not in fields:
            fields.append(field)
    return fields


def _replaced_segment_ids(run_root: Path) -> set[str]:
    result: set[str] = set()
    for path in run_root.glob("cases/*/t06_step12/t06/step3_segment_replacement/t06_step3_swsd_frcsd_segment_relation.csv"):
        for row in _read_csv_rows(path):
            status = str(row.get("relation_status") or "").strip().lower()
            if "replaced" not in status:
                continue
            segment_id = str(row.get("swsd_segment_id") or "").strip()
            if segment_id:
                result.add(segment_id)
    return result


def _replacement_plan_segment_ids(run_root: Path) -> set[str]:
    result: set[str] = set()
    for path in run_root.glob("cases/*/t06_step12/t06/step2_extract_rcsd_segments/t06_segment_replacement_plan.csv"):
        for row in _read_csv_rows(path):
            for segment_id in _replacement_plan_row_segment_ids(row):
                result.add(segment_id)
    return result


def _replacement_plan_row_segment_ids(row: Mapping[str, Any]) -> list[str]:
    result: list[str] = []
    segment_id = str(row.get("swsd_segment_id") or "").strip()
    if segment_id:
        result.append(segment_id)
    for group_segment_id in _serialized_id_list(row.get("group_segment_ids")):
        if group_segment_id and group_segment_id not in result:
            result.append(group_segment_id)
    return result


def _serialized_id_list(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = ast.literal_eval(text)
    except (ValueError, SyntaxError):
        parsed = None
    if isinstance(parsed, (list, tuple, set)):
        return [item for item in (str(item).strip() for item in parsed) if item]
    if text.lower() in {"none", "null", "nan", "[]"}:
        return []
    cleaned = text.strip("[](){}")
    return [item for item in (part.strip().strip("'\"") for part in cleaned.replace("|", ",").split(",")) if item]


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as fp:
        return list(csv.DictReader(fp))


def _blocked_record(
    stage_id: str,
    stage_dir: Path,
    message: str,
    *,
    inputs: Mapping[str, Path | None] | None = None,
    missing: Sequence[str] | None = None,
) -> dict[str, Any]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    return {
        "stage_id": stage_id,
        "stage": stage_id,
        "module_id": T10_E2E_STAGE_MODULES[stage_id],
        "status": "blocked",
        "message": message,
        "blocked_reason": message,
        "missing_inputs": list(missing or []),
        "inputs": _paths_payload(inputs or {}),
        "started_at_utc": _now_text(),
        "ended_at_utc": _now_text(),
        "duration_seconds": 0.0,
        "outputs": {},
    }


def _exception_record(stage_id: str, stage_dir: Path, exc: BaseException) -> dict[str, Any]:
    stage_dir.mkdir(parents=True, exist_ok=True)
    failure_path = stage_dir / "exception.txt"
    failure_path.write_text(traceback.format_exc(), encoding="utf-8")
    return {
        "stage_id": stage_id,
        "stage": stage_id,
        "module_id": T10_E2E_STAGE_MODULES[stage_id],
        "status": "failed",
        "message": f"{type(exc).__name__}: {exc}",
        "failure_reason": f"{type(exc).__name__}: {exc}",
        "exception_log": str(failure_path),
        "started_at_utc": _now_text(),
        "ended_at_utc": _now_text(),
        "duration_seconds": 0.0,
        "outputs": {},
    }


def _overall_case_status(stage_records: Sequence[Mapping[str, Any]], stage_limit: int) -> str:
    statuses = [str(record.get("status")) for record in stage_records]
    if len(statuses) < stage_limit:
        return "skipped"
    if any(status == "failed" for status in statuses):
        return "failed"
    if any(status == "blocked" for status in statuses):
        return "blocked"
    return "passed" if all(status == "passed" for status in statuses) else "skipped"


def _overall_run_status(case_results: Sequence[Mapping[str, Any]]) -> str:
    statuses = [str(item.get("overall_status") or "") for item in case_results]
    if not statuses:
        return "skipped"
    if any(status == "failed" for status in statuses):
        return "failed"
    if any(status == "blocked" for status in statuses):
        return "blocked"
    if all(status == "passed" for status in statuses):
        return "passed"
    return "skipped"


def _runner_qa(case_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "crs_and_transform": "T10 does not transform data in the runner; CRS audit comes from package slicing and module summaries.",
        "topology_silent_fix": False,
        "geometry_semantics": "Case identity remains SWSD semantic junction id throughout the run.",
        "audit_traceability": "Root manifest links every case manifest and every stage stdout log.",
        "performance_verifiability": "Stage duration is captured per case; T06 funnel captures module-level counts.",
        "case_status_counts": {
            "passed": sum(1 for item in case_results if item.get("overall_status") == "passed"),
            "failed": sum(1 for item in case_results if item.get("overall_status") == "failed"),
            "blocked": sum(1 for item in case_results if item.get("overall_status") == "blocked"),
            "skipped": sum(1 for item in case_results if item.get("overall_status") == "skipped"),
        },
    }


def _t06_status(
    stage_records: Sequence[Mapping[str, Any]],
    step1: Mapping[str, Any],
    step2: Mapping[str, Any],
    step3: Mapping[str, Any],
) -> str:
    statuses = {str(record.get("stage_id")): str(record.get("status")) for record in stage_records}
    if statuses.get("t06_step12") == "failed" or statuses.get("t06_step3") == "failed":
        return "failed"
    if statuses.get("t06_step12") == "blocked" or statuses.get("t06_step3") == "blocked":
        return "blocked"
    if step1 and step2 and step3:
        return "completed"
    if step1 or step2:
        return "partial"
    return "not_started"


def _missing_files(inputs: Mapping[str, Path | None]) -> list[str]:
    return [key for key, value in inputs.items() if value is None or not Path(value).is_file()]


def _attach_outputs(record: dict[str, Any], produced: Mapping[str, str]) -> None:
    record["outputs"] = dict(produced)
    missing_outputs = [key for key, value in produced.items() if not value or not Path(value).exists()]
    record["missing_outputs"] = missing_outputs


def _metric(stage: str, metric: str, value: Any) -> dict[str, Any]:
    return {"stage": stage, "metric": metric, "value": value}


def _write_funnel_csv(path: Path, summary: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=("case_id", "stage", "metric", "value"))
        writer.writeheader()
        for row in summary.get("metrics") or []:
            writer.writerow(
                {
                    "case_id": summary.get("case_id"),
                    "stage": row.get("stage"),
                    "metric": row.get("metric"),
                    "value": "" if row.get("value") is None else row.get("value"),
                }
            )


def _write_visual_check_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=T10_T06_VISUAL_CHECK_FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: _csv_value(row.get(field, ""))
                    for field in T10_T06_VISUAL_CHECK_FIELDNAMES
                }
            )


def _csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _vector_source_crs_text(path: Path) -> str:
    import fiona
    from pyproj import CRS

    with fiona.open(str(path)) as source:
        crs_wkt = getattr(source, "crs_wkt", None)
        crs_mapping = getattr(source, "crs", None)
        if crs_wkt:
            return _crs_text(CRS.from_wkt(crs_wkt))
        if crs_mapping:
            return _crs_text(CRS.from_user_input(crs_mapping))
    return "NONSPATIAL"


def _crs_text(value: Any) -> str:
    try:
        authority = value.to_authority()
    except Exception:
        authority = None
    if authority:
        return f"{authority[0]}:{authority[1]}"
    try:
        return value.to_string()
    except Exception:
        return str(value)


def _crs_status(crs_values: Mapping[str, str]) -> str:
    if not crs_values:
        return "not_run"
    allowed = {"EPSG:3857", "NONSPATIAL"}
    return "passed" if all(str(value).upper() in allowed for value in crs_values.values()) else "failed"


def _road_endpoint_missing(properties: Mapping[str, Any], node_ids: set[str]) -> bool:
    snode = _id_text(properties.get("snodeid"))
    enode = _id_text(properties.get("enodeid"))
    return bool((snode and snode not in node_ids) or (enode and enode not in node_ids))


def _id_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    try:
        number = float(str(value).strip())
    except Exception:
        return str(value).strip()
    if number.is_integer():
        return str(int(number))
    return str(value).strip()


def _source_text(value: Any) -> str:
    return _id_text(value)


def _write_funnel_md(path: Path, summary: Mapping[str, Any]) -> None:
    lines = [
        f"# T06 Funnel - {summary.get('case_id')}",
        "",
        f"- status: {summary.get('status')}",
        f"- t06_run_root: {summary.get('t06_run_root') or '<none>'}",
        "",
        "| stage | metric | value |",
        "|---|---:|---:|",
    ]
    for row in summary.get("metrics") or []:
        value = "" if row.get("value") is None else row.get("value")
        lines.append(f"| {row.get('stage')} | {row.get('metric')} | {value} |")
    lines.extend(["", "## Reject Reasons", ""])
    reject_counts = summary.get("reject_reason_counts") or {}
    for stage, counts in reject_counts.items():
        lines.append(f"- {stage}: {json.dumps(counts or {}, ensure_ascii=False, sort_keys=True)}")
    lines.extend(["", "## Replacement Quality", ""])
    quality = summary.get("replacement_quality") or {}
    for key, value in quality.items():
        lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _case_id_from_manifest(case_manifest: Mapping[str, Any], case_dir: Path) -> str:
    scope = case_manifest.get("scope") if isinstance(case_manifest.get("scope"), Mapping) else {}
    for key in ("case_id", "swsd_semantic_junction_id", "semantic_junction_id"):
        value = scope.get(key) if isinstance(scope, Mapping) else None
        if value is not None and str(value).strip():
            return str(value).strip()
    return case_dir.name


def _path_from(value: str | Path | None) -> Path | None:
    if value is None or not str(value).strip():
        return None
    return Path(value).expanduser().resolve()


def _path_text(path: Path | None) -> str:
    if path is None:
        return ""
    return path.as_posix() if path.exists() else ""


def _paths_payload(inputs: Mapping[str, Path | None]) -> dict[str, str]:
    return {key: "" if value is None else str(value) for key, value in inputs.items()}


def _first_existing(root: Path, names: Sequence[str], *, recursive: bool = True) -> Path | None:
    for name in names:
        direct = root / name
        if direct.exists():
            return direct
        if recursive:
            matches = sorted(root.rglob(name)) if root.is_dir() else []
            if matches:
                return matches[0]
    return None


def _prefer_path(root: Path, name: str, *, contains: Sequence[str] = ()) -> Path | None:
    direct = root / name
    if direct.exists() and all(part in direct.as_posix() for part in contains):
        return direct
    matches = sorted(root.rglob(name)) if root.is_dir() else []
    preferred = [path for path in matches if all(part in path.as_posix() for part in contains)]
    if preferred:
        return preferred[0]
    return matches[0] if matches else None


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_json_if_file(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    return _read_json(path)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _command_env(repo_root: Path, overrides: Mapping[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    src_root = str(repo_root / "src")
    env["PYTHONPATH"] = src_root + (":" + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    repo_python = repo_root / ".venv" / "bin" / "python"
    if _is_accessible_file(repo_python):
        env.setdefault("PYTHON_BIN", str(repo_python))
    env.update({key: str(value) for key, value in overrides.items()})
    return env


def _tail(path: Path, *, max_lines: int = 80) -> list[str]:
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return lines[-max_lines:]


def _repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / ".git").exists() and (parent / "src").is_dir():
            return parent
    return current.parents[4]


def _python_bin(repo_root: Path) -> Path | str:
    candidate = repo_root / ".venv" / "bin" / "python"
    return candidate if _is_accessible_file(candidate) else "python3"


def _is_accessible_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _default_run_id() -> str:
    return "t10_e2e_case_runner_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_case_id(case_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(case_id))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run T10 end-to-end case orchestration from a T10 case package.")
    parser.add_argument("--package-dir", required=True, help="Decoded T10 package directory.")
    parser.add_argument("--out-root", default="outputs/_work/t10_e2e_case_runs", help="T10 E2E output root.")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--case-id", dest="case_ids", action="append", default=None, help="CaseID to run. Repeatable.")
    parser.add_argument("--stop-after", choices=T10_E2E_STAGE_ORDER_WITH_T12, default=None)
    parser.add_argument(
        "--run-t12",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Insert audit-only T12 after T11 and before T09. Disabled by default.",
    )
    parser.add_argument(
        "--t12-review-decisions",
        default=None,
        help="Optional T12 review-decision CSV applied to every selected Case.",
    )
    parser.add_argument("--continue-on-error", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--exit-zero", action="store_true", help="Return 0 even when some cases are blocked or failed.")
    parser.add_argument(
        "--feedback-iterations",
        type=int,
        default=0,
        help="Optional T10 upstream-feedback iteration count. 0 keeps the default single-pass behavior.",
    )
    parser.add_argument(
        "--t10-pair-anchor-endpoint-clusters",
        default=None,
        help="Optional T10 pair-anchor endpoint cluster CSV to feed into T05 Phase2.",
    )
    return parser.parse_args(argv)


_T09_STEP12_CODE = r"""
import json
import os
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import run_t09_swsd_field_rule_restoration

def optional(name):
    value = os.environ.get(name, "").strip()
    return value or None

result = run_t09_swsd_field_rule_restoration(
    swnode_gpkg=os.environ["T09_SWNODE"],
    swroad_gpkg=os.environ["T09_SWROAD"],
    segment_gpkg=os.environ["T09_SEGMENT"],
    restriction_gpkg=optional("T09_RESTRICTION"),
    arrow_gpkg=optional("T09_ARROW"),
    output_dir=os.environ["T09_OUT_ROOT"],
    run_id=os.environ["T09_RUN_ID"],
)
print(json.dumps({
    "summary": str(result.artifacts.summary_json),
    "arms": str(result.artifacts.arms_gpkg),
    "movements": str(result.artifacts.movements_gpkg),
    "restored_rules": str(result.artifacts.rules_gpkg),
}, ensure_ascii=False, indent=2), flush=True)
"""


_T09_STEP3_CODE = r"""
import json
import os
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import run_t09_frcsd_restriction_modeling

result = run_t09_frcsd_restriction_modeling(
    arms_path=os.environ["T09_ARMS"],
    movements_path=os.environ["T09_MOVEMENTS"],
    restored_rules_path=os.environ["T09_RULES"],
    frcsd_road_path=os.environ["T09_FRCSD_ROAD"],
    frcsd_node_path=os.environ["T09_FRCSD_NODE"],
    segment_relation_path=os.environ["T09_SEGMENT_RELATION"],
    output_dir=os.environ["T09_OUT_ROOT"],
    run_id=os.environ["T09_RUN_ID"],
)
print(json.dumps({
    "summary": str(result.artifacts.summary_json),
    "frcsd_restriction": str(result.artifacts.frcsd_restriction_gpkg),
    "restriction_count": result.restriction_count,
}, ensure_ascii=False, indent=2), flush=True)
"""


if __name__ == "__main__":
    raise SystemExit(main())
