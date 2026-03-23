from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_geojson
from rcsd_topo_poc.modules.t01_data_preprocess.s2_baseline_refresh import NodeFeatureRecord, RoadFeatureRecord
from rcsd_topo_poc.modules.t01_data_preprocess.step5_staged_residual_graph import (
    PhaseInputArtifacts,
    _build_step5c_adaptive_context,
    _run_phase,
    run_step5_staged_residual_graph,
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
    segmentid: str | None = None,
    sgrade: str | None = None,
) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "formway": formway,
            "segmentid": segmentid,
            "sgrade": sgrade,
        },
        "geometry": LineString(coords),
    }


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def _load_geojson(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _node_record(feature: dict) -> NodeFeatureRecord:
    props = dict(feature["properties"])
    node_id = str(props["id"])
    mainnodeid = props.get("working_mainnodeid")
    if mainnodeid in {None, ""}:
        mainnodeid = props.get("mainnodeid")
    semantic_node_id = str(mainnodeid) if mainnodeid not in {None, ""} else node_id
    return NodeFeatureRecord(
        node_id=node_id,
        mainnodeid=str(mainnodeid) if mainnodeid not in {None, ""} else None,
        semantic_node_id=semantic_node_id,
        grade=props.get("grade"),
        kind=props.get("kind"),
        properties=props,
        geometry=feature["geometry"],
    )


def _road_record(feature: dict) -> RoadFeatureRecord:
    props = dict(feature["properties"])
    return RoadFeatureRecord(
        road_id=str(props["id"]),
        snodeid=str(props["snodeid"]),
        enodeid=str(props["enodeid"]),
        direction=int(props["direction"]),
        formway=props.get("formway"),
        road_kind=props.get("road_kind"),
        properties=props,
        geometry=feature["geometry"],
    )


def test_step5_staged_residual_graph_runs_two_phases_and_refreshes_once(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    (input_dir / "S2").mkdir()
    (input_dir / "STEP4").mkdir()
    (input_dir / "S2" / "sentinel.txt").write_text("s2", encoding="utf-8")
    (input_dir / "STEP4" / "sentinel.txt").write_text("step4", encoding="utf-8")

    node_path = input_dir / "nodes.geojson"
    road_path = input_dir / "roads.geojson"
    out_root = tmp_path / "out"

    write_geojson(
        node_path,
        [
            _node_feature(10, 0.0, 0.0, grade_2=2, kind_2=2048, closed_con=2),
            _node_feature(20, 1.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(30, 2.0, 0.0, grade_2=1, kind_2=64, closed_con=2),
            _node_feature(40, 1.0, -1.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(60, 1.2, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(70, -1.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(80, 3.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(110, 10.0, 0.0, grade_2=3, kind_2=2048, closed_con=2),
            _node_feature(120, 11.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(130, 12.0, 0.0, grade_2=3, kind_2=2048, closed_con=2),
            _node_feature(140, 11.0, -1.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(160, 11.2, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(170, 9.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(180, 13.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(500, 20.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(501, 21.0, 0.0, grade_2=0, kind_2=0, closed_con=2),
            _node_feature(502, 20.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(503, 22.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(210, 30.0, 0.0, grade_2=2, kind_2=1, closed_con=2),
            _node_feature(220, 31.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(230, 32.0, 0.0, grade_2=3, kind_2=1, closed_con=2),
            _node_feature(240, 31.0, -1.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(260, 31.2, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(270, 29.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(280, 33.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
        ],
    )

    write_geojson(
        road_path,
        [
            _road_feature("a14", 10, 40, 2, [[0.0, 0.0], [1.0, -1.0]]),
            _road_feature("a43", 40, 30, 2, [[1.0, -1.0], [2.0, 0.0]]),
            _road_feature("a32", 30, 20, 2, [[2.0, 0.0], [1.0, 1.0]]),
            _road_feature("a21", 20, 10, 2, [[1.0, 1.0], [0.0, 0.0]]),
            _road_feature("a46", 40, 60, 0, [[1.0, -1.0], [1.2, 0.0]]),
            _road_feature("a62", 60, 20, 0, [[1.2, 0.0], [1.0, 1.0]]),
            _road_feature("a10x", 10, 70, 0, [[0.0, 0.0], [-1.0, 0.0]]),
            _road_feature("a30x", 80, 30, 0, [[3.0, 0.0], [2.0, 0.0]]),
            _road_feature("b14", 110, 140, 2, [[10.0, 0.0], [11.0, -1.0]]),
            _road_feature("b43", 140, 130, 2, [[11.0, -1.0], [12.0, 0.0]]),
            _road_feature("b32", 130, 120, 2, [[12.0, 0.0], [11.0, 1.0]]),
            _road_feature("b21", 120, 110, 2, [[11.0, 1.0], [10.0, 0.0]]),
            _road_feature("b46", 140, 160, 0, [[11.0, -1.0], [11.2, 0.0]]),
            _road_feature("b62", 160, 120, 0, [[11.2, 0.0], [11.0, 1.0]]),
            _road_feature("b10x", 110, 170, 0, [[10.0, 0.0], [9.0, 0.0]]),
            _road_feature("b30x", 180, 130, 0, [[13.0, 0.0], [12.0, 0.0]]),
            _road_feature("old1", 500, 501, 0, [[20.0, 0.0], [21.0, 0.0]], segmentid="old_pair", sgrade="0-1双"),
            _road_feature("tin", 502, 501, 2, [[20.0, 1.0], [21.0, 0.0]]),
            _road_feature("tout", 501, 503, 2, [[21.0, 0.0], [22.0, 1.0]]),
            _road_feature("c14", 210, 240, 2, [[30.0, 0.0], [31.0, -1.0]]),
            _road_feature("c43", 240, 230, 2, [[31.0, -1.0], [32.0, 0.0]]),
            _road_feature("c32", 230, 220, 2, [[32.0, 0.0], [31.0, 1.0]]),
            _road_feature("c21", 220, 210, 2, [[31.0, 1.0], [30.0, 0.0]]),
            _road_feature("c46", 240, 260, 0, [[31.0, -1.0], [31.2, 0.0]]),
            _road_feature("c62", 260, 220, 0, [[31.2, 0.0], [31.0, 1.0]]),
            _road_feature("c10x", 210, 270, 0, [[30.0, 0.0], [29.0, 0.0]]),
            _road_feature("c30x", 280, 230, 0, [[33.0, 0.0], [32.0, 0.0]]),
        ],
    )

    artifacts = run_step5_staged_residual_graph(
        road_path=road_path,
        node_path=node_path,
        out_root=out_root,
        run_id="step5_case",
    )

    summary = artifacts.summary
    assert summary["step5a_input_node_count"] == 2
    assert summary["step5a_seed_count"] == 2
    assert summary["step5a_terminate_count"] == 2
    assert summary["step5a_validated_pair_count"] == 1
    assert summary["step5a_new_segment_road_count"] == 4
    assert summary["step5b_input_node_count"] == 4
    assert summary["step5b_seed_count"] == 4
    assert summary["step5b_terminate_count"] == 4
    assert summary["step5b_validated_pair_count"] == 1
    assert summary["step5b_new_segment_road_count"] == 4
    assert summary["step5c_input_node_count"] == 4
    assert summary["step5c_seed_count"] == 4
    assert summary["step5c_terminate_count"] == 4
    assert summary["step5c_validated_pair_count"] == 0
    assert summary["step5c_new_segment_road_count"] == 0
    assert summary["step5_removed_historical_segment_road_count"] == 1
    assert summary["step5_removed_step5a_segment_road_count"] == 4
    assert summary["step5_removed_step5b_segment_road_count"] == 4
    assert summary["step5_total_new_segment_road_count"] == 8
    assert summary["node_rule_keep_pair_count"] == 3
    assert summary["node_rule_new_t_count"] >= 1
    assert summary["step5c_rolling_endpoint_pool_count"] == 4
    assert summary["step5c_protected_hard_stop_count"] == 1
    assert summary["step5c_demoted_endpoint_count"] == 0
    assert summary["step5c_actual_barrier_count"] == 4

    assert (artifacts.out_root / "S2" / "sentinel.txt").read_text(encoding="utf-8") == "s2"
    assert (artifacts.out_root / "STEP4" / "sentinel.txt").read_text(encoding="utf-8") == "step4"
    assert (artifacts.out_root / "STEP5A").is_dir()
    assert (artifacts.out_root / "STEP5B").is_dir()
    assert (artifacts.out_root / "STEP5C").is_dir()
    assert artifacts.refreshed_nodes_alias_path.name == "nodes_step5_refreshed.geojson"
    assert artifacts.refreshed_roads_alias_path.name == "roads_step5_refreshed.geojson"
    step5a_strategy = json.loads((artifacts.out_root / "step5a_strategy.json").read_text(encoding="utf-8"))
    step5b_strategy = json.loads((artifacts.out_root / "step5b_strategy.json").read_text(encoding="utf-8"))
    step5c_strategy = json.loads((artifacts.out_root / "step5c_strategy.json").read_text(encoding="utf-8"))
    step5a_endpoint_pool_rows = _load_csv_rows(artifacts.out_root / "STEP5A" / "endpoint_pool.csv")
    step5b_endpoint_pool_rows = _load_csv_rows(artifacts.out_root / "STEP5B" / "endpoint_pool.csv")
    assert step5a_strategy["through_node_rule"]["disallow_seed_terminate_nodes"] is True
    assert step5b_strategy["through_node_rule"]["disallow_seed_terminate_nodes"] is True
    assert step5c_strategy["through_node_rule"]["disallow_seed_terminate_nodes"] is True
    assert step5b_strategy["force_seed_node_ids"] == [row["node_id"] for row in step5a_endpoint_pool_rows]
    assert step5b_strategy["force_terminate_node_ids"] == [row["node_id"] for row in step5a_endpoint_pool_rows]
    assert step5c_strategy["force_seed_node_ids"] == [row["node_id"] for row in step5b_endpoint_pool_rows]
    assert step5c_strategy["force_terminate_node_ids"] == [row["node_id"] for row in step5b_endpoint_pool_rows]
    assert step5c_strategy["hard_stop_node_ids"] == ["30"]
    assert step5c_strategy["through_node_rule"]["retain_seed_node_ids_as_through_node_ids"] == []
    assert step5c_strategy["through_node_rule"]["allow_seed_search_when_through"] is True
    assert step5c_strategy["hard_stop_node_ids"] == ["30"]

    step5a_rows = _load_csv_rows(artifacts.out_root / "step5a_validated_pairs.csv")
    step5b_rows = _load_csv_rows(artifacts.out_root / "step5b_validated_pairs.csv")
    step5c_rows = _load_csv_rows(artifacts.out_root / "step5c_validated_pairs.csv")
    merged_rows = _load_csv_rows(artifacts.out_root / "step5_validated_pairs_merged.csv")
    assert [row["pair_id"] for row in step5a_rows] == ["STEP5A:10__30"]
    assert [row["pair_id"] for row in step5b_rows] == ["STEP5B:110__130"]
    assert step5c_rows == []
    assert {row["pair_id"] for row in merged_rows} == {"STEP5A:10__30", "STEP5B:110__130"}

    step5b_working_roads = _load_geojson(artifacts.out_root / "step5b_working_roads.geojson")
    step5b_working_road_ids = {str(feature["properties"]["id"]) for feature in step5b_working_roads["features"]}
    assert {"a14", "a43", "a32", "a21"}.isdisjoint(step5b_working_road_ids)
    step5b_working_nodes = _load_geojson(artifacts.out_root / "step5b_working_nodes.geojson")
    step5b_node_props = {str(feature["properties"]["id"]): feature["properties"] for feature in step5b_working_nodes["features"]}
    assert step5b_node_props["10"]["step5b_historical_boundary"] is True
    assert step5b_node_props["30"]["step5b_historical_boundary"] is True
    assert step5b_node_props["10"]["step5b_input_eligible"] is True
    assert step5b_node_props["30"]["step5b_input_eligible"] is True
    assert step5b_node_props["501"]["step5b_input_eligible"] is False

    step5c_working_roads = _load_geojson(artifacts.out_root / "step5c_working_roads.geojson")
    step5c_working_road_ids = {str(feature["properties"]["id"]) for feature in step5c_working_roads["features"]}
    assert {"a14", "a43", "a32", "a21", "b14", "b43", "b32", "b21"}.isdisjoint(
        step5c_working_road_ids
    )
    step5c_working_nodes = _load_geojson(artifacts.out_root / "step5c_working_nodes.geojson")
    step5c_node_props = {str(feature["properties"]["id"]): feature["properties"] for feature in step5c_working_nodes["features"]}
    assert step5c_node_props["210"]["step5c_input_eligible"] is False
    assert step5c_node_props["230"]["step5c_input_eligible"] is False
    assert step5c_node_props["10"]["step5c_input_eligible"] is True
    assert step5c_node_props["30"]["step5c_input_eligible"] is True
    assert step5c_node_props["110"]["step5c_input_eligible"] is True
    assert step5c_node_props["130"]["step5c_input_eligible"] is True
    assert step5c_node_props["10"]["step5c_historical_boundary"] is True
    assert step5c_node_props["30"]["step5c_historical_boundary"] is True
    assert step5c_node_props["110"]["step5c_historical_boundary"] is True
    assert step5c_node_props["130"]["step5c_historical_boundary"] is True
    assert step5c_node_props["210"]["step5c_is_current_input_candidate"] is False
    assert step5c_node_props["230"]["step5c_is_current_input_candidate"] is False
    assert step5c_node_props["10"]["step5c_is_actual_barrier"] is True
    assert step5c_node_props["30"]["step5c_is_protected_hard_stop"] is True
    assert step5c_node_props["210"]["step5c_in_rolling_pool"] is False
    assert step5c_node_props["230"]["step5c_in_rolling_pool"] is False

    assert (artifacts.out_root / "STEP5C" / "step5c_rolling_endpoint_pool.csv").is_file()
    assert (artifacts.out_root / "STEP5C" / "step5c_protected_hard_stops.csv").is_file()
    assert (artifacts.out_root / "STEP5C" / "step5c_demotable_endpoints.csv").is_file()
    assert (artifacts.out_root / "STEP5C" / "step5c_actual_barriers.csv").is_file()
    assert (artifacts.out_root / "STEP5C" / "step5c_endpoint_demote_audit.json").is_file()
    target_pair_audit = json.loads(
        (artifacts.out_root / "STEP5C" / "target_pair_audit_997356__39546395.json").read_text(encoding="utf-8")
    )
    assert target_pair_audit["blocked_by_actual_barrier"] is False
    assert target_pair_audit["terminate_rigidity_cleared"] is True

    roads_doc = _load_geojson(artifacts.refreshed_roads_path)
    road_props = {str(feature["properties"]["id"]): feature["properties"] for feature in roads_doc["features"]}
    for road_id in ["a14", "a43", "a32", "a21"]:
        assert road_props[road_id]["segmentid"] == "10_30"
        assert road_props[road_id]["sgrade"] == "0-2双"
    for road_id in ["a46", "a62"]:
        assert road_props[road_id]["segmentid"] in {None, ""}
        assert road_props[road_id]["sgrade"] in {None, ""}
    for road_id in ["b14", "b43", "b32", "b21"]:
        assert road_props[road_id]["segmentid"] == "110_130"
        assert road_props[road_id]["sgrade"] == "0-2双"
    for road_id in ["b46", "b62"]:
        assert road_props[road_id]["segmentid"] in {None, ""}
        assert road_props[road_id]["sgrade"] in {None, ""}
    for road_id in ["c14", "c43", "c32", "c21"]:
        assert road_props[road_id]["segmentid"] in {None, ""}
        assert road_props[road_id]["sgrade"] in {None, ""}
    for road_id in ["c46", "c62"]:
        assert road_props[road_id]["segmentid"] in {None, ""}
        assert road_props[road_id]["sgrade"] in {None, ""}
    assert road_props["old1"]["segmentid"] == "old_pair"
    assert road_props["old1"]["sgrade"] == "0-1双"
    assert road_props["tin"]["segmentid"] in {None, ""}
    assert road_props["tout"]["segmentid"] in {None, ""}

    nodes_doc = _load_geojson(artifacts.refreshed_nodes_path)
    node_props = {str(feature["properties"]["id"]): feature["properties"] for feature in nodes_doc["features"]}
    assert node_props["10"]["grade_2"] == 2
    assert node_props["10"]["kind_2"] == 2048
    assert "working_mainnodeid" not in node_props["10"]
    assert node_props["30"]["grade_2"] == 1
    assert node_props["30"]["kind_2"] == 64
    assert node_props["110"]["grade_2"] == 3
    assert node_props["110"]["kind_2"] == 2048
    assert node_props["130"]["grade_2"] == 3
    assert node_props["130"]["kind_2"] == 2048
    assert node_props["210"]["grade_2"] == 2
    assert node_props["210"]["kind_2"] == 1
    assert node_props["230"]["grade_2"] == 3
    assert node_props["230"]["kind_2"] == 1
    assert node_props["501"]["grade_2"] == 3
    assert node_props["501"]["kind_2"] == 2048

    mainnode_rows = {row["mainnode_id"]: row for row in _load_csv_rows(artifacts.mainnode_table_path)}
    assert mainnode_rows["10"]["applied_rule"] == "keep_step5_pair_endpoint"
    assert mainnode_rows["30"]["applied_rule"] == "protected_roundabout_mainnode"
    assert mainnode_rows["110"]["applied_rule"] == "keep_step5_pair_endpoint"
    assert mainnode_rows["210"]["applied_rule"] == "keep_current"
    assert mainnode_rows["501"]["applied_rule"] == "new_t_like"


def test_step5c_adaptive_context_keeps_historical_kind1_only_by_history_and_demotes_degree2_nodes() -> None:
    node_features = [
        _node_feature(1, 0.0, 0.0, grade_2=2, kind_2=1, closed_con=2),
        _node_feature(2, 10.0, 0.0, grade_2=2, kind_2=1, closed_con=2),
        _node_feature(3, 20.0, 0.0, grade_2=1, kind_2=64, closed_con=2),
        _node_feature(4, 30.0, 0.0, grade_2=2, kind_2=4, closed_con=2),
        _node_feature(5, 0.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
        _node_feature(6, 1.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
        _node_feature(7, 10.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
        _node_feature(8, 11.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
        _node_feature(9, 12.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
        _node_feature(10, 20.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
        _node_feature(11, 21.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
        _node_feature(12, 30.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
        _node_feature(13, 31.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
    ]
    road_features = [
        _road_feature("r15", 1, 5, 0, [[0.0, 0.0], [0.0, 1.0]]),
        _road_feature("r16", 1, 6, 0, [[0.0, 0.0], [1.0, 0.0]]),
        _road_feature("r27", 2, 7, 0, [[10.0, 0.0], [10.0, 1.0]]),
        _road_feature("r28", 2, 8, 0, [[10.0, 0.0], [11.0, 0.0]]),
        _road_feature("r29", 2, 9, 0, [[10.0, 0.0], [12.0, 0.0]]),
        _road_feature("r310", 3, 10, 0, [[20.0, 0.0], [20.0, 1.0]]),
        _road_feature("r311", 3, 11, 0, [[20.0, 0.0], [21.0, 0.0]]),
        _road_feature("r412", 4, 12, 0, [[30.0, 0.0], [30.0, 1.0]]),
        _road_feature("r413", 4, 13, 0, [[30.0, 0.0], [31.0, 0.0]]),
    ]
    nodes = [_node_record(feature) for feature in node_features]
    roads = [_road_record(feature) for feature in road_features]
    adaptive_context = _build_step5c_adaptive_context(
        nodes=nodes,
        roads=roads,
        active_road_ids={road.road_id for road in roads},
        historical_seed_node_ids={"1"},
        historical_seed_source_map={"1": ("STEP5B",)},
    )
    assert adaptive_context.rolling_endpoint_pool_ids == ("1", "3", "4")
    assert adaptive_context.current_input_candidate_ids == ("3", "4")
    assert adaptive_context.protected_hard_stop_ids == ("3",)
    assert adaptive_context.demotable_endpoint_ids == ("1", "4")
    assert adaptive_context.actual_terminate_barrier_ids == ("3",)
    audit_by_node_id = {row["node_id"]: row for row in adaptive_context.demote_audit_rows}
    assert audit_by_node_id["1"]["is_historical_endpoint"] is True
    assert audit_by_node_id["1"]["is_current_input_candidate"] is False
    assert audit_by_node_id["1"]["demoted"] is True
    assert "2" not in audit_by_node_id
    assert audit_by_node_id["3"]["reason"] == "protected_roundabout"
    assert audit_by_node_id["4"]["demoted"] is True


def test_step5_historical_boundary_is_injected_into_step5a_seed_and_terminate(tmp_path: Path) -> None:
    input_dir = tmp_path / "input_hist"
    input_dir.mkdir()
    s2_dir = input_dir / "S2"
    step4_dir = input_dir / "STEP4"
    s2_dir.mkdir()
    step4_dir.mkdir()
    (s2_dir / "validated_pairs.csv").write_text(
        "pair_id,a_node_id,b_node_id\nS2:300__999,300,999\n",
        encoding="utf-8",
    )

    node_path = input_dir / "nodes.geojson"
    road_path = input_dir / "roads.geojson"
    out_root = tmp_path / "out_hist"

    write_geojson(
        node_path,
        [
            _node_feature(110, 0.0, 0.0, grade_2=2, kind_2=2048, closed_con=2),
            _node_feature(120, 1.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(300, 2.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r12", 110, 120, 0, [[0.0, 0.0], [1.0, 0.0]]),
            _road_feature("r23", 120, 300, 0, [[1.0, 0.0], [2.0, 0.0]]),
        ],
    )

    artifacts = run_step5_staged_residual_graph(
        road_path=road_path,
        node_path=node_path,
        out_root=out_root,
        run_id="step5_hist_seed",
    )

    step5a_strategy = json.loads((artifacts.out_root / "step5a_strategy.json").read_text(encoding="utf-8"))
    assert step5a_strategy["force_seed_node_ids"] == ["300", "999"]
    assert step5a_strategy["force_terminate_node_ids"] == ["300", "999"]
    assert step5a_strategy["hard_stop_node_ids"] == ["300", "999"]

    step5a_working_nodes = _load_geojson(artifacts.out_root / "step5a_working_nodes.geojson")
    step5a_node_props = {str(feature["properties"]["id"]): feature["properties"] for feature in step5a_working_nodes["features"]}
    assert step5a_node_props["300"]["step5a_input_eligible"] is True
    assert step5a_node_props["300"]["step5a_historical_boundary"] is True

    step5a_rows = _load_csv_rows(artifacts.out_root / "step5a_validated_pairs.csv")
    assert {row["pair_id"] for row in step5a_rows} == {"STEP5A:110__300"}


def test_step5_does_not_keep_kind1_pseudojunction_boundary_created_only_by_right_turn_lane(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input_kind1"
    input_dir.mkdir()
    s2_dir = input_dir / "S2"
    step4_dir = input_dir / "STEP4"
    s2_dir.mkdir()
    step4_dir.mkdir()
    (s2_dir / "endpoint_pool.csv").write_text(
        "node_id,source_tags\n2,S2\n",
        encoding="utf-8",
    )

    node_path = input_dir / "nodes.geojson"
    road_path = input_dir / "roads.geojson"
    out_root = tmp_path / "out_kind1"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, grade_2=2, kind_2=2048, closed_con=2),
            _node_feature(2, 1.0, 0.0, grade_2=3, kind_2=1, closed_con=2),
            _node_feature(3, 2.0, 0.0, grade_2=1, kind_2=4, closed_con=2),
            _node_feature(4, 1.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r12", 1, 2, 0, [[0.0, 0.0], [1.0, 0.0]]),
            _road_feature("r23", 2, 3, 0, [[1.0, 0.0], [2.0, 0.0]]),
            _road_feature("r24_right_turn", 2, 4, 0, [[1.0, 0.0], [1.0, 1.0]], formway=128),
        ],
    )

    artifacts = run_step5_staged_residual_graph(
        road_path=road_path,
        node_path=node_path,
        out_root=out_root,
        run_id="step5_kind1_pseudojunction",
    )

    step5a_strategy = json.loads((artifacts.out_root / "step5a_strategy.json").read_text(encoding="utf-8"))
    assert step5a_strategy["force_seed_node_ids"] == []
    assert step5a_strategy["force_terminate_node_ids"] == []
    assert step5a_strategy["hard_stop_node_ids"] == []

    step5a_working_roads = _load_geojson(artifacts.out_root / "step5a_working_roads.geojson")
    step5a_road_ids = {str(feature["properties"]["id"]) for feature in step5a_working_roads["features"]}
    assert "r24_right_turn" not in step5a_road_ids

    step5a_rows = _load_csv_rows(artifacts.out_root / "step5a_validated_pairs.csv")
    assert {row["pair_id"] for row in step5a_rows} == {"STEP5A:1__3"}


def test_step5_does_not_keep_kind4_pseudojunction_created_only_by_right_turn_lane(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input_kind4"
    input_dir.mkdir()
    (input_dir / "S2").mkdir()
    (input_dir / "STEP4").mkdir()

    node_path = input_dir / "nodes.geojson"
    road_path = input_dir / "roads.geojson"
    out_root = tmp_path / "out_kind4"

    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, grade_2=1, kind_2=4, closed_con=2),
            _node_feature(2, 1.0, 0.0, grade_2=1, kind_2=4, closed_con=2),
            _node_feature(3, 2.0, 0.0, grade_2=1, kind_2=4, closed_con=2),
            _node_feature(4, 1.0, 1.0, grade_2=0, kind_2=0, closed_con=0),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r12", 1, 2, 0, [[0.0, 0.0], [1.0, 0.0]]),
            _road_feature("r23", 2, 3, 0, [[1.0, 0.0], [2.0, 0.0]]),
            _road_feature("r24_right_turn", 2, 4, 0, [[1.0, 0.0], [1.0, 1.0]], formway=128),
        ],
    )

    artifacts = run_step5_staged_residual_graph(
        road_path=road_path,
        node_path=node_path,
        out_root=out_root,
        run_id="step5_kind4_pseudojunction",
    )

    step5a_working_nodes = _load_geojson(artifacts.out_root / "step5a_working_nodes.geojson")
    node_props = {str(feature["properties"]["id"]): feature["properties"] for feature in step5a_working_nodes["features"]}
    assert node_props["2"]["step5a_input_eligible"] is False

    step5a_rows = _load_csv_rows(artifacts.out_root / "step5a_validated_pairs.csv")
    assert {row["pair_id"] for row in step5a_rows} == {"STEP5A:1__3"}


def test_step5_requires_initialized_working_layers(tmp_path: Path) -> None:
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
                "properties": {
                    "id": "r1",
                    "snodeid": 1,
                    "enodeid": 1,
                    "direction": 2,
                    "formway": 0,
                },
                "geometry": LineString([(0.0, 0.0), (0.1, 0.0)]),
            }
        ],
    )

    with pytest.raises(ValueError, match="missing working fields"):
        run_step5_staged_residual_graph(
            road_path=road_path,
            node_path=node_path,
            out_root=tmp_path / "out_invalid",
            run_id="step5_invalid",
        )


def test_step5_run_phase_suffixes_when_reserved_segmentid_collides(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out_root = tmp_path / "out"
    phase_id = "STEP5A"
    phase_dir = out_root / phase_id
    phase_dir.mkdir(parents=True)

    def _fake_run_step2_segment_poc(**_: object) -> list[object]:
        (phase_dir / "validated_pairs.csv").write_text(
            "pair_id,a_node_id,b_node_id\nSTEP5A:10__30,10,30\n",
            encoding="utf-8",
        )
        write_geojson(
            phase_dir / "segment_body_roads.geojson",
            [
                {
                    "properties": {
                        "pair_id": "STEP5A:10__30",
                        "a_node_id": "10",
                        "b_node_id": "30",
                        "validated_status": "validated",
                        "road_ids": ["r1", "r2"],
                    },
                    "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
                }
            ],
        )
        (phase_dir / "segment_summary.json").write_text(
            json.dumps(
                {
                    "candidate_pair_count": 1,
                    "validated_pair_count": 1,
                    "rejected_pair_count": 0,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return [object()]

    monkeypatch.setattr(
        "rcsd_topo_poc.modules.t01_data_preprocess.step5_staged_residual_graph.run_step2_segment_poc",
        _fake_run_step2_segment_poc,
    )

    phase_input = PhaseInputArtifacts(
        phase_id=phase_id,
        working_nodes_path=tmp_path / "nodes.geojson",
        working_roads_path=tmp_path / "roads.geojson",
        strategy_path=tmp_path / "strategy.json",
        input_node_count=0,
        seed_count=0,
        terminate_count=0,
        working_graph_road_count=0,
        active_road_ids=(),
        endpoint_pool_ids=(),
        endpoint_pool_source_map={},
    )

    artifacts = _run_phase(
        phase_input=phase_input,
        out_root=out_root,
        run_id="step5_suffix_case",
        formway_mode="strict",
        left_turn_formway_bit=8,
        debug=False,
        reserved_segmentids={"10_30"},
    )

    assert artifacts.road_to_segmentid["r1"] == "10_30_1"
    assert artifacts.road_to_segmentid["r2"] == "10_30_1"
    assert artifacts.assigned_segment_ids == ("10_30_1",)
