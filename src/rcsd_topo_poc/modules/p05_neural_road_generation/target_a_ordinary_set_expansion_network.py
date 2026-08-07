from __future__ import annotations

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    TargetAOrdinaryAnchorRoadRoleGraphDecoder,
)


class TargetAOrdinarySetExpansionDecoder(
    TargetAOrdinaryAnchorRoadRoleGraphDecoder
):
    """Build a complete Road set one admissible next Road at a time."""

    def __init__(
        self,
        *,
        object_feature_dim: int = 64,
        candidate_feature_dim: int = 40,
        anchor_feature_dim: int = 3,
        anchor_relation_dim: int = 4,
        road_relation_dim: int = 13,
        hidden_dim: int = 128,
        context_dim: int = 192,
        graph_layers: int = 2,
        num_heads: int = 4,
        attention_scope: str = "ENDPOINT_THEN_FULL",
        cardinality_count: int = 67,
        component_action_decoder: bool = False,
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
            road_relation_attention_bias=False,
            road_relation_graph_adjacency=False,
            cardinality_count=cardinality_count,
            fuse_business_into_membership=False,
            component_edge_decoder=False,
            dropout=dropout,
        )
        if road_relation_dim < 1:
            raise ValueError("set expansion needs Road relation evidence")
        self.component_action_decoder = component_action_decoder
        expansion_input_dim = (
            hidden_dim * 4 + road_relation_dim * 2 + 4
        )
        stop_input_dim = hidden_dim * 3 + 3
        self.next_road_head = nn.Sequential(
            nn.Linear(expansion_input_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )
        self.stop_head = nn.Sequential(
            nn.Linear(stop_input_dim, context_dim),
            nn.GELU(),
            nn.LayerNorm(context_dim),
            nn.Dropout(dropout),
            nn.Linear(context_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )
        if component_action_decoder:
            action_input_dim = hidden_dim * 7 + 6
            self.component_action_head = nn.Sequential(
                nn.Linear(action_input_dim, context_dim),
                nn.GELU(),
                nn.LayerNorm(context_dim),
                nn.Dropout(dropout),
                nn.Linear(context_dim, hidden_dim),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dim, 3),
            )

    def decode_next(
        self,
        *,
        encoded_outputs: dict[str, torch.Tensor],
        candidate_mask: torch.Tensor,
        road_relations: torch.Tensor,
        selected_masks: torch.Tensor,
        access_seed_masks: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        """Score every unselected Road and STOP for one or more set states."""
        candidate_encoded = encoded_outputs["candidate_encoded"]
        graph_context = encoded_outputs["graph_context"]
        if selected_masks.ndim == 2:
            selected_masks = selected_masks.unsqueeze(1)
        expected = (
            candidate_encoded.shape[0],
            selected_masks.shape[1],
            candidate_encoded.shape[1],
        )
        if selected_masks.shape != expected or selected_masks.dtype is not torch.bool:
            raise ValueError("set expansion selected-mask shape differs")
        if candidate_mask.shape != candidate_encoded.shape[:2]:
            raise ValueError("set expansion candidate-mask shape differs")
        if road_relations.shape != (
            candidate_encoded.shape[0],
            candidate_encoded.shape[1],
            candidate_encoded.shape[1],
            self.road_relation_dim,
        ):
            raise ValueError("set expansion Road relation shape differs")
        selected_masks = selected_masks & candidate_mask.unsqueeze(1)
        selected_float = selected_masks.to(candidate_encoded.dtype)
        selected_count = selected_masks.sum(dim=-1)
        selected_mean = torch.einsum(
            "bsn,bnh->bsh",
            selected_float,
            candidate_encoded,
        ) / selected_count.clamp_min(1).unsqueeze(-1).to(
            candidate_encoded.dtype
        )
        minimum = torch.finfo(candidate_encoded.dtype).min
        selected_maximum = candidate_encoded.unsqueeze(1).masked_fill(
            ~selected_masks.unsqueeze(-1),
            minimum,
        ).max(dim=2).values
        selected_maximum = torch.where(
            selected_count.unsqueeze(-1) > 0,
            selected_maximum,
            torch.zeros_like(selected_maximum),
        )
        relation_exists = road_relations.abs().sum(dim=-1) > 1e-9
        relation_mask = (
            relation_exists.unsqueeze(1)
            & selected_masks.unsqueeze(2)
            & candidate_mask.unsqueeze(1).unsqueeze(-1)
        )
        relation_float = relation_mask.to(road_relations.dtype)
        relation_count = relation_mask.sum(dim=-1)
        relation_mean = torch.einsum(
            "bsij,bijr->bsir",
            relation_float,
            road_relations,
        ) / relation_count.clamp_min(1).unsqueeze(-1).to(
            road_relations.dtype
        )
        relation_maximum = road_relations.unsqueeze(1).masked_fill(
            ~relation_mask.unsqueeze(-1),
            minimum,
        ).max(dim=3).values
        relation_maximum = torch.where(
            relation_count.unsqueeze(-1) > 0,
            relation_maximum,
            torch.zeros_like(relation_maximum),
        )
        valid_count = candidate_mask.sum(dim=-1).clamp_min(1)
        count_features = torch.stack(
            (
                selected_count.to(candidate_encoded.dtype)
                / valid_count.unsqueeze(-1).to(candidate_encoded.dtype),
                torch.log1p(selected_count.to(candidate_encoded.dtype))
                / 4.219507705176107,
                (selected_count > 0).to(candidate_encoded.dtype),
            ),
            dim=-1,
        )
        relation_fraction = (
            relation_count.to(candidate_encoded.dtype)
            / selected_count.clamp_min(1)
            .unsqueeze(-1)
            .to(candidate_encoded.dtype)
        ).unsqueeze(-1)
        state_count = selected_masks.shape[1]
        candidate_count = candidate_encoded.shape[1]
        candidate_expanded = candidate_encoded.unsqueeze(1).expand(
            -1, state_count, -1, -1
        )
        graph_expanded = graph_context.unsqueeze(1).unsqueeze(2).expand(
            -1, state_count, candidate_count, -1
        )
        selected_mean_expanded = selected_mean.unsqueeze(2).expand(
            -1, -1, candidate_count, -1
        )
        selected_maximum_expanded = selected_maximum.unsqueeze(2).expand(
            -1, -1, candidate_count, -1
        )
        count_expanded = count_features.unsqueeze(2).expand(
            -1, -1, candidate_count, -1
        )
        next_logits = self.next_road_head(
            torch.cat(
                (
                    candidate_expanded,
                    graph_expanded,
                    selected_mean_expanded,
                    selected_maximum_expanded,
                    relation_mean,
                    relation_maximum,
                    count_expanded,
                    relation_fraction,
                ),
                dim=-1,
            )
        ).squeeze(-1)
        next_logits = next_logits.masked_fill(
            ~candidate_mask.unsqueeze(1) | selected_masks,
            torch.finfo(next_logits.dtype).min,
        )
        stop_logits = self.stop_head(
            torch.cat(
                (
                    graph_context.unsqueeze(1).expand(
                        -1, state_count, -1
                    ),
                    selected_mean,
                    selected_maximum,
                    count_features,
                ),
                dim=-1,
            )
        ).squeeze(-1)
        if not self.component_action_decoder:
            return {
                "next_road_logits": next_logits,
                "stop_logits": stop_logits,
                "selected_count": selected_count,
            }
        if access_seed_masks is None:
            access_seed_masks = torch.zeros_like(candidate_mask)
        if (
            access_seed_masks.shape != candidate_mask.shape
            or access_seed_masks.dtype is not torch.bool
        ):
            raise ValueError("set expansion access-seed shape differs")
        remaining = candidate_mask.unsqueeze(1) & ~selected_masks
        endpoint_relations = road_relations[..., 0] > 0.5
        frontier_masks = (
            endpoint_relations.unsqueeze(1)
            & selected_masks.unsqueeze(2)
        ).any(dim=-1) & remaining
        nonfrontier_masks = remaining & ~frontier_masks
        start_masks = nonfrontier_masks
        frontier_mean, frontier_maximum, frontier_count = (
            self._masked_candidate_pool(
                candidate_encoded,
                frontier_masks,
            )
        )
        start_mean, start_maximum, start_count = (
            self._masked_candidate_pool(
                candidate_encoded,
                start_masks,
            )
        )
        action_count_features = torch.stack(
            (
                selected_count.to(candidate_encoded.dtype)
                / valid_count.unsqueeze(-1).to(candidate_encoded.dtype),
                frontier_count.to(candidate_encoded.dtype)
                / valid_count.unsqueeze(-1).to(candidate_encoded.dtype),
                start_count.to(candidate_encoded.dtype)
                / valid_count.unsqueeze(-1).to(candidate_encoded.dtype),
                (selected_count > 0).to(candidate_encoded.dtype),
                (frontier_count > 0).to(candidate_encoded.dtype),
                (start_count > 0).to(candidate_encoded.dtype),
            ),
            dim=-1,
        )
        action_logits = self.component_action_head(
            torch.cat(
                (
                    graph_context.unsqueeze(1).expand(
                        -1, state_count, -1
                    ),
                    selected_mean,
                    selected_maximum,
                    frontier_mean,
                    frontier_maximum,
                    start_mean,
                    start_maximum,
                    action_count_features,
                ),
                dim=-1,
            )
        )
        action_logits = action_logits.clone()
        action_logits[..., 2] += stop_logits
        action_valid = torch.stack(
            (
                frontier_count > 0,
                start_count > 0,
                selected_count > 0,
            ),
            dim=-1,
        )
        action_logits = action_logits.masked_fill(
            ~action_valid,
            torch.finfo(action_logits.dtype).min,
        )
        action_log_probabilities = torch.log_softmax(
            action_logits,
            dim=-1,
        )
        structured_next_logits = torch.full_like(
            next_logits,
            torch.finfo(next_logits.dtype).min,
        )
        for action_index, action_mask in enumerate(
            (frontier_masks, start_masks)
        ):
            within_action = torch.log_softmax(
                next_logits.masked_fill(
                    ~action_mask,
                    torch.finfo(next_logits.dtype).min,
                ),
                dim=-1,
            )
            values = (
                within_action
                + action_log_probabilities[
                    ..., action_index
                ].unsqueeze(-1)
            )
            structured_next_logits = torch.where(
                action_mask,
                values,
                structured_next_logits,
            )
        return {
            "next_road_logits": structured_next_logits,
            "stop_logits": action_log_probabilities[..., 2],
            "selected_count": selected_count,
            "component_action_logits": action_logits,
            "component_action_log_probabilities": (
                action_log_probabilities
            ),
            "frontier_masks": frontier_masks,
            "start_masks": start_masks,
        }

    @staticmethod
    def _masked_candidate_pool(
        candidate_encoded: torch.Tensor,
        masks: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        counts = masks.sum(dim=-1)
        values = masks.to(candidate_encoded.dtype)
        means = torch.einsum(
            "bsn,bnh->bsh",
            values,
            candidate_encoded,
        ) / counts.clamp_min(1).unsqueeze(-1).to(
            candidate_encoded.dtype
        )
        maximums = candidate_encoded.unsqueeze(1).masked_fill(
            ~masks.unsqueeze(-1),
            torch.finfo(candidate_encoded.dtype).min,
        ).max(dim=2).values
        maximums = torch.where(
            counts.unsqueeze(-1) > 0,
            maximums,
            torch.zeros_like(maximums),
        )
        return means, maximums, counts


__all__ = ["TargetAOrdinarySetExpansionDecoder"]
