from __future__ import annotations

import json
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

from .full_input_observability import now_text, write_json_atomic


DEFAULT_PERF_AUDIT_INTERVAL_SEC = 30
DEFAULT_PERF_AUDIT_MAX_SAMPLES = 64
DEFAULT_PERF_AUDIT_MAX_BYTES = 100_000


class T04PerfAuditRecorder:
    def __init__(
        self,
        *,
        enabled: bool,
        run_root: Path,
        run_id: str,
        workers: int,
        sample_interval_sec: int = DEFAULT_PERF_AUDIT_INTERVAL_SEC,
        max_samples: int = DEFAULT_PERF_AUDIT_MAX_SAMPLES,
        max_bytes: int = DEFAULT_PERF_AUDIT_MAX_BYTES,
    ) -> None:
        self.enabled = bool(enabled)
        self.run_root = run_root
        self.run_id = run_id
        self.workers = max(1, int(workers))
        self.sample_interval_sec = max(1, int(sample_interval_sec))
        self.max_samples = max(1, int(max_samples))
        self.max_bytes = max(1024, int(max_bytes))
        self.config_path = run_root / "t04_perf_audit_config.json"
        self.samples_path = run_root / "t04_perf_audit_samples.jsonl"
        self.summary_path = run_root / "t04_perf_audit_summary.json"
        self.sample_count = 0
        self.started_perf = perf_counter()
        self._last_sample_perf: float | None = None
        self._slow_cases: list[dict[str, Any]] = []
        self._failures: list[dict[str, Any]] = []
        if self.enabled:
            write_json_atomic(
                self.config_path,
                {
                    "run_id": self.run_id,
                    "enabled": True,
                    "workers": self.workers,
                    "sample_interval_sec": self.sample_interval_sec,
                    "max_samples": self.max_samples,
                    "max_bytes": self.max_bytes,
                    "python_executable": sys.executable,
                    "perf_audit_version": "t04-perf-audit-v1",
                    "updated_at": now_text(),
                },
            )

    def record_case_result(
        self,
        *,
        case_id: str,
        elapsed_seconds: float,
        final_state: str,
        reason: str,
    ) -> None:
        if not self.enabled:
            return
        row = {
            "case_id": str(case_id),
            "elapsed_seconds": round(max(float(elapsed_seconds), 0.0), 6),
            "final_state": str(final_state),
            "reason": str(reason or ""),
        }
        self._slow_cases.append(row)
        self._slow_cases.sort(key=lambda item: item["elapsed_seconds"], reverse=True)
        self._slow_cases = self._slow_cases[:10]
        if final_state not in {"accepted", "rejected"}:
            self._failures.append(row)
            self._failures = self._failures[-10:]

    def maybe_sample(self, snapshot: dict[str, Any], *, force: bool = False) -> None:
        if not self.enabled or self.sample_count >= self.max_samples:
            return
        current_perf = perf_counter()
        if (
            not force
            and self._last_sample_perf is not None
            and current_perf - self._last_sample_perf < self.sample_interval_sec
        ):
            return
        line = json.dumps({"updated_at": now_text(), **snapshot}, ensure_ascii=False)
        current_size = self.samples_path.stat().st_size if self.samples_path.is_file() else 0
        if current_size + len(line.encode("utf-8")) + 1 > self.max_bytes:
            return
        self.samples_path.parent.mkdir(parents=True, exist_ok=True)
        with self.samples_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self.sample_count += 1
        self._last_sample_perf = current_perf

    def write_summary(self, *, final_snapshot: dict[str, Any]) -> None:
        if not self.enabled:
            return
        write_json_atomic(
            self.summary_path,
            {
                "updated_at": now_text(),
                "run_id": self.run_id,
                "sample_count": self.sample_count,
                "samples_path": str(self.samples_path),
                "top_slow_cases": list(self._slow_cases),
                "recent_failures": list(self._failures),
                "final_snapshot": dict(final_snapshot),
            },
        )


__all__ = [
    "DEFAULT_PERF_AUDIT_INTERVAL_SEC",
    "DEFAULT_PERF_AUDIT_MAX_BYTES",
    "DEFAULT_PERF_AUDIT_MAX_SAMPLES",
    "T04PerfAuditRecorder",
]
