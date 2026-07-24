from __future__ import annotations

from typing import Any

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import (
    group_probabilities,
    parameter_count,
)


class SchemeAHierarchicalCarrierClueScorer(nn.Module):
    def __init__(
        self,
        *,
        candidate_vocabulary_size: int,
        object_vocabulary_size: int,
        context_vocabulary_size: int,
        object_type_count: int,
        numeric_dim: int,
        evidence_dim: int,
        auxiliary_dim: int,
        embedding_dim: int = 96,
        hidden_dim: int = 256,
        type_embedding_dim: int = 24,
        evidence_hidden_dim: int = 256,
        dropout: float = 0.10,
    ) -> None:
        super().__init__()
        dimensions = (
            candidate_vocabulary_size,
            object_vocabulary_size,
            context_vocabulary_size,
            object_type_count,
            numeric_dim,
            evidence_dim,
            auxiliary_dim,
        )
        if min(dimensions) < 1:
            raise ValueError("vocabulary, feature, type, and auxiliary dimensions must be positive")
        self.numeric_dim = numeric_dim
        self.evidence_dim = evidence_dim
        self.auxiliary_dim = auxiliary_dim
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
        numeric_hidden = max(64, hidden_dim // 2)
        self.numeric_encoder = nn.Sequential(
            nn.Linear(numeric_dim, numeric_hidden),
            nn.GELU(),
            nn.LayerNorm(numeric_hidden),
            nn.Linear(numeric_hidden, hidden_dim),
            nn.GELU(),
        )
        self.evidence_encoder = nn.Sequential(
            nn.Linear(evidence_dim, evidence_hidden_dim * 2),
            nn.GELU(),
            nn.LayerNorm(evidence_hidden_dim * 2),
            nn.Dropout(dropout),
            nn.Linear(evidence_hidden_dim * 2, evidence_hidden_dim),
            nn.GELU(),
        )
        candidate_joint_dim = hidden_dim * 7 + evidence_hidden_dim + type_embedding_dim
        self.candidate_head = nn.Sequential(
            nn.Linear(candidate_joint_dim, hidden_dim * 2),
            nn.GELU(),
            nn.LayerNorm(hidden_dim * 2),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, 1),
        )
        self.candidate_correctness_head = nn.Sequential(
            nn.Linear(candidate_joint_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )
        group_joint_dim = hidden_dim * 3 + evidence_hidden_dim + type_embedding_dim
        self.clue_head = nn.Sequential(
            nn.Linear(group_joint_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )
        self.auxiliary_head = nn.Sequential(
            nn.Linear(group_joint_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, auxiliary_dim),
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
        group_evidence: torch.Tensor,
        candidate_group_index: torch.Tensor,
        group_type_ids: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        if numeric_features.ndim != 2 or numeric_features.shape[1] != self.numeric_dim:
            raise ValueError("numeric feature shape differs from model contract")
        if group_evidence.ndim != 2 or group_evidence.shape[1] != self.evidence_dim:
            raise ValueError("group evidence shape differs from model contract")
        candidate = self.candidate_encoder(
            self.candidate_embedding(candidate_token_ids, candidate_offsets)
        )
        object_by_group = self.object_encoder(
            self.object_embedding(object_token_ids, object_offsets)
        )
        context_by_group = self.context_encoder(
            self.context_embedding(context_token_ids, context_offsets)
        )
        evidence_by_group = self.evidence_encoder(group_evidence)
        object_type = self.type_embedding(group_type_ids)
        object_value = object_by_group[candidate_group_index]
        context_value = context_by_group[candidate_group_index]
        evidence_value = evidence_by_group[candidate_group_index]
        type_by_candidate = object_type[candidate_group_index]
        numeric = self.numeric_encoder(numeric_features)
        candidate_joint = torch.cat(
            (
                candidate,
                object_value,
                context_value,
                candidate * object_value,
                candidate * context_value,
                torch.abs(candidate - context_value),
                numeric,
                evidence_value,
                type_by_candidate,
            ),
            dim=-1,
        )
        group_joint = torch.cat(
            (
                object_by_group,
                context_by_group,
                object_by_group * context_by_group,
                evidence_by_group,
                object_type,
            ),
            dim=-1,
        )
        return (
            self.candidate_head(candidate_joint).squeeze(-1),
            self.candidate_correctness_head(candidate_joint).squeeze(-1),
            self.clue_head(group_joint).squeeze(-1),
            self.auxiliary_head(group_joint),
        )


def hierarchical_loss(
    candidate_scores: torch.Tensor,
    candidate_correctness_logits: torch.Tensor,
    clue_logits: torch.Tensor,
    auxiliary_logits: torch.Tensor,
    candidate_group_index: torch.Tensor,
    truth_mask: torch.Tensor,
    group_weights: torch.Tensor,
    clue_targets: torch.Tensor,
    auxiliary_targets: torch.Tensor,
    *,
    candidate_correctness_loss_weight: float,
    clue_loss_weight: float,
    auxiliary_loss_weight: float,
    clue_positive_weight: float,
    auxiliary_positive_weights: torch.Tensor,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    group_count = group_weights.numel()
    if candidate_scores.ndim != 1 or candidate_correctness_logits.shape != candidate_scores.shape:
        raise ValueError("candidate score/logit vectors differ")
    if candidate_group_index.shape != candidate_scores.shape:
        raise ValueError("candidate group index differs")
    if truth_mask.shape != candidate_scores.shape or truth_mask.dtype != torch.bool:
        raise ValueError("truth_mask must be a matching bool vector")
    if clue_logits.shape != group_weights.shape or clue_targets.shape != group_weights.shape:
        raise ValueError("clue tensors must match group weights")
    if auxiliary_logits.shape != auxiliary_targets.shape:
        raise ValueError("auxiliary logit/target shapes differ")
    if auxiliary_logits.shape[0] != group_count:
        raise ValueError("auxiliary group denominator differs")
    truth_counts = torch.zeros(
        group_count, dtype=candidate_scores.dtype, device=candidate_scores.device
    )
    truth_counts.scatter_add_(0, candidate_group_index, truth_mask.to(candidate_scores.dtype))
    if not torch.all(truth_counts == 1):
        raise ValueError("each candidate group must have exactly one truth candidate")

    probabilities = group_probabilities(candidate_scores, candidate_group_index, group_count)
    truth_probability = torch.zeros_like(group_weights)
    truth_probability.scatter_add_(
        0,
        candidate_group_index,
        probabilities * truth_mask.to(probabilities.dtype),
    )
    listwise_each = -torch.log(truth_probability.clamp_min(1e-12))
    listwise = torch.sum(listwise_each * group_weights) / group_weights.sum().clamp_min(1e-12)

    candidate_weight = group_weights[candidate_group_index]
    correctness_each = nn.functional.binary_cross_entropy_with_logits(
        candidate_correctness_logits,
        truth_mask.to(candidate_correctness_logits.dtype),
        reduction="none",
    )
    correctness = torch.sum(correctness_each * candidate_weight) / candidate_weight.sum().clamp_min(
        1e-12
    )
    clue_each = nn.functional.binary_cross_entropy_with_logits(
        clue_logits,
        clue_targets.to(clue_logits.dtype),
        reduction="none",
        pos_weight=torch.tensor(
            max(1e-6, clue_positive_weight),
            dtype=clue_logits.dtype,
            device=clue_logits.device,
        ),
    )
    clue = torch.sum(clue_each * group_weights) / group_weights.sum().clamp_min(1e-12)
    auxiliary_each = nn.functional.binary_cross_entropy_with_logits(
        auxiliary_logits,
        auxiliary_targets.to(auxiliary_logits.dtype),
        reduction="none",
        pos_weight=auxiliary_positive_weights.to(
            dtype=auxiliary_logits.dtype, device=auxiliary_logits.device
        ),
    )
    auxiliary_by_group = auxiliary_each.mean(dim=1)
    auxiliary = torch.sum(auxiliary_by_group * group_weights) / group_weights.sum().clamp_min(
        1e-12
    )
    total = (
        listwise
        + float(candidate_correctness_loss_weight) * correctness
        + float(clue_loss_weight) * clue
        + float(auxiliary_loss_weight) * auxiliary
    )
    return total, {
        "listwise_loss": listwise,
        "candidate_correctness_loss": correctness,
        "clue_loss": clue,
        "auxiliary_loss": auxiliary,
    }


def hierarchical_model_contract(
    model: SchemeAHierarchicalCarrierClueScorer, **metadata: Any
) -> dict[str, Any]:
    return {
        "schema_version": "p05-scheme-a-p2-p3-p0-network-v1",
        "parameter_count": parameter_count(model),
        "carrier_candidate_head": True,
        "candidate_correctness_head": True,
        "reality_change_clue_head": True,
        "auxiliary_head": True,
        "movement_head": False,
        "content_repair": False,
        "silent_fix": False,
        **metadata,
    }


def _token_encoder(embedding_dim: int, hidden_dim: int, dropout: float) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(embedding_dim, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim, hidden_dim),
        nn.GELU(),
    )


__all__ = [
    "SchemeAHierarchicalCarrierClueScorer",
    "hierarchical_loss",
    "hierarchical_model_contract",
    "parameter_count",
]
