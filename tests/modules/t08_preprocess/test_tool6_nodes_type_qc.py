from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import fiona
from pyproj import CRS
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg


def _node(node_id: str, kind_2: int, x: float, y: float) -> dict:
    return {
        "properties": {
            "id": node_id,
            "kind": kind_2,
            "kind_2": kind_2,
            "grade": 1,
            "grade_2": 1,
            "mainnodeid": node_id,
        },
        "geometry": Point(x, y),
    }


def _road(
    road_id: str,
    snodeid: str,
    enodeid: str,
    coords: list[tuple[float, float]],
    *,
    direction: int = 2,
    kind: str = "0100",
) -> dict:
    return {
        "properties": {"id": road_id, "snodeid": snodeid, "enodeid": enodeid, "direction": direction, "kind": kind},
        "geometry": LineString(coords),
    }


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def _read_gpkg_rows(path: Path) -> tuple[int | None, list[dict]]:
    with fiona.open(path) as source:
        crs_value = source.crs_wkt or source.crs
        epsg = CRS.from_user_input(crs_value).to_epsg() if crs_value else None
        return epsg, [dict(feature["properties"]) for feature in source]


def _audit(row: dict[str, str]) -> dict:
    return json.loads(row["audit_json"])


def _run_tool6(
    tmp_path: Path,
    *,
    case_name: str,
    nodes: list[dict],
    roads: list[dict],
) -> tuple[list[dict[str, str]], list[dict], dict]:
    root = tmp_path / case_name
    nodes_gpkg = root / "input" / "nodes.gpkg"
    roads_gpkg = root / "input" / "roads.gpkg"
    csv_output = root / "out" / "node_error_tool6.csv"
    error_nodes_output = root / "out" / "node_error_tool6.gpkg"
    summary_output = root / "out" / "node_error_summary_tool6.json"
    write_gpkg(nodes_gpkg, nodes, crs_text="EPSG:3857")
    write_gpkg(roads_gpkg, roads, crs_text="EPSG:3857")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool6_nodes_type_qc.py",
            "--nodes-gpkg",
            str(nodes_gpkg),
            "--roads-gpkg",
            str(roads_gpkg),
            "--csv-output",
            str(csv_output),
            "--error-nodes-output",
            str(error_nodes_output),
            "--summary-output",
            str(summary_output),
            "--progress-interval",
            "1",
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "[T08 Tool6]" in result.stderr
    csv_rows = _read_csv_rows(csv_output)
    epsg, gpkg_rows = _read_gpkg_rows(error_nodes_output)
    assert epsg == 3857
    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    return csv_rows, gpkg_rows, summary


def test_tool6_outputs_divmerge_and_cross_qc_rows(tmp_path: Path) -> None:
    nodes = [
        _node("entry", 1, -20.0, 0.0),
        _node("div", 16, 0.0, 0.0),
        _node("merge", 8, 60.0, 0.0),
        _node("right_join", 1, 30.0, -40.0),
        _node("right_stub", 1, 30.0, -60.0),
        _node("exit", 1, 90.0, 0.0),
        _node("cross", 4, 200.0, 0.0),
        _node("cross_west", 1, 190.0, 0.0),
        _node("cross_east", 1, 210.0, 0.0),
        _node("cross_south", 1, 200.0, -10.0),
        _node("noncross", 4, 300.0, 0.0),
        _node("nc_west", 1, 290.0, 0.0),
        _node("nc_east", 1, 310.0, 0.0),
        _node("cross_ok", 4, 400.0, 0.0),
        _node("ok_west", 1, 390.0, 0.0),
        _node("ok_south", 1, 400.0, -10.0),
        _node("true_cross", 4, 500.0, 0.0),
        _node("tc_west", 1, 490.0, 0.0),
        _node("tc_south", 1, 500.0, -10.0),
        _node("tc_east", 1, 510.0, 0.0),
        _node("tc_north", 1, 500.0, 10.0),
    ]
    roads = [
        _road("r-entry-div", "entry", "div", [(-20.0, 0.0), (0.0, 0.0)]),
        _road("r-div-merge", "div", "merge", [(0.0, 0.0), (60.0, 0.0)]),
        _road("r-div-right", "div", "right_join", [(0.0, 0.0), (30.0, -40.0)]),
        _road("r-right-merge", "right_join", "merge", [(30.0, -40.0), (60.0, 0.0)]),
        _road("r-right-stub", "right_join", "right_stub", [(30.0, -40.0), (30.0, -60.0)]),
        _road("r-merge-exit", "merge", "exit", [(60.0, 0.0), (90.0, 0.0)]),
        _road("r-cross-in", "cross_west", "cross", [(190.0, 0.0), (200.0, 0.0)]),
        _road("r-cross-out", "cross", "cross_east", [(200.0, 0.0), (210.0, 0.0)]),
        _road("r-cross-vertical", "cross_south", "cross", [(200.0, -10.0), (200.0, 0.0)], direction=0),
        _road("r-nc-in-h", "nc_west", "noncross", [(290.0, 0.0), (300.0, 0.0)]),
        _road("r-nc-out-h", "noncross", "nc_west", [(300.0, 0.0), (290.0, 0.0)]),
        _road("r-nc-in-e", "nc_east", "noncross", [(310.0, 0.0), (300.0, 0.0)]),
        _road("r-nc-out-e", "noncross", "nc_east", [(300.0, 0.0), (310.0, 0.0)]),
        _road("r-ok-west", "ok_west", "cross_ok", [(390.0, 0.0), (400.0, 0.0)], direction=0),
        _road("r-ok-south", "ok_south", "cross_ok", [(400.0, -10.0), (400.0, 0.0)], direction=0),
        _road("r-tc-in-west", "tc_west", "true_cross", [(490.0, 0.0), (500.0, 0.0)]),
        _road("r-tc-in-south", "tc_south", "true_cross", [(500.0, -10.0), (500.0, 0.0)]),
        _road("r-tc-out-east", "true_cross", "tc_east", [(500.0, 0.0), (510.0, 0.0)]),
        _road("r-tc-out-north", "true_cross", "tc_north", [(500.0, 0.0), (500.0, 10.0)]),
    ]

    csv_rows, gpkg_rows, summary = _run_tool6(tmp_path, case_name="basic_errors", nodes=nodes, roads=roads)

    assert [row["error_type"] for row in csv_rows].count("错误分歧合流路口") == 2
    assert [row["error_type"] for row in csv_rows].count("错误交叉路口_T型路口") == 1
    assert [row["error_type"] for row in csv_rows].count("错误交叉路口_非交叉路口") == 2
    assert csv_rows[0]["是否修复"] == "1"
    assert list(csv_rows[0])[-1] == "是否修复"
    assert {row["semantic_node_id"] for row in csv_rows if row["error_type"] == "错误分歧合流路口"} == {"div", "merge"}
    assert {row["semantic_node_id"] for row in csv_rows if row["error_type"] == "错误交叉路口_T型路口"} == {"cross"}
    assert {row["semantic_node_id"] for row in csv_rows if row["error_type"] == "错误交叉路口_非交叉路口"} == {
        "cross_ok",
        "noncross",
    }
    reason_by_node = {row["semantic_node_id"]: row["reason"] for row in csv_rows}
    assert reason_by_node["cross_ok"] == "only_two_bidirectional_roads"
    assert reason_by_node["noncross"] == "two_parallel_outward_angle_groups_each_has_in_and_out"
    cross_audit = _audit(next(row for row in csv_rows if row["semantic_node_id"] == "cross"))
    assert cross_audit["outward_angle_group_count"] == 3
    assert {member["road_id"] for group in cross_audit["angle_groups"] for member in group["members"]} == {
        "r-cross-in",
        "r-cross-out",
        "r-cross-vertical",
    }
    assert all("outward_vector" in member for group in cross_audit["angle_groups"] for member in group["members"])
    noncross_audit = _audit(next(row for row in csv_rows if row["semantic_node_id"] == "noncross"))
    assert noncross_audit["outward_angle_group_count"] == 2
    assert noncross_audit["outward_angle_group_parallel"] is True
    assert {reason["reason"] for group in noncross_audit["angle_groups"] for reason in group["merge_reasons"]} == {
        "same_remote_semantic"
    }
    assert "true_cross" not in {row["semantic_node_id"] for row in csv_rows}
    assert len(gpkg_rows) == 5
    assert summary["counts"]["error_count_by_type"] == {
        "错误交叉路口_T型路口": 1,
        "错误交叉路口_非交叉路口": 2,
        "错误分歧合流路口": 2,
    }
    assert summary["counts"]["divmerge_error_group_count"] == 1
    assert summary["params"]["vertical_endpoint_distance_m"] == 20.0
    assert summary["params"]["manual_fix_default"] == 1


def test_tool6_two_angle_nonparallel_cross_candidate_is_not_error(tmp_path: Path) -> None:
    nodes = [
        _node("cross", 4, 0.0, 0.0),
        _node("west", 1, -10.0, 0.0),
        _node("south", 1, 0.0, -10.0),
    ]
    roads = [
        _road("r-west-in", "west", "cross", [(-10.0, 0.0), (0.0, 0.0)]),
        _road("r-west-out", "cross", "west", [(0.0, 0.0), (-10.0, 0.0)]),
        _road("r-south-in", "south", "cross", [(0.0, -10.0), (0.0, 0.0)]),
        _road("r-south-out", "cross", "south", [(0.0, 0.0), (0.0, -10.0)]),
    ]

    csv_rows, gpkg_rows, summary = _run_tool6(tmp_path, case_name="two_angle_nonparallel", nodes=nodes, roads=roads)

    assert csv_rows == []
    assert gpkg_rows == []
    assert summary["counts"]["error_feature_count"] == 0


def test_tool6_three_angle_cross_candidate_is_not_error_unless_t(tmp_path: Path) -> None:
    nodes = [
        _node("cross", 4, 0.0, 0.0),
        _node("west", 1, -10.0, 0.0),
        _node("south", 1, 0.0, -10.0),
        _node("east", 1, 10.0, 0.0),
    ]
    roads = [
        _road("r-west-in", "west", "cross", [(-10.0, 0.0), (0.0, 0.0)]),
        _road("r-west-out", "cross", "west", [(0.0, 0.0), (-10.0, 0.0)]),
        _road("r-south-in", "south", "cross", [(0.0, -10.0), (0.0, 0.0)]),
        _road("r-east-out", "cross", "east", [(0.0, 0.0), (10.0, 0.0)]),
    ]

    csv_rows, gpkg_rows, summary = _run_tool6(tmp_path, case_name="three_angle_non_t", nodes=nodes, roads=roads)

    assert csv_rows == []
    assert gpkg_rows == []
    assert summary["counts"]["error_feature_count"] == 0


def test_tool6_suppresses_divmerge_when_associated_road_kind_suffix_17(tmp_path: Path) -> None:
    nodes = [
        _node("entry", 1, -20.0, 0.0),
        _node("div", 16, 0.0, 0.0),
        _node("merge", 8, 60.0, 0.0),
        _node("right_join", 1, 30.0, -40.0),
        _node("right_stub", 1, 30.0, -60.0),
        _node("exit", 1, 90.0, 0.0),
    ]
    roads = [
        _road("r-entry-div", "entry", "div", [(-20.0, 0.0), (0.0, 0.0)]),
        _road("r-div-merge", "div", "merge", [(0.0, 0.0), (60.0, 0.0)], kind="0117"),
        _road("r-div-right", "div", "right_join", [(0.0, 0.0), (30.0, -40.0)]),
        _road("r-right-merge", "right_join", "merge", [(30.0, -40.0), (60.0, 0.0)]),
        _road("r-right-stub", "right_join", "right_stub", [(30.0, -40.0), (30.0, -60.0)]),
        _road("r-merge-exit", "merge", "exit", [(60.0, 0.0), (90.0, 0.0)]),
    ]

    csv_rows, gpkg_rows, summary = _run_tool6(tmp_path, case_name="kind17_suppressed", nodes=nodes, roads=roads)

    assert csv_rows == []
    assert gpkg_rows == []
    assert summary["counts"]["error_feature_count"] == 0
    assert summary["counts"]["divmerge_suppressed_count"] == 1
    assert summary["divmerge_suppressed"][0]["reason"] == "associated_road_kind_suffix_17"


def test_tool6_suppresses_divmerge_when_oneway_vertical_links_diverge_and_merge(tmp_path: Path) -> None:
    nodes = [
        _node("entry", 1, -20.0, 0.0),
        _node("div", 16, 0.0, 0.0),
        _node("merge", 8, 60.0, 0.0),
        _node("right_mid", 1, 30.0, -40.0),
        _node("exit", 1, 90.0, 0.0),
    ]
    roads = [
        _road("r-entry-div", "entry", "div", [(-20.0, 0.0), (0.0, 0.0)]),
        _road("r-div-merge", "div", "merge", [(0.0, 0.0), (60.0, 0.0)]),
        _road("r-div-right-mid", "div", "right_mid", [(0.0, 0.0), (30.0, -40.0)]),
        _road("r-right-mid-merge", "right_mid", "merge", [(30.0, -40.0), (60.0, 0.0)]),
        _road("r-merge-exit", "merge", "exit", [(60.0, 0.0), (90.0, 0.0)]),
    ]

    csv_rows, gpkg_rows, summary = _run_tool6(
        tmp_path,
        case_name="oneway_vertical_link_suppressed",
        nodes=nodes,
        roads=roads,
    )

    assert csv_rows == []
    assert gpkg_rows == []
    assert summary["counts"]["error_feature_count"] == 0
    assert summary["counts"]["divmerge_suppressed_count"] == 1
    assert summary["divmerge_suppressed"][0]["reason"] == "oneway_vertical_connects_diverge_and_merge"


def test_tool6_requires_strict_divmerge_degrees_for_qc(tmp_path: Path) -> None:
    nodes = [
        _node("entry", 1, -20.0, 0.0),
        _node("extra_entry", 1, -20.0, 10.0),
        _node("div", 16, 0.0, 0.0),
        _node("merge", 8, 60.0, 0.0),
        _node("right_join", 1, 30.0, -40.0),
        _node("right_stub", 1, 30.0, -60.0),
        _node("exit", 1, 90.0, 0.0),
    ]
    roads = [
        _road("r-entry-div", "entry", "div", [(-20.0, 0.0), (0.0, 0.0)]),
        _road("r-extra-div", "extra_entry", "div", [(-20.0, 10.0), (0.0, 0.0)]),
        _road("r-div-merge", "div", "merge", [(0.0, 0.0), (60.0, 0.0)]),
        _road("r-div-right", "div", "right_join", [(0.0, 0.0), (30.0, -40.0)]),
        _road("r-right-merge", "right_join", "merge", [(30.0, -40.0), (60.0, 0.0)]),
        _road("r-right-stub", "right_join", "right_stub", [(30.0, -40.0), (30.0, -60.0)]),
        _road("r-merge-exit", "merge", "exit", [(60.0, 0.0), (90.0, 0.0)]),
    ]

    csv_rows, gpkg_rows, summary = _run_tool6(tmp_path, case_name="divmerge_degree_guard", nodes=nodes, roads=roads)

    assert csv_rows == []
    assert gpkg_rows == []
    assert summary["counts"]["error_feature_count"] == 0

    nodes = [
        _node("entry", 1, -20.0, 0.0),
        _node("div", 16, 0.0, 0.0),
        _node("merge", 8, 60.0, 0.0),
        _node("right_join", 1, 30.0, -40.0),
        _node("right_stub", 1, 30.0, -60.0),
        _node("exit", 1, 90.0, 0.0),
        _node("extra_exit", 1, 90.0, 10.0),
    ]
    roads = [
        _road("r-entry-div", "entry", "div", [(-20.0, 0.0), (0.0, 0.0)]),
        _road("r-div-merge", "div", "merge", [(0.0, 0.0), (60.0, 0.0)]),
        _road("r-div-right", "div", "right_join", [(0.0, 0.0), (30.0, -40.0)]),
        _road("r-right-merge", "right_join", "merge", [(30.0, -40.0), (60.0, 0.0)]),
        _road("r-right-stub", "right_join", "right_stub", [(30.0, -40.0), (30.0, -60.0)]),
        _road("r-merge-exit", "merge", "exit", [(60.0, 0.0), (90.0, 0.0)]),
        _road("r-merge-extra", "merge", "extra_exit", [(60.0, 0.0), (90.0, 10.0)]),
    ]

    csv_rows, gpkg_rows, summary = _run_tool6(tmp_path, case_name="merge_degree_guard", nodes=nodes, roads=roads)

    assert csv_rows == []
    assert gpkg_rows == []
    assert summary["counts"]["error_feature_count"] == 0


def test_tool6_script_help() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/t08_tool6_nodes_type_qc.py", "--help"],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0
    assert "--csv-output" in result.stdout
    assert "--error-nodes-output" in result.stdout
