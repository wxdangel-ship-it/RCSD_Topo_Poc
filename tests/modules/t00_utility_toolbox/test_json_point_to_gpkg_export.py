from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from shapely import from_wkb

from rcsd_topo_poc.modules.t00_utility_toolbox.json_point_to_gpkg_export import (
    JsonPointToGpkgConfig,
    run_json_point_to_gpkg_export,
)


def _decode_gpkg_geometry(blob: bytes):
    return from_wkb(blob[8:])


def test_tool10_exports_ndjson_points_without_crs_transform(tmp_path: Path) -> None:
    input_path = tmp_path / "beijing.json"
    output_path = tmp_path / "beijing.gpkg"
    input_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "_id": {"$oid": "636cced530af1c1029e6d359"},
                        "tid": "643137",
                        "gd_id": "B0FFI2YNTE",
                        "lat": "39.866327",
                        "lon": "116.305274",
                        "success": True,
                        "data": {"sessionId": "session-1", "location": {"name": "poi-1"}},
                        "other_args": {"db": "gaodedache_datas", "table_name": "beijing"},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "_id": {"$oid": "636cced530af1c1029e6d360"},
                        "tid": "643138",
                        "gd_id": "B0FFI2YNTF",
                        "lat": "39.866500",
                        "lon": "116.305500",
                        "success": False,
                        "data": {"sessionId": "session-2", "location": {"name": "poi-2"}},
                        "other_args": {"db": "gaodedache_datas", "table_name": "beijing"},
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    summary = run_json_point_to_gpkg_export(
        JsonPointToGpkgConfig(
            input_path=input_path,
            output_path=output_path,
            run_id="test_tool10_ndjson",
            progress_interval=1,
        )
    )

    assert summary["status"] == "completed"
    assert summary["input_format"] == "ndjson"
    assert summary["input_record_count"] == 2
    assert summary["output_feature_count"] == 2
    assert summary["failed_record_count"] == 0
    assert summary["output_crs"] == "EPSG:4326"
    assert summary["no_crs_transform"] is True
    assert summary["stopped_by_export_limit"] is False
    assert summary["coordinate_source_summary"] == {"top-level lon/lat": 2}

    mapping = summary["field_name_mapping"]

    with sqlite3.connect(output_path) as conn:
        contents_row = conn.execute("SELECT table_name, srs_id FROM gpkg_contents").fetchone()
        first_row = conn.execute(
            f'SELECT "{mapping["tid"]}", "{mapping["gd_id"]}", "{mapping["success"]}", '
            f'"{mapping["data"]}", geom FROM "{output_path.stem}" ORDER BY fid LIMIT 1'
        ).fetchone()

    assert contents_row == (output_path.stem, 4326)
    assert first_row[0] == "643137"
    assert first_row[1] == "B0FFI2YNTE"
    assert str(first_row[2]) == "1"
    assert "session-1" in first_row[3]

    geometry = _decode_gpkg_geometry(first_row[4])
    assert geometry.geom_type == "Point"
    assert abs(geometry.x - 116.305274) < 1e-9
    assert abs(geometry.y - 39.866327) < 1e-9


def test_tool10_supports_json_array_and_nested_location_fallback(tmp_path: Path) -> None:
    input_path = tmp_path / "beijing_array.json"
    output_path = tmp_path / "beijing_array.gpkg"
    input_path.write_text(
        json.dumps(
            [
                {
                    "_id": {"$oid": "1"},
                    "tid": "1001",
                    "gd_id": "nested-1",
                    "success": True,
                    "data": {"location": {"lat": "39.900000", "lon": "116.300000"}},
                },
                {
                    "_id": {"$oid": "2"},
                    "tid": "1002",
                    "gd_id": "bad-1",
                    "lon": "bad",
                    "lat": "39.800000",
                    "success": True,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = run_json_point_to_gpkg_export(
        JsonPointToGpkgConfig(
            input_path=input_path,
            output_path=output_path,
            run_id="test_tool10_json_array",
            progress_interval=1,
        )
    )

    assert summary["status"] == "completed"
    assert summary["input_format"] == "json-array"
    assert summary["input_record_count"] == 2
    assert summary["output_feature_count"] == 1
    assert summary["failed_record_count"] == 1
    assert summary["output_crs"] == "EPSG:4326"
    assert summary["coordinate_source_summary"] == {"data.location.lon/lat": 1}
    assert "could not convert string to float" in next(iter(summary["error_reason_summary"].keys()))

    with sqlite3.connect(output_path) as conn:
        contents_row = conn.execute("SELECT table_name, srs_id FROM gpkg_contents").fetchone()
        feature_count = conn.execute(f'SELECT COUNT(*) FROM "{output_path.stem}"').fetchone()[0]

    assert contents_row == (output_path.stem, 4326)
    assert feature_count == 1


def test_tool10_stops_after_exporting_50000_features(tmp_path: Path) -> None:
    input_path = tmp_path / "limit.json"
    output_path = tmp_path / "limit.gpkg"
    lines = []
    for index in range(1, 50003):
        lines.append(
            json.dumps(
                {
                    "_id": {"$oid": str(index)},
                    "tid": str(index),
                    "lon": "116.300000",
                    "lat": "39.900000",
                    "success": True,
                },
                ensure_ascii=False,
            )
        )
    input_path.write_text("\n".join(lines), encoding="utf-8")

    summary = run_json_point_to_gpkg_export(
        JsonPointToGpkgConfig(
            input_path=input_path,
            output_path=output_path,
            run_id="test_tool10_export_limit",
            progress_interval=10000,
        )
    )

    assert summary["status"] == "completed"
    assert summary["input_record_count"] == 50000
    assert summary["output_feature_count"] == 50000
    assert summary["failed_record_count"] == 0
    assert summary["stopped_by_export_limit"] is True
    assert summary["max_output_features"] == 50000

    with sqlite3.connect(output_path) as conn:
        feature_count = conn.execute(f'SELECT COUNT(*) FROM "{output_path.stem}"').fetchone()[0]

    assert feature_count == 50000
