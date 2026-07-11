from __future__ import annotations

from tests.modules.t01_data_preprocess.step2_segment_test_support import *  # noqa: F401,F403


def test_write_step2_outputs_streams_release_outputs_without_buffering_lists(tmp_path: Path) -> None:
    out_dir = tmp_path / "step2_outputs"
    strategy = _minimal_strategy("S2X")
    roads = [
        _road_record("r1", "A", "B"),
        _road_record("r2", "B", "C"),
    ]
    context = _minimal_context(roads)
    validations = [
        _validation_result(
            "PAIR_A_B",
            "A",
            "B",
            pruned_road_ids=("r1",),
            trunk_road_ids=("r1",),
            segment_road_ids=("r1",),
        ),
        _validation_result(
            "PAIR_B_C",
            "B",
            "C",
            pruned_road_ids=("r2",),
            trunk_road_ids=(),
            segment_road_ids=(),
            validated_status="rejected",
        ),
    ]

    result = step2_segment_poc._write_step2_outputs(
        out_dir,
        strategy=strategy,
        run_id="run-test",
        context=context,
        validations=validations,
        endpoint_pool_source_map={},
        formway_mode="strict",
        debug=False,
        retain_validation_details=False,
    )

    summary = _load_json(out_dir / "segment_summary.json")
    validated_rows = _read_csv_rows(out_dir / "validated_pairs.csv")
    rejected_rows = _read_csv_rows(out_dir / "rejected_pair_candidates.csv")
    validation_rows = _read_csv_rows(out_dir / "pair_validation_table.csv")

    assert summary["candidate_pair_count"] == 2
    assert summary["validated_pair_count"] == 1
    assert summary["rejected_pair_count"] == 1
    assert [row["pair_id"] for row in validated_rows] == ["PAIR_A_B"]
    assert [row["pair_id"] for row in rejected_rows] == ["PAIR_B_C"]
    assert [row["pair_id"] for row in validation_rows] == ["PAIR_A_B", "PAIR_B_C"]
    assert result.validations == []
    assert (out_dir / "trunk_roads.gpkg").is_file()
    assert (out_dir / "segment_body_roads.gpkg").is_file()
    assert (out_dir / "step3_residual_roads.gpkg").is_file()


def test_same_stage_arbitration_uses_exact_solver_for_single_option_large_component() -> None:
    options_by_pair: dict[str, list[step2_arbitration.PairArbitrationOption]] = {
        "S2:1019883__1026500": [
            _arbitration_option(
                "S2:1019883__1026500::opt_01",
                "S2:1019883__1026500",
                "1019883",
                "1026500",
                trunk_road_ids=("road_left", "shared_1"),
                pruned_road_ids=("road_left", "shared_1"),
                segment_candidate_road_ids=("road_left", "shared_1"),
                segment_road_ids=("road_left",),
            )
        ],
        "S2:1026500__1026503": [
            _arbitration_option(
                "S2:1026500__1026503::opt_03",
                "S2:1026500__1026503",
                "1026500",
                "1026503",
                trunk_road_ids=("shared_1", "shared_2"),
                pruned_road_ids=("shared_1", "shared_2"),
                segment_candidate_road_ids=("shared_1", "shared_2"),
                segment_road_ids=("shared_1", "shared_2"),
            )
        ],
    }
    road_to_node_ids = {
        "road_left": ("1019883", "1026500"),
        "shared_1": ("1026500", "500588029"),
        "shared_2": ("500588029", "1026503"),
    }
    road_lengths = {road_id: 1.0 for road_id in road_to_node_ids}
    for index in range(3, 12):
        pair_id = f"S2:filler_{index:02d}"
        road_id = f"filler_{index:02d}"
        options_by_pair[pair_id] = [
            _arbitration_option(
                f"{pair_id}::opt_01",
                pair_id,
                f"FN{index}",
                f"GN{index}",
                trunk_road_ids=(road_id,),
                pruned_road_ids=(road_id,),
                segment_candidate_road_ids=(road_id,),
                segment_road_ids=(road_id,),
            )
        ]
        road_to_node_ids[road_id] = (f"FN{index}", f"GN{index}")
        road_lengths[road_id] = 1.0

    outcome = step2_arbitration.arbitrate_pair_options(
        options_by_pair=options_by_pair,
        single_pair_illegal_pair_ids=set(),
        road_lengths=road_lengths,
        road_to_node_ids=road_to_node_ids,
        weak_endpoint_node_ids=set(),
        boundary_node_ids=set(),
        semantic_conflict_node_ids=set(),
        strong_anchor_node_ids={"500588029"},
    )

    decision_by_pair_id = {decision.pair_id: decision for decision in outcome.decisions}
    assert decision_by_pair_id["S2:1026500__1026503"].arbitration_status == "win"
    assert decision_by_pair_id["S2:1026500__1026503"].strong_anchor_win_count == 1
    assert decision_by_pair_id["S2:1019883__1026500"].arbitration_status == "lose"
    assert "S2:1019883__1026500" not in outcome.selected_options_by_pair_id
    assert outcome.selected_options_by_pair_id["S2:1026500__1026503"].option_id == "S2:1026500__1026503::opt_03"
    assert outcome.components[0].strong_anchor_node_ids == ("500588029",)
    assert outcome.components[0].fallback_greedy_used is False
    assert outcome.components[0].exact_solver_used is True


def test_same_stage_arbitration_prefers_higher_endpoint_grade_priority() -> None:
    options_by_pair: dict[str, list[step2_arbitration.PairArbitrationOption]] = {
        "PAIR_HIGH": [
            _arbitration_option(
                "PAIR_HIGH::opt_01",
                "PAIR_HIGH",
                "A",
                "B",
                trunk_road_ids=("shared",),
                pruned_road_ids=("shared",),
                segment_candidate_road_ids=("shared",),
                segment_road_ids=("shared",),
                support_info_overrides={"endpoint_priority_grades": [3, 2]},
            )
        ],
        "PAIR_LOW": [
            _arbitration_option(
                "PAIR_LOW::opt_01",
                "PAIR_LOW",
                "C",
                "D",
                trunk_road_ids=("shared",),
                pruned_road_ids=("shared",),
                segment_candidate_road_ids=("shared",),
                segment_road_ids=("shared",),
                support_info_overrides={"endpoint_priority_grades": [2, 2]},
            )
        ],
    }
    outcome = step2_arbitration.arbitrate_pair_options(
        options_by_pair=options_by_pair,
        single_pair_illegal_pair_ids=set(),
        road_lengths={"shared": 10.0},
        road_to_node_ids={"shared": ("N1", "N2")},
        weak_endpoint_node_ids=set(),
        boundary_node_ids=set(),
        semantic_conflict_node_ids=set(),
        strong_anchor_node_ids=set(),
    )

    decision_by_pair_id = {decision.pair_id: decision for decision in outcome.decisions}
    assert decision_by_pair_id["PAIR_HIGH"].arbitration_status == "win"
    assert decision_by_pair_id["PAIR_LOW"].arbitration_status == "lose"
    assert decision_by_pair_id["PAIR_LOW"].lose_reason == "endpoint_grade_priority_lower"
    assert outcome.selected_options_by_pair_id["PAIR_HIGH"].option_id == "PAIR_HIGH::opt_01"


def test_arbitration_strong_anchor_node_ids_requires_cross_flag_three() -> None:
    context = _minimal_context(
        [],
        semantic_nodes={
            "KEEP_2048": _semantic_node_record("KEEP_2048", kind_2=2048, grade_2=2, cross_flag=3),
            "KEEP_4": _semantic_node_record("KEEP_4", kind_2=4, grade_2=3, cross_flag=3),
            "DROP_LOW_CROSS": _semantic_node_record("DROP_LOW_CROSS", kind_2=4, grade_2=3, cross_flag=2),
            "DROP_LOW_GRADE": _semantic_node_record("DROP_LOW_GRADE", kind_2=4, grade_2=1, cross_flag=3),
            "DROP_OTHER_KIND": _semantic_node_record("DROP_OTHER_KIND", kind_2=1, grade_2=3, cross_flag=3),
        },
    )

    assert step2_validation_utils._arbitration_strong_anchor_node_ids(context) == {
        "KEEP_2048",
        "KEEP_4",
    }


def test_same_stage_arbitration_strong_anchor_exact_solver_keeps_additional_non_conflicting_pair() -> None:
    options_by_pair: dict[str, list[step2_arbitration.PairArbitrationOption]] = {
        "PAIR_A_B": [
            _arbitration_option(
                "PAIR_A_B::opt_01",
                "PAIR_A_B",
                "A",
                "B",
                trunk_road_ids=("shared_1", "shared_2"),
                pruned_road_ids=("shared_1", "shared_2"),
                segment_candidate_road_ids=("shared_1", "shared_2"),
                segment_road_ids=("shared_1", "shared_2"),
            )
        ],
        "PAIR_C_D": [
            _arbitration_option(
                "PAIR_C_D::opt_01",
                "PAIR_C_D",
                "C",
                "D",
                trunk_road_ids=("left_only", "shared_1"),
                pruned_road_ids=("left_only", "shared_1"),
                segment_candidate_road_ids=("left_only", "shared_1"),
                segment_road_ids=("left_only",),
            )
        ],
        "PAIR_E_F": [
            _arbitration_option(
                "PAIR_E_F::opt_01",
                "PAIR_E_F",
                "E",
                "F",
                trunk_road_ids=("independent",),
                pruned_road_ids=("independent",),
                segment_candidate_road_ids=("independent",),
                segment_road_ids=("independent",),
            )
        ],
    }
    road_to_node_ids = {
        "shared_1": ("B", "500588029"),
        "shared_2": ("500588029", "A2"),
        "left_only": ("C", "D"),
        "independent": ("E", "F"),
    }
    road_lengths = {road_id: 1.0 for road_id in road_to_node_ids}

    outcome = step2_arbitration.arbitrate_pair_options(
        options_by_pair=options_by_pair,
        single_pair_illegal_pair_ids=set(),
        road_lengths=road_lengths,
        road_to_node_ids=road_to_node_ids,
        weak_endpoint_node_ids=set(),
        boundary_node_ids=set(),
        semantic_conflict_node_ids=set(),
        strong_anchor_node_ids={"500588029"},
    )

    assert set(outcome.selected_options_by_pair_id) == {"PAIR_A_B", "PAIR_E_F"}
    component = next(component for component in outcome.components if component.component_id == "component_0001")
    assert component.exact_solver_used is True
    assert component.fallback_greedy_used is False


def test_same_stage_arbitration_prefers_pair_support_aligned_direct_option_in_small_triangle() -> None:
    options_by_pair: dict[str, list[step2_arbitration.PairArbitrationOption]] = {
        "STEP4:1005083__1005084": [
            _arbitration_option(
                "STEP4:1005083__1005084::opt_01",
                "STEP4:1005083__1005084",
                "1005083",
                "1005084",
                trunk_road_ids=("627810729", "15667648"),
                pruned_road_ids=("627810729", "15667648"),
                segment_candidate_road_ids=("627810729", "15667648"),
                segment_road_ids=("627810729", "15667648"),
                forward_path_road_ids=("627810729", "15667648"),
                reverse_path_road_ids=("15667648", "627810729"),
            )
        ],
        "STEP4:1005083__38626267": [
            _arbitration_option(
                "STEP4:1005083__38626267::opt_01",
                "STEP4:1005083__38626267",
                "1005083",
                "38626267",
                trunk_road_ids=("34915034", "504979401"),
                pruned_road_ids=("34915034", "504979401"),
                segment_candidate_road_ids=("34915034", "504979401"),
                segment_road_ids=("34915034", "504979401"),
                forward_path_road_ids=("34915034", "504979401"),
                reverse_path_road_ids=("504979401", "34915034"),
                pair_support_road_ids=("34915034", "504979401"),
            ),
            _arbitration_option(
                "STEP4:1005083__38626267::opt_03",
                "STEP4:1005083__38626267",
                "1005083",
                "38626267",
                trunk_road_ids=("34915023", "34915034", "504979401", "627810729"),
                pruned_road_ids=("34915023", "34915034", "504979401", "627810729"),
                segment_candidate_road_ids=("34915023", "34915034", "504979401", "627810729"),
                segment_road_ids=("34915023", "34915034", "504979401", "627810729"),
                forward_path_road_ids=("34915034", "504979401"),
                reverse_path_road_ids=("504979401", "34915023", "627810729"),
                pair_support_road_ids=("34915034", "504979401"),
                support_info_overrides={"trunk_signed_area": 1.0, "bidirectional_minimal_loop": True},
            ),
        ],
        "STEP4:1005084__38626267": [
            _arbitration_option(
                "STEP4:1005084__38626267::opt_01",
                "STEP4:1005084__38626267",
                "1005084",
                "38626267",
                trunk_road_ids=("15667648", "34915023", "504979401"),
                pruned_road_ids=("15667648", "34915023", "504979401"),
                segment_candidate_road_ids=("15667648", "34915023", "504979401"),
                segment_road_ids=("15667648", "34915023", "504979401"),
                forward_path_road_ids=("15667648", "34915023", "504979401"),
                reverse_path_road_ids=("504979401", "34915023", "15667648"),
            )
        ],
    }
    road_to_node_ids = {
        "627810729": ("1005083", "12843228"),
        "15667648": ("12843228", "1005084"),
        "34915023": ("12843228", "38626270"),
        "34915034": ("1005083", "38626270"),
        "504979401": ("38626270", "38626267"),
    }
    road_lengths = {road_id: 1.0 for road_id in road_to_node_ids}

    outcome = step2_arbitration.arbitrate_pair_options(
        options_by_pair=options_by_pair,
        single_pair_illegal_pair_ids=set(),
        road_lengths=road_lengths,
        road_to_node_ids=road_to_node_ids,
        weak_endpoint_node_ids={"1005083", "1005084", "38626267"},
        boundary_node_ids=set(),
        semantic_conflict_node_ids=set(),
        strong_anchor_node_ids={"1005084", "12843228", "38626267", "38626270"},
    )

    assert set(outcome.selected_options_by_pair_id) == {
        "STEP4:1005083__1005084",
        "STEP4:1005083__38626267",
    }
    assert (
        outcome.selected_options_by_pair_id["STEP4:1005083__38626267"].option_id
        == "STEP4:1005083__38626267::opt_01"
    )
    decision_by_pair_id = {decision.pair_id: decision for decision in outcome.decisions}
    assert decision_by_pair_id["STEP4:1005083__38626267"].pair_support_expansion_penalty == 0
    assert decision_by_pair_id["STEP4:1005084__38626267"].arbitration_status == "lose"


def test_same_stage_arbitration_keeps_first_option_for_single_pair_component() -> None:
    options_by_pair = {
        "PAIR_A_B": [
            _arbitration_option(
                "PAIR_A_B::opt_01",
                "PAIR_A_B",
                "A",
                "B",
                trunk_road_ids=("shortcut",),
                pruned_road_ids=("shortcut",),
                segment_candidate_road_ids=("shortcut",),
                segment_road_ids=("shortcut",),
            ),
            _arbitration_option(
                "PAIR_A_B::opt_02",
                "PAIR_A_B",
                "A",
                "B",
                trunk_road_ids=("left", "right"),
                pruned_road_ids=("left", "right"),
                segment_candidate_road_ids=("left", "right"),
                segment_road_ids=("left", "right"),
            ),
        ],
    }
    road_to_node_ids = {
        "shortcut": ("A", "B"),
        "left": ("A", "X"),
        "right": ("X", "B"),
    }
    road_lengths = {"shortcut": 1.0, "left": 1.0, "right": 1.0}

    outcome = step2_arbitration.arbitrate_pair_options(
        options_by_pair=options_by_pair,
        single_pair_illegal_pair_ids=set(),
        road_lengths=road_lengths,
        road_to_node_ids=road_to_node_ids,
        weak_endpoint_node_ids=set(),
        boundary_node_ids=set(),
        semantic_conflict_node_ids=set(),
        strong_anchor_node_ids=set(),
    )

    assert outcome.selected_options_by_pair_id["PAIR_A_B"].option_id == "PAIR_A_B::opt_01"


def test_same_stage_arbitration_keeps_two_direct_fanout_pairs_when_direct_options_do_not_overlap() -> None:
    options_by_pair = {
        "PAIR_74_75": [
            _arbitration_option(
                "PAIR_74_75::opt_01",
                "PAIR_74_75",
                "61250174",
                "61250175",
                trunk_road_ids=("9097534",),
                pruned_road_ids=("9097534", "9097544", "9097547"),
                segment_candidate_road_ids=("9097534", "9097544", "9097547"),
                segment_road_ids=("9097534",),
            ),
            _arbitration_option(
                "PAIR_74_75::opt_02",
                "PAIR_74_75",
                "61250174",
                "61250175",
                trunk_road_ids=("9097544", "9097547", "9097534"),
                pruned_road_ids=("9097534", "9097544", "9097547"),
                segment_candidate_road_ids=("9097534", "9097544", "9097547"),
                segment_road_ids=("9097534", "9097544", "9097547"),
                forward_path_road_ids=("9097544", "9097547"),
            ),
        ],
        "PAIR_74_76": [
            _arbitration_option(
                "PAIR_74_76::opt_01",
                "PAIR_74_76",
                "61250174",
                "61250176",
                trunk_road_ids=("9097544",),
                pruned_road_ids=("9097534", "9097544", "9097547"),
                segment_candidate_road_ids=("9097534", "9097544", "9097547"),
                segment_road_ids=("9097544",),
            ),
            _arbitration_option(
                "PAIR_74_76::opt_02",
                "PAIR_74_76",
                "61250174",
                "61250176",
                trunk_road_ids=("9097544", "9097547", "9097534"),
                pruned_road_ids=("9097534", "9097544", "9097547"),
                segment_candidate_road_ids=("9097534", "9097544", "9097547"),
                segment_road_ids=("9097534", "9097544", "9097547"),
                forward_path_road_ids=("9097544",),
            ),
        ],
    }
    road_to_node_ids = {
        "9097534": ("61250174", "61250175"),
        "9097544": ("61250176", "61250174"),
        "9097547": ("61250176", "61250175"),
    }
    road_lengths = {road_id: 1.0 for road_id in road_to_node_ids}

    outcome = step2_arbitration.arbitrate_pair_options(
        options_by_pair=options_by_pair,
        single_pair_illegal_pair_ids=set(),
        road_lengths=road_lengths,
        road_to_node_ids=road_to_node_ids,
        weak_endpoint_node_ids=set(),
        boundary_node_ids={"61250175", "61250176", "61250177"},
        semantic_conflict_node_ids={"61250175", "61250176", "61250177"},
        strong_anchor_node_ids=set(),
    )

    assert outcome.selected_options_by_pair_id["PAIR_74_75"].option_id == "PAIR_74_75::opt_01"
    assert outcome.selected_options_by_pair_id["PAIR_74_76"].option_id == "PAIR_74_76::opt_01"


def test_pair_conflicts_ignore_weak_corridor_overlap_that_does_not_dominate_trunk() -> None:
    options_by_pair = {
        "PAIR_A_B": [
            _arbitration_option(
                "PAIR_A_B::opt_01",
                "PAIR_A_B",
                "A",
                "B",
                trunk_road_ids=("t1", "t2", "t3", "t4"),
                pruned_road_ids=("t1", "t2", "t3", "t4"),
                segment_candidate_road_ids=("t1", "t2", "t3", "t4"),
                segment_road_ids=("t1", "t2", "t3", "t4"),
            )
        ],
        "PAIR_C_D": [
            _arbitration_option(
                "PAIR_C_D::opt_01",
                "PAIR_C_D",
                "C",
                "D",
                trunk_road_ids=("u1", "u2", "u3", "u4"),
                pruned_road_ids=("u1", "u2", "u3", "u4", "t1"),
                segment_candidate_road_ids=("u1", "u2", "u3", "u4", "t1"),
                segment_road_ids=("u1", "u2", "u3", "u4"),
            )
        ],
    }

    conflict_records, adjacency = step2_arbitration._build_pair_conflicts(options_by_pair)

    assert conflict_records == []
    assert adjacency["PAIR_A_B"] == set()
    assert adjacency["PAIR_C_D"] == set()


def test_pair_conflicts_ignore_asymmetric_corridor_overlap_without_mutual_trunk_ownership() -> None:
    options_by_pair = {
        "PAIR_MAIN": [
            _arbitration_option(
                "PAIR_MAIN::opt_01",
                "PAIR_MAIN",
                "A",
                "B",
                trunk_road_ids=("shared_1", "shared_2"),
                pruned_road_ids=("shared_1", "shared_2"),
                segment_candidate_road_ids=("shared_1", "shared_2"),
                segment_road_ids=("shared_1", "shared_2"),
            )
        ],
        "PAIR_LOOP": [
            _arbitration_option(
                "PAIR_LOOP::opt_01",
                "PAIR_LOOP",
                "A",
                "C",
                trunk_road_ids=("loop_1", "loop_2", "loop_3", "loop_4"),
                pruned_road_ids=("loop_1", "loop_2", "loop_3", "loop_4", "shared_1", "shared_2"),
                segment_candidate_road_ids=("loop_1", "loop_2", "loop_3", "loop_4", "shared_1", "shared_2"),
                segment_road_ids=("loop_1", "loop_2", "loop_3", "loop_4"),
            )
        ],
    }

    conflict_records, adjacency = step2_arbitration._build_pair_conflicts(options_by_pair)

    assert conflict_records == []
    assert adjacency["PAIR_MAIN"] == set()
    assert adjacency["PAIR_LOOP"] == set()


def test_pair_conflicts_ignore_exact_half_mutual_trunk_overlap() -> None:
    options_by_pair = {
        "PAIR_LONG": [
            _arbitration_option(
                "PAIR_LONG::opt_01",
                "PAIR_LONG",
                "A",
                "B",
                trunk_road_ids=("long_1", "long_2", "long_3", "long_4"),
                pruned_road_ids=("long_1", "long_2", "long_3", "long_4", "short_1", "short_2"),
                segment_candidate_road_ids=("long_1", "long_2", "long_3", "long_4", "short_1", "short_2"),
                segment_road_ids=("long_1", "long_2"),
            )
        ],
        "PAIR_SHORT": [
            _arbitration_option(
                "PAIR_SHORT::opt_01",
                "PAIR_SHORT",
                "C",
                "D",
                trunk_road_ids=("short_1", "short_2", "branch_1", "branch_2"),
                pruned_road_ids=("short_1", "short_2", "branch_1", "branch_2", "long_1", "long_2"),
                segment_candidate_road_ids=("short_1", "short_2", "branch_1", "branch_2", "long_1", "long_2"),
                segment_road_ids=("branch_1", "branch_2"),
            )
        ],
    }

    conflict_records, adjacency = step2_arbitration._build_pair_conflicts(options_by_pair)
    option_conflicts = step2_arbitration._build_option_conflicts(
        ("PAIR_LONG", "PAIR_SHORT"),
        options_by_pair=options_by_pair,
    )

    assert conflict_records == []
    assert adjacency["PAIR_LONG"] == set()
    assert adjacency["PAIR_SHORT"] == set()
    assert option_conflicts == {}


def test_pair_conflicts_ignore_pure_segment_body_overlap_without_trunk_or_mutual_corridor() -> None:
    options_by_pair = {
        "PAIR_SHORT": [
            _arbitration_option(
                "PAIR_SHORT::opt_01",
                "PAIR_SHORT",
                "A",
                "B",
                trunk_road_ids=("short_1", "short_2", "short_3"),
                pruned_road_ids=("short_1", "short_2", "short_3", "anchor_side_1", "anchor_side_2"),
                segment_candidate_road_ids=("short_1", "short_2", "short_3", "anchor_side_1", "anchor_side_2"),
                segment_road_ids=("short_1", "short_2", "short_3"),
            )
        ],
        "PAIR_LONG": [
            _arbitration_option(
                "PAIR_LONG::opt_01",
                "PAIR_LONG",
                "A",
                "C",
                trunk_road_ids=("long_1", "long_2", "long_3", "long_4", "long_5", "anchor_side_1"),
                pruned_road_ids=(
                    "long_1",
                    "long_2",
                    "long_3",
                    "long_4",
                    "long_5",
                    "anchor_side_1",
                    "anchor_side_2",
                    "short_1",
                    "short_2",
                    "short_3",
                ),
                segment_candidate_road_ids=(
                    "long_1",
                    "long_2",
                    "long_3",
                    "long_4",
                    "long_5",
                    "anchor_side_1",
                    "anchor_side_2",
                    "short_1",
                    "short_2",
                    "short_3",
                ),
                segment_road_ids=(
                    "long_1",
                    "long_2",
                    "long_3",
                    "long_4",
                    "long_5",
                    "anchor_side_1",
                    "anchor_side_2",
                    "short_1",
                    "short_2",
                    "short_3",
                ),
            )
        ],
    }
    road_to_node_ids = {
        "short_1": ("A", "J1"),
        "short_2": ("J1", "J2"),
        "short_3": ("J2", "B"),
        "anchor_side_1": ("J2", "ANCHOR"),
        "anchor_side_2": ("ANCHOR", "S1"),
        "long_1": ("A", "L1"),
        "long_2": ("L1", "L2"),
        "long_3": ("L2", "L3"),
        "long_4": ("L3", "L4"),
        "long_5": ("L4", "C"),
    }

    conflict_records, adjacency = step2_arbitration._build_pair_conflicts(
        options_by_pair,
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids={"ANCHOR"},
    )
    option_conflicts = step2_arbitration._build_option_conflicts(
        ("PAIR_LONG", "PAIR_SHORT"),
        options_by_pair=options_by_pair,
    )

    assert conflict_records == []
    assert adjacency["PAIR_SHORT"] == set()
    assert adjacency["PAIR_LONG"] == set()
    assert option_conflicts == {}


def test_pair_conflicts_ignore_serial_segment_overlap_without_shared_trunk_or_strong_anchor() -> None:
    options_by_pair = {
        "PAIR_LEFT": [
            _arbitration_option(
                "PAIR_LEFT::opt_01",
                "PAIR_LEFT",
                "1020120",
                "1020121",
                trunk_road_ids=("66969787",),
                pruned_road_ids=("1084543", "617354887", "66969787"),
                segment_candidate_road_ids=("1084543", "617354887", "66969787"),
                segment_road_ids=("1084543", "617354887", "66969787"),
            )
        ],
        "PAIR_RIGHT": [
            _arbitration_option(
                "PAIR_RIGHT::opt_01",
                "PAIR_RIGHT",
                "1020121",
                "1035968",
                trunk_road_ids=("617354887",),
                pruned_road_ids=("1084543", "617354887", "66969787"),
                segment_candidate_road_ids=("1084543", "617354887", "66969787"),
                segment_road_ids=("1084543", "617354887", "66969787"),
            )
        ],
    }
    road_to_node_ids = {
        "66969787": ("1020120", "1020121"),
        "617354887": ("1020121", "1035968"),
        "1084543": ("1020120", "1035968"),
    }

    conflict_records, adjacency = step2_arbitration._build_pair_conflicts(
        options_by_pair,
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids=set(),
    )
    option_conflicts = step2_arbitration._build_option_conflicts(
        ("PAIR_LEFT", "PAIR_RIGHT"),
        options_by_pair=options_by_pair,
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids=set(),
    )

    assert conflict_records == []
    assert adjacency["PAIR_LEFT"] == set()
    assert adjacency["PAIR_RIGHT"] == set()
    assert option_conflicts == {}


def test_pair_conflicts_ignore_single_shared_trunk_connector_without_key_corridor() -> None:
    options_by_pair = {
        "PAIR_MAIN": [
            _arbitration_option(
                "PAIR_MAIN::opt_01",
                "PAIR_MAIN",
                "A",
                "B",
                trunk_road_ids=("main_1", "main_2", "connector"),
                pruned_road_ids=("main_1", "main_2", "connector", "side_1", "side_2"),
                segment_candidate_road_ids=("main_1", "main_2", "connector", "side_1", "side_2"),
                segment_road_ids=("main_1", "main_2", "connector", "side_1", "side_2"),
            )
        ],
        "PAIR_BRANCH": [
            _arbitration_option(
                "PAIR_BRANCH::opt_01",
                "PAIR_BRANCH",
                "A",
                "C",
                trunk_road_ids=("connector", "branch_1", "branch_2"),
                pruned_road_ids=("connector", "branch_1", "branch_2", "side_1", "side_2"),
                segment_candidate_road_ids=("connector", "branch_1", "branch_2", "side_1", "side_2"),
                segment_road_ids=("connector", "branch_1", "branch_2", "side_1", "side_2"),
            )
        ],
    }

    road_to_node_ids = {
        "main_1": ("A", "M1"),
        "main_2": ("M1", "B"),
        "connector": ("M1", "ANCHOR"),
        "side_1": ("ANCHOR", "S1"),
        "side_2": ("S1", "S2"),
        "branch_1": ("ANCHOR", "B1"),
        "branch_2": ("B1", "C"),
    }

    conflict_records, adjacency = step2_arbitration._build_pair_conflicts(
        options_by_pair,
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids={"ANCHOR"},
    )

    assert conflict_records == []
    assert adjacency["PAIR_MAIN"] == set()
    assert adjacency["PAIR_BRANCH"] == set()


def test_pair_conflicts_keep_single_shared_trunk_connector_when_touching_tjunction_anchor() -> None:
    options_by_pair = {
        "PAIR_MAIN": [
            _arbitration_option(
                "PAIR_MAIN::opt_01",
                "PAIR_MAIN",
                "A",
                "B",
                trunk_road_ids=("main_1", "main_2", "connector"),
                pruned_road_ids=("main_1", "main_2", "connector", "side_1", "side_2"),
                segment_candidate_road_ids=("main_1", "main_2", "connector", "side_1", "side_2"),
                segment_road_ids=("main_1", "main_2", "connector", "side_1", "side_2"),
            )
        ],
        "PAIR_BRANCH": [
            _arbitration_option(
                "PAIR_BRANCH::opt_01",
                "PAIR_BRANCH",
                "A",
                "C",
                trunk_road_ids=("connector", "branch_1", "branch_2"),
                pruned_road_ids=("connector", "branch_1", "branch_2", "side_1", "side_2"),
                segment_candidate_road_ids=("connector", "branch_1", "branch_2", "side_1", "side_2"),
                segment_road_ids=("connector", "branch_1", "branch_2", "side_1", "side_2"),
                support_info_overrides={"bidirectional_minimal_loop": True},
            )
        ],
    }

    road_to_node_ids = {
        "main_1": ("A", "M1"),
        "main_2": ("M1", "B"),
        "connector": ("M1", "ANCHOR"),
        "side_1": ("ANCHOR", "S1"),
        "side_2": ("S1", "S2"),
        "branch_1": ("ANCHOR", "B1"),
        "branch_2": ("B1", "C"),
    }

    conflict_records, adjacency = step2_arbitration._build_pair_conflicts(
        options_by_pair,
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids={"ANCHOR"},
        tjunction_anchor_node_ids={"ANCHOR"},
    )

    assert len(conflict_records) == 1
    assert conflict_records[0].conflict_types == ("trunk_overlap", "segment_body_overlap")
    assert adjacency["PAIR_MAIN"] == {"PAIR_BRANCH"}
    assert adjacency["PAIR_BRANCH"] == {"PAIR_MAIN"}


def test_pair_conflicts_ignore_single_shared_trunk_between_tjunction_and_other_strong_anchor() -> None:
    options_by_pair = {
        "PAIR_MAIN": [
            _arbitration_option(
                "PAIR_MAIN::opt_01",
                "PAIR_MAIN",
                "A",
                "B",
                trunk_road_ids=("left_1", "connector", "left_2"),
                pruned_road_ids=("left_1", "connector", "left_2"),
                segment_candidate_road_ids=("left_1", "connector", "left_2"),
                segment_road_ids=("left_1", "connector", "left_2"),
                support_info_overrides={"bidirectional_minimal_loop": True},
            )
        ],
        "PAIR_BRANCH": [
            _arbitration_option(
                "PAIR_BRANCH::opt_01",
                "PAIR_BRANCH",
                "A",
                "C",
                trunk_road_ids=("right_1", "connector", "right_2"),
                pruned_road_ids=("right_1", "connector", "right_2"),
                segment_candidate_road_ids=("right_1", "connector", "right_2"),
                segment_road_ids=("right_1", "connector", "right_2"),
            )
        ],
    }

    road_to_node_ids = {
        "left_1": ("A", "STRONG"),
        "connector": ("STRONG", "TJ"),
        "left_2": ("TJ", "B"),
        "right_1": ("A", "STRONG"),
        "right_2": ("TJ", "C"),
    }

    conflict_records, adjacency = step2_arbitration._build_pair_conflicts(
        options_by_pair,
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids={"STRONG", "TJ"},
        tjunction_anchor_node_ids={"TJ"},
    )

    assert conflict_records == []
    assert adjacency["PAIR_MAIN"] == set()
    assert adjacency["PAIR_BRANCH"] == set()


def test_pair_conflicts_keep_single_shared_trunk_between_two_strong_anchors() -> None:
    options_by_pair = {
        "PAIR_LEFT": [
            _arbitration_option(
                "PAIR_LEFT::opt_01",
                "PAIR_LEFT",
                "A",
                "B",
                trunk_road_ids=("left_1", "connector", "left_2"),
                pruned_road_ids=("left_1", "connector", "left_2"),
                segment_candidate_road_ids=("left_1", "connector", "left_2"),
                segment_road_ids=("left_1", "connector", "left_2"),
            )
        ],
        "PAIR_RIGHT": [
            _arbitration_option(
                "PAIR_RIGHT::opt_01",
                "PAIR_RIGHT",
                "C",
                "D",
                trunk_road_ids=("right_1", "connector", "right_2"),
                pruned_road_ids=("right_1", "connector", "right_2"),
                segment_candidate_road_ids=("right_1", "connector", "right_2"),
                segment_road_ids=("right_1", "connector", "right_2"),
            )
        ],
    }

    road_to_node_ids = {
        "left_1": ("A", "STRONG_LEFT"),
        "connector": ("STRONG_LEFT", "STRONG_RIGHT"),
        "left_2": ("STRONG_RIGHT", "B"),
        "right_1": ("C", "STRONG_LEFT"),
        "right_2": ("STRONG_RIGHT", "D"),
    }

    conflict_records, adjacency = step2_arbitration._build_pair_conflicts(
        options_by_pair,
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids={"STRONG_LEFT", "STRONG_RIGHT"},
        tjunction_anchor_node_ids={"STRONG_LEFT", "STRONG_RIGHT"},
    )

    assert len(conflict_records) == 1
    assert conflict_records[0].conflict_types == ("trunk_overlap", "segment_body_overlap")
    assert adjacency["PAIR_LEFT"] == {"PAIR_RIGHT"}
    assert adjacency["PAIR_RIGHT"] == {"PAIR_LEFT"}


def test_pair_conflicts_keep_single_shared_trunk_when_not_touching_strong_anchor() -> None:
    options_by_pair = {
        "PAIR_LEFT": [
            _arbitration_option(
                "PAIR_LEFT::opt_01",
                "PAIR_LEFT",
                "A",
                "B",
                trunk_road_ids=("shared", "left_1", "left_2"),
                pruned_road_ids=("shared", "left_1", "left_2"),
                segment_candidate_road_ids=("shared", "left_1", "left_2"),
                segment_road_ids=("shared", "left_1", "left_2"),
            )
        ],
        "PAIR_RIGHT": [
            _arbitration_option(
                "PAIR_RIGHT::opt_01",
                "PAIR_RIGHT",
                "A",
                "C",
                trunk_road_ids=("shared", "right_1", "right_2"),
                pruned_road_ids=("shared", "right_1", "right_2"),
                segment_candidate_road_ids=("shared", "right_1", "right_2"),
                segment_road_ids=("shared", "right_1", "right_2"),
            )
        ],
    }
    road_to_node_ids = {
        "shared": ("J1", "J2"),
        "left_1": ("A", "J1"),
        "left_2": ("J2", "B"),
        "right_1": ("A", "J1"),
        "right_2": ("J2", "C"),
    }

    conflict_records, adjacency = step2_arbitration._build_pair_conflicts(
        options_by_pair,
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids={"ANCHOR"},
    )

    assert len(conflict_records) == 1
    assert conflict_records[0].conflict_types == ("trunk_overlap", "segment_body_overlap")
    assert adjacency["PAIR_LEFT"] == {"PAIR_RIGHT"}
    assert adjacency["PAIR_RIGHT"] == {"PAIR_LEFT"}


def test_pair_conflicts_keep_single_shared_trunk_when_shared_connector_touches_pair_endpoint() -> None:
    options_by_pair = {
        "PAIR_LEFT": [
            _arbitration_option(
                "PAIR_LEFT::opt_01",
                "PAIR_LEFT",
                "A",
                "B",
                trunk_road_ids=("shared", "left_1"),
                pruned_road_ids=("shared", "left_1", "left_side"),
                segment_candidate_road_ids=("shared", "left_1", "left_side"),
                segment_road_ids=("shared", "left_1", "left_side"),
            )
        ],
        "PAIR_RIGHT": [
            _arbitration_option(
                "PAIR_RIGHT::opt_01",
                "PAIR_RIGHT",
                "A",
                "C",
                trunk_road_ids=("shared", "right_1", "right_2"),
                pruned_road_ids=("shared", "right_1", "right_2"),
                segment_candidate_road_ids=("shared", "right_1", "right_2"),
                segment_road_ids=("shared", "right_1", "right_2"),
                support_info_overrides={"bidirectional_minimal_loop": True},
            )
        ],
    }
    road_to_node_ids = {
        "shared": ("A", "ANCHOR"),
        "left_1": ("ANCHOR", "B"),
        "left_side": ("ANCHOR", "S1"),
        "right_1": ("ANCHOR", "MID"),
        "right_2": ("MID", "C"),
    }

    conflict_records, adjacency = step2_arbitration._build_pair_conflicts(
        options_by_pair,
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids={"ANCHOR"},
    )

    assert len(conflict_records) == 1
    assert conflict_records[0].conflict_types == ("trunk_overlap", "segment_body_overlap")
    assert adjacency["PAIR_LEFT"] == {"PAIR_RIGHT"}
    assert adjacency["PAIR_RIGHT"] == {"PAIR_LEFT"}
