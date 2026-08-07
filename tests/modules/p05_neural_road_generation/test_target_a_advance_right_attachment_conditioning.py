from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_attachment_conditioning import (
    attachment_side_condition,
)


def _base(decision: str) -> dict[str, object]:
    return {
        "selected_road_ids": ["ordinary-road"],
        "selected_decision": decision,
        "access_source": "RCSD",
        "access_source_resolved": True,
        "access_road_ids": ["legacy-road"],
        "access_road_resolved": True,
        "ordinary_release_ready": True,
        "access_release_ready": True,
        "complete_release_ready": True,
        "resolution": "LEGACY",
        "condition_uses_truth": False,
    }


def _side() -> dict[str, object]:
    return {
        "access_candidates": [
            {
                "proposal_id": "teacher-proposal",
                "road_id": "teacher-road",
                "source": "RCSD",
            },
            {
                "proposal_id": "oof-proposal",
                "road_id": "oof-road",
                "source": "RCSD",
            },
        ]
    }


def _prediction() -> dict[str, object]:
    return {
        "target_proposal_id": "teacher-proposal",
        "selected_proposal_id": "oof-proposal",
        "automatic": False,
    }


def test_teacher_and_oof_lock_different_attachment_views() -> None:
    teacher = attachment_side_condition(
        _base("USE_RCSD"),
        side_feature=_side(),
        prediction=_prediction(),
        condition_view="TEACHER",
        explicit_rcsd_action=True,
    )
    oof = attachment_side_condition(
        _base("USE_RCSD"),
        side_feature=_side(),
        prediction=_prediction(),
        condition_view="STRICT_OOF",
        explicit_rcsd_action=True,
    )
    assert teacher["access_proposal_ids"] == ["teacher-proposal"]
    assert teacher["access_road_ids"] == ["teacher-road"]
    assert teacher["complete_release_ready"]
    assert oof["access_proposal_ids"] == ["oof-proposal"]
    assert oof["access_road_ids"] == ["oof-road"]
    assert not oof["complete_release_ready"]


def test_oof_keep_swsd_suppresses_rcsd_attachment_prediction() -> None:
    result = attachment_side_condition(
        _base("KEEP_SWSD"),
        side_feature=_side(),
        prediction=_prediction(),
        condition_view="STRICT_OOF",
        explicit_rcsd_action=True,
    )
    assert result["access_source"] == "SWSD"
    assert result["access_proposal_ids"] == []
    assert result["access_road_resolved"]


def test_unreachable_teacher_rcsd_attachment_stays_unresolved() -> None:
    result = attachment_side_condition(
        _base("USE_RCSD"),
        side_feature=_side(),
        prediction=None,
        condition_view="TEACHER",
        explicit_rcsd_action=True,
    )
    assert result["access_source"] == "RCSD"
    assert result["access_source_resolved"]
    assert not result["access_road_resolved"]
    assert result["access_road_ids"] == []
