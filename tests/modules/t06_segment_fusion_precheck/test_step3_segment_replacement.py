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


def test_generated_attachment_node_inherits_nearby_road_endpoint_mainnode() -> None:
    road = {"properties": {"id": "rr1", "snodeid": 10, "enodeid": 20}, "geometry": LineString([(0, 0), (100, 0)])}
    nodes = {
        "10": _node(10, 0, mainnodeid=100),
        "20": _node(20, 100, mainnodeid=200),
    }

    assert (
        _generated_node_mainnode_id(
            "swsd_mid",
            Point(5, 0),
            context_units=[],
            rcsd_road_id="rr1",
            distance_m=5.0,
            rcsd_road_by_id={"rr1": road},
            rcsd_node_by_id=nodes,
        )
        == "100"
    )
    assert (
        _generated_node_mainnode_id(
            "swsd_mid",
            Point(50, 0),
            context_units=[],
            rcsd_road_id="rr1",
            distance_m=50.0,
            rcsd_road_by_id={"rr1": road},
            rcsd_node_by_id=nodes,
        )
        is None
    )


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
    assert by_source_id[("1", "10")]["mainnodeid"] == 10
    assert by_source_id[("1", "10")]["grade_2"] == 0
    assert by_source_id[("1", "20")]["mainnodeid"] == "20"
    assert by_source_id[("1", "20")]["kind_2"] == 16
    assert by_source_id[("1", "201")]["mainnodeid"] == "20"

    junctions = {item["junction_c_id"]: item for item in _props(artifacts.junction_rebuild_audit_gpkg_path)}
    assert junctions["1"]["mainnode_selection_reason"] == "remaining_swsd_node_min_id+source_boundary_split"
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


def test_step3_splits_mainnode_when_rcsd_replacement_meets_retained_swsd_segment(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_replaced", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr_replaced"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            },
            {
                "properties": {"id": "s_retained", "sgrade": "0-1单", "pair_nodes": [1, 3], "junc_nodes": [], "roads": ["sr_retained"]},
                "geometry": LineString([(1, 0), (3, 0)]),
            },
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr_replaced", 1, 2), _road("sr_retained", 1, 3)])
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [_node(1, 1, mainnodeid=1), _node(2, 2, mainnodeid=2), _node(3, 3, mainnodeid=3)],
    )
    rcsd_roads = _write(tmp_path / "rcsdroad_out.gpkg", [_road("rr_replacement", 10, 20)])
    rcsd_nodes = _write(tmp_path / "rcsdnode_out.gpkg", [_node(10, 1, mainnodeid=100), _node(20, 2, mainnodeid=200)])
    replaceable = _write(
        tmp_path / "replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s_replaced",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [100, 200],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_replacement"],
                    "retained_node_ids": [100, 200],
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

    nodes = {(str(item["id"]), item["source"]): item for item in _props(artifacts.frcsd_node_gpkg_path)}
    assert str(nodes[("1", 2)]["mainnodeid"]) == "1"
    assert str(nodes[("10", 1)]["mainnodeid"]) == "100"

    junctions = {item["junction_c_id"]: item for item in _props(artifacts.junction_rebuild_audit_gpkg_path)}
    assert junctions["1"]["mainnode_selection_reason"] == "original_mainnode_retained+source_boundary_split"


def test_step3_backfills_missing_junction_map_from_peer_segment(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {
                    "id": "s_group",
                    "sgrade": "0-1单",
                    "pair_nodes": [1, 3],
                    "junc_nodes": [2],
                    "roads": ["sr_group"],
                },
                "geometry": LineString([(0, 0), (20, 0)]),
            },
            {
                "properties": {
                    "id": "s_peer",
                    "sgrade": "0-1单",
                    "pair_nodes": [2, 4],
                    "junc_nodes": [],
                    "roads": ["sr_peer"],
                },
                "geometry": LineString([(10, 0), (30, 0)]),
            },
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [_road("sr_group", 1, 3), _road("sr_peer", 2, 4)],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [_node(1, 0, mainnodeid=1), _node(2, 10, mainnodeid=2), _node(3, 20, mainnodeid=3), _node(4, 30, mainnodeid=4)],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            _road("rr_group", 10, 20),
            _road("rr_peer", 20, 40),
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [_node(10, 0, mainnodeid=10), _node(20, 10, mainnodeid=20), _node(40, 30, mainnodeid=40)],
    )
    replaceable = _write(
        tmp_path / "replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s_group",
                    "swsd_pair_nodes": [1, 3],
                    "swsd_junc_nodes": [2],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_group"],
                    "retained_node_ids": [10, 20],
                },
                "geometry": LineString([(0, 0), (20, 0)]),
            },
            {
                "properties": {
                    "swsd_segment_id": "s_peer",
                    "swsd_pair_nodes": [2, 4],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [20, 40],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_peer"],
                    "retained_node_ids": [20, 40],
                },
                "geometry": LineString([(10, 0), (30, 0)]),
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
    group_node_map = {item["swsd_node_id"]: item for item in relations["s_group"]["swsd_to_frcsd_node_map"]}
    assert group_node_map["2"]["mapping_status"] == "peer_mapped"
    assert group_node_map["2"]["frcsd_node_ids"] == ["20"]
    assert "peer_backfilled_junc_node_map" in relations["s_group"]["risk_flags"]


def test_step3_retained_swsd_segment_can_attach_to_selected_rcsd_advance_road(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_replaced", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr_replaced"]},
                "geometry": LineString([(10, 0), (20, 0)]),
            },
            {
                "properties": {"id": "s_replaced_next", "sgrade": "0-1单", "pair_nodes": [2, 5], "junc_nodes": [], "roads": ["sr_replaced_next"]},
                "geometry": LineString([(15, 5), (40, 0)]),
            },
            {
                "properties": {"id": "s_retained", "sgrade": "0-1单", "pair_nodes": [3, 2], "junc_nodes": [], "roads": ["sr_retained"]},
                "geometry": LineString([(0, 0), (15, 5)]),
            },
            {
                "properties": {
                    "id": "s_retained_other",
                    "sgrade": "0-1单",
                    "pair_nodes": [4, 2],
                    "junc_nodes": [],
                    "roads": ["sr_retained_other"],
                },
                "geometry": LineString([(5, 0), (15, 5)]),
            },
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            {"properties": {"id": "sr_replaced", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(10, 0), (20, 0)])},
            {"properties": {"id": "sr_replaced_next", "snodeid": 2, "enodeid": 5, "direction": 0}, "geometry": LineString([(15, 5), (40, 0)])},
            {"properties": {"id": "sr_retained", "snodeid": 3, "enodeid": 2, "direction": 0}, "geometry": LineString([(0, 0), (15, 5)])},
            {
                "properties": {"id": "sr_retained_other", "snodeid": 4, "enodeid": 2, "direction": 0},
                "geometry": LineString([(5, 0), (15, 5)]),
            },
        ],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [
            _node(1, 10, mainnodeid=1),
            {"properties": {"id": 2, "mainnodeid": 2}, "geometry": Point(15, 5)},
            _node(3, 0, mainnodeid=3),
            _node(4, 5, mainnodeid=4),
            _node(5, 40, mainnodeid=5),
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {
                "properties": {"id": "rr_adv", "snodeid": 10, "enodeid": 20, "direction": 0, "formway": 128},
                "geometry": LineString([(10, 0), (20, 0)]),
            },
            {
                "properties": {"id": "rr_main_far", "snodeid": 30, "enodeid": 40, "direction": 0, "formway": 0},
                "geometry": LineString([(30, 0), (40, 0)]),
            },
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            _node(10, 10, mainnodeid=10),
            _node(20, 20, mainnodeid=20),
            _node(30, 30, mainnodeid=30),
            _node(40, 40, mainnodeid=40),
        ],
    )
    replaceable = _write(
        tmp_path / "replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s_replaced",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_main_far", "rr_adv"],
                    "retained_node_ids": [10, 20],
                },
                "geometry": LineString([(10, 0), (20, 0)]),
            },
            {
                "properties": {
                    "swsd_segment_id": "s_replaced_next",
                    "swsd_pair_nodes": [2, 5],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [30, 40],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_main_far"],
                    "retained_node_ids": [30, 40],
                },
                "geometry": LineString([(30, 0), (40, 0)]),
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
    assert summary["retained_swsd_attachment_swsd_node_snapped_count"] == 0
    assert summary["retained_swsd_attachment_rcsd_node_generated_count"] == 0

    audit = _props(artifacts.step_root / "t06_step3_advance_right_attachment_audit.gpkg")
    retained_rows = [
        item for item in audit if item["swsd_advance_road_id"] in {"sr_retained", "sr_retained_other"}
    ]
    assert retained_rows == []

    roads = gpd.read_file(artifacts.frcsd_road_gpkg_path)
    retained = roads[roads.id.astype(str) == "sr_retained"].iloc[0]
    retained_other_parts = roads[roads.id.astype(str).str.startswith("sr_retained_other__t06swsdadvsplit_")]
    assert Point(retained.geometry.coords[-1]).equals(Point(15, 5))
    assert len(retained_other_parts) == 2
    assert set(retained_other_parts["t06_split_original_road_id"].astype(str)) == {"sr_retained_other"}
    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s_retained"]["swsd_to_frcsd_node_map"][1]["mapping_status"] == "identity"
    assert "rr_adv" not in relations["s_retained"]["frcsd_road_ids"]
    closure = _props(artifacts.step_root / "t06_step3_rcsd_advance_right_closure_audit.gpkg")
    assert any(
        item["rcsd_advance_road_id"] == "rr_adv"
        and item["action"] == "split_retained_swsd_road_for_rcsd_advance"
        and item["target_swsd_road_id"] == "sr_retained_other"
        for item in closure
    )


def test_step3_retained_swsd_boundary_uses_semantic_rcsd_node_when_projection_is_far(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_replaced", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sw_repl"]},
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "properties": {"id": "s_retained", "pair_nodes": [2, 3], "junc_nodes": [], "roads": ["sw_ret"]},
                "geometry": LineString([(40, 0), (60, 0)]),
            },
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            {"properties": {"id": "sw_repl", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "sw_ret", "snodeid": 2, "enodeid": 3, "direction": 0}, "geometry": LineString([(40, 0), (60, 0)])},
        ],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [_node(1, 0, mainnodeid=1), _node(2, 40, mainnodeid=2), _node(3, 60, mainnodeid=3)],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [{"properties": {"id": "rr_repl", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])}],
    )
    rcsd_nodes = _write(tmp_path / "rcsdnode_out.gpkg", [_node(10, 0, mainnodeid=10), _node(20, 10, mainnodeid=20)])
    replaceable = _write(
        tmp_path / "replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s_replaced",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_repl"],
                    "retained_node_ids": [10, 20],
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

    audit = [
        item
        for item in _props(artifacts.step_root / "t06_step3_advance_right_attachment_audit.gpkg")
        if item["swsd_advance_road_id"] == "sw_ret" and str(item["swsd_node_id"]) == "2"
    ]
    assert audit == []

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    retained_node_map = {item["swsd_node_id"]: item for item in relations["s_retained"]["swsd_to_frcsd_node_map"]}
    assert retained_node_map["2"]["frcsd_node_ids"] == ["2"]
    assert retained_node_map["2"]["mapping_status"] == "identity"
    assert relations["s_retained"]["risk_flags"] == ["retained_swsd_endpoint_relation_gap_manual_review"]

    nodes = _props(artifacts.frcsd_node_gpkg_path)
    by_source_id = {(str(item["source"]), str(item["id"])): item for item in nodes}
    assert str(by_source_id[("2", "2")]["mainnodeid"]) == "2"


def test_step3_retained_swsd_segment_avoids_isolated_mapped_rcsd_node(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_replaced", "pair_nodes": [1, 2], "junc_nodes": [50], "roads": ["sw_repl"]},
                "geometry": LineString([(100, 0), (110, 0)]),
            },
            {
                "properties": {"id": "s_neighbor", "pair_nodes": [3, 4], "junc_nodes": [], "roads": ["sw_nei"]},
                "geometry": LineString([(0, 0), (10, 0)]),
            },
            {
                "properties": {"id": "s_retained", "pair_nodes": [50, 60], "junc_nodes": [], "roads": ["sw_ret"]},
                "geometry": LineString([(5, 1), (8, 4)]),
            },
        ],
    )
    swsd_roads = _write(
        tmp_path / "swsd_roads.gpkg",
        [
            {"properties": {"id": "sw_repl", "snodeid": 1, "enodeid": 2, "direction": 0}, "geometry": LineString([(100, 0), (110, 0)])},
            {"properties": {"id": "sw_nei", "snodeid": 3, "enodeid": 4, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
            {"properties": {"id": "sw_ret", "snodeid": 50, "enodeid": 60, "direction": 0}, "geometry": LineString([(5, 1), (8, 4)])},
        ],
    )
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [
            _node(1, 100, mainnodeid=1),
            _node(2, 110, mainnodeid=2),
            _node(3, 0, mainnodeid=3),
            _node(4, 10, mainnodeid=4),
            {"properties": {"id": 50, "mainnodeid": 50}, "geometry": Point(5, 1)},
            {"properties": {"id": 60, "mainnodeid": 60}, "geometry": Point(8, 4)},
        ],
    )
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            {"properties": {"id": "rr_far", "snodeid": 10, "enodeid": 20, "direction": 0}, "geometry": LineString([(100, 0), (110, 0)])},
            {"properties": {"id": "rr_global", "snodeid": 30, "enodeid": 40, "direction": 0}, "geometry": LineString([(0, 0), (10, 0)])},
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            _node(10, 100, mainnodeid=10),
            _node(20, 110, mainnodeid=20),
            _node(30, 0, mainnodeid=30),
            _node(40, 10, mainnodeid=40),
            {"properties": {"id": 99, "mainnodeid": 99}, "geometry": Point(5, 1)},
        ],
    )
    replaceable = _write(
        tmp_path / "replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s_replaced",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [50],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [99],
                    "rcsd_road_ids": ["rr_far"],
                    "retained_node_ids": [10, 20, 99],
                },
                "geometry": LineString([(100, 0), (110, 0)]),
            },
            {
                "properties": {
                    "swsd_segment_id": "s_neighbor",
                    "swsd_pair_nodes": [3, 4],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [30, 40],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_global"],
                    "retained_node_ids": [30, 40],
                },
                "geometry": LineString([(0, 0), (10, 0)]),
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
    assert summary["topology_connectivity_patch_road_attachment_fail_count"] == 0

    audit = [
        item
        for item in _props(artifacts.step_root / "t06_step3_advance_right_attachment_audit.gpkg")
        if item["swsd_advance_road_id"] == "sw_ret" and str(item["swsd_node_id"]) == "50"
    ]
    assert audit == []

    split_roads = [
        item
        for item in _props(artifacts.frcsd_road_gpkg_path)
        if item.get("t06_split_original_road_id") == "rr_global"
    ]
    assert split_roads == []


def test_step3_splits_mainnode_when_remaining_swsd_member_and_rcsd_nodes_coexist(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_replaced", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr_replaced"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            }
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr_replaced", 1, 2)])
    swsd_nodes = _write(
        tmp_path / "swsd_nodes.gpkg",
        [
            _node(1, 1, mainnodeid=1),
            _node(2, 2, mainnodeid=2),
            _node(4, 4, mainnodeid=1),
        ],
    )
    rcsd_roads = _write(tmp_path / "rcsdroad_out.gpkg", [_road("rr_replacement", 10, 20)])
    rcsd_nodes = _write(tmp_path / "rcsdnode_out.gpkg", [_node(10, 1, mainnodeid=100), _node(20, 2, mainnodeid=200)])
    replaceable = _write(
        tmp_path / "replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s_replaced",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [100, 200],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_replacement"],
                    "retained_node_ids": [100, 200],
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

    nodes = {(str(item["id"]), item["source"]): item for item in _props(artifacts.frcsd_node_gpkg_path)}
    assert str(nodes[("4", 2)]["mainnodeid"]) == "4"
    assert str(nodes[("10", 1)]["mainnodeid"]) == "100"

    junctions = {item["junction_c_id"]: item for item in _props(artifacts.junction_rebuild_audit_gpkg_path)}
    assert junctions["1"]["mainnode_selection_reason"] == "remaining_swsd_node_min_id+source_boundary_split"


def test_step3_assigns_rcsd_advance_attachment_endpoint_to_rebuilt_mainnode(tmp_path: Path) -> None:
    segment = _write(
        tmp_path / "segment.gpkg",
        [
            {
                "properties": {"id": "s_replaced", "sgrade": "0-1单", "pair_nodes": [1, 2], "junc_nodes": [], "roads": ["sr_replaced"]},
                "geometry": LineString([(1, 0), (2, 0)]),
            }
        ],
    )
    swsd_roads = _write(tmp_path / "swsd_roads.gpkg", [_road("sr_replaced", 1, 2)])
    swsd_nodes = _write(tmp_path / "swsd_nodes.gpkg", [_node(1, 1, mainnodeid=1, kind=4), _node(2, 2, mainnodeid=2)])
    rcsd_roads = _write(
        tmp_path / "rcsdroad_out.gpkg",
        [
            _road("rr_main", 10, 20, formway=1),
            _road("rr_advance", 10, 30, formway=128),
        ],
    )
    rcsd_nodes = _write(
        tmp_path / "rcsdnode_out.gpkg",
        [
            _node(10, 1, mainnodeid=10, kind=4),
            _node(20, 2, mainnodeid=20, kind=4),
            _node(30, 3, mainnodeid=30, kind=16),
        ],
    )
    replaceable = _write(
        tmp_path / "replaceable.gpkg",
        [
            {
                "properties": {
                    "swsd_segment_id": "s_replaced",
                    "swsd_pair_nodes": [1, 2],
                    "swsd_junc_nodes": [],
                    "rcsd_pair_nodes": [10, 20],
                    "rcsd_junc_nodes": [],
                    "rcsd_road_ids": ["rr_main", "rr_advance"],
                    "retained_node_ids": [10, 20, 30],
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

    nodes = {(str(item["id"]), item["source"]): item for item in _props(artifacts.frcsd_node_gpkg_path)}
    assert str(nodes[("10", 1)]["mainnodeid"]) == "10"
    assert str(nodes[("30", 1)]["mainnodeid"]) == "10"
    assert nodes[("30", 1)]["kind"] == 16

    junctions = {item["junction_c_id"]: item for item in _props(artifacts.junction_rebuild_audit_gpkg_path)}
    assert junctions["1"]["advance_attachment_rcsd_node_ids"] == ["30"]


def test_step3_excludes_detached_junc_swsd_roads_from_formal_replacement(tmp_path: Path) -> None:
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
    assert summary["segment_relation_mixed_count"] == 1
    assert summary["detached_junc_retained_swsd_road_count"] == 1
    assert summary["removed_swsd_road_count"] == 1

    roads = _props(artifacts.frcsd_road_gpkg_path)
    assert {("main", 2), ("side", 2), ("rr1", 1)} & {(item["id"], item["source"]) for item in roads} == {
        ("rr1", 1),
        ("side", 2),
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
    assert "retained_swsd_excluded_from_formal_replacement" in relation["risk_flags"]
    identity_maps = [
        item
        for item in relation["swsd_to_frcsd_node_map"]
        if item["mapping_status"] == "identity_retained_swsd"
    ]
    assert identity_maps == [
            {
                "swsd_node_id": "3",
                "frcsd_node_ids": ["3", "10"],
                "node_role": "detached_junc_retained_swsd_node",
                "mapping_status": "identity_retained_swsd",
            }
    ]


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
    assert relations["s1"]["frcsd_road_ids"] == ["rr1"]
    assert relations["s2"]["relation_status"] == "replaced"
    assert relations["s2"]["rcsd_pair_nodes"] == ["20", "30"]
    assert relations["s2"]["frcsd_road_ids"] == ["rr2"]
    assert relations["s2"]["pruned_non_owner_frcsd_road_ids"] == ["rr1"]
    assert summary["final_rcsd_road_multi_segment_assignment_count"] == 0
    assert relations["s2"]["group_replacement_source_segment_ids"] == ["s2"]
    assert "group_path_corridor_replacement" in relations["s2"]["risk_flags"]


def test_step3_legacy_group_audit_does_not_replace_blocked_path_corridor_segment(tmp_path: Path) -> None:
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
    replaceable = _write(tmp_path / "t06_rcsd_segment_replaceable.gpkg", [])
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
                    "path_corridor_blocked_segment_ids": ["s1"],
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
    assert summary["group_replacement_assignment_segment_count"] == 1
    assert summary["group_replacement_created_unit_count"] == 1
    assert summary["removed_swsd_road_count"] == 1

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s1"]["relation_status"] == "retained_swsd"
    assert relations["s1"]["frcsd_road_ids"] == ["sw1"]
    assert relations["s2"]["relation_status"] == "replaced"
    assert relations["s2"]["relation_reason"] == "group_path_corridor_replacement"
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
    assert summary["group_replacement_assignment_segment_count"] == 1
    assert summary["group_replacement_created_unit_count"] == 1

    relations = {item["swsd_segment_id"]: item for item in _props(artifacts.swsd_frcsd_segment_relation_gpkg_path)}
    assert relations["s1"]["frcsd_road_ids"] == ["rr1"]
    assert relations["s2"]["relation_status"] == "replaced"
    assert relations["s2"]["relation_reason"] == "group_path_corridor_replacement"
