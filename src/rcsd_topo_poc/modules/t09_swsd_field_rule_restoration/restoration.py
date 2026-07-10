from __future__ import annotations

from collections import Counter
from dataclasses import replace

from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arrow_evidence import (
    RoadArrowDecision,
    evaluate_complete_arrow_exclusion,
    evaluate_road_arrow_directions,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.decision import (
    resolve_multi_evidence_movement,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.geometry_match import MAX_GEOMETRY_MATCH_DISTANCE_M
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.restriction_evidence import (
    RestrictionMatchResult,
    audit_cross_movement_geometry_fanout,
    match_restriction_evidence,
    restriction_condition_identity,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    ArrowInput,
    DecisionSource,
    DecisionStatus,
    EvidencePriority,
    EvidenceProvenance,
    EvidenceType,
    InferenceLevel,
    MovementApplicability,
    ProhibitionReason,
    ProhibitionStatus,
    RestorationResult,
    RestorationStrategy,
    RestrictionInput,
    RoadAttributes,
    RuleScope,
    SWSDRoadInput,
    T09ArmMovement,
    T09EvidenceItem,
    T09RestoredFieldRule,
    T09SwsdArm,
    VerificationStatus,
    normalize_restoration_strategy,
    to_jsonable,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.special_carrier import (
    SpecialCarrierArmProfile,
    build_special_carrier_arm_profile,
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
    strategy_version: str | RestorationStrategy = RestorationStrategy.RESTRICTION_ONLY_V1,
) -> RestorationResult:
    strategy = normalize_restoration_strategy(strategy_version)
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
    special_profiles_by_arm: dict[str, SpecialCarrierArmProfile] = {}
    for arm in arms:
        profile_road_ids = (
            arm.seed_road_ids + arm.connector_road_ids + arm.trunk_road_ids
            if strategy == RestorationStrategy.RESTRICTION_ONLY_V1
            else _v2_restore_profile_road_ids(arm)
        )
        arm_roads = tuple(
            attributes_by_road[road_id]
            for road_id in profile_road_ids
            if road_id in attributes_by_road
        )
        if strategy == RestorationStrategy.RESTRICTION_ONLY_V1:
            special_items = detect_special_carrier_evidence(
                junction_id=arm.junction_id,
                arm_id=arm.arm_id,
                roads=arm_roads,
            )
            evidence_items.extend(special_items)
            for item in special_items:
                special_status_by_arm.setdefault(arm.arm_id, set()).add(item.evidence_status)
        else:
            special_profiles_by_arm[arm.arm_id] = build_special_carrier_arm_profile(
                arm=arm,
                roads=arm_roads,
            )

    v2_restriction_results: dict[str, RestrictionMatchResult] = {}
    if strategy == RestorationStrategy.MULTI_EVIDENCE_V2:
        raw_results = tuple(
            (
                movement,
                match_restriction_evidence(
                    movement,
                    restrictions=_candidate_restrictions_for_movement(
                        movement,
                        restrictions_by_pair=restrictions_by_pair,
                        geometry_index=restriction_geometry_index,
                        road_geometries=road_geometries,
                        strategy=strategy,
                    ),
                    roads_by_id=roads_by_id,
                    road_geometries=road_geometries,
                    arms_by_id=arms_by_id,
                    strategy_version=strategy,
                ),
            )
            for movement in movements
            if movement.movement_applicability == MovementApplicability.APPLICABLE
            and movement.carrier_road_pairs
        )
        v2_restriction_results = audit_cross_movement_geometry_fanout(
            raw_results,
            arms_by_id=arms_by_id,
        )

    for movement in movements:
        if movement.movement_applicability != MovementApplicability.APPLICABLE or not movement.carrier_road_pairs:
            topology_evidence = _topology_not_applicable_evidence(movement)
            if strategy == RestorationStrategy.MULTI_EVIDENCE_V2:
                topology_evidence = replace(
                    topology_evidence,
                    decision_status=DecisionStatus.NOT_APPLICABLE,
                    decision_scope=RuleScope.ARM_TO_ARM,
                    verification_status=VerificationStatus.NOT_REQUIRED,
                )
            evidence_items.append(topology_evidence)
            updated_movement = replace(
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
            if strategy == RestorationStrategy.MULTI_EVIDENCE_V2:
                updated_movement = replace(
                    updated_movement,
                    strategy_version=strategy,
                    decision_status=DecisionStatus.NOT_APPLICABLE,
                    decision_source=DecisionSource.TOPOLOGY,
                    decision_scope=RuleScope.ARM_TO_ARM,
                    verification_status=VerificationStatus.NOT_REQUIRED,
                )
            updated_movements.append(updated_movement)
            topology_rule = _rule_from_movement(
                movement,
                (topology_evidence,),
                tuple(),
                field_rule_status=ProhibitionStatus.NOT_A_TRAFFIC_RULE,
            )
            if strategy == RestorationStrategy.MULTI_EVIDENCE_V2:
                topology_rule = replace(
                    topology_rule,
                    rule_id=f"{movement.movement_id}:rule:topology:not_applicable",
                    movement_id=movement.movement_id,
                    strategy_version=strategy,
                    decision_status=DecisionStatus.NOT_APPLICABLE,
                    decision_source=DecisionSource.TOPOLOGY,
                    decision_scope=RuleScope.ARM_TO_ARM,
                    verification_status=VerificationStatus.NOT_REQUIRED,
                )
            restored_rules.append(topology_rule)
            continue

        restriction_result = (
            v2_restriction_results[movement.movement_id]
            if strategy == RestorationStrategy.MULTI_EVIDENCE_V2
            else match_restriction_evidence(
                movement,
                restrictions=_candidate_restrictions_for_movement(
                    movement,
                    restrictions_by_pair=restrictions_by_pair,
                    geometry_index=restriction_geometry_index,
                    road_geometries=road_geometries,
                    strategy=strategy,
                ),
                roads_by_id=roads_by_id,
                road_geometries=road_geometries,
                arms_by_id=arms_by_id,
                strategy_version=strategy,
            )
        )
        movement_arrow_candidates = _candidate_arrows_for_movement(
            movement,
            arrows_by_road_id=arrows_by_road_id,
            geometry_index=arrow_geometry_index,
            road_geometries=road_geometries,
            candidates_by_road_cache=arrow_candidates_by_road_cache,
        )
        if strategy == RestorationStrategy.MULTI_EVIDENCE_V2:
            road_arrow_decisions = evaluate_road_arrow_directions(
                movement,
                arrows=movement_arrow_candidates,
                roads_by_id=roads_by_id,
                road_geometries=road_geometries,
                arms_by_id=arms_by_id,
            )
            decision_result = resolve_multi_evidence_movement(
                movement=movement,
                restriction_result=restriction_result,
                road_arrow_decisions=road_arrow_decisions,
                special_profile=special_profiles_by_arm.get(movement.from_arm_id),
            )
            evidence_items.extend(decision_result.evidence_items)
            restored_rules.extend(decision_result.restored_rules)
            updated_movements.append(
                _with_v2_arrow_and_special_audit(
                    movement=decision_result.movement,
                    road_arrow_decisions=road_arrow_decisions,
                    from_arm=arms_by_id.get(movement.from_arm_id),
                    special_profile=special_profiles_by_arm.get(movement.from_arm_id),
                )
            )
            continue

        arrow_result = (
            evaluate_complete_arrow_exclusion(
                movement,
                arrows=movement_arrow_candidates,
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
        "strategy_version": strategy.value,
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
            "prohibition_source": (
                "restriction_only"
                if strategy == RestorationStrategy.RESTRICTION_ONLY_V1
                else "restriction_laneinfo_special_carrier_priority"
            ),
            "arrow_role": (
                "evidence_and_conflict_signal_only"
                if strategy == RestorationStrategy.RESTRICTION_ONLY_V1
                else "road_scoped_direction_decision"
            ),
            "evidence_priority": (
                "restriction > laneinfo > special_carrier"
                if strategy == RestorationStrategy.MULTI_EVIDENCE_V2
                else "restriction_only"
            ),
        },
    }
    summary["decision_counts"] = _decision_counts(
        movements=tuple(updated_movements),
        evidence=tuple(evidence_items),
        rules=tuple(restored_rules),
    )
    summary.update(
        _operational_counts(
            arms=arms,
            movements=tuple(updated_movements),
            evidence=tuple(evidence_items),
            rules=tuple(restored_rules),
            restrictions=restrictions,
            arrows=arrows,
            strategy=strategy,
        )
    )
    return RestorationResult(
        arms=arms,
        movements=tuple(updated_movements),
        evidence_items=tuple(evidence_items),
        restored_rules=tuple(restored_rules),
        summary=to_jsonable(summary),
    )


def _v2_restore_profile_road_ids(arm: T09SwsdArm) -> tuple[str, ...]:
    """Return every formal Arm road role once for v2 evidence profiling."""

    road_ids = {
        road_id
        for role_road_ids in (
            arm.internal_road_ids,
            arm.seed_road_ids,
            arm.connector_road_ids,
            arm.inbound_road_ids,
            arm.outbound_road_ids,
            arm.bidirectional_road_ids,
            arm.approach_road_ids,
            arm.exit_road_ids,
            arm.trunk_road_ids,
            arm.parallel_branch_road_ids,
            arm.advance_left_road_ids,
            arm.advance_right_road_ids,
            arm.auxiliary_right_turn_road_ids,
        )
        for road_id in role_road_ids
    }
    return tuple(sorted(road_ids, key=_road_id_sort_key))


def _road_id_sort_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if value.isdigit() else (1, value)


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
    strategy: RestorationStrategy,
) -> tuple[RestrictionInput, ...]:
    candidates: dict[tuple[str, str, str, str], RestrictionInput] = {}
    candidate_road_ids: set[str] = set()
    for pair in movement.carrier_road_pairs:
        candidate_road_ids.add(pair.from_road_id)
        candidate_road_ids.add(pair.to_road_id)
        for restriction in restrictions_by_pair.get((pair.from_road_id, pair.to_road_id), tuple()):
            candidates.setdefault(_restriction_candidate_key(restriction, strategy=strategy), restriction)
    for road_id in candidate_road_ids:
        for restriction in geometry_index.query(road_geometries.get(road_id)):
            candidates.setdefault(_restriction_candidate_key(restriction, strategy=strategy), restriction)
    return tuple(candidates.values())


def _restriction_candidate_key(
    restriction: RestrictionInput,
    *,
    strategy: RestorationStrategy,
) -> tuple[str, str, str, str]:
    condition_identity = (
        restriction.condition_identity or restriction_condition_identity(restriction)
        if strategy == RestorationStrategy.MULTI_EVIDENCE_V2
        else ""
    )
    return (
        restriction.restriction_id,
        restriction.in_link_id,
        restriction.out_link_id,
        condition_identity,
    )


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


def _with_v2_arrow_and_special_audit(
    *,
    movement: T09ArmMovement,
    road_arrow_decisions: tuple[RoadArrowDecision, ...],
    from_arm: T09SwsdArm | None,
    special_profile: SpecialCarrierArmProfile | None,
) -> T09ArmMovement:
    statuses = {item.decision_status for item in road_arrow_decisions}
    if not road_arrow_decisions:
        direction_status = "no_approach_road"
    elif statuses == {DecisionStatus.SUPPORTED}:
        direction_status = "road_laneinfo_supports_movement"
    elif statuses == {DecisionStatus.PROHIBITED}:
        direction_status = "road_laneinfo_excludes_movement"
    elif DecisionStatus.UNKNOWN in statuses:
        direction_status = "road_laneinfo_unknown_or_incomplete"
    else:
        direction_status = "mixed_road_laneinfo_decisions"
    lane_summary = {
        "road_decision_count": len(road_arrow_decisions),
        "road_decision_status_counts": dict(
            sorted(Counter(item.decision_status.value for item in road_arrow_decisions).items())
        ),
        "matched_arrow_count": sum(len(item.source_arrow_ids) for item in road_arrow_decisions),
        "road_decisions": tuple(
            {
                "road_id": item.road_id,
                "decision_status": item.decision_status.value,
                "direction_tokens": item.direction_tokens,
                "source_arrow_ids": item.source_arrow_ids,
                "risk_flags": item.risk_flags,
                "reason": item.reason,
                "lane_summary": item.lane_summary,
            }
            for item in road_arrow_decisions
        ),
    }
    return replace(
        movement,
        arrow_direction_status=direction_status,
        arrow_lane_summary=lane_summary,
        advance_left_status=_v2_advance_status(
            movement=movement,
            from_arm=from_arm,
            special_profile=special_profile,
            direction="left",
        ),
        advance_right_status=_v2_advance_status(
            movement=movement,
            from_arm=from_arm,
            special_profile=special_profile,
            direction="right",
        ),
    )


def _v2_advance_status(
    *,
    movement: T09ArmMovement,
    from_arm: T09SwsdArm | None,
    special_profile: SpecialCarrierArmProfile | None,
    direction: str,
) -> str:
    applicable_types = {"left", "slight_left"} if direction == "left" else {"right", "slight_right"}
    if movement.movement_type.strip().lower() not in applicable_types:
        return "not_applicable"
    profile_ids = (
        special_profile.advance_left_road_ids
        if special_profile is not None and direction == "left"
        else (
            special_profile.advance_right_road_ids
            if special_profile is not None
            else tuple()
        )
    )
    if profile_ids:
        return "present_formway_special_carrier"
    arm_ids = (
        from_arm.advance_left_road_ids
        if from_arm is not None and direction == "left"
        else (
            from_arm.advance_right_road_ids
            if from_arm is not None
            else tuple()
        )
    )
    return "present" if arm_ids else f"no_advance_{direction}_evidence"


def _decision_counts(
    *,
    movements: tuple[T09ArmMovement, ...],
    evidence: tuple[T09EvidenceItem, ...],
    rules: tuple[T09RestoredFieldRule, ...],
) -> dict[str, object]:
    movement_status = _enum_counter(movements, "decision_status")
    rule_status = _enum_counter(rules, "decision_status")
    evidence_status = _enum_counter(evidence, "decision_status")
    movement_scope = _enum_counter(movements, "decision_scope")
    rule_scope = _enum_counter(rules, "decision_scope")
    evidence_scope = _enum_counter(evidence, "decision_scope")
    movement_priority = _enum_counter(movements, "evidence_priority")
    rule_priority = _enum_counter(rules, "evidence_priority")
    evidence_priority = _enum_counter(evidence, "evidence_priority")
    movement_verification = _enum_counter(movements, "verification_status")
    rule_verification = _enum_counter(rules, "verification_status")
    evidence_verification = _enum_counter(evidence, "verification_status")
    condition_identities = tuple(
        item.condition_identity
        for item in evidence + rules
        if item.condition_identity
    )
    promotion_status = dict(
        sorted(Counter(item.scope_promotion_status for item in rules).items())
    )
    promotion_allowed = sum(
        bool(item.scope_promotion_audit.get("promotion_allowed"))
        for item in rules
    )
    override_entry_count = sum(len(item.override_chain) for item in rules)
    conflicting_reference_count = sum(len(item.conflicting_evidence_ids) for item in rules)
    return {
        "movement_status": movement_status,
        "movement_source": _enum_counter(movements, "decision_source"),
        "rule_status": rule_status,
        "rule_source": _enum_counter(rules, "decision_source"),
        "rule_scope": rule_scope,
        "verification_status": rule_verification,
        "override_count": override_entry_count,
        "decision_status_counts": {
            "movement": movement_status,
            "evidence": evidence_status,
            "rule": rule_status,
        },
        "rule_scope_counts": {
            "movement": movement_scope,
            "evidence": evidence_scope,
            "rule": rule_scope,
        },
        "evidence_priority_counts": {
            "movement": movement_priority,
            "evidence": evidence_priority,
            "rule": rule_priority,
        },
        "verification_status_counts": {
            "movement": movement_verification,
            "evidence": evidence_verification,
            "rule": rule_verification,
        },
        "condition_counts": {
            "evidence_with_condition_identity": sum(bool(item.condition_identity) for item in evidence),
            "rules_with_condition_identity": sum(bool(item.condition_identity) for item in rules),
            "unique_condition_identity_count": len(set(condition_identities)),
            "condition_type_counts": dict(
                sorted(
                    Counter(
                        str(item.condition_type)
                        for item in evidence + rules
                        if item.condition_type is not None
                    ).items()
                )
            ),
            "condition_semantics_status_counts": dict(
                sorted(
                    Counter(
                        item.condition_semantics_status
                        for item in evidence + rules
                        if item.condition_semantics_status
                    ).items()
                )
            ),
        },
        "scope_promotion_counts": {
            "status_counts": promotion_status,
            "promotion_allowed_rule_count": promotion_allowed,
            "manual_review_rule_count": promotion_status.get("manual_review_required", 0),
            "unexplained_carrier_count": sum(
                int(item.scope_promotion_audit.get("unexplained_carrier_count", 0) or 0)
                for item in rules
            ),
        },
        "conflict_counts": {
            "movement_decision_conflict": movement_status.get(DecisionStatus.CONFLICT.value, 0),
            "evidence_type_conflict": sum(item.evidence_type == EvidenceType.CONFLICT for item in evidence),
            "rule_decision_conflict": rule_status.get(DecisionStatus.CONFLICT.value, 0),
            "rules_with_conflicting_evidence": sum(bool(item.conflicting_evidence_ids) for item in rules),
            "conflicting_evidence_reference_count": conflicting_reference_count,
        },
        "override_counts": {
            "rules_with_override": sum(bool(item.override_chain) for item in rules),
            "override_entry_count": override_entry_count,
        },
    }


def _operational_counts(
    *,
    arms: tuple[T09SwsdArm, ...],
    movements: tuple[T09ArmMovement, ...],
    evidence: tuple[T09EvidenceItem, ...],
    rules: tuple[T09RestoredFieldRule, ...],
    restrictions: tuple[RestrictionInput, ...],
    arrows: tuple[ArrowInput, ...],
    strategy: RestorationStrategy,
) -> dict[str, object]:
    item_groups: tuple[tuple[str, tuple[object, ...]], ...] = (
        ("arms", arms),
        ("movements", movements),
        ("evidence", evidence),
        ("rules", rules),
    )
    combined_risks: Counter[str] = Counter()
    risk_flag_counts: dict[str, dict[str, int]] = {}
    for group_name, items in item_groups:
        counts = Counter(
            flag
            for item in items
            for flag in getattr(item, "risk_flags", tuple())
        )
        combined_risks.update(counts)
        risk_flag_counts[group_name] = dict(sorted(counts.items()))
    risk_flag_counts["combined"] = dict(sorted(combined_risks.items()))
    restriction_input_identities = {
        _restriction_input_identity(item, strategy=strategy)
        for item in restrictions
    }
    matched_restriction_identities = {
        _restriction_evidence_input_identity(item, strategy=strategy)
        for item in evidence
        if item.evidence_type == EvidenceType.RESTRICTION
    }
    matched_restriction_identities.discard(None)
    unmatched_restriction_count = len(
        restriction_input_identities - matched_restriction_identities
    )
    arrow_ids = {item.arrow_id for item in arrows}
    referenced_object_ids = {
        str(object_id)
        for item in evidence
        for object_id in item.provenance.matched_object_ids
    }
    referenced_arrow_count = len(arrow_ids & referenced_object_ids)
    unreferenced_arrow_count = len(arrow_ids) - referenced_arrow_count
    skipped_counts = {
        key: value
        for key, value in (
            ("restriction_input_unmatched", unmatched_restriction_count),
            ("laneinfo_input_unreferenced", unreferenced_arrow_count),
        )
        if value
    }

    return {
        "risk_flag_counts": risk_flag_counts,
        "input_usage_counts": {
            "restriction_input_row_count": len(restrictions),
            "restriction_input_identity_count": len(restriction_input_identities),
            "restriction_matched_identity_count": len(
                restriction_input_identities & matched_restriction_identities
            ),
            "restriction_unmatched_identity_count": unmatched_restriction_count,
            "laneinfo_input_row_count": len(arrows),
            "laneinfo_referenced_row_count": referenced_arrow_count,
            "laneinfo_unreferenced_row_count": unreferenced_arrow_count,
        },
        "skipped_counts": dict(sorted(skipped_counts.items())),
        "skipped_reason_counts": dict(sorted(skipped_counts.items())),
        "outcome_reason_counts": {
            "arm_build_status": _field_counter(arms, "build_status"),
            "movement_applicability": _field_counter(
                movements,
                "movement_applicability",
            ),
            "movement_carrier_universe_status": _field_counter(
                movements,
                "carrier_universe_status",
            ),
            "movement_prohibition_reason": _field_counter(
                movements,
                "prohibition_reason",
            ),
            "movement_prohibition_status": _field_counter(
                movements,
                "prohibition_status",
            ),
            "evidence_prohibition_reason": _field_counter(
                evidence,
                "prohibition_reason",
            ),
            "evidence_status": _field_counter(evidence, "evidence_status"),
            "rule_field_rule_status": _field_counter(rules, "field_rule_status"),
        },
    }


def _restriction_input_identity(
    item: RestrictionInput,
    *,
    strategy: RestorationStrategy,
) -> tuple[str, str, str, str]:
    condition_identity = (
        item.condition_identity or restriction_condition_identity(item)
        if strategy == RestorationStrategy.MULTI_EVIDENCE_V2
        else ""
    )
    return (
        item.restriction_id,
        item.in_link_id,
        item.out_link_id,
        condition_identity,
    )


def _restriction_evidence_input_identity(
    item: T09EvidenceItem,
    *,
    strategy: RestorationStrategy,
) -> tuple[str, str, str, str] | None:
    matched_ids = item.provenance.matched_object_ids
    if len(matched_ids) < 5:
        return None
    return (
        item.provenance.source_id,
        str(matched_ids[-2]),
        str(matched_ids[-1]),
        item.condition_identity
        if strategy == RestorationStrategy.MULTI_EVIDENCE_V2
        else "",
    )


def _field_counter(items: tuple[object, ...], field_name: str) -> dict[str, int]:
    values: Counter[str] = Counter()
    for item in items:
        value = getattr(item, field_name)
        if value is None or value == "":
            continue
        values[str(value.value if hasattr(value, "value") else value)] += 1
    return dict(sorted(values.items()))


def _enum_counter(items: tuple[object, ...], field_name: str) -> dict[str, int]:
    values: Counter[str] = Counter()
    for item in items:
        value = getattr(item, field_name)
        values[value.value if value is not None else "none"] += 1
    return dict(sorted(values.items()))


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
