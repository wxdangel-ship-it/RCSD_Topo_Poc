from __future__ import annotations

import json
from dataclasses import dataclass, replace

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arrow_evidence import RoadArrowDecision
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.restriction_evidence import (
    RestrictionMatchResult,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    DecisionSource,
    DecisionStatus,
    EvidencePriority,
    EvidenceProvenance,
    EvidenceType,
    InferenceLevel,
    OverrideChainEntry,
    ProhibitionReason,
    ProhibitionStatus,
    RestorationStrategy,
    RoadPair,
    RuleScope,
    T09ArmMovement,
    T09EvidenceItem,
    T09RestoredFieldRule,
    VerificationStatus,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.special_carrier import (
    SpecialCarrierArmProfile,
    SpecialCarrierDecision,
    evaluate_special_carrier_decision,
)


@dataclass(frozen=True)
class MultiEvidenceDecisionResult:
    movement: T09ArmMovement
    evidence_items: tuple[T09EvidenceItem, ...]
    restored_rules: tuple[T09RestoredFieldRule, ...]


@dataclass(frozen=True)
class _LowerDecision:
    status: DecisionStatus
    source: DecisionSource
    scope: RuleScope
    priority: EvidencePriority
    inference_level: InferenceLevel
    verification_status: VerificationStatus
    confidence: float
    supporting: tuple[T09EvidenceItem, ...]
    conflicting: tuple[T09EvidenceItem, ...]
    override_chain: tuple[OverrideChainEntry, ...]
    evidence_items: tuple[T09EvidenceItem, ...]
    risk_flags: tuple[str, ...]


def resolve_multi_evidence_movement(
    *,
    movement: T09ArmMovement,
    restriction_result: RestrictionMatchResult,
    road_arrow_decisions: tuple[RoadArrowDecision, ...],
    special_profile: SpecialCarrierArmProfile | None,
) -> MultiEvidenceDecisionResult:
    """Resolve v2 rules on atomic Road targets before any scope promotion."""

    if movement.movement_applicability.value != "applicable" or not movement.carrier_road_pairs:
        return MultiEvidenceDecisionResult(
            movement=replace(
                movement,
                strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
                decision_status=DecisionStatus.NOT_APPLICABLE,
                decision_source=DecisionSource.TOPOLOGY,
                decision_scope=RuleScope.ARM_TO_ARM,
                verification_status=VerificationStatus.NOT_REQUIRED,
                prohibition_status=ProhibitionStatus.NOT_A_TRAFFIC_RULE,
                prohibition_reason=ProhibitionReason.TOPOLOGY_NOT_APPLICABLE,
                prohibition_confidence=1.0,
            ),
            evidence_items=tuple(),
            restored_rules=tuple(),
        )

    arrow_by_road = {item.road_id: item for item in road_arrow_decisions}
    approach_road_ids = tuple(sorted({pair.from_road_id for pair in movement.carrier_road_pairs}, key=_sort_key))
    restriction_items = tuple(restriction_result.evidence_items)
    evidence_items: list[T09EvidenceItem] = list(restriction_items)
    lower_by_road: dict[str, _LowerDecision] = {}
    for road_id in approach_road_ids:
        lower = _resolve_lower_priority_decision(
            movement=movement,
            road_id=road_id,
            arrow_decision=arrow_by_road.get(road_id),
            special_profile=special_profile,
        )
        lower_by_road[road_id] = lower
        evidence_items.extend(lower.evidence_items)

    rules: list[T09RestoredFieldRule] = []
    covered_pairs = {item.road_pair for item in restriction_items if item.road_pair is not None}
    for condition_items in _restriction_condition_groups(restriction_items):
        condition_result = _condition_restriction_result(
            restriction_result,
            condition_items=condition_items,
        )
        condition_covered_pairs = {
            item.road_pair for item in condition_items if item.road_pair is not None
        }
        if (
            condition_result.scope_promotion_status == "arm_to_arm_confirmed"
            and condition_covered_pairs == set(movement.carrier_road_pairs)
        ):
            rules.append(
                _restriction_arm_rule(
                    movement=movement,
                    restriction_result=condition_result,
                    restriction_items=condition_items,
                    lower_by_road=lower_by_road,
                )
            )
            continue
        for grouped_items in _restriction_atomic_groups(condition_items):
            pair = grouped_items[0].road_pair
            assert pair is not None
            lower = lower_by_road.get(pair.from_road_id)
            rules.append(
                _restriction_road_pair_rule(
                    movement=movement,
                    restriction_result=condition_result,
                    restriction_items=grouped_items,
                    lower_decision=lower,
                )
            )

    for road_id in approach_road_ids:
        uncovered_pairs = tuple(
            pair
            for pair in movement.carrier_road_pairs
            if pair.from_road_id == road_id and pair not in covered_pairs
        )
        if not uncovered_pairs:
            continue
        rules.append(
            _lower_rule(
                movement=movement,
                road_id=road_id,
                to_road_ids=tuple(sorted({pair.to_road_id for pair in uncovered_pairs}, key=_sort_key)),
                road_pairs=uncovered_pairs,
                lower=lower_by_road[road_id],
            )
        )

    rules = _dedupe_rules(rules)
    updated_movement = _movement_from_rules(
        movement=movement,
        rules=tuple(rules),
        restriction_result=restriction_result,
        evidence_items=tuple(_dedupe_evidence(evidence_items)),
    )
    return MultiEvidenceDecisionResult(
        movement=updated_movement,
        evidence_items=tuple(_dedupe_evidence(evidence_items)),
        restored_rules=tuple(rules),
    )


def _resolve_lower_priority_decision(
    *,
    movement: T09ArmMovement,
    road_id: str,
    arrow_decision: RoadArrowDecision | None,
    special_profile: SpecialCarrierArmProfile | None,
) -> _LowerDecision:
    lane_evidence = tuple(arrow_decision.evidence_items) if arrow_decision else tuple()
    if not lane_evidence:
        lane_evidence = (_missing_laneinfo_evidence(movement, road_id, arrow_decision),)
    special_decision = (
        evaluate_special_carrier_decision(
            special_profile,
            road_id=road_id,
            movement_type=movement.movement_type,
        )
        if special_profile is not None
        else None
    )
    special_evidence = (
        (_special_decision_evidence(movement, special_decision),)
        if special_decision is not None
        else tuple()
    )
    lane_status = arrow_decision.decision_status if arrow_decision else DecisionStatus.UNKNOWN
    lane_has_priority_barrier = lane_status != DecisionStatus.UNKNOWN
    if lane_has_priority_barrier:
        conflicting = _semantic_conflicts(lane_status, special_evidence)
        corroborating = _semantic_supports(lane_status, special_evidence)
        overridden = _priority_override_targets(lane_status, special_evidence)
        chain = _override_entries(
            winner=lane_evidence[0],
            losers=overridden,
            reason="Laneinfo has priority over special carrier weak inference",
            final_status=lane_status,
        )
        return _LowerDecision(
            status=lane_status,
            source=DecisionSource.LANEINFO,
            scope=_lane_scope(lane_status, lane_evidence),
            priority=EvidencePriority.LANEINFO,
            inference_level=(
                InferenceLevel.DERIVED
                if lane_status in {DecisionStatus.PROHIBITED, DecisionStatus.SUPPORTED}
                else InferenceLevel.UNKNOWN
            ),
            verification_status=_lane_verification_status(lane_status, lane_evidence),
            confidence=arrow_decision.confidence if arrow_decision else 0.0,
            supporting=_sorted_evidence(lane_evidence + corroborating),
            conflicting=conflicting,
            override_chain=chain,
            evidence_items=lane_evidence + special_evidence,
            risk_flags=tuple(sorted(set((arrow_decision.risk_flags if arrow_decision else tuple())) | _risk_set(special_evidence))),
        )
    if special_decision is not None:
        return _LowerDecision(
            status=special_decision.decision_status,
            source=DecisionSource.SPECIAL_CARRIER,
            scope=special_decision.decision_scope,
            priority=EvidencePriority.SPECIAL_CARRIER,
            inference_level=special_decision.inference_level,
            verification_status=special_decision.verification_status,
            confidence=0.6 if special_decision.decision_status != DecisionStatus.UNKNOWN else 0.0,
            supporting=special_evidence,
            conflicting=tuple(),
            override_chain=tuple(),
            evidence_items=lane_evidence + special_evidence,
            risk_flags=tuple(sorted(set(special_decision.risk_flags) | _risk_set(lane_evidence))),
        )
    return _LowerDecision(
        status=DecisionStatus.UNKNOWN,
        source=DecisionSource.LANEINFO,
        scope=RuleScope.ROAD_TO_ARM,
        priority=EvidencePriority.LANEINFO,
        inference_level=InferenceLevel.UNKNOWN,
        verification_status=VerificationStatus.NOT_REQUIRED,
        confidence=0.0,
        supporting=lane_evidence,
        conflicting=tuple(),
        override_chain=tuple(),
        evidence_items=lane_evidence,
        risk_flags=tuple(sorted(_risk_set(lane_evidence))),
    )


def _restriction_arm_rule(
    *,
    movement: T09ArmMovement,
    restriction_result: RestrictionMatchResult,
    restriction_items: tuple[T09EvidenceItem, ...],
    lower_by_road: dict[str, _LowerDecision],
) -> T09RestoredFieldRule:
    sorted_restrictions = _sorted_evidence(restriction_items)
    conflicting_items: list[T09EvidenceItem] = []
    chain_items: list[OverrideChainEntry] = []
    for road_id, lower in sorted(lower_by_road.items(), key=lambda item: _sort_key(item[0])):
        chain_items.extend(lower.override_chain)
        if lower.status != DecisionStatus.SUPPORTED:
            continue
        road_conflicts = _semantic_conflicts(DecisionStatus.PROHIBITED, lower.supporting)
        conflicting_items.extend(road_conflicts)
        winner = next(
            (
                item
                for item in sorted_restrictions
                if item.road_pair is not None and item.road_pair.from_road_id == road_id
            ),
            sorted_restrictions[0],
        )
        chain_items.extend(
            _override_entries(
                winner=winner,
                losers=road_conflicts,
                reason="Restriction has priority over Laneinfo or special carrier",
                final_status=DecisionStatus.PROHIBITED,
            )
        )
    conflicting = tuple(_dedupe_evidence(conflicting_items))
    chain = _dedupe_override_chain(tuple(chain_items))
    return _make_rule(
        movement=movement,
        status=DecisionStatus.PROHIBITED,
        source=DecisionSource.RESTRICTION,
        scope=RuleScope.ARM_TO_ARM,
        priority=EvidencePriority.RESTRICTION,
        inference_level=InferenceLevel.EXPLICIT,
        verification_status=VerificationStatus.VERIFIED_SWSD,
        supporting=restriction_items,
        conflicting=conflicting,
        override_chain=chain,
        from_road_ids=tuple(sorted({pair.from_road_id for pair in movement.carrier_road_pairs}, key=_sort_key)),
        to_road_ids=tuple(sorted({pair.to_road_id for pair in movement.carrier_road_pairs}, key=_sort_key)),
        road_pairs=movement.carrier_road_pairs,
        field_rule_status=ProhibitionStatus.FULLY_PROHIBITED,
        confidence=restriction_result.confidence,
        scope_promotion_status=restriction_result.scope_promotion_status,
        scope_promotion_reason=restriction_result.scope_promotion_reason,
        scope_promotion_audit=restriction_result.scope_promotion_audit or {},
    )


def _restriction_road_pair_rule(
    *,
    movement: T09ArmMovement,
    restriction_result: RestrictionMatchResult,
    restriction_items: tuple[T09EvidenceItem, ...],
    lower_decision: _LowerDecision | None,
) -> T09RestoredFieldRule:
    restriction_items = _sorted_evidence(restriction_items)
    conflicting = (
        _semantic_conflicts(DecisionStatus.PROHIBITED, lower_decision.supporting)
        if lower_decision is not None and lower_decision.status == DecisionStatus.SUPPORTED
        else tuple()
    )
    chain = (lower_decision.override_chain if lower_decision else tuple()) + _override_entries(
        winner=restriction_items[0],
        losers=conflicting,
        reason="Restriction Road-Pair has priority over lower evidence",
        final_status=DecisionStatus.PROHIBITED,
    )
    pair = restriction_items[0].road_pair
    assert pair is not None
    return _make_rule(
        movement=movement,
        status=DecisionStatus.PROHIBITED,
        source=DecisionSource.RESTRICTION,
        scope=RuleScope.ROAD_TO_ROAD,
        priority=EvidencePriority.RESTRICTION,
        inference_level=InferenceLevel.EXPLICIT,
        verification_status=(
            VerificationStatus.MANUAL_REVIEW_REQUIRED
            if restriction_result.scope_promotion_status == "manual_review_required"
            else VerificationStatus.VERIFIED_SWSD
        ),
        supporting=restriction_items,
        conflicting=conflicting,
        override_chain=chain,
        from_road_ids=(pair.from_road_id,),
        to_road_ids=(pair.to_road_id,),
        road_pairs=(pair,),
        field_rule_status=ProhibitionStatus.PARTIALLY_PROHIBITED,
        confidence=min(item.confidence for item in restriction_items),
        scope_promotion_status=restriction_result.scope_promotion_status,
        scope_promotion_reason=restriction_result.scope_promotion_reason,
        scope_promotion_audit=restriction_result.scope_promotion_audit or {},
    )


def _lower_rule(
    *,
    movement: T09ArmMovement,
    road_id: str,
    to_road_ids: tuple[str, ...],
    road_pairs: tuple[RoadPair, ...],
    lower: _LowerDecision,
) -> T09RestoredFieldRule:
    return _make_rule(
        movement=movement,
        status=lower.status,
        source=lower.source,
        scope=lower.scope,
        priority=lower.priority,
        inference_level=lower.inference_level,
        verification_status=lower.verification_status,
        supporting=lower.supporting,
        conflicting=lower.conflicting,
        override_chain=lower.override_chain,
        from_road_ids=(road_id,),
        to_road_ids=to_road_ids,
        road_pairs=road_pairs,
        field_rule_status=_legacy_status(lower.status),
        confidence=lower.confidence,
        risk_flags=lower.risk_flags,
        scope_promotion_status="not_applicable",
        scope_promotion_reason="Road-scoped evidence is not promoted to Arm scope",
        scope_promotion_audit={"promotion_allowed": False, "reason": "road_scoped_evidence"},
    )


def _make_rule(
    *,
    movement: T09ArmMovement,
    status: DecisionStatus,
    source: DecisionSource,
    scope: RuleScope,
    priority: EvidencePriority,
    inference_level: InferenceLevel,
    verification_status: VerificationStatus,
    supporting: tuple[T09EvidenceItem, ...],
    conflicting: tuple[T09EvidenceItem, ...],
    override_chain: tuple[OverrideChainEntry, ...],
    from_road_ids: tuple[str, ...],
    to_road_ids: tuple[str, ...],
    road_pairs: tuple[RoadPair, ...],
    field_rule_status: ProhibitionStatus,
    confidence: float,
    scope_promotion_status: str,
    scope_promotion_reason: str,
    scope_promotion_audit: dict[str, object],
    risk_flags: tuple[str, ...] = tuple(),
) -> T09RestoredFieldRule:
    supporting = _sorted_evidence(supporting)
    conflicting = _sorted_evidence(conflicting)
    override_chain = _dedupe_override_chain(override_chain)
    from_road_ids = tuple(sorted(set(from_road_ids), key=_sort_key))
    to_road_ids = tuple(sorted(set(to_road_ids), key=_sort_key))
    road_pairs = tuple(
        sorted(
            set(road_pairs),
            key=lambda item: (_sort_key(item.from_road_id), _sort_key(item.to_road_id)),
        )
    )
    restriction_items = tuple(item for item in supporting if item.evidence_type == EvidenceType.RESTRICTION)
    condition_identities = tuple(sorted({item.condition_identity for item in restriction_items if item.condition_identity}))
    condition_types = tuple(sorted({item.condition_type for item in restriction_items if item.condition_type is not None}))
    condition_semantics = tuple(
        sorted({item.condition_semantics_status for item in restriction_items if item.condition_semantics_status})
    )
    condition_payload = tuple(
        {
            "restriction_id": item.provenance.source_id,
            "from_road_ids": item.from_road_ids,
            "to_road_ids": item.to_road_ids,
            "raw_properties": dict(item.condition_payload),
        }
        for item in restriction_items
    )
    condition_identity = condition_identities[0] if len(condition_identities) == 1 else (
        "mixed:" + "+".join(condition_identities) if condition_identities else ""
    )
    condition_type = condition_types[0] if len(condition_types) == 1 else (
        "mixed" if condition_types else None
    )
    semantics_status = condition_semantics[0] if len(condition_semantics) == 1 else (
        "mixed" if condition_semantics else "not_applicable"
    )
    combined_risks = tuple(
        sorted(
            set(risk_flags)
            | _risk_set(supporting)
            | _risk_set(conflicting)
            | {flag for entry in override_chain for flag in entry.risk_flags}
        )
    )
    rule_id = _rule_id(
        movement=movement,
        source=source,
        scope=scope,
        status=status,
        from_road_ids=from_road_ids,
        to_road_ids=to_road_ids,
        condition_identity=condition_identity,
    )
    return T09RestoredFieldRule(
        junction_id=movement.junction_id,
        from_arm_id=movement.from_arm_id,
        to_arm_id=movement.to_arm_id,
        movement_type=movement.movement_type,
        field_rule_status=field_rule_status,
        rule_scope=scope.value,
        supporting_evidence_ids=tuple(item.evidence_id for item in supporting),
        conflicting_evidence_ids=tuple(item.evidence_id for item in conflicting),
        inference_level=inference_level,
        confidence=confidence,
        risk_flags=combined_risks,
        rule_id=rule_id,
        movement_id=movement.movement_id,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
        decision_status=status,
        decision_source=source,
        decision_scope=scope,
        evidence_priority=priority,
        verification_status=verification_status,
        override_chain=override_chain,
        from_road_ids=from_road_ids,
        to_road_ids=to_road_ids,
        road_pairs=road_pairs,
        source_restriction_ids=tuple(sorted({item.provenance.source_id for item in restriction_items})),
        condition_type=condition_type,
        condition_payload=condition_payload,
        condition_identity=condition_identity,
        condition_semantics_status=semantics_status,
        scope_promotion_status=scope_promotion_status,
        scope_promotion_reason=scope_promotion_reason,
        scope_promotion_audit=dict(scope_promotion_audit),
    )


def _movement_from_rules(
    *,
    movement: T09ArmMovement,
    rules: tuple[T09RestoredFieldRule, ...],
    restriction_result: RestrictionMatchResult,
    evidence_items: tuple[T09EvidenceItem, ...],
) -> T09ArmMovement:
    statuses = {rule.decision_status for rule in rules}
    conditional_scope_review = (
        restriction_result.condition_identity_count > 1
        and restriction_result.scope_promotion_status
        != "condition_scoped_arm_to_arm_confirmed"
    )
    mixed_atomic_outcomes = len(statuses) > 1 or conditional_scope_review
    if conditional_scope_review:
        decision_status = DecisionStatus.MANUAL_REVIEW_REQUIRED
    elif statuses == {DecisionStatus.CONFLICT}:
        decision_status = DecisionStatus.CONFLICT
    elif statuses == {DecisionStatus.NOT_APPLICABLE}:
        decision_status = DecisionStatus.NOT_APPLICABLE
    elif DecisionStatus.MANUAL_REVIEW_REQUIRED in statuses:
        decision_status = DecisionStatus.MANUAL_REVIEW_REQUIRED
    elif DecisionStatus.UNVERIFIED in statuses:
        decision_status = DecisionStatus.UNVERIFIED
    elif mixed_atomic_outcomes:
        decision_status = DecisionStatus.UNKNOWN
    elif DecisionStatus.PROHIBITED in statuses:
        decision_status = DecisionStatus.PROHIBITED
    elif statuses == {DecisionStatus.SUPPORTED}:
        decision_status = DecisionStatus.SUPPORTED
    else:
        decision_status = DecisionStatus.UNKNOWN
    priorities = [rule.evidence_priority for rule in rules if rule.evidence_priority is not None]
    priority = min(priorities, key=_priority_rank) if priorities else None
    top_rules = tuple(rule for rule in rules if rule.evidence_priority == priority) if priority else tuple()
    sources = {rule.decision_source for rule in top_rules}
    scopes = {rule.decision_scope for rule in top_rules if rule.decision_scope is not None}
    restriction_rules = tuple(
        rule
        for rule in rules
        if rule.decision_source == DecisionSource.RESTRICTION
        and rule.decision_status == DecisionStatus.PROHIBITED
    )
    if conditional_scope_review:
        legacy_status = ProhibitionStatus.PARTIALLY_PROHIBITED
    elif any(rule.decision_scope == RuleScope.ARM_TO_ARM for rule in restriction_rules):
        legacy_status = ProhibitionStatus.FULLY_PROHIBITED
    elif any(rule.decision_status == DecisionStatus.PROHIBITED for rule in rules):
        legacy_status = ProhibitionStatus.PARTIALLY_PROHIBITED
    else:
        legacy_status = _legacy_status(decision_status)
    winning_rules = tuple(rule for rule in rules if rule.decision_status == decision_status)
    confidence = (
        min((rule.confidence for rule in winning_rules), default=0.0)
        if not mixed_atomic_outcomes
        else 0.0
    )
    movement_risks = set(movement.risk_flags)
    if mixed_atomic_outcomes:
        movement_risks.add("mixed_atomic_outcomes")
    if conditional_scope_review:
        movement_risks.add("condition_scoped_mixed_outcomes")
    if decision_status == DecisionStatus.UNKNOWN and any(
        rule.verification_status == VerificationStatus.NOT_REQUIRED for rule in rules
    ):
        movement_risks.add("incomplete_atomic_evidence")
    return replace(
        movement,
        strategy_version=RestorationStrategy.MULTI_EVIDENCE_V2,
        decision_status=decision_status,
        decision_source=(
            next(iter(sources))
            if len(sources) == 1 and not mixed_atomic_outcomes
            else DecisionSource.NONE
        ),
        decision_scope=(next(iter(scopes)) if len(scopes) == 1 and not mixed_atomic_outcomes else None),
        evidence_priority=priority,
        verification_status=_movement_verification_status(rules),
        override_chain=tuple(entry for rule in rules for entry in rule.override_chain),
        evidence_item_ids=tuple(item.evidence_id for item in evidence_items),
        prohibition_status=legacy_status,
        prohibition_reason=(
            ProhibitionReason.EXPLICIT_RESTRICTION
            if restriction_result.evidence_items
            else (
                ProhibitionReason.COMPLETE_ARROW_EXCLUSION
                if any(rule.decision_status == DecisionStatus.PROHIBITED for rule in rules)
                else ProhibitionReason.INSUFFICIENT_EVIDENCE
            )
        ),
        prohibition_confidence=confidence,
        restriction_coverage=restriction_result.restriction_coverage,
        partial_basis=restriction_result.partial_basis,
        remaining_restriction_status=restriction_result.remaining_restriction_status,
        risk_flags=tuple(sorted(movement_risks)),
    )


def _missing_laneinfo_evidence(
    movement: T09ArmMovement,
    road_id: str,
    arrow_decision: RoadArrowDecision | None,
) -> T09EvidenceItem:
    reason = arrow_decision.reason if arrow_decision else "no Laneinfo input matched the approach Road"
    risk_flags = arrow_decision.risk_flags if arrow_decision else ("missing_laneinfo",)
    decision_status = arrow_decision.decision_status if arrow_decision else DecisionStatus.UNKNOWN
    return T09EvidenceItem(
        evidence_id=f"laneinfo:{movement.movement_id}:{road_id}:unknown-audit",
        evidence_type=EvidenceType.ARROW,
        junction_id=movement.junction_id,
        movement_id=movement.movement_id,
        road_pair=None,
        evidence_status=f"laneinfo_{decision_status.value}_for_road_movement",
        prohibition_reason=ProhibitionReason.INSUFFICIENT_EVIDENCE,
        inference_level=InferenceLevel.UNKNOWN,
        confidence=0.0,
        provenance=EvidenceProvenance(
            source_type="laneinfo",
            source_id=",".join(arrow_decision.source_arrow_ids) if arrow_decision else road_id,
            matched_object_ids=(movement.movement_id, road_id),
            match_method="approach_road_direction_lane_union",
            field_audit={"lane_summary": arrow_decision.lane_summary if arrow_decision else {}},
            reason=reason,
        ),
        supports_prohibition=False,
        risk_flags=risk_flags,
        decision_status=decision_status,
        decision_scope=(
            RuleScope.ROAD_DIRECTION_EXCLUSION
            if decision_status == DecisionStatus.PROHIBITED
            else RuleScope.ROAD_TO_ARM
        ),
        evidence_priority=EvidencePriority.LANEINFO,
        verification_status=_lane_verification_status(decision_status, tuple()),
        from_road_ids=(road_id,),
        to_road_ids=tuple(
            sorted({pair.to_road_id for pair in movement.carrier_road_pairs if pair.from_road_id == road_id})
        ),
    )


def _special_decision_evidence(
    movement: T09ArmMovement,
    decision: SpecialCarrierDecision,
) -> T09EvidenceItem:
    prohibited = decision.decision_status == DecisionStatus.PROHIBITED
    source_carrier_road_ids = (
        decision.source_carrier_road_ids or (decision.road_id,)
    )
    return T09EvidenceItem(
        evidence_id=(
            f"special_decision:{movement.movement_id}:{decision.road_id}:"
            f"{decision.decision_scope.value}:{decision.decision_status.value}"
        ),
        evidence_type=EvidenceType.SPECIAL_CARRIER,
        junction_id=movement.junction_id,
        movement_id=movement.movement_id,
        road_pair=None,
        evidence_status=decision.evidence_status,
        prohibition_reason=ProhibitionReason.SPECIAL_CARRIER_DISPLACEMENT,
        inference_level=decision.inference_level,
        confidence=0.6 if decision.decision_status not in {DecisionStatus.UNKNOWN, DecisionStatus.MANUAL_REVIEW_REQUIRED} else 0.0,
        provenance=EvidenceProvenance(
            source_type="special_carrier",
            source_id=",".join(source_carrier_road_ids),
            matched_object_ids=(
                movement.movement_id,
                movement.from_arm_id,
                decision.road_id,
                *source_carrier_road_ids,
            ),
            match_method="arm_scoped_formway_carrier_decision",
            field_audit={
                "carrier_type": decision.carrier_type,
                "movement_type": decision.movement_type,
                "decision_scope": decision.decision_scope.value,
                "target_approach_road_id": decision.road_id,
                "source_carrier_road_ids": source_carrier_road_ids,
            },
            reason=decision.evidence_status,
        ),
        supports_prohibition=prohibited,
        risk_flags=decision.risk_flags,
        decision_status=decision.decision_status,
        decision_scope=decision.decision_scope,
        evidence_priority=EvidencePriority.SPECIAL_CARRIER,
        verification_status=decision.verification_status,
        from_road_ids=(decision.road_id,),
        to_road_ids=tuple(
            sorted({pair.to_road_id for pair in movement.carrier_road_pairs if pair.from_road_id == decision.road_id})
        ),
    )


def _override_entries(
    *,
    winner: T09EvidenceItem,
    losers: tuple[T09EvidenceItem, ...],
    reason: str,
    final_status: DecisionStatus,
) -> tuple[OverrideChainEntry, ...]:
    winner_source = _decision_source_for_evidence(winner)
    return tuple(
        OverrideChainEntry(
            winner_evidence_id=winner.evidence_id,
            winner_source=winner_source,
            overridden_evidence_id=loser.evidence_id,
            overridden_source=_decision_source_for_evidence(loser),
            reason=reason,
            decision_status=final_status,
            risk_flags=tuple(sorted(set(winner.risk_flags) | set(loser.risk_flags))),
        )
        for loser in losers
    )


def _decision_source_for_evidence(item: T09EvidenceItem) -> DecisionSource:
    if item.evidence_priority == EvidencePriority.RESTRICTION or item.evidence_type == EvidenceType.RESTRICTION:
        return DecisionSource.RESTRICTION
    if item.evidence_priority == EvidencePriority.LANEINFO or item.evidence_type in {EvidenceType.ARROW, EvidenceType.COMPLETE_ARROW_EXCLUSION}:
        return DecisionSource.LANEINFO
    if item.evidence_priority == EvidencePriority.SPECIAL_CARRIER or item.evidence_type == EvidenceType.SPECIAL_CARRIER:
        return DecisionSource.SPECIAL_CARRIER
    return DecisionSource.NONE


def _legacy_status(status: DecisionStatus) -> ProhibitionStatus:
    if status == DecisionStatus.PROHIBITED:
        return ProhibitionStatus.PARTIALLY_PROHIBITED
    if status == DecisionStatus.SUPPORTED:
        return ProhibitionStatus.NO_PROHIBITION_EVIDENCE
    if status == DecisionStatus.CONFLICT:
        return ProhibitionStatus.CONFLICT
    if status == DecisionStatus.NOT_APPLICABLE:
        return ProhibitionStatus.NOT_A_TRAFFIC_RULE
    return ProhibitionStatus.UNKNOWN


def _movement_verification_status(rules: tuple[T09RestoredFieldRule, ...]) -> VerificationStatus:
    statuses = {rule.verification_status for rule in rules}
    if VerificationStatus.MANUAL_REVIEW_REQUIRED in statuses:
        return VerificationStatus.MANUAL_REVIEW_REQUIRED
    if VerificationStatus.UNVERIFIED_DUE_TO_MISSING_FRCSD_LANEINFO in statuses:
        return VerificationStatus.UNVERIFIED_DUE_TO_MISSING_FRCSD_LANEINFO
    if statuses == {VerificationStatus.VERIFIED_FRCSD}:
        return VerificationStatus.VERIFIED_FRCSD
    if statuses == {VerificationStatus.VERIFIED_SWSD}:
        return VerificationStatus.VERIFIED_SWSD
    return VerificationStatus.NOT_REQUIRED


def _priority_rank(priority: EvidencePriority) -> int:
    return {
        EvidencePriority.RESTRICTION: 0,
        EvidencePriority.LANEINFO: 1,
        EvidencePriority.SPECIAL_CARRIER: 2,
    }[priority]


def _rule_id(
    *,
    movement: T09ArmMovement,
    source: DecisionSource,
    scope: RuleScope,
    status: DecisionStatus,
    from_road_ids: tuple[str, ...],
    to_road_ids: tuple[str, ...],
    condition_identity: str,
) -> str:
    return ":".join(
        (
            movement.movement_id,
            "rule",
            source.value,
            scope.value,
            status.value,
            "+".join(from_road_ids) or "none",
            "+".join(to_road_ids) or "none",
            condition_identity or "unconditional",
        )
    )


def _dedupe_evidence(items: list[T09EvidenceItem]) -> list[T09EvidenceItem]:
    result: dict[str, T09EvidenceItem] = {}
    for item in items:
        result.setdefault(item.evidence_id, item)
    return list(result.values())


def _dedupe_rules(items: list[T09RestoredFieldRule]) -> list[T09RestoredFieldRule]:
    grouped: dict[str, list[T09RestoredFieldRule]] = {}
    for item in items:
        grouped.setdefault(item.rule_id, []).append(item)
    return [
        _merge_rule_group(grouped[rule_id])
        for rule_id in sorted(grouped)
    ]


def _merge_rule_group(group: list[T09RestoredFieldRule]) -> T09RestoredFieldRule:
    ordered = sorted(group, key=lambda item: _rule_sort_key(item))
    base = ordered[0]
    payload_by_text: dict[str, dict[str, object]] = {}
    for item in ordered:
        for payload in item.condition_payload:
            payload_by_text.setdefault(
                json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                payload,
            )
    return replace(
        base,
        supporting_evidence_ids=tuple(
            sorted({value for item in ordered for value in item.supporting_evidence_ids})
        ),
        conflicting_evidence_ids=tuple(
            sorted({value for item in ordered for value in item.conflicting_evidence_ids})
        ),
        override_chain=_dedupe_override_chain(
            tuple(value for item in ordered for value in item.override_chain)
        ),
        from_road_ids=tuple(
            sorted({value for item in ordered for value in item.from_road_ids}, key=_sort_key)
        ),
        to_road_ids=tuple(
            sorted({value for item in ordered for value in item.to_road_ids}, key=_sort_key)
        ),
        road_pairs=tuple(
            sorted(
                {value for item in ordered for value in item.road_pairs},
                key=lambda value: (_sort_key(value.from_road_id), _sort_key(value.to_road_id)),
            )
        ),
        source_restriction_ids=tuple(
            sorted({value for item in ordered for value in item.source_restriction_ids})
        ),
        condition_payload=tuple(payload_by_text[key] for key in sorted(payload_by_text)),
        risk_flags=tuple(sorted({value for item in ordered for value in item.risk_flags})),
        confidence=min((item.confidence for item in ordered), default=base.confidence),
    )


def _restriction_atomic_groups(
    items: tuple[T09EvidenceItem, ...],
) -> tuple[tuple[T09EvidenceItem, ...], ...]:
    grouped: dict[tuple[RoadPair, str], list[T09EvidenceItem]] = {}
    for item in items:
        if item.road_pair is None:
            continue
        grouped.setdefault((item.road_pair, item.condition_identity), []).append(item)
    return tuple(
        _sorted_evidence(grouped[key])
        for key in sorted(
            grouped,
            key=lambda key: (
                _sort_key(key[0].from_road_id),
                _sort_key(key[0].to_road_id),
                key[1],
            ),
        )
    )


def _restriction_condition_groups(
    items: tuple[T09EvidenceItem, ...],
) -> tuple[tuple[T09EvidenceItem, ...], ...]:
    grouped: dict[str, list[T09EvidenceItem]] = {}
    for item in items:
        grouped.setdefault(item.condition_identity, []).append(item)
    return tuple(
        _sorted_evidence(grouped[condition_identity])
        for condition_identity in sorted(grouped)
    )


def _condition_restriction_result(
    restriction_result: RestrictionMatchResult,
    *,
    condition_items: tuple[T09EvidenceItem, ...],
) -> RestrictionMatchResult:
    condition_identity = condition_items[0].condition_identity
    scoped = (restriction_result.condition_scope_results or {}).get(condition_identity)
    if scoped is None:
        return restriction_result
    return replace(
        restriction_result,
        evidence_items=condition_items,
        confidence=float(scoped["confidence"]),
        restriction_coverage=str(scoped["restriction_coverage"]),
        partial_basis=str(scoped["partial_basis"]),
        remaining_restriction_status=str(scoped["remaining_restriction_status"]),
        condition_identity_count=1,
        scope_promotion_status=str(scoped["scope_promotion_status"]),
        scope_promotion_reason=str(scoped["scope_promotion_reason"]),
        scope_promotion_audit=dict(scoped["scope_promotion_audit"]),
        condition_scope_results={condition_identity: scoped},
    )


def _sorted_evidence(items: tuple[T09EvidenceItem, ...] | list[T09EvidenceItem]) -> tuple[T09EvidenceItem, ...]:
    return tuple(
        sorted(
            items,
            key=lambda item: (
                item.condition_identity,
                _sort_key(item.road_pair.from_road_id) if item.road_pair else (2, ""),
                _sort_key(item.road_pair.to_road_id) if item.road_pair else (2, ""),
                item.provenance.source_id,
                item.evidence_id,
            ),
        )
    )


def _semantic_conflicts(
    winner_status: DecisionStatus,
    items: tuple[T09EvidenceItem, ...],
) -> tuple[T09EvidenceItem, ...]:
    opposite = {
        DecisionStatus.PROHIBITED: DecisionStatus.SUPPORTED,
        DecisionStatus.SUPPORTED: DecisionStatus.PROHIBITED,
    }.get(winner_status)
    if opposite is None:
        return tuple()
    return _sorted_evidence(tuple(item for item in items if item.decision_status == opposite))


def _semantic_supports(
    status: DecisionStatus,
    items: tuple[T09EvidenceItem, ...],
) -> tuple[T09EvidenceItem, ...]:
    if status not in {DecisionStatus.PROHIBITED, DecisionStatus.SUPPORTED}:
        return tuple()
    return _sorted_evidence(tuple(item for item in items if item.decision_status == status))


def _priority_override_targets(
    winner_status: DecisionStatus,
    items: tuple[T09EvidenceItem, ...],
) -> tuple[T09EvidenceItem, ...]:
    if winner_status not in {DecisionStatus.PROHIBITED, DecisionStatus.SUPPORTED}:
        return _semantic_conflicts(winner_status, items)
    return _sorted_evidence(
        tuple(
            item
            for item in items
            if item.decision_status != winner_status
            and item.evidence_priority == EvidencePriority.SPECIAL_CARRIER
            and item.inference_level in {InferenceLevel.WEAK_DERIVED, InferenceLevel.UNKNOWN}
        )
    )


def _lane_scope(
    status: DecisionStatus,
    evidence: tuple[T09EvidenceItem, ...],
) -> RuleScope:
    scopes = {item.decision_scope for item in evidence if item.decision_scope is not None}
    if len(scopes) == 1:
        return next(iter(scopes))
    return RuleScope.ROAD_DIRECTION_EXCLUSION if status == DecisionStatus.PROHIBITED else RuleScope.ROAD_TO_ARM


def _lane_verification_status(
    status: DecisionStatus,
    evidence: tuple[T09EvidenceItem, ...],
) -> VerificationStatus:
    evidence_statuses = {item.verification_status for item in evidence}
    if status in {DecisionStatus.PROHIBITED, DecisionStatus.SUPPORTED}:
        return VerificationStatus.VERIFIED_SWSD
    if status == DecisionStatus.UNVERIFIED:
        return VerificationStatus.UNVERIFIED_DUE_TO_MISSING_FRCSD_LANEINFO
    if status in {DecisionStatus.CONFLICT, DecisionStatus.MANUAL_REVIEW_REQUIRED}:
        return VerificationStatus.MANUAL_REVIEW_REQUIRED
    if len(evidence_statuses) == 1:
        return next(iter(evidence_statuses))
    return VerificationStatus.NOT_REQUIRED


def _dedupe_override_chain(
    items: tuple[OverrideChainEntry, ...],
) -> tuple[OverrideChainEntry, ...]:
    indexed = {
        (
            item.winner_evidence_id,
            item.overridden_evidence_id,
            item.reason,
            item.decision_status.value,
        ): item
        for item in items
    }
    return tuple(indexed[key] for key in sorted(indexed))


def _rule_sort_key(item: T09RestoredFieldRule) -> tuple[object, ...]:
    return (
        item.rule_id,
        item.condition_identity,
        item.source_restriction_ids,
        item.supporting_evidence_ids,
    )


def _risk_set(items: tuple[T09EvidenceItem, ...]) -> set[str]:
    return {flag for item in items for flag in item.risk_flags}


def _sort_key(value: str) -> tuple[int, object]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)
