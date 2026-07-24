from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import EvidenceRef
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_labels import (
    build_scheme_a_carrier_labels,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    CarrierKind,
    CarrierTarget,
    ClueScope,
    FallbackUnit,
    FrozenJunction,
    FrozenJunctionSegmentRelation,
    FrozenPhysicalMovement,
    FrozenSchemeACase,
    FrozenSegment,
    RealityChangeClue,
    SegmentType,
    StrategyBaselineRecord,
    StrategyOutcome,
)


def _fixture() -> tuple[FrozenSchemeACase, list[StrategyBaselineRecord], EvidenceRef]:
    evidence = EvidenceRef("source", "input.gpkg", "a" * 64)
    case = FrozenSchemeACase(
        case_key="T10:case",
        family="T10",
        business_id="case",
        sample_id="sample",
        fold=0,
        crs="EPSG:3857",
        source_manifest="manifest.json",
        source_hashes=(),
        junctions=(FrozenJunction("j1", "NORMAL", ("s1", "s2"), (), (evidence,)),),
        segments=(
            FrozenSegment(
                "s1", SegmentType.STANDARD, ("j1", "j2"), (), ("swsd1",), "DIRECTED",
                True, "", "", True, (evidence,),
            ),
            FrozenSegment(
                "s2", SegmentType.STANDARD, ("j1", "j3"), (), ("swsd2",), "DIRECTED",
                True, "", "", True, (evidence,),
            ),
        ),
        junction_segment_relations=(
            FrozenJunctionSegmentRelation("j1", "s1", "ENDPOINT", "ENTER", ("n1",), (evidence,)),
            FrozenJunctionSegmentRelation("j1", "s2", "ENDPOINT", "EXIT", ("n1",), (evidence,)),
        ),
        physical_movements=(
            FrozenPhysicalMovement(
                "m1", "j1", "s1@j1", "s2@j1", CarrierKind.NODE, ("n1",),
                False, True, (evidence,),
            ),
        ),
    )
    baselines = [
        StrategyBaselineRecord(
            "T10:case", "s1", "replaced", "", (), StrategyOutcome.SUCCESS_DIRECT,
            CarrierTarget.USE_RCSD, ("rcsd1",), ("swsd1",), (evidence,),
        ),
        StrategyBaselineRecord(
            "T10:case", "s2", "retained_swsd", "", (),
            StrategyOutcome.SUCCESS_WITH_FALLBACK, CarrierTarget.KEEP_SWSD,
            ("swsd2",), ("swsd2",), (evidence,),
        ),
    ]
    return case, baselines, evidence


def test_junction_conflict_forces_swsd_and_masks_movement_carrier() -> None:
    case, baselines, evidence = _fixture()
    clue = RealityChangeClue.create(
        case_key=case.case_key,
        scope=ClueScope.JUNCTION,
        object_id="j1",
        code="JUNCTION_MAINNODE_CONFLICT",
        detail="conflict",
        evidence_refs=(evidence,),
        recommended_fallback=FallbackUnit.JUNCTION,
    )
    labels = build_scheme_a_carrier_labels(
        case,
        baselines,
        {"scope_type": "t10_case", "business_id": "case", "target_weight": "0.7", "context_weight": "0.7"},
        case.skeleton_signature(),
        [clue],
    )
    by_id = {row.object_id: row for row in labels}
    assert by_id["s1"].carrier_target is CarrierTarget.KEEP_SWSD
    assert by_id["s1"].target_payload == ("swsd1",)
    assert by_id["s1"].available is True
    assert by_id["s2"].carrier_target is CarrierTarget.KEEP_SWSD
    assert by_id["m1"].carrier_target is CarrierTarget.REVIEW_FALLBACK
    assert by_id["m1"].available is False
    assert by_id["m1"].target_payload == ()


def test_segment_conflict_does_not_mask_movement_carrier() -> None:
    case, baselines, evidence = _fixture()
    clue = RealityChangeClue.create(
        case_key=case.case_key,
        scope=ClueScope.SEGMENT,
        object_id="s1",
        code="SEGMENT_CARRIER_CONFLICT",
        detail="conflict",
        evidence_refs=(evidence,),
        recommended_fallback=FallbackUnit.SEGMENT,
    )
    labels = build_scheme_a_carrier_labels(
        case,
        baselines,
        {"scope_type": "t10_case", "business_id": "case", "target_weight": "0.7", "context_weight": "0.7"},
        case.skeleton_signature(),
        [clue],
    )
    by_id = {row.object_id: row for row in labels}
    assert by_id["s1"].carrier_target is CarrierTarget.KEEP_SWSD
    assert by_id["m1"].available is True
    assert by_id["m1"].target_kind is CarrierKind.NODE
    assert by_id["m1"].target_payload == ("n1",)
