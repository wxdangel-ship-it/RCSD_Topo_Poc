from __future__ import annotations

from types import SimpleNamespace

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_geometry_data import (
    END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM,
    _proposal_features,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_geometry_network import (
    TargetAEndToEndGeometryConfig,
    TargetAEndToEndGeometryNetwork,
)


class _FakeRecall(nn.Module):
    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.config = SimpleNamespace(hidden_dim=hidden_dim)
        self.scale = nn.Parameter(torch.tensor(1.0))

    def forward(self, batch):
        batch_size = batch.advance_right_object_indices.shape[0]
        objects = torch.ones((batch_size, 4, 4)) * self.scale
        ordinary = torch.ones((batch_size, 2, 4)) * self.scale
        probabilities = torch.full((batch_size, 1, 3), 1.0 / 3.0)
        return {
            "object_embeddings": objects,
            "locked_ordinary_embeddings": ordinary,
            "advance_right_source_decision_probabilities": probabilities,
            "advance_right_target_decision_probabilities": probabilities,
            "advance_right_recall_plan_logits": torch.zeros(
                (batch_size, 1, 2)
            ),
        }


def test_geometry_features_use_local_evidence_and_type() -> None:
    row = {
        "proposal_type": "MIDDLE_SPLICE",
        "candidate_feature_values": [0.0] * 50,
        "target_member_feature_values": [0.0] * 24,
        "geometry_feature_values": [0.0] * 26,
    }
    values = _proposal_features(row)
    assert len(values) == END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM
    assert values[:3] == [0.0, 0.0, 1.0]


def test_geometry_network_masks_padding_and_keeps_recall_gradient() -> None:
    recall = _FakeRecall(hidden_dim=4)
    model = TargetAEndToEndGeometryNetwork(
        recall,
        TargetAEndToEndGeometryConfig(
            hidden_dim=4,
            proposal_hidden_dim=8,
            dropout=0.0,
        ),
    )
    batch = SimpleNamespace(
        advance_right_object_indices=torch.tensor([[3]]),
        advance_right_source_indices=torch.tensor([[0]]),
        advance_right_target_indices=torch.tensor([[1]]),
    )
    values = torch.zeros(
        (1, 3, END_TO_END_GEOMETRY_PROPOSAL_FEATURE_DIM)
    )
    mask = torch.tensor([[True, True, False]])
    outputs = model(
        batch,
        geometry_proposal_values=values,
        geometry_proposal_mask=mask,
    )
    logits = outputs["geometry_proposal_logits"]
    assert logits.shape == (1, 3)
    assert torch.isneginf(logits[0, 2])
    logits[0, :2].sum().backward()
    assert recall.scale.grad is not None


def test_geometry_network_can_freeze_recall() -> None:
    recall = _FakeRecall(hidden_dim=4)
    model = TargetAEndToEndGeometryNetwork(
        recall,
        TargetAEndToEndGeometryConfig(
            hidden_dim=4,
            proposal_hidden_dim=8,
            dropout=0.0,
        ),
    )
    model.freeze_recall()
    assert not any(parameter.requires_grad for parameter in recall.parameters())
