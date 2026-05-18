from __future__ import annotations

from rcsd_topo_poc.modules.p01_arm_build.models import ArmCorridorEvidence, FinalArm, RoadMovementEvidence
from rcsd_topo_poc.modules.p01_arm_build.movement import _build_arm_movements


def _final_arm(arm_id: str, trunk_road_ids: tuple[str, ...]) -> FinalArm:
    return FinalArm(
        dataset="RCSD",
        current_junction_id="J",
        final_arm_id=arm_id,
        source_initial_arm_ids=(f"A_{arm_id}",),
        merge_status="not_applied",
        merge_reason="test_fixture",
        initial_arm={"seed_road_ids": trunk_road_ids},
        trunk_road_ids=trunk_road_ids,
        trunk_status="partial",
        trunk_reason="test_fixture",
    )


def _corridor(arm_id: str, angle: float) -> ArmCorridorEvidence:
    return ArmCorridorEvidence(
        dataset="RCSD",
        current_junction_id="J",
        final_arm_id=arm_id,
        source_seed_road_ids=(),
        support_road_ids=(),
        support_node_ids=(),
        corridor_terminal_junction_id=None,
        corridor_terminal_type="semantic_boundary",
        corridor_angle_deg=angle,
        corridor_length=1.0,
        corridor_status="extended",
        risk_flags=(),
    )


def test_unique_trunk_evidence_breaks_multiple_straight_candidate_tie() -> None:
    movements = _build_arm_movements(
        dataset="RCSD",
        junction_id="J",
        final_arms=(
            _final_arm("F5", ("from_trunk",)),
            _final_arm("F2", ("to_f2_trunk",)),
            _final_arm("F3", ("to_f3_trunk",)),
        ),
        local_candidates=(),
        arm_corridor_evidence=(
            _corridor("F5", 266.0),
            _corridor("F2", 92.0),
            _corridor("F3", 101.0),
        ),
        roads={},
        evidence=(
            RoadMovementEvidence(
                evidence_id="rme_1",
                dataset="RCSD",
                current_junction_id="J",
                raw_id="raw_1",
                road_id="from_trunk",
                next_road_id="to_f2_trunk",
                raw_type="",
                raw_turn_type="",
                source="",
                raw_properties={},
                from_arm_id="F5",
                to_arm_id="F2",
                from_road_role="trunk",
                to_road_role="trunk",
                mapping_status="mapped",
                issue_flags=(),
            ),
        ),
        advance_right_turn_relations=(),
        has_road_next_road_input=True,
    )

    by_pair = {(movement.from_arm_id, movement.to_arm_id): movement for movement in movements}

    assert by_pair[("F5", "F2")].movement_type == "straight"
    assert by_pair[("F5", "F2")].movement_type_source == "road_next_road_trunk_evidence"
    assert by_pair[("F5", "F2")].straight_target_status == "unique_straight_target"
    assert by_pair[("F5", "F3")].movement_type == "unknown"
    assert by_pair[("F5", "F3")].movement_type_reason == "straight_target_resolved_to_other_arm"
