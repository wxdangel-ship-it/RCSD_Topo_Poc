from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_access_sets import (
    conditioned_candidate_features,
    conditioned_feature_view,
    oof_side_condition,
    selected_road_source,
    teacher_access_road_ids,
    teacher_side_condition,
)


def _road(
    road_id: str,
    source: str,
    start: str,
    end: str,
) -> dict[str, object]:
    return {
        "road_id": road_id,
        "source": source,
        "start_node_id": start,
        "end_node_id": end,
        "feature_values": [0.0] * 40,
    }


def test_selected_road_source_requires_complete_single_source_set() -> None:
    roads = [
        _road("s", "SWSD", "a", "b"),
        _road("r", "RCSD", "c", "d"),
    ]
    assert selected_road_source(["s"], roads) == (
        "SWSD",
        "COMPLETE_ROAD_SOURCE_UNIQUE",
    )
    assert selected_road_source(["r"], roads) == (
        "RCSD",
        "COMPLETE_ROAD_SOURCE_UNIQUE",
    )
    assert selected_road_source(["s", "r"], roads) == (
        "UNRESOLVED",
        "COMPLETE_ROAD_SOURCE_MIXED",
    )
    assert selected_road_source(["missing"], roads) == (
        "UNRESOLVED",
        "COMPLETE_ROAD_MEMBER_MISSING",
    )


def test_teacher_access_prefers_explicit_attachment_action() -> None:
    side = {
        "t01_access_node_id": "n",
        "road_candidates": [
            _road("s", "SWSD", "n", "x"),
            _road("r", "RCSD", "y", "z"),
        ],
    }
    label = {
        "acceptable_access_targets": [{"road_id": "s"}],
    }
    attachment = {
        "attachment_actions": [
            {"swsd_node_id": "n", "rcsd_road_id": "r"}
        ]
    }
    assert teacher_access_road_ids(
        side=side,
        selected_road_ids=["s", "r"],
        access_label=label,
        attachment=attachment,
    ) == ["r"]


def test_teacher_condition_keeps_unknown_exact_access_masked() -> None:
    side = {
        "t01_access_node_id": "n",
        "road_candidates": [_road("r", "RCSD", "a", "b")],
    }
    condition = teacher_side_condition(
        side=side,
        member_label={
            "acceptable_road_ids": ["r"],
            "preferred_decision": "USE_RCSD",
        },
        access_label=None,
        attachment={},
    )
    assert condition["access_source"] == "RCSD"
    assert condition["access_source_resolved"]
    assert not condition["access_road_resolved"]
    assert not condition["complete_release_ready"]
    assert condition["resolution"] == "TEACHER_ACCESS_ROAD_UNKNOWN"


def test_oof_condition_does_not_guess_missing_access_road() -> None:
    side = {
        "t01_access_node_id": "j",
        "road_candidates": [_road("r", "RCSD", "a", "b")],
    }
    condition = oof_side_condition(
        side=side,
        state={
            "complete_road_ids": ["r"],
            "raw_carrier_decision": "USE_RCSD",
            "raw_carrier_probability": 0.9,
            "hierarchical_release_ready": True,
            "access_predictions": [
                {
                    "junc_node_id": "other",
                    "road_id": "r",
                    "road_source": "RCSD",
                    "in_complete_carrier": True,
                    "automatic": True,
                }
            ],
        },
    )
    assert condition["access_source"] == "RCSD"
    assert not condition["access_road_resolved"]
    assert not condition["complete_release_ready"]
    assert condition["resolution"] == "OOF_ACCESS_ROAD_UNRESOLVED"


def test_conditioned_candidate_features_use_locked_access_nodes() -> None:
    row = {
        "local_feature_values": [0.0] * 50,
        "raw_snodeid": "source-access",
        "raw_enodeid": "target-plan",
    }
    values = conditioned_candidate_features(
        row,
        source_nodes={"source-access"},
        target_nodes={"target-plan"},
        source_access_nodes={"source-access"},
        target_access_nodes=set(),
    )
    assert len(values) == 60
    assert values[50:] == [
        1.0,
        0.0,
        1.0,
        0.0,
        1.0,
        1.0,
        1.0,
        0.0,
        0.0,
        0.0,
    ]


def test_conditioned_view_separates_source_from_exact_access() -> None:
    road = _road("r", "RCSD", "a", "b")
    feature = {
        "schema_version": "test",
        "case_key": "case",
        "object_id": "ar",
        "fold": 0,
        "fixed_swsd_road_ids": ["s"],
        "access_valid": True,
        "source_side": {
            "owner_segment_id": "left",
            "t01_access_node_id": "j1",
            "object_feature_values": [0.0] * 64,
            "road_candidates": [road],
            "access_candidates": [],
        },
        "target_side": {
            "owner_segment_id": "right",
            "t01_access_node_id": "j2",
            "object_feature_values": [0.0] * 64,
            "road_candidates": [road],
            "access_candidates": [],
        },
        "candidate_rows": [
            {
                "bundle_id": "b",
                "candidate_road_id": "ar-road",
                "local_feature_values": [0.0] * 50,
                "raw_snodeid": "a",
                "raw_enodeid": "b",
            }
        ],
    }
    locked = {
        "selected_road_ids": ["r"],
        "selected_decision": "USE_RCSD",
        "access_source": "RCSD",
        "access_source_resolved": True,
        "access_road_ids": [],
        "access_road_resolved": False,
        "carrier_probability": 1.0,
        "ordinary_release_ready": True,
        "access_release_ready": False,
        "complete_release_ready": False,
        "resolution": "ACCESS_UNKNOWN",
        "condition_uses_truth": True,
    }
    condition = {
        "source_condition": locked,
        "target_condition": locked,
        "both_access_source_resolved": True,
        "both_access_road_resolved": False,
        "condition_kind": "TEACHER",
    }
    view = conditioned_feature_view(feature, condition)
    assert view["adjacent_context_resolved"]
    assert not view["adjacent_access_road_resolved"]
    assert not view["required_rcsd_access_resolved"]
    assert len(view["source_context"]["plan_features"]) == 64
    assert len(view["source_context"]["status_features"]) == 22
    assert len(view["candidate_rows"][0]["feature_values"]) == 60


def test_swsd_side_preserves_frozen_access_without_new_attachment() -> None:
    road = _road("s", "SWSD", "a", "b")
    feature = {
        "schema_version": "test",
        "case_key": "case",
        "object_id": "ar",
        "fold": 0,
        "fixed_swsd_road_ids": ["fixed"],
        "access_valid": True,
        "source_side": {
            "owner_segment_id": "left",
            "t01_access_node_id": "j1",
            "object_feature_values": [0.0] * 64,
            "road_candidates": [road],
            "access_candidates": [],
        },
        "target_side": {
            "owner_segment_id": "right",
            "t01_access_node_id": "j2",
            "object_feature_values": [0.0] * 64,
            "road_candidates": [road],
            "access_candidates": [],
        },
        "candidate_rows": [],
    }
    locked = {
        "selected_road_ids": ["s"],
        "selected_decision": "KEEP_SWSD",
        "access_source": "SWSD",
        "access_source_resolved": True,
        "access_road_ids": [],
        "access_road_resolved": False,
        "carrier_probability": 1.0,
        "ordinary_release_ready": True,
        "access_release_ready": False,
        "complete_release_ready": False,
        "resolution": "FROZEN_SWSD_ACCESS",
        "condition_uses_truth": True,
    }
    view = conditioned_feature_view(
        feature,
        {
            "source_condition": locked,
            "target_condition": locked,
            "both_access_source_resolved": True,
            "both_access_road_resolved": False,
            "condition_kind": "TEACHER",
        },
    )
    assert not view["adjacent_access_road_resolved"]
    assert view["required_rcsd_access_resolved"]
