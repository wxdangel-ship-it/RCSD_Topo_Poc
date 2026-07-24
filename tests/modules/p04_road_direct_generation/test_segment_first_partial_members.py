from __future__ import annotations

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, box

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_partial_members import (
    build_partial_member_carriers,
)


def test_partial_member_uses_observation_completion_and_separate_retained_part() -> None:
    member = pd.Series(
        {
            "id": 1,
            "direction": 2,
            "snodeid": 10,
            "enodeid": 20,
            "geometry": LineString([(0, 0), (100, 0)]),
        }
    )
    evidence = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "p:1",
                "geometry": LineString([(50, 1), (90, 1)]),
            }
        ],
        crs="EPSG:32650",
    )

    rows = build_partial_member_carriers(
        "s",
        "1",
        member,
        evidence,
        run_id="run",
        drivezone_surface=box(89, -2, 101, 2),
        full_minimum_coverage=0.60,
        sample_spacing_m=2.0,
        completion_min_coverage=0.90,
        member_carrier_builder=_fake_member_builder,
    )

    assert len(rows) == 2
    built, retained = rows
    assert built["realization"] == "built"
    assert built["geometry"].coords[0] == pytest.approx((50.0, 1.0))
    assert built["geometry"].coords[-1] == pytest.approx((100.0, 0.0))
    assert built["inherit_source_snodeid"] is False
    assert built["inherit_source_enodeid"] is True
    assert built["internal_completion_fraction"] > 0.0
    assert retained["realization"] == "retained"
    assert retained["geometry_source"] == "swsd_retained_partial"
    assert retained["geometry"].coords[0] == pytest.approx((0.0, 0.0))
    assert retained["geometry"].coords[-1] == pytest.approx((50.0, 0.0))
    assert retained["inherit_source_snodeid"] is True
    assert retained["inherit_source_enodeid"] is False


def test_partial_member_does_not_activate_for_bidirectional_swsd_member() -> None:
    member = pd.Series(
        {
            "id": 1,
            "direction": 1,
            "geometry": LineString([(0, 0), (100, 0)]),
        }
    )
    evidence = gpd.GeoDataFrame(
        [{"patch_road_key": "p:1", "geometry": LineString([(0, 0), (50, 0)])}],
        crs="EPSG:32650",
    )

    rows = build_partial_member_carriers(
        "s",
        "1",
        member,
        evidence,
        run_id="run",
        drivezone_surface=box(-1, -1, 101, 1),
        full_minimum_coverage=0.60,
        sample_spacing_m=2.0,
        completion_min_coverage=0.90,
        member_carrier_builder=_fake_member_builder,
    )

    assert rows == []


def _fake_member_builder(
    segment_id: str,
    member_id: str,
    member: pd.Series,
    evidence: gpd.GeoDataFrame,
    **_: object,
) -> list[dict[str, object]]:
    geometry = evidence.iloc[0].geometry
    return [
        {
            "segment_id": segment_id,
            "member_swsd_road_id": member_id,
            "patch_road_key": "p:1",
            "source_patch_road_keys": "p:1",
            "carrier_id": "built:1",
            "carrier_role": "main_oneway",
            "direction_role": "forward",
            "realization": "built",
            "geometry_source": "hp_observed",
            "observed_coverage_ratio": 0.50,
            "internal_completion_fraction": 0.0,
            "assembly_state": "single_patch_observation",
            "geometry": geometry,
        }
    ]
