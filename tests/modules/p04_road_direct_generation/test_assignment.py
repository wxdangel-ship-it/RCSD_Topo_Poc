from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Polygon

from rcsd_topo_poc.modules.p04_road_direct_generation.assignment import (
    build_lane_assignments,
    classify_width,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.config import MilestoneOneConfig


def _config(tmp_path: Path) -> MilestoneOneConfig:
    return MilestoneOneConfig(
        patch_root=tmp_path,
        swsd_road_path=tmp_path / "road.gpkg",
        swsd_node_path=tmp_path / "node.gpkg",
        output_dir=tmp_path / "out",
        run_id="synthetic",
        analysis_crs="EPSG:32650",
    )


def test_lane_owner_and_bilateral_width_form_an_accepted_decision(tmp_path: Path) -> None:
    crs = "EPSG:32650"
    lane = LineString([(0, 0), (40, 0)])
    lanes = gpd.GeoDataFrame(
        [
            {
                "Id": 1,
                "RoadId": 10,
                "patch_id": "p1",
                "IsIntersectionInLane": False,
                "IsIntersectionOutLane": False,
                "geometry": lane,
            }
        ],
        crs=crs,
    )
    boundaries = gpd.GeoDataFrame(
        [
            {"Id": 101, "patch_id": "p1", "geometry": LineString([(0, 1.75), (40, 1.75)])},
            {"Id": 102, "patch_id": "p1", "geometry": LineString([(0, -1.75), (40, -1.75)])},
        ],
        crs=crs,
    )
    swsd = gpd.GeoDataFrame(
        [
            {
                "swsd_unit_id": "r1",
                "direction": 2,
                "patch_membership": frozenset({"p1"}),
                "geometry": LineString([(0, 0), (40, 0)]),
            },
            {
                "swsd_unit_id": "r2",
                "direction": 2,
                "patch_membership": frozenset({"p1"}),
                "geometry": LineString([(0, 12), (40, 12)]),
            },
        ],
        crs=crs,
    )
    drivezone = gpd.GeoDataFrame(
        [{"patch_id": "p1", "geometry": Polygon([(-2, -4), (42, -4), (42, 4), (-2, 4)])}],
        crs=crs,
    )
    divstrip = gpd.GeoDataFrame(
        [{"patch_id": "p1", "geometry": Polygon([(100, 100), (101, 100), (101, 101), (100, 101)])}],
        crs=crs,
    )
    lane_next = pd.DataFrame(columns=["LaneId", "NextLaneId"])
    reference = gpd.GeoDataFrame(
        columns=["FromLaneId", "ToLaneId", "FlowNum", "geometry"], geometry="geometry", crs=crs
    )

    result = build_lane_assignments(
        lanes,
        boundaries,
        swsd,
        drivezone,
        divstrip,
        lane_next,
        reference,
        config=_config(tmp_path),
    )

    decision = result.decisions.iloc[0]
    assert decision["decision"] == "accepted"
    assert decision["swsd_unit_id"] == "r1"
    assert decision["left_boundary_id"] == "101"
    assert decision["right_boundary_id"] == "102"
    assert decision["inferred_lane_width_m"] == pytest.approx(3.5)
    assert decision["width_sample_coverage"] == pytest.approx(1.0)


def test_narrow_width_is_review_evidence_not_automatic_rejection(tmp_path: Path) -> None:
    state, reasons = classify_width(
        {
            "bilateral_coverage": 1.0,
            "width_median_m": 2.1,
            "width_variation_m": 0.2,
        },
        config=_config(tmp_path),
    )

    assert state == "narrow_candidate"
    assert reasons == ["width_narrow_candidate"]
