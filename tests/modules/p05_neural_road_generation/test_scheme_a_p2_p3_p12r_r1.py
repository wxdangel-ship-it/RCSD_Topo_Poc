from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_models import (
    RoadRecord,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_r1_candidates import (
    _build_bundles,
    build_truth_free_case_candidates,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_r1_models import (
    P12RR1Config,
)


def test_config_rejects_invalid_candidate_scale() -> None:
    config = P12RR1Config(max_candidate_count_p95=0)
    try:
        config.validate()
    except ValueError as error:
        assert "max_candidate_count_p95" in str(error)
    else:
        raise AssertionError("invalid config was accepted")


def test_bundle_groups_parallel_and_sequential_roads() -> None:
    roads = [
        _road("a", [(0, 0), (10, 10)], snodeid="a0", enodeid="a1"),
        _road("b", [(1, 0), (11, 10)], snodeid="b0", enodeid="b1"),
        _road(
            "c",
            [(10.5, 10.5), (20, 20)],
            snodeid="c0",
            enodeid="c1",
        ),
        _road(
            "far",
            [(100, 100), (110, 110)],
            snodeid="f0",
            enodeid="f1",
        ),
    ]
    bundles = _build_bundles(roads, P12RR1Config())
    road_sets = {frozenset(row["road_ids"]) for row in bundles}
    assert frozenset({"a", "b", "c"}) in road_sets
    assert frozenset({"far"}) in road_sets


def test_endpoint_owner_pair_adds_truth_free_candidate() -> None:
    result = build_truth_free_case_candidates(
        case_key="T10:fixture",
        skeleton=_skeleton(ambiguous=False),
        t01_roads=_t01_roads(ambiguous=False),
        raw_rcsd_roads=_raw_roads(),
        config=P12RR1Config(),
    )
    object_row = result["objects"][0]
    assert object_row["control_candidate_road_ids"] == []
    assert object_row["treatment_candidate_road_ids"] == ["raw_ar"]
    candidate = result["candidates"][0]
    assert candidate["candidate_sources"] == ["ENDPOINT_JUNCTION"]
    assert candidate["endpoint_evidence_complete"] is True
    assert candidate["orientation"] == "FORWARD"


def test_ambiguous_orientation_is_not_auto_added() -> None:
    result = build_truth_free_case_candidates(
        case_key="T10:fixture",
        skeleton=_skeleton(ambiguous=True),
        t01_roads=_t01_roads(ambiguous=True),
        raw_rcsd_roads=_raw_roads(),
        config=P12RR1Config(),
    )
    assert result["objects"][0]["treatment_candidate_road_ids"] == []
    assert result["candidates"] == []
    assert any(
        row["orientation"] == "AMBIGUOUS"
        and not row["endpoint_candidate_selected"]
        for row in result["evidence"]
    )


def _skeleton(*, ambiguous: bool) -> dict[str, object]:
    target_roads = ["owner_a"] if ambiguous else ["owner_b"]
    return {
        "segments": [
            {
                "segment_id": "A",
                "segment_type": "STANDARD",
                "swsd_road_ids": ["owner_a"],
            },
            {
                "segment_id": "B",
                "segment_type": "STANDARD",
                "swsd_road_ids": target_roads,
            },
            {
                "access_valid": True,
                "segment_id": "advance_right_fixture",
                "segment_type": "ADVANCE_RIGHT",
                "source_segment_access": "A@a1",
                "swsd_road_ids": ["swsd_ar"],
                "target_segment_access": "B@b1",
            },
        ]
    }


def _t01_roads(*, ambiguous: bool) -> list[RoadRecord]:
    target_geometry = (
        [(0, 0), (10, 0)]
        if ambiguous
        else [(20, 10), (30, 10)]
    )
    return [
        _road(
            "owner_a",
            [(0, 0), (10, 0)],
            source=2,
            formway=0,
        ),
        _road(
            "owner_b",
            target_geometry,
            source=2,
            formway=0,
        ),
        _road(
            "swsd_ar",
            [(0, 100), (30, 100)],
            source=2,
        ),
    ]


def _raw_roads() -> list[RoadRecord]:
    return [
        _road(
            "source_carrier",
            [(-5, 0), (0, 0)],
            snodeid="source_outer",
            enodeid="raw_source",
            formway=0,
        ),
        _road(
            "target_carrier",
            [(10, 10), (35, 10)],
            snodeid="raw_target",
            enodeid="target_outer",
            formway=0,
        ),
        _road(
            "raw_ar",
            [(0, 0), (10, 10)],
            snodeid="raw_source",
            enodeid="raw_target",
        ),
    ]


def _road(
    road_id: str,
    coordinates: list[tuple[float, float]],
    *,
    snodeid: str = "s",
    enodeid: str = "e",
    source: int = 1,
    formway: int = 128,
) -> RoadRecord:
    return RoadRecord(
        road_id=road_id,
        source=source,
        snodeid=snodeid,
        enodeid=enodeid,
        formway=formway,
        segment_id="",
        source_road_id="",
        split_original_road_id="",
        mixed_advance_right=False,
        geometry=LineString(coordinates),
        properties={},
    )
