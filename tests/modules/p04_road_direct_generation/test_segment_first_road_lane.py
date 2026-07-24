from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_road_lane import (
    build_road_lane_relation,
)


def test_patch_lane_group_candidate_only_matches_same_direction_road() -> None:
    relations = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "patch:road",
                "road_id": "patch-road",
                "lane_id": "lane-forward",
                "geometry": LineString([(0, 1), (20, 1)]),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "source_patch_road_keys": "patch:road",
                "source_lane_ids": "",
                "geometry": LineString([(0, 0), (20, 0)]),
            },
            {
                "id": 2,
                "source_patch_road_keys": "patch:road",
                "source_lane_ids": "",
                "geometry": LineString([(20, 2), (0, 2)]),
            },
        ],
        crs=relations.crs,
    )

    result = build_road_lane_relation(relations, roads)

    assert list(result["road_id"]) == [1]
    assert list(result["relation_basis"]) == [
        "patch_lane_group_directional_fit"
    ]


def test_lane_can_relate_to_adjacent_fine_road_parts() -> None:
    relations = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "patch:road",
                "road_id": "patch-road",
                "lane_id": "lane",
                "geometry": LineString([(0, 1), (20, 1)]),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "source_patch_road_keys": "patch:road",
                "source_lane_ids": "lane",
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "id": 2,
                "source_patch_road_keys": "patch:road",
                "source_lane_ids": "lane",
                "geometry": LineString([(10, 0), (20, 0)]),
            },
        ],
        crs=relations.crs,
    )

    result = build_road_lane_relation(relations, roads)

    assert set(result["road_id"]) == {1, 2}
    assert set(result["lane_id"]) == {"lane"}
    assert set(result["relation_basis"]) == {"direct_lane_lineage"}


def test_distant_lane_is_not_attached_by_lineage_alone() -> None:
    relations = gpd.GeoDataFrame(
        [
            {
                "patch_road_key": "patch:road",
                "road_id": "patch-road",
                "lane_id": "lane",
                "geometry": LineString([(0, 50), (20, 50)]),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "source_patch_road_keys": "patch:road",
                "source_lane_ids": "lane",
                "geometry": LineString([(0, 0), (20, 0)]),
            }
        ],
        crs=relations.crs,
    )

    result = build_road_lane_relation(relations, roads)

    assert result.empty
