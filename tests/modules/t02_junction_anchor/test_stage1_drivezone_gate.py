from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_geojson
from rcsd_topo_poc.modules.t02_junction_anchor.stage1_drivezone_gate import run_t02_stage1_drivezone_gate


def _load_geojson(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _node_feature(node_id: int, x: float, y: float, *, mainnodeid: int | None) -> dict:
    return {
        "properties": {
            "id": node_id,
            "mainnodeid": mainnodeid,
        },
        "geometry": Point(x, y),
    }


def _segment_feature(
    segment_id: str,
    *,
    pair_nodes: str,
    junc_nodes: str,
    s_grade: str = "0-1双",
    grade_field: str = "sgrade",
) -> dict:
    return {
        "properties": {
            "id": segment_id,
            "pair_nodes": pair_nodes,
            "junc_nodes": junc_nodes,
            grade_field: s_grade,
        },
        "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
    }


def _drivezone_feature(min_x: float, min_y: float, max_x: float, max_y: float) -> dict:
    return {
        "properties": {"name": "dz"},
        "geometry": Polygon(
            [
                (min_x, min_y),
                (max_x, min_y),
                (max_x, max_y),
                (min_x, max_y),
                (min_x, min_y),
            ]
        ),
    }


def test_stage1_marks_representative_yes_and_segment_yes(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.geojson"
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"

    write_geojson(segment_path, [_segment_feature("seg-1", pair_nodes="1", junc_nodes="")])
    write_geojson(
        nodes_path,
        [
            _node_feature(1, 0.0, 0.0, mainnodeid=1),
            _node_feature(101, 1.0, 0.0, mainnodeid=1),
            _node_feature(9, 9.0, 9.0, mainnodeid=None),
        ],
    )
    write_geojson(drivezone_path, [_drivezone_feature(-0.5, -0.5, 1.5, 0.5)])

    artifacts = run_t02_stage1_drivezone_gate(
        segment_path=segment_path,
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        out_root=tmp_path / "out",
        run_id="yes_case",
    )

    assert artifacts.success is True
    nodes_doc = _load_geojson(artifacts.nodes_path)
    segment_doc = _load_geojson(artifacts.segment_path)

    node_props_by_id = {str(feature["properties"]["id"]): feature["properties"] for feature in nodes_doc["features"]}
    assert node_props_by_id["1"]["has_evd"] == "yes"
    assert node_props_by_id["101"]["has_evd"] is None
    assert segment_doc["features"][0]["properties"]["has_evd"] == "yes"
    assert artifacts.summary["summary_by_s_grade"]["0-1双"] == {
        "segment_count": 1,
        "segment_has_evd_count": 1,
        "junction_count": 1,
        "junction_has_evd_count": 1,
    }


def test_stage1_marks_representative_no_when_drivezone_misses(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.geojson"
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"

    write_geojson(segment_path, [_segment_feature("seg-1", pair_nodes="1", junc_nodes="")])
    write_geojson(
        nodes_path,
        [
            _node_feature(1, 0.0, 0.0, mainnodeid=1),
            _node_feature(101, 1.0, 0.0, mainnodeid=1),
        ],
    )
    write_geojson(drivezone_path, [_drivezone_feature(10.0, 10.0, 11.0, 11.0)])

    artifacts = run_t02_stage1_drivezone_gate(
        segment_path=segment_path,
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        out_root=tmp_path / "out",
        run_id="no_case",
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    segment_doc = _load_geojson(artifacts.segment_path)
    node_props_by_id = {str(feature["properties"]["id"]): feature["properties"] for feature in nodes_doc["features"]}

    assert node_props_by_id["1"]["has_evd"] == "no"
    assert node_props_by_id["101"]["has_evd"] is None
    assert segment_doc["features"][0]["properties"]["has_evd"] == "no"
    assert artifacts.summary["summary_by_s_grade"]["0-1双"]["junction_has_evd_count"] == 0


def test_stage1_audits_missing_junction_group(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.geojson"
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"

    write_geojson(segment_path, [_segment_feature("seg-1", pair_nodes="", junc_nodes="9")])
    write_geojson(nodes_path, [_node_feature(1, 0.0, 0.0, mainnodeid=None)])
    write_geojson(drivezone_path, [_drivezone_feature(-1.0, -1.0, 1.0, 1.0)])

    artifacts = run_t02_stage1_drivezone_gate(
        segment_path=segment_path,
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        out_root=tmp_path / "out",
        run_id="missing_group_case",
    )

    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert any(row["reason"] == "junction_nodes_not_found" and row["junction_id"] == "9" for row in audit_doc["rows"])
    segment_doc = _load_geojson(artifacts.segment_path)
    assert segment_doc["features"][0]["properties"]["has_evd"] == "no"


def test_stage1_audits_no_target_junctions(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.geojson"
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"

    write_geojson(segment_path, [_segment_feature("seg-1", pair_nodes="", junc_nodes="")])
    write_geojson(nodes_path, [_node_feature(1, 0.0, 0.0, mainnodeid=None)])
    write_geojson(drivezone_path, [_drivezone_feature(-1.0, -1.0, 1.0, 1.0)])

    artifacts = run_t02_stage1_drivezone_gate(
        segment_path=segment_path,
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        out_root=tmp_path / "out",
        run_id="empty_segment_case",
    )

    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert any(row["reason"] == "no_target_junctions" and row["segment_id"] == "seg-1" for row in audit_doc["rows"])
    segment_doc = _load_geojson(artifacts.segment_path)
    assert segment_doc["features"][0]["properties"]["has_evd"] == "no"


def test_stage1_audits_representative_node_missing(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.geojson"
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"

    write_geojson(segment_path, [_segment_feature("seg-1", pair_nodes="7", junc_nodes="")])
    write_geojson(
        nodes_path,
        [
            _node_feature(700, 0.0, 0.0, mainnodeid=7),
            _node_feature(701, 1.0, 0.0, mainnodeid=7),
        ],
    )
    write_geojson(drivezone_path, [_drivezone_feature(-1.0, -1.0, 2.0, 1.0)])

    artifacts = run_t02_stage1_drivezone_gate(
        segment_path=segment_path,
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        out_root=tmp_path / "out",
        run_id="missing_rep_case",
    )

    audit_doc = json.loads(artifacts.audit_json_path.read_text(encoding="utf-8"))
    assert any(
        row["reason"] == "representative_node_missing" and row["junction_id"] == "7"
        for row in audit_doc["rows"]
    )
    nodes_doc = _load_geojson(artifacts.nodes_path)
    assert all(feature["properties"]["has_evd"] is None for feature in nodes_doc["features"])


def test_stage1_supports_s_grade_compatibility(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.geojson"
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"

    write_geojson(
        segment_path,
        [
            _segment_feature("seg-1", pair_nodes="1", junc_nodes="", s_grade="0-0双", grade_field="s_grade"),
            _segment_feature("seg-2", pair_nodes="2", junc_nodes="", s_grade="0-2双", grade_field="sgrade"),
        ],
    )
    write_geojson(
        nodes_path,
        [
            _node_feature(1, 0.0, 0.0, mainnodeid=None),
            _node_feature(2, 10.0, 10.0, mainnodeid=None),
        ],
    )
    write_geojson(drivezone_path, [_drivezone_feature(-1.0, -1.0, 1.0, 1.0)])

    artifacts = run_t02_stage1_drivezone_gate(
        segment_path=segment_path,
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        out_root=tmp_path / "out",
        run_id="sgrade_case",
    )

    assert artifacts.summary["summary_by_s_grade"]["0-0双"]["segment_has_evd_count"] == 1
    assert artifacts.summary["summary_by_s_grade"]["0-2双"]["segment_has_evd_count"] == 0


def test_stage1_projects_nodes_and_drivezone_to_epsg_3857(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.geojson"
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"

    write_geojson(
        segment_path,
        [_segment_feature("seg-1", pair_nodes="1", junc_nodes="")],
        crs_text="EPSG:4326",
    )
    write_geojson(
        nodes_path,
        [_node_feature(1, 0.0, 0.0, mainnodeid=None)],
        crs_text="EPSG:4326",
    )
    write_geojson(
        drivezone_path,
        [_drivezone_feature(-0.01, -0.01, 0.01, 0.01)],
        crs_text="EPSG:4326",
    )

    artifacts = run_t02_stage1_drivezone_gate(
        segment_path=segment_path,
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        out_root=tmp_path / "out",
        run_id="crs_case",
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    assert nodes_doc["crs"]["properties"]["name"] == "EPSG:3857"
    assert nodes_doc["features"][0]["properties"]["has_evd"] == "yes"
