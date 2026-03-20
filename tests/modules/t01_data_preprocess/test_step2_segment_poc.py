from __future__ import annotations

import csv
import json
from pathlib import Path

from shapely.geometry import LineString

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


def _minimal_strategy(strategy_id: str = "S2X") -> step1_pair_poc.StrategySpec:
    rule = step1_pair_poc.RuleSpec(kind_bits_all=(2,), grade_eq=1, closed_con_in=(2, 3))
    return step1_pair_poc.StrategySpec(
        strategy_id=strategy_id,
        description="synthetic",
        seed_rule=rule,
        terminate_rule=rule,
        through_rule=step1_pair_poc.ThroughRuleSpec(incident_road_degree_eq=2),
    )


def _minimal_execution(
    pairs: list[step1_pair_poc.PairRecord],
    *,
    terminate_ids: list[str] | None = None,
    strategy_id: str = "S2X",
) -> step1_pair_poc.Step1StrategyExecution:
    return step1_pair_poc.Step1StrategyExecution(
        strategy=_minimal_strategy(strategy_id),
        seed_eval={},
        terminate_eval={},
        seed_ids=[],
        terminate_ids=[] if terminate_ids is None else terminate_ids,
        through_node_ids=set(),
        search_seed_ids=[],
        through_seed_pruned_count=0,
        search_results={},
        search_event_counts={},
        search_event_samples=[],
        pair_candidates=pairs,
    )


def _minimal_context(
    roads: list[step1_pair_poc.RoadRecord],
    *,
    directed: dict[str, tuple[step1_pair_poc.TraversalEdge, ...]] | None = None,
) -> step1_pair_poc.Step1GraphContext:
    return step1_pair_poc.Step1GraphContext(
        physical_nodes={},
        roads={road.road_id: road for road in roads},
        semantic_nodes={},
        physical_to_semantic={},
        directed={} if directed is None else directed,
        blocked={},
        orphan_ref_count=0,
        graph_audit_events=[],
    )


def _road_record(road_id: str, snodeid: str, enodeid: str) -> step1_pair_poc.RoadRecord:
    base = float(sum(ord(ch) for ch in road_id) % 17)
    return step1_pair_poc.RoadRecord(
        road_id=road_id,
        snodeid=snodeid,
        enodeid=enodeid,
        direction=0,
        formway=0,
        geometry=LineString([(base, 0.0), (base + 0.5, 1.0)]),
        raw_properties={},
    )


def _pair_record(
    pair_id: str,
    a_node_id: str,
    b_node_id: str,
    road_ids: tuple[str, ...],
    *,
    strategy_id: str = "S2X",
) -> step1_pair_poc.PairRecord:
    return step1_pair_poc.PairRecord(
        pair_id=pair_id,
        a_node_id=a_node_id,
        b_node_id=b_node_id,
        strategy_id=strategy_id,
        reverse_confirmed=True,
        forward_path_node_ids=(a_node_id, b_node_id),
        forward_path_road_ids=road_ids,
        reverse_path_node_ids=(b_node_id, a_node_id),
        reverse_path_road_ids=tuple(reversed(road_ids)),
        through_node_ids=(),
    )


def _validation_result(
    pair_id: str,
    a_node_id: str,
    b_node_id: str,
    *,
    pruned_road_ids: tuple[str, ...],
    trunk_road_ids: tuple[str, ...],
    segment_road_ids: tuple[str, ...],
    validated_status: str = "validated",
) -> step2_segment_poc.PairValidationResult:
    return step2_segment_poc.PairValidationResult(
        pair_id=pair_id,
        a_node_id=a_node_id,
        b_node_id=b_node_id,
        candidate_status="candidate",
        validated_status=validated_status,
        reject_reason=None if validated_status == "validated" else "synthetic_reject",
        trunk_mode="counterclockwise_loop",
        trunk_found=validated_status == "validated",
        counterclockwise_ok=validated_status == "validated",
        left_turn_excluded_mode="strict",
        warning_codes=(),
        candidate_channel_road_ids=pruned_road_ids,
        pruned_road_ids=pruned_road_ids,
        trunk_road_ids=trunk_road_ids,
        segment_road_ids=segment_road_ids,
        residual_road_ids=(),
        branch_cut_road_ids=(),
        boundary_terminate_node_ids=(),
        transition_same_dir_blocked=False,
        support_info={"branch_cut_infos": []},
        conflict_pair_id=None,
    )


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


def _build_segment_formway_filtered_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path, node_path = _build_counterclockwise_dataset(base_dir)
    doc = _load_json(road_path)
    for feature in doc["features"]:
        if feature["properties"]["id"] == "r46":
            feature["properties"]["formway"] = 128
    road_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return road_path, node_path


def _build_through_collapsed_corridor_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"
    node_features = [
        _node_feature(1, 0.0, 0.0),
        _node_feature(2, 1.0, 0.0),
        _node_feature(3, 2.0, 0.0),
        _node_feature(4, 1.0, 1.0, kind=0, grade=0, closed_con=0),
        _node_feature(5, 1.0, -1.0, kind=0, grade=0, closed_con=0),
    ]
    road_features = [
        _road_feature("r12", 1, 2, 1, [[0.0, 0.0], [1.0, 0.0]]),
        _road_feature("r23", 2, 3, 1, [[1.0, 0.0], [2.0, 0.0]]),
        _road_feature("r24", 2, 4, 1, [[1.0, 0.0], [1.0, 1.0]], formway=128),
        _road_feature("r25", 2, 5, 1, [[1.0, 0.0], [1.0, -1.0]], formway=128),
    ]
    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
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


def _build_bridge_cycle_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path, node_path = _build_counterclockwise_dataset(base_dir)
    node_doc = _load_json(node_path)
    node_doc["features"].extend(
        [
            _node_feature(7, 2.0, 1.5, kind=0, grade=0, closed_con=0),
            _node_feature(8, 3.0, 1.5, kind=0, grade=0, closed_con=0),
            _node_feature(9, 2.5, 2.2, kind=0, grade=0, closed_con=0),
        ]
    )
    node_path.write_text(json.dumps(node_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    road_doc = _load_json(road_path)
    road_doc["features"].extend(
        [
            _road_feature("r27", 2, 7, 0, [[1.0, 1.0], [2.0, 1.5]]),
            _road_feature("r78", 7, 8, 0, [[2.0, 1.5], [3.0, 1.5]]),
            _road_feature("r89", 8, 9, 0, [[3.0, 1.5], [2.5, 2.2]]),
            _road_feature("r97", 9, 7, 0, [[2.5, 2.2], [2.0, 1.5]]),
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
    segment_body = _load_json(out_root / "S2X" / "segment_body_roads.geojson")
    residual = _load_json(out_root / "S2X" / "step3_residual_roads.geojson")
    trunk_members = _load_json(out_root / "S2X" / "trunk_road_members.geojson")
    segment_members = _load_json(out_root / "S2X" / "segment_body_road_members.geojson")

    assert [row["pair_id"] for row in candidate_rows] == ["S2X:1__3"]
    assert [row["pair_id"] for row in validated_rows] == ["S2X:1__3"]
    assert validation_rows[0]["validated_status"] == "validated"
    assert validation_rows[0]["reject_reason"] == ""
    assert summary["candidate_pair_count"] == 1
    assert summary["validated_pair_count"] == 1
    assert summary["prune_branch_count"] == 1
    assert summary["branch_cut_component_count"] == 1
    assert summary["other_terminate_cut_count"] == 1
    assert summary["residual_component_count"] == 0
    assert {feature["properties"]["road_id"] for feature in branch_cut["features"]} == {"r25"}
    assert len(trunk["features"]) == 1
    assert len(segment_body["features"]) == 1
    assert residual["features"] == []
    assert trunk["features"][0]["geometry"]["type"] == "MultiLineString"
    assert segment_body["features"][0]["geometry"]["type"] == "MultiLineString"
    assert set(trunk["features"][0]["properties"]["road_ids"]) == {"r14", "r43", "r32", "r21"}
    assert set(segment_body["features"][0]["properties"]["road_ids"]) == {"r14", "r43", "r32", "r21", "r46", "r62"}
    trunk_member_ids = {feature["properties"]["road_id"] for feature in trunk_members["features"]}
    segment_member_ids = {feature["properties"]["road_id"] for feature in segment_members["features"]}
    assert trunk_member_ids == {"r14", "r43", "r32", "r21"}
    assert segment_member_ids == {"r14", "r43", "r32", "r21", "r46", "r62"}


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


def test_step2_segment_excludes_step1_formway_branches(tmp_path: Path) -> None:
    road_path, node_path = _build_segment_formway_filtered_dataset(tmp_path)
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

    validation_rows = _read_csv_rows(out_root / "S2X" / "pair_validation_table.csv")
    segment_body = _load_json(out_root / "S2X" / "segment_body_roads.geojson")
    residual = _load_json(out_root / "S2X" / "step3_residual_roads.geojson")
    branch_cut = _load_json(out_root / "S2X" / "branch_cut_roads.geojson")

    assert validation_rows[0]["validated_status"] == "validated"
    assert validation_rows[0]["segment_body_road_count"] == "4"
    assert validation_rows[0]["residual_road_count"] == "2"
    assert set(segment_body["features"][0]["properties"]["road_ids"]) == {"r14", "r43", "r32", "r21"}
    assert set(residual["features"][0]["properties"]["road_ids"]) == {"r46", "r62"}

    cut_reasons = {
        (feature["properties"]["road_id"], feature["properties"]["cut_reason"])
        for feature in branch_cut["features"]
    }
    assert ("r25", "branch_leads_to_other_terminate") in cut_reasons


def test_step2_segment_prunes_bridge_connected_side_cycle(tmp_path: Path) -> None:
    road_path, node_path = _build_bridge_cycle_dataset(tmp_path)
    strategy = step1_pair_poc._load_strategy(_write_strategy(tmp_path / "step2_strategy.json"))
    context = step1_pair_poc.build_step1_graph_context(road_path=road_path, node_path=node_path)
    execution = step1_pair_poc.run_step1_strategy(context, strategy)
    road_endpoints, _ = step2_segment_poc._build_semantic_endpoints(context)

    segment_road_ids, segment_cut_infos = step2_segment_poc._refine_segment_roads(
        execution.pair_candidates[0],
        context=context,
        road_endpoints=road_endpoints,
        pruned_road_ids={"r14", "r43", "r32", "r21", "r46", "r62", "r27", "r78", "r89", "r97"},
        trunk_road_ids=("r14", "r43", "r32", "r21"),
        through_rule=execution.strategy.through_rule,
    )

    assert set(segment_road_ids) == {"r14", "r43", "r32", "r21", "r46", "r62"}
    cut_reasons = {(info["road_id"], info["cut_reason"]) for info in segment_cut_infos}
    assert ("r27", "segment_bridge_prune") in cut_reasons
    assert ("r78", "segment_disconnected_component_prune") in cut_reasons
    assert ("r89", "segment_disconnected_component_prune") in cut_reasons
    assert ("r97", "segment_disconnected_component_prune") in cut_reasons


def test_step2_validates_through_collapsed_corridor_candidate(tmp_path: Path) -> None:
    road_path, node_path = _build_through_collapsed_corridor_dataset(tmp_path)
    strategy_path = tmp_path / "step2_strategy.json"
    strategy_path.write_text(
        json.dumps(
            {
                "strategy_id": "S2X",
                "description": "Synthetic Step2 strategy with through enabled by bit7-excluded degree=2.",
                "seed_rule": {"kind_bits_all": [2], "closed_con_in": [2, 3], "grade_eq": 1},
                "terminate_rule": {"kind_bits_all": [2], "closed_con_in": [2, 3], "grade_eq": 1},
                "through_node_rule": {"incident_road_degree_eq": 2, "incident_degree_exclude_formway_bits_any": [7]},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
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

    validated_rows = _read_csv_rows(out_root / "S2X" / "validated_pairs.csv")
    validation_rows = _read_csv_rows(out_root / "S2X" / "pair_validation_table.csv")
    trunk = _load_json(out_root / "S2X" / "trunk_roads.geojson")
    segment_body = _load_json(out_root / "S2X" / "segment_body_roads.geojson")
    residual = _load_json(out_root / "S2X" / "step3_residual_roads.geojson")

    assert [row["pair_id"] for row in validated_rows] == ["S2X:1__3"]
    assert validated_rows[0]["trunk_mode"] == "through_collapsed_corridor"
    assert validation_rows[0]["validated_status"] == "validated"
    assert validation_rows[0]["trunk_mode"] == "through_collapsed_corridor"
    assert validation_rows[0]["counterclockwise_ok"] == "False"
    assert set(trunk["features"][0]["properties"]["road_ids"]) == {"r12", "r23"}
    assert set(segment_body["features"][0]["properties"]["road_ids"]) == {"r12", "r23"}
    assert residual["features"] == []


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


def test_step2_moves_weak_component_to_step3_residual() -> None:
    roads = [
        _road_record("r12", "1", "2"),
        _road_record("r23", "2", "3"),
        _road_record("r34", "3", "4"),
        _road_record("r45", "4", "5"),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("r12", "r23"))
    execution = _minimal_execution([pair_current])

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [
            _validation_result(
                "S2X:1__3",
                "1",
                "3",
                pruned_road_ids=("r12", "r23", "r34", "r45"),
                trunk_road_ids=("r12", "r23"),
                segment_road_ids=("r12", "r23", "r34", "r45"),
            )
        ],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    assert set(current.segment_road_ids) == {"r12", "r23"}
    assert set(current.residual_road_ids) == {"r34", "r45"}
    assert current.branch_cut_road_ids == ()
    component_info = current.support_info["non_trunk_components"][0]
    assert component_info["moved_to_step3_residual"] is True
    assert component_info["decision_reason"] == "weak_rule_residual"


def test_step2_component_with_other_validated_trunk_is_cut_from_segment_body() -> None:
    roads = [
        _road_record("r12", "1", "2"),
        _road_record("r23", "2", "3"),
        _road_record("r34", "3", "4"),
        _road_record("r45", "4", "5"),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("r12", "r23"))
    pair_other = _pair_record("S2X:4__5", "4", "5", ("r45",))
    execution = _minimal_execution([pair_current, pair_other])

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [
            _validation_result(
                "S2X:1__3",
                "1",
                "3",
                pruned_road_ids=("r12", "r23", "r34", "r45"),
                trunk_road_ids=("r12", "r23"),
                segment_road_ids=("r12", "r23", "r34", "r45"),
            ),
            _validation_result(
                "S2X:4__5",
                "4",
                "5",
                pruned_road_ids=("r45",),
                trunk_road_ids=("r45",),
                segment_road_ids=("r45",),
            ),
        ],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = next(item for item in tightened if item.pair_id == "S2X:1__3")
    assert set(current.segment_road_ids) == {"r12", "r23"}
    assert set(current.branch_cut_road_ids) == {"r34", "r45"}
    assert current.residual_road_ids == ()
    component_info = current.support_info["non_trunk_components"][0]
    assert component_info["contains_other_validated_trunk"] is True
    assert component_info["decision_reason"] == "contains_other_validated_trunk"


def test_step2_transition_same_dir_component_stops_expansion_and_moves_to_residual() -> None:
    roads = [
        _road_record("r12", "2", "1"),
        _road_record("r23", "2", "3"),
        _road_record("r24", "2", "4"),
    ]
    directed = {
        "2": (
            step1_pair_poc.TraversalEdge("r12", "2", "1"),
            step1_pair_poc.TraversalEdge("r23", "2", "3"),
            step1_pair_poc.TraversalEdge("r24", "2", "4"),
        )
    }
    context = _minimal_context(roads, directed=directed)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("r12", "r23"))
    execution = _minimal_execution([pair_current])

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [
            _validation_result(
                "S2X:1__3",
                "1",
                "3",
                pruned_road_ids=("r12", "r23", "r24"),
                trunk_road_ids=("r12", "r23"),
                segment_road_ids=("r12", "r23", "r24"),
            )
        ],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    assert current.transition_same_dir_blocked is True
    assert set(current.segment_road_ids) == {"r12", "r23"}
    assert current.residual_road_ids == ("r24",)
    component_info = current.support_info["non_trunk_components"][0]
    assert component_info["blocked_by_transition_same_dir"] is True
    assert component_info["decision_reason"] == "transition_same_dir_block"


def test_step2_transition_mirrored_bidirectional_component_moves_to_residual() -> None:
    roads = [
        _road_record("t_in", "X", "N"),
        _road_record("t_out", "N", "Y"),
        _road_record("c_in", "A", "N"),
        _road_record("c_out", "N", "B"),
    ]
    directed = {
        "X": (step1_pair_poc.TraversalEdge("t_in", "X", "N"),),
        "N": (
            step1_pair_poc.TraversalEdge("t_out", "N", "Y"),
            step1_pair_poc.TraversalEdge("c_out", "N", "B"),
        ),
        "A": (step1_pair_poc.TraversalEdge("c_in", "A", "N"),),
    }
    context = _minimal_context(roads, directed=directed)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:X__Y", "X", "Y", ("t_in", "t_out"))
    execution = _minimal_execution([pair_current])

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [
            _validation_result(
                "S2X:X__Y",
                "X",
                "Y",
                pruned_road_ids=("t_in", "t_out", "c_in", "c_out"),
                trunk_road_ids=("t_in", "t_out"),
                segment_road_ids=("t_in", "t_out", "c_in", "c_out"),
            )
        ],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    assert current.transition_same_dir_blocked is True
    assert set(current.segment_road_ids) == {"t_in", "t_out"}
    assert set(current.residual_road_ids) == {"c_in", "c_out"}
    component_info = current.support_info["non_trunk_components"][0]
    assert component_info["blocked_by_transition_same_dir"] is True
    assert component_info["decision_reason"] == "transition_same_dir_block"
