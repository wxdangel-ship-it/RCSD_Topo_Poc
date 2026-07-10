from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arrow_codes import (
    arrow_tokens_support_movement,
    parse_arrow_code,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.geometry_match import (
    DirectedGeometryMatch,
    approach_arrow_endpoint_distance,
    match_arrow_to_approach_road,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    ArrowInput,
    DecisionStatus,
    EvidenceProvenance,
    EvidencePriority,
    EvidenceType,
    InferenceLevel,
    MovementApplicability,
    ProhibitionReason,
    ProhibitionStatus,
    RuleScope,
    SWSDRoadInput,
    T09ArmMovement,
    T09EvidenceItem,
    T09SwsdArm,
    VerificationStatus,
)


SUPPORTED_ARROW_MOVEMENT_TYPES = frozenset(
    {
        "straight",
        "left",
        "right",
        "uturn",
        "slight_left",
        "slight_right",
    }
)


@dataclass(frozen=True)
class ArrowEvaluationResult:
    evidence_items: tuple[T09EvidenceItem, ...]
    prohibition_status: ProhibitionStatus
    prohibition_reason: ProhibitionReason
    confidence: float
    arrow_supports_movement: bool = False
    arrow_direction_status: str = "no_arrow_evidence"
    arrow_lane_summary: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RoadArrowDecision:
    road_id: str
    movement_id: str
    movement_type: str
    decision_status: DecisionStatus
    evidence_items: tuple[T09EvidenceItem, ...]
    evidence_ids: tuple[str, ...]
    confidence: float
    direction_tokens: tuple[str, ...]
    reason: str
    risk_flags: tuple[str, ...] = tuple()
    source_arrow_ids: tuple[str, ...] = tuple()
    lane_summary: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class _MatchedArrow:
    road_id: str
    arrow: ArrowInput
    match_method: str
    confidence: float
    distance_m: float | None = None
    direction_delta_deg: float | None = None
    endpoint_distance_m: float | None = None

    def audit(self) -> dict[str, object]:
        audit: dict[str, object] = {
            "swsd_approach_road_id": self.road_id,
            "raw_arrow_linkid": self.arrow.road_id,
            "arrow_id": self.arrow.arrow_id,
            "match_method": self.match_method,
            "confidence": round(self.confidence, 3),
        }
        if self.distance_m is not None:
            audit["distance_m"] = round(self.distance_m, 3)
        if self.direction_delta_deg is not None:
            audit["direction_delta_deg"] = round(self.direction_delta_deg, 3)
        if self.endpoint_distance_m is not None:
            audit["endpoint_distance_m"] = round(self.endpoint_distance_m, 3)
        return audit


def evaluate_road_arrow_directions(
    movement: T09ArmMovement,
    arrows: tuple[ArrowInput, ...],
    *,
    evidence_prefix: str = "laneinfo",
    roads_by_id: dict[str, SWSDRoadInput] | None = None,
    road_geometries: dict[str, BaseGeometry] | None = None,
    arms_by_id: dict[str, T09SwsdArm] | None = None,
) -> tuple[RoadArrowDecision, ...]:
    """Evaluate v2 Laneinfo once per approach Road without widening it to Arm scope."""

    roads_by_id = roads_by_id or {}
    road_geometries = road_geometries or {}
    arms_by_id = arms_by_id or {}
    approach_road_ids = tuple(sorted({pair.from_road_id for pair in movement.carrier_road_pairs}))
    matched_by_road = _match_all_arrows_to_approach_roads(
        movement=movement,
        approach_road_ids=approach_road_ids,
        arrows=arrows,
        roads_by_id=roads_by_id,
        road_geometries=road_geometries,
        arms_by_id=arms_by_id,
    )
    decisions: list[RoadArrowDecision] = []
    for road_id in approach_road_ids:
        matched_arrows = matched_by_road.get(road_id, tuple())
        decisions.append(
            _evaluate_one_road_arrow_direction(
                movement=movement,
                road_id=road_id,
                matched_arrows=matched_arrows,
                evidence_prefix=evidence_prefix,
            )
        )
    return tuple(decisions)


def _evaluate_one_road_arrow_direction(
    *,
    movement: T09ArmMovement,
    road_id: str,
    matched_arrows: tuple[_MatchedArrow, ...],
    evidence_prefix: str,
) -> RoadArrowDecision:
    movement_type = movement.movement_type.strip().lower()
    source_arrow_ids = tuple(sorted({item.arrow.arrow_id for item in matched_arrows}))
    lane_summary = _road_arrow_lane_summary(
        movement_type=movement_type,
        matched_arrows=matched_arrows,
    )
    if movement.movement_applicability != MovementApplicability.APPLICABLE:
        return RoadArrowDecision(
            road_id=road_id,
            movement_id=movement.movement_id,
            movement_type=movement.movement_type,
            decision_status=DecisionStatus.NOT_APPLICABLE,
            evidence_items=tuple(),
            evidence_ids=tuple(),
            confidence=0.0,
            direction_tokens=tuple(),
            reason=f"movement_not_applicable:{movement.movement_applicability.value}",
            risk_flags=("movement_not_applicable",),
            source_arrow_ids=source_arrow_ids,
            lane_summary=lane_summary,
        )
    if not matched_arrows:
        return RoadArrowDecision(
            road_id=road_id,
            movement_id=movement.movement_id,
            movement_type=movement.movement_type,
            decision_status=DecisionStatus.UNKNOWN,
            evidence_items=tuple(),
            evidence_ids=tuple(),
            confidence=0.0,
            direction_tokens=tuple(),
            reason="missing_laneinfo_for_approach_road",
            risk_flags=("missing_laneinfo",),
            source_arrow_ids=tuple(),
            lane_summary=lane_summary,
        )

    invalid_reasons: list[str] = []
    direction_tokens: set[str] = set()
    if movement_type not in SUPPORTED_ARROW_MOVEMENT_TYPES:
        invalid_reasons.append(f"unsupported_movement_type:{movement.movement_type}")
    for matched_arrow in matched_arrows:
        arrow = matched_arrow.arrow
        if not arrow.direction_matched:
            invalid_reasons.append(f"direction_mismatch:{arrow.arrow_id}")
        if not arrow.lane_sequence_complete:
            invalid_reasons.append(
                f"incomplete_lane_sequence:{arrow.arrow_id}:{arrow.sequence_metadata_status}"
            )
        elif arrow.sequence_metadata_status != "complete":
            invalid_reasons.append(
                f"unverified_lane_sequence_metadata:{arrow.arrow_id}:{arrow.sequence_metadata_status}"
            )
        for code in arrow.lane_codes:
            try:
                parsed = parse_arrow_code(code)
            except ValueError:
                invalid_reasons.append(f"unknown_arrow_code:{arrow.arrow_id}:{code}")
                continue
            direction_tokens.update(parsed.tokens)
            if not parsed.usable_for_prohibition:
                invalid_reasons.append(f"arrow_not_usable_for_decision:{arrow.arrow_id}:{code}")

    if invalid_reasons:
        reason = ";".join(dict.fromkeys(invalid_reasons))
        risk_flags = tuple(sorted({item.split(":", 1)[0] for item in invalid_reasons}))
        evidence = _road_arrow_evidence(
            movement=movement,
            road_id=road_id,
            matched_arrows=matched_arrows,
            evidence_id=f"{evidence_prefix}:{movement.movement_id}:{road_id}:unknown",
            decision_status=DecisionStatus.UNKNOWN,
            direction_tokens=tuple(sorted(direction_tokens)),
            reason=reason,
            confidence=0.0,
            risk_flags=risk_flags,
        )
        return RoadArrowDecision(
            road_id=road_id,
            movement_id=movement.movement_id,
            movement_type=movement.movement_type,
            decision_status=DecisionStatus.UNKNOWN,
            evidence_items=(evidence,),
            evidence_ids=(evidence.evidence_id,),
            confidence=0.0,
            direction_tokens=tuple(sorted(direction_tokens)),
            reason=reason,
            risk_flags=risk_flags,
            source_arrow_ids=source_arrow_ids,
            lane_summary=lane_summary,
        )

    supported = movement_type in direction_tokens
    decision_status = DecisionStatus.SUPPORTED if supported else DecisionStatus.PROHIBITED
    confidence_cap = 0.8 if supported else 0.75
    confidence = min(
        confidence_cap,
        min((item.confidence for item in matched_arrows), default=confidence_cap),
    )
    reason = (
        "lane_direction_union_supports_movement"
        if supported
        else "complete_lane_direction_union_excludes_movement"
    )
    evidence = _road_arrow_evidence(
        movement=movement,
        road_id=road_id,
        matched_arrows=matched_arrows,
        evidence_id=f"{evidence_prefix}:{movement.movement_id}:{road_id}:{decision_status.value}",
        decision_status=decision_status,
        direction_tokens=tuple(sorted(direction_tokens)),
        reason=reason,
        confidence=confidence,
        risk_flags=tuple(),
    )
    return RoadArrowDecision(
        road_id=road_id,
        movement_id=movement.movement_id,
        movement_type=movement.movement_type,
        decision_status=decision_status,
        evidence_items=(evidence,),
        evidence_ids=(evidence.evidence_id,),
        confidence=confidence,
        direction_tokens=tuple(sorted(direction_tokens)),
        reason=reason,
        source_arrow_ids=source_arrow_ids,
        lane_summary=lane_summary,
    )


def _road_arrow_evidence(
    *,
    movement: T09ArmMovement,
    road_id: str,
    matched_arrows: tuple[_MatchedArrow, ...],
    evidence_id: str,
    decision_status: DecisionStatus,
    direction_tokens: tuple[str, ...],
    reason: str,
    confidence: float,
    risk_flags: tuple[str, ...],
) -> T09EvidenceItem:
    source_arrow_ids = tuple(sorted({item.arrow.arrow_id for item in matched_arrows}))
    prohibited = decision_status == DecisionStatus.PROHIBITED
    determined = decision_status in {DecisionStatus.PROHIBITED, DecisionStatus.SUPPORTED}
    to_road_ids = tuple(
        sorted(
            {
                pair.to_road_id
                for pair in movement.carrier_road_pairs
                if pair.from_road_id == road_id
            }
        )
    )
    return T09EvidenceItem(
        evidence_id=evidence_id,
        evidence_type=(EvidenceType.COMPLETE_ARROW_EXCLUSION if prohibited else EvidenceType.ARROW),
        junction_id=movement.junction_id,
        movement_id=movement.movement_id,
        road_pair=None,
        evidence_status=(
            "laneinfo_supports_road_movement"
            if decision_status == DecisionStatus.SUPPORTED
            else (
                "laneinfo_excludes_road_movement"
                if prohibited
                else "laneinfo_unknown_for_road_movement"
            )
        ),
        prohibition_reason=(
            ProhibitionReason.COMPLETE_ARROW_EXCLUSION
            if prohibited
            else ProhibitionReason.INSUFFICIENT_EVIDENCE
        ),
        inference_level=InferenceLevel.DERIVED if determined else InferenceLevel.UNKNOWN,
        confidence=confidence,
        provenance=EvidenceProvenance(
            source_type="laneinfo",
            source_id=",".join(source_arrow_ids),
            matched_object_ids=(movement.movement_id, road_id, *source_arrow_ids),
            match_method="approach_road_direction_lane_union",
            field_audit={
                "approach_road_id": road_id,
                "movement_type": movement.movement_type,
                "direction_union": direction_tokens,
                "laneinfo_records": tuple(
                    _matched_arrow_raw_audit(item) for item in matched_arrows
                ),
            },
            reason=reason,
        ),
        supports_prohibition=prohibited,
        risk_flags=risk_flags,
        decision_status=decision_status,
        decision_scope=(
            RuleScope.ROAD_DIRECTION_EXCLUSION if prohibited else RuleScope.ROAD_TO_ARM
        ),
        evidence_priority=EvidencePriority.LANEINFO,
        verification_status=(
            VerificationStatus.VERIFIED_SWSD
            if determined
            else VerificationStatus.NOT_REQUIRED
        ),
        from_road_ids=(road_id,),
        to_road_ids=to_road_ids,
    )


def _matched_arrow_raw_audit(item: _MatchedArrow) -> dict[str, object]:
    arrow = item.arrow
    return item.audit() | {
        "lane_codes": arrow.lane_codes,
        "lane_dir": arrow.lane_dir,
        "road_direction": arrow.road_direction,
        "direction_matched": arrow.direction_matched,
        "lane_sequence_complete": arrow.lane_sequence_complete,
        "sequence_metadata_status": arrow.sequence_metadata_status,
        "seq_start": arrow.seq_start,
        "seq_end": arrow.seq_end,
        "source_arrow_dir": arrow.source_arrow_dir,
        "raw_properties": dict(arrow.properties),
    }


def _road_arrow_lane_summary(
    *,
    movement_type: str,
    matched_arrows: tuple[_MatchedArrow, ...],
) -> dict[str, object]:
    summary: dict[str, object] = {
        "movement_type": movement_type,
        "matched_arrow_count": len(matched_arrows),
        "lane_count": 0,
        "direction_mismatch_count": 0,
        "incomplete_sequence_count": 0,
        "unknown_code_count": 0,
        "unusable_code_count": 0,
        "matched_arrow_ids": tuple(item.arrow.arrow_id for item in matched_arrows),
        "raw_arrow_sequences": tuple(
            ",".join(item.arrow.lane_codes) for item in matched_arrows
        ),
    }
    for matched_arrow in matched_arrows:
        arrow = matched_arrow.arrow
        if not arrow.direction_matched:
            summary["direction_mismatch_count"] = int(summary["direction_mismatch_count"]) + 1
        if not arrow.lane_sequence_complete:
            summary["incomplete_sequence_count"] = int(summary["incomplete_sequence_count"]) + 1
        for code in arrow.lane_codes:
            summary["lane_count"] = int(summary["lane_count"]) + 1
            try:
                parsed = parse_arrow_code(code)
            except ValueError:
                summary["unknown_code_count"] = int(summary["unknown_code_count"]) + 1
                continue
            if not parsed.usable_for_prohibition:
                summary["unusable_code_count"] = int(summary["unusable_code_count"]) + 1
    return summary


def evaluate_complete_arrow_exclusion(
    movement: T09ArmMovement,
    arrows: tuple[ArrowInput, ...],
    *,
    evidence_prefix: str = "arrow",
    roads_by_id: dict[str, SWSDRoadInput] | None = None,
    road_geometries: dict[str, BaseGeometry] | None = None,
    arms_by_id: dict[str, T09SwsdArm] | None = None,
) -> ArrowEvaluationResult:
    roads_by_id = roads_by_id or {}
    road_geometries = road_geometries or {}
    arms_by_id = arms_by_id or {}
    approach_road_ids = tuple(sorted({pair.from_road_id for pair in movement.carrier_road_pairs}))
    matched_arrows = _match_arrows_to_approach_roads(
        movement=movement,
        approach_road_ids=approach_road_ids,
        arrows=arrows,
        roads_by_id=roads_by_id,
        road_geometries=road_geometries,
        arms_by_id=arms_by_id,
    )
    movement_type = movement.movement_type.strip().lower()
    arrow_lane_summary = _arrow_lane_summary(movement_type=movement_type, matched_arrows=matched_arrows)
    arrow_direction_status = _arrow_direction_status(arrow_lane_summary)
    field_audit = _arrow_field_audit(matched_arrows)
    source_id = _arrow_source_id(matched_arrows, fallback=approach_road_ids)
    if movement_type not in SUPPORTED_ARROW_MOVEMENT_TYPES:
        return ArrowEvaluationResult(
            evidence_items=(
                _arrow_evidence(
                    movement,
                    evidence_id=f"{evidence_prefix}:{movement.movement_id}:ambiguous",
                    evidence_status="arrow_ambiguous_for_prohibition",
                    source_id=source_id,
                    reason=f"movement_type_not_stable:{movement.movement_type}",
                    supports_prohibition=False,
                    confidence=0.0,
                    field_audit=field_audit,
                    matched_object_ids=(movement.movement_id, *approach_road_ids),
                ),
            ),
            prohibition_status=ProhibitionStatus.UNKNOWN,
            prohibition_reason=ProhibitionReason.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            arrow_direction_status=arrow_direction_status,
            arrow_lane_summary=arrow_lane_summary,
        )
    incomplete_reasons: list[str] = []
    any_lane_supports_movement = False

    for road_id in approach_road_ids:
        matched_arrow = matched_arrows.get(road_id)
        if matched_arrow is None:
            incomplete_reasons.append(f"missing_arrow:{road_id}")
            continue
        arrow = matched_arrow.arrow
        if not arrow.direction_matched:
            incomplete_reasons.append(f"direction_mismatch:{road_id}")
            continue
        if not arrow.lane_sequence_complete:
            incomplete_reasons.append(f"incomplete_lane_sequence:{road_id}")
            continue
        try:
            parsed_codes = tuple(parse_arrow_code(code) for code in arrow.lane_codes)
        except ValueError:
            incomplete_reasons.append(f"unknown_arrow_code:{road_id}")
            continue
        if not parsed_codes or any(not parsed.usable_for_prohibition for parsed in parsed_codes):
            incomplete_reasons.append(f"arrow_not_usable_for_prohibition:{road_id}")
            continue
        for parsed in parsed_codes:
            if arrow_tokens_support_movement(parsed.tokens, movement.movement_type):
                any_lane_supports_movement = True

    if incomplete_reasons:
        return ArrowEvaluationResult(
            evidence_items=(
                _arrow_evidence(
                    movement,
                    evidence_id=f"{evidence_prefix}:{movement.movement_id}:incomplete",
                    evidence_status="arrow_incomplete_for_prohibition",
                    source_id=source_id,
                    reason=";".join(incomplete_reasons),
                    supports_prohibition=False,
                    confidence=0.0,
                    field_audit=field_audit,
                    matched_object_ids=(movement.movement_id, *approach_road_ids),
                ),
            ),
            prohibition_status=ProhibitionStatus.UNKNOWN,
            prohibition_reason=ProhibitionReason.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            arrow_direction_status=arrow_direction_status,
            arrow_lane_summary=arrow_lane_summary,
        )
    if any_lane_supports_movement:
        return ArrowEvaluationResult(
            evidence_items=(
                _arrow_evidence(
                    movement,
                    evidence_id=f"{evidence_prefix}:{movement.movement_id}:supports",
                    evidence_status="arrow_supports_movement",
                    source_id=source_id,
                    reason="at least one lane arrow supports movement type",
                    supports_prohibition=False,
                    confidence=0.8,
                    field_audit=field_audit,
                    matched_object_ids=(movement.movement_id, *approach_road_ids),
                ),
            ),
            prohibition_status=ProhibitionStatus.NO_PROHIBITION_EVIDENCE,
            prohibition_reason=ProhibitionReason.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            arrow_supports_movement=True,
            arrow_direction_status=arrow_direction_status,
            arrow_lane_summary=arrow_lane_summary,
        )
    prohibition_confidence = min(0.75, min((item.confidence for item in matched_arrows.values()), default=0.75))
    return ArrowEvaluationResult(
        evidence_items=(
            _arrow_evidence(
                movement,
                evidence_id=f"{evidence_prefix}:{movement.movement_id}:exclusion",
                evidence_status="arrow_excludes_movement",
                source_id=source_id,
                reason="complete arrow sequence excludes movement type",
                supports_prohibition=False,
                confidence=prohibition_confidence,
                evidence_type=EvidenceType.COMPLETE_ARROW_EXCLUSION,
                field_audit=field_audit,
                matched_object_ids=(movement.movement_id, *approach_road_ids),
            ),
        ),
        prohibition_status=ProhibitionStatus.NO_PROHIBITION_EVIDENCE,
        prohibition_reason=ProhibitionReason.INSUFFICIENT_EVIDENCE,
        confidence=0.0,
        arrow_direction_status=arrow_direction_status,
        arrow_lane_summary=arrow_lane_summary,
    )


def _arrow_evidence(
    movement: T09ArmMovement,
    *,
    evidence_id: str,
    evidence_status: str,
    source_id: str,
    reason: str,
    supports_prohibition: bool,
    confidence: float,
    evidence_type: EvidenceType | None = None,
    field_audit: dict[str, object] | None = None,
    matched_object_ids: tuple[str, ...] | None = None,
) -> T09EvidenceItem:
    resolved_evidence_type = evidence_type or (
        EvidenceType.COMPLETE_ARROW_EXCLUSION if supports_prohibition else EvidenceType.ARROW
    )
    inference_level = (
        InferenceLevel.DERIVED
        if supports_prohibition
        else (
            InferenceLevel.WEAK_DERIVED
            if resolved_evidence_type == EvidenceType.COMPLETE_ARROW_EXCLUSION
            else InferenceLevel.UNKNOWN
        )
    )
    return T09EvidenceItem(
        evidence_id=evidence_id,
        evidence_type=resolved_evidence_type,
        junction_id=movement.junction_id,
        movement_id=movement.movement_id,
        road_pair=None,
        evidence_status=evidence_status,
        prohibition_reason=(
            ProhibitionReason.COMPLETE_ARROW_EXCLUSION
            if supports_prohibition
            else ProhibitionReason.INSUFFICIENT_EVIDENCE
        ),
        inference_level=inference_level,
        confidence=confidence,
        provenance=EvidenceProvenance(
            source_type="arrow",
            source_id=source_id,
            matched_object_ids=matched_object_ids or (movement.movement_id,),
            match_method="directed_geometry_or_road_id_and_lane_sequence",
            field_audit=field_audit or {},
            reason=reason,
        ),
        supports_prohibition=supports_prohibition,
    )


def _match_arrows_to_approach_roads(
    *,
    movement: T09ArmMovement,
    approach_road_ids: tuple[str, ...],
    arrows: tuple[ArrowInput, ...],
    roads_by_id: dict[str, SWSDRoadInput],
    road_geometries: dict[str, BaseGeometry],
    arms_by_id: dict[str, T09SwsdArm],
) -> dict[str, _MatchedArrow]:
    from_arm = arms_by_id.get(movement.from_arm_id)
    matched: dict[str, _MatchedArrow] = {}
    for road_id in approach_road_ids:
        road = roads_by_id.get(road_id)
        road_geometry = road_geometries.get(road_id)
        candidates: list[_MatchedArrow] = []
        if from_arm is not None and road is not None and road_geometry is not None:
            candidates.extend(
                _geometry_arrow_candidates(
                    road_id=road_id,
                    arrows=arrows,
                    road=road,
                    road_geometry=road_geometry,
                    from_arm=from_arm,
                )
            )
        if not candidates:
            candidates.extend(_road_id_arrow_candidates(road_id=road_id, arrows=arrows))
        if candidates:
            matched[road_id] = min(candidates, key=_arrow_sort_key)
    return matched


def _match_all_arrows_to_approach_roads(
    *,
    movement: T09ArmMovement,
    approach_road_ids: tuple[str, ...],
    arrows: tuple[ArrowInput, ...],
    roads_by_id: dict[str, SWSDRoadInput],
    road_geometries: dict[str, BaseGeometry],
    arms_by_id: dict[str, T09SwsdArm],
) -> dict[str, tuple[_MatchedArrow, ...]]:
    from_arm = arms_by_id.get(movement.from_arm_id)
    matched: dict[str, tuple[_MatchedArrow, ...]] = {}
    for road_id in approach_road_ids:
        road = roads_by_id.get(road_id)
        road_geometry = road_geometries.get(road_id)
        candidates: tuple[_MatchedArrow, ...] = tuple()
        if from_arm is not None and road is not None and road_geometry is not None:
            candidates = _geometry_arrow_candidates(
                road_id=road_id,
                arrows=arrows,
                road=road,
                road_geometry=road_geometry,
                from_arm=from_arm,
            )
            direct_candidates = tuple(
                item for item in candidates if item.arrow.road_id == road_id
            )
            if direct_candidates:
                candidates = direct_candidates
        if not candidates:
            candidates = _road_id_arrow_candidates(road_id=road_id, arrows=arrows)
        if candidates:
            unique_candidates: dict[str, _MatchedArrow] = {}
            for candidate in sorted(candidates, key=_arrow_sort_key):
                unique_candidates.setdefault(candidate.arrow.arrow_id, candidate)
            matched[road_id] = tuple(unique_candidates.values())
    return matched


def _geometry_arrow_candidates(
    *,
    road_id: str,
    arrows: tuple[ArrowInput, ...],
    road: SWSDRoadInput,
    road_geometry: BaseGeometry,
    from_arm: T09SwsdArm,
) -> tuple[_MatchedArrow, ...]:
    candidates: list[_MatchedArrow] = []
    for arrow in arrows:
        match = match_arrow_to_approach_road(
            arrow_geometry=arrow.geometry,
            road=road,
            road_geometry=road_geometry,
            member_node_ids=from_arm.member_node_ids,
        )
        if match is None:
            continue
        candidates.append(
            _matched_arrow_from_geometry(
                road_id=road_id,
                arrow=arrow,
                match=match,
                road=road,
                road_geometry=road_geometry,
                from_arm=from_arm,
            )
        )
    return tuple(candidates)


def _matched_arrow_from_geometry(
    *,
    road_id: str,
    arrow: ArrowInput,
    match: DirectedGeometryMatch,
    road: SWSDRoadInput,
    road_geometry: BaseGeometry,
    from_arm: T09SwsdArm,
) -> _MatchedArrow:
    endpoint_distance = approach_arrow_endpoint_distance(
        arrow_geometry=arrow.geometry,
        road=road,
        road_geometry=road_geometry,
        member_node_ids=from_arm.member_node_ids,
    )
    return _MatchedArrow(
        road_id=road_id,
        arrow=arrow,
        match_method=match.method,
        confidence=match.confidence,
        distance_m=match.distance_m,
        direction_delta_deg=match.direction_delta_deg,
        endpoint_distance_m=endpoint_distance,
    )


def _road_id_arrow_candidates(*, road_id: str, arrows: tuple[ArrowInput, ...]) -> tuple[_MatchedArrow, ...]:
    return tuple(
        _MatchedArrow(
            road_id=road_id,
            arrow=arrow,
            match_method="road_id_fallback",
            confidence=1.0,
        )
        for arrow in arrows
        if arrow.road_id == road_id
    )


def _arrow_sort_key(item: _MatchedArrow) -> tuple[float, float, float, str]:
    return (
        item.endpoint_distance_m if item.endpoint_distance_m is not None else float("inf"),
        item.direction_delta_deg if item.direction_delta_deg is not None else 0.0,
        item.distance_m if item.distance_m is not None else 0.0,
        item.arrow.arrow_id,
    )


def _arrow_field_audit(matched_arrows: dict[str, _MatchedArrow]) -> dict[str, object]:
    return {
        "approach_road_matches": {
            road_id: matched_arrow.audit() for road_id, matched_arrow in sorted(matched_arrows.items())
        }
    }


def _arrow_lane_summary(*, movement_type: str, matched_arrows: dict[str, _MatchedArrow]) -> dict[str, object]:
    movement_type_supported = movement_type in SUPPORTED_ARROW_MOVEMENT_TYPES
    unique_arrows: dict[str, ArrowInput] = {}
    for matched_arrow in matched_arrows.values():
        unique_arrows.setdefault(matched_arrow.arrow.arrow_id, matched_arrow.arrow)

    summary: dict[str, object] = {
        "matched_approach_road_count": len(matched_arrows),
        "matched_arrow_count": len(unique_arrows),
        "lane_count": 0,
        "supporting_lane_count": 0,
        "excluding_lane_count": 0,
        "empty_lane_count": 0,
        "uninvestigated_lane_count": 0,
        "unknown_code_count": 0,
        "direction_mismatch_count": 0,
        "incomplete_sequence_count": 0,
        "movement_type_supported": movement_type_supported,
        "matched_arrow_ids": tuple(sorted(unique_arrows)),
        "raw_arrow_sequences": tuple(",".join(arrow.lane_codes) for arrow in unique_arrows.values()),
    }
    for arrow in unique_arrows.values():
        if not arrow.direction_matched:
            summary["direction_mismatch_count"] = int(summary["direction_mismatch_count"]) + 1
        if not arrow.lane_sequence_complete:
            summary["incomplete_sequence_count"] = int(summary["incomplete_sequence_count"]) + 1
        for code in arrow.lane_codes:
            summary["lane_count"] = int(summary["lane_count"]) + 1
            try:
                parsed = parse_arrow_code(code)
            except ValueError:
                summary["unknown_code_count"] = int(summary["unknown_code_count"]) + 1
                continue
            if "empty" in parsed.tokens:
                summary["empty_lane_count"] = int(summary["empty_lane_count"]) + 1
            if "uninvestigated" in parsed.tokens:
                summary["uninvestigated_lane_count"] = int(summary["uninvestigated_lane_count"]) + 1
            if not parsed.usable_for_prohibition or not movement_type_supported:
                continue
            if arrow_tokens_support_movement(parsed.tokens, movement_type):
                summary["supporting_lane_count"] = int(summary["supporting_lane_count"]) + 1
            else:
                summary["excluding_lane_count"] = int(summary["excluding_lane_count"]) + 1
    return summary


def _arrow_direction_status(summary: dict[str, object]) -> str:
    if int(summary["matched_arrow_count"]) == 0:
        return "no_arrow_evidence"
    if (
        not bool(summary["movement_type_supported"])
        or int(summary["direction_mismatch_count"]) > 0
        or int(summary["incomplete_sequence_count"]) > 0
        or int(summary["unknown_code_count"]) > 0
    ):
        return "incomplete_or_unknown"
    if int(summary["empty_lane_count"]) > 0 or int(summary["uninvestigated_lane_count"]) > 0:
        return "has_empty_or_uninvestigated_lane"
    if int(summary["supporting_lane_count"]) > 0:
        return "supports_movement"
    if int(summary["excluding_lane_count"]) > 0 and int(summary["lane_count"]) > 0:
        return "excludes_movement"
    return "incomplete_or_unknown"


def _arrow_source_id(matched_arrows: dict[str, _MatchedArrow], *, fallback: tuple[str, ...]) -> str:
    source_ids = tuple(sorted({item.arrow.arrow_id for item in matched_arrows.values()}))
    if source_ids:
        return ",".join(source_ids)
    return ",".join(fallback)
