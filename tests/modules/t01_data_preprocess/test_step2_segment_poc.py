from __future__ import annotations

import csv
import json
from pathlib import Path

from rcsd_topo_poc.cli import main
from rcsd_topo_poc.modules.t01_data_preprocess import step1_pair_poc, step2_segment_poc


def _write_geojson(path: Path, *, features: list[dict]) -> None:
    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
        "features": features,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _node_feature(
    node_id: int,
    x: float,
    y: float,
    *,
    kind: int = 4,
    grade: int = 1,
    closed_con: int = 2,
) -> dict:
    return {
        "type": "Feature",
        "properties": {"id": node_id, "kind": kind, "grade": grade, "closed_con": closed_con},
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


def _road_feature(
    road_id: str,
    snodeid: int,
    enodeid: int,
    direction: int,
    coords: list[list[float]],
    *,
    formway: int = 0,
) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "formway": formway,
        },
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open("r", encoding="utf-8-sig")))


def _write_strategy(path: Path) -> Path:
    payload = {
        "strategy_id": "S2X",
        "description": "Synthetic Step2 strategy: S2 seed/terminate, through disabled for test focus.",
        "seed_rule": {"kind_bits_all": [2], "closed_con_in": [2, 3], "grade_eq": 1},
        "terminate_rule": {"kind_bits_all": [2], "closed_con_in": [2, 3], "grade_eq": 1},
        "through_node_rule": {"incident_road_degree_eq": 99, "incident_degree_exclude_formway_bits_any": [7]},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _build_counterclockwise_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"
    node_features = [
        _node_feature(1, 0.0, 0.0),
        _node_feature(2, 1.0, 1.0, kind=0, grade=0, closed_con=0),
        _node_feature(3, 2.0, 0.0),
        _node_feature(4, 1.0, -1.0, kind=0, grade=0, closed_con=0),
        _node_feature(5, 1.0, 2.0),
        _node_feature(6, 1.2, 0.0, kind=0, grade=0, closed_con=0),
    ]
    road_features = [
        _road_feature("r14", 1, 4, 2, [[0.0, 0.0], [1.0, -1.0]]),
        _road_feature("r43", 4, 3, 2, [[1.0, -1.0], [2.0, 0.0]]),
        _road_feature("r32", 3, 2, 2, [[2.0, 0.0], [1.0, 1.0]]),
        _road_feature("r21", 2, 1, 2, [[1.0, 1.0], [0.0, 0.0]]),
        _road_feature("r25", 2, 5, 2, [[1.0, 1.0], [1.0, 2.0]]),
        _road_feature("r46", 4, 6, 0, [[1.0, -1.0], [1.2, 0.0]]),
        _road_feature("r62", 6, 2, 0, [[1.2, 0.0], [1.0, 1.0]]),
    ]
    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _build_clockwise_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"
    node_features = [
        _node_feature(1, 0.0, 0.0),
        _node_feature(2, 1.0, 1.0, kind=0, grade=0, closed_con=0),
        _node_feature(3, 2.0, 0.0),
        _node_feature(4, 1.0, -1.0, kind=0, grade=0, closed_con=0),
    ]
    road_features = [
        _road_feature("r12", 1, 2, 2, [[0.0, 0.0], [1.0, 1.0]]),
        _road_feature("r23", 2, 3, 2, [[1.0, 1.0], [2.0, 0.0]]),
        _road_feature("r34", 3, 4, 2, [[2.0, 0.0], [1.0, -1.0]]),
        _road_feature("r41", 4, 1, 2, [[1.0, -1.0], [0.0, 0.0]]),
    ]
    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _build_left_turn_polluted_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path, node_path = _build_counterclockwise_dataset(base_dir)
    doc = _load_json(road_path)
    for feature in doc["features"]:
        if feature["properties"]["id"] == "r32":
            feature["properties"]["formway"] = 256
    road_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return road_path, node_path


def _build_disconnected_cycle_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path, node_path = _build_counterclockwise_dataset(base_dir)
    node_doc = _load_json(node_path)
    node_doc["features"].extend(
        [
            _node_feature(7, 3.0, 1.0, kind=0, grade=0, closed_con=0),
            _node_feature(8, 4.0, 1.0, kind=0, grade=0, closed_con=0),
            _node_feature(9, 3.5, 2.0, kind=0, grade=0, closed_con=0),
        ]
    )
    node_path.write_text(json.dumps(node_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    road_doc = _load_json(road_path)
    road_doc["features"].extend(
        [
            _road_feature("r78", 7, 8, 0, [[3.0, 1.0], [4.0, 1.0]]),
            _road_feature("r89", 8, 9, 0, [[4.0, 1.0], [3.5, 2.0]]),
            _road_feature("r97", 9, 7, 0, [[3.5, 2.0], [3.0, 1.0]]),
        ]
    )
    road_path.write_text(json.dumps(road_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return road_path, node_path


def test_step2_segment_poc_validates_and_prunes_counterclockwise_segment(tmp_path: Path) -> None:
    road_path, node_path = _build_counterclockwise_dataset(tmp_path)
    strategy_path = _write_strategy(tmp_path / "step2_strategy.json")
    out_root = tmp_path / "outputs"

    rc = main(
        [
            "t01-step2-segment-poc",
            "--road-path",
            str(road_path),
            "--node-path",
            str(node_path),
            "--strategy-config",
            str(strategy_path),
            "--out-root",
            str(out_root),
        ]
    )

    assert rc == 0

    candidate_rows = _read_csv_rows(out_root / "S2X" / "pair_candidates.csv")
    validated_rows = _read_csv_rows(out_root / "S2X" / "validated_pairs.csv")
    validation_rows = _read_csv_rows(out_root / "S2X" / "pair_validation_table.csv")
    summary = _load_json(out_root / "S2X" / "segment_summary.json")
    branch_cut = _load_json(out_root / "S2X" / "branch_cut_roads.geojson")
    trunk = _load_json(out_root / "S2X" / "trunk_roads.geojson")
    segment = _load_json(out_root / "S2X" / "segment_roads.geojson")

    assert [row["pair_id"] for row in candidate_rows] == ["S2X:1__3"]
    assert [row["pair_id"] for row in validated_rows] == ["S2X:1__3"]
    assert validation_rows[0]["validated_status"] == "validated"
    assert validation_rows[0]["reject_reason"] == ""
    assert summary["candidate_pair_count"] == 1
    assert summary["validated_pair_count"] == 1
    assert summary["prune_branch_count"] == 1
    assert {feature["properties"]["road_id"] for feature in branch_cut["features"]} == {"r25"}
    trunk_ids = {feature["properties"]["road_id"] for feature in trunk["features"]}
    segment_ids = {feature["properties"]["road_id"] for feature in segment["features"]}
    assert trunk_ids == {"r14", "r43", "r32", "r21"}
    assert segment_ids == {"r14", "r43", "r32", "r21", "r46", "r62"}


def test_step2_rejects_clockwise_only_candidate(tmp_path: Path) -> None:
    road_path, node_path = _build_clockwise_dataset(tmp_path)
    strategy_path = _write_strategy(tmp_path / "step2_strategy.json")
    out_root = tmp_path / "outputs"

    rc = main(
        [
            "t01-step2-segment-poc",
            "--road-path",
            str(road_path),
            "--node-path",
            str(node_path),
            "--strategy-config",
            str(strategy_path),
            "--out-root",
            str(out_root),
        ]
    )

    assert rc == 0
    rejected_rows = _read_csv_rows(out_root / "S2X" / "rejected_pair_candidates.csv")
    summary = _load_json(out_root / "S2X" / "segment_summary.json")

    assert len(rejected_rows) == 1
    assert rejected_rows[0]["reject_reason"] == "only_clockwise_loop"
    assert summary["validated_pair_count"] == 0
    assert summary["rejected_pair_count"] == 1
    assert summary["clockwise_reject_count"] == 1


def test_step2_strict_rejects_left_turn_polluted_trunk(tmp_path: Path) -> None:
    road_path, node_path = _build_left_turn_polluted_dataset(tmp_path)
    strategy_path = _write_strategy(tmp_path / "step2_strategy.json")
    out_root = tmp_path / "outputs"

    rc = main(
        [
            "t01-step2-segment-poc",
            "--road-path",
            str(road_path),
            "--node-path",
            str(node_path),
            "--strategy-config",
            str(strategy_path),
            "--formway-mode",
            "strict",
            "--out-root",
            str(out_root),
        ]
    )

    assert rc == 0
    rejected_rows = _read_csv_rows(out_root / "S2X" / "rejected_pair_candidates.csv")
    assert rejected_rows[0]["reject_reason"] == "left_turn_only_polluted_trunk"


def test_step2_rejects_disconnected_after_prune(monkeypatch, tmp_path: Path) -> None:
    road_path, node_path = _build_disconnected_cycle_dataset(tmp_path)
    strategy_path = _write_strategy(tmp_path / "step2_strategy.json")
    context = step1_pair_poc.build_step1_graph_context(road_path=road_path, node_path=node_path)
    strategy = step1_pair_poc._load_strategy(strategy_path)
    execution = step1_pair_poc.run_step1_strategy(context, strategy)
    road_endpoints, undirected_adjacency = step2_segment_poc._build_semantic_endpoints(context)

    assert len(execution.pair_candidates) == 1
    pair = execution.pair_candidates[0]

    def _fake_candidate_channel(*_args, **_kwargs):
        return {"r14", "r43", "r32", "r21", "r78", "r89", "r97"}, set()

    monkeypatch.setattr(step2_segment_poc, "_build_candidate_channel", _fake_candidate_channel)
    validations = step2_segment_poc._validate_pair_candidates(
        execution,
        context=context,
        road_endpoints=road_endpoints,
        undirected_adjacency=undirected_adjacency,
        formway_mode="strict",
        left_turn_formway_bit=8,
    )

    assert len(validations) == 1
    assert validations[0].reject_reason == "disconnected_after_prune"
