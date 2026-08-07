from __future__ import annotations

import copy
import random
import time
from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_business_plan import (
    BusinessPlanTemplate,
    business_plan_targets,
    decode_business_plan_tasks,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_data import (
    OBJECT_ROLE_INDICES,
    TASK_CLASSES,
    JunctionJointBatch,
    JunctionJointExample,
    collate_junction_joint,
    virtual_surface_carrier_candidate_mask,
    virtual_surface_carrier_object_grid,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_network import (
    JunctionJointConfig,
    JunctionJointNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_ROLE_INDEX,
)


TASK_LOSS_WEIGHTS: Mapping[str, float] = {
    "t07_step1": 1.00,
    "t07_step2": 0.75,
    "surface_mode": 1.00,
    "surface_state": 1.00,
    "relation_state": 1.25,
    "junctionization_action": 1.50,
    "final_state": 2.00,
}


@dataclass(frozen=True)
class JunctionJointTrainingResult:
    model: JunctionJointNetwork
    best_epoch: int
    history: tuple[Mapping[str, float], ...]
    wall_seconds: float
    cohort_audit: Mapping[str, object]


def compute_junction_joint_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
    *,
    class_weights: Mapping[str, torch.Tensor] | None = None,
    business_plan_catalog: Sequence[BusinessPlanTemplate] | None = None,
) -> tuple[torch.Tensor, dict[str, float]]:
    weighted: list[tuple[float, torch.Tensor]] = []
    metrics: dict[str, float] = {}
    exact_relation_task_mask = _exact_relation_task_mask(batch)
    weak_relation_task_mask = (
        batch.object_task_mask & ~_complete_relation_plan_mask(batch)
    )
    for task, weight in TASK_LOSS_WEIGHTS.items():
        loss = _weighted_masked_cross_entropy(
            outputs[f"{task}_logits"],
            batch.task_labels[task],
            batch.task_masks[task],
            batch.sample_weights,
            None if class_weights is None else class_weights.get(task),
        )
        weighted.append((weight, loss))
        metrics[f"{task}_loss"] = float(loss.detach().item())

    surface_loss = _surface_loss(outputs["surface_logits"], batch)
    surface_boundary_loss = (
        _surface_boundary_loss(outputs, batch)
        if "surface_row_left_logits" in outputs
        else outputs["surface_logits"].sum() * 0.0
    )
    surface_object_valid_mask = batch.geometry_object_mask & batch.geometry_object_roles.eq(
        GEOMETRY_ROLE_INDEX["RCSD_INTERSECTION"]
    )
    surface_object_loss = _acceptable_multilabel_loss(
        outputs["surface_object_logits"],
        valid_mask=surface_object_valid_mask,
        acceptable_sets=batch.surface_object_acceptable_sets,
        acceptable_set_mask=batch.surface_object_acceptable_set_mask,
        task_mask=batch.surface_object_task_mask,
        sample_weights=batch.sample_weights,
    )
    surface_object_cardinality_loss = _surface_object_cardinality_loss(
        outputs,
        batch,
    )
    virtual_surface_carrier_valid_mask = virtual_surface_carrier_candidate_mask(batch)
    virtual_surface_carrier_loss = _acceptable_multilabel_loss(
        outputs["virtual_surface_carrier_logits"],
        valid_mask=virtual_surface_carrier_valid_mask,
        acceptable_sets=batch.virtual_surface_carrier_acceptable_sets,
        acceptable_set_mask=batch.virtual_surface_carrier_acceptable_set_mask,
        task_mask=batch.virtual_surface_carrier_task_mask,
        sample_weights=batch.sample_weights,
    )
    virtual_surface_carrier_cardinality_loss = (
        _virtual_surface_carrier_cardinality_loss(outputs, batch)
    )
    structured_virtual_surface_carrier_loss = (
        outputs["virtual_surface_carrier_logits"].sum() * 0.0
    )
    if "structured_virtual_surface_carrier_loss_by_row" in outputs:
        per_row = outputs["structured_virtual_surface_carrier_loss_by_row"]
        if per_row.shape != batch.virtual_surface_carrier_task_mask.shape:
            raise ValueError("structured virtual carrier loss shape differs")
        weights = batch.sample_weights * batch.virtual_surface_carrier_task_mask.to(
            batch.sample_weights.dtype
        )
        structured_virtual_surface_carrier_loss = (
            per_row * weights
        ).sum() / weights.sum().clamp_min(1e-8)
    virtual_surface_geometric_coverage_loss = (
        _virtual_surface_geometric_coverage_loss(outputs, batch)
        if "virtual_surface_geometric_coverage_logits" in outputs
        else outputs["virtual_surface_carrier_logits"].sum() * 0.0
    )
    object_loss = _acceptable_multilabel_loss(
        outputs["object_logits"],
        valid_mask=batch.object_supervision_mask,
        acceptable_sets=batch.object_acceptable_sets,
        acceptable_set_mask=batch.object_acceptable_set_mask,
        task_mask=exact_relation_task_mask,
        sample_weights=batch.sample_weights,
    )
    weak_object_positive_loss = _acceptable_positive_loss(
        outputs.get("weak_evidence_logits", outputs["object_logits"]),
        valid_mask=batch.object_supervision_mask,
        acceptable_sets=batch.object_acceptable_sets,
        acceptable_set_mask=batch.object_acceptable_set_mask,
        task_mask=weak_relation_task_mask,
        sample_weights=batch.sample_weights,
    )
    cardinality_loss = _object_cardinality_loss(
        outputs,
        batch,
        task_mask=exact_relation_task_mask,
    )
    role_cardinality_loss = _object_role_cardinality_loss(
        outputs,
        batch,
        task_mask=exact_relation_task_mask,
    )
    candidate_loss = _acceptable_single_choice_loss(
        outputs["candidate_logits"],
        valid_mask=batch.candidate_mask,
        acceptable_sets=batch.candidate_acceptable,
        task_mask=batch.candidate_task_mask,
        sample_weights=batch.sample_weights,
    )
    member_loss = _acceptable_multilabel_loss(
        outputs["member_logits"],
        valid_mask=batch.member_mask,
        acceptable_sets=batch.member_acceptable_sets,
        acceptable_set_mask=batch.member_acceptable_set_mask,
        task_mask=batch.member_task_mask & _complete_relation_plan_mask(batch),
        sample_weights=batch.sample_weights,
    )
    weak_member_positive_loss = _acceptable_positive_loss(
        outputs["member_logits"],
        valid_mask=batch.member_mask,
        acceptable_sets=batch.member_acceptable_sets,
        acceptable_set_mask=batch.member_acceptable_set_mask,
        task_mask=batch.member_task_mask & ~_complete_relation_plan_mask(batch),
        sample_weights=batch.sample_weights,
    )
    structured_member_loss = outputs["member_logits"].sum() * 0.0
    if "structured_member_loss_by_row" in outputs:
        per_row = outputs["structured_member_loss_by_row"]
        if per_row.shape != batch.member_task_mask.shape:
            raise ValueError("junction structured member loss shape differs")
        weights = batch.sample_weights * batch.member_task_mask.to(
            batch.sample_weights.dtype
        )
        structured_member_loss = (per_row * weights).sum() / weights.sum().clamp_min(
            1e-8
        )
    structured_relation_loss = outputs["object_logits"].sum() * 0.0
    if "structured_relation_loss_by_row" in outputs:
        per_row = outputs["structured_relation_loss_by_row"]
        if per_row.shape != batch.object_task_mask.shape:
            raise ValueError("junction structured relation loss shape differs")
        weights = batch.sample_weights * exact_relation_task_mask.to(
            batch.sample_weights.dtype
        )
        structured_relation_loss = (
            per_row * weights
        ).sum() / weights.sum().clamp_min(1e-8)
    topology_loss = _topology_plan_loss(outputs, batch)
    business_plan_loss = _business_plan_loss(
        outputs,
        batch,
        business_plan_catalog,
    )
    weighted.extend(
        (
            (1.50, surface_loss),
            (1.50, surface_boundary_loss),
            (2.00, surface_object_loss),
            (0.50, surface_object_cardinality_loss),
            (
                0.25
                if "virtual_surface_geometric_coverage_logits" in outputs
                else 3.00,
                virtual_surface_carrier_loss,
            ),
            (1.00, virtual_surface_carrier_cardinality_loss),
            (2.00, object_loss),
            (1.00, weak_object_positive_loss),
            (0.25, cardinality_loss),
            (1.00, role_cardinality_loss),
            (0.25, candidate_loss),
            (0.50, member_loss),
            (0.25, weak_member_positive_loss),
            (1.50, topology_loss),
            (2.00, business_plan_loss),
        )
    )
    if "structured_member_loss_by_row" in outputs:
        weighted.append((3.00, structured_member_loss))
    if "structured_relation_loss_by_row" in outputs:
        weighted.append((4.00, structured_relation_loss))
    if "structured_virtual_surface_carrier_loss_by_row" in outputs:
        weighted.append((4.00, structured_virtual_surface_carrier_loss))
    if "virtual_surface_geometric_coverage_logits" in outputs:
        weighted.append((6.00, virtual_surface_geometric_coverage_loss))
    metrics.update(
        {
            "surface_loss": float(surface_loss.detach().item()),
            "surface_boundary_loss": float(surface_boundary_loss.detach().item()),
            "surface_object_loss": float(surface_object_loss.detach().item()),
            "surface_object_cardinality_loss": float(
                surface_object_cardinality_loss.detach().item()
            ),
            "virtual_surface_carrier_loss": float(
                virtual_surface_carrier_loss.detach().item()
            ),
            "virtual_surface_carrier_cardinality_loss": float(
                virtual_surface_carrier_cardinality_loss.detach().item()
            ),
            "structured_virtual_surface_carrier_loss": float(
                structured_virtual_surface_carrier_loss.detach().item()
            ),
            "virtual_surface_geometric_coverage_loss": float(
                virtual_surface_geometric_coverage_loss.detach().item()
            ),
            "object_loss": float(object_loss.detach().item()),
            "weak_object_positive_loss": float(
                weak_object_positive_loss.detach().item()
            ),
            "object_cardinality_loss": float(cardinality_loss.detach().item()),
            "object_role_cardinality_loss": float(
                role_cardinality_loss.detach().item()
            ),
            "candidate_loss": float(candidate_loss.detach().item()),
            "member_loss": float(member_loss.detach().item()),
            "weak_member_positive_loss": float(
                weak_member_positive_loss.detach().item()
            ),
            "structured_member_loss": float(
                structured_member_loss.detach().item()
            ),
            "structured_relation_loss": float(
                structured_relation_loss.detach().item()
            ),
            "topology_plan_loss": float(topology_loss.detach().item()),
            "business_plan_loss": float(business_plan_loss.detach().item()),
        }
    )
    denominator = sum(weight for weight, _ in weighted)
    total = sum(weight * loss for weight, loss in weighted) / denominator
    metrics["total_loss"] = float(total.detach().item())
    return total, metrics


def train_junction_joint_canary(
    examples: Sequence[JunctionJointExample],
    *,
    seed: int,
    epochs: int = 24,
    max_batch_examples: int = 4,
    max_batch_tokens: int = 9_000,
    max_batch_objects: int = 1_000,
    learning_rate: float = 2e-4,
    weight_decay: float = 2e-4,
    device: torch.device | str = "cpu",
    config: JunctionJointConfig = JunctionJointConfig(),
    initial_state_dict: Mapping[str, torch.Tensor] | None = None,
    initial_state_strict: bool = True,
    business_plan_catalog: Sequence[BusinessPlanTemplate] | None = None,
    trainable_parameter_prefixes: Sequence[str] | None = None,
    balance_supervision_sources: bool = False,
    validation_score_fn: (
        Callable[[Mapping[str, Mapping[str, float]]], tuple[float, ...]] | None
    ) = None,
    epoch_callback: Callable[[Mapping[str, float]], None] | None = None,
) -> JunctionJointTrainingResult:
    if epochs < 3 or min(max_batch_examples, max_batch_tokens, max_batch_objects) < 1:
        raise ValueError("junction joint canary controls are invalid")
    cohort_audit = audit_joint_supervision_cohort(examples)
    if int(cohort_audit["test_count"]):
        raise AssertionError("junction test examples entered canary optimization")
    train_rows = [row for row in examples if row.split == "train"]
    validation_rows = [row for row in examples if row.split == "validation"]
    if not train_rows or not validation_rows:
        raise ValueError("junction joint explicit train/validation split is empty")

    random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)
    target_device = torch.device(device)
    model = JunctionJointNetwork(config).to(target_device)
    if config.business_plan_count != len(business_plan_catalog or ()):
        raise ValueError("junction business plan catalog and network size differ")
    if initial_state_dict is not None:
        model.load_state_dict(initial_state_dict, strict=initial_state_strict)
    if trainable_parameter_prefixes is not None:
        prefixes = tuple(str(value) for value in trainable_parameter_prefixes)
        if not prefixes or any(not value for value in prefixes):
            raise ValueError("junction trainable parameter prefixes are empty")
        for name, parameter in model.named_parameters():
            parameter.requires_grad_(name.startswith(prefixes))
    trainable_parameters = [
        parameter for parameter in model.parameters() if parameter.requires_grad
    ]
    if not trainable_parameters:
        raise ValueError("junction canary has no trainable parameters")
    optimizer = torch.optim.AdamW(
        trainable_parameters,
        lr=learning_rate,
        weight_decay=weight_decay,
    )
    class_weights = {
        task: values.to(target_device)
        for task, values in build_task_class_weights(train_rows).items()
    }
    history: list[dict[str, float]] = []
    best_state: dict[str, torch.Tensor] | None = None
    best_score: tuple[float, ...] | None = None
    best_epoch = -1
    started = time.perf_counter()
    amp_enabled = target_device.type == "cuda"
    for epoch in range(1, epochs + 1):
        model.train()
        forcing = teacher_forcing_ratio(epoch, epochs)
        total_loss = 0.0
        total_count = 0
        batches = _training_batches(
            train_rows,
            max_examples=max_batch_examples,
            max_tokens=max_batch_tokens,
            max_objects=max_batch_objects,
            seed=seed + epoch,
            balance_supervision_sources=balance_supervision_sources,
        )
        for rows in batches:
            batch = collate_junction_joint(rows).to(target_device)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast(
                device_type=target_device.type,
                dtype=torch.bfloat16,
                enabled=amp_enabled,
            ):
                outputs = model(
                    batch,
                    teacher_labels=batch.task_labels,
                    teacher_masks=batch.task_masks,
                    teacher_forcing_ratio=forcing,
                    teacher_member_sets=batch.member_acceptable_sets,
                    teacher_member_set_mask=batch.member_acceptable_set_mask,
                    teacher_member_task_mask=batch.member_task_mask,
                    teacher_virtual_surface_carrier_sets=(
                        batch.virtual_surface_carrier_acceptable_sets
                    ),
                    teacher_virtual_surface_carrier_set_mask=(
                        batch.virtual_surface_carrier_acceptable_set_mask
                    ),
                    teacher_virtual_surface_carrier_task_mask=(
                        batch.virtual_surface_carrier_task_mask
                    ),
                    teacher_relation_sets=batch.object_acceptable_sets,
                    teacher_relation_set_mask=batch.object_acceptable_set_mask,
                    teacher_relation_task_mask=_exact_relation_task_mask(batch),
                )
                loss, _ = compute_junction_joint_loss(
                    outputs,
                    batch,
                    class_weights=class_weights,
                    business_plan_catalog=business_plan_catalog,
                )
            loss.backward()
            nn.utils.clip_grad_norm_(trainable_parameters, 1.0)
            optimizer.step()
            total_loss += float(loss.detach().item()) * len(rows)
            total_count += len(rows)

        validation_by_source = {
            source: evaluate_junction_joint(
                model,
                [row for row in validation_rows if row.supervision_source == source],
                max_batch_examples=max_batch_examples,
                max_batch_tokens=max_batch_tokens,
                max_batch_objects=max_batch_objects,
                device=target_device,
                class_weights=class_weights,
                business_plan_catalog=business_plan_catalog,
            )
            for source in sorted({row.supervision_source for row in validation_rows})
        }
        primary_source = (
            "STRONG_GOLD"
            if "STRONG_GOLD" in validation_by_source
            else next(iter(validation_by_source))
        )
        validation = validation_by_source[primary_source]
        row = {
            "epoch": float(epoch),
            "teacher_forcing_ratio": forcing,
            "train_loss": total_loss / max(1, total_count),
            "train_batch_count": float(len(batches)),
            "train_example_count": float(total_count),
            **validation,
        }
        for source, source_metrics in validation_by_source.items():
            prefix = source.lower()
            row.update(
                {
                    f"{prefix}_{name}": value
                    for name, value in source_metrics.items()
                }
            )
        history.append(row)
        if epoch_callback is not None:
            epoch_callback(row)
        score = (validation_score_fn or _joint_validation_score)(
            validation_by_source
        )
        if not score:
            raise ValueError("junction validation score is empty")
        if best_score is None or score > best_score:
            best_score = score
            best_epoch = epoch
            best_state = copy.deepcopy(model.state_dict())
    if best_state is None:
        raise RuntimeError("junction joint canary produced no checkpoint")
    model.load_state_dict(best_state)
    return JunctionJointTrainingResult(
        model=model,
        best_epoch=best_epoch,
        history=tuple(history),
        wall_seconds=time.perf_counter() - started,
        cohort_audit=cohort_audit,
    )


def audit_joint_supervision_cohort(
    examples: Sequence[JunctionJointExample],
) -> Mapping[str, object]:
    if not examples:
        raise ValueError("junction supervision cohort is empty")
    allowed_sources = {"STRONG_GOLD", "T10_WEAK"}
    allowed_splits = {"train", "validation", "test"}
    source_split_counts: dict[str, dict[str, int]] = {}
    effective_weights: dict[str, dict[str, float]] = {}
    group_splits: dict[str, str] = {}
    strong_group_weights: dict[str, float] = {}
    task_supervision_counts: dict[str, dict[str, int]] = {}
    for row in examples:
        if row.supervision_source not in allowed_sources:
            raise ValueError(
                f"unknown junction supervision source: {row.supervision_source}"
            )
        if row.split not in allowed_splits:
            raise ValueError(f"unknown junction cohort split: {row.split}")
        if row.sample_weight <= 0.0:
            raise ValueError("junction sample weight must be positive")
        if row.supervision_source == "T10_WEAK":
            if abs(row.sample_weight - 0.7) > 1e-6:
                raise ValueError("T10 weak junction supervision weight must be 0.7")
        elif row.sample_weight > 1.0 + 1e-6:
            raise ValueError("strong Gold junction sample weight cannot exceed 1.0")

        previous_split = group_splits.setdefault(row.supervision_group, row.split)
        if previous_split != row.split:
            raise ValueError("junction supervision group crosses frozen splits")
        if row.supervision_source == "STRONG_GOLD":
            strong_group_weights[row.supervision_group] = (
                strong_group_weights.get(row.supervision_group, 0.0)
                + row.sample_weight
            )
        source_split_counts.setdefault(row.supervision_source, {}).setdefault(
            row.split, 0
        )
        source_split_counts[row.supervision_source][row.split] += 1
        effective_weights.setdefault(row.supervision_source, {}).setdefault(
            row.split, 0.0
        )
        effective_weights[row.supervision_source][row.split] += row.sample_weight
        for task, enabled in row.task_masks.items():
            if enabled:
                task_supervision_counts.setdefault(
                    row.supervision_source, {}
                ).setdefault(task, 0)
                task_supervision_counts[row.supervision_source][task] += 1

    invalid_gold_groups = {
        group: weight
        for group, weight in strong_group_weights.items()
        if abs(weight - 1.0) > 1e-6
    }
    if invalid_gold_groups:
        raise ValueError(
            "strong Gold effective Case weight must equal 1.0: "
            f"{sorted(invalid_gold_groups.items())[:3]}"
        )
    return {
        "schema_version": "p05-target-a-junction-joint-cohort-audit-v1",
        "example_count": len(examples),
        "test_count": sum(row.split == "test" for row in examples),
        "source_split_counts": source_split_counts,
        "effective_weights": effective_weights,
        "task_supervision_counts": task_supervision_counts,
        "strong_group_count": len(strong_group_weights),
        "group_split_leakage_count": 0,
        "inference_feature_source_field_count": 0,
        "status": "JOINT_SUPERVISION_COHORT_GO",
    }


def _joint_validation_score(
    validation_by_source: Mapping[str, Mapping[str, float]],
) -> tuple[float, ...]:
    strong = validation_by_source.get("STRONG_GOLD")
    weak = validation_by_source.get("T10_WEAK")
    primary = strong or weak
    if primary is None:
        raise ValueError("junction validation source metrics are empty")
    weak_values = weak or primary
    return (
        weak_values["surface_object_set_exact"],
        weak_values["surface_mode_accuracy"],
        primary["virtual_junction_exact"],
        primary["surface_grid_mean_iou"],
        primary["junctionization_action_accuracy"],
        primary["raw_object_set_exact"],
        primary["topology_plan_exact_at_2m"],
        primary["complete_junction_exact_proxy"],
        min(
            primary["business_state_chain_exact"],
            weak_values["business_state_chain_exact"],
        ),
        min(
            primary["raw_object_set_exact"],
            weak_values["raw_object_partial_full_coverage"],
        ),
        primary["raw_object_set_exact"],
        weak_values["raw_object_partial_full_coverage"],
        weak_values["raw_object_partial_recall"],
        primary["business_state_chain_exact"],
        weak_values["business_state_chain_exact"],
        -primary["validation_loss"],
    )


@torch.no_grad()
def evaluate_junction_joint(
    model: JunctionJointNetwork,
    examples: Sequence[JunctionJointExample],
    *,
    max_batch_examples: int,
    max_batch_tokens: int,
    max_batch_objects: int,
    device: torch.device | str,
    class_weights: Mapping[str, torch.Tensor] | None = None,
    business_plan_catalog: Sequence[BusinessPlanTemplate] | None = None,
) -> dict[str, float]:
    model.eval()
    target_device = torch.device(device)
    task_correct = {task: 0.0 for task in TASK_CLASSES}
    task_total = {task: 0.0 for task in TASK_CLASSES}
    chain_correct = chain_total = 0.0
    object_correct = object_total = 0.0
    object_partial_recall_sum = object_partial_full = 0.0
    weak_evidence_recall_at_12_sum = 0.0
    weak_evidence_full_at_12 = weak_evidence_total = 0.0
    structured_relation_feasible = structured_relation_total = 0.0
    surface_object_correct = surface_object_total = 0.0
    virtual_surface_carrier_correct = virtual_surface_carrier_total = 0.0
    virtual_surface_carrier_recall_sum = 0.0
    virtual_surface_carrier_grid_coverage_sum = 0.0
    virtual_surface_carrier_grid_coverage_90 = 0.0
    virtual_surface_carrier_grid_coverage_95 = 0.0
    surface_iou_sum = surface_total = surface_exact = 0.0
    topology_exact = topology_total = 0.0
    complete_exact = complete_total = 0.0
    virtual_complete_exact = virtual_complete_total = 0.0
    loss_sum = row_count = 0.0
    business_plan_abstain = 0.0
    batches = build_cost_batches(
        examples,
        max_examples=max_batch_examples,
        max_tokens=max_batch_tokens,
        max_objects=max_batch_objects,
        seed=0,
        shuffle=False,
    )
    for rows in batches:
        batch = collate_junction_joint(rows).to(target_device)
        outputs = model(
            batch,
            teacher_forcing_ratio=0.0,
            teacher_member_sets=batch.member_acceptable_sets,
            teacher_member_set_mask=batch.member_acceptable_set_mask,
            teacher_member_task_mask=batch.member_task_mask,
            teacher_virtual_surface_carrier_sets=(
                batch.virtual_surface_carrier_acceptable_sets
            ),
            teacher_virtual_surface_carrier_set_mask=(
                batch.virtual_surface_carrier_acceptable_set_mask
            ),
            teacher_virtual_surface_carrier_task_mask=(
                batch.virtual_surface_carrier_task_mask
            ),
            teacher_relation_sets=batch.object_acceptable_sets,
            teacher_relation_set_mask=batch.object_acceptable_set_mask,
            teacher_relation_task_mask=_exact_relation_task_mask(batch),
        )
        loss, _ = compute_junction_joint_loss(
            outputs,
            batch,
            class_weights=class_weights,
            business_plan_catalog=business_plan_catalog,
        )
        loss_sum += float(loss.item()) * len(rows)
        row_count += len(rows)
        if "business_plan_logits" in outputs:
            if not business_plan_catalog:
                raise ValueError("junction business plan output has no catalog")
            task_predictions, requires_abstain = decode_business_plan_tasks(
                outputs["business_plan_logits"],
                business_plan_catalog,
            )
            business_plan_abstain += float(requires_abstain.sum())
        else:
            task_predictions = {
                task: outputs[f"{task}_logits"].argmax(dim=-1)
                for task in TASK_CLASSES
            }
        chain = torch.ones(len(rows), dtype=torch.bool, device=target_device)
        chain_mask = torch.zeros(len(rows), dtype=torch.bool, device=target_device)
        for task in TASK_CLASSES:
            mask = batch.task_masks[task]
            correct = task_predictions[task].eq(batch.task_labels[task])
            weights = batch.sample_weights
            task_correct[task] += float((correct & mask).to(weights.dtype).mul(weights).sum())
            task_total[task] += float(mask.to(weights.dtype).mul(weights).sum())
            chain &= ~mask | correct
            chain_mask |= mask
        chain_correct += float((chain & chain_mask).sum())
        chain_total += float(chain_mask.sum())

        object_prediction = _decode_object_sets(outputs, batch)
        object_match = _matches_any_set(
            object_prediction,
            batch.object_acceptable_sets,
            batch.object_acceptable_set_mask,
            valid_mask=batch.object_supervision_mask,
        )
        object_match |= ~batch.object_task_mask
        object_correct += float((object_match & batch.object_task_mask).sum())
        object_total += float(batch.object_task_mask.sum())
        for index in range(len(rows)):
            if not bool(batch.object_task_mask[index]):
                continue
            options = batch.object_acceptable_sets[index][
                batch.object_acceptable_set_mask[index]
            ]
            if options.numel() == 0:
                continue
            recalls = (
                options & object_prediction[index].unsqueeze(0)
            ).sum(dim=1) / options.sum(dim=1).clamp_min(1)
            best_recall = float(recalls.max())
            object_partial_recall_sum += best_recall
            object_partial_full += float(best_recall >= 1.0)
        if "weak_evidence_logits" in outputs:
            evidence_logits = outputs["weak_evidence_logits"]
            minimum = torch.finfo(evidence_logits.dtype).min
            for index in range(len(rows)):
                if not bool(batch.object_task_mask[index]):
                    continue
                options = batch.object_acceptable_sets[index][
                    batch.object_acceptable_set_mask[index]
                ]
                valid = batch.object_supervision_mask[index]
                if options.numel() == 0 or not bool(valid.any()):
                    continue
                limit = min(12, int(valid.sum()))
                selected = torch.zeros_like(valid)
                ranked = evidence_logits[index].masked_fill(~valid, minimum)
                selected[ranked.topk(limit).indices] = True
                recalls = (
                    options & selected.unsqueeze(0)
                ).sum(dim=1) / options.sum(dim=1).clamp_min(1)
                best_recall = float(recalls.max())
                weak_evidence_recall_at_12_sum += best_recall
                weak_evidence_full_at_12 += float(best_recall >= 1.0)
                weak_evidence_total += 1.0
        if "structured_relation_feasible" in outputs:
            structured_relation_feasible += float(
                (
                    outputs["structured_relation_feasible"]
                    & batch.object_task_mask
                ).sum()
            )
            structured_relation_total += float(batch.object_task_mask.sum())

        surface_object_prediction = _decode_surface_object_sets(outputs, batch)
        surface_object_match = _matches_any_set(
            surface_object_prediction,
            batch.surface_object_acceptable_sets,
            batch.surface_object_acceptable_set_mask,
            valid_mask=(
                batch.geometry_object_mask
                & batch.geometry_object_roles.eq(
                    GEOMETRY_ROLE_INDEX["RCSD_INTERSECTION"]
                )
            ),
        )
        surface_object_match |= ~batch.surface_object_task_mask
        surface_object_correct += float(
            (surface_object_match & batch.surface_object_task_mask).sum()
        )
        surface_object_total += float(batch.surface_object_task_mask.sum())

        virtual_surface_carrier_prediction = _decode_virtual_surface_carrier_sets(
            outputs,
            batch,
        )
        virtual_surface_carrier_match = _matches_any_set(
            virtual_surface_carrier_prediction,
            batch.virtual_surface_carrier_acceptable_sets,
            batch.virtual_surface_carrier_acceptable_set_mask,
            valid_mask=virtual_surface_carrier_candidate_mask(batch),
        )
        virtual_surface_carrier_correct += float(
            (
                virtual_surface_carrier_match
                & batch.virtual_surface_carrier_task_mask
            ).sum()
        )
        virtual_surface_carrier_total += float(
            batch.virtual_surface_carrier_task_mask.sum()
        )
        for index in range(len(rows)):
            if not bool(batch.virtual_surface_carrier_task_mask[index]):
                continue
            options = batch.virtual_surface_carrier_acceptable_sets[index][
                batch.virtual_surface_carrier_acceptable_set_mask[index]
            ]
            recalls = (
                options & virtual_surface_carrier_prediction[index].unsqueeze(0)
            ).sum(dim=1) / options.sum(dim=1).clamp_min(1)
            virtual_surface_carrier_recall_sum += float(recalls.max())
        carrier_grid = virtual_surface_carrier_object_grid(batch).bool()
        predicted_grid = (
            carrier_grid
            & virtual_surface_carrier_prediction.unsqueeze(-1).unsqueeze(-1)
        ).any(dim=1)
        target_boundary = _surface_boundary_grid(batch.surface_targets).bool()
        for index in range(len(rows)):
            if not bool(batch.virtual_surface_carrier_task_mask[index]):
                continue
            boundary_count = target_boundary[index].sum().clamp_min(1)
            coverage = float(
                (predicted_grid[index] & target_boundary[index]).sum()
                / boundary_count
            )
            virtual_surface_carrier_grid_coverage_sum += coverage
            virtual_surface_carrier_grid_coverage_90 += float(coverage >= 0.90)
            virtual_surface_carrier_grid_coverage_95 += float(coverage >= 0.95)

        surface_prediction = outputs["surface_logits"].sigmoid().ge(0.5)
        surface_match = torch.ones(len(rows), dtype=torch.bool, device=target_device)
        for index in range(len(rows)):
            if not bool(batch.surface_task_mask[index]):
                continue
            target = batch.surface_targets[index].bool()
            prediction = surface_prediction[index]
            union = (prediction | target).sum().clamp_min(1)
            iou = float((prediction & target).sum() / union)
            surface_iou_sum += iou
            surface_total += 1.0
            surface_match[index] = iou >= 0.90
            surface_exact += float(iou >= 0.90)

        topology_match = _topology_plan_exact(
            outputs,
            batch,
            object_prediction=object_prediction,
            tolerance_m=2.0,
        )
        topology_exact += float(
            (topology_match & batch.topology_geometry_task_mask).sum()
        )
        topology_total += float(batch.topology_geometry_task_mask.sum())

        supervised = batch.complete_junction_task_mask
        complete = (
            chain
            & object_match
            & surface_object_match
            & surface_match
            & topology_match
        )
        complete_exact += float((complete & supervised).sum())
        complete_total += float(supervised.sum())
        virtual_index = TASK_CLASSES["surface_mode"].index("VIRTUAL_SURFACE")
        virtual_supervised = (
            supervised
            & batch.task_masks["surface_mode"]
            & batch.task_labels["surface_mode"].eq(virtual_index)
        )
        virtual_complete_exact += float((complete & virtual_supervised).sum())
        virtual_complete_total += float(virtual_supervised.sum())

    result = {
        "validation_loss": loss_sum / max(1.0, row_count),
        "business_state_chain_exact": chain_correct / max(1.0, chain_total),
        "raw_object_set_exact": object_correct / max(1.0, object_total),
        "raw_object_partial_recall": (
            object_partial_recall_sum / max(1.0, object_total)
        ),
        "raw_object_partial_full_coverage": (
            object_partial_full / max(1.0, object_total)
        ),
        "weak_evidence_partial_recall_at_12": (
            weak_evidence_recall_at_12_sum / max(1.0, weak_evidence_total)
        ),
        "weak_evidence_partial_full_coverage_at_12": (
            weak_evidence_full_at_12 / max(1.0, weak_evidence_total)
        ),
        "structured_relation_set_exact": (
            object_correct / max(1.0, object_total)
            if structured_relation_total
            else 0.0
        ),
        "structured_relation_feasible_rate": (
            structured_relation_feasible / max(1.0, structured_relation_total)
        ),
        "surface_object_set_exact": (
            surface_object_correct / max(1.0, surface_object_total)
        ),
        "virtual_surface_carrier_set_exact": (
            virtual_surface_carrier_correct
            / max(1.0, virtual_surface_carrier_total)
        ),
        "virtual_surface_carrier_set_recall": (
            virtual_surface_carrier_recall_sum
            / max(1.0, virtual_surface_carrier_total)
        ),
        "virtual_surface_carrier_grid_coverage_mean": (
            virtual_surface_carrier_grid_coverage_sum
            / max(1.0, virtual_surface_carrier_total)
        ),
        "virtual_surface_carrier_grid_coverage_at_0_90": (
            virtual_surface_carrier_grid_coverage_90
            / max(1.0, virtual_surface_carrier_total)
        ),
        "virtual_surface_carrier_grid_coverage_at_0_95": (
            virtual_surface_carrier_grid_coverage_95
            / max(1.0, virtual_surface_carrier_total)
        ),
        "surface_grid_mean_iou": surface_iou_sum / max(1.0, surface_total),
        "surface_grid_exact_at_0_90": surface_exact / max(1.0, surface_total),
        "topology_plan_exact_at_2m": topology_exact / max(1.0, topology_total),
        "complete_junction_exact_proxy": complete_exact / max(1.0, complete_total),
        "virtual_junction_exact": (
            virtual_complete_exact / max(1.0, virtual_complete_total)
        ),
        "business_plan_requires_abstain_rate": (
            business_plan_abstain / max(1.0, row_count)
        ),
    }
    for task in TASK_CLASSES:
        result[f"{task}_accuracy"] = task_correct[task] / max(1.0, task_total[task])
    return result


def build_cost_batches(
    examples: Sequence[JunctionJointExample],
    *,
    max_examples: int,
    max_tokens: int,
    max_objects: int,
    seed: int,
    shuffle: bool,
) -> tuple[tuple[JunctionJointExample, ...], ...]:
    if min(max_examples, max_tokens, max_objects) < 1:
        raise ValueError("junction batch budgets must be positive")
    ordered = sorted(
        examples,
        key=lambda row: (row.geometry_tokens.shape[0], len(row.geometry_objects)),
    )
    batches: list[tuple[JunctionJointExample, ...]] = []
    current: list[JunctionJointExample] = []
    token_total = object_total = 0
    for row in ordered:
        tokens = row.geometry_tokens.shape[0]
        objects = len(row.geometry_objects)
        exceeds = current and (
            len(current) >= max_examples
            or token_total + tokens > max_tokens
            or object_total + objects > max_objects
        )
        if exceeds:
            batches.append(tuple(current))
            current = []
            token_total = object_total = 0
        current.append(row)
        token_total += tokens
        object_total += objects
    if current:
        batches.append(tuple(current))
    if shuffle:
        random.Random(seed).shuffle(batches)
    return tuple(batches)


def _training_batches(
    examples: Sequence[JunctionJointExample],
    *,
    max_examples: int,
    max_tokens: int,
    max_objects: int,
    seed: int,
    balance_supervision_sources: bool,
) -> tuple[tuple[JunctionJointExample, ...], ...]:
    if not balance_supervision_sources:
        return build_cost_batches(
            examples,
            max_examples=max_examples,
            max_tokens=max_tokens,
            max_objects=max_objects,
            seed=seed,
            shuffle=True,
        )
    sources = tuple(sorted({row.supervision_source for row in examples}))
    if len(sources) <= 1:
        return build_cost_batches(
            examples,
            max_examples=max_examples,
            max_tokens=max_tokens,
            max_objects=max_objects,
            seed=seed,
            shuffle=True,
        )
    by_source = {
        source: build_cost_batches(
            tuple(row for row in examples if row.supervision_source == source),
            max_examples=max_examples,
            max_tokens=max_tokens,
            max_objects=max_objects,
            seed=seed + rank * 10_003,
            shuffle=True,
        )
        for rank, source in enumerate(sources)
    }
    batch_count = min(len(rows) for rows in by_source.values())
    if batch_count < 1:
        raise ValueError("junction source-balanced training batch is empty")
    return tuple(
        by_source[source][batch_index]
        for batch_index in range(batch_count)
        for source in sources
    )


def build_task_class_weights(
    examples: Sequence[JunctionJointExample],
) -> Mapping[str, torch.Tensor]:
    result: dict[str, torch.Tensor] = {}
    for task, classes in TASK_CLASSES.items():
        counts = torch.ones(len(classes), dtype=torch.float64)
        for row in examples:
            if row.task_masks[task]:
                counts[row.task_labels[task]] += row.sample_weight
        values = counts.sum().sqrt() / counts.sqrt()
        result[task] = (values / values.mean()).to(torch.float32)
    return result


def teacher_forcing_ratio(epoch: int, epochs: int) -> float:
    if epochs < 2 or epoch < 1 or epoch > epochs:
        raise ValueError("junction teacher forcing schedule is invalid")
    progress = (epoch - 1) / (epochs - 1)
    return 0.90 * max(0.0, 1.0 - progress)


def _weighted_masked_cross_entropy(
    logits: torch.Tensor,
    labels: torch.Tensor,
    mask: torch.Tensor,
    sample_weights: torch.Tensor,
    class_weights: torch.Tensor | None,
) -> torch.Tensor:
    valid = mask & labels.ge(0)
    if not bool(valid.any()):
        return logits.sum() * 0.0
    losses = nn.functional.cross_entropy(
        logits[valid],
        labels[valid],
        weight=class_weights,
        reduction="none",
    )
    weights = sample_weights[valid]
    return (losses * weights).sum() / weights.sum().clamp_min(1e-8)


def _surface_loss(logits: torch.Tensor, batch: JunctionJointBatch) -> torch.Tensor:
    losses: list[torch.Tensor] = []
    weights: list[torch.Tensor] = []
    for index in range(logits.shape[0]):
        if not bool(batch.surface_task_mask[index]):
            continue
        target = batch.surface_targets[index]
        positives = target.sum().clamp_min(1.0)
        negatives = target.numel() - positives
        positive_weight = (negatives / positives).clamp(max=20.0)
        bce = nn.functional.binary_cross_entropy_with_logits(
            logits[index],
            target,
            pos_weight=positive_weight,
        )
        probability = logits[index].sigmoid()
        dice = 1.0 - (
            2.0 * (probability * target).sum() + 1.0
        ) / (probability.sum() + target.sum() + 1.0)
        losses.append(bce + dice)
        weights.append(batch.sample_weights[index])
    return _weighted_list(losses, weights, logits)


def _business_plan_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
    catalog: Sequence[BusinessPlanTemplate] | None,
) -> torch.Tensor:
    if "business_plan_logits" not in outputs:
        return outputs["surface_logits"].sum() * 0.0
    if not catalog:
        raise ValueError("junction business plan output has no training catalog")
    targets = business_plan_targets(batch, catalog)
    valid = targets.ge(0)
    if not bool(valid.any()):
        return outputs["business_plan_logits"].sum() * 0.0
    losses = nn.functional.cross_entropy(
        outputs["business_plan_logits"][valid],
        targets[valid],
        reduction="none",
    )
    weights = batch.sample_weights[valid]
    return (losses * weights).sum() / weights.sum().clamp_min(1e-8)


def _surface_boundary_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
) -> torch.Tensor:
    losses: list[torch.Tensor] = []
    weights: list[torch.Tensor] = []
    reference = outputs["surface_row_left_logits"]
    for index in range(reference.shape[0]):
        if not bool(batch.surface_task_mask[index]):
            continue
        target = batch.surface_targets[index].bool()
        row_present = target.any(dim=-1)
        column_present = target.any(dim=-2)
        if not bool(row_present.any()) or not bool(column_present.any()):
            continue
        row_left = target.to(torch.float32).argmax(dim=-1)
        row_right = target.shape[-1] - 1 - torch.flip(
            target, dims=(-1,)
        ).to(torch.float32).argmax(dim=-1)
        column_top = target.to(torch.float32).argmax(dim=-2)
        column_bottom = target.shape[-2] - 1 - torch.flip(
            target, dims=(-2,)
        ).to(torch.float32).argmax(dim=-2)
        row_positive_weight = (
            (~row_present).sum() / row_present.sum().clamp_min(1)
        ).clamp(1.0, 20.0)
        column_positive_weight = (
            (~column_present).sum() / column_present.sum().clamp_min(1)
        ).clamp(1.0, 20.0)
        parts = (
            nn.functional.binary_cross_entropy_with_logits(
                outputs["surface_row_presence_logits"][index],
                row_present.to(reference.dtype),
                pos_weight=row_positive_weight.to(reference.dtype),
            ),
            nn.functional.binary_cross_entropy_with_logits(
                outputs["surface_column_presence_logits"][index],
                column_present.to(reference.dtype),
                pos_weight=column_positive_weight.to(reference.dtype),
            ),
            nn.functional.cross_entropy(
                outputs["surface_row_left_logits"][index][row_present],
                row_left[row_present],
            ),
            nn.functional.cross_entropy(
                outputs["surface_row_right_logits"][index][row_present],
                row_right[row_present],
            ),
            nn.functional.cross_entropy(
                outputs["surface_column_top_logits"][index]
                .transpose(0, 1)[column_present],
                column_top[column_present],
            ),
            nn.functional.cross_entropy(
                outputs["surface_column_bottom_logits"][index]
                .transpose(0, 1)[column_present],
                column_bottom[column_present],
            ),
        )
        losses.append(torch.stack(parts).mean())
        weights.append(batch.sample_weights[index])
    return _weighted_list(losses, weights, reference)


def _acceptable_single_choice_loss(
    logits: torch.Tensor,
    *,
    valid_mask: torch.Tensor,
    acceptable_sets: torch.Tensor,
    task_mask: torch.Tensor,
    sample_weights: torch.Tensor,
) -> torch.Tensor:
    losses: list[torch.Tensor] = []
    weights: list[torch.Tensor] = []
    minimum = torch.finfo(logits.dtype).min
    for index in range(logits.shape[0]):
        if not bool(task_mask[index]):
            continue
        allowed = acceptable_sets[index].any(dim=0) & valid_mask[index]
        if not bool(allowed.any()):
            continue
        log_probability = logits[index].masked_fill(~valid_mask[index], minimum).log_softmax(0)
        losses.append(-torch.logsumexp(log_probability[allowed], dim=0))
        weights.append(sample_weights[index])
    return _weighted_list(losses, weights, logits)


def _acceptable_multilabel_loss(
    logits: torch.Tensor,
    *,
    valid_mask: torch.Tensor,
    acceptable_sets: torch.Tensor,
    acceptable_set_mask: torch.Tensor,
    task_mask: torch.Tensor,
    sample_weights: torch.Tensor,
) -> torch.Tensor:
    losses: list[torch.Tensor] = []
    weights: list[torch.Tensor] = []
    for index in range(logits.shape[0]):
        if not bool(task_mask[index]):
            continue
        valid = valid_mask[index]
        options = acceptable_sets[index][acceptable_set_mask[index]]
        if not bool(valid.any()) or options.numel() == 0:
            continue
        option_losses = []
        for target in options:
            positives = target[valid].sum().clamp_min(1)
            positive_weight = ((valid.sum() - positives) / positives).clamp(1.0, 20.0)
            option_losses.append(
                nn.functional.binary_cross_entropy_with_logits(
                    logits[index][valid],
                    target[valid].to(logits.dtype),
                    pos_weight=positive_weight,
                )
            )
        losses.append(torch.stack(option_losses).min())
        weights.append(sample_weights[index])
    return _weighted_list(losses, weights, logits)


def _acceptable_positive_loss(
    logits: torch.Tensor,
    *,
    valid_mask: torch.Tensor,
    acceptable_sets: torch.Tensor,
    acceptable_set_mask: torch.Tensor,
    task_mask: torch.Tensor,
    sample_weights: torch.Tensor,
) -> torch.Tensor:
    """Train known weak positives without treating unlisted objects as negatives."""
    losses: list[torch.Tensor] = []
    weights: list[torch.Tensor] = []
    for index in range(logits.shape[0]):
        if not bool(task_mask[index]):
            continue
        valid = valid_mask[index]
        options = acceptable_sets[index][acceptable_set_mask[index]]
        if not bool(valid.any()) or options.numel() == 0:
            continue
        option_losses = []
        for target in options:
            positive = target & valid
            if bool(positive.any()):
                option_losses.append(
                    nn.functional.softplus(-logits[index][positive]).mean()
                )
        if option_losses:
            losses.append(torch.stack(option_losses).min())
            weights.append(sample_weights[index])
    return _weighted_list(losses, weights, logits)


def _complete_relation_plan_mask(batch: JunctionJointBatch) -> torch.Tensor:
    return batch.complete_junction_task_mask


def _exact_relation_task_mask(batch: JunctionJointBatch) -> torch.Tensor:
    return batch.object_task_mask & _complete_relation_plan_mask(batch)


def _object_cardinality_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
    *,
    task_mask: torch.Tensor | None = None,
) -> torch.Tensor:
    labels = torch.zeros(outputs["object_cardinality_logits"].shape[0], dtype=torch.long, device=batch.sample_weights.device)
    mask = (batch.object_task_mask if task_mask is None else task_mask).clone()
    for index in range(labels.shape[0]):
        if not torch.equal(
            batch.object_supervision_mask[index],
            batch.selectable_object_mask[index],
        ):
            mask[index] = False
            continue
        options = batch.object_acceptable_sets[index][batch.object_acceptable_set_mask[index]]
        if options.numel() == 0:
            mask[index] = False
            continue
        cardinalities = options.sum(dim=1).unique()
        if cardinalities.numel() != 1:
            mask[index] = False
            continue
        labels[index] = cardinalities[0].clamp_max(
            outputs["object_cardinality_logits"].shape[1] - 1
        )
    return _weighted_masked_cross_entropy(
        outputs["object_cardinality_logits"],
        labels,
        mask,
        batch.sample_weights,
        None,
    )


def _surface_object_cardinality_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
) -> torch.Tensor:
    logits = outputs["surface_object_cardinality_logits"]
    labels = torch.zeros(
        logits.shape[0],
        dtype=torch.long,
        device=batch.sample_weights.device,
    )
    mask = batch.surface_object_task_mask.clone()
    for index in range(labels.shape[0]):
        options = batch.surface_object_acceptable_sets[index][
            batch.surface_object_acceptable_set_mask[index]
        ]
        if options.numel() == 0:
            mask[index] = False
            continue
        cardinalities = options.sum(dim=1).unique()
        if cardinalities.numel() != 1:
            mask[index] = False
            continue
        labels[index] = cardinalities[0].clamp_max(logits.shape[1] - 1)
    return _weighted_masked_cross_entropy(
        logits,
        labels,
        mask,
        batch.sample_weights,
        None,
    )


def _virtual_surface_carrier_cardinality_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
) -> torch.Tensor:
    logits = outputs["virtual_surface_carrier_cardinality_logits"]
    labels = torch.zeros(
        logits.shape[0],
        dtype=torch.long,
        device=batch.sample_weights.device,
    )
    mask = batch.virtual_surface_carrier_task_mask.clone()
    for index in range(labels.shape[0]):
        options = batch.virtual_surface_carrier_acceptable_sets[index][
            batch.virtual_surface_carrier_acceptable_set_mask[index]
        ]
        if options.numel() == 0:
            mask[index] = False
            continue
        cardinalities = options.sum(dim=1).unique()
        if cardinalities.numel() != 1:
            mask[index] = False
            continue
        labels[index] = cardinalities[0].clamp_max(logits.shape[1] - 1)
    return _weighted_masked_cross_entropy(
        logits,
        labels,
        mask,
        batch.sample_weights,
        None,
    )


def _virtual_surface_geometric_coverage_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
) -> torch.Tensor:
    logits = outputs["virtual_surface_geometric_coverage_logits"]
    valid_mask = virtual_surface_carrier_candidate_mask(batch)
    object_grid = virtual_surface_carrier_object_grid(batch).to(logits.dtype)
    boundary = _surface_boundary_grid(batch.surface_targets).to(logits.dtype)
    losses: list[torch.Tensor] = []
    weights: list[torch.Tensor] = []
    for index in range(logits.shape[0]):
        if not bool(batch.virtual_surface_carrier_task_mask[index]):
            continue
        options = batch.virtual_surface_carrier_acceptable_sets[index][
            batch.virtual_surface_carrier_acceptable_set_mask[index]
        ]
        if options.numel() == 0 or not bool(valid_mask[index].any()):
            continue
        cardinalities = options.sum(dim=1).unique()
        if cardinalities.numel() != 1 or not bool(boundary[index].any()):
            continue
        probability = logits[index].sigmoid() * valid_mask[index].to(logits.dtype)
        covered = 1.0 - torch.prod(
            1.0 - probability.unsqueeze(-1).unsqueeze(-1) * object_grid[index],
            dim=0,
        )
        missed_boundary = (
            (1.0 - covered) * boundary[index]
        ).sum() / boundary[index].sum().clamp_min(1.0)
        target_count = cardinalities[0].to(logits.dtype)
        count_penalty = nn.functional.smooth_l1_loss(
            probability.sum(),
            target_count,
            beta=1.0,
        ) / 8.0
        active_probability = probability[valid_mask[index]]
        discreteness = (
            active_probability * (1.0 - active_probability)
        ).mean()
        losses.append(missed_boundary + 0.25 * count_penalty + 0.05 * discreteness)
        weights.append(batch.sample_weights[index])
    return _weighted_list(losses, weights, logits)


def _surface_boundary_grid(surface_targets: torch.Tensor) -> torch.Tensor:
    target = surface_targets.unsqueeze(1).float()
    dilated = nn.functional.max_pool2d(target, 3, stride=1, padding=1)
    eroded = 1.0 - nn.functional.max_pool2d(
        1.0 - target,
        3,
        stride=1,
        padding=1,
    )
    return (dilated - eroded).clamp(0.0, 1.0).squeeze(1)


def _object_role_cardinality_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
    *,
    task_mask: torch.Tensor | None = None,
) -> torch.Tensor:
    logits = outputs["object_role_cardinality_logits"]
    losses: list[torch.Tensor] = []
    weights: list[torch.Tensor] = []
    active_mask = batch.object_task_mask if task_mask is None else task_mask
    for index in range(logits.shape[0]):
        if not bool(active_mask[index]):
            continue
        options = batch.object_acceptable_sets[index][
            batch.object_acceptable_set_mask[index]
        ]
        if options.numel() == 0:
            continue
        for role_rank, role_index in enumerate(OBJECT_ROLE_INDICES):
            if not bool(batch.object_role_task_mask[index, role_rank]):
                continue
            role_mask = batch.geometry_object_roles[index].eq(role_index)
            cardinalities = (options & role_mask.unsqueeze(0)).sum(dim=1).unique()
            if cardinalities.numel() != 1:
                continue
            target = cardinalities[0].clamp_max(logits.shape[-1] - 1).reshape(1)
            losses.append(
                nn.functional.cross_entropy(
                    logits[index, role_rank].unsqueeze(0),
                    target,
                )
            )
            weights.append(batch.sample_weights[index])
    return _weighted_list(losses, weights, logits)


def _topology_plan_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
) -> torch.Tensor:
    losses: list[torch.Tensor] = []
    weights: list[torch.Tensor] = []
    road_role = GEOMETRY_ROLE_INDEX["RCSD_ROAD"]
    node_role = GEOMETRY_ROLE_INDEX["RCSD_NODE"]
    for index in range(outputs["break_fractions"].shape[0]):
        if not bool(batch.topology_geometry_task_mask[index]):
            continue
        selected = batch.object_acceptable_sets[index][
            batch.object_acceptable_set_mask[index]
        ][0]
        selected_roads = selected & batch.geometry_object_roles[index].eq(road_role)
        valid_break_slots = selected_roads.unsqueeze(-1).expand_as(
            batch.break_target_mask[index]
        )
        target_breaks = batch.break_target_mask[index]
        parts: list[torch.Tensor] = []
        if bool(valid_break_slots.any()):
            positive_count = target_breaks[valid_break_slots].sum().clamp_min(1)
            negative_count = valid_break_slots.sum() - positive_count
            positive_weight = (negative_count / positive_count).clamp(1.0, 20.0)
            parts.append(
                nn.functional.binary_cross_entropy_with_logits(
                    outputs["break_presence_logits"][index][valid_break_slots],
                    target_breaks[valid_break_slots].to(outputs["break_fractions"].dtype),
                    pos_weight=positive_weight,
                )
            )
        if bool(target_breaks.any()):
            lengths = batch.break_road_length_m[index].unsqueeze(-1).expand_as(
                batch.break_fraction_targets[index]
            )
            predicted_m = outputs["break_fractions"][index] * lengths
            target_m = batch.break_fraction_targets[index] * lengths
            parts.append(
                nn.functional.smooth_l1_loss(
                    predicted_m[target_breaks],
                    target_m[target_breaks],
                    beta=2.0,
                )
                / 10.0
            )
        if bool(batch.main_object_task_mask[index]):
            valid_nodes = selected & batch.geometry_object_roles[index].eq(node_role)
            parts.append(
                _masked_choice_loss(
                    outputs["object_main_logits"][index],
                    valid_nodes,
                    batch.main_object_target[index],
                )
            )
        if bool(batch.break_main_task_mask[index]):
            parts.append(
                _masked_choice_loss(
                    outputs["break_main_logits"][index].reshape(-1),
                    target_breaks.reshape(-1),
                    batch.break_main_mask[index].reshape(-1),
                )
            )
        if not parts:
            continue
        losses.append(torch.stack(parts).sum())
        weights.append(batch.sample_weights[index])
    return _weighted_list(losses, weights, outputs["break_fractions"])


def _weighted_list(
    losses: Sequence[torch.Tensor],
    weights: Sequence[torch.Tensor],
    reference: torch.Tensor,
) -> torch.Tensor:
    if not losses:
        return reference.sum() * 0.0
    loss_tensor = torch.stack(tuple(losses))
    weight_tensor = torch.stack(tuple(weights)).to(loss_tensor.dtype)
    return (loss_tensor * weight_tensor).sum() / weight_tensor.sum().clamp_min(1e-8)


def _decode_object_sets(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
) -> torch.Tensor:
    structured_relation = outputs.get("structured_relation_prediction")
    if structured_relation is not None:
        if structured_relation.shape != batch.selectable_object_mask.shape:
            raise ValueError("junction structured relation prediction shape differs")
        return structured_relation & batch.selectable_object_mask
    structured = outputs.get("structured_member_prediction")
    if structured is not None:
        if structured.shape != batch.member_mask.shape:
            raise ValueError("junction structured member prediction shape differs")
        safe_index = batch.geometry_object_member_index.clamp_min(0)
        selected = structured.gather(1, safe_index)
        return selected & (
            batch.selectable_object_mask
            & batch.geometry_object_member_index.ge(0)
        )
    result = torch.zeros_like(batch.selectable_object_mask)
    cardinalities = outputs["object_role_cardinality_logits"].argmax(dim=-1)
    minimum = torch.finfo(outputs["object_logits"].dtype).min
    for index in range(outputs["object_logits"].shape[0]):
        for role_rank, role_index in enumerate(OBJECT_ROLE_INDICES):
            valid = batch.selectable_object_mask[index] & batch.geometry_object_roles[
                index
            ].eq(role_index)
            count = min(int(cardinalities[index, role_rank]), int(valid.sum()))
            if count <= 0:
                continue
            logits = outputs["object_logits"][index].masked_fill(~valid, minimum)
            selected = logits.topk(count).indices
            result[index, selected] = True
    return result


def _decode_surface_object_sets(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
) -> torch.Tensor:
    result = torch.zeros_like(batch.geometry_object_mask)
    cardinalities = outputs["surface_object_cardinality_logits"].argmax(dim=-1)
    minimum = torch.finfo(outputs["surface_object_logits"].dtype).min
    surface_role = GEOMETRY_ROLE_INDEX["RCSD_INTERSECTION"]
    for index in range(outputs["surface_object_logits"].shape[0]):
        valid = batch.geometry_object_mask[index] & batch.geometry_object_roles[
            index
        ].eq(surface_role)
        count = min(int(cardinalities[index]), int(valid.sum()))
        if count <= 0:
            continue
        logits = outputs["surface_object_logits"][index].masked_fill(~valid, minimum)
        selected = logits.topk(count).indices
        result[index, selected] = True
    return result


def _decode_virtual_surface_carrier_sets(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
) -> torch.Tensor:
    structured = outputs.get("structured_virtual_surface_carrier_prediction")
    if structured is not None:
        if structured.shape != batch.geometry_object_mask.shape:
            raise ValueError("structured virtual carrier prediction shape differs")
        return structured & virtual_surface_carrier_candidate_mask(batch)
    result = torch.zeros_like(batch.geometry_object_mask)
    valid_mask = virtual_surface_carrier_candidate_mask(batch)
    cardinalities = outputs[
        "virtual_surface_carrier_cardinality_logits"
    ].argmax(dim=-1)
    minimum = torch.finfo(outputs["virtual_surface_carrier_logits"].dtype).min
    for index in range(outputs["virtual_surface_carrier_logits"].shape[0]):
        valid = valid_mask[index]
        count = min(int(cardinalities[index]), int(valid.sum()))
        if count <= 0:
            continue
        logits = outputs["virtual_surface_carrier_logits"][index].masked_fill(
            ~valid,
            minimum,
        )
        selected = logits.topk(count).indices
        result[index, selected] = True
    return result


def _matches_any_set(
    prediction: torch.Tensor,
    acceptable_sets: torch.Tensor,
    acceptable_set_mask: torch.Tensor,
    *,
    valid_mask: torch.Tensor | None = None,
) -> torch.Tensor:
    equality = prediction.unsqueeze(1).eq(acceptable_sets)
    if valid_mask is not None:
        equality = equality | ~valid_mask.unsqueeze(1)
    matches = equality.all(dim=-1)
    return (matches & acceptable_set_mask).any(dim=1)


def _topology_plan_exact(
    outputs: Mapping[str, torch.Tensor],
    batch: JunctionJointBatch,
    *,
    object_prediction: torch.Tensor,
    tolerance_m: float,
) -> torch.Tensor:
    result = torch.ones(
        outputs["break_fractions"].shape[0],
        dtype=torch.bool,
        device=outputs["break_fractions"].device,
    )
    road_role = GEOMETRY_ROLE_INDEX["RCSD_ROAD"]
    node_role = GEOMETRY_ROLE_INDEX["RCSD_NODE"]
    for index in range(result.shape[0]):
        if not bool(batch.topology_geometry_task_mask[index]):
            continue
        predicted_roads = object_prediction[index] & batch.geometry_object_roles[index].eq(
            road_role
        )
        valid_slots = predicted_roads.unsqueeze(-1).expand_as(
            batch.break_target_mask[index]
        )
        predicted_breaks = outputs["break_presence_logits"][index].sigmoid().ge(0.5)
        predicted_breaks &= valid_slots
        target_breaks = batch.break_target_mask[index]
        if not torch.equal(predicted_breaks, target_breaks):
            result[index] = False
            continue
        if bool(target_breaks.any()):
            lengths = batch.break_road_length_m[index].unsqueeze(-1).expand_as(
                batch.break_fraction_targets[index]
            )
            error_m = (
                outputs["break_fractions"][index]
                - batch.break_fraction_targets[index]
            ).abs() * lengths
            if bool((error_m[target_breaks] > tolerance_m).any()):
                result[index] = False
                continue
        if bool(batch.main_object_task_mask[index]):
            predicted_nodes = object_prediction[index] & batch.geometry_object_roles[index].eq(
                node_role
            )
            if not bool(predicted_nodes.any()):
                result[index] = False
                continue
            logits = outputs["object_main_logits"][index].masked_fill(
                ~predicted_nodes,
                torch.finfo(outputs["object_main_logits"].dtype).min,
            )
            result[index] = bool(batch.main_object_target[index, logits.argmax()])
        elif bool(batch.break_main_task_mask[index]):
            logits = outputs["break_main_logits"][index].masked_fill(
                ~predicted_breaks,
                torch.finfo(outputs["break_main_logits"].dtype).min,
            )
            result[index] = bool(batch.break_main_mask[index].reshape(-1)[logits.reshape(-1).argmax()])
    return result


def _masked_choice_loss(
    logits: torch.Tensor,
    valid_mask: torch.Tensor,
    target_mask: torch.Tensor,
) -> torch.Tensor:
    if not bool(valid_mask.any()) or not bool((target_mask & valid_mask).any()):
        return logits.sum() * 0.0
    minimum = torch.finfo(logits.dtype).min
    log_probability = logits.masked_fill(~valid_mask, minimum).log_softmax(dim=0)
    return -torch.logsumexp(log_probability[target_mask & valid_mask], dim=0)


__all__ = [
    "JunctionJointTrainingResult",
    "build_cost_batches",
    "build_task_class_weights",
    "compute_junction_joint_loss",
    "evaluate_junction_joint",
    "teacher_forcing_ratio",
    "train_junction_joint_canary",
]
