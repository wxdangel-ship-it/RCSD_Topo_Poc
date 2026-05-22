from __future__ import annotations

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
            "grade": 1,
            "kind_2": kind_2,
            "grade_2": 1,
            "mainnodeid": node_id,
        },
        "geometry": Point(x, y),
    }


def _road(road_id: str, snodeid: str, enodeid: str, coords: list[tuple[float, float]], direction: int = 2) -> dict:
    return {
        "properties": {"id": road_id, "snodeid": snodeid, "enodeid": enodeid, "direction": direction},
        "geometry": LineString(coords),
    }


def _read_rows(path: Path) -> tuple[int | None, dict[str, dict]]:
    with fiona.open(path) as source:
        crs_value = source.crs_wkt or source.crs
        epsg = CRS.from_user_input(crs_value).to_epsg() if crs_value else None
        rows = {str(feature["properties"]["semantic_node_id"]): dict(feature["properties"]) for feature in source}
    return epsg, rows


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
    assert rows["400"]["error_type"] == "错误交叉路口"
    assert rows["100"]["error_type"] == "错误分歧合流路口"
    assert rows["200"]["error_type"] == "错误分歧合流路口"

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["counts"]["error_feature_count"] == 4
    assert summary["counts"]["error_count_by_type"] == {
        "错误T型路口": 1,
        "错误交叉路口": 1,
        "错误分歧合流路口": 2,
    }
    assert summary["performance"]["elapsed_seconds"] >= 0
    assert "detect_errors_seconds" in summary["performance"]["stage_timings"]
    assert summary["performance"]["road_read_mode"] == {
        "reader": "gpkg_sqlite_light",
        "selected_fields_only": True,
        "geometry_stored": False,
        "output_crs": "EPSG:3857",
        "layer_name": "roads",
    }


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
