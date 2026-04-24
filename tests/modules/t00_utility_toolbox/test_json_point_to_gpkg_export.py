from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from shapely import from_wkb

from rcsd_topo_poc.modules.t00_utility_toolbox.json_point_to_gpkg_export import (
    ALL_LAYER_NAME,
    RECOMMENDED_LAYER_NAME,
    JsonPointToGpkgConfig,
    run_json_point_to_gpkg_export,
)


def _decode_gpkg_geometry(blob: bytes):
    return from_wkb(blob[8:])


def test_tool10_exports_all_and_recommended_pickup_layers(tmp_path: Path) -> None:
    input_path = tmp_path / "beijing.json"
    output_path = tmp_path / "pickup.gpkg"
    input_path.write_text(
        json.dumps(
            {
                "tid": "643137",
                "gd_id": "B0FFI2YNTE",
                "lat": "39.866327",
                "lon": "116.305274",
                "success": True,
                "data": {
                    "hadRecommend": True,
                    "hadSpotImage": False,
                    "location": {
                        "id": "50116305274039866327",
                        "lat": "39.866327",
                        "lon": "116.305274",
                        "name": "center-name",
                        "type": 96,
                        "adcode": "110106",
                        "cityAdcode": "110000",
                        "provinceAdcode": "110000",
                        "districtAdcode": "110106",
                    },
                    "card": {
                        "selectedShowId": "10116304681039866670",
                        "cardStyle": "list",
                        "title": "confirm pickup",
                    },
                    "spots": [
                        {
                            "id": "10116304681039866670",
                            "spotId": "10116304681039866670",
                            "lat": "39.866670",
                            "lon": "116.304681",
                            "name": "recommended spot",
                            "distance": 63,
                            "walkDistance": 74,
                            "isRecommend": 1,
                            "type": 7,
                            "linkId": "5121409004792186423",
                            "isNparking": 0,
                            "linkCoors": "116.303995,39.866627;116.304681,39.866670",
                            "location": "116.304681,39.866670",
                            "originId": "origin-1",
                        },
                        {
                            "id": "10116306720039866807",
                            "spotId": "10116306720039866807",
                            "lat": "39.866807",
                            "lon": "116.306720",
                            "name": "normal spot",
                            "distance": 134,
                            "walkDistance": -1,
                            "isRecommend": 0,
                            "type": 21,
                            "linkId": "5121409004792186089",
                            "isNparking": 0,
                            "linkCoors": "116.306596,39.866799;116.307342,39.866847",
                            "location": "116.306720,39.866807",
                            "originId": "",
                        },
                    ],
                },
                "other_args": {"db": "gaodedache_datas", "table_name": "beijing"},
                "crawl_time": "2022-11-10 18:13:41",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = run_json_point_to_gpkg_export(
        JsonPointToGpkgConfig(
            input_path=input_path,
            output_path=output_path,
            run_id="test_tool10_two_layers",
            progress_interval=1,
        )
    )

    assert summary["status"] == "completed"
    assert summary["input_format"] == "ndjson"
    assert summary["input_record_count"] == 1
    assert summary["spot_candidate_count"] == 2
    assert summary["all_spot_output_count"] == 2
    assert summary["recommended_spot_output_count"] == 1
    assert summary["failed_spot_count"] == 0
    assert summary["source_crs"] == "EPSG:4326"
    assert summary["output_crs"] == "EPSG:4326"
    assert summary["layer_names"] == {
        "all": ALL_LAYER_NAME,
        "recommended": RECOMMENDED_LAYER_NAME,
    }
    assert summary["coordinate_source_summary"] == {"data.spots.lon/lat": 2}

    with sqlite3.connect(output_path) as conn:
        contents = conn.execute(
            "SELECT table_name, srs_id FROM gpkg_contents ORDER BY table_name"
        ).fetchall()
        all_count = conn.execute(f'SELECT COUNT(*) FROM "{ALL_LAYER_NAME}"').fetchone()[0]
        recommended_count = conn.execute(
            f'SELECT COUNT(*) FROM "{RECOMMENDED_LAYER_NAME}"'
        ).fetchone()[0]
        all_rows = conn.execute(
            f'SELECT spot_id, req_tid, cen_name, is_recommend, geom FROM "{ALL_LAYER_NAME}" ORDER BY fid'
        ).fetchall()
        recommended_rows = conn.execute(
            f'SELECT spot_id, name, is_recommend FROM "{RECOMMENDED_LAYER_NAME}" ORDER BY fid'
        ).fetchall()

    assert contents == [(ALL_LAYER_NAME, 4326), (RECOMMENDED_LAYER_NAME, 4326)]
    assert all_count == 2
    assert recommended_count == 1
    assert all_rows[0][:4] == ("10116304681039866670", "643137", "center-name", 1)
    assert recommended_rows == [("10116304681039866670", "recommended spot", 1)]

    geometry = _decode_gpkg_geometry(all_rows[0][4])
    assert geometry.geom_type == "Point"
    assert abs(geometry.x - 116.304681) < 1e-9
    assert abs(geometry.y - 39.866670) < 1e-9


def test_tool10_supports_json_array_and_default_output_path(tmp_path: Path) -> None:
    input_path = tmp_path / "array.json"
    input_path.write_text(
        json.dumps(
            [
                {
                    "tid": "1001",
                    "data": {
                        "spots": [
                            {"id": "spot-1", "lon": "116.300001", "lat": "39.900001", "isRecommend": False},
                            {"id": "spot-2", "lon": "116.300002", "lat": "39.900002", "isRecommend": True},
                        ]
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary = run_json_point_to_gpkg_export(
        JsonPointToGpkgConfig(
            input_path=input_path,
            run_id="test_tool10_default_output",
            progress_interval=1,
        )
    )

    output_path = input_path.with_suffix(".gpkg")
    assert summary["status"] == "completed"
    assert summary["input_format"] == "json-array"
    assert summary["output_path"] == str(output_path.resolve())
    assert summary["all_spot_output_count"] == 2
    assert summary["recommended_spot_output_count"] == 1

    with sqlite3.connect(output_path) as conn:
        all_rows = conn.execute(f'SELECT spot_id FROM "{ALL_LAYER_NAME}" ORDER BY fid').fetchall()
        recommended_rows = conn.execute(
            f'SELECT spot_id FROM "{RECOMMENDED_LAYER_NAME}" ORDER BY fid'
        ).fetchall()

    assert all_rows == [("spot-1",), ("spot-2",)]
    assert recommended_rows == [("spot-2",)]
