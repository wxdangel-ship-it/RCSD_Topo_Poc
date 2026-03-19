from __future__ import annotations

import json
from pathlib import Path

from rcsd_topo_poc.cli import main


def _write_geojson(path: Path, *, features: list[dict]) -> None:
    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": features,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _node_feature(node_id: int, x: float, y: float) -> dict:
    return {
        "type": "Feature",
        "properties": {"id": node_id, "kind": 4, "grade": 1, "closed_con": 2},
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


def _road_feature(road_id: str, snodeid: int, enodeid: int, coords: list[list[float]]) -> dict:
    return {
        "type": "Feature",
        "properties": {"id": road_id, "snodeid": snodeid, "enodeid": enodeid, "direction": 0},
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _build_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"

    node_features = []
    road_features = []
    for row in range(4):
        for col in range(4):
            node_id = row * 4 + col + 1
            node_features.append(_node_feature(node_id, col * 0.01, row * 0.01))

    for row in range(4):
        for col in range(3):
            a = row * 4 + col + 1
            b = a + 1
            road_features.append(_road_feature(f"h_{a}_{b}", a, b, [[col * 0.01, row * 0.01], [(col + 1) * 0.01, row * 0.01]]))

    for row in range(3):
        for col in range(4):
            a = row * 4 + col + 1
            b = a + 4
            road_features.append(_road_feature(f"v_{a}_{b}", a, b, [[col * 0.01, row * 0.01], [col * 0.01, (row + 1) * 0.01]]))

    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _write_profile_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "profiles": [
                    {"profile_id": "XS", "target_core_node_count": 4, "description": "xs"},
                    {"profile_id": "S", "target_core_node_count": 8, "description": "s"},
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_build_validation_slices_generates_multiple_profiles(tmp_path: Path) -> None:
    road_path, node_path = _build_dataset(tmp_path)
    profile_config = tmp_path / "slice_profiles.json"
    out_root = tmp_path / "slice_outputs"
    _write_profile_config(profile_config)

    rc = main(
        [
            "t01-build-validation-slices",
            "--road-path",
            str(road_path),
            "--node-path",
            str(node_path),
            "--profile-config",
            str(profile_config),
            "--out-root",
            str(out_root),
        ]
    )

    assert rc == 0
    for profile_id in ("XS", "S"):
        profile_dir = out_root / profile_id
        assert (profile_dir / "roads.geojson").is_file()
        assert (profile_dir / "nodes.geojson").is_file()
        assert (profile_dir / "slice_summary.json").is_file()

    manifest = _load_json(out_root / "slice_manifest.json")
    xs_summary = _load_json(out_root / "XS" / "slice_summary.json")
    s_summary = _load_json(out_root / "S" / "slice_summary.json")

    assert manifest["source_node_count"] == 16
    assert manifest["source_road_count"] == 24
    assert xs_summary["output_node_count"] >= xs_summary["core_node_count"]
    assert s_summary["output_node_count"] >= s_summary["core_node_count"]
    assert xs_summary["output_node_count"] <= s_summary["output_node_count"]
