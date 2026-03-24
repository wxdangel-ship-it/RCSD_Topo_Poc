from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from rcsd_topo_poc.modules.t00_utility_toolbox.geojson_to_gpkg_export import (
    GeoJsonToGpkgDirectoryConfig,
    run_geojson_to_gpkg_directory_export,
)


def _write_feature_collection(
    path: Path,
    features: list[dict[str, object]],
    *,
    crs_name: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "type": "FeatureCollection",
        "features": features,
    }
    if crs_name is not None:
        payload["crs"] = {"type": "name", "properties": {"name": crs_name}}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_tool7_converts_only_top_level_geojson_files_to_gpkg(tmp_path: Path) -> None:
    export_dir = tmp_path / "geojson_dir"
    _write_feature_collection(
        export_dir / "roads.geojson",
        [
            {
                "type": "Feature",
                "properties": {"name": "r-1", "speed": 60},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[12657000.0, 2545000.0], [12657100.0, 2545050.0]],
                },
            }
        ],
        crs_name="EPSG:3857",
    )
    _write_feature_collection(
        export_dir / "nodes.geojson",
        [
            {
                "type": "Feature",
                "properties": {"name": "n-1"},
                "geometry": {
                    "type": "Point",
                    "coordinates": [116.30, 39.90],
                },
            }
        ],
    )
    _write_feature_collection(
        export_dir / "nested" / "ignored.geojson",
        [
            {
                "type": "Feature",
                "properties": {"name": "ignored"},
                "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
            }
        ],
        crs_name="EPSG:4326",
    )

    summary = run_geojson_to_gpkg_directory_export(
        GeoJsonToGpkgDirectoryConfig(
            directory_path=export_dir,
            run_id="test_tool7_top_level_only",
        )
    )

    roads_gpkg = export_dir / "roads.gpkg"
    nodes_gpkg = export_dir / "nodes.gpkg"
    ignored_gpkg = export_dir / "nested" / "ignored.gpkg"

    assert summary["geojson_file_count"] == 2
    assert summary["converted_file_count"] == 2
    assert summary["failed_file_count"] == 0
    assert roads_gpkg.is_file()
    assert nodes_gpkg.is_file()
    assert not ignored_gpkg.exists()

    roads_result = next(item for item in summary["file_results"] if item["output_table_name"] == "roads")
    nodes_result = next(item for item in summary["file_results"] if item["output_table_name"] == "nodes")
    assert roads_result["source_crs"] == "EPSG:3857"
    assert nodes_result["source_crs"] == "EPSG:4326"

    with sqlite3.connect(roads_gpkg) as conn:
        row = conn.execute("SELECT table_name, srs_id FROM gpkg_contents").fetchone()
        feature_count = conn.execute('SELECT COUNT(*) FROM "roads"').fetchone()[0]
        geom_blob = conn.execute('SELECT geom FROM "roads"').fetchone()[0]

    assert row == ("roads", 3857)
    assert feature_count == 1
    assert geom_blob[:2] == b"GP"

    with sqlite3.connect(nodes_gpkg) as conn:
        row = conn.execute("SELECT table_name, srs_id FROM gpkg_contents").fetchone()
        feature_count = conn.execute('SELECT COUNT(*) FROM "nodes"').fetchone()[0]

    assert row == ("nodes", 4326)
    assert feature_count == 1


def test_tool7_renames_reserved_output_field_names(tmp_path: Path) -> None:
    export_dir = tmp_path / "geojson_dir"
    _write_feature_collection(
        export_dir / "conflict.geojson",
        [
            {
                "type": "Feature",
                "properties": {"fid": 7, "geom": "text-geom", "name": "a"},
                "geometry": {
                    "type": "Point",
                    "coordinates": [12657000.0, 2545000.0],
                },
            }
        ],
        crs_name="EPSG:3857",
    )

    summary = run_geojson_to_gpkg_directory_export(
        GeoJsonToGpkgDirectoryConfig(
            directory_path=export_dir,
            run_id="test_tool7_field_mapping",
        )
    )

    result = summary["file_results"][0]
    assert result["field_name_mapping"]["fid"].lower() != "fid"
    assert result["field_name_mapping"]["geom"].lower() != "geom"

    with sqlite3.connect(export_dir / "conflict.gpkg") as conn:
        columns = [row[1] for row in conn.execute('PRAGMA table_info("conflict")').fetchall()]
        row = conn.execute(
            f'SELECT "{result["field_name_mapping"]["fid"]}", "{result["field_name_mapping"]["geom"]}", "name" '
            'FROM "conflict"'
        ).fetchone()

    assert "fid" in columns
    assert "geom" in columns
    assert result["field_name_mapping"]["fid"] in columns
    assert result["field_name_mapping"]["geom"] in columns
    assert row == (7, "text-geom", "a")
