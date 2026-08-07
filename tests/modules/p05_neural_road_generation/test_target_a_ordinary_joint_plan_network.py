from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_plan_network import (
    TargetAOrdinaryJointPlanNetwork,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_proposals import (
    PLAN_PROPOSAL_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_member_network import (
    TargetAOrdinaryJointRoadGraphDecoder,
)


def test_joint_plan_loss_reaches_shared_candidate_encoder() -> None:
    base = TargetAOrdinaryJointRoadGraphDecoder(
        object_feature_dim=3,
        candidate_feature_dim=4,
        hidden_dim=16,
        context_dim=24,
        graph_layers=1,
        num_heads=4,
        cardinality_count=5,
        dropout=0.0,
    )
    model = TargetAOrdinaryJointPlanNetwork(
        base_model=base,
        base_hidden_dim=16,
        plan_hidden_dim=16,
        plan_feedforward_dim=24,
        dropout=0.0,
    )
    candidate_mask = torch.tensor(
        [[True, True, True], [True, True, False]]
    )
    base_batch = {
        "objects": torch.randn(2, 3),
        "candidates": torch.randn(2, 3, 4),
        "mask": candidate_mask,
        "adjacency": torch.ones(2, 3, 3, dtype=torch.bool),
        "endpoint_adjacency": torch.ones(
            2,
            3,
            3,
            dtype=torch.bool,
        ),
        "road_relations": torch.zeros(2, 3, 3, 0),
    }
    proposal_membership = torch.tensor(
        [
            [[False, False, False], [True, False, False], [True, True, False]],
            [[False, False, False], [True, False, False], [False, True, False]],
        ]
    )
    proposal_valid = torch.ones(2, 3, dtype=torch.bool)
    outputs = model(
        base_batch=base_batch,
        proposal_features=torch.randn(
            2,
            3,
            PLAN_PROPOSAL_FEATURE_DIM,
        ),
        proposal_valid=proposal_valid,
        proposal_membership=proposal_membership,
        proposal_decisions=torch.tensor(
            [[2, 1, 1], [2, 0, 0]]
        ),
        proposal_cardinalities=proposal_membership.sum(dim=-1),
        candidate_sources=torch.tensor(
            [[1, 1, 0], [0, 0, 0]]
        ),
    )

    assert outputs["plan_logits"].shape == (2, 3)
    assert outputs["plan_validity_logits"].shape == (2, 3)
    assert outputs["plan_dynamic_features"].shape == (2, 3, 8)
    (
        outputs["plan_logits"].sum()
        + outputs["plan_validity_logits"].sum()
    ).backward()
    gradient = base.candidate_encoder[0].weight.grad
    assert gradient is not None
    assert torch.isfinite(gradient).all()
    assert float(gradient.abs().sum()) > 0.0


def test_joint_plan_rejects_padded_candidate_membership() -> None:
    base = TargetAOrdinaryJointRoadGraphDecoder(
        object_feature_dim=2,
        candidate_feature_dim=2,
        hidden_dim=8,
        context_dim=12,
        graph_layers=1,
        num_heads=2,
        cardinality_count=3,
        dropout=0.0,
    )
    model = TargetAOrdinaryJointPlanNetwork(
        base_model=base,
        base_hidden_dim=8,
        plan_hidden_dim=8,
        plan_feedforward_dim=12,
        dropout=0.0,
    )
    try:
        model(
            base_batch={
                "objects": torch.zeros(1, 2),
                "candidates": torch.zeros(1, 2, 2),
                "mask": torch.tensor([[True, False]]),
                "adjacency": torch.ones(1, 2, 2, dtype=torch.bool),
                "endpoint_adjacency": torch.ones(
                    1,
                    2,
                    2,
                    dtype=torch.bool,
                ),
                "road_relations": torch.zeros(1, 2, 2, 0),
            },
            proposal_features=torch.zeros(
                1,
                1,
                PLAN_PROPOSAL_FEATURE_DIM,
            ),
            proposal_valid=torch.tensor([[True]]),
            proposal_membership=torch.tensor([[[False, True]]]),
            proposal_decisions=torch.tensor([[1]]),
            proposal_cardinalities=torch.tensor([[1]]),
            candidate_sources=torch.tensor([[1, 1]]),
        )
    except ValueError as exc:
        assert "padded candidate" in str(exc)
    else:
        raise AssertionError("padded proposal membership was accepted")
