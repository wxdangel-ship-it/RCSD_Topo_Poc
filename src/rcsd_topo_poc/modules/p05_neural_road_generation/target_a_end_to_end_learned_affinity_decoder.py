from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import torch
from torch import nn
from torch.nn import functional as F

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_end_to_end_pair_graph_decoder import (
    TargetAPairGraphSetDecoder,
    TargetAPairGraphSetDecoderConfig,
    compute_pair_graph_set_loss,
)


@dataclass(frozen=True)
class TargetALearnedAffinityGraphSetConfig:
    signal_dim: int = 115
    relation_dim: int = 13
    embedding_dim: int = 64
    pair_signal_dim: int = 8
    pair_hidden_dim: int = 96
    decoder_hidden_dim: int = 96
    decoder_layer_count: int = 3
    maximum_cardinality: int = 66
    dropout: float = 0.10

    def validate(self) -> None:
        if min(
            self.signal_dim,
            self.relation_dim,
            self.embedding_dim,
            self.pair_signal_dim,
            self.pair_hidden_dim,
            self.decoder_hidden_dim,
            self.decoder_layer_count,
            self.maximum_cardinality,
        ) < 1:
            raise ValueError("learned affinity decoder config differs")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("learned affinity decoder dropout differs")


class TargetALearnedAffinityGraphSetDecoder(nn.Module):
    """Learn Road-pair carrier affinity before complete-set decoding."""

    def __init__(
        self,
        config: TargetALearnedAffinityGraphSetConfig = (
            TargetALearnedAffinityGraphSetConfig()
        ),
    ) -> None:
        super().__init__()
        config.validate()
        self.config = config
        self.candidate_stem = nn.Sequential(
            nn.Linear(config.signal_dim + 4, config.embedding_dim),
            nn.GELU(),
            nn.LayerNorm(config.embedding_dim),
        )
        self.pair_signal_stem = nn.Sequential(
            nn.Linear(config.signal_dim, config.pair_signal_dim),
            nn.GELU(),
            nn.LayerNorm(config.pair_signal_dim),
        )
        pair_input_dim = (
            config.embedding_dim * 2
            + config.pair_signal_dim * 2
            + config.relation_dim
        )
        self.affinity_head = nn.Sequential(
            nn.Linear(pair_input_dim, config.pair_hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.pair_hidden_dim),
            nn.Dropout(config.dropout),
            nn.Linear(config.pair_hidden_dim, config.pair_hidden_dim // 2),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.pair_hidden_dim // 2, 1),
        )
        self.decoder = TargetAPairGraphSetDecoder(
            TargetAPairGraphSetDecoderConfig(
                signal_dim=config.embedding_dim,
                relation_dim=config.relation_dim,
                hidden_dim=config.decoder_hidden_dim,
                layer_count=config.decoder_layer_count,
                maximum_cardinality=config.maximum_cardinality,
                dropout=config.dropout,
            )
        )

    def forward(
        self,
        *,
        candidate_signals: torch.Tensor,
        road_relations: torch.Tensor,
        candidate_sources: torch.Tensor,
        candidate_mask: torch.Tensor,
        effective_decision: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        if candidate_signals.ndim != 3:
            raise ValueError("learned affinity candidate signal rank differs")
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
            or candidate_sources.shape != (batch_size, candidate_count)
            or candidate_mask.shape != (batch_size, candidate_count)
            or effective_decision.shape != (batch_size,)
        ):
            raise ValueError("learned affinity decoder input shape differs")
        allowed = (
            candidate_mask
            & effective_decision.unsqueeze(1).lt(2)
            & candidate_sources.eq(effective_decision.unsqueeze(1))
        )
        source_one_hot = F.one_hot(
            candidate_sources.clamp(min=0, max=1), num_classes=2
        ).to(candidate_signals.dtype)
        decision_one_hot = F.one_hot(
            effective_decision.clamp(min=0, max=1), num_classes=2
        ).to(candidate_signals.dtype)
        decision_values = decision_one_hot.unsqueeze(1).expand(
            -1, candidate_count, -1
        )
        embeddings = self.candidate_stem(
            torch.cat(
                (candidate_signals, source_one_hot, decision_values), dim=-1
            )
        )
        pair_signals = self.pair_signal_stem(candidate_signals)
        left_embedding = embeddings.unsqueeze(2)
        right_embedding = embeddings.unsqueeze(1)
        left_signal = pair_signals.unsqueeze(2)
        right_signal = pair_signals.unsqueeze(1)
        pair_features = torch.cat(
            (
                (left_embedding - right_embedding).abs().expand(
                    -1, -1, candidate_count, -1
                ),
                (left_embedding * right_embedding).expand(
                    -1, -1, candidate_count, -1
                ),
                ((left_signal + right_signal) / 2.0).expand(
                    -1, -1, candidate_count, -1
                ),
                (left_signal - right_signal).abs().expand(
                    -1, -1, candidate_count, -1
                ),
                road_relations,
            ),
            dim=-1,
        )
        affinity_logits = self.affinity_head(pair_features).squeeze(-1)
        affinity_logits = 0.5 * (
            affinity_logits + affinity_logits.transpose(1, 2)
        )
        pair_valid = allowed.unsqueeze(1) & allowed.unsqueeze(2)
        affinity_logits = affinity_logits.masked_fill(~pair_valid, -20.0)
        outputs = self.decoder(
            candidate_signals=embeddings,
            road_relations=road_relations,
            pair_affinity=torch.sigmoid(affinity_logits),
            candidate_sources=candidate_sources,
            candidate_mask=candidate_mask,
            effective_decision=effective_decision,
        )
        return {
            **outputs,
            "affinity_logits": affinity_logits,
            "affinity_pair_valid": pair_valid,
            "candidate_embeddings": embeddings,
        }


def compute_learned_affinity_graph_set_loss(
    outputs: Mapping[str, torch.Tensor],
    *,
    member_targets: torch.Tensor,
    task_mask: torch.Tensor,
    sample_weights: torch.Tensor,
    pair_loss_weight: float = 0.5,
    pair_dice_weight: float = 0.25,
    boundary_ranking_loss_weight: float = 0.0,
    boundary_ranking_margin: float = 0.5,
    positive_weight_cap: float = 20.0,
) -> dict[str, torch.Tensor]:
    if min(
        pair_loss_weight,
        pair_dice_weight,
        boundary_ranking_loss_weight,
        boundary_ranking_margin,
    ) < 0.0:
        raise ValueError("learned affinity loss weight differs")
    base = compute_pair_graph_set_loss(
        outputs,
        member_targets=member_targets,
        task_mask=task_mask,
        sample_weights=sample_weights,
        positive_weight_cap=positive_weight_cap,
    )
    pair_valid = outputs["affinity_pair_valid"]
    candidate_count = pair_valid.shape[-1]
    upper = torch.triu(
        torch.ones(
            (candidate_count, candidate_count),
            dtype=torch.bool,
            device=pair_valid.device,
        ),
        diagonal=1,
    )
    pair_task = (
        base["effective_task_mask"] & member_targets.sum(dim=-1).ge(2)
    )
    active = pair_valid & upper.unsqueeze(0) & pair_task[:, None, None]
    pair_targets = (
        member_targets.unsqueeze(1)
        & member_targets.unsqueeze(2)
        & active
    )
    positive = pair_targets.sum().to(outputs["affinity_logits"].dtype)
    negative = (active & ~pair_targets).sum().to(
        outputs["affinity_logits"].dtype
    )
    positive_weight = torch.clamp(
        negative / positive.clamp_min(1.0),
        min=1.0,
        max=positive_weight_cap,
    )
    raw = F.binary_cross_entropy_with_logits(
        outputs["affinity_logits"],
        pair_targets.to(outputs["affinity_logits"].dtype),
        reduction="none",
        pos_weight=positive_weight,
    )
    per_row_pair = (raw * active).sum(dim=(1, 2)) / active.sum(
        dim=(1, 2)
    ).clamp_min(1)
    probabilities = torch.sigmoid(outputs["affinity_logits"]) * active
    target_values = pair_targets.to(probabilities.dtype)
    intersection = (probabilities * target_values).sum(dim=(1, 2))
    per_row_dice = 1.0 - (
        2.0 * intersection + 1.0
    ) / (
        probabilities.sum(dim=(1, 2))
        + target_values.sum(dim=(1, 2))
        + 1.0
    )
    weights = sample_weights * pair_task.to(sample_weights.dtype)
    weight_total = weights.sum().clamp_min(1e-9)
    pair_loss = (per_row_pair * weights).sum() / weight_total
    pair_dice = (per_row_dice * weights).sum() / weight_total
    member_logits = outputs["member_logits"]
    allowed = outputs["allowed_mask"]
    positive_members = member_targets & allowed
    negative_members = ~member_targets & allowed
    boundary_task = (
        base["effective_task_mask"]
        & positive_members.any(dim=-1)
        & negative_members.any(dim=-1)
    )
    weakest_positive = member_logits.masked_fill(
        ~positive_members,
        1e4,
    ).amin(dim=-1)
    strongest_negative = member_logits.masked_fill(
        ~negative_members,
        -1e4,
    ).amax(dim=-1)
    per_row_boundary = F.softplus(
        strongest_negative
        - weakest_positive
        + float(boundary_ranking_margin)
    )
    boundary_weights = sample_weights * boundary_task.to(
        sample_weights.dtype
    )
    boundary_ranking_loss = (
        per_row_boundary * boundary_weights
    ).sum() / boundary_weights.sum().clamp_min(1e-9)
    total = (
        base["loss"]
        + pair_loss_weight * pair_loss
        + pair_dice_weight * pair_dice
        + boundary_ranking_loss_weight * boundary_ranking_loss
    )
    return {
        **base,
        "loss": total,
        "set_loss": base["loss"],
        "pair_loss": pair_loss,
        "pair_dice_loss": pair_dice,
        "pair_task_mask": pair_task,
        "pair_targets": pair_targets,
        "boundary_ranking_loss": boundary_ranking_loss,
        "boundary_task_mask": boundary_task,
    }


__all__ = [
    "TargetALearnedAffinityGraphSetConfig",
    "TargetALearnedAffinityGraphSetDecoder",
    "compute_learned_affinity_graph_set_loss",
]
