from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_drivezone_surface import (
    DriveZoneOnlySurfaceNetwork,
    pool_surface_features_by_object,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_TOKEN_DIM,
    SURFACE_GRID_SIZE,
)


def test_drivezone_surface_network_preserves_full_resolution() -> None:
    model = DriveZoneOnlySurfaceNetwork(base_channels=8, dropout=0.0).eval()
    values = torch.zeros(2, SURFACE_GRID_SIZE, SURFACE_GRID_SIZE)
    values[:, 50:78, 60:68] = 1.0

    output = model(values)

    assert output.surface_logits.shape == (2, SURFACE_GRID_SIZE, SURFACE_GRID_SIZE)
    assert output.surface_features.shape == (2, 8, SURFACE_GRID_SIZE, SURFACE_GRID_SIZE)


def test_surface_object_pool_ignores_outside_and_padding_tokens() -> None:
    features = torch.ones(1, 3, SURFACE_GRID_SIZE, SURFACE_GRID_SIZE)
    logits = torch.zeros(1, SURFACE_GRID_SIZE, SURFACE_GRID_SIZE)
    tokens = torch.zeros(1, 4, GEOMETRY_TOKEN_DIM)
    tokens[0, 1, 7] = 2.0
    mask = torch.tensor([[True, True, True, False]])
    indices = torch.tensor([[0, 0, 1, -1]])

    pooled = pool_surface_features_by_object(
        features,
        logits,
        tokens,
        mask,
        indices,
        object_count=2,
    )

    assert pooled.shape == (1, 2, 8)
    assert torch.allclose(pooled[0, 0, :3], torch.ones(3))
    assert torch.allclose(pooled[0, 1, :3], torch.ones(3))
