from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_junction_topology import (
    materialize_swsd_junction_movement_contract,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_topology import (
    TopologyBuildResult,
)


CRS = "EPSG:32650"


def test_ordinary_junction_requires_complete_directional_cross_product():
    result = materialize_swsd_junction_movement_contract(
        _segments(),
        _swsd_roads(),
        _swsd_nodes(),
        _junction_units("ordinary_semantic"),
        _accesses(),
        _published_roads(),
        _published_nodes("ordinary"),
        TopologyBuildResult(
            _road_next_road(
                [
                    {
                        "RoadId": 101,
                        "NextRoadId": 201,
                        "source_node_id": 100,
                        "target_node_id": 200,
                        "shared_node_id": "",
                        "junction_group_id": "10",
                        "mainnodeid": 10,
                        "compile_source": (
                            "ordinary_junction_semantic"
                        ),
                    }
                ]
            ),
            {"road_next_road_count": 1},
        ),
        run_id="ordinary",
        maximum_surface_distance_m=10.0,
    )

    assert result.summary["gate_pass"] is True
    assert result.summary["expected_movement_count"] == 1
    assert result.summary["actual_movement_count"] == 1
    assert result.summary["explicit_swsd_movement_count"] == 0


def test_complex_junction_materializes_only_exact_swsd_shared_node_movement():
    result = materialize_swsd_junction_movement_contract(
        _segments(),
        _swsd_roads(),
        _swsd_nodes(),
        _junction_units("explicit_physical"),
        _accesses(),
        _published_roads(),
        _published_nodes("complex_divmerge"),
        TopologyBuildResult(
            _road_next_road([]),
            {"road_next_road_count": 0},
        ),
        run_id="complex",
        maximum_surface_distance_m=10.0,
    )

    assert result.summary["gate_pass"] is True
    assert result.summary["explicit_swsd_movement_count"] == 1
    assert len(result.topology.road_next_road) == 1
    relation = result.topology.road_next_road.iloc[0]
    assert relation["RoadId"] == 101
    assert relation["NextRoadId"] == 201
    assert (
        relation["compile_source"]
        == "complex_junction_swsd_explicit"
    )
    assert relation["shared_node_id"] == ""


def test_complex_junction_refuses_portal_outside_accepted_surface():
    nodes = _published_nodes("complex_divmerge")
    nodes.loc[nodes["id"] == 200, "geometry"] = Point(100, 0)
    result = materialize_swsd_junction_movement_contract(
        _segments(),
        _swsd_roads(),
        _swsd_nodes(),
        _junction_units("explicit_physical"),
        _accesses(),
        _published_roads(),
        nodes,
        TopologyBuildResult(
            _road_next_road([]),
            {"road_next_road_count": 0},
        ),
        run_id="complex-fail",
        maximum_surface_distance_m=10.0,
    )

    assert result.summary["gate_pass"] is False
    assert result.summary["failed_junction_count"] == 1
    assert result.summary["explicit_swsd_movement_count"] == 0
    assert "swsd_junction_movement_missing" in str(
        result.audit.iloc[0]["reason_codes"]
    )


def test_complex_junction_materializes_lane_topo_local_connector_exit():
    roads = _published_roads()
    roads = gpd.GeoDataFrame(
        [
            {
                **roads.iloc[0].to_dict(),
                "enodeid": 110,
                "geometry": LineString([(-20, 0), (-5, 0)]),
            },
            {
                "id": 102,
                "segment_id": "A",
                "member_swsd_road_id": "",
                "carrier_role": "local_connector",
                "realization": "built",
                "snodeid": 110,
                "enodeid": 100,
                "direction": 2,
                "geometry": LineString([(-5, 0), (-2, 0)]),
            },
            roads.iloc[1].to_dict(),
        ],
        geometry="geometry",
        crs=CRS,
    )
    nodes = _published_nodes("complex_divmerge")
    nodes = gpd.GeoDataFrame(
        [
            *nodes.to_dict("records"),
            {
                "id": 110,
                "mainnodeid": 110,
                "junction_group_ids": "",
                "junction_kind": "",
                "geometry": Point(-5, 0),
            },
        ],
        geometry="geometry",
        crs=CRS,
    )
    swsd_roads = _swsd_roads()
    swsd_roads.loc[swsd_roads["id"] == 2, "snodeid"] = 20
    result = materialize_swsd_junction_movement_contract(
        _segments(),
        swsd_roads,
        _swsd_nodes(),
        _junction_units("explicit_physical"),
        _accesses(),
        roads,
        nodes,
        TopologyBuildResult(
            _road_next_road(
                [
                    {
                        "RoadId": 101,
                        "NextRoadId": 102,
                        "source_node_id": 110,
                        "target_node_id": 110,
                        "shared_node_id": 110,
                        "junction_group_id": "",
                        "mainnodeid": 110,
                        "compile_source": "actual_shared_node",
                    }
                ]
            ),
            {"road_next_road_count": 1},
        ),
        run_id="complex-lane-topo",
        maximum_surface_distance_m=10.0,
        connection_evidence=gpd.GeoDataFrame(
            [
                {
                    "source_relation_id": "lane-topo-1",
                    "pair_source": "lane_topo",
                    "source_road_id": 101,
                    "target_road_id": 201,
                    "connection_decision": "accepted",
                    "geometry": Point(-3, 0),
                }
            ],
            geometry="geometry",
            crs=CRS,
        ),
    )

    lane_relation = result.topology.road_next_road[
        result.topology.road_next_road["compile_source"].eq(
            "complex_junction_lane_topo_explicit"
        )
    ].iloc[0]
    assert result.summary["gate_pass"] is True
    assert result.summary["explicit_lane_topo_movement_count"] == 1
    assert lane_relation["RoadId"] == 102
    assert lane_relation["NextRoadId"] == 201
    assert lane_relation["junction_group_id"] == "10"
    assert lane_relation["source_relation_ids"] == "lane-topo-1"


def _segments() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "segment_id": "A",
                "swsd_road_ids": "1",
                "geometry": LineString([(-20, 0), (0, 0)]),
            },
            {
                "segment_id": "B",
                "swsd_road_ids": "2",
                "geometry": LineString([(0, 0), (20, 0)]),
            },
        ],
        geometry="geometry",
        crs=CRS,
    )


def _swsd_roads() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "snodeid": 1,
                "enodeid": 10,
                "direction": 2,
                "geometry": LineString([(-20, 0), (0, 0)]),
            },
            {
                "id": 2,
                "snodeid": 10,
                "enodeid": 2,
                "direction": 2,
                "geometry": LineString([(0, 0), (20, 0)]),
            },
        ],
        geometry="geometry",
        crs=CRS,
    )


def _swsd_nodes() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "id": 10,
                "mainnodeid": 10,
                "geometry": Point(0, 0),
            }
        ],
        geometry="geometry",
        crs=CRS,
    )


def _junction_units(mode: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "10",
                "topology_mode": mode,
                "source_priority": 3,
                "geometry": box(-10, -10, 10, 10),
            }
        ],
        geometry="geometry",
        crs=CRS,
    )


def _accesses() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "segment_id": "A",
                "junction_group_id": "10",
                "geometry": Point(-2, 0),
            },
            {
                "segment_id": "B",
                "junction_group_id": "10",
                "geometry": Point(2, 0),
            },
        ],
        geometry="geometry",
        crs=CRS,
    )


def _published_roads() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "id": 101,
                "segment_id": "A",
                "member_swsd_road_id": "1",
                "carrier_role": "main_oneway",
                "realization": "built",
                "snodeid": 1,
                "enodeid": 100,
                "direction": 2,
                "geometry": LineString([(-20, 0), (-2, 0)]),
            },
            {
                "id": 201,
                "segment_id": "B",
                "member_swsd_road_id": "2",
                "carrier_role": "semantic_carrier",
                "realization": "retained",
                "snodeid": 200,
                "enodeid": 2,
                "direction": 2,
                "geometry": LineString([(2, 0), (20, 0)]),
            },
        ],
        geometry="geometry",
        crs=CRS,
    )


def _published_nodes(kind: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "mainnodeid": 1,
                "junction_group_ids": "",
                "junction_kind": "",
                "geometry": Point(-20, 0),
            },
            {
                "id": 100,
                "mainnodeid": 10,
                "junction_group_ids": "10",
                "junction_kind": kind,
                "geometry": Point(-2, 0),
            },
            {
                "id": 200,
                "mainnodeid": 10,
                "junction_group_ids": "10",
                "junction_kind": kind,
                "geometry": Point(2, 0),
            },
            {
                "id": 2,
                "mainnodeid": 2,
                "junction_group_ids": "",
                "junction_kind": "",
                "geometry": Point(20, 0),
            },
        ],
        geometry="geometry",
        crs=CRS,
    )


def _road_next_road(
    rows: list[dict[str, object]],
) -> gpd.GeoDataFrame:
    records = []
    for index, row in enumerate(rows, start=1):
        records.append(
            {
                "run_id": "test",
                "Id": index,
                "TurnType": 0,
                "Length": 0,
                "TrafficLightControl": 0,
                "MultiTurnType": 0,
                **row,
                "geometry": Point(0, 0),
            }
        )
    if not records:
        return gpd.GeoDataFrame(
            {
                "run_id": [],
                "Id": [],
                "RoadId": [],
                "NextRoadId": [],
                "source_node_id": [],
                "target_node_id": [],
                "shared_node_id": [],
                "junction_group_id": [],
                "mainnodeid": [],
                "compile_source": [],
                "geometry": gpd.GeoSeries([], crs=CRS),
            },
            geometry="geometry",
            crs=CRS,
        )
    return gpd.GeoDataFrame(
        records,
        geometry="geometry",
        crs=CRS,
    )
