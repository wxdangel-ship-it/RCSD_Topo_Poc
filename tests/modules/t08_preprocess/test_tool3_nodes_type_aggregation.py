from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fiona
from pyproj import CRS
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg


def _node(properties: dict, x: float, y: float) -> dict:
    return {"properties": properties, "geometry": Point(x, y)}


def _road(properties: dict, coords: list[tuple[float, float]]) -> dict:
    return {"properties": properties, "geometry": LineString(coords)}


def _read_features(path: Path) -> tuple[int | None, dict[str, dict]]:
    with fiona.open(path) as source:
        crs_value = source.crs_wkt or source.crs
        epsg = CRS.from_user_input(crs_value).to_epsg() if crs_value else None
        rows = {str(feature["properties"]["id"]): dict(feature["properties"]) for feature in source}
    return epsg, rows


def test_tool3_script_aggregates_nodes_types_and_mainnode(tmp_path: Path) -> None:
    nodes_gpkg = tmp_path / "input" / "nodes.gpkg"
    roads_gpkg = tmp_path / "input" / "roads.gpkg"
    nodes_output = tmp_path / "out" / "nodes_agg.gpkg"
    summary_output = tmp_path / "out" / "nodes_agg_summary.json"

    write_gpkg(
        nodes_gpkg,
        [
            _node({"id": "1", "kind": 1, "grade": 9, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "subnodeid": None}, 0.0, 100.0),
            _node({"id": "2", "kind": 1, "grade": 9, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "subnodeid": None}, 10.0, 100.0),
            _node({"id": "3", "kind": 1, "grade": 9, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "subnodeid": None}, 20.0, 100.0),
            _node({"id": "100", "kind": 16, "grade": 2, "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "subnodeid": None}, 0.0, 0.0),
            _node({"id": "200", "kind": 8, "grade": 1, "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "subnodeid": None}, 60.0, 0.0),
            _node({"id": "101", "kind": 1, "grade": 0, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "subnodeid": None}, 20.0, 0.0),
            _node({"id": "102", "kind": 1, "grade": 0, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "subnodeid": None}, 40.0, 0.0),
            _node({"id": "110", "kind": 1, "grade": 0, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "subnodeid": None}, 0.0, 10.0),
            _node({"id": "120", "kind": 1, "grade": 0, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "subnodeid": None}, 0.0, -10.0),
            _node({"id": "210", "kind": 1, "grade": 0, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "subnodeid": None}, 60.0, 10.0),
            _node({"id": "220", "kind": 1, "grade": 0, "mainnodeid": None, "has_evd": "no", "is_anchor": "no", "subnodeid": None}, 60.0, -10.0),
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        roads_gpkg,
        [
            _road({"id": "rr1", "snodeid": "1", "enodeid": "2", "direction": 2, "roadtype": 8}, [(0.0, 100.0), (10.0, 100.0)]),
            _road({"id": "rr2", "snodeid": "2", "enodeid": "3", "direction": 2, "roadtype": 8}, [(10.0, 100.0), (20.0, 100.0)]),
            _road({"id": "r-main-1", "snodeid": "100", "enodeid": "101", "direction": 2, "roadtype": 0}, [(0.0, 0.0), (20.0, 0.0)]),
            _road({"id": "r-main-2", "snodeid": "101", "enodeid": "102", "direction": 2, "roadtype": 0}, [(20.0, 0.0), (40.0, 0.0)]),
            _road({"id": "r-main-3", "snodeid": "102", "enodeid": "200", "direction": 2, "roadtype": 0}, [(40.0, 0.0), (60.0, 0.0)]),
            _road({"id": "r-100-out", "snodeid": "100", "enodeid": "110", "direction": 2, "roadtype": 0}, [(0.0, 0.0), (0.0, 10.0)]),
            _road({"id": "r-100-in", "snodeid": "120", "enodeid": "100", "direction": 2, "roadtype": 0}, [(0.0, -10.0), (0.0, 0.0)]),
            _road({"id": "r-200-out", "snodeid": "200", "enodeid": "210", "direction": 2, "roadtype": 0}, [(60.0, 0.0), (60.0, 10.0)]),
            _road({"id": "r-200-in", "snodeid": "220", "enodeid": "200", "direction": 2, "roadtype": 0}, [(60.0, -10.0), (60.0, 0.0)]),
        ],
        crs_text="EPSG:3857",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool3_nodes_type_aggregation.py",
            "--nodes-gpkg",
            str(nodes_gpkg),
            "--roads-gpkg",
            str(roads_gpkg),
            "--nodes-output",
            str(nodes_output),
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
    assert "[T08 Tool3]" in result.stderr
    epsg, props_by_id = _read_features(nodes_output)
    assert epsg == 3857

    assert props_by_id["1"]["kind_2"] == 64
    assert props_by_id["1"]["grade_2"] == 1
    assert props_by_id["1"]["mainnodeid"] == "1"
    assert props_by_id["2"]["kind_2"] == 0
    assert props_by_id["2"]["grade_2"] == 0
    assert props_by_id["2"]["mainnodeid"] == "1"

    assert props_by_id["200"]["kind"] == 8
    assert props_by_id["200"]["kind_2"] == 128
    assert props_by_id["200"]["mainnodeid"] == "200"
    assert props_by_id["200"]["subnodeid"] == "100,200"
    assert props_by_id["100"]["kind"] == 16
    assert props_by_id["100"]["kind_2"] == 0
    assert props_by_id["100"]["grade_2"] == 0
    assert props_by_id["100"]["mainnodeid"] == "200"

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["counts"]["roundabout_group_count"] == 1
    assert summary["counts"]["complex_junction_count"] == 1
    assert summary["complex_divmerge"]["complex_mainnodeids"] == ["200"]
    assert summary["performance"]["elapsed_seconds"] >= 0
    assert summary["performance"]["nodes_per_second"] is not None
    assert "complex_divmerge_seconds" in summary["performance"]["stage_timings"]
