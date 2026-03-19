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


def _node_feature(node_id: int, x: float, y: float, *, kind: int = 4, grade: int = 1, closed_con: int = 2) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": node_id,
            "kind": kind,
            "grade": grade,
            "closed_con": closed_con,
        },
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


def _road_feature(road_id: str, snodeid: int, enodeid: int, direction: int, coords: list[list[float]]) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
        },
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _build_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"

    node_features = [
        _node_feature(1, 0.0, 0.0, grade=1),
        _node_feature(2, 0.01, 0.0, grade=2),
        _node_feature(3, 0.02, 0.0, grade=2),
        _node_feature(4, 0.03, 0.01, grade=1),
        _node_feature(5, 0.03, -0.01, grade=1),
        _node_feature(8, 0.0, 0.02, grade=1),
        _node_feature(9, 0.01, 0.02, grade=1),
    ]
    road_features = [
        _road_feature("r12", 1, 2, 0, [[0.0, 0.0], [0.01, 0.0]]),
        _road_feature("r23", 2, 3, 0, [[0.01, 0.0], [0.02, 0.0]]),
        _road_feature("r34", 3, 4, 0, [[0.02, 0.0], [0.03, 0.01]]),
        _road_feature("r35", 3, 5, 0, [[0.02, 0.0], [0.03, -0.01]]),
        _road_feature("r89", 8, 9, 2, [[0.0, 0.02], [0.01, 0.02]]),
    ]

    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_step1_pair_poc_generates_strategy_outputs(tmp_path: Path) -> None:
    road_path, node_path = _build_dataset(tmp_path)
    out_root = tmp_path / "outputs"

    rc = main(
        [
            "t01-step1-pair-poc",
            "--road-path",
            str(road_path),
            "--node-path",
            str(node_path),
            "--strategy-config",
            "configs/t01_data_preprocess/step1_pair_s1.json",
            "--strategy-config",
            "configs/t01_data_preprocess/step1_pair_s2.json",
            "--out-root",
            str(out_root),
        ]
    )

    assert rc == 0
    for strategy_id in ("S1", "S2"):
        strategy_dir = out_root / strategy_id
        assert (strategy_dir / "seed_nodes.geojson").is_file()
        assert (strategy_dir / "terminate_nodes.geojson").is_file()
        assert (strategy_dir / "pair_nodes.geojson").is_file()
        assert (strategy_dir / "pair_links.geojson").is_file()
        assert (strategy_dir / "pair_support_roads.geojson").is_file()
        assert (strategy_dir / "pair_summary.json").is_file()
        assert (strategy_dir / "pair_table.csv").is_file()


def test_through_node_does_not_terminate_early(tmp_path: Path) -> None:
    road_path, node_path = _build_dataset(tmp_path)
    out_root = tmp_path / "outputs"

    rc = main(
        [
            "t01-step1-pair-poc",
            "--road-path",
            str(road_path),
            "--node-path",
            str(node_path),
            "--strategy-config",
            "configs/t01_data_preprocess/step1_pair_s1.json",
            "--out-root",
            str(out_root),
        ]
    )

    assert rc == 0
    pair_table = (out_root / "S1" / "pair_table.csv").read_text(encoding="utf-8")
    summary = _load_json(out_root / "S1" / "pair_summary.json")

    assert "S1:1__3" in pair_table
    assert "S1:1__2" not in pair_table
    assert summary["through_pass_count"] >= 1


def test_reverse_confirmation_is_required(tmp_path: Path) -> None:
    road_path, node_path = _build_dataset(tmp_path)
    out_root = tmp_path / "outputs"

    rc = main(
        [
            "t01-step1-pair-poc",
            "--road-path",
            str(road_path),
            "--node-path",
            str(node_path),
            "--strategy-config",
            "configs/t01_data_preprocess/step1_pair_s1.json",
            "--out-root",
            str(out_root),
        ]
    )

    assert rc == 0
    pair_table = (out_root / "S1" / "pair_table.csv").read_text(encoding="utf-8")
    summary = _load_json(out_root / "S1" / "pair_summary.json")

    assert "S1:8__9" not in pair_table
    assert summary["reverse_confirm_fail_count"] >= 1


def test_default_out_root_uses_standard_run_id(monkeypatch, tmp_path: Path) -> None:
    road_path, node_path = _build_dataset(tmp_path)
    repo_root = Path(__file__).resolve().parents[3]
    repo_like_root = tmp_path / "repo"
    (repo_like_root / "docs").mkdir(parents=True, exist_ok=True)
    (repo_like_root / "SPEC.md").write_text("spec\n", encoding="utf-8")
    monkeypatch.chdir(repo_like_root)

    run_id = "t01_step1_pair_poc_20990101_010203"
    rc = main(
        [
            "t01-step1-pair-poc",
            "--road-path",
            str(road_path),
            "--node-path",
            str(node_path),
            "--strategy-config",
            str(repo_root / "configs" / "t01_data_preprocess" / "step1_pair_s1.json"),
            "--run-id",
            run_id,
        ]
    )

    assert rc == 0
    default_out_root = repo_like_root / "outputs" / "_work" / "t01_step1_pair_poc" / run_id
    assert (default_out_root / "strategy_comparison.json").is_file()
    assert (default_out_root / "S1" / "pair_summary.json").is_file()
