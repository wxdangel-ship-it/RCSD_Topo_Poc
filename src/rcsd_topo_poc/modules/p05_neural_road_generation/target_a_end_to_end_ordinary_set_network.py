from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_access_sets import (
    SIDE_ACCESS_FEATURE_DIM,
    SIDE_OBJECT_FEATURE_DIM,
    SIDE_ROAD_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_outcome_review import (
    AnchorOutcomeReviewConfig,
    AnchorOutcomeReviewHead,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    ORDINARY_ANCHOR_UNRESOLVED,
    advance_right_business_plan_mask,
    advance_right_plan_type_from_ordinary,
    apply_advance_right_business_mask,
    ordinary_business_states_from_anchor_state,
    ordinary_free_run_business_states,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_data import (
    ORDINARY_SET_ROAD_RELATION_DIM,
    ORDINARY_SET_SOURCE_RCSD,
    ORDINARY_SET_SOURCE_SWSD,
    EndToEndOrdinarySetBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_COUNT,
    TargetABatchTensors,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_members import (
    ROAD_BUSINESS_ROLE_LABELS,
    ROAD_OWNERSHIP_LABELS,
)


@dataclass(frozen=True)
class TargetAEndToEndOrdinarySetConfig:
    hidden_dim: int
    road_hidden_dim: int = 128
    access_hidden_dim: int = 96
    road_set_layers: int = 2
    road_set_heads: int = 4
    max_road_cardinality: int = 66
    cardinality_mode: str = "categorical"
    dropout: float = 0.10
    anchor_gate_pass_threshold: float = 0.50
    no_evidence_probability_threshold: float = 1.0
    stop_gradient_at_business_boundaries: bool = False
    anchor_outcome_enabled: bool = False
    anchor_outcome_hidden_dim: int = 128
    anchor_outcome_positive_release_threshold: float = 0.50
    anchor_outcome_fallback_threshold: float = 0.50
    anchor_outcome_stop_gradient: bool = True

    def validate(self) -> None:
        if min(
            self.hidden_dim,
            self.road_hidden_dim,
            self.access_hidden_dim,
            self.road_set_layers,
            self.road_set_heads,
            self.max_road_cardinality,
        ) < 1:
            raise ValueError("end-to-end ordinary-set dimensions are invalid")
        if self.road_hidden_dim % self.road_set_heads:
            raise ValueError("ordinary-set Road heads do not divide hidden dim")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("end-to-end ordinary-set dropout is invalid")
        if not 0.0 < self.anchor_gate_pass_threshold < 1.0:
            raise ValueError("ordinary-set anchor threshold is invalid")
        if not 0.0 <= self.no_evidence_probability_threshold <= 1.0:
            raise ValueError("ordinary-set NO_EVIDENCE threshold is invalid")
        if self.cardinality_mode not in {"categorical", "ordinal"}:
            raise ValueError("ordinary-set cardinality mode is invalid")
        if self.anchor_outcome_enabled:
            AnchorOutcomeReviewConfig(
                hidden_dim=self.hidden_dim,
                head_hidden_dim=self.anchor_outcome_hidden_dim,
                dropout=self.dropout,
                positive_release_threshold=(
                    self.anchor_outcome_positive_release_threshold
                ),
                fallback_threshold=self.anchor_outcome_fallback_threshold,
                stop_gradient_at_anchor_evidence=(
                    self.anchor_outcome_stop_gradient
                ),
            ).validate()


class TargetAEndToEndOrdinarySetNetwork(nn.Module):
    """Decode adjacent ordinary final states before AdvanceRight in one forward."""

    def __init__(
        self,
        base: nn.Module,
        config: TargetAEndToEndOrdinarySetConfig,
    ) -> None:
        super().__init__()
        config.validate()
        self.base = base
        self.config = config
        self.anchor_outcome_head = (
            AnchorOutcomeReviewHead(
                AnchorOutcomeReviewConfig(
                    hidden_dim=config.hidden_dim,
                    head_hidden_dim=config.anchor_outcome_hidden_dim,
                    dropout=config.dropout,
                    positive_release_threshold=(
                        config.anchor_outcome_positive_release_threshold
                    ),
                    fallback_threshold=(
                        config.anchor_outcome_fallback_threshold
                    ),
                    stop_gradient_at_anchor_evidence=(
                        config.anchor_outcome_stop_gradient
                    ),
                )
            )
            if config.anchor_outcome_enabled
            else None
        )
        self.road_stem = nn.Sequential(
            nn.Linear(SIDE_ROAD_FEATURE_DIM, config.road_hidden_dim * 2),
            nn.GELU(),
            nn.LayerNorm(config.road_hidden_dim * 2),
            nn.Dropout(config.dropout),
            nn.Linear(config.road_hidden_dim * 2, config.road_hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.road_hidden_dim),
        )
        self.relation_stem = nn.Sequential(
            nn.Linear(
                ORDINARY_SET_ROAD_RELATION_DIM,
                config.road_hidden_dim,
            ),
            nn.GELU(),
            nn.LayerNorm(config.road_hidden_dim),
        )
        self.relation_fusion = nn.Sequential(
            nn.Linear(config.road_hidden_dim * 2, config.road_hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.road_hidden_dim),
        )
        self.road_anchor_relation_stem = nn.Sequential(
            nn.Linear(8, config.road_hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.road_hidden_dim),
        )
        self.road_anchor_relation_scale = nn.Parameter(
            torch.tensor(0.0)
        )
        road_layer = nn.TransformerEncoderLayer(
            d_model=config.road_hidden_dim,
            nhead=config.road_set_heads,
            dim_feedforward=config.road_hidden_dim * 4,
            dropout=config.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.road_set_encoder = nn.TransformerEncoder(
            road_layer,
            num_layers=config.road_set_layers,
            enable_nested_tensor=False,
        )
        self.object_stem = nn.Sequential(
            nn.Linear(SIDE_OBJECT_FEATURE_DIM, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        side_input_dim = (
            2 * config.hidden_dim + 2 * config.road_hidden_dim
        )
        self.side_context = nn.Sequential(
            nn.Linear(side_input_dim, config.hidden_dim * 2),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim * 2),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim * 2, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        self.decision_head = _head(
            config.hidden_dim,
            config.hidden_dim,
            ORDINARY_DECISION_COUNT,
            config.dropout,
        )
        self.cardinality_head = _head(
            config.hidden_dim,
            config.hidden_dim,
            config.max_road_cardinality + 1,
            config.dropout,
        )
        self.member_head = _head(
            config.road_hidden_dim
            + config.hidden_dim
            + ORDINARY_DECISION_COUNT,
            config.hidden_dim,
            1,
            config.dropout,
        )
        road_business_input_dim = (
            config.road_hidden_dim
            + config.hidden_dim
            + ORDINARY_DECISION_COUNT
        )
        self.ownership_head = _head(
            road_business_input_dim,
            config.hidden_dim,
            len(ROAD_OWNERSHIP_LABELS),
            config.dropout,
        )
        self.business_role_head = _head(
            road_business_input_dim,
            config.hidden_dim,
            len(ROAD_BUSINESS_ROLE_LABELS),
            config.dropout,
        )
        self.member_business_fusion = nn.Sequential(
            nn.Linear(
                1
                + len(ROAD_OWNERSHIP_LABELS)
                + len(ROAD_BUSINESS_ROLE_LABELS),
                config.road_hidden_dim,
            ),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.road_hidden_dim, 1),
        )
        nn.init.zeros_(self.member_business_fusion[-1].weight)
        nn.init.zeros_(self.member_business_fusion[-1].bias)
        self.expansion_context_stem = nn.Sequential(
            nn.Linear(config.hidden_dim, config.road_hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.road_hidden_dim),
        )
        expansion_input_dim = (
            4 * config.road_hidden_dim
            + 2 * ORDINARY_SET_ROAD_RELATION_DIM
            + 4
        )
        expansion_hidden_dim = config.road_hidden_dim * 3 // 2
        self.next_road_head = _expansion_head(
            expansion_input_dim,
            expansion_hidden_dim,
            config.road_hidden_dim,
            config.dropout,
        )
        stop_input_dim = 3 * config.road_hidden_dim + 3
        self.stop_head = _expansion_head(
            stop_input_dim,
            expansion_hidden_dim,
            config.road_hidden_dim,
            config.dropout,
        )
        self.access_stem = nn.Sequential(
            nn.Linear(SIDE_ACCESS_FEATURE_DIM, config.access_hidden_dim * 2),
            nn.GELU(),
            nn.LayerNorm(config.access_hidden_dim * 2),
            nn.Dropout(config.dropout),
            nn.Linear(
                config.access_hidden_dim * 2,
                config.access_hidden_dim,
            ),
            nn.GELU(),
            nn.LayerNorm(config.access_hidden_dim),
        )
        self.access_head = _head(
            config.access_hidden_dim + config.hidden_dim,
            config.hidden_dim,
            1,
            config.dropout,
        )
        self.advance_plan_stem = nn.Sequential(
            nn.Linear(TARGET_A_FEATURE_DIM, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        self.advance_residual_head = _head(
            4 * config.hidden_dim + 2 * ORDINARY_DECISION_COUNT,
            config.hidden_dim,
            1,
            config.dropout,
        )
        nn.init.zeros_(self.advance_residual_head[-1].weight)
        nn.init.zeros_(self.advance_residual_head[-1].bias)

    def freeze_base(self) -> None:
        self.base.requires_grad_(False)

    def forward(
        self,
        batch: TargetABatchTensors,
        ordinary_set: EndToEndOrdinarySetBatch,
        *,
        advance_right_road_member_values: torch.Tensor | None = None,
        advance_right_road_member_mask: torch.Tensor | None = None,
        advance_right_plan_membership: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        base_outputs = self._forward_base(
            batch,
            advance_right_road_member_values=(
                advance_right_road_member_values
            ),
            advance_right_road_member_mask=advance_right_road_member_mask,
            advance_right_plan_membership=advance_right_plan_membership,
        )
        if self.anchor_outcome_head is not None:
            base_outputs = {
                **base_outputs,
                **self.anchor_outcome_head(base_outputs, batch),
            }
        base_object_embeddings = base_outputs["object_embeddings"]
        if self.config.stop_gradient_at_business_boundaries:
            base_object_embeddings = base_object_embeddings.detach()
        ordinary_evidence = _gather_groups(
            base_object_embeddings,
            batch.ordinary_object_indices,
        )
        ordinary_evidence = _gather_groups(
            ordinary_evidence,
            ordinary_set.side_group_indices,
        )
        ordinary_outputs = self.decode_ordinary_sets(
            ordinary_set,
            ordinary_evidence,
            anchor_outputs=(
                None
                if ordinary_set.side_precomputed_anchor_context is not None
                else base_outputs
            ),
        )
        side_context = ordinary_outputs["ordinary_side_context"]
        decision_logits = ordinary_outputs[
            "ordinary_side_decision_logits"
        ]
        decision_probabilities = ordinary_outputs[
            "ordinary_side_decision_probabilities"
        ]

        group_probabilities = _scatter_side_probabilities(
            decision_probabilities,
            ordinary_set.side_group_indices,
            group_count=batch.ordinary_plan_mask.shape[1],
        )
        if ordinary_set.side_precomputed_anchor_context is not None:
            if ordinary_set.side_precomputed_anchor_state is None:
                raise ValueError(
                    "precomputed Road anchor context lacks business state"
                )
            group_anchor_state = _scatter_side_anchor_states(
                ordinary_set.side_precomputed_anchor_state,
                ordinary_set.side_group_indices,
                group_count=batch.ordinary_plan_mask.shape[1],
            )
            ordinary_business = (
                ordinary_business_states_from_anchor_state(
                    group_anchor_state,
                    group_probabilities,
                )
            )
        else:
            ordinary_business = ordinary_free_run_business_states(
                base_outputs,
                batch,
                group_probabilities,
                anchor_gate_pass_threshold=(
                    self.config.anchor_gate_pass_threshold
                ),
                no_evidence_probability_threshold=(
                    self.config.no_evidence_probability_threshold
                ),
            )
        side_effective_decisions = _gather_group_indices(
            ordinary_business["effective_decision"],
            ordinary_set.side_group_indices,
        )
        business_plan_type, business_ready = (
            advance_right_plan_type_from_ordinary(
                side_effective_decisions[:, 0:1],
                side_effective_decisions[:, 1:2],
            )
        )
        business_plan_mask = advance_right_business_plan_mask(
            batch.advance_right_plan_features,
            batch.advance_right_plan_mask,
            business_plan_type,
        )
        conditional_base = _conditional_advance_logits(base_outputs)
        if self.config.stop_gradient_at_business_boundaries:
            conditional_base = conditional_base.detach()
        advance_objects = _gather_groups(
            base_object_embeddings,
            batch.advance_right_object_indices,
        )
        advance_side_context = side_context
        advance_decision_probabilities = decision_probabilities
        if self.config.stop_gradient_at_business_boundaries:
            advance_side_context = advance_side_context.detach()
            advance_decision_probabilities = (
                advance_decision_probabilities.detach()
            )
        advance_context = torch.cat(
            (
                advance_objects,
                advance_side_context[:, 0:1],
                advance_side_context[:, 1:2],
                advance_decision_probabilities[:, 0:1],
                advance_decision_probabilities[:, 1:2],
            ),
            dim=-1,
        )
        advance_plans = self.advance_plan_stem(
            batch.advance_right_plan_features
        )
        expanded_advance = advance_context.unsqueeze(2).expand(
            -1,
            -1,
            advance_plans.shape[2],
            -1,
        )
        advance_residual = self.advance_residual_head(
            torch.cat((advance_plans, expanded_advance), dim=-1)
        ).squeeze(-1)
        conditional_logits = (
            conditional_base.masked_fill(
                ~batch.advance_right_plan_mask,
                0.0,
            )
            + advance_residual
        ).masked_fill(
            ~batch.advance_right_plan_mask,
            float("-inf"),
        )
        business_logits = apply_advance_right_business_mask(
            conditional_logits,
            business_plan_mask,
        )
        return {
            **base_outputs,
            **ordinary_outputs,
            "ordinary_group_decision_probabilities": group_probabilities,
            "ordinary_raw_business_decisions": ordinary_business[
                "raw_decision"
            ],
            "ordinary_effective_business_decisions": ordinary_business[
                "effective_decision"
            ],
            "ordinary_anchor_business_state": ordinary_business[
                "anchor_state"
            ],
            "advance_right_source_business_decision": (
                side_effective_decisions[:, 0:1]
            ),
            "advance_right_target_business_decision": (
                side_effective_decisions[:, 1:2]
            ),
            "advance_right_business_plan_type": business_plan_type,
            "advance_right_business_ready": business_ready,
            "advance_right_business_plan_mask": business_plan_mask,
            "advance_right_conditional_plan_logits": conditional_logits,
            "advance_right_business_plan_logits": business_logits,
            "advance_right_plan_logits": conditional_logits,
        }

    def decode_ordinary_sets(
        self,
        ordinary_set: EndToEndOrdinarySetBatch,
        ordinary_evidence: torch.Tensor,
        *,
        anchor_outputs: Mapping[str, torch.Tensor] | None = None,
    ) -> dict[str, torch.Tensor]:
        if ordinary_evidence.shape != (
            *ordinary_set.side_group_indices.shape,
            self.config.hidden_dim,
        ):
            raise ValueError("ordinary evidence embedding shape differs")
        road_encoded = self._encode_roads(
            ordinary_set,
            anchor_outputs=anchor_outputs,
        )
        road_mean, road_max = _masked_pool(
            road_encoded,
            ordinary_set.side_road_mask,
        )
        object_context = self.object_stem(
            ordinary_set.side_object_values
        )
        side_context = self.side_context(
            torch.cat(
                (
                    ordinary_evidence,
                    object_context,
                    road_mean,
                    road_max,
                ),
                dim=-1,
            )
        )
        decision_logits = self.decision_head(side_context)
        decision_probabilities = torch.softmax(decision_logits, dim=-1)
        expanded_context = side_context.unsqueeze(2).expand(
            -1,
            -1,
            road_encoded.shape[2],
            -1,
        )
        expanded_decisions = decision_probabilities.unsqueeze(2).expand(
            -1,
            -1,
            road_encoded.shape[2],
            -1,
        )
        road_business_inputs = torch.cat(
            (
                road_encoded,
                expanded_context,
                expanded_decisions,
            ),
            dim=-1,
        )
        base_member_logits = self.member_head(
            road_business_inputs
        ).squeeze(-1)
        detached_business_inputs = road_business_inputs.detach()
        ownership_logits = self.ownership_head(detached_business_inputs)
        business_role_logits = self.business_role_head(
            detached_business_inputs
        )
        member_logits = base_member_logits
        member_logits = member_logits.masked_fill(
            ~ordinary_set.side_road_mask,
            0.0,
        )
        cardinality_logits = self.cardinality_head(side_context)
        cardinality_predictions = decode_ordinary_road_cardinality(
            cardinality_logits,
            mode=self.config.cardinality_mode,
        )
        access_encoded = self.access_stem(
            ordinary_set.side_access_values
        )
        access_context = side_context.unsqueeze(2).expand(
            -1,
            -1,
            access_encoded.shape[2],
            -1,
        )
        access_logits = self.access_head(
            torch.cat((access_encoded, access_context), dim=-1)
        ).squeeze(-1)
        access_logits = access_logits.masked_fill(
            ~ordinary_set.side_access_mask,
            float("-inf"),
        )
        return {
            "ordinary_side_decision_logits": decision_logits,
            "ordinary_side_decision_probabilities": (
                decision_probabilities
            ),
            "ordinary_side_road_member_logits": member_logits,
            "ordinary_side_road_base_member_logits": (
                base_member_logits.masked_fill(
                    ~ordinary_set.side_road_mask,
                    0.0,
                )
            ),
            "ordinary_side_road_ownership_logits": (
                ownership_logits.masked_fill(
                    ~ordinary_set.side_road_mask.unsqueeze(-1),
                    0.0,
                )
            ),
            "ordinary_side_road_business_role_logits": (
                business_role_logits.masked_fill(
                    ~ordinary_set.side_road_mask.unsqueeze(-1),
                    0.0,
                )
            ),
            "ordinary_side_road_cardinality_logits": cardinality_logits,
            "ordinary_side_road_cardinality_predictions": (
                cardinality_predictions
            ),
            "ordinary_side_access_logits": access_logits,
            "ordinary_side_context": side_context,
            "_ordinary_road_encoded": road_encoded,
            "_ordinary_expansion_context": (
                self.expansion_context_stem(side_context)
            ),
        }

    def decode_ordinary_next(
        self,
        encoded_outputs: Mapping[str, torch.Tensor],
        ordinary_set: EndToEndOrdinarySetBatch,
        selected_masks: torch.Tensor,
        *,
        candidate_mask: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        road_encoded = encoded_outputs["_ordinary_road_encoded"]
        expansion_context = encoded_outputs[
            "_ordinary_expansion_context"
        ]
        if selected_masks.ndim == 3:
            selected_masks = selected_masks.unsqueeze(2)
        if selected_masks.ndim != 4:
            raise ValueError("ordinary expansion selected-mask rank differs")
        batch_size, side_count, road_count, hidden_dim = (
            road_encoded.shape
        )
        expected = (
            batch_size,
            side_count,
            selected_masks.shape[2],
            road_count,
        )
        if selected_masks.shape != expected:
            raise ValueError("ordinary expansion selected-mask shape differs")
        allowed = (
            ordinary_set.side_road_mask
            if candidate_mask is None
            else candidate_mask
        )
        if allowed.shape != ordinary_set.side_road_mask.shape:
            raise ValueError("ordinary expansion candidate-mask shape differs")
        allowed = allowed & ordinary_set.side_road_mask
        selected_masks = selected_masks & allowed.unsqueeze(2)
        flat_count = batch_size * side_count
        state_count = selected_masks.shape[2]
        candidates = road_encoded.reshape(
            flat_count,
            road_count,
            hidden_dim,
        )
        contexts = expansion_context.reshape(flat_count, hidden_dim)
        selected = selected_masks.reshape(
            flat_count,
            state_count,
            road_count,
        )
        flat_allowed = allowed.reshape(flat_count, road_count)
        relations = ordinary_set.side_road_relation_values.reshape(
            flat_count,
            road_count,
            road_count,
            ORDINARY_SET_ROAD_RELATION_DIM,
        )
        selected_float = selected.to(candidates.dtype)
        selected_count = selected.sum(dim=-1)
        selected_mean = torch.einsum(
            "bsn,bnh->bsh",
            selected_float,
            candidates,
        ) / selected_count.clamp_min(1).unsqueeze(-1).to(
            candidates.dtype
        )
        selected_maximum = candidates.unsqueeze(1).masked_fill(
            ~selected.unsqueeze(-1),
            torch.finfo(candidates.dtype).min,
        ).amax(dim=2)
        selected_maximum = torch.where(
            selected_count.unsqueeze(-1) > 0,
            selected_maximum,
            torch.zeros_like(selected_maximum),
        )
        relation_exists = relations.abs().sum(dim=-1).gt(0.0)
        relation_mask = (
            relation_exists.unsqueeze(1)
            & selected.unsqueeze(2)
            & flat_allowed.unsqueeze(1).unsqueeze(-1)
        )
        relation_float = relation_mask.to(relations.dtype)
        relation_count = relation_mask.sum(dim=-1)
        relation_mean = torch.einsum(
            "bsij,bijr->bsir",
            relation_float,
            relations,
        ) / relation_count.clamp_min(1).unsqueeze(-1).to(
            relations.dtype
        )
        relation_maximum = relations.unsqueeze(1).masked_fill(
            ~relation_mask.unsqueeze(-1),
            torch.finfo(relations.dtype).min,
        ).amax(dim=3)
        relation_maximum = torch.where(
            relation_count.unsqueeze(-1) > 0,
            relation_maximum,
            torch.zeros_like(relation_maximum),
        )
        valid_count = flat_allowed.sum(dim=-1).clamp_min(1)
        count_features = torch.stack(
            (
                selected_count.to(candidates.dtype)
                / valid_count.unsqueeze(-1).to(candidates.dtype),
                torch.log1p(selected_count.to(candidates.dtype))
                / 4.219507705176107,
                selected_count.gt(0).to(candidates.dtype),
            ),
            dim=-1,
        )
        relation_fraction = (
            relation_count.to(candidates.dtype)
            / selected_count.clamp_min(1)
            .unsqueeze(-1)
            .to(candidates.dtype)
        ).unsqueeze(-1)
        candidate_values = candidates.unsqueeze(1).expand(
            -1,
            state_count,
            -1,
            -1,
        )
        context_values = contexts.unsqueeze(1).unsqueeze(2).expand(
            -1,
            state_count,
            road_count,
            -1,
        )
        mean_values = selected_mean.unsqueeze(2).expand(
            -1,
            -1,
            road_count,
            -1,
        )
        maximum_values = selected_maximum.unsqueeze(2).expand(
            -1,
            -1,
            road_count,
            -1,
        )
        count_values = count_features.unsqueeze(2).expand(
            -1,
            -1,
            road_count,
            -1,
        )
        next_logits = self.next_road_head(
            torch.cat(
                (
                    candidate_values,
                    context_values,
                    mean_values,
                    maximum_values,
                    relation_mean,
                    relation_maximum,
                    count_values,
                    relation_fraction,
                ),
                dim=-1,
            )
        ).squeeze(-1)
        next_logits = next_logits.masked_fill(
            ~flat_allowed.unsqueeze(1) | selected,
            torch.finfo(next_logits.dtype).min,
        )
        stop_logits = self.stop_head(
            torch.cat(
                (
                    contexts.unsqueeze(1).expand(-1, state_count, -1),
                    selected_mean,
                    selected_maximum,
                    count_features,
                ),
                dim=-1,
            )
        ).squeeze(-1)
        return {
            "next_road_logits": next_logits.reshape(
                batch_size,
                side_count,
                state_count,
                road_count,
            ),
            "stop_logits": stop_logits.reshape(
                batch_size,
                side_count,
                state_count,
            ),
            "selected_count": selected_count.reshape(
                batch_size,
                side_count,
                state_count,
            ),
        }

    def greedy_decode_ordinary_set(
        self,
        encoded_outputs: Mapping[str, torch.Tensor],
        ordinary_set: EndToEndOrdinarySetBatch,
        effective_decisions: torch.Tensor,
        *,
        stop_logit_bias: float = 0.0,
        initial_selected_mask: torch.Tensor | None = None,
    ) -> dict[str, torch.Tensor]:
        if effective_decisions.shape != ordinary_set.side_group_indices.shape:
            raise ValueError("ordinary expansion decision shape differs")
        sources = ordinary_set.side_road_source_indices
        allowed = ordinary_set.side_road_mask & (
            (
                effective_decisions.unsqueeze(-1)
                == ORDINARY_SET_SOURCE_SWSD
            )
            & sources.eq(ORDINARY_SET_SOURCE_SWSD)
            | (
                effective_decisions.unsqueeze(-1)
                == ORDINARY_SET_SOURCE_RCSD
            )
            & sources.eq(ORDINARY_SET_SOURCE_RCSD)
        )
        if initial_selected_mask is None:
            initial_selected_mask = torch.zeros_like(allowed)
        if initial_selected_mask.shape != allowed.shape:
            raise ValueError("ordinary expansion initial seed shape differs")
        selected = initial_selected_mask & allowed
        active = allowed.any(dim=-1)
        stopped = ~active
        confidence = torch.ones(
            active.shape,
            dtype=ordinary_set.side_road_values.dtype,
            device=ordinary_set.side_road_values.device,
        )
        road_count = allowed.shape[-1]
        for _ in range(road_count + 1):
            if not bool(active.any()):
                break
            step = self.decode_ordinary_next(
                encoded_outputs,
                ordinary_set,
                selected,
                candidate_mask=allowed,
            )
            logits = torch.cat(
                (
                    step["next_road_logits"].squeeze(2),
                    (
                        step["stop_logits"].squeeze(2)
                        + float(stop_logit_bias)
                    ).unsqueeze(-1),
                ),
                dim=-1,
            )
            probabilities = torch.softmax(logits, dim=-1)
            chosen_probability, chosen = probabilities.max(dim=-1)
            confidence = torch.where(
                active,
                torch.minimum(confidence, chosen_probability),
                confidence,
            )
            stop = chosen.eq(road_count)
            add = active & ~stop
            if bool(add.any()):
                batch_indices, side_indices = add.nonzero(
                    as_tuple=True
                )
                selected[
                    batch_indices,
                    side_indices,
                    chosen[batch_indices, side_indices],
                ] = True
            stopped |= active & stop
            active &= ~stop
        return {
            "selected_mask": selected,
            "stopped": stopped,
            "confidence": confidence,
            "candidate_mask": allowed,
        }

    def _forward_base(
        self,
        batch: TargetABatchTensors,
        *,
        advance_right_road_member_values: torch.Tensor | None,
        advance_right_road_member_mask: torch.Tensor | None,
        advance_right_plan_membership: torch.Tensor | None,
    ) -> Mapping[str, torch.Tensor]:
        road_arguments = (
            advance_right_road_member_values,
            advance_right_road_member_mask,
            advance_right_plan_membership,
        )
        if all(value is None for value in road_arguments):
            return self.base(batch)
        if any(value is None for value in road_arguments):
            raise ValueError("conditional AdvanceRight Road-set input is partial")
        return self.base(
            batch,
            road_member_values=advance_right_road_member_values,
            road_member_mask=advance_right_road_member_mask,
            plan_membership=advance_right_plan_membership,
        )

    def _encode_roads(
        self,
        ordinary_set: EndToEndOrdinarySetBatch,
        *,
        anchor_outputs: Mapping[str, torch.Tensor] | None,
    ) -> torch.Tensor:
        values = ordinary_set.side_road_values
        mask = ordinary_set.side_road_mask
        batch_size, side_count, road_count, _ = values.shape
        flat_values = values.reshape(
            batch_size * side_count,
            road_count,
            values.shape[-1],
        )
        flat_mask = mask.reshape(batch_size * side_count, road_count)
        encoded = self.road_stem(flat_values)
        if ordinary_set.side_precomputed_anchor_context is not None:
            if anchor_outputs is not None:
                raise ValueError(
                    "ordinary Road anchor context has two sources"
                )
            anchor_context = ordinary_set.side_precomputed_anchor_context
        else:
            anchor_context = self._same_forward_road_anchor_context(
                ordinary_set,
                anchor_outputs=anchor_outputs,
            )
        anchor_context = anchor_context.reshape(
            batch_size * side_count,
            road_count,
            8,
        )
        encoded = (
            encoded
            + self.road_anchor_relation_scale
            * self.road_anchor_relation_stem(anchor_context)
        )
        relations = ordinary_set.side_road_relation_values.reshape(
            batch_size * side_count,
            road_count,
            road_count,
            ORDINARY_SET_ROAD_RELATION_DIM,
        )
        relation_mask = relations.abs().sum(dim=-1).gt(0.0)
        relation_encoded = self.relation_stem(relations)
        relation_weights = relation_mask.unsqueeze(-1).to(encoded.dtype)
        messages = (
            relation_encoded * relation_weights
        ).sum(dim=2) / relation_weights.sum(dim=2).clamp_min(1.0)
        encoded = encoded + self.relation_fusion(
            torch.cat((encoded, messages), dim=-1)
        )
        safe_mask = flat_mask.clone()
        empty = ~safe_mask.any(dim=-1)
        if bool(empty.any()):
            safe_mask[empty, 0] = True
        encoded = self.road_set_encoder(
            encoded,
            src_key_padding_mask=~safe_mask,
        )
        encoded = encoded * flat_mask.unsqueeze(-1).to(encoded.dtype)
        return encoded.reshape(
            batch_size,
            side_count,
            road_count,
            encoded.shape[-1],
        )

    @staticmethod
    def _same_forward_road_anchor_context(
        ordinary_set: EndToEndOrdinarySetBatch,
        *,
        anchor_outputs: Mapping[str, torch.Tensor] | None,
    ) -> torch.Tensor:
        relations = ordinary_set.side_anchor_candidate_relation_values
        required = ordinary_set.side_required_anchor_indices
        candidate_mask = ordinary_set.side_anchor_candidate_mask
        shape = (*ordinary_set.side_road_mask.shape, 8)
        if (
            anchor_outputs is None
            or relations is None
            or required is None
            or candidate_mask is None
        ):
            return torch.zeros(
                shape,
                dtype=ordinary_set.side_road_values.dtype,
                device=ordinary_set.side_road_values.device,
            )
        selected = anchor_outputs.get(
            "anchor_selected_candidate_indices"
        )
        success = anchor_outputs.get("anchor_selection_success")
        if selected is None or success is None:
            raise ValueError(
                "same-forward anchor outputs are incomplete"
            )
        batch_size, side_count, road_count, required_count = (
            relations.shape[:4]
        )
        if (
            selected.shape[0] != batch_size
            or success.shape != selected.shape
            or required.shape
            != (batch_size, side_count, required_count)
        ):
            raise ValueError(
                "same-forward Road-anchor indices differ"
            )
        safe_required = required.clamp_min(0)
        flat_required = safe_required.reshape(batch_size, -1)
        selected_required = torch.gather(
            selected,
            1,
            flat_required,
        ).reshape(batch_size, side_count, required_count)
        success_required = torch.gather(
            success,
            1,
            flat_required,
        ).reshape(batch_size, side_count, required_count)
        maximum_candidate = relations.shape[4]
        safe_selected = selected_required.clamp(
            min=0,
            max=maximum_candidate - 1,
        )
        selected_valid = torch.gather(
            candidate_mask,
            3,
            safe_selected.unsqueeze(-1),
        ).squeeze(-1)
        relation_index = safe_selected.unsqueeze(2).unsqueeze(
            -1
        ).unsqueeze(-1).expand(
            batch_size,
            side_count,
            road_count,
            required_count,
            1,
            relations.shape[-1],
        )
        chosen_relations = torch.gather(
            relations,
            4,
            relation_index,
        ).squeeze(4)
        active = (
            required.ge(0)
            & selected_valid
            & success_required
        )
        active_values = active.unsqueeze(2).unsqueeze(-1).to(
            chosen_relations.dtype
        )
        relation_mean = (
            chosen_relations * active_values
        ).sum(dim=3) / active_values.sum(dim=3).clamp_min(1.0)
        relation_maximum = chosen_relations.masked_fill(
            ~active.unsqueeze(2).unsqueeze(-1),
            torch.finfo(chosen_relations.dtype).min,
        ).amax(dim=3)
        relation_maximum = torch.where(
            active.any(dim=-1).unsqueeze(2).unsqueeze(-1),
            relation_maximum,
            torch.zeros_like(relation_maximum),
        )
        return torch.cat((relation_mean, relation_maximum), dim=-1)


def compute_end_to_end_ordinary_set_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: EndToEndOrdinarySetBatch,
    *,
    decision_class_weights: torch.Tensor | None = None,
    cardinality_mode: str = "categorical",
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    normalization_mask = (
        batch.decision_task_mask
        | batch.road_task_mask
        | batch.access_task_mask
    )
    if bool(normalization_mask.any()):
        weights = batch.sample_weights / batch.sample_weights[
            normalization_mask
        ].mean().clamp_min(1e-6)
    else:
        weights = torch.zeros_like(batch.sample_weights)
    decision_losses = nn.functional.cross_entropy(
        outputs["ordinary_side_decision_logits"].reshape(
            -1,
            ORDINARY_DECISION_COUNT,
        ),
        batch.decision_targets.reshape(-1),
        weight=decision_class_weights,
        reduction="none",
    ).reshape_as(batch.decision_targets)
    decision_loss = _masked_weighted_mean(
        decision_losses,
        batch.decision_task_mask,
        weights,
    )

    member_logits = outputs["ordinary_side_road_member_logits"]
    member_targets = batch.road_member_targets.to(member_logits.dtype)
    road_active = (
        batch.side_road_mask
        & batch.road_task_mask.unsqueeze(-1)
    )
    positive_count = (
        member_targets * road_active.to(member_targets.dtype)
    ).sum(dim=-1)
    negative_count = road_active.sum(dim=-1).to(
        member_targets.dtype
    ) - positive_count
    positive_weight = (
        negative_count / positive_count.clamp_min(1.0)
    ).clamp(min=1.0, max=8.0)
    member_weights = torch.where(
        member_targets.gt(0.5),
        positive_weight.unsqueeze(-1),
        torch.ones_like(member_targets),
    )
    member_losses = nn.functional.binary_cross_entropy_with_logits(
        member_logits,
        member_targets,
        reduction="none",
    ) * member_weights
    per_side_member = (
        member_losses * road_active.to(member_losses.dtype)
    ).sum(dim=-1) / road_active.sum(dim=-1).clamp_min(1)
    member_loss = _masked_weighted_mean(
        per_side_member,
        batch.road_task_mask,
        weights,
    )

    cardinality_logits = outputs[
        "ordinary_side_road_cardinality_logits"
    ]
    if cardinality_mode == "categorical":
        cardinality_losses = nn.functional.cross_entropy(
            cardinality_logits.reshape(
                -1,
                cardinality_logits.shape[-1],
            ),
            batch.road_cardinality_targets.clamp_max(
                cardinality_logits.shape[-1] - 1
            ).reshape(-1),
            reduction="none",
        ).reshape_as(batch.road_cardinality_targets)
    elif cardinality_mode == "ordinal":
        cardinality_losses = _ordinal_cardinality_losses(
            cardinality_logits,
            batch.road_cardinality_targets,
        )
    else:
        raise ValueError("ordinary-set cardinality mode is invalid")
    cardinality_loss = _masked_weighted_mean(
        cardinality_losses,
        batch.road_task_mask,
        weights,
    )

    access_logits = outputs["ordinary_side_access_logits"]
    safe_access_logits = access_logits.masked_fill(
        ~batch.side_access_mask,
        float("-inf"),
    )
    access_log_probabilities = torch.log_softmax(
        safe_access_logits,
        dim=-1,
    )
    acceptable_access = access_log_probabilities.masked_fill(
        ~batch.access_targets,
        float("-inf"),
    )
    access_losses = -torch.logsumexp(acceptable_access, dim=-1)
    access_losses = access_losses.masked_fill(
        ~batch.access_task_mask,
        0.0,
    )
    access_loss = _masked_weighted_mean(
        access_losses,
        batch.access_task_mask,
        weights,
    )
    ownership_loss = _optional_road_business_loss(
        outputs["ordinary_side_road_ownership_logits"],
        batch.road_ownership_targets,
        batch.road_ownership_task_mask,
        batch.road_ownership_sample_weights,
    )
    role_loss = _optional_road_business_loss(
        outputs["ordinary_side_road_business_role_logits"],
        batch.road_business_role_targets,
        batch.road_business_role_task_mask,
        batch.road_business_role_sample_weights,
    )
    total = (
        decision_loss
        + member_loss
        + 0.50 * cardinality_loss
        + 0.50 * access_loss
        + 0.50 * ownership_loss
        + 0.50 * role_loss
    )
    parts = {
        "ordinary_side_decision_loss": decision_loss,
        "ordinary_side_member_loss": member_loss,
        "ordinary_side_cardinality_loss": cardinality_loss,
        "ordinary_side_access_loss": access_loss,
    }
    if batch.road_ownership_targets is not None:
        parts["ordinary_side_ownership_loss"] = ownership_loss
        parts["ordinary_side_business_role_loss"] = role_loss
    return total, parts


def decode_ordinary_road_cardinality(
    logits: torch.Tensor,
    *,
    mode: str,
) -> torch.Tensor:
    """Decode a count without reading truth or downstream Road selection."""
    if logits.ndim < 2 or logits.shape[-1] < 1:
        raise ValueError("ordinary cardinality logits are invalid")
    if mode == "categorical":
        return logits.argmax(dim=-1)
    if mode != "ordinal":
        raise ValueError("ordinary-set cardinality mode is invalid")
    positive_prefix = logits.gt(0.0).to(torch.long).cumprod(dim=-1)
    return positive_prefix.sum(dim=-1)


def _ordinal_cardinality_losses(
    logits: torch.Tensor,
    targets: torch.Tensor,
) -> torch.Tensor:
    thresholds = torch.arange(
        logits.shape[-1],
        device=logits.device,
    )
    ordinal_targets = targets.clamp_max(logits.shape[-1]).unsqueeze(
        -1
    ).gt(thresholds)
    losses = nn.functional.binary_cross_entropy_with_logits(
        logits,
        ordinal_targets.to(logits.dtype),
        reduction="none",
    )
    positive = ordinal_targets
    negative = ~positive
    positive_loss = (
        (losses * positive.to(losses.dtype)).sum(dim=-1)
        / positive.sum(dim=-1).clamp_min(1)
    )
    negative_loss = (
        (losses * negative.to(losses.dtype)).sum(dim=-1)
        / negative.sum(dim=-1).clamp_min(1)
    )
    balanced = torch.where(
        positive.any(dim=-1),
        0.5 * (positive_loss + negative_loss),
        negative_loss,
    )
    monotonic = nn.functional.relu(
        logits[..., 1:] - logits[..., :-1]
    ).mean(dim=-1)
    return balanced + 0.25 * monotonic


def _optional_road_business_loss(
    logits: torch.Tensor,
    targets: torch.Tensor | None,
    task_mask: torch.Tensor | None,
    sample_weights: torch.Tensor | None,
) -> torch.Tensor:
    if targets is None or task_mask is None or sample_weights is None:
        return logits.sum() * 0.0
    losses = nn.functional.cross_entropy(
        logits.reshape(-1, logits.shape[-1]),
        targets.reshape(-1),
        reduction="none",
    ).reshape_as(targets)
    per_side = (
        losses * task_mask.to(losses.dtype)
    ).sum(dim=-1) / task_mask.sum(dim=-1).clamp_min(1)
    side_mask = task_mask.any(dim=-1)
    if not bool(side_mask.any()):
        return logits.sum() * 0.0
    normalized_weights = sample_weights / sample_weights[
        side_mask
    ].mean().clamp_min(1e-6)
    return _masked_weighted_mean(
        per_side,
        side_mask,
        normalized_weights,
    )


def _conditional_advance_logits(
    outputs: Mapping[str, torch.Tensor],
) -> torch.Tensor:
    for key in (
        "advance_right_conditional_road_set_logits",
        "advance_right_conditional_plan_logits",
        "advance_right_recall_plan_logits",
        "advance_right_plan_logits",
    ):
        if key in outputs:
            return outputs[key]
    raise ValueError("base model lacks conditional AdvanceRight logits")


def _head(
    input_dim: int,
    hidden_dim: int,
    output_dim: int,
    dropout: float,
) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim * 2),
        nn.GELU(),
        nn.LayerNorm(hidden_dim * 2),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim * 2, output_dim),
    )


def _expansion_head(
    input_dim: int,
    context_dim: int,
    hidden_dim: int,
    dropout: float,
) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, context_dim),
        nn.GELU(),
        nn.LayerNorm(context_dim),
        nn.Dropout(dropout),
        nn.Linear(context_dim, hidden_dim),
        nn.GELU(),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim, 1),
    )


def _masked_pool(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    weights = mask.unsqueeze(-1).to(values.dtype)
    mean = (values * weights).sum(dim=2) / weights.sum(
        dim=2
    ).clamp_min(1.0)
    maximum = values.masked_fill(
        ~mask.unsqueeze(-1),
        torch.finfo(values.dtype).min,
    ).amax(dim=2)
    maximum = maximum.masked_fill(
        ~mask.any(dim=2).unsqueeze(-1),
        0.0,
    )
    return mean, maximum


def _gather_groups(
    values: torch.Tensor,
    indices: torch.Tensor,
) -> torch.Tensor:
    if values.shape[0] != indices.shape[0]:
        raise ValueError("ordinary-set group gather batch differs")
    safe = indices.clamp_min(0)
    gathered = torch.gather(
        values,
        1,
        safe.unsqueeze(-1).expand(*safe.shape, values.shape[-1]),
    )
    return gathered * indices.ge(0).unsqueeze(-1).to(gathered.dtype)


def _gather_group_indices(
    values: torch.Tensor,
    indices: torch.Tensor,
) -> torch.Tensor:
    return _gather_groups(values.unsqueeze(-1), indices).squeeze(-1).long()


def _scatter_side_probabilities(
    side_probabilities: torch.Tensor,
    group_indices: torch.Tensor,
    *,
    group_count: int,
) -> torch.Tensor:
    batch_size = side_probabilities.shape[0]
    result = torch.zeros(
        (
            batch_size,
            group_count,
            side_probabilities.shape[-1],
        ),
        dtype=side_probabilities.dtype,
        device=side_probabilities.device,
    )
    counts = torch.zeros(
        (batch_size, group_count, 1),
        dtype=side_probabilities.dtype,
        device=side_probabilities.device,
    )
    safe = group_indices.clamp_min(0)
    result.scatter_add_(
        1,
        safe.unsqueeze(-1).expand_as(side_probabilities),
        side_probabilities
        * group_indices.ge(0).unsqueeze(-1).to(side_probabilities.dtype),
    )
    counts.scatter_add_(
        1,
        safe.unsqueeze(-1),
        group_indices.ge(0).unsqueeze(-1).to(side_probabilities.dtype),
    )
    return result / counts.clamp_min(1.0)


def _scatter_side_anchor_states(
    side_states: torch.Tensor,
    group_indices: torch.Tensor,
    *,
    group_count: int,
) -> torch.Tensor:
    if side_states.shape != group_indices.shape:
        raise ValueError("ordinary anchor-state scatter shape differs")
    safe = group_indices.clamp_min(0)
    valid = group_indices.ge(0)
    votes = nn.functional.one_hot(
        side_states,
        num_classes=3,
    ).to(torch.long)
    votes = votes * valid.unsqueeze(-1).to(votes.dtype)
    counts = torch.zeros(
        (side_states.shape[0], group_count, 3),
        dtype=torch.long,
        device=side_states.device,
    )
    counts.scatter_add_(
        1,
        safe.unsqueeze(-1).expand_as(votes),
        votes,
    )
    if bool(counts.gt(0).sum(dim=-1).gt(1).any()):
        raise ValueError("shared ordinary Segment has conflicting OOF anchors")
    result = counts.argmax(dim=-1)
    return result.masked_fill(
        counts.sum(dim=-1).eq(0),
        ORDINARY_ANCHOR_UNRESOLVED,
    )


def _masked_weighted_mean(
    values: torch.Tensor,
    mask: torch.Tensor,
    weights: torch.Tensor,
) -> torch.Tensor:
    active = mask.to(values.dtype) * weights
    return (values * active).sum() / active.sum().clamp_min(1.0)


__all__ = [
    "TargetAEndToEndOrdinarySetConfig",
    "TargetAEndToEndOrdinarySetNetwork",
    "compute_end_to_end_ordinary_set_loss",
    "decode_ordinary_road_cardinality",
]
