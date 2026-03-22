from __future__ import annotations

import json
from pathlib import Path

import shapefile
from pyproj import CRS

from rcsd_topo_poc.modules.t00_utility_toolbox.shapefile_geojson_export import (
    ShapefileGeoJsonExportConfig,
    run_shapefile_geojson_export,
)


def _write_point_shapefile(
    path: Path,
    *,
    fields: list[tuple[str, str, int, int]],
    rows: list[tuple[list[float], list[object]]],
    epsg: int | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with shapefile.Writer(str(path), shapeType=shapefile.POINT) as writer:
        for name, field_type, size, decimal in fields:
            writer.field(name, field_type, size=size, decimal=decimal)
        for coordinates, values in rows:
            writer.point(*coordinates)
            writer.record(*values)

    if epsg is not None:
        path.with_suffix(".prj").write_text(CRS.from_epsg(epsg).to_wkt(), encoding="utf-8")


def test_tool6_exports_point_shapefile_to_geojson_3857(tmp_path: Path) -> None:
    input_path = tmp_path / "first_layer_road_net_v0" / "A200_node.shp"
    output_path = tmp_path / "first_layer_road_net_v0" / "nodes.geojson"

    _write_point_shapefile(
        input_path,
        fields=[("ID", "C", 20, 0), ("NAME", "C", 40, 0)],
        rows=[
            ([116.3000, 39.9000], ["1", "node-1"]),
            ([116.3010, 39.9010], ["2", "node-2"]),
        ],
        epsg=4326,
    )

    summary = run_shapefile_geojson_export(
        ShapefileGeoJsonExportConfig(
            input_path=input_path,
            output_path=output_path,
            target_epsg=3857,
            run_id="test_tool6_export",
        )
    )

    output_doc = json.loads(output_path.read_text(encoding="utf-8"))

    assert summary["status"] == "completed"
    assert summary["input_feature_count"] == 2
    assert summary["output_feature_count"] == 2
    assert summary["input_crs"] == "EPSG:4326"
    assert summary["output_crs"] == "EPSG:3857"
    assert summary["failed_feature_count"] == 0
    assert summary["repaired_feature_count"] == 0
    assert summary["field_names"] == ["ID", "NAME"]
    assert output_doc["crs"]["properties"]["name"] == "EPSG:3857"
    assert len(output_doc["features"]) == 2
    assert output_doc["features"][0]["properties"]["ID"] == "1"
    assert output_doc["features"][0]["properties"]["NAME"] == "node-1"


def test_tool6_blocks_when_input_crs_missing(tmp_path: Path) -> None:
    input_path = tmp_path / "first_layer_road_net_v0" / "A200_node.shp"
    output_path = tmp_path / "first_layer_road_net_v0" / "nodes.geojson"

    _write_point_shapefile(
        input_path,
        fields=[("ID", "C", 20, 0)],
        rows=[
            ([116.3000, 39.9000], ["1"]),
        ],
        epsg=None,
    )

    summary = run_shapefile_geojson_export(
        ShapefileGeoJsonExportConfig(
            input_path=input_path,
            output_path=output_path,
            target_epsg=3857,
            run_id="test_tool6_blocked",
        )
    )

    assert summary["status"] == "blocked"
    assert summary["blocking_reason"] is not None
    assert "CRS not found for shapefile" in summary["blocking_reason"]
    assert summary["output_feature_count"] == 0
    assert not output_path.exists()
