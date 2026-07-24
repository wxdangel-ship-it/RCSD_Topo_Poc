from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_network import (
    SchemeACarrierGraphSetScorer,
    group_probabilities,
    parameter_count,
    scheme_a_p1_loss,
)


def test_scheme_a_p1_parameter_range_and_loss() -> None:
    model = SchemeACarrierGraphSetScorer(
        candidate_vocabulary_size=64,
        object_vocabulary_size=64,
        context_vocabulary_size=64,
        object_type_count=3,
    )
    assert 1_000_000 <= parameter_count(model) <= 5_000_000
    scores = torch.tensor([1.0, 0.0, -1.0, 2.0, 1.0])
    groups = torch.tensor([0, 0, 0, 1, 1])
    truth = torch.tensor([True, False, False, False, True])
    weights = torch.tensor([1.0, 0.3])
    anomaly_logits = torch.tensor([-2.0, 2.0])
    anomaly_targets = torch.tensor([False, True])
    total, parts = scheme_a_p1_loss(
        scores,
        anomaly_logits,
        groups,
        truth,
        weights,
        anomaly_targets,
        anomaly_loss_weight=0.5,
        anomaly_positive_weight=1.0,
    )
    assert torch.isfinite(total)
    assert float(parts["listwise_loss"]) > 0.0
    probabilities = group_probabilities(scores, groups, 2)
    assert torch.allclose(probabilities[:3].sum(), torch.tensor(1.0))
    assert torch.allclose(probabilities[3:].sum(), torch.tensor(1.0))


def test_scheme_a_p1_forward_shapes() -> None:
    model = SchemeACarrierGraphSetScorer(
        candidate_vocabulary_size=8,
        object_vocabulary_size=8,
        context_vocabulary_size=8,
        object_type_count=3,
    )
    scores, anomaly = model(
        candidate_token_ids=torch.tensor([1, 2, 3, 4]),
        candidate_offsets=torch.tensor([0, 2, 3]),
        object_token_ids=torch.tensor([1, 2, 3]),
        object_offsets=torch.tensor([0, 2]),
        context_token_ids=torch.tensor([1, 2]),
        context_offsets=torch.tensor([0, 1]),
        numeric_features=torch.zeros((3, 8)),
        candidate_group_index=torch.tensor([0, 0, 1]),
        group_type_ids=torch.tensor([1, 2]),
    )
    assert scores.shape == (3,)
    assert anomaly.shape == (2,)
