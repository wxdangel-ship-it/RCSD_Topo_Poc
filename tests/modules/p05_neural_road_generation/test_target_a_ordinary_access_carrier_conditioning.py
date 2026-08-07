from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_carrier_conditioning import (
    ACCESS_CARRIER_FEATURE_NAMES,
    carrier_condition_features,
)


def test_carrier_condition_marks_complete_selected_road() -> None:
    values = carrier_condition_features(
        road_id="r1",
        road_source="RCSD",
        decision="USE_RCSD",
        selected_road_ids={"r1", "r2"},
        condition_available=True,
        decision_confidence=0.8,
        road_set_confidence=0.7,
        release_ready=True,
    )
    by_name = dict(zip(ACCESS_CARRIER_FEATURE_NAMES, values))
    assert by_name["decision_use_rcsd"] == 1.0
    assert by_name["road_in_complete_carrier"] == 1.0
    assert by_name["road_source_matches_decision"] == 1.0
    assert by_name["upstream_release_ready"] == 1.0


def test_missing_carrier_condition_does_not_select_road() -> None:
    values = carrier_condition_features(
        road_id="s1",
        road_source="SWSD",
        decision="",
        selected_road_ids=set(),
        condition_available=False,
        decision_confidence=0.0,
        road_set_confidence=0.0,
        release_ready=False,
    )
    by_name = dict(zip(ACCESS_CARRIER_FEATURE_NAMES, values))
    assert by_name["condition_available"] == 0.0
    assert by_name["road_in_complete_carrier"] == 0.0
    assert by_name["road_source_matches_decision"] == 0.0
