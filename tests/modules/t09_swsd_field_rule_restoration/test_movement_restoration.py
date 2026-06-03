import json

from shapely.geometry import LineString

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration import (
    ArrowInput,
    EvidenceType,
    InferenceLevel,
    MovementApplicability,
    ProhibitionReason,
    ProhibitionStatus,
    RestrictionInput,
    RoadAttributes,
    RoadPair,
    SWSDSegmentInput,
    SWSDRoadInput,
    T09ArmMovement,
    T09SwsdArm,
    build_arm_movements,
    build_swsd_arms,
    restore_field_rules,
    to_jsonable,
)


def _geometry(coords: list[tuple[float, float]]) -> LineString:
    return LineString(coords)


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


def test_arm_builder_merges_same_direction_multi_segment_arm() -> None:
    roads = (
        SWSDRoadInput(road_id="e_in_main", snodeid="n_e1", enodeid="j", direction=2),
        SWSDRoadInput(road_id="e_out", snodeid="j", enodeid="n_e2", direction=2),
        SWSDRoadInput(road_id="e_in_aux", snodeid="n_e3", enodeid="j", direction=2),
        SWSDRoadInput(road_id="n_in", snodeid="n_n1", enodeid="j", direction=2),
        SWSDRoadInput(road_id="n_out", snodeid="j", enodeid="n_n2", direction=2),
        SWSDRoadInput(road_id="w_in", snodeid="n_w1", enodeid="j", direction=2),
        SWSDRoadInput(road_id="w_out", snodeid="j", enodeid="n_w2", direction=2),
        SWSDRoadInput(road_id="s_in", snodeid="n_s1", enodeid="j", direction=2),
        SWSDRoadInput(road_id="s_out", snodeid="j", enodeid="n_s2", direction=2),
    )
    arms = build_swsd_arms(
        junction_id="j",
        member_node_ids=("j",),
        roads=roads,
        segments=(
            SWSDSegmentInput(segment_id="seg_e_main", pair_nodes=("j", "n_e2"), road_ids=("e_in_main", "e_out")),
            SWSDSegmentInput(segment_id="seg_e_aux", pair_nodes=("j", "n_e3"), road_ids=("e_in_aux",)),
            SWSDSegmentInput(segment_id="seg_n", pair_nodes=("j", "n_n2"), road_ids=("n_in", "n_out")),
            SWSDSegmentInput(segment_id="seg_w", pair_nodes=("j", "n_w2"), road_ids=("w_in", "w_out")),
            SWSDSegmentInput(segment_id="seg_s", pair_nodes=("j", "n_s2"), road_ids=("s_in", "s_out")),
        ),
        road_geometries={
            "e_in_main": _geometry([(10.0, 0.0), (0.0, 0.0)]),
            "e_out": _geometry([(0.0, 0.0), (10.0, 0.5)]),
            "e_in_aux": _geometry([(11.0, -0.5), (0.0, 0.0)]),
            "n_in": _geometry([(0.0, 10.0), (0.0, 0.0)]),
            "n_out": _geometry([(0.0, 0.0), (0.5, 10.0)]),
            "w_in": _geometry([(-10.0, 0.0), (0.0, 0.0)]),
            "w_out": _geometry([(0.0, 0.0), (-10.0, -0.5)]),
            "s_in": _geometry([(0.0, -10.0), (0.0, 0.0)]),
            "s_out": _geometry([(0.0, 0.0), (-0.5, -10.0)]),
        },
    )

    assert len(arms) == 4
    east_arm = next(arm for arm in arms if set(arm.seed_road_ids) == {"e_in_aux", "e_in_main", "e_out"})
    assert set(east_arm.segment_ids) == {"seg_e_aux", "seg_e_main"}
    assert east_arm.approach_road_ids == ("e_in_aux", "e_in_main")
    assert east_arm.exit_road_ids == ("e_out",)
    assert east_arm.terminal_kind == "multi_segment_directional_corridor"
    assert "multi_segment_directional_arm" in east_arm.risk_flags

    movements = build_arm_movements(junction_id="j", arms=arms)
    assert len(movements) == 16
    assert next(item for item in movements if item.from_arm_id == east_arm.arm_id and item.to_arm_id == east_arm.arm_id).candidate_road_pair_count == 2


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
    assert result.movements[0].restriction_coverage == "not_applicable"
    assert result.movements[0].arrow_direction_status == "not_applicable"
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
    assert result.movements[0].restriction_coverage == "all_restricted"
    assert result.movements[0].arrow_direction_status == "supports_movement"
    assert evidence_types == {EvidenceType.RESTRICTION, EvidenceType.ARROW, EvidenceType.CONFLICT}
    assert conflict_items
    assert result.restored_rules[0].field_rule_status == ProhibitionStatus.FULLY_PROHIBITED
    assert result.restored_rules[0].inference_level == InferenceLevel.CONFLICT
    assert conflict_items[0].evidence_id in result.restored_rules[0].conflicting_evidence_ids
    assert result.summary["qa"]["crs_transform_executed"] is False
    assert json.loads(json.dumps(to_jsonable(result)))["summary"]["input_counts"]["movements"] == 1


def test_arrow_exclusion_without_restriction_does_not_restore_prohibition_rule() -> None:
    movement = T09ArmMovement(
        junction_id="j1",
        movement_id="m_arrow_only",
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
        arrows=(
            ArrowInput(
                arrow_id="arr_straight_right",
                road_id="in_1",
                lane_codes=("a", "c"),
            ),
        ),
    )

    restored = result.movements[0]
    assert restored.prohibition_status == ProhibitionStatus.NO_PROHIBITION_EVIDENCE
    assert restored.prohibition_reason == ProhibitionReason.INSUFFICIENT_EVIDENCE
    assert restored.arrow_direction_status == "excludes_movement"
    assert {item.evidence_type for item in result.evidence_items} == {EvidenceType.COMPLETE_ARROW_EXCLUSION}
    assert all(item.supports_prohibition is False for item in result.evidence_items)
    assert result.restored_rules == tuple()
    assert result.summary["business_policy"]["prohibition_source"] == "restriction_only"


def test_restoration_populates_movement_level_business_evidence_summary() -> None:
    movement = T09ArmMovement(
        junction_id="j1",
        movement_id="m_summary",
        from_arm_id="from",
        to_arm_id="to",
        movement_type="left",
        candidate_road_pair_count=1,
        carrier_universe_status="available",
        carrier_road_pairs=(RoadPair("in_1", "out_1"),),
    )

    result = restore_field_rules(
        arms=(
            T09SwsdArm(
                junction_id="j1",
                arm_id="from",
                seed_road_ids=("in_1",),
                advance_left_road_ids=("in_1",),
            ),
            T09SwsdArm(junction_id="j1", arm_id="to", seed_road_ids=("out_1",)),
        ),
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
        road_attributes=(RoadAttributes(road_id="in_1", formway=256),),
    )

    restored = result.movements[0]
    assert restored.restriction_coverage == "all_restricted"
    assert restored.partial_basis == "not_applicable"
    assert restored.remaining_restriction_status == "not_applicable"
    assert restored.arrow_direction_status == "supports_movement"
    assert restored.arrow_lane_summary["supporting_lane_count"] == 1
    assert restored.advance_left_status == "present"
    assert restored.advance_right_status == "not_applicable"


def test_restoration_records_partial_restriction_basis_on_movement() -> None:
    movement = T09ArmMovement(
        junction_id="j1",
        movement_id="m_partial",
        from_arm_id="from",
        to_arm_id="to",
        movement_type="straight",
        candidate_road_pair_count=2,
        carrier_universe_status="available",
        carrier_road_pairs=(
            RoadPair("in_1", "out_1"),
            RoadPair("in_1", "out_2"),
        ),
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
    )

    restored = result.movements[0]
    assert restored.prohibition_status == ProhibitionStatus.PARTIALLY_PROHIBITED
    assert restored.restriction_coverage == "partial_restricted"
    assert restored.partial_basis == "exit_arm_subset"
    assert restored.remaining_restriction_status == "no_restriction_evidence"


def test_restoration_records_advance_right_status_on_right_movement() -> None:
    movement = T09ArmMovement(
        junction_id="j1",
        movement_id="m_right",
        from_arm_id="from",
        to_arm_id="to",
        movement_type="right",
        candidate_road_pair_count=1,
        carrier_universe_status="available",
        carrier_road_pairs=(RoadPair("in_1", "out_1"),),
    )

    result = restore_field_rules(
        arms=(T09SwsdArm(junction_id="j1", arm_id="from", seed_road_ids=("in_1",)),),
        movements=(movement,),
        road_attributes=(RoadAttributes(road_id="in_1", kind="12|0a"),),
    )

    restored = result.movements[0]
    assert restored.advance_left_status == "not_applicable"
    assert restored.advance_right_status == "present_bypass_core_junction"
