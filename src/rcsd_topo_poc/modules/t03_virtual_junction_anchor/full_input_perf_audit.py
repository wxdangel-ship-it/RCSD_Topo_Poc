from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.full_input_observability import (
    write_json_atomic,
)


PERF_AUDIT_VERSION = "t03-perf-audit-v1"
T03_PERF_AUDIT_CONFIG_FILENAME = "t03_perf_audit_config.json"
T03_PERF_AUDIT_SAMPLES_FILENAME = "t03_perf_audit_samples.jsonl"
T03_PERF_AUDIT_SUMMARY_FILENAME = "t03_perf_audit_summary.json"
DEFAULT_PERF_AUDIT_INTERVAL_SEC = 30
DEFAULT_PERF_AUDIT_MAX_SAMPLES = 64
DEFAULT_PERF_AUDIT_MAX_BYTES = 100_000
DEFAULT_PERF_AUDIT_SAMPLE_BUDGET_BYTES = 70_000
DEFAULT_PERF_AUDIT_SUMMARY_BUDGET_BYTES = 20_000
DEFAULT_PERF_AUDIT_CONFIG_BUDGET_BYTES = 3_000
DEFAULT_PERF_AUDIT_SLACK_BUDGET_BYTES = 7_000
DEFAULT_PERF_AUDIT_TOP_N = 8


def _truncate_text(value: object, *, limit: int) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _directory_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_symlink():
                            continue
                        if entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(Path(entry.path))
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def _count_immediate_dirs(path: Path) -> int:
    if not path.is_dir():
        return 0
    count = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    if entry.is_dir(follow_symlinks=False):
                        count += 1
                except OSError:
                    continue
    except OSError:
        return 0
    return count


def _count_png_files(path: Path) -> int:
    if not path.is_dir():
        return 0
    count = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                try:
                    if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".png"):
                        count += 1
                except OSError:
                    continue
    except OSError:
        return 0
    return count


def _stage_timer_summary(raw_stage_timers: dict[str, Any]) -> dict[str, float | None]:
    return {
        "candidate_discovery": round(_safe_float(raw_stage_timers.get("candidate_discovery")) or 0.0, 6),
        "shared_preload": round(_safe_float(raw_stage_timers.get("shared_preload")) or 0.0, 6),
        "local_feature_selection": round(_safe_float(raw_stage_timers.get("local_feature_selection")) or 0.0, 6),
        "step3": round(_safe_float(raw_stage_timers.get("step3")) or 0.0, 6),
        "step3_reachable_support": round(_safe_float(raw_stage_timers.get("step3_reachable_support")) or 0.0, 6),
        "step3_negative_masks": round(_safe_float(raw_stage_timers.get("step3_negative_masks")) or 0.0, 6),
        "step3_cleanup_preview": round(_safe_float(raw_stage_timers.get("step3_cleanup_preview")) or 0.0, 6),
        "step3_hard_path_validation": round(
            _safe_float(raw_stage_timers.get("step3_hard_path_validation")) or 0.0,
            6,
        ),
        "step4_or_association": round(_safe_float(raw_stage_timers.get("association")) or 0.0, 6),
        "step5_or_foreign_filter": None,
        "step6": round(_safe_float(raw_stage_timers.get("step6")) or 0.0, 6),
        "step6_mask_prep": round(_safe_float(raw_stage_timers.get("step6_mask_prep")) or 0.0, 6),
        "step6_directional_cut": round(_safe_float(raw_stage_timers.get("step6_directional_cut")) or 0.0, 6),
        "step6_finalize": round(_safe_float(raw_stage_timers.get("step6_finalize")) or 0.0, 6),
        "step6_finalize_cleanup": round(
            _safe_float(raw_stage_timers.get("step6_finalize_cleanup")) or 0.0,
            6,
        ),
        "step6_finalize_validation": round(
            _safe_float(raw_stage_timers.get("step6_finalize_validation")) or 0.0,
            6,
        ),
        "step6_finalize_status": round(
            _safe_float(raw_stage_timers.get("step6_finalize_status")) or 0.0,
            6,
        ),
        "step7": round(_safe_float(raw_stage_timers.get("step7")) or 0.0, 6),
        "output_write": round(_safe_float(raw_stage_timers.get("output_write")) or 0.0, 6),
        "visual_copy": round(_safe_float(raw_stage_timers.get("visual_copy")) or 0.0, 6),
        "root_observability_write": round(
            _safe_float(raw_stage_timers.get("root_observability_write")) or 0.0,
            6,
        ),
        "case_observability_write": round(
            _safe_float(raw_stage_timers.get("case_observability_write")) or 0.0,
            6,
        ),
        "local_context_snapshot_write": round(
            _safe_float(raw_stage_timers.get("local_context_snapshot_write")) or 0.0,
            6,
        ),
        "perf_audit_write": round(_safe_float(raw_stage_timers.get("perf_audit_write")) or 0.0, 6),
    }


def _top_stage(stage_summary: dict[str, float | None]) -> tuple[str | None, float | None]:
    best_name: str | None = None
    best_value: float | None = None
    for stage_name, value in stage_summary.items():
        if value is None:
            continue
        if best_value is None or value > best_value:
            best_name = stage_name
            best_value = value
    return best_name, best_value


def _build_sample_budget(log_budget_bytes: int) -> int:
    remaining = (
        int(log_budget_bytes)
        - DEFAULT_PERF_AUDIT_CONFIG_BUDGET_BYTES
        - DEFAULT_PERF_AUDIT_SUMMARY_BUDGET_BYTES
        - DEFAULT_PERF_AUDIT_SLACK_BUDGET_BYTES
    )
    return max(0, min(DEFAULT_PERF_AUDIT_SAMPLE_BUDGET_BYTES, remaining))


class T03PerfAuditRecorder:
    def __init__(
        self,
        *,
        enabled: bool,
        internal_root: Path,
        run_root: Path,
        visual_check_dir: Path,
        run_id: str,
        started_at: str,
        workers: int,
        sample_interval_sec: int,
        max_samples: int,
        log_budget_bytes: int,
    ) -> None:
        self.enabled = bool(enabled)
        self.internal_root = internal_root
        self.run_root = run_root
        self.visual_check_dir = visual_check_dir
        self.run_id = run_id
        self.started_at = started_at
        self.workers = max(1, int(workers))
        self.sample_interval_sec = max(1, int(sample_interval_sec))
        self.max_samples = max(1, int(max_samples))
        self.log_budget_bytes = max(1_024, int(log_budget_bytes))
        self.sample_budget_bytes = _build_sample_budget(self.log_budget_bytes)
        self.summary_budget_bytes = min(
            DEFAULT_PERF_AUDIT_SUMMARY_BUDGET_BYTES,
            max(1_024, self.log_budget_bytes - self.sample_budget_bytes - DEFAULT_PERF_AUDIT_CONFIG_BUDGET_BYTES),
        )
        self.config_path = internal_root / T03_PERF_AUDIT_CONFIG_FILENAME
        self.samples_path = internal_root / T03_PERF_AUDIT_SAMPLES_FILENAME
        self.summary_path = internal_root / T03_PERF_AUDIT_SUMMARY_FILENAME
        self.sample_count_written = 0
        self.samples_truncated = False
        self._last_sample_perf: float | None = None
        self._last_snapshot: dict[str, Any] | None = None
        self._top_slow_cases: list[dict[str, Any]] = []
        self._top_failures: list[dict[str, Any]] = []

        if self.enabled:
            self._write_config()

    def _write_config(self) -> None:
        write_json_atomic(
            self.config_path,
            {
                "run_id": self.run_id,
                "enabled": self.enabled,
                "started_at": self.started_at,
                "sample_interval_sec": self.sample_interval_sec,
                "max_samples": self.max_samples,
                "max_bytes": self.log_budget_bytes,
                "sample_budget_bytes": self.sample_budget_bytes,
                "summary_budget_bytes": self.summary_budget_bytes,
                "workers": self.workers,
                "python_executable": sys.executable,
                "perf_audit_version": PERF_AUDIT_VERSION,
                "log_budget_bytes": self.log_budget_bytes,
                "effective_concurrency_formula": (
                    "little_law_style_estimate=(completed_cases_per_minute/60)*avg_completed_case_seconds, "
                    "smoothed_with_current_running_count_while_active"
                ),
            },
        )

    def record_case_result(
        self,
        *,
        case_id: str,
        case_elapsed_seconds: float,
        final_state: str,
        last_stage: str,
        short_reason: str | None,
    ) -> None:
        if not self.enabled:
            return
        slow_row = {
            "case_id": str(case_id),
            "total_case_seconds": round(max(float(case_elapsed_seconds), 0.0), 6),
            "final_state": str(final_state),
            "last_stage": str(last_stage),
        }
        self._top_slow_cases.append(slow_row)
        self._top_slow_cases.sort(
            key=lambda row: (-float(row["total_case_seconds"]), str(row["case_id"])),
        )
        del self._top_slow_cases[DEFAULT_PERF_AUDIT_TOP_N:]

        if final_state == "accepted":
            return

        failure_type = "runtime_failed" if final_state == "failed" else "business_rejected"
        if len(self._top_failures) < DEFAULT_PERF_AUDIT_TOP_N:
            self._top_failures.append(
                {
                    "case_id": str(case_id),
                    "failure_type": failure_type,
                    "short_reason": _truncate_text(short_reason or failure_type, limit=120),
                }
            )

    def _effective_concurrency_estimate(
        self,
        *,
        avg_case_seconds: float | None,
        cases_per_minute: float,
        running_case_count: int,
        status: str,
    ) -> float:
        if avg_case_seconds is None or cases_per_minute <= 0:
            return round(min(float(self.workers), max(float(running_case_count), 0.0)), 3)
        throughput_based = (cases_per_minute / 60.0) * max(avg_case_seconds, 0.0)
        if status == "completed" and running_case_count == 0:
            estimate = throughput_based
        elif running_case_count > 0:
            estimate = max(throughput_based, min(float(running_case_count), throughput_based + 1.0))
        else:
            estimate = throughput_based
        return round(min(float(self.workers), max(estimate, 0.0)), 3)

    def _build_storage_snapshot(self) -> dict[str, Any]:
        run_root_size_bytes = _directory_size_bytes(self.run_root)
        internal_root_size_bytes = _directory_size_bytes(self.internal_root)
        return {
            "run_root_size_mb": round(run_root_size_bytes / (1024.0 * 1024.0), 3),
            "internal_root_size_mb": round(internal_root_size_bytes / (1024.0 * 1024.0), 3),
            "cases_dir_count": _count_immediate_dirs(self.run_root / "cases"),
            "visual_png_count": _count_png_files(self.visual_check_dir),
        }

    def _build_snapshot(
        self,
        *,
        phase: str,
        status: str,
        metrics: dict[str, Any],
        timestamp: str,
    ) -> dict[str, Any]:
        performance = metrics.get("performance", {}) if isinstance(metrics, dict) else {}
        stage_summary = _stage_timer_summary(
            performance.get("stage_timer_totals_seconds", {})
            if isinstance(performance, dict)
            else {}
        )
        top_stage_name, top_stage_value = _top_stage(stage_summary)
        avg_case_seconds = _safe_float(performance.get("avg_completed_case_seconds"))
        cases_per_minute = _safe_float(performance.get("completed_cases_per_minute")) or 0.0
        running_case_count = _safe_int(metrics.get("running_case_count"))
        snapshot = {
            "ts": timestamp,
            "phase": str(phase),
            "status": str(status),
            "total": _safe_int(metrics.get("total_case_count")),
            "completed": _safe_int(metrics.get("completed_case_count")),
            "running": running_case_count,
            "pending": _safe_int(metrics.get("pending_case_count")),
            "success": _safe_int(metrics.get("success_case_count")),
            "failed": _safe_int(metrics.get("failed_case_count")),
            "runtime_failed_count": _safe_int(metrics.get("runtime_failed_case_count")),
            "business_rejected_count": _safe_int(metrics.get("rejected_case_count")),
            "elapsed_s": round(_safe_float(performance.get("elapsed_seconds_total")) or 0.0, 6),
            "avg_case_s": round(avg_case_seconds, 6) if avg_case_seconds is not None else None,
            "case_per_min": round(cases_per_minute, 6),
            "effective_concurrency_est": self._effective_concurrency_estimate(
                avg_case_seconds=avg_case_seconds,
                cases_per_minute=cases_per_minute,
                running_case_count=running_case_count,
                status=str(status),
            ),
            "top_stage": top_stage_name,
            "top_stage_s": round(top_stage_value or 0.0, 6),
            "stage_timer_totals_seconds": stage_summary,
        }
        snapshot.update(self._build_storage_snapshot())
        return snapshot

    def _append_sample(self, sample: dict[str, Any]) -> bool:
        self.samples_path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(sample, ensure_ascii=False, separators=(",", ":")) + "\n"
        encoded = line.encode("utf-8")
        current_size = self.samples_path.stat().st_size if self.samples_path.exists() else 0
        if self.sample_count_written >= self.max_samples or current_size + len(encoded) > self.sample_budget_bytes:
            self.samples_truncated = True
            return False
        with self.samples_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        self.sample_count_written += 1
        return True

    def _summary_payload(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "last_updated_at": snapshot["ts"],
            "status": snapshot["status"],
            "phase": snapshot["phase"],
            "elapsed_seconds_total": snapshot["elapsed_s"],
            "last_snapshot": {
                "total": snapshot["total"],
                "completed": snapshot["completed"],
                "running": snapshot["running"],
                "pending": snapshot["pending"],
                "success": snapshot["success"],
                "failed": snapshot["failed"],
                "runtime_failed_count": snapshot["runtime_failed_count"],
                "business_rejected_count": snapshot["business_rejected_count"],
                "avg_completed_case_seconds": snapshot["avg_case_s"],
                "completed_cases_per_minute": snapshot["case_per_min"],
                "effective_concurrency_est": snapshot["effective_concurrency_est"],
            },
            "stage_timer_totals_seconds": snapshot["stage_timer_totals_seconds"],
            "top_slow_cases": list(self._top_slow_cases),
            "top_failures": list(self._top_failures),
            "output_footprint": {
                "run_root_size_mb": snapshot["run_root_size_mb"],
                "internal_root_size_mb": snapshot["internal_root_size_mb"],
                "review_png_count": snapshot["visual_png_count"],
                "case_dir_count": snapshot["cases_dir_count"],
            },
            "sample_count_written": self.sample_count_written,
            "samples_truncated": self.samples_truncated,
            "total_log_bytes_est": 0,
        }

    def _fit_summary_budget(self, payload: dict[str, Any]) -> dict[str, Any]:
        while True:
            encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
            if len(encoded) <= self.summary_budget_bytes:
                return payload
            if payload["top_failures"]:
                payload["top_failures"] = payload["top_failures"][:-1]
                continue
            if payload["top_slow_cases"]:
                payload["top_slow_cases"] = payload["top_slow_cases"][:-1]
                continue
            return payload

    def _log_bytes_estimate(self) -> int:
        total = 0
        for path in (self.config_path, self.samples_path, self.summary_path):
            if path.exists():
                total += path.stat().st_size
        return total

    def _write_summary(self, snapshot: dict[str, Any]) -> None:
        payload = self._fit_summary_budget(self._summary_payload(snapshot))
        for _ in range(3):
            write_json_atomic(self.summary_path, payload)
            updated_total = self._log_bytes_estimate()
            if payload.get("total_log_bytes_est") == updated_total:
                break
            payload["total_log_bytes_est"] = updated_total
            payload = self._fit_summary_budget(payload)

    def observe_snapshot(
        self,
        *,
        phase: str,
        status: str,
        metrics: dict[str, Any],
        timestamp: str,
        force_summary: bool = False,
        force_sample: bool = False,
    ) -> None:
        if not self.enabled:
            return
        now_perf = perf_counter()
        should_sample = False
        if self.sample_count_written == 0:
            should_sample = True
        elif force_sample:
            should_sample = True
        elif self._last_sample_perf is not None and now_perf - self._last_sample_perf >= self.sample_interval_sec:
            should_sample = True

        snapshot = self._build_snapshot(
            phase=phase,
            status=status,
            metrics=metrics,
            timestamp=timestamp,
        )

        sample_payload = {
            "ts": snapshot["ts"],
            "phase": snapshot["phase"],
            "total": snapshot["total"],
            "completed": snapshot["completed"],
            "running": snapshot["running"],
            "pending": snapshot["pending"],
            "success": snapshot["success"],
            "failed": snapshot["failed"],
            "runtime_failed_count": snapshot["runtime_failed_count"],
            "business_rejected_count": snapshot["business_rejected_count"],
            "elapsed_s": snapshot["elapsed_s"],
            "avg_case_s": snapshot["avg_case_s"],
            "case_per_min": snapshot["case_per_min"],
            "effective_concurrency_est": snapshot["effective_concurrency_est"],
            "top_stage": snapshot["top_stage"],
            "top_stage_s": snapshot["top_stage_s"],
            "run_root_size_mb": snapshot["run_root_size_mb"],
            "internal_root_size_mb": snapshot["internal_root_size_mb"],
            "cases_dir_count": snapshot["cases_dir_count"],
            "visual_png_count": snapshot["visual_png_count"],
        }

        if should_sample and self._append_sample(sample_payload):
            self._last_sample_perf = now_perf
            self._last_snapshot = snapshot
        elif self._last_snapshot is None or force_summary:
            self._last_snapshot = snapshot

        if should_sample or force_summary:
            self._write_summary(self._last_snapshot or snapshot)


__all__ = [
    "DEFAULT_PERF_AUDIT_INTERVAL_SEC",
    "DEFAULT_PERF_AUDIT_MAX_BYTES",
    "DEFAULT_PERF_AUDIT_MAX_SAMPLES",
    "PERF_AUDIT_VERSION",
    "T03_PERF_AUDIT_CONFIG_FILENAME",
    "T03_PERF_AUDIT_SAMPLES_FILENAME",
    "T03_PERF_AUDIT_SUMMARY_FILENAME",
    "T03PerfAuditRecorder",
]
