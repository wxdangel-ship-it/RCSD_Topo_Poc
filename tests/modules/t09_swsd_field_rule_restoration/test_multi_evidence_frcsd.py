from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.t08_preprocess.vector_io import write_gpkg, write_json
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import run_t09_frcsd_restriction_modeling
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.frcsd_restriction import (
    _parse_int,
    _read_records_with_audit,
)


V1 = "restriction_only_v1"
V2 = "multi_evidence_v2"


@dataclass(frozen=True)
class _Step3Inputs:
    arms: Path
    movements: Path
    rules: Path
    roads: Path
    nodes: Path
    relations: Path


def _arm_rule(
    *,
    rule_id: str = "rule:arm",
    strategy: str = V2,
    condition_identity: str = "condition:all-day",
    condition_type: str = "1",
    condition_payload: list[dict[str, Any]] | None = None,
    verification_status: str = "verified_swsd",
    scope_promotion_status: str = "arm_to_arm_confirmed",
    promotion_allowed: bool = True,
) -> dict[str, Any]:
    return {
        "rule_id": rule_id,
        "junction_id": "j",
        "movement_id": "movement:straight",
        "from_arm_id": "arm:in",
        "to_arm_id": "arm:out",
        "movement_type": "straight",
        "strategy_version": strategy,
        "field_rule_status": "fully_prohibited",
        "rule_scope": "arm_to_arm",
        "decision_status": "prohibited",
        "decision_source": "restriction",
        "decision_scope": "arm_to_arm",
        "evidence_priority": "restriction",
        "inference_level": "explicit",
        "verification_status": verification_status,
        "supporting_evidence_ids": [f"evidence:{rule_id}"],
        "conflicting_evidence_ids": [],
        "override_chain": [],
        "from_road_ids": ["sw_in"],
        "to_road_ids": ["sw_out"],
        "road_pairs": [{"from_road_id": "sw_in", "to_road_id": "sw_out"}],
        "source_restriction_ids": [f"restriction:{rule_id}"],
        "condition_type": condition_type,
        "condition_payload": condition_payload or [{"CondType": condition_type}],
        "condition_identity": condition_identity,
        "condition_semantics_status": "unknown",
        "scope_promotion_status": scope_promotion_status,
        "scope_promotion_reason": "test_fixture",
        "scope_promotion_audit": {"promotion_allowed": promotion_allowed},
        "confidence": 1.0,
        "risk_flags": [],
    }


def _road_rule(
    *,
    source: str,
    scope: str,
    rule_id: str,
    strategy: str = V2,
) -> dict[str, Any]:
    rule = _arm_rule(rule_id=rule_id, strategy=strategy, condition_identity="", condition_type="")
    rule.update(
        {
            "field_rule_status": "partially_prohibited",
            "rule_scope": scope,
            "decision_source": source,
            "decision_scope": scope,
            "evidence_priority": source,
            "inference_level": "derived" if source == "laneinfo" else "weak_derived",
            "verification_status": "verified_swsd",
            "condition_payload": [],
            "source_restriction_ids": [],
        }
    )
    return rule


def _road_feature(
    road_id: str,
    snodeid: str,
    enodeid: str,
    source: int | str,
    coords: list[tuple[float, float]],
    *,
    direction: int = 2,
) -> dict[str, Any]:
    return {
        "properties": {
            "id": road_id,
            "snodeid": snodeid,
            "enodeid": enodeid,
            "direction": direction,
            "source": source,
        },
        "geometry": LineString(coords),
    }


def _relation_feature(
    *,
    segment_id: str,
    status: str,
    road_ids: list[str],
    sources: list[int | str],
    mapped_node_ids: list[str],
    geometry: LineString,
) -> dict[str, Any]:
    return {
        "properties": {
            "swsd_segment_id": segment_id,
            "relation_status": status,
            "frcsd_road_ids": road_ids,
            "frcsd_road_source_values": sources,
            "swsd_to_frcsd_node_map": [
                {"swsd_node_id": "j", "frcsd_node_ids": mapped_node_ids, "node_role": "junc_node"}
            ],
        },
        "geometry": geometry,
    }


def _write_case(
    root: Path,
    *,
    rules: list[dict[str, Any]],
    from_status: str | None = "replaced",
    to_status: str | None = "replaced",
    fallback_from_seed: bool = False,
    ambiguous_from: bool = False,
    missing_from_road: bool = False,
    invalid_from_direction: bool = False,
    missing_frcsd_junction_node: bool = False,
    missing_swsd_junction_node: bool = False,
    unresolved_from_junction_direction: bool = False,
    replaced_from_source2: bool = False,
    fallback_with_successful_relation: bool = False,
    declared_missing_from_relation: bool = False,
    failed_from_relation: bool = False,
    from_mapped_node_ids: list[str] | None = None,
    replaced_same_id_source1_with_global_source2: bool = False,
    from_relation_sources: tuple[int | str, ...] | None = None,
    missing_from_far_endpoint: bool = False,
    from_road_source_override: int | str | None = None,
    global_source2_for_missing_from: bool = False,
) -> _Step3Inputs:
    root.mkdir(parents=True, exist_ok=True)
    inputs = _Step3Inputs(
        arms=root / "arms.json",
        movements=root / "movements.json",
        rules=root / "rules.json",
        roads=root / "frcsd_roads.gpkg",
        nodes=root / "frcsd_nodes.gpkg",
        relations=root / "segment_relations.gpkg",
    )
    write_json(
        inputs.arms,
        [
            {
                "junction_id": "j",
                "arm_id": "arm:in",
                "member_node_ids": ["j"],
                "segment_ids": (
                    ["seg:missing"]
                    if declared_missing_from_relation
                    else ["seg:in"]
                    if failed_from_relation or fallback_with_successful_relation
                    else []
                    if fallback_from_seed
                    else ["seg:in"]
                ),
                "approach_road_ids": ["sw_in"],
                "exit_road_ids": [],
            },
            {
                "junction_id": "j",
                "arm_id": "arm:out",
                "member_node_ids": ["j"],
                "segment_ids": ["seg:out"],
                "approach_road_ids": [],
                "exit_road_ids": ["sw_out"],
            },
        ],
    )
    write_json(
        inputs.movements,
        [
            {
                "junction_id": "j",
                "movement_id": "movement:straight",
                "from_arm_id": "arm:in",
                "to_arm_id": "arm:out",
                "movement_type": "straight",
                "prohibition_reason": "explicit_restriction",
                "prohibition_confidence": 1.0,
                "risk_flags": [],
            }
        ],
    )
    write_json(inputs.rules, rules)

    node_features = [
        {"properties": {"id": "nw1", "mainnodeid": 0, "source": 1}, "geometry": Point(-10, 0)},
        {"properties": {"id": "ne1", "mainnodeid": 0, "source": 1}, "geometry": Point(10, 0)},
        {"properties": {"id": "nw2", "mainnodeid": 0, "source": 2}, "geometry": Point(-10, -1)},
        {"properties": {"id": "ne2", "mainnodeid": 0, "source": 2}, "geometry": Point(10, -1)},
        {"properties": {"id": "other_w", "mainnodeid": 0, "source": 2}, "geometry": Point(-10, -2)},
        {"properties": {"id": "other_e", "mainnodeid": 0, "source": 2}, "geometry": Point(10, -2)},
    ]
    if not missing_swsd_junction_node:
        node_features.append(
            {"properties": {"id": "j", "mainnodeid": 0, "source": 2}, "geometry": Point(0, 0)}
        )
    if not missing_frcsd_junction_node and not missing_swsd_junction_node:
        node_features.append(
            {"properties": {"id": "fj", "mainnodeid": "j", "source": 1}, "geometry": Point(0, 0)}
        )
    write_gpkg(inputs.nodes, node_features, crs_text="EPSG:3857")

    road_features: list[dict[str, Any]] = []
    relation_features: list[dict[str, Any]] = []
    from_direction = 9 if invalid_from_direction else 2
    source2_end_node = "other_e" if unresolved_from_junction_direction else "j"
    source1_start_node = "ghost_from_far" if missing_from_far_endpoint else "nw1"
    source2_start_node = "ghost_from_far" if missing_from_far_endpoint else "nw2"
    if fallback_from_seed:
        road_features.append(
            _road_feature("sw_in", "nw2", source2_end_node, 2, [(-10, -1), (0, 0)])
        )
        if fallback_with_successful_relation:
            relation_features.append(
                _relation_feature(
                    segment_id="seg:in",
                    status="replaced",
                    road_ids=[],
                    sources=[],
                    mapped_node_ids=["fj"],
                    geometry=LineString([(-10, 0), (0, 0)]),
                )
            )
        elif failed_from_relation:
            relation_features.append(
                _relation_feature(
                    segment_id="seg:in",
                    status="failed",
                    road_ids=[],
                    sources=[],
                    mapped_node_ids=["fj"],
                    geometry=LineString([(-10, 0), (0, 0)]),
                )
            )
    elif from_status == "replaced":
        if missing_from_road and global_source2_for_missing_from:
            road_features.append(
                _road_feature("sw_in", "nw2", "j", 2, [(-10, -1), (0, 0)])
            )
        if not missing_from_road:
            if replaced_from_source2:
                road_features.append(
                    _road_feature("sw_in", source2_start_node, "j", 2, [(-10, -1), (0, 0)])
                )
            elif replaced_same_id_source1_with_global_source2:
                road_features.extend(
                    [
                        _road_feature("sw_in", source1_start_node, "fj", 1, [(-10, 0), (0, 0)]),
                        _road_feature("sw_in", "nw2", "j", 2, [(-10, -1), (0, 0)]),
                    ]
                )
            else:
                road_features.append(
                    _road_feature(
                        "fr_in",
                        source1_start_node,
                        "fj",
                        from_road_source_override or 1,
                        [(-10, 0), (0, 0)],
                        direction=from_direction,
                    )
                )
            if ambiguous_from:
                road_features.append(
                    _road_feature("fr_in_b", "other_w", "fj", 1, [(-10, -2), (0, 0)])
                )
        relation_features.append(
            _relation_feature(
                segment_id="seg:in",
                status="replaced",
                road_ids=(
                    ["missing_in"]
                    if missing_from_road
                    else (
                        ["sw_in"]
                        if replaced_from_source2 or replaced_same_id_source1_with_global_source2
                        else (["fr_in", "fr_in_b"] if ambiguous_from else ["fr_in"])
                    )
                ),
                sources=(
                    list(from_relation_sources)
                    if from_relation_sources is not None
                    else [2] if replaced_from_source2 else [1]
                ),
                mapped_node_ids=from_mapped_node_ids or ["fj"],
                geometry=LineString([(-10, 0), (0, 0)]),
            )
        )
    elif from_status == "retained_swsd":
        road_features.append(
            _road_feature("sw_in", source2_start_node, source2_end_node, 2, [(-10, -1), (0, 0)])
        )
        relation_features.append(
            _relation_feature(
                segment_id="seg:in",
                status="retained_swsd",
                road_ids=["sw_in"],
                sources=(
                    list(from_relation_sources)
                    if from_relation_sources is not None
                    else [2]
                ),
                mapped_node_ids=from_mapped_node_ids or ["j"],
                geometry=LineString([(-10, -1), (0, 0)]),
            )
        )
    elif from_status == "replaced+retained_swsd":
        road_features.extend(
            [
                _road_feature("fr_in", source1_start_node, "fj", 1, [(-10, 0), (0, 0)]),
                _road_feature("sw_in", source2_start_node, "j", 2, [(-10, -1), (0, 0)]),
                _road_feature("other_in", "other_w", "j", 2, [(-10, -2), (0, 0)]),
            ]
        )
        relation_features.append(
            _relation_feature(
                segment_id="seg:in",
                status="replaced+retained_swsd",
                road_ids=["fr_in", "sw_in", "other_in"],
                sources=(
                    list(from_relation_sources)
                    if from_relation_sources is not None
                    else [1, 2]
                ),
                mapped_node_ids=["fj", "j"],
                geometry=LineString([(-10, 0), (0, 0)]),
            )
        )

    if to_status == "replaced":
        road_features.append(_road_feature("fr_out", "fj", "ne1", 1, [(0, 0), (10, 0)]))
        relation_features.append(
            _relation_feature(
                segment_id="seg:out",
                status="replaced",
                road_ids=["fr_out"],
                sources=[1],
                mapped_node_ids=["fj"],
                geometry=LineString([(0, 0), (10, 0)]),
            )
        )
    elif to_status == "retained_swsd":
        road_features.append(_road_feature("sw_out", "j", "ne2", 2, [(0, 0), (10, -1)]))
        relation_features.append(
            _relation_feature(
                segment_id="seg:out",
                status="retained_swsd",
                road_ids=["sw_out"],
                sources=[2],
                mapped_node_ids=["j"],
                geometry=LineString([(0, 0), (10, -1)]),
            )
        )
    elif to_status == "replaced+retained_swsd":
        road_features.extend(
            [
                _road_feature("fr_out", "fj", "ne1", 1, [(0, 0), (10, 0)]),
                _road_feature("sw_out", "j", "ne2", 2, [(0, 0), (10, -1)]),
                _road_feature("other_out", "j", "other_e", 2, [(0, 0), (10, -2)]),
            ]
        )
        relation_features.append(
            _relation_feature(
                segment_id="seg:out",
                status="replaced+retained_swsd",
                road_ids=["fr_out", "sw_out", "other_out"],
                sources=[1, 2],
                mapped_node_ids=["fj", "j"],
                geometry=LineString([(0, 0), (10, 0)]),
            )
        )

    write_gpkg(inputs.roads, road_features, crs_text="EPSG:3857")
    write_gpkg(inputs.relations, relation_features, crs_text="EPSG:3857")
    return inputs


def _run(inputs: _Step3Inputs, output_root: Path, *, strategy: str):
    return run_t09_frcsd_restriction_modeling(
        arms_path=inputs.arms,
        movements_path=inputs.movements,
        restored_rules_path=inputs.rules,
        frcsd_road_path=inputs.roads,
        frcsd_node_path=inputs.nodes,
        segment_relation_path=inputs.relations,
        output_dir=output_root,
        run_id="run",
        strategy_version=strategy,
    )


def _json_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [dict(item["properties"]) for item in payload["features"]]


@pytest.mark.parametrize(
    ("relation_status", "expected_pairs"),
    [
        ("replaced", {("fr_in", "fr_out", "1", "1")}),
        ("retained_swsd", {("sw_in", "sw_out", "2", "2")}),
        (
            "replaced+retained_swsd",
            {
                ("fr_in", "fr_out", "1", "1"),
                ("fr_in", "sw_out", "1", "2"),
                ("sw_in", "fr_out", "2", "1"),
                ("sw_in", "sw_out", "2", "2"),
            },
        ),
    ],
)
def test_v2_arm_to_arm_restriction_is_stable_for_t06_carrier_statuses(
    tmp_path: Path,
    relation_status: str,
    expected_pairs: set[tuple[str, str, str, str]],
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status=relation_status,
        to_status=relation_status,
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == len(expected_pairs)
    assert result.candidate_count == 0
    rows = _json_rows(result.artifacts.frcsd_restriction_json)
    assert {
        (row["LinkID"], row["outLinkID"], row["from_road_source"], row["to_road_source"])
        for row in rows
    } == expected_pairs
    assert {row["decision_scope"] for row in rows} == {"arm_to_arm"}
    assert {row["verification_status"] for row in rows} == {"verified_frcsd"}
    assert result.artifacts.frcsd_restriction_candidates_gpkg.is_file()
    assert result.artifacts.frcsd_restriction_candidates_csv.is_file()
    assert result.artifacts.frcsd_restriction_candidates_json.is_file()


@pytest.mark.parametrize(
    ("relation_status", "declared_sources", "expected_risk"),
    [
        ("replaced", tuple(), "segment_relation_source_values_missing:seg:in:replaced"),
        ("replaced", (2,), "segment_relation_source_values_invalid:seg:in:replaced:2"),
        (
            "retained_swsd",
            (1,),
            "segment_relation_source_values_invalid:seg:in:retained_swsd:1",
        ),
        (
            "replaced+retained_swsd",
            ("unknown",),
            "segment_relation_source_values_invalid:seg:in:replaced+retained_swsd:unknown",
        ),
    ],
)
def test_v2_relation_source_gate_blocks_missing_unknown_or_wrong_source(
    tmp_path: Path,
    relation_status: str,
    declared_sources: tuple[int | str, ...],
    expected_risk: str,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status=relation_status,
        to_status=relation_status,
        from_relation_sources=declared_sources,
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert expected_risk in candidate["risk_flags"]
    assert "retained_swsd_seed_fallback_blocked_by_relation_gap" in candidate["risk_flags"]


def test_v2_relation_source_gate_audits_declared_to_actual_source_mismatch(
    tmp_path: Path,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status="replaced",
        to_status="replaced",
        from_relation_sources=(1,),
        from_road_source_override="unknown",
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert any(
        flag.startswith("segment_relation_road_source_mismatch:seg:in:fr_in:")
        for flag in candidate["risk_flags"]
    )


@pytest.mark.parametrize(
    ("source", "scope"),
    [("laneinfo", "road_direction_exclusion"), ("special_carrier", "special_carrier")],
)
def test_v2_derived_road_rules_are_unverified_candidates_without_arm_expansion(
    tmp_path: Path,
    source: str,
    scope: str,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_road_rule(source=source, scope=scope, rule_id=f"rule:{source}")],
        from_status="replaced+retained_swsd",
        to_status="replaced+retained_swsd",
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    row = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert (row["LinkID"], row["outLinkID"]) == ("sw_in", "sw_out")
    assert row["decision_scope"] == scope
    assert row["verification_status"] == "unverified_due_to_missing_frcsd_laneinfo"
    assert row["candidate_reason"] == "derived_rule_requires_frcsd_laneinfo"
    assert "unverified_due_to_missing_frcsd_laneinfo" in row["risk_flags"]


@pytest.mark.parametrize(
    ("promotion_status", "promotion_allowed", "reason_token"),
    [
        ("manual_review_required", True, "status=manual_review_required"),
        ("arm_to_arm_confirmed", False, "promotion_allowed_not_true"),
    ],
)
def test_v2_arm_stable_requires_confirmed_allowed_scope_promotion(
    tmp_path: Path,
    promotion_status: str,
    promotion_allowed: bool,
    reason_token: str,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[
            _arm_rule(
                scope_promotion_status=promotion_status,
                promotion_allowed=promotion_allowed,
            )
        ],
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert candidate["verification_status"] == "manual_review_required"
    assert candidate["candidate_reason"] == f"arm_scope_promotion_not_confirmed:{reason_token}"


@pytest.mark.parametrize("scope", ["arm_to_arm", "road_to_road"])
def test_v2_restriction_stable_requires_verified_swsd_source_rule(
    tmp_path: Path,
    scope: str,
) -> None:
    rule = (
        _arm_rule(verification_status="manual_review_required")
        if scope == "arm_to_arm"
        else _road_rule(source="restriction", scope=scope, rule_id="rule:road")
    )
    rule["verification_status"] = "manual_review_required"
    inputs = _write_case(tmp_path / "inputs", rules=[rule])
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert candidate["verification_status"] == "manual_review_required"
    assert candidate["candidate_reason"] == (
        "restriction_verification_not_stable:manual_review_required"
    )


def test_v2_candidate_semantic_twins_keep_distinct_source_rule_proposals(
    tmp_path: Path,
) -> None:
    rules = [
        _road_rule(
            source="laneinfo",
            scope="road_direction_exclusion",
            rule_id=rule_id,
        )
        for rule_id in ("rule:proposal:a", "rule:proposal:b")
    ]
    inputs = _write_case(tmp_path / "inputs", rules=rules)
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 2
    rows = _json_rows(result.artifacts.frcsd_restriction_candidates_json)
    assert {row["source_rule_id"] for row in rows} == {
        "rule:proposal:a",
        "rule:proposal:b",
    }
    assert {
        (
            row["LinkID"],
            row["outLinkID"],
            row["junction_id"],
            row["movement_type"],
            row["condition_identity"],
            row["decision_scope"],
        )
        for row in rows
    } == {("fr_in", "fr_out", "j", "straight", "", "road_direction_exclusion")}


def test_v2_retained_swsd_seed_fallback_remains_stable_and_audited(tmp_path: Path) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status=None,
        to_status="retained_swsd",
        fallback_from_seed=True,
        fallback_with_successful_relation=True,
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 1
    assert result.candidate_count == 0
    row = _json_rows(result.artifacts.frcsd_restriction_json)[0]
    assert (row["LinkID"], row["outLinkID"]) == ("sw_in", "sw_out")
    assert "retained_swsd_seed_fallback" in row["from_arm_relation_status"]
    assert "retained_swsd_seed_carrier_fallback" in row["risk_flags"]
    assert result.summary["arm_carrier_risk_flag_counts"]["retained_swsd_seed_carrier_fallback"] == 1


def test_v2_retained_source2_relation_with_missing_node_is_candidate_not_stable(
    tmp_path: Path,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status="retained_swsd",
        to_status="retained_swsd",
        missing_swsd_junction_node=True,
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert candidate["candidate_reason"] == "from_arm_approach_missing"
    assert any("frcsd_junction_node_missing:j" == flag for flag in candidate["risk_flags"])
    assert "frcsd_road_endpoint_node_missing:2:sw_in:enodeid=j" in candidate["risk_flags"]


def test_v2_seed_fallback_with_missing_registered_node_is_candidate_not_stable(
    tmp_path: Path,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status=None,
        to_status="retained_swsd",
        fallback_from_seed=True,
        missing_swsd_junction_node=True,
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert candidate["candidate_reason"] == "from_arm_approach_missing"
    assert any(
        flag.startswith("retained_swsd_seed_fallback_node_alias_missing:j")
        for flag in candidate["risk_flags"]
    )
    assert "retained_swsd_seed_carrier_fallback" not in candidate["risk_flags"]


def test_v2_source2_seed_with_unresolved_junction_direction_is_not_stable(
    tmp_path: Path,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status="retained_swsd",
        to_status="retained_swsd",
        unresolved_from_junction_direction=True,
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert candidate["candidate_reason"] == "from_arm_approach_missing"
    assert any(
        flag == "frcsd_road_junction_direction_unresolved:2:sw_in"
        for flag in candidate["risk_flags"]
    )
    assert (
        "retained_swsd_seed_fallback_blocked_by_declared_relation_road:sw_in"
        in candidate["risk_flags"]
    )


def test_v2_source2_under_replaced_relation_is_blocked_by_status_and_not_readded(
    tmp_path: Path,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status="replaced",
        to_status="replaced",
        replaced_from_source2=True,
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert candidate["candidate_reason"] == "from_arm_approach_missing"
    assert "segment_relation_source_values_invalid:seg:in:replaced:2" in candidate["risk_flags"]
    assert "retained_swsd_seed_fallback_blocked_by_relation_gap" in candidate["risk_flags"]


def test_v2_retained_declared_seed_with_ghost_mapped_node_cannot_fallback(
    tmp_path: Path,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status="retained_swsd",
        to_status="retained_swsd",
        from_mapped_node_ids=["ghost_node"],
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert "frcsd_junction_node_missing:ghost_node" in candidate["risk_flags"]
    assert "retained_swsd_seed_fallback_blocked_by_relation_gap" in candidate["risk_flags"]


def test_v2_missing_declared_relation_road_blocks_global_source2_fallback(
    tmp_path: Path,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        missing_from_road=True,
        global_source2_for_missing_from=True,
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert "frcsd_road_missing:relation:missing_in" in candidate["risk_flags"]
    assert "retained_swsd_seed_fallback_blocked_by_relation_gap" in candidate["risk_flags"]
    assert "retained_swsd_seed_carrier_fallback" not in candidate["risk_flags"]


def test_v2_missing_declared_central_node_blocks_global_source2_fallback(
    tmp_path: Path,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        replaced_same_id_source1_with_global_source2=True,
        from_mapped_node_ids=["ghost_node"],
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert "frcsd_junction_node_missing:ghost_node" in candidate["risk_flags"]
    assert "retained_swsd_seed_fallback_blocked_by_relation_gap" in candidate["risk_flags"]


def test_v2_replaced_source1_same_logical_id_blocks_global_source2_fallback(
    tmp_path: Path,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status="replaced",
        to_status="replaced",
        replaced_same_id_source1_with_global_source2=True,
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 1
    assert result.candidate_count == 0
    row = _json_rows(result.artifacts.frcsd_restriction_json)[0]
    assert (row["LinkID"], row["from_road_source"]) == ("sw_in", "1")
    assert (
        "retained_swsd_seed_fallback_blocked_by_declared_relation_road:sw_in"
        in row["risk_flags"]
    )


@pytest.mark.parametrize("relation_fault", ["missing", "failed"])
def test_v2_declared_relation_gap_blocks_seed_fallback_for_entire_arm(
    tmp_path: Path,
    relation_fault: str,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status=None,
        to_status="retained_swsd",
        fallback_from_seed=True,
        declared_missing_from_relation=relation_fault == "missing",
        failed_from_relation=relation_fault == "failed",
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert "retained_swsd_seed_fallback_blocked_by_relation_gap" in candidate["risk_flags"]
    assert any(
        flag.startswith(f"segment_relation_{relation_fault}")
        for flag in candidate["risk_flags"]
    )


@pytest.mark.parametrize("fault", ["missing_relation", "missing_road", "invalid_direction"])
def test_v2_missing_or_uninterpretable_carrier_is_not_stable_and_has_audit_reason(
    tmp_path: Path,
    fault: str,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status=None if fault == "missing_relation" else "replaced",
        to_status="replaced",
        missing_from_road=fault == "missing_road",
        invalid_from_direction=fault == "invalid_direction",
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    audit_text = json.dumps(
        {
            "skipped": result.summary["skipped_counts"],
            "candidate_reasons": result.summary["candidate_reason_counts"],
            "carrier_risks": result.summary["arm_carrier_risk_flag_counts"],
        },
        ensure_ascii=False,
        sort_keys=True,
    ).lower()
    expected_token = {
        "missing_relation": "segment_relation_missing",
        "missing_road": "road_missing",
        "invalid_direction": "direction",
    }[fault]
    assert expected_token in audit_text


def test_v2_missing_frcsd_node_is_not_silently_published(tmp_path: Path) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status="replaced",
        to_status="replaced",
        missing_frcsd_junction_node=True,
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    audit_text = json.dumps(result.summary, ensure_ascii=False, sort_keys=True).lower()
    assert "node" in audit_text


def test_v2_carrier_requires_both_road_endpoints_in_frcsd_node_aliases(
    tmp_path: Path,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        missing_from_far_endpoint=True,
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    candidate = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert candidate["candidate_reason"] == "from_arm_approach_missing"
    assert (
        "frcsd_road_endpoint_node_missing:1:fr_in:snodeid=ghost_from_far"
        in candidate["risk_flags"]
    )


def test_v2_ambiguous_road_to_road_mapping_becomes_candidate_not_cartesian_stable(tmp_path: Path) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_road_rule(source="restriction", scope="road_to_road", rule_id="rule:road-pair")],
        from_status="replaced",
        to_status="replaced",
        ambiguous_from=True,
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 1
    row = _json_rows(result.artifacts.frcsd_restriction_candidates_json)[0]
    assert "from_arm_approach_not_unique" in row["candidate_reason"]
    assert row["verification_status"] == "manual_review_required"


def test_v2_multi_pair_road_proposal_is_atomic_across_stable_and_candidate_layers(
    tmp_path: Path,
) -> None:
    rule = _road_rule(
        source="restriction",
        scope="road_to_road",
        rule_id="rule:atomic-pairs",
    )
    rule["from_road_ids"] = ["sw_in", "unmapped_in"]
    rule["to_road_ids"] = ["sw_out"]
    rule["road_pairs"] = [
        {"from_road_id": "sw_in", "to_road_id": "sw_out"},
        {"from_road_id": "unmapped_in", "to_road_id": "sw_out"},
    ]
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[rule],
        from_status="replaced+retained_swsd",
        to_status="replaced+retained_swsd",
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 0
    assert result.candidate_count == 2
    candidates = _json_rows(result.artifacts.frcsd_restriction_candidates_json)
    assert {row["source_rule_id"] for row in candidates} == {"rule:atomic-pairs"}
    assert {row["candidate_reason"] for row in candidates} == {
        "road_to_road_proposal_not_atomic",
        "road_to_road_mapping_not_exact:from_arm_approach_not_unique",
    }
    assert {row["LinkID"] for row in candidates} == {
        "sw_in",
        "unmapped_in",
    }


@pytest.mark.parametrize(
    ("run_strategy", "rule_strategy"),
    [(V2, V1), (V1, V2)],
)
def test_step3_rejects_explicit_strategy_mixing(
    tmp_path: Path,
    run_strategy: str,
    rule_strategy: str,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule(strategy=rule_strategy)],
        from_status="replaced",
        to_status="replaced",
    )
    result = _run(inputs, tmp_path / "out", strategy=run_strategy)

    assert result.restriction_count == 0
    assert result.candidate_count == 0
    mismatch_count = sum(
        count for reason, count in result.summary["skipped_counts"].items() if reason.startswith("rule_strategy_mismatch")
    )
    assert mismatch_count == 1


def test_v2_same_link_pair_keeps_distinct_condition_identities(tmp_path: Path) -> None:
    rules = [
        _arm_rule(
            rule_id="rule:condition:a",
            condition_identity="condition:a",
            condition_type="1",
            condition_payload=[{"CondType": 1, "raw_window": "A"}],
        ),
        _arm_rule(
            rule_id="rule:condition:b",
            condition_identity="condition:b",
            condition_type="2",
            condition_payload=[{"CondType": 2, "raw_window": "B"}],
        ),
    ]
    inputs = _write_case(
        tmp_path / "inputs",
        rules=rules,
        from_status="replaced",
        to_status="replaced",
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)

    assert result.restriction_count == 2
    rows = _json_rows(result.artifacts.frcsd_restriction_json)
    assert {row["condition_identity"] for row in rows} == {"condition:a", "condition:b"}
    assert {row["CondType"] for row in rows} == {"1", "2"}
    assert {json.dumps(row["condition_payload"], sort_keys=True) for row in rows} == {
        json.dumps([{"CondType": 1, "raw_window": "A"}], sort_keys=True),
        json.dumps([{"CondType": 2, "raw_window": "B"}], sort_keys=True),
    }


def test_step3_summary_records_complete_input_crs_runtime_and_stage_audit(
    tmp_path: Path,
) -> None:
    inputs = _write_case(
        tmp_path / "inputs",
        rules=[_arm_rule()],
        from_status="replaced",
        to_status="replaced",
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)
    summary = result.summary

    assert set(summary["input_audit"]) == {
        "arms",
        "movements",
        "restored_rules",
        "frcsd_roads",
        "frcsd_nodes",
        "segment_relations",
    }
    for audit in summary["input_audit"].values():
        assert Path(audit["resolved_path"]).is_file()
        assert "requested_layer_name" in audit
        assert "resolved_layer_name" in audit
        assert isinstance(audit["field_names"], list)
        assert isinstance(audit["feature_count"], int)
        assert "source_crs" in audit
        assert "output_crs" in audit
        assert isinstance(audit["crs_transform_executed"], bool)

    for vector_key in ("frcsd_roads", "frcsd_nodes", "segment_relations"):
        audit = summary["input_audit"][vector_key]
        assert audit["source_crs"] == "EPSG:3857"
        assert audit["output_crs"] == "EPSG:3857"
        assert audit["resolved_layer_name"]
    assert summary["output_crs"] == "EPSG:3857"
    assert isinstance(summary["qa"]["crs_transform_executed"], bool)
    assert summary["qa"]["crs_transform_executed"] is False
    assert summary["runtime_environment"]["python_version"]
    assert summary["runtime_environment"]["python_executable"]
    assert set(summary["stage_durations_seconds"]) == {
        "read_inputs_seconds",
        "build_carriers_seconds",
        "model_rules_seconds",
        "write_artifacts_before_summary_seconds",
        "run_before_summary_write_seconds",
    }
    assert all(value >= 0 for value in summary["stage_durations_seconds"].values())
    assert "summary" in summary["stage_duration_scope"]
    assert summary["output_row_counts"] == {"stable_rows": 1, "candidate_rows": 0}
    assert "funnel" in summary["processing_event_counts"]["count_semantics"]


def test_json_geometry_declared_crs_is_transformed_and_qa_matches(
    tmp_path: Path,
) -> None:
    spatial_json = tmp_path / "spatial.json"
    write_json(
        spatial_json,
        {
            "features": [
                {
                    "properties": {"id": "point:1"},
                    "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
                    "crs": "EPSG:4326",
                }
            ]
        },
    )
    loaded = _read_records_with_audit(
        spatial_json,
        layer_name=None,
        target_epsg=3857,
    )
    point = loaded.records[0].geometry
    assert point is not None
    assert point.x == pytest.approx(111319.490793, rel=1e-8)
    assert point.y == pytest.approx(111325.142866, rel=1e-8)
    assert loaded.audit["source_crs"] == "EPSG:4326"
    assert loaded.audit["output_crs"] == "EPSG:3857"
    assert loaded.audit["crs_transform_executed"] is True

    inputs = _write_case(tmp_path / "inputs", rules=[_arm_rule()])
    arm_rows = json.loads(inputs.arms.read_text(encoding="utf-8"))
    write_json(
        inputs.arms,
        {
            "features": [
                {
                    "properties": properties,
                    "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
                    "crs": "EPSG:4326",
                }
                for properties in arm_rows
            ]
        },
    )
    result = _run(inputs, tmp_path / "out", strategy=V2)
    assert result.summary["input_audit"]["arms"]["crs_transform_executed"] is True
    assert result.summary["qa"]["crs_transform_executed"] is True


def test_json_geometry_mixed_declared_crs_is_rejected(tmp_path: Path) -> None:
    spatial_json = tmp_path / "mixed.json"
    write_json(
        spatial_json,
        {
            "features": [
                {
                    "properties": {"id": "a"},
                    "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                    "crs": "EPSG:4326",
                },
                {
                    "properties": {"id": "b"},
                    "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                    "crs": "EPSG:3857",
                },
            ]
        },
    )

    with pytest.raises(ValueError, match="mixed CRS"):
        _read_records_with_audit(
            spatial_json,
            layer_name=None,
            target_epsg=3857,
        )


def test_json_geometry_semantically_equivalent_crs_declarations_are_accepted(
    tmp_path: Path,
) -> None:
    spatial_json = tmp_path / "equivalent_crs.json"
    write_json(
        spatial_json,
        {
            "crs": "EPSG:4326",
            "features": [
                {
                    "properties": {"id": "equivalent"},
                    "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
                    "crs": "urn:ogc:def:crs:EPSG::4326",
                }
            ],
        },
    )

    loaded = _read_records_with_audit(
        spatial_json,
        layer_name=None,
        target_epsg=3857,
    )

    assert loaded.audit["source_crs"] == "EPSG:4326"
    assert loaded.audit["crs_transform_executed"] is True


def test_json_geometry_without_declared_crs_is_rejected(tmp_path: Path) -> None:
    spatial_json = tmp_path / "missing_crs.json"
    write_json(
        spatial_json,
        {
            "features": [
                {
                    "properties": {"id": "missing"},
                    "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                }
            ]
        },
    )

    with pytest.raises(ValueError, match="requires a declared CRS"):
        _read_records_with_audit(
            spatial_json,
            layer_name=None,
            target_epsg=3857,
        )


def test_json_geometry_partial_feature_crs_without_top_level_is_rejected(
    tmp_path: Path,
) -> None:
    spatial_json = tmp_path / "partial_crs.json"
    write_json(
        spatial_json,
        {
            "features": [
                {
                    "properties": {"id": "declared"},
                    "geometry": {"type": "Point", "coordinates": [0.0, 0.0]},
                    "crs": "EPSG:4326",
                },
                {
                    "properties": {"id": "missing"},
                    "geometry": {"type": "Point", "coordinates": [1.0, 1.0]},
                },
            ]
        },
    )

    with pytest.raises(ValueError, match="feature CRS is missing at indexes 2"):
        _read_records_with_audit(
            spatial_json,
            layer_name=None,
            target_epsg=3857,
        )


@pytest.mark.parametrize("value", [2.5, "2.5", float("nan"), float("inf"), "-inf"])
def test_parse_int_rejects_fractional_or_non_finite_values(value: Any) -> None:
    assert _parse_int(value) is None


@pytest.mark.parametrize(("value", "expected"), [(2, 2), ("2", 2), ("2.0", 2), (-3.0, -3)])
def test_parse_int_accepts_only_finite_integral_values(value: Any, expected: int) -> None:
    assert _parse_int(value) == expected
