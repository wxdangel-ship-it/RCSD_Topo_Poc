from __future__ import annotations

import math

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    MovementApplicability,
    ProhibitionReason,
    ProhibitionStatus,
    RoadPair,
    T09ArmMovement,
    T09SwsdArm,
)


STRAIGHT_TARGET_MAX_ANGLE_DEG = 35.0


def build_arm_movements(*, junction_id: str, arms: tuple[T09SwsdArm, ...]) -> tuple[T09ArmMovement, ...]:
    movements: list[T09ArmMovement] = []
    for from_arm in arms:
        for to_arm in arms:
            road_pairs = tuple(
                RoadPair(from_road_id=from_road_id, to_road_id=to_road_id)
                for from_road_id in from_arm.approach_road_ids
                for to_road_id in to_arm.exit_road_ids
            )
            if not road_pairs:
                movements.append(_not_applicable_movement(junction_id, from_arm, to_arm))
                continue
            movements.append(
                T09ArmMovement(
                    junction_id=junction_id,
                    movement_id=f"{junction_id}:movement:{from_arm.arm_id}->{to_arm.arm_id}",
                    from_arm_id=from_arm.arm_id,
                    to_arm_id=to_arm.arm_id,
                    movement_type=_movement_type(from_arm, to_arm),
                    candidate_road_pair_count=len(road_pairs),
                    carrier_universe_status="available",
                    prohibition_status=ProhibitionStatus.UNKNOWN,
                    prohibition_reason=ProhibitionReason.INSUFFICIENT_EVIDENCE,
                    carrier_road_pairs=road_pairs,
                )
            )
    return tuple(movements)


def _not_applicable_movement(junction_id: str, from_arm: T09SwsdArm, to_arm: T09SwsdArm) -> T09ArmMovement:
    return T09ArmMovement(
        junction_id=junction_id,
        movement_id=f"{junction_id}:movement:{from_arm.arm_id}->{to_arm.arm_id}",
        from_arm_id=from_arm.arm_id,
        to_arm_id=to_arm.arm_id,
        movement_type="uturn" if from_arm.arm_id == to_arm.arm_id else "unknown",
        movement_applicability=MovementApplicability.NOT_APPLICABLE,
        candidate_road_pair_count=0,
        carrier_universe_status="empty",
        prohibition_status=ProhibitionStatus.NOT_A_TRAFFIC_RULE,
        prohibition_reason=ProhibitionReason.TOPOLOGY_NOT_APPLICABLE,
        risk_flags=("empty_carrier_universe",),
    )


def _movement_type(from_arm: T09SwsdArm, to_arm: T09SwsdArm) -> str:
    if from_arm.arm_id == to_arm.arm_id:
        return "uturn"
    if from_arm.angle_deg is None or to_arm.angle_deg is None:
        return "unknown"
    from_vector = _angle_to_vector(float(from_arm.angle_deg))
    to_vector = _angle_to_vector(float(to_arm.angle_deg))
    incoming = (-from_vector[0], -from_vector[1])
    straight_angle = _angle_between(incoming, to_vector)
    if straight_angle <= STRAIGHT_TARGET_MAX_ANGLE_DEG:
        return "straight"
    cross = incoming[0] * to_vector[1] - incoming[1] * to_vector[0]
    if abs(cross) <= 0.08:
        return "unknown"
    return "left" if cross > 0 else "right"


def _angle_to_vector(angle_deg: float) -> tuple[float, float]:
    radians = math.radians(angle_deg)
    return (math.cos(radians), math.sin(radians))


def _angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.degrees(math.acos(dot))
