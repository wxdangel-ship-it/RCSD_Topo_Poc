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


def _road(road_id: str, coords: list[tuple[float, float]]) -> dict:
    return {"properties": {"id": road_id}, "geometry": LineString(coords)}


def _write_condition_table(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE Cguangdong1 (
                CondType INTEGER,
                inLinkID INTEGER,
                outLinkID INTEGER,
                memo TEXT
            )
            """
        )
        conn.executemany(
            "INSERT INTO Cguangdong1 (CondType, inLinkID, outLinkID, memo) VALUES (?, ?, ?, ?)",
            [
                (1, 100, 200, "touching"),
                (2, 100, 200, "wrong_type"),
                (1, 300, 400, "connected_by_line"),
                (1, 999, 200, "missing_in_link"),
            ],
        )
        conn.commit()


def test_tool7_builds_explicit_restrictions_from_condition_table(tmp_path: Path) -> None:
    root = tmp_path / "tool7"
    condition_gpkg = root / "input" / "Cguangdong1.gpkg"
    swnode_gpkg = root / "input" / "A200-2025M12-node.gpkg"
    swroad_gpkg = root / "input" / "A200-2025M12-road.gpkg"
    restriction_output = root / "out" / "sw_restriction_tool7.gpkg"
    summary_output = root / "out" / "sw_restriction_summary_tool7.json"
    _write_condition_table(condition_gpkg)
    write_gpkg(
        swnode_gpkg,
        [_node("n1", 0.0, 0.0), _node("n2", 10.0, 0.0)],
        crs_text="EPSG:3857",
    )
    write_gpkg(
        swroad_gpkg,
        [
            _road("100", [(0.0, 0.0), (10.0, 0.0)]),
            _road("200", [(10.0, 0.0), (20.0, 0.0)]),
            _road("300", [(40.0, 0.0), (50.0, 0.0)]),
            _road("400", [(50.0, 10.0), (60.0, 10.0)]),
        ],
        crs_text="EPSG:3857",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool7_traffic_restriction.py",
            "--condition-gpkg",
            str(condition_gpkg),
            "--swnode-gpkg",
            str(swnode_gpkg),
            "--swroad-gpkg",
            str(swroad_gpkg),
            "--restriction-output",
            str(restriction_output),
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
    with fiona.open(restriction_output) as source:
        crs_value = source.crs_wkt or source.crs
        assert CRS.from_user_input(crs_value).to_epsg() == 3857
        rows = list(source)
    assert len(rows) == 2
    props_by_memo = {feature["properties"]["memo"]: dict(feature["properties"]) for feature in rows}
    assert props_by_memo["touching"]["CondType"] == 1
    assert props_by_memo["connected_by_line"]["outLinkID"] == 400
    geometries = {feature["properties"]["memo"]: shape(feature["geometry"]) for feature in rows}
    assert list(geometries["touching"].coords) == [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    assert list(geometries["connected_by_line"].coords) == [
        (40.0, 0.0),
        (50.0, 0.0),
        (50.0, 10.0),
        (60.0, 10.0),
    ]

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["counts"]["condition_record_count"] == 4
    assert summary["counts"]["condition_cond_type_1_count"] == 3
    assert summary["counts"]["missing_road_count"] == 1
    assert summary["counts"]["restriction_feature_count"] == 2
    assert summary["field_audit"]["cond_type_field"] == "CondType"
