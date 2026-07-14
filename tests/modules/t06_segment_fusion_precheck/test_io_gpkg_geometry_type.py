from __future__ import annotations

from types import SimpleNamespace

import fiona
import pytest
from shapely.geometry import LineString, MultiLineString, Point, mapping

from rcsd_topo_poc.modules.t06_segment_fusion_precheck import io as io_module
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.io import read_features, write_feature_triplet
from rcsd_topo_poc.modules.t06_segment_fusion_precheck.step3_validation_publish import (
    decision_only_validation_step3_run,
)


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
    with io_module.preserve_read_features_cache():
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


def test_read_features_does_not_cache_outside_preserve_scope(tmp_path, monkeypatch):
    path = tmp_path / "input.gpkg"
    path.write_bytes(b"data")
    calls = 0

    def fake_read_vector_layer(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return SimpleNamespace(features=[])

    monkeypatch.setattr(io_module, "read_vector_layer", fake_read_vector_layer)

    read_features(path)
    read_features(path)

    assert calls == 2
    assert io_module._read_features_cache_size() == 0


def test_preserve_read_features_cache_defers_clear_until_scope_exit(tmp_path, monkeypatch):
    path = tmp_path / "input.gpkg"
    path.write_bytes(b"data")
    monkeypatch.setattr(
        io_module,
        "read_vector_layer",
        lambda *_args, **_kwargs: SimpleNamespace(features=[]),
    )

    with io_module.preserve_read_features_cache():
        read_features(path)
        io_module.clear_read_features_cache()
        assert io_module._read_features_cache_size() == 1
    assert io_module._read_features_cache_size() == 0


def test_preserve_read_features_cache_releases_unpinned_paths(tmp_path, monkeypatch):
    pinned_path = tmp_path / "pinned.gpkg"
    released_path = tmp_path / "released.gpkg"
    pinned_path.write_bytes(b"pinned")
    released_path.write_bytes(b"released")
    monkeypatch.setattr(
        io_module,
        "read_vector_layer",
        lambda *_args, **_kwargs: SimpleNamespace(features=[]),
    )

    with io_module.preserve_read_features_cache([pinned_path]):
        read_features(pinned_path)
        read_features(released_path)
        io_module.clear_read_features_cache()
        assert list(io_module._READ_FEATURES_SNAPSHOT_CACHE) == [(str(pinned_path.resolve()), None)]
    assert io_module._read_features_cache_size() == 0


def test_discard_read_features_cache_removes_only_target_path(tmp_path, monkeypatch):
    first_path = tmp_path / "first.gpkg"
    second_path = tmp_path / "second.gpkg"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    monkeypatch.setattr(
        io_module,
        "read_vector_layer",
        lambda *_args, **_kwargs: SimpleNamespace(features=[]),
    )
    with io_module.preserve_read_features_cache():
        read_features(first_path)
        read_features(second_path)

        io_module.discard_read_features_cache(first_path)

        assert list(io_module._READ_FEATURES_SNAPSHOT_CACHE) == [(str(second_path.resolve()), None)]
    io_module.clear_read_features_cache(force=True)


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


def test_decision_only_feature_triplet_skips_csv_but_keeps_gpkg(tmp_path):
    step_root = tmp_path / "step3_segment_replacement"

    with decision_only_validation_step3_run():
        paths = write_feature_triplet(
            step_root=step_root,
            stem="decision_only",
            features=[],
            fieldnames=["id"],
            write_json_output=False,
        )

    assert paths["gpkg"].is_file()
    assert not paths["csv"].exists()


def test_stage_feature_outputs_publishes_to_requested_paths(tmp_path, monkeypatch):
    step_root = tmp_path / "step2_extract_rcsd_segments"
    write_paths = []

    def fake_write_gpkg(path, *_args, **_kwargs):
        write_path = io_module.Path(path)
        write_paths.append(write_path)
        write_path.parent.mkdir(parents=True, exist_ok=True)
        write_path.write_bytes(b"staged-gpkg")

    monkeypatch.setattr(io_module, "write_gpkg", fake_write_gpkg)

    with io_module.stage_feature_outputs():
        paths = write_feature_triplet(
            step_root=step_root,
            stem="staged",
            features=[],
            fieldnames=["id"],
            write_json_output=False,
        )
        assert write_paths[0] != paths["gpkg"]
        assert paths["gpkg"].read_bytes() == b"staged-gpkg"
        assert paths["csv"].is_file()

    assert not write_paths[0].exists()


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
