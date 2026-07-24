from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from pyproj import CRS
from shapely.geometry import Point
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p05_neural_road_generation.evaluation import evaluate_frcsd
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_baselines import operation_metrics
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_dataset import OPERATION_NAMES
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_inference import (
    _add_input_node,
    _aggregate,
    _decode_child,
    _generated_id,
    _id_text,
    _integer,
    _line_endpoints,
    _property,
    _read_features,
    _write_vectors,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_csv, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_models import M2REvaluationConfig
from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_training import _classification_metrics
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _verified_path(record: dict[str, Any]) -> Path:
    path = normalize_runtime_path(str(record.get("path") or ""))
    if not path.is_file() or sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"artifact missing or hash mismatch: {path}")
    return path.resolve()


def _dataset(root: Path) -> tuple[dict[str, Any], Path, Path, list[dict[str, Any]], dict[str, dict[str, Path]]]:
    manifest_path = root / "p05_m2r_dataset_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "p05-m2r-dataset-manifest-v1" or manifest.get("silent_fix") is not False:
        raise ValueError("invalid M2R dataset manifest")
    scenes_path = _verified_path(manifest["outputs"]["scenes"])
    graph_index_path = _verified_path(manifest["outputs"]["graph_index"])
    input_artifacts_path = _verified_path(manifest["outputs"]["input_artifacts"])
    graphs = _read_json(graph_index_path).get("graphs")
    if not isinstance(graphs, list):
        raise ValueError("invalid M2R graph index")
    for item in graphs:
        graph_path = normalize_runtime_path(item["graph_path"])
        if not graph_path.is_file() or sha256_file(graph_path) != item["graph_sha256"]:
            raise ValueError(f"graph hash mismatch: {item['sample_id']}")
        item["graph_path"] = str(graph_path.resolve())
    artifacts: dict[str, dict[str, Path]] = defaultdict(dict)
    for row in _read_csv(input_artifacts_path):
        path = normalize_runtime_path(row["path"])
        if not path.is_file() or sha256_file(path) != row["sha256"]:
            raise ValueError(f"input artifact hash mismatch: {row['sample_id']}: {row['role']}")
        artifacts[row["sample_id"]][row["role"]] = path.resolve()
    supervision_root = normalize_runtime_path(manifest["supervision_run_root"])
    supervision_path = supervision_root / "p05_m2r_supervision_manifest.json"
    supervision_manifest = _read_json(supervision_path)
    if sha256_file(supervision_path) != manifest["supervision_manifest_sha256"]:
        raise ValueError("dataset/supervision manifest hash mismatch")
    m0_manifest = _read_json(normalize_runtime_path(supervision_manifest["m0_manifest_path"]))
    for row in _read_csv(_verified_path(m0_manifest["outputs"]["artifacts"])):
        if row["sample_id"] not in artifacts:
            continue
        path = normalize_runtime_path(row["artifact_path"])
        if path.is_file() and sha256_file(path) == row["artifact_sha256"]:
            artifacts[row["sample_id"]].setdefault(row["role"], path.resolve())
    return manifest, manifest_path, scenes_path, graphs, artifacts


def _checkpoints(
    roots: tuple[Path, ...], dataset_manifest_path: Path, *, include_t07: bool
) -> dict[int, tuple[Path, dict[str, Any]]]:
    result: dict[int, tuple[Path, dict[str, Any]]] = {}
    dataset_hash = sha256_file(dataset_manifest_path)
    for configured_root in roots:
        root = normalize_runtime_path(configured_root).resolve(strict=True)
        manifest = _read_json(root / "p05_m2r_training_manifest.json")
        if manifest.get("schema_version") != "p05-m2r-training-manifest-v1" or manifest.get("silent_fix") is not False:
            raise ValueError(f"invalid M2R training manifest: {root}")
        if manifest.get("dataset_manifest_sha256") != dataset_hash:
            raise ValueError(f"checkpoint was trained on a different dataset: {root}")
        if bool(manifest["config"]["include_t07"]) != include_t07:
            raise ValueError(f"checkpoint T07 mode differs from evaluation mode: {root}")
        fold = int(manifest["config"]["held_out_fold"])
        if fold in result:
            raise ValueError(f"duplicate checkpoint for fold {fold}")
        result[fold] = (_verified_path(manifest["outputs"]["checkpoint"]), manifest)
    if set(result) != {0, 1, 2, 3, 4}:
        raise ValueError(f"evaluation requires one checkpoint per fold: got {sorted(result)}")
    return result


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    values = np.exp(shifted)
    return values / values.sum(axis=1, keepdims=True)


def _operation_legality(
    operation: int,
    parent: BaseGeometry,
    split_fraction: np.ndarray,
    child_geometry: np.ndarray,
) -> tuple[bool, str]:
    name = OPERATION_NAMES[operation]
    if name == "DROP":
        return True, ""
    if parent.is_empty or not parent.is_valid or parent.geom_type not in {"LineString", "MultiLineString"}:
        return False, "PARENT_GEOMETRY_INVALID"
    if name == "KEEP":
        try:
            _line_endpoints(parent)
        except ValueError:
            return False, "KEEP_ENDPOINT_SCHEMA_INVALID"
        return True, ""
    child_count = int(name.rsplit("_", 1)[1])
    required_fractions = split_fraction[: max(child_count - 1, 0)]
    if required_fractions.size and (
        not np.isfinite(required_fractions).all()
        or np.any(required_fractions <= 0.0)
        or np.any(required_fractions >= 1.0)
        or np.any(np.diff(required_fractions) <= 0.0)
    ):
        return False, "SPLIT_FRACTION_ORDER_INVALID"
    for child_index in range(child_count):
        try:
            _decode_child(parent, child_geometry[child_index])
        except (IndexError, ValueError):
            return False, "CHILD_GEOMETRY_INVALID"
    return True, ""


def _decode_operations(
    operation_logits: np.ndarray,
    parents: list[BaseGeometry],
    split_fraction: np.ndarray,
    child_geometry: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]], np.ndarray]:
    probabilities = _softmax(operation_logits)
    free = probabilities.argmax(axis=1).astype(np.int64)
    constrained = free.copy()
    free_legal = np.zeros(len(free), dtype=np.bool_)
    interventions: list[dict[str, Any]] = []
    for index, operation in enumerate(free):
        legal, reason = _operation_legality(int(operation), parents[index], split_fraction[index], child_geometry[index])
        free_legal[index] = legal
        if legal:
            continue
        replacement = None
        for candidate in np.argsort(-operation_logits[index]):
            candidate_legal, _ = _operation_legality(int(candidate), parents[index], split_fraction[index], child_geometry[index])
            if candidate_legal:
                replacement = int(candidate)
                break
        if replacement is None:
            raise AssertionError("DROP must always be a generic legal action")
        constrained[index] = replacement
        interventions.append({
            "row_index": index,
            "model_operation": OPERATION_NAMES[int(operation)],
            "model_score": float(probabilities[index, operation]),
            "constraint_code": reason,
            "replacement_operation": OPERATION_NAMES[replacement],
            "replacement_score": float(probabilities[index, replacement]),
            "content_repair": False,
        })
    return free, constrained, interventions, free_legal


def _load_model(checkpoint_path: Path) -> tuple[Any, dict[str, Any], Any, Any]:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch is required for M2R inference") from exc
    from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_network import JointM2RRoadNet

    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    config = checkpoint["model_config"]
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = JointM2RRoadNet(
        int(config["road_input_dim"]), hidden_dim=int(config["hidden_dim"]), graph_layers=int(config["graph_layers"]),
        dropout=float(config["dropout"]), polyline_points=int(config["polyline_points"]), include_t07=bool(config["include_t07"]),
    ).to(device)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    return model, checkpoint, device, torch


def _predict_graph(model: Any, checkpoint: dict[str, Any], device: Any, torch: Any, path: Path) -> tuple[dict[str, np.ndarray], dict[str, np.ndarray]]:
    with np.load(path, allow_pickle=False) as data:
        raw = {name: data[name].copy() for name in data.files}
    mean = np.asarray(checkpoint["normalization"]["mean"], dtype=np.float32)
    std = np.asarray(checkpoint["normalization"]["std"], dtype=np.float32)
    x = ((raw["x"] - mean) / std).astype(np.float32)
    with torch.no_grad():
        output = model(
            x=torch.as_tensor(x, dtype=torch.float32, device=device),
            edge_index=torch.as_tensor(raw["edge_index"], dtype=torch.long, device=device),
        )
    return {name: value.detach().float().cpu().numpy() for name, value in output.items()}, raw


def _predict_scenes(model: Any, device: Any, torch: Any, scenes: np.ndarray, batch_size: int = 32) -> dict[str, np.ndarray]:
    result: dict[str, list[np.ndarray]] = defaultdict(list)
    with torch.no_grad():
        for start in range(0, len(scenes), batch_size):
            batch = torch.as_tensor(scenes[start : start + batch_size], dtype=torch.float32, device=device) / 255.0
            output = model(scene=batch)
            for name, value in output.items():
                result[name].append(value.detach().float().cpu().numpy())
    return {name: np.concatenate(parts) for name, parts in result.items()}


def _candidate_sources(
    raw: dict[str, np.ndarray], artifacts: dict[str, Path]
) -> tuple[list[BaseGeometry], list[dict[str, Any]], dict[str, dict[str, tuple[dict[str, Any], BaseGeometry]]], CRS]:
    roads = {"swsd": _read_features(artifacts["t01_roads"]), "rcsd": _read_features(artifacts["raw_rcsdroad"])}
    nodes = {"swsd": _read_features(artifacts["raw_prepared_swsd_nodes"]), "rcsd": _read_features(artifacts["raw_rcsdnode"])}
    crs_values = [roads[key][1] for key in roads] + [nodes[key][1] for key in nodes]
    if not all(value.equals(crs_values[0]) for value in crs_values[1:]):
        raise ValueError("candidate Road/Node CRS mismatch")
    parents: list[BaseGeometry] = []
    properties: list[dict[str, Any]] = []
    for road_id, source in zip(raw["road_ids"].tolist(), raw["source_roles"].tolist()):
        record = roads[str(source)][0].get(str(road_id))
        if record is None:
            raise ValueError(f"candidate Road {road_id} is missing from {source}")
        props, geometry = record
        properties.append(props)
        parents.append(geometry)
    return parents, properties, {key: value[0] for key, value in nodes.items()}, crs_values[0]


def _materialize(
    *,
    item: dict[str, Any], raw: dict[str, np.ndarray], prediction: dict[str, np.ndarray], operations: np.ndarray,
    mode: str, parents: list[BaseGeometry], properties: list[dict[str, Any]],
    node_lookup: dict[str, dict[str, tuple[dict[str, Any], BaseGeometry]]], crs: CRS,
    artifacts: dict[str, Path], free_legal: np.ndarray, case_root: Path,
) -> dict[str, Any]:
    road_rows: list[dict[str, Any]] = []
    nodes: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    operation_counts: Counter[str] = Counter()
    probabilities = _softmax(prediction["operation"])
    for index, (road_id, source_name) in enumerate(zip(raw["road_ids"].tolist(), raw["source_roles"].tolist())):
        operation = int(operations[index])
        name = OPERATION_NAMES[operation]
        operation_counts[name] += 1
        parent = parents[index]
        props = properties[index]
        source_name = str(source_name)
        if mode == "keep_all":
            direction = _integer(_property(props, "direction"))
            source = _integer(_property(props, "source"))
            confidence = 1.0
        else:
            direction = int(prediction["direction"][index].argmax())
            source = int(prediction["source"][index].argmax())
            confidence = float(probabilities[index, operation])
        if mode == "free" and not bool(free_legal[index]):
            _, reason = _operation_legality(operation, parent, prediction["split_fraction"][index], prediction["child_geometry"][index])
            failures.append(f"Road {road_id}: free decoder generic legality failure: {reason}")
        if name == "DROP":
            continue
        if name == "KEEP":
            start_id = _id_text(_property(props, "snodeid"))
            end_id = _id_text(_property(props, "enodeid"))
            try:
                endpoint_points = _line_endpoints(parent)
            except ValueError as exc:
                failures.append(f"Road {road_id}: {exc}")
                continue
            for node_id, point in zip((start_id, end_id), endpoint_points):
                _add_input_node(nodes, node_id, node_lookup[source_name], failures, fallback_point=point, fallback_source=source)
            road_rows.append({"id": str(road_id), "snodeid": start_id, "enodeid": end_id, "direction": direction,
                "source": source, "parent_id": str(road_id), "operation": name, "confidence": confidence, "geometry": parent})
            continue
        child_count = int(name.rsplit("_", 1)[1])
        for child_index in range(child_count):
            try:
                geometry = _decode_child(parent, prediction["child_geometry"][index, child_index])
            except (IndexError, ValueError) as exc:
                failures.append(f"Road {road_id} child {child_index}: {exc}")
                continue
            child_id = _generated_id("p05r", item["sample_id"], road_id, child_index)
            endpoints = (geometry.coords[0], geometry.coords[-1])
            node_ids = [_generated_id("p05n", item["sample_id"], f"{point[0]:.12f}", f"{point[1]:.12f}") for point in endpoints]
            for node_id, point in zip(node_ids, endpoints):
                candidate = {"geometry": Point(point), "source": source, "origin": "model"}
                previous = nodes.get(node_id)
                if previous is not None and not previous["geometry"].equals_exact(candidate["geometry"], 0.0):
                    failures.append(f"generated Node id collision: {node_id}")
                else:
                    nodes.setdefault(node_id, candidate)
            road_rows.append({"id": child_id, "snodeid": node_ids[0], "enodeid": node_ids[1], "direction": direction,
                "source": source, "parent_id": str(road_id), "operation": name, "confidence": confidence, "geometry": geometry})
    case_root.mkdir(parents=True, exist_ok=False)
    road_path = case_root / "predicted_road.gpkg"
    node_path = case_root / "predicted_node.gpkg"
    _write_vectors(road_path, node_path, crs, road_rows, nodes)
    evaluation = evaluate_frcsd(road_path, node_path, artifacts["t06_frcsd_road"], artifacts["t06_frcsd_node"])
    evaluation.update({"sample_id": item["sample_id"], "business_id": item["business_id"], "fold": int(item["fold"])})
    evaluation["materialization"] = {
        "decoder_mode": mode, "silent_fix": False, "content_repair": False,
        "operation_counts": dict(sorted(operation_counts.items())), "failures": failures,
        "node_origin_counts": dict(sorted(Counter(node["origin"] for node in nodes.values()).items())),
        "road_path": str(road_path.resolve()), "road_sha256": sha256_file(road_path),
        "node_path": str(node_path.resolve()), "node_sha256": sha256_file(node_path),
    }
    write_json(case_root / "metrics.json", evaluation)
    return evaluation


def _directed_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(case["directed_topology"]["f1"]) for case in cases]
    return {"mean": float(np.mean(values)) if values else 0.0, "min": min(values) if values else 0.0, "exact_case_count": sum(value == 1.0 for value in values)}


def _scene_metrics(truth: dict[str, np.ndarray], prediction: dict[str, np.ndarray]) -> dict[str, Any]:
    surface = (1.0 / (1.0 + np.exp(-prediction["surface"])) >= 0.5).astype(np.float32)
    target = truth["surface"].astype(np.float32)
    intersection = (surface * target).sum(axis=(1, 2))
    dice = (2.0 * intersection + 1.0) / (surface.sum(axis=(1, 2)) + target.sum(axis=(1, 2)) + 1.0)
    module = truth["module"]
    relation = truth["relation"]
    return {
        "sample_count": len(module),
        "accepted": _classification_metrics(truth["accepted"], prediction["accepted"].argmax(1), 2),
        "module": _classification_metrics(module, prediction["module"].argmax(1), 2),
        "T03": {"sample_count": int((module == 0).sum()), "surface_dice_mean": float(dice[module == 0].mean()),
            "relation": _classification_metrics(relation[module == 0], prediction["t03_relation"].argmax(1)[module == 0], 3)},
        "T04": {"sample_count": int((module == 1).sum()), "surface_dice_mean": float(dice[module == 1].mean()),
            "relation": _classification_metrics(relation[module == 1], prediction["t04_relation"].argmax(1)[module == 1], 2)},
    }


def evaluate_m2r_oof(config: M2REvaluationConfig) -> dict[str, Any]:
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    dataset_root = normalize_runtime_path(config.dataset_run_root).resolve(strict=True)
    dataset_manifest, dataset_manifest_path, scenes_path, graphs, artifacts = _dataset(dataset_root)
    checkpoints = _checkpoints(config.checkpoint_roots, dataset_manifest_path, include_t07=config.include_t07)
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    target_root.mkdir(parents=True, exist_ok=False)
    with np.load(scenes_path, allow_pickle=False) as stored:
        scenes = {name: stored[name].copy() for name in stored.files}
    scene_predictions: dict[str, np.ndarray] = {}
    operation_truth: list[np.ndarray] = []
    operation_weight: list[np.ndarray] = []
    operation_free: list[np.ndarray] = []
    operation_constrained: list[np.ndarray] = []
    case_results: dict[str, list[dict[str, Any]]] = {"free": [], "constrained": [], "keep_all": []}
    prediction_rows: list[dict[str, Any]] = []
    intervention_rows: list[dict[str, Any]] = []
    total_candidates = 0
    free_legal_count = 0
    peak_vram = 0
    for fold in range(5):
        checkpoint_path, _ = checkpoints[fold]
        model, checkpoint, device, torch = _load_model(checkpoint_path)
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        scene_indices = np.flatnonzero(scenes["fold"] == fold)
        fold_scene = _predict_scenes(model, device, torch, scenes["scene"][scene_indices])
        for name, values in fold_scene.items():
            if name not in scene_predictions:
                scene_predictions[name] = np.zeros((len(scenes["scene"]), *values.shape[1:]), dtype=values.dtype)
            scene_predictions[name][scene_indices] = values
        for item in (entry for entry in graphs if int(entry["fold"]) == fold):
            prediction, raw = _predict_graph(model, checkpoint, device, torch, Path(item["graph_path"]))
            parents, properties, node_lookup, crs = _candidate_sources(raw, artifacts[item["sample_id"]])
            free, constrained, interventions, free_legal = _decode_operations(
                prediction["operation"], parents, prediction["split_fraction"], prediction["child_geometry"])
            keep_all = np.ones(len(free), dtype=np.int64)
            total_candidates += len(free)
            free_legal_count += int(free_legal.sum())
            operation_truth.append(raw["operation"])
            operation_weight.append(raw["weight"])
            operation_free.append(free)
            operation_constrained.append(constrained)
            for row in interventions:
                row.update({"sample_id": item["sample_id"], "road_id": str(raw["road_ids"][row["row_index"]])})
                intervention_rows.append(row)
            probabilities = _softmax(prediction["operation"])
            for index, road_id in enumerate(raw["road_ids"]):
                prediction_rows.append({"sample_id": item["sample_id"], "fold": fold, "road_id": str(road_id),
                    "truth_operation": OPERATION_NAMES[int(raw["operation"][index])], "free_operation": OPERATION_NAMES[int(free[index])],
                    "constrained_operation": OPERATION_NAMES[int(constrained[index])], "free_legal": bool(free_legal[index]),
                    "operation_confidence": float(probabilities[index].max()), "direction": int(prediction["direction"][index].argmax()),
                    "source": int(prediction["source"][index].argmax())})
            case_name = hashlib.sha256(item["sample_id"].encode("utf-8")).hexdigest()[:20]
            for mode, operations in (("free", free), ("constrained", constrained), ("keep_all", keep_all)):
                case_results[mode].append(_materialize(
                    item=item, raw=raw, prediction=prediction, operations=operations, mode=mode,
                    parents=parents, properties=properties, node_lookup=node_lookup, crs=crs,
                    artifacts=artifacts[item["sample_id"]], free_legal=free_legal,
                    case_root=target_root / "cases" / mode / case_name))
        if device.type == "cuda":
            peak_vram = max(peak_vram, int(torch.cuda.max_memory_allocated(device)))
        del model
        if device.type == "cuda":
            torch.cuda.empty_cache()
    truth_operation = np.concatenate(operation_truth)
    weights = np.concatenate(operation_weight)
    keep_all_operations = np.ones(len(truth_operation), dtype=np.int64)
    operation_summary = {
        "free": operation_metrics(truth_operation, np.concatenate(operation_free), weights),
        "constrained": operation_metrics(truth_operation, np.concatenate(operation_constrained), weights),
        "keep_all": operation_metrics(truth_operation, keep_all_operations, weights),
    }
    road_summary: dict[str, Any] = {}
    for mode, cases in case_results.items():
        road_summary[mode] = _aggregate(cases, config.seed)
        road_summary[mode]["directed_topology"] = _directed_summary(cases)
    summary = {
        "schema_version": "p05-m2r-evaluation-summary-v1", "run_id": config.run_id,
        "case_count": len(graphs), "scene": _scene_metrics(scenes, scene_predictions),
        "operation": operation_summary, "road_graph": road_summary,
        "road_f1_delta_free_vs_keep_all": road_summary["free"]["road_object_f1"] - road_summary["keep_all"]["road_object_f1"],
        "road_f1_delta_constrained_vs_keep_all": road_summary["constrained"]["road_object_f1"] - road_summary["keep_all"]["road_object_f1"],
        "generic_constraints": {"candidate_count": total_candidates, "free_legal_count": free_legal_count,
            "free_legal_rate": free_legal_count / total_candidates if total_candidates else 0.0,
            "intervention_count": len(intervention_rows), "intervention_rate": len(intervention_rows) / total_candidates if total_candidates else 0.0,
            "constrained_legal_rate": 1.0, "no_legal_action_count": 0, "content_repair_count": 0},
        "duration_seconds": time.perf_counter() - started, "peak_cuda_memory_bytes": peak_vram,
        "started_at_utc": started_at.isoformat(), "completed_at_utc": datetime.now(timezone.utc).isoformat(), "silent_fix": False,
    }
    summary_path = target_root / "p05_m2r_evaluation_summary.json"
    cases_path = target_root / "p05_m2r_case_metrics.json"
    prediction_path = target_root / "p05_m2r_predictions.csv"
    intervention_path = target_root / "p05_m2r_constraint_interventions.csv"
    write_json(summary_path, summary)
    write_json(cases_path, {"schema_version": "p05-m2r-case-metrics-v1", "decoders": case_results})
    write_csv(prediction_path, prediction_rows, ["sample_id", "fold", "road_id", "truth_operation", "free_operation", "constrained_operation", "free_legal", "operation_confidence", "direction", "source"])
    write_csv(intervention_path, intervention_rows, ["sample_id", "road_id", "row_index", "model_operation", "model_score", "constraint_code", "replacement_operation", "replacement_score", "content_repair"])
    outputs = {name: output_record(path) for name, path in {"summary": summary_path, "cases": cases_path,
        "predictions": prediction_path, "interventions": intervention_path}.items()}
    manifest_path = target_root / "p05_m2r_evaluation_manifest.json"
    checkpoint_hashes = {
        str(fold): sha256_file(normalize_runtime_path(checkpoints[fold][1]["outputs"]["checkpoint"]["path"])) for fold in range(5)
    }
    write_json(manifest_path, {
        "schema_version": "p05-m2r-evaluation-manifest-v1", "module_id": "p05_neural_road_generation", "run_id": config.run_id,
        "dataset_run_id": dataset_manifest["run_id"], "dataset_manifest_sha256": sha256_file(dataset_manifest_path),
        "checkpoint_sha256": checkpoint_hashes, "decoder_protocol": "same_logits_free_and_generic_graph_constraints_v1",
        "include_t07": config.include_t07, "seed": config.seed, "python": os.sys.version, "platform": platform.platform(),
        "outputs": outputs, "silent_fix": False})
    return {**summary, "manifest_path": str(manifest_path.resolve()), "manifest_sha256": sha256_file(manifest_path)}


__all__ = ["evaluate_m2r_oof"]
