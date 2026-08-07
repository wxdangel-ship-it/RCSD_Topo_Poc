from __future__ import annotations

from dataclasses import replace

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_structural_decision import (
    TargetAAnchorStructuralJointHead,
    TargetAAnchorStructuralJointOutput,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_ANCHOR_CONDITION_DIM,
    TargetABatchTensors,
    TargetAJointNetwork,
)


_ANCHOR_DECISION_SUMMARY_DIM = 6


def build_ordinary_anchor_condition_features(
    batch: TargetABatchTensors,
    structural: TargetAAnchorStructuralJointOutput,
) -> torch.Tensor:
    """Aggregate immutable raw-evidence anchor decisions for each Segment."""
    object_indices = batch.anchor_object_indices
    if object_indices.ndim != 2:
        raise ValueError("anchor object indices must be [B, A]")
    valid_anchor = object_indices.ge(0)
    if bool(
        (
            valid_anchor
            & object_indices.ge(batch.object_features.shape[1])
        ).any()
    ):
        raise ValueError("anchor object index is outside the object batch")
    safe_object_indices = object_indices.clamp_min(0)
    batch_indices = torch.arange(
        batch.object_features.shape[0],
        device=batch.object_features.device,
    ).unsqueeze(-1)
    raw_anchor = batch.object_features[
        batch_indices,
        safe_object_indices,
    ]
    relation_probabilities = torch.softmax(
        structural.relation_logits,
        dim=-1,
    )
    type_probabilities = torch.softmax(
        structural.object_type_logits,
        dim=-1,
    )
    cardinality_probabilities = torch.softmax(
        structural.cardinality_logits,
        dim=-1,
    )
    cardinalities = torch.arange(
        1,
        structural.cardinality_logits.shape[-1] + 1,
        dtype=cardinality_probabilities.dtype,
        device=cardinality_probabilities.device,
    )
    expected_cardinality = (
        cardinality_probabilities * cardinalities
    ).sum(dim=-1) / cardinalities[-1]
    summary = torch.cat(
        (
            relation_probabilities,
            type_probabilities[..., 1:2],
            expected_cardinality.unsqueeze(-1),
            relation_probabilities.amax(dim=-1, keepdim=True),
        ),
        dim=-1,
    )
    if summary.shape[-1] != _ANCHOR_DECISION_SUMMARY_DIM:
        raise ValueError("anchor decision summary dimension differs")
    anchor_condition = torch.cat((raw_anchor, summary), dim=-1)
    anchor_condition = anchor_condition * valid_anchor.unsqueeze(-1).to(
        anchor_condition.dtype
    )
    if anchor_condition.shape[-1] != ORDINARY_ANCHOR_CONDITION_DIM:
        raise ValueError("ordinary anchor condition dimension differs")

    required = batch.ordinary_required_anchor_indices
    if required.ndim != 3:
        raise ValueError("required anchor indices must be [B, S, R]")
    required_mask = required.ge(0)
    if bool(
        (
            required_mask
            & required.ge(anchor_condition.shape[1])
        ).any()
    ):
        raise ValueError("required anchor index is outside the anchor batch")
    safe_required = required.clamp_min(0)
    row_indices = torch.arange(
        anchor_condition.shape[0],
        device=anchor_condition.device,
    ).view(-1, 1, 1)
    gathered = anchor_condition[row_indices, safe_required]
    weights = required_mask.unsqueeze(-1).to(gathered.dtype)
    return (
        (gathered * weights).sum(dim=2)
        / weights.sum(dim=2).clamp_min(1.0)
    )


class TargetAFrozenAnchorConditionedNetwork(nn.Module):
    """Condition ordinary decoding without carrier gradients entering anchor."""

    def __init__(
        self,
        base: TargetAJointNetwork,
        structural_head: TargetAAnchorStructuralJointHead,
    ) -> None:
        super().__init__()
        self.base = base
        self.structural_head = structural_head
        for parameter in self.structural_head.parameters():
            parameter.requires_grad_(False)

    def forward(
        self,
        batch: TargetABatchTensors,
    ) -> dict[str, torch.Tensor]:
        self.structural_head.eval()
        with torch.no_grad():
            structural = self.structural_head(
                batch,
                batch.object_features,
            )
            condition = build_ordinary_anchor_condition_features(
                batch,
                structural,
            )
        conditioned = replace(
            batch,
            ordinary_anchor_condition_features=condition,
        )
        result = dict(self.base(conditioned))
        result.update(
            {
                "structural_relation_logits": structural.relation_logits,
                "structural_object_type_logits": (
                    structural.object_type_logits
                ),
                "structural_cardinality_logits": (
                    structural.cardinality_logits
                ),
                "structural_ordinal_cardinality_logits": (
                    structural.ordinal_cardinality_logits
                ),
                "structural_member_logits": structural.member_logits,
                "structural_decision_context": (
                    structural.decision_context
                ),
            }
        )
        return result


__all__ = [
    "TargetAFrozenAnchorConditionedNetwork",
    "build_ordinary_anchor_condition_features",
]
