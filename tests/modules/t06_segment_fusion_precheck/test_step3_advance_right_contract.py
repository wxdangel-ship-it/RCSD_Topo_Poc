from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_advance_right_contract import (
    _retain_post_advance_right_swsd_carriers,
    apply_junction_advance_right_contract,
    apply_retained_swsd_segment_attachment_contract,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_advance_right_common import (
    _replace_features_by_id,
)


def test_replace_features_by_id_preserves_sequential_splice_order() -> None:
    first = {"properties": {"id": "1"}, "geometry": Point(0, 0)}
    second = {"properties": {"id": "2"}, "geometry": Point(1, 0)}
    third = {"properties": {"id": "3"}, "geometry": Point(2, 0)}
    replacement_1 = {"properties": {"id": "10"}, "geometry": Point(0, 0)}
    replacement_2 = {"properties": {"id": "20"}, "geometry": Point(1, 0)}
    missing_replacement = {"properties": {"id": "40"}, "geometry": Point(4, 0)}
    features = [first, second, third]

    _replace_features_by_id(
        features,
        {"1": [replacement_1], "2": [replacement_2], "4": [missing_replacement]},
    )

    assert [item["properties"]["id"] for item in features] == ["10", "20", "3", "40"]


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


def test_mixed_advance_right_carrier_is_retained_near_rcsd_advance() -> None:
    sw_replaced = {
        "properties": {"id": "sw_repl", "snodeid": "1", "enodeid": "2", "segmentid": "s_repl"},
        "geometry": LineString([(0, 0), (10, 0)]),
    }
    sw_retained = {
        "properties": {"id": "sw_ret", "snodeid": "3", "enodeid": "4", "segmentid": "s_ret"},
        "geometry": LineString([(20, 0), (30, 0)]),
    }
    sw_advance = {
        "properties": {"id": "sw_adv", "snodeid": "2", "enodeid": "3", "formway": 128},
        "geometry": LineString([(10, 0), (20, 0)]),
    }
    rcsd_advance = {
        "properties": {"id": "rc_adv", "snodeid": "10", "enodeid": "20", "formway": 128},
        "geometry": LineString([(10, 0.5), (20, 0.5)]),
    }
    unit = SimpleNamespace(
        status="passed",
        segment_id="s_repl",
        swsd_road_ids=["sw_adv"],
        retained_detached_swsd_road_ids=[],
    )

    stats = _retain_post_advance_right_swsd_carriers(
        [unit],
        swsd_roads=[sw_replaced, sw_retained, sw_advance],
        rcsd_roads=[rcsd_advance],
    )

    assert stats["retained_road_count"] == 1
    assert unit.swsd_road_ids == []
    assert unit.retained_detached_swsd_road_ids == ["sw_adv"]
    assert sw_advance["properties"]["t06_mixed_advance_right_carrier"] == 1


def test_dedicated_advance_segment_does_not_make_both_replaced_sides_mixed() -> None:
    sw_left = {
        "properties": {"id": "sw_left", "snodeid": "1", "enodeid": "2", "segmentid": "s_left"},
        "geometry": LineString([(0, 0), (10, 0)]),
    }
    sw_right = {
        "properties": {"id": "sw_right", "snodeid": "3", "enodeid": "4", "segmentid": "s_right"},
        "geometry": LineString([(20, 0), (30, 0)]),
    }
    sw_advance = {
        "properties": {
            "id": "sw_adv",
            "snodeid": "2",
            "enodeid": "3",
            "formway": 128,
            "segmentid": "advance_right_sw_adv",
            "segment_type": "advance_right",
        },
        "geometry": LineString([(10, 0), (20, 0)]),
    }
    rcsd_advance = {
        "properties": {"id": "rc_adv", "snodeid": "10", "enodeid": "20", "formway": 128},
        "geometry": LineString([(10, 0.5), (20, 0.5)]),
    }
    left_unit = SimpleNamespace(
        status="passed",
        segment_id="s_left",
        swsd_road_ids=["sw_adv"],
        retained_detached_swsd_road_ids=[],
    )
    right_unit = SimpleNamespace(
        status="passed",
        segment_id="s_right",
        swsd_road_ids=[],
        retained_detached_swsd_road_ids=[],
    )

    stats = _retain_post_advance_right_swsd_carriers(
        [left_unit, right_unit],
        swsd_roads=[sw_left, sw_right, sw_advance],
        rcsd_roads=[rcsd_advance],
    )

    assert stats["retained_road_count"] == 0
    assert left_unit.swsd_road_ids == ["sw_adv"]
    assert left_unit.retained_detached_swsd_road_ids == []
    assert "t06_mixed_advance_right_carrier" not in sw_advance["properties"]
