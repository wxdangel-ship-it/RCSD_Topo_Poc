from __future__ import annotations

import csv
import ctypes
import json
import os
import random
import time
from collections import Counter, defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_baselines import operation_metrics
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_models import M1TrainingConfig
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _verify_dataset(root: Path) -> tuple[dict[str, Any], dict[str, Path], list[dict[str, Any]]]:
    manifest_path = root / "p05_m1_dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "p05-m1-dataset-manifest-v1":
        raise ValueError("unsupported M1 dataset manifest")
    if manifest.get("silent_fix") is not False:
        raise ValueError("dataset must declare silent_fix=false")
    paths: dict[str, Path] = {}
    for role in ("graph_index", "candidates", "normalization"):
        record = manifest["outputs"][role]
        path = normalize_runtime_path(record["path"])
        if not path.is_file() or sha256_file(path) != record["sha256"]:
            raise ValueError(f"dataset output missing or hash mismatch: {role}")
        paths[role] = path
    graph_index = json.loads(paths["graph_index"].read_text(encoding="utf-8"))["graphs"]
    for item in graph_index:
        graph_path = normalize_runtime_path(item["graph_path"])
        if not graph_path.is_file() or sha256_file(graph_path) != item["graph_sha256"]:
            raise ValueError(f"graph missing or hash mismatch: {item['sample_id']}")
        item["graph_path"] = str(graph_path)
    return manifest, paths, graph_index


def _candidate_ids(path: Path) -> dict[str, list[str]]:
    result: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for row in _read_csv(path):
        result[row["sample_id"]].append((int(row["row_index_raw"]), row["road_id"]))
    return {sample_id: [road_id for _, road_id in sorted(items)] for sample_id, items in result.items()}


def _expand_mask(mask: np.ndarray, edge_index: np.ndarray, hops: int = 1) -> np.ndarray:
    removed = set(np.flatnonzero(~mask).tolist())
    adjacency: dict[int, set[int]] = defaultdict(set)
    for left, right in edge_index.T:
        adjacency[int(left)].add(int(right))
    frontier = deque((index, 0) for index in sorted(removed))
    while frontier:
        index, depth = frontier.popleft()
        if depth >= hops:
            continue
        for neighbor in adjacency.get(index, set()):
            if neighbor not in removed:
                removed.add(neighbor)
                frontier.append((neighbor, depth + 1))
    result = np.ones_like(mask, dtype=np.bool_)
    if removed:
        result[np.asarray(sorted(removed), dtype=np.int64)] = False
    return result


def _holdout_masks(
    graph_index: list[dict[str, Any]],
    ids_by_sample: dict[str, list[str]],
    holdout_sample_ids: set[str],
) -> dict[str, np.ndarray]:
    test_ids = {
        road_id
        for item in graph_index
        if int(item["fold"]) == 0
        for road_id in ids_by_sample[item["sample_id"]]
    }
    validation_ids = {
        road_id
        for item in graph_index
        if item["sample_id"] in holdout_sample_ids
        for road_id in ids_by_sample[item["sample_id"]]
    }
    result: dict[str, np.ndarray] = {}
    for item in graph_index:
        fold = int(item["fold"])
        graph_ids = ids_by_sample[item["sample_id"]]
        if fold == 0:
            result[item["sample_id"]] = np.zeros(len(graph_ids), dtype=np.bool_)
            continue
        forbidden = test_ids if item["sample_id"] in holdout_sample_ids else test_ids | validation_ids
        base = np.asarray([road_id not in forbidden for road_id in graph_ids], dtype=np.bool_)
        with np.load(item["graph_path"], allow_pickle=False) as data:
            result[item["sample_id"]] = _expand_mask(base, data["raw_edge_index"], hops=1)
    return result


def _cv_masks(
    graph_index: list[dict[str, Any]],
    ids_by_sample: dict[str, list[str]],
    validation_fold: int,
) -> dict[str, np.ndarray]:
    holdout = {item["sample_id"] for item in graph_index if int(item["fold"]) == validation_fold}
    return _holdout_masks(graph_index, ids_by_sample, holdout)


def _view(
    graph_index: list[dict[str, Any]],
    candidate_path: Path,
    validation_fold: int | None,
    holdout_sample_ids: tuple[str, ...],
    train_all_development: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, np.ndarray] | None, dict[str, Any]]:
    if train_all_development:
        ids_by_sample = _candidate_ids(candidate_path)
        masks = _holdout_masks(graph_index, ids_by_sample, set())
        train = [item for item in graph_index if int(item["fold"]) in {1, 2, 3, 4}]
        return train, [], masks, {
            "kind": "final_development_train",
            "development_folds": [1, 2, 3, 4],
            "fixed_test_guard_hops": 1,
            "test_accessed": False,
        }
    if holdout_sample_ids:
        holdout = set(holdout_sample_ids)
        known = {item["sample_id"] for item in graph_index}
        if not holdout.issubset(known):
            raise ValueError(f"unknown holdout sample ids: {sorted(holdout - known)}")
        if any(int(item["fold"]) == 0 and item["sample_id"] in holdout for item in graph_index):
            raise ValueError("fixed test samples cannot be used as development holdout")
        ids_by_sample = _candidate_ids(candidate_path)
        masks = _holdout_masks(graph_index, ids_by_sample, holdout)
        train = [item for item in graph_index if int(item["fold"]) in {1, 2, 3, 4} and item["sample_id"] not in holdout]
        validation = [item for item in graph_index if item["sample_id"] in holdout]
        return train, validation, masks, {
            "kind": "development_shadow_holdout",
            "holdout_sample_ids": sorted(holdout),
            "test_accessed": False,
        }
    if validation_fold is None:
        train = [item for item in graph_index if item["split"] == "train" and int(item["candidate_count"]) > 0]
        validation = [item for item in graph_index if item["split"] == "validation" and int(item["candidate_count"]) > 0]
        return train, validation, None, {"kind": "fixed", "validation_split": "validation", "test_accessed": False}
    if validation_fold not in {1, 2, 3, 4}:
        raise ValueError("validation_fold must be one of 1,2,3,4 or None")
    ids_by_sample = _candidate_ids(candidate_path)
    masks = _cv_masks(graph_index, ids_by_sample, validation_fold)
    train = [item for item in graph_index if int(item["fold"]) in {1, 2, 3, 4} - {validation_fold}]
    validation = [item for item in graph_index if int(item["fold"]) == validation_fold]
    return train, validation, masks, {"kind": "development_cv", "validation_fold": validation_fold, "test_accessed": False}


def _raw_normalization(rows: list[dict[str, Any]], masks: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    matrices: list[np.ndarray] = []
    for item in rows:
        with np.load(item["graph_path"], allow_pickle=False) as data:
            mask = masks[item["sample_id"]]
            if mask.any():
                matrices.append(data["raw_x"][mask])
    if not matrices:
        raise ValueError("no train candidates remain in CV view")
    merged = np.concatenate(matrices, axis=0).astype(np.float64)
    mean = merged.mean(axis=0)
    std = merged.std(axis=0)
    std[std < 1.0e-8] = 1.0
    return mean.astype(np.float32), std.astype(np.float32)


def _merge_numpy(
    rows: list[dict[str, Any]],
    *,
    masks: dict[str, np.ndarray] | None,
    mean: np.ndarray | None,
    std: np.ndarray | None,
) -> dict[str, np.ndarray]:
    fields = ("operation", "weight", "direction", "source", "split_fractions", "split_fraction_mask", "child_geometry", "child_mask")
    values: dict[str, list[np.ndarray]] = {field: [] for field in fields}
    x_values: list[np.ndarray] = []
    edge_values: list[np.ndarray] = []
    offset = 0
    for item in rows:
        with np.load(item["graph_path"], allow_pickle=False) as data:
            if masks is None:
                x = data["x"]
                edge = data["edge_index"]
                selected = {field: data[field] for field in fields}
            else:
                mask = masks[item["sample_id"]]
                kept = np.flatnonzero(mask)
                remap = np.full(len(mask), -1, dtype=np.int64)
                remap[kept] = np.arange(len(kept), dtype=np.int64)
                raw_edge = data["raw_edge_index"]
                edge_mask = mask[raw_edge[0]] & mask[raw_edge[1]] if raw_edge.size else np.zeros(0, dtype=np.bool_)
                edge = remap[raw_edge[:, edge_mask]] if raw_edge.size else np.empty((2, 0), dtype=np.int64)
                assert mean is not None and std is not None
                x = ((data["raw_x"][mask] - mean) / std).astype(np.float32)
                selected = {field: data[f"raw_{field}"][mask] for field in fields}
            if not len(x):
                continue
            x_values.append(x.astype(np.float32))
            edge_values.append(edge + offset)
            offset += len(x)
            for field in fields:
                values[field].append(selected[field])
    if not x_values:
        raise ValueError("dataset view contains no candidates")
    result = {"x": np.concatenate(x_values, axis=0), "edge_index": np.concatenate(edge_values, axis=1) if edge_values else np.empty((2, 0), dtype=np.int64)}
    result.update({field: np.concatenate(parts, axis=0) for field, parts in values.items()})
    return result


def _to_torch(numpy_batch: dict[str, np.ndarray], device: Any, torch: Any) -> dict[str, Any]:
    float_fields = {"x", "weight", "split_fractions", "split_fraction_mask", "child_geometry", "child_mask"}
    return {
        name: torch.as_tensor(value, dtype=torch.float32 if name in float_fields else torch.long, device=device)
        for name, value in numpy_batch.items()
    }


def _class_weights(operation: np.ndarray, torch: Any, device: Any) -> Any:
    counts = np.bincount(operation, minlength=5).astype(np.float64)
    weights = np.sqrt(counts.sum() / np.maximum(counts, 1.0))
    weights = np.clip(weights / weights.mean(), 0.25, 8.0)
    return torch.as_tensor(weights, dtype=torch.float32, device=device)


def _apply_development_ablation(
    train: dict[str, np.ndarray],
    validation: dict[str, np.ndarray] | None,
    config: M1TrainingConfig,
) -> None:
    feature_count = int(train["x"].shape[1])
    for start, end in config.zero_feature_ranges:
        if end > feature_count:
            raise ValueError(f"zero feature range {(start, end)} exceeds feature count {feature_count}")
        train["x"][:, start:end] = 0.0
        if validation is not None:
            validation["x"][:, start:end] = 0.0
    if config.min_train_label_weight > 0.0:
        train["weight"][train["weight"] < config.min_train_label_weight] = 0.0
        if not np.any(train["weight"] > 0.0):
            raise ValueError("development ablation removed all positive-weight training labels")


def _evaluate(model: Any, batch: dict[str, Any], class_weights: Any, torch: Any, loss_function: Any) -> dict[str, Any]:
    model.eval()
    with torch.no_grad():
        prediction = model(batch["x"], batch["edge_index"])
        loss, parts = loss_function(prediction, batch, operation_class_weights=class_weights)
        predicted = prediction["operation"].argmax(dim=1).cpu().numpy()
    truth = batch["operation"].cpu().numpy()
    weights = batch["weight"].cpu().numpy()
    return {
        "loss": float(loss.item()),
        "loss_parts": {name: float(value.item()) for name, value in parts.items()},
        "operation": operation_metrics(truth, predicted, weights),
    }


def _peak_process_rss_bytes() -> int | None:
    if os.name != "nt":
        try:
            import resource

            value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            return int(value if os.sys.platform == "darwin" else value * 1024)
        except (ImportError, OSError):
            return None
    class Counters(ctypes.Structure):
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
    counters = Counters()
    counters.cb = ctypes.sizeof(Counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    if psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        return int(counters.PeakWorkingSetSize)
    return None


def train_m1_model(config: M1TrainingConfig) -> dict[str, Any]:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch optional dependency is required for P05 M1 training") from exc
    from rcsd_topo_poc.modules.p05_neural_road_generation.m1_network import (
        build_model,
        multitask_loss,
        trainable_parameter_count,
    )

    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    random.seed(config.seed)
    np.random.seed(config.seed)
    torch.manual_seed(config.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(config.seed)
    torch.use_deterministic_algorithms(True, warn_only=True)
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    dataset_root = normalize_runtime_path(config.dataset_run_root).resolve(strict=True)
    dataset_manifest, dataset_paths, graph_index = _verify_dataset(dataset_root)
    train_rows, validation_rows, masks, dataset_view = _view(
        graph_index,
        dataset_paths["candidates"],
        config.validation_fold,
        config.holdout_sample_ids,
        config.train_all_development,
    )
    if masks is None:
        mean = std = None
    else:
        mean, std = _raw_normalization(train_rows, masks)
    train_numpy = _merge_numpy(train_rows, masks=masks, mean=mean, std=std)
    validation_numpy = (
        _merge_numpy(validation_rows, masks=masks, mean=mean, std=std)
        if validation_rows
        else None
    )
    _apply_development_ablation(train_numpy, validation_numpy, config)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train = _to_torch(train_numpy, device, torch)
    validation = _to_torch(validation_numpy, device, torch) if validation_numpy is not None else None
    polyline_points = int(train["child_geometry"].shape[2])
    model = build_model(
        config.model_type,
        int(train["x"].shape[1]),
        hidden_dim=config.hidden_dim,
        layers=config.layers,
        dropout=config.dropout,
        polyline_points=polyline_points,
    ).to(device)
    parameter_count = trainable_parameter_count(model)
    if config.model_type == "graph" and not 8_000_000 <= parameter_count <= 15_000_000:
        raise ValueError(f"graph model parameter count outside M1 contract: {parameter_count}")
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay)
    class_weight_operation = (
        train_numpy["operation"][train_numpy["weight"] > 0.0]
        if config.min_train_label_weight > 0.0
        else train_numpy["operation"]
    )
    class_weights = _class_weights(class_weight_operation, torch, device)
    amp_enabled = device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=amp_enabled)
    history: list[dict[str, Any]] = []
    best_score = -1.0
    best_epoch = 0
    best_state: dict[str, Any] | None = None
    stale_epochs = 0
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    for epoch in range(1, config.epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=amp_enabled):
            prediction = model(train["x"], train["edge_index"])
            loss, parts = multitask_loss(prediction, train, operation_class_weights=class_weights)
        scaler.scale(loss).backward()
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        scaler.step(optimizer)
        scaler.update()
        validation_metrics = (
            _evaluate(model, validation, class_weights, torch, multitask_loss)
            if validation is not None
            else None
        )
        score = (
            float(validation_metrics["operation"]["macro_f1"])
            if validation_metrics is not None
            else None
        )
        history.append(
            {
                "epoch": epoch,
                "train_loss": float(loss.item()),
                "train_loss_parts": {name: float(value.item()) for name, value in parts.items()},
                "validation_loss": validation_metrics["loss"] if validation_metrics is not None else None,
                "validation_macro_f1": score,
                "validation_weighted_accuracy": (
                    validation_metrics["operation"]["weighted_accuracy"]
                    if validation_metrics is not None
                    else None
                ),
            }
        )
        if validation_metrics is None:
            continue
        assert score is not None
        if score > best_score + 1.0e-6:
            best_score = score
            best_epoch = epoch
            best_state = {name: tensor.detach().cpu().clone() for name, tensor in model.state_dict().items()}
            stale_epochs = 0
        else:
            stale_epochs += 1
        if stale_epochs >= config.patience:
            break
    if validation is None:
        best_epoch = len(history)
        best_state = {name: tensor.detach().cpu().clone() for name, tensor in model.state_dict().items()}
    if best_state is None:
        raise RuntimeError("training produced no checkpoint")
    model.load_state_dict(best_state)
    train_metrics = _evaluate(model, train, class_weights, torch, multitask_loss)
    validation_metrics = (
        _evaluate(model, validation, class_weights, torch, multitask_loss)
        if validation is not None
        else None
    )
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    target_root.mkdir(parents=True, exist_ok=False)
    model_config = {
        "model_type": config.model_type,
        "input_dim": int(train["x"].shape[1]),
        "hidden_dim": config.hidden_dim,
        "layers": config.layers,
        "dropout": config.dropout,
        "polyline_points": polyline_points,
        "trainable_parameter_count": parameter_count,
        "operation_class_weights": class_weights.detach().cpu().tolist(),
        "development_ablation": {
            "zero_feature_ranges": [list(item) for item in config.zero_feature_ranges],
            "min_train_label_weight": config.min_train_label_weight,
        },
    }
    checkpoint_path = target_root / "p05_m1_model.pt"
    torch.save(
        {
            "schema_version": "p05-m1-checkpoint-v1",
            "state_dict": best_state,
            "model_config": model_config,
            "dataset_manifest_sha256": sha256_file(dataset_root / "p05_m1_dataset_manifest.json"),
            "dataset_view": dataset_view,
            "normalization": {
                "mean": mean.tolist() if mean is not None else None,
                "std": std.tolist() if std is not None else None,
            },
            "seed": config.seed,
            "best_epoch": best_epoch,
        },
        checkpoint_path,
    )
    history_path = target_root / "p05_m1_training_history.json"
    metrics_path = target_root / "p05_m1_development_metrics.json"
    config_path = target_root / "p05_m1_model_config.json"
    write_json(history_path, {"schema_version": "p05-m1-training-history-v1", "epochs": history})
    write_json(
        metrics_path,
        {
            "schema_version": "p05-m1-development-metrics-v1",
            "dataset_view": dataset_view,
            "train": train_metrics,
            "validation": validation_metrics,
        },
    )
    write_json(config_path, model_config)
    duration = time.perf_counter() - started
    summary = {
        "schema_version": "p05-m1-training-summary-v1",
        "run_id": config.run_id,
        "model_type": config.model_type,
        "dataset_view": dataset_view,
        "device": str(device),
        "train_candidate_count": int(train["x"].shape[0]),
        "validation_candidate_count": int(validation["x"].shape[0]) if validation is not None else 0,
        "trainable_parameter_count": parameter_count,
        "best_epoch": best_epoch,
        "completed_epochs": len(history),
        "validation_operation_macro_f1": (
            validation_metrics["operation"]["macro_f1"] if validation_metrics is not None else None
        ),
        "validation_operation_weighted_accuracy": (
            validation_metrics["operation"]["weighted_accuracy"]
            if validation_metrics is not None
            else None
        ),
        "duration_seconds": duration,
        "peak_process_rss_bytes": _peak_process_rss_bytes(),
        "peak_cuda_memory_bytes": int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0,
    }
    summary_path = target_root / "p05_m1_training_summary.json"
    write_json(summary_path, summary)
    run_manifest = {
        "schema_version": "p05-m1-training-manifest-v1",
        "run_id": config.run_id,
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_manifest_path": str((dataset_root / "p05_m1_dataset_manifest.json").resolve()),
        "dataset_manifest_sha256": sha256_file(dataset_root / "p05_m1_dataset_manifest.json"),
        "dataset_run_id": dataset_manifest["run_id"],
        "dataset_view": dataset_view,
        "seed": config.seed,
        "epochs_requested": config.epochs,
        "learning_rate": config.learning_rate,
        "weight_decay": config.weight_decay,
        "patience": config.patience,
        "development_ablation": model_config["development_ablation"],
        "python": os.sys.version,
        "torch": torch.__version__,
        "cuda_runtime": torch.version.cuda,
        "cuda_available": torch.cuda.is_available(),
        "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "peak_process_rss_bytes": summary["peak_process_rss_bytes"],
        "peak_cuda_memory_bytes": summary["peak_cuda_memory_bytes"],
        "silent_fix": False,
        "test_accessed": False,
        "outputs": {
            "checkpoint": output_record(checkpoint_path),
            "history": output_record(history_path),
            "metrics": output_record(metrics_path),
            "model_config": output_record(config_path),
            "summary": output_record(summary_path),
        },
    }
    manifest_path = target_root / "p05_m1_training_manifest.json"
    write_json(manifest_path, run_manifest)
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["train_m1_model"]
