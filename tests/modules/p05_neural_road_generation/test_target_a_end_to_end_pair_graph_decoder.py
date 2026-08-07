from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_pair_graph_decoder import (
    TargetAPairGraphSetDecoder,
    TargetAPairGraphSetDecoderConfig,
    compute_pair_graph_set_loss,
    decode_pair_graph_set_proposals,
)


def test_pair_graph_decoder_respects_effective_source_gate() -> None:
    model = _model()
    outputs = model(
        candidate_signals=torch.rand(2, 4, 3),
        road_relations=torch.zeros(2, 4, 4, 13),
        pair_affinity=torch.rand(2, 4, 4),
        candidate_sources=torch.tensor([[0, 1, 1, 0], [0, 1, 1, 0]]),
        candidate_mask=torch.ones(2, 4, dtype=torch.bool),
        effective_decision=torch.tensor([1, 2]),
    )
    assert outputs["allowed_mask"].tolist() == [
        [False, True, True, False],
        [False, False, False, False],
    ]
    assert outputs["member_logits"].shape == (2, 4)
    assert outputs["cardinality_logits"].shape == (2, 5)
    assert torch.isfinite(outputs["member_logits"]).all()


def test_pair_graph_loss_masks_mixed_source_target() -> None:
    model = _model()
    outputs = model(
        candidate_signals=torch.rand(2, 4, 3),
        road_relations=torch.zeros(2, 4, 4, 13),
        pair_affinity=torch.rand(2, 4, 4),
        candidate_sources=torch.tensor([[0, 1, 1, 0], [0, 1, 1, 0]]),
        candidate_mask=torch.ones(2, 4, dtype=torch.bool),
        effective_decision=torch.tensor([1, 1]),
    )
    loss = compute_pair_graph_set_loss(
        outputs,
        member_targets=torch.tensor(
            [[False, True, True, False], [True, True, False, False]]
        ),
        task_mask=torch.ones(2, dtype=torch.bool),
        sample_weights=torch.ones(2),
    )
    assert torch.isfinite(loss["loss"])
    assert loss["effective_task_mask"].tolist() == [True, False]
    assert loss["target_outside_source_gate"].tolist() == [False, True]


def test_pair_graph_decode_returns_only_allowed_complete_sets() -> None:
    proposals = decode_pair_graph_set_proposals(
        {
            "member_logits": torch.tensor([[5.0, 4.0, 3.0, 20.0]]),
            "cardinality_logits": torch.tensor(
                [[-5.0, 0.0, 6.0, 1.0, 0.0]]
            ),
            "allowed_mask": torch.tensor([[True, True, True, False]]),
        },
        cardinality_width=3,
    )[0]
    selected = {
        tuple(value["selected_indices"]) for value in proposals
    }
    assert (0, 1) in selected
    assert all(3 not in value for value in selected)


def _model() -> TargetAPairGraphSetDecoder:
    return TargetAPairGraphSetDecoder(
        TargetAPairGraphSetDecoderConfig(
            hidden_dim=16,
            layer_count=1,
            maximum_cardinality=4,
            dropout=0.0,
        )
    )
