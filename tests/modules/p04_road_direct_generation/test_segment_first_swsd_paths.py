from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_swsd_paths import (
    build_swsd_segment_directional_paths,
)


CRS = "EPSG:32650"


def test_resolves_two_oneway_member_paths_through_mainnode_groups() -> None:
    nodes = gpd.GeoDataFrame(
        [
            {"id": 11, "mainnodeid": 100, "geometry": Point(0, 0)},
            {"id": 12, "mainnodeid": 100, "geometry": Point(0, 1)},
            {"id": 21, "mainnodeid": 200, "geometry": Point(10, 0)},
            {"id": 22, "mainnodeid": 200, "geometry": Point(10, 1)},
            {"id": 300, "mainnodeid": None, "geometry": Point(5, 0)},
            {"id": 400, "mainnodeid": None, "geometry": Point(5, 1)},
        ],
        geometry="geometry",
        crs=CRS,
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "snodeid": 11,
                "enodeid": 300,
                "direction": 2,
                "geometry": LineString([(0, 0), (5, 0)]),
            },
            {
                "id": 2,
                "snodeid": 300,
                "enodeid": 21,
                "direction": 2,
                "geometry": LineString([(5, 0), (10, 0)]),
            },
            {
                "id": 3,
                "snodeid": 22,
                "enodeid": 400,
                "direction": 2,
                "geometry": LineString([(10, 1), (5, 1)]),
            },
            {
                "id": 4,
                "snodeid": 400,
                "enodeid": 12,
                "direction": 2,
                "geometry": LineString([(5, 1), (0, 1)]),
            },
        ],
        geometry="geometry",
        crs=CRS,
    )
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "100_200",
                "target_required": True,
                "target_class": "core_trunk",
                "sgrade": "0-0双",
                "swsd_road_ids": "1,2,3,4",
                "geometry": LineString([(0, 0.5), (10, 0.5)]),
            }
        ],
        geometry="geometry",
        crs=CRS,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "segment_id": "100_200",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "junction_group_id": 100,
                "geometry": Point(0, 0.5),
            },
            {
                "segment_id": "100_200",
                "access_type": "ENDPOINT",
                "access_ordinal": 1,
                "junction_group_id": 200,
                "geometry": Point(10, 0.5),
            },
        ],
        geometry="geometry",
        crs=CRS,
    )

    result = build_swsd_segment_directional_paths(
        segments,
        roads,
        nodes,
        accesses,
        run_id="paths",
    )

    assert result.summary["resolved_dual_core_segment_count"] == 1
    assert result.summary["unresolved_dual_core_segment_count"] == 0
    assert result.member_roles == {
        ("100_200", "1", "forward"): "main_forward",
        ("100_200", "2", "forward"): "main_forward",
        ("100_200", "3", "forward"): "main_reverse",
        ("100_200", "4", "forward"): "main_reverse",
    }
    assert set(result.audit["path_role"]) == {"main_forward", "main_reverse"}
    assert set(result.audit["path_state"]) == {"unique"}


def test_does_not_assign_roles_when_swsd_path_is_ambiguous() -> None:
    nodes = gpd.GeoDataFrame(
        [
            {"id": 100, "mainnodeid": None, "geometry": Point(0, 0)},
            {"id": 200, "mainnodeid": None, "geometry": Point(10, 0)},
        ],
        geometry="geometry",
        crs=CRS,
    )
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "snodeid": 100,
                "enodeid": 200,
                "direction": 1,
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "id": 2,
                "snodeid": 100,
                "enodeid": 200,
                "direction": 1,
                "geometry": LineString([(0, 1), (10, 1)]),
            },
        ],
        geometry="geometry",
        crs=CRS,
    )
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "100_200",
                "target_required": True,
                "target_class": "core_trunk",
                "sgrade": "0-0双",
                "swsd_road_ids": "1,2",
                "geometry": LineString([(0, 0.5), (10, 0.5)]),
            }
        ],
        geometry="geometry",
        crs=CRS,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "segment_id": "100_200",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "junction_group_id": 100,
                "geometry": Point(0, 0),
            },
            {
                "segment_id": "100_200",
                "access_type": "ENDPOINT",
                "access_ordinal": 1,
                "junction_group_id": 200,
                "geometry": Point(10, 0),
            },
        ],
        geometry="geometry",
        crs=CRS,
    )

    result = build_swsd_segment_directional_paths(
        segments,
        roads,
        nodes,
        accesses,
        run_id="ambiguous",
    )

    assert result.member_roles == {}
    assert result.summary["resolved_dual_core_segment_count"] == 0
    assert result.summary["ambiguous_direction_count"] == 2
    assert set(result.audit["path_state"]) == {"ambiguous"}
