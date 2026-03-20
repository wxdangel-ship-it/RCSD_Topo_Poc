from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Optional

from rcsd_topo_poc.cli import main
from rcsd_topo_poc.modules.t01_data_preprocess import step1_pair_poc


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
    mainnodeid: Optional[int] = None,
) -> dict:
    properties = {
        "id": node_id,
        "kind": kind,
        "grade": grade,
        "closed_con": closed_con,
    }
    if mainnodeid is not None:
        properties["mainnodeid"] = mainnodeid
    return {
        "type": "Feature",
        "properties": properties,
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


def _write_strategy(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _build_compound_intersection_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "compound_roads.geojson"
    node_path = base_dir / "compound_nodes.geojson"

    node_features = [
        _node_feature(1, 0.0, 0.0, grade=1),
        _node_feature(100, 0.02, 0.0, grade=1, closed_con=2),
        _node_feature(101, 0.0205, 0.0005, kind=0, grade=9, closed_con=1, mainnodeid=100),
    ]
    road_features = [
        _road_feature("r1_101", 1, 101, 0, [[0.0, 0.0], [0.0205, 0.0005]]),
        _road_feature("r100_101_internal", 100, 101, 0, [[0.02, 0.0], [0.0205, 0.0005]]),
    ]

    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _build_formway_turn_lane_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "formway_roads.geojson"
    node_path = base_dir / "formway_nodes.geojson"

    node_features = [
        _node_feature(10, 0.0, 0.0),
        _node_feature(20, 0.01, 0.0),
        _node_feature(30, 0.02, 0.0),
        _node_feature(40, 0.01, 0.01, kind=0, grade=0, closed_con=0),
        _node_feature(50, 0.01, -0.01, kind=0, grade=0, closed_con=0),
    ]
    road_features = [
        _road_feature("r10_20", 10, 20, 0, [[0.0, 0.0], [0.01, 0.0]]),
        _road_feature("r20_30", 20, 30, 0, [[0.01, 0.0], [0.02, 0.0]]),
        _road_feature("r20_40_right_turn", 20, 40, 0, [[0.01, 0.0], [0.01, 0.01]], formway=128),
        _road_feature("r50_20_right_turn", 50, 20, 0, [[0.01, -0.01], [0.01, 0.0]], formway=128),
    ]

    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _build_force_terminate_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "force_terminate_roads.geojson"
    node_path = base_dir / "force_terminate_nodes.geojson"

    node_features = [
        _node_feature(1, 0.0, 0.0, grade=2, closed_con=2),
        _node_feature(2, 0.01, 0.0, grade=2, closed_con=2),
        _node_feature(3, 0.02, 0.0, grade=2, closed_con=2),
    ]
    road_features = [
        _road_feature("r12", 1, 2, 0, [[0.0, 0.0], [0.01, 0.0]]),
        _road_feature("r23", 2, 3, 0, [[0.01, 0.0], [0.02, 0.0]]),
    ]

    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


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
        assert (strategy_dir / "pair_candidate_nodes.geojson").is_file()
        assert (strategy_dir / "pair_links_candidates.geojson").is_file()
        assert (strategy_dir / "pair_candidates.csv").is_file()
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


def test_eligible_seed_terminate_node_can_be_forced_not_through(tmp_path: Path) -> None:
    road_path, node_path = _build_force_terminate_dataset(tmp_path)
    out_root = tmp_path / "outputs_force_terminate"
    strategy_path = _write_strategy(
        tmp_path / "step1_force_terminate.json",
        {
            "strategy_id": "S_FORCE",
            "description": "Do not traverse through eligible terminate nodes.",
            "seed_rule": {"kind_bits_all": [2], "grade_eq": 2, "closed_con_in": [2]},
            "terminate_rule": {"kind_bits_all": [2], "grade_eq": 2, "closed_con_in": [2]},
            "through_node_rule": {
                "incident_road_degree_eq": 2,
                "disallow_seed_terminate_nodes": True,
            },
        },
    )

    rc = main(
        [
            "t01-step1-pair-poc",
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
    pair_table = (out_root / "S_FORCE" / "pair_table.csv").read_text(encoding="utf-8")
    summary = _load_json(out_root / "S_FORCE" / "pair_summary.json")

    assert "S_FORCE:1__2" in pair_table
    assert "S_FORCE:2__3" in pair_table
    assert "S_FORCE:1__3" not in pair_table
    assert summary["through_seed_pruned_count"] == 0


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


def test_search_audit_uses_counts_and_capped_samples(monkeypatch, tmp_path: Path) -> None:
    road_path, node_path = _build_dataset(tmp_path)
    out_root = tmp_path / "outputs"
    monkeypatch.setattr(step1_pair_poc, "SEARCH_EVENT_SAMPLE_LIMIT_PER_TYPE", 1)

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
    audit = _load_json(out_root / "S1" / "search_audit.json")
    summary = _load_json(out_root / "S1" / "pair_summary.json")

    assert audit["search_event_counts"]["through_continue"] >= 1
    assert audit["search_event_counts"]["reverse_confirm_fail"] >= 1
    assert audit["search_event_sample_limit_per_type"] == 1
    assert len([event for event in audit["search_events"] if event["event"] == "through_continue"]) <= 1
    assert summary["search_event_sample_limit_per_type"] == 1


def test_through_seed_is_pruned_from_pair_search(tmp_path: Path) -> None:
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
    summary = _load_json(out_root / "S1" / "pair_summary.json")

    assert summary["seed_count"] == 7
    assert summary["search_seed_count"] == 6
    assert summary["through_seed_pruned_count"] == 1


def test_mainnodeid_group_is_handled_as_one_semantic_intersection(tmp_path: Path) -> None:
    road_path, node_path = _build_compound_intersection_dataset(tmp_path)
    out_root = tmp_path / "outputs"

    rc = main(
        [
            "t01-step1-pair-poc",
            "--road-path",
            str(road_path),
            "--node-path",
            str(node_path),
            "--strategy-config",
            "configs/t01_data_preprocess/step1_pair_s2.json",
            "--out-root",
            str(out_root),
        ]
    )

    assert rc == 0

    pair_table = (out_root / "S2" / "pair_table.csv").read_text(encoding="utf-8")
    pair_summary = _load_json(out_root / "S2" / "pair_summary.json")
    rule_audit = _load_json(out_root / "S2" / "rule_audit.json")
    search_audit = _load_json(out_root / "S2" / "search_audit.json")
    pair_nodes = _load_json(out_root / "S2" / "pair_nodes.geojson")

    assert "S2:1__100" in pair_table
    assert pair_summary["pair_count"] == 1
    assert pair_summary["total_nodes"] == 2
    assert pair_summary["total_physical_nodes"] == 3

    grouped_node = next(row for row in rule_audit if row["semantic_node_id"] == "100")
    assert grouped_node["representative_node_id"] == "100"
    assert grouped_node["member_node_count"] == 2
    assert grouped_node["seed_match"] is True
    assert grouped_node["terminate_match"] is True

    pair_node_props = next(
        feature["properties"] for feature in pair_nodes["features"] if feature["properties"]["semantic_node_id"] == "100"
    )
    assert pair_node_props["semantic_node_id"] == "100"
    assert pair_node_props["representative_node_id"] == "100"
    assert pair_node_props["member_node_count"] == 2

    event_names = {event["event"] for event in search_audit["graph_events"]}
    assert "semantic_intersection_grouped" in event_names
    assert "internal_semantic_road" in event_names


def test_formway_right_turn_lane_is_excluded_from_through_degree(tmp_path: Path) -> None:
    road_path, node_path = _build_formway_turn_lane_dataset(tmp_path)
    out_root = tmp_path / "outputs"
    strategy_path = _write_strategy(
        tmp_path / "formway_strategy.json",
        {
            "strategy_id": "Sx",
            "description": "Seed/terminate use kind+grade+closed_con; through degree excludes right-turn-only roads.",
            "seed_rule": {
                "kind_bits_all": [2],
                "closed_con_in": [2, 3],
                "grade_eq": 1,
            },
            "terminate_rule": {
                "kind_bits_all": [2],
                "closed_con_in": [2, 3],
                "grade_eq": 1,
            },
            "through_node_rule": {
                "incident_road_degree_eq": 2,
                "incident_degree_exclude_formway_bits_any": [7],
            },
        },
    )

    rc = main(
        [
            "t01-step1-pair-poc",
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

    pair_rows = list(csv.DictReader((out_root / "Sx" / "pair_table.csv").open("r", encoding="utf-8-sig")))
    summary = _load_json(out_root / "Sx" / "pair_summary.json")

    assert len(pair_rows) == 1
    assert pair_rows[0]["pair_id"] == "Sx:10__30"
    support_info = json.loads(pair_rows[0]["support_info"])
    assert support_info["through_node_ids"] == ["20"]
    assert summary["pair_count"] == 1
    assert summary["search_seed_count"] == 2
    assert summary["through_seed_pruned_count"] == 1
