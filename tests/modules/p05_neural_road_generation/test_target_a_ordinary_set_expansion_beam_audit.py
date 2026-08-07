from __future__ import annotations

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_ordinary_set_expansion_beam_audit import (
    beam_decode_complete_sets,
)


class _FixedBeamDecoder:
    def decode_next(
        self,
        *,
        encoded_outputs: dict[str, torch.Tensor],
        candidate_mask: torch.Tensor,
        road_relations: torch.Tensor,
        selected_masks: torch.Tensor,
        access_seed_masks: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        del encoded_outputs, road_relations, access_seed_masks
        logits = torch.full(
            selected_masks.shape,
            -30.0,
            dtype=torch.float32,
        )
        stop = torch.full(
            selected_masks.shape[:2],
            -30.0,
            dtype=torch.float32,
        )
        for state in range(selected_masks.shape[1]):
            selected = selected_masks[0, state]
            if not bool(selected.any()):
                logits[0, state, 0] = 2.0
                logits[0, state, 1] = 1.0
            elif bool(selected[0]) and not bool(selected[1]):
                stop[0, state] = 2.0
                logits[0, state, 1] = 1.5
            else:
                stop[0, state] = 2.0
        logits = logits.masked_fill(
            ~candidate_mask.unsqueeze(1) | selected_masks,
            torch.finfo(torch.float32).min,
        )
        return {
            "next_road_logits": logits,
            "stop_logits": stop,
        }


def test_beam_decoder_returns_multiple_complete_truth_free_sets() -> None:
    proposals = beam_decode_complete_sets(
        _FixedBeamDecoder(),
        encoded_outputs={
            "candidate_encoded": torch.zeros(1, 2, 3),
            "graph_context": torch.zeros(1, 3),
        },
        candidate_mask=torch.ones(1, 2, dtype=torch.bool),
        road_relations=torch.zeros(1, 2, 2, 1),
        access_seed_masks=torch.zeros(1, 2, dtype=torch.bool),
        beam_width=4,
    )
    selected = {
        tuple(value["selected_indices"]) for value in proposals
    }
    assert (0,) in selected
    assert (0, 1) in selected
    assert proposals == sorted(
        proposals,
        key=lambda value: -value["log_probability"],
    )
