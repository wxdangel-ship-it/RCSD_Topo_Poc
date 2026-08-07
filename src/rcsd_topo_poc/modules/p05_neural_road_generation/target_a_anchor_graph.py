from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_evidence import (
    ANCHOR_ARM_FEATURE_DIM,
    ANCHOR_MEMBER_LOCAL_FEATURE_DIM,
    ANCHOR_MEMBER_RELATION_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_members import (
    anchor_candidate_member_tensors,
    anchor_member_set_confidence,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_relations import (
    ANCHOR_CANDIDATE_RELATION_DIM,
    anchor_candidate_relation_matrix,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
    TARGET_A_FEATURE_DIM,
    AnchorPretrainExample,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ANCHOR_TYPE_NODE,
    ANCHOR_TYPE_ROAD,
    TargetABatchTensors,
    TargetAJointNetwork,
    hierarchical_anchor_selection_logits,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    TargetATrainingBatch,
    TargetATrainingTargets,
    move_training_batch,
)


@dataclass(frozen=True)
class AnchorDependencyGroup:
    case_key: str
    fold: int
    focal_anchor_id: str
    examples: tuple[AnchorPretrainExample, ...]
    adjacency: tuple[tuple[bool, ...], ...]

    def __post_init__(self) -> None:
        count = len(self.examples)
        if count < 1:
            raise ValueError("anchor dependency group is empty")
        if len(self.adjacency) != count or any(
            len(row) != count for row in self.adjacency
        ):
            raise ValueError("anchor dependency adjacency shape differs")
        if any(row.case_key != self.case_key for row in self.examples):
            raise ValueError("anchor dependency group spans Cases")
        if any(row.fold != self.fold for row in self.examples):
            raise ValueError("anchor dependency group spans folds")
        if self.examples[0].anchor_id != self.focal_anchor_id:
            raise ValueError("focal anchor must be first in its dependency group")
        if any(not self.adjacency[index][index] for index in range(count)):
            raise ValueError("anchor dependency adjacency lacks self edges")


@dataclass(frozen=True)
class AnchorDependencyBatch:
    groups: tuple[AnchorDependencyGroup, ...]
    training_batch: TargetATrainingBatch


def build_anchor_dependency_groups(
    examples: Sequence[AnchorPretrainExample],
) -> tuple[AnchorDependencyGroup, ...]:
    if not examples:
        raise ValueError("anchor dependency grouping requires examples")
    by_case: dict[str, list[AnchorPretrainExample]] = defaultdict(list)
    for row in examples:
        by_case[row.case_key].append(row)
    groups: list[AnchorDependencyGroup] = []
    for case_key, case_examples in sorted(by_case.items()):
        by_anchor: dict[str, AnchorPretrainExample] = {}
        for row in case_examples:
            if row.anchor_id in by_anchor:
                raise ValueError(
                    f"anchor dependency Case has duplicate anchor: "
                    f"{case_key}/{row.anchor_id}"
                )
            by_anchor[row.anchor_id] = row
        neighbours = {anchor_id: {anchor_id} for anchor_id in by_anchor}
        for row in case_examples:
            for dependency_id in row.dependency_anchor_ids or (row.anchor_id,):
                if dependency_id not in by_anchor:
                    continue
                neighbours[row.anchor_id].add(dependency_id)
                neighbours[dependency_id].add(row.anchor_id)
        for focal_anchor_id in sorted(by_anchor):
            anchor_ids = (
                focal_anchor_id,
                *sorted(neighbours[focal_anchor_id] - {focal_anchor_id}),
            )
            component_examples = tuple(by_anchor[value] for value in anchor_ids)
            adjacency = tuple(
                tuple(
                    target_id in neighbours[source_id]
                    for target_id in anchor_ids
                )
                for source_id in anchor_ids
            )
            groups.append(
                AnchorDependencyGroup(
                    case_key=case_key,
                    fold=component_examples[0].fold,
                    focal_anchor_id=focal_anchor_id,
                    examples=component_examples,
                    adjacency=adjacency,
                )
            )
    return tuple(
        sorted(
            groups,
            key=lambda row: (
                row.fold,
                row.case_key,
                row.focal_anchor_id,
            ),
        )
    )


def build_anchor_dependency_batches(
    examples: Sequence[AnchorPretrainExample],
    *,
    max_anchor_count: int,
    include_candidate_relations: bool = False,
) -> tuple[AnchorDependencyBatch, ...]:
    if max_anchor_count < 1:
        raise ValueError("max_anchor_count must be positive")
    groups = tuple(
        sorted(
            build_anchor_dependency_groups(examples),
            key=lambda row: (
                len(row.examples),
                row.fold,
                row.case_key,
                row.focal_anchor_id,
            ),
        )
    )
    packed: list[tuple[AnchorDependencyGroup, ...]] = []
    current: list[AnchorDependencyGroup] = []
    current_count = 0
    for group in groups:
        group_count = len(group.examples)
        if current and current_count + group_count > max_anchor_count:
            packed.append(tuple(current))
            current = []
            current_count = 0
        current.append(group)
        current_count += group_count
        if current_count >= max_anchor_count:
            packed.append(tuple(current))
            current = []
            current_count = 0
    if current:
        packed.append(tuple(current))
    return tuple(
        AnchorDependencyBatch(
            groups=batch_groups,
            training_batch=collate_anchor_dependency_groups(
                batch_groups,
                include_candidate_relations=include_candidate_relations,
            ),
        )
        for batch_groups in packed
    )


def collate_anchor_dependency_groups(
    groups: Sequence[AnchorDependencyGroup],
    *,
    include_candidate_relations: bool = False,
) -> TargetATrainingBatch:
    if not groups:
        raise ValueError("cannot collate empty anchor dependency groups")
    batch_size = len(groups)
    anchor_count = max(len(group.examples) for group in groups)
    candidate_count = max(
        len(group.examples[0].candidate_features)
        for group in groups
    )
    member_rows = tuple(
        anchor_candidate_member_tensors(
            group.examples[0].candidate_ids,
            group.examples[0].candidate_features,
        )
        for group in groups
    )
    member_count = max(
        row.member_features.shape[0]
        for row in member_rows
    )
    member_option_count = max(
        1,
        max(
            len(group.examples[0].member_acceptable_sets)
            for group in groups
        ),
    )
    swsd_arm_count = max(
        1,
        max(
            len(group.examples[0].swsd_arm_features)
            for group in groups
        ),
    )
    member_arm_count = max(
        1,
        max(
            (
                len(arms)
                for group in groups
                for arms in group.examples[0].member_arm_features
            ),
            default=0,
        ),
    )
    object_features = torch.zeros(
        (batch_size, anchor_count, TARGET_A_FEATURE_DIM),
        dtype=torch.float32,
    )
    object_types = torch.zeros((batch_size, anchor_count), dtype=torch.long)
    object_mask = torch.zeros((batch_size, anchor_count), dtype=torch.bool)
    adjacency = torch.zeros(
        (batch_size, anchor_count, anchor_count),
        dtype=torch.bool,
    )
    anchor_indices = torch.full(
        (batch_size, 1),
        -1,
        dtype=torch.long,
    )
    candidate_features = torch.zeros(
        (
            batch_size,
            1,
            candidate_count,
            TARGET_A_FEATURE_DIM,
        ),
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
    swsd_arm_features = torch.zeros(
        (
            batch_size,
            1,
            swsd_arm_count,
            ANCHOR_ARM_FEATURE_DIM,
        ),
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
    anchor_status = torch.zeros(
        (batch_size, 1),
        dtype=torch.long,
    )
    anchor_status_mask = torch.zeros(
        (batch_size, 1),
        dtype=torch.bool,
    )
    anchor_preferred = torch.full(
        (batch_size, 1),
        -1,
        dtype=torch.long,
    )
    anchor_candidate_task_mask = torch.zeros(
        (batch_size, 1),
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
    member_task_mask = torch.zeros(
        (batch_size, 1),
        dtype=torch.bool,
    )
    anchor_sample_weights = torch.zeros(
        (batch_size, 1),
        dtype=torch.float32,
    )
    teacher_anchor_success = torch.zeros(
        (batch_size, 1),
        dtype=torch.bool,
    )
    teacher_anchor_candidate_indices = torch.zeros(
        (batch_size, 1),
        dtype=torch.long,
    )
    for batch_index, group in enumerate(groups):
        count = len(group.examples)
        object_mask[batch_index, :count] = True
        adjacency[batch_index, :count, :count] = torch.tensor(
            group.adjacency,
            dtype=torch.bool,
        )
        anchor_indices[batch_index, 0] = 0
        for anchor_index, row in enumerate(group.examples):
            object_features[batch_index, anchor_index] = torch.tensor(
                row.object_features,
                dtype=torch.float32,
            )
        focal = group.examples[0]
        row_candidate_count = len(focal.candidate_features)
        candidate_features[
            batch_index,
            0,
            :row_candidate_count,
        ] = torch.tensor(
            focal.candidate_features,
            dtype=torch.float32,
        )
        candidate_mask[
            batch_index,
            0,
            :row_candidate_count,
        ] = True
        if candidate_relations is not None:
            candidate_relations[
                batch_index,
                0,
                :row_candidate_count,
                :row_candidate_count,
            ] = anchor_candidate_relation_matrix(focal.candidate_ids)
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
            :row_candidate_count,
            :row_member_count,
        ] = members.candidate_membership
        if focal.structural_member_ids:
            swsd_count = len(focal.swsd_arm_features)
            if swsd_count:
                swsd_arm_features[
                    batch_index,
                    0,
                    :swsd_count,
                ] = torch.tensor(
                    focal.swsd_arm_features,
                    dtype=torch.float32,
                )
                swsd_arm_mask[
                    batch_index,
                    0,
                    :swsd_count,
                ] = True
            for member_index, arms in enumerate(
                focal.member_arm_features
            ):
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
            if focal.member_local_features:
                member_local_features[
                    batch_index,
                    0,
                    :row_member_count,
                ] = torch.tensor(
                    focal.member_local_features,
                    dtype=torch.float32,
                )
            for left, right, relation in focal.member_relation_edges:
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
        for candidate_index in focal.candidate_acceptable_indices:
            if not 0 <= candidate_index < row_candidate_count:
                raise ValueError(
                    "anchor acceptable candidate index is outside the set"
                )
            candidate_acceptable[
                batch_index,
                0,
                candidate_index,
            ] = True
        anchor_status[batch_index, 0] = focal.status_label
        anchor_status_mask[batch_index, 0] = focal.status_supervised
        anchor_preferred[
            batch_index,
            0,
        ] = focal.preferred_candidate_index
        anchor_candidate_task_mask[
            batch_index,
            0,
        ] = focal.candidate_supervised
        for option_index, acceptable in enumerate(
            focal.member_acceptable_sets
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
        member_task_mask[batch_index, 0] = focal.member_supervised
        anchor_sample_weights[
            batch_index,
            0,
        ] = focal.sample_weight
        teacher_anchor_success[
            batch_index,
            0,
        ] = (
            focal.status_supervised
            and focal.status_label
            == ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
        )

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
        anchor_object_indices=anchor_indices,
        anchor_candidate_features=candidate_features,
        anchor_candidate_mask=candidate_mask,
        ordinary_object_indices=torch.full(
            (batch_size, 1),
            -1,
            dtype=torch.long,
        ),
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
        teacher_anchor_candidate_indices=teacher_anchor_candidate_indices,
        teacher_anchor_success=teacher_anchor_success,
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
        sample_weights=torch.ones(batch_size, dtype=torch.float32),
        anchor_status=anchor_status,
        anchor_status_mask=anchor_status_mask,
        anchor_acceptable=candidate_acceptable,
        anchor_preferred=anchor_preferred,
        anchor_candidate_task_mask=anchor_candidate_task_mask,
        ordinary_acceptable=dummy_mask.clone(),
        ordinary_preferred=torch.full(
            (batch_size, 1),
            -1,
            dtype=torch.long,
        ),
        ordinary_task_mask=torch.zeros(
            (batch_size, 1),
            dtype=torch.bool,
        ),
        clue=torch.zeros((batch_size, 1), dtype=torch.long),
        clue_task_mask=torch.zeros((batch_size, 1), dtype=torch.bool),
        fallback_scope=torch.zeros((batch_size, 1), dtype=torch.long),
        fallback_scope_task_mask=torch.zeros(
            (batch_size, 1),
            dtype=torch.bool,
        ),
        advance_right_acceptable=dummy_mask.clone(),
        advance_right_preferred=torch.full(
            (batch_size, 1),
            -1,
            dtype=torch.long,
        ),
        advance_right_task_mask=torch.zeros(
            (batch_size, 1),
            dtype=torch.bool,
        ),
        anchor_sample_weights=anchor_sample_weights,
        anchor_gate=torch.tensor(
            [[group.examples[0].gate_label] for group in groups],
            dtype=torch.long,
        ),
        anchor_gate_mask=torch.tensor(
            [[group.examples[0].gate_supervised] for group in groups],
            dtype=torch.bool,
        ),
        anchor_member_acceptable_sets=member_acceptable_sets,
        anchor_member_acceptable_set_mask=member_acceptable_set_mask,
        anchor_member_task_mask=member_task_mask,
    )
    return TargetATrainingBatch(tensors=tensors, targets=targets)


def predict_anchor_dependency_graph(
    model: TargetAJointNetwork,
    examples: Sequence[AnchorPretrainExample],
    *,
    max_anchor_count: int,
    device: torch.device,
) -> list[dict[str, Any]]:
    model.eval()
    rows: list[dict[str, Any]] = []
    batches = build_anchor_dependency_batches(
        examples,
        max_anchor_count=max_anchor_count,
        include_candidate_relations=(
            model.config.structured_anchor_object_decoder
        ),
    )
    with torch.no_grad():
        for source_batch in batches:
            batch = move_training_batch(source_batch.training_batch, device)
            outputs = model(batch.tensors)
            status_probabilities = torch.softmax(
                outputs["anchor_status_logits"],
                dim=-1,
            ).detach().cpu()
            gate_probabilities = (
                torch.softmax(outputs["anchor_gate_logits"], dim=-1)
                .detach()
                .cpu()
                if "anchor_gate_logits" in outputs
                else None
            )
            raw_candidate_logits = outputs["anchor_candidate_logits"]
            member_logits = outputs.get("anchor_member_logits")
            candidate_logits = raw_candidate_logits
            candidate_validity_logits: torch.Tensor | None = None
            if model.config.structured_anchor_object_decoder:
                candidate_validity_logits = (
                    raw_candidate_logits.detach().cpu()
                )
            type_probabilities: torch.Tensor | None = None
            cardinality_probabilities: torch.Tensor | None = None
            if model.config.hierarchical_anchor_decoder:
                type_logits = outputs["anchor_type_logits"]
                type_probabilities = torch.softmax(
                    type_logits,
                    dim=-1,
                ).detach().cpu()
                cardinality_logits = outputs.get(
                    "anchor_cardinality_logits"
                )
                if cardinality_logits is not None:
                    cardinality_probabilities = torch.softmax(
                        cardinality_logits,
                        dim=-1,
                    ).detach().cpu()
                candidate_logits = hierarchical_anchor_selection_logits(
                    candidate_logits,
                    type_logits,
                    batch.tensors,
                    cardinality_logits=(
                        cardinality_logits
                        if model.config.anchor_cardinality_hard_lock
                        else None
                    ),
                    hard_type_lock=model.config.anchor_type_hard_lock,
                    type_prior_weight=model.config.anchor_type_prior_weight,
                )
            candidate_logits = candidate_logits.detach().cpu()
            for batch_index, group in enumerate(source_batch.groups):
                for anchor_index, example in enumerate(group.examples[:1]):
                    status_probability = status_probabilities[
                        batch_index,
                        anchor_index,
                    ]
                    row_candidate_count = len(example.candidate_ids)
                    candidate_probability = torch.softmax(
                        candidate_logits[
                            batch_index,
                            anchor_index,
                            :row_candidate_count,
                        ],
                        dim=-1,
                    )
                    raw_predicted = int(status_probability.argmax().item())
                    gate_pass_probability = (
                        float(
                            gate_probabilities[
                                batch_index,
                                anchor_index,
                                1,
                            ].item()
                        )
                        if gate_probabilities is not None
                        else 1.0
                    )
                    gate_passed = (
                        gate_pass_probability
                        >= model.config.anchor_gate_pass_threshold
                    )
                    predicted = (
                        raw_predicted
                        if gate_passed
                        else ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN]
                    )
                    candidate_prediction = int(
                        candidate_probability.argmax().item()
                    )
                    member_confidence = (
                        anchor_member_set_confidence(
                            member_logits[
                                batch_index,
                                anchor_index,
                            ],
                            batch.tensors.anchor_member_mask[
                                batch_index,
                                anchor_index,
                            ],
                            batch.tensors.anchor_member_is_road[
                                batch_index,
                                anchor_index,
                            ],
                            batch.tensors.anchor_candidate_membership[
                                batch_index,
                                anchor_index,
                            ],
                            torch.tensor(
                                candidate_prediction,
                                dtype=torch.long,
                                device=device,
                            ),
                        )
                        if member_logits is not None
                        and batch.tensors.anchor_member_mask is not None
                        and batch.tensors.anchor_member_is_road is not None
                        and batch.tensors.anchor_candidate_membership
                        is not None
                        else None
                    )
                    candidate_validity_probability = 1.0
                    if candidate_validity_logits is not None:
                        candidate_validity_probability = float(
                            torch.sigmoid(
                                candidate_validity_logits[
                                    batch_index,
                                    anchor_index,
                                    candidate_prediction,
                                ]
                            ).item()
                        )
                    ordered = candidate_probability.sort(
                        descending=True
                    ).values
                    top_one = float(ordered[0].item())
                    top_two = (
                        float(ordered[1].item())
                        if len(ordered) > 1
                        else 0.0
                    )
                    type_probability: torch.Tensor | None = None
                    type_prediction: int | None = None
                    type_top_one = 1.0
                    type_top_two = 0.0
                    cardinality_prediction: int | None = None
                    cardinality_top_one = 1.0
                    cardinality_top_two = 0.0
                    if type_probabilities is not None:
                        type_probability = type_probabilities[
                            batch_index,
                            anchor_index,
                        ]
                        type_prediction = int(
                            type_probability.argmax().item()
                        )
                        ordered_types = type_probability.sort(
                            descending=True
                        ).values
                        type_top_one = float(ordered_types[0].item())
                        type_top_two = float(ordered_types[1].item())
                        if (
                            cardinality_probabilities is not None
                            and model.config.anchor_cardinality_hard_lock
                        ):
                            cardinality_probability = (
                                cardinality_probabilities[
                                    batch_index,
                                    anchor_index,
                                    type_prediction,
                                ]
                            )
                            ordered_cardinalities = (
                                cardinality_probability.sort(
                                    descending=True
                                ).values
                            )
                            cardinality_prediction = int(
                                cardinality_probability.argmax().item()
                            ) + 1
                            cardinality_top_one = float(
                                ordered_cardinalities[0].item()
                            )
                            cardinality_top_two = float(
                                ordered_cardinalities[1].item()
                                if len(ordered_cardinalities) > 1
                                else 0.0
                            )
                    success_probability = float(
                        status_probability[
                            ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]
                        ].item()
                    )
                    acceptable = set(
                        example.candidate_acceptable_indices
                    )
                    rows.append(
                        {
                            "sample_id": example.sample_id,
                            "case_key": example.case_key,
                            "anchor_id": example.anchor_id,
                            "fold": example.fold,
                            "label_index": example.status_label,
                            "label": list(AnchorStatus)[
                                example.status_label
                            ].value,
                            "status_supervised": (
                                example.status_supervised
                            ),
                            "gate_label": example.gate_label,
                            "gate_supervised": example.gate_supervised,
                            "gate_pass_probability": gate_pass_probability,
                            "gate_passed": gate_passed,
                            "raw_status_predicted_index": raw_predicted,
                            "raw_status_predicted": list(AnchorStatus)[
                                raw_predicted
                            ].value,
                            "predicted_index": predicted,
                            "predicted": list(AnchorStatus)[
                                predicted
                            ].value,
                            "probabilities": {
                                status.value: float(
                                    status_probability[index].item()
                                )
                                for index, status in enumerate(
                                    AnchorStatus
                                )
                            },
                            "candidate_supervised": (
                                example.candidate_supervised
                            ),
                            "candidate_predicted_index": (
                                candidate_prediction
                            ),
                            "candidate_predicted_id": (
                                example.candidate_ids[
                                    candidate_prediction
                                ]
                            ),
                            "candidate_acceptable_indices": sorted(
                                acceptable
                            ),
                            "candidate_acceptable_ids": [
                                example.candidate_ids[index]
                                for index in sorted(acceptable)
                            ],
                            "candidate_preferred_index": (
                                example.preferred_candidate_index
                            ),
                            "candidate_preferred_id": (
                                example.candidate_ids[
                                    example.preferred_candidate_index
                                ]
                                if example.preferred_candidate_index >= 0
                                else ""
                            ),
                            "candidate_acceptable_exact": (
                                candidate_prediction in acceptable
                                if example.candidate_supervised
                                else None
                            ),
                            "candidate_preferred_exact": (
                                candidate_prediction
                                == example.preferred_candidate_index
                                if example.candidate_supervised
                                and example.preferred_candidate_index >= 0
                                else None
                            ),
                            "status_predicted_index": predicted,
                            "success_probability": success_probability,
                            "candidate_probability": top_one,
                            "candidate_margin": top_one - top_two,
                            "candidate_confidence_score": min(
                                gate_pass_probability,
                                success_probability,
                                type_top_one,
                                max(0.0, type_top_one - type_top_two),
                                cardinality_top_one,
                                max(
                                    0.0,
                                    cardinality_top_one
                                    - cardinality_top_two,
                                ),
                                candidate_validity_probability,
                                top_one,
                                max(0.0, top_one - top_two),
                            ),
                            "candidate_type": (
                                (
                                    "ROAD"
                                    if type_prediction == ANCHOR_TYPE_ROAD
                                    else "NODE"
                                )
                                if type_prediction is not None
                                and example.case_key.split(":", 1)[0]
                                in {"T10", "T10-Error", "T10-Error-2"}
                                else _candidate_type(
                                    example,
                                    candidate_prediction,
                                )
                            ),
                            "anchor_type_probabilities": (
                                {
                                    "NODE": float(
                                        type_probability[
                                            ANCHOR_TYPE_NODE
                                        ].item()
                                    ),
                                    "ROAD": float(
                                        type_probability[
                                            ANCHOR_TYPE_ROAD
                                        ].item()
                                    ),
                                }
                                if type_probability is not None
                                else None
                            ),
                            "anchor_type_probability": type_top_one,
                            "anchor_type_margin": (
                                type_top_one - type_top_two
                            ),
                            "anchor_cardinality_prediction": (
                                cardinality_prediction
                            ),
                            "anchor_cardinality_probability": (
                                cardinality_top_one
                            ),
                            "anchor_cardinality_margin": (
                                cardinality_top_one
                                - cardinality_top_two
                            ),
                            "candidate_validity_probability": (
                                candidate_validity_probability
                            ),
                            "member_set_log_probability": (
                                float(
                                    member_confidence.set_log_probability.item()
                                )
                                if member_confidence is not None
                                else None
                            ),
                            "member_set_mean_log_probability": (
                                float(
                                    member_confidence.mean_log_probability.item()
                                )
                                if member_confidence is not None
                                else None
                            ),
                            "member_min_included_probability": (
                                float(
                                    member_confidence
                                    .min_included_probability.item()
                                )
                                if member_confidence is not None
                                else None
                            ),
                            "member_max_excluded_probability": (
                                float(
                                    member_confidence
                                    .max_excluded_probability.item()
                                )
                                if member_confidence is not None
                                else None
                            ),
                            "member_inclusion_margin": (
                                float(
                                    member_confidence.inclusion_margin.item()
                                )
                                if member_confidence is not None
                                else None
                            ),
                            "member_selected_count": (
                                int(
                                    member_confidence
                                    .selected_member_count.item()
                                )
                                if member_confidence is not None
                                else None
                            ),
                            "member_expected_count": (
                                float(
                                    member_confidence
                                    .expected_member_count.item()
                                )
                                if member_confidence is not None
                                else None
                            ),
                            "member_cardinality_residual": (
                                float(
                                    member_confidence
                                    .cardinality_residual.item()
                                )
                                if member_confidence is not None
                                else None
                            ),
                            "member_mean_entropy": (
                                float(
                                    member_confidence.mean_entropy.item()
                                )
                                if member_confidence is not None
                                else None
                            ),
                        }
                    )
    return sorted(rows, key=lambda row: str(row["sample_id"]))


def anchor_dependency_contract(
    examples: Sequence[AnchorPretrainExample],
) -> Mapping[str, Any]:
    groups = build_anchor_dependency_groups(examples)
    sizes = [len(group.examples) for group in groups]
    examples_by_case = defaultdict(dict)
    for row in examples:
        examples_by_case[row.case_key][row.anchor_id] = row
    edges = {
        (
            case_key,
            *sorted((row.anchor_id, dependency_id)),
        )
        for case_key, case_examples in examples_by_case.items()
        for row in case_examples.values()
        for dependency_id in row.dependency_anchor_ids
        if dependency_id in case_examples
        and dependency_id != row.anchor_id
    }
    counts = Counter(sizes)
    return {
        "forward_unit": "T01_SEGMENT_DIRECT_ANCHOR_DEPENDENCY_EGO_GRAPH",
        "group_count": len(groups),
        "multi_anchor_group_count": sum(size > 1 for size in sizes),
        "singleton_group_count": counts.get(1, 0),
        "maximum_anchor_count": max(sizes),
        "mean_anchor_count": sum(sizes) / len(sizes),
        "direct_dependency_edge_count": len(edges),
        "example_count": len(examples),
        "context_object_count_with_reuse": sum(sizes),
    }


def _candidate_type(
    example: AnchorPretrainExample,
    predicted_index: int,
) -> str:
    family = example.case_key.split(":", 1)[0]
    if family not in {"T10", "T10-Error", "T10-Error-2"}:
        return "SINGLE_POINT"
    features = example.candidate_features[predicted_index]
    return "ROAD" if features[27] > 0.5 else "NODE"


__all__ = [
    "AnchorDependencyBatch",
    "AnchorDependencyGroup",
    "anchor_dependency_contract",
    "build_anchor_dependency_batches",
    "build_anchor_dependency_groups",
    "collate_anchor_dependency_groups",
    "predict_anchor_dependency_graph",
]
