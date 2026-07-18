from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any

from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.utils.field_names import get_case_insensitive_property, normalize_field_name

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.geometry_match import (
    DirectedGeometryMatch,
    MAX_DIRECTION_DELTA_DEG,
    MAX_GEOMETRY_MATCH_DISTANCE_M,
    MAX_RESTRICTION_INSIDE_DISTANCE_M,
    match_restriction_endpoint_to_road,
    restriction_inside_endpoint_distance,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    DecisionStatus,
    EvidenceProvenance,
    EvidencePriority,
    EvidenceType,
    InferenceLevel,
    ProhibitionReason,
    ProhibitionStatus,
    RestrictionInput,
    RestorationStrategy,
    RoadPair,
    SWSDRoadInput,
    T09ArmMovement,
    T09EvidenceItem,
    T09SwsdArm,
    RuleScope,
    VerificationStatus,
    normalize_restoration_strategy,
)


@dataclass(frozen=True)
class RestrictionMatchResult:
    evidence_items: tuple[T09EvidenceItem, ...]
    prohibition_status: ProhibitionStatus
    prohibition_reason: ProhibitionReason
    confidence: float
    restriction_coverage: str = "unknown"
    partial_basis: str = "not_applicable"
    remaining_restriction_status: str = "unknown"
    condition_identity_count: int = 0
    scope_promotion_status: str = "not_evaluated"
    scope_promotion_reason: str = ""
    scope_promotion_audit: dict[str, Any] | None = None
    condition_scope_results: dict[str, dict[str, Any]] | None = None


def match_restriction_evidence(
    movement: T09ArmMovement,
    restrictions: tuple[RestrictionInput, ...],
    *,
    evidence_prefix: str = "restriction",
    roads_by_id: dict[str, SWSDRoadInput] | None = None,
    road_geometries: dict[str, BaseGeometry] | None = None,
    arms_by_id: dict[str, T09SwsdArm] | None = None,
    strategy_version: str | RestorationStrategy = RestorationStrategy.RESTRICTION_ONLY_V1,
) -> RestrictionMatchResult:
    strategy = normalize_restoration_strategy(strategy_version)
    roads_by_id = roads_by_id or {}
    road_geometries = road_geometries or {}
    arms_by_id = arms_by_id or {}
    pair_by_key = {(pair.from_road_id, pair.to_road_id): pair for pair in movement.carrier_road_pairs}
    evidence_items: list[T09EvidenceItem] = []
    next_index = 1
    matched_keys: set[tuple[str, str, str, str]] = set()
    ordered_restrictions = (
        tuple(sorted(restrictions, key=_restriction_input_sort_key))
        if strategy == RestorationStrategy.MULTI_EVIDENCE_V2
        else restrictions
    )
    for restriction in ordered_restrictions:
        road_pair = pair_by_key.get((restriction.in_link_id, restriction.out_link_id))
        if road_pair is not None:
            match_key = _restriction_match_key(
                restriction=restriction,
                road_pair=road_pair,
                strategy=strategy,
            )
            if match_key not in matched_keys:
                evidence_items.append(
                    _restriction_evidence(
                        movement=movement,
                        restriction=restriction,
                        road_pair=road_pair,
                        evidence_id=f"{evidence_prefix}:{movement.movement_id}:{next_index}",
                        evidence_status="prohibited_by_restriction",
                        match_method="inLinkID_to_outLinkID",
                        confidence=1.0,
                        field_audit={
                            "inLinkID": restriction.in_link_id,
                            "outLinkID": restriction.out_link_id,
                        },
                        reason="restriction road-pair matches movement carrier universe",
                    )
                )
                matched_keys.add(match_key)
                next_index += 1
            continue

        for carrier_pair in movement.carrier_road_pairs:
            geometry_match = _match_restriction_geometry(
                movement=movement,
                road_pair=carrier_pair,
                restriction=restriction,
                roads_by_id=roads_by_id,
                road_geometries=road_geometries,
                arms_by_id=arms_by_id,
            )
            if geometry_match is None:
                continue
            match_key = _restriction_match_key(
                restriction=restriction,
                road_pair=carrier_pair,
                strategy=strategy,
            )
            if match_key in matched_keys:
                continue
            from_match, to_match, inside_distance = geometry_match
            evidence_items.append(
                _restriction_evidence(
                    movement=movement,
                    restriction=restriction,
                    road_pair=carrier_pair,
                    evidence_id=f"{evidence_prefix}:{movement.movement_id}:{next_index}",
                    evidence_status="prohibited_by_restriction_geometry",
                    match_method="directed_geometry_restriction_to_carrier",
                    confidence=min(from_match.confidence, to_match.confidence),
                    field_audit={
                        "inLinkID": restriction.in_link_id,
                        "outLinkID": restriction.out_link_id,
                        "from_swsd_road_id": carrier_pair.from_road_id,
                        "to_swsd_road_id": carrier_pair.to_road_id,
                        "from_geometry_match": from_match.audit(),
                        "to_geometry_match": to_match.audit(),
                        "inside_endpoint_distance_m": round(inside_distance, 3),
                    },
                    reason="Tool7 raw SW restriction geometry matches SWSD movement carrier geometry and direction",
                )
            )
            matched_keys.add(match_key)
            next_index += 1

    if not evidence_items:
        return RestrictionMatchResult(
            evidence_items=tuple(),
            prohibition_status=ProhibitionStatus.NO_PROHIBITION_EVIDENCE,
            prohibition_reason=ProhibitionReason.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            restriction_coverage="no_restriction_evidence",
            partial_basis="not_applicable",
            remaining_restriction_status="no_restriction_evidence",
            scope_promotion_status="not_applicable",
            scope_promotion_reason="no restriction evidence",
            scope_promotion_audit={
                "promotion_allowed": False,
                "reason": "no_restriction_evidence",
            },
        )
    if strategy == RestorationStrategy.RESTRICTION_ONLY_V1:
        return _legacy_restriction_match_result(
            movement=movement,
            evidence_items=tuple(evidence_items),
        )

    audited_evidence = _mark_ambiguous_geometry_fanout(tuple(evidence_items))
    return _v2_condition_scoped_match_result(
        movement=movement,
        evidence_items=audited_evidence,
        arms_by_id=arms_by_id,
    )


def _legacy_restriction_match_result(
    *,
    movement: T09ArmMovement,
    evidence_items: tuple[T09EvidenceItem, ...],
) -> RestrictionMatchResult:
    """Preserve origin/main v1 coverage semantics without condition reinterpretation."""

    covered_pair_count = len(
        {item.road_pair for item in evidence_items if item.road_pair is not None}
    )
    condition_identity_count = len(
        {item.condition_identity for item in evidence_items if item.condition_identity}
    )
    if covered_pair_count == movement.candidate_road_pair_count:
        return RestrictionMatchResult(
            evidence_items=evidence_items,
            prohibition_status=ProhibitionStatus.FULLY_PROHIBITED,
            prohibition_reason=ProhibitionReason.EXPLICIT_RESTRICTION,
            confidence=min(item.confidence for item in evidence_items),
            restriction_coverage="all_restricted",
            partial_basis="not_applicable",
            remaining_restriction_status="not_applicable",
            condition_identity_count=condition_identity_count,
            scope_promotion_status="not_applicable_v1",
            scope_promotion_reason="v1 preserves legacy Road-Pair coverage semantics",
            scope_promotion_audit={
                "promotion_allowed": False,
                "strategy_version": RestorationStrategy.RESTRICTION_ONLY_V1.value,
                "reason": "scope_promotion_not_evaluated_in_v1",
            },
        )
    return RestrictionMatchResult(
        evidence_items=evidence_items,
        prohibition_status=ProhibitionStatus.PARTIALLY_PROHIBITED,
        prohibition_reason=ProhibitionReason.EXPLICIT_RESTRICTION,
        confidence=min(0.9, max(item.confidence for item in evidence_items)),
        restriction_coverage="partial_restricted",
        partial_basis=_partial_basis(movement=movement, evidence_items=evidence_items),
        remaining_restriction_status="no_restriction_evidence",
        condition_identity_count=condition_identity_count,
        scope_promotion_status="not_applicable_v1",
        scope_promotion_reason="v1 preserves legacy Road-Pair coverage semantics",
        scope_promotion_audit={
            "promotion_allowed": False,
            "strategy_version": RestorationStrategy.RESTRICTION_ONLY_V1.value,
            "reason": "scope_promotion_not_evaluated_in_v1",
        },
    )


def _v2_condition_scoped_match_result(
    *,
    movement: T09ArmMovement,
    evidence_items: tuple[T09EvidenceItem, ...],
    arms_by_id: dict[str, T09SwsdArm],
) -> RestrictionMatchResult:
    candidate_pairs = set(movement.carrier_road_pairs)
    grouped_items: dict[str, tuple[T09EvidenceItem, ...]] = {}
    for condition_identity in sorted(
        {item.condition_identity for item in evidence_items if item.condition_identity}
    ):
        grouped_items[condition_identity] = tuple(
            item for item in evidence_items if item.condition_identity == condition_identity
        )

    multiple_conditions = len(grouped_items) > 1
    condition_scope_results: dict[str, dict[str, Any]] = {}
    for condition_identity, condition_items in grouped_items.items():
        covered_pairs = {
            item.road_pair for item in condition_items if item.road_pair is not None
        }
        condition_group_complete = bool(candidate_pairs) and covered_pairs == candidate_pairs
        audit = _scope_promotion_audit(
            movement=movement,
            evidence_items=condition_items,
            arms_by_id=arms_by_id,
            same_condition_identity=True,
            strategy=RestorationStrategy.MULTI_EVIDENCE_V2,
        )
        ambiguous_geometry_fanout = any(
            "ambiguous_restriction_geometry_fanout" in item.risk_flags
            for item in condition_items
        )
        promotable = (
            condition_group_complete
            and bool(audit["promotion_allowed"])
            and not ambiguous_geometry_fanout
        )
        if promotable:
            status = "arm_to_arm_confirmed"
            reason = "complete condition-scoped carrier universe passed all promotion gates"
        elif condition_group_complete or multiple_conditions or ambiguous_geometry_fanout:
            status = "manual_review_required"
            reason = (
                "ambiguous directed restriction geometry fan-out cannot prove Arm scope"
                if ambiguous_geometry_fanout
                else "condition-scoped Arm equivalence or complete coverage is not fully proven"
            )
        else:
            status = "partial_coverage"
            reason = "restriction condition does not cover the full movement carrier universe"
        condition_scope_results[condition_identity] = {
            "condition_identity": condition_identity,
            "condition_group_complete": condition_group_complete,
            "restriction_coverage": (
                "all_restricted" if condition_group_complete else "partial_restricted"
            ),
            "partial_basis": (
                "not_applicable"
                if condition_group_complete
                else _partial_basis(movement=movement, evidence_items=condition_items)
            ),
            "remaining_restriction_status": (
                "not_applicable"
                if condition_group_complete
                else "condition_scoped_no_restriction_evidence"
            ),
            "confidence": (
                min(item.confidence for item in condition_items)
                if condition_group_complete
                else min(0.9, max(item.confidence for item in condition_items))
            ),
            "scope_promotion_status": status,
            "scope_promotion_reason": reason,
            "scope_promotion_audit": audit,
            "ambiguous_geometry_fanout": ambiguous_geometry_fanout,
        }

    group_results = tuple(condition_scope_results.values())
    complete_groups = tuple(
        item for item in group_results if item["condition_group_complete"]
    )
    promoted_groups = tuple(
        item
        for item in group_results
        if item["scope_promotion_status"] == "arm_to_arm_confirmed"
    )
    all_groups_complete = len(complete_groups) == len(group_results)
    all_groups_promoted = len(promoted_groups) == len(group_results)
    any_group_promoted = bool(promoted_groups)

    if len(group_results) == 1:
        only = group_results[0]
        return RestrictionMatchResult(
            evidence_items=evidence_items,
            prohibition_status=(
                ProhibitionStatus.FULLY_PROHIBITED
                if only["condition_group_complete"]
                else ProhibitionStatus.PARTIALLY_PROHIBITED
            ),
            prohibition_reason=ProhibitionReason.EXPLICIT_RESTRICTION,
            confidence=float(only["confidence"]),
            restriction_coverage=str(only["restriction_coverage"]),
            partial_basis=str(only["partial_basis"]),
            remaining_restriction_status=str(only["remaining_restriction_status"]),
            condition_identity_count=1,
            scope_promotion_status=str(only["scope_promotion_status"]),
            scope_promotion_reason=str(only["scope_promotion_reason"]),
            scope_promotion_audit=dict(only["scope_promotion_audit"]),
            condition_scope_results=condition_scope_results,
        )

    if all_groups_promoted:
        global_status = "condition_scoped_arm_to_arm_confirmed"
        global_reason = "each condition identity independently passed Arm promotion gates"
    elif any_group_promoted:
        global_status = "condition_scoped_mixed"
        global_reason = "complete conditions were promoted while partial conditions remain atomic"
    else:
        global_status = "manual_review_required"
        global_reason = "no condition identity independently proved Arm scope"
    global_audit = {
        "promotion_allowed": all_groups_promoted,
        "condition_identity_count": len(group_results),
        "complete_condition_identities": tuple(
            item["condition_identity"] for item in complete_groups
        ),
        "promoted_condition_identities": tuple(
            item["condition_identity"] for item in promoted_groups
        ),
        "condition_scope_results": condition_scope_results,
        "unexplained_carrier_count": sum(
            int(item["scope_promotion_audit"].get("unexplained_carrier_count", 0))
            for item in group_results
        ),
        "reason": global_reason,
    }
    return RestrictionMatchResult(
        evidence_items=evidence_items,
        prohibition_status=(
            ProhibitionStatus.FULLY_PROHIBITED
            if all_groups_complete
            else ProhibitionStatus.PARTIALLY_PROHIBITED
        ),
        prohibition_reason=ProhibitionReason.EXPLICIT_RESTRICTION,
        confidence=(
            min(item.confidence for item in evidence_items)
            if all_groups_complete
            else min(0.9, max(item.confidence for item in evidence_items))
        ),
        restriction_coverage=(
            "condition_scoped_all_restricted"
            if all_groups_complete
            else "conditional_mixed_coverage"
        ),
        partial_basis=("not_applicable" if all_groups_complete else "condition_scoped_coverage"),
        remaining_restriction_status=(
            "not_applicable" if all_groups_complete else "condition_dependent"
        ),
        condition_identity_count=len(group_results),
        scope_promotion_status=global_status,
        scope_promotion_reason=global_reason,
        scope_promotion_audit=global_audit,
        condition_scope_results=condition_scope_results,
    )


def _mark_ambiguous_geometry_fanout(
    evidence_items: tuple[T09EvidenceItem, ...],
) -> tuple[T09EvidenceItem, ...]:
    grouped: dict[tuple[str, str, str, str], list[T09EvidenceItem]] = {}
    for item in evidence_items:
        if item.provenance.match_method not in {
            "inLinkID_to_outLinkID",
            "directed_geometry_restriction_to_carrier",
        }:
            continue
        field_audit = item.provenance.field_audit
        key = (
            item.provenance.source_id,
            item.condition_identity,
            str(field_audit.get("inLinkID", "")),
            str(field_audit.get("outLinkID", "")),
        )
        grouped.setdefault(key, []).append(item)

    ambiguous_keys = {
        key
        for key, items in grouped.items()
        if len({item.road_pair for item in items if item.road_pair is not None}) > 1
    }
    if not ambiguous_keys:
        return evidence_items

    audited_items: list[T09EvidenceItem] = []
    for item in evidence_items:
        field_audit = item.provenance.field_audit
        key = (
            item.provenance.source_id,
            item.condition_identity,
            str(field_audit.get("inLinkID", "")),
            str(field_audit.get("outLinkID", "")),
        )
        if (
            key not in ambiguous_keys
            or item.provenance.match_method != "directed_geometry_restriction_to_carrier"
        ):
            audited_items.append(item)
            continue
        fanout_pairs = {
            candidate.road_pair
            for candidate in grouped[key]
            if candidate.road_pair is not None
        }
        updated_field_audit = dict(field_audit)
        updated_field_audit.update(
            {
                "geometry_fanout_status": "ambiguous_restriction_geometry_fanout",
                "geometry_fanout_road_pair_count": len(fanout_pairs),
                "geometry_fanout_road_pairs": _road_pair_audit(fanout_pairs),
            }
        )
        audited_items.append(
            replace(
                item,
                provenance=replace(item.provenance, field_audit=updated_field_audit),
                verification_status=VerificationStatus.MANUAL_REVIEW_REQUIRED,
                risk_flags=tuple(
                    sorted(
                        set(item.risk_flags)
                        | {"ambiguous_restriction_geometry_fanout"}
                    )
                ),
            )
        )
    return tuple(audited_items)


def audit_cross_movement_geometry_fanout(
    movement_results: tuple[tuple[T09ArmMovement, RestrictionMatchResult], ...],
    *,
    arms_by_id: dict[str, T09SwsdArm],
) -> dict[str, RestrictionMatchResult]:
    """Re-audit raw geometry fan-out across every Movement in one v2 restore run."""

    all_evidence = tuple(
        item
        for _movement, result in movement_results
        for item in result.evidence_items
    )
    audited = _mark_ambiguous_geometry_fanout(all_evidence)
    audited_by_key = {
        (item.movement_id, item.evidence_id): item
        for item in audited
    }
    rebuilt: dict[str, RestrictionMatchResult] = {}
    for movement, result in movement_results:
        if not result.evidence_items:
            rebuilt[movement.movement_id] = result
            continue
        evidence_items = tuple(
            audited_by_key.get((item.movement_id, item.evidence_id), item)
            for item in result.evidence_items
        )
        rebuilt[movement.movement_id] = _v2_condition_scoped_match_result(
            movement=movement,
            evidence_items=evidence_items,
            arms_by_id=arms_by_id,
        )
    return rebuilt


def _restriction_match_key(
    *,
    restriction: RestrictionInput,
    road_pair: RoadPair,
    strategy: RestorationStrategy,
) -> tuple[str, str, str, str]:
    condition_identity = (
        restriction.condition_identity or restriction_condition_identity(restriction)
        if strategy == RestorationStrategy.MULTI_EVIDENCE_V2
        else ""
    )
    return (
        restriction.restriction_id,
        road_pair.from_road_id,
        road_pair.to_road_id,
        condition_identity,
    )


def _restriction_input_sort_key(restriction: RestrictionInput) -> tuple[str, str, str, str]:
    return (
        restriction.restriction_id,
        restriction.in_link_id,
        restriction.out_link_id,
        restriction.condition_identity or restriction_condition_identity(restriction),
    )


def _scope_promotion_audit(
    *,
    movement: T09ArmMovement,
    evidence_items: tuple[T09EvidenceItem, ...],
    arms_by_id: dict[str, T09SwsdArm],
    same_condition_identity: bool,
    strategy: RestorationStrategy,
) -> dict[str, Any]:
    candidate_pairs = set(movement.carrier_road_pairs)
    covered_pairs = {item.road_pair for item in evidence_items if item.road_pair is not None}
    from_arm = arms_by_id.get(movement.from_arm_id)
    to_arm = arms_by_id.get(movement.to_arm_id)

    # Keep the work-in-progress v1 audit semantics untouched.  Scope promotion is
    # consumed only by v2, while the v1 compatibility path continues to use its
    # legacy restriction-only decisions.
    if strategy != RestorationStrategy.MULTI_EVIDENCE_V2:
        return _legacy_scope_promotion_audit(
            movement=movement,
            candidate_pairs=candidate_pairs,
            covered_pairs=covered_pairs,
            evidence_items=evidence_items,
            from_arm=from_arm,
            to_arm=to_arm,
            same_condition_identity=same_condition_identity,
        )

    from_role_ids = set(from_arm.approach_road_ids) if from_arm is not None else set()
    to_role_ids = set(to_arm.exit_road_ids) if to_arm is not None else set()
    candidate_from_ids = {pair.from_road_id for pair in candidate_pairs}
    candidate_to_ids = {pair.to_road_id for pair in candidate_pairs}
    expected_role_pairs = {
        RoadPair(from_road_id, to_road_id)
        for from_road_id in from_role_ids
        for to_road_id in to_role_ids
    }
    arms_match_movement = bool(from_arm and to_arm) and all(
        (
            from_arm.junction_id == movement.junction_id,
            to_arm.junction_id == movement.junction_id,
            from_arm.arm_id == movement.from_arm_id,
            to_arm.arm_id == movement.to_arm_id,
        )
    )
    same_arm_pair = arms_match_movement and all(
        pair.from_road_id in from_role_ids and pair.to_road_id in to_role_ids
        for pair in candidate_pairs
    )
    role_specific_carrier_universe_complete = all(
        (
            movement.carrier_universe_status == "available",
            bool(from_role_ids),
            bool(to_role_ids),
            candidate_from_ids == from_role_ids,
            candidate_to_ids == to_role_ids,
            candidate_pairs == expected_role_pairs,
            len(candidate_pairs) == len(movement.carrier_road_pairs),
            len(candidate_pairs) == movement.candidate_road_pair_count,
        )
    )
    condition_group_complete = covered_pairs == candidate_pairs

    ordered_evidence_items = tuple(
        sorted(
            evidence_items,
            key=lambda item: (
                item.road_pair.from_road_id if item.road_pair else "",
                item.road_pair.to_road_id if item.road_pair else "",
                item.evidence_id,
            ),
        )
    )
    match_proofs = tuple(
        _restriction_match_proof_audit(item) for item in ordered_evidence_items
    )
    proven_pairs = {
        item.road_pair
        for item, proof in zip(ordered_evidence_items, match_proofs)
        if item.road_pair is not None and proof["proof_valid"]
    }
    match_proof_complete = proven_pairs == candidate_pairs

    from_equivalence = _role_equivalence_audit(
        arm=from_arm,
        role="approach",
        role_road_ids=from_role_ids,
    )
    to_equivalence = _role_equivalence_audit(
        arm=to_arm,
        role="exit",
        role_road_ids=to_role_ids,
    )
    parallel_or_split_equivalence_explained = bool(
        from_equivalence["equivalence_proven"] and to_equivalence["equivalence_proven"]
    )

    missing_candidate_pairs = expected_role_pairs - candidate_pairs
    extra_candidate_pairs = candidate_pairs - expected_role_pairs
    uncovered_pairs = candidate_pairs - covered_pairs
    unproven_pairs = candidate_pairs - proven_pairs
    unexplained_pairs = (
        missing_candidate_pairs | extra_candidate_pairs | uncovered_pairs | unproven_pairs
    )
    unexplained_carrier_count = len(unexplained_pairs)
    promotion_gates = {
        "same_condition_identity": same_condition_identity,
        "arms_match_movement": arms_match_movement,
        "same_arm_pair": same_arm_pair,
        "role_specific_carrier_universe_complete": role_specific_carrier_universe_complete,
        "condition_group_complete": condition_group_complete,
        "parallel_or_split_equivalence_explained": parallel_or_split_equivalence_explained,
        "match_proof_complete": match_proof_complete,
        "no_unexplained_carrier": unexplained_carrier_count == 0,
    }
    failed_gates = tuple(name for name, passed in promotion_gates.items() if not passed)
    promotion_allowed = not failed_gates
    return {
        "promotion_allowed": promotion_allowed,
        **promotion_gates,
        # Compatibility alias used by existing summary consumers.
        "carrier_universe_complete": role_specific_carrier_universe_complete,
        "from_role_carrier_road_ids": tuple(sorted(from_role_ids, key=_sort_key)),
        "to_role_carrier_road_ids": tuple(sorted(to_role_ids, key=_sort_key)),
        "candidate_from_road_ids": tuple(sorted(candidate_from_ids, key=_sort_key)),
        "candidate_to_road_ids": tuple(sorted(candidate_to_ids, key=_sort_key)),
        "candidate_road_pairs": _road_pair_audit(candidate_pairs),
        "expected_role_road_pairs": _road_pair_audit(expected_role_pairs),
        "covered_road_pairs": _road_pair_audit(covered_pairs),
        "candidate_road_pair_count": len(candidate_pairs),
        "covered_road_pair_count": len(covered_pairs),
        "from_role_equivalence": from_equivalence,
        "to_role_equivalence": to_equivalence,
        "restriction_match_proofs": match_proofs,
        "missing_candidate_road_pairs": _road_pair_audit(missing_candidate_pairs),
        "extra_candidate_road_pairs": _road_pair_audit(extra_candidate_pairs),
        "uncovered_road_pairs": _road_pair_audit(uncovered_pairs),
        "unproven_match_road_pairs": _road_pair_audit(unproven_pairs),
        "unexplained_carrier_count": unexplained_carrier_count,
        "failed_gates": failed_gates,
        "reason": "all_v2_scope_promotion_gates_passed" if promotion_allowed else "v2_scope_promotion_gate_failed",
    }


def _legacy_scope_promotion_audit(
    *,
    movement: T09ArmMovement,
    candidate_pairs: set[RoadPair],
    covered_pairs: set[RoadPair],
    evidence_items: tuple[T09EvidenceItem, ...],
    from_arm: T09SwsdArm | None,
    to_arm: T09SwsdArm | None,
    same_condition_identity: bool,
) -> dict[str, Any]:
    from_arm_road_ids = _arm_road_ids(from_arm, role="approach")
    to_arm_road_ids = _arm_road_ids(to_arm, role="exit")
    same_arm_pair = bool(from_arm_road_ids and to_arm_road_ids) and all(
        pair.from_road_id in from_arm_road_ids and pair.to_road_id in to_arm_road_ids
        for pair in candidate_pairs
    )
    candidate_from_ids = {pair.from_road_id for pair in candidate_pairs}
    candidate_to_ids = {pair.to_road_id for pair in candidate_pairs}
    expected_cross_product = {
        RoadPair(from_road_id, to_road_id)
        for from_road_id in candidate_from_ids
        for to_road_id in candidate_to_ids
    }
    carrier_universe_complete = (
        bool(candidate_pairs)
        and len(candidate_pairs) == movement.candidate_road_pair_count
        and candidate_pairs == expected_cross_product
    )
    condition_group_complete = covered_pairs == candidate_pairs
    match_proof_complete = all(
        item.provenance.match_method
        in {"inLinkID_to_outLinkID", "directed_geometry_restriction_to_carrier"}
        for item in evidence_items
    )
    unexplained_carrier_count = len(candidate_pairs - covered_pairs)
    promotion_allowed = all(
        (
            same_condition_identity,
            same_arm_pair,
            carrier_universe_complete,
            condition_group_complete,
            match_proof_complete,
            unexplained_carrier_count == 0,
        )
    )
    return {
        "promotion_allowed": promotion_allowed,
        "same_condition_identity": same_condition_identity,
        "same_arm_pair": same_arm_pair,
        "carrier_universe_complete": carrier_universe_complete,
        "parallel_or_split_equivalence_explained": carrier_universe_complete and same_arm_pair,
        "condition_group_complete": condition_group_complete,
        "match_proof_complete": match_proof_complete,
        "unexplained_carrier_count": unexplained_carrier_count,
        "candidate_road_pair_count": len(candidate_pairs),
        "covered_road_pair_count": len(covered_pairs),
    }


def _restriction_match_proof_audit(item: T09EvidenceItem) -> dict[str, Any]:
    road_pair = item.road_pair
    method = item.provenance.match_method
    field_audit = item.provenance.field_audit
    if road_pair is None:
        return {
            "evidence_id": item.evidence_id,
            "match_method": method,
            "proof_type": "missing_road_pair",
            "proof_valid": False,
        }

    exact_identity_valid = (
        method == "inLinkID_to_outLinkID"
        and str(field_audit.get("inLinkID", "")) == road_pair.from_road_id
        and str(field_audit.get("outLinkID", "")) == road_pair.to_road_id
    )
    from_geometry = field_audit.get("from_geometry_match")
    to_geometry = field_audit.get("to_geometry_match")
    ambiguous_geometry_fanout = (
        "ambiguous_restriction_geometry_fanout" in item.risk_flags
        or int(field_audit.get("geometry_fanout_road_pair_count", 0) or 0) > 1
    )
    directed_geometry_valid = (
        method == "directed_geometry_restriction_to_carrier"
        and not ambiguous_geometry_fanout
        and str(field_audit.get("from_swsd_road_id", "")) == road_pair.from_road_id
        and str(field_audit.get("to_swsd_road_id", "")) == road_pair.to_road_id
        and _directed_geometry_component_valid(from_geometry, road_pair.from_road_id)
        and _directed_geometry_component_valid(to_geometry, road_pair.to_road_id)
        and _bounded_number(
            field_audit.get("inside_endpoint_distance_m"),
            maximum=MAX_RESTRICTION_INSIDE_DISTANCE_M,
        )
    )
    proof_type = (
        "exact_link_identity"
        if exact_identity_valid
        else "directed_geometry_match"
        if directed_geometry_valid
        else "unproven"
    )
    return {
        "evidence_id": item.evidence_id,
        "road_pair": {
            "from_road_id": road_pair.from_road_id,
            "to_road_id": road_pair.to_road_id,
        },
        "match_method": method,
        "proof_type": proof_type,
        "exact_link_identity_valid": exact_identity_valid,
        "directed_geometry_match_valid": directed_geometry_valid,
        "ambiguous_geometry_fanout": ambiguous_geometry_fanout,
        "proof_valid": exact_identity_valid or directed_geometry_valid,
    }


def _directed_geometry_component_valid(value: Any, expected_road_id: str) -> bool:
    if not isinstance(value, dict):
        return False
    return all(
        (
            str(value.get("road_id", "")) == expected_road_id,
            _bounded_number(value.get("distance_m"), maximum=MAX_GEOMETRY_MATCH_DISTANCE_M),
            _bounded_number(value.get("direction_delta_deg"), maximum=MAX_DIRECTION_DELTA_DEG),
            str(value.get("method", "")).startswith("directed_geometry_"),
        )
    )


def _bounded_number(value: Any, *, maximum: float) -> bool:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return 0.0 <= number <= maximum


def _role_equivalence_audit(
    *,
    arm: T09SwsdArm | None,
    role: str,
    role_road_ids: set[str],
) -> dict[str, Any]:
    if arm is None or not role_road_ids:
        return {
            "role": role,
            "role_road_ids": tuple(),
            "proof_type": "missing_role_carrier_universe",
            "equivalence_proven": False,
            "failed_gates": ("arm_and_role_universe_available",),
        }
    formal_t01_membership_complete = bool(arm.t01_segment_ids) and (
        arm.segment_membership_status in {"consistent", "t01_only"}
        and "segment_membership_conflict" not in arm.risk_flags
    )
    audit_refs = set(arm.audit_refs)
    expected_seed_ref = "seed_road_ids=" + ",".join(sorted(arm.seed_road_ids, key=_sort_key))
    common_gates = {
        "built_arm": arm.build_status == "built",
        "role_roads_are_seed_carriers": role_road_ids <= set(arm.seed_road_ids),
        "directional_grouping_audited": "grouping=segment_local_direction" in audit_refs,
        "seed_universe_audited": expected_seed_ref in audit_refs,
        "direction_geometry_available": arm.angle_deg is not None,
    }
    if len(role_road_ids) == 1:
        gates = {
            **common_gates,
            "formal_t01_membership_complete": formal_t01_membership_complete,
        }
        failed_gates = tuple(name for name, passed in gates.items() if not passed)
        return {
            "role": role,
            "role_road_ids": tuple(sorted(role_road_ids, key=_sort_key)),
            "proof_type": "singleton_role_carrier",
            "equivalence_proven": not failed_gates,
            "t01_segment_ids": tuple(sorted(arm.t01_segment_ids, key=_sort_key)),
            "segment_membership_status": arm.segment_membership_status,
            "formal_t01_membership_complete": formal_t01_membership_complete,
            "gates": gates,
            "failed_gates": failed_gates,
        }

    parallel_role_ids = role_road_ids.intersection(arm.parallel_branch_road_ids)
    non_parallel_role_ids = role_road_ids - parallel_role_ids
    explicit_parallel_equivalence = (
        len(role_road_ids) > 1
        and role_road_ids == parallel_role_ids
        and "parallel_branch_proof=same_role_same_terminal_directional_bundle" in audit_refs
        and not non_parallel_role_ids
    )
    shared_segment_split_equivalence = (
        formal_t01_membership_complete
        and len(arm.t01_segment_ids) == 1
    )
    carrier_equivalence_source_available = (
        explicit_parallel_equivalence or shared_segment_split_equivalence
    )
    gates = {
        **common_gates,
        "carrier_equivalence_source_available": carrier_equivalence_source_available,
    }
    failed_gates = tuple(name for name, passed in gates.items() if not passed)
    proof_type = (
        "explicit_parallel_branch"
        if explicit_parallel_equivalence
        else "shared_segment_directional_split"
        if shared_segment_split_equivalence
        else "unproven_multi_road_equivalence"
    )
    return {
        "role": role,
        "role_road_ids": tuple(sorted(role_road_ids, key=_sort_key)),
        "proof_type": proof_type,
        "equivalence_proven": not failed_gates,
        "t01_segment_ids": tuple(sorted(arm.t01_segment_ids, key=_sort_key)),
        "segment_membership_status": arm.segment_membership_status,
        "legacy_segment_ids": tuple(sorted(arm.segment_ids, key=_sort_key)),
        "parallel_branch_road_ids": tuple(sorted(parallel_role_ids, key=_sort_key)),
        "explicit_parallel_equivalence": explicit_parallel_equivalence,
        "formal_t01_membership_complete": formal_t01_membership_complete,
        "shared_segment_split_equivalence": shared_segment_split_equivalence,
        "angle_deg": arm.angle_deg,
        "audit_refs": tuple(sorted(audit_refs)),
        "risk_flags": tuple(sorted(arm.risk_flags)),
        "gates": gates,
        "failed_gates": failed_gates,
    }


def _road_pair_audit(pairs: set[RoadPair]) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "from_road_id": pair.from_road_id,
            "to_road_id": pair.to_road_id,
        }
        for pair in sorted(
            pairs,
            key=lambda item: (_sort_key(item.from_road_id), _sort_key(item.to_road_id)),
        )
    )


def _sort_key(value: str) -> tuple[int, int | str]:
    text = str(value)
    return (0, int(text)) if text.isdigit() else (1, text)


def _arm_road_ids(arm: T09SwsdArm | None, *, role: str) -> set[str]:
    if arm is None:
        return set()
    if role == "approach":
        return set(
            arm.approach_road_ids
            + arm.inbound_road_ids
            + arm.bidirectional_road_ids
            + arm.seed_road_ids
            + arm.trunk_road_ids
            + arm.connector_road_ids
        )
    return set(
        arm.exit_road_ids
        + arm.outbound_road_ids
        + arm.bidirectional_road_ids
        + arm.seed_road_ids
        + arm.trunk_road_ids
        + arm.connector_road_ids
    )


def _partial_basis(*, movement: T09ArmMovement, evidence_items: tuple[T09EvidenceItem, ...]) -> str:
    candidate_pairs = set(movement.carrier_road_pairs)
    covered_pairs = {item.road_pair for item in evidence_items if item.road_pair is not None}
    if not candidate_pairs or not covered_pairs:
        return "carrier_subset_unresolved"
    if covered_pairs == candidate_pairs:
        return "not_applicable"

    candidate_from = {pair.from_road_id for pair in candidate_pairs}
    candidate_to = {pair.to_road_id for pair in candidate_pairs}
    covered_from = {pair.from_road_id for pair in covered_pairs}
    covered_to = {pair.to_road_id for pair in covered_pairs}
    if covered_from != candidate_from and covered_to == candidate_to:
        return "entry_arm_subset"
    if covered_from == candidate_from and covered_to != candidate_to:
        return "exit_arm_subset"
    return "carrier_subset_unresolved"


def _match_restriction_geometry(
    *,
    movement: T09ArmMovement,
    road_pair: RoadPair,
    restriction: RestrictionInput,
    roads_by_id: dict[str, SWSDRoadInput],
    road_geometries: dict[str, BaseGeometry],
    arms_by_id: dict[str, T09SwsdArm],
) -> tuple[DirectedGeometryMatch, DirectedGeometryMatch, float] | None:
    from_arm = arms_by_id.get(movement.from_arm_id)
    to_arm = arms_by_id.get(movement.to_arm_id)
    from_road = roads_by_id.get(road_pair.from_road_id)
    to_road = roads_by_id.get(road_pair.to_road_id)
    if from_arm is None or to_arm is None or from_road is None or to_road is None:
        return None
    from_match = match_restriction_endpoint_to_road(
        restriction_geometry=restriction.geometry,
        road=from_road,
        road_geometry=road_geometries.get(road_pair.from_road_id),
        member_node_ids=from_arm.member_node_ids,
        endpoint="start",
        road_role="approach",
    )
    if from_match is None:
        return None
    to_match = match_restriction_endpoint_to_road(
        restriction_geometry=restriction.geometry,
        road=to_road,
        road_geometry=road_geometries.get(road_pair.to_road_id),
        member_node_ids=to_arm.member_node_ids,
        endpoint="end",
        road_role="exit",
    )
    if to_match is None:
        return None
    inside_distance = restriction_inside_endpoint_distance(
        restriction_geometry=restriction.geometry,
        from_road=from_road,
        from_road_geometry=road_geometries.get(road_pair.from_road_id),
        from_member_node_ids=from_arm.member_node_ids,
        to_road=to_road,
        to_road_geometry=road_geometries.get(road_pair.to_road_id),
        to_member_node_ids=to_arm.member_node_ids,
    )
    if inside_distance > MAX_RESTRICTION_INSIDE_DISTANCE_M:
        return None
    return from_match, to_match, inside_distance


def _restriction_evidence(
    *,
    movement: T09ArmMovement,
    restriction: RestrictionInput,
    road_pair: RoadPair,
    evidence_id: str,
    evidence_status: str,
    match_method: str,
    confidence: float,
    field_audit: dict[str, object],
    reason: str,
) -> T09EvidenceItem:
    condition_type = restriction.condition_type or _case_get(
        restriction.properties,
        ("CondType", "condtype", "condition_type"),
    )
    condition_payload = dict(restriction.condition_payload or restriction.properties)
    condition_identity = restriction.condition_identity or restriction_condition_identity(restriction)
    field_audit = dict(field_audit)
    if condition_payload or condition_type is not None:
        field_audit.update(
            {
                "condition_type": None if condition_type is None else str(condition_type),
                "condition_identity": condition_identity,
                "condition_semantics_status": restriction.condition_semantics_status,
                "raw_condition_payload": condition_payload,
            }
        )
    return T09EvidenceItem(
        evidence_id=evidence_id,
        evidence_type=EvidenceType.RESTRICTION,
        junction_id=movement.junction_id,
        movement_id=movement.movement_id,
        road_pair=road_pair,
        evidence_status=evidence_status,
        prohibition_reason=ProhibitionReason.EXPLICIT_RESTRICTION,
        inference_level=InferenceLevel.EXPLICIT,
        confidence=confidence,
        provenance=EvidenceProvenance(
            source_type="restriction",
            source_id=restriction.restriction_id,
            matched_object_ids=(
                movement.movement_id,
                road_pair.from_road_id,
                road_pair.to_road_id,
                restriction.in_link_id,
                restriction.out_link_id,
            ),
            match_method=match_method,
            field_audit=field_audit,
            reason=reason,
        ),
        supports_prohibition=True,
        decision_status=DecisionStatus.PROHIBITED,
        decision_scope=RuleScope.ROAD_TO_ROAD,
        evidence_priority=EvidencePriority.RESTRICTION,
        verification_status=VerificationStatus.VERIFIED_SWSD,
        from_road_ids=(road_pair.from_road_id,),
        to_road_ids=(road_pair.to_road_id,),
        condition_type=None if condition_type is None else str(condition_type),
        condition_payload=condition_payload,
        condition_identity=condition_identity,
        condition_semantics_status=restriction.condition_semantics_status,
    )


_CONDITION_IDENTITY_EXCLUDED_FIELDS = {
    "fid",
    "geom",
    "geometry",
    "id",
    "restriction_id",
    "condid",
    "cond_id",
    "inlinkid",
    "outlinkid",
    "in_link_id",
    "out_link_id",
}


def restriction_condition_identity(restriction: RestrictionInput) -> str:
    """Return a stable raw-condition identity without folding Road-Pair identity into it."""

    source = dict(restriction.condition_payload or restriction.properties)
    condition_payload = {
        str(key): _json_safe(value)
        for key, value in source.items()
        if normalize_field_name(str(key).strip()) not in _CONDITION_IDENTITY_EXCLUDED_FIELDS
    }
    condition_type = restriction.condition_type or _case_get(
        restriction.properties,
        ("CondType", "condtype", "condition_type"),
    )
    canonical = json.dumps(
        {
            "condition_type": None if condition_type is None else str(condition_type),
            "condition_payload": condition_payload,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return "condition:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def _case_get(properties: dict[str, Any], candidates: tuple[str, ...]) -> Any:
    return get_case_insensitive_property(properties, candidates)


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in {float("inf"), float("-inf")} else str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    return str(value)
