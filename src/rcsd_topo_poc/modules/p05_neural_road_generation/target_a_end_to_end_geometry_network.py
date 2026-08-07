from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_geometry_data import (
    END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_recall_network import (
    TargetAEndToEndRecallNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetABatchTensors,
)


@dataclass(frozen=True)
class TargetAEndToEndGeometryConfig:
    hidden_dim: int
    proposal_hidden_dim: int = 128
    dropout: float = 0.10

    def validate(self) -> None:
        if min(self.hidden_dim, self.proposal_hidden_dim) < 1:
            raise ValueError("end-to-end geometry dimensions must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("end-to-end geometry dropout is invalid")


class TargetAEndToEndGeometryNetwork(nn.Module):
    """One forward for anchors, ordinary plans, AR Road sets and geometry."""

    def __init__(
        self,
        recall: TargetAEndToEndRecallNetwork,
        config: TargetAEndToEndGeometryConfig,
    ) -> None:
        super().__init__()
        config.validate()
        if recall.config.hidden_dim != config.hidden_dim:
            raise ValueError("geometry and recall dimensions differ")
        self.recall = recall
        self.config = config
        self.proposal_encoder = nn.Sequential(
            nn.Linear(
                END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM,
                config.proposal_hidden_dim * 2,
            ),
            nn.GELU(),
            nn.LayerNorm(config.proposal_hidden_dim * 2),
            nn.Dropout(config.dropout),
            nn.Linear(
                config.proposal_hidden_dim * 2,
                config.proposal_hidden_dim,
            ),
            nn.GELU(),
            nn.LayerNorm(config.proposal_hidden_dim),
        )
        context_dim = 3 * config.hidden_dim + 6
        self.proposal_head = nn.Sequential(
            nn.Linear(
                config.proposal_hidden_dim + context_dim,
                config.proposal_hidden_dim * 2,
            ),
            nn.GELU(),
            nn.LayerNorm(config.proposal_hidden_dim * 2),
            nn.Dropout(config.dropout),
            nn.Linear(config.proposal_hidden_dim * 2, 1),
        )

    def freeze_recall(self) -> None:
        self.recall.requires_grad_(False)

    def forward(
        self,
        batch: TargetABatchTensors,
        *,
        geometry_proposal_values: torch.Tensor,
        geometry_proposal_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        if (
            geometry_proposal_values.ndim != 3
            or geometry_proposal_values.shape[-1]
            != END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM
        ):
            raise ValueError("end-to-end geometry proposal shape differs")
        if (
            geometry_proposal_mask.shape
            != geometry_proposal_values.shape[:2]
            or geometry_proposal_mask.dtype != torch.bool
        ):
            raise ValueError("end-to-end geometry proposal mask differs")
        outputs = self.recall(batch)
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
            ),
            dim=-1,
        )
        if context.shape[1] != 1:
            raise ValueError("geometry forward expects one AdvanceRight group")
        encoded = self.proposal_encoder(geometry_proposal_values)
        expanded = context.expand(
            -1,
            geometry_proposal_values.shape[1],
            -1,
        )
        logits = self.proposal_head(
            torch.cat((encoded, expanded), dim=-1)
        ).squeeze(-1)
        logits = logits.masked_fill(
            ~geometry_proposal_mask,
            float("-inf"),
        )
        return {
            **outputs,
            "geometry_proposal_logits": logits,
            "geometry_proposal_embeddings": encoded,
        }


def _gather(values: torch.Tensor, indices: torch.Tensor) -> torch.Tensor:
    if values.shape[0] != indices.shape[0]:
        raise ValueError("geometry gather batch differs")
    safe = indices.clamp_min(0)
    gathered = torch.gather(
        values,
        1,
        safe.unsqueeze(-1).expand(*safe.shape, values.shape[-1]),
    )
    return gathered * indices.ge(0).unsqueeze(-1).to(gathered.dtype)


__all__ = [
    "TargetAEndToEndGeometryConfig",
    "TargetAEndToEndGeometryNetwork",
]
