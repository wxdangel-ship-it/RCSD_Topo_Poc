from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_geometry_data import (
    END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_road_set_network import (
    TargetAEndToEndRoadSetNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetABatchTensors,
)


_GEOMETRY_TYPE_COUNT = 3


@dataclass(frozen=True)
class TargetAEndToEndTypedGeometryConfig:
    hidden_dim: int
    proposal_hidden_dim: int = 128
    max_road_cardinality: int = 12
    dropout: float = 0.10

    def validate(self) -> None:
        if min(
            self.hidden_dim,
            self.proposal_hidden_dim,
            self.max_road_cardinality,
        ) < 1:
            raise ValueError("typed geometry dimensions must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("typed geometry dropout is invalid")


class TargetAEndToEndTypedGeometryNetwork(nn.Module):
    """Use one geometry expert per explicit T06 action type."""

    def __init__(
        self,
        road_set: TargetAEndToEndRoadSetNetwork,
        config: TargetAEndToEndTypedGeometryConfig,
    ) -> None:
        super().__init__()
        config.validate()
        if road_set.config.hidden_dim != config.hidden_dim:
            raise ValueError("typed geometry Road-set dimension differs")
        self.road_set = road_set
        self.config = config
        self.proposal_encoders = nn.ModuleList(
            [
                _proposal_encoder(
                    config.proposal_hidden_dim,
                    config.dropout,
                )
                for _ in range(_GEOMETRY_TYPE_COUNT)
            ]
        )
        context_dim = (
            3 * config.hidden_dim
            + 6
            + 2
            + config.max_road_cardinality
            + 1
        )
        self.proposal_heads = nn.ModuleList(
            [
                _proposal_head(
                    config.proposal_hidden_dim + context_dim,
                    config.proposal_hidden_dim,
                    config.dropout,
                )
                for _ in range(_GEOMETRY_TYPE_COUNT)
            ]
        )

    def freeze_road_set(self) -> None:
        self.road_set.requires_grad_(False)

    def forward(
        self,
        batch: TargetABatchTensors,
        *,
        road_member_values: torch.Tensor,
        road_member_mask: torch.Tensor,
        plan_membership: torch.Tensor,
        geometry_proposal_values: torch.Tensor,
        geometry_proposal_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        _validate_geometry_tensors(
            geometry_proposal_values,
            geometry_proposal_mask,
        )
        outputs = self.road_set(
            batch,
            road_member_values=road_member_values,
            road_member_mask=road_member_mask,
            plan_membership=plan_membership,
        )
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
                torch.softmax(
                    outputs["advance_right_road_source_logits"],
                    dim=-1,
                ),
                torch.softmax(
                    outputs["advance_right_road_cardinality_logits"],
                    dim=-1,
                ),
            ),
            dim=-1,
        )
        if context.shape[1] != 1:
            raise ValueError("typed geometry expects one AdvanceRight group")
        expanded_context = context.expand(
            -1,
            geometry_proposal_values.shape[1],
            -1,
        )
        expert_embeddings = []
        expert_logits = []
        for encoder, head in zip(
            self.proposal_encoders,
            self.proposal_heads,
            strict=True,
        ):
            encoded = encoder(geometry_proposal_values)
            logits = head(
                torch.cat((encoded, expanded_context), dim=-1)
            ).squeeze(-1)
            expert_embeddings.append(encoded)
            expert_logits.append(logits)
        stacked_logits = torch.stack(expert_logits, dim=-1)
        type_values = geometry_proposal_values[..., :_GEOMETRY_TYPE_COUNT]
        type_indices = type_values.argmax(dim=-1)
        logits = torch.gather(
            stacked_logits,
            -1,
            type_indices.unsqueeze(-1),
        ).squeeze(-1)
        logits = logits.masked_fill(
            ~geometry_proposal_mask,
            float("-inf"),
        )
        return {
            **outputs,
            "geometry_proposal_logits": logits,
            "geometry_type_expert_logits": stacked_logits,
            "geometry_type_expert_embeddings": torch.stack(
                expert_embeddings,
                dim=-2,
            ),
        }


def _proposal_encoder(
    hidden_dim: int,
    dropout: float,
) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(
            END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM,
            hidden_dim * 2,
        ),
        nn.GELU(),
        nn.LayerNorm(hidden_dim * 2),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim * 2, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
    )


def _proposal_head(
    input_dim: int,
    hidden_dim: int,
    dropout: float,
) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim * 2),
        nn.GELU(),
        nn.LayerNorm(hidden_dim * 2),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim * 2, 1),
    )


def _validate_geometry_tensors(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> None:
    if (
        values.ndim != 3
        or values.shape[-1] != END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM
    ):
        raise ValueError("typed geometry proposal shape differs")
    if mask.shape != values.shape[:2] or mask.dtype != torch.bool:
        raise ValueError("typed geometry proposal mask differs")
    active_types = values[..., :_GEOMETRY_TYPE_COUNT].sum(dim=-1)
    if bool(
        (
            mask
            & ~torch.isclose(
                active_types,
                torch.ones_like(active_types),
            )
        ).any()
    ):
        raise ValueError("typed geometry proposal has no unique type")


def _gather(values: torch.Tensor, indices: torch.Tensor) -> torch.Tensor:
    if values.shape[0] != indices.shape[0]:
        raise ValueError("typed geometry gather batch differs")
    safe = indices.clamp_min(0)
    gathered = torch.gather(
        values,
        1,
        safe.unsqueeze(-1).expand(*safe.shape, values.shape[-1]),
    )
    return gathered * indices.ge(0).unsqueeze(-1).to(gathered.dtype)


__all__ = [
    "TargetAEndToEndTypedGeometryConfig",
    "TargetAEndToEndTypedGeometryNetwork",
]
