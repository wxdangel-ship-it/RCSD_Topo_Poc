from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_recall_data import (
    ADVANCE_RIGHT_RECALL_RCSD_FEATURE_INDEX,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_recall_network import (
    TargetAEndToEndRecallNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    apply_advance_right_business_mask,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_road_set_data import (
    END_TO_END_ROAD_MEMBER_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetABatchTensors,
)


@dataclass(frozen=True)
class TargetAEndToEndRoadSetConfig:
    hidden_dim: int
    road_hidden_dim: int = 96
    max_road_cardinality: int = 12
    dropout: float = 0.10
    source_scale: float = 1.0
    cardinality_scale: float = 1.0
    member_scale: float = 1.0

    def validate(self) -> None:
        if min(
            self.hidden_dim,
            self.road_hidden_dim,
            self.max_road_cardinality,
        ) < 1:
            raise ValueError("factorized Road-set dimensions must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("factorized Road-set dropout is invalid")
        if min(
            self.source_scale,
            self.cardinality_scale,
            self.member_scale,
        ) < 0.0:
            raise ValueError("factorized Road-set scales must be non-negative")


class TargetAEndToEndRoadSetNetwork(nn.Module):
    """Factor complete Road-set choice into source, cardinality and members."""

    def __init__(
        self,
        recall: TargetAEndToEndRecallNetwork,
        config: TargetAEndToEndRoadSetConfig,
    ) -> None:
        super().__init__()
        config.validate()
        if recall.config.hidden_dim != config.hidden_dim:
            raise ValueError("factorized Road-set backbone dimension differs")
        self.recall = recall
        self.config = config
        self.member_encoder = nn.Sequential(
            nn.Linear(
                END_TO_END_ROAD_MEMBER_FEATURE_DIM,
                config.road_hidden_dim * 2,
            ),
            nn.GELU(),
            nn.LayerNorm(config.road_hidden_dim * 2),
            nn.Dropout(config.dropout),
            nn.Linear(
                config.road_hidden_dim * 2,
                config.road_hidden_dim,
            ),
            nn.GELU(),
            nn.LayerNorm(config.road_hidden_dim),
        )
        context_dim = (
            3 * config.hidden_dim
            + 6
            + 2 * config.road_hidden_dim
            + config.max_road_cardinality
            + 1
        )
        self.source_head = _head(
            context_dim,
            config.road_hidden_dim,
            2,
            config.dropout,
        )
        self.cardinality_head = _head(
            context_dim,
            config.road_hidden_dim,
            config.max_road_cardinality + 1,
            config.dropout,
        )
        self.member_head = _head(
            config.road_hidden_dim + context_dim,
            config.road_hidden_dim,
            1,
            config.dropout,
        )

    def freeze_recall(self) -> None:
        self.recall.requires_grad_(False)

    def forward(
        self,
        batch: TargetABatchTensors,
        *,
        road_member_values: torch.Tensor,
        road_member_mask: torch.Tensor,
        plan_membership: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        _validate_road_tensors(
            batch,
            road_member_values=road_member_values,
            road_member_mask=road_member_mask,
            plan_membership=plan_membership,
        )
        outputs = self.recall(batch)
        encoded = self.member_encoder(road_member_values)
        member_mean, member_max = _masked_member_summary(
            encoded,
            road_member_mask,
        )
        candidate_counts = road_member_mask.sum(dim=-1).clamp(
            max=self.config.max_road_cardinality
        )
        count_one_hot = nn.functional.one_hot(
            candidate_counts,
            num_classes=self.config.max_road_cardinality + 1,
        ).to(encoded.dtype)
        advance_objects = _gather(
            outputs["object_embeddings"],
            batch.advance_right_object_indices,
        )
        source = _gather(
            outputs["locked_ordinary_embeddings"],
            batch.advance_right_source_indices,
        )
        target = _gather(
            outputs["locked_ordinary_embeddings"],
            batch.advance_right_target_indices,
        )
        context = torch.cat(
            (
                advance_objects,
                source,
                target,
                outputs["advance_right_source_decision_probabilities"],
                outputs["advance_right_target_decision_probabilities"],
                member_mean,
                member_max,
                count_one_hot,
            ),
            dim=-1,
        )
        source_logits = self.source_head(context)
        cardinality_logits = self.cardinality_head(context)
        expanded_context = context.unsqueeze(2).expand(
            -1,
            -1,
            encoded.shape[2],
            -1,
        )
        member_logits = self.member_head(
            torch.cat((encoded, expanded_context), dim=-1)
        ).squeeze(-1)
        member_logits = member_logits.masked_fill(
            ~road_member_mask,
            0.0,
        )
        source_log_prior = _source_log_prior(
            source_logits,
            batch.advance_right_plan_features,
        )
        cardinality_log_prior = _cardinality_log_prior(
            cardinality_logits,
            plan_membership,
            max_road_cardinality=self.config.max_road_cardinality,
        )
        member_log_prior = _member_log_prior(
            member_logits,
            road_member_mask,
            plan_membership,
        )
        plan_mask = batch.advance_right_plan_mask
        base_logits = outputs[
            "advance_right_recall_plan_logits"
        ].masked_fill(~plan_mask, 0.0)
        selection_logits = (
            base_logits
            + self.config.source_scale * source_log_prior
            + self.config.cardinality_scale * cardinality_log_prior
            + self.config.member_scale * member_log_prior
        ).masked_fill(~plan_mask, float("-inf"))
        business_logits = apply_advance_right_business_mask(
            selection_logits,
            outputs["advance_right_business_plan_mask"],
        )
        return {
            **outputs,
            "advance_right_base_recall_plan_logits": outputs[
                "advance_right_recall_plan_logits"
            ],
            "advance_right_recall_plan_logits": selection_logits,
            "advance_right_conditional_road_set_logits": selection_logits,
            "advance_right_business_road_set_logits": business_logits,
            "advance_right_road_source_logits": source_logits,
            "advance_right_road_cardinality_logits": cardinality_logits,
            "advance_right_road_member_logits": member_logits,
            "advance_right_road_source_log_prior": source_log_prior,
            "advance_right_road_cardinality_log_prior": (
                cardinality_log_prior
            ),
            "advance_right_road_member_log_prior": member_log_prior,
            "advance_right_road_member_embeddings": encoded,
        }


def compose_road_set_logits(
    outputs: dict[str, torch.Tensor],
    *,
    plan_mask: torch.Tensor,
    source_scale: float,
    cardinality_scale: float,
    member_scale: float,
) -> torch.Tensor:
    """Recompose inference scores for inner-fold scale selection."""
    values = (
        outputs["advance_right_base_recall_plan_logits"]
        + source_scale * outputs["advance_right_road_source_log_prior"]
        + cardinality_scale
        * outputs["advance_right_road_cardinality_log_prior"]
        + member_scale * outputs["advance_right_road_member_log_prior"]
    )
    return values.masked_fill(~plan_mask, float("-inf"))


def compose_business_road_set_logits(
    outputs: dict[str, torch.Tensor],
    *,
    plan_mask: torch.Tensor,
    source_scale: float,
    cardinality_scale: float,
    member_scale: float,
) -> torch.Tensor:
    values = compose_road_set_logits(
        outputs,
        plan_mask=plan_mask,
        source_scale=source_scale,
        cardinality_scale=cardinality_scale,
        member_scale=member_scale,
    )
    return apply_advance_right_business_mask(
        values,
        outputs["advance_right_business_plan_mask"],
    )


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


def _validate_road_tensors(
    batch: TargetABatchTensors,
    *,
    road_member_values: torch.Tensor,
    road_member_mask: torch.Tensor,
    plan_membership: torch.Tensor,
) -> None:
    if (
        road_member_values.ndim != 4
        or road_member_values.shape[-1]
        != END_TO_END_ROAD_MEMBER_FEATURE_DIM
    ):
        raise ValueError("factorized Road member value shape differs")
    if (
        road_member_mask.shape != road_member_values.shape[:3]
        or road_member_mask.dtype != torch.bool
    ):
        raise ValueError("factorized Road member mask differs")
    if (
        plan_membership.shape[:3] != batch.advance_right_plan_mask.shape
        or plan_membership.shape[3] != road_member_values.shape[2]
        or plan_membership.dtype != torch.bool
    ):
        raise ValueError("factorized Road plan membership differs")


def _masked_member_summary(
    encoded: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    weights = mask.unsqueeze(-1).to(encoded.dtype)
    mean = (encoded * weights).sum(dim=2) / weights.sum(
        dim=2
    ).clamp_min(1.0)
    maximum = encoded.masked_fill(
        ~mask.unsqueeze(-1),
        torch.finfo(encoded.dtype).min,
    ).amax(dim=2)
    empty = ~mask.any(dim=2)
    maximum = maximum.masked_fill(empty.unsqueeze(-1), 0.0)
    return mean, maximum


def _source_log_prior(
    source_logits: torch.Tensor,
    plan_features: torch.Tensor,
) -> torch.Tensor:
    log_probabilities = torch.log_softmax(source_logits, dim=-1)
    is_rcsd = plan_features[
        ...,
        ADVANCE_RIGHT_RECALL_RCSD_FEATURE_INDEX,
    ].round().long().clamp(0, 1)
    return torch.gather(
        log_probabilities.unsqueeze(2).expand(
            -1,
            -1,
            plan_features.shape[2],
            -1,
        ),
        -1,
        is_rcsd.unsqueeze(-1),
    ).squeeze(-1)


def _cardinality_log_prior(
    cardinality_logits: torch.Tensor,
    plan_membership: torch.Tensor,
    *,
    max_road_cardinality: int,
) -> torch.Tensor:
    cardinalities = plan_membership.sum(dim=-1).clamp(
        max=max_road_cardinality
    )
    log_probabilities = torch.log_softmax(cardinality_logits, dim=-1)
    return torch.gather(
        log_probabilities.unsqueeze(2).expand(
            -1,
            -1,
            plan_membership.shape[2],
            -1,
        ),
        -1,
        cardinalities.unsqueeze(-1),
    ).squeeze(-1)


def _member_log_prior(
    member_logits: torch.Tensor,
    member_mask: torch.Tensor,
    plan_membership: torch.Tensor,
) -> torch.Tensor:
    selected = nn.functional.logsigmoid(member_logits).unsqueeze(2)
    omitted = nn.functional.logsigmoid(-member_logits).unsqueeze(2)
    active = member_mask.unsqueeze(2)
    terms = torch.where(plan_membership, selected, omitted)
    total = (terms * active.to(terms.dtype)).sum(dim=-1)
    return total / active.sum(dim=-1).clamp_min(1).to(total.dtype)


def _gather(values: torch.Tensor, indices: torch.Tensor) -> torch.Tensor:
    if values.shape[0] != indices.shape[0]:
        raise ValueError("factorized Road gather batch differs")
    safe = indices.clamp_min(0)
    gathered = torch.gather(
        values,
        1,
        safe.unsqueeze(-1).expand(*safe.shape, values.shape[-1]),
    )
    return gathered * indices.ge(0).unsqueeze(-1).to(gathered.dtype)


__all__ = [
    "TargetAEndToEndRoadSetConfig",
    "TargetAEndToEndRoadSetNetwork",
    "compose_business_road_set_logits",
    "compose_road_set_logits",
]
