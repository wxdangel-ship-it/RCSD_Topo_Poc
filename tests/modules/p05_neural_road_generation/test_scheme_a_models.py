from dataclasses import replace

from rcsd_topo_poc.modules.p05_neural_road_generation.jsg_models import EvidenceRef
from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_models import (
    CarrierKind,
    FrozenJunction,
    FrozenJunctionSegmentRelation,
    FrozenPhysicalMovement,
    FrozenSchemeACase,
    FrozenSegment,
    SegmentType,
)


def _case() -> FrozenSchemeACase:
    evidence = (EvidenceRef("source", "input.gpkg", "a" * 64, "s1"),)
    return FrozenSchemeACase(
        case_key="T10:case",
        family="T10",
        business_id="case",
        sample_id="sample",
        fold=0,
        crs="EPSG:3857",
        source_manifest="manifest.json",
        source_hashes=(("input", "a" * 64),),
        junctions=(FrozenJunction("j1", "NORMAL", ("s1",), ("j1",), evidence),),
        segments=(
            FrozenSegment(
                "s1",
                SegmentType.ADVANCE_RIGHT,
                ("j1", "j2"),
                ("j3",),
                ("r1",),
                "DIRECTED",
                True,
                "source@source_node",
                "target@target_node",
                True,
                evidence,
            ),
        ),
        junction_segment_relations=(
            FrozenJunctionSegmentRelation("j1", "s1", "ENDPOINT", "EXIT", ("n1",), evidence),
        ),
        physical_movements=(
            FrozenPhysicalMovement(
                "m1",
                "j1",
                "s1@j1",
                "s1@j1",
                CarrierKind.NODE,
                ("n1",),
                False,
                True,
                evidence,
            ),
        ),
    )


def test_skeleton_signature_ignores_carrier_choice_and_provenance() -> None:
    case = _case()
    changed_movement = replace(
        case.physical_movements[0],
        carrier_kind=CarrierKind.ROAD,
        carrier_ids=("r99",),
        evidence_refs=(EvidenceRef("other", "other.gpkg", "b" * 64),),
    )
    changed = replace(
        case,
        source_manifest="other-manifest.json",
        source_hashes=(("other", "b" * 64),),
        physical_movements=(changed_movement,),
    )
    assert case.skeleton_signature() == changed.skeleton_signature()


def test_advance_right_is_a_formal_segment_without_legacy_object_collection() -> None:
    payload = _case().to_dict()
    assert payload["segments"][0]["segment_type"] == "ADVANCE_RIGHT"
    assert payload["segments"][0]["swsd_road_ids"] == ["r1"]
    assert payload["segments"][0]["source_segment_access"] == "source@source_node"
    assert "segment_connectors" not in payload
    assert payload["content_repair"] is False
    assert payload["silent_fix"] is False
