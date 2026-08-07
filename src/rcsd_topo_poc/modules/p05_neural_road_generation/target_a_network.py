from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_evidence import (
    ANCHOR_ARM_FEATURE_DIM,
    ANCHOR_MEMBER_LOCAL_FEATURE_DIM,
    ANCHOR_MEMBER_RELATION_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_members import (
    ANCHOR_CANDIDATE_ROAD_FEATURE_INDEX,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_relations import (
    ANCHOR_CANDIDATE_RELATION_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_arms import (
    ORDINARY_PLAN_ARM_COUNT,
    ORDINARY_PLAN_ARM_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_members import (
    ORDINARY_PLAN_MEMBER_FEATURE_DIM,
)

ANCHOR_TYPE_COUNT = 2
ANCHOR_TYPE_NODE = 0
ANCHOR_TYPE_ROAD = 1
ORDINARY_ANCHOR_CONDITION_DIM = 70
ORDINARY_DECISION_COUNT = 3
ORDINARY_DECISION_KEEP_SWSD = 0
ORDINARY_DECISION_USE_RCSD = 1
ORDINARY_DECISION_ABSTAIN = 2
ORDINARY_PLAN_MEMBER_HIDDEN_DIM = 64


@dataclass(frozen=True)
class TargetABatchTensors:
    object_features: torch.Tensor
    object_types: torch.Tensor
    object_mask: torch.Tensor
    adjacency: torch.Tensor
    anchor_object_indices: torch.Tensor
    anchor_candidate_features: torch.Tensor
    anchor_candidate_mask: torch.Tensor
    ordinary_object_indices: torch.Tensor
    ordinary_required_anchor_indices: torch.Tensor
    ordinary_plan_features: torch.Tensor
    ordinary_plan_mask: torch.Tensor
    advance_right_object_indices: torch.Tensor
    advance_right_source_indices: torch.Tensor
    advance_right_target_indices: torch.Tensor
    advance_right_plan_features: torch.Tensor
    advance_right_plan_mask: torch.Tensor
    teacher_anchor_candidate_indices: torch.Tensor | None = None
    teacher_anchor_success: torch.Tensor | None = None
    teacher_ordinary_plan_indices: torch.Tensor | None = None
    anchor_candidate_relations: torch.Tensor | None = None
    anchor_member_features: torch.Tensor | None = None
    anchor_member_mask: torch.Tensor | None = None
    anchor_member_is_road: torch.Tensor | None = None
    anchor_candidate_membership: torch.Tensor | None = None
    anchor_swsd_arm_features: torch.Tensor | None = None
    anchor_swsd_arm_mask: torch.Tensor | None = None
    anchor_member_arm_features: torch.Tensor | None = None
    anchor_member_arm_mask: torch.Tensor | None = None
    anchor_member_local_features: torch.Tensor | None = None
    anchor_member_relation_features: torch.Tensor | None = None
    anchor_member_relation_mask: torch.Tensor | None = None
    ordinary_anchor_condition_features: torch.Tensor | None = None
    ordinary_plan_decision_indices: torch.Tensor | None = None
    ordinary_plan_member_features: torch.Tensor | None = None
    ordinary_plan_member_mask: torch.Tensor | None = None
    ordinary_plan_arm_features: torch.Tensor | None = None
    ordinary_plan_arm_mask: torch.Tensor | None = None


class MaskedGraphBlock(nn.Module):
    def __init__(self, config: TargetAConfig) -> None:
        super().__init__()
        self.num_heads = config.num_heads
        self.attention = nn.MultiheadAttention(
            config.hidden_dim,
            config.num_heads,
            dropout=config.dropout,
            batch_first=True,
        )
        self.norm1 = nn.LayerNorm(config.hidden_dim)
        self.norm2 = nn.LayerNorm(config.hidden_dim)
        self.feedforward = nn.Sequential(
            nn.Linear(config.hidden_dim, config.feedforward_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.feedforward_dim, config.hidden_dim),
            nn.Dropout(config.dropout),
        )

    def forward(
        self,
        values: torch.Tensor,
        object_mask: torch.Tensor,
        adjacency: torch.Tensor,
    ) -> torch.Tensor:
        batch, object_count, _ = values.shape
        if adjacency.shape != (batch, object_count, object_count):
            raise ValueError("Target A adjacency shape differs")
        diagonal = torch.eye(
            object_count,
            dtype=torch.bool,
            device=values.device,
        ).unsqueeze(0)
        allowed = adjacency | diagonal
        blocked = ~allowed
        blocked = blocked.unsqueeze(1).expand(
            batch,
            self.num_heads,
            object_count,
            object_count,
        )
        blocked = blocked.reshape(batch * self.num_heads, object_count, object_count)
        attended, _ = self.attention(
            values,
            values,
            values,
            attn_mask=blocked,
            need_weights=False,
        )
        values = self.norm1(values + attended)
        values = self.norm2(values + self.feedforward(values))
        return values * object_mask.unsqueeze(-1).to(values.dtype)


class CandidateSetEncoder(nn.Module):
    def __init__(self, config: TargetAConfig, feature_stem: nn.Module) -> None:
        super().__init__()
        self.feature_dim = config.feature_dim
        self.feature_stem = feature_stem
        layer = nn.TransformerEncoderLayer(
            d_model=config.hidden_dim,
            nhead=config.num_heads,
            dim_feedforward=config.feedforward_dim,
            dropout=config.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.encoder = nn.TransformerEncoder(
            layer,
            num_layers=config.set_layers,
            enable_nested_tensor=False,
        )
        self.norm = nn.LayerNorm(config.hidden_dim)

    def forward(
        self,
        features: torch.Tensor,
        mask: torch.Tensor,
    ) -> torch.Tensor:
        if features.ndim != 4 or features.shape[-1] != self.feature_dim:
            raise ValueError("Target A candidate feature shape differs")
        if mask.shape != features.shape[:3] or mask.dtype is not torch.bool:
            raise ValueError("Target A candidate mask shape or dtype differs")
        batch, group_count, candidate_count, _ = features.shape
        flat_features = features.reshape(
            batch * group_count,
            candidate_count,
            self.feature_dim,
        )
        flat_mask = mask.reshape(batch * group_count, candidate_count)
        safe_mask = flat_mask.clone()
        empty = ~safe_mask.any(dim=1)
        if bool(empty.any()):
            safe_mask[empty, 0] = True
        encoded = self.feature_stem(flat_features)
        encoded = self.encoder(encoded, src_key_padding_mask=~safe_mask)
        encoded = self.norm(encoded)
        encoded = encoded * flat_mask.unsqueeze(-1).to(encoded.dtype)
        return encoded.reshape(
            batch,
            group_count,
            candidate_count,
            encoded.shape[-1],
        )


class TargetAJointNetwork(nn.Module):
    """Shared encoder with locked anchor, ordinary, and conditional AR stages."""

    def __init__(self, config: TargetAConfig) -> None:
        super().__init__()
        config.validate()
        self.config = config
        self.object_stem = nn.Sequential(
            nn.Linear(config.feature_dim, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
            nn.Linear(config.hidden_dim, config.hidden_dim),
            nn.GELU(),
        )
        self.candidate_stem = nn.Sequential(
            nn.Linear(config.feature_dim, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
            nn.Linear(config.hidden_dim, config.hidden_dim),
            nn.GELU(),
        )
        self.object_type_embedding = nn.Embedding(8, config.hidden_dim)
        self.graph_blocks = nn.ModuleList(
            MaskedGraphBlock(config) for _ in range(config.graph_layers)
        )
        self.candidate_set_encoder = CandidateSetEncoder(
            config,
            self.candidate_stem,
        )
        self.anchor_candidate_pool = nn.Linear(config.hidden_dim, 1)
        self.anchor_candidate_fusion = nn.Sequential(
            nn.Linear(config.hidden_dim * 2, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        if config.anchor_structural_evidence_encoder:
            self.anchor_arm_stem = nn.Sequential(
                nn.Linear(ANCHOR_ARM_FEATURE_DIM, config.hidden_dim),
                nn.GELU(),
                nn.LayerNorm(config.hidden_dim),
            )
            self.anchor_arm_match_fusion = nn.Sequential(
                nn.Linear(config.hidden_dim * 4, config.hidden_dim),
                nn.GELU(),
                nn.LayerNorm(config.hidden_dim),
            )
            self.anchor_member_relation_stem = nn.Sequential(
                nn.Linear(
                    ANCHOR_MEMBER_RELATION_DIM,
                    config.hidden_dim,
                ),
                nn.GELU(),
                nn.LayerNorm(config.hidden_dim),
            )
            self.anchor_member_local_stem = (
                nn.Sequential(
                    nn.Linear(
                        ANCHOR_MEMBER_LOCAL_FEATURE_DIM,
                        config.hidden_dim,
                    ),
                    nn.GELU(),
                    nn.LayerNorm(config.hidden_dim),
                )
                if config.anchor_structural_member_local_encoder
                else None
            )
            self.anchor_member_evidence_fusion = nn.Sequential(
                nn.Linear(config.hidden_dim * 2, config.hidden_dim),
                nn.GELU(),
                nn.LayerNorm(config.hidden_dim),
            )
            self.anchor_candidate_evidence_fusion = (
                nn.Sequential(
                    nn.Linear(config.hidden_dim * 2, config.hidden_dim),
                    nn.GELU(),
                    nn.LayerNorm(config.hidden_dim),
                )
                if config.anchor_structural_candidate_context_fusion
                else None
            )
        else:
            self.anchor_arm_stem = None
            self.anchor_arm_match_fusion = None
            self.anchor_member_relation_stem = None
            self.anchor_member_local_stem = None
            self.anchor_member_evidence_fusion = None
            self.anchor_candidate_evidence_fusion = None

        if config.hierarchical_anchor_decoder:
            anchor_status_input_dim = config.hidden_dim * 4
            self.anchor_type_head = (
                None
                if (
                    config.anchor_raw_evidence_type_decoder
                    or config.anchor_raw_evidence_candidate_decoder
                )
                else self._head(
                    config.hidden_dim * 3,
                    ANCHOR_TYPE_COUNT,
                )
            )
            self.anchor_raw_evidence_type_head = (
                self._head(
                    config.feature_dim * 7 + ANCHOR_TYPE_COUNT,
                    ANCHOR_TYPE_COUNT,
                )
                if config.anchor_raw_evidence_type_decoder
                else None
            )
            self.anchor_raw_evidence_candidate_head = (
                self._candidate_head(
                    config.feature_dim * 2 + ANCHOR_TYPE_COUNT
                )
                if config.anchor_raw_evidence_candidate_decoder
                else None
            )
            self.anchor_type_embedding = nn.Embedding(
                ANCHOR_TYPE_COUNT,
                config.hidden_dim,
            )
            if config.cardinality_conditioned_anchor_decoder:
                self.anchor_node_cardinality_head = self._head(
                    config.hidden_dim * 2,
                    config.anchor_cardinality_count,
                )
                self.anchor_road_cardinality_head = self._head(
                    config.hidden_dim * 2,
                    config.anchor_cardinality_count,
                )
            else:
                self.anchor_node_cardinality_head = None
                self.anchor_road_cardinality_head = None
            anchor_candidate_input_dim = config.hidden_dim * 3
        else:
            anchor_status_input_dim = config.hidden_dim * (
                3 if config.anchor_status_use_selected_candidate else 2
            )
            self.anchor_type_head = None
            self.anchor_raw_evidence_type_head = None
            self.anchor_raw_evidence_candidate_head = None
            self.anchor_type_embedding = None
            self.anchor_node_cardinality_head = None
            self.anchor_road_cardinality_head = None
            anchor_candidate_input_dim = config.hidden_dim * 2
        if config.structured_anchor_object_decoder:
            self.anchor_relation_stem = nn.Sequential(
                nn.Linear(
                    ANCHOR_CANDIDATE_RELATION_DIM,
                    config.hidden_dim,
                ),
                nn.GELU(),
                nn.LayerNorm(config.hidden_dim),
            )
            self.anchor_relation_score = nn.Linear(config.hidden_dim, 1)
            anchor_candidate_input_dim += config.hidden_dim
        else:
            self.anchor_relation_stem = None
            self.anchor_relation_score = None
        self.anchor_status_head = self._head(
            anchor_status_input_dim,
            config.anchor_status_count,
        )
        self.anchor_gate_head = (
            self._head(anchor_status_input_dim, 2)
            if config.learned_anchor_gate
            else None
        )
        if config.compositional_anchor_object_decoder:
            self.anchor_candidate_head = None
            self.anchor_node_member_head = self._head(
                config.hidden_dim * 2,
                1,
            )
            self.anchor_road_member_head = self._head(
                config.hidden_dim * 2,
                1,
            )
            if config.compositional_anchor_candidate_residual:
                self.anchor_compositional_candidate_head = self._head(
                    config.hidden_dim
                    * (
                        4
                        if config.anchor_structural_candidate_residual_context
                        else 3
                    ),
                    1,
                )
                self.anchor_composition_scale = nn.Parameter(
                    torch.tensor(0.5413248546)
                )
            else:
                self.anchor_compositional_candidate_head = None
                self.anchor_composition_scale = None
        else:
            self.anchor_candidate_head = self._candidate_head(
                anchor_candidate_input_dim
            )
            self.anchor_node_member_head = None
            self.anchor_road_member_head = None
            self.anchor_compositional_candidate_head = None
            self.anchor_composition_scale = None
        self.ordinary_anchor_condition_stem = (
            nn.Sequential(
                nn.Linear(
                    ORDINARY_ANCHOR_CONDITION_DIM,
                    config.hidden_dim,
                ),
                nn.GELU(),
                nn.LayerNorm(config.hidden_dim),
            )
            if config.ordinary_oof_anchor_condition_encoder
            else None
        )
        self.ordinary_plan_head = self._candidate_head(config.hidden_dim * 3)
        self.ordinary_plan_validity_head = (
            self._candidate_head(config.hidden_dim * 3)
            if config.separate_ordinary_candidate_validity_head
            else None
        )
        self.ordinary_plan_member_stem = (
            nn.Sequential(
                nn.Linear(
                    ORDINARY_PLAN_MEMBER_FEATURE_DIM,
                    ORDINARY_PLAN_MEMBER_HIDDEN_DIM,
                ),
                nn.GELU(),
                nn.LayerNorm(ORDINARY_PLAN_MEMBER_HIDDEN_DIM),
                nn.Linear(
                    ORDINARY_PLAN_MEMBER_HIDDEN_DIM,
                    ORDINARY_PLAN_MEMBER_HIDDEN_DIM,
                ),
                nn.GELU(),
            )
            if config.ordinary_plan_member_encoder
            else None
        )
        self.ordinary_plan_member_fusion = (
            nn.Sequential(
                nn.Linear(
                    config.hidden_dim
                    + 2 * ORDINARY_PLAN_MEMBER_HIDDEN_DIM,
                    config.hidden_dim,
                ),
                nn.GELU(),
                nn.LayerNorm(config.hidden_dim),
            )
            if config.ordinary_plan_member_encoder
            else None
        )
        self.ordinary_plan_arm_projection = (
            nn.Sequential(
                nn.Linear(
                    ORDINARY_PLAN_ARM_COUNT * ORDINARY_PLAN_ARM_FEATURE_DIM,
                    64,
                ),
                nn.GELU(),
                nn.LayerNorm(64),
                nn.Linear(64, config.hidden_dim),
            )
            if config.ordinary_plan_arm_encoder
            else None
        )
        self.ordinary_decision_head = (
            self._candidate_head(config.hidden_dim * 3)
            if config.hierarchical_ordinary_plan_decoder
            else None
        )
        self.ordinary_decision_validity_head = (
            self._candidate_head(config.hidden_dim * 3)
            if config.separate_ordinary_decision_validity_head
            else None
        )
        self.clue_head = self._head(config.hidden_dim * 2, config.clue_class_count)
        self.fallback_scope_head = self._head(
            config.hidden_dim * 2,
            config.fallback_scope_count,
        )
        self.advance_right_plan_head = self._candidate_head(config.hidden_dim * 4)
        self.output_norm = nn.LayerNorm(config.hidden_dim)

    def _head(self, input_dim: int, output_dim: int) -> nn.Sequential:
        return nn.Sequential(
            nn.Linear(input_dim, self.config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(self.config.hidden_dim),
            nn.Dropout(self.config.dropout),
            nn.Linear(self.config.hidden_dim, output_dim),
        )

    def _candidate_head(self, input_dim: int) -> nn.Sequential:
        return nn.Sequential(
            nn.Linear(input_dim, self.config.feedforward_dim),
            nn.GELU(),
            nn.LayerNorm(self.config.feedforward_dim),
            nn.Dropout(self.config.dropout),
            nn.Linear(self.config.feedforward_dim, self.config.hidden_dim),
            nn.GELU(),
            nn.Dropout(self.config.dropout),
            nn.Linear(self.config.hidden_dim, 1),
        )

    def encode_objects(
        self,
        batch: TargetABatchTensors,
        anchor_candidate_context: torch.Tensor | None = None,
    ) -> torch.Tensor:
        self._validate_batch(batch)
        values = self.object_stem(batch.object_features)
        values = values + self.object_type_embedding(batch.object_types)
        values = values * batch.object_mask.unsqueeze(-1).to(values.dtype)
        if anchor_candidate_context is not None:
            anchor_values = _batched_gather(
                values,
                batch.anchor_object_indices,
            )
            fused = self.anchor_candidate_fusion(
                torch.cat((anchor_values, anchor_candidate_context), dim=-1)
            )
            values = values + _scatter_group_context(
                fused,
                batch.anchor_object_indices,
                object_count=values.shape[1],
            )
        for block in self.graph_blocks:
            values = block(values, batch.object_mask, batch.adjacency)
        return self.output_norm(values)

    def forward(self, batch: TargetABatchTensors) -> dict[str, torch.Tensor]:
        anchor_candidates = self.candidate_set_encoder(
            batch.anchor_candidate_features,
            batch.anchor_candidate_mask,
        )
        anchor_member_structural_context: torch.Tensor | None = None
        anchor_candidate_structural_context: torch.Tensor | None = None
        if self.config.anchor_structural_evidence_encoder:
            (
                anchor_candidate_structural_context,
                anchor_member_structural_context,
            ) = self._anchor_structural_context(batch)
            if self.config.anchor_structural_candidate_context_fusion:
                if self.anchor_candidate_evidence_fusion is None:
                    raise RuntimeError(
                        "anchor candidate evidence fusion is missing"
                    )
                anchor_candidates = (
                    anchor_candidates
                    + self.anchor_candidate_evidence_fusion(
                        torch.cat(
                            (
                                anchor_candidates,
                                anchor_candidate_structural_context,
                            ),
                            dim=-1,
                        )
                    )
                )
        anchor_pool_logits = self.anchor_candidate_pool(
            anchor_candidates
        ).squeeze(-1)
        anchor_pool_logits = anchor_pool_logits.masked_fill(
            ~batch.anchor_candidate_mask,
            torch.finfo(anchor_pool_logits.dtype).min,
        )
        anchor_pool_weights = torch.softmax(anchor_pool_logits, dim=-1)
        anchor_candidate_context = (
            anchor_candidates * anchor_pool_weights.unsqueeze(-1)
        ).sum(dim=2)
        candidate_type_masks = anchor_candidate_type_masks(batch)
        node_candidate_context = _masked_candidate_pool(
            anchor_candidates,
            anchor_pool_logits,
            candidate_type_masks[..., ANCHOR_TYPE_NODE],
        )
        road_candidate_context = _masked_candidate_pool(
            anchor_candidates,
            anchor_pool_logits,
            candidate_type_masks[..., ANCHOR_TYPE_ROAD],
        )
        objects = self.encode_objects(
            batch,
            anchor_candidate_context=anchor_candidate_context,
        )
        anchor_objects = _batched_gather(objects, batch.anchor_object_indices)
        anchor_member_logits: torch.Tensor | None = None
        anchor_composition_logits: torch.Tensor | None = None
        if self.config.anchor_raw_evidence_candidate_decoder:
            anchor_candidate_logits = self._raw_anchor_candidate_logits(
                batch,
                candidate_type_masks,
            )
        elif self.config.compositional_anchor_object_decoder:
            (
                anchor_member_logits,
                anchor_composition_logits,
                anchor_candidate_logits,
            ) = (
                self._compositional_anchor_logits(
                    anchor_objects,
                    anchor_candidates,
                    batch,
                    anchor_member_structural_context,
                    anchor_candidate_structural_context,
                )
            )
        else:
            if self.anchor_candidate_head is None:
                raise RuntimeError("anchor candidate head is missing")
            anchor_expanded = anchor_objects.unsqueeze(2).expand_as(
                anchor_candidates
            )
            anchor_candidate_parts = [anchor_expanded, anchor_candidates]
            if self.config.hierarchical_anchor_decoder:
                if self.anchor_type_embedding is None:
                    raise RuntimeError(
                        "hierarchical anchor type embedding is missing"
                    )
                candidate_type_indices = candidate_type_masks[
                    ..., ANCHOR_TYPE_ROAD
                ].long()
                anchor_candidate_parts.append(
                    self.anchor_type_embedding(candidate_type_indices)
                )
            if self.config.structured_anchor_object_decoder:
                anchor_candidate_parts.append(
                    self._anchor_relation_context(
                        anchor_candidates,
                        candidate_type_masks,
                        batch,
                    )
                )
            anchor_candidate_logits = self.anchor_candidate_head(
                torch.cat(anchor_candidate_parts, dim=-1)
            ).squeeze(-1)
            anchor_candidate_logits = anchor_candidate_logits.masked_fill(
                ~batch.anchor_candidate_mask,
                float("-inf"),
            )
        anchor_type_logits: torch.Tensor | None = None
        anchor_cardinality_logits: torch.Tensor | None = None
        if self.config.hierarchical_anchor_decoder:
            if self.config.anchor_raw_evidence_candidate_decoder:
                anchor_type_logits = _candidate_type_logmeanexp(
                    anchor_candidate_logits,
                    candidate_type_masks,
                )
            elif self.config.anchor_raw_evidence_type_decoder:
                anchor_type_logits = self._raw_anchor_type_logits(
                    batch,
                    candidate_type_masks,
                )
            else:
                if self.anchor_type_head is None:
                    raise RuntimeError(
                        "hierarchical anchor type head is missing"
                    )
                anchor_type_logits = self.anchor_type_head(
                    torch.cat(
                        (
                            anchor_objects,
                            node_candidate_context,
                            road_candidate_context,
                        ),
                        dim=-1,
                    )
                )
            valid_types = candidate_type_masks.any(dim=2)
            anchor_type_logits = anchor_type_logits.masked_fill(
                ~valid_types,
                float("-inf"),
            )
            if self.config.cardinality_conditioned_anchor_decoder:
                if (
                    self.anchor_node_cardinality_head is None
                    or self.anchor_road_cardinality_head is None
                ):
                    raise RuntimeError(
                        "anchor cardinality heads are missing"
                    )
                node_cardinality_logits = (
                    self.anchor_node_cardinality_head(
                        torch.cat(
                            (anchor_objects, node_candidate_context),
                            dim=-1,
                        )
                    )
                )
                road_cardinality_logits = (
                    self.anchor_road_cardinality_head(
                        torch.cat(
                            (anchor_objects, road_candidate_context),
                            dim=-1,
                        )
                    )
                )
                anchor_cardinality_logits = torch.stack(
                    (
                        node_cardinality_logits,
                        road_cardinality_logits,
                    ),
                    dim=2,
                )
                cardinality_masks = anchor_candidate_cardinality_masks(
                    batch,
                    self.config.anchor_cardinality_count,
                )
                valid_cardinalities = (
                    candidate_type_masks.unsqueeze(-1)
                    & cardinality_masks.unsqueeze(-2)
                ).any(dim=2)
                if self.config.compositional_anchor_object_decoder:
                    valid_cardinalities |= (
                        anchor_member_cardinality_valid_masks(
                            batch,
                            self.config.anchor_cardinality_count,
                        )
                    )
                anchor_cardinality_logits = (
                    anchor_cardinality_logits.masked_fill(
                        ~valid_cardinalities,
                        float("-inf"),
                    )
                )
                if not self.config.anchor_cardinality_hard_lock:
                    anchor_candidate_logits = (
                        anchor_candidate_logits
                        + self.config.anchor_cardinality_prior_weight
                        * anchor_cardinality_candidate_log_prior(
                            anchor_cardinality_logits,
                            batch,
                        )
                    )
            anchor_status_parts = [
                anchor_objects,
                anchor_candidate_context,
                node_candidate_context,
                road_candidate_context,
            ]
        else:
            anchor_status_parts = [anchor_objects, anchor_candidate_context]
        if (
            not self.config.hierarchical_anchor_decoder
            and self.config.anchor_status_use_selected_candidate
        ):
            candidate_weights = torch.softmax(
                anchor_candidate_logits,
                dim=-1,
            )
            selected_candidate_context = (
                anchor_candidates * candidate_weights.unsqueeze(-1)
            ).sum(dim=2)
            anchor_status_parts.append(selected_candidate_context)
        anchor_status_input = torch.cat(anchor_status_parts, dim=-1)
        anchor_status_logits = self.anchor_status_head(anchor_status_input)
        anchor_gate_logits = (
            self.anchor_gate_head(anchor_status_input)
            if self.anchor_gate_head is not None
            else None
        )
        (
            locked_anchor,
            anchor_selected_candidate_indices,
            anchor_selection_success,
        ) = self._lock_anchor(
            anchor_candidates,
            anchor_status_logits,
            anchor_gate_logits,
            anchor_candidate_logits,
            anchor_type_logits,
            (
                anchor_cardinality_logits
                if self.config.anchor_cardinality_hard_lock
                else None
            ),
            batch,
        )

        ordinary_objects = _batched_gather(objects, batch.ordinary_object_indices)
        ordinary_anchor_context = _indexed_mean(
            locked_anchor,
            batch.ordinary_required_anchor_indices,
        )
        if self.config.ordinary_oof_anchor_condition_encoder:
            if (
                self.ordinary_anchor_condition_stem is None
                or batch.ordinary_anchor_condition_features is None
            ):
                raise RuntimeError(
                    "ordinary OOF anchor conditioning tensors are missing"
                )
            ordinary_anchor_context = (
                ordinary_anchor_context
                + self.ordinary_anchor_condition_stem(
                    batch.ordinary_anchor_condition_features
                )
            )
        ordinary_base_plans = self.candidate_set_encoder(
            batch.ordinary_plan_features,
            batch.ordinary_plan_mask,
        )
        ordinary_plans = ordinary_base_plans
        if self.config.ordinary_plan_member_encoder:
            if (
                self.ordinary_plan_member_stem is None
                or self.ordinary_plan_member_fusion is None
                or batch.ordinary_plan_member_features is None
                or batch.ordinary_plan_member_mask is None
            ):
                raise RuntimeError(
                    "ordinary plan member evidence tensors are missing"
                )
            ordinary_member_context = ordinary_plan_member_context(
                self.ordinary_plan_member_stem(
                    batch.ordinary_plan_member_features
                ),
                batch.ordinary_plan_member_mask,
            )
            ordinary_plans = (
                ordinary_plans
                + self.ordinary_plan_member_fusion(
                    torch.cat(
                        (ordinary_plans, ordinary_member_context),
                        dim=-1,
                    )
                )
            )
        ordinary_decision_plans = (
            ordinary_base_plans
            if self.config.ordinary_plan_member_within_decision_only
            else ordinary_plans
        )
        if self.config.ordinary_plan_arm_encoder:
            if (
                self.ordinary_plan_arm_projection is None
                or batch.ordinary_plan_arm_features is None
                or batch.ordinary_plan_arm_mask is None
            ):
                raise RuntimeError(
                    "ordinary plan arm evidence tensors are missing"
                )
            arm_mask = batch.ordinary_plan_arm_mask.unsqueeze(-1)
            arm_mask_values = arm_mask.to(
                batch.ordinary_plan_arm_features.dtype
            )
            arm_mean = (
                (
                    batch.ordinary_plan_arm_features
                    * arm_mask_values
                ).sum(dim=-2)
                / arm_mask_values.sum(dim=-2).clamp_min(1.0)
            )
            arm_max = batch.ordinary_plan_arm_features.masked_fill(
                ~arm_mask,
                torch.finfo(
                    batch.ordinary_plan_arm_features.dtype
                ).min,
            ).amax(dim=-2)
            arm_max = torch.where(
                batch.ordinary_plan_arm_mask.any(dim=-1).unsqueeze(-1),
                arm_max,
                torch.zeros_like(arm_max),
            )
            arm_context = self.ordinary_plan_arm_projection(
                torch.cat((arm_mean, arm_max), dim=-1)
            )
            ordinary_plans = ordinary_plans + arm_context
            ordinary_decision_plans = ordinary_decision_plans + arm_context
        ordinary_context = torch.cat(
            (ordinary_objects, ordinary_anchor_context),
            dim=-1,
        )
        ordinary_expanded = ordinary_context.unsqueeze(2).expand(
            -1,
            -1,
            ordinary_plans.shape[2],
            -1,
        )
        ordinary_plan_inputs = torch.cat(
            (ordinary_expanded, ordinary_plans),
            dim=-1,
        )
        ordinary_bundle_logits = self.ordinary_plan_head(
            ordinary_plan_inputs
        ).squeeze(-1)
        ordinary_bundle_logits = ordinary_bundle_logits.masked_fill(
            ~batch.ordinary_plan_mask,
            float("-inf"),
        )
        ordinary_plan_validity_logits: torch.Tensor | None = None
        if self.ordinary_plan_validity_head is not None:
            ordinary_plan_validity_logits = (
                self.ordinary_plan_validity_head(
                    ordinary_plan_inputs
                ).squeeze(-1)
            )
            ordinary_plan_validity_logits = (
                ordinary_plan_validity_logits.masked_fill(
                    ~batch.ordinary_plan_mask,
                    float("-inf"),
                )
        )
        ordinary_decision_logits: torch.Tensor | None = None
        ordinary_decision_validity_logits: torch.Tensor | None = None
        if self.config.hierarchical_ordinary_plan_decoder:
            if self.ordinary_decision_head is None:
                raise RuntimeError("ordinary decision head is missing")
            decision_masks = ordinary_plan_decision_masks(batch)
            decision_contexts = ordinary_decision_contexts(
                ordinary_decision_plans,
                decision_masks,
            )
            decision_base = ordinary_context.unsqueeze(2).expand(
                -1,
                -1,
                ORDINARY_DECISION_COUNT,
                -1,
            )
            ordinary_decision_inputs = torch.cat(
                (decision_base, decision_contexts),
                dim=-1,
            )
            ordinary_decision_logits = self.ordinary_decision_head(
                ordinary_decision_inputs
            ).squeeze(-1)
            ordinary_decision_logits = ordinary_decision_logits.masked_fill(
                ~decision_masks.any(dim=2),
                float("-inf"),
            )
            if self.ordinary_decision_validity_head is not None:
                ordinary_decision_validity_logits = (
                    self.ordinary_decision_validity_head(
                        ordinary_decision_inputs
                    ).squeeze(-1)
                )
                ordinary_decision_validity_logits = (
                    ordinary_decision_validity_logits.masked_fill(
                        ~decision_masks.any(dim=2),
                        float("-inf"),
                    )
                )
            ordinary_plan_logits = hierarchical_ordinary_plan_logits(
                ordinary_bundle_logits,
                ordinary_decision_logits,
                batch,
            )
        else:
            ordinary_plan_logits = ordinary_bundle_logits
        clue_logits = self.clue_head(ordinary_context)
        fallback_scope_logits = self.fallback_scope_head(ordinary_context)
        locked_ordinary = self._lock_ordinary(
            ordinary_plans,
            ordinary_plan_logits,
            batch,
        )

        advance_objects = _batched_gather(
            objects,
            batch.advance_right_object_indices,
        )
        source_context = _batched_gather(
            locked_ordinary,
            batch.advance_right_source_indices,
        )
        target_context = _batched_gather(
            locked_ordinary,
            batch.advance_right_target_indices,
        )
        advance_plans = self.candidate_set_encoder(
            batch.advance_right_plan_features,
            batch.advance_right_plan_mask,
        )
        advance_context = torch.cat(
            (advance_objects, source_context, target_context),
            dim=-1,
        )
        advance_expanded = advance_context.unsqueeze(2).expand(
            -1,
            -1,
            advance_plans.shape[2],
            -1,
        )
        advance_right_plan_logits = self.advance_right_plan_head(
            torch.cat((advance_expanded, advance_plans), dim=-1)
        ).squeeze(-1)
        advance_right_plan_logits = advance_right_plan_logits.masked_fill(
            ~batch.advance_right_plan_mask,
            float("-inf"),
        )
        result = {
            "anchor_status_logits": anchor_status_logits,
            "anchor_candidate_logits": anchor_candidate_logits,
            "anchor_selected_candidate_indices": (
                anchor_selected_candidate_indices
            ),
            "anchor_selection_success": anchor_selection_success,
            "ordinary_plan_logits": ordinary_plan_logits,
            "clue_logits": clue_logits,
            "fallback_scope_logits": fallback_scope_logits,
            "advance_right_plan_logits": advance_right_plan_logits,
            "locked_anchor_embeddings": locked_anchor,
            "locked_ordinary_embeddings": locked_ordinary,
            "object_embeddings": objects,
        }
        if anchor_type_logits is not None:
            result["anchor_type_logits"] = anchor_type_logits
        if anchor_gate_logits is not None:
            result["anchor_gate_logits"] = anchor_gate_logits
        if anchor_cardinality_logits is not None:
            result["anchor_cardinality_logits"] = (
                anchor_cardinality_logits
            )
        if anchor_member_logits is not None:
            result["anchor_member_logits"] = anchor_member_logits
        if anchor_composition_logits is not None:
            result["anchor_composition_logits"] = anchor_composition_logits
        if anchor_member_structural_context is not None:
            result["anchor_member_structural_context"] = (
                anchor_member_structural_context
            )
        if anchor_candidate_structural_context is not None:
            result["anchor_candidate_structural_context"] = (
                anchor_candidate_structural_context
            )
        if ordinary_decision_logits is not None:
            result["ordinary_decision_logits"] = ordinary_decision_logits
        if ordinary_decision_validity_logits is not None:
            result["ordinary_decision_validity_logits"] = (
                ordinary_decision_validity_logits
            )
        if ordinary_plan_validity_logits is not None:
            result["ordinary_plan_validity_logits"] = (
                ordinary_plan_validity_logits
            )
        return result

    def _anchor_structural_context(
        self,
        batch: TargetABatchTensors,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if (
            self.anchor_arm_stem is None
            or self.anchor_arm_match_fusion is None
            or self.anchor_member_relation_stem is None
            or batch.anchor_swsd_arm_features is None
            or batch.anchor_swsd_arm_mask is None
            or batch.anchor_member_arm_features is None
            or batch.anchor_member_arm_mask is None
            or batch.anchor_member_relation_features is None
            or batch.anchor_member_relation_mask is None
            or batch.anchor_candidate_membership is None
            or batch.anchor_member_mask is None
        ):
            raise ValueError(
                "anchor structural encoder lacks inference evidence"
            )
        swsd_features = batch.anchor_swsd_arm_features
        member_features = batch.anchor_member_arm_features
        if (
            swsd_features.ndim != 4
            or swsd_features.shape[-1] != ANCHOR_ARM_FEATURE_DIM
            or member_features.ndim != 5
            or member_features.shape[-1] != ANCHOR_ARM_FEATURE_DIM
        ):
            raise ValueError("anchor structural arm tensor shape differs")
        if batch.anchor_swsd_arm_mask.shape != swsd_features.shape[:-1]:
            raise ValueError("anchor SWSD arm mask shape differs")
        if batch.anchor_member_arm_mask.shape != member_features.shape[:-1]:
            raise ValueError("anchor member arm mask shape differs")
        relation_features = batch.anchor_member_relation_features
        if (
            relation_features.ndim != 5
            or relation_features.shape[-1]
            != ANCHOR_MEMBER_RELATION_DIM
            or batch.anchor_member_relation_mask.shape
            != relation_features.shape[:-1]
        ):
            raise ValueError("anchor member relation tensor shape differs")
        swsd_embeddings = self.anchor_arm_stem(swsd_features)
        member_arm_embeddings = self.anchor_arm_stem(member_features)
        scores = torch.einsum(
            "bamrh,bash->bamrs",
            member_arm_embeddings,
            swsd_embeddings,
        ) / (self.config.hidden_dim**0.5)
        pair_mask = (
            batch.anchor_member_arm_mask.unsqueeze(-1)
            & batch.anchor_swsd_arm_mask.unsqueeze(2).unsqueeze(2)
        )
        weights = _masked_softmax(scores, pair_mask, dim=-1)
        matched_swsd = torch.einsum(
            "bamrs,bash->bamrh",
            weights,
            swsd_embeddings,
        )
        arm_relations = self.anchor_arm_match_fusion(
            torch.cat(
                (
                    member_arm_embeddings,
                    matched_swsd,
                    (member_arm_embeddings - matched_swsd).abs(),
                    member_arm_embeddings * matched_swsd,
                ),
                dim=-1,
            )
        )
        arm_mask = batch.anchor_member_arm_mask.unsqueeze(-1)
        member_arm_context = (
            arm_relations * arm_mask.to(arm_relations.dtype)
        ).sum(dim=3) / arm_mask.sum(dim=3).clamp_min(1).to(
            arm_relations.dtype
        )
        relation_embeddings = self.anchor_member_relation_stem(
            relation_features
        )
        relation_mask = batch.anchor_member_relation_mask.unsqueeze(-1)
        relation_context = (
            relation_embeddings
            * relation_mask.to(relation_embeddings.dtype)
        ).sum(dim=3) / relation_mask.sum(dim=3).clamp_min(1).to(
            relation_embeddings.dtype
        )
        local_context = torch.zeros_like(member_arm_context)
        if self.config.anchor_structural_member_local_encoder:
            if (
                self.anchor_member_local_stem is None
                or batch.anchor_member_local_features is None
            ):
                raise ValueError(
                    "anchor member-local encoder lacks inference evidence"
                )
            local_features = batch.anchor_member_local_features
            if (
                local_features.ndim != 4
                or local_features.shape[:-1]
                != batch.anchor_member_mask.shape
                or local_features.shape[-1]
                != ANCHOR_MEMBER_LOCAL_FEATURE_DIM
            ):
                raise ValueError(
                    "anchor member-local tensor shape differs"
                )
            local_context = self.anchor_member_local_stem(local_features)
        member_context = (
            member_arm_context + relation_context + local_context
        ) * batch.anchor_member_mask.unsqueeze(-1).to(
            member_arm_context.dtype
        )
        membership = (
            batch.anchor_candidate_membership
            & batch.anchor_candidate_mask.unsqueeze(-1)
            & batch.anchor_member_mask.unsqueeze(2)
        )
        candidate_context = torch.einsum(
            "bacm,bamh->bach",
            membership.to(member_context.dtype),
            member_context,
        )
        candidate_context = candidate_context / membership.sum(
            dim=-1,
            keepdim=True,
        ).clamp_min(1).to(candidate_context.dtype)
        return candidate_context, member_context

    def _compositional_anchor_logits(
        self,
        anchor_objects: torch.Tensor,
        anchor_candidates: torch.Tensor,
        batch: TargetABatchTensors,
        member_structural_context: torch.Tensor | None = None,
        candidate_structural_context: torch.Tensor | None = None,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        if (
            batch.anchor_member_features is None
            or batch.anchor_member_mask is None
            or batch.anchor_member_is_road is None
            or batch.anchor_candidate_membership is None
            or self.anchor_node_member_head is None
            or self.anchor_road_member_head is None
        ):
            raise ValueError(
                "compositional anchor decoder lacks atomic member tensors"
            )
        member_embeddings = self.candidate_set_encoder(
            batch.anchor_member_features,
            batch.anchor_member_mask,
        )
        if member_structural_context is not None:
            if self.anchor_member_evidence_fusion is None:
                raise RuntimeError(
                    "anchor member evidence fusion is missing"
                )
            if member_structural_context.shape != member_embeddings.shape:
                raise ValueError(
                    "anchor member structural context shape differs"
                )
            member_embeddings = (
                member_embeddings
                + self.anchor_member_evidence_fusion(
                    torch.cat(
                        (member_embeddings, member_structural_context),
                        dim=-1,
                    )
                )
            )
        anchor_expanded = anchor_objects.unsqueeze(2).expand(
            -1,
            -1,
            member_embeddings.shape[2],
            -1,
        )
        member_context = torch.cat(
            (anchor_expanded, member_embeddings),
            dim=-1,
        )
        node_logits = self.anchor_node_member_head(
            member_context
        ).squeeze(-1)
        road_logits = self.anchor_road_member_head(
            member_context
        ).squeeze(-1)
        member_logits = torch.where(
            batch.anchor_member_is_road,
            road_logits,
            node_logits,
        ).masked_fill(
            ~batch.anchor_member_mask,
            float("-inf"),
        )
        composition_logits = compositional_anchor_candidate_logits(
            member_logits,
            batch,
        )
        candidate_logits = composition_logits
        if self.config.compositional_anchor_candidate_residual:
            if (
                self.anchor_compositional_candidate_head is None
                or self.anchor_composition_scale is None
                or self.anchor_type_embedding is None
            ):
                raise RuntimeError(
                    "anchor composition residual modules are missing"
                )
            candidate_is_road = anchor_candidate_type_masks(batch)[
                ..., ANCHOR_TYPE_ROAD
            ].long()
            type_embeddings = self.anchor_type_embedding(
                candidate_is_road
            )
            anchor_expanded = anchor_objects.unsqueeze(2).expand_as(
                anchor_candidates
            )
            residual_parts = [
                anchor_expanded,
                anchor_candidates,
                type_embeddings,
            ]
            if self.config.anchor_structural_candidate_residual_context:
                if candidate_structural_context is None:
                    raise ValueError(
                        "anchor candidate residual lacks structural context"
                    )
                if (
                    candidate_structural_context.shape
                    != anchor_candidates.shape
                ):
                    raise ValueError(
                        "anchor candidate structural context shape differs"
                    )
                residual_parts.append(candidate_structural_context)
            residual_logits = self.anchor_compositional_candidate_head(
                torch.cat(residual_parts, dim=-1)
            ).squeeze(-1)
            safe_composition_logits = torch.where(
                batch.anchor_candidate_mask,
                composition_logits,
                torch.zeros_like(composition_logits),
            )
            candidate_logits = (
                nn.functional.softplus(self.anchor_composition_scale)
                * safe_composition_logits
                + residual_logits
            ).masked_fill(
                ~batch.anchor_candidate_mask,
                float("-inf"),
            )
        return member_logits, composition_logits, candidate_logits

    def _anchor_relation_context(
        self,
        candidates: torch.Tensor,
        candidate_type_masks: torch.Tensor,
        batch: TargetABatchTensors,
    ) -> torch.Tensor:
        relations = batch.anchor_candidate_relations
        if (
            relations is None
            or self.anchor_relation_stem is None
            or self.anchor_relation_score is None
        ):
            raise ValueError(
                "structured anchor decoder lacks candidate relations"
            )
        expected = (
            *candidates.shape[:-2],
            candidates.shape[-2],
            candidates.shape[-2],
            ANCHOR_CANDIDATE_RELATION_DIM,
        )
        if relations.shape != expected:
            raise ValueError("anchor candidate relation shape differs")
        relation_embeddings = self.anchor_relation_stem(relations)
        relation_logits = self.anchor_relation_score(
            relation_embeddings
        ).squeeze(-1)
        valid = batch.anchor_candidate_mask
        same_type = (
            candidate_type_masks.unsqueeze(3)
            & candidate_type_masks.unsqueeze(2)
        ).any(dim=-1)
        pair_mask = (
            valid.unsqueeze(-1)
            & valid.unsqueeze(-2)
            & same_type
        )
        relation_logits = relation_logits.masked_fill(
            ~pair_mask,
            torch.finfo(relation_logits.dtype).min,
        )
        weights = torch.softmax(relation_logits, dim=-1)
        weights = weights * pair_mask.to(weights.dtype)
        weights = weights / weights.sum(
            dim=-1,
            keepdim=True,
        ).clamp_min(1e-12)
        neighbours = candidates.unsqueeze(2) + relation_embeddings
        return (neighbours * weights.unsqueeze(-1)).sum(dim=3)

    def _lock_anchor(
        self,
        candidates: torch.Tensor,
        status_logits: torch.Tensor,
        gate_logits: torch.Tensor | None,
        candidate_logits: torch.Tensor,
        type_logits: torch.Tensor | None,
        cardinality_logits: torch.Tensor | None,
        batch: TargetABatchTensors,
    ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        if batch.teacher_anchor_candidate_indices is not None:
            indices = batch.teacher_anchor_candidate_indices
        else:
            selection_logits = (
                hierarchical_anchor_selection_logits(
                    candidate_logits,
                    type_logits,
                    batch,
                    cardinality_logits=cardinality_logits,
                    hard_type_lock=self.config.anchor_type_hard_lock,
                    type_prior_weight=self.config.anchor_type_prior_weight,
                )
                if self.config.hierarchical_anchor_decoder
                else candidate_logits
            )
            indices = selection_logits.argmax(dim=-1)
        locked = _batched_group_gather(candidates, indices)
        if batch.teacher_anchor_success is not None:
            success = batch.teacher_anchor_success
        else:
            success = status_logits.argmax(dim=-1).eq(0)
            if gate_logits is not None:
                gate_pass_probability = torch.softmax(
                    gate_logits,
                    dim=-1,
                )[..., 1]
                success = success & gate_pass_probability.ge(
                    self.config.anchor_gate_pass_threshold
                )
        locked = locked * success.unsqueeze(-1).to(locked.dtype)
        locked = (
            locked.detach()
            if self.config.stop_gradient_between_stages
            else locked
        )
        return locked, indices, success

    def _raw_anchor_type_logits(
        self,
        batch: TargetABatchTensors,
        candidate_type_masks: torch.Tensor,
    ) -> torch.Tensor:
        if self.anchor_raw_evidence_type_head is None:
            raise RuntimeError("raw-evidence anchor type head is missing")
        anchor_features = _batched_gather(
            batch.object_features,
            batch.anchor_object_indices,
        )
        summaries = [
            _masked_feature_statistics(
                batch.anchor_candidate_features,
                candidate_type_masks[..., type_index],
            )
            for type_index in range(ANCHOR_TYPE_COUNT)
        ]
        counts = candidate_type_masks.to(
            batch.anchor_candidate_features.dtype
        ).sum(dim=2) / float(self.config.anchor_cardinality_count)
        return self.anchor_raw_evidence_type_head(
            torch.cat((anchor_features, *summaries, counts), dim=-1)
        )

    def _raw_anchor_candidate_logits(
        self,
        batch: TargetABatchTensors,
        candidate_type_masks: torch.Tensor,
    ) -> torch.Tensor:
        if self.anchor_raw_evidence_candidate_head is None:
            raise RuntimeError("raw-evidence anchor candidate head is missing")
        anchor_features = _batched_gather(
            batch.object_features,
            batch.anchor_object_indices,
        )
        expanded = anchor_features.unsqueeze(2).expand(
            -1,
            -1,
            batch.anchor_candidate_features.shape[2],
            -1,
        )
        logits = self.anchor_raw_evidence_candidate_head(
            torch.cat(
                (
                    expanded,
                    batch.anchor_candidate_features,
                    candidate_type_masks.to(
                        batch.anchor_candidate_features.dtype
                    ),
                ),
                dim=-1,
            )
        ).squeeze(-1)
        return logits.masked_fill(
            ~batch.anchor_candidate_mask,
            float("-inf"),
        )

    def _lock_ordinary(
        self,
        plans: torch.Tensor,
        logits: torch.Tensor,
        batch: TargetABatchTensors,
    ) -> torch.Tensor:
        if batch.teacher_ordinary_plan_indices is not None:
            indices = batch.teacher_ordinary_plan_indices
        else:
            indices = logits.argmax(dim=-1)
        locked = _batched_group_gather(plans, indices)
        return locked.detach() if self.config.stop_gradient_between_stages else locked

    def _validate_batch(self, batch: TargetABatchTensors) -> None:
        if batch.object_features.ndim != 3:
            raise ValueError("Target A object_features must be [B, N, F]")
        if batch.object_features.shape[-1] != self.config.feature_dim:
            raise ValueError("Target A object feature dimension differs")
        if batch.object_types.shape != batch.object_features.shape[:2]:
            raise ValueError("Target A object type shape differs")
        if batch.object_mask.shape != batch.object_features.shape[:2]:
            raise ValueError("Target A object mask shape differs")
        if batch.object_mask.dtype is not torch.bool:
            raise ValueError("Target A object mask must be bool")
        if batch.object_types.dtype not in {torch.int32, torch.int64}:
            raise ValueError("Target A object types must be integer")
        if batch.adjacency.dtype is not torch.bool:
            raise ValueError("Target A adjacency must be bool")
        if batch.ordinary_anchor_condition_features is not None and (
            batch.ordinary_anchor_condition_features.shape
            != (
                batch.object_features.shape[0],
                batch.ordinary_object_indices.shape[1],
                ORDINARY_ANCHOR_CONDITION_DIM,
            )
        ):
            raise ValueError(
                "ordinary anchor condition feature shape differs"
            )
        if batch.ordinary_plan_decision_indices is not None and (
            batch.ordinary_plan_decision_indices.shape
            != batch.ordinary_plan_mask.shape
            or batch.ordinary_plan_decision_indices.dtype
            not in {torch.int32, torch.int64}
        ):
            raise ValueError(
                "ordinary plan decision index shape or dtype differs"
            )
        if (
            self.config.hierarchical_ordinary_plan_decoder
            and batch.ordinary_plan_decision_indices is None
        ):
            raise ValueError(
                "hierarchical ordinary decoding lacks decision indices"
            )
        if batch.ordinary_plan_member_features is not None:
            expected_member_shape = (
                *batch.ordinary_plan_mask.shape,
                batch.ordinary_plan_member_features.shape[-2],
            )
            if (
                batch.ordinary_plan_member_features.shape[:-1]
                != expected_member_shape
                or batch.ordinary_plan_member_features.shape[-1]
                != ORDINARY_PLAN_MEMBER_FEATURE_DIM
                or batch.ordinary_plan_member_mask is None
                or batch.ordinary_plan_member_mask.shape
                != expected_member_shape
            ):
                raise ValueError(
                    "ordinary plan member evidence shape differs"
                )
        if batch.ordinary_plan_arm_features is not None:
            expected_arm_shape = (
                *batch.ordinary_plan_mask.shape,
                ORDINARY_PLAN_ARM_COUNT,
            )
            if (
                batch.ordinary_plan_arm_features.shape[:-1]
                != expected_arm_shape
                or batch.ordinary_plan_arm_features.shape[-1]
                != ORDINARY_PLAN_ARM_FEATURE_DIM
                or batch.ordinary_plan_arm_mask is None
                or batch.ordinary_plan_arm_mask.shape != expected_arm_shape
            ):
                raise ValueError("ordinary plan arm evidence shape differs")
        if (
            self.config.ordinary_plan_member_encoder
            and batch.ordinary_plan_member_features is None
        ):
            raise ValueError(
                "ordinary plan member encoder lacks member evidence"
            )
        if (
            self.config.ordinary_plan_arm_encoder
            and batch.ordinary_plan_arm_features is None
        ):
            raise ValueError(
                "ordinary plan arm encoder lacks arm evidence"
            )


def _batched_gather(values: torch.Tensor, indices: torch.Tensor) -> torch.Tensor:
    if indices.ndim != 2 or values.ndim != 3:
        raise ValueError("batched gather shape differs")
    safe = indices.clamp_min(0)
    batch_indices = torch.arange(values.shape[0], device=values.device).unsqueeze(1)
    gathered = values[batch_indices, safe]
    return gathered * indices.ge(0).unsqueeze(-1).to(gathered.dtype)


def _batched_group_gather(values: torch.Tensor, indices: torch.Tensor) -> torch.Tensor:
    if values.ndim != 4 or indices.shape != values.shape[:2]:
        raise ValueError("candidate group gather shape differs")
    safe = indices.clamp_min(0)
    batch_indices = torch.arange(values.shape[0], device=values.device)[:, None]
    group_indices = torch.arange(values.shape[1], device=values.device)[None, :]
    gathered = values[batch_indices, group_indices, safe]
    return gathered * indices.ge(0).unsqueeze(-1).to(gathered.dtype)


def anchor_candidate_type_masks(
    batch: TargetABatchTensors,
) -> torch.Tensor:
    if (
        batch.anchor_candidate_features.shape[:-1]
        != batch.anchor_candidate_mask.shape
    ):
        raise ValueError("anchor candidate feature/mask shape differs")
    road = (
        batch.anchor_candidate_features[
            ..., ANCHOR_CANDIDATE_ROAD_FEATURE_INDEX
        ]
        > 0.5
    ) & batch.anchor_candidate_mask
    node = (~road) & batch.anchor_candidate_mask
    return torch.stack((node, road), dim=-1)


def _masked_feature_statistics(
    features: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    if features.shape[:-1] != mask.shape:
        raise ValueError("masked feature statistics shape differs")
    expanded = mask.unsqueeze(-1)
    counts = expanded.sum(dim=2)
    mean = (features * expanded.to(features.dtype)).sum(dim=2)
    mean = mean / counts.clamp_min(1).to(features.dtype)
    maximum = features.masked_fill(~expanded, float("-inf")).amax(dim=2)
    minimum = features.masked_fill(~expanded, float("inf")).amin(dim=2)
    present = counts.gt(0)
    maximum = torch.where(present, maximum, torch.zeros_like(maximum))
    minimum = torch.where(present, minimum, torch.zeros_like(minimum))
    return torch.cat((mean, minimum, maximum), dim=-1)


def _candidate_type_logmeanexp(
    candidate_logits: torch.Tensor,
    candidate_type_masks: torch.Tensor,
) -> torch.Tensor:
    if candidate_type_masks.shape != candidate_logits.shape + (
        ANCHOR_TYPE_COUNT,
    ):
        raise ValueError("candidate type masks and logits shape differs")
    values = []
    for type_index in range(ANCHOR_TYPE_COUNT):
        mask = candidate_type_masks[..., type_index]
        count = mask.sum(dim=-1)
        pooled = torch.logsumexp(
            candidate_logits.masked_fill(~mask, float("-inf")),
            dim=-1,
        )
        pooled = pooled - count.clamp_min(1).to(
            candidate_logits.dtype
        ).log()
        values.append(
            torch.where(
                count.gt(0),
                pooled,
                torch.full_like(pooled, float("-inf")),
            )
        )
    return torch.stack(values, dim=-1)


def anchor_candidate_cardinality_masks(
    batch: TargetABatchTensors,
    cardinality_count: int,
) -> torch.Tensor:
    membership = batch.anchor_candidate_membership
    if membership is None:
        raise ValueError("anchor cardinality conditioning lacks membership")
    if cardinality_count < 1:
        raise ValueError("anchor cardinality count must be positive")
    if membership.shape[:-1] != batch.anchor_candidate_mask.shape:
        raise ValueError("anchor candidate membership shape differs")
    member_counts = membership.sum(dim=-1)
    valid_counts = member_counts[batch.anchor_candidate_mask]
    if bool((valid_counts < 1).any()):
        raise ValueError("anchor candidate has no atomic member")
    if bool((valid_counts > cardinality_count).any()):
        raise ValueError("anchor candidate exceeds the cardinality limit")
    return (
        nn.functional.one_hot(
            member_counts.clamp_min(1) - 1,
            num_classes=cardinality_count,
        ).bool()
        & batch.anchor_candidate_mask.unsqueeze(-1)
    )


def anchor_member_cardinality_valid_masks(
    batch: TargetABatchTensors,
    cardinality_count: int,
) -> torch.Tensor:
    member_mask = batch.anchor_member_mask
    member_is_road = batch.anchor_member_is_road
    if member_mask is None or member_is_road is None:
        raise ValueError("anchor member cardinality lacks member tensors")
    if member_mask.shape != member_is_road.shape:
        raise ValueError("anchor member cardinality mask shapes differ")
    if cardinality_count < 1:
        raise ValueError("anchor member cardinality count must be positive")
    typed_members = torch.stack(
        (
            member_mask & ~member_is_road,
            member_mask & member_is_road,
        ),
        dim=-1,
    )
    member_counts = typed_members.sum(dim=2)
    count_indices = torch.arange(
        1,
        cardinality_count + 1,
        device=member_mask.device,
    )
    return count_indices < (
        member_counts.unsqueeze(-1) + 1
    )


def anchor_cardinality_candidate_log_prior(
    cardinality_logits: torch.Tensor,
    batch: TargetABatchTensors,
) -> torch.Tensor:
    if cardinality_logits.ndim != 4:
        raise ValueError("anchor cardinality logits must be [B, A, T, K]")
    candidate_type_indices = anchor_candidate_type_masks(batch)[
        ..., ANCHOR_TYPE_ROAD
    ].long()
    typed_logits = torch.gather(
        cardinality_logits.unsqueeze(2).expand(
            -1,
            -1,
            candidate_type_indices.shape[-1],
            -1,
            -1,
        ),
        -2,
        candidate_type_indices.unsqueeze(-1).unsqueeze(-1).expand(
            *candidate_type_indices.shape,
            1,
            cardinality_logits.shape[-1],
        ),
    ).squeeze(-2)
    cardinality_masks = anchor_candidate_cardinality_masks(
        batch,
        cardinality_logits.shape[-1],
    )
    count_indices = cardinality_masks.long().argmax(dim=-1)
    log_probabilities = nn.functional.log_softmax(
        typed_logits,
        dim=-1,
    )
    prior = torch.gather(
        log_probabilities,
        -1,
        count_indices.unsqueeze(-1),
    ).squeeze(-1)
    return prior.masked_fill(
        ~batch.anchor_candidate_mask,
        float("-inf"),
    )


def compositional_anchor_candidate_logits(
    member_logits: torch.Tensor,
    batch: TargetABatchTensors,
) -> torch.Tensor:
    member_mask = batch.anchor_member_mask
    member_is_road = batch.anchor_member_is_road
    membership = batch.anchor_candidate_membership
    if member_mask is None or member_is_road is None or membership is None:
        raise ValueError("compositional anchor candidate tensors are missing")
    if member_logits.shape != member_mask.shape:
        raise ValueError("anchor member logits/mask shape differs")
    if member_is_road.shape != member_mask.shape:
        raise ValueError("anchor member type shape differs")
    expected_membership = (
        *batch.anchor_candidate_mask.shape,
        member_mask.shape[-1],
    )
    if membership.shape != expected_membership:
        raise ValueError("anchor candidate membership shape differs")
    candidate_is_road = anchor_candidate_type_masks(batch)[
        ..., ANCHOR_TYPE_ROAD
    ]
    same_type_members = member_mask.unsqueeze(2) & (
        member_is_road.unsqueeze(2)
        == candidate_is_road.unsqueeze(-1)
    )
    if bool(
        (
            membership
            & ~same_type_members
            & batch.anchor_candidate_mask.unsqueeze(-1)
        ).any()
    ):
        raise ValueError("anchor candidate contains a cross-type member")
    included_log_probability = nn.functional.logsigmoid(
        member_logits
    ).unsqueeze(2)
    excluded_log_probability = nn.functional.logsigmoid(
        -member_logits
    ).unsqueeze(2)
    member_log_probability = torch.where(
        membership,
        included_log_probability,
        excluded_log_probability,
    )
    candidate_logits = (
        member_log_probability
        * same_type_members.to(member_log_probability.dtype)
    ).sum(dim=-1)
    return candidate_logits.masked_fill(
        ~batch.anchor_candidate_mask,
        float("-inf"),
    )


def hierarchical_anchor_selection_logits(
    candidate_logits: torch.Tensor,
    type_logits: torch.Tensor | None,
    batch: TargetABatchTensors,
    *,
    cardinality_logits: torch.Tensor | None = None,
    hard_type_lock: bool = True,
    type_prior_weight: float = 1.0,
) -> torch.Tensor:
    if type_logits is None:
        raise ValueError("hierarchical anchor selection lacks type logits")
    type_masks = anchor_candidate_type_masks(batch)
    if type_logits.shape != type_masks.shape[:-2] + (ANCHOR_TYPE_COUNT,):
        raise ValueError("hierarchical anchor type shape differs")
    if type_prior_weight < 0:
        raise ValueError("anchor type prior weight must not be negative")
    if not hard_type_lock:
        type_log_probabilities = nn.functional.log_softmax(
            type_logits,
            dim=-1,
        )
        type_log_prior = torch.logsumexp(
            type_log_probabilities.unsqueeze(-2).masked_fill(
                ~type_masks,
                float("-inf"),
            ),
            dim=-1,
        )
        result = candidate_logits + type_prior_weight * type_log_prior
        if cardinality_logits is not None:
            result = result + anchor_cardinality_candidate_log_prior(
                cardinality_logits,
                batch,
            )
        return result.masked_fill(
            ~batch.anchor_candidate_mask,
            float("-inf"),
        )
    selected_types = type_logits.argmax(dim=-1)
    selected_mask = torch.gather(
        type_masks,
        -1,
        selected_types.unsqueeze(-1).unsqueeze(-1).expand(
            *selected_types.shape,
            type_masks.shape[-2],
            1,
        ),
    ).squeeze(-1)
    if cardinality_logits is not None:
        expected = (
            *selected_types.shape,
            ANCHOR_TYPE_COUNT,
            cardinality_logits.shape[-1],
        )
        if cardinality_logits.shape != expected:
            raise ValueError("hierarchical anchor cardinality shape differs")
        cardinality_masks = anchor_candidate_cardinality_masks(
            batch,
            cardinality_logits.shape[-1],
        )
        selected_type_cardinality_logits = torch.gather(
            cardinality_logits,
            -2,
            selected_types.unsqueeze(-1).unsqueeze(-1).expand(
                *selected_types.shape,
                1,
                cardinality_logits.shape[-1],
            ),
        ).squeeze(-2)
        selected_cardinalities = (
            selected_type_cardinality_logits.argmax(dim=-1)
        )
        selected_cardinality_mask = torch.gather(
            cardinality_masks,
            -1,
            selected_cardinalities.unsqueeze(-1).unsqueeze(-1).expand(
                *selected_cardinalities.shape,
                cardinality_masks.shape[-2],
                1,
            ),
        ).squeeze(-1)
        selected_mask = selected_mask & selected_cardinality_mask
    return candidate_logits.masked_fill(~selected_mask, float("-inf"))


def ordinary_plan_decision_masks(
    batch: TargetABatchTensors,
) -> torch.Tensor:
    indices = batch.ordinary_plan_decision_indices
    if indices is None:
        raise ValueError("ordinary plan decision indices are missing")
    if indices.shape != batch.ordinary_plan_mask.shape:
        raise ValueError("ordinary plan decision index shape differs")
    invalid = (indices < 0) | (indices >= ORDINARY_DECISION_COUNT)
    if bool((invalid & batch.ordinary_plan_mask).any()):
        raise ValueError("ordinary plan has an invalid decision index")
    return (
        nn.functional.one_hot(
            indices.clamp(0, ORDINARY_DECISION_COUNT - 1),
            num_classes=ORDINARY_DECISION_COUNT,
        ).bool()
        & batch.ordinary_plan_mask.unsqueeze(-1)
    )


def ordinary_decision_contexts(
    plans: torch.Tensor,
    decision_masks: torch.Tensor,
) -> torch.Tensor:
    expected = (*plans.shape[:-1], ORDINARY_DECISION_COUNT)
    if decision_masks.shape != expected:
        raise ValueError("ordinary decision context shape differs")
    weights = decision_masks.to(plans.dtype)
    total = (
        plans.unsqueeze(-2)
        * weights.unsqueeze(-1)
    ).sum(dim=2)
    denominator = weights.sum(dim=2).unsqueeze(-1).clamp_min(1.0)
    return total / denominator


def ordinary_plan_member_context(
    encoded_members: torch.Tensor,
    member_mask: torch.Tensor,
) -> torch.Tensor:
    if (
        encoded_members.shape[:-1] != member_mask.shape
        or member_mask.dtype is not torch.bool
    ):
        raise ValueError("ordinary plan member context shape differs")
    weights = member_mask.unsqueeze(-1).to(encoded_members.dtype)
    mean_context = (encoded_members * weights).sum(dim=-2) / (
        weights.sum(dim=-2).clamp_min(1.0)
    )
    maximum_context = encoded_members.masked_fill(
        ~member_mask.unsqueeze(-1),
        torch.finfo(encoded_members.dtype).min,
    ).max(dim=-2).values
    maximum_context = torch.where(
        member_mask.any(dim=-1).unsqueeze(-1),
        maximum_context,
        torch.zeros_like(maximum_context),
    )
    return torch.cat((mean_context, maximum_context), dim=-1)


def hierarchical_ordinary_plan_logits(
    bundle_logits: torch.Tensor,
    decision_logits: torch.Tensor,
    batch: TargetABatchTensors,
) -> torch.Tensor:
    decision_masks = ordinary_plan_decision_masks(batch)
    if bundle_logits.shape != batch.ordinary_plan_mask.shape:
        raise ValueError("ordinary bundle logit shape differs")
    expected_decisions = (
        *bundle_logits.shape[:-1],
        ORDINARY_DECISION_COUNT,
    )
    if decision_logits.shape != expected_decisions:
        raise ValueError("ordinary decision logit shape differs")
    valid_decisions = decision_masks.any(dim=2)
    decision_log_probabilities = nn.functional.log_softmax(
        decision_logits.masked_fill(
            ~valid_decisions,
            torch.finfo(decision_logits.dtype).min,
        ),
        dim=-1,
    )
    indices = batch.ordinary_plan_decision_indices
    if indices is None:
        raise ValueError("ordinary plan decision indices are missing")
    selected_decision_log_probability = torch.gather(
        decision_log_probabilities,
        -1,
        indices.clamp(0, ORDINARY_DECISION_COUNT - 1),
    )
    grouped_bundle_logits = bundle_logits.unsqueeze(-1).masked_fill(
        ~decision_masks,
        torch.finfo(bundle_logits.dtype).min,
    )
    group_log_normalizer = torch.logsumexp(
        grouped_bundle_logits,
        dim=2,
    )
    selected_group_log_normalizer = torch.gather(
        group_log_normalizer,
        -1,
        indices.clamp(0, ORDINARY_DECISION_COUNT - 1),
    )
    combined = (
        selected_decision_log_probability
        + bundle_logits
        - selected_group_log_normalizer
    )
    return combined.masked_fill(
        ~batch.ordinary_plan_mask,
        float("-inf"),
    )


def _masked_softmax(
    scores: torch.Tensor,
    mask: torch.Tensor,
    *,
    dim: int,
) -> torch.Tensor:
    if scores.shape != mask.shape or mask.dtype is not torch.bool:
        raise ValueError("masked softmax shape or dtype differs")
    safe_scores = scores.masked_fill(
        ~mask,
        torch.finfo(scores.dtype).min,
    )
    weights = torch.softmax(safe_scores, dim=dim)
    weights = weights * mask.to(weights.dtype)
    return weights / weights.sum(dim=dim, keepdim=True).clamp_min(1e-12)


def _masked_candidate_pool(
    candidates: torch.Tensor,
    pool_logits: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    if pool_logits.shape != mask.shape or candidates.shape[:-1] != mask.shape:
        raise ValueError("typed anchor candidate pool shape differs")
    safe_logits = pool_logits.masked_fill(
        ~mask,
        torch.finfo(pool_logits.dtype).min,
    )
    weights = torch.softmax(safe_logits, dim=-1)
    weights = weights * mask.to(weights.dtype)
    weights = weights / weights.sum(dim=-1, keepdim=True).clamp_min(1e-12)
    return (candidates * weights.unsqueeze(-1)).sum(dim=2)


def _scatter_group_context(
    values: torch.Tensor,
    indices: torch.Tensor,
    *,
    object_count: int,
) -> torch.Tensor:
    if values.ndim != 3 or indices.shape != values.shape[:2]:
        raise ValueError("group context scatter shape differs")
    valid = indices.ge(0)
    safe = indices.clamp_min(0)
    result = torch.zeros(
        (values.shape[0], object_count, values.shape[-1]),
        dtype=values.dtype,
        device=values.device,
    )
    result.scatter_add_(
        1,
        safe.unsqueeze(-1).expand_as(values),
        values * valid.unsqueeze(-1).to(values.dtype),
    )
    counts = torch.zeros(
        (values.shape[0], object_count, 1),
        dtype=values.dtype,
        device=values.device,
    )
    counts.scatter_add_(
        1,
        safe.unsqueeze(-1),
        valid.unsqueeze(-1).to(values.dtype),
    )
    return result / counts.clamp_min(1.0)


def _indexed_mean(values: torch.Tensor, indices: torch.Tensor) -> torch.Tensor:
    if values.ndim != 3 or indices.ndim != 3:
        raise ValueError("indexed mean shape differs")
    batch, group_count, dependency_count = indices.shape
    safe = indices.clamp_min(0)
    batch_indices = torch.arange(batch, device=values.device)[:, None, None]
    gathered = values[batch_indices, safe]
    mask = indices.ge(0).unsqueeze(-1)
    total = (gathered * mask.to(gathered.dtype)).sum(dim=2)
    denominator = mask.sum(dim=2).clamp_min(1).to(gathered.dtype)
    result = total / denominator
    if result.shape[:2] != (batch, group_count):
        raise AssertionError("indexed mean output shape differs")
    return result


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


def model_contract(model: TargetAJointNetwork) -> dict[str, Any]:
    return {
        "feature_dim": model.config.feature_dim,
        "hidden_dim": model.config.hidden_dim,
        "graph_layers": model.config.graph_layers,
        "set_layers": model.config.set_layers,
        "parameter_count": parameter_count(model),
        "stop_gradient_between_stages": model.config.stop_gradient_between_stages,
        "anchor_structural_evidence_encoder": (
            model.config.anchor_structural_evidence_encoder
        ),
        "anchor_structural_candidate_context_fusion": (
            model.config.anchor_structural_candidate_context_fusion
        ),
        "anchor_structural_member_local_encoder": (
            model.config.anchor_structural_member_local_encoder
        ),
        "anchor_structural_candidate_residual_context": (
            model.config.anchor_structural_candidate_residual_context
        ),
        "ordinary_oof_anchor_condition_encoder": (
            model.config.ordinary_oof_anchor_condition_encoder
        ),
        "hierarchical_ordinary_plan_decoder": (
            model.config.hierarchical_ordinary_plan_decoder
        ),
        "ordinary_plan_member_encoder": (
            model.config.ordinary_plan_member_encoder
        ),
        "ordinary_plan_member_within_decision_only": (
            model.config.ordinary_plan_member_within_decision_only
        ),
        "ordinary_plan_arm_encoder": (
            model.config.ordinary_plan_arm_encoder
        ),
    }


__all__ = [
    "ANCHOR_CANDIDATE_ROAD_FEATURE_INDEX",
    "ANCHOR_TYPE_COUNT",
    "ANCHOR_TYPE_NODE",
    "ANCHOR_TYPE_ROAD",
    "ORDINARY_ANCHOR_CONDITION_DIM",
    "ORDINARY_DECISION_ABSTAIN",
    "ORDINARY_DECISION_COUNT",
    "ORDINARY_DECISION_KEEP_SWSD",
    "ORDINARY_DECISION_USE_RCSD",
    "TargetABatchTensors",
    "TargetAJointNetwork",
    "anchor_cardinality_candidate_log_prior",
    "anchor_candidate_cardinality_masks",
    "anchor_candidate_type_masks",
    "compositional_anchor_candidate_logits",
    "hierarchical_anchor_selection_logits",
    "hierarchical_ordinary_plan_logits",
    "model_contract",
    "ordinary_decision_contexts",
    "ordinary_plan_member_context",
    "ordinary_plan_decision_masks",
    "parameter_count",
]
