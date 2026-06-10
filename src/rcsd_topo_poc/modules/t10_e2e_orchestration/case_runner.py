from __future__ import annotations

import argparse
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

from .contracts import T10_MODULE_ID, T10_T08_POLICY, T10_V1_CHAIN


T10_E2E_STAGE_ORDER = (
    "t01",
    "t07",
    "t03",
    "t04",
    "t05",
    "t06_step12",
    "t06_step3",
    "t09_step12",
    "t09_step3",
)

T10_E2E_STAGE_MODULES = {
    "t01": "t01_data_preprocess",
    "t07": "t07_semantic_junction_anchor",
    "t03": "t03_virtual_junction_anchor",
    "t04": "t04_divmerge_virtual_polygon",
    "t05": "t05_junction_surface_fusion",
    "t06_step12": "t06_segment_fusion_precheck",
    "t06_step3": "t06_segment_fusion_precheck",
    "t09_step12": "t09_swsd_field_rule_restoration",
    "t09_step3": "t09_swsd_field_rule_restoration",
}


@dataclass(frozen=True)
class T10E2ECaseRunArtifacts:
    run_root: Path
    manifest_json: Path
    summary_json: Path
    case_manifest_paths: tuple[Path, ...]
    t06_funnel_paths: tuple[Path, ...]


def run_t10_e2e_cases_from_package(
    *,
    package_dir: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    case_ids: Sequence[str] | None = None,
    stop_after: str | None = None,
    continue_on_error: bool = True,
    exit_on_incomplete: bool = False,
) -> T10E2ECaseRunArtifacts:
    package_root = Path(package_dir).expanduser().resolve()
    if not package_root.is_dir():
        raise FileNotFoundError(f"T10 package_dir is not a directory: {package_root}")

    selected_case_dirs = _discover_case_dirs(package_root=package_root, case_ids=case_ids)
    if not selected_case_dirs:
        raise ValueError(f"No T10 case directories found under package: {package_root}")
    effective_run_id = run_id or _default_run_id()
    run_root = Path(out_root).expanduser().resolve() / effective_run_id
    run_root.mkdir(parents=True, exist_ok=True)

    repo_root = _repo_root()
    python_bin = _python_bin(repo_root)
    stage_limit = _stage_limit(stop_after)
    case_manifests: list[Path] = []
    funnel_paths: list[Path] = []
    case_results: list[dict[str, Any]] = []

    for case_dir in selected_case_dirs:
        case_result = _run_one_case(
            package_root=package_root,
            case_dir=case_dir,
            run_root=run_root,
            repo_root=repo_root,
            python_bin=python_bin,
            stage_limit=stage_limit,
            continue_on_error=continue_on_error,
        )
        case_manifests.append(Path(case_result["case_run_manifest_path"]))
        if case_result.get("t06_funnel_json"):
            funnel_paths.append(Path(case_result["t06_funnel_json"]))
        case_results.append(case_result)
        if not continue_on_error and case_result["overall_status"] != "passed":
            break

    manifest = {
        "module_id": T10_MODULE_ID,
        "runner": "run_t10_e2e_cases_from_package",
        "run_id": effective_run_id,
        "produced_at_utc": _now_text(),
        "package_dir": str(package_root),
        "run_root": str(run_root),
        "repo_root": str(repo_root),
        "python_bin": str(python_bin),
        "chain": list(T10_V1_CHAIN),
        "stage_order": list(T10_E2E_STAGE_ORDER[:stage_limit]),
        "t08_policy": T10_T08_POLICY,
        "case_count": len(case_results),
        "cases": case_results,
        "qa": _runner_qa(case_results),
    }
    summary = {
        "module_id": T10_MODULE_ID,
        "run_id": effective_run_id,
        "package_dir": str(package_root),
        "run_root": str(run_root),
        "case_count": len(case_results),
        "passed_case_count": sum(1 for item in case_results if item["overall_status"] == "passed"),
        "failed_case_count": sum(1 for item in case_results if item["overall_status"] == "failed"),
        "blocked_case_count": sum(1 for item in case_results if item["overall_status"] == "blocked"),
        "skipped_case_count": sum(1 for item in case_results if item["overall_status"] == "skipped"),
        "passed": bool(case_results) and all(item["overall_status"] == "passed" for item in case_results),
        "exit_on_incomplete": exit_on_incomplete,
    }
    manifest_path = run_root / "t10_e2e_run_manifest.json"
    summary_path = run_root / "t10_e2e_run_summary.json"
    _write_json(manifest_path, manifest)
    _write_json(summary_path, summary)
    return T10E2ECaseRunArtifacts(
        run_root=run_root,
        manifest_json=manifest_path,
        summary_json=summary_path,
        case_manifest_paths=tuple(case_manifests),
        t06_funnel_paths=tuple(funnel_paths),
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    artifacts = run_t10_e2e_cases_from_package(
        package_dir=args.package_dir,
        out_root=args.out_root,
        run_id=args.run_id,
        case_ids=args.case_ids,
        stop_after=args.stop_after,
        continue_on_error=args.continue_on_error,
        exit_on_incomplete=not args.exit_zero,
    )
    summary = _read_json(artifacts.summary_json)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    if args.exit_zero:
        return 0
    return 0 if summary.get("passed") else 1


def _run_one_case(
    *,
    package_root: Path,
    case_dir: Path,
    run_root: Path,
    repo_root: Path,
    python_bin: Path | str,
    stage_limit: int,
    continue_on_error: bool,
) -> dict[str, Any]:
    case_manifest_path = case_dir / "t10_case_evidence_manifest.json"
    case_manifest = _read_json(case_manifest_path)
    case_id = _case_id_from_manifest(case_manifest, case_dir)
    case_run_dir = run_root / "cases" / _safe_case_id(case_id)
    case_run_dir.mkdir(parents=True, exist_ok=True)
    external_inputs = _external_input_paths(case_manifest=case_manifest, case_dir=case_dir)

    stage_records: list[dict[str, Any]] = []
    handoffs: dict[str, str] = {}
    blocked = False
    for stage_id in T10_E2E_STAGE_ORDER[:stage_limit]:
        stage_dir = case_run_dir / stage_id
        if blocked:
            record = _blocked_record(stage_id, stage_dir, "Previous stage did not produce required handoff.")
        else:
            try:
                record, produced = _run_stage(
                    stage_id=stage_id,
                    case_id=case_id,
                    case_run_dir=case_run_dir,
                    stage_dir=stage_dir,
                    repo_root=repo_root,
                    python_bin=python_bin,
                    external_inputs=external_inputs,
                    handoffs=handoffs,
                )
            except Exception as exc:  # noqa: BLE001 - runner must audit unexpected module failures.
                record = _exception_record(stage_id, stage_dir, exc)
                produced = {}
            if record["status"] == "passed":
                handoffs.update({key: value for key, value in produced.items() if value})
            else:
                blocked = True
        stage_records.append(record)
        _write_json(stage_dir / f"{stage_id}_stage.json", record)

    funnel = _write_t06_funnel(case_run_dir=case_run_dir, case_id=case_id, handoffs=handoffs, stage_records=stage_records)
    overall_status = _overall_case_status(stage_records, stage_limit)
    case_payload = {
        "module_id": T10_MODULE_ID,
        "runner": "run_t10_e2e_cases_from_package",
        "case_id": case_id,
        "case_dir": str(case_dir),
        "package_root": str(package_root),
        "case_run_dir": str(case_run_dir),
        "produced_at_utc": _now_text(),
        "stage_order": list(T10_E2E_STAGE_ORDER[:stage_limit]),
        "stage_records": stage_records,
        "external_inputs": {key: str(value) for key, value in external_inputs.items()},
        "handoffs": handoffs,
        "overall_status": overall_status,
        "t06_funnel_json": str(funnel["json_path"]),
        "qa": {
            "crs_and_transform": "T10 delegates CRS handling to each module runner and records source package CRS audit.",
            "topology_silent_fix": False,
            "geometry_semantics": "Case is keyed by SWSD semantic junction id; spatial extent comes from the package scope.",
            "audit_traceability": "Every stage records command, explicit inputs, outputs, status and stdout log path.",
            "performance_verifiability": "Every stage records wall-clock duration and T06 funnel counts when T06 outputs exist.",
        },
    }
    case_summary = {
        "module_id": T10_MODULE_ID,
        "case_id": case_id,
        "overall_status": overall_status,
        "passed": overall_status == "passed",
        "stage_statuses": {record["stage_id"]: record["status"] for record in stage_records},
        "t06_funnel": funnel["summary"],
    }
    manifest_path = case_run_dir / "t10_e2e_case_run_manifest.json"
    summary_path = case_run_dir / "t10_e2e_case_run_summary.json"
    _write_json(manifest_path, case_payload)
    _write_json(summary_path, case_summary)
    return {
        "case_id": case_id,
        "case_dir": str(case_dir),
        "case_run_dir": str(case_run_dir),
        "case_run_manifest_path": str(manifest_path),
        "case_run_summary_path": str(summary_path),
        "overall_status": overall_status,
        "stage_statuses": case_summary["stage_statuses"],
        "t06_funnel_json": str(funnel["json_path"]),
    }


def _run_stage(
    *,
    stage_id: str,
    case_id: str,
    case_run_dir: Path,
    stage_dir: Path,
    repo_root: Path,
    python_bin: Path | str,
    external_inputs: Mapping[str, Path],
    handoffs: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    if stage_id == "t01":
        return _run_t01(case_id, stage_dir, repo_root, external_inputs)
    if stage_id == "t07":
        return _run_t07(case_id, stage_dir, repo_root, external_inputs, handoffs)
    if stage_id == "t03":
        return _run_t03(case_id, stage_dir, repo_root, external_inputs, handoffs)
    if stage_id == "t04":
        return _run_t04(case_id, stage_dir, repo_root, external_inputs, handoffs)
    if stage_id == "t05":
        return _run_t05(case_id, stage_dir, repo_root, python_bin, external_inputs, handoffs)
    if stage_id == "t06_step12":
        return _run_t06_step12(case_id, stage_dir, repo_root, python_bin, handoffs)
    if stage_id == "t06_step3":
        return _run_t06_step3(case_id, stage_dir, repo_root, python_bin, handoffs)
    if stage_id == "t09_step12":
        return _run_t09_step12(case_id, stage_dir, repo_root, python_bin, external_inputs, handoffs)
    if stage_id == "t09_step3":
        return _run_t09_step3(case_id, stage_dir, repo_root, python_bin, handoffs)
    raise ValueError(f"unsupported T10 stage: {stage_id}")


def _run_t01(
    case_id: str,
    stage_dir: Path,
    repo_root: Path,
    external_inputs: Mapping[str, Path],
) -> tuple[dict[str, Any], dict[str, str]]:
    inputs = {
        "prepared_swsd_roads": external_inputs.get("prepared_swsd_roads"),
        "prepared_swsd_nodes": external_inputs.get("prepared_swsd_nodes"),
    }
    missing = _missing_files(inputs)
    if missing:
        return _blocked_record("t01", stage_dir, "Missing T01 external inputs.", inputs=inputs, missing=missing), {}
    env = {"RUN_ID": f"t01_{_safe_case_id(case_id)}", "DEBUG": "0"}
    command = [
        "bash",
        "scripts/t01_run_full_data.sh",
        str(inputs["prepared_swsd_roads"]),
        str(inputs["prepared_swsd_nodes"]),
        str(stage_dir),
    ]
    record = _execute_command("t01", stage_dir, repo_root, command, env, inputs)
    produced = {
        "t01_segment": _path_text(_first_existing(stage_dir, ("segment.gpkg",), recursive=False)),
        "t01_nodes": _path_text(_first_existing(stage_dir, ("nodes.gpkg",), recursive=False)),
        "t01_roads": _path_text(_first_existing(stage_dir, ("roads.gpkg",), recursive=False)),
        "t01_summary": _path_text(stage_dir / "t01_skill_v1_summary.json"),
    }
    _attach_outputs(record, produced)
    return record, produced if record["status"] == "passed" else produced


def _run_t07(
    case_id: str,
    stage_dir: Path,
    repo_root: Path,
    external_inputs: Mapping[str, Path],
    handoffs: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    inputs = {
        "t01_nodes": _path_from(handoffs.get("t01_nodes")),
        "drivezone": external_inputs.get("drivezone"),
        "rcsd_intersection": external_inputs.get("rcsd_intersection"),
    }
    missing = _missing_files(inputs)
    if missing:
        return _blocked_record("t07", stage_dir, "Missing T07 inputs.", inputs=inputs, missing=missing), {}
    env = {
        "NODES_PATH": str(inputs["t01_nodes"]),
        "DRIVEZONE_PATH": str(inputs["drivezone"]),
        "INTERSECTION_PATH": str(inputs["rcsd_intersection"]),
        "OUT_ROOT": str(stage_dir),
        "RUN_ID": "t07",
    }
    record = _execute_command("t07", stage_dir, repo_root, ["bash", "scripts/t07_run_semantic_junction_anchor_innernet.sh"], env, inputs)
    run_root = stage_dir / "t07"
    produced = {
        "t07_run_root": _path_text(run_root),
        "t07_nodes": _path_text(_prefer_path(run_root, "nodes.gpkg", contains=("step2_anchor_recognition",))),
        "t07_relation_evidence": _path_text(_prefer_path(run_root, "t07_swsd_rcsd_relation_evidence.csv")),
        "t07_surface": _path_text(_prefer_path(run_root, "t07_rcsdintersection_anchor_surface.gpkg")),
    }
    _attach_outputs(record, produced)
    return record, produced


def _run_t03(
    case_id: str,
    stage_dir: Path,
    repo_root: Path,
    external_inputs: Mapping[str, Path],
    handoffs: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    inputs = {
        "t07_nodes": _path_from(handoffs.get("t07_nodes")),
        "t01_roads": _path_from(handoffs.get("t01_roads")),
        "drivezone": external_inputs.get("drivezone"),
        "rcsdroad": external_inputs.get("rcsdroad"),
        "rcsdnode": external_inputs.get("rcsdnode"),
    }
    missing = _missing_files(inputs)
    if missing:
        return _blocked_record("t03", stage_dir, "Missing T03 inputs.", inputs=inputs, missing=missing), {}
    env = {
        "NODES_PATH": str(inputs["t07_nodes"]),
        "ROADS_PATH": str(inputs["t01_roads"]),
        "DRIVEZONE_PATH": str(inputs["drivezone"]),
        "RCSDROAD_PATH": str(inputs["rcsdroad"]),
        "RCSDNODE_PATH": str(inputs["rcsdnode"]),
        "OUT_ROOT": str(stage_dir),
        "RUN_ID": "t03",
        "WORKERS": os.environ.get("T10_T03_WORKERS", "1"),
        "MAX_CASES": os.environ.get("T10_T03_MAX_CASES", ""),
        "PERF_AUDIT": "0",
        "RESUME": "0",
        "RETRY_FAILED": "0",
        "LOCAL_CONTEXT_SNAPSHOT_MODE": os.environ.get("T10_LOCAL_CONTEXT_SNAPSHOT_MODE", "all"),
    }
    record = _execute_command("t03", stage_dir, repo_root, ["bash", "scripts/t03_run_internal_full_input_8workers.sh"], env, inputs)
    run_root = stage_dir / "t03"
    produced = {
        "t03_run_root": _path_text(run_root),
        "t03_surface": _path_text(run_root / "virtual_intersection_polygons.gpkg"),
        "t03_relation_evidence": _path_text(run_root / "t03_swsd_rcsd_relation_evidence.csv"),
        "t03_intersection_match": _path_text(run_root / "intersection_match_t03.geojson"),
    }
    _attach_outputs(record, produced)
    return record, produced


def _run_t04(
    case_id: str,
    stage_dir: Path,
    repo_root: Path,
    external_inputs: Mapping[str, Path],
    handoffs: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    inputs = {
        "t07_nodes": _path_from(handoffs.get("t07_nodes")),
        "t01_roads": _path_from(handoffs.get("t01_roads")),
        "drivezone": external_inputs.get("drivezone"),
        "divstripzone": external_inputs.get("divstripzone"),
        "rcsdroad": external_inputs.get("rcsdroad"),
        "rcsdnode": external_inputs.get("rcsdnode"),
    }
    missing = _missing_files(inputs)
    if missing:
        return _blocked_record("t04", stage_dir, "Missing T04 inputs.", inputs=inputs, missing=missing), {}
    env = {
        "NODES_PATH": str(inputs["t07_nodes"]),
        "ROADS_PATH": str(inputs["t01_roads"]),
        "DRIVEZONE_PATH": str(inputs["drivezone"]),
        "DIVSTRIPZONE_PATH": str(inputs["divstripzone"]),
        "RCSDROAD_PATH": str(inputs["rcsdroad"]),
        "RCSDNODE_PATH": str(inputs["rcsdnode"]),
        "INTERSECTION_MATCH_T03_PATH": handoffs.get("t03_intersection_match", ""),
        "OUT_ROOT": str(stage_dir),
        "RUN_ID": "t04",
        "WORKERS": os.environ.get("T10_T04_WORKERS", "1"),
        "MAX_CASES": os.environ.get("T10_T04_MAX_CASES", ""),
        "PERF_AUDIT": "0",
        "RESUME": "0",
        "RETRY_FAILED": "0",
        "CASE_SCAN": "off",
        "LOCAL_CONTEXT_SNAPSHOT_MODE": os.environ.get("T10_LOCAL_CONTEXT_SNAPSHOT_MODE", "all"),
    }
    record = _execute_command("t04", stage_dir, repo_root, ["bash", "scripts/t04_run_internal_full_input_8workers.sh"], env, inputs)
    run_root = stage_dir / "t04"
    produced = {
        "t04_run_root": _path_text(run_root),
        "t04_surface": _path_text(run_root / "divmerge_virtual_anchor_surface.gpkg"),
        "t04_relation_evidence": _path_text(run_root / "t04_swsd_rcsd_relation_evidence.csv"),
        "t04_intersection_match": _path_text(run_root / "intersection_match_t04.geojson"),
        "t04_summary": _path_text(_first_existing(run_root, ("divmerge_virtual_anchor_surface_summary.json", "divmerge_virtual_anchor_surface_summary.csv"))),
        "t04_audit": _path_text(run_root / "divmerge_virtual_anchor_surface_audit.gpkg"),
        "t04_case_root": _path_text(run_root / "cases"),
    }
    _attach_outputs(record, produced)
    return record, produced


def _run_t05(
    case_id: str,
    stage_dir: Path,
    repo_root: Path,
    python_bin: Path | str,
    external_inputs: Mapping[str, Path],
    handoffs: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    inputs = {
        "t07_run_root": _path_from(handoffs.get("t07_run_root")),
        "t07_nodes": _path_from(handoffs.get("t07_nodes")),
        "t07_surface": _path_from(handoffs.get("t07_surface")),
        "t07_relation_evidence": _path_from(handoffs.get("t07_relation_evidence")),
        "t03_run_root": _path_from(handoffs.get("t03_run_root")),
        "t03_surface": _path_from(handoffs.get("t03_surface")),
        "t03_relation_evidence": _path_from(handoffs.get("t03_relation_evidence")),
        "t04_run_root": _path_from(handoffs.get("t04_run_root")),
        "t04_surface": _path_from(handoffs.get("t04_surface")),
        "t04_relation_evidence": _path_from(handoffs.get("t04_relation_evidence")),
        "rcsdroad": external_inputs.get("rcsdroad"),
        "rcsdnode": external_inputs.get("rcsdnode"),
    }
    missing = _missing_files(inputs)
    if missing:
        return _blocked_record("t05", stage_dir, "Missing T05 explicit file inputs.", inputs=inputs, missing=missing), {}
    command = [
        str(python_bin),
        "scripts/t05_innernet_experiment.py",
        "--t07-dir",
        str(inputs["t07_run_root"]),
        "--t03-dir",
        str(inputs["t03_run_root"]),
        "--t04-dir",
        str(inputs["t04_run_root"]),
        "--rcsdroad",
        str(inputs["rcsdroad"]),
        "--rcsdnode",
        str(inputs["rcsdnode"]),
        "--nodes",
        str(inputs["t07_nodes"]),
        "--out-root",
        str(stage_dir),
        "--phase1-run-id",
        "t05_phase1",
        "--phase2-run-id",
        "t05_phase2",
        "--readonly-workers",
        os.environ.get("T10_T05_READONLY_WORKERS", "1"),
        "--progress-interval",
        os.environ.get("T10_T05_PROGRESS_INTERVAL", "100"),
    ]
    record = _execute_command("t05", stage_dir, repo_root, command, {}, inputs)
    phase1_root = stage_dir / "t05_phase1"
    phase2_root = stage_dir / "t05_phase2"
    produced = {
        "t05_phase1_root": _path_text(phase1_root),
        "t05_phase2_root": _path_text(phase2_root),
        "t05_junction_surface": _path_text(phase1_root / "junction_anchor_surface.gpkg"),
        "t05_intersection_match_all": _path_text(phase2_root / "intersection_match_all.geojson"),
        "t05_rcsdroad_out": _path_text(phase2_root / "rcsdroad_out.gpkg"),
        "t05_rcsdnode_out": _path_text(phase2_root / "rcsdnode_out.gpkg"),
        "t05_phase2_summary": _path_text(phase2_root / "t05_phase2_summary.json"),
    }
    _attach_outputs(record, produced)
    return record, produced


def _run_t06_step12(
    case_id: str,
    stage_dir: Path,
    repo_root: Path,
    python_bin: Path | str,
    handoffs: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    inputs = {
        "t01_segment": _path_from(handoffs.get("t01_segment")),
        "t01_roads": _path_from(handoffs.get("t01_roads")),
        "t07_nodes": _path_from(handoffs.get("t07_nodes")),
        "t05_intersection_match_all": _path_from(handoffs.get("t05_intersection_match_all")),
        "t05_rcsdroad_out": _path_from(handoffs.get("t05_rcsdroad_out")),
        "t05_rcsdnode_out": _path_from(handoffs.get("t05_rcsdnode_out")),
    }
    missing = _missing_files(inputs)
    if missing:
        return _blocked_record("t06_step12", stage_dir, "Missing T06 Step1/2 inputs.", inputs=inputs, missing=missing), {}
    command = [
        str(python_bin),
        "scripts/t06_run_innernet_precheck.py",
        "--swsd-segment",
        str(inputs["t01_segment"]),
        "--swsd-roads",
        str(inputs["t01_roads"]),
        "--swsd-nodes",
        str(inputs["t07_nodes"]),
        "--intersection-match",
        str(inputs["t05_intersection_match_all"]),
        "--rcsdroad",
        str(inputs["t05_rcsdroad_out"]),
        "--rcsdnode",
        str(inputs["t05_rcsdnode_out"]),
        "--out-root",
        str(stage_dir),
        "--run-id",
        "t06",
        "--no-progress",
    ]
    record = _execute_command("t06_step12", stage_dir, repo_root, command, {}, inputs)
    run_root = stage_dir / "t06"
    produced = {
        "t06_run_root": _path_text(run_root),
        "t06_step1_summary": _path_text(run_root / "step1_identify_fusion_units" / "t06_step1_summary.json"),
        "t06_step2_summary": _path_text(run_root / "step2_extract_rcsd_segments" / "t06_step2_summary.json"),
        "t06_step2_replaceable": _path_text(run_root / "step2_extract_rcsd_segments" / "t06_rcsd_segment_replaceable.gpkg"),
    }
    _attach_outputs(record, produced)
    return record, produced


def _run_t06_step3(
    case_id: str,
    stage_dir: Path,
    repo_root: Path,
    python_bin: Path | str,
    handoffs: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    t06_run_root = _path_from(handoffs.get("t06_run_root"))
    inputs = {
        "t06_run_root": t06_run_root,
        "t01_segment": _path_from(handoffs.get("t01_segment")),
        "t01_roads": _path_from(handoffs.get("t01_roads")),
        "t07_nodes": _path_from(handoffs.get("t07_nodes")),
        "t05_rcsdroad_out": _path_from(handoffs.get("t05_rcsdroad_out")),
        "t05_rcsdnode_out": _path_from(handoffs.get("t05_rcsdnode_out")),
    }
    missing = _missing_files(inputs)
    if missing:
        return _blocked_record("t06_step3", stage_dir, "Missing T06 Step3 inputs.", inputs=inputs, missing=missing), {}
    command = [
        str(python_bin),
        "scripts/t06_run_step3_segment_replacement.py",
        "--t06-run-root",
        str(t06_run_root),
        "--swsd-segment",
        str(inputs["t01_segment"]),
        "--swsd-roads",
        str(inputs["t01_roads"]),
        "--swsd-nodes",
        str(inputs["t07_nodes"]),
        "--rcsdroad",
        str(inputs["t05_rcsdroad_out"]),
        "--rcsdnode",
        str(inputs["t05_rcsdnode_out"]),
        "--out-root",
        str(t06_run_root.parent),
        "--run-id",
        t06_run_root.name,
        "--no-progress",
    ]
    record = _execute_command("t06_step3", stage_dir, repo_root, command, {}, inputs)
    step3_root = t06_run_root / "step3_segment_replacement"
    produced = {
        "t06_step3_root": _path_text(step3_root),
        "t06_frcsd_road": _path_text(step3_root / "t06_frcsd_road.gpkg"),
        "t06_frcsd_node": _path_text(step3_root / "t06_frcsd_node.gpkg"),
        "t06_swsd_frcsd_segment_relation": _path_text(step3_root / "t06_step3_swsd_frcsd_segment_relation.gpkg"),
        "t06_step3_summary": _path_text(step3_root / "t06_step3_summary.json"),
    }
    _attach_outputs(record, produced)
    return record, produced


def _run_t09_step12(
    case_id: str,
    stage_dir: Path,
    repo_root: Path,
    python_bin: Path | str,
    external_inputs: Mapping[str, Path],
    handoffs: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    inputs = {
        "t07_nodes": _path_from(handoffs.get("t07_nodes")),
        "t01_roads": _path_from(handoffs.get("t01_roads")),
        "t01_segment": _path_from(handoffs.get("t01_segment")),
        "sw_restriction_tool7": external_inputs.get("sw_restriction_tool7"),
        "sw_arrow_tool8": external_inputs.get("sw_arrow_tool8"),
    }
    required = {key: value for key, value in inputs.items() if key in {"t07_nodes", "t01_roads", "t01_segment"}}
    missing = _missing_files(required)
    if missing:
        return _blocked_record("t09_step12", stage_dir, "Missing T09 Step1/2 inputs.", inputs=inputs, missing=missing), {}
    env = {
        "T09_SWNODE": str(inputs["t07_nodes"]),
        "T09_SWROAD": str(inputs["t01_roads"]),
        "T09_SEGMENT": str(inputs["t01_segment"]),
        "T09_RESTRICTION": str(inputs["sw_restriction_tool7"] or ""),
        "T09_ARROW": str(inputs["sw_arrow_tool8"] or ""),
        "T09_OUT_ROOT": str(stage_dir),
        "T09_RUN_ID": "t09_step12",
    }
    command = [str(python_bin), "-c", _T09_STEP12_CODE]
    record = _execute_command("t09_step12", stage_dir, repo_root, command, env, inputs)
    run_root = stage_dir / "t09_step12"
    produced = {
        "t09_step12_root": _path_text(run_root),
        "t09_arms": _path_text(run_root / "t09_swsd_arms.gpkg"),
        "t09_movements": _path_text(run_root / "t09_arm_movements.gpkg"),
        "t09_restored_field_rules": _path_text(run_root / "t09_restored_field_rules.gpkg"),
        "t09_step12_summary": _path_text(run_root / "t09_swsd_field_rule_restoration_summary.json"),
    }
    _attach_outputs(record, produced)
    return record, produced


def _run_t09_step3(
    case_id: str,
    stage_dir: Path,
    repo_root: Path,
    python_bin: Path | str,
    handoffs: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    inputs = {
        "t09_arms": _path_from(handoffs.get("t09_arms")),
        "t09_movements": _path_from(handoffs.get("t09_movements")),
        "t09_restored_field_rules": _path_from(handoffs.get("t09_restored_field_rules")),
        "t06_frcsd_road": _path_from(handoffs.get("t06_frcsd_road")),
        "t06_frcsd_node": _path_from(handoffs.get("t06_frcsd_node")),
        "t06_swsd_frcsd_segment_relation": _path_from(handoffs.get("t06_swsd_frcsd_segment_relation")),
    }
    missing = _missing_files(inputs)
    if missing:
        return _blocked_record("t09_step3", stage_dir, "Missing T09 Step3 inputs.", inputs=inputs, missing=missing), {}
    env = {
        "T09_ARMS": str(inputs["t09_arms"]),
        "T09_MOVEMENTS": str(inputs["t09_movements"]),
        "T09_RULES": str(inputs["t09_restored_field_rules"]),
        "T09_FRCSD_ROAD": str(inputs["t06_frcsd_road"]),
        "T09_FRCSD_NODE": str(inputs["t06_frcsd_node"]),
        "T09_SEGMENT_RELATION": str(inputs["t06_swsd_frcsd_segment_relation"]),
        "T09_OUT_ROOT": str(stage_dir),
        "T09_RUN_ID": "t09_step3",
    }
    command = [str(python_bin), "-c", _T09_STEP3_CODE]
    record = _execute_command("t09_step3", stage_dir, repo_root, command, env, inputs)
    run_root = stage_dir / "t09_step3"
    produced = {
        "t09_step3_root": _path_text(run_root),
        "t09_frcsd_restriction": _path_text(run_root / "frcsd_restriction.gpkg"),
        "t09_step3_summary": _path_text(run_root / "t09_step3_frcsd_restriction_summary.json"),
    }
    _attach_outputs(record, produced)
    return record, produced


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
        _metric("T06 Step2", "rejected_count", step2.get("rejected_count")),
        _metric("T06 Step2", "buffer_segment_count", step2.get("buffer_segment_count")),
        _metric("T06 Step2", "buffer_rejected_count", step2.get("buffer_rejected_count")),
        _metric("T06 Step3", "input_replaceable_count", step3.get("input_replaceable_count")),
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
        case_dirs = [path for path in sorted(candidates_root.iterdir()) if (path / "t10_case_evidence_manifest.json").is_file()]
    elif (package_root / "t10_case_evidence_manifest.json").is_file():
        case_dirs = [package_root]
    else:
        case_dirs = []
    if wanted:
        case_dirs = [path for path in case_dirs if _safe_case_id(path.name) in wanted]
    return case_dirs


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


def _stage_limit(stop_after: str | None) -> int:
    if not stop_after:
        return len(T10_E2E_STAGE_ORDER)
    normalized = str(stop_after).strip()
    if normalized not in T10_E2E_STAGE_ORDER:
        raise ValueError(f"stop_after must be one of {', '.join(T10_E2E_STAGE_ORDER)}.")
    return T10_E2E_STAGE_ORDER.index(normalized) + 1


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
    return str(path) if path.exists() else ""


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
    if repo_python.is_file():
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
    return candidate if candidate.is_file() else "python3"


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
    parser.add_argument("--stop-after", choices=T10_E2E_STAGE_ORDER, default=None)
    parser.add_argument("--continue-on-error", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--exit-zero", action="store_true", help="Return 0 even when some cases are blocked or failed.")
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
