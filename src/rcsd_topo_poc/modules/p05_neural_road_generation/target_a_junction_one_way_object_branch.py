from __future__ import annotations

from typing import Mapping

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_evidence import (
    ANCHOR_MEMBER_INCIDENCE_DIM,
    ANCHOR_MEMBER_RELATION_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_data import (
    MAX_BREAKS_PER_ROAD,
    JunctionJointBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_RADIUS_M,
    GEOMETRY_ROLE_INDEX,
    GEOMETRY_TOKEN_DIM,
    MEMBER_FEATURE_DIM,
    OBJECT_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_structured_decoder import (
    JunctionStructuredSetDecoder,
)


class JunctionOneWayObjectBranch(nn.Module):
    """Independent object encoder conditioned by detached business-plan evidence."""

    def __init__(
        self,
        *,
        hidden_dim: int,
        num_heads: int,
        dropout: float,
        business_plan_count: int,
        cardinality_count: int,
        structured_max_steps: int,
    ) -> None:
        super().__init__()
        if hidden_dim < 64 or hidden_dim % num_heads:
            raise ValueError("one-way object hidden dimension must divide by heads")
        if business_plan_count < 2 or cardinality_count < 1:
            raise ValueError("one-way object output dimensions are invalid")
        self.cardinality_count = cardinality_count
        self.geometry_token_stem = _stem(GEOMETRY_TOKEN_DIM, hidden_dim, dropout)
        self.geometry_role_embedding = nn.Embedding(
            len(GEOMETRY_ROLE_INDEX), hidden_dim
        )
        self.geometry_encoder = _set_encoder(
            hidden_dim,
            num_heads,
            dropout,
            layers=2,
        )
        self.geometry_pool_score = nn.Linear(hidden_dim, 1)
        self.object_stem = _stem(OBJECT_FEATURE_DIM, hidden_dim, dropout)
        self.candidate_stem = _stem(OBJECT_FEATURE_DIM, hidden_dim, dropout)
        self.candidate_encoder = _set_encoder(
            hidden_dim,
            num_heads,
            dropout,
            layers=1,
        )
        self.candidate_pool_score = nn.Linear(hidden_dim, 1)
        self.member_stem = _stem(MEMBER_FEATURE_DIM, hidden_dim, dropout)
        self.member_encoder = _set_encoder(
            hidden_dim,
            num_heads,
            dropout,
            layers=1,
        )
        self.member_relation_stem = _stem(
            ANCHOR_MEMBER_RELATION_DIM,
            hidden_dim,
            dropout,
        )
        self.member_incidence_stem = _stem(
            ANCHOR_MEMBER_INCIDENCE_DIM,
            hidden_dim,
            dropout,
        )
        self.member_graph_blocks = nn.ModuleList(
            _ObjectGraphBlock(hidden_dim, dropout) for _ in range(2)
        )
        self.member_pool_score = nn.Linear(hidden_dim, 1)
        self.geometry_member_fusion = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.business_condition = nn.Sequential(
            nn.Linear(business_plan_count, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.context_fusion = nn.Sequential(
            nn.Linear(hidden_dim * 5, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.trunk = nn.ModuleList(
            _residual_block(hidden_dim, dropout) for _ in range(2)
        )
        self.object_score = _PairScore(hidden_dim)
        self.object_main_score = _PairScore(hidden_dim)
        self.member_score = _PairScore(hidden_dim)
        self.object_cardinality_head = _head(
            hidden_dim,
            cardinality_count,
            dropout,
        )
        self.object_role_cardinality_head = _head(
            hidden_dim,
            2 * cardinality_count,
            dropout,
        )
        self.structured_decoder = JunctionStructuredSetDecoder(
            hidden_dim,
            dropout=dropout,
            max_steps=structured_max_steps,
        )
        self.break_slot_embeddings = nn.Parameter(
            torch.empty(MAX_BREAKS_PER_ROAD, hidden_dim)
        )
        nn.init.normal_(self.break_slot_embeddings, std=0.02)
        self.break_decoder = nn.Sequential(
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.break_presence_head = nn.Linear(hidden_dim, 1)
        self.break_offset_head = nn.Linear(hidden_dim, 1)
        self.break_main_head = nn.Linear(hidden_dim, 1)
        nn.init.zeros_(self.break_offset_head.weight)
        nn.init.zeros_(self.break_offset_head.bias)

    def forward(
        self,
        batch: JunctionJointBatch,
        *,
        business_plan_logits: torch.Tensor,
        teacher_member_sets: torch.Tensor | None = None,
        teacher_member_set_mask: torch.Tensor | None = None,
        teacher_member_task_mask: torch.Tensor | None = None,
    ) -> Mapping[str, torch.Tensor]:
        geometry_tokens = self.geometry_token_stem(batch.geometry_tokens)
        geometry_objects = _pool_tokens_by_object(
            geometry_tokens,
            batch.geometry_token_mask,
            batch.geometry_token_object_index,
            batch.geometry_object_mask.shape[1],
        )
        geometry_objects = geometry_objects + self.geometry_role_embedding(
            batch.geometry_object_roles.clamp_min(0)
        )
        candidate_hidden = _encode_set(
            self.candidate_stem(batch.candidate_features),
            batch.candidate_mask,
            self.candidate_encoder,
        )
        member_hidden = self.member_stem(batch.member_features)
        relation_values = self.member_relation_stem(
            batch.member_relation_features
        )
        incidence_values = self.member_incidence_stem(
            batch.member_incidence_features
        )
        for block in self.member_graph_blocks:
            member_hidden = block(
                member_hidden,
                relation_values,
                batch.member_relation_mask,
                incidence_values,
                batch.member_incidence_mask,
                batch.member_mask,
            )
        member_hidden = _encode_set(
            member_hidden,
            batch.member_mask,
            self.member_encoder,
        )
        geometry_objects = self._fuse_geometry_members(
            geometry_objects,
            member_hidden,
            batch,
        )
        geometry_objects = _encode_set(
            geometry_objects,
            batch.geometry_object_mask,
            self.geometry_encoder,
        )
        business_context = self.business_condition(
            business_plan_logits.softmax(dim=-1).detach()
        )
        context = self.context_fusion(
            torch.cat(
                (
                    self.object_stem(batch.object_features),
                    _attention_pool(
                        geometry_objects,
                        batch.geometry_object_mask,
                        self.geometry_pool_score,
                    ),
                    _attention_pool(
                        candidate_hidden,
                        batch.candidate_mask,
                        self.candidate_pool_score,
                    ),
                    _attention_pool(
                        member_hidden,
                        batch.member_mask,
                        self.member_pool_score,
                    ),
                    business_context,
                ),
                dim=-1,
            )
        )
        for block in self.trunk:
            context = context + block(context)
        structured = self.structured_decoder.greedy_decode(
            member_hidden,
            batch.member_mask,
            context,
        )
        break_hidden = self.break_decoder(
            geometry_objects.unsqueeze(2)
            + context.unsqueeze(1).unsqueeze(2)
            + self.break_slot_embeddings.unsqueeze(0).unsqueeze(0)
        )
        break_offset_m = 50.0 * torch.tanh(
            self.break_offset_head(break_hidden).squeeze(-1)
        )
        break_fractions = (
            batch.geometry_object_anchor_projection_fraction.unsqueeze(-1)
            + break_offset_m
            / batch.geometry_object_length_m.clamp_min(1.0).unsqueeze(-1)
        ).clamp(0.0, 1.0)
        result = {
            "object_member_hidden": member_hidden,
            "object_decoder_context": context,
            "object_logits": self.object_score(geometry_objects, context),
            "object_main_logits": self.object_main_score(geometry_objects, context),
            "object_cardinality_logits": self.object_cardinality_head(context),
            "object_role_cardinality_logits": self.object_role_cardinality_head(
                context
            ).reshape(context.shape[0], 2, self.cardinality_count),
            "member_logits": self.member_score(member_hidden, context),
            "structured_member_prediction": structured.selected_members,
            "structured_member_stopped": structured.stopped,
            "structured_member_sequence_log_probability": (
                structured.sequence_log_probability
            ),
            "break_presence_logits": self.break_presence_head(
                break_hidden
            ).squeeze(-1),
            "break_fractions": break_fractions,
            "break_main_logits": self.break_main_head(break_hidden).squeeze(-1),
        }
        teacher_values = (
            teacher_member_sets,
            teacher_member_set_mask,
            teacher_member_task_mask,
        )
        if any(value is not None for value in teacher_values):
            if any(value is None for value in teacher_values):
                raise ValueError("one-way object teacher tensors are incomplete")
            result["structured_member_loss_by_row"] = (
                self.structured_decoder.teacher_forced_loss_by_row(
                    member_hidden,
                    batch.member_mask,
                    context,
                    teacher_member_sets,
                    teacher_member_set_mask,
                    teacher_member_task_mask,
                )
            )
        return result

    def _fuse_geometry_members(
        self,
        geometry_objects: torch.Tensor,
        member_hidden: torch.Tensor,
        batch: JunctionJointBatch,
    ) -> torch.Tensor:
        safe_index = batch.geometry_object_member_index.clamp_min(0)
        gathered = member_hidden.gather(
            1,
            safe_index.unsqueeze(-1).expand(-1, -1, member_hidden.shape[-1]),
        )
        fused = self.geometry_member_fusion(
            torch.cat((geometry_objects, gathered), dim=-1)
        )
        valid = (
            batch.geometry_object_member_index.ge(0)
            & batch.geometry_object_mask
        ).unsqueeze(-1)
        return torch.where(valid, fused, geometry_objects)


class _ObjectGraphBlock(nn.Module):
    def __init__(self, hidden_dim: int, dropout: float) -> None:
        super().__init__()
        self.neighbor = nn.Linear(hidden_dim, hidden_dim)
        self.message_norm = nn.LayerNorm(hidden_dim)
        self.update = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, hidden_dim),
            nn.Dropout(dropout),
        )
        self.output_norm = nn.LayerNorm(hidden_dim)

    def forward(
        self,
        members: torch.Tensor,
        relation_values: torch.Tensor,
        relation_mask: torch.Tensor,
        incidence_values: torch.Tensor,
        incidence_mask: torch.Tensor,
        member_mask: torch.Tensor,
    ) -> torch.Tensor:
        neighbor = self.neighbor(members).unsqueeze(1)
        relation_message = self.message_norm(
            torch.nn.functional.gelu(relation_values + neighbor)
        )
        incidence_message = self.message_norm(
            torch.nn.functional.gelu(incidence_values + neighbor)
        )
        relation_context = _masked_neighbor_mean(
            relation_message,
            relation_mask,
        )
        incidence_context = _masked_neighbor_mean(
            incidence_message,
            incidence_mask,
        )
        context = relation_context + incidence_context
        updated = self.output_norm(
            members + self.update(torch.cat((members, context), dim=-1))
        )
        return updated * member_mask.unsqueeze(-1).to(updated.dtype)


class _PairScore(nn.Module):
    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.score = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Linear(hidden_dim, 1),
        )

    def forward(self, values: torch.Tensor, context: torch.Tensor) -> torch.Tensor:
        expanded = context.unsqueeze(1).expand(-1, values.shape[1], -1)
        return self.score(torch.cat((values, expanded), dim=-1)).squeeze(-1)


def _stem(input_dim: int, hidden_dim: int, dropout: float) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
    )


def _head(input_dim: int, output_dim: int, dropout: float) -> nn.Sequential:
    return nn.Sequential(
        nn.LayerNorm(input_dim),
        nn.Dropout(dropout),
        nn.Linear(input_dim, input_dim),
        nn.GELU(),
        nn.Dropout(dropout),
        nn.Linear(input_dim, output_dim),
    )


def _set_encoder(
    hidden_dim: int,
    num_heads: int,
    dropout: float,
    *,
    layers: int,
) -> nn.TransformerEncoder:
    layer = nn.TransformerEncoderLayer(
        d_model=hidden_dim,
        nhead=num_heads,
        dim_feedforward=hidden_dim * 4,
        dropout=dropout,
        activation="gelu",
        batch_first=True,
        norm_first=True,
    )
    return nn.TransformerEncoder(
        layer,
        num_layers=layers,
        norm=nn.LayerNorm(hidden_dim),
        enable_nested_tensor=False,
    )


def _residual_block(hidden_dim: int, dropout: float) -> nn.Sequential:
    return nn.Sequential(
        nn.LayerNorm(hidden_dim),
        nn.Linear(hidden_dim, hidden_dim * 4),
        nn.GELU(),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim * 4, hidden_dim),
        nn.Dropout(dropout),
    )


def _encode_set(
    values: torch.Tensor,
    mask: torch.Tensor,
    encoder: nn.Module,
) -> torch.Tensor:
    encoded = encoder(values, src_key_padding_mask=~mask)
    return encoded * mask.unsqueeze(-1).to(encoded.dtype)


def _attention_pool(
    values: torch.Tensor,
    mask: torch.Tensor,
    scorer: nn.Module,
) -> torch.Tensor:
    scores = scorer(values).squeeze(-1).masked_fill(~mask, float("-inf"))
    weights = scores.softmax(dim=1)
    return (values * weights.unsqueeze(-1)).sum(dim=1)


def _pool_tokens_by_object(
    tokens: torch.Tensor,
    token_mask: torch.Tensor,
    token_object_index: torch.Tensor,
    object_count: int,
) -> torch.Tensor:
    safe_index = token_object_index.clamp_min(0)
    membership = torch.nn.functional.one_hot(
        safe_index,
        num_classes=object_count,
    ).to(tokens.dtype)
    membership = membership * token_mask.unsqueeze(-1).to(tokens.dtype)
    sums = torch.einsum("bth,bto->boh", tokens, membership)
    counts = membership.sum(dim=1).clamp_min(1.0).unsqueeze(-1)
    return sums / counts


def _masked_neighbor_mean(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    expanded = mask.unsqueeze(-1).to(values.dtype)
    degree = expanded.sum(dim=2).clamp_min(1.0)
    return (values * expanded).sum(dim=2) / degree


__all__ = ["JunctionOneWayObjectBranch"]
