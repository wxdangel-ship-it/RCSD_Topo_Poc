from __future__ import annotations

from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_geojson
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    RuleSpec,
    StrategySpec,
    ThroughRuleSpec,
    build_step1_graph_context,
    run_step1_strategy,
)


def _node_feature(
    node_id: int,
    x: float,
    y: float,
    *,
    grade_2: int = 0,
    kind_2: int = 0,
    closed_con: int = 0,
) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": node_id,
            "kind": 0,
            "grade": 0,
            "kind_2": kind_2,
            "grade_2": grade_2,
            "closed_con": closed_con,
            "mainnodeid": None,
        },
        "geometry": Point(x, y),
    }


def _road_feature(
    road_id: str,
    snodeid: int,
    enodeid: int,
    direction: int,
    coords: list[list[float]],
) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "formway": 0,
        },
        "geometry": LineString(coords),
    }


def _strategy(*, allow_fallback: bool) -> StrategySpec:
    empty_rule = RuleSpec(kind_bits_all=(), kind_bits_any=(), kind_values_in=(), grade_eq=9999, grade_in=(), closed_con_in=())
    return StrategySpec(
        strategy_id="STEP5C",
        description="test",
        seed_rule=empty_rule,
        terminate_rule=empty_rule,
        through_rule=ThroughRuleSpec(
            incident_road_degree_eq=2,
            disallow_seed_terminate_nodes=True,
        ),
        allow_mirrored_one_sided_reverse_confirm_for_force_terminate_nodes=allow_fallback,
        force_seed_node_ids=("1", "3"),
        force_terminate_node_ids=("1", "3"),
    )


def test_step1_reverse_confirm_fallback_is_step5c_opt_in(tmp_path: Path) -> None:
    node_path = tmp_path / "nodes.geojson"
    road_path = tmp_path / "roads.geojson"
    write_geojson(
        node_path,
        [
            _node_feature(1, 0.0, 0.0, grade_2=1, kind_2=4, closed_con=2),
            _node_feature(2, 1.0, 0.0, grade_2=0, kind_2=0, closed_con=0),
            _node_feature(3, 2.0, 0.0, grade_2=1, kind_2=4, closed_con=2),
        ],
    )
    write_geojson(
        road_path,
        [
            _road_feature("r12", 1, 2, 2, [[0.0, 0.0], [1.0, 0.0]]),
            _road_feature("r23", 2, 3, 2, [[1.0, 0.0], [2.0, 0.0]]),
        ],
    )
    context = build_step1_graph_context(road_path=road_path, node_path=node_path)

    no_fallback = run_step1_strategy(context, _strategy(allow_fallback=False))
    assert no_fallback.pair_candidates == []
    assert no_fallback.search_event_counts["reverse_confirm_fail"] == 1

    with_fallback = run_step1_strategy(context, _strategy(allow_fallback=True))
    assert len(with_fallback.pair_candidates) == 1
    pair = with_fallback.pair_candidates[0]
    assert pair.a_node_id == "1"
    assert pair.b_node_id == "3"
    assert pair.forward_path_road_ids == ("r12", "r23")
    assert pair.reverse_path_road_ids == ("r23", "r12")
    assert with_fallback.search_event_counts["reverse_confirm_fallback_mirrored"] == 1
