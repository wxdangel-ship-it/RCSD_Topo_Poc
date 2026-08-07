from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_network import (
    TargetAOrdinaryAccessCardinalityDecoder,
    TargetAOrdinaryAccessDecoder,
    parameter_count,
)


def test_access_decoder_scores_masked_candidate_sets() -> None:
    model = TargetAOrdinaryAccessDecoder(
        feature_dim=12,
        hidden_dim=16,
        context_dim=24,
        dropout=0.0,
    )
    values = torch.randn(2, 5, 12)
    mask = torch.tensor(
        [
            [True, True, True, False, False],
            [True, False, False, False, False],
        ]
    )
    logits = model(values, mask)
    assert logits.shape == (2, 5)
    assert torch.isfinite(logits).all()
    assert torch.equal(logits[~mask], torch.zeros_like(logits[~mask]))
    assert parameter_count(model) > 0


def test_access_decoder_rejects_shape_drift() -> None:
    model = TargetAOrdinaryAccessDecoder(feature_dim=4)
    values = torch.randn(2, 3, 5)
    mask = torch.ones(2, 3, dtype=torch.bool)
    try:
        model(values, mask)
    except ValueError as error:
        assert "shape differs" in str(error)
    else:
        raise AssertionError("feature shape drift should fail")


def test_cardinality_decoder_returns_masked_structured_outputs() -> None:
    model = TargetAOrdinaryAccessCardinalityDecoder(
        feature_dim=4,
        hidden_dim=16,
        context_dim=24,
        attention_heads=4,
        max_cardinality=5,
        dropout=0.0,
    )
    values = torch.randn(2, 4, 4)
    mask = torch.tensor(
        [[True, True, True, False], [True, True, False, False]]
    )

    member_logits, cardinality_logits = model(values, mask)

    assert member_logits.shape == (2, 4)
    assert cardinality_logits.shape == (2, 5)
    minimum = torch.finfo(cardinality_logits.dtype).min
    assert torch.equal(
        cardinality_logits[0, 3:],
        torch.full_like(cardinality_logits[0, 3:], minimum),
    )
    assert torch.equal(
        cardinality_logits[1, 2:],
        torch.full_like(cardinality_logits[1, 2:], minimum),
    )
