from __future__ import annotations

from rcsd_topo_poc.modules.t01_data_preprocess import step2_arbitration


def _option(
    option_id: str,
    pair_id: str,
    a_node_id: str,
    b_node_id: str,
    *,
    trunk_road_ids: tuple[str, ...],
    pair_support_road_ids: tuple[str, ...],
    transition_same_dir_blocked: bool = False,
) -> step2_arbitration.PairArbitrationOption:
    return step2_arbitration.PairArbitrationOption(
        option_id=option_id,
        pair_id=pair_id,
        a_node_id=a_node_id,
        b_node_id=b_node_id,
        trunk_mode="counterclockwise_loop",
        counterclockwise_ok=True,
        warning_codes=(),
        candidate_channel_road_ids=trunk_road_ids,
        pruned_road_ids=trunk_road_ids,
        trunk_road_ids=trunk_road_ids,
        segment_candidate_road_ids=trunk_road_ids,
        segment_road_ids=trunk_road_ids,
        branch_cut_road_ids=(),
        boundary_terminate_node_ids=(),
        transition_same_dir_blocked=transition_same_dir_blocked,
        support_info={
            "pair_support_road_ids": list(pair_support_road_ids),
            "endpoint_priority_grades": [1, 1],
        },
    )


def test_prefer_pair_support_aligned_minimal_options_prefers_max_overlap_in_compact_anchor_scope() -> None:
    road_to_node_ids = {
        "t1": ("A", "LEFT"),
        "t2": ("LEFT", "ANCHOR"),
        "t3": ("ANCHOR", "RIGHT"),
        "t4": ("RIGHT", "B"),
        "u1": ("ANCHOR", "B"),
    }
    pair_options = [
        _option(
            "PAIR::opt_local",
            "PAIR",
            "A",
            "B",
            trunk_road_ids=("t1", "t2", "t3", "t4"),
            pair_support_road_ids=("t1", "t2", "t3", "t4"),
        ),
        _option(
            "PAIR::opt_loop",
            "PAIR",
            "A",
            "B",
            trunk_road_ids=("t1", "t2", "u1"),
            pair_support_road_ids=("t1", "t2", "t3", "t4"),
        ),
    ]

    preferred = step2_arbitration._prefer_pair_support_aligned_minimal_options(
        pair_options,
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids={"ANCHOR"},
    )

    assert [option.option_id for option in preferred] == ["PAIR::opt_local"]


def test_prefer_pair_support_aligned_minimal_options_uses_trunk_internal_nodes_for_anchor_touch() -> None:
    road_to_node_ids = {
        "t1": ("A", "MID"),
        "t2": ("MID", "B"),
        "side_1": ("MID", "ANCHOR"),
        "side_2": ("ANCHOR", "SIDE"),
    }
    trunk_only = _option(
        "PAIR::opt_trunk_only",
        "PAIR",
        "A",
        "B",
        trunk_road_ids=("t1", "t2"),
        pair_support_road_ids=("t1", "t2"),
    )
    anchor_only_in_segment_candidate = step2_arbitration.PairArbitrationOption(
        **{
            **trunk_only.__dict__,
            "option_id": "PAIR::opt_anchor_only_in_segment_candidate",
            "segment_candidate_road_ids": ("t1", "t2", "side_1", "side_2"),
            "pruned_road_ids": ("t1", "t2", "side_1", "side_2"),
        }
    )

    preferred = step2_arbitration._prefer_pair_support_aligned_minimal_options(
        [anchor_only_in_segment_candidate, trunk_only],
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids={"ANCHOR"},
    )

    assert preferred == [anchor_only_in_segment_candidate, trunk_only]


def test_option_metrics_discount_transition_blocked_expanded_boundary_swallow() -> None:
    option = _option(
        "PAIR::opt_discount",
        "PAIR",
        "A",
        "B",
        trunk_road_ids=("road_1", "road_2", "road_3"),
        pair_support_road_ids=("road_1", "road_2"),
        transition_same_dir_blocked=True,
    )
    road_to_node_ids = {
        "road_1": ("A", "MID"),
        "road_2": ("MID", "B"),
        "road_3": ("MID", "SIDE"),
    }

    metrics = step2_arbitration._option_metrics(
        option,
        contested_road_ids={"road_1", "road_2", "road_3", "road_4"},
        road_lengths={road_id: 1.0 for road_id in road_to_node_ids},
        road_to_node_ids=road_to_node_ids,
        weak_endpoint_node_ids=set(),
        boundary_node_ids={"MID"},
        semantic_conflict_node_ids=set(),
    )

    assert metrics.pair_support_expansion_penalty == 1
    assert metrics.internal_endpoint_penalty == 1
    assert metrics.contested_trunk_coverage_count == 2
    assert metrics.contested_trunk_coverage_ratio == 0.5


def test_strong_anchor_win_count_ignores_anchor_only_reached_by_expanded_tail() -> None:
    option = _option(
        "PAIR::opt_expanded_tail",
        "PAIR",
        "A",
        "B",
        trunk_road_ids=("support_1", "support_2", "tail_1", "tail_2"),
        pair_support_road_ids=("support_1", "support_2"),
    )
    road_to_node_ids = {
        "support_1": ("A", "MID"),
        "support_2": ("MID", "B"),
        "tail_1": ("MID", "ANCHOR"),
        "tail_2": ("ANCHOR", "SIDE"),
    }
    metrics = step2_arbitration._option_metrics(
        option,
        contested_road_ids=set(road_to_node_ids),
        road_lengths={road_id: 1.0 for road_id in road_to_node_ids},
        road_to_node_ids=road_to_node_ids,
        weak_endpoint_node_ids=set(),
        boundary_node_ids=set(),
        semantic_conflict_node_ids=set(),
    )

    win_counts = step2_arbitration._strong_anchor_win_counts(
        ("PAIR",),
        options_by_pair={"PAIR": [option]},
        metrics_by_option_id={option.option_id: metrics},
        road_lengths={road_id: 1.0 for road_id in road_to_node_ids},
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids={"ANCHOR"},
    )

    assert win_counts == {}


def test_prefer_subset_dominated_same_pair_options_drops_larger_superset_loop() -> None:
    mid_local = _option(
        "MID::opt_01",
        "MID",
        "M1",
        "M2",
        trunk_road_ids=("m1", "m2", "m3", "m4", "m5", "m6", "m7"),
        pair_support_road_ids=("m1", "m2", "m3", "m4", "m5", "m6"),
    )
    mid_expanded = _option(
        "MID::opt_05",
        "MID",
        "M1",
        "M2",
        trunk_road_ids=("m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9"),
        pair_support_road_ids=("m1", "m2", "m3", "m4", "m5", "m6", "m7"),
    )

    metrics_by_option_id = {
        mid_local.option_id: step2_arbitration.PairArbitrationMetrics(
            endpoint_grade_priority_major=1,
            endpoint_grade_priority_minor=1,
            endpoint_boundary_penalty=0,
            strong_anchor_win_count=0,
            corridor_naturalness_score=0,
            contested_trunk_coverage_count=1,
            contested_trunk_coverage_ratio=0.05,
            pair_support_expansion_penalty=1,
            internal_endpoint_penalty=0,
            body_connectivity_support=587.0,
            semantic_conflict_penalty=3,
        ),
        mid_expanded.option_id: step2_arbitration.PairArbitrationMetrics(
            endpoint_grade_priority_major=1,
            endpoint_grade_priority_minor=1,
            endpoint_boundary_penalty=0,
            strong_anchor_win_count=0,
            corridor_naturalness_score=0,
            contested_trunk_coverage_count=3,
            contested_trunk_coverage_ratio=0.15,
            pair_support_expansion_penalty=2,
            internal_endpoint_penalty=0,
            body_connectivity_support=798.0,
            semantic_conflict_penalty=4,
        ),
    }

    preferred = step2_arbitration._prefer_subset_dominated_same_pair_options(
        [mid_local, mid_expanded],
        metrics_by_option_id=metrics_by_option_id,
    )

    assert [option.option_id for option in preferred] == ["MID::opt_01"]


def test_solve_component_exact_keeps_tie_break_stable_when_scores_equal() -> None:
    left_opt_01 = _option(
        "LEFT::opt_01",
        "LEFT",
        "A",
        "B",
        trunk_road_ids=("l1",),
        pair_support_road_ids=("l1",),
    )
    left_opt_02 = _option(
        "LEFT::opt_02",
        "LEFT",
        "A",
        "B",
        trunk_road_ids=("l2",),
        pair_support_road_ids=("l2",),
    )
    right_opt_01 = _option(
        "RIGHT::opt_01",
        "RIGHT",
        "C",
        "D",
        trunk_road_ids=("r1",),
        pair_support_road_ids=("r1",),
    )
    right_opt_02 = _option(
        "RIGHT::opt_02",
        "RIGHT",
        "C",
        "D",
        trunk_road_ids=("r2",),
        pair_support_road_ids=("r2",),
    )

    metrics = step2_arbitration.PairArbitrationMetrics(
        endpoint_grade_priority_major=1,
        endpoint_grade_priority_minor=1,
        endpoint_boundary_penalty=0,
        strong_anchor_win_count=0,
        corridor_naturalness_score=0,
        contested_trunk_coverage_count=0,
        contested_trunk_coverage_ratio=0.0,
        pair_support_expansion_penalty=0,
        internal_endpoint_penalty=0,
        body_connectivity_support=1.0,
        semantic_conflict_penalty=0,
    )

    selected = step2_arbitration._solve_component_exact(
        ("LEFT", "RIGHT"),
        options_by_pair={
            "LEFT": [left_opt_01, left_opt_02],
            "RIGHT": [right_opt_01, right_opt_02],
        },
        option_conflicts={},
        metrics_by_option_id={
            left_opt_01.option_id: metrics,
            left_opt_02.option_id: metrics,
            right_opt_01.option_id: metrics,
            right_opt_02.option_id: metrics,
        },
        strong_anchor_priority_enabled=False,
    )

    assert selected == {
        "LEFT": left_opt_01,
        "RIGHT": right_opt_01,
    }
