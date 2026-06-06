from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import fiona
from pyproj import CRS
from shapely.geometry import LineString, Point, Polygon

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg


def _node(node_id: str, x: float, y: float, mainnodeid: str = "0") -> dict:
    return {"properties": {"id": node_id, "mainnodeid": mainnodeid}, "geometry": Point(x, y)}


def _road(road_id: str, snodeid: str, enodeid: str, coords: list[tuple[float, float]]) -> dict:
    return {
        "properties": {"id": road_id, "snodeid": snodeid, "enodeid": enodeid},
        "geometry": LineString(coords),
    }


def test_tool9_cleans_rcsd_nodes_and_roads_by_road_surface(tmp_path: Path) -> None:
    root = tmp_path / "tool9"
    rcsdnode_gpkg = root / "input" / "rcsdnode.gpkg"
    rcsdroad_gpkg = root / "input" / "rcsdroad.gpkg"
    road_surface_gpkg = root / "input" / "road_surface.gpkg"
    nodes_output = root / "out" / "rcsdnode_clean_tool9.gpkg"
    roads_output = root / "out" / "rcsdroad_clean_tool9.gpkg"
    summary_output = root / "out" / "rcsd_clean_summary_tool9.json"

    write_gpkg(
        road_surface_gpkg,
        [{"properties": {"id": "surface"}, "geometry": Polygon([(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)])}],
        crs_text="EPSG:3857",
        geometry_type="Polygon",
    )
    write_gpkg(
        rcsdnode_gpkg,
        [
            _node("n1", 1.0, 1.0),
            _node("n2", 2.0, 2.0, "100"),
            _node("n3", 3.0, 3.0, "100"),
            _node("n4", 30.0, 30.0),
            _node("n5", 4.0, 4.0, "200"),
            _node("n6", 40.0, 40.0, "200"),
        ],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        rcsdroad_gpkg,
        [
            _road("r1", "n1", "n2", [(1.0, 1.0), (2.0, 2.0)]),
            _road("r2", "n2", "n4", [(2.0, 2.0), (30.0, 30.0)]),
            _road("r3", "n5", "n6", [(4.0, 4.0), (40.0, 40.0)]),
            _road("r4", "n1", "n3", [(30.0, 5.0), (40.0, 5.0)]),
            _road("r5", "n2", "n3", [(2.0, 2.0), (3.0, 3.0)]),
        ],
        crs_text="EPSG:3857",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool9_rcsd_cleaning.py",
            "--rcsdnode-gpkg",
            str(rcsdnode_gpkg),
            "--rcsdroad-gpkg",
            str(rcsdroad_gpkg),
            "--road-surface-gpkg",
            str(road_surface_gpkg),
            "--nodes-output",
            str(nodes_output),
            "--roads-output",
            str(roads_output),
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
    with fiona.open(nodes_output) as source:
        node_crs_value = source.crs_wkt or source.crs
        assert CRS.from_user_input(node_crs_value).to_epsg() == 3857
        kept_node_ids = {str(feature["properties"]["id"]) for feature in source}
    with fiona.open(roads_output) as source:
        road_crs_value = source.crs_wkt or source.crs
        assert CRS.from_user_input(road_crs_value).to_epsg() == 3857
        kept_road_ids = {str(feature["properties"]["id"]) for feature in source}

    assert kept_node_ids == {"n1", "n2", "n3"}
    assert kept_road_ids == {"r1", "r5"}

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["counts"]["rcsdnode_input_count"] == 6
    assert summary["counts"]["rcsdnode_individual_covered_count"] == 4
    assert summary["counts"]["rcsdnode_output_count"] == 3
    assert summary["counts"]["rcsdnode_deleted_count"] == 3
    assert summary["counts"]["semantic_group_count"] == 4
    assert summary["counts"]["semantic_group_kept_count"] == 2
    assert summary["counts"]["semantic_group_deleted_count"] == 2
    assert summary["counts"]["rcsdroad_input_count"] == 5
    assert summary["counts"]["rcsdroad_surface_intersect_count"] == 4
    assert summary["counts"]["rcsdroad_surface_not_intersect_count"] == 1
    assert summary["counts"]["rcsdroad_endpoint_not_kept_count"] == 2
    assert summary["counts"]["rcsdroad_output_count"] == 2

    for output_path, expected_count in [(nodes_output, 3), (roads_output, 2)]:
        with sqlite3.connect(output_path) as conn:
            feature_count = conn.execute(
                "SELECT feature_count FROM gpkg_ogr_contents WHERE table_name = ?",
                (output_path.stem,),
            ).fetchone()[0]
        assert feature_count == expected_count
