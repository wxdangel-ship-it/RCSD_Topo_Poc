from __future__ import annotations

import copy
import hashlib
import io
import math
import random
import time
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_models import (
    TargetAConfig,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    ANCHOR_TYPE_COUNT,
    TargetABatchTensors,
    TargetAJointNetwork,
    anchor_candidate_cardinality_masks,
    anchor_candidate_type_masks,
    ordinary_plan_decision_masks,
    parameter_count,
)


@dataclass(frozen=True)
class TargetATrainingTargets:
    sample_weights: torch.Tensor
    anchor_status: torch.Tensor
    anchor_status_mask: torch.Tensor
    anchor_acceptable: torch.Tensor
    anchor_preferred: torch.Tensor
    anchor_candidate_task_mask: torch.Tensor
    ordinary_acceptable: torch.Tensor
    ordinary_preferred: torch.Tensor
    ordinary_task_mask: torch.Tensor
    clue: torch.Tensor
    clue_task_mask: torch.Tensor
    fallback_scope: torch.Tensor
    fallback_scope_task_mask: torch.Tensor
    advance_right_acceptable: torch.Tensor
    advance_right_preferred: torch.Tensor
    advance_right_task_mask: torch.Tensor
    anchor_sample_weights: torch.Tensor | None = None
    anchor_gate: torch.Tensor | None = None
    anchor_gate_mask: torch.Tensor | None = None
    ordinary_sample_weights: torch.Tensor | None = None
    anchor_member_acceptable_sets: torch.Tensor | None = None
    anchor_member_acceptable_set_mask: torch.Tensor | None = None
    anchor_member_task_mask: torch.Tensor | None = None


@dataclass(frozen=True)
class TargetATrainingBatch:
    tensors: TargetABatchTensors
    targets: TargetATrainingTargets


@dataclass
class TargetAStageResult:
    model: TargetAJointNetwork
    best_epoch: int
    best_validation_loss: float
    history: list[dict[str, float]]
    wall_seconds: float
    state_signature: str


@dataclass
class TargetAFixedEpochResult:
    model: TargetAJointNetwork
    epoch_count: int
    history: list[dict[str, float]]
    wall_seconds: float
    state_signature: str


def acceptable_set_nll(
    logits: torch.Tensor,
    acceptable_mask: torch.Tensor,
    valid_mask: torch.Tensor,
) -> torch.Tensor:
    if logits.shape != acceptable_mask.shape or logits.shape != valid_mask.shape:
        raise ValueError("acceptable-set tensor shapes differ")
    if acceptable_mask.dtype is not torch.bool or valid_mask.dtype is not torch.bool:
        raise ValueError("acceptable-set masks must be bool")
    if bool((acceptable_mask & ~valid_mask).any()):
        raise ValueError("acceptable targets must be valid candidates")
    supervised = acceptable_mask.any(dim=-1) & valid_mask.any(dim=-1)
    if not bool(supervised.any()):
        return _finite_graph_zero(logits, reduce_last=True)
    minimum = torch.finfo(logits.dtype).min
    valid_logsumexp = torch.logsumexp(
        logits.masked_fill(~valid_mask, minimum),
        dim=-1,
    )
    effective_acceptable = acceptable_mask | (
        valid_mask & ~supervised.unsqueeze(-1)
    )
    acceptable_logsumexp = torch.logsumexp(
        logits.masked_fill(~effective_acceptable, minimum),
        dim=-1,
    )
    return valid_logsumexp - acceptable_logsumexp


def preferred_cross_entropy(
    logits: torch.Tensor,
    preferred: torch.Tensor,
    valid_mask: torch.Tensor,
) -> torch.Tensor:
    if preferred.shape != logits.shape[:-1]:
        raise ValueError("preferred target shape differs")
    supervised = preferred.ge(0) & valid_mask.any(dim=-1)
    if not bool(supervised.any()):
        return _finite_graph_zero(logits, reduce_last=True)
    safe_logits = logits.masked_fill(
        ~valid_mask,
        torch.finfo(logits.dtype).min,
    )
    losses = nn.functional.cross_entropy(
        safe_logits.reshape(-1, safe_logits.shape[-1]),
        preferred.clamp_min(0).reshape(-1),
        reduction="none",
    ).reshape(preferred.shape)
    return losses


def balanced_candidate_validity_bce(
    logits: torch.Tensor,
    acceptable_mask: torch.Tensor,
    valid_mask: torch.Tensor,
) -> torch.Tensor:
    if logits.shape != acceptable_mask.shape or logits.shape != valid_mask.shape:
        raise ValueError("candidate validity tensor shapes differ")
    if acceptable_mask.dtype is not torch.bool or valid_mask.dtype is not torch.bool:
        raise ValueError("candidate validity masks must be bool")
    if bool((acceptable_mask & ~valid_mask).any()):
        raise ValueError("candidate validity targets must be valid candidates")
    safe_logits = torch.where(valid_mask, logits, torch.zeros_like(logits))
    raw = nn.functional.binary_cross_entropy_with_logits(
        safe_logits,
        acceptable_mask.to(logits.dtype),
        reduction="none",
    )
    positive = acceptable_mask
    negative = valid_mask & ~acceptable_mask
    positive_mean = (raw * positive.to(raw.dtype)).sum(dim=-1) / positive.sum(
        dim=-1
    ).clamp_min(1)
    negative_mean = (raw * negative.to(raw.dtype)).sum(dim=-1) / negative.sum(
        dim=-1
    ).clamp_min(1)
    has_positive = positive.any(dim=-1)
    has_negative = negative.any(dim=-1)
    denominator = has_positive.to(raw.dtype) + has_negative.to(raw.dtype)
    return (
        positive_mean * has_positive.to(raw.dtype)
        + negative_mean * has_negative.to(raw.dtype)
    ) / denominator.clamp_min(1.0)


def anchor_member_supervision(
    acceptable_candidates: torch.Tensor,
    batch: TargetABatchTensors,
) -> tuple[torch.Tensor, torch.Tensor]:
    membership = batch.anchor_candidate_membership
    member_mask = batch.anchor_member_mask
    member_is_road = batch.anchor_member_is_road
    if membership is None or member_mask is None or member_is_road is None:
        raise ValueError("anchor member supervision lacks member tensors")
    if acceptable_candidates.shape != batch.anchor_candidate_mask.shape:
        raise ValueError("anchor acceptable candidate shape differs")
    if membership.shape != (
        *acceptable_candidates.shape,
        member_mask.shape[-1],
    ):
        raise ValueError("anchor candidate membership shape differs")
    acceptable_by_type = (
        acceptable_candidates.unsqueeze(-1)
        & anchor_candidate_type_masks(batch)
    )
    acceptable_type_counts = acceptable_by_type.sum(dim=2)
    acceptable_member_counts = (
        membership.unsqueeze(-1)
        & acceptable_by_type.unsqueeze(3)
    ).sum(dim=2)
    member_type_masks = torch.stack(
        (~member_is_road, member_is_road),
        dim=-1,
    ) & member_mask.unsqueeze(-1)
    relevant = member_type_masks & acceptable_type_counts.unsqueeze(2).gt(0)
    required = (
        relevant
        & acceptable_member_counts.eq(
            acceptable_type_counts.unsqueeze(2)
        )
    ).any(dim=-1)
    forbidden = (
        relevant
        & acceptable_member_counts.eq(0)
    ).any(dim=-1)
    return required, required | forbidden


def acceptable_member_set_nll(
    member_logits: torch.Tensor,
    member_mask: torch.Tensor,
    member_is_road: torch.Tensor,
    acceptable_sets: torch.Tensor,
    acceptable_set_mask: torch.Tensor,
) -> torch.Tensor:
    """Return a normalized multi-solution exact typed-set loss."""
    if (
        member_logits.shape != member_mask.shape
        or member_logits.shape != member_is_road.shape
    ):
        raise ValueError("anchor member logit/mask shapes differ")
    if acceptable_sets.shape != (
        *member_logits.shape[:-1],
        acceptable_sets.shape[-2],
        member_logits.shape[-1],
    ):
        raise ValueError("anchor acceptable member-set shape differs")
    if acceptable_set_mask.shape != acceptable_sets.shape[:-1]:
        raise ValueError("anchor acceptable member-set mask shape differs")
    if (
        member_mask.dtype is not torch.bool
        or member_is_road.dtype is not torch.bool
        or acceptable_sets.dtype is not torch.bool
        or acceptable_set_mask.dtype is not torch.bool
    ):
        raise ValueError("anchor member supervision masks must be bool")
    if bool(
        (
            acceptable_sets
            & ~member_mask.unsqueeze(-2)
            & acceptable_set_mask.unsqueeze(-1)
        ).any()
    ):
        raise ValueError("acceptable anchor member is outside the set")
    selected_road = (
        acceptable_sets & member_is_road.unsqueeze(-2)
    ).any(dim=-1)
    selected_node = (
        acceptable_sets & ~member_is_road.unsqueeze(-2)
    ).any(dim=-1)
    invalid = acceptable_set_mask & (
        selected_road == selected_node
    )
    if bool(invalid.any()):
        raise ValueError(
            "acceptable anchor member option must select one object type"
        )
    same_type = member_mask.unsqueeze(-2) & (
        member_is_road.unsqueeze(-2)
        == selected_road.unsqueeze(-1)
    )
    included_loss = nn.functional.softplus(-member_logits).unsqueeze(-2)
    excluded_loss = nn.functional.softplus(member_logits).unsqueeze(-2)
    option_member_loss = torch.where(
        acceptable_sets,
        included_loss,
        excluded_loss,
    )
    positive = acceptable_sets & same_type
    negative = ~acceptable_sets & same_type
    positive_mean = (
        option_member_loss * positive.to(option_member_loss.dtype)
    ).sum(dim=-1) / positive.sum(dim=-1).clamp_min(1).to(
        option_member_loss.dtype
    )
    negative_mean = (
        option_member_loss * negative.to(option_member_loss.dtype)
    ).sum(dim=-1) / negative.sum(dim=-1).clamp_min(1).to(
        option_member_loss.dtype
    )
    has_positive = positive.any(dim=-1)
    has_negative = negative.any(dim=-1)
    option_nll = (
        positive_mean * has_positive.to(positive_mean.dtype)
        + negative_mean * has_negative.to(negative_mean.dtype)
    ) / (
        has_positive.to(positive_mean.dtype)
        + has_negative.to(positive_mean.dtype)
    ).clamp_min(
        1.0
    )
    maximum = torch.finfo(option_nll.dtype).max
    masked = option_nll.masked_fill(~acceptable_set_mask, maximum)
    minimum = masked.amin(dim=-1)
    return torch.where(
        acceptable_set_mask.any(dim=-1),
        minimum,
        torch.zeros_like(minimum),
    )


def anchor_member_type_cardinality_targets(
    acceptable_sets: torch.Tensor,
    acceptable_set_mask: torch.Tensor,
    member_is_road: torch.Tensor,
    *,
    cardinality_count: int,
) -> tuple[torch.Tensor, torch.Tensor]:
    if cardinality_count < 1:
        raise ValueError("anchor member cardinality count must be positive")
    selected_road = (
        acceptable_sets & member_is_road.unsqueeze(-2)
    ).any(dim=-1)
    selected_node = (
        acceptable_sets & ~member_is_road.unsqueeze(-2)
    ).any(dim=-1)
    invalid = acceptable_set_mask & (
        selected_road == selected_node
    )
    if bool(invalid.any()):
        raise ValueError(
            "anchor member type target must select one object type"
        )
    option_types = torch.stack((selected_node, selected_road), dim=-1)
    acceptable_types = (
        option_types & acceptable_set_mask.unsqueeze(-1)
    ).any(dim=-2)
    counts = acceptable_sets.sum(dim=-1)
    if bool(
        (
            acceptable_set_mask
            & ((counts < 1) | (counts > cardinality_count))
        ).any()
    ):
        raise ValueError("anchor member cardinality target is invalid")
    count_one_hot = nn.functional.one_hot(
        counts.clamp_min(1) - 1,
        num_classes=cardinality_count,
    ).bool()
    acceptable_cardinalities = (
        option_types.unsqueeze(-1)
        & count_one_hot.unsqueeze(-2)
        & acceptable_set_mask.unsqueeze(-1).unsqueeze(-1)
    ).any(dim=-3)
    return acceptable_types, acceptable_cardinalities


def compute_target_a_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: TargetATrainingBatch,
    config: TargetAConfig,
) -> tuple[torch.Tensor, dict[str, float]]:
    targets = batch.targets
    weights = targets.sample_weights
    if weights.ndim != 1:
        raise ValueError("sample_weights must be [B]")
    anchor_weights = (
        targets.anchor_sample_weights
        if targets.anchor_sample_weights is not None
        else weights
    )
    ordinary_weights = (
        targets.ordinary_sample_weights
        if targets.ordinary_sample_weights is not None
        else weights
    )
    if (
        targets.anchor_sample_weights is not None
        and anchor_weights.shape != targets.anchor_status_mask.shape
    ):
        raise ValueError("anchor_sample_weights must match anchor status shape")
    if (
        targets.ordinary_sample_weights is not None
        and ordinary_weights.shape != targets.ordinary_task_mask.shape
    ):
        raise ValueError(
            "ordinary_sample_weights must match ordinary task shape"
        )
    losses: dict[str, torch.Tensor] = {}
    explicit_member_task_mask = (
        targets.anchor_member_task_mask
        if targets.anchor_member_task_mask is not None
        else torch.zeros_like(targets.anchor_candidate_task_mask)
    )
    explicit_member_types: torch.Tensor | None = None
    explicit_member_cardinalities: torch.Tensor | None = None
    if bool(explicit_member_task_mask.any()):
        if (
            targets.anchor_member_acceptable_sets is None
            or targets.anchor_member_acceptable_set_mask is None
            or batch.tensors.anchor_member_is_road is None
        ):
            raise ValueError(
                "anchor member task lacks explicit set supervision"
            )
        (
            explicit_member_types,
            explicit_member_cardinalities,
        ) = anchor_member_type_cardinality_targets(
            targets.anchor_member_acceptable_sets,
            targets.anchor_member_acceptable_set_mask,
            batch.tensors.anchor_member_is_road,
            cardinality_count=config.anchor_cardinality_count,
        )

    anchor_status_class_weights = (
        torch.tensor(
            config.anchor_status_class_weights,
            dtype=outputs["anchor_status_logits"].dtype,
            device=outputs["anchor_status_logits"].device,
        )
        if config.anchor_status_class_weights
        else None
    )
    anchor_status_raw = nn.functional.cross_entropy(
        outputs["anchor_status_logits"].transpose(1, 2),
        targets.anchor_status.clamp_min(0),
        weight=anchor_status_class_weights,
        reduction="none",
    )
    losses["anchor_status"] = _weighted_masked_mean(
        anchor_status_raw,
        targets.anchor_status_mask,
        anchor_weights,
    )
    if config.learned_anchor_gate:
        losses["anchor_gate"] = compute_anchor_gate_loss(
            outputs,
            batch,
            config,
        )
    if config.hierarchical_anchor_decoder:
        type_masks = anchor_candidate_type_masks(batch.tensors)
        acceptable_types = (
            targets.anchor_acceptable.unsqueeze(-1) & type_masks
        ).any(dim=2)
        if explicit_member_types is not None:
            acceptable_types |= explicit_member_types
        valid_types = type_masks.any(dim=2)
        anchor_type_raw = acceptable_set_nll(
            outputs["anchor_type_logits"],
            acceptable_types,
            valid_types,
        )
        losses["anchor_type"] = _weighted_masked_mean(
            anchor_type_raw,
            targets.anchor_candidate_task_mask | explicit_member_task_mask,
            anchor_weights,
        )
        if config.cardinality_conditioned_anchor_decoder:
            cardinality_masks = anchor_candidate_cardinality_masks(
                batch.tensors,
                config.anchor_cardinality_count,
            )
            typed_cardinality_masks = (
                type_masks.unsqueeze(-1)
                & cardinality_masks.unsqueeze(-2)
            )
            acceptable_cardinalities = (
                targets.anchor_acceptable.unsqueeze(-1).unsqueeze(-1)
                & typed_cardinality_masks
            ).any(dim=2)
            if explicit_member_cardinalities is not None:
                acceptable_cardinalities |= explicit_member_cardinalities
            valid_cardinalities = typed_cardinality_masks.any(dim=2)
            valid_cardinalities |= acceptable_cardinalities
            per_type_cardinality_raw = acceptable_set_nll(
                outputs["anchor_cardinality_logits"],
                acceptable_cardinalities,
                valid_cardinalities,
            )
            anchor_cardinality_raw = (
                per_type_cardinality_raw
                * acceptable_types.to(per_type_cardinality_raw.dtype)
            ).sum(dim=-1) / acceptable_types.sum(
                dim=-1
            ).clamp_min(1)
            losses["anchor_cardinality"] = _weighted_masked_mean(
                anchor_cardinality_raw,
                targets.anchor_candidate_task_mask
                | explicit_member_task_mask,
                anchor_weights,
            )
        per_type_candidate_raw = torch.stack(
            tuple(
                acceptable_set_nll(
                    outputs["anchor_candidate_logits"],
                    targets.anchor_acceptable
                    & type_masks[..., type_index],
                    type_masks[..., type_index],
                )
                for type_index in range(ANCHOR_TYPE_COUNT)
            ),
            dim=-1,
        )
        acceptable_type_count = acceptable_types.sum(dim=-1).clamp_min(1)
        anchor_set_raw = (
            per_type_candidate_raw
            * acceptable_types.to(per_type_candidate_raw.dtype)
        ).sum(dim=-1) / acceptable_type_count
        preferred_indices = targets.anchor_preferred.clamp_min(0)
        preferred_is_road = torch.gather(
            type_masks[..., 1],
            -1,
            preferred_indices.unsqueeze(-1),
        ).squeeze(-1)
        preferred_type_mask = torch.where(
            preferred_is_road.unsqueeze(-1),
            type_masks[..., 1],
            type_masks[..., 0],
        )
    else:
        anchor_set_raw = acceptable_set_nll(
            outputs["anchor_candidate_logits"],
            targets.anchor_acceptable,
            batch.tensors.anchor_candidate_mask,
        )
        preferred_type_mask = batch.tensors.anchor_candidate_mask
    losses["anchor_candidate"] = _weighted_masked_mean(
        anchor_set_raw,
        targets.anchor_candidate_task_mask,
        anchor_weights,
    )
    if config.structured_anchor_object_decoder:
        anchor_validity_raw = balanced_candidate_validity_bce(
            outputs["anchor_candidate_logits"],
            targets.anchor_acceptable,
            batch.tensors.anchor_candidate_mask,
        )
        losses["anchor_candidate_validity"] = _weighted_masked_mean(
            anchor_validity_raw,
            targets.anchor_candidate_task_mask,
            anchor_weights,
        )
    if (
        config.compositional_anchor_object_decoder
        and config.anchor_member_loss_weight > 0
    ):
        if (
            targets.anchor_member_acceptable_sets is not None
            and targets.anchor_member_acceptable_set_mask is not None
            and targets.anchor_member_task_mask is not None
            and batch.tensors.anchor_member_mask is not None
            and batch.tensors.anchor_member_is_road is not None
        ):
            anchor_member_raw = acceptable_member_set_nll(
                outputs["anchor_member_logits"],
                batch.tensors.anchor_member_mask,
                batch.tensors.anchor_member_is_road,
                targets.anchor_member_acceptable_sets,
                targets.anchor_member_acceptable_set_mask,
            )
            losses["anchor_member"] = _weighted_masked_mean(
                anchor_member_raw,
                targets.anchor_member_task_mask,
                anchor_weights,
            )
        else:
            member_targets, member_supervision_mask = (
                anchor_member_supervision(
                    targets.anchor_acceptable,
                    batch.tensors,
                )
            )
            anchor_member_raw = balanced_candidate_validity_bce(
                outputs["anchor_member_logits"],
                member_targets,
                member_supervision_mask,
            )
            losses["anchor_member"] = _weighted_masked_mean(
                anchor_member_raw,
                targets.anchor_candidate_task_mask,
                anchor_weights,
            )
    anchor_preferred_raw = preferred_cross_entropy(
        outputs["anchor_candidate_logits"],
        targets.anchor_preferred,
        preferred_type_mask,
    )
    losses["anchor_preferred"] = _weighted_masked_mean(
        anchor_preferred_raw,
        targets.anchor_candidate_task_mask & targets.anchor_preferred.ge(0),
        anchor_weights,
    )

    ordinary_set_raw = acceptable_set_nll(
        outputs["ordinary_plan_logits"],
        targets.ordinary_acceptable,
        batch.tensors.ordinary_plan_mask,
    )
    losses["ordinary_plan"] = _weighted_masked_mean(
        ordinary_set_raw,
        targets.ordinary_task_mask,
        ordinary_weights,
    )
    if config.hierarchical_ordinary_plan_decoder:
        decision_masks = ordinary_plan_decision_masks(batch.tensors)
        decision_acceptable = (
            targets.ordinary_acceptable.unsqueeze(-1)
            & decision_masks
        ).any(dim=2)
        ordinary_decision_raw = acceptable_set_nll(
            outputs["ordinary_decision_logits"],
            decision_acceptable,
            decision_masks.any(dim=2),
        )
        losses["ordinary_decision"] = _weighted_masked_mean(
            ordinary_decision_raw,
            targets.ordinary_task_mask,
            ordinary_weights,
        )
        if config.ordinary_decision_validity_loss_weight > 0:
            ordinary_decision_validity_raw = (
                balanced_candidate_validity_bce(
                    outputs["ordinary_decision_validity_logits"],
                    decision_acceptable,
                    decision_masks.any(dim=2),
                )
            )
            losses["ordinary_decision_validity"] = (
                _weighted_masked_mean(
                    ordinary_decision_validity_raw,
                    targets.ordinary_task_mask,
                    ordinary_weights,
                )
            )
    if config.ordinary_candidate_validity_loss_weight > 0:
        ordinary_validity_logits = (
            outputs["ordinary_plan_validity_logits"]
            if config.separate_ordinary_candidate_validity_head
            else outputs["ordinary_plan_logits"]
        )
        ordinary_validity_raw = balanced_candidate_validity_bce(
            ordinary_validity_logits,
            targets.ordinary_acceptable,
            batch.tensors.ordinary_plan_mask,
        )
        losses["ordinary_candidate_validity"] = _weighted_masked_mean(
            ordinary_validity_raw,
            targets.ordinary_task_mask,
            ordinary_weights,
        )
    ordinary_preferred_raw = preferred_cross_entropy(
        outputs["ordinary_plan_logits"],
        targets.ordinary_preferred,
        batch.tensors.ordinary_plan_mask,
    )
    losses["ordinary_preferred"] = _weighted_masked_mean(
        ordinary_preferred_raw,
        targets.ordinary_task_mask & targets.ordinary_preferred.ge(0),
        ordinary_weights,
    )

    clue_raw = nn.functional.cross_entropy(
        outputs["clue_logits"].transpose(1, 2),
        targets.clue.clamp_min(0),
        reduction="none",
    )
    losses["clue"] = _weighted_masked_mean(
        clue_raw,
        targets.clue_task_mask,
        weights,
    )
    scope_raw = nn.functional.cross_entropy(
        outputs["fallback_scope_logits"].transpose(1, 2),
        targets.fallback_scope.clamp_min(0),
        reduction="none",
    )
    losses["fallback_scope"] = _weighted_masked_mean(
        scope_raw,
        targets.fallback_scope_task_mask,
        weights,
    )

    advance_set_raw = acceptable_set_nll(
        outputs["advance_right_plan_logits"],
        targets.advance_right_acceptable,
        batch.tensors.advance_right_plan_mask,
    )
    losses["advance_right_plan"] = _weighted_masked_mean(
        advance_set_raw,
        targets.advance_right_task_mask,
        weights,
    )
    advance_preferred_raw = preferred_cross_entropy(
        outputs["advance_right_plan_logits"],
        targets.advance_right_preferred,
        batch.tensors.advance_right_plan_mask,
    )
    losses["advance_right_preferred"] = _weighted_masked_mean(
        advance_preferred_raw,
        targets.advance_right_task_mask & targets.advance_right_preferred.ge(0),
        weights,
    )

    total = (
        losses["anchor_status"]
        + config.anchor_gate_loss_weight
        * losses.get(
            "anchor_gate",
            _finite_graph_zero(outputs["anchor_status_logits"]),
        )
        + config.anchor_type_loss_weight
        * losses.get(
            "anchor_type",
            _finite_graph_zero(
                outputs["anchor_status_logits"],
            ),
        )
        + losses.get(
            "anchor_cardinality",
            _finite_graph_zero(
                outputs["anchor_status_logits"],
            ),
        )
        + losses["anchor_candidate"]
        + config.anchor_candidate_validity_loss_weight
        * losses.get(
            "anchor_candidate_validity",
            _finite_graph_zero(outputs["anchor_candidate_logits"]),
        )
        + config.anchor_member_loss_weight
        * losses.get(
            "anchor_member",
            _finite_graph_zero(outputs["anchor_candidate_logits"]),
        )
        + config.preferred_loss_weight * losses["anchor_preferred"]
        + losses["ordinary_plan"]
        + config.ordinary_decision_loss_weight
        * losses.get(
            "ordinary_decision",
            _finite_graph_zero(outputs["ordinary_plan_logits"]),
        )
        + config.ordinary_decision_validity_loss_weight
        * losses.get(
            "ordinary_decision_validity",
            _finite_graph_zero(outputs["ordinary_plan_logits"]),
        )
        + config.ordinary_candidate_validity_loss_weight
        * losses.get(
            "ordinary_candidate_validity",
            _finite_graph_zero(outputs["ordinary_plan_logits"]),
        )
        + config.preferred_loss_weight * losses["ordinary_preferred"]
        + losses["clue"]
        + losses["fallback_scope"]
        + losses["advance_right_plan"]
        + config.preferred_loss_weight * losses["advance_right_preferred"]
    )
    return total, {key: float(value.detach().item()) for key, value in losses.items()}


def compute_anchor_gate_loss(
    outputs: Mapping[str, torch.Tensor],
    batch: TargetATrainingBatch,
    config: TargetAConfig,
) -> torch.Tensor:
    """Compute only the resolved/unresolved anchor hard-gate loss."""
    targets = batch.targets
    if (
        not config.learned_anchor_gate
        or targets.anchor_gate is None
        or targets.anchor_gate_mask is None
        or "anchor_gate_logits" not in outputs
    ):
        raise ValueError("learned anchor gate lacks training targets or logits")
    anchor_weights = (
        targets.anchor_sample_weights
        if targets.anchor_sample_weights is not None
        else targets.sample_weights
    )
    gate_class_weights = (
        torch.tensor(
            config.anchor_gate_class_weights,
            dtype=outputs["anchor_gate_logits"].dtype,
            device=outputs["anchor_gate_logits"].device,
        )
        if config.anchor_gate_class_weights
        else None
    )
    raw = nn.functional.cross_entropy(
        outputs["anchor_gate_logits"].transpose(1, 2),
        targets.anchor_gate.clamp_min(0),
        weight=gate_class_weights,
        reduction="none",
    )
    return _weighted_masked_mean(
        raw,
        targets.anchor_gate_mask,
        anchor_weights,
    )


def train_target_a_stage(
    train_batches: Sequence[TargetATrainingBatch],
    validation_batches: Sequence[TargetATrainingBatch],
    *,
    config: TargetAConfig,
    seed: int,
    device: torch.device,
    model: TargetAJointNetwork | None = None,
) -> TargetAStageResult:
    if not train_batches or not validation_batches:
        raise ValueError("Target A stage requires train and validation batches")
    initialization_seed = int(seed)
    random.seed(initialization_seed)
    torch.manual_seed(initialization_seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(initialization_seed)
    torch.set_num_threads(config.torch_num_threads)
    model = model or TargetAJointNetwork(config)
    model = model.to(device)
    count = parameter_count(model)
    if not config.min_parameter_count <= count <= config.max_parameter_count:
        raise ValueError(f"Target A parameter count {count} is outside the gate")
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )

    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = 0
    best_validation_loss = float("inf")
    no_improvement = 0
    history: list[dict[str, float]] = []
    started = time.perf_counter()
    for epoch in range(1, config.max_epochs + 1):
        model.train()
        order = list(range(len(train_batches)))
        random.Random(initialization_seed * 1000 + epoch).shuffle(order)
        train_total = 0.0
        for index in order:
            training_batch = move_training_batch(train_batches[index], device)
            optimizer.zero_grad(set_to_none=True)
            outputs = model(training_batch.tensors)
            loss, _ = compute_target_a_loss(outputs, training_batch, config)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            train_total += float(loss.detach().item())

        model.eval()
        validation_total = 0.0
        with torch.no_grad():
            for item in validation_batches:
                validation_batch = move_training_batch(item, device)
                outputs = model(validation_batch.tensors)
                loss, _ = compute_target_a_loss(outputs, validation_batch, config)
                validation_total += float(loss.item())
        train_loss = train_total / len(train_batches)
        validation_loss = validation_total / len(validation_batches)
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_loss,
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_validation_loss - 1e-6:
            best_state = copy.deepcopy(model.state_dict())
            best_epoch = epoch
            best_validation_loss = validation_loss
            no_improvement = 0
        else:
            no_improvement += 1
            if no_improvement >= config.patience:
                break
    if best_state is None:
        raise RuntimeError("Target A stage did not produce a checkpoint")
    model.load_state_dict(best_state)
    model.eval()
    return TargetAStageResult(
        model=model,
        best_epoch=best_epoch,
        best_validation_loss=best_validation_loss,
        history=history,
        wall_seconds=time.perf_counter() - started,
        state_signature=model_state_signature(model),
    )


def train_target_a_fixed_epochs(
    train_batches: Sequence[TargetATrainingBatch],
    *,
    config: TargetAConfig,
    seed: int,
    device: torch.device,
    epoch_count: int,
    model: TargetAJointNetwork | None = None,
) -> TargetAFixedEpochResult:
    """Fit on all outer-training data after inner validation fixes the epoch."""
    if not train_batches:
        raise ValueError("Target A fixed-epoch fit requires training batches")
    if not 1 <= epoch_count <= config.max_epochs:
        raise ValueError("Target A fixed epoch count is outside the config")
    initialization_seed = int(seed)
    random.seed(initialization_seed)
    torch.manual_seed(initialization_seed)
    if device.type == "cuda":
        torch.cuda.manual_seed_all(initialization_seed)
    torch.set_num_threads(config.torch_num_threads)
    model = (model or TargetAJointNetwork(config)).to(device)
    count = parameter_count(model)
    if not config.min_parameter_count <= count <= config.max_parameter_count:
        raise ValueError(f"Target A parameter count {count} is outside the gate")
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    history: list[dict[str, float]] = []
    started = time.perf_counter()
    for epoch in range(1, epoch_count + 1):
        model.train()
        order = list(range(len(train_batches)))
        random.Random(initialization_seed * 1000 + epoch).shuffle(order)
        train_total = 0.0
        for index in order:
            training_batch = move_training_batch(train_batches[index], device)
            optimizer.zero_grad(set_to_none=True)
            outputs = model(training_batch.tensors)
            loss, _ = compute_target_a_loss(outputs, training_batch, config)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            train_total += float(loss.detach().item())
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_total / len(train_batches),
            }
        )
    model.eval()
    return TargetAFixedEpochResult(
        model=model,
        epoch_count=epoch_count,
        history=history,
        wall_seconds=time.perf_counter() - started,
        state_signature=model_state_signature(model),
    )


def train_anchor_gate_stage(
    train_batches: Sequence[TargetATrainingBatch],
    validation_batches: Sequence[TargetATrainingBatch],
    *,
    model: TargetAJointNetwork,
    config: TargetAConfig,
    seed: int,
    device: torch.device,
) -> TargetAStageResult:
    """Tune only the hard-gate head while every shared parameter is frozen."""
    if not train_batches or not validation_batches:
        raise ValueError("anchor gate stage requires train and validation batches")
    model = _prepare_gate_only_model(model, config, seed=seed, device=device)
    gate_parameters = tuple(model.anchor_gate_head.parameters())
    optimizer = torch.optim.AdamW(
        gate_parameters,
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    best_state: dict[str, torch.Tensor] | None = None
    best_epoch = 0
    best_validation_loss = float("inf")
    no_improvement = 0
    history: list[dict[str, float]] = []
    started = time.perf_counter()
    for epoch in range(1, config.max_epochs + 1):
        model.eval()
        model.anchor_gate_head.train()
        order = list(range(len(train_batches)))
        random.Random(int(seed) * 1000 + epoch).shuffle(order)
        train_total = 0.0
        for index in order:
            training_batch = move_training_batch(train_batches[index], device)
            optimizer.zero_grad(set_to_none=True)
            loss = compute_anchor_gate_loss(
                model(training_batch.tensors),
                training_batch,
                config,
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(gate_parameters, 5.0)
            optimizer.step()
            train_total += float(loss.detach().item())
        model.eval()
        validation_total = 0.0
        with torch.no_grad():
            for item in validation_batches:
                validation_batch = move_training_batch(item, device)
                validation_total += float(
                    compute_anchor_gate_loss(
                        model(validation_batch.tensors),
                        validation_batch,
                        config,
                    ).item()
                )
        train_loss = train_total / len(train_batches)
        validation_loss = validation_total / len(validation_batches)
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_loss,
                "validation_loss": validation_loss,
            }
        )
        if validation_loss < best_validation_loss - 1e-6:
            best_state = copy.deepcopy(model.anchor_gate_head.state_dict())
            best_epoch = epoch
            best_validation_loss = validation_loss
            no_improvement = 0
        else:
            no_improvement += 1
            if no_improvement >= config.patience:
                break
    if best_state is None:
        raise RuntimeError("anchor gate stage did not produce a checkpoint")
    model.anchor_gate_head.load_state_dict(best_state)
    model.eval()
    return TargetAStageResult(
        model=model,
        best_epoch=best_epoch,
        best_validation_loss=best_validation_loss,
        history=history,
        wall_seconds=time.perf_counter() - started,
        state_signature=model_state_signature(model.anchor_gate_head),
    )


def train_anchor_gate_fixed_epochs(
    train_batches: Sequence[TargetATrainingBatch],
    *,
    model: TargetAJointNetwork,
    config: TargetAConfig,
    seed: int,
    device: torch.device,
    epoch_count: int,
) -> TargetAFixedEpochResult:
    """Fit only the hard-gate head after inner validation fixes the epoch."""
    if not train_batches:
        raise ValueError("anchor gate fixed-epoch fit requires training batches")
    if not 1 <= epoch_count <= config.max_epochs:
        raise ValueError("anchor gate fixed epoch count is outside the config")
    model = _prepare_gate_only_model(model, config, seed=seed, device=device)
    gate_parameters = tuple(model.anchor_gate_head.parameters())
    optimizer = torch.optim.AdamW(
        gate_parameters,
        lr=config.learning_rate,
        weight_decay=config.weight_decay,
    )
    history: list[dict[str, float]] = []
    started = time.perf_counter()
    for epoch in range(1, epoch_count + 1):
        model.eval()
        model.anchor_gate_head.train()
        order = list(range(len(train_batches)))
        random.Random(int(seed) * 1000 + epoch).shuffle(order)
        train_total = 0.0
        for index in order:
            training_batch = move_training_batch(train_batches[index], device)
            optimizer.zero_grad(set_to_none=True)
            loss = compute_anchor_gate_loss(
                model(training_batch.tensors),
                training_batch,
                config,
            )
            loss.backward()
            torch.nn.utils.clip_grad_norm_(gate_parameters, 5.0)
            optimizer.step()
            train_total += float(loss.detach().item())
        history.append(
            {
                "epoch": float(epoch),
                "train_loss": train_total / len(train_batches),
            }
        )
    model.eval()
    return TargetAFixedEpochResult(
        model=model,
        epoch_count=epoch_count,
        history=history,
        wall_seconds=time.perf_counter() - started,
        state_signature=model_state_signature(model.anchor_gate_head),
    )


def _prepare_gate_only_model(
    model: TargetAJointNetwork,
    config: TargetAConfig,
    *,
    seed: int,
    device: torch.device,
) -> TargetAJointNetwork:
    if not config.learned_anchor_gate or model.anchor_gate_head is None:
        raise ValueError("anchor gate-only training requires a learned gate head")
    random.seed(int(seed))
    torch.manual_seed(int(seed))
    if device.type == "cuda":
        torch.cuda.manual_seed_all(int(seed))
    torch.set_num_threads(config.torch_num_threads)
    model = model.to(device)
    for parameter in model.parameters():
        parameter.requires_grad_(False)
    for parameter in model.anchor_gate_head.parameters():
        parameter.requires_grad_(True)
    return model


def move_training_batch(
    batch: TargetATrainingBatch,
    device: torch.device,
) -> TargetATrainingBatch:
    def move_dataclass(value):
        values = {
            name: (
                item.to(device)
                if isinstance(item, torch.Tensor)
                else item
            )
            for name, item in vars(value).items()
        }
        return type(value)(**values)

    return TargetATrainingBatch(
        tensors=move_dataclass(batch.tensors),
        targets=move_dataclass(batch.targets),
    )


def model_state_signature(model: nn.Module) -> str:
    buffer = io.BytesIO()
    torch.save(
        {
            key: value.detach().cpu()
            for key, value in sorted(model.state_dict().items())
        },
        buffer,
    )
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def _weighted_masked_mean(
    values: torch.Tensor,
    mask: torch.Tensor,
    sample_weights: torch.Tensor,
) -> torch.Tensor:
    if values.shape != mask.shape:
        raise ValueError("weighted masked mean shapes differ")
    expanded_weights = sample_weights
    while expanded_weights.ndim < values.ndim:
        expanded_weights = expanded_weights.unsqueeze(-1)
    effective = mask.to(values.dtype) * expanded_weights
    denominator = effective.sum()
    if float(denominator.detach().item()) <= 0:
        return _finite_graph_zero(values)
    return (values * effective).sum() / denominator


def _finite_graph_zero(
    values: torch.Tensor,
    *,
    reduce_last: bool = False,
) -> torch.Tensor:
    finite_values = torch.where(torch.isfinite(values), values, torch.zeros_like(values))
    reduced = finite_values.sum(dim=-1) if reduce_last else finite_values.sum()
    return reduced * 0.0


def iter_case_group_folds(
    case_keys: Iterable[str],
    *,
    fold_count: int,
) -> dict[str, int]:
    if fold_count < 2:
        raise ValueError("fold_count must be at least two")
    result: dict[str, int] = {}
    for case_key in sorted(set(case_keys)):
        digest = hashlib.sha256(case_key.encode("utf-8")).digest()
        result[case_key] = int.from_bytes(digest[:8], "big") % fold_count
    return result


def iter_weighted_case_group_folds(
    case_weights: Mapping[str, float],
    *,
    fold_count: int,
) -> dict[str, int]:
    """Assign whole Cases to folds while balancing their supervised mass."""
    if fold_count < 2:
        raise ValueError("fold_count must be at least two")
    if not case_weights:
        raise ValueError("case_weights must not be empty")
    normalized: list[tuple[str, float]] = []
    for case_key, raw_weight in case_weights.items():
        weight = float(raw_weight)
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError("case fold weights must be finite and positive")
        normalized.append((str(case_key), weight))
    fold_weights = [0.0] * fold_count
    result: dict[str, int] = {}
    for case_key, weight in sorted(normalized, key=lambda row: (-row[1], row[0])):
        fold = min(range(fold_count), key=lambda index: (fold_weights[index], index))
        result[case_key] = fold
        fold_weights[fold] += weight
    return result


__all__ = [
    "TargetAFixedEpochResult",
    "TargetAStageResult",
    "TargetATrainingBatch",
    "TargetATrainingTargets",
    "acceptable_set_nll",
    "anchor_member_supervision",
    "balanced_candidate_validity_bce",
    "compute_anchor_gate_loss",
    "compute_target_a_loss",
    "iter_case_group_folds",
    "iter_weighted_case_group_folds",
    "model_state_signature",
    "move_training_batch",
    "preferred_cross_entropy",
    "train_anchor_gate_fixed_epochs",
    "train_anchor_gate_stage",
    "train_target_a_fixed_epochs",
    "train_target_a_stage",
]
