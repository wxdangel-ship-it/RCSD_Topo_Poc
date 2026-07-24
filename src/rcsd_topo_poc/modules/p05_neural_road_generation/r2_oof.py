from __future__ import annotations

import csv
import json
import math
import os
import platform
import random
import time
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rcsd_topo_poc.modules.p05_neural_road_generation.evaluation import evaluate_frcsd
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_csv, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_network import m2r_scene_loss
from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_training import _expand_guard
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_gate2 import (
    CoordinateFrame,
    _materialize_prediction,
    _read_json,
    _resolve_output,
    classification_metrics,
    slot_topology_metrics,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_models import R2OOFConfig, R2SlotLimits
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_network import (
    R2GraphGenerator,
    parameter_count,
    r2_graph_loss,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import read_vector_payloads
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def _verify_dataset(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], R2SlotLimits, Path]:
    manifest_path = root / "p05_r2_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "p05-r2-dataset-manifest-v1":
        raise ValueError("unsupported R2 dataset manifest")
    if manifest.get("status") != "completed" or manifest.get("silent_fix") is not False:
        raise ValueError("R2 OOF requires a completed no-silent-fix dataset")
    index_path = _resolve_output(root, dict(manifest["outputs"])["index"])
    schema_path = _resolve_output(root, dict(manifest["outputs"])["schema"])
    schema = _read_json(schema_path)
    if schema.get("oracle_payload_entered_input") is not False:
        raise ValueError("R2 dataset input/target boundary is unsafe")
    rows = list(_read_json(index_path).get("cases") or [])
    if len(rows) != 51 or {int(row["fold"]) for row in rows} != {0, 1, 2, 3, 4}:
        raise ValueError("R2 OOF requires the complete 51-Case five-fold dataset")
    for row in rows:
        path = normalize_runtime_path(row["case_path"]).resolve(strict=True)
        if sha256_file(path) != row["case_sha256"]:
            raise ValueError(f"R2 case hash mismatch: {row['sample_id']}")
        row["case_path"] = str(path)
    limits = R2SlotLimits(**dict(schema["slot_limits"]))
    scene_path = normalize_runtime_path(manifest["m2r_scene_path"]).resolve(strict=True)
    if sha256_file(scene_path) != manifest["m2r_scene_sha256"]:
        raise ValueError("R2 scene lineage hash mismatch")
    return manifest, rows, limits, scene_path


def _load_case(row: dict[str, Any]) -> dict[str, np.ndarray]:
    with np.load(row["case_path"], allow_pickle=False) as source:
        return {name: source[name] for name in source.files}


def _target_guard(rows: list[dict[str, Any]], cases: dict[str, dict[str, np.ndarray]], fold: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    held_road: set[str] = set()
    held_node: set[str] = set()
    for row in rows:
        if int(row["fold"]) == fold:
            held_road.update(cases[row["sample_id"]]["truth_road_ids"].tolist())
            held_node.update(cases[row["sample_id"]]["truth_node_ids"].tolist())
    kept = []
    audit = []
    for row in rows:
        if int(row["fold"]) == fold:
            continue
        data = cases[row["sample_id"]]
        road_overlap = len(set(data["truth_road_ids"].tolist()) & held_road)
        node_overlap = len(set(data["truth_node_ids"].tolist()) & held_node)
        removed = road_overlap > 0 or node_overlap > 0
        audit.append(
            {
                "held_out_fold": fold,
                "sample_id": row["sample_id"],
                "road_overlap_count": road_overlap,
                "node_overlap_count": node_overlap,
                "whole_case_removed": removed,
            }
        )
        if not removed:
            kept.append(row)
    if not kept:
        raise ValueError(f"fold {fold}: target entity guard removed all training cases")
    return kept, audit


def _guarded_input(data: dict[str, np.ndarray], heldout_ids: set[str]) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    ids = data["input_road_ids"].astype(str)
    direct = np.asarray([identifier not in heldout_ids for identifier in ids], dtype=np.bool_)
    guarded = _expand_guard(direct, data["edge_index"], 1)
    kept = np.flatnonzero(guarded)
    if not len(kept):
        raise ValueError("input entity guard removed an entire training graph")
    remap = np.full(len(ids), -1, dtype=np.int64)
    remap[kept] = np.arange(len(kept), dtype=np.int64)
    edge = data["edge_index"]
    edge_mask = guarded[edge[0]] & guarded[edge[1]] if edge.size else np.zeros(0, dtype=np.bool_)
    guarded_edge = remap[edge[:, edge_mask]] if edge.size else np.empty((2, 0), dtype=np.int64)
    return data["input_x"][guarded], guarded_edge, {
        "candidate_count": len(ids),
        "direct_removed": int((~direct).sum()),
        "neighbor_removed": int((direct & ~guarded).sum()),
        "retained_count": int(guarded.sum()),
    }


def _normalization(
    train_rows: list[dict[str, Any]],
    guarded: dict[str, tuple[np.ndarray, np.ndarray]],
) -> tuple[np.ndarray, np.ndarray]:
    merged = np.concatenate([guarded[row["sample_id"]][0].astype(np.float64) for row in train_rows])
    mean = merged.mean(axis=0).astype(np.float32)
    std = merged.std(axis=0).astype(np.float32)
    std[std < 1.0e-6] = 1.0
    return mean, std


def _graph_tensors(
    data: dict[str, np.ndarray],
    x: np.ndarray,
    edge: np.ndarray,
    mean: np.ndarray,
    std: np.ndarray,
    device: Any,
    torch: Any,
) -> tuple[Any, Any, dict[str, Any]]:
    input_tensor = torch.as_tensor((x - mean) / std, dtype=torch.float32, device=device)
    edge_tensor = torch.as_tensor(edge, dtype=torch.long, device=device)
    float_names = {"road_geometry", "node_xy", "t05_node_xy", "counts"}
    target_names = {
        "road_geometry",
        "road_direction",
        "road_source",
        "road_endpoint",
        "node_xy",
        "t05_node_xy",
        "pointer",
        "road_action",
        "node_action",
        "t05_action",
        "counts",
    }
    batch = {
        name: torch.as_tensor(value, dtype=torch.float32 if name in float_names else torch.long, device=device)
        for name, value in data.items()
        if name in target_names
    }
    return input_tensor, edge_tensor, batch


def _scene_arrays(path: Path) -> dict[str, np.ndarray]:
    with np.load(path, allow_pickle=False) as source:
        return {name: source[name] for name in source.files if name != "sample_id"}


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


def _decode_counts(values: np.ndarray, limits: R2SlotLimits) -> list[int]:
    result = []
    for value, limit in zip(
        values,
        (limits.road_slots, limits.node_slots, limits.t05_node_slots, limits.pointer_queries),
        strict=True,
    ):
        result.append(max(1, min(limit, int(round(math.expm1(float(value) * math.log1p(limit)))))))
    return result


def _macro_recall(truth: np.ndarray, predicted: np.ndarray, label: int) -> float:
    mask = truth == label
    return float((predicted[mask] == label).mean()) if mask.any() else 1.0


def _train_fold(
    config: R2OOFConfig,
    fold: int,
    rows: list[dict[str, Any]],
    cases: dict[str, dict[str, np.ndarray]],
    limits: R2SlotLimits,
    scenes: dict[str, np.ndarray],
    fold_root: Path,
) -> tuple[Path, dict[str, Any], list[dict[str, Any]], dict[str, tuple[np.ndarray, np.ndarray]], np.ndarray, np.ndarray]:
    import torch

    heldout_ids: set[str] = set()
    for row in rows:
        if int(row["fold"]) == fold:
            heldout_ids.update(cases[row["sample_id"]]["input_road_ids"].astype(str).tolist())
    train_rows, target_guard_audit = _target_guard(rows, cases, fold)
    guarded: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    input_guard_audit = []
    for row in train_rows:
        x, edge, audit = _guarded_input(cases[row["sample_id"]], heldout_ids)
        guarded[row["sample_id"]] = (x, edge)
        input_guard_audit.append({"held_out_fold": fold, "sample_id": row["sample_id"], **audit})
    mean, std = _normalization(train_rows, guarded)

    seed = config.seed + fold
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = R2GraphGenerator(
        road_input_dim=len(mean),
        limits=limits,
        hidden_dim=config.hidden_dim,
        graph_layers=config.graph_layers,
        query_layers=config.query_layers,
        polyline_points=int(cases[rows[0]["sample_id"]]["road_geometry"].shape[1]),
        dropout=0.05,
        include_scene=True,
    ).to(device)
    initial_checkpoint_path: Path | None = None
    initial_checkpoint_sha256 = ""
    if config.initial_oof_run_root is not None:
        initial_root = normalize_runtime_path(config.initial_oof_run_root).resolve(strict=True)
        initial_checkpoint_path = (initial_root / f"fold_{fold}" / "p05_r2_oof_checkpoint.pt").resolve(strict=True)
        initial = torch.load(initial_checkpoint_path, map_location=device, weights_only=False)
        if int(initial.get("fold", -1)) != fold or dict(initial.get("limits") or {}) != asdict(limits):
            raise ValueError(f"fold {fold}: initial OOF checkpoint identity mismatch")
        if not np.array_equal(initial["mean"], mean) or not np.array_equal(initial["std"], std):
            raise ValueError(f"fold {fold}: initial OOF normalization differs")
        model.load_state_dict(initial["model_state"], strict=True)
        initial_checkpoint_sha256 = sha256_file(initial_checkpoint_path)
    optimizer = torch.optim.AdamW(model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay)
    train_scene_indices = np.flatnonzero(scenes["fold"] != fold)
    curves = []
    for epoch in range(1, config.epochs + 1):
        model.train()
        shuffled = train_rows.copy()
        random.Random(seed + epoch).shuffle(shuffled)
        graph_losses = []
        for row in shuffled:
            data = cases[row["sample_id"]]
            x, edge = guarded[row["sample_id"]]
            input_tensor, edge_tensor, batch = _graph_tensors(data, x, edge, mean, std, device, torch)
            optimizer.zero_grad(set_to_none=True)
            prediction = model.forward_graph(
                input_tensor,
                edge_tensor,
                road_count=len(data["road_geometry"]),
                node_count=len(data["node_xy"]),
                t05_node_count=len(data["t05_node_xy"]),
                pointer_count=len(data["pointer"]),
                road_action_count=len(data["road_action"]),
                node_action_count=len(data["node_action"]),
                t05_action_count=len(data["t05_action"]),
            )
            loss, _ = r2_graph_loss(prediction, batch)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
            optimizer.step()
            graph_losses.append(float(loss.detach().item()))
        scene_losses = []
        shuffled_scene = np.random.default_rng(seed + epoch).permutation(train_scene_indices)
        for start in range(0, len(shuffled_scene), 32):
            indices = shuffled_scene[start : start + 32]
            batch = _scene_batch(scenes, indices, device, torch)
            optimizer.zero_grad(set_to_none=True)
            prediction = model.forward_scene(batch["scene"])
            loss, _ = m2r_scene_loss(prediction, batch)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
            optimizer.step()
            scene_losses.append(float(loss.detach().item()))
        curves.append(
            {
                "fold": fold,
                "epoch": epoch,
                "train_case_count": len(train_rows),
                "graph_loss": float(np.mean(graph_losses)),
                "scene_loss": float(np.mean(scene_losses)),
            }
        )
    checkpoint_path = fold_root / "p05_r2_oof_checkpoint.pt"
    torch.save(
        {
            "model_state": model.state_dict(),
            "fold": fold,
            "limits": asdict(limits),
            "mean": mean,
            "std": std,
            "parameter_count": parameter_count(model),
        },
        checkpoint_path,
    )
    write_csv(fold_root / "p05_r2_oof_training_curves.csv", curves, list(curves[0]))
    write_csv(
        fold_root / "p05_r2_oof_target_guard.csv",
        target_guard_audit,
        list(target_guard_audit[0]),
    )
    write_csv(
        fold_root / "p05_r2_oof_input_guard.csv",
        input_guard_audit,
        list(input_guard_audit[0]),
    )
    fold_summary = {
        "fold": fold,
        "train_case_count": len(train_rows),
        "heldout_case_count": sum(int(row["fold"]) == fold for row in rows),
        "target_guard_removed_case_count": sum(row["whole_case_removed"] for row in target_guard_audit),
        "input_direct_removed": sum(row["direct_removed"] for row in input_guard_audit),
        "input_neighbor_removed": sum(row["neighbor_removed"] for row in input_guard_audit),
        "parameter_count": parameter_count(model),
        "initial_checkpoint_path": str(initial_checkpoint_path) if initial_checkpoint_path else "",
        "initial_checkpoint_sha256": initial_checkpoint_sha256,
    }
    return checkpoint_path, fold_summary, curves, guarded, mean, std


def _scene_oof_metrics(model: Any, scenes: dict[str, np.ndarray], fold: int, device: Any, torch: Any) -> dict[str, Any]:
    indices = np.flatnonzero(scenes["fold"] == fold)
    surface_intersection = surface_sum = target_sum = 0.0
    module_values = []
    relation_values = []
    relation_predictions = []
    accepted_values = []
    accepted_predictions = []
    with torch.no_grad():
        for start in range(0, len(indices), 32):
            batch = _scene_batch(scenes, indices[start : start + 32], device, torch)
            prediction = model.forward_scene(batch["scene"])
            probability = prediction["surface"].sigmoid()
            surface_intersection += float((probability * batch["surface"]).sum().item())
            surface_sum += float(probability.sum().item())
            target_sum += float(batch["surface"].sum().item())
            module = batch["module"].detach().cpu().numpy()
            relation = batch["relation"].detach().cpu().numpy()
            t03_pred = prediction["t03_relation"].argmax(-1).detach().cpu().numpy()
            t04_pred = prediction["t04_relation"].argmax(-1).detach().cpu().numpy()
            relation_pred = np.where(module == 0, t03_pred, t04_pred)
            module_values.append(module)
            relation_values.append(relation)
            relation_predictions.append(relation_pred)
            accepted_values.append(batch["accepted"].detach().cpu().numpy())
            accepted_predictions.append(prediction["accepted"].argmax(-1).detach().cpu().numpy())
    module = np.concatenate(module_values)
    relation = np.concatenate(relation_values)
    relation_pred = np.concatenate(relation_predictions)
    valid = relation >= 0
    t03 = valid & (module == 0)
    t04 = valid & (module == 1)
    return {
        "fold": fold,
        "surface_dice": (2 * surface_intersection + 1) / (surface_sum + target_sum + 1),
        "t03_relation": classification_metrics(relation[t03], relation_pred[t03], 3),
        "t04_relation": classification_metrics(relation[t04], relation_pred[t04], 2),
        "accepted": classification_metrics(
            np.concatenate(accepted_values), np.concatenate(accepted_predictions), 2
        ),
        "scene_count": len(indices),
    }


def evaluate_r2_oof(config: R2OOFConfig) -> dict[str, Any]:
    import torch

    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.use_deterministic_algorithms(True)
    dataset_root = normalize_runtime_path(config.dataset_run_root).resolve(strict=True)
    dataset_manifest, rows, limits, scene_path = _verify_dataset(dataset_root)
    initial_oof_manifest_path: Path | None = None
    initial_oof_manifest_sha256 = ""
    if config.initial_oof_run_root is not None:
        initial_root = normalize_runtime_path(config.initial_oof_run_root).resolve(strict=True)
        initial_oof_manifest_path = (initial_root / "p05_r2_oof_manifest.json").resolve(strict=True)
        initial_manifest = _read_json(initial_oof_manifest_path)
        if initial_manifest.get("schema_version") != "p05-r2-oof-manifest-v1":
            raise ValueError("initial OOF run manifest is incompatible")
        if initial_manifest.get("dataset_manifest_sha256") != sha256_file(dataset_root / "p05_r2_dataset_manifest.json"):
            raise ValueError("initial OOF run uses a different dataset")
        initial_oof_manifest_sha256 = sha256_file(initial_oof_manifest_path)
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)
    cases = {row["sample_id"]: _load_case(row) for row in rows}
    scenes = _scene_arrays(scene_path)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    case_metrics = []
    fold_summaries = []
    scene_metrics = []
    checkpoint_records = {}
    inference_seconds = []
    deterministic_all = True

    for fold in config.folds:
        fold_root = target_root / f"fold_{fold}"
        fold_root.mkdir()
        checkpoint_path, fold_summary, _, _, mean, std = _train_fold(
            config, fold, rows, cases, limits, scenes, fold_root
        )
        checkpoint_records[str(fold)] = output_record(checkpoint_path)
        checkpoint = torch.load(checkpoint_path, map_location=device, weights_only=False)
        model = R2GraphGenerator(
            road_input_dim=len(mean),
            limits=limits,
            hidden_dim=config.hidden_dim,
            graph_layers=config.graph_layers,
            query_layers=config.query_layers,
            polyline_points=int(cases[rows[0]["sample_id"]]["road_geometry"].shape[1]),
            dropout=0.05,
            include_scene=True,
        ).to(device)
        model.load_state_dict(checkpoint["model_state"])
        model.eval()
        scene_metrics.append(_scene_oof_metrics(model, scenes, fold, device, torch))

        for row in [item for item in rows if int(item["fold"]) == fold]:
            case_started = time.perf_counter()
            data = cases[row["sample_id"]]
            x = torch.as_tensor((data["input_x"] - mean) / std, dtype=torch.float32, device=device)
            edge = torch.as_tensor(data["edge_index"], dtype=torch.long, device=device)
            with torch.no_grad():
                probe = model.forward_graph(
                    x,
                    edge,
                    road_count=1,
                    node_count=1,
                    t05_node_count=1,
                    pointer_count=1,
                    road_action_count=len(data["road_action"]),
                    node_action_count=len(data["node_action"]),
                    t05_action_count=len(data["t05_action"]),
                )
                predicted_counts = _decode_counts(probe["counts"].detach().cpu().numpy(), limits)
                prediction = model.forward_graph(
                    x,
                    edge,
                    road_count=predicted_counts[0],
                    node_count=predicted_counts[1],
                    t05_node_count=predicted_counts[2],
                    pointer_count=predicted_counts[3],
                    road_action_count=len(data["road_action"]),
                    node_action_count=len(data["node_action"]),
                    t05_action_count=len(data["t05_action"]),
                )
                repeat = model.forward_graph(
                    x,
                    edge,
                    road_count=predicted_counts[0],
                    node_count=predicted_counts[1],
                    t05_node_count=predicted_counts[2],
                    pointer_count=predicted_counts[3],
                    road_action_count=len(data["road_action"]),
                    node_action_count=len(data["node_action"]),
                    t05_action_count=len(data["t05_action"]),
                )
            deterministic = all(
                torch.equal(prediction[name], repeat[name])
                for name in ("road_geometry", "node_xy", "road_direction", "road_source", "road_endpoint", "pointer")
            )
            deterministic_all = deterministic_all and deterministic
            case_key = __import__("hashlib").sha256(row["sample_id"].encode()).hexdigest()[:20]
            case_root = fold_root / "cases" / case_key
            case_root.mkdir(parents=True)
            free_road = case_root / "free_road.gpkg"
            free_node = case_root / "free_node.gpkg"
            constrained_road = case_root / "constrained_road.gpkg"
            constrained_node = case_root / "constrained_node.gpkg"
            _, road_meta = read_vector_payloads(Path(row["truth_road_path"]), source_role="truth")
            _, node_meta = read_vector_payloads(Path(row["truth_node_path"]), source_role="truth")
            frame = CoordinateFrame(
                float(row["frame_center_x"]), float(row["frame_center_y"]), float(row["frame_scale"])
            )
            _materialize_prediction(prediction, frame, road_meta, node_meta, free_road, free_node)
            _materialize_prediction(
                prediction, frame, road_meta, node_meta, constrained_road, constrained_node
            )
            evaluation = evaluate_frcsd(
                constrained_road,
                constrained_node,
                Path(row["truth_road_path"]),
                Path(row["truth_node_path"]),
            )
            road_action_pred = prediction["road_action"].argmax(-1).detach().cpu().numpy()
            node_action_pred = prediction["node_action"].argmax(-1).detach().cpu().numpy()
            t05_action_pred = prediction["t05_action"].argmax(-1).detach().cpu().numpy()
            road_min = min(predicted_counts[0], len(data["road_geometry"]))
            pointer_min = min(predicted_counts[3], len(data["pointer"]))
            pointer_pred = prediction["pointer"].argmax(-1).detach().cpu().numpy()
            if predicted_counts[2] != len(data["t05_node_xy"]):
                pointer_accuracy = 0.0
            else:
                pointer_accuracy = float(
                    (pointer_pred[:pointer_min] == data["pointer"][:pointer_min]).sum()
                    / max(predicted_counts[3], len(data["pointer"]))
                )
            normalized_topology = {"f1": 0.0, "alignment": "slot_count_mismatch"}
            if predicted_counts[0] == len(data["road_geometry"]) and predicted_counts[1] == len(data["node_xy"]):
                normalized_topology = slot_topology_metrics(
                    prediction["road_endpoint"].argmax(-1).detach().cpu().numpy(),
                    prediction["road_direction"].argmax(-1).detach().cpu().numpy(),
                    data["road_endpoint"],
                    data["road_direction"],
                )
            metric = {
                "sample_id": row["sample_id"],
                "fold": fold,
                "truth_counts": [
                    len(data["road_geometry"]),
                    len(data["node_xy"]),
                    len(data["t05_node_xy"]),
                    len(data["pointer"]),
                ],
                "predicted_counts": predicted_counts,
                "road_action": classification_metrics(data["road_action"], road_action_pred, 5),
                "node_action": classification_metrics(data["node_action"], node_action_pred, 4),
                "t05_action": classification_metrics(data["t05_action"], t05_action_pred, 4),
                "split_recall": _macro_recall(data["road_action"], road_action_pred, 2),
                "pointer_accuracy": pointer_accuracy,
                "road_direction_accuracy": float(
                    (prediction["road_direction"].argmax(-1).detach().cpu().numpy()[:road_min] == data["road_direction"][:road_min]).sum()
                    / max(predicted_counts[0], len(data["road_direction"]))
                ),
                "road_source_accuracy": float(
                    (prediction["road_source"].argmax(-1).detach().cpu().numpy()[:road_min] == data["road_source"][:road_min]).sum()
                    / max(predicted_counts[0], len(data["road_source"]))
                ),
                "normalized_topology": normalized_topology,
                "evaluation": evaluation,
                "deterministic_repeat": deterministic,
                "generic_intervention_count": 0,
                "content_repair": False,
                "inference_seconds": time.perf_counter() - case_started,
                "paths": {
                    "free_road": str(free_road.resolve()),
                    "free_node": str(free_node.resolve()),
                    "constrained_road": str(constrained_road.resolve()),
                    "constrained_node": str(constrained_node.resolve()),
                },
            }
            inference_seconds.append(metric["inference_seconds"])
            case_metrics.append(metric)
        fold_summaries.append(fold_summary)
        del model
        torch.cuda.empty_cache()

    road_f1_values = np.asarray([item["evaluation"]["road_object"]["f1"] for item in case_metrics])
    node_f1_values = np.asarray([item["evaluation"]["node_object"]["f1"] for item in case_metrics])
    topology_values = np.asarray([item["normalized_topology"]["f1"] for item in case_metrics])
    action_values = np.asarray([item["road_action"]["macro_f1"] for item in case_metrics])
    pointer_values = np.asarray([item["pointer_accuracy"] for item in case_metrics])
    split_values = np.asarray([item["split_recall"] for item in case_metrics])
    hard_failure_count = sum(bool(item["evaluation"]["hard_failures"]) for item in case_metrics)
    scene_t03 = float(np.mean([item["t03_relation"]["macro_f1"] for item in scene_metrics]))
    scene_t04 = float(np.mean([item["t04_relation"]["macro_f1"] for item in scene_metrics]))
    surface_dice = float(np.mean([item["surface_dice"] for item in scene_metrics]))
    baseline_path = dataset_root.parent / "p05_m2r_oof_evaluation_t07_off_20260721_01" / "p05_m2r_evaluation_summary.json"
    baseline_road_f1 = 0.6465723463878067
    if not baseline_path.is_file():
        baseline_path = Path("")
    gate3_pass = (
        scene_t03 >= 0.80
        and scene_t04 >= 0.75
        and surface_dice >= 0.80
        and float(pointer_values.mean()) >= 0.90
        and float(action_values.mean()) >= 0.75
        and float(split_values.mean()) >= 0.70
        and float(road_f1_values.mean()) >= max(0.85, baseline_road_f1 + 0.05)
        and float(road_f1_values.min()) >= 0.70
        and float(node_f1_values.mean()) >= 0.90
        and float(topology_values.mean()) == 1.0
        and hard_failure_count == 0
        and deterministic_all
    )
    summary = {
        "schema_version": "p05-r2-oof-summary-v1",
        "case_count": len(case_metrics),
        "gate3_pass": gate3_pass,
        "scene": {"t03_relation_macro_f1": scene_t03, "t04_relation_macro_f1": scene_t04, "surface_dice": surface_dice},
        "pointer_accuracy_mean": float(pointer_values.mean()),
        "road_action_macro_f1_mean": float(action_values.mean()),
        "split_recall_mean": float(split_values.mean()),
        "road_f1_mean": float(road_f1_values.mean()),
        "road_f1_worst": float(road_f1_values.min()),
        "node_f1_mean": float(node_f1_values.mean()),
        "normalized_topology_f1_mean": float(topology_values.mean()),
        "hard_failure_case_count": hard_failure_count,
        "deterministic_repeat_all": deterministic_all,
        "baseline_road_f1": baseline_road_f1,
        "road_f1_delta": float(road_f1_values.mean() - baseline_road_f1),
        "inference_p95_seconds": float(np.percentile(inference_seconds, 95)),
        "fold_summaries": fold_summaries,
        "scene_fold_metrics": scene_metrics,
        "peak_cuda_memory_bytes": int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0,
        "duration_seconds": time.perf_counter() - started,
        "silent_fix": False,
        "content_repair": False,
    }
    case_metrics_path = target_root / "p05_r2_oof_case_metrics.json"
    case_index_path = target_root / "p05_r2_oof_case_index.csv"
    summary_path = target_root / "p05_r2_oof_summary.json"
    report_path = target_root / "p05_r2_oof_report.md"
    write_json(case_metrics_path, {"schema_version": "p05-r2-oof-case-metrics-v1", "cases": case_metrics})
    flat_rows = [
        {
            "sample_id": item["sample_id"],
            "fold": item["fold"],
            "road_f1": item["evaluation"]["road_object"]["f1"],
            "node_f1": item["evaluation"]["node_object"]["f1"],
            "normalized_topology_f1": item["normalized_topology"]["f1"],
            "road_action_macro_f1": item["road_action"]["macro_f1"],
            "pointer_accuracy": item["pointer_accuracy"],
            "split_recall": item["split_recall"],
            "hard_failure_count": len(item["evaluation"]["hard_failures"]),
            "deterministic_repeat": item["deterministic_repeat"],
            "inference_seconds": item["inference_seconds"],
        }
        for item in case_metrics
    ]
    write_csv(case_index_path, flat_rows, list(flat_rows[0]))
    write_json(summary_path, summary)
    report_path.write_text(
        "# P05-R2 grouped 5-fold OOF\n\n"
        f"- Road F1 mean/worst: `{summary['road_f1_mean']:.6f}` / `{summary['road_f1_worst']:.6f}`\n"
        f"- Node F1 mean: `{summary['node_f1_mean']:.6f}`\n"
        f"- normalized topology F1: `{summary['normalized_topology_f1_mean']:.6f}`\n"
        f"- T05 pointer: `{summary['pointer_accuracy_mean']:.6f}`\n"
        f"- T03/T04 relation: `{scene_t03:.6f}` / `{scene_t04:.6f}`\n"
        f"- surface Dice: `{surface_dice:.6f}`\n"
        f"- Gate 3: `{'PASS' if gate3_pass else 'FAIL'}`\n",
        encoding="utf-8",
    )
    outputs = {
        "case_metrics": output_record(case_metrics_path),
        "case_index": output_record(case_index_path),
        "summary": output_record(summary_path),
        "report": output_record(report_path),
    }
    manifest = {
        "schema_version": "p05-r2-oof-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "gate3_passed" if gate3_pass else "gate3_failed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_manifest_path": str(dataset_root / "p05_r2_dataset_manifest.json"),
        "dataset_manifest_sha256": sha256_file(dataset_root / "p05_r2_dataset_manifest.json"),
        "initial_oof_manifest_path": str(initial_oof_manifest_path) if initial_oof_manifest_path else "",
        "initial_oof_manifest_sha256": initial_oof_manifest_sha256,
        "parameters": {name: str(value) if isinstance(value, Path) else value for name, value in asdict(config).items()},
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "device": torch.cuda.get_device_name(device) if device.type == "cuda" else "cpu",
        },
        "baseline": {
            "path": str(baseline_path) if baseline_path else "",
            "sha256": sha256_file(baseline_path) if baseline_path and baseline_path.is_file() else "",
            "road_f1": baseline_road_f1,
        },
        "checkpoints": checkpoint_records,
        "outputs": outputs,
        "silent_fix": False,
        "content_repair": False,
    }
    manifest_path = target_root / "p05_r2_oof_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["evaluate_r2_oof"]
