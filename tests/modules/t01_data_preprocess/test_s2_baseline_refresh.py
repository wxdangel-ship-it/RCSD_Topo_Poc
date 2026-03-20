from __future__ import annotations

import csv
import json
from pathlib import Path

from shapely.geometry import LineString, MultiLineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_geojson
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import refresh_s2_baseline


def _node_feature(
    node_id: int,
    x: float,
    y: float,
    *,
    kind: int,
    grade: int,
    mainnodeid: int | None = None,
) -> dict:
    props = {
        "id": node_id,
        "kind": kind,
        "grade": grade,
        "closed_con": 2,
        "mainnodeid": mainnodeid,
    }
    return {"properties": props, "geometry": Point(x, y)}


def _road_feature(
    road_id: str,
    snodeid: int,
    enodeid: int,
    *,
    direction: int = 2,
    formway: int = 0,
    x_offset: float = 0.0,
) -> dict:
    return {
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "formway": formway,
        },
        "geometry": LineString([(x_offset, float(snodeid)), (x_offset + 1.0, float(enodeid))]),
    }


def _load_geojson(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def test_refresh_s2_baseline_writes_node_and_road_fields(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    s2_dir = tmp_path / "baseline" / "S2"
    out_root = tmp_path / "out"
    s2_dir.mkdir(parents=True)

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, kind=4, grade=1),
            _node_feature(101, 0.1, 0.1, kind=0, grade=0, mainnodeid=1),
            _node_feature(2, 10.0, 0.0, kind=4, grade=1),
            _node_feature(3, 3.0, 0.0, kind=7, grade=7),
            _node_feature(4, 4.0, 0.0, kind=8, grade=8),
            _node_feature(5, 5.0, 0.0, kind=9, grade=9),
            _node_feature(6, 6.0, 0.0, kind=6, grade=6),
            _node_feature(7, 7.0, 0.0, kind=4, grade=1),
            _node_feature(8, 8.0, 0.0, kind=4, grade=1),
            _node_feature(9, 4.0, 1.0, kind=0, grade=0),
            _node_feature(10, 5.0, 1.0, kind=0, grade=0),
            _node_feature(11, 5.0, -1.0, kind=0, grade=0),
        ],
    )

    write_geojson(
        road_path,
        [
            _road_feature("s1", 1, 3, x_offset=0.0),
            _road_feature("s2", 3, 4, x_offset=1.0),
            _road_feature("s3", 4, 5, x_offset=2.0),
            _road_feature("s4", 5, 2, x_offset=3.0),
            _road_feature("x1", 3, 6, x_offset=4.0),
            _road_feature("t1", 7, 6, x_offset=5.0),
            _road_feature("t2", 6, 8, x_offset=6.0),
            _road_feature("rt1", 4, 9, formway=128, x_offset=7.0),
            _road_feature("in1", 10, 5, x_offset=8.0),
            _road_feature("out1", 5, 11, x_offset=9.0),
        ],
    )

    write_csv(
        s2_dir / "validated_pairs.csv",
        [
            {
                "pair_id": "S2:1__2",
                "a_node_id": "1",
                "b_node_id": "2",
                "trunk_mode": "counterclockwise_loop",
                "left_turn_excluded_mode": "strict",
                "warning_codes": "",
                "segment_body_road_count": "5",
                "residual_road_count": "0",
            },
            {
                "pair_id": "S2:7__8",
                "a_node_id": "7",
                "b_node_id": "8",
                "trunk_mode": "counterclockwise_loop",
                "left_turn_excluded_mode": "strict",
                "warning_codes": "",
                "segment_body_road_count": "2",
                "residual_road_count": "0",
            },
        ],
        [
            "pair_id",
            "a_node_id",
            "b_node_id",
            "trunk_mode",
            "left_turn_excluded_mode",
            "warning_codes",
            "segment_body_road_count",
            "residual_road_count",
        ],
    )

    write_geojson(
        s2_dir / "segment_body_roads.geojson",
        [
            {
                "properties": {
                    "pair_id": "S2:1__2",
                    "a_node_id": "1",
                    "b_node_id": "2",
                    "validated_status": "validated",
                    "road_ids": ["s1", "s2", "s3", "s4", "x1"],
                    "road_ids_text": "s1,s2,s3,s4,x1",
                },
                "geometry": MultiLineString(
                    [
                        LineString([(0.0, 1.0), (1.0, 3.0)]),
                        LineString([(1.0, 3.0), (2.0, 4.0)]),
                    ]
                ),
            },
            {
                "properties": {
                    "pair_id": "S2:7__8",
                    "a_node_id": "7",
                    "b_node_id": "8",
                    "validated_status": "validated",
                    "road_ids": ["t1", "t2"],
                    "road_ids_text": "t1,t2",
                },
                "geometry": MultiLineString(
                    [
                        LineString([(5.0, 7.0), (6.0, 6.0)]),
                        LineString([(6.0, 6.0), (7.0, 8.0)]),
                    ]
                ),
            },
        ],
    )

    artifacts = refresh_s2_baseline(
        road_path=road_path,
        node_path=node_path,
        s2_path=tmp_path / "baseline",
        out_root=out_root,
        run_id="refresh_case",
    )

    assert artifacts.nodes_path.name == "nodes.geojson"
    assert artifacts.roads_path.name == "roads.geojson"
    assert artifacts.preserved_s2_dir.name == "S2"
    assert (artifacts.preserved_s2_dir / "validated_pairs.csv").is_file()

    summary = artifacts.summary
    assert summary["validated_pair_count"] == 2
    assert summary["segment_body_road_count"] == 7
    assert summary["road_written_s_grade_count"] == 7
    assert summary["road_written_segmentid_count"] == 7
    assert summary["mainnode_pair_endpoint_count"] == 4
    assert summary["mainnode_single_segment_non_intersection_count"] == 1
    assert summary["mainnode_right_turn_only_side_count"] == 1
    assert summary["mainnode_t_like_count"] == 1
    assert summary["multi_segment_mainnode_kept_init_count"] == 1
    assert summary["subnode_kept_init_count"] == 1
    assert summary["preserved_s2_dir"] == str(artifacts.preserved_s2_dir)

    nodes_doc = _load_geojson(artifacts.nodes_path)
    node_props = {str(feature["properties"]["id"]): feature["properties"] for feature in nodes_doc["features"]}
    assert node_props["1"]["grade_2"] == 1
    assert node_props["1"]["kind_2"] == 4
    assert node_props["101"]["grade_2"] == 0
    assert node_props["101"]["kind_2"] == 0
    assert node_props["3"]["grade_2"] == -1
    assert node_props["3"]["kind_2"] == 1
    assert node_props["4"]["grade_2"] == 3
    assert node_props["4"]["kind_2"] == 1
    assert node_props["5"]["grade_2"] == 2
    assert node_props["5"]["kind_2"] == 2048
    assert node_props["6"]["grade_2"] == 6
    assert node_props["6"]["kind_2"] == 6

    roads_doc = _load_geojson(artifacts.roads_path)
    road_props = {str(feature["properties"]["id"]): feature["properties"] for feature in roads_doc["features"]}
    assert road_props["s1"]["s_grade"] == "0-0双"
    assert road_props["s1"]["segmentid"] == "1_2"
    assert road_props["t1"]["segmentid"] == "7_8"
    assert road_props["rt1"]["s_grade"] is None
    assert road_props["rt1"]["segmentid"] is None
    assert road_props["in1"]["s_grade"] is None
    assert road_props["in1"]["segmentid"] is None

    mainnode_rows = {row["mainnode_id"]: row for row in _csv_rows(artifacts.mainnode_table_path)}
    assert mainnode_rows["1"]["applied_rule"] == "validated_pair_endpoint"
    assert mainnode_rows["3"]["applied_rule"] == "single_segment_non_intersection"
    assert mainnode_rows["4"]["applied_rule"] == "right_turn_only_side"
    assert mainnode_rows["5"]["applied_rule"] == "t_like"
    assert mainnode_rows["6"]["applied_rule"] == "multi_segment_kept_init"


def test_refresh_s2_baseline_keeps_roundabout_mainnode_protected(tmp_path: Path) -> None:
    node_path = tmp_path / "working_nodes.geojson"
    road_path = tmp_path / "working_roads.geojson"
    s2_dir = tmp_path / "baseline_roundabout" / "S2"
    out_root = tmp_path / "out_roundabout"
    s2_dir.mkdir(parents=True)

    write_geojson(
        node_path,
        [
            {
                "properties": {
                    "id": 50,
                    "kind": 4,
                    "grade": 1,
                    "kind_2": 64,
                    "grade_2": 1,
                    "closed_con": 2,
                    "mainnodeid": 50,
                },
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {
                    "id": 51,
                    "kind": 0,
                    "grade": 0,
                    "kind_2": 0,
                    "grade_2": 0,
                    "closed_con": 2,
                    "mainnodeid": 50,
                },
                "geometry": Point(0.1, 0.0),
            },
            {
                "properties": {
                    "id": 60,
                    "kind": 4,
                    "grade": 1,
                    "kind_2": 4,
                    "grade_2": 1,
                    "closed_con": 2,
                },
                "geometry": Point(1.0, 0.0),
            },
        ],
    )
    write_geojson(
        road_path,
        [
            {
                "properties": {
                    "id": "r_roundabout_segment",
                    "snodeid": 51,
                    "enodeid": 60,
                    "direction": 2,
                    "formway": 0,
                    "s_grade": None,
                    "segmentid": None,
                },
                "geometry": LineString([(0.1, 0.0), (1.0, 0.0)]),
            }
        ],
    )

    write_csv(
        s2_dir / "validated_pairs.csv",
        [
            {
                "pair_id": "S2:50__60",
                "a_node_id": "50",
                "b_node_id": "60",
                "trunk_mode": "counterclockwise_loop",
                "left_turn_excluded_mode": "strict",
                "warning_codes": "",
                "segment_body_road_count": "1",
                "residual_road_count": "0",
            }
        ],
        [
            "pair_id",
            "a_node_id",
            "b_node_id",
            "trunk_mode",
            "left_turn_excluded_mode",
            "warning_codes",
            "segment_body_road_count",
            "residual_road_count",
        ],
    )
    write_geojson(
        s2_dir / "segment_body_roads.geojson",
        [
            {
                "properties": {
                    "pair_id": "S2:50__60",
                    "a_node_id": "50",
                    "b_node_id": "60",
                    "validated_status": "validated",
                    "road_ids": ["r_roundabout_segment"],
                    "road_ids_text": "r_roundabout_segment",
                },
                "geometry": MultiLineString([LineString([(0.1, 0.0), (1.0, 0.0)])]),
            }
        ],
    )

    artifacts = refresh_s2_baseline(
        road_path=road_path,
        node_path=node_path,
        s2_path=tmp_path / "baseline_roundabout",
        out_root=out_root,
        run_id="refresh_roundabout_case",
        assume_working_layers=True,
    )

    nodes_doc = _load_geojson(artifacts.nodes_path)
    node_props = {str(feature["properties"]["id"]): feature["properties"] for feature in nodes_doc["features"]}
    assert node_props["50"]["grade_2"] == 1
    assert node_props["50"]["kind_2"] == 64

    mainnode_rows = {row["mainnode_id"]: row for row in _csv_rows(artifacts.mainnode_table_path)}
    assert mainnode_rows["50"]["applied_rule"] == "protected_roundabout_mainnode"
