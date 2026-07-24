from __future__ import annotations

import geopandas as gpd
from shapely.geometry import Point, box

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_swsd_junction_audit import (
    build_swsd_junction_structure_audit,
)


def test_junction_structure_summarizes_endpoints_through_and_movements() -> None:
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "topology_mode": "ordinary_semantic",
                "geometry": box(-1, -1, 1, 1),
            }
        ],
        crs="EPSG:32650",
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "segment_id": "a",
                "access_type": "ENDPOINT",
                "geometry": Point(0, 0),
            },
            {
                "junction_group_id": "100",
                "segment_id": "b",
                "access_type": "THROUGH",
                "geometry": Point(0, 0),
            },
        ],
        crs=junctions.crs,
    )
    direction = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "expected_inbound": True,
                "expected_outbound": True,
                "topology_preserved": True,
                "geometry": Point(0, 0),
            },
            {
                "junction_group_id": "100",
                "expected_inbound": True,
                "expected_outbound": False,
                "topology_preserved": True,
                "geometry": Point(0, 0),
            },
        ],
        crs=junctions.crs,
    )
    movement = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "expected_movement_count": 3,
                "actual_movement_count": 3,
                "movement_topology_preserved": True,
                "geometry": Point(0, 0),
            }
        ],
        crs=junctions.crs,
    )

    result = build_swsd_junction_structure_audit(
        junctions,
        accesses,
        direction,
        movement,
        run_id="run",
    )

    row = result.iloc[0]
    assert row["segment_count"] == 2
    assert row["endpoint_access_count"] == 1
    assert row["through_access_count"] == 1
    assert row["expected_inbound_count"] == 2
    assert row["expected_outbound_count"] == 1
    assert row["expected_movement_count"] == 3
    assert row["junction_structure_class"] == "ordinary_with_through"
    assert bool(row["complete_topology_contract"])
