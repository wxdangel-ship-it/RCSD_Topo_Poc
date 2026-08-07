from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_conditioning import (
    SIDE_STATUS_FEATURE_NAMES,
    _candidate_relation_values,
    _side_status_features,
    lock_ordinary_plan,
)


def _group():
    return {
        "candidates": [
            {
                "plan_id": "keep",
                "decision": "KEEP_SWSD",
            },
            {
                "plan_id": "use",
                "decision": "USE_RCSD",
            },
            {
                "plan_id": "abstain",
                "decision": "ABSTAIN",
            },
        ]
    }


def test_release_fallback_locks_complete_keep_plan() -> None:
    selected, reason = lock_ordinary_plan(
        group=_group(),
        prediction={
            "release_fallback_required": True,
            "raw_predicted_plan_id": "use",
        },
    )
    assert selected is not None
    assert selected["plan_id"] == "keep"
    assert reason == "RELEASE_FALLBACK_KEEP_SWSD"


def test_raw_plan_is_locked_only_when_release_does_not_fallback() -> None:
    selected, reason = lock_ordinary_plan(
        group=_group(),
        prediction={
            "release_fallback_required": False,
            "raw_predicted_plan_id": "use",
        },
    )
    assert selected is not None
    assert selected["decision"] == "USE_RCSD"
    assert reason == "OOF_PLAN_LOCKED"


def test_missing_oof_never_guesses_a_plan() -> None:
    selected, reason = lock_ordinary_plan(
        group=_group(),
        prediction=None,
    )
    assert selected is None
    assert reason == "OOF_MISSING"


def test_side_status_uses_predictions_not_training_truth() -> None:
    values = _side_status_features(
        source="SWSD",
        selected_decision="KEEP_SWSD",
        prediction={
            "raw_predicted_decision": "USE_RCSD",
            "effective_decision": "ABSTAIN",
            "release_fallback_required": True,
            "all_required_anchors_resolved": False,
            "all_required_anchors_success": False,
            "raw_predicted_probability": 0.8,
            "fallback_none_probability": 0.1,
            "fallback_segment_probability": 0.7,
            "fallback_junction_probability": 0.2,
            "predicted_clue_probability": 0.3,
            "required_anchor_count": 2,
            "anchor_resolved_count": 1,
            "anchor_success_count": 1,
            "preferred_decision": "KEEP_SWSD",
        },
    )
    assert len(values) == len(SIDE_STATUS_FEATURE_NAMES)
    assert values[0] == 1.0
    assert values[6] == 1.0
    assert values[10] == 1.0
    assert values[11] == 1.0
    assert values[-2:] == [0.5, 0.5]


def test_candidate_relation_is_exact_id_join_only() -> None:
    values = _candidate_relation_values(
        snode="r1",
        enode="r2",
        source_nodes={"r1"},
        target_nodes={"r2"},
        source_access="swsd-a",
        target_access="swsd-b",
    )
    assert values[:6] == [1.0, 0.0, 1.0, 0.0, 1.0, 1.0]
    assert values[6:] == [0.0, 0.0, 0.0, 0.0]
