from __future__ import annotations

from dataclasses import replace

import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arrow_evidence import (
    evaluate_road_arrow_directions,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arm_builder import (
    build_swsd_arms,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.decision import (
    resolve_multi_evidence_movement,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.restriction_evidence import (
    RestrictionMatchResult,
    match_restriction_evidence,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.movement_builder import (
    build_arm_movements,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.restoration import (
    restore_field_rules,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    ArrowInput,
    DecisionSource,
    DecisionStatus,
    EvidencePriority,
    EvidenceProvenance,
    EvidenceType,
    InferenceLevel,
    ProhibitionReason,
    ProhibitionStatus,
    RestrictionInput,
    RestorationStrategy,
    RoadAttributes,
    RoadPair,
    RuleScope,
    SWSDSegmentInput,
    SWSDRoadInput,
    T09ArmMovement,
    T09EvidenceItem,
    T09SwsdArm,
    VerificationStatus,
    to_jsonable,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.special_carrier import (
    SpecialCarrierArmProfile,
    SpecialCarrierRoadProfile,
)


def _movement(
    movement_type: str = "right",
    *,
    pairs: tuple[RoadPair, ...] = (RoadPair("in_1", "out_1"),),
) -> T09ArmMovement:
    return T09ArmMovement(
        junction_id="junction_1",
        movement_id=f"movement_{movement_type}",
        from_arm_id="arm_in",
        to_arm_id="arm_out",
        movement_type=movement_type,
        candidate_road_pair_count=len(pairs),
        carrier_universe_status="available",
        carrier_road_pairs=pairs,
    )


def _audited_equivalent_arm(
    arm_id: str,
    *,
    role: str,
    road_ids: tuple[str, ...],
    segment_membership_status: str = "consistent",
) -> T09SwsdArm:
    sorted_ids = tuple(sorted(road_ids))
    segment_id = f"segment_{arm_id}"
    return T09SwsdArm(
        junction_id="junction_1",
        arm_id=arm_id,
        member_node_ids=("junction_1",),
        seed_road_ids=sorted_ids,
        segment_ids=(segment_id,),
        t01_segment_ids=(segment_id,),
        segment_membership_status=segment_membership_status,
        inbound_road_ids=sorted_ids if role == "approach" else tuple(),
        outbound_road_ids=sorted_ids if role == "exit" else tuple(),
        approach_road_ids=sorted_ids if role == "approach" else tuple(),
        exit_road_ids=sorted_ids if role == "exit" else tuple(),
        trunk_road_ids=sorted_ids,
        angle_deg=180.0 if role == "approach" else 90.0,
        terminal_kind="segment_junc_node",
        audit_refs=(
            "grouping=segment_local_direction",
            f"seed_road_ids={','.join(sorted_ids)}",
            f"terminal_node_ids=terminal_{arm_id}",
        ),
    )


def _built_two_by_two_scope_fixture(
    *,
    from_membership: str = "complete_t01",
) -> tuple[tuple[T09SwsdArm, ...], T09ArmMovement]:
    from_segment_ids = (
        ("stale_from",) if from_membership == "stale_conflict" else tuple()
    )
    roads = (
        SWSDRoadInput("in_1", "west_1", "junction_1", 2, segment_ids=from_segment_ids),
        SWSDRoadInput("in_2", "west_2", "junction_1", 2, segment_ids=from_segment_ids),
        SWSDRoadInput("out_1", "junction_1", "north_1", 2),
        SWSDRoadInput("out_2", "junction_1", "north_2", 2),
    )
    from_t01_road_ids = (
        ("in_1",)
        if from_membership == "partial_t01"
        else ("in_1", "in_2")
    )
    segments = (
        SWSDSegmentInput(
            segment_id="official_from",
            junc_nodes=("junction_1",),
            road_ids=from_t01_road_ids,
        ),
        SWSDSegmentInput(
            segment_id="official_to",
            junc_nodes=("junction_1",),
            road_ids=("out_1", "out_2"),
        ),
    )
    road_geometries = {
        "in_1": LineString([(-20.0, -1.0), (0.0, 0.0)]),
        "in_2": LineString([(-20.0, 1.0), (0.0, 0.0)]),
        "out_1": LineString([(0.0, 0.0), (-1.0, 20.0)]),
        "out_2": LineString([(0.0, 0.0), (1.0, 20.0)]),
    }
    arms = build_swsd_arms(
        junction_id="junction_1",
        member_node_ids=("junction_1",),
        roads=roads,
        segments=segments,
        road_geometries=road_geometries,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )
    movements = build_arm_movements(junction_id="junction_1", arms=arms)
    movement = next(
        item
        for item in movements
        if {pair.from_road_id for pair in item.carrier_road_pairs} == {"in_1", "in_2"}
        and {pair.to_road_id for pair in item.carrier_road_pairs} == {"out_1", "out_2"}
    )
    return arms, movement


def _restriction(
    restriction_id: str,
    pair: RoadPair,
    *,
    condition_type: int = 1,
    **condition_properties: object,
) -> RestrictionInput:
    properties = {
        "CondID": restriction_id,
        "CondType": condition_type,
        "inLinkID": pair.from_road_id,
        "outLinkID": pair.to_road_id,
        **condition_properties,
    }
    return RestrictionInput(
        restriction_id=restriction_id,
        in_link_id=pair.from_road_id,
        out_link_id=pair.to_road_id,
        properties=properties,
        condition_type=str(condition_type),
        condition_payload=properties,
        condition_semantics_status="unknown",
    )


def _valid_arrow(
    arrow_id: str,
    road_id: str,
    *codes: str,
    direction_matched: bool = True,
    lane_sequence_complete: bool = True,
) -> ArrowInput:
    return ArrowInput(
        arrow_id=arrow_id,
        road_id=road_id,
        lane_codes=tuple(codes),
        direction_matched=direction_matched,
        lane_sequence_complete=lane_sequence_complete,
        lane_dir=2,
        road_direction=2,
        seq_start=1,
        seq_end=len(codes),
        source_arrow_dir="|".join(codes),
        sequence_metadata_status=("complete" if lane_sequence_complete else "explicit_incomplete"),
        properties={
            "lane_dir": 2,
            "road_direction": 2,
            "lane_count": len(codes),
            "seq_start": 1,
            "seq_end": len(codes),
            "source_arrow_dir": "|".join(codes),
        },
    )


def _special_profile(
    road_id: str,
    *,
    dedicated_movement_type: str = "right",
    arm_role: str = "incident_seed",
) -> SpecialCarrierArmProfile:
    profile = SpecialCarrierRoadProfile(
        road_id=road_id,
        dedicated_movement_type=dedicated_movement_type,
        formway=128 if dedicated_movement_type == "right" else 256,
        kind=None,
        arm_role=arm_role,
        carrier_type=f"advance_{dedicated_movement_type}",
        classification_status=DecisionStatus.SUPPORTED,
        verification_status=VerificationStatus.VERIFIED_SWSD,
    )
    return SpecialCarrierArmProfile(
        junction_id="junction_1",
        arm_id="arm_in",
        road_profiles=(profile,),
        advance_left_road_ids=(road_id,) if dedicated_movement_type == "left" else tuple(),
        advance_right_road_ids=(road_id,) if dedicated_movement_type == "right" else tuple(),
        core_road_ids=tuple(),
    )


def _resolve(
    movement: T09ArmMovement,
    *,
    restrictions: tuple[RestrictionInput, ...] = tuple(),
    arrows: tuple[ArrowInput, ...] = tuple(),
    special_profile: SpecialCarrierArmProfile | None = None,
    restriction_result: RestrictionMatchResult | None = None,
):
    matched_restrictions = restriction_result or match_restriction_evidence(
        movement,
        restrictions,
    )
    road_arrow_decisions = evaluate_road_arrow_directions(movement, arrows)
    return resolve_multi_evidence_movement(
        movement=movement,
        restriction_result=matched_restrictions,
        road_arrow_decisions=road_arrow_decisions,
        special_profile=special_profile,
    )


def _restriction_rules(result) -> tuple:
    return tuple(
        rule
        for rule in result.restored_rules
        if rule.decision_source == DecisionSource.RESTRICTION
    )


def _manual_restriction_evidence(
    *,
    evidence_id: str,
    restriction_id: str,
    pair: RoadPair,
) -> T09EvidenceItem:
    return T09EvidenceItem(
        evidence_id=evidence_id,
        evidence_type=EvidenceType.RESTRICTION,
        junction_id="junction_1",
        movement_id="movement_right",
        road_pair=pair,
        evidence_status="prohibited_by_restriction",
        prohibition_reason=ProhibitionReason.EXPLICIT_RESTRICTION,
        inference_level=InferenceLevel.EXPLICIT,
        confidence=1.0,
        provenance=EvidenceProvenance(
            source_type="restriction",
            source_id=restriction_id,
            matched_object_ids=(pair.from_road_id, pair.to_road_id),
            match_method="inLinkID_to_outLinkID",
        ),
        supports_prohibition=True,
        decision_status=DecisionStatus.PROHIBITED,
        decision_scope=RuleScope.ROAD_TO_ROAD,
        evidence_priority=EvidencePriority.RESTRICTION,
        verification_status=VerificationStatus.VERIFIED_SWSD,
        from_road_ids=(pair.from_road_id,),
        to_road_ids=(pair.to_road_id,),
        condition_type="1",
        condition_payload={"CondType": 1, "TimeWindow": "all_day"},
        condition_identity="condition:stable",
        condition_semantics_status="unknown",
    )


def test_scenario_01_restriction_overrides_lane_support_with_explicit_provenance() -> None:
    movement = _movement("right")
    result = _resolve(
        movement,
        restrictions=(_restriction("restriction_1", movement.carrier_road_pairs[0]),),
        arrows=(_valid_arrow("arrow_right", "in_1", "c"),),
    )

    rule = _restriction_rules(result)[0]
    assert rule.decision_status == DecisionStatus.PROHIBITED
    assert rule.decision_source == DecisionSource.RESTRICTION
    assert rule.inference_level == InferenceLevel.EXPLICIT
    assert any(entry.overridden_source == DecisionSource.LANEINFO for entry in rule.override_chain)
    assert rule.conflicting_evidence_ids


def test_scenario_02_same_restriction_id_keeps_each_road_pair_evidence() -> None:
    pairs = (RoadPair("in_1", "out_1"), RoadPair("in_2", "out_2"))
    movement = _movement(pairs=pairs)
    restrictions = tuple(_restriction("shared_condition", pair) for pair in pairs)
    matched = match_restriction_evidence(movement, restrictions)
    result = _resolve(movement, restrictions=restrictions, restriction_result=matched)

    assert {item.road_pair for item in matched.evidence_items} == set(pairs)
    assert len({item.evidence_id for item in matched.evidence_items}) == 2
    restriction_rules = _restriction_rules(result)
    assert {pair for rule in restriction_rules for pair in rule.road_pairs} == set(pairs)
    assert {
        evidence_id
        for rule in restriction_rules
        for evidence_id in rule.supporting_evidence_ids
    } == {item.evidence_id for item in matched.evidence_items}


def test_scenario_03_partial_restriction_stays_road_to_road() -> None:
    pairs = (RoadPair("in_1", "out_1"), RoadPair("in_1", "out_2"))
    movement = _movement(pairs=pairs)
    result = _resolve(
        movement,
        restrictions=(_restriction("partial", pairs[0]),),
    )

    restriction_rule = _restriction_rules(result)[0]
    assert restriction_rule.decision_scope == RuleScope.ROAD_TO_ROAD
    assert restriction_rule.road_pairs == (pairs[0],)
    assert all(rule.decision_scope != RuleScope.ARM_TO_ARM for rule in result.restored_rules)
    assert result.movement.prohibition_status == ProhibitionStatus.PARTIALLY_PROHIBITED


@pytest.mark.parametrize("segment_membership_status", ("consistent", "t01_only"))
def test_scenario_04_confirmed_full_coverage_promotes_to_arm_to_arm(
    segment_membership_status: str,
) -> None:
    from_road_ids = ("in_1", "in_2")
    to_road_ids = ("out_1", "out_2")
    pairs = tuple(
        RoadPair(from_road_id, to_road_id)
        for from_road_id in from_road_ids
        for to_road_id in to_road_ids
    )
    movement = _movement(pairs=pairs)
    restrictions = tuple(_restriction("full", pair) for pair in pairs)
    matched = match_restriction_evidence(
        movement,
        restrictions,
        arms_by_id={
            "arm_in": _audited_equivalent_arm(
                "arm_in",
                role="approach",
                road_ids=from_road_ids,
                segment_membership_status=segment_membership_status,
            ),
            "arm_out": _audited_equivalent_arm(
                "arm_out",
                role="exit",
                road_ids=to_road_ids,
                segment_membership_status=segment_membership_status,
            ),
        },
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    result = _resolve(movement, restriction_result=matched)

    assert matched.scope_promotion_status == "arm_to_arm_confirmed"
    assert matched.scope_promotion_audit is not None
    assert matched.scope_promotion_audit["role_specific_carrier_universe_complete"] is True
    assert matched.scope_promotion_audit["parallel_or_split_equivalence_explained"] is True
    assert matched.scope_promotion_audit["match_proof_complete"] is True
    assert matched.scope_promotion_audit["unexplained_carrier_count"] == 0
    assert {
        proof["proof_type"]
        for proof in matched.scope_promotion_audit["restriction_match_proofs"]
    } == {"exact_link_identity"}
    assert len(result.restored_rules) == 1
    rule = result.restored_rules[0]
    assert rule.decision_scope == RuleScope.ARM_TO_ARM
    assert set(rule.road_pairs) == set(pairs)
    assert rule.scope_promotion_status == "arm_to_arm_confirmed"


def test_v2_real_builder_multi_road_shared_t01_promotes_after_movement_build() -> None:
    arms, movement = _built_two_by_two_scope_fixture()
    restrictions = tuple(_restriction("full_built", pair) for pair in movement.carrier_road_pairs)

    matched = match_restriction_evidence(
        movement,
        restrictions,
        arms_by_id={arm.arm_id: arm for arm in arms},
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    assert matched.scope_promotion_status == "arm_to_arm_confirmed"
    assert matched.scope_promotion_audit is not None
    assert matched.scope_promotion_audit["from_role_equivalence"][
        "shared_segment_split_equivalence"
    ] is True
    assert matched.scope_promotion_audit["to_role_equivalence"][
        "shared_segment_split_equivalence"
    ] is True


@pytest.mark.parametrize("from_membership", ("partial_t01", "stale_conflict"))
def test_v2_builder_membership_gap_blocks_shared_segment_scope_promotion(
    from_membership: str,
) -> None:
    arms, movement = _built_two_by_two_scope_fixture(
        from_membership=from_membership,
    )
    from_arm = next(arm for arm in arms if set(arm.approach_road_ids) == {"in_1", "in_2"})
    matched = match_restriction_evidence(
        movement,
        tuple(_restriction("full_unproven", pair) for pair in movement.carrier_road_pairs),
        arms_by_id={arm.arm_id: arm for arm in arms},
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    assert from_arm.segment_membership_status == "conflict"
    assert "segment_membership_conflict" in from_arm.risk_flags
    assert matched.scope_promotion_status == "manual_review_required"
    assert matched.scope_promotion_audit is not None
    from_equivalence = matched.scope_promotion_audit["from_role_equivalence"]
    assert from_equivalence["formal_t01_membership_complete"] is False
    assert from_equivalence["shared_segment_split_equivalence"] is False


@pytest.mark.parametrize(
    ("segment_membership_status", "t01_segment_ids"),
    (("missing", tuple()), ("road_only", tuple()), ("conflict", ("official",))),
)
def test_v2_singleton_role_requires_formal_t01_membership_gate(
    segment_membership_status: str,
    t01_segment_ids: tuple[str, ...],
) -> None:
    movement = _movement()
    pair = movement.carrier_road_pairs[0]
    invalid_from = replace(
        _audited_equivalent_arm("arm_in", role="approach", road_ids=(pair.from_road_id,)),
        t01_segment_ids=t01_segment_ids,
        segment_membership_status=segment_membership_status,
        risk_flags=(
            ("segment_membership_conflict",)
            if segment_membership_status == "conflict"
            else tuple()
        ),
    )

    matched = match_restriction_evidence(
        movement,
        (_restriction("singleton_invalid", pair),),
        arms_by_id={
            "arm_in": invalid_from,
            "arm_out": _audited_equivalent_arm(
                "arm_out",
                role="exit",
                road_ids=(pair.to_road_id,),
            ),
        },
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    assert matched.scope_promotion_status == "manual_review_required"
    assert matched.scope_promotion_audit is not None
    from_equivalence = matched.scope_promotion_audit["from_role_equivalence"]
    assert from_equivalence["equivalence_proven"] is False
    assert from_equivalence["failed_gates"] == ("formal_t01_membership_complete",)


def test_v2_singleton_role_still_requires_built_seed_and_geometry_audit() -> None:
    movement = _movement()
    pair = movement.carrier_road_pairs[0]
    invalid_from = replace(
        _audited_equivalent_arm(
            "arm_in",
            role="approach",
            road_ids=(pair.from_road_id,),
        ),
        build_status="failed",
        seed_road_ids=tuple(),
        angle_deg=None,
        audit_refs=tuple(),
    )

    matched = match_restriction_evidence(
        movement,
        (_restriction("singleton_invalid_build", pair),),
        arms_by_id={
            "arm_in": invalid_from,
            "arm_out": _audited_equivalent_arm(
                "arm_out",
                role="exit",
                road_ids=(pair.to_road_id,),
            ),
        },
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    assert matched.scope_promotion_status == "manual_review_required"
    assert matched.scope_promotion_audit is not None
    failed = set(
        matched.scope_promotion_audit["from_role_equivalence"]["failed_gates"]
    )
    assert {
        "built_arm",
        "role_roads_are_seed_carriers",
        "directional_grouping_audited",
        "seed_universe_audited",
        "direction_geometry_available",
    } <= failed


def test_v2_explicit_parallel_equivalence_remains_t01_independent() -> None:
    from_ids = ("in_1", "in_2")
    movement = _movement(
        pairs=tuple(RoadPair(from_id, "out_1") for from_id in from_ids),
    )
    base_from_arm = _audited_equivalent_arm(
        "arm_in", role="approach", road_ids=from_ids
    )
    from_arm = replace(
        base_from_arm,
        t01_segment_ids=tuple(),
        segment_membership_status="conflict",
        parallel_branch_road_ids=from_ids,
        risk_flags=("segment_membership_conflict",),
        audit_refs=base_from_arm.audit_refs
        + ("parallel_branch_proof=same_role_same_terminal_directional_bundle",),
    )
    matched = match_restriction_evidence(
        movement,
        tuple(_restriction("parallel_full", pair) for pair in movement.carrier_road_pairs),
        arms_by_id={
            "arm_in": from_arm,
            "arm_out": _audited_equivalent_arm(
                "arm_out",
                role="exit",
                road_ids=("out_1",),
            ),
        },
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    assert matched.scope_promotion_status == "arm_to_arm_confirmed"
    assert matched.scope_promotion_audit is not None
    from_equivalence = matched.scope_promotion_audit["from_role_equivalence"]
    assert from_equivalence["explicit_parallel_equivalence"] is True
    assert from_equivalence["shared_segment_split_equivalence"] is False


@pytest.mark.parametrize(("same_terminal", "expected_promoted"), ((True, True), (False, False)))
def test_v2_builder_produces_only_same_terminal_parallel_proof(
    same_terminal: bool,
    expected_promoted: bool,
) -> None:
    roads = (
        SWSDRoadInput("in_1", "west", "junction_1", 2),
        SWSDRoadInput(
            "in_2",
            "west" if same_terminal else "west_2",
            "junction_1",
            2,
        ),
        SWSDRoadInput("out_1", "junction_1", "north", 2),
    )
    geometries = {
        "in_1": LineString([(-20.0, -0.5), (0.0, 0.0)]),
        "in_2": LineString([(-20.0, 0.5), (0.0, 0.0)]),
        "out_1": LineString([(0.0, 0.0), (0.0, 20.0)]),
    }
    v1_arms = build_swsd_arms(
        junction_id="junction_1",
        member_node_ids=("junction_1",),
        roads=roads,
        segments=(
            SWSDSegmentInput(
                segment_id="official_out",
                junc_nodes=("junction_1",),
                road_ids=("out_1",),
            ),
        ),
        road_geometries=geometries,
    )
    assert all(not arm.parallel_branch_road_ids for arm in v1_arms)
    assert all(
        not any(ref.startswith("parallel_branch_") for ref in arm.audit_refs)
        for arm in v1_arms
    )

    arms = build_swsd_arms(
        junction_id="junction_1",
        member_node_ids=("junction_1",),
        roads=roads,
        segments=(
            SWSDSegmentInput(
                segment_id="official_out",
                junc_nodes=("junction_1",),
                road_ids=("out_1",),
            ),
        ),
        road_geometries=geometries,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )
    from_arm = next(
        arm for arm in arms if set(arm.approach_road_ids) == {"in_1", "in_2"}
    )
    to_arm = next(arm for arm in arms if arm.exit_road_ids == ("out_1",))
    movement = next(
        item
        for item in build_arm_movements(junction_id="junction_1", arms=arms)
        if item.from_arm_id == from_arm.arm_id and item.to_arm_id == to_arm.arm_id
    )
    matched = match_restriction_evidence(
        movement,
        tuple(_restriction("parallel_builder", pair) for pair in movement.carrier_road_pairs),
        arms_by_id={arm.arm_id: arm for arm in arms},
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    assert bool(from_arm.parallel_branch_road_ids) is expected_promoted
    assert (matched.scope_promotion_status == "arm_to_arm_confirmed") is expected_promoted
    if expected_promoted:
        special = restore_field_rules(
            arms=arms,
            movements=(replace(movement, movement_type="right"),),
            road_attributes=(
                RoadAttributes(road_id="in_1"),
                RoadAttributes(road_id="in_2", formway=128),
                RoadAttributes(road_id="out_1"),
            ),
            strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
        )
        assert any(
            item.evidence_type == EvidenceType.SPECIAL_CARRIER
            and "in_2" in item.provenance.source_id.split(",")
            for item in special.evidence_items
        )


def test_parallel_special_decision_is_invariant_to_road_id_assignment() -> None:
    roads = (
        SWSDRoadInput("in_1", "west", "junction_1", 2),
        SWSDRoadInput("in_2", "west", "junction_1", 2),
        SWSDRoadInput("out_1", "junction_1", "north", 2),
    )
    geometries = {
        "in_1": LineString([(-20.0, -0.5), (0.0, 0.0)]),
        "in_2": LineString([(-20.0, 0.5), (0.0, 0.0)]),
        "out_1": LineString([(0.0, 0.0), (0.0, 20.0)]),
    }
    arms = build_swsd_arms(
        junction_id="junction_1",
        member_node_ids=("junction_1",),
        roads=roads,
        segments=(
            SWSDSegmentInput(
                "official_out",
                junc_nodes=("junction_1",),
                road_ids=("out_1",),
            ),
        ),
        road_geometries=geometries,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )
    from_arm = next(
        arm for arm in arms if set(arm.approach_road_ids) == {"in_1", "in_2"}
    )
    assert set(from_arm.parallel_branch_road_ids) == {"in_1", "in_2"}
    movement = next(
        item
        for item in build_arm_movements(junction_id="junction_1", arms=arms)
        if item.from_arm_id == from_arm.arm_id
        and {pair.to_road_id for pair in item.carrier_road_pairs} == {"out_1"}
    )
    movement = replace(movement, movement_type="right")

    def outcome(special_road_id: str) -> list[tuple[str, str, str]]:
        restored = restore_field_rules(
            arms=arms,
            movements=(movement,),
            road_attributes=tuple(
                RoadAttributes(
                    road_id=road_id,
                    formway=128 if road_id == special_road_id else 0,
                )
                for road_id in ("in_1", "in_2", "out_1")
            ),
            strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
        )
        return sorted(
            (
                item.decision_status.value,
                item.decision_scope.value if item.decision_scope else "",
                str(item.provenance.field_audit.get("carrier_type", "")),
            )
            for item in restored.evidence_items
            if item.evidence_type == EvidenceType.SPECIAL_CARRIER
        )

    assert outcome("in_1") == outcome("in_2")


def test_v2_full_cross_product_without_equivalence_proof_stays_road_to_road() -> None:
    from_road_ids = ("in_1", "in_2")
    to_road_ids = ("out_1", "out_2")
    pairs = tuple(
        RoadPair(from_road_id, to_road_id)
        for from_road_id in from_road_ids
        for to_road_id in to_road_ids
    )
    movement = _movement(pairs=pairs)
    matched = match_restriction_evidence(
        movement,
        tuple(_restriction("full_without_equivalence", pair) for pair in pairs),
        arms_by_id={
            "arm_in": T09SwsdArm(
                junction_id="junction_1",
                arm_id="arm_in",
                seed_road_ids=from_road_ids,
                approach_road_ids=from_road_ids,
            ),
            "arm_out": T09SwsdArm(
                junction_id="junction_1",
                arm_id="arm_out",
                seed_road_ids=to_road_ids,
                exit_road_ids=to_road_ids,
            ),
        },
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    result = _resolve(movement, restriction_result=matched)

    assert matched.prohibition_status == ProhibitionStatus.FULLY_PROHIBITED
    assert matched.scope_promotion_status == "manual_review_required"
    assert matched.scope_promotion_audit is not None
    assert matched.scope_promotion_audit["role_specific_carrier_universe_complete"] is True
    assert matched.scope_promotion_audit["match_proof_complete"] is True
    assert matched.scope_promotion_audit["parallel_or_split_equivalence_explained"] is False
    assert "parallel_or_split_equivalence_explained" in matched.scope_promotion_audit["failed_gates"]
    restriction_rules = _restriction_rules(result)
    assert len(restriction_rules) == len(pairs)
    assert all(rule.decision_scope == RuleScope.ROAD_TO_ROAD for rule in restriction_rules)
    assert all(
        rule.verification_status == VerificationStatus.MANUAL_REVIEW_REQUIRED
        for rule in restriction_rules
    )


def test_v2_directed_geometry_match_is_audited_as_scope_match_proof() -> None:
    pair = RoadPair("swsd_in", "swsd_out")
    movement = _movement(pairs=(pair,))
    matched = match_restriction_evidence(
        movement,
        (
            RestrictionInput(
                restriction_id="raw_geometry_restriction",
                in_link_id="raw_in",
                out_link_id="raw_out",
                geometry=LineString([(-12.0, 0.0), (0.0, 0.0), (0.0, 12.0)]),
            ),
        ),
        roads_by_id={
            "swsd_in": SWSDRoadInput("swsd_in", "west", "junction_1", 2),
            "swsd_out": SWSDRoadInput("swsd_out", "junction_1", "north", 2),
        },
        road_geometries={
            "swsd_in": LineString([(-20.0, 0.0), (0.0, 0.0)]),
            "swsd_out": LineString([(0.0, 0.0), (0.0, 20.0)]),
        },
        arms_by_id={
            "arm_in": _audited_equivalent_arm(
                "arm_in",
                role="approach",
                road_ids=("swsd_in",),
            ),
            "arm_out": _audited_equivalent_arm(
                "arm_out",
                role="exit",
                road_ids=("swsd_out",),
            ),
        },
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    assert matched.scope_promotion_status == "arm_to_arm_confirmed"
    assert matched.scope_promotion_audit is not None
    assert matched.scope_promotion_audit["restriction_match_proofs"][0]["proof_type"] == (
        "directed_geometry_match"
    )
    assert matched.scope_promotion_audit["match_proof_complete"] is True


def test_v2_single_raw_geometry_fanout_to_multiple_pairs_cannot_promote() -> None:
    from_road_ids = ("swsd_in_1", "swsd_in_2")
    to_road_ids = ("swsd_out_1", "swsd_out_2")
    pairs = tuple(
        RoadPair(from_road_id, to_road_id)
        for from_road_id in from_road_ids
        for to_road_id in to_road_ids
    )
    movement = _movement(pairs=pairs)
    matched = match_restriction_evidence(
        movement,
        (
            RestrictionInput(
                restriction_id="one_raw_geometry",
                in_link_id="raw_in",
                out_link_id="raw_out",
                geometry=LineString([(-12.0, 1.0), (1.0, 1.0), (1.0, 12.0)]),
            ),
        ),
        roads_by_id={
            "swsd_in_1": SWSDRoadInput("swsd_in_1", "west_1", "junction_1", 2),
            "swsd_in_2": SWSDRoadInput("swsd_in_2", "west_2", "junction_1", 2),
            "swsd_out_1": SWSDRoadInput("swsd_out_1", "junction_1", "north_1", 2),
            "swsd_out_2": SWSDRoadInput("swsd_out_2", "junction_1", "north_2", 2),
        },
        road_geometries={
            "swsd_in_1": LineString([(-20.0, 0.0), (0.0, 0.0)]),
            "swsd_in_2": LineString([(-20.0, 2.0), (0.0, 2.0)]),
            "swsd_out_1": LineString([(0.0, 0.0), (0.0, 20.0)]),
            "swsd_out_2": LineString([(2.0, 0.0), (2.0, 20.0)]),
        },
        arms_by_id={
            "arm_in": _audited_equivalent_arm(
                "arm_in",
                role="approach",
                road_ids=from_road_ids,
            ),
            "arm_out": _audited_equivalent_arm(
                "arm_out",
                role="exit",
                road_ids=to_road_ids,
            ),
        },
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    result = _resolve(movement, restriction_result=matched)

    assert len(matched.evidence_items) == 4
    assert all(
        "ambiguous_restriction_geometry_fanout" in item.risk_flags
        for item in matched.evidence_items
    )
    assert all(
        item.verification_status == VerificationStatus.MANUAL_REVIEW_REQUIRED
        for item in matched.evidence_items
    )
    assert all(
        item.provenance.field_audit["geometry_fanout_road_pair_count"] == 4
        for item in matched.evidence_items
    )
    assert matched.scope_promotion_status == "manual_review_required"
    assert matched.scope_promotion_audit is not None
    assert matched.scope_promotion_audit["match_proof_complete"] is False
    restriction_rules = _restriction_rules(result)
    assert len(restriction_rules) == 4
    assert all(rule.decision_scope == RuleScope.ROAD_TO_ROAD for rule in restriction_rules)
    assert all(
        rule.verification_status == VerificationStatus.MANUAL_REVIEW_REQUIRED
        for rule in restriction_rules
    )


def test_v2_raw_geometry_fanout_across_movements_is_globally_manual() -> None:
    movement_1 = replace(
        _movement("right", pairs=(RoadPair("swsd_in_1", "swsd_out_1"),)),
        movement_id="movement_geometry_fanout_1",
        from_arm_id="arm_in_1",
        to_arm_id="arm_out_1",
    )
    movement_2 = replace(
        _movement("left", pairs=(RoadPair("swsd_in_2", "swsd_out_2"),)),
        movement_id="movement_geometry_fanout_2",
        from_arm_id="arm_in_2",
        to_arm_id="arm_out_2",
    )
    arms = (
        _audited_equivalent_arm("arm_in_1", role="approach", road_ids=("swsd_in_1",)),
        _audited_equivalent_arm("arm_out_1", role="exit", road_ids=("swsd_out_1",)),
        _audited_equivalent_arm("arm_in_2", role="approach", road_ids=("swsd_in_2",)),
        _audited_equivalent_arm("arm_out_2", role="exit", road_ids=("swsd_out_2",)),
    )
    roads = (
        SWSDRoadInput("swsd_in_1", "west_1", "junction_1", 2),
        SWSDRoadInput("swsd_in_2", "west_2", "junction_1", 2),
        SWSDRoadInput("swsd_out_1", "junction_1", "north_1", 2),
        SWSDRoadInput("swsd_out_2", "junction_1", "north_2", 2),
    )
    geometries = {
        "swsd_in_1": LineString([(-20.0, 0.0), (0.0, 0.0)]),
        "swsd_in_2": LineString([(-20.0, 2.0), (0.0, 2.0)]),
        "swsd_out_1": LineString([(0.0, 0.0), (0.0, 20.0)]),
        "swsd_out_2": LineString([(2.0, 0.0), (2.0, 20.0)]),
    }
    restored = restore_field_rules(
        arms=arms,
        movements=(movement_1, movement_2),
        restrictions=(
            RestrictionInput(
                restriction_id="one_cross_movement_geometry",
                in_link_id="raw_in",
                out_link_id="raw_out",
                geometry=LineString([(-12.0, 1.0), (1.0, 1.0), (1.0, 12.0)]),
            ),
        ),
        roads=roads,
        road_geometries=geometries,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    restriction_evidence = tuple(
        item for item in restored.evidence_items if item.evidence_type == EvidenceType.RESTRICTION
    )
    restriction_rules = tuple(
        rule
        for rule in restored.restored_rules
        if rule.decision_source == DecisionSource.RESTRICTION
    )
    assert len(restriction_evidence) == 2
    assert all(
        item.verification_status == VerificationStatus.MANUAL_REVIEW_REQUIRED
        and "ambiguous_restriction_geometry_fanout" in item.risk_flags
        for item in restriction_evidence
    )
    assert len(restriction_rules) == 2
    assert all(
        rule.decision_scope == RuleScope.ROAD_TO_ROAD
        and rule.verification_status == VerificationStatus.MANUAL_REVIEW_REQUIRED
        for rule in restriction_rules
    )


def test_v2_cross_movement_exact_match_blocks_extra_geometry_fallback() -> None:
    movement_1 = replace(
        _movement("right", pairs=(RoadPair("swsd_in_1", "swsd_out_1"),)),
        movement_id="movement_exact",
        from_arm_id="arm_in_1",
        to_arm_id="arm_out_1",
    )
    movement_2 = replace(
        _movement("left", pairs=(RoadPair("swsd_in_2", "swsd_out_2"),)),
        movement_id="movement_geometry_extra",
        from_arm_id="arm_in_2",
        to_arm_id="arm_out_2",
    )
    arms = (
        _audited_equivalent_arm("arm_in_1", role="approach", road_ids=("swsd_in_1",)),
        _audited_equivalent_arm("arm_out_1", role="exit", road_ids=("swsd_out_1",)),
        _audited_equivalent_arm("arm_in_2", role="approach", road_ids=("swsd_in_2",)),
        _audited_equivalent_arm("arm_out_2", role="exit", road_ids=("swsd_out_2",)),
    )
    roads = (
        SWSDRoadInput("swsd_in_1", "west_1", "junction_1", 2),
        SWSDRoadInput("swsd_in_2", "west_2", "junction_1", 2),
        SWSDRoadInput("swsd_out_1", "junction_1", "north_1", 2),
        SWSDRoadInput("swsd_out_2", "junction_1", "north_2", 2),
    )
    geometries = {
        "swsd_in_1": LineString([(-20.0, 0.0), (0.0, 0.0)]),
        "swsd_in_2": LineString([(-20.0, 2.0), (0.0, 2.0)]),
        "swsd_out_1": LineString([(0.0, 0.0), (0.0, 20.0)]),
        "swsd_out_2": LineString([(2.0, 0.0), (2.0, 20.0)]),
    }
    restored = restore_field_rules(
        arms=arms,
        movements=(movement_1, movement_2),
        restrictions=(
            RestrictionInput(
                restriction_id="exact_plus_geometry",
                in_link_id="swsd_in_1",
                out_link_id="swsd_out_1",
                geometry=LineString([(-12.0, 1.0), (1.0, 1.0), (1.0, 12.0)]),
            ),
        ),
        roads=roads,
        road_geometries=geometries,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    evidence_by_movement = {
        item.movement_id: item
        for item in restored.evidence_items
        if item.evidence_type == EvidenceType.RESTRICTION
    }
    exact = evidence_by_movement["movement_exact"]
    geometry = evidence_by_movement["movement_geometry_extra"]
    assert exact.provenance.match_method == "inLinkID_to_outLinkID"
    assert exact.verification_status == VerificationStatus.VERIFIED_SWSD
    assert geometry.provenance.match_method == "directed_geometry_restriction_to_carrier"
    assert geometry.verification_status == VerificationStatus.MANUAL_REVIEW_REQUIRED
    assert "ambiguous_restriction_geometry_fanout" in geometry.risk_flags


def test_scenario_05_condition_payload_round_trips_without_semantic_guessing() -> None:
    movement = _movement()
    restriction = _restriction(
        "timed_condition",
        movement.carrier_road_pairs[0],
        condition_type=7,
        TimeWindow="07:00-09:00",
        VehicleClass="raw_unknown",
    )
    result = _resolve(movement, restrictions=(restriction,))

    rule = _restriction_rules(result)[0]
    assert rule.condition_type == "7"
    assert rule.condition_identity.startswith("condition:")
    assert rule.condition_semantics_status == "unknown"
    raw_payloads = tuple(item["raw_properties"] for item in rule.condition_payload)
    assert raw_payloads[0]["TimeWindow"] == "07:00-09:00"
    assert raw_payloads[0]["VehicleClass"] == "raw_unknown"


def test_scenario_05_different_conditions_do_not_form_full_or_arm_scope_prohibition() -> None:
    pairs = (RoadPair("in_1", "out_1"), RoadPair("in_2", "out_2"))
    movement = _movement(pairs=pairs)
    restrictions = (
        _restriction("conditional", pairs[0], TimeWindow="AM"),
        _restriction("conditional", pairs[1], TimeWindow="PM"),
    )
    matched = match_restriction_evidence(
        movement,
        restrictions,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )
    result = _resolve(movement, restriction_result=matched)

    assert matched.scope_promotion_status != "arm_to_arm_confirmed"
    assert all(rule.decision_scope != RuleScope.ARM_TO_ARM for rule in result.restored_rules)
    assert result.movement.prohibition_status != ProhibitionStatus.FULLY_PROHIBITED
    assert result.movement.decision_status in {
        DecisionStatus.UNKNOWN,
        DecisionStatus.MANUAL_REVIEW_REQUIRED,
    }


def test_v1_cross_condition_union_preserves_legacy_full_coverage() -> None:
    pairs = (RoadPair("in_1", "out_1"), RoadPair("in_2", "out_2"))
    movement = _movement(pairs=pairs)
    restrictions = (
        _restriction("legacy_conditional", pairs[0], TimeWindow="AM"),
        _restriction("legacy_conditional", pairs[1], TimeWindow="PM"),
    )

    default_result = match_restriction_evidence(movement, restrictions)
    explicit_v1_result = match_restriction_evidence(
        movement,
        restrictions,
        strategy_version=RestorationStrategy.RESTRICTION_ONLY_V1,
    )

    assert default_result == explicit_v1_result
    assert default_result.prohibition_status == ProhibitionStatus.FULLY_PROHIBITED
    assert default_result.restriction_coverage == "all_restricted"
    assert default_result.partial_basis == "not_applicable"
    assert default_result.remaining_restriction_status == "not_applicable"


def test_v2_each_complete_condition_promotes_independently_without_flattening() -> None:
    from_road_ids = ("in_1", "in_2")
    to_road_ids = ("out_1",)
    pairs = tuple(RoadPair(from_road_id, "out_1") for from_road_id in from_road_ids)
    movement = _movement(pairs=pairs)
    restrictions = tuple(
        _restriction("conditional_full", pair, TimeWindow=time_window)
        for time_window in ("AM", "PM")
        for pair in pairs
    )
    matched = match_restriction_evidence(
        movement,
        restrictions,
        arms_by_id={
            "arm_in": _audited_equivalent_arm(
                "arm_in",
                role="approach",
                road_ids=from_road_ids,
            ),
            "arm_out": _audited_equivalent_arm(
                "arm_out",
                role="exit",
                road_ids=to_road_ids,
            ),
        },
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    result = _resolve(movement, restriction_result=matched)
    restriction_rules = _restriction_rules(result)

    assert matched.scope_promotion_status == "condition_scoped_arm_to_arm_confirmed"
    assert matched.condition_scope_results is not None
    assert {
        item["scope_promotion_status"]
        for item in matched.condition_scope_results.values()
    } == {"arm_to_arm_confirmed"}
    assert len(restriction_rules) == 2
    assert all(rule.decision_scope == RuleScope.ARM_TO_ARM for rule in restriction_rules)
    assert len({rule.condition_identity for rule in restriction_rules}) == 2
    assert {
        frozenset(
            payload["raw_properties"]["TimeWindow"]
            for payload in rule.condition_payload
        )
        for rule in restriction_rules
    } == {frozenset({"AM"}), frozenset({"PM"})}


def test_v2_complete_and_partial_conditions_keep_independent_scopes() -> None:
    from_road_ids = ("in_1", "in_2")
    to_road_ids = ("out_1",)
    pairs = tuple(RoadPair(from_road_id, "out_1") for from_road_id in from_road_ids)
    movement = _movement(pairs=pairs)
    restrictions = tuple(
        [_restriction("conditional_mixed", pair, TimeWindow="AM") for pair in pairs]
        + [_restriction("conditional_mixed", pairs[0], TimeWindow="PM")]
    )
    matched = match_restriction_evidence(
        movement,
        restrictions,
        arms_by_id={
            "arm_in": _audited_equivalent_arm(
                "arm_in",
                role="approach",
                road_ids=from_road_ids,
            ),
            "arm_out": _audited_equivalent_arm(
                "arm_out",
                role="exit",
                road_ids=to_road_ids,
            ),
        },
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )

    result = _resolve(movement, restriction_result=matched)
    restriction_rules = _restriction_rules(result)
    rules_by_time = {
        next(
            payload["raw_properties"]["TimeWindow"]
            for payload in rule.condition_payload
        ): rule
        for rule in restriction_rules
    }

    assert matched.scope_promotion_status == "condition_scoped_mixed"
    assert set(rules_by_time) == {"AM", "PM"}
    assert rules_by_time["AM"].decision_scope == RuleScope.ARM_TO_ARM
    assert rules_by_time["AM"].verification_status == VerificationStatus.VERIFIED_SWSD
    assert rules_by_time["PM"].decision_scope == RuleScope.ROAD_TO_ROAD
    assert rules_by_time["PM"].verification_status == VerificationStatus.MANUAL_REVIEW_REQUIRED
    assert rules_by_time["AM"].condition_identity != rules_by_time["PM"].condition_identity
    assert result.movement.decision_status == DecisionStatus.MANUAL_REVIEW_REQUIRED
    assert result.movement.prohibition_status == ProhibitionStatus.PARTIALLY_PROHIBITED
    assert "condition_scoped_mixed_outcomes" in result.movement.risk_flags


def test_scenario_06_complete_lane_union_missing_right_prohibits_only_the_road_direction() -> None:
    movement = _movement("right")
    result = _resolve(
        movement,
        arrows=(_valid_arrow("arrow_no_right", "in_1", "a", "b"),),
    )

    rule = result.restored_rules[0]
    assert rule.decision_status == DecisionStatus.PROHIBITED
    assert rule.decision_source == DecisionSource.LANEINFO
    assert rule.decision_scope == RuleScope.ROAD_DIRECTION_EXCLUSION
    assert rule.from_road_ids == ("in_1",)


def test_scenario_07_any_lane_supporting_right_prevents_exclusion() -> None:
    movement = _movement("right")
    result = _resolve(
        movement,
        arrows=(
            _valid_arrow("arrow_straight", "in_1", "a"),
            _valid_arrow("arrow_right", "in_1", "c"),
        ),
    )

    rule = result.restored_rules[0]
    assert rule.decision_status == DecisionStatus.SUPPORTED
    assert rule.decision_source == DecisionSource.LANEINFO
    assert all(
        not (
            candidate.decision_status == DecisionStatus.PROHIBITED
            and candidate.decision_scope == RuleScope.ROAD_DIRECTION_EXCLUSION
        )
        for candidate in result.restored_rules
    )


def test_scenario_08_missing_left_and_uturn_excludes_both_existing_movements() -> None:
    arrow = _valid_arrow("arrow_straight", "in_1", "a")
    left = _resolve(_movement("left"), arrows=(arrow,))
    uturn = _resolve(_movement("uturn"), arrows=(arrow,))

    assert left.restored_rules[0].decision_status == DecisionStatus.PROHIBITED
    assert uturn.restored_rules[0].decision_status == DecisionStatus.PROHIBITED


def test_scenario_09_explicit_uturn_support_does_not_release_left_exclusion() -> None:
    arrow = _valid_arrow("arrow_uturn", "in_1", "d")
    left = _resolve(_movement("left"), arrows=(arrow,))
    uturn = _resolve(_movement("uturn"), arrows=(arrow,))

    assert left.restored_rules[0].decision_status == DecisionStatus.PROHIBITED
    assert uturn.restored_rules[0].decision_status == DecisionStatus.SUPPORTED


@pytest.mark.parametrize(
    ("arrow", "expected_risk"),
    (
        (_valid_arrow("arrow_9", "in_1", "9"), "arrow_not_usable_for_decision"),
        (_valid_arrow("arrow_o", "in_1", "o"), "arrow_not_usable_for_decision"),
        (_valid_arrow("arrow_unknown", "in_1", "?"), "unknown_arrow_code"),
        (
            _valid_arrow(
                "arrow_incomplete",
                "in_1",
                "a",
                lane_sequence_complete=False,
            ),
            "incomplete_lane_sequence",
        ),
    ),
)
def test_scenario_10_unusable_or_incomplete_laneinfo_is_unknown(
    arrow: ArrowInput,
    expected_risk: str,
) -> None:
    decision = evaluate_road_arrow_directions(_movement("right"), (arrow,))[0]

    assert decision.decision_status == DecisionStatus.UNKNOWN
    assert expected_risk in decision.risk_flags


def test_scenario_11_direction_mismatch_is_unknown() -> None:
    arrow = _valid_arrow(
        "arrow_wrong_direction",
        "in_1",
        "c",
        direction_matched=False,
    )
    decision = evaluate_road_arrow_directions(_movement("right"), (arrow,))[0]

    assert decision.decision_status == DecisionStatus.UNKNOWN
    assert "direction_mismatch" in decision.risk_flags


def test_scenario_18_restriction_wins_three_source_conflict_with_complete_chain() -> None:
    movement = _movement("right")
    result = _resolve(
        movement,
        restrictions=(_restriction("restriction_three_way", movement.carrier_road_pairs[0]),),
        arrows=(_valid_arrow("arrow_right", "in_1", "c"),),
        special_profile=_special_profile("in_1", dedicated_movement_type="right"),
    )

    rule = _restriction_rules(result)[0]
    assert rule.decision_status == DecisionStatus.PROHIBITED
    assert rule.decision_source == DecisionSource.RESTRICTION
    assert rule.inference_level == InferenceLevel.EXPLICIT
    assert {entry.overridden_source for entry in rule.override_chain} == {
        DecisionSource.LANEINFO,
        DecisionSource.SPECIAL_CARRIER,
    }


def test_scenario_19_laneinfo_overrides_opposite_special_carrier_default() -> None:
    movement = _movement("straight")
    result = _resolve(
        movement,
        arrows=(_valid_arrow("arrow_straight", "in_1", "a"),),
        special_profile=_special_profile("in_1", dedicated_movement_type="right"),
    )

    rule = result.restored_rules[0]
    assert rule.decision_status == DecisionStatus.SUPPORTED
    assert rule.decision_source == DecisionSource.LANEINFO
    assert rule.evidence_priority == EvidencePriority.LANEINFO
    assert any(entry.overridden_source == DecisionSource.SPECIAL_CARRIER for entry in rule.override_chain)


@pytest.mark.parametrize("formal_role", ("internal", "parallel"))
def test_restore_field_rules_profiles_all_formal_arm_roads_and_laneinfo_overrides(
    formal_role: str,
) -> None:
    road_id = f"{formal_role}_right_carrier"
    arm = T09SwsdArm(
        junction_id="junction_1",
        arm_id="arm_in",
        internal_road_ids=(road_id,) if formal_role == "internal" else tuple(),
        parallel_branch_road_ids=(road_id,) if formal_role == "parallel" else tuple(),
        approach_road_ids=(road_id,),
    )
    movement = _movement(
        "straight",
        pairs=(RoadPair(road_id, "out_1"),),
    )
    kwargs = {
        "arms": (arm,),
        "movements": (movement,),
        "road_attributes": (RoadAttributes(road_id=road_id, formway=128),),
        "strategy_version": RestorationStrategy.MULTI_EVIDENCE_V2,
    }

    special_only = restore_field_rules(**kwargs)
    special_rule = special_only.restored_rules[0]
    special_evidence = next(
        item
        for item in special_only.evidence_items
        if item.evidence_type == EvidenceType.SPECIAL_CARRIER
    )
    expected_role_risk = (
        "special_carrier_inside_core_requires_review"
        if formal_role == "internal"
        else "special_carrier_topology_subtype_unverified"
    )
    assert expected_role_risk in special_evidence.risk_flags
    assert special_evidence.inference_level == InferenceLevel.WEAK_DERIVED
    assert special_evidence.verification_status != VerificationStatus.VERIFIED_SWSD
    assert special_rule.decision_source == DecisionSource.SPECIAL_CARRIER
    assert special_rule.inference_level == InferenceLevel.WEAK_DERIVED

    lane_wins = restore_field_rules(
        **kwargs,
        arrows=(_valid_arrow("straight_lane", road_id, "a"),),
    )
    lane_rule = lane_wins.restored_rules[0]
    assert lane_rule.decision_source == DecisionSource.LANEINFO
    assert lane_rule.decision_status == DecisionStatus.SUPPORTED
    assert any(
        entry.overridden_source == DecisionSource.SPECIAL_CARRIER
        for entry in lane_rule.override_chain
    )


def test_real_builder_internal_special_carrier_keeps_source_provenance() -> None:
    roads = (
        SWSDRoadInput("main_in", "west", "junction_1", 2),
        SWSDRoadInput("internal_special", "junction_1", "junction_2", 2),
        SWSDRoadInput("out_1", "junction_1", "north", 2),
    )
    geometries = {
        "main_in": LineString([(-20.0, 0.0), (0.0, 0.0)]),
        "internal_special": LineString([(0.0, 0.0), (1.0, 1.0)]),
        "out_1": LineString([(0.0, 0.0), (0.0, 20.0)]),
    }
    segments = (
        SWSDSegmentInput("segment_in", junc_nodes=("junction_1",), road_ids=("main_in",)),
        SWSDSegmentInput("segment_out", junc_nodes=("junction_1",), road_ids=("out_1",)),
    )
    arms = build_swsd_arms(
        junction_id="junction_1",
        member_node_ids=("junction_1", "junction_2"),
        roads=roads,
        segments=segments,
        road_geometries=geometries,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
    )
    movement = next(
        item
        for item in build_arm_movements(junction_id="junction_1", arms=arms)
        if {pair.from_road_id for pair in item.carrier_road_pairs} == {"main_in"}
        and {pair.to_road_id for pair in item.carrier_road_pairs} == {"out_1"}
    )
    movement = replace(movement, movement_id="movement_internal_special", movement_type="right")
    kwargs = {
        "arms": arms,
        "movements": (movement,),
        "road_attributes": (
            RoadAttributes("main_in"),
            RoadAttributes("internal_special", formway=128),
            RoadAttributes("out_1"),
        ),
        "strategy_version": RestorationStrategy.MULTI_EVIDENCE_V2,
    }

    special_only = restore_field_rules(**kwargs)
    special_evidence = next(
        item
        for item in special_only.evidence_items
        if item.evidence_type == EvidenceType.SPECIAL_CARRIER
    )
    assert special_evidence.provenance.source_id == "internal_special"
    assert special_evidence.provenance.field_audit["source_carrier_road_ids"] == (
        "internal_special",
    )
    assert special_evidence.verification_status == VerificationStatus.MANUAL_REVIEW_REQUIRED

    lane_wins = restore_field_rules(
        **kwargs,
        arrows=(_valid_arrow("main_right", "main_in", "c"),),
    )
    lane_rule = lane_wins.restored_rules[0]
    assert lane_rule.decision_source == DecisionSource.LANEINFO
    assert any(
        entry.overridden_source == DecisionSource.SPECIAL_CARRIER
        for entry in lane_rule.override_chain
    )


def test_scenario_20_special_carrier_only_remains_weak_inference() -> None:
    profile = _special_profile("in_1", dedicated_movement_type="right")
    supported = _resolve(_movement("right"), special_profile=profile)
    excluded = _resolve(_movement("straight"), special_profile=profile)

    supported_rule = supported.restored_rules[0]
    excluded_rule = excluded.restored_rules[0]
    assert supported_rule.decision_source == DecisionSource.SPECIAL_CARRIER
    assert supported_rule.decision_status == DecisionStatus.SUPPORTED
    assert supported_rule.inference_level == InferenceLevel.WEAK_DERIVED
    assert excluded_rule.decision_source == DecisionSource.SPECIAL_CARRIER
    assert excluded_rule.decision_status == DecisionStatus.PROHIBITED
    assert excluded_rule.inference_level == InferenceLevel.WEAK_DERIVED
    assert (
        excluded_rule.verification_status
        == VerificationStatus.UNVERIFIED_DUE_TO_MISSING_FRCSD_LANEINFO
    )


def test_mixed_road_atomic_outcomes_are_not_same_atom_conflict() -> None:
    pairs = (RoadPair("in_1", "out_1"), RoadPair("in_2", "out_1"))
    movement = _movement("right", pairs=pairs)
    result = _resolve(
        movement,
        arrows=(
            _valid_arrow("arrow_right", "in_1", "c"),
            _valid_arrow("arrow_no_right", "in_2", "a"),
        ),
    )

    assert {
        (rule.from_road_ids, rule.decision_status)
        for rule in result.restored_rules
    } == {
        (("in_1",), DecisionStatus.SUPPORTED),
        (("in_2",), DecisionStatus.PROHIBITED),
    }
    assert result.movement.decision_status != DecisionStatus.CONFLICT


def test_restriction_rule_merge_is_deterministic_under_input_reversal() -> None:
    pair = RoadPair("in_1", "out_1")
    movement = _movement(pairs=(pair,))
    evidence = (
        _manual_restriction_evidence(
            evidence_id="restriction:evidence_a",
            restriction_id="restriction_a",
            pair=pair,
        ),
        _manual_restriction_evidence(
            evidence_id="restriction:evidence_b",
            restriction_id="restriction_b",
            pair=pair,
        ),
    )

    def resolve(items: tuple[T09EvidenceItem, ...]):
        restriction_result = RestrictionMatchResult(
            evidence_items=items,
            prohibition_status=ProhibitionStatus.PARTIALLY_PROHIBITED,
            prohibition_reason=ProhibitionReason.EXPLICIT_RESTRICTION,
            confidence=1.0,
            restriction_coverage="partial_restricted",
            scope_promotion_status="partial_coverage",
            scope_promotion_reason="kept atomic for deterministic merge test",
        )
        return _resolve(movement, restriction_result=restriction_result)

    forward = resolve(evidence)
    reverse = resolve(tuple(reversed(evidence)))

    assert to_jsonable(forward.restored_rules) == to_jsonable(reverse.restored_rules)
    assert len(forward.restored_rules) == 1
    assert set(forward.restored_rules[0].source_restriction_ids) == {
        "restriction_a",
        "restriction_b",
    }
    assert set(forward.restored_rules[0].supporting_evidence_ids) == {
        "restriction:evidence_a",
        "restriction:evidence_b",
    }


def test_default_arrow_metadata_cannot_form_determined_v2_decision() -> None:
    arrow = ArrowInput(
        arrow_id="arrow_without_metadata",
        road_id="in_1",
        lane_codes=("c",),
    )

    decision = evaluate_road_arrow_directions(_movement("right"), (arrow,))[0]

    assert arrow.sequence_metadata_status == "not_provided"
    assert decision.decision_status == DecisionStatus.UNKNOWN
    assert decision.confidence == 0.0


def test_default_strategy_is_identical_to_explicit_restriction_only_v1() -> None:
    movement = _movement("right")
    kwargs = {
        "arms": tuple(),
        "movements": (movement,),
        "restrictions": (
            _restriction("restriction_v1_compat", movement.carrier_road_pairs[0]),
        ),
        "arrows": (_valid_arrow("arrow_v1_compat", "in_1", "c"),),
    }

    default_result = restore_field_rules(**kwargs)
    explicit_result = restore_field_rules(
        **kwargs,
        strategy_version="restriction_only_v1",
    )

    assert to_jsonable(default_result) == to_jsonable(explicit_result)


def test_v2_preserves_same_restriction_pair_with_distinct_conditions_deterministically() -> None:
    movement = _movement("right")
    pair = movement.carrier_road_pairs[0]
    restrictions = (
        _restriction("shared_cond_id", pair, TimeWindow="AM"),
        _restriction("shared_cond_id", pair, TimeWindow="PM"),
    )

    def run(items: tuple[RestrictionInput, ...]):
        return restore_field_rules(
            arms=tuple(),
            movements=(movement,),
            restrictions=items,
            strategy_version="multi_evidence_v2",
        )

    forward = run(restrictions)
    reverse = run(tuple(reversed(restrictions)))
    restriction_evidence = tuple(
        item
        for item in forward.evidence_items
        if item.evidence_type == EvidenceType.RESTRICTION
    )
    restriction_rules = tuple(
        item
        for item in forward.restored_rules
        if item.decision_source == DecisionSource.RESTRICTION
    )

    assert len(restriction_evidence) == 2
    assert len({item.condition_identity for item in restriction_evidence}) == 2
    assert len(restriction_rules) == 2
    assert len({item.condition_identity for item in restriction_rules}) == 2
    assert to_jsonable(forward) == to_jsonable(reverse)
