from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_same_plan_affinity import (
    SamePlanAffinityHead,
    plan_affinity_terms,
)


def test_same_plan_affinity_is_pair_order_symmetric() -> None:
    model = SamePlanAffinityHead(hidden_dim=32, dropout=0.0)
    embeddings = torch.randn(2, 4, 128)
    signals = torch.rand(2, 4, 3)
    relations = torch.rand(2, 4, 4, 13)
    relations = (relations + relations.transpose(1, 2)) / 2.0
    mask = torch.ones(2, 4, dtype=torch.bool)
    logits = model(embeddings, signals, relations, mask)
    assert torch.allclose(logits, logits.transpose(1, 2), atol=1e-6)


def test_relational_same_plan_affinity_is_pair_order_symmetric() -> None:
    model = SamePlanAffinityHead(
        hidden_dim=32,
        dropout=0.0,
        feature_mode="RELATIONAL",
    )
    embeddings = torch.randn(2, 4, 128)
    signals = torch.rand(2, 4, 3)
    relations = torch.rand(2, 4, 4, 13)
    relations = (relations + relations.transpose(1, 2)) / 2.0
    mask = torch.ones(2, 4, dtype=torch.bool)
    logits = model(embeddings, signals, relations, mask)
    assert torch.allclose(logits, logits.transpose(1, 2), atol=1e-6)


def test_plan_affinity_terms_reward_inside_and_boundary_consistency() -> None:
    probabilities = torch.tensor(
        [
            [0.0, 0.9, 0.2],
            [0.9, 0.0, 0.1],
            [0.2, 0.1, 0.0],
        ]
    )
    inside, boundary = plan_affinity_terms(
        probabilities,
        selected_indices=(0, 1),
        source_indices=(0, 1, 2),
    )
    assert inside > -0.2
    assert boundary > -0.2


def test_plan_affinity_terms_can_be_gated_by_proposal_cardinality() -> None:
    probabilities = torch.full((4, 4), 0.9)
    inside, boundary = plan_affinity_terms(
        probabilities,
        selected_indices=(0, 1),
        source_indices=(0, 1, 2, 3),
        minimum_selected_cardinality=3,
    )
    assert inside == 0.0
    assert boundary == 0.0
