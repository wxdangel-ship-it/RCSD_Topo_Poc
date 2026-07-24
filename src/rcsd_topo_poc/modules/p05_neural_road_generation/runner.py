from __future__ import annotations

import importlib.metadata
import ctypes
import json
import os
import platform
import sys
import time
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fiona

from rcsd_topo_poc.modules.p05_neural_road_generation.evaluation import evaluate_frcsd
from rcsd_topo_poc.modules.p05_neural_road_generation.inventory import scan_training_samples
from rcsd_topo_poc.modules.p05_neural_road_generation.labels import discover_label_artifacts
from rcsd_topo_poc.modules.p05_neural_road_generation.models import DataAnomaly, LabelArtifact, M0Config
from rcsd_topo_poc.modules.p05_neural_road_generation.outputs import write_m0_outputs
from rcsd_topo_poc.modules.p05_neural_road_generation.splits import build_grouped_split
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def _write_fixture_graph(
    root: Path,
    name: str,
    *,
    roads: list[dict[str, Any]],
    nodes: list[dict[str, Any]],
) -> tuple[Path, Path]:
    road_path = root / f"{name}_road.gpkg"
    node_path = root / f"{name}_node.gpkg"
    road_schema = {
        "geometry": "LineString",
        "properties": {"id": "str", "snodeid": "str", "enodeid": "str", "direction": "int", "source": "int"},
    }
    node_schema = {"geometry": "Point", "properties": {"id": "str", "source": "int"}}
    with fiona.open(road_path, "w", driver="GPKG", layer="road", crs="EPSG:3857", schema=road_schema) as sink:
        for feature in roads:
            sink.write(feature)
    with fiona.open(node_path, "w", driver="GPKG", layer="node", crs="EPSG:3857", schema=node_schema) as sink:
        for feature in nodes:
            sink.write(feature)
    return road_path, node_path


def _synthetic_corruption_suite(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=False)
    truth_nodes = [
        {"geometry": {"type": "Point", "coordinates": (0.0, 0.0)}, "properties": {"id": "n1", "source": 1}},
        {"geometry": {"type": "Point", "coordinates": (10.0, 0.0)}, "properties": {"id": "n2", "source": 1}},
    ]
    truth_roads = [
        {
            "geometry": {"type": "LineString", "coordinates": ((0.0, 0.0), (10.0, 0.0))},
            "properties": {"id": "r1", "snodeid": "n1", "enodeid": "n2", "direction": 2, "source": 1},
        }
    ]
    truth_road, truth_node = _write_fixture_graph(root, "truth", roads=truth_roads, nodes=truth_nodes)
    scenarios: dict[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]] = {
        "road_deleted": ([], truth_nodes),
        "direction_reversed": ([{**truth_roads[0], "properties": {**truth_roads[0]["properties"], "direction": 3}}], truth_nodes),
        "source_changed": ([{**truth_roads[0], "properties": {**truth_roads[0]["properties"], "source": 2}}], truth_nodes),
        "endpoint_moved": (
            truth_roads,
            [truth_nodes[0], {**truth_nodes[1], "geometry": {"type": "Point", "coordinates": (15.0, 0.0)}}],
        ),
        "topology_broken": (
            [{**truth_roads[0], "properties": {**truth_roads[0]["properties"], "enodeid": "missing"}}],
            truth_nodes,
        ),
    }
    results: dict[str, Any] = {}
    for scenario, (roads, nodes) in scenarios.items():
        candidate_road, candidate_node = _write_fixture_graph(root, scenario, roads=roads, nodes=nodes)
        evaluation = evaluate_frcsd(candidate_road, candidate_node, truth_road, truth_node)
        results[scenario] = {
            "detected": not evaluation["overall_passed"],
            "road_f1": evaluation["road_object"]["f1"],
            "direction_accuracy": evaluation["attributes"]["direction_accuracy"],
            "source_accuracy": evaluation["attributes"]["source_accuracy"],
            "node_distance_max_m": evaluation["geometry_m"]["node_distance"]["max"],
            "directed_topology_f1": evaluation["directed_topology"]["f1"],
            "hard_failures": evaluation["hard_failures"],
        }
    return {"all_detected": all(item["detected"] for item in results.values()), "scenarios": results}


def _oracle_evaluation(
    artifacts: list[LabelArtifact],
    fixture_root: Path,
    *,
    approved_exclusion_keys: frozenset[tuple[str, str]] = frozenset(),
) -> dict[str, Any]:
    by_sample: dict[str, dict[str, LabelArtifact]] = defaultdict(dict)
    for artifact in artifacts:
        by_sample[artifact.sample_id][artifact.role] = artifact
    case_results: list[dict[str, Any]] = []
    for sample_id, roles in sorted(by_sample.items()):
        road = roles.get("t06_frcsd_road")
        node = roles.get("t06_frcsd_node")
        if road is None or node is None:
            continue
        try:
            result = evaluate_frcsd(
                Path(road.artifact_path),
                Path(node.artifact_path),
                Path(road.artifact_path),
                Path(node.artifact_path),
            )
            approved = (road.family, road.business_id) in approved_exclusion_keys
            integrity_passed = bool(result["overall_passed"])
            case_results.append(
                {
                    "sample_id": sample_id,
                    "family": road.family,
                    "business_id": road.business_id,
                    "passed": integrity_passed,
                    "eligible": integrity_passed and not approved,
                    "status": (
                        "approved_exclusion"
                        if approved
                        else "passed"
                        if integrity_passed
                        else "quarantined_truth_integrity_failure"
                    ),
                    "road_count": result["counts"]["truth_roads"],
                    "node_count": result["counts"]["truth_nodes"],
                    "duration_seconds": result["duration_seconds"],
                    "hard_failures": result["hard_failures"],
                }
            )
        except Exception as exc:  # Preserve the Case as auditable failed evidence.
            approved = (road.family, road.business_id) in approved_exclusion_keys
            case_results.append(
                {
                    "sample_id": sample_id,
                    "family": road.family,
                    "business_id": road.business_id,
                    "passed": False,
                    "eligible": False,
                    "status": "approved_exclusion" if approved else "quarantined_evaluation_error",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
    corruption_suite = _synthetic_corruption_suite(fixture_root)
    eligible_results = [item for item in case_results if item.get("eligible")]
    passed_count = sum(bool(item.get("passed")) for item in eligible_results)
    approved = [item for item in case_results if item.get("status") == "approved_exclusion"]
    quarantined = [
        item
        for item in case_results
        if not item.get("eligible") and item.get("status") != "approved_exclusion"
    ]
    return {
        "schema_version": "p05-m0-oracle-v1",
        "evaluated_case_count": len(case_results),
        "case_count": len(eligible_results),
        "quarantined_count": len(quarantined),
        "quarantined_sample_ids": sorted(str(item["sample_id"]) for item in quarantined),
        "approved_exclusion_count": len(approved),
        "approved_exclusion_sample_ids": sorted(str(item["sample_id"]) for item in approved),
        "passed_count": passed_count,
        "all_passed": passed_count == len(eligible_results) and bool(eligible_results),
        "case_results": case_results,
        "corruption_suite": corruption_suite,
    }


def _environment() -> dict[str, Any]:
    versions: dict[str, str] = {}
    for package in ("fiona", "shapely", "pyproj"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpu_count": os.cpu_count(),
        "libraries": versions,
    }


def _peak_rss_bytes() -> int | None:
    if os.name == "nt":
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

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ProcessMemoryCounters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        process = kernel32.GetCurrentProcess()
        ok = psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb)
        return int(counters.PeakWorkingSetSize) if ok else None
    try:
        import resource

        peak = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        return peak if sys.platform == "darwin" else peak * 1024
    except (ImportError, OSError, ValueError):
        return None


def build_m0_benchmark(config: M0Config) -> Path:
    started_at = datetime.now(timezone.utc)
    started = time.perf_counter()
    run_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    if run_root.exists():
        raise FileExistsError(f"M0 run root is immutable and already exists: {run_root}")
    run_root.mkdir(parents=True, exist_ok=False)
    try:
        samples, inventory_anomalies = scan_training_samples(config)
        samples, artifacts, label_anomalies = discover_label_artifacts(config, samples)
        assignments = build_grouped_split(samples, config.split_seed)
        approved_by_key = {exclusion.key: exclusion for exclusion in config.approved_exclusions}
        inventory_keys = {(sample.family, sample.business_id) for sample in samples}
        missing_approved_keys = sorted(set(approved_by_key) - inventory_keys)
        oracle = _oracle_evaluation(
            artifacts,
            run_root / "oracle_fixture",
            approved_exclusion_keys=frozenset(approved_by_key),
        )
        anomalies: list[DataAnomaly] = [*inventory_anomalies, *label_anomalies]
        quarantined_ids = set(oracle.get("quarantined_sample_ids", []))
        approved_ids = set(oracle.get("approved_exclusion_sample_ids", []))
        masked_ids = quarantined_ids | approved_ids
        if masked_ids:
            samples = [
                replace(
                    sample,
                    task_mask=(
                        {task: False for task in sample.task_mask}
                        if sample.sample_id in approved_ids
                        else {**sample.task_mask, "road_graph": False}
                    ),
                    task_mask_reasons=(
                        {task: "whole sample excluded from training by approved user decision" for task in sample.task_mask}
                        if sample.sample_id in approved_ids
                        else {
                            **sample.task_mask_reasons,
                            "road_graph": "canonical T06 truth failed Road/Node integrity and is quarantined pending manual re-evaluation",
                        }
                    ),
                )
                if sample.sample_id in masked_ids
                else sample
                for sample in samples
            ]
            for result in oracle["case_results"]:
                sample_id = result.get("sample_id")
                if sample_id not in masked_ids:
                    continue
                detail = result.get("error") or "; ".join(result.get("hard_failures", []))
                family = str(result.get("family") or "")
                business_id = str(result.get("business_id") or "")
                if sample_id in approved_ids:
                    exclusion = approved_by_key[(family, business_id)]
                    anomalies.append(
                        DataAnomaly(
                            "info",
                            "approved_sample_exclusion",
                            f"{exclusion.decision_source}: {exclusion.reason}; integrity evidence: {detail}",
                            family,
                            business_id,
                            str(sample_id or ""),
                        )
                    )
                else:
                    anomalies.append(
                        DataAnomaly(
                            "error",
                            "canonical_truth_integrity_failure",
                            str(detail),
                            family,
                            business_id,
                            str(sample_id or ""),
                        )
                    )
        for family, business_id in missing_approved_keys:
            exclusion = approved_by_key[(family, business_id)]
            anomalies.append(
                DataAnomaly(
                    "error",
                    "approved_exclusion_sample_missing",
                    f"{exclusion.decision_source}: {exclusion.reason}",
                    family,
                    business_id,
                )
            )
        if not oracle["all_passed"]:
            anomalies.append(DataAnomaly("error", "oracle_not_all_passed", "one or more eligible truth-vs-truth evaluations failed", path=str(run_root)))
        if not oracle["corruption_suite"]["all_detected"]:
            anomalies.append(DataAnomaly("error", "corruption_not_detected", "one or more synthetic corruptions were not detected", path=str(run_root)))
        anomalies.sort(key=lambda item: (item.severity, item.category, item.family, item.business_id, item.path))
        duration = time.perf_counter() - started
        manifest = {
            "schema_version": "p05-m0-manifest-v1",
            "module_id": "p05_neural_road_generation",
            "run_id": config.run_id,
            "started_at_utc": started_at.isoformat(),
            "completed_at_utc": datetime.now(timezone.utc).isoformat(),
            "poc_data_root": str(normalize_runtime_path(config.poc_data_root).resolve(strict=False)),
            "baseline_roots_in_priority_order": [
                str(normalize_runtime_path(path).resolve(strict=False)) for path in config.baseline_roots
            ],
            "split_seed": config.split_seed,
            "fold_policy": {"fold_count": 5, "test": [0], "validation": [1], "train": [2, 3, 4]},
            "label_weights": {"t03_t04_target": 1.0, "t10_checked": 0.7, "rule_context": 0.3},
            "approved_exclusions": [exclusion.to_dict() for exclusion in config.approved_exclusions],
            "silent_fix": False,
            "environment": _environment(),
            "performance": {"duration_seconds": duration, "peak_rss_bytes": _peak_rss_bytes()},
        }
        write_m0_outputs(
            run_root,
            samples=samples,
            artifacts=artifacts,
            assignments=assignments,
            anomalies=anomalies,
            oracle=oracle,
            manifest=manifest,
            duration_seconds=duration,
        )
    except Exception:
        failure_path = run_root / "p05_m0_failed.json"
        failure_path.write_text(
            json.dumps(
                {
                    "schema_version": "p05-m0-failure-v1",
                    "run_id": config.run_id,
                    "failed_at_utc": datetime.now(timezone.utc).isoformat(),
                    "note": "The immutable failed run is retained for audit; use a new run_id after correcting the cause.",
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        raise
    return run_root


__all__ = ["build_m0_benchmark"]
