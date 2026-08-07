from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona
import numpy as np
from shapely import contains_xy
from shapely.geometry import Point, box, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file


OBJECT_FEATURE_DIM = 64
MEMBER_FEATURE_DIM = 12
GEOMETRY_TOKEN_DIM = 21
GEOMETRY_RELATION_DIM = 8
GEOMETRY_RADIUS_M = 200.0
SURFACE_GRID_SIZE = 128
SURFACE_GRID_RESOLUTION_M = 4.0
SURFACE_GRID_HALF_EXTENT_M = (
    SURFACE_GRID_SIZE * SURFACE_GRID_RESOLUTION_M / 2.0
)

GEOMETRY_ROLE_FILES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("SWSD_NODE", ("nodes.gpkg",)),
    ("SWSD_ROAD", ("roads.gpkg",)),
    ("DRIVEZONE", ("drivezone.gpkg",)),
    ("RCSD_NODE", ("rcsdnode.gpkg",)),
    ("RCSD_ROAD", ("rcsdroad.gpkg",)),
    ("DIVSTRIP", ("divstripzone.gpkg", "divstrip.gpkg")),
    (
        "RCSD_INTERSECTION",
        ("rcsdintersection.gpkg", "rcsd_intersection.gpkg"),
    ),
)
GEOMETRY_ROLE_INDEX = {
    role: index for index, (role, _) in enumerate(GEOMETRY_ROLE_FILES)
}

FORBIDDEN_INFERENCE_FIELD_TOKENS = (
    "label",
    "truth",
    "preferred",
    "acceptable",
    "selected",
    "status",
    "split",
    "fold",
    "family",
    "route",
    "t03",
    "t04",
    "t05",
)


@dataclass(frozen=True)
class JunctionJointStoreInputs:
    final_labels_path: Path
    split_samples_path: Path
    legacy_feature_store_root: Path


def write_junction_joint_store(
    *,
    inputs: JunctionJointStoreInputs,
    output_root: Path,
    radius_m: float = GEOMETRY_RADIUS_M,
    max_candidates: int = 64,
) -> dict[str, Any]:
    if radius_m <= 0 or max_candidates < 1:
        raise ValueError("junction joint store candidate controls are invalid")
    output = Path(output_root).resolve()
    if output.exists():
        raise FileExistsError(output)
    feature_root = output / "inference_feature_store"
    label_root = output / "training_label_store"
    lineage_root = output / "lineage_store"
    feature_root.mkdir(parents=True)
    label_root.mkdir()
    lineage_root.mkdir()

    labels = {
        str(row["sample_id"]): row
        for row in _read_jsonl(Path(inputs.final_labels_path))
    }
    split_rows = tuple(_read_jsonl(Path(inputs.split_samples_path)))
    split_by_sample = {str(row["sample_id"]): row for row in split_rows}
    if len(split_by_sample) != len(split_rows):
        raise ValueError("junction split contains duplicate sample_id values")
    if not set(split_by_sample).issubset(labels):
        raise ValueError("junction split contains unknown final labels")

    legacy = _read_legacy_single_point_features(
        Path(inputs.legacy_feature_store_root)
    )
    feature_rows: list[dict[str, Any]] = []
    label_rows: list[dict[str, Any]] = []
    lineage_rows: list[dict[str, Any]] = []
    for split_row in sorted(
        split_rows,
        key=lambda row: (
            str(row["split"]),
            str(row["case_id"]),
            int(row["source_index"]),
        ),
    ):
        sample_id = str(split_row["sample_id"])
        label = labels[sample_id]
        case_root = Path(str(label["case_root"]))
        representation = _representation_for_label(
            label,
            legacy=legacy,
            radius_m=radius_m,
            max_candidates=max_candidates,
        )
        _verify_representation_inputs(case_root, representation["input_hashes"])
        anchor_point = _semantic_anchor_point(case_root / "nodes.gpkg", str(label["case_id"]))
        geometry = _geometry_evidence(
            case_root,
            anchor_point=anchor_point,
            radius_m=radius_m,
        )
        drivezone_grid_indices = _raw_role_grid_indices(
            geometry["object_geometries"],
            role="DRIVEZONE",
            anchor_point=anchor_point,
        )
        feature_rows.append(
            {
                "sample_id": sample_id,
                "anchor_id": str(label["case_id"]),
                "input_fingerprint": str(label["input_fingerprint"]),
                "object_features": representation["object_features"],
                "candidate_ids": representation["candidate_ids"],
                "candidate_features": representation["candidate_features"],
                "structural_member_ids": representation["structural_member_ids"],
                "swsd_arm_features": representation["swsd_arm_features"],
                "member_arm_features": representation["member_arm_features"],
                "member_local_features": representation["member_local_features"],
                "member_relation_edges": representation["member_relation_edges"],
                "geometry_token_features": geometry["token_features"],
                "geometry_object_spans": geometry["object_spans"],
                "geometry_relation_edges": geometry["relation_edges"],
                "drivezone_grid_indices": drivezone_grid_indices,
            }
        )
        label_rows.append(
            _training_label_row(
                label,
                split_row=split_row,
                representation=representation,
                geometry=geometry,
                anchor_point=anchor_point,
            )
        )
        lineage_rows.append(
            {
                "sample_id": sample_id,
                "case_id": str(label["case_id"]),
                "family": str(label["family"]),
                "source_scope": str(label["source_scope"]),
                "case_root": str(case_root),
                "input_fingerprint": str(label["input_fingerprint"]),
                "input_hashes": representation["input_hashes"],
                "split": str(split_row["split"]),
                "source_index": int(split_row["source_index"]),
            }
        )

    if len(feature_rows) != len(label_rows) or len(feature_rows) != len(lineage_rows):
        raise AssertionError("junction joint store scopes differ")
    leakage = audit_junction_joint_feature_rows(feature_rows)
    if not leakage["passed"]:
        raise RuntimeError(f"junction inference feature leakage: {leakage}")

    feature_path = feature_root / "junction_features.jsonl"
    label_path = label_root / "junction_labels.jsonl"
    lineage_path = lineage_root / "junction_lineage.jsonl"
    _write_jsonl(feature_path, feature_rows)
    _write_jsonl(label_path, label_rows)
    _write_jsonl(lineage_path, lineage_rows)
    summary = {
        "schema_version": "p05-target-a-junction-joint-store-v4",
        "status": "JUNCTION_JOINT_STORE_GO",
        "example_count": len(feature_rows),
        "split_counts": _counts(row["split"] for row in label_rows),
        "effective_weight_by_split": {
            split: round(
                sum(
                    float(row["sample_weight"])
                    for row in label_rows
                    if row["split"] == split
                ),
                6,
            )
            for split in ("train", "validation", "test")
        },
        "final_state_counts": _counts(
            row["task_labels"]["final_state"] for row in label_rows
        ),
        "surface_mode_counts": _counts(
            row["task_labels"]["surface_mode"] for row in label_rows
        ),
        "t07_step2_supervised_count": sum(
            bool(row["task_masks"]["t07_step2"]) for row in label_rows
        ),
        "surface_grid_supervised_count": sum(
            bool(row["surface_grid_supervised"]) for row in label_rows
        ),
        "surface_grid_clipped_count": sum(
            float(row["surface_grid_clipped_area_ratio"]) > 1.0e-9
            for row in label_rows
        ),
        "drivezone_grid_nonempty_count": sum(
            bool(row["drivezone_grid_indices"]) for row in feature_rows
        ),
        "drivezone_grid_max_occupied_cells": max(
            (len(row["drivezone_grid_indices"]) for row in feature_rows),
            default=0,
        ),
        "action_supervised_count": sum(
            bool(row["task_masks"]["junctionization_action"])
            for row in label_rows
        ),
        "candidate_supervised_count": sum(
            bool(row["candidate_supervised"]) for row in label_rows
        ),
        "candidate_target_unreachable_count": sum(
            bool(row["candidate_target_required"])
            and not bool(row["candidate_supervised"])
            for row in label_rows
        ),
        "member_supervised_count": sum(
            bool(row["member_supervised"]) for row in label_rows
        ),
        "member_target_unreachable_count": sum(
            bool(row["member_target_required"])
            and not bool(row["member_supervised"])
            for row in label_rows
        ),
        "raw_object_target_required_count": sum(
            bool(row["raw_object_target_required"]) for row in label_rows
        ),
        "raw_object_target_unreachable_count": sum(
            bool(row["raw_object_target_required"])
            and not bool(row["raw_object_supervised"])
            for row in label_rows
        ),
        "surface_object_supervised_count": sum(
            bool(row["surface_object_supervised"]) for row in label_rows
        ),
        "break_position_target_count": sum(
            len(row["break_position_targets"]) for row in label_rows
        ),
        "break_position_max_per_road": max(
            (
                max(
                    Counter(
                        target["road_object_id"]
                        for target in row["break_position_targets"]
                    ).values(),
                    default=0,
                )
                for row in label_rows
            ),
            default=0,
        ),
        "complete_junction_supervised_count": sum(
            bool(row["complete_junction_supervised"]) for row in label_rows
        ),
        "topology_geometry_supervised_count": sum(
            bool(row["topology_geometry_supervised"]) for row in label_rows
        ),
        "geometry_token_count": sum(
            len(row["geometry_token_features"]) for row in feature_rows
        ),
        "geometry_relation_edge_count": sum(
            len(row["geometry_relation_edges"]) for row in feature_rows
        ),
        "invalid_raw_geometry_object_count": sum(
            not bool(span["geometry_valid"])
            for row in feature_rows
            for span in row["geometry_object_spans"]
        ),
        "geometry_token_max_per_example": max(
            (len(row["geometry_token_features"]) for row in feature_rows),
            default=0,
        ),
        "feature_dimensions": {
            "object": OBJECT_FEATURE_DIM,
            "candidate": OBJECT_FEATURE_DIM,
            "member": MEMBER_FEATURE_DIM,
            "geometry_token": GEOMETRY_TOKEN_DIM,
            "geometry_relation": GEOMETRY_RELATION_DIM,
        },
        "surface_grid": {
            "size": SURFACE_GRID_SIZE,
            "resolution_m": SURFACE_GRID_RESOLUTION_M,
            "half_extent_m": SURFACE_GRID_HALF_EXTENT_M,
        },
        "feature_field_leakage_audit": leakage,
        "geometry_changed": False,
        "silent_fix": False,
        "artifacts": {
            "inference_features": _artifact(feature_path),
            "training_labels": _artifact(label_path),
            "lineage": _artifact(lineage_path),
        },
    }
    (output / "manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def audit_junction_joint_feature_rows(
    feature_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    violations: list[dict[str, str]] = []

    def visit(value: Any, path: str) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                lowered = str(key).lower()
                if any(token in lowered for token in FORBIDDEN_INFERENCE_FIELD_TOKENS):
                    violations.append({"path": f"{path}.{key}", "field": str(key)})
                visit(nested, f"{path}.{key}")
        elif isinstance(value, (list, tuple)):
            for index, nested in enumerate(value):
                visit(nested, f"{path}[{index}]")

    for index, row in enumerate(feature_rows):
        visit(row, f"rows[{index}]")
    return {
        "passed": not violations,
        "violation_count": len(violations),
        "violations": violations[:100],
    }


def _representation_for_label(
    label: Mapping[str, Any],
    *,
    legacy: Mapping[str, Mapping[str, Any]],
    radius_m: float,
    max_candidates: int,
) -> dict[str, Any]:
    case_key = f"{label['family']}:{label['case_id']}"
    if str(label["source_scope"]) == "POC_Data":
        source = legacy.get(case_key)
        if source is None:
            raise ValueError(f"legacy truth-free feature row is missing: {case_key}")
        return {
            key: source.get(key) or ()
            for key in (
                "object_features",
                "candidate_ids",
                "candidate_features",
                "structural_member_ids",
                "swsd_arm_features",
                "member_arm_features",
                "member_local_features",
                "member_relation_edges",
                "input_hashes",
            )
        }
    if str(label["source_scope"]) != "POC_QA":
        raise ValueError(f"unsupported Gold source scope: {label['source_scope']}")
    from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_t05_anchor_dataset import (
        _single_point_t05_representation,
    )

    return _single_point_t05_representation(
        Path(str(label["case_root"])),
        target_id=str(label["case_id"]),
        radius_m=radius_m,
        max_candidates=max_candidates,
    )


def _read_legacy_single_point_features(
    store_root: Path,
) -> dict[str, Mapping[str, Any]]:
    path = (
        Path(store_root)
        / "inference_feature_store"
        / "anchor_features.jsonl"
    )
    rows: dict[str, Mapping[str, Any]] = {}
    for row in _read_jsonl(path):
        case_key = str(row.get("case_key") or "")
        family = case_key.partition(":")[0]
        if family not in {"T03", "T03_Error", "T04", "T04_Error"}:
            continue
        if case_key in rows:
            raise ValueError(f"legacy single-point case key is duplicated: {case_key}")
        rows[case_key] = row
    return rows


def _verify_representation_inputs(
    case_root: Path,
    input_hashes: Iterable[Sequence[str]],
) -> None:
    expected = {str(name): str(digest) for name, digest in input_hashes}
    if not expected:
        raise ValueError(f"truth-free feature input hashes are absent: {case_root}")
    for name, digest in expected.items():
        path = case_root / name
        if not path.is_file() or sha256_file(path) != digest:
            raise ValueError(f"truth-free feature input differs: {path}")


def _geometry_evidence(
    case_root: Path,
    *,
    anchor_point: Point,
    radius_m: float,
) -> dict[str, Any]:
    files = {path.name.casefold(): path for path in case_root.iterdir() if path.is_file()}
    objects: list[tuple[int, str, str, BaseGeometry, Mapping[str, Any]]] = []
    for role, names in GEOMETRY_ROLE_FILES:
        path = next((files.get(name.casefold()) for name in names if files.get(name.casefold())), None)
        if path is None:
            continue
        with fiona.open(path) as source:
            if source.crs.to_epsg() != 3857:
                raise ValueError(f"raw geometry CRS must be EPSG:3857: {path}")
            for index, feature in enumerate(source):
                if not feature["geometry"]:
                    continue
                geometry = shape(feature["geometry"])
                if geometry.is_empty:
                    continue
                properties = dict(feature["properties"])
                object_id = _geometry_object_id(role, properties, geometry, index)
                objects.append(
                    (GEOMETRY_ROLE_INDEX[role], object_id, role, geometry, properties)
                )
    objects.sort(key=lambda row: (row[0], row[1]))
    token_features: list[list[float]] = []
    spans: list[dict[str, Any]] = []
    for _, object_id, role, geometry, properties in objects:
        start = len(token_features)
        token_features.extend(
            _geometry_tokens(
                geometry,
                role=role,
                properties=properties,
                anchor_point=anchor_point,
                radius_m=radius_m,
            )
        )
        end = len(token_features)
        if end > start:
            spans.append(
                {
                    "object_id": object_id,
                    "role_index": GEOMETRY_ROLE_INDEX[role],
                    "token_start": start,
                    "token_end": end,
                    "geometry_valid": bool(geometry.is_valid),
                }
            )
    if not token_features:
        raise ValueError(f"junction raw geometry evidence is empty: {case_root}")
    relation_edges = _geometry_relation_edges(objects, spans)
    return {
        "token_features": token_features,
        "object_spans": spans,
        "relation_edges": relation_edges,
        "object_geometries": {
            object_id: geometry for _, object_id, _, geometry, _ in objects
        },
    }


def _geometry_relation_edges(
    objects: Sequence[
        tuple[int, str, str, BaseGeometry, Mapping[str, Any]]
    ],
    spans: Sequence[Mapping[str, Any]],
) -> list[list[Any]]:
    """Build truth-free RCSD Node/Road incidence, grouping and connectivity."""
    object_index = {
        str(span["object_id"]): index for index, span in enumerate(spans)
    }
    nodes: dict[str, tuple[int, str]] = {}
    roads: dict[str, tuple[int, str, str]] = {}
    for _, object_id, role, _, properties in objects:
        if object_id not in object_index:
            continue
        raw_id = object_id.partition(":")[2]
        if role == "RCSD_NODE":
            main_id = _topology_id(_property(properties, ("mainnodeid", "main_node_id")))
            nodes[raw_id] = (object_index[object_id], main_id)
        elif role == "RCSD_ROAD":
            roads[raw_id] = (
                object_index[object_id],
                _topology_id(_property(properties, ("snodeid", "startnodeid"))),
                _topology_id(_property(properties, ("enodeid", "endnodeid"))),
            )

    edges: dict[tuple[int, int], list[float]] = {}

    def add(left: int, right: int, features: Sequence[float]) -> None:
        if left == right:
            return
        key = (left, right)
        values = [float(value) for value in features]
        if len(values) != GEOMETRY_RELATION_DIM:
            raise AssertionError("junction geometry relation dimension differs")
        previous = edges.get(key)
        edges[key] = (
            values
            if previous is None
            else [max(a, b) for a, b in zip(previous, values)]
        )

    endpoint_roads: dict[str, list[tuple[int, bool, bool]]] = {}
    for road_index, start_id, end_id in roads.values():
        for node_id, at_start, at_end in (
            (start_id, True, start_id == end_id),
            (end_id, end_id == start_id, True),
        ):
            if not node_id:
                continue
            endpoint_roads.setdefault(node_id, []).append(
                (road_index, at_start, at_end)
            )
            node = nodes.get(node_id)
            if node is None:
                continue
            node_index = node[0]
            add(
                node_index,
                road_index,
                (1, 0, 0, 0, 0, 0, at_start, at_end),
            )
            add(
                road_index,
                node_index,
                (0, 1, 0, 0, at_start, at_end, 0, 0),
            )

    groups: dict[str, list[tuple[str, int]]] = {}
    for node_id, (node_index, main_id) in nodes.items():
        if main_id:
            groups.setdefault(main_id, []).append((node_id, node_index))
    for main_id, members in groups.items():
        if len(members) < 2:
            continue
        representative = next(
            (row for row in members if row[0] == main_id),
            min(members),
        )
        for member in members:
            if member == representative:
                continue
            add(representative[1], member[1], (0, 0, 1, 0, 0, 0, 0, 0))
            add(member[1], representative[1], (0, 0, 1, 0, 0, 0, 0, 0))

    for endpoint_members in endpoint_roads.values():
        unique = sorted(set(endpoint_members))
        for left_index, left_start, left_end in unique:
            for right_index, right_start, right_end in unique:
                if left_index == right_index:
                    continue
                add(
                    left_index,
                    right_index,
                    (
                        0,
                        0,
                        0,
                        1,
                        left_start,
                        left_end,
                        right_start,
                        right_end,
                    ),
                )
    return [
        [left, right, features]
        for (left, right), features in sorted(edges.items())
    ]


def _topology_id(value: Any) -> str:
    result = _canonical_id(value)
    return (
        ""
        if result.casefold() in {"", "0", "-1", "none", "null", "nan"}
        else result
    )


def _geometry_tokens(
    geometry: BaseGeometry,
    *,
    role: str,
    properties: Mapping[str, Any],
    anchor_point: Point,
    radius_m: float,
) -> list[list[float]]:
    sequences = _sample_geometry_sequences(geometry)
    rows: list[list[float]] = []
    length = float(geometry.length) / radius_m
    area = float(geometry.area) / (radius_m * radius_m)
    distance = float(geometry.distance(anchor_point)) / radius_m
    raw = (
        _normalized_property(properties, ("kind",)),
        _normalized_property(properties, ("kind_2",)),
        _normalized_property(properties, ("grade", "grade_2")),
        _normalized_property(properties, ("direction",)),
        _normalized_property(
            properties,
            ("function_class", "functional_class", "form_of_way"),
        ),
    )
    role_one_hot = [0.0] * len(GEOMETRY_ROLE_FILES)
    role_one_hot[GEOMETRY_ROLE_INDEX[role]] = 1.0
    for points in sequences:
        count = len(points)
        for index, point in enumerate(points):
            before = points[max(0, index - 1)]
            after = points[min(count - 1, index + 1)]
            dx = float(after.x - before.x)
            dy = float(after.y - before.y)
            norm = math.hypot(dx, dy)
            tangent = (dx / norm, dy / norm) if norm else (0.0, 0.0)
            row = [
                *role_one_hot,
                float(point.x - anchor_point.x) / radius_m,
                float(point.y - anchor_point.y) / radius_m,
                tangent[0],
                tangent[1],
                index / max(1, count - 1),
                length,
                area,
                distance,
                float(geometry.is_valid),
                *raw,
            ]
            if len(row) != GEOMETRY_TOKEN_DIM:
                raise AssertionError("junction geometry token dimension differs")
            rows.append([float(value) for value in row])
    return rows


def _sample_geometry_sequences(geometry: BaseGeometry) -> list[list[Point]]:
    geometry_type = geometry.geom_type
    if geometry_type == "Point":
        return [[Point(geometry.x, geometry.y)]]
    if geometry_type == "MultiPoint":
        return [[Point(part.x, part.y)] for part in geometry.geoms]
    if geometry_type == "LineString":
        return [_sample_line(geometry, maximum=24)]
    if geometry_type == "MultiLineString":
        return [_sample_line(part, maximum=24) for part in geometry.geoms]
    if geometry_type == "Polygon":
        rings = [_sample_line(geometry.exterior, maximum=32)]
        rings.extend(_sample_line(ring, maximum=16) for ring in geometry.interiors)
        return rings
    if geometry_type == "MultiPolygon":
        return [
            sequence
            for polygon in geometry.geoms
            for sequence in _sample_geometry_sequences(polygon)
        ]
    if geometry_type == "GeometryCollection":
        return [
            sequence
            for part in geometry.geoms
            for sequence in _sample_geometry_sequences(part)
        ]
    point = geometry.representative_point()
    return [[Point(point.x, point.y)]]


def _sample_line(line: BaseGeometry, *, maximum: int) -> list[Point]:
    if line.length <= 0:
        point = line.representative_point()
        return [Point(point.x, point.y)]
    count = min(maximum, max(2, int(math.ceil(line.length / 10.0)) + 1))
    return [line.interpolate(index / (count - 1), normalized=True) for index in range(count)]


def _training_label_row(
    label: Mapping[str, Any],
    *,
    split_row: Mapping[str, Any],
    representation: Mapping[str, Any],
    geometry: Mapping[str, Any],
    anchor_point: Point,
) -> dict[str, Any]:
    final_state = str(label["anchor_business_state"])
    action = str(label.get("junctionization_action") or "")
    task_labels = {
        "t07_step1": str(label.get("t07_step1_has_evd") or ""),
        "t07_step2": str(label.get("t07_step2_is_anchor") or ""),
        "surface_mode": _strong_surface_mode(label),
        "surface_state": str(label.get("surface_state") or ""),
        "relation_state": str(label.get("relation_state") or ""),
        "junctionization_action": action,
        "final_state": final_state,
    }
    task_masks = {
        "t07_step1": bool(task_labels["t07_step1"]),
        "t07_step2": bool(task_labels["t07_step2"]),
        "surface_mode": bool(task_labels["surface_mode"]),
        "surface_state": bool(task_labels["surface_state"]),
        "relation_state": bool(task_labels["relation_state"]),
        "junctionization_action": str(
            label.get("junctionization_action_gold_status")
        )
        in {"READY", "ACTION_ONLY"},
        "final_state": True,
    }
    desired_kind, desired_ids = _desired_raw_object_set(label)
    candidate_indices = _acceptable_candidate_indices(
        representation.get("candidate_ids") or (),
        desired_kind=desired_kind,
        desired_ids=desired_ids,
    )
    node_targets, node_targets_complete = _junction_node_targets(label, anchor_point=anchor_point)
    topology = _structured_topology_targets(
        label,
        node_rows=node_targets,
        object_geometries=geometry["object_geometries"],
        anchor_point=anchor_point,
    )
    member_ids = tuple(str(value) for value in representation.get("structural_member_ids") or ())
    desired_members = tuple(topology["raw_object_target_object_ids"])
    member_index = {value: index for index, value in enumerate(member_ids)}
    member_target = tuple(
        sorted(member_index[value] for value in desired_members if value in member_index)
    )
    member_complete = bool(desired_members) and len(member_target) == len(desired_members)
    surface = _surface_grid_target(label, anchor_point=anchor_point)
    complete_ready = str(label.get("complete_junction_gold_status")) == "READY"
    topology_required = final_state == "SUCCESS"
    return {
        "sample_id": str(label["sample_id"]),
        "split": str(split_row["split"]),
        "sample_weight": float(split_row["effective_label_weight"]),
        "task_labels": task_labels,
        "task_masks": task_masks,
        "candidate_acceptable_indices": list(candidate_indices),
        "candidate_target_required": bool(desired_ids),
        "candidate_supervised": bool(desired_ids and candidate_indices),
        "member_acceptable_sets": [list(member_target)] if member_complete else [],
        "member_target_required": bool(desired_members),
        "member_supervised": member_complete,
        "raw_object_target_kind": desired_kind,
        "raw_object_target_ids": list(desired_ids),
        "raw_object_target_object_ids": list(
            topology["raw_object_target_object_ids"]
        ),
        "raw_object_target_required": bool(
            topology["raw_object_target_object_ids"]
        ),
        "raw_object_supervised": bool(topology["raw_object_complete"]),
        "surface_object_target_object_sets": [],
        "surface_object_supervised": False,
        "break_position_targets": list(topology["break_position_targets"]),
        "selected_main_target": topology["selected_main_target"],
        "surface_grid_indices": surface["indices"],
        "surface_grid_supervised": surface["supervised"],
        "surface_grid_clipped_area_ratio": surface["clipped_area_ratio"],
        "junction_node_point_targets": node_targets,
        "complete_junction_supervised": complete_ready,
        "topology_geometry_supervised": bool(
            complete_ready
            and topology_required
            and node_targets_complete
            and topology["topology_complete"]
        ),
        "terminal_business_signature": str(label["terminal_business_signature"]),
    }


def _strong_surface_mode(label: Mapping[str, Any]) -> str:
    state = str(label.get("surface_state") or "")
    if state == "accepted":
        return "VIRTUAL_SURFACE"
    if state == "rejected":
        return "NO_VALID_SURFACE"
    if state == "runtime_failed":
        return "AMBIGUOUS"
    return ""


def _structured_topology_targets(
    label: Mapping[str, Any],
    *,
    node_rows: Sequence[Mapping[str, Any]],
    object_geometries: Mapping[str, BaseGeometry],
    anchor_point: Point,
) -> dict[str, Any]:
    action = str(label.get("junctionization_action") or "")
    raw_node_objects = {
        object_id for object_id in object_geometries if object_id.startswith("NODE:")
    }
    explicit_new_node_ids = set(_sorted_ids(label.get("t05_new_rcsdnode_ids")))
    raw_objects: set[str] = set()
    break_rows: list[dict[str, Any]] = []
    if action in {"direct_relation", "group_existing_rcsd_nodes"}:
        desired_kind, desired_ids = _desired_raw_object_set(label)
        raw_objects.update(f"{desired_kind}:{value}" for value in desired_ids)
    elif action == "split_rcsdroad_generate_rcsdnode":
        road_objects = tuple(
            f"ROAD:{value}"
            for value in _sorted_ids(label.get("t05_original_rcsdroad_ids"))
        )
        raw_objects.update(road_objects)
        for row in node_rows:
            node_id = str(row["node_id"])
            node_object = f"NODE:{node_id}"
            if node_object in raw_node_objects and node_id not in explicit_new_node_ids:
                raw_objects.add(node_object)
                continue
            point = Point(
                anchor_point.x + float(row["dx_m"]),
                anchor_point.y + float(row["dy_m"]),
            )
            candidates = [
                (object_geometries[road].distance(point), road)
                for road in road_objects
                if road in object_geometries
            ]
            if not candidates:
                continue
            distance, road_object = min(candidates)
            road_geometry = object_geometries[road_object]
            if distance > 0.001 or road_geometry.length <= 0:
                continue
            break_rows.append(
                {
                    "node_id": node_id,
                    "road_object_id": road_object,
                    "fraction": float(road_geometry.project(point, normalized=True)),
                    "road_length_m": float(road_geometry.length),
                    "is_selected_main": bool(row.get("is_selected_main")),
                    "projection_distance_m": float(distance),
                }
            )
    raw_object_complete = bool(raw_objects) and raw_objects.issubset(object_geometries)
    break_rows.sort(key=lambda row: (row["road_object_id"], row["fraction"], row["node_id"]))
    road_counts = Counter(row["road_object_id"] for row in break_rows)
    if max(road_counts.values(), default=0) > 2:
        raise ValueError("junction Gold requires more than two breaks on one RCSD Road")
    selected_main = str(label.get("selected_main_rcsdnode_id") or "")
    selected_main_object = f"NODE:{selected_main}" if selected_main else ""
    if selected_main_object and selected_main_object in raw_objects:
        main_target: Mapping[str, Any] | None = {
            "kind": "RAW_NODE",
            "object_id": selected_main_object,
        }
    else:
        matching_breaks = [
            row for row in break_rows if str(row["node_id"]) == selected_main
        ]
        main_target = None
        if len(matching_breaks) == 1:
            target = matching_breaks[0]
            road_breaks = [
                row for row in break_rows if row["road_object_id"] == target["road_object_id"]
            ]
            main_target = {
                "kind": "BREAK",
                "road_object_id": target["road_object_id"],
                "break_rank": road_breaks.index(target),
            }
    generated_count = sum(
        f"NODE:{row['node_id']}" not in raw_node_objects
        or str(row["node_id"]) in explicit_new_node_ids
        for row in node_rows
    )
    topology_complete = (
        action not in {
            "direct_relation",
            "group_existing_rcsd_nodes",
            "split_rcsdroad_generate_rcsdnode",
        }
        or (
            raw_object_complete
            and len(break_rows) == generated_count
            and main_target is not None
        )
    )
    return {
        "raw_object_target_object_ids": tuple(sorted(raw_objects)),
        "raw_object_complete": raw_object_complete,
        "break_position_targets": tuple(break_rows),
        "selected_main_target": main_target,
        "topology_complete": topology_complete,
    }


def _desired_raw_object_set(label: Mapping[str, Any]) -> tuple[str, tuple[str, ...]]:
    action = str(label.get("junctionization_action") or "")
    if action == "split_rcsdroad_generate_rcsdnode":
        return "ROAD", _sorted_ids(label.get("t05_original_rcsdroad_ids"))
    if action in {"direct_relation", "group_existing_rcsd_nodes"}:
        ids = _sorted_ids(label.get("t05_grouped_rcsdnode_ids"))
        if not ids:
            ids = _sorted_ids(label.get("t05_original_rcsdnode_ids"))
        if not ids and label.get("selected_main_rcsdnode_id"):
            ids = (str(label["selected_main_rcsdnode_id"]),)
        return "NODE", ids
    return "", ()


def _acceptable_candidate_indices(
    candidate_ids: Iterable[Any],
    *,
    desired_kind: str,
    desired_ids: Sequence[str],
) -> tuple[int, ...]:
    if not desired_kind or not desired_ids:
        return ()
    desired = set(desired_ids)
    result = []
    for index, candidate_id in enumerate(candidate_ids):
        kind, separator, payload = str(candidate_id).partition(":")
        if not separator or kind != desired_kind:
            continue
        values = {value for value in payload.split("|") if value}
        if values == desired:
            result.append(index)
    return tuple(result)


def _surface_grid_target(
    label: Mapping[str, Any],
    *,
    anchor_point: Point,
) -> dict[str, Any]:
    if str(label.get("surface_state")) != "accepted":
        return {"indices": [], "supervised": False, "clipped_area_ratio": 0.0}
    path = Path(str(label.get("surface_geometry_path") or ""))
    geometries: list[BaseGeometry] = []
    with fiona.open(path) as source:
        if source.crs.to_epsg() != 3857:
            raise ValueError(f"Gold surface CRS must be EPSG:3857: {path}")
        for feature in source:
            if feature["geometry"]:
                geometry = shape(feature["geometry"])
                if geometry.is_empty or not geometry.is_valid:
                    raise ValueError(f"Gold surface geometry is invalid: {path}")
                geometries.append(geometry)
    if not geometries:
        raise ValueError(f"accepted Gold surface is empty: {path}")
    geometry = unary_union(geometries)
    half = SURFACE_GRID_HALF_EXTENT_M
    window = box(
        anchor_point.x - half,
        anchor_point.y - half,
        anchor_point.x + half,
        anchor_point.y + half,
    )
    inside_area = float(geometry.intersection(window).area)
    total_area = max(float(geometry.area), 1.0e-9)
    clipped_ratio = max(0.0, 1.0 - inside_area / total_area)
    offset = -half + SURFACE_GRID_RESOLUTION_M / 2.0
    coordinates = offset + np.arange(SURFACE_GRID_SIZE) * SURFACE_GRID_RESOLUTION_M
    xx, yy = np.meshgrid(
        coordinates + anchor_point.x,
        coordinates + anchor_point.y,
    )
    mask = contains_xy(geometry, xx, yy)
    indices = np.flatnonzero(mask.reshape(-1)).astype(np.int64).tolist()
    return {
        "indices": indices,
        "supervised": clipped_ratio <= 1.0e-9,
        "clipped_area_ratio": round(clipped_ratio, 12),
    }


def _raw_role_grid_indices(
    object_geometries: Mapping[str, BaseGeometry],
    *,
    role: str,
    anchor_point: Point,
) -> list[int]:
    prefix = f"{role}:"
    geometries = [
        geometry
        for object_id, geometry in object_geometries.items()
        if object_id.startswith(prefix)
        and geometry.geom_type in {"Polygon", "MultiPolygon"}
    ]
    if not geometries:
        return []
    half = SURFACE_GRID_HALF_EXTENT_M
    offset = -half + SURFACE_GRID_RESOLUTION_M / 2.0
    coordinates = offset + np.arange(SURFACE_GRID_SIZE) * SURFACE_GRID_RESOLUTION_M
    xx, yy = np.meshgrid(
        coordinates + anchor_point.x,
        coordinates + anchor_point.y,
    )
    # Evaluate each original polygon independently. Unioning an invalid raw
    # DriveZone would either fail or require an unauthorized geometry repair.
    mask = np.zeros(xx.shape, dtype=bool)
    for geometry in geometries:
        mask |= contains_xy(geometry, xx, yy)
    return np.flatnonzero(mask.reshape(-1)).astype(np.int64).tolist()


def _junction_node_targets(
    label: Mapping[str, Any],
    *,
    anchor_point: Point,
) -> tuple[list[dict[str, Any]], bool]:
    if str(label.get("anchor_business_state")) != "SUCCESS":
        return [], True
    ids = set(_sorted_ids(label.get("t05_new_rcsdnode_ids")))
    ids.update(_sorted_ids(label.get("t05_grouped_rcsdnode_ids")))
    ids.update(_sorted_ids(label.get("t05_original_rcsdnode_ids")))
    selected = str(label.get("selected_main_rcsdnode_id") or "")
    if selected:
        ids.add(selected)
    if not ids:
        return [], False
    path = Path(str(label.get("t05_phase2_rcsdnode_path") or ""))
    points: dict[str, Point] = {}
    with fiona.open(path) as source:
        if source.crs.to_epsg() != 3857:
            raise ValueError(f"T05 Node CRS must be EPSG:3857: {path}")
        for feature in source:
            properties = dict(feature["properties"])
            node_id = _canonical_id(_property(properties, ("id", "nodeid", "node_id")))
            if node_id not in ids or not feature["geometry"]:
                continue
            geometry = shape(feature["geometry"])
            point = geometry if geometry.geom_type == "Point" else geometry.centroid
            points[node_id] = Point(point.x, point.y)
    targets = [
        {
            "node_id": node_id,
            "dx_m": float(points[node_id].x - anchor_point.x),
            "dy_m": float(points[node_id].y - anchor_point.y),
            "is_selected_main": node_id == selected,
        }
        for node_id in sorted(points)
    ]
    return targets, set(points) == ids


def _semantic_anchor_point(nodes_path: Path, case_id: str) -> Point:
    exact: list[tuple[int, Point]] = []
    grouped: list[Point] = []
    with fiona.open(nodes_path) as source:
        if source.crs.to_epsg() != 3857:
            raise ValueError(f"SWSD Node CRS must be EPSG:3857: {nodes_path}")
        for feature in source:
            if not feature["geometry"]:
                continue
            properties = dict(feature["properties"])
            node_id = _canonical_id(_property(properties, ("id", "nodeid", "node_id")))
            mainnodeid = _canonical_id(_property(properties, ("mainnodeid", "main_node_id")))
            geometry = shape(feature["geometry"])
            point = geometry if geometry.geom_type == "Point" else geometry.centroid
            point = Point(point.x, point.y)
            if node_id == case_id:
                exact.append((int(_number(_property(properties, ("kind_2",)), 0.0)), point))
            if mainnodeid == case_id:
                grouped.append(point)
    if exact:
        return max(exact, key=lambda row: row[0])[1]
    if grouped:
        return Point(
            sum(point.x for point in grouped) / len(grouped),
            sum(point.y for point in grouped) / len(grouped),
        )
    raise ValueError(f"SWSD semantic anchor point is missing: {nodes_path}/{case_id}")


def _geometry_object_id(
    role: str,
    properties: Mapping[str, Any],
    geometry: BaseGeometry,
    index: int,
) -> str:
    raw = _canonical_id(
        _property(properties, ("id", "roadid", "road_id", "nodeid", "node_id"))
    )
    if not raw:
        raw = f"{index}:{hashlib.sha256(geometry.wkb).hexdigest()[:12]}"
    if role == "RCSD_NODE":
        return f"NODE:{raw}"
    if role == "RCSD_ROAD":
        return f"ROAD:{raw}"
    return f"{role}:{raw}"


def _normalized_property(
    properties: Mapping[str, Any],
    keys: Sequence[str],
) -> float:
    return math.tanh(_number(_property(properties, keys), 0.0) / 16.0)


def _property(properties: Mapping[str, Any], keys: Sequence[str]) -> Any:
    lower = {str(key).casefold(): value for key, value in properties.items()}
    for key in keys:
        if key.casefold() in lower:
            return lower[key.casefold()]
    return None


def _number(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _canonical_id(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).strip()
    if text.endswith(".0"):
        try:
            return str(int(float(text)))
        except ValueError:
            pass
    return text


def _sorted_ids(values: Any) -> tuple[str, ...]:
    if values in (None, ""):
        return ()
    raw = values if isinstance(values, (list, tuple, set)) else str(values).replace(",", "|").split("|")
    return tuple(sorted({_canonical_id(value) for value in raw if _canonical_id(value)}))


def _counts(values: Iterable[Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


__all__ = [
    "GEOMETRY_RELATION_DIM",
    "GEOMETRY_TOKEN_DIM",
    "JunctionJointStoreInputs",
    "OBJECT_FEATURE_DIM",
    "SURFACE_GRID_RESOLUTION_M",
    "SURFACE_GRID_SIZE",
    "audit_junction_joint_feature_rows",
    "write_junction_joint_store",
]
