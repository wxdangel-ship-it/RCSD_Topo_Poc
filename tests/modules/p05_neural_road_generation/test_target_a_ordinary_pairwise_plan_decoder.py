from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_pairwise_plan_decoder import (
    PairwiseStructuredPlanDecoder,
    _pairwise_plan_metrics,
)


def test_pairwise_plan_decoder_is_candidate_order_invariant() -> None:
    torch.manual_seed(17)
    model = PairwiseStructuredPlanDecoder(
        hidden_dim=32,
        dropout=0.0,
    ).eval()
    plan_features = torch.randn(1, 3, 32)
    plan_valid = torch.ones(1, 3, dtype=torch.bool)
    plan_decisions = torch.tensor([[-1, 0, 1]])
    plan_selected = torch.tensor(
        [
            [
                [False, False, False, False],
                [True, True, False, False],
                [False, False, True, True],
            ]
        ]
    )
    signals = torch.randn(1, 4, 3)
    candidate_valid = torch.ones(1, 4, dtype=torch.bool)
    sources = torch.tensor([[0, 0, 1, 1]])
    relations = torch.randn(1, 4, 4, 13)
    relations = (relations + relations.transpose(1, 2)) / 2.0
    original = model(
        plan_features=plan_features,
        base_energies=torch.zeros(1, 3),
        plan_valid=plan_valid,
        plan_decisions=plan_decisions,
        plan_selected=plan_selected,
        candidate_signals=signals,
        candidate_valid=candidate_valid,
        candidate_sources=sources,
        road_relations=relations,
    )
    permutation = torch.tensor([2, 0, 3, 1])
    permuted = model(
        plan_features=plan_features,
        base_energies=torch.zeros(1, 3),
        plan_valid=plan_valid,
        plan_decisions=plan_decisions,
        plan_selected=plan_selected[:, :, permutation],
        candidate_signals=signals[:, permutation],
        candidate_valid=candidate_valid[:, permutation],
        candidate_sources=sources[:, permutation],
        road_relations=relations[:, permutation][:, :, permutation],
    )
    assert torch.allclose(original, permuted, atol=1e-6)


def test_pairwise_metrics_separate_plan_exact_from_safe_abstain() -> None:
    rows = [
        {
            "target_reachable": True,
            "truth_cardinality": 12,
            "selection_label_correct": True,
            "raw_complete_exact": True,
            "raw_automatic": True,
            "automatic": True,
            "unsafe_automatic": False,
            "selected_decision": "USE_RCSD",
        },
        {
            "target_reachable": False,
            "truth_cardinality": 12,
            "selection_label_correct": True,
            "raw_complete_exact": True,
            "raw_automatic": False,
            "automatic": False,
            "unsafe_automatic": False,
            "selected_decision": "ABSTAIN",
        },
    ]
    metrics = _pairwise_plan_metrics(rows)
    assert metrics["raw_complete_exact"] == 1.0
    assert metrics["reachable_plan_exact"] == 1.0
    assert metrics["reachable_plan_exact_count"] == 1
    assert metrics["unreachable_safe_abstain_count"] == 1
    assert metrics["long_10_plus_reachable_plan_exact_count"] == 1
