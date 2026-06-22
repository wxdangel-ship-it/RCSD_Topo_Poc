from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_advance_right_contract import (
    apply_junction_advance_right_contract,
    apply_retained_swsd_segment_attachment_contract,
)


def test_retained_non_advance_swsd_attachment_contract_is_noop() -> None:
    swsd_road = {
        "properties": {"id": "sw_retained", "snodeid": "2", "enodeid": "3", "source": 2},
        "geometry": LineString([(10, 1), (20, 1)]),
    }
    swsd_node = {"properties": {"id": "2", "mainnodeid": "2"}, "geometry": Point(10, 1)}
    rcsd_road = {
        "properties": {"id": "rr_main", "snodeid": "10", "enodeid": "20", "source": 1},
        "geometry": LineString([(0, 0), (20, 0)]),
    }
    rcsd_nodes = [
        {"properties": {"id": "10", "mainnodeid": "10", "source": 1}, "geometry": Point(0, 0)},
        {"properties": {"id": "20", "mainnodeid": "20", "source": 1}, "geometry": Point(20, 0)},
    ]
    unit = SimpleNamespace(
        status="passed",
        segment_id="s_replaced",
        pair_nodes=["1", "2"],
        junc_nodes=[],
        detached_junc_nodes=[],
        rcsd_road_ids=["rr_main"],
        retained_node_ids=[],
    )

    stats = apply_retained_swsd_segment_attachment_contract(
        [unit],
        swsd_segments=[],
        swsd_roads=[swsd_road],
        swsd_node_by_id={"2": swsd_node},
        rcsd_roads=[rcsd_road],
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id={"rr_main": rcsd_road},
        rcsd_node_by_id={node["properties"]["id"]: node for node in rcsd_nodes},
        retained_swsd_roads=[swsd_road],
        added_road_to_segments={"rr_main": ["s_replaced"]},
    )

    assert stats["candidate_road_count"] == 0
    assert stats["swsd_node_snapped_count"] == 0
    assert stats["rcsd_split_road_count"] == 0
    assert stats["audit_rows"] == []
    assert swsd_node["geometry"].equals(Point(10, 1))
    assert list(swsd_road["geometry"].coords) == [(10.0, 1.0), (20.0, 1.0)]


def test_retained_advance_endpoint_reuse_snaps_shared_swsd_node_and_roads() -> None:
    advance_road = {
        "properties": {"id": "adv", "snodeid": "2", "enodeid": "4", "source": 2, "formway": 128},
        "geometry": LineString([(0, 10), (5, 10)]),
    }
    side_road = {
        "properties": {"id": "side", "snodeid": "2", "enodeid": "5", "source": 2},
        "geometry": LineString([(0, 10), (-5, 10)]),
    }
    swsd_node = {"properties": {"id": "2", "mainnodeid": "2"}, "geometry": Point(0, 10)}
    swsd_segments = [
        {
            "properties": {"id": "s1", "pair_nodes": ["1", "3"], "junc_nodes": ["2"], "roads": ["side"]},
            "geometry": LineString([(0, 10), (-5, 10)]),
        }
    ]
    rcsd_road = {
        "properties": {"id": "rr_main", "snodeid": "10", "enodeid": "20", "source": 1},
        "geometry": LineString([(0, 0), (20, 0)]),
    }
    rcsd_nodes = [
        {"properties": {"id": "10", "mainnodeid": "10", "source": 1}, "geometry": Point(0, 0)},
        {"properties": {"id": "20", "mainnodeid": "20", "source": 1}, "geometry": Point(20, 0)},
    ]
    unit = SimpleNamespace(
        status="passed",
        segment_id="s1",
        pair_nodes=["1", "3"],
        junc_nodes=["2"],
        detached_junc_nodes=[],
        rcsd_road_ids=["rr_main"],
        retained_node_ids=[],
    )

    stats = apply_junction_advance_right_contract(
        [unit],
        swsd_segments=swsd_segments,
        swsd_roads=[advance_road, side_road],
        swsd_node_by_id={"2": swsd_node},
        rcsd_roads=[rcsd_road],
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id={"rr_main": rcsd_road},
        rcsd_node_by_id={node["properties"]["id"]: node for node in rcsd_nodes},
        retained_swsd_roads=[advance_road, side_road],
        added_road_to_segments={"rr_main": ["s1"]},
    )

    assert stats["rcsd_endpoint_reused_count"] == 1
    assert swsd_node["geometry"].equals(Point(0, 0))
    assert list(advance_road["geometry"].coords)[0] == (0.0, 0.0)
    assert list(side_road["geometry"].coords)[0] == (0.0, 0.0)
    assert unit.retained_node_ids == ["10"]
