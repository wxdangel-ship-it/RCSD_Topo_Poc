from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_training import (
    acceptable_set_nll,
    choose_zero_error_threshold,
    ordinary_access_metrics,
)


def test_access_loss_accepts_multiple_correct_candidates() -> None:
    logits = torch.tensor([[0.0, 3.0, 2.0, -1.0]])
    acceptable = torch.tensor([[False, True, True, False]])
    valid = torch.tensor([[True, True, True, True]])
    loss = acceptable_set_nll(logits, acceptable, valid)
    assert loss.shape == (1,)
    assert 0.0 < float(loss[0]) < 0.1


def test_zero_error_threshold_uses_only_release_eligible_errors() -> None:
    rows = [
        {"confidence": 0.8, "release_eligible": True, "raw_exact": False},
        {"confidence": 0.9, "release_eligible": False, "raw_exact": False},
        {"confidence": 0.7, "release_eligible": True, "raw_exact": True},
    ]
    threshold = choose_zero_error_threshold(rows)
    assert 0.8 < threshold < 0.81


def test_access_metrics_separate_teacher_oof_and_abstain() -> None:
    rows = [
        {
            "case_key": "c1",
            "raw_exact": True,
            "teacher_exact": True,
            "release_eligible": True,
            "automatic": True,
        },
        {
            "case_key": "c2",
            "raw_exact": False,
            "teacher_exact": True,
            "release_eligible": False,
            "automatic": False,
        },
    ]
    metrics = ordinary_access_metrics(rows)
    assert metrics["oof_raw_exact"] == 0.5
    assert metrics["teacher_raw_exact"] == 1.0
    assert metrics["automatic_coverage"] == 0.5
    assert metrics["unsafe_automatic_count"] == 0
