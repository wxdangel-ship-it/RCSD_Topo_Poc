from __future__ import annotations

import json
from pathlib import Path

import fiona
from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_geojson, write_vector
from rcsd_topo_poc.modules.t02_junction_anchor.stage1_drivezone_gate import (
    ALL_D_SGRADE_BUCKET,
    KNOWN_S_GRADE_BUCKETS,
    run_t02_stage1_drivezone_gate,
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


def _node_feature(
    node_id: int,
    x: float,
    y: float,
    *,
    mainnodeid: int | None,
    kind_2: int | None = None,
    grade_2: int | None = None,
) -> dict:
    properties = {
        "id": node_id,
        "mainnodeid": mainnodeid,
    }
    if kind_2 is not None:
        properties["kind_2"] = kind_2
    if grade_2 is not None:
        properties["grade_2"] = grade_2
    return {
        "properties": properties,
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
    assert artifacts.out_root == tmp_path / "out" / "yes_case"
    assert artifacts.progress_path.is_file()
    assert artifacts.perf_json_path.is_file()
    assert artifacts.perf_markers_path.is_file()
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
    assert artifacts.summary["summary_by_s_grade"]["all__d_sgrade"] == {
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
    assert artifacts.summary["summary_by_s_grade"]["all__d_sgrade"] == {
        "segment_count": 2,
        "segment_has_evd_count": 1,
        "junction_count": 2,
        "junction_has_evd_count": 1,
    }


def test_stage1_outputs_all_d_sgrade_with_unique_junction_count(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.geojson"
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"

    write_geojson(
        segment_path,
        [
            _segment_feature("seg-1", pair_nodes="1,2", junc_nodes="", s_grade="0-0双"),
            _segment_feature("seg-2", pair_nodes="1", junc_nodes="", s_grade="0-1双"),
            _segment_feature("seg-3", pair_nodes="3", junc_nodes="", s_grade=""),
        ],
    )
    write_geojson(
        nodes_path,
        [
            _node_feature(1, 0.0, 0.0, mainnodeid=None),
            _node_feature(2, 10.0, 10.0, mainnodeid=None),
            _node_feature(3, 0.5, 0.0, mainnodeid=None),
        ],
    )
    write_geojson(drivezone_path, [_drivezone_feature(-1.0, -1.0, 1.0, 1.0)])

    artifacts = run_t02_stage1_drivezone_gate(
        segment_path=segment_path,
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        out_root=tmp_path / "out",
        run_id="all_d_sgrade_case",
    )

    assert artifacts.summary["summary_by_s_grade"]["0-0双"] == {
        "segment_count": 1,
        "segment_has_evd_count": 0,
        "junction_count": 2,
        "junction_has_evd_count": 1,
    }
    assert artifacts.summary["summary_by_s_grade"]["0-1双"] == {
        "segment_count": 1,
        "segment_has_evd_count": 1,
        "junction_count": 1,
        "junction_has_evd_count": 1,
    }
    assert artifacts.summary["summary_by_s_grade"]["all__d_sgrade"] == {
        "segment_count": 2,
        "segment_has_evd_count": 1,
        "junction_count": 2,
        "junction_has_evd_count": 1,
    }


def test_stage1_outputs_zeroed_all_d_sgrade_when_all_segment_grades_are_empty(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.geojson"
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"

    write_geojson(
        segment_path,
        [
            _segment_feature("seg-1", pair_nodes="1", junc_nodes="", s_grade=""),
            _segment_feature("seg-2", pair_nodes="2", junc_nodes="", s_grade=""),
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
        run_id="all_d_sgrade_zero_case",
    )

    assert artifacts.summary["summary_by_s_grade"]["all__d_sgrade"] == {
        "segment_count": 0,
        "segment_has_evd_count": 0,
        "junction_count": 0,
        "junction_has_evd_count": 0,
    }


def test_stage1_outputs_summary_by_kind_grade_with_unique_junction_counts(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.geojson"
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"
    bucket_0_0, bucket_0_1, bucket_0_2 = KNOWN_S_GRADE_BUCKETS

    write_geojson(
        segment_path,
        [
            _segment_feature("seg-1", pair_nodes="1,2", junc_nodes="", s_grade=bucket_0_0),
            _segment_feature("seg-2", pair_nodes="1", junc_nodes="3", s_grade=bucket_0_1),
            _segment_feature("seg-3", pair_nodes="4", junc_nodes="", s_grade=bucket_0_2),
        ],
    )
    write_geojson(
        nodes_path,
        [
            _node_feature(1, 0.0, 0.0, mainnodeid=None, kind_2=4, grade_2=1),
            _node_feature(2, 10.0, 10.0, mainnodeid=None, kind_2=4, grade_2=2),
            _node_feature(3, 0.5, 0.0, mainnodeid=None, kind_2=2048, grade_2=3),
            _node_feature(4, 0.25, 0.0, mainnodeid=None, kind_2=16, grade_2=0),
            _node_feature(5, 20.0, 20.0, mainnodeid=None, kind_2=32, grade_2=1),
        ],
    )
    write_geojson(drivezone_path, [_drivezone_feature(-1.0, -1.0, 1.0, 1.0)])

    artifacts = run_t02_stage1_drivezone_gate(
        segment_path=segment_path,
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        out_root=tmp_path / "out",
        run_id="kind_summary_case",
    )

    assert artifacts.summary["summary_by_s_grade"][bucket_0_0] == {
        "segment_count": 1,
        "segment_has_evd_count": 0,
        "junction_count": 2,
        "junction_has_evd_count": 1,
    }
    assert artifacts.summary["summary_by_s_grade"][bucket_0_1] == {
        "segment_count": 1,
        "segment_has_evd_count": 1,
        "junction_count": 2,
        "junction_has_evd_count": 2,
    }
    assert artifacts.summary["summary_by_s_grade"][bucket_0_2] == {
        "segment_count": 1,
        "segment_has_evd_count": 1,
        "junction_count": 1,
        "junction_has_evd_count": 1,
    }
    assert artifacts.summary["summary_by_s_grade"][ALL_D_SGRADE_BUCKET] == {
        "segment_count": 3,
        "segment_has_evd_count": 2,
        "junction_count": 4,
        "junction_has_evd_count": 3,
    }
    assert artifacts.summary["summary_by_kind_grade"] == {
        "kind2_4_64_grade2_1": {
            "junction_count": 1,
            "junction_has_evd_count": 1,
        },
        "kind2_4_64_grade2_0_2_3": {
            "junction_count": 1,
            "junction_has_evd_count": 0,
        },
        "kind2_2048": {
            "junction_count": 1,
            "junction_has_evd_count": 1,
        },
        "kind2_8_16": {
            "junction_count": 1,
            "junction_has_evd_count": 1,
        },
    }


def test_stage1_excludes_missing_or_out_of_range_kind_grade_from_formal_buckets(tmp_path: Path) -> None:
    segment_path = tmp_path / "segment.geojson"
    nodes_path = tmp_path / "nodes.geojson"
    drivezone_path = tmp_path / "drivezone.geojson"
    bucket_0_0, _, _ = KNOWN_S_GRADE_BUCKETS

    write_geojson(
        segment_path,
        [
            _segment_feature("seg-1", pair_nodes="1,2,3", junc_nodes="", s_grade=bucket_0_0),
        ],
    )
    write_geojson(
        nodes_path,
        [
            _node_feature(1, 0.0, 0.0, mainnodeid=None, kind_2=4, grade_2=1),
            _node_feature(2, 0.25, 0.0, mainnodeid=None, kind_2=4),
            _node_feature(3, 0.5, 0.0, mainnodeid=None, kind_2=32, grade_2=1),
        ],
    )
    write_geojson(drivezone_path, [_drivezone_feature(-1.0, -1.0, 1.0, 1.0)])

    artifacts = run_t02_stage1_drivezone_gate(
        segment_path=segment_path,
        nodes_path=nodes_path,
        drivezone_path=drivezone_path,
        out_root=tmp_path / "out",
        run_id="kind_grade_unclassified_case",
    )

    assert artifacts.summary["summary_by_s_grade"][bucket_0_0] == {
        "segment_count": 1,
        "segment_has_evd_count": 1,
        "junction_count": 3,
        "junction_has_evd_count": 3,
    }
    assert artifacts.summary["summary_by_kind_grade"] == {
        "kind2_4_64_grade2_1": {
            "junction_count": 1,
            "junction_has_evd_count": 1,
        },
        "kind2_4_64_grade2_0_2_3": {
            "junction_count": 0,
            "junction_has_evd_count": 0,
        },
        "kind2_2048": {
            "junction_count": 0,
            "junction_has_evd_count": 0,
        },
        "kind2_8_16": {
            "junction_count": 0,
            "junction_has_evd_count": 0,
        },
    }


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


def test_stage1_prefers_same_name_gpkg_inputs_over_geojson(tmp_path: Path) -> None:
    segment_geojson_path = tmp_path / "segment.geojson"
    nodes_geojson_path = tmp_path / "nodes.geojson"
    drivezone_geojson_path = tmp_path / "drivezone.geojson"

    write_geojson(segment_geojson_path, [_segment_feature("seg-1", pair_nodes="1", junc_nodes="")])
    write_geojson(
        nodes_geojson_path,
        [_node_feature(1, 50.0, 50.0, mainnodeid=None)],
    )
    write_geojson(
        drivezone_geojson_path,
        [_drivezone_feature(49.0, 49.0, 51.0, 51.0)],
    )

    write_vector(
        tmp_path / "segment.gpkg",
        [_segment_feature("seg-1", pair_nodes="1", junc_nodes="")],
        crs_text="EPSG:3857",
    )
    write_vector(
        tmp_path / "nodes.gpkg",
        [_node_feature(1, 0.0, 0.0, mainnodeid=None)],
        crs_text="EPSG:3857",
    )
    write_vector(
        tmp_path / "drivezone.gpkg",
        [_drivezone_feature(-1.0, -1.0, 1.0, 1.0)],
        crs_text="EPSG:3857",
    )

    artifacts = run_t02_stage1_drivezone_gate(
        segment_path=segment_geojson_path,
        nodes_path=nodes_geojson_path,
        drivezone_path=drivezone_geojson_path,
        out_root=tmp_path / "out",
        run_id="prefer_gpkg_case",
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    assert nodes_doc["features"][0]["properties"]["has_evd"] == "yes"
