from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_conditioning import (
    ACCESS_ANCHOR_FEATURE_NAMES,
    ConditioningRoad,
    anchor_condition_features,
)


def _road(
    road_id: str,
    source: str,
    start: str,
    end: str,
    coordinates: list[tuple[float, float]],
) -> ConditioningRoad:
    return ConditioningRoad(
        road_id=road_id,
        source=source,
        start_node_id=start,
        end_node_id=end,
        geometry=LineString(coordinates),
    )


def test_anchor_condition_supports_node_and_road_candidates() -> None:
    roads = {
        "r1": _road("r1", "RCSD", "n1", "n2", [(0, 0), (1, 0)]),
        "r2": _road("r2", "RCSD", "n2", "n3", [(1, 0), (2, 0)]),
        "s1": _road("s1", "SWSD", "s1a", "s1b", [(0, 3), (1, 3)]),
    }
    values = anchor_condition_features(
        road=roads["r2"],
        candidate_ids=["NODE:n2", "ROAD:r1"],
        roads=roads,
        status_success=True,
        gate_passed=True,
        proven_safe=True,
        candidate_confidence=0.8,
        candidate_probability=0.7,
        success_probability=0.9,
        gate_pass_probability=0.95,
    )
    by_name = dict(zip(ACCESS_ANCHOR_FEATURE_NAMES, values))
    assert by_name["condition_available"] == 1.0
    assert by_name["anchor_type_node"] == 1.0
    assert by_name["anchor_type_road"] == 1.0
    assert by_name["road_incident_anchor_node"] == 1.0
    assert by_name["road_shares_anchor_road_endpoint"] == 1.0
    assert by_name["road_within_0_5m_anchor_road"] == 1.0
    assert by_name["road_source_rcsd"] == 1.0


def test_missing_exact_anchor_does_not_invent_condition() -> None:
    road = _road("r1", "SWSD", "a", "b", [(0, 0), (1, 0)])
    values = anchor_condition_features(
        road=road,
        candidate_ids=[],
        roads={"r1": road},
        status_success=True,
        gate_passed=True,
        proven_safe=False,
        candidate_confidence=0.0,
        candidate_probability=0.0,
        success_probability=1.0,
        gate_pass_probability=1.0,
    )
    by_name = dict(zip(ACCESS_ANCHOR_FEATURE_NAMES, values))
    assert by_name["condition_available"] == 0.0
    assert by_name["anchor_status_success"] == 1.0
    assert by_name["anchor_proven_safe"] == 0.0
    assert by_name["road_is_anchor_member"] == 0.0
    assert by_name["road_source_swsd"] == 1.0
