from __future__ import annotations

from tests.modules.t01_data_preprocess.step2_segment_test_support import *  # noqa: F401,F403


def test_step2_compact_validation_result_for_release_drops_nonessential_payloads() -> None:
    validation = replace(
        _validation_result(
            "S2X:1__3",
            "1",
            "3",
            pruned_road_ids=("r12", "r23", "r34"),
            trunk_road_ids=("r12", "r23"),
            segment_road_ids=("r12", "r23", "r34"),
        ),
        candidate_channel_road_ids=("r12", "r23", "r34"),
        branch_cut_road_ids=("r34",),
        boundary_terminate_node_ids=("T1",),
        support_info={
            "boundary_terminate_node_ids": ["T1"],
            "candidate_channel_road_ids": ["r12", "r23", "r34"],
            "pruned_road_ids": ["r12", "r23", "r34"],
            "forward_path_road_ids": ["r12", "r23"],
            "reverse_path_road_ids": ["r23", "r12"],
            "left_turn_road_ids": [],
            "branch_cut_infos": [{"road_id": "r34", "cut_reason": "hits_other_terminate", "terminate_node_ids": ["T1"]}],
            "segment_body_candidate_road_ids": ["r12", "r23", "r34"],
            "segment_body_candidate_cut_infos": [{"road_id": "r34", "cut_reason": "segment_exclude_formway"}],
            "trunk_signed_area": 1.0,
        },
    )

    compact = step2_segment_poc._compact_validation_result_for_release(
        validation,
        keep_tighten_fields=True,
    )

    assert compact.candidate_channel_road_ids == ()
    assert compact.pruned_road_ids == ("r12", "r23", "r34")
    assert compact.trunk_road_ids == ("r12", "r23")
    assert compact.segment_road_ids == ()
    assert compact.branch_cut_road_ids == ()
    assert compact.boundary_terminate_node_ids == ()
    assert compact.support_info["candidate_channel_road_count"] == 3
    assert compact.support_info["pruned_road_count"] == 3
    assert compact.support_info["segment_body_candidate_road_ids"] == ["r12", "r23", "r34"]
    assert compact.support_info["segment_body_candidate_cut_infos"] == [
        {"road_id": "r34", "cut_reason": "segment_exclude_formway"}
    ]
    assert "forward_path_road_ids" not in compact.support_info
    assert "reverse_path_road_ids" not in compact.support_info


def test_step2_validation_compact_release_tightens_only_validated_subset(monkeypatch) -> None:
    pair_validated = _pair_record("S2X:1__3", "1", "3", ("r12", "r23"))
    pair_rejected = _pair_record("S2X:4__6", "4", "6", ("r45", "r56"))
    execution = _minimal_execution([pair_validated, pair_rejected])
    roads = [
        _road_record("r12", "1", "2"),
        _road_record("r23", "2", "3"),
        _road_record("r45", "4", "5"),
        _road_record("r56", "5", "6"),
    ]
    context = _minimal_context(roads)
    road_endpoints = {
        "r12": ("1", "2"),
        "r23": ("2", "3"),
        "r45": ("4", "5"),
        "r56": ("5", "6"),
    }
    undirected_adjacency = {
        "1": (step1_pair_poc.TraversalEdge("r12", "1", "2"),),
        "2": (
            step1_pair_poc.TraversalEdge("r12", "2", "1"),
            step1_pair_poc.TraversalEdge("r23", "2", "3"),
        ),
        "3": (step1_pair_poc.TraversalEdge("r23", "3", "2"),),
        "4": (step1_pair_poc.TraversalEdge("r45", "4", "5"),),
        "5": (
            step1_pair_poc.TraversalEdge("r45", "5", "4"),
            step1_pair_poc.TraversalEdge("r56", "5", "6"),
        ),
        "6": (step1_pair_poc.TraversalEdge("r56", "6", "5"),),
    }

    trunk_candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(("1", "2", "3"), ("r12", "r23"), 2.0),
        reverse_path=step2_segment_poc.DirectedPath(("3", "2", "1"), ("r23", "r12"), 2.0),
        road_ids=("r12", "r23"),
        signed_area=1.0,
        total_length=4.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=0.0,
    )
    tighten_inputs: list[list[step2_segment_poc.PairValidationResult]] = []

    def _fake_build_candidate_channel(pair, **kwargs):
        if pair.pair_id == pair_validated.pair_id:
            return {"r12", "r23"}, set()
        return {"r45", "r56"}, set()

    def _fake_prune_candidate_channel(pair, **kwargs):
        if pair.pair_id == pair_validated.pair_id:
            return {"r12", "r23"}, [], False
        return {"r45", "r56"}, [], False

    def _fake_evaluate_trunk_choices(pair, **kwargs):
        if pair.pair_id == pair_validated.pair_id:
            return (
                [step2_segment_poc._TrunkEvaluationChoice(trunk_candidate, (), {})],
                None,
                (),
                {},
            )
        return ([], "only_clockwise_loop", (), {})

    def _fake_tighten(validations, **kwargs):
        tighten_inputs.append(list(validations))
        assert len(validations) == 1
        current = validations[0]
        return [
            replace(
                current,
                segment_road_ids=("r12", "r23"),
                residual_road_ids=(),
                support_info={
                    **current.support_info,
                    "branch_cut_infos": [],
                    "non_trunk_components": [],
                    "step3_residual_infos": [],
                    "segment_body_road_ids": ["r12", "r23"],
                    "residual_road_ids": [],
                },
            )
        ]

    monkeypatch.setattr(step2_segment_poc, "_build_candidate_channel", _fake_build_candidate_channel)
    monkeypatch.setattr(step2_segment_poc, "_prune_candidate_channel", _fake_prune_candidate_channel)
    monkeypatch.setattr(step2_segment_poc, "_evaluate_trunk_choices", _fake_evaluate_trunk_choices)
    monkeypatch.setattr(step2_segment_poc, "_collect_internal_boundary_nodes", lambda *args, **kwargs: ())
    monkeypatch.setattr(
        step2_segment_poc,
        "_build_segment_body_candidate_channel",
        lambda *args, **kwargs: {"r12", "r23"},
    )
    monkeypatch.setattr(
        step2_segment_poc,
        "_refine_segment_roads",
        lambda *args, **kwargs: (("r12", "r23"), []),
    )
    monkeypatch.setattr(step2_segment_poc, "_tighten_validated_segment_components", _fake_tighten)

    results = step2_segment_poc._validate_pair_candidates(
        execution,
        context=context,
        road_endpoints=road_endpoints,
        undirected_adjacency=undirected_adjacency,
        formway_mode="strict",
        left_turn_formway_bit=8,
        compact_release_payloads=True,
    )

    assert [item.pair_id for item in results] == ["S2X:1__3", "S2X:4__6"]
    assert len(tighten_inputs) == 1
    tightened_input = tighten_inputs[0][0]
    assert tightened_input.pair_id == "S2X:1__3"
    assert tightened_input.candidate_channel_road_ids == ("r12", "r23")
    assert tightened_input.pruned_road_ids == ("r12", "r23")
    assert tightened_input.trunk_road_ids == ("r12", "r23")
    assert tightened_input.segment_road_ids == ("r12", "r23")

    final_validated = results[0]
    assert final_validated.validated_status == "validated"
    assert final_validated.segment_road_ids == ("r12", "r23")
    assert final_validated.candidate_channel_road_ids == ()
    assert final_validated.pruned_road_ids == ()
    assert final_validated.support_info["segment_body_road_count"] == 2

    final_rejected = results[1]
    assert final_rejected.validated_status == "rejected"
    assert final_rejected.candidate_channel_road_ids == ()
    assert final_rejected.pruned_road_ids == ()
    assert final_rejected.segment_road_ids == ()
    assert final_rejected.support_info["candidate_channel_road_count"] == 2
    assert final_rejected.support_info["pruned_road_count"] == 2


def test_step2_compact_release_keeps_parallel_twin_swap_semantics(monkeypatch) -> None:
    roads = [
        _road_record("f14", "1", "4", coords=((0.0, 0.0), (30.0, 0.0)), direction=2),
        _road_record("r4a", "4", "A", coords=((30.0, 10.0), (20.0, 10.0)), direction=2),
        _road_record("tab", "A", "B", coords=((20.0, 10.0), (10.0, 10.0)), direction=1),
        _road_record("sab", "A", "B", coords=((20.0, 12.0), (10.0, 12.0)), direction=2),
        _road_record("rb1", "B", "1", coords=((10.0, 10.0), (0.0, 10.0)), direction=2),
    ]
    semantic_nodes = {
        "1": _semantic_node_record("1", kind_2=4),
        "4": _semantic_node_record("4", kind_2=4),
        "A": _semantic_node_record("A", kind_2=4),
        "B": _semantic_node_record("B", kind_2=2048, grade_2=3),
    }
    context = _minimal_context(roads, semantic_nodes=semantic_nodes)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    undirected_adjacency = {
        "1": (
            step1_pair_poc.TraversalEdge("f14", "1", "4"),
            step1_pair_poc.TraversalEdge("rb1", "1", "B"),
        ),
        "4": (
            step1_pair_poc.TraversalEdge("f14", "4", "1"),
            step1_pair_poc.TraversalEdge("r4a", "4", "A"),
        ),
        "A": (
            step1_pair_poc.TraversalEdge("r4a", "A", "4"),
            step1_pair_poc.TraversalEdge("tab", "A", "B"),
            step1_pair_poc.TraversalEdge("sab", "A", "B"),
        ),
        "B": (
            step1_pair_poc.TraversalEdge("tab", "B", "A"),
            step1_pair_poc.TraversalEdge("sab", "B", "A"),
            step1_pair_poc.TraversalEdge("rb1", "B", "1"),
        ),
    }
    pair_current = step1_pair_poc.PairRecord(
        pair_id="S2X:1__4",
        a_node_id="1",
        b_node_id="4",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("1", "4"),
        forward_path_road_ids=("f14",),
        reverse_path_node_ids=("4", "A", "B", "1"),
        reverse_path_road_ids=("r4a", "tab", "rb1"),
        through_node_ids=("A", "B"),
    )
    execution = _minimal_execution([pair_current])
    trunk_candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(("1", "4"), ("f14",), 30.0),
        reverse_path=step2_segment_poc.DirectedPath(("4", "A", "B", "1"), ("r4a", "tab", "rb1"), 30.0),
        road_ids=("f14", "r4a", "tab", "rb1"),
        signed_area=1.0,
        total_length=60.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=0.0,
    )

    def _fake_build_candidate_channel(pair, **kwargs):
        assert pair.pair_id == "S2X:1__4"
        return {"f14", "r4a", "tab", "sab", "rb1"}, set()

    def _fake_prune_candidate_channel(pair, **kwargs):
        return {"f14", "r4a", "tab", "sab", "rb1"}, [], False

    def _fake_evaluate_trunk_choices(pair, **kwargs):
        return (
            [step2_segment_poc._TrunkEvaluationChoice(
                trunk_candidate,
                (),
                {
                    "branch_cut_infos": [],
                    "pair_support_road_ids": ["f14", "r4a", "tab", "rb1"],
                    "forward_path_road_ids": ["f14"],
                    "reverse_path_road_ids": ["r4a", "tab", "rb1"],
                },
            )],
            None,
            (),
            {},
        )

    monkeypatch.setattr(step2_segment_poc, "_build_candidate_channel", _fake_build_candidate_channel)
    monkeypatch.setattr(step2_segment_poc, "_prune_candidate_channel", _fake_prune_candidate_channel)
    monkeypatch.setattr(step2_segment_poc, "_evaluate_trunk_choices", _fake_evaluate_trunk_choices)
    monkeypatch.setattr(step2_segment_poc, "_collect_internal_boundary_nodes", lambda *args, **kwargs: ())
    monkeypatch.setattr(
        step2_segment_poc,
        "_build_segment_body_candidate_channel",
        lambda *args, **kwargs: {"f14", "r4a", "tab", "sab", "rb1"},
    )
    monkeypatch.setattr(
        step2_segment_poc,
        "_refine_segment_roads",
        lambda *args, **kwargs: (("f14", "r4a", "tab", "sab", "rb1"), []),
    )

    for compact_release_payloads in (False, True):
        results = step2_segment_poc._validate_pair_candidates(
            execution,
            context=context,
            road_endpoints=road_endpoints,
            undirected_adjacency=undirected_adjacency,
            formway_mode="strict",
            left_turn_formway_bit=8,
            compact_release_payloads=compact_release_payloads,
        )
        current = results[0]
        assert set(current.trunk_road_ids) == {"f14", "r4a", "sab", "rb1"}
        assert set(current.segment_road_ids) == {"f14", "r4a", "sab", "rb1"}
        assert set(current.residual_road_ids) == {"tab"}


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


def test_step2_side_access_distance_gate_moves_far_component_to_residual() -> None:
    roads = [
        _road_record("r12", "1", "2", coords=((0.0, 0.0), (10.0, 0.0))),
        _road_record("r23", "2", "3", coords=((10.0, 0.0), (20.0, 0.0))),
        _road_record("r2a", "2", "A", coords=((10.0, 0.0), (10.0, 80.0)), direction=2),
        _road_record("ra3", "A", "3", coords=((10.0, 80.0), (20.0, 0.0)), direction=2),
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
                pruned_road_ids=("r12", "r23", "r2a", "ra3"),
                trunk_road_ids=("r12", "r23"),
                segment_road_ids=("r12", "r23", "r2a", "ra3"),
            )
        ],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    assert set(current.segment_road_ids) == {"r12", "r23"}
    assert set(current.residual_road_ids) == {"r2a", "ra3"}
    component_info = current.support_info["non_trunk_components"][0]
    assert component_info["decision_reason"] == "side_access_distance_exceeded"
    assert component_info["side_access_gate_passed"] is False
    assert component_info["side_access_distance_m"] > 50.0
    residual_info = current.support_info["step3_residual_infos"][0]
    assert residual_info["side_access_gate_passed"] is False
    assert residual_info["side_access_distance_m"] > 50.0


def test_step2_tighten_trims_other_terminate_roads_before_component_decision() -> None:
    roads = [
        _road_record("t12", "1", "2", coords=((0.0, 0.0), (10.0, 0.0))),
        _road_record("t23", "2", "3", coords=((10.0, 0.0), (20.0, 0.0))),
        _road_record("r2a", "2", "A", coords=((10.0, 0.0), (10.0, 10.0)), direction=2),
        _road_record("rab", "A", "B", coords=((10.0, 10.0), (20.0, 10.0)), direction=2),
        _road_record("rb3", "B", "3", coords=((20.0, 10.0), (20.0, 0.0)), direction=2),
        _road_record("r2t", "2", "T", coords=((10.0, 0.0), (10.0, 20.0)), direction=2),
        _road_record("rtb", "T", "B", coords=((10.0, 20.0), (20.0, 10.0)), direction=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("t12", "t23"))
    execution = _minimal_execution([pair_current], terminate_ids=["T"])
    validation = replace(
        _validation_result(
            "S2X:1__3",
            "1",
            "3",
            pruned_road_ids=("t12", "t23", "r2a", "rab", "rb3", "r2t", "rtb"),
            trunk_road_ids=("t12", "t23"),
            segment_road_ids=("t12", "t23", "r2a", "rab", "rb3", "r2t", "rtb"),
        ),
        support_info={
            "branch_cut_infos": [],
            "segment_body_candidate_road_ids": ["t12", "t23", "r2a", "rab", "rb3", "r2t", "rtb"],
            "segment_body_candidate_cut_infos": [],
        },
    )

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    assert set(current.segment_road_ids) == {"t12", "t23", "r2a", "rab", "rb3"}
    assert set(current.residual_road_ids) == set()
    branch_cut_infos = current.support_info["branch_cut_infos"]
    assert {info["road_id"] for info in branch_cut_infos if info["cut_reason"] == "hits_other_terminate"} == {"r2t", "rtb"}
    component_info = current.support_info["non_trunk_components"][0]
    assert component_info["road_ids"] == ["r2a", "rab", "rb3"]
    assert component_info["decision_reason"] == "segment_body"


def test_step2_tighten_cuts_roads_hitting_other_validated_support_node() -> None:
    roads = [
        _road_record("t12", "1", "2", coords=((0.0, 0.0), (10.0, 0.0))),
        _road_record("t23", "2", "3", coords=((10.0, 0.0), (20.0, 0.0))),
        _road_record("r2a", "2", "A", coords=((10.0, 0.0), (10.0, 10.0)), direction=2),
        _road_record("rab", "A", "B", coords=((10.0, 10.0), (20.0, 10.0)), direction=2),
        _road_record("rb3", "B", "3", coords=((20.0, 10.0), (20.0, 0.0)), direction=2),
        _road_record("bX", "B", "X", coords=((20.0, 10.0), (30.0, 10.0)), direction=2),
        _road_record("xY", "X", "Y", coords=((30.0, 10.0), (40.0, 10.0)), direction=2),
        _road_record("other_t1", "9", "X", coords=((30.0, 0.0), (30.0, 10.0)), direction=2),
        _road_record("other_t2", "X", "11", coords=((30.0, 10.0), (30.0, 20.0)), direction=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("t12", "t23"))
    pair_other = step1_pair_poc.PairRecord(
        pair_id="S2X:9__11",
        a_node_id="9",
        b_node_id="11",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("9", "X", "11"),
        forward_path_road_ids=("other_t1", "other_t2"),
        reverse_path_node_ids=("11", "X", "9"),
        reverse_path_road_ids=("other_t2", "other_t1"),
        through_node_ids=("X",),
    )
    execution = _minimal_execution([pair_current, pair_other])
    validation = replace(
        _validation_result(
            "S2X:1__3",
            "1",
            "3",
            pruned_road_ids=("t12", "t23", "r2a", "rab", "rb3", "bX", "xY"),
            trunk_road_ids=("t12", "t23"),
            segment_road_ids=("t12", "t23", "r2a", "rab", "rb3", "bX", "xY"),
        ),
        support_info={
            "branch_cut_infos": [],
            "segment_body_candidate_road_ids": ["t12", "t23", "r2a", "rab", "rb3", "bX", "xY"],
            "segment_body_candidate_cut_infos": [],
        },
    )
    other_validation = _validation_result(
        "S2X:9__11",
        "9",
        "11",
        pruned_road_ids=("other_t1", "other_t2"),
        trunk_road_ids=("other_t1", "other_t2"),
        segment_road_ids=("other_t1", "other_t2"),
    )

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation, other_validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = next(item for item in tightened if item.pair_id == "S2X:1__3")
    assert set(current.segment_road_ids) == {"t12", "t23", "r2a", "rab", "rb3"}
    assert set(current.residual_road_ids) == set()
    branch_cut_infos = current.support_info["branch_cut_infos"]
    assert {info["road_id"] for info in branch_cut_infos if info["cut_reason"] == "hits_other_validated_support_node"} == {"bX", "xY"}
    component_info = current.support_info["non_trunk_components"][0]
    assert component_info["road_ids"] == ["r2a", "rab", "rb3"]
    assert component_info["attachment_node_ids"] == ["2", "3"]
    assert component_info["decision_reason"] == "segment_body"


def test_step2_side_access_distance_gate_excludes_near_component_when_trunk_far_end_is_long() -> None:
    roads = [
        _road_record("r12", "1", "2", coords=((0.0, 0.0), (100.0, 0.0))),
        _road_record("r23", "2", "3", coords=((100.0, 0.0), (200.0, 0.0))),
        _road_record("r2a", "2", "A", coords=((100.0, 0.0), (100.0, 40.0))),
        _road_record("rab", "A", "B", coords=((100.0, 40.0), (120.0, 40.0))),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("r12", "r23"))
    execution = _minimal_execution([pair_current])
    validation = replace(
        _validation_result(
            "S2X:1__3",
            "1",
            "3",
            pruned_road_ids=("r12", "r23", "r2a", "rab"),
            trunk_road_ids=("r12", "r23"),
            segment_road_ids=("r12", "r23", "r2a", "rab"),
        ),
        support_info={
            "branch_cut_infos": [],
            "segment_body_candidate_road_ids": ["r12", "r23", "r2a", "rab"],
            "segment_body_candidate_cut_infos": [],
        },
    )

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    assert set(current.segment_road_ids) == {"r12", "r23"}
    assert set(current.residual_road_ids) == {"r2a", "rab"}
    component_info = current.support_info["non_trunk_components"][0]
    assert component_info["attachment_node_ids"] == ["2"]
    assert component_info["side_access_metric"] == "component_to_trunk_sampled"
    assert component_info["decision_reason"] == "side_access_attachment_insufficient"
    assert component_info["side_access_gate_passed"] is False
    assert component_info["side_access_distance_m"] <= 50.0


def test_step2_side_access_distance_gate_keeps_two_attachment_side_corridor() -> None:
    roads = [
        _road_record("r12", "1", "2", coords=((0.0, 0.0), (100.0, 0.0))),
        _road_record("r23", "2", "3", coords=((100.0, 0.0), (200.0, 0.0))),
        _road_record("r2a", "2", "A", coords=((100.0, 0.0), (100.0, 40.0)), direction=2),
        _road_record("rab", "A", "B", coords=((100.0, 40.0), (200.0, 40.0)), direction=2),
        _road_record("rb3", "B", "3", coords=((200.0, 40.0), (200.0, 0.0)), direction=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("r12", "r23"))
    execution = _minimal_execution([pair_current])
    validation = replace(
        _validation_result(
            "S2X:1__3",
            "1",
            "3",
            pruned_road_ids=("r12", "r23", "r2a", "rab", "rb3"),
            trunk_road_ids=("r12", "r23"),
            segment_road_ids=("r12", "r23", "r2a", "rab", "rb3"),
        ),
        support_info={
            "branch_cut_infos": [],
            "segment_body_candidate_road_ids": ["r12", "r23", "r2a", "rab", "rb3"],
            "segment_body_candidate_cut_infos": [],
        },
    )

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    assert set(current.segment_road_ids) == {"r12", "r23", "r2a", "rab", "rb3"}
    assert current.residual_road_ids == ()
    component_info = current.support_info["non_trunk_components"][0]
    assert component_info["attachment_node_ids"] == ["2", "3"]
    assert component_info["side_access_metric"] == "component_to_trunk_sampled"
    assert component_info["decision_reason"] == "segment_body"
    assert component_info["side_access_gate_passed"] is True
    assert component_info["side_access_distance_m"] <= 50.0


def test_step2_keeps_one_way_parallel_corridor_as_segment_body() -> None:
    roads = [
        _road_record("t12", "1", "2", coords=((0.0, 0.0), (10.0, 0.0))),
        _road_record("t23", "2", "3", coords=((10.0, 0.0), (20.0, 0.0))),
        _road_record("r2a", "2", "A", coords=((10.0, 0.0), (10.0, 10.0)), direction=2),
        _road_record("rab", "A", "B", coords=((10.0, 10.0), (20.0, 10.0)), direction=2),
        _road_record("rb3", "B", "3", coords=((20.0, 10.0), (20.0, 0.0)), direction=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("t12", "t23"))
    execution = _minimal_execution([pair_current])
    validation = replace(
        _validation_result(
            "S2X:1__3",
            "1",
            "3",
            pruned_road_ids=("t12", "t23", "r2a", "rab", "rb3"),
            trunk_road_ids=("t12", "t23"),
            segment_road_ids=("t12", "t23", "r2a", "rab", "rb3"),
        ),
        support_info={
            "branch_cut_infos": [],
            "segment_body_candidate_road_ids": ["t12", "t23", "r2a", "rab", "rb3"],
            "segment_body_candidate_cut_infos": [],
        },
    )

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    component_info = current.support_info["non_trunk_components"][0]
    assert set(current.segment_road_ids) == {"t12", "t23", "r2a", "rab", "rb3"}
    assert component_info["parallel_corridor_directionality"] == "one_way_parallel"
    assert component_info["parallel_corridor_directions"] == ["2->3"]
    assert component_info["decision_reason"] == "segment_body"


def test_step2_moves_same_endpoint_one_way_parallel_closure_to_residual() -> None:
    roads = [
        _road_record("t13", "1", "3", coords=((0.0, 0.0), (20.0, 0.0)), direction=1),
        _road_record("s31", "3", "1", coords=((20.0, 10.0), (0.0, 10.0)), direction=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("t13",))
    execution = _minimal_execution([pair_current])
    validation = replace(
        _validation_result(
            "S2X:1__3",
            "1",
            "3",
            pruned_road_ids=("t13", "s31"),
            trunk_road_ids=("t13",),
            segment_road_ids=("t13", "s31"),
        ),
        support_info={
            "branch_cut_infos": [],
            "bidirectional_minimal_loop": True,
            "segment_body_candidate_road_ids": ["t13", "s31"],
            "segment_body_candidate_cut_infos": [],
        },
    )

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    component_info = current.support_info["non_trunk_components"][0]
    assert set(current.segment_road_ids) == {"t13"}
    assert set(current.residual_road_ids) == {"s31"}
    assert component_info["attachment_node_ids"] == ["1", "3"]
    assert component_info["parallel_corridor_directionality"] == "one_way_parallel"
    assert component_info["decision_reason"] == "same_endpoint_parallel_closure"


def test_step2_moves_side_corridor_with_bidirectional_connector_to_residual() -> None:
    roads = [
        _road_record("t12", "1", "2", coords=((0.0, 0.0), (10.0, 0.0))),
        _road_record("t23", "2", "3", coords=((10.0, 0.0), (20.0, 0.0))),
        _road_record("r2a", "2", "A", coords=((10.0, 0.0), (10.0, 10.0)), direction=2),
        _road_record("rab", "A", "B", coords=((10.0, 10.0), (20.0, 10.0)), direction=0),
        _road_record("rb3", "B", "3", coords=((20.0, 10.0), (20.0, 0.0)), direction=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("t12", "t23"))
    execution = _minimal_execution([pair_current])
    validation = replace(
        _validation_result(
            "S2X:1__3",
            "1",
            "3",
            pruned_road_ids=("t12", "t23", "r2a", "rab", "rb3"),
            trunk_road_ids=("t12", "t23"),
            segment_road_ids=("t12", "t23", "r2a", "rab", "rb3"),
        ),
        support_info={
            "branch_cut_infos": [],
            "segment_body_candidate_road_ids": ["t12", "t23", "r2a", "rab", "rb3"],
            "segment_body_candidate_cut_infos": [],
        },
    )

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    component_info = current.support_info["non_trunk_components"][0]
    assert set(current.segment_road_ids) == {"t12", "t23"}
    assert set(current.residual_road_ids) == {"r2a", "rab", "rb3"}
    assert component_info["component_directionality"] == "mixed_with_bidirectional"
    assert component_info["bidirectional_road_ids"] == ["rab"]
    assert component_info["parallel_corridor_directionality"] == "one_way_parallel"
    assert component_info["decision_reason"] == "contains_bidirectional_side_road"


def test_step2_moves_one_way_parallel_corridor_attached_to_internal_t_support_nodes_to_residual() -> None:
    roads = [
        _road_record("t1", "1", "T1", coords=((0.0, 0.0), (10.0, 0.0))),
        _road_record("t2", "T1", "T2", coords=((10.0, 0.0), (20.0, 0.0))),
        _road_record("t3", "T2", "3", coords=((20.0, 0.0), (30.0, 0.0))),
        _road_record("r1", "T1", "A", coords=((10.0, 0.0), (10.0, 10.0)), direction=2),
        _road_record("r2", "A", "B", coords=((10.0, 10.0), (20.0, 10.0)), direction=2),
        _road_record("r3", "B", "T2", coords=((20.0, 10.0), (20.0, 0.0)), direction=2),
    ]
    semantic_nodes = {
        "1": _semantic_node_record("1", kind_2=4),
        "T1": _semantic_node_record("T1", kind_2=2048, grade_2=2),
        "T2": _semantic_node_record("T2", kind_2=2048, grade_2=3),
        "3": _semantic_node_record("3", kind_2=4),
        "A": _semantic_node_record("A", kind_2=0, grade_2=0),
        "B": _semantic_node_record("B", kind_2=0, grade_2=0),
    }
    context = _minimal_context(roads, semantic_nodes=semantic_nodes)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = step1_pair_poc.PairRecord(
        pair_id="S2X:1__3",
        a_node_id="1",
        b_node_id="3",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("1", "T1", "T2", "3"),
        forward_path_road_ids=("t1", "t2", "t3"),
        reverse_path_node_ids=("3", "T2", "T1", "1"),
        reverse_path_road_ids=("t3", "t2", "t1"),
        through_node_ids=("T1", "T2"),
    )
    execution = _minimal_execution([pair_current])
    validation = replace(
        _validation_result(
            "S2X:1__3",
            "1",
            "3",
            pruned_road_ids=("t1", "t2", "t3", "r1", "r2", "r3"),
            trunk_road_ids=("t1", "t2", "t3"),
            segment_road_ids=("t1", "t2", "t3", "r1", "r2", "r3"),
        ),
        support_info={
            "branch_cut_infos": [],
            "segment_body_candidate_road_ids": ["t1", "t2", "t3", "r1", "r2", "r3"],
            "segment_body_candidate_cut_infos": [],
        },
    )

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    component_info = current.support_info["non_trunk_components"][0]
    assert set(current.segment_road_ids) == {"t1", "t2", "t3"}
    assert set(current.residual_road_ids) == {"r1", "r2", "r3"}
    assert component_info["attachment_node_ids"] == ["T1", "T2"]
    assert component_info["internal_support_attachment_node_ids"] == ["T1", "T2"]
    assert component_info["internal_t_support_attachment_node_ids"] == ["T1", "T2"]
    assert component_info["attachment_flow_status"] == "single_departure_return"
    assert component_info["attachment_direction_labels"] == ["T1:out", "T2:in"]
    assert component_info["parallel_corridor_directionality"] == "one_way_parallel"
    assert component_info["decision_reason"] == "internal_support_one_way_parallel"


def test_step2_swaps_internal_one_way_parallel_twin_into_trunk() -> None:
    roads = [
        _road_record("f14", "1", "4", coords=((0.0, 0.0), (30.0, 0.0)), direction=2),
        _road_record("r4a", "4", "A", coords=((30.0, 10.0), (20.0, 10.0)), direction=2),
        _road_record("tab", "A", "B", coords=((20.0, 10.0), (10.0, 10.0)), direction=1),
        _road_record("sab", "A", "B", coords=((20.0, 12.0), (10.0, 12.0)), direction=2),
        _road_record("rb1", "B", "1", coords=((10.0, 10.0), (0.0, 10.0)), direction=2),
    ]
    semantic_nodes = {
        "1": _semantic_node_record("1", kind_2=4),
        "4": _semantic_node_record("4", kind_2=4),
        "A": _semantic_node_record("A", kind_2=4),
        "B": _semantic_node_record("B", kind_2=2048, grade_2=3),
    }
    context = _minimal_context(roads, semantic_nodes=semantic_nodes)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = step1_pair_poc.PairRecord(
        pair_id="S2X:1__4",
        a_node_id="1",
        b_node_id="4",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("1", "4"),
        forward_path_road_ids=("f14",),
        reverse_path_node_ids=("4", "A", "B", "1"),
        reverse_path_road_ids=("r4a", "tab", "rb1"),
        through_node_ids=("A", "B"),
    )
    execution = _minimal_execution([pair_current])
    validation = replace(
        _validation_result(
            "S2X:1__4",
            "1",
            "4",
            pruned_road_ids=("f14", "r4a", "tab", "sab", "rb1"),
            trunk_road_ids=("f14", "r4a", "tab", "rb1"),
            segment_road_ids=("f14", "r4a", "tab", "sab", "rb1"),
        ),
        support_info={
            "branch_cut_infos": [],
            "pair_support_road_ids": ["f14", "r4a", "tab", "rb1"],
            "forward_path_road_ids": ["f14"],
            "reverse_path_road_ids": ["r4a", "tab", "rb1"],
            "segment_body_candidate_road_ids": ["f14", "r4a", "tab", "sab", "rb1"],
            "segment_body_candidate_cut_infos": [],
        },
    )

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    assert set(current.trunk_road_ids) == {"f14", "r4a", "sab", "rb1"}
    assert set(current.segment_road_ids) == {"f14", "r4a", "sab", "rb1"}
    assert set(current.residual_road_ids) == {"tab"}
    assert current.support_info["forward_path_road_ids"] == ["f14"]
    assert current.support_info["reverse_path_road_ids"] == ["r4a", "sab", "rb1"]
    assert current.support_info["pair_support_road_ids"] == ["f14", "r4a", "sab", "rb1"]
    assert current.support_info["internal_parallel_trunk_swap_infos"] == [
        {
            "decision_reason": "internal_support_parallel_twin_swap",
            "pair_id": "S2X:1__4",
            "attachment_node_ids": ["A", "B"],
            "replaced_trunk_road_id": "tab",
            "promoted_parallel_road_id": "sab",
        }
    ]
    component_info = current.support_info["non_trunk_components"][0]
    assert component_info["road_ids"] == ["tab"]
    assert component_info["attachment_node_ids"] == ["A", "B"]
    assert component_info["decision_reason"] == "contains_bidirectional_side_road"


def test_step2_keeps_braided_one_way_single_side_bypass_as_segment_body() -> None:
    roads = [
        _road_record("t12", "1", "2", coords=((0.0, 0.0), (10.0, 0.0))),
        _road_record("t23", "2", "3", coords=((10.0, 0.0), (20.0, 0.0))),
        _road_record("r2a", "2", "A", coords=((10.0, 0.0), (10.0, 8.0)), direction=2),
        _road_record("ra3", "A", "3", coords=((10.0, 8.0), (20.0, 8.0)), direction=2),
        _road_record("r2c", "2", "C", coords=((10.0, 0.0), (10.0, 14.0)), direction=2),
        _road_record("rc3", "C", "3", coords=((10.0, 14.0), (20.0, 14.0)), direction=2),
        _road_record("ac", "A", "C", coords=((15.0, 8.0), (15.0, 14.0)), direction=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("t12", "t23"))
    execution = _minimal_execution([pair_current])
    validation = replace(
        _validation_result(
            "S2X:1__3",
            "1",
            "3",
            pruned_road_ids=("t12", "t23", "r2a", "ra3", "r2c", "rc3", "ac"),
            trunk_road_ids=("t12", "t23"),
            segment_road_ids=("t12", "t23", "r2a", "ra3", "r2c", "rc3", "ac"),
        ),
        support_info={
            "branch_cut_infos": [],
            "segment_body_candidate_road_ids": ["t12", "t23", "r2a", "ra3", "r2c", "rc3", "ac"],
            "segment_body_candidate_cut_infos": [],
        },
    )

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    component_info = current.support_info["non_trunk_components"][0]
    assert set(current.segment_road_ids) == {"t12", "t23", "r2a", "ra3", "r2c", "rc3", "ac"}
    assert current.residual_road_ids == ()
    assert component_info["attachment_node_ids"] == ["2", "3"]
    assert component_info["attachment_flow_status"] == "single_departure_return"
    assert component_info["attachment_direction_labels"] == ["2:out", "3:in"]
    assert component_info["decision_reason"] == "segment_body"


def test_step2_moves_multi_attachment_internal_network_to_residual() -> None:
    roads = [
        _road_record("t12", "1", "2", coords=((0.0, 0.0), (10.0, 0.0))),
        _road_record("t23", "2", "3", coords=((10.0, 0.0), (20.0, 0.0))),
        _road_record("t34", "3", "4", coords=((20.0, 0.0), (30.0, 0.0))),
        _road_record("r2x", "2", "X", coords=((10.0, 0.0), (15.0, 10.0)), direction=2),
        _road_record("rx3", "X", "3", coords=((15.0, 10.0), (20.0, 0.0)), direction=2),
        _road_record("rx4", "X", "4", coords=((15.0, 10.0), (30.0, 0.0)), direction=2),
    ]
    semantic_nodes = {
        "1": _semantic_node_record("1", kind_2=4),
        "2": _semantic_node_record("2", kind_2=2048, grade_2=3),
        "3": _semantic_node_record("3", kind_2=2048, grade_2=3),
        "4": _semantic_node_record("4", kind_2=2048, grade_2=3),
        "X": _semantic_node_record("X", kind_2=0, grade_2=0),
    }
    context = _minimal_context(roads, semantic_nodes=semantic_nodes)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = step1_pair_poc.PairRecord(
        pair_id="S2X:1__4",
        a_node_id="1",
        b_node_id="4",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("1", "2", "3", "4"),
        forward_path_road_ids=("t12", "t23", "t34"),
        reverse_path_node_ids=("4", "3", "2", "1"),
        reverse_path_road_ids=("t34", "t23", "t12"),
        through_node_ids=("2", "3"),
    )
    execution = _minimal_execution([pair_current])
    validation = replace(
        _validation_result(
            "S2X:1__4",
            "1",
            "4",
            pruned_road_ids=("t12", "t23", "t34", "r2x", "rx3", "rx4"),
            trunk_road_ids=("t12", "t23", "t34"),
            segment_road_ids=("t12", "t23", "t34", "r2x", "rx3", "rx4"),
        ),
        support_info={
            "branch_cut_infos": [],
            "segment_body_candidate_road_ids": ["t12", "t23", "t34", "r2x", "rx3", "rx4"],
            "segment_body_candidate_cut_infos": [],
        },
    )

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    component_info = current.support_info["non_trunk_components"][0]
    assert set(current.segment_road_ids) == {"t12", "t23", "t34"}
    assert set(current.residual_road_ids) == {"r2x", "rx3", "rx4"}
    assert component_info["attachment_node_ids"] == ["2", "3", "4"]
    assert component_info["internal_support_attachment_node_ids"] == ["2", "3"]
    assert component_info["attachment_flow_status"] == "single_side_attachment_flow_not_two_attachments"
    assert component_info["attachment_direction_labels"] == ["2:out", "3:in", "4:in"]
    assert component_info["decision_reason"] == "single_side_attachment_flow_not_two_attachments"


def test_step2_moves_bidirectional_parallel_corridor_to_residual() -> None:
    roads = [
        _road_record("t12", "1", "2", coords=((0.0, 0.0), (10.0, 0.0))),
        _road_record("t23", "2", "3", coords=((10.0, 0.0), (20.0, 0.0))),
        _road_record("r2a", "2", "A", coords=((10.0, 0.0), (10.0, 10.0)), direction=2),
        _road_record("ra3", "A", "3", coords=((10.0, 10.0), (20.0, 10.0)), direction=2),
        _road_record("r3b", "3", "B", coords=((20.0, 0.0), (20.0, 15.0)), direction=2),
        _road_record("rb2", "B", "2", coords=((20.0, 15.0), (10.0, 15.0)), direction=2),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("t12", "t23"))
    execution = _minimal_execution([pair_current])
    validation = replace(
        _validation_result(
            "S2X:1__3",
            "1",
            "3",
            pruned_road_ids=("t12", "t23", "r2a", "ra3", "r3b", "rb2"),
            trunk_road_ids=("t12", "t23"),
            segment_road_ids=("t12", "t23", "r2a", "ra3", "r3b", "rb2"),
        ),
        support_info={
            "branch_cut_infos": [],
            "segment_body_candidate_road_ids": ["t12", "t23", "r2a", "ra3", "r3b", "rb2"],
            "segment_body_candidate_cut_infos": [],
        },
    )

    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    current = tightened[0]
    component_info = current.support_info["non_trunk_components"][0]
    assert set(current.segment_road_ids) == {"t12", "t23"}
    assert set(current.residual_road_ids) == {"r2a", "ra3", "r3b", "rb2"}
    assert component_info["parallel_corridor_directionality"] == "bidirectional_parallel"
    assert component_info["parallel_corridor_directions"] == ["2->3", "3->2"]
    assert component_info["decision_reason"] == "bidirectional_parallel_corridor"


def test_step2_tighten_reuses_precomputed_segment_candidates(monkeypatch) -> None:
    roads = [
        _road_record("r12", "1", "2"),
        _road_record("r23", "2", "3"),
        _road_record("r34", "3", "4"),
    ]
    context = _minimal_context(roads)
    road_endpoints = {road.road_id: (road.snodeid, road.enodeid) for road in roads}
    pair_current = _pair_record("S2X:1__3", "1", "3", ("r12", "r23"))
    execution = _minimal_execution([pair_current])
    validation = replace(
        _validation_result(
            "S2X:1__3",
            "1",
            "3",
            pruned_road_ids=("r12", "r23", "r34"),
            trunk_road_ids=("r12", "r23"),
            segment_road_ids=("r12", "r23", "r34"),
        ),
        support_info={
            "branch_cut_infos": [],
            "segment_body_candidate_road_ids": ["r12", "r23", "r34"],
            "segment_body_candidate_cut_infos": [],
        },
    )

    def _fail_refine(*args, **kwargs):
        raise AssertionError("_refine_segment_roads should not be recomputed when support_info already has candidates")

    monkeypatch.setattr(step2_segment_poc, "_refine_segment_roads", _fail_refine)
    tightened = step2_segment_poc._tighten_validated_segment_components(
        [validation],
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )

    assert tightened[0].segment_road_ids == ("r12", "r23")
    assert tightened[0].residual_road_ids == ("r34",)
    component_info = tightened[0].support_info["non_trunk_components"][0]
    assert component_info["decision_reason"] == "side_access_attachment_insufficient"


def test_step2_build_filtered_directed_adjacency_uses_allowed_road_subset() -> None:
    roads = {
        "r12": _road_record("r12", "1", "2"),
        "r23": _road_record("r23", "2", "3"),
        "r34": _road_record("r34", "3", "4"),
    }
    roads["r23"] = replace(roads["r23"], direction=2)
    roads["r34"] = replace(roads["r34"], direction=3)
    road_endpoints = {
        "r12": ("1", "2"),
        "r23": ("2", "3"),
        "r34": ("3", "4"),
    }

    adjacency = step2_segment_poc._build_filtered_directed_adjacency(
        roads,
        road_endpoints=road_endpoints,
        allowed_road_ids={"r12", "r23", "r34"},
        exclude_left_turn=False,
        left_turn_formway_bit=8,
    )

    assert [edge.road_id for edge in adjacency["1"]] == ["r12"]
    assert [edge.road_id for edge in adjacency["2"]] == ["r12", "r23"]
    assert "3" not in adjacency
    assert [edge.road_id for edge in adjacency["4"]] == ["r34"]


def test_step2_build_filtered_directed_adjacency_excludes_formway_bits_any() -> None:
    roads = {
        "r12": _road_record("r12", "1", "2"),
        "r23": replace(
            _road_record("r23", "2", "3", direction=2),
            formway=128,
            raw_properties={"road_kind": 0, "formway": 128},
        ),
        "r34": _road_record("r34", "3", "4"),
    }
    road_endpoints = {
        "r12": ("1", "2"),
        "r23": ("2", "3"),
        "r34": ("3", "4"),
    }

    adjacency = step2_segment_poc._build_filtered_directed_adjacency(
        roads,
        road_endpoints=road_endpoints,
        allowed_road_ids={"r12", "r23", "r34"},
        exclude_left_turn=False,
        left_turn_formway_bit=8,
        exclude_formway_bits_any=(7,),
    )

    assert [edge.road_id for edge in adjacency["1"]] == ["r12"]
    assert [edge.road_id for edge in adjacency["2"]] == ["r12"]
    assert [edge.road_id for edge in adjacency["3"]] == ["r34"]
    assert [edge.road_id for edge in adjacency["4"]] == ["r34"]


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
    assert set(current.branch_cut_road_ids) == {"r45"}
    assert set(current.residual_road_ids) == {"r34"}
    component_info = current.support_info["non_trunk_components"][0]
    assert component_info["contains_other_validated_trunk"] is False
    assert component_info["decision_reason"] == "weak_rule_residual"


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


def test_step2_segment_poc_emits_substage_progress_and_can_drop_validation_details(
    tmp_path: Path,
    monkeypatch,
) -> None:
    out_root = tmp_path / "step2_run"
    strategy = _minimal_strategy("S2X")
    context = _minimal_context([_road_record("r1", "A", "B")])
    execution = replace(
        _minimal_execution(
            [_pair_record("PAIR_A_B", "A", "B", ("r1",), strategy_id="S2X")],
            terminate_ids=["A", "B"],
            strategy_id="S2X",
        ),
        seed_eval={"A": "seed"},
        terminate_eval={"B": "terminate"},
        seed_ids=["A", "B"],
        through_node_ids={"X"},
        search_seed_ids=["A"],
        through_seed_pruned_count=7,
        search_results={"PAIR_A_B": "heavy"},
        search_event_counts={"expanded": 3},
        search_event_samples=[{"event": "expanded"}],
    )
    validations = [
        _validation_result(
            "PAIR_A_B",
            "A",
            "B",
            pruned_road_ids=("r1",),
            trunk_road_ids=("r1",),
            segment_road_ids=("r1",),
        )
    ]

    monkeypatch.setattr(step2_segment_poc, "build_step1_graph_context", lambda **_: context)
    captured_execution: dict[str, step1_pair_poc.Step1StrategyExecution] = {}
    monkeypatch.setattr(
        step2_segment_poc,
        "_build_semantic_endpoints",
        lambda _context: ({"r1": ("A", "B")}, {"A": (), "B": ()}),
    )
    monkeypatch.setattr(step2_segment_poc, "_load_strategy", lambda _path: strategy)
    monkeypatch.setattr(step2_segment_poc, "run_step1_strategy", lambda _context, _strategy: execution)
    monkeypatch.setattr(step2_segment_poc, "write_step1_candidate_outputs", lambda *args, **kwargs: None)
    def _fake_validate_pair_candidates(*args, **kwargs):
        captured_execution["value"] = args[0]
        callback = kwargs["progress_callback"]
        callback("validation_started", {"validation_count": 1})
        callback(
            "validation_pair_state",
            {
                "pair_index": 1,
                "validation_count": 1,
                "pair_id": "S2X:10__20",
                "phase": "validation_pair_started",
                "_perf_log": False,
                "_stdout_log": False,
            },
        )
        callback(
            "validation_pair_checkpoint",
            {
                "pair_index": 1,
                "validation_count": 1,
                "pair_id": "S2X:10__20",
                "phase": "validation_pair_started",
            },
        )
        callback("validation_tighten_started", {"validation_count": 1, "validated_pair_count": 1})
        callback("validation_tighten_completed", {"validation_count": 1, "validated_pair_count": 1})
        return validations

    monkeypatch.setattr(step2_segment_poc, "_validate_pair_candidates", _fake_validate_pair_candidates)

    def _fake_write_step2_outputs(
        out_dir: Path,
        *,
        strategy,
        run_id,
        context,
        validations,
        endpoint_pool_source_map,
        formway_mode,
        debug,
        retain_validation_details,
        progress_callback=None,
    ) -> step2_segment_poc.Step2StrategyResult:
        out_dir.mkdir(parents=True, exist_ok=True)
        return step2_segment_poc.Step2StrategyResult(
            strategy=strategy,
            segment_summary={
                "strategy_id": strategy.strategy_id,
                "candidate_pair_count": 1,
                "validated_pair_count": 1,
                "rejected_pair_count": 0,
            },
            output_files=[],
            validations=validations if retain_validation_details else [],
        )

    monkeypatch.setattr(step2_segment_poc, "_write_step2_outputs", _fake_write_step2_outputs)

    progress_events: list[tuple[str, dict[str, object]]] = []
    results = step2_segment_poc.run_step2_segment_poc(
        road_path=tmp_path / "roads.geojson",
        node_path=tmp_path / "nodes.geojson",
        strategy_config_paths=[tmp_path / "strategy.json"],
        out_root=out_root,
        retain_validation_details=False,
        assume_working_layers=True,
        progress_callback=lambda event, payload: progress_events.append((event, payload)),
    )

    assert results[0].validations == []
    assert captured_execution["value"].pair_candidates == execution.pair_candidates
    assert captured_execution["value"].seed_ids == execution.seed_ids
    assert captured_execution["value"].terminate_ids == execution.terminate_ids
    assert captured_execution["value"].seed_eval == {}
    assert captured_execution["value"].terminate_eval == {}
    assert captured_execution["value"].through_node_ids == set()
    assert captured_execution["value"].search_seed_ids == []
    assert captured_execution["value"].through_seed_pruned_count == 0
    assert captured_execution["value"].search_results == {}
    assert captured_execution["value"].search_event_counts == {}
    assert captured_execution["value"].search_event_samples == []
    assert [event for event, _ in progress_events] == [
        "context_build_started",
        "context_build_completed",
        "semantic_endpoints_completed",
        "strategy_started",
        "strategy_loaded",
        "candidate_search_completed",
        "candidate_outputs_written",
        "validation_started",
        "validation_pair_state",
        "validation_pair_checkpoint",
        "validation_tighten_started",
        "validation_tighten_completed",
        "validation_completed",
        "step2_outputs_written",
        "strategy_memory_released",
        "comparison_summary_written",
    ]
    comparison_summary = _load_json(out_root / "strategy_comparison.json")
    assert comparison_summary[0]["strategy_id"] == "S2X"
    assert comparison_summary[0]["validated_pair_count"] == 1
