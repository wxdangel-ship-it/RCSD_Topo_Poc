from __future__ import annotations

import torch
from torch import nn


class TargetAOrdinaryRoadSetDecoder(nn.Module):
    """Decode decision, cardinality, and complete Road membership."""

    def __init__(
        self,
        *,
        object_feature_dim: int = 64,
        candidate_feature_dim: int = 40,
        hidden_dim: int = 128,
        context_dim: int = 192,
        cardinality_count: int = 65,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if min(
            object_feature_dim,
            candidate_feature_dim,
            hidden_dim,
            context_dim,
            cardinality_count,
        ) < 1:
            raise ValueError("ordinary Road-set decoder dimensions are invalid")
        self.object_feature_dim = object_feature_dim
        self.candidate_feature_dim = candidate_feature_dim
        self.cardinality_count = cardinality_count
        self.object_encoder = nn.Sequential(
            nn.Linear(object_feature_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.candidate_encoder = nn.Sequential(
            nn.Linear(candidate_feature_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.graph_context = nn.Sequential(
            nn.Linear(hidden_dim * 3, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.decision_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 2),
        )
        self.cardinality_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, cardinality_count),
        )
        self.member_head = nn.Sequential(
            nn.Linear(candidate_feature_dim + hidden_dim * 2, context_dim),
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
        *,
        object_features: torch.Tensor,
        candidate_features: torch.Tensor,
        candidate_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        if (
            object_features.ndim != 2
            or object_features.shape[-1] != self.object_feature_dim
        ):
            raise ValueError("ordinary Road-set object shape differs")
        if (
            candidate_features.ndim != 3
            or candidate_features.shape[-1] != self.candidate_feature_dim
        ):
            raise ValueError("ordinary Road-set candidate shape differs")
        if (
            candidate_mask.shape != candidate_features.shape[:2]
            or candidate_mask.dtype is not torch.bool
        ):
            raise ValueError("ordinary Road-set mask shape differs")
        object_encoded = self.object_encoder(object_features)
        candidate_encoded = self.candidate_encoder(candidate_features)
        mask_float = candidate_mask.unsqueeze(-1).to(candidate_encoded.dtype)
        mean = (candidate_encoded * mask_float).sum(dim=1) / mask_float.sum(
            dim=1
        ).clamp_min(1.0)
        minimum = torch.finfo(candidate_encoded.dtype).min
        maximum = candidate_encoded.masked_fill(
            ~candidate_mask.unsqueeze(-1),
            minimum,
        ).max(dim=1).values
        maximum = torch.where(
            candidate_mask.any(dim=1, keepdim=True),
            maximum,
            torch.zeros_like(maximum),
        )
        context = self.graph_context(
            torch.cat((object_encoded, mean, maximum), dim=-1)
        )
        expanded = context.unsqueeze(1).expand(
            -1,
            candidate_features.shape[1],
            -1,
        )
        member_logits = self.member_head(
            torch.cat(
                (candidate_features, candidate_encoded, expanded),
                dim=-1,
            )
        ).squeeze(-1)
        member_logits = member_logits.masked_fill(~candidate_mask, 0.0)
        return {
            "decision_logits": self.decision_head(context),
            "cardinality_logits": self.cardinality_head(context),
            "member_logits": member_logits,
            "graph_context": context,
        }


class _RoadGraphBlock(nn.Module):
    def __init__(
        self,
        *,
        hidden_dim: int,
        num_heads: int,
        feedforward_dim: int,
        road_relation_dim: int,
        road_relation_attention_bias: bool,
        dropout: float,
    ) -> None:
        super().__init__()
        self.num_heads = num_heads
        self.road_relation_dim = road_relation_dim
        self.attention = nn.MultiheadAttention(
            hidden_dim,
            num_heads,
            dropout=dropout,
            batch_first=True,
        )
        self.norm1 = nn.LayerNorm(hidden_dim)
        self.norm2 = nn.LayerNorm(hidden_dim)
        self.feedforward = nn.Sequential(
            nn.Linear(hidden_dim, feedforward_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(feedforward_dim, hidden_dim),
            nn.Dropout(dropout),
        )
        self.road_relation_bias = (
            nn.Linear(road_relation_dim, num_heads, bias=False)
            if road_relation_dim > 0 and road_relation_attention_bias
            else None
        )

    def forward(
        self,
        values: torch.Tensor,
        mask: torch.Tensor,
        adjacency: torch.Tensor,
        road_relations: torch.Tensor,
    ) -> torch.Tensor:
        batch, count, _ = values.shape
        if adjacency.shape != (batch, count, count):
            raise ValueError("ordinary USE Road adjacency shape differs")
        if road_relations.shape != (
            batch,
            count,
            count,
            self.road_relation_dim,
        ):
            raise ValueError("ordinary Road relation shape differs")
        allowed = adjacency | torch.eye(
            count,
            dtype=torch.bool,
            device=values.device,
        ).unsqueeze(0)
        allowed &= mask.unsqueeze(1) & mask.unsqueeze(2)
        allowed[:, :, 0] |= ~mask
        if self.road_relation_bias is None:
            attention_mask = (~allowed).unsqueeze(1).expand(
                batch,
                self.num_heads,
                count,
                count,
            )
            attention_mask = attention_mask.reshape(
                batch * self.num_heads,
                count,
                count,
            )
            encoded, _ = self.attention(
                values,
                values,
                values,
                attn_mask=attention_mask,
                key_padding_mask=~mask,
                need_weights=False,
            )
        else:
            attention_mask = self.road_relation_bias(
                road_relations
            ).permute(0, 3, 1, 2)
            attention_mask = attention_mask.masked_fill(
                ~allowed.unsqueeze(1),
                torch.finfo(attention_mask.dtype).min,
            )
            attention_mask = attention_mask.reshape(
                batch * self.num_heads,
                count,
                count,
            )
            encoded, _ = self.attention(
                values,
                values,
                values,
                attn_mask=attention_mask,
                need_weights=False,
            )
        values = self.norm1(values + encoded)
        values = self.norm2(values + self.feedforward(values))
        return values * mask.unsqueeze(-1).to(values.dtype)


class TargetAOrdinaryUseRoadGraphDecoder(nn.Module):
    """Graph decoder for the RCSD Road set after USE_RCSD is selected."""

    def __init__(
        self,
        *,
        object_feature_dim: int = 64,
        candidate_feature_dim: int = 40,
        hidden_dim: int = 128,
        context_dim: int = 192,
        graph_layers: int = 2,
        num_heads: int = 4,
        attention_scope: str = "ENDPOINT",
        road_relation_dim: int = 0,
        road_relation_attention_bias: bool = True,
        road_relation_graph_adjacency: bool = True,
        cardinality_count: int = 65,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if hidden_dim % num_heads:
            raise ValueError("ordinary USE Road heads do not divide hidden dim")
        if graph_layers < 1:
            raise ValueError("ordinary USE Road graph layer count is invalid")
        if road_relation_dim < 0:
            raise ValueError("ordinary Road relation dimension is invalid")
        if attention_scope not in {
            "ENDPOINT",
            "FULL",
            "ENDPOINT_THEN_FULL",
        }:
            raise ValueError("ordinary USE Road attention scope is invalid")
        self.object_feature_dim = object_feature_dim
        self.candidate_feature_dim = candidate_feature_dim
        self.cardinality_count = cardinality_count
        self.attention_scope = attention_scope
        self.road_relation_dim = road_relation_dim
        self.road_relation_attention_bias = road_relation_attention_bias
        self.road_relation_graph_adjacency = (
            road_relation_graph_adjacency
        )
        self.object_encoder = nn.Sequential(
            nn.Linear(object_feature_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.candidate_encoder = nn.Sequential(
            nn.Linear(candidate_feature_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.graph_blocks = nn.ModuleList(
            _RoadGraphBlock(
                hidden_dim=hidden_dim,
                num_heads=num_heads,
                feedforward_dim=context_dim * 2,
                road_relation_dim=road_relation_dim,
                road_relation_attention_bias=(
                    road_relation_attention_bias
                ),
                dropout=dropout,
            )
            for _ in range(graph_layers)
        )
        self.graph_context = nn.Sequential(
            nn.Linear(hidden_dim * 3, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.cardinality_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, cardinality_count),
        )
        self.member_head = nn.Sequential(
            nn.Linear(candidate_feature_dim + hidden_dim * 2, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def _apply_graph_blocks(
        self,
        encoded: torch.Tensor,
        candidate_mask: torch.Tensor,
        adjacency: torch.Tensor,
        road_relations: torch.Tensor,
    ) -> torch.Tensor:
        full_adjacency = (
            candidate_mask.unsqueeze(1) & candidate_mask.unsqueeze(2)
        )
        for block_index, block in enumerate(self.graph_blocks):
            block_adjacency = adjacency
            if self.attention_scope == "FULL" or (
                self.attention_scope == "ENDPOINT_THEN_FULL"
                and block_index > 0
            ):
                block_adjacency = full_adjacency
            encoded = block(
                encoded,
                candidate_mask,
                block_adjacency,
                road_relations,
            )
        return encoded

    def _decode_encoded(
        self,
        *,
        object_features: torch.Tensor,
        candidate_features: torch.Tensor,
        candidate_mask: torch.Tensor,
        encoded: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        object_encoded = self.object_encoder(object_features)
        mask_float = candidate_mask.unsqueeze(-1).to(encoded.dtype)
        mean = (encoded * mask_float).sum(dim=1) / mask_float.sum(
            dim=1
        ).clamp_min(1.0)
        maximum = encoded.masked_fill(
            ~candidate_mask.unsqueeze(-1),
            torch.finfo(encoded.dtype).min,
        ).max(dim=1).values
        maximum = torch.where(
            candidate_mask.any(dim=1, keepdim=True),
            maximum,
            torch.zeros_like(maximum),
        )
        context = self.graph_context(
            torch.cat((object_encoded, mean, maximum), dim=-1)
        )
        expanded = context.unsqueeze(1).expand(
            -1,
            candidate_features.shape[1],
            -1,
        )
        member_logits = self.member_head(
            torch.cat((candidate_features, encoded, expanded), dim=-1)
        ).squeeze(-1)
        return {
            "cardinality_logits": self.cardinality_head(context),
            "member_logits": member_logits.masked_fill(
                ~candidate_mask,
                0.0,
            ),
            "graph_context": context,
            "candidate_encoded": encoded,
        }

    def forward(
        self,
        *,
        object_features: torch.Tensor,
        candidate_features: torch.Tensor,
        candidate_mask: torch.Tensor,
        adjacency: torch.Tensor,
        road_relations: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        if (
            object_features.ndim != 2
            or object_features.shape[-1] != self.object_feature_dim
        ):
            raise ValueError("ordinary USE Road object shape differs")
        if (
            candidate_features.ndim != 3
            or candidate_features.shape[-1] != self.candidate_feature_dim
        ):
            raise ValueError("ordinary USE Road candidate shape differs")
        if (
            candidate_mask.shape != candidate_features.shape[:2]
            or candidate_mask.dtype is not torch.bool
        ):
            raise ValueError("ordinary USE Road mask shape differs")
        if road_relations is None:
            if self.road_relation_dim > 0:
                raise ValueError("ordinary Road relations are required")
            road_relations = candidate_features.new_zeros(
                (
                    candidate_features.shape[0],
                    candidate_features.shape[1],
                    candidate_features.shape[1],
                    0,
                )
            )
        encoded = self.candidate_encoder(candidate_features)
        encoded = self._apply_graph_blocks(
            encoded,
            candidate_mask,
            adjacency,
            road_relations,
        )
        return self._decode_encoded(
            object_features=object_features,
            candidate_features=candidate_features,
            candidate_mask=candidate_mask,
            encoded=encoded,
        )


class TargetAOrdinaryJointRoadGraphDecoder(
    TargetAOrdinaryUseRoadGraphDecoder
):
    """Joint KEEP/USE and complete Road-set graph decoder."""

    def __init__(
        self,
        *,
        object_feature_dim: int = 64,
        candidate_feature_dim: int = 40,
        hidden_dim: int = 128,
        context_dim: int = 192,
        graph_layers: int = 2,
        num_heads: int = 4,
        attention_scope: str = "ENDPOINT",
        road_relation_dim: int = 0,
        road_relation_attention_bias: bool = True,
        road_relation_graph_adjacency: bool = True,
        cardinality_count: int = 65,
        dropout: float = 0.1,
    ) -> None:
        super().__init__(
            object_feature_dim=object_feature_dim,
            candidate_feature_dim=candidate_feature_dim,
            hidden_dim=hidden_dim,
            context_dim=context_dim,
            graph_layers=graph_layers,
            num_heads=num_heads,
            attention_scope=attention_scope,
            road_relation_dim=road_relation_dim,
            road_relation_attention_bias=road_relation_attention_bias,
            road_relation_graph_adjacency=road_relation_graph_adjacency,
            cardinality_count=cardinality_count,
            dropout=dropout,
        )
        self.decision_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 2),
        )

    def forward(
        self,
        *,
        object_features: torch.Tensor,
        candidate_features: torch.Tensor,
        candidate_mask: torch.Tensor,
        adjacency: torch.Tensor,
        road_relations: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        outputs = super().forward(
            object_features=object_features,
            candidate_features=candidate_features,
            candidate_mask=candidate_mask,
            adjacency=adjacency,
            road_relations=road_relations,
        )
        outputs["decision_logits"] = self.decision_head(
            outputs["graph_context"]
        )
        return outputs


class TargetAOrdinaryAnchorRoadGraphDecoder(
    TargetAOrdinaryJointRoadGraphDecoder
):
    """Condition each Road on independently selected semantic anchors."""

    def __init__(
        self,
        *,
        object_feature_dim: int = 64,
        candidate_feature_dim: int = 40,
        anchor_feature_dim: int = 3,
        anchor_relation_dim: int = 4,
        hidden_dim: int = 128,
        context_dim: int = 192,
        graph_layers: int = 2,
        num_heads: int = 4,
        attention_scope: str = "ENDPOINT_THEN_FULL",
        road_relation_dim: int = 0,
        road_relation_attention_bias: bool = True,
        road_relation_graph_adjacency: bool = True,
        cardinality_count: int = 65,
        dropout: float = 0.1,
    ) -> None:
        super().__init__(
            object_feature_dim=object_feature_dim,
            candidate_feature_dim=candidate_feature_dim,
            hidden_dim=hidden_dim,
            context_dim=context_dim,
            graph_layers=graph_layers,
            num_heads=num_heads,
            attention_scope=attention_scope,
            road_relation_dim=road_relation_dim,
            road_relation_attention_bias=road_relation_attention_bias,
            road_relation_graph_adjacency=road_relation_graph_adjacency,
            cardinality_count=cardinality_count,
            dropout=dropout,
        )
        if min(anchor_feature_dim, anchor_relation_dim) < 1:
            raise ValueError("ordinary anchor-Road dimensions are invalid")
        self.anchor_feature_dim = anchor_feature_dim
        self.anchor_relation_dim = anchor_relation_dim
        self.anchor_encoder = nn.Sequential(
            nn.Linear(anchor_feature_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.anchor_relation_encoder = nn.Sequential(
            nn.Linear(anchor_relation_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.anchor_message = nn.Sequential(
            nn.Linear(hidden_dim * 3, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.anchor_road_fusion = nn.Sequential(
            nn.Linear(hidden_dim * 3, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )

    def forward(
        self,
        *,
        object_features: torch.Tensor,
        candidate_features: torch.Tensor,
        candidate_mask: torch.Tensor,
        adjacency: torch.Tensor,
        anchor_features: torch.Tensor,
        anchor_mask: torch.Tensor,
        anchor_relations: torch.Tensor,
        road_relations: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        if (
            anchor_features.ndim != 3
            or anchor_features.shape[-1] != self.anchor_feature_dim
        ):
            raise ValueError("ordinary anchor feature shape differs")
        if (
            anchor_mask.shape != anchor_features.shape[:2]
            or anchor_mask.dtype is not torch.bool
        ):
            raise ValueError("ordinary anchor mask shape differs")
        expected = (
            candidate_features.shape[0],
            candidate_features.shape[1],
            anchor_features.shape[1],
            self.anchor_relation_dim,
        )
        if anchor_relations.shape != expected:
            raise ValueError("ordinary anchor-Road relation shape differs")
        if road_relations is None:
            if self.road_relation_dim > 0:
                raise ValueError("ordinary Road relations are required")
            road_relations = candidate_features.new_zeros(
                (
                    candidate_features.shape[0],
                    candidate_features.shape[1],
                    candidate_features.shape[1],
                    0,
                )
            )
        encoded = self.candidate_encoder(candidate_features)
        anchor_encoded = self.anchor_encoder(anchor_features)
        relation_encoded = self.anchor_relation_encoder(anchor_relations)
        road_expanded = encoded.unsqueeze(2).expand(
            -1,
            -1,
            anchor_features.shape[1],
            -1,
        )
        anchor_expanded = anchor_encoded.unsqueeze(1).expand(
            -1,
            candidate_features.shape[1],
            -1,
            -1,
        )
        messages = self.anchor_message(
            torch.cat(
                (road_expanded, anchor_expanded, relation_encoded),
                dim=-1,
            )
        )
        relation_mask = (
            candidate_mask.unsqueeze(-1) & anchor_mask.unsqueeze(1)
        )
        mask_float = relation_mask.unsqueeze(-1).to(messages.dtype)
        mean = (messages * mask_float).sum(dim=2) / mask_float.sum(
            dim=2
        ).clamp_min(1.0)
        maximum = messages.masked_fill(
            ~relation_mask.unsqueeze(-1),
            torch.finfo(messages.dtype).min,
        ).max(dim=2).values
        maximum = torch.where(
            relation_mask.any(dim=2, keepdim=True),
            maximum,
            torch.zeros_like(maximum),
        )
        encoded = self.anchor_road_fusion(
            torch.cat((encoded, mean, maximum), dim=-1)
        )
        encoded = self._apply_graph_blocks(
            encoded,
            candidate_mask,
            adjacency,
            road_relations,
        )
        outputs = self._decode_encoded(
            object_features=object_features,
            candidate_features=candidate_features,
            candidate_mask=candidate_mask,
            encoded=encoded,
        )
        outputs["decision_logits"] = self.decision_head(
            outputs["graph_context"]
        )
        return outputs


class TargetAOrdinaryAnchorRoadRoleGraphDecoder(
    TargetAOrdinaryAnchorRoadGraphDecoder
):
    """Jointly decode Road membership, ownership, and business role."""

    def __init__(
        self,
        *,
        object_feature_dim: int = 64,
        candidate_feature_dim: int = 40,
        anchor_feature_dim: int = 3,
        anchor_relation_dim: int = 4,
        hidden_dim: int = 128,
        context_dim: int = 192,
        graph_layers: int = 2,
        num_heads: int = 4,
        attention_scope: str = "ENDPOINT_THEN_FULL",
        road_relation_dim: int = 0,
        road_relation_attention_bias: bool = True,
        road_relation_graph_adjacency: bool = True,
        cardinality_count: int = 65,
        ownership_count: int = 3,
        business_role_count: int = 4,
        fuse_business_into_membership: bool = True,
        component_edge_decoder: bool = False,
        dropout: float = 0.1,
    ) -> None:
        super().__init__(
            object_feature_dim=object_feature_dim,
            candidate_feature_dim=candidate_feature_dim,
            anchor_feature_dim=anchor_feature_dim,
            anchor_relation_dim=anchor_relation_dim,
            hidden_dim=hidden_dim,
            context_dim=context_dim,
            graph_layers=graph_layers,
            num_heads=num_heads,
            attention_scope=attention_scope,
            road_relation_dim=road_relation_dim,
            road_relation_attention_bias=road_relation_attention_bias,
            road_relation_graph_adjacency=road_relation_graph_adjacency,
            cardinality_count=cardinality_count,
            dropout=dropout,
        )
        if min(ownership_count, business_role_count) < 2:
            raise ValueError("ordinary Road business label counts are invalid")
        if component_edge_decoder and road_relation_dim < 1:
            raise ValueError(
                "ordinary component edge decoder needs Road relations"
            )
        self.ownership_count = ownership_count
        self.business_role_count = business_role_count
        self.fuse_business_into_membership = fuse_business_into_membership
        self.component_edge_decoder = component_edge_decoder
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
        self.member_business_fusion = nn.Sequential(
            nn.Linear(1 + ownership_count + business_role_count, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )
        self.component_candidate_projection = (
            nn.Sequential(
                nn.Linear(hidden_dim, hidden_dim),
                nn.GELU(),
                nn.LayerNorm(hidden_dim),
            )
            if component_edge_decoder
            else None
        )
        self.component_relation_head = (
            nn.Linear(road_relation_dim, 1, bias=False)
            if component_edge_decoder
            else None
        )
        self.component_edge_bias = (
            nn.Parameter(torch.zeros(()))
            if component_edge_decoder
            else None
        )
        self.component_member_fusion = (
            nn.Sequential(
                nn.Linear(3, hidden_dim),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim, 1),
            )
            if component_edge_decoder
            else None
        )
        if self.component_member_fusion is not None:
            nn.init.zeros_(self.component_member_fusion[-1].weight)
            nn.init.zeros_(self.component_member_fusion[-1].bias)

    def forward(
        self,
        *,
        object_features: torch.Tensor,
        candidate_features: torch.Tensor,
        candidate_mask: torch.Tensor,
        adjacency: torch.Tensor,
        anchor_features: torch.Tensor,
        anchor_mask: torch.Tensor,
        anchor_relations: torch.Tensor,
        road_relations: torch.Tensor | None = None,
        component_adjacency: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        outputs = super().forward(
            object_features=object_features,
            candidate_features=candidate_features,
            candidate_mask=candidate_mask,
            adjacency=adjacency,
            anchor_features=anchor_features,
            anchor_mask=anchor_mask,
            anchor_relations=anchor_relations,
            road_relations=road_relations,
        )
        expanded = outputs["graph_context"].unsqueeze(1).expand(
            -1,
            candidate_features.shape[1],
            -1,
        )
        business_inputs = torch.cat(
            (
                candidate_features,
                outputs["candidate_encoded"],
                expanded,
            ),
            dim=-1,
        )
        ownership_logits = self.ownership_head(business_inputs)
        business_role_logits = self.business_role_head(business_inputs)
        base_member_logits = outputs["member_logits"]
        fused = self.member_business_fusion(
            torch.cat(
                (
                    base_member_logits.unsqueeze(-1),
                    ownership_logits,
                    business_role_logits,
                ),
                dim=-1,
            )
        ).squeeze(-1)
        outputs["base_member_logits"] = base_member_logits
        outputs["member_logits"] = (
            base_member_logits + fused
            if self.fuse_business_into_membership
            else base_member_logits
        ).masked_fill(~candidate_mask, 0.0)
        outputs["ownership_logits"] = ownership_logits.masked_fill(
            ~candidate_mask.unsqueeze(-1),
            0.0,
        )
        outputs["business_role_logits"] = business_role_logits.masked_fill(
            ~candidate_mask.unsqueeze(-1),
            0.0,
        )
        if self.component_edge_decoder:
            if (
                road_relations is None
                or component_adjacency is None
                or component_adjacency.shape
                != (
                    candidate_features.shape[0],
                    candidate_features.shape[1],
                    candidate_features.shape[1],
                )
                or component_adjacency.dtype is not torch.bool
            ):
                raise ValueError(
                    "ordinary component edge inputs differ"
                )
            if (
                self.component_candidate_projection is None
                or self.component_relation_head is None
                or self.component_edge_bias is None
                or self.component_member_fusion is None
            ):
                raise RuntimeError(
                    "ordinary component edge decoder is incomplete"
                )
            projected = self.component_candidate_projection(
                outputs["candidate_encoded"]
            )
            component_edge_logits = (
                torch.matmul(projected, projected.transpose(1, 2))
                / float(projected.shape[-1]) ** 0.5
                + self.component_relation_head(road_relations).squeeze(-1)
                + self.component_edge_bias
            )
            component_edge_logits = component_edge_logits.masked_fill(
                ~component_adjacency,
                0.0,
            )
            edge_probabilities = torch.sigmoid(
                component_edge_logits
            ) * component_adjacency.to(component_edge_logits.dtype)
            edge_count = component_adjacency.sum(dim=-1)
            edge_mean = edge_probabilities.sum(dim=-1) / edge_count.clamp_min(
                1
            ).to(edge_probabilities.dtype)
            edge_maximum = edge_probabilities.max(dim=-1).values
            component_fused = self.component_member_fusion(
                torch.stack(
                    (outputs["member_logits"], edge_mean, edge_maximum),
                    dim=-1,
                )
            ).squeeze(-1)
            outputs["base_component_member_logits"] = outputs[
                "member_logits"
            ]
            outputs["member_logits"] = (
                outputs["member_logits"] + component_fused
            ).masked_fill(~candidate_mask, 0.0)
            outputs["component_edge_logits"] = component_edge_logits
        return outputs


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


__all__ = [
    "TargetAOrdinaryAnchorRoadGraphDecoder",
    "TargetAOrdinaryAnchorRoadRoleGraphDecoder",
    "TargetAOrdinaryJointRoadGraphDecoder",
    "TargetAOrdinaryRoadSetDecoder",
    "TargetAOrdinaryUseRoadGraphDecoder",
    "parameter_count",
]
