from shapely.geometry import LineString

from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.restriction_evidence import (
    match_restriction_evidence,
)
from rcsd_topo_poc.modules.t09_swsd_field_rule_restoration.schemas import (
    EvidenceType,
    ProhibitionReason,
    ProhibitionStatus,
    RestrictionInput,
    RoadPair,
    SWSDRoadInput,
    T09ArmMovement,
    T09SwsdArm,
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
    assert result.restriction_coverage == "all_restricted"
    assert result.partial_basis == "not_applicable"
    assert result.remaining_restriction_status == "not_applicable"
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
    assert result.restriction_coverage == "partial_restricted"
    assert result.partial_basis == "exit_arm_subset"
    assert result.remaining_restriction_status == "no_restriction_evidence"
    assert result.confidence == 0.9
    assert tuple(item.road_pair for item in result.evidence_items) == (
        RoadPair("in_1", "out_1"),
    )


def test_restriction_geometry_maps_raw_sw_links_to_swsd_carrier_pair() -> None:
    movement = T09ArmMovement(
        junction_id="j1",
        movement_id="m_geometry",
        from_arm_id="arm_w",
        to_arm_id="arm_n",
        movement_type="right",
        candidate_road_pair_count=1,
        carrier_universe_status="available",
        carrier_road_pairs=(RoadPair("swsd_in_w", "swsd_out_n"),),
    )

    result = match_restriction_evidence(
        movement,
        (
            RestrictionInput(
                restriction_id="rst_raw",
                in_link_id="raw_in_w",
                out_link_id="raw_out_n",
                geometry=LineString([(-12.0, 0.0), (0.0, 0.0), (0.0, 12.0)]),
            ),
        ),
        roads_by_id={
            "swsd_in_w": SWSDRoadInput("swsd_in_w", "n_w", "j1", 2),
            "swsd_out_n": SWSDRoadInput("swsd_out_n", "j1", "n_n", 2),
        },
        road_geometries={
            "swsd_in_w": LineString([(-20.0, 0.0), (0.0, 0.0)]),
            "swsd_out_n": LineString([(0.0, 0.0), (0.0, 20.0)]),
        },
        arms_by_id={
            "arm_w": T09SwsdArm(junction_id="j1", arm_id="arm_w", member_node_ids=("j1",)),
            "arm_n": T09SwsdArm(junction_id="j1", arm_id="arm_n", member_node_ids=("j1",)),
        },
    )

    assert result.prohibition_status == ProhibitionStatus.FULLY_PROHIBITED
    assert len(result.evidence_items) == 1
    evidence = result.evidence_items[0]
    assert evidence.road_pair == RoadPair("swsd_in_w", "swsd_out_n")
    assert evidence.provenance.match_method == "directed_geometry_restriction_to_carrier"
    assert evidence.provenance.field_audit["inLinkID"] == "raw_in_w"
    assert evidence.provenance.field_audit["outLinkID"] == "raw_out_n"
    assert evidence.provenance.field_audit["from_geometry_match"]["road_id"] == "swsd_in_w"
    assert evidence.provenance.field_audit["to_geometry_match"]["road_id"] == "swsd_out_n"


def test_restriction_geometry_rejects_adjacent_junction_on_same_corridor() -> None:
    movement = T09ArmMovement(
        junction_id="j1",
        movement_id="m_adjacent",
        from_arm_id="arm_in",
        to_arm_id="arm_out",
        movement_type="uturn",
        candidate_road_pair_count=1,
        carrier_universe_status="available",
        carrier_road_pairs=(RoadPair("swsd_in", "swsd_out"),),
    )

    result = match_restriction_evidence(
        movement,
        (
            RestrictionInput(
                restriction_id="adjacent",
                in_link_id="raw_in_adjacent",
                out_link_id="raw_out_adjacent",
                geometry=LineString([(-10.0, 0.0), (0.0, 0.0), (0.0, 10.0), (-10.0, 10.0)]),
            ),
        ),
        roads_by_id={
            "swsd_in": SWSDRoadInput("swsd_in", "n_w", "j1", 2),
            "swsd_out": SWSDRoadInput("swsd_out", "j1", "n_w_out", 2),
        },
        road_geometries={
            "swsd_in": LineString([(0.0, 0.0), (100.0, 0.0)]),
            "swsd_out": LineString([(100.0, 10.0), (0.0, 10.0)]),
        },
        arms_by_id={
            "arm_in": T09SwsdArm(junction_id="j1", arm_id="arm_in", member_node_ids=("j1",)),
            "arm_out": T09SwsdArm(junction_id="j1", arm_id="arm_out", member_node_ids=("j1",)),
        },
    )

    assert result.prohibition_status == ProhibitionStatus.NO_PROHIBITION_EVIDENCE
    assert result.restriction_coverage == "no_restriction_evidence"
    assert result.partial_basis == "not_applicable"
    assert result.remaining_restriction_status == "no_restriction_evidence"
    assert result.evidence_items == tuple()
