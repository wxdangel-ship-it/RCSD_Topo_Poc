from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fiona
from pyproj import CRS
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg


def _node(node_id: str, kind_2: int, x: float, y: float, *, mainnodeid: str | None = None) -> dict:
    return {
        "properties": {
            "id": node_id,
            "kind": 0,
            "kind_2": kind_2,
            "grade": 1,
            "grade_2": 1,
            "mainnodeid": mainnodeid if mainnodeid is not None else node_id,
        },
        "geometry": Point(x, y),
    }


def _road(
    road_id: str,
    snodeid: str,
    enodeid: str,
    coords: list[tuple[float, float]],
    direction: int = 2,
    *,
    kind: str | None = None,
    formway: int | None = None,
) -> dict:
    properties = {"id": road_id, "snodeid": snodeid, "enodeid": enodeid, "direction": direction}
    if kind is not None:
        properties["kind"] = kind
    if formway is not None:
        properties["formway"] = formway
    return {"properties": properties, "geometry": LineString(coords)}


def _read_rows(path: Path) -> tuple[int | None, dict[str, dict]]:
    with fiona.open(path) as source:
        crs_value = source.crs_wkt or source.crs
        epsg = CRS.from_user_input(crs_value).to_epsg() if crs_value else None
        rows = {str(feature["properties"]["semantic_node_id"]): dict(feature["properties"]) for feature in source}
    return epsg, rows


def _run_tool4_case(
    tmp_path: Path,
    *,
    case_name: str,
    nodes: list[dict],
    roads: list[dict],
) -> tuple[dict[str, dict], dict]:
    nodes_gpkg = tmp_path / case_name / "input" / "nodes.gpkg"
    roads_gpkg = tmp_path / case_name / "input" / "roads.gpkg"
    nodes_error_output = tmp_path / case_name / "out" / "nodes_error.gpkg"
    summary_output = tmp_path / case_name / "out" / "nodes_error_summary.json"
    write_gpkg(nodes_gpkg, nodes, crs_text="EPSG:3857")
    write_gpkg(roads_gpkg, roads, crs_text="EPSG:3857")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool4_junction_type_repair.py",
            "--nodes-gpkg",
            str(nodes_gpkg),
            "--roads-gpkg",
            str(roads_gpkg),
            "--nodes-error-output",
            str(nodes_error_output),
            "--summary-output",
            str(summary_output),
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    _, rows = _read_rows(nodes_error_output)
    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    return rows, summary


def test_tool4_detects_junction_type_errors(tmp_path: Path) -> None:
    nodes_gpkg = tmp_path / "input" / "nodes.gpkg"
    roads_gpkg = tmp_path / "input" / "roads.gpkg"
    nodes_error_output = tmp_path / "out" / "nodes_error.gpkg"
    summary_output = tmp_path / "out" / "nodes_error_summary.json"

    nodes = [
        _node("10", 1, -20.0, 0.0),
        _node("100", 16, 0.0, 0.0),
        _node("150", 1, 40.0, 0.0),
        _node("200", 8, 80.0, 0.0),
        _node("210", 1, 100.0, 0.0),
        _node("300", 1, 40.0, -40.0),
        _node("390", 1, -10.0, 100.0),
        _node("391", 1, 0.0, 90.0),
        _node("400", 4, 0.0, 100.0),
        _node("410", 1, 10.0, 100.0),
        _node("411", 1, 0.0, 110.0),
        _node("500", 2048, 0.0, 200.0),
        _node("510", 1, -10.0, 200.0),
        _node("520", 1, 10.0, 200.0),
        _node("521", 1, 0.0, 210.0),
    ]
    roads = [
        _road("r-in-div", "10", "100", [(-20.0, 0.0), (0.0, 0.0)]),
        _road("r-main-1", "100", "150", [(0.0, 0.0), (40.0, 0.0)]),
        _road("r-main-2", "150", "200", [(40.0, 0.0), (80.0, 0.0)]),
        _road("r-merge-out", "200", "210", [(80.0, 0.0), (100.0, 0.0)]),
        _road("r-side-div", "100", "300", [(0.0, 0.0), (40.0, -40.0)]),
        _road("r-side-merge", "300", "200", [(40.0, -40.0), (80.0, 0.0)]),
        _road("r-cross-in-1", "390", "400", [(-10.0, 100.0), (0.0, 100.0)]),
        _road("r-cross-in-2", "391", "400", [(0.0, 90.0), (0.0, 100.0)]),
        _road("r-cross-out-1", "400", "410", [(0.0, 100.0), (10.0, 100.0)]),
        _road("r-cross-out-2", "400", "411", [(0.0, 100.0), (0.0, 110.0)]),
        _road("r-t-in", "510", "500", [(-10.0, 200.0), (0.0, 200.0)]),
        _road("r-t-out-1", "500", "520", [(0.0, 200.0), (10.0, 200.0)]),
        _road("r-t-out-2", "500", "521", [(0.0, 200.0), (0.0, 210.0)]),
    ]
    write_gpkg(nodes_gpkg, nodes, crs_text="EPSG:3857")
    write_gpkg(roads_gpkg, roads, crs_text="EPSG:3857")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool4_junction_type_repair.py",
            "--nodes-gpkg",
            str(nodes_gpkg),
            "--roads-gpkg",
            str(roads_gpkg),
            "--nodes-error-output",
            str(nodes_error_output),
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
    assert "[T08 Tool4]" in result.stderr
    epsg, rows = _read_rows(nodes_error_output)
    assert epsg == 3857
    assert rows["500"]["error_type"] == "错误T型路口"
    assert rows["500"]["kind_2"] == 2048
    assert "kind" not in rows["500"]
    assert "400" not in rows
    assert rows["100"]["error_type"] == "错误分歧合流路口"
    assert rows["200"]["error_type"] == "错误分歧合流路口"

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["counts"]["error_feature_count"] == 3
    assert summary["counts"]["error_count_by_type"] == {
        "错误T型路口": 1,
        "错误分歧合流路口": 2,
    }
    assert summary["field_audit"]["node_kind_2_field"] == "kind_2"
    assert "node_kind_field" not in summary["field_audit"]
    assert summary["performance"]["elapsed_seconds"] >= 0
    assert "detect_errors_seconds" in summary["performance"]["stage_timings"]
    assert summary["performance"]["road_read_mode"] == {
        "reader": "gpkg_sqlite_light",
        "selected_fields_only": True,
        "geometry_stored": False,
        "output_crs": "EPSG:3857",
        "layer_name": "roads",
    }


def test_tool4_counts_internal_road_as_in_and_out_degree(tmp_path: Path) -> None:
    nodes = [
        _node("500", 2048, 0.0, 0.0),
        _node("501", 0, 1.0, 0.0, mainnodeid="500"),
        _node("510", 1, -10.0, 0.0),
        _node("520", 1, 10.0, 0.0),
    ]
    roads = [
        _road("r-in", "510", "500", [(-10.0, 0.0), (0.0, 0.0)], direction=2),
        _road("r-internal", "500", "501", [(0.0, 0.0), (1.0, 0.0)], direction=2),
        _road("r-out", "501", "520", [(1.0, 0.0), (10.0, 0.0)], direction=2),
    ]

    rows, summary = _run_tool4_case(
        tmp_path,
        case_name="internal_road_degree",
        nodes=nodes,
        roads=roads,
    )

    assert rows == {}
    assert summary["counts"]["internal_road_count"] == 1
    assert summary["counts"]["error_feature_count"] == 0


def test_tool4_parallel_shortening_requires_20m_end_distance(tmp_path: Path) -> None:
    def build_case(merge_back_node: tuple[float, float]) -> tuple[list[dict], list[dict]]:
        nodes = [
            _node("10", 1, -20.0, 0.0),
            _node("100", 16, 0.0, 0.0),
            _node("150", 1, 40.0, 0.0),
            _node("200", 8, 80.0, 0.0),
            _node("210", 1, 100.0, 0.0),
            _node("300", 1, 95.0, -9.5),
            _node("301", 1, merge_back_node[0], merge_back_node[1]),
        ]
        roads = [
            _road("r-in-div", "10", "100", [(-20.0, 0.0), (0.0, 0.0)]),
            _road("r-main-1", "100", "150", [(0.0, 0.0), (40.0, 0.0)]),
            _road("r-main-2", "150", "200", [(40.0, 0.0), (80.0, 0.0)]),
            _road("r-merge-out", "200", "210", [(80.0, 0.0), (100.0, 0.0)]),
            _road("r-side-div", "100", "300", [(0.0, 0.0), (95.0, -9.5)]),
            _road("r-side-merge", "301", "200", [merge_back_node, (80.0, 0.0)]),
        ]
        return nodes, roads

    ok_nodes, ok_roads = build_case((95.0, -1.5))
    ok_rows, ok_summary = _run_tool4_case(
        tmp_path,
        case_name="parallel_within_20m",
        nodes=ok_nodes,
        roads=ok_roads,
    )
    assert ok_rows["100"]["error_type"] == "错误分歧合流路口"
    assert ok_rows["200"]["error_type"] == "错误分歧合流路口"
    ok_audit = ok_summary["errors"][0]["audit_json"]
    assert ok_audit["vertical_parallel_shortening"] is True
    assert ok_audit["end_distance_m"] == 8.0
    assert ok_audit["parallel_distance_threshold_m"] == 20.0

    far_nodes, far_roads = build_case((115.0, -3.5))
    far_rows, far_summary = _run_tool4_case(
        tmp_path,
        case_name="parallel_over_20m",
        nodes=far_nodes,
        roads=far_roads,
    )
    assert far_rows == {}
    assert far_summary["counts"]["error_feature_count"] == 0


def test_tool4_suppresses_divmerge_error_when_related_road_kind_is_entrance_exit(tmp_path: Path) -> None:
    nodes = [
        _node("10", 1, -20.0, 0.0),
        _node("100", 16, 0.0, 0.0),
        _node("150", 1, 40.0, 0.0),
        _node("200", 8, 80.0, 0.0),
        _node("210", 1, 100.0, 0.0),
        _node("300", 1, 40.0, -40.0),
    ]
    roads = [
        _road("r-in-div", "10", "100", [(-20.0, 0.0), (0.0, 0.0)], kind="0100"),
        _road("r-main-1", "100", "150", [(0.0, 0.0), (40.0, 0.0)], kind="0100"),
        _road("r-main-2", "150", "200", [(40.0, 0.0), (80.0, 0.0)], kind="0100"),
        _road("r-merge-out", "200", "210", [(80.0, 0.0), (100.0, 0.0)], kind="0100"),
        _road("r-side-div", "100", "300", [(0.0, 0.0), (40.0, -40.0)], kind="0117"),
        _road("r-side-merge", "300", "200", [(40.0, -40.0), (80.0, 0.0)], kind="0100"),
    ]

    rows, summary = _run_tool4_case(
        tmp_path,
        case_name="divmerge_entrance_exit_road",
        nodes=nodes,
        roads=roads,
    )

    assert rows == {}
    assert summary["counts"]["entrance_exit_road_count"] == 1
    assert summary["counts"]["divmerge_entrance_exit_suppressed_count"] == 1
    suppressed = summary["divmerge_entrance_exit_suppressed"][0]
    assert suppressed["reason"] == "related_road_kind_suffix_17"
    assert suppressed["entrance_exit_road_ids"] == ["r-side-div"]


def test_tool4_suppresses_divmerge_error_when_vertical_road_is_left_side(tmp_path: Path) -> None:
    nodes = [
        _node("10", 1, -20.0, 0.0),
        _node("100", 16, 0.0, 0.0),
        _node("150", 1, 40.0, 0.0),
        _node("200", 8, 80.0, 0.0),
        _node("210", 1, 100.0, 0.0),
        _node("300", 1, 40.0, 40.0),
    ]
    roads = [
        _road("r-in-div", "10", "100", [(-20.0, 0.0), (0.0, 0.0)]),
        _road("r-main-1", "100", "150", [(0.0, 0.0), (40.0, 0.0)]),
        _road("r-main-2", "150", "200", [(40.0, 0.0), (80.0, 0.0)]),
        _road("r-merge-out", "200", "210", [(80.0, 0.0), (100.0, 0.0)]),
        _road("r-side-div", "100", "300", [(0.0, 0.0), (40.0, 40.0)]),
        _road("r-side-merge", "300", "200", [(40.0, 40.0), (80.0, 0.0)]),
    ]

    rows, summary = _run_tool4_case(
        tmp_path,
        case_name="divmerge_left_side_road",
        nodes=nodes,
        roads=roads,
    )

    assert rows == {}
    assert summary["counts"]["divmerge_right_side_suppressed_count"] == 1
    suppressed = summary["divmerge_right_side_suppressed"][0]
    assert suppressed["reason"] == "vertical_road_not_right_side"
    assert suppressed["diverge_side_is_right"] is False
    assert suppressed["merge_side_is_right"] is False


def test_tool4_script_help() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/t08_tool4_junction_type_repair.py", "--help"],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0
    assert "--nodes-error-output" in result.stdout
    assert "id/kind_2" in result.stdout


def test_tool4_suppresses_t_error_when_advance_right_turn_excluded_degree_is_2_2(tmp_path: Path) -> None:
    nodes_gpkg = tmp_path / "input" / "nodes.gpkg"
    roads_gpkg = tmp_path / "input" / "roads.gpkg"
    nodes_error_output = tmp_path / "out" / "nodes_error.gpkg"
    summary_output = tmp_path / "out" / "nodes_error_summary.json"

    nodes = [
        _node("500", 2048, 0.0, 0.0),
        _node("510", 1, -10.0, -5.0),
        _node("511", 1, -10.0, 5.0),
        _node("520", 1, 10.0, -5.0),
        _node("521", 1, 10.0, 5.0),
        _node("530", 1, 15.0, -15.0),
    ]
    roads = [
        _road("r-in-1", "510", "500", [(-10.0, -5.0), (0.0, 0.0)], kind="0100", formway=0),
        _road("r-in-2", "511", "500", [(-10.0, 5.0), (0.0, 0.0)], kind="0100", formway=0),
        _road("r-out-1", "500", "520", [(0.0, 0.0), (10.0, -5.0)], kind="0100", formway=0),
        _road("r-out-2", "500", "521", [(0.0, 0.0), (10.0, 5.0)], kind="0100", formway=0),
        _road("r-advance-right", "500", "530", [(0.0, 0.0), (15.0, -15.0)], kind="0100", formway=128),
    ]
    write_gpkg(nodes_gpkg, nodes, crs_text="EPSG:3857")
    write_gpkg(roads_gpkg, roads, crs_text="EPSG:3857")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool4_junction_type_repair.py",
            "--nodes-gpkg",
            str(nodes_gpkg),
            "--roads-gpkg",
            str(roads_gpkg),
            "--nodes-error-output",
            str(nodes_error_output),
            "--summary-output",
            str(summary_output),
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    _, rows = _read_rows(nodes_error_output)
    assert rows == {}
    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["counts"]["error_feature_count"] == 0
    assert summary["counts"]["advance_right_turn_road_count"] == 1
    assert summary["counts"]["degree_exception_suppressed_count"] == 1
    assert summary["field_audit"]["node_kind_2_field"] == "kind_2"
    assert summary["field_audit"]["road_formway_field"] == "formway"
    assert summary["degree_exceptions"][0]["error_type"] == "错误T型路口"
    assert summary["degree_exceptions"][0]["effective_in_degree"] == 2
    assert summary["degree_exceptions"][0]["effective_out_degree"] == 2
    assert summary["degree_exceptions"][0]["excluded_advance_right_turn_road_ids"] == ["r-advance-right"]


def test_tool4_suppresses_t_error_when_auxiliary_road_excluded_degree_is_2_2(tmp_path: Path) -> None:
    nodes_gpkg = tmp_path / "input" / "nodes.gpkg"
    roads_gpkg = tmp_path / "input" / "roads.gpkg"
    nodes_error_output = tmp_path / "out" / "nodes_error.gpkg"
    summary_output = tmp_path / "out" / "nodes_error_summary.json"

    nodes = [
        _node("600", 2048, 0.0, 0.0),
        _node("610", 1, -10.0, -5.0),
        _node("611", 1, -10.0, 5.0),
        _node("620", 1, 10.0, -5.0),
        _node("621", 1, 10.0, 5.0),
        _node("630", 1, 15.0, -15.0),
    ]
    roads = [
        _road("r-in-1", "610", "600", [(-10.0, -5.0), (0.0, 0.0)], kind="0100", formway=0),
        _road("r-in-2", "611", "600", [(-10.0, 5.0), (0.0, 0.0)], kind="0100", formway=0),
        _road("r-out-1", "600", "620", [(0.0, 0.0), (10.0, -5.0)], kind="0100", formway=0),
        _road("r-out-2", "600", "621", [(0.0, 0.0), (10.0, 5.0)], kind="0100", formway=0),
        _road("r-aux", "600", "630", [(0.0, 0.0), (15.0, -15.0)], kind="020A|0100", formway=0),
    ]
    write_gpkg(nodes_gpkg, nodes, crs_text="EPSG:3857")
    write_gpkg(roads_gpkg, roads, crs_text="EPSG:3857")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool4_junction_type_repair.py",
            "--nodes-gpkg",
            str(nodes_gpkg),
            "--roads-gpkg",
            str(roads_gpkg),
            "--nodes-error-output",
            str(nodes_error_output),
            "--summary-output",
            str(summary_output),
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    _, rows = _read_rows(nodes_error_output)
    assert rows == {}
    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["counts"]["error_feature_count"] == 0
    assert summary["counts"]["auxiliary_road_count"] == 1
    assert summary["counts"]["degree_exception_suppressed_count"] == 1
    assert summary["field_audit"]["node_kind_2_field"] == "kind_2"
    assert summary["field_audit"]["road_kind_field"] == "kind"
    assert summary["degree_exceptions"][0]["error_type"] == "错误T型路口"
    assert summary["degree_exceptions"][0]["effective_in_degree"] == 2
    assert summary["degree_exceptions"][0]["effective_out_degree"] == 2
    assert summary["degree_exceptions"][0]["excluded_auxiliary_road_ids"] == ["r-aux"]
