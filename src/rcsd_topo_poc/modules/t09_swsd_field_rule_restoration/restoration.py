from __future__ import annotations

from dataclasses import replace

from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arrow_evidence import (
    evaluate_complete_arrow_exclusion,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.geometry_match import MAX_GEOMETRY_MATCH_DISTANCE_M
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
    SWSDRoadInput,
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
    roads: tuple[SWSDRoadInput, ...] = tuple(),
    road_geometries: dict[str, BaseGeometry] | None = None,
) -> RestorationResult:
    evidence_items: list[T09EvidenceItem] = []
    restored_rules: list[T09RestoredFieldRule] = []
    updated_movements: list[T09ArmMovement] = []

    attributes_by_road = {road.road_id: road for road in road_attributes}
    roads_by_id = {road.road_id: road for road in roads}
    arms_by_id = {arm.arm_id: arm for arm in arms}
    road_geometries = road_geometries or {}
    restrictions_by_pair = _restrictions_by_pair(restrictions)
    restriction_geometry_index = _GeometryCandidateIndex(restrictions)
    arrows_by_road_id = _arrows_by_road_id(arrows)
    arrow_geometry_index = _GeometryCandidateIndex(arrows)
    arrow_candidates_by_road_cache: dict[str, tuple[ArrowInput, ...]] = {}
    special_status_by_arm: dict[str, set[str]] = {}
    for arm in arms:
        arm_roads = tuple(
            attributes_by_road[road_id]
            for road_id in arm.seed_road_ids + arm.connector_road_ids + arm.trunk_road_ids
            if road_id in attributes_by_road
        )
        special_items = detect_special_carrier_evidence(junction_id=arm.junction_id, arm_id=arm.arm_id, roads=arm_roads)
        evidence_items.extend(special_items)
        for item in special_items:
            special_status_by_arm.setdefault(arm.arm_id, set()).add(item.evidence_status)

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
                    restriction_coverage="not_applicable",
                    partial_basis="not_applicable",
                    remaining_restriction_status="not_applicable",
                    arrow_direction_status="not_applicable",
                    arrow_lane_summary=_empty_arrow_lane_summary(),
                    advance_left_status="not_applicable",
                    advance_right_status="not_applicable",
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

        restriction_result = match_restriction_evidence(
            movement,
            restrictions=_candidate_restrictions_for_movement(
                movement,
                restrictions_by_pair=restrictions_by_pair,
                geometry_index=restriction_geometry_index,
                road_geometries=road_geometries,
            ),
            roads_by_id=roads_by_id,
            road_geometries=road_geometries,
            arms_by_id=arms_by_id,
        )
        arrow_result = (
            evaluate_complete_arrow_exclusion(
                movement,
                arrows=_candidate_arrows_for_movement(
                    movement,
                    arrows_by_road_id=arrows_by_road_id,
                    geometry_index=arrow_geometry_index,
                    road_geometries=road_geometries,
                    candidates_by_road_cache=arrow_candidates_by_road_cache,
                ),
                roads_by_id=roads_by_id,
                road_geometries=road_geometries,
                arms_by_id=arms_by_id,
            )
            if arrows
            else None
        )
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
        else:
            if arrow_result:
                movement_evidence.extend(arrow_result.evidence_items)
            status = ProhibitionStatus.NO_PROHIBITION_EVIDENCE
            reason = ProhibitionReason.INSUFFICIENT_EVIDENCE
            confidence = 0.0
            supporting = tuple()

        evidence_items.extend(movement_evidence)
        from_arm = arms_by_id.get(movement.from_arm_id)
        arrow_direction_status = arrow_result.arrow_direction_status if arrow_result else "no_arrow_evidence"
        arrow_lane_summary = arrow_result.arrow_lane_summary if arrow_result else _empty_arrow_lane_summary()
        updated_movements.append(
            replace(
                movement,
                prohibition_status=status,
                prohibition_reason=reason,
                prohibition_confidence=confidence,
                restriction_coverage=restriction_result.restriction_coverage,
                partial_basis=restriction_result.partial_basis,
                remaining_restriction_status=restriction_result.remaining_restriction_status,
                arrow_direction_status=arrow_direction_status,
                arrow_lane_summary=arrow_lane_summary,
                advance_left_status=_advance_left_status(movement, from_arm, special_status_by_arm),
                advance_right_status=_advance_right_status(movement, from_arm, special_status_by_arm),
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
            "roads": len(roads),
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
        "business_policy": {
            "prohibition_source": "restriction_only",
            "arrow_role": "evidence_and_conflict_signal_only",
        },
    }
    return RestorationResult(
        arms=arms,
        movements=tuple(updated_movements),
        evidence_items=tuple(evidence_items),
        restored_rules=tuple(restored_rules),
        summary=to_jsonable(summary),
    )


class _GeometryCandidateIndex:
    def __init__(self, items: tuple[RestrictionInput, ...] | tuple[ArrowInput, ...]) -> None:
        self._items = tuple(item for item in items if item.geometry is not None)
        self._geometries = tuple(item.geometry for item in self._items)
        self._tree = STRtree(self._geometries) if self._geometries else None
        self._geometry_id_to_index = {id(geometry): index for index, geometry in enumerate(self._geometries)}

    def query(self, geometry: BaseGeometry | None) -> tuple[RestrictionInput, ...] | tuple[ArrowInput, ...]:
        if self._tree is None or geometry is None or geometry.is_empty:
            return tuple()
        query_geometry = geometry.buffer(MAX_GEOMETRY_MATCH_DISTANCE_M).envelope
        results = self._tree.query(query_geometry)
        candidates = []
        for result in results:
            if hasattr(result, "__index__"):
                index = int(result)
            else:
                index = self._geometry_id_to_index.get(id(result))
                if index is None:
                    continue
            candidates.append(self._items[index])
        return tuple(candidates)


def _restrictions_by_pair(restrictions: tuple[RestrictionInput, ...]) -> dict[tuple[str, str], tuple[RestrictionInput, ...]]:
    indexed: dict[tuple[str, str], list[RestrictionInput]] = {}
    for restriction in restrictions:
        indexed.setdefault((restriction.in_link_id, restriction.out_link_id), []).append(restriction)
    return {key: tuple(value) for key, value in indexed.items()}


def _arrows_by_road_id(arrows: tuple[ArrowInput, ...]) -> dict[str, tuple[ArrowInput, ...]]:
    indexed: dict[str, list[ArrowInput]] = {}
    for arrow in arrows:
        indexed.setdefault(arrow.road_id, []).append(arrow)
    return {key: tuple(value) for key, value in indexed.items()}


def _candidate_restrictions_for_movement(
    movement: T09ArmMovement,
    *,
    restrictions_by_pair: dict[tuple[str, str], tuple[RestrictionInput, ...]],
    geometry_index: _GeometryCandidateIndex,
    road_geometries: dict[str, BaseGeometry],
) -> tuple[RestrictionInput, ...]:
    candidates: dict[tuple[str, str, str], RestrictionInput] = {}
    candidate_road_ids: set[str] = set()
    for pair in movement.carrier_road_pairs:
        candidate_road_ids.add(pair.from_road_id)
        candidate_road_ids.add(pair.to_road_id)
        for restriction in restrictions_by_pair.get((pair.from_road_id, pair.to_road_id), tuple()):
            candidates.setdefault(_restriction_candidate_key(restriction), restriction)
    for road_id in candidate_road_ids:
        for restriction in geometry_index.query(road_geometries.get(road_id)):
            candidates.setdefault(_restriction_candidate_key(restriction), restriction)
    return tuple(candidates.values())


def _restriction_candidate_key(restriction: RestrictionInput) -> tuple[str, str, str]:
    return (restriction.restriction_id, restriction.in_link_id, restriction.out_link_id)


def _candidate_arrows_for_movement(
    movement: T09ArmMovement,
    *,
    arrows_by_road_id: dict[str, tuple[ArrowInput, ...]],
    geometry_index: _GeometryCandidateIndex,
    road_geometries: dict[str, BaseGeometry],
    candidates_by_road_cache: dict[str, tuple[ArrowInput, ...]],
) -> tuple[ArrowInput, ...]:
    candidates: dict[str, ArrowInput] = {}
    approach_road_ids = {pair.from_road_id for pair in movement.carrier_road_pairs}
    for road_id in approach_road_ids:
        if road_id not in candidates_by_road_cache:
            road_candidates: dict[str, ArrowInput] = {
                arrow.arrow_id: arrow for arrow in arrows_by_road_id.get(road_id, tuple())
            }
            for arrow in geometry_index.query(road_geometries.get(road_id)):
                road_candidates.setdefault(arrow.arrow_id, arrow)
            candidates_by_road_cache[road_id] = tuple(road_candidates.values())
        for arrow in candidates_by_road_cache[road_id]:
            candidates.setdefault(arrow.arrow_id, arrow)
    return tuple(candidates.values())


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


def _empty_arrow_lane_summary() -> dict[str, object]:
    return {
        "matched_approach_road_count": 0,
        "matched_arrow_count": 0,
        "lane_count": 0,
        "supporting_lane_count": 0,
        "excluding_lane_count": 0,
        "empty_lane_count": 0,
        "uninvestigated_lane_count": 0,
        "unknown_code_count": 0,
        "direction_mismatch_count": 0,
        "incomplete_sequence_count": 0,
        "movement_type_supported": False,
        "matched_arrow_ids": tuple(),
        "raw_arrow_sequences": tuple(),
    }


def _advance_left_status(
    movement: T09ArmMovement,
    from_arm: T09SwsdArm | None,
    special_status_by_arm: dict[str, set[str]],
) -> str:
    if movement.movement_type.strip().lower() not in {"left", "slight_left"}:
        return "not_applicable"
    statuses = special_status_by_arm.get(movement.from_arm_id, set())
    if "advance_left_carrier_exists" in statuses:
        return "present"
    if from_arm is not None and from_arm.advance_left_road_ids:
        return "present"
    return "no_advance_left_evidence"


def _advance_right_status(
    movement: T09ArmMovement,
    from_arm: T09SwsdArm | None,
    special_status_by_arm: dict[str, set[str]],
) -> str:
    if movement.movement_type.strip().lower() not in {"right", "slight_right"}:
        return "not_applicable"
    statuses = special_status_by_arm.get(movement.from_arm_id, set())
    if "auxiliary_right_turn_carrier_exists" in statuses:
        return "present_bypass_core_junction"
    if from_arm is not None and from_arm.auxiliary_right_turn_road_ids:
        return "present_bypass_core_junction"
    if "pre_junction_non_aux_advance_right_relation" in statuses:
        return "present_through_core_junction"
    if from_arm is not None and from_arm.advance_right_turn_relation_ids:
        return "present_through_core_junction"
    return "no_advance_right_evidence"


def _status_from_evidence(evidence_items: tuple[T09EvidenceItem, ...]) -> ProhibitionStatus:
    if any(item.evidence_type == EvidenceType.TOPOLOGY_NOT_APPLICABLE for item in evidence_items):
        return ProhibitionStatus.NOT_A_TRAFFIC_RULE
    if any(item.evidence_type == EvidenceType.RESTRICTION for item in evidence_items):
        road_pair_count = len({item.road_pair for item in evidence_items if item.road_pair is not None})
        return ProhibitionStatus.FULLY_PROHIBITED if road_pair_count > 1 else ProhibitionStatus.PARTIALLY_PROHIBITED
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
