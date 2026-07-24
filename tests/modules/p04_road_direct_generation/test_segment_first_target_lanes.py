from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_evidence import (
    _full_rcsd_patch_anchor_support,
    _target_lane_centers,
)


def test_target_lane_center_preserves_lane_geometry_and_lineage() -> None:
    lanes = gpd.GeoDataFrame(
        [
            {
                "Id": 101,
                "RoadId": 201,
                "Width": 3.5,
                "IsLeftmost": False,
                "source_patch_id": "patch-1",
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
        crs="EPSG:32650",
    )

    result = _target_lane_centers(lanes, "lane-run")

    assert result.iloc[0]["patch_road_key"] == "patch-1:lane:101"
    assert result.iloc[0]["center_lane_id"] == "101"
    assert result.iloc[0]["centerline_method"] == "lane_centerline_direct_evidence"
    assert result.iloc[0]["median_lane_width_m"] == 3.5
    assert result.iloc[0].geometry.equals(lanes.iloc[0].geometry)


def test_full_rcsd_id_anchors_target_to_patch_geometry_without_copying_it() -> None:
    centers = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "patch-1:road-1",
                "geometry": LineString([(0, 1), (20, 1)]),
            },
            {
                "patch_road_key": "patch-1:road-2",
                "geometry": LineString([(0, 8), (20, 8)]),
            },
        ],
        crs="EPSG:32650",
    )
    full_rcsd = gpd.GeoDataFrame(
        [{"id": 301, "geometry": LineString([(5, 0), (15, 0)])}],
        crs=centers.crs,
    )
    targets = gpd.GeoDataFrame(
        [
            {
                "segment_id": "segment-1",
                "target_required": True,
                "t06_rcsd_road_ids": "301",
                "geometry": LineString([(0, 0), (20, 0)]),
            }
        ],
        crs=centers.crs,
    )

    result = _full_rcsd_patch_anchor_support(
        centers,
        full_rcsd,
        targets,
        max_distance_m=8.0,
        max_angle_deg=35.0,
    )

    assert result == {("segment-1", "patch-1:road-1"): ("301",)}
