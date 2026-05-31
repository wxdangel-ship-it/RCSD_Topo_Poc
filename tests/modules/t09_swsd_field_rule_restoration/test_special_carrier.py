from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    EvidenceType,
    ProhibitionReason,
    RoadAttributes,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.special_carrier import (
    detect_special_carrier_evidence,
)


def test_special_carriers_are_displacement_evidence_not_prohibitions() -> None:
    evidence_items = detect_special_carrier_evidence(
        junction_id="j1",
        arm_id="arm_1",
        roads=(
            RoadAttributes(road_id="advance_left", formway=256),
            RoadAttributes(road_id="aux_right", kind="road12|road0a"),
            RoadAttributes(road_id="pre_right", kind="road12"),
        ),
    )

    statuses = {item.evidence_status for item in evidence_items}

    assert statuses == {
        "advance_left_carrier_exists",
        "auxiliary_right_turn_carrier_exists",
        "pre_junction_non_aux_advance_right_relation",
    }
    assert all(item.evidence_type == EvidenceType.SPECIAL_CARRIER for item in evidence_items)
    assert all(item.prohibition_reason == ProhibitionReason.SPECIAL_CARRIER_DISPLACEMENT for item in evidence_items)
    assert all(item.supports_prohibition is False for item in evidence_items)
