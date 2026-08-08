from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import torch
import torch.nn.functional as functional
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    JunctionPredictionError,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)


@dataclass(frozen=True)
class PointerScoreOutput:
    object_refs: tuple[ObjectRef, ...]
    object_batch_indices: torch.Tensor
    logits: torch.Tensor


@dataclass(frozen=True)
class PointerSetOutput:
    object_refs: tuple[ObjectRef, ...]
    object_batch_indices: torch.Tensor
    logits: torch.Tensor
    predicted_cardinality: torch.Tensor


@dataclass(frozen=True)
class RoadBreakSetOutput:
    road_refs: tuple[ObjectRef, ...]
    road_batch_indices: torch.Tensor
    count_logits: torch.Tensor
    fraction_slots: torch.Tensor
    max_break_points: int

    @property
    def overflow_class_index(self) -> int:
        return self.max_break_points + 1

    @property
    def presence_logits(self) -> torch.Tensor:
        if not int(self.count_logits.shape[0]):
            return self.count_logits.new_zeros((0,))
        present = torch.logsumexp(self.count_logits[:, 1:], dim=-1)
        return present - self.count_logits[:, 0]

    @property
    def fractions(self) -> torch.Tensor:
        """Compatibility view for the historical single-break auxiliary loss."""

        if not self.max_break_points:
            return self.fraction_slots.new_zeros((int(self.fraction_slots.shape[0]),))
        return self.fraction_slots[:, 0]


class ObjectPointerScorer(nn.Module):
    """Scores visible objects without raw-ID embeddings."""

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.score_head = nn.Sequential(
            nn.Linear(hidden_dim * 4, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, 1),
        )

    @staticmethod
    def _selected_indices(
        object_refs: Sequence[ObjectRef],
        roles: frozenset[EvidenceRole],
    ) -> tuple[int, ...]:
        return tuple(
            index for index, ref in enumerate(object_refs) if ref.role in roles
        )

    def forward(
        self,
        *,
        query_embeddings: torch.Tensor,
        object_embeddings: torch.Tensor,
        object_batch_indices: torch.Tensor,
        object_refs: Sequence[ObjectRef],
        roles: frozenset[EvidenceRole],
    ) -> PointerScoreOutput:
        indices = self._selected_indices(object_refs, roles)
        if not indices:
            return PointerScoreOutput(
                object_refs=(),
                object_batch_indices=torch.zeros(
                    (0,), dtype=torch.long, device=query_embeddings.device
                ),
                logits=query_embeddings.new_zeros((0,)),
            )
        index_tensor = torch.tensor(
            indices,
            dtype=torch.long,
            device=query_embeddings.device,
        )
        batches = object_batch_indices[index_tensor]
        selected = object_embeddings[index_tensor]
        queries = query_embeddings[batches]
        logits = self.score_head(
            torch.cat(
                (
                    queries,
                    selected,
                    selected - queries,
                    selected * queries,
                ),
                dim=-1,
            )
        ).squeeze(-1)
        return PointerScoreOutput(
            object_refs=tuple(object_refs[index] for index in indices),
            object_batch_indices=batches,
            logits=logits,
        )


class PointerSetHead(nn.Module):
    """Object pointer logits plus an uncapped set-cardinality prediction."""

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.pointer = ObjectPointerScorer(hidden_dim)
        self.cardinality_head = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(
        self,
        *,
        query_embeddings: torch.Tensor,
        object_embeddings: torch.Tensor,
        object_batch_indices: torch.Tensor,
        object_refs: Sequence[ObjectRef],
        roles: frozenset[EvidenceRole],
    ) -> PointerSetOutput:
        pointer = self.pointer(
            query_embeddings=query_embeddings,
            object_embeddings=object_embeddings,
            object_batch_indices=object_batch_indices,
            object_refs=object_refs,
            roles=roles,
        )
        candidate_pool = torch.zeros_like(query_embeddings)
        candidate_counts = query_embeddings.new_zeros(
            (int(query_embeddings.shape[0]), 1)
        )
        if len(pointer.object_refs):
            selected_indices = ObjectPointerScorer._selected_indices(
                object_refs,
                roles,
            )
            index_tensor = torch.tensor(
                selected_indices,
                dtype=torch.long,
                device=query_embeddings.device,
            )
            candidate_pool.index_add_(
                0,
                pointer.object_batch_indices,
                object_embeddings[index_tensor],
            )
            candidate_counts.index_add_(
                0,
                pointer.object_batch_indices,
                query_embeddings.new_ones((len(selected_indices), 1)),
            )
        candidate_pool = candidate_pool / candidate_counts.clamp_min(1.0)
        cardinality = functional.softplus(
            self.cardinality_head(
                torch.cat((query_embeddings, candidate_pool), dim=-1)
            ).squeeze(-1)
        )
        return PointerSetOutput(
            object_refs=pointer.object_refs,
            object_batch_indices=pointer.object_batch_indices,
            logits=pointer.logits,
            predicted_cardinality=cardinality,
        )


class RoadBreakSetHead(nn.Module):
    """Road-conditioned count and ordered multi-break location decoder."""

    def __init__(self, hidden_dim: int, *, max_break_points: int = 4) -> None:
        super().__init__()
        if max_break_points < 1:
            raise ValueError("max_break_points must be positive")
        self.max_break_points = int(max_break_points)
        input_dim = hidden_dim * 4
        self.trunk = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.count_head = nn.Linear(hidden_dim, self.max_break_points + 2)
        self.gap_head = nn.Linear(hidden_dim, self.max_break_points + 1)

    def forward(
        self,
        *,
        query_embeddings: torch.Tensor,
        object_embeddings: torch.Tensor,
        object_batch_indices: torch.Tensor,
        object_refs: Sequence[ObjectRef],
    ) -> RoadBreakSetOutput:
        indices = tuple(
            index
            for index, ref in enumerate(object_refs)
            if ref.role == EvidenceRole.RCSD_ROAD
        )
        if not indices:
            return RoadBreakSetOutput(
                road_refs=(),
                road_batch_indices=torch.zeros(
                    (0,), dtype=torch.long, device=query_embeddings.device
                ),
                count_logits=query_embeddings.new_zeros(
                    (0, self.max_break_points + 2)
                ),
                fraction_slots=query_embeddings.new_zeros(
                    (0, self.max_break_points)
                ),
                max_break_points=self.max_break_points,
            )
        index_tensor = torch.tensor(
            indices,
            dtype=torch.long,
            device=query_embeddings.device,
        )
        batches = object_batch_indices[index_tensor]
        roads = object_embeddings[index_tensor]
        queries = query_embeddings[batches]
        hidden = self.trunk(
            torch.cat(
                (queries, roads, roads - queries, roads * queries),
                dim=-1,
            )
        )
        gaps = functional.softplus(self.gap_head(hidden)) + 1e-4
        cumulative = torch.cumsum(gaps[:, :-1], dim=-1)
        fraction_slots = cumulative / gaps.sum(dim=-1, keepdim=True)
        return RoadBreakSetOutput(
            road_refs=tuple(object_refs[index] for index in indices),
            road_batch_indices=batches,
            count_logits=self.count_head(hidden),
            fraction_slots=fraction_slots,
            max_break_points=self.max_break_points,
        )


def decode_pointer_set(
    output: PointerSetOutput,
    *,
    batch_index: int,
) -> tuple[ObjectRef, ...]:
    if batch_index < 0 or batch_index >= int(output.predicted_cardinality.shape[0]):
        raise JunctionPredictionError("pointer-set batch index is out of range")
    local = tuple(
        index
        for index in range(len(output.object_refs))
        if int(output.object_batch_indices[index]) == batch_index
    )
    predicted_count = int(round(float(output.predicted_cardinality[batch_index])))
    selected_count = max(0, min(predicted_count, len(local)))
    if not selected_count:
        return ()
    ranked = sorted(
        local,
        key=lambda index: float(output.logits[index]),
        reverse=True,
    )[:selected_count]
    return tuple(output.object_refs[index] for index in ranked)
