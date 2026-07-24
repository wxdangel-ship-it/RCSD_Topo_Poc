from __future__ import annotations

from typing import Any

import torch
from torch import nn


class ContextSetScorer(nn.Module):
    def __init__(
        self,
        *,
        candidate_vocabulary_size: int,
        context_vocabulary_size: int,
        object_type_count: int,
        embedding_dim: int = 128,
        hidden_dim: int = 256,
        type_embedding_dim: int = 32,
        dropout: float = 0.10,
    ) -> None:
        super().__init__()
        if min(candidate_vocabulary_size, context_vocabulary_size, object_type_count) < 1:
            raise ValueError("vocabulary/type sizes must be positive")
        self.candidate_embedding = nn.EmbeddingBag(
            candidate_vocabulary_size,
            embedding_dim,
            mode="mean",
            include_last_offset=False,
        )
        self.context_embedding = nn.EmbeddingBag(
            context_vocabulary_size,
            embedding_dim,
            mode="mean",
            include_last_offset=False,
        )
        self.type_embedding = nn.Embedding(object_type_count, type_embedding_dim)
        self.candidate_encoder = nn.Sequential(
            nn.Linear(embedding_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
        )
        self.context_encoder = nn.Sequential(
            nn.Linear(embedding_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
        )
        joint_dim = hidden_dim * 3 + type_embedding_dim
        self.interaction = nn.Sequential(
            nn.Linear(joint_dim, hidden_dim * 2),
            nn.GELU(),
            nn.LayerNorm(hidden_dim * 2),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(
        self,
        *,
        candidate_token_ids: torch.Tensor,
        candidate_offsets: torch.Tensor,
        context_token_ids: torch.Tensor,
        context_offsets: torch.Tensor,
        candidate_group_index: torch.Tensor,
        group_type_ids: torch.Tensor,
    ) -> torch.Tensor:
        candidate = self.candidate_encoder(
            self.candidate_embedding(candidate_token_ids, candidate_offsets)
        )
        context_by_group = self.context_encoder(
            self.context_embedding(context_token_ids, context_offsets)
        )
        context = context_by_group[candidate_group_index]
        object_type = self.type_embedding(group_type_ids)[candidate_group_index]
        joint = torch.cat((candidate, context, candidate * context, object_type), dim=-1)
        return self.interaction(joint).squeeze(-1)


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)


def listwise_group_loss(
    scores: torch.Tensor,
    candidate_group_index: torch.Tensor,
    truth_mask: torch.Tensor,
    group_weights: torch.Tensor,
) -> torch.Tensor:
    if scores.ndim != 1 or candidate_group_index.shape != scores.shape:
        raise ValueError("scores/group index must be matching vectors")
    if truth_mask.shape != scores.shape or truth_mask.dtype != torch.bool:
        raise ValueError("truth_mask must be a bool vector matching scores")
    group_count = int(group_weights.numel())
    if group_count < 1:
        raise ValueError("at least one group is required")
    truth_counts = torch.zeros(group_count, device=scores.device, dtype=scores.dtype)
    truth_counts.scatter_add_(0, candidate_group_index, truth_mask.to(scores.dtype))
    if not torch.all(truth_counts == 1):
        raise ValueError("each group must contain exactly one truth candidate")
    max_score = torch.full(
        (group_count,), -torch.inf, device=scores.device, dtype=scores.dtype
    )
    max_score.scatter_reduce_(0, candidate_group_index, scores, reduce="amax", include_self=True)
    shifted = torch.exp(scores - max_score[candidate_group_index])
    denominator = torch.zeros(group_count, device=scores.device, dtype=scores.dtype)
    denominator.scatter_add_(0, candidate_group_index, shifted)
    log_partition = max_score + torch.log(denominator.clamp_min(1e-12))
    truth_score = torch.zeros(group_count, device=scores.device, dtype=scores.dtype)
    truth_score.scatter_add_(0, candidate_group_index, scores * truth_mask.to(scores.dtype))
    losses = log_partition - truth_score
    return torch.sum(losses * group_weights) / group_weights.sum().clamp_min(1e-12)


def group_probabilities(
    scores: torch.Tensor, candidate_group_index: torch.Tensor, group_count: int
) -> torch.Tensor:
    max_score = torch.full(
        (group_count,), -torch.inf, device=scores.device, dtype=scores.dtype
    )
    max_score.scatter_reduce_(0, candidate_group_index, scores, reduce="amax", include_self=True)
    values = torch.exp(scores - max_score[candidate_group_index])
    denominator = torch.zeros(group_count, device=scores.device, dtype=scores.dtype)
    denominator.scatter_add_(0, candidate_group_index, values)
    return values / denominator[candidate_group_index].clamp_min(1e-12)


def expected_calibration_error(
    confidences: torch.Tensor, correctness: torch.Tensor, *, bin_count: int = 10
) -> float:
    if confidences.ndim != 1 or correctness.shape != confidences.shape:
        raise ValueError("confidence/correctness must be matching vectors")
    if bin_count < 2:
        raise ValueError("bin_count must be at least two")
    total = max(1, confidences.numel())
    result = torch.zeros((), dtype=torch.float64, device=confidences.device)
    for index in range(bin_count):
        lower = index / bin_count
        upper = (index + 1) / bin_count
        mask = (confidences >= lower) & (
            confidences <= upper if index == bin_count - 1 else confidences < upper
        )
        if not torch.any(mask):
            continue
        accuracy = correctness[mask].to(torch.float64).mean()
        confidence = confidences[mask].to(torch.float64).mean()
        result += mask.sum().to(torch.float64) / total * torch.abs(accuracy - confidence)
    return float(result.item())


def model_contract(model: ContextSetScorer, **metadata: Any) -> dict[str, Any]:
    return {
        "schema_version": "p05-jsg-p3-context-scorer-v1",
        "parameter_count": parameter_count(model),
        **metadata,
    }


__all__ = [
    "ContextSetScorer",
    "expected_calibration_error",
    "group_probabilities",
    "listwise_group_loss",
    "model_contract",
    "parameter_count",
]
