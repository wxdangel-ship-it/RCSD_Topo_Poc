from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import dataclass, replace
from itertools import combinations
from pathlib import Path
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_case_joint_data import (
    CaseJointBatch,
    CaseJointExample,
    collate_case_joint_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
    AnchorPretrainExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    OrdinaryPlanTrainingExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    TargetATrainingBatch,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.common import (
    normalize_runtime_path,
)


_SWSD_PLAN_ID = "SWSD_ONLY"
_RCSD_PLAN_PREFIX = "RCSD_SET:"
_ADVANCE_RIGHT_OBJECT_TYPE = 2
ADVANCE_RIGHT_RECALL_CARDINALITY_FEATURE_INDEX = 59
ADVANCE_RIGHT_RECALL_SWSD_FEATURE_INDEX = 60
ADVANCE_RIGHT_RECALL_RCSD_FEATURE_INDEX = 61


@dataclass(frozen=True)
class AdvanceRightRecallPlan:
    plan_id: str
    road_ids: tuple[str, ...]
    feature_values: tuple[float, ...]

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("AdvanceRight recall plan requires an id")
        if len(self.feature_values) != TARGET_A_FEATURE_DIM:
            raise ValueError("AdvanceRight recall plan feature dimension differs")
        if len(self.road_ids) != len(set(self.road_ids)):
            raise ValueError("AdvanceRight recall plan repeats a Road")


@dataclass(frozen=True)
class AdvanceRightRecallExample:
    case_key: str
    segment_id: str
    fold: int
    source_segment_id: str
    target_segment_id: str
    plans: tuple[AdvanceRightRecallPlan, ...]
    acceptable_plan_ids: frozenset[str]
    preferred_plan_id: str | None
    task_mask: bool
    label_weight: float
    truth_plan_type: str
    source_truth_decision: str = ""
    target_truth_decision: str = ""
    source_truth_road_ids: tuple[str, ...] = ()
    target_truth_road_ids: tuple[str, ...] = ()
    source_truth_access_road_ids: tuple[str, ...] = ()
    target_truth_access_road_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.case_key or not self.segment_id:
            raise ValueError("AdvanceRight recall example lacks identity")
        if not self.source_segment_id or not self.target_segment_id:
            raise ValueError("AdvanceRight recall example lacks adjacent Segment")
        plan_ids = {row.plan_id for row in self.plans}
        if len(plan_ids) != len(self.plans) or not self.plans:
            raise ValueError("AdvanceRight recall plans are empty or duplicated")
        if not self.acceptable_plan_ids <= plan_ids:
            raise ValueError("AdvanceRight acceptable plan is unavailable")
        if self.task_mask and not self.acceptable_plan_ids:
            raise ValueError("supervised AdvanceRight has no acceptable plan")
        if (
            self.preferred_plan_id is not None
            and self.preferred_plan_id not in self.acceptable_plan_ids
        ):
            raise ValueError("AdvanceRight preferred plan is not acceptable")


@dataclass(frozen=True)
class EndToEndRecallExample:
    dependency_subgraph: CaseJointExample
    advance_right: AdvanceRightRecallExample | None = None

    def __post_init__(self) -> None:
        if self.advance_right is None:
            return
        if self.advance_right.case_key != self.dependency_subgraph.case_key:
            raise ValueError("AdvanceRight and dependency subgraph span Cases")
        if self.advance_right.fold != self.dependency_subgraph.fold:
            raise ValueError("AdvanceRight and dependency subgraph span folds")
        segment_ids = {
            row.segment_id
            for row in self.dependency_subgraph.ordinary_segments
        }
        if not {
            self.advance_right.source_segment_id,
            self.advance_right.target_segment_id,
        } <= segment_ids:
            raise ValueError("AdvanceRight adjacent Segment is outside subgraph")


@dataclass(frozen=True)
class EndToEndRecallBatch:
    example: EndToEndRecallExample
    training_batch: TargetATrainingBatch
    base_batch: CaseJointBatch


def build_advance_right_recall_examples(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[AdvanceRightRecallExample, ...]:
    """Turn truth-free Road bundles into complete-plan recall candidates."""
    result = []
    for row in rows:
        base_feature = row.get("base_feature")
        if not isinstance(base_feature, Mapping):
            raise ValueError("AdvanceRight joint row lacks base inference feature")
        if bool(base_feature.get("feature_uses_truth")):
            raise ValueError("AdvanceRight recall feature uses truth")
        source_id = _owner_segment_id(row, base_feature, "source")
        target_id = _owner_segment_id(row, base_feature, "target")
        if not source_id or not target_id:
            continue
        plans = [_swsd_plan()]
        by_bundle: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for candidate in base_feature.get("candidate_rows", ()):
            candidate_id = str(candidate.get("candidate_road_id") or "")
            if not candidate_id:
                raise ValueError("AdvanceRight candidate lacks Road id")
            bundle_id = str(candidate.get("bundle_id") or candidate_id)
            by_bundle[bundle_id].append(candidate)
        plans.extend(_rcsd_recall_plans(by_bundle))
        acceptable = _acceptable_plan_ids(
            plans,
            truth_plan_type=str(row.get("truth_plan_type") or ""),
            acceptable_candidate_groups=row.get(
                "acceptable_candidate_groups",
                (),
            ),
        )
        task_mask = bool(row.get("candidate_supervised") and acceptable)
        preferred = sorted(acceptable)[0] if task_mask else None
        result.append(
            AdvanceRightRecallExample(
                case_key=str(row.get("case_key") or ""),
                segment_id=str(row.get("object_id") or ""),
                fold=int(row.get("fold", -1)),
                source_segment_id=source_id,
                target_segment_id=target_id,
                plans=tuple(plans),
                acceptable_plan_ids=frozenset(acceptable),
                preferred_plan_id=preferred,
                task_mask=task_mask,
                label_weight=float(row.get("label_weight", 1.0)),
                truth_plan_type=str(row.get("truth_plan_type") or ""),
                source_truth_decision=_side_truth_decision(
                    row.get("source_context")
                ),
                target_truth_decision=_side_truth_decision(
                    row.get("target_context")
                ),
                source_truth_road_ids=_side_truth_road_ids(
                    row.get("source_context"),
                    "road_members",
                ),
                target_truth_road_ids=_side_truth_road_ids(
                    row.get("target_context"),
                    "road_members",
                ),
                source_truth_access_road_ids=_side_truth_road_ids(
                    row.get("source_context"),
                    "access_rows",
                ),
                target_truth_access_road_ids=_side_truth_road_ids(
                    row.get("target_context"),
                    "access_rows",
                ),
            )
        )
    return tuple(
        sorted(
            result,
            key=lambda value: (
                value.fold,
                value.case_key,
                value.segment_id,
            ),
        )
    )


def build_advance_right_dependency_subgraphs(
    anchors: Sequence[AnchorPretrainExample],
    ordinary: Sequence[OrdinaryPlanTrainingExample],
    advance_right: Sequence[AdvanceRightRecallExample],
) -> tuple[EndToEndRecallExample, ...]:
    """Build one Junction-bounded forward unit per AdvanceRight Segment."""
    anchors_by_case: dict[str, dict[str, AnchorPretrainExample]] = defaultdict(
        dict
    )
    ordinary_by_key: dict[
        tuple[str, str],
        OrdinaryPlanTrainingExample,
    ] = {}
    ordinary_by_anchor: dict[
        str,
        dict[str, list[OrdinaryPlanTrainingExample]],
    ] = defaultdict(lambda: defaultdict(list))
    for row in anchors:
        previous = anchors_by_case[row.case_key].setdefault(row.anchor_id, row)
        if previous is not row:
            raise ValueError("duplicate anchor in AdvanceRight dependency Case")
    for row in ordinary:
        key = (row.case_key, row.segment_id)
        if key in ordinary_by_key:
            raise ValueError("duplicate ordinary Segment in dependency store")
        ordinary_by_key[key] = row
        for anchor_id in row.required_anchor_ids:
            ordinary_by_anchor[row.case_key][anchor_id].append(row)
    result = []
    for advance in advance_right:
        side_rows = tuple(
            ordinary_by_key.get((advance.case_key, segment_id))
            for segment_id in (
                advance.source_segment_id,
                advance.target_segment_id,
            )
        )
        if any(row is None for row in side_rows):
            continue
        resolved_side_rows = tuple(
            {
                row.segment_id: row
                for row in side_rows
                if row is not None
            }.values()
        )
        if any(row.fold != advance.fold for row in resolved_side_rows):
            raise ValueError("AdvanceRight adjacent Segment fold differs")
        by_anchor = anchors_by_case.get(advance.case_key, {})
        selected_ids = {
            anchor_id
            for row in resolved_side_rows
            for anchor_id in row.required_anchor_ids
            if anchor_id in by_anchor
        }
        for anchor_id in tuple(selected_ids):
            selected_ids.update(
                dependency_id
                for dependency_id in by_anchor[
                    anchor_id
                ].dependency_anchor_ids
                if dependency_id in by_anchor
            )
        if not selected_ids:
            continue
        context_by_id = {
            row.segment_id: row
            for anchor_id in selected_ids
            for row in ordinary_by_anchor[advance.case_key].get(
                anchor_id,
                (),
            )
        }
        context_by_id.update(
            {
                row.segment_id: row
                for row in resolved_side_rows
            }
        )
        if any(row.fold != advance.fold for row in context_by_id.values()):
            raise ValueError("AdvanceRight Junction context fold differs")
        subgraph = CaseJointExample(
            case_key=advance.case_key,
            fold=advance.fold,
            anchors=tuple(by_anchor[value] for value in sorted(selected_ids)),
            ordinary_segments=tuple(
                context_by_id[value]
                for value in sorted(context_by_id)
            ),
        )
        result.append(
            EndToEndRecallExample(
                dependency_subgraph=subgraph,
                advance_right=advance,
            )
        )
    return tuple(result)


def read_inference_only_ordinary_plan_examples(
    *,
    candidate_store_root: Path,
    required_keys: set[tuple[str, str]],
    fold_by_case: Mapping[str, int],
) -> tuple[OrdinaryPlanTrainingExample, ...]:
    """Read unlabeled adjacent Segments without inventing carrier truth."""
    if not required_keys:
        return ()
    root = normalize_runtime_path(candidate_store_root).resolve(strict=True)
    selected: dict[tuple[str, str], OrdinaryPlanTrainingExample] = {}
    with (root / "inference_plan_groups.jsonl").open(
        "r",
        encoding="utf-8",
    ) as handle:
        for line in handle:
            row = json.loads(line)
            key = (str(row["case_key"]), str(row["segment_id"]))
            if key not in required_keys:
                continue
            candidates = list(row["candidates"])
            dummy_index = next(
                (
                    index
                    for index, candidate in enumerate(candidates)
                    if str(candidate["decision"]) == "KEEP_SWSD"
                ),
                0,
            )
            selected[key] = _inference_only_ordinary_example(
                row,
                candidates,
                fold=int(fold_by_case[key[0]]),
                dummy_index=dummy_index,
            )
    missing = required_keys - set(selected)
    if missing:
        preview = sorted(missing)[:5]
        raise ValueError(
            f"ordinary inference context is missing: {preview}"
        )
    return tuple(selected[key] for key in sorted(selected))


def collate_end_to_end_recall_batch(
    example: EndToEndRecallExample,
    *,
    teacher_forcing: bool,
    include_candidate_relations: bool = True,
    retain_anchor_structural_evidence: bool = True,
    retain_ordinary_member_evidence: bool = True,
    retain_ordinary_arm_evidence: bool = True,
) -> EndToEndRecallBatch:
    base = collate_case_joint_batch(
        example.dependency_subgraph,
        teacher_forcing=teacher_forcing,
        include_candidate_relations=include_candidate_relations,
        retain_anchor_structural_evidence=retain_anchor_structural_evidence,
        retain_ordinary_member_evidence=retain_ordinary_member_evidence,
        retain_ordinary_arm_evidence=retain_ordinary_arm_evidence,
    )
    if example.advance_right is None:
        return EndToEndRecallBatch(
            example=example,
            training_batch=base.training_batch,
            base_batch=base,
        )
    advance = example.advance_right
    segment_index = {
        segment_id: index
        for index, segment_id in enumerate(base.metadata.segment_ids)
    }
    source_group = segment_index[advance.source_segment_id]
    target_group = segment_index[advance.target_segment_id]
    training = base.training_batch
    tensors = training.tensors
    object_count = tensors.object_features.shape[1]
    plan_features = torch.tensor(
        [[
            [list(plan.feature_values) for plan in advance.plans]
        ]],
        dtype=torch.float32,
    )
    plan_mask = torch.ones(
        (1, 1, len(advance.plans)),
        dtype=torch.bool,
    )
    ar_object_feature = plan_features.mean(dim=2)
    object_features = torch.cat(
        (tensors.object_features, ar_object_feature),
        dim=1,
    )
    object_types = torch.cat(
        (
            tensors.object_types,
            torch.full(
                (1, 1),
                _ADVANCE_RIGHT_OBJECT_TYPE,
                dtype=torch.long,
            ),
        ),
        dim=1,
    )
    object_mask = torch.cat(
        (tensors.object_mask, torch.ones((1, 1), dtype=torch.bool)),
        dim=1,
    )
    adjacency = torch.zeros(
        (1, object_count + 1, object_count + 1),
        dtype=torch.bool,
    )
    adjacency[:, :object_count, :object_count] = tensors.adjacency
    adjacency[:, object_count, object_count] = True
    tensors = replace(
        tensors,
        object_features=object_features,
        object_types=object_types,
        object_mask=object_mask,
        adjacency=adjacency,
        advance_right_object_indices=torch.tensor(
            [[object_count]],
            dtype=torch.long,
        ),
        advance_right_source_indices=torch.tensor(
            [[source_group]],
            dtype=torch.long,
        ),
        advance_right_target_indices=torch.tensor(
            [[target_group]],
            dtype=torch.long,
        ),
        advance_right_plan_features=plan_features,
        advance_right_plan_mask=plan_mask,
    )
    plan_index = {
        plan.plan_id: index for index, plan in enumerate(advance.plans)
    }
    acceptable = torch.tensor(
        [[[
            plan.plan_id in advance.acceptable_plan_ids
            for plan in advance.plans
        ]]],
        dtype=torch.bool,
    )
    preferred = (
        plan_index[advance.preferred_plan_id]
        if advance.preferred_plan_id is not None
        else -1
    )
    targets = replace(
        training.targets,
        advance_right_acceptable=acceptable,
        advance_right_preferred=torch.tensor(
            [[preferred]],
            dtype=torch.long,
        ),
        advance_right_task_mask=torch.tensor(
            [[advance.task_mask]],
            dtype=torch.bool,
        ),
    )
    return EndToEndRecallBatch(
        example=example,
        training_batch=TargetATrainingBatch(
            tensors=tensors,
            targets=targets,
        ),
        base_batch=base,
    )


def _inference_only_ordinary_example(
    group: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    *,
    fold: int,
    dummy_index: int,
) -> OrdinaryPlanTrainingExample:
    member_rows = [
        list(candidate.get("road_members") or ())
        for candidate in candidates
    ]
    arm_rows = [
        list(candidate.get("arm_rows") or ())
        for candidate in candidates
    ]
    key = (str(group["case_key"]), str(group["segment_id"]))
    return OrdinaryPlanTrainingExample(
        sample_id=f"{key[0]}:{key[1]}:INFERENCE_ONLY",
        case_key=key[0],
        segment_id=key[1],
        fold=fold,
        object_features=tuple(
            float(value) for value in group["object_features"]
        ),
        required_anchor_ids=tuple(
            str(value) for value in group["required_anchor_ids"]
        ),
        arm_anchor_ids=tuple(
            str(value) for value in group.get("arm_anchor_ids") or ()
        ),
        candidate_ids=tuple(
            str(candidate["plan_id"]) for candidate in candidates
        ),
        candidate_decisions=tuple(
            str(candidate["decision"]) for candidate in candidates
        ),
        candidate_road_ids=tuple(
            tuple(str(value) for value in candidate["road_ids"])
            for candidate in candidates
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
                tuple(float(value) for value in member["features"])
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
            tuple(float(value) for value in candidate["features"])
            for candidate in candidates
        ),
        acceptable_indices=(dummy_index,),
        preferred_index=dummy_index,
        preferred_decision=str(candidates[dummy_index]["decision"]),
        sample_weight=0.0,
        clue_label=0,
        clue_task_mask=False,
        fallback_scope_label=0,
        fallback_scope_task_mask=False,
        carrier_task_mask=False,
    )


def _owner_segment_id(
    row: Mapping[str, Any],
    base_feature: Mapping[str, Any],
    side_name: str,
) -> str:
    context = row.get(f"{side_name}_context")
    if isinstance(context, Mapping):
        value = str(context.get("owner_segment_id") or "")
        if value:
            return value
    side = base_feature.get(f"{side_name}_side")
    return (
        str(side.get("owner_segment_id") or "")
        if isinstance(side, Mapping)
        else ""
    )


def _swsd_plan() -> AdvanceRightRecallPlan:
    values = [0.0] * TARGET_A_FEATURE_DIM
    values[ADVANCE_RIGHT_RECALL_SWSD_FEATURE_INDEX] = 1.0
    return AdvanceRightRecallPlan(
        plan_id=_SWSD_PLAN_ID,
        road_ids=(),
        feature_values=tuple(values),
    )


def _rcsd_recall_plans(
    by_bundle: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[AdvanceRightRecallPlan, ...]:
    candidates_by_road = {
        str(candidate.get("candidate_road_id") or ""): candidate
        for candidates in by_bundle.values()
        for candidate in candidates
    }
    if not all(candidates_by_road):
        raise ValueError("AdvanceRight candidate Road id is empty")
    road_ids = sorted(candidates_by_road)
    candidate_sets: dict[
        tuple[str, ...],
        tuple[Mapping[str, Any], ...],
    ] = {}
    if len(road_ids) <= 8:
        for count in range(1, len(road_ids) + 1):
            for selected_ids in combinations(road_ids, count):
                candidate_sets[selected_ids] = tuple(
                    candidates_by_road[value] for value in selected_ids
                )
    else:
        bundle_ids = sorted(by_bundle)
        for count in range(1, len(bundle_ids) + 1):
            for selected_bundles in combinations(bundle_ids, count):
                selected = {
                    str(candidate.get("candidate_road_id") or ""): candidate
                    for bundle_id in selected_bundles
                    for candidate in by_bundle[bundle_id]
                }
                selected_ids = tuple(sorted(selected))
                candidate_sets[selected_ids] = tuple(
                    selected[value] for value in selected_ids
                )
        all_ids = tuple(road_ids)
        candidate_sets[all_ids] = tuple(
            candidates_by_road[value] for value in all_ids
        )
    return tuple(
        _rcsd_bundle_plan(candidates)
        for _, candidates in sorted(
            candidate_sets.items(),
            key=lambda item: (len(item[0]), item[0]),
        )
    )


def _rcsd_bundle_plan(
    candidates: Sequence[Mapping[str, Any]],
) -> AdvanceRightRecallPlan:
    feature_rows = [
        [float(value) for value in row.get("local_feature_values", ())]
        for row in candidates
    ]
    feature_dim = max((len(row) for row in feature_rows), default=0)
    if feature_dim > 50:
        raise ValueError("AdvanceRight local feature dimension exceeds 50")
    padded = [
        row + [0.0] * (50 - len(row))
        for row in feature_rows
    ]
    values = [0.0] * TARGET_A_FEATURE_DIM
    if padded:
        for feature_index in range(50):
            column = [row[feature_index] for row in padded]
            values[feature_index] = sum(column) / len(column)
        summary_values = [
            value
            for feature_index in range(4)
            for value in (
                max(row[feature_index] for row in padded),
                min(row[feature_index] for row in padded),
            )
        ]
        values[50:58] = summary_values
        values[58] = math.log1p(len(candidates))
        values[59] = float(len(road_ids := {
            str(row.get("candidate_road_id") or "")
            for row in candidates
        }))
    values[ADVANCE_RIGHT_RECALL_RCSD_FEATURE_INDEX] = 1.0
    values[62] = math.log1p(len(candidates))
    road_ids = tuple(sorted(road_ids))
    if not all(road_ids):
        raise ValueError("AdvanceRight bundle contains an empty Road id")
    return AdvanceRightRecallPlan(
        plan_id=f"{_RCSD_PLAN_PREFIX}{'|'.join(road_ids)}",
        road_ids=road_ids,
        feature_values=tuple(values),
    )


def _acceptable_plan_ids(
    plans: Sequence[AdvanceRightRecallPlan],
    *,
    truth_plan_type: str,
    acceptable_candidate_groups: Any,
) -> set[str]:
    if truth_plan_type == _SWSD_PLAN_ID:
        return {_SWSD_PLAN_ID}
    if truth_plan_type not in {"RCSD_ONLY", "MIXED_SPLICE"}:
        return set()
    groups = [
        {str(value) for value in values}
        for values in acceptable_candidate_groups
    ]
    if not groups or any(not group for group in groups):
        return set()
    result = set()
    for plan in plans:
        selected = set(plan.road_ids)
        if len(selected) != len(groups):
            continue
        if all(len(selected & group) == 1 for group in groups):
            result.add(plan.plan_id)
    return result


def _side_truth_decision(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    source = str(value.get("data_source") or "")
    if source == "SWSD":
        return "KEEP_SWSD"
    if source == "RCSD":
        return "USE_RCSD"
    return ""


def _side_truth_road_ids(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    return tuple(
        sorted(
            {
                str(row.get("road_id") or "")
                for row in value.get(field) or ()
                if str(row.get("road_id") or "")
            }
        )
    )


__all__ = [
    "AdvanceRightRecallExample",
    "AdvanceRightRecallPlan",
    "ADVANCE_RIGHT_RECALL_CARDINALITY_FEATURE_INDEX",
    "ADVANCE_RIGHT_RECALL_RCSD_FEATURE_INDEX",
    "ADVANCE_RIGHT_RECALL_SWSD_FEATURE_INDEX",
    "EndToEndRecallBatch",
    "EndToEndRecallExample",
    "build_advance_right_dependency_subgraphs",
    "build_advance_right_recall_examples",
    "collate_end_to_end_recall_batch",
    "read_inference_only_ordinary_plan_examples",
]
