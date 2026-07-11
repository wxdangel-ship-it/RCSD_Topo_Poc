from __future__ import annotations

from tests.modules.p01_arm_build.p01_test_support import *  # noqa: F401,F403


def test_final_arm_validation_not_required_for_single_source_final_arm() -> None:
    nodes = _validation_nodes()
    roads = _validation_roads()
    initial = (_validation_initial("A1", "T1", "s1"),)
    traces = (_validation_trace("A1", "T1", "s1"),)

    for merge_status in ("not_applied", "local_candidate_fallback"):
        result = build_final_arm_validation(
            dataset="SWSD",
            junction_id="C",
            current_group_id="C",
            groups=_validation_groups(nodes),
            nodes=nodes,
            roads=roads,
            initial_arms=initial,
            final_arms=(_validation_final(("A1",), merge_status=merge_status),),
            traces=traces,
            excluded_road_ids=set(),
            internal_road_ids=set(),
        )

        assert result.validations[0].validation_status == "not_required"
        assert result.final_arms[0].validation_status == "not_required"
        assert result.metrics["final_arm_validation_count"] == 1


def test_final_arm_validation_validated_when_relaxed_traces_converge() -> None:
    nodes = _validation_nodes()
    roads = _validation_roads(same_terminal=True)
    initial = (
        _validation_initial("A1", "T1", "s1"),
        _validation_initial("A2", "T2", "s2"),
    )
    final = (_validation_final(("A1", "A2")),)
    traces = (_validation_trace("A1", "T1", "s1"), _validation_trace("A2", "T2", "s2"))

    result = build_final_arm_validation(
        dataset="SWSD",
        junction_id="C",
        current_group_id="C",
        groups=_validation_groups(nodes),
        nodes=nodes,
        roads=roads,
        initial_arms=initial,
        final_arms=final,
        traces=traces,
        excluded_road_ids=set(),
        internal_road_ids=set(),
    )

    validation = result.validations[0]
    assert validation.validation_status == "validated"
    assert validation.convergence_status == "same_semantic_junction"
    assert validation.relaxed_trace_terminal_junction_ids == ("X",)
    assert result.final_arms[0].validation_confidence == "high"


def test_final_arm_validation_continues_through_clear_transition_junction() -> None:
    nodes = {
        "C": NodeRecord("C", "C", "4", Point(0.0, 0.0)),
        "X": NodeRecord("X", "X", "4", Point(40.0, 0.0)),
        "T": NodeRecord("T", "T", "4", Point(20.0, 1.0)),
        "S": NodeRecord("S", None, "1", Point(20.0, 20.0)),
    }
    roads = {
        "s1": RoadRecord("s1", "C", "X", 2, "0", LineString([(0.0, 0.0), (40.0, 0.0)])),
        "s2": RoadRecord("s2", "C", "T", 2, "0", LineString([(0.0, 1.0), (20.0, 1.0)])),
        "c2": RoadRecord("c2", "T", "X", 2, "0", LineString([(20.0, 1.0), (40.0, 0.0)])),
        "side": RoadRecord("side", "T", "S", 2, "0", LineString([(20.0, 1.0), (20.0, 20.0)])),
    }
    initial = (
        _validation_initial("A1", "X", "s1"),
        _validation_initial("A2", "T", "s2"),
    )
    final = (_validation_final(("A1", "A2")),)
    traces = (_validation_trace("A1", "X", "s1"), _validation_trace("A2", "T", "s2"))

    result = build_final_arm_validation(
        dataset="SWSD",
        junction_id="C",
        current_group_id="C",
        groups=_validation_groups(nodes),
        nodes=nodes,
        roads=roads,
        initial_arms=initial,
        final_arms=final,
        traces=traces,
        excluded_road_ids=set(),
        internal_road_ids=set(),
    )

    validation = result.validations[0]
    assert validation.validation_status == "validated"
    assert validation.relaxed_trace_terminal_junction_ids == ("X",)
    assert validation.relaxed_trace_road_ids_by_initial_arm["A2"] == ("c2", "s2")


def test_final_arm_validation_refines_weak_transition_to_unique_strong_terminal() -> None:
    nodes = {
        "C": NodeRecord("C", "C", "4", Point(0.0, 0.0)),
        "X": NodeRecord("X", "X", "4", Point(40.0, 0.0)),
        "X2": NodeRecord("X2", "X", "0", Point(40.0, 1.0)),
        "X3": NodeRecord("X3", "X", "0", Point(41.0, 0.0)),
        "W": NodeRecord("W", None, "8", Point(20.0, 0.0)),
        "Q": NodeRecord("Q", None, "1", Point(40.0, 1.0)),
    }
    roads = {
        "s1": RoadRecord("s1", "C", "X", 2, "0", LineString([(0.0, 0.0), (40.0, 0.0)])),
        "s2": RoadRecord("s2", "C", "W", 2, "0", LineString([(0.0, 1.0), (20.0, 0.0)])),
        "to_x": RoadRecord("to_x", "W", "X", 2, "0", LineString([(20.0, 0.0), (40.0, 0.0)])),
        "to_q": RoadRecord("to_q", "W", "Q", 2, "0", LineString([(20.0, 0.0), (40.0, 1.0)])),
    }
    initial = (
        _validation_initial("A1", "X", "s1"),
        _validation_initial("A2", "W", "s2"),
    )
    final = (_validation_final(("A1", "A2")),)
    traces = (_validation_trace("A1", "X", "s1"), _validation_trace("A2", "W", "s2"))

    result = build_final_arm_validation(
        dataset="SWSD",
        junction_id="C",
        current_group_id="C",
        groups=_validation_groups(nodes),
        nodes=nodes,
        roads=roads,
        initial_arms=initial,
        final_arms=final,
        traces=traces,
        excluded_road_ids=set(),
        internal_road_ids=set(),
    )

    validation = result.validations[0]
    assert validation.validation_status == "validated"
    assert validation.relaxed_trace_terminal_junction_ids == ("X",)
    assert "relaxed_trace_weak_terminal_refined" in validation.risk_flags


def test_final_arm_validation_consensus_target_allows_same_final_arm_current_bridge() -> None:
    nodes = {
        "C": NodeRecord("C", "C", "4", Point(0.0, 0.0)),
        "X": NodeRecord("X", "X", "4", Point(30.0, 0.0)),
        "X2": NodeRecord("X2", "X", "0", Point(30.0, 1.0)),
        "X3": NodeRecord("X3", "X", "0", Point(31.0, 0.0)),
        "W": NodeRecord("W", None, "8", Point(0.0, 10.0)),
    }
    roads = {
        "s1": RoadRecord("s1", "C", "X", 2, "0", LineString([(0.0, 0.0), (30.0, 0.0)])),
        "s2": RoadRecord("s2", "C", "W", 2, "0", LineString([(0.0, 0.0), (0.0, 10.0)])),
    }
    initial = (
        _validation_initial("A1", "X", "s1"),
        _validation_initial("A2", "W", "s2"),
    )

    result = build_final_arm_validation(
        dataset="SWSD",
        junction_id="C",
        current_group_id="C",
        groups=_validation_groups(nodes),
        nodes=nodes,
        roads=roads,
        initial_arms=initial,
        final_arms=(_validation_final(("A1", "A2")),),
        traces=(_validation_trace("A1", "X", "s1"), _validation_trace("A2", "W", "s2")),
        excluded_road_ids=set(),
        internal_road_ids=set(),
    )

    validation = result.validations[0]
    assert validation.validation_status == "validated"
    assert validation.relaxed_trace_terminal_junction_ids == ("X",)
    assert "relaxed_trace_consensus_target_convergence" in validation.risk_flags


def test_final_arm_validation_weak_validated_for_same_dead_end_terminal() -> None:
    nodes = _validation_nodes()
    roads = _validation_roads(include_continuations=False)
    initial = (
        _validation_initial("A1", "D", "s1", terminal_type="dead_end"),
        _validation_initial("A2", "D", "s2", terminal_type="dead_end"),
    )
    final = (_validation_final(("A1", "A2")),)
    traces = (
        _validation_trace("A1", "D", "s1", stop_type="dead_end"),
        _validation_trace("A2", "D", "s2", stop_type="dead_end"),
    )

    result = build_final_arm_validation(
        dataset="SWSD",
        junction_id="C",
        current_group_id="C",
        groups=_validation_groups(nodes),
        nodes=nodes,
        roads=roads,
        initial_arms=initial,
        final_arms=final,
        traces=traces,
        excluded_road_ids=set(),
        internal_road_ids=set(),
    )

    validation = result.validations[0]
    assert validation.validation_status == "weak_validated"
    assert validation.convergence_status in {"same_terminal_boundary", "partial_same_corridor"}
    assert "final_arm_validation_weak" in validation.issue_flags


def test_final_arm_validation_unvalidated_when_source_trace_missing() -> None:
    nodes = _validation_nodes()
    roads = _validation_roads()
    initial = (
        _validation_initial("A1", "T1", "s1"),
        _validation_initial("A2", "", "s2"),
    )
    final = (_validation_final(("A1", "A2")),)
    traces = (_validation_trace("A1", "T1", "s1"),)

    result = build_final_arm_validation(
        dataset="SWSD",
        junction_id="C",
        current_group_id="C",
        groups=_validation_groups(nodes),
        nodes=nodes,
        roads=roads,
        initial_arms=initial,
        final_arms=final,
        traces=traces,
        excluded_road_ids=set(),
        internal_road_ids=set(),
    )

    validation = result.validations[0]
    assert validation.validation_status == "unvalidated"
    assert "final_arm_validation_unvalidated" in validation.issue_flags
    assert result.issues[0]["issue_type"] == "final_arm_validation_unvalidated"


def test_final_arm_validation_conflict_when_relaxed_terminals_differ() -> None:
    nodes = _validation_nodes(same_terminal=False)
    roads = _validation_roads(same_terminal=False)
    initial = (
        _validation_initial("A1", "T1", "s1"),
        _validation_initial("A2", "T2", "s2"),
    )
    final = (_validation_final(("A1", "A2")),)
    traces = (_validation_trace("A1", "T1", "s1"), _validation_trace("A2", "T2", "s2"))

    result = build_final_arm_validation(
        dataset="SWSD",
        junction_id="C",
        current_group_id="C",
        groups=_validation_groups(nodes),
        nodes=nodes,
        roads=roads,
        initial_arms=initial,
        final_arms=final,
        traces=traces,
        excluded_road_ids=set(),
        internal_road_ids=set(),
    )

    validation = result.validations[0]
    assert validation.validation_status == "conflict"
    assert validation.convergence_status == "conflicting_terminals"
    assert validation.confidence == "none"
    assert "final_arm_validation_conflict" in validation.issue_flags


def test_seed_first_hop_non_kind4_continues_by_forward_rule(tmp_path: Path) -> None:
    nodes_path = tmp_path / "single_road_nodes.gpkg"
    roads_path = tmp_path / "single_road_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("J", None, 20.0, 0.0, "8"),
            ("D", None, 40.0, 0.0, "1"),
            ("S", None, 20.0, 20.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("seed", "C", "J", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("continue", "J", "D", 2, "0", [(20.0, 0.0), (40.0, 0.0)]),
            ("side", "J", "S", 2, "0", [(20.0, 0.0), (20.0, 20.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})
    trace = next(item for item in result.traces if item.seed_road_id == "seed")

    assert "first_hop_non_minor_kind_terminal" not in trace.stop_reason
    assert trace.traced_road_ids[:2] == ("seed", "continue")
    assert trace.through_decisions[0] == "t_mainline_through"
    assert trace.traced_node_ids[0] == "J"


def test_seed_first_hop_non_minor_kind_continues_when_entry_node_is_not_three_degree(tmp_path: Path) -> None:
    nodes_path = tmp_path / "non_three_degree_nodes.gpkg"
    roads_path = tmp_path / "non_three_degree_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("J", None, 20.0, 0.0, "8"),
            ("D", None, 40.0, 0.0, "4"),
            ("D2", "D", 40.0, 1.0, "0"),
            ("D3", "D", 41.0, 0.0, "0"),
            ("E1", None, 60.0, 0.0, "1"),
            ("E2", None, 40.0, 20.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("seed", "C", "J", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("continue", "J", "D", 2, "0", [(20.0, 0.0), (40.0, 0.0)]),
            ("d_side_1", "D", "E1", 2, "0", [(40.0, 0.0), (60.0, 0.0)]),
            ("d_side_2", "D", "E2", 2, "0", [(40.0, 0.0), (40.0, 20.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})
    trace = next(item for item in result.traces if item.seed_road_id == "seed")

    assert "first_hop_non_minor_kind_terminal" not in trace.stop_reason
    assert trace.traced_road_ids[:2] == ("seed", "continue")
    assert trace.through_decisions[0] == "simple_through"
    assert trace.traced_node_ids[0] == "J"
    assert trace.stop_type != "semantic_boundary" or trace.stop_reason != "first_hop_non_minor_kind_terminal|kind=8"


def test_p01_arm_build_outputs_multi_group_review_artifacts(tmp_path: Path) -> None:
    out_root = tmp_path / "out"
    assert run_p01_arm_build_from_args(_run_args(tmp_path, out_root)) == 0

    run_root = out_root / "test_run"
    assert (run_root / "preflight.json").is_file()
    assert (run_root / "p01_arm_build_summary.json").is_file()
    assert (run_root / "p01_arm_build_review_index.csv").is_file()
    assert (run_root / "cases" / "group_0001" / "case_input.json").is_file()
    assert (run_root / "cases" / "group_0002" / "case_summary.json").is_file()

    swsd_dir = run_root / "cases" / "group_0001" / "SWSD"
    context = json.loads((swsd_dir / "junction_context.json").read_text(encoding="utf-8"))
    assert context["member_node_ids"] == ["S1", "S1b"]
    assert context["internal_road_ids"] == ["S1_internal"]
    assert context["excluded_right_turn_road_ids"] == []
    assert context["advance_right_turn_road_ids"] == ["S1_right_turn"]
    assert context["formway_missing_road_ids"] == []
    assert context["formway_unparseable_road_ids"] == []

    initial_arms = json.loads((swsd_dir / "initial_arms.json").read_text(encoding="utf-8"))
    assert len(initial_arms) == 4
    assert any("S1_east_continue" in arm["connector_road_ids"] for arm in initial_arms)
    assert all("S1_right_turn" not in arm["member_road_ids"] for arm in initial_arms)
    assert all("trunk_status" in arm for arm in initial_arms)
    assert all("S1_right_turn" not in arm["trunk_road_ids"] for arm in initial_arms)
    final_arms = json.loads((swsd_dir / "final_arms.json").read_text(encoding="utf-8"))
    assert all("validation_status" in arm for arm in final_arms)
    validations = json.loads((swsd_dir / "final_arm_validation.json").read_text(encoding="utf-8"))
    assert len(validations) == len(final_arms)
    assert all(item["validation_status"] in {"not_required", "validated", "weak_validated", "unvalidated", "conflict"} for item in validations)

    advance_right_relations = json.loads((swsd_dir / "advance_right_turn_relations.json").read_text(encoding="utf-8"))
    assert len(advance_right_relations) == 1
    assert advance_right_relations[0]["advance_right_turn_road_ids"] == ["S1_right_turn"]
    assert advance_right_relations[0]["trace_status"] in {"target_arm_not_found", "ambiguous", "partial", "resolved"}
    assert (swsd_dir / "arm_movements.json").is_file()
    assert (swsd_dir / "road_movement_evidence.json").is_file()
    assert (swsd_dir / "arm_receiving_road_roles.json").is_file()
    assert (swsd_dir / "trunk_corrections.json").is_file()
    assert (swsd_dir / "corrected_final_arms.json").is_file()
    corrected_final_arms = json.loads((swsd_dir / "corrected_final_arms.json").read_text(encoding="utf-8"))
    assert all("validation_status" in item["final_arm"] for item in corrected_final_arms)
    trunk_corrections = json.loads((swsd_dir / "trunk_corrections.json").read_text(encoding="utf-8"))
    assert {item["trunk_correction_status"] for item in trunk_corrections} == {
        "not_evaluated_no_road_next_road_input"
    }

    local_candidates = json.loads((swsd_dir / "local_arm_candidates.json").read_text(encoding="utf-8"))
    assert len(local_candidates) == 4
    assert all("S1_right_turn" not in item["source_seed_road_ids"] for item in local_candidates)
    assert any(item["local_stub_road_ids"] == ["S1_east_continue", "S1_east_seed"] for item in local_candidates)

    decisions = json.loads((swsd_dir / "through_decisions.json").read_text(encoding="utf-8"))
    assert any(decision["status"] == "simple_through" for decision in decisions)
    assert any(decision["status"] == "dead_end" for decision in decisions)

    assert not (swsd_dir / "p01_arm_review.png").exists()
    assert not (swsd_dir / "p01_arm_movement_turn_audit.png").exists()
    assert (swsd_dir / "review_layers.gpkg").is_file()
    rcsd_dir = run_root / "cases" / "group_0001" / "RCSD"
    assert not (rcsd_dir / "p01_arm_review.png").exists()
    assert not (rcsd_dir / "p01_arm_movement_turn_audit.png").exists()
    frcsd_dir = run_root / "cases" / "group_0001" / "FRCSD"
    assert not (frcsd_dir / "p01_arm_review.png").exists()
    assert (frcsd_dir / "p01_arm_movement_turn_audit.png").is_file()
    assert (frcsd_dir / "frcsd_road_next_road.geojson").is_file()
    assert (frcsd_dir / "frcsd_source_road_map.json").is_file()
    assert (frcsd_dir / "source_movement_policy_swsd.json").is_file()
    assert (frcsd_dir / "source_movement_policy_rcsd.json").is_file()
    assert (frcsd_dir / "arm_source_profiles.json").is_file()
    assert (frcsd_dir / "source_arm_pass_rules_swsd.json").is_file()
    assert (frcsd_dir / "source_arm_pass_rules_rcsd.json").is_file()
    assert (frcsd_dir / "final_generation_decisions.json").is_file()
    assert (frcsd_dir / "parallel_branch_alignment.json").is_file()
    assert (frcsd_dir / "frcsd_road_next_road_audit.json").is_file()
    assert (frcsd_dir / "frcsd_road_next_road_issue_report.json").is_file()
    assert (frcsd_dir / "frcsd_road_next_road_review_layers.gpkg").is_file()
    assert not (frcsd_dir / "frcsd_road_next_road_review.png").exists()
    assert (frcsd_dir / "frcsd_pass_capability_audit.png").is_file()
    assert not (run_root / "cases" / "group_0001" / "compare" / "p01_arm_compare.png").exists()
    assert (run_root / "cases" / "group_0001" / "compare" / "p01_arm_compare_layers.gpkg").is_file()
    case_summary = json.loads((run_root / "cases" / "group_0001" / "case_summary.json").read_text(encoding="utf-8"))
    assert case_summary["datasets"]["FRCSD"]["frcsd_generated_road_next_road_count"] >= 0
    assert case_summary["dataset_outputs"]["FRCSD"]["frcsd_road_next_road_review_png_path"] is None
    assert case_summary["compare_outputs"]["compare_png_path"] is None
    assert "trace_review_png_paths" not in case_summary
    assert not (run_root / "cases" / "group_0001" / "trace_review").exists()
    assert set(fiona.listlayers(swsd_dir / "review_layers.gpkg")) >= {
        "current_junction_nodes",
        "arm_roads",
        "local_arm_candidate_roads",
        "through_decision_nodes",
        "excluded_right_turn_roads",
        "advance_left_turn_roads",
        "advance_right_turn_roads",
        "arm_trunk_roads",
        "advance_right_turn_relations",
        "arm_movements",
        "road_movement_evidence",
        "straight_receiving_roads",
        "advance_left_receiving_roads",
        "trunk_excluded_by_movement_roads",
        "corrected_trunk_roads",
        "final_arm_validation",
        "relaxed_trace_roads",
        "relaxed_trace_terminals",
        "special_formway_issue_points",
    }

    with (run_root / "p01_arm_build_review_index.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 6
    assert {row["junction_group_id"] for row in rows} == {"group_0001", "group_0002"}
    assert {row["dataset"] for row in rows} == {"SWSD", "RCSD", "FRCSD"}
    assert all(row["review_priority"] in {"P0", "P1", "P2", "P3"} for row in rows)
    assert all("advance_right_turn_road_count" in row for row in rows)
    assert all("trunk_partial_count" in row for row in rows)
    assert all("arm_movement_count" in row for row in rows)
    assert all("final_arm_validation_count" in row for row in rows)
    assert all("final_arm_validation_conflict_count" in row for row in rows)
    assert all("trunk_correction_count" in row for row in rows)
    assert all("frcsd_generated_road_next_road_count" in row for row in rows)
    assert all("frcsd_rule_projected_count" in row for row in rows)
    assert all("frcsd_data_error_partial_target_coverage_count" in row for row in rows)
    assert all("frcsd_parallel_branch_alignment_count" in row for row in rows)


def test_advance_right_turn_bit7_is_detected_without_explicit_field_value(tmp_path: Path) -> None:
    out_root = tmp_path / "out_no_rt"
    assert run_p01_arm_build_from_args(_run_args(tmp_path, out_root, include_right_turn_value=False)) == 0
    context = json.loads(
        (out_root / "test_run" / "cases" / "group_0001" / "SWSD" / "junction_context.json").read_text(
            encoding="utf-8"
        )
    )
    assert context["excluded_right_turn_road_ids"] == []
    assert context["advance_right_turn_road_ids"] == ["S1_right_turn"]
    initial_arms = json.loads(
        (out_root / "test_run" / "cases" / "group_0001" / "SWSD" / "initial_arms.json").read_text(
            encoding="utf-8"
        )
    )
    assert all("S1_right_turn" not in arm["seed_road_ids"] for arm in initial_arms)
    assert all("S1_right_turn" not in arm["member_road_ids"] for arm in initial_arms)


def test_advance_left_turn_bit8_stays_in_arm_but_not_trunk(tmp_path: Path) -> None:
    nodes_path = tmp_path / "adv_left_nodes.gpkg"
    roads_path = tmp_path / "adv_left_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
            ("L", None, 40.0, 10.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("in", "N", "C", 2, "0", [(0.0, 20.0), (0.0, 0.0)]),
            ("out", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("adv_left", "E", "L", 2, "256", [(20.0, 0.0), (40.0, 10.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert "adv_left" in result.context.advance_left_turn_road_ids
    arm = next(item for item in result.initial_arms if "adv_left" in item.member_road_ids)
    assert arm.has_advance_left_turn is True
    assert arm.advance_left_turn_road_ids == ("adv_left",)
    assert "adv_left" not in arm.trunk_road_ids
    assert "adv_left" in arm.non_trunk_member_road_ids


def test_advance_right_turn_relation_resolves_to_outbound_arm(tmp_path: Path) -> None:
    nodes_path = tmp_path / "adv_right_nodes.gpkg"
    roads_path = tmp_path / "adv_right_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
            ("M", None, 20.0, -12.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("in", "N", "C", 2, "0", [(0.0, 20.0), (0.0, 0.0)]),
            ("out", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("adv_right", "C", "M", 2, "128", [(0.0, 0.0), (20.0, -12.0)]),
            ("adv_right_link", "M", "E", 2, "0", [(20.0, -12.0), (20.0, 0.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert "adv_right" in result.context.advance_right_turn_road_ids
    assert all("adv_right" not in arm.member_road_ids for arm in result.initial_arms)
    assert len(result.advance_right_turn_relations) == 1
    relation = result.advance_right_turn_relations[0]
    assert relation.trace_status == "resolved"
    assert relation.from_arm_id
    assert relation.to_arm_id
    assert relation.advance_right_turn_road_ids == ("adv_right",)
    assert relation.trace_road_ids[:2] == ("adv_right", "adv_right_link")
    assert any(relation.relation_id in arm.advance_right_turn_relation_ids for arm in result.initial_arms)


def test_advance_right_turn_adjacent_to_seed_outside_node_is_detected(tmp_path: Path) -> None:
    nodes_path = tmp_path / "adjacent_adv_right_nodes.gpkg"
    roads_path = tmp_path / "adjacent_adv_right_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("in", "N", "C", 2, "0", [(0.0, 20.0), (0.0, 0.0)]),
            ("out", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("adjacent_adv_right", "N", "E", 2, "128", [(0.0, 20.0), (20.0, 0.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert result.context.advance_right_turn_road_ids == ("adjacent_adv_right",)
    assert all("adjacent_adv_right" not in arm.member_road_ids for arm in result.initial_arms)
    assert len(result.advance_right_turn_relations) == 1
    relation = result.advance_right_turn_relations[0]
    assert relation.trace_status == "resolved"
    assert relation.advance_right_turn_road_ids == ("adjacent_adv_right",)
    assert relation.from_arm_id
    assert relation.to_arm_id


def test_contiguous_advance_right_turn_roads_form_one_relation(tmp_path: Path) -> None:
    nodes_path = tmp_path / "chain_adv_right_nodes.gpkg"
    roads_path = tmp_path / "chain_adv_right_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("M", None, 12.0, 12.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("in", "N", "C", 2, "0", [(0.0, 20.0), (0.0, 0.0)]),
            ("out", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("adv_right_1", "N", "M", 2, "128", [(0.0, 20.0), (12.0, 12.0)]),
            ("adv_right_2", "M", "E", 2, "128", [(12.0, 12.0), (20.0, 0.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert result.context.advance_right_turn_road_ids == ("adv_right_1", "adv_right_2")
    assert len(result.advance_right_turn_relations) == 1
    relation = result.advance_right_turn_relations[0]
    assert relation.trace_status == "resolved"
    assert relation.advance_right_turn_road_ids == ("adv_right_1", "adv_right_2")
    assert relation.trace_road_ids[:3] == ("adv_right_1", "adv_right_2", "out")
    assert all("adv_right_1" not in arm.member_road_ids for arm in result.initial_arms)
    assert all("adv_right_2" not in arm.member_road_ids for arm in result.initial_arms)


def test_trunk_falls_back_to_local_non_special_seed_roads(tmp_path: Path) -> None:
    nodes_path = tmp_path / "local_trunk_nodes.gpkg"
    roads_path = tmp_path / "local_trunk_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
            ("L", None, 40.0, 10.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("in", "N", "C", 2, "0", [(0.0, 20.0), (0.0, 0.0)]),
            ("out", "C", "E", 2, "0", [(0.0, 0.0), (20.0, 0.0)]),
            ("adv_left", "E", "L", 2, "256", [(20.0, 0.0), (40.0, 10.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert any(arm.trunk_road_ids for arm in result.initial_arms)
    for arm in result.initial_arms:
        assert "adv_left" not in arm.trunk_road_ids
        if set(arm.seed_road_ids) & {"in", "out"}:
            assert arm.trunk_status == "partial"
            assert set(arm.trunk_road_ids) <= {"in", "out"}


def test_formway_missing_and_unparseable_are_audited(tmp_path: Path) -> None:
    nodes_path = tmp_path / "formway_nodes.gpkg"
    roads_path = tmp_path / "formway_roads.gpkg"
    _write_nodes(
        nodes_path,
        [
            ("C", "C", 0.0, 0.0, "4"),
            ("N", None, 0.0, 20.0, "1"),
            ("E", None, 20.0, 0.0, "1"),
        ],
    )
    _write_roads(
        roads_path,
        [
            ("missing_formway", "N", "C", 2, "", [(0.0, 20.0), (0.0, 0.0)]),
            ("bad_formway", "C", "E", 2, "abc", [(0.0, 0.0), (20.0, 0.0)]),
        ],
    )
    loaded = load_dataset(DatasetInput("SWSD", nodes_path, roads_path))

    result = build_dataset_arm_result(loaded, junction_id="C", right_turn_formway_values={"128"})

    assert result.context.formway_missing_road_ids == ("missing_formway",)
    assert result.context.formway_unparseable_road_ids == ("bad_formway",)
    assert result.issue_report.issue_counts["formway_missing"] == 1
    assert result.issue_report.issue_counts["formway_unparseable"] == 1
    assert result.metrics["formway_missing_count"] == 1
    assert result.metrics["formway_unparseable_count"] == 1
