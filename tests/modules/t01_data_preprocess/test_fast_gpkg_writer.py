from __future__ import annotations

import sqlite3
from pathlib import Path

import fiona
from shapely.geometry import LineString

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
    assert count == 2


def test_write_vector_fast_gpkg_handles_empty_layers(tmp_path: Path) -> None:
    output_path = tmp_path / "empty_debug.gpkg"

    write_vector(output_path, [])

    with fiona.open(output_path) as source:
        assert len(source) == 0
        assert source.crs.to_epsg() == 3857
