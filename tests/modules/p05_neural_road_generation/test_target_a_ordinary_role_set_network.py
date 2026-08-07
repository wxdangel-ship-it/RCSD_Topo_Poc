from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_role_set_network import (
    TargetAOrdinaryCountAwareRoleSetDecoder,
    TargetAOrdinaryRoleSetDecoder,
)


def test_role_set_decoder_preserves_membership_forward_and_adds_roles() -> None:
    model = TargetAOrdinaryRoleSetDecoder(dropout=0.0)
    outputs = model(
        object_features=torch.randn(2, 64),
        candidate_features=torch.randn(2, 5, 40),
        candidate_mask=torch.tensor(
            [
                [True, True, False, False, False],
                [True, True, True, True, True],
            ]
        ),
    )
    assert outputs["decision_logits"].shape == (2, 2)
    assert outputs["cardinality_logits"].shape == (2, 67)
    assert outputs["member_logits"].shape == (2, 5)
    assert outputs["ownership_logits"].shape == (2, 5, 3)
    assert outputs["business_role_logits"].shape == (2, 5, 4)
    assert outputs["ownership_logits"][0, 2:].eq(0).all()
    assert outputs["business_role_logits"][0, 2:].eq(0).all()


def test_count_aware_decoder_exposes_ordinal_and_soft_count() -> None:
    model = TargetAOrdinaryCountAwareRoleSetDecoder(dropout=0.0)
    outputs = model(
        object_features=torch.randn(2, 64),
        candidate_features=torch.randn(2, 6, 40),
        candidate_mask=torch.tensor(
            [
                [True, True, False, False, False, False],
                [True, True, True, True, True, True],
            ]
        ),
    )
    assert outputs["cardinality_logits"].shape == (2, 67)
    assert outputs["cardinality_ordinal_logits"].shape == (2, 66)
    assert outputs["soft_member_count"].shape == (2,)
    assert torch.all(outputs["soft_member_count"] >= 0.0)
    assert torch.all(outputs["soft_member_count"] <= torch.tensor([2.0, 6.0]))
