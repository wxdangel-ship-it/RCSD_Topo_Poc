from __future__ import annotations

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetABatchTensors,
    TargetAJointNetwork,
)


class TargetACaseJointNetwork(TargetAJointNetwork):
    """Add an explicit anchor-to-complete-plan compatibility path."""

    def __init__(
        self,
        config: TargetAConfig,
        *,
        apply_compatibility_to_plan_logits: bool = True,
    ) -> None:
        super().__init__(config)
        self.apply_compatibility_to_plan_logits = (
            apply_compatibility_to_plan_logits
        )
        self.case_joint_anchor_projection = nn.Linear(
            config.hidden_dim,
            config.hidden_dim,
            bias=False,
        )
        self.case_joint_plan_projection = nn.Linear(
            config.hidden_dim,
            config.hidden_dim,
            bias=False,
        )
        self.case_joint_compatibility_scale = nn.Parameter(
            torch.tensor(-0.43275213)
        )

    def forward(self, batch: TargetABatchTensors) -> dict[str, torch.Tensor]:
        outputs = super().forward(batch)
        anchor_context = _indexed_mean(
            outputs["locked_anchor_embeddings"],
            batch.ordinary_required_anchor_indices,
        )
        plan_embeddings = self.candidate_set_encoder(
            batch.ordinary_plan_features,
            batch.ordinary_plan_mask,
        )
        anchor_values = nn.functional.normalize(
            self.case_joint_anchor_projection(anchor_context),
            dim=-1,
        )
        plan_values = nn.functional.normalize(
            self.case_joint_plan_projection(plan_embeddings),
            dim=-1,
        )
        compatibility = torch.einsum(
            "boh,boph->bop",
            anchor_values,
            plan_values,
        )
        compatibility = compatibility.masked_fill(
            ~batch.ordinary_plan_mask,
            float("-inf"),
        )
        scale = nn.functional.softplus(
            self.case_joint_compatibility_scale
        )
        ordinary_logits = outputs["ordinary_plan_logits"]
        safe_compatibility = torch.where(
            batch.ordinary_plan_mask,
            compatibility,
            torch.zeros_like(compatibility),
        )
        if self.apply_compatibility_to_plan_logits:
            outputs["ordinary_plan_logits"] = (
                ordinary_logits + scale * safe_compatibility
            )
        outputs["anchor_plan_compatibility_logits"] = compatibility
        outputs["anchor_plan_compatibility_scale"] = scale.reshape(1)
        return outputs


def _indexed_mean(
    values: torch.Tensor,
    indices: torch.Tensor,
) -> torch.Tensor:
    if values.ndim != 3 or indices.ndim != 3:
        raise ValueError("Case joint indexed mean shape differs")
    safe = indices.clamp_min(0)
    batch_indices = torch.arange(values.shape[0], device=values.device)[
        :, None, None
    ]
    gathered = values[batch_indices, safe]
    mask = indices.ge(0).unsqueeze(-1)
    total = (gathered * mask.to(gathered.dtype)).sum(dim=2)
    denominator = mask.sum(dim=2).clamp_min(1).to(gathered.dtype)
    return total / denominator


__all__ = ["TargetACaseJointNetwork"]
