from __future__ import annotations

import gzip
import hashlib
import itertools
import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona
from shapely import STRtree
from shapely.geometry import Point, box, shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_data import (
    TASK_CLASSES,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_RELATION_DIM,
    GEOMETRY_ROLE_INDEX,
    GEOMETRY_TOKEN_DIM,
    _canonical_id,
    _geometry_object_id,
    _geometry_relation_edges,
    _geometry_tokens,
    _raw_role_grid_indices,
    _structured_topology_targets,
    audit_junction_joint_feature_rows,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_t10_complete_gold import (
    T10CompleteJunctionGold,
    read_t10_complete_junction_gold,
)


T10_SOURCE_PATHS: Mapping[str, str] = {
    "SWSD_NODE": "t01/nodes.gpkg",
    "SWSD_ROAD": "t01/roads.gpkg",
    "DRIVEZONE": "external_inputs/drivezone/drivezone_slice.gpkg",
    "RCSD_NODE": "external_inputs/rcsdnode/rcsdnode_slice.gpkg",
    "RCSD_ROAD": "external_inputs/rcsdroad/rcsdroad_slice.gpkg",
    "DIVSTRIP": "external_inputs/divstripzone/divstripzone_slice.gpkg",
    "RCSD_INTERSECTION": (
        "external_inputs/rcsd_intersection/rcsd_intersection_slice.gpkg"
    ),
}


@dataclass(frozen=True)
class T10JointStoreInputs:
    anchor_store_root: Path
    junction_audit_path: Path
    t10_data_root: Path
    t10_baseline_cases_root: Path


@dataclass(frozen=True)
class _GeometryRecord:
    role: str
    object_id: str
    geometry: BaseGeometry
    properties: Mapping[str, Any]


@dataclass
class _CaseIndex:
    records_by_role: Mapping[str, tuple[_GeometryRecord, ...]]
    trees_by_role: Mapping[str, STRtree]
    object_lookup: Mapping[str, _GeometryRecord]
    anchor_points: Mapping[str, Point]
    source_hashes: tuple[tuple[str, str], ...]
    t07_surface_targets: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


@dataclass(frozen=True)
class _ManualRelationGold:
    action: str
    relation_object_kind: str
    acceptable_object_sets: tuple[tuple[str, ...], ...]
    final_state: str
    supervision_scope: str


def write_t10_junction_joint_store(
    *,
    inputs: T10JointStoreInputs,
    output_root: Path,
    radius_m: float = 200.0,
    case_limit: int | None = None,
    sample_limit_per_case: int | None = None,
    include_test_shard: bool = True,
) -> dict[str, Any]:
    if (
        radius_m <= 0
        or (case_limit is not None and case_limit < 1)
        or (sample_limit_per_case is not None and sample_limit_per_case < 1)
    ):
        raise ValueError("T10 junction store controls are invalid")
    output = Path(output_root).resolve()
    if output.exists():
        raise FileExistsError(output)
    feature_root = output / "inference_feature_store"
    label_root = output / "training_label_store"
    lineage_root = output / "lineage_store"
    feature_root.mkdir(parents=True)
    label_root.mkdir()
    lineage_root.mkdir()

    anchor_root = Path(inputs.anchor_store_root).resolve(strict=True)
    old_features = [
        row
        for row in _read_jsonl(
            anchor_root / "inference_feature_store/anchor_features.jsonl"
        )
        if str(row.get("case_key") or "").startswith("T10:")
    ]
    old_labels = {
        str(row["sample_id"]): row
        for row in _read_jsonl(
            anchor_root / "training_label_store/anchor_labels.jsonl"
        )
    }
    audits = {
        str(row["sample_id"]): row
        for row in _read_jsonl(Path(inputs.junction_audit_path).resolve(strict=True))
    }
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in old_features:
        sample_id = str(row["sample_id"])
        if sample_id not in old_labels or sample_id not in audits:
            raise ValueError(f"T10 weak sample lacks label audit: {sample_id}")
        by_case[str(row["case_key"])].append(row)
    if case_limit is not None:
        selected_cases = sorted(by_case)[:case_limit]
        by_case = {key: by_case[key] for key in selected_cases}
    if sample_limit_per_case is not None:
        by_case = {
            key: sorted(rows, key=lambda row: str(row["sample_id"]))[
                :sample_limit_per_case
            ]
            for key, rows in by_case.items()
        }
    split_map = assign_t10_case_splits(
        {key: len(rows) for key, rows in by_case.items()}
    )

    split_counts: Counter[str] = Counter()
    effective_weights: Counter[str] = Counter()
    example_count = 0
    final_state_supervised_count = 0
    relation_record_absent_masked_count = 0
    partial_object_supervised_count = 0
    complete_relation_plan_count = 0
    complete_relation_object_supervised_count = 0
    complete_relation_topology_supervised_count = 0
    complete_relation_unreachable_count = 0
    surface_object_supervised_count = 0
    surface_object_unreachable_count = 0
    surface_mode_counts: Counter[str] = Counter()
    t07_surface_relation_anchor_count = 0
    t07_surface_relation_object_count = 0
    t07_surface_relation_multi_object_count = 0
    geometry_token_count = 0
    geometry_token_max = 0
    geometry_relation_edge_count = 0
    drivezone_grid_nonempty_count = 0
    shard_artifacts: list[dict[str, Any]] = []
    t10_data_root = Path(inputs.t10_data_root).resolve(strict=True)
    baseline_cases_root = Path(inputs.t10_baseline_cases_root).resolve(strict=True)
    selected_case_keys = tuple(
        case_key
        for case_key in sorted(by_case)
        if include_test_shard or split_map[case_key] != "test"
    )
    for case_key in selected_case_keys:
        case_id = case_key.partition(":")[2]
        case_split = split_map[case_key]
        complete_gold: Mapping[str, T10CompleteJunctionGold]
        complete_gold_hashes: tuple[tuple[str, str], ...]
        if case_split == "test":
            complete_gold = {}
            complete_gold_hashes = ()
        else:
            complete_gold, complete_gold_paths = read_t10_complete_junction_gold(
                baseline_cases_root / case_id
            )
            complete_gold_hashes = tuple(
                (path.name, sha256_file(path)) for path in complete_gold_paths
            )
        complete_gold_node_points = _read_complete_gold_node_points(complete_gold)
        index = _read_case_index(
            case_id,
            t10_data_root=t10_data_root,
            baseline_cases_root=baseline_cases_root,
        )
        t07_surface_relation_anchor_count += len(index.t07_surface_targets)
        t07_surface_relation_object_count += sum(
            len(object_ids) for object_ids in index.t07_surface_targets.values()
        )
        t07_surface_relation_multi_object_count += sum(
            len(object_ids) > 1 for object_ids in index.t07_surface_targets.values()
        )
        input_fingerprint = hashlib.sha256(
            json.dumps(index.source_hashes, separators=(",", ":")).encode()
        ).hexdigest()
        feature_path = feature_root / f"{case_id}.jsonl.gz"
        label_path = label_root / f"{case_id}.jsonl.gz"
        lineage_path = lineage_root / f"{case_id}.jsonl.gz"
        with (
            gzip.open(feature_path, "wt", encoding="utf-8", compresslevel=3) as feature_stream,
            gzip.open(label_path, "wt", encoding="utf-8", compresslevel=3) as label_stream,
            gzip.open(lineage_path, "wt", encoding="utf-8", compresslevel=3) as lineage_stream,
        ):
            for old_feature in sorted(
                by_case[case_key],
                key=lambda row: (str(row["anchor_id"]), str(row["sample_id"])),
            ):
                sample_id = str(old_feature["sample_id"])
                anchor_id = str(old_feature["anchor_id"])
                anchor_point = index.anchor_points.get(anchor_id)
                if anchor_point is None:
                    raise ValueError(
                        f"T10 SWSD semantic anchor is missing: {case_key}/{anchor_id}"
                    )
                selected = _dependency_geometry_records(
                    index,
                    old_feature,
                    anchor_point=anchor_point,
                    radius_m=radius_m,
                )
                geometry = _geometry_representation(
                    selected,
                    anchor_point=anchor_point,
                    radius_m=radius_m,
                )
                feature_row = {
                    "sample_id": sample_id,
                    "anchor_id": anchor_id,
                    "input_fingerprint": input_fingerprint,
                    "object_features": old_feature["object_features"],
                    "candidate_ids": old_feature["candidate_ids"],
                    "candidate_features": old_feature["candidate_features"],
                    "structural_member_ids": old_feature.get(
                        "structural_member_ids"
                    )
                    or [],
                    "swsd_arm_features": old_feature.get("swsd_arm_features") or [],
                    "member_arm_features": old_feature.get("member_arm_features") or [],
                    "member_local_features": old_feature.get("member_local_features")
                    or [],
                    "member_relation_edges": old_feature.get("member_relation_edges")
                    or [],
                    "geometry_token_features": geometry["token_features"],
                    "geometry_object_spans": geometry["object_spans"],
                    "geometry_relation_edges": geometry["relation_edges"],
                    "drivezone_grid_indices": _raw_role_grid_indices(
                        geometry["object_geometries"],
                        role="DRIVEZONE",
                        anchor_point=anchor_point,
                    ),
                }
                label_row = _weak_label_row(
                    old_feature,
                    old_labels[sample_id],
                    audits[sample_id],
                    split=split_map[case_key],
                    available_objects={row.object_id for row in selected},
                    surface_object_ids=index.t07_surface_targets.get(anchor_id, ()),
                    complete_gold=complete_gold.get(anchor_id),
                    complete_gold_node_points=complete_gold_node_points,
                    anchor_point=anchor_point,
                    object_geometries=geometry["object_geometries"],
                )
                lineage_row = {
                    "sample_id": sample_id,
                    "case_id": case_id,
                    "case_key": case_key,
                    "family": "T10",
                    "source_scope": "POC_Data",
                    "case_root": str(t10_data_root / case_id),
                    "input_fingerprint": input_fingerprint,
                    "input_hashes": list(index.source_hashes),
                    "complete_gold_hashes": list(complete_gold_hashes),
                    "split": split_map[case_key],
                }
                leakage = audit_junction_joint_feature_rows((feature_row,))
                if not leakage["passed"]:
                    raise RuntimeError(f"T10 junction feature leakage: {leakage}")
                _write_jsonl_row(feature_stream, feature_row)
                _write_jsonl_row(label_stream, label_row)
                _write_jsonl_row(lineage_stream, lineage_row)
                split = str(label_row["split"])
                example_count += 1
                split_counts[split] += 1
                effective_weights[split] += float(label_row["sample_weight"])
                final_state_supervised_count += bool(
                    label_row["task_masks"]["final_state"]
                )
                relation_record_absent_masked_count += label_row[
                    "weak_label_reason"
                ].startswith("t05:relation_record_absent")
                partial_object_supervised_count += bool(
                    label_row["raw_object_target_object_sets"]
                )
                complete_relation_plan_count += bool(
                    label_row.get("complete_relation_plan_supervised")
                )
                complete_relation_object_supervised_count += bool(
                    label_row.get("complete_relation_object_supervised")
                )
                complete_relation_topology_supervised_count += bool(
                    label_row.get("topology_geometry_supervised")
                    and label_row.get("complete_relation_plan_supervised")
                )
                complete_relation_unreachable_count += bool(
                    label_row.get("complete_relation_plan_supervised")
                    and label_row["task_labels"]["junctionization_action"]
                    != "failure_relation"
                    and not label_row.get("complete_relation_object_supervised")
                )
                surface_object_supervised_count += bool(
                    label_row["surface_object_supervised"]
                )
                surface_object_unreachable_count += bool(
                    label_row["surface_object_target_required"]
                    and not label_row["surface_object_supervised"]
                )
                surface_mode_counts[str(label_row["task_labels"]["surface_mode"])] += 1
                token_count = len(feature_row["geometry_token_features"])
                geometry_token_count += token_count
                geometry_token_max = max(geometry_token_max, token_count)
                geometry_relation_edge_count += len(
                    feature_row["geometry_relation_edges"]
                )
                drivezone_grid_nonempty_count += bool(
                    feature_row["drivezone_grid_indices"]
                )
        shard_artifacts.append(
            {
                "case_key": case_key,
                "split": split_map[case_key],
                "inference_features": _artifact(feature_path),
                "training_labels": _artifact(label_path),
                "lineage": _artifact(lineage_path),
            }
        )

    leakage = {"passed": True, "violation_count": 0, "violations": []}
    summary = {
        "schema_version": "p05-target-a-junction-joint-t10-mixed-store-v5",
        "status": "T10_MIXED_COMPLETE_JUNCTION_STORE_GO",
        "storage_layout": "case_jsonl_gzip_shards",
        "example_count": example_count,
        "case_count": len(selected_case_keys),
        "case_split_map": split_map,
        "test_shard_included": include_test_shard,
        "split_counts": dict(sorted(split_counts.items())),
        "effective_weight_by_split": {
            split: round(effective_weights[split], 6)
            for split in ("train", "validation", "test")
        },
        "final_state_supervised_count": final_state_supervised_count,
        "relation_record_absent_masked_count": relation_record_absent_masked_count,
        "partial_object_supervised_count": partial_object_supervised_count,
        "complete_relation_plan_count": complete_relation_plan_count,
        "complete_relation_object_supervised_count": (
            complete_relation_object_supervised_count
        ),
        "complete_relation_topology_supervised_count": (
            complete_relation_topology_supervised_count
        ),
        "complete_relation_unreachable_count": complete_relation_unreachable_count,
        "surface_object_supervised_count": surface_object_supervised_count,
        "surface_object_unreachable_count": surface_object_unreachable_count,
        "surface_mode_counts": dict(sorted(surface_mode_counts.items())),
        "t07_surface_relation_anchor_count": t07_surface_relation_anchor_count,
        "t07_surface_relation_object_count": t07_surface_relation_object_count,
        "t07_surface_relation_multi_object_count": (
            t07_surface_relation_multi_object_count
        ),
        "surface_geometry_supervised_count": 0,
        "topology_geometry_supervised_count": (
            complete_relation_topology_supervised_count
        ),
        "geometry_token_count": geometry_token_count,
        "geometry_token_max_per_example": geometry_token_max,
        "geometry_relation_edge_count": geometry_relation_edge_count,
        "geometry_relation_feature_dim": GEOMETRY_RELATION_DIM,
        "drivezone_grid_nonempty_count": drivezone_grid_nonempty_count,
        "feature_field_leakage_audit": leakage,
        "geometry_changed": False,
        "silent_fix": False,
        "artifacts": {"case_shards": shard_artifacts},
    }
    (output / "manifest.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def assign_t10_case_splits(case_counts: Mapping[str, int]) -> dict[str, str]:
    cases = tuple(sorted(case_counts))
    if len(cases) < 3:
        return {case: "train" for case in cases}
    total = sum(case_counts.values())
    target = {"train": total * 0.70, "validation": total * 0.15, "test": total * 0.15}
    best: tuple[float, tuple[str, str]] | None = None
    for validation_case, test_case in itertools.permutations(cases, 2):
        counts = {
            "validation": case_counts[validation_case],
            "test": case_counts[test_case],
        }
        counts["train"] = total - counts["validation"] - counts["test"]
        score = sum(
            ((counts[split] - target[split]) / max(target[split], 1.0)) ** 2
            for split in target
        )
        candidate = (score, (validation_case, test_case))
        if best is None or candidate < best:
            best = candidate
    assert best is not None
    validation_case, test_case = best[1]
    return {
        case: (
            "validation"
            if case == validation_case
            else "test"
            if case == test_case
            else "train"
        )
        for case in cases
    }


def _read_case_index(
    case_id: str,
    *,
    t10_data_root: Path,
    baseline_cases_root: Path,
) -> _CaseIndex:
    source_case = t10_data_root / case_id
    baseline_case = baseline_cases_root / case_id
    role_paths = {
        role: (
            baseline_case / relative
            if relative.startswith("t01/")
            else source_case / relative
        )
        for role, relative in T10_SOURCE_PATHS.items()
    }
    records_by_role: dict[str, tuple[_GeometryRecord, ...]] = {}
    object_lookup: dict[str, _GeometryRecord] = {}
    hashes: list[tuple[str, str]] = []
    for role, path in role_paths.items():
        path = path.resolve(strict=True)
        records: list[_GeometryRecord] = []
        with fiona.open(path) as source:
            if source.crs.to_epsg() != 3857:
                raise ValueError(f"T10 raw geometry CRS must be EPSG:3857: {path}")
            for index, feature in enumerate(source):
                if not feature["geometry"]:
                    continue
                geometry = shape(feature["geometry"])
                if geometry.is_empty:
                    continue
                properties = dict(feature["properties"])
                record = _GeometryRecord(
                    role=role,
                    object_id=_geometry_object_id(
                        role,
                        properties,
                        geometry,
                        index,
                    ),
                    geometry=geometry,
                    properties=properties,
                )
                records.append(record)
                object_lookup[record.object_id] = record
        records_by_role[role] = tuple(records)
        hashes.append((role, sha256_file(path)))
    trees = {
        role: STRtree([record.geometry for record in records])
        for role, records in records_by_role.items()
    }
    return _CaseIndex(
        records_by_role=records_by_role,
        trees_by_role=trees,
        object_lookup=object_lookup,
        anchor_points=_anchor_points(records_by_role["SWSD_NODE"]),
        source_hashes=tuple(sorted(hashes)),
        t07_surface_targets=_read_t07_surface_targets(
            baseline_case,
            object_lookup=object_lookup,
        ),
    )


def _anchor_points(records: Sequence[_GeometryRecord]) -> Mapping[str, Point]:
    exact: dict[str, list[tuple[int, Point]]] = defaultdict(list)
    grouped: dict[str, list[Point]] = defaultdict(list)
    for record in records:
        properties = {str(key).casefold(): value for key, value in record.properties.items()}
        node_id = _canonical_id(properties.get("id") or properties.get("nodeid"))
        mainnodeid = _canonical_id(properties.get("mainnodeid"))
        geometry = record.geometry
        point = geometry if geometry.geom_type == "Point" else geometry.centroid
        value = Point(point.x, point.y)
        try:
            kind_2 = int(float(properties.get("kind_2") or 0))
        except (TypeError, ValueError):
            kind_2 = 0
        if node_id:
            exact[node_id].append((kind_2, value))
        if mainnodeid:
            grouped[mainnodeid].append(value)
    result = {
        node_id: max(values, key=lambda row: row[0])[1]
        for node_id, values in exact.items()
    }
    for mainnodeid, values in grouped.items():
        result.setdefault(
            mainnodeid,
            Point(
                sum(value.x for value in values) / len(values),
                sum(value.y for value in values) / len(values),
            ),
        )
    return result


def _read_t07_surface_targets(
    baseline_case: Path,
    *,
    object_lookup: Mapping[str, _GeometryRecord],
) -> Mapping[str, tuple[str, ...]]:
    evidence_path = (
        baseline_case
        / "t07/t07/step2_anchor_recognition/t07_swsd_rcsd_relation_evidence.json"
    )
    if not evidence_path.is_file():
        return {}
    payload = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    result: dict[str, tuple[str, ...]] = {}
    for row in payload.get("rows") or ():
        if str(row.get("relation_state") or "") != "existing_rcsdintersection_matched":
            continue
        try:
            accepted = int(row.get("status_suggested")) == 0
        except (TypeError, ValueError):
            accepted = False
        if not accepted:
            continue
        anchor_id = _canonical_id(
            row.get("target_id") or row.get("representative_node_id")
        )
        raw_ids = str(row.get("matched_rcsdintersection_ids") or "")
        values = {
            _canonical_id(value)
            for value in raw_ids.replace(",", "|").split("|")
            if _canonical_id(value)
        }
        targets = tuple(
            sorted(
                object_id
                for value in values
                if (object_id := f"RCSD_INTERSECTION:{value}") in object_lookup
            )
        )
        if anchor_id and targets:
            result[anchor_id] = targets
    return result


def _dependency_geometry_records(
    index: _CaseIndex,
    feature: Mapping[str, Any],
    *,
    anchor_point: Point,
    radius_m: float,
) -> tuple[_GeometryRecord, ...]:
    selected: dict[str, _GeometryRecord] = {}
    for role, records in index.records_by_role.items():
        tree = index.trees_by_role[role]
        query = box(
            anchor_point.x - radius_m,
            anchor_point.y - radius_m,
            anchor_point.x + radius_m,
            anchor_point.y + radius_m,
        )
        indices = {int(value) for value in tree.query(query)}
        for record_index in indices:
            record = records[record_index]
            selected[record.object_id] = record
    forced_ids = set(str(value) for value in feature.get("structural_member_ids") or ())
    for candidate_id in feature.get("candidate_ids") or ():
        kind, separator, payload = str(candidate_id).partition(":")
        if separator:
            forced_ids.update(f"{kind}:{value}" for value in payload.split("|") if value)
    forced_ids.update(
        index.t07_surface_targets.get(str(feature.get("anchor_id") or ""), ())
    )
    for object_id in forced_ids:
        record = index.object_lookup.get(object_id)
        if record is not None:
            selected[object_id] = record
    return tuple(
        sorted(
            selected.values(),
            key=lambda row: (GEOMETRY_ROLE_INDEX[row.role], row.object_id),
        )
    )


def _geometry_representation(
    records: Sequence[_GeometryRecord],
    *,
    anchor_point: Point,
    radius_m: float,
) -> dict[str, Any]:
    tokens: list[list[float]] = []
    spans: list[dict[str, Any]] = []
    geometries: dict[str, BaseGeometry] = {}
    for record in records:
        start = len(tokens)
        tokens.extend(
            _geometry_tokens(
                record.geometry,
                role=record.role,
                properties=record.properties,
                anchor_point=anchor_point,
                radius_m=radius_m,
            )
        )
        end = len(tokens)
        if end == start:
            continue
        spans.append(
            {
                "object_id": record.object_id,
                "role_index": GEOMETRY_ROLE_INDEX[record.role],
                "token_start": start,
                "token_end": end,
                "geometry_valid": bool(record.geometry.is_valid),
            }
        )
        geometries[record.object_id] = record.geometry
    if not tokens or any(len(row) != GEOMETRY_TOKEN_DIM for row in tokens):
        raise ValueError("T10 junction geometry representation is invalid")
    relation_edges = _geometry_relation_edges(
        [
            (
                GEOMETRY_ROLE_INDEX[record.role],
                record.object_id,
                record.role,
                record.geometry,
                record.properties,
            )
            for record in records
        ],
        spans,
    )
    return {
        "token_features": tokens,
        "object_spans": spans,
        "relation_edges": relation_edges,
        "object_geometries": geometries,
    }


def _weak_label_row(
    feature: Mapping[str, Any],
    label: Mapping[str, Any],
    audit: Mapping[str, Any],
    *,
    split: str,
    available_objects: set[str],
    surface_object_ids: Sequence[str] = (),
    complete_gold: T10CompleteJunctionGold | None = None,
    complete_gold_node_points: Mapping[str, Point] | None = None,
    anchor_point: Point | None = None,
    object_geometries: Mapping[str, BaseGeometry] | None = None,
) -> dict[str, Any]:
    task_labels = {task: "" for task in TASK_CLASSES}
    task_masks = {task: False for task in TASK_CLASSES}
    _set_task(task_labels, task_masks, "t07_step1", audit.get("t07_step1_status"))
    _set_task(task_labels, task_masks, "t07_step2", audit.get("t07_step2_status"))
    route = _route_label(audit)
    surface_state = _surface_state(audit, route)
    _set_task(
        task_labels,
        task_masks,
        "surface_mode",
        _surface_mode(audit, route=route, surface_state=surface_state),
    )
    _set_task(task_labels, task_masks, "surface_state", surface_state)
    _set_task(
        task_labels,
        task_masks,
        "relation_state",
        _relation_state(audit, route),
    )
    _set_task(
        task_labels,
        task_masks,
        "junctionization_action",
        audit.get("t05_junctionization_action"),
    )
    reason = str(label.get("label_reason") or "")
    status = int(label.get("status_label", 3))
    final_state = {
        0: "SUCCESS",
        1: "NO_RCSD_EVIDENCE",
        2: "QUALITY_ISSUE",
        3: "QUALITY_ISSUE",
    }[status]
    final_mask = bool(label.get("status_supervised")) and not reason.startswith(
        "t05:relation_record_absent"
    )
    if final_mask:
        _set_task(task_labels, task_masks, "final_state", final_state)

    candidate_object_sets = _member_object_sets(feature, label)
    object_sets = [
        list(option)
        for option in candidate_object_sets
        if option and set(option).issubset(available_objects)
    ]
    roles = sorted(
        {
            value.partition(":")[0]
            for option in object_sets
            for value in option
            if value.partition(":")[0] in {"NODE", "ROAD"}
        }
    )
    first = object_sets[0] if object_sets else []
    surface_targets = tuple(sorted(set(str(value) for value in surface_object_ids)))
    surface_required = task_labels["surface_mode"] == "EXISTING_RCSD_INTERSECTION"
    surface_reachable = bool(surface_targets) and set(surface_targets).issubset(
        available_objects
    )
    signature = hashlib.sha256(
        json.dumps(
            {"tasks": task_labels, "objects": object_sets},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    result = {
        "sample_id": str(feature["sample_id"]),
        "split": split,
        "sample_weight": 0.7,
        "task_labels": task_labels,
        "task_masks": task_masks,
        "candidate_acceptable_indices": list(
            label.get("candidate_acceptable_indices") or ()
        ),
        "candidate_supervised": bool(label.get("candidate_supervised")),
        "candidate_target_required": bool(label.get("candidate_supervised")),
        "member_acceptable_sets": list(label.get("member_acceptable_sets") or ()),
        "member_supervised": bool(label.get("member_supervised")),
        "member_target_required": bool(label.get("member_supervised")),
        "raw_object_target_object_ids": first,
        "raw_object_target_object_sets": object_sets,
        "raw_object_supervision_roles": roles,
        "raw_object_target_required": bool(object_sets),
        "raw_object_supervised": bool(object_sets),
        "raw_object_target_kind": roles[0] if len(roles) == 1 else "",
        "raw_object_target_ids": [value.partition(":")[2] for value in first],
        "surface_object_target_object_sets": (
            [list(surface_targets)] if surface_reachable else []
        ),
        "surface_object_target_required": surface_required,
        "surface_object_supervised": bool(surface_required and surface_reachable),
        "break_position_targets": [],
        "selected_main_target": None,
        "surface_grid_indices": [],
        "surface_grid_supervised": False,
        "surface_grid_clipped_area_ratio": 0.0,
        "junction_node_point_targets": [],
        "complete_junction_supervised": False,
        "topology_geometry_supervised": False,
        "complete_relation_plan_supervised": False,
        "complete_relation_object_supervised": False,
        "relation_object_supervision_scope": (
            "POSITIVE_PARTIAL" if object_sets else "MASKED"
        ),
        "terminal_business_signature": signature,
        "weak_label_reason": reason,
    }
    manual_gold = _manual_relation_gold(reason, candidate_object_sets)
    if manual_gold is not None:
        _overlay_manual_relation_gold(
            result,
            feature=feature,
            manual_gold=manual_gold,
            available_objects=available_objects,
        )
    elif _manual_relation_claimed(reason):
        _mask_lower_priority_relation_gold(result, reason=reason)
    elif complete_gold is not None:
        if anchor_point is None or object_geometries is None:
            raise ValueError("complete T10 relation Gold lacks geometry context")
        _overlay_complete_relation_gold(
            result,
            feature=feature,
            complete_gold=complete_gold,
            complete_gold_node_points=complete_gold_node_points or {},
            anchor_point=anchor_point,
            object_geometries=object_geometries,
        )
    return result


def _member_object_sets(
    feature: Mapping[str, Any],
    label: Mapping[str, Any],
) -> tuple[tuple[str, ...], ...]:
    if not bool(label.get("member_supervised")):
        return ()
    member_ids = tuple(
        str(value) for value in feature.get("structural_member_ids") or ()
    )
    result = {
        tuple(
            sorted(
                {
                    member_ids[int(index)]
                    for index in option
                    if 0 <= int(index) < len(member_ids)
                }
            )
        )
        for option in label.get("member_acceptable_sets") or ()
    }
    return tuple(sorted((option for option in result if option)))


def _manual_relation_gold(
    reason: str,
    acceptable_object_sets: Sequence[Sequence[str]],
) -> _ManualRelationGold | None:
    if reason.startswith("t11_manual:no_valid_relation:"):
        return _ManualRelationGold(
            action="failure_relation",
            relation_object_kind="NONE",
            acceptable_object_sets=((),),
            final_state="QUALITY_ISSUE",
            supervision_scope="T11_MANUAL_COMPLETE_RELATION",
        )
    if reason.startswith("user_confirmed:no_rcsd_evidence:"):
        return _ManualRelationGold(
            action="failure_relation",
            relation_object_kind="NONE",
            acceptable_object_sets=((),),
            final_state="NO_RCSD_EVIDENCE",
            supervision_scope="USER_CONFIRMED_COMPLETE_RELATION",
        )
    positive_scope = (
        "T11_MANUAL_COMPLETE_RELATION"
        if reason.startswith("t11_manual:")
        else "USER_CONFIRMED_COMPLETE_RELATION"
        if reason.startswith(
            (
                "user_anchor_gold:success_confirmed:",
                "user_phase1_anchor:success_unique:",
                "user_manual_anchor:",
            )
        )
        else ""
    )
    if not positive_scope:
        return None
    options = tuple(
        sorted(
            {
                tuple(sorted(set(str(value) for value in option)))
                for option in acceptable_object_sets
                if option
            }
        )
    )
    if not options:
        return None
    roles = {
        value.partition(":")[0]
        for option in options
        for value in option
    }
    if len(roles) != 1 or not roles.issubset({"NODE", "ROAD"}):
        raise ValueError(f"manual relation object roles are invalid: {reason}")
    role = next(iter(roles))
    if reason.startswith("t11_manual:1v1_rcsd_junction:"):
        if role != "NODE":
            raise ValueError("T11 1v1 Junction Gold object role is invalid")
        actions = {
            "direct_relation" if len(option) == 1 else "group_existing_rcsd_nodes"
            for option in options
        }
        if len(actions) != 1:
            raise ValueError("T11 1v1 Junction raw Node plan is ambiguous")
        action = next(iter(actions))
    elif reason.startswith("t11_manual:1vn_rcsd_junction:"):
        if role != "NODE" or any(len(option) < 2 for option in options):
            raise ValueError("T11 1vN Junction Gold cardinality is invalid")
        action = "group_existing_rcsd_nodes"
    elif reason.startswith("t11_manual:1v1_rcsd_road:"):
        if role != "ROAD":
            raise ValueError("T11 Road Gold object role is invalid")
        action = "split_rcsdroad_generate_rcsdnode"
    else:
        actions = {
            "split_rcsdroad_generate_rcsdnode"
            if role == "ROAD"
            else "direct_relation"
            if len(option) == 1
            else "group_existing_rcsd_nodes"
            for option in options
        }
        if len(actions) != 1:
            raise ValueError(f"manual relation action is ambiguous: {reason}")
        action = next(iter(actions))
    return _ManualRelationGold(
        action=action,
        relation_object_kind=role,
        acceptable_object_sets=options,
        final_state="SUCCESS",
        supervision_scope=positive_scope,
    )


def _manual_relation_claimed(reason: str) -> bool:
    return reason.startswith(
        (
            "t11_manual:",
            "user_anchor_gold:success_confirmed:",
            "user_phase1_anchor:success_unique:",
            "user_manual_anchor:",
            "user_confirmed:no_rcsd_evidence:",
        )
    )


def _mask_lower_priority_relation_gold(
    row: dict[str, Any],
    *,
    reason: str,
) -> None:
    if reason.startswith("t11_manual:1v1_rcsd_road:"):
        row["task_labels"]["junctionization_action"] = (
            "split_rcsdroad_generate_rcsdnode"
        )
        row["task_masks"]["junctionization_action"] = True
        row["task_labels"]["final_state"] = "SUCCESS"
        row["task_masks"]["final_state"] = True
        row["task_masks"]["relation_state"] = False
    row["candidate_acceptable_indices"] = []
    row["candidate_supervised"] = False
    row["candidate_target_required"] = False
    row["member_acceptable_sets"] = []
    row["member_supervised"] = False
    row["member_target_required"] = False
    row["raw_object_target_object_ids"] = []
    row["raw_object_target_object_sets"] = []
    row["raw_object_supervision_roles"] = []
    row["raw_object_target_required"] = False
    row["raw_object_supervised"] = False
    row["raw_object_target_kind"] = ""
    row["raw_object_target_ids"] = []
    row["junction_node_point_targets"] = []
    row["break_position_targets"] = []
    row["selected_main_target"] = None
    row["complete_junction_supervised"] = False
    row["topology_geometry_supervised"] = False
    row["complete_relation_plan_supervised"] = False
    row["complete_relation_object_supervised"] = False
    row["relation_object_supervision_scope"] = (
        "MANUAL_RELATION_OBJECT_UNREACHABLE"
    )
    row["terminal_business_signature"] = hashlib.sha256(
        json.dumps(
            {"tasks": row["task_labels"], "reason": reason, "objects": "MASKED"},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _overlay_manual_relation_gold(
    row: dict[str, Any],
    *,
    feature: Mapping[str, Any],
    manual_gold: _ManualRelationGold,
    available_objects: set[str],
) -> None:
    options = manual_gold.acceptable_object_sets
    positive_options = tuple(option for option in options if option)
    object_reachable = bool(positive_options) and all(
        set(option).issubset(available_objects) for option in positive_options
    )
    member_ids = tuple(
        str(value) for value in feature.get("structural_member_ids") or ()
    )
    member_index = {value: index for index, value in enumerate(member_ids)}
    member_reachable = bool(positive_options) and all(
        set(option).issubset(member_index) for option in positive_options
    )
    first = positive_options[0] if positive_options else ()

    # Human adjudication wins the label semantics, while the enclosing T10
    # Case keeps the user-confirmed 0.7 sample weight.
    row["sample_weight"] = 0.7
    row["task_labels"]["junctionization_action"] = manual_gold.action
    row["task_masks"]["junctionization_action"] = True
    row["task_labels"]["final_state"] = manual_gold.final_state
    row["task_masks"]["final_state"] = True
    row["task_masks"]["relation_state"] = False
    row["candidate_acceptable_indices"] = []
    row["candidate_supervised"] = False
    row["candidate_target_required"] = False
    row["complete_relation_plan_supervised"] = True
    row["complete_relation_object_supervised"] = (
        object_reachable or manual_gold.action == "failure_relation"
    )
    row["relation_object_supervision_scope"] = manual_gold.supervision_scope
    row["complete_junction_supervised"] = True
    row["raw_object_target_kind"] = manual_gold.relation_object_kind
    row["raw_object_target_ids"] = [value.partition(":")[2] for value in first]
    row["raw_object_target_object_ids"] = list(first)
    row["raw_object_target_object_sets"] = (
        [list(option) for option in positive_options] if object_reachable else []
    )
    row["raw_object_supervision_roles"] = (
        [manual_gold.relation_object_kind]
        if manual_gold.relation_object_kind in {"NODE", "ROAD"}
        else []
    )
    row["raw_object_target_required"] = bool(positive_options)
    row["raw_object_supervised"] = object_reachable
    row["member_target_required"] = bool(positive_options)
    row["member_supervised"] = member_reachable
    row["member_acceptable_sets"] = (
        [
            [member_index[value] for value in option]
            for option in positive_options
        ]
        if member_reachable
        else []
    )
    row["junction_node_point_targets"] = []
    row["break_position_targets"] = []
    row["selected_main_target"] = None
    row["topology_geometry_supervised"] = False
    row["terminal_business_signature"] = hashlib.sha256(
        json.dumps(
            {
                "tasks": row["task_labels"],
                "action": manual_gold.action,
                "objects": options,
                "scope": manual_gold.supervision_scope,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _overlay_complete_relation_gold(
    row: dict[str, Any],
    *,
    feature: Mapping[str, Any],
    complete_gold: T10CompleteJunctionGold,
    complete_gold_node_points: Mapping[str, Point],
    anchor_point: Point,
    object_geometries: Mapping[str, BaseGeometry],
) -> None:
    action = str(row["task_labels"].get("junctionization_action") or "")
    if action != complete_gold.action:
        raise ValueError(
            "T10 complete relation action differs from current task label: "
            f"{complete_gold.target_id}/{action}/{complete_gold.action}"
        )
    complete_objects = tuple(complete_gold.complete_object_ids)
    geometry_reachable = set(complete_objects).issubset(object_geometries)
    member_ids = tuple(
        str(value) for value in feature.get("structural_member_ids") or ()
    )
    member_index = {value: index for index, value in enumerate(member_ids)}
    member_reachable = set(complete_objects).issubset(member_index)
    object_decodable = geometry_reachable and (
        bool(complete_objects) or complete_gold.action == "failure_relation"
    )

    row["complete_relation_plan_supervised"] = True
    row["complete_relation_object_supervised"] = object_decodable
    row["relation_object_supervision_scope"] = "COMPLETE_RELATION_PLAN"
    row["complete_junction_supervised"] = True
    row["raw_object_target_kind"] = complete_gold.relation_object_kind
    row["raw_object_target_ids"] = [
        value.partition(":")[2] for value in complete_objects
    ]
    row["raw_object_target_object_ids"] = list(complete_objects)
    row["raw_object_target_object_sets"] = (
        [list(complete_objects)] if geometry_reachable and complete_objects else []
    )
    row["raw_object_supervision_roles"] = (
        [complete_gold.relation_object_kind]
        if complete_gold.relation_object_kind in {"NODE", "ROAD"}
        else []
    )
    row["raw_object_target_required"] = bool(complete_objects)
    row["raw_object_supervised"] = bool(geometry_reachable and complete_objects)
    row["member_target_required"] = bool(complete_objects)
    row["member_supervised"] = bool(member_reachable and complete_objects)
    row["member_acceptable_sets"] = (
        [[member_index[value] for value in complete_objects]]
        if member_reachable and complete_objects
        else []
    )

    topology_label = complete_gold.topology_label()
    node_targets, node_targets_complete = _complete_gold_node_targets(
        complete_gold,
        node_points=complete_gold_node_points,
        anchor_point=anchor_point,
    )
    topology = _structured_topology_targets(
        topology_label,
        node_rows=node_targets,
        object_geometries=object_geometries,
        anchor_point=anchor_point,
    )
    topology_required = row["task_labels"]["final_state"] == "SUCCESS"
    row["junction_node_point_targets"] = node_targets
    row["break_position_targets"] = list(topology["break_position_targets"])
    row["selected_main_target"] = topology["selected_main_target"]
    row["topology_geometry_supervised"] = bool(
        topology_required
        and node_targets_complete
        and topology["topology_complete"]
    )
    row["terminal_business_signature"] = hashlib.sha256(
        json.dumps(
            {
                "tasks": row["task_labels"],
                "action": complete_gold.action,
                "objects": complete_objects,
                "main": complete_gold.selected_main_rcsdnode_id,
                "breaks": row["break_position_targets"],
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _read_complete_gold_node_points(
    plans: Mapping[str, T10CompleteJunctionGold],
) -> Mapping[str, Point]:
    required = {
        node_id
        for plan in plans.values()
        for node_id in _complete_gold_node_ids(plan)
    }
    if not required:
        return {}
    paths = {plan.rcsdnode_output_path.resolve(strict=True) for plan in plans.values()}
    if len(paths) != 1:
        raise ValueError("one T10 Case has multiple T05 Node outputs")
    points: dict[str, Point] = {}
    with fiona.open(next(iter(paths))) as source:
        if source.crs.to_epsg() != 3857:
            raise ValueError("T10 T05 Node output CRS must be EPSG:3857")
        for feature in source:
            if not feature["geometry"]:
                continue
            properties = {
                str(key).casefold(): value
                for key, value in dict(feature["properties"]).items()
            }
            node_id = _canonical_id(
                properties.get("id")
                or properties.get("nodeid")
                or properties.get("node_id")
            )
            if node_id not in required:
                continue
            geometry = shape(feature["geometry"])
            point = geometry if geometry.geom_type == "Point" else geometry.centroid
            points[node_id] = Point(point.x, point.y)
    return points


def _complete_gold_node_targets(
    plan: T10CompleteJunctionGold,
    *,
    node_points: Mapping[str, Point],
    anchor_point: Point,
) -> tuple[list[dict[str, Any]], bool]:
    node_ids = _complete_gold_node_ids(plan)
    targets = [
        {
            "node_id": node_id,
            "dx_m": float(node_points[node_id].x - anchor_point.x),
            "dy_m": float(node_points[node_id].y - anchor_point.y),
            "is_selected_main": node_id == plan.selected_main_rcsdnode_id,
        }
        for node_id in node_ids
        if node_id in node_points
    ]
    return targets, set(node_points).issuperset(node_ids)


def _complete_gold_node_ids(
    plan: T10CompleteJunctionGold,
) -> tuple[str, ...]:
    if plan.action == "failure_relation":
        return ()
    return tuple(
        sorted(
            set(plan.original_rcsdnode_ids)
            | set(plan.new_rcsdnode_ids)
            | set(plan.grouped_rcsdnode_ids)
            | {plan.selected_main_rcsdnode_id}
        )
    )


def _route_label(audit: Mapping[str, Any]) -> str:
    step1 = str(audit.get("t07_step1_status") or "")
    step2 = str(audit.get("t07_step2_status") or "")
    if step1 == "no":
        return "NO_RCSD_EVIDENCE"
    if step2 in {"yes", "fail1", "fail2"}:
        return "T07"
    if bool(audit.get("t03_available")):
        return "T03"
    if bool(audit.get("t04_available")):
        return "T04"
    return "UNRESOLVED"


def _surface_mode(
    audit: Mapping[str, Any],
    *,
    route: str,
    surface_state: str,
) -> str:
    if route == "T07" and str(audit.get("t07_step2_status") or "") == "yes":
        return "EXISTING_RCSD_INTERSECTION"
    if route in {"T03", "T04"} and surface_state == "accepted":
        return "VIRTUAL_SURFACE"
    if route == "NO_RCSD_EVIDENCE" or surface_state == "rejected":
        return "NO_VALID_SURFACE"
    return "AMBIGUOUS"


def _surface_state(audit: Mapping[str, Any], route: str) -> str:
    if route == "T03":
        return str(audit.get("t03_step7_state") or "")
    if route == "T04":
        return str(audit.get("t04_final_state") or "")
    if route == "T07" and str(audit.get("t07_step2_status") or "") == "yes":
        return "accepted"
    return ""


def _relation_state(audit: Mapping[str, Any], route: str) -> str:
    if route == "T07":
        return str(audit.get("t07_relation_state") or "")
    if route == "T03":
        return str(audit.get("t03_relation_state") or "")
    if route == "T04":
        return str(audit.get("t04_relation_state") or "")
    return ""


def _set_task(
    labels: dict[str, str],
    masks: dict[str, bool],
    task: str,
    raw: Any,
) -> None:
    value = str(raw if raw is not None else "").strip()
    if not value:
        return
    if value not in TASK_CLASSES[task]:
        raise ValueError(f"unknown T10 weak {task} label: {value}")
    labels[task] = value
    masks[task] = True


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _counts(values: Iterable[Any]) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _read_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _write_jsonl(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                + "\n"
            )


def _write_jsonl_row(stream: Any, row: Mapping[str, Any]) -> None:
    stream.write(
        json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    )


__all__ = [
    "T10JointStoreInputs",
    "assign_t10_case_splits",
    "write_t10_junction_joint_store",
]
