from __future__ import annotations

from dataclasses import dataclass

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arrow_codes import (
    arrow_tokens_support_movement,
    parse_arrow_code,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    ArrowInput,
    EvidenceProvenance,
    EvidenceType,
    InferenceLevel,
    ProhibitionReason,
    ProhibitionStatus,
    T09ArmMovement,
    T09EvidenceItem,
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


def evaluate_complete_arrow_exclusion(
    movement: T09ArmMovement,
    arrows: tuple[ArrowInput, ...],
    *,
    evidence_prefix: str = "arrow",
) -> ArrowEvaluationResult:
    approach_road_ids = tuple(sorted({pair.from_road_id for pair in movement.carrier_road_pairs}))
    movement_type = movement.movement_type.strip().lower()
    if movement_type not in SUPPORTED_ARROW_MOVEMENT_TYPES:
        return ArrowEvaluationResult(
            evidence_items=(
                _arrow_evidence(
                    movement,
                    evidence_id=f"{evidence_prefix}:{movement.movement_id}:ambiguous",
                    evidence_status="arrow_ambiguous_for_prohibition",
                    source_id=",".join(approach_road_ids),
                    reason=f"movement_type_not_stable:{movement.movement_type}",
                    supports_prohibition=False,
                    confidence=0.0,
                ),
            ),
            prohibition_status=ProhibitionStatus.UNKNOWN,
            prohibition_reason=ProhibitionReason.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
        )
    arrow_by_road = {arrow.road_id: arrow for arrow in arrows}
    incomplete_reasons: list[str] = []
    any_lane_supports_movement = False

    for road_id in approach_road_ids:
        arrow = arrow_by_road.get(road_id)
        if arrow is None:
            incomplete_reasons.append(f"missing_arrow:{road_id}")
            continue
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
                    source_id=",".join(approach_road_ids),
                    reason=";".join(incomplete_reasons),
                    supports_prohibition=False,
                    confidence=0.0,
                ),
            ),
            prohibition_status=ProhibitionStatus.UNKNOWN,
            prohibition_reason=ProhibitionReason.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
        )
    if any_lane_supports_movement:
        return ArrowEvaluationResult(
            evidence_items=(
                _arrow_evidence(
                    movement,
                    evidence_id=f"{evidence_prefix}:{movement.movement_id}:supports",
                    evidence_status="arrow_supports_movement",
                    source_id=",".join(approach_road_ids),
                    reason="at least one lane arrow supports movement type",
                    supports_prohibition=False,
                    confidence=0.8,
                ),
            ),
            prohibition_status=ProhibitionStatus.NO_PROHIBITION_EVIDENCE,
            prohibition_reason=ProhibitionReason.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            arrow_supports_movement=True,
        )
    return ArrowEvaluationResult(
        evidence_items=(
            _arrow_evidence(
                movement,
                evidence_id=f"{evidence_prefix}:{movement.movement_id}:exclusion",
                evidence_status="prohibited_by_complete_arrow_exclusion",
                source_id=",".join(approach_road_ids),
                reason="complete arrow sequence excludes movement type",
                supports_prohibition=True,
                confidence=0.75,
            ),
        ),
        prohibition_status=ProhibitionStatus.FULLY_PROHIBITED,
        prohibition_reason=ProhibitionReason.COMPLETE_ARROW_EXCLUSION,
        confidence=0.75,
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
) -> T09EvidenceItem:
    return T09EvidenceItem(
        evidence_id=evidence_id,
        evidence_type=EvidenceType.COMPLETE_ARROW_EXCLUSION if supports_prohibition else EvidenceType.ARROW,
        junction_id=movement.junction_id,
        movement_id=movement.movement_id,
        road_pair=None,
        evidence_status=evidence_status,
        prohibition_reason=(
            ProhibitionReason.COMPLETE_ARROW_EXCLUSION
            if supports_prohibition
            else ProhibitionReason.INSUFFICIENT_EVIDENCE
        ),
        inference_level=InferenceLevel.DERIVED if supports_prohibition else InferenceLevel.UNKNOWN,
        confidence=confidence,
        provenance=EvidenceProvenance(
            source_type="arrow",
            source_id=source_id,
            matched_object_ids=(movement.movement_id,),
            match_method="road_id_and_lane_sequence",
            reason=reason,
        ),
        supports_prohibition=supports_prohibition,
    )
