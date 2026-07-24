from __future__ import annotations

import math

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p7_audit import (
    aggregate_neighborhood,
    best_recall_one_threshold,
    relative_geometry_features,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p7_models import (
    DECISION_AUDIT_NO_GO,
    DECISION_CURRENT_SOURCE_NO_GO,
    DECISION_REPRESENTATION_GO,
    choose_p7_decision,
)


def test_choose_p7_decision_separates_audit_and_source_failure() -> None:
    assert choose_p7_decision(True, True, True) == DECISION_REPRESENTATION_GO
    assert (
        choose_p7_decision(True, False, True)
        == DECISION_CURRENT_SOURCE_NO_GO
    )
    assert (
        choose_p7_decision(True, True, False)
        == DECISION_CURRENT_SOURCE_NO_GO
    )
    assert choose_p7_decision(False, True, True) == DECISION_AUDIT_NO_GO


def test_aggregate_neighborhood_has_defined_zero_neighbor_contract() -> None:
    features = {"a": (1.0, 2.0), "b": (3.0, 6.0)}
    result = aggregate_neighborhood(features, {"a": set(), "b": {"a"}})
    assert result["a"] == (0.0, 0.0, 0.0, 0.0, 0.0)
    assert result["b"][:2] == (-2.0, -4.0)
    assert result["b"][2:4] == (0.0, 0.0)
    assert result["b"][4] == math.log1p(1)


def test_relative_geometry_is_translation_and_rotation_invariant() -> None:
    components = (((0.0, 0.0), (3.0, 0.0), (3.0, 4.0)),)
    translated_rotated = (
        ((10.0, -2.0), (10.0, 1.0), (6.0, 1.0)),
    )
    first = relative_geometry_features(
        components,
        pair_node_count=2,
        junction_node_count=1,
    )
    second = relative_geometry_features(
        translated_rotated,
        pair_node_count=2,
        junction_node_count=1,
    )
    assert len(first) == 12
    assert all(math.isclose(a, b, abs_tol=1e-12) for a, b in zip(first, second))


def test_best_recall_one_threshold_proves_infeasible_precision() -> None:
    audit = best_recall_one_threshold(
        probabilities=(0.1, 0.2, 0.3, 0.4),
        targets=(True, False, False, False),
        required_precision=0.8,
        required_macro_f1=0.85,
    )
    assert audit["recall"] == 1.0
    assert audit["precision"] == 0.25
    assert audit["feasible"] is False
