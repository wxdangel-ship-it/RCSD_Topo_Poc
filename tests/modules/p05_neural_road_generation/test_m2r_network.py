from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_network import (
    JointM2RRoadNet,
    m2r_graph_loss,
    m2r_scene_loss,
    parameter_count,
)


def _model(include_t07: bool = True) -> JointM2RRoadNet:
    return JointM2RRoadNet(103, hidden_dim=384, graph_layers=6, dropout=0.0, include_t07=include_t07)


def test_default_joint_model_parameter_budget_and_forward_contract() -> None:
    model = _model()
    assert 8_000_000 <= parameter_count(model) <= 20_000_000
    scene = model(scene=torch.zeros((2, 8, 64, 64)))
    assert scene["surface"].shape == (2, 64, 64)
    assert scene["t03_relation"].shape == (2, 3)
    graph = model(x=torch.zeros((5, 103)), edge_index=torch.tensor([[0, 1, 2], [1, 2, 3]]))
    assert graph["operation"].shape == (5, 5)
    assert graph["t05_endpoint"].shape == (5, 2, 2)
    assert graph["t07_endpoint"].shape == (5, 2, 2)


def test_scene_and_graph_losses_respect_task_masks() -> None:
    model = _model()
    scene_prediction = model(scene=torch.zeros((2, 8, 64, 64)))
    scene_total, scene_losses = m2r_scene_loss(
        scene_prediction,
        {
            "surface": torch.zeros((2, 64, 64)),
            "module": torch.tensor([0, 1]),
            "accepted": torch.tensor([1, 0]),
            "relation": torch.tensor([2, 1]),
            "weight": torch.ones(2),
            "relation_weight": torch.ones(2),
        },
    )
    assert scene_total.isfinite()
    assert set(scene_losses) == {"surface", "accepted", "t03_relation", "t04_relation", "module", "total"}

    graph_prediction = model(x=torch.zeros((3, 103)), edge_index=torch.empty((2, 0), dtype=torch.long))
    graph_total, graph_losses = m2r_graph_loss(
        graph_prediction,
        {
            "operation": torch.tensor([0, 1, 0]),
            "weight": torch.ones(3),
            "direction": torch.tensor([0, -1, 1]),
            "source": torch.tensor([0, 1, -1]),
            "split_fractions": torch.zeros((3, 2)),
            "split_fraction_mask": torch.zeros((3, 2)),
            "child_geometry": torch.zeros((3, 3, 16, 2)),
            "child_mask": torch.zeros((3, 3)),
            "t05_endpoint_relation": torch.tensor([[1, 0], [-1, -1], [0, 1]]),
            "t07_endpoint_member": torch.tensor([[1, 1], [1, 0], [-1, -1]]),
        },
        operation_class_weights=torch.ones(5),
        include_t07=True,
    )
    assert graph_total.isfinite()
    assert "t06_operation" in graph_losses
    assert "t05_endpoint" in graph_losses
    assert "t07_endpoint" in graph_losses


def test_t07_ablation_removes_only_optional_head() -> None:
    model = _model(include_t07=False)
    prediction = model(x=torch.zeros((2, 103)), edge_index=torch.empty((2, 0), dtype=torch.long))
    assert "t05_endpoint" in prediction
    assert "t07_endpoint" not in prediction
