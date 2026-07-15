from __future__ import annotations

import json
import math
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import fiona
import pytest
from pyproj import CRS

from rcsd_topo_poc.modules.t08_preprocess import run_t08_trajectory_aggregation


def _write_trajectory(
    patch_dir: Path,
    traj_id: str,
    rows: list[dict[str, Any]],
    *,
    crs: str | None = "EPSG:3857",
) -> Path:
    path = patch_dir / "Traj" / traj_id / "raw_dat_pose.geojson"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": dict(row.get("properties") or {}),
                "geometry": row["geometry"],
            }
            for row in rows
        ],
    }
    if crs is not None:
        payload["crs"] = {"type": "name", "properties": {"name": crs}}
    path.write_text(json.dumps(payload, ensure_ascii=False, allow_nan=True), encoding="utf-8")
    return path


def _point_row(
    coords: list[float],
    frame_id: int,
    *,
    timestamp: Any = None,
    drive_id: str = "drive-a",
) -> dict[str, Any]:
    properties: dict[str, Any] = {"frame_id": frame_id, "drive_id": drive_id}
    if timestamp is not None:
        properties["timestamp"] = timestamp
    return {
        "properties": properties,
        "geometry": {"type": "Point", "coordinates": coords},
    }


def _read_layer_rows(path: Path) -> list[dict[str, Any]]:
    with fiona.open(path, layer="raw_dat_pose") as source:
        return [
            {
                "properties": dict(feature["properties"]),
                "coordinates": [tuple(coord) for coord in feature["geometry"]["coordinates"]],
            }
            for feature in source
        ]


def test_tool10_aggregates_all_trajectories_into_one_linestringz_gpkg(tmp_path: Path) -> None:
    patch_dir = tmp_path / "00000001"
    _write_trajectory(
        patch_dir,
        "traj-a",
        [
            _point_row([2.0, 0.0, 102.0], 2, timestamp=0.2),
            _point_row([1.0, 0.0, 101.0], 1, timestamp=0.1),
            _point_row([3.0, 0.0, 103.0], 3, timestamp=0.3),
        ],
    )
    _write_trajectory(
        patch_dir,
        "traj-b",
        [
            _point_row([0.0, 10.0, 201.0], 1, timestamp=0.1, drive_id="drive-b"),
            _point_row([1.0, 10.0, 202.0], 2, timestamp=0.2, drive_id="drive-b"),
            _point_row([30.0, 10.0, 203.0], 3, timestamp=0.3, drive_id="drive-b"),
            _point_row([31.0, 10.0, 204.0], 4, timestamp=0.4, drive_id="drive-b"),
        ],
    )

    artifacts = run_t08_trajectory_aggregation(patch_dir=patch_dir)

    assert artifacts.output_gpkg == patch_dir / "Traj" / "raw_dat_pose.gpkg"
    assert artifacts.summary_json == patch_dir / "Traj" / "raw_dat_pose_summary_tool10.json"
    assert artifacts.output_gpkg.is_file()
    rows = _read_layer_rows(artifacts.output_gpkg)
    assert len(rows) == 3
    traj_a = next(row for row in rows if row["properties"]["source_traj_id"] == "traj-a")
    assert traj_a["coordinates"] == [
        (1.0, 0.0, 101.0),
        (2.0, 0.0, 102.0),
        (3.0, 0.0, 103.0),
    ]
    assert [row["properties"]["point_count"] for row in rows if row["properties"]["source_traj_id"] == "traj-b"] == [2, 2]

    with fiona.open(artifacts.output_gpkg, layer="raw_dat_pose") as source:
        assert CRS.from_user_input(source.crs_wkt or source.crs).to_epsg() == 3857
        assert len(source) == 3
    with sqlite3.connect(artifacts.output_gpkg) as conn:
        geometry_type, z_flag = conn.execute(
            "SELECT geometry_type_name, z FROM gpkg_geometry_columns WHERE table_name = 'raw_dat_pose'"
        ).fetchone()
        feature_count = conn.execute(
            "SELECT feature_count FROM gpkg_ogr_contents WHERE table_name = 'raw_dat_pose'"
        ).fetchone()[0]
    assert geometry_type == "LINESTRING"
    assert z_flag == 1
    assert feature_count == 3

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["counts"]["source_file_count"] == 2
    assert summary["counts"]["input_point_count"] == 7
    assert summary["counts"]["output_point_count"] == 7
    assert summary["counts"]["output_segment_count"] == 3
    assert summary["counts"]["split_by_distance_count"] == 1
    assert summary["z_audit"] == {
        "z_preservation": "source_value_unchanged",
        "z_min": 101.0,
        "z_max": 204.0,
    }
    assert summary["geometry_audit"]["point_conservation_passed"] is True
    assert summary["geometry_audit"]["silent_geometry_fix_applied"] is False


@pytest.mark.parametrize(
    ("geometry", "error_text"),
    [
        ({"type": "Point", "coordinates": [0.0, 0.0]}, "missing Z"),
        ({"type": "Point", "coordinates": [0.0, 0.0, math.nan]}, "invalid Z"),
        ({"type": "LineString", "coordinates": [[0.0, 0.0, 1.0], [1.0, 0.0, 2.0]]}, "must be Point"),
    ],
)
def test_tool10_invalid_pointz_fails_without_outputs(
    tmp_path: Path,
    geometry: dict[str, Any],
    error_text: str,
) -> None:
    patch_dir = tmp_path / "invalid"
    _write_trajectory(
        patch_dir,
        "traj-a",
        [
            {"properties": {"frame_id": 1}, "geometry": geometry},
            _point_row([1.0, 0.0, 2.0], 2),
        ],
    )

    with pytest.raises(ValueError, match=error_text):
        run_t08_trajectory_aggregation(patch_dir=patch_dir)

    assert not (patch_dir / "Traj" / "raw_dat_pose.gpkg").exists()
    assert not (patch_dir / "Traj" / "raw_dat_pose_summary_tool10.json").exists()


def test_tool10_missing_crs_requires_explicit_default(tmp_path: Path) -> None:
    patch_dir = tmp_path / "missing-crs"
    _write_trajectory(
        patch_dir,
        "traj-a",
        [_point_row([0.0, 0.0, 1.0], 1), _point_row([1.0, 0.0, 2.0], 2)],
        crs=None,
    )

    with pytest.raises(ValueError, match="CRS not found"):
        run_t08_trajectory_aggregation(patch_dir=patch_dir)
    artifacts = run_t08_trajectory_aggregation(patch_dir=patch_dir, default_crs_text="EPSG:3857")

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["inputs"]["files"][0]["crs_source"] == "default"


def test_tool10_splits_on_time_and_sequence_gaps(tmp_path: Path) -> None:
    patch_dir = tmp_path / "split"
    _write_trajectory(
        patch_dir,
        "time-gap",
        [
            _point_row([0.0, 0.0, 1.0], 1, timestamp=0.0),
            _point_row([1.0, 0.0, 2.0], 2, timestamp=0.1),
            _point_row([2.0, 0.0, 3.0], 3, timestamp=5.0),
            _point_row([3.0, 0.0, 4.0], 4, timestamp=5.1),
        ],
    )
    _write_trajectory(
        patch_dir,
        "seq-gap",
        [
            _point_row([0.0, 10.0, 5.0], 1),
            _point_row([1.0, 10.0, 6.0], 2),
            _point_row([2.0, 10.0, 7.0], 20),
            _point_row([3.0, 10.0, 8.0], 21),
        ],
    )

    artifacts = run_t08_trajectory_aggregation(patch_dir=patch_dir, max_seq_gap=5)

    summary = json.loads(artifacts.summary_json.read_text(encoding="utf-8"))
    assert summary["counts"]["output_segment_count"] == 4
    assert summary["counts"]["split_by_time_count"] == 1
    assert summary["counts"]["split_by_seq_count"] == 1
    assert {row["properties"]["split_reason_before"] for row in _read_layer_rows(artifacts.output_gpkg)} == {"", "time", "seq"}


def test_tool10_single_point_segment_and_failed_overwrite_preserve_existing_outputs(tmp_path: Path) -> None:
    patch_dir = tmp_path / "atomic"
    source_path = _write_trajectory(
        patch_dir,
        "traj-a",
        [_point_row([0.0, 0.0, 1.0], 1), _point_row([1.0, 0.0, 2.0], 2)],
    )
    artifacts = run_t08_trajectory_aggregation(patch_dir=patch_dir)
    original_gpkg = artifacts.output_gpkg.read_bytes()
    original_summary = artifacts.summary_json.read_bytes()

    _write_trajectory(
        patch_dir,
        "traj-a",
        [
            _point_row([0.0, 0.0, 1.0], 1),
            _point_row([100.0, 0.0, 2.0], 2),
            _point_row([101.0, 0.0, 3.0], 3),
        ],
    )
    assert source_path.is_file()
    with pytest.raises(ValueError, match="single-point segment"):
        run_t08_trajectory_aggregation(patch_dir=patch_dir, overwrite=True)

    assert artifacts.output_gpkg.read_bytes() == original_gpkg
    assert artifacts.summary_json.read_bytes() == original_summary
    assert not list((patch_dir / "Traj").glob(".*.tmp.*"))
    assert not list((patch_dir / "Traj").glob(".*.backup.*"))


def test_tool10_script_uses_patch_derived_output_paths_and_overwrite_guard(tmp_path: Path) -> None:
    patch_dir = tmp_path / "cli"
    _write_trajectory(
        patch_dir,
        "traj-a",
        [_point_row([0.0, 0.0, 1.0], 1), _point_row([1.0, 0.0, 2.0], 2)],
    )
    repo_root = Path(__file__).resolve().parents[3]
    command = [
        sys.executable,
        "scripts/t08_tool10_trajectory_aggregation.py",
        "--patch-dir",
        str(patch_dir),
    ]

    first = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, check=False)
    second = subprocess.run(command, cwd=repo_root, text=True, capture_output=True, check=False)

    assert first.returncode == 0, first.stderr
    artifacts = json.loads(first.stdout)
    assert Path(artifacts["output_gpkg"]) == patch_dir / "Traj" / "raw_dat_pose.gpkg"
    assert Path(artifacts["summary_json"]) == patch_dir / "Traj" / "raw_dat_pose_summary_tool10.json"
    assert second.returncode == 2
    assert "Output already exists" in second.stderr


def test_tool10_innernet_batch_script_accepts_patch_arguments(tmp_path: Path) -> None:
    patch_a = tmp_path / "batch-a"
    patch_b = tmp_path / "batch-b"
    for patch_dir, z_start in ((patch_a, 10.0), (patch_b, 20.0)):
        _write_trajectory(
            patch_dir,
            "traj-a",
            [
                _point_row([0.0, 0.0, z_start], 1),
                _point_row([1.0, 0.0, z_start + 1.0], 2),
            ],
        )

    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "t08_tool10_run_patches_innernet.sh"
    no_args = subprocess.run(
        ["bash", str(script)],
        cwd=repo_root,
        text=True,
        capture_output=True,
        check=False,
    )
    environment = dict(os.environ)
    environment.update({"PYTHON": sys.executable, "LOG_ROOT": str(tmp_path / "logs")})
    result = subprocess.run(
        ["bash", str(script), str(patch_a), str(patch_b)],
        cwd=repo_root,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert no_args.returncode == 2
    assert "PATCH_DIR [PATCH_DIR ...]" in no_args.stderr
    assert result.returncode == 0, result.stderr
    assert "patch_count=2" in result.stdout
    assert "success_count=2" in result.stdout
    for patch_dir in (patch_a, patch_b):
        assert (patch_dir / "Traj" / "raw_dat_pose.gpkg").is_file()
        assert (patch_dir / "Traj" / "raw_dat_pose_summary_tool10.json").is_file()
        assert (tmp_path / "logs" / f"{patch_dir.name}.log").is_file()
