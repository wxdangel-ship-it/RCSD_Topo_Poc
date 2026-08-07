from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import torch


ANCHOR_CANDIDATE_ROAD_FEATURE_INDEX = 27


@dataclass(frozen=True)
class AnchorMemberTensors:
    """Truth-free atomic members derived from the inference candidate set."""

    member_features: torch.Tensor
    member_is_road: torch.Tensor
    candidate_membership: torch.Tensor


@dataclass(frozen=True)
class AnchorMemberSetConfidence:
    """Absolute confidence for one selected typed member set."""

    set_log_probability: torch.Tensor
    mean_log_probability: torch.Tensor
    min_included_probability: torch.Tensor
    max_excluded_probability: torch.Tensor
    inclusion_margin: torch.Tensor
    selected_member_count: torch.Tensor
    expected_member_count: torch.Tensor
    cardinality_residual: torch.Tensor
    mean_entropy: torch.Tensor


def anchor_candidate_member_tensors(
    candidate_ids: Sequence[str],
    candidate_features: Sequence[Sequence[float]] | torch.Tensor,
) -> AnchorMemberTensors:
    """Split NODE/ROAD candidates into typed members without encoding raw IDs."""
    features = torch.as_tensor(candidate_features, dtype=torch.float32)
    if features.ndim != 2:
        raise ValueError("anchor candidate member features must be [C, F]")
    if len(candidate_ids) != features.shape[0]:
        raise ValueError("anchor candidate IDs/features differ")
    if features.shape[1] <= ANCHOR_CANDIDATE_ROAD_FEATURE_INDEX:
        raise ValueError("anchor candidate features lack the type field")
    if not candidate_ids:
        raise ValueError("anchor candidate members require candidates")

    ordered_keys = ordered_anchor_candidate_members(
        candidate_ids,
        features,
    )
    candidate_members: list[tuple[tuple[bool, str], ...]] = []
    member_indices = {
        key: index for index, key in enumerate(ordered_keys)
    }
    member_feature_rows: dict[tuple[bool, str], list[torch.Tensor]] = {}
    singleton_features: dict[tuple[bool, str], torch.Tensor] = {}
    for candidate_index, candidate_id in enumerate(candidate_ids):
        is_road = bool(
            features[
                candidate_index,
                ANCHOR_CANDIDATE_ROAD_FEATURE_INDEX,
            ].item()
            > 0.5
        )
        keys = tuple(
            (is_road, member)
            for member in _candidate_members(candidate_id)
        )
        candidate_members.append(keys)
        for key in keys:
            member_feature_rows.setdefault(key, []).append(
                features[candidate_index]
            )
        if len(keys) == 1:
            singleton_features.setdefault(keys[0], features[candidate_index])

    member_count = len(member_indices)
    membership = torch.zeros(
        (len(candidate_ids), member_count),
        dtype=torch.bool,
    )
    for candidate_index, keys in enumerate(candidate_members):
        for key in keys:
            membership[candidate_index, member_indices[key]] = True

    member_features = torch.stack(
        tuple(
            singleton_features.get(
                key,
                torch.stack(member_feature_rows[key]).mean(dim=0),
            )
            for key in ordered_keys
        )
    )
    member_is_road = torch.tensor(
        [key[0] for key in ordered_keys],
        dtype=torch.bool,
    )
    return AnchorMemberTensors(
        member_features=member_features,
        member_is_road=member_is_road,
        candidate_membership=membership,
    )


def ordered_anchor_candidate_members(
    candidate_ids: Sequence[str],
    candidate_features: Sequence[Sequence[float]] | torch.Tensor,
) -> tuple[tuple[bool, str], ...]:
    """Return typed atomic members in the tensor builder's stable order."""
    features = torch.as_tensor(candidate_features, dtype=torch.float32)
    if features.ndim != 2:
        raise ValueError("anchor candidate member features must be [C, F]")
    if len(candidate_ids) != features.shape[0]:
        raise ValueError("anchor candidate IDs/features differ")
    if features.shape[1] <= ANCHOR_CANDIDATE_ROAD_FEATURE_INDEX:
        raise ValueError("anchor candidate features lack the type field")
    ordered: list[tuple[bool, str]] = []
    seen: set[tuple[bool, str]] = set()
    for candidate_index, candidate_id in enumerate(candidate_ids):
        is_road = bool(
            features[
                candidate_index,
                ANCHOR_CANDIDATE_ROAD_FEATURE_INDEX,
            ].item()
            > 0.5
        )
        for member in _candidate_members(candidate_id):
            key = (is_road, member)
            if key not in seen:
                seen.add(key)
                ordered.append(key)
    if not ordered:
        raise ValueError("anchor candidate members require candidates")
    return tuple(ordered)


def anchor_member_set_confidence(
    member_logits: torch.Tensor,
    member_mask: torch.Tensor,
    member_is_road: torch.Tensor,
    candidate_membership: torch.Tensor,
    candidate_indices: torch.Tensor,
) -> AnchorMemberSetConfidence:
    """Score exact typed-set completeness without labels or raw IDs."""
    if member_logits.ndim < 1:
        raise ValueError("anchor member logits must include a member dimension")
    if (
        member_mask.shape != member_logits.shape
        or member_is_road.shape != member_logits.shape
    ):
        raise ValueError("anchor member confidence tensor shapes differ")
    if member_mask.dtype is not torch.bool or member_is_road.dtype is not torch.bool:
        raise ValueError("anchor member confidence masks must be bool")
    expected_membership = (
        *member_logits.shape[:-1],
        candidate_membership.shape[-2],
        member_logits.shape[-1],
    )
    if candidate_membership.shape != expected_membership:
        raise ValueError("anchor candidate membership shape differs")
    if candidate_membership.dtype is not torch.bool:
        raise ValueError("anchor candidate membership must be bool")
    if candidate_indices.shape != member_logits.shape[:-1]:
        raise ValueError("anchor candidate index shape differs")
    candidate_count = candidate_membership.shape[-2]
    if bool(
        ((candidate_indices < 0) | (candidate_indices >= candidate_count)).any()
    ):
        raise ValueError("anchor candidate index is outside the candidate set")

    member_count = member_logits.shape[-1]
    flat_membership = candidate_membership.reshape(
        -1,
        candidate_count,
        member_count,
    )
    flat_indices = candidate_indices.reshape(-1)
    selected = flat_membership[
        torch.arange(flat_indices.numel(), device=flat_indices.device),
        flat_indices,
    ].reshape(member_logits.shape)
    if bool((selected & ~member_mask).any()) or bool(
        (~selected.any(dim=-1)).any()
    ):
        raise ValueError("selected anchor candidate has invalid membership")
    selected_road = (selected & member_is_road).any(dim=-1)
    selected_node = (selected & ~member_is_road).any(dim=-1)
    if bool((selected_road & selected_node).any()):
        raise ValueError("selected anchor candidate mixes Node and Road members")
    same_type = member_mask & (
        member_is_road == selected_road.unsqueeze(-1)
    )
    included = selected & same_type
    excluded = same_type & ~selected
    probabilities = torch.sigmoid(member_logits).clamp(1e-7, 1.0 - 1e-7)
    included_log = torch.log(probabilities)
    excluded_log = torch.log1p(-probabilities)
    set_log_probability = (
        included_log * included.to(included_log.dtype)
        + excluded_log * excluded.to(excluded_log.dtype)
    ).sum(dim=-1)
    typed_count = same_type.sum(dim=-1).clamp_min(1)
    min_included = probabilities.masked_fill(~included, 1.0).amin(dim=-1)
    max_excluded = probabilities.masked_fill(~excluded, 0.0).amax(dim=-1)
    selected_count = included.sum(dim=-1)
    expected_count = (
        probabilities * same_type.to(probabilities.dtype)
    ).sum(dim=-1)
    entropy = -(
        probabilities * included_log
        + (1.0 - probabilities) * excluded_log
    )
    mean_entropy = (
        entropy * same_type.to(entropy.dtype)
    ).sum(dim=-1) / typed_count.to(entropy.dtype)
    return AnchorMemberSetConfidence(
        set_log_probability=set_log_probability,
        mean_log_probability=(
            set_log_probability / typed_count.to(set_log_probability.dtype)
        ),
        min_included_probability=min_included,
        max_excluded_probability=max_excluded,
        inclusion_margin=min_included - max_excluded,
        selected_member_count=selected_count,
        expected_member_count=expected_count,
        cardinality_residual=(
            expected_count - selected_count.to(expected_count.dtype)
        ).abs(),
        mean_entropy=mean_entropy,
    )


def _candidate_members(candidate_id: str) -> tuple[str, ...]:
    text = str(candidate_id).strip()
    _, separator, payload = text.partition(":")
    if not separator:
        payload = text
    members = tuple(
        member.strip()
        for member in payload.split("|")
        if member.strip()
    )
    if not members:
        return ("EMPTY_CANDIDATE",)
    return tuple(dict.fromkeys(members))


__all__ = [
    "ANCHOR_CANDIDATE_ROAD_FEATURE_INDEX",
    "AnchorMemberSetConfidence",
    "AnchorMemberTensors",
    "anchor_candidate_member_tensors",
    "anchor_member_set_confidence",
    "ordered_anchor_candidate_members",
]
