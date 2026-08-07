from __future__ import annotations

import torch
from torch import nn


class _SetEncoder(nn.Module):
    def __init__(
        self,
        *,
        input_dim: int,
        hidden_dim: int,
        output_dim: int,
        dropout: float,
    ) -> None:
        super().__init__()
        self.input_dim = input_dim
        self.output_dim = output_dim
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, output_dim),
            nn.GELU(),
            nn.LayerNorm(output_dim),
        )

    def forward(
        self,
        values: torch.Tensor,
        mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if values.ndim != 3 or values.shape[-1] != self.input_dim:
            raise ValueError("set encoder value shape differs")
        if mask.shape != values.shape[:2] or mask.dtype != torch.bool:
            raise ValueError("set encoder mask shape differs")
        encoded = self.encoder(values)
        mask_float = mask.unsqueeze(-1).to(encoded.dtype)
        denominator = mask_float.sum(dim=1).clamp_min(1.0)
        mean = (encoded * mask_float).sum(dim=1) / denominator
        minimum = torch.finfo(encoded.dtype).min
        maximum = encoded.masked_fill(
            ~mask.unsqueeze(-1),
            minimum,
        ).max(dim=1).values
        has_value = mask.any(dim=1, keepdim=True)
        maximum = torch.where(
            has_value,
            maximum,
            torch.zeros_like(maximum),
        )
        return encoded, torch.cat((mean, maximum), dim=-1)


class TargetAAdvanceRightConditionalDecoder(nn.Module):
    def __init__(
        self,
        *,
        candidate_feature_dim: int = 60,
        side_feature_dim: int = 150,
        member_feature_dim: int = 24,
        arm_feature_dim: int = 13,
        candidate_hidden_dim: int = 128,
        member_hidden_dim: int = 64,
        arm_hidden_dim: int = 32,
        side_hidden_dim: int = 128,
        context_dim: int = 256,
        plan_type_count: int = 5,
        cardinality_count: int = 10,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        self.candidate_feature_dim = candidate_feature_dim
        self.side_feature_dim = side_feature_dim
        self.plan_type_count = plan_type_count
        self.cardinality_count = cardinality_count
        self.candidate_encoder = _SetEncoder(
            input_dim=candidate_feature_dim,
            hidden_dim=candidate_hidden_dim,
            output_dim=candidate_hidden_dim,
            dropout=dropout,
        )
        self.member_encoder = _SetEncoder(
            input_dim=member_feature_dim,
            hidden_dim=member_hidden_dim,
            output_dim=member_hidden_dim,
            dropout=dropout,
        )
        self.arm_encoder = _SetEncoder(
            input_dim=arm_feature_dim,
            hidden_dim=arm_hidden_dim,
            output_dim=arm_hidden_dim,
            dropout=dropout,
        )
        side_input_dim = (
            side_feature_dim + 2 * member_hidden_dim + 2 * arm_hidden_dim
        )
        self.side_encoder = nn.Sequential(
            nn.Linear(side_input_dim, side_hidden_dim * 2),
            nn.GELU(),
            nn.LayerNorm(side_hidden_dim * 2),
            nn.Dropout(dropout),
            nn.Linear(side_hidden_dim * 2, side_hidden_dim),
            nn.GELU(),
            nn.LayerNorm(side_hidden_dim),
        )
        graph_input_dim = 2 * side_hidden_dim + 2 * candidate_hidden_dim
        self.graph_context = nn.Sequential(
            nn.Linear(graph_input_dim, context_dim * 2),
            nn.GELU(),
            nn.LayerNorm(context_dim * 2),
            nn.Dropout(dropout),
            nn.Linear(context_dim * 2, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
        )
        candidate_decoder_dim = (
            candidate_hidden_dim + context_dim + candidate_feature_dim
        )
        self.candidate_decoder = nn.Sequential(
            nn.Linear(candidate_decoder_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, candidate_hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(candidate_hidden_dim, 1),
        )
        self.plan_type_head = nn.Sequential(
            nn.Linear(context_dim, context_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(context_dim, plan_type_count),
        )
        self.cardinality_head = nn.Sequential(
            nn.Linear(context_dim, context_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(context_dim, cardinality_count),
        )
        self.safety_head = nn.Sequential(
            nn.Linear(context_dim, side_hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(side_hidden_dim, 1),
        )

    def forward(
        self,
        *,
        candidate_values: torch.Tensor,
        candidate_mask: torch.Tensor,
        source_side_values: torch.Tensor,
        source_member_values: torch.Tensor,
        source_member_mask: torch.Tensor,
        source_arm_values: torch.Tensor,
        source_arm_mask: torch.Tensor,
        target_side_values: torch.Tensor,
        target_member_values: torch.Tensor,
        target_member_mask: torch.Tensor,
        target_arm_values: torch.Tensor,
        target_arm_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        if (
            source_side_values.ndim != 2
            or source_side_values.shape[-1] != self.side_feature_dim
            or target_side_values.shape != source_side_values.shape
        ):
            raise ValueError("AdvanceRight side feature shape differs")
        candidate_encoded, candidate_pool = self.candidate_encoder(
            candidate_values,
            candidate_mask,
        )
        _, source_member_pool = self.member_encoder(
            source_member_values,
            source_member_mask,
        )
        _, target_member_pool = self.member_encoder(
            target_member_values,
            target_member_mask,
        )
        _, source_arm_pool = self.arm_encoder(
            source_arm_values,
            source_arm_mask,
        )
        _, target_arm_pool = self.arm_encoder(
            target_arm_values,
            target_arm_mask,
        )
        source_context = self.side_encoder(
            torch.cat(
                (
                    source_side_values,
                    source_member_pool,
                    source_arm_pool,
                ),
                dim=-1,
            )
        )
        target_context = self.side_encoder(
            torch.cat(
                (
                    target_side_values,
                    target_member_pool,
                    target_arm_pool,
                ),
                dim=-1,
            )
        )
        graph_context = self.graph_context(
            torch.cat(
                (source_context, target_context, candidate_pool),
                dim=-1,
            )
        )
        expanded = graph_context.unsqueeze(1).expand(
            -1,
            candidate_values.shape[1],
            -1,
        )
        candidate_logits = self.candidate_decoder(
            torch.cat(
                (candidate_encoded, expanded, candidate_values),
                dim=-1,
            )
        ).squeeze(-1)
        candidate_logits = candidate_logits.masked_fill(
            ~candidate_mask,
            0.0,
        )
        return {
            "candidate_logits": candidate_logits,
            "plan_type_logits": self.plan_type_head(graph_context),
            "cardinality_logits": self.cardinality_head(graph_context),
            "safety_logits": self.safety_head(graph_context).squeeze(-1),
            "graph_context": graph_context,
        }


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


__all__ = [
    "TargetAAdvanceRightConditionalDecoder",
    "parameter_count",
]
