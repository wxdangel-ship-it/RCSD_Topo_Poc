from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_geometry_data import (
    END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_recall_data import (
    collate_end_to_end_recall_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_road_set_data import (
    collate_end_to_end_road_set_batch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_typed_geometry_network import (
    TargetAEndToEndTypedGeometryConfig,
    TargetAEndToEndTypedGeometryNetwork,
)
from tests.modules.p05_neural_road_generation.test_target_a_end_to_end_road_set import (
    _example,
    _model,
)


def _inputs():
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
    geometry = torch.zeros(
        (1, 4, END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM)
    )
    geometry[0, 0, 0] = 1.0
    geometry[0, 1, 1] = 1.0
    geometry[0, 2, 2] = 1.0
    geometry[0, 3, 0] = 1.0
    mask = torch.tensor([[True, True, True, False]])
    return packed.training_batch.tensors, road, geometry, mask


def test_typed_geometry_uses_three_experts_and_masks_padding() -> None:
    batch, road, geometry, mask = _inputs()
    model = TargetAEndToEndTypedGeometryNetwork(
        _model(),
        TargetAEndToEndTypedGeometryConfig(
            hidden_dim=32,
            proposal_hidden_dim=16,
            max_road_cardinality=4,
            dropout=0.0,
        ),
    ).eval()

    outputs = model(
        batch,
        road_member_values=road.member_values,
        road_member_mask=road.member_mask,
        plan_membership=road.plan_membership,
        geometry_proposal_values=geometry,
        geometry_proposal_mask=mask,
    )

    assert outputs["geometry_proposal_logits"].shape == (1, 4)
    assert outputs["geometry_type_expert_logits"].shape == (1, 4, 3)
    assert torch.isneginf(outputs["geometry_proposal_logits"][0, 3])


def test_typed_geometry_can_freeze_complete_road_set_model() -> None:
    model = TargetAEndToEndTypedGeometryNetwork(
        _model(),
        TargetAEndToEndTypedGeometryConfig(
            hidden_dim=32,
            proposal_hidden_dim=16,
            max_road_cardinality=4,
            dropout=0.0,
        ),
    )
    model.freeze_road_set()

    assert not any(
        parameter.requires_grad for parameter in model.road_set.parameters()
    )
    assert any(
        parameter.requires_grad
        for parameter in model.proposal_heads.parameters()
    )
