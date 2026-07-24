import pytest

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_p2_oof import (
    _softmax_confidences,
    _validate_pto_a,
)


def test_softmax_confidence_prefers_lowest_cost_and_normalizes() -> None:
    probabilities = _softmax_confidences([0.0, 1.0, 3.0])
    assert probabilities[0] > probabilities[1] > probabilities[2]
    assert sum(probabilities) == pytest.approx(1.0)


def test_pto_a_validation_rejects_missing_dependency() -> None:
    failures, multi = _validate_pto_a(
        [
            {
                "candidate_id": "candidate-a",
                "group_id": "group-a",
                "object_type": "SEGMENT",
                "dependencies": ["group-missing"],
                "payload": {},
            }
        ]
    )
    assert failures == ["candidate-a missing dependency group-missing"]
    assert multi == 0


def test_pto_a_validation_rejects_multiple_publishable_through_relations() -> None:
    rows = [
        {
            "candidate_id": f"candidate-{index}",
            "group_id": f"group-{index}",
            "object_type": "RELATION",
            "dependencies": [],
            "payload": {
                "structural_role": "THROUGH",
                "state": "PUBLISHABLE",
                "junction_id": "junction-a",
            },
        }
        for index in range(2)
    ]
    failures, multi = _validate_pto_a(rows)
    assert failures == ["multiple publishable THROUGH relations selected"]
    assert multi == 1
