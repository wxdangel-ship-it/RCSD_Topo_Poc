from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import Point, Polygon

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_geojson
from rcsd_topo_poc.modules.t02_junction_anchor.stage2_anchor_recognition import (
    run_t02_stage2_anchor_recognition,
)


def _load_geojson(path: Path) -> dict:
    if path.suffix.lower() in {".geojson", ".json"}:
        return json.loads(path.read_text(encoding="utf-8"))
    with fiona.open(path) as src:
        return {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
            "features": [
                {
                    "type": "Feature",
                    "properties": dict(feature["properties"]),
                    "geometry": feature["geometry"],
                }
                for feature in src
            ],
        }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _node_feature(
    node_id: int,
    x: float,
    y: float,
    *,
    mainnodeid: int | None,
    has_evd: str | None,
    kind_2: int | None = 4,
    grade_2: int | None = 1,
) -> dict:
    return {
        "properties": {
            "id": node_id,
            "mainnodeid": mainnodeid,
            "has_evd": has_evd,
            "kind_2": kind_2,
            "grade_2": grade_2,
        },
        "geometry": Point(x, y),
    }


def _segment_feature(
    segment_id: str,
    *,
    pair_nodes: str,
    junc_nodes: str,
    s_grade: str | None = "0-0双",
    grade_field: str = "s_grade",
) -> dict:
    properties = {
        "id": segment_id,
        "pair_nodes": pair_nodes,
        "junc_nodes": junc_nodes,
    }
    properties[grade_field] = s_grade
    return {
        "properties": properties,
        "geometry": None,
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


def _run_case(
    tmp_path: Path,
    *,
    nodes: list[dict],
    intersections: list[dict],
    segments: list[dict],
    run_id: str,
    nodes_crs_text: str | None = None,
    intersections_crs_text: str | None = None,
) -> object:
    nodes_path = tmp_path / "nodes.geojson"
    intersection_path = tmp_path / "intersection.geojson"
    segment_path = tmp_path / "segment.geojson"

    write_geojson(nodes_path, nodes, crs_text=nodes_crs_text)
    write_geojson(intersection_path, intersections, crs_text=intersections_crs_text)
    write_geojson(segment_path, segments)

    return run_t02_stage2_anchor_recognition(
        segment_path=segment_path,
        nodes_path=nodes_path,
        intersection_path=intersection_path,
        out_root=tmp_path / "out",
        run_id=run_id,
    )


def test_stage2_marks_representative_yes_for_single_hit(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes"),
            _node_feature(101, 1.0, 0.0, mainnodeid=1, has_evd=None),
            _node_feature(9, 9.0, 9.0, mainnodeid=None, has_evd="no"),
        ],
        intersections=[_intersection_feature(-0.5, -0.5, 1.5, 0.5, properties={"id": "A"})],
        segments=[_segment_feature("seg-1", pair_nodes="1", junc_nodes="")],
        run_id="yes_case",
    )

    assert artifacts.success is True
    nodes_doc = _load_geojson(artifacts.nodes_path)
    node_props_by_id = _node_props_by_id(nodes_doc)
    assert node_props_by_id["1"]["is_anchor"] == "yes"
    assert node_props_by_id["1"]["anchor_reason"] is None
    assert node_props_by_id["101"]["is_anchor"] is None
    assert node_props_by_id["101"]["anchor_reason"] is None
    assert node_props_by_id["9"]["is_anchor"] is None
    assert node_props_by_id["9"]["anchor_reason"] is None

    assert _load_geojson(artifacts.node_error_1_path)["features"] == []
    assert _load_geojson(artifacts.node_error_2_path)["features"] == []


def test_stage2_marks_representative_no_when_no_intersection_hits(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes"),
            _node_feature(101, 1.0, 0.0, mainnodeid=1, has_evd=None),
        ],
        intersections=[_intersection_feature(10.0, 10.0, 11.0, 11.0, properties={"id": "A"})],
        segments=[_segment_feature("seg-1", pair_nodes="1", junc_nodes="")],
        run_id="no_case",
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    node_props_by_id = _node_props_by_id(nodes_doc)
    assert node_props_by_id["1"]["is_anchor"] == "no"
    assert node_props_by_id["1"]["anchor_reason"] is None
    assert node_props_by_id["101"]["is_anchor"] is None
    assert node_props_by_id["101"]["anchor_reason"] is None


def test_stage2_outputs_fail1_and_node_error_1(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes", kind_2=4, grade_2=1),
            _node_feature(101, 10.0, 0.0, mainnodeid=1, has_evd=None, kind_2=None, grade_2=None),
        ],
        intersections=[
            _intersection_feature(-0.5, -0.5, 0.5, 0.5, properties={"intersection_id": "A"}),
            _intersection_feature(9.5, -0.5, 10.5, 0.5, properties={}),
        ],
        segments=[_segment_feature("seg-1", pair_nodes="1", junc_nodes="")],
        run_id="fail1_case",
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    node_props_by_id = _node_props_by_id(nodes_doc)
    assert node_props_by_id["1"]["is_anchor"] == "fail1"
    assert node_props_by_id["1"]["anchor_reason"] is None
    assert node_props_by_id["101"]["is_anchor"] is None
    assert node_props_by_id["101"]["anchor_reason"] is None

    error1_doc = _load_geojson(artifacts.node_error_1_path)
    assert len(error1_doc["features"]) == 2
    error1_audit = _load_json(artifacts.node_error_1_audit_json_path)
    assert error1_audit["error_count"] == 1
    assert error1_audit["rows"][0]["reason"] == "multiple_intersections_for_group"
    assert error1_audit["rows"][0]["intersection_ids"] == ["feature_index:1", "intersection_id:A"]


def test_stage2_single_node_multi_hit_marks_yes_without_node_error_1(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[_node_feature(1, 0.0, 0.0, mainnodeid=None, has_evd="yes", kind_2=4, grade_2=1)],
        intersections=[
            _intersection_feature(-0.5, -0.5, 0.5, 0.5, properties={"id": "A"}),
            _intersection_feature(-1.0, -1.0, 1.0, 1.0, properties={"id": "B"}),
        ],
        segments=[_segment_feature("seg-1", pair_nodes="1", junc_nodes="")],
        run_id="single_node_multi_hit_case",
    )

    node_props_by_id = _node_props_by_id(_load_geojson(artifacts.nodes_path))
    assert node_props_by_id["1"]["is_anchor"] == "yes"
    assert node_props_by_id["1"]["anchor_reason"] is None

    assert _load_geojson(artifacts.node_error_1_path)["features"] == []
    assert _load_json(artifacts.node_error_1_audit_json_path)["error_count"] == 0
    assert _load_geojson(artifacts.node_error_2_path)["features"] == []


def test_stage2_roundabout_group_marks_yes_with_anchor_reason(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes", kind_2=64, grade_2=0),
            _node_feature(101, 10.0, 0.0, mainnodeid=1, has_evd=None, kind_2=None, grade_2=None),
        ],
        intersections=[
            _intersection_feature(-0.5, -0.5, 0.5, 0.5, properties={"id": "A"}),
            _intersection_feature(9.5, -0.5, 10.5, 0.5, properties={"id": "B"}),
        ],
        segments=[_segment_feature("seg-1", pair_nodes="1", junc_nodes="")],
        run_id="roundabout_case",
    )

    node_props_by_id = _node_props_by_id(_load_geojson(artifacts.nodes_path))
    assert node_props_by_id["1"]["is_anchor"] == "yes"
    assert node_props_by_id["1"]["anchor_reason"] == "roundabout"
    assert node_props_by_id["101"]["is_anchor"] is None
    assert node_props_by_id["101"]["anchor_reason"] is None

    assert _load_geojson(artifacts.node_error_1_path)["features"] == []
    assert _load_json(artifacts.node_error_1_audit_json_path)["error_count"] == 0
    assert _load_geojson(artifacts.node_error_2_path)["features"] == []


def test_stage2_t_group_marks_yes_with_anchor_reason(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes", kind_2=2048, grade_2=1),
            _node_feature(101, 10.0, 0.0, mainnodeid=1, has_evd=None, kind_2=None, grade_2=None),
        ],
        intersections=[
            _intersection_feature(-0.5, -0.5, 0.5, 0.5, properties={"id": "A"}),
            _intersection_feature(9.5, -0.5, 10.5, 0.5, properties={"id": "B"}),
        ],
        segments=[_segment_feature("seg-1", pair_nodes="1", junc_nodes="")],
        run_id="t_case",
    )

    node_props_by_id = _node_props_by_id(_load_geojson(artifacts.nodes_path))
    assert node_props_by_id["1"]["is_anchor"] == "yes"
    assert node_props_by_id["1"]["anchor_reason"] == "t"
    assert node_props_by_id["101"]["is_anchor"] is None
    assert node_props_by_id["101"]["anchor_reason"] is None

    assert _load_geojson(artifacts.node_error_1_path)["features"] == []
    assert _load_json(artifacts.node_error_1_audit_json_path)["error_count"] == 0
    assert _load_geojson(artifacts.node_error_2_path)["features"] == []


def test_stage2_outputs_fail2_and_node_error_2(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes"),
            _node_feature(2, 1.0, 0.0, mainnodeid=2, has_evd="yes"),
        ],
        intersections=[_intersection_feature(-1.0, -1.0, 2.0, 1.0, properties={"id": "A"})],
        segments=[_segment_feature("seg-1", pair_nodes="1,2", junc_nodes="")],
        run_id="fail2_case",
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    node_props_by_id = _node_props_by_id(nodes_doc)
    assert node_props_by_id["1"]["is_anchor"] == "fail2"
    assert node_props_by_id["1"]["anchor_reason"] is None
    assert node_props_by_id["2"]["is_anchor"] == "fail2"
    assert node_props_by_id["2"]["anchor_reason"] is None

    error2_doc = _load_geojson(artifacts.node_error_2_path)
    assert len(error2_doc["features"]) == 2
    error2_audit = _load_json(artifacts.node_error_2_audit_json_path)
    assert error2_audit["error_count"] == 2
    assert all(row["reason"] == "intersection_shared_by_multiple_groups" for row in error2_audit["rows"])


def test_stage2_fail2_overrides_fail1_and_keeps_both_error_outputs(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes"),
            _node_feature(101, 10.0, 0.0, mainnodeid=1, has_evd=None, kind_2=None, grade_2=None),
            _node_feature(2, 10.0, 0.2, mainnodeid=2, has_evd="yes"),
        ],
        intersections=[
            _intersection_feature(-0.5, -0.5, 0.5, 0.5, properties={"id": "A"}),
            _intersection_feature(9.5, -0.5, 10.5, 0.5, properties={"id": "B"}),
        ],
        segments=[_segment_feature("seg-1", pair_nodes="1,2", junc_nodes="")],
        run_id="fail2_over_fail1_case",
    )

    node_props_by_id = _node_props_by_id(_load_geojson(artifacts.nodes_path))
    assert node_props_by_id["1"]["is_anchor"] == "fail2"
    assert node_props_by_id["1"]["anchor_reason"] is None
    assert node_props_by_id["2"]["is_anchor"] == "fail2"
    assert node_props_by_id["2"]["anchor_reason"] is None
    assert node_props_by_id["101"]["is_anchor"] is None
    assert node_props_by_id["101"]["anchor_reason"] is None

    error1_ids = {str(feature["properties"]["id"]) for feature in _load_geojson(artifacts.node_error_1_path)["features"]}
    error2_ids = {str(feature["properties"]["id"]) for feature in _load_geojson(artifacts.node_error_2_path)["features"]}
    assert {"1", "101"}.issubset(error1_ids)
    assert {"1", "101"}.issubset(error2_ids)


def test_stage2_fail2_ignores_kind2_1_when_single_group_remains(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=None, has_evd="yes", kind_2=1, grade_2=1),
            _node_feature(2, 0.2, 0.0, mainnodeid=None, has_evd="yes", kind_2=4, grade_2=1),
        ],
        intersections=[_intersection_feature(-1.0, -1.0, 1.0, 1.0, properties={"id": "A"})],
        segments=[_segment_feature("seg-1", pair_nodes="1,2", junc_nodes="")],
        run_id="fail2_ignore_kind1_single_remaining_case",
    )

    node_props_by_id = _node_props_by_id(_load_geojson(artifacts.nodes_path))
    assert node_props_by_id["1"]["is_anchor"] == "yes"
    assert node_props_by_id["1"]["anchor_reason"] is None
    assert node_props_by_id["2"]["is_anchor"] == "yes"
    assert node_props_by_id["2"]["anchor_reason"] is None

    assert _load_geojson(artifacts.node_error_2_path)["features"] == []
    assert _load_json(artifacts.node_error_2_audit_json_path)["error_count"] == 0


def test_stage2_fail2_excludes_kind2_1_groups_from_node_error_2(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=None, has_evd="yes", kind_2=1, grade_2=1),
            _node_feature(2, 0.2, 0.0, mainnodeid=None, has_evd="yes", kind_2=4, grade_2=1),
            _node_feature(3, 0.4, 0.0, mainnodeid=None, has_evd="yes", kind_2=4, grade_2=1),
        ],
        intersections=[_intersection_feature(-1.0, -1.0, 1.0, 1.0, properties={"id": "A"})],
        segments=[_segment_feature("seg-1", pair_nodes="1,2,3", junc_nodes="")],
        run_id="fail2_ignore_kind1_multi_remaining_case",
    )

    node_props_by_id = _node_props_by_id(_load_geojson(artifacts.nodes_path))
    assert node_props_by_id["1"]["is_anchor"] == "yes"
    assert node_props_by_id["1"]["anchor_reason"] is None
    assert node_props_by_id["2"]["is_anchor"] == "fail2"
    assert node_props_by_id["2"]["anchor_reason"] is None
    assert node_props_by_id["3"]["is_anchor"] == "fail2"
    assert node_props_by_id["3"]["anchor_reason"] is None

    error2_ids = {str(feature["properties"]["id"]) for feature in _load_geojson(artifacts.node_error_2_path)["features"]}
    assert error2_ids == {"2", "3"}
    error2_audit = _load_json(artifacts.node_error_2_audit_json_path)
    assert error2_audit["error_count"] == 2
    assert all(row["reason"] == "intersection_shared_by_multiple_groups" for row in error2_audit["rows"])


def test_stage2_fail2_overrides_t_anchor_reason_without_node_error_1(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes", kind_2=2048, grade_2=1),
            _node_feature(101, 10.0, 0.0, mainnodeid=1, has_evd=None, kind_2=None, grade_2=None),
            _node_feature(2, 0.2, 0.0, mainnodeid=2, has_evd="yes", kind_2=4, grade_2=1),
        ],
        intersections=[
            _intersection_feature(-0.5, -0.5, 0.5, 0.5, properties={"id": "A"}),
            _intersection_feature(9.5, -0.5, 10.5, 0.5, properties={"id": "B"}),
        ],
        segments=[_segment_feature("seg-1", pair_nodes="1,2", junc_nodes="")],
        run_id="fail2_over_t_case",
    )

    node_props_by_id = _node_props_by_id(_load_geojson(artifacts.nodes_path))
    assert node_props_by_id["1"]["is_anchor"] == "fail2"
    assert node_props_by_id["1"]["anchor_reason"] is None
    assert node_props_by_id["2"]["is_anchor"] == "fail2"
    assert node_props_by_id["2"]["anchor_reason"] is None
    assert node_props_by_id["101"]["is_anchor"] is None
    assert node_props_by_id["101"]["anchor_reason"] is None

    assert _load_geojson(artifacts.node_error_1_path)["features"] == []
    error2_ids = {str(feature["properties"]["id"]) for feature in _load_geojson(artifacts.node_error_2_path)["features"]}
    assert {"1", "101", "2"}.issubset(error2_ids)


def test_stage2_keeps_null_for_has_evd_not_yes_groups(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="no"),
            _node_feature(101, 0.2, 0.0, mainnodeid=1, has_evd=None),
        ],
        intersections=[_intersection_feature(-1.0, -1.0, 1.0, 1.0, properties={"id": "A"})],
        segments=[_segment_feature("seg-1", pair_nodes="1", junc_nodes="")],
        run_id="skip_case",
    )

    node_props_by_id = _node_props_by_id(_load_geojson(artifacts.nodes_path))
    assert node_props_by_id["1"]["is_anchor"] is None
    assert node_props_by_id["1"]["anchor_reason"] is None
    assert node_props_by_id["101"]["is_anchor"] is None
    assert node_props_by_id["101"]["anchor_reason"] is None
    assert _load_geojson(artifacts.node_error_1_path)["features"] == []
    assert _load_geojson(artifacts.node_error_2_path)["features"] == []


def test_stage2_accepts_semantic_only_divmerge_group_when_it_meets_anchor_rule(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes", kind_2=4, grade_2=1),
            _node_feature(16, 20.0, 0.0, mainnodeid=None, has_evd="yes", kind_2=16, grade_2=0),
        ],
        intersections=[
            _intersection_feature(-0.5, -0.5, 0.5, 0.5, properties={"id": "A"}),
            _intersection_feature(19.5, -0.5, 20.5, 0.5, properties={"id": "B"}),
        ],
        segments=[_segment_feature("seg-1", pair_nodes="1", junc_nodes="")],
        run_id="semantic_only_divmerge_stage4_defer_case",
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    node_props_by_id = _node_props_by_id(nodes_doc)
    assert node_props_by_id["1"]["is_anchor"] == "yes"
    assert node_props_by_id["16"]["is_anchor"] == "yes"
    assert node_props_by_id["16"]["anchor_reason"] is None

    audit_doc = _load_json(artifacts.audit_json_path)
    assert not any(row["junction_id"] == "16" for row in audit_doc["rows"])
    summary_doc = _load_json(artifacts.summary_path)
    assert summary_doc["counts"]["segment_referenced_junction_count"] == 1
    assert summary_doc["counts"]["semantic_candidate_junction_count"] == 2
    assert summary_doc["counts"]["semantic_only_candidate_junction_count"] == 1
    assert summary_doc["counts"]["stage2_anchor_domain_group_count"] == 2
    assert summary_doc["anchor_summary_by_kind_grade"]["kind2_8_16"] == {
        "evidence_junction_count": 1,
        "anchored_junction_count": 1,
    }


def test_stage2_boundary_touch_counts_as_hit(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[_node_feature(1, 1.0, 0.0, mainnodeid=None, has_evd="yes")],
        intersections=[_intersection_feature(0.0, -1.0, 1.0, 1.0, properties={"id": "A"})],
        segments=[_segment_feature("seg-1", pair_nodes="1", junc_nodes="")],
        run_id="boundary_case",
    )

    node_props_by_id = _node_props_by_id(_load_geojson(artifacts.nodes_path))
    assert node_props_by_id["1"]["is_anchor"] == "yes"
    assert node_props_by_id["1"]["anchor_reason"] is None


def test_stage2_projects_nodes_and_intersections_to_epsg_3857(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[_node_feature(1, 0.0, 0.0, mainnodeid=None, has_evd="yes")],
        intersections=[_intersection_feature(-0.01, -0.01, 0.01, 0.01, properties={"id": "A"})],
        segments=[_segment_feature("seg-1", pair_nodes="1", junc_nodes="", grade_field="sgrade")],
        run_id="crs_case",
        nodes_crs_text="EPSG:4326",
        intersections_crs_text="EPSG:4326",
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    assert nodes_doc["crs"]["properties"]["name"] == "EPSG:3857"
    assert _node_props_by_id(nodes_doc)["1"]["is_anchor"] == "yes"
    assert _node_props_by_id(nodes_doc)["1"]["anchor_reason"] is None


def test_stage2_audits_representative_node_missing(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(700, 0.0, 0.0, mainnodeid=7, has_evd="yes"),
            _node_feature(701, 1.0, 0.0, mainnodeid=7, has_evd=None, kind_2=None, grade_2=None),
        ],
        intersections=[_intersection_feature(-1.0, -1.0, 2.0, 1.0, properties={"id": "A"})],
        segments=[_segment_feature("seg-1", pair_nodes="7", junc_nodes="")],
        run_id="missing_rep_case",
    )

    audit_doc = _load_json(artifacts.audit_json_path)
    assert any(row["reason"] == "representative_node_missing" and row["junction_id"] == "7" for row in audit_doc["rows"])
    nodes_doc = _load_geojson(artifacts.nodes_path)
    assert all(feature["properties"]["is_anchor"] is None for feature in nodes_doc["features"])
    assert all(feature["properties"].get("anchor_reason") is None for feature in nodes_doc["features"])


def test_stage2_outputs_anchor_summaries_without_changing_error_outputs(tmp_path: Path) -> None:
    artifacts = _run_case(
        tmp_path,
        nodes=[
            _node_feature(1, 0.0, 0.0, mainnodeid=1, has_evd="yes", kind_2=4, grade_2=1),
            _node_feature(2, 10.0, 0.0, mainnodeid=2, has_evd="yes", kind_2=64, grade_2=0),
            _node_feature(3, 20.0, 0.0, mainnodeid=3, has_evd="yes", kind_2=2048, grade_2=1),
            _node_feature(103, 30.0, 0.0, mainnodeid=3, has_evd=None, kind_2=None, grade_2=None),
            _node_feature(4, 40.0, 0.0, mainnodeid=4, has_evd="yes", kind_2=8, grade_2=1),
            _node_feature(6, 40.2, 0.0, mainnodeid=6, has_evd="yes", kind_2=16, grade_2=1),
            _node_feature(5, 60.0, 0.0, mainnodeid=5, has_evd="yes", kind_2=None, grade_2=None),
        ],
        intersections=[
            _intersection_feature(-0.5, -0.5, 0.5, 0.5, properties={"id": "A"}),
            _intersection_feature(19.5, -0.5, 20.5, 0.5, properties={"id": "C"}),
            _intersection_feature(29.5, -0.5, 30.5, 0.5, properties={"id": "D"}),
            _intersection_feature(39.5, -0.5, 40.5, 0.5, properties={"id": "E"}),
            _intersection_feature(59.5, -0.5, 60.5, 0.5, properties={"id": "F"}),
        ],
        segments=[
            _segment_feature("seg-a", pair_nodes="1", junc_nodes="", s_grade="0-0双"),
            _segment_feature("seg-b", pair_nodes="2", junc_nodes="3", s_grade="0-1双"),
            _segment_feature("seg-c", pair_nodes="4", junc_nodes="", s_grade="0-2双"),
            _segment_feature("seg-d", pair_nodes="", junc_nodes="5", s_grade="0-2双"),
        ],
        run_id="summary_case",
    )

    summary_doc = _load_json(artifacts.summary_path)
    assert "anchor_summary_by_s_grade" in summary_doc
    assert "anchor_summary_by_kind_grade" in summary_doc
    nodes_doc = _load_geojson(artifacts.nodes_path)
    node_props_by_id = _node_props_by_id(nodes_doc)
    assert node_props_by_id["4"]["is_anchor"] == "fail2"
    assert node_props_by_id["6"]["is_anchor"] == "fail2"

    s_grade_summary = summary_doc["anchor_summary_by_s_grade"]
    assert s_grade_summary["0-0双"] == {
        "total_segment_count": 1,
        "pair_nodes_all_anchor_segment_count": 1,
        "pair_and_junc_nodes_all_anchor_segment_count": 1,
    }
    assert s_grade_summary["0-1双"] == {
        "total_segment_count": 1,
        "pair_nodes_all_anchor_segment_count": 0,
        "pair_and_junc_nodes_all_anchor_segment_count": 0,
    }
    assert s_grade_summary["0-2双"] == {
        "total_segment_count": 2,
        "pair_nodes_all_anchor_segment_count": 0,
        "pair_and_junc_nodes_all_anchor_segment_count": 1,
    }
    assert s_grade_summary["all__d_sgrade"] == {
        "total_segment_count": 4,
        "pair_nodes_all_anchor_segment_count": 1,
        "pair_and_junc_nodes_all_anchor_segment_count": 2,
    }

    kind_grade_summary = summary_doc["anchor_summary_by_kind_grade"]
    assert kind_grade_summary["kind2_4_64_grade2_1"] == {
        "evidence_junction_count": 1,
        "anchored_junction_count": 1,
    }
    assert kind_grade_summary["kind2_4_64_grade2_0_2_3"] == {
        "evidence_junction_count": 1,
        "anchored_junction_count": 0,
    }
    assert kind_grade_summary["kind2_2048"] == {
        "evidence_junction_count": 1,
        "anchored_junction_count": 1,
    }
    assert kind_grade_summary["kind2_8_16"] == {
        "evidence_junction_count": 2,
        "anchored_junction_count": 0,
    }
    assert summary_doc["counts"]["segment_referenced_junction_count"] == 5
    assert summary_doc["counts"]["semantic_candidate_junction_count"] == 5
    assert summary_doc["counts"]["semantic_only_candidate_junction_count"] == 1
    assert summary_doc["counts"]["stage2_anchor_domain_group_count"] == 6
    assert summary_doc["counts"]["evidence_junction_count"] == 5
    assert summary_doc["counts"]["anchored_junction_count"] == 2
    assert summary_doc["counts"]["unclassified_kind_grade_junction_count"] == 1

    assert len(_load_geojson(artifacts.node_error_1_path)["features"]) == 0
    assert len(_load_geojson(artifacts.node_error_2_path)["features"]) == 2
