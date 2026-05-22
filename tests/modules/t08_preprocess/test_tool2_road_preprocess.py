from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fiona
from pyproj import CRS
from shapely.geometry import LineString

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg


def _feature(properties: dict, coords: list[tuple[float, float]]) -> dict:
    return {"properties": properties, "geometry": LineString(coords)}


def _read_gpkg(path: Path) -> tuple[int | None, list[dict]]:
    with fiona.open(path) as source:
        crs_value = source.crs_wkt or source.crs
        epsg = CRS.from_user_input(crs_value).to_epsg() if crs_value else None
        features = [
            {"properties": dict(feature.get("properties") or {}), "geometry": feature.get("geometry")}
            for feature in source
        ]
    return epsg, features


def test_tool2_script_preprocesses_road_gpkg_inputs_to_3857(tmp_path: Path) -> None:
    road_gpkg = tmp_path / "input" / "road.gpkg"
    patch_road_gpkg = tmp_path / "input" / "patch_road.gpkg"
    raw_kind_gpkg = tmp_path / "input" / "raw_kind_road.gpkg"
    road_patch_output = tmp_path / "out" / "t08_road_patch.gpkg"
    unmatched_output = tmp_path / "out" / "t08_road_patch_unmatched.gpkg"
    kind_output = tmp_path / "out" / "t08_road_patch_kind.gpkg"
    summary_output = tmp_path / "out" / "t08_road_preprocess_summary.json"

    write_gpkg(
        road_gpkg,
        [
            _feature({"id": "1"}, [(116.3000, 39.9000), (116.3001, 39.9001)]),
            _feature({"id": "2"}, [(116.3100, 39.9000), (116.3101, 39.9001)]),
            _feature({"id": "3"}, [(116.3200, 39.9000), (116.3201, 39.9001)]),
        ],
        crs_text="EPSG:4326",
    )
    write_gpkg(
        patch_road_gpkg,
        [
            _feature({"road_id": "1", "patch_id": "1001"}, [(116.3000, 39.9000), (116.3001, 39.9001)]),
            _feature({"road_id": "2", "patch_id": "1002"}, [(116.3100, 39.9000), (116.3101, 39.9001)]),
            _feature({"road_id": "2", "patch_id": "1003"}, [(116.3100, 39.9000), (116.3101, 39.9001)]),
        ],
        crs_text="EPSG:4326",
    )
    write_gpkg(
        raw_kind_gpkg,
        [
            _feature({"Kind": "1201|1202"}, [(116.3000, 39.9000), (116.3001, 39.9001)]),
            _feature({"kind": "1301"}, [(116.3100, 39.9000), (116.3101, 39.9001)]),
        ],
        crs_text="EPSG:4326",
    )

    result = subprocess.run(
        [
            sys.executable,
            "scripts/t08_tool2_road_preprocess.py",
            "--road-gpkg",
            str(road_gpkg),
            "--patch-road-gpkg",
            str(patch_road_gpkg),
            "--raw-kind-road-gpkg",
            str(raw_kind_gpkg),
            "--road-patch-output",
            str(road_patch_output),
            "--road-patch-unmatched-output",
            str(unmatched_output),
            "--road-patch-kind-output",
            str(kind_output),
            "--summary-output",
            str(summary_output),
            "--progress-interval",
            "1",
        ],
        cwd=Path(__file__).resolve().parents[3],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "[T08 Tool2]" in result.stderr
    patch_epsg, patch_features = _read_gpkg(road_patch_output)
    unmatched_epsg, unmatched_features = _read_gpkg(unmatched_output)
    kind_epsg, kind_features = _read_gpkg(kind_output)

    assert patch_epsg == 3857
    assert unmatched_epsg == 3857
    assert kind_epsg == 3857
    assert len(patch_features) == 2
    assert len(unmatched_features) == 1
    assert len(kind_features) == 2

    patch_by_id = {feature["properties"]["id"]: feature for feature in patch_features}
    assert patch_by_id["1"]["properties"]["patch_id"] == "1001"
    assert patch_by_id["2"]["properties"]["patch_id"] == "1002,1003"
    assert unmatched_features[0]["properties"]["id"] == "3"
    assert unmatched_features[0]["properties"]["unmatched_reason"] == "no patch road match"

    kind_by_id = {feature["properties"]["id"]: feature for feature in kind_features}
    assert set(str(kind_by_id["1"]["properties"]["kind"]).split("|")) == {"1201", "1202"}
    assert kind_by_id["2"]["properties"]["kind"] == "1301"

    first_coordinate = patch_features[0]["geometry"]["coordinates"][0]
    assert abs(first_coordinate[0]) > 1_000_000
    assert abs(first_coordinate[1]) > 1_000_000

    summary = json.loads(summary_output.read_text(encoding="utf-8"))
    assert summary["counts"]["road_count"] == 3
    assert summary["counts"]["patch_join_matched_count"] == 2
    assert summary["counts"]["patch_join_unmatched_count"] == 1
    assert summary["counts"]["kind_matched_count"] == 2
    assert summary["performance"]["elapsed_seconds"] >= 0
    assert summary["performance"]["roads_per_second"] is not None
    assert summary["performance"]["spatial_candidate_count"] >= 2
    patch_summary = json.loads((tmp_path / "out" / "t08_road_patch_summary.json").read_text(encoding="utf-8"))
    kind_summary = json.loads((tmp_path / "out" / "t08_road_kind_summary.json").read_text(encoding="utf-8"))
    assert patch_summary["stage_timings"]["read_patch_attributes_seconds"] >= 0
    assert patch_summary["stage_timings"]["join_roads_seconds"] >= 0
    assert kind_summary["stage_timings"]["buffer_build_seconds"] >= 0
    assert kind_summary["stage_timings"]["spatial_query_seconds"] >= 0
    assert kind_summary["spatial_query_chunk_size"] == 5000
