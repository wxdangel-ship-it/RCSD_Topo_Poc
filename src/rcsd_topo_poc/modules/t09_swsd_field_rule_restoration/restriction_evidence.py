from __future__ import annotations

from dataclasses import dataclass

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    EvidenceProvenance,
    EvidenceType,
    InferenceLevel,
    ProhibitionReason,
    ProhibitionStatus,
    RestrictionInput,
    T09ArmMovement,
    T09EvidenceItem,
)


@dataclass(frozen=True)
class RestrictionMatchResult:
    evidence_items: tuple[T09EvidenceItem, ...]
    prohibition_status: ProhibitionStatus
    prohibition_reason: ProhibitionReason
    confidence: float


def match_restriction_evidence(
    movement: T09ArmMovement,
    restrictions: tuple[RestrictionInput, ...],
    *,
    evidence_prefix: str = "restriction",
) -> RestrictionMatchResult:
    pair_by_key = {(pair.from_road_id, pair.to_road_id): pair for pair in movement.carrier_road_pairs}
    evidence_items: list[T09EvidenceItem] = []
    for index, restriction in enumerate(restrictions, start=1):
        road_pair = pair_by_key.get((restriction.in_link_id, restriction.out_link_id))
        if road_pair is None:
            continue
        evidence_items.append(
            T09EvidenceItem(
                evidence_id=f"{evidence_prefix}:{movement.movement_id}:{index}",
                evidence_type=EvidenceType.RESTRICTION,
                junction_id=movement.junction_id,
                movement_id=movement.movement_id,
                road_pair=road_pair,
                evidence_status="prohibited_by_restriction",
                prohibition_reason=ProhibitionReason.EXPLICIT_RESTRICTION,
                inference_level=InferenceLevel.EXPLICIT,
                confidence=1.0,
                provenance=EvidenceProvenance(
                    source_type="restriction",
                    source_id=restriction.restriction_id,
                    matched_object_ids=(movement.movement_id, road_pair.from_road_id, road_pair.to_road_id),
                    match_method="inLinkID_to_outLinkID",
                    field_audit={
                        "inLinkID": restriction.in_link_id,
                        "outLinkID": restriction.out_link_id,
                    },
                    reason="restriction road-pair matches movement carrier universe",
                ),
                supports_prohibition=True,
            )
        )

    if not evidence_items:
        return RestrictionMatchResult(
            evidence_items=tuple(),
            prohibition_status=ProhibitionStatus.NO_PROHIBITION_EVIDENCE,
            prohibition_reason=ProhibitionReason.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
        )
    if len({item.road_pair for item in evidence_items}) == movement.candidate_road_pair_count:
        return RestrictionMatchResult(
            evidence_items=tuple(evidence_items),
            prohibition_status=ProhibitionStatus.FULLY_PROHIBITED,
            prohibition_reason=ProhibitionReason.EXPLICIT_RESTRICTION,
            confidence=1.0,
        )
    return RestrictionMatchResult(
        evidence_items=tuple(evidence_items),
        prohibition_status=ProhibitionStatus.PARTIALLY_PROHIBITED,
        prohibition_reason=ProhibitionReason.EXPLICIT_RESTRICTION,
        confidence=0.9,
    )
