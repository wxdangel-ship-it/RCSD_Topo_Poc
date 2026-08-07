from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_recall_data import (
    EndToEndRecallExample,
)


END_TO_END_ROAD_MEMBER_SUMMARY_DIM = 4
END_TO_END_ROAD_MEMBER_FEATURE_DIM = (
    TARGET_A_FEATURE_DIM + END_TO_END_ROAD_MEMBER_SUMMARY_DIM
)
_CARDINALITY_NORMALIZER = 12.0


@dataclass(frozen=True)
class EndToEndRoadSetBatch:
    road_ids: tuple[tuple[str, ...], ...]
    member_values: torch.Tensor
    member_mask: torch.Tensor
    plan_membership: torch.Tensor
    plan_mask: torch.Tensor

    def __post_init__(self) -> None:
        if self.member_values.ndim != 4:
            raise ValueError("Road member values must be four-dimensional")
        if (
            self.member_values.shape[-1]
            != END_TO_END_ROAD_MEMBER_FEATURE_DIM
        ):
            raise ValueError("Road member feature dimension differs")
        if self.member_mask.shape != self.member_values.shape[:3]:
            raise ValueError("Road member mask shape differs")
        if self.member_mask.dtype != torch.bool:
            raise ValueError("Road member mask must be boolean")
        if self.plan_membership.ndim != 4:
            raise ValueError("Road plan membership must be four-dimensional")
        if (
            self.plan_membership.shape[0]
            != self.member_values.shape[0]
            or self.plan_membership.shape[1] != 1
            or self.plan_membership.shape[3]
            != self.member_values.shape[2]
        ):
            raise ValueError("Road plan membership shape differs")
        if self.plan_membership.dtype != torch.bool:
            raise ValueError("Road plan membership must be boolean")
        if self.plan_mask.shape != self.plan_membership.shape[:3]:
            raise ValueError("Road plan mask shape differs")
        if self.plan_mask.dtype != torch.bool:
            raise ValueError("Road plan mask must be boolean")
        if len(self.road_ids) != self.member_values.shape[0]:
            raise ValueError("Road ids and batch size differ")


def collate_end_to_end_road_set_batch(
    examples: Sequence[EndToEndRecallExample],
) -> EndToEndRoadSetBatch:
    """Build truth-free Road-member evidence for complete-set ranking."""
    if not examples:
        raise ValueError("Road-set collate requires at least one example")
    advances = []
    for example in examples:
        if example.advance_right is None:
            raise ValueError("Road-set example lacks AdvanceRight")
        advances.append(example.advance_right)
    road_ids = tuple(
        tuple(
            sorted(
                {
                    road_id
                    for plan in advance.plans
                    for road_id in plan.road_ids
                }
            )
        )
        for advance in advances
    )
    max_road_count = max(max(map(len, road_ids)), 1)
    max_plan_count = max(len(advance.plans) for advance in advances)
    member_values = torch.zeros(
        (
            len(examples),
            1,
            max_road_count,
            END_TO_END_ROAD_MEMBER_FEATURE_DIM,
        ),
        dtype=torch.float32,
    )
    member_mask = torch.zeros(
        (len(examples), 1, max_road_count),
        dtype=torch.bool,
    )
    plan_membership = torch.zeros(
        (len(examples), 1, max_plan_count, max_road_count),
        dtype=torch.bool,
    )
    plan_mask = torch.zeros(
        (len(examples), 1, max_plan_count),
        dtype=torch.bool,
    )
    for batch_index, (advance, ids) in enumerate(
        zip(advances, road_ids, strict=True)
    ):
        id_to_index = {
            road_id: index for index, road_id in enumerate(ids)
        }
        member_mask[batch_index, 0, : len(ids)] = True
        plan_mask[batch_index, 0, : len(advance.plans)] = True
        for plan_index, plan in enumerate(advance.plans):
            for road_id in plan.road_ids:
                plan_membership[
                    batch_index,
                    0,
                    plan_index,
                    id_to_index[road_id],
                ] = True
        for road_index, road_id in enumerate(ids):
            member_values[batch_index, 0, road_index] = torch.tensor(
                _road_member_feature(
                    advance.plans,
                    road_id=road_id,
                    candidate_road_count=len(ids),
                ),
                dtype=torch.float32,
            )
    return EndToEndRoadSetBatch(
        road_ids=road_ids,
        member_values=member_values,
        member_mask=member_mask,
        plan_membership=plan_membership,
        plan_mask=plan_mask,
    )


def _road_member_feature(
    plans: Sequence[object],
    *,
    road_id: str,
    candidate_road_count: int,
) -> tuple[float, ...]:
    containing = [
        plan
        for plan in plans
        if road_id in getattr(plan, "road_ids")
    ]
    if not containing:
        raise ValueError("Road member is absent from every candidate plan")
    minimum_cardinality = min(
        len(getattr(plan, "road_ids")) for plan in containing
    )
    local = [
        plan
        for plan in containing
        if len(getattr(plan, "road_ids")) == minimum_cardinality
    ]
    pooled = tuple(
        sum(
            float(getattr(plan, "feature_values")[feature_index])
            for plan in local
        )
        / len(local)
        for feature_index in range(TARGET_A_FEATURE_DIM)
    )
    total_plan_count = max(len(plans), 1)
    summary = (
        min(candidate_road_count, 12) / _CARDINALITY_NORMALIZER,
        min(minimum_cardinality, 12) / _CARDINALITY_NORMALIZER,
        len(containing) / total_plan_count,
        math.log1p(len(containing)) / math.log1p(total_plan_count),
    )
    return (*pooled, *summary)


__all__ = [
    "END_TO_END_ROAD_MEMBER_FEATURE_DIM",
    "EndToEndRoadSetBatch",
    "collate_end_to_end_road_set_batch",
]
