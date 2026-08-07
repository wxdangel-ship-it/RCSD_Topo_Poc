from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_set_training import (
    choose_set_selection_threshold,
    choose_zero_error_set_threshold,
    decode_access_set_probabilities,
    multi_solution_set_loss,
)


def _probability_row(
    probabilities: list[float],
    acceptable: list[list[int]],
) -> dict[str, object]:
    count = len(probabilities)
    return {
        "case_key": "T10:case",
        "segment_id": "segment",
        "junction_id": "junction",
        "fold": 1,
        "proposal_ids": [f"p{index}" for index in range(count)],
        "road_ids": [f"r{index}" for index in range(count)],
        "operations": ["USE_ENDPOINT"] * count,
        "fractions": [0.0] * count,
        "probabilities": probabilities,
        "acceptable_index_sets": acceptable,
        "oof_anchor_release_ready": True,
        "upstream_plan_release_blocked": False,
    }


def test_set_loss_rewards_all_jointly_required_members() -> None:
    expected = multi_solution_set_loss(
        torch.tensor([5.0, -5.0, 5.0]),
        ((0, 2),),
    )
    missing = multi_solution_set_loss(
        torch.tensor([5.0, -5.0, -5.0]),
        ((0, 2),),
    )
    assert expected < missing


def test_set_loss_takes_minimum_over_valid_multi_solution_sets() -> None:
    loss = multi_solution_set_loss(
        torch.tensor([-5.0, 5.0, -5.0]),
        ((0,), (1,)),
    )
    wrong = multi_solution_set_loss(
        torch.tensor([-5.0, 5.0, -5.0]),
        ((0,),),
    )
    assert loss < wrong


def test_decoder_compares_the_complete_set_and_never_returns_empty() -> None:
    exact = decode_access_set_probabilities(
        [_probability_row([0.9, 0.1, 0.8], [[0, 2]])],
        selection_threshold=0.5,
    )[0]
    assert exact["predicted_indices"] == [0, 2]
    assert exact["raw_set_exact"] is True

    nonempty = decode_access_set_probabilities(
        [_probability_row([0.2, 0.3], [[1]])],
        selection_threshold=0.9,
    )[0]
    assert nonempty["predicted_indices"] == [1]


def test_selection_threshold_is_fit_on_complete_set_exact() -> None:
    rows = [
        _probability_row([0.8, 0.45], [[0]]),
        {
            **_probability_row([0.7, 0.6], [[0, 1]]),
            "junction_id": "junction-2",
        },
    ]
    threshold = choose_set_selection_threshold(rows)
    decoded = decode_access_set_probabilities(
        rows,
        selection_threshold=threshold,
    )
    assert all(bool(row["raw_set_exact"]) for row in decoded)


def test_uncalibrated_or_all_safe_inner_slice_cannot_auto_release() -> None:
    no_eligible = [
        {
            "release_eligible": False,
            "raw_set_exact": True,
            "set_confidence": 0.99,
        }
    ]
    all_safe = [
        {
            "release_eligible": True,
            "raw_set_exact": True,
            "set_confidence": 0.99,
        }
    ]
    assert choose_zero_error_set_threshold(no_eligible) > 1.0
    assert choose_zero_error_set_threshold(all_safe) > 1.0
