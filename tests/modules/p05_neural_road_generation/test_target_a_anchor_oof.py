from __future__ import annotations

from types import SimpleNamespace

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_oof import (
    _balanced_class_weights,
    _classification_metrics,
)


def test_anchor_metrics_separate_supported_and_unseen_statuses() -> None:
    rows = [
        {
            "label_index": 0,
            "predicted_index": 0,
            "candidate_supervised": True,
            "candidate_acceptable_exact": True,
            "candidate_preferred_exact": True,
        },
        {
            "label_index": 3,
            "predicted_index": 3,
            "candidate_supervised": False,
        },
        {
            "label_index": 0,
            "predicted_index": 3,
            "status_supervised": False,
            "candidate_supervised": False,
        },
    ]
    metrics = _classification_metrics(rows)
    assert metrics["accuracy"] == 1.0
    assert metrics["count"] == 2
    assert metrics["prediction_count"] == 3
    assert metrics["macro_f1_supported_statuses"] == 1.0
    assert metrics["macro_f1_all_statuses"] == 0.4
    assert metrics["candidate_selection"]["acceptable_exact"] == 1.0


def test_anchor_class_balance_is_separate_from_label_confidence() -> None:
    examples = [
        SimpleNamespace(status_label=0),
        SimpleNamespace(status_label=3),
        SimpleNamespace(status_label=3),
        SimpleNamespace(status_label=0, status_supervised=False),
    ]
    weights = _balanced_class_weights(examples)
    assert weights == (1.5, 0.0, 0.0, 0.75, 0.0)
