from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_final_state_release_gate import (
    compose_final_state_release_rows,
)


def _row(*, automatic: bool, roads: list[str]) -> dict[str, object]:
    return {
        "case_key": "case",
        "object_id": "advance",
        "fold": 0,
        "predicted_plan_type": "SWSD_ONLY",
        "raw_selected_candidate_road_ids": [],
        "raw_selected_fixed_swsd_road_ids": roads,
        "automatic_decision": automatic,
        "safety_target": True,
        "raw_plan_exact": True,
    }


def test_two_seed_gate_accepts_only_the_same_complete_plan() -> None:
    key = ("case", "advance")
    rows = compose_final_state_release_rows(
        {key: _row(automatic=True, roads=["a", "b"])},
        {key: _row(automatic=True, roads=["b", "a"])},
    )
    assert rows[0]["automatic_decision"]
    assert rows[0]["ensemble_plan_consistent"]
    assert not rows[0]["unsafe_automatic"]


def test_two_seed_gate_rejects_one_seed_or_plan_disagreement() -> None:
    key = ("case", "advance")
    one_seed = compose_final_state_release_rows(
        {key: _row(automatic=True, roads=["a"])},
        {key: _row(automatic=False, roads=["a"])},
    )
    assert not one_seed[0]["automatic_decision"]
    disagreement = compose_final_state_release_rows(
        {key: _row(automatic=True, roads=["a"])},
        {key: _row(automatic=True, roads=["b"])},
    )
    assert not disagreement[0]["automatic_decision"]
    assert not disagreement[0]["ensemble_plan_consistent"]
