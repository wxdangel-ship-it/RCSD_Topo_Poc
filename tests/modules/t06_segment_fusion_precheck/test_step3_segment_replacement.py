from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point, mapping

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector
from rcsd_topo_poc.modules.t06_segment_fusion_precheck import run_t06_step3_segment_replacement


def _write(path: Path, features: list[dict]) -> Path:
    write_vector(path, features, crs_text="EPSG:3857")
    return path


def _road(road_id: str, snode: int | str, enode: int | str):
    return {
        "properties": {"id": road_id, "snodeid": snode, "enodeid": enode, "direction": 0},
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


def test_step3_replaces_roads_endpoint_nodes_only_rebuilds_c_and_audits_id_collisions(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "主双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr1"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "properties": {"id": "s2", "sgrade": "主双", "pair_nodes": [3, 4], "junc_nodes": [], "roads": ["sr2"]},
                "geometry": LineString([(3, 0), (4, 0)]),
            }
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            _road("sr1", 1, 2),
            _road("sr2", 3, 4),
            _road("rr1", 11, 3),
        ],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [
            _node(1, 1, mainnodeid=1, kind=4, grade=7, kind_2=4, grade_2=8, closed_con=9),
            _node(11, 1.1, mainnodeid=1),
            _node(2, 2, mainnodeid=2, kind=8, grade=3, kind_2=16, grade_2=6, closed_con=5),
            _node(3, 3, mainnodeid=0, kind=64, grade=1, kind_2=64, grade_2=1, closed_con=0),
            _node(4, 4, mainnodeid=0, kind=64, grade=1, kind_2=64, grade_2=1, closed_con=0),
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])},
            {"properties": {"id": "rr2", "snodeid": 30, "enodeid": 40, "direction": 0}, "geometry": LineString([(30, 0), (32, 0)])},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            _node(10, 1, mainnodeid=10),
            _node(20, 2, mainnodeid=20),
            _node(201, 2.1, mainnodeid=20),
            _node(30, 30, mainnodeid=30),
            _node(40, 32, mainnodeid=40),
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
                    "rcsd_pair_nodes": [10, 201],
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
    assert summary["removed_swsd_road_count"] == 1
    assert summary["removed_swsd_node_count"] == 2
    assert summary["added_rcsd_road_count"] == 1
    assert summary["added_rcsd_node_count"] == 3
    assert summary["unreplaced_rcsd_road_count"] == 1
    assert summary["unreplaced_rcsd_road_length_m"] == 2.0
    assert summary["junction_c_count"] == 2
    assert summary["road_id_collision_count"] == 1
    assert summary["segment_relation_count"] == 2
    assert summary["segment_relation_replaced_count"] == 1
    assert summary["segment_relation_retained_swsd_count"] == 1
    assert summary["segment_relation_failed_count"] == 0

    roads = _props(artifacts.frcsd_road_gpkg_path)
    assert ("sr1", 2) not in {(item["id"], item["source"]) for item in roads}
    assert {("rr1", 2), ("rr1", 1), ("sr2", 2)}.issubset({(item["id"], item["source"]) for item in roads})

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s1"]["relation_status"] == "replaced"
    assert relations["s1"]["frcsd_road_ids"] == ["rr1"]
    assert relations["s1"]["frcsd_road_source_values"] == [1]
    assert relations["s1"]["source_mix"] == "source_1"
    assert relations["s1"]["swsd_to_frcsd_node_map"][0]["frcsd_node_ids"] == ["10"]
    assert relations["s2"]["relation_status"] == "retained_swsd"
    assert relations["s2"]["frcsd_road_ids"] == ["sr2"]
    assert relations["s2"]["frcsd_road_source_values"] == [2]
    assert relations["s2"]["swsd_to_frcsd_node_map"][0]["mapping_status"] == "identity"

    nodes = _props(artifacts.frcsd_node_gpkg_path)
    by_source_id = {(str(item["source"]), str(item["id"])): item for item in nodes}
    assert ("2", "1") not in by_source_id
    assert ("2", "2") not in by_source_id
    assert by_source_id[("2", "11")]["mainnodeid"] == "11"
    assert by_source_id[("2", "11")]["kind"] == 4
    assert by_source_id[("1", "10")]["mainnodeid"] == "11"
    assert by_source_id[("1", "10")]["grade_2"] == 8
    assert by_source_id[("1", "20")]["mainnodeid"] == "20"
    assert by_source_id[("1", "20")]["kind_2"] == 16
    assert by_source_id[("1", "201")]["mainnodeid"] == "20"

    junctions = {item["junction_c_id"]: item for item in _props(artifacts.junction_rebuild_audit_gpkg_path)}
    assert junctions["1"]["mainnode_selection_reason"] == "remaining_swsd_node_min_id"
    assert junctions["2"]["mainnode_selection_reason"] == "added_rcsd_node_min_id"
    assert set(junctions["2"]["added_rcsd_node_ids"]) == {"20", "201"}
    assert junctions["1"]["removed_swsd_node_ids"] == ["1"]

    collision_payload = json.loads((artifacts.step_root / "t06_step3_id_collision_audit.json").read_text(encoding="utf-8"))
    assert collision_payload["features"][0]["properties"]["entity_id"] == "rr1"

    unreplaced_payload = json.loads((artifacts.step_root / "t06_step3_unreplaced_rcsd_roads.json").read_text(encoding="utf-8"))
    unreplaced_props = unreplaced_payload["features"][0]["properties"]
    assert unreplaced_props["id"] == "rr2"
    assert unreplaced_props["replacement_status"] == "not_replaced"
    assert unreplaced_props["length_m"] == 2.0
    assert Path(summary["outputs"]["unreplaced_rcsd_roads_json"]).exists()


def test_step3_retains_detached_junc_swsd_roads_as_local_carriers(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "0-0双", "pair_nodes": [1, 2], "junc_nodes": [3], "roads": ["main", "side"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            }
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            _road("main", 1, 2),
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
                    "swsd_segment_id": "s1",
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
    assert summary["detached_junc_retained_segment_count"] == 1
    assert summary["detached_junc_retained_swsd_road_count"] == 1
    assert summary["removed_swsd_road_count"] == 1

    roads = _props(artifacts.frcsd_road_gpkg_path)
    assert {("main", 2), ("side", 2), ("rr1", 1)} & {(item["id"], item["source"]) for item in roads} == {
        ("side", 2),
        ("rr1", 1),
    }

    units = _props(artifacts.replacement_units_gpkg_path)
    assert units[0]["detached_junc_nodes"] == ["3"]
    assert units[0]["retained_detached_swsd_road_ids"] == ["side"]
    assert units[0]["removed_swsd_road_ids"] == ["main"]

    relations = _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)
    relation = relations[0]
    assert relation["relation_status"] == "replaced+retained_swsd"
    assert relation["frcsd_road_ids"] == ["rr1", "side"]
    assert relation["frcsd_road_source_values"] == [1, 2]
    assert relation["retained_detached_swsd_road_ids"] == ["side"]
    assert relation["source_mix"] == "source_1+source_2"
    detached_map = [item for item in relation["swsd_to_frcsd_node_map"] if item["swsd_node_id"] == "3"][0]
    assert detached_map["frcsd_node_ids"] == ["3"]
    assert detached_map["mapping_status"] == "identity_retained_swsd"


def test_step3_consumes_path_corridor_group_replacement_audit(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "0-0双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw1"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "properties": {"id": "s2", "sgrade": "0-0双", "pair_nodes": [2, 3], "junc_nodes": [], "roads": ["sw2"]},
                "geometry": LineString([(2, 0), (3, 0)]),
            },
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sw1", 1, 2), _road("sw2", 2, 3)])
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [_node(1, 1, mainnodeid=1), _node(2, 2, mainnodeid=2), _node(3, 3, mainnodeid=3)],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])},
            {"properties": {"id": "rr2", "snodeid": 20, "enodeid": 30, "direction": 0}, "geometry": LineString([(2, 0), (3, 0)])},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [_node(10, 1, mainnodeid=10), _node(20, 2, mainnodeid=20), _node(30, 3, mainnodeid=30)],
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
                "geometry": LineString([(1, 0), (2, 0)]),
            }
        ],
    )
    _write(
        tmp_path / "t06_segment_group_replacement_audit.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s2",
                    "group_probe_status": "passed",
                    "group_probe_repair_owner": "T06_path_corridor_group_replacement",
                    "group_probe_buffer_distance_m": 50.0,
                    "path_corridor_group_segment_ids": ["s1", "s2"],
                    "group_probe_rcsd_road_ids": ["rr1", "rr2"],
                    "rcsd_pair_nodes": [20, 30],
                },
                "geometry": LineString([(1, 0), (3, 0)]),
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
    assert summary["group_replacement_audit_input_row_count"] == 1
    assert summary["group_replacement_passed_row_count"] == 1
    assert summary["group_replacement_plan_count"] == 1
    assert summary["group_replacement_assignment_segment_count"] == 2
    assert summary["group_replacement_created_unit_count"] == 1
    assert summary["replacement_unit_success_count"] == 2
    assert summary["removed_swsd_road_count"] == 2
    assert summary["added_rcsd_road_count"] == 2

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s1"]["relation_status"] == "replaced"
    assert relations["s1"]["relation_reason"] == "group_path_corridor_replacement"
    assert relations["s1"]["frcsd_road_ids"] == ["rr1", "rr2"]
    assert relations["s2"]["relation_status"] == "replaced"
    assert relations["s2"]["rcsd_pair_nodes"] == ["20", "30"]
    assert relations["s2"]["frcsd_road_ids"] == ["rr1", "rr2"]
    assert relations["s2"]["group_replacement_source_segment_ids"] == ["s2"]
    assert "group_path_corridor_replacement" in relations["s2"]["risk_flags"]


def test_step3_consumes_path_corridor_group_from_replacement_plan(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s1", "sgrade": "0-0双", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw1"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "properties": {"id": "s2", "sgrade": "0-0双", "pair_nodes": [2, 3], "junc_nodes": [], "roads": ["sw2"]},
                "geometry": LineString([(2, 0), (3, 0)]),
            },
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sw1", 1, 2), _road("sw2", 2, 3)])
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [_node(1, 1, mainnodeid=1), _node(2, 2, mainnodeid=2), _node(3, 3, mainnodeid=3)],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(1, 0), (2, 0)])},
            {"properties": {"id": "rr2", "snodeid": 20, "enodeid": 30, "direction": 0}, "geometry": LineString([(2, 0), (3, 0)])},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [_node(10, 1, mainnodeid=10), _node(20, 2, mainnodeid=20), _node(30, 3, mainnodeid=30)],
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
                "geometry": LineString([(1, 0), (2, 0)]),
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
                "geometry": LineString([(1, 0), (2, 0)]),
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
                    "retained_node_ids": [10, 20, 30],
                    "rcsd_pair_nodes": [20, 30],
                    "buffer_distances_m": [50.0],
                },
                "geometry": LineString([(1, 0), (3, 0)]),
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
    assert summary["replacement_plan_source"] == "step2_replacement_plan"
    assert summary["input_replacement_plan_count"] == 2
    assert summary["group_replacement_assignment_segment_count"] == 2
    assert summary["group_replacement_created_unit_count"] == 1

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s1"]["frcsd_road_ids"] == ["rr1", "rr2"]
    assert relations["s2"]["relation_status"] == "replaced"
    assert relations["s2"]["relation_reason"] == "group_path_corridor_replacement"


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
