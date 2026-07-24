from __future__ import annotations

import csv
import json
import math
import os
import platform
import random
import time
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from shapely.geometry import LineString, MultiLineString, Point, mapping, shape

from rcsd_topo_poc.modules.p05_neural_road_generation.evaluation import evaluate_frcsd
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_csv, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_network import m2r_scene_loss
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_edit import (
    NODE_ACTIONS,
    ROAD_ACTIONS,
    read_vector_payloads,
    write_vector_payloads,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_models import R2Gate2Config, R2SlotLimits
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_network import (
    R2GraphGenerator,
    parameter_count,
    r2_graph_loss,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


@dataclass(frozen=True)
class CoordinateFrame:
    center_x: float
    center_y: float
    scale: float

    def normalize(self, x: float, y: float) -> tuple[float, float]:
        return ((x - self.center_x) / self.scale, (y - self.center_y) / self.scale)

    def denormalize(self, x: float, y: float) -> tuple[float, float]:
        return (x * self.scale + self.center_x, y * self.scale + self.center_y)


def resample_geometry(geometry: dict[str, Any], frame: CoordinateFrame, *, points: int) -> np.ndarray:
    item = shape(geometry)
    if item.is_empty or item.length <= 0:
        raise ValueError("Road target geometry must be finite and non-empty")
    distances = np.linspace(0.0, float(item.length), points)
    coordinates = [item.interpolate(float(distance)).coords[0] for distance in distances]
    return np.asarray([frame.normalize(float(x), float(y)) for x, y, *_ in coordinates], dtype=np.float32)


def classification_metrics(truth: np.ndarray, predicted: np.ndarray, class_count: int) -> dict[str, float]:
    if not len(truth):
        return {"accuracy": 0.0, "macro_f1": 0.0}
    scores: list[float] = []
    for label in range(class_count):
        if not np.any(truth == label):
            continue
        true_positive = int(((truth == label) & (predicted == label)).sum())
        false_positive = int(((truth != label) & (predicted == label)).sum())
        false_negative = int(((truth == label) & (predicted != label)).sum())
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(2 * true_positive / denominator if denominator else 0.0)
    return {
        "accuracy": float((truth == predicted).mean()),
        "macro_f1": float(np.mean(scores)) if scores else 0.0,
    }


def slot_topology_metrics(
    candidate_endpoint: np.ndarray,
    candidate_direction: np.ndarray,
    truth_endpoint: np.ndarray,
    truth_direction: np.ndarray,
) -> dict[str, float]:
    def edges(endpoints: np.ndarray, directions: np.ndarray) -> Counter[tuple[int, int]]:
        result: Counter[tuple[int, int]] = Counter()
        for (start, end), direction in zip(endpoints, directions, strict=True):
            result[(int(start), int(end))] += 1
            if int(direction) == 0:
                result[(int(end), int(start))] += 1
        return result

    candidate = edges(candidate_endpoint, candidate_direction)
    truth = edges(truth_endpoint, truth_direction)
    matched = sum((candidate & truth).values())
    candidate_count = sum(candidate.values())
    truth_count = sum(truth.values())
    precision = matched / candidate_count if candidate_count else float(truth_count == 0)
    recall = matched / truth_count if truth_count else float(candidate_count == 0)
    return {
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        "matched_edge_count": matched,
        "candidate_edge_count": candidate_count,
        "truth_edge_count": truth_count,
        "alignment": "generated_slot_to_truth_slot",
    }


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _resolve_output(root: Path, record: dict[str, Any]) -> Path:
    path = normalize_runtime_path(str(record.get("path") or ""))
    if not path.is_file():
        path = root / path.name
    path = path.resolve(strict=True)
    if sha256_file(path) != str(record.get("sha256") or ""):
        raise ValueError(f"output hash mismatch: {path}")
    return path


def _oracle_lineage(root: Path) -> tuple[dict[str, Any], dict[str, Path], Path, dict[str, Any]]:
    manifest_path = root / "p05_r2_oracle_manifest.json"
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "p05-r2-oracle-manifest-v1":
        raise ValueError("unsupported R2 oracle manifest")
    if manifest.get("status") != "gate1_passed" or manifest.get("silent_fix") is not False:
        raise ValueError("R2 Gate 2 requires a passed, no-silent-fix oracle run")
    outputs = {name: _resolve_output(root, record) for name, record in dict(manifest["outputs"]).items()}
    summary = _read_json(outputs["summary"])
    if summary.get("gate1_pass") is not True or int(summary.get("case_count", 0)) != 51:
        raise ValueError("R2 oracle summary does not satisfy Gate 1")
    dataset_manifest_path = normalize_runtime_path(str(manifest["m2r_dataset_manifest_path"])).resolve(strict=True)
    if sha256_file(dataset_manifest_path) != str(manifest["m2r_dataset_manifest_sha256"]):
        raise ValueError("M2R dataset manifest differs from oracle lineage")
    return manifest, outputs, dataset_manifest_path.parent, _read_json(dataset_manifest_path)


def _jsonl_for_sample(path: Path, sample_id: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            if row.get("sample_id") == sample_id:
                rows.append(row)
    return rows


def _choose_sample(metrics_path: Path, requested: str) -> str:
    cases = list(_read_json(metrics_path).get("cases") or [])
    if requested:
        if not any(str(case.get("sample_id")) == requested for case in cases):
            raise ValueError(f"selected Gate 2 sample is absent: {requested}")
        return requested
    eligible = []
    for case in cases:
        road = set(dict(case["road_summary"]["action_counts"]))
        node = set(dict(case["node_summary"]["action_counts"]))
        if road == set(ROAD_ACTIONS) and node == set(NODE_ACTIONS) and int(case["pointer_summary"]["target_count"]) > 0:
            eligible.append(case)
    if not eligible:
        raise ValueError("no Gate 2 sample covers every Road/Node action and pointer")
    selected = min(eligible, key=lambda item: (int(item["road_summary"]["truth_count"]), str(item["sample_id"])))
    return str(selected["sample_id"])


def _property(payload: dict[str, Any], name: str) -> Any:
    folded = name.casefold()
    for key, value in dict(payload.get("properties") or {}).items():
        if str(key).casefold() == folded:
            return value
    return None


def _id_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _merge_payloads(paths: Iterable[Path], role: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in paths:
        payloads, _ = read_vector_payloads(path, source_role=role)
        result.update(payloads)
    return result


def _frame(payload_groups: Iterable[dict[str, dict[str, Any]]]) -> CoordinateFrame:
    bounds = []
    for payloads in payload_groups:
        for payload in payloads.values():
            geometry = payload.get("geometry")
            if geometry is not None:
                bounds.append(shape(geometry).bounds)
    if not bounds:
        raise ValueError("input graph has no geometry for R2 coordinate frame")
    min_x = min(item[0] for item in bounds)
    min_y = min(item[1] for item in bounds)
    max_x = max(item[2] for item in bounds)
    max_y = max(item[3] for item in bounds)
    scale = max(max_x - min_x, max_y - min_y, 1.0) * 1.2
    return CoordinateFrame((min_x + max_x) / 2, (min_y + max_y) / 2, scale)


def _spatial_order(payloads: dict[str, dict[str, Any]], frame: CoordinateFrame) -> list[dict[str, Any]]:
    def key(payload: dict[str, Any]) -> tuple[float, float, str]:
        centroid = shape(payload["geometry"]).centroid
        x, y = frame.normalize(float(centroid.x), float(centroid.y))
        return (round(x, 8), round(y, 8), str(payload["id"]))

    return sorted(payloads.values(), key=key)


def _node_targets(
    payloads: dict[str, dict[str, Any]], frame: CoordinateFrame
) -> tuple[list[dict[str, Any]], np.ndarray, dict[str, int]]:
    ordered = _spatial_order(payloads, frame)
    coordinates = []
    by_id: dict[str, int] = {}
    for index, payload in enumerate(ordered):
        point = shape(payload["geometry"])
        coordinates.append(frame.normalize(float(point.x), float(point.y)))
        by_id[str(payload["id"])] = index
    return ordered, np.asarray(coordinates, dtype=np.float32), by_id


def _road_targets(
    payloads: dict[str, dict[str, Any]],
    frame: CoordinateFrame,
    node_slots: dict[str, int],
    points: int,
) -> tuple[list[dict[str, Any]], dict[str, np.ndarray]]:
    ordered = _spatial_order(payloads, frame)
    geometry = []
    direction = []
    source = []
    endpoints = []
    for payload in ordered:
        geometry.append(resample_geometry(payload["geometry"], frame, points=points))
        direction_value = int(float(_property(payload, "direction")))
        source_value = int(float(_property(payload, "source")))
        if direction_value not in {1, 2} or source_value not in {1, 2}:
            raise ValueError(f"unsupported R2 Road attributes: direction={direction_value}, source={source_value}")
        direction.append(direction_value - 1)
        source.append(source_value - 1)
        start = _id_text(_property(payload, "snodeid"))
        end = _id_text(_property(payload, "enodeid"))
        if start not in node_slots or end not in node_slots:
            raise ValueError(f"Road endpoints are not present in truth Node slots: {payload['id']}")
        endpoints.append((node_slots[start], node_slots[end]))
    return ordered, {
        "road_geometry": np.asarray(geometry, dtype=np.float32),
        "road_direction": np.asarray(direction, dtype=np.int64),
        "road_source": np.asarray(source, dtype=np.int64),
        "road_endpoint": np.asarray(endpoints, dtype=np.int64),
    }


def _action_targets(edits: list[dict[str, Any]], actions: tuple[str, ...]) -> np.ndarray:
    lookup = {name: index for index, name in enumerate(actions)}
    return np.asarray([lookup[str(edit["action"])] for edit in edits], dtype=np.int64)


def _pointer_targets(
    rows: list[dict[str, str]],
    ordered_t05_nodes: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], np.ndarray]:
    aliases: dict[str, int] = {}
    for index, payload in enumerate(ordered_t05_nodes):
        aliases[str(payload["id"])] = index
        mainnode_id = _id_text(_property(payload, "mainnodeid"))
        if mainnode_id not in {"", "0", "0.0"}:
            aliases.setdefault(mainnode_id, index)
    ordered_rows = sorted(rows, key=lambda row: str(row["target_id"]))
    no_match_index = len(ordered_t05_nodes)
    targets = []
    for row in ordered_rows:
        selected = str(row.get("selected_base_id") or "")
        if selected:
            if selected not in aliases:
                raise ValueError(f"T05 pointer target absent from materialized candidate slots: {selected}")
            targets.append(aliases[selected])
        else:
            targets.append(no_match_index)
    return ordered_rows, np.asarray(targets, dtype=np.int64)


def _slot_limits(outputs: dict[str, Path]) -> R2SlotLimits:
    action_counts: dict[str, Counter[str]] = {}
    for key in ("road_edits", "node_edits", "t05_node_edits"):
        counts: Counter[str] = Counter()
        with outputs[key].open("r", encoding="utf-8") as stream:
            for line in stream:
                counts[str(json.loads(line)["sample_id"])] += 1
        action_counts[key] = counts
    metrics = list(_read_json(outputs["case_metrics"]).get("cases") or [])
    return R2SlotLimits(
        road_slots=max(int(item["road_summary"]["truth_count"]) for item in metrics),
        node_slots=max(int(item["node_summary"]["truth_count"]) for item in metrics),
        t05_node_slots=max(int(item["t05_node_summary"]["truth_count"]) for item in metrics),
        pointer_queries=max(int(item["pointer_summary"]["target_count"]) for item in metrics),
        road_action_queries=max(action_counts["road_edits"].values()),
        node_action_queries=max(action_counts["node_edits"].values()),
        t05_action_queries=max(action_counts["t05_node_edits"].values()),
    )


def _scene_data(dataset_root: Path, dataset_manifest: dict[str, Any]) -> dict[str, np.ndarray]:
    path = _resolve_output(dataset_root, dict(dataset_manifest["outputs"])["scenes"])
    with np.load(path, allow_pickle=False) as source:
        all_data = {name: source[name] for name in source.files}
    selected: set[int] = set()
    for module in (0, 1):
        candidates = np.flatnonzero(all_data["module"] == module)
        for relation in np.unique(all_data["relation"][candidates]):
            selected.update(candidates[all_data["relation"][candidates] == relation][:3].tolist())
        for accepted in (0, 1):
            selected.update(candidates[all_data["accepted"][candidates] == accepted][:3].tolist())
    indices = np.asarray(sorted(selected), dtype=np.int64)
    return {name: value[indices] for name, value in all_data.items() if name != "sample_id"}


def _torch_graph_batch(batch: dict[str, np.ndarray], device: Any, torch: Any) -> dict[str, Any]:
    float_names = {"road_geometry", "node_xy", "t05_node_xy", "counts"}
    return {
        name: torch.as_tensor(value, dtype=torch.float32 if name in float_names else torch.long, device=device)
        for name, value in batch.items()
        if name not in {"x", "edge_index"}
    }


def _torch_scene_batch(data: dict[str, np.ndarray], device: Any, torch: Any) -> dict[str, Any]:
    return {
        "scene": torch.as_tensor(data["scene"], dtype=torch.float32, device=device) / 255.0,
        "surface": torch.as_tensor(data["surface"], dtype=torch.float32, device=device),
        "module": torch.as_tensor(data["module"], dtype=torch.long, device=device),
        "accepted": torch.as_tensor(data["accepted"], dtype=torch.long, device=device),
        "relation": torch.as_tensor(data["relation"], dtype=torch.long, device=device),
        "weight": torch.as_tensor(data["weight"], dtype=torch.float32, device=device),
        "relation_weight": torch.as_tensor(data["relation_weight"], dtype=torch.float32, device=device),
    }


def _graph_metrics(
    prediction: dict[str, Any], batch: dict[str, Any], frame: CoordinateFrame, limits: R2SlotLimits
) -> dict[str, Any]:
    def numpy(value: Any) -> np.ndarray:
        return value.detach().cpu().numpy()

    result: dict[str, Any] = {}
    for name, classes in (("road_action", 5), ("node_action", 4), ("t05_action", 4)):
        result[name] = classification_metrics(numpy(batch[name]), numpy(prediction[name].argmax(-1)), classes)
    for name in ("road_direction", "road_source"):
        result[name + "_accuracy"] = float((numpy(prediction[name].argmax(-1)) == numpy(batch[name])).mean())
    result["endpoint_accuracy"] = float(
        (numpy(prediction["road_endpoint"].argmax(-1)) == numpy(batch["road_endpoint"])).mean()
    )
    result["pointer_accuracy"] = float((numpy(prediction["pointer"].argmax(-1)) == numpy(batch["pointer"])).mean())
    node_error = np.linalg.norm(numpy(prediction["node_xy"]) - numpy(batch["node_xy"]), axis=1) * frame.scale
    road_error = np.linalg.norm(
        numpy(prediction["road_geometry"]) - numpy(batch["road_geometry"]), axis=2
    ) * frame.scale
    result["node_max_error_m"] = float(node_error.max())
    result["road_point_max_error_m"] = float(road_error.max())
    predicted_counts = []
    for value, limit in zip(
        numpy(prediction["counts"]),
        (limits.road_slots, limits.node_slots, limits.t05_node_slots, limits.pointer_queries),
        strict=True,
    ):
        predicted_counts.append(int(round(math.expm1(float(value) * math.log1p(limit)))))
    result["predicted_counts"] = predicted_counts
    return result


def _scene_metrics(prediction: dict[str, Any], batch: dict[str, Any]) -> dict[str, float]:
    probability = prediction["surface"].sigmoid()
    target = batch["surface"]
    intersection = (probability * target).sum(dim=(-2, -1))
    dice = (2 * intersection + 1) / (probability.sum(dim=(-2, -1)) + target.sum(dim=(-2, -1)) + 1)
    module = batch["module"]
    relation = batch["relation"]
    t03 = (module == 0) & (relation >= 0)
    t04 = (module == 1) & (relation >= 0)
    return {
        "surface_dice": float(dice.mean().item()),
        "accepted_accuracy": float((prediction["accepted"].argmax(-1) == batch["accepted"]).float().mean().item()),
        "t03_relation_accuracy": float(
            (prediction["t03_relation"].argmax(-1)[t03] == relation[t03]).float().mean().item()
        ),
        "t04_relation_accuracy": float(
            (prediction["t04_relation"].argmax(-1)[t04] == relation[t04]).float().mean().item()
        ),
    }


def _set_property(properties: dict[str, Any], name: str, value: Any) -> None:
    folded = name.casefold()
    for key in list(properties):
        if str(key).casefold() == folded:
            properties[key] = value
            return
    properties[name] = value


def _materialize_prediction(
    prediction: dict[str, Any],
    frame: CoordinateFrame,
    road_meta: dict[str, Any],
    node_meta: dict[str, Any],
    road_path: Path,
    node_path: Path,
) -> None:
    road_geometry = prediction["road_geometry"].detach().cpu().numpy()
    node_xy = prediction["node_xy"].detach().cpu().numpy()
    direction = prediction["road_direction"].argmax(-1).detach().cpu().numpy() + 1
    source = prediction["road_source"].argmax(-1).detach().cpu().numpy() + 1
    endpoints = prediction["road_endpoint"].argmax(-1).detach().cpu().numpy()
    node_payloads = []
    node_ids = [-(index + 1) for index in range(len(node_xy))]
    for index, coordinate in enumerate(node_xy):
        x, y = frame.denormalize(float(coordinate[0]), float(coordinate[1]))
        properties = {name: None for name in dict(node_meta["schema"]["properties"])}
        _set_property(properties, "id", node_ids[index])
        node_payloads.append({"id": str(node_ids[index]), "geometry": mapping(Point(x, y)), "properties": properties})
    road_payloads = []
    for index, coordinates in enumerate(road_geometry):
        points = [frame.denormalize(float(x), float(y)) for x, y in coordinates]
        properties = {name: None for name in dict(road_meta["schema"]["properties"])}
        road_id = -(1_000_000 + index)
        _set_property(properties, "id", str(road_id))
        _set_property(properties, "snodeid", str(node_ids[int(endpoints[index, 0])]))
        _set_property(properties, "enodeid", str(node_ids[int(endpoints[index, 1])]))
        _set_property(properties, "direction", int(direction[index]))
        _set_property(properties, "source", int(source[index]))
        line = LineString(points)
        schema_geometry = str(road_meta["schema"].get("geometry") or "")
        output_geometry = MultiLineString([line]) if "multilinestring" in schema_geometry.casefold() else line
        road_payloads.append(
            {"id": str(road_id), "geometry": mapping(output_geometry), "properties": properties}
        )
    write_vector_payloads(node_path, node_payloads, meta=node_meta)
    write_vector_payloads(road_path, road_payloads, meta=road_meta)


def train_r2_gate2(config: R2Gate2Config) -> dict[str, Any]:
    import torch

    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    root = normalize_runtime_path(config.oracle_run_root).resolve(strict=True)
    oracle_manifest, outputs, dataset_root, dataset_manifest = _oracle_lineage(root)
    sample_id = _choose_sample(outputs["case_metrics"], config.selected_sample_id)
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    if target_root.exists():
        raise FileExistsError(target_root)
    target_root.mkdir(parents=True)

    case_row = next(row for row in _read_csv(outputs["case_index"]) if row["sample_id"] == sample_id)
    pointer_rows = [row for row in _read_csv(outputs["t05_pointers"]) if row["sample_id"] == sample_id]
    road_edits = _jsonl_for_sample(outputs["road_edits"], sample_id)
    node_edits = _jsonl_for_sample(outputs["node_edits"], sample_id)
    t05_edits = _jsonl_for_sample(outputs["t05_node_edits"], sample_id)
    truth_roads, road_meta = read_vector_payloads(Path(case_row["truth_road_path"]), source_role="truth")
    truth_nodes, node_meta = read_vector_payloads(Path(case_row["truth_node_path"]), source_role="truth")
    t05_nodes, _ = read_vector_payloads(Path(case_row["t05_node_truth_path"]), source_role="truth")

    artifact_path = _resolve_output(dataset_root, dict(dataset_manifest["outputs"])["input_artifacts"])
    roles = {row["role"]: normalize_runtime_path(row["path"]) for row in _read_csv(artifact_path) if row["sample_id"] == sample_id}
    base_roads = _merge_payloads((roles["t01_roads"], roles["raw_rcsdroad"]), "input")
    base_nodes = _merge_payloads((roles["raw_prepared_swsd_nodes"], roles["raw_rcsdnode"]), "input")
    frame = _frame((base_roads, base_nodes))
    ordered_nodes, node_xy, node_slots = _node_targets(truth_nodes, frame)
    ordered_roads, road_targets = _road_targets(
        truth_roads, frame, node_slots, config.polyline_points
    )
    ordered_t05_nodes, t05_node_xy, _ = _node_targets(t05_nodes, frame)
    ordered_pointers, pointer_target = _pointer_targets(pointer_rows, ordered_t05_nodes)

    graph_index_path = _resolve_output(dataset_root, dict(dataset_manifest["outputs"])["graph_index"])
    graph_row = next(row for row in list(_read_json(graph_index_path)["graphs"]) if row["sample_id"] == sample_id)
    graph_path = normalize_runtime_path(graph_row["graph_path"]).resolve(strict=True)
    if sha256_file(graph_path) != graph_row["graph_sha256"]:
        raise ValueError("Gate 2 input graph hash mismatch")
    with np.load(graph_path, allow_pickle=False) as graph:
        graph_x = graph["x"].astype(np.float32)
        edge_index = graph["edge_index"].astype(np.int64)
    mean = graph_x.mean(axis=0)
    std = graph_x.std(axis=0)
    std[std < 1.0e-6] = 1.0
    graph_x = ((graph_x - mean) / std).astype(np.float32)

    limits = _slot_limits(outputs)
    counts = (
        len(ordered_roads),
        len(ordered_nodes),
        len(ordered_t05_nodes),
        len(ordered_pointers),
    )
    count_targets = np.asarray(
        [
            math.log1p(value) / math.log1p(limit)
            for value, limit in zip(
                counts,
                (limits.road_slots, limits.node_slots, limits.t05_node_slots, limits.pointer_queries),
                strict=True,
            )
        ],
        dtype=np.float32,
    )
    batch_np = {
        "x": graph_x,
        "edge_index": edge_index,
        **road_targets,
        "node_xy": node_xy,
        "t05_node_xy": t05_node_xy,
        "pointer": pointer_target,
        "road_action": _action_targets(road_edits, ROAD_ACTIONS),
        "node_action": _action_targets(node_edits, NODE_ACTIONS),
        "t05_action": _action_targets(t05_edits, NODE_ACTIONS),
        "counts": count_targets,
    }
    batch_path = target_root / "p05_r2_gate2_batch.npz"
    np.savez_compressed(batch_path, **batch_np)
    scene_np = _scene_data(dataset_root, dataset_manifest)

    random.seed(config.seed)
    np.random.seed(config.seed)
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    torch.manual_seed(config.seed)
    torch.cuda.manual_seed_all(config.seed)
    torch.use_deterministic_algorithms(True)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if device.type == "cuda":
        torch.cuda.reset_peak_memory_stats(device)
    model = R2GraphGenerator(
        road_input_dim=graph_x.shape[1],
        limits=limits,
        hidden_dim=config.hidden_dim,
        graph_layers=config.graph_layers,
        query_layers=config.query_layers,
        polyline_points=config.polyline_points,
        dropout=0.0,
        include_scene=True,
    ).to(device)
    model_parameter_count = parameter_count(model)
    if not 20_000_000 <= model_parameter_count <= 50_000_000:
        raise ValueError(f"R2 model parameter count is outside target: {model_parameter_count}")
    initial_checkpoint_path: Path | None = None
    initial_checkpoint_sha256 = ""
    reinitialized_checkpoint_heads: list[str] = []
    if config.initial_checkpoint_path is not None:
        initial_checkpoint_path = normalize_runtime_path(config.initial_checkpoint_path).resolve(strict=True)
        checkpoint = torch.load(initial_checkpoint_path, map_location=device, weights_only=False)
        if checkpoint.get("sample_id") != sample_id or dict(checkpoint.get("limits") or {}) != asdict(limits):
            raise ValueError("R2 initial checkpoint sample/slot limits do not match Gate 2 run")
        checkpoint_state = dict(checkpoint["model_state"])
        current_state = model.state_dict()
        for name in ("road_geometry_head.weight", "road_geometry_head.bias"):
            if name in checkpoint_state and checkpoint_state[name].shape != current_state[name].shape:
                checkpoint_state.pop(name)
                reinitialized_checkpoint_heads.append(name)
        incompatible = model.load_state_dict(checkpoint_state, strict=False)
        if set(incompatible.missing_keys) != set(reinitialized_checkpoint_heads) or incompatible.unexpected_keys:
            raise ValueError(
                f"R2 initial checkpoint incompatibility exceeds geometry head: {incompatible}"
            )
        initial_checkpoint_sha256 = sha256_file(initial_checkpoint_path)
    graph_batch = _torch_graph_batch(batch_np, device, torch)
    graph_x_tensor = torch.as_tensor(graph_x, dtype=torch.float32, device=device)
    edge_tensor = torch.as_tensor(edge_index, dtype=torch.long, device=device)
    scene_batch = _torch_scene_batch(scene_np, device, torch)
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
    )
    curves: list[dict[str, Any]] = []
    consecutive_pass = 0
    final_graph_metrics: dict[str, Any] = {}
    final_scene_metrics: dict[str, float] = {}
    completed_epoch = 0

    for epoch in range(1, config.max_epochs + 1):
        model.train()
        optimizer.zero_grad(set_to_none=True)
        graph_prediction = model.forward_graph(
            graph_x_tensor,
            edge_tensor,
            road_count=counts[0],
            node_count=counts[1],
            t05_node_count=counts[2],
            pointer_count=counts[3],
            road_action_count=len(road_edits),
            node_action_count=len(node_edits),
            t05_action_count=len(t05_edits),
        )
        graph_loss, graph_parts = r2_graph_loss(graph_prediction, graph_batch)
        scene_prediction = model.forward_scene(scene_batch["scene"])
        scene_loss, scene_parts = m2r_scene_loss(scene_prediction, scene_batch)
        total_loss = graph_loss + scene_loss
        total_loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 10.0)
        optimizer.step()
        completed_epoch = epoch

        if epoch == 1 or epoch % 10 == 0:
            model.eval()
            with torch.no_grad():
                final_graph_metrics = _graph_metrics(graph_prediction, graph_batch, frame, limits)
                final_scene_metrics = _scene_metrics(scene_prediction, scene_batch)
            row = {
                "epoch": epoch,
                "total_loss": float(total_loss.detach().item()),
                **{f"graph_{name}_loss": float(value.item()) for name, value in graph_parts.items()},
                **{f"scene_{name}_loss": float(value.item()) for name, value in scene_parts.items()},
                "road_action_macro_f1": final_graph_metrics["road_action"]["macro_f1"],
                "node_action_macro_f1": final_graph_metrics["node_action"]["macro_f1"],
                "t05_action_macro_f1": final_graph_metrics["t05_action"]["macro_f1"],
                "endpoint_accuracy": final_graph_metrics["endpoint_accuracy"],
                "pointer_accuracy": final_graph_metrics["pointer_accuracy"],
                "node_max_error_m": final_graph_metrics["node_max_error_m"],
                "road_point_max_error_m": final_graph_metrics["road_point_max_error_m"],
                **final_scene_metrics,
            }
            curves.append(row)
            gate_metrics_pass = (
                min(
                    final_graph_metrics["road_action"]["macro_f1"],
                    final_graph_metrics["node_action"]["macro_f1"],
                    final_graph_metrics["t05_action"]["macro_f1"],
                    final_graph_metrics["road_direction_accuracy"],
                    final_graph_metrics["road_source_accuracy"],
                    final_graph_metrics["endpoint_accuracy"],
                    final_graph_metrics["pointer_accuracy"],
                    final_scene_metrics["accepted_accuracy"],
                    final_scene_metrics["t03_relation_accuracy"],
                    final_scene_metrics["t04_relation_accuracy"],
                )
                >= 0.95
                and final_scene_metrics["surface_dice"] >= 0.95
                and final_graph_metrics["node_max_error_m"] <= 0.5
                and final_graph_metrics["road_point_max_error_m"] <= 1.0
                and final_graph_metrics["predicted_counts"] == list(counts)
            )
            consecutive_pass = consecutive_pass + 1 if gate_metrics_pass else 0
            if consecutive_pass >= 2:
                break

    model.eval()
    with torch.no_grad():
        final_prediction = model.forward_graph(
            graph_x_tensor,
            edge_tensor,
            road_count=counts[0],
            node_count=counts[1],
            t05_node_count=counts[2],
            pointer_count=counts[3],
            road_action_count=len(road_edits),
            node_action_count=len(node_edits),
            t05_action_count=len(t05_edits),
        )
        final_scene_prediction = model.forward_scene(scene_batch["scene"])
        final_graph_metrics = _graph_metrics(final_prediction, graph_batch, frame, limits)
        final_scene_metrics = _scene_metrics(final_scene_prediction, scene_batch)

    candidate_road_path = target_root / "p05_r2_gate2_road.gpkg"
    candidate_node_path = target_root / "p05_r2_gate2_node.gpkg"
    _materialize_prediction(
        final_prediction, frame, road_meta, node_meta, candidate_road_path, candidate_node_path
    )
    evaluation = evaluate_frcsd(
        candidate_road_path,
        candidate_node_path,
        Path(case_row["truth_road_path"]),
        Path(case_row["truth_node_path"]),
    )
    predicted_endpoint = final_prediction["road_endpoint"].argmax(-1).detach().cpu().numpy()
    predicted_direction = final_prediction["road_direction"].argmax(-1).detach().cpu().numpy()
    normalized_topology = slot_topology_metrics(
        predicted_endpoint,
        predicted_direction,
        batch_np["road_endpoint"],
        batch_np["road_direction"],
    )
    structural_hard_failures = [
        failure for failure in evaluation["hard_failures"] if failure != "directed topology differs from truth"
    ]
    gate2_pass = (
        final_graph_metrics["road_action"]["macro_f1"] >= 0.95
        and final_graph_metrics["node_action"]["macro_f1"] >= 0.95
        and final_graph_metrics["t05_action"]["macro_f1"] >= 0.95
        and final_graph_metrics["pointer_accuracy"] >= 0.95
        and final_scene_metrics["surface_dice"] >= 0.95
        and final_scene_metrics["t03_relation_accuracy"] >= 0.95
        and final_scene_metrics["t04_relation_accuracy"] >= 0.95
        and float(evaluation["road_object"]["f1"]) >= 0.98
        and float(evaluation["node_object"]["f1"]) >= 0.98
        and float(normalized_topology["f1"]) == 1.0
        and not structural_hard_failures
    )

    checkpoint_path = target_root / "p05_r2_gate2_checkpoint.pt"
    torch.save(
        {
            "model_state": model.state_dict(),
            "config": asdict(config),
            "limits": asdict(limits),
            "input_mean": mean,
            "input_std": std,
            "frame": asdict(frame),
            "sample_id": sample_id,
            "counts": counts,
            "parameter_count": model_parameter_count,
        },
        checkpoint_path,
    )
    curves_path = target_root / "p05_r2_gate2_curves.csv"
    write_csv(curves_path, curves, list(curves[0]))
    summary = {
        "schema_version": "p05-r2-gate2-summary-v1",
        "sample_id": sample_id,
        "gate2_pass": gate2_pass,
        "epochs": completed_epoch,
        "parameter_count": model_parameter_count,
        "slot_limits": asdict(limits),
        "counts": {
            "road": counts[0],
            "node": counts[1],
            "t05_node": counts[2],
            "pointer": counts[3],
            "road_action": len(road_edits),
            "node_action": len(node_edits),
            "t05_action": len(t05_edits),
        },
        "graph_metrics": final_graph_metrics,
        "scene_metrics": final_scene_metrics,
        "evaluation": evaluation,
        "normalized_directed_topology": normalized_topology,
        "structural_hard_failures": structural_hard_failures,
        "silent_fix": False,
        "content_repair": False,
        "duration_seconds": time.perf_counter() - started,
        "peak_cuda_memory_bytes": int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0,
    }
    summary_path = target_root / "p05_r2_gate2_summary.json"
    write_json(summary_path, summary)
    report_path = target_root / "p05_r2_gate2_report.md"
    report_path.write_text(
        "# P05-R2 Gate 2\n\n"
        f"- sample: `{sample_id}`\n"
        f"- parameters: `{model_parameter_count}`\n"
        f"- epochs: `{completed_epoch}`\n"
        f"- Road/Node F1: `{evaluation['road_object']['f1']:.6f}` / `{evaluation['node_object']['f1']:.6f}`\n"
        f"- directed topology F1 (slot-normalized): `{normalized_topology['f1']:.6f}`\n"
        f"- legacy greedy-node topology F1: `{evaluation['directed_topology']['f1']:.6f}`\n"
        f"- Gate 2: `{'PASS' if gate2_pass else 'FAIL'}`\n\n"
        "本门禁仅证明全动作 small-batch 可学习，不代表 held-out 泛化。\n",
        encoding="utf-8",
    )
    audit_path = target_root / "p05_r2_gate2_input_target_audit.json"
    write_json(
        audit_path,
        {
            "input_only": {
                "graph_path": str(graph_path),
                "graph_sha256": sha256_file(graph_path),
                "roles": {name: str(path) for name, path in sorted(roles.items()) if name in {"t01_roads", "raw_rcsdroad", "raw_prepared_swsd_nodes", "raw_rcsdnode"}},
            },
            "label_only": {
                "oracle_manifest_path": str(root / "p05_r2_oracle_manifest.json"),
                "truth_road_path": case_row["truth_road_path"],
                "truth_node_path": case_row["truth_node_path"],
                "t05_node_truth_path": case_row["t05_node_truth_path"],
                "oracle_payload_entered_input": False,
            },
            "initial_checkpoint": {
                "path": str(initial_checkpoint_path) if initial_checkpoint_path else "",
                "sha256": initial_checkpoint_sha256,
                "reinitialized_heads": reinitialized_checkpoint_heads,
            },
            "coordinate_frame": asdict(frame),
        },
    )
    output_paths = {
        "batch": batch_path,
        "checkpoint": checkpoint_path,
        "curves": curves_path,
        "candidate_road": candidate_road_path,
        "candidate_node": candidate_node_path,
        "summary": summary_path,
        "report": report_path,
        "input_target_audit": audit_path,
    }
    manifest = {
        "schema_version": "p05-r2-gate2-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "gate2_passed" if gate2_pass else "gate2_failed",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "oracle_manifest_path": str(root / "p05_r2_oracle_manifest.json"),
        "oracle_manifest_sha256": sha256_file(root / "p05_r2_oracle_manifest.json"),
        "initial_checkpoint_path": str(initial_checkpoint_path) if initial_checkpoint_path else "",
        "initial_checkpoint_sha256": initial_checkpoint_sha256,
        "reinitialized_checkpoint_heads": reinitialized_checkpoint_heads,
        "parameters": {
            name: str(value) if isinstance(value, Path) else value
            for name, value in asdict(config).items()
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
            "torch": torch.__version__,
            "cuda": torch.version.cuda,
            "device": torch.cuda.get_device_name(device) if device.type == "cuda" else "cpu",
        },
        "outputs": {name: output_record(path) for name, path in output_paths.items()},
        "silent_fix": False,
        "content_repair": False,
    }
    manifest_path = target_root / "p05_r2_gate2_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = [
    "CoordinateFrame",
    "classification_metrics",
    "resample_geometry",
    "slot_topology_metrics",
    "train_r2_gate2",
]
