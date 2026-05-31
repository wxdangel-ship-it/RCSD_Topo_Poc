from __future__ import annotations

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    EvidenceProvenance,
    EvidenceType,
    InferenceLevel,
    ProhibitionReason,
    RoadAttributes,
    T09EvidenceItem,
)


def detect_special_carrier_evidence(
    *,
    junction_id: str,
    arm_id: str,
    roads: tuple[RoadAttributes, ...],
    evidence_prefix: str = "special_carrier",
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


def _kind_tokens(kind: str | None) -> tuple[str, ...]:
    if kind is None:
        return tuple()
    return tuple(token.strip().lower() for token in str(kind).split("|") if token.strip())


def _has_kind_suffix(tokens: tuple[str, ...], suffix: str) -> bool:
    return any(token.endswith(suffix.lower()) for token in tokens)
