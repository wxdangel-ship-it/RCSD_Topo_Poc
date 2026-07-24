from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.io import (
    write_gpkg_layers,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_quality import (
    run_independent_quality,
)


def test_quality_canonicalizes_ids_after_gpkg_numeric_roundtrip(tmp_path) -> None:
    crs = "EPSG:32650"
    first_id = "7000000000000001"
    second_id = "7000000000000002"
    roads = gpd.GeoDataFrame(
        [
            {
                "id": first_id,
                "snodeid": "1",
                "enodeid": "2",
                "segment_id": "s1",
                "direction": 2,
                "realization": "built",
                "geometry_source": "hp_observed",
                "carrier_role": "main_forward",
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "id": second_id,
                "snodeid": "2",
                "enodeid": "3",
                "segment_id": "s1",
                "direction": 2,
                "realization": "built",
                "geometry_source": "hp_observed",
                "carrier_role": "main_forward",
                "geometry": LineString([(10, 0), (20, 0)]),
            },
        ],
        crs=crs,
    )
    nodes = gpd.GeoDataFrame(
        [
            {
                "id": node_id,
                "mainnodeid": node_id,
                "junction_group_ids": "",
                "junction_kind": "",
                "geometry": Point(x, 0),
            }
            for node_id, x in ((1, 0), (2, 10), (3, 20))
        ],
        crs=crs,
    )
    road_next_road = gpd.GeoDataFrame(
        [
            {
                "Id": 7100000000000001,
                "RoadId": int(first_id),
                "NextRoadId": int(second_id),
                "source_node_id": "2",
                "target_node_id": "2",
                "shared_node_id": "2",
                "junction_group_id": "",
                "mainnodeid": 2,
                "compile_source": "actual_shared_node",
                "geometry": Point(10, 0),
            }
        ],
        crs=crs,
    )
    plans = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "geometry": LineString([(0, 0), (20, 0)]),
            }
        ],
        crs=crs,
    )
    spans = gpd.GeoDataFrame(
        [
            {
                "road_id": int(road_id),
                "start_fraction": 0.0,
                "end_fraction": 1.0,
                "geometry": Point(x, 0),
            }
            for road_id, x in ((first_id, 5), (second_id, 15))
        ],
        crs=crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "s1:endpoint:0",
                "access_realized": True,
                "geometry": Point(0, 0),
            }
        ],
        crs=crs,
    )
    swsd_topology = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "junction_group_id": "100",
                "topology_preserved": True,
                "geometry": Point(0, 0),
            }
        ],
        crs=crs,
    )
    junction_movements = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "movement_topology_preserved": True,
                "geometry": Point(0, 0),
            }
        ],
        crs=crs,
    )
    formal = tmp_path / "formal.gpkg"
    audit = tmp_path / "audit.gpkg"
    write_gpkg_layers(
        formal,
        {
            "Road": roads,
            "Node": nodes,
            "RoadNextRoad": road_next_road,
        },
    )
    write_gpkg_layers(
        audit,
        {
            "segment_build_units": plans,
            "road_geometry_sources": spans,
            "segment_access_realization": accesses,
            "swsd_topology_contract": swsd_topology,
            "swsd_junction_movement_contract": (
                junction_movements
            ),
        },
    )

    result = run_independent_quality(
        formal,
        audit,
        tmp_path,
        expected_crs=crs,
        expected_segment_count=1,
        run_id="quality-id-roundtrip",
    )

    assert result.gate_pass
    assert result.payload["counts"]["violation"] == 0
