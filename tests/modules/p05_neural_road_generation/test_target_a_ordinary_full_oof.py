from __future__ import annotations

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_full_oof import (
    ordinary_inference_example_from_group,
    validate_inference_group_dimensions,
)


def _candidate(plan_id: str, decision: str):
    road_members = (
        []
        if decision == "ABSTAIN"
        else [
            {
                "road_id": "r1",
                "start_node_id": "n1",
                "end_node_id": "n2",
                "features": [0.0] * 24,
            }
        ]
    )
    arm_rows = (
        []
        if decision == "ABSTAIN"
        else [
            {
                "nearest_road_id": "r1",
                "nearest_node_id": "n1",
                "features": [0.0] * 13,
            },
            {
                "nearest_road_id": "r1",
                "nearest_node_id": "n2",
                "features": [0.0] * 13,
            },
        ]
    )
    return {
        "plan_id": plan_id,
        "decision": decision,
        "road_ids": [] if decision == "ABSTAIN" else ["r1"],
        "road_members": road_members,
        "arm_rows": arm_rows,
        "features": [0.0] * 64,
    }


def test_inference_example_uses_dummy_abstain_only_for_collation() -> None:
    example = ordinary_inference_example_from_group(
        {
            "case_key": "T10:1",
            "segment_id": "a_b",
            "object_features": [0.0] * 64,
            "required_anchor_ids": ["a", "b"],
            "arm_anchor_ids": ["a", "b"],
            "candidates": [
                _candidate("keep", "KEEP_SWSD"),
                _candidate("use", "USE_RCSD"),
                _candidate("stop", "ABSTAIN"),
            ],
        },
        fold=2,
    )
    assert example.acceptable_indices == (2,)
    assert example.preferred_index == 2
    assert example.sample_weight == 0.0
    assert not example.carrier_task_mask
    validate_inference_group_dimensions(example)


def test_inference_group_requires_one_abstain_plan() -> None:
    group = {
        "case_key": "T10:1",
        "segment_id": "a_b",
        "object_features": [0.0] * 64,
        "required_anchor_ids": [],
        "arm_anchor_ids": ["a", "b"],
        "candidates": [_candidate("keep", "KEEP_SWSD")],
    }
    try:
        ordinary_inference_example_from_group(group, fold=0)
    except ValueError as exc:
        assert "ABSTAIN" in str(exc)
    else:
        raise AssertionError("missing ABSTAIN plan was accepted")
