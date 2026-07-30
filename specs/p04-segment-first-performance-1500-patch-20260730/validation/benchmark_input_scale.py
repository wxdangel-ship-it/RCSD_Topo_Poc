from __future__ import annotations

import argparse
import ctypes
import gc
import json
import os
import platform
import sys
import threading
import time
from ctypes import wintypes
from pathlib import Path
from typing import Any


NATIVE_THREAD_ENV = (
    "OPENBLAS_NUM_THREADS",
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "NUMEXPR_MAX_THREADS",
    "GDAL_NUM_THREADS",
)
PATCH_LAYERS = (
    ("patch_roads", "Road.geojson", False),
    ("patch_lanes", "Lane.geojson", False),
    ("patch_boundaries", "LaneBoundary.geojson", False),
    ("patch_lane_topo", "LaneNextLane.geojson", True),
    ("patch_road_next_road", "RoadNextRoad.geojson", True),
    ("patch_intersections", "Intersection.geojson", False),
    ("drivezones", ("DriveZone_fix.geojson", "DriveZone.geojson"), False),
    ("divstripzones", ("DivStripZone_fix.geojson", "DivStripZone.geojson"), False),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="P04 Segment-first Patch 输入规模化验证；不运行正式业务流水线。",
    )
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--patch-root", type=Path, required=True)
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--analysis-crs", default="EPSG:32650")
    parser.add_argument("--source-real-patch-count", type=int, default=0)
    parser.add_argument("--target-peak-rss-gib", type=float, default=8.0)
    parser.add_argument("--hard-peak-rss-gib", type=float, default=16.0)
    parser.add_argument("--sample-seconds", type=float, default=5.0)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    return parser.parse_args()


class _WindowsMemoryCounters(ctypes.Structure):
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
        ("PrivateUsage", ctypes.c_size_t),
    ]


def _windows_memory() -> dict[str, int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_WindowsMemoryCounters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = _WindowsMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    succeeded = psapi.GetProcessMemoryInfo(
        kernel32.GetCurrentProcess(),
        ctypes.byref(counters),
        counters.cb,
    )
    if not succeeded:
        raise ctypes.WinError(ctypes.get_last_error())
    return {
        "rss_bytes": int(counters.WorkingSetSize),
        "peak_rss_bytes": int(counters.PeakWorkingSetSize),
        "private_bytes": int(counters.PrivateUsage),
        "peak_pagefile_bytes": int(counters.PeakPagefileUsage),
    }


def _linux_memory() -> dict[str, int]:
    values: dict[str, int] = {}
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        key, separator, raw_value = line.partition(":")
        if separator and key in {"VmRSS", "VmHWM", "VmSize", "VmPeak"}:
            values[key] = int(raw_value.strip().split()[0]) * 1024
    return {
        "rss_bytes": values.get("VmRSS", 0),
        "peak_rss_bytes": values.get("VmHWM", 0),
        "private_bytes": values.get("VmSize", 0),
        "peak_pagefile_bytes": values.get("VmPeak", 0),
    }


def process_memory() -> dict[str, int]:
    if os.name == "nt":
        return _windows_memory()
    if Path("/proc/self/status").is_file():
        return _linux_memory()
    return {
        "rss_bytes": 0,
        "peak_rss_bytes": 0,
        "private_bytes": 0,
        "peak_pagefile_bytes": 0,
    }


class ProgressSampler:
    def __init__(
        self,
        *,
        started_wall: float,
        started_cpu: float,
        sample_seconds: float,
        heartbeat_seconds: float,
    ) -> None:
        self.started_wall = started_wall
        self.started_cpu = started_cpu
        self.sample_seconds = sample_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.current_stage = "startup"
        self.timeline: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            name="p04-input-scale-sampler",
            daemon=True,
        )

    def start(self) -> None:
        self._thread.start()
        self.sample("start", emit=True)

    def stop(self) -> None:
        self._stop_event.set()
        self._thread.join(timeout=max(1.0, self.sample_seconds * 2.0))

    def set_stage(self, stage: str) -> None:
        with self._lock:
            self.current_stage = stage
        self.sample(f"{stage}_start", emit=True)

    def sample(self, label: str, *, emit: bool) -> dict[str, Any]:
        with self._lock:
            stage = self.current_stage
        item = {
            "label": label,
            "stage": stage,
            "elapsed_seconds": round(time.perf_counter() - self.started_wall, 3),
            "cpu_seconds": round(time.process_time() - self.started_cpu, 3),
            **process_memory(),
        }
        with self._lock:
            self.timeline.append(item)
        if emit:
            print(
                "[P04 input scale] "
                f"{label}: stage={stage}, "
                f"elapsed={item['elapsed_seconds']:.1f}s, "
                f"cpu={item['cpu_seconds']:.1f}s, "
                f"rss={item['rss_bytes'] / 1024**3:.3f}GiB, "
                f"peak={item['peak_rss_bytes'] / 1024**3:.3f}GiB",
                flush=True,
            )
        return item

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.timeline)

    def _run(self) -> None:
        next_heartbeat = time.monotonic() + self.heartbeat_seconds
        while not self._stop_event.wait(self.sample_seconds):
            now = time.monotonic()
            emit = now >= next_heartbeat
            self.sample("heartbeat" if emit else "sample", emit=emit)
            if emit:
                next_heartbeat = now + self.heartbeat_seconds


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> int:
    args = parse_args()
    for name in NATIVE_THREAD_ENV:
        os.environ.setdefault(name, "1")
    os.environ.setdefault("CPL_MAX_ERROR_REPORTS", "100")

    repo_root = args.repo_root.resolve()
    patch_root = args.patch_root.resolve()
    report_path = args.report_path.resolve()
    sys.path.insert(0, str(repo_root / "src"))

    from rcsd_topo_poc.modules.p04_road_direct_generation.io import (
        build_input_manifest,
        discover_patch_dirs,
    )
    from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_inputs import (
        _consumed_patch_inputs,
        _load_patch_layer,
    )

    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    sampler = ProgressSampler(
        started_wall=started_wall,
        started_cpu=started_cpu,
        sample_seconds=args.sample_seconds,
        heartbeat_seconds=args.heartbeat_seconds,
    )
    report: dict[str, Any] = {
        "benchmark_type": "p04_segment_first_input_scale_reuse",
        "business_scope": (
            "input discovery/read/CRS/concat/manifest only; "
            "not full business pipeline"
        ),
        "limitations": [
            "合成 Patch 若复用少量真实 Vector，驻留行数可代表重复倍数，数据分布不代表内网全量。",
            "文件系统缓存与重复文件内容会使 I/O 和哈希时间成为偏乐观下界。",
            "本验证不替代约 1500 Patch 的内网正式端到端验收。",
        ],
        "patch_root": str(patch_root),
        "analysis_crs": args.analysis_crs,
        "runtime": {
            "python": sys.version,
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
            "native_thread_env": {
                name: os.environ.get(name)
                for name in (*NATIVE_THREAD_ENV, "CPL_MAX_ERROR_REPORTS")
            },
        },
        "status": "running",
    }
    sampler.start()
    frames: dict[str, Any] = {}
    try:
        sampler.set_stage("patch_discovery")
        patch_dirs = discover_patch_dirs(
            patch_root,
            allow_equivalent_vector_fallback=True,
        )
        report["synthetic_patch_count"] = len(patch_dirs)
        report["source_real_patch_count"] = args.source_real_patch_count
        if args.source_real_patch_count > 0:
            report["reuse_multiplier"] = (
                len(patch_dirs) / args.source_real_patch_count
            )
        sampler.sample("patch_discovery_complete", emit=True)

        stages: list[dict[str, Any]] = []
        for layer_name, filenames, geometry_optional in PATCH_LAYERS:
            sampler.set_stage(layer_name)
            stage_wall = time.perf_counter()
            stage_cpu = time.process_time()
            before = process_memory()
            frame = _load_patch_layer(
                patch_dirs,
                filenames,
                args.analysis_crs,
                geometry_optional=geometry_optional,
            )
            frames[layer_name] = frame
            after = process_memory()
            stage = {
                "layer": layer_name,
                "filenames": (
                    list(filenames)
                    if isinstance(filenames, tuple)
                    else [filenames]
                ),
                "row_count": len(frame),
                "column_count": len(frame.columns),
                "crs": str(frame.crs),
                "wall_seconds": round(time.perf_counter() - stage_wall, 3),
                "cpu_seconds": round(time.process_time() - stage_cpu, 3),
                "rss_before_bytes": before["rss_bytes"],
                "rss_after_bytes": after["rss_bytes"],
                "rss_delta_bytes": after["rss_bytes"] - before["rss_bytes"],
                "peak_rss_bytes": after["peak_rss_bytes"],
                "pandas_deep_bytes": int(
                    frame.memory_usage(index=True, deep=True).sum()
                ),
            }
            stages.append(stage)
            sampler.sample(
                f"{layer_name}_complete_rows_{len(frame)}",
                emit=True,
            )
        report["layer_stages"] = stages
        report["total_loaded_rows"] = sum(
            item["row_count"] for item in stages
        )
        report["total_pandas_deep_bytes"] = sum(
            item["pandas_deep_bytes"] for item in stages
        )

        sampler.set_stage("input_manifest")
        manifest_wall = time.perf_counter()
        manifest_cpu = time.process_time()
        patch_inputs = _consumed_patch_inputs(patch_dirs)
        report["consumed_patch_input_count"] = len(patch_inputs)
        manifest = build_input_manifest(
            run_id=report_path.stem,
            patch_dirs=patch_dirs,
            external_inputs={},
            parameters={
                "analysis_crs": args.analysis_crs,
                "patch_read_workers": 6,
                "benchmark_only": True,
            },
            patch_inputs=patch_inputs,
        )
        report["manifest"] = {
            "input_file_count": manifest["input_file_count"],
            "input_total_bytes": manifest["input_total_bytes"],
            "wall_seconds": round(
                time.perf_counter() - manifest_wall,
                3,
            ),
            "cpu_seconds": round(time.process_time() - manifest_cpu, 3),
        }
        sampler.sample("manifest_complete", emit=True)

        gc.collect()
        final_memory = sampler.sample("benchmark_complete", emit=True)
        report["status"] = "completed"
        report["final_memory"] = final_memory
        peak_rss_bytes = max(
            item["peak_rss_bytes"] for item in sampler.snapshot()
        )
        report["budget_assessment"] = {
            "target_peak_rss_gib": args.target_peak_rss_gib,
            "hard_peak_rss_gib": args.hard_peak_rss_gib,
            "peak_rss_gib": round(peak_rss_bytes / 1024**3, 3),
            "target_pass": (
                peak_rss_bytes <= args.target_peak_rss_gib * 1024**3
            ),
            "hard_pass": (
                peak_rss_bytes < args.hard_peak_rss_gib * 1024**3
            ),
        }
        return_code = 0
    except Exception as error:
        report["status"] = "failed"
        report["error_type"] = type(error).__name__
        report["error"] = str(error)
        sampler.sample("benchmark_failed", emit=True)
        return_code = 1
    finally:
        sampler.stop()
        report["timeline"] = sampler.snapshot()
        report["total_wall_seconds"] = round(
            time.perf_counter() - started_wall,
            3,
        )
        report["total_cpu_seconds"] = round(
            time.process_time() - started_cpu,
            3,
        )
        _write_report(report_path, report)
        print(f"[P04 input scale] report={report_path}", flush=True)
        print(
            json.dumps(
                {
                    "status": report["status"],
                    "total_wall_seconds": report["total_wall_seconds"],
                    "total_cpu_seconds": report["total_cpu_seconds"],
                    "total_loaded_rows": report.get("total_loaded_rows"),
                    "budget_assessment": report.get("budget_assessment"),
                    "manifest_file_count": report.get(
                        "manifest",
                        {},
                    ).get("input_file_count"),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
