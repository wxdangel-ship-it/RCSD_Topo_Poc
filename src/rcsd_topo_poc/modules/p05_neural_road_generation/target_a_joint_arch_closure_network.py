from __future__ import annotations

from typing import Mapping

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_arch_closure_data import (
    ArchClosureModelInput,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_arch_closure_network import (
    TargetAArchClosureNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetABatchTensors,
    TargetAJointNetwork,
)


class TargetAJointArchClosureNetwork(nn.Module):
    """Anchor-first live Junction encoder plus complete ordinary Plan decoder."""

    def __init__(
        self,
        anchor: TargetAJointNetwork,
        ordinary: TargetAArchClosureNetwork,
    ) -> None:
        super().__init__()
        if ordinary.config.detach_junction_embeddings:
            raise ValueError(
                "joint architecture requires live Junction gradients"
            )
        if (
            anchor.config.hidden_dim
            != ordinary.config.junction_embedding_dim
        ):
            raise ValueError("joint anchor/ordinary embedding dimensions differ")
        self.anchor = anchor
        self.ordinary = ordinary

    def forward_anchor(
        self,
        tensors: TargetABatchTensors,
    ) -> dict[str, torch.Tensor]:
        return self.anchor(tensors)

    def forward_ordinary(
        self,
        inputs: ArchClosureModelInput,
        *,
        teacher_gate_decisions: torch.Tensor | None = None,
    ) -> Mapping[str, torch.Tensor]:
        return self.ordinary(
            inputs,
            teacher_gate_decisions=teacher_gate_decisions,
        )


def joint_arch_closure_parameter_count(
    model: TargetAJointArchClosureNetwork,
) -> int:
    return sum(parameter.numel() for parameter in model.parameters())


__all__ = [
    "TargetAJointArchClosureNetwork",
    "joint_arch_closure_parameter_count",
]
