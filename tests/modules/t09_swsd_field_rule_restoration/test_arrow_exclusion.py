import pytest

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.arrow_evidence import (
    evaluate_complete_arrow_exclusion,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    ArrowInput,
    EvidenceType,
    ProhibitionReason,
    ProhibitionStatus,
    RoadPair,
    T09ArmMovement,
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
