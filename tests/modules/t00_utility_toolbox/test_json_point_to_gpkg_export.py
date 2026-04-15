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


def test_tool10_exports_spots_as_pickup_points(tmp_path: Path) -> None:
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
                        "data": {
                            "sessionId": "session-1",
                            "hadRecommend": True,
                            "hadSpotImage": False,
                            "location": {
                                "id": "50116305274039866327",
                                "lat": "39.866327",
                                "lon": "116.305274",
                                "name": "中国黄金(恒泰广场店)",
                                "type": 96,
                                "adcode": "110106",
                                "cityAdcode": "110000",
                                "provinceAdcode": "110000",
                                "districtAdcode": "110106",
                            },
                            "card": {
                                "selectedShowId": "10116304681039866670",
                                "cardStyle": "list",
                                "title": "请确认上车位置",
                            },
                            "spots": [
                                {
                                    "id": "10116304681039866670",
                                    "spotId": "10116304681039866670",
                                    "lat": "39.866670",
                                    "lon": "116.304681",
                                    "name": "楼梯(金唐新光界)西北侧",
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
                                    "name": "金唐中心",
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
                )
            ]
        ),
        encoding="utf-8",
    )

    summary = run_json_point_to_gpkg_export(
        JsonPointToGpkgConfig(
            input_path=input_path,
            output_path=output_path,
            run_id="test_tool10_spots",
            progress_interval=1,
        )
    )

    assert summary["status"] == "completed"
    assert summary["input_format"] == "ndjson"
    assert summary["input_record_count"] == 1
    assert summary["spot_candidate_count"] == 2
    assert summary["selected_spot_count"] == 2
    assert summary["output_feature_count"] == 2
    assert summary["failed_record_count"] == 0
    assert summary["output_crs"] == "EPSG:4326"
    assert summary["layer_name"] == "pickup_spots"
    assert summary["coordinate_source_summary"] == {"data.spots.lon/lat": 2}

    mapping = summary["field_name_mapping"]
    with sqlite3.connect(output_path) as conn:
        contents_row = conn.execute("SELECT table_name, srs_id FROM gpkg_contents").fetchone()
        first_row = conn.execute(
            f'SELECT "{mapping["spot_id"]}", "{mapping["req_tid"]}", "{mapping["cen_name"]}", '
            f'"{mapping["selected_show_id"]}", "{mapping["source_crs"]}", geom '
            'FROM "pickup_spots" ORDER BY fid LIMIT 1'
        ).fetchone()
        feature_count = conn.execute('SELECT COUNT(*) FROM "pickup_spots"').fetchone()[0]

    assert contents_row == ("pickup_spots", 4326)
    assert feature_count == 2
    assert first_row[0] == "10116304681039866670"
    assert first_row[1] == "643137"
    assert "中国黄金" in first_row[2]
    assert first_row[3] == "10116304681039866670"
    assert first_row[4] == "raw_lonlat_unconfirmed"

    geometry = _decode_gpkg_geometry(first_row[5])
    assert geometry.geom_type == "Point"
    assert abs(geometry.x - 116.304681) < 1e-9
    assert abs(geometry.y - 39.866670) < 1e-9


def test_tool10_supports_default_pickup_filter(tmp_path: Path) -> None:
    input_path = tmp_path / "beijing_array.json"
    output_path = tmp_path / "beijing_array.gpkg"
    input_path.write_text(
        json.dumps(
            [
                {
                    "tid": "1001",
                    "gd_id": "nested-1",
                    "success": True,
                    "crawl_time": "2022-11-10 18:13:41",
                    "data": {
                        "hadRecommend": True,
                        "hadSpotImage": False,
                        "location": {
                            "id": "center-1",
                            "lat": "39.900000",
                            "lon": "116.300000",
                            "name": "center-name",
                            "type": 1,
                        },
                        "card": {
                            "selectedShowId": "spot-2",
                            "cardStyle": "list",
                            "title": "请选择",
                        },
                        "spots": [
                            {"id": "spot-1", "lon": "116.300001", "lat": "39.900001", "isRecommend": 0},
                            {"id": "spot-2", "lon": "116.300002", "lat": "39.900002", "isRecommend": 0},
                            {"id": "spot-3", "lon": "116.300003", "lat": "39.900003", "isRecommend": 1},
                        ],
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
            output_path=output_path,
            run_id="test_tool10_default_pickup",
            progress_interval=1,
            spot_filter_mode="default_pickup",
        )
    )

    assert summary["status"] == "completed"
    assert summary["input_format"] == "json-array"
    assert summary["spot_filter_mode"] == "default_pickup"
    assert summary["spot_candidate_count"] == 3
    assert summary["selected_spot_count"] == 2
    assert summary["filtered_out_spot_count"] == 1
    assert summary["output_feature_count"] == 2

    with sqlite3.connect(output_path) as conn:
        feature_count = conn.execute('SELECT COUNT(*) FROM "pickup_spots"').fetchone()[0]
        rows = conn.execute('SELECT spot_id FROM "pickup_spots" ORDER BY fid').fetchall()

    assert feature_count == 2
    assert rows == [("spot-2",), ("spot-3",)]


def test_tool10_stops_after_exporting_50000_spots(tmp_path: Path) -> None:
    input_path = tmp_path / "limit.json"
    output_path = tmp_path / "limit.gpkg"
    lines = []
    for index in range(1, 50003):
        lines.append(
            json.dumps(
                {
                    "tid": str(index),
                    "data": {
                        "spots": [
                            {
                                "id": f"spot-{index}",
                                "lon": "116.300000",
                                "lat": "39.900000",
                                "isRecommend": 0,
                            }
                        ]
                    },
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
    assert summary["spot_candidate_count"] == 50000
    assert summary["selected_spot_count"] == 50000
    assert summary["output_feature_count"] == 50000
    assert summary["failed_record_count"] == 0
    assert summary["stopped_by_export_limit"] is True
    assert summary["max_output_features"] == 50000

    with sqlite3.connect(output_path) as conn:
        feature_count = conn.execute('SELECT COUNT(*) FROM "pickup_spots"').fetchone()[0]

    assert feature_count == 50000
