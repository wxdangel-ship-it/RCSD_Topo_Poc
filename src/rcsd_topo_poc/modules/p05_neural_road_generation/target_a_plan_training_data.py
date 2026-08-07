from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    FallbackScope,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_ABSTAIN,
    ORDINARY_DECISION_KEEP_SWSD,
    ORDINARY_DECISION_USE_RCSD,
    TargetABatchTensors,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_arms import (
    ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
    ORDINARY_PLAN_ARM_COUNT,
    ORDINARY_PLAN_ARM_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_members import (
    ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,
    ORDINARY_PLAN_MEMBER_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    TargetATrainingBatch,
    TargetATrainingTargets,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


_FALLBACK_SCOPE_INDEX = {
    value.value: index for index, value in enumerate(FallbackScope)
}
_ORDINARY_DECISION_INDEX = {
    "KEEP_SWSD": ORDINARY_DECISION_KEEP_SWSD,
    "USE_RCSD": ORDINARY_DECISION_USE_RCSD,
    "T06_MAIN_RCSD_ATTACHED_SWSD": ORDINARY_DECISION_USE_RCSD,
    "ABSTAIN": ORDINARY_DECISION_ABSTAIN,
}


@dataclass(frozen=True)
class OrdinaryPlanTrainingExample:
    sample_id: str
    case_key: str
    segment_id: str
    fold: int
    object_features: tuple[float, ...]
    required_anchor_ids: tuple[str, ...]
    arm_anchor_ids: tuple[str, ...]
    candidate_ids: tuple[str, ...]
    candidate_decisions: tuple[str, ...]
    candidate_road_ids: tuple[tuple[str, ...], ...]
    candidate_member_ids: tuple[tuple[str, ...], ...]
    candidate_member_endpoint_ids: tuple[
        tuple[tuple[str, str], ...],
        ...,
    ]
    candidate_member_features: tuple[
        tuple[tuple[float, ...], ...],
        ...,
    ]
    candidate_arm_road_ids: tuple[tuple[str, ...], ...]
    candidate_arm_node_ids: tuple[tuple[str, ...], ...]
    candidate_arm_features: tuple[
        tuple[tuple[float, ...], ...],
        ...,
    ]
    candidate_features: tuple[tuple[float, ...], ...]
    acceptable_indices: tuple[int, ...]
    preferred_index: int
    preferred_decision: str
    sample_weight: float
    clue_label: int
    clue_task_mask: bool
    fallback_scope_label: int
    fallback_scope_task_mask: bool
    carrier_task_mask: bool = True
    candidate_road_roles: tuple[
        tuple[tuple[str, str], ...], ...
    ] = ()
    candidate_owned_road_ids: tuple[tuple[str, ...], ...] = ()
    candidate_hard_valid: tuple[bool, ...] = ()
    junc_node_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.object_features) != TARGET_A_FEATURE_DIM:
            raise ValueError("ordinary object feature dimension differs")
        if len(self.arm_anchor_ids) not in {0, ORDINARY_PLAN_ARM_COUNT}:
            raise ValueError("ordinary Segment arm anchor mapping differs")
        if (
            not self.candidate_ids
            or len(self.candidate_ids) != len(self.candidate_features)
            or len(self.candidate_ids) != len(self.candidate_decisions)
            or len(self.candidate_ids) != len(self.candidate_road_ids)
            or len(self.candidate_ids) != len(self.candidate_member_ids)
            or len(self.candidate_ids)
            != len(self.candidate_member_endpoint_ids)
            or len(self.candidate_ids)
            != len(self.candidate_member_features)
            or len(self.candidate_ids) != len(self.candidate_arm_road_ids)
            or len(self.candidate_ids) != len(self.candidate_arm_node_ids)
            or len(self.candidate_ids) != len(self.candidate_arm_features)
        ):
            raise ValueError("ordinary plan candidates differ")
        if any(
            len(values) != TARGET_A_FEATURE_DIM
            for values in self.candidate_features
        ):
            raise ValueError("ordinary plan feature dimension differs")
        for values, label in (
            (self.candidate_road_roles, "Road roles"),
            (self.candidate_owned_road_ids, "owned Roads"),
            (self.candidate_hard_valid, "hard-valid mask"),
        ):
            if values and len(values) != len(self.candidate_ids):
                raise ValueError(
                    f"ordinary plan candidate {label} differ"
                )
        for member_ids, endpoint_ids, member_features in zip(
            self.candidate_member_ids,
            self.candidate_member_endpoint_ids,
            self.candidate_member_features,
            strict=True,
        ):
            if (
                len(member_ids) != len(endpoint_ids)
                or len(member_ids) != len(member_features)
                or any(
                    len(values) != ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM
                    for values in member_features
                )
            ):
                raise ValueError("ordinary plan member evidence differs")
        for road_ids, node_ids, arm_features in zip(
            self.candidate_arm_road_ids,
            self.candidate_arm_node_ids,
            self.candidate_arm_features,
            strict=True,
        ):
            if (
                len(road_ids) != len(node_ids)
                or len(road_ids) != len(arm_features)
                or len(road_ids) not in {0, ORDINARY_PLAN_ARM_COUNT}
                or any(
                    len(values) != ORDINARY_PLAN_ARM_BASE_FEATURE_DIM
                    for values in arm_features
                )
            ):
                raise ValueError("ordinary plan arm evidence differs")
        if not self.acceptable_indices:
            raise ValueError("ordinary plan example lacks a reachable label")
        if self.preferred_index >= len(self.candidate_ids):
            raise ValueError("ordinary preferred plan index is outside candidates")


def read_ordinary_plan_training_examples(
    *,
    candidate_store_root: Path,
    preflight_root: Path,
) -> list[OrdinaryPlanTrainingExample]:
    candidate_root = normalize_runtime_path(candidate_store_root).resolve(strict=True)
    label_root = normalize_runtime_path(preflight_root).resolve(strict=True)
    groups = {
        (str(row["case_key"]), str(row["segment_id"])): row
        for row in _read_jsonl(candidate_root / "inference_plan_groups.jsonl")
    }
    labels = _read_jsonl(label_root / "training_plan_labels.jsonl")
    examples: list[OrdinaryPlanTrainingExample] = []
    for label in labels:
        if (
            not label.get("training_task_mask")
            or str(label.get("segment_type")) != "STANDARD"
        ):
            continue
        key = (str(label["case_key"]), str(label["segment_id"]))
        group = groups.get(key)
        if group is None:
            raise ValueError(f"ordinary candidate group is missing: {key}")
        candidates = list(group["candidates"])
        member_rows = [
            list(candidate.get("road_members") or ())
            for candidate in candidates
        ]
        arm_rows = [
            list(candidate.get("arm_rows") or ())
            for candidate in candidates
        ]
        candidate_ids = tuple(str(row["plan_id"]) for row in candidates)
        index_by_id = {
            candidate_id: index
            for index, candidate_id in enumerate(candidate_ids)
        }
        acceptable_indices = tuple(
            sorted(
                index_by_id[plan_id]
                for plan_id in label["acceptable_plan_ids"]
                if plan_id in index_by_id
            )
        )
        preferred_plan_id = str(label.get("preferred_plan_id") or "")
        preferred_index = index_by_id.get(preferred_plan_id, -1)
        fallback_scope = str(label.get("fallback_scope") or "NONE")
        examples.append(
            OrdinaryPlanTrainingExample(
                sample_id=f"{key[0]}:{key[1]}",
                case_key=key[0],
                segment_id=key[1],
                fold=int(label["fold"]),
                object_features=tuple(
                    float(value) for value in group["object_features"]
                ),
                required_anchor_ids=tuple(
                    str(value) for value in group["required_anchor_ids"]
                ),
                arm_anchor_ids=tuple(
                    str(value) for value in group.get("arm_anchor_ids") or ()
                ),
                candidate_ids=candidate_ids,
                candidate_decisions=tuple(
                    str(row["decision"]) for row in candidates
                ),
                candidate_road_ids=tuple(
                    tuple(str(value) for value in row["road_ids"])
                    for row in candidates
                ),
                candidate_member_ids=tuple(
                    tuple(str(member["road_id"]) for member in members)
                    for members in member_rows
                ),
                candidate_member_endpoint_ids=tuple(
                    tuple(
                        (
                            str(member["start_node_id"]),
                            str(member["end_node_id"]),
                        )
                        for member in members
                    )
                    for members in member_rows
                ),
                candidate_member_features=tuple(
                    tuple(
                        tuple(
                            float(value)
                            for value in member["features"]
                        )
                        for member in members
                    )
                    for members in member_rows
                ),
                candidate_arm_road_ids=tuple(
                    tuple(str(arm["nearest_road_id"]) for arm in arms)
                    for arms in arm_rows
                ),
                candidate_arm_node_ids=tuple(
                    tuple(str(arm["nearest_node_id"]) for arm in arms)
                    for arms in arm_rows
                ),
                candidate_arm_features=tuple(
                    tuple(
                        tuple(float(value) for value in arm["features"])
                        for arm in arms
                    )
                    for arms in arm_rows
                ),
                candidate_features=tuple(
                    tuple(float(value) for value in row["features"])
                    for row in candidates
                ),
                acceptable_indices=acceptable_indices,
                preferred_index=preferred_index,
                preferred_decision=str(
                    label.get("preferred_carrier_target") or ""
                ),
                sample_weight=float(label["label_weight"]),
                clue_label=int(bool(label.get("reality_change_clue"))),
                clue_task_mask=bool(label.get("clue_task_mask")),
                fallback_scope_label=_FALLBACK_SCOPE_INDEX.get(
                    fallback_scope,
                    0,
                ),
                fallback_scope_task_mask=bool(
                    label.get("fallback_scope_task_mask")
                ),
                carrier_task_mask=bool(
                    label.get("carrier_task_mask", True)
                ),
                candidate_road_roles=tuple(
                    tuple(
                        (str(value["road_id"]), str(value["role"]))
                        for value in row.get("road_roles") or ()
                    )
                    for row in candidates
                ),
                candidate_owned_road_ids=tuple(
                    tuple(
                        str(value)
                        for value in row.get("owned_road_ids") or ()
                    )
                    for row in candidates
                ),
                candidate_hard_valid=tuple(
                    bool(row.get("hard_valid")) for row in candidates
                ),
                junc_node_ids=tuple(
                    str(value) for value in group.get("junc_node_ids") or ()
                ),
            )
        )
    return sorted(examples, key=lambda row: (row.case_key, row.segment_id))


def collate_ordinary_plan_batch(
    examples: Sequence[OrdinaryPlanTrainingExample],
) -> TargetATrainingBatch:
    if not examples:
        raise ValueError("cannot collate empty ordinary plan batch")
    batch_size = len(examples)
    candidate_count = max(len(row.candidate_ids) for row in examples)
    ordinary_features = torch.zeros(
        (batch_size, 1, candidate_count, TARGET_A_FEATURE_DIM),
        dtype=torch.float32,
    )
    ordinary_mask = torch.zeros(
        (batch_size, 1, candidate_count),
        dtype=torch.bool,
    )
    ordinary_decisions = torch.zeros(
        (batch_size, 1, candidate_count),
        dtype=torch.long,
    )
    member_count = max(
        1,
        max(
            (
                len(members)
                for example in examples
                for members in example.candidate_member_ids
            ),
            default=0,
        ),
    )
    ordinary_member_features = torch.zeros(
        (
            batch_size,
            1,
            candidate_count,
            member_count,
            ORDINARY_PLAN_MEMBER_FEATURE_DIM,
        ),
        dtype=torch.float32,
    )
    ordinary_member_mask = torch.zeros(
        (batch_size, 1, candidate_count, member_count),
        dtype=torch.bool,
    )
    ordinary_arm_features = torch.zeros(
        (
            batch_size,
            1,
            candidate_count,
            ORDINARY_PLAN_ARM_COUNT,
            ORDINARY_PLAN_ARM_FEATURE_DIM,
        ),
        dtype=torch.float32,
    )
    ordinary_arm_mask = torch.zeros(
        (batch_size, 1, candidate_count, ORDINARY_PLAN_ARM_COUNT),
        dtype=torch.bool,
    )
    ordinary_acceptable = torch.zeros_like(ordinary_mask)
    ordinary_preferred = torch.full(
        (batch_size, 1),
        -1,
        dtype=torch.long,
    )
    teacher_ordinary = torch.zeros((batch_size, 1), dtype=torch.long)
    for batch_index, example in enumerate(examples):
        count = len(example.candidate_ids)
        ordinary_features[batch_index, 0, :count] = torch.tensor(
            example.candidate_features,
            dtype=torch.float32,
        )
        ordinary_mask[batch_index, 0, :count] = True
        try:
            ordinary_decisions[batch_index, 0, :count] = torch.tensor(
                [
                    _ORDINARY_DECISION_INDEX[value]
                    for value in example.candidate_decisions
                ],
                dtype=torch.long,
            )
        except KeyError as exc:
            raise ValueError(
                f"unsupported ordinary decision: {exc.args[0]}"
            ) from exc
        for candidate_index, member_features in enumerate(
            example.candidate_member_features
        ):
            count_members = len(member_features)
            if not count_members:
                continue
            ordinary_member_features[
                batch_index,
                0,
                candidate_index,
                :count_members,
                :ORDINARY_PLAN_MEMBER_BASE_FEATURE_DIM,
            ] = torch.tensor(member_features, dtype=torch.float32)
            ordinary_member_mask[
                batch_index,
                0,
                candidate_index,
                :count_members,
            ] = True
        for candidate_index, arm_features in enumerate(
            example.candidate_arm_features
        ):
            count_arms = len(arm_features)
            if not count_arms:
                continue
            ordinary_arm_features[
                batch_index,
                0,
                candidate_index,
                :count_arms,
                :ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
            ] = torch.tensor(arm_features, dtype=torch.float32)
            ordinary_arm_mask[
                batch_index,
                0,
                candidate_index,
                :count_arms,
            ] = True
        for candidate_index in example.acceptable_indices:
            ordinary_acceptable[batch_index, 0, candidate_index] = True
        ordinary_preferred[batch_index, 0] = example.preferred_index
        teacher_ordinary[batch_index, 0] = (
            example.preferred_index
            if example.preferred_index >= 0
            else example.acceptable_indices[0]
        )
    dummy_features = torch.zeros(
        (batch_size, 1, 1, TARGET_A_FEATURE_DIM),
        dtype=torch.float32,
    )
    dummy_valid_mask = torch.ones((batch_size, 1, 1), dtype=torch.bool)
    dummy_empty_mask = torch.zeros((batch_size, 1, 1), dtype=torch.bool)
    tensors = TargetABatchTensors(
        object_features=torch.tensor(
            [[row.object_features] for row in examples],
            dtype=torch.float32,
        ),
        object_types=torch.ones((batch_size, 1), dtype=torch.long),
        object_mask=torch.ones((batch_size, 1), dtype=torch.bool),
        adjacency=torch.ones((batch_size, 1, 1), dtype=torch.bool),
        anchor_object_indices=torch.zeros((batch_size, 1), dtype=torch.long),
        anchor_candidate_features=dummy_features.clone(),
        anchor_candidate_mask=dummy_valid_mask.clone(),
        ordinary_object_indices=torch.zeros((batch_size, 1), dtype=torch.long),
        ordinary_required_anchor_indices=torch.zeros(
            (batch_size, 1, 1),
            dtype=torch.long,
        ),
        ordinary_plan_features=ordinary_features,
        ordinary_plan_mask=ordinary_mask,
        ordinary_plan_decision_indices=ordinary_decisions,
        ordinary_plan_member_features=ordinary_member_features,
        ordinary_plan_member_mask=ordinary_member_mask,
        ordinary_plan_arm_features=ordinary_arm_features,
        ordinary_plan_arm_mask=ordinary_arm_mask,
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
        advance_right_plan_mask=dummy_empty_mask.clone(),
        teacher_anchor_candidate_indices=torch.zeros(
            (batch_size, 1),
            dtype=torch.long,
        ),
        teacher_anchor_success=torch.ones(
            (batch_size, 1),
            dtype=torch.bool,
        ),
        teacher_ordinary_plan_indices=teacher_ordinary,
    )
    targets = TargetATrainingTargets(
        sample_weights=torch.tensor(
            [row.sample_weight for row in examples],
            dtype=torch.float32,
        ),
        anchor_status=torch.zeros((batch_size, 1), dtype=torch.long),
        anchor_status_mask=torch.zeros((batch_size, 1), dtype=torch.bool),
        anchor_acceptable=dummy_empty_mask.clone(),
        anchor_preferred=torch.full((batch_size, 1), -1, dtype=torch.long),
        anchor_candidate_task_mask=torch.zeros(
            (batch_size, 1),
            dtype=torch.bool,
        ),
        ordinary_acceptable=ordinary_acceptable,
        ordinary_preferred=ordinary_preferred,
        ordinary_task_mask=torch.tensor(
            [[row.carrier_task_mask] for row in examples],
            dtype=torch.bool,
        ),
        clue=torch.tensor(
            [[row.clue_label] for row in examples],
            dtype=torch.long,
        ),
        clue_task_mask=torch.tensor(
            [[row.clue_task_mask] for row in examples],
            dtype=torch.bool,
        ),
        fallback_scope=torch.tensor(
            [[row.fallback_scope_label] for row in examples],
            dtype=torch.long,
        ),
        fallback_scope_task_mask=torch.tensor(
            [[row.fallback_scope_task_mask] for row in examples],
            dtype=torch.bool,
        ),
        advance_right_acceptable=dummy_empty_mask.clone(),
        advance_right_preferred=torch.full(
            (batch_size, 1),
            -1,
            dtype=torch.long,
        ),
        advance_right_task_mask=torch.zeros(
            (batch_size, 1),
            dtype=torch.bool,
        ),
    )
    return TargetATrainingBatch(tensors=tensors, targets=targets)


def ordinary_batches_for_fold(
    examples: Sequence[OrdinaryPlanTrainingExample],
    *,
    held_out_fold: int,
    batch_size: int,
) -> tuple[list[TargetATrainingBatch], list[TargetATrainingBatch]]:
    train = [row for row in examples if row.fold != held_out_fold]
    validation = [row for row in examples if row.fold == held_out_fold]
    if not train or not validation:
        raise ValueError("ordinary plan fold lacks train or validation examples")
    return (
        [
            collate_ordinary_plan_batch(train[index : index + batch_size])
            for index in range(0, len(train), batch_size)
        ],
        [
            collate_ordinary_plan_batch(validation[index : index + batch_size])
            for index in range(0, len(validation), batch_size)
        ],
    )


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"JSONL row is not an object: {path}:{line_number}")
            rows.append(payload)
    return rows


__all__ = [
    "OrdinaryPlanTrainingExample",
    "collate_ordinary_plan_batch",
    "ordinary_batches_for_fold",
    "read_ordinary_plan_training_examples",
]
