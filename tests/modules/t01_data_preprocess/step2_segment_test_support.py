from __future__ import annotations

from typing import Any

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


__all__ = [name for name in globals() if not name.startswith("__")]
