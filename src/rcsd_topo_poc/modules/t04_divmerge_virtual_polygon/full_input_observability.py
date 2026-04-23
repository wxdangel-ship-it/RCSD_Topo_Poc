from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_json


T04_INTERNAL_PROGRESS_FILENAME = "t04_internal_full_input_progress.json"
T04_INTERNAL_FAILURE_FILENAME = "t04_internal_full_input_failure.json"
T04_CASE_WATCH_STATUS_FILENAME = "t04_case_watch_status.json"


def now_text() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_json_doc(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        write_json(temp_path, payload)
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def write_root_progress(
    *,
    run_root: Path,
    phase: str,
    status: str,
    message: str,
    selected_case_ids: list[str],
    completed_case_count: int = 0,
    running_case_ids: list[str] | None = None,
    accepted_case_count: int = 0,
    rejected_case_count: int = 0,
    runtime_failed_case_count: int = 0,
    missing_status_case_count: int = 0,
    entered_case_execution: bool = False,
    performance: dict[str, Any] | None = None,
    last_completed_case_id: str | None = None,
    last_completed_at: str | None = None,
    **extra: Any,
) -> Path:
    running = list(running_case_ids or [])
    selected_count = len(selected_case_ids)
    pending_count = max(selected_count - completed_case_count - len(running), 0)
    payload = {
        "updated_at": now_text(),
        "phase": phase,
        "status": status,
        "message": message,
        "run_root": str(run_root),
        "selected_case_count": selected_count,
        "selected_case_ids": list(selected_case_ids),
        "completed_case_count": int(completed_case_count),
        "running_case_count": len(running),
        "running_case_ids": running,
        "pending_case_count": pending_count,
        "accepted_case_count": int(accepted_case_count),
        "rejected_case_count": int(rejected_case_count),
        "runtime_failed_case_count": int(runtime_failed_case_count),
        "missing_status_case_count": int(missing_status_case_count),
        "entered_case_execution": bool(entered_case_execution),
        "entered_case_execution_stage": bool(entered_case_execution),
        "last_completed_case_id": last_completed_case_id,
        "last_completed_at": last_completed_at,
        "performance": dict(performance or {}),
        **extra,
    }
    path = run_root / T04_INTERNAL_PROGRESS_FILENAME
    write_json_atomic(path, payload)
    return path


def write_root_failure(
    *,
    run_root: Path,
    phase: str,
    failure: str,
    traceback_text: str = "",
    selected_case_ids: list[str] | None = None,
    **extra: Any,
) -> Path:
    payload = {
        "updated_at": now_text(),
        "phase": phase,
        "failure": failure,
        "traceback": traceback_text,
        "run_root": str(run_root),
        "selected_case_ids": list(selected_case_ids or []),
        **extra,
    }
    path = run_root / T04_INTERNAL_FAILURE_FILENAME
    write_json_atomic(path, payload)
    return path


def write_case_watch_status(
    *,
    run_root: Path,
    case_id: str,
    state: str,
    current_stage: str,
    reason: str,
    detail: str,
    **extra: Any,
) -> Path:
    case_dir = run_root / "cases" / str(case_id)
    payload = {
        "case_id": str(case_id),
        "state": str(state),
        "current_stage": str(current_stage),
        "reason": str(reason),
        "detail": str(detail),
        "updated_at": now_text(),
        **extra,
    }
    path = case_dir / T04_CASE_WATCH_STATUS_FILENAME
    write_json_atomic(path, payload)
    return path


def build_performance_snapshot(
    *,
    started_perf: float,
    now_perf: float,
    completed_case_count: int,
    running_case_count: int,
    selected_case_count: int,
    case_elapsed_total_seconds: float,
) -> dict[str, Any]:
    elapsed = max(float(now_perf) - float(started_perf), 0.0)
    completed = max(int(completed_case_count), 0)
    avg_case = case_elapsed_total_seconds / completed if completed else None
    cases_per_minute = (completed / elapsed * 60.0) if elapsed > 0 else None
    remaining = max(int(selected_case_count) - completed - max(int(running_case_count), 0), 0)
    eta = (remaining * avg_case / max(int(running_case_count), 1)) if avg_case is not None else None
    return {
        "elapsed_seconds_total": round(elapsed, 3),
        "avg_completed_case_seconds": round(avg_case, 3) if avg_case is not None else None,
        "completed_cases_per_minute": round(cases_per_minute, 3) if cases_per_minute is not None else None,
        "estimated_remaining_seconds": round(eta, 3) if eta is not None else None,
    }


__all__ = [
    "T04_CASE_WATCH_STATUS_FILENAME",
    "T04_INTERNAL_FAILURE_FILENAME",
    "T04_INTERNAL_PROGRESS_FILENAME",
    "build_performance_snapshot",
    "load_json_doc",
    "now_text",
    "write_case_watch_status",
    "write_json_atomic",
    "write_root_failure",
    "write_root_progress",
]
