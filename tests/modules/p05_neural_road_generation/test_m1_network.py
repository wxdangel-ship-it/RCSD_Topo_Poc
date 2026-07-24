from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_network import (  # noqa: E402
    RoadOperationGraphNet,
    multitask_loss,
    trainable_parameter_count,
)


def test_graph_model_parameter_count_and_multitask_shapes() -> None:
    model = RoadOperationGraphNet(103, hidden_dim=384, layers=6, dropout=0.0, polyline_points=16)
    assert 8_000_000 <= trainable_parameter_count(model) <= 15_000_000
    x = torch.randn(8, 103)
    edge_index = torch.tensor([[0, 1, 1, 2, 3, 4], [1, 0, 2, 1, 4, 3]], dtype=torch.long)
    prediction = model(x, edge_index)
    assert prediction["operation"].shape == (8, 5)
    assert prediction["child_geometry"].shape == (8, 3, 16, 2)
    batch = {
        "operation": torch.tensor([0, 1, 3, 1, 0, 1, 3, 1]),
        "weight": torch.full((8,), 0.7),
        "direction": torch.tensor([-1, 2, 2, 2, -1, 2, 2, 2]),
        "source": torch.tensor([-1, 1, 1, 2, -1, 1, 1, 2]),
        "split_fractions": torch.zeros(8, 2),
        "split_fraction_mask": torch.zeros(8, 2),
        "child_geometry": torch.zeros(8, 3, 16, 2),
        "child_mask": torch.zeros(8, 3),
    }
    loss, parts = multitask_loss(prediction, batch, operation_class_weights=torch.ones(5))
    assert torch.isfinite(loss)
    assert set(parts) == {"operation", "direction", "source", "split_fraction", "child_geometry", "total"}
