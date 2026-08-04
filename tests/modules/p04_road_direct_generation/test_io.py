from __future__ import annotations

import geopandas as gpd
from shapely.geometry import LineString

from rcsd_topo_poc.modules.p04_road_direct_generation.io import (
    _gpkg_stage_root,
    write_gpkg_layers,
)


def _frame() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        [
            {
                "id": "road-a",
                "tags": ("hp_observed", "built"),
                "geometry": LineString([(0, 0), (10, 0)]),
            }
        ],
        crs="EPSG:32650",
    )


def test_gpkg_staging_writes_equivalent_content_and_cleans_stage_root(
    tmp_path,
    monkeypatch,
) -> None:
    stage_root = tmp_path / "stage"
    output_root = tmp_path / "output"
    output_root.mkdir()
    target = output_root / "result.gpkg"
    monkeypatch.setenv("P04_GPKG_STAGING", "force")
    monkeypatch.setenv("P04_GPKG_STAGE_ROOT", str(stage_root))

    write_gpkg_layers(target, {"Road": _frame()})

    actual = gpd.read_file(target, layer="Road")
    assert actual["id"].tolist() == ["road-a"]
    assert actual["tags"].tolist() == ['["hp_observed", "built"]']
    assert list(actual.geometry.to_wkb()) == list(_frame().geometry.to_wkb())
    assert list(stage_root.iterdir()) == []
    assert not list(output_root.glob(".*.partial"))


def test_gpkg_staging_can_be_disabled(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("P04_GPKG_STAGING", "off")
    monkeypatch.setenv("P04_GPKG_STAGE_ROOT", str(tmp_path / "stage"))

    assert _gpkg_stage_root(tmp_path / "result.gpkg", {"Road": _frame()}) is None
