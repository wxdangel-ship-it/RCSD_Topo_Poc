from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point

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
