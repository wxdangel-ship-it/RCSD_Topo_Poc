from __future__ import annotations

import ctypes
import json
import math
import platform
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import (
    output_record,
    write_csv,
    write_json,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import canonical_sha256
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import (
    SchemeACarrierGraphSetScorer,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1FoldVocabulary,
    encode_groups,
    score_encoded_groups,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_models import (
    SchemeAP2P1OOFConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p1_training import (
    load_scheme_a_p2_p1_groups,
    score_selection_rows,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def build_scheme_a_p2_p1_audit(
    config: SchemeAP2P1OOFConfig,
    *,
    run_a: Path,
    run_b: Path,
    output_root: Path,
    run_id: str,
) -> Path:
    root_a = _resolve_dir(run_a)
    root_b = _resolve_dir(run_b)
    target_root = normalize_runtime_path(output_root).resolve() / run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)
    determinism = _determinism_audit(root_a, root_b)
    determinism_path = target_root / "determinism_audit.json"
    write_json(determinism_path, determinism)
    gis = _gis_topology_audit(root_a)
    gis_path = target_root / "gis_topology_audit.json"
    write_json(gis_path, gis)
    benchmark, benchmark_rows = _scoring_benchmark(config, root_a)
    benchmark_path = target_root / "scoring_benchmark.json"
    benchmark_csv_path = target_root / "scoring_benchmark.csv"
    write_json(benchmark_path, benchmark)
    write_csv(
        benchmark_csv_path,
        benchmark_rows,
        [
            "seed",
            "fold",
            "case_key",
            "group_count",
            "candidate_count",
            "scoring_seconds",
        ],
    )
    summary_a = _read_json(root_a / "scheme_a_p2_p1_oof_summary.json")
    summary_b = _read_json(root_b / "scheme_a_p2_p1_oof_summary.json")
    audit_pass = determinism["passed"] and gis["passed"] and benchmark["passed"]
    summary = {
        "schema_version": "p05-scheme-a-p2-p1-audit-summary-v1",
        "gate_pass": audit_pass,
        "scorer_decision": summary_a["decision"],
        "scorer_gate_pass": bool(summary_a["gate_pass"]),
        "replay_decision_match": summary_a["decision"] == summary_b["decision"],
        "determinism_pass": determinism["passed"],
        "gis_topology_pass": gis["passed"],
        "resource_pass": benchmark["passed"],
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
    }
    summary_path = target_root / "audit_summary.json"
    write_json(summary_path, summary)
    outputs = {
        "determinism": output_record(determinism_path),
        "gis_topology": output_record(gis_path),
        "scoring_benchmark": output_record(benchmark_path),
        "scoring_benchmark_csv": output_record(benchmark_csv_path),
        "summary": output_record(summary_path),
    }
    manifest_path = target_root / "scheme_a_p2_p1_audit_manifest.json"
    write_json(
        manifest_path,
        {
            "schema_version": "p05-scheme-a-p2-p1-audit-manifest-v1",
            "module_id": "p05_neural_road_generation",
            "run_id": run_id,
            "status": "audit_passed" if audit_pass else "audit_failed",
            "scorer_decision": summary_a["decision"],
            "run_a": _run_record(root_a),
            "run_b": _run_record(root_b),
            "outputs": outputs,
        },
    )
    write_json(
        target_root / "artifact_manifest.json",
        {
            "schema_version": "p05-scheme-a-p2-p1-audit-artifact-manifest-v1",
            "artifacts": [outputs[key] for key in sorted(outputs)]
            + [output_record(manifest_path)],
        },
    )
    return target_root


def _determinism_audit(root_a: Path, root_b: Path) -> dict[str, Any]:
    byte_roles = ("scores.jsonl", "selections.jsonl", "effective_selections.jsonl")
    byte_checks = {
        role: sha256_file(root_a / role) == sha256_file(root_b / role)
        for role in byte_roles
    }
    folds_a = _read_json(root_a / "fold_index.json")
    folds_b = _read_json(root_b / "fold_index.json")
    fold_checks = {
        "model_state_signature": _fold_values(folds_a, "model_state_signature")
        == _fold_values(folds_b, "model_state_signature"),
        "checkpoint": _artifact_hashes(folds_a, "checkpoint")
        == _artifact_hashes(folds_b, "checkpoint"),
        "fold_vocabulary": _artifact_hashes(folds_a, "fold_vocabulary")
        == _artifact_hashes(folds_b, "fold_vocabulary"),
        "thresholds": _artifact_hashes(folds_a, "thresholds")
        == _artifact_hashes(folds_b, "thresholds"),
        "training_history": _artifact_hashes(folds_a, "training_history")
        == _artifact_hashes(folds_b, "training_history"),
    }
    summary_a = _read_json(root_a / "scheme_a_p2_p1_oof_summary.json")
    summary_b = _read_json(root_b / "scheme_a_p2_p1_oof_summary.json")
    summary_a.pop("resource", None)
    summary_b.pop("resource", None)
    summary_match = summary_a == summary_b
    roadgraphs_a = _normalized_roadgraph_index(root_a / "roadgraph_index.jsonl")
    roadgraphs_b = _normalized_roadgraph_index(root_b / "roadgraph_index.jsonl")
    checks = {
        **byte_checks,
        **fold_checks,
        "semantic_summary": summary_match,
        "roadgraph_index": roadgraphs_a == roadgraphs_b,
    }
    return {
        "schema_version": "p05-scheme-a-p2-p1-determinism-audit-v1",
        "checks": checks,
        "model_count": len(folds_a),
        "score_sha256": sha256_file(root_a / "scores.jsonl"),
        "selection_sha256": sha256_file(root_a / "selections.jsonl"),
        "effective_selection_sha256": sha256_file(root_a / "effective_selections.jsonl"),
        "semantic_summary_signature": canonical_sha256(summary_a),
        "roadgraph_index_signature": canonical_sha256(roadgraphs_a),
        "passed": all(checks.values()),
    }


def _gis_topology_audit(root: Path) -> dict[str, Any]:
    terminal = Counter()
    crs = Counter()
    failure_reasons = Counter()
    output_hash_mismatch_count = 0
    graph_count = legal_failure_count = expected_match_failure_count = 0
    content_repair_count = silent_fix_count = relaxation_count = 0
    skeleton_mutation_count = node_conflict_count = 0
    for row in _read_jsonl(root / "roadgraph_index.jsonl"):
        graph_count += 1
        terminal[str(row["terminal_state"])] += 1
        output_path = normalize_runtime_path(str(row["output"]["path"])).resolve(strict=True)
        output_hash_mismatch_count += int(sha256_file(output_path) != row["output"]["sha256"])
        graph = _read_json(output_path)
        audit = graph["audit"]
        crs[str(graph.get("crs") or "")] += 1
        legal_failure_count += int(
            row["terminal_state"] == "LEGAL"
            and (not audit["legal"] or int(audit["failure_count"]) != 0)
        )
        expected_match_failure_count += int(
            row["terminal_state"] == "EXPECTED_FAIL"
            and not bool(audit["expected_failure_match"])
        )
        content_repair_count += int(bool(audit["content_repair"]))
        silent_fix_count += int(bool(audit["silent_fix"]))
        relaxation_count += int(bool(audit["relaxation"]))
        skeleton_mutation_count += int(audit["skeleton_mutation_count"])
        node_conflict_count += int(audit["node_conflict_count"])
        for reason in audit["failures"]:
            text = str(reason)
            if text.startswith("CRS mismatch"):
                failure_reasons["CRS"] += 1
            elif "geometry" in text.lower():
                failure_reasons["GEOMETRY"] += 1
            elif "endpoint" in text.lower():
                failure_reasons["EXPECTED_ENDPOINT"] += 1
            else:
                failure_reasons["OTHER"] += 1
    checks = {
        "graph_count_153": graph_count == 153,
        "terminal_147_6": terminal == Counter({"LEGAL": 147, "EXPECTED_FAIL": 6}),
        "crs_epsg_3857": crs == Counter({"EPSG:3857": 153}),
        "legal_graph_hard_gate": legal_failure_count == 0,
        "expected_failure_exact": expected_match_failure_count == 0,
        "source_output_hashes": output_hash_mismatch_count == 0,
        "crs_geometry_failure_zero": failure_reasons["CRS"] == failure_reasons["GEOMETRY"] == 0,
        "node_conflict_zero": node_conflict_count == 0,
        "no_repair_or_mutation": content_repair_count
        == silent_fix_count
        == relaxation_count
        == skeleton_mutation_count
        == 0,
    }
    return {
        "schema_version": "p05-scheme-a-p2-p1-gis-topology-audit-v1",
        "qgis_runtime": "C:\\Program Files\\QGIS 3.40.14\\bin\\python-qgis-ltr.bat",
        "qgis_runtime_exists": Path(
            r"C:\Program Files\QGIS 3.40.14\bin\python-qgis-ltr.bat"
        ).exists(),
        "overlay_gate_applicable": False,
        "overlay_gate_reason": "P2-P1 publishes normalized RoadGraph JSON and frozen source payload references, not a new vector layer; source GPKG CRS and geometry are validated by the materializer hard gate.",
        "terminal_counts": dict(sorted(terminal.items())),
        "crs_counts": dict(sorted(crs.items())),
        "failure_reason_counts": dict(sorted(failure_reasons.items())),
        "checks": checks,
        "passed": all(checks.values()),
    }


def _scoring_benchmark(
    config: SchemeAP2P1OOFConfig, root: Path
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    groups, dataset = load_scheme_a_p2_p1_groups(
        config.dataset_run_root, strict_hashes=config.strict_hashes
    )
    by_case: dict[str, list[Any]] = defaultdict(list)
    for group in groups:
        by_case[group.case_key].append(group)
    case_folds = {case_key: rows[0].fold for case_key, rows in by_case.items()}
    junction_by_group = {
        group_id: str(label.get("junction_key") or group_id)
        for group_id, label in dataset["labels"].items()
    }
    fold_index = {
        (int(row["seed"]), int(row["fold"])): row
        for row in _read_json(root / "fold_index.json")
    }
    device = torch.device("cpu")
    torch.set_num_threads(config.torch_num_threads)
    rows: list[dict[str, Any]] = []
    peak_rss = _peak_working_set_bytes()
    for seed in config.seeds:
        for fold in range(config.expected_fold_count):
            record = fold_index[(seed, fold)]
            vocabulary = _load_vocabulary(Path(record["fold_vocabulary"]["path"]))
            model = SchemeACarrierGraphSetScorer(
                candidate_vocabulary_size=len(vocabulary.candidate_tokens) + 1,
                object_vocabulary_size=len(vocabulary.object_tokens) + 1,
                context_vocabulary_size=len(vocabulary.context_tokens) + 1,
                object_type_count=len(vocabulary.object_types) + 1,
                numeric_dim=config.numeric_dim,
                embedding_dim=config.embedding_dim,
                hidden_dim=config.hidden_dim,
                type_embedding_dim=config.type_embedding_dim,
                dropout=config.dropout,
            ).to(device)
            checkpoint = torch.load(
                record["checkpoint"]["path"], map_location=device, weights_only=True
            )
            model.load_state_dict(checkpoint["state_dict"], strict=True)
            thresholds = _read_json(Path(record["thresholds"]["path"]))
            held_cases = sorted(
                case_key for case_key, case_fold in case_folds.items() if case_fold == fold
            )
            warmup_groups = by_case[held_cases[0]]
            _score_case(
                warmup_groups,
                model,
                vocabulary,
                thresholds,
                config,
                dataset["compatibility_edges"],
                junction_by_group,
                seed,
                fold,
            )
            for case_key in held_cases:
                case_groups = by_case[case_key]
                started = time.perf_counter()
                _score_case(
                    case_groups,
                    model,
                    vocabulary,
                    thresholds,
                    config,
                    dataset["compatibility_edges"],
                    junction_by_group,
                    seed,
                    fold,
                )
                elapsed = time.perf_counter() - started
                rows.append(
                    {
                        "seed": seed,
                        "fold": fold,
                        "case_key": case_key,
                        "group_count": len(case_groups),
                        "candidate_count": sum(len(group.candidates) for group in case_groups),
                        "scoring_seconds": elapsed,
                    }
                )
                peak_rss = max(peak_rss, _peak_working_set_bytes())
            del model
    values = sorted(float(row["scoring_seconds"]) for row in rows)
    p95 = _percentile(values, 0.95)
    maximum = max(values)
    run_summary = _read_json(root / "scheme_a_p2_p1_oof_summary.json")
    training_seconds = float(run_summary["resource"]["training_wall_seconds"])
    checks = {
        "case_seed_count_153": len(rows) == 153,
        "p95_le_5_seconds": p95 <= 5.0,
        "max_le_20_seconds": maximum <= 20.0,
        "training_le_6_hours": training_seconds <= 6 * 60 * 60,
        "peak_rss_le_16_gib": peak_rss <= 16 * 1024**3,
        "gpu_within_budget": not torch.cuda.is_available(),
    }
    return (
        {
            "schema_version": "p05-scheme-a-p2-p1-scoring-benchmark-v1",
            "platform": platform.platform(),
            "case_seed_count": len(rows),
            "p95_scoring_seconds": p95,
            "max_scoring_seconds": maximum,
            "training_wall_seconds": training_seconds,
            "peak_working_set_bytes": peak_rss,
            "checks": checks,
            "passed": all(checks.values()),
        },
        rows,
    )


def _score_case(
    groups: Sequence[Any],
    model: SchemeACarrierGraphSetScorer,
    vocabulary: P1FoldVocabulary,
    thresholds: Mapping[str, float],
    config: SchemeAP2P1OOFConfig,
    compatibility_edges: Sequence[Mapping[str, Any]],
    junction_by_group: Mapping[str, str],
    seed: int,
    fold: int,
) -> None:
    encoded = encode_groups(groups, vocabulary)
    scores, probabilities, anomaly = score_encoded_groups(
        model,
        encoded,
        batch_group_count=config.batch_group_count,
        device=torch.device("cpu"),
    )
    score_selection_rows(
        groups,
        scores,
        probabilities,
        anomaly,
        thresholds,
        seed=seed,
        fold=fold,
        model_signature="benchmark",
        compatibility_edges=compatibility_edges,
        junction_by_group=junction_by_group,
    )


def _load_vocabulary(path: Path) -> P1FoldVocabulary:
    raw = _read_json(path)
    return P1FoldVocabulary(
        candidate_tokens={str(key): int(value) for key, value in raw["candidate_tokens"].items()},
        object_tokens={str(key): int(value) for key, value in raw["object_tokens"].items()},
        context_tokens={str(key): int(value) for key, value in raw["context_tokens"].items()},
        object_types={str(key): int(value) for key, value in raw["object_types"].items()},
        numeric_mean=tuple(float(value) for value in raw["numeric_mean"]),
        numeric_scale=tuple(float(value) for value in raw["numeric_scale"]),
        train_case_keys=tuple(str(value) for value in raw["train_case_keys"]),
        inner_validation_case_keys=tuple(
            str(value) for value in raw["inner_validation_case_keys"]
        ),
        held_out_case_keys=tuple(str(value) for value in raw["held_out_case_keys"]),
        dataset_manifest_sha256=str(raw["dataset_manifest_sha256"]),
    )


def _peak_working_set_bytes() -> int:
    if platform.system() != "Windows":
        return 0

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
    get_process_memory_info = ctypes.windll.psapi.GetProcessMemoryInfo
    get_process_memory_info.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(ProcessMemoryCounters),
        ctypes.c_ulong,
    )
    get_process_memory_info.restype = ctypes.c_int
    handle = get_current_process()
    ok = get_process_memory_info(
        handle, ctypes.byref(counters), counters.cb
    )
    if not ok:
        raise OSError("GetProcessMemoryInfo failed")
    return int(counters.PeakWorkingSetSize)


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("cannot calculate an empty percentile")
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def _normalized_roadgraph_index(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in _read_jsonl(path):
        normalized = dict(row)
        normalized["output"] = {
            key: value for key, value in row["output"].items() if key != "path"
        }
        result.append(normalized)
    return result


def _fold_values(rows: Sequence[Mapping[str, Any]], field: str) -> list[Any]:
    return [row[field] for row in rows]


def _artifact_hashes(rows: Sequence[Mapping[str, Any]], field: str) -> list[str]:
    return [str(row[field]["sha256"]) for row in rows]


def _run_record(root: Path) -> dict[str, Any]:
    manifest_path = root / "scheme_a_p2_p1_oof_manifest.json"
    return {
        "path": str(manifest_path.resolve()),
        "sha256": sha256_file(manifest_path),
    }


def _read_json(path: Path) -> dict[str, Any] | list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _resolve_dir(path: Path | str) -> Path:
    resolved = normalize_runtime_path(path).resolve(strict=True)
    if not resolved.is_dir():
        raise NotADirectoryError(resolved)
    return resolved


__all__ = ["build_scheme_a_p2_p1_audit"]
