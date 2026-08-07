from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_joint_network import (
    TargetAAdvanceRightJointAccessDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_joint_training import (
    _new_optimizer,
    _score_side,
    apply_joint_release,
    choose_zero_error_joint_threshold,
)


def test_joint_threshold_uses_end_to_end_truth() -> None:
    rows = [
        {
            "joint_confidence": 0.9,
            "joint_input_complete": True,
            "predicted_plan_type": "SWSD_ONLY",
            "raw_end_to_end_exact": False,
        },
        {
            "joint_confidence": 0.8,
            "joint_input_complete": True,
            "predicted_plan_type": "SWSD_ONLY",
            "raw_end_to_end_exact": True,
        },
    ]
    assert choose_zero_error_joint_threshold(rows) > 0.9


def test_positive_keep_is_separate_from_abstain_fallback() -> None:
    rows = [
        {
            "joint_confidence": 0.9,
            "joint_input_complete": True,
            "predicted_plan_type": "SWSD_ONLY",
            "raw_end_to_end_exact": True,
        },
        {
            "joint_confidence": 0.4,
            "joint_input_complete": True,
            "predicted_plan_type": "SWSD_ONLY",
            "raw_end_to_end_exact": True,
        },
    ]
    released = apply_joint_release(rows, acceptance_threshold=0.8)
    assert released[0]["positive_keep_swsd"]
    assert released[0]["effective_decision"] == "SWSD_ONLY"
    assert not released[1]["positive_keep_swsd"]
    assert released[1]["effective_decision"] == "ABSTAIN"


def test_complete_road_set_is_masked_by_locked_source() -> None:
    cardinality = torch.zeros(65)
    cardinality[1] = 1.0
    row = _score_side(
        {
            "source_supervision": {
                "source_index": 0,
                "road_supervised": True,
                "acceptable_road_ids": ("swsd",),
                "access_supervised": False,
                "acceptable_access_road_ids": (),
            },
            "base_feature": {
                "source_side": {
                    "road_candidates": [
                        {"road_id": "swsd", "source": "SWSD"},
                        {"road_id": "rcsd", "source": "RCSD"},
                    ],
                    "access_candidates": [],
                }
            },
        },
        side_name="source",
        source_probabilities=torch.tensor([0.9, 0.1, 0.0]),
        road_logits=torch.tensor([1.0, 10.0]),
        road_cardinality_probabilities=cardinality,
        access_logits=torch.empty(0),
    )
    assert row["source_side_predicted_road_ids"] == ["swsd"]
    assert row["source_side_road_exact"]


def test_optimizer_uses_lower_rate_for_pretrained_ordinary() -> None:
    model = TargetAAdvanceRightJointAccessDecoder(dropout=0.0)
    optimizer = _new_optimizer(
        model,
        learning_rate=4e-4,
        ordinary_learning_rate_scale=0.1,
        weight_decay=2e-4,
    )
    assert sorted(group["lr"] for group in optimizer.param_groups) == [
        4e-5,
        4e-4,
    ]
    ordinary_ids = {
        id(parameter)
        for parameter in model.ordinary_road_decoder.parameters()
    }
    low_rate_ids = {
        id(parameter)
        for group in optimizer.param_groups
        if group["lr"] == 4e-5
        for parameter in group["params"]
    }
    assert low_rate_ids == ordinary_ids
