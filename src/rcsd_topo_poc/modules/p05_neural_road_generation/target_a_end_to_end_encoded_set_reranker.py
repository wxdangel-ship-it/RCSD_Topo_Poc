from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_set_reranker import (
    END_TO_END_SET_RERANKER_FEATURE_DIM,
)


@dataclass(frozen=True)
class TargetAEndToEndEncodedSetRerankerConfig:
    feature_dim: int
    hidden_dim: int = 128
    dropout: float = 0.10

    def validate(self) -> None:
        if (
            self.feature_dim <= END_TO_END_SET_RERANKER_FEATURE_DIM
            or self.hidden_dim < 32
            or not 0.0 <= self.dropout < 1.0
        ):
            raise ValueError("encoded ordinary set reranker config differs")


class TargetAEndToEndEncodedSetReranker(nn.Module):
    """Rank complete proposals from shared-encoder Road embeddings."""

    def __init__(
        self,
        config: TargetAEndToEndEncodedSetRerankerConfig,
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
            raise ValueError("encoded set normalization values differ")
        self.feature_mean.copy_(values.mean(dim=0))
        self.feature_std.copy_(
            values.std(dim=0, unbiased=False).clamp_min(1e-4)
        )

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        if values.shape[-1] != self.config.feature_dim:
            raise ValueError("encoded set feature dim differs")
        normalized = (
            values - self.feature_mean
        ) / self.feature_std
        return self.scorer(normalized).squeeze(-1)


@dataclass(frozen=True)
class TargetAEndToEndListwiseSetTransformerConfig:
    feature_dim: int
    hidden_dim: int = 192
    num_heads: int = 4
    layer_count: int = 2
    feedforward_dim: int = 384
    dropout: float = 0.10

    def validate(self) -> None:
        if min(
            self.feature_dim,
            self.hidden_dim,
            self.num_heads,
            self.layer_count,
            self.feedforward_dim,
        ) < 1:
            raise ValueError("listwise set Transformer dimensions differ")
        if self.feature_dim <= END_TO_END_SET_RERANKER_FEATURE_DIM:
            raise ValueError("listwise set Transformer lacks encoded evidence")
        if self.hidden_dim % self.num_heads:
            raise ValueError("listwise set Transformer heads do not divide")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("listwise set Transformer dropout differs")


class TargetAEndToEndListwiseSetTransformer(nn.Module):
    """Compare complete Road proposals jointly within one Segment."""

    def __init__(
        self,
        config: TargetAEndToEndListwiseSetTransformerConfig,
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
        self.input_projection = nn.Sequential(
            nn.Linear(config.feature_dim, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        layer = nn.TransformerEncoderLayer(
            d_model=config.hidden_dim,
            nhead=config.num_heads,
            dim_feedforward=config.feedforward_dim,
            dropout=config.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.proposal_encoder = nn.TransformerEncoder(
            layer,
            num_layers=config.layer_count,
            enable_nested_tensor=False,
        )
        head_input_dim = config.hidden_dim * 3
        self.selection_head = _listwise_head(
            head_input_dim,
            config.hidden_dim,
            config.dropout,
        )
        self.validity_head = _listwise_head(
            head_input_dim,
            config.hidden_dim,
            config.dropout,
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
            raise ValueError("listwise normalization values differ")
        self.feature_mean.copy_(values.mean(dim=0))
        self.feature_std.copy_(
            values.std(dim=0, unbiased=False).clamp_min(1e-4)
        )

    def forward(
        self,
        values: torch.Tensor,
        valid_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        if (
            values.ndim != 3
            or values.shape[-1] != self.config.feature_dim
            or valid_mask.shape != values.shape[:2]
            or valid_mask.dtype is not torch.bool
            or not bool(valid_mask.any(dim=-1).all())
        ):
            raise ValueError("listwise proposal batch differs")
        normalized = (
            values - self.feature_mean
        ) / self.feature_std
        encoded = self.input_projection(normalized)
        encoded = self.proposal_encoder(
            encoded,
            src_key_padding_mask=~valid_mask,
        )
        encoded = encoded * valid_mask.unsqueeze(-1).to(encoded.dtype)
        weights = valid_mask.unsqueeze(-1).to(encoded.dtype)
        mean = (encoded * weights).sum(dim=1) / weights.sum(
            dim=1
        ).clamp_min(1.0)
        maximum = encoded.masked_fill(
            ~valid_mask.unsqueeze(-1),
            torch.finfo(encoded.dtype).min,
        ).amax(dim=1)
        comparison = torch.cat(
            (
                encoded,
                mean.unsqueeze(1).expand_as(encoded),
                maximum.unsqueeze(1).expand_as(encoded),
            ),
            dim=-1,
        )
        selection_logits = self.selection_head(comparison).squeeze(-1)
        validity_logits = self.validity_head(comparison).squeeze(-1)
        return {
            "plan_logits": selection_logits.masked_fill(
                ~valid_mask,
                float("-inf"),
            ),
            "plan_validity_logits": validity_logits.masked_fill(
                ~valid_mask,
                0.0,
            ),
            "plan_embeddings": encoded,
        }


@dataclass(frozen=True)
class TargetAEndToEndLinearSetRerankerConfig:
    feature_dim: int

    def validate(self) -> None:
        if self.feature_dim <= END_TO_END_SET_RERANKER_FEATURE_DIM:
            raise ValueError("linear ordinary set reranker config differs")


class TargetAEndToEndLinearSetReranker(nn.Module):
    """Use a regularized linear score over compact encoder evidence."""

    def __init__(
        self,
        config: TargetAEndToEndLinearSetRerankerConfig,
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
        self.scorer = nn.Linear(config.feature_dim, 1)

    def set_feature_normalization(
        self,
        values: torch.Tensor,
    ) -> None:
        if (
            values.ndim != 2
            or values.shape[-1] != self.config.feature_dim
            or values.shape[0] < 1
        ):
            raise ValueError("linear set normalization values differ")
        self.feature_mean.copy_(values.mean(dim=0))
        self.feature_std.copy_(
            values.std(dim=0, unbiased=False).clamp_min(1e-4)
        )

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        if values.shape[-1] != self.config.feature_dim:
            raise ValueError("linear set feature dim differs")
        normalized = (
            values - self.feature_mean
        ) / self.feature_std
        return self.scorer(normalized).squeeze(-1)


def build_encoded_set_proposal_features(
    proposals: Sequence[Mapping[str, object]],
    *,
    scalar_features: torch.Tensor,
    road_embeddings: torch.Tensor,
    allowed_mask: torch.Tensor,
) -> torch.Tensor:
    """Pool shared Road embeddings without labels or terminal facts."""
    proposal_count = len(proposals)
    road_count = int(road_embeddings.shape[0])
    if (
        scalar_features.ndim != 2
        or scalar_features.shape
        != (proposal_count, END_TO_END_SET_RERANKER_FEATURE_DIM)
        or road_embeddings.ndim != 2
        or allowed_mask.shape != (road_count,)
    ):
        raise ValueError("encoded proposal feature inputs differ")
    if proposal_count == 0:
        return road_embeddings.new_zeros(
            (
                0,
                encoded_set_feature_dim(
                    int(road_embeddings.shape[-1])
                ),
            )
        )
    allowed = allowed_mask.bool()
    proposal_masks = torch.zeros(
        proposal_count,
        road_count,
        dtype=torch.bool,
        device=road_embeddings.device,
    )
    for proposal_index, proposal in enumerate(proposals):
        for raw_index in proposal["selected_indices"]:  # type: ignore[index]
            index = int(raw_index)
            if 0 <= index < road_count and bool(allowed[index]):
                proposal_masks[proposal_index, index] = True
    excluded_masks = allowed.unsqueeze(0) & ~proposal_masks
    selected_mean, selected_maximum = _masked_embedding_pool(
        road_embeddings,
        proposal_masks,
    )
    excluded_mean, excluded_maximum = _masked_embedding_pool(
        road_embeddings,
        excluded_masks,
    )
    return torch.cat(
        (
            scalar_features,
            selected_mean,
            selected_maximum,
            excluded_mean,
            excluded_maximum,
            selected_mean - excluded_mean,
        ),
        dim=-1,
    )


def encoded_set_feature_dim(road_embedding_dim: int) -> int:
    if road_embedding_dim < 1:
        raise ValueError("Road embedding dimension differs")
    return END_TO_END_SET_RERANKER_FEATURE_DIM + 5 * road_embedding_dim


def _listwise_head(
    input_dim: int,
    hidden_dim: int,
    dropout: float,
) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim, 1),
    )


def _masked_embedding_pool(
    road_embeddings: torch.Tensor,
    masks: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    counts = masks.sum(dim=1, keepdim=True)
    means = masks.to(road_embeddings.dtype).matmul(
        road_embeddings
    ) / counts.clamp_min(1).to(road_embeddings.dtype)
    expanded = road_embeddings.unsqueeze(0).expand(
        masks.shape[0],
        -1,
        -1,
    )
    maximums = expanded.masked_fill(
        ~masks.unsqueeze(-1),
        torch.finfo(road_embeddings.dtype).min,
    ).amax(dim=1)
    active = counts.gt(0)
    means = torch.where(active, means, torch.zeros_like(means))
    maximums = torch.where(
        active,
        maximums,
        torch.zeros_like(maximums),
    )
    return means, maximums


__all__ = [
    "TargetAEndToEndEncodedSetReranker",
    "TargetAEndToEndEncodedSetRerankerConfig",
    "TargetAEndToEndLinearSetReranker",
    "TargetAEndToEndLinearSetRerankerConfig",
    "TargetAEndToEndListwiseSetTransformer",
    "TargetAEndToEndListwiseSetTransformerConfig",
    "build_encoded_set_proposal_features",
    "encoded_set_feature_dim",
]
