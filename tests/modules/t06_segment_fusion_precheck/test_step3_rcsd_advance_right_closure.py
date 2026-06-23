from __future__ import annotations

from types import SimpleNamespace

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_rcsd_advance_right_closure import (
    apply_final_advance_right_endpoint_closure,
    apply_native_rcsd_advance_right_closure,
)
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_topology_connectivity_audit import (
    build_topology_connectivity_audit_rows,
    summarize_topology_connectivity_audit,
)


def _road(road_id: str, snode: str, enode: str, coords: list[tuple[float, float]], *, formway: int = 1) -> dict:
    return {
        "properties": {
            "id": road_id,
            "snodeid": snode,
            "enodeid": enode,
            "source": 1,
            "direction": 2,
            "formway": formway,
        },
        "geometry": LineString(coords),
    }


def _node(node_id: str, x: float, y: float) -> dict:
    return {
        "properties": {"id": node_id, "mainnodeid": node_id, "source": 1},
        "geometry": Point(x, y),
    }


def _swsd_road(road_id: str, snode: str, enode: str, coords: list[tuple[float, float]], *, formway: int = 1) -> dict:
    return {
        "properties": {
            "id": road_id,
            "snodeid": snode,
            "enodeid": enode,
            "source": 2,
            "direction": 2,
            "formway": formway,
            "segmentid": "s_ret",
        },
        "geometry": LineString(coords),
    }


def _swsd_node(node_id: str, x: float, y: float) -> dict:
    return {
        "properties": {"id": node_id, "mainnodeid": node_id, "source": 2},
        "geometry": Point(x, y),
    }


def test_native_rcsd_advance_leaf_endpoint_splits_selected_rcsd_road() -> None:
    main = _road("main", "10", "20", [(0, 0), (20, 0)])
    advance = _road("adv", "10", "99", [(0, 0), (10, 1)], formway=128)
    rcsd_roads = [main, advance]
    rcsd_nodes = [_node("10", 0, 0), _node("20", 20, 0), _node("99", 10, 1)]
    rcsd_road_by_id = {road["properties"]["id"]: road for road in rcsd_roads}
    rcsd_node_by_id = {node["properties"]["id"]: node for node in rcsd_nodes}
    unit = SimpleNamespace(
        status="passed",
        segment_id="s1",
        rcsd_road_ids=["main", "adv"],
        retained_node_ids=[],
    )
    added_road_to_segments = {"main": ["s1"], "adv": ["s1"]}

    stats = apply_native_rcsd_advance_right_closure(
        [unit],
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        added_road_to_segments=added_road_to_segments,
    )

    assert stats["candidate_road_count"] == 1
    assert stats["repaired_endpoint_count"] == 1
    assert stats["failed_endpoint_count"] == 0
    assert stats["split_original_road_count"] == 1
    assert stats["split_road_count"] == 2
    assert Point(list(advance["geometry"].coords)[-1]).equals(Point(10, 0))
    assert rcsd_node_by_id["99"]["geometry"].equals(Point(10, 0))
    assert "main" not in added_road_to_segments
    assert any(road_id.startswith("main__t06advsplit_") for road_id in added_road_to_segments)
    assert "99" in unit.retained_node_ids


def test_native_rcsd_advance_leaf_endpoint_splits_retained_swsd_road() -> None:
    main = _road("main", "10", "20", [(0, 0), (-10, 0)])
    advance = _road("adv", "10", "99", [(0, 0), (10, 1)], formway=128)
    rcsd_roads = [main, advance]
    rcsd_nodes = [_node("10", 0, 0), _node("20", -10, 0), _node("99", 10, 1)]
    swsd_road = {
        "properties": {"id": "sw_main", "snodeid": "1", "enodeid": "2", "source": 2, "segmentid": "s_ret"},
        "geometry": LineString([(0, 0), (20, 0)]),
    }
    swsd_roads = [swsd_road]
    swsd_nodes = [
        {"properties": {"id": "1", "mainnodeid": "1", "source": 2}, "geometry": Point(0, 0)},
        {"properties": {"id": "2", "mainnodeid": "2", "source": 2}, "geometry": Point(20, 0)},
    ]
    rcsd_road_by_id = {"main": main, "adv": advance}
    rcsd_node_by_id = {node["properties"]["id"]: node for node in rcsd_nodes}
    swsd_road_by_id = {"sw_main": swsd_road}
    swsd_node_by_id = {node["properties"]["id"]: node for node in swsd_nodes}
    unit = SimpleNamespace(status="passed", segment_id="s1", rcsd_road_ids=["main", "adv"], retained_node_ids=[])

    stats = apply_native_rcsd_advance_right_closure(
        [unit],
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        swsd_roads=swsd_roads,
        swsd_nodes=swsd_nodes,
        swsd_road_by_id=swsd_road_by_id,
        swsd_node_by_id=swsd_node_by_id,
        retained_swsd_roads=swsd_roads,
        added_road_to_segments={"main": ["s1"], "adv": ["s1"]},
    )

    assert stats["repaired_endpoint_count"] == 1
    assert stats["failed_endpoint_count"] == 0
    assert stats["generated_swsd_node_count"] == 1
    assert stats["retained_swsd_split_original_road_count"] == 1
    assert stats["retained_swsd_split_road_count"] == 2
    generated_node_id = stats["audit_rows"][1]["properties"]["generated_swsd_node_id"]
    assert Point(list(advance["geometry"].coords)[-1]).equals(Point(10, 0))
    assert rcsd_node_by_id["99"]["properties"]["mainnodeid"] == "99"
    assert swsd_node_by_id[generated_node_id]["properties"]["mainnodeid"] == "99"
    assert swsd_node_by_id[generated_node_id]["properties"]["source"] == 2
    assert "sw_main" not in swsd_road_by_id
    assert all(road["properties"]["id"].startswith("sw_main__t06swsdadvsplit_") for road in swsd_roads)


def test_native_rcsd_advance_keeps_mixed_retained_swsd_boundary_connected() -> None:
    main = _road("main", "0", "10", [(-10, 0), (0, 0)])
    advance = _road("adv", "10", "20", [(0, 0), (10, 0)], formway=128)
    retained_advance = _swsd_road("sw_adv", "20", "2", [(10, 0), (20, 0)], formway=128)
    retained_advance["properties"]["segmentid"] = ""
    retained_advance["properties"]["t06_mixed_advance_right_split_reason"] = "mixed_advance_right_retained_swsd_side"
    rcsd_roads = [main, advance]
    rcsd_nodes = [_node("0", -10, 0), _node("10", 0, 0), _node("20", 10, 0)]
    rcsd_road_by_id = {road["properties"]["id"]: road for road in rcsd_roads}
    rcsd_node_by_id = {node["properties"]["id"]: node for node in rcsd_nodes}
    unit = SimpleNamespace(status="passed", segment_id="s1", rcsd_road_ids=["main", "adv"], retained_node_ids=[])

    stats = apply_native_rcsd_advance_right_closure(
        [unit],
        rcsd_roads=rcsd_roads,
        rcsd_nodes=rcsd_nodes,
        rcsd_road_by_id=rcsd_road_by_id,
        rcsd_node_by_id=rcsd_node_by_id,
        retained_swsd_roads=[retained_advance],
        added_road_to_segments={"main": ["s1"], "adv": ["s1"]},
    )

    assert stats["repaired_endpoint_count"] == 0
    assert stats["failed_endpoint_count"] == 0
    assert stats["retained_swsd_split_original_road_count"] == 0
    assert Point(list(advance["geometry"].coords)[-1]).equals(Point(10, 0))
    assert rcsd_node_by_id["20"]["geometry"].equals(Point(10, 0))
    assert all(row["properties"]["action"] == "verify_existing_rcsd_advance_endpoint" for row in stats["audit_rows"])


def test_final_advance_endpoint_closure_repairs_retained_swsd_advance_leaf() -> None:
    main = _swsd_road("sw_main", "1", "2", [(0, 0), (20, 0)])
    advance = _swsd_road("sw_adv", "1", "9", [(0, 0), (10, 1)], formway=128)
    frcsd_roads = [main, advance]
    frcsd_nodes = [_swsd_node("1", 0, 0), _swsd_node("2", 20, 0), _swsd_node("9", 10, 1)]
    stats = {"audit_rows": [], "repaired_endpoint_count": 0, "failed_endpoint_count": 0}
    unit = SimpleNamespace(status="passed", segment_id="s1", rcsd_road_ids=[], retained_node_ids=[])

    apply_final_advance_right_endpoint_closure(
        frcsd_roads,
        frcsd_nodes,
        stats,
        [unit],
        [],
        {},
        {},
        {},
        "source",
        1,
    )

    assert stats["final_repaired_endpoint_count"] == 1
    assert stats["failed_endpoint_count"] == 0
    assert Point(list(advance["geometry"].coords)[-1]).equals(Point(10, 0))
    assert any(road["properties"]["id"].startswith("sw_main__t06finaladvsplit_") for road in frcsd_roads)
    assert next(node for node in frcsd_nodes if node["properties"]["id"] == "9")["geometry"].equals(Point(10, 0))
    assert any(road["properties"]["snodeid"] == "9" or road["properties"]["enodeid"] == "9" for road in frcsd_roads)

    audit_rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        swsd_roads=[],
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=[],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )
    summarize_topology_connectivity_audit(audit_rows)
    assert not [
        row
        for row in audit_rows
        if (row["properties"].get("audit_layer") == "advance_right_endpoint_connectivity")
        and row["properties"].get("audit_status") == "fail"
    ]


def test_final_advance_endpoint_closure_does_not_split_retained_only_swsd_target() -> None:
    retained_main = _swsd_road("sw_main", "1", "2", [(0, 0), (20, 0)])
    rcsd_main = _road("rc_main", "10", "20", [(-10, 0), (0, 0)])
    rcsd_advance = _road("rc_adv", "10", "99", [(0, 0), (10, 1)], formway=128)
    frcsd_roads = [retained_main, rcsd_main, rcsd_advance]
    frcsd_nodes = [
        _swsd_node("1", 0, 0),
        _swsd_node("2", 20, 0),
        _node("10", 0, 0),
        _node("20", -10, 0),
        _node("99", 10, 1),
    ]
    stats = {"audit_rows": [], "repaired_endpoint_count": 0, "failed_endpoint_count": 0}
    unit = SimpleNamespace(status="passed", segment_id="s1", rcsd_road_ids=["rc_adv"], retained_node_ids=[])

    apply_final_advance_right_endpoint_closure(
        frcsd_roads,
        frcsd_nodes,
        stats,
        [unit],
        [],
        {},
        {},
        {},
        "source",
        1,
    )

    assert stats["final_repaired_endpoint_count"] == 0
    assert stats["final_failed_endpoint_count"] >= 1
    assert Point(list(rcsd_advance["geometry"].coords)[-1]).equals(Point(10, 1))
    assert not any(road["properties"]["id"].startswith("sw_main__t06finaladvsplit_") for road in frcsd_roads)
    assert any(
        row["properties"].get("action") == "audit_retained_swsd_non_advance_target"
        for row in stats["audit_rows"]
    )


def test_final_advance_endpoint_closure_does_not_split_retained_non_advance_target_for_added_rcsd_advance() -> None:
    retained_main = _swsd_road("sw_main", "1", "2", [(0, 0), (20, 0)])
    rcsd_main = _road("rc_main", "10", "20", [(-10, 0), (0, 0)])
    rcsd_advance = _road("rc_adv", "10", "99", [(0, 0), (10, 1)], formway=128)
    frcsd_roads = [retained_main, rcsd_main, rcsd_advance]
    frcsd_nodes = [
        _swsd_node("1", 0, 0),
        _swsd_node("2", 20, 0),
        _node("10", 0, 0),
        _node("20", -10, 0),
        _node("99", 10, 1),
    ]
    stats = {"audit_rows": [], "repaired_endpoint_count": 0, "failed_endpoint_count": 0}
    unit = SimpleNamespace(status="passed", segment_id="s1", rcsd_road_ids=["rc_adv"], retained_node_ids=[])
    added_road_to_segments = {"rc_adv": ["s1"]}

    apply_final_advance_right_endpoint_closure(
        frcsd_roads,
        frcsd_nodes,
        stats,
        [unit],
        [],
        {},
        added_road_to_segments,
        {},
        "source",
        1,
    )

    assert stats["final_repaired_endpoint_count"] == 0
    assert stats["final_failed_endpoint_count"] >= 1
    assert "rc_adv" in added_road_to_segments
    assert any(road["properties"]["id"] == "rc_adv" for road in frcsd_roads)
    assert not any(road["properties"]["id"].startswith("sw_main__t06finaladvsplit_") for road in frcsd_roads)
    assert Point(list(rcsd_advance["geometry"].coords)[-1]).equals(Point(10, 1))
    assert any(
        row["properties"].get("action") == "audit_retained_swsd_non_advance_target"
        and row["properties"].get("audit_status") == "fail"
        for row in stats["audit_rows"]
    )


def test_final_advance_endpoint_closure_can_split_retained_swsd_advance_target() -> None:
    retained_advance = _swsd_road("sw_adv", "1", "2", [(0, 0), (20, 0)], formway=128)
    rcsd_main = _road("rc_main", "10", "20", [(-10, 0), (0, 0)])
    rcsd_advance = _road("rc_adv", "10", "99", [(0, 0), (10, 1)], formway=128)
    frcsd_roads = [retained_advance, rcsd_main, rcsd_advance]
    frcsd_nodes = [
        _swsd_node("1", 0, 0),
        _swsd_node("2", 20, 0),
        _node("10", 0, 0),
        _node("20", -10, 0),
        _node("99", 10, 1),
    ]
    stats = {"audit_rows": [], "repaired_endpoint_count": 0, "failed_endpoint_count": 0}

    apply_final_advance_right_endpoint_closure(
        frcsd_roads,
        frcsd_nodes,
        stats,
        [SimpleNamespace(status="passed", segment_id="s1", rcsd_road_ids=["rc_adv"], retained_node_ids=[])],
        [],
        {},
        {"rc_adv": ["s1"]},
        {},
        "source",
        1,
    )

    assert stats["final_repaired_endpoint_count"] >= 1
    assert stats["final_failed_endpoint_count"] == 0
    assert any(
        row["properties"].get("rcsd_advance_road_id") == "rc_adv"
        and row["properties"].get("target_swsd_road_id") == "sw_adv"
        and row["properties"].get("audit_status") == "repaired"
        for row in stats["audit_rows"]
    )

    audit_rows = build_topology_connectivity_audit_rows(
        swsd_segments=[],
        swsd_roads=[],
        frcsd_roads=frcsd_roads,
        frcsd_nodes=frcsd_nodes,
        segment_relation_rows=[],
        advance_right_audit_rows=[],
        source_field_name="source",
        swsd_source_value=2,
        rcsd_source_value=1,
    )
    assert not [
        row
        for row in audit_rows
        if row["properties"].get("audit_layer") == "advance_right_endpoint_connectivity"
        and row["properties"].get("audit_status") == "fail"
    ]
