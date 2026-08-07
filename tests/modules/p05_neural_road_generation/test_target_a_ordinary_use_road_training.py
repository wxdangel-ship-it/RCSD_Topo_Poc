from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_use_road_training import (
    choose_zero_use_set_error_threshold,
    ordinary_use_road_metrics,
    road_endpoint_adjacency,
)


def test_endpoint_adjacency_uses_shared_nodes_without_raw_id_features() -> None:
    adjacency = road_endpoint_adjacency(
        [("n1", "n2"), ("n2", "n3"), ("n4", "n5")]
    )
    assert bool(adjacency[0, 1])
    assert bool(adjacency[1, 0])
    assert not bool(adjacency[0, 2])


def test_use_threshold_requires_single_component_exact_sets() -> None:
    rows = [
        {
            "confidence": 0.6,
            "release_eligible": True,
            "selected_component_count": 1,
            "road_set_exact": False,
        },
        {
            "confidence": 0.9,
            "release_eligible": True,
            "selected_component_count": 2,
            "road_set_exact": False,
        },
    ]
    threshold = choose_zero_use_set_error_threshold(rows)
    assert 0.6 < threshold < 0.61


def test_use_metrics_separate_conditional_safety() -> None:
    rows = [
        {
            "case_key": "c1",
            "road_set_exact": True,
            "road_f1": 1.0,
            "cardinality_exact": True,
            "selected_component_count": 1,
            "conditional_automatic": True,
        },
        {
            "case_key": "c2",
            "road_set_exact": False,
            "road_f1": 0.5,
            "cardinality_exact": False,
            "selected_component_count": 2,
            "conditional_automatic": False,
        },
    ]
    metrics = ordinary_use_road_metrics(rows)
    assert metrics["road_set_exact"] == 0.5
    assert metrics["road_macro_f1"] == 0.75
    assert metrics["unsafe_conditional_automatic_count"] == 0
