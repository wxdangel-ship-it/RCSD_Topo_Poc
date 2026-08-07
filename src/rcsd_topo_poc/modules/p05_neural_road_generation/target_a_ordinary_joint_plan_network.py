from __future__ import annotations

from typing import Mapping

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_proposals import (
    PLAN_PROPOSAL_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    OrdinaryRoadSetModel,
    _forward_model,
)


ABSTAIN_DECISION_INDEX = 2
JOINT_PLAN_DYNAMIC_FEATURE_DIM = 8


class TargetAOrdinaryJointPlanNetwork(nn.Module):
    """Fine-tune the shared Road encoder through complete-plan selection."""

    def __init__(
        self,
        *,
        base_model: OrdinaryRoadSetModel,
        base_hidden_dim: int,
        plan_hidden_dim: int = 128,
        plan_feedforward_dim: int = 192,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if min(
            base_hidden_dim,
            plan_hidden_dim,
            plan_feedforward_dim,
        ) < 1:
            raise ValueError("ordinary joint plan dimensions are invalid")
        if not 0.0 <= dropout < 1.0:
            raise ValueError("ordinary joint plan dropout is invalid")
        self.base_model = base_model
        self.base_hidden_dim = base_hidden_dim
        plan_input_dim = (
            PLAN_PROPOSAL_FEATURE_DIM
            + base_hidden_dim * 3
            + JOINT_PLAN_DYNAMIC_FEATURE_DIM
        )
        self.plan_encoder = nn.Sequential(
            nn.Linear(plan_input_dim, plan_feedforward_dim),
            nn.GELU(),
            nn.LayerNorm(plan_feedforward_dim),
            nn.Dropout(dropout),
            nn.Linear(plan_feedforward_dim, plan_hidden_dim),
            nn.GELU(),
            nn.LayerNorm(plan_hidden_dim),
            nn.Dropout(dropout),
        )
        self.plan_selection_head = nn.Linear(plan_hidden_dim, 1)
        self.plan_validity_head = nn.Linear(plan_hidden_dim, 1)

    def forward(
        self,
        *,
        base_batch: Mapping[str, torch.Tensor],
        proposal_features: torch.Tensor,
        proposal_valid: torch.Tensor,
        proposal_membership: torch.Tensor,
        proposal_decisions: torch.Tensor,
        proposal_cardinalities: torch.Tensor,
        candidate_sources: torch.Tensor,
    ) -> dict[str, torch.Tensor | Mapping[str, torch.Tensor]]:
        base_outputs = _forward_model(self.base_model, base_batch)
        encoded = base_outputs.get("candidate_encoded")
        context = base_outputs.get("graph_context")
        if encoded is None or context is None:
            raise ValueError(
                "ordinary joint plan needs graph candidate encodings"
            )
        self._validate_inputs(
            base_batch=base_batch,
            encoded=encoded,
            context=context,
            proposal_features=proposal_features,
            proposal_valid=proposal_valid,
            proposal_membership=proposal_membership,
            proposal_decisions=proposal_decisions,
            proposal_cardinalities=proposal_cardinalities,
            candidate_sources=candidate_sources,
        )
        candidate_valid = base_batch["mask"]
        selected = proposal_membership & candidate_valid.unsqueeze(1)
        non_abstain = proposal_decisions < ABSTAIN_DECISION_INDEX
        main_source = proposal_decisions.clamp(
            min=0,
            max=1,
        ).unsqueeze(-1)
        source_candidates = (
            candidate_sources.unsqueeze(1) == main_source
        ) & candidate_valid.unsqueeze(1) & non_abstain.unsqueeze(-1)
        excluded = source_candidates & ~selected
        selected_mean = _masked_candidate_mean(encoded, selected)
        excluded_mean = _masked_candidate_mean(encoded, excluded)
        expanded_context = context.unsqueeze(1).expand(
            -1,
            proposal_features.shape[1],
            -1,
        )
        dynamic = _dynamic_plan_features(
            base_outputs=base_outputs,
            selected=selected,
            excluded=excluded,
            proposal_decisions=proposal_decisions,
            proposal_cardinalities=proposal_cardinalities,
            non_abstain=non_abstain,
        )
        plan_encoded = self.plan_encoder(
            torch.cat(
                (
                    proposal_features,
                    expanded_context,
                    selected_mean,
                    excluded_mean,
                    dynamic,
                ),
                dim=-1,
            )
        )
        selection_logits = self.plan_selection_head(
            plan_encoded
        ).squeeze(-1)
        validity_logits = self.plan_validity_head(
            plan_encoded
        ).squeeze(-1)
        selection_logits = selection_logits.masked_fill(
            ~proposal_valid,
            torch.finfo(selection_logits.dtype).min,
        )
        validity_logits = validity_logits.masked_fill(
            ~proposal_valid,
            0.0,
        )
        return {
            "base_outputs": base_outputs,
            "plan_logits": selection_logits,
            "plan_validity_logits": validity_logits,
            "plan_dynamic_features": dynamic,
        }

    def _validate_inputs(
        self,
        *,
        base_batch: Mapping[str, torch.Tensor],
        encoded: torch.Tensor,
        context: torch.Tensor,
        proposal_features: torch.Tensor,
        proposal_valid: torch.Tensor,
        proposal_membership: torch.Tensor,
        proposal_decisions: torch.Tensor,
        proposal_cardinalities: torch.Tensor,
        candidate_sources: torch.Tensor,
    ) -> None:
        candidate_valid = base_batch.get("mask")
        if (
            candidate_valid is None
            or candidate_valid.dtype is not torch.bool
            or encoded.ndim != 3
            or encoded.shape[:2] != candidate_valid.shape
            or encoded.shape[-1] != self.base_hidden_dim
            or context.shape
            != (encoded.shape[0], self.base_hidden_dim)
        ):
            raise ValueError("ordinary joint plan base shape differs")
        expected_plan_shape = proposal_features.shape[:2]
        if (
            proposal_features.ndim != 3
            or proposal_features.shape[-1] != PLAN_PROPOSAL_FEATURE_DIM
            or proposal_valid.shape != expected_plan_shape
            or proposal_valid.dtype is not torch.bool
            or proposal_membership.shape
            != (*expected_plan_shape, encoded.shape[1])
            or proposal_membership.dtype is not torch.bool
            or proposal_decisions.shape != expected_plan_shape
            or proposal_cardinalities.shape != expected_plan_shape
            or candidate_sources.shape != candidate_valid.shape
        ):
            raise ValueError("ordinary joint plan proposal shape differs")
        if bool((proposal_membership & ~candidate_valid.unsqueeze(1)).any()):
            raise ValueError(
                "ordinary joint plan references a padded candidate"
            )
        if bool(
            (
                proposal_membership.sum(dim=-1)
                != proposal_cardinalities
            )[proposal_valid].any()
        ):
            raise ValueError(
                "ordinary joint plan cardinality differs from membership"
            )
        if bool(
            (
                (proposal_decisions < 0)
                | (proposal_decisions > ABSTAIN_DECISION_INDEX)
            )[proposal_valid].any()
        ):
            raise ValueError("ordinary joint plan decision differs")


def _masked_candidate_mean(
    encoded: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    weights = mask.to(encoded.dtype)
    return torch.einsum("bpc,bch->bph", weights, encoded) / weights.sum(
        dim=-1,
        keepdim=True,
    ).clamp_min(1.0)


def _dynamic_plan_features(
    *,
    base_outputs: Mapping[str, torch.Tensor],
    selected: torch.Tensor,
    excluded: torch.Tensor,
    proposal_decisions: torch.Tensor,
    proposal_cardinalities: torch.Tensor,
    non_abstain: torch.Tensor,
) -> torch.Tensor:
    member_logits = base_outputs["member_logits"]
    decision_log_probabilities = torch.log_softmax(
        base_outputs["decision_logits"],
        dim=-1,
    )
    cardinality_log_probabilities = torch.log_softmax(
        base_outputs["cardinality_logits"],
        dim=-1,
    )
    decision_indices = proposal_decisions.clamp(min=0, max=1)
    decision_evidence = torch.gather(
        decision_log_probabilities,
        1,
        decision_indices,
    ) * non_abstain.to(member_logits.dtype)
    cardinality_indices = proposal_cardinalities.clamp(
        max=cardinality_log_probabilities.shape[-1] - 1,
    )
    cardinality_evidence = torch.gather(
        cardinality_log_probabilities,
        1,
        cardinality_indices,
    ) * non_abstain.to(member_logits.dtype)
    selected_log = nn.functional.logsigmoid(member_logits).unsqueeze(1)
    excluded_log = nn.functional.logsigmoid(-member_logits).unsqueeze(1)
    selected_mean = _masked_scalar_mean(selected_log, selected)
    excluded_mean = _masked_scalar_mean(excluded_log, excluded)
    probabilities = torch.sigmoid(member_logits).unsqueeze(1)
    selected_min = _masked_scalar_extreme(
        probabilities,
        selected,
        maximum=False,
    )
    selected_max = _masked_scalar_extreme(
        probabilities,
        selected,
        maximum=True,
    )
    excluded_max = _masked_scalar_extreme(
        probabilities,
        excluded,
        maximum=True,
    )
    margin = selected_min - excluded_max
    cardinality_normalized = torch.tanh(
        proposal_cardinalities.to(member_logits.dtype) / 8.0
    )
    values = torch.stack(
        (
            decision_evidence,
            cardinality_evidence,
            selected_mean,
            excluded_mean,
            selected_min,
            selected_max,
            excluded_max,
            margin + cardinality_normalized,
        ),
        dim=-1,
    )
    if values.shape[-1] != JOINT_PLAN_DYNAMIC_FEATURE_DIM:
        raise AssertionError("ordinary joint plan dynamic dimension differs")
    return values


def _masked_scalar_mean(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    weights = mask.to(values.dtype)
    return (values * weights).sum(dim=-1) / weights.sum(
        dim=-1
    ).clamp_min(1.0)


def _masked_scalar_extreme(
    values: torch.Tensor,
    mask: torch.Tensor,
    *,
    maximum: bool,
) -> torch.Tensor:
    fill = (
        torch.finfo(values.dtype).min
        if maximum
        else torch.finfo(values.dtype).max
    )
    result = values.masked_fill(~mask, fill)
    result = result.max(dim=-1).values if maximum else result.min(
        dim=-1
    ).values
    return torch.where(
        mask.any(dim=-1),
        result,
        torch.zeros_like(result),
    )


__all__ = [
    "ABSTAIN_DECISION_INDEX",
    "JOINT_PLAN_DYNAMIC_FEATURE_DIM",
    "TargetAOrdinaryJointPlanNetwork",
]
