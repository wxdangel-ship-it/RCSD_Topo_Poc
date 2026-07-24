from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point, box

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_config import (
    SegmentFirstConfig,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_nodes import (
    _connect_endpoint,
    _max_sample_turn,
    _road_endpoints,
    build_nodes_and_connect_roads,
    resolve_road_endpoint_junctions,
)


def _config(*, relation_distance: float = 20.0) -> SegmentFirstConfig:
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
        relation_endpoint_max_distance_m=relation_distance,
    )


def _roads(*, realization: str, start: tuple[float, float]) -> gpd.GeoDataFrame:
    line = LineString([start, (10.0, 0.0)])
    return gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "segment_id": "segment-1",
                "segment_type": "advance_right",
                "patch_road_key": "patch:1" if realization == "built" else "",
                "carrier_role": "main_oneway",
                "realization": realization,
                "source_snodeid": 10 if realization == "retained" else "",
                "source_enodeid": 20 if realization == "retained" else "",
                "snodeid": 10,
                "enodeid": 20,
                "length": line.length,
                "geometry": line,
            }
        ],
        crs="EPSG:32650",
    )


def _junctions() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "999",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "wrong-overlap",
                "geometry": box(-0.25, -0.25, 0.25, 0.25),
            },
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "expected",
                "geometry": box(-1.0, -1.0, 0.0, 1.0),
            },
        ],
        crs="EPSG:32650",
    )


def _accesses() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "access_id": "access-1",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "source_node_id": "10",
                "junction_group_id": "100",
                "geometry": Point(0.0, 0.0),
            }
        ],
        crs="EPSG:32650",
    )


def _empty_points() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"id": pd.Series(dtype="int64"), "geometry": gpd.GeoSeries([], crs="EPSG:32650")},
        geometry="geometry",
        crs="EPSG:32650",
    )


def _build(roads: gpd.GeoDataFrame, *, relation_distance: float = 20.0):
    return build_nodes_and_connect_roads(
        roads,
        _junctions(),
        _accesses(),
        pd.DataFrame(),
        gpd.GeoDataFrame(geometry=[], crs="EPSG:32650"),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=relation_distance),
    )


def test_retained_access_lineage_overrides_overlapping_surface() -> None:
    result = _build(_roads(realization="retained", start=(0.0, 0.0)))
    start_id = int(result.roads.iloc[0]["snodeid"])
    node = result.nodes[result.nodes["id"] == start_id].iloc[0]
    audit = result.endpoint_audit[result.endpoint_audit["endpoint"] == "start"].iloc[0]
    assert node["junction_group_ids"] == "100"
    assert int(node["mainnodeid"]) == 100
    assert audit["junction_membership_source"] == "t01_segment_access_lineage"
    assert result.summary["retained_lineage_override_count"] == 1


def test_junction_group_nodes_inherit_t01_mainnode_lineage() -> None:
    t01_nodes = gpd.GeoDataFrame(
        [
            {
                "id": 100,
                "mainnodeid": 999,
                "geometry": Point(0.0, 0.0),
            }
        ],
        crs="EPSG:32650",
    )
    result = build_nodes_and_connect_roads(
        _roads(realization="built", start=(1.5, 0.0)),
        _junctions(),
        _accesses(),
        pd.DataFrame(),
        gpd.GeoDataFrame(geometry=[], crs="EPSG:32650"),
        t01_nodes,
        _empty_points(),
        config=_config(),
    )

    grouped = result.nodes[result.nodes["junction_group_ids"].eq("100")]
    assert not grouped.empty
    assert set(grouped["mainnodeid"].astype(int)) == {999}


def test_built_access_handoff_uses_segment_surface_within_relation_limit() -> None:
    result = _build(_roads(realization="built", start=(1.5, 0.0)))
    start_id = int(result.roads.iloc[0]["snodeid"])
    node = result.nodes[result.nodes["id"] == start_id].iloc[0]
    audit = result.endpoint_audit[result.endpoint_audit["endpoint"] == "start"].iloc[0]
    assert node["junction_group_ids"] == "100"
    assert int(node["mainnodeid"]) == 100
    assert audit["junction_membership_source"] == "segment_access_surface_handoff"
    assert result.summary["built_access_handoff_count"] == 1


def test_built_endpoint_access_lineage_overrides_wrong_overlapping_surface() -> None:
    result = _build(_roads(realization="built", start=(0.0, 0.0)))
    start_id = int(result.roads.iloc[0]["snodeid"])
    node = result.nodes[result.nodes["id"] == start_id].iloc[0]
    audit = result.endpoint_audit[result.endpoint_audit["endpoint"] == "start"].iloc[0]
    assert node["junction_group_ids"] == "100"
    assert int(node["mainnodeid"]) == 100
    assert audit["junction_membership_source"] == (
        "segment_endpoint_access_lineage_override"
    )


def test_declared_through_split_keeps_shared_node_in_expected_junction() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "segment_id": "segment-1",
                "segment_type": "normal",
                "patch_road_key": "patch:1",
                "carrier_role": "main_forward",
                "carrier_id": "main:part:0",
                "realization": "built",
                "end_junction_group_ids": "200",
                "snodeid": 0,
                "enodeid": 0,
                "length": 10.0,
                "geometry": LineString([(0.0, 0.0), (10.0, 0.0)]),
            },
            {
                "id": 2,
                "segment_id": "segment-1",
                "segment_type": "normal",
                "patch_road_key": "patch:2",
                "carrier_role": "main_forward",
                "carrier_id": "main:part:1",
                "realization": "built",
                "start_junction_group_ids": "200",
                "snodeid": 0,
                "enodeid": 0,
                "length": 10.0,
                "geometry": LineString([(10.0, 0.0), (20.0, 0.0)]),
            },
        ],
        crs="EPSG:32650",
    )
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "overlap",
                "geometry": box(9.0, -2.0, 11.0, 2.0),
            },
            {
                "junction_group_id": "200",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "declared-through",
                "geometry": box(9.0, -2.0, 11.0, 2.0),
            },
        ],
        crs=roads.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "through-200",
                "segment_id": "segment-1",
                "access_type": "THROUGH",
                "access_ordinal": 0,
                "source_node_id": "200",
                "junction_group_id": "200",
                "geometry": Point(10.0, 0.0),
            }
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        _empty_points(),
        _empty_points(),
        config=_config(),
    )

    first = result.roads[result.roads["id"] == 1].iloc[0]
    second = result.roads[result.roads["id"] == 2].iloc[0]
    assert int(first["enodeid"]) == int(second["snodeid"])
    node = result.nodes[
        result.nodes["id"].astype(int) == int(first["enodeid"])
    ].iloc[0]
    assert node["junction_group_ids"] == "200"
    assert int(node["mainnodeid"]) == 200


def test_single_declared_terminal_does_not_override_surface_membership() -> None:
    roads = _roads(realization="built", start=(0.0, 0.0)).copy()
    roads.loc[:, "carrier_id"] = "main:part:0"
    roads.loc[:, "start_junction_group_ids"] = "200"

    resolution = resolve_road_endpoint_junctions(
        roads,
        _junctions(),
        _accesses(),
        _empty_points(),
        config=_config(),
    )

    assert resolution.memberships[0]["junction_group_id"] != "200"
    assert (
        resolution.memberships[0]["junction_source"]
        != "carrier_split_access_lineage"
    )


def test_advance_right_endpoint_cannot_claim_a_distant_junction_surface() -> None:
    result = _build(
        _roads(realization="built", start=(25.0, 0.0)),
        relation_distance=5.0,
    )
    assert "100" not in set(result.nodes["junction_group_ids"].astype(str))
    assert result.summary["built_access_handoff_count"] == 0


def test_near_exact_swsd_retained_access_lineage_keeps_high_precision_portal() -> None:
    roads = _roads(realization="built", start=(4.0, 0.0)).copy()
    roads.loc[:, "source_snodeid"] = "10"
    roads.loc[:, "source_enodeid"] = "20"
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "swsd_retained",
                "junction_kind": "retained",
                "source_priority": 0,
                "source_object_id": "100",
                "geometry": box(-1.0, -1.0, 1.0, 1.0),
            }
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        _accesses(),
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(3.0, -1.0, 11.0, 1.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=5.0),
    )

    start = result.endpoint_audit[
        result.endpoint_audit["endpoint"].eq("start")
    ].iloc[0]
    assert start["junction_group_id"] == "100"
    assert start["junction_membership_source"] == (
        "swsd_retained_exact_segment_access_lineage"
    )
    assert result.summary["built_access_handoff_count"] == 1


def test_distant_advance_right_cannot_claim_exact_swsd_access_lineage() -> None:
    roads = _roads(realization="built", start=(25.0, 0.0)).copy()
    roads.loc[:, "source_snodeid"] = "10"
    roads.loc[:, "source_enodeid"] = "20"
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "swsd_retained",
                "junction_kind": "retained",
                "source_priority": 0,
                "source_object_id": "100",
                "geometry": box(-1.0, -1.0, 1.0, 1.0),
            }
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        _accesses(),
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(9.0, -1.0, 26.0, 1.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=5.0),
    )

    start = result.endpoint_audit[
        result.endpoint_audit["endpoint"].eq("start")
    ].iloc[0]
    assert start["junction_group_id"] == ""
    assert start["junction_membership_source"] == ""
    assert result.summary["built_access_handoff_count"] == 0


def test_swsd_retained_lineage_cannot_hide_unsupported_built_portal() -> None:
    roads = _roads(realization="built", start=(25.0, 0.0)).copy()
    roads.loc[:, "source_snodeid"] = "10"
    roads.loc[:, "source_enodeid"] = "20"
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "swsd_retained",
                "junction_kind": "retained",
                "source_priority": 0,
                "source_object_id": "100",
                "geometry": Point(0.0, 0.0),
            }
        ],
        crs=roads.crs,
    )
    unrelated_drivezone = gpd.GeoDataFrame(
        [{"geometry": box(-2.0, -2.0, 2.0, 2.0)}],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        _accesses(),
        pd.DataFrame(),
        unrelated_drivezone,
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=30.0),
    )

    start = result.endpoint_audit[
        result.endpoint_audit["endpoint"].eq("start")
    ].iloc[0]
    assert start["junction_group_id"] == ""
    assert start["junction_membership_source"] == ""
    assert result.summary["built_access_handoff_count"] == 0


def test_normal_segment_endpoint_keeps_physical_surface_distance_gate() -> None:
    roads = _roads(realization="built", start=(25.0, 0.0)).copy()
    roads.loc[:, "segment_type"] = "normal"
    result = _build(roads, relation_distance=5.0)
    assert "100" not in set(result.nodes["junction_group_ids"].astype(str))
    assert result.summary["built_access_handoff_count"] == 0


def test_core_target_endpoint_cannot_bypass_junction_surface_distance() -> None:
    roads = _roads(realization="built", start=(25.0, 0.0)).copy()
    roads.loc[:, "segment_type"] = "normal"
    roads.loc[:, "target_class"] = "core_trunk"
    result = build_nodes_and_connect_roads(
        roads,
        _junctions(),
        _accesses(),
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(-2.0, -2.0, 6.0, 2.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=5.0),
        semantic_endpoint_segment_ids={"segment-1"},
    )
    assert "100" not in set(result.nodes["junction_group_ids"].astype(str))
    assert result.summary["built_access_handoff_count"] == 0


def test_core_target_endpoint_uses_drivezone_constrained_surface_completion() -> None:
    roads = _roads(realization="built", start=(5.0, 0.0)).copy()
    roads.loc[:, "segment_type"] = "normal"
    roads.loc[:, "target_class"] = "core_trunk"
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-2.0, -2.0, 11.0, 2.0)}],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        _junctions(),
        _accesses(),
        pd.DataFrame(),
        drivezones,
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=10.0),
        semantic_endpoint_segment_ids={"segment-1"},
    )

    start = result.endpoint_audit[
        result.endpoint_audit["endpoint"].eq("start")
    ].iloc[0]
    assert start["junction_group_id"] == "100"
    assert start["junction_membership_source"] == (
        "segment_endpoint_surface_constrained_completion"
    )
    assert float(start["junction_surface_distance_m"]) == 0.0
    assert bool(start["junction_surface_strict_inside"])
    assert float(start["junction_surface_inset_m"]) > 0.0
    assert start["junction_interior_completion_source"] != ""
    assert float(result.roads.iloc[0].geometry.distance(_junctions().iloc[1].geometry)) == 0.0
    assert result.summary["constrained_completion_count"] == 1


def test_normal_built_endpoint_uses_drivezone_constrained_surface_completion() -> None:
    roads = _roads(realization="built", start=(5.0, 0.0)).copy()
    roads.loc[:, "segment_type"] = "normal"
    drivezones = gpd.GeoDataFrame(
        [{"geometry": box(-2.0, -2.0, 11.0, 2.0)}],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        _junctions(),
        _accesses(),
        pd.DataFrame(),
        drivezones,
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=10.0),
    )

    start = result.endpoint_audit[
        result.endpoint_audit["endpoint"].eq("start")
    ].iloc[0]
    assert start["junction_group_id"] == "100"
    assert start["junction_membership_source"] == (
        "segment_access_surface_constrained_completion"
    )
    assert float(start["junction_surface_distance_m"]) == 0.0
    assert result.summary["constrained_completion_count"] == 1


def test_access_completion_rejects_inward_backtracking_geometry() -> None:
    road = _built_road(
        1,
        "segment-1",
        "patch:1",
        [(5.0, 0.0), (20.0, 0.0)],
    )
    road["carrier_role"] = "main_oneway"
    roads = gpd.GeoDataFrame([road], crs="EPSG:32650")
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "inward-target",
                "geometry": box(9.0, -1.0, 11.0, 1.0),
            }
        ],
        crs=roads.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "through-1",
                "segment_id": "segment-1",
                "access_type": "THROUGH",
                "access_ordinal": 0,
                "source_node_id": "100",
                "junction_group_id": "100",
                "geometry": Point(10.0, 0.0),
            }
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(0.0, -2.0, 25.0, 2.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=10.0),
    )

    assert list(result.roads.iloc[0].geometry.coords) == [
        (5.0, 0.0),
        (20.0, 0.0),
    ]
    assert result.summary["built_access_handoff_count"] == 0
    assert result.summary["constrained_completion_count"] == 0


def test_through_access_does_not_pull_nearby_main_road_to_surface() -> None:
    first = _built_road(
        1,
        "segment-1",
        "patch:1",
        [(3.0, 0.0), (20.0, 0.0)],
    )
    second = _built_road(
        2,
        "segment-1",
        "patch:2",
        [(8.0, 1.0), (20.0, 1.0)],
    )
    first["carrier_role"] = "main_oneway"
    second["carrier_role"] = "main_oneway"
    roads = gpd.GeoDataFrame([first, second], crs="EPSG:32650")
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "through-target",
                "geometry": box(0.0, -2.0, 1.0, 2.0),
            }
        ],
        crs=roads.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "through-1",
                "segment_id": "segment-1",
                "access_type": "THROUGH",
                "access_ordinal": 0,
                "source_node_id": "100",
                "junction_group_id": "100",
                "geometry": Point(0.5, 0.0),
            }
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(-1.0, -3.0, 25.0, 3.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=10.0),
    )

    updated = result.roads.set_index("id")
    assert tuple(updated.loc[1].geometry.coords[0]) == (3.0, 0.0)
    assert tuple(updated.loc[2].geometry.coords[0]) == (8.0, 1.0)
    assert result.summary["built_access_handoff_count"] == 0
    assert result.summary["constrained_completion_count"] == 0


def test_through_access_uses_exact_source_node_lineage_for_surface_portal() -> None:
    road = _built_road(1, "segment-1", "patch:1", [(3.0, 0.0), (20.0, 0.0)])
    road["carrier_role"] = "main_oneway"
    road["source_snodeid"] = "100"
    roads = gpd.GeoDataFrame([road], crs="EPSG:32650")
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "through-target",
                "geometry": box(0.0, -2.0, 1.0, 2.0),
            }
        ],
        crs=roads.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "through-1",
                "segment_id": "segment-1",
                "access_type": "THROUGH",
                "access_ordinal": 0,
                "source_node_id": "100",
                "junction_group_id": "100",
                "geometry": Point(0.5, 0.0),
            }
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(-1.0, -3.0, 25.0, 3.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=10.0),
    )

    start = result.endpoint_audit[
        result.endpoint_audit["endpoint"].eq("start")
    ].iloc[0]
    assert start["junction_group_id"] == "100"
    assert bool(start["junction_surface_strict_inside"])
    assert tuple(result.roads.iloc[0].geometry.coords[0]) == (0.5, 0.0)


def test_normal_built_endpoint_cannot_use_attribute_only_surface_handoff() -> None:
    roads = _roads(realization="built", start=(5.0, 0.0)).copy()
    roads.loc[:, "segment_type"] = "normal"
    unrelated_drivezone = gpd.GeoDataFrame(
        [{"geometry": box(4.0, -1.0, 11.0, 1.0)}],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        _junctions(),
        _accesses(),
        pd.DataFrame(),
        unrelated_drivezone,
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=10.0),
    )

    assert "100" not in set(result.nodes["junction_group_ids"].astype(str))
    assert result.summary["built_access_handoff_count"] == 0


def test_semantic_endpoint_also_binds_nearby_access_support_road() -> None:
    roads = _roads(realization="built", start=(25.0, 0.0)).copy()
    roads.loc[:, "segment_type"] = "normal"
    roads.loc[:, "target_class"] = "core_trunk"
    support = roads.iloc[0].to_dict()
    support.update(
        {
            "id": 2,
            "carrier_role": "access_support",
            "patch_road_key": "patch:support",
            "geometry": LineString([(1.5, 0.0), (5.0, 0.0)]),
            "length": 3.5,
        }
    )
    roads = gpd.GeoDataFrame(
        pd.concat([roads, gpd.GeoDataFrame([support], crs=roads.crs)]),
        geometry="geometry",
        crs=roads.crs,
    ).reset_index(drop=True)

    result = build_nodes_and_connect_roads(
        roads,
        _junctions(),
        _accesses(),
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(-2.0, -2.0, 6.0, 2.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=5.0),
        semantic_endpoint_segment_ids={"segment-1"},
    )

    support_audit = result.endpoint_audit[result.endpoint_audit["road_id"].eq(2)]
    assert "100" in set(support_audit["junction_group_id"].astype(str))
    assert "segment_access_surface_constrained_completion" in set(
        support_audit["junction_membership_source"].astype(str)
    )
    assert result.summary["built_access_handoff_count"] == 1


def test_declared_access_support_completion_overrides_overlapping_surface() -> None:
    roads = _roads(realization="built", start=(0.0, 0.0)).copy()
    roads.loc[:, "segment_type"] = "normal"
    roads.loc[:, "carrier_role"] = "access_support"
    roads.loc[:, "constrained_completion_access_ids"] = "access-1"

    result = build_nodes_and_connect_roads(
        roads,
        _junctions(),
        _accesses(),
        pd.DataFrame(),
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=5.0),
    )

    start_audit = result.endpoint_audit[
        result.endpoint_audit["endpoint"].eq("start")
    ].iloc[0]
    assert start_audit["junction_group_id"] == "100"
    assert start_audit["junction_membership_source"] == (
        "segment_access_surface_constrained_completion"
    )


def test_declared_completion_keeps_other_access_support_handoff() -> None:
    roads = _roads(realization="built", start=(0.0, 0.0)).copy()
    roads.loc[:, "segment_type"] = "normal"
    roads.loc[:, "target_class"] = "core_trunk"
    roads.loc[:, "carrier_role"] = "access_support"
    roads.loc[:, "constrained_completion_access_ids"] = "through-1"
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "endpoint",
                "geometry": box(9.0, -1.0, 11.0, 1.0),
            },
            {
                "junction_group_id": "200",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "through",
                "geometry": box(-1.0, -1.0, 1.0, 1.0),
            },
        ],
        crs=roads.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "endpoint-1",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "source_node_id": "20",
                "junction_group_id": "100",
                "geometry": Point(10.0, 0.0),
            },
            {
                "access_id": "through-1",
                "segment_id": "segment-1",
                "access_type": "THROUGH",
                "access_ordinal": 1,
                "source_node_id": "30",
                "junction_group_id": "200",
                "geometry": Point(0.0, 0.0),
            },
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(-7.0, -2.0, 6.0, 2.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=5.0),
        semantic_endpoint_segment_ids={"segment-1"},
    )

    assert set(result.endpoint_audit["junction_group_id"].astype(str)) == {
        "100",
        "200",
    }


def test_exact_ordinary_retained_access_portal_compiles_shared_node() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "segment_id": "",
                "segment_type": "junction_internal",
                "target_class": "not_target",
                "patch_road_key": "",
                "carrier_role": "junction_surface_carrier",
                "realization": "built",
                "owner_type": "JUNCTION_UNIT",
                "junction_group_id": "100",
                "source_snodeid": "",
                "source_enodeid": "",
                "snodeid": 0,
                "enodeid": 0,
                "geometry": LineString([(0.0, 0.0), (-5.0, 0.0)]),
            },
            {
                "id": 2,
                "segment_id": "segment-1",
                "segment_type": "normal",
                "target_class": "core_trunk",
                "patch_road_key": "patch:support",
                "carrier_role": "access_support",
                "realization": "built",
                "owner_type": "SEGMENT",
                "junction_group_id": "",
                "access_support_access_ids": "through-1",
                "constrained_completion_access_ids": "",
                "source_snodeid": "",
                "source_enodeid": "",
                "snodeid": 0,
                "enodeid": 0,
                "geometry": LineString([(0.0, 0.0), (5.0, 0.0)]),
            },
        ],
        crs="EPSG:32650",
    )
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "ordinary",
                "geometry": box(-6.0, -1.0, -1.0, 1.0),
            },
            {
                "junction_group_id": "200",
                "junction_source": "swsd_retained",
                "junction_kind": "retained",
                "source_priority": 0,
                "source_object_id": "retained",
                "geometry": Point(2.0, 0.0),
            },
        ],
        crs=roads.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "endpoint-1",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "source_node_id": "10",
                "junction_group_id": "100",
                "geometry": Point(-2.0, 0.0),
            },
            {
                "access_id": "through-1",
                "segment_id": "segment-1",
                "access_type": "THROUGH",
                "access_ordinal": 1,
                "source_node_id": "20",
                "junction_group_id": "200",
                "geometry": Point(2.0, 0.0),
            },
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(-7.0, -2.0, 6.0, 2.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=5.0),
        semantic_endpoint_segment_ids={"segment-1"},
    )

    assert int(result.roads.iloc[0]["snodeid"]) == int(
        result.roads.iloc[1]["snodeid"]
    )
    shared = result.nodes[
        result.nodes["id"].eq(int(result.roads.iloc[0]["snodeid"]))
    ].iloc[0]
    assert shared["junction_group_ids"] == "100"
    assert int(shared["mainnodeid"]) == 100
    retained = result.nodes[
        result.nodes["id"].eq(int(result.roads.iloc[1]["enodeid"]))
    ].iloc[0]
    assert retained["junction_group_ids"] == "200"


def test_same_swsd_source_node_does_not_collapse_separate_built_portals() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                **_built_road(1, "segment-1", "patch:1", [(-2.0, 0.0), (8.0, 0.0)]),
                "segment_type": "normal",
                "target_class": "core_trunk",
                "carrier_role": "main_forward",
                "source_snodeid": "10",
            },
            {
                **_built_road(2, "segment-1", "patch:2", [(2.0, 0.0), (8.0, 2.0)]),
                "segment_type": "normal",
                "target_class": "core_trunk",
                "carrier_role": "main_reverse",
                "source_snodeid": "10",
            },
            {
                "id": 3,
                "segment_id": "retained-segment",
                "segment_type": "normal",
                "target_class": "not_target",
                "patch_road_key": "",
                "source_patch_road_keys": "",
                "carrier_role": "semantic_carrier",
                "carrier_id": "retained",
                "realization": "retained",
                "source_snodeid": "",
                "source_enodeid": "10",
                "snodeid": 30,
                "enodeid": 31,
                "length": LineString([(8.0, -2.0), (0.0, 0.0)]).length,
                "geometry": LineString([(8.0, -2.0), (0.0, 0.0)]),
            },
        ],
        crs="EPSG:32650",
    )
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "ordinary",
                "geometry": box(-3.0, -2.0, 3.0, 2.0),
            }
        ],
        crs=roads.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "endpoint-1",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "source_node_id": "10",
                "junction_group_id": "100",
                "geometry": Point(0.0, 0.0),
            }
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(-4.0, -3.0, 9.0, 3.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=10.0),
    )

    assert int(result.roads.iloc[0]["snodeid"]) != int(
        result.roads.iloc[1]["snodeid"]
    )
    assert len(
        {
            int(result.roads.iloc[0]["snodeid"]),
            int(result.roads.iloc[1]["snodeid"]),
            int(result.roads.iloc[2]["enodeid"]),
        }
    ) == 3
    assert {
        tuple(road.geometry.coords[0])
        for road in result.roads.iloc[:2].itertuples()
    } == {(-2.0, 0.0), (2.0, 0.0)}
    start_audit = result.endpoint_audit[
        result.endpoint_audit["endpoint"].eq("start")
        & result.endpoint_audit["road_id"].isin({1, 2})
    ]
    assert set(start_audit["junction_group_id"].astype(str)) == {"100"}


def test_nearby_ordinary_built_direction_portals_remain_separate() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                **_built_road(
                    1,
                    "segment-1",
                    "patch:forward",
                    [(-1.0, 0.0), (10.0, 0.0)],
                ),
                "segment_type": "normal",
                "target_class": "core_trunk",
                "carrier_role": "main_forward",
                "carrier_id": "forward",
            },
            {
                **_built_road(
                    2,
                    "segment-1",
                    "patch:reverse",
                    [(1.0, 0.0), (10.0, 2.0)],
                ),
                "segment_type": "normal",
                "target_class": "core_trunk",
                "carrier_role": "main_reverse",
                "carrier_id": "reverse",
            },
        ],
        crs="EPSG:32650",
    )
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "ordinary",
                "geometry": box(-2.0, -2.0, 2.0, 2.0),
            }
        ],
        crs=roads.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "endpoint-1",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "source_node_id": "100",
                "junction_group_id": "100",
                "geometry": Point(0.0, 0.0),
            }
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(-3.0, -3.0, 11.0, 3.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(),
    )

    assert int(result.roads.iloc[0]["snodeid"]) != int(
        result.roads.iloc[1]["snodeid"]
    )
    grouped = result.nodes[
        result.nodes["junction_group_ids"].eq("100")
    ]
    assert len(grouped) == 2
    assert set(grouped["mainnodeid"].astype(int)) == {100}


def test_colocated_bidirectional_segment_uses_surface_portals() -> None:
    forward = {
        **_built_road(
            1,
            "segment-1",
            "patch:forward",
            [(0.0, 0.0), (20.0, 2.0)],
        ),
        "segment_type": "normal",
        "target_class": "core_trunk",
        "carrier_role": "main_forward",
        "carrier_id": "forward",
        "source_snodeid": "10",
    }
    reverse = {
        **_built_road(
            2,
            "segment-1",
            "patch:reverse",
            [(20.0, -2.0), (0.0, 0.0)],
        ),
        "segment_type": "normal",
        "target_class": "core_trunk",
        "carrier_role": "main_reverse",
        "carrier_id": "reverse",
        "source_enodeid": "10",
    }
    roads = gpd.GeoDataFrame([forward, reverse], crs="EPSG:32650")
    surface = box(-3.0, -3.0, 3.0, 3.0)
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t03_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "ordinary",
                "geometry": surface,
            }
        ],
        crs=roads.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "endpoint-1",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "source_node_id": "10",
                "junction_group_id": "100",
                "geometry": Point(0.0, 0.0),
            }
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(-4.0, -4.0, 21.0, 4.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(),
    )

    forward_portal = Point(result.roads.iloc[0].geometry.coords[0])
    reverse_portal = Point(result.roads.iloc[1].geometry.coords[-1])
    assert surface.contains(forward_portal)
    assert surface.contains(reverse_portal)
    assert forward_portal.distance(surface.boundary) >= 1.0 - 1e-6
    assert reverse_portal.distance(surface.boundary) >= 1.0 - 1e-6
    assert forward_portal.distance(reverse_portal) > 0.1
    assert int(result.roads.iloc[0]["snodeid"]) != int(
        result.roads.iloc[1]["enodeid"]
    )
    grouped = result.nodes[
        result.nodes["junction_group_ids"].eq("100")
    ]
    assert len(grouped) == 2
    assert set(grouped["mainnodeid"].astype(int)) == {100}


def test_built_through_handoff_still_requires_physical_surface_proximity() -> None:
    accesses = _accesses().copy()
    accesses.loc[0, "access_type"] = "THROUGH"
    result = build_nodes_and_connect_roads(
        _roads(realization="built", start=(25.0, 0.0)),
        _junctions(),
        accesses,
        pd.DataFrame(),
        gpd.GeoDataFrame(geometry=[], crs="EPSG:32650"),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=5.0),
    )
    assert "100" not in set(result.nodes["junction_group_ids"].astype(str))
    assert result.summary["built_access_handoff_count"] == 0


def test_semantic_endpoint_rejects_all_distant_terminals_per_main_role() -> None:
    roads = gpd.GeoDataFrame(
        [
            {
                "id": 1,
                "segment_id": "segment-1",
                "segment_type": "advance_right",
                "patch_road_key": "patch:1",
                "carrier_role": "main_oneway",
                "realization": "built",
                "source_snodeid": "",
                "source_enodeid": "",
                "snodeid": 10,
                "enodeid": 11,
                "length": 10.0,
                "geometry": LineString([(25.0, 0.0), (35.0, 0.0)]),
            },
            {
                "id": 2,
                "segment_id": "segment-1",
                "segment_type": "advance_right",
                "patch_road_key": "patch:2",
                "carrier_role": "main_oneway",
                "realization": "built",
                "source_snodeid": "",
                "source_enodeid": "",
                "snodeid": 12,
                "enodeid": 13,
                "length": 10.0,
                "geometry": LineString([(100.0, 0.0), (110.0, 0.0)]),
            },
        ],
        crs="EPSG:32650",
    )
    result = build_nodes_and_connect_roads(
        roads,
        _junctions(),
        _accesses(),
        pd.DataFrame(),
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=5.0),
    )
    assert result.summary["built_access_handoff_count"] == 0
    assert sum(
        "100" in value
        for value in result.nodes["junction_group_ids"].astype(str)
    ) == 0


def test_semantic_endpoint_uses_distinct_terminals_for_two_accesses() -> None:
    roads = _roads(realization="built", start=(25.0, 0.0)).copy()
    roads.loc[0, "geometry"] = LineString([(0.0, 0.0), (100.0, 0.0)])
    roads.loc[0, "length"] = 100.0
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "start",
                "geometry": box(-1.0, -1.0, 0.0, 1.0),
            },
            {
                "junction_group_id": "200",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "end",
                "geometry": box(99.0, -1.0, 100.0, 1.0),
            },
        ],
        crs=roads.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "access-start",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "source_node_id": "10",
                "junction_group_id": "100",
                "geometry": Point(0.0, 0.0),
            },
            {
                "access_id": "access-end",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "access_ordinal": 1,
                "source_node_id": "20",
                "junction_group_id": "200",
                "geometry": Point(100.0, 0.0),
            },
        ],
        crs=roads.crs,
    )
    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=5.0),
    )
    groups = set(result.nodes["junction_group_ids"].astype(str))
    assert {"100", "200"}.issubset(groups)
    assert result.summary["built_access_handoff_count"] == 2
    required = result.endpoint_audit[
        result.endpoint_audit["junction_surface_required"]
        .fillna(False)
        .astype(bool)
    ]
    assert required["junction_surface_strict_inside"].astype(bool).all()


def test_semantic_endpoint_allows_smooth_road_surface_lateral_completion() -> None:
    roads = _roads(realization="built", start=(0.0, 0.0)).copy()
    roads.loc[0, "geometry"] = LineString([(0.0, 0.0), (0.0, -20.0)])
    roads.loc[0, "length"] = 20.0
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "lateral",
                "geometry": box(-3.0, -1.0, -1.0, 1.0),
            }
        ],
        crs=roads.crs,
    )
    accesses = gpd.GeoDataFrame(
        [
            {
                "access_id": "access-lateral",
                "segment_id": "segment-1",
                "access_type": "ENDPOINT",
                "access_ordinal": 0,
                "source_node_id": "10",
                "junction_group_id": "100",
                "geometry": Point(-2.0, 0.0),
            }
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        accesses,
        pd.DataFrame(),
        gpd.GeoDataFrame(
            [{"geometry": box(-4.0, -21.0, 2.0, 2.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(relation_distance=5.0),
        semantic_endpoint_segment_ids={"segment-1"},
    )

    start_audit = result.endpoint_audit[
        result.endpoint_audit["endpoint"].eq("start")
    ].iloc[0]
    assert start_audit["junction_group_id"] == "100"
    assert bool(start_audit["junction_surface_strict_inside"])
    assert start_audit["junction_interior_completion_source"] == (
        "segment_endpoint_surface_smooth_lateral_completion"
    )
    assert result.roads.iloc[0].geometry.is_simple


def test_duplicate_fragment_keys_select_nearest_directed_endpoint_pair() -> None:
    roads = gpd.GeoDataFrame(
        [
            _built_road(1, "s1", "patch:source", [(0.0, 0.0), (10.0, 0.0)]),
            _built_road(2, "s2", "patch:target", [(10.5, 0.0), (20.0, 0.0)]),
            _built_road(3, "s3", "patch:source", [(100.0, 0.0), (110.0, 0.0)]),
            _built_road(4, "s4", "patch:target", [(200.0, 0.0), (210.0, 0.0)]),
        ],
        crs="EPSG:32650",
    )
    pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "source_relation_id": "lane-topo-1",
                "pair_source": "lane_topo",
            }
        ]
    )

    result = build_nodes_and_connect_roads(
        roads,
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        pairs,
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        _empty_points(),
        _empty_points(),
        config=_config(),
    )

    connection = result.connection_evidence.iloc[0]
    assert connection["connection_decision"] == "accepted"
    assert connection["reason_codes"] == "endpoint_snap"
    assert connection["endpoint_distance_m"] == 0.5


def test_parallel_lane_topo_relations_reuse_already_connected_physical_node() -> None:
    roads = gpd.GeoDataFrame(
        [
            _built_road(1, "s1", "patch:source", [(0.0, 0.0), (10.0, 0.0)]),
            _built_road(2, "s1", "patch:target", [(20.0, 0.0), (30.0, 0.0)]),
        ],
        crs="EPSG:32650",
    )
    pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "source_relation_id": "lane-topo-1",
                "pair_source": "lane_topo",
            },
            {
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "source_relation_id": "lane-topo-2",
                "pair_source": "lane_topo",
            },
        ]
    )

    result = build_nodes_and_connect_roads(
        roads,
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        pairs,
        gpd.GeoDataFrame(
            [{"geometry": box(-1.0, -1.0, 31.0, 1.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(),
    )

    assert list(result.connection_evidence["connection_decision"]) == [
        "accepted",
        "accepted",
    ]
    assert (
        result.connection_evidence.iloc[1]["reason_codes"]
        == "already_connected_physical_component"
    )
    assert int(result.roads.iloc[0]["enodeid"]) == int(
        result.roads.iloc[1]["snodeid"]
    )


def test_proximity_snap_preserves_ordered_split_road_chain() -> None:
    roads = gpd.GeoDataFrame(
        [
            _built_road(1, "s1", "patch:1", [(0.0, 0.0), (10.0, 0.0)]),
            _built_road(2, "s1", "patch:2", [(10.0, 0.0), (12.2, 0.0)]),
            _built_road(3, "s1", "patch:3", [(12.2, 0.0), (20.0, 0.0)]),
        ],
        crs="EPSG:32650",
    )

    result = build_nodes_and_connect_roads(
        roads,
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        pd.DataFrame(),
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        _empty_points(),
        _empty_points(),
        config=_config(),
    )

    by_id = result.roads.set_index("id")
    assert int(by_id.loc[1, "enodeid"]) == int(by_id.loc[2, "snodeid"])
    assert int(by_id.loc[2, "enodeid"]) == int(by_id.loc[3, "snodeid"])
    assert int(by_id.loc[2, "snodeid"]) != int(by_id.loc[3, "snodeid"])
    assert len(result.nodes) == 4


def test_cross_segment_lane_topo_does_not_collapse_separate_portals() -> None:
    roads = gpd.GeoDataFrame(
        [
            _built_road(1, "s1", "patch:source", [(0.0, 0.0), (10.0, 0.0)]),
            _built_road(2, "s2", "patch:target", [(15.0, 0.0), (25.0, 0.0)]),
        ],
        crs="EPSG:32650",
    )
    pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "source_relation_id": "lane-topo-separated-portals",
                "pair_source": "lane_topo",
            }
        ]
    )

    result = build_nodes_and_connect_roads(
        roads,
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        pairs,
        gpd.GeoDataFrame(
            [{"geometry": box(-1.0, -1.0, 26.0, 1.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(),
    )

    connection = result.connection_evidence.iloc[0]
    assert connection["connection_decision"] == "rejected"
    assert connection["reason_codes"] == "cross_segment_physical_portal_separation"
    assert int(result.roads.iloc[0]["enodeid"]) != int(
        result.roads.iloc[1]["snodeid"]
    )
    assert tuple(result.roads.iloc[0].geometry.coords[-1]) == (10.0, 0.0)
    assert tuple(result.roads.iloc[1].geometry.coords[0]) == (15.0, 0.0)


def test_same_segment_completion_preserves_trusted_surface_portal() -> None:
    roads = gpd.GeoDataFrame(
        [
            _built_road(1, "s1", "patch:source", [(0.0, 0.0), (10.0, 0.0)]),
            _built_road(2, "s1", "patch:target", [(20.0, 0.0), (30.0, 0.0)]),
        ],
        crs="EPSG:32650",
    )
    pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "patch:source",
                "target_patch_road_key": "patch:target",
                "source_relation_id": "lane-topo-intra-segment-gap",
                "pair_source": "lane_topo",
            }
        ]
    )
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "100",
                "junction_source": "t07_accepted",
                "junction_kind": "ordinary",
                "source_priority": 2,
                "source_object_id": "surface-portal",
                "geometry": box(9.0, -1.0, 11.0, 1.0),
            }
        ],
        crs=roads.crs,
    )

    result = build_nodes_and_connect_roads(
        roads,
        junctions,
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        pairs,
        gpd.GeoDataFrame(
            [{"geometry": box(-1.0, -1.0, 31.0, 1.0)}],
            crs=roads.crs,
        ),
        _empty_points(),
        _empty_points(),
        config=_config(),
    )

    assert int(result.roads.iloc[0]["enodeid"]) == int(
        result.roads.iloc[1]["snodeid"]
    )
    assert tuple(result.roads.iloc[0].geometry.coords[-1]) == (10.0, 0.0)
    assert tuple(result.roads.iloc[1].geometry.coords[0]) == (10.0, 0.0)
    source_end = result.endpoint_audit[
        result.endpoint_audit["road_id"].eq(1)
        & result.endpoint_audit["endpoint"].eq("end")
    ].iloc[0]
    assert float(source_end["junction_surface_distance_m"]) == 0.0


def test_lane_topo_within_split_carrier_is_already_physically_covered() -> None:
    first = _built_road(1, "s", "patch:a", [(0.0, 0.0), (10.0, 0.0)])
    first["carrier_id"] = "target-corridor:s:main_oneway:part:0"
    first["carrier_role"] = "main_oneway"
    second = _built_road(2, "s", "patch:b", [(10.0, 0.0), (20.0, 0.0)])
    second["carrier_id"] = "target-corridor:s:main_oneway:part:1"
    second["carrier_role"] = "main_oneway"
    roads = gpd.GeoDataFrame([first, second], crs="EPSG:32650")
    pairs = pd.DataFrame(
        [
            {
                "source_patch_road_key": "patch:a",
                "target_patch_road_key": "patch:b",
                "source_relation_id": "lane-topo-internal",
                "pair_source": "lane_topo",
            }
        ]
    )

    result = build_nodes_and_connect_roads(
        roads,
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        pairs,
        gpd.GeoDataFrame(geometry=[], crs=roads.crs),
        _empty_points(),
        _empty_points(),
        config=_config(),
    )

    connection = result.connection_evidence.iloc[0]
    assert connection["connection_decision"] == "accepted"
    assert connection["reason_codes"] == "within_assembled_carrier_path"


def test_endpoint_completion_trims_far_enough_to_avoid_new_hairpin() -> None:
    observed = LineString([(0.0, 0.0), (10.0, 50.0)])

    connected, completion = _connect_endpoint(
        observed,
        "start",
        Point(-2.0, 0.0),
    )

    assert completion is not None
    assert connected.coords[0] == (-2.0, 0.0)
    assert _max_sample_turn(connected, 2.0) <= 75.0


def test_endpoint_connection_trims_to_existing_line_point() -> None:
    observed = LineString([(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)])

    start, start_completion = _connect_endpoint(
        observed,
        "start",
        Point(10.0, 0.0),
    )
    end, end_completion = _connect_endpoint(
        observed,
        "end",
        Point(10.0, 0.0),
    )

    assert list(start.coords) == [(10.0, 0.0), (20.0, 0.0)]
    assert list(end.coords) == [(0.0, 0.0), (10.0, 0.0)]
    assert start_completion is None
    assert end_completion is None


def _built_road(
    road_id: int,
    segment_id: str,
    patch_key: str,
    coords: list[tuple[float, float]],
) -> dict[str, object]:
    geometry = LineString(coords)
    return {
        "id": road_id,
        "segment_id": segment_id,
        "patch_road_key": patch_key,
        "source_patch_road_keys": patch_key,
        "start_patch_road_keys": patch_key,
        "end_patch_road_keys": patch_key,
        "realization": "built",
        "source_snodeid": "",
        "source_enodeid": "",
        "snodeid": road_id * 10,
        "enodeid": road_id * 10 + 1,
        "length": geometry.length,
        "geometry": geometry,
    }


def test_lineage_internal_endpoint_does_not_inherit_patch_endpoint_key() -> None:
    road = _built_road(1, "segment-1", "patch:1", [(0.0, 0.0), (10.0, 0.0)])
    road["lineage_internal_end"] = True
    endpoints = _road_endpoints(
        gpd.GeoDataFrame([road], geometry="geometry", crs="EPSG:32650")
    )

    assert endpoints[0]["patch_road_keys"] == "patch:1"
    assert endpoints[1]["patch_road_keys"] == ""
    assert endpoints[1]["all_patch_road_keys"] == "patch:1"


def test_null_lineage_fields_do_not_enable_split_semantics() -> None:
    road = _built_road(1, "segment-1", "patch:1", [(0.0, 0.0), (10.0, 0.0)])
    road.update(
        {
            "carrier_id": float("nan"),
            "lineage_internal_start": float("nan"),
            "lineage_internal_end": float("nan"),
        }
    )
    endpoints = _road_endpoints(
        gpd.GeoDataFrame([road], geometry="geometry", crs="EPSG:32650")
    )

    assert [row["carrier_lineage_id"] for row in endpoints] == [
        "road:1",
        "road:1",
    ]
    assert [row["patch_road_keys"] for row in endpoints] == [
        "patch:1",
        "patch:1",
    ]
