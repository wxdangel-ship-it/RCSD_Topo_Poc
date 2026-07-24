from __future__ import annotations

import csv
import ctypes
import hashlib
import json
import math
import os
import platform
import random
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fiona
import numpy as np
from pyproj import CRS
from shapely.geometry import LineString, MultiLineString, Point, mapping, shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p05_neural_road_generation.evaluation import evaluate_frcsd
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_dataset import OPERATION_NAMES
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_models import M1EvaluationConfig
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_csv, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _path_from_record(record: dict[str, Any]) -> Path:
    path = normalize_runtime_path(str(record.get("path") or ""))
    if not path.is_file():
        raise FileNotFoundError(path)
    expected = str(record.get("sha256") or "")
    if expected and sha256_file(path) != expected:
        raise ValueError(f"output hash mismatch: {path}")
    return path


def _verify_dataset(root: Path) -> tuple[dict[str, Any], dict[str, Path], list[dict[str, Any]]]:
    manifest_path = root / "p05_m1_dataset_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "p05-m1-dataset-manifest-v1" or manifest.get("silent_fix") is not False:
        raise ValueError("invalid M1 dataset manifest")
    paths = {role: _path_from_record(manifest["outputs"][role]) for role in ("candidates", "input_artifacts", "graph_index")}
    graphs = json.loads(paths["graph_index"].read_text(encoding="utf-8"))["graphs"]
    for item in graphs:
        graph_path = normalize_runtime_path(item["graph_path"])
        if not graph_path.is_file() or sha256_file(graph_path) != item["graph_sha256"]:
            raise ValueError(f"graph hash mismatch: {item['sample_id']}")
        item["graph_path"] = str(graph_path)
    return manifest, paths, graphs


def _verify_model(root: Path, dataset_manifest_path: Path) -> tuple[dict[str, Any], Path]:
    manifest_path = root / "p05_m1_training_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "p05-m1-training-manifest-v1":
        raise ValueError("invalid M1 training manifest")
    if manifest.get("silent_fix") is not False or manifest.get("test_accessed") is not False:
        raise ValueError("training manifest violates no-test/no-silent-fix contract")
    if manifest.get("dataset_manifest_sha256") != sha256_file(dataset_manifest_path):
        raise ValueError("model and evaluation dataset manifests differ")
    return manifest, _path_from_record(manifest["outputs"]["checkpoint"])


def _id_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _property(properties: dict[str, Any], name: str) -> Any:
    wanted = name.casefold()
    for key, value in properties.items():
        if str(key).casefold() == wanted:
            return value
    return None


def _integer(value: Any, default: int = -1) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _read_features(path: Path) -> tuple[dict[str, tuple[dict[str, Any], BaseGeometry]], CRS]:
    layers = fiona.listlayers(path)
    if not layers:
        raise ValueError(f"vector has no layer: {path}")
    result: dict[str, tuple[dict[str, Any], BaseGeometry]] = {}
    with fiona.open(path, layer=layers[0]) as source:
        raw_crs = source.crs_wkt or source.crs
        if not raw_crs:
            raise ValueError(f"vector CRS is missing: {path}")
        crs = CRS.from_user_input(raw_crs)
        for feature in source:
            properties = dict(feature.properties)
            feature_id = _id_text(_property(properties, "id"))
            if feature_id and feature.geometry is not None:
                result.setdefault(feature_id, (properties, shape(feature.geometry)))
    return result, crs


def _artifacts_by_sample(path: Path) -> dict[str, dict[str, Path]]:
    result: dict[str, dict[str, Path]] = defaultdict(dict)
    for row in _read_csv(path):
        artifact = normalize_runtime_path(row["path"])
        if not artifact.is_file() or sha256_file(artifact) != row["sha256"]:
            raise ValueError(f"input artifact hash mismatch: {row['sample_id']}: {row['role']}")
        result[row["sample_id"]][row["role"]] = artifact
    return result


def _generated_id(prefix: str, *parts: Any) -> str:
    digest = hashlib.sha256("\x1f".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _decode_child(parent: BaseGeometry, normalized: np.ndarray) -> LineString:
    if normalized.ndim != 2 or normalized.shape[1] != 2 or not np.isfinite(normalized).all():
        raise ValueError("predicted child geometry is not finite Nx2")
    points = [parent.interpolate(float(fraction), normalized=True) for fraction in np.linspace(0.0, 1.0, len(normalized))]
    center = np.asarray([(point.x, point.y) for point in points], dtype=np.float64).mean(axis=0)
    coordinates = normalized.astype(np.float64) * max(float(parent.length), 1.0e-6) + center
    geometry = LineString(coordinates)
    if geometry.is_empty or not geometry.is_valid or not math.isfinite(geometry.length) or geometry.length <= 1.0e-6:
        raise ValueError("predicted child geometry is empty, invalid, or zero-length")
    return geometry


def _as_multiline(geometry: BaseGeometry) -> MultiLineString:
    if geometry.geom_type == "LineString":
        return MultiLineString([geometry])
    if geometry.geom_type == "MultiLineString":
        return geometry  # type: ignore[return-value]
    raise ValueError(f"Road geometry type is not lineal: {geometry.geom_type}")


def _line_endpoints(geometry: BaseGeometry) -> tuple[tuple[float, float], tuple[float, float]]:
    if geometry.geom_type == "LineString":
        coordinates = list(geometry.coords)
        return tuple(coordinates[0][:2]), tuple(coordinates[-1][:2])
    if geometry.geom_type == "MultiLineString":
        parts = list(geometry.geoms)
        if not parts:
            raise ValueError("retained MultiLineString has no parts")
        return tuple(parts[0].coords[0][:2]), tuple(parts[-1].coords[-1][:2])
    raise ValueError(f"retained Road geometry type is not lineal: {geometry.geom_type}")


def _write_vectors(
    road_path: Path,
    node_path: Path,
    crs: CRS,
    roads: list[dict[str, Any]],
    nodes: dict[str, dict[str, Any]],
) -> None:
    road_schema = {
        "geometry": "MultiLineString",
        "properties": {
            "id": "str",
            "snodeid": "str",
            "enodeid": "str",
            "direction": "int",
            "source": "int",
            "parent_id": "str",
            "operation": "str",
            "confidence": "float",
        },
    }
    node_schema = {"geometry": "Point", "properties": {"id": "str", "source": "int", "origin": "str"}}
    with fiona.open(road_path, "w", driver="GPKG", layer="Road", schema=road_schema, crs_wkt=crs.to_wkt()) as sink:
        for road in roads:
            sink.write({"geometry": mapping(_as_multiline(road.pop("geometry"))), "properties": road})
    with fiona.open(node_path, "w", driver="GPKG", layer="Node", schema=node_schema, crs_wkt=crs.to_wkt()) as sink:
        for node_id in sorted(nodes):
            node = nodes[node_id]
            sink.write(
                {
                    "geometry": mapping(node["geometry"]),
                    "properties": {"id": node_id, "source": node["source"], "origin": node["origin"]},
                }
            )


def _add_input_node(
    nodes: dict[str, dict[str, Any]],
    node_id: str,
    lookup: dict[str, tuple[dict[str, Any], BaseGeometry]],
    failures: list[str],
    *,
    fallback_point: tuple[float, float],
    fallback_source: int,
) -> None:
    if not node_id:
        failures.append("retained Road has an empty endpoint id")
        return
    raw = lookup.get(node_id)
    if raw is None:
        if not all(math.isfinite(value) for value in fallback_point):
            failures.append(f"cannot derive missing input Node {node_id} from a finite Road endpoint")
            return
        candidate = {
            "geometry": Point(fallback_point),
            "source": fallback_source,
            "origin": "retained_geometry_endpoint",
        }
    else:
        properties, geometry = raw
        if geometry.geom_type != "Point":
            failures.append(f"input Node {node_id} is {geometry.geom_type}, not Point")
            return
        candidate = {"geometry": geometry, "source": _integer(_property(properties, "source")), "origin": "input"}
    previous = nodes.get(node_id)
    if previous is not None and not previous["geometry"].equals_exact(candidate["geometry"], 0.0):
        failures.append(f"input Node {node_id} has conflicting geometries across retained Roads")
        return
    nodes.setdefault(node_id, candidate)


def _model_predictions(
    checkpoint_path: Path,
    graph_path: Path,
    *,
    use_raw: bool,
) -> tuple[dict[str, np.ndarray], dict[str, Any], str, int]:
    try:
        import torch
    except ImportError as exc:
        raise RuntimeError("PyTorch optional dependency is required for P05 M1 inference") from exc
    from rcsd_topo_poc.modules.p05_neural_road_generation.m1_network import build_model

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    config = checkpoint["model_config"]
    model = build_model(
        config["model_type"],
        int(config["input_dim"]),
        hidden_dim=int(config["hidden_dim"]),
        layers=int(config["layers"]),
        dropout=float(config["dropout"]),
        polyline_points=int(config["polyline_points"]),
    ).to(device)
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    with np.load(graph_path, allow_pickle=False) as data:
        if use_raw:
            normalization = checkpoint.get("normalization") or {}
            if normalization.get("mean") is None or normalization.get("std") is None:
                raise ValueError("final-development checkpoint lacks train-only normalization")
            mean = np.asarray(normalization["mean"], dtype=np.float32)
            std = np.asarray(normalization["std"], dtype=np.float32)
            x = ((data["raw_x"] - mean) / std).astype(np.float32)
            edge = data["raw_edge_index"]
        else:
            x = data["x"]
            edge = data["edge_index"]
    with torch.no_grad():
        output = model(
            torch.as_tensor(x, dtype=torch.float32, device=device),
            torch.as_tensor(edge, dtype=torch.long, device=device),
        )
        operation_probability = torch.softmax(output["operation"], dim=1)
        result = {
            "operation": operation_probability.argmax(dim=1).cpu().numpy(),
            "confidence": operation_probability.max(dim=1).values.cpu().numpy(),
            "direction": output["direction"].argmax(dim=1).cpu().numpy(),
            "source": output["source"].argmax(dim=1).cpu().numpy(),
            "split_fraction": output["split_fraction"].cpu().numpy(),
            "child_geometry": output["child_geometry"].cpu().numpy(),
        }
    peak_vram = int(torch.cuda.max_memory_allocated(device)) if device.type == "cuda" else 0
    return result, checkpoint, str(device), peak_vram


def _materialize_case(
    *,
    item: dict[str, Any],
    candidate_rows: list[dict[str, str]],
    artifacts: dict[str, Path],
    prediction_mode: str,
    checkpoint_path: Path | None,
    use_raw: bool,
    case_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]], int]:
    roads_by_role: dict[str, dict[str, tuple[dict[str, Any], BaseGeometry]]] = {}
    crs_values: list[CRS] = []
    for role in ("t01_roads", "t05_rcsdroad_out"):
        roads_by_role[role], crs = _read_features(artifacts[role])
        crs_values.append(crs)
    nodes_by_role: dict[str, dict[str, tuple[dict[str, Any], BaseGeometry]]] = {}
    for role in ("t04_nodes", "t05_rcsdnode_out"):
        nodes_by_role[role], crs = _read_features(artifacts[role])
        crs_values.append(crs)
    truth_road_crs = _read_features(artifacts["t06_frcsd_road"])[1]
    truth_node_crs = _read_features(artifacts["t06_frcsd_node"])[1]
    crs_values.extend((truth_road_crs, truth_node_crs))
    if not all(crs.equals(crs_values[0]) for crs in crs_values[1:]):
        raise ValueError(f"{item['sample_id']}: input/truth CRS mismatch")
    rows = sorted(
        candidate_rows,
        key=lambda row: int(row["row_index_raw"] if use_raw else row["row_index"]),
    )
    if prediction_mode == "model":
        assert checkpoint_path is not None
        prediction, _, _, peak_vram = _model_predictions(
            checkpoint_path, Path(item["graph_path"]), use_raw=use_raw
        )
        if len(prediction["operation"]) != len(rows):
            raise ValueError(f"{item['sample_id']}: graph/candidate row count differs")
    else:
        prediction = {
            "operation": np.ones(len(rows), dtype=np.int64),
            "confidence": np.ones(len(rows), dtype=np.float32),
            "direction": np.full(len(rows), -1, dtype=np.int64),
            "source": np.full(len(rows), -1, dtype=np.int64),
            "split_fraction": np.zeros((len(rows), 2), dtype=np.float32),
            "child_geometry": np.zeros((len(rows), 3, 16, 2), dtype=np.float32),
        }
        peak_vram = 0
    output_roads: list[dict[str, Any]] = []
    output_nodes: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    prediction_rows: list[dict[str, Any]] = []
    operation_counts: Counter[str] = Counter()
    for index, row in enumerate(rows):
        road_id = row["road_id"]
        source_role = row["source_role"]
        raw = roads_by_role[source_role].get(road_id)
        if raw is None:
            failures.append(f"candidate Road {road_id} missing from {source_role}")
            continue
        properties, parent_geometry = raw
        operation = OPERATION_NAMES[int(prediction["operation"][index])]
        confidence = float(prediction["confidence"][index])
        direction = (
            int(prediction["direction"][index])
            if prediction_mode == "model"
            else _integer(_property(properties, "direction"))
        )
        source = (
            int(prediction["source"][index])
            if prediction_mode == "model"
            else _integer(_property(properties, "source"))
        )
        operation_counts[operation] += 1
        prediction_rows.append(
            {
                "sample_id": item["sample_id"],
                "prediction_mode": prediction_mode,
                "road_id": road_id,
                "source_role": source_role,
                "operation": operation,
                "confidence": confidence,
                "direction": direction,
                "source": source,
                "split_fraction": prediction["split_fraction"][index].tolist(),
            }
        )
        if operation == "DROP":
            continue
        if operation == "KEEP":
            start_id = _id_text(_property(properties, "snodeid"))
            end_id = _id_text(_property(properties, "enodeid"))
            if not start_id or not end_id:
                failures.append(f"retained Road {road_id} has empty endpoint id")
            node_role = "t04_nodes" if source_role == "t01_roads" else "t05_rcsdnode_out"
            try:
                endpoint_points = _line_endpoints(parent_geometry)
            except ValueError as exc:
                failures.append(f"retained Road {road_id}: {exc}")
                endpoint_points = ((math.nan, math.nan), (math.nan, math.nan))
            _add_input_node(
                output_nodes,
                start_id,
                nodes_by_role[node_role],
                failures,
                fallback_point=endpoint_points[0],
                fallback_source=source,
            )
            _add_input_node(
                output_nodes,
                end_id,
                nodes_by_role[node_role],
                failures,
                fallback_point=endpoint_points[1],
                fallback_source=source,
            )
            output_roads.append(
                {
                    "id": road_id,
                    "snodeid": start_id,
                    "enodeid": end_id,
                    "direction": direction,
                    "source": source,
                    "parent_id": road_id,
                    "operation": operation,
                    "confidence": confidence,
                    "geometry": parent_geometry,
                }
            )
            continue
        child_count = int(operation.rsplit("_", 1)[1])
        for child_index in range(child_count):
            try:
                child_geometry = _decode_child(parent_geometry, prediction["child_geometry"][index, child_index])
            except ValueError as exc:
                failures.append(f"Road {road_id} child {child_index}: {exc}")
                continue
            child_id = _generated_id("p05r", item["sample_id"], road_id, child_index)
            endpoints = (child_geometry.coords[0], child_geometry.coords[-1])
            node_ids = [
                _generated_id("p05n", item["sample_id"], f"{point[0]:.12f}", f"{point[1]:.12f}")
                for point in endpoints
            ]
            for node_id, point in zip(node_ids, endpoints):
                candidate = {"geometry": Point(point), "source": source, "origin": "model"}
                previous = output_nodes.get(node_id)
                if previous is not None and not previous["geometry"].equals_exact(candidate["geometry"], 0.0):
                    failures.append(f"generated Node id collision: {node_id}")
                else:
                    output_nodes.setdefault(node_id, candidate)
            output_roads.append(
                {
                    "id": child_id,
                    "snodeid": node_ids[0],
                    "enodeid": node_ids[1],
                    "direction": direction,
                    "source": source,
                    "parent_id": road_id,
                    "operation": operation,
                    "confidence": confidence,
                    "geometry": child_geometry,
                }
            )
    case_root.mkdir(parents=True, exist_ok=False)
    road_path = case_root / "predicted_road.gpkg"
    node_path = case_root / "predicted_node.gpkg"
    _write_vectors(road_path, node_path, crs_values[0], output_roads, output_nodes)
    evaluation = evaluate_frcsd(
        road_path,
        node_path,
        artifacts["t06_frcsd_road"],
        artifacts["t06_frcsd_node"],
    )
    evaluation["sample_id"] = item["sample_id"]
    evaluation["business_id"] = item["business_id"]
    evaluation["materialization"] = {
        "prediction_mode": prediction_mode,
        "silent_fix": False,
        "operation_counts": dict(sorted(operation_counts.items())),
        "node_origin_counts": dict(sorted(Counter(node["origin"] for node in output_nodes.values()).items())),
        "failures": failures,
        "road_sha256": sha256_file(road_path),
        "node_sha256": sha256_file(node_path),
    }
    metrics_path = case_root / "metrics.json"
    write_json(metrics_path, evaluation)
    return evaluation, prediction_rows, peak_vram


def _f1(matched: int, candidate: int, truth: int) -> float:
    precision = matched / candidate if candidate else (1.0 if truth == 0 else 0.0)
    recall = matched / truth if truth else (1.0 if candidate == 0 else 0.0)
    return 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0


def _bootstrap_interval(cases: list[dict[str, Any]], seed: int) -> list[float]:
    if not cases:
        return [0.0, 0.0]
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(2000):
        selected = [cases[rng.randrange(len(cases))] for _ in cases]
        counts = [case["counts"] for case in selected]
        values.append(
            _f1(
                sum(item["matched_roads"] for item in counts),
                sum(item["candidate_roads"] for item in counts),
                sum(item["truth_roads"] for item in counts),
            )
        )
    return [float(np.quantile(values, 0.025)), float(np.quantile(values, 0.975))]


def _aggregate(cases: list[dict[str, Any]], seed: int) -> dict[str, Any]:
    counts = [case["counts"] for case in cases]
    matched = sum(item["matched_roads"] for item in counts)
    candidate = sum(item["candidate_roads"] for item in counts)
    truth = sum(item["truth_roads"] for item in counts)
    per_case = [case["road_object"]["f1"] for case in cases]
    attribute_result: dict[str, float | None] = {}
    for name in ("direction_accuracy", "source_accuracy", "endpoint_semantic_accuracy"):
        numerator = sum(
            case["attributes"][name] * case["counts"]["matched_roads"]
            for case in cases
            if case["attributes"][name] is not None
        )
        denominator = sum(
            case["counts"]["matched_roads"]
            for case in cases
            if case["attributes"][name] is not None
        )
        attribute_result[name] = numerator / denominator if denominator else None
    return {
        "case_count": len(cases),
        "road_object_f1": _f1(matched, candidate, truth),
        "road_object_f1_case_mean": float(np.mean(per_case)) if per_case else None,
        "road_object_f1_case_min": min(per_case) if per_case else None,
        "road_object_f1_bootstrap_95": _bootstrap_interval(cases, seed),
        "counts": {"matched_roads": matched, "candidate_roads": candidate, "truth_roads": truth},
        "attributes": attribute_result,
        "hard_failure_case_count": sum(bool(case["hard_failures"]) for case in cases),
        "materialization_failure_count": sum(len(case["materialization"]["failures"]) for case in cases),
        "worst_cases": [
            {"sample_id": case["sample_id"], "road_f1": case["road_object"]["f1"]}
            for case in sorted(cases, key=lambda item: (item["road_object"]["f1"], item["sample_id"]))[:5]
        ],
    }


def _peak_rss_bytes() -> int | None:
    if os.name == "nt":
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
        handle = kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return int(counters.PeakWorkingSetSize)
        return None
    try:
        import resource

        value = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return int(value if platform.system() == "Darwin" else value * 1024)
    except (ImportError, OSError):
        return None


def evaluate_m1_model(config: M1EvaluationConfig) -> dict[str, Any]:
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    dataset_root = normalize_runtime_path(config.dataset_run_root).resolve(strict=True)
    dataset_manifest, paths, graphs = _verify_dataset(dataset_root)
    candidates = _read_csv(paths["candidates"])
    artifacts = _artifacts_by_sample(paths["input_artifacts"])
    selected = [item for item in graphs if item["split"] == config.split]
    if not selected:
        raise ValueError(f"dataset has no {config.split} samples")
    checkpoint_path: Path | None = None
    model_manifest: dict[str, Any] | None = None
    use_raw = False
    if config.prediction_mode == "model":
        assert config.model_run_root is not None
        model_root = normalize_runtime_path(config.model_run_root).resolve(strict=True)
        model_manifest, checkpoint_path = _verify_model(model_root, dataset_root / "p05_m1_dataset_manifest.json")
        view_kind = model_manifest["dataset_view"]["kind"]
        if config.split == "test" and view_kind != "final_development_train":
            raise ValueError("fixed test requires a final-development checkpoint")
        use_raw = view_kind == "final_development_train"
    if config.split == "test" and not config.allow_fixed_test:
        raise ValueError("fixed test access was not explicitly allowed")
    target_root = normalize_runtime_path(config.output_root).resolve(strict=False) / config.run_id
    target_root.mkdir(parents=True, exist_ok=False)
    cases: list[dict[str, Any]] = []
    baseline_cases: list[dict[str, Any]] = []
    prediction_rows: list[dict[str, Any]] = []
    peak_vram = 0
    by_sample_candidates: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in candidates:
        include = True if use_raw else int(row["row_index"]) >= 0
        if include:
            by_sample_candidates[row["sample_id"]].append(row)
    for item in selected:
        case_name = hashlib.sha256(item["sample_id"].encode("utf-8")).hexdigest()[:20]
        evaluation, rows, case_vram = _materialize_case(
            item=item,
            candidate_rows=by_sample_candidates[item["sample_id"]],
            artifacts=artifacts[item["sample_id"]],
            prediction_mode=config.prediction_mode,
            checkpoint_path=checkpoint_path,
            use_raw=use_raw,
            case_root=target_root / "cases" / config.prediction_mode / case_name,
        )
        cases.append(evaluation)
        prediction_rows.extend(rows)
        peak_vram = max(peak_vram, case_vram)
    if config.include_keep_all_baseline:
        for item in selected:
            case_name = hashlib.sha256(item["sample_id"].encode("utf-8")).hexdigest()[:20]
            evaluation, rows, _ = _materialize_case(
                item=item,
                candidate_rows=by_sample_candidates[item["sample_id"]],
                artifacts=artifacts[item["sample_id"]],
                prediction_mode="keep_all",
                checkpoint_path=None,
                use_raw=use_raw,
                case_root=target_root / "cases" / "keep_all" / case_name,
            )
            baseline_cases.append(evaluation)
            prediction_rows.extend(rows)
    aggregate = _aggregate(cases, config.seed)
    baseline_aggregate = _aggregate(baseline_cases, config.seed) if baseline_cases else None
    case_metrics_path = target_root / "p05_m1_case_metrics.json"
    prediction_path = target_root / "p05_m1_predictions.csv"
    summary_path = target_root / "p05_m1_evaluation_summary.json"
    write_json(
        case_metrics_path,
        {
            "schema_version": "p05-m1-case-metrics-v1",
            "cases": cases,
            "keep_all_baseline_cases": baseline_cases,
        },
    )
    write_csv(
        prediction_path,
        prediction_rows,
        [
            "sample_id",
            "prediction_mode",
            "road_id",
            "source_role",
            "operation",
            "confidence",
            "direction",
            "source",
            "split_fraction",
        ],
    )
    summary = {
        "schema_version": "p05-m1-evaluation-summary-v1",
        "run_id": config.run_id,
        "split": config.split,
        "prediction_mode": config.prediction_mode,
        "test_accessed": config.split == "test",
        "silent_fix": False,
        "aggregate": aggregate,
        "keep_all_baseline": baseline_aggregate,
        "road_object_f1_delta_vs_keep_all": (
            aggregate["road_object_f1"] - baseline_aggregate["road_object_f1"]
            if baseline_aggregate is not None
            else None
        ),
        "duration_seconds": time.perf_counter() - started,
        "peak_process_rss_bytes": _peak_rss_bytes(),
        "peak_cuda_memory_bytes": peak_vram,
    }
    write_json(summary_path, summary)
    manifest = {
        "schema_version": "p05-m1-evaluation-manifest-v1",
        "run_id": config.run_id,
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset_run_id": dataset_manifest["run_id"],
        "dataset_manifest_sha256": sha256_file(dataset_root / "p05_m1_dataset_manifest.json"),
        "model_manifest_sha256": (
            sha256_file(normalize_runtime_path(config.model_run_root) / "p05_m1_training_manifest.json")
            if config.model_run_root is not None
            else None
        ),
        "split": config.split,
        "prediction_mode": config.prediction_mode,
        "include_keep_all_baseline": config.include_keep_all_baseline,
        "inference_protocol": "operation_argmax_v1",
        "seed": config.seed,
        "python": os.sys.version,
        "platform": platform.platform(),
        "silent_fix": False,
        "test_accessed": config.split == "test",
        "outputs": {
            "case_metrics": output_record(case_metrics_path),
            "predictions": output_record(prediction_path),
            "summary": output_record(summary_path),
        },
    }
    manifest_path = target_root / "p05_m1_evaluation_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["evaluate_m1_model"]
