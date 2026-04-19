from __future__ import annotations

import os
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
    sort_patch_key,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_loader import (
    DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_case_pipeline import (
    run_single_case_direct,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_bootstrap import (
    build_full_input_preflight_doc,
    build_shared_memory_summary,
    build_step3_preflight_doc,
    select_candidate_case_ids,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_observability import (
    RUNTIME_STAGE_TIMER_KEYS,
    accumulate_duration,
    internal_observability_paths,
    now_text,
    write_case_watch_status,
    write_internal_case_progress,
    write_internal_failure,
    write_internal_manifest,
    write_internal_performance,
    write_internal_progress,
    write_json_atomic,
    write_local_context_snapshot,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_perf_audit import (
    DEFAULT_PERF_AUDIT_INTERVAL_SEC,
    DEFAULT_PERF_AUDIT_MAX_BYTES,
    DEFAULT_PERF_AUDIT_MAX_SAMPLES,
    T03PerfAuditRecorder,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_shared_layers import (
    discover_candidate_case_ids,
    feature_id,
    feature_mainnodeid,
    load_shared_layers,
    load_shared_nodes,
    stable_case_ids,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.t03_batch_closeout import (
    T03_REVIEW_FLAT_DIRNAME,
    materialize_t03_review_gallery,
    mirror_visual_checks,
    publish_incremental_visual_check,
    write_t03_review_index,
    write_t03_review_summary,
    write_t03_summary,
    write_updated_nodes_outputs,
    write_virtual_intersection_polygons,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_outputs import (
    write_review_index as write_step3_review_index,
    write_summary as write_step3_summary,
)

PROGRESS_LOG_INTERVAL_CASES = 1000


@dataclass(frozen=True)
class T03InternalFullInputArtifacts:
    run_root: Path
    visual_check_dir: Path
    internal_root: Path
    case_root: Path
    step3_run_root: Path
    selected_case_ids: tuple[str, ...]
    discovered_case_ids: tuple[str, ...]
    excluded_case_ids: tuple[str, ...]


T03Step67InternalFullInputArtifacts = T03InternalFullInputArtifacts

_now_text = now_text
_write_json_atomic = write_json_atomic
_accumulate_duration = accumulate_duration
_stable_case_ids = stable_case_ids
_feature_id = feature_id
_feature_mainnodeid = feature_mainnodeid
_load_shared_nodes = load_shared_nodes
_load_shared_layers = load_shared_layers
_discover_candidate_case_ids = discover_candidate_case_ids
_write_local_context_snapshot = write_local_context_snapshot
_write_internal_case_progress = write_internal_case_progress
_write_internal_progress = write_internal_progress
_write_internal_performance = write_internal_performance
_write_internal_failure = write_internal_failure
_write_internal_manifest = write_internal_manifest
_write_case_watch_status = write_case_watch_status
_publish_incremental_visual_check = publish_incremental_visual_check
_mirror_visual_checks = mirror_visual_checks
_write_virtual_intersection_polygons = write_virtual_intersection_polygons
_write_updated_nodes_outputs = write_updated_nodes_outputs
_run_single_case_direct = run_single_case_direct


def run_t03_internal_full_input(
    *,
    nodes_path: str | Path,
    roads_path: str | Path,
    drivezone_path: str | Path,
    rcsdroad_path: str | Path,
    rcsdnode_path: str | Path,
    out_root: str | Path,
    run_id: str,
    workers: int = 1,
    max_cases: int | None = None,
    buffer_m: float = 100.0,
    patch_size_m: float = 200.0,
    resolution_m: float = 0.2,
    debug: bool = False,
    review_mode: bool = False,
    visual_check_dir: str | Path | None = None,
    perf_audit: bool = False,
    perf_audit_interval_sec: int = DEFAULT_PERF_AUDIT_INTERVAL_SEC,
    perf_audit_max_samples: int = DEFAULT_PERF_AUDIT_MAX_SAMPLES,
    perf_audit_max_bytes: int = DEFAULT_PERF_AUDIT_MAX_BYTES,
) -> T03InternalFullInputArtifacts:
    resolved_nodes_path = normalize_runtime_path(nodes_path)
    resolved_roads_path = normalize_runtime_path(roads_path)
    resolved_drivezone_path = normalize_runtime_path(drivezone_path)
    resolved_rcsdroad_path = normalize_runtime_path(rcsdroad_path)
    resolved_rcsdnode_path = normalize_runtime_path(rcsdnode_path)
    resolved_out_root = normalize_runtime_path(out_root)
    resolved_visual_check_dir = (
        normalize_runtime_path(visual_check_dir)
        if visual_check_dir is not None
        else resolved_out_root / run_id / "visual_checks"
    )
    run_root = resolved_out_root / run_id
    internal_root = resolved_out_root / "_internal" / run_id
    case_root = internal_root / "local_context"
    case_progress_root = internal_root / "case_progress"
    step3_out_root = internal_root / "step3_runs"
    step3_run_root = step3_out_root / f"{run_id}__step3"
    max_workers = max(1, int(workers or 1))
    rerun_cleaned_before_write = False

    if run_root.exists():
        shutil.rmtree(run_root)
        rerun_cleaned_before_write = True
    if internal_root.exists():
        shutil.rmtree(internal_root)
    run_root.mkdir(parents=True, exist_ok=True)
    case_root.mkdir(parents=True, exist_ok=True)
    case_progress_root.mkdir(parents=True, exist_ok=True)
    step3_run_root.mkdir(parents=True, exist_ok=True)
    resolved_visual_check_dir.mkdir(parents=True, exist_ok=True)

    discovered_case_ids: list[str] = []
    excluded_case_ids = _stable_case_ids(list(DEFAULT_FULL_BATCH_EXCLUDED_CASE_IDS))
    selected_case_ids: list[str] = []
    step3_rows = []
    step67_rows = []
    failed_case_ids: list[str] = []
    successful_case_results: dict[str, dict[str, Any]] = {}
    shared_memory_summary: dict[str, Any] = build_shared_memory_summary()
    input_paths = {
        "nodes_path": resolved_nodes_path,
        "roads_path": resolved_roads_path,
        "drivezone_path": resolved_drivezone_path,
        "rcsdroad_path": resolved_rcsdroad_path,
        "rcsdnode_path": resolved_rcsdnode_path,
    }
    run_started_at = _now_text()
    run_started_perf = perf_counter()
    progress_lock = Lock()
    progress_state: dict[str, Any] = {
        "phase": "bootstrap",
        "status": "running",
        "message": "Preloading shared nodes handle for T03 internal full-input execution.",
        "current_phase_started_perf": run_started_perf,
        "completed_phase_durations_seconds": {},
        "stage_timer_totals_seconds": {key: 0.0 for key in RUNTIME_STAGE_TIMER_KEYS},
        "entered_case_execution_stage": False,
        "running_case_ids": set(),
        "completed_case_count": 0,
        "accepted_case_count": 0,
        "rejected_case_count": 0,
        "runtime_failed_case_count": 0,
        "case_elapsed_total_seconds": 0.0,
        "last_completed_case_id": None,
        "last_completed_at": None,
        "next_progress_log_threshold": PROGRESS_LOG_INTERVAL_CASES,
    }
    perf_audit_recorder = T03PerfAuditRecorder(
        enabled=perf_audit,
        internal_root=internal_root,
        run_root=run_root,
        visual_check_dir=resolved_visual_check_dir,
        run_id=run_id,
        started_at=run_started_at,
        workers=max_workers,
        sample_interval_sec=perf_audit_interval_sec,
        max_samples=perf_audit_max_samples,
        log_budget_bytes=perf_audit_max_bytes,
    )

    def _record_stage_timer_locked(stage_name: str, elapsed_seconds: float) -> None:
        _accumulate_duration(progress_state["stage_timer_totals_seconds"], stage_name, elapsed_seconds)

    def _record_stage_timer(stage_name: str, elapsed_seconds: float) -> None:
        with progress_lock:
            _record_stage_timer_locked(stage_name, elapsed_seconds)

    def _runtime_metrics_locked() -> dict[str, Any]:
        now_perf = perf_counter()
        total = len(selected_case_ids)
        completed = int(progress_state["completed_case_count"])
        running = len(progress_state["running_case_ids"])
        pending = max(total - completed - running, 0)
        elapsed_total = max(now_perf - float(run_started_perf), 0.0)
        case_elapsed_total = float(progress_state["case_elapsed_total_seconds"])
        avg_completed_case_seconds = (
            round(case_elapsed_total / completed, 6) if completed > 0 else None
        )
        completed_cases_per_minute = (
            round(completed / (elapsed_total / 60.0), 6) if completed > 0 and elapsed_total > 0 else 0.0
        )
        eta_remaining_seconds = (
            round(pending / (completed / elapsed_total), 6)
            if pending > 0 and completed > 0 and elapsed_total > 0
            else None
        )
        phase_durations = {
            phase_name: round(float(value), 6)
            for phase_name, value in progress_state["completed_phase_durations_seconds"].items()
        }
        current_phase = str(progress_state["phase"])
        phase_durations[current_phase] = round(
            phase_durations.get(current_phase, 0.0)
            + max(now_perf - float(progress_state["current_phase_started_perf"]), 0.0),
            6,
        )
        return {
            "entered_case_execution_stage": bool(progress_state["entered_case_execution_stage"]),
            "completed_case_count": completed,
            "accepted_case_count": int(progress_state["accepted_case_count"]),
            "rejected_case_count": int(progress_state["rejected_case_count"]),
            "runtime_failed_case_count": int(progress_state["runtime_failed_case_count"]),
            "success_case_count": int(progress_state["accepted_case_count"]),
            "failed_case_count": int(progress_state["rejected_case_count"]) + int(progress_state["runtime_failed_case_count"]),
            "running_case_count": running,
            "pending_case_count": pending,
            "last_completed_case_id": progress_state["last_completed_case_id"],
            "last_completed_at": progress_state["last_completed_at"],
            "performance": {
                "run_started_at": run_started_at,
                "elapsed_seconds_total": round(elapsed_total, 6),
                "case_elapsed_total_seconds": round(case_elapsed_total, 6),
                "avg_completed_case_seconds": avg_completed_case_seconds,
                "completed_cases_per_minute": completed_cases_per_minute,
                "estimated_remaining_seconds": eta_remaining_seconds,
                "phase_durations_seconds": phase_durations,
                "stage_timer_totals_seconds": {
                    stage_name: round(float(progress_state["stage_timer_totals_seconds"].get(stage_name, 0.0)), 6)
                    for stage_name in RUNTIME_STAGE_TIMER_KEYS
                },
                "progress_log_interval_cases": PROGRESS_LOG_INTERVAL_CASES,
            },
        }

    def _write_runtime_observability_locked(
        *,
        step3_run_root_for_progress: Path | None = None,
        extra_progress: dict[str, Any] | None = None,
    ) -> None:
        observability_started_perf = perf_counter()
        metrics = _runtime_metrics_locked()
        _write_internal_progress(
            internal_root=internal_root,
            run_root=run_root,
            phase=str(progress_state["phase"]),
            status=str(progress_state["status"]),
            message=str(progress_state["message"]),
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            prepared_case_ids=[],
            step3_run_root=step3_run_root_for_progress,
            **metrics,
            **(extra_progress or {}),
        )
        _write_internal_performance(
            internal_root=internal_root,
            run_root=run_root,
            phase=str(progress_state["phase"]),
            status=str(progress_state["status"]),
            payload={
                "selected_case_count": len(selected_case_ids),
                "total_case_count": len(selected_case_ids),
                **metrics,
            },
        )
        perf_audit_recorder.observe_snapshot(
            phase=str(progress_state["phase"]),
            status=str(progress_state["status"]),
            metrics={
                "total_case_count": len(selected_case_ids),
                **metrics,
            },
            timestamp=_now_text(),
            force_summary=str(progress_state["status"]) in {"completed", "failed"},
            force_sample=str(progress_state["status"]) in {"completed", "failed"},
        )
        _record_stage_timer_locked("observability_write", perf_counter() - observability_started_perf)

    def _write_internal_case_progress_runtime(**kwargs: Any) -> None:
        started_perf = perf_counter()
        _write_internal_case_progress(**kwargs)
        _record_stage_timer("observability_write", perf_counter() - started_perf)

    def _write_case_watch_status_runtime(**kwargs: Any) -> None:
        started_perf = perf_counter()
        _write_case_watch_status(**kwargs)
        _record_stage_timer("observability_write", perf_counter() - started_perf)

    def _write_local_context_snapshot_runtime(**kwargs: Any) -> None:
        started_perf = perf_counter()
        _write_local_context_snapshot(**kwargs)
        _record_stage_timer("output_write", perf_counter() - started_perf)

    def _emit_progress_log_locked(*, force: bool = False) -> None:
        completed = int(progress_state["completed_case_count"])
        threshold = int(progress_state["next_progress_log_threshold"])
        if not force and completed < threshold:
            return
        metrics = _runtime_metrics_locked()
        print(
            "[PROGRESS] "
            f"phase={progress_state['phase']} "
            f"total={len(selected_case_ids)} "
            f"completed={metrics['completed_case_count']} "
            f"success={metrics['success_case_count']} "
            f"failed={metrics['failed_case_count']} "
            f"running={metrics['running_case_count']} "
            f"pending={metrics['pending_case_count']} "
            f"elapsed_s={metrics['performance']['elapsed_seconds_total']:.1f} "
            f"rate_case_per_min={metrics['performance']['completed_cases_per_minute']:.3f}",
            flush=True,
        )
        while int(progress_state["next_progress_log_threshold"]) <= completed:
            progress_state["next_progress_log_threshold"] = int(progress_state["next_progress_log_threshold"]) + PROGRESS_LOG_INTERVAL_CASES

    def _set_phase(
        phase: str,
        *,
        status: str,
        message: str,
        step3_run_root_for_progress: Path | None = None,
        extra_progress: dict[str, Any] | None = None,
    ) -> None:
        with progress_lock:
            now_perf = perf_counter()
            previous_phase = str(progress_state["phase"])
            progress_state["completed_phase_durations_seconds"][previous_phase] = (
                float(progress_state["completed_phase_durations_seconds"].get(previous_phase, 0.0))
                + max(now_perf - float(progress_state["current_phase_started_perf"]), 0.0)
            )
            progress_state["phase"] = phase
            progress_state["status"] = status
            progress_state["message"] = message
            progress_state["current_phase_started_perf"] = now_perf
            if phase == "direct_case_execution":
                progress_state["entered_case_execution_stage"] = True
            _write_runtime_observability_locked(
                step3_run_root_for_progress=step3_run_root_for_progress,
                extra_progress=extra_progress,
            )
            metrics = _runtime_metrics_locked()
        print(
            "[PHASE] "
            f"phase={phase} status={status} total={len(selected_case_ids)} "
            f"completed={metrics['completed_case_count']} success={metrics['success_case_count']} "
            f"failed={metrics['failed_case_count']} message={message}",
            flush=True,
        )

    def _mark_case_running(case_id: str) -> None:
        with progress_lock:
            progress_state["running_case_ids"].add(str(case_id))
            _write_runtime_observability_locked(step3_run_root_for_progress=step3_run_root)

    def _mark_case_finished(
        case_id: str,
        *,
        state: str,
        case_elapsed_seconds: float,
        short_reason: str | None = None,
        last_stage: str = "completed",
    ) -> None:
        with progress_lock:
            progress_state["running_case_ids"].discard(str(case_id))
            progress_state["completed_case_count"] = int(progress_state["completed_case_count"]) + 1
            progress_state["case_elapsed_total_seconds"] = float(progress_state["case_elapsed_total_seconds"]) + max(case_elapsed_seconds, 0.0)
            progress_state["last_completed_case_id"] = str(case_id)
            progress_state["last_completed_at"] = _now_text()
            if state == "accepted":
                progress_state["accepted_case_count"] = int(progress_state["accepted_case_count"]) + 1
            elif state == "rejected":
                progress_state["rejected_case_count"] = int(progress_state["rejected_case_count"]) + 1
            else:
                progress_state["runtime_failed_case_count"] = int(progress_state["runtime_failed_case_count"]) + 1
                if str(case_id) not in failed_case_ids:
                    failed_case_ids.append(str(case_id))
            perf_audit_recorder.record_case_result(
                case_id=str(case_id),
                case_elapsed_seconds=case_elapsed_seconds,
                final_state=str(state),
                last_stage=last_stage,
                short_reason=short_reason,
            )
            _write_runtime_observability_locked(step3_run_root_for_progress=step3_run_root)
            _emit_progress_log_locked(force=False)

    _write_internal_progress(
        internal_root=internal_root,
        run_root=run_root,
        phase="bootstrap",
        status="running",
        message="Preloading shared nodes handle for T03 internal full-input execution.",
        selected_case_ids=[],
        discovered_case_ids=[],
        excluded_case_ids=excluded_case_ids,
        entered_case_execution_stage=False,
        completed_case_count=0,
        accepted_case_count=0,
        rejected_case_count=0,
        runtime_failed_case_count=0,
        success_case_count=0,
        failed_case_count=0,
        running_case_count=0,
        pending_case_count=0,
        performance={
            "run_started_at": run_started_at,
            "elapsed_seconds_total": 0.0,
            "case_elapsed_total_seconds": 0.0,
            "avg_completed_case_seconds": None,
            "completed_cases_per_minute": 0.0,
            "estimated_remaining_seconds": None,
            "phase_durations_seconds": {"bootstrap": 0.0},
            "progress_log_interval_cases": PROGRESS_LOG_INTERVAL_CASES,
        },
    )

    try:
        candidate_discovery_started_perf = perf_counter()
        shared_nodes = _load_shared_nodes(nodes_path=resolved_nodes_path)
        shared_memory_summary["enabled"] = True
        shared_memory_summary["node_group_lookup"] = True
        shared_memory_summary["layers"]["nodes"] = {
            "feature_count": len(shared_nodes),
        }
        discovered_case_ids = _discover_candidate_case_ids(shared_nodes)
        selection_result = select_candidate_case_ids(
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            max_cases=max_cases,
        )
        default_formal_case_ids = list(selection_result["eligible_case_ids"])
        selected_case_ids = list(selection_result["selected_case_ids"])
        _record_stage_timer("candidate_discovery", perf_counter() - candidate_discovery_started_perf)
        if not selected_case_ids:
            _write_internal_progress(
                internal_root=internal_root,
                run_root=run_root,
                phase="candidate_selection",
                status="failed",
                message="No eligible T03 internal full-input candidates were discovered.",
                selected_case_ids=[],
                discovered_case_ids=discovered_case_ids,
                excluded_case_ids=excluded_case_ids,
            )
            raise ValueError(
                "No eligible T03 internal full-input cases were discovered after applying "
                "has_evd=yes, is_anchor=no, kind_2 in {4, 2048} and the default T03 excluded-case set."
            )

        preflight_doc = build_full_input_preflight_doc(
            nodes_path=str(resolved_nodes_path),
            roads_path=str(resolved_roads_path),
            drivezone_path=str(resolved_drivezone_path),
            rcsdroad_path=str(resolved_rcsdroad_path),
            rcsdnode_path=str(resolved_rcsdnode_path),
            out_root=str(resolved_out_root),
            run_root=str(run_root),
            visual_check_dir=str(resolved_visual_check_dir),
            discovered_case_ids=list(discovered_case_ids),
            default_formal_case_ids=list(default_formal_case_ids),
            selected_case_ids=list(selected_case_ids),
            excluded_case_ids=list(excluded_case_ids),
            review_mode=review_mode,
            now_text=_now_text(),
        )
        _write_json_atomic(run_root / "preflight.json", preflight_doc)
        _write_internal_manifest(
            internal_root=internal_root,
            run_id=run_id,
            out_root=resolved_out_root,
            run_root=run_root,
            case_root=case_root,
            step3_run_root=step3_run_root,
            visual_check_dir=resolved_visual_check_dir,
            input_paths=input_paths,
            workers=max_workers,
            max_cases=max_cases,
            buffer_m=buffer_m,
            patch_size_m=patch_size_m,
            resolution_m=resolution_m,
            debug=debug,
            review_mode=review_mode,
            shared_memory_summary=shared_memory_summary,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            selected_case_ids=selected_case_ids,
            runtime_failed_case_ids=[],
        )

        _set_phase(
            "shared_handle_preload",
            status="running",
            message="Preloading shared full-input layers for direct per-case local query.",
        )
        shared_preload_started_perf = perf_counter()
        shared_layers = _load_shared_layers(
            nodes=shared_nodes,
            roads_path=resolved_roads_path,
            drivezone_path=resolved_drivezone_path,
            rcsdroad_path=resolved_rcsdroad_path,
            rcsdnode_path=resolved_rcsdnode_path,
        )
        shared_memory_summary["shared_local_layer_query"] = True
        shared_memory_summary["layers"].update(
            {
                "roads": {"feature_count": len(shared_layers.roads)},
                "drivezone": {"feature_count": len(shared_layers.drivezones)},
                "rcsdroad": {"feature_count": len(shared_layers.rcsd_roads)},
                "rcsdnode": {"feature_count": len(shared_layers.rcsd_nodes)},
            }
        )
        _record_stage_timer("shared_preload", perf_counter() - shared_preload_started_perf)

        _write_json_atomic(
            step3_run_root / "preflight.json",
            build_step3_preflight_doc(
                case_root=str(case_root),
                step3_run_root=str(step3_run_root),
                selected_case_ids=list(selected_case_ids),
                discovered_case_ids=list(discovered_case_ids),
                default_formal_case_ids=list(default_formal_case_ids),
                excluded_case_ids=list(excluded_case_ids),
                now_text=_now_text(),
            ),
        )

        _set_phase(
            "direct_case_execution",
            status="running",
            message="Executing T03 Step3 and downstream stages directly inside full-input runner with shared local query.",
            step3_run_root_for_progress=step3_run_root,
        )

        def _execute_case(case_id: str) -> dict[str, Any]:
            case_started_perf = perf_counter()
            _mark_case_running(case_id)
            _write_internal_case_progress_runtime(
                case_progress_root=case_progress_root,
                case_id=case_id,
                state="running",
                current_stage="direct_case_execution",
                reason="direct_case_started",
                detail="executing step3/step67 directly from shared full-input layers",
            )
            _write_case_watch_status_runtime(
                run_root=run_root,
                case_id=case_id,
                state="running",
                current_stage="direct_case_execution",
                reason="t03_case_started",
                detail="executing T03 stages directly from shared full-input layers",
            )
            try:
                result = _run_single_case_direct(
                    case_id=case_id,
                    shared_layers=shared_layers,
                    buffer_m=buffer_m,
                    patch_size_m=patch_size_m,
                    resolution_m=resolution_m,
                    internal_root=internal_root,
                    run_root=run_root,
                    step3_run_root=step3_run_root,
                    input_paths=input_paths,
                    debug_render=debug,
                )
            except Exception as exc:
                _write_internal_case_progress_runtime(
                    case_progress_root=case_progress_root,
                    case_id=case_id,
                    state="failed",
                    current_stage="direct_case_execution",
                    reason="direct_case_failed",
                    detail=str(exc),
                )
                _write_case_watch_status_runtime(
                    run_root=run_root,
                    case_id=case_id,
                    state="failed",
                    current_stage="direct_case_execution",
                    reason="t03_case_failed",
                    detail=f"{type(exc).__name__}: {exc}",
                )
                _mark_case_finished(
                    case_id,
                    state="failed",
                    case_elapsed_seconds=max(perf_counter() - case_started_perf, 0.0),
                    short_reason=f"{type(exc).__name__}: {exc}",
                    last_stage="direct_case_execution",
                )
                raise

            _write_local_context_snapshot_runtime(
                local_context_root=case_root,
                case_id=case_id,
                selected_counts=result["selected_counts"],
                selection_window=result["selection_window"],
            )
            for stage_name, elapsed_seconds in result.get("stage_timers", {}).items():
                _record_stage_timer(str(stage_name), float(elapsed_seconds))
            case_result = result["step67_case_result"]
            _write_internal_case_progress_runtime(
                case_progress_root=case_progress_root,
                case_id=case_id,
                state=case_result.step7_result.step7_state,
                current_stage="completed",
                reason=case_result.step7_result.reason,
                detail=case_result.step7_result.note or case_result.step6_result.reason,
                step3_state=result["step3_case_result"].step3_state,
                step45_state=case_result.step45_state,
                step6_state=case_result.step6_result.step6_state,
                step7_state=case_result.step7_result.step7_state,
                selected_counts=result["selected_counts"],
            )
            _write_case_watch_status_runtime(
                run_root=run_root,
                case_id=case_id,
                state=case_result.step7_result.step7_state,
                current_stage="completed",
                reason=case_result.step7_result.reason,
                detail=case_result.step7_result.note or case_result.step6_result.reason,
                step45_state=case_result.step45_state,
                step6_state=case_result.step6_result.step6_state,
                step7_state=case_result.step7_result.step7_state,
            )
            visual_copy_started_perf = perf_counter()
            _publish_incremental_visual_check(
                source_png_path=result["step67_row"].source_png_path,
                target_dir=resolved_visual_check_dir,
                case_id=case_id,
                step7_state=case_result.step7_result.step7_state,
            )
            _record_stage_timer("visual_copy", perf_counter() - visual_copy_started_perf)
            _mark_case_finished(
                case_id,
                state=case_result.step7_result.step7_state,
                case_elapsed_seconds=max(perf_counter() - case_started_perf, 0.0),
                short_reason=case_result.step7_result.reason,
                last_stage="completed",
            )
            return result

        if max_workers == 1 or len(selected_case_ids) <= 1:
            for case_id in selected_case_ids:
                try:
                    result = _execute_case(case_id)
                except Exception:
                    continue
                step3_rows.append(result["step3_row"])
                step67_rows.append(result["step67_row"])
                successful_case_results[case_id] = result
        else:
            futures = {}
            with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="t03-full-input-direct") as executor:
                for case_id in selected_case_ids:
                    futures[executor.submit(_execute_case, case_id)] = case_id
                for future in as_completed(futures):
                    case_id = futures[future]
                    try:
                        result = future.result()
                    except Exception:
                        continue
                    step3_rows.append(result["step3_row"])
                    step67_rows.append(result["step67_row"])
                    successful_case_results[case_id] = result

        step3_rows.sort(key=lambda row: sort_patch_key(str(row.case_id)))
        step67_rows.sort(key=lambda row: sort_patch_key(str(row.case_id)))
        output_write_started_perf = perf_counter()
        categorized_rows = materialize_t03_review_gallery(run_root, step67_rows)
        write_step3_review_index(step3_run_root, step3_rows)
        write_step3_summary(
            step3_run_root,
            step3_rows,
            expected_case_ids=list(selected_case_ids),
            raw_case_count=len(discovered_case_ids),
            default_formal_case_count=len(default_formal_case_ids),
            effective_case_ids=list(selected_case_ids),
            raw_case_ids=list(discovered_case_ids),
            default_formal_case_ids=list(default_formal_case_ids),
            default_full_batch_excluded_case_ids=list(excluded_case_ids),
            excluded_case_ids=list(excluded_case_ids),
            explicit_case_selection=False,
            failed_case_ids=list(failed_case_ids),
            rerun_cleaned_before_write=False,
        )
        write_t03_review_index(run_root, categorized_rows)
        write_t03_review_summary(run_root, categorized_rows)
        write_t03_summary(
            run_root,
            categorized_rows,
            expected_case_ids=list(selected_case_ids),
            raw_case_count=len(discovered_case_ids),
            default_formal_case_count=len(default_formal_case_ids),
            effective_case_ids=list(selected_case_ids),
            raw_case_ids=list(discovered_case_ids),
            default_formal_case_ids=list(default_formal_case_ids),
            default_full_batch_excluded_case_ids=list(excluded_case_ids),
            excluded_case_ids=list(excluded_case_ids),
            explicit_case_selection=False,
            failed_case_ids=list(failed_case_ids),
            rerun_cleaned_before_write=rerun_cleaned_before_write,
        )
        polygons_path = _write_virtual_intersection_polygons(
            run_root=run_root,
            successful_results=successful_case_results,
        )
        nodes_outputs = _write_updated_nodes_outputs(
            run_root=run_root,
            shared_nodes=shared_nodes,
            selected_case_ids=selected_case_ids,
            successful_results=successful_case_results,
            failed_case_ids=failed_case_ids,
        )
        _record_stage_timer("output_write", perf_counter() - output_write_started_perf)
        visual_copy_started_perf = perf_counter()
        _mirror_visual_checks(
            source_dir=run_root / T03_REVIEW_FLAT_DIRNAME,
            target_dir=resolved_visual_check_dir,
        )
        _record_stage_timer("visual_copy", perf_counter() - visual_copy_started_perf)

        _set_phase(
            "completed",
            status="completed",
            message="T03 internal full-input execution completed with direct shared-handle local query.",
            step3_run_root_for_progress=step3_run_root,
            extra_progress={
                "execution_mode": "direct_shared_handle_local_query",
                "runtime_failed_case_ids": list(failed_case_ids),
                "virtual_intersection_polygons_path": str(polygons_path),
                "nodes_output_path": str(nodes_outputs["nodes_path"]),
                "nodes_anchor_update_audit_csv": str(nodes_outputs["audit_csv_path"]),
                "nodes_anchor_update_audit_json": str(nodes_outputs["audit_json_path"]),
            },
        )
        with progress_lock:
            _emit_progress_log_locked(force=True)

        _write_internal_manifest(
            internal_root=internal_root,
            run_id=run_id,
            out_root=resolved_out_root,
            run_root=run_root,
            case_root=case_root,
            step3_run_root=step3_run_root,
            visual_check_dir=resolved_visual_check_dir,
            input_paths=input_paths,
            workers=max_workers,
            max_cases=max_cases,
            buffer_m=buffer_m,
            patch_size_m=patch_size_m,
            resolution_m=resolution_m,
            debug=debug,
            review_mode=review_mode,
            shared_memory_summary=shared_memory_summary,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            selected_case_ids=selected_case_ids,
            runtime_failed_case_ids=list(failed_case_ids),
            polygons_path=polygons_path,
            nodes_outputs=nodes_outputs,
        )
    except Exception as exc:
        with progress_lock:
            progress_state["phase"] = "failed"
            progress_state["status"] = "failed"
            progress_state["message"] = "T03 internal full-input execution failed before completion."
            _write_runtime_observability_locked(
                step3_run_root_for_progress=step3_run_root if step3_run_root.exists() else None,
                extra_progress={
                    "failure": str(exc),
                    "execution_mode": "direct_shared_handle_local_query",
                },
            )
            _emit_progress_log_locked(force=True)
        _write_internal_failure(
            internal_root=internal_root,
            run_root=run_root,
            phase="failed",
            failure=str(exc),
            selected_case_ids=selected_case_ids,
            discovered_case_ids=discovered_case_ids,
            excluded_case_ids=excluded_case_ids,
            prepared_case_ids=[],
            step3_run_root=step3_run_root if step3_run_root.exists() else None,
        )
        raise

    return T03InternalFullInputArtifacts(
        run_root=run_root,
        visual_check_dir=resolved_visual_check_dir,
        internal_root=internal_root,
        case_root=case_root,
        step3_run_root=step3_run_root,
        selected_case_ids=tuple(selected_case_ids),
        discovered_case_ids=tuple(discovered_case_ids),
        excluded_case_ids=tuple(excluded_case_ids),
    )


run_t03_step67_internal_full_input = run_t03_internal_full_input
