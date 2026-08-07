from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_data import (
    TASK_CLASSES,
    JunctionJointBatch,
    JunctionJointExample,
)


BUSINESS_PLAN_TASKS = tuple(TASK_CLASSES)
WILDCARD = -1


@dataclass(frozen=True)
class BusinessPlanTemplate:
    values: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.values) != len(BUSINESS_PLAN_TASKS):
            raise ValueError("junction business plan task count differs")
        for task, value in zip(BUSINESS_PLAN_TASKS, self.values):
            if value != WILDCARD and not 0 <= value < len(TASK_CLASSES[task]):
                raise ValueError(f"junction business plan {task} value is invalid")

    @property
    def complete(self) -> bool:
        return all(value != WILDCARD for value in self.values)

    def to_dict(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "values": {
                task: (
                    "*" if value == WILDCARD else TASK_CLASSES[task][value]
                )
                for task, value in zip(BUSINESS_PLAN_TASKS, self.values)
            },
        }


def build_business_plan_catalog(
    examples: Sequence[JunctionJointExample],
) -> tuple[BusinessPlanTemplate, ...]:
    signatures = {
        tuple(
            int(row.task_labels[task]) if row.task_masks[task] else WILDCARD
            for task in BUSINESS_PLAN_TASKS
        )
        for row in examples
    }
    if not signatures:
        raise ValueError("junction business plan catalog source is empty")
    return tuple(
        BusinessPlanTemplate(values)
        for values in sorted(
            signatures,
            key=lambda values: (
                -sum(value != WILDCARD for value in values),
                values,
            ),
        )
    )


def business_plan_targets(
    batch: JunctionJointBatch,
    catalog: Sequence[BusinessPlanTemplate],
) -> torch.Tensor:
    index = {template.values: rank for rank, template in enumerate(catalog)}
    targets = torch.full(
        (len(batch.sample_ids),),
        -1,
        dtype=torch.long,
        device=batch.sample_weights.device,
    )
    for row_index in range(len(batch.sample_ids)):
        signature = tuple(
            int(batch.task_labels[task][row_index])
            if bool(batch.task_masks[task][row_index])
            else WILDCARD
            for task in BUSINESS_PLAN_TASKS
        )
        if signature in index:
            targets[row_index] = index[signature]
    return targets


def decode_business_plan_tasks(
    plan_logits: torch.Tensor,
    catalog: Sequence[BusinessPlanTemplate],
) -> tuple[Mapping[str, torch.Tensor], torch.Tensor]:
    if plan_logits.ndim != 2 or plan_logits.shape[1] != len(catalog):
        raise ValueError("junction business plan logit shape differs")
    values = torch.tensor(
        [template.values for template in catalog],
        dtype=torch.long,
        device=plan_logits.device,
    )
    selected = values[plan_logits.argmax(dim=-1)]
    predictions = {
        task: selected[:, index]
        for index, task in enumerate(BUSINESS_PLAN_TASKS)
    }
    requires_abstain = selected.eq(WILDCARD).any(dim=-1)
    return predictions, requires_abstain


def catalog_manifest(
    catalog: Sequence[BusinessPlanTemplate],
) -> dict[str, object]:
    return {
        "schema_version": "p05-target-a-junction-business-plan-catalog-v1",
        "task_order": list(BUSINESS_PLAN_TASKS),
        "template_count": len(catalog),
        "complete_template_count": sum(template.complete for template in catalog),
        "partial_template_count": sum(not template.complete for template in catalog),
        "templates": [template.to_dict() for template in catalog],
    }


__all__ = [
    "BUSINESS_PLAN_TASKS",
    "WILDCARD",
    "BusinessPlanTemplate",
    "build_business_plan_catalog",
    "business_plan_targets",
    "catalog_manifest",
    "decode_business_plan_tasks",
]
