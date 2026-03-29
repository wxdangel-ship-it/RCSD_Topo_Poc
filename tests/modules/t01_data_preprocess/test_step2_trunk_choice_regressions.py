from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess import step1_pair_poc, step2_segment_poc, step2_trunk_utils


def _road(
    road_id: str,
    snodeid: str,
    enodeid: str,
    *,
    direction: int,
    coords: tuple[tuple[float, float], ...],
    road_kind: int = 2,
) -> step1_pair_poc.RoadRecord:
    return step1_pair_poc.RoadRecord(
        road_id=road_id,
        snodeid=snodeid,
        enodeid=enodeid,
        direction=direction,
        formway=0,
        road_kind=road_kind,
        geometry=LineString(list(coords)),
        raw_properties={"road_kind": road_kind},
    )


def _semantic_node(
    node_id: str,
    *,
    kind: int,
    grade: int,
    cross_flag: int,
) -> step1_pair_poc.SemanticNodeRecord:
    return step1_pair_poc.SemanticNodeRecord(
        semantic_node_id=node_id,
        representative_node_id=node_id,
        member_node_ids=(node_id,),
        raw_kind=kind,
        raw_grade=grade,
        kind_2=kind,
        grade_2=grade,
        closed_con=2,
        geometry=Point(0.0, 0.0),
        raw_properties={"kind": kind, "grade": grade, "cross_flag": cross_flag},
    )


def _context(
    roads: list[step1_pair_poc.RoadRecord],
    *,
    semantic_nodes: list[step1_pair_poc.SemanticNodeRecord] | None = None,
) -> step1_pair_poc.Step1GraphContext:
    return step1_pair_poc.Step1GraphContext(
        physical_nodes={},
        roads={road.road_id: road for road in roads},
        semantic_nodes={
            node.semantic_node_id: node for node in (semantic_nodes or [])
        },
        physical_to_semantic={},
        directed={},
        blocked={},
        orphan_ref_count=0,
        graph_audit_events=[],
    )


def _pair(
    pair_id: str,
    *,
    a_node_id: str,
    b_node_id: str,
    forward_path_node_ids: tuple[str, ...],
    forward_path_road_ids: tuple[str, ...],
    reverse_path_node_ids: tuple[str, ...],
    reverse_path_road_ids: tuple[str, ...],
    through_node_ids: tuple[str, ...] = (),
) -> step1_pair_poc.PairRecord:
    return step1_pair_poc.PairRecord(
        pair_id=pair_id,
        a_node_id=a_node_id,
        b_node_id=b_node_id,
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=forward_path_node_ids,
        forward_path_road_ids=forward_path_road_ids,
        reverse_path_node_ids=reverse_path_node_ids,
        reverse_path_road_ids=reverse_path_road_ids,
        through_node_ids=through_node_ids,
    )


def test_evaluate_trunk_choices_applies_tjunction_vertical_tracking_gate(monkeypatch) -> None:
    pair = _pair(
        "PAIR_DIRECT_BIDIR",
        a_node_id="A",
        b_node_id="B",
        forward_path_node_ids=("A", "B"),
        forward_path_road_ids=("direct",),
        reverse_path_node_ids=("B", "A"),
        reverse_path_road_ids=("direct",),
    )
    roads = [
        _road("direct", "A", "B", direction=1, coords=((0.0, 0.0), (2.0, 0.0))),
        _road("bc", "B", "C", direction=2, coords=((2.0, 0.0), (1.0, 1.0))),
        _road("ca", "C", "A", direction=2, coords=((1.0, 1.0), (0.0, 0.0))),
    ]
    context = _context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}

    def _fake_split(pair, *, candidates, context):
        if not candidates:
            return [], []
        return [], [(candidates[0], {"t_junction_vertical_tracking_blocked": True, "pair_id": pair.pair_id})]

    monkeypatch.setattr(step2_trunk_utils, "_split_tjunction_vertical_tracking_candidates", _fake_split)

    choices, reject_reason, warnings, support_info = step2_segment_poc._evaluate_trunk_choices(
        pair,
        context=context,
        candidate_road_ids={"direct", "bc", "ca"},
        pruned_road_ids={"direct", "bc", "ca"},
        branch_cut_infos=[],
        road_endpoints=road_endpoints,
        through_rule=step1_pair_poc.ThroughRuleSpec(),
        formway_mode="strict",
        left_turn_formway_bit=step2_segment_poc.LEFT_TURN_FORMWAY_BIT,
    )

    assert choices == []
    assert reject_reason == "t_junction_vertical_tracking"
    assert warnings == ()
    assert support_info["t_junction_vertical_tracking_blocked"] is True
    assert support_info["pair_id"] == "PAIR_DIRECT_BIDIR"


def test_evaluate_trunk_choices_keeps_direct_single_road_oneway_pair_with_endpoint_tail() -> None:
    pair = _pair(
        "PAIR_DIRECT_ONEWAY_TAIL",
        a_node_id="A",
        b_node_id="B",
        forward_path_node_ids=("A", "B"),
        forward_path_road_ids=("ab",),
        reverse_path_node_ids=("B", "A"),
        reverse_path_road_ids=("ba",),
    )
    roads = [
        _road("ab", "A", "B", direction=2, coords=((0.0, 0.0), (100.0, 0.0))),
        _road("ba", "B", "A", direction=2, coords=((100.0, 0.0), (100.0, 50.2), (0.0, 49.4))),
    ]
    context = _context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}

    choices, reject_reason, warnings, _ = step2_segment_poc._evaluate_trunk_choices(
        pair,
        context=context,
        candidate_road_ids={"ab", "ba"},
        pruned_road_ids={"ab", "ba"},
        branch_cut_infos=[],
        road_endpoints=road_endpoints,
        through_rule=step1_pair_poc.ThroughRuleSpec(),
        formway_mode="strict",
        left_turn_formway_bit=step2_segment_poc.LEFT_TURN_FORMWAY_BIT,
    )

    assert reject_reason is None
    assert warnings == ()
    assert [choice.candidate.road_ids for choice in choices] == [("ab", "ba")]
    assert choices[0].candidate.max_dual_carriageway_separation_m < 50.0


def test_dual_carriageway_separation_keeps_long_unmatched_tail_blocked() -> None:
    roads = {
        road.road_id: road
        for road in [
            _road("ab", "A", "B", direction=2, coords=((0.0, 0.0), (100.0, 0.0))),
            _road(
                "ba",
                "B",
                "A",
                direction=2,
                coords=((100.0, 0.0), (100.0, 40.0), (0.0, 40.0), (0.0, 60.0)),
            ),
        ]
    }
    forward_path = step2_trunk_utils.DirectedPath(
        node_ids=("A", "B"),
        road_ids=("ab",),
        total_length=100.0,
    )
    reverse_path = step2_trunk_utils.DirectedPath(
        node_ids=("B", "A"),
        road_ids=("ba",),
        total_length=float(roads["ba"].geometry.length),
    )

    separation_m = step2_trunk_utils._dual_carriageway_separation_m(
        forward_path=forward_path,
        reverse_path=reverse_path,
        roads=roads,
    )

    assert separation_m == pytest.approx(60.0)
    assert separation_m > 50.0
