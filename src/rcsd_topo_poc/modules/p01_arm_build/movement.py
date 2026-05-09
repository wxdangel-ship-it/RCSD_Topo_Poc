from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from shapely.geometry import LineString

from rcsd_topo_poc.modules.p01_arm_build.models import (
    AdvanceRightTurnRelation,
    ArmMovement,
    ArmReceivingRoadRole,
    CorrectedFinalArm,
    FinalArm,
    InitialArm,
    LocalArmCandidate,
    RawRoadNextRoad,
    RoadMovementEvidence,
    RoadRecord,
    TrunkCorrection,
)
from rcsd_topo_poc.modules.p01_arm_build.trunk import build_trunk_for_arm


@dataclass(frozen=True)
class MovementBuildResult:
    road_movement_evidence: tuple[RoadMovementEvidence, ...]
    arm_movements: tuple[ArmMovement, ...]
    arm_receiving_road_roles: tuple[ArmReceivingRoadRole, ...]
    trunk_corrections: tuple[TrunkCorrection, ...]
    corrected_final_arms: tuple[CorrectedFinalArm, ...]
    issues: tuple[dict[str, Any], ...]
    metrics: dict[str, Any]


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return tuple()
    if isinstance(value, tuple):
        return tuple(str(item) for item in value)
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return (str(value),)


def _arm_payload(arm: FinalArm) -> dict[str, Any]:
    payload = dict(arm.initial_arm or {})
    payload.setdefault("member_road_ids", tuple())
    payload.setdefault("seed_road_ids", tuple())
    payload.setdefault("connector_road_ids", tuple())
    payload.setdefault("inbound_member_road_ids", tuple())
    payload.setdefault("outbound_member_road_ids", tuple())
    payload.setdefault("bidirectional_member_road_ids", tuple())
    return payload


def _final_arm_to_initial(arm: FinalArm) -> InitialArm:
    payload = _arm_payload(arm)
    return InitialArm(
        dataset=arm.dataset,
        current_junction_id=arm.current_junction_id,
        initial_arm_id=arm.final_arm_id,
        terminal_type=str(payload.get("terminal_type") or ""),
        terminal_junction_id=payload.get("terminal_junction_id"),
        terminal_member_node_ids=_tuple(payload.get("terminal_member_node_ids")),
        member_road_ids=_tuple(payload.get("member_road_ids")),
        seed_road_ids=_tuple(payload.get("seed_road_ids")),
        connector_road_ids=_tuple(payload.get("connector_road_ids")),
        inbound_member_road_ids=_tuple(payload.get("inbound_member_road_ids")),
        outbound_member_road_ids=_tuple(payload.get("outbound_member_road_ids")),
        bidirectional_member_road_ids=_tuple(payload.get("bidirectional_member_road_ids")),
        build_status=str(payload.get("build_status") or ""),
        risk_flags=_tuple(payload.get("risk_flags")),
        has_advance_left_turn=arm.has_advance_left_turn,
        advance_left_turn_road_ids=arm.advance_left_turn_road_ids,
        trunk_road_ids=arm.trunk_road_ids,
        trunk_status=arm.trunk_status,
        trunk_reason=arm.trunk_reason,
        non_trunk_member_road_ids=arm.non_trunk_member_road_ids,
        has_inbound_advance_right_turn=arm.has_inbound_advance_right_turn,
        advance_right_turn_relation_ids=arm.advance_right_turn_relation_ids,
        advance_right_turn_target_arm_ids=arm.advance_right_turn_target_arm_ids,
    )


def _road_mapping(
    final_arms: tuple[FinalArm, ...],
    *,
    mode: str,
) -> tuple[dict[str, tuple[tuple[str, str], ...]], dict[str, tuple[tuple[str, str], ...]]]:
    valid: dict[str, list[tuple[str, str]]] = defaultdict(list)
    conflicts: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for arm in final_arms:
        payload = _arm_payload(arm)
        inbound = set(_tuple(payload.get("inbound_member_road_ids")))
        outbound = set(_tuple(payload.get("outbound_member_road_ids")))
        bidirectional = set(_tuple(payload.get("bidirectional_member_road_ids")))
        trunk = set(arm.trunk_road_ids)
        if mode == "from":
            for road_id in inbound:
                valid[road_id].append((arm.final_arm_id, "inbound"))
            for road_id in bidirectional:
                valid[road_id].append((arm.final_arm_id, "bidirectional"))
            for road_id in trunk - inbound - bidirectional - outbound:
                valid[road_id].append((arm.final_arm_id, "trunk_inbound_capable"))
            for road_id in outbound - inbound - bidirectional:
                conflicts[road_id].append((arm.final_arm_id, "outbound_only"))
        else:
            for road_id in outbound:
                valid[road_id].append((arm.final_arm_id, "outbound"))
            for road_id in bidirectional:
                valid[road_id].append((arm.final_arm_id, "bidirectional"))
            for road_id in trunk - inbound - bidirectional - outbound:
                valid[road_id].append((arm.final_arm_id, "trunk_outbound_capable"))
            for road_id in inbound - outbound - bidirectional:
                conflicts[road_id].append((arm.final_arm_id, "inbound_only"))
    return (
        {road_id: tuple(items) for road_id, items in valid.items()},
        {road_id: tuple(items) for road_id, items in conflicts.items()},
    )


def _map_raw_evidence(
    *,
    dataset: str,
    junction_id: str,
    raw_records: tuple[RawRoadNextRoad, ...],
    final_arms: tuple[FinalArm, ...],
) -> tuple[tuple[RoadMovementEvidence, ...], tuple[dict[str, Any], ...]]:
    from_valid, from_conflicts = _road_mapping(final_arms, mode="from")
    to_valid, to_conflicts = _road_mapping(final_arms, mode="to")
    arm_road_universe = set(from_valid) | set(to_valid) | set(from_conflicts) | set(to_conflicts)
    evidence: list[RoadMovementEvidence] = []
    issues: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_records, start=1):
        issue_flags: list[str] = []
        from_matches = from_valid.get(raw.road_id, tuple())
        to_matches = to_valid.get(raw.next_road_id, tuple())
        status = "mapped"
        if len(from_matches) > 1 or len(to_matches) > 1:
            status = "ambiguous_arm_mapping"
        elif not from_matches and raw.road_id in from_conflicts:
            status = "from_road_role_conflict"
        elif not to_matches and raw.next_road_id in to_conflicts:
            status = "to_road_role_conflict"
        elif not from_matches and not to_matches and raw.road_id not in arm_road_universe and raw.next_road_id not in arm_road_universe:
            status = "cross_junction_or_out_of_scope"
        elif not from_matches:
            status = "from_road_not_in_any_arm"
        elif not to_matches:
            status = "to_road_not_in_any_arm"
        if status != "mapped":
            issue_flags.append(status)
        from_arm_id = from_matches[0][0] if len(from_matches) == 1 else None
        to_arm_id = to_matches[0][0] if len(to_matches) == 1 else None
        item = RoadMovementEvidence(
            evidence_id=f"{dataset.lower()}_{junction_id}_rme_{index:04d}",
            dataset=dataset,
            current_junction_id=junction_id,
            raw_id=raw.raw_id,
            road_id=raw.road_id,
            next_road_id=raw.next_road_id,
            raw_type=raw.raw_type,
            raw_turn_type=raw.raw_turn_type,
            source=raw.source,
            raw_properties=raw.raw_properties,
            from_arm_id=from_arm_id,
            to_arm_id=to_arm_id,
            from_road_role=from_matches[0][1] if len(from_matches) == 1 else "",
            to_road_role=to_matches[0][1] if len(to_matches) == 1 else "",
            mapping_status=status,
            issue_flags=tuple(issue_flags),
        )
        evidence.append(item)
        for flag in issue_flags:
            issues.append(
                {
                    "issue_type": f"road_movement_{flag}",
                    "evidence_id": item.evidence_id,
                    "road_id": raw.road_id,
                    "next_road_id": raw.next_road_id,
                }
            )
    return tuple(evidence), tuple(issues)


def _angle_to_vector(angle_deg: float) -> tuple[float, float]:
    radians = math.radians(angle_deg)
    return (math.cos(radians), math.sin(radians))


def _normalise(vector: tuple[float, float]) -> tuple[float, float] | None:
    length = math.hypot(vector[0], vector[1])
    if length <= 1e-9:
        return None
    return (vector[0] / length, vector[1] / length)


def _road_flow_vector(road: RoadRecord) -> tuple[float, float] | None:
    if road.geometry.is_empty:
        return None
    coords = list(road.geometry.coords) if isinstance(road.geometry, LineString) else list(road.geometry.boundary.coords)
    if len(coords) < 2:
        return None
    forward = (float(coords[-1][0]) - float(coords[0][0]), float(coords[-1][1]) - float(coords[0][1]))
    if road.direction == 3:
        forward = (-forward[0], -forward[1])
    return _normalise(forward)


def _seed_outward_vector(road: RoadRecord, role: str) -> tuple[float, float] | None:
    flow = _road_flow_vector(road)
    if flow is None:
        return None
    if role == "inbound":
        return (-flow[0], -flow[1])
    return flow


def _arm_vectors(
    *,
    final_arms: tuple[FinalArm, ...],
    local_candidates: tuple[LocalArmCandidate, ...],
    roads: dict[str, RoadRecord],
) -> dict[str, tuple[float, float]]:
    vectors: dict[str, tuple[float, float]] = {}
    for arm in final_arms:
        source_initials = set(arm.source_initial_arm_ids)
        candidate_vectors = [
            _angle_to_vector(candidate.trend_angle_deg)
            for candidate in local_candidates
            if source_initials & set(candidate.source_initial_arm_ids)
        ]
        if candidate_vectors:
            vector = _normalise(
                (
                    sum(item[0] for item in candidate_vectors) / len(candidate_vectors),
                    sum(item[1] for item in candidate_vectors) / len(candidate_vectors),
                )
            )
            if vector:
                vectors[arm.final_arm_id] = vector
                continue
        payload = _arm_payload(arm)
        seed_roles = {
            **{road_id: "inbound" for road_id in _tuple(payload.get("inbound_member_road_ids"))},
            **{road_id: "outbound" for road_id in _tuple(payload.get("outbound_member_road_ids"))},
            **{road_id: "bidirectional" for road_id in _tuple(payload.get("bidirectional_member_road_ids"))},
        }
        seed_vectors = [_seed_outward_vector(roads[road_id], seed_roles.get(road_id, "bidirectional")) for road_id in _tuple(payload.get("seed_road_ids")) if road_id in roads]
        seed_vectors = [item for item in seed_vectors if item is not None]
        if seed_vectors:
            vector = _normalise(
                (
                    sum(item[0] for item in seed_vectors) / len(seed_vectors),
                    sum(item[1] for item in seed_vectors) / len(seed_vectors),
                )
            )
            if vector:
                vectors[arm.final_arm_id] = vector
    return vectors


def _angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    dot = max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))
    return math.degrees(math.acos(dot))


def _movement_type(
    *,
    from_arm_id: str,
    to_arm_id: str,
    vectors: dict[str, tuple[float, float]],
    has_trunk_evidence: bool,
) -> tuple[str, str, str, str]:
    if from_arm_id == to_arm_id:
        return "uturn", "same_arm", "high", "from_arm_id_equals_to_arm_id"
    from_vector = vectors.get(from_arm_id)
    to_vector = vectors.get(to_arm_id)
    if from_vector is None or to_vector is None:
        return "unknown", "insufficient_evidence", "low", "arm_direction_vector_missing"
    incoming = (-from_vector[0], -from_vector[1])
    straight_angle = _angle_between(incoming, to_vector)
    if straight_angle <= 35.0:
        if has_trunk_evidence:
            return "straight", "road_next_road_trunk_evidence", "high", "trunk_road_next_road_evidence_and_direction_continuity"
        return "straight", "local_arm_candidate_continuity", "medium", "opposite_arm_corridor_direction_continuity"
    cross = incoming[0] * to_vector[1] - incoming[1] * to_vector[0]
    if abs(cross) <= 0.08:
        return "unknown", "insufficient_evidence", "low", "relative_side_too_close_to_collinear"
    if cross > 0:
        return "left", "relative_side_after_straight_resolved", "medium", "target_arm_on_left_side_of_entering_flow"
    return "right", "relative_side_after_straight_resolved", "medium", "target_arm_on_right_side_of_entering_flow"


def _build_arm_movements(
    *,
    dataset: str,
    junction_id: str,
    final_arms: tuple[FinalArm, ...],
    local_candidates: tuple[LocalArmCandidate, ...],
    roads: dict[str, RoadRecord],
    evidence: tuple[RoadMovementEvidence, ...],
    advance_right_turn_relations: tuple[AdvanceRightTurnRelation, ...],
    has_road_next_road_input: bool,
) -> tuple[ArmMovement, ...]:
    evidence_by_pair: dict[tuple[str, str], list[RoadMovementEvidence]] = defaultdict(list)
    for item in evidence:
        if item.mapping_status == "mapped" and item.from_arm_id and item.to_arm_id:
            evidence_by_pair[(item.from_arm_id, item.to_arm_id)].append(item)
    vectors = _arm_vectors(final_arms=final_arms, local_candidates=local_candidates, roads=roads)
    arm_by_id = {arm.final_arm_id: arm for arm in final_arms}
    movements: list[ArmMovement] = []
    movement_index = 1
    for from_arm in final_arms:
        from_payload = _arm_payload(from_arm)
        from_trunk = set(from_arm.trunk_road_ids)
        for to_arm in final_arms:
            to_trunk = set(to_arm.trunk_road_ids)
            pair_evidence = tuple(evidence_by_pair.get((from_arm.final_arm_id, to_arm.final_arm_id), tuple()))
            has_trunk_evidence = any(item.road_id in from_trunk and item.next_road_id in to_trunk for item in pair_evidence)
            movement_type, type_source, confidence, reason = _movement_type(
                from_arm_id=from_arm.final_arm_id,
                to_arm_id=to_arm.final_arm_id,
                vectors=vectors,
                has_trunk_evidence=has_trunk_evidence,
            )
            if not has_road_next_road_input:
                permission_status = "out_of_scope"
            elif pair_evidence:
                permission_status = "allowed_supported"
            else:
                permission_status = "no_allowed_evidence"
            related_r7 = tuple(
                sorted(
                    relation.relation_id
                    for relation in advance_right_turn_relations
                    if relation.from_arm_id == from_arm.final_arm_id and relation.to_arm_id == to_arm.final_arm_id
                )
            )
            turn_summary = Counter(item.raw_turn_type or "<empty>" for item in pair_evidence)
            advance_left_ids = set(from_arm.advance_left_turn_road_ids)
            issue_flags = tuple(sorted({flag for item in pair_evidence for flag in item.issue_flags}))
            movements.append(
                ArmMovement(
                    movement_id=f"{dataset.lower()}_{junction_id}_mov_{movement_index:04d}",
                    dataset=dataset,
                    current_junction_id=junction_id,
                    from_arm_id=from_arm.final_arm_id,
                    to_arm_id=to_arm.final_arm_id,
                    movement_type=movement_type,
                    movement_type_source=type_source,
                    movement_type_confidence=confidence,
                    movement_type_reason=reason,
                    permission_evidence_status=permission_status,
                    road_movement_evidence_ids=tuple(item.evidence_id for item in pair_evidence),
                    from_road_ids=tuple(sorted({item.road_id for item in pair_evidence})),
                    to_road_ids=tuple(sorted({item.next_road_id for item in pair_evidence})),
                    evidence_count=len(pair_evidence),
                    turn_type_summary=dict(sorted(turn_summary.items())),
                    has_advance_left_road_evidence=any(item.road_id in advance_left_ids for item in pair_evidence),
                    related_advance_right_relation_ids=related_r7,
                    issue_flags=issue_flags,
                )
            )
            movement_index += 1
    return tuple(movements)


def _receiving_roles(
    *,
    arm_movements: tuple[ArmMovement, ...],
    evidence_by_id: dict[str, RoadMovementEvidence],
) -> tuple[ArmReceivingRoadRole, ...]:
    stats: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    target_has_straight: Counter[str] = Counter()
    for movement in arm_movements:
        if movement.permission_evidence_status != "allowed_supported":
            continue
        for evidence_id in movement.road_movement_evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                continue
            key = (movement.to_arm_id, evidence.next_road_id)
            if movement.movement_type == "straight":
                stats[key]["straight_receiving_road"] += 1
                target_has_straight[movement.to_arm_id] += 1
            elif movement.movement_type == "left":
                stats[key]["left_turn_receiving_road"] += 1
                if movement.has_advance_left_road_evidence:
                    stats[key]["advance_left_receiving_road"] += 1
            elif movement.movement_type == "right":
                stats[key]["right_turn_receiving_road"] += 1
            else:
                stats[key]["unknown_receiving_road"] += 1
    roles: list[ArmReceivingRoadRole] = []
    for (target_arm_id, road_id), counts in sorted(stats.items()):
        receiving_roles = tuple(sorted(role for role, count in counts.items() if count > 0))
        straight_count = counts.get("straight_receiving_road", 0)
        advance_left_count = counts.get("advance_left_receiving_road", 0)
        exclude = advance_left_count > 0 and straight_count == 0 and target_has_straight[target_arm_id] > 0
        if exclude:
            reason = "advance_left_receiving_only_not_straight_receiving"
        elif advance_left_count > 0 and target_has_straight[target_arm_id] == 0:
            reason = "straight_receiving_evidence_missing"
        elif advance_left_count > 0 and straight_count > 0:
            reason = "straight_receiving_evidence_priority"
        else:
            reason = ""
        roles.append(
            ArmReceivingRoadRole(
                target_arm_id=target_arm_id,
                road_id=road_id,
                receiving_roles=receiving_roles,
                straight_evidence_count=straight_count,
                left_evidence_count=counts.get("left_turn_receiving_road", 0),
                advance_left_evidence_count=advance_left_count,
                right_evidence_count=counts.get("right_turn_receiving_road", 0),
                unknown_evidence_count=counts.get("unknown_receiving_road", 0),
                exclude_from_trunk=exclude,
                exclude_reason=reason,
            )
        )
    return tuple(roles)


def _corrected_final_arms(
    *,
    final_arms: tuple[FinalArm, ...],
    roles: tuple[ArmReceivingRoadRole, ...],
    roads: dict[str, RoadRecord],
    has_road_next_road_input: bool,
) -> tuple[tuple[TrunkCorrection, ...], tuple[CorrectedFinalArm, ...]]:
    roles_by_arm: dict[str, list[ArmReceivingRoadRole]] = defaultdict(list)
    for role in roles:
        roles_by_arm[role.target_arm_id].append(role)
    corrections: list[TrunkCorrection] = []
    corrected: list[CorrectedFinalArm] = []
    for arm in final_arms:
        original = tuple(arm.trunk_road_ids)
        if not has_road_next_road_input:
            status = "not_evaluated_no_road_next_road_input"
            reason = "road_next_road_input_missing"
            excluded: tuple[str, ...] = tuple()
            corrected_trunk = original
        else:
            arm_roles = roles_by_arm.get(arm.final_arm_id, [])
            excluded = tuple(sorted(role.road_id for role in arm_roles if role.exclude_from_trunk))
            straight_missing = any(role.exclude_reason == "straight_receiving_evidence_missing" for role in arm_roles)
            if excluded:
                pseudo = _final_arm_to_initial(arm)
                trunk = build_trunk_for_arm(pseudo, roads, additional_blocked_road_ids=set(excluded))
                corrected_trunk = trunk.trunk_road_ids
                if set(corrected_trunk) == set(original):
                    status = "candidate_excluded_but_trunk_unchanged"
                    reason = "movement_excluded_receiving_road_not_in_original_trunk"
                else:
                    status = "corrected"
                    reason = "advance_left_receiving_only_not_straight_receiving"
            elif straight_missing:
                corrected_trunk = original
                status = "straight_evidence_missing"
                reason = "advance_left_receiving_exists_but_no_straight_receiving_evidence"
            else:
                corrected_trunk = original
                status = "not_needed"
                reason = "no_movement_based_trunk_exclusion"
        corrections.append(
            TrunkCorrection(
                arm_id=arm.final_arm_id,
                original_trunk_road_ids=original,
                movement_excluded_receiving_road_ids=excluded,
                corrected_trunk_road_ids=corrected_trunk,
                trunk_correction_status=status,
                trunk_correction_reason=reason,
            )
        )
        payload = {
            "dataset": arm.dataset,
            "current_junction_id": arm.current_junction_id,
            "final_arm_id": arm.final_arm_id,
            "source_initial_arm_ids": list(arm.source_initial_arm_ids),
            "merge_status": arm.merge_status,
            "merge_reason": arm.merge_reason,
            "initial_arm": dict(arm.initial_arm),
            "has_advance_left_turn": arm.has_advance_left_turn,
            "advance_left_turn_road_ids": list(arm.advance_left_turn_road_ids),
            "trunk_road_ids": list(arm.trunk_road_ids),
            "trunk_status": arm.trunk_status,
            "trunk_reason": arm.trunk_reason,
            "non_trunk_member_road_ids": list(arm.non_trunk_member_road_ids),
            "has_inbound_advance_right_turn": arm.has_inbound_advance_right_turn,
            "advance_right_turn_relation_ids": list(arm.advance_right_turn_relation_ids),
            "advance_right_turn_target_arm_ids": list(arm.advance_right_turn_target_arm_ids),
            "original_trunk_road_ids": list(original),
            "corrected_trunk_road_ids": list(corrected_trunk),
            "trunk_correction_status": status,
            "trunk_correction_reason": reason,
        }
        corrected.append(
            CorrectedFinalArm(
                final_arm=payload,
                original_trunk_road_ids=original,
                corrected_trunk_road_ids=corrected_trunk,
                trunk_correction_status=status,
                trunk_correction_reason=reason,
            )
        )
    return tuple(corrections), tuple(corrected)


def build_movement_outputs(
    *,
    dataset: str,
    junction_id: str,
    roads: dict[str, RoadRecord],
    final_arms: tuple[FinalArm, ...],
    local_arm_candidates: tuple[LocalArmCandidate, ...],
    advance_right_turn_relations: tuple[AdvanceRightTurnRelation, ...],
    road_next_road_records: tuple[RawRoadNextRoad, ...],
    has_road_next_road_input: bool,
) -> MovementBuildResult:
    evidence, mapping_issues = _map_raw_evidence(
        dataset=dataset,
        junction_id=junction_id,
        raw_records=road_next_road_records,
        final_arms=final_arms,
    )
    arm_movements = _build_arm_movements(
        dataset=dataset,
        junction_id=junction_id,
        final_arms=final_arms,
        local_candidates=local_arm_candidates,
        roads=roads,
        evidence=evidence,
        advance_right_turn_relations=advance_right_turn_relations,
        has_road_next_road_input=has_road_next_road_input,
    )
    evidence_by_id = {item.evidence_id: item for item in evidence}
    roles = _receiving_roles(arm_movements=arm_movements, evidence_by_id=evidence_by_id)
    corrections, corrected_final_arms = _corrected_final_arms(
        final_arms=final_arms,
        roles=roles,
        roads=roads,
        has_road_next_road_input=has_road_next_road_input,
    )
    correction_counts = Counter(correction.trunk_correction_status for correction in corrections)
    corrected_trunk_counts = Counter(
        "none" if not correction.corrected_trunk_road_ids else "partial" for correction in corrections
    )
    metrics = {
        "arm_movement_count": len(arm_movements),
        "road_movement_evidence_count": len(evidence),
        "road_movement_mapped_count": sum(1 for item in evidence if item.mapping_status == "mapped"),
        "road_movement_unmapped_count": sum(1 for item in evidence if item.mapping_status != "mapped"),
        "straight_receiving_road_count": sum(1 for role in roles if role.straight_evidence_count > 0),
        "advance_left_receiving_road_count": sum(1 for role in roles if role.advance_left_evidence_count > 0),
        "trunk_correction_count": correction_counts.get("corrected", 0),
        "trunk_correction_excluded_road_count": sum(len(item.movement_excluded_receiving_road_ids) for item in corrections),
        "trunk_correction_straight_evidence_missing_count": correction_counts.get("straight_evidence_missing", 0),
        "corrected_trunk_complete_count": 0,
        "corrected_trunk_partial_count": corrected_trunk_counts.get("partial", 0),
        "corrected_trunk_none_count": corrected_trunk_counts.get("none", 0),
        "corrected_trunk_ambiguous_count": 0,
    }
    return MovementBuildResult(
        road_movement_evidence=evidence,
        arm_movements=arm_movements,
        arm_receiving_road_roles=roles,
        trunk_corrections=corrections,
        corrected_final_arms=corrected_final_arms,
        issues=mapping_issues,
        metrics=metrics,
    )
