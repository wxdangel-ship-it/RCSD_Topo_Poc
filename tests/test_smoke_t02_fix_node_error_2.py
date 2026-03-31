from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import fiona
import pytest
from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc import cli
from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector


def _load_properties_by_id(path: Path) -> dict[str, dict]:
    with fiona.open(path) as src:
        return {str(feature["properties"]["id"]): dict(feature["properties"]) for feature in src}


def _load_ids(path: Path) -> list[str]:
    with fiona.open(path) as src:
        return [str(feature["properties"]["id"]) for feature in src]


@pytest.mark.smoke
def test_smoke_t02_fix_node_error_2() -> None:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    root = Path("outputs/_work/smoke_t02_fix_node_error_2") / f"{run_id}_{os.getpid()}"
    inputs_dir = root / "inputs"
    outputs_dir = root / "run"
    inputs_dir.mkdir(parents=True, exist_ok=True)

    node_error2_path = inputs_dir / "node_error_2.gpkg"
    nodes_path = inputs_dir / "nodes.gpkg"
    roads_path = inputs_dir / "roads.gpkg"
    intersection_path = inputs_dir / "RCSDIntersection.gpkg"
    nodes_fix_path = outputs_dir / "nodes_fix.gpkg"
    roads_fix_path = outputs_dir / "roads_fix.gpkg"
    report_path = outputs_dir / "fix_report.json"

    write_vector(
        node_error2_path,
        [
            {
                "properties": {"id": "10", "junction_id": "10", "error_type": "node_error_2"},
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {"id": "20", "junction_id": "20", "error_type": "node_error_2"},
                "geometry": Point(10.0, 0.0),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        nodes_path,
        [
            {
                "properties": {"id": "10", "mainnodeid": "10", "kind_2": 64, "grade_2": 2, "subnodeid": None},
                "geometry": Point(0.0, 0.0),
            },
            {
                "properties": {"id": "11", "mainnodeid": "10", "kind_2": 0, "grade_2": 0, "subnodeid": None},
                "geometry": Point(2.0, 0.0),
            },
            {
                "properties": {"id": "20", "mainnodeid": "20", "kind_2": 2048, "grade_2": 1, "subnodeid": None},
                "geometry": Point(10.0, 0.0),
            },
            {
                "properties": {"id": "21", "mainnodeid": "20", "kind_2": 0, "grade_2": 0, "subnodeid": None},
                "geometry": Point(12.0, 0.0),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        roads_path,
        [
            {
                "properties": {"id": "r-in-1", "snodeid": "10", "enodeid": "20", "direction": 0},
                "geometry": LineString([(0.0, 0.0), (10.0, 0.0)]),
            },
            {
                "properties": {"id": "r-in-2", "snodeid": "11", "enodeid": "21", "direction": 0},
                "geometry": LineString([(2.0, 0.0), (12.0, 0.0)]),
            },
        ],
        crs_text="EPSG:3857",
    )
    write_vector(
        intersection_path,
        [
            {
                "properties": {"id": "A"},
                "geometry": Polygon([(-1.0, -1.0), (20.0, -1.0), (20.0, 1.0), (-1.0, 1.0), (-1.0, -1.0)]),
            }
        ],
        crs_text="EPSG:3857",
    )

    exit_code = cli.main(
        [
            "t02-fix-node-error-2",
            "--node-error2-path",
            str(node_error2_path),
            "--nodes-path",
            str(nodes_path),
            "--roads-path",
            str(roads_path),
            "--intersection-path",
            str(intersection_path),
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

    nodes_fix = _load_properties_by_id(nodes_fix_path)
    assert nodes_fix["10"]["kind_2"] == 4
    assert nodes_fix["10"]["grade_2"] == 1
    assert nodes_fix["10"]["subnodeid"] == "11,20,21"
    assert nodes_fix["20"]["mainnodeid"] == "10"
    assert _load_ids(roads_fix_path) == []

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["counts"]["merged_intersection_count"] == 1
    assert report["rows"][0]["deleted_road_ids"] == ["r-in-1", "r-in-2"]
