from __future__ import annotations

from tests.modules.t01_data_preprocess.step2_segment_test_support import *  # noqa: F401,F403


def test_build_candidate_channel_stops_at_local_branching_corridor_for_trunk_search() -> None:
    def _edge(road_id: str, from_node: str, to_node: str) -> step1_pair_poc.TraversalEdge:
        return step1_pair_poc.TraversalEdge(road_id=road_id, from_node=from_node, to_node=to_node)

    pair = step1_pair_poc.PairRecord(
        pair_id="S2X:A__B",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "B"),
        forward_path_road_ids=("trunk",),
        reverse_path_node_ids=("B", "A"),
        reverse_path_road_ids=("trunk",),
        through_node_ids=(),
    )
    undirected_adjacency = {
        "A": (_edge("trunk", "A", "B"), _edge("r1", "A", "N1")),
        "B": (_edge("trunk", "B", "A"), _edge("r3", "B", "N2")),
        "N1": (_edge("r1", "N1", "A"), _edge("r2", "N1", "N2"), _edge("b1", "N1", "X")),
        "N2": (
            _edge("r2", "N2", "N1"),
            _edge("r3", "N2", "B"),
            _edge("b2", "N2", "X"),
            _edge("leaf", "N2", "L"),
        ),
        "X": (_edge("b1", "X", "N1"), _edge("b2", "X", "N2")),
        "L": (_edge("leaf", "L", "N2"),),
    }

    candidate_road_ids, boundary_terminate_ids = step2_segment_poc._build_candidate_channel(
        pair,
        undirected_adjacency=undirected_adjacency,
        boundary_node_ids=set(),
    )

    assert candidate_road_ids == {"trunk", "r1", "r3"}
    assert boundary_terminate_ids == set()


def test_build_segment_body_candidate_channel_continues_through_local_branching_corridor() -> None:
    def _edge(road_id: str, from_node: str, to_node: str) -> step1_pair_poc.TraversalEdge:
        return step1_pair_poc.TraversalEdge(road_id=road_id, from_node=from_node, to_node=to_node)

    pair = step1_pair_poc.PairRecord(
        pair_id="S2X:A__B",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "B"),
        forward_path_road_ids=("trunk",),
        reverse_path_node_ids=("B", "A"),
        reverse_path_road_ids=("trunk",),
        through_node_ids=(),
    )
    undirected_adjacency = {
        "A": (_edge("trunk", "A", "B"), _edge("r1", "A", "N1")),
        "B": (_edge("trunk", "B", "A"), _edge("r3", "B", "N2")),
        "N1": (_edge("r1", "N1", "A"), _edge("r2", "N1", "N2"), _edge("b1", "N1", "X")),
        "N2": (
            _edge("r2", "N2", "N1"),
            _edge("r3", "N2", "B"),
            _edge("b2", "N2", "X"),
            _edge("leaf", "N2", "L"),
        ),
        "X": (_edge("b1", "X", "N1"), _edge("b2", "X", "N2")),
        "L": (_edge("leaf", "L", "N2"),),
    }
    road_endpoints = {
        "trunk": ("A", "B"),
        "r1": ("A", "N1"),
        "r2": ("N1", "N2"),
        "r3": ("N2", "B"),
        "b1": ("N1", "X"),
        "b2": ("N2", "X"),
        "leaf": ("N2", "L"),
    }

    candidate_road_ids = step2_segment_poc._build_segment_body_candidate_channel(
        pair,
        trunk_road_ids=("trunk",),
        undirected_adjacency=undirected_adjacency,
        boundary_node_ids=set(),
        road_endpoints=road_endpoints,
    )

    assert candidate_road_ids == {"trunk", "r1", "r2", "r3", "b1", "b2", "leaf"}


def test_build_segment_body_candidate_channel_drops_single_attachment_branch_component() -> None:
    def _edge(road_id: str, from_node: str, to_node: str) -> step1_pair_poc.TraversalEdge:
        return step1_pair_poc.TraversalEdge(road_id=road_id, from_node=from_node, to_node=to_node)

    pair = step1_pair_poc.PairRecord(
        pair_id="S2X:A__B",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "B"),
        forward_path_road_ids=("trunk",),
        reverse_path_node_ids=("B", "A"),
        reverse_path_road_ids=("trunk",),
        through_node_ids=(),
    )
    undirected_adjacency = {
        "A": (_edge("trunk", "A", "B"), _edge("spur1", "A", "N1")),
        "B": (_edge("trunk", "B", "A"),),
        "N1": (_edge("spur1", "N1", "A"), _edge("spur2", "N1", "N2")),
        "N2": (_edge("spur2", "N2", "N1"),),
    }
    road_endpoints = {
        "trunk": ("A", "B"),
        "spur1": ("A", "N1"),
        "spur2": ("N1", "N2"),
    }

    candidate_road_ids = step2_segment_poc._build_segment_body_candidate_channel(
        pair,
        trunk_road_ids=("trunk",),
        undirected_adjacency=undirected_adjacency,
        boundary_node_ids=set(),
        road_endpoints=road_endpoints,
    )

    assert candidate_road_ids == {"trunk"}


def test_build_segment_body_candidate_channel_respects_allowed_road_ids() -> None:
    def _edge(road_id: str, from_node: str, to_node: str) -> step1_pair_poc.TraversalEdge:
        return step1_pair_poc.TraversalEdge(road_id=road_id, from_node=from_node, to_node=to_node)

    pair = step1_pair_poc.PairRecord(
        pair_id="S2X:A__B",
        a_node_id="A",
        b_node_id="B",
        strategy_id="S2X",
        reverse_confirmed=True,
        forward_path_node_ids=("A", "B"),
        forward_path_road_ids=("trunk",),
        reverse_path_node_ids=("B", "A"),
        reverse_path_road_ids=("trunk",),
        through_node_ids=(),
    )
    undirected_adjacency = {
        "A": (_edge("trunk", "A", "B"), _edge("r1", "A", "N1")),
        "B": (_edge("trunk", "B", "A"), _edge("r3", "B", "N2"), _edge("spill", "B", "Z1")),
        "N1": (_edge("r1", "N1", "A"), _edge("r2", "N1", "N2")),
        "N2": (_edge("r2", "N2", "N1"), _edge("r3", "N2", "B")),
        "Z1": (_edge("spill", "Z1", "B"), _edge("spill2", "Z1", "Z2")),
        "Z2": (_edge("spill2", "Z2", "Z1"),),
    }
    road_endpoints = {
        "trunk": ("A", "B"),
        "r1": ("A", "N1"),
        "r2": ("N1", "N2"),
        "r3": ("N2", "B"),
        "spill": ("B", "Z1"),
        "spill2": ("Z1", "Z2"),
    }

    candidate_road_ids = step2_segment_poc._build_segment_body_candidate_channel(
        pair,
        trunk_road_ids=("trunk",),
        undirected_adjacency=undirected_adjacency,
        boundary_node_ids=set(),
        road_endpoints=road_endpoints,
        allowed_road_ids={"trunk", "r1", "r2", "r3"},
    )

    assert candidate_road_ids == {"trunk", "r1", "r2", "r3"}


def test_expand_segment_body_allowed_road_ids_recovers_local_bridge_component() -> None:
    def _edge(road_id: str, from_node: str, to_node: str) -> step1_pair_poc.TraversalEdge:
        return step1_pair_poc.TraversalEdge(road_id=road_id, from_node=from_node, to_node=to_node)

    undirected_adjacency = {
        "A": (_edge("trunk", "A", "B"), _edge("r1", "A", "N1")),
        "B": (_edge("trunk", "B", "A"), _edge("r3", "B", "N2")),
        "N1": (_edge("r1", "N1", "A"), _edge("r2", "N1", "N2")),
        "N2": (
            _edge("r2", "N2", "N1"),
            _edge("r3", "N2", "B"),
            _edge("leaf", "N2", "L"),
        ),
        "L": (_edge("leaf", "L", "N2"),),
    }
    road_endpoints = {
        "trunk": ("A", "B"),
        "r1": ("A", "N1"),
        "r2": ("N1", "N2"),
        "r3": ("N2", "B"),
        "leaf": ("N2", "L"),
    }

    allowed_road_ids = step2_segment_poc._expand_segment_body_allowed_road_ids(
        pruned_road_ids={"trunk"},
        branch_cut_infos=[
            {"road_id": "r1", "cut_reason": "branch_backtrack_prune", "from_node_id": "N1", "to_node_id": "A"},
            {"road_id": "r3", "cut_reason": "branch_backtrack_prune", "from_node_id": "N2", "to_node_id": "B"},
        ],
        undirected_adjacency=undirected_adjacency,
        boundary_node_ids=set(),
        road_endpoints=road_endpoints,
    )

    assert allowed_road_ids == {"trunk", "r1", "r2", "r3"}


def test_alternative_trunk_only_road_ids_returns_roads_unique_to_other_choices() -> None:
    candidate_direct = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(node_ids=("A", "B"), road_ids=("direct",), total_length=1.0),
        reverse_path=step2_segment_poc.DirectedPath(node_ids=("B", "A"), road_ids=("direct",), total_length=1.0),
        road_ids=("direct",),
        signed_area=0.0,
        total_length=2.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=0.0,
        is_bidirectional_minimal_loop=True,
    )
    candidate_loop = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(node_ids=("A", "C", "B"), road_ids=("up", "cross"), total_length=2.0),
        reverse_path=step2_segment_poc.DirectedPath(node_ids=("B", "A"), road_ids=("direct",), total_length=1.0),
        road_ids=("cross", "direct", "up"),
        signed_area=5.0,
        total_length=3.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=0.0,
    )
    trunk_choices = [
        step2_segment_poc._TrunkEvaluationChoice(candidate=candidate_direct, warning_codes=(), support_info={}),
        step2_segment_poc._TrunkEvaluationChoice(candidate=candidate_loop, warning_codes=(), support_info={}),
    ]

    assert step2_segment_poc._alternative_trunk_only_road_ids(trunk_choices, current_choice_index=0) == {"cross", "up"}
    assert step2_segment_poc._alternative_trunk_only_road_ids(trunk_choices, current_choice_index=1) == set()


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
    branch_cut = _load_json(out_root / "S2X" / "branch_cut_roads.gpkg")
    trunk = _load_json(out_root / "S2X" / "trunk_roads.gpkg")
    segment_body = _load_json(out_root / "S2X" / "segment_body_roads.gpkg")
    residual = _load_json(out_root / "S2X" / "step3_residual_roads.gpkg")
    trunk_members = _load_json(out_root / "S2X" / "trunk_road_members.gpkg")
    segment_members = _load_json(out_root / "S2X" / "segment_body_road_members.gpkg")
    endpoint_pool_rows = _read_csv_rows(out_root / "S2X" / "endpoint_pool.csv")

    assert [row["pair_id"] for row in candidate_rows] == ["S2X:1__3"]
    assert [row["pair_id"] for row in validated_rows] == ["S2X:1__3"]
    assert validation_rows[0]["validated_status"] == "validated"
    assert validation_rows[0]["reject_reason"] == ""
    assert summary["candidate_pair_count"] == 1
    assert summary["validated_pair_count"] == 1
    assert summary["prune_branch_count"] == 1
    assert summary["branch_cut_component_count"] == 1
    assert summary["other_terminate_cut_count"] == 1
    assert summary["residual_component_count"] == 1
    assert {feature["properties"]["road_id"] for feature in branch_cut["features"]} == {"r25"}
    assert len(trunk["features"]) == 1
    assert len(segment_body["features"]) == 1
    assert len(residual["features"]) == 1
    assert trunk["features"][0]["geometry"]["type"] == "MultiLineString"
    assert segment_body["features"][0]["geometry"]["type"] == "MultiLineString"
    assert set(trunk["features"][0]["properties"]["road_ids"]) == {"r14", "r43", "r32", "r21"}
    assert set(segment_body["features"][0]["properties"]["road_ids"]) == {"r14", "r43", "r32", "r21"}
    assert residual["features"][0]["geometry"]["type"] == "MultiLineString"
    assert set(residual["features"][0]["properties"]["road_ids"]) == {"r46", "r62"}
    trunk_member_ids = {feature["properties"]["road_id"] for feature in trunk_members["features"]}
    segment_member_ids = {feature["properties"]["road_id"] for feature in segment_members["features"]}
    assert trunk_member_ids == {"r14", "r43", "r32", "r21"}
    assert segment_member_ids == {"r14", "r43", "r32", "r21"}
    assert [row["node_id"] for row in endpoint_pool_rows] == ["1", "3", "5"]


def test_step2_rejects_dual_carriageway_separation_over_50m(tmp_path: Path) -> None:
    road_path, node_path = _build_dual_separation_exceeded_dataset(tmp_path)
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
    summary = _load_json(out_root / "S2X" / "segment_summary.json")

    assert len(validation_rows) == 1
    assert validation_rows[0]["validated_status"] == "rejected"
    assert validation_rows[0]["reject_reason"] == "dual_carriageway_separation_exceeded"
    support_info = json.loads(validation_rows[0]["support_info"])
    assert support_info["dual_carriageway_separation_gate_limit_m"] == 50.0
    assert support_info["dual_carriageway_max_separation_m"] > 50.0
    assert summary["dual_carriageway_separation_reject_count"] == 1
    assert summary["dual_carriageway_separation_gate_limit_m"] == 50.0


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
    segment_body = _load_json(out_root / "S2X" / "segment_body_roads.gpkg")
    residual = _load_json(out_root / "S2X" / "step3_residual_roads.gpkg")
    branch_cut = _load_json(out_root / "S2X" / "branch_cut_roads.gpkg")

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
    bootstrap = initialize_working_layers(
        road_path=road_path,
        node_path=node_path,
        out_root=tmp_path / "working_bridge_cycle",
    )
    context = step1_pair_poc.build_step1_graph_context(
        road_path=bootstrap.roads_path,
        node_path=bootstrap.nodes_path,
    )
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


def test_collect_segment_path_road_ids_excludes_side_cycle_attached_at_articulation() -> None:
    roads = [
        _road_record("r12", "1", "2", coords=((0.0, 0.0), (1.0, 0.0))),
        _road_record("r23", "2", "3", coords=((1.0, 0.0), (2.0, 0.0))),
        _road_record("r24", "2", "4", coords=((1.0, 0.0), (1.5, 0.5))),
        _road_record("r45", "4", "5", coords=((1.5, 0.5), (2.0, 1.0))),
        _road_record("r52", "5", "2", coords=((2.0, 1.0), (1.0, 0.0))),
    ]
    context = _minimal_context(roads)
    pair = _pair_record("S2X:1__3", "1", "3", ("r12", "r23"))
    road_endpoints = {
        "r12": ("1", "2"),
        "r23": ("2", "3"),
        "r24": ("2", "4"),
        "r45": ("4", "5"),
        "r52": ("5", "2"),
    }

    path_road_ids = step2_trunk_utils._collect_segment_path_road_ids(
        pair,
        context=context,
        road_endpoints=road_endpoints,
        allowed_road_ids=set(road_endpoints),
    )

    assert path_road_ids == {"r12", "r23"}


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
    trunk = _load_json(out_root / "S2X" / "trunk_roads.gpkg")
    segment_body = _load_json(out_root / "S2X" / "segment_body_roads.gpkg")
    residual = _load_json(out_root / "S2X" / "step3_residual_roads.gpkg")

    assert [row["pair_id"] for row in validated_rows] == ["S2X:1__3"]
    assert validated_rows[0]["trunk_mode"] == "through_collapsed_corridor"
    assert validation_rows[0]["validated_status"] == "validated"
    assert validation_rows[0]["trunk_mode"] == "through_collapsed_corridor"
    assert validation_rows[0]["counterclockwise_ok"] == "False"
    assert set(trunk["features"][0]["properties"]["road_ids"]) == {"r12", "r23"}
    assert set(segment_body["features"][0]["properties"]["road_ids"]) == {"r12", "r23"}
    assert residual["features"] == []


def test_step2_validates_step5c_mirrored_one_sided_corridor_candidate(tmp_path: Path) -> None:
    road_path, node_path = _build_step5c_mirrored_one_sided_corridor_dataset(tmp_path)
    strategy_path = tmp_path / "step5c_strategy.json"
    strategy_path.write_text(
        json.dumps(
            {
                "strategy_id": "STEP5C",
                "description": "Synthetic Step5C strategy with mirrored reverse-confirm fallback corridor.",
                "seed_rule": {"kind_bits_all": [2], "closed_con_in": [2, 3], "grade_eq": 1},
                "terminate_rule": {"kind_bits_all": [2], "closed_con_in": [2, 3], "grade_eq": 1},
                "allow_mirrored_one_sided_reverse_confirm_for_force_terminate_nodes": True,
                "through_node_rule": {
                    "incident_road_degree_eq": 2,
                    "incident_degree_exclude_formway_bits_any": [7],
                    "disallow_seed_terminate_nodes": True,
                },
                "force_seed_node_ids": [1, 4],
                "force_terminate_node_ids": [1, 4],
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

    validated_rows = _read_csv_rows(out_root / "STEP5C" / "validated_pairs.csv")
    validation_rows = _read_csv_rows(out_root / "STEP5C" / "pair_validation_table.csv")
    trunk = _load_json(out_root / "STEP5C" / "trunk_roads.gpkg")
    segment_body = _load_json(out_root / "STEP5C" / "segment_body_roads.gpkg")
    residual = _load_json(out_root / "STEP5C" / "step3_residual_roads.gpkg")

    assert [row["pair_id"] for row in validated_rows] == ["STEP5C:1__4"]
    assert validated_rows[0]["trunk_mode"] == "mirrored_one_sided_corridor"
    assert validation_rows[0]["validated_status"] == "validated"
    assert validation_rows[0]["trunk_mode"] == "mirrored_one_sided_corridor"
    assert validation_rows[0]["counterclockwise_ok"] == "False"
    assert set(trunk["features"][0]["properties"]["road_ids"]) == {"r12", "r23", "r34"}
    assert set(segment_body["features"][0]["properties"]["road_ids"]) == {"r12", "r23", "r34"}
    assert residual["features"] == []


def test_step2_validates_bidirectional_direct_road_as_minimal_loop(tmp_path: Path) -> None:
    road_path, node_path = _build_bidirectional_minimal_loop_dataset(tmp_path)
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

    validated_rows = _read_csv_rows(out_root / "S2X" / "validated_pairs.csv")
    validation_rows = _read_csv_rows(out_root / "S2X" / "pair_validation_table.csv")
    trunk = _load_json(out_root / "S2X" / "trunk_roads.gpkg")
    segment_body = _load_json(out_root / "S2X" / "segment_body_roads.gpkg")

    assert [row["pair_id"] for row in validated_rows] == ["S2X:1__2"]
    assert validation_rows[0]["validated_status"] == "validated"
    assert validation_rows[0]["trunk_mode"] == "counterclockwise_loop"
    assert validation_rows[0]["counterclockwise_ok"] == "True"
    support_info = json.loads(validation_rows[0]["support_info"])
    assert support_info["bidirectional_minimal_loop"] is True
    assert set(trunk["features"][0]["properties"]["road_ids"]) == {"r12"}
    assert set(segment_body["features"][0]["properties"]["road_ids"]) == {"r12"}


def test_step2_validates_bidirectional_overlap_loop_as_minimal_loop(tmp_path: Path) -> None:
    road_path, node_path = _build_bidirectional_overlap_loop_dataset(tmp_path)
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

    validated_rows = _read_csv_rows(out_root / "S2X" / "validated_pairs.csv")
    validation_rows = _read_csv_rows(out_root / "S2X" / "pair_validation_table.csv")
    trunk = _load_json(out_root / "S2X" / "trunk_roads.gpkg")

    assert [row["pair_id"] for row in validated_rows] == ["S2X:1__3"]
    assert validation_rows[0]["validated_status"] == "validated"
    assert validation_rows[0]["trunk_mode"] == "counterclockwise_loop"
    support_info = json.loads(validation_rows[0]["support_info"])
    assert support_info["bidirectional_minimal_loop"] is True
    assert set(trunk["features"][0]["properties"]["road_ids"]) == {"r12", "r23", "r32"}


def test_step2_validates_bidirectional_overlap_loop_with_through_nodes(tmp_path: Path) -> None:
    road_path, node_path = _build_bidirectional_overlap_with_through_dataset(tmp_path)
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
    rejected_rows = _read_csv_rows(out_root / "S2X" / "rejected_pair_candidates.csv")
    summary = _load_json(out_root / "S2X" / "segment_summary.json")

    assert len(validation_rows) == 1
    assert validation_rows[0]["validated_status"] == "rejected"
    assert validation_rows[0]["reject_reason"] == "bidirectional_minimal_loop_lasso"
    support_info = json.loads(validation_rows[0]["support_info"])
    assert support_info["bidirectional_minimal_loop_lasso_blocked"] is True
    assert support_info["bidirectional_minimal_loop_lasso_leaf_node_id"] == "4"
    assert rejected_rows[0]["reject_reason"] == "bidirectional_minimal_loop_lasso"
    assert summary["validated_pair_count"] == 0
    assert summary["rejected_pair_count"] == 1


def test_step2_validates_semantic_node_group_closure_loop(tmp_path: Path) -> None:
    road_path, node_path = _build_semantic_group_closure_dataset(tmp_path)
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
    strategy_root = out_root / "S2X"
    validated_rows = _read_csv_rows(strategy_root / "validated_pairs.csv")
    validation_rows = _read_csv_rows(strategy_root / "pair_validation_table.csv")
    trunk = _load_json(strategy_root / "trunk_roads.gpkg")
    segment_body = _load_json(strategy_root / "segment_body_roads.gpkg")

    assert [row["pair_id"] for row in validated_rows] == ["S2X:1__3"]
    assert validation_rows[0]["validated_status"] == "validated"
    assert validation_rows[0]["trunk_mode"] == "counterclockwise_loop"
    assert validation_rows[0]["counterclockwise_ok"] == "True"
    support_info = json.loads(validation_rows[0]["support_info"])
    assert support_info["bidirectional_minimal_loop"] is False
    assert support_info["semantic_node_group_closure"] is True
    assert set(trunk["features"][0]["properties"]["road_ids"]) == {"r12", "r31"}
    assert set(segment_body["features"][0]["properties"]["road_ids"]) == {"r12", "r31"}


def test_step2_rejects_disconnected_after_prune(monkeypatch, tmp_path: Path) -> None:
    road_path, node_path = _build_disconnected_cycle_dataset(tmp_path)
    strategy_path = _write_strategy(tmp_path / "step2_strategy.json")
    bootstrap = initialize_working_layers(
        road_path=road_path,
        node_path=node_path,
        out_root=tmp_path / "working_disconnected_cycle",
    )
    context = step1_pair_poc.build_step1_graph_context(
        road_path=bootstrap.roads_path,
        node_path=bootstrap.nodes_path,
    )
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


def test_step2_validation_emits_pair_phase_markers(monkeypatch) -> None:
    pair = _pair_record("S2X:10__20", "10", "20", ("r1020",))
    execution = _minimal_execution([pair])
    roads = [_road_record("r1020", "10", "20")]
    context = _minimal_context(roads)
    road_endpoints = {"r1020": ("10", "20")}
    undirected_adjacency = {
        "10": (step1_pair_poc.TraversalEdge("r1020", "10", "20"),),
        "20": (step1_pair_poc.TraversalEdge("r1020", "20", "10"),),
    }

    trunk_candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(("10", "20"), ("r1020",), 1.0),
        reverse_path=step2_segment_poc.DirectedPath(("20", "10"), ("r1020",), 1.0),
        road_ids=("r1020",),
        signed_area=1.0,
        total_length=2.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=0.0,
    )

    monkeypatch.setattr(step2_segment_poc, "_build_candidate_channel", lambda *args, **kwargs: ({"r1020"}, set()))
    monkeypatch.setattr(
        step2_segment_poc,
        "_prune_candidate_channel",
        lambda *args, **kwargs: ({"r1020"}, [], False),
    )
    monkeypatch.setattr(
        step2_segment_poc,
        "_evaluate_trunk",
        lambda *args, **kwargs: (trunk_candidate, None, (), {}),
    )
    monkeypatch.setattr(step2_segment_poc, "_collect_internal_boundary_nodes", lambda *args, **kwargs: ())
    captured_allowed_road_ids: dict[str, set[str]] = {}

    def _fake_build_segment_body_candidate_channel(*args, **kwargs):
        allowed_road_ids = kwargs["allowed_road_ids"]
        captured_allowed_road_ids["value"] = None if allowed_road_ids is None else set(allowed_road_ids)
        return {"r1020"}

    monkeypatch.setattr(
        step2_segment_poc,
        "_build_segment_body_candidate_channel",
        _fake_build_segment_body_candidate_channel,
    )
    monkeypatch.setattr(
        step2_segment_poc,
        "_refine_segment_roads",
        lambda *args, **kwargs: (("r1020",), []),
    )
    monkeypatch.setattr(
        step2_segment_poc,
        "_tighten_validated_segment_components",
        lambda provisional_results, **kwargs: provisional_results,
    )

    progress_events: list[tuple[str, dict[str, object]]] = []
    validations = step2_segment_poc._validate_pair_candidates(
        execution,
        context=context,
        road_endpoints=road_endpoints,
        undirected_adjacency=undirected_adjacency,
        formway_mode="strict",
        left_turn_formway_bit=8,
        progress_callback=lambda event, payload: progress_events.append((event, payload)),
    )

    assert len(validations) == 1
    phases = [
        payload["phase"]
        for event, payload in progress_events
        if event == "validation_pair_state"
    ]
    assert phases == [
        "validation_pair_started",
        "validation_pair_started",
        "candidate_channel_built",
        "prune_completed",
        "trunk_evaluated",
        "segment_body_started",
        "segment_body_candidate_channel_built",
        "segment_body_refine_started",
        "segment_body_refine_completed",
        "segment_body_completed",
        "result_appended",
    ]
    assert captured_allowed_road_ids["value"] == {"r1020"}
    assert [event for event, _ in progress_events if event in {"validation_started", "validation_tighten_started", "validation_tighten_completed"}] == [
        "validation_started",
        "validation_tighten_started",
        "validation_tighten_completed",
    ]


def test_trace_validation_pair_ids_only_toggle_perf_log_without_changing_validations(monkeypatch) -> None:
    pair = _pair_record("S2X:10__20", "10", "20", ("r1020",))
    execution = _minimal_execution([pair])
    roads = [_road_record("r1020", "10", "20")]
    context = _minimal_context(roads)
    road_endpoints = {"r1020": ("10", "20")}
    undirected_adjacency = {
        "10": (step1_pair_poc.TraversalEdge("r1020", "10", "20"),),
        "20": (step1_pair_poc.TraversalEdge("r1020", "20", "10"),),
    }

    trunk_candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(("10", "20"), ("r1020",), 1.0),
        reverse_path=step2_segment_poc.DirectedPath(("20", "10"), ("r1020",), 1.0),
        road_ids=("r1020",),
        signed_area=1.0,
        total_length=2.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=0.0,
    )

    monkeypatch.setattr(step2_segment_poc, "VALIDATION_PHASE_TRACE_PAIR_LIMIT", 0)
    monkeypatch.setattr(step2_segment_poc, "_build_candidate_channel", lambda *args, **kwargs: ({"r1020"}, set()))
    monkeypatch.setattr(
        step2_segment_poc,
        "_prune_candidate_channel",
        lambda *args, **kwargs: ({"r1020"}, [], False),
    )
    monkeypatch.setattr(
        step2_segment_poc,
        "_evaluate_trunk",
        lambda *args, **kwargs: (trunk_candidate, None, (), {}),
    )
    monkeypatch.setattr(step2_segment_poc, "_collect_internal_boundary_nodes", lambda *args, **kwargs: ())
    monkeypatch.setattr(
        step2_segment_poc,
        "_build_segment_body_candidate_channel",
        lambda *args, **kwargs: {"r1020"},
    )
    monkeypatch.setattr(
        step2_segment_poc,
        "_refine_segment_roads",
        lambda *args, **kwargs: (("r1020",), []),
    )
    monkeypatch.setattr(
        step2_segment_poc,
        "_tighten_validated_segment_components",
        lambda provisional_results, **kwargs: provisional_results,
    )

    progress_without_trace: list[tuple[str, dict[str, object]]] = []
    validations_without_trace = step2_segment_poc._validate_pair_candidates(
        execution,
        context=context,
        road_endpoints=road_endpoints,
        undirected_adjacency=undirected_adjacency,
        formway_mode="strict",
        left_turn_formway_bit=8,
        progress_callback=lambda event, payload: progress_without_trace.append((event, payload)),
    )

    progress_with_trace: list[tuple[str, dict[str, object]]] = []
    validations_with_trace = step2_segment_poc._validate_pair_candidates(
        execution,
        context=context,
        road_endpoints=road_endpoints,
        undirected_adjacency=undirected_adjacency,
        formway_mode="strict",
        left_turn_formway_bit=8,
        progress_callback=lambda event, payload: progress_with_trace.append((event, payload)),
        trace_validation_pair_ids={pair.pair_id},
    )

    assert validations_without_trace == validations_with_trace
    without_perf_flags = [
        payload["_perf_log"]
        for event, payload in progress_without_trace
        if event == "validation_pair_state"
    ]
    with_perf_flags = [
        payload["_perf_log"]
        for event, payload in progress_with_trace
        if event == "validation_pair_state"
    ]
    assert without_perf_flags
    assert with_perf_flags
    assert set(without_perf_flags) == {False}
    assert set(with_perf_flags) == {True}


def test_step2_rejects_trunk_when_current_boundary_terminate_becomes_internal_node(monkeypatch) -> None:
    pair = _pair_record("S2X:A__B", "A", "B", ("rAT", "rTB"))
    execution = _minimal_execution([pair], terminate_ids=["T1"])
    roads = [
        _road_record("rAT", "A", "T1"),
        _road_record("rTB", "T1", "B"),
    ]
    context = _minimal_context(roads)
    road_endpoints = {
        "rAT": ("A", "T1"),
        "rTB": ("T1", "B"),
    }
    undirected_adjacency = {
        "A": (step1_pair_poc.TraversalEdge("rAT", "A", "T1"),),
        "T1": (
            step1_pair_poc.TraversalEdge("rAT", "T1", "A"),
            step1_pair_poc.TraversalEdge("rTB", "T1", "B"),
        ),
        "B": (step1_pair_poc.TraversalEdge("rTB", "B", "T1"),),
    }
    trunk_candidate = step2_segment_poc.TrunkCandidate(
        forward_path=step2_segment_poc.DirectedPath(("A", "T1", "B"), ("rAT", "rTB"), 2.0),
        reverse_path=step2_segment_poc.DirectedPath(("B", "T1", "A"), ("rTB", "rAT"), 2.0),
        road_ids=("rAT", "rTB"),
        signed_area=1.0,
        total_length=4.0,
        left_turn_road_ids=(),
        max_dual_carriageway_separation_m=0.0,
    )

    monkeypatch.setattr(
        step2_segment_poc,
        "_build_candidate_channel",
        lambda *args, **kwargs: ({"rAT", "rTB"}, {"T1"}),
    )
    monkeypatch.setattr(
        step2_segment_poc,
        "_prune_candidate_channel",
        lambda *args, **kwargs: ({"rAT", "rTB"}, [], False),
    )
    monkeypatch.setattr(
        step2_segment_poc,
        "_evaluate_trunk_choices",
        lambda *args, **kwargs: (
            [step2_segment_poc._TrunkEvaluationChoice(trunk_candidate, (), {})],
            None,
            (),
            {},
        ),
    )

    results = step2_segment_poc._validate_pair_candidates(
        execution,
        context=context,
        road_endpoints=road_endpoints,
        undirected_adjacency=undirected_adjacency,
        formway_mode="strict",
        left_turn_formway_bit=8,
    )

    assert len(results) == 1
    assert results[0].validated_status == "rejected"
    assert results[0].reject_reason == "current_terminate_blocked"
    assert results[0].support_info["current_terminate_node_ids"] == ["T1"]
    assert results[0].boundary_terminate_node_ids == ("T1",)
