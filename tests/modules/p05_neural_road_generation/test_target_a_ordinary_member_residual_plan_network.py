from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_encoded_set_reranker import (
    TargetAEndToEndListwiseSetTransformerConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_member_aware_plan_network import (
    OrdinaryMemberAwarePlanConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_member_residual_plan_network import (
    OrdinaryMemberResidualPlanNetwork,
)


def _model() -> OrdinaryMemberResidualPlanNetwork:
    return OrdinaryMemberResidualPlanNetwork(
        base_config=TargetAEndToEndListwiseSetTransformerConfig(
            feature_dim=20,
            hidden_dim=16,
            num_heads=4,
            layer_count=1,
            feedforward_dim=32,
            dropout=0.0,
        ),
        member_config=OrdinaryMemberAwarePlanConfig(
            signal_dim=7,
            relation_dim=3,
            scalar_feature_dim=6,
            hidden_dim=16,
            graph_layer_count=1,
            proposal_layer_count=1,
            attention_head_count=4,
            feedforward_dim=32,
            dropout=0.0,
        ),
    )


def _inputs() -> dict[str, torch.Tensor]:
    generator = torch.Generator().manual_seed(9)
    selected = torch.zeros(2, 3, 4, dtype=torch.bool)
    selected[0, 1, [2, 3]] = True
    selected[0, 2, [0]] = True
    selected[1, 0, [0, 2]] = True
    selected[1, 1, [1]] = True
    return {
        "base_features": torch.randn(2, 3, 20, generator=generator),
        "candidate_signals": torch.randn(2, 4, 7, generator=generator),
        "road_relations": torch.randn(2, 4, 4, 3, generator=generator),
        "candidate_sources": torch.tensor(
            [[0, 0, 1, 1], [0, 1, 0, 1]], dtype=torch.long
        ),
        "candidate_mask": torch.ones(2, 4, dtype=torch.bool),
        "proposal_scalars": torch.randn(2, 3, 6, generator=generator),
        "proposal_sources": torch.tensor(
            [[0, 1, 0], [0, 1, 0]], dtype=torch.long
        ),
        "proposal_selected": selected,
        "proposal_mask": torch.tensor(
            [[True, True, True], [True, True, False]]
        ),
    }


def test_zero_initialized_member_residual_reproduces_frozen_base() -> None:
    model = _model().eval()
    inputs = _inputs()
    with torch.no_grad():
        base = model.base(inputs["base_features"], inputs["proposal_mask"])
        outputs = model(**inputs)
    assert torch.allclose(outputs["plan_logits"], base["plan_logits"])
    assert torch.allclose(
        outputs["plan_validity_logits"], base["plan_validity_logits"]
    )
    assert torch.count_nonzero(outputs["plan_residual_logits"]) == 0


def test_frozen_base_stays_eval_and_only_member_receives_gradient() -> None:
    model = _model().train()
    assert not model.base.training
    assert all(not value.requires_grad for value in model.base.parameters())
    outputs = model(**_inputs())
    outputs["plan_logits"][torch.isfinite(outputs["plan_logits"])].sum().backward()
    assert all(value.grad is None for value in model.base.parameters())
    last = model.member.selection_head[-1]
    assert isinstance(last, torch.nn.Linear)
    assert last.weight.grad is not None
    assert torch.count_nonzero(last.weight.grad) > 0
