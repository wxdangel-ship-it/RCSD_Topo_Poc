from __future__ import annotations

import sqlite3
from pathlib import Path

from shapely.geometry import GeometryCollection, MultiLineString, Point, Polygon, box

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon.case_output_io import (
    write_case_event_vector,
    write_case_polygon_vector,
)


def test_write_case_polygon_vector_preserves_unknown_declared_geometry_type(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "final_case_polygon.gpkg"
    expected = box(0.0, 0.0, 1.0, 1.0)

    write_case_polygon_vector(
        output_path,
        [{"properties": {"case_id": "100001"}, "geometry": expected}],
    )

    with sqlite3.connect(output_path) as connection:
        declared_type, z_mode = connection.execute(
            "SELECT geometry_type_name, z FROM gpkg_geometry_columns"
        ).fetchone()
    features = read_vector_layer(output_path).features
    assert declared_type == "GEOMETRY"
    assert z_mode == 0
    assert len(features) == 1
    assert features[0].properties["case_id"] == "100001"
    assert features[0].geometry.equals(expected)


def test_write_case_event_vector_preserves_z_geometry(tmp_path: Path) -> None:
    output_path = tmp_path / "step4_event_evidence.gpkg"
    expected = GeometryCollection([box(0.0, 0.0, 1.0, 1.0), Point(0.5, 0.5, 3.0)])

    write_case_event_vector(
        output_path,
        [{"properties": {"unit_id": "unit-1"}, "geometry": expected}],
    )

    with sqlite3.connect(output_path) as connection:
        declared_type, z_mode = connection.execute(
            "SELECT geometry_type_name, z FROM gpkg_geometry_columns"
        ).fetchone()
    feature = read_vector_layer(output_path).features[0]
    assert declared_type == "GEOMETRY"
    assert z_mode == 2
    assert feature.properties["unit_id"] == "unit-1"
    assert feature.geometry.equals_exact(expected, tolerance=0.0)


def test_write_case_event_vector_uses_fast_2d_writer(tmp_path: Path) -> None:
    output_path = tmp_path / "step4_event_evidence.gpkg"
    expected = box(0.0, 0.0, 1.0, 1.0)

    write_case_event_vector(
        output_path,
        [{"properties": {"unit_id": "unit-2"}, "geometry": expected}],
    )

    with sqlite3.connect(output_path) as connection:
        declared_type = connection.execute(
            "SELECT geometry_type_name FROM gpkg_geometry_columns"
        ).fetchone()[0]
    feature = read_vector_layer(output_path).features[0]
    assert declared_type == "GEOMETRY"
    assert feature.properties["unit_id"] == "unit-2"
    assert feature.geometry.equals_exact(expected, tolerance=0.0)


def test_write_case_polygon_vector_marks_mixed_z_as_optional_for_pyogrio(tmp_path: Path) -> None:
    geopandas = __import__("geopandas")
    output_path = tmp_path / "step5_domains.gpkg"
    features = [
        {
            "properties": {"id": "z"},
            "geometry": Polygon([(0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (0.0, 1.0, 1.0)]),
        },
        {
            "properties": {"id": "flat"},
            "geometry": MultiLineString([[(0.0, 0.0), (1.0, 1.0)]]),
        },
    ]

    write_case_polygon_vector(output_path, features)

    with sqlite3.connect(output_path) as connection:
        z_mode = connection.execute("SELECT z FROM gpkg_geometry_columns").fetchone()[0]
    frame = geopandas.read_file(output_path)
    assert z_mode == 2
    assert len(frame) == 2
