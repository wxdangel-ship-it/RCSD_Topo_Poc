from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import torch
from torch import nn
from torch.nn import functional as F


END_TO_END_SET_RERANKER_FEATURE_DIM = 18


@dataclass(frozen=True)
class TargetAEndToEndSetRerankerConfig:
    feature_dim: int = END_TO_END_SET_RERANKER_FEATURE_DIM
    hidden_dim: int = 32
    dropout: float = 0.10

    def validate(self) -> None:
        if (
            self.feature_dim != END_TO_END_SET_RERANKER_FEATURE_DIM
            or self.hidden_dim < 8
            or not 0.0 <= self.dropout < 1.0
        ):
            raise ValueError("ordinary set reranker config differs")


class TargetAEndToEndSetReranker(nn.Module):
    """Score complete beam proposals from inference-time set evidence."""

    def __init__(
        self,
        config: TargetAEndToEndSetRerankerConfig,
    ) -> None:
        super().__init__()
        config.validate()
        self.config = config
        self.register_buffer(
            "feature_mean",
            torch.zeros(config.feature_dim),
        )
        self.register_buffer(
            "feature_std",
            torch.ones(config.feature_dim),
        )
        self.scorer = nn.Sequential(
            nn.Linear(config.feature_dim, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim, config.hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim, 1),
        )

    def set_feature_normalization(
        self,
        values: torch.Tensor,
    ) -> None:
        if (
            values.ndim != 2
            or values.shape[-1] != self.config.feature_dim
            or values.shape[0] < 1
        ):
            raise ValueError("ordinary set normalization values differ")
        self.feature_mean.copy_(values.mean(dim=0))
        self.feature_std.copy_(
            values.std(dim=0, unbiased=False).clamp_min(1e-4)
        )

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        if values.shape[-1] != self.config.feature_dim:
            raise ValueError("ordinary set reranker feature dim differs")
        normalized = (
            values - self.feature_mean
        ) / self.feature_std
        return self.scorer(normalized).squeeze(-1)


def build_end_to_end_set_proposal_features(
    proposals: Sequence[Mapping[str, object]],
    *,
    member_logits: torch.Tensor,
    cardinality_logits: torch.Tensor,
    road_relations: torch.Tensor,
    allowed_mask: torch.Tensor,
) -> torch.Tensor:
    """Describe complete proposals without label or terminal-state inputs."""
    if (
        member_logits.ndim != 1
        or cardinality_logits.ndim != 1
        or road_relations.ndim != 3
        or road_relations.shape[:2]
        != (member_logits.shape[0], member_logits.shape[0])
        or road_relations.shape[-1] < 9
        or allowed_mask.shape != member_logits.shape
    ):
        raise ValueError("ordinary proposal feature inputs differ")
    allowed = allowed_mask.bool()
    allowed_count = int(allowed.sum().item())
    if allowed_count < 1 or not proposals:
        return member_logits.new_zeros(
            (0, END_TO_END_SET_RERANKER_FEATURE_DIM)
        )
    member_probabilities = torch.sigmoid(member_logits)
    cardinality_log_probabilities = torch.log_softmax(
        cardinality_logits,
        dim=-1,
    )
    cardinalities = torch.arange(
        cardinality_logits.shape[0],
        dtype=cardinality_logits.dtype,
        device=cardinality_logits.device,
    )
    expected_cardinality = (
        cardinality_log_probabilities.exp() * cardinalities
    ).sum()
    result = []
    for proposal in proposals:
        selected = torch.zeros_like(allowed)
        for raw_index in proposal["selected_indices"]:  # type: ignore[index]
            index = int(raw_index)
            if 0 <= index < len(selected) and bool(allowed[index]):
                selected[index] = True
        excluded = allowed & ~selected
        size = int(selected.sum().item())
        raw_log_probability = member_logits.new_tensor(
            float(proposal["log_probability"])
        )
        selected_mean, selected_minimum = _mean_and_minimum(
            member_probabilities,
            selected,
        )
        excluded_mean, excluded_maximum = _mean_and_maximum(
            member_probabilities,
            excluded,
        )
        membership_log_probability = (
            F.logsigmoid(member_logits[selected]).sum()
            + F.logsigmoid(-member_logits[excluded]).sum()
        ) / float(allowed_count)
        internal_any, internal_endpoint, internal_near = (
            _internal_relation_features(
                road_relations,
                selected,
            )
        )
        cross_any = _cross_relation_density(
            road_relations,
            selected,
            excluded,
        )
        size_tensor = member_logits.new_tensor(float(size))
        allowed_tensor = member_logits.new_tensor(float(allowed_count))
        cardinality_index = min(
            size,
            cardinality_logits.shape[0] - 1,
        )
        result.append(
            torch.stack(
                (
                    torch.tanh(raw_log_probability / 10.0),
                    torch.tanh(
                        raw_log_probability
                        / float(size + 1)
                        / 3.0
                    ),
                    torch.tanh(
                        cardinality_log_probabilities[
                            cardinality_index
                        ]
                        / 5.0
                    ),
                    size_tensor / allowed_tensor,
                    torch.log1p(size_tensor)
                    / torch.log1p(allowed_tensor),
                    expected_cardinality / allowed_tensor,
                    (
                        size_tensor - expected_cardinality
                    ) / allowed_tensor,
                    selected_mean,
                    selected_minimum,
                    excluded_mean,
                    excluded_maximum,
                    selected_minimum - excluded_maximum,
                    torch.tanh(membership_log_probability),
                    internal_any,
                    internal_endpoint,
                    internal_near,
                    cross_any,
                    member_logits.new_tensor(float(size == 0)),
                )
            )
        )
    return torch.stack(result)


def listwise_multi_positive_loss(
    scores: torch.Tensor,
    *,
    proposal_mask: torch.Tensor,
    positive_mask: torch.Tensor,
    sample_weights: torch.Tensor,
) -> torch.Tensor:
    if (
        scores.ndim != 2
        or proposal_mask.shape != scores.shape
        or positive_mask.shape != scores.shape
        or sample_weights.shape != scores.shape[:1]
    ):
        raise ValueError("ordinary set reranker loss inputs differ")
    positive_mask = positive_mask & proposal_mask
    active = positive_mask.any(dim=-1)
    if not bool(active.any()):
        return scores.sum() * 0.0
    minimum = torch.finfo(scores.dtype).min
    all_log_mass = torch.logsumexp(
        scores.masked_fill(~proposal_mask, minimum),
        dim=-1,
    )
    positive_log_mass = torch.logsumexp(
        scores.masked_fill(~positive_mask, minimum),
        dim=-1,
    )
    losses = all_log_mass - positive_log_mass
    weights = sample_weights * active.to(sample_weights.dtype)
    return (losses * weights).sum() / weights.sum().clamp_min(1e-6)


def _mean_and_minimum(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    if not bool(mask.any()):
        zero = values.new_zeros(())
        return zero, zero
    return values[mask].mean(), values[mask].amin()


def _mean_and_maximum(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    if not bool(mask.any()):
        zero = values.new_zeros(())
        return zero, zero
    return values[mask].mean(), values[mask].amax()


def _internal_relation_features(
    relations: torch.Tensor,
    selected: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    pair_mask = selected.unsqueeze(1) & selected.unsqueeze(0)
    pair_mask.fill_diagonal_(False)
    if not bool(pair_mask.any()):
        zero = relations.new_zeros(())
        return zero, zero, zero
    any_relation = relations.abs().sum(dim=-1).gt(0.0)
    return (
        any_relation[pair_mask].to(relations.dtype).mean(),
        relations[..., 0][pair_mask].mean(),
        relations[..., 8][pair_mask].mean(),
    )


def _cross_relation_density(
    relations: torch.Tensor,
    selected: torch.Tensor,
    excluded: torch.Tensor,
) -> torch.Tensor:
    pair_mask = selected.unsqueeze(1) & excluded.unsqueeze(0)
    if not bool(pair_mask.any()):
        return relations.new_zeros(())
    any_relation = relations.abs().sum(dim=-1).gt(0.0)
    return any_relation[pair_mask].to(relations.dtype).mean()


__all__ = [
    "END_TO_END_SET_RERANKER_FEATURE_DIM",
    "TargetAEndToEndSetReranker",
    "TargetAEndToEndSetRerankerConfig",
    "build_end_to_end_set_proposal_features",
    "listwise_multi_positive_loss",
]
