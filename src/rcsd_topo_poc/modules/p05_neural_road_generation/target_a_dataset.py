from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import fiona
import numpy as np
import torch
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_evidence import (
    ANCHOR_ARM_FEATURE_DIM,
    ANCHOR_MEMBER_LOCAL_FEATURE_DIM,
    ANCHOR_MEMBER_RELATION_DIM,
    AnchorStructuralEvidence,
    validate_anchor_structural_evidence,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_members import (
    anchor_candidate_member_tensors,
    ordered_anchor_candidate_members,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_relations import (
    ANCHOR_CANDIDATE_RELATION_DIM,
    anchor_candidate_relation_matrix,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
    TARGET_A_SCHEMA_VERSION,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetABatchTensors,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    TargetATrainingBatch,
    TargetATrainingTargets,
    iter_case_group_folds,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


ANCHOR_FAMILIES = ("T03", "T03_Error", "T04", "T04_Error")
ANCHOR_STATUS_INDEX = {status: index for index, status in enumerate(AnchorStatus)}
TARGET_A_FEATURE_DIM = 64


@dataclass(frozen=True)
class TargetACaseBundle:
    case_key: str
    family: str
    business_id: str
    case_root: Path
    source_case_root: Path
    run_summary: Path
    t01_segment: Path
    t01_roads: Path
    t01_nodes: Path
    t05_relation: Path
    t06_segment_relation: Path
    t06_frcsd_road: Path
    t06_frcsd_node: Path
    target_weight: float
    target_segment_id: str


@dataclass(frozen=True)
class AnchorPretrainExample:
    sample_id: str
    case_key: str
    anchor_id: str
    fold: int
    object_features: tuple[float, ...]
    candidate_ids: tuple[str, ...]
    candidate_features: tuple[tuple[float, ...], ...]
    status_label: int
    candidate_acceptable_indices: tuple[int, ...]
    preferred_candidate_index: int
    candidate_supervised: bool
    sample_weight: float
    input_hashes: tuple[tuple[str, str], ...]
    label_reason: str
    dependency_anchor_ids: tuple[str, ...] = ()
    status_supervised: bool = True
    gate_label: int = 0
    gate_supervised: bool = False
    structural_member_ids: tuple[str, ...] = ()
    swsd_arm_features: tuple[tuple[float, ...], ...] = ()
    member_arm_features: tuple[
        tuple[tuple[float, ...], ...],
        ...,
    ] = ()
    member_local_features: tuple[tuple[float, ...], ...] = ()
    member_relation_edges: tuple[
        tuple[int, int, tuple[float, ...]],
        ...,
    ] = ()
    member_acceptable_sets: tuple[tuple[int, ...], ...] = ()
    member_supervised: bool = False

    def __post_init__(self) -> None:
        if len(self.object_features) != TARGET_A_FEATURE_DIM:
            raise ValueError("Target A anchor object feature dimension differs")
        if not self.candidate_features:
            raise ValueError("Target A anchor example must retain one padded candidate")
        if len(self.candidate_ids) != len(self.candidate_features):
            raise ValueError("Target A anchor candidate IDs/features differ")
        if any(not candidate_id for candidate_id in self.candidate_ids):
            raise ValueError("Target A anchor candidate ID is empty")
        if any(len(row) != TARGET_A_FEATURE_DIM for row in self.candidate_features):
            raise ValueError("Target A anchor candidate feature dimension differs")
        if not 0 <= self.status_label < len(AnchorStatus):
            raise ValueError("Target A anchor status label is invalid")
        if self.sample_weight <= 0:
            raise ValueError("Target A sample weight must be positive")
        if self.gate_supervised and self.gate_label not in {0, 1}:
            raise ValueError("Target A anchor gate label is invalid")
        if self.candidate_supervised and not self.candidate_acceptable_indices:
            raise ValueError("candidate-supervised anchor lacks an acceptable candidate")
        if any(not value for value in self.dependency_anchor_ids):
            raise ValueError("Target A anchor dependency ID is empty")
        if len(set(self.dependency_anchor_ids)) != len(
            self.dependency_anchor_ids
        ):
            raise ValueError("Target A anchor dependency IDs are duplicated")
        if self.structural_member_ids:
            expected_members = tuple(
                f"{'ROAD' if is_road else 'NODE'}:{member_id}"
                for is_road, member_id in ordered_anchor_candidate_members(
                    self.candidate_ids,
                    self.candidate_features,
                )
            )
            if self.structural_member_ids != expected_members:
                raise ValueError(
                    "Target A structural members differ from candidates"
                )
            validate_anchor_structural_evidence(
                AnchorStructuralEvidence(
                    member_ids=self.structural_member_ids,
                    swsd_arm_features=self.swsd_arm_features,
                    member_arm_features=self.member_arm_features,
                    member_local_features=self.member_local_features,
                    member_relation_edges=self.member_relation_edges,
                )
            )
        elif (
            self.swsd_arm_features
            or self.member_arm_features
            or self.member_local_features
            or self.member_relation_edges
        ):
            raise ValueError(
                "Target A structural evidence lacks member alignment"
            )
        if self.member_supervised and not self.member_acceptable_sets:
            raise ValueError(
                "member-supervised anchor lacks an acceptable member set"
            )
        if self.member_acceptable_sets and not self.member_supervised:
            raise ValueError(
                "anchor member sets require member supervision"
            )
        if len(set(self.member_acceptable_sets)) != len(
            self.member_acceptable_sets
        ):
            raise ValueError("anchor acceptable member sets are duplicated")
        for acceptable in self.member_acceptable_sets:
            if not acceptable or len(set(acceptable)) != len(acceptable):
                raise ValueError("anchor acceptable member set is invalid")
            if any(
                index < 0 or index >= len(self.structural_member_ids)
                for index in acceptable
            ):
                raise ValueError(
                    "anchor acceptable member index is outside the set"
                )
            prefixes = {
                self.structural_member_ids[index].partition(":")[0]
                for index in acceptable
            }
            if prefixes - {"NODE", "ROAD"} or len(prefixes) != 1:
                raise ValueError(
                    "anchor acceptable member set must have one object type"
                )


def discover_target_a_case_bundles(
    *,
    poc_data_root: Path,
    full_baseline_root: Path,
    six_case_baseline_root: Path,
    excluded_case_keys: Iterable[str] = ("T10-Error:1213556_1263661",),
) -> list[TargetACaseBundle]:
    poc_root = normalize_runtime_path(poc_data_root).resolve(strict=True)
    excluded = set(excluded_case_keys)
    selected: dict[str, TargetACaseBundle] = {}
    baseline_specs = (
        (normalize_runtime_path(six_case_baseline_root).resolve(strict=True), {"T10"}),
        (
            normalize_runtime_path(full_baseline_root).resolve(strict=True),
            {"T10-Error", "T10-Error-2"},
        ),
    )
    for baseline_root, allowed_families in baseline_specs:
        summary = _read_json(baseline_root / "baseline_summary.json")
        entries = summary.get("package_summaries")
        if not isinstance(entries, list):
            entries = [
                {
                    "source_root": summary.get("source_root"),
                    "run_root": summary.get("run_root"),
                }
            ]
        for entry in entries:
            source_root = normalize_runtime_path(
                str(entry.get("source_root") or "")
            ).resolve(strict=True)
            family = source_root.name
            if family not in allowed_families:
                continue
            expected_source = (poc_root / family).resolve(strict=True)
            if source_root != expected_source:
                raise ValueError(
                    f"Target A baseline source differs from POC_Data: {source_root}"
                )
            run_root = normalize_runtime_path(
                str(entry.get("run_root") or "")
            ).resolve(strict=True)
            for case_dir in sorted(
                (run_root / "cases").iterdir(),
                key=lambda path: path.name.casefold(),
            ):
                if not case_dir.is_dir():
                    continue
                business_id = (
                    case_dir.name[len("segment_") :]
                    if case_dir.name.startswith("segment_")
                    else case_dir.name
                )
                case_key = f"{family}:{business_id}"
                if case_key in excluded:
                    continue
                if case_key in selected:
                    raise ValueError(f"duplicate Target A Case bundle: {case_key}")
                run_summary = case_dir / "t10_e2e_case_run_summary.json"
                payload = _read_json(run_summary)
                if not (
                    bool(payload.get("passed"))
                    or str(payload.get("status") or "").casefold() == "passed"
                ):
                    raise ValueError(f"Target A baseline Case is not passed: {case_key}")
                handoffs = dict(
                    (payload.get("t06_funnel") or {}).get("handoffs") or {}
                )
                required = {
                    "t01_segment",
                    "t01_roads",
                    "t05_intersection_match_all",
                    "t06_swsd_frcsd_segment_relation",
                    "t06_frcsd_road",
                    "t06_frcsd_node",
                }
                missing = sorted(required - set(handoffs))
                if missing:
                    raise ValueError(f"{case_key}: missing handoffs {missing}")
                paths = {
                    role: normalize_runtime_path(handoffs[role]).resolve(strict=True)
                    for role in required
                }
                selected[case_key] = TargetACaseBundle(
                    case_key=case_key,
                    family=family,
                    business_id=business_id,
                    case_root=case_dir.resolve(),
                    source_case_root=(poc_root / family / business_id).resolve(
                        strict=True
                    ),
                    run_summary=run_summary.resolve(),
                    t01_segment=paths["t01_segment"],
                    t01_roads=paths["t01_roads"],
                    t01_nodes=(paths["t01_roads"].parent / "nodes.gpkg").resolve(
                        strict=True
                    ),
                    t05_relation=paths["t05_intersection_match_all"],
                    t06_segment_relation=paths[
                        "t06_swsd_frcsd_segment_relation"
                    ],
                    t06_frcsd_road=paths["t06_frcsd_road"],
                    t06_frcsd_node=paths["t06_frcsd_node"],
                    target_weight=0.7,
                    target_segment_id=business_id if family != "T10" else "",
                )
    return [selected[key] for key in sorted(selected)]


def build_anchor_pretrain_examples(
    poc_data_root: Path,
    *,
    fold_count: int = 5,
) -> list[AnchorPretrainExample]:
    root = normalize_runtime_path(poc_data_root).resolve(strict=True)
    case_keys = [
        f"{family}:{case_dir.name}"
        for family in ANCHOR_FAMILIES
        for case_dir in _case_directories(root / family)
    ]
    folds = iter_case_group_folds(case_keys, fold_count=fold_count)
    examples: list[AnchorPretrainExample] = []
    for family in ANCHOR_FAMILIES:
        for case_root in _case_directories(root / family):
            case_key = f"{family}:{case_root.name}"
            manifest_path = case_root / "manifest.json"
            manifest = _read_json(manifest_path)
            target_id = str(manifest.get("mainnodeid") or case_root.name)
            inputs = _single_point_inputs(case_root)
            target_point = _target_point(inputs["nodes"], target_id)
            object_features = _anchor_object_features(inputs, target_point)
            candidate_rows, candidate_ids = _anchor_candidates(inputs, target_point)
            status = (
                AnchorStatus.ABSTAIN
                if family.endswith("_Error")
                else AnchorStatus.SUCCESS
            )
            # The single-point success/failure terminal is user-confirmed at
            # weight 1.0. The historical per-object relation output was held in
            # ignored P05 artifacts and is not reconstructed from folder names,
            # so candidate selection remains masked in this first stage.
            acceptable: tuple[int, ...] = ()
            preferred = -1
            examples.append(
                AnchorPretrainExample(
                    sample_id=_sample_id(case_key, manifest_path),
                    case_key=case_key,
                    anchor_id=target_id,
                    fold=folds[case_key],
                    object_features=tuple(float(value) for value in object_features),
                    candidate_ids=tuple(str(value) for value in candidate_ids),
                    candidate_features=tuple(
                        tuple(float(value) for value in row) for row in candidate_rows
                    ),
                    status_label=ANCHOR_STATUS_INDEX[status],
                    candidate_acceptable_indices=acceptable,
                    preferred_candidate_index=preferred,
                    candidate_supervised=False,
                    sample_weight=1.0,
                    input_hashes=tuple(
                        sorted(
                            (role, sha256_file(path))
                            for role, path in inputs.items()
                            if path.is_file()
                        )
                    ),
                    label_reason=(
                        "user_confirmed_strategy_replay_success"
                        if status is AnchorStatus.SUCCESS
                        else "user_confirmed_strategy_replay_failure_reason_unspecified"
                    ),
                    dependency_anchor_ids=(target_id,),
                )
            )
            if candidate_ids and len(candidate_rows) != len(candidate_ids):
                raise AssertionError("anchor candidate ids/features differ")
    return sorted(examples, key=lambda row: row.case_key)


def write_anchor_pretraining_stores(
    examples: Sequence[AnchorPretrainExample],
    *,
    output_root: Path,
    run_id: str,
) -> Path:
    root = normalize_runtime_path(output_root).resolve() / run_id
    if root.exists():
        raise FileExistsError(root)
    feature_root = root / "inference_feature_store"
    label_root = root / "training_label_store"
    feature_root.mkdir(parents=True)
    label_root.mkdir()
    feature_path = feature_root / "anchor_features.jsonl"
    label_path = label_root / "anchor_labels.jsonl"
    feature_rows = [
        {
            "sample_id": row.sample_id,
            "case_key": row.case_key,
            "anchor_id": row.anchor_id,
            "fold": row.fold,
            "object_features": row.object_features,
            "candidate_ids": row.candidate_ids,
            "candidate_features": row.candidate_features,
            "input_hashes": row.input_hashes,
            "dependency_anchor_ids": (
                row.dependency_anchor_ids or (row.anchor_id,)
            ),
            "structural_member_ids": row.structural_member_ids,
            "swsd_arm_features": row.swsd_arm_features,
            "member_arm_features": row.member_arm_features,
            "member_local_features": row.member_local_features,
            "member_relation_edges": row.member_relation_edges,
        }
        for row in examples
    ]
    label_rows = [
        {
            "sample_id": row.sample_id,
            "status_label": row.status_label,
            "candidate_acceptable_indices": row.candidate_acceptable_indices,
            "preferred_candidate_index": row.preferred_candidate_index,
            "candidate_supervised": row.candidate_supervised,
            "status_supervised": row.status_supervised,
            "gate_label": row.gate_label,
            "gate_supervised": row.gate_supervised,
            "member_acceptable_sets": row.member_acceptable_sets,
            "member_supervised": row.member_supervised,
            "sample_weight": row.sample_weight,
            "label_reason": row.label_reason,
        }
        for row in examples
    ]
    _write_jsonl(feature_path, feature_rows)
    _write_jsonl(label_path, label_rows)
    leakage = audit_anchor_store_leakage(feature_rows, label_rows)
    manifest = {
        "schema_version": TARGET_A_SCHEMA_VERSION,
        "stage": "ANCHOR_PRETRAIN",
        "example_count": len(examples),
        "case_count": len({row.case_key for row in examples}),
        "fold_counts": _counts(row.fold for row in examples),
        "status_counts": _counts(row.status_label for row in examples),
        "status_supervised_count": sum(row.status_supervised for row in examples),
        "gate_supervised_count": sum(row.gate_supervised for row in examples),
        "gate_label_counts": _counts(
            row.gate_label for row in examples if row.gate_supervised
        ),
        "candidate_supervised_count": sum(row.candidate_supervised for row in examples),
        "member_supervised_count": sum(row.member_supervised for row in examples),
        "dependency_reference_count": sum(
            len(row.dependency_anchor_ids or (row.anchor_id,))
            for row in examples
        ),
        "inference_feature_store": {
            "path": str(feature_path.resolve()),
            "sha256": sha256_file(feature_path),
        },
        "training_label_store": {
            "path": str(label_path.resolve()),
            "sha256": sha256_file(label_path),
        },
        "leakage_audit": leakage,
        "feature_dim": TARGET_A_FEATURE_DIM,
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not leakage["passed"]:
        raise RuntimeError(f"Target A leakage audit failed: {root}")
    return root


def read_anchor_pretraining_stores(
    store_root: Path,
) -> list[AnchorPretrainExample]:
    root = normalize_runtime_path(store_root).resolve(strict=True)
    manifest = _read_json(root / "manifest.json")
    if manifest.get("schema_version") != TARGET_A_SCHEMA_VERSION:
        raise ValueError(f"Target A anchor store schema differs: {root}")
    feature_path = root / "inference_feature_store" / "anchor_features.jsonl"
    label_path = root / "training_label_store" / "anchor_labels.jsonl"
    feature_rows = _read_jsonl(feature_path)
    label_rows = _read_jsonl(label_path)
    leakage = audit_anchor_store_leakage(feature_rows, label_rows)
    if not leakage["passed"]:
        raise RuntimeError(f"Target A anchor store leakage audit failed: {root}")
    expected_feature_hash = str(
        (manifest.get("inference_feature_store") or {}).get("sha256") or ""
    )
    expected_label_hash = str(
        (manifest.get("training_label_store") or {}).get("sha256") or ""
    )
    if expected_feature_hash != sha256_file(feature_path):
        raise ValueError(f"Target A anchor feature store hash differs: {feature_path}")
    if expected_label_hash != sha256_file(label_path):
        raise ValueError(f"Target A anchor label store hash differs: {label_path}")
    label_by_id = {str(row["sample_id"]): row for row in label_rows}
    examples: list[AnchorPretrainExample] = []
    for feature in feature_rows:
        sample_id = str(feature["sample_id"])
        label = label_by_id[sample_id]
        examples.append(
            AnchorPretrainExample(
                sample_id=sample_id,
                case_key=str(feature["case_key"]),
                anchor_id=str(feature.get("anchor_id") or ""),
                fold=int(feature["fold"]),
                object_features=tuple(
                    float(value) for value in feature["object_features"]
                ),
                candidate_ids=tuple(
                    str(value)
                    for value in (
                        feature.get("candidate_ids")
                        or [
                            f"INDEX:{index}"
                            for index, _ in enumerate(
                                feature["candidate_features"]
                            )
                        ]
                    )
                ),
                candidate_features=tuple(
                    tuple(float(value) for value in row)
                    for row in feature["candidate_features"]
                ),
                status_label=int(label["status_label"]),
                candidate_acceptable_indices=tuple(
                    int(value)
                    for value in label["candidate_acceptable_indices"]
                ),
                preferred_candidate_index=int(
                    label["preferred_candidate_index"]
                ),
                candidate_supervised=bool(label["candidate_supervised"]),
                sample_weight=float(label["sample_weight"]),
                input_hashes=tuple(
                    (str(role), str(digest))
                    for role, digest in feature["input_hashes"]
                ),
                label_reason=str(label["label_reason"]),
                dependency_anchor_ids=tuple(
                    str(value)
                    for value in (
                        feature.get("dependency_anchor_ids")
                        or [feature.get("anchor_id") or ""]
                    )
                    if str(value)
                ),
                status_supervised=bool(label.get("status_supervised", True)),
                gate_label=int(label.get("gate_label", 0)),
                gate_supervised=bool(label.get("gate_supervised", False)),
                structural_member_ids=tuple(
                    str(value)
                    for value in (
                        feature.get("structural_member_ids") or ()
                    )
                ),
                swsd_arm_features=tuple(
                    tuple(float(value) for value in row)
                    for row in (
                        feature.get("swsd_arm_features") or ()
                    )
                ),
                member_arm_features=tuple(
                    tuple(
                        tuple(float(value) for value in arm)
                        for arm in member
                    )
                    for member in (
                        feature.get("member_arm_features") or ()
                    )
                ),
                member_local_features=tuple(
                    tuple(float(value) for value in row)
                    for row in (
                        feature.get("member_local_features") or ()
                    )
                ),
                member_relation_edges=tuple(
                    (
                        int(edge[0]),
                        int(edge[1]),
                        tuple(float(value) for value in edge[2]),
                    )
                    for edge in (
                        feature.get("member_relation_edges") or ()
                    )
                ),
                member_acceptable_sets=tuple(
                    tuple(int(index) for index in acceptable)
                    for acceptable in (
                        label.get("member_acceptable_sets") or ()
                    )
                ),
                member_supervised=bool(
                    label.get("member_supervised", False)
                ),
            )
        )
    if len(examples) != int(manifest.get("example_count") or -1):
        raise ValueError(f"Target A anchor example count differs: {root}")
    return sorted(examples, key=lambda row: row.case_key)


def audit_anchor_store_leakage(
    feature_rows: Sequence[Mapping[str, Any]],
    label_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    forbidden_feature_keys = {
        "status_label",
        "gate_label",
        "gate_supervised",
        "label_reason",
        "candidate_acceptable_indices",
        "preferred_candidate_index",
        "member_acceptable_sets",
        "member_supervised",
        "sample_weight",
        "t03_status",
        "t04_status",
        "t05_relation",
        "t06_relation",
    }
    forbidden_label_keys = {
        "object_features",
        "candidate_features",
        "adjacency",
        "swsd_arm_features",
        "member_arm_features",
        "member_local_features",
        "member_relation_edges",
    }
    feature_violations = sorted(
        {
            key
            for row in feature_rows
            for key in row
            if key in forbidden_feature_keys
        }
    )
    label_violations = sorted(
        {key for row in label_rows for key in row if key in forbidden_label_keys}
    )
    feature_ids = [str(row["sample_id"]) for row in feature_rows]
    label_ids = [str(row["sample_id"]) for row in label_rows]
    join_ok = (
        len(feature_ids) == len(set(feature_ids))
        and len(label_ids) == len(set(label_ids))
        and sorted(feature_ids) == sorted(label_ids)
    )
    return {
        "passed": not feature_violations and not label_violations and join_ok,
        "feature_forbidden_key_count": len(feature_violations),
        "feature_forbidden_keys": feature_violations,
        "label_feature_key_count": len(label_violations),
        "label_feature_keys": label_violations,
        "one_to_one_join": join_ok,
        "terminal_path_feature_count": 0,
        "absolute_coordinate_feature_count": 0,
        "raw_id_embedding_count": 0,
    }


def collate_anchor_pretrain_batch(
    examples: Sequence[AnchorPretrainExample],
    *,
    include_candidate_relations: bool = False,
) -> TargetATrainingBatch:
    if not examples:
        raise ValueError("cannot collate an empty Target A batch")
    batch_size = len(examples)
    candidate_count = max(len(row.candidate_features) for row in examples)
    member_rows = tuple(
        anchor_candidate_member_tensors(
            row.candidate_ids,
            row.candidate_features,
        )
        for row in examples
    )
    member_count = max(
        row.member_features.shape[0]
        for row in member_rows
    )
    member_option_count = max(
        1,
        max(len(row.member_acceptable_sets) for row in examples),
    )
    object_features = torch.tensor(
        [[row.object_features] for row in examples],
        dtype=torch.float32,
    )
    object_types = torch.zeros((batch_size, 1), dtype=torch.long)
    object_mask = torch.ones((batch_size, 1), dtype=torch.bool)
    adjacency = torch.ones((batch_size, 1, 1), dtype=torch.bool)
    candidate_features = torch.zeros(
        (batch_size, 1, candidate_count, TARGET_A_FEATURE_DIM),
        dtype=torch.float32,
    )
    candidate_mask = torch.zeros(
        (batch_size, 1, candidate_count),
        dtype=torch.bool,
    )
    candidate_acceptable = torch.zeros_like(candidate_mask)
    candidate_relations = (
        torch.zeros(
            (
                batch_size,
                1,
                candidate_count,
                candidate_count,
                ANCHOR_CANDIDATE_RELATION_DIM,
            ),
            dtype=torch.float32,
        )
        if include_candidate_relations
        else None
    )
    member_features = torch.zeros(
        (batch_size, 1, member_count, TARGET_A_FEATURE_DIM),
        dtype=torch.float32,
    )
    member_mask = torch.zeros(
        (batch_size, 1, member_count),
        dtype=torch.bool,
    )
    member_is_road = torch.zeros_like(member_mask)
    candidate_membership = torch.zeros(
        (batch_size, 1, candidate_count, member_count),
        dtype=torch.bool,
    )
    member_acceptable_sets = torch.zeros(
        (
            batch_size,
            1,
            member_option_count,
            member_count,
        ),
        dtype=torch.bool,
    )
    member_acceptable_set_mask = torch.zeros(
        (batch_size, 1, member_option_count),
        dtype=torch.bool,
    )
    swsd_arm_count = max(
        1,
        max(len(row.swsd_arm_features) for row in examples),
    )
    member_arm_count = max(
        1,
        max(
            (
                len(arms)
                for row in examples
                for arms in row.member_arm_features
            ),
            default=0,
        ),
    )
    swsd_arm_features = torch.zeros(
        (batch_size, 1, swsd_arm_count, ANCHOR_ARM_FEATURE_DIM),
        dtype=torch.float32,
    )
    swsd_arm_mask = torch.zeros(
        (batch_size, 1, swsd_arm_count),
        dtype=torch.bool,
    )
    member_arm_features = torch.zeros(
        (
            batch_size,
            1,
            member_count,
            member_arm_count,
            ANCHOR_ARM_FEATURE_DIM,
        ),
        dtype=torch.float32,
    )
    member_arm_mask = torch.zeros(
        (batch_size, 1, member_count, member_arm_count),
        dtype=torch.bool,
    )
    member_local_features = torch.zeros(
        (
            batch_size,
            1,
            member_count,
            ANCHOR_MEMBER_LOCAL_FEATURE_DIM,
        ),
        dtype=torch.float32,
    )
    member_relation_features = torch.zeros(
        (
            batch_size,
            1,
            member_count,
            member_count,
            ANCHOR_MEMBER_RELATION_DIM,
        ),
        dtype=torch.float32,
    )
    member_relation_mask = torch.zeros(
        (batch_size, 1, member_count, member_count),
        dtype=torch.bool,
    )
    for batch_index, row in enumerate(examples):
        count = len(row.candidate_features)
        candidate_features[batch_index, 0, :count] = torch.tensor(
            row.candidate_features,
            dtype=torch.float32,
        )
        candidate_mask[batch_index, 0, :count] = True
        if candidate_relations is not None:
            candidate_relations[
                batch_index,
                0,
                :count,
                :count,
            ] = anchor_candidate_relation_matrix(row.candidate_ids)
        members = member_rows[batch_index]
        row_member_count = members.member_features.shape[0]
        member_features[
            batch_index,
            0,
            :row_member_count,
        ] = members.member_features
        member_mask[batch_index, 0, :row_member_count] = True
        member_is_road[
            batch_index,
            0,
            :row_member_count,
        ] = members.member_is_road
        candidate_membership[
            batch_index,
            0,
            :count,
            :row_member_count,
        ] = members.candidate_membership
        if row.structural_member_ids:
            swsd_count = len(row.swsd_arm_features)
            if swsd_count:
                swsd_arm_features[
                    batch_index,
                    0,
                    :swsd_count,
                ] = torch.tensor(
                    row.swsd_arm_features,
                    dtype=torch.float32,
                )
                swsd_arm_mask[batch_index, 0, :swsd_count] = True
            for member_index, arms in enumerate(row.member_arm_features):
                arm_count = len(arms)
                if not arm_count:
                    continue
                member_arm_features[
                    batch_index,
                    0,
                    member_index,
                    :arm_count,
                ] = torch.tensor(arms, dtype=torch.float32)
                member_arm_mask[
                    batch_index,
                    0,
                    member_index,
                    :arm_count,
                ] = True
            if row.member_local_features:
                member_local_features[
                    batch_index,
                    0,
                    :row_member_count,
                ] = torch.tensor(
                    row.member_local_features,
                    dtype=torch.float32,
                )
            for left, right, relation in row.member_relation_edges:
                member_relation_features[
                    batch_index,
                    0,
                    left,
                    right,
                ] = torch.tensor(relation, dtype=torch.float32)
                member_relation_mask[
                    batch_index,
                    0,
                    left,
                    right,
                ] = True
        for index in row.candidate_acceptable_indices:
            if not 0 <= index < count:
                raise ValueError("anchor acceptable candidate index is outside the set")
            candidate_acceptable[batch_index, 0, index] = True
        for option_index, acceptable in enumerate(
            row.member_acceptable_sets
        ):
            member_acceptable_set_mask[
                batch_index,
                0,
                option_index,
            ] = True
            for member_index in acceptable:
                if not 0 <= member_index < row_member_count:
                    raise ValueError(
                        "anchor acceptable member index is outside the set"
                    )
                member_acceptable_sets[
                    batch_index,
                    0,
                    option_index,
                    member_index,
                ] = True

    dummy_features = torch.zeros(
        (batch_size, 1, 1, TARGET_A_FEATURE_DIM),
        dtype=torch.float32,
    )
    dummy_mask = torch.zeros((batch_size, 1, 1), dtype=torch.bool)
    tensors = TargetABatchTensors(
        object_features=object_features,
        object_types=object_types,
        object_mask=object_mask,
        adjacency=adjacency,
        anchor_object_indices=torch.zeros((batch_size, 1), dtype=torch.long),
        anchor_candidate_features=candidate_features,
        anchor_candidate_mask=candidate_mask,
        ordinary_object_indices=torch.full((batch_size, 1), -1, dtype=torch.long),
        ordinary_required_anchor_indices=torch.full(
            (batch_size, 1, 1),
            -1,
            dtype=torch.long,
        ),
        ordinary_plan_features=dummy_features.clone(),
        ordinary_plan_mask=dummy_mask.clone(),
        advance_right_object_indices=torch.full(
            (batch_size, 1),
            -1,
            dtype=torch.long,
        ),
        advance_right_source_indices=torch.full(
            (batch_size, 1),
            -1,
            dtype=torch.long,
        ),
        advance_right_target_indices=torch.full(
            (batch_size, 1),
            -1,
            dtype=torch.long,
        ),
        advance_right_plan_features=dummy_features.clone(),
        advance_right_plan_mask=dummy_mask.clone(),
        teacher_anchor_candidate_indices=torch.zeros(
            (batch_size, 1),
            dtype=torch.long,
        ),
        teacher_anchor_success=torch.tensor(
            [
                [
                    row.status_supervised
                    and row.status_label
                    == ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
                ]
                for row in examples
            ],
            dtype=torch.bool,
        ),
        teacher_ordinary_plan_indices=torch.zeros(
            (batch_size, 1),
            dtype=torch.long,
        ),
        anchor_candidate_relations=candidate_relations,
        anchor_member_features=member_features,
        anchor_member_mask=member_mask,
        anchor_member_is_road=member_is_road,
        anchor_candidate_membership=candidate_membership,
        anchor_swsd_arm_features=swsd_arm_features,
        anchor_swsd_arm_mask=swsd_arm_mask,
        anchor_member_arm_features=member_arm_features,
        anchor_member_arm_mask=member_arm_mask,
        anchor_member_local_features=member_local_features,
        anchor_member_relation_features=member_relation_features,
        anchor_member_relation_mask=member_relation_mask,
    )
    targets = TargetATrainingTargets(
        sample_weights=torch.tensor(
            [row.sample_weight for row in examples],
            dtype=torch.float32,
        ),
        anchor_status=torch.tensor(
            [[row.status_label] for row in examples],
            dtype=torch.long,
        ),
        anchor_status_mask=torch.tensor(
            [[row.status_supervised] for row in examples],
            dtype=torch.bool,
        ),
        anchor_acceptable=candidate_acceptable,
        anchor_preferred=torch.tensor(
            [[row.preferred_candidate_index] for row in examples],
            dtype=torch.long,
        ),
        anchor_candidate_task_mask=torch.tensor(
            [[row.candidate_supervised] for row in examples],
            dtype=torch.bool,
        ),
        ordinary_acceptable=dummy_mask.clone(),
        ordinary_preferred=torch.full((batch_size, 1), -1, dtype=torch.long),
        ordinary_task_mask=torch.zeros((batch_size, 1), dtype=torch.bool),
        clue=torch.zeros((batch_size, 1), dtype=torch.long),
        clue_task_mask=torch.zeros((batch_size, 1), dtype=torch.bool),
        fallback_scope=torch.zeros((batch_size, 1), dtype=torch.long),
        fallback_scope_task_mask=torch.zeros((batch_size, 1), dtype=torch.bool),
        advance_right_acceptable=dummy_mask.clone(),
        advance_right_preferred=torch.full(
            (batch_size, 1),
            -1,
            dtype=torch.long,
        ),
        advance_right_task_mask=torch.zeros((batch_size, 1), dtype=torch.bool),
        anchor_gate=torch.tensor(
            [[row.gate_label] for row in examples],
            dtype=torch.long,
        ),
        anchor_gate_mask=torch.tensor(
            [[row.gate_supervised] for row in examples],
            dtype=torch.bool,
        ),
        anchor_member_acceptable_sets=member_acceptable_sets,
        anchor_member_acceptable_set_mask=member_acceptable_set_mask,
        anchor_member_task_mask=torch.tensor(
            [[row.member_supervised] for row in examples],
            dtype=torch.bool,
        ),
    )
    return TargetATrainingBatch(tensors=tensors, targets=targets)


def anchor_batches_for_fold(
    examples: Sequence[AnchorPretrainExample],
    *,
    held_out_fold: int,
    batch_size: int,
    include_candidate_relations: bool = False,
) -> tuple[list[TargetATrainingBatch], list[TargetATrainingBatch]]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    train = [row for row in examples if row.fold != held_out_fold]
    validation = [row for row in examples if row.fold == held_out_fold]
    if not train or not validation:
        raise ValueError("Target A anchor fold lacks train or validation examples")
    return (
        [
            collate_anchor_pretrain_batch(
                train[index : index + batch_size],
                include_candidate_relations=include_candidate_relations,
            )
            for index in range(0, len(train), batch_size)
        ],
        [
            collate_anchor_pretrain_batch(
                validation[index : index + batch_size],
                include_candidate_relations=include_candidate_relations,
            )
            for index in range(0, len(validation), batch_size)
        ],
    )


def _single_point_inputs(case_root: Path) -> dict[str, Path]:
    candidates = {
        "nodes": case_root / "nodes.gpkg",
        "roads": case_root / "roads.gpkg",
        "rcsd_nodes": case_root / "rcsdnode.gpkg",
        "rcsd_roads": case_root / "rcsdroad.gpkg",
        "drivezone": case_root / "drivezone.gpkg",
        "divstripzone": case_root / "divstripzone.gpkg",
    }
    required = {"nodes", "roads", "rcsd_nodes", "rcsd_roads", "drivezone"}
    missing = sorted(role for role in required if not candidates[role].is_file())
    if missing:
        raise FileNotFoundError(f"{case_root}: missing single-point inputs {missing}")
    return candidates


def _target_point(nodes_path: Path, target_id: str) -> Point:
    fallback: Point | None = None
    with fiona.open(nodes_path) as source:
        for feature in source:
            if not feature["geometry"]:
                continue
            geometry = shape(feature["geometry"])
            if not isinstance(geometry, Point):
                continue
            fallback = fallback or geometry
            properties = dict(feature["properties"])
            ids = {
                str(properties.get(key) or "")
                for key in ("id", "nodeid", "mainnodeid", "kind_2")
            }
            if target_id in ids:
                return geometry
    if fallback is None:
        raise ValueError(f"no target Point is available: {nodes_path}")
    return fallback


def _anchor_object_features(
    inputs: Mapping[str, Path],
    target: Point,
) -> np.ndarray:
    result = np.zeros(TARGET_A_FEATURE_DIM, dtype=np.float32)
    node_rows = _geometry_rows(inputs["nodes"])
    road_rows = _geometry_rows(inputs["roads"])
    rcsd_nodes = _geometry_rows(inputs["rcsd_nodes"])
    rcsd_roads = _geometry_rows(inputs["rcsd_roads"])
    drivezones = _geometry_rows(inputs["drivezone"])
    groups = (node_rows, road_rows, rcsd_nodes, rcsd_roads, drivezones)
    result[:5] = [math.log1p(len(rows)) for rows in groups]
    scale = _local_scale(target, [*road_rows, *rcsd_roads, *drivezones])
    cursor = 5
    for rows in groups:
        distances = [float(geometry.distance(target)) / scale for geometry, _ in rows]
        lengths = [float(geometry.length) / scale for geometry, _ in rows]
        for values in (distances, lengths):
            result[cursor : cursor + 5] = _quantiles(values)
            cursor += 5
    orientations = [_orientation(geometry) for geometry, _ in [*road_rows, *rcsd_roads]]
    if orientations:
        result[cursor] = float(np.mean([value[0] for value in orientations]))
        result[cursor + 1] = float(np.mean([value[1] for value in orientations]))
    cursor += 2
    result[cursor] = float(
        any(geometry.buffer(1e-9).covers(target) for geometry, _ in drivezones)
    )
    result[cursor + 1] = min(
        [float(geometry.distance(target)) / scale for geometry, _ in drivezones]
        or [1.0]
    )
    cursor += 2
    nearest_rcsd = sorted(
        [
            (
                float(geometry.distance(target)) / scale,
                properties,
            )
            for geometry, properties in [*rcsd_nodes, *rcsd_roads]
        ],
        key=lambda row: row[0],
    )[:2]
    for offset, (distance, properties) in enumerate(nearest_rcsd):
        base = cursor + offset * 2
        result[base] = distance
        result[base + 1] = _numeric_property(properties, ("kind", "kind_2", "direction"))
    return np.nan_to_num(result, nan=0.0, posinf=10.0, neginf=-10.0)


def _anchor_candidates(
    inputs: Mapping[str, Path],
    target: Point,
    *,
    max_candidates: int = 32,
) -> tuple[list[np.ndarray], list[str]]:
    candidates: list[tuple[float, str, np.ndarray]] = []
    all_rows = [
        ("NODE", *_row)
        for _row in _geometry_rows(inputs["rcsd_nodes"])
    ] + [
        ("ROAD", *_row)
        for _row in _geometry_rows(inputs["rcsd_roads"])
    ]
    scale = _local_scale(target, [(geometry, props) for _, geometry, props in all_rows])
    for kind, geometry, properties in all_rows:
        centroid = geometry if isinstance(geometry, Point) else geometry.centroid
        dx = float(centroid.x - target.x) / scale
        dy = float(centroid.y - target.y) / scale
        distance = float(geometry.distance(target)) / scale
        values = np.zeros(TARGET_A_FEATURE_DIM, dtype=np.float32)
        values[0] = 1.0 if kind == "NODE" else 0.0
        values[1] = 1.0 if kind == "ROAD" else 0.0
        values[2:8] = (
            dx,
            dy,
            distance,
            math.log1p(max(0.0, float(geometry.length)) / scale),
            *_orientation(geometry),
        )
        values[8] = _numeric_property(properties, ("kind", "kind_2"))
        values[9] = _numeric_property(properties, ("direction",))
        values[10] = _numeric_property(properties, ("source",))
        candidate_id = str(
            properties.get("id")
            or properties.get("nodeid")
            or properties.get("roadid")
            or ""
        )
        if not candidate_id:
            candidate_id = (
                "UNIDENTIFIED:"
                + hashlib.sha256(geometry.wkb).hexdigest()[:16]
            )
        candidates.append((distance, f"{kind}:{candidate_id}", values))
    candidates.sort(key=lambda row: (row[0], row[1]))
    selected = candidates[:max_candidates]
    if not selected:
        return [
            np.zeros(TARGET_A_FEATURE_DIM, dtype=np.float32)
        ], ["UNIDENTIFIED:NO_RAW_RCSD_CANDIDATE"]
    return [row[2] for row in selected], [row[1] for row in selected]


def _geometry_rows(path: Path) -> list[tuple[BaseGeometry, dict[str, Any]]]:
    if not path.is_file():
        return []
    rows: list[tuple[BaseGeometry, dict[str, Any]]] = []
    with fiona.open(path) as source:
        for feature in source:
            if not feature["geometry"]:
                continue
            geometry = shape(feature["geometry"])
            if geometry.is_empty:
                continue
            rows.append((geometry, dict(feature["properties"])))
    return rows


def _local_scale(
    target: Point,
    rows: Sequence[tuple[BaseGeometry, Mapping[str, Any]]],
) -> float:
    distances = [float(geometry.distance(target)) for geometry, _ in rows]
    lengths = [float(geometry.length) for geometry, _ in rows]
    nonzero = [value for value in [*distances, *lengths] if value > 0]
    return max(20.0, float(np.quantile(nonzero, 0.75)) if nonzero else 20.0)


def _orientation(geometry: BaseGeometry) -> tuple[float, float]:
    if isinstance(geometry, Point):
        return 0.0, 0.0
    coordinates: list[tuple[float, ...]] = []
    if geometry.geom_type == "LineString":
        coordinates = list(geometry.coords)
    elif geometry.geom_type == "MultiLineString":
        longest = max(geometry.geoms, key=lambda item: item.length, default=None)
        coordinates = list(longest.coords) if longest is not None else []
    if len(coordinates) < 2:
        return 0.0, 0.0
    dx = float(coordinates[-1][0] - coordinates[0][0])
    dy = float(coordinates[-1][1] - coordinates[0][1])
    norm = math.hypot(dx, dy)
    return (dx / norm, dy / norm) if norm else (0.0, 0.0)


def _numeric_property(
    properties: Mapping[str, Any],
    keys: Sequence[str],
) -> float:
    for key in keys:
        value = properties.get(key)
        try:
            return math.tanh(float(value) / 16.0)
        except (TypeError, ValueError):
            continue
    return 0.0


def _quantiles(values: Sequence[float]) -> np.ndarray:
    if not values:
        return np.zeros(5, dtype=np.float32)
    return np.asarray(
        np.quantile(np.asarray(values, dtype=np.float64), [0.0, 0.25, 0.5, 0.75, 1.0]),
        dtype=np.float32,
    )


def _case_directories(root: Path) -> list[Path]:
    if not root.is_dir():
        raise FileNotFoundError(root)
    return sorted(
        (
            path
            for path in root.iterdir()
            if path.is_dir() and not path.name.startswith("_")
        ),
        key=lambda path: path.name.casefold(),
    )


def _sample_id(case_key: str, manifest_path: Path) -> str:
    digest = hashlib.sha256(
        f"{case_key}:{sha256_file(manifest_path)}".encode("utf-8")
    ).hexdigest()
    return f"anchor:{digest[:20]}"


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL row is not an object: {path}:{line_number}")
            rows.append(payload)
    return rows


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
            )
            stream.write("\n")


def _counts(values: Iterable[Any]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value)
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items()))


__all__ = [
    "ANCHOR_FAMILIES",
    "ANCHOR_STATUS_INDEX",
    "AnchorPretrainExample",
    "TARGET_A_FEATURE_DIM",
    "TargetACaseBundle",
    "anchor_batches_for_fold",
    "audit_anchor_store_leakage",
    "build_anchor_pretrain_examples",
    "collate_anchor_pretrain_batch",
    "discover_target_a_case_bundles",
    "read_anchor_pretraining_stores",
    "write_anchor_pretraining_stores",
]
