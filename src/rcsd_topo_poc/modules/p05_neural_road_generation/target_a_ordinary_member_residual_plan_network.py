from __future__ import annotations

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_encoded_set_reranker import (
    TargetAEndToEndListwiseSetTransformer,
    TargetAEndToEndListwiseSetTransformerConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_member_aware_plan_network import (
    OrdinaryMemberAwarePlanConfig,
    OrdinaryMemberAwarePlanNetwork,
)


class OrdinaryMemberResidualPlanNetwork(nn.Module):
    """Add a zero-initialized member-graph residual to a frozen proposal scorer."""

    def __init__(
        self,
        *,
        base_config: TargetAEndToEndListwiseSetTransformerConfig,
        member_config: OrdinaryMemberAwarePlanConfig,
        freeze_base: bool = True,
    ) -> None:
        super().__init__()
        self.base = TargetAEndToEndListwiseSetTransformer(base_config)
        self.member = OrdinaryMemberAwarePlanNetwork(member_config)
        self.freeze_base = freeze_base
        _zero_last_linear(self.member.selection_head)
        _zero_last_linear(self.member.validity_head)
        if freeze_base:
            for parameter in self.base.parameters():
                parameter.requires_grad_(False)
            self.base.eval()

    def train(self, mode: bool = True) -> OrdinaryMemberResidualPlanNetwork:
        super().train(mode)
        if self.freeze_base:
            self.base.eval()
        return self

    def forward(
        self,
        *,
        base_features: torch.Tensor,
        candidate_signals: torch.Tensor,
        road_relations: torch.Tensor,
        candidate_sources: torch.Tensor,
        candidate_mask: torch.Tensor,
        proposal_scalars: torch.Tensor,
        proposal_sources: torch.Tensor,
        proposal_selected: torch.Tensor,
        proposal_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        if (
            base_features.ndim != 3
            or base_features.shape[:2] != proposal_mask.shape
            or base_features.shape[-1] != self.base.config.feature_dim
        ):
            raise ValueError("member residual base feature shape differs")
        if self.freeze_base:
            with torch.no_grad():
                base_outputs = self.base(base_features, proposal_mask)
        else:
            base_outputs = self.base(base_features, proposal_mask)
        member_outputs = self.member(
            candidate_signals=candidate_signals,
            road_relations=road_relations,
            candidate_sources=candidate_sources,
            candidate_mask=candidate_mask,
            proposal_scalars=proposal_scalars,
            proposal_sources=proposal_sources,
            proposal_selected=proposal_selected,
            proposal_mask=proposal_mask,
        )
        plan_residual = member_outputs["plan_logits"].masked_fill(
            ~proposal_mask, 0.0
        )
        validity_residual = member_outputs["plan_validity_logits"]
        plan_logits = base_outputs["plan_logits"] + plan_residual
        validity_logits = (
            base_outputs["plan_validity_logits"] + validity_residual
        )
        return {
            "plan_logits": plan_logits.masked_fill(
                ~proposal_mask, float("-inf")
            ),
            "plan_validity_logits": validity_logits.masked_fill(
                ~proposal_mask, 0.0
            ),
            "base_plan_logits": base_outputs["plan_logits"],
            "base_validity_logits": base_outputs["plan_validity_logits"],
            "plan_residual_logits": plan_residual,
            "validity_residual_logits": validity_residual,
            "road_embeddings": member_outputs["road_embeddings"],
            "proposal_embeddings": member_outputs["proposal_embeddings"],
            "selected_attention": member_outputs["selected_attention"],
        }


def _zero_last_linear(module: nn.Sequential) -> None:
    last = next(
        (value for value in reversed(module) if isinstance(value, nn.Linear)),
        None,
    )
    if last is None:
        raise ValueError("member residual head lacks Linear output")
    nn.init.zeros_(last.weight)
    if last.bias is not None:
        nn.init.zeros_(last.bias)


__all__ = ["OrdinaryMemberResidualPlanNetwork"]
