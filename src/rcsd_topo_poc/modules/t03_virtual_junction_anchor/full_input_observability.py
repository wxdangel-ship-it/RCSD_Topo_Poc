from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_json


RUNTIME_STAGE_TIMER_KEYS = (
    "candidate_discovery",
    "shared_preload",
    "local_feature_selection",
    "step3",
    "step3_reachable_support",
    "step3_negative_masks",
    "step3_cleanup_preview",
    "step3_hard_path_validation",
    "step45",
    "step6",
    "step6_mask_prep",
    "step6_directional_cut",
    "step6_finalize",
    "step6_finalize_cleanup",
    "step6_finalize_validation",
    "step6_finalize_status",
    "step7",
    "output_write",
    "visual_copy",
    "root_observability_write",
    "case_observability_write",
    "local_context_snapshot_write",
    "perf_audit_write",
)

T03_INTERNAL_MANIFEST_FILENAME = "t03_internal_full_input_manifest.json"
T03_INTERNAL_PROGRESS_FILENAME = "t03_internal_full_input_progress.json"
T03_INTERNAL_PERFORMANCE_FILENAME = "t03_internal_full_input_performance.json"
T03_INTERNAL_FAILURE_FILENAME = "t03_internal_full_input_failure.json"
T03_CASE_WATCH_STATUS_FILENAME = "t03_case_watch_status.json"

LEGACY_INTERNAL_MANIFEST_FILENAME = "internal_full_input_manifest.json"
LEGACY_INTERNAL_PROGRESS_FILENAME = "internal_full_input_progress.json"
LEGACY_INTERNAL_PERFORMANCE_FILENAME = "internal_full_input_performance.json"
LEGACY_INTERNAL_FAILURE_FILENAME = "internal_full_input_failure.json"
LEGACY_CASE_WATCH_STATUS_FILENAME = "step67_watch_status.json"


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        write_json(temp_path, payload)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _load_existing_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _semantic_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "updated_at"}


def _write_state_payload_atomic(path: Path, payload: dict[str, Any]) -> None:
    existing = _load_existing_json(path)
    if isinstance(existing, dict) and _semantic_payload(existing) == _semantic_payload(payload):
        return
    write_json_atomic(path, payload)


def accumulate_duration(totals: dict[str, float], key: str, duration_seconds: float) -> None:
    totals[key] = round(float(totals.get(key, 0.0)) + max(float(duration_seconds), 0.0), 6)


def internal_observability_paths(internal_root: Path) -> dict[str, Path]:
    return {
        "manifest": internal_root / T03_INTERNAL_MANIFEST_FILENAME,
        "progress": internal_root / T03_INTERNAL_PROGRESS_FILENAME,
        "performance": internal_root / T03_INTERNAL_PERFORMANCE_FILENAME,
        "failure": internal_root / T03_INTERNAL_FAILURE_FILENAME,
    }


def write_local_context_snapshot(
    *,
    local_context_root: Path,
    case_id: str,
    selected_counts: dict[str, int],
    selection_window: BaseGeometry,
) -> None:
    local_context_root.mkdir(parents=True, exist_ok=True)
    _write_state_payload_atomic(
        local_context_root / f"{case_id}.json",
        {
            "case_id": case_id,
            "source_mode": "t03_internal_full_input_direct_local_query",
            "selection_window_bounds": [round(float(value), 6) for value in selection_window.bounds],
            "selected_feature_counts": dict(selected_counts),
            "updated_at": now_text(),
        },
    )


def write_case_watch_status(
    *,
    run_root: Path,
    case_id: str,
    state: str,
    current_stage: str,
    reason: str,
    detail: str,
    **extra: Any,
) -> None:
    case_dir = run_root / "cases" / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    _write_state_payload_atomic(
        case_dir / T03_CASE_WATCH_STATUS_FILENAME,
        {
            "case_id": case_id,
            "state": state,
            "current_stage": current_stage,
            "reason": reason,
            "detail": detail,
            "updated_at": now_text(),
            **extra,
        },
    )


def write_internal_case_progress(
    *,
    case_progress_root: Path,
    case_id: str,
    state: str,
    current_stage: str,
    reason: str,
    detail: str,
    **extra: Any,
) -> None:
    case_progress_root.mkdir(parents=True, exist_ok=True)
    _write_state_payload_atomic(
        case_progress_root / f"{case_id}.json",
        {
            "case_id": str(case_id),
            "state": state,
            "current_stage": current_stage,
            "reason": reason,
            "detail": detail,
            "updated_at": now_text(),
            **extra,
        },
    )


def write_internal_progress(
    *,
    internal_root: Path,
    run_root: Path,
    phase: str,
    status: str,
    message: str,
    selected_case_ids: list[str],
    discovered_case_ids: list[str],
    excluded_case_ids: list[str],
    prepared_case_ids: list[str] | None = None,
    step3_run_root: Path | None = None,
    **extra: Any,
) -> None:
    paths = internal_observability_paths(internal_root)
    payload = {
        "updated_at": now_text(),
        "phase": phase,
        "status": status,
        "message": message,
        "run_root": str(run_root),
        "internal_root": str(internal_root),
        "manifest_path": str(paths["manifest"]),
        "preflight_path": str(run_root / "preflight.json"),
        "performance_path": str(paths["performance"]),
        "total_case_count": len(selected_case_ids),
        "selected_case_count": len(selected_case_ids),
        "discovered_case_count": len(discovered_case_ids),
        "default_full_batch_excluded_case_count": len(excluded_case_ids),
        "prepared_case_count": len(prepared_case_ids or []),
        "step3_run_root": str(step3_run_root) if step3_run_root is not None else None,
        **extra,
    }
    write_json_atomic(paths["progress"], payload)


def write_internal_performance(
    *,
    internal_root: Path,
    run_root: Path,
    phase: str,
    status: str,
    payload: dict[str, Any],
) -> None:
    paths = internal_observability_paths(internal_root)
    write_json_atomic(
        paths["performance"],
        {
            "updated_at": now_text(),
            "run_root": str(run_root),
            "internal_root": str(internal_root),
            "phase": phase,
            "status": status,
            **payload,
        },
    )


def write_internal_failure(
    *,
    internal_root: Path,
    run_root: Path,
    phase: str,
    failure: str,
    selected_case_ids: list[str],
    discovered_case_ids: list[str],
    excluded_case_ids: list[str],
    prepared_case_ids: list[str] | None = None,
    step3_run_root: Path | None = None,
) -> None:
    paths = internal_observability_paths(internal_root)
    write_json_atomic(
        paths["failure"],
        {
            "updated_at": now_text(),
            "phase": phase,
            "failure": failure,
            "run_root": str(run_root),
            "internal_root": str(internal_root),
            "selected_case_ids": list(selected_case_ids),
            "discovered_case_ids": list(discovered_case_ids),
            "excluded_case_ids": list(excluded_case_ids),
            "prepared_case_ids": list(prepared_case_ids or []),
            "step3_run_root": str(step3_run_root) if step3_run_root is not None else None,
        },
    )


def write_internal_manifest(
    *,
    internal_root: Path,
    run_id: str,
    out_root: Path,
    run_root: Path,
    case_root: Path,
    step3_run_root: Path,
    visual_check_dir: Path,
    input_paths: dict[str, Path],
    workers: int,
    max_cases: int | None,
    buffer_m: float,
    patch_size_m: float,
    resolution_m: float,
    debug: bool,
    review_mode: bool,
    render_review_png: bool,
    progress_flush_interval_sec: float,
    progress_flush_interval_cases: int,
    local_context_snapshot_mode: str,
    shared_memory_summary: dict[str, Any],
    discovered_case_ids: list[str],
    excluded_case_ids: list[str],
    selected_case_ids: list[str],
    runtime_failed_case_ids: list[str],
    execution_case_ids: list[str] | None = None,
    streamed_results_path: Path | None = None,
    terminal_case_records_root: Path | None = None,
    resume_requested: bool = False,
    retry_failed_requested: bool = False,
    resume_effective: bool = False,
    retry_failed_effective: bool = False,
    polygons_path: Path | None = None,
    nodes_outputs: dict[str, Path] | None = None,
) -> None:
    paths = internal_observability_paths(internal_root)
    payload = {
        "run_id": run_id,
        "nodes_path": str(input_paths["nodes_path"]),
        "roads_path": str(input_paths["roads_path"]),
        "drivezone_path": str(input_paths["drivezone_path"]),
        "rcsdroad_path": str(input_paths["rcsdroad_path"]),
        "rcsdnode_path": str(input_paths["rcsdnode_path"]),
        "out_root": str(out_root),
        "run_root": str(run_root),
        "case_root": str(case_root),
        "step3_run_root": str(step3_run_root),
        "visual_check_dir": str(visual_check_dir),
        "workers": workers,
        "max_cases": max_cases,
        "buffer_m": buffer_m,
        "patch_size_m": patch_size_m,
        "resolution_m": resolution_m,
        "debug": debug,
        "render_review_png": render_review_png,
        "review_mode_requested": review_mode,
        "review_mode_effective": False,
        "review_mode_note": (
            "accepted for parameter compatibility only; "
            "T03 internal full-input runner keeps formal Step67 semantics unchanged"
        ),
        "progress_flush_interval_sec": float(progress_flush_interval_sec),
        "progress_flush_interval_cases": int(progress_flush_interval_cases),
        "local_context_snapshot_mode": str(local_context_snapshot_mode),
        "source_mode": "t03_internal_full_input_direct_local_query",
        "execution_mode": "direct_shared_handle_local_query",
        "candidate_discovery_mode": "shared_nodes_handle",
        "progress_payload_mode": "lightweight_runtime_counters",
        "pending_case_prewrite_enabled": False,
        "stage_timer_keys": list(RUNTIME_STAGE_TIMER_KEYS),
        "shared_memory_summary": shared_memory_summary,
        "discovered_case_ids": list(discovered_case_ids),
        "default_full_batch_excluded_case_ids": list(excluded_case_ids),
        "selected_case_ids": list(selected_case_ids),
        "execution_case_ids": list(execution_case_ids or []),
        "prepared_cases": [],
        "transitional_case_package_path_retained": False,
        "local_context_root": str(case_root),
        "progress_path": str(paths["progress"]),
        "performance_path": str(paths["performance"]),
        "case_progress_root": str(internal_root / "case_progress"),
        "runtime_failed_case_ids": list(runtime_failed_case_ids),
        "resume_requested": resume_requested,
        "retry_failed_requested": retry_failed_requested,
        "resume_effective": resume_effective,
        "retry_failed_effective": retry_failed_effective,
    }
    if streamed_results_path is not None:
        payload["streamed_case_results_path"] = str(streamed_results_path)
    if terminal_case_records_root is not None:
        payload["terminal_case_records_root"] = str(terminal_case_records_root)
        payload["authoritative_terminal_state_source"] = "per_case_atomic_terminal_record"
    if polygons_path is not None:
        payload["virtual_intersection_polygons_path"] = str(polygons_path)
    if nodes_outputs is not None:
        payload["nodes_output_path"] = str(nodes_outputs["nodes_path"])
        payload["nodes_anchor_update_audit_csv"] = str(nodes_outputs["audit_csv_path"])
        payload["nodes_anchor_update_audit_json"] = str(nodes_outputs["audit_json_path"])
    write_json_atomic(paths["manifest"], payload)


__all__ = [
    "LEGACY_CASE_WATCH_STATUS_FILENAME",
    "LEGACY_INTERNAL_FAILURE_FILENAME",
    "LEGACY_INTERNAL_MANIFEST_FILENAME",
    "LEGACY_INTERNAL_PERFORMANCE_FILENAME",
    "LEGACY_INTERNAL_PROGRESS_FILENAME",
    "RUNTIME_STAGE_TIMER_KEYS",
    "T03_CASE_WATCH_STATUS_FILENAME",
    "T03_INTERNAL_FAILURE_FILENAME",
    "T03_INTERNAL_MANIFEST_FILENAME",
    "T03_INTERNAL_PERFORMANCE_FILENAME",
    "T03_INTERNAL_PROGRESS_FILENAME",
    "accumulate_duration",
    "internal_observability_paths",
    "now_text",
    "write_case_watch_status",
    "write_internal_case_progress",
    "write_internal_failure",
    "write_internal_manifest",
    "write_internal_performance",
    "write_internal_progress",
    "write_json_atomic",
    "write_local_context_snapshot",
]
