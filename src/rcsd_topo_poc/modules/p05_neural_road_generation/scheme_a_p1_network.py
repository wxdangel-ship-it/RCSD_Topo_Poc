from __future__ import annotations

from typing import Any

import torch
from torch import nn


class SchemeACarrierGraphSetScorer(nn.Module):
    def __init__(
        self,
        *,
        candidate_vocabulary_size: int,
        object_vocabulary_size: int,
        context_vocabulary_size: int,
        object_type_count: int,
        numeric_dim: int = 8,
        embedding_dim: int = 160,
        hidden_dim: int = 384,
        type_embedding_dim: int = 48,
        dropout: float = 0.10,
    ) -> None:
        super().__init__()
        if min(
            candidate_vocabulary_size,
            object_vocabulary_size,
            context_vocabulary_size,
            object_type_count,
            numeric_dim,
        ) < 1:
            raise ValueError("vocabulary, type, and numeric dimensions must be positive")
        self.numeric_dim = numeric_dim
        self.candidate_embedding = nn.EmbeddingBag(
            candidate_vocabulary_size, embedding_dim, mode="mean", include_last_offset=False
        )
        self.object_embedding = nn.EmbeddingBag(
            object_vocabulary_size, embedding_dim, mode="mean", include_last_offset=False
        )
        self.context_embedding = nn.EmbeddingBag(
            context_vocabulary_size, embedding_dim, mode="mean", include_last_offset=False
        )
        self.type_embedding = nn.Embedding(object_type_count, type_embedding_dim)
        self.candidate_encoder = _token_encoder(embedding_dim, hidden_dim, dropout)
        self.object_encoder = _token_encoder(embedding_dim, hidden_dim, dropout)
        self.context_encoder = _token_encoder(embedding_dim, hidden_dim, dropout)
        numeric_hidden = max(64, hidden_dim // 4)
        self.numeric_encoder = nn.Sequential(
            nn.Linear(numeric_dim, numeric_hidden),
            nn.GELU(),
            nn.LayerNorm(numeric_hidden),
            nn.Linear(numeric_hidden, hidden_dim),
            nn.GELU(),
        )
        joint_dim = hidden_dim * 7 + type_embedding_dim
        self.candidate_head = nn.Sequential(
            nn.Linear(joint_dim, hidden_dim * 2),
            nn.GELU(),
            nn.LayerNorm(hidden_dim * 2),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, 1),
        )
        anomaly_dim = hidden_dim * 3 + type_embedding_dim
        self.anomaly_head = nn.Sequential(
            nn.Linear(anomaly_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(
        self,
        *,
        candidate_token_ids: torch.Tensor,
        candidate_offsets: torch.Tensor,
        object_token_ids: torch.Tensor,
        object_offsets: torch.Tensor,
        context_token_ids: torch.Tensor,
        context_offsets: torch.Tensor,
        numeric_features: torch.Tensor,
        candidate_group_index: torch.Tensor,
        group_type_ids: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if numeric_features.ndim != 2 or numeric_features.shape[1] != self.numeric_dim:
            raise ValueError("numeric feature shape differs from model contract")
        candidate = self.candidate_encoder(
            self.candidate_embedding(candidate_token_ids, candidate_offsets)
        )
        object_by_group = self.object_encoder(
            self.object_embedding(object_token_ids, object_offsets)
        )
        context_by_group = self.context_encoder(
            self.context_embedding(context_token_ids, context_offsets)
        )
        object_value = object_by_group[candidate_group_index]
        context_value = context_by_group[candidate_group_index]
        object_type = self.type_embedding(group_type_ids)
        type_by_candidate = object_type[candidate_group_index]
        numeric = self.numeric_encoder(numeric_features)
        joint = torch.cat(
            (
                candidate,
                object_value,
                context_value,
                candidate * object_value,
                candidate * context_value,
                torch.abs(candidate - context_value),
                numeric,
                type_by_candidate,
            ),
            dim=-1,
        )
        candidate_scores = self.candidate_head(joint).squeeze(-1)
        anomaly_joint = torch.cat(
            (object_by_group, context_by_group, object_by_group * context_by_group, object_type),
            dim=-1,
        )
        anomaly_logits = self.anomaly_head(anomaly_joint).squeeze(-1)
        return candidate_scores, anomaly_logits


def _token_encoder(embedding_dim: int, hidden_dim: int, dropout: float) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(embedding_dim, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim, hidden_dim),
        nn.GELU(),
    )


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)


def group_probabilities(
    scores: torch.Tensor, candidate_group_index: torch.Tensor, group_count: int
) -> torch.Tensor:
    if group_count < 1:
        raise ValueError("group_count must be positive")
    maxima = torch.full((group_count,), -torch.inf, dtype=scores.dtype, device=scores.device)
    maxima.scatter_reduce_(0, candidate_group_index, scores, reduce="amax", include_self=True)
    shifted = torch.exp(scores - maxima[candidate_group_index])
    denominator = torch.zeros(group_count, dtype=scores.dtype, device=scores.device)
    denominator.scatter_add_(0, candidate_group_index, shifted)
    return shifted / denominator[candidate_group_index].clamp_min(1e-12)


def scheme_a_p1_loss(
    candidate_scores: torch.Tensor,
    anomaly_logits: torch.Tensor,
    candidate_group_index: torch.Tensor,
    truth_mask: torch.Tensor,
    group_weights: torch.Tensor,
    anomaly_targets: torch.Tensor,
    *,
    anomaly_loss_weight: float,
    anomaly_positive_weight: float,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    if candidate_scores.ndim != 1 or candidate_group_index.shape != candidate_scores.shape:
        raise ValueError("candidate scores/group index must be matching vectors")
    if truth_mask.shape != candidate_scores.shape or truth_mask.dtype != torch.bool:
        raise ValueError("truth_mask must be a matching bool vector")
    group_count = group_weights.numel()
    if anomaly_logits.shape != group_weights.shape or anomaly_targets.shape != group_weights.shape:
        raise ValueError("anomaly tensors must match group weights")
    truth_counts = torch.zeros(group_count, dtype=candidate_scores.dtype, device=candidate_scores.device)
    truth_counts.scatter_add_(0, candidate_group_index, truth_mask.to(candidate_scores.dtype))
    if not torch.all(truth_counts == 1):
        raise ValueError("each candidate group must have exactly one truth candidate")
    maxima = torch.full(
        (group_count,), -torch.inf, dtype=candidate_scores.dtype, device=candidate_scores.device
    )
    maxima.scatter_reduce_(
        0, candidate_group_index, candidate_scores, reduce="amax", include_self=True
    )
    shifted = torch.exp(candidate_scores - maxima[candidate_group_index])
    denominator = torch.zeros_like(maxima)
    denominator.scatter_add_(0, candidate_group_index, shifted)
    partition = maxima + torch.log(denominator.clamp_min(1e-12))
    truth_scores = torch.zeros_like(maxima)
    truth_scores.scatter_add_(
        0, candidate_group_index, candidate_scores * truth_mask.to(candidate_scores.dtype)
    )
    listwise = torch.sum((partition - truth_scores) * group_weights) / group_weights.sum().clamp_min(
        1e-12
    )
    positive_weight = torch.tensor(
        max(1e-6, anomaly_positive_weight),
        dtype=anomaly_logits.dtype,
        device=anomaly_logits.device,
    )
    anomaly_each = nn.functional.binary_cross_entropy_with_logits(
        anomaly_logits,
        anomaly_targets.to(anomaly_logits.dtype),
        reduction="none",
        pos_weight=positive_weight,
    )
    anomaly = torch.sum(anomaly_each * group_weights) / group_weights.sum().clamp_min(1e-12)
    total = listwise + float(anomaly_loss_weight) * anomaly
    return total, {"listwise_loss": listwise, "anomaly_loss": anomaly}


def expected_calibration_error(
    confidences: torch.Tensor, correctness: torch.Tensor, *, bin_count: int = 10
) -> float:
    if confidences.ndim != 1 or correctness.shape != confidences.shape:
        raise ValueError("confidence/correctness must be matching vectors")
    total = max(1, confidences.numel())
    result = torch.zeros((), dtype=torch.float64, device=confidences.device)
    for index in range(bin_count):
        lower = index / bin_count
        upper = (index + 1) / bin_count
        mask = (confidences >= lower) & (
            confidences <= upper if index == bin_count - 1 else confidences < upper
        )
        if torch.any(mask):
            result += mask.sum().to(torch.float64) / total * torch.abs(
                correctness[mask].to(torch.float64).mean()
                - confidences[mask].to(torch.float64).mean()
            )
    return float(result.item())


def model_contract(model: SchemeACarrierGraphSetScorer, **metadata: Any) -> dict[str, Any]:
    return {
        "schema_version": "p05-scheme-a-p1-graphset-scorer-v1",
        "parameter_count": parameter_count(model),
        "listwise_loss": True,
        "anomaly_head": True,
        "content_repair": False,
        "silent_fix": False,
        **metadata,
    }


__all__ = [
    "SchemeACarrierGraphSetScorer",
    "expected_calibration_error",
    "group_probabilities",
    "model_contract",
    "parameter_count",
    "scheme_a_p1_loss",
]
