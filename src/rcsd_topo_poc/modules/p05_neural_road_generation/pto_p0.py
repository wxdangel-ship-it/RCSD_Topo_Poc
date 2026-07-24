from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from rcsd_topo_poc.modules.p05_neural_road_generation.evaluation import evaluate_frcsd
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_csv, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_lineage import read_json, resolved_path
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_models import PTOOracleSolveConfig
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_solver import solve_oracle_case
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import read_vector_payloads, write_vector_payloads


_EXPECTED_COUNTS = {
    "FINAL_ROAD": 23224,
    "FINAL_NODE": 27553,
    "T05_NODE": 24739,
    "T05_POINTER": 4760,
    "SPLIT_CHILD": 1730,
}


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return [dict(row) for row in csv.DictReader(stream)]


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, raw in enumerate(stream, start=1):
            if not raw.strip():
                continue
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError(f"expected JSON object at {path}:{line_number}")
            yield payload


def _append_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _resolved_output(root: Path, record: dict[str, Any], *, strict_hashes: bool) -> Path:
    path = resolved_path(str(record.get("path") or ""))
    if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"artifact hash mismatch: {path}")
    return path


def _sha(payload: Any) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _split_lineage_child_count(edits: Iterable[dict[str, Any]]) -> int:
    child_ids: set[str] = set()
    for edit in edits:
        for payload in edit.get("output_payloads") or []:
            properties = {str(key).casefold(): value for key, value in dict(payload.get("properties") or {}).items()}
            if str(properties.get("t06_split_original_road_id") or "").strip():
                child_ids.add(str(payload["id"]))
    return len(child_ids)


def _case_key(family: str, business_id: str) -> str:
    return hashlib.sha256(f"{family}:{business_id}".encode("utf-8")).hexdigest()[:20]


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, math_ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def math_ceil(value: float) -> int:
    integer = int(value)
    return integer if value == integer else integer + 1


def _process_rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process(os.getpid()).memory_info().rss)
    except (ImportError, OSError):
        if os.name != "nt":
            return None
    try:
        import ctypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("PageFaultCount", ctypes.c_ulong),
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
        get_current_process = ctypes.windll.kernel32.GetCurrentProcess
        get_current_process.restype = ctypes.c_void_p
        get_process_memory_info = ctypes.windll.kernel32.K32GetProcessMemoryInfo
        get_process_memory_info.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ProcessMemoryCounters),
            ctypes.c_ulong,
        ]
        get_process_memory_info.restype = ctypes.c_int
        if not get_process_memory_info(get_current_process(), ctypes.byref(counters), counters.cb):
            return None
        return int(counters.WorkingSetSize)
    except (AttributeError, OSError):
        return None


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


def _load_candidate_run(config: PTOOracleSolveConfig) -> tuple[Path, dict[str, Any], dict[tuple[str, str], list[dict[str, Any]]], dict[tuple[str, str], dict[str, str]]]:
    root = resolved_path(config.candidate_run_root)
    manifest_path = root / "p05_pto_candidate_manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("status") != "candidate_scope_passed":
        raise ValueError("candidate run did not pass scope gate")
    if manifest.get("truth_input_count") != 0 or manifest.get("truth_derived_candidate_count") != 0:
        raise ValueError("candidate manifest declares truth leakage")
    if manifest.get("silent_fix") is not False:
        raise ValueError("candidate manifest must declare silent_fix=false")
    outputs = dict(manifest.get("outputs") or {})
    candidate_path = _resolved_output(root, dict(outputs["candidates"]), strict_hashes=config.strict_hashes)
    case_index_path = _resolved_output(root, dict(outputs["case_index"]), strict_hashes=config.strict_hashes)
    by_scope: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for candidate in _read_jsonl(candidate_path):
        by_scope[(str(candidate["family"]), str(candidate["business_id"]))].append(candidate)
    index = {
        (str(row["family"]), str(row["business_id"])): row
        for row in _read_csv(case_index_path)
    }
    if len(by_scope) != config.expected_case_count or set(by_scope) != set(index):
        raise ValueError(f"candidate run scope mismatch: candidates={len(by_scope)}, index={len(index)}")
    return manifest_path, manifest, by_scope, index


def _load_r2_oracle(config: PTOOracleSolveConfig) -> tuple[Path, dict[str, Any], dict[tuple[str, str], dict[str, str]], dict[str, dict[str, list[dict[str, Any]]]], dict[str, list[dict[str, str]]]]:
    root = resolved_path(config.r2_oracle_run_root)
    manifest_path = root / "p05_r2_oracle_manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("status") != "gate1_passed" or manifest.get("silent_fix") is not False:
        raise ValueError("R2 oracle run is not a passed no-silent-fix Gate 1 run")
    outputs = dict(manifest.get("outputs") or {})
    paths = {
        role: _resolved_output(root, dict(outputs[role]), strict_hashes=config.strict_hashes)
        for role in ("case_index", "road_edits", "node_edits", "t05_node_edits", "t05_pointers")
    }
    case_rows = _read_csv(paths["case_index"])
    by_scope = {(row["family"], row["business_id"]): row for row in case_rows}
    if len(by_scope) != config.expected_case_count:
        raise ValueError(f"R2 oracle scope requires {config.expected_case_count} cases, got {len(by_scope)}")
    edits: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for stage, role in (("FINAL_ROAD", "road_edits"), ("FINAL_NODE", "node_edits"), ("T05_NODE", "t05_node_edits")):
        for edit in _read_jsonl(paths[role]):
            if edit.get("label_only") is not True:
                raise ValueError(f"R2 oracle edit is not label_only: {role}")
            edits[str(edit["sample_id"])][stage].append(edit)
    pointers: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv(paths["t05_pointers"]):
        if str(row.get("label_only") or "").casefold() != "true":
            raise ValueError("R2 pointer is not label_only")
        pointers[row["sample_id"]].append(row)
    return manifest_path, manifest, by_scope, edits, pointers


def _evaluation_exact(evaluation: dict[str, Any]) -> bool:
    attributes = dict(evaluation.get("attributes") or {})
    return (
        float(dict(evaluation.get("road_object") or {}).get("f1", 0.0)) == 1.0
        and float(dict(evaluation.get("node_object") or {}).get("f1", 0.0)) == 1.0
        and float(dict(evaluation.get("directed_topology") or {}).get("f1", 0.0)) == 1.0
        and all(float(attributes.get(name, 0.0)) == 1.0 for name in ("direction_accuracy", "source_accuracy", "endpoint_semantic_accuracy"))
        and bool(dict(evaluation.get("crs") or {}).get("compatible"))
        and not list(evaluation.get("hard_failures") or [])
    )


def _report(summary: dict[str, Any]) -> str:
    return f"""# P05-PTO-P0 Candidate Reachability 与 Oracle-cost 报告

## 结论

- Case：{summary['case_count']}/51；排除项出现：{summary['excluded_occurrence_count']}。
- Gate 1 candidate reachability：{'PASS' if summary['gate1_candidate_reachability_pass'] else 'FAIL'}。
- Gate 2 Oracle-cost solve：{'PASS' if summary['gate2_oracle_solve_pass'] else 'FAIL'}。
- Road/最终 Node/T05 Node/pointer/SPLIT child：{summary['truth_counts']}。
- OPTIMAL 且 gap=0：{summary['optimal_case_count']}/{summary['case_count']}。
- 精确 Road/Node/属性/有向拓扑：{summary['semantic_exact_case_count']}/{summary['case_count']}。
- 候选 build+solve P95：{summary['candidate_build_plus_solve_p95_seconds']:.3f}s；含策略 replay 端到端 P95：{summary['end_to_end_p95_seconds']:.3f}s。
- 性能门禁：{'PASS' if summary['performance_gate_pass'] else 'FAIL'}。

## 边界

候选 manifest 在 truth 接入前冻结，`truth_input_count=0`、`truth_derived_candidate_count=0`。Oracle cost 只证明正确组合位于有限候选空间并可由通用约束精确选出；它不是训练模型或生产评分器。`relaxation=false`、`content_repair=false`、`silent_fix=false`。
"""


def solve_pto_oracle_run(config: PTOOracleSolveConfig) -> dict[str, Any]:
    started = time.perf_counter()
    cpu_started = time.process_time()
    started_at = datetime.now(timezone.utc)
    candidate_manifest_path, candidate_manifest, candidates_by_scope, candidate_index = _load_candidate_run(config)
    r2_manifest_path, _, truth_by_scope, edits_by_sample, pointers_by_sample = _load_r2_oracle(config)
    if set(candidates_by_scope) != set(truth_by_scope):
        missing = sorted(set(truth_by_scope) - set(candidates_by_scope))
        extra = sorted(set(candidates_by_scope) - set(truth_by_scope))
        raise ValueError(f"candidate/oracle scope mismatch: missing={missing}, extra={extra}")

    target_root = resolved_path(config.output_root, strict=False) / config.run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)
    cost_path = target_root / "p05_pto_oracle_costs.jsonl"
    certificate_path = target_root / "p05_pto_solve_certificates.jsonl"
    cost_path.touch()
    certificate_path.touch()
    case_index: list[dict[str, Any]] = []
    case_metrics: list[dict[str, Any]] = []
    truth_counts: Counter[str] = Counter()
    represented_counts: Counter[str] = Counter()
    optimal_cases = semantic_exact_cases = 0
    hard_failure_count = 0
    rss_samples = [value for value in [_process_rss_bytes()] if value is not None]

    for scope in sorted(candidates_by_scope):
        family, business_id = scope
        oracle_case = truth_by_scope[scope]
        oracle_sample_id = oracle_case["sample_id"]
        solve_started = time.perf_counter()
        result = solve_oracle_case(
            candidates_by_scope[scope],
            dict(edits_by_sample[oracle_sample_id]),
            list(pointers_by_sample[oracle_sample_id]),
        )
        solve_seconds = time.perf_counter() - solve_started
        rss = _process_rss_bytes()
        if rss is not None:
            rss_samples.append(rss)
        for stage, count in dict(result["truth_output_counts"]).items():
            truth_counts[stage] += int(count)
        for stage, count in dict(result["represented_output_counts"]).items():
            represented_counts[stage] += int(count)
        split_children = _split_lineage_child_count(edits_by_sample[oracle_sample_id]["FINAL_ROAD"])
        truth_counts["SPLIT_CHILD"] += split_children
        represented_counts["SPLIT_CHILD"] += split_children if result["status"] == "OPTIMAL" else 0
        _append_jsonl(
            cost_path,
            (
                {
                    **row,
                    "family": family,
                    "business_id": business_id,
                    "oracle_sample_id": oracle_sample_id,
                    "candidate_manifest_sha256": sha256_file(candidate_manifest_path),
                }
                for row in result["costs"]
            ),
        )

        evaluation: dict[str, Any] = {}
        selected_road_path = selected_node_path = Path()
        materialize_evaluate_seconds = 0.0
        if result["status"] == "OPTIMAL" and config.emit_reconstructed_gpkg:
            materialize_started = time.perf_counter()
            case_root = target_root / "cases" / _case_key(family, business_id)
            selected_road_path = case_root / "selected_road.gpkg"
            selected_node_path = case_root / "selected_node.gpkg"
            truth_road_path = resolved_path(oracle_case["truth_road_path"])
            truth_node_path = resolved_path(oracle_case["truth_node_path"])
            _, road_meta = read_vector_payloads(truth_road_path, source_role="pto_label_schema")
            _, node_meta = read_vector_payloads(truth_node_path, source_role="pto_label_schema")
            write_vector_payloads(selected_road_path, result["roads"].values(), meta=road_meta)
            write_vector_payloads(selected_node_path, result["nodes"].values(), meta=node_meta)
            evaluation = evaluate_frcsd(selected_road_path, selected_node_path, truth_road_path, truth_node_path)
            materialize_evaluate_seconds = time.perf_counter() - materialize_started

        exact = bool(evaluation) and _evaluation_exact(evaluation)
        optimal_cases += result["status"] == "OPTIMAL" and result["optimality_gap"] == 0.0
        semantic_exact_cases += exact
        hard_failure_count += len(result["hard_failures"]) + len(list(evaluation.get("hard_failures") or []))
        selection_signature = _sha(sorted(item["candidate_id"] for item in result["selected"]))
        graph_signature = _sha(
            {
                "road": sorted(item["canonical_payload_sha256"] for item in result["selected"] if item["stage"] == "FINAL_ROAD"),
                "node": sorted(item["canonical_payload_sha256"] for item in result["selected"] if item["stage"] == "FINAL_NODE"),
            }
        )
        certificate = {
            "family": family,
            "business_id": business_id,
            "oracle_sample_id": oracle_sample_id,
            "status": result["status"],
            "objective": result["objective"],
            "lower_bound": result["lower_bound"],
            "optimality_gap": result["optimality_gap"],
            "selected_candidate_ids": sorted(item["candidate_id"] for item in result["selected"]),
            "selection_sha256": selection_signature,
            "normalized_graph_sha256": graph_signature,
            "candidate_count": result["candidate_count"],
            "variable_count": result["variable_count"],
            "constraint_count": result["constraint_count"],
            "missing_groups": result["missing_groups"],
            "unmatched_exact_groups": result["unmatched_exact_groups"],
            "extra_exactly_one_groups": result["extra_exactly_one_groups"],
            "hard_failures": result["hard_failures"],
            "relaxation": False,
            "content_repair": False,
            "silent_fix": False,
        }
        _append_jsonl(certificate_path, [certificate])
        candidate_build_seconds = float(candidate_index[scope].get("candidate_build_seconds") or 0.0)
        replay_seconds = float(candidate_index[scope].get("replay_duration_seconds") or 0.0)
        case_index.append(
            {
                "family": family,
                "business_id": business_id,
                "oracle_sample_id": oracle_sample_id,
                "status": result["status"],
                "optimality_gap": result["optimality_gap"],
                "candidate_count": result["candidate_count"],
                "variable_count": result["variable_count"],
                "constraint_count": result["constraint_count"],
                "road_f1": float(dict(evaluation.get("road_object") or {}).get("f1", 0.0)),
                "node_f1": float(dict(evaluation.get("node_object") or {}).get("f1", 0.0)),
                "directed_topology_f1": float(dict(evaluation.get("directed_topology") or {}).get("f1", 0.0)),
                "attribute_exact": exact,
                "hard_failure_count": len(result["hard_failures"]) + len(list(evaluation.get("hard_failures") or [])),
                "candidate_signature": candidate_index[scope]["candidate_signature"],
                "selection_signature": selection_signature,
                "normalized_graph_signature": graph_signature,
                "replay_seconds": replay_seconds,
                "candidate_build_seconds": candidate_build_seconds,
                "solve_seconds": solve_seconds,
                "materialize_evaluate_seconds": materialize_evaluate_seconds,
                "candidate_build_plus_solve_seconds": candidate_build_seconds + solve_seconds,
                "end_to_end_seconds": replay_seconds + candidate_build_seconds + solve_seconds + materialize_evaluate_seconds,
                "selected_road_path": str(selected_road_path.resolve()) if evaluation else "",
                "selected_node_path": str(selected_node_path.resolve()) if evaluation else "",
            }
        )
        case_metrics.append(
            {
                "family": family,
                "business_id": business_id,
                "oracle_sample_id": oracle_sample_id,
                "coverage_by_action": result["coverage_by_action"],
                "coverage_by_stage": result["coverage_by_stage"],
                "truth_action_counts": result["truth_action_counts"],
                "represented_action_counts": result["represented_action_counts"],
                "evaluation": evaluation,
            }
        )

    exact_counts = all(truth_counts[key] == expected for key, expected in _EXPECTED_COUNTS.items())
    full_coverage = all(represented_counts[key] == truth_counts[key] for key in _EXPECTED_COUNTS)
    all_action_coverage = all(
        all(float(value) == 1.0 for value in dict(case["coverage_by_action"]).values())
        for case in case_metrics
    )
    candidate_times = [float(row["candidate_build_plus_solve_seconds"]) for row in case_index]
    end_to_end_times = [float(row["end_to_end_seconds"]) for row in case_index]
    candidate_p95 = _percentile(candidate_times, 0.95)
    candidate_max = max(candidate_times, default=0.0)
    end_to_end_p95 = _percentile(end_to_end_times, 0.95)
    peak_rss = max(rss_samples, default=0)
    cpu_seconds = time.process_time() - cpu_started
    replay_cpu_time_available = False
    performance_gate = (
        end_to_end_p95 <= 60.0
        and max(end_to_end_times, default=0.0) <= 300.0
        and peak_rss <= 16 * 1024**3
        and cpu_seconds <= 2 * 3600.0
        and replay_cpu_time_available
    )
    excluded_ids = set(dict(candidate_manifest.get("parameters") or {}).get("excluded_business_ids") or [])
    excluded_occurrence_count = sum(row["business_id"] in excluded_ids for row in case_index)
    gate1 = (
        len(case_index) == config.expected_case_count
        and excluded_occurrence_count == 0
        and exact_counts
        and full_coverage
        and all_action_coverage
    )
    gate2 = optimal_cases == len(case_index) and semantic_exact_cases == len(case_index) and hard_failure_count == 0
    summary = {
        "schema_version": "p05-pto-summary-v1",
        "case_count": len(case_index),
        "family_counts": dict(sorted(Counter(row["family"] for row in case_index).items())),
        "excluded_business_ids": sorted(excluded_ids),
        "excluded_occurrence_count": excluded_occurrence_count,
        "truth_counts": dict(sorted(truth_counts.items())),
        "represented_counts": dict(sorted(represented_counts.items())),
        "expected_counts": _EXPECTED_COUNTS,
        "exact_frozen_counts": exact_counts,
        "full_candidate_coverage": full_coverage,
        "all_action_coverage": all_action_coverage,
        "optimal_case_count": optimal_cases,
        "semantic_exact_case_count": semantic_exact_cases,
        "hard_failure_count": hard_failure_count,
        "gate1_candidate_reachability_pass": gate1,
        "gate2_oracle_solve_pass": gate2,
        "candidate_build_plus_solve_p95_seconds": candidate_p95,
        "candidate_build_plus_solve_max_seconds": candidate_max,
        "end_to_end_p95_seconds": end_to_end_p95,
        "end_to_end_max_seconds": max(end_to_end_times, default=0.0),
        "peak_process_rss_bytes": peak_rss,
        "p0_process_cpu_seconds": cpu_seconds,
        "gpu_required": False,
        "performance_gate_pass": performance_gate,
        "replay_cpu_time_available": replay_cpu_time_available,
        "determinism_verified": False,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
        "unbounded_enumeration": False,
        "duration_seconds": time.perf_counter() - started,
    }
    case_index_path = target_root / "p05_pto_case_index.csv"
    metrics_path = target_root / "p05_pto_case_metrics.json"
    summary_path = target_root / "p05_pto_summary.json"
    report_path = target_root / "p05_pto_report.md"
    write_csv(case_index_path, case_index, list(case_index[0]))
    write_json(metrics_path, {"schema_version": "p05-pto-case-metrics-v1", "cases": case_metrics})
    write_json(summary_path, summary)
    report_path.write_text(_report(summary), encoding="utf-8")
    outputs = {
        "oracle_costs": output_record(cost_path),
        "solve_certificates": output_record(certificate_path),
        "case_index": output_record(case_index_path),
        "case_metrics": output_record(metrics_path),
        "summary": output_record(summary_path),
        "report": output_record(report_path),
    }
    manifest = {
        "schema_version": "p05-pto-solve-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": (
            "p0_passed"
            if gate1 and gate2 and performance_gate
            else "p0_semantic_passed_performance_failed"
            if gate1 and gate2
            else "p0_failed"
        ),
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "candidate_manifest_path": str(candidate_manifest_path),
        "candidate_manifest_sha256": sha256_file(candidate_manifest_path),
        "r2_oracle_manifest_path": str(r2_manifest_path),
        "r2_oracle_manifest_sha256": sha256_file(r2_manifest_path),
        "parameters": {
            "expected_case_count": config.expected_case_count,
            "strict_hashes": config.strict_hashes,
            "emit_reconstructed_gpkg": config.emit_reconstructed_gpkg,
        },
        "environment": _environment(),
        "performance": {
            key: summary[key]
            for key in (
                "candidate_build_plus_solve_p95_seconds",
                "candidate_build_plus_solve_max_seconds",
                "end_to_end_p95_seconds",
                "end_to_end_max_seconds",
                "peak_process_rss_bytes",
                "p0_process_cpu_seconds",
                "gpu_required",
                "replay_cpu_time_available",
            )
        },
        "outputs": outputs,
        "relaxation": False,
        "content_repair": False,
        "silent_fix": False,
        "unbounded_enumeration": False,
    }
    manifest_path = target_root / "p05_pto_solve_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["solve_pto_oracle_run"]
