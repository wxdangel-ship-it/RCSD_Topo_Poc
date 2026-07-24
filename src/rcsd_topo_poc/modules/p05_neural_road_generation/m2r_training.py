from __future__ import annotations

import ctypes
import json
import os
import platform
import random
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_baselines import operation_metrics
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_csv, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_models import M2RTrainingConfig
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


GRAPH_FIELDS = (
    "operation",
    "weight",
    "direction",
    "source",
    "split_fractions",
    "split_fraction_mask",
    "child_geometry",
    "child_mask",
    "t05_endpoint_relation",
    "t07_endpoint_member",
)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _resolve_output(root: Path, record: dict[str, Any]) -> Path:
    path = normalize_runtime_path(str(record.get("path") or ""))
    if not path.is_file():
        path = root / path.name
    if not path.is_file() or sha256_file(path) != record.get("sha256"):
        raise ValueError(f"dataset output missing or hash mismatch: {record}")
    return path.resolve()


def _verify_dataset(root: Path) -> tuple[dict[str, Any], Path, list[dict[str, Any]]]:
    manifest_path = root / "p05_m2r_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "p05-m2r-dataset-manifest-v1" or manifest.get("silent_fix") is not False:
        raise ValueError("unsupported or unsafe M2R dataset manifest")
    scenes_path = _resolve_output(root, manifest["outputs"]["scenes"])
    graph_index_path = _resolve_output(root, manifest["outputs"]["graph_index"])
    graph_index = _read_json(graph_index_path).get("graphs")
    if not isinstance(graph_index, list):
        raise ValueError("M2R graph index is invalid")
    for item in graph_index:
        path = normalize_runtime_path(item["graph_path"])
        if not path.is_file() or sha256_file(path) != item["graph_sha256"]:
            raise ValueError(f"graph missing or hash mismatch: {item['sample_id']}")
        item["graph_path"] = str(path.resolve())
    return manifest, scenes_path, graph_index


def _expand_guard(mask: np.ndarray, edge_index: np.ndarray, hops: int) -> np.ndarray:
    removed = set(np.flatnonzero(~mask).tolist())
    adjacency: dict[int, set[int]] = defaultdict(set)
    for left, right in edge_index.T:
        adjacency[int(left)].add(int(right))
        adjacency[int(right)].add(int(left))
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


def _entity_guard_masks(
    graph_index: list[dict[str, Any]], held_out_fold: int, hops: int
) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    held_out_ids: set[str] = set()
    for item in graph_index:
        if int(item["fold"]) != held_out_fold:
            continue
        with np.load(item["graph_path"], allow_pickle=False) as data:
            held_out_ids.update(data["road_ids"].tolist())
    masks: dict[str, np.ndarray] = {}
    audit: list[dict[str, Any]] = []
    for item in graph_index:
        if int(item["fold"]) == held_out_fold:
            continue
        with np.load(item["graph_path"], allow_pickle=False) as data:
            ids = data["road_ids"].tolist()
            direct = np.asarray([road_id not in held_out_ids for road_id in ids], dtype=np.bool_)
            guarded = _expand_guard(direct, data["edge_index"], hops)
        if any(ids[index] in held_out_ids for index in np.flatnonzero(guarded)):
            raise AssertionError("entity guard retained a held-out Road ID")
        masks[item["sample_id"]] = guarded
        audit.append(
            {
                "sample_id": item["sample_id"],
                "fold": int(item["fold"]),
                "candidate_count": len(ids),
                "direct_overlap_removed": int((~direct).sum()),
                "neighbor_removed": int((direct & ~guarded).sum()),
                "retained_count": int(guarded.sum()),
                "held_out_fold": held_out_fold,
                "guard_hops": hops,
            }
        )
    return masks, audit


def _normalization(rows: list[dict[str, Any]], masks: dict[str, np.ndarray]) -> tuple[np.ndarray, np.ndarray]:
    values = []
    for item in rows:
        with np.load(item["graph_path"], allow_pickle=False) as data:
            mask = masks[item["sample_id"]]
            if mask.any():
                values.append(data["x"][mask].astype(np.float64))
    if not values:
        raise ValueError("entity guard removed all training candidates")
    merged = np.concatenate(values)
    mean = merged.mean(axis=0)
    std = merged.std(axis=0)
    std[std < 1.0e-8] = 1.0
    return mean.astype(np.float32), std.astype(np.float32)


def _merge_graphs(
    rows: list[dict[str, Any]],
    *,
    masks: dict[str, np.ndarray] | None,
    mean: np.ndarray,
    std: np.ndarray,
) -> tuple[dict[str, np.ndarray], list[dict[str, Any]]]:
    values: dict[str, list[np.ndarray]] = {field: [] for field in GRAPH_FIELDS}
    features: list[np.ndarray] = []
    edges: list[np.ndarray] = []
    road_ids: list[np.ndarray] = []
    slices: list[dict[str, Any]] = []
    offset = 0
    for item in rows:
        with np.load(item["graph_path"], allow_pickle=False) as data:
            mask = masks[item["sample_id"]] if masks is not None else np.ones(len(data["x"]), dtype=np.bool_)
            kept = np.flatnonzero(mask)
            if not len(kept):
                continue
            remap = np.full(len(mask), -1, dtype=np.int64)
            remap[kept] = np.arange(len(kept), dtype=np.int64)
            raw_edge = data["edge_index"]
            edge_mask = mask[raw_edge[0]] & mask[raw_edge[1]] if raw_edge.size else np.zeros(0, dtype=np.bool_)
            edge = remap[raw_edge[:, edge_mask]] if raw_edge.size else np.empty((2, 0), dtype=np.int64)
            x = ((data["x"][mask] - mean) / std).astype(np.float32)
            features.append(x)
            edges.append(edge + offset)
            road_ids.append(data["road_ids"][mask])
            for field in GRAPH_FIELDS:
                values[field].append(data[field][mask])
            slices.append({**item, "start": offset, "end": offset + len(x)})
            offset += len(x)
    if not features:
        raise ValueError("graph view contains no candidates")
    batch = {
        "x": np.concatenate(features),
        "edge_index": np.concatenate(edges, axis=1) if edges else np.empty((2, 0), dtype=np.int64),
        "road_ids": np.concatenate(road_ids),
    }
    batch.update({field: np.concatenate(parts) for field, parts in values.items()})
    return batch, slices


def _small_graph_batch(batch: dict[str, np.ndarray], *, per_operation: int = 96) -> dict[str, np.ndarray]:
    selected: set[int] = set()
    for operation in range(5):
        selected.update(np.flatnonzero(batch["operation"] == operation)[:per_operation].tolist())
    for field in ("t05_endpoint_relation", "t07_endpoint_member"):
        target = batch[field]
        selected.update(np.flatnonzero((target == 0).any(axis=1))[:per_operation].tolist())
        selected.update(np.flatnonzero((target == 1).any(axis=1))[:per_operation].tolist())
    kept = np.asarray(sorted(selected), dtype=np.int64)
    if not len(kept):
        raise ValueError("small graph batch selection is empty")
    mask = np.zeros(len(batch["x"]), dtype=np.bool_)
    mask[kept] = True
    remap = np.full(len(mask), -1, dtype=np.int64)
    remap[kept] = np.arange(len(kept), dtype=np.int64)
    edge = batch["edge_index"]
    edge_mask = mask[edge[0]] & mask[edge[1]] if edge.size else np.zeros(0, dtype=np.bool_)
    result = {name: value[mask] for name, value in batch.items() if name != "edge_index"}
    result["edge_index"] = remap[edge[:, edge_mask]] if edge.size else np.empty((2, 0), dtype=np.int64)
    return result


def _small_scene_indices(data: dict[str, np.ndarray], train_indices: np.ndarray, per_class: int = 3) -> np.ndarray:
    selected: set[int] = set()
    for module in (0, 1):
        module_indices = train_indices[data["module"][train_indices] == module]
        for relation in np.unique(data["relation"][module_indices]):
            selected.update(module_indices[data["relation"][module_indices] == relation][:per_class].tolist())
        for accepted in (0, 1):
            selected.update(module_indices[data["accepted"][module_indices] == accepted][:per_class].tolist())
    return np.asarray(sorted(selected), dtype=np.int64)


def _class_weights(labels: np.ndarray, class_count: int, device: Any, torch: Any) -> Any:
    labels = labels[labels >= 0]
    counts = np.bincount(labels, minlength=class_count).astype(np.float64)
    weights = np.sqrt(max(float(counts.sum()), 1.0) / np.maximum(counts, 1.0))
    weights = np.clip(weights / weights.mean(), 0.25, 8.0)
    return torch.as_tensor(weights, dtype=torch.float32, device=device)


def _to_torch(batch: dict[str, np.ndarray], device: Any, torch: Any) -> dict[str, Any]:
    float_fields = {"x", "weight", "split_fractions", "split_fraction_mask", "child_geometry", "child_mask"}
    return {
        name: torch.as_tensor(value, dtype=torch.float32 if name in float_fields else torch.long, device=device)
        for name, value in batch.items()
        if name != "road_ids"
    }


def _scene_batch(data: dict[str, np.ndarray], indices: np.ndarray, device: Any, torch: Any) -> dict[str, Any]:
    return {
        "scene": torch.as_tensor(data["scene"][indices], dtype=torch.float32, device=device) / 255.0,
        "surface": torch.as_tensor(data["surface"][indices], dtype=torch.float32, device=device),
        "module": torch.as_tensor(data["module"][indices], dtype=torch.long, device=device),
        "accepted": torch.as_tensor(data["accepted"][indices], dtype=torch.long, device=device),
        "relation": torch.as_tensor(data["relation"][indices], dtype=torch.long, device=device),
        "weight": torch.as_tensor(data["weight"][indices], dtype=torch.float32, device=device),
        "relation_weight": torch.as_tensor(data["relation_weight"][indices], dtype=torch.float32, device=device),
    }


def _classification_metrics(truth: np.ndarray, predicted: np.ndarray, class_count: int) -> dict[str, float]:
    mask = truth >= 0
    truth = truth[mask]
    predicted = predicted[mask]
    if not len(truth):
        return {"accuracy": 0.0, "macro_f1": 0.0}
    f1 = []
    for label in range(class_count):
        if not np.any(truth == label):
            continue
        tp = int(((truth == label) & (predicted == label)).sum())
        fp = int(((truth != label) & (predicted == label)).sum())
        fn = int(((truth == label) & (predicted != label)).sum())
        f1.append(2.0 * tp / max(2 * tp + fp + fn, 1))
    return {"accuracy": float((truth == predicted).mean()), "macro_f1": float(np.mean(f1)) if f1 else 0.0}


def _evaluate_scene(model: Any, batch: dict[str, Any], loss_kwargs: dict[str, Any], torch: Any) -> dict[str, Any]:
    from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_network import m2r_scene_loss

    model.eval()
    with torch.no_grad():
        prediction = model(scene=batch["scene"])
        total, parts = m2r_scene_loss(prediction, batch, **loss_kwargs)
        surface = (prediction["surface"].sigmoid() >= 0.5).float()
        intersection = (surface * batch["surface"]).sum(dim=(-2, -1))
        dice = (2.0 * intersection + 1.0) / (surface.sum(dim=(-2, -1)) + batch["surface"].sum(dim=(-2, -1)) + 1.0)
        module = batch["module"].cpu().numpy()
        relation = batch["relation"].cpu().numpy()
        result = {
            "loss": float(total.item()),
            "loss_parts": {name: float(value.item()) for name, value in parts.items()},
            "module": _classification_metrics(module, prediction["module"].argmax(1).cpu().numpy(), 2),
            "accepted": _classification_metrics(batch["accepted"].cpu().numpy(), prediction["accepted"].argmax(1).cpu().numpy(), 2),
            "t03_relation": _classification_metrics(relation[module == 0], prediction["t03_relation"].argmax(1).cpu().numpy()[module == 0], 3),
            "t04_relation": _classification_metrics(relation[module == 1], prediction["t04_relation"].argmax(1).cpu().numpy()[module == 1], 2),
            "surface_dice": float(dice.mean().item()),
            "t03_surface_dice": float(dice[batch["module"] == 0].mean().item()),
            "t04_surface_dice": float(dice[batch["module"] == 1].mean().item()),
        }
    return result


def _evaluate_graph(model: Any, batch: dict[str, Any], loss_kwargs: dict[str, Any], torch: Any) -> dict[str, Any]:
    from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_network import m2r_graph_loss

    model.eval()
    with torch.no_grad():
        prediction = model(x=batch["x"], edge_index=batch["edge_index"])
        total, parts = m2r_graph_loss(prediction, batch, **loss_kwargs)
        operation = prediction["operation"].argmax(1).cpu().numpy()
        direction_mask = batch["direction"] >= 0
        source_mask = batch["source"] >= 0
        split_mask = batch["split_fraction_mask"] > 0
        geometry_mask = batch["child_mask"][:, :, None, None] > 0
        split_mae = torch.abs(prediction["split_fraction"] - batch["split_fractions"])[split_mask].mean().item() if split_mask.any() else 0.0
        geometry_mae = torch.abs(prediction["child_geometry"] - batch["child_geometry"])[geometry_mask.expand_as(prediction["child_geometry"])].mean().item() if geometry_mask.any() else 0.0
        return {
            "loss": float(total.item()),
            "loss_parts": {name: float(value.item()) for name, value in parts.items()},
            "operation": operation_metrics(batch["operation"].cpu().numpy(), operation, batch["weight"].cpu().numpy()),
            "direction_accuracy": float((prediction["direction"].argmax(1)[direction_mask] == batch["direction"][direction_mask]).float().mean().item()) if direction_mask.any() else 0.0,
            "source_accuracy": float((prediction["source"].argmax(1)[source_mask] == batch["source"][source_mask]).float().mean().item()) if source_mask.any() else 0.0,
            "split_score": max(0.0, 1.0 - float(split_mae)),
            "geometry_score": max(0.0, 1.0 - float(geometry_mae)),
            "t05_endpoint": _classification_metrics(batch["t05_endpoint_relation"].cpu().numpy().ravel(), prediction["t05_endpoint"].argmax(2).cpu().numpy().ravel(), 2),
            "t07_endpoint": _classification_metrics(batch["t07_endpoint_member"].cpu().numpy().ravel(), prediction.get("t07_endpoint", prediction["t05_endpoint"]).argmax(2).cpu().numpy().ravel(), 2),
        }


def _head_scores(scene: dict[str, Any], graph: dict[str, Any]) -> dict[str, float]:
    return {
        "T03": min(scene["t03_surface_dice"], scene["accepted"]["accuracy"], scene["t03_relation"]["accuracy"]),
        "T04": min(scene["t04_surface_dice"], scene["accepted"]["accuracy"], scene["t04_relation"]["accuracy"]),
        "T05": graph["t05_endpoint"]["macro_f1"],
        "T06": min(
            graph["operation"]["weighted_accuracy"],
            graph["direction_accuracy"],
            graph["source_accuracy"],
            graph["split_score"],
            graph["geometry_score"],
        ),
        "T07": graph["t07_endpoint"]["macro_f1"],
    }


def _gradient_norm(parameters: Iterable[Any]) -> float:
    total = 0.0
    for parameter in parameters:
        if parameter.grad is not None:
            total += float(parameter.grad.detach().float().pow(2).sum().item())
    return total ** 0.5


def _gradient_audit(model: Any) -> dict[str, float]:
    modules = {
        "surface": model.scene_decoder,
        "module": model.scene_module_head,
        "accepted": model.scene_accept_head,
        "t03_relation": model.t03_relation_head,
        "t04_relation": model.t04_relation_head,
        "t05_endpoint": model.t05_endpoint_head,
        "t06_operation": model.t06_heads.operation,
        "t06_direction": model.t06_heads.direction,
        "t06_source": model.t06_heads.source,
        "t06_split_fraction": model.t06_heads.split_fraction,
        "t06_child_geometry": model.t06_heads.child_geometry,
        "shared_latent": model.shared_latent,
    }
    if model.t07_endpoint_head is not None:
        modules["t07_endpoint"] = model.t07_endpoint_head
    return {name: _gradient_norm(module.parameters()) for name, module in modules.items()}


def _peak_process_rss_bytes() -> int | None:
    if os.name != "nt":
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong), ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t), ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t), ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t), ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
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


def train_m2r_model(config: M2RTrainingConfig) -> dict[str, Any]:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for P05 M2R training") from exc
    from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_network import (
        JointM2RRoadNet,
        m2r_graph_loss,
        m2r_scene_loss,
        parameter_count,
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
    dataset_manifest, scenes_path, graph_index = _verify_dataset(dataset_root)
    train_rows = [item for item in graph_index if int(item["fold"]) != config.held_out_fold]
    held_out_rows = [item for item in graph_index if int(item["fold"]) == config.held_out_fold]
    masks, guard_audit = _entity_guard_masks(graph_index, config.held_out_fold, int(dataset_manifest["config"]["entity_guard_hops"]))
    mean, std = _normalization(train_rows, masks)
    train_graph_numpy, _ = _merge_graphs(train_rows, masks=masks, mean=mean, std=std)
    held_out_graph_numpy, held_out_slices = _merge_graphs(held_out_rows, masks=None, mean=mean, std=std)
    with np.load(scenes_path, allow_pickle=False) as stored:
        scene_numpy = {name: stored[name].copy() for name in stored.files}
    train_scene_indices = np.flatnonzero(scene_numpy["fold"] != config.held_out_fold)
    held_out_scene_indices = np.flatnonzero(scene_numpy["fold"] == config.held_out_fold)
    if config.small_batch_overfit:
        train_graph_numpy = _small_graph_batch(train_graph_numpy)
        held_out_graph_numpy = train_graph_numpy
        train_scene_indices = _small_scene_indices(scene_numpy, train_scene_indices)
        held_out_scene_indices = train_scene_indices

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    train_graph = _to_torch(train_graph_numpy, device, torch)
    held_out_graph = _to_torch(held_out_graph_numpy, device, torch)
    model = JointM2RRoadNet(
        int(train_graph["x"].shape[1]), hidden_dim=config.hidden_dim, graph_layers=config.graph_layers,
        dropout=config.dropout, polyline_points=int(train_graph["child_geometry"].shape[2]), include_t07=config.include_t07,
    ).to(device)
    parameters = parameter_count(model)
    if not 8_000_000 <= parameters <= 20_000_000:
        raise ValueError(f"M2R parameter count outside contract: {parameters}")
    operation_weights = _class_weights(train_graph_numpy["operation"], 5, device, torch)
    t05_weights = _class_weights(train_graph_numpy["t05_endpoint_relation"].ravel(), 2, device, torch)
    t07_weights = _class_weights(train_graph_numpy["t07_endpoint_member"].ravel(), 2, device, torch)
    accepted_weights = _class_weights(scene_numpy["accepted"][train_scene_indices], 2, device, torch)
    t03_indices = train_scene_indices[scene_numpy["module"][train_scene_indices] == 0]
    t04_indices = train_scene_indices[scene_numpy["module"][train_scene_indices] == 1]
    scene_loss_kwargs = {
        "accepted_class_weights": accepted_weights,
        "t03_class_weights": _class_weights(scene_numpy["relation"][t03_indices], 3, device, torch),
        "t04_class_weights": _class_weights(scene_numpy["relation"][t04_indices], 2, device, torch),
    }
    graph_loss_kwargs = {
        "operation_class_weights": operation_weights,
        "include_t07": config.include_t07,
        "t05_class_weights": t05_weights,
        "t07_class_weights": t07_weights,
    }
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay)
    amp_enabled = device.type == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=amp_enabled)
    if amp_enabled:
        torch.cuda.reset_peak_memory_stats(device)
    history: list[dict[str, Any]] = []
    best_score = -1.0
    best_state: dict[str, Any] | None = None
    best_epoch = 0
    stale = 0
    gradient_audit: dict[str, float] = {}
    for epoch in range(1, config.epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=amp_enabled):
            graph_prediction = model(x=train_graph["x"], edge_index=train_graph["edge_index"])
            graph_loss, _ = m2r_graph_loss(graph_prediction, train_graph, **graph_loss_kwargs)
        scaler.scale(graph_loss).backward()
        scaler.unscale_(optimizer)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
        scaler.step(optimizer)
        scaler.update()

        permutation = np.random.default_rng(config.seed + epoch).permutation(train_scene_indices)
        scene_loss_value = 0.0
        for start in range(0, len(permutation), 16):
            indices = permutation[start : start + 16]
            scene_batch = _scene_batch(scene_numpy, indices, device, torch)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(device_type=device.type, dtype=torch.float16, enabled=amp_enabled):
                prediction = model(scene=scene_batch["scene"])
                scene_loss, _ = m2r_scene_loss(prediction, scene_batch, **scene_loss_kwargs)
            scaler.scale(scene_loss).backward()
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            scaler.step(optimizer)
            scaler.update()
            scene_loss_value += float(scene_loss.item()) * len(indices)

        held_out_scene = _scene_batch(scene_numpy, held_out_scene_indices, device, torch)
        scene_metrics = _evaluate_scene(model, held_out_scene, scene_loss_kwargs, torch)
        graph_metrics = _evaluate_graph(model, held_out_graph, graph_loss_kwargs, torch)
        scores = _head_scores(scene_metrics, graph_metrics)
        required = [scores[name] for name in ("T03", "T04", "T05", "T06")]
        score = float(np.mean(required))
        history.append({
            "epoch": epoch,
            "train_graph_loss": float(graph_loss.item()),
            "train_scene_loss": scene_loss_value / max(len(permutation), 1),
            "held_out_head_scores": scores,
            "selection_score": score,
        })
        if score > best_score + 1.0e-6:
            best_score = score
            best_epoch = epoch
            best_state = {name: tensor.detach().cpu().clone() for name, tensor in model.state_dict().items()}
            stale = 0
        else:
            stale += 1
        if config.small_batch_overfit and all(value >= 0.95 for value in required):
            break
        if not config.small_batch_overfit and stale >= config.patience:
            break

    if best_state is None:
        raise RuntimeError("M2R training produced no checkpoint")
    model.load_state_dict(best_state)
    audit_graph = _to_torch(_small_graph_batch(train_graph_numpy, per_operation=16), device, torch)
    audit_scene_indices = train_scene_indices[: min(16, len(train_scene_indices))]
    audit_scene = _scene_batch(scene_numpy, audit_scene_indices, device, torch)
    model.train()
    optimizer.zero_grad(set_to_none=True)
    scene_audit_loss, _ = m2r_scene_loss(model(scene=audit_scene["scene"]), audit_scene, **scene_loss_kwargs)
    graph_audit_loss, _ = m2r_graph_loss(model(x=audit_graph["x"], edge_index=audit_graph["edge_index"]), audit_graph, **graph_loss_kwargs)
    (scene_audit_loss + graph_audit_loss).backward()
    gradient_audit = _gradient_audit(model)
    model.load_state_dict(best_state)
    held_out_scene = _scene_batch(scene_numpy, held_out_scene_indices, device, torch)
    final_scene = _evaluate_scene(model, held_out_scene, scene_loss_kwargs, torch)
    final_graph = _evaluate_graph(model, held_out_graph, graph_loss_kwargs, torch)
    final_scores = _head_scores(final_scene, final_graph)

    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    target_root.mkdir(parents=True, exist_ok=False)
    checkpoint_path = target_root / "p05_m2r_model.pt"
    torch.save({
        "schema_version": "p05-m2r-checkpoint-v1",
        "state_dict": best_state,
        "model_config": {
            "road_input_dim": int(train_graph["x"].shape[1]), "hidden_dim": config.hidden_dim,
            "graph_layers": config.graph_layers, "dropout": config.dropout,
            "polyline_points": int(train_graph["child_geometry"].shape[2]), "include_t07": config.include_t07,
            "trainable_parameter_count": parameters,
        },
        "normalization": {"mean": mean.tolist(), "std": std.tolist()},
        "dataset_manifest_sha256": sha256_file(dataset_root / "p05_m2r_dataset_manifest.json"),
        "held_out_fold": config.held_out_fold, "seed": config.seed, "best_epoch": best_epoch,
    }, checkpoint_path)
    history_path = target_root / "p05_m2r_training_history.json"
    metrics_path = target_root / "p05_m2r_metrics.json"
    guard_path = target_root / "p05_m2r_entity_guard.csv"
    gradient_path = target_root / "p05_m2r_gradient_audit.json"
    write_json(history_path, {"schema_version": "p05-m2r-training-history-v1", "epochs": history})
    write_json(metrics_path, {"schema_version": "p05-m2r-metrics-v1", "scene": final_scene, "graph": final_graph, "head_scores": final_scores})
    write_csv(guard_path, guard_audit, ["sample_id", "fold", "candidate_count", "direct_overlap_removed", "neighbor_removed", "retained_count", "held_out_fold", "guard_hops"])
    write_json(gradient_path, {"schema_version": "p05-m2r-gradient-audit-v1", "head_gradient_norms": gradient_audit})
    duration = time.perf_counter() - started
    peak_vram = int(torch.cuda.max_memory_allocated(device)) if amp_enabled else 0
    summary = {
        "schema_version": "p05-m2r-training-summary-v1", "run_id": config.run_id,
        "held_out_fold": config.held_out_fold, "small_batch_overfit": config.small_batch_overfit,
        "include_t07": config.include_t07, "device": str(device), "device_name": torch.cuda.get_device_name(device) if amp_enabled else "CPU",
        "trainable_parameter_count": parameters, "train_scene_count": int(len(train_scene_indices)),
        "held_out_scene_count": int(len(held_out_scene_indices)), "train_graph_candidate_count": int(len(train_graph_numpy["x"])),
        "held_out_graph_candidate_count": int(len(held_out_graph_numpy["x"])),
        "entity_guard_direct_removed": sum(item["direct_overlap_removed"] for item in guard_audit),
        "entity_guard_neighbor_removed": sum(item["neighbor_removed"] for item in guard_audit),
        "entity_guard_retained_overlap_count": 0, "best_epoch": best_epoch, "completed_epochs": len(history),
        "head_scores": final_scores, "small_batch_overfit_pass": all(final_scores[name] >= 0.95 for name in ("T03", "T04", "T05", "T06")),
        "duration_seconds": duration, "peak_cuda_memory_bytes": peak_vram, "peak_process_rss_bytes": _peak_process_rss_bytes(),
        "started_at_utc": started_at.isoformat(), "completed_at_utc": datetime.now(timezone.utc).isoformat(), "silent_fix": False,
    }
    summary_path = target_root / "p05_m2r_training_summary.json"
    write_json(summary_path, summary)
    outputs = {name: output_record(path) for name, path in {
        "checkpoint": checkpoint_path, "history": history_path, "metrics": metrics_path,
        "entity_guard": guard_path, "gradient_audit": gradient_path, "summary": summary_path,
    }.items()}
    manifest_path = target_root / "p05_m2r_training_manifest.json"
    write_json(manifest_path, {
        "schema_version": "p05-m2r-training-manifest-v1", "module_id": "p05_neural_road_generation",
        "run_id": config.run_id, "dataset_manifest_path": str((dataset_root / "p05_m2r_dataset_manifest.json").resolve()),
        "dataset_manifest_sha256": sha256_file(dataset_root / "p05_m2r_dataset_manifest.json"),
        "config": {"held_out_fold": config.held_out_fold, "seed": config.seed, "include_t07": config.include_t07,
            "small_batch_overfit": config.small_batch_overfit, "hidden_dim": config.hidden_dim, "graph_layers": config.graph_layers,
            "dropout": config.dropout, "epochs": config.epochs, "learning_rate": config.learning_rate,
            "weight_decay": config.weight_decay, "patience": config.patience},
        "environment": {"python": platform.python_version(), "platform": platform.platform(), "torch": torch.__version__, "cuda": torch.version.cuda},
        "outputs": outputs, "silent_fix": False,
    })
    return {**summary, "manifest_path": str(manifest_path.resolve()), "manifest_sha256": sha256_file(manifest_path)}


__all__ = ["train_m2r_model"]
