from __future__ import annotations

import fiona
from shapely.geometry import LineString, MultiLineString, mapping

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.io import write_feature_triplet


def test_write_feature_triplet_uses_specific_linestring_geometry_type(tmp_path):
    step_root = tmp_path / "step3_segment_replacement"
    paths = write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_unreplaced_rcsd_roads",
        features=[
            {
                "properties": {
                    "id": "r1",
                    "replacement_status": "not_replaced",
                    "audit_reason": "not_referenced_by_step2_replaceable_rcsd_segment",
                    "source": 1,
                    "length_m": 1.0,
                },
                "geometry": LineString([(0.0, 0.0), (1.0, 0.0)]),
            }
        ],
        fieldnames=["id", "replacement_status", "audit_reason", "source", "length_m"],
        write_json_output=False,
    )

    with fiona.open(paths["gpkg"], layer="t06_step3_unreplaced_rcsd_roads") as layer:
        assert layer.schema["geometry"] == "LineString"
        assert len(layer) == 1


def test_write_feature_triplet_promotes_mixed_line_geometries(tmp_path):
    step_root = tmp_path / "step3_segment_replacement"
    paths = write_feature_triplet(
        step_root=step_root,
        stem="t06_step3_replacement_units",
        features=[
            {
                "properties": {"id": "a"},
                "geometry": MultiLineString([[(0.0, 0.0), (1.0, 0.0)]]),
            },
            {
                "properties": {"id": "b"},
                "geometry": mapping(LineString([(1.0, 0.0), (2.0, 0.0)])),
            },
        ],
        fieldnames=["id"],
        write_json_output=False,
    )

    with fiona.open(paths["gpkg"], layer="t06_step3_replacement_units") as layer:
        assert layer.schema["geometry"] == "MultiLineString"
        assert len(layer) == 2
