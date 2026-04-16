from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import fiona
import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc import cli
from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector


@pytest.mark.smoke
def test_smoke_t02_aggregate_continuous_divmerge(capsys: pytest.CaptureFixture[str]) -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = Path("outputs/_work/smoke_t02_aggregate_continuous_divmerge") / f"{run_id}_{os.getpid()}"
    inputs_dir = root / "inputs"
    outputs_dir = root / "run"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    nodes_path = inputs_dir / "nodes.gpkg"
    roads_path = inputs_dir / "roads.gpkg"
    nodes_fix_path = outputs_dir / "nodes_fix.gpkg"
    roads_fix_path = outputs_dir / "roads_fix.gpkg"
    report_path = outputs_dir / "report.json"

    write_vector(
        nodes_path,
        [
            {"properties": {"id": "100", "mainnodeid": "100", "has_evd": "yes", "is_anchor": "no", "kind": 16, "grade": 2, "kind_2": 16, "grade_2": 2, "subnodeid": None}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "200", "mainnodeid": "200", "has_evd": "yes", "is_anchor": "no", "kind": 8, "grade": 1, "kind_2": 8, "grade_2": 1, "subnodeid": None}, "geometry": Point(60.0, 0.0)},
            {"properties": {"id": "101", "mainnodeid": None, "has_evd": None, "is_anchor": None, "kind": None, "grade": None, "kind_2": None, "grade_2": None, "subnodeid": None}, "geometry": Point(20.0, 0.0)},
            {"properties": {"id": "102", "mainnodeid": None, "has_evd": None, "is_anchor": None, "kind": None, "grade": None, "kind_2": None, "grade_2": None, "subnodeid": None}, "geometry": Point(40.0, 0.0)},
            {"properties": {"id": "110", "mainnodeid": None, "has_evd": None, "is_anchor": None, "kind": None, "grade": None, "kind_2": None, "grade_2": None, "subnodeid": None}, "geometry": Point(0.0, 10.0)},
            {"properties": {"id": "120", "mainnodeid": None, "has_evd": None, "is_anchor": None, "kind": None, "grade": None, "kind_2": None, "grade_2": None, "subnodeid": None}, "geometry": Point(0.0, -10.0)},
            {"properties": {"id": "210", "mainnodeid": None, "has_evd": None, "is_anchor": None, "kind": None, "grade": None, "kind_2": None, "grade_2": None, "subnodeid": None}, "geometry": Point(60.0, 10.0)},
            {"properties": {"id": "220", "mainnodeid": None, "has_evd": None, "is_anchor": None, "kind": None, "grade": None, "kind_2": None, "grade_2": None, "subnodeid": None}, "geometry": Point(60.0, -10.0)},
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {"properties": {"id": "r-main-1", "snodeid": "100", "enodeid": "101", "direction": 2, "formway": 1}, "geometry": LineString([(0.0, 0.0), (20.0, 0.0)])},
            {"properties": {"id": "r-main-2", "snodeid": "101", "enodeid": "102", "direction": 2, "formway": 1}, "geometry": LineString([(20.0, 0.0), (40.0, 0.0)])},
            {"properties": {"id": "r-main-3", "snodeid": "102", "enodeid": "200", "direction": 2, "formway": 1}, "geometry": LineString([(40.0, 0.0), (60.0, 0.0)])},
            {"properties": {"id": "r-100-out", "snodeid": "100", "enodeid": "110", "direction": 2, "formway": 1}, "geometry": LineString([(0.0, 0.0), (0.0, 10.0)])},
            {"properties": {"id": "r-100-in", "snodeid": "120", "enodeid": "100", "direction": 2, "formway": 1}, "geometry": LineString([(0.0, -10.0), (0.0, 0.0)])},
            {"properties": {"id": "r-200-out", "snodeid": "200", "enodeid": "210", "direction": 2, "formway": 1}, "geometry": LineString([(60.0, 0.0), (60.0, 10.0)])},
            {"properties": {"id": "r-200-in", "snodeid": "220", "enodeid": "200", "direction": 2, "formway": 1}, "geometry": LineString([(60.0, -10.0), (60.0, 0.0)])},
        ],
        crs_text="EPSG:3857",
    )

    exit_code = cli.main(
        [
            "t02-aggregate-continuous-divmerge",
            "--nodes-path",
            str(nodes_path),
            "--roads-path",
            str(roads_path),
            "--nodes-fix-path",
            str(nodes_fix_path),
            "--roads-fix-path",
            str(roads_fix_path),
            "--report-path",
            str(report_path),
        ]
    )

    assert exit_code == 0
    assert nodes_fix_path.is_file()
    assert roads_fix_path.is_file()
    assert report_path.is_file()

    stdout = capsys.readouterr().out
    assert "Complex junction count: 1" in stdout
    assert "Complex junction mainnodeids: 200" in stdout

    with fiona.open(nodes_fix_path) as src:
        props_by_id = {str(feature["properties"]["id"]): dict(feature["properties"]) for feature in src}
    assert props_by_id["200"]["kind_2"] == 128
    assert props_by_id["100"]["mainnodeid"] == "200"

    report_doc = json.loads(report_path.read_text(encoding="utf-8"))
    assert report_doc["counts"]["complex_junction_count"] == 1
    assert report_doc["complex_mainnodeids"] == ["200"]
    assert report_doc["counts"]["aggregated_component_count"] == 1
