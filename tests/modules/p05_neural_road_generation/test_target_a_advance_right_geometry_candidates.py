from __future__ import annotations

from shapely.geometry import LineString

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_geometry_candidates import (
    ATTACHMENT_GEOMETRY_FEATURE_NAMES,
    SPLICE_GEOMETRY_FEATURE_NAMES,
    _attachment_proposal,
    _attachment_proposals,
    _splice_proposal,
    _variant_proposal_id_sets,
    _variant_proposal_ids,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_geometry_teacher import (
    GeometryRoad,
)


def _road(road_id: str, coordinates) -> GeometryRoad:
    return GeometryRoad(
        road_id=road_id,
        start_node_id=f"{road_id}_s",
        end_node_id=f"{road_id}_e",
        geometry=LineString(coordinates),
    )


def test_attachment_candidate_is_truth_free_projected_position() -> None:
    row = _attachment_proposal(
        case_key="T10:case",
        object_id="ar",
        side="source",
        candidate=_road("candidate", [(0, 0), (5, 0)]),
        endpoint_index=0,
        target=_road("ordinary", [(-2, -2), (-2, 2)]),
        candidate_feature_values=[0.0] * 60,
        target_member_feature_values=[0.0] * 24,
        parent_piece="SOURCE_PART",
    )
    assert row["gap_m"] == 2.0
    assert row["target_fraction"] == 0.5
    assert row["operation"] == "SPLIT_ROAD"
    assert row["parent_piece"] == "SOURCE_PART"
    assert not row["feature_uses_truth"]
    assert len(row["geometry_feature_values"]) == len(
        ATTACHMENT_GEOMETRY_FEATURE_NAMES
    )


def test_splice_candidate_contains_two_break_positions() -> None:
    row = _splice_proposal(
        case_key="T10:case",
        object_id="ar",
        candidate=_road("candidate", [(0, 0), (10, 0)]),
        swsd=_road("swsd", [(5, 1), (5, 3)]),
        candidate_feature_values=[0.0] * 60,
    )
    assert row["rcsd_fraction"] == 0.5
    assert row["swsd_fraction"] == 0.0
    assert row["gap_m"] == 1.0
    assert len(row["geometry_feature_values"]) == len(
        SPLICE_GEOMETRY_FEATURE_NAMES
    )


def test_teacher_variant_maps_to_candidate_ids() -> None:
    variant = {
        "source_attachment": {
            "selected_rcsd_road_id": "candidate",
            "selected_endpoint_index": 0,
            "target_ordinary_road_id": "ordinary",
            "operation": "SPLIT_ROAD",
        },
        "target_attachment": None,
        "middle_splice": {
            "rcsd_road_id": "candidate",
            "swsd_road_id": "swsd",
        },
    }
    assert len(_variant_proposal_ids(variant)) == 2
    assert len(_variant_proposal_id_sets(variant)) == 2


def test_interior_attachment_emits_both_acceptable_parent_pieces() -> None:
    rows = _attachment_proposals(
        case_key="T10:case",
        object_id="ar",
        side="source",
        candidate=_road("candidate", [(0, 0), (5, 0)]),
        endpoint_index=0,
        target=_road("ordinary", [(-2, -2), (-2, 2)]),
        candidate_feature_values=[0.0] * 60,
        target_member_feature_values=[0.0] * 24,
    )
    assert {row["parent_piece"] for row in rows} == {
        "SOURCE_PART",
        "TARGET_PART",
    }
    assert len({row["proposal_id"] for row in rows}) == 2
