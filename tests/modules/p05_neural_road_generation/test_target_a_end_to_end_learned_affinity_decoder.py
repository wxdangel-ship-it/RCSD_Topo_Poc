from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_learned_affinity_decoder import (
    TargetALearnedAffinityGraphSetConfig,
    TargetALearnedAffinityGraphSetDecoder,
    compute_learned_affinity_graph_set_loss,
)


def _model() -> TargetALearnedAffinityGraphSetDecoder:
    return TargetALearnedAffinityGraphSetDecoder(
        TargetALearnedAffinityGraphSetConfig(
            signal_dim=7,
            relation_dim=3,
            embedding_dim=8,
            pair_signal_dim=4,
            pair_hidden_dim=12,
            decoder_hidden_dim=16,
            decoder_layer_count=1,
            maximum_cardinality=5,
            dropout=0.0,
        )
    )


def _inputs() -> dict[str, torch.Tensor]:
    return {
        "candidate_signals": torch.randn(1, 5, 7),
        "road_relations": torch.randn(1, 5, 5, 3),
        "candidate_sources": torch.tensor([[1, 1, 1, 0, 0]]),
        "candidate_mask": torch.ones((1, 5), dtype=torch.bool),
        "effective_decision": torch.tensor([1]),
    }


def test_learned_affinity_is_symmetric_and_source_gated() -> None:
    outputs = _model()(**_inputs())

    assert outputs["affinity_logits"].shape == (1, 5, 5)
    assert torch.allclose(
        outputs["affinity_logits"],
        outputs["affinity_logits"].transpose(1, 2),
    )
    assert outputs["allowed_mask"].tolist() == [
        [True, True, True, False, False]
    ]
    assert outputs["affinity_pair_valid"][0, :3, :3].all()
    assert not outputs["affinity_pair_valid"][0, 3:, :].any()


def test_pair_supervision_uses_only_multi_road_targets() -> None:
    model = _model()
    outputs = model(**_inputs())
    targets = torch.tensor([[True, True, False, False, False]])
    losses = compute_learned_affinity_graph_set_loss(
        outputs,
        member_targets=targets,
        task_mask=torch.tensor([True]),
        sample_weights=torch.tensor([1.0]),
    )

    assert losses["pair_task_mask"].tolist() == [True]
    assert losses["pair_targets"][0, 0, 1]
    assert torch.isfinite(losses["loss"])


def test_target_outside_source_disables_set_and_pair_tasks() -> None:
    model = _model()
    outputs = model(**_inputs())
    targets = torch.tensor([[True, True, False, True, False]])
    losses = compute_learned_affinity_graph_set_loss(
        outputs,
        member_targets=targets,
        task_mask=torch.tensor([True]),
        sample_weights=torch.tensor([1.0]),
    )

    assert losses["effective_task_mask"].tolist() == [False]
    assert losses["pair_task_mask"].tolist() == [False]
    assert torch.isfinite(losses["loss"])


def test_boundary_ranking_penalizes_false_road_above_true_road() -> None:
    outputs = _model()(**_inputs())
    targets = torch.tensor([[True, True, False, False, False]])

    separated = {
        **outputs,
        "member_logits": torch.tensor(
            [[3.0, 2.0, -1.0, -20.0, -20.0]],
            requires_grad=True,
        ),
    }
    inverted = {
        **outputs,
        "member_logits": torch.tensor(
            [[3.0, -1.0, 2.0, -20.0, -20.0]],
            requires_grad=True,
        ),
    }
    separated_loss = compute_learned_affinity_graph_set_loss(
        separated,
        member_targets=targets,
        task_mask=torch.tensor([True]),
        sample_weights=torch.tensor([1.0]),
        boundary_ranking_loss_weight=1.0,
    )
    inverted_loss = compute_learned_affinity_graph_set_loss(
        inverted,
        member_targets=targets,
        task_mask=torch.tensor([True]),
        sample_weights=torch.tensor([1.0]),
        boundary_ranking_loss_weight=1.0,
    )

    assert separated_loss["boundary_task_mask"].tolist() == [True]
    assert (
        separated_loss["boundary_ranking_loss"]
        < inverted_loss["boundary_ranking_loss"]
    )
    inverted_loss["loss"].backward()
    assert inverted["member_logits"].grad is not None
