from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_arms import (
    ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
    ORDINARY_PLAN_ARM_COUNT,
)


@dataclass(frozen=True)
class OrdinaryAccessConsistencyConfig:
    hidden_dim: int = 48
    feedforward_dim: int = 96
    upstream_context_dim: int = 0
    dropout: float = 0.1
    preserve_arm_order: bool = False
    geometry_prior_scale: float = 0.0
    residual_scale: float = 1.0
    bound_residual: bool = False

    def __post_init__(self) -> None:
        if min(self.hidden_dim, self.feedforward_dim) < 1:
            raise ValueError("ordinary access consistency dimensions are invalid")
        if self.upstream_context_dim < 0:
            raise ValueError("ordinary access upstream context dimension is invalid")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("ordinary access consistency dropout is invalid")
        if self.geometry_prior_scale < 0.0 or self.residual_scale < 0.0:
            raise ValueError("ordinary access score scales are invalid")


class TargetAOrdinaryAccessConsistencyHead(nn.Module):
    """Score whether a Road plan reaches both frozen Segment arms.

    The branch consumes only plan-arm evidence plus an optional detached
    upstream context.  It cannot change semantic anchor or carrier outputs;
    its score is available only to the downstream plan decoder.
    """

    def __init__(
        self,
        config: OrdinaryAccessConsistencyConfig | None = None,
    ) -> None:
        super().__init__()
        self.config = config or OrdinaryAccessConsistencyConfig()
        hidden_dim = self.config.hidden_dim
        self.arm_encoder = nn.Sequential(
            nn.Linear(ORDINARY_PLAN_ARM_BASE_FEATURE_DIM, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(self.config.dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
        )
        pair_multiplier = 7 if self.config.preserve_arm_order else 4
        pair_dim = (
            hidden_dim * pair_multiplier + self.config.upstream_context_dim
        )
        self.pair_encoder = nn.Sequential(
            nn.Linear(pair_dim, self.config.feedforward_dim),
            nn.GELU(),
            nn.LayerNorm(self.config.feedforward_dim),
            nn.Dropout(self.config.dropout),
            nn.Linear(self.config.feedforward_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.score_head = nn.Linear(hidden_dim, 1)

    def forward(
        self,
        arm_features: torch.Tensor,
        arm_mask: torch.Tensor,
        *,
        candidate_mask: torch.Tensor | None = None,
        upstream_context: torch.Tensor | None = None,
    ) -> torch.Tensor:
        if (
            arm_features.ndim != 4
            or arm_features.shape[-2] != ORDINARY_PLAN_ARM_COUNT
            or arm_features.shape[-1] != ORDINARY_PLAN_ARM_BASE_FEATURE_DIM
            or arm_mask.shape != arm_features.shape[:-1]
            or arm_mask.dtype is not torch.bool
        ):
            raise ValueError("ordinary access arm evidence shape differs")
        expected_candidate_shape = arm_features.shape[:2]
        if candidate_mask is None:
            candidate_mask = arm_mask.any(dim=-1)
        if (
            candidate_mask.shape != expected_candidate_shape
            or candidate_mask.dtype is not torch.bool
        ):
            raise ValueError("ordinary access candidate mask shape differs")
        if bool((candidate_mask & ~arm_mask.all(dim=-1)).any()):
            raise ValueError("ordinary access candidate lacks both arm rows")

        encoded = self.arm_encoder(arm_features.detach())
        weights = arm_mask.unsqueeze(-1).to(encoded.dtype)
        masked_encoded = encoded * weights
        mean = masked_encoded.sum(dim=-2) / weights.sum(
            dim=-2
        ).clamp_min(1.0)
        minimum = encoded.masked_fill(
            ~arm_mask.unsqueeze(-1),
            torch.finfo(encoded.dtype).max,
        ).amin(dim=-2)
        maximum = encoded.masked_fill(
            ~arm_mask.unsqueeze(-1),
            torch.finfo(encoded.dtype).min,
        ).amax(dim=-2)
        has_arm = arm_mask.any(dim=-1).unsqueeze(-1)
        minimum = torch.where(has_arm, minimum, torch.zeros_like(minimum))
        maximum = torch.where(has_arm, maximum, torch.zeros_like(maximum))
        signed_difference = (
            masked_encoded[:, :, 0] - masked_encoded[:, :, 1]
        )
        difference = torch.abs(signed_difference)
        pair_parts = [mean, minimum, maximum, difference]
        if self.config.preserve_arm_order:
            pair_parts.extend(
                (
                    masked_encoded[:, :, 0],
                    masked_encoded[:, :, 1],
                    signed_difference,
                )
            )
        if self.config.upstream_context_dim:
            if (
                upstream_context is None
                or upstream_context.shape
                != (*expected_candidate_shape, self.config.upstream_context_dim)
            ):
                raise ValueError("ordinary access upstream context shape differs")
            pair_parts.append(upstream_context.detach())
        elif upstream_context is not None:
            raise ValueError("ordinary access upstream context is not configured")
        residual = self.score_head(
            self.pair_encoder(torch.cat(pair_parts, dim=-1))
        ).squeeze(-1)
        if self.config.bound_residual:
            residual = torch.tanh(residual)
        logits = (
            self.config.geometry_prior_scale
            * ordinary_access_geometry_prior(arm_features.detach())
            + self.config.residual_scale * residual
        )
        return logits.masked_fill(
            ~candidate_mask,
            torch.finfo(logits.dtype).min,
        )


def ordinary_access_geometry_prior(arm_features: torch.Tensor) -> torch.Tensor:
    if (
        arm_features.ndim < 3
        or arm_features.shape[-2] != ORDINARY_PLAN_ARM_COUNT
        or arm_features.shape[-1] != ORDINARY_PLAN_ARM_BASE_FEATURE_DIM
    ):
        raise ValueError("ordinary access geometry-prior shape differs")
    closeness = arm_features[..., 3].amin(dim=-1)
    leaf_closeness = arm_features[..., 5].amin(dim=-1)
    alignment = arm_features[..., 11].mean(dim=-1)
    return closeness + 0.35 * leaf_closeness + 0.10 * alignment


def access_equivalent_candidate_mask(
    *,
    candidate_arm_road_ids: Sequence[Sequence[str]],
    candidate_arm_node_ids: Sequence[Sequence[str]],
    acceptable_indices: Sequence[int],
) -> tuple[bool, ...]:
    """Derive plan-arm targets without treating endpoints as anchor labels."""
    if len(candidate_arm_road_ids) != len(candidate_arm_node_ids):
        raise ValueError("ordinary access candidate sidecars differ")
    signatures = []
    for road_ids, node_ids in zip(
        candidate_arm_road_ids,
        candidate_arm_node_ids,
        strict=True,
    ):
        if len(road_ids) != len(node_ids):
            raise ValueError("ordinary access arm sidecars are misaligned")
        signatures.append(
            tuple(
                (str(road_id), str(node_id))
                for road_id, node_id in zip(road_ids, node_ids, strict=True)
            )
        )
    acceptable = {
        signatures[index]
        for index in acceptable_indices
        if 0 <= index < len(signatures) and signatures[index]
    }
    if not acceptable:
        return (False,) * len(signatures)
    return tuple(bool(signature and signature in acceptable) for signature in signatures)


def multi_acceptable_access_loss(
    logits: torch.Tensor,
    *,
    candidate_mask: torch.Tensor,
    acceptable_access_mask: torch.Tensor,
    sample_weight: torch.Tensor | None = None,
) -> torch.Tensor:
    if (
        logits.ndim != 2
        or candidate_mask.shape != logits.shape
        or acceptable_access_mask.shape != logits.shape
        or candidate_mask.dtype is not torch.bool
        or acceptable_access_mask.dtype is not torch.bool
    ):
        raise ValueError("ordinary access loss shapes differ")
    if bool((acceptable_access_mask & ~candidate_mask).any()):
        raise ValueError("ordinary access target references a masked candidate")
    supervised = acceptable_access_mask.any(dim=-1) & candidate_mask.any(dim=-1)
    if not bool(supervised.any()):
        return logits.sum() * 0.0
    all_scores = logits.masked_fill(
        ~candidate_mask,
        torch.finfo(logits.dtype).min,
    )
    target_scores = logits.masked_fill(
        ~acceptable_access_mask,
        torch.finfo(logits.dtype).min,
    )
    losses = torch.logsumexp(all_scores, dim=-1) - torch.logsumexp(
        target_scores,
        dim=-1,
    )
    if sample_weight is None:
        weights = torch.ones_like(losses)
    else:
        if sample_weight.shape != losses.shape:
            raise ValueError("ordinary access sample weights differ")
        weights = sample_weight.to(losses.dtype)
    weights = weights * supervised.to(losses.dtype)
    return (losses * weights).sum() / weights.sum().clamp_min(1.0)


__all__ = [
    "OrdinaryAccessConsistencyConfig",
    "TargetAOrdinaryAccessConsistencyHead",
    "access_equivalent_candidate_mask",
    "multi_acceptable_access_loss",
    "ordinary_access_geometry_prior",
]
