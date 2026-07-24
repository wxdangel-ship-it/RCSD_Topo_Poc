from __future__ import annotations

import numpy as np

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_baselines import operation_metrics


def test_operation_metrics_reports_confusion_and_macro_f1() -> None:
    truth = np.asarray([0, 1, 1, 3], dtype=np.int64)
    prediction = np.asarray([0, 1, 0, 3], dtype=np.int64)
    metrics = operation_metrics(truth, prediction, np.asarray([0.3, 0.7, 0.7, 0.7]))
    assert metrics["count"] == 4
    assert metrics["accuracy"] == 0.75
    assert metrics["weighted_accuracy"] == 17 / 24
    assert metrics["confusion"][1][0] == 1
    assert metrics["per_class"]["SPLIT_2"]["recall"] == 1.0
