from __future__ import annotations

import math
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import fiona
from pyproj import CRS
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.utils.field_names import FieldNameConflictError, PropertyLookup


@dataclass(frozen=True)
class EvaluationConfig:
    road_geometry_fallback_m: float = 2.0
    node_geometry_fallback_m: float = 1.0
    geometry_tolerance_m: float = 0.01
    chamfer_samples: int = 20


@dataclass(frozen=True)
class _Feature:
    feature_id: str
    geometry: BaseGeometry
    properties: dict[str, Any]


@dataclass(frozen=True)
class _VectorData:
    path: str
    crs: CRS | None
    features: tuple[_Feature, ...]
    duplicates: tuple[str, ...]
    read_failures: tuple[str, ...]


def _id_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _layer_name(path: Path) -> str | None:
    layers = fiona.listlayers(path)
    if not layers:
        raise ValueError(f"no readable vector layer: {path}")
    if len(layers) == 1:
        return layers[0]
    return sorted(layers, key=str.casefold)[0]


def _read_vector(path: Path, *, kind: str) -> _VectorData:
    failures: list[str] = []
    features: list[_Feature] = []
    counts: Counter[str] = Counter()
    layer = _layer_name(path)
    with fiona.open(path, layer=layer) as source:
        raw_crs = source.crs_wkt or source.crs
        crs = CRS.from_user_input(raw_crs) if raw_crs else None
        for row_index, raw in enumerate(source):
            properties = dict(raw.get("properties") or {})
            try:
                lookup = PropertyLookup(properties)
                feature_id = _id_text(lookup.require("id", label=f"{kind}.id"))
            except (FieldNameConflictError, KeyError) as exc:
                failures.append(f"row {row_index}: {exc}")
                feature_id = f"__invalid_{row_index}"
            if not feature_id:
                failures.append(f"row {row_index}: empty {kind}.id")
                feature_id = f"__empty_{row_index}"
            raw_geometry = raw.get("geometry")
            if raw_geometry is None:
                failures.append(f"{kind} {feature_id}: missing geometry")
                continue
            geometry = shape(raw_geometry)
            if geometry.is_empty:
                failures.append(f"{kind} {feature_id}: empty geometry")
                continue
            counts[feature_id] += 1
            features.append(_Feature(feature_id, geometry, properties))
    return _VectorData(
        path=str(path.resolve()),
        crs=crs,
        features=tuple(features),
        duplicates=tuple(sorted(feature_id for feature_id, count in counts.items() if count > 1)),
        read_failures=tuple(failures),
    )


def _crs_equal(first: CRS | None, second: CRS | None) -> bool:
    return first is not None and second is not None and first.equals(second)


def _feature_map(data: _VectorData) -> dict[str, _Feature]:
    result: dict[str, _Feature] = {}
    for feature in data.features:
        result.setdefault(feature.feature_id, feature)
    return result


def _greedy_geometry_match(
    candidate: dict[str, _Feature],
    truth: dict[str, _Feature],
    exact_ids: set[str],
    *,
    threshold: float,
    distance_kind: str,
) -> tuple[list[tuple[str, str, str, float]], set[str], set[str]]:
    matches = [(feature_id, feature_id, "id", 0.0) for feature_id in sorted(exact_ids)]
    unmatched_candidate = set(candidate) - exact_ids
    unmatched_truth = set(truth) - exact_ids
    options: list[tuple[float, str, str]] = []
    for candidate_id in sorted(unmatched_candidate):
        for truth_id in sorted(unmatched_truth):
            if distance_kind == "hausdorff":
                distance = candidate[candidate_id].geometry.hausdorff_distance(truth[truth_id].geometry)
            else:
                distance = candidate[candidate_id].geometry.distance(truth[truth_id].geometry)
            if math.isfinite(distance) and distance <= threshold:
                options.append((float(distance), candidate_id, truth_id))
    used_candidate: set[str] = set()
    used_truth: set[str] = set()
    for distance, candidate_id, truth_id in sorted(options):
        if candidate_id in used_candidate or truth_id in used_truth:
            continue
        used_candidate.add(candidate_id)
        used_truth.add(truth_id)
        matches.append((candidate_id, truth_id, "geometry_fallback", distance))
    return matches, unmatched_candidate - used_candidate, unmatched_truth - used_truth


def _f1(matched: int, candidate_count: int, truth_count: int) -> dict[str, float]:
    precision = 1.0 if candidate_count == 0 and truth_count == 0 else matched / candidate_count if candidate_count else 0.0
    recall = 1.0 if truth_count == 0 and candidate_count == 0 else matched / truth_count if truth_count else 0.0
    score = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": score}


def _lookup(feature: _Feature, candidates: str | Iterable[str]) -> Any:
    return PropertyLookup(feature.properties).get(candidates)


def _numeric_or_text(value: Any) -> Any:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return int(number) if number.is_integer() else number


def _accuracy(values: list[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def _sample_points(geometry: BaseGeometry, count: int) -> list[BaseGeometry]:
    if count <= 1 or geometry.length == 0:
        return [geometry.representative_point()]
    return [geometry.interpolate(index / (count - 1), normalized=True) for index in range(count)]


def _chamfer(first: BaseGeometry, second: BaseGeometry, samples: int) -> float:
    first_points = _sample_points(first, samples)
    second_points = _sample_points(second, samples)
    first_mean = sum(point.distance(second) for point in first_points) / len(first_points)
    second_mean = sum(point.distance(first) for point in second_points) / len(second_points)
    return float((first_mean + second_mean) / 2.0)


def _stats(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"mean": None, "max": None}
    return {"mean": sum(values) / len(values), "max": max(values)}


def _road_endpoint(feature: _Feature, name: str) -> str:
    aliases = (name, "startnodeid") if name == "snodeid" else (name, "endnodeid")
    return _id_text(_lookup(feature, aliases))


def _directed_edges(roads: Iterable[_Feature], node_map: dict[str, str] | None = None) -> tuple[Counter[tuple[str, str]], list[str]]:
    edges: Counter[tuple[str, str]] = Counter()
    failures: list[str] = []
    mapping = node_map or {}
    for road in roads:
        start_raw = _road_endpoint(road, "snodeid")
        end_raw = _road_endpoint(road, "enodeid")
        start = mapping.get(start_raw, start_raw)
        end = mapping.get(end_raw, end_raw)
        direction_raw = _numeric_or_text(_lookup(road, "direction"))
        if not start or not end:
            failures.append(f"road {road.feature_id}: missing snodeid/enodeid")
            continue
        if direction_raw in {0, 1, 2}:
            edges[(start, end)] += 1
        if direction_raw in {0, 1, 3}:
            edges[(end, start)] += 1
        if direction_raw not in {0, 1, 2, 3}:
            failures.append(f"road {road.feature_id}: unsupported direction {direction_raw!r}")
    return edges, failures


def _multiset_f1(candidate: Counter[tuple[str, str]], truth: Counter[tuple[str, str]]) -> dict[str, float]:
    matched = sum((candidate & truth).values())
    return _f1(matched, sum(candidate.values()), sum(truth.values()))


def _missing_endpoint_references(roads: Iterable[_Feature], nodes: dict[str, _Feature]) -> list[str]:
    missing: list[str] = []
    for road in roads:
        for field in ("snodeid", "enodeid"):
            node_id = _road_endpoint(road, field)
            if not node_id or node_id not in nodes:
                missing.append(f"road {road.feature_id}: {field}={node_id!r} does not reference an existing Node")
    return missing


def evaluate_frcsd(
    candidate_road_path: Path,
    candidate_node_path: Path,
    truth_road_path: Path,
    truth_node_path: Path,
    *,
    config: EvaluationConfig | None = None,
) -> dict[str, Any]:
    settings = config or EvaluationConfig()
    started = time.perf_counter()
    paths = (candidate_road_path, candidate_node_path, truth_road_path, truth_node_path)
    for path in paths:
        if not Path(path).is_file():
            raise FileNotFoundError(path)
    candidate_roads = _read_vector(Path(candidate_road_path), kind="Road")
    candidate_nodes = _read_vector(Path(candidate_node_path), kind="Node")
    truth_roads = _read_vector(Path(truth_road_path), kind="Road")
    truth_nodes = _read_vector(Path(truth_node_path), kind="Node")
    hard_failures: list[str] = []
    for label, data in (
        ("candidate Road", candidate_roads),
        ("candidate Node", candidate_nodes),
        ("truth Road", truth_roads),
        ("truth Node", truth_nodes),
    ):
        if data.crs is None:
            hard_failures.append(f"{label}: CRS is missing")
        if data.duplicates:
            hard_failures.append(f"{label}: duplicate ids {list(data.duplicates)}")
        hard_failures.extend(f"{label}: {failure}" for failure in data.read_failures)
    crs_compatible = _crs_equal(candidate_roads.crs, truth_roads.crs) and _crs_equal(candidate_nodes.crs, truth_nodes.crs)
    cross_layer_crs = _crs_equal(candidate_roads.crs, candidate_nodes.crs) and _crs_equal(truth_roads.crs, truth_nodes.crs)
    if not crs_compatible:
        hard_failures.append("candidate and truth CRS differ")
    if not cross_layer_crs:
        hard_failures.append("Road and Node CRS differ within one graph")

    candidate_road_map = _feature_map(candidate_roads)
    truth_road_map = _feature_map(truth_roads)
    candidate_node_map = _feature_map(candidate_nodes)
    truth_node_map = _feature_map(truth_nodes)
    node_matches, unmatched_candidate_nodes, unmatched_truth_nodes = _greedy_geometry_match(
        candidate_node_map,
        truth_node_map,
        set(candidate_node_map) & set(truth_node_map),
        threshold=settings.node_geometry_fallback_m,
        distance_kind="distance",
    )
    road_matches, unmatched_candidate_roads, unmatched_truth_roads = _greedy_geometry_match(
        candidate_road_map,
        truth_road_map,
        set(candidate_road_map) & set(truth_road_map),
        threshold=settings.road_geometry_fallback_m,
        distance_kind="hausdorff",
    )
    node_id_map = {candidate_id: truth_id for candidate_id, truth_id, _, _ in node_matches}

    direction_equal: list[bool] = []
    source_equal: list[bool] = []
    endpoint_semantic_equal: list[bool] = []
    hausdorff_values: list[float] = []
    chamfer_values: list[float] = []
    fallback_road_matches: list[dict[str, Any]] = []
    for candidate_id, truth_id, method, match_distance in road_matches:
        candidate = candidate_road_map[candidate_id]
        truth = truth_road_map[truth_id]
        direction_equal.append(_numeric_or_text(_lookup(candidate, "direction")) == _numeric_or_text(_lookup(truth, "direction")))
        source_equal.append(_numeric_or_text(_lookup(candidate, "source")) == _numeric_or_text(_lookup(truth, "source")))
        candidate_start = node_id_map.get(_road_endpoint(candidate, "snodeid"), _road_endpoint(candidate, "snodeid"))
        candidate_end = node_id_map.get(_road_endpoint(candidate, "enodeid"), _road_endpoint(candidate, "enodeid"))
        endpoint_semantic_equal.append(candidate_start == _road_endpoint(truth, "snodeid") and candidate_end == _road_endpoint(truth, "enodeid"))
        hausdorff_values.append(float(candidate.geometry.hausdorff_distance(truth.geometry)))
        chamfer_values.append(_chamfer(candidate.geometry, truth.geometry, settings.chamfer_samples))
        if method != "id":
            fallback_road_matches.append(
                {"candidate_id": candidate_id, "truth_id": truth_id, "method": method, "match_distance_m": match_distance}
            )

    node_geometry_values = [
        float(candidate_node_map[candidate_id].geometry.distance(truth_node_map[truth_id].geometry))
        for candidate_id, truth_id, _, _ in node_matches
    ]
    candidate_missing_endpoints = _missing_endpoint_references(candidate_roads.features, candidate_node_map)
    truth_missing_endpoints = _missing_endpoint_references(truth_roads.features, truth_node_map)
    hard_failures.extend(f"candidate topology: {item}" for item in candidate_missing_endpoints)
    hard_failures.extend(f"truth topology: {item}" for item in truth_missing_endpoints)
    candidate_edges, candidate_direction_failures = _directed_edges(candidate_roads.features, node_id_map)
    truth_edges, truth_direction_failures = _directed_edges(truth_roads.features)
    hard_failures.extend(f"candidate topology: {item}" for item in candidate_direction_failures)
    hard_failures.extend(f"truth topology: {item}" for item in truth_direction_failures)

    road_object = _f1(len(road_matches), len(candidate_road_map), len(truth_road_map))
    node_object = _f1(len(node_matches), len(candidate_node_map), len(truth_node_map))
    directed_topology = _multiset_f1(candidate_edges, truth_edges)
    direction_accuracy = _accuracy(direction_equal)
    source_accuracy = _accuracy(source_equal)
    endpoint_accuracy = _accuracy(endpoint_semantic_equal)
    hausdorff = _stats(hausdorff_values)
    chamfer = _stats(chamfer_values)
    node_geometry = _stats(node_geometry_values)
    strict_metric_pass = all(
        (
            road_object["f1"] == 1.0,
            node_object["f1"] == 1.0,
            directed_topology["f1"] == 1.0,
            direction_accuracy == 1.0,
            source_accuracy == 1.0,
            endpoint_accuracy == 1.0,
            (hausdorff["max"] or 0.0) <= settings.geometry_tolerance_m,
            (node_geometry["max"] or 0.0) <= settings.geometry_tolerance_m,
        )
    )
    if directed_topology["f1"] != 1.0:
        hard_failures.append("directed topology differs from truth")

    return {
        "schema_version": "p05-m0-evaluation-v1",
        "candidate": {"road": candidate_roads.path, "node": candidate_nodes.path},
        "truth": {"road": truth_roads.path, "node": truth_nodes.path},
        "crs": {
            "candidate_road": candidate_roads.crs.to_string() if candidate_roads.crs else None,
            "candidate_node": candidate_nodes.crs.to_string() if candidate_nodes.crs else None,
            "truth_road": truth_roads.crs.to_string() if truth_roads.crs else None,
            "truth_node": truth_nodes.crs.to_string() if truth_nodes.crs else None,
            "compatible": crs_compatible and cross_layer_crs,
        },
        "counts": {
            "candidate_roads": len(candidate_road_map),
            "truth_roads": len(truth_road_map),
            "candidate_nodes": len(candidate_node_map),
            "truth_nodes": len(truth_node_map),
            "matched_roads": len(road_matches),
            "matched_nodes": len(node_matches),
        },
        "road_object": road_object,
        "node_object": node_object,
        "attributes": {
            "direction_accuracy": direction_accuracy,
            "source_accuracy": source_accuracy,
            "endpoint_semantic_accuracy": endpoint_accuracy,
        },
        "geometry_m": {
            "road_hausdorff": hausdorff,
            "road_chamfer": chamfer,
            "node_distance": node_geometry,
        },
        "directed_topology": directed_topology,
        "unmatched": {
            "candidate_road_ids": sorted(unmatched_candidate_roads),
            "truth_road_ids": sorted(unmatched_truth_roads),
            "candidate_node_ids": sorted(unmatched_candidate_nodes),
            "truth_node_ids": sorted(unmatched_truth_nodes),
        },
        "geometry_fallback_road_matches": fallback_road_matches,
        "hard_failures": sorted(set(hard_failures)),
        "overall_passed": not hard_failures and strict_metric_pass,
        "duration_seconds": time.perf_counter() - started,
    }


__all__ = ["EvaluationConfig", "evaluate_frcsd"]
