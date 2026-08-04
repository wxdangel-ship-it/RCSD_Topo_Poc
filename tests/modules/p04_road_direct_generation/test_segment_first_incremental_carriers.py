from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation import (
    segment_first_incremental_carriers as incremental,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_carriers import (
    CarrierPlanResult,
)


def _segments() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "segment_id": segment_id,
                "target_required": target_required,
                "target_class": "core_trunk" if target_required else "not_target",
                "geometry": LineString([(offset, 0), (offset + 1, 0)]),
            }
            for offset, (segment_id, target_required) in enumerate(
                (("a", True), ("b", True), ("c", False))
            )
        ],
        geometry="geometry",
        crs="EPSG:32650",
    )


def _assignments(score_b: float = 2.0) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "assigned_segment_id": segment_id,
                "patch_road_key": f"patch:{segment_id}",
                "assignment_source": "direct",
                "assignment_score": score,
                "geometry": LineString([(offset, 0), (offset + 1, 0)]),
            }
            for offset, (segment_id, score) in enumerate(
                (("a", 1.0), ("b", score_b), ("c", 3.0))
            )
        ],
        geometry="geometry",
        crs="EPSG:32650",
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    (
        (None, b"<none>"),
        (float("nan"), b"<nan>"),
        (pd.NA, b"<missing>"),
        (pd.NaT, b"<missing>"),
        ("road", b"str:'road'"),
        (7, b"int:7"),
        (True, b"bool:True"),
        (b"road", b"bytes:b'road'"),
        (1.5, b"float:1.5"),
    ),
)
def test_value_bytes_common_scalar_fast_path_preserves_contract(
    value: object,
    expected: bytes,
) -> None:
    assert incremental._value_bytes(value) == expected


def test_value_bytes_geometry_fast_path_preserves_wkb_contract() -> None:
    geometry = LineString([(0, 0), (1, 1)])
    assert incremental._value_bytes(geometry) == (
        b"<geometry>" + bytes(geometry.wkb)
    )


def _fake_planner(calls: list[tuple[str, ...]]):
    def run(segment_units, swsd_roads, assignments, **kwargs):
        segment_ids = tuple(segment_units["segment_id"].astype(str))
        calls.append(segment_ids)
        plans = []
        carriers = []
        contributions = {}
        for row in segment_units.itertuples(index=False):
            segment_id = str(row.segment_id)
            score = float(
                assignments.loc[
                    assignments["assigned_segment_id"].astype(str).eq(segment_id),
                    "assignment_score",
                ].iloc[0]
            )
            plans.append(
                {
                    "segment_id": segment_id,
                    "segment_state": "hp_full",
                    "geometry": row.geometry,
                }
            )
            carriers.append(
                {
                    "segment_id": segment_id,
                    "id": f"road:{segment_id}:{score}",
                    "realization": "built",
                    "geometry": row.geometry,
                }
            )
            contributions[segment_id] = {
                "assembled_patch_source_count": int(score),
            }
        plan_frame = gpd.GeoDataFrame(
            plans,
            geometry="geometry",
            crs=segment_units.crs,
        )
        carrier_frame = gpd.GeoDataFrame(
            carriers,
            geometry="geometry",
            crs=segment_units.crs,
        )
        summary = {
            "segment_count": len(plans),
            "state_counts": {"hp_full": len(plans)},
            "built_carrier_count": len(carriers),
            "retained_carrier_count": 0,
        }
        return CarrierPlanResult(
            plan_frame,
            carrier_frame,
            summary,
            contributions,
            {
                segment_id: tuple(carrier_frame.columns)
                for segment_id in segment_ids
            },
        )

    return run


def test_incremental_planner_recomputes_only_changed_segment(monkeypatch):
    calls = []
    monkeypatch.setattr(
        incremental,
        "_plan_all_segment_carriers",
        _fake_planner(calls),
    )
    incremental.reset_incremental_carrier_planner()
    segments = _segments()
    swsd = gpd.GeoDataFrame(
        [{"id": "swsd", "geometry": LineString([(0, 0), (1, 0)])}],
        geometry="geometry",
        crs=segments.crs,
    )
    first = incremental.plan_segment_carriers_incremental(
        segments,
        swsd,
        _assignments(),
        run_id="run",
    )
    unchanged = incremental.plan_segment_carriers_incremental(
        segments,
        swsd,
        _assignments(),
        run_id="run",
    )
    changed = incremental.plan_segment_carriers_incremental(
        segments,
        swsd,
        _assignments(score_b=20.0),
        run_id="run",
    )

    assert calls == [("a", "b", "c"), ("b",)]
    assert list(first.carriers["id"]) == ["road:a:1.0", "road:b:2.0", "road:c:3.0"]
    assert unchanged is first
    assert list(changed.carriers["id"]) == ["road:a:1.0", "road:b:20.0", "road:c:3.0"]
    assert changed.summary["assembled_patch_source_count"] == 24
    stats = incremental.incremental_carrier_planner_stats()
    assert stats["invocation_count"] == 3
    assert stats["segment_units_seen"] == 9
    assert stats["segment_units_recomputed"] == 4
    assert stats["segment_units_reused"] == 5


def test_recovery_reservation_change_recomputes_all_target_core_segments(
    monkeypatch,
):
    calls = []
    monkeypatch.setattr(
        incremental,
        "_plan_all_segment_carriers",
        _fake_planner(calls),
    )
    incremental.reset_incremental_carrier_planner()
    segments = _segments()
    swsd = gpd.GeoDataFrame(
        [{"id": "swsd", "geometry": LineString([(0, 0), (1, 0)])}],
        geometry="geometry",
        crs=segments.crs,
    )
    baseline = _assignments()
    incremental.plan_segment_carriers_incremental(
        segments,
        swsd,
        baseline,
        run_id="run",
    )
    changed = baseline.copy()
    changed.loc[
        changed["assigned_segment_id"].eq("a"),
        "assignment_source",
    ] = "target_access_surface_candidate"
    incremental.plan_segment_carriers_incremental(
        segments,
        swsd,
        changed,
        run_id="run",
    )

    assert calls == [("a", "b", "c"), ("a", "b")]


def test_new_through_surface_recomputes_only_its_segment(monkeypatch):
    calls = []
    monkeypatch.setattr(
        incremental,
        "_plan_all_segment_carriers",
        _fake_planner(calls),
    )
    incremental.reset_incremental_carrier_planner()
    segments = _segments()
    swsd = gpd.GeoDataFrame(
        [{"id": "swsd", "geometry": LineString([(0, 0), (1, 0)])}],
        geometry="geometry",
        crs=segments.crs,
    )
    incremental.plan_segment_carriers_incremental(
        segments,
        swsd,
        _assignments(),
        run_id="run",
    )
    through_surfaces = gpd.GeoDataFrame(
        [
            {
                "segment_id": "b",
                "access_id": "access-b",
                "geometry": LineString([(1, -1), (1, 1)]).buffer(0.5),
            }
        ],
        geometry="geometry",
        crs=segments.crs,
    )
    incremental.plan_segment_carriers_incremental(
        segments,
        swsd,
        _assignments(),
        run_id="run",
        required_through_surfaces=through_surfaces,
        forced_through_access_ids={"access-b"},
    )

    assert calls == [("a", "b", "c"), ("b",)]
    stats = incremental.incremental_carrier_planner_stats()
    assert stats["full_recompute_invocation_count"] == 1
    assert stats["incremental_recompute_invocation_count"] == 1


def test_original_planner_contributions_sum_to_public_summary():
    from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_carriers import (
        plan_segment_carriers,
    )

    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "swsd_road_ids": "r1",
                "target_required": False,
                "target_class": "not_target",
                "sgrade": "普通双",
                "segment_type": "normal",
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
        geometry="geometry",
        crs="EPSG:32650",
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "id": "r1",
                "direction": 1,
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
        geometry="geometry",
        crs=segments.crs,
    )
    assignments = gpd.GeoDataFrame(
        [],
        geometry=[],
        crs=segments.crs,
    )
    result = plan_segment_carriers(
        segments,
        swsd,
        assignments,
        run_id="run",
    )

    contributions = result.segment_summary_contributions["s1"]
    for key, value in contributions.items():
        assert result.summary[key] == value
