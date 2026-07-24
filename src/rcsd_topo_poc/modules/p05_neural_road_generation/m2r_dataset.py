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
from typing import Any

import fiona
import numpy as np
from PIL import Image, ImageDraw
from pyproj import CRS
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_dataset import (
    OPERATION_TO_INDEX,
    _CaseGraph,
    _build_edges,
    _feature_names,
    _lookup,
    _norm_id,
    _operation_labels,
    _read_node_lookup,
    _read_vector,
    _road_feature,
    _target_truth_ids,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_csv, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_models import M2RDatasetConfig
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


BASE_INPUT_ROLE_NAMES = {
    "t01_roads",
    "t01_segment",
    "raw_prepared_swsd_nodes",
    "raw_rcsdroad",
    "raw_rcsdnode",
    "raw_drivezone",
    "raw_divstripzone",
}


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _resolve_output(run_root: Path, record: dict[str, Any]) -> Path:
    configured = normalize_runtime_path(str(record.get("path") or ""))
    if configured.is_file():
        return configured.resolve()
    fallback = run_root / configured.name
    if fallback.is_file():
        return fallback.resolve()
    raise FileNotFoundError(configured)


def _verify_manifest(run_root: Path, *, strict_hashes: bool) -> tuple[dict[str, Any], dict[str, Path]]:
    path = run_root / "p05_m2r_supervision_manifest.json"
    manifest = _read_json(path)
    if manifest.get("schema_version") != "p05-m2r-supervision-manifest-v1":
        raise ValueError("invalid M2R supervision manifest")
    if manifest.get("silent_fix") is not False:
        raise ValueError("supervision manifest must declare silent_fix=false")
    outputs: dict[str, Path] = {}
    for role, record in dict(manifest.get("outputs") or {}).items():
        resolved = _resolve_output(run_root, record)
        if strict_hashes and sha256_file(resolved) != str(record.get("sha256") or ""):
            raise ValueError(f"supervision output hash mismatch: {role}")
        outputs[role] = resolved
    for required in ("targets", "coverage", "summary"):
        if required not in outputs:
            raise ValueError(f"supervision output missing: {required}")
    return manifest, outputs


def _m0_paths(supervision: dict[str, Any], *, strict_hashes: bool) -> tuple[dict[str, Any], dict[str, Path]]:
    manifest_path = normalize_runtime_path(str(supervision.get("m0_manifest_path") or ""))
    manifest = _read_json(manifest_path)
    if strict_hashes and sha256_file(manifest_path) != str(supervision.get("m0_manifest_sha256") or ""):
        raise ValueError("M0 manifest hash differs from supervision lineage")
    run_root = manifest_path.parent
    outputs: dict[str, Path] = {}
    for role, record in dict(manifest.get("outputs") or {}).items():
        outputs[role] = _resolve_output(run_root, record)
        if strict_hashes and sha256_file(outputs[role]) != str(record.get("sha256") or ""):
            raise ValueError(f"M0 output hash mismatch: {role}")
    return manifest, outputs


def _first_gpkg(case_root: Path, role: str) -> Path:
    paths = sorted((case_root / "external_inputs" / role).glob("*.gpkg"))
    if len(paths) != 1:
        raise ValueError(f"expected exactly one {role} GPKG under {case_root}, got {len(paths)}")
    return paths[0].resolve()


def _artifact_row(sample_id: str, role: str, path: Path, *, label_only: bool) -> dict[str, Any]:
    if role not in BASE_INPUT_ROLE_NAMES and not label_only:
        raise ValueError(f"non-base artifact attempted as input: {role}")
    layers = fiona.listlayers(path) if path.suffix.casefold() in {".gpkg", ".geojson"} else []
    crs = ""
    count = 0
    if layers:
        with fiona.open(path, layer=layers[0]) as source:
            crs = source.crs.to_string() if source.crs else ""
            count = len(source)
    return {
        "sample_id": sample_id,
        "role": role,
        "path": str(path.resolve()),
        "sha256": sha256_file(path),
        "label_only": label_only,
        "crs": crs,
        "feature_count": count,
    }


def _draw_geometry(draw: ImageDraw.ImageDraw, geometry: BaseGeometry, project, *, fill: int, width: int = 1) -> None:
    if geometry.is_empty:
        return
    kind = geometry.geom_type
    if kind == "Point":
        x, y = project(geometry.x, geometry.y)
        radius = max(1, width)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill)
    elif kind in {"LineString", "LinearRing"}:
        coordinates = [project(x, y) for x, y, *_ in geometry.coords]
        if len(coordinates) >= 2:
            draw.line(coordinates, fill=fill, width=width)
    elif kind == "Polygon":
        exterior = [project(x, y) for x, y, *_ in geometry.exterior.coords]
        if exterior:
            draw.polygon(exterior, fill=fill)
        for interior in geometry.interiors:
            hole = [project(x, y) for x, y, *_ in interior.coords]
            if hole:
                draw.polygon(hole, fill=0)
    elif hasattr(geometry, "geoms"):
        for child in geometry.geoms:
            _draw_geometry(draw, child, project, fill=fill, width=width)


def _vector_mask(path: Path, size: int, project, *, geometry_filter=None, width: int = 1) -> np.ndarray:
    image = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(image)
    layers = fiona.listlayers(path)
    if not layers:
        return np.zeros((size, size), dtype=np.uint8)
    with fiona.open(path, layer=layers[0]) as source:
        for feature in source:
            if feature.geometry is None:
                continue
            properties = dict(feature.properties)
            if geometry_filter is not None and not geometry_filter(properties):
                continue
            _draw_geometry(draw, shape(feature.geometry), project, fill=1, width=width)
    return np.asarray(image, dtype=np.uint8)


def _case_projector(manifest: dict[str, Any], size: int):
    raster = dict(dict(manifest.get("transform") or {}).get("raster") or {})
    width = int(raster.get("width") or 0)
    height = int(raster.get("height") or 0)
    resolution = float(raster.get("resolution_m") or 0.0)
    top_left_x = float(raster.get("top_left_x_epsg3857") or 0.0)
    top_left_y = float(raster.get("top_left_y_epsg3857") or 0.0)
    if min(width, height, resolution) <= 0:
        raise ValueError("invalid raster transform")

    def project(x: float, y: float) -> tuple[float, float]:
        return ((x - top_left_x) / (width * resolution) * size, (top_left_y - y) / (height * resolution) * size)

    return project


def _scene_tensor(case_root: Path, business_id: str, size: int) -> tuple[np.ndarray, str]:
    manifest = _read_json(case_root / "manifest.json")
    project = _case_projector(manifest, size)
    drive_png = Image.open(case_root / "drivezone_mask.png").convert("L").resize((size, size), Image.Resampling.NEAREST)
    drive_mask = (np.asarray(drive_png) > 0).astype(np.uint8)
    channels = [
        drive_mask,
        _vector_mask(case_root / "drivezone.gpkg", size, project),
        _vector_mask(case_root / "divstripzone.gpkg", size, project) if (case_root / "divstripzone.gpkg").is_file() else np.zeros_like(drive_mask),
        _vector_mask(case_root / "roads.gpkg", size, project, width=2),
        _vector_mask(case_root / "rcsdroad.gpkg", size, project, width=2),
        _vector_mask(case_root / "nodes.gpkg", size, project),
        _vector_mask(
            case_root / "nodes.gpkg",
            size,
            project,
            geometry_filter=lambda props: str(props.get("id") or "") == business_id
            or str(props.get("mainnodeid") or "") == business_id,
            width=2,
        ),
        _vector_mask(case_root / "rcsdnode.gpkg", size, project),
    ]
    epsg = str(manifest.get("epsg") or "")
    return np.stack(channels, axis=0), f"EPSG:{epsg}" if epsg else ""


def _surface_target(label_doc: dict[str, Any], size: int, case_root: Path) -> tuple[np.ndarray, int]:
    state = str(label_doc.get("formal_state") or "").casefold()
    if state not in {"accepted", "rejected"}:
        raise ValueError("surface label lacks formal terminal state")
    if state == "rejected":
        return np.zeros((size, size), dtype=np.uint8), 0
    geometry_record = label_doc.get("surface_geometry")
    if not isinstance(geometry_record, dict):
        raise ValueError("accepted surface label lacks geometry lineage")
    path = normalize_runtime_path(str(geometry_record.get("path") or ""))
    if sha256_file(path) != str(geometry_record.get("sha256") or ""):
        raise ValueError("surface geometry hash mismatch")
    return _vector_mask(path, size, _case_projector(_read_json(case_root / "manifest.json"), size)), 1


def _relation_target(label_doc: dict[str, Any], task_name: str) -> int:
    if label_doc.get("target_kind") != "relation" or label_doc.get("task_name") != task_name:
        raise ValueError("relation label wrapper task mismatch")
    evidence = label_doc.get("relation_evidence")
    label = evidence.get("label") if isinstance(evidence, dict) else None
    try:
        value = int(label.get("class_index")) if isinstance(label, dict) else -1
    except (TypeError, ValueError):
        value = -1
    maximum = 2 if task_name == "T03" else 1
    if value < 0 or value > maximum:
        raise ValueError(f"invalid {task_name} relation class: {value}")
    return value


def _build_scenes(
    samples: dict[str, dict[str, str]],
    targets: list[dict[str, str]],
    folds: dict[str, int],
    config: M2RDatasetConfig,
) -> tuple[dict[str, np.ndarray], list[dict[str, Any]], list[dict[str, Any]]]:
    arrays: dict[str, list[Any]] = defaultdict(list)
    index: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    relation_targets = {
        (target["sample_id"], target["task_name"]): target
        for target in targets
        if target.get("availability") == "available"
        and target.get("target_kind") == "relation"
        and target.get("task_name") in {"T03", "T04"}
    }
    for target in targets:
        if target.get("availability") != "available" or target.get("target_kind") != "surface":
            continue
        if target.get("task_name") not in {"T03", "T04"}:
            continue
        sample_id = target["sample_id"]
        if sample_id not in samples or folds.get(sample_id) not in config.folds:
            continue
        sample = samples[sample_id]
        label_path = normalize_runtime_path(target["artifact_path"])
        if config.strict_hashes and sha256_file(label_path) != target["artifact_sha256"]:
            raise ValueError(f"surface label wrapper hash mismatch: {sample_id}")
        label_doc = _read_json(label_path)
        case_root = normalize_runtime_path(sample["manifest_path"]).parent
        scene, crs = _scene_tensor(case_root, sample["business_id"], config.image_size)
        surface, accepted = _surface_target(label_doc, config.image_size, case_root)
        relation_record = relation_targets.get((sample_id, target["task_name"]))
        relation_value = -1
        relation_weight = 0.0
        relation_path: Path | None = None
        if relation_record is not None:
            relation_path = normalize_runtime_path(relation_record["artifact_path"])
            if config.strict_hashes and sha256_file(relation_path) != relation_record["artifact_sha256"]:
                raise ValueError(f"relation label wrapper hash mismatch: {sample_id}")
            relation_value = _relation_target(_read_json(relation_path), target["task_name"])
            relation_weight = float(relation_record["target_weight"] or 0.0)
        arrays["scene"].append(scene)
        arrays["surface"].append(surface)
        arrays["module"].append(0 if target["task_name"] == "T03" else 1)
        arrays["accepted"].append(accepted)
        arrays["fold"].append(folds[sample_id])
        arrays["weight"].append(float(target["target_weight"] or 0.0))
        arrays["relation"].append(relation_value)
        arrays["relation_weight"].append(relation_weight)
        arrays["sample_id"].append(sample_id)
        index.append(
            {
                "row_index": len(index),
                "sample_id": sample_id,
                "family": sample["family"],
                "business_id": sample["business_id"],
                "fold": folds[sample_id],
                "task_name": target["task_name"],
                "formal_state": label_doc["formal_state"],
                "crs": crs,
                "case_root": str(case_root.resolve()),
                "label_path": str(label_path.resolve()),
                "label_sha256": target["artifact_sha256"],
                "relation_label_path": str(relation_path.resolve()) if relation_path else "",
                "relation_class": relation_value,
            }
        )
        for role, name in (
            ("raw_drivezone", "drivezone.gpkg"),
            ("raw_divstripzone", "divstripzone.gpkg"),
            ("raw_prepared_swsd_nodes", "nodes.gpkg"),
            ("raw_rcsdroad", "rcsdroad.gpkg"),
            ("raw_rcsdnode", "rcsdnode.gpkg"),
        ):
            path = case_root / name
            if path.is_file():
                artifacts.append(_artifact_row(sample_id, role, path, label_only=False))
        artifacts.append(_artifact_row(sample_id, "surface_truth_wrapper", label_path, label_only=True))
        if relation_path is not None:
            artifacts.append(_artifact_row(sample_id, "relation_truth_wrapper", relation_path, label_only=True))
    if not index:
        raise ValueError("no T03/T04 surface scenes are available")
    packed = {
        "scene": np.asarray(arrays["scene"], dtype=np.uint8),
        "surface": np.asarray(arrays["surface"], dtype=np.uint8),
        "module": np.asarray(arrays["module"], dtype=np.int64),
        "accepted": np.asarray(arrays["accepted"], dtype=np.int64),
        "fold": np.asarray(arrays["fold"], dtype=np.int64),
        "weight": np.asarray(arrays["weight"], dtype=np.float32),
        "relation": np.asarray(arrays["relation"], dtype=np.int64),
        "relation_weight": np.asarray(arrays["relation_weight"], dtype=np.float32),
        "sample_id": np.asarray(arrays["sample_id"], dtype=np.str_),
    }
    return packed, index, artifacts


def _t01_roads(artifact: dict[str, str]) -> Path:
    summary = _read_json(normalize_runtime_path(artifact["case_run_summary_path"]))
    funnel = summary.get("t06_funnel") if isinstance(summary.get("t06_funnel"), dict) else {}
    handoffs = funnel.get("handoffs") if isinstance(funnel.get("handoffs"), dict) else {}
    path = normalize_runtime_path(str(handoffs.get("t01_roads") or ""))
    if not path.is_file():
        raise FileNotFoundError(path)
    return path.resolve()


def _vector_id_set(path: Path, field: str, *, status_field: str = "", accepted_status: int = 0) -> set[str]:
    result: set[str] = set()
    for layer in fiona.listlayers(path):
        with fiona.open(path, layer=layer) as source:
            for feature in source:
                properties = dict(feature.properties)
                if status_field:
                    try:
                        if int(_lookup(properties, status_field)) != accepted_status:
                            continue
                    except (TypeError, ValueError):
                        continue
                value = _norm_id(_lookup(properties, field))
                if value and value != "-1":
                    result.add(value)
    return result


def _endpoint_membership(graph: _CaseGraph, node_ids: set[str], *, source_role: str) -> np.ndarray:
    result = np.full((len(graph.roads), 2), -1, dtype=np.int64)
    for index, road in enumerate(graph.roads):
        if road.source_role != source_role:
            continue
        result[index] = [
            int(_norm_id(_lookup(road.properties, field)) in node_ids)
            for field in ("snodeid", "enodeid")
        ]
    return result


def _build_road_graph(sample: dict[str, str], roles: dict[str, dict[str, str]], fold: int, config: M2RDatasetConfig) -> _CaseGraph:
    required = {"t01_segment", "t05_intersection_match_all", "t06_frcsd_road", "t06_frcsd_node", "t06_swsd_frcsd_segment_relation"}
    if not required.issubset(roles):
        raise ValueError(f"{sample['sample_id']}: missing RoadGraph labels {sorted(required - set(roles))}")
    case_root = normalize_runtime_path(sample["case_root"])
    t01_roads_path = _t01_roads(roles["t01_segment"])
    t01_segment_path = normalize_runtime_path(roles["t01_segment"]["artifact_path"])
    raw_swsd_nodes = _first_gpkg(case_root, "prepared_swsd_nodes")
    raw_rcsd_road = _first_gpkg(case_root, "rcsdroad")
    raw_rcsd_node = _first_gpkg(case_root, "rcsdnode")
    truth_road_path = normalize_runtime_path(roles["t06_frcsd_road"]["artifact_path"])
    truth_relation_path = normalize_runtime_path(roles["t06_swsd_frcsd_segment_relation"]["artifact_path"])
    t05_relation_path = normalize_runtime_path(roles["t05_intersection_match_all"]["artifact_path"])
    t07_nodes_path = normalize_runtime_path(roles["t07_nodes"]["artifact_path"]) if config.include_t07 and "t07_nodes" in roles else None
    t01, t01_crs, t01_duplicates = _read_vector(t01_roads_path, source_role="t01_roads")
    raw_rcsd, rcsd_crs, rcsd_duplicates = _read_vector(raw_rcsd_road, source_role="t05_rcsdroad_out")
    truth, truth_crs, truth_duplicates = _read_vector(truth_road_path, source_role="truth")
    if not t01_crs or not rcsd_crs or not truth_crs or not (
        CRS.from_user_input(t01_crs) == CRS.from_user_input(rcsd_crs) == CRS.from_user_input(truth_crs)
    ):
        raise ValueError(f"{sample['sample_id']}: base candidate/truth CRS mismatch")
    swsd_nodes, swsd_crs = _read_node_lookup(raw_swsd_nodes)
    rcsd_nodes, rcsd_node_crs = _read_node_lookup(raw_rcsd_node)
    if CRS.from_user_input(swsd_crs) != CRS.from_user_input(truth_crs) or CRS.from_user_input(rcsd_node_crs) != CRS.from_user_input(truth_crs):
        raise ValueError(f"{sample['sample_id']}: raw Node CRS differs from Road CRS")
    combined = dict(t01)
    cross_source = sorted(set(t01) & set(raw_rcsd))
    combined.update(raw_rcsd)
    roads = [combined[key] for key in sorted(combined)]
    for road in roads:
        lookup = swsd_nodes if road.source_role == "t01_roads" else rcsd_nodes
        road.feature, road.endpoint_xy = _road_feature(road, polyline_points=config.polyline_points, node_lookup=lookup)
    edges = _build_edges(roads, config.neighbor_distance_m)
    degree = Counter(left for left, _ in edges)
    for index, road in enumerate(roads):
        road.feature = np.concatenate((road.feature, np.asarray([np.log1p(degree.get(index, 0))])))
    target_ids, target_found = _target_truth_ids(truth_relation_path, sample["scope_type"], sample["business_id"])
    if sample["scope_type"] == "t10_case":
        target_ids = set(truth)
    labels, uncovered, accounted, label_anomalies = _operation_labels(
        roads,
        truth,
        target_truth_ids=target_ids,
        target_weight=float(sample["target_weight"]),
        context_weight=float(sample["context_weight"]),
        polyline_points=config.polyline_points,
        all_candidates_target=sample["scope_type"] == "t10_case",
    )
    anomalies = list(label_anomalies)
    for role, count in (("t01_roads", t01_duplicates), ("raw_rcsdroad", rcsd_duplicates), ("t06_frcsd_road", truth_duplicates)):
        if count:
            anomalies.append({"category": "duplicate_road_id", "role": role, "detail": f"duplicates={count}"})
    if cross_source:
        anomalies.append({"category": "cross_source_duplicate_road_id", "detail": f"count={len(cross_source)}", "examples": cross_source[:20]})
    input_artifacts = [
        _artifact_row(sample["sample_id"], "t01_roads", t01_roads_path, label_only=False),
        _artifact_row(sample["sample_id"], "t01_segment", t01_segment_path, label_only=False),
        _artifact_row(sample["sample_id"], "raw_prepared_swsd_nodes", raw_swsd_nodes, label_only=False),
        _artifact_row(sample["sample_id"], "raw_rcsdroad", raw_rcsd_road, label_only=False),
        _artifact_row(sample["sample_id"], "raw_rcsdnode", raw_rcsd_node, label_only=False),
        _artifact_row(sample["sample_id"], "t06_frcsd_road_truth", truth_road_path, label_only=True),
        _artifact_row(sample["sample_id"], "t06_segment_relation_truth", truth_relation_path, label_only=True),
        _artifact_row(sample["sample_id"], "t05_relation_truth", t05_relation_path, label_only=True),
    ]
    if t07_nodes_path is not None:
        input_artifacts.append(_artifact_row(sample["sample_id"], "t07_nodes_truth", t07_nodes_path, label_only=True))
    return _CaseGraph(
        sample_id=sample["sample_id"], family=sample["family"], business_id=sample["business_id"],
        scope_type=sample["scope_type"], split="oof", fold=fold, crs=truth_crs, roads=roads,
        labels=labels, edges=edges, input_artifacts=input_artifacts, truth_count=len(truth),
        accounted_truth_count=accounted, uncovered_truth_ids=uncovered, target_relation_found=target_found,
        anomalies=anomalies,
    )


def _write_road_graphs(run_root: Path, graphs: list[_CaseGraph]) -> list[dict[str, Any]]:
    root = run_root / "road_graphs"
    root.mkdir()
    result = []
    for graph in graphs:
        features = np.vstack([road.feature for road in graph.roads]).astype(np.float32)
        edge_pairs = sorted(graph.edges)
        edge_index = np.asarray(edge_pairs, dtype=np.int64).T if edge_pairs else np.empty((2, 0), dtype=np.int64)
        count = len(graph.roads)
        split_fractions = np.zeros((count, 2), dtype=np.float32)
        split_mask = np.zeros((count, 2), dtype=np.float32)
        child_geometry = np.zeros((count, 3, graph.labels[0].child_geometry.shape[1], 2), dtype=np.float32)
        child_mask = np.zeros((count, 3), dtype=np.float32)
        label_paths = {item["role"]: normalize_runtime_path(item["path"]) for item in graph.input_artifacts if item["label_only"]}
        t05_ids = _vector_id_set(label_paths["t05_relation_truth"], "base_id", status_field="status")
        t05_endpoint_relation = _endpoint_membership(graph, t05_ids, source_role="t05_rcsdroad_out")
        t07_endpoint_member = np.full((count, 2), -1, dtype=np.int64)
        if "t07_nodes_truth" in label_paths:
            t07_endpoint_member = _endpoint_membership(
                graph, _vector_id_set(label_paths["t07_nodes_truth"], "id"), source_role="t01_roads"
            )
        for index, label in enumerate(graph.labels):
            for position, value in enumerate(label.split_fractions[:2]):
                split_fractions[index, position] = value
                split_mask[index, position] = float(label.split_fraction_valid)
            child_geometry[index] = label.child_geometry
            child_mask[index] = label.child_mask
        path = root / (hashlib.sha256(graph.sample_id.encode("utf-8")).hexdigest()[:20] + ".npz")
        np.savez_compressed(
            path,
            x=features,
            edge_index=edge_index,
            operation=np.asarray([OPERATION_TO_INDEX[label.operation] for label in graph.labels], dtype=np.int64),
            weight=np.asarray([label.label_weight for label in graph.labels], dtype=np.float32),
            direction=np.asarray([label.direction_values[0] if label.direction_values else -1 for label in graph.labels], dtype=np.int64),
            source=np.asarray([label.source_values[0] if label.source_values else -1 for label in graph.labels], dtype=np.int64),
            split_fractions=split_fractions,
            split_fraction_mask=split_mask,
            child_geometry=child_geometry,
            child_mask=child_mask,
            road_ids=np.asarray([road.road_id for road in graph.roads], dtype=np.str_),
            source_roles=np.asarray(["swsd" if road.source_role == "t01_roads" else "rcsd" for road in graph.roads], dtype=np.str_),
            t05_endpoint_relation=t05_endpoint_relation,
            t07_endpoint_member=t07_endpoint_member,
        )
        result.append(
            {
                "sample_id": graph.sample_id, "family": graph.family, "business_id": graph.business_id,
                "scope_type": graph.scope_type, "fold": graph.fold, "graph_path": str(path.resolve()),
                "graph_sha256": sha256_file(path), "candidate_count": count,
                "edge_count": int(edge_index.shape[1]), "truth_count": graph.truth_count,
                "accounted_truth_count": graph.accounted_truth_count, "uncovered_truth_ids": graph.uncovered_truth_ids,
                "target_relation_found": graph.target_relation_found, "crs": graph.crs,
                "t05_endpoint_positive_count": int((t05_endpoint_relation == 1).sum()),
                "t05_endpoint_observed_count": int((t05_endpoint_relation >= 0).sum()),
                "t07_endpoint_positive_count": int((t07_endpoint_member == 1).sum()),
                "t07_endpoint_observed_count": int((t07_endpoint_member >= 0).sum()),
            }
        )
    return result


def _environment() -> dict[str, Any]:
    versions = {}
    for package in ("fiona", "numpy", "pillow", "pyproj", "shapely"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return {"python": sys.version, "platform": platform.platform(), "logical_cpu_count": os.cpu_count(), "libraries": versions}


def build_m2r_dataset(config: M2RDatasetConfig) -> dict[str, Any]:
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    supervision_root = normalize_runtime_path(config.supervision_run_root).resolve(strict=True)
    supervision, supervision_outputs = _verify_manifest(supervision_root, strict_hashes=config.strict_hashes)
    m0_manifest, m0_outputs = _m0_paths(supervision, strict_hashes=config.strict_hashes)
    samples = {row["sample_id"]: row for row in _read_csv(m0_outputs["samples"])}
    folds = {row["sample_id"]: int(row["fold"]) for row in _read_csv(m0_outputs["split"])}
    targets = _read_csv(supervision_outputs["targets"])
    output_root = normalize_runtime_path(config.output_root).resolve(strict=False)
    output_root.mkdir(parents=True, exist_ok=True)
    run_root = output_root / config.run_id
    run_root.mkdir(exist_ok=False)

    scenes, scene_index, input_artifacts = _build_scenes(samples, targets, folds, config)
    scene_path = run_root / "p05_m2r_scenes.npz"
    np.savez_compressed(scene_path, **scenes)
    road_samples = {
        sample_id: sample for sample_id, sample in samples.items()
        if folds.get(sample_id) in config.folds and bool(json.loads(sample["task_mask"]).get("road_graph"))
    }
    artifact_roles: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in _read_csv(m0_outputs["artifacts"]):
        if row["sample_id"] in road_samples:
            artifact_roles[row["sample_id"]][row["role"]] = row
    graphs = [_build_road_graph(road_samples[sample_id], artifact_roles[sample_id], folds[sample_id], config) for sample_id in sorted(road_samples)]
    graph_index = _write_road_graphs(run_root, graphs)
    input_artifacts.extend(item for graph in graphs for item in graph.input_artifacts)
    anomalies = [
        {"sample_id": graph.sample_id, "family": graph.family, "business_id": graph.business_id, **item}
        for graph in graphs for item in graph.anomalies
    ]
    ids_by_fold: dict[int, set[str]] = defaultdict(set)
    for graph in graphs:
        ids_by_fold[graph.fold].update(road.road_id for road in graph.roads)
    cross_fold_overlap = {
        f"{left}__{right}": len(ids_by_fold[left] & ids_by_fold[right])
        for left in config.folds for right in config.folds if left < right
    }
    feature_names = [name.replace("source_role_t05", "source_role_raw_rcsd") for name in _feature_names(config.polyline_points)]
    if graphs and len(feature_names) != len(graphs[0].roads[0].feature):
        raise AssertionError("M2R Road feature schema mismatch")
    truth_count = sum(graph.truth_count for graph in graphs)
    accounted = sum(graph.accounted_truth_count for graph in graphs)
    summary = {
        "schema_version": "p05-m2r-dataset-summary-v1", "scene_count": len(scene_index),
        "scene_fold_counts": dict(sorted(Counter(str(row["fold"]) for row in scene_index).items())),
        "scene_shape": list(scenes["scene"].shape), "road_graph_count": len(graphs),
        "scene_surface_target_count": int((scenes["weight"] > 0).sum()),
        "scene_relation_target_count": int((scenes["relation_weight"] > 0).sum()),
        "road_graph_fold_counts": dict(sorted(Counter(str(graph.fold) for graph in graphs).items())),
        "road_candidate_count": sum(len(graph.roads) for graph in graphs),
        "road_edge_count": sum(item["edge_count"] for item in graph_index), "road_truth_count": truth_count,
        "road_accounted_truth_count": accounted,
        "road_operation_truth_coverage": accounted / truth_count if truth_count else 0.0,
        "t05_endpoint_positive_count": sum(item["t05_endpoint_positive_count"] for item in graph_index),
        "t05_endpoint_observed_count": sum(item["t05_endpoint_observed_count"] for item in graph_index),
        "t07_endpoint_positive_count": sum(item["t07_endpoint_positive_count"] for item in graph_index),
        "t07_endpoint_observed_count": sum(item["t07_endpoint_observed_count"] for item in graph_index),
        "raw_cross_fold_road_id_overlap": cross_fold_overlap,
        "input_role_names": sorted({item["role"] for item in input_artifacts if not item["label_only"]}),
        "label_only_role_names": sorted({item["role"] for item in input_artifacts if item["label_only"]}),
        "feature_dim": len(feature_names), "duration_seconds": time.perf_counter() - started, "silent_fix": False,
    }
    forbidden_inputs = sorted(set(summary["input_role_names"]) - BASE_INPUT_ROLE_NAMES)
    if forbidden_inputs:
        raise ValueError(f"label leakage roles entered M2R input: {forbidden_inputs}")
    paths = {
        "scenes": scene_path,
        "scene_index": run_root / "p05_m2r_scene_index.csv",
        "graph_index": run_root / "p05_m2r_road_graph_index.json",
        "input_artifacts": run_root / "p05_m2r_input_artifacts.csv",
        "anomalies": run_root / "p05_m2r_dataset_anomalies.csv",
        "feature_schema": run_root / "p05_m2r_feature_schema.json",
        "summary": run_root / "p05_m2r_dataset_summary.json",
        "report": run_root / "p05_m2r_dataset_report.md",
    }
    write_csv(paths["scene_index"], scene_index, list(scene_index[0]))
    write_json(paths["graph_index"], {"schema_version": "p05-m2r-road-graph-index-v1", "graphs": graph_index})
    write_csv(paths["input_artifacts"], input_artifacts, ["sample_id", "role", "path", "sha256", "label_only", "crs", "feature_count"])
    write_csv(paths["anomalies"], anomalies, ["sample_id", "family", "business_id", "category", "role", "road_id", "detail", "examples"])
    write_json(paths["feature_schema"], {"scene_channels": ["drivezone_raster", "drivezone", "divstripzone", "swsd_roads", "rcsd_roads", "swsd_nodes", "target_nodes", "rcsd_nodes"], "road_feature_names": feature_names})
    write_json(paths["summary"], summary)
    paths["report"].write_text(
        "# P05 M2R 联合数据集报告\n\n"
        f"- T03/T04 scene：{summary['scene_count']}。\n"
        f"- T10 RoadGraph：{summary['road_graph_count']}，候选 Road {summary['road_candidate_count']}。\n"
        f"- Road truth coverage：{summary['road_operation_truth_coverage']:.4%}。\n"
        f"- 模型输入角色：{summary['input_role_names']}。\n\n"
        "T03/T04/T05/T06 当前样本目标仅在 label-only 侧；OOF 训练阶段继续执行 held-out entity guard。\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": "p05-m2r-dataset-manifest-v1", "module_id": "p05_neural_road_generation",
        "run_id": config.run_id, "status": "dataset_ready", "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(), "supervision_run_root": str(supervision_root),
        "supervision_manifest_sha256": sha256_file(supervision_root / "p05_m2r_supervision_manifest.json"),
        "m0_run_id": m0_manifest.get("run_id"),
        "config": {"folds": list(config.folds), "include_t07": config.include_t07, "image_size": config.image_size, "polyline_points": config.polyline_points, "entity_guard_hops": config.entity_guard_hops, "neighbor_distance_m": config.neighbor_distance_m, "strict_hashes": config.strict_hashes},
        "environment": _environment(), "performance": {"duration_seconds": summary["duration_seconds"]},
        "silent_fix": False, "outputs": {role: output_record(path) for role, path in paths.items()},
        "road_graph_outputs": {item["sample_id"]: {"path": item["graph_path"], "sha256": item["graph_sha256"]} for item in graph_index},
    }
    manifest_path = run_root / "p05_m2r_dataset_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_path"] = str(manifest_path.resolve())
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["BASE_INPUT_ROLE_NAMES", "build_m2r_dataset"]
