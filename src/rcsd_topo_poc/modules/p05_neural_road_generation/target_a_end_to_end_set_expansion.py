from __future__ import annotations

import random
from typing import Mapping

import torch
from torch.nn import functional as F

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_data import (
    ORDINARY_SET_SOURCE_RCSD,
    ORDINARY_SET_SOURCE_SWSD,
    EndToEndOrdinarySetBatch,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_ordinary_set_network import (
    TargetAEndToEndOrdinarySetNetwork,
)


def compute_order_free_set_expansion_loss(
    model: TargetAEndToEndOrdinarySetNetwork,
    encoded_outputs: Mapping[str, torch.Tensor],
    batch: EndToEndOrdinarySetBatch,
    *,
    seed: int,
    state_count: int = 10,
    remaining_vs_stop_weight: float = 0.5,
    remaining_vs_stop_margin: float = 0.5,
    remaining_coverage_weight: float = 0.0,
    cardinality_weight_power: float = 0.0,
) -> tuple[torch.Tensor, dict[str, torch.Tensor]]:
    """Train arbitrary valid next-Road choices and an explicit STOP action."""
    if state_count < 4:
        raise ValueError("ordinary expansion needs at least four states")
    if min(
        remaining_vs_stop_weight,
        remaining_vs_stop_margin,
        remaining_coverage_weight,
        cardinality_weight_power,
    ) < 0.0:
        raise ValueError("ordinary expansion STOP-ranking config is invalid")
    target = batch.road_member_targets & batch.side_road_mask
    allowed = _source_allowed_mask(batch)
    task_mask = (
        batch.road_task_mask
        & target.any(dim=-1)
        & ~(target & ~allowed).any(dim=-1)
    )
    selected, state_weights = build_order_free_prefix_masks(
        target,
        task_mask=task_mask,
        state_count=state_count,
        seed=seed,
    )
    outputs = model.decode_ordinary_next(
        encoded_outputs,
        batch,
        selected,
        candidate_mask=allowed,
    )
    logits = torch.cat(
        (
            outputs["next_road_logits"],
            outputs["stop_logits"].unsqueeze(-1),
        ),
        dim=-1,
    )
    log_probabilities = torch.log_softmax(logits, dim=-1)
    remaining = target.unsqueeze(2) & ~selected
    acceptable_next = remaining
    acceptable = torch.zeros_like(logits, dtype=torch.bool)
    acceptable[..., :-1] = acceptable_next
    acceptable[..., -1] = ~remaining.any(dim=-1)
    selected_log_probability = torch.logsumexp(
        log_probabilities.masked_fill(
            ~acceptable,
            torch.finfo(log_probabilities.dtype).min,
        ),
        dim=-1,
    )
    state_losses = -selected_log_probability
    active_states = state_weights.gt(0.0)
    state_losses = torch.where(
        active_states,
        state_losses,
        torch.zeros_like(state_losses),
    )
    next_acceptable = acceptable_next
    next_count = next_acceptable.sum(dim=-1)
    stop_differences = (
        outputs["stop_logits"].unsqueeze(-1)
        - outputs["next_road_logits"]
        + float(remaining_vs_stop_margin)
    )
    stop_rank_rows = (
        F.softplus(stop_differences)
        * next_acceptable.to(stop_differences.dtype)
    ).sum(dim=-1) / next_count.clamp_min(1).to(
        stop_differences.dtype
    )
    stop_rank_rows = torch.where(
        next_count.gt(0) & active_states,
        stop_rank_rows,
        torch.zeros_like(stop_rank_rows),
    )
    remaining_count = remaining.sum(dim=-1)
    coverage_rows = -(
        log_probabilities[..., :-1].masked_fill(
            ~remaining,
            0.0,
        )
    ).sum(dim=-1) / remaining_count.clamp_min(1).to(
        log_probabilities.dtype
    )
    coverage_rows = torch.where(
        remaining_count.gt(0) & active_states,
        coverage_rows,
        torch.zeros_like(coverage_rows),
    )
    combined = (
        state_losses
        + float(remaining_vs_stop_weight) * stop_rank_rows
        + float(remaining_coverage_weight) * coverage_rows
    )
    per_side = (
        combined * state_weights
    ).sum(dim=-1) / state_weights.sum(dim=-1).clamp_min(1.0)
    cardinality_weights = target.sum(dim=-1).clamp_min(1).to(
        batch.sample_weights.dtype
    ).pow(float(cardinality_weight_power))
    weights = (
        batch.sample_weights
        * cardinality_weights
        * task_mask.to(batch.sample_weights.dtype)
    )
    total = (per_side * weights).sum() / weights.sum().clamp_min(1e-6)
    action_loss = (
        state_losses * state_weights
    ).sum() / state_weights.sum().clamp_min(1.0)
    stop_rank_loss = (
        stop_rank_rows * state_weights
    ).sum() / state_weights.sum().clamp_min(1.0)
    coverage_loss = (
        coverage_rows * state_weights
    ).sum() / state_weights.sum().clamp_min(1.0)
    return total, {
        "ordinary_expansion_action_loss": action_loss,
        "ordinary_expansion_coverage_loss": coverage_loss,
        "ordinary_expansion_stop_rank_loss": stop_rank_loss,
        "ordinary_expansion_task_count": task_mask.sum().to(
            total.dtype
        ),
    }


def build_order_free_prefix_masks(
    targets: torch.Tensor,
    *,
    task_mask: torch.Tensor,
    state_count: int,
    seed: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    if (
        targets.ndim != 3
        or task_mask.shape != targets.shape[:2]
        or state_count < 4
    ):
        raise ValueError("ordinary expansion prefix inputs differ")
    selected = torch.zeros(
        (*targets.shape[:2], state_count, targets.shape[-1]),
        dtype=torch.bool,
        device=targets.device,
    )
    state_weights = torch.zeros(
        (*targets.shape[:2], state_count),
        dtype=torch.float32,
        device=targets.device,
    )
    generator = random.Random(seed)
    for batch_index in range(targets.shape[0]):
        for side_index in range(targets.shape[1]):
            if not bool(task_mask[batch_index, side_index]):
                continue
            values = (
                targets[batch_index, side_index]
                .nonzero(as_tuple=False)
                .flatten()
                .tolist()
            )
            if not values:
                raise ValueError("ordinary expansion target is empty")
            generator.shuffle(values)
            counts = _prefix_counts(
                len(values),
                state_count=state_count,
            )
            for state_index, count in enumerate(counts):
                selected[
                    batch_index,
                    side_index,
                    state_index,
                    values[:count],
                ] = True
                state_weights[
                    batch_index,
                    side_index,
                    state_index,
                ] = 1.0
    return selected, state_weights


def _prefix_counts(
    cardinality: int,
    *,
    state_count: int,
) -> list[int]:
    if cardinality < 1 or state_count < 4:
        raise ValueError("ordinary expansion prefix count is invalid")
    if cardinality + 1 <= state_count:
        return list(range(cardinality + 1))
    required = {0, 1, 2, cardinality - 1, cardinality}
    for index in range(state_count):
        required.add(round(index * cardinality / (state_count - 1)))
    ordered = sorted(required)
    if len(ordered) <= state_count:
        return ordered
    fixed = {0, 1, 2, cardinality - 1, cardinality}
    optional = [value for value in ordered if value not in fixed]
    remaining = state_count - len(fixed)
    chosen = {
        optional[
            round(index * (len(optional) - 1) / max(remaining - 1, 1))
        ]
        for index in range(remaining)
    }
    if len(chosen) < remaining:
        for value in reversed(optional):
            chosen.add(value)
            if len(chosen) == remaining:
                break
    result = sorted(fixed | chosen)
    if len(result) != state_count:
        raise AssertionError("ordinary expansion prefix sampling differs")
    return result


def _source_allowed_mask(
    batch: EndToEndOrdinarySetBatch,
) -> torch.Tensor:
    decisions = batch.decision_targets.unsqueeze(-1)
    sources = batch.side_road_source_indices
    return batch.side_road_mask & (
        decisions.eq(ORDINARY_SET_SOURCE_SWSD)
        & sources.eq(ORDINARY_SET_SOURCE_SWSD)
        | decisions.eq(ORDINARY_SET_SOURCE_RCSD)
        & sources.eq(ORDINARY_SET_SOURCE_RCSD)
    )


__all__ = [
    "build_order_free_prefix_masks",
    "compute_order_free_set_expansion_loss",
]
