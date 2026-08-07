from __future__ import annotations

from types import SimpleNamespace

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    TARGET_A_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_KEEP_SWSD,
    ORDINARY_DECISION_USE_RCSD,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_mainline_data import (
    ACCESS_COLLECTION_FEATURE_DIM,
    BREAK_CANDIDATE_FEATURE_DIM,
    OrdinaryJointAccessBatch,
    OrdinaryJointBreakBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_mainline_network import (
    TargetAOrdinaryJointMainlineConfig,
    TargetAOrdinaryJointMainlineNetwork,
    _plan_proposal_compatibility,
    _structured_plan_loss,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_joint_structured_data import (
    STRUCTURED_PLAN_KEEP_SWSD,
    STRUCTURED_PLAN_USE_RCSD,
    OrdinaryJointStructuredPlanBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_road_members import (
    ROAD_BUSINESS_ROLE_LABELS,
    ROAD_OWNERSHIP_LABELS,
)


class _StructuredFakeOrdinaryNetwork(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.config = SimpleNamespace(hidden_dim=8, road_hidden_dim=8)

    def forward(self, batch: object, ordinary_set: object) -> dict[str, torch.Tensor]:
        del batch, ordinary_set
        member_logits = torch.tensor(
            [[[2.0, -2.0, 100.0], [0.0, 0.0, 0.0]]]
        )
        return {
            "_ordinary_road_encoded": torch.arange(
                48, dtype=torch.float32
            ).reshape(1, 2, 3, 8),
            "ordinary_side_road_member_logits": member_logits,
            "ordinary_side_context": torch.ones((1, 2, 8)),
            "ordinary_effective_business_decisions": torch.tensor(
                [[ORDINARY_DECISION_KEEP_SWSD, ORDINARY_DECISION_USE_RCSD]]
            ),
            "ordinary_side_decision_logits": torch.zeros((1, 2, 3)),
            "ordinary_side_road_cardinality_logits": torch.zeros((1, 2, 5)),
            "ordinary_side_road_business_role_logits": torch.zeros(
                (1, 2, 3, len(ROAD_BUSINESS_ROLE_LABELS))
            ),
            "ordinary_side_road_ownership_logits": torch.zeros(
                (1, 2, 3, len(ROAD_OWNERSHIP_LABELS))
            ),
        }


def _empty_access_batch() -> OrdinaryJointAccessBatch:
    return OrdinaryJointAccessBatch(
        proposal_values=torch.zeros(
            (1, 2, 1, 1, ACCESS_COLLECTION_FEATURE_DIM)
        ),
        proposal_road_indices=torch.full((1, 2, 1, 1), -1),
        proposal_mask=torch.zeros((1, 2, 1, 1), dtype=torch.bool),
        proposal_targets=torch.zeros((1, 2, 1, 1), dtype=torch.bool),
        task_mask=torch.zeros((1, 2, 1), dtype=torch.bool),
        cardinality_targets=torch.zeros((1, 2, 1), dtype=torch.long),
        sample_weights=torch.zeros((1, 2, 1)),
        junction_ids=(((), ()),),
        proposal_ids=((((),), ((),)),),
    )


def _empty_break_batch() -> OrdinaryJointBreakBatch:
    return OrdinaryJointBreakBatch(
        parent_road_indices=torch.full((1, 2, 1), -1),
        parent_mask=torch.zeros((1, 2, 1), dtype=torch.bool),
        candidate_values=torch.zeros(
            (1, 2, 1, 1, BREAK_CANDIDATE_FEATURE_DIM)
        ),
        candidate_fractions=torch.zeros((1, 2, 1, 1)),
        candidate_mask=torch.zeros((1, 2, 1, 1), dtype=torch.bool),
        candidate_targets=torch.zeros((1, 2, 1, 1), dtype=torch.bool),
        task_mask=torch.zeros((1, 2, 1), dtype=torch.bool),
        presence_targets=torch.zeros((1, 2, 1), dtype=torch.bool),
        cardinality_targets=torch.zeros((1, 2, 1), dtype=torch.long),
        ownership_targets=torch.zeros((1, 2, 1), dtype=torch.long),
        sample_weights=torch.zeros((1, 2, 1)),
        parent_road_ids=(((), ()),),
    )


def _structured_batch() -> OrdinaryJointStructuredPlanBatch:
    plan_shape = (1, 2, 2)
    road_shape = (*plan_shape, 3)
    membership = torch.zeros(road_shape, dtype=torch.bool)
    membership[0, 0, :, 0] = True
    access_membership = torch.zeros(
        (*plan_shape, 2, 3), dtype=torch.bool
    )
    access_membership[0, 0, :, 0, 0] = True
    access_membership[0, 0, :, 1, 1] = True
    return OrdinaryJointStructuredPlanBatch(
        plan_feature_values=torch.zeros((*plan_shape, TARGET_A_FEATURE_DIM)),
        plan_mask=torch.tensor([[[True, True], [False, False]]]),
        plan_hard_valid=torch.tensor([[[True, True], [False, False]]]),
        plan_decisions=torch.tensor(
            [[[STRUCTURED_PLAN_KEEP_SWSD, STRUCTURED_PLAN_USE_RCSD], [0, 0]]]
        ),
        plan_base_decisions=torch.tensor(
            [[[ORDINARY_DECISION_KEEP_SWSD, ORDINARY_DECISION_USE_RCSD], [0, 0]]]
        ),
        plan_road_membership=membership,
        plan_role_targets=torch.zeros(road_shape, dtype=torch.long),
        plan_ownership_targets=torch.zeros(road_shape, dtype=torch.long),
        plan_access_road_membership=access_membership,
        access_group_arm_indices=torch.tensor([[[0], [-2]]]),
        acceptable_plan_mask=torch.tensor(
            [[[False, True], [False, False]]]
        ),
        task_mask=torch.tensor([[True, False]]),
        sample_weights=torch.tensor([[1.0, 0.0]]),
        teacher_gate_decisions=torch.full((1, 2), -1, dtype=torch.long),
        plan_ids=((('keep', 'use'), ()),),
    )


def test_structured_plan_uses_focal_group_gate_and_excludes_padded_roads() -> None:
    ordinary_set = SimpleNamespace(
        side_group_indices=torch.tensor([[1, -1]]),
        side_road_mask=torch.tensor(
            [[[True, True, False], [False, False, False]]]
        ),
    )
    config = TargetAOrdinaryJointMainlineConfig(
        hidden_dim=8,
        road_hidden_dim=8,
        access_hidden_dim=8,
        break_hidden_dim=8,
        plan_hidden_dim=8,
        set_heads=2,
        plan_set_heads=2,
        dropout=0.0,
    )
    model = TargetAOrdinaryJointMainlineNetwork(
        _StructuredFakeOrdinaryNetwork(),
        config,
    ).eval()

    outputs = model(
        object(),
        ordinary_set,
        _empty_access_batch(),
        _empty_break_batch(),
        _structured_batch(),
    )

    assert outputs["ordinary_structured_plan_gate_decisions"].tolist() == [
        [ORDINARY_DECISION_USE_RCSD, 2]
    ]
    assert outputs["ordinary_structured_plan_allowed_mask"].tolist() == [
        [[False, True], [False, False]]
    ]
    expected_excluded = torch.nn.functional.logsigmoid(torch.tensor(2.0))
    assert torch.allclose(
        outputs["_ordinary_structured_plan_dynamic"][0, 0, 1, 3],
        expected_excluded,
    )


def test_structured_plan_loss_accepts_multiple_correct_solutions() -> None:
    batch = _structured_batch()
    all_acceptable = OrdinaryJointStructuredPlanBatch(
        **{
            **batch.__dict__,
            "acceptable_plan_mask": torch.tensor(
                [[[True, True], [False, False]]]
            ),
        }
    )
    outputs = {
        "ordinary_structured_plan_logits": torch.tensor(
            [[[1.0, -1.0], [float("-inf"), float("-inf")]]]
        ),
        "ordinary_structured_plan_allowed_mask": torch.tensor(
            [[[True, True], [False, False]]]
        ),
    }

    loss = _structured_plan_loss(outputs, all_acceptable)

    assert torch.isfinite(loss)
    assert torch.allclose(loss, torch.tensor(0.0))


def test_structured_plan_keeps_source_and_target_access_arms_separate() -> None:
    plan_roads = torch.zeros((1, 2, 1, 3), dtype=torch.bool)
    plan_roads[0, 0, 0, :2] = True
    plan_arm_roads = torch.zeros((1, 2, 1, 2, 3), dtype=torch.bool)
    plan_arm_roads[0, 0, 0, 0, 0] = True
    plan_arm_roads[0, 0, 0, 1, 1] = True
    group_arm_indices = torch.tensor([[[0, 1], [-1, -1]]])
    proposal_road_indices = torch.tensor(
        [[[[0, 1], [0, 1]], [[-1, -1], [-1, -1]]]]
    )

    compatible = _plan_proposal_compatibility(
        plan_roads,
        plan_arm_roads,
        group_arm_indices,
        proposal_road_indices,
    )

    assert compatible[0, 0, 0].tolist() == [
        [True, False],
        [False, True],
    ]
