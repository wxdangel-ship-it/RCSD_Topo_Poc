from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_audit import (
    _candidate_component_hits,
    _road_origin,
    assign_case_grouped_folds,
    classify_truth_plan,
    required_source_from_relation_status,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p12r_models import (
    PLAN_MIXED_SPLICE,
    PLAN_RCSD_ONLY,
    PLAN_REVIEW_FALLBACK,
    PLAN_SAFE_SWSD_FALLBACK,
    PLAN_SWSD_ONLY,
    REQUIRED_RCSD,
    REQUIRED_SWSD,
    RoadRecord,
)


def test_case_grouped_folds_are_deterministic_and_non_empty() -> None:
    counts = {
        "T10:1885118": 187,
        "T10:605415675": 87,
        "T10:609214532": 155,
        "T10:706247": 29,
        "T10:74155468": 3,
        "T10:991176": 13,
    }
    first = assign_case_grouped_folds(counts, fold_count=5)
    second = assign_case_grouped_folds(
        dict(reversed(list(counts.items()))),
        fold_count=5,
    )
    assert first == second
    assert set(first.values()) == set(range(5))


def test_relation_status_controls_required_side_source() -> None:
    assert required_source_from_relation_status("replaced") == REQUIRED_RCSD
    assert (
        required_source_from_relation_status("replaced+retained_swsd")
        == REQUIRED_RCSD
    )
    assert (
        required_source_from_relation_status("retained_swsd")
        == REQUIRED_SWSD
    )
    assert required_source_from_relation_status("failed") == REQUIRED_SWSD


def test_truth_plan_follows_adjacent_segment_sources() -> None:
    assert (
        classify_truth_plan(
            access_valid=True,
            required_sources=(REQUIRED_RCSD, REQUIRED_RCSD),
            truth_swsd_count=1,
            truth_rcsd_count=2,
            topology_hard_fail=False,
        )
        == PLAN_RCSD_ONLY
    )
    assert (
        classify_truth_plan(
            access_valid=True,
            required_sources=(REQUIRED_SWSD, REQUIRED_RCSD),
            truth_swsd_count=1,
            truth_rcsd_count=1,
            topology_hard_fail=False,
        )
        == PLAN_MIXED_SPLICE
    )
    assert (
        classify_truth_plan(
            access_valid=True,
            required_sources=(REQUIRED_RCSD, REQUIRED_RCSD),
            truth_swsd_count=1,
            truth_rcsd_count=0,
            topology_hard_fail=False,
        )
        == PLAN_SAFE_SWSD_FALLBACK
    )
    assert (
        classify_truth_plan(
            access_valid=True,
            required_sources=(REQUIRED_SWSD, REQUIRED_SWSD),
            truth_swsd_count=1,
            truth_rcsd_count=0,
            topology_hard_fail=False,
        )
        == PLAN_SWSD_ONLY
    )
    assert (
        classify_truth_plan(
            access_valid=False,
            required_sources=(REQUIRED_RCSD, REQUIRED_RCSD),
            truth_swsd_count=1,
            truth_rcsd_count=1,
            topology_hard_fail=False,
        )
        == PLAN_REVIEW_FALLBACK
    )


def test_topology_supplement_keeps_swsd_business_origin() -> None:
    road = _road(
        "42__t06toposupp_1",
        source=1,
        source_road_id="42",
        split_original_road_id="42",
        properties={"t06_split_reason": "topology_supplement_from_swsd"},
    )
    assert (
        _road_origin(
            road,
            t01_road_ids={"42"},
            raw_rcsd_road_ids={"99"},
        )
        == REQUIRED_SWSD
    )


def test_candidate_hit_accepts_lineage_or_geometric_materialization() -> None:
    truth = _road(
        "derived",
        source=1,
        geometry=LineString([(0, 0), (10, 0)]),
    )
    lineage = _road(
        "raw-lineage",
        source=1,
        source_road_id="derived",
        geometry=LineString([(100, 100), (110, 100)]),
    )
    geometric = _road(
        "raw-geometric",
        source=1,
        geometry=LineString([(0, 2), (10, 2)]),
    )
    far = _road(
        "raw-far",
        source=1,
        geometry=LineString([(0, 8), (10, 8)]),
    )
    assert _candidate_component_hits(
        truth=truth,
        candidates=[lineage, geometric, far],
        max_distance_m=5.0,
    ) == ["raw-geometric", "raw-lineage"]


def _road(
    road_id: str,
    *,
    source: int,
    source_road_id: str = "",
    split_original_road_id: str = "",
    geometry: LineString | None = None,
    properties: dict[str, object] | None = None,
) -> RoadRecord:
    return RoadRecord(
        road_id=road_id,
        source=source,
        snodeid="s",
        enodeid="e",
        formway=128,
        segment_id="",
        source_road_id=source_road_id,
        split_original_road_id=split_original_road_id,
        mixed_advance_right=False,
        geometry=geometry or LineString([(0, 0), (1, 0)]),
        properties=properties or {},
    )
