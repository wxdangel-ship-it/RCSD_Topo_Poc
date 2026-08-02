from __future__ import annotations

import json
import logging
from pathlib import Path
import threading
import time
from typing import Mapping


PROGRESS_EVENT_VERSION = "p04-progress-v1"
_EVENT_INTERVAL_SECONDS = 30.0
_MIN_EVENT_INTERVAL_SECONDS = 1.0
_LOGGER = logging.getLogger(__name__)


class SegmentFirstProgressTracker:
    """Thread-safe actual-work progress for one formal P04 run."""

    def __init__(self, run_id: str, event_path: Path) -> None:
        self.run_id = str(run_id)
        self.event_path = event_path
        self._lock = threading.RLock()
        self._run_started = time.monotonic()
        self._stage_started = self._run_started
        self._stage = "initializing"
        self._detail = ""
        self._completed = 0
        self._total = 0
        self._last_unit = ""
        self._last_progress = self._run_started
        self._last_event = 0.0
        self._last_percent_bucket = -1
        self._counters: dict[str, int | float | str] = {}
        self._invocations: dict[str, int] = {}
        self._stage_invocation = 0
        self._stage_sequence = 0
        event_path.parent.mkdir(parents=True, exist_ok=True)
        event_path.touch(exist_ok=False)
        self._emit_locked("run_started", force=True)

    def begin_stage(
        self,
        stage: str,
        total: int,
        *,
        detail: str = "",
        counters: Mapping[str, int | float | str] | None = None,
    ) -> dict[str, object]:
        with self._lock:
            now = time.monotonic()
            self._stage = str(stage)
            self._detail = str(detail)
            self._completed = 0
            self._total = max(0, int(total))
            self._last_unit = ""
            self._stage_started = now
            self._last_progress = now
            self._last_event = 0.0
            self._last_percent_bucket = -1
            self._counters = dict(counters or {})
            self._stage_sequence += 1
            self._stage_invocation = self._invocations.get(self._stage, 0) + 1
            self._invocations[self._stage] = self._stage_invocation
            self._emit_locked("stage_started", force=True)
            return self._snapshot_locked(now)

    def advance(
        self,
        stage: str,
        *,
        amount: int = 1,
        completed: int | None = None,
        last_unit: object = "",
        counters: Mapping[str, int | float | str] | None = None,
    ) -> dict[str, object]:
        with self._lock:
            if self._stage != str(stage):
                return self._snapshot_locked(time.monotonic())
            previous = self._completed
            next_completed = (
                int(completed)
                if completed is not None
                else previous + int(amount)
            )
            self._completed = max(previous, min(next_completed, self._total))
            if last_unit not in (None, ""):
                self._last_unit = str(last_unit)
            if counters:
                self._counters.update(counters)
            now = time.monotonic()
            if self._completed > previous:
                self._last_progress = now
            self._emit_locked("stage_progress")
            return self._snapshot_locked(now)

    def finish_stage(
        self,
        stage: str,
        *,
        counters: Mapping[str, int | float | str] | None = None,
    ) -> dict[str, object]:
        with self._lock:
            if self._stage != str(stage):
                return self._snapshot_locked(time.monotonic())
            self._completed = self._total
            if counters:
                self._counters.update(counters)
            now = time.monotonic()
            self._last_progress = now
            self._emit_locked("stage_completed", force=True)
            return self._snapshot_locked(now)

    def fail(self, error: BaseException) -> dict[str, object]:
        with self._lock:
            self._counters["error_type"] = type(error).__name__
            self._counters["error_message"] = str(error)
            self._emit_locked("run_failed", force=True)
            return self._snapshot_locked(time.monotonic())

    def complete_run(
        self,
        *,
        counters: Mapping[str, int | float | str] | None = None,
    ) -> dict[str, object]:
        with self._lock:
            if counters:
                self._counters.update(counters)
            self._emit_locked("run_completed", force=True)
            return self._snapshot_locked(time.monotonic())

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._snapshot_locked(time.monotonic())

    def _snapshot_locked(self, now: float) -> dict[str, object]:
        elapsed = max(0.0, now - self._stage_started)
        rate = self._completed / elapsed if elapsed > 0.0 else 0.0
        remaining = max(0, self._total - self._completed)
        eta = remaining / rate if rate > 0.0 else None
        percentage = (
            100.0 * self._completed / self._total
            if self._total
            else 100.0
        )
        return {
            "version": PROGRESS_EVENT_VERSION,
            "run_id": self.run_id,
            "stage_sequence": self._stage_sequence,
            "stage": self._stage,
            "stage_invocation": self._stage_invocation,
            "detail": self._detail,
            "completed": self._completed,
            "total": self._total,
            "percentage": percentage,
            "overall_estimate": None,
            "last_unit": self._last_unit,
            "stage_elapsed_seconds": elapsed,
            "seconds_since_progress": max(0.0, now - self._last_progress),
            "rate_per_second": rate,
            "eta_seconds": eta,
            "counters": dict(self._counters),
            "event_path": str(self.event_path),
        }

    def _emit_locked(self, event_type: str, *, force: bool = False) -> None:
        now = time.monotonic()
        percent_bucket = (
            int(100 * self._completed / self._total)
            if self._total
            else 100
        )
        if not force:
            event_age = now - self._last_event
            heartbeat_due = event_age >= _EVENT_INTERVAL_SECONDS
            percent_advanced = percent_bucket > self._last_percent_bucket
            percent_emit_due = (
                percent_advanced
                and event_age >= _MIN_EVENT_INTERVAL_SECONDS
            )
            if not heartbeat_due and not percent_emit_due:
                return
        payload = self._snapshot_locked(now)
        payload["event_type"] = event_type
        payload["run_elapsed_seconds"] = max(0.0, now - self._run_started)
        with self.event_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")
        _LOGGER.info(
            "actual progress event=%s; stage=%s#%s; units=%s/%s; "
            "last=%s; detail=%s; counters=%s",
            event_type,
            payload["stage"],
            payload["stage_invocation"],
            payload["completed"],
            payload["total"],
            payload["last_unit"] or "-",
            payload["detail"] or "-",
            payload["counters"] or "-",
        )
        self._last_event = now
        self._last_percent_bucket = percent_bucket


_TRACKER: SegmentFirstProgressTracker | None = None
_TRACKER_LOCK = threading.RLock()


def configure_progress(run_id: str, event_path: Path) -> SegmentFirstProgressTracker:
    global _TRACKER
    with _TRACKER_LOCK:
        _TRACKER = SegmentFirstProgressTracker(run_id, event_path)
        return _TRACKER


def reset_progress() -> None:
    global _TRACKER
    with _TRACKER_LOCK:
        _TRACKER = None


def begin_progress_stage(
    stage: str,
    total: int,
    *,
    detail: str = "",
    counters: Mapping[str, int | float | str] | None = None,
) -> dict[str, object]:
    tracker = _TRACKER
    return (
        tracker.begin_stage(stage, total, detail=detail, counters=counters)
        if tracker is not None
        else _empty_snapshot(stage, total, detail)
    )


def advance_progress(
    stage: str,
    *,
    amount: int = 1,
    completed: int | None = None,
    last_unit: object = "",
    counters: Mapping[str, int | float | str] | None = None,
) -> dict[str, object]:
    tracker = _TRACKER
    return (
        tracker.advance(
            stage,
            amount=amount,
            completed=completed,
            last_unit=last_unit,
            counters=counters,
        )
        if tracker is not None
        else _empty_snapshot(stage, 0, "")
    )


def finish_progress_stage(
    stage: str,
    *,
    counters: Mapping[str, int | float | str] | None = None,
) -> dict[str, object]:
    tracker = _TRACKER
    return (
        tracker.finish_stage(stage, counters=counters)
        if tracker is not None
        else _empty_snapshot(stage, 0, "")
    )


def fail_progress(error: BaseException) -> dict[str, object]:
    tracker = _TRACKER
    return (
        tracker.fail(error)
        if tracker is not None
        else _empty_snapshot("failed", 0, "")
    )


def complete_progress(
    *,
    counters: Mapping[str, int | float | str] | None = None,
) -> dict[str, object]:
    tracker = _TRACKER
    return (
        tracker.complete_run(counters=counters)
        if tracker is not None
        else _empty_snapshot("completed", 0, "")
    )


def progress_snapshot() -> dict[str, object]:
    tracker = _TRACKER
    return (
        tracker.snapshot()
        if tracker is not None
        else _empty_snapshot("not_started", 0, "")
    )


def format_progress_snapshot(snapshot: Mapping[str, object]) -> str:
    total = int(snapshot.get("total", 0) or 0)
    completed = int(snapshot.get("completed", 0) or 0)
    percentage = float(snapshot.get("percentage", 0.0) or 0.0)
    eta = snapshot.get("eta_seconds")
    counters = snapshot.get("counters") or {}
    rendered_counters = ",".join(
        f"{key}={value}" for key, value in sorted(dict(counters).items())
    )
    return (
        f"stage={snapshot.get('stage', 'unknown')}"
        f"#{snapshot.get('stage_invocation', 0)}; "
        f"units={completed}/{total}({percentage:.1f}%); "
        f"rate={float(snapshot.get('rate_per_second', 0.0) or 0.0):.2f}/s; "
        f"eta={_format_duration(eta)}; "
        f"last={snapshot.get('last_unit', '') or '-'}; "
        f"detail={snapshot.get('detail', '') or '-'}; "
        f"counters={rendered_counters or '-'}"
    )


def _format_duration(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "estimating"
    seconds = max(0, int(value))
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _empty_snapshot(stage: str, total: int, detail: str) -> dict[str, object]:
    return {
        "version": PROGRESS_EVENT_VERSION,
        "run_id": "",
        "stage_sequence": 0,
        "stage": stage,
        "stage_invocation": 0,
        "detail": detail,
        "completed": 0,
        "total": total,
        "percentage": 0.0,
        "overall_estimate": None,
        "last_unit": "",
        "stage_elapsed_seconds": 0.0,
        "seconds_since_progress": 0.0,
        "rate_per_second": 0.0,
        "eta_seconds": None,
        "counters": {},
        "event_path": "",
    }


__all__ = [
    "PROGRESS_EVENT_VERSION",
    "SegmentFirstProgressTracker",
    "advance_progress",
    "begin_progress_stage",
    "complete_progress",
    "configure_progress",
    "fail_progress",
    "finish_progress_stage",
    "format_progress_snapshot",
    "progress_snapshot",
    "reset_progress",
]
