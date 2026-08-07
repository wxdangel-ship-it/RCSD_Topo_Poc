from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_geometry_data import (
    END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_COUNT,
)


STRUCTURED_COMBINATION_SCHEMA_COUNT = 4
STRUCTURED_COMBINATION_FEATURE_DIM = (
    STRUCTURED_COMBINATION_SCHEMA_COUNT
    + TARGET_A_FEATURE_DIM
    + 2 * ORDINARY_DECISION_COUNT
    + 1
    + 2 * END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM
    + 2
)


@dataclass(frozen=True)
class TargetAStructuredCombinationConfig:
    hidden_dim: int = 128
    dropout: float = 0.10

    def validate(self) -> None:
        if self.hidden_dim < 1:
            raise ValueError("structured combination dimension is invalid")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("structured combination dropout is invalid")


class TargetAStructuredCombinationDecoder(nn.Module):
    """Choose one explainable Road-set plus geometry action combination."""

    def __init__(
        self,
        config: TargetAStructuredCombinationConfig,
    ) -> None:
        super().__init__()
        config.validate()
        self.config = config
        self.encoder = nn.Sequential(
            nn.Linear(
                STRUCTURED_COMBINATION_FEATURE_DIM,
                config.hidden_dim * 2,
            ),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim * 2),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim * 2, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        self.scorer = nn.Sequential(
            nn.Linear(config.hidden_dim * 3, config.hidden_dim * 2),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim * 2),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim * 2, config.hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim, 1),
        )

    def forward(
        self,
        feature_values: torch.Tensor,
        mask: torch.Tensor,
    ) -> torch.Tensor:
        if (
            feature_values.ndim != 3
            or feature_values.shape[-1]
            != STRUCTURED_COMBINATION_FEATURE_DIM
        ):
            raise ValueError("structured combination feature shape differs")
        if (
            mask.shape != feature_values.shape[:2]
            or mask.dtype != torch.bool
        ):
            raise ValueError("structured combination mask differs")
        encoded = self.encoder(feature_values)
        mask_value = mask.unsqueeze(-1).to(encoded.dtype)
        mean = (
            (encoded * mask_value).sum(dim=1)
            / mask_value.sum(dim=1).clamp_min(1.0)
        )
        minimum = torch.finfo(encoded.dtype).min
        maximum = encoded.masked_fill(
            ~mask.unsqueeze(-1),
            minimum,
        ).amax(dim=1)
        maximum = torch.where(
            mask.any(dim=1, keepdim=True),
            maximum,
            torch.zeros_like(maximum),
        )
        context = torch.cat((mean, maximum), dim=-1).unsqueeze(1)
        context = context.expand(-1, encoded.shape[1], -1)
        logits = self.scorer(
            torch.cat((encoded, context), dim=-1)
        ).squeeze(-1)
        return logits.masked_fill(~mask, float("-inf"))


__all__ = [
    "STRUCTURED_COMBINATION_FEATURE_DIM",
    "STRUCTURED_COMBINATION_SCHEMA_COUNT",
    "TargetAStructuredCombinationConfig",
    "TargetAStructuredCombinationDecoder",
]
