from dataclasses import replace

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import EvidenceRef
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_fallback import (
    resolve_scheme_a_fallback,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    CarrierKind,
    ClueScope,
    FallbackOutcome,
    FallbackUnit,
    FrozenJunction,
    FrozenJunctionSegmentRelation,
    FrozenPhysicalMovement,
    FrozenSchemeACase,
    FrozenSegment,
    SegmentType,
)


def _case(*, movement_shared: bool = False) -> FrozenSchemeACase:
    evidence = (EvidenceRef("source", "input.gpkg", "a" * 64),)
    movement = FrozenPhysicalMovement(
        "m1",
        "j1",
        "s1@j1",
        "s2@j1",
        CarrierKind.NODE,
        ("n1",),
        not movement_shared,
        movement_shared,
        evidence,
    )
    return FrozenSchemeACase(
        case_key="T10:case",
        family="T10",
        business_id="case",
        sample_id="sample",
        fold=0,
        crs="EPSG:3857",
        source_manifest="manifest.json",
        source_hashes=(),
        junctions=(FrozenJunction("j1", "NORMAL", ("s1", "s2"), (), evidence),),
        segments=(
            FrozenSegment(
                "s1", SegmentType.STANDARD, ("j1", "j2"), (), ("r1",), "DIRECTED", True,
                "", "", True, evidence,
            ),
            FrozenSegment(
                "s2", SegmentType.STANDARD, ("j1", "j3"), (), ("r2",), "DIRECTED", False,
                "", "", True, evidence,
            ),
        ),
        junction_segment_relations=(
            FrozenJunctionSegmentRelation("j1", "s1", "ENDPOINT", "ENTER", ("n1",), evidence),
            FrozenJunctionSegmentRelation("j1", "s2", "ENDPOINT", "EXIT", ("n1",), evidence),
        ),
        physical_movements=(movement,),
    )


def test_exclusive_movement_fallback_stays_local() -> None:
    plan = resolve_scheme_a_fallback(_case(), ClueScope.MOVEMENT, "m1")
    assert plan.unit is FallbackUnit.MOVEMENT
    assert plan.case_key == "T10:case"
    assert plan.movement_ids == ("m1",)
    assert plan.segment_ids == ()
    assert plan.outcome is FallbackOutcome.SUCCESS_WITH_FALLBACK


def test_shared_movement_escalates_to_junction_and_fails_if_any_segment_is_illegal() -> None:
    plan = resolve_scheme_a_fallback(_case(movement_shared=True), ClueScope.MOVEMENT, "m1")
    assert plan.unit is FallbackUnit.JUNCTION
    assert plan.junction_ids == ("j1",)
    assert plan.segment_ids == ("s1", "s2")
    assert plan.outcome is FallbackOutcome.FAIL
    assert any("s2" in reason for reason in plan.failure_reasons)


def test_segment_fallback_is_minimal_closure() -> None:
    plan = resolve_scheme_a_fallback(_case(), ClueScope.SEGMENT, "s1", clue_ids=("c1",))
    assert plan.unit is FallbackUnit.SEGMENT
    assert plan.segment_ids == ("s1",)
    assert plan.movement_ids == ()
    assert plan.retained_swsd_road_ids == ("r1",)
    assert plan.clue_ids == ("c1",)
    assert plan.outcome is FallbackOutcome.SUCCESS_WITH_FALLBACK


def test_movement_without_carrier_is_a_failed_fallback() -> None:
    case = _case()
    movement = replace(case.physical_movements[0], carrier_kind=CarrierKind.UNKNOWN, carrier_ids=())
    plan = resolve_scheme_a_fallback(
        replace(case, physical_movements=(movement,)),
        ClueScope.MOVEMENT,
        "m1",
    )
    assert plan.unit is FallbackUnit.MOVEMENT
    assert plan.outcome is FallbackOutcome.FAIL
