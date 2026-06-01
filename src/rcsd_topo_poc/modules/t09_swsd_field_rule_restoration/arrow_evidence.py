from __future__ import annotations

from dataclasses import dataclass

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
    EvidenceProvenance,
    EvidenceType,
    InferenceLevel,
    ProhibitionReason,
    ProhibitionStatus,
    SWSDRoadInput,
    T09ArmMovement,
    T09EvidenceItem,
    T09SwsdArm,
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
    field_audit = _arrow_field_audit(matched_arrows)
    source_id = _arrow_source_id(matched_arrows, fallback=approach_road_ids)
    movement_type = movement.movement_type.strip().lower()
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
        )
    prohibition_confidence = min(0.75, min((item.confidence for item in matched_arrows.values()), default=0.75))
    return ArrowEvaluationResult(
        evidence_items=(
            _arrow_evidence(
                movement,
                evidence_id=f"{evidence_prefix}:{movement.movement_id}:exclusion",
                evidence_status="prohibited_by_complete_arrow_exclusion",
                source_id=source_id,
                reason="complete arrow sequence excludes movement type",
                supports_prohibition=True,
                confidence=prohibition_confidence,
                field_audit=field_audit,
                matched_object_ids=(movement.movement_id, *approach_road_ids),
            ),
        ),
        prohibition_status=ProhibitionStatus.FULLY_PROHIBITED,
        prohibition_reason=ProhibitionReason.COMPLETE_ARROW_EXCLUSION,
        confidence=prohibition_confidence,
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
    field_audit: dict[str, object] | None = None,
    matched_object_ids: tuple[str, ...] | None = None,
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


def _arrow_source_id(matched_arrows: dict[str, _MatchedArrow], *, fallback: tuple[str, ...]) -> str:
    source_ids = tuple(sorted({item.arrow.arrow_id for item in matched_arrows.values()}))
    if source_ids:
        return ",".join(source_ids)
    return ",".join(fallback)
