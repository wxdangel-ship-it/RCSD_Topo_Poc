from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_geometry_teacher_student import (
    apply_strict_geometry_truth,
    choose_zero_error_end_to_end_geometry_threshold,
)


def test_geometry_cannot_hide_unsafe_upstream_ordinary_state() -> None:
    row = {
        "case_key": "case",
        "object_id": "ar",
        "raw_complete_plan_geometry_exact": True,
        "automatic_decision": True,
        "base_automatic_decision": True,
        "geometry_confidence": 0.9,
        "missing_geometry_proposal_types": [],
    }
    strict = {
        "case_key": "case",
        "object_id": "ar",
        "safety_target": False,
        "adjacent_access_road_resolved": True,
    }
    result = apply_strict_geometry_truth(
        [row],
        strict_examples={("case", "ar"): strict},
    )[0]
    assert not result["raw_end_to_end_complete_exact"]
    assert result["unsafe_automatic"]


def test_geometry_threshold_uses_end_to_end_exact_not_local_exact() -> None:
    rows = [
        {
            "base_automatic_decision": True,
            "missing_geometry_proposal_types": [],
            "geometry_confidence": 0.9,
            "raw_end_to_end_complete_exact": False,
        },
        {
            "base_automatic_decision": True,
            "missing_geometry_proposal_types": [],
            "geometry_confidence": 0.8,
            "raw_end_to_end_complete_exact": True,
        },
    ]
    assert choose_zero_error_end_to_end_geometry_threshold(rows) > 0.9
