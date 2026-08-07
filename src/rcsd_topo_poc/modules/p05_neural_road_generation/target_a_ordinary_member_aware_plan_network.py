from __future__ import annotations

import math
from dataclasses import dataclass

import torch
from torch import nn
from torch.nn import functional as F


@dataclass(frozen=True)
class OrdinaryMemberAwarePlanConfig:
    signal_dim: int = 115
    relation_dim: int = 13
    scalar_feature_dim: int = 18
    hidden_dim: int = 96
    graph_layer_count: int = 2
    proposal_layer_count: int = 2
    attention_head_count: int = 4
    feedforward_dim: int = 192
    dropout: float = 0.10

    def validate(self) -> None:
        if min(
            self.signal_dim,
            self.relation_dim,
            self.scalar_feature_dim,
            self.hidden_dim,
            self.graph_layer_count,
            self.proposal_layer_count,
            self.attention_head_count,
            self.feedforward_dim,
        ) < 1:
            raise ValueError("member-aware plan dimensions differ")
        if self.hidden_dim % self.attention_head_count:
            raise ValueError("member-aware attention heads do not divide")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("member-aware dropout differs")


class OrdinaryMemberAwarePlanNetwork(nn.Module):
    """Compare complete KEEP/USE proposals from Road members and pair relations."""

    def __init__(
        self,
        config: OrdinaryMemberAwarePlanConfig = OrdinaryMemberAwarePlanConfig(),
    ) -> None:
        super().__init__()
        config.validate()
        self.config = config
        self.register_buffer(
            "signal_mean", torch.zeros(config.signal_dim)
        )
        self.register_buffer(
            "signal_std", torch.ones(config.signal_dim)
        )
        self.register_buffer(
            "relation_mean", torch.zeros(config.relation_dim)
        )
        self.register_buffer(
            "relation_std", torch.ones(config.relation_dim)
        )
        self.register_buffer(
            "scalar_mean", torch.zeros(config.scalar_feature_dim)
        )
        self.register_buffer(
            "scalar_std", torch.ones(config.scalar_feature_dim)
        )
        self.road_stem = nn.Sequential(
            nn.Linear(config.signal_dim + 2, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        self.relation_stem = nn.Sequential(
            nn.Linear(config.relation_dim, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        self.graph_layers = nn.ModuleList(
            _RelationAwareRoadLayer(
                hidden_dim=config.hidden_dim,
                feedforward_dim=config.feedforward_dim,
                dropout=config.dropout,
            )
            for _ in range(config.graph_layer_count)
        )
        self.proposal_query = nn.Sequential(
            nn.Linear(config.scalar_feature_dim + 2, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        self.road_key = nn.Linear(
            config.hidden_dim, config.hidden_dim, bias=False
        )
        self.road_value = nn.Linear(
            config.hidden_dim, config.hidden_dim, bias=False
        )
        proposal_input_dim = (
            config.scalar_feature_dim + 2 + config.hidden_dim * 4
        )
        self.proposal_stem = nn.Sequential(
            nn.Linear(proposal_input_dim, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        proposal_layer = nn.TransformerEncoderLayer(
            d_model=config.hidden_dim,
            nhead=config.attention_head_count,
            dim_feedforward=config.feedforward_dim,
            dropout=config.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.proposal_encoder = nn.TransformerEncoder(
            proposal_layer,
            num_layers=config.proposal_layer_count,
            enable_nested_tensor=False,
        )
        self.selection_head = _proposal_head(
            config.hidden_dim * 3,
            hidden_dim=config.hidden_dim,
            dropout=config.dropout,
        )
        self.validity_head = _proposal_head(
            config.hidden_dim * 3,
            hidden_dim=config.hidden_dim,
            dropout=config.dropout,
        )

    def set_feature_normalization(
        self,
        *,
        candidate_signals: torch.Tensor,
        road_relations: torch.Tensor,
        proposal_scalars: torch.Tensor,
    ) -> None:
        _copy_normalization(
            candidate_signals,
            expected_dim=self.config.signal_dim,
            mean=self.signal_mean,
            std=self.signal_std,
        )
        _copy_normalization(
            road_relations,
            expected_dim=self.config.relation_dim,
            mean=self.relation_mean,
            std=self.relation_std,
        )
        _copy_normalization(
            proposal_scalars,
            expected_dim=self.config.scalar_feature_dim,
            mean=self.scalar_mean,
            std=self.scalar_std,
        )

    def forward(
        self,
        *,
        candidate_signals: torch.Tensor,
        road_relations: torch.Tensor,
        candidate_sources: torch.Tensor,
        candidate_mask: torch.Tensor,
        proposal_scalars: torch.Tensor,
        proposal_sources: torch.Tensor,
        proposal_selected: torch.Tensor,
        proposal_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        batch_size, road_count, proposal_count = self._validate_inputs(
            candidate_signals=candidate_signals,
            road_relations=road_relations,
            candidate_sources=candidate_sources,
            candidate_mask=candidate_mask,
            proposal_scalars=proposal_scalars,
            proposal_sources=proposal_sources,
            proposal_selected=proposal_selected,
            proposal_mask=proposal_mask,
        )
        signal_values = (
            candidate_signals - self.signal_mean
        ) / self.signal_std
        relation_values = (
            road_relations - self.relation_mean
        ) / self.relation_std
        scalar_values = (
            proposal_scalars - self.scalar_mean
        ) / self.scalar_std
        candidate_source_values = F.one_hot(
            candidate_sources.clamp(min=0, max=1), num_classes=2
        ).to(candidate_signals.dtype)
        road_hidden = self.road_stem(
            torch.cat((signal_values, candidate_source_values), dim=-1)
        )
        relation_hidden = self.relation_stem(relation_values)
        same_source_pairs = (
            candidate_mask.unsqueeze(1)
            & candidate_mask.unsqueeze(2)
            & candidate_sources.unsqueeze(1).eq(
                candidate_sources.unsqueeze(2)
            )
        )
        for layer in self.graph_layers:
            road_hidden = layer(
                road_hidden,
                relation_hidden=relation_hidden,
                pair_mask=same_source_pairs,
                candidate_mask=candidate_mask,
            )
        proposal_source_values = F.one_hot(
            proposal_sources.clamp(min=0, max=1), num_classes=2
        ).to(candidate_signals.dtype)
        proposal_query = self.proposal_query(
            torch.cat((scalar_values, proposal_source_values), dim=-1)
        )
        proposal_allowed = (
            candidate_mask.unsqueeze(1)
            & candidate_sources.unsqueeze(1).eq(
                proposal_sources.unsqueeze(-1)
            )
            & proposal_mask.unsqueeze(-1)
        )
        selected_mask = proposal_selected & proposal_allowed
        excluded_mask = proposal_allowed & ~selected_mask
        road_keys = self.road_key(road_hidden)
        road_values = self.road_value(road_hidden)
        attention_logits = torch.einsum(
            "bph,bnh->bpn", proposal_query, road_keys
        ) / math.sqrt(self.config.hidden_dim)
        selected_pool, selected_attention = _dynamic_pool(
            attention_logits,
            road_values,
            selected_mask,
        )
        excluded_pool, excluded_attention = _dynamic_pool(
            attention_logits,
            road_values,
            excluded_mask,
        )
        proposal_hidden = self.proposal_stem(
            torch.cat(
                (
                    scalar_values,
                    proposal_source_values,
                    proposal_query,
                    selected_pool,
                    excluded_pool,
                    selected_pool - excluded_pool,
                ),
                dim=-1,
            )
        )
        proposal_hidden = self.proposal_encoder(
            proposal_hidden,
            src_key_padding_mask=~proposal_mask,
        )
        proposal_hidden = proposal_hidden * proposal_mask.unsqueeze(-1)
        mean = _masked_mean(proposal_hidden, proposal_mask)
        maximum = _masked_max(proposal_hidden, proposal_mask)
        comparison = torch.cat(
            (
                proposal_hidden,
                mean.unsqueeze(1).expand(
                    batch_size, proposal_count, -1
                ),
                maximum.unsqueeze(1).expand(
                    batch_size, proposal_count, -1
                ),
            ),
            dim=-1,
        )
        selection_logits = self.selection_head(comparison).squeeze(-1)
        validity_logits = self.validity_head(comparison).squeeze(-1)
        return {
            "plan_logits": selection_logits.masked_fill(
                ~proposal_mask, float("-inf")
            ),
            "plan_validity_logits": validity_logits.masked_fill(
                ~proposal_mask, 0.0
            ),
            "road_embeddings": road_hidden,
            "proposal_embeddings": proposal_hidden,
            "selected_attention": selected_attention,
            "excluded_attention": excluded_attention,
        }

    def _validate_inputs(
        self,
        *,
        candidate_signals: torch.Tensor,
        road_relations: torch.Tensor,
        candidate_sources: torch.Tensor,
        candidate_mask: torch.Tensor,
        proposal_scalars: torch.Tensor,
        proposal_sources: torch.Tensor,
        proposal_selected: torch.Tensor,
        proposal_mask: torch.Tensor,
    ) -> tuple[int, int, int]:
        if candidate_signals.ndim != 3:
            raise ValueError("member-aware candidate signal rank differs")
        batch_size, road_count, signal_dim = candidate_signals.shape
        if proposal_scalars.ndim != 3:
            raise ValueError("member-aware proposal scalar rank differs")
        proposal_count = proposal_scalars.shape[1]
        if (
            signal_dim != self.config.signal_dim
            or road_relations.shape
            != (
                batch_size,
                road_count,
                road_count,
                self.config.relation_dim,
            )
            or candidate_sources.shape != (batch_size, road_count)
            or candidate_mask.shape != (batch_size, road_count)
            or proposal_scalars.shape
            != (
                batch_size,
                proposal_count,
                self.config.scalar_feature_dim,
            )
            or proposal_sources.shape != (batch_size, proposal_count)
            or proposal_selected.shape
            != (batch_size, proposal_count, road_count)
            or proposal_mask.shape != (batch_size, proposal_count)
        ):
            raise ValueError("member-aware plan input shape differs")
        if (
            candidate_sources.dtype != torch.long
            or proposal_sources.dtype != torch.long
            or candidate_mask.dtype != torch.bool
            or proposal_selected.dtype != torch.bool
            or proposal_mask.dtype != torch.bool
        ):
            raise ValueError("member-aware plan input dtype differs")
        if not bool(proposal_mask.any(dim=-1).all()):
            raise ValueError("member-aware batch lacks proposal")
        if bool(
            (
                candidate_mask
                & (candidate_sources.lt(0) | candidate_sources.gt(1))
            ).any()
        ) or bool(
            (
                proposal_mask
                & (proposal_sources.lt(0) | proposal_sources.gt(1))
            ).any()
        ):
            raise ValueError("member-aware source value differs")
        selected_outside_source = proposal_selected & (
            ~candidate_mask.unsqueeze(1)
            | ~candidate_sources.unsqueeze(1).eq(
                proposal_sources.unsqueeze(-1)
            )
            | ~proposal_mask.unsqueeze(-1)
        )
        if bool(selected_outside_source.any()):
            raise ValueError("proposal selects Road outside its source")
        return batch_size, road_count, proposal_count


class _RelationAwareRoadLayer(nn.Module):
    def __init__(
        self,
        *,
        hidden_dim: int,
        feedforward_dim: int,
        dropout: float,
    ) -> None:
        super().__init__()
        self.query = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.key = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.value = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.relation_score = nn.Linear(hidden_dim, 1, bias=False)
        self.message_output = nn.Linear(hidden_dim, hidden_dim)
        self.message_norm = nn.LayerNorm(hidden_dim)
        self.feed_forward = nn.Sequential(
            nn.Linear(hidden_dim, feedforward_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(feedforward_dim, hidden_dim),
        )
        self.feed_forward_norm = nn.LayerNorm(hidden_dim)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        hidden: torch.Tensor,
        *,
        relation_hidden: torch.Tensor,
        pair_mask: torch.Tensor,
        candidate_mask: torch.Tensor,
    ) -> torch.Tensor:
        logits = torch.einsum(
            "bih,bjh->bij", self.query(hidden), self.key(hidden)
        ) / math.sqrt(hidden.shape[-1])
        logits = logits + self.relation_score(relation_hidden).squeeze(-1)
        weights = torch.softmax(logits.masked_fill(~pair_mask, -1e4), dim=-1)
        weights = weights * pair_mask.to(weights.dtype)
        weights = weights / weights.sum(dim=-1, keepdim=True).clamp_min(1e-9)
        message = weights.matmul(self.value(hidden))
        hidden = self.message_norm(
            hidden + self.dropout(self.message_output(message))
        )
        hidden = self.feed_forward_norm(
            hidden + self.dropout(self.feed_forward(hidden))
        )
        return hidden * candidate_mask.unsqueeze(-1)


def _dynamic_pool(
    logits: torch.Tensor,
    road_values: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    weights = torch.softmax(logits.masked_fill(~mask, -1e4), dim=-1)
    weights = weights * mask.to(weights.dtype)
    weights = weights / weights.sum(dim=-1, keepdim=True).clamp_min(1e-9)
    pooled = torch.einsum("bpn,bnh->bph", weights, road_values)
    return pooled, weights


def _masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    weights = mask.unsqueeze(-1).to(values.dtype)
    return (values * weights).sum(dim=1) / weights.sum(dim=1).clamp_min(1.0)


def _masked_max(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    maximum = values.masked_fill(
        ~mask.unsqueeze(-1), torch.finfo(values.dtype).min
    ).amax(dim=1)
    return torch.where(mask.any(dim=1, keepdim=True), maximum, 0.0)


def _copy_normalization(
    values: torch.Tensor,
    *,
    expected_dim: int,
    mean: torch.Tensor,
    std: torch.Tensor,
) -> None:
    if values.ndim != 2 or values.shape[-1] != expected_dim or len(values) < 1:
        raise ValueError("member-aware normalization values differ")
    mean.copy_(values.mean(dim=0))
    std.copy_(values.std(dim=0, unbiased=False).clamp_min(1e-4))


def _proposal_head(
    input_dim: int,
    *,
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


__all__ = [
    "OrdinaryMemberAwarePlanConfig",
    "OrdinaryMemberAwarePlanNetwork",
]
