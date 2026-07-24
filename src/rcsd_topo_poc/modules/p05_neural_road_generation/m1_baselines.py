from __future__ import annotations

import csv
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_dataset import OPERATION_NAMES, OPERATION_TO_INDEX
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def operation_metrics(truth: np.ndarray, prediction: np.ndarray, weights: np.ndarray | None = None) -> dict[str, Any]:
    truth = np.asarray(truth, dtype=np.int64)
    prediction = np.asarray(prediction, dtype=np.int64)
    if truth.shape != prediction.shape:
        raise ValueError("truth and prediction shapes differ")
    sample_weights = np.ones(len(truth), dtype=np.float64) if weights is None else np.asarray(weights, dtype=np.float64)
    if sample_weights.shape != truth.shape:
        raise ValueError("weights shape differs from truth")
    confusion = np.zeros((len(OPERATION_NAMES), len(OPERATION_NAMES)), dtype=np.int64)
    for expected, actual in zip(truth, prediction):
        confusion[int(expected), int(actual)] += 1
    per_class: dict[str, dict[str, float | int]] = {}
    f1_values: list[float] = []
    for index, name in enumerate(OPERATION_NAMES):
        true_positive = int(confusion[index, index])
        predicted = int(confusion[:, index].sum())
        expected = int(confusion[index, :].sum())
        precision = true_positive / predicted if predicted else 0.0
        recall = true_positive / expected if expected else 0.0
        f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_class[name] = {"support": expected, "precision": precision, "recall": recall, "f1": f1}
        if expected:
            f1_values.append(f1)
    correct = truth == prediction
    weighted_denominator = float(sample_weights.sum())
    return {
        "count": int(len(truth)),
        "accuracy": float(correct.mean()) if len(truth) else 0.0,
        "weighted_accuracy": float(sample_weights[correct].sum() / weighted_denominator) if weighted_denominator else 0.0,
        "macro_f1": float(np.mean(f1_values)) if f1_values else 0.0,
        "confusion": confusion.tolist(),
        "per_class": per_class,
    }


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _verify_dataset(dataset_root: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    manifest_path = dataset_root / "p05_m1_dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "p05-m1-dataset-manifest-v1":
        raise ValueError("unsupported M1 dataset manifest")
    if manifest.get("silent_fix") is not False:
        raise ValueError("M1 dataset must declare silent_fix=false")
    resolved: dict[str, Path] = {}
    for role in ("candidates", "labels", "summary", "graph_index", "normalization"):
        record = manifest["outputs"][role]
        path = normalize_runtime_path(record["path"])
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise ValueError(f"M1 dataset output missing or hash mismatch: {role}")
        resolved[role] = path
    return manifest, resolved


def _rows(dataset_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest, paths = _verify_dataset(dataset_root)
    candidates = {
        (row["sample_id"], row["road_id"]): row
        for row in _read_csv(paths["candidates"])
        if row["guarded_out"].casefold() == "false"
    }
    rows: list[dict[str, Any]] = []
    for label in _read_csv(paths["labels"]):
        if label["guarded_out"].casefold() != "false":
            continue
        key = (label["sample_id"], label["road_id"])
        candidate = candidates[key]
        rows.append(
            {
                **label,
                "source_role": candidate["source_role"],
                "truth_operation": OPERATION_TO_INDEX[label["operation"]],
                "weight": float(label["label_weight"]),
                "truth_output_count": len(json.loads(label["output_road_ids"])),
            }
        )
    return manifest, rows


def _road_identity_metrics(rows: list[dict[str, Any]], predictions: np.ndarray) -> dict[str, float | int]:
    truth_count = sum(int(row["truth_output_count"]) for row in rows)
    predicted_count = 0
    matched = 0
    for row, prediction in zip(rows, predictions):
        operation = OPERATION_NAMES[int(prediction)]
        predicted_count += 0 if operation == "DROP" else 1 if operation == "KEEP" else int(operation.rsplit("_", 1)[1])
        if operation == "KEEP" and row["operation"] == "KEEP":
            matched += 1
    precision = matched / predicted_count if predicted_count else 0.0
    recall = matched / truth_count if truth_count else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "matched_input_identity_roads": matched,
        "predicted_road_count": predicted_count,
        "truth_road_count": truth_count,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "note": "Only exact KEEP identity matches count; predicted SPLIT geometry is not credited by this proxy.",
    }


def _evaluate_rows(rows: list[dict[str, Any]], predictor: Callable[[dict[str, Any]], int]) -> dict[str, Any]:
    truth = np.asarray([row["truth_operation"] for row in rows], dtype=np.int64)
    predictions = np.asarray([predictor(row) for row in rows], dtype=np.int64)
    weights = np.asarray([row["weight"] for row in rows], dtype=np.float64)
    by_case: dict[str, Any] = {}
    indices_by_case: dict[str, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        indices_by_case[row["sample_id"]].append(index)
    for sample_id, indices in sorted(indices_by_case.items()):
        index_array = np.asarray(indices, dtype=np.int64)
        case_rows = [rows[index] for index in indices]
        by_case[sample_id] = {
            "split": case_rows[0]["split"],
            "operation": operation_metrics(truth[index_array], predictions[index_array], weights[index_array]),
            "road_identity": _road_identity_metrics(case_rows, predictions[index_array]),
        }
    return {
        "operation": operation_metrics(truth, predictions, weights),
        "road_identity": _road_identity_metrics(rows, predictions),
        "by_case": by_case,
    }


def run_m1_baselines(
    dataset_run_root: Path,
    output_root: Path,
    run_id: str,
    *,
    include_test: bool = False,
) -> dict[str, Any]:
    if not run_id.strip():
        raise ValueError("run_id must not be empty")
    started = time.perf_counter()
    dataset_root = normalize_runtime_path(dataset_run_root).resolve(strict=True)
    manifest, rows = _rows(dataset_root)
    source_counts: dict[str, Counter[int]] = defaultdict(Counter)
    for row in rows:
        if row["split"] == "train":
            source_counts[row["source_role"]][row["truth_operation"]] += float(row["weight"])
    source_majority = {
        role: max(counts, key=lambda operation: (counts[operation], -operation))
        for role, counts in source_counts.items()
    }
    predictors: dict[str, Callable[[dict[str, Any]], int]] = {
        "keep_all": lambda row: OPERATION_TO_INDEX["KEEP"],
        "swsd_only": lambda row: OPERATION_TO_INDEX["KEEP"] if row["source_role"] == "t01_roads" else OPERATION_TO_INDEX["DROP"],
        "source_majority": lambda row: source_majority[row["source_role"]],
    }
    allowed_splits = {"train", "validation", "test"} if include_test else {"train", "validation"}
    evaluated_rows = [row for row in rows if row["split"] in allowed_splits]
    results = {name: _evaluate_rows(evaluated_rows, predictor) for name, predictor in predictors.items()}
    validation_scores = {
        name: _evaluate_rows([row for row in rows if row["split"] == "validation"], predictor)["road_identity"]["f1"]
        for name, predictor in predictors.items()
    }
    strongest = max(validation_scores, key=lambda name: (validation_scores[name], name))
    summary = {
        "schema_version": "p05-m1-baseline-summary-v1",
        "dataset_run_id": manifest["run_id"],
        "include_test": include_test,
        "source_majority_operations": {role: OPERATION_NAMES[index] for role, index in source_majority.items()},
        "strongest_validation_baseline": strongest,
        "validation_road_identity_f1": validation_scores,
        "results": results,
        "duration_seconds": time.perf_counter() - started,
    }
    target_root = normalize_runtime_path(output_root).resolve(strict=False) / run_id
    target_root.mkdir(parents=True, exist_ok=False)
    summary_path = target_root / "p05_m1_baselines.json"
    write_json(summary_path, summary)
    output_manifest = {
        "schema_version": "p05-m1-baseline-manifest-v1",
        "run_id": run_id,
        "dataset_manifest_path": str((dataset_root / "p05_m1_dataset_manifest.json").resolve()),
        "dataset_manifest_sha256": sha256_file(dataset_root / "p05_m1_dataset_manifest.json"),
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "include_test": include_test,
        "silent_fix": False,
        "outputs": {"baselines": output_record(summary_path)},
    }
    manifest_path = target_root / "p05_m1_baseline_manifest.json"
    write_json(manifest_path, output_manifest)
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["operation_metrics", "run_m1_baselines"]
