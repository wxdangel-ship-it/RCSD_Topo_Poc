from __future__ import annotations

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    TargetAOrdinaryRoadSetDecoder,
)


class TargetAOrdinaryRoleSetDecoder(TargetAOrdinaryRoadSetDecoder):
    """Keep the production-like set forward while learning Road roles."""

    def __init__(
        self,
        *,
        object_feature_dim: int = 64,
        candidate_feature_dim: int = 40,
        hidden_dim: int = 128,
        context_dim: int = 192,
        cardinality_count: int = 67,
        ownership_count: int = 3,
        business_role_count: int = 4,
        dropout: float = 0.1,
    ) -> None:
        super().__init__(
            object_feature_dim=object_feature_dim,
            candidate_feature_dim=candidate_feature_dim,
            hidden_dim=hidden_dim,
            context_dim=context_dim,
            cardinality_count=cardinality_count,
            dropout=dropout,
        )
        if min(ownership_count, business_role_count) < 2:
            raise ValueError("ordinary role-set label counts are invalid")
        self.ownership_count = ownership_count
        self.business_role_count = business_role_count
        business_input_dim = candidate_feature_dim + hidden_dim * 2
        self.ownership_head = nn.Sequential(
            nn.Linear(business_input_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, ownership_count),
        )
        self.business_role_head = nn.Sequential(
            nn.Linear(business_input_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, business_role_count),
        )

    def forward(
        self,
        *,
        object_features: torch.Tensor,
        candidate_features: torch.Tensor,
        candidate_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        outputs = super().forward(
            object_features=object_features,
            candidate_features=candidate_features,
            candidate_mask=candidate_mask,
        )
        candidate_encoded = self.candidate_encoder(candidate_features)
        expanded = outputs["graph_context"].unsqueeze(1).expand(
            -1,
            candidate_features.shape[1],
            -1,
        )
        business_inputs = torch.cat(
            (candidate_features, candidate_encoded, expanded),
            dim=-1,
        )
        outputs["ownership_logits"] = self.ownership_head(
            business_inputs
        ).masked_fill(~candidate_mask.unsqueeze(-1), 0.0)
        outputs["business_role_logits"] = self.business_role_head(
            business_inputs
        ).masked_fill(~candidate_mask.unsqueeze(-1), 0.0)
        return outputs


class TargetAOrdinaryCountAwareSetDecoder(TargetAOrdinaryRoadSetDecoder):
    """Predict bundle size from explicit set size and soft member mass."""

    def __init__(
        self,
        *,
        object_feature_dim: int = 64,
        candidate_feature_dim: int = 40,
        hidden_dim: int = 128,
        context_dim: int = 192,
        cardinality_count: int = 67,
        dropout: float = 0.1,
    ) -> None:
        super().__init__(
            object_feature_dim=object_feature_dim,
            candidate_feature_dim=candidate_feature_dim,
            hidden_dim=hidden_dim,
            context_dim=context_dim,
            cardinality_count=cardinality_count,
            dropout=dropout,
        )
        self.count_head = nn.Sequential(
            nn.Linear(hidden_dim + 4, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, cardinality_count),
        )
        self.cardinality_ordinal_head = nn.Sequential(
            nn.Linear(hidden_dim + 4, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, cardinality_count - 1),
        )

    def forward(
        self,
        *,
        object_features: torch.Tensor,
        candidate_features: torch.Tensor,
        candidate_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        outputs = super().forward(
            object_features=object_features,
            candidate_features=candidate_features,
            candidate_mask=candidate_mask,
        )
        member_probabilities = torch.sigmoid(
            outputs["member_logits"]
        ) * candidate_mask.to(outputs["member_logits"].dtype)
        valid_count = candidate_mask.sum(dim=-1).to(
            member_probabilities.dtype
        )
        soft_count = member_probabilities.sum(dim=-1)
        maximum = member_probabilities.max(dim=-1).values
        count_features = torch.stack(
            (
                torch.log1p(valid_count) / 5.545177444479562,
                torch.log1p(soft_count) / 4.219507705176107,
                soft_count / valid_count.clamp_min(1.0),
                maximum,
            ),
            dim=-1,
        )
        context = torch.cat(
            (outputs["graph_context"], count_features),
            dim=-1,
        )
        outputs["cardinality_logits"] = self.count_head(context)
        outputs["cardinality_ordinal_logits"] = (
            self.cardinality_ordinal_head(context)
        )
        outputs["soft_member_count"] = soft_count
        return outputs


class TargetAOrdinaryCountAwareRoleSetDecoder(
    TargetAOrdinaryCountAwareSetDecoder
):
    """Add auxiliary ownership/role supervision to count-aware membership."""

    def __init__(
        self,
        *,
        object_feature_dim: int = 64,
        candidate_feature_dim: int = 40,
        hidden_dim: int = 128,
        context_dim: int = 192,
        cardinality_count: int = 67,
        ownership_count: int = 3,
        business_role_count: int = 4,
        dropout: float = 0.1,
    ) -> None:
        super().__init__(
            object_feature_dim=object_feature_dim,
            candidate_feature_dim=candidate_feature_dim,
            hidden_dim=hidden_dim,
            context_dim=context_dim,
            cardinality_count=cardinality_count,
            dropout=dropout,
        )
        if min(ownership_count, business_role_count) < 2:
            raise ValueError(
                "ordinary count-aware role label counts are invalid"
            )
        business_input_dim = candidate_feature_dim + hidden_dim * 2
        self.ownership_head = nn.Sequential(
            nn.Linear(business_input_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, ownership_count),
        )
        self.business_role_head = nn.Sequential(
            nn.Linear(business_input_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, business_role_count),
        )

    def forward(
        self,
        *,
        object_features: torch.Tensor,
        candidate_features: torch.Tensor,
        candidate_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        outputs = super().forward(
            object_features=object_features,
            candidate_features=candidate_features,
            candidate_mask=candidate_mask,
        )
        candidate_encoded = self.candidate_encoder(candidate_features)
        expanded = outputs["graph_context"].unsqueeze(1).expand(
            -1,
            candidate_features.shape[1],
            -1,
        )
        business_inputs = torch.cat(
            (candidate_features, candidate_encoded, expanded),
            dim=-1,
        )
        outputs["ownership_logits"] = self.ownership_head(
            business_inputs
        ).masked_fill(~candidate_mask.unsqueeze(-1), 0.0)
        outputs["business_role_logits"] = self.business_role_head(
            business_inputs
        ).masked_fill(~candidate_mask.unsqueeze(-1), 0.0)
        return outputs


__all__ = [
    "TargetAOrdinaryCountAwareRoleSetDecoder",
    "TargetAOrdinaryCountAwareSetDecoder",
    "TargetAOrdinaryRoleSetDecoder",
]
