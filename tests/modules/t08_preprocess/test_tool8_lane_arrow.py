from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import fiona
from pyproj import CRS
from shapely.geometry import LineString, Point, shape

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg


def _node(node_id: str, x: float, y: float) -> dict:
    return {"properties": {"id": node_id}, "geometry": Point(x, y)}


def _road(road_id: str, direction: int, coords: list[tuple[float, float]]) -> dict:
    return {"properties": {"id": road_id, "direction": direction}, "geometry": LineString(coords)}


def _write_lane_table(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE Laneguangdong1 (
                LinkID INTEGER,
                Seq_Nm INTEGER,
                Arrow_Dir TEXT,
                Lane_Dir INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO Laneguangdong1 (LinkID, Seq_Nm, Arrow_Dir, Lane_Dir) VALUES (?, ?, ?, ?)",
            [
                (100, 2, "L,R", 3),
                (100, 1, "S", 2),
                (200, 1, "U", 2),
                (200, 2, "R", 3),
                (300, 1, "S,R", 3),
                (500, 1, "A", 2),
                (999, 1, "S", 2),
                (400, 1, "", 2),
            ],
        )
        conn.commit()


def test_tool8_builds_lane_level_arrow_lines(tmp_path: Path) -> None:
    root = tmp_path / "tool8"
    lane_gpkg = root / "input" / "Laneguangdong1.gpkg"
    swnode_gpkg = root / "input" / "A200-2025M12-node.gpkg"
    swroad_gpkg = root / "input" / "A200-2025M12-road.gpkg"
    arrow_output = root / "out" / "sw_arrow_tool8.gpkg"
    summary_output = root / "out" / "sw_arrow_summary_tool8.json"
    _write_lane_table(lane_gpkg)
    write_gpkg(
        swnode_gpkg,
        [_node("n1", 0.0, 0.0), _node("n2", 10.0, 0.0)],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        swroad_gpkg,
        [
            _road("100", 2, [(0.0, 0.0), (10.0, 0.0)]),
            _road("200", 3, [(0.0, 10.0), (10.0, 10.0)]),
            _road("300", 1, [(0.0, 20.0), (10.0, 20.0)]),
            _road("400", 2, [(0.0, 30.0), (10.0, 30.0)]),
            _road("500", 0, [(0.0, 40.0), (10.0, 40.0)]),
        ],
        crs_text="EPSG:3857",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool8_lane_arrow.py",
            "--lane-gpkg",
            str(lane_gpkg),
            "--swnode-gpkg",
            str(swnode_gpkg),
            "--swroad-gpkg",
            str(swroad_gpkg),
            "--arrow-output",
            str(arrow_output),
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
    with fiona.open(arrow_output) as source:
        crs_value = source.crs_wkt or source.crs
        assert CRS.from_user_input(crs_value).to_epsg() == 3857
        rows = list(source)
    assert len(rows) == 8

    arrow_rows = [
        (feature["properties"]["linkid"], feature["properties"]["lane_index"], feature["properties"]["arrow"])
        for feature in rows
    ]
    assert arrow_rows == [
        ("100", 1, "S"),
        ("100", 2, "L"),
        ("100", 3, "R"),
        ("200", 1, "U"),
        ("200", 2, "R"),
        ("300", 1, "S"),
        ("300", 2, "R"),
        ("500", 1, "A"),
    ]
    geometries = [shape(feature["geometry"]) for feature in rows]
    assert list(geometries[0].coords) == [(0.0, 0.0), (10.0, 0.0)]
    assert list(geometries[1].coords) == [(10.0, 0.0), (0.0, 0.0)]
    assert list(geometries[3].coords) == [(10.0, 10.0), (0.0, 10.0)]
    assert list(geometries[4].coords) == [(0.0, 10.0), (10.0, 10.0)]
    assert list(geometries[5].coords) == [(10.0, 20.0), (0.0, 20.0)]
    assert list(geometries[7].coords) == [(0.0, 40.0), (10.0, 40.0)]

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["counts"]["lane_record_count"] == 8
    assert summary["counts"]["lane_record_with_matching_link_count"] == 7
    assert summary["counts"]["missing_link_count"] == 1
    assert summary["counts"]["empty_arrow_value_count"] == 1
    assert summary["counts"]["arrow_feature_count"] == 8
    assert summary["field_audit"]["link_field"] == "LinkID"

    with sqlite3.connect(arrow_output) as conn:
        feature_count = conn.execute(
            "SELECT feature_count FROM gpkg_ogr_contents WHERE table_name = ?",
            (arrow_output.stem,),
        ).fetchone()[0]
    assert feature_count == 8
