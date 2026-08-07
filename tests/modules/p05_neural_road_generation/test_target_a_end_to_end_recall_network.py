from __future__ import annotations

from dataclasses import replace

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_case_joint_data import (
    build_segment_joint_examples,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_recall_data import (
    AdvanceRightRecallExample,
    AdvanceRightRecallPlan,
    EndToEndRecallExample,
    collate_end_to_end_recall_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_recall_network import (
    TargetAEndToEndRecallConfig,
    TargetAEndToEndRecallNetwork,
    ordinary_decision_probabilities,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetAJointNetwork,
)
from tests.modules.p05_neural_road_generation.test_target_a_case_joint_data import (
    _anchor,
    _ordinary,
)


def _plan(
    plan_id: str,
    road_ids: tuple[str, ...],
    *,
    swsd: bool,
) -> AdvanceRightRecallPlan:
    values = [0.0] * 64
    values[59] = float(len(road_ids))
    values[60 if swsd else 61] = 1.0
    return AdvanceRightRecallPlan(
        plan_id=plan_id,
        road_ids=road_ids,
        feature_values=tuple(values),
    )


def _batch():
    anchors = (_anchor("a1"), _anchor("a2"))
    ordinary = (
        _ordinary("s1", ("a1",)),
        _ordinary("s2", ("a2",)),
    )
    dependency = build_segment_joint_examples(anchors, ordinary)
    combined = replace(
        dependency[0],
        anchors=anchors,
        ordinary_segments=ordinary,
    )
    plans = (
        _plan("SWSD_ONLY", (), swsd=True),
        _plan("RCSD_SET:r1", ("r1",), swsd=False),
    )
    advance = AdvanceRightRecallExample(
        case_key=combined.case_key,
        segment_id="ar-1",
        fold=combined.fold,
        source_segment_id="s1",
        target_segment_id="s2",
        plans=plans,
        acceptable_plan_ids=frozenset({"RCSD_SET:r1"}),
        preferred_plan_id="RCSD_SET:r1",
        task_mask=True,
        label_weight=1.0,
        truth_plan_type="RCSD_ONLY",
    )
    return collate_end_to_end_recall_batch(
        EndToEndRecallExample(combined, advance),
        teacher_forcing=False,
        include_candidate_relations=False,
        retain_anchor_structural_evidence=False,
        retain_ordinary_member_evidence=False,
        retain_ordinary_arm_evidence=False,
    ).training_batch


def _model() -> TargetAEndToEndRecallNetwork:
    backbone_config = TargetAConfig(
        feature_dim=64,
        hidden_dim=32,
        num_heads=4,
        graph_layers=1,
        set_layers=1,
        feedforward_dim=64,
        min_parameter_count=1,
        max_parameter_count=10_000_000,
    )
    return TargetAEndToEndRecallNetwork(
        TargetAJointNetwork(backbone_config),
        TargetAEndToEndRecallConfig(
            hidden_dim=32,
            reranker_hidden_dim=16,
            max_road_cardinality=4,
            dropout=0.0,
        ),
    )


def test_recall_network_outputs_source_and_cardinality_conditioning() -> None:
    batch = _batch()
    outputs = _model().eval()(batch.tensors)

    assert outputs["advance_right_recall_plan_logits"].shape == (1, 1, 2)
    assert outputs["advance_right_recall_cardinality_logits"].shape == (
        1,
        1,
        5,
    )
    assert outputs[
        "advance_right_source_decision_probabilities"
    ].shape == (1, 1, 3)
    assert outputs["advance_right_business_plan_mask"].shape == (1, 1, 2)
    assert outputs["advance_right_business_plan_type"].shape == (1, 1)
    assert outputs["advance_right_business_ready"].shape == (1, 1)
    assert outputs["ordinary_effective_business_decisions"].shape == (
        1,
        2,
    )
    assert torch.isfinite(
        outputs["advance_right_recall_plan_logits"]
    ).all()


def test_frozen_backbone_only_leaves_recall_reranker_trainable() -> None:
    batch = _batch()
    model = _model()
    model.freeze_backbone()
    outputs = model(batch.tensors)
    outputs["advance_right_recall_plan_logits"].sum().backward()

    assert all(
        parameter.grad is None for parameter in model.backbone.parameters()
    )
    assert any(
        parameter.grad is not None for parameter in model.reranker.parameters()
    )


def test_ordinary_decision_probabilities_pool_candidate_plans() -> None:
    logits = torch.tensor([[[1.0, 2.0, 4.0]]])
    indices = torch.tensor([[[0, 0, 1]]])
    mask = torch.ones((1, 1, 3), dtype=torch.bool)

    probabilities = ordinary_decision_probabilities(
        logits,
        indices,
        mask,
    )

    assert probabilities.shape == (1, 1, 3)
    assert probabilities[0, 0, 1] > probabilities[0, 0, 0]
    assert probabilities[0, 0, 2] == 0.0


def test_ordinary_decision_probabilities_keep_padded_group_zero() -> None:
    logits = torch.tensor([[[1.0, 2.0], [0.0, 0.0]]])
    indices = torch.tensor([[[0, 1], [0, 0]]])
    mask = torch.tensor([[[True, True], [False, False]]])

    probabilities = ordinary_decision_probabilities(
        logits,
        indices,
        mask,
    )

    assert torch.allclose(
        probabilities[0, 1],
        torch.zeros(3),
    )
