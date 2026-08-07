from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_consistency import (
    OrdinaryAccessConsistencyConfig,
    TargetAOrdinaryAccessConsistencyHead,
    access_equivalent_candidate_mask,
    multi_acceptable_access_loss,
    ordinary_access_geometry_prior,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_arms import (
    ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
    ORDINARY_PLAN_ARM_COUNT,
)


def test_access_equivalence_uses_plan_endpoints_only_as_access_targets() -> None:
    mask = access_equivalent_candidate_mask(
        candidate_arm_road_ids=(
            ("r1", "r2"),
            ("r1", "r2"),
            ("r1", "r3"),
            (),
        ),
        candidate_arm_node_ids=(
            ("n1", "n2"),
            ("n1", "n2"),
            ("n1", "n3"),
            (),
        ),
        acceptable_indices=(1,),
    )

    assert mask == (True, True, False, False)


def test_access_head_blocks_gradients_into_arm_and_upstream_evidence() -> None:
    model = TargetAOrdinaryAccessConsistencyHead(
        OrdinaryAccessConsistencyConfig(
            hidden_dim=16,
            feedforward_dim=24,
            upstream_context_dim=5,
            dropout=0.0,
        )
    )
    arms = torch.randn(
        2,
        3,
        ORDINARY_PLAN_ARM_COUNT,
        ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
        requires_grad=True,
    )
    arm_mask = torch.ones(2, 3, ORDINARY_PLAN_ARM_COUNT, dtype=torch.bool)
    candidate_mask = torch.ones(2, 3, dtype=torch.bool)
    context = torch.randn(2, 3, 5, requires_grad=True)

    logits = model(
        arms,
        arm_mask,
        candidate_mask=candidate_mask,
        upstream_context=context,
    )
    loss = multi_acceptable_access_loss(
        logits,
        candidate_mask=candidate_mask,
        acceptable_access_mask=torch.tensor(
            [[True, False, False], [False, True, True]]
        ),
    )
    loss.backward()

    assert logits.shape == (2, 3)
    assert arms.grad is None
    assert context.grad is None
    assert any(parameter.grad is not None for parameter in model.parameters())


def test_access_loss_accepts_multiple_equivalent_candidates() -> None:
    logits = torch.tensor([[0.1, 2.0, -1.0]], requires_grad=True)
    candidate_mask = torch.tensor([[True, True, True]])
    targets = torch.tensor([[True, True, False]])

    loss = multi_acceptable_access_loss(
        logits,
        candidate_mask=candidate_mask,
        acceptable_access_mask=targets,
        sample_weight=torch.tensor([0.7]),
    )
    loss.backward()

    assert float(loss.detach()) < 0.1
    assert logits.grad is not None


def test_ordered_residual_keeps_geometry_prior_and_gradient_boundary() -> None:
    model = TargetAOrdinaryAccessConsistencyHead(
        OrdinaryAccessConsistencyConfig(
            hidden_dim=12,
            feedforward_dim=18,
            dropout=0.0,
            preserve_arm_order=True,
            geometry_prior_scale=4.0,
            residual_scale=0.0,
            bound_residual=True,
        )
    )
    arms = torch.zeros(
        1,
        2,
        ORDINARY_PLAN_ARM_COUNT,
        ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
        requires_grad=True,
    )
    arms.data[0, 0, :, 3] = 0.9
    arms.data[0, 0, :, 5] = 0.8
    arms.data[0, 0, :, 11] = 0.7
    arms.data[0, 1, :, 3] = 0.4
    arms.data[0, 1, :, 5] = 0.3
    mask = torch.ones(1, 2, ORDINARY_PLAN_ARM_COUNT, dtype=torch.bool)

    logits = model(arms, mask)
    expected = 4.0 * ordinary_access_geometry_prior(arms.detach())

    assert torch.allclose(logits, expected)
    assert int(logits.argmax(dim=-1)) == 0
    assert arms.grad is None


def test_masked_empty_candidate_does_not_produce_nan() -> None:
    model = TargetAOrdinaryAccessConsistencyHead(
        OrdinaryAccessConsistencyConfig(
            hidden_dim=12,
            feedforward_dim=18,
            dropout=0.0,
            preserve_arm_order=True,
            geometry_prior_scale=4.0,
            residual_scale=0.15,
            bound_residual=True,
        )
    )
    arms = torch.zeros(
        1,
        2,
        ORDINARY_PLAN_ARM_COUNT,
        ORDINARY_PLAN_ARM_BASE_FEATURE_DIM,
    )
    arm_mask = torch.tensor([[[True, True], [False, False]]])
    candidate_mask = torch.tensor([[True, False]])

    logits = model(
        arms,
        arm_mask,
        candidate_mask=candidate_mask,
    )
    loss = multi_acceptable_access_loss(
        logits,
        candidate_mask=candidate_mask,
        acceptable_access_mask=torch.tensor([[True, False]]),
    )

    assert bool(torch.isfinite(logits).all())
    assert bool(torch.isfinite(loss))
