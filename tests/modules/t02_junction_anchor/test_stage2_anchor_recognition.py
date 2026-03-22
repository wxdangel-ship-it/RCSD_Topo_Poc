from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import Point, Polygon

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_geojson
from rcsd_topo_poc.modules.t02_junction_anchor.stage2_anchor_recognition import (
    run_t02_stage2_anchor_recognition,
)


def _load_geojson(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _node_feature(
    node_id: int,
    x: float,
    y: float,
    *,
    mainnodeid: int | None,
    has_evd: str | None,
) -> dict:
    return {
        "properties": {
            "id": node_id,
            "mainnodeid": mainnodeid,
            "has_evd": has_evd,
        },
        "geometry": Point(x, y),
    }


def _intersection_feature(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    *,
    properties: dict | None = None,
) -> dict:
    return {
        "properties": properties or {},
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


def _node_props_by_id(nodes_doc: dict) -> dict[str, dict]:
    return {str(feature["properties"]["id"]): feature["properties"] for feature in nodes_doc["features"]}


def test_stage2_marks_representative_yes_for_single_hit(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersection_path = tmp_path / "intersection.geojson"

    write_geojson(
        nodes_path,
        [
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes"),
            _node_feature(101, 1.0, 0.0, mainnodeid=1, has_evd=None),
            _node_feature(9, 9.0, 9.0, mainnodeid=None, has_evd="no"),
        ],
    )
    write_geojson(
        intersection_path,
        [_intersection_feature(-0.5, -0.5, 1.5, 0.5, properties={"id": "A"})],
    )

    artifacts = run_t02_stage2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersection_path,
        out_root=tmp_path / "out",
        run_id="yes_case",
    )

    assert artifacts.success is True
    nodes_doc = _load_geojson(artifacts.nodes_path)
    node_props_by_id = _node_props_by_id(nodes_doc)
    assert node_props_by_id["1"]["is_anchor"] == "yes"
    assert node_props_by_id["101"]["is_anchor"] is None
    assert node_props_by_id["9"]["is_anchor"] is None

    error1_doc = _load_geojson(artifacts.node_error_1_path)
    error2_doc = _load_geojson(artifacts.node_error_2_path)
    assert error1_doc["features"] == []
    assert error2_doc["features"] == []


def test_stage2_marks_representative_no_when_no_intersection_hits(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersection_path = tmp_path / "intersection.geojson"

    write_geojson(
        nodes_path,
        [
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes"),
            _node_feature(101, 1.0, 0.0, mainnodeid=1, has_evd=None),
        ],
    )
    write_geojson(
        intersection_path,
        [_intersection_feature(10.0, 10.0, 11.0, 11.0, properties={"id": "A"})],
    )

    artifacts = run_t02_stage2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersection_path,
        out_root=tmp_path / "out",
        run_id="no_case",
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    node_props_by_id = _node_props_by_id(nodes_doc)
    assert node_props_by_id["1"]["is_anchor"] == "no"
    assert node_props_by_id["101"]["is_anchor"] is None


def test_stage2_outputs_fail1_and_node_error_1(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersection_path = tmp_path / "intersection.geojson"

    write_geojson(
        nodes_path,
        [
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes"),
            _node_feature(101, 10.0, 0.0, mainnodeid=1, has_evd=None),
        ],
    )
    write_geojson(
        intersection_path,
        [
            _intersection_feature(-0.5, -0.5, 0.5, 0.5, properties={"intersection_id": "A"}),
            _intersection_feature(9.5, -0.5, 10.5, 0.5, properties={}),
        ],
    )

    artifacts = run_t02_stage2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersection_path,
        out_root=tmp_path / "out",
        run_id="fail1_case",
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    node_props_by_id = _node_props_by_id(nodes_doc)
    assert node_props_by_id["1"]["is_anchor"] == "fail1"
    assert node_props_by_id["101"]["is_anchor"] is None

    error1_doc = _load_geojson(artifacts.node_error_1_path)
    assert len(error1_doc["features"]) == 2
    error1_audit = _load_json(artifacts.node_error_1_audit_json_path)
    assert error1_audit["error_count"] == 1
    assert error1_audit["rows"][0]["reason"] == "multiple_intersections_for_group"
    assert error1_audit["rows"][0]["intersection_ids"] == ["feature_index:1", "intersection_id:A"]


def test_stage2_outputs_fail2_and_node_error_2(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersection_path = tmp_path / "intersection.geojson"

    write_geojson(
        nodes_path,
        [
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes"),
            _node_feature(2, 1.0, 0.0, mainnodeid=2, has_evd="yes"),
        ],
    )
    write_geojson(
        intersection_path,
        [_intersection_feature(-1.0, -1.0, 2.0, 1.0, properties={"id": "A"})],
    )

    artifacts = run_t02_stage2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersection_path,
        out_root=tmp_path / "out",
        run_id="fail2_case",
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    node_props_by_id = _node_props_by_id(nodes_doc)
    assert node_props_by_id["1"]["is_anchor"] == "fail2"
    assert node_props_by_id["2"]["is_anchor"] == "fail2"

    error2_doc = _load_geojson(artifacts.node_error_2_path)
    assert len(error2_doc["features"]) == 2
    error2_audit = _load_json(artifacts.node_error_2_audit_json_path)
    assert error2_audit["error_count"] == 2
    assert all(row["reason"] == "intersection_shared_by_multiple_groups" for row in error2_audit["rows"])


def test_stage2_fail2_overrides_fail1_and_keeps_both_error_outputs(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersection_path = tmp_path / "intersection.geojson"

    write_geojson(
        nodes_path,
        [
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes"),
            _node_feature(101, 10.0, 0.0, mainnodeid=1, has_evd=None),
            _node_feature(2, 10.0, 0.2, mainnodeid=2, has_evd="yes"),
        ],
    )
    write_geojson(
        intersection_path,
        [
            _intersection_feature(-0.5, -0.5, 0.5, 0.5, properties={"id": "A"}),
            _intersection_feature(9.5, -0.5, 10.5, 0.5, properties={"id": "B"}),
        ],
    )

    artifacts = run_t02_stage2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersection_path,
        out_root=tmp_path / "out",
        run_id="fail2_over_fail1_case",
    )

    node_props_by_id = _node_props_by_id(_load_geojson(artifacts.nodes_path))
    assert node_props_by_id["1"]["is_anchor"] == "fail2"
    assert node_props_by_id["2"]["is_anchor"] == "fail2"
    assert node_props_by_id["101"]["is_anchor"] is None

    error1_ids = {str(feature["properties"]["id"]) for feature in _load_geojson(artifacts.node_error_1_path)["features"]}
    error2_ids = {str(feature["properties"]["id"]) for feature in _load_geojson(artifacts.node_error_2_path)["features"]}
    assert {"1", "101"}.issubset(error1_ids)
    assert {"1", "101"}.issubset(error2_ids)


def test_stage2_keeps_null_for_has_evd_not_yes_groups(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersection_path = tmp_path / "intersection.geojson"

    write_geojson(
        nodes_path,
        [
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="no"),
            _node_feature(101, 0.2, 0.0, mainnodeid=1, has_evd=None),
        ],
    )
    write_geojson(
        intersection_path,
        [_intersection_feature(-1.0, -1.0, 1.0, 1.0, properties={"id": "A"})],
    )

    artifacts = run_t02_stage2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersection_path,
        out_root=tmp_path / "out",
        run_id="skip_case",
    )

    node_props_by_id = _node_props_by_id(_load_geojson(artifacts.nodes_path))
    assert node_props_by_id["1"]["is_anchor"] is None
    assert node_props_by_id["101"]["is_anchor"] is None
    assert _load_geojson(artifacts.node_error_1_path)["features"] == []
    assert _load_geojson(artifacts.node_error_2_path)["features"] == []


def test_stage2_boundary_touch_counts_as_hit(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersection_path = tmp_path / "intersection.geojson"

    write_geojson(
        nodes_path,
        [_node_feature(1, 1.0, 0.0, mainnodeid=None, has_evd="yes")],
    )
    write_geojson(
        intersection_path,
        [_intersection_feature(0.0, -1.0, 1.0, 1.0, properties={"id": "A"})],
    )

    artifacts = run_t02_stage2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersection_path,
        out_root=tmp_path / "out",
        run_id="boundary_case",
    )

    node_props_by_id = _node_props_by_id(_load_geojson(artifacts.nodes_path))
    assert node_props_by_id["1"]["is_anchor"] == "yes"


def test_stage2_projects_nodes_and_intersections_to_epsg_3857(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersection_path = tmp_path / "intersection.geojson"

    write_geojson(
        nodes_path,
        [_node_feature(1, 0.0, 0.0, mainnodeid=None, has_evd="yes")],
        crs_text="EPSG:4326",
    )
    write_geojson(
        intersection_path,
        [_intersection_feature(-0.01, -0.01, 0.01, 0.01, properties={"id": "A"})],
        crs_text="EPSG:4326",
    )

    artifacts = run_t02_stage2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersection_path,
        out_root=tmp_path / "out",
        run_id="crs_case",
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    assert nodes_doc["crs"]["properties"]["name"] == "EPSG:3857"
    assert _node_props_by_id(nodes_doc)["1"]["is_anchor"] == "yes"


def test_stage2_audits_representative_node_missing(tmp_path: Path) -> None:
    nodes_path = tmp_path / "nodes.geojson"
    intersection_path = tmp_path / "intersection.geojson"

    write_geojson(
        nodes_path,
        [
            _node_feature(700, 0.0, 0.0, mainnodeid=7, has_evd="yes"),
            _node_feature(701, 1.0, 0.0, mainnodeid=7, has_evd=None),
        ],
    )
    write_geojson(
        intersection_path,
        [_intersection_feature(-1.0, -1.0, 2.0, 1.0, properties={"id": "A"})],
    )

    artifacts = run_t02_stage2_anchor_recognition(
        nodes_path=nodes_path,
        intersection_path=intersection_path,
        out_root=tmp_path / "out",
        run_id="missing_rep_case",
    )

    audit_doc = _load_json(artifacts.audit_json_path)
    assert any(row["reason"] == "representative_node_missing" and row["junction_id"] == "7" for row in audit_doc["rows"])
    nodes_doc = _load_geojson(artifacts.nodes_path)
    assert all(feature["properties"]["is_anchor"] is None for feature in nodes_doc["features"])
