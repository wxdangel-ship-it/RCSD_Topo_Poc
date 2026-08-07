from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_structural_decision import (
    ANCHOR_OBJECT_TYPES,
    ANCHOR_RELATION_STATES,
    TargetAAnchorStructuralJointOutput,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetABatchTensors,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_training import (
    acceptable_member_set_nll,
    acceptable_set_nll,
    anchor_member_type_cardinality_targets,
)


@dataclass(frozen=True)
class TargetAAnchorStructuralLossConfig:
    relation_weight: float = 1.0
    object_type_weight: float = 1.0
    cardinality_weight: float = 0.35
    ordinal_cardinality_weight: float = 0.35
    member_weight: float = 1.0

    def validate(self) -> None:
        values = (
            self.relation_weight,
            self.object_type_weight,
            self.cardinality_weight,
            self.ordinal_cardinality_weight,
            self.member_weight,
        )
        if any(value < 0.0 for value in values):
            raise ValueError("anchor structural loss weights must be nonnegative")
        if not any(value > 0.0 for value in values):
            raise ValueError("anchor structural loss requires a positive weight")


@dataclass(frozen=True)
class TargetAAnchorStructuralTargets:
    """Training-only labels kept physically outside the inference batch."""

    relation_target: torch.Tensor
    relation_task_mask: torch.Tensor
    member_acceptable_sets: torch.Tensor
    member_acceptable_set_mask: torch.Tensor
    member_task_mask: torch.Tensor
    sample_weights: torch.Tensor

    def validate(
        self,
        *,
        batch: TargetABatchTensors,
        max_cardinality: int,
    ) -> None:
        member_mask = batch.anchor_member_mask
        member_is_road = batch.anchor_member_is_road
        if member_mask is None or member_is_road is None:
            raise ValueError("anchor structural targets require atomic members")
        if member_mask.ndim != 3:
            raise ValueError("anchor member mask must be [B, A, M]")
        group_shape = member_mask.shape[:2]
        if (
            self.relation_target.shape != group_shape
            or self.relation_target.dtype is not torch.long
            or self.relation_task_mask.shape != group_shape
            or self.relation_task_mask.dtype is not torch.bool
        ):
            raise ValueError("anchor relation target shape or dtype differs")
        if bool(
            (
                self.relation_task_mask
                & (
                    (self.relation_target < 0)
                    | (
                        self.relation_target
                        >= len(ANCHOR_RELATION_STATES)
                    )
                )
            ).any()
        ):
            raise ValueError("anchor relation target is outside the vocabulary")
        if (
            self.member_acceptable_sets.ndim != 4
            or self.member_acceptable_sets.shape[:2] != group_shape
            or self.member_acceptable_sets.shape[-1]
            != member_mask.shape[-1]
            or self.member_acceptable_sets.dtype is not torch.bool
        ):
            raise ValueError("anchor acceptable member set shape differs")
        option_shape = self.member_acceptable_sets.shape[:-1]
        if (
            self.member_acceptable_set_mask.shape != option_shape
            or self.member_acceptable_set_mask.dtype is not torch.bool
            or self.member_task_mask.shape != group_shape
            or self.member_task_mask.dtype is not torch.bool
        ):
            raise ValueError("anchor member supervision mask shape differs")
        if bool(
            (
                self.member_task_mask
                & ~self.member_acceptable_set_mask.any(dim=-1)
            ).any()
        ):
            raise ValueError("anchor member task has no acceptable option")
        if self.sample_weights.shape != group_shape:
            raise ValueError("anchor structural sample weight shape differs")
        if not bool(torch.isfinite(self.sample_weights).all()) or bool(
            (self.sample_weights < 0.0).any()
        ):
            raise ValueError(
                "anchor structural sample weights must be finite and nonnegative"
            )
        active_task_mask = (
            self.relation_task_mask | self.member_task_mask
        )
        if bool(
            (
                active_task_mask
                & self.sample_weights.le(0.0)
            ).any()
        ):
            raise ValueError(
                "active anchor structural task requires positive weight"
            )
        counts = self.member_acceptable_sets.sum(dim=-1)
        if bool(
            (
                self.member_acceptable_set_mask
                & ((counts < 1) | (counts > max_cardinality))
            ).any()
        ):
            raise ValueError("anchor acceptable cardinality is invalid")

    def to(self, device: torch.device) -> "TargetAAnchorStructuralTargets":
        return TargetAAnchorStructuralTargets(
            **{
                name: value.to(device)
                for name, value in self.__dict__.items()
            }
        )


def compute_anchor_structural_loss(
    output: TargetAAnchorStructuralJointOutput,
    *,
    batch: TargetABatchTensors,
    targets: TargetAAnchorStructuralTargets,
    config: TargetAAnchorStructuralLossConfig,
) -> tuple[torch.Tensor, dict[str, float]]:
    config.validate()
    max_cardinality = output.cardinality_logits.shape[-1]
    targets.validate(
        batch=batch,
        max_cardinality=max_cardinality,
    )
    member_mask = batch.anchor_member_mask
    member_is_road = batch.anchor_member_is_road
    if member_mask is None or member_is_road is None:
        raise AssertionError("anchor structural member narrowing failed")
    group_shape = member_mask.shape[:2]
    if output.relation_logits.shape != (
        *group_shape,
        len(ANCHOR_RELATION_STATES),
    ):
        raise ValueError("anchor structural relation output shape differs")
    if output.object_type_logits.shape != (
        *group_shape,
        len(ANCHOR_OBJECT_TYPES),
    ):
        raise ValueError("anchor structural type output shape differs")
    if output.cardinality_logits.shape[:2] != group_shape:
        raise ValueError("anchor structural cardinality output shape differs")
    if output.ordinal_cardinality_logits.shape != (
        *group_shape,
        max_cardinality - 1,
    ):
        raise ValueError(
            "anchor structural ordinal cardinality output shape differs"
        )
    if output.member_logits.shape != member_mask.shape:
        raise ValueError("anchor structural member output shape differs")

    relation_raw = nn.functional.cross_entropy(
        output.relation_logits.reshape(
            -1,
            len(ANCHOR_RELATION_STATES),
        ),
        targets.relation_target.clamp_min(0).reshape(-1),
        reduction="none",
    ).reshape(group_shape)
    relation_loss = _weighted_masked_mean(
        relation_raw,
        targets.relation_task_mask,
        targets.sample_weights,
    )

    acceptable_types, acceptable_cardinalities_by_type = (
        anchor_member_type_cardinality_targets(
            targets.member_acceptable_sets,
            targets.member_acceptable_set_mask,
            member_is_road,
            cardinality_count=max_cardinality,
        )
    )
    valid_types = torch.stack(
        (
            (member_mask & ~member_is_road).any(dim=-1),
            (member_mask & member_is_road).any(dim=-1),
        ),
        dim=-1,
    )
    object_type_raw = acceptable_set_nll(
        output.object_type_logits,
        acceptable_types,
        valid_types,
    )
    object_type_loss = _weighted_masked_mean(
        object_type_raw,
        targets.member_task_mask,
        targets.sample_weights,
    )

    acceptable_cardinalities = acceptable_cardinalities_by_type.any(
        dim=-2
    )
    valid_cardinalities = (
        torch.arange(
            1,
            max_cardinality + 1,
            device=member_mask.device,
        )
        .view(1, 1, -1)
        .le(member_mask.sum(dim=-1, keepdim=True))
    )
    cardinality_raw = acceptable_set_nll(
        output.cardinality_logits,
        acceptable_cardinalities,
        valid_cardinalities,
    )
    cardinality_loss = _weighted_masked_mean(
        cardinality_raw,
        targets.member_task_mask,
        targets.sample_weights,
    )

    option_counts = targets.member_acceptable_sets.sum(dim=-1)
    thresholds = torch.arange(
        2,
        max_cardinality + 1,
        device=member_mask.device,
    ).view(1, 1, 1, -1)
    ordinal_targets = option_counts.unsqueeze(-1).ge(thresholds)
    ordinal_raw = nn.functional.binary_cross_entropy_with_logits(
        output.ordinal_cardinality_logits.unsqueeze(-2).expand_as(
            ordinal_targets
        ),
        ordinal_targets.to(output.ordinal_cardinality_logits.dtype),
        reduction="none",
    ).mean(dim=-1)
    ordinal_raw = ordinal_raw.masked_fill(
        ~targets.member_acceptable_set_mask,
        torch.finfo(ordinal_raw.dtype).max,
    ).amin(dim=-1)
    ordinal_loss = _weighted_masked_mean(
        ordinal_raw,
        targets.member_task_mask,
        targets.sample_weights,
    )

    member_raw = acceptable_member_set_nll(
        output.member_logits,
        member_mask,
        member_is_road,
        targets.member_acceptable_sets,
        targets.member_acceptable_set_mask,
    )
    member_loss = _weighted_masked_mean(
        member_raw,
        targets.member_task_mask,
        targets.sample_weights,
    )
    total = (
        config.relation_weight * relation_loss
        + config.object_type_weight * object_type_loss
        + config.cardinality_weight * cardinality_loss
        + config.ordinal_cardinality_weight * ordinal_loss
        + config.member_weight * member_loss
    )
    parts = {
        "relation_loss": float(relation_loss.detach().item()),
        "object_type_loss": float(object_type_loss.detach().item()),
        "cardinality_loss": float(cardinality_loss.detach().item()),
        "ordinal_cardinality_loss": float(ordinal_loss.detach().item()),
        "member_loss": float(member_loss.detach().item()),
        "total_loss": float(total.detach().item()),
    }
    return total, parts


def _weighted_masked_mean(
    values: torch.Tensor,
    mask: torch.Tensor,
    weights: torch.Tensor,
) -> torch.Tensor:
    if values.shape != mask.shape or values.shape != weights.shape:
        raise ValueError("anchor structural weighted mean shapes differ")
    effective = mask.to(values.dtype) * weights
    denominator = effective.sum()
    if float(denominator.detach().item()) <= 0.0:
        finite = torch.where(
            torch.isfinite(values),
            values,
            torch.zeros_like(values),
        )
        return finite.sum() * 0.0
    return (values * effective).sum() / denominator


__all__ = [
    "TargetAAnchorStructuralLossConfig",
    "TargetAAnchorStructuralTargets",
    "compute_anchor_structural_loss",
]
