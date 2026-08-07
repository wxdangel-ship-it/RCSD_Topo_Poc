from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_candidates import (
    build_advance_right_label,
)


def _truth(plan: str) -> dict[str, object]:
    return {
        "case_key": "T10:case",
        "object_id": "advance_right_1",
        "fold": 1,
        "truth_plan_type": plan,
        "truth_rcsd_road_ids": ["r1"],
        "truth_swsd_road_ids": ["s1"],
        "eligible": plan != "REVIEW_FALLBACK",
    }


def test_rcsd_label_requires_complete_candidate_road_set() -> None:
    label = build_advance_right_label(
        _truth("RCSD_ONLY"),
        {"treatment_candidate_road_ids": ["r2"]},
        {"eligible": True},
        {
            "eligible": True,
            "materializer_ready": True,
            "swsd_reachable": True,
            "treatment_truth_component_hits": {"r1": []},
            "treatment_oracle_hit": False,
        },
    )

    assert not label["candidate_reachable"]
    assert not label["plan_task_mask"]


def test_mixed_splice_keeps_both_truth_sources() -> None:
    label = build_advance_right_label(
        _truth("MIXED_SPLICE"),
        {"treatment_candidate_road_ids": ["r1", "r2"]},
        {"eligible": True},
        {
            "eligible": True,
            "materializer_ready": True,
            "swsd_reachable": True,
            "treatment_truth_component_hits": {"r1": ["r2"]},
            "treatment_oracle_hit": True,
        },
    )

    assert label["candidate_reachable"]
    assert label["truth_rcsd_road_ids"] == ["r1"]
    assert label["truth_swsd_road_ids"] == ["s1"]
    assert label["acceptable_rcsd_candidate_ids_by_truth_road"] == {
        "r1": ["r2"]
    }


def test_review_is_fallback_supervision_not_plan_supervision() -> None:
    label = build_advance_right_label(
        _truth("REVIEW_FALLBACK"),
        {"treatment_candidate_road_ids": ["r1"]},
        {"eligible": False},
        {
            "eligible": False,
            "materializer_ready": False,
            "swsd_reachable": False,
            "treatment_truth_component_hits": {"r1": []},
            "treatment_oracle_hit": False,
        },
    )

    assert label["fallback_task_mask"]
    assert not label["plan_task_mask"]
