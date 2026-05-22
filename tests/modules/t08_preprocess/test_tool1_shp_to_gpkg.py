from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fiona
import shapefile
from pyproj import CRS


def _write_polyline_shapefile(path: Path, *, row_id: str, epsg: int = 4326) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with shapefile.Writer(str(path), shapeType=shapefile.POLYLINE) as writer:
        writer.field("id", "C", size=20)
        writer.line([[[116.3, 39.9], [116.3001, 39.9001]]])
        writer.record(row_id)
    path.with_suffix(".prj").write_text(CRS.from_epsg(epsg).to_wkt(), encoding="utf-8")


def _read_gpkg(path: Path) -> tuple[int | None, int]:
    with fiona.open(path) as source:
        crs_value = source.crs_wkt or source.crs
        epsg = CRS.from_user_input(crs_value).to_epsg() if crs_value else None
        count = len(source)
    return epsg, count


def test_tool1_script_converts_multiple_shapefiles_to_gpkg(tmp_path: Path) -> None:
    shp_a = tmp_path / "input" / "a_roads.shp"
    shp_b = tmp_path / "input" / "b_roads.shp"
    out_dir = tmp_path / "out"
    summary_path = tmp_path / "summary" / "tool1_summary.json"
    _write_polyline_shapefile(shp_a, row_id="a")
    _write_polyline_shapefile(shp_b, row_id="b")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool1_shp_to_gpkg.py",
            "--input-shp",
            str(shp_a),
            "--input-shp",
            str(shp_b),
            "--out-dir",
            str(out_dir),
            "--summary-output",
            str(summary_path),
            "--target-epsg",
            "3857",
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (out_dir / "a_roads.gpkg").is_file()
    assert (out_dir / "b_roads.gpkg").is_file()
    epsg_a, count_a = _read_gpkg(out_dir / "a_roads.gpkg")
    epsg_b, count_b = _read_gpkg(out_dir / "b_roads.gpkg")
    assert epsg_a == 3857
    assert epsg_b == 3857
    assert count_a == 1
    assert count_b == 1

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["input_count"] == 2
    assert summary["converted_count"] == 2
    assert summary["failed_count"] == 0
    assert summary["total_feature_count"] == 2
