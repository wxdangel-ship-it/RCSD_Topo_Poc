from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_independent_gate import (
    INDEPENDENT_GATE_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_joint_gate import (
    JOINT_GATE_SEGMENT_FEATURE_DIM,
    JointAnchorSegmentGate,
    JointGateConfig,
    build_joint_segment_gate_features,
    combine_required_anchor_margins,
)


def _group() -> dict[str, object]:
    return {
        "object_features": [0.0] * 64,
        "pair_node_ids": ["p1", "p2"],
        "junc_node_ids": ["j1"],
        "candidates": [
            {
                "decision": "KEEP_SWSD",
                "road_ids": ["s1"],
                "features": [0.0] * 64,
            },
            {
                "decision": "USE_RCSD",
                "road_ids": ["r1", "r2"],
                "features": [1.0] * 64,
            },
            {
                "decision": "ABSTAIN",
                "road_ids": [],
                "features": [0.5] * 64,
            },
        ],
    }


def test_joint_segment_features_are_bounded_truth_free_aggregates() -> None:
    features = build_joint_segment_gate_features(_group())

    assert len(features) == JOINT_GATE_SEGMENT_FEATURE_DIM
    assert all(torch.isfinite(torch.tensor(features)))
    assert features[64] == 0.5
    assert features[64 * 2] > 0.0


def test_joint_gate_handles_empty_required_anchor_set() -> None:
    model = JointAnchorSegmentGate(
        JointGateConfig(hidden_dim=32, bottleneck_dim=16)
    )
    logits = model.forward_segment(
        segment_features=torch.zeros(
            (2, JOINT_GATE_SEGMENT_FEATURE_DIM),
        ),
        anchor_features=torch.zeros(
            (2, 1, INDEPENDENT_GATE_FEATURE_DIM),
        ),
        anchor_mask=torch.tensor([[False], [True]]),
    )

    assert logits.shape == (2, 2)
    assert torch.isfinite(logits).all()
    assert logits[0, 1] > logits[0, 0]


def test_segment_loss_updates_shared_anchor_encoder() -> None:
    model = JointAnchorSegmentGate(
        JointGateConfig(hidden_dim=32, bottleneck_dim=16)
    )
    logits = model.forward_segment(
        segment_features=torch.zeros(
            (1, JOINT_GATE_SEGMENT_FEATURE_DIM),
        ),
        anchor_features=torch.ones(
            (1, 2, INDEPENDENT_GATE_FEATURE_DIM),
        ),
        anchor_mask=torch.tensor([[True, True]]),
    )

    torch.nn.functional.cross_entropy(logits, torch.tensor([1])).backward()

    gradient = model.anchor_encoder[0].weight.grad
    assert gradient is not None
    assert bool((gradient.abs() > 0).any())


def test_required_anchor_soft_and_is_monotone() -> None:
    mask = torch.tensor([[True, True]])
    original = combine_required_anchor_margins(
        torch.tensor([[2.0, 2.0]]),
        mask,
        temperature=0.5,
        empty_pass_margin=12.0,
    )
    weakened = combine_required_anchor_margins(
        torch.tensor([[-1.0, 2.0]]),
        mask,
        temperature=0.5,
        empty_pass_margin=12.0,
    )

    assert weakened.item() < original.item()
