from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_beam_reranker import (
    BEAM_EMBEDDING_FEATURE_DIM,
    BEAM_RELATIONAL_FEATURE_DIM,
    _proposal_feature_vector,
    choose_zero_error_beam_threshold,
)


def test_beam_plan_feature_vector_is_fixed_and_truth_free() -> None:
    values = _proposal_feature_vector(
        rank=2,
        beam_width=8,
        decision_index=1,
        selected=(0, 1),
        log_probability=-2.0,
        top_log_probability=-1.0,
        log_normalizer=-0.5,
        sources=("RCSD", "RCSD", "SWSD"),
        decision_log_probabilities=torch.log(
            torch.tensor([0.2, 0.8])
        ),
        member_probabilities=torch.tensor([0.9, 0.8, 0.1]),
        ownership_probabilities=torch.tensor(
            [
                [0.1, 0.8, 0.1],
                [0.2, 0.6, 0.2],
                [0.8, 0.1, 0.1],
            ]
        ),
        role_probabilities=torch.tensor(
            [
                [0.1, 0.8, 0.05, 0.05],
                [0.2, 0.6, 0.1, 0.1],
                [0.8, 0.1, 0.05, 0.05],
            ]
        ),
        candidate_embeddings=torch.randn(3, 128),
        graph_context=torch.randn(128),
        road_relations=torch.zeros(3, 3, 13).index_put(
            (
                torch.tensor([0, 1]),
                torch.tensor([1, 0]),
                torch.tensor([0, 0]),
            ),
            torch.ones(2),
        ),
        access_seeds=torch.tensor([True, False, False]),
        feature_mode="EMBEDDING",
    )
    assert len(values) == BEAM_EMBEDDING_FEATURE_DIM
    assert all(torch.isfinite(torch.tensor(values)))
    assert values[2] == 1.0
    assert values[27] > 0.0


def test_relational_plan_features_are_candidate_order_invariant() -> None:
    sources = ("RCSD", "RCSD", "RCSD", "SWSD")
    selected = (0, 1)
    decision = torch.log(torch.tensor([0.2, 0.8]))
    member = torch.tensor([0.9, 0.8, 0.3, 0.1])
    ownership = torch.softmax(torch.randn(4, 3), dim=-1)
    roles = torch.softmax(torch.randn(4, 4), dim=-1)
    relations = torch.rand(4, 4, 13)
    relations = (relations + relations.transpose(0, 1)) / 2.0
    relations[..., 0] = relations[..., 0] > 0.6
    embeddings = torch.randn(4, 128)
    context = torch.randn(128)
    seeds = torch.tensor([True, False, False, False])
    original = _proposal_feature_vector(
        rank=3,
        beam_width=16,
        decision_index=1,
        selected=selected,
        log_probability=-3.0,
        top_log_probability=-1.0,
        log_normalizer=-0.5,
        sources=sources,
        decision_log_probabilities=decision,
        member_probabilities=member,
        ownership_probabilities=ownership,
        role_probabilities=roles,
        candidate_embeddings=embeddings,
        graph_context=context,
        road_relations=relations,
        access_seeds=seeds,
        feature_mode="RELATIONAL",
    )
    permutation = torch.tensor([2, 0, 3, 1])
    remapped_selected = tuple(
        index
        for index, original_index in enumerate(permutation.tolist())
        if original_index in selected
    )
    permuted = _proposal_feature_vector(
        rank=3,
        beam_width=16,
        decision_index=1,
        selected=remapped_selected,
        log_probability=-3.0,
        top_log_probability=-1.0,
        log_normalizer=-0.5,
        sources=tuple(sources[index] for index in permutation),
        decision_log_probabilities=decision,
        member_probabilities=member[permutation],
        ownership_probabilities=ownership[permutation],
        role_probabilities=roles[permutation],
        candidate_embeddings=embeddings[permutation],
        graph_context=context,
        road_relations=relations[permutation][:, permutation],
        access_seeds=seeds[permutation],
        feature_mode="RELATIONAL",
    )
    assert len(original) == BEAM_RELATIONAL_FEATURE_DIM
    assert torch.allclose(
        torch.tensor(original),
        torch.tensor(permuted),
        atol=1e-6,
    )


def test_zero_error_threshold_excludes_observed_wrong_plan() -> None:
    rows = [
        {
            "raw_automatic": True,
            "raw_complete_exact": False,
            "confidence": 0.8,
        },
        {
            "raw_automatic": True,
            "raw_complete_exact": True,
            "confidence": 0.9,
        },
    ]
    threshold = choose_zero_error_beam_threshold(rows)
    assert threshold > 0.8
    assert threshold < 0.9
