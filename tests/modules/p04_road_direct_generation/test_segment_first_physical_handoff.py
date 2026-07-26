from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_config import (
    SegmentFirstConfig,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_nodes import (
    NodeBuildResult,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_physical_handoff import (
    normalize_segment_main_handoffs,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_topology import (
    compile_road_next_road,
)


def test_retained_group_near_straight_handoff_becomes_exact_shared_node() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "snodeid": 10,
                "enodeid": 20,
                "direction": 2,
                "segment_id": "segment",
                "owner_type": "SEGMENT",
                "carrier_role": "main_oneway",
                "realization": "built",
                "width": 3.5,
                "length": 10.0,
                "base_geometry_length_m": 10.0,
                "assembly_state": "observed",
                "smoothing_state": "",
                "geometry": LineString([(0.0, 0.0), (10.0, 0.0)]),
            },
            {
                "id": 2,
                "snodeid": 30,
                "enodeid": 40,
                "direction": 2,
                "segment_id": "segment",
                "owner_type": "SEGMENT",
                "carrier_role": "semantic_carrier",
                "realization": "retained",
                "width": 3.5,
                "length": 10.0,
                "base_geometry_length_m": 10.0,
                "assembly_state": "retained",
                "smoothing_state": "",
                "geometry": LineString([(12.0, 0.0), (22.0, 0.0)]),
            },
        ],
        crs="EPSG:32650",
    )
    nodes = gpd.GeoDataFrame(
        [
            _node(10, 10, "", Point(0.0, 0.0)),
            _node(20, 100, "retained", Point(10.0, 0.0)),
            _node(30, 100, "retained", Point(12.0, 0.0)),
            _node(40, 40, "", Point(22.0, 0.0)),
        ],
        crs=roads.crs,
    )
    endpoint_audit = gpd.GeoDataFrame(
        [
            _endpoint(1, "start", 10, Point(0.0, 0.0)),
            _endpoint(1, "end", 20, Point(10.0, 0.0)),
            _endpoint(2, "start", 30, Point(12.0, 0.0)),
            _endpoint(2, "end", 40, Point(22.0, 0.0)),
        ],
        crs=roads.crs,
    )
    evidence = gpd.GeoDataFrame(
        {
            "source_road_id": pd.Series(dtype=object),
            "target_road_id": pd.Series(dtype=object),
            "connection_decision": pd.Series(dtype=str),
            "geometry": gpd.GeoSeries([], crs=roads.crs),
        },
        geometry="geometry",
        crs=roads.crs,
    )
    result = normalize_segment_main_handoffs(
        NodeBuildResult(
            roads,
            nodes,
            endpoint_audit,
            gpd.GeoDataFrame(
                {"geometry": gpd.GeoSeries([], crs=roads.crs)},
                geometry="geometry",
                crs=roads.crs,
            ),
            evidence,
            {},
        ),
        config=_config(),
    )

    target = result.roads[result.roads["id"].eq(2)].iloc[0]
    assert int(target["snodeid"]) == 20
    assert Point(target.geometry.coords[0]).equals(Point(10.0, 0.0))
    assert "30" not in set(result.nodes["id"].astype(str))
    assert result.summary["physical_handoff_normalized_count"] == 1

    topology = compile_road_next_road(
        result.roads,
        result.nodes,
        explicit_pairs=None,
        run_id="run",
    )
    relation = topology.road_next_road.iloc[0]
    assert (relation["RoadId"], relation["NextRoadId"]) == (1, 2)
    assert relation["compile_source"] == "actual_shared_node"


def test_ordinary_semantic_relation_excludes_automatic_uturn() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "snodeid": 1,
                "enodeid": 10,
                "direction": 2,
                "geometry": LineString([(-10.0, 0.0), (-1.0, 0.0)]),
            },
            {
                "id": 2,
                "snodeid": 20,
                "enodeid": 2,
                "direction": 2,
                "geometry": LineString([(1.0, 0.0), (10.0, 0.0)]),
            },
            {
                "id": 3,
                "snodeid": 30,
                "enodeid": 3,
                "direction": 2,
                "geometry": LineString([(-1.0, 1.0), (-10.0, 1.0)]),
            },
        ],
        crs="EPSG:32650",
    )
    nodes = gpd.GeoDataFrame(
        [
            _node(10, 100, "ordinary", Point(-1.0, 0.0)),
            _node(20, 100, "ordinary", Point(1.0, 0.0)),
            _node(30, 100, "ordinary", Point(-1.0, 1.0)),
        ],
        crs=roads.crs,
    )

    topology = compile_road_next_road(
        roads,
        nodes,
        explicit_pairs=None,
        run_id="run",
    )
    pairs = set(
        zip(
            topology.road_next_road["RoadId"],
            topology.road_next_road["NextRoadId"],
        )
    )
    assert (1, 2) in pairs
    assert (1, 3) not in pairs


def test_retained_semantic_relation_requires_explicit_lane_topo() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "snodeid": 1,
                "enodeid": 10,
                "direction": 2,
                "source_patch_ids": "patch",
                "source_lane_ids": "lane-a",
                "geometry": LineString([(-10.0, 0.0), (-1.0, 0.0)]),
            },
            {
                "id": 2,
                "snodeid": 20,
                "enodeid": 2,
                "direction": 2,
                "start_patch_road_keys": "patch:road-b",
                "geometry": LineString([(1.0, 0.0), (10.0, 0.0)]),
            },
        ],
        crs="EPSG:32650",
    )
    nodes = gpd.GeoDataFrame(
        [
            _node(10, 100, "retained", Point(-1.0, 0.0)),
            _node(20, 100, "retained", Point(1.0, 0.0)),
        ],
        crs=roads.crs,
    )
    unsupported = compile_road_next_road(
        roads,
        nodes,
        explicit_pairs=None,
        run_id="run",
    )
    assert unsupported.road_next_road.empty

    supported = compile_road_next_road(
        roads,
        nodes,
        explicit_pairs=pd.DataFrame(
                [
                    {
                        "source_patch_road_key": "patch:road-x",
                        "target_patch_road_key": "patch:road-b",
                        "source_relation_id": "lane-topo-1",
                    },
                    {
                        "source_patch_road_key": "patch:lane:lane-a",
                        "target_patch_road_key": "patch:lane:lane-b",
                        "source_relation_id": "lane-topo-1",
                    }
                ]
        ),
        run_id="run",
    )
    assert len(supported.road_next_road) == 1
    relation = supported.road_next_road.iloc[0]
    assert (relation["RoadId"], relation["NextRoadId"]) == (1, 2)
    assert (
        relation["compile_source"]
        == "explicit_lane_topo_retained_semantic"
    )


def test_advance_right_explicit_relation_may_bridge_lineage_groups() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "snodeid": 1,
                "enodeid": 10,
                "direction": 2,
                "segment_id": "advance_right_example",
                "end_patch_road_keys": "patch:road-a",
                "geometry": LineString([(-10.0, 0.0), (-1.0, 0.0)]),
            },
            {
                "id": 2,
                "snodeid": 20,
                "enodeid": 2,
                "direction": 2,
                "segment_id": "main-segment",
                "start_patch_road_keys": "patch:road-b",
                "geometry": LineString([(5.0, 4.0), (10.0, 4.0)]),
            },
        ],
        crs="EPSG:32650",
    )
    nodes = gpd.GeoDataFrame(
        [
            _node(10, 100, "retained", Point(-1.0, 0.0)),
            _node(20, 200, "ordinary", Point(5.0, 4.0)),
        ],
        crs=roads.crs,
    )
    topology = compile_road_next_road(
        roads,
        nodes,
        explicit_pairs=pd.DataFrame(
            [
                {
                    "source_patch_road_key": "patch:road-a",
                    "target_patch_road_key": "patch:road-b",
                }
            ]
        ),
        run_id="run",
    )
    assert len(topology.road_next_road) == 1
    relation = topology.road_next_road.iloc[0]
    assert (relation["RoadId"], relation["NextRoadId"]) == (1, 2)
    assert (
        relation["compile_source"]
        == "explicit_lane_topo_advance_right_semantic"
    )


def _node(
    node_id: int,
    mainnodeid: int,
    kind: str,
    geometry: Point,
) -> dict[str, object]:
    return {
        "id": node_id,
        "mainnodeid": mainnodeid,
        "junction_group_ids": str(mainnodeid) if kind else "",
        "junction_kind": kind,
        "geometry": geometry,
    }


def _endpoint(
    road_id: int,
    endpoint: str,
    node_id: int,
    geometry: Point,
) -> dict[str, object]:
    return {
        "road_id": road_id,
        "endpoint": endpoint,
        "node_id": node_id,
        "endpoint_shift_m": 0.0,
        "connection_state": "unchanged",
        "reason_codes": "",
        "geometry": geometry,
    }


def _config() -> SegmentFirstConfig:
    path = Path("unused")
    return SegmentFirstConfig(
        patch_root=path,
        swsd_road_path=path,
        swsd_node_path=path,
        t01_road_path=path,
        t01_node_path=path,
        t01_segment_path=path,
        t07_surface_path=path,
        t03_surface_path=path,
        t04_surface_path=path,
        full_rcsd_road_path=path,
        full_rcsd_node_path=path,
        output_dir=Path("output"),
        run_id="run",
    )
