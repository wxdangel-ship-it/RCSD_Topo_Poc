from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.t00_utility_toolbox.divstripzone_merge import (
    DivStripZoneMergeConfig,
    run_divstripzone_merge,
)


def _write_polygon_feature_collection(
    path: Path,
    coordinates: list[list[float]],
    *,
    properties: dict[str, object] | None = None,
    crs_name: str | None = None,
) -> None:
    payload: dict[str, object] = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": properties or {},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [coordinates],
                },
            }
        ],
    }
    if crs_name is not None:
        payload["crs"] = {"type": "name", "properties": {"name": crs_name}}

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_divstripzone_merge_writes_patchid_for_vector_dir(tmp_path: Path) -> None:
    patch_all_root = tmp_path / "patch_all"

    _write_polygon_feature_collection(
        patch_all_root / "1001" / "vector" / "DivStripZone.geojson",
        [
            [116.30, 39.90],
            [116.31, 39.90],
            [116.31, 39.91],
            [116.30, 39.91],
            [116.30, 39.90],
        ],
    )

    summary = run_divstripzone_merge(
        DivStripZoneMergeConfig(
            patch_all_root=patch_all_root,
            run_id="test_divstripzone_vector_dir",
        )
    )

    fixed_output_path = patch_all_root / "1001" / "vector" / "DivStripZone_fix.geojson"
    output_path = patch_all_root / "DivStripZone.geojson"

    fixed_doc = json.loads(fixed_output_path.read_text(encoding="utf-8"))
    output_doc = json.loads(output_path.read_text(encoding="utf-8"))

    assert summary["processed_patch_count"] == 1
    assert summary["fixed_output_count"] == 1
    assert summary["global_merge_input_count"] == 1
    assert summary["output_feature_count"] == 1
    assert fixed_doc["crs"]["properties"]["name"] == "EPSG:3857"
    assert output_doc["crs"]["properties"]["name"] == "EPSG:3857"
    assert fixed_doc["features"][0]["properties"]["patchid"] == "1001"
    assert output_doc["features"][0]["properties"]["patchid"] == "1001"


def test_divstripzone_merge_skips_bad_crs(tmp_path: Path) -> None:
    patch_all_root = tmp_path / "patch_all"

    _write_polygon_feature_collection(
        patch_all_root / "2001" / "Vector" / "DivStripZone.geojson",
        [
            [500000.0, 4000000.0],
            [500100.0, 4000000.0],
            [500100.0, 4000100.0],
            [500000.0, 4000100.0],
            [500000.0, 4000000.0],
        ],
    )
    _write_polygon_feature_collection(
        patch_all_root / "2002" / "Vector" / "DivStripZone.geojson",
        [
            [116.40, 39.90],
            [116.41, 39.90],
            [116.41, 39.91],
            [116.40, 39.91],
            [116.40, 39.90],
        ],
    )

    summary = run_divstripzone_merge(
        DivStripZoneMergeConfig(
            patch_all_root=patch_all_root,
            run_id="test_divstripzone_bad_crs",
        )
    )

    assert summary["processed_patch_count"] == 1
    assert summary["skip_error_count"] == 1
    assert summary["output_feature_count"] == 1
    assert summary["patch_results"][0]["status"] == "skip_error"
    assert "missing or incorrect CRS metadata" in summary["patch_results"][0]["error_reason"]
