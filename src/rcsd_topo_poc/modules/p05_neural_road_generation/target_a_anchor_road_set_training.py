from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import torch
import torch.nn.functional as functional

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    TargetATrainingTargets,
)


@dataclass(frozen=True)
class AnchorRoadSetLossConfig:
    member_weight: float = 1.0
    cardinality_weight: float = 1.5
    ranking_weight: float = 0.5
    count_consistency_weight: float = 0.25
    cardinality_mode: str = "categorical"
    ordinal_monotonic_weight: float = 0.25

    def validate(self) -> None:
        if min(
            self.member_weight,
            self.cardinality_weight,
            self.ranking_weight,
            self.count_consistency_weight,
            self.ordinal_monotonic_weight,
        ) < 0:
            raise ValueError(
                "anchor Road-set loss weights must not be negative"
            )
        if (
            self.member_weight
            + self.cardinality_weight
            + self.ranking_weight
            + self.count_consistency_weight
            <= 0
        ):
            raise ValueError("anchor Road-set loss cannot be empty")
        if self.cardinality_mode not in {"categorical", "ordinal"}:
            raise ValueError(
                "anchor Road-set cardinality_mode must be categorical or ordinal"
            )


@dataclass(frozen=True)
class AnchorRoadSetLoss:
    total: torch.Tensor
    member: torch.Tensor
    cardinality: torch.Tensor
    ranking: torch.Tensor
    count_consistency: torch.Tensor
    supervised_count: int


def anchor_road_set_loss(
    outputs: Mapping[str, torch.Tensor],
    targets: TargetATrainingTargets,
    *,
    config: AnchorRoadSetLossConfig = AnchorRoadSetLossConfig(),
) -> AnchorRoadSetLoss:
    """Multi-solution exact-set loss over Road-only acceptable sets."""
    config.validate()
    member_logits = outputs["road_member_logits"]
    cardinality_logits = outputs["road_cardinality_logits"]
    road_mask = outputs["road_member_mask"]
    acceptable_sets = targets.anchor_member_acceptable_sets
    acceptable_mask = targets.anchor_member_acceptable_set_mask
    task_mask = targets.anchor_member_task_mask
    if (
        acceptable_sets is None
        or acceptable_mask is None
        or task_mask is None
    ):
        raise ValueError("anchor Road-set labels are absent")
    if (
        member_logits.shape != road_mask.shape
        or cardinality_logits.shape != road_mask.shape
        or acceptable_sets.shape[:-2] != member_logits.shape[:-1]
        or acceptable_sets.shape[-1] != member_logits.shape[-1]
        or acceptable_mask.shape != acceptable_sets.shape[:-1]
        or task_mask.shape != member_logits.shape[:-1]
    ):
        raise ValueError("anchor Road-set label/output shapes differ")

    total_rows = []
    member_rows = []
    cardinality_rows = []
    ranking_rows = []
    count_rows = []
    row_weights = []
    for batch_index in range(member_logits.shape[0]):
        for anchor_index in range(member_logits.shape[1]):
            if not bool(task_mask[batch_index, anchor_index]):
                continue
            mask = road_mask[batch_index, anchor_index]
            if not bool(mask.any()):
                continue
            option_losses = []
            option_members = []
            option_cardinalities = []
            option_rankings = []
            option_counts = []
            logits = member_logits[batch_index, anchor_index]
            cardinalities = cardinality_logits[
                batch_index,
                anchor_index,
            ]
            for option_index in range(acceptable_sets.shape[-2]):
                if not bool(
                    acceptable_mask[
                        batch_index,
                        anchor_index,
                        option_index,
                    ]
                ):
                    continue
                option = acceptable_sets[
                    batch_index,
                    anchor_index,
                    option_index,
                ]
                if not bool(option.any()) or bool((option & ~mask).any()):
                    continue
                positive = logits[option]
                negative = logits[mask & ~option]
                positive_loss = functional.softplus(-positive).mean()
                negative_loss = (
                    functional.softplus(negative).mean()
                    if negative.numel()
                    else positive_loss.new_zeros(())
                )
                member_loss = (
                    0.5 * (positive_loss + negative_loss)
                    if negative.numel()
                    else positive_loss
                )
                ranking_loss = (
                    functional.softplus(
                        negative.unsqueeze(0) - positive.unsqueeze(1)
                    ).mean()
                    if negative.numel()
                    else positive_loss.new_zeros(())
                )
                truth_count = int(option.sum().item())
                if config.cardinality_mode == "categorical":
                    cardinality_loss = functional.cross_entropy(
                        cardinalities.unsqueeze(0),
                        torch.tensor(
                            [truth_count - 1],
                            dtype=torch.long,
                            device=cardinalities.device,
                        ),
                    )
                else:
                    cardinality_rank = torch.arange(
                        cardinalities.shape[-1],
                        device=cardinalities.device,
                    )
                    cardinality_mask = cardinality_rank < int(mask.sum().item())
                    ordinal_logits = cardinalities[cardinality_mask]
                    ordinal_target = (
                        cardinality_rank[cardinality_mask] < truth_count
                    )
                    positive_ordinal = functional.softplus(
                        -ordinal_logits[ordinal_target]
                    ).mean()
                    negative_ordinal = (
                        functional.softplus(
                            ordinal_logits[~ordinal_target]
                        ).mean()
                        if bool((~ordinal_target).any())
                        else positive_ordinal.new_zeros(())
                    )
                    ordinal_loss = (
                        0.5 * (positive_ordinal + negative_ordinal)
                        if bool((~ordinal_target).any())
                        else positive_ordinal
                    )
                    monotonic_loss = (
                        functional.relu(
                            ordinal_logits[1:] - ordinal_logits[:-1]
                        ).mean()
                        if ordinal_logits.numel() > 1
                        else ordinal_loss.new_zeros(())
                    )
                    cardinality_loss = (
                        ordinal_loss
                        + config.ordinal_monotonic_weight * monotonic_loss
                    )
                expected_count = torch.sigmoid(logits[mask]).sum()
                count_loss = functional.smooth_l1_loss(
                    expected_count,
                    expected_count.new_tensor(float(truth_count)),
                )
                total = (
                    config.member_weight * member_loss
                    + config.cardinality_weight * cardinality_loss
                    + config.ranking_weight * ranking_loss
                    + config.count_consistency_weight * count_loss
                )
                option_losses.append(total)
                option_members.append(member_loss)
                option_cardinalities.append(cardinality_loss)
                option_rankings.append(ranking_loss)
                option_counts.append(count_loss)
            if not option_losses:
                continue
            stacked = torch.stack(option_losses)
            selected = int(stacked.detach().argmin().item())
            total_rows.append(stacked[selected])
            member_rows.append(torch.stack(option_members)[selected])
            cardinality_rows.append(
                torch.stack(option_cardinalities)[selected]
            )
            ranking_rows.append(torch.stack(option_rankings)[selected])
            count_rows.append(torch.stack(option_counts)[selected])
            row_weights.append(targets.sample_weights[batch_index])
    if not total_rows:
        raise ValueError("anchor Road-set batch lacks Road supervision")
    weights = torch.stack(row_weights)
    weights = weights / weights.sum().clamp_min(1.0e-8)
    return AnchorRoadSetLoss(
        total=(torch.stack(total_rows) * weights).sum(),
        member=(torch.stack(member_rows) * weights).sum(),
        cardinality=(
            torch.stack(cardinality_rows) * weights
        ).sum(),
        ranking=(torch.stack(ranking_rows) * weights).sum(),
        count_consistency=(torch.stack(count_rows) * weights).sum(),
        supervised_count=len(total_rows),
    )


__all__ = [
    "AnchorRoadSetLoss",
    "AnchorRoadSetLossConfig",
    "anchor_road_set_loss",
]
