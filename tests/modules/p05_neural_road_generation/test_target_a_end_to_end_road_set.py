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
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_road_set_data import (
    END_TO_END_ROAD_MEMBER_FEATURE_DIM,
    collate_end_to_end_road_set_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_road_set_network import (
    TargetAEndToEndRoadSetConfig,
    TargetAEndToEndRoadSetNetwork,
    compose_business_road_set_logits,
    compose_road_set_logits,
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
    swsd: bool = False,
) -> AdvanceRightRecallPlan:
    values = [0.0] * 64
    values[0] = sum(float(value[1:]) for value in road_ids)
    values[59] = float(len(road_ids))
    values[60 if swsd else 61] = 1.0
    return AdvanceRightRecallPlan(
        plan_id=plan_id,
        road_ids=road_ids,
        feature_values=tuple(values),
    )


def _example() -> EndToEndRecallExample:
    anchors = (_anchor("a1"), _anchor("a2"))
    ordinary = (
        _ordinary("s1", ("a1",)),
        _ordinary("s2", ("a2",)),
    )
    dependency = build_segment_joint_examples(anchors, ordinary)[0]
    dependency = replace(
        dependency,
        anchors=anchors,
        ordinary_segments=ordinary,
    )
    plans = (
        _plan("SWSD_ONLY", (), swsd=True),
        _plan("RCSD_SET:r1", ("r1",)),
        _plan("RCSD_SET:r2", ("r2",)),
        _plan("RCSD_SET:r1|r2", ("r1", "r2")),
    )
    advance = AdvanceRightRecallExample(
        case_key=dependency.case_key,
        segment_id="ar-1",
        fold=dependency.fold,
        source_segment_id="s1",
        target_segment_id="s2",
        plans=plans,
        acceptable_plan_ids=frozenset({"RCSD_SET:r1|r2"}),
        preferred_plan_id="RCSD_SET:r1|r2",
        task_mask=True,
        label_weight=1.0,
        truth_plan_type="RCSD_ONLY",
    )
    return EndToEndRecallExample(dependency, advance)


def _model() -> TargetAEndToEndRoadSetNetwork:
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
    recall = TargetAEndToEndRecallNetwork(
        TargetAJointNetwork(backbone_config),
        TargetAEndToEndRecallConfig(
            hidden_dim=32,
            reranker_hidden_dim=16,
            max_road_cardinality=4,
            dropout=0.0,
        ),
    )
    return TargetAEndToEndRoadSetNetwork(
        recall,
        TargetAEndToEndRoadSetConfig(
            hidden_dim=32,
            road_hidden_dim=16,
            max_road_cardinality=4,
            dropout=0.0,
        ),
    )


def test_road_set_collate_exposes_members_without_terminal_labels() -> None:
    road = collate_end_to_end_road_set_batch([_example()])

    assert road.road_ids == (("r1", "r2"),)
    assert road.member_values.shape == (
        1,
        1,
        2,
        END_TO_END_ROAD_MEMBER_FEATURE_DIM,
    )
    assert road.plan_membership.tolist() == [
        [[
            [False, False],
            [True, False],
            [False, True],
            [True, True],
        ]]
    ]
    assert road.member_mask.all()
    assert road.plan_mask.all()


def test_factorized_road_set_outputs_source_cardinality_and_members() -> None:
    example = _example()
    packed = collate_end_to_end_recall_batch(
        example,
        teacher_forcing=False,
        include_candidate_relations=False,
        retain_anchor_structural_evidence=False,
        retain_ordinary_member_evidence=False,
        retain_ordinary_arm_evidence=False,
    )
    road = collate_end_to_end_road_set_batch([example])
    model = _model().eval()

    outputs = model(
        packed.training_batch.tensors,
        road_member_values=road.member_values,
        road_member_mask=road.member_mask,
        plan_membership=road.plan_membership,
    )

    assert outputs["advance_right_recall_plan_logits"].shape == (1, 1, 4)
    assert outputs["advance_right_road_source_logits"].shape == (1, 1, 2)
    assert outputs["advance_right_road_cardinality_logits"].shape == (
        1,
        1,
        5,
    )
    assert outputs["advance_right_road_member_logits"].shape == (1, 1, 2)
    recomposed = compose_road_set_logits(
        outputs,
        plan_mask=packed.training_batch.tensors.advance_right_plan_mask,
        source_scale=1.0,
        cardinality_scale=1.0,
        member_scale=1.0,
    )
    assert torch.allclose(
        recomposed,
        outputs["advance_right_recall_plan_logits"],
    )
    business = compose_business_road_set_logits(
        outputs,
        plan_mask=packed.training_batch.tensors.advance_right_plan_mask,
        source_scale=1.0,
        cardinality_scale=1.0,
        member_scale=1.0,
    )
    assert torch.equal(
        torch.isfinite(business),
        outputs["advance_right_business_plan_mask"],
    )


def test_freeze_recall_keeps_only_factorized_heads_trainable() -> None:
    model = _model()
    model.freeze_recall()

    assert not any(
        parameter.requires_grad for parameter in model.recall.parameters()
    )
    assert any(
        parameter.requires_grad for parameter in model.member_encoder.parameters()
    )
