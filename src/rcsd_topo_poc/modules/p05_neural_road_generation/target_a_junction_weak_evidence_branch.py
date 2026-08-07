from __future__ import annotations

from typing import Mapping

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_data import (
    JunctionJointBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_RELATION_DIM,
    GEOMETRY_ROLE_INDEX,
    GEOMETRY_TOKEN_DIM,
    OBJECT_FEATURE_DIM,
)


class JunctionWeakEvidenceBranch(nn.Module):
    """Independent weak-label encoder whose evidence flows one way into planning."""

    def __init__(
        self,
        *,
        hidden_dim: int,
        num_heads: int,
        dropout: float,
    ) -> None:
        super().__init__()
        if hidden_dim < 64 or hidden_dim % num_heads:
            raise ValueError("weak evidence hidden dimension must divide by heads")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("weak evidence dropout is invalid")
        self.hidden_dim = hidden_dim
        self.geometry_token_stem = _stem(
            GEOMETRY_TOKEN_DIM,
            hidden_dim,
            dropout,
        )
        self.geometry_role_embedding = nn.Embedding(
            len(GEOMETRY_ROLE_INDEX),
            hidden_dim,
        )
        self.geometry_relation_stem = _stem(
            GEOMETRY_RELATION_DIM,
            hidden_dim,
            dropout,
        )
        self.geometry_graph_blocks = nn.ModuleList(
            _SparseEvidenceGraphBlock(hidden_dim, dropout) for _ in range(2)
        )
        self.geometry_encoder = _set_encoder(
            hidden_dim,
            num_heads,
            dropout,
        )
        self.object_context_stem = _stem(
            OBJECT_FEATURE_DIM,
            hidden_dim,
            dropout,
        )
        self.geometry_pool_score = nn.Linear(hidden_dim, 1)
        self.context_fusion = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.object_score = _PairScore(hidden_dim)

    def forward(
        self,
        batch: JunctionJointBatch,
    ) -> Mapping[str, torch.Tensor]:
        token_hidden = self.geometry_token_stem(batch.geometry_tokens)
        object_hidden = _pool_tokens_by_object(
            token_hidden,
            batch.geometry_token_mask,
            batch.geometry_token_object_index,
            batch.geometry_object_mask.shape[1],
        )
        object_hidden = object_hidden + self.geometry_role_embedding(
            batch.geometry_object_roles.clamp_min(0)
        )
        relation_hidden = self.geometry_relation_stem(
            batch.geometry_relation_features
        )
        for block in self.geometry_graph_blocks:
            object_hidden = block(
                object_hidden,
                batch.geometry_relation_index,
                relation_hidden,
                batch.geometry_relation_mask,
                batch.geometry_object_mask,
            )
        object_hidden = _encode_set(
            object_hidden,
            batch.geometry_object_mask,
            self.geometry_encoder,
        )
        context = self.context_fusion(
            torch.cat(
                (
                    self.object_context_stem(batch.object_features),
                    _attention_pool(
                        object_hidden,
                        batch.geometry_object_mask,
                        self.geometry_pool_score,
                    ),
                ),
                dim=-1,
            )
        )
        return {
            "weak_evidence_object_hidden": object_hidden,
            "weak_evidence_context": context,
            "weak_evidence_logits": self.object_score(object_hidden, context),
        }


class _SparseEvidenceGraphBlock(nn.Module):
    def __init__(self, hidden_dim: int, dropout: float) -> None:
        super().__init__()
        self.message = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.update = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Dropout(dropout),
        )
        self.output_norm = nn.LayerNorm(hidden_dim)

    def forward(
        self,
        objects: torch.Tensor,
        relation_index: torch.Tensor,
        relation_features: torch.Tensor,
        relation_mask: torch.Tensor,
        object_mask: torch.Tensor,
    ) -> torch.Tensor:
        if relation_index.shape[:2] != relation_mask.shape:
            raise ValueError("weak evidence relation index/mask differs")
        if relation_features.shape[:2] != relation_mask.shape:
            raise ValueError("weak evidence relation features/mask differs")
        object_count = objects.shape[1]
        safe_index = relation_index.clamp(0, object_count - 1)
        source_index = safe_index[..., 0]
        target_index = safe_index[..., 1]
        sources = torch.gather(
            objects,
            1,
            source_index.unsqueeze(-1).expand(-1, -1, objects.shape[-1]),
        )
        messages = self.message(torch.cat((sources, relation_features), dim=-1))
        valid = (
            relation_mask
            & torch.gather(object_mask, 1, source_index)
            & torch.gather(object_mask, 1, target_index)
        )
        messages = messages * valid.unsqueeze(-1).to(messages.dtype)
        aggregate = torch.zeros_like(objects)
        aggregate.scatter_add_(
            1,
            target_index.unsqueeze(-1).expand_as(messages),
            messages,
        )
        degree = objects.new_zeros(objects.shape[0], object_count, 1)
        degree.scatter_add_(
            1,
            target_index.unsqueeze(-1),
            valid.unsqueeze(-1).to(objects.dtype),
        )
        context = aggregate / degree.clamp_min(1.0)
        updated = self.output_norm(
            objects + self.update(torch.cat((objects, context), dim=-1))
        )
        return torch.where(degree.gt(0), updated, objects) * object_mask.unsqueeze(
            -1
        ).to(objects.dtype)


class _PairScore(nn.Module):
    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.score = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, 1),
        )

    def forward(
        self,
        values: torch.Tensor,
        context: torch.Tensor,
    ) -> torch.Tensor:
        expanded = context.unsqueeze(1).expand(-1, values.shape[1], -1)
        return self.score(torch.cat((values, expanded), dim=-1)).squeeze(-1)


def _stem(
    input_dim: int,
    hidden_dim: int,
    dropout: float,
) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
    )


def _set_encoder(
    hidden_dim: int,
    num_heads: int,
    dropout: float,
) -> nn.TransformerEncoder:
    layer = nn.TransformerEncoderLayer(
        d_model=hidden_dim,
        nhead=num_heads,
        dim_feedforward=hidden_dim * 4,
        dropout=dropout,
        activation="gelu",
        batch_first=True,
        norm_first=True,
    )
    return nn.TransformerEncoder(
        layer,
        num_layers=1,
        norm=nn.LayerNorm(hidden_dim),
        enable_nested_tensor=False,
    )


def _encode_set(
    values: torch.Tensor,
    mask: torch.Tensor,
    encoder: nn.TransformerEncoder,
) -> torch.Tensor:
    safe_mask = mask.clone()
    empty = ~safe_mask.any(dim=1)
    if bool(empty.any()):
        safe_mask[empty, 0] = True
    encoded = encoder(values, src_key_padding_mask=~safe_mask)
    return encoded * mask.unsqueeze(-1).to(encoded.dtype)


def _attention_pool(
    values: torch.Tensor,
    mask: torch.Tensor,
    scorer: nn.Linear,
) -> torch.Tensor:
    logits = scorer(values).squeeze(-1)
    minimum = torch.finfo(logits.dtype).min
    weights = logits.masked_fill(~mask, minimum).softmax(dim=-1)
    weights = torch.where(mask, weights, torch.zeros_like(weights))
    weights = weights / weights.sum(dim=-1, keepdim=True).clamp_min(1e-8)
    return (values * weights.unsqueeze(-1)).sum(dim=1)


def _pool_tokens_by_object(
    tokens: torch.Tensor,
    token_mask: torch.Tensor,
    token_object_index: torch.Tensor,
    object_count: int,
) -> torch.Tensor:
    safe_index = token_object_index.clamp_min(0)
    membership = torch.nn.functional.one_hot(
        safe_index,
        num_classes=object_count,
    ).to(tokens.dtype)
    membership = membership * token_mask.unsqueeze(-1).to(tokens.dtype)
    sums = torch.einsum("bth,bto->boh", tokens, membership)
    counts = membership.sum(dim=1).clamp_min(1.0).unsqueeze(-1)
    return sums / counts


__all__ = ["JunctionWeakEvidenceBranch"]
