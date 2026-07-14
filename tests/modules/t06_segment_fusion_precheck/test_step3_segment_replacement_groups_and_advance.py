from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point, mapping

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import run_t06_step3_segment_replacement
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_advance_right_contract import _generated_node_mainnode_id


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def _road(road_id: str, snode: int | str, enode: int | str, **props):
    payload = {"id": road_id, "snodeid": snode, "enodeid": enode, "direction": 0}
    payload.update(props)
    return {
        "properties": payload,
        "geometry": LineString([(float(str(snode).lstrip("r") or 0), 0), (float(str(enode).lstrip("r") or 0), 0)]),
    }


def _node(node_id: int | str, x: float, *, mainnodeid=0, kind=0, grade=0, kind_2=0, grade_2=0, closed_con=0):
    return {
        "properties": {
            "id": node_id,
            "mainnodeid": mainnodeid,
            "kind": kind,
            "grade": grade,
            "kind_2": kind_2,
            "grade_2": grade_2,
            "closed_con": closed_con,
        },
        "geometry": Point(x, 0),
    }


def _props(path: Path) -> list[dict]:
    payload = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    return [item["properties"] for item in payload["features"]]


def test_step3_group_created_member_filters_distant_group_roads(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "0-0双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw1"]},
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "properties": {"id": "s2", "sgrade": "0-0双", "pair_nodes": [3, 4], "junc_nodes": [], "roads": ["sw2"]},
                "geometry": LineString([(100, 0), (110, 0)]),
            },
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            {"properties": {"id": "sw1", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "sw2", "snodeid": 3, "enodeid": 4, "direction": 0}, "geometry": LineString([(100, 0), (110, 0)])},
        ],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [_node(1, 0, mainnodeid=1), _node(2, 10, mainnodeid=2), _node(3, 100, mainnodeid=3), _node(4, 110, mainnodeid=4)],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "rr2", "snodeid": 30, "enodeid": 40, "direction": 0}, "geometry": LineString([(100, 0), (110, 0)])},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [_node(10, 0, mainnodeid=10), _node(20, 10, mainnodeid=20), _node(30, 100, mainnodeid=30), _node(40, 110, mainnodeid=40)],
    )
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": [10, 20],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
    )
    _write(
        tmp_path / "t06_segment_replacement_plan.gpkg",
        [
            {
                "properties": {
                    "replacement_plan_id": "standard:s1",
                    "swsd_segment_id": "s1",
                    "plan_status": "ready",
                    "execution_action": "replace",
                    "execution_scope": "standard_segment",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": [10, 20],
                },
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "properties": {
                    "replacement_plan_id": "group_path_corridor:s2",
                    "swsd_segment_id": "s2",
                    "plan_status": "ready",
                    "execution_action": "replace",
                    "execution_scope": "path_corridor_group",
                    "group_segment_ids": ["s1", "s2"],
                    "source_segment_ids": ["s2"],
                    "rcsd_road_ids": ["rr1", "rr2"],
                    "retained_node_ids": [10, 20, 30, 40],
                    "rcsd_pair_nodes": [30, 40],
                    "buffer_distances_m": [20.0],
                },
                "geometry": LineString([(0, 0), (110, 0)]),
            },
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s1"]["frcsd_road_ids"] == ["rr1"]
    assert relations["s2"]["relation_status"] == "replaced"
    assert relations["s2"]["frcsd_road_ids"] == ["rr2"]
    assert relations["s2"]["pruned_non_owner_frcsd_road_ids"] == ["rr1"]


def test_step3_prefers_replacement_plan_json_to_keep_geometryless_special_rows(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sr1"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            }
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr1", 1, 2)])
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [
            _node(1, 1, mainnodeid=1),
            _node(2, 2, mainnodeid=2),
            _node(3, 3, mainnodeid=3, kind=64, kind_2=64),
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])},
            {"properties": {"id": "rr_internal", "snodeid": 30, "enodeid": 31, "direction": 0}, "geometry": LineString([(3, 0), (3.1, 0)])},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [_node(10, 1, mainnodeid=10), _node(20, 2, mainnodeid=20), _node(30, 3, mainnodeid=30), _node(31, 3.1, mainnodeid=30)],
    )
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [3],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [30],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": [10, 20],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(1, 0), (2, 0)]),
            }
        ],
    )
    standard_plan = {
        "replacement_plan_id": "standard:s1",
        "swsd_segment_id": "s1",
        "plan_status": "ready",
        "execution_action": "replace",
        "execution_scope": "standard_segment",
        "swsd_pair_nodes": [1, 2],
        "swsd_junc_nodes": [3],
        "rcsd_pair_nodes": [10, 20],
        "rcsd_junc_nodes": [30],
        "rcsd_road_ids": ["rr1"],
        "retained_node_ids": [10, 20],
    }
    _write(
        tmp_path / "t06_segment_replacement_plan.gpkg",
        [{"properties": standard_plan, "geometry": LineString([(1, 0), (2, 0)])}],
    )
    (tmp_path / "t06_segment_replacement_plan.json").write_text(
        json.dumps(
            {
                "row_count": 2,
                "features": [
                    {"properties": standard_plan, "geometry": mapping(LineString([(1, 0), (2, 0)]))},
                    {
                        "properties": {
                            "replacement_plan_id": "special:3",
                            "swsd_segment_id": "s1",
                            "plan_status": "ready",
                            "execution_action": "include_context",
                            "execution_scope": "special_junction_group_internal",
                            "special_junction_id": "3",
                            "special_junction_type": "roundabout",
                            "group_segment_ids": ["s1"],
                            "source_segment_ids": ["s1"],
                            "rcsd_road_ids": ["rr_internal"],
                            "retained_node_ids": [30, 31],
                        },
                        "geometry": None,
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["input_paths"]["step2_replacement_plan_path"].endswith("t06_segment_replacement_plan.json")
    assert summary["input_replacement_plan_count"] == 2
    assert summary["special_junction_group_consumed_count"] == 1
    assert summary["special_junction_added_rcsd_road_count"] == 1
    assert summary["special_junction_added_rcsd_node_count"] == 2
    assert summary["added_rcsd_road_count"] == 2

    roads = {(item["id"], item["source"]) for item in _props(artifacts.frcsd_road_gpkg_path)}
    assert ("rr_internal", 1) in roads


def test_step3_preserves_removed_node_when_retained_swsd_segment_still_references_it(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "main_seg", "sgrade": "main", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["main_a", "main_b"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "properties": {"id": "side_seg", "sgrade": "side", "pair_nodes": [3, 4], "junc_nodes": [], "roads": ["side"]},
                "geometry": LineString([(3, 0), (4, 0)]),
            },
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            _road("main_a", 1, 3),
            _road("main_b", 3, 2),
            _road("side", 3, 4),
        ],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [
            _node(1, 1, mainnodeid=1),
            _node(2, 2, mainnodeid=2),
            _node(3, 3, mainnodeid=3),
            _node(4, 4, mainnodeid=4),
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])}],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [_node(10, 1, mainnodeid=10), _node(20, 2, mainnodeid=20)],
    )
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "main_seg",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": [10, 20],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(1, 0), (2, 0)]),
            }
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["removed_swsd_node_preserved_by_retained_road_count"] == 1

    roads = _props(artifacts.frcsd_road_gpkg_path)
    nodes = _props(artifacts.frcsd_node_gpkg_path)
    node_ids = {str(item["id"]) for item in nodes if item["source"] == 2}
    assert "3" in node_ids
    assert ("side", 2) in {(item["id"], item["source"]) for item in roads}
    assert not {
        str(road[endpoint])
        for road in roads
        for endpoint in ("snodeid", "enodeid")
        if road["source"] == 2
    }.difference(node_ids)

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["main_seg"]["relation_status"] == "replaced"
    assert relations["side_seg"]["relation_status"] == "retained_swsd"
    assert relations["side_seg"]["frcsd_road_ids"] == ["side"]
    assert relations["side_seg"]["swsd_to_frcsd_node_map"][0]["frcsd_node_ids"] == ["3"]


def test_step3_adds_passed_special_junction_internal_rcsd_entities(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sr1"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            }
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [_road("sr1", 1, 2)],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [
            _node(1, 1, mainnodeid=1, kind=4, grade=1, kind_2=4, grade_2=1, closed_con=0),
            _node(2, 2, mainnodeid=2, kind=4, grade=1, kind_2=4, grade_2=1, closed_con=0),
            _node(3, 3, mainnodeid=3, kind=64, grade=2, kind_2=64, grade_2=2, closed_con=0),
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])},
            {"properties": {"id": "rr_internal", "snodeid": 30, "enodeid": 31, "direction": 0}, "geometry": LineString([(3, 0), (3.1, 0)])},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            _node(10, 1, mainnodeid=10),
            _node(20, 2, mainnodeid=20),
            _node(30, 3, mainnodeid=30),
            _node(31, 3.1, mainnodeid=30),
        ],
    )
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [3],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [30],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": [10, 20],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(1, 0), (2, 0)]),
            }
        ],
    )
    (tmp_path / "t06_special_junction_group_audit.json").write_text(
        json.dumps(
            {
                "row_count": 1,
                "features": [
                    {
                        "properties": {
                            "special_junction_id": "3",
                            "special_junction_type": "roundabout",
                            "gate_status": "passed",
                            "associated_segment_ids": ["s1"],
                            "replaceable_segment_ids": ["s1"],
                            "rcsd_junction_id": "30",
                            "rcsd_junction_node_ids": [30, 31],
                            "rcsd_junction_road_ids": ["rr_internal"],
                        },
                        "geometry": None,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["special_junction_group_consumed_count"] == 1
    assert summary["special_junction_added_rcsd_road_count"] == 1
    assert summary["special_junction_added_rcsd_node_count"] == 2
    assert summary["added_rcsd_road_count"] == 2
    assert summary["added_rcsd_node_count"] == 4
    assert summary["unreplaced_rcsd_road_count"] == 0

    roads = {(item["id"], item["source"]) for item in _props(artifacts.frcsd_road_gpkg_path)}
    assert ("rr1", 1) in roads
    assert ("rr_internal", 1) in roads

    nodes = {(str(item["id"]), item["source"]) for item in _props(artifacts.frcsd_node_gpkg_path)}
    assert {("10", 1), ("20", 1), ("30", 1), ("31", 1)}.issubset(nodes)

    junctions = {item["junction_c_id"]: item for item in _props(artifacts.junction_rebuild_audit_gpkg_path)}
    assert set(junctions["3"]["added_rcsd_node_ids"]) == {"30", "31"}


def test_step3_removes_passed_complex_junction_internal_swsd_road(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {"properties": {"id": "s1", "sgrade": "主单", "pair_nodes": [1, 3], "junc_nodes": [], "roads": ["sr1"]}, "geometry": LineString([(1, 0), (3, 0)])},
            {"properties": {"id": "s2", "sgrade": "主单", "pair_nodes": [3, 5], "junc_nodes": [], "roads": ["sr2"]}, "geometry": LineString([(4, 0), (5, 0)])},
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [_road("sr1", 1, 3), _road("internal", 3, 4), _road("sr2", 4, 5)],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [
            _node(1, 1, mainnodeid=1),
            _node(3, 3, mainnodeid=3, kind=16, grade=1, kind_2=128, grade_2=1, closed_con=2),
            _node(4, 4, mainnodeid=3),
            _node(5, 5, mainnodeid=5),
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [_road("rr1", 10, 30), _road("rr2", 30, 50)],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [_node(10, 1, mainnodeid=10), _node(30, 3, mainnodeid=30), _node(50, 5, mainnodeid=50)],
    )
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {"properties": {"swsd_segment_id": "s1", "swsd_pair_nodes": [1, 3], "rcsd_pair_nodes": [10, 30], "rcsd_road_ids": ["rr1"], "retained_node_ids": [10, 30]}, "geometry": LineString([(1, 0), (3, 0)])},
            {"properties": {"swsd_segment_id": "s2", "swsd_pair_nodes": [3, 5], "rcsd_pair_nodes": [30, 50], "rcsd_road_ids": ["rr2"], "retained_node_ids": [30, 50]}, "geometry": LineString([(4, 0), (5, 0)])},
        ],
    )
    (tmp_path / "t06_special_junction_group_audit.json").write_text(
        json.dumps(
            {
                "features": [
                    {
                        "properties": {
                            "special_junction_id": "3",
                            "special_junction_type": "complex",
                            "gate_status": "passed",
                            "associated_segment_ids": ["s1", "s2"],
                            "replaceable_segment_ids": ["s1", "s2"],
                            "rcsd_junction_id": "30",
                            "rcsd_junction_node_ids": [30],
                            "rcsd_junction_road_ids": [],
                        },
                        "geometry": None,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["special_junction_internal_swsd_removed_road_count"] == 1
    roads = {(item["id"], item["source"]) for item in _props(artifacts.frcsd_road_gpkg_path)}
    assert ("internal", 2) not in roads
    removed = {item["entity_id"] for item in _props(artifacts.summary_path.parent / "t06_step3_removed_swsd_roads.gpkg")}
    assert "internal" in removed


def test_step3_adds_post_replacement_advance_right_attachments(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "0-0双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw1"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "properties": {"id": "s2", "sgrade": "0-0双", "pair_nodes": [3, 4], "junc_nodes": [], "roads": ["sw2"]},
                "geometry": LineString([(3, 0), (4, 0)]),
            },
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sw1", 1, 2), _road("sw2", 3, 4)])
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [_node(1, 1, mainnodeid=1), _node(2, 2, mainnodeid=2), _node(3, 3, mainnodeid=3), _node(4, 4, mainnodeid=4)],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            _road("rr1", 10, 20),
            _road("rr2", 30, 40),
            _road("connector_a", 20, 50),
            _road("advance_bridge", 50, 60, formway=128),
            _road("connector_b", 60, 30),
            _road("dead_spur", 50, 99),
            _road("advance_seed", 70, 71, formway=128),
            _road("attached_to_seed", 70, 71),
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            _node(10, 10, mainnodeid=10),
            _node(20, 20, mainnodeid=20),
            _node(30, 30, mainnodeid=30),
            _node(40, 40, mainnodeid=40),
            _node(50, 50, mainnodeid=50),
            _node(60, 60, mainnodeid=60),
            _node(70, 70, mainnodeid=70),
            _node(71, 71, mainnodeid=71),
            _node(99, 99, mainnodeid=99),
        ],
    )
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr1", "advance_seed"],
                    "retained_node_ids": [10, 20, 70, 71],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "properties": {
                    "swsd_segment_id": "s2",
                    "swsd_pair_nodes": [3, 4],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [30, 40],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr2"],
                    "retained_node_ids": [30, 40],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(3, 0), (4, 0)]),
            },
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["post_advance_right_attachment_component_count"] == 0
    assert summary["post_advance_right_attachment_added_road_count"] == 0
    assert summary["post_advance_right_attachment_attached_road_count"] == 0

    roads = {(item["id"], item["source"]) for item in _props(artifacts.frcsd_road_gpkg_path)}
    assert not {
        ("connector_a", 1),
        ("advance_bridge", 1),
        ("connector_b", 1),
        ("attached_to_seed", 1),
    }.intersection(roads)
    assert ("dead_spur", 1) not in roads

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert "advance_bridge" not in relations["s1"]["frcsd_road_ids"]
    assert "advance_bridge" not in relations["s2"]["frcsd_road_ids"]
    assert "dead_spur" not in relations["s1"]["frcsd_road_ids"]


def test_step3_adds_paired_advance_right_road_sharing_selected_endpoint(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [{"properties": {"id": "s1", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw1"]}, "geometry": LineString([(0, 0), (10, 0)])}],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [{"properties": {"id": "sw1", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])}],
    )
    swsd_nodes = _write(tmp_path / "swsd_nodes.gpkg", [_node(1, 0), _node(2, 10)])
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr_main", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "advance_seed", "snodeid": 20, "enodeid": 30, "direction": 0, "formway": 128}, "geometry": LineString([(10, 0), (15, 5)])},
            {"properties": {"id": "advance_pair", "snodeid": 40, "enodeid": 20, "direction": 0, "formway": 128}, "geometry": LineString([(15, -5), (10, 0)])},
            {"properties": {"id": "advance_unrelated", "snodeid": 50, "enodeid": 60, "direction": 0, "formway": 128}, "geometry": LineString([(50, 0), (60, 0)])},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [_node(10, 0), _node(20, 10), _node(30, 15), _node(40, 15), _node(50, 50), _node(60, 60)],
    )
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_main", "advance_seed"],
                    "retained_node_ids": [10, 20, 30],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["post_advance_right_paired_advance_road_count"] == 0

    roads = {(item["id"], item["source"]) for item in _props(artifacts.frcsd_road_gpkg_path)}
    assert ("advance_pair", 1) not in roads
    assert ("advance_unrelated", 1) not in roads

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert "advance_pair" not in relations["s1"]["frcsd_road_ids"]


def test_step3_post_advance_does_not_cross_retained_swsd_corridor(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {"properties": {"id": "s1", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw1"]}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "s_ret", "pair_nodes": [2, 3], "junc_nodes": [], "roads": ["sw_ret"]}, "geometry": LineString([(20, 0), (30, 0)])},
            {"properties": {"id": "s2", "pair_nodes": [3, 4], "junc_nodes": [], "roads": ["sw2"]}, "geometry": LineString([(40, 0), (50, 0)])},
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            {"properties": {"id": "sw1", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "sw_ret", "snodeid": 2, "enodeid": 3, "direction": 0}, "geometry": LineString([(20, 0), (30, 0)])},
            {"properties": {"id": "sw2", "snodeid": 3, "enodeid": 4, "direction": 0}, "geometry": LineString([(40, 0), (50, 0)])},
        ],
    )
    swsd_nodes = _write(tmp_path / "swsd_nodes.gpkg", [_node(1, 0), _node(2, 20), _node(3, 30), _node(4, 50)])
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "blocked_corridor", "snodeid": 20, "enodeid": 30, "direction": 0}, "geometry": LineString([(20, 0), (30, 0)])},
            {"properties": {"id": "advance_tail", "snodeid": 30, "enodeid": 40, "direction": 0, "formway": 128}, "geometry": LineString([(30, 0), (40, 0)])},
            {"properties": {"id": "rr2", "snodeid": 40, "enodeid": 50, "direction": 0}, "geometry": LineString([(40, 0), (50, 0)])},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [_node(10, 0), _node(20, 10), _node(30, 30), _node(40, 40), _node(50, 50)],
    )
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": [10, 20],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "properties": {
                    "swsd_segment_id": "s2",
                    "swsd_pair_nodes": [3, 4],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [40, 50],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr2"],
                    "retained_node_ids": [40, 50],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(40, 0), (50, 0)]),
            },
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    roads = {(item["id"], item["source"]) for item in _props(artifacts.frcsd_road_gpkg_path)}
    assert ("sw_ret", 2) in roads
    assert ("blocked_corridor", 1) not in roads

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s_ret"]["relation_status"] == "retained_swsd"
    assert relations["s_ret"]["frcsd_road_ids"] == ["sw_ret"]
    assert "blocked_corridor" not in relations["s1"]["frcsd_road_ids"]
    assert "blocked_corridor" not in relations["s2"]["frcsd_road_ids"]


def test_step3_adds_advance_right_bridge_to_mixed_rcsd_swsd_boundary(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {"properties": {"id": "s1", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw1"]}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "s2", "pair_nodes": [3, 4], "junc_nodes": [], "roads": ["sw2"]}, "geometry": LineString([(20, 0), (30, 0)])},
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            {"properties": {"id": "sw1", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "sw2", "snodeid": 3, "enodeid": 4, "direction": 0}, "geometry": LineString([(20, 0), (30, 0)])},
        ],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [_node(1, 0), _node(2, 10), _node(3, 20), _node(4, 30)],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "advance_bridge", "snodeid": 20, "enodeid": 50, "direction": 0, "formway": 128}, "geometry": LineString([(10, 0), (20, 0)])},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [_node(10, 0), _node(20, 10), _node(50, 20)],
    )
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr1"],
                    "retained_node_ids": [10, 20],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["post_advance_right_attachment_component_count"] == 0
    assert summary["post_advance_right_mixed_boundary_component_count"] == 0

    roads = {(item["id"], item["source"]) for item in _props(artifacts.frcsd_road_gpkg_path)}
    assert ("advance_bridge", 1) not in roads
    assert ("sw2", 2) in roads

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert "advance_bridge" not in relations["s1"]["frcsd_road_ids"]
    assert relations["s2"]["relation_status"] == "retained_swsd"


def test_step3_projects_swsd_only_advance_right_carrier_to_split_rcsd_road(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [{"properties": {"id": "s1", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["sw_main", "sw_adv"]}, "geometry": LineString([(0, 0), (10, 0)])}],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            {"properties": {"id": "sw_main", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "sw_adv", "snodeid": 3, "enodeid": 4, "direction": 0, "formway": 128}, "geometry": LineString([(5, 0), (5, 5)])},
        ],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [
            _node(1, 0),
            _node(2, 10),
            _node(3, 5, kind=4, grade=1),
            {"properties": {"id": 4, "mainnodeid": 4, "kind": 4, "grade": 1}, "geometry": Point(5, 5)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr_main", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])}],
    )
    rcsd_nodes = _write(tmp_path / "rcsdnode_out.gpkg", [_node(10, 0), _node(15, 5, mainnodeid=15), _node(20, 10)])
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [3],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [15],
                    "rcsd_road_ids": ["rr_main"],
                    "retained_node_ids": [10, 15, 20],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["post_advance_right_swsd_carrier_retained_road_count"] == 1
    assert summary["post_advance_right_swsd_carrier_rcsd_generated_node_count"] == 0
    assert summary["post_advance_right_swsd_carrier_rcsd_split_original_road_count"] == 0
    assert summary["post_advance_right_swsd_carrier_rcsd_split_road_count"] == 0

    roads = {(item["id"], item["source"]) for item in _props(artifacts.frcsd_road_gpkg_path)}
    assert ("sw_main", 2) not in roads
    assert {("sw_adv", 2), ("rr_main__t06advsplit_1", 1), ("rr_main__t06advsplit_2", 1)}.issubset(roads)
    assert ("rr_main", 1) not in roads

    nodes = {(str(item["id"]), item["source"]): item for item in _props(artifacts.frcsd_node_gpkg_path)}
    assert ("21", 1) in nodes
    relations = _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)
    assert relations[0]["relation_status"] == "replaced"
    assert relations[0]["frcsd_road_source_values"] == [1]
    assert relations[0]["retained_detached_swsd_road_ids"] == []


def test_step3_contract_handles_retained_segment_advance_right_shared_node(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_repl", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw_repl"]},
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "properties": {"id": "s_ret", "pair_nodes": [2, 4], "junc_nodes": [50], "roads": ["sw_ret"]},
                "geometry": LineString([(10, 0), (20, 0)]),
            },
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            {"properties": {"id": "sw_repl", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "sw_ret", "snodeid": 2, "enodeid": 50, "direction": 0}, "geometry": LineString([(10, 0), (5, 1)])},
            {"properties": {"id": "sw_adv", "snodeid": 50, "enodeid": 60, "direction": 0, "formway": 128}, "geometry": LineString([(5, 1), (5, 6)])},
            {"properties": {"id": "sw_side", "snodeid": 50, "enodeid": 70, "direction": 0}, "geometry": LineString([(5, 1), (8, 4)])},
        ],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [
            _node(1, 0, mainnodeid=1),
            _node(2, 10, mainnodeid=2),
            {"properties": {"id": 50, "mainnodeid": None, "kind": 1, "grade": 1}, "geometry": Point(5, 1)},
            _node(60, 5, mainnodeid=60),
            _node(70, 8, mainnodeid=70),
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr_main", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])}],
    )
    rcsd_nodes = _write(tmp_path / "rcsdnode_out.gpkg", [_node(10, 0, mainnodeid=10), _node(20, 10, mainnodeid=20)])
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s_repl",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_main"],
                    "retained_node_ids": [10, 20],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["advance_right_contract_retained_candidate_road_count"] == 0
    assert summary["advance_right_contract_swsd_mainnode_normalized_node_count"] == 0
    assert summary["advance_right_contract_swsd_node_snapped_count"] == 0
    assert summary["advance_right_contract_rcsd_node_generated_count"] == 0
    assert summary["advance_right_contract_rcsd_split_original_road_count"] == 0
    assert summary["advance_right_contract_rcsd_split_road_count"] == 0
    assert summary["advance_right_attachment_swsd_mainnode_synced_count"] == 0

    nodes = {(str(item["id"]), item["source"]): item for item in _props(artifacts.frcsd_node_gpkg_path)}
    assert str(nodes[("50", 2)]["mainnodeid"]) in {"50", "None", ""}
    assert ("21", 1) not in nodes

    roads = {str(item["id"]): item for item in _props(artifacts.frcsd_road_gpkg_path)}
    assert "rr_main" in roads
    assert {"sw_ret", "sw_adv", "sw_side"}.issubset(roads)
    assert not {"rr_main__t06advsplit_1", "rr_main__t06advsplit_2"}.intersection(roads)
    road_gdf = gpd.read_file(artifacts.frcsd_road_gpkg_path)
    sw_side_geom = road_gdf.loc[road_gdf["id"].astype(str) == "sw_side"].geometry.iloc[0]
    assert list(sw_side_geom.coords) == [(5.0, 1.0), (8.0, 4.0)]

    audit_rows = _props(artifacts.step_root / "t06_step3_advance_right_attachment_audit.gpkg")
    assert "split_rcsd_road_for_swsd_advance" not in {row["action"] for row in audit_rows}


def test_step3_adds_paired_advance_right_even_when_swsd_advance_duplicate_is_retained(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [{"properties": {"id": "s1", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw1"]}, "geometry": LineString([(0, 0), (10, 0)])}],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            {"properties": {"id": "sw1", "snodeid": 1, "enodeid": 2, "direction": 0, "segmentid": "s1"}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "sw_dup", "snodeid": 101, "enodeid": 102, "direction": 0, "formway": 128}, "geometry": LineString([(10, 10), (12, 12)])},
        ],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [_node(1, 0), _node(2, 10), {"properties": {"id": 101, "mainnodeid": 101}, "geometry": Point(10, 10)}, {"properties": {"id": 102, "mainnodeid": 102}, "geometry": Point(12, 12)}],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr_main", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "adv_seed", "snodeid": 30, "enodeid": 31, "direction": 0, "formway": 128}, "geometry": LineString([(0, 10), (10, 10)])},
            {"properties": {"id": "adv_pair", "snodeid": 31, "enodeid": 32, "direction": 0, "formway": 128}, "geometry": LineString([(10, 10), (12, 12)])},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [_node(10, 0), _node(20, 10), _node(30, 0), _node(31, 10), _node(32, 12)],
    )
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_main", "adv_seed"],
                    "retained_node_ids": [10, 20, 30, 31],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["post_advance_right_paired_advance_road_count"] == 0

    roads = {(item["id"], item["source"]) for item in _props(artifacts.frcsd_road_gpkg_path)}
    assert ("adv_pair", 1) not in roads
    assert ("sw_dup", 2) not in roads


def test_step3_contract_projects_retained_advance_endpoint_from_incident_segment_context(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [{"properties": {"id": "s1", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw_main", "sw_stub"]}, "geometry": LineString([(0, 0), (10, 0)])}],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            {"properties": {"id": "sw_main", "snodeid": 1, "enodeid": 2, "direction": 0, "segmentid": "s1"}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "sw_stub", "snodeid": 50, "enodeid": 2, "direction": 0, "segmentid": "s1"}, "geometry": LineString([(5, 3), (10, 0)])},
            {"properties": {"id": "sw_adv", "snodeid": 50, "enodeid": 60, "direction": 0, "formway": 128}, "geometry": LineString([(5, 3), (20, 0)])},
        ],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [
            _node(1, 0, mainnodeid=1),
            _node(2, 10, mainnodeid=2),
            {"properties": {"id": 50, "mainnodeid": None, "kind": 1, "grade": 1}, "geometry": Point(5, 3)},
            _node(60, 20, mainnodeid=60),
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr_main", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])}],
    )
    rcsd_nodes = _write(tmp_path / "rcsdnode_out.gpkg", [_node(10, 0, mainnodeid=10), _node(20, 10, mainnodeid=20)])
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_main"],
                    "retained_node_ids": [10, 20],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["advance_right_contract_retained_candidate_road_count"] == 1
    assert summary["advance_right_contract_swsd_node_snapped_count"] == 1
    assert summary["advance_right_contract_rcsd_node_generated_count"] == 1
    assert summary["advance_right_contract_rcsd_split_road_count"] == 2

    roads = {str(item["id"]): item for item in _props(artifacts.frcsd_road_gpkg_path)}
    assert "rr_main" not in roads
    assert {"rr_main__t06advsplit_1", "rr_main__t06advsplit_2", "sw_adv"}.issubset(roads)

    road_payload = json.loads(artifacts.frcsd_road_gpkg_path.with_suffix(".json").read_text(encoding="utf-8"))
    sw_adv = next(item for item in road_payload["features"] if item["properties"]["id"] == "sw_adv")
    assert sw_adv["geometry"]["coordinates"][0][:2] == [5.0, 0.0]


def test_step3_splits_selected_advance_right_when_side_road_attaches_to_midpoint(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [{"properties": {"id": "s1", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw1"]}, "geometry": LineString([(0, 0), (10, 0)])}],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [{"properties": {"id": "sw1", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])}])
    swsd_nodes = _write(tmp_path / "swsd_nodes.gpkg", [_node(1, 0), _node(2, 10)])
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr_main", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "advance_seed", "snodeid": 70, "enodeid": 71, "direction": 0, "formway": 128}, "geometry": LineString([(0, 10), (10, 10)])},
            {"properties": {"id": "side_mid", "snodeid": 72, "enodeid": 73, "direction": 0}, "geometry": LineString([(5, 10), (5, 15)])},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [_node(10, 0), _node(20, 10), _node(70, 0), _node(71, 10), _node(72, 5), _node(73, 5)],
    )
    replaceable = _write(
        tmp_path / "t06_rcsd_segment_replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s1",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_main", "advance_seed"],
                    "retained_node_ids": [10, 20, 70, 71],
                    "hard_filter_passed": True,
                },
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
    )

    artifacts = run_t06_step3_segment_replacement(
        step2_replaceable_path=replaceable,
        swsd_segment_path=segment,
        swsd_roads_path=swsd_roads,
        swsd_nodes_path=swsd_nodes,
        rcsdroad_path=rcsd_roads,
        rcsdnode_path=rcsd_nodes,
        out_root=tmp_path / "out",
        run_id="run",
    )

    summary = json.loads(artifacts.summary_path.read_text(encoding="utf-8"))
    assert summary["post_advance_right_midroad_split_original_road_count"] == 0
    assert summary["post_advance_right_midroad_split_road_count"] == 0
    assert summary["post_advance_right_midroad_attached_road_count"] == 0

    roads = {(item["id"], item["source"]) for item in _props(artifacts.frcsd_road_gpkg_path)}
    assert ("advance_seed", 1) in roads
    assert not {("advance_seed__t06advsplit_1", 1), ("advance_seed__t06advsplit_2", 1), ("side_mid", 1)}.intersection(roads)
