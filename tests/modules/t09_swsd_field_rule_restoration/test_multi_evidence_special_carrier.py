from __future__ import annotations

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arrow_evidence import (
    evaluate_road_arrow_directions,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.decision import (
    resolve_multi_evidence_movement,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.restriction_evidence import (
    match_restriction_evidence,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    ArrowInput,
    DecisionSource,
    DecisionStatus,
    EvidencePriority,
    EvidenceType,
    InferenceLevel,
    RestorationStrategy,
    RoadAttributes,
    RoadPair,
    RuleScope,
    T09ArmMovement,
    T09SwsdArm,
    VerificationStatus,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.special_carrier import (
    SpecialCarrierArmProfile,
    build_special_carrier_arm_profile,
    detect_special_carrier_evidence,
    evaluate_special_carrier_decision,
)


def _movement(road_id: str, movement_type: str) -> T09ArmMovement:
    return T09ArmMovement(
        junction_id="junction_1",
        movement_id=f"movement_{road_id}_{movement_type}",
        from_arm_id="arm_in",
        to_arm_id="arm_out",
        movement_type=movement_type,
        candidate_road_pair_count=1,
        carrier_universe_status="available",
        carrier_road_pairs=(RoadPair(road_id, f"out_{movement_type}"),),
    )


def _arrow(arrow_id: str, road_id: str, code: str) -> ArrowInput:
    return ArrowInput(
        arrow_id=arrow_id,
        road_id=road_id,
        lane_codes=(code,),
        direction_matched=True,
        lane_sequence_complete=True,
        lane_dir=2,
        road_direction=2,
        seq_start=1,
        seq_end=1,
        source_arrow_dir=code,
        sequence_metadata_status="complete",
        properties={
            "lane_dir": 2,
            "road_direction": 2,
            "lane_count": 1,
            "seq_start": 1,
            "seq_end": 1,
            "source_arrow_dir": code,
        },
    )


def _profile(
    direction: str,
    *,
    role: str = "segment_connector",
    kind: str | None = None,
) -> SpecialCarrierArmProfile:
    special_id = f"advance_{direction}"
    bit = 128 if direction == "right" else 256
    seed_ids = ("main", special_id) if role == "incident_seed" else ("main",)
    connector_ids = (special_id,) if role == "segment_connector" else tuple()
    parallel_ids = (special_id,) if role == "parallel_branch" else tuple()
    arm = T09SwsdArm(
        junction_id="junction_1",
        arm_id="arm_in",
        seed_road_ids=seed_ids,
        connector_road_ids=connector_ids,
        approach_road_ids=("main", special_id),
        trunk_road_ids=seed_ids,
        parallel_branch_road_ids=parallel_ids,
    )
    return build_special_carrier_arm_profile(
        arm=arm,
        roads=(
            RoadAttributes(road_id="main"),
            RoadAttributes(road_id=special_id, kind=kind, formway=bit),
        ),
    )


def _resolve(
    movement: T09ArmMovement,
    *,
    profile: SpecialCarrierArmProfile,
    arrows: tuple[ArrowInput, ...] = tuple(),
):
    return resolve_multi_evidence_movement(
        movement=movement,
        restriction_result=match_restriction_evidence(movement, tuple()),
        road_arrow_decisions=evaluate_road_arrow_directions(movement, arrows),
        special_profile=profile,
    )


def test_scenario_12_advance_right_creates_main_displacement_candidate_and_dedicated_support() -> None:
    profile = _profile("right", role="segment_connector")

    main = evaluate_special_carrier_decision(
        profile,
        road_id="main",
        movement_type="right",
    )
    dedicated = evaluate_special_carrier_decision(
        profile,
        road_id="advance_right",
        movement_type="right",
    )

    assert main is not None
    assert main.decision_status == DecisionStatus.UNVERIFIED
    assert main.decision_scope == RuleScope.CORE_JUNCTION_DISPLACEMENT
    assert main.inference_level == InferenceLevel.WEAK_DERIVED
    assert "core_junction_displacement_weak_candidate" in main.risk_flags
    assert dedicated is not None
    assert dedicated.decision_status == DecisionStatus.SUPPORTED
    assert dedicated.decision_scope == RuleScope.SPECIAL_CARRIER
    assert dedicated.inference_level == InferenceLevel.WEAK_DERIVED


def test_scenario_13_laneinfo_right_support_wins_over_main_displacement_inference() -> None:
    profile = _profile("right", role="segment_connector")
    movement = _movement("main", "right")
    result = _resolve(
        movement,
        profile=profile,
        arrows=(_arrow("main_right", "main", "c"),),
    )

    rule = result.restored_rules[0]
    assert rule.decision_status == DecisionStatus.SUPPORTED
    assert rule.decision_source == DecisionSource.LANEINFO
    assert rule.evidence_priority == EvidencePriority.LANEINFO
    assert any(
        entry.overridden_source == DecisionSource.SPECIAL_CARRIER
        for entry in rule.override_chain
    )
    assert any(
        item.evidence_type == EvidenceType.SPECIAL_CARRIER
        and item.decision_scope == RuleScope.CORE_JUNCTION_DISPLACEMENT
        for item in result.evidence_items
    )
    assert all(
        not (
            item.evidence_type == EvidenceType.SPECIAL_CARRIER
            and item.supports_prohibition
        )
        for item in result.evidence_items
    )


def test_scenario_14_advance_right_other_direction_is_only_weak_candidate() -> None:
    result = _resolve(
        _movement("advance_right", "straight"),
        profile=_profile("right", role="segment_connector"),
    )

    rule = result.restored_rules[0]
    assert rule.decision_status == DecisionStatus.PROHIBITED
    assert rule.decision_source == DecisionSource.SPECIAL_CARRIER
    assert rule.decision_scope == RuleScope.SPECIAL_CARRIER
    assert rule.inference_level == InferenceLevel.WEAK_DERIVED
    assert (
        rule.verification_status
        == VerificationStatus.UNVERIFIED_DUE_TO_MISSING_FRCSD_LANEINFO
    )


def test_scenario_15_explicit_straight_laneinfo_prevents_special_carrier_exclusion() -> None:
    movement = _movement("advance_right", "straight")
    result = _resolve(
        movement,
        profile=_profile("right", role="segment_connector"),
        arrows=(_arrow("advance_right_straight", "advance_right", "a"),),
    )

    rule = result.restored_rules[0]
    assert rule.decision_status == DecisionStatus.SUPPORTED
    assert rule.decision_source == DecisionSource.LANEINFO
    assert rule.evidence_priority == EvidencePriority.LANEINFO
    assert any(
        entry.overridden_source == DecisionSource.SPECIAL_CARRIER
        for entry in rule.override_chain
    )
    assert all(item.decision_status != DecisionStatus.PROHIBITED for item in (rule,))


def test_scenario_16_advance_left_is_symmetric_with_advance_right() -> None:
    profile = _profile("left", role="segment_connector")

    main = evaluate_special_carrier_decision(
        profile,
        road_id="main",
        movement_type="left",
    )
    dedicated = evaluate_special_carrier_decision(
        profile,
        road_id="advance_left",
        movement_type="left",
    )
    other = evaluate_special_carrier_decision(
        profile,
        road_id="advance_left",
        movement_type="straight",
    )

    assert profile.advance_left_road_ids == ("advance_left",)
    assert profile.advance_right_road_ids == tuple()
    assert main is not None and main.decision_status == DecisionStatus.UNVERIFIED
    assert main.decision_scope == RuleScope.CORE_JUNCTION_DISPLACEMENT
    assert dedicated is not None and dedicated.decision_status == DecisionStatus.SUPPORTED
    assert other is not None and other.decision_status == DecisionStatus.PROHIBITED
    assert other.inference_level == InferenceLevel.WEAK_DERIVED


def test_scenario_17_auxiliary_bypass_and_pre_junction_right_have_distinct_states() -> None:
    auxiliary = _profile(
        "right",
        role="segment_connector",
        kind="road12|road0a",
    )
    bypass = _profile("right", role="segment_connector")
    pre_junction = _profile("right", role="incident_seed")

    auxiliary_road = auxiliary.road_profiles[0]
    bypass_road = bypass.road_profiles[0]
    pre_junction_road = pre_junction.road_profiles[0]
    assert auxiliary_road.carrier_type == "auxiliary_right_turn_unverified"
    assert "kind_auxiliary_hint_not_decision_source" in auxiliary_road.risk_flags
    assert bypass_road.carrier_type == "bypass_core_junction_candidate"
    assert pre_junction_road.carrier_type == "pre_junction_through_core"
    assert auxiliary_road.classification_status == DecisionStatus.MANUAL_REVIEW_REQUIRED
    assert bypass_road.classification_status == DecisionStatus.MANUAL_REVIEW_REQUIRED
    assert pre_junction_road.classification_status == DecisionStatus.SUPPORTED

    bypass_main = evaluate_special_carrier_decision(
        bypass,
        road_id="main",
        movement_type="right",
    )
    pre_junction_main = evaluate_special_carrier_decision(
        pre_junction,
        road_id="main",
        movement_type="right",
    )
    assert bypass_main is not None and bypass_main.decision_status == DecisionStatus.UNVERIFIED
    assert pre_junction_main is not None and pre_junction_main.decision_status == DecisionStatus.UNKNOWN
    assert pre_junction_main.verification_status == VerificationStatus.MANUAL_REVIEW_REQUIRED


def test_kind_only_does_not_trigger_v2_special_carrier() -> None:
    arm = T09SwsdArm(
        junction_id="junction_1",
        arm_id="arm_in",
        seed_road_ids=("main",),
        connector_road_ids=("kind_only",),
        trunk_road_ids=("main",),
    )
    roads = (RoadAttributes(road_id="kind_only", kind="road12|road0a"),)

    profile = build_special_carrier_arm_profile(arm=arm, roads=roads)
    v2_evidence = detect_special_carrier_evidence(
        junction_id=arm.junction_id,
        arm_id=arm.arm_id,
        arm=arm,
        roads=roads,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    assert profile.road_profiles == tuple()
    assert profile.advance_right_road_ids == tuple()
    assert v2_evidence == tuple()
    assert detect_special_carrier_evidence(
        junction_id=arm.junction_id,
        arm_id=arm.arm_id,
        roads=roads,
    )
