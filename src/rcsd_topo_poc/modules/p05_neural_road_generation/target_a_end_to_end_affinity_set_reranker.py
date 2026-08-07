from __future__ import annotations

from typing import Mapping, Sequence

import torch
from torch.nn import functional as F

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_set_reranker import (
    END_TO_END_SET_RERANKER_FEATURE_DIM,
)


AFFINITY_SET_FEATURE_DIM = END_TO_END_SET_RERANKER_FEATURE_DIM + 10


def build_affinity_set_proposal_features(
    proposals: Sequence[Mapping[str, object]],
    *,
    scalar_features: torch.Tensor,
    affinity_logits: torch.Tensor,
    allowed_mask: torch.Tensor,
) -> torch.Tensor:
    """Append truth-free learned Road-pair coherence to set features."""
    proposal_count = len(proposals)
    road_count = int(affinity_logits.shape[0])
    if (
        scalar_features.shape
        != (proposal_count, END_TO_END_SET_RERANKER_FEATURE_DIM)
        or affinity_logits.ndim != 2
        or affinity_logits.shape != (road_count, road_count)
        or allowed_mask.shape != (road_count,)
    ):
        raise ValueError("affinity set proposal feature inputs differ")
    if proposal_count == 0:
        return affinity_logits.new_zeros((0, AFFINITY_SET_FEATURE_DIM))
    allowed = allowed_mask.bool()
    selected = torch.zeros(
        proposal_count,
        road_count,
        dtype=torch.bool,
        device=affinity_logits.device,
    )
    for proposal_index, proposal in enumerate(proposals):
        for raw_index in proposal["selected_indices"]:  # type: ignore[index]
            index = int(raw_index)
            if 0 <= index < road_count and bool(allowed[index]):
                selected[proposal_index, index] = True
    excluded = allowed.unsqueeze(0) & ~selected
    upper = torch.triu(
        torch.ones(
            road_count,
            road_count,
            dtype=torch.bool,
            device=affinity_logits.device,
        ),
        diagonal=1,
    )
    internal = (
        selected.unsqueeze(2)
        & selected.unsqueeze(1)
        & upper.unsqueeze(0)
    )
    internal_full = (
        selected.unsqueeze(2)
        & selected.unsqueeze(1)
        & ~torch.eye(
            road_count,
            dtype=torch.bool,
            device=affinity_logits.device,
        ).unsqueeze(0)
    )
    cross = selected.unsqueeze(2) & excluded.unsqueeze(1)
    probabilities = torch.sigmoid(affinity_logits).unsqueeze(0).expand(
        proposal_count,
        -1,
        -1,
    )
    positive_log_probability = F.logsigmoid(
        affinity_logits
    ).unsqueeze(0).expand_as(probabilities)
    negative_log_probability = F.logsigmoid(
        -affinity_logits
    ).unsqueeze(0).expand_as(probabilities)
    internal_mean, internal_minimum, internal_maximum = _masked_statistics(
        probabilities,
        internal,
    )
    cross_mean, _, cross_maximum = _masked_statistics(
        probabilities,
        cross,
    )
    internal_positive = _masked_mean(
        positive_log_probability,
        internal,
    )
    cross_negative = _masked_mean(
        negative_log_probability,
        cross,
    )
    degree_counts = internal_full.sum(dim=2)
    degrees = (probabilities * internal_full).sum(dim=2) / degree_counts.clamp_min(
        1
    )
    degree_active = selected & degree_counts.gt(0)
    selected_degree_minimum = _masked_vector_minimum(
        degrees,
        degree_active,
    )
    affinity_features = torch.stack(
        (
            internal_mean,
            internal_minimum,
            internal_maximum,
            cross_mean,
            cross_maximum,
            internal_mean - cross_mean,
            internal_positive,
            cross_negative,
            0.5 * (internal_positive + cross_negative),
            selected_degree_minimum,
        ),
        dim=-1,
    )
    return torch.cat((scalar_features, affinity_features), dim=-1)


def _masked_statistics(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    return (
        _masked_mean(values, mask),
        _masked_minimum(values, mask),
        _masked_maximum(values, mask),
    )


def _masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return (values * mask).sum(dim=(1, 2)) / mask.sum(dim=(1, 2)).clamp_min(1)


def _masked_minimum(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    minimum = values.masked_fill(~mask, torch.finfo(values.dtype).max).amin(
        dim=-1
    )
    minimum = minimum.amin(dim=-1)
    return torch.where(mask.any(dim=(1, 2)), minimum, 0.0)


def _masked_maximum(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    maximum = values.masked_fill(~mask, torch.finfo(values.dtype).min).amax(
        dim=-1
    )
    maximum = maximum.amax(dim=-1)
    return torch.where(mask.any(dim=(1, 2)), maximum, 0.0)


def _masked_vector_minimum(
    values: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    minimum = values.masked_fill(~mask, torch.finfo(values.dtype).max).amin(
        dim=-1
    )
    return torch.where(mask.any(dim=-1), minimum, 0.0)


__all__ = [
    "AFFINITY_SET_FEATURE_DIM",
    "build_affinity_set_proposal_features",
]
