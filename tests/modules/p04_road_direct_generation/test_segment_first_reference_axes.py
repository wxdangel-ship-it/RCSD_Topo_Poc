from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_reference_axes import (
    build_segment_reference_axes,
)


def test_reference_axis_compiles_endpoint_to_endpoint_swsd_topology_chain() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "target_required": True,
                "pair_node_ids": "n0,n2",
                "swsd_road_ids": "main-b,branch,main-a",
                "geometry": LineString([(0, 0), (20, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            _road("main-a", "n0", "n1", [(0, 0), (10, 0)]),
            _road("main-b", "n1", "n2", [(20, 0), (10, 0)]),
            _road("branch", "n1", "side", [(10, 0), (10, 30)]),
        ],
        crs=segments.crs,
    )
    nodes = gpd.GeoDataFrame(
        [
            {"id": "n0", "geometry": Point(0, 0)},
            {"id": "n1", "geometry": Point(10, 0)},
            {"id": "n2", "geometry": Point(20, 0)},
            {"id": "side", "geometry": Point(10, 30)},
        ],
        crs=segments.crs,
    )

    result = build_segment_reference_axes(
        segments,
        roads,
        nodes,
        run_id="reference-axis",
    )

    axis = result.axes.iloc[0]
    assert axis["reference_state"] == "resolved"
    assert bool(axis["carrier_guidance_eligible"])
    assert axis["path_swsd_road_ids"] == "main-a,main-b"
    assert axis["excluded_swsd_road_ids"] == "branch"
    assert list(axis.geometry.coords) == [
        (0.0, 0.0),
        (10.0, 0.0),
        (20.0, 0.0),
    ]
    assert result.summary == {
        "required_segment_count": 1,
        "resolved_axis_count": 1,
        "exact_carrier_guidance_axis_count": 1,
        "semantic_audit_axis_count": 0,
        "unresolved_axis_count": 0,
    }


def test_reference_axis_audits_disconnected_swsd_member_graph() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "target_required": True,
                "pair_node_ids": "n0,n3",
                "swsd_road_ids": "m1,m2",
                "geometry": LineString([(0, 0), (30, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            _road("m1", "n0", "n1", [(0, 0), (10, 0)]),
            _road("m2", "n2", "n3", [(20, 0), (30, 0)]),
        ],
        crs=segments.crs,
    )
    nodes = gpd.GeoDataFrame(
        [
            {"id": node_id, "geometry": Point(x, 0)}
            for node_id, x in (("n0", 0), ("n1", 10), ("n2", 20), ("n3", 30))
        ],
        crs=segments.crs,
    )

    result = build_segment_reference_axes(
        segments,
        roads,
        nodes,
        run_id="reference-axis-disconnected",
    )

    assert result.axes.empty
    assert len(result.audit) == 1
    assert result.audit.iloc[0]["reference_state"] == "unresolved"
    assert (
        result.audit.iloc[0]["reason_codes"]
        == "swsd_member_graph_endpoint_path_missing"
    )
    assert result.summary["unresolved_axis_count"] == 1
    assert result.summary["exact_carrier_guidance_axis_count"] == 0


def test_reference_axis_uses_ordinary_mainnode_topology_handoff() -> None:
    segments, roads, nodes = _mainnode_handoff_fixture()
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "j1",
                "junction_kind": "ordinary",
                "topology_mode": "ordinary_semantic",
                "geometry": Point(15, 0),
            }
        ],
        crs=segments.crs,
    )

    result = build_segment_reference_axes(
        segments,
        roads,
        nodes,
        run_id="reference-axis-mainnode",
        junction_units=junctions,
    )

    axis = result.axes.iloc[0]
    assert axis["reference_state"] == "resolved"
    assert axis["path_swsd_road_ids"] == "m1,m2"
    assert (
        axis["reference_source"]
        == "swsd_endpoint_mainnode_topology_chain"
    )
    assert not bool(axis["carrier_guidance_eligible"])
    assert axis["maximum_join_gap_m"] == 10.0


def test_reference_axis_does_not_cross_complex_mainnode() -> None:
    segments, roads, nodes = _mainnode_handoff_fixture()
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "j1",
                "junction_kind": "complex",
                "topology_mode": "complex_physical",
                "geometry": Point(15, 0),
            }
        ],
        crs=segments.crs,
    )

    result = build_segment_reference_axes(
        segments,
        roads,
        nodes,
        run_id="reference-axis-complex",
        junction_units=junctions,
    )

    assert result.axes.empty
    assert result.audit.iloc[0]["reference_state"] == "unresolved"


def test_reference_axis_prefers_exact_node_path_over_mainnode_shortcut() -> None:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "target_required": True,
                "pair_node_ids": "n0,n3",
                "swsd_road_ids": "direct-a,direct-b,shortcut-a,shortcut-b",
                "geometry": LineString([(0, 0), (30, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            _road("direct-a", "n0", "n1", [(0, 0), (10, 0)]),
            _road("direct-b", "n1", "n3", [(10, 0), (30, 0)]),
            _road("shortcut-a", "n0", "side-a", [(0, 0), (0, 1)]),
            _road("shortcut-b", "side-b", "n3", [(30, 1), (30, 0)]),
        ],
        crs=segments.crs,
    )
    nodes = gpd.GeoDataFrame(
        [
            {"id": "n0", "mainnodeid": "", "geometry": Point(0, 0)},
            {"id": "n1", "mainnodeid": "", "geometry": Point(10, 0)},
            {"id": "n3", "mainnodeid": "", "geometry": Point(30, 0)},
            {"id": "side-a", "mainnodeid": "j1", "geometry": Point(0, 1)},
            {"id": "side-b", "mainnodeid": "j1", "geometry": Point(30, 1)},
        ],
        crs=segments.crs,
    )
    junctions = gpd.GeoDataFrame(
        [
            {
                "junction_group_id": "j1",
                "junction_kind": "ordinary",
                "topology_mode": "ordinary_semantic",
                "geometry": Point(15, 1),
            }
        ],
        crs=segments.crs,
    )

    result = build_segment_reference_axes(
        segments,
        roads,
        nodes,
        run_id="reference-axis-exact-first",
        junction_units=junctions,
    )

    axis = result.axes.iloc[0]
    assert axis["path_swsd_road_ids"] == "direct-a,direct-b"
    assert axis["reference_source"] == "swsd_endpoint_topology_chain"
    assert bool(axis["carrier_guidance_eligible"])


def _mainnode_handoff_fixture() -> tuple[
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
]:
    segments = gpd.GeoDataFrame(
        [
            {
                "segment_id": "s1",
                "target_required": True,
                "pair_node_ids": "n0,n3",
                "swsd_road_ids": "m1,m2",
                "geometry": LineString([(0, 0), (30, 0)]),
            }
        ],
        crs="EPSG:32650",
    )
    roads = gpd.GeoDataFrame(
        [
            _road("m1", "n0", "n1a", [(0, 0), (10, 0)]),
            _road("m2", "n1b", "n3", [(20, 0), (30, 0)]),
        ],
        crs=segments.crs,
    )
    nodes = gpd.GeoDataFrame(
        [
            {"id": "n0", "mainnodeid": "", "geometry": Point(0, 0)},
            {"id": "n1a", "mainnodeid": "j1", "geometry": Point(10, 0)},
            {"id": "n1b", "mainnodeid": "j1", "geometry": Point(20, 0)},
            {"id": "n3", "mainnodeid": "", "geometry": Point(30, 0)},
        ],
        crs=segments.crs,
    )
    return segments, roads, nodes


def _road(
    road_id: str,
    start_node: str,
    end_node: str,
    coordinates: list[tuple[float, float]],
) -> dict[str, object]:
    return {
        "id": road_id,
        "snodeid": start_node,
        "enodeid": end_node,
        "geometry": LineString(coordinates),
    }
