from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import fiona
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_ANCHOR_CONDITION_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_arms import (
    ORDINARY_PLAN_ARM_FEATURE_DIM,
    condition_ordinary_plan_arm_features,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    OrdinaryPlanTrainingExample,
    collate_ordinary_plan_batch,
    read_ordinary_plan_training_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_members import (
    ORDINARY_PLAN_MEMBER_FEATURE_DIM,
    condition_ordinary_plan_member_features,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    TargetATrainingBatch,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


_RCSD_ANCHOR_REQUIRED_DECISIONS = frozenset(
    {
        "USE_RCSD",
        "T06_MAIN_RCSD_ATTACHED_SWSD",
    }
)
_ANCHOR_COUNT_NORMALIZER = 8.0


@dataclass(frozen=True)
class AnchorOOFCondition:
    anchor_id: str
    selected_candidate_id: str
    predicted_status: str
    gate_pass_probability: float
    selected_candidate_features: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.selected_candidate_features) != TARGET_A_FEATURE_DIM:
            raise ValueError("selected anchor candidate feature dimension differs")
        if not 0.0 <= self.gate_pass_probability <= 1.0:
            raise ValueError("anchor gate probability is outside [0, 1]")

    @property
    def success(self) -> bool:
        return self.predicted_status == "SUCCESS"

    @property
    def resolved_for_carrier(self) -> bool:
        return self.predicted_status in {"SUCCESS", "NO_EVIDENCE"}


@dataclass(frozen=True)
class OrdinaryAnchorConditionedExample:
    base: OrdinaryPlanTrainingExample
    anchor_condition_features: tuple[float, ...]
    conditioned_candidate_features: tuple[tuple[float, ...], ...]
    conditioned_member_features: tuple[
        tuple[tuple[float, ...], ...],
        ...,
    ]
    conditioned_arm_features: tuple[
        tuple[tuple[float, ...], ...],
        ...,
    ]
    enabled_candidate_mask: tuple[bool, ...]
    conditioned_acceptable_indices: tuple[int, ...]
    conditioned_preferred_index: int
    all_required_anchors_success: bool
    anchor_success_count: int
    all_required_anchors_resolved: bool
    anchor_resolved_count: int
    missing_anchor_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if len(self.anchor_condition_features) != ORDINARY_ANCHOR_CONDITION_DIM:
            raise ValueError("ordinary anchor condition dimension differs")
        if len(self.enabled_candidate_mask) != len(self.base.candidate_ids):
            raise ValueError("conditioned ordinary candidate mask differs")
        if (
            len(self.conditioned_candidate_features)
            != len(self.base.candidate_ids)
            or any(
                len(features) != TARGET_A_FEATURE_DIM
                for features in self.conditioned_candidate_features
            )
        ):
            raise ValueError("conditioned ordinary plan features differ")
        if (
            len(self.conditioned_member_features)
            != len(self.base.candidate_ids)
            or any(
                len(features) != len(base_features)
                for features, base_features in zip(
                    self.conditioned_member_features,
                    self.base.candidate_member_features,
                    strict=True,
                )
            )
            or any(
                len(member) != ORDINARY_PLAN_MEMBER_FEATURE_DIM
                for features in self.conditioned_member_features
                for member in features
            )
        ):
            raise ValueError("conditioned ordinary member features differ")
        if (
            len(self.conditioned_arm_features)
            != len(self.base.candidate_ids)
            or any(
                len(features) != len(base_features)
                for features, base_features in zip(
                    self.conditioned_arm_features,
                    self.base.candidate_arm_features,
                    strict=True,
                )
            )
            or any(
                len(arm) != ORDINARY_PLAN_ARM_FEATURE_DIM
                for features in self.conditioned_arm_features
                for arm in features
            )
        ):
            raise ValueError("conditioned ordinary arm features differ")
        if not any(self.enabled_candidate_mask):
            raise ValueError("conditioned ordinary plan has no enabled candidate")
        if any(
            not self.enabled_candidate_mask[index]
            for index in self.conditioned_acceptable_indices
        ):
            raise ValueError("conditioned acceptable plan is hard-masked")

    @property
    def sample_id(self) -> str:
        return self.base.sample_id

    @property
    def case_key(self) -> str:
        return self.base.case_key

    @property
    def segment_id(self) -> str:
        return self.base.segment_id

    @property
    def fold(self) -> int:
        return self.base.fold

    @property
    def conditioned_label_reachable(self) -> bool:
        return bool(self.conditioned_acceptable_indices)

    @property
    def fallback_required(self) -> bool:
        return not self.all_required_anchors_resolved


def read_oof_anchor_conditioned_ordinary_examples(
    *,
    candidate_store_root: Path,
    preflight_root: Path,
    anchor_store_root: Path,
    anchor_oof_root: Path,
    include_anchor_plan_relations: bool = False,
    include_plan_member_relations: bool = False,
    include_plan_arm_relations: bool = False,
) -> list[OrdinaryAnchorConditionedExample]:
    plans = read_ordinary_plan_training_examples(
        candidate_store_root=candidate_store_root,
        preflight_root=preflight_root,
    )
    required_keys = {
        (plan.case_key, anchor_id)
        for plan in plans
        for anchor_id in plan.required_anchor_ids
    }
    prediction_root = normalize_runtime_path(anchor_oof_root).resolve(strict=True)
    predictions = _read_anchor_oof_predictions(
        prediction_root / "oof_predictions.jsonl",
        required_keys,
    )
    feature_root = normalize_runtime_path(anchor_store_root).resolve(strict=True)
    conditions = _read_selected_anchor_conditions(
        feature_root / "inference_feature_store" / "anchor_features.jsonl",
        predictions,
        required_keys,
    )
    candidate_node_ids = (
        _read_candidate_plan_node_ids(
            normalize_runtime_path(candidate_store_root).resolve(strict=True),
            plans,
        )
        if include_anchor_plan_relations
        else {}
    )
    return [
        condition_ordinary_plan_example(
            plan,
            {
                anchor_id: conditions[(plan.case_key, anchor_id)]
                for anchor_id in plan.required_anchor_ids
                if (plan.case_key, anchor_id) in conditions
            },
            include_anchor_plan_relations=include_anchor_plan_relations,
            include_plan_member_relations=include_plan_member_relations,
            include_plan_arm_relations=include_plan_arm_relations,
            candidate_node_ids=candidate_node_ids.get(plan.sample_id, ()),
        )
        for plan in plans
    ]


def condition_ordinary_plan_example(
    example: OrdinaryPlanTrainingExample,
    anchor_conditions: Mapping[str, AnchorOOFCondition],
    *,
    include_anchor_plan_relations: bool = False,
    include_plan_member_relations: bool = False,
    include_plan_arm_relations: bool = False,
    candidate_node_ids: Sequence[Sequence[str]] = (),
) -> OrdinaryAnchorConditionedExample:
    required_count = len(example.required_anchor_ids)
    present = [
        anchor_conditions[anchor_id]
        for anchor_id in example.required_anchor_ids
        if anchor_id in anchor_conditions
    ]
    missing = tuple(
        anchor_id
        for anchor_id in example.required_anchor_ids
        if anchor_id not in anchor_conditions
    )
    success_count = sum(condition.success for condition in present)
    resolved_count = sum(condition.resolved_for_carrier for condition in present)
    all_success = (
        not missing
        and success_count == required_count
    )
    all_resolved = (
        not missing
        and resolved_count == required_count
    )
    selected_feature_mean = [0.0] * TARGET_A_FEATURE_DIM
    gate_probabilities: list[float] = []
    for condition in present:
        gate_probabilities.append(condition.gate_pass_probability)
        for index, value in enumerate(condition.selected_candidate_features):
            selected_feature_mean[index] += value
    if required_count:
        selected_feature_mean = [
            value / required_count for value in selected_feature_mean
        ]
        gate_mean = sum(gate_probabilities) / required_count
        gate_min = (
            min(gate_probabilities)
            if len(gate_probabilities) == required_count
            else 0.0
        )
        success_fraction = success_count / required_count
    else:
        gate_mean = 0.0
        gate_min = 0.0
        success_fraction = 0.0
    condition_features = tuple(
        selected_feature_mean
        + [
            float(all_resolved),
            success_fraction,
            min(required_count, int(_ANCHOR_COUNT_NORMALIZER))
            / _ANCHOR_COUNT_NORMALIZER,
            gate_mean,
            gate_min,
            float(bool(missing) or required_count == 0),
        ]
    )
    enabled = tuple(
        all_success
        or decision not in _RCSD_ANCHOR_REQUIRED_DECISIONS
        for decision in example.candidate_decisions
    )
    acceptable = tuple(
        index
        for index in example.acceptable_indices
        if enabled[index]
    )
    preferred = (
        example.preferred_index
        if (
            example.preferred_index >= 0
            and enabled[example.preferred_index]
            and example.preferred_index in acceptable
        )
        else -1
    )
    conditioned_candidate_features = (
        _anchor_plan_relation_features(
            example,
            present,
            candidate_node_ids,
        )
        if include_anchor_plan_relations
        else example.candidate_features
    )
    selected_road_ids, selected_node_ids = _successful_anchor_member_sets(
        present
    )
    (
        selected_road_ids_by_anchor,
        selected_node_ids_by_anchor,
    ) = _successful_anchor_member_sets_by_anchor(present)
    conditioned_member_features = tuple(
        condition_ordinary_plan_member_features(
            base_features=base_features,
            road_ids=member_ids,
            endpoint_ids=endpoint_ids,
            selected_road_ids=(
                selected_road_ids
                if include_plan_member_relations
                else set()
            ),
            selected_node_ids=(
                selected_node_ids
                if include_plan_member_relations
                else set()
            ),
        )
        for base_features, member_ids, endpoint_ids in zip(
            example.candidate_member_features,
            example.candidate_member_ids,
            example.candidate_member_endpoint_ids,
            strict=True,
        )
    )
    conditioned_arm_features = tuple(
        condition_ordinary_plan_arm_features(
            base_features=base_features,
            nearest_road_ids=road_ids,
            nearest_node_ids=node_ids,
            arm_anchor_ids=(
                example.arm_anchor_ids if base_features else ()
            ),
            selected_road_ids=(
                selected_road_ids if include_plan_arm_relations else set()
            ),
            selected_node_ids=(
                selected_node_ids if include_plan_arm_relations else set()
            ),
            selected_road_ids_by_anchor=(
                selected_road_ids_by_anchor
                if include_plan_arm_relations
                else {}
            ),
            selected_node_ids_by_anchor=(
                selected_node_ids_by_anchor
                if include_plan_arm_relations
                else {}
            ),
        )
        for base_features, road_ids, node_ids in zip(
            example.candidate_arm_features,
            example.candidate_arm_road_ids,
            example.candidate_arm_node_ids,
            strict=True,
        )
    )
    return OrdinaryAnchorConditionedExample(
        base=example,
        anchor_condition_features=condition_features,
        conditioned_candidate_features=conditioned_candidate_features,
        conditioned_member_features=conditioned_member_features,
        conditioned_arm_features=conditioned_arm_features,
        enabled_candidate_mask=enabled,
        conditioned_acceptable_indices=acceptable,
        conditioned_preferred_index=preferred,
        all_required_anchors_success=all_success,
        anchor_success_count=success_count,
        all_required_anchors_resolved=all_resolved,
        anchor_resolved_count=resolved_count,
        missing_anchor_ids=missing,
    )


def collate_oof_anchor_conditioned_ordinary_batch(
    examples: Sequence[OrdinaryAnchorConditionedExample],
    *,
    decision_class_weights: Mapping[str, float] | None = None,
    case_weights: Mapping[str, float] | None = None,
) -> TargetATrainingBatch:
    if not examples:
        raise ValueError("cannot collate empty conditioned ordinary batch")
    batch = collate_ordinary_plan_batch([example.base for example in examples])
    plan_mask = batch.tensors.ordinary_plan_mask.clone()
    acceptable = torch.zeros_like(batch.targets.ordinary_acceptable)
    preferred = torch.full_like(batch.targets.ordinary_preferred, -1)
    task_mask = torch.zeros_like(batch.targets.ordinary_task_mask)
    teacher = torch.zeros_like(batch.tensors.teacher_ordinary_plan_indices)
    condition_features = torch.tensor(
        [[example.anchor_condition_features] for example in examples],
        dtype=torch.float32,
    )
    plan_features = batch.tensors.ordinary_plan_features.clone()
    member_features = batch.tensors.ordinary_plan_member_features
    if member_features is None:
        raise RuntimeError("ordinary member feature tensor is missing")
    member_features = member_features.clone()
    arm_features = batch.tensors.ordinary_plan_arm_features
    if arm_features is None:
        raise RuntimeError("ordinary arm feature tensor is missing")
    arm_features = arm_features.clone()
    for batch_index, example in enumerate(examples):
        count = len(example.base.candidate_ids)
        plan_features[batch_index, 0, :count] = torch.tensor(
            example.conditioned_candidate_features,
            dtype=torch.float32,
        )
        enabled = torch.tensor(
            example.enabled_candidate_mask,
            dtype=torch.bool,
        )
        plan_mask[batch_index, 0, :count] &= enabled
        for candidate_index, values in enumerate(
            example.conditioned_member_features
        ):
            member_count = len(values)
            if member_count:
                member_features[
                    batch_index,
                    0,
                    candidate_index,
                    :member_count,
                    :,
                ] = torch.tensor(values, dtype=torch.float32)
        for candidate_index, values in enumerate(
            example.conditioned_arm_features
        ):
            arm_count = len(values)
            if arm_count:
                arm_features[
                    batch_index,
                    0,
                    candidate_index,
                    :arm_count,
                    :,
                ] = torch.tensor(values, dtype=torch.float32)
        for candidate_index in example.conditioned_acceptable_indices:
            acceptable[batch_index, 0, candidate_index] = True
        if (
            example.conditioned_label_reachable
            and example.all_required_anchors_resolved
            and example.base.carrier_task_mask
        ):
            task_mask[batch_index, 0] = True
            preferred[batch_index, 0] = example.conditioned_preferred_index
        teacher[batch_index, 0] = _teacher_candidate_index(example)
    tensors = replace(
        batch.tensors,
        ordinary_required_anchor_indices=torch.full_like(
            batch.tensors.ordinary_required_anchor_indices,
            -1,
        ),
        ordinary_plan_features=plan_features,
        ordinary_plan_member_features=member_features,
        ordinary_plan_arm_features=arm_features,
        ordinary_plan_mask=plan_mask,
        teacher_anchor_success=torch.zeros_like(
            batch.tensors.teacher_anchor_success,
        ),
        teacher_ordinary_plan_indices=teacher,
        ordinary_anchor_condition_features=condition_features,
    )
    targets = replace(
        batch.targets,
        ordinary_acceptable=acceptable,
        ordinary_preferred=preferred,
        ordinary_task_mask=task_mask,
        ordinary_sample_weights=torch.tensor(
            [
                [
                    example.base.sample_weight
                    * (
                        decision_class_weights.get(
                            example.base.preferred_decision,
                            1.0,
                        )
                        if decision_class_weights is not None
                        else 1.0
                    )
                    * (
                        case_weights.get(example.case_key, 1.0)
                        if case_weights is not None
                        else 1.0
                    )
                ]
                for example in examples
            ],
            dtype=torch.float32,
        ),
    )
    return TargetATrainingBatch(tensors=tensors, targets=targets)


def conditioned_ordinary_batches(
    examples: Sequence[OrdinaryAnchorConditionedExample],
    *,
    batch_size: int,
    decision_class_weights: Mapping[str, float] | None = None,
    case_weights: Mapping[str, float] | None = None,
) -> list[TargetATrainingBatch]:
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    return [
        collate_oof_anchor_conditioned_ordinary_batch(
            examples[index : index + batch_size],
            decision_class_weights=decision_class_weights,
            case_weights=case_weights,
        )
        for index in range(0, len(examples), batch_size)
    ]


def _teacher_candidate_index(
    example: OrdinaryAnchorConditionedExample,
) -> int:
    if example.fallback_required:
        for index, decision in enumerate(
            example.base.candidate_decisions
        ):
            if (
                decision == "ABSTAIN"
                and example.enabled_candidate_mask[index]
            ):
                return index
    if example.conditioned_preferred_index >= 0:
        return example.conditioned_preferred_index
    if example.conditioned_acceptable_indices:
        return example.conditioned_acceptable_indices[0]
    for decision in ("ABSTAIN", "KEEP_SWSD"):
        for index, candidate_decision in enumerate(
            example.base.candidate_decisions
        ):
            if (
                candidate_decision == decision
                and example.enabled_candidate_mask[index]
            ):
                return index
    return next(
        index
        for index, enabled in enumerate(example.enabled_candidate_mask)
        if enabled
    )


def _read_anchor_oof_predictions(
    path: Path,
    required_keys: set[tuple[str, str]],
) -> dict[tuple[str, str], dict[str, Any]]:
    predictions: dict[tuple[str, str], dict[str, Any]] = {}
    for row in _iter_jsonl(path):
        key = (str(row["case_key"]), str(row["anchor_id"]))
        if key not in required_keys:
            continue
        if key in predictions:
            raise ValueError(f"duplicate OOF anchor prediction: {key}")
        predictions[key] = row
    return predictions


def _read_selected_anchor_conditions(
    path: Path,
    predictions: Mapping[tuple[str, str], Mapping[str, Any]],
    required_keys: set[tuple[str, str]],
) -> dict[tuple[str, str], AnchorOOFCondition]:
    conditions: dict[tuple[str, str], AnchorOOFCondition] = {}
    for row in _iter_jsonl(path):
        key = (str(row["case_key"]), str(row["anchor_id"]))
        prediction = predictions.get(key)
        if key not in required_keys or prediction is None:
            continue
        if key in conditions:
            raise ValueError(f"duplicate anchor inference evidence: {key}")
        candidate_index = int(prediction["candidate_predicted_index"])
        candidate_features = row["candidate_features"]
        if not 0 <= candidate_index < len(candidate_features):
            continue
        conditions[key] = AnchorOOFCondition(
            anchor_id=key[1],
            selected_candidate_id=str(
                prediction["candidate_predicted_id"]
            ),
            predicted_status=str(prediction["predicted"]),
            gate_pass_probability=float(
                prediction["gate_pass_probability"]
            ),
            selected_candidate_features=tuple(
                float(value)
                for value in candidate_features[candidate_index]
            ),
        )
    return conditions


def _anchor_plan_relation_features(
    example: OrdinaryPlanTrainingExample,
    conditions: Sequence[AnchorOOFCondition],
    candidate_node_ids: Sequence[Sequence[str]],
) -> tuple[tuple[float, ...], ...]:
    if len(candidate_node_ids) != len(example.candidate_ids):
        raise ValueError("candidate plan Node relation count differs")
    successful = [condition for condition in conditions if condition.success]
    road_anchors = [
        _candidate_members(condition.selected_candidate_id, "ROAD")
        for condition in successful
        if condition.selected_candidate_id.startswith("ROAD:")
    ]
    node_anchors = [
        _candidate_members(condition.selected_candidate_id, "NODE")
        for condition in successful
        if condition.selected_candidate_id.startswith("NODE:")
    ]
    road_members = set().union(*road_anchors) if road_anchors else set()
    node_members = set().union(*node_anchors) if node_anchors else set()
    result: list[tuple[float, ...]] = []
    for base_features, road_ids, node_ids in zip(
        example.candidate_features,
        example.candidate_road_ids,
        candidate_node_ids,
        strict=True,
    ):
        plan_roads = set(road_ids)
        plan_nodes = set(node_ids)
        road_overlap = plan_roads & road_members
        node_overlap = plan_nodes & node_members
        road_object_coverage = (
            sum(bool(plan_roads & members) for members in road_anchors)
            / len(road_anchors)
            if road_anchors
            else 0.0
        )
        node_object_coverage = (
            sum(bool(plan_nodes & members) for members in node_anchors)
            / len(node_anchors)
            if node_anchors
            else 0.0
        )
        values = list(base_features)
        values[23:36] = [
            min(len(road_anchors), 8) / 8.0,
            min(len(node_anchors), 8) / 8.0,
            len(road_overlap) / max(len(road_members), 1),
            len(node_overlap) / max(len(node_members), 1),
            road_object_coverage,
            node_object_coverage,
            float(bool(road_members) and road_members <= plan_roads),
            float(bool(node_members) and node_members <= plan_nodes),
            float(bool(road_overlap)),
            float(bool(node_overlap)),
            (
                (len(road_overlap) + len(node_overlap))
                / max(
                    len(plan_roads | road_members)
                    + len(plan_nodes | node_members),
                    1,
                )
            ),
            min(len(plan_roads), 16) / 16.0,
            min(len(plan_nodes), 16) / 16.0,
        ]
        result.append(tuple(values))
    return tuple(result)


def _candidate_members(
    candidate_id: str,
    expected_type: str,
) -> set[str]:
    prefix = f"{expected_type}:"
    if not candidate_id.startswith(prefix):
        return set()
    return {
        value
        for value in candidate_id[len(prefix) :].split("|")
        if value
    }


def _successful_anchor_member_sets(
    conditions: Sequence[AnchorOOFCondition],
) -> tuple[set[str], set[str]]:
    successful = [condition for condition in conditions if condition.success]
    road_members = set().union(
        *[
            _candidate_members(condition.selected_candidate_id, "ROAD")
            for condition in successful
            if condition.selected_candidate_id.startswith("ROAD:")
        ]
    ) if any(
        condition.selected_candidate_id.startswith("ROAD:")
        for condition in successful
    ) else set()
    node_members = set().union(
        *[
            _candidate_members(condition.selected_candidate_id, "NODE")
            for condition in successful
            if condition.selected_candidate_id.startswith("NODE:")
        ]
    ) if any(
        condition.selected_candidate_id.startswith("NODE:")
        for condition in successful
    ) else set()
    return road_members, node_members


def _successful_anchor_member_sets_by_anchor(
    conditions: Sequence[AnchorOOFCondition],
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    road_members: dict[str, set[str]] = {}
    node_members: dict[str, set[str]] = {}
    for condition in conditions:
        if not condition.success:
            continue
        roads = _candidate_members(condition.selected_candidate_id, "ROAD")
        nodes = _candidate_members(condition.selected_candidate_id, "NODE")
        if roads:
            road_members[condition.anchor_id] = roads
        if nodes:
            node_members[condition.anchor_id] = nodes
    return road_members, node_members


def _read_candidate_plan_node_ids(
    candidate_root: Path,
    examples: Sequence[OrdinaryPlanTrainingExample],
) -> dict[str, tuple[tuple[str, ...], ...]]:
    case_keys = {example.case_key for example in examples}
    road_paths: dict[str, Path] = {}
    for row in _iter_jsonl(candidate_root / "input_lineage.jsonl"):
        case_key = str(row["case_key"])
        if (
            case_key in case_keys
            and str(row["role"]) == "raw_rcsd_roads"
        ):
            road_paths[case_key] = normalize_runtime_path(
                Path(str(row["path"]))
            ).resolve(strict=True)
    missing_cases = sorted(case_keys - set(road_paths))
    if missing_cases:
        raise ValueError(
            f"ordinary candidate Road lineage is missing: {missing_cases}"
        )
    road_endpoints_by_case: dict[str, dict[str, tuple[str, str]]] = {}
    for case_key, path in sorted(road_paths.items()):
        endpoints: dict[str, tuple[str, str]] = {}
        with fiona.open(path) as source:
            for feature in source:
                properties = dict(feature["properties"])
                road_id = _first_text(
                    properties,
                    ("id", "roadid", "road_id"),
                )
                start_node_id = _first_text(
                    properties,
                    ("snodeid", "start_node_id"),
                )
                end_node_id = _first_text(
                    properties,
                    ("enodeid", "end_node_id"),
                )
                if road_id and start_node_id and end_node_id:
                    endpoints[road_id] = (start_node_id, end_node_id)
        road_endpoints_by_case[case_key] = endpoints
    return {
        example.sample_id: tuple(
            tuple(
                sorted(
                    {
                        node_id
                        for road_id in road_ids
                        for node_id in road_endpoints_by_case[
                            example.case_key
                        ].get(road_id, ())
                    }
                )
            )
            for road_ids in example.candidate_road_ids
        )
        for example in examples
    }


def _first_text(
    properties: Mapping[str, Any],
    keys: Sequence[str],
) -> str:
    for key in keys:
        value = properties.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _iter_jsonl(path: Path):
    with path.open("r", encoding="utf-8-sig") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(
                    f"JSONL row is not an object: {path}:{line_number}"
                )
            yield row


__all__ = [
    "AnchorOOFCondition",
    "OrdinaryAnchorConditionedExample",
    "collate_oof_anchor_conditioned_ordinary_batch",
    "condition_ordinary_plan_example",
    "conditioned_ordinary_batches",
    "read_oof_anchor_conditioned_ordinary_examples",
]
