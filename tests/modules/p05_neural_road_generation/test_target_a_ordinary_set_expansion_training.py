from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_training import (
    SetExpansionTrainingConfig,
    _cardinality_weight,
    _expansion_loss_rows,
    _frontier_acceptable_masks,
    _frontier_prefix_masks,
    _prefix_counts,
    _prefix_masks,
)


def test_prefix_masks_are_order_free_and_end_with_complete_target() -> None:
    targets = torch.tensor(
        [
            [True, False, True, False],
            [False, True, False, False],
        ]
    )
    selected, weights = _prefix_masks(targets, seed=17)
    assert selected.shape == (2, 4, 4)
    assert not bool(selected[:, 0].any())
    assert torch.equal(selected[:, 3], targets)
    assert not bool((selected & ~targets.unsqueeze(1)).any())
    assert weights[1].tolist() == [1.0, 0.0, 0.0, 1.0]


def test_large_road_sets_receive_bounded_training_emphasis() -> None:
    assert _cardinality_weight(1) == 1.0
    assert _cardinality_weight(5) == 1.5
    assert _cardinality_weight(9) == 2.0
    assert _cardinality_weight(10) == 3.0
    assert _cardinality_weight(66) == 3.0


def test_stop_bias_candidates_must_be_finite() -> None:
    SetExpansionTrainingConfig(
        stop_logit_bias_candidates=(-0.5, 0.0, 0.5),
    ).validate()
    try:
        SetExpansionTrainingConfig(
            stop_logit_bias_candidates=(float("nan"),),
        ).validate()
    except ValueError as error:
        assert "STOP-bias" in str(error)
    else:
        raise AssertionError("non-finite STOP bias was accepted")


def test_dense_prefix_sampling_covers_all_small_and_late_large_states() -> None:
    assert _prefix_counts(5, state_count=16) == [0, 1, 2, 3, 4, 5]
    counts = _prefix_counts(20, state_count=12)
    assert len(counts) == 12
    assert counts[:3] == [0, 1, 2]
    assert counts[-3:] == [18, 19, 20]
    assert counts == sorted(set(counts))

    targets = torch.zeros(2, 24, dtype=torch.bool)
    targets[0, :5] = True
    targets[1, :20] = True
    selected, weights = _prefix_masks(
        targets,
        seed=19,
        state_count=12,
    )
    assert selected.shape == (2, 12, 24)
    assert weights[0].sum().item() == 6
    assert weights[1].sum().item() == 12
    assert torch.equal(selected[0, 5], targets[0])
    assert torch.equal(selected[1, -1], targets[1])


def test_remaining_road_ranking_adds_explicit_early_stop_penalty() -> None:
    class _FixedDecoder:
        def decode_next(
            self,
            *,
            encoded_outputs: dict[str, torch.Tensor],
            candidate_mask: torch.Tensor,
            road_relations: torch.Tensor,
            selected_masks: torch.Tensor,
            access_seed_masks: torch.Tensor | None = None,
        ) -> dict[str, torch.Tensor]:
            del encoded_outputs, road_relations
            return {
                "next_road_logits": torch.zeros(
                    *selected_masks.shape,
                    dtype=torch.float32,
                ).masked_fill(
                    ~candidate_mask.unsqueeze(1) | selected_masks,
                    torch.finfo(torch.float32).min,
                ),
                "stop_logits": torch.zeros(
                    selected_masks.shape[:2],
                    dtype=torch.float32,
                ),
            }

    batch = {
        "candidate_encoded": torch.zeros(1, 4, 2),
        "graph_context": torch.zeros(1, 3),
        "road_relations": torch.zeros(1, 4, 4, 1),
        "targets": torch.tensor([[True, True, True, False]]),
        "allowed": torch.tensor([[True, True, True, True]]),
        "access_seeds": torch.tensor([[True, False, False, False]]),
    }
    base = _expansion_loss_rows(
        _FixedDecoder(),
        batch,
        config=SetExpansionTrainingConfig(),
        seed=23,
    )
    ranked = _expansion_loss_rows(
        _FixedDecoder(),
        batch,
        config=SetExpansionTrainingConfig(
            remaining_vs_stop_weight=0.5,
            remaining_vs_stop_margin=0.5,
        ),
        seed=23,
    )
    assert ranked.item() > base.item()


def test_stop_ranking_ignores_truth_roads_not_valid_for_current_action() -> None:
    class _StructuredDecoder:
        def decode_next(
            self,
            *,
            encoded_outputs: dict[str, torch.Tensor],
            candidate_mask: torch.Tensor,
            road_relations: torch.Tensor,
            selected_masks: torch.Tensor,
            access_seed_masks: torch.Tensor | None = None,
        ) -> dict[str, torch.Tensor]:
            del encoded_outputs, road_relations
            logits = torch.zeros_like(selected_masks, dtype=torch.float32)
            initial = ~selected_masks.any(dim=-1, keepdim=True)
            seeds = access_seed_masks.unsqueeze(1)
            valid = torch.where(
                initial & seeds.any(dim=-1, keepdim=True),
                seeds,
                candidate_mask.unsqueeze(1) & ~selected_masks,
            )
            return {
                "next_road_logits": logits.masked_fill(
                    ~valid,
                    torch.finfo(torch.float32).min,
                ),
                "stop_logits": torch.zeros(
                    selected_masks.shape[:2],
                    dtype=torch.float32,
                ),
            }

    batch = {
        "candidate_encoded": torch.zeros(1, 4, 2),
        "graph_context": torch.zeros(1, 3),
        "road_relations": torch.zeros(1, 4, 4, 1),
        "targets": torch.tensor([[True, True, True, False]]),
        "allowed": torch.tensor([[True, True, True, True]]),
        "access_seeds": torch.tensor([[True, False, False, False]]),
    }
    loss = _expansion_loss_rows(
        _StructuredDecoder(),
        batch,
        config=SetExpansionTrainingConfig(
            frontier_teacher_forcing=True,
            remaining_vs_stop_weight=0.5,
            remaining_vs_stop_margin=0.5,
        ),
        seed=29,
    )
    assert torch.isfinite(loss).all()


def test_frontier_teacher_forcing_expands_component_before_new_seed() -> None:
    targets = torch.tensor([[True, True, True, True, False]])
    seeds = torch.tensor([[True, False, False, True, False]])
    relations = torch.zeros(1, 5, 5, 1)
    relations[0, 0, 1, 0] = 1.0
    relations[0, 1, 0, 0] = 1.0
    relations[0, 1, 2, 0] = 1.0
    relations[0, 2, 1, 0] = 1.0
    selected, weights = _frontier_prefix_masks(
        targets,
        seeds,
        relations,
        seed=31,
        state_count=8,
    )
    assert weights.sum().item() == 5
    assert torch.equal(selected[0, 4], targets[0])
    first = selected[0, 1].nonzero().flatten().tolist()
    assert first[0] in {0, 3}

    selected_states = torch.tensor(
        [
            [
                [True, False, False, False, False],
                [True, True, True, False, False],
                [True, True, True, True, False],
            ]
        ]
    )
    acceptable = _frontier_acceptable_masks(
        targets,
        selected_states,
        seeds,
        relations,
    )
    assert acceptable[0, 0].tolist() == [
        False,
        True,
        False,
        False,
        False,
    ]
    assert acceptable[0, 1].tolist() == [
        False,
        False,
        False,
        True,
        False,
    ]
    assert not bool(acceptable[0, 2].any())
