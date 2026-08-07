from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_geometry_network import (
    TargetAAdvanceRightGeometryDecoder,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_advance_right_geometry_training import (
    PROPOSAL_FEATURE_DIM,
    _base_joint_loss,
    choose_zero_error_geometry_threshold,
    decode_geometry_score,
)


def test_geometry_network_reuses_graph_context() -> None:
    model = TargetAAdvanceRightGeometryDecoder(dropout=0.0)
    model.freeze_base()
    output = model(
        candidate_values=torch.zeros((2, 1, 60)),
        candidate_mask=torch.tensor([[True], [False]]),
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
        proposal_values=torch.zeros((2, 3, PROPOSAL_FEATURE_DIM)),
        proposal_mask=torch.tensor(
            [[True, True, False], [False, False, False]]
        ),
    )
    assert output["geometry_proposal_logits"].shape == (2, 3)
    assert output["geometry_safety_logits"].shape == (2,)
    assert output["graph_context"].shape == (2, 256)


def test_geometry_decoder_requires_road_set_consistency() -> None:
    base = {
        "case_key": "T10:case",
        "object_id": "ar",
        "predicted_plan_type": "RCSD_ONLY",
        "truth_plan_type": "RCSD_ONLY",
        "raw_selected_candidate_road_ids": ["selected"],
        "raw_plan_exact": True,
        "automatic_decision": True,
    }
    proposals = [
        _proposal("source-good", "SOURCE_ATTACHMENT", "selected"),
        _proposal("source-high-wrong-road", "SOURCE_ATTACHMENT", "other"),
        _proposal("target-good", "TARGET_ATTACHMENT", "selected"),
    ]
    example = {
        "truth_plan_type": "RCSD_ONLY",
        "source_context": {"data_source": "RCSD"},
        "geometry_proposals": proposals,
        "geometry_task_mask": True,
        "geometry_safety_target": True,
        "acceptable_geometry_variants": [
            {
                "proposal_ids": ["source-good", "target-good"],
                "reachable": True,
            }
        ],
    }
    result = decode_geometry_score(
        base,
        example,
        {
            "geometry_proposal_probabilities": [0.8, 0.99, 0.7],
            "geometry_safety_probability": 0.9,
        },
        geometry_acceptance_threshold=0.6,
    )
    assert result["geometry_proposal_exact"]
    assert result["automatic_decision"]
    assert not result["unsafe_automatic"]


def test_zero_error_threshold_can_choose_no_unsafe_prefix() -> None:
    rows = [
        _threshold_row(0.9, exact=True),
        _threshold_row(0.8, exact=False),
        _threshold_row(0.7, exact=True),
    ]
    assert choose_zero_error_geometry_threshold(rows) == 0.9


def test_base_joint_loss_updates_all_carrier_heads() -> None:
    outputs = {
        "plan_type_logits": torch.zeros((1, 5), requires_grad=True),
        "safety_logits": torch.zeros((1,), requires_grad=True),
        "cardinality_logits": torch.zeros((1, 10), requires_grad=True),
        "candidate_logits": torch.zeros((1, 1), requires_grad=True),
    }
    examples = [
        {
            "plan_type_index": 0,
            "safety_target": True,
            "candidate_supervised": True,
            "truth_cardinality": 1,
            "candidate_rows": [{"candidate_road_id": "r1"}],
            "acceptable_candidate_groups": [["r1"]],
        }
    ]
    loss = _base_joint_loss(
        outputs,
        examples,
        plan_weights=torch.ones(5),
        safety_negative_weight=2.0,
    )
    loss.backward()
    assert all(value.grad is not None for value in outputs.values())


def _proposal(proposal_id: str, proposal_type: str, road_id: str):
    return {
        "proposal_id": proposal_id,
        "proposal_type": proposal_type,
        "selected_rcsd_road_id": road_id,
        "selected_endpoint_index": 0,
        "target_ordinary_road_id": "ordinary",
        "target_fraction": 0.5,
        "gap_m": 0.0,
        "operation": "SPLIT_ROAD",
    }


def _threshold_row(confidence: float, *, exact: bool):
    return {
        "base_automatic_decision": True,
        "missing_geometry_proposal_types": [],
        "geometry_confidence": confidence,
        "raw_complete_plan_geometry_exact": exact,
    }
