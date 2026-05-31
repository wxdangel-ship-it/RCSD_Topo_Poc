from __future__ import annotations

from dataclasses import replace

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arrow_evidence import (
    evaluate_complete_arrow_exclusion,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.restriction_evidence import (
    match_restriction_evidence,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    ArrowInput,
    EvidenceProvenance,
    EvidenceType,
    InferenceLevel,
    MovementApplicability,
    ProhibitionReason,
    ProhibitionStatus,
    RestorationResult,
    RestrictionInput,
    RoadAttributes,
    T09ArmMovement,
    T09EvidenceItem,
    T09RestoredFieldRule,
    T09SwsdArm,
    to_jsonable,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.special_carrier import (
    detect_special_carrier_evidence,
)


def restore_field_rules(
    *,
    arms: tuple[T09SwsdArm, ...],
    movements: tuple[T09ArmMovement, ...],
    restrictions: tuple[RestrictionInput, ...] = tuple(),
    arrows: tuple[ArrowInput, ...] = tuple(),
    road_attributes: tuple[RoadAttributes, ...] = tuple(),
) -> RestorationResult:
    evidence_items: list[T09EvidenceItem] = []
    restored_rules: list[T09RestoredFieldRule] = []
    updated_movements: list[T09ArmMovement] = []

    attributes_by_road = {road.road_id: road for road in road_attributes}
    for arm in arms:
        arm_roads = tuple(
            attributes_by_road[road_id]
            for road_id in arm.seed_road_ids + arm.connector_road_ids + arm.trunk_road_ids
            if road_id in attributes_by_road
        )
        evidence_items.extend(
            detect_special_carrier_evidence(junction_id=arm.junction_id, arm_id=arm.arm_id, roads=arm_roads)
        )

    for movement in movements:
        if movement.movement_applicability != MovementApplicability.APPLICABLE or not movement.carrier_road_pairs:
            topology_evidence = _topology_not_applicable_evidence(movement)
            evidence_items.append(topology_evidence)
            updated_movements.append(
                replace(
                    movement,
                    prohibition_status=ProhibitionStatus.NOT_A_TRAFFIC_RULE,
                    prohibition_reason=ProhibitionReason.TOPOLOGY_NOT_APPLICABLE,
                    prohibition_confidence=1.0,
                    evidence_item_ids=(topology_evidence.evidence_id,),
                )
            )
            restored_rules.append(
                _rule_from_movement(
                    movement,
                    (topology_evidence,),
                    tuple(),
                    field_rule_status=ProhibitionStatus.NOT_A_TRAFFIC_RULE,
                )
            )
            continue

        restriction_result = match_restriction_evidence(movement, restrictions=restrictions)
        arrow_result = evaluate_complete_arrow_exclusion(movement, arrows=arrows) if arrows else None
        movement_evidence = list(restriction_result.evidence_items)
        conflicting_evidence: tuple[T09EvidenceItem, ...] = tuple()

        if restriction_result.evidence_items:
            if arrow_result:
                movement_evidence.extend(arrow_result.evidence_items)
                if arrow_result.arrow_supports_movement:
                    conflict = _conflict_evidence(movement, restriction_result.evidence_items, arrow_result.evidence_items)
                    movement_evidence.append(conflict)
                    conflicting_evidence = arrow_result.evidence_items + (conflict,)
            status = restriction_result.prohibition_status
            reason = restriction_result.prohibition_reason
            confidence = restriction_result.confidence
            supporting = restriction_result.evidence_items
        elif arrow_result and arrow_result.prohibition_status == ProhibitionStatus.FULLY_PROHIBITED:
            movement_evidence.extend(arrow_result.evidence_items)
            status = arrow_result.prohibition_status
            reason = arrow_result.prohibition_reason
            confidence = arrow_result.confidence
            supporting = arrow_result.evidence_items
        else:
            if arrow_result:
                movement_evidence.extend(arrow_result.evidence_items)
            status = ProhibitionStatus.NO_PROHIBITION_EVIDENCE
            reason = ProhibitionReason.INSUFFICIENT_EVIDENCE
            confidence = 0.0
            supporting = tuple()

        evidence_items.extend(movement_evidence)
        updated_movements.append(
            replace(
                movement,
                prohibition_status=status,
                prohibition_reason=reason,
                prohibition_confidence=confidence,
                evidence_item_ids=tuple(item.evidence_id for item in movement_evidence),
            )
        )
        if supporting:
            restored_rules.append(
                _rule_from_movement(
                    movement,
                    supporting,
                    conflicting_evidence,
                    field_rule_status=status,
                )
            )

    summary = {
        "stage": "t09_swsd_field_rule_restoration_minimal",
        "input_counts": {
            "arms": len(arms),
            "movements": len(movements),
            "restrictions": len(restrictions),
            "arrows": len(arrows),
            "road_attributes": len(road_attributes),
        },
        "output_counts": {
            "evidence_items": len(evidence_items),
            "restored_rules": len(restored_rules),
        },
        "qa": {
            "crs_transform_executed": False,
            "crs_note": "minimal object-level implementation; no GIS projection was executed",
            "topology_silent_fix": False,
            "performance_counter_scope": "object counts only",
        },
    }
    return RestorationResult(
        arms=arms,
        movements=tuple(updated_movements),
        evidence_items=tuple(evidence_items),
        restored_rules=tuple(restored_rules),
        summary=to_jsonable(summary),
    )


def _topology_not_applicable_evidence(movement: T09ArmMovement) -> T09EvidenceItem:
    return T09EvidenceItem(
        evidence_id=f"topology:{movement.movement_id}",
        evidence_type=EvidenceType.TOPOLOGY_NOT_APPLICABLE,
        junction_id=movement.junction_id,
        movement_id=movement.movement_id,
        road_pair=None,
        evidence_status="topology_not_applicable",
        prohibition_reason=ProhibitionReason.TOPOLOGY_NOT_APPLICABLE,
        inference_level=InferenceLevel.EXPLICIT,
        confidence=1.0,
        provenance=EvidenceProvenance(
            source_type="carrier_universe",
            source_id=movement.movement_id,
            matched_object_ids=(movement.from_arm_id, movement.to_arm_id),
            match_method="candidate_road_pair_count",
            reason="empty or non-applicable carrier universe is not a traffic prohibition",
        ),
        supports_prohibition=False,
    )


def _conflict_evidence(
    movement: T09ArmMovement,
    restriction_items: tuple[T09EvidenceItem, ...],
    arrow_items: tuple[T09EvidenceItem, ...],
) -> T09EvidenceItem:
    return T09EvidenceItem(
        evidence_id=f"conflict:{movement.movement_id}",
        evidence_type=EvidenceType.CONFLICT,
        junction_id=movement.junction_id,
        movement_id=movement.movement_id,
        road_pair=None,
        evidence_status="restriction_arrow_conflict_restriction_priority",
        prohibition_reason=ProhibitionReason.CONFLICTING_EVIDENCE,
        inference_level=InferenceLevel.CONFLICT,
        confidence=0.5,
        provenance=EvidenceProvenance(
            source_type="restriction_arrow_conflict",
            source_id=movement.movement_id,
            matched_object_ids=tuple(item.evidence_id for item in restriction_items + arrow_items),
            match_method="evidence_priority",
            reason="restriction evidence has priority over arrow support evidence",
        ),
        supports_prohibition=False,
        risk_flags=("restriction_arrow_conflict",),
    )


def _rule_from_movement(
    movement: T09ArmMovement,
    supporting: tuple[T09EvidenceItem, ...],
    conflicting: tuple[T09EvidenceItem, ...],
    *,
    field_rule_status: ProhibitionStatus | None = None,
) -> T09RestoredFieldRule:
    return T09RestoredFieldRule(
        junction_id=movement.junction_id,
        from_arm_id=movement.from_arm_id,
        to_arm_id=movement.to_arm_id,
        movement_type=movement.movement_type,
        field_rule_status=field_rule_status or _status_from_evidence(supporting),
        rule_scope="movement",
        supporting_evidence_ids=tuple(item.evidence_id for item in supporting),
        conflicting_evidence_ids=tuple(item.evidence_id for item in conflicting),
        inference_level=_inference_from_evidence(supporting, conflicting),
        confidence=max((item.confidence for item in supporting), default=0.0),
        risk_flags=tuple(sorted({flag for item in supporting + conflicting for flag in item.risk_flags})),
    )


def _status_from_evidence(evidence_items: tuple[T09EvidenceItem, ...]) -> ProhibitionStatus:
    if any(item.evidence_type == EvidenceType.TOPOLOGY_NOT_APPLICABLE for item in evidence_items):
        return ProhibitionStatus.NOT_A_TRAFFIC_RULE
    if any(item.evidence_type == EvidenceType.RESTRICTION for item in evidence_items):
        road_pair_count = len({item.road_pair for item in evidence_items if item.road_pair is not None})
        return ProhibitionStatus.FULLY_PROHIBITED if road_pair_count > 1 else ProhibitionStatus.PARTIALLY_PROHIBITED
    if any(item.evidence_type == EvidenceType.COMPLETE_ARROW_EXCLUSION for item in evidence_items):
        return ProhibitionStatus.FULLY_PROHIBITED
    return ProhibitionStatus.UNKNOWN


def _inference_from_evidence(
    supporting: tuple[T09EvidenceItem, ...],
    conflicting: tuple[T09EvidenceItem, ...],
) -> InferenceLevel:
    if conflicting:
        return InferenceLevel.CONFLICT
    if any(item.inference_level == InferenceLevel.EXPLICIT for item in supporting):
        return InferenceLevel.EXPLICIT
    if any(item.inference_level == InferenceLevel.DERIVED for item in supporting):
        return InferenceLevel.DERIVED
    return InferenceLevel.UNKNOWN
