from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_oof import (
    _plan_metrics,
)


def test_ordinary_metrics_separate_plan_exact_from_carrier_decision() -> None:
    rows = [
        {
            "predicted_decision": "USE_RCSD",
            "acceptable_decisions": ["USE_RCSD"],
            "acceptable_exact": False,
            "preferred_exact": False,
            "preferred_decision": "USE_RCSD",
        },
        {
            "predicted_decision": "KEEP_SWSD",
            "acceptable_decisions": ["KEEP_SWSD"],
            "acceptable_exact": True,
            "preferred_exact": True,
            "preferred_decision": "KEEP_SWSD",
        },
    ]
    metrics = _plan_metrics(rows)
    assert metrics["complete_plan_acceptable_exact"] == 0.5
    assert metrics["carrier_decision_accuracy"] == 1.0
    assert metrics["preferred_plan_exact"] == 0.5
