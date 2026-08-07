from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    advance_right_business_plan_mask,
    advance_right_plan_type_from_ordinary,
    apply_advance_right_business_mask,
    ordinary_free_run_business_states,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_recall_data import (
    ADVANCE_RIGHT_RECALL_CARDINALITY_FEATURE_INDEX,
    ADVANCE_RIGHT_RECALL_RCSD_FEATURE_INDEX,
    ADVANCE_RIGHT_RECALL_SWSD_FEATURE_INDEX,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_ABSTAIN,
    ORDINARY_DECISION_COUNT,
    ORDINARY_DECISION_KEEP_SWSD,
    ORDINARY_DECISION_USE_RCSD,
    TargetABatchTensors,
    TargetAJointNetwork,
)


@dataclass(frozen=True)
class TargetAEndToEndRecallConfig:
    hidden_dim: int
    reranker_hidden_dim: int = 96
    max_road_cardinality: int = 12
    dropout: float = 0.10
    no_evidence_probability_threshold: float = 1.0

    def validate(self) -> None:
        if min(
            self.hidden_dim,
            self.reranker_hidden_dim,
            self.max_road_cardinality,
        ) < 1:
            raise ValueError("end-to-end recall dimensions must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("end-to-end recall dropout is invalid")
        if not 0.0 <= self.no_evidence_probability_threshold <= 1.0:
            raise ValueError("end-to-end NO_EVIDENCE threshold is invalid")


class TargetAEndToEndRecallNetwork(nn.Module):
    """Rerank complete AR Road sets from locked ordinary free-run states."""

    def __init__(
        self,
        backbone: TargetAJointNetwork,
        config: TargetAEndToEndRecallConfig,
    ) -> None:
        super().__init__()
        config.validate()
        if backbone.config.hidden_dim != config.hidden_dim:
            raise ValueError("end-to-end recall backbone dimension differs")
        self.backbone = backbone
        self.config = config
        context_dim = 2 * config.hidden_dim + 2 * ORDINARY_DECISION_COUNT
        self.cardinality_head = nn.Sequential(
            nn.Linear(context_dim, config.reranker_hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(
                config.reranker_hidden_dim,
                config.max_road_cardinality + 1,
            ),
        )
        reranker_input_dim = (
            1
            + 2 * ORDINARY_DECISION_COUNT
            + 2
            + 1
            + 1
            + 1
        )
        self.reranker = nn.Sequential(
            nn.Linear(reranker_input_dim, config.reranker_hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.reranker_hidden_dim, 1),
        )
        nn.init.zeros_(self.reranker[-1].weight)
        nn.init.zeros_(self.reranker[-1].bias)
        self.cardinality_scale = nn.Parameter(torch.tensor(0.10))
        self.source_compatibility_scale = nn.Parameter(torch.tensor(0.10))

    def freeze_backbone(self) -> None:
        self.backbone.requires_grad_(False)

    def forward(
        self,
        batch: TargetABatchTensors,
    ) -> dict[str, torch.Tensor]:
        outputs = self.backbone(batch)
        ordinary_probabilities = ordinary_decision_probabilities(
            outputs["ordinary_plan_logits"],
            batch.ordinary_plan_decision_indices,
            batch.ordinary_plan_mask,
        )
        source_probabilities = _gather_groups(
            ordinary_probabilities,
            batch.advance_right_source_indices,
        )
        target_probabilities = _gather_groups(
            ordinary_probabilities,
            batch.advance_right_target_indices,
        )
        source_embeddings = _gather_groups(
            outputs["locked_ordinary_embeddings"],
            batch.advance_right_source_indices,
        )
        target_embeddings = _gather_groups(
            outputs["locked_ordinary_embeddings"],
            batch.advance_right_target_indices,
        )
        decision_context = torch.cat(
            (
                source_embeddings,
                target_embeddings,
                source_probabilities,
                target_probabilities,
            ),
            dim=-1,
        )
        cardinality_logits = self.cardinality_head(decision_context)
        cardinality_log_probabilities = torch.log_softmax(
            cardinality_logits,
            dim=-1,
        )
        plan_features = batch.advance_right_plan_features
        plan_mask = batch.advance_right_plan_mask
        cardinalities = plan_features[
            ...,
            ADVANCE_RIGHT_RECALL_CARDINALITY_FEATURE_INDEX,
        ].round().long().clamp(
            min=0,
            max=self.config.max_road_cardinality,
        )
        cardinality_log_prior = torch.gather(
            cardinality_log_probabilities.unsqueeze(2).expand(
                -1,
                -1,
                plan_features.shape[2],
                -1,
            ),
            -1,
            cardinalities.unsqueeze(-1),
        ).squeeze(-1)
        source_compatibility = _source_compatibility(
            source_probabilities,
            target_probabilities,
            plan_features,
        ).clamp_min(1e-6)
        base_logits = outputs["advance_right_plan_logits"]
        safe_base_logits = base_logits.masked_fill(~plan_mask, 0.0)
        plan_count_feature = (
            cardinalities.to(plan_features.dtype)
            / float(self.config.max_road_cardinality)
        )
        expanded_source = source_probabilities.unsqueeze(2).expand(
            -1,
            -1,
            plan_features.shape[2],
            -1,
        )
        expanded_target = target_probabilities.unsqueeze(2).expand_as(
            expanded_source
        )
        plan_kinds = torch.stack(
            (
                plan_features[
                    ...,
                    ADVANCE_RIGHT_RECALL_SWSD_FEATURE_INDEX,
                ],
                plan_features[
                    ...,
                    ADVANCE_RIGHT_RECALL_RCSD_FEATURE_INDEX,
                ],
            ),
            dim=-1,
        )
        reranker_input = torch.cat(
            (
                safe_base_logits.unsqueeze(-1),
                expanded_source,
                expanded_target,
                plan_kinds,
                plan_count_feature.unsqueeze(-1),
                cardinality_log_prior.unsqueeze(-1),
                source_compatibility.log().unsqueeze(-1),
            ),
            dim=-1,
        )
        residual = self.reranker(reranker_input).squeeze(-1)
        reranked_logits = (
            safe_base_logits
            + residual
            + self.cardinality_scale * cardinality_log_prior
            + self.source_compatibility_scale
            * source_compatibility.log()
        ).masked_fill(~plan_mask, float("-inf"))
        ordinary_business = ordinary_free_run_business_states(
            outputs,
            batch,
            ordinary_probabilities,
            anchor_gate_pass_threshold=(
                self.backbone.config.anchor_gate_pass_threshold
            ),
            no_evidence_probability_threshold=(
                self.config.no_evidence_probability_threshold
            ),
        )
        source_decisions = _gather_group_indices(
            ordinary_business["effective_decision"],
            batch.advance_right_source_indices,
        )
        target_decisions = _gather_group_indices(
            ordinary_business["effective_decision"],
            batch.advance_right_target_indices,
        )
        business_plan_type, business_ready = (
            advance_right_plan_type_from_ordinary(
                source_decisions,
                target_decisions,
            )
        )
        business_plan_mask = advance_right_business_plan_mask(
            plan_features,
            plan_mask,
            business_plan_type,
        )
        business_logits = apply_advance_right_business_mask(
            reranked_logits,
            business_plan_mask,
        )
        return {
            **outputs,
            "advance_right_recall_plan_logits": reranked_logits,
            "advance_right_conditional_plan_logits": reranked_logits,
            "advance_right_business_plan_logits": business_logits,
            "advance_right_business_plan_mask": business_plan_mask,
            "advance_right_business_plan_type": business_plan_type,
            "advance_right_business_ready": business_ready,
            "advance_right_recall_cardinality_logits": cardinality_logits,
            "advance_right_source_decision_probabilities": (
                source_probabilities
            ),
            "advance_right_target_decision_probabilities": (
                target_probabilities
            ),
            "ordinary_raw_business_decisions": ordinary_business[
                "raw_decision"
            ],
            "ordinary_effective_business_decisions": ordinary_business[
                "effective_decision"
            ],
            "ordinary_anchor_business_state": ordinary_business[
                "anchor_state"
            ],
            "advance_right_source_business_decision": source_decisions,
            "advance_right_target_business_decision": target_decisions,
        }


def ordinary_decision_probabilities(
    plan_logits: torch.Tensor,
    decision_indices: torch.Tensor | None,
    plan_mask: torch.Tensor,
) -> torch.Tensor:
    if decision_indices is None:
        raise ValueError("ordinary decision indices are required")
    if (
        plan_logits.shape != plan_mask.shape
        or decision_indices.shape != plan_mask.shape
    ):
        raise ValueError("ordinary decision tensors differ")
    decision_logits = []
    for decision_index in range(ORDINARY_DECISION_COUNT):
        mask = plan_mask & decision_indices.eq(decision_index)
        values = plan_logits.masked_fill(~mask, float("-inf"))
        pooled = torch.logsumexp(values, dim=-1)
        pooled = pooled.masked_fill(~mask.any(dim=-1), float("-inf"))
        decision_logits.append(pooled)
    stacked = torch.stack(decision_logits, dim=-1)
    empty = torch.isneginf(stacked).all(dim=-1)
    safe = stacked.masked_fill(empty.unsqueeze(-1), 0.0)
    probabilities = torch.softmax(safe, dim=-1)
    return probabilities.masked_fill(empty.unsqueeze(-1), 0.0)


def _source_compatibility(
    source: torch.Tensor,
    target: torch.Tensor,
    plan_features: torch.Tensor,
) -> torch.Tensor:
    source_keep = source[..., ORDINARY_DECISION_KEEP_SWSD]
    target_keep = target[..., ORDINARY_DECISION_KEEP_SWSD]
    source_use = source[..., ORDINARY_DECISION_USE_RCSD]
    target_use = target[..., ORDINARY_DECISION_USE_RCSD]
    source_abstain = source[..., ORDINARY_DECISION_ABSTAIN]
    target_abstain = target[..., ORDINARY_DECISION_ABSTAIN]
    swsd = source_keep * target_keep
    rcsd = (
        source_use * target_use
        + source_keep * target_use
        + source_use * target_keep
    )
    unresolved = 1.0 - (source_abstain + target_abstain).clamp_max(1.0)
    swsd_marker = plan_features[
        ...,
        ADVANCE_RIGHT_RECALL_SWSD_FEATURE_INDEX,
    ]
    rcsd_marker = plan_features[
        ...,
        ADVANCE_RIGHT_RECALL_RCSD_FEATURE_INDEX,
    ]
    return (
        swsd_marker * swsd.unsqueeze(-1)
        + rcsd_marker * rcsd.unsqueeze(-1)
    ) * unresolved.unsqueeze(-1)


def _gather_groups(
    values: torch.Tensor,
    indices: torch.Tensor,
) -> torch.Tensor:
    if values.shape[0] != indices.shape[0]:
        raise ValueError("group gather batch differs")
    safe = indices.clamp_min(0)
    gathered = torch.gather(
        values,
        1,
        safe.unsqueeze(-1).expand(
            *safe.shape,
            values.shape[-1],
        ),
    )
    return gathered * indices.ge(0).unsqueeze(-1).to(gathered.dtype)


def _gather_group_indices(
    values: torch.Tensor,
    indices: torch.Tensor,
) -> torch.Tensor:
    return _gather_groups(values.unsqueeze(-1), indices).squeeze(-1).long()


__all__ = [
    "TargetAEndToEndRecallConfig",
    "TargetAEndToEndRecallNetwork",
    "ordinary_decision_probabilities",
]
