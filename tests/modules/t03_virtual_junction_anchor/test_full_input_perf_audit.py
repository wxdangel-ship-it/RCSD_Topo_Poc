from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_perf_audit import (
    T03PerfAuditRecorder,
)


def _metrics(*, completed: int, status: str = "running") -> dict[str, object]:
    return {
        "total_case_count": 10,
        "completed_case_count": completed,
        "running_case_count": 1 if status == "running" else 0,
        "pending_case_count": max(10 - completed, 0),
        "success_case_count": completed,
        "failed_case_count": 0,
        "runtime_failed_case_count": 0,
        "rejected_case_count": 0,
        "performance": {
            "elapsed_seconds_total": float(completed),
            "avg_completed_case_seconds": 1.0 if completed else None,
            "completed_cases_per_minute": float(completed),
            "stage_timer_totals_seconds": {},
        },
    }


def test_perf_audit_skips_storage_scan_when_interval_is_not_due(tmp_path: Path) -> None:
    recorder = T03PerfAuditRecorder(
        enabled=True,
        internal_root=tmp_path / "internal",
        run_root=tmp_path / "run",
        visual_check_dir=tmp_path / "visual",
        run_id="interval_gate",
        started_at="2026-08-02T00:00:00+00:00",
        workers=8,
        sample_interval_sec=30,
        max_samples=64,
        log_budget_bytes=100_000,
    )
    storage_scan_count = 0

    def _storage_snapshot() -> dict[str, object]:
        nonlocal storage_scan_count
        storage_scan_count += 1
        return {
            "run_root_size_mb": 0.0,
            "internal_root_size_mb": 0.0,
            "cases_dir_count": 0,
            "visual_png_count": 0,
        }

    recorder._build_storage_snapshot = _storage_snapshot  # type: ignore[method-assign]
    recorder.observe_snapshot(
        phase="direct_case_execution",
        status="running",
        metrics=_metrics(completed=1),
        timestamp="2026-08-02T00:00:01+00:00",
    )
    recorder.observe_snapshot(
        phase="direct_case_execution",
        status="running",
        metrics=_metrics(completed=2),
        timestamp="2026-08-02T00:00:02+00:00",
    )

    assert storage_scan_count == 1
    assert recorder.sample_count_written == 1


def test_perf_audit_stops_routine_scans_after_sample_cap_but_keeps_final_summary(
    tmp_path: Path,
) -> None:
    recorder = T03PerfAuditRecorder(
        enabled=True,
        internal_root=tmp_path / "internal",
        run_root=tmp_path / "run",
        visual_check_dir=tmp_path / "visual",
        run_id="sample_cap",
        started_at="2026-08-02T00:00:00+00:00",
        workers=8,
        sample_interval_sec=1,
        max_samples=1,
        log_budget_bytes=100_000,
    )
    storage_scan_count = 0

    def _storage_snapshot() -> dict[str, object]:
        nonlocal storage_scan_count
        storage_scan_count += 1
        return {
            "run_root_size_mb": 1.0,
            "internal_root_size_mb": 0.1,
            "cases_dir_count": 1,
            "visual_png_count": 1,
        }

    recorder._build_storage_snapshot = _storage_snapshot  # type: ignore[method-assign]
    recorder.observe_snapshot(
        phase="direct_case_execution",
        status="running",
        metrics=_metrics(completed=1),
        timestamp="2026-08-02T00:00:01+00:00",
    )
    recorder.observe_snapshot(
        phase="direct_case_execution",
        status="running",
        metrics=_metrics(completed=2),
        timestamp="2026-08-02T00:00:02+00:00",
        force_sample=True,
    )

    assert storage_scan_count == 1
    assert recorder.sample_count_written == 1
    assert recorder.samples_truncated is True

    recorder.observe_snapshot(
        phase="completed",
        status="completed",
        metrics=_metrics(completed=10, status="completed"),
        timestamp="2026-08-02T00:00:10+00:00",
        force_summary=True,
        force_sample=True,
    )

    summary = json.loads(recorder.summary_path.read_text(encoding="utf-8"))
    assert storage_scan_count == 2
    assert recorder.sample_count_written == 1
    assert summary["status"] == "completed"
    assert summary["last_snapshot"]["completed"] == 10
