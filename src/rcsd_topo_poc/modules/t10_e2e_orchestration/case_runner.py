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

from .contracts import T10_MODULE_ID, T10_T08_POLICY, T10_V1_CHAIN
from .segment_noop_handoffs import try_segment_no_candidate_handoff as _seg_noop
from .upstream_feedback import write_t10_upstream_feedback


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
    "t07_step3": "t07_semantic_junction_anchor",
    "t06_step12": "t06_segment_fusion_precheck",
    "t06_step3": "t06_segment_fusion_precheck",
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


def run_t10_e2e_cases_from_package(
    *,
    package_dir: str | Path,
    out_root: str | Path,
    run_id: str | None = None,
    case_ids: Sequence[str] | None = None,
    stop_after: str | None = None,
    continue_on_error: bool = True,
    exit_on_incomplete: bool = False,
    feedback_iterations: int = 0,
    t10_side_group_endpoint_candidates: str | Path | None = None,
    t10_pair_anchor_endpoint_clusters: str | Path | None = None,
) -> T10E2ECaseRunArtifacts:
    if feedback_iterations < 0:
        raise ValueError("feedback_iterations must be >= 0.")
    if feedback_iterations and stop_after:
        raise ValueError("feedback_iterations requires the full T10 stage order; do not use stop_after.")
    if feedback_iterations:
        return _run_t10_e2e_feedback_iterations_from_package(
            package_dir=package_dir,
            out_root=out_root,
            run_id=run_id,
            case_ids=case_ids,
            continue_on_error=continue_on_error,
            exit_on_incomplete=exit_on_incomplete,
            feedback_iterations=feedback_iterations,
            t10_side_group_endpoint_candidates=t10_side_group_endpoint_candidates,
            t10_pair_anchor_endpoint_clusters=t10_pair_anchor_endpoint_clusters,
        )

    package_root = Path(package_dir).expanduser().resolve()
    if not package_root.is_dir():
        raise FileNotFoundError(f"T10 package_dir is not a directory: {package_root}")

    selected_case_dirs = _discover_case_dirs(package_root=package_root, case_ids=case_ids)
    if not selected_case_dirs:
        raise ValueError(f"No T10 case directories found under package: {package_root}")
    effective_run_id = run_id or _default_run_id()
    run_root = Path(out_root).expanduser().resolve() / effective_run_id
    run_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    started_at = _now_text()

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
            side_group_endpoint_candidate_path=_path_from(t10_side_group_endpoint_candidates),
            pair_anchor_endpoint_cluster_path=_path_from(t10_pair_anchor_endpoint_clusters),
        )
        case_manifests.append(Path(case_result["case_run_manifest_path"]))
        if case_result.get("t06_funnel_json"):
            funnel_paths.append(Path(case_result["t06_funnel_json"]))
        case_results.append(case_result)
        if not continue_on_error and case_result["overall_status"] != "passed":
            break

    upstream_feedback = write_t10_upstream_feedback(run_root=run_root, case_results=case_results)
    visual_check = _write_t06_visual_check_summary(run_root=run_root, case_results=case_results)
    ended_at = _now_text()
    duration_seconds = round(time.perf_counter() - started, 6)
    run_status = _overall_run_status(case_results)
    manifest = {
        "module_id": T10_MODULE_ID,
        "runner": "run_t10_e2e_cases_from_package",
        "run_id": effective_run_id,
        "produced_at_utc": _now_text(),
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "duration_seconds": duration_seconds,
        "status": run_status,
        "passed": run_status == "passed",
        "package_dir": str(package_root),
        "run_root": str(run_root),
        "repo_root": str(repo_root),
        "python_bin": str(python_bin),
        "chain": list(T10_V1_CHAIN),
        "stage_order": list(T10_E2E_STAGE_ORDER[:stage_limit]),
        "t08_policy": T10_T08_POLICY,
        "case_count": len(case_results),
        "cases": case_results,
        "upstream_feedback": {
            "segments_csv": str(upstream_feedback.segments_csv),
            "segments_json": str(upstream_feedback.segments_json),
            "summary_csv": str(upstream_feedback.summary_csv),
            "summary_json": str(upstream_feedback.summary_json),
            "relations_csv": str(upstream_feedback.relations_csv),
            "relations_json": str(upstream_feedback.relations_json),
            "relation_summary_csv": str(upstream_feedback.relation_summary_csv),
            "relation_summary_json": str(upstream_feedback.relation_summary_json),
            "side_group_candidates_csv": str(upstream_feedback.side_group_candidates_csv),
            "side_group_candidates_json": str(upstream_feedback.side_group_candidates_json),
            "side_group_endpoint_candidates_csv": str(upstream_feedback.side_group_endpoint_candidates_csv),
            "side_group_endpoint_candidates_json": str(upstream_feedback.side_group_endpoint_candidates_json),
            "pair_anchor_endpoint_clusters_csv": str(upstream_feedback.pair_anchor_endpoint_clusters_csv),
            "pair_anchor_endpoint_clusters_json": str(upstream_feedback.pair_anchor_endpoint_clusters_json),
            "segment_count": upstream_feedback.segment_count,
            "summary_count": upstream_feedback.summary_count,
            "relation_count": upstream_feedback.relation_count,
            "relation_summary_count": upstream_feedback.relation_summary_count,
            "side_group_candidate_count": upstream_feedback.side_group_candidate_count,
            "side_group_endpoint_candidate_count": upstream_feedback.side_group_endpoint_candidate_count,
            "pair_anchor_endpoint_cluster_count": upstream_feedback.pair_anchor_endpoint_cluster_count,
        },
        "t06_visual_check": {
            "summary_csv": str(visual_check["csv_path"]),
            "summary_json": str(visual_check["json_path"]),
            "case_count": len(visual_check["rows"]),
            "schema_version": visual_check["schema_version"],
        },
        "qa": _runner_qa(case_results),
    }
    summary = {
        "module_id": T10_MODULE_ID,
        "run_id": effective_run_id,
        "status": run_status,
        "package_dir": str(package_root),
        "run_root": str(run_root),
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "duration_seconds": duration_seconds,
        "case_count": len(case_results),
        "completed_case_count": len(case_results),
        "passed_case_count": sum(1 for item in case_results if item["overall_status"] == "passed"),
        "failed_case_count": sum(1 for item in case_results if item["overall_status"] == "failed"),
        "blocked_case_count": sum(1 for item in case_results if item["overall_status"] == "blocked"),
        "skipped_case_count": sum(1 for item in case_results if item["overall_status"] == "skipped"),
        "passed": run_status == "passed",
        "exit_on_incomplete": exit_on_incomplete,
        "upstream_feedback_segment_count": upstream_feedback.segment_count,
        "upstream_feedback_relation_count": upstream_feedback.relation_count,
        "upstream_feedback_summary_json": str(upstream_feedback.summary_json),
        "upstream_feedback_segments_csv": str(upstream_feedback.segments_csv),
        "upstream_feedback_relation_summary_json": str(upstream_feedback.relation_summary_json),
        "upstream_feedback_relations_csv": str(upstream_feedback.relations_csv),
        "upstream_side_group_candidate_count": upstream_feedback.side_group_candidate_count,
        "upstream_side_group_candidates_csv": str(upstream_feedback.side_group_candidates_csv),
        "upstream_side_group_endpoint_candidate_count": upstream_feedback.side_group_endpoint_candidate_count,
        "upstream_side_group_endpoint_candidates_csv": str(upstream_feedback.side_group_endpoint_candidates_csv),
        "upstream_pair_anchor_endpoint_cluster_count": upstream_feedback.pair_anchor_endpoint_cluster_count,
        "upstream_pair_anchor_endpoint_clusters_csv": str(upstream_feedback.pair_anchor_endpoint_clusters_csv),
        "t06_visual_check_summary_json": str(visual_check["json_path"]),
        "t06_visual_check_summary_csv": str(visual_check["csv_path"]),
        "t06_visual_check_case_count": len(visual_check["rows"]),
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
        upstream_feedback_summary_json=upstream_feedback.summary_json,
        upstream_feedback_segments_csv=upstream_feedback.segments_csv,
        upstream_feedback_relation_summary_json=upstream_feedback.relation_summary_json,
        upstream_feedback_relations_csv=upstream_feedback.relations_csv,
        upstream_side_group_candidates_csv=upstream_feedback.side_group_candidates_csv,
        upstream_side_group_endpoint_candidates_csv=upstream_feedback.side_group_endpoint_candidates_csv,
        upstream_pair_anchor_endpoint_clusters_csv=upstream_feedback.pair_anchor_endpoint_clusters_csv,
        t06_visual_check_summary_json=visual_check["json_path"],
        t06_visual_check_summary_csv=visual_check["csv_path"],
    )


def _run_t10_e2e_feedback_iterations_from_package(
    *,
    package_dir: str | Path,
    out_root: str | Path,
    run_id: str | None,
    case_ids: Sequence[str] | None,
    continue_on_error: bool,
    exit_on_incomplete: bool,
    feedback_iterations: int,
    t10_side_group_endpoint_candidates: str | Path | None,
    t10_pair_anchor_endpoint_clusters: str | Path | None,
) -> T10E2ECaseRunArtifacts:
    effective_run_id = run_id or _default_run_id()
    run_root = Path(out_root).expanduser().resolve() / effective_run_id
    iterations_root = run_root / "iterations"
    run_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    started_at = _now_text()
    current_side_group_candidates = _path_from(t10_side_group_endpoint_candidates)
    current_pair_anchor_clusters = _path_from(t10_pair_anchor_endpoint_clusters)
    iteration_records: list[dict[str, Any]] = []
    iteration_artifacts: list[T10E2ECaseRunArtifacts] = []

    for index in range(feedback_iterations + 1):
        role = "baseline" if index == 0 else f"feedback_{index}"
        iteration_run_id = f"iteration_{index:02d}_{role}"
        artifacts = run_t10_e2e_cases_from_package(
            package_dir=package_dir,
            out_root=iterations_root,
            run_id=iteration_run_id,
            case_ids=case_ids,
            stop_after=None,
            continue_on_error=continue_on_error,
            exit_on_incomplete=exit_on_incomplete,
            feedback_iterations=0,
            t10_side_group_endpoint_candidates=current_side_group_candidates,
            t10_pair_anchor_endpoint_clusters=current_pair_anchor_clusters,
        )
        summary = _read_json(artifacts.summary_json)
        record = {
            "iteration_index": index,
            "iteration_role": role,
            "run_id": iteration_run_id,
            "run_root": str(artifacts.run_root),
            "manifest_json": str(artifacts.manifest_json),
            "summary_json": str(artifacts.summary_json),
            "input_side_group_endpoint_candidates": (
                str(current_side_group_candidates) if current_side_group_candidates else ""
            ),
            "input_pair_anchor_endpoint_clusters": str(current_pair_anchor_clusters) if current_pair_anchor_clusters else "",
            "passed": bool(summary.get("passed")),
            "upstream_feedback_segment_count": summary.get("upstream_feedback_segment_count", 0),
            "upstream_side_group_endpoint_candidate_count": summary.get(
                "upstream_side_group_endpoint_candidate_count", 0
            ),
            "upstream_side_group_endpoint_candidates_csv": summary.get(
                "upstream_side_group_endpoint_candidates_csv", ""
            ),
            "upstream_pair_anchor_endpoint_cluster_count": summary.get(
                "upstream_pair_anchor_endpoint_cluster_count", 0
            ),
            "upstream_pair_anchor_endpoint_clusters_csv": summary.get(
                "upstream_pair_anchor_endpoint_clusters_csv", ""
            ),
            "t06_visual_check_summary_json": summary.get("t06_visual_check_summary_json", ""),
            "t06_visual_check_summary_csv": summary.get("t06_visual_check_summary_csv", ""),
            "t06_visual_check_case_count": summary.get("t06_visual_check_case_count", 0),
        }
        iteration_records.append(record)
        iteration_artifacts.append(artifacts)
        if index >= feedback_iterations or not summary.get("passed"):
            break
        has_side_group_output = int(summary.get("upstream_side_group_endpoint_candidate_count") or 0) > 0
        next_side_group_candidates = _path_from(summary.get("upstream_side_group_endpoint_candidates_csv"))
        next_pair_anchor_clusters_raw = _path_from(summary.get("upstream_pair_anchor_endpoint_clusters_csv"))
        if has_side_group_output and (not next_side_group_candidates or not next_side_group_candidates.is_file()):
            break
        next_pair_anchor_clusters: Path | None = None
        auto_pair_anchor_count = 0
        if next_pair_anchor_clusters_raw and next_pair_anchor_clusters_raw.is_file():
            next_pair_anchor_clusters, auto_pair_anchor_count = _write_auto_consumable_pair_anchor_clusters(
                next_pair_anchor_clusters_raw,
                run_root
                / "feedback_candidates"
                / f"iteration_{index:02d}_auto_pair_anchor_endpoint_clusters.csv",
            )
            record["auto_pair_anchor_endpoint_cluster_count"] = auto_pair_anchor_count
            record["auto_pair_anchor_endpoint_clusters_csv"] = str(next_pair_anchor_clusters) if next_pair_anchor_clusters else ""
        if not has_side_group_output and auto_pair_anchor_count <= 0:
            break
        changed_any = False
        if next_side_group_candidates and next_side_group_candidates.is_file():
            current_side_group_candidates, side_group_changed = _next_cumulative_feedback_file(
                current=current_side_group_candidates,
                new=next_side_group_candidates,
                out_path=run_root
                / "feedback_candidates"
                / f"iteration_{index:02d}_cumulative_side_group_endpoint_candidates.csv",
            )
            changed_any = changed_any or side_group_changed
            record["cumulative_side_group_endpoint_candidates_csv"] = (
                str(current_side_group_candidates) if current_side_group_candidates else ""
            )
        if next_pair_anchor_clusters and next_pair_anchor_clusters.is_file():
            current_pair_anchor_clusters, pair_anchor_changed = _next_cumulative_feedback_file(
                current=current_pair_anchor_clusters,
                new=next_pair_anchor_clusters,
                out_path=run_root
                / "feedback_candidates"
                / f"iteration_{index:02d}_cumulative_pair_anchor_endpoint_clusters.csv",
            )
            changed_any = changed_any or pair_anchor_changed
            record["cumulative_pair_anchor_endpoint_clusters_csv"] = (
                str(current_pair_anchor_clusters) if current_pair_anchor_clusters else ""
            )
        if not changed_any:
            record["feedback_stop_reason"] = "feedback_candidates_converged"
            break

    baseline_artifacts = iteration_artifacts[0]
    final_artifacts = iteration_artifacts[-1]
    final_summary = _read_json(final_artifacts.summary_json)
    final_status = str(final_summary.get("status") or ("passed" if final_summary.get("passed") else "failed"))
    comparison = _compare_feedback_iteration_outputs(
        baseline_run_root=baseline_artifacts.run_root,
        final_run_root=final_artifacts.run_root,
    )
    regression_guard_passed = (
        not comparison["removed_replaced_segment_ids"]
        and not comparison["removed_replacement_plan_segment_ids"]
    )
    run_status = final_status if regression_guard_passed else "failed"
    ended_at = _now_text()
    duration_seconds = round(time.perf_counter() - started, 6)
    manifest = {
        "module_id": T10_MODULE_ID,
        "runner": "run_t10_e2e_cases_from_package",
        "run_id": effective_run_id,
        "produced_at_utc": _now_text(),
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "duration_seconds": duration_seconds,
        "status": run_status,
        "passed": run_status == "passed",
        "package_dir": str(Path(package_dir).expanduser().resolve()),
        "run_root": str(run_root),
        "feedback_iteration_mode": True,
        "feedback_iteration_requested_count": feedback_iterations,
        "feedback_iteration_pass_count": len(iteration_records),
        "feedback_iteration_completed_count": max(0, len(iteration_records) - 1),
        "iterations": iteration_records,
        "final_iteration": iteration_records[-1],
        "feedback_comparison": comparison,
        "feedback_regression_guard_passed": regression_guard_passed,
        "qa": {
            "crs_and_transform": "Feedback iteration reuses T10 package inputs and does not transform geometry in T10.",
            "topology_silent_fix": False,
            "geometry_semantics": "Only endpoint-level side-group candidates and auto-consumable pair-anchor endpoint clusters are forwarded; segment endpoints are not merged into one junction.",
            "audit_traceability": "Each iteration keeps its own full T10 run manifest and stage outputs under iterations/.",
            "performance_verifiability": "Each iteration keeps stage timings; top-level manifest records iteration count and comparison.",
        },
    }
    summary = {
        "module_id": T10_MODULE_ID,
        "run_id": effective_run_id,
        "status": run_status,
        "package_dir": str(Path(package_dir).expanduser().resolve()),
        "run_root": str(run_root),
        "started_at_utc": started_at,
        "ended_at_utc": ended_at,
        "duration_seconds": duration_seconds,
        "feedback_iteration_mode": True,
        "feedback_iteration_requested_count": feedback_iterations,
        "feedback_iteration_pass_count": len(iteration_records),
        "feedback_iteration_completed_count": max(0, len(iteration_records) - 1),
        "feedback_regression_guard_passed": regression_guard_passed,
        "feedback_comparison": comparison,
        "case_count": final_summary.get("case_count", 0),
        "completed_case_count": final_summary.get("completed_case_count", final_summary.get("case_count", 0)),
        "passed_case_count": final_summary.get("passed_case_count", 0),
        "failed_case_count": final_summary.get("failed_case_count", 0),
        "blocked_case_count": final_summary.get("blocked_case_count", 0),
        "skipped_case_count": final_summary.get("skipped_case_count", 0),
        "passed": run_status == "passed",
        "exit_on_incomplete": exit_on_incomplete,
        "upstream_feedback_segment_count": final_summary.get("upstream_feedback_segment_count", 0),
        "upstream_feedback_relation_count": final_summary.get("upstream_feedback_relation_count", 0),
        "upstream_feedback_summary_json": final_summary.get("upstream_feedback_summary_json", ""),
        "upstream_feedback_segments_csv": final_summary.get("upstream_feedback_segments_csv", ""),
        "upstream_feedback_relation_summary_json": final_summary.get(
            "upstream_feedback_relation_summary_json", ""
        ),
        "upstream_feedback_relations_csv": final_summary.get("upstream_feedback_relations_csv", ""),
        "upstream_side_group_candidate_count": final_summary.get("upstream_side_group_candidate_count", 0),
        "upstream_side_group_candidates_csv": final_summary.get("upstream_side_group_candidates_csv", ""),
        "upstream_side_group_endpoint_candidate_count": final_summary.get(
            "upstream_side_group_endpoint_candidate_count", 0
        ),
        "upstream_side_group_endpoint_candidates_csv": final_summary.get(
            "upstream_side_group_endpoint_candidates_csv", ""
        ),
        "upstream_pair_anchor_endpoint_cluster_count": final_summary.get(
            "upstream_pair_anchor_endpoint_cluster_count", 0
        ),
        "upstream_pair_anchor_endpoint_clusters_csv": final_summary.get(
            "upstream_pair_anchor_endpoint_clusters_csv", ""
        ),
        "t06_visual_check_summary_json": final_summary.get("t06_visual_check_summary_json", ""),
        "t06_visual_check_summary_csv": final_summary.get("t06_visual_check_summary_csv", ""),
        "t06_visual_check_case_count": final_summary.get("t06_visual_check_case_count", 0),
    }
    manifest_path = run_root / "t10_e2e_run_manifest.json"
    summary_path = run_root / "t10_e2e_run_summary.json"
    _write_json(manifest_path, manifest)
    _write_json(summary_path, summary)
    return T10E2ECaseRunArtifacts(
        run_root=run_root,
        manifest_json=manifest_path,
        summary_json=summary_path,
        case_manifest_paths=final_artifacts.case_manifest_paths,
        t06_funnel_paths=final_artifacts.t06_funnel_paths,
        upstream_feedback_summary_json=final_artifacts.upstream_feedback_summary_json,
        upstream_feedback_segments_csv=final_artifacts.upstream_feedback_segments_csv,
        upstream_feedback_relation_summary_json=final_artifacts.upstream_feedback_relation_summary_json,
        upstream_feedback_relations_csv=final_artifacts.upstream_feedback_relations_csv,
        upstream_side_group_candidates_csv=final_artifacts.upstream_side_group_candidates_csv,
        upstream_side_group_endpoint_candidates_csv=final_artifacts.upstream_side_group_endpoint_candidates_csv,
        upstream_pair_anchor_endpoint_clusters_csv=final_artifacts.upstream_pair_anchor_endpoint_clusters_csv,
        t06_visual_check_summary_json=final_artifacts.t06_visual_check_summary_json,
        t06_visual_check_summary_csv=final_artifacts.t06_visual_check_summary_csv,
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
        feedback_iterations=args.feedback_iterations,
        t10_pair_anchor_endpoint_clusters=args.t10_pair_anchor_endpoint_clusters,
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
    side_group_endpoint_candidate_path: Path | None = None,
    pair_anchor_endpoint_cluster_path: Path | None = None,
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
                    side_group_endpoint_candidate_path=side_group_endpoint_candidate_path,
                    pair_anchor_endpoint_cluster_path=pair_anchor_endpoint_cluster_path,
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
        "status": overall_status,
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
        "status": overall_status,
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
    side_group_endpoint_candidate_path: Path | None = None,
    pair_anchor_endpoint_cluster_path: Path | None = None,
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
        return _run_t05(
            case_id,
            stage_dir,
            repo_root,
            python_bin,
            external_inputs,
            handoffs,
            side_group_endpoint_candidate_path=side_group_endpoint_candidate_path,
            pair_anchor_endpoint_cluster_path=pair_anchor_endpoint_cluster_path,
        )
    if stage_id == "t07_step3":
        return _run_t07_step3(case_id, stage_dir, repo_root, python_bin, handoffs)
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
        "rcsdnode": external_inputs.get("rcsdnode"),
    }
    missing = _missing_files(inputs)
    if missing:
        return _blocked_record("t07", stage_dir, "Missing T07 inputs.", inputs=inputs, missing=missing), {}
    env = {
        "NODES_PATH": str(inputs["t01_nodes"]),
        "DRIVEZONE_PATH": str(inputs["drivezone"]),
        "INTERSECTION_PATH": str(inputs["rcsd_intersection"]),
        "RCSDNODE_PATH": str(inputs["rcsdnode"]),
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
        "t03_nodes": _path_text(run_root / "nodes.gpkg"),
        "t03_surface": _path_text(run_root / "virtual_intersection_polygons.gpkg"),
        "t03_relation_evidence": _path_text(run_root / "t03_swsd_rcsd_relation_evidence.csv"),
        "t03_intersection_match": _path_text(run_root / "intersection_match_t03.geojson"),
    }
    np = _seg_noop("t03", case_id, stage_dir, record, inputs, produced)
    if np is not None:
        produced = np
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
        "t03_nodes": _path_from(handoffs.get("t03_nodes")),
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
        "NODES_PATH": str(inputs["t03_nodes"]),
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
        "t04_nodes": _path_text(run_root / "nodes.gpkg"),
        "final_swsd_nodes": _path_text(run_root / "nodes.gpkg"),
        "t04_surface": _path_text(run_root / "divmerge_virtual_anchor_surface.gpkg"),
        "t04_relation_evidence": _path_text(run_root / "t04_swsd_rcsd_relation_evidence.csv"),
        "t04_intersection_match": _path_text(run_root / "intersection_match_t04.geojson"),
        "t04_summary": _path_text(_first_existing(run_root, ("divmerge_virtual_anchor_surface_summary.json", "divmerge_virtual_anchor_surface_summary.csv"))),
        "t04_audit": _path_text(run_root / "divmerge_virtual_anchor_surface_audit.gpkg"),
        "t04_case_root": _path_text(run_root / "cases"),
    }
    np = _seg_noop("t04", case_id, stage_dir, record, inputs, produced)
    if np is not None:
        produced = np
    _attach_outputs(record, produced)
    return record, produced


def _run_t05(
    case_id: str,
    stage_dir: Path,
    repo_root: Path,
    python_bin: Path | str,
    external_inputs: Mapping[str, Path],
    handoffs: Mapping[str, str],
    *,
    side_group_endpoint_candidate_path: Path | None = None,
    pair_anchor_endpoint_cluster_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    inputs = {
        "final_swsd_nodes": _path_from(handoffs.get("final_swsd_nodes") or handoffs.get("t04_nodes")),
        "t07_surface": _path_from(handoffs.get("t07_surface")),
        "t07_relation_evidence": _path_from(handoffs.get("t07_relation_evidence")),
        "t03_surface": _path_from(handoffs.get("t03_surface")),
        "t03_relation_evidence": _path_from(handoffs.get("t03_relation_evidence")),
        "t04_surface": _path_from(handoffs.get("t04_surface")),
        "t04_relation_evidence": _path_from(handoffs.get("t04_relation_evidence")),
        "t04_summary": _path_from(handoffs.get("t04_summary")),
        "t04_audit": _path_from(handoffs.get("t04_audit")),
        "t10_side_group_endpoint_candidates": side_group_endpoint_candidate_path
        or _path_from(os.environ.get("T10_SIDE_GROUP_ENDPOINT_CANDIDATES")),
        "t10_pair_anchor_endpoint_clusters": pair_anchor_endpoint_cluster_path
        or _path_from(os.environ.get("T10_PAIR_ANCHOR_ENDPOINT_CLUSTERS")),
        "rcsdroad": external_inputs.get("rcsdroad"),
        "rcsdnode": external_inputs.get("rcsdnode"),
    }
    required_inputs = {
        key: value
        for key, value in inputs.items()
        if key
        not in {
            "t04_summary",
            "t04_audit",
            "t10_side_group_endpoint_candidates",
            "t10_pair_anchor_endpoint_clusters",
        }
    }
    missing = _missing_files(required_inputs)
    if missing:
        return _blocked_record("t05", stage_dir, "Missing T05 explicit file inputs.", inputs=inputs, missing=missing), {}
    t04_case_root = _path_from(handoffs.get("t04_case_root"))
    command = [
        str(python_bin),
        "scripts/t05_innernet_experiment.py",
        "--t07-input",
        str(inputs["t07_surface"]),
        "--t07-evidence",
        str(inputs["t07_relation_evidence"]),
        "--t03-surface",
        str(inputs["t03_surface"]),
        "--t03-evidence",
        str(inputs["t03_relation_evidence"]),
        "--t04-surface",
        str(inputs["t04_surface"]),
        "--t04-evidence",
        str(inputs["t04_relation_evidence"]),
        "--rcsdroad",
        str(inputs["rcsdroad"]),
        "--rcsdnode",
        str(inputs["rcsdnode"]),
        "--nodes",
        str(inputs["final_swsd_nodes"]),
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
    if inputs["t04_summary"] and inputs["t04_summary"].is_file():
        command.extend(["--t04-summary", str(inputs["t04_summary"])])
    if inputs["t04_audit"] and inputs["t04_audit"].is_file():
        command.extend(["--t04-audit", str(inputs["t04_audit"])])
    if t04_case_root and t04_case_root.is_dir():
        command.extend(["--t04-case-root", str(t04_case_root)])
    if inputs["t10_side_group_endpoint_candidates"] and inputs["t10_side_group_endpoint_candidates"].is_file():
        command.extend(["--t10-side-group-endpoint-candidates", str(inputs["t10_side_group_endpoint_candidates"])])
    if inputs["t10_pair_anchor_endpoint_clusters"] and inputs["t10_pair_anchor_endpoint_clusters"].is_file():
        command.extend(["--t10-pair-anchor-endpoint-clusters", str(inputs["t10_pair_anchor_endpoint_clusters"])])
    record = _execute_command("t05", stage_dir, repo_root, command, {}, inputs)
    if t04_case_root:
        record["execution_context"] = _paths_payload({"t04_case_root": t04_case_root})
    phase1_root = stage_dir / "t05_phase1"
    phase2_root = stage_dir / "t05_phase2"
    produced = {
        "t05_phase1_root": _path_text(phase1_root),
        "t05_phase2_root": _path_text(phase2_root),
        "t05_junction_surface": _path_text(phase1_root / "junction_anchor_surface.gpkg"),
        "t05_intersection_match_all": _path_text(phase2_root / "intersection_match_all.geojson"),
        "t05_rcsdroad_out": _path_text(phase2_root / "rcsdroad_out.gpkg"),
        "t05_rcsdnode_out": _path_text(phase2_root / "rcsdnode_out.gpkg"),
        "t05_phase2_summary": _path_text(phase2_root / "summary.json"),
    }
    _attach_outputs(record, produced)
    return record, produced


def _run_t07_step3(
    case_id: str,
    stage_dir: Path,
    repo_root: Path,
    python_bin: Path | str,
    handoffs: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    inputs = {
        "t07_nodes": _path_from(handoffs.get("t07_nodes")),
        "t05_intersection_match_all": _path_from(handoffs.get("t05_intersection_match_all")),
        "t05_rcsdnode_out": _path_from(handoffs.get("t05_rcsdnode_out")),
    }
    missing = _missing_files(inputs)
    if missing:
        return _blocked_record("t07_step3", stage_dir, "Missing T07 Step3 backfill inputs.", inputs=inputs, missing=missing), {}
    env = {
        "PYTHON_BIN": str(python_bin),
        "NODES_PATH": str(inputs["t07_nodes"]),
        "INTERSECTION_MATCH_ALL_PATH": str(inputs["t05_intersection_match_all"]),
        "RCSDNODE_PATH": str(inputs["t05_rcsdnode_out"]),
        "OUT_ROOT": str(stage_dir),
        "RUN_ID": "t07_step3",
    }
    record = _execute_command(
        "t07_step3",
        stage_dir,
        repo_root,
        ["bash", "scripts/t07_run_step3_intersection_match_innernet.sh"],
        env,
        inputs,
    )
    step3_root = stage_dir / "t07_step3" / "step3_intersection_match"
    produced = {
        "t07_step2_nodes": str(inputs["t07_nodes"]),
        "t07_step3_root": _path_text(step3_root),
        "t07_step3_nodes": _path_text(step3_root / "nodes.gpkg"),
        "t07_intersection_match_t07": _path_text(step3_root / "intersection_match_t07.geojson"),
        "t07_surface": _path_text(step3_root / "t07_rcsdintersection_anchor_surface.gpkg"),
        "t07_relation_evidence": _path_text(step3_root / "t07_swsd_rcsd_relation_evidence.csv"),
        "t07_step3_summary": _path_text(step3_root / "t07_step3_summary.json"),
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
        "final_swsd_nodes": _path_from(handoffs.get("final_swsd_nodes") or handoffs.get("t04_nodes")),
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
        str(inputs["final_swsd_nodes"]),
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
    t06_step2_replaceable = _path_from(handoffs.get("t06_step2_replaceable"))
    if (t06_run_root is None or not t06_run_root.is_dir()) and t06_step2_replaceable is not None:
        t06_run_root = t06_step2_replaceable.parent.parent
    inputs = {
        "t06_step2_replaceable": t06_step2_replaceable,
        "t01_segment": _path_from(handoffs.get("t01_segment")),
        "t01_roads": _path_from(handoffs.get("t01_roads")),
        "final_swsd_nodes": _path_from(handoffs.get("final_swsd_nodes") or handoffs.get("t04_nodes")),
        "t05_rcsdroad_out": _path_from(handoffs.get("t05_rcsdroad_out")),
        "t05_rcsdnode_out": _path_from(handoffs.get("t05_rcsdnode_out")),
        "t07_surface": _path_from(handoffs.get("t07_surface")),
        "t03_surface": _path_from(handoffs.get("t03_surface")),
        "t04_surface": _path_from(handoffs.get("t04_surface")),
        "t04_audit": _path_from(handoffs.get("t04_audit")),
        "t05_junction_surface": _path_from(handoffs.get("t05_junction_surface")),
    }
    required_inputs = {key: inputs[key] for key in ("t06_step2_replaceable", "t01_segment", "t01_roads", "final_swsd_nodes", "t05_rcsdroad_out", "t05_rcsdnode_out")}
    missing = _missing_files(required_inputs)
    if missing:
        return _blocked_record("t06_step3", stage_dir, "Missing T06 Step3 inputs.", inputs=inputs, missing=missing), {}
    if t06_run_root is None or not t06_run_root.is_dir():
        return _blocked_record("t06_step3", stage_dir, "Missing T06 Step3 execution context.", inputs=inputs, missing=["t06_run_root"]), {}
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
        str(inputs["final_swsd_nodes"]),
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
    for arg_name, input_key in (
        ("--t07-surface", "t07_surface"),
        ("--t03-surface", "t03_surface"),
        ("--t04-surface", "t04_surface"),
        ("--t04-audit", "t04_audit"),
        ("--t05-surface", "t05_junction_surface"),
    ):
        value = inputs.get(input_key)
        if value and value.is_file():
            command.extend([arg_name, str(value)])
    command.append("--surface-topology-closure")
    record = _execute_command("t06_step3", stage_dir, repo_root, command, {}, inputs)
    record["execution_context"] = _paths_payload({"t06_run_root": t06_run_root})
    step3_root = t06_run_root / "step3_segment_replacement"
    has_surface_inputs = any(inputs.get(key) for key in ("t07_surface", "t03_surface", "t04_surface", "t04_audit", "t05_junction_surface"))
    produced = {
        "t06_step3_root": _path_text(step3_root),
        "t06_frcsd_road": _path_text(step3_root / "t06_frcsd_road.gpkg"),
        "t06_frcsd_node": _path_text(step3_root / "t06_frcsd_node.gpkg"),
        "t06_swsd_frcsd_segment_relation": _path_text(step3_root / "t06_step3_swsd_frcsd_segment_relation.gpkg"),
        "t06_topology_connectivity_audit": _path_text(step3_root / "t06_step3_topology_connectivity_audit.gpkg"),
        "t06_step3_summary": _path_text(step3_root / "t06_step3_summary.json"),
    }
    if has_surface_inputs:
        produced["t06_surface_topology_audit"] = _path_text(step3_root / "t06_step3_surface_topology_audit.gpkg")
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
        "final_swsd_nodes": _path_from(handoffs.get("final_swsd_nodes") or handoffs.get("t04_nodes")),
        "t01_roads": _path_from(handoffs.get("t01_roads")),
        "t01_segment": _path_from(handoffs.get("t01_segment")),
        "sw_restriction_tool7": external_inputs.get("sw_restriction_tool7"),
        "sw_arrow_tool8": external_inputs.get("sw_arrow_tool8"),
    }
    required = {key: value for key, value in inputs.items() if key in {"final_swsd_nodes", "t01_roads", "t01_segment"}}
    missing = _missing_files(required)
    if missing:
        return _blocked_record("t09_step12", stage_dir, "Missing T09 Step1/2 inputs.", inputs=inputs, missing=missing), {}
    env = {
        "T09_SWNODE": str(inputs["final_swsd_nodes"]),
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


def _stage_limit(stop_after: str | None) -> int:
    if not stop_after:
        return len(T10_E2E_STAGE_ORDER)
    normalized = str(stop_after).strip()
    if normalized not in T10_E2E_STAGE_ORDER:
        raise ValueError(f"stop_after must be one of {', '.join(T10_E2E_STAGE_ORDER)}.")
    return T10_E2E_STAGE_ORDER.index(normalized) + 1


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
    parser.add_argument("--stop-after", choices=T10_E2E_STAGE_ORDER, default=None)
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
