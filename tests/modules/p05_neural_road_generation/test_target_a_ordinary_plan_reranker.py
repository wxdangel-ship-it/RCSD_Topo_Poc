from __future__ import annotations

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_proposals import (
    PLAN_PROPOSAL_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_plan_reranker import (
    TargetAOrdinaryPlanProposalReranker,
    acceptable_plan_nll,
    choose_zero_error_plan_threshold,
)


def test_plan_reranker_respects_proposal_mask() -> None:
    model = TargetAOrdinaryPlanProposalReranker(
        hidden_dim=16,
        feedforward_dim=32,
        layer_count=1,
        head_count=4,
        dropout=0.0,
    )
    features = torch.randn(2, 3, PLAN_PROPOSAL_FEATURE_DIM)
    mask = torch.tensor(
        [[True, True, False], [True, True, True]],
        dtype=torch.bool,
    )

    logits = model(features, mask)

    assert logits.shape == (2, 3)
    assert torch.isfinite(logits[0, :2]).all()
    assert logits[0, 2].item() == torch.finfo(logits.dtype).min
    assert torch.isfinite(logits[1]).all()


def test_acceptable_plan_nll_supports_multiple_correct_proposals() -> None:
    logits = torch.tensor([[0.0, 1.0, 2.0]])
    valid = torch.tensor([[True, True, True]])
    multiple = torch.tensor([[False, True, True]])
    single = torch.tensor([[False, False, True]])

    multiple_loss = acceptable_plan_nll(logits, multiple, valid)
    single_loss = acceptable_plan_nll(logits, single, valid)
    all_loss = acceptable_plan_nll(logits, valid, valid)

    assert multiple_loss.item() < single_loss.item()
    assert all_loss.item() == pytest.approx(0.0)


def test_zero_error_threshold_sits_above_highest_inner_error() -> None:
    rows = [
        {
            "confidence": 0.2,
            "raw_automatic": True,
            "complete_exact": False,
        },
        {
            "confidence": 0.9,
            "raw_automatic": True,
            "complete_exact": True,
        },
        {
            "confidence": 0.7,
            "raw_automatic": False,
            "complete_exact": False,
        },
    ]

    threshold = choose_zero_error_plan_threshold(rows)

    assert threshold > 0.2
    assert threshold < 0.200001
    assert choose_zero_error_plan_threshold(rows[1:]) == 0.0
