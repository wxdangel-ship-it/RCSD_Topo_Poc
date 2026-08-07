from __future__ import annotations

from dataclasses import dataclass

import pytest
import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_structural_conditioning import (
    TargetAFrozenAnchorConditionedNetwork,
    build_ordinary_anchor_condition_features,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_structural_decision import (
    TargetAAnchorStructuralJointOutput,
)


@dataclass(frozen=True)
class _Batch:
    object_features: torch.Tensor
    anchor_object_indices: torch.Tensor
    ordinary_required_anchor_indices: torch.Tensor
    ordinary_anchor_condition_features: torch.Tensor | None = None


def _structural() -> TargetAAnchorStructuralJointOutput:
    return TargetAAnchorStructuralJointOutput(
        relation_logits=torch.tensor(
            [[[0.0, 3.0, -2.0], [0.0, 0.0, 0.0]]]
        ),
        object_type_logits=torch.tensor(
            [[[0.0, 2.0], [0.0, 0.0]]]
        ),
        cardinality_logits=torch.tensor(
            [[[0.0, 0.0, 2.0, 0.0], [0.0, 0.0, 0.0, 0.0]]]
        ),
        ordinal_cardinality_logits=torch.zeros(1, 2, 3),
        member_logits=torch.zeros(1, 2, 1),
        decision_context=torch.zeros(1, 2, 8),
    )


def _batch() -> _Batch:
    objects = torch.arange(3 * 64, dtype=torch.float32).reshape(
        1,
        3,
        64,
    )
    return _Batch(
        object_features=objects,
        anchor_object_indices=torch.tensor([[1, -1]]),
        ordinary_required_anchor_indices=torch.tensor(
            [[[0, -1], [-1, -1]]]
        ),
    )


def test_condition_uses_raw_anchor_and_ignores_padding() -> None:
    batch = _batch()

    condition = build_ordinary_anchor_condition_features(
        batch,  # type: ignore[arg-type]
        _structural(),
    )

    assert condition.shape == (1, 2, 70)
    assert torch.equal(
        condition[0, 0, :64],
        batch.object_features[0, 1],
    )
    assert torch.count_nonzero(condition[0, 1]) == 0


def test_condition_rejects_invalid_required_anchor_index() -> None:
    batch = _batch()
    invalid = _Batch(
        object_features=batch.object_features,
        anchor_object_indices=batch.anchor_object_indices,
        ordinary_required_anchor_indices=torch.tensor([[[2]]]),
    )

    with pytest.raises(
        ValueError,
        match="required anchor index",
    ):
        build_ordinary_anchor_condition_features(
            invalid,  # type: ignore[arg-type]
            _structural(),
        )


class _StructuralHead(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.scale = nn.Parameter(torch.tensor(1.0))

    def forward(
        self,
        batch: _Batch,
        object_features: torch.Tensor,
    ) -> TargetAAnchorStructuralJointOutput:
        del batch, object_features
        output = _structural()
        return TargetAAnchorStructuralJointOutput(
            relation_logits=output.relation_logits * self.scale,
            object_type_logits=output.object_type_logits * self.scale,
            cardinality_logits=output.cardinality_logits * self.scale,
            ordinal_cardinality_logits=(
                output.ordinal_cardinality_logits * self.scale
            ),
            member_logits=output.member_logits * self.scale,
            decision_context=output.decision_context * self.scale,
        )


class _Base(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.scale = nn.Parameter(torch.tensor(1.0))

    def forward(self, batch: _Batch) -> dict[str, torch.Tensor]:
        condition = batch.ordinary_anchor_condition_features
        if condition is None:
            raise AssertionError("ordinary condition was not injected")
        return {"score": condition.sum() * self.scale}


def test_wrapper_freezes_anchor_branch_and_keeps_base_gradient() -> None:
    structural = _StructuralHead()
    base = _Base()
    model = TargetAFrozenAnchorConditionedNetwork(
        base,  # type: ignore[arg-type]
        structural,  # type: ignore[arg-type]
    )

    output = model(_batch())  # type: ignore[arg-type]
    output["score"].backward()

    assert structural.scale.requires_grad is False
    assert structural.scale.grad is None
    assert base.scale.grad is not None
    assert "structural_relation_logits" in output
