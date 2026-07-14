from __future__ import annotations

from types import SimpleNamespace

import fiona
import pytest
from shapely.geometry import LineString, MultiLineString, Point, mapping

from rcsd_topo_poc.modules.t06_segment_fusion_precheck import io as io_module
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.io import read_features, write_feature_triplet


def test_read_features_normalizes_mixed_case_property_keys(tmp_path, monkeypatch):
    path = tmp_path / "mixed_case.gpkg"
    path.write_bytes(b"mixed-case")
    io_module.clear_read_features_cache()

    monkeypatch.setattr(
        io_module,
        "read_vector_layer",
        lambda *args, **kwargs: SimpleNamespace(
            features=[
                SimpleNamespace(
                    properties={
                        "Id": "5855295910117642",
                        "MainNodeId": "5855295910117642",
                        "SubNodeId": "[5855295910117626]",
                    },
                    geometry=Point(1.0, 2.0),
                )
            ]
        ),
    )

    properties = read_features(path)[0]["properties"]

    assert properties == {
        "id": "5855295910117642",
        "mainnodeid": "5855295910117642",
        "subnodeid": "[5855295910117626]",
    }


def test_read_features_blocks_conflicting_case_variants(tmp_path, monkeypatch):
    path = tmp_path / "conflicting_case.gpkg"
    path.write_bytes(b"conflict")
    io_module.clear_read_features_cache()
    monkeypatch.setattr(
        io_module,
        "read_vector_layer",
        lambda *args, **kwargs: SimpleNamespace(
            features=[
                SimpleNamespace(
                    properties={"ID": "1", "id": "2"},
                    geometry=Point(1.0, 2.0),
                )
            ]
        ),
    )

    with pytest.raises(ValueError, match="case-insensitive property conflict"):
        read_features(path)


def test_read_features_reuses_unchanged_snapshot_without_sharing_properties(tmp_path, monkeypatch):
    path = tmp_path / "input.gpkg"
    path.write_bytes(b"first")
    io_module.clear_read_features_cache()
    calls = 0

    def fake_read_vector_layer(path_text, *, crs_override=None):
        nonlocal calls
        calls += 1
        return SimpleNamespace(
            features=[
                SimpleNamespace(
                    properties={"id": "r1", "nested": ["original"]},
                    geometry=Point(1.0, 2.0),
                )
            ]
        )

    monkeypatch.setattr(io_module, "read_vector_layer", fake_read_vector_layer)
    first = read_features(path)
    first[0]["properties"]["nested"].append("mutated")
    second = read_features(path)

    assert calls == 1
    assert second[0]["properties"] == {"id": "r1", "nested": ["original"]}

    path.write_bytes(b"second-version")
    read_features(path)
    assert calls == 2
    assert io_module._read_features_cache_size() == 1

    io_module.clear_read_features_cache()
    assert io_module._read_features_cache_size() == 0


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
