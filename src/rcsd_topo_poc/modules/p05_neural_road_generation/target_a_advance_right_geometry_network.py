from __future__ import annotations

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_network import (
    TargetAAdvanceRightConditionalDecoder,
)


class TargetAAdvanceRightGeometryDecoder(nn.Module):
    """Shared conditional encoder plus a structured geometry proposal head."""

    def __init__(
        self,
        *,
        proposal_feature_dim: int = 113,
        proposal_hidden_dim: int = 128,
        context_dim: int = 256,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.proposal_feature_dim = proposal_feature_dim
        self.base = TargetAAdvanceRightConditionalDecoder(dropout=dropout)
        self.proposal_encoder = nn.Sequential(
            nn.Linear(proposal_feature_dim, proposal_hidden_dim * 2),
            nn.GELU(),
            nn.LayerNorm(proposal_hidden_dim * 2),
            nn.Dropout(dropout),
            nn.Linear(proposal_hidden_dim * 2, proposal_hidden_dim),
            nn.GELU(),
            nn.LayerNorm(proposal_hidden_dim),
        )
        self.proposal_decoder = nn.Sequential(
            nn.Linear(
                proposal_feature_dim + proposal_hidden_dim + context_dim,
                context_dim,
            ),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, proposal_hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(proposal_hidden_dim, 1),
        )
        self.geometry_safety_head = nn.Sequential(
            nn.Linear(context_dim + proposal_hidden_dim * 2, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, 1),
        )

    def load_base_state_dict(self, state_dict) -> None:
        self.base.load_state_dict(state_dict)

    def freeze_base(self) -> None:
        for parameter in self.base.parameters():
            parameter.requires_grad = False

    def forward(
        self,
        *,
        proposal_values: torch.Tensor,
        proposal_mask: torch.Tensor,
        **base_inputs: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        if (
            proposal_values.ndim != 3
            or proposal_values.shape[-1] != self.proposal_feature_dim
        ):
            raise ValueError("geometry proposal feature shape differs")
        if (
            proposal_mask.shape != proposal_values.shape[:2]
            or proposal_mask.dtype != torch.bool
        ):
            raise ValueError("geometry proposal mask shape differs")
        base_outputs = self.base(**base_inputs)
        graph_context = base_outputs["graph_context"]
        encoded = self.proposal_encoder(proposal_values)
        mask_float = proposal_mask.unsqueeze(-1).to(encoded.dtype)
        denominator = mask_float.sum(dim=1).clamp_min(1.0)
        mean = (encoded * mask_float).sum(dim=1) / denominator
        minimum = torch.finfo(encoded.dtype).min
        maximum = encoded.masked_fill(
            ~proposal_mask.unsqueeze(-1),
            minimum,
        ).max(dim=1).values
        maximum = torch.where(
            proposal_mask.any(dim=1, keepdim=True),
            maximum,
            torch.zeros_like(maximum),
        )
        expanded = graph_context.unsqueeze(1).expand(
            -1,
            proposal_values.shape[1],
            -1,
        )
        proposal_logits = self.proposal_decoder(
            torch.cat((proposal_values, encoded, expanded), dim=-1)
        ).squeeze(-1)
        proposal_logits = proposal_logits.masked_fill(~proposal_mask, 0.0)
        return {
            **base_outputs,
            "geometry_proposal_logits": proposal_logits,
            "geometry_safety_logits": self.geometry_safety_head(
                torch.cat((graph_context, mean, maximum), dim=-1)
            ).squeeze(-1),
        }


def trainable_parameter_count(model: nn.Module) -> int:
    return sum(
        parameter.numel()
        for parameter in model.parameters()
        if parameter.requires_grad
    )


__all__ = [
    "TargetAAdvanceRightGeometryDecoder",
    "trainable_parameter_count",
]
