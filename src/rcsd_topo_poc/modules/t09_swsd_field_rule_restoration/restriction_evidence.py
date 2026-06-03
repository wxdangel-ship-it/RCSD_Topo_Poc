from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.geometry_match import (
    DirectedGeometryMatch,
    MAX_RESTRICTION_INSIDE_DISTANCE_M,
    match_restriction_endpoint_to_road,
    restriction_inside_endpoint_distance,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    EvidenceProvenance,
    EvidenceType,
    InferenceLevel,
    ProhibitionReason,
    ProhibitionStatus,
    RestrictionInput,
    RoadPair,
    SWSDRoadInput,
    T09ArmMovement,
    T09EvidenceItem,
    T09SwsdArm,
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


def match_restriction_evidence(
    movement: T09ArmMovement,
    restrictions: tuple[RestrictionInput, ...],
    *,
    evidence_prefix: str = "restriction",
    roads_by_id: dict[str, SWSDRoadInput] | None = None,
    road_geometries: dict[str, BaseGeometry] | None = None,
    arms_by_id: dict[str, T09SwsdArm] | None = None,
) -> RestrictionMatchResult:
    roads_by_id = roads_by_id or {}
    road_geometries = road_geometries or {}
    arms_by_id = arms_by_id or {}
    pair_by_key = {(pair.from_road_id, pair.to_road_id): pair for pair in movement.carrier_road_pairs}
    evidence_items: list[T09EvidenceItem] = []
    next_index = 1
    matched_keys: set[tuple[str, str, str]] = set()
    for restriction in restrictions:
        road_pair = pair_by_key.get((restriction.in_link_id, restriction.out_link_id))
        if road_pair is not None:
            if (restriction.restriction_id, road_pair.from_road_id, road_pair.to_road_id) not in matched_keys:
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
                matched_keys.add((restriction.restriction_id, road_pair.from_road_id, road_pair.to_road_id))
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
            if (restriction.restriction_id, carrier_pair.from_road_id, carrier_pair.to_road_id) in matched_keys:
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
            matched_keys.add((restriction.restriction_id, carrier_pair.from_road_id, carrier_pair.to_road_id))
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
        )
    if len({item.road_pair for item in evidence_items}) == movement.candidate_road_pair_count:
        return RestrictionMatchResult(
            evidence_items=tuple(evidence_items),
            prohibition_status=ProhibitionStatus.FULLY_PROHIBITED,
            prohibition_reason=ProhibitionReason.EXPLICIT_RESTRICTION,
            confidence=min(item.confidence for item in evidence_items),
            restriction_coverage="all_restricted",
            partial_basis="not_applicable",
            remaining_restriction_status="not_applicable",
        )
    return RestrictionMatchResult(
        evidence_items=tuple(evidence_items),
        prohibition_status=ProhibitionStatus.PARTIALLY_PROHIBITED,
        prohibition_reason=ProhibitionReason.EXPLICIT_RESTRICTION,
        confidence=min(0.9, max(item.confidence for item in evidence_items)),
        restriction_coverage="partial_restricted",
        partial_basis=_partial_basis(movement=movement, evidence_items=tuple(evidence_items)),
        remaining_restriction_status="no_restriction_evidence",
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
    )
