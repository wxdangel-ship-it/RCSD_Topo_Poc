from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fiona
import pytest
import shapefile
from pyproj import CRS

from rcsd_topo_poc.modules.t08_preprocess import run_t08_tool1_conversions
from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_geojson, write_gpkg


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


def _read_geojson_count(path: Path) -> int:
    with fiona.open(path) as source:
        return len(source)


def test_tool1_script_converts_supported_formats_next_to_inputs(tmp_path: Path) -> None:
    shp_a = tmp_path / "input" / "a_roads.shp"
    shp_b = tmp_path / "input" / "b_roads.shp"
    geojson_path = tmp_path / "input" / "c_roads.geojson"
    gpkg_path = tmp_path / "input" / "d_roads.gpkg"
    summary_path = tmp_path / "summary" / "tool1_summary.json"
    _write_polyline_shapefile(shp_a, row_id="a")
    _write_polyline_shapefile(shp_b, row_id="b")
    write_geojson(
        geojson_path,
        [{"properties": {"id": "c"}, "geometry": {"type": "LineString", "coordinates": [[116.31, 39.91], [116.32, 39.92]]}}],
        crs_text="EPSG:4326",
    )
    write_gpkg(
        gpkg_path,
        [{"properties": {"id": "d"}, "geometry": {"type": "LineString", "coordinates": [[116.33, 39.93], [116.34, 39.94]]}}],
        crs_text="EPSG:4326",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool1_vector_convert.py",
            "--input-shp",
            str(shp_a),
            "--input-shp",
            str(shp_b),
            "--input-geojson",
            str(geojson_path),
            "--input-gpkg",
            str(gpkg_path),
            "--summary-output",
            str(summary_path),
            "--target-epsg",
            "3857",
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
    assert "[T08 Tool1]" in result.stderr
    assert (tmp_path / "input" / "a_roads.gpkg").is_file()
    assert (tmp_path / "input" / "b_roads.gpkg").is_file()
    assert (tmp_path / "input" / "c_roads.gpkg").is_file()
    assert (tmp_path / "input" / "d_roads.geojson").is_file()
    epsg_a, count_a = _read_gpkg(tmp_path / "input" / "a_roads.gpkg")
    epsg_b, count_b = _read_gpkg(tmp_path / "input" / "b_roads.gpkg")
    epsg_c, count_c = _read_gpkg(tmp_path / "input" / "c_roads.gpkg")
    assert epsg_a == 3857
    assert epsg_b == 3857
    assert epsg_c == 3857
    assert count_a == 1
    assert count_b == 1
    assert count_c == 1
    assert _read_geojson_count(tmp_path / "input" / "d_roads.geojson") == 1

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["input_count"] == 4
    assert summary["converted_count"] == 4
    assert summary["failed_count"] == 0
    assert summary["total_feature_count"] == 4
    assert summary["elapsed_seconds"] >= 0
    assert summary["features_per_second"] is not None
    conversions = {row["conversion"] for row in summary["file_results"]}
    assert conversions == {"shp_to_gpkg", "geojson_to_gpkg", "gpkg_to_geojson"}
    assert all(row["source_feature_count"] == 1 for row in summary["file_results"])
    assert all(row["features_per_second"] is not None for row in summary["file_results"])
    assert all(Path(row["output_path"]).parent == Path(row["input_path"]).parent for row in summary["file_results"])


def test_tool1_rejects_same_run_input_output_collision(tmp_path: Path) -> None:
    geojson_path = tmp_path / "input" / "roads.geojson"
    gpkg_path = tmp_path / "input" / "roads.gpkg"
    write_geojson(
        geojson_path,
        [{"properties": {"id": "g"}, "geometry": {"type": "LineString", "coordinates": [[116.31, 39.91], [116.32, 39.92]]}}],
        crs_text="EPSG:4326",
    )
    write_gpkg(
        gpkg_path,
        [{"properties": {"id": "p"}, "geometry": {"type": "LineString", "coordinates": [[116.33, 39.93], [116.34, 39.94]]}}],
        crs_text="EPSG:4326",
    )

    with pytest.raises(ValueError, match="overwrite an input"):
        run_t08_tool1_conversions(
            input_geojson_paths=[geojson_path],
            input_gpkg_paths=[gpkg_path],
        )
