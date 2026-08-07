from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import torch
from torch import nn
from torch.nn import functional as F


@dataclass(frozen=True)
class TargetAPairGraphSetDecoderConfig:
    signal_dim: int = 3
    relation_dim: int = 13
    hidden_dim: int = 64
    layer_count: int = 2
    maximum_cardinality: int = 66
    dropout: float = 0.10

    def validate(self) -> None:
        if min(
            self.signal_dim,
            self.relation_dim,
            self.hidden_dim,
            self.layer_count,
            self.maximum_cardinality,
        ) < 1:
            raise ValueError("pair graph decoder config differs")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("pair graph decoder dropout differs")


class TargetAPairGraphSetDecoder(nn.Module):
    """Decode one complete source-gated Road set from unary and pair evidence."""

    def __init__(
        self,
        config: TargetAPairGraphSetDecoderConfig = (
            TargetAPairGraphSetDecoderConfig()
        ),
    ) -> None:
        super().__init__()
        config.validate()
        self.config = config
        node_input_dim = config.signal_dim + 4
        edge_input_dim = config.relation_dim + 1
        self.node_stem = nn.Sequential(
            nn.Linear(node_input_dim, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        self.edge_stem = nn.Sequential(
            nn.Linear(edge_input_dim, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        self.layers = nn.ModuleList(
            _PairGraphMessageLayer(
                hidden_dim=config.hidden_dim,
                dropout=config.dropout,
            )
            for _ in range(config.layer_count)
        )
        self.member_head = nn.Sequential(
            nn.Linear(config.hidden_dim, config.hidden_dim // 2),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim // 2, 1),
        )
        self.cardinality_head = nn.Sequential(
            nn.Linear(config.hidden_dim * 2, config.hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim, config.maximum_cardinality + 1),
        )

    def forward(
        self,
        *,
        candidate_signals: torch.Tensor,
        road_relations: torch.Tensor,
        pair_affinity: torch.Tensor,
        candidate_sources: torch.Tensor,
        candidate_mask: torch.Tensor,
        effective_decision: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        if candidate_signals.ndim != 3:
            raise ValueError("pair graph candidate signal rank differs")
        batch_size, candidate_count, signal_dim = candidate_signals.shape
        if (
            signal_dim != self.config.signal_dim
            or road_relations.shape
            != (
                batch_size,
                candidate_count,
                candidate_count,
                self.config.relation_dim,
            )
            or pair_affinity.shape
            != (batch_size, candidate_count, candidate_count)
            or candidate_sources.shape != (batch_size, candidate_count)
            or candidate_mask.shape != (batch_size, candidate_count)
            or effective_decision.shape != (batch_size,)
        ):
            raise ValueError("pair graph decoder input shape differs")
        if candidate_sources.dtype != torch.long:
            raise ValueError("pair graph candidate source dtype differs")
        source_one_hot = F.one_hot(
            candidate_sources.clamp(min=0, max=1),
            num_classes=2,
        ).to(candidate_signals.dtype)
        decision_one_hot = F.one_hot(
            effective_decision.clamp(min=0, max=1),
            num_classes=2,
        ).to(candidate_signals.dtype)
        decision_values = decision_one_hot.unsqueeze(1).expand(
            -1, candidate_count, -1
        )
        allowed = (
            candidate_mask
            & effective_decision.unsqueeze(1).lt(2)
            & candidate_sources.eq(effective_decision.unsqueeze(1))
        )
        hidden = self.node_stem(
            torch.cat(
                (candidate_signals, source_one_hot, decision_values),
                dim=-1,
            )
        )
        edge_hidden = self.edge_stem(
            torch.cat((road_relations, pair_affinity.unsqueeze(-1)), dim=-1)
        )
        for layer in self.layers:
            hidden = layer(hidden, edge_hidden=edge_hidden, allowed=allowed)
        member_logits = self.member_head(hidden).squeeze(-1)
        member_logits = member_logits.masked_fill(~allowed, -20.0)
        pooled_mean = _masked_mean(hidden, allowed)
        pooled_max = _masked_max(hidden, allowed)
        cardinality_logits = self.cardinality_head(
            torch.cat((pooled_mean, pooled_max), dim=-1)
        )
        return {
            "member_logits": member_logits,
            "cardinality_logits": cardinality_logits,
            "allowed_mask": allowed,
            "candidate_encoded": hidden,
        }


class _PairGraphMessageLayer(nn.Module):
    def __init__(self, *, hidden_dim: int, dropout: float) -> None:
        super().__init__()
        self.query = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.key = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.value = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.edge_score = nn.Linear(hidden_dim, 1, bias=False)
        self.message_output = nn.Linear(hidden_dim, hidden_dim)
        self.message_norm = nn.LayerNorm(hidden_dim)
        self.feed_forward = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim * 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim * 2, hidden_dim),
        )
        self.feed_forward_norm = nn.LayerNorm(hidden_dim)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        hidden: torch.Tensor,
        *,
        edge_hidden: torch.Tensor,
        allowed: torch.Tensor,
    ) -> torch.Tensor:
        scale = math.sqrt(hidden.shape[-1])
        logits = (
            self.query(hidden).unsqueeze(2)
            * self.key(hidden).unsqueeze(1)
        ).sum(dim=-1) / scale
        logits = logits + self.edge_score(edge_hidden).squeeze(-1)
        pair_mask = allowed.unsqueeze(1) & allowed.unsqueeze(2)
        logits = logits.masked_fill(~pair_mask, -1e4)
        weights = torch.softmax(logits, dim=-1)
        weights = weights * pair_mask.to(weights.dtype)
        weights = weights / weights.sum(dim=-1, keepdim=True).clamp_min(1e-9)
        message = weights.matmul(self.value(hidden))
        hidden = self.message_norm(
            hidden + self.dropout(self.message_output(message))
        )
        hidden = self.feed_forward_norm(
            hidden + self.dropout(self.feed_forward(hidden))
        )
        return hidden


def compute_pair_graph_set_loss(
    outputs: Mapping[str, torch.Tensor],
    *,
    member_targets: torch.Tensor,
    task_mask: torch.Tensor,
    sample_weights: torch.Tensor,
    member_loss_weight: float = 1.0,
    dice_loss_weight: float = 0.5,
    cardinality_loss_weight: float = 0.5,
    positive_weight_cap: float = 20.0,
) -> dict[str, torch.Tensor]:
    member_logits = outputs["member_logits"]
    cardinality_logits = outputs["cardinality_logits"]
    allowed = outputs["allowed_mask"]
    if (
        member_targets.shape != member_logits.shape
        or member_targets.dtype != torch.bool
        or task_mask.shape != member_logits.shape[:1]
        or sample_weights.shape != member_logits.shape[:1]
        or cardinality_logits.shape[0] != member_logits.shape[0]
        or min(
            member_loss_weight,
            dice_loss_weight,
            cardinality_loss_weight,
            positive_weight_cap,
        )
        < 0.0
    ):
        raise ValueError("pair graph set loss input differs")
    target_outside_source_gate = (member_targets & ~allowed).any(dim=-1)
    effective_task = task_mask & ~target_outside_source_gate & allowed.any(
        dim=-1
    )
    active = allowed & effective_task.unsqueeze(-1)
    positive_count = (member_targets & active).sum().to(member_logits.dtype)
    negative_count = ((~member_targets) & active).sum().to(
        member_logits.dtype
    )
    positive_weight = torch.clamp(
        negative_count / positive_count.clamp_min(1.0),
        min=1.0,
        max=positive_weight_cap,
    )
    raw_member = F.binary_cross_entropy_with_logits(
        member_logits,
        member_targets.to(member_logits.dtype),
        reduction="none",
        pos_weight=positive_weight,
    )
    per_row_member = (raw_member * active).sum(dim=-1) / active.sum(
        dim=-1
    ).clamp_min(1)
    probabilities = torch.sigmoid(member_logits) * allowed.to(
        member_logits.dtype
    )
    targets = member_targets.to(member_logits.dtype)
    intersection = (probabilities * targets).sum(dim=-1)
    per_row_dice = 1.0 - (
        2.0 * intersection + 1.0
    ) / (probabilities.sum(dim=-1) + targets.sum(dim=-1) + 1.0)
    cardinality_targets = member_targets.sum(dim=-1).clamp(
        max=cardinality_logits.shape[-1] - 1
    )
    per_row_cardinality = F.cross_entropy(
        cardinality_logits,
        cardinality_targets,
        reduction="none",
    )
    weights = sample_weights * effective_task.to(sample_weights.dtype)
    weight_total = weights.sum().clamp_min(1e-9)
    member_loss = (per_row_member * weights).sum() / weight_total
    dice_loss = (per_row_dice * weights).sum() / weight_total
    cardinality_loss = (
        per_row_cardinality * weights
    ).sum() / weight_total
    total = (
        member_loss_weight * member_loss
        + dice_loss_weight * dice_loss
        + cardinality_loss_weight * cardinality_loss
    )
    return {
        "loss": total,
        "member_loss": member_loss,
        "dice_loss": dice_loss,
        "cardinality_loss": cardinality_loss,
        "effective_task_mask": effective_task,
        "target_outside_source_gate": target_outside_source_gate,
    }


def decode_pair_graph_set_proposals(
    outputs: Mapping[str, torch.Tensor],
    *,
    cardinality_width: int = 8,
    probability_thresholds: Sequence[float] = (
        0.20,
        0.30,
        0.40,
        0.50,
        0.60,
        0.70,
        0.80,
    ),
) -> list[list[dict[str, Any]]]:
    member_logits = outputs["member_logits"].detach().cpu()
    cardinality_logits = outputs["cardinality_logits"].detach().cpu()
    allowed = outputs["allowed_mask"].detach().cpu()
    if min(cardinality_width, *probability_thresholds) <= 0.0 or any(
        value >= 1.0 for value in probability_thresholds
    ):
        raise ValueError("pair graph proposal decode config differs")
    result = []
    for row_index in range(member_logits.shape[0]):
        allowed_indices = allowed[row_index].nonzero(
            as_tuple=False
        ).flatten().tolist()
        if not allowed_indices:
            result.append([])
            continue
        scores = member_logits[row_index]
        ranked = sorted(
            allowed_indices,
            key=lambda index: (-float(scores[index].item()), index),
        )
        maximum = min(
            len(ranked), cardinality_logits.shape[-1] - 1
        )
        valid_cardinality_logits = cardinality_logits[
            row_index, 1 : maximum + 1
        ]
        width = min(cardinality_width, maximum)
        cardinalities = set(
            torch.topk(valid_cardinality_logits, width)
            .indices.add(1)
            .tolist()
        )
        probabilities = torch.sigmoid(scores)
        cardinalities.update(
            sum(float(probabilities[index].item()) >= threshold for index in ranked)
            for threshold in probability_thresholds
        )
        proposals: dict[tuple[int, ...], float] = {}
        card_log_probabilities = torch.log_softmax(
            cardinality_logits[row_index], dim=-1
        )
        for cardinality in sorted(cardinalities):
            if not 1 <= cardinality <= maximum:
                continue
            selected = tuple(sorted(ranked[:cardinality]))
            score = float(
                F.logsigmoid(scores[list(selected)]).mean().item()
                + 0.25 * card_log_probabilities[cardinality].item()
            )
            proposals[selected] = max(score, proposals.get(selected, -math.inf))
        result.append(
            [
                {
                    "selected_indices": list(selected),
                    "score": score,
                }
                for selected, score in sorted(
                    proposals.items(),
                    key=lambda value: (-value[1], value[0]),
                )
            ]
        )
    return result


def _masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return (values * mask.unsqueeze(-1)).sum(dim=1) / mask.sum(
        dim=1, keepdim=True
    ).clamp_min(1)


def _masked_max(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    masked = values.masked_fill(~mask.unsqueeze(-1), -1e4)
    maximum = masked.amax(dim=1)
    return torch.where(mask.any(dim=1, keepdim=True), maximum, 0.0)


__all__ = [
    "TargetAPairGraphSetDecoder",
    "TargetAPairGraphSetDecoderConfig",
    "compute_pair_graph_set_loss",
    "decode_pair_graph_set_proposals",
]
