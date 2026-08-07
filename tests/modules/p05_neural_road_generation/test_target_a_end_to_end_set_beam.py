from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_data import (
    ORDINARY_SET_ROAD_RELATION_DIM,
    EndToEndOrdinarySetBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_set_beam import (
    beam_decode_ordinary_side,
    diverse_beam_decode_ordinary_side,
    ranked_subset_proposals,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_encoded_set_reranker import (
    TargetAEndToEndEncodedSetReranker,
    TargetAEndToEndEncodedSetRerankerConfig,
    TargetAEndToEndListwiseSetTransformer,
    TargetAEndToEndListwiseSetTransformerConfig,
    TargetAEndToEndLinearSetReranker,
    TargetAEndToEndLinearSetRerankerConfig,
    build_encoded_set_proposal_features,
    encoded_set_feature_dim,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_set_reranker import (
    END_TO_END_SET_RERANKER_FEATURE_DIM,
    TargetAEndToEndSetReranker,
    TargetAEndToEndSetRerankerConfig,
    build_end_to_end_set_proposal_features,
    listwise_multi_positive_loss,
)


def test_beam_decoder_proposes_complete_source_gated_set() -> None:
    batch = _ordinary_batch()
    outputs = {
        "_ordinary_road_encoded": torch.zeros((1, 2, 2, 4)),
        "_ordinary_expansion_context": torch.zeros((1, 2, 4)),
    }
    proposals = beam_decode_ordinary_side(
        _FakeExpansionModel(),
        outputs,
        batch,
        side_index=0,
        effective_decision=1,
        beam_width=4,
    )
    assert proposals
    assert any(
        value["selected_indices"] == [0, 1] for value in proposals
    )
    assert (
        beam_decode_ordinary_side(
            _FakeExpansionModel(),
            outputs,
            batch,
            side_index=0,
            effective_decision=2,
            beam_width=4,
        )
        == []
    )
    diverse = diverse_beam_decode_ordinary_side(
        _FakeExpansionModel(),
        outputs,
        batch,
        side_index=0,
        effective_decision=1,
        active_beam_width=4,
        proposal_width=4,
        cardinality_logits=torch.tensor([0.0, 0.0, 4.0]),
    )
    assert diverse
    assert any(
        value["selected_indices"] == [0, 1] for value in diverse
    )


def test_complete_set_reranker_uses_only_proposal_evidence() -> None:
    proposals = [
        {"selected_indices": [0], "log_probability": -1.0},
        {"selected_indices": [0, 1], "log_probability": -1.5},
    ]
    relations = torch.zeros((3, 3, 13))
    relations[0, 1, 0] = 1.0
    relations[1, 0, 0] = 1.0
    features = build_end_to_end_set_proposal_features(
        proposals,
        member_logits=torch.tensor([2.0, 1.0, -2.0]),
        cardinality_logits=torch.tensor([-3.0, 0.0, 2.0, -1.0]),
        road_relations=relations,
        allowed_mask=torch.ones(3, dtype=torch.bool),
    )
    assert features.shape == (2, END_TO_END_SET_RERANKER_FEATURE_DIM)
    model = TargetAEndToEndSetReranker(
        TargetAEndToEndSetRerankerConfig(
            hidden_dim=8,
            dropout=0.0,
        )
    )
    model.set_feature_normalization(features)
    scores = model(features).unsqueeze(0)
    loss = listwise_multi_positive_loss(
        scores,
        proposal_mask=torch.ones_like(scores, dtype=torch.bool),
        positive_mask=torch.tensor([[False, True]]),
        sample_weights=torch.ones(1),
    )
    assert torch.isfinite(loss)


def test_ranked_subset_proposals_keep_cardinality_and_graph_variants() -> None:
    relations = torch.zeros((4, 4, ORDINARY_SET_ROAD_RELATION_DIM))
    relations[0, 2, 0] = 1.0
    relations[2, 0, 0] = 1.0
    proposals = ranked_subset_proposals(
        member_logits=torch.tensor([4.0, 3.0, 2.0, 100.0]),
        cardinality_logits=torch.tensor([-4.0, 0.0, 5.0, 1.0, 0.0]),
        road_relations=relations,
        allowed_mask=torch.tensor([True, True, True, False]),
        proposal_width=16,
        cardinality_width=3,
        boundary_width=2,
        seed_width=3,
    )
    selected = {
        tuple(value["selected_indices"]) for value in proposals
    }
    assert (0, 1) in selected
    assert (0, 2) in selected
    assert (0, 1, 2) in selected
    assert all(3 not in value for value in selected)
    assert proposals[0]["log_probability"] >= proposals[-1][
        "log_probability"
    ]


def test_encoded_set_reranker_pools_shared_road_embeddings() -> None:
    proposals = [
        {"selected_indices": [0], "log_probability": -1.0},
        {"selected_indices": [0, 1], "log_probability": -1.5},
    ]
    features = build_encoded_set_proposal_features(
        proposals,
        scalar_features=torch.zeros(
            2,
            END_TO_END_SET_RERANKER_FEATURE_DIM,
        ),
        road_embeddings=torch.tensor(
            [
                [1.0, 0.0, 0.0, 0.0],
                [0.0, 1.0, 0.0, 0.0],
                [0.0, 0.0, 1.0, 0.0],
            ]
        ),
        allowed_mask=torch.ones(3, dtype=torch.bool),
    )
    assert features.shape == (2, encoded_set_feature_dim(4))
    assert not torch.equal(features[0], features[1])
    model = TargetAEndToEndEncodedSetReranker(
        TargetAEndToEndEncodedSetRerankerConfig(
            feature_dim=features.shape[-1],
            hidden_dim=32,
            dropout=0.0,
        )
    )
    model.set_feature_normalization(features)
    assert torch.isfinite(model(features)).all()
    compact = torch.cat((features[:, :18], features[:, -4:]), dim=-1)
    linear = TargetAEndToEndLinearSetReranker(
        TargetAEndToEndLinearSetRerankerConfig(
            feature_dim=compact.shape[-1],
        )
    )
    linear.set_feature_normalization(compact)
    assert torch.isfinite(linear(compact)).all()


def test_listwise_set_transformer_compares_complete_proposals() -> None:
    torch.manual_seed(7)
    values = torch.randn(2, 3, 22)
    valid = torch.tensor(
        [[True, True, True], [True, True, False]]
    )
    model = TargetAEndToEndListwiseSetTransformer(
        TargetAEndToEndListwiseSetTransformerConfig(
            feature_dim=22,
            hidden_dim=32,
            num_heads=4,
            layer_count=1,
            feedforward_dim=64,
            dropout=0.0,
        )
    )
    model.set_feature_normalization(values[valid])
    model.eval()
    outputs = model(values, valid)
    assert outputs["plan_logits"].shape == (2, 3)
    assert torch.isneginf(outputs["plan_logits"][1, 2])
    permutation = torch.tensor([2, 0, 1])
    permuted = model(
        values[0:1, permutation],
        valid[0:1, permutation],
    )
    assert torch.allclose(
        permuted["plan_logits"][0],
        outputs["plan_logits"][0, permutation],
        atol=1e-5,
    )
    outputs["plan_logits"][valid].sum().backward()
    assert model.selection_head[-1].weight.grad is not None


class _FakeExpansionModel:
    def decode_ordinary_next(
        self,
        encoded_outputs,
        ordinary_set,
        selected_masks,
        *,
        candidate_mask,
    ):
        del encoded_outputs, ordinary_set
        batch_size, side_count, state_count, road_count = (
            selected_masks.shape
        )
        next_logits = torch.full(
            (batch_size, side_count, state_count, road_count),
            torch.finfo(torch.float32).min,
        )
        stop_logits = torch.full(
            (batch_size, side_count, state_count),
            -6.0,
        )
        for state in range(state_count):
            selected = selected_masks[0, 0, state]
            remaining = candidate_mask[0, 0] & ~selected
            next_logits[0, 0, state, remaining] = 0.0
            if not bool(remaining.any()):
                stop_logits[0, 0, state] = 0.0
        return {
            "next_road_logits": next_logits,
            "stop_logits": stop_logits,
        }


def _ordinary_batch() -> EndToEndOrdinarySetBatch:
    return EndToEndOrdinarySetBatch(
        case_keys=("T10:case",),
        advance_right_ids=("ar",),
        side_segment_ids=(("s1", "s2"),),
        side_group_indices=torch.tensor([[0, 1]]),
        side_object_values=torch.zeros((1, 2, 64)),
        side_road_values=torch.zeros((1, 2, 2, 40)),
        side_road_mask=torch.ones((1, 2, 2), dtype=torch.bool),
        side_road_source_indices=torch.ones((1, 2, 2), dtype=torch.long),
        side_road_relation_values=torch.zeros(
            (1, 2, 2, 2, ORDINARY_SET_ROAD_RELATION_DIM)
        ),
        side_access_values=torch.zeros((1, 2, 1, 64)),
        side_access_mask=torch.zeros((1, 2, 1), dtype=torch.bool),
        decision_targets=torch.ones((1, 2), dtype=torch.long),
        decision_task_mask=torch.ones((1, 2), dtype=torch.bool),
        road_member_targets=torch.ones((1, 2, 2), dtype=torch.bool),
        road_task_mask=torch.ones((1, 2), dtype=torch.bool),
        road_cardinality_targets=torch.full((1, 2), 2, dtype=torch.long),
        access_targets=torch.zeros((1, 2, 1), dtype=torch.bool),
        access_task_mask=torch.zeros((1, 2), dtype=torch.bool),
        sample_weights=torch.ones((1, 2)),
        candidate_reachable=torch.ones((1, 2), dtype=torch.bool),
        road_ids=((("r1", "r2"), ("r3", "r4")),),
        access_road_ids=(((), ()),),
    )
