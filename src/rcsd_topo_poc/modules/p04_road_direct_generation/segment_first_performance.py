from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


GIB = 1024**3
RSS_TARGET_BYTES = 8 * GIB
RSS_HARD_LIMIT_BYTES = 16 * GIB
WALL_TARGET_SECONDS = 6 * 60 * 60
WALL_HARD_LIMIT_SECONDS = 8 * 60 * 60
RESOURCE_TIMELINE_SECONDS = 30.0
MAX_RESOURCE_TIMELINE_SAMPLES = 1024
PATCH_IO_WORKERS_MAX = 6
NATIVE_THREAD_ENV_KEYS = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "NUMEXPR_MAX_THREADS",
    "GDAL_NUM_THREADS",
    "CPL_MAX_ERROR_REPORTS",
)


@dataclass(frozen=True)
class ProcessResourceSnapshot:
    wall_seconds: float
    process_cpu_seconds: float
    rss_bytes: int | None
    peak_rss_bytes: int | None
    read_bytes: int | None
    write_bytes: int | None


class SegmentFirstPerformanceMonitor:
    """Low-overhead process resource and sampled-hotspot monitor."""

    def __init__(self) -> None:
        self._started_wall = time.perf_counter()
        self._started_cpu = time.process_time()
        self._started_io = _process_io_bytes()
        self._peak_rss_bytes = 0
        self._sample_count = 0
        self._hotspots: Counter[str] = Counter()
        self._warnings_emitted: set[str] = set()
        self._resource_timeline: list[dict[str, Any]] = []

    def sample(self, *, active_location: str | None = None) -> ProcessResourceSnapshot:
        snapshot = self.snapshot()
        self._sample_count += 1
        if active_location:
            self._hotspots[active_location] += 1
        if snapshot.rss_bytes is not None:
            self._peak_rss_bytes = max(self._peak_rss_bytes, snapshot.rss_bytes)
        if snapshot.peak_rss_bytes is not None:
            self._peak_rss_bytes = max(
                self._peak_rss_bytes,
                snapshot.peak_rss_bytes,
            )
        self._record_timeline(snapshot, active_location=active_location)
        return snapshot

    def snapshot(self) -> ProcessResourceSnapshot:
        rss_bytes, native_peak_rss_bytes = _process_memory_bytes()
        read_bytes, write_bytes = _process_io_bytes()
        started_read, started_write = self._started_io
        return ProcessResourceSnapshot(
            wall_seconds=max(0.0, time.perf_counter() - self._started_wall),
            process_cpu_seconds=max(0.0, time.process_time() - self._started_cpu),
            rss_bytes=rss_bytes,
            peak_rss_bytes=native_peak_rss_bytes,
            read_bytes=_nonnegative_delta(read_bytes, started_read),
            write_bytes=_nonnegative_delta(write_bytes, started_write),
        )

    def new_warnings(self, snapshot: ProcessResourceSnapshot) -> tuple[str, ...]:
        candidates: list[tuple[str, str]] = []
        if snapshot.wall_seconds >= WALL_TARGET_SECONDS:
            candidates.append(
                (
                    "wall_target",
                    "elapsed time reached the 6h target; investigate current hotspot",
                )
            )
        if snapshot.wall_seconds >= WALL_HARD_LIMIT_SECONDS:
            candidates.append(
                (
                    "wall_hard_limit",
                    "elapsed time reached the 8h hard limit",
                )
            )
        observed_peak = max(
            self._peak_rss_bytes,
            snapshot.rss_bytes or 0,
            snapshot.peak_rss_bytes or 0,
        )
        if observed_peak >= RSS_TARGET_BYTES:
            candidates.append(
                (
                    "rss_target",
                    "peak RSS reached the 8 GiB target budget",
                )
            )
        if observed_peak >= RSS_HARD_LIMIT_BYTES:
            candidates.append(
                (
                    "rss_hard_limit",
                    "peak RSS reached the 16 GiB hard limit",
                )
            )
        fresh: list[str] = []
        for key, message in candidates:
            if key not in self._warnings_emitted:
                self._warnings_emitted.add(key)
                fresh.append(message)
        return tuple(fresh)

    def finish(self, *, active_location: str | None = None) -> dict[str, Any]:
        final = self.sample(active_location=active_location)
        self._record_timeline(
            final,
            active_location=active_location,
            force=True,
        )
        peak_rss_bytes = max(
            self._peak_rss_bytes,
            final.rss_bytes or 0,
            final.peak_rss_bytes or 0,
        )
        cpu_percent = (
            100.0 * final.process_cpu_seconds / final.wall_seconds
            if final.wall_seconds > 0.0
            else 0.0
        )
        hotspots = [
            {
                "location": location,
                "sample_count": count,
                "sample_ratio": count / self._sample_count,
            }
            for location, count in self._hotspots.most_common(20)
        ]
        return {
            "monitor_version": "p04-process-resource-v1",
            "wall_seconds": final.wall_seconds,
            "process_cpu_seconds": final.process_cpu_seconds,
            "average_process_cpu_percent": cpu_percent,
            "current_rss_bytes": final.rss_bytes,
            "peak_rss_bytes": peak_rss_bytes or None,
            "read_bytes": final.read_bytes,
            "write_bytes": final.write_bytes,
            "sample_count": self._sample_count,
            "sample_interval_seconds": None,
            "sampled_hotspots": hotspots,
            "resource_timeline": list(self._resource_timeline),
            "runtime_resources": runtime_resource_contract(),
            "budgets": {
                "wall_target_seconds": WALL_TARGET_SECONDS,
                "wall_hard_limit_seconds": WALL_HARD_LIMIT_SECONDS,
                "rss_target_bytes": RSS_TARGET_BYTES,
                "rss_hard_limit_bytes": RSS_HARD_LIMIT_BYTES,
            },
            "budget_state": {
                "wall_target_pass": final.wall_seconds <= WALL_TARGET_SECONDS,
                "wall_hard_limit_pass": final.wall_seconds <= WALL_HARD_LIMIT_SECONDS,
                "rss_target_pass": (
                    peak_rss_bytes <= RSS_TARGET_BYTES
                    if peak_rss_bytes
                    else None
                ),
                "rss_hard_limit_pass": (
                    peak_rss_bytes < RSS_HARD_LIMIT_BYTES
                    if peak_rss_bytes
                    else None
                ),
            },
        }

    def _record_timeline(
        self,
        snapshot: ProcessResourceSnapshot,
        *,
        active_location: str | None,
        force: bool = False,
    ) -> None:
        previous_wall = (
            float(self._resource_timeline[-1]["wall_seconds"])
            if self._resource_timeline
            else None
        )
        if previous_wall is not None:
            elapsed = snapshot.wall_seconds - previous_wall
            if not force and elapsed < RESOURCE_TIMELINE_SECONDS:
                return
            if force and elapsed <= 1e-6:
                return
        row = {
            "wall_seconds": snapshot.wall_seconds,
            "process_cpu_seconds": snapshot.process_cpu_seconds,
            "rss_bytes": snapshot.rss_bytes,
            "peak_rss_bytes": max(
                self._peak_rss_bytes,
                snapshot.peak_rss_bytes or 0,
            )
            or None,
            "read_bytes": snapshot.read_bytes,
            "write_bytes": snapshot.write_bytes,
            "active_location": active_location,
        }
        if len(self._resource_timeline) >= MAX_RESOURCE_TIMELINE_SAMPLES:
            if force:
                self._resource_timeline[-1] = row
            return
        self._resource_timeline.append(row)


def runtime_resource_contract() -> dict[str, Any]:
    return {
        "logical_cpu_count": os.cpu_count(),
        "patch_io_workers_max": PATCH_IO_WORKERS_MAX,
        "native_thread_limits": {
            name: os.environ.get(name)
            for name in NATIVE_THREAD_ENV_KEYS
        },
    }


def merge_performance_into_summary(
    summary_path: Path,
    performance: dict[str, Any],
) -> bool:
    """Merge launcher telemetry into an existing P04 summary atomically."""
    if not summary_path.is_file():
        return False
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    current = dict(payload.get("performance") or {})
    current.update(performance)
    payload["performance"] = current
    temporary = summary_path.with_suffix(summary_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, summary_path)
    return True


def active_p04_location(thread_id: int) -> str:
    frame = sys._current_frames().get(thread_id)
    if frame is None:
        return "unavailable"
    selected = frame
    while frame is not None:
        path = Path(frame.f_code.co_filename)
        if (
            (
                "p04_road_direct_generation" in path.parts
                and path.name != "segment_first_performance.py"
            )
            or path.name == "p04_run_segment_first_innernet.py"
        ):
            selected = frame
            break
        frame = frame.f_back
    return (
        f"{Path(selected.f_code.co_filename).name}:"
        f"{selected.f_code.co_name}:{selected.f_lineno}"
    )


def format_resource_snapshot(snapshot: ProcessResourceSnapshot) -> str:
    return (
        f"cpu={snapshot.process_cpu_seconds:.1f}s; "
        f"rss={_format_bytes(snapshot.rss_bytes)}; "
        f"peak_rss={_format_bytes(snapshot.peak_rss_bytes)}; "
        f"read={_format_bytes(snapshot.read_bytes)}; "
        f"write={_format_bytes(snapshot.write_bytes)}"
    )


def _process_memory_bytes() -> tuple[int | None, int | None]:
    if sys.platform.startswith("linux"):
        return _read_linux_memory()
    if sys.platform == "win32":
        return _read_windows_memory()
    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        if sys.platform != "darwin":
            peak *= 1024
        return None, peak
    except (ImportError, OSError, ValueError):
        return None, None


def _read_linux_memory() -> tuple[int | None, int | None]:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/self/status").read_text(
            encoding="ascii",
            errors="replace",
        ).splitlines():
            if line.startswith(("VmRSS:", "VmHWM:")):
                key, value, *_ = line.split()
                values[key.rstrip(":")] = int(value) * 1024
    except (OSError, ValueError):
        return None, None
    return values.get("VmRSS"), values.get("VmHWM")


def _read_windows_memory() -> tuple[int | None, int | None]:
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        success = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(),
            ctypes.byref(counters),
            counters.cb,
        )
        if not success:
            return None, None
        return int(counters.WorkingSetSize), int(counters.PeakWorkingSetSize)
    except (AttributeError, OSError, ValueError):
        return None, None


def _process_io_bytes() -> tuple[int | None, int | None]:
    if sys.platform.startswith("linux"):
        values: dict[str, int] = {}
        try:
            for line in Path("/proc/self/io").read_text(
                encoding="ascii",
                errors="replace",
            ).splitlines():
                key, value = line.split(":", maxsplit=1)
                if key in {"read_bytes", "write_bytes"}:
                    values[key] = int(value.strip())
        except (OSError, ValueError):
            return None, None
        return values.get("read_bytes"), values.get("write_bytes")
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            class IoCounters(ctypes.Structure):
                _fields_ = [
                    ("ReadOperationCount", ctypes.c_ulonglong),
                    ("WriteOperationCount", ctypes.c_ulonglong),
                    ("OtherOperationCount", ctypes.c_ulonglong),
                    ("ReadTransferCount", ctypes.c_ulonglong),
                    ("WriteTransferCount", ctypes.c_ulonglong),
                    ("OtherTransferCount", ctypes.c_ulonglong),
                ]

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentProcess.restype = wintypes.HANDLE
            kernel32.GetProcessIoCounters.argtypes = [
                wintypes.HANDLE,
                ctypes.POINTER(IoCounters),
            ]
            kernel32.GetProcessIoCounters.restype = wintypes.BOOL
            counters = IoCounters()
            success = kernel32.GetProcessIoCounters(
                kernel32.GetCurrentProcess(),
                ctypes.byref(counters),
            )
            if not success:
                return None, None
            return int(counters.ReadTransferCount), int(counters.WriteTransferCount)
        except (AttributeError, OSError, ValueError):
            return None, None
    return None, None


def _nonnegative_delta(
    current: int | None,
    started: int | None,
) -> int | None:
    if current is None or started is None:
        return None
    return max(0, current - started)


def _format_bytes(value: int | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value / (1024**2):.1f}MiB"


__all__ = [
    "ProcessResourceSnapshot",
    "PATCH_IO_WORKERS_MAX",
    "SegmentFirstPerformanceMonitor",
    "active_p04_location",
    "format_resource_snapshot",
    "merge_performance_into_summary",
    "runtime_resource_contract",
]
