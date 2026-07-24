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
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_pipeline import (
    _has_junction_carrier_path,
    _same_segment_rejected_mask,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_topology import (
    compile_road_next_road,
)


def _config() -> SegmentFirstConfig:
    return SegmentFirstConfig(
        **{
            name: Path(name)
            for name in (
                "patch_root",
                "swsd_road_path",
                "swsd_node_path",
                "t01_road_path",
                "t01_node_path",
                "t01_segment_path",
                "t07_surface_path",
                "t03_surface_path",
                "t04_surface_path",
                "full_rcsd_road_path",
                "full_rcsd_node_path",
                "output_dir",
            )
        },
        run_id="run",
    )


def _segment_roads() -> gpd.GeoDataFrame:
    common = {
        "direction": 2,
        "realization": "built",
        "length": 9.0,
        "source_snodeid": "",
        "source_enodeid": "",
        "source_patch_ids": "p",
        "patch_road_key": "",
        "source_patch_road_keys": "",
        "start_patch_road_keys": "",
        "end_patch_road_keys": "",
        "carrier_role": "main_oneway",
        "geometry_source": "hp_observed",
        "snodeid": 0,
        "enodeid": 0,
    }
    return gpd.GeoDataFrame(
        [
            {
                **common,
                "id": 1,
                "segment_id": "s1",
                "geometry": LineString([(-10, 0), (-4, 0)]),
            },
            {
                **common,
                "id": 2,
                "segment_id": "s2",
                "geometry": LineString([(4, 0), (10, 0)]),
            },
        ],
        crs="EPSG:32650",
    )


def _junctions() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "j",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "surface:j",
                "geometry": box(-5, -2, 5, 2),
            }
        ],
        crs="EPSG:32650",
    )


def _empty_points(*columns: str) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {**{column: pd.Series(dtype=object) for column in columns}, "geometry": []},
        geometry="geometry",
        crs="EPSG:32650",
    )


def test_ordinary_junction_uses_semantic_connectivity_without_star_roads() -> None:
    roads = _segment_roads()
    junctions = _junctions()
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-20, -5, 20, 5)}], crs="EPSG:32650"
    )
    t01_nodes = _empty_points("id", "mainnodeid")
    accesses = _empty_points(
        "segment_id",
        "junction_group_id",
        "source_node_id",
        "access_type",
        "access_ordinal",
        "access_id",
    )

    carriers = materialize_ordinary_junction_carriers(
        roads,
        junctions,
        accesses,
        drivezones,
        t01_nodes,
        config=_config(),
    )
    assert carriers.materialized_group_ids == frozenset({"j"})
    assert carriers.roads.empty
    nodes = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        drivezones,
        t01_nodes,
        _empty_points("id", "mainnodeid"),
        config=_config(),
        materialized_ordinary_group_ids=set(carriers.materialized_group_ids),
    )
    segment_only = nodes.roads
    assert float(nodes.endpoint_audit["endpoint_shift_m"].max()) <= 1e-6
    assert segment_only.iloc[0].geometry.coords[-1] == (-4.0, 0.0)
    assert segment_only.iloc[1].geometry.coords[0] == (4.0, 0.0)

    topology = compile_road_next_road(
        nodes.roads,
        nodes.nodes,
        pd.DataFrame(),
        run_id="run",
    )
    adjacency: dict[object, set[object]] = {}
    for row in topology.road_next_road.itertuples():
        adjacency.setdefault(row.RoadId, set()).add(row.NextRoadId)
    assert (1, 2) in set(
        zip(
            topology.road_next_road["RoadId"],
            topology.road_next_road["NextRoadId"],
        )
    )
    assert set(topology.road_next_road["compile_source"]) == {
        "ordinary_junction_semantic"
    }


def test_lane_topo_forces_portals_for_roads_wholly_inside_junction() -> None:
    roads = _segment_roads()
    roads.at[0, "geometry"] = LineString([(-9, 0), (-4, 0)])
    roads.at[1, "geometry"] = LineString([(4, 0), (9, 0)])
    roads.at[0, "patch_road_key"] = "patch:source"
    roads.at[0, "source_patch_road_keys"] = "patch:source"
    roads.at[0, "start_patch_road_keys"] = "patch:source"
    roads.at[0, "end_patch_road_keys"] = "patch:source"
    roads.at[1, "patch_road_key"] = "patch:target"
    roads.at[1, "source_patch_road_keys"] = "patch:target"
    roads.at[1, "start_patch_road_keys"] = "patch:target"
    roads.at[1, "end_patch_road_keys"] = "patch:target"
    junctions = _junctions()
    junctions.at[0, "geometry"] = box(-10, -2, 10, 2)
    pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "source_relation_id": "lane-topo:1",
                "pair_source": "lane_topo",
            }
        ]
    )

    carriers = materialize_ordinary_junction_carriers(
        roads,
        junctions,
        _empty_points(
            "segment_id",
            "junction_group_id",
            "source_node_id",
            "access_type",
            "access_ordinal",
            "access_id",
        ),
        gpd.GeoDataFrame(
            [{"geometry": box(-10, -2, 10, 2)}], crs=roads.crs
        ),
        _empty_points("id", "mainnodeid"),
        config=_config(),
        explicit_pairs=pairs,
    )

    assert carriers.materialized_group_ids == frozenset({"j"})
    assert carriers.roads.empty
    assert {
        value
        for value in carriers.audit["carrier_evidence_ids"]
        if value
    } == {"lane-topo:1"}


def test_only_same_segment_rejected_relation_requests_segment_fallback() -> None:
    rejected = gpd.GeoDataFrame(
        [
            {
                "source_patch_road_key": "a",
                "target_patch_road_key": "b",
                "geometry": Point(0, 0),
            },
            {
                "source_patch_road_key": "a",
                "target_patch_road_key": "c",
                "geometry": Point(1, 0),
            },
        ],
        crs="EPSG:32650",
    )
    assignments = gpd.GeoDataFrame(
        [
            {"patch_road_key": "a", "assigned_segment_id": "s1", "geometry": Point()},
            {"patch_road_key": "b", "assigned_segment_id": "s1", "geometry": Point()},
            {"patch_road_key": "c", "assigned_segment_id": "s2", "geometry": Point()},
        ],
        crs="EPSG:32650",
    )
    assert list(_same_segment_rejected_mask(rejected, assignments)) == [True, False]


def test_surface_gap_between_supported_portals_does_not_create_fallback() -> None:
    roads = _segment_roads()
    junctions = _junctions()
    junctions.at[0, "geometry"] = box(-5, -1, -3, 1).union(
        box(3, -1, 5, 1)
    )
    result = materialize_ordinary_junction_carriers(
        roads,
        junctions,
        _empty_points(
            "segment_id",
            "junction_group_id",
            "source_node_id",
            "access_type",
            "access_ordinal",
            "access_id",
        ),
        gpd.GeoDataFrame(
            {"geometry": gpd.GeoSeries([], crs="EPSG:32650")},
            geometry="geometry",
            crs="EPSG:32650",
        ),
        _empty_points("id", "mainnodeid"),
        config=_config(),
    )
    assert result.summary["rejected_portal_count"] == 0
    assert result.fallback_segment_ids == frozenset()
    assert result.roads.empty


def test_junction_spoke_accepts_union_of_surface_and_drivezone_support() -> None:
    roads = _segment_roads()
    junctions = _junctions()
    junctions.at[0, "geometry"] = box(-1, -2, 1, 2)
    accesses = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "junction_group_id": "j",
                "source_node_id": "",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "access_id": "s1:endpoint",
                "geometry": Point(-4, 0),
            },
            {
                "segment_id": "s2",
                "junction_group_id": "j",
                "source_node_id": "",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "access_id": "s2:endpoint",
                "geometry": Point(4, 0),
            },
        ],
        crs=roads.crs,
    )
    drivezones = gpd.GeoDataFrame(
        [
            {"geometry": box(-5, -2, -2, 2)},
            {"geometry": box(2, -2, 5, 2)},
        ],
        crs=roads.crs,
    )

    result = materialize_ordinary_junction_carriers(
        roads,
        junctions,
        accesses,
        drivezones,
        _empty_points("id", "mainnodeid"),
        config=_config(),
        semantic_endpoint_segment_ids={"s1", "s2"},
    )

    assert result.fallback_segment_ids == frozenset()
    assert result.roads.empty
    assert set(result.audit["reason_codes"]) == {
        "drivezone_supported_portal"
    }
    assert bool((result.audit["support_coverage"] >= 0.9).all())


def test_concave_support_does_not_route_distributed_portals_to_center() -> None:
    roads = _segment_roads()
    junctions = _junctions()
    junctions.at[0, "geometry"] = box(-1, 4, 1, 6)
    accesses = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "junction_group_id": "j",
                "source_node_id": "",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "access_id": "s1:endpoint",
                "geometry": Point(-4, 0),
            },
            {
                "segment_id": "s2",
                "junction_group_id": "j",
                "source_node_id": "",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "access_id": "s2:endpoint",
                "geometry": Point(4, 0),
            },
        ],
        crs=roads.crs,
    )
    drivezones = gpd.GeoDataFrame(
        [
            {"geometry": box(-5, -1, -4, 5)},
            {"geometry": box(4, -1, 5, 5)},
            {"geometry": box(-5, 4, 5, 5)},
        ],
        crs=roads.crs,
    )

    result = materialize_ordinary_junction_carriers(
        roads,
        junctions,
        accesses,
        drivezones,
        _empty_points("id", "mainnodeid"),
        config=_config(),
        semantic_endpoint_segment_ids={"s1", "s2"},
    )

    assert result.fallback_segment_ids == frozenset()
    assert result.roads.empty
    assert set(result.audit["routing_state"]) == {"distributed_portal"}
    assert bool((result.audit["support_coverage"] >= 0.9).all())


def test_t07_junction_does_not_materialize_full_rcsd_weak_star_carrier() -> None:
    roads = _segment_roads()
    junctions = _junctions()
    junctions.at[0, "geometry"] = box(-0.5, -0.5, 0.5, 0.5)
    accesses = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "junction_group_id": "j",
                "source_node_id": "",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "access_id": "s1:endpoint",
                "geometry": Point(-4, 0),
            },
            {
                "segment_id": "s2",
                "junction_group_id": "j",
                "source_node_id": "",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "access_id": "s2:endpoint",
                "geometry": Point(4, 0),
            },
        ],
        crs=roads.crs,
    )
    full_rcsd = gpd.GeoDataFrame(
        [
            {
                "id": "full-left",
                "geometry": LineString([(-4, 0), (-4, 8), (0, 8), (0, 0)]),
            },
            {
                "id": "full-right",
                "geometry": LineString([(4, 0), (4, -8), (0, -8), (0, 0)]),
            },
        ],
        crs=roads.crs,
    )
    drivezones = gpd.GeoDataFrame(
        [{"geometry": geometry.buffer(0.1)} for geometry in full_rcsd.geometry],
        crs=roads.crs,
    )

    result = materialize_ordinary_junction_carriers(
        roads,
        junctions,
        accesses,
        drivezones,
        _empty_points("id", "mainnodeid"),
        config=_config(),
        semantic_endpoint_segment_ids={"s1", "s2"},
        full_rcsd_roads=full_rcsd,
    )

    assert result.fallback_segment_ids == frozenset()
    assert result.roads.empty
    assert set(result.audit["routing_state"]) == {"distributed_portal"}
    assert set(result.audit["reason_codes"]) == {
        "drivezone_supported_portal"
    }
    assert not bool(result.audit["review_required"].any())


def test_junction_carriers_use_the_same_semantic_endpoint_context_as_nodes() -> None:
    roads = _segment_roads()
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "j-wrong",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 3,
                "source_object_id": "surface:j-wrong",
                "geometry": box(-5, -2, 5, 2),
            },
            {
                "junction_group_id": "j-expected",
                "junction_source": "t03_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "surface:j-expected",
                "geometry": box(-5, -2, 5, 2),
            },
        ],
        crs=roads.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "junction_group_id": "j-expected",
                "source_node_id": "",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "access_id": "s1:endpoint",
                "geometry": Point(-4, 0),
            }
        ],
        crs=roads.crs,
    )
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-20, -5, 20, 5)}], crs=roads.crs
    )
    t01_nodes = _empty_points("id", "mainnodeid")

    stale = materialize_ordinary_junction_carriers(
        roads,
        junctions,
        accesses,
        drivezones,
        t01_nodes,
        config=_config(),
    )
    synchronized = materialize_ordinary_junction_carriers(
        roads,
        junctions,
        accesses,
        drivezones,
        t01_nodes,
        config=_config(),
        semantic_endpoint_segment_ids={"s1"},
    )

    assert stale.roads.empty
    assert "j-wrong" in set(stale.audit["junction_group_id"])
    assert synchronized.roads.empty
    assert "j-expected" in set(synchronized.audit["junction_group_id"])
