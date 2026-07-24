from __future__ import annotations

import torch
from torch import nn


class AdvanceRightCandidateSetScorer(nn.Module):
    def __init__(
        self,
        *,
        feature_dim: int,
        encoder_hidden_dim: int,
        embedding_dim: int,
        context_dim: int,
        decoder_hidden_dim: int,
        decoder_bottleneck_dim: int,
        dropout: float,
    ) -> None:
        super().__init__()
        if min(
            feature_dim,
            encoder_hidden_dim,
            embedding_dim,
            context_dim,
            decoder_hidden_dim,
            decoder_bottleneck_dim,
        ) <= 0:
            raise ValueError("network dimensions must be positive")
        self.feature_dim = feature_dim
        self.encoder = nn.Sequential(
            nn.Linear(feature_dim, encoder_hidden_dim),
            nn.GELU(),
            nn.LayerNorm(encoder_hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(encoder_hidden_dim, embedding_dim),
            nn.GELU(),
            nn.LayerNorm(embedding_dim),
        )
        self.context = nn.Sequential(
            nn.Linear(embedding_dim * 2, embedding_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(embedding_dim, context_dim),
            nn.GELU(),
        )
        decoder_input_dim = embedding_dim + context_dim + feature_dim
        self.candidate_decoder = nn.Sequential(
            nn.Linear(decoder_input_dim, decoder_hidden_dim),
            nn.GELU(),
            nn.LayerNorm(decoder_hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(decoder_hidden_dim, decoder_bottleneck_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(decoder_bottleneck_dim, 1),
        )
        self.object_head = nn.Sequential(
            nn.Linear(context_dim, context_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(context_dim, 1),
        )
        self.safety_head = nn.Sequential(
            nn.Linear(context_dim, context_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(context_dim, 1),
        )

    def forward(
        self,
        values: torch.Tensor,
        mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        if values.ndim != 3 or values.shape[2] != self.feature_dim:
            raise ValueError("candidate tensor shape differs")
        if mask.shape != values.shape[:2] or mask.dtype != torch.bool:
            raise ValueError("candidate mask shape or dtype differs")
        if not bool(mask.any(dim=1).all()):
            raise ValueError("every scorer group must contain a candidate")

        encoded = self.encoder(values)
        mask_float = mask.unsqueeze(-1).to(dtype=encoded.dtype)
        mean_context = (encoded * mask_float).sum(dim=1) / (
            mask_float.sum(dim=1).clamp_min(1.0)
        )
        minimum = torch.finfo(encoded.dtype).min
        max_context = encoded.masked_fill(
            ~mask.unsqueeze(-1),
            minimum,
        ).max(dim=1).values
        context = self.context(
            torch.cat((mean_context, max_context), dim=1)
        )
        expanded = context.unsqueeze(1).expand(
            -1,
            values.shape[1],
            -1,
        )
        candidate_logits = self.candidate_decoder(
            torch.cat((encoded, expanded, values), dim=2)
        ).squeeze(-1)
        # Feature 0 is the frozen R1 LOCAL_5M Control membership and remains
        # unscaled. The network learns a residual over that safe audited prior.
        local_prior = 2.0 * (2.0 * values[:, :, 0] - 1.0)
        candidate_logits = candidate_logits + local_prior
        candidate_logits = candidate_logits.masked_fill(~mask, 0.0)
        object_logits = self.object_head(context).squeeze(-1)
        safety_logits = self.safety_head(context).squeeze(-1)
        return candidate_logits, object_logits, safety_logits


def parameter_count(model: nn.Module) -> int:
    return sum(value.numel() for value in model.parameters())


__all__ = ["AdvanceRightCandidateSetScorer", "parameter_count"]
