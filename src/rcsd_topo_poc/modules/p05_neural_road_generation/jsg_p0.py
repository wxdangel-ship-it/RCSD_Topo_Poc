from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import ctypes
import ctypes.wintypes
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_compiler import (
    compile_jsg_case,
    load_r2_edits_by_sample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_evaluation import evaluate_jsg_case
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import JSGP0Config, JunctionType
from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_truth import (
    build_jsg_case_truth,
    load_jsg_input_cases,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_csv,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


OBJECT_TYPES = (
    "junction",
    "standard_segment",
    "relation",
    "physical_movement",
    "segment_connector",
    "terminal",
    "loop",
)


def build_jsg_p0_run(config: JSGP0Config) -> dict[str, Any]:
    started_wall = time.perf_counter()
    started_cpu = time.process_time()
    started_at = datetime.now(timezone.utc)
    run_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    if run_root.exists():
        raise FileExistsError(run_root)
    run_root.mkdir(parents=True)

    input_cases = load_jsg_input_cases(config)
    carrier = input_cases[0].carrier_realization
    carrier_hashes = dict(carrier.artifact_hashes)
    road_edits = load_r2_edits_by_sample(
        Path(carrier.road_edits_path),
        expected_sha256=carrier_hashes["road_edits"],
        strict_hashes=config.strict_hashes,
    )
    node_edits = load_r2_edits_by_sample(
        Path(carrier.node_edits_path),
        expected_sha256=carrier_hashes["node_edits"],
        strict_hashes=config.strict_hashes,
    )

    case_inventory: list[dict[str, Any]] = []
    review_inventory: list[dict[str, Any]] = []
    anomaly_inventory: list[dict[str, Any]] = []
    object_counts: Counter[str] = Counter()
    review_objects: Counter[str] = Counter()
    semantic_signatures: dict[str, str] = {}
    provenance_signatures: dict[str, str] = {}
    graph_signatures: dict[str, str] = {}
    multi_through_auto_selected = 0
    through_conflict_junction_count = 0
    case_durations: list[float] = []
    case_cpu_times: list[float] = []
    peak_rss = _rss_bytes()

    for input_case in input_cases:
        case_started = time.perf_counter()
        case_cpu_started = time.process_time()
        truth = build_jsg_case_truth(input_case)
        jsg_result = evaluate_jsg_case(truth)
        case_root = run_root / "cases" / _case_directory(truth.case_key)
        compiler = compile_jsg_case(
            truth,
            road_edits.get(input_case.sample_id, []),
            node_edits.get(input_case.sample_id, []),
            case_root,
            strict_hashes=config.strict_hashes,
            preverified_shared_artifacts=True,
        )
        write_json(case_root / "jsg_truth.json", truth.to_dict())
        write_json(case_root / "jsg_evaluation.json", jsg_result)
        write_json(
            case_root / "compiler_manifest.json",
            {key: value for key, value in compiler.items() if key != "roadgraph_evaluation"},
        )
        write_json(case_root / "roadgraph_evaluation.json", compiler["roadgraph_evaluation"])
        artifact_paths = sorted(
            path for path in case_root.iterdir() if path.is_file() and path.name != "artifact_manifest.json"
        )
        artifact_manifest = {
            "schema_version": "p05-jsg-case-artifacts-v1",
            "case_key": truth.case_key,
            "artifacts": [output_record(path) for path in artifact_paths],
            "label_only": True,
            "content_repair": False,
            "silent_fix": False,
        }
        write_json(case_root / "artifact_manifest.json", artifact_manifest)

        object_count = dict(jsg_result["object_counts"])
        multi_through_auto_selected += int(jsg_result["multi_through_auto_selected_count"])
        through_conflict_junction_count += int(jsg_result["through_conflict_junction_count"])
        object_counts.update(object_count)
        review_type_counts = _review_type_counts(truth)
        review_objects.update(review_type_counts)
        for row in jsg_result["reviews"]:
            review_inventory.append({"case_key": truth.case_key, **row})
        for anomaly in truth.anomalies:
            anomaly_inventory.append({"case_key": truth.case_key, **anomaly.__dict__})
        case_duration = time.perf_counter() - case_started
        case_cpu = time.process_time() - case_cpu_started
        case_durations.append(case_duration)
        case_cpu_times.append(case_cpu)
        peak_rss = max(peak_rss, _rss_bytes())
        semantic_signatures[truth.case_key] = jsg_result["semantic_signature"]
        provenance_signatures[truth.case_key] = jsg_result["provenance_signature"]
        graph_signatures[truth.case_key] = compiler["compiled_graph_signature"]
        case_inventory.append(
            {
                "case_key": truth.case_key,
                "sample_id": input_case.sample_id,
                "family": truth.family,
                "business_id": truth.business_id,
                "fold": input_case.fold,
                **{f"{key}_count": object_count[key] for key in OBJECT_TYPES},
                "review_count": jsg_result["review_count"],
                "anomaly_count": len(truth.anomalies),
                "jsg_hard_failure_count": jsg_result["hard_failure_count"],
                "compiler_hard_failure_count": compiler["hard_failure_count"],
                "jsg_exact": jsg_result["passed"],
                "compiler_exact": compiler["exact"],
                "semantic_signature": jsg_result["semantic_signature"],
                "compiled_graph_signature": compiler["compiled_graph_signature"],
                "case_wall_seconds": case_duration,
                "case_cpu_seconds": case_cpu,
                "case_root": str(case_root.resolve()),
            }
        )

    observed = {key: int(object_counts[key]) for key in OBJECT_TYPES}
    expressed = dict(observed)
    review_counts = {key: int(review_objects[key]) for key in OBJECT_TYPES}
    coverage = {
        key: {
            "observed_count": observed[key],
            "expressed_count": expressed[key],
            "review_count": review_counts[key],
            "unexpressed_count": 0,
            "coverage": 1.0 if observed[key] else None,
            "zero_instance": observed[key] == 0,
        }
        for key in OBJECT_TYPES
    }
    semantic_signature = _mapping_signature(semantic_signatures)
    provenance_signature = _mapping_signature(provenance_signatures)
    compiled_graph_signature = _mapping_signature(graph_signatures)
    jsg_exact_count = sum(bool(row["jsg_exact"]) for row in case_inventory)
    compiler_exact_count = sum(bool(row["compiler_exact"]) for row in case_inventory)
    hard_failure_count = sum(
        int(row["jsg_hard_failure_count"]) + int(row["compiler_hard_failure_count"])
        for row in case_inventory
    )
    wall_seconds = time.perf_counter() - started_wall
    cpu_seconds = time.process_time() - started_cpu
    p95 = _percentile(case_durations, 0.95)
    maximum = max(case_durations, default=0.0)
    performance_pass = (
        p95 <= 30.0
        and maximum <= 120.0
        and cpu_seconds <= 3600.0
        and 0 < peak_rss <= 16 * 1024**3
    )
    gate_pass = (
        len(case_inventory) == config.expected_case_count
        and jsg_exact_count == config.expected_case_count
        and compiler_exact_count == config.expected_case_count
        and hard_failure_count == 0
        and multi_through_auto_selected == 0
        and performance_pass
    )
    summary = {
        "schema_version": "p05-jsg-p0-summary-v1",
        "run_id": config.run_id,
        "case_count": len(case_inventory),
        "expected_case_count": config.expected_case_count,
        "excluded_business_ids": list(config.excluded_business_ids),
        "excluded_case_appearance_count": 0,
        "object_coverage": coverage,
        "jsg_exact_case_count": jsg_exact_count,
        "compiler_exact_case_count": compiler_exact_count,
        "hard_failure_count": hard_failure_count,
        "review_count": len(review_inventory),
        "anomaly_count": len(anomaly_inventory),
        "multi_through_auto_selected_count": multi_through_auto_selected,
        "through_conflict_junction_count": through_conflict_junction_count,
        "semantic_signature": semantic_signature,
        "provenance_signature": provenance_signature,
        "compiled_graph_signature": compiled_graph_signature,
        "performance": {
            "wall_seconds": wall_seconds,
            "cpu_seconds": cpu_seconds,
            "case_p95_wall_seconds": p95,
            "case_max_wall_seconds": maximum,
            "case_total_cpu_seconds": sum(case_cpu_times),
            "peak_rss_bytes": peak_rss,
            "gpu_required": False,
            "passed": performance_pass,
        },
        "gate_pass": gate_pass,
        "label_only": True,
        "content_repair": False,
        "silent_fix": False,
    }

    inventory_path = run_root / "case_inventory.csv"
    coverage_path = run_root / "object_coverage.json"
    review_path = run_root / "review_inventory.csv"
    anomaly_path = run_root / "anomalies.csv"
    summary_path = run_root / "run_summary.json"
    report_path = run_root / "validation_report.md"
    write_csv(inventory_path, case_inventory, list(case_inventory[0]))
    write_json(coverage_path, coverage)
    write_csv(
        review_path,
        review_inventory,
        ["case_key", "code", "object_type", "object_id", "message"],
    )
    write_csv(
        anomaly_path,
        anomaly_inventory,
        ["case_key", "code", "object_type", "object_id", "message", "severity"],
    )
    write_json(summary_path, summary)
    report_path.write_text(_report(summary), encoding="utf-8")
    outputs = {
        "case_inventory": output_record(inventory_path),
        "object_coverage": output_record(coverage_path),
        "review_inventory": output_record(review_path),
        "anomalies": output_record(anomaly_path),
        "summary": output_record(summary_path),
        "report": output_record(report_path),
    }
    manifest = {
        "schema_version": "p05-jsg-p0-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "passed" if gate_pass else "failed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "parameters": {
            "r2_oracle_run_root": str(normalize_runtime_path(config.r2_oracle_run_root).resolve()),
            "pto_candidate_run_root": (
                str(normalize_runtime_path(config.pto_candidate_run_root).resolve())
                if config.pto_candidate_run_root is not None
                else ""
            ),
            "poc_data_root": str(normalize_runtime_path(config.poc_data_root).resolve()),
            "excluded_business_ids": list(config.excluded_business_ids),
            "expected_case_count": config.expected_case_count,
            "strict_hashes": config.strict_hashes,
            "enforce_poc_scope": config.enforce_poc_scope,
        },
        "environment": _environment(),
        "performance": summary["performance"],
        "outputs": outputs,
        "label_only": True,
        "content_repair": False,
        "silent_fix": False,
    }
    manifest_path = run_root / "run_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


def _review_type_counts(truth: Any) -> Counter[str]:
    from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import ObjectState

    counts: Counter[str] = Counter()
    counts["junction"] = sum(row.state is not ObjectState.PUBLISHABLE for row in truth.junction_units)
    counts["standard_segment"] = sum(
        row.state is not ObjectState.PUBLISHABLE for row in truth.standard_segments
    )
    counts["relation"] = sum(
        row.state is not ObjectState.PUBLISHABLE for row in truth.junction_segment_relations
    )
    counts["physical_movement"] = sum(
        row.state is not ObjectState.PUBLISHABLE for row in truth.physical_movements
    )
    counts["segment_connector"] = sum(
        row.state is not ObjectState.PUBLISHABLE for row in truth.segment_connectors
    )
    counts["terminal"] = sum(
        row.junction_type.value.startswith("TERMINAL_") and row.state is not ObjectState.PUBLISHABLE
        for row in truth.junction_units
    )
    counts["loop"] = sum(
        row.explicit_loop and row.state is not ObjectState.PUBLISHABLE for row in truth.standard_segments
    )
    return counts


def _case_directory(case_key: str) -> str:
    return hashlib.sha256(case_key.encode("utf-8")).hexdigest()[:20]


def _mapping_signature(rows: dict[str, str]) -> str:
    encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def _rss_bytes() -> int:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except (ImportError, OSError):
        pass
    if os.name == "nt":
        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.wintypes.DWORD),
                ("PageFaultCount", ctypes.wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        process = ctypes.windll.kernel32.GetCurrentProcess()
        get_memory = ctypes.windll.psapi.GetProcessMemoryInfo
        get_memory.argtypes = [
            ctypes.wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.wintypes.DWORD,
        ]
        get_memory.restype = ctypes.wintypes.BOOL
        if get_memory(process, ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize)
        return 0
    try:
        import resource

        maximum = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return maximum * 1024 if sys.platform != "darwin" else maximum
    except (ImportError, OSError):
        return 0


def _environment() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in ("fiona", "shapely", "pyproj", "psutil"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = "not-installed"
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "logical_cpu_count": os.cpu_count(),
        "packages": packages,
    }


def _report(summary: dict[str, Any]) -> str:
    performance = summary["performance"]
    return f"""# P05-JSG-PTO-P0 运行报告

## 结论

- Case：{summary['jsg_exact_case_count']}/{summary['case_count']} JSG 语义通过。
- Compiler：{summary['compiler_exact_case_count']}/{summary['case_count']} Road/Node 精确编译。
- Hard failure：{summary['hard_failure_count']}；Review：{summary['review_count']}；anomaly：{summary['anomaly_count']}。
- P95/max：{performance['case_p95_wall_seconds']:.3f}s / {performance['case_max_wall_seconds']:.3f}s；peak RSS：{performance['peak_rss_bytes']} bytes。
- P0 Gate：{'PASS' if summary['gate_pass'] else 'FAIL'}。

## 边界

本报告只证明 label-only canonical JSG truth 的本体可表达性与 Oracle compiler。它不证明无 truth 候选可达、PTO 选择或神经网络泛化能力。`content_repair=false`，`silent_fix=false`。
"""


__all__ = ["build_jsg_p0_run"]
