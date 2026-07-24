from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    CarrierKind,
    ClueScope,
    FallbackOutcome,
    FallbackPlan,
    FallbackUnit,
    FrozenPhysicalMovement,
    FrozenSchemeACase,
)


def resolve_scheme_a_fallback(
    case: FrozenSchemeACase,
    scope: ClueScope | str,
    object_id: str,
    *,
    carrier_exclusive: bool | None = None,
    affects_shared_junction_unit: bool | None = None,
    clue_ids: tuple[str, ...] = (),
) -> FallbackPlan:
    requested_scope = ClueScope(scope)
    unit = FallbackUnit(requested_scope.value)
    junction_ids: set[str] = set()
    segment_ids: set[str] = set()
    movement_ids: set[str] = set()

    if requested_scope is ClueScope.JUNCTION:
        junction_ids.add(object_id)
        _expand_junction(case, object_id, segment_ids, movement_ids)
    elif requested_scope is ClueScope.SEGMENT:
        segment_ids.add(object_id)
    else:
        movement = _movement(case, object_id)
        exclusive = movement.carrier_exclusive if carrier_exclusive is None else carrier_exclusive
        shared = (
            movement.affects_shared_junction_unit
            if affects_shared_junction_unit is None
            else affects_shared_junction_unit
        )
        if exclusive and not shared:
            movement_ids.add(object_id)
        else:
            unit = FallbackUnit.JUNCTION
            junction_ids.add(movement.junction_id)
            _expand_junction(case, movement.junction_id, segment_ids, movement_ids)

    segments_by_id = {item.segment_id: item for item in case.segments}
    failures: list[str] = []
    retained_roads: set[str] = set()
    for segment_id in sorted(segment_ids):
        segment = segments_by_id.get(segment_id)
        if segment is None:
            failures.append(f"frozen Segment not found: {segment_id}")
            continue
        retained_roads.update(segment.swsd_road_ids)
        if not segment.independent_road_valid:
            failures.append(f"Segment has no legal independent SWSD Road: {segment_id}")
        if not segment.access_valid:
            failures.append(f"Segment has no legal frozen access relation: {segment_id}")

    if unit is FallbackUnit.MOVEMENT:
        movement = _movement(case, object_id)
        if movement.carrier_kind is CarrierKind.UNKNOWN or not movement.carrier_ids:
            failures.append(f"Movement has no legal carrier: {object_id}")

    outcome = FallbackOutcome.FAIL if failures else FallbackOutcome.SUCCESS_WITH_FALLBACK
    return FallbackPlan(
        case_key=case.case_key,
        trigger=f"{requested_scope.value}:{object_id}",
        clue_ids=tuple(sorted(set(clue_ids))),
        unit=unit,
        junction_ids=tuple(sorted(junction_ids)),
        segment_ids=tuple(sorted(segment_ids)),
        movement_ids=tuple(sorted(movement_ids)),
        retained_swsd_road_ids=tuple(sorted(retained_roads)),
        outcome=outcome,
        failure_reasons=tuple(failures),
    )


def _movement(case: FrozenSchemeACase, movement_id: str) -> FrozenPhysicalMovement:
    for item in case.physical_movements:
        if item.movement_id == movement_id:
            return item
    raise ValueError(f"frozen PhysicalMovement not found: {movement_id}")


def _expand_junction(
    case: FrozenSchemeACase,
    junction_id: str,
    segment_ids: set[str],
    movement_ids: set[str],
) -> None:
    junction = next((item for item in case.junctions if item.junction_id == junction_id), None)
    if junction is None:
        raise ValueError(f"frozen Junction not found: {junction_id}")
    segment_ids.update(junction.related_segment_ids)
    movement_ids.update(
        item.movement_id for item in case.physical_movements if item.junction_id == junction_id
    )


__all__ = ["resolve_scheme_a_fallback"]
