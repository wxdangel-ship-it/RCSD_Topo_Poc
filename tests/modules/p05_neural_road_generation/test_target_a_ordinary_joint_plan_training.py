from __future__ import annotations

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_plan_training import (
    OrdinaryJointPlanTrainingConfig,
    _joint_loss_rows,
    balanced_plan_validity_bce,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_training import (
    OrdinaryRoadSetTrainingConfig,
)


def test_joint_plan_training_requires_enabled_loss() -> None:
    config = OrdinaryJointPlanTrainingConfig(
        plan_loss_weight=0.0,
        validity_loss_weight=0.0,
        base_loss_weight=0.0,
    )
    with pytest.raises(ValueError, match="losses are disabled"):
        config.validate()


def test_joint_plan_loss_combines_plan_and_base_targets() -> None:
    outputs = {
        "plan_logits": torch.tensor(
            [[0.0, 1.0]],
            requires_grad=True,
        ),
        "plan_validity_logits": torch.tensor(
            [[0.0, 1.0]],
            requires_grad=True,
        ),
        "base_outputs": {
            "decision_logits": torch.tensor(
                [[0.0, 1.0]],
                requires_grad=True,
            ),
            "cardinality_logits": torch.tensor(
                [[0.0, 1.0, -1.0]],
                requires_grad=True,
            ),
            "member_logits": torch.tensor(
                [[-1.0, 1.0]],
                requires_grad=True,
            ),
        },
    }
    batch = {
        "proposal_acceptable": torch.tensor([[False, True]]),
        "proposal_valid": torch.tensor([[True, True]]),
        "proposal_decisions": torch.tensor([[2, 1]]),
        "base_batch": {
            "decisions": torch.tensor([1]),
            "cardinalities": torch.tensor([1]),
            "targets": torch.tensor([[False, True]]),
            "mask": torch.tensor([[True, True]]),
            "member_weight_ratios": torch.ones(1, 2),
        },
    }
    loss = _joint_loss_rows(
        outputs,
        batch,
        base_config=OrdinaryRoadSetTrainingConfig(
            cardinality_count=3,
            decision_loss_weight=1.0,
            cardinality_loss_weight=1.0,
            member_loss_weight=1.0,
        ),
        config=OrdinaryJointPlanTrainingConfig(
            plan_loss_weight=1.0,
            base_loss_weight=1.0,
        ),
    )

    assert loss.shape == (1,)
    assert float(loss.item()) > 0.0
    loss.sum().backward()
    assert outputs["plan_logits"].grad is not None
    assert outputs["plan_validity_logits"].grad is not None
    assert outputs["base_outputs"]["member_logits"].grad is not None


def test_plan_validity_bce_balances_one_positive_many_negatives() -> None:
    logits = torch.zeros(1, 4)
    targets = torch.tensor([[True, False, False, False]])
    valid = torch.tensor([[True, True, True, True]])

    loss = balanced_plan_validity_bce(logits, targets, valid)

    assert loss.shape == (1,)
    assert float(loss.item()) == pytest.approx(0.693147, rel=1e-5)
