from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from itertools import combinations
from typing import Sequence

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_data import (
    JunctionJointBatch,
    JunctionJointExample,
)


DEFAULT_MAX_PLAN_CARDINALITY = 24
DEFAULT_MAX_PLAN_CANDIDATES = 2048


@dataclass(frozen=True)
class JunctionPlanCandidateBatch:
    candidate_sets: torch.Tensor
    candidate_mask: torch.Tensor
    inference_candidate_mask: torch.Tensor
    positive_mask: torch.Tensor

    def to(self, device: torch.device | str) -> JunctionPlanCandidateBatch:
        return JunctionPlanCandidateBatch(
            candidate_sets=self.candidate_sets.to(device),
            candidate_mask=self.candidate_mask.to(device),
            inference_candidate_mask=self.inference_candidate_mask.to(device),
            positive_mask=self.positive_mask.to(device),
        )


class JunctionCompletePlanRanker(nn.Module):
    """Scores complete Node/Road sets without changing the business-state branch."""

    def __init__(self, hidden_dim: int, *, dropout: float) -> None:
        super().__init__()
        if hidden_dim < 32:
            raise ValueError("junction plan ranker hidden dimension is too small")
        self.numeric_stem = nn.Sequential(
            nn.Linear(14, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.score = nn.Sequential(
            nn.Linear(hidden_dim * 4, hidden_dim * 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.LayerNorm(hidden_dim * 2),
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(
        self,
        member_hidden: torch.Tensor,
        context: torch.Tensor,
        batch: JunctionJointBatch,
        plans: JunctionPlanCandidateBatch,
    ) -> torch.Tensor:
        if member_hidden.ndim != 3 or context.ndim != 2:
            raise ValueError("junction plan ranker encoder shape is invalid")
        if plans.candidate_sets.ndim != 3:
            raise ValueError("junction plan candidates must be rank-3")
        if plans.candidate_sets.shape[0] != member_hidden.shape[0]:
            raise ValueError("junction plan candidate batch size differs")
        if plans.candidate_sets.shape[2] != member_hidden.shape[1]:
            raise ValueError("junction plan member width differs")
        selected = plans.candidate_sets & batch.member_mask.unsqueeze(1)
        selected_float = selected.to(member_hidden.dtype)
        available_float = batch.member_mask.unsqueeze(1).to(member_hidden.dtype)
        unselected_float = available_float - selected_float
        selected_count = selected_float.sum(dim=2).clamp_min(1.0)
        unselected_count = unselected_float.sum(dim=2).clamp_min(1.0)
        selected_pool = torch.einsum("bpm,bmh->bph", selected_float, member_hidden)
        selected_pool = selected_pool / selected_count.unsqueeze(-1)
        unselected_pool = torch.einsum(
            "bpm,bmh->bph", unselected_float, member_hidden
        ) / unselected_count.unsqueeze(-1)

        role_is_road = batch.member_features[:, :, 0].clamp(0.0, 1.0)
        road_count = torch.einsum("bpm,bm->bp", selected_float, role_is_road)
        node_count = selected_count - road_count
        distance = batch.member_features[:, :, 1].clamp_min(0.0)
        selected_distance_sum = torch.einsum("bpm,bm->bp", selected_float, distance)
        selected_distance_mean = selected_distance_sum / selected_count
        selected_distance_square = torch.einsum(
            "bpm,bm->bp", selected_float, distance.square()
        ) / selected_count
        selected_distance_std = (
            selected_distance_square - selected_distance_mean.square()
        ).clamp_min(0.0).sqrt()

        relation = batch.member_relation_mask.to(member_hidden.dtype)
        incidence = batch.member_incidence_mask.to(member_hidden.dtype)
        relation_internal, relation_boundary = _edge_statistics(
            selected_float, unselected_float, relation
        )
        incidence_internal, incidence_boundary = _edge_statistics(
            selected_float, unselected_float, incidence
        )
        total_members = batch.member_mask.sum(dim=1).clamp_min(1).to(member_hidden.dtype)
        numeric = torch.stack(
            (
                selected_count / total_members.unsqueeze(1),
                node_count / selected_count,
                road_count / selected_count,
                selected_distance_mean,
                selected_distance_std,
                relation_internal / selected_count,
                relation_boundary / selected_count,
                incidence_internal / selected_count,
                incidence_boundary / selected_count,
                (selected_count == 1).to(member_hidden.dtype),
                (node_count > 0).to(member_hidden.dtype),
                (road_count > 0).to(member_hidden.dtype),
                (node_count > 0).logical_and(road_count > 0).to(member_hidden.dtype),
                selected_count.log1p() / 4.0,
            ),
            dim=-1,
        )
        plan_hidden = self.numeric_stem(numeric)
        expanded_context = context.unsqueeze(1).expand(
            -1, plans.candidate_sets.shape[1], -1
        )
        logits = self.score(
            torch.cat(
                (selected_pool, unselected_pool, expanded_context, plan_hidden),
                dim=-1,
            )
        ).squeeze(-1)
        return logits.masked_fill(~plans.candidate_mask, float("-inf"))

    @staticmethod
    def loss_by_row(
        logits: torch.Tensor,
        plans: JunctionPlanCandidateBatch,
    ) -> torch.Tensor:
        if logits.shape != plans.candidate_mask.shape:
            raise ValueError("junction plan logits/mask shape differs")
        if not (plans.positive_mask & plans.candidate_mask).any(dim=1).all():
            raise ValueError("junction plan training row has no positive plan")
        all_score = torch.logsumexp(
            logits.masked_fill(~plans.candidate_mask, float("-inf")), dim=1
        )
        positive_score = torch.logsumexp(
            logits.masked_fill(~plans.positive_mask, float("-inf")), dim=1
        )
        return all_score - positive_score

    @staticmethod
    def decode(
        logits: torch.Tensor,
        plans: JunctionPlanCandidateBatch,
    ) -> torch.Tensor:
        eligible = plans.candidate_mask & plans.inference_candidate_mask
        if not eligible.any(dim=1).all():
            raise ValueError("junction plan inference row has no candidate")
        choice = logits.masked_fill(~eligible, float("-inf")).argmax(dim=1)
        return plans.candidate_sets.gather(
            1,
            choice[:, None, None].expand(-1, 1, plans.candidate_sets.shape[2]),
        ).squeeze(1)


class JunctionPlanTeacherAdapter(nn.Module):
    """Training-only residual adapter for a supervision source/domain."""

    def __init__(self, hidden_dim: int, *, dropout: float) -> None:
        super().__init__()
        self.member_adapter = _residual_adapter(hidden_dim, dropout)
        self.context_adapter = _residual_adapter(hidden_dim, dropout)

    def forward(
        self,
        member_hidden: torch.Tensor,
        context: torch.Tensor,
        member_mask: torch.Tensor,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        if member_hidden.ndim != 3 or context.ndim != 2:
            raise ValueError("junction teacher adapter encoder shape is invalid")
        adapted_members = member_hidden + self.member_adapter(member_hidden)
        adapted_members = adapted_members * member_mask.unsqueeze(-1).to(
            adapted_members.dtype
        )
        return adapted_members, context + self.context_adapter(context)


class JunctionPlanGraphReranker(nn.Module):
    """Second-stage scorer with plan-internal role, variance and boundary evidence."""

    def __init__(self, hidden_dim: int, *, dropout: float) -> None:
        super().__init__()
        self.plan_query = nn.Linear(hidden_dim, hidden_dim)
        self.variance_stem = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.numeric_stem = nn.Sequential(
            nn.Linear(14, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.base_score_stem = nn.Sequential(
            nn.Linear(1, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.score = nn.Sequential(
            nn.Linear(hidden_dim * 8, hidden_dim * 3),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.LayerNorm(hidden_dim * 3),
            nn.Linear(hidden_dim * 3, hidden_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim, 1),
        )

    def forward(
        self,
        member_hidden: torch.Tensor,
        context: torch.Tensor,
        batch: JunctionJointBatch,
        plans: JunctionPlanCandidateBatch,
        base_logits: torch.Tensor,
    ) -> torch.Tensor:
        if base_logits.shape != plans.candidate_mask.shape:
            raise ValueError("junction plan reranker base score shape differs")
        selected = plans.candidate_sets & batch.member_mask.unsqueeze(1)
        selected_float = selected.to(member_hidden.dtype)
        available = batch.member_mask.unsqueeze(1)
        unselected_float = (available & ~selected).to(member_hidden.dtype)
        selected_count = selected_float.sum(dim=2).clamp_min(1.0)
        member_query_score = torch.einsum(
            "bmh,bh->bm", member_hidden, self.plan_query(context)
        ) / member_hidden.shape[-1] ** 0.5
        attention_score = member_query_score.unsqueeze(1).expand_as(selected_float)
        attention_score = attention_score.masked_fill(~selected, -1e4)
        attention = attention_score.softmax(dim=2) * selected_float
        attention = attention / attention.sum(dim=2).clamp_min(1e-8).unsqueeze(-1)
        attention_pool = torch.einsum("bpm,bmh->bph", attention, member_hidden)
        mean_pool = torch.einsum(
            "bpm,bmh->bph", selected_float, member_hidden
        ) / selected_count.unsqueeze(-1)
        square_pool = torch.einsum(
            "bpm,bmh->bph", selected_float, member_hidden.square()
        ) / selected_count.unsqueeze(-1)
        variance_hidden = self.variance_stem(
            (square_pool - mean_pool.square()).clamp_min(0.0)
        )

        road_member = batch.member_features[:, :, 0].ge(0.5).unsqueeze(1)
        node_pool = _masked_plan_pool(member_hidden, selected & ~road_member)
        road_pool = _masked_plan_pool(member_hidden, selected & road_member)
        adjacency = batch.member_relation_mask | batch.member_incidence_mask
        boundary_weight = torch.matmul(
            selected_float, adjacency.to(member_hidden.dtype)
        ) * unselected_float
        boundary_pool = torch.einsum(
            "bpm,bmh->bph", boundary_weight, member_hidden
        ) / boundary_weight.sum(dim=2).clamp_min(1.0).unsqueeze(-1)

        relation_internal, relation_boundary = _edge_statistics(
            selected_float,
            unselected_float,
            batch.member_relation_mask.to(member_hidden.dtype),
        )
        incidence_internal, incidence_boundary = _edge_statistics(
            selected_float,
            unselected_float,
            batch.member_incidence_mask.to(member_hidden.dtype),
        )
        road_count = (selected & road_member).sum(dim=2).to(member_hidden.dtype)
        node_count = selected_count - road_count
        distance = batch.member_features[:, :, 1].clamp_min(0.0)
        distance_mean = torch.einsum(
            "bpm,bm->bp", selected_float, distance
        ) / selected_count
        distance_square = torch.einsum(
            "bpm,bm->bp", selected_float, distance.square()
        ) / selected_count
        distance_std = (distance_square - distance_mean.square()).clamp_min(0.0).sqrt()
        total_members = batch.member_mask.sum(dim=1).clamp_min(1).to(member_hidden.dtype)
        numeric = torch.stack(
            (
                selected_count / total_members.unsqueeze(1),
                node_count / selected_count,
                road_count / selected_count,
                distance_mean,
                distance_std,
                relation_internal / selected_count,
                relation_boundary / selected_count,
                incidence_internal / selected_count,
                incidence_boundary / selected_count,
                selected_count.eq(1).to(member_hidden.dtype),
                node_count.gt(0).to(member_hidden.dtype),
                road_count.gt(0).to(member_hidden.dtype),
                node_count.gt(0).logical_and(road_count.gt(0)).to(member_hidden.dtype),
                selected_count.log1p() / 4.0,
            ),
            dim=-1,
        )
        expanded_context = context.unsqueeze(1).expand(
            -1, plans.candidate_sets.shape[1], -1
        )
        safe_base_logits = torch.where(
            plans.candidate_mask,
            base_logits,
            torch.zeros_like(base_logits),
        )
        logits = self.score(
            torch.cat(
                (
                    attention_pool,
                    node_pool,
                    road_pool,
                    boundary_pool,
                    variance_hidden,
                    expanded_context,
                    self.numeric_stem(numeric),
                    self.base_score_stem(safe_base_logits.unsqueeze(-1)),
                ),
                dim=-1,
            )
        ).squeeze(-1)
        return logits.masked_fill(~plans.candidate_mask, float("-inf"))

    loss_by_row = staticmethod(JunctionCompletePlanRanker.loss_by_row)
    decode = staticmethod(JunctionCompletePlanRanker.decode)


def select_diverse_plan_shortlist(
    base_logits: torch.Tensor,
    plans: JunctionPlanCandidateBatch,
    batch: JunctionJointBatch,
    *,
    include_training_positives: bool,
    overall_count: int = 20,
    per_cardinality_count: int = 4,
    per_role_count: int = 8,
    max_candidates: int = 96,
) -> tuple[JunctionPlanCandidateBatch, torch.Tensor]:
    if base_logits.shape != plans.candidate_mask.shape:
        raise ValueError("junction diverse shortlist base score shape differs")
    if min(overall_count, per_cardinality_count, per_role_count) < 1:
        raise ValueError("junction diverse shortlist group size is invalid")
    selected_rows: list[list[int]] = []
    for row_index in range(base_logits.shape[0]):
        eligible = (
            plans.candidate_mask[row_index]
            & plans.inference_candidate_mask[row_index]
        )
        chosen: set[int] = set()

        def choose(mask: torch.Tensor, count: int) -> None:
            available = eligible & mask
            if not bool(available.any()):
                return
            indices = base_logits[row_index].masked_fill(
                ~available, float("-inf")
            ).topk(min(count, int(available.sum()))).indices
            chosen.update(int(index) for index in indices)

        choose(eligible, overall_count)
        cardinality = plans.candidate_sets[row_index].sum(dim=1)
        for count in range(1, 13):
            choose(cardinality.eq(count), per_cardinality_count)
        road_member = batch.member_features[row_index, :, 0].ge(0.5)
        road_count = (
            plans.candidate_sets[row_index] & road_member.unsqueeze(0)
        ).sum(dim=1)
        node_count = cardinality - road_count
        choose(node_count.gt(0) & road_count.eq(0), per_role_count)
        choose(road_count.gt(0) & node_count.eq(0), per_role_count)
        choose(node_count.gt(0) & road_count.gt(0), per_role_count)
        if len(chosen) > max_candidates:
            chosen = set(
                sorted(
                    chosen,
                    key=lambda index: (-float(base_logits[row_index, index]), index),
                )[:max_candidates]
            )
        ordered = sorted(
            chosen,
            key=lambda index: (-float(base_logits[row_index, index]), index),
        )
        if include_training_positives:
            positive_indices = (
                plans.positive_mask[row_index] & plans.candidate_mask[row_index]
            ).nonzero().flatten().tolist()
            ordered.extend(index for index in positive_indices if index not in chosen)
        if not ordered:
            raise ValueError("junction diverse shortlist is empty")
        selected_rows.append(ordered)

    maximum = max(map(len, selected_rows))
    members = plans.candidate_sets.shape[2]
    candidate_sets = torch.zeros(
        len(selected_rows), maximum, members, dtype=torch.bool, device=base_logits.device
    )
    candidate_mask = torch.zeros(
        len(selected_rows), maximum, dtype=torch.bool, device=base_logits.device
    )
    inference_mask = torch.zeros_like(candidate_mask)
    positive_mask = torch.zeros_like(candidate_mask)
    shortlist_logits = torch.full_like(candidate_mask, float("-inf"), dtype=base_logits.dtype)
    for row_index, indices in enumerate(selected_rows):
        count = len(indices)
        source = torch.tensor(indices, dtype=torch.long, device=base_logits.device)
        candidate_sets[row_index, :count] = plans.candidate_sets[row_index, source]
        candidate_mask[row_index, :count] = True
        inference_mask[row_index, :count] = plans.inference_candidate_mask[
            row_index, source
        ]
        positive_mask[row_index, :count] = plans.positive_mask[row_index, source]
        shortlist_logits[row_index, :count] = base_logits[row_index, source]
    return (
        JunctionPlanCandidateBatch(
            candidate_sets=candidate_sets,
            candidate_mask=candidate_mask,
            inference_candidate_mask=inference_mask,
            positive_mask=positive_mask,
        ),
        shortlist_logits,
    )


def collate_junction_plan_candidates(
    examples: Sequence[JunctionJointExample],
    *,
    training: bool,
    max_plan_cardinality: int = DEFAULT_MAX_PLAN_CARDINALITY,
    max_plan_candidates: int = DEFAULT_MAX_PLAN_CANDIDATES,
    max_training_candidates: int | None = None,
) -> JunctionPlanCandidateBatch:
    if not examples:
        raise ValueError("junction plan candidate batch is empty")
    if max_plan_cardinality < 1 or max_plan_candidates < 2:
        raise ValueError("junction plan candidate limits are invalid")
    if max_training_candidates is not None and max_training_candidates < 2:
        raise ValueError("junction plan training candidate limit is invalid")
    row_sets: list[tuple[frozenset[int], ...]] = []
    row_inference: list[frozenset[frozenset[int]]] = []
    row_positive: list[frozenset[frozenset[int]]] = []
    for row in examples:
        inference = generate_junction_plan_candidates(
            row,
            max_plan_cardinality=max_plan_cardinality,
            max_plan_candidates=max_plan_candidates,
        )
        positives = frozenset(
            frozenset(option)
            for option in row.member_acceptable_sets
            if option and len(option) <= max_plan_cardinality
        )
        selected_inference = (
            inference[:max_training_candidates]
            if training and max_training_candidates is not None
            else inference
        )
        values = list(selected_inference)
        if training:
            if not positives:
                raise ValueError("junction plan training row has no Gold plan")
            for positive in positives:
                if positive not in values:
                    values.append(positive)
            for negative in _gold_hard_negatives(row, positives):
                if negative not in values and len(values) < max_plan_candidates + 256:
                    values.append(negative)
        row_sets.append(tuple(values))
        row_inference.append(frozenset(selected_inference))
        row_positive.append(positives)
    maximum_plans = max(len(values) for values in row_sets)
    maximum_members = max(len(row.member_ids) for row in examples)
    candidate_sets = torch.zeros(
        len(examples), maximum_plans, maximum_members, dtype=torch.bool
    )
    candidate_mask = torch.zeros(len(examples), maximum_plans, dtype=torch.bool)
    inference_mask = torch.zeros_like(candidate_mask)
    positive_mask = torch.zeros_like(candidate_mask)
    for row_index, values in enumerate(row_sets):
        for plan_index, option in enumerate(values):
            candidate_mask[row_index, plan_index] = True
            inference_mask[row_index, plan_index] = option in row_inference[row_index]
            positive_mask[row_index, plan_index] = option in row_positive[row_index]
            for member_index in option:
                candidate_sets[row_index, plan_index, member_index] = True
    return JunctionPlanCandidateBatch(
        candidate_sets=candidate_sets,
        candidate_mask=candidate_mask,
        inference_candidate_mask=inference_mask,
        positive_mask=positive_mask,
    )


def generate_junction_plan_candidates(
    row: JunctionJointExample,
    *,
    max_plan_cardinality: int = DEFAULT_MAX_PLAN_CARDINALITY,
    max_plan_candidates: int = DEFAULT_MAX_PLAN_CANDIDATES,
) -> tuple[frozenset[int], ...]:
    """Build truth-independent complete-plan proposals from raw IDs and topology."""
    ordered: dict[frozenset[int], None] = {}
    member_count = len(row.member_ids)
    distances = [float(row.member_features[index, 1]) for index in range(member_count)]
    roles = [member_id.split(":", 1)[0] for member_id in row.member_ids]
    adjacency = _adjacency(
        member_count,
        row.member_relation_edges + row.member_incidence_edges,
    )

    def add(values: Sequence[int] | frozenset[int]) -> None:
        option = frozenset(int(value) for value in values)
        if option and len(option) <= max_plan_cardinality:
            ordered.setdefault(option, None)

    for option in _existing_candidate_sets(row):
        add(option)
    for index in range(member_count):
        add((index,))
    for role in (None, "NODE", "ROAD"):
        eligible = [
            index
            for index in range(member_count)
            if role is None or roles[index] == role
        ]
        eligible.sort(key=lambda index: (distances[index], index))
        for size in range(1, min(len(eligible), max_plan_cardinality) + 1):
            add(eligible[:size])
        combination_roots = eligible[:16]
        for size in (2, 3):
            for option in combinations(combination_roots[: 16 if size == 2 else 10], size):
                add(option)
    roots = sorted(range(member_count), key=lambda index: (distances[index], index))[:24]
    for root in roots:
        for radius in range(1, 5):
            add(_ego_ball(root, adjacency, radius))
        for option in _greedy_growth(
            root, adjacency, distances, max_plan_cardinality
        ):
            add(option)
        for option in _greedy_growth(
            root,
            adjacency,
            distances,
            max_plan_cardinality,
            allowed_role=roles[root],
            roles=roles,
        ):
            add(option)
    return tuple(ordered)[:max_plan_candidates]


def _gold_hard_negatives(
    row: JunctionJointExample,
    positives: frozenset[frozenset[int]],
) -> tuple[frozenset[int], ...]:
    member_count = len(row.member_ids)
    distances = [float(row.member_features[index, 1]) for index in range(member_count)]
    nearest = sorted(range(member_count), key=lambda index: (distances[index], index))[:24]
    values: dict[frozenset[int], None] = {}
    for positive in positives:
        for member in positive:
            reduced = positive - {member}
            if reduced:
                values.setdefault(frozenset(reduced), None)
        for member in nearest:
            if member not in positive:
                values.setdefault(frozenset((*positive, member)), None)
        for removed in positive:
            for added in nearest[:12]:
                if added not in positive:
                    values.setdefault(frozenset((positive - {removed}) | {added}), None)
    return tuple(values)


def _edge_statistics(
    selected: torch.Tensor,
    unselected: torch.Tensor,
    adjacency: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    selected_neighbors = torch.matmul(selected, adjacency)
    internal = (selected_neighbors * selected).sum(dim=2)
    boundary = (selected_neighbors * unselected).sum(dim=2)
    return internal, boundary


def _residual_adapter(hidden_dim: int, dropout: float) -> nn.Sequential:
    layer = nn.Sequential(
        nn.LayerNorm(hidden_dim),
        nn.Linear(hidden_dim, hidden_dim * 2),
        nn.GELU(),
        nn.Dropout(dropout),
        nn.Linear(hidden_dim * 2, hidden_dim),
    )
    nn.init.zeros_(layer[-1].weight)
    nn.init.zeros_(layer[-1].bias)
    return layer


def _masked_plan_pool(
    member_hidden: torch.Tensor,
    mask: torch.Tensor,
) -> torch.Tensor:
    values = mask.to(member_hidden.dtype)
    return torch.einsum("bpm,bmh->bph", values, member_hidden) / values.sum(
        dim=2
    ).clamp_min(1.0).unsqueeze(-1)


def _existing_candidate_sets(
    row: JunctionJointExample,
) -> tuple[frozenset[int], ...]:
    member_index = {member_id: index for index, member_id in enumerate(row.member_ids)}
    values: dict[frozenset[int], None] = {}
    for candidate_id in row.candidate_ids:
        if ":" not in candidate_id:
            continue
        role, raw_ids = candidate_id.split(":", 1)
        option = frozenset(
            member_index[f"{role}:{raw_id}"]
            for raw_id in raw_ids.split("|")
            if f"{role}:{raw_id}" in member_index
        )
        if option:
            values.setdefault(option, None)
    return tuple(values)


def _adjacency(
    member_count: int,
    edges: tuple[tuple[int, int, tuple[float, ...]], ...],
) -> tuple[frozenset[int], ...]:
    values = [set() for _ in range(member_count)]
    for first, second, _ in edges:
        values[first].add(second)
        values[second].add(first)
    return tuple(frozenset(value) for value in values)


def _ego_ball(
    root: int,
    adjacency: tuple[frozenset[int], ...],
    radius: int,
) -> frozenset[int]:
    distance = {root: 0}
    queue = deque((root,))
    while queue:
        current = queue.popleft()
        if distance[current] >= radius:
            continue
        for neighbor in adjacency[current]:
            if neighbor not in distance:
                distance[neighbor] = distance[current] + 1
                queue.append(neighbor)
    return frozenset(distance)


def _greedy_growth(
    root: int,
    adjacency: tuple[frozenset[int], ...],
    distances: list[float],
    maximum: int,
    *,
    allowed_role: str | None = None,
    roles: list[str] | None = None,
) -> tuple[frozenset[int], ...]:
    selected = {root}
    frontier = set(adjacency[root])
    prefixes = [frozenset(selected)]
    while frontier and len(selected) < maximum:
        eligible = [
            index
            for index in frontier
            if allowed_role is None or roles is not None and roles[index] == allowed_role
        ]
        if not eligible:
            break
        chosen = min(eligible, key=lambda index: (distances[index], index))
        frontier.remove(chosen)
        selected.add(chosen)
        frontier.update(adjacency[chosen] - selected)
        prefixes.append(frozenset(selected))
    return tuple(prefixes)


__all__ = [
    "DEFAULT_MAX_PLAN_CANDIDATES",
    "DEFAULT_MAX_PLAN_CARDINALITY",
    "JunctionCompletePlanRanker",
    "JunctionPlanGraphReranker",
    "JunctionPlanCandidateBatch",
    "JunctionPlanTeacherAdapter",
    "collate_junction_plan_candidates",
    "generate_junction_plan_candidates",
    "select_diverse_plan_shortlist",
]
