from __future__ import annotations

from pathlib import Path

import fiona

from rcsd_topo_poc.modules.t00_utility_toolbox.mif_to_vector_export import (
    MifToVectorConfig,
    run_mif_to_vector_export,
)


def _write_point_mif(path: Path, *, name_prefix: str = "point") -> None:
    path.write_text(
        "\n".join(
            [
                "Version 300",
                'Charset "Neutral"',
                'Delimiter ","',
                "CoordSys Earth Projection 1, 104",
                "Columns 2",
                "  ID Integer",
                "  NAME Char(40)",
                "Data",
                "",
                "Point 116.300001 39.900001",
                "Point 116.300002 39.900002",
                "",
            ]
        ),
        encoding="utf-8",
    )
    path.with_suffix(".mid").write_text(
        f'1,"{name_prefix}-1"\n2,"{name_prefix}-2"\n',
        encoding="utf-8",
    )


def test_tool11_converts_single_mif_to_geojson_and_gpkg(tmp_path: Path) -> None:
    input_path = tmp_path / "pickup.mif"
    _write_point_mif(input_path)

    summary = run_mif_to_vector_export(
        MifToVectorConfig(
            input_path=input_path,
            run_id="test_tool11_single",
            progress_interval=1,
        )
    )

    geojson_path = input_path.with_suffix(".geojson")
    gpkg_path = input_path.with_suffix(".gpkg")
    assert summary["status"] == "completed"
    assert summary["input_mode"] == "file"
    assert summary["mif_file_count"] == 1
    assert summary["converted_file_count"] == 1
    assert summary["failed_file_count"] == 0
    assert summary["total_geojson_feature_count"] == 2
    assert summary["total_gpkg_feature_count"] == 2
    assert summary["file_results"][0]["features_per_second"] is not None
    assert summary["file_results"][0]["geojson_output"]["write_engine"] == "streaming-json"
    assert summary["file_results"][0]["gpkg_output"]["write_engine"] == "sqlite-gpkg"
    assert geojson_path.is_file()
    assert gpkg_path.is_file()

    with fiona.open(geojson_path) as src:
        assert len(src) == 2
        first = next(iter(src))
        assert first["properties"]["ID"] == 1
        assert first["properties"]["NAME"] == "point-1"
    with fiona.open(gpkg_path, layer="pickup") as src:
        assert len(src) == 2
        assert src.crs


def test_tool11_converts_top_level_mifs_in_directory(tmp_path: Path) -> None:
    input_dir = tmp_path / "MIF"
    input_dir.mkdir()
    _write_point_mif(input_dir / "a.mif", name_prefix="a")
    _write_point_mif(input_dir / "b.mif", name_prefix="b")

    nested = input_dir / "nested"
    nested.mkdir()
    _write_point_mif(nested / "ignored.mif", name_prefix="ignored")

    summary = run_mif_to_vector_export(
        MifToVectorConfig(
            input_path=input_dir,
            run_id="test_tool11_directory",
            progress_interval=1,
        )
    )

    assert summary["status"] == "completed"
    assert summary["input_mode"] == "directory"
    assert summary["scan_scope"] == "top-level"
    assert summary["mif_file_count"] == 2
    assert summary["converted_file_count"] == 2
    assert summary["failed_file_count"] == 0
    assert (input_dir / "a.geojson").is_file()
    assert (input_dir / "a.gpkg").is_file()
    assert (input_dir / "b.geojson").is_file()
    assert (input_dir / "b.gpkg").is_file()
    assert not (nested / "ignored.geojson").exists()
    assert not (nested / "ignored.gpkg").exists()
