from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import case_runner as _facade


def T10E2ECaseRunArtifacts(*args: Any, **kwargs: Any) -> Any:
    return _facade.T10E2ECaseRunArtifacts(*args, **kwargs)


def _attach_outputs(*args: Any, **kwargs: Any) -> Any:
    return _facade._attach_outputs(*args, **kwargs)


def _blocked_record(*args: Any, **kwargs: Any) -> Any:
    return _facade._blocked_record(*args, **kwargs)


def _case_id_from_manifest(*args: Any, **kwargs: Any) -> Any:
    return _facade._case_id_from_manifest(*args, **kwargs)


def _compare_feedback_iteration_outputs(*args: Any, **kwargs: Any) -> Any:
    return _facade._compare_feedback_iteration_outputs(*args, **kwargs)


def _default_run_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._default_run_id(*args, **kwargs)


def _discover_case_dirs(*args: Any, **kwargs: Any) -> Any:
    return _facade._discover_case_dirs(*args, **kwargs)


def _exception_record(*args: Any, **kwargs: Any) -> Any:
    return _facade._exception_record(*args, **kwargs)


def _execute_command(*args: Any, **kwargs: Any) -> Any:
    return _facade._execute_command(*args, **kwargs)


def _external_input_paths(*args: Any, **kwargs: Any) -> Any:
    return _facade._external_input_paths(*args, **kwargs)


def _first_existing(*args: Any, **kwargs: Any) -> Any:
    return _facade._first_existing(*args, **kwargs)


def _missing_files(*args: Any, **kwargs: Any) -> Any:
    return _facade._missing_files(*args, **kwargs)


def _next_cumulative_feedback_file(*args: Any, **kwargs: Any) -> Any:
    return _facade._next_cumulative_feedback_file(*args, **kwargs)


def _now_text(*args: Any, **kwargs: Any) -> Any:
    return _facade._now_text(*args, **kwargs)


def _overall_case_status(*args: Any, **kwargs: Any) -> Any:
    return _facade._overall_case_status(*args, **kwargs)


def _overall_run_status(*args: Any, **kwargs: Any) -> Any:
    return _facade._overall_run_status(*args, **kwargs)


def _parse_args(*args: Any, **kwargs: Any) -> Any:
    return _facade._parse_args(*args, **kwargs)


def _path_from(*args: Any, **kwargs: Any) -> Any:
    return _facade._path_from(*args, **kwargs)


def _path_text(*args: Any, **kwargs: Any) -> Any:
    return _facade._path_text(*args, **kwargs)


def _paths_payload(*args: Any, **kwargs: Any) -> Any:
    return _facade._paths_payload(*args, **kwargs)


def _prefer_path(*args: Any, **kwargs: Any) -> Any:
    return _facade._prefer_path(*args, **kwargs)


def _python_bin(*args: Any, **kwargs: Any) -> Any:
    return _facade._python_bin(*args, **kwargs)


def _read_json(*args: Any, **kwargs: Any) -> Any:
    return _facade._read_json(*args, **kwargs)


def _repo_root(*args: Any, **kwargs: Any) -> Any:
    return _facade._repo_root(*args, **kwargs)


def _runner_qa(*args: Any, **kwargs: Any) -> Any:
    return _facade._runner_qa(*args, **kwargs)


def _safe_case_id(*args: Any, **kwargs: Any) -> Any:
    return _facade._safe_case_id(*args, **kwargs)


def _seg_noop(*args: Any, **kwargs: Any) -> Any:
    return _facade._seg_noop(*args, **kwargs)


def _stage_limit(*args: Any, **kwargs: Any) -> Any:
    return _facade._stage_limit(*args, **kwargs)


def _write_auto_consumable_pair_anchor_clusters(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_auto_consumable_pair_anchor_clusters(*args, **kwargs)


def _write_json(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_json(*args, **kwargs)


def _write_t06_funnel(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_t06_funnel(*args, **kwargs)


def _write_t06_visual_check_summary(*args: Any, **kwargs: Any) -> Any:
    return _facade._write_t06_visual_check_summary(*args, **kwargs)


def write_t10_upstream_feedback(*args: Any, **kwargs: Any) -> Any:
    return _facade.write_t10_upstream_feedback(*args, **kwargs)


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
        case_result = _facade._run_one_case(
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
        "module_id": _facade.T10_MODULE_ID,
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
        "chain": list(_facade.T10_V1_CHAIN),
        "stage_order": list(_facade.T10_E2E_STAGE_ORDER[:stage_limit]),
        "t08_policy": _facade.T10_T08_POLICY,
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
        "module_id": _facade.T10_MODULE_ID,
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
        "module_id": _facade.T10_MODULE_ID,
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
        "module_id": _facade.T10_MODULE_ID,
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
    for stage_id in _facade.T10_E2E_STAGE_ORDER[:stage_limit]:
        stage_dir = case_run_dir / stage_id
        if blocked:
            record = _blocked_record(stage_id, stage_dir, "Previous stage did not produce required handoff.")
        else:
            try:
                record, produced = _facade._run_stage(
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
        "module_id": _facade.T10_MODULE_ID,
        "runner": "run_t10_e2e_cases_from_package",
        "case_id": case_id,
        "status": overall_status,
        "case_dir": str(case_dir),
        "package_root": str(package_root),
        "case_run_dir": str(case_run_dir),
        "produced_at_utc": _now_text(),
        "stage_order": list(_facade.T10_E2E_STAGE_ORDER[:stage_limit]),
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
        "module_id": _facade.T10_MODULE_ID,
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
    if stage_id == "t11":
        return _facade._run_t11(case_id, case_run_dir, stage_dir, repo_root, python_bin, handoffs)
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
    produced = _seg_noop("t07", case_id, stage_dir, record, inputs, produced) or produced
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
        "WORKERS": os.environ.get("T10_T03_WORKERS", str(min(16, os.cpu_count() or 1))),
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
    produced = _seg_noop("t03", case_id, stage_dir, record, inputs, produced) or produced
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
    produced = _seg_noop("t04", case_id, stage_dir, record, inputs, produced) or produced
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
    command = [str(python_bin), "-c", _facade._T09_STEP12_CODE]
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
    command = [str(python_bin), "-c", _facade._T09_STEP3_CODE]
    record = _execute_command("t09_step3", stage_dir, repo_root, command, env, inputs)
    run_root = stage_dir / "t09_step3"
    produced = {
        "t09_step3_root": _path_text(run_root),
        "t09_frcsd_restriction": _path_text(run_root / "frcsd_restriction.gpkg"),
        "t09_step3_summary": _path_text(run_root / "t09_step3_frcsd_restriction_summary.json"),
    }
    _attach_outputs(record, produced)
    return record, produced
