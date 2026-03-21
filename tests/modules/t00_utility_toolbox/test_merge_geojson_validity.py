from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.modules.t00_utility_toolbox.drivezone_merge import (
    DriveZoneMergeConfig,
    run_drivezone_merge,
)
from rcsd_topo_poc.modules.t00_utility_toolbox.intersection_merge import (
    IntersectionMergeConfig,
    run_intersection_merge,
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


def test_drivezone_merge_skips_missing_crs_patch_with_out_of_range_lonlat_bounds(tmp_path: Path) -> None:
    patch_all_root = tmp_path / "patch_all"

    _write_polygon_feature_collection(
        patch_all_root / "1001" / "Vector" / "DriveZone.geojson",
        [
            [500000.0, 4000000.0],
            [500100.0, 4000000.0],
            [500100.0, 4000100.0],
            [500000.0, 4000100.0],
            [500000.0, 4000000.0],
        ],
    )
    _write_polygon_feature_collection(
        patch_all_root / "1002" / "Vector" / "DriveZone.geojson",
        [
            [116.30, 39.90],
            [116.31, 39.90],
            [116.31, 39.91],
            [116.30, 39.91],
            [116.30, 39.90],
        ],
    )

    summary = run_drivezone_merge(
        DriveZoneMergeConfig(
            patch_all_root=patch_all_root,
            run_id="test_drivezone_geojson_validity",
        )
    )

    fixed_output_path = patch_all_root / "1002" / "Vector" / "DriveZone_fix.geojson"
    output_path = patch_all_root / "DriveZone.geojson"
    output_text = output_path.read_text(encoding="utf-8")
    output_doc = json.loads(output_text)
    fixed_output_doc = json.loads(fixed_output_path.read_text(encoding="utf-8"))

    assert summary["processed_patch_count"] == 1
    assert summary["fixed_output_count"] == 1
    assert summary["global_merge_input_count"] == 1
    assert summary["skip_error_count"] == 1
    assert summary["output_feature_count"] == 1
    assert "Infinity" not in output_text
    assert "NaN" not in output_text
    assert output_doc["type"] == "FeatureCollection"
    assert output_doc["crs"]["properties"]["name"] == "EPSG:3857"
    assert fixed_output_doc["type"] == "FeatureCollection"
    assert fixed_output_doc["crs"]["properties"]["name"] == "EPSG:3857"
    assert summary["patch_results"][0]["status"] == "skip_error"
    assert "missing or incorrect CRS metadata" in summary["patch_results"][0]["error_reason"]


def test_drivezone_merge_writes_fix_outputs_before_global_merge(tmp_path: Path) -> None:
    patch_all_root = tmp_path / "patch_all"

    _write_polygon_feature_collection(
        patch_all_root / "3001" / "Vector" / "DriveZone.geojson",
        [
            [116.30, 39.90],
            [116.302, 39.90],
            [116.302, 39.902],
            [116.30, 39.902],
            [116.30, 39.90],
        ],
    )
    _write_polygon_feature_collection(
        patch_all_root / "3002" / "Vector" / "DriveZone.geojson",
        [
            [116.305, 39.905],
            [116.307, 39.905],
            [116.307, 39.907],
            [116.305, 39.907],
            [116.305, 39.905],
        ],
    )

    summary = run_drivezone_merge(
        DriveZoneMergeConfig(
            patch_all_root=patch_all_root,
            run_id="test_drivezone_fix_outputs",
        )
    )

    fix_3001 = patch_all_root / "3001" / "Vector" / "DriveZone_fix.geojson"
    fix_3002 = patch_all_root / "3002" / "Vector" / "DriveZone_fix.geojson"
    global_output = patch_all_root / "DriveZone.geojson"

    assert fix_3001.is_file()
    assert fix_3002.is_file()
    assert global_output.is_file()
    assert summary["processed_patch_count"] == 2
    assert summary["fixed_output_count"] == 2
    assert summary["global_merge_input_count"] == 2
    assert summary["output_feature_count"] == 1
    assert summary["output_bounds_3857"] is not None


def test_intersection_merge_skips_missing_crs_patch_with_out_of_range_lonlat_bounds(tmp_path: Path) -> None:
    patch_all_root = tmp_path / "patch_all"

    _write_polygon_feature_collection(
        patch_all_root / "2001" / "Vector" / "Intersection.geojson",
        [
            [500000.0, 4000000.0],
            [500050.0, 4000000.0],
            [500050.0, 4000050.0],
            [500000.0, 4000050.0],
            [500000.0, 4000000.0],
        ],
        properties={"kind": "bad-crs"},
    )
    _write_polygon_feature_collection(
        patch_all_root / "2002" / "Vector" / "Intersection.geojson",
        [
            [116.40, 39.90],
            [116.401, 39.90],
            [116.401, 39.901],
            [116.40, 39.901],
            [116.40, 39.90],
        ],
        properties={"kind": "good"},
    )

    summary = run_intersection_merge(
        IntersectionMergeConfig(
            patch_all_root=patch_all_root,
            run_id="test_intersection_geojson_validity",
        )
    )

    output_path = patch_all_root / "Intersection.geojson"
    output_text = output_path.read_text(encoding="utf-8")
    output_doc = json.loads(output_text)

    assert summary["processed_patch_count"] == 1
    assert summary["skip_error_count"] == 1
    assert summary["output_feature_count"] == 1
    assert "Infinity" not in output_text
    assert "NaN" not in output_text
    assert output_doc["type"] == "FeatureCollection"
    assert output_doc["features"][0]["properties"]["patchid"] == "2002"
    assert output_doc["features"][0]["properties"]["kind"] == "good"
    assert summary["patch_results"][0]["status"] == "skip_error"
    assert "missing or incorrect CRS metadata" in summary["patch_results"][0]["error_reason"]
