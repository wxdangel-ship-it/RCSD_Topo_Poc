from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, fields, replace
from typing import Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    TARGET_A_FEATURE_DIM,
    AnchorPretrainExample,
    collate_anchor_pretrain_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetABatchTensors,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    OrdinaryPlanTrainingExample,
    collate_ordinary_plan_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    TargetATrainingBatch,
    TargetATrainingTargets,
)


@dataclass(frozen=True)
class CaseJointExample:
    """One Case-level forward unit with anchors and ordinary Segments."""

    case_key: str
    fold: int
    anchors: tuple[AnchorPretrainExample, ...]
    ordinary_segments: tuple[OrdinaryPlanTrainingExample, ...]

    def __post_init__(self) -> None:
        if not self.case_key or not self.anchors or not self.ordinary_segments:
            raise ValueError("Case joint example requires anchors and ordinary Segments")
        if any(row.case_key != self.case_key for row in self.anchors):
            raise ValueError("Case joint anchors span Cases")
        if any(row.case_key != self.case_key for row in self.ordinary_segments):
            raise ValueError("Case joint ordinary Segments span Cases")
        if any(row.fold != self.fold for row in self.anchors):
            raise ValueError("Case joint anchors span folds")
        if any(row.fold != self.fold for row in self.ordinary_segments):
            raise ValueError("Case joint ordinary Segments span folds")
        anchor_ids = [row.anchor_id for row in self.anchors]
        segment_ids = [row.segment_id for row in self.ordinary_segments]
        if len(anchor_ids) != len(set(anchor_ids)):
            raise ValueError("Case joint example has duplicate anchors")
        if len(segment_ids) != len(set(segment_ids)):
            raise ValueError("Case joint example has duplicate ordinary Segments")


@dataclass(frozen=True)
class CaseJointBatchMetadata:
    case_key: str
    fold: int
    anchor_ids: tuple[str, ...]
    segment_ids: tuple[str, ...]
    anchor_candidate_ids: tuple[tuple[str, ...], ...]
    ordinary_candidate_ids: tuple[tuple[str, ...], ...]
    ordinary_required_anchor_ids: tuple[tuple[str, ...], ...]
    ordinary_training_ready: tuple[bool, ...]


@dataclass(frozen=True)
class CaseJointBatch:
    example: CaseJointExample
    training_batch: TargetATrainingBatch
    metadata: CaseJointBatchMetadata


@dataclass(frozen=True)
class PackedCaseJointBatch:
    members: tuple[CaseJointBatch, ...]
    training_batch: TargetATrainingBatch


def build_case_joint_examples(
    anchor_examples: Sequence[AnchorPretrainExample],
    ordinary_examples: Sequence[OrdinaryPlanTrainingExample],
) -> tuple[CaseJointExample, ...]:
    """Join once in memory; no Case data is reread for each Segment."""
    if not anchor_examples or not ordinary_examples:
        raise ValueError("Case joint examples require both supervision stores")
    anchors_by_case: dict[str, list[AnchorPretrainExample]] = defaultdict(list)
    ordinary_by_case: dict[str, list[OrdinaryPlanTrainingExample]] = defaultdict(
        list
    )
    for row in anchor_examples:
        anchors_by_case[row.case_key].append(row)
    for row in ordinary_examples:
        ordinary_by_case[row.case_key].append(row)
    shared_cases = sorted(set(anchors_by_case) & set(ordinary_by_case))
    if not shared_cases:
        raise ValueError("anchor and ordinary stores have no shared Cases")
    result = []
    for case_key in shared_cases:
        anchors = tuple(
            sorted(anchors_by_case[case_key], key=lambda row: row.anchor_id)
        )
        ordinary = tuple(
            sorted(
                ordinary_by_case[case_key],
                key=lambda row: row.segment_id,
            )
        )
        folds = {row.fold for row in (*anchors, *ordinary)}
        if len(folds) != 1:
            raise ValueError(f"Case joint fold differs: {case_key}/{sorted(folds)}")
        result.append(
            CaseJointExample(
                case_key=case_key,
                fold=next(iter(folds)),
                anchors=anchors,
                ordinary_segments=ordinary,
            )
        )
    return tuple(result)


def build_segment_joint_examples(
    anchor_examples: Sequence[AnchorPretrainExample],
    ordinary_examples: Sequence[OrdinaryPlanTrainingExample],
) -> tuple[CaseJointExample, ...]:
    """Build bounded focal-Segment subgraphs without transitive Case closure."""
    if not anchor_examples or not ordinary_examples:
        raise ValueError("Segment joint examples require both supervision stores")
    anchors_by_case: dict[str, dict[str, AnchorPretrainExample]] = defaultdict(
        dict
    )
    for row in anchor_examples:
        previous = anchors_by_case[row.case_key].setdefault(row.anchor_id, row)
        if previous is not row:
            raise ValueError(
                f"duplicate anchor in Case: {row.case_key}/{row.anchor_id}"
            )
    result = []
    for ordinary in sorted(
        ordinary_examples,
        key=lambda row: (row.fold, row.case_key, row.segment_id),
    ):
        by_anchor = anchors_by_case.get(ordinary.case_key, {})
        direct_neighbours = _direct_anchor_neighbours(by_anchor)
        selected_ids = {
            value for value in ordinary.required_anchor_ids if value in by_anchor
        }
        for anchor_id in tuple(selected_ids):
            selected_ids.update(direct_neighbours[anchor_id])
        if not selected_ids:
            continue
        anchors = tuple(by_anchor[value] for value in sorted(selected_ids))
        result.append(
            CaseJointExample(
                case_key=ordinary.case_key,
                fold=ordinary.fold,
                anchors=anchors,
                ordinary_segments=(ordinary,),
            )
        )
    if not result:
        raise ValueError("Segment joint builder produced no dependency subgraphs")
    return tuple(result)


def build_focal_ordinary_dependency_examples(
    anchor_examples: Sequence[AnchorPretrainExample],
    ordinary_examples: Sequence[OrdinaryPlanTrainingExample],
    *,
    lightweight_context_segments: bool = False,
) -> tuple[CaseJointExample, ...]:
    """Build one non-transitive Junction-bounded graph per focal Segment.

    The focal Segment is always the first ordinary row. Immediate Segments
    sharing one of its required/dependent anchors are context only; their
    other Junctions are not followed.
    """
    if not anchor_examples or not ordinary_examples:
        raise ValueError("focal ordinary graphs require supervision stores")
    anchors_by_case: dict[str, dict[str, AnchorPretrainExample]] = defaultdict(
        dict
    )
    ordinary_by_case: dict[
        str,
        list[OrdinaryPlanTrainingExample],
    ] = defaultdict(list)
    ordinary_by_anchor: dict[
        str,
        dict[str, list[OrdinaryPlanTrainingExample]],
    ] = defaultdict(lambda: defaultdict(list))
    for row in anchor_examples:
        previous = anchors_by_case[row.case_key].setdefault(
            row.anchor_id,
            row,
        )
        if previous is not row:
            raise ValueError(
                f"duplicate anchor in Case: {row.case_key}/{row.anchor_id}"
            )
    for row in ordinary_examples:
        ordinary_by_case[row.case_key].append(row)
        for anchor_id in row.required_anchor_ids:
            ordinary_by_anchor[row.case_key][anchor_id].append(row)

    result = []
    for case_key in sorted(ordinary_by_case):
        by_anchor = anchors_by_case.get(case_key, {})
        direct_neighbours = _direct_anchor_neighbours(by_anchor)
        for focal in sorted(
            ordinary_by_case[case_key],
            key=lambda row: row.segment_id,
        ):
            selected_ids = {
                anchor_id
                for anchor_id in focal.required_anchor_ids
                if anchor_id in by_anchor
            }
            for anchor_id in tuple(selected_ids):
                selected_ids.update(direct_neighbours[anchor_id])
            if not selected_ids:
                continue
            neighbors = {
                row.segment_id: row
                for anchor_id in selected_ids
                for row in ordinary_by_anchor[case_key].get(
                    anchor_id,
                    (),
                )
                if row.segment_id != focal.segment_id
            }
            context = tuple(
                (
                    _as_context_only_ordinary(neighbors[key])
                    if lightweight_context_segments
                    else neighbors[key]
                )
                for key in sorted(neighbors)
            )
            result.append(
                CaseJointExample(
                    case_key=case_key,
                    fold=focal.fold,
                    anchors=tuple(
                        by_anchor[value] for value in sorted(selected_ids)
                    ),
                    ordinary_segments=(focal, *context),
                )
            )
    if not result:
        raise ValueError("focal ordinary builder produced no dependency graphs")
    return tuple(result)


def _as_context_only_ordinary(
    row: OrdinaryPlanTrainingExample,
) -> OrdinaryPlanTrainingExample:
    """Retain one inference-time Segment token without decoding its carrier."""

    return replace(
        row,
        candidate_ids=(f"CONTEXT_ONLY:{row.segment_id}",),
        candidate_decisions=("ABSTAIN",),
        candidate_road_ids=((),),
        candidate_member_ids=((),),
        candidate_member_endpoint_ids=((),),
        candidate_member_features=((),),
        candidate_arm_road_ids=((),),
        candidate_arm_node_ids=((),),
        candidate_arm_features=((),),
        candidate_features=((0.0,) * TARGET_A_FEATURE_DIM,),
        acceptable_indices=(0,),
        preferred_index=0,
        preferred_decision="ABSTAIN",
        sample_weight=0.0,
        clue_task_mask=False,
        fallback_scope_task_mask=False,
        carrier_task_mask=False,
        candidate_road_roles=((),),
        candidate_owned_road_ids=((),),
        candidate_hard_valid=(True,),
    )


def _direct_anchor_neighbours(
    by_anchor: Mapping[str, AnchorPretrainExample],
) -> dict[str, set[str]]:
    """Return the canonical undirected one-hop anchor dependency graph."""
    neighbours = {
        anchor_id: {anchor_id} for anchor_id in by_anchor
    }
    for row in by_anchor.values():
        for dependency_id in row.dependency_anchor_ids or (row.anchor_id,):
            if dependency_id not in by_anchor:
                continue
            neighbours[row.anchor_id].add(dependency_id)
            neighbours[dependency_id].add(row.anchor_id)
    return neighbours


def segment_joint_anchor_repeat_counts(
    examples: Sequence[CaseJointExample],
) -> dict[tuple[str, str], int]:
    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in examples:
        if len(row.ordinary_segments) != 1:
            raise ValueError("anchor repeat counts require focal-Segment examples")
        required = set(row.ordinary_segments[0].required_anchor_ids)
        for anchor in row.anchors:
            if anchor.anchor_id in required:
                counts[(row.case_key, anchor.anchor_id)] += 1
    return dict(counts)


def focal_joint_anchor_repeat_counts(
    examples: Sequence[CaseJointExample],
) -> dict[tuple[str, str], int]:
    """Count supervision repeats for only the focal Segment in each graph."""

    counts: dict[tuple[str, str], int] = defaultdict(int)
    for row in examples:
        if not row.ordinary_segments:
            raise ValueError("focal anchor repeat counts require a Segment")
        required = set(row.ordinary_segments[0].required_anchor_ids)
        for anchor in row.anchors:
            if anchor.anchor_id in required:
                counts[(row.case_key, anchor.anchor_id)] += 1
    return dict(counts)


def collate_case_joint_batch(
    example: CaseJointExample,
    *,
    teacher_forcing: bool,
    include_candidate_relations: bool = False,
    retain_anchor_structural_evidence: bool = False,
    retain_ordinary_member_evidence: bool = False,
    retain_ordinary_arm_evidence: bool = False,
    anchor_repeat_counts: Mapping[tuple[str, str], int] | None = None,
    focal_only_supervision: bool = False,
    bidirectional_segment_anchor_context: bool = False,
    segment_peer_context: bool = False,
) -> CaseJointBatch:
    """Build one Case forward with anchor and carrier labels physically separate."""
    anchor_batch = collate_anchor_pretrain_batch(
        example.anchors,
        include_candidate_relations=include_candidate_relations,
    )
    ordinary_batch = collate_ordinary_plan_batch(example.ordinary_segments)
    anchor_tensors = anchor_batch.tensors
    ordinary_tensors = ordinary_batch.tensors
    anchor_count = len(example.anchors)
    ordinary_count = len(example.ordinary_segments)
    object_count = anchor_count + ordinary_count
    anchor_index_by_id = {
        row.anchor_id: index for index, row in enumerate(example.anchors)
    }

    object_features = torch.cat(
        (
            anchor_tensors.object_features[:, 0],
            ordinary_tensors.object_features[:, 0],
        ),
        dim=0,
    ).unsqueeze(0)
    object_types = torch.cat(
        (
            torch.zeros(anchor_count, dtype=torch.long),
            torch.ones(ordinary_count, dtype=torch.long),
        )
    ).unsqueeze(0)
    object_mask = torch.ones((1, object_count), dtype=torch.bool)
    adjacency = _case_adjacency(
        example,
        anchor_index_by_id,
        bidirectional_segment_anchor_context=(
            bidirectional_segment_anchor_context
        ),
        segment_peer_context=segment_peer_context,
    )
    required_count = max(
        1,
        max(
            len(row.required_anchor_ids)
            for row in example.ordinary_segments
        ),
    )
    required_indices = torch.full(
        (1, ordinary_count, required_count),
        -1,
        dtype=torch.long,
    )
    training_ready = []
    for ordinary_index, row in enumerate(example.ordinary_segments):
        for required_index, anchor_id in enumerate(row.required_anchor_ids):
            required_indices[0, ordinary_index, required_index] = (
                anchor_index_by_id.get(anchor_id, -1)
            )
        training_ready.append(
            row.carrier_task_mask
            and _ordinary_anchor_training_ready(
                row,
                anchor_index_by_id,
                example.anchors,
            )
        )

    teacher_anchor_indices = torch.tensor(
        [
            [
                _teacher_anchor_candidate_index(row)
                for row in example.anchors
            ]
        ],
        dtype=torch.long,
    )
    teacher_anchor_success = torch.tensor(
        [
            [
                _anchor_training_success(row)
                for row in example.anchors
            ]
        ],
        dtype=torch.bool,
    )
    teacher_ordinary_indices = (
        ordinary_tensors.teacher_ordinary_plan_indices.transpose(0, 1)
        if teacher_forcing
        else None
    )
    dummy_plan_features = torch.zeros(
        (1, 1, 1, TARGET_A_FEATURE_DIM),
        dtype=torch.float32,
    )
    dummy_plan_mask = torch.zeros((1, 1, 1), dtype=torch.bool)

    tensors = TargetABatchTensors(
        object_features=object_features,
        object_types=object_types,
        object_mask=object_mask,
        adjacency=adjacency,
        anchor_object_indices=torch.arange(
            anchor_count,
            dtype=torch.long,
        ).unsqueeze(0),
        anchor_candidate_features=_groups_first(
            anchor_tensors.anchor_candidate_features
        ),
        anchor_candidate_mask=_groups_first(
            anchor_tensors.anchor_candidate_mask
        ),
        ordinary_object_indices=torch.arange(
            anchor_count,
            object_count,
            dtype=torch.long,
        ).unsqueeze(0),
        ordinary_required_anchor_indices=required_indices,
        ordinary_plan_features=_groups_first(
            ordinary_tensors.ordinary_plan_features
        ),
        ordinary_plan_mask=_groups_first(
            ordinary_tensors.ordinary_plan_mask
        ),
        advance_right_object_indices=torch.full(
            (1, 1),
            -1,
            dtype=torch.long,
        ),
        advance_right_source_indices=torch.full(
            (1, 1),
            -1,
            dtype=torch.long,
        ),
        advance_right_target_indices=torch.full(
            (1, 1),
            -1,
            dtype=torch.long,
        ),
        advance_right_plan_features=dummy_plan_features,
        advance_right_plan_mask=dummy_plan_mask,
        teacher_anchor_candidate_indices=(
            teacher_anchor_indices if teacher_forcing else None
        ),
        teacher_anchor_success=(
            teacher_anchor_success if teacher_forcing else None
        ),
        teacher_ordinary_plan_indices=teacher_ordinary_indices,
        anchor_candidate_relations=_optional_groups_first(
            anchor_tensors.anchor_candidate_relations
        ),
        anchor_member_features=_optional_groups_first(
            anchor_tensors.anchor_member_features
        ),
        anchor_member_mask=_optional_groups_first(
            anchor_tensors.anchor_member_mask
        ),
        anchor_member_is_road=_optional_groups_first(
            anchor_tensors.anchor_member_is_road
        ),
        anchor_candidate_membership=_optional_groups_first(
            anchor_tensors.anchor_candidate_membership
        ),
        anchor_swsd_arm_features=_optional_groups_first(
            anchor_tensors.anchor_swsd_arm_features
        )
        if retain_anchor_structural_evidence
        else None,
        anchor_swsd_arm_mask=_optional_groups_first(
            anchor_tensors.anchor_swsd_arm_mask
        )
        if retain_anchor_structural_evidence
        else None,
        anchor_member_arm_features=_optional_groups_first(
            anchor_tensors.anchor_member_arm_features
        )
        if retain_anchor_structural_evidence
        else None,
        anchor_member_arm_mask=_optional_groups_first(
            anchor_tensors.anchor_member_arm_mask
        )
        if retain_anchor_structural_evidence
        else None,
        anchor_member_local_features=_optional_groups_first(
            anchor_tensors.anchor_member_local_features
        )
        if retain_anchor_structural_evidence
        else None,
        anchor_member_relation_features=_optional_groups_first(
            anchor_tensors.anchor_member_relation_features
        )
        if retain_anchor_structural_evidence
        else None,
        anchor_member_relation_mask=_optional_groups_first(
            anchor_tensors.anchor_member_relation_mask
        )
        if retain_anchor_structural_evidence
        else None,
        ordinary_plan_decision_indices=_optional_groups_first(
            ordinary_tensors.ordinary_plan_decision_indices
        ),
        ordinary_plan_member_features=_optional_groups_first(
            ordinary_tensors.ordinary_plan_member_features
        )
        if retain_ordinary_member_evidence
        else None,
        ordinary_plan_member_mask=_optional_groups_first(
            ordinary_tensors.ordinary_plan_member_mask
        )
        if retain_ordinary_member_evidence
        else None,
        ordinary_plan_arm_features=_optional_groups_first(
            ordinary_tensors.ordinary_plan_arm_features
        )
        if retain_ordinary_arm_evidence
        else None,
        ordinary_plan_arm_mask=_optional_groups_first(
            ordinary_tensors.ordinary_plan_arm_mask
        )
        if retain_ordinary_arm_evidence
        else None,
    )
    targets = _case_targets(
        example,
        anchor_batch.targets,
        ordinary_batch.targets,
        tuple(training_ready),
        dummy_plan_mask,
        anchor_repeat_counts=anchor_repeat_counts,
        focal_only_supervision=focal_only_supervision,
    )
    metadata = CaseJointBatchMetadata(
        case_key=example.case_key,
        fold=example.fold,
        anchor_ids=tuple(row.anchor_id for row in example.anchors),
        segment_ids=tuple(row.segment_id for row in example.ordinary_segments),
        anchor_candidate_ids=tuple(
            row.candidate_ids for row in example.anchors
        ),
        ordinary_candidate_ids=tuple(
            row.candidate_ids for row in example.ordinary_segments
        ),
        ordinary_required_anchor_ids=tuple(
            row.required_anchor_ids for row in example.ordinary_segments
        ),
        ordinary_training_ready=tuple(training_ready),
    )
    return CaseJointBatch(
        example=example,
        training_batch=TargetATrainingBatch(
            tensors=tensors,
            targets=targets,
        ),
        metadata=metadata,
    )


def without_case_joint_teacher_forcing(
    batch: TargetATrainingBatch,
) -> TargetATrainingBatch:
    return TargetATrainingBatch(
        tensors=replace(
            batch.tensors,
            teacher_anchor_candidate_indices=None,
            teacher_anchor_success=None,
            teacher_ordinary_plan_indices=None,
        ),
        targets=batch.targets,
    )


def case_joint_batches_for_folds(
    examples: Sequence[CaseJointExample],
    folds: Sequence[int],
    *,
    teacher_forcing: bool,
    include_candidate_relations: bool = False,
    retain_anchor_structural_evidence: bool = False,
    retain_ordinary_member_evidence: bool = False,
    retain_ordinary_arm_evidence: bool = False,
    anchor_repeat_counts: Mapping[tuple[str, str], int] | None = None,
) -> list[CaseJointBatch]:
    selected = set(int(value) for value in folds)
    if not selected:
        raise ValueError("Case joint fold selection is empty")
    result = [
        collate_case_joint_batch(
            row,
            teacher_forcing=teacher_forcing,
            include_candidate_relations=include_candidate_relations,
            retain_anchor_structural_evidence=(
                retain_anchor_structural_evidence
            ),
            retain_ordinary_member_evidence=(
                retain_ordinary_member_evidence
            ),
            retain_ordinary_arm_evidence=retain_ordinary_arm_evidence,
            anchor_repeat_counts=anchor_repeat_counts,
        )
        for row in examples
        if row.fold in selected
    ]
    if not result:
        raise ValueError("Case joint fold selection has no Cases")
    return result


def pack_case_joint_batches(
    batches: Sequence[CaseJointBatch],
    *,
    max_batch_size: int,
    max_anchor_groups: int,
) -> tuple[PackedCaseJointBatch, ...]:
    if max_batch_size < 1 or max_anchor_groups < 1:
        raise ValueError("Case joint packing limits must be positive")
    if not batches:
        raise ValueError("cannot pack empty Case joint batches")
    ordered = sorted(
        batches,
        key=lambda row: (
            len(row.example.anchors),
            row.metadata.fold,
            row.metadata.case_key,
            row.metadata.segment_ids,
        ),
    )
    groups: list[tuple[CaseJointBatch, ...]] = []
    current: list[CaseJointBatch] = []
    current_anchor_count = 0
    for row in ordered:
        row_anchor_count = len(row.example.anchors)
        if current and (
            len(current) >= max_batch_size
            or current_anchor_count + row_anchor_count > max_anchor_groups
        ):
            groups.append(tuple(current))
            current = []
            current_anchor_count = 0
        current.append(row)
        current_anchor_count += row_anchor_count
        if (
            len(current) >= max_batch_size
            or current_anchor_count >= max_anchor_groups
        ):
            groups.append(tuple(current))
            current = []
            current_anchor_count = 0
    if current:
        groups.append(tuple(current))
    return tuple(
        PackedCaseJointBatch(
            members=members,
            training_batch=_stack_training_batches(
                [row.training_batch for row in members]
            ),
        )
        for members in groups
    )


def case_joint_data_contract(
    examples: Sequence[CaseJointExample],
) -> dict[str, int]:
    anchor_count = sum(len(row.anchors) for row in examples)
    ordinary_count = sum(len(row.ordinary_segments) for row in examples)
    anchor_by_case = {
        row.case_key: {anchor.anchor_id: anchor for anchor in row.anchors}
        for row in examples
    }
    ready_count = 0
    missing_required_count = 0
    unresolved_required_count = 0
    for case in examples:
        by_anchor = anchor_by_case[case.case_key]
        for segment in case.ordinary_segments:
            missing = [
                value
                for value in segment.required_anchor_ids
                if value not in by_anchor
            ]
            if missing or not segment.required_anchor_ids:
                missing_required_count += 1
                continue
            if _ordinary_anchor_training_ready(
                segment,
                {
                    anchor_id: index
                    for index, anchor_id in enumerate(
                        sorted(by_anchor)
                    )
                },
                tuple(by_anchor[value] for value in sorted(by_anchor)),
            ):
                ready_count += int(segment.carrier_task_mask)
            else:
                unresolved_required_count += 1
    return {
        "case_count": len(examples),
        "anchor_count": anchor_count,
        "ordinary_segment_count": ordinary_count,
        "ordinary_training_ready_count": ready_count,
        "ordinary_missing_required_anchor_count": missing_required_count,
        "ordinary_unresolved_required_anchor_count": unresolved_required_count,
        "store_read_pass_count": 1,
    }


def _case_targets(
    example: CaseJointExample,
    anchor_targets: TargetATrainingTargets,
    ordinary_targets: TargetATrainingTargets,
    training_ready: tuple[bool, ...],
    dummy_plan_mask: torch.Tensor,
    *,
    anchor_repeat_counts: Mapping[tuple[str, str], int] | None,
    focal_only_supervision: bool,
) -> TargetATrainingTargets:
    anchor_status_mask = _groups_first(anchor_targets.anchor_status_mask)
    anchor_candidate_task_mask = _groups_first(
        anchor_targets.anchor_candidate_task_mask
    )
    anchor_gate_mask = _optional_groups_first(
        anchor_targets.anchor_gate_mask
    )
    anchor_member_task_mask = _optional_groups_first(
        anchor_targets.anchor_member_task_mask
    )
    supervised_anchor_ids = (
        set(example.ordinary_segments[0].required_anchor_ids)
        if focal_only_supervision or len(example.ordinary_segments) == 1
        else {row.anchor_id for row in example.anchors}
    )
    focal_mask = torch.tensor(
        [
            [
                row.anchor_id in supervised_anchor_ids
                for row in example.anchors
            ]
        ],
        dtype=torch.bool,
    )
    anchor_status_mask &= focal_mask
    anchor_candidate_task_mask &= focal_mask
    if anchor_gate_mask is not None:
        anchor_gate_mask &= focal_mask
    if anchor_member_task_mask is not None:
        anchor_member_task_mask &= focal_mask
    anchor_weights = []
    for row in example.anchors:
        divisor = (
            int(
                (anchor_repeat_counts or {}).get(
                    (example.case_key, row.anchor_id),
                    1,
                )
            )
            if row.anchor_id in supervised_anchor_ids
            else 1
        )
        anchor_weights.append(row.sample_weight / max(divisor, 1))
    ordinary_task_mask = torch.tensor(
        [training_ready],
        dtype=torch.bool,
    )
    clue_task_mask = _groups_first(ordinary_targets.clue_task_mask)
    fallback_scope_task_mask = _groups_first(
        ordinary_targets.fallback_scope_task_mask
    )
    ordinary_sample_weights = torch.tensor(
        [[row.sample_weight for row in example.ordinary_segments]],
        dtype=torch.float32,
    )
    if focal_only_supervision:
        focal_ordinary_mask = torch.zeros_like(ordinary_task_mask)
        focal_ordinary_mask[:, 0] = True
        ordinary_task_mask &= focal_ordinary_mask
        clue_task_mask &= focal_ordinary_mask
        fallback_scope_task_mask &= focal_ordinary_mask
        ordinary_sample_weights = ordinary_sample_weights.masked_fill(
            ~focal_ordinary_mask,
            0.0,
        )
    return TargetATrainingTargets(
        sample_weights=torch.ones(1, dtype=torch.float32),
        anchor_status=_groups_first(anchor_targets.anchor_status),
        anchor_status_mask=anchor_status_mask,
        anchor_acceptable=_groups_first(anchor_targets.anchor_acceptable),
        anchor_preferred=_groups_first(anchor_targets.anchor_preferred),
        anchor_candidate_task_mask=anchor_candidate_task_mask,
        ordinary_acceptable=_groups_first(
            ordinary_targets.ordinary_acceptable
        ),
        ordinary_preferred=_groups_first(
            ordinary_targets.ordinary_preferred
        ),
        ordinary_task_mask=ordinary_task_mask,
        clue=_groups_first(ordinary_targets.clue),
        clue_task_mask=clue_task_mask,
        fallback_scope=_groups_first(ordinary_targets.fallback_scope),
        fallback_scope_task_mask=fallback_scope_task_mask,
        advance_right_acceptable=dummy_plan_mask.clone(),
        advance_right_preferred=torch.full((1, 1), -1, dtype=torch.long),
        advance_right_task_mask=torch.zeros((1, 1), dtype=torch.bool),
        anchor_sample_weights=torch.tensor(
            [anchor_weights],
            dtype=torch.float32,
        ),
        anchor_gate=_optional_groups_first(anchor_targets.anchor_gate),
        anchor_gate_mask=anchor_gate_mask,
        ordinary_sample_weights=ordinary_sample_weights,
        anchor_member_acceptable_sets=_optional_groups_first(
            anchor_targets.anchor_member_acceptable_sets
        ),
        anchor_member_acceptable_set_mask=_optional_groups_first(
            anchor_targets.anchor_member_acceptable_set_mask
        ),
        anchor_member_task_mask=anchor_member_task_mask,
    )


def _stack_training_batches(
    batches: Sequence[TargetATrainingBatch],
) -> TargetATrainingBatch:
    if not batches:
        raise ValueError("cannot stack empty training batches")
    if any(batch.targets.sample_weights.shape != (1,) for batch in batches):
        raise ValueError("Case joint stack expects one subgraph per row")
    tensor_values = {}
    index_fields = {
        "anchor_object_indices",
        "ordinary_object_indices",
        "ordinary_required_anchor_indices",
        "advance_right_object_indices",
        "advance_right_source_indices",
        "advance_right_target_indices",
    }
    for field in fields(TargetABatchTensors):
        values = [getattr(batch.tensors, field.name) for batch in batches]
        tensor_values[field.name] = _stack_optional_tensors(
            values,
            pad_value=-1 if field.name in index_fields else 0,
        )
    target_values = {}
    preferred_fields = {
        "anchor_preferred",
        "ordinary_preferred",
        "advance_right_preferred",
    }
    for field in fields(TargetATrainingTargets):
        values = [getattr(batch.targets, field.name) for batch in batches]
        if field.name == "sample_weights":
            target_values[field.name] = torch.cat(values, dim=0)
            continue
        target_values[field.name] = _stack_optional_tensors(
            values,
            pad_value=-1 if field.name in preferred_fields else 0,
        )
    tensors = TargetABatchTensors(**tensor_values)
    targets = TargetATrainingTargets(**target_values)
    return TargetATrainingBatch(tensors=tensors, targets=targets)


def _stack_optional_tensors(
    values: Sequence[torch.Tensor | None],
    *,
    pad_value: int,
) -> torch.Tensor | None:
    if all(value is None for value in values):
        return None
    if any(value is None for value in values):
        raise ValueError("Case joint optional tensor availability differs")
    tensors = [value for value in values if value is not None]
    if any(value.shape[0] != 1 for value in tensors):
        raise ValueError("Case joint tensor row must have batch size one")
    rank = tensors[0].ndim
    if any(value.ndim != rank for value in tensors):
        raise ValueError("Case joint tensor ranks differ")
    maximum_shape = tuple(
        max(value.shape[dimension] for value in tensors)
        for dimension in range(1, rank)
    )
    result = torch.full(
        (len(tensors), *maximum_shape),
        pad_value,
        dtype=tensors[0].dtype,
    )
    for index, value in enumerate(tensors):
        slices = (index,) + tuple(
            slice(0, value.shape[dimension])
            for dimension in range(1, rank)
        )
        result[slices] = value[0]
    return result


def _case_adjacency(
    example: CaseJointExample,
    anchor_index_by_id: dict[str, int],
    *,
    bidirectional_segment_anchor_context: bool = False,
    segment_peer_context: bool = False,
) -> torch.Tensor:
    anchor_count = len(example.anchors)
    ordinary_count = len(example.ordinary_segments)
    object_count = anchor_count + ordinary_count
    adjacency = torch.eye(object_count, dtype=torch.bool)
    for anchor_index, row in enumerate(example.anchors):
        for dependency_id in row.dependency_anchor_ids:
            dependency_index = anchor_index_by_id.get(dependency_id)
            if dependency_index is None:
                continue
            adjacency[anchor_index, dependency_index] = True
            adjacency[dependency_index, anchor_index] = True
    for ordinary_index, row in enumerate(example.ordinary_segments):
        object_index = anchor_count + ordinary_index
        for required_id in row.required_anchor_ids:
            anchor_index = anchor_index_by_id.get(required_id)
            if anchor_index is None:
                continue
            adjacency[object_index, anchor_index] = True
            if bidirectional_segment_anchor_context:
                adjacency[anchor_index, object_index] = True
    if segment_peer_context:
        visible_anchors = [
            _ordinary_visible_anchor_ids(row, example.anchors)
            for row in example.ordinary_segments
        ]
        for left_index in range(ordinary_count):
            left_object = anchor_count + left_index
            for right_index in range(left_index + 1, ordinary_count):
                if not (
                    visible_anchors[left_index]
                    & visible_anchors[right_index]
                ):
                    continue
                right_object = anchor_count + right_index
                adjacency[left_object, right_object] = True
                adjacency[right_object, left_object] = True
    return adjacency.unsqueeze(0)


def _ordinary_visible_anchor_ids(
    ordinary: OrdinaryPlanTrainingExample,
    anchors: Sequence[AnchorPretrainExample],
) -> set[str]:
    by_id = {row.anchor_id: row for row in anchors}
    direct_neighbours = _direct_anchor_neighbours(by_id)
    visible = {
        anchor_id
        for anchor_id in ordinary.required_anchor_ids
        if anchor_id in by_id
    }
    for anchor_id in tuple(visible):
        visible.update(direct_neighbours[anchor_id])
    return visible


def _ordinary_anchor_training_ready(
    ordinary: OrdinaryPlanTrainingExample,
    anchor_index_by_id: dict[str, int],
    anchors: Sequence[AnchorPretrainExample],
) -> bool:
    required_anchor_ids = ordinary.required_anchor_ids
    if not required_anchor_ids:
        return False
    indices = [anchor_index_by_id.get(value, -1) for value in required_anchor_ids]
    if any(index < 0 for index in indices):
        return False
    required = [anchors[index] for index in indices]
    all_success = all(_anchor_training_success(row) for row in required)
    acceptable_decisions = {
        ordinary.candidate_decisions[index]
        for index in ordinary.acceptable_indices
    }
    if all_success:
        return True
    keep_is_acceptable = "KEEP_SWSD" in acceptable_decisions
    return keep_is_acceptable and all(
        _anchor_training_success(row) or _anchor_training_no_evidence(row)
        for row in required
    )


def _anchor_training_success(row: AnchorPretrainExample) -> bool:
    return (
        row.status_supervised
        and row.status_label == ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
        and row.candidate_supervised
        and bool(row.candidate_acceptable_indices)
    )


def _anchor_training_no_evidence(row: AnchorPretrainExample) -> bool:
    return (
        row.status_supervised
        and row.status_label
        == ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]
    )


def _teacher_anchor_candidate_index(row: AnchorPretrainExample) -> int:
    if not _anchor_training_success(row):
        return 0
    if row.preferred_candidate_index in row.candidate_acceptable_indices:
        return row.preferred_candidate_index
    return row.candidate_acceptable_indices[0]


def _groups_first(values: torch.Tensor) -> torch.Tensor:
    if values.shape[1] != 1:
        raise ValueError("source collator must expose one group per example")
    return values.transpose(0, 1).contiguous()


def _optional_groups_first(
    values: torch.Tensor | None,
) -> torch.Tensor | None:
    return None if values is None else _groups_first(values)


__all__ = [
    "CaseJointBatch",
    "CaseJointBatchMetadata",
    "CaseJointExample",
    "PackedCaseJointBatch",
    "build_case_joint_examples",
    "build_focal_ordinary_dependency_examples",
    "build_segment_joint_examples",
    "case_joint_batches_for_folds",
    "case_joint_data_contract",
    "collate_case_joint_batch",
    "focal_joint_anchor_repeat_counts",
    "pack_case_joint_batches",
    "segment_joint_anchor_repeat_counts",
    "without_case_joint_teacher_forcing",
]
