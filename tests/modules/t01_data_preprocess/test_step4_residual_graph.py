from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_geojson
from rcsd_topo_poc.modules.t01_data_preprocess.step4_residual_graph import (
    _parse_segment_body_assignments,
    run_step4_residual_graph,
)


def _node_feature(
    node_id: int,
    x: float,
    y: float,
    *,
    grade: int = 0,
    kind: int = 0,
    grade_2: int,
    kind_2: int,
    closed_con: int,
    mainnodeid: int | None = None,
    working_mainnodeid: int | None = None,
) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": node_id,
            "kind": kind,
            "grade": grade,
            "grade_2": grade_2,
            "kind_2": kind_2,
            "closed_con": closed_con,
            "mainnodeid": mainnodeid,
            "working_mainnodeid": working_mainnodeid,
        },
        "geometry": Point(x, y),
    }


def _road_feature(
    road_id: str,
    snodeid: int,
    enodeid: int,
    direction: int,
    coords: list[list[float]],
    *,
    formway: int = 0,
    road_kind: int = 0,
    segmentid: str | None = None,
    s_grade: str | None = None,
) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "formway": formway,
            "road_kind": road_kind,
            "segmentid": segmentid,
            "s_grade": s_grade,
        },
        "geometry": LineString(coords),
    }


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def _load_geojson(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_step4_residual_graph_constructs_new_segments_and_refreshes_fields(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "S2").mkdir()
    (input_dir / "S2" / "sentinel.txt").write_text("keep", encoding="utf-8")

    node_path = input_dir / "nodes.geojson"
    road_path = input_dir / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, grade_2=2, kind_2=2048, closed_con=2),
            _node_feature(2, 1.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(3, 2.0, 0.0, grade_2=1, kind_2=64, closed_con=2),
            _node_feature(4, 1.0, -1.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(5, 1.0, 2.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(6, 1.2, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(7, -1.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(8, 3.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(300, 6.0, 0.0, grade_2=1, kind_2=4, closed_con=0),
            _node_feature(500, 8.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(501, 9.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(502, 8.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(503, 10.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
        ],
    )

    write_geojson(
        road_path,
        [
            _road_feature("r14", 1, 4, 2, [[0.0, 0.0], [1.0, -1.0]]),
            _road_feature("r43", 4, 3, 2, [[1.0, -1.0], [2.0, 0.0]]),
            _road_feature("r32", 3, 2, 2, [[2.0, 0.0], [1.0, 1.0]]),
            _road_feature("r21", 2, 1, 2, [[1.0, 1.0], [0.0, 0.0]]),
            _road_feature("r25", 2, 5, 2, [[1.0, 1.0], [1.0, 2.0]]),
            _road_feature("r46", 4, 6, 0, [[1.0, -1.0], [1.2, 0.0]]),
            _road_feature("r62", 6, 2, 0, [[1.2, 0.0], [1.0, 1.0]]),
            _road_feature("r17", 1, 7, 0, [[0.0, 0.0], [-1.0, 0.0]]),
            _road_feature("r83", 8, 3, 0, [[3.0, 0.0], [2.0, 0.0]]),
            _road_feature("closed1", 7, 8, 0, [[-1.0, 0.0], [3.0, 0.0]], road_kind=1),
            _road_feature("old1", 500, 501, 0, [[8.0, 0.0], [9.0, 0.0]], segmentid="old_pair", s_grade="0-0\u53cc"),
            _road_feature("tin", 502, 501, 2, [[8.0, 1.0], [9.0, 0.0]]),
            _road_feature("tout", 501, 503, 2, [[9.0, 0.0], [10.0, 1.0]]),
        ],
    )

    artifacts = run_step4_residual_graph(
        road_path=road_path,
        node_path=node_path,
        out_root=out_root,
        run_id="step4_case",
    )

    summary = artifacts.summary
    assert summary["input_mainnode_candidate_count"] == 3
    assert summary["input_seed_count"] == 2
    assert summary["input_terminate_count"] == 2
    assert summary["input_closed_con_filtered_out_count"] == 1
    assert summary["removed_existing_segment_road_count"] == 1
    assert summary["removed_closed_road_count"] == 1
    assert summary["working_graph_road_count"] == 11
    assert summary["step4_candidate_pair_count"] == 1
    assert summary["step4_validated_pair_count"] == 1
    assert summary["step4_new_segment_road_count"] == 4
    assert summary["node_rule_keep_pair_count"] == 1
    assert summary["node_rule_new_t_count"] >= 1

    assert (artifacts.out_root / "STEP4").is_dir()
    assert (artifacts.out_root / "STEP4" / "endpoint_pool.csv").is_file()
    assert (artifacts.out_root / "step4_pair_candidates.csv").is_file()
    assert (artifacts.out_root / "step4_validated_pairs.csv").is_file()
    assert (artifacts.out_root / "step4_segment_body_roads.geojson").is_file()
    assert (artifacts.out_root / "S2" / "sentinel.txt").read_text(encoding="utf-8") == "keep"
    assert artifacts.refreshed_nodes_path.name == "nodes.geojson"
    assert artifacts.refreshed_roads_path.name == "roads.geojson"
    strategy_doc = json.loads((artifacts.out_root / "step4_strategy.json").read_text(encoding="utf-8"))
    assert strategy_doc["through_node_rule"]["disallow_seed_terminate_nodes"] is True
    assert strategy_doc["through_node_rule"]["disallow_null_mainnode_singleton_seed_terminate_nodes"] is True

    validated_rows = _load_csv_rows(artifacts.out_root / "step4_validated_pairs.csv")
    assert [row["pair_id"] for row in validated_rows] == ["STEP4:1__3"]
    working_nodes_doc = _load_geojson(artifacts.out_root / "step4_working_nodes.geojson")
    working_node_props = {str(feature["properties"]["id"]): feature["properties"] for feature in working_nodes_doc["features"]}
    assert working_node_props["3"]["step4_input_kind_2"] == 64
    assert working_node_props["3"]["step4_input_eligible"] is True

    roads_doc = _load_geojson(artifacts.refreshed_roads_path)
    road_props = {str(feature["properties"]["id"]): feature["properties"] for feature in roads_doc["features"]}
    for road_id in ["r14", "r43", "r32", "r21"]:
        assert road_props[road_id]["s_grade"] == "0-1\u53cc"
        assert road_props[road_id]["segmentid"] == "1_3"
    for road_id in ["r46", "r62"]:
        assert road_props[road_id]["segmentid"] in {None, ""}
        assert road_props[road_id]["s_grade"] in {None, ""}
    assert road_props["old1"]["segmentid"] == "old_pair"
    assert road_props["old1"]["s_grade"] == "0-0\u53cc"
    assert road_props["r25"]["segmentid"] in {None, ""}
    assert road_props["r17"]["segmentid"] in {None, ""}
    assert road_props["r83"]["segmentid"] in {None, ""}
    assert road_props["closed1"]["segmentid"] in {None, ""}
    assert road_props["tin"]["segmentid"] in {None, ""}
    assert road_props["tout"]["segmentid"] in {None, ""}

    nodes_doc = _load_geojson(artifacts.refreshed_nodes_path)
    node_props = {str(feature["properties"]["id"]): feature["properties"] for feature in nodes_doc["features"]}
    assert node_props["1"]["grade_2"] == 2
    assert node_props["1"]["kind_2"] == 2048
    assert node_props["3"]["grade_2"] == 1
    assert node_props["3"]["kind_2"] == 64
    assert node_props["501"]["grade_2"] == 3
    assert node_props["501"]["kind_2"] == 2048
    assert node_props["300"]["grade_2"] == 1
    assert node_props["300"]["kind_2"] == 4

    mainnode_rows = {row["mainnode_id"]: row for row in _load_csv_rows(artifacts.mainnode_table_path)}
    assert mainnode_rows["1"]["applied_rule"] == "keep_step4_pair_endpoint"
    assert mainnode_rows["3"]["applied_rule"] == "protected_roundabout_mainnode"
    assert mainnode_rows["501"]["applied_rule"] == "new_t_like"
    assert mainnode_rows["300"]["applied_rule"] == "keep_current"


def test_step4_historical_boundary_is_injected_into_seed_and_terminate(tmp_path: Path) -> None:
    input_dir = tmp_path / "input_hist"
    input_dir.mkdir()
    s2_dir = input_dir / "S2"
    s2_dir.mkdir()
    (s2_dir / "endpoint_pool.csv").write_text(
        "node_id,source_tags\n300,S2\n999,S2\n",
        encoding="utf-8",
    )

    node_path = input_dir / "nodes.geojson"
    road_path = input_dir / "roads.geojson"
    out_root = tmp_path / "out_hist"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, grade_2=2, kind_2=2048, closed_con=2),
            _node_feature(2, 1.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(300, 2.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r12", 1, 2, 0, [[0.0, 0.0], [1.0, 0.0]]),
            _road_feature("r23", 2, 300, 0, [[1.0, 0.0], [2.0, 0.0]]),
        ],
    )

    artifacts = run_step4_residual_graph(
        road_path=road_path,
        node_path=node_path,
        out_root=out_root,
        run_id="step4_hist_seed",
    )

    strategy_doc = json.loads((artifacts.out_root / "step4_strategy.json").read_text(encoding="utf-8"))
    assert strategy_doc["force_seed_node_ids"] == ["300", "999"]
    assert strategy_doc["force_terminate_node_ids"] == ["300", "999"]
    assert strategy_doc["hard_stop_node_ids"] == ["300", "999"]

    working_nodes = _load_geojson(artifacts.out_root / "step4_working_nodes.geojson")
    working_props = {str(feature["properties"]["id"]): feature["properties"] for feature in working_nodes["features"]}
    assert working_props["300"]["step4_input_eligible"] is True
    assert working_props["300"]["step4_historical_boundary"] is True

    validated_rows = _load_csv_rows(artifacts.out_root / "step4_validated_pairs.csv")
    assert {row["pair_id"] for row in validated_rows} == {"STEP4:1__300"}


def test_step4_requires_initialized_working_layers(tmp_path: Path) -> None:
    node_path = tmp_path / "raw_nodes.geojson"
    road_path = tmp_path / "raw_roads.geojson"

    write_geojson(
        node_path,
        [
            {
                "type": "Feature",
                "properties": {"id": 1, "kind": 4, "grade": 1, "closed_con": 2},
                "geometry": Point(0.0, 0.0),
            }
        ],
    )
    write_geojson(
        road_path,
        [
            {
                "type": "Feature",
                "properties": {"id": "r1", "snodeid": 1, "enodeid": 1, "direction": 2, "formway": 0},
                "geometry": LineString([(0.0, 0.0), (0.1, 0.0)]),
            }
        ],
    )

    with pytest.raises(ValueError, match="missing working fields"):
        run_step4_residual_graph(
            road_path=road_path,
            node_path=node_path,
            out_root=tmp_path / "out_invalid",
            run_id="step4_invalid",
        )


def test_step4_segment_body_assignments_suffix_when_colliding_with_existing_segmentid(tmp_path: Path) -> None:
    segment_body_path = tmp_path / "segment_body_roads.geojson"
    write_geojson(
        segment_body_path,
        [
            {
                "properties": {
                    "pair_id": "STEP4:1__3",
                    "a_node_id": "1",
                    "b_node_id": "3",
                    "validated_status": "validated",
                    "road_ids": ["r1", "r2"],
                },
                "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
            }
        ],
    )

    road_to_segmentid, _ = _parse_segment_body_assignments(
        segment_body_path,
        reserved_segmentids={"1_3"},
    )

    assert road_to_segmentid["r1"] == "1_3_1"
    assert road_to_segmentid["r2"] == "1_3_1"
