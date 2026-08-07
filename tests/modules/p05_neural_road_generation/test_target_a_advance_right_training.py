from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_network import (
    TargetAAdvanceRightConditionalDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_training import (
    choose_zero_error_acceptance_threshold,
    choose_zero_unsafe_safety_threshold,
    conditional_plan_target,
    decode_advance_right_scores,
    source_condition_plan_type,
    structured_candidate_exact,
)


def test_multi_solution_exact_accepts_one_candidate_per_truth_road() -> None:
    groups = [["a1", "a2"], ["b1", "b2"]]
    assert structured_candidate_exact(["a2", "b1"], groups)
    assert not structured_candidate_exact(["a1", "a2"], groups)
    assert not structured_candidate_exact(["a1"], groups)
    assert not structured_candidate_exact(["a1", "b1", "b2"], groups)


def test_empty_swsd_candidate_set_is_exact() -> None:
    assert structured_candidate_exact([], [])
    assert not structured_candidate_exact(["unexpected"], [])


def test_zero_unsafe_safety_threshold_rejects_highest_unsafe() -> None:
    rows = [
        {"safety_probability": 0.9, "safety_target": False},
        {"safety_probability": 0.8, "safety_target": True},
        {"safety_probability": 0.2, "safety_target": True},
    ]
    threshold = choose_zero_unsafe_safety_threshold(rows)
    assert threshold > 0.9


def test_zero_error_acceptance_keeps_only_exact_rows() -> None:
    rows = [
        {
            "safety_pass": True,
            "predicted_plan_type": "RCSD_ONLY",
            "confidence": 0.9,
            "safety_target": True,
            "raw_plan_exact": True,
        },
        {
            "safety_pass": True,
            "predicted_plan_type": "RCSD_ONLY",
            "confidence": 0.8,
            "safety_target": True,
            "raw_plan_exact": False,
        },
    ]
    threshold = choose_zero_error_acceptance_threshold(rows)
    assert 0.8 < threshold <= 0.9


def test_network_supports_empty_candidate_set_with_side_context() -> None:
    model = TargetAAdvanceRightConditionalDecoder(dropout=0.0)
    output = model(
        candidate_values=torch.zeros((2, 1, 60)),
        candidate_mask=torch.zeros((2, 1), dtype=torch.bool),
        source_side_values=torch.zeros((2, 150)),
        source_member_values=torch.zeros((2, 1, 24)),
        source_member_mask=torch.zeros((2, 1), dtype=torch.bool),
        source_arm_values=torch.zeros((2, 1, 13)),
        source_arm_mask=torch.zeros((2, 1), dtype=torch.bool),
        target_side_values=torch.zeros((2, 150)),
        target_member_values=torch.zeros((2, 1, 24)),
        target_member_mask=torch.zeros((2, 1), dtype=torch.bool),
        target_arm_values=torch.zeros((2, 1, 13)),
        target_arm_mask=torch.zeros((2, 1), dtype=torch.bool),
    )
    assert output["candidate_logits"].shape == (2, 1)
    assert output["plan_type_logits"].shape == (2, 5)
    assert output["cardinality_logits"].shape == (2, 10)
    assert output["safety_logits"].shape == (2,)


def test_conditional_target_follows_locked_adjacent_access_sources() -> None:
    label = {
        "truth_plan_type": "RCSD_ONLY",
        "plan_task_mask": True,
        "acceptable_rcsd_candidate_ids_by_truth_road": {
            "truth": ["raw"]
        },
    }
    feature = {
        "adjacent_context_resolved": True,
        "source_context": {"data_source": "SWSD"},
        "target_context": {"data_source": "SWSD"},
        "fixed_swsd_road_ids": ["swsd"],
    }
    target, groups, reason = conditional_plan_target(feature, label)
    assert target == "SWSD_ONLY"
    assert groups == []
    assert reason == "BOTH_ADJACENT_ACCESS_SWSD"

    feature["target_context"]["data_source"] = "RCSD"
    target, groups, reason = conditional_plan_target(feature, label)
    assert target == "MIXED_SPLICE"
    assert groups == [["raw"]]
    assert reason == "MIXED_ADJACENT_ACCESS_SOURCE"


def test_unreachable_formal_auto_plan_becomes_review_fallback() -> None:
    target, groups, reason = conditional_plan_target(
        {
            "adjacent_context_resolved": True,
            "source_context": {"data_source": "RCSD"},
            "target_context": {"data_source": "RCSD"},
            "fixed_swsd_road_ids": ["swsd"],
        },
        {
            "truth_plan_type": "RCSD_ONLY",
            "plan_task_mask": False,
            "acceptable_rcsd_candidate_ids_by_truth_road": {},
        },
    )
    assert target == "REVIEW_FALLBACK"
    assert groups == []
    assert reason == "FORMAL_CANDIDATE_UNREACHABLE"


def test_unreachable_formal_rcsd_does_not_block_ready_swsd_final_state() -> None:
    target, groups, reason = conditional_plan_target(
        {
            "adjacent_context_resolved": True,
            "access_valid": True,
            "source_context": {"data_source": "SWSD"},
            "target_context": {"data_source": "SWSD"},
            "fixed_swsd_road_ids": ["swsd"],
        },
        {
            "truth_plan_type": "RCSD_ONLY",
            "plan_task_mask": False,
            "candidate_reachable": False,
            "swsd_reachable": True,
            "materializer_ready": True,
            "acceptable_rcsd_candidate_ids_by_truth_road": {},
        },
    )
    assert target == "SWSD_ONLY"
    assert groups == []
    assert reason == "BOTH_ADJACENT_ACCESS_SWSD"


def test_source_condition_is_a_hard_decoder_constraint() -> None:
    assert source_condition_plan_type(
        {
            "adjacent_context_resolved": True,
            "source_context": {"data_source": "RCSD"},
            "target_context": {"data_source": "SWSD"},
        }
    ) == "MIXED_SPLICE"
    decoded = decode_advance_right_scores(
        [
            {
                "case_key": "T10:1",
                "object_id": "advance_right_x",
                "truth_plan_type": "MIXED_SPLICE",
                "truth_cardinality": 1,
                "acceptable_candidate_groups": [["r1"]],
                "candidate_supervised": True,
                "safety_target": True,
                "adjacent_context_resolved": True,
                "source_condition_plan_type": "MIXED_SPLICE",
                "fixed_swsd_road_ids": ["s1"],
                "candidate_road_ids": ["r1"],
                "candidate_probabilities": [0.9],
                "plan_type_probabilities": [0.05, 0.9, 0.03, 0.01, 0.01],
                "cardinality_probabilities": [
                    0.01,
                    0.9,
                    0.01,
                    0.01,
                    0.01,
                    0.01,
                    0.01,
                    0.01,
                    0.01,
                    0.02,
                ],
                "safety_probability": 0.99,
            }
        ],
        safety_threshold=0.95,
        acceptance_threshold=0.0,
    )[0]
    assert decoded["unconstrained_predicted_plan_type"] == "SWSD_ONLY"
    assert decoded["predicted_plan_type"] == "MIXED_SPLICE"
    assert decoded["raw_selected_fixed_swsd_road_ids"] == ["s1"]
