from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import (
    EvidenceRef,
    split_segment_access,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    CarrierKind,
    CarrierLabel,
    CarrierTarget,
    ClueScope,
    FrozenSchemeACase,
    RealityChangeClue,
    StrategyBaselineRecord,
    StrategyOutcome,
)


def build_scheme_a_carrier_labels(
    case: FrozenSchemeACase,
    baselines: list[StrategyBaselineRecord],
    sample: Mapping[str, str],
    skeleton_signature: str,
    clues: list[RealityChangeClue],
) -> list[CarrierLabel]:
    segments = {row.segment_id: row for row in case.segments}
    junctions = {row.junction_id: row for row in case.junctions}
    movements = {row.movement_id: row for row in case.physical_movements}
    forced_segments = {
        row.segment_id for row in baselines if row.outcome is StrategyOutcome.FAIL
    }
    conflict_junctions: set[str] = set()
    blocked_movements: set[str] = set()
    clue_refs_by_segment: dict[str, list[EvidenceRef]] = defaultdict(list)

    def force_junction(junction_id: str, refs: Iterable[EvidenceRef]) -> None:
        conflict_junctions.add(junction_id)
        junction = junctions.get(junction_id)
        if junction is None:
            return
        for segment_id in junction.related_segment_ids:
            forced_segments.add(segment_id)
            clue_refs_by_segment[segment_id].extend(refs)

    for clue in clues:
        if clue.scope is ClueScope.JUNCTION:
            force_junction(clue.object_id, clue.evidence_refs)
        elif clue.scope is ClueScope.SEGMENT:
            forced_segments.add(clue.object_id)
            clue_refs_by_segment[clue.object_id].extend(clue.evidence_refs)
        else:
            blocked_movements.add(clue.object_id)
            movement = movements.get(clue.object_id)
            if movement is not None and (
                not movement.carrier_exclusive or movement.affects_shared_junction_unit
            ):
                force_junction(movement.junction_id, clue.evidence_refs)

    result: list[CarrierLabel] = []
    for baseline in baselines:
        segment = segments[baseline.segment_id]
        effective_target = baseline.carrier_target
        if segment.segment_id in forced_segments:
            effective_target = CarrierTarget.KEEP_SWSD
        if effective_target is CarrierTarget.USE_RCSD:
            payload = baseline.selected_road_ids
        elif effective_target is CarrierTarget.KEEP_SWSD:
            payload = baseline.swsd_fallback_road_ids
        elif effective_target is CarrierTarget.MIXED_CARRIER:
            payload = tuple(
                sorted(set(baseline.selected_road_ids) | set(baseline.swsd_fallback_road_ids))
            )
        else:
            payload = ()
        available = bool(payload) and segment.independent_road_valid and segment.access_valid
        if not available:
            effective_target = CarrierTarget.REVIEW_FALLBACK
            payload = ()
        weight, role = label_weight(sample, (baseline.segment_id,))
        lineage = _dedupe_evidence(
            baseline.lineage
            + segment.evidence_refs
            + tuple(clue_refs_by_segment.get(segment.segment_id, ()))
        )
        result.append(
            CarrierLabel(
                case_key=case.case_key,
                object_type="SEGMENT",
                object_id=baseline.segment_id,
                skeleton_signature=skeleton_signature,
                carrier_target=effective_target,
                target_kind=CarrierKind.ROAD if available else CarrierKind.UNKNOWN,
                target_payload=payload,
                label_weight=weight,
                weight_role=role,
                fold=case.fold,
                available=available,
                mask_reason=(
                    ""
                    if available
                    else "frozen Segment access or independent SWSD Road is not publishable"
                ),
                lineage=lineage,
            )
        )

    for movement in case.physical_movements:
        from_segment, _ = split_segment_access(movement.from_segment_access)
        to_segment, _ = split_segment_access(movement.to_segment_access)
        dependency_blocked = (
            movement.movement_id in blocked_movements
            or movement.junction_id in conflict_junctions
        )
        available = (
            not dependency_blocked
            and movement.carrier_kind is not CarrierKind.UNKNOWN
            and bool(movement.carrier_ids)
        )
        weight, role = label_weight(sample, (from_segment, to_segment))
        result.append(
            CarrierLabel(
                case_key=case.case_key,
                object_type="MOVEMENT",
                object_id=movement.movement_id,
                skeleton_signature=skeleton_signature,
                carrier_target=(
                    CarrierTarget.USE_RCSD if available else CarrierTarget.REVIEW_FALLBACK
                ),
                target_kind=movement.carrier_kind if available else CarrierKind.UNKNOWN,
                target_payload=movement.carrier_ids if available else (),
                label_weight=weight,
                weight_role=role,
                fold=case.fold,
                available=available,
                mask_reason=(
                    ""
                    if available
                    else "Movement carrier is unavailable or its own/Junction fallback applies"
                ),
                lineage=movement.evidence_refs,
            )
        )
    return result


def label_weight(
    sample: Mapping[str, str], object_segment_ids: tuple[str, ...]
) -> tuple[float, str]:
    scope = sample["scope_type"]
    is_target = scope != "t10_segment" or sample["business_id"] in object_segment_ids
    key = "target_weight" if is_target else "context_weight"
    return float(sample[key]), "TARGET" if is_target else "CONTEXT"


def _dedupe_evidence(rows: Iterable[EvidenceRef]) -> tuple[EvidenceRef, ...]:
    return tuple(dict.fromkeys(rows))


__all__ = ["build_scheme_a_carrier_labels", "label_weight"]
