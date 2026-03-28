from __future__ import annotations

import argparse
import csv
import json
from dataclasses import replace
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.cli import main
from rcsd_topo_poc.modules.t01_data_preprocess import (
    step1_pair_poc,
    step2_arbitration,
    step2_segment_poc,
    step2_trunk_utils,
    step2_validation_utils,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import load_vector_feature_collection
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import initialize_working_layers


def _write_geojson(path: Path, *, features: list[dict]) -> None:
    payload = {
        "type": "FeatureCollection",
        # Step2 distance gates work in projected meters. Keep synthetic fixtures in EPSG:3857
        # so 50m thresholds are exercised on realistic units instead of projected degrees.
        "crs": {"type": "name", "properties": {"name": "EPSG:3857"}},
        "features": features,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _node_feature(
    node_id: int,
    x: float,
    y: float,
    *,
    kind: int = 4,
    grade: int = 1,
    closed_con: int = 2,
    mainnodeid: int | None = None,
) -> dict:
    properties = {"id": node_id, "kind": kind, "grade": grade, "closed_con": closed_con}
    if mainnodeid is not None:
        properties["mainnodeid"] = mainnodeid
    return {
        "type": "Feature",
        "properties": properties,
        "geometry": {"type": "Point", "coordinates": [x, y]},
    }


def _road_feature(
    road_id: str,
    snodeid: int,
    enodeid: int,
    direction: int,
    coords: list[list[float]],
    *,
    formway: int = 0,
    road_kind: int = 0,
) -> dict:
    return {
        "type": "Feature",
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "formway": formway,
            "road_kind": road_kind,
        },
        "geometry": {"type": "LineString", "coordinates": coords},
    }


def _load_json(path: Path) -> dict:
    if path.suffix.lower() in {".gpkg", ".gpkt"}:
        doc = load_vector_feature_collection(path)
        for feature in doc.get("features", []):
            props = feature.get("properties") or {}
            road_ids = props.get("road_ids")
            if isinstance(road_ids, str):
                try:
                    parsed = json.loads(road_ids)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, list):
                    props["road_ids"] = parsed
        return doc
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    return list(csv.DictReader(path.open("r", encoding="utf-8-sig")))


def _minimal_strategy(strategy_id: str = "S2X") -> step1_pair_poc.StrategySpec:
    rule = step1_pair_poc.RuleSpec(kind_bits_all=(2,), grade_eq=1, closed_con_in=(2, 3))
    return step1_pair_poc.StrategySpec(
        strategy_id=strategy_id,
        description="synthetic",
        seed_rule=rule,
        terminate_rule=rule,
        through_rule=step1_pair_poc.ThroughRuleSpec(incident_road_degree_eq=2),
    )


def _minimal_execution(
    pairs: list[step1_pair_poc.PairRecord],
    *,
    terminate_ids: list[str] | None = None,
    strategy_id: str = "S2X",
) -> step1_pair_poc.Step1StrategyExecution:
    return step1_pair_poc.Step1StrategyExecution(
        strategy=_minimal_strategy(strategy_id),
        seed_eval={},
        terminate_eval={},
        seed_ids=[],
        terminate_ids=[] if terminate_ids is None else terminate_ids,
        through_node_ids=set(),
        search_seed_ids=[],
        through_seed_pruned_count=0,
        search_results={},
        search_event_counts={},
        search_event_samples=[],
        pair_candidates=pairs,
    )


def _minimal_context(
    roads: list[step1_pair_poc.RoadRecord],
    *,
    directed: dict[str, tuple[step1_pair_poc.TraversalEdge, ...]] | None = None,
    semantic_nodes: dict[str, step1_pair_poc.SemanticNodeRecord] | None = None,
) -> step1_pair_poc.Step1GraphContext:
    return step1_pair_poc.Step1GraphContext(
        physical_nodes={},
        roads={road.road_id: road for road in roads},
        semantic_nodes={} if semantic_nodes is None else semantic_nodes,
        physical_to_semantic={},
        directed={} if directed is None else directed,
        blocked={},
        orphan_ref_count=0,
        graph_audit_events=[],
    )


def _semantic_node_record(
    node_id: str,
    *,
    kind_2: int,
    grade_2: int = 1,
    raw_kind: int | None = None,
    raw_grade: int | None = None,
    closed_con: int = 2,
    cross_flag: int = 0,
    mainnodeid: str | None = None,
) -> step1_pair_poc.SemanticNodeRecord:
    raw_properties = {
        "id": node_id,
        "kind": kind_2 if raw_kind is None else raw_kind,
        "grade": grade_2 if raw_grade is None else raw_grade,
        "kind_2": kind_2,
        "grade_2": grade_2,
        "closed_con": closed_con,
        "cross_flag": cross_flag,
    }
    if mainnodeid is not None:
        raw_properties["mainnodeid"] = mainnodeid
    return step1_pair_poc.SemanticNodeRecord(
        semantic_node_id=node_id,
        representative_node_id=node_id,
        member_node_ids=(node_id,),
        raw_kind=kind_2 if raw_kind is None else raw_kind,
        raw_grade=grade_2 if raw_grade is None else raw_grade,
        kind_2=kind_2,
        grade_2=grade_2,
        closed_con=closed_con,
        geometry=Point(0.0, 0.0),
        raw_properties=raw_properties,
    )


def _road_record(
    road_id: str,
    snodeid: str,
    enodeid: str,
    *,
    coords: tuple[tuple[float, float], tuple[float, float]] | None = None,
    direction: int = 0,
    road_kind: int = 0,
) -> step1_pair_poc.RoadRecord:
    if coords is None:
        base = float(sum(ord(ch) for ch in road_id) % 17)
        coords = ((base, 0.0), (base + 0.5, 1.0))
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


def _pair_record(
    pair_id: str,
    a_node_id: str,
    b_node_id: str,
    road_ids: tuple[str, ...],
    *,
    strategy_id: str = "S2X",
) -> step1_pair_poc.PairRecord:
    return step1_pair_poc.PairRecord(
        pair_id=pair_id,
        a_node_id=a_node_id,
        b_node_id=b_node_id,
        strategy_id=strategy_id,
        reverse_confirmed=True,
        forward_path_node_ids=(a_node_id, b_node_id),
        forward_path_road_ids=road_ids,
        reverse_path_node_ids=(b_node_id, a_node_id),
        reverse_path_road_ids=tuple(reversed(road_ids)),
        through_node_ids=(),
    )


def _validation_result(
    pair_id: str,
    a_node_id: str,
    b_node_id: str,
    *,
    pruned_road_ids: tuple[str, ...],
    trunk_road_ids: tuple[str, ...],
    segment_road_ids: tuple[str, ...],
    validated_status: str = "validated",
) -> step2_segment_poc.PairValidationResult:
    return step2_segment_poc.PairValidationResult(
        pair_id=pair_id,
        a_node_id=a_node_id,
        b_node_id=b_node_id,
        candidate_status="candidate",
        validated_status=validated_status,
        reject_reason=None if validated_status == "validated" else "synthetic_reject",
        trunk_mode="counterclockwise_loop",
        trunk_found=validated_status == "validated",
        counterclockwise_ok=validated_status == "validated",
        left_turn_excluded_mode="strict",
        warning_codes=(),
        candidate_channel_road_ids=pruned_road_ids,
        pruned_road_ids=pruned_road_ids,
        trunk_road_ids=trunk_road_ids,
        segment_road_ids=segment_road_ids,
        residual_road_ids=(),
        branch_cut_road_ids=(),
        boundary_terminate_node_ids=(),
        transition_same_dir_blocked=False,
        support_info={"branch_cut_infos": []},
        conflict_pair_id=None,
    )


def _arbitration_option(
    option_id: str,
    pair_id: str,
    a_node_id: str,
    b_node_id: str,
    *,
    trunk_road_ids: tuple[str, ...],
    pruned_road_ids: tuple[str, ...] | None = None,
    segment_candidate_road_ids: tuple[str, ...] | None = None,
    segment_road_ids: tuple[str, ...] | None = None,
    forward_path_road_ids: tuple[str, ...] | None = None,
    reverse_path_road_ids: tuple[str, ...] | None = None,
    pair_support_road_ids: tuple[str, ...] | None = None,
    support_info_overrides: dict[str, Any] | None = None,
) -> step2_arbitration.PairArbitrationOption:
    if pruned_road_ids is None:
        pruned_road_ids = trunk_road_ids
    if segment_candidate_road_ids is None:
        segment_candidate_road_ids = pruned_road_ids
    if segment_road_ids is None:
        segment_road_ids = trunk_road_ids
    if forward_path_road_ids is None:
        forward_path_road_ids = trunk_road_ids
    if reverse_path_road_ids is None:
        reverse_path_road_ids = tuple(reversed(forward_path_road_ids))
    if pair_support_road_ids is None:
        pair_support_road_ids = tuple(sorted(set(forward_path_road_ids) | set(reverse_path_road_ids)))
    support_info = {
        "forward_path_road_ids": list(forward_path_road_ids),
        "reverse_path_road_ids": list(reverse_path_road_ids),
        "pair_support_road_ids": list(pair_support_road_ids),
        "trunk_signed_area": 0.0,
    }
    if support_info_overrides:
        support_info.update(support_info_overrides)
    return step2_arbitration.PairArbitrationOption(
        option_id=option_id,
        pair_id=pair_id,
        a_node_id=a_node_id,
        b_node_id=b_node_id,
        trunk_mode="counterclockwise_loop",
        counterclockwise_ok=True,
        warning_codes=(),
        candidate_channel_road_ids=pruned_road_ids,
        pruned_road_ids=pruned_road_ids,
        trunk_road_ids=trunk_road_ids,
        segment_candidate_road_ids=segment_candidate_road_ids,
        segment_road_ids=segment_road_ids,
        branch_cut_road_ids=(),
        boundary_terminate_node_ids=(),
        transition_same_dir_blocked=False,
        support_info=support_info,
    )


def _write_strategy(path: Path) -> Path:
    payload = {
        "strategy_id": "S2X",
        "description": "Synthetic Step2 strategy: S2 seed/terminate, through disabled for test focus.",
        "seed_rule": {"kind_bits_all": [2], "closed_con_in": [2, 3], "grade_eq": 1},
        "terminate_rule": {"kind_bits_all": [2], "closed_con_in": [2, 3], "grade_eq": 1},
        "through_node_rule": {"incident_road_degree_eq": 99, "incident_degree_exclude_formway_bits_any": [7]},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


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


def _build_counterclockwise_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"
    node_features = [
        _node_feature(1, 0.0, 0.0),
        _node_feature(2, 1.0, 1.0, kind=0, grade=0, closed_con=0),
        _node_feature(3, 2.0, 0.0),
        _node_feature(4, 1.0, -1.0, kind=0, grade=0, closed_con=0),
        _node_feature(5, 1.0, 2.0),
        _node_feature(6, 1.2, 0.0, kind=0, grade=0, closed_con=0),
    ]
    road_features = [
        _road_feature("r14", 1, 4, 2, [[0.0, 0.0], [1.0, -1.0]]),
        _road_feature("r43", 4, 3, 2, [[1.0, -1.0], [2.0, 0.0]]),
        _road_feature("r32", 3, 2, 2, [[2.0, 0.0], [1.0, 1.0]]),
        _road_feature("r21", 2, 1, 2, [[1.0, 1.0], [0.0, 0.0]]),
        _road_feature("r25", 2, 5, 2, [[1.0, 1.0], [1.0, 2.0]]),
        _road_feature("r46", 4, 6, 0, [[1.0, -1.0], [1.2, 0.0]]),
        _road_feature("r62", 6, 2, 0, [[1.2, 0.0], [1.0, 1.0]]),
    ]
    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _build_clockwise_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"
    node_features = [
        _node_feature(1, 0.0, 0.0),
        _node_feature(2, 1.0, 1.0, kind=0, grade=0, closed_con=0),
        _node_feature(3, 2.0, 0.0),
        _node_feature(4, 1.0, -1.0, kind=0, grade=0, closed_con=0),
    ]
    road_features = [
        _road_feature("r12", 1, 2, 2, [[0.0, 0.0], [1.0, 1.0]]),
        _road_feature("r23", 2, 3, 2, [[1.0, 1.0], [2.0, 0.0]]),
        _road_feature("r34", 3, 4, 2, [[2.0, 0.0], [1.0, -1.0]]),
        _road_feature("r41", 4, 1, 2, [[1.0, -1.0], [0.0, 0.0]]),
    ]
    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _build_left_turn_polluted_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path, node_path = _build_counterclockwise_dataset(base_dir)
    doc = _load_json(road_path)
    for feature in doc["features"]:
        if feature["properties"]["id"] == "r32":
            feature["properties"]["formway"] = 256
    road_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return road_path, node_path


def _build_segment_formway_filtered_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path, node_path = _build_counterclockwise_dataset(base_dir)
    doc = _load_json(road_path)
    for feature in doc["features"]:
        if feature["properties"]["id"] == "r46":
            feature["properties"]["formway"] = 128
    road_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return road_path, node_path


def _build_through_collapsed_corridor_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"
    node_features = [
        _node_feature(1, 0.0, 0.0),
        _node_feature(2, 1.0, 0.0),
        _node_feature(3, 2.0, 0.0),
        _node_feature(4, 1.0, 1.0, kind=0, grade=0, closed_con=0),
        _node_feature(5, 1.0, -1.0, kind=0, grade=0, closed_con=0),
    ]
    road_features = [
        _road_feature("r12", 1, 2, 1, [[0.0, 0.0], [1.0, 0.0]]),
        _road_feature("r23", 2, 3, 1, [[1.0, 0.0], [2.0, 0.0]]),
        _road_feature("r24", 2, 4, 1, [[1.0, 0.0], [1.0, 1.0]], formway=128),
        _road_feature("r25", 2, 5, 1, [[1.0, 0.0], [1.0, -1.0]], formway=128),
    ]
    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _build_step5c_mirrored_one_sided_corridor_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"
    node_features = [
        _node_feature(1, 0.0, 0.0),
        _node_feature(2, 1.0, 0.0, kind=0, grade=0, closed_con=0),
        _node_feature(3, 2.0, 0.0, kind=0, grade=0, closed_con=0),
        _node_feature(4, 3.0, 0.0),
    ]
    road_features = [
        _road_feature("r12", 1, 2, 2, [[0.0, 0.0], [1.0, 0.0]]),
        _road_feature("r23", 2, 3, 2, [[1.0, 0.0], [2.0, 0.0]]),
        _road_feature("r34", 3, 4, 2, [[2.0, 0.0], [3.0, 0.0]]),
    ]
    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _build_bidirectional_minimal_loop_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"
    node_features = [
        _node_feature(1, 0.0, 0.0),
        _node_feature(2, 1.0, 0.0),
    ]
    road_features = [
        _road_feature("r12", 1, 2, 1, [[0.0, 0.0], [1.0, 0.0]]),
    ]
    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _build_bidirectional_overlap_loop_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"
    node_features = [
        _node_feature(1, 0.0, 0.0),
        _node_feature(2, 1.0, 0.0, kind=0, grade=0, closed_con=0),
        _node_feature(3, 2.0, 0.0),
    ]
    road_features = [
        _road_feature("r12", 1, 2, 1, [[0.0, 0.0], [1.0, 0.0]]),
        _road_feature("r23", 2, 3, 2, [[1.0, 0.0], [2.0, 0.5]]),
        _road_feature("r32", 3, 2, 2, [[2.0, 0.0], [1.0, -0.5]]),
    ]
    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _build_bidirectional_overlap_with_through_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"
    node_features = [
        _node_feature(1, 0.0, 0.0),
        _node_feature(2, 1.0, 0.5, kind=0, grade=0, closed_con=0),
        _node_feature(3, 2.0, 0.0, kind=0, grade=0, closed_con=0),
        _node_feature(4, 3.0, 0.0),
        _node_feature(5, 2.0, -0.5, kind=0, grade=0, closed_con=0),
    ]
    road_features = [
        _road_feature("r12", 1, 2, 2, [[0.0, 0.0], [1.0, 0.5]]),
        _road_feature("r23", 2, 3, 2, [[1.0, 0.5], [2.0, 0.0]]),
        _road_feature("r34", 3, 4, 1, [[2.0, 0.0], [3.0, 0.0]]),
        _road_feature("r35", 3, 5, 2, [[2.0, 0.0], [2.0, -0.5]]),
        _road_feature("r51", 5, 1, 2, [[2.0, -0.5], [0.0, 0.0]]),
    ]
    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _build_semantic_group_closure_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"
    node_features = [
        _node_feature(1, 0.0, 0.0),
        _node_feature(2, 1.0, 1.0, kind=0, grade=0, closed_con=0, mainnodeid=3),
        _node_feature(3, 1.0, -1.0),
    ]
    road_features = [
        _road_feature("r12", 1, 2, 2, [[0.0, 0.0], [1.0, 1.0]]),
        _road_feature("r31", 3, 1, 2, [[1.0, -1.0], [0.0, 0.0]]),
    ]
    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


def _build_disconnected_cycle_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path, node_path = _build_counterclockwise_dataset(base_dir)
    node_doc = _load_json(node_path)
    node_doc["features"].extend(
        [
            _node_feature(7, 3.0, 1.0, kind=0, grade=0, closed_con=0),
            _node_feature(8, 4.0, 1.0, kind=0, grade=0, closed_con=0),
            _node_feature(9, 3.5, 2.0, kind=0, grade=0, closed_con=0),
        ]
    )
    node_path.write_text(json.dumps(node_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    road_doc = _load_json(road_path)
    road_doc["features"].extend(
        [
            _road_feature("r78", 7, 8, 0, [[3.0, 1.0], [4.0, 1.0]]),
            _road_feature("r89", 8, 9, 0, [[4.0, 1.0], [3.5, 2.0]]),
            _road_feature("r97", 9, 7, 0, [[3.5, 2.0], [3.0, 1.0]]),
        ]
    )
    road_path.write_text(json.dumps(road_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return road_path, node_path


def _build_bridge_cycle_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path, node_path = _build_counterclockwise_dataset(base_dir)
    node_doc = _load_json(node_path)
    node_doc["features"].extend(
        [
            _node_feature(7, 2.0, 1.5, kind=0, grade=0, closed_con=0),
            _node_feature(8, 3.0, 1.5, kind=0, grade=0, closed_con=0),
            _node_feature(9, 2.5, 2.2, kind=0, grade=0, closed_con=0),
        ]
    )
    node_path.write_text(json.dumps(node_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    road_doc = _load_json(road_path)
    road_doc["features"].extend(
        [
            _road_feature("r27", 2, 7, 0, [[1.0, 1.0], [2.0, 1.5]]),
            _road_feature("r78", 7, 8, 0, [[2.0, 1.5], [3.0, 1.5]]),
            _road_feature("r89", 8, 9, 0, [[3.0, 1.5], [2.5, 2.2]]),
            _road_feature("r97", 9, 7, 0, [[2.5, 2.2], [2.0, 1.5]]),
        ]
    )
    road_path.write_text(json.dumps(road_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return road_path, node_path


def _build_dual_separation_exceeded_dataset(base_dir: Path) -> tuple[Path, Path]:
    road_path = base_dir / "roads.geojson"
    node_path = base_dir / "nodes.geojson"
    node_features = [
        _node_feature(1, 0.0, 0.0),
        _node_feature(2, 10.0, 0.0, kind=0, grade=0, closed_con=0),
        _node_feature(3, 20.0, 0.0),
        _node_feature(4, 20.0, 120.0, kind=0, grade=0, closed_con=0),
        _node_feature(5, 0.0, 120.0, kind=0, grade=0, closed_con=0),
    ]
    road_features = [
        _road_feature("r12", 1, 2, 2, [[0.0, 0.0], [10.0, 0.0]]),
        _road_feature("r23", 2, 3, 2, [[10.0, 0.0], [20.0, 0.0]]),
        _road_feature("r34", 3, 4, 2, [[20.0, 0.0], [20.0, 120.0]]),
        _road_feature("r45", 4, 5, 2, [[20.0, 120.0], [0.0, 120.0]]),
        _road_feature("r51", 5, 1, 2, [[0.0, 120.0], [0.0, 0.0]]),
    ]
    _write_geojson(road_path, features=road_features)
    _write_geojson(node_path, features=node_features)
    return road_path, node_path


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


def test_step2_compact_option_for_validation_runtime_drops_duplicate_payloads() -> None:
    option = step2_segment_poc.PairArbitrationOption(
        option_id="S2X:1__3::opt_01",
        pair_id="S2X:1__3",
        a_node_id="1",
        b_node_id="3",
        trunk_mode="counterclockwise_loop",
        counterclockwise_ok=True,
        warning_codes=(),
        candidate_channel_road_ids=("r12", "r23", "r34"),
        pruned_road_ids=("r12", "r23", "r34"),
        trunk_road_ids=("r12", "r23"),
        segment_candidate_road_ids=("r12", "r23", "r34"),
        segment_road_ids=("r12", "r23"),
        branch_cut_road_ids=("r34",),
        boundary_terminate_node_ids=("T1",),
        transition_same_dir_blocked=False,
        support_info={
            "boundary_terminate_node_ids": ["T1"],
            "candidate_channel_road_ids": ["r12", "r23", "r34"],
            "pruned_road_ids": ["r12", "r23", "r34"],
            "pair_support_road_ids": ["r12", "r23"],
            "forward_path_road_ids": ["r12", "r23"],
            "reverse_path_road_ids": ["r23", "r12"],
            "segment_body_candidate_road_ids": ["r12", "r23", "r34"],
            "segment_body_candidate_cut_infos": [{"road_id": "r34", "cut_reason": "segment_exclude_formway"}],
            "left_turn_road_ids": [],
            "branch_cut_infos": [{"road_id": "r34", "cut_reason": "hits_other_terminate", "terminate_node_ids": ["T1"]}],
            "trunk_signed_area": 1.0,
            "bidirectional_minimal_loop": True,
            "semantic_node_group_closure": False,
            "endpoint_priority_grades": [3, 2],
        },
    )

    compact = step2_segment_poc._compact_option_for_validation_runtime(option)

    assert compact.candidate_channel_road_ids == ()
    assert compact.pruned_road_ids == ("r12", "r23", "r34")
    assert compact.segment_candidate_road_ids == ("r12", "r23", "r34")
    assert compact.segment_road_ids == ("r12", "r23")
    assert compact.branch_cut_road_ids == ()
    assert compact.boundary_terminate_node_ids == ()
    assert compact.support_info["candidate_channel_road_count"] == 3
    assert compact.support_info["pruned_road_count"] == 3
    assert compact.support_info["segment_body_candidate_road_count"] == 3
    assert compact.support_info["segment_body_road_count"] == 2
    assert compact.support_info["forward_path_road_ids"] == ["r12", "r23"]
    assert compact.support_info["reverse_path_road_ids"] == ["r23", "r12"]
    assert compact.support_info["branch_cut_infos"] == [
        {"road_id": "r34", "cut_reason": "hits_other_terminate", "terminate_node_ids": ["T1"]}
    ]
    assert "candidate_channel_road_ids" not in compact.support_info
    assert "pruned_road_ids" not in compact.support_info
    assert "left_turn_road_ids" not in compact.support_info
    assert "pair_support_road_ids" not in compact.support_info
    assert "segment_body_candidate_road_ids" not in compact.support_info
    assert "segment_body_candidate_cut_infos" not in compact.support_info


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


def test_step2_segment_poc_can_filter_validation_pairs_after_candidate_search(
    tmp_path: Path,
    monkeypatch,
) -> None:
    out_root = tmp_path / "step2_filter_run"
    strategy = _minimal_strategy("S2X")
    context = _minimal_context([_road_record("r1", "A", "B"), _road_record("r2", "C", "D")])
    execution = _minimal_execution(
        [
            _pair_record("PAIR_A_B", "A", "B", ("r1",), strategy_id="S2X"),
            _pair_record("PAIR_C_D", "C", "D", ("r2",), strategy_id="S2X"),
        ],
        terminate_ids=["A", "B", "C", "D"],
        strategy_id="S2X",
    )

    monkeypatch.setattr(step2_segment_poc, "build_step1_graph_context", lambda **_: context)
    monkeypatch.setattr(
        step2_segment_poc,
        "_build_semantic_endpoints",
        lambda _context: ({"r1": ("A", "B"), "r2": ("C", "D")}, {"A": (), "B": (), "C": (), "D": ()}),
    )
    monkeypatch.setattr(step2_segment_poc, "_load_strategy", lambda _path: strategy)
    monkeypatch.setattr(step2_segment_poc, "run_step1_strategy", lambda _context, _strategy: execution)
    monkeypatch.setattr(step2_segment_poc, "write_step1_candidate_outputs", lambda *args, **kwargs: None)

    captured_execution: dict[str, step1_pair_poc.Step1StrategyExecution] = {}

    def _fake_validate_pair_candidates(*args, **kwargs):
        captured_execution["value"] = args[0]
        return []

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
                "candidate_pair_count": 0,
                "validated_pair_count": 0,
                "rejected_pair_count": 0,
            },
            output_files=[],
            validations=[],
        )

    monkeypatch.setattr(step2_segment_poc, "_write_step2_outputs", _fake_write_step2_outputs)

    progress_events: list[tuple[str, dict[str, object]]] = []
    step2_segment_poc.run_step2_segment_poc(
        road_path=tmp_path / "roads.geojson",
        node_path=tmp_path / "nodes.geojson",
        strategy_config_paths=[tmp_path / "strategy.json"],
        out_root=out_root,
        retain_validation_details=False,
        assume_working_layers=True,
        only_validation_pair_ids=["PAIR_C_D"],
        progress_callback=lambda event, payload: progress_events.append((event, payload)),
    )

    assert [pair.pair_id for pair in captured_execution["value"].pair_candidates] == ["PAIR_C_D"]
    filter_events = [
        payload
        for event, payload in progress_events
        if event == "validation_pair_filter_applied"
    ]
    assert len(filter_events) == 1
    assert filter_events[0]["requested_pair_count"] == 1
    assert filter_events[0]["matched_pair_count"] == 1


def test_step2_segment_poc_can_filter_validation_pairs_by_index_range_and_pair_id_intersection(
    tmp_path: Path,
    monkeypatch,
) -> None:
    out_root = tmp_path / "step2_filter_range_run"
    strategy = _minimal_strategy("S2X")
    context = _minimal_context(
        [
            _road_record("r1", "A", "B"),
            _road_record("r2", "C", "D"),
            _road_record("r3", "E", "F"),
        ]
    )
    execution = _minimal_execution(
        [
            _pair_record("PAIR_A_B", "A", "B", ("r1",), strategy_id="S2X"),
            _pair_record("PAIR_C_D", "C", "D", ("r2",), strategy_id="S2X"),
            _pair_record("PAIR_E_F", "E", "F", ("r3",), strategy_id="S2X"),
        ],
        terminate_ids=["A", "B", "C", "D", "E", "F"],
        strategy_id="S2X",
    )

    monkeypatch.setattr(step2_segment_poc, "build_step1_graph_context", lambda **_: context)
    monkeypatch.setattr(
        step2_segment_poc,
        "_build_semantic_endpoints",
        lambda _context: (
            {"r1": ("A", "B"), "r2": ("C", "D"), "r3": ("E", "F")},
            {"A": (), "B": (), "C": (), "D": (), "E": (), "F": ()},
        ),
    )
    monkeypatch.setattr(step2_segment_poc, "_load_strategy", lambda _path: strategy)
    monkeypatch.setattr(step2_segment_poc, "run_step1_strategy", lambda _context, _strategy: execution)
    monkeypatch.setattr(step2_segment_poc, "write_step1_candidate_outputs", lambda *args, **kwargs: None)

    captured_execution: dict[str, step1_pair_poc.Step1StrategyExecution] = {}

    def _fake_validate_pair_candidates(*args, **kwargs):
        captured_execution["value"] = args[0]
        return []

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
                "candidate_pair_count": 0,
                "validated_pair_count": 0,
                "rejected_pair_count": 0,
            },
            output_files=[],
            validations=[],
        )

    monkeypatch.setattr(step2_segment_poc, "_write_step2_outputs", _fake_write_step2_outputs)

    progress_events: list[tuple[str, dict[str, object]]] = []
    step2_segment_poc.run_step2_segment_poc(
        road_path=tmp_path / "roads.geojson",
        node_path=tmp_path / "nodes.geojson",
        strategy_config_paths=[tmp_path / "strategy.json"],
        out_root=out_root,
        retain_validation_details=False,
        assume_working_layers=True,
        only_validation_pair_ids=["PAIR_C_D", "PAIR_E_F"],
        validation_pair_index_start=2,
        validation_pair_index_end=2,
        progress_callback=lambda event, payload: progress_events.append((event, payload)),
    )

    assert [pair.pair_id for pair in captured_execution["value"].pair_candidates] == ["PAIR_C_D"]
    filter_events = [
        payload
        for event, payload in progress_events
        if event == "validation_pair_filter_applied"
    ]
    assert len(filter_events) == 1
    assert filter_events[0]["requested_pair_count"] == 2
    assert filter_events[0]["requested_pair_index_start"] == 2
    assert filter_events[0]["requested_pair_index_end"] == 2
    assert filter_events[0]["matched_pair_count"] == 1


def test_step2_segment_poc_cli_writes_progress_and_perf_files(tmp_path: Path, monkeypatch) -> None:
    out_root = tmp_path / "step2_cli_run"

    def _fake_run_step2_segment_poc(**kwargs):
        assert kwargs["assume_working_layers"] is True
        callback = kwargs["progress_callback"]
        callback("validation_started", {"validation_count": 1})
        callback(
            "validation_pair_state",
            {
                "pair_index": 1,
                "validation_count": 1,
                "pair_id": "PAIR_A_B",
                "phase": "validation_pair_started",
            },
        )
        callback(
            "validation_completed",
            {
                "strategy_id": "S2X",
                "candidate_pair_count": 1,
                "validated_pair_count": 1,
                "rejected_pair_count": 0,
            },
        )
        return [
            step2_segment_poc.Step2StrategyResult(
                strategy=_minimal_strategy("S2X"),
                segment_summary={
                    "candidate_pair_count": 1,
                    "validated_pair_count": 1,
                    "rejected_pair_count": 0,
                },
                output_files=[],
                validations=[],
            )
        ]

    monkeypatch.setattr(step2_segment_poc, "run_step2_segment_poc", _fake_run_step2_segment_poc)

    args = argparse.Namespace(
        road_path=tmp_path / "roads.gpkg",
        road_layer=None,
        road_crs=None,
        node_path=tmp_path / "nodes.gpkg",
        node_layer=None,
        node_crs=None,
        strategy_config=[tmp_path / "strategy.json"],
        formway_mode="strict",
        left_turn_formway_bit=8,
        run_id="t01_step2_diag_test",
        out_root=out_root,
        debug=False,
        trace_validation_pair_ids=["PAIR_A_B"],
        only_validation_pair_ids=["PAIR_A_B"],
        validation_pair_index_start=1,
        validation_pair_index_end=1,
        assume_working_layers=True,
    )

    exit_code = step2_segment_poc.run_step2_segment_poc_cli(args)

    assert exit_code == 0
    progress = _load_json(out_root / "t01_step2_segment_poc_progress.json")
    markers = [
        json.loads(line)
        for line in (out_root / "t01_step2_segment_poc_perf_markers.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert progress["status"] == "completed"
    assert markers[0]["event"] == "step2_run_start"
    assert any(item["event"] == "step2_subprogress" for item in markers)
    assert markers[-1]["event"] == "step2_run_completed"


def test_step2_validation_trace_pair_forces_perf_log_beyond_default_limit(monkeypatch) -> None:
    pair = _pair_record("PAIR_A_B", "A", "B", ("r1",))
    execution = _minimal_execution([pair], terminate_ids=["A", "B"])
    context = _minimal_context([_road_record("r1", "A", "B")])
    road_endpoints = {"r1": ("A", "B")}
    undirected_adjacency = {"A": (), "B": ()}

    monkeypatch.setattr(step2_segment_poc, "VALIDATION_PHASE_TRACE_PAIR_LIMIT", 0)
    monkeypatch.setattr(
        step2_segment_poc,
        "_build_candidate_channel",
        lambda *args, **kwargs: (set(), set()),
    )
    monkeypatch.setattr(
        step2_segment_poc,
        "_tighten_validated_segment_components",
        lambda provisional_results, **kwargs: provisional_results,
    )

    progress_events: list[tuple[str, dict[str, object]]] = []
    results = step2_segment_poc._validate_pair_candidates(
        execution,
        context=context,
        road_endpoints=road_endpoints,
        undirected_adjacency=undirected_adjacency,
        formway_mode="strict",
        left_turn_formway_bit=8,
        trace_validation_pair_ids={"PAIR_A_B"},
        progress_callback=lambda event, payload: progress_events.append((event, payload)),
    )

    assert len(results) == 1
    traced_states = [
        payload
        for event, payload in progress_events
        if event == "validation_pair_state"
    ]
    assert [payload["phase"] for payload in traced_states] == [
        "validation_pair_started",
        "validation_pair_started",
        "candidate_channel_built",
        "result_appended",
    ]
    assert all(payload["_perf_log"] is True for payload in traced_states)


def test_pair_validation_from_option_keeps_winner_full_until_tighten() -> None:
    option = _arbitration_option(
        "PAIR_A_B::opt_01",
        "PAIR_A_B",
        "A",
        "B",
        trunk_road_ids=("r1",),
        pruned_road_ids=("r1", "r2"),
        segment_candidate_road_ids=("r1", "r2"),
        segment_road_ids=("r1", "r2"),
        support_info_overrides={
            "segment_body_candidate_road_ids": ["r1", "r2"],
            "non_trunk_components": [
                {
                    "component_id": "PAIR_A_B:C1",
                    "road_ids": ["r2"],
                    "attachment_node_ids": ["X", "Y"],
                    "internal_support_attachment_node_ids": ["X", "Y"],
                    "internal_t_support_attachment_node_ids": [],
                    "component_directionality": "bidirectional_only",
                    "bidirectional_road_ids": ["r2"],
                    "attachment_flow_status": "single_departure_return",
                    "attachment_direction_labels": ["X:both", "Y:both"],
                    "parallel_corridor_directionality": "bidirectional_parallel",
                    "parallel_corridor_directions": ["X->Y", "Y->X"],
                    "hits_other_terminate": False,
                    "terminate_node_ids": [],
                    "contains_other_validated_trunk": False,
                    "conflicting_pair_ids": [],
                    "blocked_by_transition_same_dir": False,
                    "transition_block_infos": [],
                    "side_access_metric": "component_to_trunk_sampled",
                    "side_access_distance_m": 10.0,
                    "side_access_gate_passed": True,
                    "kept_as_segment_body": False,
                    "moved_to_step3_residual": True,
                    "moved_to_branch_cut": False,
                    "decision_reason": "contains_bidirectional_side_road",
                }
            ],
            "step3_residual_infos": [
                {
                    "road_id": "r2",
                    "component_id": "PAIR_A_B:C1",
                    "residual_reason": "contains_bidirectional_side_road",
                    "blocked_by_transition_same_dir": False,
                    "conflicting_pair_ids": [],
                    "terminate_node_ids": [],
                    "side_access_distance_m": 10.0,
                    "side_access_gate_passed": True,
                    "hint_cut_reasons": [],
                }
            ],
        },
    )
    decision = step2_arbitration.PairArbitrationDecision(
        pair_id="PAIR_A_B",
        component_id="component_0001",
        single_pair_legal=True,
        arbitration_status="win",
        endpoint_boundary_penalty=0,
        strong_anchor_win_count=0,
        corridor_naturalness_score=0,
        contested_trunk_coverage_count=0,
        contested_trunk_coverage_ratio=0.0,
        pair_support_expansion_penalty=0,
        internal_endpoint_penalty=0,
        body_connectivity_support=1.0,
        semantic_conflict_penalty=0,
        lose_reason="",
        selected_option_id=option.option_id,
    )

    result = step2_validation_utils._pair_validation_from_option(
        option,
        decision=decision,
        conflict_pair_id=None,
        left_turn_excluded_mode="strict",
        compact_release_payloads=True,
    )

    assert result.candidate_channel_road_ids == ("r1", "r2")
    assert result.segment_road_ids == ("r1", "r2")
    assert result.support_info["segment_body_candidate_road_ids"] == ["r1", "r2"]
    assert result.support_info["non_trunk_components"][0]["road_ids"] == ["r2"]
    assert result.support_info["step3_residual_infos"][0]["road_id"] == "r2"


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
