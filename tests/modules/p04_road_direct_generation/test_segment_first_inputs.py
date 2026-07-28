from __future__ import annotations

import geopandas as gpd
import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.io import (
    CORE_VECTOR_FILES,
    discover_patch_dirs,
)
from rcsd_topo_poc.modules.p04_road_direct_generation.segment_first_inputs import (
    _load_patch_layer,
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

    result = _load_patch_layer(
        patch_dirs,
        ("DivStripZone_fix.geojson", "DivStripZone.geojson"),
        "EPSG:32650",
    )

    assert result["source_patch_id"].tolist() == ["patch_fix", "patch_raw"]
    assert result["source_vector_filename"].tolist() == [
        "DivStripZone_fix.geojson",
        "DivStripZone.geojson",
    ]
    assert result["Id"].tolist() == ["fix", "raw"]
