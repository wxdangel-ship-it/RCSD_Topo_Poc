from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.directional_topology import (
    build_directional_topology,
)


def test_directional_portals_and_arms_close_to_each_road_endpoint() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "directional_road_id": "r1:forward",
                "parent_swsd_unit_id": "r1",
                "travel_side": "forward",
                "direction": 2,
                "semantic_snode_id": "j1",
                "semantic_enode_id": "j2",
                "geometry": LineString([(0, 3), (100, 3)]),
            },
            {
                "directional_road_id": "r1:reverse",
                "parent_swsd_unit_id": "r1",
                "travel_side": "reverse",
                "direction": 2,
                "semantic_snode_id": "j2",
                "semantic_enode_id": "j1",
                "geometry": LineString([(100, -3), (0, -3)]),
            },
        ],
        crs="EPSG:32650",
    )

    result = build_directional_topology(roads, run_id="topology-test")

    assert len(result.portals) == 4
    assert len(result.arms) == 4
    assert result.summary["road_portal_max_delta_m"] == 0.0
    assert result.summary["road_arm_max_delta_m"] == 0.0
    assert result.summary["reverse_single_direction_encoding_count"] == 1
    assert result.summary["road_topology_gate_pass"]
    assert "cross_road closure is gated by directional_movement" in result.summary[
        "gate_scope"
    ]
