from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_multi_view_plan_audit import (
    build_ranked_prefix_sets,
)


def test_ranked_prefix_sets_use_scores_without_truth_cardinality() -> None:
    result = build_ranked_prefix_sets(
        (0, 2, 3),
        scores=torch.tensor([0.4, 0.9, 0.8, 0.6]),
    )
    assert result == ((2,), (2, 3), (0, 2, 3))
