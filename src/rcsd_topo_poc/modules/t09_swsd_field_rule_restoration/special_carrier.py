from __future__ import annotations

from dataclasses import dataclass

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    DecisionStatus,
    EvidenceProvenance,
    EvidencePriority,
    EvidenceType,
    InferenceLevel,
    ProhibitionReason,
    RestorationStrategy,
    RoadAttributes,
    RuleScope,
    T09EvidenceItem,
    T09SwsdArm,
    VerificationStatus,
)


ADVANCE_RIGHT_FORMWAY_BIT = 128
ADVANCE_LEFT_FORMWAY_BIT = 256


@dataclass(frozen=True)
class SpecialCarrierRoadProfile:
    road_id: str
    dedicated_movement_type: str
    formway: int
    kind: str | None
    arm_role: str
    carrier_type: str
    classification_status: DecisionStatus
    verification_status: VerificationStatus
    risk_flags: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class SpecialCarrierArmProfile:
    junction_id: str
    arm_id: str
    road_profiles: tuple[SpecialCarrierRoadProfile, ...]
    advance_left_road_ids: tuple[str, ...]
    advance_right_road_ids: tuple[str, ...]
    core_road_ids: tuple[str, ...]
    risk_flags: tuple[str, ...] = tuple()


@dataclass(frozen=True)
class SpecialCarrierDecision:
    road_id: str
    movement_type: str
    evidence_status: str
    decision_status: DecisionStatus
    decision_scope: RuleScope
    evidence_priority: EvidencePriority
    inference_level: InferenceLevel
    verification_status: VerificationStatus
    supports_prohibition: bool
    carrier_type: str
    risk_flags: tuple[str, ...] = tuple()
    source_carrier_road_ids: tuple[str, ...] = tuple()


def detect_special_carrier_evidence(
    *,
    junction_id: str,
    arm_id: str,
    roads: tuple[RoadAttributes, ...],
    evidence_prefix: str = "special_carrier",
    strategy_version: str | RestorationStrategy = RestorationStrategy.RESTRICTION_ONLY_V1,
    arm: T09SwsdArm | None = None,
) -> tuple[T09EvidenceItem, ...]:
    strategy = RestorationStrategy(strategy_version)
    if strategy == RestorationStrategy.RESTRICTION_ONLY_V1:
        return _detect_v1_special_carrier_evidence(
            junction_id=junction_id,
            arm_id=arm_id,
            roads=roads,
            evidence_prefix=evidence_prefix,
        )

    profile = build_special_carrier_arm_profile(
        arm=arm or T09SwsdArm(junction_id=junction_id, arm_id=arm_id),
        roads=roads,
    )
    attributes_by_road = {road.road_id: road for road in roads}
    evidence_items: list[T09EvidenceItem] = []
    for road_profile in profile.road_profiles:
        direction = road_profile.dedicated_movement_type
        formway_bit = (
            ADVANCE_RIGHT_FORMWAY_BIT
            if direction == "right"
            else ADVANCE_LEFT_FORMWAY_BIT
        )
        road = attributes_by_road.get(
            road_profile.road_id,
            RoadAttributes(road_id=road_profile.road_id, formway=formway_bit),
        )
        evidence_items.append(
            T09EvidenceItem(
                evidence_id=f"{evidence_prefix}:{arm_id}:{road.road_id}:{direction}",
                evidence_type=EvidenceType.SPECIAL_CARRIER,
                junction_id=junction_id,
                movement_id=None,
                road_pair=None,
                evidence_status=f"advance_{direction}_special_carrier_default_support",
                prohibition_reason=ProhibitionReason.SPECIAL_CARRIER_DISPLACEMENT,
                inference_level=InferenceLevel.WEAK_DERIVED,
                confidence=0.6,
                provenance=EvidenceProvenance(
                    source_type="road",
                    source_id=road.road_id,
                    matched_object_ids=(arm_id, road.road_id),
                    match_method=f"formway_bit_{formway_bit}",
                    field_audit={
                        "kind": road.kind,
                        "kind_tokens": _kind_tokens(road.kind),
                        "formway": road.formway,
                        "formway_bit": formway_bit,
                        "arm_role": road_profile.arm_role,
                        "carrier_type": road_profile.carrier_type,
                    },
                    reason=(
                        "formway identifies a special carrier candidate; "
                        "the default dedicated direction is weak supporting evidence"
                    ),
                ),
                supports_prohibition=False,
                risk_flags=road_profile.risk_flags,
                decision_status=DecisionStatus.SUPPORTED,
                decision_scope=RuleScope.SPECIAL_CARRIER,
                evidence_priority=EvidencePriority.SPECIAL_CARRIER,
                verification_status=VerificationStatus.VERIFIED_SWSD,
                from_road_ids=(road.road_id,),
            )
        )
    return tuple(evidence_items)


def build_special_carrier_arm_profile(
    *,
    arm: T09SwsdArm,
    roads: tuple[RoadAttributes, ...],
) -> SpecialCarrierArmProfile:
    """Build an Arm-scoped profile using formway as the only v2 trigger.

    ``kind`` is retained as raw/audit context.  It may refine an explicitly
    unverified subtype label, but it never creates a special carrier profile.
    """

    attributes_by_road = {road.road_id: road for road in roads}
    left_ids = set(arm.advance_left_road_ids)
    right_ids = set(arm.advance_right_road_ids)
    for road in roads:
        if road.formway & ADVANCE_LEFT_FORMWAY_BIT:
            left_ids.add(road.road_id)
        if road.formway & ADVANCE_RIGHT_FORMWAY_BIT:
            right_ids.add(road.road_id)

    road_profiles: list[SpecialCarrierRoadProfile] = []
    for road_id, direction, formway_bit in (
        *((road_id, "left", ADVANCE_LEFT_FORMWAY_BIT) for road_id in left_ids),
        *((road_id, "right", ADVANCE_RIGHT_FORMWAY_BIT) for road_id in right_ids),
    ):
        road = attributes_by_road.get(
            road_id,
            RoadAttributes(road_id=road_id, formway=formway_bit),
        )
        arm_role = _arm_road_role(arm, road_id)
        carrier_type, classification_status, verification_status, risk_flags = (
            _classify_special_carrier(
                direction=direction,
                arm_role=arm_role,
                kind=road.kind,
            )
        )
        if road_id in left_ids and road_id in right_ids:
            risk_flags = tuple(sorted(set(risk_flags) | {"multiple_special_carrier_formway_bits"}))
        road_profiles.append(
            SpecialCarrierRoadProfile(
                road_id=road_id,
                dedicated_movement_type=direction,
                formway=road.formway,
                kind=road.kind,
                arm_role=arm_role,
                carrier_type=carrier_type,
                classification_status=classification_status,
                verification_status=verification_status,
                risk_flags=risk_flags,
            )
        )

    road_profiles.sort(
        key=lambda item: (_sort_key(item.road_id), item.dedicated_movement_type)
    )
    special_ids = left_ids | right_ids
    core_ids = (
        set(arm.trunk_road_ids)
        | set(arm.approach_road_ids)
        | set(arm.exit_road_ids)
    ) - special_ids
    profile_risks = tuple(
        sorted({flag for item in road_profiles for flag in item.risk_flags})
    )
    return SpecialCarrierArmProfile(
        junction_id=arm.junction_id,
        arm_id=arm.arm_id,
        road_profiles=tuple(road_profiles),
        advance_left_road_ids=tuple(sorted(left_ids, key=_sort_key)),
        advance_right_road_ids=tuple(sorted(right_ids, key=_sort_key)),
        core_road_ids=tuple(sorted(core_ids, key=_sort_key)),
        risk_flags=profile_risks,
    )


def evaluate_special_carrier_decision(
    profile: SpecialCarrierArmProfile,
    *,
    road_id: str,
    movement_type: str,
) -> SpecialCarrierDecision | None:
    """Return a v2 weak decision without promoting it to Arm scope."""

    normalized_movement = _normalize_movement_type(movement_type)
    road_profiles = tuple(
        item for item in profile.road_profiles if item.road_id == road_id
    )
    matching_profile = next(
        (
            item
            for item in road_profiles
            if item.dedicated_movement_type == normalized_movement
        ),
        None,
    )
    if matching_profile is not None:
        return SpecialCarrierDecision(
            road_id=road_id,
            movement_type=movement_type,
            evidence_status=(
                f"advance_{matching_profile.dedicated_movement_type}_"
                "special_carrier_default_support"
            ),
            decision_status=DecisionStatus.SUPPORTED,
            decision_scope=RuleScope.SPECIAL_CARRIER,
            evidence_priority=EvidencePriority.SPECIAL_CARRIER,
            inference_level=InferenceLevel.WEAK_DERIVED,
            verification_status=VerificationStatus.VERIFIED_SWSD,
            supports_prohibition=False,
            carrier_type=matching_profile.carrier_type,
            risk_flags=matching_profile.risk_flags,
            source_carrier_road_ids=(matching_profile.road_id,),
        )
    if road_profiles:
        carrier_types = "+".join(
            sorted({item.carrier_type for item in road_profiles})
        )
        risk_flags = {
            flag for item in road_profiles for flag in item.risk_flags
        }
        risk_flags.add("weak_special_carrier_direction_exclusion")
        return SpecialCarrierDecision(
            road_id=road_id,
            movement_type=movement_type,
            evidence_status="special_carrier_other_direction_weak_exclusion_candidate",
            decision_status=DecisionStatus.PROHIBITED,
            decision_scope=RuleScope.SPECIAL_CARRIER,
            evidence_priority=EvidencePriority.SPECIAL_CARRIER,
            inference_level=InferenceLevel.WEAK_DERIVED,
            verification_status=(
                VerificationStatus.UNVERIFIED_DUE_TO_MISSING_FRCSD_LANEINFO
            ),
            supports_prohibition=True,
            carrier_type=carrier_types,
            risk_flags=tuple(sorted(risk_flags)),
            source_carrier_road_ids=tuple(
                sorted({item.road_id for item in road_profiles}, key=_sort_key)
            ),
        )

    if road_id not in profile.core_road_ids:
        return None
    direction_profiles = tuple(
        item
        for item in profile.road_profiles
        if item.dedicated_movement_type == normalized_movement
    )
    if not direction_profiles:
        return None

    displacement_candidates = tuple(
        item
        for item in direction_profiles
        if item.arm_role in {"segment_connector", "parallel_branch"}
    )
    if displacement_candidates:
        risk_flags = {
            flag for item in displacement_candidates for flag in item.risk_flags
        }
        risk_flags.update(
            {
                "core_junction_displacement_weak_candidate",
                "special_carrier_topology_subtype_unverified",
            }
        )
        return SpecialCarrierDecision(
            road_id=road_id,
            movement_type=movement_type,
            evidence_status="core_junction_displacement_weak_candidate",
            decision_status=DecisionStatus.UNVERIFIED,
            decision_scope=RuleScope.CORE_JUNCTION_DISPLACEMENT,
            evidence_priority=EvidencePriority.SPECIAL_CARRIER,
            inference_level=InferenceLevel.WEAK_DERIVED,
            verification_status=(
                VerificationStatus.UNVERIFIED_DUE_TO_MISSING_FRCSD_LANEINFO
            ),
            supports_prohibition=False,
            carrier_type="bypass_or_auxiliary_unverified",
            risk_flags=tuple(sorted(risk_flags)),
            source_carrier_road_ids=tuple(
                sorted({item.road_id for item in displacement_candidates}, key=_sort_key)
            ),
        )

    incident_profiles = tuple(
        item for item in direction_profiles if item.arm_role == "incident_seed"
    )
    if incident_profiles:
        return SpecialCarrierDecision(
            road_id=road_id,
            movement_type=movement_type,
            evidence_status="pre_junction_carrier_does_not_prove_core_displacement",
            decision_status=DecisionStatus.UNKNOWN,
            decision_scope=RuleScope.CORE_JUNCTION_DISPLACEMENT,
            evidence_priority=EvidencePriority.SPECIAL_CARRIER,
            inference_level=InferenceLevel.UNKNOWN,
            verification_status=VerificationStatus.MANUAL_REVIEW_REQUIRED,
            supports_prohibition=False,
            carrier_type="pre_junction_through_core",
            risk_flags=("core_displacement_not_proven",),
            source_carrier_road_ids=tuple(
                sorted({item.road_id for item in incident_profiles}, key=_sort_key)
            ),
        )

    return SpecialCarrierDecision(
        road_id=road_id,
        movement_type=movement_type,
        evidence_status="special_carrier_topology_subtype_manual_review",
        decision_status=DecisionStatus.MANUAL_REVIEW_REQUIRED,
        decision_scope=RuleScope.CORE_JUNCTION_DISPLACEMENT,
        evidence_priority=EvidencePriority.SPECIAL_CARRIER,
        inference_level=InferenceLevel.UNKNOWN,
        verification_status=VerificationStatus.MANUAL_REVIEW_REQUIRED,
        supports_prohibition=False,
        carrier_type="unclassified_special_carrier",
        risk_flags=("special_carrier_topology_subtype_unverified",),
        source_carrier_road_ids=tuple(
            sorted({item.road_id for item in direction_profiles}, key=_sort_key)
        ),
    )


def _detect_v1_special_carrier_evidence(
    *,
    junction_id: str,
    arm_id: str,
    roads: tuple[RoadAttributes, ...],
    evidence_prefix: str,
) -> tuple[T09EvidenceItem, ...]:
    evidence_items: list[T09EvidenceItem] = []
    for index, road in enumerate(roads, start=1):
        kind_tokens = _kind_tokens(road.kind)
        has_auxiliary = _has_kind_suffix(kind_tokens, "0a")
        has_right_turn = _has_kind_suffix(kind_tokens, "12")
        status: str | None = None
        if road.formway & 256:
            status = "advance_left_carrier_exists"
        elif has_right_turn and has_auxiliary:
            status = "auxiliary_right_turn_carrier_exists"
        elif has_right_turn and not has_auxiliary:
            status = "pre_junction_non_aux_advance_right_relation"
        if status is None:
            continue
        evidence_items.append(
            T09EvidenceItem(
                evidence_id=f"{evidence_prefix}:{arm_id}:{index}",
                evidence_type=EvidenceType.SPECIAL_CARRIER,
                junction_id=junction_id,
                movement_id=None,
                road_pair=None,
                evidence_status=status,
                prohibition_reason=ProhibitionReason.SPECIAL_CARRIER_DISPLACEMENT,
                inference_level=InferenceLevel.EXPLICIT,
                confidence=0.8,
                provenance=EvidenceProvenance(
                    source_type="road",
                    source_id=road.road_id,
                    matched_object_ids=(arm_id, road.road_id),
                    match_method="formway_or_kind_token",
                    field_audit={"kind": road.kind, "formway": road.formway},
                    reason="special carrier is recorded as carrier/displacement evidence only",
                ),
                supports_prohibition=False,
            )
        )
    return tuple(evidence_items)


def _arm_road_role(arm: T09SwsdArm, road_id: str) -> str:
    if road_id in arm.parallel_branch_road_ids:
        return "parallel_branch"
    if road_id in arm.seed_road_ids:
        return "incident_seed"
    if road_id in arm.connector_road_ids:
        return "segment_connector"
    if road_id in arm.internal_road_ids:
        return "junction_internal"
    if road_id in arm.trunk_road_ids:
        return "trunk"
    return "unclassified"


def _classify_special_carrier(
    *,
    direction: str,
    arm_role: str,
    kind: str | None,
) -> tuple[str, DecisionStatus, VerificationStatus, tuple[str, ...]]:
    kind_tokens = _kind_tokens(kind)
    auxiliary_hint = direction == "right" and _has_kind_suffix(kind_tokens, "0a")
    risk_flags: set[str] = set()
    if auxiliary_hint:
        risk_flags.add("kind_auxiliary_hint_not_decision_source")

    if arm_role == "incident_seed":
        return (
            "pre_junction_through_core",
            DecisionStatus.SUPPORTED,
            VerificationStatus.VERIFIED_SWSD,
            tuple(sorted(risk_flags)),
        )
    if arm_role == "segment_connector":
        risk_flags.add("special_carrier_topology_subtype_unverified")
        return (
            "auxiliary_right_turn_unverified"
            if auxiliary_hint
            else "bypass_core_junction_candidate",
            DecisionStatus.MANUAL_REVIEW_REQUIRED,
            VerificationStatus.MANUAL_REVIEW_REQUIRED,
            tuple(sorted(risk_flags)),
        )
    if arm_role == "parallel_branch":
        risk_flags.add("special_carrier_topology_subtype_unverified")
        return (
            "auxiliary_or_bypass_candidate",
            DecisionStatus.MANUAL_REVIEW_REQUIRED,
            VerificationStatus.MANUAL_REVIEW_REQUIRED,
            tuple(sorted(risk_flags)),
        )
    if arm_role == "junction_internal":
        risk_flags.add("special_carrier_inside_core_requires_review")
        return (
            "core_junction_internal_candidate",
            DecisionStatus.MANUAL_REVIEW_REQUIRED,
            VerificationStatus.MANUAL_REVIEW_REQUIRED,
            tuple(sorted(risk_flags)),
        )

    risk_flags.add("special_carrier_arm_role_unclassified")
    return (
        "unclassified_special_carrier",
        DecisionStatus.MANUAL_REVIEW_REQUIRED,
        VerificationStatus.MANUAL_REVIEW_REQUIRED,
        tuple(sorted(risk_flags)),
    )


def _normalize_movement_type(movement_type: str) -> str:
    normalized = movement_type.strip().lower().replace("-", "_")
    if normalized in {"left", "slight_left"}:
        return "left"
    if normalized in {"right", "slight_right"}:
        return "right"
    return normalized


def _kind_tokens(kind: str | None) -> tuple[str, ...]:
    if kind is None:
        return tuple()
    return tuple(token.strip().lower() for token in str(kind).split("|") if token.strip())


def _has_kind_suffix(tokens: tuple[str, ...], suffix: str) -> bool:
    return any(token.endswith(suffix.lower()) for token in tokens)


def _sort_key(value: str) -> tuple[int, object]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)
