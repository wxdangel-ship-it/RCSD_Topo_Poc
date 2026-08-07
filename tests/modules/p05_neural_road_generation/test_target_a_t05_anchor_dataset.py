from __future__ import annotations

import math
from pathlib import Path

from shapely.geometry import LineString, Point

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_business_adjudications import (
    user_anchor_adjudication,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_t05_anchor_dataset import (
    _RawNodeGroup,
    _RawRoad,
    _anchor_status_is_supervised,
    _anchor_status_for_audit,
    _arm_context_features,
    _canonical_id,
    _manual_anchor_status,
    _manual_candidate_id,
    _nearby_group_bundles,
    _read_t11_manual_labels,
    _road_corridor_features,
    _road_member_local_features,
    _split_ids,
)


def test_t05_anchor_status_preserves_no_evidence_and_unknown_failure() -> None:
    assert _anchor_status_for_audit({"status": "0"}) is AnchorStatus.SUCCESS
    assert (
        _anchor_status_for_audit(
            {"status": "1", "scene": "no_related_rcsd"}
        )
        is AnchorStatus.NO_EVIDENCE
    )
    assert (
        _anchor_status_for_audit(
            {"status": "1", "scene": "failure", "reason": "unknown"}
        )
        is AnchorStatus.ABSTAIN
    )


def test_missing_t05_relation_is_unknown_not_supervised_failure() -> None:
    assert not _anchor_status_is_supervised(audit=None, manual=None)
    assert _anchor_status_is_supervised(
        audit={"status": "1", "scene": "no_related_rcsd"},
        manual=None,
    )


def test_t05_anchor_ids_are_metadata_not_numeric_features() -> None:
    assert _canonical_id("622700016.0") == "622700016"
    assert _canonical_id("1010443_1010444") == "1010443_1010444"
    assert _canonical_id("5395908758673924") == "5395908758673924"
    assert _canonical_id("0") == ""
    assert _split_ids("[1, 2]") == {"1", "2"}
    assert _split_ids("1|2,3") == {"1", "2", "3"}


def test_anchor_arm_context_rewards_matching_road_bearings() -> None:
    swsd = ((0.0, 1, 2), (math.pi / 2.0, 1, 2))
    matched = _arm_context_features(swsd, swsd)
    opposed = _arm_context_features(
        swsd,
        ((math.pi, 1, 2), (-math.pi / 2.0, 1, 2)),
    )

    assert matched[3] > opposed[3]
    assert matched[4] > opposed[4]
    assert matched[5] == 1.0


def test_road_member_local_features_express_split_contact_position() -> None:
    road = _RawRoad(
        road_id="1",
        start_node_id="10",
        end_node_id="20",
        direction=2,
        function_class=3,
        geometry=LineString(((0.0, 0.0), (100.0, 0.0))),
    )

    row = _road_member_local_features(
        road,
        Point(25.0, 3.0),
        radius_m=200.0,
    )

    assert len(row) == 12
    assert row[0] == 1.0
    assert math.isclose(row[1], 3.0 / 200.0)
    assert row[2:6] == (1.0, 1.0, 1.0, 1.0)
    assert math.isclose(row[6], 0.25)
    assert math.isclose(row[7], math.hypot(25.0, 3.0) / 200.0)
    assert math.isclose(row[8], math.hypot(75.0, 3.0) / 200.0)
    assert math.isclose(row[9], 0.0)
    assert math.isclose(row[10], 1.0)
    assert math.isclose(row[11], 0.2)


def test_road_corridor_features_compare_rcsd_with_frozen_swsd_roads() -> None:
    swsd = _RawRoad(
        road_id="swsd",
        start_node_id="1",
        end_node_id="2",
        direction=2,
        function_class=3,
        geometry=LineString(((0.0, 0.0), (100.0, 0.0))),
    )
    aligned = _RawRoad(
        road_id="aligned",
        start_node_id="10",
        end_node_id="20",
        direction=2,
        function_class=3,
        geometry=LineString(((0.0, 2.0), (100.0, 2.0))),
    )
    remote = _RawRoad(
        road_id="remote",
        start_node_id="30",
        end_node_id="40",
        direction=2,
        function_class=3,
        geometry=LineString(((0.0, 50.0), (100.0, 50.0))),
    )

    aligned_features = _road_corridor_features(
        (aligned,),
        (swsd,),
        Point(0.0, 0.0),
        radius_m=200.0,
    )
    remote_features = _road_corridor_features(
        (remote,),
        (swsd,),
        Point(0.0, 0.0),
        radius_m=200.0,
    )

    assert len(aligned_features) == 9
    assert math.isclose(aligned_features[0], 2.0 / 200.0)
    assert aligned_features[1] == 1.0
    assert remote_features[0] > aligned_features[0]
    assert remote_features[1] == 0.0


def test_t11_manual_anchor_labels_are_explicit_training_truth(
    tmp_path: Path,
) -> None:
    path = tmp_path / "t11.csv"
    path.write_text(
        "case_id,target_id,manual_relation_type,selected_ids\n"
        "706247,55022132,no_valid_relation,\n"
        "706247,707913,1v1_rcsd_road,2|1\n"
        "706247,706416,1v1_rcsd_junction,9\n",
        encoding="utf-8",
    )

    labels, resolved = _read_t11_manual_labels(path)

    assert resolved == path.resolve()
    no_valid = labels[("T10:706247", "55022132")]
    assert _manual_anchor_status(no_valid) is AnchorStatus.ABSTAIN
    assert _manual_candidate_id(no_valid) == ""
    road = labels[("T10:706247", "707913")]
    assert _manual_anchor_status(road) is AnchorStatus.SUCCESS
    assert _manual_candidate_id(road) == "ROAD:1|2"
    junction = labels[("T10:706247", "706416")]
    assert _manual_candidate_id(junction) == "NODE:9"
    assert (
        _manual_candidate_id(
            junction,
            group_id_by_node_id={"9": "10"},
        )
        == "NODE:10"
    )


def test_truth_free_multi_node_anchor_candidates_are_bounded() -> None:
    groups = tuple(
        _RawNodeGroup(
            group_id=str(index),
            member_ids=(str(index),),
            points=(Point(float(index), 0.0),),
            kinds=(1,),
            cross_flags=(0,),
            layers=(0,),
        )
        for index in range(10)
    )

    bundles = _nearby_group_bundles(groups)
    bundle_ids = {row.group_id for row in bundles}

    assert len(bundles) == math.comb(6, 2) + math.comb(4, 3)
    assert "0|5" in bundle_ids
    assert "0|2|3" in bundle_ids
    assert "0|6" not in bundle_ids


def test_user_visual_anchor_truth_does_not_invent_exact_candidate() -> None:
    adjudication = user_anchor_adjudication(
        "T10-Error:501386978_504378551",
        "621989990",
    )

    assert adjudication is not None
    assert adjudication.business_status == "SUCCESS"
    assert adjudication.acceptable_candidate_ids == ()
    assert adjudication.status_supervised
    assert adjudication.sample_weight == 1.0
    assert adjudication.release_decision == "ABSTAIN"
    assert adjudication.fallback_scope == "SEGMENT"
    assert not adjudication.reality_change_clue


def test_user_confirmed_road_only_split_is_exact_candidate_truth() -> None:
    adjudication = user_anchor_adjudication(
        "T10:605415675",
        "1633165",
    )

    assert adjudication is not None
    assert adjudication.segment_id == "1633165_512279283"
    assert adjudication.business_status == "SUCCESS"
    assert adjudication.acceptable_candidate_ids == (
        "ROAD:5391329551450177|5391329551450189|"
        "5391329551450260|5391329551450265|"
        "5391330021350944|5391330021350949",
    )
    assert adjudication.status_supervised
    assert adjudication.sample_weight == 1.0
    assert adjudication.release_decision is None
    assert adjudication.fallback_scope is None
    assert adjudication.reality_change_clue is None
