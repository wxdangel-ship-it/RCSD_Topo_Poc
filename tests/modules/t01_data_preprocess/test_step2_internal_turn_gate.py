from __future__ import annotations

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t01_data_preprocess import step1_pair_poc, step2_segment_poc


def _road(
    road_id: str,
    snodeid: str,
    enodeid: str,
    *,
    direction: int = 2,
    coords: tuple[tuple[float, float], ...],
    kind: str = "0601",
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
        raw_properties={"kind": kind, "road_kind": road_kind},
    )


def _semantic_node(
    node_id: str,
    *,
    x: float,
    y: float,
    kind_2: int = 4,
    grade_2: int = 2,
    closed_con: int = 2,
) -> step1_pair_poc.SemanticNodeRecord:
    return step1_pair_poc.SemanticNodeRecord(
        semantic_node_id=node_id,
        representative_node_id=node_id,
        member_node_ids=(node_id,),
        raw_kind=kind_2,
        raw_grade=grade_2,
        kind_2=kind_2,
        grade_2=grade_2,
        closed_con=closed_con,
        geometry=Point(x, y),
        raw_properties={"kind": kind_2, "grade": grade_2},
    )


def _context(roads: list[step1_pair_poc.RoadRecord]) -> step1_pair_poc.Step1GraphContext:
    node_xy = {
        "A": (0.0, 0.0),
        "J": (1.0, 0.0),
        "D": (1.0, 1.0),
        "R": (0.0, 1.0),
        "S": (2.0, 0.0),
    }
    return step1_pair_poc.Step1GraphContext(
        physical_nodes={},
        roads={road.road_id: road for road in roads},
        semantic_nodes={
            node_id: _semantic_node(node_id, x=x, y=y)
            for node_id, (x, y) in node_xy.items()
        },
        physical_to_semantic={},
        directed={},
        blocked={},
        orphan_ref_count=0,
        graph_audit_events=[],
    )


def _pair() -> step1_pair_poc.PairRecord:
    return step1_pair_poc.PairRecord(
        pair_id="STEP4:A__D",
        a_node_id="A",
        b_node_id="D",
        strategy_id="STEP4",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "J", "D"),
        forward_path_road_ids=("aj", "jd"),
        reverse_path_node_ids=("D", "R", "A"),
        reverse_path_road_ids=("dr", "ra"),
        through_node_ids=(),
    )


def _evaluate(roads: list[step1_pair_poc.RoadRecord]):
    context = _context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    return step2_segment_poc._evaluate_trunk_choices(
        _pair(),
        context=context,
        candidate_road_ids={road.road_id for road in roads},
        pruned_road_ids={road.road_id for road in roads},
        branch_cut_infos=[],
        road_endpoints=road_endpoints,
        through_rule=step1_pair_poc.ThroughRuleSpec(),
        formway_mode="strict",
        left_turn_formway_bit=step2_segment_poc.LEFT_TURN_FORMWAY_BIT,
    )


def test_internal_turn_gate_rejects_multileg_junction_right_angle_continuation() -> None:
    roads = [
        _road("aj", "A", "J", coords=((0.0, 0.0), (1.0, 0.0))),
        _road("jd", "J", "D", coords=((1.0, 0.0), (1.0, 1.0))),
        _road("dr", "D", "R", coords=((1.0, 1.0), (0.0, 1.0))),
        _road("ra", "R", "A", coords=((0.0, 1.0), (0.0, 0.0))),
        _road("js", "J", "S", coords=((1.0, 0.0), (0.0, -1.0))),
    ]

    choices, reject_reason, warnings, support_info = _evaluate(roads)

    assert choices == []
    assert reject_reason == "internal_turn_angle_conflict"
    assert warnings == ()
    assert support_info["internal_turn_angle_blocked"] is True
    assert support_info["internal_turn_angle_node_id"] == "J"
    assert support_info["internal_turn_angle_incoming_road_id"] == "aj"
    assert support_info["internal_turn_angle_outgoing_road_id"] == "jd"
    assert support_info["internal_turn_angle_deg"] == 90.0
    assert support_info["internal_turn_angle_incident_road_count"] == 3


def test_internal_turn_gate_keeps_degree_two_curved_corridor() -> None:
    roads = [
        _road("aj", "A", "J", coords=((0.0, 0.0), (1.0, 0.0))),
        _road("jd", "J", "D", coords=((1.0, 0.0), (1.0, 1.0))),
        _road("dr", "D", "R", coords=((1.0, 1.0), (0.0, 1.0))),
        _road("ra", "R", "A", coords=((0.0, 1.0), (0.0, 0.0))),
    ]

    choices, reject_reason, warnings, _support_info = _evaluate(roads)

    assert reject_reason is None
    assert warnings == ()
    assert len(choices) == 1
