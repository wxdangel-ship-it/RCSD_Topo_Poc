from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_final_state_conditioning import (
    final_ordinary_side_condition,
)


def _side() -> dict[str, object]:
    return {
        "owner_segment_id": "ordinary",
        "t01_access_node_id": "access",
        "road_candidates": [
            {
                "road_id": "swsd-a",
                "source": "SWSD",
                "start_node_id": "access",
                "end_node_id": "middle",
            },
            {
                "road_id": "swsd-b",
                "source": "SWSD",
                "start_node_id": "middle",
                "end_node_id": "access",
            },
            {
                "road_id": "rcsd",
                "source": "RCSD",
                "start_node_id": "raw-a",
                "end_node_id": "raw-b",
            },
        ],
    }


def test_rejected_ordinary_prediction_becomes_explicit_swsd_fallback() -> None:
    condition = final_ordinary_side_condition(
        _side(),
        prediction={
            "automatic": False,
            "predicted_decision": "USE_RCSD",
            "selected_road_ids": ["rcsd"],
        },
    )
    assert condition["selected_decision"] == "ABSTAIN"
    assert condition["final_outcome_kind"] == "FALLBACK_SWSD"
    assert condition["fallback_applied"]
    assert not condition["ordinary_automatic"]
    assert condition["selected_road_ids"] == ["swsd-a", "swsd-b"]
    assert condition["access_road_ids"] == ["swsd-a", "swsd-b"]
    assert condition["final_state_ready"]


def test_positive_keep_remains_separate_from_fallback() -> None:
    condition = final_ordinary_side_condition(
        _side(),
        prediction={
            "automatic": True,
            "predicted_decision": "KEEP_SWSD",
            "selected_road_ids": ["swsd-a", "swsd-b"],
            "confidence": 0.99,
        },
    )
    assert condition["selected_decision"] == "KEEP_SWSD"
    assert condition["final_outcome_kind"] == "POSITIVE_KEEP_SWSD"
    assert not condition["fallback_applied"]
    assert condition["ordinary_automatic"]
    assert condition["complete_release_ready"]


def test_auto_rcsd_waits_for_neural_attachment_resolution() -> None:
    condition = final_ordinary_side_condition(
        _side(),
        prediction={
            "automatic": True,
            "predicted_decision": "USE_RCSD",
            "selected_road_ids": ["rcsd"],
            "confidence": 0.99,
        },
    )
    assert condition["access_source"] == "RCSD"
    assert condition["access_source_resolved"]
    assert not condition["access_road_resolved"]
    assert not condition["final_state_ready"]
    assert condition["resolution"] == "AUTO_USE_RCSD_ACCESS_PENDING"


def test_missing_owner_does_not_invent_a_fallback_relation() -> None:
    side = _side()
    side["owner_segment_id"] = ""
    condition = final_ordinary_side_condition(side, prediction=None)
    assert condition["selected_road_ids"] == []
    assert not condition["final_state_ready"]
    assert condition["resolution"] == "OWNER_SEGMENT_MISSING"
