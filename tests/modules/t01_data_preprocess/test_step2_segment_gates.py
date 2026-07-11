from __future__ import annotations

from tests.modules.t01_data_preprocess.step2_segment_test_support import *  # noqa: F401,F403


def test_tjunction_vertical_tracking_gate_blocks_bidirectional_loop_with_weak_connectors() -> None:
    pair = step1_pair_poc.PairRecord(
        pair_id="PAIR_TJ",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "SUPPORT", "WEAK_1", "WEAK_2", "B"),
        forward_path_road_ids=("r1", "r2", "r3", "r4"),
        reverse_path_node_ids=("B", "WEAK_3", "WEAK_1", "SUPPORT", "A"),
        reverse_path_road_ids=("r5", "r6", "r2", "r1"),
        through_node_ids=("WEAK_2", "WEAK_3"),
    )
    candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(
            node_ids=pair.forward_path_node_ids,
            road_ids=pair.forward_path_road_ids,
            total_length=40.0,
        ),
        reverse_path=step2_segment_poc.DirectedPath(
            node_ids=pair.reverse_path_node_ids,
            road_ids=pair.reverse_path_road_ids,
            total_length=38.0,
        ),
        road_ids=("r1", "r2", "r3", "r4", "r5", "r6"),
        signed_area=100.0,
        total_length=78.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=10.0,
        is_bidirectional_minimal_loop=True,
    )
    context = _minimal_context(
        [],
        semantic_nodes={
            "SUPPORT": _semantic_node_record("SUPPORT", kind_2=2048, grade_2=3, cross_flag=2),
            "WEAK_1": _semantic_node_record("WEAK_1", kind_2=1, grade_2=3, cross_flag=0),
            "WEAK_2": _semantic_node_record("WEAK_2", kind_2=1, grade_2=3, cross_flag=0),
            "WEAK_3": _semantic_node_record("WEAK_3", kind_2=1, grade_2=3, cross_flag=0),
        },
    )

    gate_info = step2_segment_poc._tjunction_vertical_tracking_gate_info(
        pair,
        candidate=candidate,
        context=context,
    )

    assert gate_info is not None
    assert gate_info["t_junction_vertical_tracking_blocked"] is True
    assert gate_info["t_junction_support_anchor_node_ids"] == ["SUPPORT"]
    assert gate_info["t_junction_weak_connector_node_ids"] == ["WEAK_1", "WEAK_2", "WEAK_3"]


def test_tjunction_vertical_tracking_gate_ignores_kind4_support_anchor() -> None:
    pair = step1_pair_poc.PairRecord(
        pair_id="PAIR_TJ_KIND4",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "SUPPORT", "WEAK_1", "WEAK_2", "B"),
        forward_path_road_ids=("r1", "r2", "r3", "r4"),
        reverse_path_node_ids=("B", "WEAK_3", "WEAK_1", "SUPPORT", "A"),
        reverse_path_road_ids=("r5", "r6", "r2", "r1"),
        through_node_ids=("WEAK_2", "WEAK_3"),
    )
    candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(
            node_ids=pair.forward_path_node_ids,
            road_ids=pair.forward_path_road_ids,
            total_length=40.0,
        ),
        reverse_path=step2_segment_poc.DirectedPath(
            node_ids=pair.reverse_path_node_ids,
            road_ids=pair.reverse_path_road_ids,
            total_length=38.0,
        ),
        road_ids=("r1", "r2", "r3", "r4", "r5", "r6"),
        signed_area=100.0,
        total_length=78.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=10.0,
        is_bidirectional_minimal_loop=True,
    )
    context = _minimal_context(
        [],
        semantic_nodes={
            "SUPPORT": _semantic_node_record("SUPPORT", kind_2=4, grade_2=3, cross_flag=2),
            "WEAK_1": _semantic_node_record("WEAK_1", kind_2=1, grade_2=3, cross_flag=0),
            "WEAK_2": _semantic_node_record("WEAK_2", kind_2=1, grade_2=3, cross_flag=0),
            "WEAK_3": _semantic_node_record("WEAK_3", kind_2=1, grade_2=3, cross_flag=0),
        },
    )

    gate_info = step2_segment_poc._tjunction_vertical_tracking_gate_info(
        pair,
        candidate=candidate,
        context=context,
    )

    assert gate_info is None


def test_tjunction_vertical_tracking_gate_keeps_major_corridor_competition() -> None:
    pair = step1_pair_poc.PairRecord(
        pair_id="PAIR_CORRIDOR",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "ANCHOR_1", "ANCHOR_2", "B"),
        forward_path_road_ids=("r1", "r2", "r3"),
        reverse_path_node_ids=("B", "ANCHOR_2", "ANCHOR_1", "A"),
        reverse_path_road_ids=("r4", "r5", "r6"),
        through_node_ids=(),
    )
    candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(
            node_ids=pair.forward_path_node_ids,
            road_ids=pair.forward_path_road_ids,
            total_length=30.0,
        ),
        reverse_path=step2_segment_poc.DirectedPath(
            node_ids=pair.reverse_path_node_ids,
            road_ids=pair.reverse_path_road_ids,
            total_length=28.0,
        ),
        road_ids=("r1", "r2", "r3", "r4", "r5", "r6"),
        signed_area=120.0,
        total_length=58.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=8.0,
        is_bidirectional_minimal_loop=True,
    )
    context = _minimal_context(
        [],
        semantic_nodes={
            "ANCHOR_1": _semantic_node_record("ANCHOR_1", kind_2=4, grade_2=3, cross_flag=2, mainnodeid="ANCHOR_1"),
            "ANCHOR_2": _semantic_node_record("ANCHOR_2", kind_2=4, grade_2=3, cross_flag=3, mainnodeid="ANCHOR_2"),
        },
    )

    gate_info = step2_segment_poc._tjunction_vertical_tracking_gate_info(
        pair,
        candidate=candidate,
        context=context,
    )

    assert gate_info is None


def test_tjunction_vertical_tracking_gate_falls_back_to_raw_kind_for_refreshed_nodes() -> None:
    pair = step1_pair_poc.PairRecord(
        pair_id="PAIR_TJ_REFRESH",
        a_node_id="A",
        b_node_id="B",
        strategy_id="STEP4",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "SUPPORT", "WEAK_1", "WEAK_2", "B"),
        forward_path_road_ids=("r1", "r2", "r3", "r4"),
        reverse_path_node_ids=("B", "WEAK_3", "WEAK_1", "SUPPORT", "A"),
        reverse_path_road_ids=("r5", "r6", "r2", "r1"),
        through_node_ids=("WEAK_2", "WEAK_3"),
    )
    candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(
            node_ids=pair.forward_path_node_ids,
            road_ids=pair.forward_path_road_ids,
            total_length=40.0,
        ),
        reverse_path=step2_segment_poc.DirectedPath(
            node_ids=pair.reverse_path_node_ids,
            road_ids=pair.reverse_path_road_ids,
            total_length=38.0,
        ),
        road_ids=("r1", "r2", "r3", "r4", "r5", "r6"),
        signed_area=100.0,
        total_length=78.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=10.0,
        is_bidirectional_minimal_loop=True,
    )
    context = _minimal_context(
        [],
        semantic_nodes={
            "SUPPORT": _semantic_node_record(
                "SUPPORT",
                kind_2=0,
                raw_kind=2048,
                grade_2=0,
                raw_grade=3,
                cross_flag=2,
            ),
            "WEAK_1": _semantic_node_record(
                "WEAK_1",
                kind_2=0,
                raw_kind=1,
                grade_2=0,
                raw_grade=3,
                cross_flag=0,
            ),
            "WEAK_2": _semantic_node_record(
                "WEAK_2",
                kind_2=0,
                raw_kind=1,
                grade_2=0,
                raw_grade=3,
                cross_flag=0,
            ),
            "WEAK_3": _semantic_node_record(
                "WEAK_3",
                kind_2=0,
                raw_kind=1,
                grade_2=0,
                raw_grade=3,
                cross_flag=0,
            ),
        },
    )

    gate_info = step2_segment_poc._tjunction_vertical_tracking_gate_info(
        pair,
        candidate=candidate,
        context=context,
    )

    assert gate_info is not None
    assert gate_info["t_junction_vertical_tracking_blocked"] is True
    assert gate_info["t_junction_support_anchor_node_ids"] == ["SUPPORT"]
    assert gate_info["t_junction_weak_connector_node_ids"] == ["WEAK_1", "WEAK_2", "WEAK_3"]


def test_bidirectional_side_bypass_gate_blocks_large_mixed_kind_loop() -> None:
    pair = step1_pair_poc.PairRecord(
        pair_id="PAIR_BYPASS",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "HG_1", "HG_2", "WEAK", "MID", "B"),
        forward_path_road_ids=("r1", "r2", "r3", "r4", "r5"),
        reverse_path_node_ids=("B", "HG_3", "HG_4", "WEAK", "TAIL", "A"),
        reverse_path_road_ids=("r6", "r7", "r8", "r9", "r10"),
        through_node_ids=(),
    )
    candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(
            node_ids=pair.forward_path_node_ids,
            road_ids=pair.forward_path_road_ids,
            total_length=60.0,
        ),
        reverse_path=step2_segment_poc.DirectedPath(
            node_ids=pair.reverse_path_node_ids,
            road_ids=pair.reverse_path_road_ids,
            total_length=59.0,
        ),
        road_ids=("r1", "r2", "r3", "r4", "r5", "r6", "r7", "r8", "r9", "r10"),
        signed_area=180.0,
        total_length=119.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=6.0,
        is_bidirectional_minimal_loop=True,
    )
    roads = [
        _road_record("r1", "A", "HG_1", road_kind=3),
        _road_record("r2", "HG_1", "HG_2", road_kind=3),
        _road_record("r3", "HG_2", "WEAK", road_kind=3),
        _road_record("r4", "WEAK", "MID", road_kind=2),
        _road_record("r5", "MID", "B", road_kind=2),
        _road_record("r6", "B", "HG_3", road_kind=2),
        _road_record("r7", "HG_3", "HG_4", road_kind=3),
        _road_record("r8", "HG_4", "WEAK", road_kind=3),
        _road_record("r9", "WEAK", "TAIL", road_kind=2),
        _road_record("r10", "TAIL", "A", road_kind=2),
    ]
    context = _minimal_context(
        roads,
        semantic_nodes={
            "HG_1": _semantic_node_record("HG_1", kind_2=4, grade_2=3, cross_flag=2),
            "HG_2": _semantic_node_record("HG_2", kind_2=4, grade_2=3, cross_flag=2),
            "HG_3": _semantic_node_record("HG_3", kind_2=4, grade_2=3, cross_flag=2),
            "HG_4": _semantic_node_record("HG_4", kind_2=4, grade_2=3, cross_flag=2),
            "WEAK": _semantic_node_record("WEAK", kind_2=1, grade_2=3, cross_flag=0),
            "MID": _semantic_node_record("MID", kind_2=0, grade_2=0),
            "TAIL": _semantic_node_record("TAIL", kind_2=0, grade_2=0),
        },
    )

    gate_info = step2_segment_poc._bidirectional_side_bypass_gate_info(
        pair,
        candidate=candidate,
        context=context,
    )

    assert gate_info is not None
    assert gate_info["bidirectional_side_bypass_blocked"] is True
    assert gate_info["bidirectional_side_bypass_high_grade_node_ids"] == ["HG_1", "HG_2", "HG_3", "HG_4"]
    assert gate_info["bidirectional_side_bypass_weak_connector_node_ids"] == ["WEAK"]


def test_bidirectional_side_bypass_gate_keeps_small_minimal_loop() -> None:
    pair = step1_pair_poc.PairRecord(
        pair_id="PAIR_SMALL_LOOP",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "MID", "B"),
        forward_path_road_ids=("r1", "r2"),
        reverse_path_node_ids=("B", "MID", "A"),
        reverse_path_road_ids=("r3", "r4"),
        through_node_ids=(),
    )
    candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(
            node_ids=pair.forward_path_node_ids,
            road_ids=pair.forward_path_road_ids,
            total_length=20.0,
        ),
        reverse_path=step2_segment_poc.DirectedPath(
            node_ids=pair.reverse_path_node_ids,
            road_ids=pair.reverse_path_road_ids,
            total_length=19.0,
        ),
        road_ids=("r1", "r2", "r3", "r4"),
        signed_area=90.0,
        total_length=39.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=4.0,
        is_bidirectional_minimal_loop=True,
    )
    roads = [
        _road_record("r1", "A", "MID", road_kind=2),
        _road_record("r2", "MID", "B", road_kind=2),
        _road_record("r3", "B", "MID", road_kind=2),
        _road_record("r4", "MID", "A", road_kind=2),
    ]
    context = _minimal_context(
        roads,
        semantic_nodes={
            "MID": _semantic_node_record("MID", kind_2=1, grade_2=1, cross_flag=0),
        },
    )

    gate_info = step2_segment_poc._bidirectional_side_bypass_gate_info(
        pair,
        candidate=candidate,
        context=context,
    )

    assert gate_info is None


def test_minimal_trunk_chain_gate_blocks_lasso_candidate() -> None:
    pair = _pair_record("PAIR_LASSO", "A", "B", ())
    candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(
            node_ids=("A", "P", "Q", "R", "B"),
            road_ids=("r1", "r2", "r3", "r4"),
            total_length=40.0,
        ),
        reverse_path=step2_segment_poc.DirectedPath(
            node_ids=("B", "Q", "S", "A"),
            road_ids=("r5", "r6", "r7"),
            total_length=30.0,
        ),
        road_ids=("r1", "r2", "r3", "r4", "r5", "r6", "r7"),
        signed_area=120.0,
        total_length=70.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=6.0,
    )

    gate_info = step2_segment_poc._minimal_trunk_chain_gate_info(pair, candidate=candidate)

    assert gate_info is not None
    assert gate_info["minimal_trunk_chain_blocked"] is True
    assert gate_info["minimal_trunk_chain_topology_kind"] == "branching"
    assert gate_info["minimal_trunk_chain_branching_node_ids"] == ["Q"]


def test_minimal_trunk_chain_gate_keeps_small_loop_collapsing_to_path() -> None:
    pair = _pair_record("PAIR_SMALL_LOOP_CHAIN", "A", "B", ())
    candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(
            node_ids=("A", "MID", "B"),
            road_ids=("r1", "r2"),
            total_length=20.0,
        ),
        reverse_path=step2_segment_poc.DirectedPath(
            node_ids=("B", "MID", "A"),
            road_ids=("r3", "r4"),
            total_length=19.0,
        ),
        road_ids=("r1", "r2", "r3", "r4"),
        signed_area=90.0,
        total_length=39.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=4.0,
    )

    gate_info = step2_segment_poc._minimal_trunk_chain_gate_info(pair, candidate=candidate)

    assert gate_info is None


def test_bidirectional_minimal_loop_extra_branch_gate_blocks_internal_spur() -> None:
    pair = step1_pair_poc.PairRecord(
        pair_id="PAIR_BIDIR_EXTRA_BRANCH",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "UP", "MERGE", "B"),
        forward_path_road_ids=("r1", "r2", "r3"),
        reverse_path_node_ids=("B", "MERGE", "LOW", "A"),
        reverse_path_road_ids=("r3", "r4", "r5"),
        through_node_ids=(),
    )
    candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(
            node_ids=pair.forward_path_node_ids,
            road_ids=pair.forward_path_road_ids,
            total_length=30.0,
        ),
        reverse_path=step2_segment_poc.DirectedPath(
            node_ids=pair.reverse_path_node_ids,
            road_ids=pair.reverse_path_road_ids,
            total_length=29.0,
        ),
        road_ids=("r1", "r2", "r3", "r4", "r5"),
        signed_area=80.0,
        total_length=59.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=6.0,
        is_bidirectional_minimal_loop=True,
    )

    gate_info = step2_segment_poc._bidirectional_minimal_loop_extra_branch_gate_info(
        pair,
        candidate=candidate,
        candidate_road_ids={"r1", "r2", "r3", "r4", "r5", "spur"},
        road_endpoints={
            "r1": ("A", "UP"),
            "r2": ("UP", "MERGE"),
            "r3": ("MERGE", "B"),
            "r4": ("MERGE", "LOW"),
            "r5": ("LOW", "A"),
            "spur": ("MERGE", "X"),
        },
    )

    assert gate_info is not None
    assert gate_info["bidirectional_minimal_loop_extra_branch_blocked"] is True
    assert gate_info["bidirectional_minimal_loop_internal_node_ids"] == ["LOW", "MERGE", "UP"]
    assert gate_info["bidirectional_minimal_loop_extra_branch_infos"] == [
        {
            "road_id": "spur",
            "from_node_id": "MERGE",
            "to_node_id": "X",
            "touched_internal_node_ids": ["MERGE"],
        }
    ]


def test_evaluate_trunk_choices_prefers_bidirectional_minimal_loop_over_triangle_detour() -> None:
    pair = _pair_record("PAIR_DIRECT_BIDIR", "A", "B", ())
    roads = [
        _road_record("direct", "A", "B", direction=1, coords=((0.0, 0.0), (2.0, 0.0)), road_kind=2),
        _road_record("bc", "B", "C", direction=2, coords=((2.0, 0.0), (1.0, 1.0)), road_kind=2),
        _road_record("ca", "C", "A", direction=2, coords=((1.0, 1.0), (0.0, 0.0)), road_kind=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}

    choices, reject_reason, warnings, _ = step2_segment_poc._evaluate_trunk_choices(
        pair,
        context=context,
        candidate_road_ids={"direct", "bc", "ca"},
        pruned_road_ids={"direct", "bc", "ca"},
        branch_cut_infos=[],
        road_endpoints=road_endpoints,
        through_rule=_minimal_strategy().through_rule,
        formway_mode="strict",
        left_turn_formway_bit=step2_segment_poc.LEFT_TURN_FORMWAY_BIT,
    )

    assert reject_reason is None
    assert warnings == ()
    assert [choice.candidate.road_ids for choice in choices] == [("direct",)]
    assert choices[0].candidate.is_bidirectional_minimal_loop is True


def test_evaluate_trunk_choices_prefers_same_endpoint_direct_bidirectional_over_expanded_loop() -> None:
    pair = _pair_record("PAIR_DIRECT_BIDIR_EXPANDED", "A", "B", ("direct",))
    roads = [
        _road_record("direct", "A", "B", direction=1, coords=((0.0, 0.0), (2.0, 0.0)), road_kind=2),
        _road_record("ac", "A", "C", direction=2, coords=((0.0, 0.0), (1.0, 1.0)), road_kind=2),
        _road_record("cb", "C", "B", direction=1, coords=((1.0, 1.0), (2.0, 0.0)), road_kind=2),
        _road_record("ca", "C", "A", direction=2, coords=((1.0, 1.0), (0.0, 0.0)), road_kind=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}

    choices, reject_reason, warnings, _ = step2_segment_poc._evaluate_trunk_choices(
        pair,
        context=context,
        candidate_road_ids={"direct", "ac", "cb", "ca"},
        pruned_road_ids={"direct", "ac", "cb", "ca"},
        branch_cut_infos=[],
        road_endpoints=road_endpoints,
        through_rule=_minimal_strategy().through_rule,
        formway_mode="strict",
        left_turn_formway_bit=step2_segment_poc.LEFT_TURN_FORMWAY_BIT,
    )

    assert reject_reason is None
    assert warnings == ()
    assert [choice.candidate.road_ids for choice in choices] == [("direct",)]
    assert choices[0].candidate.is_bidirectional_minimal_loop is True


def test_pair_support_seed_candidates_keep_compact_local_bidirectional_loop() -> None:
    pair = step1_pair_poc.PairRecord(
        pair_id="PAIR_SUPPORT_SEED",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "MID", "B"),
        forward_path_road_ids=("f1", "f2"),
        reverse_path_node_ids=("B", "MID", "A"),
        reverse_path_road_ids=("r1", "r2"),
        through_node_ids=(),
    )
    roads = [
        _road_record("f1", "A", "MID", direction=2, coords=((0.0, 0.0), (1.0, -1.0)), road_kind=2),
        _road_record("f2", "MID", "B", direction=2, coords=((1.0, -1.0), (2.0, 0.0)), road_kind=2),
        _road_record("r1", "B", "MID", direction=2, coords=((2.0, 0.0), (1.0, 1.0)), road_kind=2),
        _road_record("r2", "MID", "A", direction=2, coords=((1.0, 1.0), (0.0, 0.0)), road_kind=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}

    candidates = step2_trunk_utils._pair_support_seed_candidates(
        pair,
        roads=context.roads,
        road_endpoints=road_endpoints,
        pruned_road_ids={"f1", "f2", "r1", "r2"},
        left_turn_formway_bit=step2_segment_poc.LEFT_TURN_FORMWAY_BIT,
    )

    assert len(candidates) == 1
    assert candidates[0].road_ids == ("f1", "f2", "r1", "r2")
    assert candidates[0].is_bidirectional_minimal_loop is False


def test_evaluate_trunk_choices_rejects_bidirectional_minimal_loop_lasso_with_internal_extra_branch() -> None:
    pair = step1_pair_poc.PairRecord(
        pair_id="PAIR_BIDIR_BRANCH",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "UP", "MERGE", "B"),
        forward_path_road_ids=("r1", "r2", "r3"),
        reverse_path_node_ids=("B", "MERGE", "LOW", "A"),
        reverse_path_road_ids=("r3", "r4", "r5"),
        through_node_ids=(),
    )
    roads = [
        _road_record("r1", "A", "UP", direction=2, coords=((0.0, 0.0), (1.0, 1.0)), road_kind=2),
        _road_record("r2", "UP", "MERGE", direction=2, coords=((1.0, 1.0), (2.0, 1.0)), road_kind=2),
        _road_record("r3", "MERGE", "B", direction=1, coords=((2.0, 1.0), (3.0, 0.0)), road_kind=2),
        _road_record("r4", "MERGE", "LOW", direction=2, coords=((2.0, 1.0), (1.0, -1.0)), road_kind=2),
        _road_record("r5", "LOW", "A", direction=2, coords=((1.0, -1.0), (0.0, 0.0)), road_kind=2),
        _road_record("spur", "MERGE", "X", direction=2, coords=((2.0, 1.0), (2.0, 2.0)), road_kind=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}

    choices, reject_reason, warnings, support_info = step2_segment_poc._evaluate_trunk_choices(
        pair,
        context=context,
        candidate_road_ids={"r1", "r2", "r3", "r4", "r5", "spur"},
        pruned_road_ids={"r1", "r2", "r3", "r4", "r5", "spur"},
        branch_cut_infos=[],
        road_endpoints=road_endpoints,
        through_rule=_minimal_strategy().through_rule,
        formway_mode="strict",
        left_turn_formway_bit=step2_segment_poc.LEFT_TURN_FORMWAY_BIT,
    )

    assert choices == []
    assert reject_reason == "bidirectional_minimal_loop_lasso"
    assert warnings == ()
    assert support_info["bidirectional_minimal_loop_lasso_blocked"] is True
    assert support_info["bidirectional_minimal_loop_lasso_leaf_node_id"] == "B"
    assert support_info["bidirectional_minimal_loop_lasso_branching_node_ids"] == ["MERGE"]


def test_evaluate_trunk_choices_keeps_counterclockwise_loop_with_branching_internal_node() -> None:
    pair = _pair_record("PAIR_BRANCHING_LOOP", "A", "B", ())
    roads = [
        _road_record("r1", "A", "P", direction=2, coords=((0.0, 0.0), (0.0, -1.0)), road_kind=2),
        _road_record("r2", "P", "Q", direction=2, coords=((0.0, -1.0), (1.0, -1.0)), road_kind=2),
        _road_record("r3", "Q", "B", direction=2, coords=((1.0, -1.0), (2.0, 0.0)), road_kind=2),
        _road_record("r4", "B", "Q", direction=2, coords=((2.0, 0.0), (1.0, -1.0)), road_kind=2),
        _road_record("r5", "Q", "R", direction=2, coords=((1.0, -1.0), (1.0, 1.0)), road_kind=2),
        _road_record("r6", "R", "A", direction=2, coords=((1.0, 1.0), (0.0, 0.0)), road_kind=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}

    choices, reject_reason, warnings, _ = step2_segment_poc._evaluate_trunk_choices(
        pair,
        context=context,
        candidate_road_ids={"r1", "r2", "r3", "r4", "r5", "r6"},
        pruned_road_ids={"r1", "r2", "r3", "r4", "r5", "r6"},
        branch_cut_infos=[],
        road_endpoints=road_endpoints,
        through_rule=_minimal_strategy().through_rule,
        formway_mode="strict",
        left_turn_formway_bit=step2_segment_poc.LEFT_TURN_FORMWAY_BIT,
    )

    assert reject_reason is None
    assert warnings == ()
    assert choices
    assert choices[0].candidate.is_bidirectional_minimal_loop is False
    assert choices[0].candidate.road_ids == ("r1", "r2", "r3", "r4", "r5", "r6")


def test_evaluate_trunk_choices_rejects_mixed_kind_wedge_counterclockwise_loop() -> None:
    pair = _pair_record("PAIR_MIXED_KIND_WEDGE", "A", "B", ())
    roads = [
        _road_record("direct", "A", "B", direction=2, coords=((0.0, 0.0), (0.0, 10.0)), road_kind=3),
        _road_record("detour_1", "B", "MID", direction=2, coords=((0.0, 10.0), (-3.0, 6.0)), road_kind=2),
        _road_record("detour_2", "MID", "A", direction=2, coords=((-3.0, 6.0), (0.0, 0.0)), road_kind=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}

    choices, reject_reason, warnings, support_info = step2_segment_poc._evaluate_trunk_choices(
        pair,
        context=context,
        candidate_road_ids={"direct", "detour_1", "detour_2"},
        pruned_road_ids={"direct", "detour_1", "detour_2"},
        branch_cut_infos=[],
        road_endpoints=road_endpoints,
        through_rule=_minimal_strategy().through_rule,
        formway_mode="strict",
        left_turn_formway_bit=step2_segment_poc.LEFT_TURN_FORMWAY_BIT,
    )

    assert choices == []
    assert reject_reason == "counterclockwise_mixed_kind_wedge"
    assert warnings == ()
    assert support_info["counterclockwise_mixed_kind_wedge_blocked"] is True
    assert support_info["counterclockwise_mixed_kind_wedge_direct_road_id"] == "direct"
    assert support_info["counterclockwise_mixed_kind_wedge_detour_road_ids"] == ["detour_1", "detour_2"]


def test_evaluate_trunk_choices_keeps_all_kind2_three_road_counterclockwise_loop() -> None:
    pair = _pair_record("PAIR_ALL_KIND2_WEDGE", "A", "B", ())
    roads = [
        _road_record("direct", "A", "B", direction=2, coords=((0.0, 0.0), (0.0, 10.0)), road_kind=2),
        _road_record("detour_1", "B", "MID", direction=2, coords=((0.0, 10.0), (-3.0, 6.0)), road_kind=2),
        _road_record("detour_2", "MID", "A", direction=2, coords=((-3.0, 6.0), (0.0, 0.0)), road_kind=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}

    choices, reject_reason, warnings, _ = step2_segment_poc._evaluate_trunk_choices(
        pair,
        context=context,
        candidate_road_ids={"direct", "detour_1", "detour_2"},
        pruned_road_ids={"direct", "detour_1", "detour_2"},
        branch_cut_infos=[],
        road_endpoints=road_endpoints,
        through_rule=_minimal_strategy().through_rule,
        formway_mode="strict",
        left_turn_formway_bit=step2_segment_poc.LEFT_TURN_FORMWAY_BIT,
    )

    assert reject_reason is None
    assert warnings == ()
    assert choices
    assert choices[0].candidate.road_ids == ("detour_1", "detour_2", "direct")
    assert choices[0].candidate.is_bidirectional_minimal_loop is False


def test_bidirectional_side_bypass_gate_blocks_four_road_mixed_loop_with_weak_connector() -> None:
    pair = step1_pair_poc.PairRecord(
        pair_id="PAIR_FOUR_ROAD_BYPASS",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "SUPPORT", "WEAK", "B"),
        forward_path_road_ids=("r1", "r2", "r3"),
        reverse_path_node_ids=("B", "WEAK", "SUPPORT", "A"),
        reverse_path_road_ids=("r4", "r2", "r1"),
        through_node_ids=(),
    )
    candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(
            node_ids=pair.forward_path_node_ids,
            road_ids=pair.forward_path_road_ids,
            total_length=30.0,
        ),
        reverse_path=step2_segment_poc.DirectedPath(
            node_ids=pair.reverse_path_node_ids,
            road_ids=pair.reverse_path_road_ids,
            total_length=29.0,
        ),
        road_ids=("r1", "r2", "r3", "r4"),
        signed_area=80.0,
        total_length=59.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=8.0,
        is_bidirectional_minimal_loop=True,
    )
    roads = [
        _road_record("r1", "A", "SUPPORT", road_kind=3),
        _road_record("r2", "SUPPORT", "WEAK", road_kind=3),
        _road_record("r3", "WEAK", "B", road_kind=2),
        _road_record("r4", "B", "A", road_kind=2),
    ]
    context = _minimal_context(
        roads,
        semantic_nodes={
            "SUPPORT": _semantic_node_record("SUPPORT", kind_2=2048, grade_2=3, cross_flag=2),
            "WEAK": _semantic_node_record("WEAK", kind_2=1, grade_2=3, cross_flag=0),
        },
    )

    gate_info = step2_segment_poc._bidirectional_side_bypass_gate_info(
        pair,
        candidate=candidate,
        context=context,
    )

    assert gate_info is not None
    assert gate_info["bidirectional_side_bypass_blocked"] is True
    assert gate_info["bidirectional_side_bypass_high_grade_node_ids"] == ["SUPPORT"]
    assert gate_info["bidirectional_side_bypass_weak_connector_node_ids"] == ["WEAK"]


def test_minimal_loop_long_branch_gate_blocks_two_road_loop_with_far_endpoint_branch() -> None:
    pair = step1_pair_poc.PairRecord(
        pair_id="PAIR_LONG_BRANCH",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "B"),
        forward_path_road_ids=("main",),
        reverse_path_node_ids=("B", "A"),
        reverse_path_road_ids=("main",),
        through_node_ids=(),
    )
    candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(
            node_ids=pair.forward_path_node_ids,
            road_ids=pair.forward_path_road_ids,
            total_length=40.0,
        ),
        reverse_path=step2_segment_poc.DirectedPath(
            node_ids=pair.reverse_path_node_ids,
            road_ids=pair.reverse_path_road_ids,
            total_length=39.0,
        ),
        road_ids=("main",),
        signed_area=0.0,
        total_length=79.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=0.0,
        is_bidirectional_minimal_loop=True,
    )
    roads = [
        _road_record("main", "A", "B", coords=((0.0, 0.0), (40.0, 0.0)), road_kind=3),
        _road_record("side", "B", "A", coords=((0.0, 6.0), (40.0, 6.0)), road_kind=2),
        _road_record("long_branch", "B", "X", coords=((40.0, 0.0), (115.0, 0.0)), road_kind=2),
        _road_record("short_branch", "A", "Y", coords=((0.0, 0.0), (0.0, 10.0)), road_kind=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}

    gate_info = step2_segment_poc._minimal_loop_long_branch_gate_info(
        pair,
        candidate=candidate,
        candidate_road_ids={"main", "side", "long_branch", "short_branch"},
        pruned_road_ids={"main", "side"},
        branch_cut_infos=[
            {
                "road_id": "long_branch",
                "cut_reason": "branch_backtrack_prune",
                "from_node_id": "B",
                "to_node_id": "X",
            },
            {
                "road_id": "short_branch",
                "cut_reason": "branch_backtrack_prune",
                "from_node_id": "A",
                "to_node_id": "Y",
            },
        ],
        context=context,
        road_endpoints=road_endpoints,
    )

    assert gate_info is not None
    assert gate_info["minimal_loop_long_branch_blocked"] is True
    assert gate_info["minimal_loop_long_branch_infos"][0]["road_id"] == "long_branch"
    assert gate_info["minimal_loop_long_branch_infos"][0]["branch_length_m"] > 50.0


def test_pair_arbitration_rows_and_component_payload_include_strong_anchor_fields() -> None:
    validation = replace(
        _validation_result(
            "PAIR_A_B",
            "A",
            "B",
            pruned_road_ids=("r1",),
            trunk_road_ids=("r1",),
            segment_road_ids=("r1",),
        ),
        single_pair_legal=True,
        arbitration_status="win",
        arbitration_component_id="component_0001",
        arbitration_option_id="PAIR_A_B::opt_01",
    )
    outcome = step2_arbitration.PairArbitrationOutcome(
        selected_options_by_pair_id={},
        decisions=[
            step2_arbitration.PairArbitrationDecision(
                pair_id="PAIR_A_B",
                component_id="component_0001",
                single_pair_legal=True,
                arbitration_status="win",
                endpoint_boundary_penalty=0,
                strong_anchor_win_count=1,
                corridor_naturalness_score=1,
                contested_trunk_coverage_count=2,
                contested_trunk_coverage_ratio=1.0,
                pair_support_expansion_penalty=0,
                internal_endpoint_penalty=0,
                body_connectivity_support=12.5,
                semantic_conflict_penalty=0,
                lose_reason="",
                selected_option_id="PAIR_A_B::opt_01",
            )
        ],
        conflict_records=[],
        components=[
            step2_arbitration.ConflictComponentSummary(
                component_id="component_0001",
                pair_ids=("PAIR_A_B", "PAIR_C_D"),
                contested_road_ids=("r1", "r2"),
                strong_anchor_node_ids=("500588029",),
                exact_solver_used=True,
                fallback_greedy_used=False,
                selected_option_ids=("PAIR_A_B::opt_01",),
            )
        ],
    )

    rows = list(step2_segment_poc._iter_pair_arbitration_rows([validation], outcome))
    payload = step2_segment_poc._pair_conflict_components_payload(outcome)

    assert rows[0]["strong_anchor_win_count"] == 1
    assert rows[0]["contested_trunk_coverage_count"] == 2
    assert rows[0]["pair_support_expansion_penalty"] == 0
    assert payload[0]["strong_anchor_node_ids"] == ["500588029"]
    assert payload[0]["component_size"] == 2
