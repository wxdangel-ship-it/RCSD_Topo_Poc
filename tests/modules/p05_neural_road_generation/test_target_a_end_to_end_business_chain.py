from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_business_chain import (
    ADVANCE_RIGHT_LOCAL_FALLBACK,
    ADVANCE_RIGHT_MIXED_SPLICE,
    ADVANCE_RIGHT_RCSD_ONLY,
    ADVANCE_RIGHT_SWSD_ONLY,
    advance_right_business_plan_mask,
    advance_right_plan_type_from_ordinary,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ORDINARY_DECISION_ABSTAIN,
    ORDINARY_DECISION_KEEP_SWSD,
    ORDINARY_DECISION_USE_RCSD,
)


def test_advance_right_plan_type_is_fixed_by_both_ordinary_sides() -> None:
    source = torch.tensor([[
        ORDINARY_DECISION_KEEP_SWSD,
        ORDINARY_DECISION_USE_RCSD,
        ORDINARY_DECISION_KEEP_SWSD,
        ORDINARY_DECISION_ABSTAIN,
    ]])
    target = torch.tensor([[
        ORDINARY_DECISION_KEEP_SWSD,
        ORDINARY_DECISION_USE_RCSD,
        ORDINARY_DECISION_USE_RCSD,
        ORDINARY_DECISION_USE_RCSD,
    ]])

    plan_type, ready = advance_right_plan_type_from_ordinary(source, target)

    assert plan_type.tolist() == [[
        ADVANCE_RIGHT_SWSD_ONLY,
        ADVANCE_RIGHT_RCSD_ONLY,
        ADVANCE_RIGHT_MIXED_SPLICE,
        ADVANCE_RIGHT_LOCAL_FALLBACK,
    ]]
    assert ready.tolist() == [[True, True, True, False]]


def test_business_mask_cannot_reverse_ordinary_source_decisions() -> None:
    features = torch.zeros((1, 4, 2, 64))
    features[:, :, 0, 60] = 1.0
    features[:, :, 1, 61] = 1.0
    candidate_mask = torch.ones((1, 4, 2), dtype=torch.bool)
    plan_type = torch.tensor([[
        ADVANCE_RIGHT_SWSD_ONLY,
        ADVANCE_RIGHT_RCSD_ONLY,
        ADVANCE_RIGHT_MIXED_SPLICE,
        ADVANCE_RIGHT_LOCAL_FALLBACK,
    ]])

    mask = advance_right_business_plan_mask(
        features,
        candidate_mask,
        plan_type,
    )

    assert mask.tolist() == [[
        [True, False],
        [False, True],
        [False, True],
        [False, False],
    ]]
