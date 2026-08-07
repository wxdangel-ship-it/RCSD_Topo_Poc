from __future__ import annotations

import torch
from torch import nn


class TargetAOrdinaryAccessDecoder(nn.Module):
    """Set-conditioned decoder for one access Road and split position."""

    def __init__(
        self,
        *,
        feature_dim: int,
        hidden_dim: int = 128,
        context_dim: int = 192,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if min(feature_dim, hidden_dim, context_dim) < 1:
            raise ValueError("ordinary access decoder dimensions are invalid")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("ordinary access decoder dropout is invalid")
        self.feature_dim = feature_dim
        self.hidden_dim = hidden_dim
        self.candidate_encoder = nn.Sequential(
            nn.Linear(feature_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.set_context = nn.Sequential(
            nn.Linear(hidden_dim * 2, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.candidate_decoder = nn.Sequential(
            nn.Linear(feature_dim + hidden_dim * 2, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(
        self,
        candidate_values: torch.Tensor,
        candidate_mask: torch.Tensor,
    ) -> torch.Tensor:
        if (
            candidate_values.ndim != 3
            or candidate_values.shape[-1] != self.feature_dim
        ):
            raise ValueError("ordinary access candidate feature shape differs")
        if (
            candidate_mask.shape != candidate_values.shape[:2]
            or candidate_mask.dtype is not torch.bool
        ):
            raise ValueError("ordinary access candidate mask shape differs")
        encoded = self.candidate_encoder(candidate_values)
        mask_float = candidate_mask.unsqueeze(-1).to(encoded.dtype)
        mean = (encoded * mask_float).sum(dim=1) / mask_float.sum(
            dim=1
        ).clamp_min(1.0)
        minimum = torch.finfo(encoded.dtype).min
        maximum = encoded.masked_fill(
            ~candidate_mask.unsqueeze(-1),
            minimum,
        ).max(dim=1).values
        maximum = torch.where(
            candidate_mask.any(dim=1, keepdim=True),
            maximum,
            torch.zeros_like(maximum),
        )
        context = self.set_context(torch.cat((mean, maximum), dim=-1))
        expanded = context.unsqueeze(1).expand(
            -1,
            candidate_values.shape[1],
            -1,
        )
        logits = self.candidate_decoder(
            torch.cat((candidate_values, encoded, expanded), dim=-1)
        ).squeeze(-1)
        return logits.masked_fill(~candidate_mask, 0.0)


class TargetAOrdinaryAccessCardinalityDecoder(nn.Module):
    """Set Transformer encoder with structured member and cardinality heads."""

    def __init__(
        self,
        *,
        feature_dim: int,
        hidden_dim: int = 128,
        context_dim: int = 192,
        attention_heads: int = 4,
        attention_layers: int = 1,
        max_cardinality: int = 16,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if min(
            feature_dim,
            hidden_dim,
            context_dim,
            attention_heads,
            attention_layers,
            max_cardinality,
        ) < 1:
            raise ValueError("ordinary access structured dimensions are invalid")
        if hidden_dim % attention_heads:
            raise ValueError("hidden dimension must divide attention heads")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("ordinary access structured dropout is invalid")
        self.feature_dim = feature_dim
        self.hidden_dim = hidden_dim
        self.max_cardinality = max_cardinality
        self.candidate_projection = nn.Sequential(
            nn.Linear(feature_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim,
            nhead=attention_heads,
            dim_feedforward=context_dim * 2,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.set_encoder = nn.TransformerEncoder(
            layer,
            num_layers=attention_layers,
            enable_nested_tensor=False,
        )
        self.set_context = nn.Sequential(
            nn.Linear(hidden_dim * 2, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.member_head = nn.Sequential(
            nn.Linear(feature_dim + hidden_dim * 2, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )
        self.cardinality_head = nn.Sequential(
            nn.Linear(hidden_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, max_cardinality),
        )

    def forward(
        self,
        candidate_values: torch.Tensor,
        candidate_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if (
            candidate_values.ndim != 3
            or candidate_values.shape[-1] != self.feature_dim
        ):
            raise ValueError("ordinary access candidate feature shape differs")
        if (
            candidate_mask.shape != candidate_values.shape[:2]
            or candidate_mask.dtype is not torch.bool
        ):
            raise ValueError("ordinary access candidate mask shape differs")
        projected = self.candidate_projection(candidate_values)
        encoded = self.set_encoder(
            projected,
            src_key_padding_mask=~candidate_mask,
        )
        mask_float = candidate_mask.unsqueeze(-1).to(encoded.dtype)
        mean = (encoded * mask_float).sum(dim=1) / mask_float.sum(
            dim=1
        ).clamp_min(1.0)
        minimum = torch.finfo(encoded.dtype).min
        maximum = encoded.masked_fill(
            ~candidate_mask.unsqueeze(-1),
            minimum,
        ).max(dim=1).values
        maximum = torch.where(
            candidate_mask.any(dim=1, keepdim=True),
            maximum,
            torch.zeros_like(maximum),
        )
        context = self.set_context(torch.cat((mean, maximum), dim=-1))
        expanded = context.unsqueeze(1).expand(
            -1,
            candidate_values.shape[1],
            -1,
        )
        member_logits = self.member_head(
            torch.cat((candidate_values, encoded, expanded), dim=-1)
        ).squeeze(-1)
        member_logits = member_logits.masked_fill(~candidate_mask, 0.0)
        cardinality_logits = self.cardinality_head(context)
        candidate_counts = candidate_mask.sum(dim=1, keepdim=True)
        cardinalities = torch.arange(
            1,
            self.max_cardinality + 1,
            device=candidate_values.device,
        ).unsqueeze(0)
        cardinality_logits = cardinality_logits.masked_fill(
            cardinalities > candidate_counts,
            torch.finfo(cardinality_logits.dtype).min,
        )
        return member_logits, cardinality_logits


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


__all__ = [
    "TargetAOrdinaryAccessCardinalityDecoder",
    "TargetAOrdinaryAccessDecoder",
    "parameter_count",
]
