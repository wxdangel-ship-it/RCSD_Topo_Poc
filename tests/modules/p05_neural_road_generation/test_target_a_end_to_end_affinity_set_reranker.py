from __future__ import annotations

import pytest
import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_affinity_set_reranker import (
    AFFINITY_SET_FEATURE_DIM,
    build_affinity_set_proposal_features,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_set_reranker import (
    END_TO_END_SET_RERANKER_FEATURE_DIM,
)


def test_affinity_features_distinguish_coherent_road_sets() -> None:
    logits = torch.tensor(
        [
            [-20.0, 5.0, -4.0, -20.0],
            [5.0, -20.0, -3.0, -20.0],
            [-4.0, -3.0, -20.0, -20.0],
            [-20.0, -20.0, -20.0, -20.0],
        ]
    )
    features = build_affinity_set_proposal_features(
        [
            {"selected_indices": [0, 1]},
            {"selected_indices": [0, 2, 3]},
        ],
        scalar_features=torch.zeros(
            2,
            END_TO_END_SET_RERANKER_FEATURE_DIM,
        ),
        affinity_logits=logits,
        allowed_mask=torch.tensor([True, True, True, False]),
    )
    assert features.shape == (2, AFFINITY_SET_FEATURE_DIM)
    affinity = features[:, END_TO_END_SET_RERANKER_FEATURE_DIM :]
    assert affinity[0, 0] > affinity[1, 0]
    assert affinity[0, 5] > affinity[1, 5]
    assert affinity[0, 6] > affinity[1, 6]


def test_affinity_features_validate_pair_shape() -> None:
    with pytest.raises(ValueError, match="feature inputs differ"):
        build_affinity_set_proposal_features(
            [{"selected_indices": [0]}],
            scalar_features=torch.zeros(
                1,
                END_TO_END_SET_RERANKER_FEATURE_DIM,
            ),
            affinity_logits=torch.zeros(2, 3),
            allowed_mask=torch.ones(2, dtype=torch.bool),
        )
