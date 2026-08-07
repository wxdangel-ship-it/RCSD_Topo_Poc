from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_structured_combination_decoder import (
    STRUCTURED_COMBINATION_FEATURE_DIM,
    TargetAStructuredCombinationConfig,
    TargetAStructuredCombinationDecoder,
)


def test_structured_combination_decoder_masks_padding() -> None:
    model = TargetAStructuredCombinationDecoder(
        TargetAStructuredCombinationConfig(
            hidden_dim=16,
            dropout=0.0,
        )
    )
    values = torch.zeros((2, 5, STRUCTURED_COMBINATION_FEATURE_DIM))
    mask = torch.tensor(
        [
            [True, True, True, False, False],
            [True, False, False, False, False],
        ]
    )
    logits = model(values, mask)
    assert logits.shape == (2, 5)
    assert torch.isneginf(logits[0, 3])
    assert torch.isneginf(logits[1, 1])
    logits[mask].sum().backward()
    assert all(
        parameter.grad is not None for parameter in model.parameters()
    )


def test_structured_combination_decoder_rejects_wrong_feature_dim() -> None:
    model = TargetAStructuredCombinationDecoder(
        TargetAStructuredCombinationConfig(
            hidden_dim=8,
            dropout=0.0,
        )
    )
    try:
        model(
            torch.zeros((1, 2, STRUCTURED_COMBINATION_FEATURE_DIM - 1)),
            torch.ones((1, 2), dtype=torch.bool),
        )
    except ValueError as error:
        assert "feature shape" in str(error)
    else:
        raise AssertionError("wrong feature dimension was accepted")
