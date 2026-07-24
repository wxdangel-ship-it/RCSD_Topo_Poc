from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_config import (
    SegmentFirstConfig,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_junction_carriers import (
    materialize_ordinary_junction_carriers,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_nodes import (
    build_nodes_and_connect_roads,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_topology import (
    compile_road_next_road,
)


def _config() -> SegmentFirstConfig:
    paths = [Path(f"input-{index}") for index in range(11)]
    return SegmentFirstConfig(
        patch_root=paths[0],
        swsd_road_path=paths[1],
        swsd_node_path=paths[2],
        t01_road_path=paths[3],
        t01_node_path=paths[4],
        t01_segment_path=paths[5],
        t07_surface_path=paths[6],
        t03_surface_path=paths[7],
        t04_surface_path=paths[8],
        full_rcsd_road_path=paths[9],
        full_rcsd_node_path=paths[10],
        output_dir=Path("output"),
        run_id="run",
        endpoint_snap_distance_m=0.5,
    )


def _roads() -> gpd.GeoDataFrame:
    common = {
        "direction": 2,
        "realization": "built",
        "owner_type": "SEGMENT",
        "junction_group_id": "",
        "source_snodeid": "",
        "source_enodeid": "",
        "source_patch_ids": "patch",
        "source_patch_road_keys": "",
        "start_patch_road_keys": "",
        "end_patch_road_keys": "",
        "carrier_role": "main_oneway",
        "geometry_source": "hp_observed",
        "snodeid": 0,
        "enodeid": 0,
    }
    rows = [
        {
            **common,
            "id": 1,
            "segment_id": "west-in",
            "geometry": LineString([(-10.0, 0.0), (-4.0, 0.0)]),
        },
        {
            **common,
            "id": 2,
            "segment_id": "east-out",
            "geometry": LineString([(4.0, 0.0), (10.0, 0.0)]),
        },
        {
            **common,
            "id": 3,
            "segment_id": "south-in",
            "geometry": LineString([(0.0, -10.0), (0.0, -4.0)]),
        },
        {
            **common,
            "id": 4,
            "segment_id": "north-out",
            "geometry": LineString([(0.0, 4.0), (0.0, 10.0)]),
        },
    ]
    for row in rows:
        row["length"] = row["geometry"].length
    return gpd.GeoDataFrame(rows, crs="EPSG:32650")


def _junction(kind: str = "ordinary") -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": (
                    "t04_accepted" if kind == "complex_divmerge" else "t07_accepted"
                ),
                "junction_kind": kind,
                "source_priority": 3 if kind == "complex_divmerge" else 2,
                "source_object_id": "junction-100",
                "geometry": box(-5.0, -5.0, 5.0, 5.0),
            }
        ],
        crs="EPSG:32650",
    )


def _empty_points(*columns: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            **{column: pd.Series(dtype=object) for column in columns},
            "geometry": gpd.GeoSeries([], crs="EPSG:32650"),
        },
        geometry="geometry",
        crs="EPSG:32650",
    )


def test_ordinary_junction_keeps_distributed_portals_without_star_roads() -> None:
    roads = _roads()
    junctions = _junction()
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-20.0, -20.0, 20.0, 20.0)}],
        crs=roads.crs,
    )
    accesses = _empty_points(
        "segment_id",
        "junction_group_id",
        "source_node_id",
        "access_type",
        "access_ordinal",
        "access_id",
    )
    t01_nodes = _empty_points("id", "mainnodeid")

    realization = materialize_ordinary_junction_carriers(
        roads,
        junctions,
        accesses,
        drivezones,
        t01_nodes,
        config=_config(),
    )

    assert realization.materialized_group_ids == frozenset({"100"})
    assert realization.roads.empty
    assert realization.summary["junction_carrier_road_count"] == 0
    assert realization.summary["accepted_portal_count"] == 4

    connected = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        drivezones,
        t01_nodes,
        _empty_points("id", "mainnodeid"),
        config=_config(),
        materialized_ordinary_group_ids=set(realization.materialized_group_ids),
    )

    portal_nodes = connected.nodes[
        connected.nodes["junction_group_ids"].eq("100")
    ]
    assert len(portal_nodes) == 4
    assert portal_nodes["id"].nunique() == 4
    assert portal_nodes["mainnodeid"].nunique() == 1
    assert set(
        (round(point.x, 3), round(point.y, 3))
        for point in portal_nodes.geometry
    ) == {
        (-4.0, 0.0),
        (4.0, 0.0),
        (0.0, -4.0),
        (0.0, 4.0),
    }
    assert not connected.roads["owner_type"].eq("JUNCTION_UNIT").any()

    topology = compile_road_next_road(
        connected.roads,
        connected.nodes,
        pd.DataFrame(),
        run_id="run",
    )
    semantic = topology.road_next_road[
        topology.road_next_road["compile_source"].eq(
            "ordinary_junction_semantic"
        )
    ]
    assert set(zip(semantic["RoadId"], semantic["NextRoadId"])) == {
        (1, 2),
        (1, 4),
        (3, 2),
        (3, 4),
    }
    assert semantic["shared_node_id"].fillna("").eq("").all()
    assert semantic["junction_group_id"].eq("100").all()
    assert semantic["source_node_id"].astype(str).ne(
        semantic["target_node_id"].astype(str)
    ).all()


def test_complex_junction_does_not_use_mainnode_semantic_full_connect() -> None:
    roads = _roads()
    nodes = gpd.GeoDataFrame(
        [
            {
                "id": 10,
                "mainnodeid": 100,
                "junction_group_ids": "100",
                "junction_kind": "complex_divmerge",
                "geometry": Point(-4.0, 0.0),
            },
            {
                "id": 20,
                "mainnodeid": 100,
                "junction_group_ids": "100",
                "junction_kind": "complex_divmerge",
                "geometry": Point(4.0, 0.0),
            },
            {
                "id": 30,
                "mainnodeid": 100,
                "junction_group_ids": "100",
                "junction_kind": "complex_divmerge",
                "geometry": Point(0.0, -4.0),
            },
            {
                "id": 40,
                "mainnodeid": 100,
                "junction_group_ids": "100",
                "junction_kind": "complex_divmerge",
                "geometry": Point(0.0, 4.0),
            },
        ],
        crs=roads.crs,
    )
    roads.loc[:, "snodeid"] = [90, 20, 91, 40]
    roads.loc[:, "enodeid"] = [10, 92, 30, 93]

    topology = compile_road_next_road(
        roads,
        nodes,
        pd.DataFrame(),
        run_id="run",
    )

    assert topology.road_next_road.empty


def test_actual_shared_node_remains_valid_inside_segment_chain() -> None:
    roads = _roads().iloc[:2].copy()
    roads.loc[roads["id"].eq(1), "enodeid"] = 20
    roads.loc[roads["id"].eq(2), "snodeid"] = 20
    nodes = gpd.GeoDataFrame(
        [
            {
                "id": 20,
                "mainnodeid": 20,
                "junction_group_ids": "",
                "junction_kind": "",
                "geometry": Point(0.0, 0.0),
            }
        ],
        crs=roads.crs,
    )

    topology = compile_road_next_road(
        roads,
        nodes,
        pd.DataFrame(),
        run_id="run",
    )

    relation = topology.road_next_road.iloc[0]
    assert (relation["RoadId"], relation["NextRoadId"]) == (1, 2)
    assert relation["compile_source"] == "actual_shared_node"
    assert str(relation["shared_node_id"]) == "20"
