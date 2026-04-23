from __future__ import annotations

import shutil
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import build_run_id, normalize_runtime_path, write_json

from .final_publish import T04Step7CaseArtifact, write_step7_batch_outputs
from .full_input_bootstrap import (
    build_preflight_doc,
    validate_full_input_paths,
    write_bootstrap_artifacts,
    write_candidate_artifacts,
)
from .full_input_case_pipeline import run_single_case_direct
from .full_input_observability import (
    build_performance_snapshot,
    now_text,
    write_case_watch_status,
    write_root_failure,
    write_root_progress,
)
from .full_input_perf_audit import (
    DEFAULT_PERF_AUDIT_INTERVAL_SEC,
    DEFAULT_PERF_AUDIT_MAX_BYTES,
    DEFAULT_PERF_AUDIT_MAX_SAMPLES,
    T04PerfAuditRecorder,
)
from .full_input_shared_layers import (
    discover_candidate_case_ids,
    load_shared_full_input_layers,
    select_candidate_case_ids,
)
from .full_input_streamed_results import (
    append_streamed_case_result,
    materialize_final_visual_checks,
    runtime_failed_terminal_case_record,
    streamed_case_results_path,
    terminal_case_record_from_artifact,
    write_terminal_case_record,
)


DEFAULT_OUT_ROOT = Path("/mnt/e/Work/RCSD_Topo_Poc/outputs/_work/t04_internal_full_input")
DEFAULT_LOCAL_QUERY_BUFFER_M = 360.0
DEFAULT_PROGRESS_FLUSH_INTERVAL_SEC = 5.0
DEFAULT_PROGRESS_FLUSH_INTERVAL_CASES = 5
DEFAULT_LOCAL_CONTEXT_SNAPSHOT_MODE = "failed_only"


@dataclass(frozen=True)
class T04InternalFullInputArtifacts:
    run_root: Path
    selected_case_ids: list[str]
    accepted_count: int
    rejected_count: int
    runtime_failed_count: int
    visual_check_dir: Path
    summary_path: Path


def _optional_path(value: str | Path | None) -> Path | None:
    return normalize_runtime_path(value) if value is not None else None


def _progress_snapshot(
    *,
    started_perf: float,
    selected_case_ids: list[str],
    running_case_ids: set[str],
    completed_case_count: int,
    accepted_case_count: int,
    rejected_case_count: int,
    runtime_failed_case_count: int,
    missing_status_case_count: int,
    case_elapsed_total_seconds: float,
    last_completed_case_id: str | None,
    last_completed_at: str | None,
) -> dict[str, Any]:
    performance = build_performance_snapshot(
        started_perf=started_perf,
        now_perf=perf_counter(),
        completed_case_count=completed_case_count,
        running_case_count=len(running_case_ids),
        selected_case_count=len(selected_case_ids),
        case_elapsed_total_seconds=case_elapsed_total_seconds,
    )
    return {
        "completed_case_count": completed_case_count,
        "running_case_ids": sorted(running_case_ids),
        "accepted_case_count": accepted_case_count,
        "rejected_case_count": rejected_case_count,
        "runtime_failed_case_count": runtime_failed_case_count,
        "missing_status_case_count": missing_status_case_count,
        "performance": performance,
        "last_completed_case_id": last_completed_case_id,
        "last_completed_at": last_completed_at,
    }


def _write_summary(
    *,
    run_root: Path,
    selected_case_ids: list[str],
    discovered_case_ids: list[str],
    artifacts: list[T04Step7CaseArtifact],
    runtime_failed_case_ids: list[str],
    candidate_artifacts: dict[str, str],
    bootstrap_artifacts: dict[str, str],
    step7_outputs: dict[str, Any],
    visual_outputs: dict[str, Any],
    rerun_cleaned_before_write: bool,
    resume_requested: bool,
    retry_failed_requested: bool,
    performance: dict[str, Any],
) -> Path:
    final_state_by_case = {artifact.case_id: artifact.final_state for artifact in artifacts}
    missing_status_case_ids = [
        case_id for case_id in selected_case_ids
        if case_id not in final_state_by_case and case_id not in set(runtime_failed_case_ids)
    ]
    summary = {
        "updated_at": now_text(),
        "run_root": str(run_root),
        "cases_dir": str(run_root / "cases"),
        "selected_case_count": len(selected_case_ids),
        "selected_case_ids": list(selected_case_ids),
        "raw_case_count": len(discovered_case_ids),
        "raw_case_ids": list(discovered_case_ids),
        "completed_case_count": len(artifacts) + len(runtime_failed_case_ids),
        "accepted_count": sum(1 for item in artifacts if item.final_state == "accepted"),
        "rejected_count": sum(1 for item in artifacts if item.final_state == "rejected"),
        "runtime_failed_count": len(runtime_failed_case_ids),
        "runtime_failed_case_ids": list(runtime_failed_case_ids),
        "missing_status_count": len(missing_status_case_ids),
        "missing_status_case_ids": missing_status_case_ids,
        "rerun_cleaned_before_write": rerun_cleaned_before_write,
        "resume_requested": resume_requested,
        "retry_failed_requested": retry_failed_requested,
        "performance": dict(performance),
        **candidate_artifacts,
        **bootstrap_artifacts,
        "step7_accepted_layer": step7_outputs.get("accepted_layer_path"),
        "step7_rejected_layer": step7_outputs.get("rejected_layer_path"),
        "step7_audit_layer": step7_outputs.get("audit_layer_path"),
        "step7_summary_csv": step7_outputs.get("summary_csv_path"),
        "step7_summary_json": step7_outputs.get("summary_json_path"),
        "step7_rejected_index_csv": step7_outputs.get("rejected_index_csv_path"),
        "step7_rejected_index_json": step7_outputs.get("rejected_index_json_path"),
        "step7_consistency_report": step7_outputs.get("consistency_report_path"),
        **visual_outputs,
    }
    summary_path = run_root / "summary.json"
    write_json(summary_path, summary)
    return summary_path


def run_t04_internal_full_input(
    *,
    nodes_path: str | Path,
    roads_path: str | Path,
    drivezone_path: str | Path,
    divstripzone_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path = DEFAULT_OUT_ROOT,
    run_id: str | None = None,
    workers: int = 8,
    max_cases: int | None = None,
    debug: bool = False,
    visual_check_dir: str | Path | None = None,
    resume: bool = True,
    retry_failed: bool = True,
    perf_audit: bool = True,
    perf_audit_interval_sec: int = DEFAULT_PERF_AUDIT_INTERVAL_SEC,
    perf_audit_max_samples: int = DEFAULT_PERF_AUDIT_MAX_SAMPLES,
    perf_audit_max_bytes: int = DEFAULT_PERF_AUDIT_MAX_BYTES,
    progress_flush_interval_sec: float = DEFAULT_PROGRESS_FLUSH_INTERVAL_SEC,
    progress_flush_interval_cases: int = DEFAULT_PROGRESS_FLUSH_INTERVAL_CASES,
    local_context_snapshot_mode: str = DEFAULT_LOCAL_CONTEXT_SNAPSHOT_MODE,
    local_query_buffer_m: float = DEFAULT_LOCAL_QUERY_BUFFER_M,
    nodes_layer: str | None = None,
    roads_layer: str | None = None,
    drivezone_layer: str | None = None,
    divstripzone_layer: str | None = None,
    rcsdroad_layer: str | None = None,
    rcsdnode_layer: str | None = None,
    nodes_crs: str | None = None,
    roads_crs: str | None = None,
    drivezone_crs: str | None = None,
    divstripzone_crs: str | None = None,
    rcsdroad_crs: str | None = None,
    rcsdnode_crs: str | None = None,
) -> T04InternalFullInputArtifacts:
    resolved_run_id = run_id or build_run_id("t04_internal_full_input")
    resolved_out_root = normalize_runtime_path(out_root)
    run_root = resolved_out_root / resolved_run_id
    resolved_visual_check_dir = _optional_path(visual_check_dir) or (run_root / "visual_checks")
    input_paths = {
        "nodes_path": normalize_runtime_path(nodes_path),
        "roads_path": normalize_runtime_path(roads_path),
        "drivezone_path": normalize_runtime_path(drivezone_path),
        "divstripzone_path": normalize_runtime_path(divstripzone_path),
        "rcsdroad_path": normalize_runtime_path(rcsdroad_path),
        "rcsdnode_path": normalize_runtime_path(rcsdnode_path),
    }
    max_workers = max(1, int(workers or 1))
    rerun_cleaned_before_write = False
    if run_root.exists() and not (resume or retry_failed):
        shutil.rmtree(run_root)
        rerun_cleaned_before_write = True
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "cases").mkdir(parents=True, exist_ok=True)
    (run_root / "case_logs").mkdir(parents=True, exist_ok=True)
    resolved_visual_check_dir.mkdir(parents=True, exist_ok=True)

    if resume and (run_root / "summary.json").is_file() and not retry_failed:
        summary_doc = {}
        try:
            import json

            summary_doc = json.loads((run_root / "summary.json").read_text(encoding="utf-8"))
        except Exception:
            summary_doc = {}
        return T04InternalFullInputArtifacts(
            run_root=run_root,
            selected_case_ids=[str(value) for value in summary_doc.get("selected_case_ids", [])],
            accepted_count=int(summary_doc.get("accepted_count", 0)),
            rejected_count=int(summary_doc.get("rejected_count", 0)),
            runtime_failed_count=int(summary_doc.get("runtime_failed_count", 0)),
            visual_check_dir=resolved_visual_check_dir,
            summary_path=run_root / "summary.json",
        )

    started_perf = perf_counter()
    selected_case_ids: list[str] = []
    discovered_case_ids: list[str] = []
    artifacts: list[T04Step7CaseArtifact] = []
    runtime_failed_case_ids: list[str] = []
    progress_lock = Lock()
    stream_lock = Lock()
    running_case_ids: set[str] = set()
    completed_case_count = 0
    accepted_case_count = 0
    rejected_case_count = 0
    runtime_failed_case_count = 0
    missing_status_case_count = 0
    case_elapsed_total_seconds = 0.0
    last_completed_case_id: str | None = None
    last_completed_at: str | None = None

    def _flush_progress(phase: str, status: str, message: str, *, force: bool = False) -> None:
        nonlocal last_completed_case_id, last_completed_at
        snapshot = _progress_snapshot(
            started_perf=started_perf,
            selected_case_ids=selected_case_ids,
            running_case_ids=running_case_ids,
            completed_case_count=completed_case_count,
            accepted_case_count=accepted_case_count,
            rejected_case_count=rejected_case_count,
            runtime_failed_case_count=runtime_failed_case_count,
            missing_status_case_count=missing_status_case_count,
            case_elapsed_total_seconds=case_elapsed_total_seconds,
            last_completed_case_id=last_completed_case_id,
            last_completed_at=last_completed_at,
        )
        write_root_progress(
            run_root=run_root,
            phase=phase,
            status=status,
            message=message,
            selected_case_ids=selected_case_ids,
            entered_case_execution=phase in {"direct_case_execution", "batch_closeout", "completed"},
            **snapshot,
        )
        if force:
            perf_recorder.maybe_sample(snapshot, force=True)

    perf_recorder = T04PerfAuditRecorder(
        enabled=perf_audit,
        run_root=run_root,
        run_id=resolved_run_id,
        workers=max_workers,
        sample_interval_sec=perf_audit_interval_sec,
        max_samples=perf_audit_max_samples,
        max_bytes=perf_audit_max_bytes,
    )

    try:
        _flush_progress("preflight", "running", "checking input files and output root")
        path_check_doc = validate_full_input_paths(
            input_paths=input_paths,
            out_root=resolved_out_root,
            run_root=run_root,
        )

        _flush_progress("shared_bootstrap", "running", "loading shared full-input layers once")
        bootstrap_started = perf_counter()
        shared_layers = load_shared_full_input_layers(
            **input_paths,
            nodes_layer=nodes_layer,
            roads_layer=roads_layer,
            drivezone_layer=drivezone_layer,
            divstripzone_layer=divstripzone_layer,
            rcsdroad_layer=rcsdroad_layer,
            rcsdnode_layer=rcsdnode_layer,
            nodes_crs=nodes_crs,
            roads_crs=roads_crs,
            drivezone_crs=drivezone_crs,
            divstripzone_crs=divstripzone_crs,
            rcsdroad_crs=rcsdroad_crs,
            rcsdnode_crs=rcsdnode_crs,
        )
        bootstrap_seconds = perf_counter() - bootstrap_started

        _flush_progress("candidate_discovery", "running", "discovering T04 candidate mainnodeids once")
        discovered_case_ids = discover_candidate_case_ids(shared_layers)
        selected_case_ids = select_candidate_case_ids(
            discovered_case_ids=discovered_case_ids,
            max_cases=max_cases,
        )
        if not selected_case_ids:
            raise ValueError("No eligible T04 candidates were discovered.")

        preflight_doc = build_preflight_doc(
            input_paths=input_paths,
            out_root=resolved_out_root,
            run_root=run_root,
            visual_check_dir=resolved_visual_check_dir,
            path_check_doc=path_check_doc,
            shared_layers=shared_layers,
            discovered_case_ids=discovered_case_ids,
            selected_case_ids=selected_case_ids,
            max_cases=max_cases,
            workers=max_workers,
            resume_requested=resume,
            retry_failed_requested=retry_failed,
        )
        write_json(run_root / "preflight.json", preflight_doc)
        candidate_artifacts = write_candidate_artifacts(
            run_root=run_root,
            discovered_case_ids=discovered_case_ids,
            selected_case_ids=selected_case_ids,
        )
        bootstrap_artifacts = write_bootstrap_artifacts(
            run_root=run_root,
            shared_layers=shared_layers,
            bootstrap_seconds=bootstrap_seconds,
        )

        _flush_progress("direct_case_execution", "running", "executing T04 Step1-7 per case")
        artifact_lock = Lock()
        stream_path = streamed_case_results_path(run_root)

        def _execute(case_id: str) -> None:
            nonlocal completed_case_count
            nonlocal accepted_case_count
            nonlocal rejected_case_count
            nonlocal runtime_failed_case_count
            nonlocal missing_status_case_count
            nonlocal case_elapsed_total_seconds
            nonlocal last_completed_case_id
            nonlocal last_completed_at
            case_started = perf_counter()
            with progress_lock:
                running_case_ids.add(case_id)
                _flush_progress("direct_case_execution", "running", f"case {case_id} started")
            write_case_watch_status(
                run_root=run_root,
                case_id=case_id,
                state="running",
                current_stage="direct_case_execution",
                reason="case_started",
                detail="executing Step1-7 from shared full-input layers",
            )
            try:
                result = run_single_case_direct(
                    case_id=case_id,
                    shared_layers=shared_layers,
                    input_paths=input_paths,
                    run_root=run_root,
                    local_query_buffer_m=local_query_buffer_m,
                )
                artifact = result["step7_artifact"]
                record = terminal_case_record_from_artifact(run_root=run_root, artifact=artifact)
                write_terminal_case_record(run_root=run_root, record=record)
                with stream_lock:
                    append_streamed_case_result(stream_path, record)
                with artifact_lock:
                    artifacts.append(artifact)
                final_state = artifact.final_state
                reject_reason = str(artifact.reject_reasons[0]) if artifact.reject_reasons else ""
                elapsed = perf_counter() - case_started
                perf_recorder.record_case_result(
                    case_id=case_id,
                    elapsed_seconds=elapsed,
                    final_state=final_state,
                    reason=reject_reason,
                )
                write_case_watch_status(
                    run_root=run_root,
                    case_id=case_id,
                    state=final_state,
                    current_stage="completed",
                    reason=reject_reason or final_state,
                    detail="case Step1-7 completed",
                    selected_counts=result["selected_counts"],
                    stage_timers=result["stage_timers"],
                )
                with progress_lock:
                    running_case_ids.discard(case_id)
                    completed_case_count += 1
                    accepted_case_count += 1 if final_state == "accepted" else 0
                    rejected_case_count += 1 if final_state == "rejected" else 0
                    case_elapsed_total_seconds += max(elapsed, 0.0)
                    last_completed_case_id = case_id
                    last_completed_at = now_text()
                    should_flush = (
                        completed_case_count % max(1, int(progress_flush_interval_cases)) == 0
                    )
                    _flush_progress(
                        "direct_case_execution",
                        "running",
                        f"case {case_id} completed with final_state={final_state}",
                        force=should_flush,
                    )
            except Exception as exc:
                elapsed = perf_counter() - case_started
                detail = f"{type(exc).__name__}: {exc}"
                record = runtime_failed_terminal_case_record(
                    run_root=run_root,
                    case_id=case_id,
                    reason="runtime_failed",
                    detail=detail,
                )
                write_terminal_case_record(run_root=run_root, record=record)
                with stream_lock:
                    append_streamed_case_result(stream_path, record)
                perf_recorder.record_case_result(
                    case_id=case_id,
                    elapsed_seconds=elapsed,
                    final_state="runtime_failed",
                    reason=detail,
                )
                write_case_watch_status(
                    run_root=run_root,
                    case_id=case_id,
                    state="runtime_failed",
                    current_stage="direct_case_execution",
                    reason="runtime_failed",
                    detail=detail,
                )
                if local_context_snapshot_mode in {"all", "failed_only"}:
                    write_json(
                        run_root / "cases" / str(case_id) / "local_context_snapshot.json",
                        {"case_id": str(case_id), "snapshot_mode": local_context_snapshot_mode, "failure": detail},
                    )
                with progress_lock:
                    running_case_ids.discard(case_id)
                    completed_case_count += 1
                    runtime_failed_case_count += 1
                    runtime_failed_case_ids.append(case_id)
                    case_elapsed_total_seconds += max(elapsed, 0.0)
                    last_completed_case_id = case_id
                    last_completed_at = now_text()
                    _flush_progress(
                        "direct_case_execution",
                        "running",
                        f"case {case_id} runtime_failed",
                        force=True,
                    )

        if max_workers == 1 or len(selected_case_ids) <= 1:
            for case_id in selected_case_ids:
                _execute(case_id)
        else:
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="t04-full-input") as executor:
                futures = {executor.submit(_execute, case_id): case_id for case_id in selected_case_ids}
                for future in as_completed(futures):
                    future.result()

        _flush_progress("batch_closeout", "running", "writing Step7 batch outputs and final visual checks")
        ordered_artifacts = sorted(artifacts, key=lambda item: item.case_id)
        step7_outputs = write_step7_batch_outputs(run_root=run_root, artifacts=ordered_artifacts)
        visual_outputs = materialize_final_visual_checks(
            run_root=run_root,
            artifacts=ordered_artifacts,
            visual_check_dir=resolved_visual_check_dir,
        )
        final_snapshot = _progress_snapshot(
            started_perf=started_perf,
            selected_case_ids=selected_case_ids,
            running_case_ids=running_case_ids,
            completed_case_count=completed_case_count,
            accepted_case_count=accepted_case_count,
            rejected_case_count=rejected_case_count,
            runtime_failed_case_count=runtime_failed_case_count,
            missing_status_case_count=missing_status_case_count,
            case_elapsed_total_seconds=case_elapsed_total_seconds,
            last_completed_case_id=last_completed_case_id,
            last_completed_at=last_completed_at,
        )
        summary_path = _write_summary(
            run_root=run_root,
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            artifacts=ordered_artifacts,
            runtime_failed_case_ids=runtime_failed_case_ids,
            candidate_artifacts=candidate_artifacts,
            bootstrap_artifacts=bootstrap_artifacts,
            step7_outputs=step7_outputs,
            visual_outputs=visual_outputs,
            rerun_cleaned_before_write=rerun_cleaned_before_write,
            resume_requested=resume,
            retry_failed_requested=retry_failed,
            performance=final_snapshot["performance"],
        )
        perf_recorder.write_summary(final_snapshot=final_snapshot)
        _flush_progress("completed", "completed", "T04 internal full-input execution completed", force=True)
        return T04InternalFullInputArtifacts(
            run_root=run_root,
            selected_case_ids=selected_case_ids,
            accepted_count=accepted_case_count,
            rejected_count=rejected_case_count,
            runtime_failed_count=runtime_failed_case_count,
            visual_check_dir=resolved_visual_check_dir,
            summary_path=summary_path,
        )
    except Exception as exc:
        write_root_failure(
            run_root=run_root,
            phase="failed",
            failure=f"{type(exc).__name__}: {exc}",
            traceback_text=traceback.format_exc(),
            selected_case_ids=selected_case_ids,
        )
        write_root_progress(
            run_root=run_root,
            phase="failed",
            status="failed",
            message=f"{type(exc).__name__}: {exc}",
            selected_case_ids=selected_case_ids,
            runtime_failed_case_count=len(runtime_failed_case_ids),
            entered_case_execution=bool(selected_case_ids),
        )
        raise


__all__ = [
    "DEFAULT_LOCAL_QUERY_BUFFER_M",
    "T04InternalFullInputArtifacts",
    "run_t04_internal_full_input",
]
