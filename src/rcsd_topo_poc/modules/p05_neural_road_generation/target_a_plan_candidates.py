from __future__ import annotations

import json
import math
import time
from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona
import networkx as nx
import numpy as np
from shapely.geometry import LineString, Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    canonical_sha256,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
    TargetACaseBundle,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_internal_connector_candidates import (
    enumerate_internal_connector_trees,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_arms import (
    ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
    build_ordinary_plan_arm_rows,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_members import (
    ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,
    build_ordinary_plan_member_rows,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


PLAN_CANDIDATE_THRESHOLDS_M = (6.0, 12.0, 25.0, 50.0, 80.0)
SEMANTIC_JUNCTION_KINDS = frozenset({4, 8, 16, 64, 128, 2048})


@dataclass(frozen=True)
class _Road:
    road_id: str
    start_node_id: str
    end_node_id: str
    direction: int
    function_class: int
    geometry: BaseGeometry

    @property
    def length_m(self) -> float:
        return max(float(self.geometry.length), 0.01)


@dataclass(frozen=True)
class _Plan:
    decision: str
    road_ids: tuple[str, ...]
    road_roles: tuple[tuple[str, str], ...]
    generator: str
    threshold_m: float
    hard_valid: bool
    connector_tree_proof: Mapping[str, Any] | None = None


def build_truth_free_plan_candidate_store(
    bundles: Sequence[TargetACaseBundle],
    *,
    output_root: Path,
    run_id: str,
    max_candidates_per_segment: int = 32,
) -> Path:
    """Build complete ordinary/AR Road-plan alternatives from raw evidence only."""
    started = time.perf_counter()
    if not bundles:
        raise ValueError("Target A plan candidates require Case bundles")
    if max_candidates_per_segment < 3:
        raise ValueError("plan candidate limit must retain KEEP/USE/ABSTAIN")
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    root.mkdir(parents=True)
    group_path = root / "inference_plan_groups.jsonl"
    case_rows: list[dict[str, Any]] = []
    lineage_rows: list[dict[str, Any]] = []
    group_count = 0
    candidate_count = 0
    member_count = 0
    arm_count = 0
    decision_counts: Counter[str] = Counter()
    generator_counts: Counter[str] = Counter()
    crs_counts: Counter[str] = Counter()
    case_seconds: list[float] = []
    with group_path.open("w", encoding="utf-8", newline="\n") as output:
        for bundle in sorted(bundles, key=lambda row: row.case_key):
            case_started = time.perf_counter()
            inputs = _case_input_paths(bundle)
            roads, road_crs = _read_roads(inputs["raw_rcsd_roads"])
            nodes, node_crs, _ = _read_points(inputs["raw_rcsd_nodes"])
            swsd_roads, swsd_road_crs = _read_roads(bundle.t01_roads)
            swsd_nodes, swsd_node_crs, semantic_anchor_by_node = _read_points(
                bundle.t01_nodes
            )
            segments, segment_crs = _read_segments(bundle.t01_segment)
            crs_values = {
                road_crs,
                node_crs,
                swsd_road_crs,
                swsd_node_crs,
                segment_crs,
            }
            if crs_values != {"EPSG:3857"}:
                raise ValueError(
                    f"{bundle.case_key}: Target A candidate CRS differs {crs_values}"
                )
            crs_counts.update(crs_values)
            road_tree = STRtree([row.geometry for row in roads])
            node_ids = list(nodes)
            node_geometries = [nodes[node_id] for node_id in node_ids]
            node_tree = STRtree(node_geometries)
            case_candidate_count = 0
            case_member_count = 0
            case_arm_count = 0
            for segment in segments:
                plans = _segment_plans(
                    segment=segment,
                    roads=roads,
                    road_tree=road_tree,
                    raw_nodes=nodes,
                    raw_node_ids=node_ids,
                    raw_node_geometries=node_geometries,
                    raw_node_tree=node_tree,
                    swsd_nodes=swsd_nodes,
                    max_candidates=max_candidates_per_segment,
                )
                candidate_rows = [
                    _plan_dict(
                        bundle.case_key,
                        str(segment["segment_id"]),
                        plan,
                        segment["geometry"],
                        roads,
                        swsd_roads,
                        nodes,
                        swsd_nodes,
                        segment["pair_node_ids"],
                    )
                    for plan in plans
                ]
                row = {
                    "schema_version": TARGET_A_SCHEMA_VERSION,
                    "case_key": bundle.case_key,
                    "family": bundle.family,
                    "business_id": bundle.business_id,
                    "segment_id": segment["segment_id"],
                    "segment_type": segment["segment_type"],
                    "pair_node_ids": list(segment["pair_node_ids"]),
                    "arm_anchor_ids": [
                        semantic_anchor_by_node.get(node_id, "")
                        for node_id in (
                            segment["pair_node_ids"][0],
                            segment["pair_node_ids"][-1],
                        )
                    ]
                    if segment["pair_node_ids"]
                    else [],
                    "junc_node_ids": list(segment["junc_node_ids"]),
                    "junc_node_count": len(segment["junc_node_ids"]),
                    "required_anchor_ids": sorted(
                        {
                            semantic_anchor_by_node[node_id]
                            for node_id in (
                                *segment["pair_node_ids"],
                                *segment["junc_node_ids"],
                            )
                            if node_id in semantic_anchor_by_node
                        }
                    ),
                    "object_features": _segment_features(segment),
                    "candidates": candidate_rows,
                    "feature_uses_truth": False,
                    "truth_derived_candidate_count": 0,
                    "terminal_input_count": 0,
                    "absolute_coordinate_feature_count": 0,
                    "raw_id_embedding_count": 0,
                }
                output.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                group_count += 1
                candidate_count += len(plans)
                case_candidate_count += len(plans)
                plan_member_count = sum(
                    len(candidate["road_members"])
                    for candidate in candidate_rows
                )
                member_count += plan_member_count
                case_member_count += plan_member_count
                plan_arm_count = sum(
                    len(candidate["arm_rows"])
                    for candidate in candidate_rows
                )
                arm_count += plan_arm_count
                case_arm_count += plan_arm_count
                decision_counts.update(plan.decision for plan in plans)
                generator_counts.update(plan.generator for plan in plans)
            case_rows.append(
                {
                    "case_key": bundle.case_key,
                    "segment_count": len(segments),
                    "raw_rcsd_road_count": len(roads),
                    "raw_rcsd_node_count": len(nodes),
                    "t01_swsd_road_count": len(swsd_roads),
                    "candidate_count": case_candidate_count,
                    "member_count": case_member_count,
                    "arm_count": case_arm_count,
                    "wall_seconds": time.perf_counter() - case_started,
                }
            )
            case_seconds.append(time.perf_counter() - case_started)
            for role, path in (
                ("t01_segment", bundle.t01_segment),
                ("t01_nodes", bundle.t01_nodes),
                ("raw_rcsd_roads", inputs["raw_rcsd_roads"]),
                ("raw_rcsd_nodes", inputs["raw_rcsd_nodes"]),
                ("t07_rcsd_intersection", inputs["t07_rcsd_intersection"]),
            ):
                lineage_rows.append(
                    {
                        "case_key": bundle.case_key,
                        "role": role,
                        "path": str(path.resolve()),
                        "sha256": sha256_file(path),
                        "label_only": False,
                        "truth_derived": False,
                    }
                )
    _write_jsonl(root / "case_performance.jsonl", case_rows)
    _write_jsonl(root / "input_lineage.jsonl", lineage_rows)
    manifest = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "TRUTH_FREE_PLAN_CANDIDATES",
        "case_count": len(case_rows),
        "group_count": group_count,
        "candidate_count": candidate_count,
        "member_count": member_count,
        "member_base_feature_dim": ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,
        "arm_count": arm_count,
        "arm_base_feature_dim": ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
        "max_candidates_per_segment": max_candidates_per_segment,
        "thresholds_m": list(PLAN_CANDIDATE_THRESHOLDS_M),
        "decision_counts": dict(sorted(decision_counts.items())),
        "generator_counts": dict(sorted(generator_counts.items())),
        "internal_connector_tree_candidate_count": generator_counts.get(
            "INTERNAL_CONNECTOR_TREE",
            0,
        ),
        "legacy_unproven_corridor_component_count": generator_counts.get(
            "CORRIDOR_COMPONENT",
            0,
        ),
        "crs_counts": dict(sorted(crs_counts.items())),
        "truth_input_count": 0,
        "truth_derived_candidate_count": 0,
        "terminal_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "raw_id_embedding_count": 0,
        "content_repair": False,
        "silent_fix": False,
        "skeleton_mutation_count": 0,
        "performance": {
            "wall_seconds": time.perf_counter() - started,
            "case_p95_seconds": _percentile(case_seconds, 0.95),
            "case_max_seconds": max(case_seconds, default=0.0),
        },
        "outputs": {
            "groups": {
                "path": str(group_path.resolve()),
                "sha256": sha256_file(group_path),
            },
            "case_performance": {
                "path": str((root / "case_performance.jsonl").resolve()),
                "sha256": sha256_file(root / "case_performance.jsonl"),
            },
            "input_lineage": {
                "path": str((root / "input_lineage.jsonl").resolve()),
                "sha256": sha256_file(root / "input_lineage.jsonl"),
            },
        },
        "gate_pass": (
            len(case_rows) == 51
            and group_count == 8_863
            and not any(
                (
                    decision_counts.get("KEEP_SWSD", 0) != group_count,
                    decision_counts.get("ABSTAIN", 0) != group_count,
                    generator_counts.get("CORRIDOR_COMPONENT", 0) != 0,
                )
            )
        ),
    }
    _write_json(root / "manifest.json", manifest)
    if not manifest["gate_pass"]:
        raise RuntimeError(f"Target A truth-free plan candidate gate failed: {root}")
    return root


def _segment_plans(
    *,
    segment: Mapping[str, Any],
    roads: Sequence[_Road],
    road_tree: STRtree,
    raw_nodes: Mapping[str, Point],
    raw_node_ids: Sequence[str],
    raw_node_geometries: Sequence[Point],
    raw_node_tree: STRtree,
    swsd_nodes: Mapping[str, Point],
    max_candidates: int,
) -> list[_Plan]:
    segment_geometry = segment["geometry"]
    keep_roads = tuple(sorted(set(segment["swsd_road_ids"])))
    plans: list[_Plan] = [
        _Plan(
            decision="KEEP_SWSD",
            road_ids=keep_roads,
            road_roles=tuple((road_id, "MAIN") for road_id in keep_roads),
            generator="KEEP_T01",
            threshold_m=0.0,
            hard_valid=bool(keep_roads),
        ),
        _Plan(
            decision="ABSTAIN",
            road_ids=(),
            road_roles=(),
            generator="SAFE_ABSTAIN",
            threshold_m=0.0,
            hard_valid=True,
        ),
    ]
    pair_points = [
        swsd_nodes[node_id]
        for node_id in segment["pair_node_ids"]
        if node_id in swsd_nodes
    ]
    if len(pair_points) < 2:
        pair_points = _geometry_boundary_points(segment_geometry)
    if len(pair_points) < 2:
        return plans
    start_nodes = _nearest_node_ids(
        pair_points[0],
        raw_node_ids,
        raw_node_geometries,
        raw_node_tree,
    )
    end_nodes = _nearest_node_ids(
        pair_points[-1],
        raw_node_ids,
        raw_node_geometries,
        raw_node_tree,
    )
    for threshold in PLAN_CANDIDATE_THRESHOLDS_M:
        local_indices = [
            index
            for index in _tree_indices(road_tree, segment_geometry.buffer(threshold))
            if roads[index].geometry.distance(segment_geometry) <= threshold
        ]
        if not local_indices:
            continue
        graph = _local_graph(roads, local_indices, segment_geometry)
        threshold_paths: list[tuple[str, ...]] = []
        for start_node in start_nodes:
            for end_node in end_nodes:
                path_road_ids = _shortest_path_roads(graph, start_node, end_node)
                if path_road_ids:
                    threshold_paths.append(path_road_ids)
                    plans.append(
                        _Plan(
                            decision="USE_RCSD",
                            road_ids=path_road_ids,
                            road_roles=tuple(
                                (road_id, "MAIN") for road_id in path_road_ids
                            ),
                            generator="ANCHOR_PATH",
                            threshold_m=threshold,
                            hard_valid=True,
                        )
                    )
        distinct_paths = sorted(set(threshold_paths), key=lambda row: (len(row), row))
        path_unions = [
            tuple(sorted(set(first) | set(second)))
            for first, second in combinations(distinct_paths[:6], 2)
        ]
        if distinct_paths:
            path_unions.append(
                tuple(sorted({road_id for path in distinct_paths for road_id in path}))
            )
        for union_ids in sorted(set(path_unions), key=lambda row: (len(row), row)):
            plans.append(
                _Plan(
                    decision="USE_RCSD",
                    road_ids=union_ids,
                    road_roles=tuple((road_id, "MAIN") for road_id in union_ids),
                    generator="MULTIPATH_UNION",
                    threshold_m=threshold,
                    hard_valid=True,
                )
            )
        for node_set in nx.connected_components(nx.Graph(graph)):
            if not node_set.intersection(start_nodes) or not node_set.intersection(
                end_nodes
            ):
                continue
            component_ids = tuple(
                sorted(
                    {
                        str(data["road_id"])
                        for _, _, data in graph.subgraph(node_set).edges(data=True)
                    }
                )
            )
            if not component_ids:
                continue
            main_ids = _best_component_path(
                graph,
                node_set,
                start_nodes,
                end_nodes,
            )
            component_graph = graph.subgraph(node_set).copy()
            plans.append(
                _Plan(
                    decision="USE_RCSD",
                    road_ids=component_ids,
                    road_roles=tuple(
                        (road_id, "MAIN") for road_id in component_ids
                    ),
                    generator="COMPONENT_ALL_MAIN",
                    threshold_m=threshold,
                    hard_valid=bool(main_ids),
                )
            )
            component_paths = {
                path
                for path in distinct_paths[:6]
                if set(path).issubset(component_ids)
            }
            if main_ids:
                component_paths.add(main_ids)
            for main_path in sorted(
                component_paths,
                key=lambda row: (len(row), row),
            ):
                for proof in enumerate_internal_connector_trees(
                    component_graph,
                    main_road_ids=main_path,
                    maximum_candidates=4,
                ):
                    main_set = set(proof.main_road_ids)
                    connector_set = set(proof.connector_road_ids)
                    road_ids = tuple(sorted(main_set | connector_set))
                    plans.append(
                        _Plan(
                            decision="USE_RCSD",
                            road_ids=road_ids,
                            road_roles=tuple(
                                (
                                    road_id,
                                    "INTERNAL_CONNECTOR"
                                    if road_id in connector_set
                                    else "MAIN",
                                )
                                for road_id in road_ids
                            ),
                            generator="INTERNAL_CONNECTOR_TREE",
                            threshold_m=threshold,
                            hard_valid=proof.hard_valid,
                            connector_tree_proof=proof.as_dict(),
                        )
                    )
    unique: dict[tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]], _Plan] = {}
    for plan in plans:
        if not plan.hard_valid:
            continue
        key = (plan.decision, plan.road_ids, plan.road_roles)
        current = unique.get(key)
        if current is None or plan.threshold_m < current.threshold_m:
            unique[key] = plan
    ordered = sorted(
        unique.values(),
        key=lambda row: (
            {"KEEP_SWSD": 0, "ABSTAIN": 1, "USE_RCSD": 2}[row.decision],
            len(row.road_ids),
            row.threshold_m,
            {
                "ANCHOR_PATH": 0,
                "MULTIPATH_UNION": 1,
                "INTERNAL_CONNECTOR_TREE": 2,
                "COMPONENT_ALL_MAIN": 3,
            }.get(row.generator, 4),
            row.road_ids,
        ),
    )
    return ordered[:max_candidates]


def _local_graph(
    roads: Sequence[_Road],
    indices: Iterable[int],
    segment_geometry: BaseGeometry,
) -> nx.MultiGraph:
    graph = nx.MultiGraph()
    for index in indices:
        road = roads[index]
        distance = float(road.geometry.distance(segment_geometry))
        graph.add_edge(
            road.start_node_id,
            road.end_node_id,
            key=road.road_id,
            road_id=road.road_id,
            weight=road.length_m * (1.0 + min(distance, 80.0) / 40.0),
        )
    return graph


def _shortest_path_roads(
    graph: nx.MultiGraph,
    start_node: str,
    end_node: str,
) -> tuple[str, ...]:
    if start_node not in graph or end_node not in graph or start_node == end_node:
        return ()
    try:
        nodes = nx.shortest_path(graph, start_node, end_node, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return ()
    road_ids = []
    for source, target in zip(nodes, nodes[1:]):
        data = graph.get_edge_data(source, target) or {}
        best = min(data.values(), key=lambda row: (row["weight"], row["road_id"]))
        road_ids.append(str(best["road_id"]))
    return tuple(sorted(set(road_ids)))


def _best_component_path(
    graph: nx.MultiGraph,
    node_set: set[str],
    start_nodes: Sequence[str],
    end_nodes: Sequence[str],
) -> tuple[str, ...]:
    subgraph = graph.subgraph(node_set)
    candidates = [
        _shortest_path_roads(subgraph, start_node, end_node)
        for start_node in start_nodes
        for end_node in end_nodes
    ]
    candidates = [row for row in candidates if row]
    return min(candidates, key=lambda row: (len(row), row), default=())


def _plan_dict(
    case_key: str,
    segment_id: str,
    plan: _Plan,
    segment_geometry: BaseGeometry,
    roads: Sequence[_Road],
    swsd_roads: Sequence[_Road],
    raw_nodes: Mapping[str, Point],
    swsd_nodes: Mapping[str, Point],
    pair_node_ids: Sequence[str],
) -> dict[str, Any]:
    road_by_id = {row.road_id: row for row in roads}
    swsd_road_by_id = {row.road_id: row for row in swsd_roads}
    member_road_by_id = (
        swsd_road_by_id if plan.decision == "KEEP_SWSD" else road_by_id
    )
    member_nodes = (
        swsd_nodes if plan.decision == "KEEP_SWSD" else raw_nodes
    )
    pair_points = [
        swsd_nodes[node_id]
        for node_id in pair_node_ids
        if node_id in swsd_nodes
    ]
    plan_id = "tap:" + canonical_sha256(
        {
            "case_key": case_key,
            "segment_id": segment_id,
            "decision": plan.decision,
            "road_ids": plan.road_ids,
            "road_roles": plan.road_roles,
        }
    )[:24]
    return {
        "plan_id": plan_id,
        "decision": plan.decision,
        "road_ids": list(plan.road_ids),
        "road_roles": [
            {"road_id": road_id, "role": role}
            for road_id, role in plan.road_roles
        ],
        "owned_road_ids": list(plan.road_ids),
        "internal_connector_road_ids": [
            road_id
            for road_id, role in plan.road_roles
            if role == "INTERNAL_CONNECTOR"
        ],
        "internal_connector_tree_proof": plan.connector_tree_proof,
        "road_members": build_ordinary_plan_member_rows(
            road_ids=plan.road_ids,
            road_roles=dict(plan.road_roles),
            road_by_id=member_road_by_id,
            segment_geometry=segment_geometry,
            raw_nodes=member_nodes,
            swsd_nodes=swsd_nodes,
            pair_node_ids=pair_node_ids,
        ),
        "arm_rows": build_ordinary_plan_arm_rows(
            road_ids=plan.road_ids,
            road_roles=dict(plan.road_roles),
            road_by_id=member_road_by_id,
            segment_geometry=segment_geometry,
            node_points=member_nodes,
            pair_points=pair_points,
        ),
        "generator": plan.generator,
        "threshold_m": plan.threshold_m,
        "hard_valid": plan.hard_valid,
        "features": _plan_features(
            plan,
            segment_geometry,
            road_by_id,
            raw_nodes,
            swsd_nodes,
            pair_node_ids,
        ),
    }


def _plan_features(
    plan: _Plan,
    segment_geometry: BaseGeometry,
    road_by_id: Mapping[str, _Road],
    raw_nodes: Mapping[str, Point],
    swsd_nodes: Mapping[str, Point],
    pair_node_ids: Sequence[str],
) -> list[float]:
    selected = [road_by_id[road_id] for road_id in plan.road_ids if road_id in road_by_id]
    distances = [
        float(road.geometry.distance(segment_geometry)) for road in selected
    ]
    total_length = sum(road.length_m for road in selected)
    segment_length = max(float(segment_geometry.length), 0.01)
    directions = Counter(road.direction for road in selected)
    function_classes = [road.function_class for road in selected]
    graph = nx.Graph()
    for road in selected:
        graph.add_edge(road.start_node_id, road.end_node_id)
    pair_points = [
        swsd_nodes[node_id] for node_id in pair_node_ids if node_id in swsd_nodes
    ]
    raw_endpoints = [
        point
        for road in selected
        for node_id in (road.start_node_id, road.end_node_id)
        if (point := raw_nodes.get(node_id)) is not None
    ]
    start_distance = (
        min(pair_points[0].distance(point) for point in raw_endpoints)
        if pair_points and raw_endpoints
        else 0.0
    )
    end_distance = (
        min(pair_points[-1].distance(point) for point in raw_endpoints)
        if len(pair_points) > 1 and raw_endpoints
        else 0.0
    )
    values = [
        float(plan.decision == "KEEP_SWSD"),
        float(plan.decision == "USE_RCSD"),
        float(plan.decision == "ABSTAIN"),
        float(plan.generator == "ANCHOR_PATH"),
        float(
            plan.generator
            in {"CORRIDOR_COMPONENT", "INTERNAL_CONNECTOR_TREE"}
        ),
        float(plan.generator == "MULTIPATH_UNION"),
        float(plan.generator == "KEEP_T01"),
        float(plan.generator == "SAFE_ABSTAIN"),
        float(plan.generator == "COMPONENT_ALL_MAIN"),
        math.tanh(plan.threshold_m / 40.0),
        math.tanh(len(plan.road_ids) / 12.0),
        math.tanh(total_length / segment_length),
        math.tanh((sum(distances) / len(distances) if distances else 0.0) / 20.0),
        math.tanh((max(distances) if distances else 0.0) / 40.0),
        math.tanh(start_distance / 40.0),
        math.tanh(end_distance / 40.0),
        float(nx.is_connected(graph)) if graph.number_of_nodes() else 0.0,
        float(nx.is_tree(graph)) if graph.number_of_nodes() else 0.0,
        math.tanh(
            (
                graph.number_of_edges()
                - graph.number_of_nodes()
                + nx.number_connected_components(graph)
            )
            / 4.0
        )
        if graph.number_of_nodes()
        else 0.0,
        directions.get(1, 0) / max(len(selected), 1),
        directions.get(2, 0) / max(len(selected), 1),
        directions.get(3, 0) / max(len(selected), 1),
        math.tanh(
            (sum(function_classes) / len(function_classes) if function_classes else 0)
            / 5.0
        ),
        sum(role == "INTERNAL_CONNECTOR" for _, role in plan.road_roles)
        / max(len(plan.road_roles), 1),
        float(
            bool(
                plan.connector_tree_proof
                and plan.connector_tree_proof.get("hard_valid")
            )
        ),
        math.tanh(
            len(
                plan.connector_tree_proof.get("leaf_node_ids") or ()
            )
            / 4.0
        )
        if plan.connector_tree_proof
        else 0.0,
    ]
    return _pad_features(values)


def _segment_features(segment: Mapping[str, Any]) -> list[float]:
    geometry = segment["geometry"]
    bounds = geometry.bounds
    width = max(float(bounds[2] - bounds[0]), 0.0)
    height = max(float(bounds[3] - bounds[1]), 0.0)
    values = [
        math.tanh(float(geometry.length) / 500.0),
        math.tanh(width / 500.0),
        math.tanh(height / 500.0),
        math.tanh(len(segment["swsd_road_ids"]) / 8.0),
        math.tanh(len(segment["pair_node_ids"]) / 2.0),
        math.tanh(len(segment["junc_node_ids"]) / 8.0),
        float(segment["segment_type"] == "ADVANCE_RIGHT"),
        float(segment["segment_type"] == "STANDARD"),
    ]
    return _pad_features(values)


def _nearest_node_ids(
    point: Point,
    node_ids: Sequence[str],
    node_geometries: Sequence[Point],
    node_tree: STRtree,
    *,
    radius_m: float = 80.0,
    limit: int = 4,
) -> tuple[str, ...]:
    indices = _tree_indices(node_tree, point.buffer(radius_m))
    ranked = sorted(
        (
            (float(point.distance(node_geometries[index])), node_ids[index])
            for index in indices
            if point.distance(node_geometries[index]) <= radius_m
        ),
        key=lambda row: (row[0], row[1]),
    )
    return tuple(node_id for _, node_id in ranked[:limit])


def _case_input_paths(bundle: TargetACaseBundle) -> dict[str, Path]:
    external = bundle.source_case_root / "external_inputs"
    paths = {
        "raw_rcsd_roads": external / "rcsdroad" / "rcsdroad_slice.gpkg",
        "raw_rcsd_nodes": external / "rcsdnode" / "rcsdnode_slice.gpkg",
        "t07_rcsd_intersection": (
            external / "rcsd_intersection" / "rcsd_intersection_slice.gpkg"
        ),
    }
    missing = sorted(role for role, path in paths.items() if not path.is_file())
    if missing:
        raise FileNotFoundError(f"{bundle.case_key}: missing raw inputs {missing}")
    return paths


def _read_roads(path: Path) -> tuple[list[_Road], str]:
    rows: list[_Road] = []
    with fiona.open(path) as source:
        crs = _crs_name(source)
        for feature in source:
            if not feature["geometry"]:
                continue
            properties = dict(feature["properties"])
            road_id = _first_text(properties, ("id", "roadid", "road_id"))
            start = _first_text(properties, ("snodeid", "start_node_id"))
            end = _first_text(properties, ("enodeid", "end_node_id"))
            if not road_id or not start or not end:
                continue
            rows.append(
                _Road(
                    road_id=road_id,
                    start_node_id=start,
                    end_node_id=end,
                    direction=_integer(properties.get("direction")),
                    function_class=_integer(
                        properties.get("funcclass")
                        or properties.get("function_class")
                    ),
                    geometry=shape(feature["geometry"]),
                )
            )
    rows.sort(key=lambda row: row.road_id)
    if not rows:
        raise ValueError(f"Target A raw RCSD Road input is empty: {path}")
    return rows, crs


def _read_points(path: Path) -> tuple[dict[str, Point], str, dict[str, str]]:
    rows: dict[str, Point] = {}
    node_metadata: list[tuple[str, str, int]] = []
    with fiona.open(path) as source:
        crs = _crs_name(source)
        for feature in source:
            if not feature["geometry"]:
                continue
            properties = dict(feature["properties"])
            node_id = _first_text(properties, ("id", "nodeid", "node_id"))
            geometry = shape(feature["geometry"])
            if node_id and isinstance(geometry, Point):
                rows[node_id] = geometry
                main_node_id = _first_text(
                    properties,
                    ("mainnodeid", "main_node_id"),
                )
                if main_node_id in {"", "0", "-1"}:
                    main_node_id = node_id
                node_metadata.append(
                    (
                        node_id,
                        main_node_id,
                        _integer(properties.get("kind_2")),
                    )
                )
    if not rows:
        raise ValueError(f"Target A Node input is empty: {path}")
    semantic_targets = {
        main_node_id
        for _, main_node_id, kind in node_metadata
        if kind in SEMANTIC_JUNCTION_KINDS
    }
    semantic_anchor_by_node: dict[str, str] = {}
    for node_id, main_node_id, kind in node_metadata:
        if kind in SEMANTIC_JUNCTION_KINDS or main_node_id in semantic_targets:
            semantic_anchor_by_node[node_id] = main_node_id
            semantic_anchor_by_node[main_node_id] = main_node_id
    return rows, crs, semantic_anchor_by_node


def _read_segments(path: Path) -> tuple[list[dict[str, Any]], str]:
    rows: list[dict[str, Any]] = []
    with fiona.open(path) as source:
        crs = _crs_name(source)
        for feature in source:
            if not feature["geometry"]:
                continue
            properties = dict(feature["properties"])
            segment_id = _first_text(properties, ("id", "segmentid", "segment_id"))
            if not segment_id:
                continue
            segment_type = str(properties.get("segment_type") or "normal").casefold()
            rows.append(
                {
                    "segment_id": segment_id,
                    "segment_type": (
                        "ADVANCE_RIGHT"
                        if segment_type == "advance_right"
                        else "STANDARD"
                    ),
                    "pair_node_ids": _split_ids(properties.get("pair_nodes")),
                    "junc_node_ids": _split_ids(properties.get("junc_nodes")),
                    "swsd_road_ids": _split_ids(properties.get("roads")),
                    "geometry": shape(feature["geometry"]),
                }
            )
    rows.sort(key=lambda row: row["segment_id"])
    return rows, crs


def _geometry_boundary_points(geometry: BaseGeometry) -> list[Point]:
    lines = (
        [geometry]
        if isinstance(geometry, LineString)
        else [part for part in getattr(geometry, "geoms", ()) if isinstance(part, LineString)]
    )
    if not lines:
        return []
    endpoints = [
        Point(line.coords[0]) for line in lines if len(line.coords)
    ] + [
        Point(line.coords[-1]) for line in lines if len(line.coords)
    ]
    if len(endpoints) < 2:
        return endpoints
    best = max(
        (
            (first.distance(second), first, second)
            for first in endpoints
            for second in endpoints
        ),
        key=lambda row: row[0],
    )
    return [best[1], best[2]]


def _tree_indices(tree: STRtree, geometry: BaseGeometry) -> list[int]:
    result = tree.query(geometry)
    if len(result) == 0:
        return []
    first = result[0]
    if isinstance(first, (int, np.integer)):
        return [int(value) for value in result]
    geometry_by_id = {id(value): index for index, value in enumerate(tree.geometries)}
    return [geometry_by_id[id(value)] for value in result]


def _crs_name(source: fiona.Collection) -> str:
    value = source.crs
    epsg = value.to_epsg() if hasattr(value, "to_epsg") else None
    if epsg:
        return f"EPSG:{epsg}"
    text = str(value)
    return text.upper()


def _split_ids(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    text = str(value).strip()
    if not text:
        return ()
    if text.startswith("["):
        try:
            payload = json.loads(text)
            return tuple(str(item).strip() for item in payload if str(item).strip())
        except json.JSONDecodeError:
            pass
    return tuple(item.strip() for item in text.split(",") if item.strip())


def _first_text(properties: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = properties.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _pad_features(values: Sequence[float]) -> list[float]:
    if len(values) > TARGET_A_FEATURE_DIM:
        raise ValueError("Target A plan feature vector exceeds configured dimension")
    return [float(value) for value in values] + [0.0] * (
        TARGET_A_FEATURE_DIM - len(values)
    )


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    return float(np.quantile(np.asarray(values, dtype=np.float64), quantile))


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )


__all__ = [
    "PLAN_CANDIDATE_THRESHOLDS_M",
    "build_truth_free_plan_candidate_store",
]
