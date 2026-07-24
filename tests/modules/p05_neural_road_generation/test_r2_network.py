from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.r2_models import R2SlotLimits
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_network import (
    R2GraphGenerator,
    parameter_count,
    r2_graph_loss,
)


def _limits() -> R2SlotLimits:
    return R2SlotLimits(
        road_slots=7,
        node_slots=9,
        t05_node_slots=8,
        pointer_queries=4,
        road_action_queries=10,
        node_action_queries=11,
        t05_action_queries=12,
    )


def test_r2_network_shapes_and_gradients() -> None:
    model = R2GraphGenerator(
        road_input_dim=6,
        limits=_limits(),
        hidden_dim=64,
        graph_layers=2,
        query_layers=2,
        polyline_points=5,
        include_scene=False,
    )
    graph_x = torch.randn(13, 6)
    edge_index = torch.tensor([[0, 1, 2, 3], [1, 2, 3, 4]], dtype=torch.long)
    prediction = model.forward_graph(
        graph_x,
        edge_index,
        road_count=7,
        node_count=9,
        t05_node_count=8,
        pointer_count=4,
        road_action_count=10,
        node_action_count=11,
        t05_action_count=12,
    )
    assert prediction["road_geometry"].shape == (7, 5, 2)
    assert prediction["node_xy"].shape == (9, 2)
    assert prediction["road_endpoint"].shape == (7, 2, 9)
    assert prediction["pointer"].shape == (4, 9)
    assert prediction["road_action"].shape == (10, 5)

    batch = {
        "road_geometry": torch.rand(7, 5, 2) - 0.5,
        "node_xy": torch.rand(9, 2) - 0.5,
        "t05_node_xy": torch.rand(8, 2) - 0.5,
        "road_direction": torch.randint(0, 2, (7,)),
        "road_source": torch.randint(0, 2, (7,)),
        "road_endpoint": torch.randint(0, 9, (7, 2)),
        "pointer": torch.randint(0, 9, (4,)),
        "road_action": torch.randint(0, 5, (10,)),
        "node_action": torch.randint(0, 4, (11,)),
        "t05_action": torch.randint(0, 4, (12,)),
        "counts": torch.tensor([7 / 7, 9 / 9, 8 / 8, 4 / 4]),
    }
    loss, parts = r2_graph_loss(prediction, batch)
    loss.backward()
    assert torch.isfinite(loss)
    assert parts["total"] > 0
    assert any(parameter.grad is not None for parameter in model.parameters())


def test_production_slot_model_stays_in_20m_to_50m_target() -> None:
    model = R2GraphGenerator(
        road_input_dim=103,
        limits=R2SlotLimits(
            road_slots=7099,
            node_slots=8037,
            t05_node_slots=6884,
            pointer_queries=1427,
            road_action_queries=10962,
            node_action_queries=10472,
            t05_action_queries=10113,
        ),
        hidden_dim=384,
        graph_layers=4,
        query_layers=2,
        polyline_points=32,
        include_scene=True,
    )
    assert 20_000_000 <= parameter_count(model) <= 50_000_000
