from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation import io as io_module
from rcsd_topo_poc.modules.p04_road_direct_generation import (
    segment_first_inputs as inputs_module,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.io import (
    CORE_VECTOR_FILES,
    build_input_manifest,
    discover_patch_dirs,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_inputs import (
    SEGMENT_FIRST_PATCH_LAYER_FAMILIES,
    _consumed_patch_inputs,
    _load_patch_layer,
    _project_patch_frames,
    accepted_surface,
    require_columns,
)


def test_t07_review_surface_is_not_accepted() -> None:
    frame = gpd.GeoDataFrame(
        [
            {"id": "ok", "final_state": "accepted", "geometry": LineString([(0, 0), (1, 0)]).buffer(1)},
            {"id": "review", "final_state": "review_required", "geometry": LineString([(2, 0), (3, 0)]).buffer(1)},
        ],
        crs="EPSG:32650",
    )
    result = accepted_surface(frame, "t07")
    assert result["id"].tolist() == ["ok"]


def test_t03_requires_explicit_accepted_and_success() -> None:
    frame = gpd.GeoDataFrame(
        [
            {"id": "ok", "success": True, "acceptance_class": "accepted", "geometry": LineString([(0, 0), (1, 0)]).buffer(1)},
            {"id": "failed", "success": False, "acceptance_class": "accepted", "geometry": LineString([(2, 0), (3, 0)]).buffer(1)},
        ],
        crs="EPSG:32650",
    )
    assert accepted_surface(frame, "t03")["id"].tolist() == ["ok"]


def test_t03_formal_step7_state_is_preferred() -> None:
    frame = gpd.GeoDataFrame(
        [
            {
                "id": "ok",
                "step7_state": "accepted",
                "success": False,
                "acceptance_class": "rejected",
                "geometry": LineString([(0, 0), (1, 0)]).buffer(1),
            },
            {
                "id": "rejected",
                "step7_state": "rejected",
                "success": True,
                "acceptance_class": "accepted",
                "geometry": LineString([(2, 0), (3, 0)]).buffer(1),
            },
        ],
        crs="EPSG:32650",
    )

    assert accepted_surface(frame, "t03")["id"].tolist() == ["ok"]


def test_required_t01_contract_is_explicit() -> None:
    frame = gpd.GeoDataFrame(
        [{"id": "s1", "geometry": LineString([(0, 0), (1, 0)])}],
        crs="EPSG:32650",
    )
    with pytest.raises(ValueError, match="pair_nodes"):
        require_columns(
            frame,
            ("id", "sgrade", "pair_nodes", "junc_nodes", "roads"),
            "t01_segments",
        )


def test_segment_first_discovery_accepts_raw_divstrip_when_fix_is_missing(
    tmp_path,
) -> None:
    vector_dir = tmp_path / "5417631180197200" / "Vector"
    vector_dir.mkdir(parents=True)
    for filename in CORE_VECTOR_FILES:
        (vector_dir / filename).touch()
    (vector_dir / "DivStripZone_fix.geojson").unlink()

    patch_dirs = discover_patch_dirs(
        tmp_path,
        allow_equivalent_vector_fallback=True,
    )

    assert [path.name for path in patch_dirs] == ["5417631180197200"]
    with pytest.raises(FileNotFoundError, match="DivStripZone_fix.geojson"):
        discover_patch_dirs(tmp_path)


def test_patch_layer_prefers_fix_and_records_raw_fallback(tmp_path) -> None:
    patch_dirs = (
        tmp_path / "patch_fix",
        tmp_path / "patch_raw",
    )
    for patch_dir in patch_dirs:
        (patch_dir / "Vector").mkdir(parents=True)

    fix_frame = gpd.GeoDataFrame(
        [{"Id": "fix", "geometry": LineString([(0, 0), (1, 0)]).buffer(1)}],
        crs="EPSG:32650",
    )
    raw_frame = gpd.GeoDataFrame(
        [{"Id": "raw", "geometry": LineString([(2, 0), (3, 0)]).buffer(1)}],
        crs="EPSG:32650",
    )
    fix_frame.to_file(
        patch_dirs[0] / "Vector" / "DivStripZone_fix.geojson",
        driver="GeoJSON",
    )
    raw_frame.to_file(
        patch_dirs[0] / "Vector" / "DivStripZone.geojson",
        driver="GeoJSON",
    )
    raw_frame.to_file(
        patch_dirs[1] / "Vector" / "DivStripZone.geojson",
        driver="GeoJSON",
    )

    manifest_by_path: dict = {}
    result = _load_patch_layer(
        patch_dirs,
        ("DivStripZone_fix.geojson", "DivStripZone.geojson"),
        "EPSG:32650",
        manifest_by_path=manifest_by_path,
    )

    assert result["source_patch_id"].tolist() == ["patch_fix", "patch_raw"]
    assert result["source_vector_filename"].tolist() == [
        "DivStripZone_fix.geojson",
        "DivStripZone.geojson",
    ]
    assert result["Id"].tolist() == ["fix", "raw"]
    expected_paths = {
        patch_dirs[0] / "Vector" / "DivStripZone_fix.geojson",
        patch_dirs[1] / "Vector" / "DivStripZone.geojson",
    }
    assert set(manifest_by_path) == expected_paths
    for path in expected_paths:
        row = manifest_by_path[path]
        assert row["patch_id"] == path.parents[1].name
        assert row["size_bytes"] == path.stat().st_size
        assert row["sha256"] == io_module.sha256_file(path)


def test_patch_layer_stages_drvfs_input_and_preserves_manifest(
    tmp_path,
    monkeypatch,
) -> None:
    patch_dir = tmp_path / "patch_a"
    vector_dir = patch_dir / "Vector"
    vector_dir.mkdir(parents=True)
    source_path = vector_dir / "Road.geojson"
    source = gpd.GeoDataFrame(
        [{"Id": "road-a", "geometry": LineString([(0, 0), (1, 0)])}],
        crs="EPSG:32650",
    )
    source.to_file(source_path, driver="GeoJSON")
    stage_root = tmp_path / "stage"
    read_paths: list = []
    original_read_file = inputs_module.gpd.read_file

    def recording_read_file(path, *args, **kwargs):
        read_paths.append(path)
        return original_read_file(path, *args, **kwargs)

    monkeypatch.setenv("P04_PATCH_INPUT_STAGING", "force")
    monkeypatch.setenv("P04_PATCH_STAGE_ROOT", str(stage_root))
    monkeypatch.setattr(inputs_module.gpd, "read_file", recording_read_file)
    manifest_by_path: dict = {}

    actual = _load_patch_layer(
        (patch_dir,),
        "Road.geojson",
        "EPSG:32650",
        manifest_by_path=manifest_by_path,
    )

    assert actual["Id"].tolist() == ["road-a"]
    assert list(actual.geometry.to_wkb()) == list(source.geometry.to_wkb())
    assert read_paths and all(Path(path) != source_path for path in read_paths)
    assert manifest_by_path[source_path]["size_bytes"] == source_path.stat().st_size
    assert manifest_by_path[source_path]["sha256"] == io_module.sha256_file(
        source_path
    )
    assert list(stage_root.iterdir()) == []


def test_segment_first_manifest_hashes_only_consumed_patch_layers(
    tmp_path,
) -> None:
    patch_dir = tmp_path / "patches" / "patch_a"
    vector_dir = patch_dir / "Vector"
    vector_dir.mkdir(parents=True)
    for filenames in SEGMENT_FIRST_PATCH_LAYER_FAMILIES:
        (vector_dir / filenames[0]).write_text(
            filenames[0],
            encoding="utf-8",
        )
    unrelated = vector_dir / "Crosswalk.geojson"
    unrelated.write_text("not consumed by P04", encoding="utf-8")
    external = tmp_path / "swsd.gpkg"
    external.write_text("external", encoding="utf-8")

    manifest = build_input_manifest(
        run_id="case",
        patch_dirs=(patch_dir,),
        external_inputs={"swsd_roads": external},
        parameters={},
        patch_inputs=_consumed_patch_inputs((patch_dir,)),
    )

    assert manifest["input_file_count"] == (
        len(SEGMENT_FIRST_PATCH_LAYER_FAMILIES) + 1
    )
    assert unrelated.as_posix() not in {
        str(row["path"]).replace("\\", "/")
        for row in manifest["files"]
    }


def test_input_manifest_reuses_precomputed_patch_hashes_without_rehash(
    tmp_path,
    monkeypatch,
) -> None:
    patch_dir = tmp_path / "patches" / "patch_a"
    vector_dir = patch_dir / "Vector"
    vector_dir.mkdir(parents=True)
    for filenames in SEGMENT_FIRST_PATCH_LAYER_FAMILIES:
        (vector_dir / filenames[0]).write_text(
            filenames[0],
            encoding="utf-8",
        )
    external = tmp_path / "swsd.gpkg"
    external.write_text("external", encoding="utf-8")
    patch_inputs = _consumed_patch_inputs((patch_dir,))
    baseline = build_input_manifest(
        run_id="case",
        patch_dirs=(patch_dir,),
        external_inputs={"swsd_roads": external},
        parameters={"mode": "baseline"},
        patch_inputs=patch_inputs,
    )
    precomputed = [
        row for row in baseline["files"] if row["patch_id"] is not None
    ]
    hashed_paths: list = []
    original = io_module._manifest_row_request

    def tracked_manifest_row(request):
        hashed_paths.append(request[0])
        return original(request)

    monkeypatch.setattr(
        io_module,
        "_manifest_row_request",
        tracked_manifest_row,
    )
    fused = build_input_manifest(
        run_id="case",
        patch_dirs=(patch_dir,),
        external_inputs={"swsd_roads": external},
        parameters={"mode": "baseline"},
        patch_inputs=patch_inputs,
        precomputed_patch_files=precomputed,
    )

    assert hashed_paths == [external]
    assert fused["files"] == baseline["files"]
    assert fused["input_file_count"] == baseline["input_file_count"]
    assert fused["input_total_bytes"] == baseline["input_total_bytes"]


def test_patch_frames_with_shared_crs_use_one_exact_projection_batch() -> None:
    frames = [
        gpd.GeoDataFrame(
            [{"id": "a", "geometry": LineString([(114.0, 30.0), (114.001, 30.0)])}],
            crs="EPSG:4326",
        ),
        gpd.GeoDataFrame(
            [{"id": "b", "geometry": LineString([(114.0, 30.001), (114.001, 30.001)])}],
            crs="EPSG:4326",
        ),
    ]
    expected_frames = []
    for frame in frames:
        projected = frame.to_crs("EPSG:32650")
        projected.geometry = projected.geometry.map(io_module.to_2d)
        expected_frames.append(projected)
    expected = gpd.GeoDataFrame(
        pd.concat(expected_frames, ignore_index=True),
        geometry="geometry",
        crs="EPSG:32650",
    )

    actual, batch_count, shared = _project_patch_frames(
        frames,
        "EPSG:32650",
    )

    assert shared is True
    assert batch_count == 1
    assert actual.drop(columns="geometry").equals(
        expected.drop(columns="geometry")
    )
    assert list(actual.geometry.to_wkb()) == list(expected.geometry.to_wkb())


def test_patch_frames_with_mixed_crs_preserve_per_frame_projection() -> None:
    frames = [
        gpd.GeoDataFrame(
            [{"id": "a", "geometry": LineString([(114.0, 30.0), (114.001, 30.0)])}],
            crs="EPSG:4326",
        ),
        gpd.GeoDataFrame(
            [{"id": "b", "geometry": LineString([(12690421.95, 3503549.84), (12690521.95, 3503549.84)])}],
            crs="EPSG:3857",
        ),
    ]
    expected_frames = []
    for frame in frames:
        projected = frame.to_crs("EPSG:32650")
        projected.geometry = projected.geometry.map(io_module.to_2d)
        expected_frames.append(projected)
    expected = gpd.GeoDataFrame(
        pd.concat(expected_frames, ignore_index=True),
        geometry="geometry",
        crs="EPSG:32650",
    )

    actual, batch_count, shared = _project_patch_frames(
        frames,
        "EPSG:32650",
    )

    assert shared is False
    assert batch_count == 2
    assert actual.drop(columns="geometry").equals(
        expected.drop(columns="geometry")
    )
    assert list(actual.geometry.to_wkb()) == list(expected.geometry.to_wkb())
