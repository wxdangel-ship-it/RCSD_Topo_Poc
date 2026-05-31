import json

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import (
    ArrowInput,
    EvidenceType,
    InferenceLevel,
    MovementApplicability,
    ProhibitionReason,
    ProhibitionStatus,
    RestrictionInput,
    RoadPair,
    SWSDSegmentInput,
    SWSDRoadInput,
    T09ArmMovement,
    build_arm_movements,
    build_swsd_arms,
    restore_field_rules,
    to_jsonable,
)


def test_arm_builder_marks_segment_junc_node_internal_split() -> None:
    arms = build_swsd_arms(
        junction_id="j1",
        member_node_ids=("jn_1", "jn_2"),
        roads=(
            SWSDRoadInput(road_id="r_in", snodeid="n_w", enodeid="jn_1", direction=2),
            SWSDRoadInput(road_id="r_out", snodeid="jn_2", enodeid="n_e", direction=2),
            SWSDRoadInput(road_id="r_internal", snodeid="jn_1", enodeid="jn_2", direction=0),
        ),
        segments=(
            SWSDSegmentInput(
                segment_id="seg_1",
                pair_nodes=("n_w", "n_e"),
                junc_nodes=("jn_1", "jn_2"),
                road_ids=("r_in", "r_internal", "r_out"),
            ),
        ),
    )

    assert len(arms) == 2
    assert {arm.terminal_kind for arm in arms} == {"segment_junc_node"}
    assert all(arm.segment_ids == ("seg_1",) for arm in arms)
    assert all(arm.internal_road_ids == ("r_internal",) for arm in arms)

    movement = next(
        item
        for item in build_arm_movements(junction_id="j1", arms=arms)
        if item.carrier_road_pairs == (RoadPair("r_in", "r_out"),)
    )

    assert movement.movement_applicability == MovementApplicability.APPLICABLE
    assert movement.candidate_road_pair_count == 1


def test_topology_not_applicable_is_not_reported_as_prohibition() -> None:
    movement = T09ArmMovement(
        junction_id="j1",
        movement_id="m_topology",
        from_arm_id="from",
        to_arm_id="to",
        movement_type="left",
        movement_applicability=MovementApplicability.NOT_APPLICABLE,
        carrier_universe_status="empty",
    )

    result = restore_field_rules(arms=tuple(), movements=(movement,))

    assert result.movements[0].movement_applicability == MovementApplicability.NOT_APPLICABLE
    assert result.movements[0].prohibition_status == ProhibitionStatus.NOT_A_TRAFFIC_RULE
    assert result.evidence_items[0].supports_prohibition is False
    assert result.restored_rules[0].field_rule_status == ProhibitionStatus.NOT_A_TRAFFIC_RULE
    assert result.summary["qa"]["topology_silent_fix"] is False


def test_restriction_priority_with_arrow_conflict_keeps_restriction_rule() -> None:
    movement = T09ArmMovement(
        junction_id="j1",
        movement_id="m_conflict",
        from_arm_id="from",
        to_arm_id="to",
        movement_type="left",
        candidate_road_pair_count=1,
        carrier_universe_status="available",
        carrier_road_pairs=(RoadPair("in_1", "out_1"),),
    )

    result = restore_field_rules(
        arms=tuple(),
        movements=(movement,),
        restrictions=(
            RestrictionInput(
                restriction_id="rst_1",
                in_link_id="in_1",
                out_link_id="out_1",
            ),
        ),
        arrows=(
            ArrowInput(
                arrow_id="arr_left",
                road_id="in_1",
                lane_codes=("b",),
            ),
        ),
    )

    evidence_types = {item.evidence_type for item in result.evidence_items}
    conflict_items = [item for item in result.evidence_items if item.evidence_type == EvidenceType.CONFLICT]

    assert result.movements[0].prohibition_status == ProhibitionStatus.FULLY_PROHIBITED
    assert result.movements[0].prohibition_reason == ProhibitionReason.EXPLICIT_RESTRICTION
    assert evidence_types == {EvidenceType.RESTRICTION, EvidenceType.ARROW, EvidenceType.CONFLICT}
    assert conflict_items
    assert result.restored_rules[0].field_rule_status == ProhibitionStatus.FULLY_PROHIBITED
    assert result.restored_rules[0].inference_level == InferenceLevel.CONFLICT
    assert conflict_items[0].evidence_id in result.restored_rules[0].conflicting_evidence_ids
    assert result.summary["qa"]["crs_transform_executed"] is False
    assert json.loads(json.dumps(to_jsonable(result)))["summary"]["input_counts"]["movements"] == 1
