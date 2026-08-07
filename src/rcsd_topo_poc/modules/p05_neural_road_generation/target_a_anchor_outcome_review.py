from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_dataset import (
    ANCHOR_STATUS_INDEX,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    AnchorStatus,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetABatchTensors,
)


ANCHOR_OUTCOME_SUCCESS = 0
ANCHOR_OUTCOME_NO_EVIDENCE = 1
ANCHOR_OUTCOME_FALLBACK = 2
ANCHOR_OUTCOME_COUNT = 3


@dataclass(frozen=True)
class AnchorOutcomeReviewConfig:
    hidden_dim: int
    head_hidden_dim: int = 128
    dropout: float = 0.10
    positive_release_threshold: float = 0.50
    fallback_threshold: float = 0.50
    stop_gradient_at_anchor_evidence: bool = True

    def validate(self) -> None:
        if min(self.hidden_dim, self.head_hidden_dim) < 1:
            raise ValueError("anchor outcome dimensions are invalid")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("anchor outcome dropout is invalid")
        for value in (
            self.positive_release_threshold,
            self.fallback_threshold,
        ):
            if not 0.0 < value < 1.0:
                raise ValueError("anchor outcome threshold is invalid")


class AnchorOutcomeReviewHead(nn.Module):
    """Verify anchor business outcomes before any ordinary carrier decision."""

    _RUNTIME_EVIDENCE_DIM = 16

    def __init__(self, config: AnchorOutcomeReviewConfig) -> None:
        super().__init__()
        config.validate()
        self.config = config
        input_dim = config.hidden_dim + self._RUNTIME_EVIDENCE_DIM
        self.head = nn.Sequential(
            nn.LayerNorm(input_dim),
            nn.Linear(input_dim, config.head_hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.head_hidden_dim, config.head_hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.head_hidden_dim),
            nn.Linear(config.head_hidden_dim, ANCHOR_OUTCOME_COUNT),
        )

    def forward(
        self,
        outputs: Mapping[str, torch.Tensor],
        batch: TargetABatchTensors,
    ) -> dict[str, torch.Tensor]:
        features = anchor_outcome_runtime_features(outputs, batch)
        if self.config.stop_gradient_at_anchor_evidence:
            features = features.detach()
        logits = self.head(features)
        decoded = decode_anchor_outcome_review(
            logits,
            status_logits=outputs["anchor_status_logits"],
            selection_success=outputs["anchor_selection_success"],
            gate_logits=outputs.get("anchor_gate_logits"),
            positive_release_threshold=(
                self.config.positive_release_threshold
            ),
            fallback_threshold=self.config.fallback_threshold,
        )
        return {
            "anchor_outcome_logits": logits,
            **decoded,
            "_anchor_outcome_runtime_features": features,
        }


def anchor_outcome_runtime_features(
    outputs: Mapping[str, torch.Tensor],
    batch: TargetABatchTensors,
) -> torch.Tensor:
    locked = outputs["locked_anchor_embeddings"]
    status_logits = outputs["anchor_status_logits"]
    candidate_logits = outputs["anchor_candidate_logits"]
    if (
        locked.ndim != 3
        or status_logits.shape[:2] != locked.shape[:2]
        or candidate_logits.shape[:2] != locked.shape[:2]
        or batch.anchor_candidate_mask.shape != candidate_logits.shape
    ):
        raise ValueError("anchor outcome evidence shapes differ")
    status_probabilities = torch.softmax(status_logits, dim=-1)
    candidate_statistics = _distribution_statistics(
        candidate_logits,
        batch.anchor_candidate_mask,
    )
    gate_logits = outputs.get("anchor_gate_logits")
    if gate_logits is None:
        gate_probability = torch.full(
            (*locked.shape[:2], 1),
            0.5,
            dtype=locked.dtype,
            device=locked.device,
        )
    else:
        if gate_logits.shape != (*locked.shape[:2], 2):
            raise ValueError("anchor outcome gate shape differs")
        gate_probability = torch.softmax(gate_logits, dim=-1)[
            ..., 1:2
        ]
    selection_success = outputs["anchor_selection_success"]
    if selection_success.shape != locked.shape[:2]:
        raise ValueError("anchor outcome selection shape differs")
    type_statistics = _optional_distribution_statistics(
        outputs.get("anchor_type_logits"),
        locked,
    )
    cardinality_statistics = _optional_distribution_statistics(
        outputs.get("anchor_cardinality_logits"),
        locked,
    )
    features = torch.cat(
        (
            locked,
            status_probabilities,
            candidate_statistics,
            gate_probability,
            selection_success.unsqueeze(-1).to(locked.dtype),
            type_statistics,
            cardinality_statistics,
        ),
        dim=-1,
    )
    expected = locked.shape[-1] + AnchorOutcomeReviewHead._RUNTIME_EVIDENCE_DIM
    if features.shape != (*locked.shape[:2], expected):
        raise ValueError("anchor outcome feature dimension differs")
    return torch.where(
        torch.isfinite(features),
        features,
        torch.zeros_like(features),
    )


def decode_anchor_outcome_review(
    logits: torch.Tensor,
    *,
    status_logits: torch.Tensor,
    selection_success: torch.Tensor,
    gate_logits: torch.Tensor | None,
    positive_release_threshold: float,
    fallback_threshold: float,
) -> dict[str, torch.Tensor]:
    if (
        logits.ndim != 3
        or logits.shape[-1] != ANCHOR_OUTCOME_COUNT
        or status_logits.shape[:2] != logits.shape[:2]
        or selection_success.shape != logits.shape[:2]
    ):
        raise ValueError("anchor outcome decode shapes differ")
    if not 0.0 < positive_release_threshold < 1.0:
        raise ValueError("anchor outcome positive threshold is invalid")
    if not 0.0 < fallback_threshold < 1.0:
        raise ValueError("anchor outcome fallback threshold is invalid")

    probabilities = torch.softmax(logits, dim=-1)
    confidence, predicted = probabilities.max(dim=-1)
    status = status_logits.argmax(dim=-1)
    status_outcome = anchor_status_to_outcome(status)
    agreement = predicted.eq(status_outcome)
    if gate_logits is None:
        gate_pass = torch.ones_like(agreement)
    else:
        if gate_logits.shape != (*logits.shape[:2], 2):
            raise ValueError("anchor outcome gate shape differs")
        gate_pass = torch.softmax(gate_logits, dim=-1)[..., 1].ge(0.5)

    positive_release = (
        predicted.ne(ANCHOR_OUTCOME_FALLBACK)
        & agreement
        & confidence.ge(positive_release_threshold)
    )
    success_release = (
        positive_release
        & predicted.eq(ANCHOR_OUTCOME_SUCCESS)
        & selection_success
        & gate_pass
    )
    no_evidence_release = positive_release & predicted.eq(
        ANCHOR_OUTCOME_NO_EVIDENCE
    )
    explicit_fallback = (
        predicted.eq(ANCHOR_OUTCOME_FALLBACK)
        & agreement
        & confidence.ge(fallback_threshold)
    )
    review = ~(success_release | no_evidence_release | explicit_fallback)

    effective_status = torch.full_like(
        status,
        ANCHOR_STATUS_INDEX[AnchorStatus.ABSTAIN],
    )
    effective_status = effective_status.masked_fill(
        success_release,
        ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS],
    )
    effective_status = effective_status.masked_fill(
        no_evidence_release,
        ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE],
    )
    return {
        "anchor_outcome_probabilities": probabilities,
        "anchor_outcome_predictions": predicted,
        "anchor_outcome_confidence": confidence,
        "anchor_outcome_status_agreement": agreement,
        "anchor_outcome_positive_release": (
            success_release | no_evidence_release
        ),
        "anchor_outcome_explicit_fallback": explicit_fallback,
        "anchor_outcome_review": review,
        "anchor_outcome_effective_status": effective_status,
    }


def anchor_status_to_outcome(status: torch.Tensor) -> torch.Tensor:
    outcome = torch.full_like(status, ANCHOR_OUTCOME_FALLBACK)
    outcome = outcome.masked_fill(
        status.eq(ANCHOR_STATUS_INDEX[AnchorStatus.SUCCESS]),
        ANCHOR_OUTCOME_SUCCESS,
    )
    outcome = outcome.masked_fill(
        status.eq(ANCHOR_STATUS_INDEX[AnchorStatus.NO_EVIDENCE]),
        ANCHOR_OUTCOME_NO_EVIDENCE,
    )
    return outcome


def compute_anchor_outcome_review_loss(
    outputs: Mapping[str, torch.Tensor],
    *,
    anchor_status: torch.Tensor,
    anchor_status_mask: torch.Tensor,
    sample_weights: torch.Tensor | None = None,
    class_weights: torch.Tensor | None = None,
) -> torch.Tensor:
    logits = outputs["anchor_outcome_logits"]
    if (
        anchor_status.shape != logits.shape[:2]
        or anchor_status_mask.shape != logits.shape[:2]
        or anchor_status_mask.dtype is not torch.bool
    ):
        raise ValueError("anchor outcome target shapes differ")
    targets = anchor_status_to_outcome(anchor_status.clamp_min(0))
    losses = nn.functional.cross_entropy(
        logits.transpose(1, 2),
        targets,
        weight=class_weights,
        reduction="none",
    )
    weights = _expanded_weights(losses, sample_weights)
    active = anchor_status_mask.to(losses.dtype) * weights
    denominator = active.sum()
    if not bool(denominator.gt(0.0)):
        return logits.sum() * 0.0
    return (losses * active).sum() / denominator


def _distribution_statistics(
    logits: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    if logits.shape != mask.shape or mask.dtype is not torch.bool:
        raise ValueError("anchor outcome distribution mask differs")
    minimum = torch.finfo(logits.dtype).min
    safe_logits = logits.masked_fill(~mask, minimum)
    probabilities = torch.softmax(safe_logits, dim=-1)
    probabilities = torch.where(
        mask,
        probabilities,
        torch.zeros_like(probabilities),
    )
    count = mask.sum(dim=-1)
    top_count = min(2, probabilities.shape[-1])
    top = torch.topk(probabilities, k=top_count, dim=-1).values
    top_one = top[..., 0]
    top_two = top[..., 1] if top_count == 2 else torch.zeros_like(top_one)
    entropy = -(
        probabilities
        * probabilities.clamp_min(torch.finfo(probabilities.dtype).tiny).log()
    ).sum(dim=-1)
    normalizer = count.clamp_min(2).to(logits.dtype).log()
    entropy = torch.where(
        count.gt(1),
        entropy / normalizer,
        torch.zeros_like(entropy),
    )
    log_count = torch.log1p(count.to(logits.dtype))
    return torch.stack(
        (top_one, top_two, top_one - top_two, entropy, log_count),
        dim=-1,
    )


def _optional_distribution_statistics(
    logits: torch.Tensor | None,
    reference: torch.Tensor,
) -> torch.Tensor:
    if logits is None:
        return torch.zeros(
            (*reference.shape[:2], 2),
            dtype=reference.dtype,
            device=reference.device,
        )
    if logits.ndim < 3 or logits.shape[:2] != reference.shape[:2]:
        raise ValueError("anchor outcome optional distribution differs")
    logits = logits.reshape(*logits.shape[:2], -1)
    mask = torch.isfinite(logits)
    statistics = _distribution_statistics(logits, mask)
    return statistics[..., (0, 2)]


def _expanded_weights(
    losses: torch.Tensor,
    sample_weights: torch.Tensor | None,
) -> torch.Tensor:
    if sample_weights is None:
        return torch.ones_like(losses)
    if sample_weights.shape == losses.shape:
        return sample_weights.to(losses.dtype)
    if sample_weights.ndim == 1 and sample_weights.shape[0] == losses.shape[0]:
        return sample_weights.unsqueeze(-1).expand_as(losses).to(losses.dtype)
    raise ValueError("anchor outcome sample weights differ")


__all__ = [
    "ANCHOR_OUTCOME_COUNT",
    "ANCHOR_OUTCOME_FALLBACK",
    "ANCHOR_OUTCOME_NO_EVIDENCE",
    "ANCHOR_OUTCOME_SUCCESS",
    "AnchorOutcomeReviewConfig",
    "AnchorOutcomeReviewHead",
    "anchor_outcome_runtime_features",
    "anchor_status_to_outcome",
    "compute_anchor_outcome_review_loss",
    "decode_anchor_outcome_review",
]
