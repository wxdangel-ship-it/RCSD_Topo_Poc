from __future__ import annotations

from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.skeleton import build_swsd_skeleton


def test_skeleton_keeps_internal_overlap_and_external_open_boundary() -> None:
    crs = "EPSG:32650"
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "snodeid": 10,
                "enodeid": 11,
                "direction": 2,
                "patch_id": "p1,p2",
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "id": 2,
                "snodeid": 11,
                "enodeid": 12,
                "direction": 1,
                "patch_id": "p1,p3",
                "geometry": LineString([(10, 0), (20, 0)]),
            },
        ],
        crs=crs,
    )
    nodes = gpd.GeoDataFrame(
        [
            {"id": 10, "mainnodeid": None, "kind_2": 4, "grade_2": 1, "geometry": Point(0, 0)},
            {"id": 11, "mainnodeid": None, "kind_2": 4, "grade_2": 1, "geometry": Point(10, 0)},
            {"id": 12, "mainnodeid": None, "kind_2": 4, "grade_2": 1, "geometry": Point(20, 0)},
        ],
        crs=crs,
    )

    result = build_swsd_skeleton(roads, nodes, patch_ids={"p1", "p2"}, run_id="synthetic")

    assert result.summary["road_count"] == 2
    assert result.summary["internal_overlap_road_count"] == 1
    assert result.summary["open_boundary_road_count"] == 1
    assert result.summary["junction_count"] == 3
    assert result.summary["arm_count"] == 4
