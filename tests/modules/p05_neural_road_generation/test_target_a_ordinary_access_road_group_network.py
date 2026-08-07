from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_access_road_group_network import (
    TargetAOrdinaryAccessRoadGroupDecoder,
)


def test_access_road_group_decoder_shapes_and_padding() -> None:
    model = TargetAOrdinaryAccessRoadGroupDecoder(
        feature_dim=12,
        hidden_dim=16,
        context_dim=24,
        attention_heads=4,
        maximum_per_road=2,
        dropout=0.0,
    )
    values = torch.randn(2, 5, 12)
    mask = torch.tensor(
        [[True, True, True, True, False], [True, True, True, False, False]]
    )
    roads = torch.tensor(
        [
            [0, 0, 1, 2, -1],
            [0, 1, 1, -1, -1],
        ]
    )
    same = (
        roads.unsqueeze(1) == roads.unsqueeze(2)
    ) & mask.unsqueeze(1) & mask.unsqueeze(2)
    outputs = model(values, mask, same)
    assert outputs["candidate_logits"].shape == (2, 5)
    assert outputs["road_count_logits"].shape == (2, 5, 3)
    assert torch.isfinite(outputs["candidate_logits"]).all()
    assert torch.isfinite(outputs["road_count_logits"]).all()
    assert torch.allclose(
        outputs["road_count_logits"][0, 0],
        outputs["road_count_logits"][0, 1],
    )
    assert torch.allclose(
        outputs["road_count_logits"][1, 1],
        outputs["road_count_logits"][1, 2],
    )


def test_access_road_group_decoder_is_candidate_permutation_equivariant() -> None:
    torch.manual_seed(7)
    model = TargetAOrdinaryAccessRoadGroupDecoder(
        feature_dim=10,
        hidden_dim=16,
        context_dim=24,
        attention_heads=4,
        maximum_per_road=2,
        dropout=0.0,
    ).eval()
    values = torch.randn(1, 5, 10)
    mask = torch.ones(1, 5, dtype=torch.bool)
    roads = torch.tensor([[0, 1, 0, 2, 1]])
    same = roads.unsqueeze(1) == roads.unsqueeze(2)
    permutation = torch.tensor([3, 0, 4, 2, 1])
    inverse = permutation.argsort()
    original = model(values, mask, same)
    permuted = model(
        values[:, permutation],
        mask[:, permutation],
        same[:, permutation][:, :, permutation],
    )
    assert torch.allclose(
        original["candidate_logits"],
        permuted["candidate_logits"][:, inverse],
        atol=1e-6,
    )
    assert torch.allclose(
        original["road_count_logits"],
        permuted["road_count_logits"][:, inverse],
        atol=1e-6,
    )


def test_access_road_group_decoder_rejects_invalid_relation_mask() -> None:
    model = TargetAOrdinaryAccessRoadGroupDecoder(
        feature_dim=6,
        hidden_dim=8,
        context_dim=12,
        attention_heads=2,
        dropout=0.0,
    )
    values = torch.randn(1, 2, 6)
    mask = torch.ones(1, 2, dtype=torch.bool)
    invalid = torch.tensor([[[True, True], [False, True]]])
    try:
        model(values, mask, invalid)
    except ValueError as error:
        assert "symmetric" in str(error)
    else:
        raise AssertionError("invalid same-Road mask was accepted")
