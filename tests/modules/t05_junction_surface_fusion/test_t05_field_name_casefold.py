from __future__ import annotations

from pathlib import Path

import fiona
from shapely.geometry import Point

from rcsd_topo_poc.modules.t05_junction_surface_fusion.phase2_io import _write_gpkg_records


def test_phase2_writer_merges_case_variant_fields_across_records(tmp_path: Path) -> None:
    output_path = tmp_path / "case_variant_fields.gpkg"

    _write_gpkg_records(
        output_path,
        [
            {"properties": {"ID": "n1", "mainNodeId": "m1"}, "geometry": Point(0.0, 0.0)},
            {"properties": {"id": "n2", "mainnodeid": "m2"}, "geometry": Point(1.0, 1.0)},
        ],
        geometry_type="Point",
        batch_size=2,
    )

    with fiona.open(output_path) as source:
        assert tuple(source.schema["properties"]) == ("ID", "mainNodeId")
        rows = [dict(feature["properties"]) for feature in source]

    assert rows == [
        {"ID": "n1", "mainNodeId": "m1"},
        {"ID": "n2", "mainNodeId": "m2"},
    ]
