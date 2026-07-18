from __future__ import annotations

import sqlite3
from pathlib import Path

import fiona
from shapely.geometry import LineString

from rcsd_topo_poc.modules.t01_data_preprocess.fast_gpkg_writer import (
    GPKG_IN_MEMORY_PUBLISH_MAX_RECORDS,
    _small_gpkg_template_bytes,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_vector


def test_write_vector_fast_gpkg_roundtrips_debug_line_features(tmp_path: Path) -> None:
    output_path = tmp_path / "debug_lines.gpkg"

    write_vector(
        output_path,
        [
            {
                "properties": {
                    "pair_id": "S2:1__2",
                    "road_id": "r1",
                    "road_ids": ["r1", "r2"],
                    "trunk_found": True,
                    "score": 1.5,
                },
                "geometry": LineString([(0.0, 0.0), (1.0, 1.0)]),
            },
            {
                "properties": {
                    "pair_id": "S2:2__3",
                    "road_id": "r2",
                    "road_ids": ["r3"],
                    "trunk_found": False,
                    "score": 2.0,
                },
                "geometry": LineString([(1.0, 1.0), (2.0, 1.0)]),
            },
        ],
    )

    with fiona.open(output_path) as source:
        assert len(source) == 2
        assert source.crs.to_epsg() == 3857
        assert source.schema["geometry"] == "LineString"
        features = list(source)

    first_props = dict(features[0]["properties"])
    assert first_props["pair_id"] == "S2:1__2"
    assert first_props["road_ids"] == '["r1","r2"]'
    assert int(first_props["trunk_found"]) == 1
    assert first_props["score"] == 1.5

    with sqlite3.connect(output_path) as conn:
        table_name = conn.execute("SELECT table_name FROM gpkg_contents LIMIT 1").fetchone()[0]
        count = conn.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]
        feature_count = conn.execute(
            "SELECT feature_count FROM gpkg_ogr_contents WHERE table_name = ?",
            (table_name,),
        ).fetchone()[0]
        trigger_names = {
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'trigger' AND tbl_name = ?
                """,
                (table_name,),
            )
        }
    assert count == 2
    assert feature_count == 2
    assert trigger_names == {
        "trigger_insert_feature_count_debug_lines",
        "trigger_delete_feature_count_debug_lines",
    }


def test_write_vector_fast_gpkg_handles_empty_layers(tmp_path: Path) -> None:
    output_path = tmp_path / "empty_debug.gpkg"

    write_vector(output_path, [])

    with fiona.open(output_path) as source:
        assert len(source) == 0
        assert source.crs.to_epsg() == 3857
    with sqlite3.connect(output_path) as conn:
        table_name = conn.execute("SELECT table_name FROM gpkg_contents LIMIT 1").fetchone()[0]
        feature_count = conn.execute(
            "SELECT feature_count FROM gpkg_ogr_contents WHERE table_name = ?",
            (table_name,),
        ).fetchone()[0]
    assert feature_count == 0


def test_small_gpkg_writer_reuses_schema_template(tmp_path: Path) -> None:
    _small_gpkg_template_bytes.cache_clear()
    features = [{"properties": {"id": "1"}, "geometry": LineString([(0.0, 0.0), (1.0, 1.0)])}]

    write_vector(tmp_path / "first.gpkg", features, layer_name="shared_layer")
    write_vector(tmp_path / "second.gpkg", features, layer_name="shared_layer")

    cache_info = _small_gpkg_template_bytes.cache_info()
    assert cache_info.misses == 1
    assert cache_info.hits >= 1
    for path in (tmp_path / "first.gpkg", tmp_path / "second.gpkg"):
        with fiona.open(path) as source:
            assert source.name == "shared_layer"
            assert len(source) == 1


def test_fast_gpkg_large_record_set_keeps_disk_backed_path(tmp_path: Path) -> None:
    output_path = tmp_path / "large_debug.gpkg"
    features = [
        {
            "properties": {"id": index},
            "geometry": LineString([(float(index), 0.0), (float(index), 1.0)]),
        }
        for index in range(GPKG_IN_MEMORY_PUBLISH_MAX_RECORDS + 1)
    ]

    write_vector(output_path, features)

    with fiona.open(output_path) as source:
        assert len(source) == len(features)
        assert source.crs.to_epsg() == 3857


def test_fast_gpkg_writer_merges_case_variant_fields_across_records(tmp_path: Path) -> None:
    output_path = tmp_path / "case_variant_fields.gpkg"
    features = [
        {"properties": {"ID": "r1", "formWay": 1}, "geometry": LineString([(0.0, 0.0), (1.0, 0.0)])},
        {"properties": {"id": "r2", "formway": 2}, "geometry": LineString([(1.0, 0.0), (2.0, 0.0)])},
    ]

    write_vector(output_path, features)

    with fiona.open(output_path) as source:
        assert tuple(source.schema["properties"]) == ("ID", "formWay")
        rows = [dict(feature["properties"]) for feature in source]
    assert rows == [{"ID": "r1", "formWay": 1}, {"ID": "r2", "formWay": 2}]
