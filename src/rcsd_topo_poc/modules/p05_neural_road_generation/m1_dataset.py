from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import sys
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import fiona
import numpy as np
from pyproj import CRS
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_models import M1DatasetConfig
from rcsd_topo_poc.modules.p05_neural_road_generation.m1_outputs import output_record, write_csv, write_json
from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


OPERATION_NAMES = ("DROP", "KEEP", "SPLIT_1", "SPLIT_2", "SPLIT_3")
OPERATION_TO_INDEX = {name: index for index, name in enumerate(OPERATION_NAMES)}
SPLIT_PRIORITY = {"train": 0, "validation": 1, "test": 2}
INPUT_ROLES = (
    "t01_segment",
    "t03_nodes",
    "t04_nodes",
    "t05_rcsdroad_out",
    "t05_rcsdnode_out",
    "t07_nodes",
)
LABEL_ONLY_ROLES = ("t06_frcsd_road", "t06_frcsd_node", "t06_swsd_frcsd_segment_relation")
ROAD_NUMERIC_FIELDS = (
    "direction",
    "source",
    "formway",
    "funcclass",
    "roadclass",
    "roadtype",
    "layer",
    "const_st",
    "lanenumsum",
    "lanenums2e",
    "lanenume2s",
    "length",
)
NODE_NUMERIC_FIELDS = ("kind", "grade", "cross_flag", "source", "layer", "closed_con", "light_flag")
MAX_SPATIAL_NEIGHBORS = 16


@dataclass
class _Road:
    road_id: str
    source_role: str
    properties: dict[str, Any]
    geometry: BaseGeometry
    crs: str
    feature: np.ndarray | None = None
    endpoint_xy: tuple[tuple[float, float], tuple[float, float]] | None = None


@dataclass
class _Label:
    operation: str
    output_road_ids: list[str]
    direction_values: list[int]
    source_values: list[int]
    split_fractions: list[float]
    split_fraction_valid: bool
    child_geometry: np.ndarray
    child_mask: np.ndarray
    target_scope: str
    label_weight: float


@dataclass
class _CaseGraph:
    sample_id: str
    family: str
    business_id: str
    scope_type: str
    split: str
    fold: int
    crs: str
    roads: list[_Road]
    labels: list[_Label]
    edges: set[tuple[int, int]]
    input_artifacts: list[dict[str, Any]]
    truth_count: int
    accounted_truth_count: int
    uncovered_truth_ids: list[str]
    target_relation_found: bool
    anomalies: list[dict[str, Any]] = field(default_factory=list)
    guarded_out: set[int] = field(default_factory=set)
    direct_guarded_out: set[int] = field(default_factory=set)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _resolve_record_path(run_root: Path, record: dict[str, Any]) -> Path:
    configured = normalize_runtime_path(str(record.get("path") or ""))
    if configured.is_file():
        return configured
    fallback = run_root / configured.name
    if fallback.is_file():
        return fallback
    raise FileNotFoundError(configured)


def _verify_m0_run(run_root: Path, *, strict_hashes: bool) -> tuple[dict[str, Any], dict[str, Path]]:
    manifest_path = run_root / "p05_m0_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    manifest = _read_json(manifest_path)
    if manifest.get("schema_version") != "p05-m0-manifest-v1":
        raise ValueError(f"unsupported M0 manifest schema: {manifest.get('schema_version')!r}")
    if manifest.get("silent_fix") is not False:
        raise ValueError("M0 manifest must declare silent_fix=false")
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ValueError("M0 manifest outputs are missing")
    required = {"samples", "artifacts", "split", "anomalies", "oracle", "summary"}
    if not required.issubset(outputs):
        raise ValueError(f"M0 manifest outputs missing: {sorted(required - set(outputs))}")
    resolved: dict[str, Path] = {}
    for role in sorted(required):
        record = outputs[role]
        if not isinstance(record, dict):
            raise ValueError(f"invalid M0 output record: {role}")
        path = _resolve_record_path(run_root, record)
        if strict_hashes and sha256_file(path) != str(record.get("sha256") or ""):
            raise ValueError(f"M0 output hash mismatch: {role}: {path}")
        resolved[role] = path
    return manifest, resolved


def _norm_id(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.casefold() in {"", "none", "null", "nan"} else text


def _lookup(properties: dict[str, Any], name: str) -> Any:
    wanted = name.casefold()
    for key, value in properties.items():
        if str(key).casefold() == wanted:
            return value
    return None


def _to_number(value: Any, *, logarithmic: bool = False) -> tuple[float, float]:
    if value is None or str(value).strip() == "":
        return 0.0, 1.0
    text = str(value).strip().casefold()
    mapped = {"yes": 1.0, "true": 1.0, "no": 0.0, "false": 0.0}
    try:
        number = mapped[text] if text in mapped else float(value)
    except (TypeError, ValueError):
        return 0.0, 1.0
    if not math.isfinite(number):
        return 0.0, 1.0
    if logarithmic:
        number = math.copysign(math.log1p(abs(number)), number)
    return number, 0.0


def _sample_geometry(geometry: BaseGeometry, count: int) -> tuple[np.ndarray, tuple[tuple[float, float], tuple[float, float]]]:
    if geometry.is_empty or geometry.length <= 0:
        raise ValueError("Road geometry is empty or has zero length")
    points = []
    for fraction in np.linspace(0.0, 1.0, count):
        point = geometry.interpolate(float(fraction), normalized=True)
        points.append((float(point.x), float(point.y)))
    array = np.asarray(points, dtype=np.float64)
    return array, (tuple(array[0]), tuple(array[-1]))


def _geometry_feature(geometry: BaseGeometry, count: int) -> tuple[np.ndarray, tuple[tuple[float, float], tuple[float, float]]]:
    sampled, endpoints = _sample_geometry(geometry, count)
    center = sampled.mean(axis=0)
    length = max(float(geometry.length), 1.0e-6)
    normalized = (sampled - center) / length
    chord = float(np.linalg.norm(sampled[-1] - sampled[0]))
    bounds = geometry.bounds
    stats = np.asarray(
        [
            math.log1p(length),
            math.log1p(chord),
            chord / length,
            (sampled[-1, 0] - sampled[0, 0]) / length,
            (sampled[-1, 1] - sampled[0, 1]) / length,
            math.log1p(max(0.0, bounds[2] - bounds[0])),
            math.log1p(max(0.0, bounds[3] - bounds[1])),
            1.0 if geometry.geom_type == "MultiLineString" else 0.0,
        ],
        dtype=np.float64,
    )
    return np.concatenate((normalized.reshape(-1), stats)), endpoints


def _node_feature(properties: dict[str, Any] | None) -> np.ndarray:
    values: list[float] = []
    for name in NODE_NUMERIC_FIELDS:
        number, missing = _to_number(_lookup(properties or {}, name))
        values.extend((number, missing))
    for name in ("is_anchor", "has_evd"):
        number, missing = _to_number(_lookup(properties or {}, name))
        values.extend((number, missing))
    return np.asarray(values, dtype=np.float64)


def _feature_names(polyline_points: int) -> list[str]:
    names = [f"geometry_point_{index}_{axis}" for index in range(polyline_points) for axis in ("x", "y")]
    names.extend(("geometry_log_length", "geometry_log_chord", "geometry_chord_ratio", "geometry_dx_ratio", "geometry_dy_ratio", "geometry_log_width", "geometry_log_height", "geometry_is_multiline"))
    for name in ROAD_NUMERIC_FIELDS:
        names.extend((f"road_{name}", f"road_{name}_missing"))
    names.extend(("source_role_t01", "source_role_t05"))
    for endpoint in ("start", "end"):
        for name in NODE_NUMERIC_FIELDS + ("is_anchor", "has_evd"):
            names.extend((f"{endpoint}_node_{name}", f"{endpoint}_node_{name}_missing"))
    names.append("graph_log_degree")
    return names


def _road_feature(
    road: _Road,
    *,
    polyline_points: int,
    node_lookup: dict[str, dict[str, Any]],
) -> tuple[np.ndarray, tuple[tuple[float, float], tuple[float, float]]]:
    geometry_values, endpoints = _geometry_feature(road.geometry, polyline_points)
    values = list(geometry_values)
    for name in ROAD_NUMERIC_FIELDS:
        number, missing = _to_number(_lookup(road.properties, name), logarithmic=name == "length")
        values.extend((number, missing))
    values.extend((1.0 if road.source_role == "t01_roads" else 0.0, 1.0 if road.source_role == "t05_rcsdroad_out" else 0.0))
    start_id = _norm_id(_lookup(road.properties, "snodeid"))
    end_id = _norm_id(_lookup(road.properties, "enodeid"))
    values.extend(_node_feature(node_lookup.get(start_id)))
    values.extend(_node_feature(node_lookup.get(end_id)))
    return np.asarray(values, dtype=np.float64), endpoints


def _read_vector(path: Path, *, source_role: str) -> tuple[dict[str, _Road], str, int]:
    layers = fiona.listlayers(path)
    if not layers:
        raise ValueError(f"vector has no layers: {path}")
    roads: dict[str, _Road] = {}
    duplicates = 0
    with fiona.open(path, layer=layers[0]) as source:
        crs = source.crs.to_string() if source.crs else ""
        for feature in source:
            properties = dict(feature.properties)
            road_id = _norm_id(_lookup(properties, "id"))
            if not road_id or feature.geometry is None:
                continue
            if road_id in roads:
                duplicates += 1
                continue
            roads[road_id] = _Road(road_id, source_role, properties, shape(feature.geometry), crs)
    return roads, crs, duplicates


def _read_node_lookup(path: Path) -> tuple[dict[str, dict[str, Any]], str]:
    layers = fiona.listlayers(path)
    if not layers:
        raise ValueError(f"vector has no layers: {path}")
    result: dict[str, dict[str, Any]] = {}
    with fiona.open(path, layer=layers[0]) as source:
        crs = source.crs.to_string() if source.crs else ""
        for feature in source:
            properties = dict(feature.properties)
            node_id = _norm_id(_lookup(properties, "id"))
            if node_id and node_id not in result:
                result[node_id] = properties
    return result, crs


def _parse_array(value: Any) -> list[str]:
    if value is None or str(value).strip() == "":
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in (_norm_id(raw) for raw in parsed) if item and item != "[]"]


def _integer_value(value: Any, default: int = -1) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _child_geometry_target(
    parent: BaseGeometry,
    children: list[_Road],
    *,
    polyline_points: int,
) -> tuple[list[float], bool, np.ndarray, np.ndarray]:
    child_target = np.zeros((3, polyline_points, 2), dtype=np.float32)
    child_mask = np.zeros(3, dtype=np.float32)
    parent_sample, _ = _sample_geometry(parent, polyline_points)
    center = parent_sample.mean(axis=0)
    scale = max(float(parent.length), 1.0e-6)
    intervals: list[tuple[float, float]] = []
    geometry_valid = True
    for index, child in enumerate(children[:3]):
        sampled, endpoints = _sample_geometry(child.geometry, polyline_points)
        child_target[index] = ((sampled - center) / scale).astype(np.float32)
        child_mask[index] = 1.0
        projections = [float(parent.project(Point(point), normalized=True)) for point in endpoints]
        distances = [float(parent.distance(Point(point))) for point in endpoints]
        intervals.append((min(projections), max(projections)))
        if max(distances, default=0.0) > 2.0:
            geometry_valid = False
    intervals.sort(key=lambda item: (item[0], item[1]))
    fractions = [float((left[1] + right[0]) / 2.0) for left, right in zip(intervals, intervals[1:])]
    if any(not 0.0 < value < 1.0 for value in fractions) or any(left >= right for left, right in zip(fractions, fractions[1:])):
        geometry_valid = False
    return fractions, geometry_valid, child_target, child_mask


def _operation_labels(
    roads: list[_Road],
    truth: dict[str, _Road],
    *,
    target_truth_ids: set[str],
    target_weight: float,
    context_weight: float,
    polyline_points: int,
    all_candidates_target: bool = False,
) -> tuple[list[_Label], list[str], int, list[dict[str, Any]]]:
    candidate_ids = {road.road_id for road in roads}
    children_by_parent: dict[str, list[_Road]] = defaultdict(list)
    uncovered: list[str] = []
    for truth_id, truth_road in truth.items():
        if truth_id in candidate_ids:
            continue
        parent_id = _norm_id(_lookup(truth_road.properties, "t06_split_original_road_id"))
        if parent_id in candidate_ids:
            children_by_parent[parent_id].append(truth_road)
        else:
            uncovered.append(truth_id)
    labels: list[_Label] = []
    anomalies: list[dict[str, Any]] = []
    accounted = 0
    for road in roads:
        exact = truth.get(road.road_id)
        children = children_by_parent.get(road.road_id, [])
        if exact is not None and children:
            anomalies.append({"category": "ambiguous_keep_and_split", "road_id": road.road_id, "detail": "candidate is retained and also has generated children"})
        if children:
            children.sort(key=lambda item: item.road_id)
            if len(children) > 3:
                anomalies.append({"category": "unsupported_split_child_count", "road_id": road.road_id, "detail": f"child_count={len(children)}"})
                operation = "DROP"
                outputs: list[_Road] = []
                fractions: list[float] = []
                fraction_valid = False
                child_target = np.zeros((3, polyline_points, 2), dtype=np.float32)
                child_mask = np.zeros(3, dtype=np.float32)
            else:
                operation = f"SPLIT_{len(children)}"
                outputs = children
                fractions, fraction_valid, child_target, child_mask = _child_geometry_target(
                    road.geometry, children, polyline_points=polyline_points
                )
                accounted += len(children)
        elif exact is not None:
            operation = "KEEP"
            outputs = [exact]
            fractions = []
            fraction_valid = True
            child_target = np.zeros((3, polyline_points, 2), dtype=np.float32)
            child_mask = np.zeros(3, dtype=np.float32)
            accounted += 1
        else:
            operation = "DROP"
            outputs = []
            fractions = []
            fraction_valid = True
            child_target = np.zeros((3, polyline_points, 2), dtype=np.float32)
            child_mask = np.zeros(3, dtype=np.float32)
        is_target = (
            all_candidates_target
            or road.road_id in target_truth_ids
            or any(item.road_id in target_truth_ids for item in outputs)
        )
        labels.append(
            _Label(
                operation=operation,
                output_road_ids=[item.road_id for item in outputs],
                direction_values=[_integer_value(_lookup(item.properties, "direction")) for item in outputs],
                source_values=[_integer_value(_lookup(item.properties, "source")) for item in outputs],
                split_fractions=fractions,
                split_fraction_valid=fraction_valid,
                child_geometry=child_target,
                child_mask=child_mask,
                target_scope="target_segment" if is_target else "context",
                label_weight=target_weight if is_target else context_weight,
            )
        )
    return labels, sorted(uncovered), accounted, anomalies


def _build_edges(roads: list[_Road], neighbor_distance_m: float) -> set[tuple[int, int]]:
    edges: set[tuple[int, int]] = set()
    by_endpoint_id: dict[tuple[str, str], list[int]] = defaultdict(list)
    for index, road in enumerate(roads):
        namespace = "swsd" if road.source_role == "t01_roads" else "rcsd"
        for field_name in ("snodeid", "enodeid"):
            endpoint_id = _norm_id(_lookup(road.properties, field_name))
            if endpoint_id:
                by_endpoint_id[(namespace, endpoint_id)].append(index)
    for indices in by_endpoint_id.values():
        for left in indices:
            for right in indices:
                if left != right:
                    edges.add((left, right))
    if neighbor_distance_m <= 0:
        return edges
    cells: dict[tuple[int, int], list[tuple[int, tuple[float, float]]]] = defaultdict(list)
    for index, road in enumerate(roads):
        assert road.endpoint_xy is not None
        for point in road.endpoint_xy:
            cell = (math.floor(point[0] / neighbor_distance_m), math.floor(point[1] / neighbor_distance_m))
            candidates: list[tuple[float, int]] = []
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for other, other_point in cells.get((cell[0] + dx, cell[1] + dy), []):
                        if other == index:
                            continue
                        distance = math.hypot(point[0] - other_point[0], point[1] - other_point[1])
                        if distance <= neighbor_distance_m:
                            candidates.append((distance, other))
            for _, other in sorted(candidates)[:MAX_SPATIAL_NEIGHBORS]:
                edges.add((index, other))
                edges.add((other, index))
            cells[cell].append((index, point))
    return edges


def _adjacency(size: int, edges: Iterable[tuple[int, int]]) -> list[set[int]]:
    result = [set() for _ in range(size)]
    for left, right in edges:
        result[left].add(right)
    return result


def _apply_entity_guard(graphs: list[_CaseGraph], hops: int) -> list[dict[str, Any]]:
    appearances: dict[str, list[tuple[int, int, str]]] = defaultdict(list)
    for graph_index, graph in enumerate(graphs):
        for road_index, road in enumerate(graph.roads):
            appearances[road.road_id].append((graph_index, road_index, graph.split))
    direct: dict[int, set[int]] = defaultdict(set)
    owner_by_entity: dict[str, str] = {}
    for entity_id, items in appearances.items():
        splits = {item[2] for item in items}
        if len(splits) <= 1:
            continue
        owner = max(splits, key=lambda split: SPLIT_PRIORITY[split])
        owner_by_entity[entity_id] = owner
        for graph_index, road_index, split in items:
            if split != owner:
                direct[graph_index].add(road_index)
    audit: list[dict[str, Any]] = []
    for graph_index, graph in enumerate(graphs):
        graph.direct_guarded_out = set(direct.get(graph_index, set()))
        removed = set(graph.direct_guarded_out)
        adjacency = _adjacency(len(graph.roads), graph.edges)
        frontier = deque((index, 0) for index in sorted(graph.direct_guarded_out))
        while frontier:
            index, depth = frontier.popleft()
            if depth >= hops:
                continue
            for neighbor in adjacency[index]:
                if neighbor not in removed:
                    removed.add(neighbor)
                    frontier.append((neighbor, depth + 1))
        graph.guarded_out = removed
        if graph.roads and len(removed) == len(graph.roads):
            graph.anomalies.append(
                {
                    "category": "all_candidates_removed_by_entity_guard",
                    "detail": f"candidate_count={len(graph.roads)}, direct_overlap={len(graph.direct_guarded_out)}, hops={hops}",
                }
            )
        for index in sorted(removed):
            road = graph.roads[index]
            direct_item = index in graph.direct_guarded_out
            audit.append(
                {
                    "sample_id": graph.sample_id,
                    "split": graph.split,
                    "road_id": road.road_id,
                    "source_role": road.source_role,
                    "decision": "removed_direct_overlap" if direct_item else "removed_guard_neighbor",
                    "owner_split": owner_by_entity.get(road.road_id, "higher_priority_neighbor"),
                    "entity_guard_hops": hops,
                }
            )
    return audit


def _environment() -> dict[str, Any]:
    versions: dict[str, str] = {}
    for package in ("fiona", "numpy", "shapely", "pyproj"):
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


def _artifact_row(
    *,
    sample_id: str,
    role: str,
    path: Path,
    expected_hash: str | None,
    label_only: bool,
    strict_hashes: bool,
) -> dict[str, Any]:
    actual_hash = sha256_file(path)
    if strict_hashes and expected_hash and actual_hash != expected_hash:
        raise ValueError(f"artifact hash mismatch: {sample_id} {role}: {path}")
    layers = fiona.listlayers(path)
    if not layers:
        raise ValueError(f"vector has no layers: {path}")
    with fiona.open(path, layer=layers[0]) as source:
        crs = source.crs.to_string() if source.crs else ""
        feature_count = len(source)
        schema = dict(source.schema)
    return {
        "sample_id": sample_id,
        "role": role,
        "path": str(path.resolve()),
        "sha256": actual_hash,
        "label_only": label_only,
        "crs": crs,
        "feature_count": feature_count,
        "schema": schema,
    }


def _target_truth_ids(relation_path: Path, scope_type: str, business_id: str) -> tuple[set[str], bool]:
    target: set[str] = set()
    found = scope_type == "t10_case"
    layers = fiona.listlayers(relation_path)
    with fiona.open(relation_path, layer=layers[0]) as source:
        for feature in source:
            properties = dict(feature.properties)
            segment_id = _norm_id(_lookup(properties, "swsd_segment_id"))
            if scope_type == "t10_case" or segment_id == business_id:
                found = True
                for field_name in (
                    "swsd_road_ids",
                    "removed_swsd_road_ids",
                    "retained_detached_swsd_road_ids",
                    "external_retained_swsd_carrier_ids",
                    "frcsd_road_ids",
                    "owned_frcsd_road_ids",
                    "related_special_junction_internal_road_ids",
                    "related_connectivity_road_ids",
                ):
                    target.update(_parse_array(_lookup(properties, field_name)))
    return target, found


def _load_case_graph(
    sample: dict[str, str],
    roles: dict[str, dict[str, str]],
    split: str,
    fold: int,
    config: M1DatasetConfig,
) -> _CaseGraph:
    sample_id = sample["sample_id"]
    required = set(INPUT_ROLES) | set(LABEL_ONLY_ROLES)
    if not required.issubset(roles):
        raise ValueError(f"{sample_id}: required M1 roles missing: {sorted(required - set(roles))}")
    run_summary_path = normalize_runtime_path(roles["t01_segment"]["case_run_summary_path"])
    run_summary = _read_json(run_summary_path)
    funnel = run_summary.get("t06_funnel") if isinstance(run_summary.get("t06_funnel"), dict) else {}
    handoffs = funnel.get("handoffs") if isinstance(funnel.get("handoffs"), dict) else {}
    raw_t01_roads = handoffs.get("t01_roads")
    if not raw_t01_roads:
        raise ValueError(f"{sample_id}: t01_roads handoff is missing")
    t01_roads_path = normalize_runtime_path(str(raw_t01_roads))
    if not t01_roads_path.is_file():
        raise FileNotFoundError(t01_roads_path)
    paths = {role: normalize_runtime_path(item["artifact_path"]) for role, item in roles.items()}
    input_artifacts = [
        _artifact_row(
            sample_id=sample_id,
            role="t01_roads",
            path=t01_roads_path,
            expected_hash=None,
            label_only=False,
            strict_hashes=config.strict_hashes,
        )
    ]
    for role in INPUT_ROLES + LABEL_ONLY_ROLES:
        input_artifacts.append(
            _artifact_row(
                sample_id=sample_id,
                role=role,
                path=paths[role],
                expected_hash=roles[role]["artifact_sha256"],
                label_only=role in LABEL_ONLY_ROLES,
                strict_hashes=config.strict_hashes,
            )
        )
    t01, t01_crs, t01_duplicates = _read_vector(t01_roads_path, source_role="t01_roads")
    t05, t05_crs, t05_duplicates = _read_vector(paths["t05_rcsdroad_out"], source_role="t05_rcsdroad_out")
    truth, truth_crs, truth_duplicates = _read_vector(paths["t06_frcsd_road"], source_role="truth")
    if not t01_crs or not t05_crs or not truth_crs or not (CRS.from_user_input(t01_crs) == CRS.from_user_input(t05_crs) == CRS.from_user_input(truth_crs)):
        raise ValueError(f"{sample_id}: candidate/truth Road CRS mismatch: {t01_crs!r}, {t05_crs!r}, {truth_crs!r}")
    crs = CRS.from_user_input(truth_crs)
    if not crs.axis_info or "metre" not in crs.axis_info[0].unit_name.casefold():
        raise ValueError(f"{sample_id}: Road CRS is not metre-based: {truth_crs}")
    semantic_nodes: dict[str, dict[str, Any]] = {}
    node_crs_values: list[str] = []
    for role in ("t07_nodes", "t04_nodes", "t03_nodes"):
        lookup, node_crs = _read_node_lookup(paths[role])
        node_crs_values.append(node_crs)
        for node_id, properties in lookup.items():
            semantic_nodes.setdefault(node_id, properties)
    rcsd_nodes, rcsd_node_crs = _read_node_lookup(paths["t05_rcsdnode_out"])
    node_crs_values.append(rcsd_node_crs)
    if any(not value or CRS.from_user_input(value) != crs for value in node_crs_values):
        raise ValueError(f"{sample_id}: input Node CRS differs from Road CRS")
    anomalies: list[dict[str, Any]] = []
    for role, count in (("t01_roads", t01_duplicates), ("t05_rcsdroad_out", t05_duplicates), ("t06_frcsd_road", truth_duplicates)):
        if count:
            anomalies.append({"category": "duplicate_road_id", "role": role, "detail": f"duplicates={count}"})
    duplicate_sources = sorted(set(t01) & set(t05))
    if duplicate_sources:
        anomalies.append({"category": "cross_source_duplicate_road_id", "detail": f"count={len(duplicate_sources)}", "examples": duplicate_sources[:20]})
    combined = dict(t01)
    combined.update(t05)  # Fixed input-only precedence; T05 wins without consulting truth.
    roads = [combined[key] for key in sorted(combined)]
    for road in roads:
        lookup = semantic_nodes if road.source_role == "t01_roads" else rcsd_nodes
        road.feature, road.endpoint_xy = _road_feature(road, polyline_points=config.polyline_points, node_lookup=lookup)
    edges = _build_edges(roads, config.neighbor_distance_m)
    degree = Counter(left for left, _ in edges)
    for index, road in enumerate(roads):
        assert road.feature is not None
        road.feature = np.concatenate((road.feature, np.asarray([math.log1p(degree.get(index, 0))], dtype=np.float64)))
    target_ids, target_found = _target_truth_ids(paths["t06_swsd_frcsd_segment_relation"], sample["scope_type"], sample["business_id"])
    target_weight = float(sample["target_weight"])
    context_weight = float(sample["context_weight"])
    if sample["scope_type"] == "t10_case":
        target_ids = set(truth)
    if not target_found:
        anomalies.append({"category": "target_segment_relation_missing", "detail": f"business_id={sample['business_id']}"})
        target_ids = set()
    labels, uncovered, accounted, label_anomalies = _operation_labels(
        roads,
        truth,
        target_truth_ids=target_ids,
        target_weight=target_weight,
        context_weight=context_weight,
        polyline_points=config.polyline_points,
        all_candidates_target=sample["scope_type"] == "t10_case",
    )
    anomalies.extend(label_anomalies)
    return _CaseGraph(
        sample_id=sample_id,
        family=sample["family"],
        business_id=sample["business_id"],
        scope_type=sample["scope_type"],
        split=split,
        fold=fold,
        crs=truth_crs,
        roads=roads,
        labels=labels,
        edges=edges,
        input_artifacts=input_artifacts,
        truth_count=len(truth),
        accounted_truth_count=accounted,
        uncovered_truth_ids=uncovered,
        target_relation_found=target_found,
        anomalies=anomalies,
    )


def _normalization(graphs: list[_CaseGraph]) -> tuple[np.ndarray, np.ndarray, int]:
    train_rows = [
        road.feature
        for graph in graphs
        if graph.split == "train"
        for index, road in enumerate(graph.roads)
        if index not in graph.guarded_out
    ]
    if not train_rows:
        raise ValueError("no train candidates remain after entity guard")
    matrix = np.vstack(train_rows)
    mean = matrix.mean(axis=0)
    std = matrix.std(axis=0)
    std[std < 1.0e-8] = 1.0
    return mean, std, len(train_rows)


def _safe_graph_name(sample_id: str) -> str:
    import hashlib

    return hashlib.sha256(sample_id.encode("utf-8")).hexdigest()[:20] + ".npz"


def _write_graphs(
    run_root: Path,
    graphs: list[_CaseGraph],
    mean: np.ndarray,
    std: np.ndarray,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    graph_root = run_root / "graphs"
    graph_root.mkdir()
    graph_index: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    for graph in graphs:
        raw_count = len(graph.roads)
        kept = [index for index in range(len(graph.roads)) if index not in graph.guarded_out]
        remap = {old: new for new, old in enumerate(kept)}
        raw_edge_pairs = sorted(graph.edges)
        raw_edge_index = np.asarray(raw_edge_pairs, dtype=np.int64).T if raw_edge_pairs else np.empty((2, 0), dtype=np.int64)
        edge_pairs = sorted((remap[left], remap[right]) for left, right in graph.edges if left in remap and right in remap)
        edge_index = np.asarray(edge_pairs, dtype=np.int64).T if edge_pairs else np.empty((2, 0), dtype=np.int64)
        raw_x = np.vstack([road.feature for road in graph.roads]).astype(np.float32) if graph.roads else np.empty((0, len(mean)), dtype=np.float32)
        raw_operation = np.asarray([OPERATION_TO_INDEX[label.operation] for label in graph.labels], dtype=np.int64)
        raw_weight = np.asarray([label.label_weight for label in graph.labels], dtype=np.float32)
        raw_direction = np.asarray([label.direction_values[0] if label.direction_values else -1 for label in graph.labels], dtype=np.int64)
        raw_source = np.asarray([label.source_values[0] if label.source_values else -1 for label in graph.labels], dtype=np.int64)
        raw_split_fractions = np.zeros((raw_count, 2), dtype=np.float32)
        raw_split_fraction_mask = np.zeros((raw_count, 2), dtype=np.float32)
        raw_child_geometry = np.zeros((raw_count, 3, graph.labels[0].child_geometry.shape[1], 2), dtype=np.float32)
        raw_child_mask = np.zeros((raw_count, 3), dtype=np.float32)
        for old_index, label in enumerate(graph.labels):
            label = graph.labels[old_index]
            for position, value in enumerate(label.split_fractions[:2]):
                raw_split_fractions[old_index, position] = value
                if label.split_fraction_valid:
                    raw_split_fraction_mask[old_index, position] = 1.0
            raw_child_geometry[old_index] = label.child_geometry
            raw_child_mask[old_index] = label.child_mask
        fixed_keep_mask = np.asarray([index in remap for index in range(raw_count)], dtype=np.bool_)
        x = ((raw_x[kept] - mean) / std).astype(np.float32) if kept else np.empty((0, len(mean)), dtype=np.float32)
        operation = raw_operation[kept]
        weight = raw_weight[kept]
        direction = raw_direction[kept]
        source = raw_source[kept]
        split_fractions = raw_split_fractions[kept]
        split_fraction_mask = raw_split_fraction_mask[kept]
        child_geometry = raw_child_geometry[kept]
        child_mask = raw_child_mask[kept]
        graph_name = _safe_graph_name(graph.sample_id)
        graph_path = graph_root / graph_name
        np.savez_compressed(
            graph_path,
            x=x,
            edge_index=edge_index,
            operation=operation,
            weight=weight,
            direction=direction,
            source=source,
            split_fractions=split_fractions,
            split_fraction_mask=split_fraction_mask,
            child_geometry=child_geometry,
            child_mask=child_mask,
            raw_x=raw_x,
            raw_edge_index=raw_edge_index,
            raw_operation=raw_operation,
            raw_weight=raw_weight,
            raw_direction=raw_direction,
            raw_source=raw_source,
            raw_split_fractions=raw_split_fractions,
            raw_split_fraction_mask=raw_split_fraction_mask,
            raw_child_geometry=raw_child_geometry,
            raw_child_mask=raw_child_mask,
            fixed_keep_mask=fixed_keep_mask,
        )
        graph_index.append(
            {
                "sample_id": graph.sample_id,
                "family": graph.family,
                "business_id": graph.business_id,
                "scope_type": graph.scope_type,
                "split": graph.split,
                "fold": graph.fold,
                "graph_path": str(graph_path.resolve()),
                "graph_sha256": sha256_file(graph_path),
                "candidate_count_before_guard": len(graph.roads),
                "candidate_count": len(kept),
                "edge_count": int(edge_index.shape[1]),
                "edge_count_before_guard": int(raw_edge_index.shape[1]),
                "truth_count": graph.truth_count,
                "accounted_truth_count": graph.accounted_truth_count,
                "uncovered_truth_ids": graph.uncovered_truth_ids,
                "target_relation_found": graph.target_relation_found,
                "crs": graph.crs,
            }
        )
        for old_index, road in enumerate(graph.roads):
            label = graph.labels[old_index]
            guarded = old_index in graph.guarded_out
            row_index = remap.get(old_index, -1)
            candidate_rows.append(
                {
                    "sample_id": graph.sample_id,
                    "family": graph.family,
                    "business_id": graph.business_id,
                    "split": graph.split,
                    "fold": graph.fold,
                    "road_id": road.road_id,
                    "source_role": road.source_role,
                    "graph_path": str(graph_path.resolve()),
                    "row_index_raw": old_index,
                    "row_index": row_index,
                    "guarded_out": guarded,
                    "direct_guard_overlap": old_index in graph.direct_guarded_out,
                    "feature_vector_sha256": hashlib.sha256(road.feature.tobytes()).hexdigest(),
                }
            )
            label_rows.append(
                {
                    "sample_id": graph.sample_id,
                    "road_id": road.road_id,
                    "split": graph.split,
                    "fold": graph.fold,
                    "operation": label.operation,
                    "output_road_ids": label.output_road_ids,
                    "direction_values": label.direction_values,
                    "source_values": label.source_values,
                    "split_fractions": label.split_fractions,
                    "split_fraction_valid": label.split_fraction_valid,
                    "target_scope": label.target_scope,
                    "label_weight": label.label_weight,
                    "guarded_out": guarded,
                }
            )
    return graph_index, candidate_rows, label_rows


def _report(summary: dict[str, Any]) -> str:
    return f"""# P05 M1 数据集报告

## 结论

- 冻结 RoadGraph Case：{summary['sample_count']}；train/validation/test：{summary['split_counts']}。
- 候选 Road：门禁前 {summary['candidate_count_before_guard']}，门禁后 {summary['candidate_count']}。
- operation truth coverage：{summary['operation_truth_coverage']:.4%}；uncovered truth：{summary['uncovered_truth_count']}。
- 实体泄漏直接移除：{summary['direct_entity_overlap_removed']}；含一跳邻域共移除：{summary['entity_guard_removed']}。
- 门禁后跨 split Road ID 交集：{summary['post_guard_cross_split_overlap']}。
- 缺目标 Segment relation：{summary['missing_target_relation_count']} 个，仅保留 0.3 上下文监督。
- 特征维度：{summary['feature_dim']}；图边：{summary['edge_count']}。

## 边界

T06 Road/Node/relation 仅用于监督与评价，未进入模型特征。canonical ID 只用于 lineage、label join 和实体泄漏审计。所有输入保持只读，`silent_fix=false`。
"""


def build_m1_dataset(config: M1DatasetConfig) -> dict[str, Any]:
    started = time.perf_counter()
    started_at = datetime.now(timezone.utc)
    m0_root = normalize_runtime_path(config.m0_run_root).resolve(strict=True)
    output_root = normalize_runtime_path(config.output_root).resolve(strict=False)
    output_root.mkdir(parents=True, exist_ok=True)
    run_root = output_root / config.run_id
    run_root.mkdir(parents=False, exist_ok=False)
    m0_manifest, m0_paths = _verify_m0_run(m0_root, strict_hashes=config.strict_hashes)
    samples = {
        row["sample_id"]: row
        for row in _read_csv(m0_paths["samples"])
        if bool(json.loads(row["task_mask"]).get("road_graph"))
    }
    split_rows = _read_csv(m0_paths["split"])
    split_by_sample = {row["sample_id"]: row["split"] for row in split_rows}
    fold_by_sample = {row["sample_id"]: int(row["fold"]) for row in split_rows}
    artifacts_by_sample: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for row in _read_csv(m0_paths["artifacts"]):
        if row["sample_id"] in samples:
            artifacts_by_sample[row["sample_id"]][row["role"]] = row
    graphs: list[_CaseGraph] = []
    for sample_id in sorted(samples):
        if sample_id not in split_by_sample:
            raise ValueError(f"M0 split missing sample: {sample_id}")
        graphs.append(
            _load_case_graph(
                samples[sample_id],
                artifacts_by_sample[sample_id],
                split_by_sample[sample_id],
                fold_by_sample[sample_id],
                config,
            )
        )
    guard_audit = _apply_entity_guard(graphs, config.entity_guard_hops)
    mean, std, normalization_train_count = _normalization(graphs)
    feature_names = _feature_names(config.polyline_points)
    if len(feature_names) != len(mean):
        raise AssertionError(f"feature schema mismatch: names={len(feature_names)} values={len(mean)}")
    graph_index, candidate_rows, label_rows = _write_graphs(run_root, graphs, mean, std)
    input_artifacts = [item for graph in graphs for item in graph.input_artifacts]
    anomalies = [
        {"sample_id": graph.sample_id, "family": graph.family, "business_id": graph.business_id, **item}
        for graph in graphs
        for item in graph.anomalies
    ]
    split_counts = Counter(graph.split for graph in graphs)
    fold_counts = Counter(str(graph.fold) for graph in graphs)
    candidate_count_before = sum(len(graph.roads) for graph in graphs)
    candidate_count = sum(len(graph.roads) - len(graph.guarded_out) for graph in graphs)
    truth_count = sum(graph.truth_count for graph in graphs)
    accounted_truth_count = sum(graph.accounted_truth_count for graph in graphs)
    ids_by_split: dict[str, set[str]] = defaultdict(set)
    for graph in graphs:
        ids_by_split[graph.split].update(road.road_id for index, road in enumerate(graph.roads) if index not in graph.guarded_out)
    post_guard_overlap = {
        f"{left}__{right}": len(ids_by_split[left] & ids_by_split[right])
        for left, right in (("train", "validation"), ("train", "test"), ("validation", "test"))
    }
    operation_counts = Counter(
        graph.labels[index].operation
        for graph in graphs
        for index in range(len(graph.roads))
        if index not in graph.guarded_out
    )
    summary = {
        "schema_version": "p05-m1-dataset-summary-v1",
        "sample_count": len(graphs),
        "split_counts": dict(sorted(split_counts.items())),
        "fold_counts": dict(sorted(fold_counts.items())),
        "candidate_count_before_guard": candidate_count_before,
        "candidate_count": candidate_count,
        "operation_counts": dict(sorted(operation_counts.items())),
        "truth_count": truth_count,
        "accounted_truth_count": accounted_truth_count,
        "uncovered_truth_count": truth_count - accounted_truth_count,
        "operation_truth_coverage": accounted_truth_count / truth_count if truth_count else 0.0,
        "direct_entity_overlap_removed": sum(len(graph.direct_guarded_out) for graph in graphs),
        "entity_guard_removed": sum(len(graph.guarded_out) for graph in graphs),
        "post_guard_cross_split_overlap": post_guard_overlap,
        "missing_target_relation_count": sum(not graph.target_relation_found for graph in graphs),
        "feature_dim": len(feature_names),
        "edge_count": sum(item["edge_count"] for item in graph_index),
        "normalization_train_candidate_count": normalization_train_count,
        "duration_seconds": time.perf_counter() - started,
    }
    paths = {
        "input_artifacts": run_root / "p05_m1_input_artifacts.csv",
        "candidates": run_root / "p05_m1_candidate_roads.csv",
        "labels": run_root / "p05_m1_operation_labels.csv",
        "graph_index": run_root / "p05_m1_graph_index.json",
        "entity_guard": run_root / "p05_m1_entity_leakage_audit.csv",
        "anomalies": run_root / "p05_m1_anomalies.csv",
        "normalization": run_root / "p05_m1_normalization.json",
        "summary": run_root / "p05_m1_dataset_summary.json",
        "report": run_root / "p05_m1_dataset_report.md",
    }
    write_csv(paths["input_artifacts"], input_artifacts, ["sample_id", "role", "path", "sha256", "label_only", "crs", "feature_count", "schema"])
    write_csv(paths["candidates"], candidate_rows, ["sample_id", "family", "business_id", "split", "fold", "road_id", "source_role", "graph_path", "row_index_raw", "row_index", "guarded_out", "direct_guard_overlap", "feature_vector_sha256"])
    write_csv(paths["labels"], label_rows, ["sample_id", "road_id", "split", "fold", "operation", "output_road_ids", "direction_values", "source_values", "split_fractions", "split_fraction_valid", "target_scope", "label_weight", "guarded_out"])
    write_json(paths["graph_index"], {"schema_version": "p05-m1-graph-index-v1", "graphs": graph_index})
    write_csv(paths["entity_guard"], guard_audit, ["sample_id", "split", "road_id", "source_role", "decision", "owner_split", "entity_guard_hops"])
    write_csv(paths["anomalies"], anomalies, ["sample_id", "family", "business_id", "category", "role", "road_id", "detail", "examples"])
    write_json(
        paths["normalization"],
        {
            "schema_version": "p05-m1-normalization-v1",
            "source_split": "train",
            "candidate_count": normalization_train_count,
            "feature_names": feature_names,
            "mean": mean.tolist(),
            "std": std.tolist(),
        },
    )
    write_json(paths["summary"], summary)
    paths["report"].write_text(_report(summary), encoding="utf-8")
    manifest = {
        "schema_version": "p05-m1-dataset-manifest-v1",
        "module_id": "p05_neural_road_generation",
        "run_id": config.run_id,
        "status": "dataset_ready",
        "started_at_utc": started_at.isoformat(),
        "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "m0_run_root": str(m0_root),
        "m0_manifest_sha256": sha256_file(m0_root / "p05_m0_manifest.json"),
        "m0_run_id": m0_manifest.get("run_id"),
        "config": {
            "seed": config.seed,
            "polyline_points": config.polyline_points,
            "entity_guard_hops": config.entity_guard_hops,
            "neighbor_distance_m": config.neighbor_distance_m,
            "strict_hashes": config.strict_hashes,
        },
        "environment": _environment(),
        "performance": {"duration_seconds": summary["duration_seconds"]},
        "silent_fix": False,
        "outputs": {name: output_record(path) for name, path in paths.items()},
        "graph_outputs": {item["sample_id"]: {"path": item["graph_path"], "sha256": item["graph_sha256"]} for item in graph_index},
    }
    manifest_path = run_root / "p05_m1_dataset_manifest.json"
    write_json(manifest_path, manifest)
    summary["manifest_sha256"] = sha256_file(manifest_path)
    return summary


__all__ = ["OPERATION_NAMES", "build_m1_dataset"]
