from __future__ import annotations

import csv
import json
from pathlib import Path

from rcsd_topo_poc.modules.t01_data_preprocess import (
    step1_pair_poc,
    step2_output_utils,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_validation_utils import PairValidationResult


def _write_geojson(path: Path, *, features: list[dict]) -> None:
    payload = {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
        "features": features,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _node(
    node_id: int,
    x: float,
    y: float,
    *,
    kind_2: int,
    grade_2: int = 1,
    kind: int | None = None,
    grade: int | None = None,
    mainnodeid: int | None = None,
) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": node_id,
            "kind": kind_2 if kind is None else kind,
            "grade": grade_2 if grade is None else grade,
            "kind_2": kind_2,
            "grade_2": grade_2,
            "closed_con": 2,
            "mainnodeid": mainnodeid,
        },
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


def _road(road_id: str, snodeid: int, enodeid: int, coords: list[list[float]]) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": 0,
            "formway": 0,
            "road_kind": 0,
        },
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _strategy() -> step1_pair_poc.StrategySpec:
    rule = step1_pair_poc.RuleSpec(kind_bits_all=(), kind_bits_any=(2, 6), grade_eq=1, closed_con_in=(2, 3))
    return step1_pair_poc.StrategySpec(
        strategy_id="S2X",
        description="kind_2=128 audit fixture",
        seed_rule=rule,
        terminate_rule=rule,
        through_rule=step1_pair_poc.ThroughRuleSpec(incident_road_degree_eq=2),
    )


def test_step1_records_kind_2_128_crossing_without_marking_it_as_through(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    _write_geojson(
        node_path,
        features=[
            _node(1, 0.0, 0.0, kind_2=4),
            _node(2, 10.0, 0.0, kind_2=128),
            _node(3, 20.0, 0.0, kind_2=4),
            _node(4, 10.0, 10.0, kind_2=4),
        ],
    )
    _write_geojson(
        road_path,
        features=[
            _road("r12", 1, 2, [[0.0, 0.0], [10.0, 0.0]]),
            _road("r23", 2, 3, [[10.0, 0.0], [20.0, 0.0]]),
            _road("r24", 2, 4, [[10.0, 0.0], [10.0, 10.0]]),
        ],
    )

    context = step1_pair_poc.build_step1_graph_context(road_path=road_path, node_path=node_path)
    execution = step1_pair_poc.run_step1_strategy(context, _strategy())
    pair = next(item for item in execution.pair_candidates if item.pair_id == "S2X:1__3")

    assert pair.through_node_ids == ()
    assert pair.kind_2_128_node_ids == ("2",)
    assert pair.forward_kind_2_128_node_ids == ("2",)
    assert pair.reverse_kind_2_128_node_ids == ("2",)

    result = step1_pair_poc.write_step1_candidate_outputs(
        tmp_path / "out" / "S2X",
        strategy=execution.strategy,
        run_id="test",
        semantic_nodes=context.semantic_nodes,
        physical_nodes=context.physical_nodes,
        physical_to_semantic=context.physical_to_semantic,
        roads=context.roads,
        seed_eval=execution.seed_eval,
        terminate_eval=execution.terminate_eval,
        pairs=execution.pair_candidates,
        search_event_counts=execution.search_event_counts,
        search_event_samples=execution.search_event_samples,
        graph_audit_events=context.graph_audit_events,
        orphan_ref_count=context.orphan_ref_count,
        search_seed_count=len(execution.search_seed_ids),
        through_seed_pruned_count=execution.through_seed_pruned_count,
        debug=False,
    )
    assert result.pair_summary["kind_2_128_semantic_node_count"] == 1
    assert result.pair_summary["kind_2_128_candidate_pair_count"] >= 1

    rows = list(csv.DictReader((tmp_path / "out" / "S2X" / "pair_candidates.csv").open(encoding="utf-8-sig")))
    row = next(item for item in rows if item["pair_id"] == "S2X:1__3")
    assert row["crosses_kind_2_128"] == "True"
    assert row["kind_2_128_node_ids"] == "2"
    assert json.loads(row["support_info"])["kind_2_128_node_ids"] == ["2"]


def test_step1_splits_kind_2_128_mainnode_group_to_physical_raw_kind_nodes(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    _write_geojson(
        node_path,
        features=[
            _node(1, 0.0, 0.0, kind_2=4),
            _node(20, 20.0, 0.0, kind=4, grade=1, kind_2=128, grade_2=1, mainnodeid=20),
            _node(21, 10.0, 0.0, kind=64, grade=1, kind_2=0, grade_2=0, mainnodeid=20),
            _node(22, 10.0, 10.0, kind_2=1),
            _node(3, 30.0, 0.0, kind_2=4),
        ],
    )
    _write_geojson(
        road_path,
        features=[
            _road("r1_21", 1, 21, [[0.0, 0.0], [10.0, 0.0]]),
            _road("r21_20", 21, 20, [[10.0, 0.0], [20.0, 0.0]]),
            _road("r21_22", 21, 22, [[10.0, 0.0], [10.0, 10.0]]),
            _road("r20_3", 20, 3, [[20.0, 0.0], [30.0, 0.0]]),
        ],
    )

    context = step1_pair_poc.build_step1_graph_context(road_path=road_path, node_path=node_path)
    execution = step1_pair_poc.run_step1_strategy(context, _strategy())
    pair_ids = {pair.pair_id for pair in execution.pair_candidates}

    assert context.physical_to_semantic["20"] == "20"
    assert context.physical_to_semantic["21"] == "21"
    assert context.semantic_nodes["20"].kind_2 == 4
    assert context.semantic_nodes["20"].grade_2 == 1
    assert context.semantic_nodes["21"].kind_2 == 64
    assert context.semantic_nodes["21"].grade_2 == 1
    assert "S2X:1__21" in pair_ids
    assert "S2X:1__3" not in pair_ids
    assert any(event["event"] == "complex_kind_2_128_physical_semantics" for event in context.graph_audit_events)


def _validation(
    pair_id: str,
    *,
    validated_status: str,
    reject_reason: str | None = None,
    kind_2_128_node_ids: tuple[str, ...] = (),
) -> PairValidationResult:
    return PairValidationResult(
        pair_id=pair_id,
        a_node_id="1",
        b_node_id="3",
        candidate_status="candidate",
        validated_status=validated_status,
        reject_reason=reject_reason,
        trunk_mode="none",
        trunk_found=validated_status == "validated",
        counterclockwise_ok=validated_status == "validated",
        left_turn_excluded_mode="strict",
        warning_codes=(),
        candidate_channel_road_ids=(),
        pruned_road_ids=(),
        trunk_road_ids=(),
        segment_road_ids=(),
        residual_road_ids=(),
        branch_cut_road_ids=(),
        boundary_terminate_node_ids=(),
        transition_same_dir_blocked=False,
        support_info={
            "crosses_kind_2_128": bool(kind_2_128_node_ids),
            "kind_2_128_node_ids": list(kind_2_128_node_ids),
        },
    )


def test_step2_summary_groups_validation_results_by_kind_2_128_crossing() -> None:
    summary = step2_output_utils._collect_validation_summary(
        [
            _validation("p1", validated_status="validated", kind_2_128_node_ids=("2",)),
            _validation(
                "p2",
                validated_status="rejected",
                reject_reason="dual_carriageway_separation_exceeded",
                kind_2_128_node_ids=("8",),
            ),
            _validation(
                "p4",
                validated_status="rejected",
                reject_reason="trunk_search_budget_exceeded",
                kind_2_128_node_ids=("9",),
            ),
            _validation("p3", validated_status="rejected", reject_reason="no_valid_trunk"),
        ]
    )

    assert summary["kind_2_128_candidate_pair_count"] == 3
    assert summary["kind_2_128_validated_pair_count"] == 1
    assert summary["kind_2_128_rejected_pair_count"] == 2
    assert summary["kind_2_128_dual_carriageway_separation_reject_count"] == 1
    assert summary["trunk_search_budget_exceeded_count"] == 1
    assert summary["kind_2_128_trunk_search_budget_exceeded_count"] == 1
    assert summary["kind_2_128_path_node_hit_count"] == 3

    rows = list(
        step2_output_utils._iter_validation_rows(
            [_validation("p1", validated_status="validated", kind_2_128_node_ids=("2",))]
        )
    )
    assert rows[0]["crosses_kind_2_128"] is True
    assert rows[0]["kind_2_128_node_ids"] == "2"
