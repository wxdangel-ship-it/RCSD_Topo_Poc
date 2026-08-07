from __future__ import annotations

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_member_aware_plan_network import (
    OrdinaryMemberAwarePlanConfig,
    OrdinaryMemberAwarePlanNetwork,
)


def _inputs() -> dict[str, torch.Tensor]:
    generator = torch.Generator().manual_seed(7)
    candidate_signals = torch.randn(2, 5, 7, generator=generator)
    road_relations = torch.randn(2, 5, 5, 3, generator=generator)
    candidate_sources = torch.tensor(
        [[0, 0, 1, 1, 1], [0, 1, 1, 0, 1]], dtype=torch.long
    )
    candidate_mask = torch.tensor(
        [[True, True, True, True, True], [True, True, True, True, False]]
    )
    proposal_scalars = torch.randn(2, 4, 6, generator=generator)
    proposal_sources = torch.tensor(
        [[0, 1, 1, 0], [0, 1, 0, 1]], dtype=torch.long
    )
    proposal_selected = torch.zeros(2, 4, 5, dtype=torch.bool)
    proposal_selected[0, 1, [2, 3]] = True
    proposal_selected[0, 2, [2, 3, 4]] = True
    proposal_selected[0, 3, [0]] = True
    proposal_selected[1, 0, [0, 3]] = True
    proposal_selected[1, 1, [1]] = True
    proposal_selected[1, 2, [3]] = True
    proposal_selected[1, 3, [1, 2]] = True
    proposal_mask = torch.tensor(
        [[True, True, True, True], [True, True, True, False]]
    )
    proposal_selected[1, 3] = False
    return {
        "candidate_signals": candidate_signals,
        "road_relations": road_relations,
        "candidate_sources": candidate_sources,
        "candidate_mask": candidate_mask,
        "proposal_scalars": proposal_scalars,
        "proposal_sources": proposal_sources,
        "proposal_selected": proposal_selected,
        "proposal_mask": proposal_mask,
    }


def _model() -> OrdinaryMemberAwarePlanNetwork:
    return OrdinaryMemberAwarePlanNetwork(
        OrdinaryMemberAwarePlanConfig(
            signal_dim=7,
            relation_dim=3,
            scalar_feature_dim=6,
            hidden_dim=16,
            graph_layer_count=1,
            proposal_layer_count=1,
            attention_head_count=4,
            feedforward_dim=32,
            dropout=0.0,
        )
    ).eval()


def test_member_aware_plan_compares_keep_and_use_without_given_decision() -> None:
    model = _model()
    values = _inputs()
    with torch.no_grad():
        outputs = model(**values)
    assert outputs["plan_logits"].shape == (2, 4)
    assert outputs["plan_validity_logits"].shape == (2, 4)
    assert outputs["selected_attention"].shape == (2, 4, 5)
    assert torch.isfinite(outputs["plan_logits"][values["proposal_mask"]]).all()
    assert torch.isneginf(outputs["plan_logits"][1, 3])
    assert torch.count_nonzero(outputs["selected_attention"][0, 0]) == 0
    assert "effective_decision" not in model.forward.__annotations__


def test_member_aware_plan_is_road_and_proposal_permutation_equivariant() -> None:
    model = _model()
    values = _inputs()
    road_order = torch.tensor([3, 0, 4, 2, 1])
    proposal_order = torch.tensor([2, 0, 3, 1])
    permuted = {
        **values,
        "candidate_signals": values["candidate_signals"][:, road_order],
        "road_relations": values["road_relations"][:, road_order][:, :, road_order],
        "candidate_sources": values["candidate_sources"][:, road_order],
        "candidate_mask": values["candidate_mask"][:, road_order],
        "proposal_scalars": values["proposal_scalars"][:, proposal_order],
        "proposal_sources": values["proposal_sources"][:, proposal_order],
        "proposal_selected": values["proposal_selected"][:, proposal_order][
            :, :, road_order
        ],
        "proposal_mask": values["proposal_mask"][:, proposal_order],
    }
    with torch.no_grad():
        original = model(**values)["plan_logits"]
        changed = model(**permuted)["plan_logits"]
    assert torch.allclose(
        changed,
        original[:, proposal_order],
        atol=1e-5,
        rtol=1e-5,
    )


def test_member_aware_plan_rejects_cross_source_member() -> None:
    model = _model()
    values = _inputs()
    values["proposal_selected"][0, 0, 2] = True
    with pytest.raises(ValueError, match="outside its source"):
        model(**values)


def test_member_aware_feature_normalization_is_explicit() -> None:
    model = _model()
    model.set_feature_normalization(
        candidate_signals=torch.randn(10, 7),
        road_relations=torch.randn(20, 3),
        proposal_scalars=torch.randn(12, 6),
    )
    assert torch.isfinite(model.signal_mean).all()
    assert torch.all(model.signal_std >= 1e-4)
