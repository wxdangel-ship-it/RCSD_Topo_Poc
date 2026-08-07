from __future__ import annotations

import torch
from torch import nn


class TargetAOrdinaryAccessRoadGroupDecoder(nn.Module):
    """Decode 0, 1 or 2 access recipes inside each selected carrier Road."""

    def __init__(
        self,
        *,
        feature_dim: int,
        hidden_dim: int = 128,
        context_dim: int = 192,
        attention_heads: int = 4,
        attention_layers: int = 1,
        maximum_per_road: int = 2,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if min(
            feature_dim,
            hidden_dim,
            context_dim,
            attention_heads,
            attention_layers,
            maximum_per_road,
        ) < 1:
            raise ValueError("ordinary access Road-group dimensions are invalid")
        if hidden_dim % attention_heads:
            raise ValueError("hidden dimension must divide attention heads")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("ordinary access Road-group dropout is invalid")
        self.feature_dim = feature_dim
        self.hidden_dim = hidden_dim
        self.maximum_per_road = maximum_per_road
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
        self.global_context = nn.Sequential(
            nn.Linear(hidden_dim * 2, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.road_context = nn.Sequential(
            nn.Linear(hidden_dim * 3, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.road_count_head = nn.Sequential(
            nn.Linear(hidden_dim, context_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(context_dim, maximum_per_road + 1),
        )
        self.candidate_head = nn.Sequential(
            nn.Linear(feature_dim + hidden_dim * 3, context_dim),
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
        same_road_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        if (
            candidate_values.ndim != 3
            or candidate_values.shape[-1] != self.feature_dim
        ):
            raise ValueError("ordinary access Road-group feature shape differs")
        if (
            candidate_mask.shape != candidate_values.shape[:2]
            or candidate_mask.dtype is not torch.bool
        ):
            raise ValueError("ordinary access Road-group candidate mask differs")
        expected_relations = (
            candidate_values.shape[0],
            candidate_values.shape[1],
            candidate_values.shape[1],
        )
        if (
            same_road_mask.shape != expected_relations
            or same_road_mask.dtype is not torch.bool
        ):
            raise ValueError("ordinary access same-Road mask differs")
        valid_relations = (
            candidate_mask.unsqueeze(1) & candidate_mask.unsqueeze(2)
        )
        if bool((same_road_mask & ~valid_relations).any()):
            raise ValueError("same-Road mask includes padded candidates")
        if not torch.equal(same_road_mask, same_road_mask.transpose(1, 2)):
            raise ValueError("same-Road mask must be symmetric")
        diagonal = same_road_mask.diagonal(dim1=1, dim2=2)
        if not torch.equal(diagonal, candidate_mask):
            raise ValueError("same-Road mask diagonal differs from candidates")

        projected = self.candidate_projection(candidate_values)
        encoded = self.set_encoder(
            projected,
            src_key_padding_mask=~candidate_mask,
        )
        global_mean, global_maximum = _masked_mean_max(
            encoded,
            candidate_mask,
        )
        global_context = self.global_context(
            torch.cat((global_mean, global_maximum), dim=-1)
        )
        relation_float = same_road_mask.to(encoded.dtype)
        road_mean = torch.bmm(relation_float, encoded) / relation_float.sum(
            dim=-1,
            keepdim=True,
        ).clamp_min(1.0)
        minimum = torch.finfo(encoded.dtype).min
        expanded = encoded.unsqueeze(1).expand(
            -1,
            encoded.shape[1],
            -1,
            -1,
        )
        road_maximum = expanded.masked_fill(
            ~same_road_mask.unsqueeze(-1),
            minimum,
        ).max(dim=2).values
        road_maximum = torch.where(
            candidate_mask.unsqueeze(-1),
            road_maximum,
            torch.zeros_like(road_maximum),
        )
        global_expanded = global_context.unsqueeze(1).expand(
            -1,
            encoded.shape[1],
            -1,
        )
        road_context = self.road_context(
            torch.cat((road_mean, road_maximum, global_expanded), dim=-1)
        )
        road_count_logits = self.road_count_head(road_context)
        road_candidate_counts = same_road_mask.sum(dim=-1, keepdim=True)
        count_values = torch.arange(
            self.maximum_per_road + 1,
            device=candidate_values.device,
        ).view(1, 1, -1)
        road_count_logits = road_count_logits.masked_fill(
            count_values > road_candidate_counts,
            minimum,
        )
        road_count_logits = road_count_logits.masked_fill(
            ~candidate_mask.unsqueeze(-1),
            0.0,
        )
        candidate_logits = self.candidate_head(
            torch.cat(
                (
                    candidate_values,
                    encoded,
                    road_context,
                    global_expanded,
                ),
                dim=-1,
            )
        ).squeeze(-1)
        candidate_logits = candidate_logits.masked_fill(~candidate_mask, 0.0)
        return {
            "candidate_logits": candidate_logits,
            "road_count_logits": road_count_logits,
            "candidate_embeddings": encoded,
            "road_context": road_context,
        }


def _masked_mean_max(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    mask_float = mask.unsqueeze(-1).to(values.dtype)
    mean = (values * mask_float).sum(dim=1) / mask_float.sum(
        dim=1
    ).clamp_min(1.0)
    minimum = torch.finfo(values.dtype).min
    maximum = values.masked_fill(~mask.unsqueeze(-1), minimum).max(dim=1).values
    maximum = torch.where(
        mask.any(dim=1, keepdim=True),
        maximum,
        torch.zeros_like(maximum),
    )
    return mean, maximum


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


__all__ = ["TargetAOrdinaryAccessRoadGroupDecoder", "parameter_count"]
