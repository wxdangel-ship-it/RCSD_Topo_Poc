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
    cardinality_logits: torch.Tensor
    cardinality_valid_mask: torch.Tensor

    @property
    def predicted_cardinality(self) -> torch.Tensor:
        if self.cardinality_logits.ndim != 2:
            raise JunctionPredictionError("cardinality logits must be rank-2")
        if self.cardinality_valid_mask.shape != self.cardinality_logits.shape:
            raise JunctionPredictionError("cardinality mask shape differs from logits")
        if not torch.all(self.cardinality_valid_mask.any(dim=-1)):
            raise JunctionPredictionError("each pointer set requires a valid count class")
        masked = self.cardinality_logits.masked_fill(
            ~self.cardinality_valid_mask,
            -torch.inf,
        )
        return masked.argmax(dim=-1)


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
    """Object pointers plus a dynamic categorical count over 0..candidate_count."""

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.pointer = ObjectPointerScorer(hidden_dim)
        self.cardinality_context = nn.Sequential(
            nn.Linear(hidden_dim * 3, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.cardinality_count_projection = nn.Sequential(
            nn.Linear(6, hidden_dim),
            nn.GELU(),
        )
        self.cardinality_score = nn.Sequential(
            nn.Linear(hidden_dim * 4, hidden_dim),
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
        batch_size = int(query_embeddings.shape[0])
        candidate_sum = torch.zeros_like(query_embeddings)
        candidate_counts = torch.zeros(
            (batch_size,),
            dtype=torch.long,
            device=query_embeddings.device,
        )
        selected = query_embeddings.new_zeros((0, int(query_embeddings.shape[1])))
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
            selected = object_embeddings[index_tensor]
            candidate_sum.index_add_(
                0,
                pointer.object_batch_indices,
                selected,
            )
            candidate_counts = torch.bincount(
                pointer.object_batch_indices,
                minlength=batch_size,
            )
        candidate_mean = candidate_sum / candidate_counts.clamp_min(1).unsqueeze(-1)
        candidate_max_rows: list[torch.Tensor] = []
        for batch_index in range(batch_size):
            local = selected[pointer.object_batch_indices == batch_index]
            candidate_max_rows.append(
                local.amax(dim=0)
                if int(local.shape[0])
                else torch.zeros_like(query_embeddings[batch_index])
            )
        candidate_max = torch.stack(candidate_max_rows)
        context = self.cardinality_context(
            torch.cat((query_embeddings, candidate_mean, candidate_max), dim=-1)
        )

        maximum_count = int(candidate_counts.max()) if batch_size else 0
        cardinality_rows: list[torch.Tensor] = []
        validity_rows: list[torch.Tensor] = []
        for batch_index in range(batch_size):
            local_count = int(candidate_counts[batch_index])
            count_values = torch.arange(
                local_count + 1,
                dtype=query_embeddings.dtype,
                device=query_embeddings.device,
            )
            denominator = float(max(local_count, 1))
            log_denominator = torch.log1p(
                query_embeddings.new_tensor(float(max(local_count, 1)))
            )
            count_features = torch.stack(
                (
                    count_values / denominator,
                    (float(local_count) - count_values) / denominator,
                    torch.log1p(count_values) / log_denominator,
                    (count_values == 0).to(query_embeddings.dtype),
                    (count_values == local_count).to(query_embeddings.dtype),
                    torch.full_like(count_values, 1.0 / float(local_count + 1)),
                ),
                dim=-1,
            )
            count_embeddings = self.cardinality_count_projection(count_features)
            repeated_context = context[batch_index].expand(local_count + 1, -1)
            valid_logits = self.cardinality_score(
                torch.cat(
                    (
                        repeated_context,
                        count_embeddings,
                        count_embeddings - repeated_context,
                        count_embeddings * repeated_context,
                    ),
                    dim=-1,
                )
            ).squeeze(-1)
            padding = maximum_count - local_count
            cardinality_rows.append(
                functional.pad(valid_logits, (0, padding), value=-torch.inf)
            )
            validity_rows.append(
                functional.pad(
                    torch.ones(
                        (local_count + 1,),
                        dtype=torch.bool,
                        device=query_embeddings.device,
                    ),
                    (0, padding),
                    value=False,
                )
            )
        return PointerSetOutput(
            object_refs=pointer.object_refs,
            object_batch_indices=pointer.object_batch_indices,
            logits=pointer.logits,
            cardinality_logits=torch.stack(cardinality_rows),
            cardinality_valid_mask=torch.stack(validity_rows),
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
    predicted_count = int(output.predicted_cardinality[batch_index])
    selected_count = max(0, min(predicted_count, len(local)))
    if not selected_count:
        return ()
    ranked = sorted(
        local,
        key=lambda index: float(output.logits[index]),
        reverse=True,
    )[:selected_count]
    return tuple(output.object_refs[index] for index in ranked)
