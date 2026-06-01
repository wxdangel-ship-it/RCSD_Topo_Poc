import pytest
from shapely.geometry import LineString

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arrow_evidence import (
    evaluate_complete_arrow_exclusion,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    ArrowInput,
    EvidenceType,
    ProhibitionReason,
    ProhibitionStatus,
    RoadPair,
    SWSDRoadInput,
    T09ArmMovement,
    T09SwsdArm,
)


def _movement(movement_type: str = "left") -> T09ArmMovement:
    return T09ArmMovement(
        junction_id="j1",
        movement_id="m1",
        from_arm_id="from",
        to_arm_id="to",
        movement_type=movement_type,
        candidate_road_pair_count=1,
        carrier_universe_status="available",
        carrier_road_pairs=(RoadPair("in_1", "out_1"),),
    )


def test_complete_arrow_exclusion_generates_secondary_prohibition_evidence() -> None:
    result = evaluate_complete_arrow_exclusion(
        _movement("left"),
        (
            ArrowInput(
                arrow_id="arr_1",
                road_id="in_1",
                lane_codes=("a", "c"),
            ),
        ),
    )

    assert result.prohibition_status == ProhibitionStatus.FULLY_PROHIBITED
    assert result.prohibition_reason == ProhibitionReason.COMPLETE_ARROW_EXCLUSION
    assert result.evidence_items[0].evidence_type == EvidenceType.COMPLETE_ARROW_EXCLUSION
    assert result.evidence_items[0].supports_prohibition is True


@pytest.mark.parametrize("code", ("9", "o"))
def test_uninvestigated_or_empty_arrow_does_not_generate_strong_prohibition(code: str) -> None:
    result = evaluate_complete_arrow_exclusion(
        _movement("left"),
        (
            ArrowInput(
                arrow_id=f"arr_{code}",
                road_id="in_1",
                lane_codes=(code,),
            ),
        ),
    )

    assert result.prohibition_status == ProhibitionStatus.UNKNOWN
    assert result.prohibition_reason == ProhibitionReason.INSUFFICIENT_EVIDENCE
    assert result.evidence_items[0].evidence_type == EvidenceType.ARROW
    assert result.evidence_items[0].supports_prohibition is False


def test_incomplete_arrow_sequence_is_ambiguous_not_prohibition() -> None:
    result = evaluate_complete_arrow_exclusion(
        _movement("left"),
        (
            ArrowInput(
                arrow_id="arr_incomplete",
                road_id="in_1",
                lane_codes=("a", "c"),
                lane_sequence_complete=False,
            ),
        ),
    )

    assert result.prohibition_status == ProhibitionStatus.UNKNOWN
    assert result.evidence_items[0].evidence_status == "arrow_incomplete_for_prohibition"
    assert result.evidence_items[0].supports_prohibition is False


def test_arrow_supporting_movement_blocks_arrow_exclusion() -> None:
    result = evaluate_complete_arrow_exclusion(
        _movement("left"),
        (
            ArrowInput(
                arrow_id="arr_left",
                road_id="in_1",
                lane_codes=("g",),
            ),
        ),
    )

    assert result.prohibition_status == ProhibitionStatus.NO_PROHIBITION_EVIDENCE
    assert result.arrow_supports_movement is True
    assert result.evidence_items[0].evidence_status == "arrow_supports_movement"


def test_arrow_geometry_maps_raw_sw_link_to_swsd_approach_road() -> None:
    movement = T09ArmMovement(
        junction_id="j1",
        movement_id="m_geometry",
        from_arm_id="from",
        to_arm_id="to",
        movement_type="left",
        candidate_road_pair_count=1,
        carrier_universe_status="available",
        carrier_road_pairs=(RoadPair("swsd_in_w", "swsd_out_n"),),
    )

    result = evaluate_complete_arrow_exclusion(
        movement,
        (
            ArrowInput(
                arrow_id="arrow_raw",
                road_id="raw_in_w",
                lane_codes=("a", "c"),
                geometry=LineString([(-12.0, 0.0), (-1.0, 0.0)]),
            ),
        ),
        roads_by_id={
            "swsd_in_w": SWSDRoadInput("swsd_in_w", "n_w", "j1", 2),
        },
        road_geometries={
            "swsd_in_w": LineString([(-20.0, 0.0), (0.0, 0.0)]),
        },
        arms_by_id={
            "from": T09SwsdArm(junction_id="j1", arm_id="from", member_node_ids=("j1",)),
        },
    )

    assert result.prohibition_status == ProhibitionStatus.FULLY_PROHIBITED
    evidence = result.evidence_items[0]
    assert evidence.evidence_status == "prohibited_by_complete_arrow_exclusion"
    assert evidence.provenance.source_id == "arrow_raw"
    match_audit = evidence.provenance.field_audit["approach_road_matches"]["swsd_in_w"]
    assert match_audit["raw_arrow_linkid"] == "raw_in_w"
    assert match_audit["match_method"] == "directed_geometry_arrow_approach"


def test_uppercase_straight_arrow_code_is_normalized_before_exclusion() -> None:
    result = evaluate_complete_arrow_exclusion(
        _movement("left"),
        (
            ArrowInput(
                arrow_id="arr_upper_a",
                road_id="in_1",
                lane_codes=("A", "c"),
            ),
        ),
    )

    assert result.prohibition_status == ProhibitionStatus.FULLY_PROHIBITED
    assert result.evidence_items[0].evidence_status == "prohibited_by_complete_arrow_exclusion"
