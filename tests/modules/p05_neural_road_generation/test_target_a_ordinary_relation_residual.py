from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_conditioned_data import (
    AnchorOOFCondition,
    condition_ordinary_plan_example,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_relation_residual import (
    ORDINARY_RELATION_FEATURE_DIM,
    OrdinaryRelationResidual,
    OrdinaryRelationResidualExample,
    _residual_loss,
    collate_ordinary_relation_residual_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_plan_training_data import (
    OrdinaryPlanTrainingExample,
)


def _base_example() -> OrdinaryPlanTrainingExample:
    return OrdinaryPlanTrainingExample(
        sample_id="case:s1",
        case_key="T10:case",
        segment_id="s1",
        fold=1,
        object_features=(0.0,) * 64,
        required_anchor_ids=("a1", "a2"),
        arm_anchor_ids=("a1", "a2"),
        candidate_ids=("keep", "use", "abstain"),
        candidate_decisions=("KEEP_SWSD", "USE_RCSD", "ABSTAIN"),
        candidate_road_ids=(("swsd-r",), ("r1", "r2"), ()),
        candidate_member_ids=((), (), ()),
        candidate_member_endpoint_ids=((), (), ()),
        candidate_member_features=((), (), ()),
        candidate_arm_road_ids=((), (), ()),
        candidate_arm_node_ids=((), (), ()),
        candidate_arm_features=((), (), ()),
        candidate_features=(
            (0.0,) * 64,
            (1.0,) * 64,
            (0.5,) * 64,
        ),
        acceptable_indices=(0,),
        preferred_index=0,
        preferred_decision="KEEP_SWSD",
        sample_weight=0.7,
        clue_label=0,
        clue_task_mask=False,
        fallback_scope_label=0,
        fallback_scope_task_mask=False,
    )


def _condition(anchor_id: str, status: str) -> AnchorOOFCondition:
    return AnchorOOFCondition(
        anchor_id=anchor_id,
        selected_candidate_id=(
            f"NODE:{anchor_id}" if anchor_id == "a1" else "ROAD:r1"
        ),
        predicted_status=status,
        gate_pass_probability=0.9 if status == "SUCCESS" else 0.2,
        selected_candidate_features=(0.25,) * 64,
    )


def test_residual_sanitizes_masked_negative_infinity() -> None:
    model = OrdinaryRelationResidual(hidden_dim=16)
    base_logits = torch.tensor([[0.0, float("-inf"), 1.0]])
    relation_features = torch.zeros(
        (1, 3, ORDINARY_RELATION_FEATURE_DIM)
    )
    candidate_mask = torch.tensor([[True, False, True]])

    outputs = model(base_logits, relation_features, candidate_mask)

    assert torch.isfinite(outputs["combined_logits"][0, [0, 2]]).all()
    assert torch.isneginf(outputs["combined_logits"][0, 1])
    assert torch.isfinite(outputs["bounded_residual"]).all()
    assert outputs["bounded_residual"].abs().max() <= 2.0


def test_residual_batch_keeps_anchor_mask_and_has_finite_gradients() -> None:
    conditioned = condition_ordinary_plan_example(
        _base_example(),
        {
            "a1": _condition("a1", "SUCCESS"),
            "a2": _condition("a2", "AMBIGUOUS"),
        },
        include_anchor_plan_relations=True,
        candidate_node_ids=(("swsd-n",), ("a1", "n2"), ()),
    )
    example = OrdinaryRelationResidualExample(
        conditioned=conditioned,
        base_logits=(0.0, float("-inf"), 1.0),
    )
    batch = collate_ordinary_relation_residual_batch([example])
    model = OrdinaryRelationResidual(hidden_dim=16)

    outputs = model(
        batch.base_logits,
        batch.relation_features,
        batch.candidate_mask,
    )
    loss = _residual_loss(outputs, batch)
    loss.backward()

    assert batch.candidate_mask.tolist() == [[True, False, True]]
    assert torch.isfinite(loss)
    assert all(
        parameter.grad is None or torch.isfinite(parameter.grad).all()
        for parameter in model.parameters()
    )
