from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.restriction_evidence import (
    match_restriction_evidence,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    EvidenceType,
    ProhibitionReason,
    ProhibitionStatus,
    RestrictionInput,
    RoadPair,
    T09ArmMovement,
)


def _movement(*road_pairs: RoadPair) -> T09ArmMovement:
    return T09ArmMovement(
        junction_id="j1",
        movement_id="m1",
        from_arm_id="from",
        to_arm_id="to",
        movement_type="left",
        candidate_road_pair_count=len(road_pairs),
        carrier_universe_status="available",
        carrier_road_pairs=road_pairs,
    )


def test_restriction_pair_match_generates_explicit_prohibition_evidence() -> None:
    movement = _movement(RoadPair("in_1", "out_1"))

    result = match_restriction_evidence(
        movement,
        (
            RestrictionInput(
                restriction_id="rst_1",
                in_link_id="in_1",
                out_link_id="out_1",
            ),
        ),
    )

    assert result.prohibition_status == ProhibitionStatus.FULLY_PROHIBITED
    assert result.prohibition_reason == ProhibitionReason.EXPLICIT_RESTRICTION
    assert result.confidence == 1.0
    assert len(result.evidence_items) == 1
    assert result.evidence_items[0].evidence_type == EvidenceType.RESTRICTION
    assert result.evidence_items[0].supports_prohibition is True
    assert result.evidence_items[0].provenance.field_audit == {
        "inLinkID": "in_1",
        "outLinkID": "out_1",
    }


def test_single_restriction_does_not_expand_to_full_multi_pair_movement() -> None:
    movement = _movement(
        RoadPair("in_1", "out_1"),
        RoadPair("in_1", "out_2"),
    )

    result = match_restriction_evidence(
        movement,
        (
            RestrictionInput(
                restriction_id="rst_1",
                in_link_id="in_1",
                out_link_id="out_1",
            ),
        ),
    )

    assert result.prohibition_status == ProhibitionStatus.PARTIALLY_PROHIBITED
    assert result.confidence == 0.9
    assert tuple(item.road_pair for item in result.evidence_items) == (
        RoadPair("in_1", "out_1"),
    )
