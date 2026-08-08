from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Sequence

import torch
import torch.nn.functional as functional
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_object_decoder import (
    PointerSetHead,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    JunctionPredictionError,
    SurfaceMode,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)


class ConstraintState(str, Enum):
    REQUIRED = "REQUIRED"
    FORBIDDEN = "FORBIDDEN"
    UNKNOWN = "UNKNOWN"
    REVIEW = "REVIEW"


@dataclass(frozen=True)
class SurfaceConstraint:
    object_ref: ObjectRef
    state: ConstraintState
    weight: float

    def validate(self) -> None:
        if self.object_ref.role not in {EvidenceRole.RCSD_NODE, EvidenceRole.RCSD_ROAD}:
            raise JunctionPredictionError(
                "virtual-surface constraint must target an RCSD Node or Road"
            )
        if not math.isfinite(self.weight) or self.weight < 0.0:
            raise JunctionPredictionError("surface constraint weight is invalid")
        if (
            self.state in {ConstraintState.UNKNOWN, ConstraintState.REVIEW}
            and self.weight != 0.0
        ):
            raise JunctionPredictionError("UNKNOWN/REVIEW surface constraint must have zero weight")


@dataclass(frozen=True)
class SurfaceHeadOutput:
    mode_logits: torch.Tensor
    existing_object_logits: torch.Tensor
    existing_object_refs: tuple[ObjectRef, ...]
    virtual_member_logits: torch.Tensor
    virtual_member_refs: tuple[ObjectRef, ...]
    virtual_member_batch_indices: torch.Tensor
    virtual_cardinality: torch.Tensor


class SurfaceBranchHeads(nn.Module):
    """Mode and object/member heads; stage isolation is provided by StageFirewall."""

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        if hidden_dim < 1:
            raise ValueError("hidden_dim must be positive")
        self.mode_head = nn.Linear(hidden_dim, len(SurfaceMode))
        self.existing_head = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, 1),
        )
        self.virtual_member_head = PointerSetHead(hidden_dim)

    def forward(
        self,
        *,
        query_embeddings: torch.Tensor,
        object_embeddings: torch.Tensor,
        object_batch_indices: torch.Tensor,
        object_refs: Sequence[ObjectRef],
    ) -> SurfaceHeadOutput:
        if query_embeddings.ndim != 2 or object_embeddings.ndim != 2:
            raise JunctionPredictionError("surface embeddings must be rank-2 tensors")
        if int(object_embeddings.shape[0]) != len(object_refs):
            raise JunctionPredictionError("surface object embedding/ref counts differ")
        if tuple(object_batch_indices.shape) != (len(object_refs),):
            raise JunctionPredictionError("surface object batch indices have wrong shape")
        if len(object_refs) and (
            int(object_batch_indices.min()) < 0
            or int(object_batch_indices.max()) >= int(query_embeddings.shape[0])
        ):
            raise JunctionPredictionError("surface object batch index is out of range")
        mode_logits = self.mode_head(query_embeddings)

        existing_indices = tuple(
            index
            for index, ref in enumerate(object_refs)
            if ref.role == EvidenceRole.RCSD_INTERSECTION
        )
        def score(indices: tuple[int, ...], head: nn.Module) -> torch.Tensor:
            if not indices:
                return object_embeddings.new_zeros((0,))
            index_tensor = torch.tensor(
                indices,
                dtype=torch.long,
                device=object_embeddings.device,
            )
            selected = object_embeddings[index_tensor]
            query = query_embeddings[object_batch_indices[index_tensor]]
            return head(torch.cat((query, selected), dim=-1)).squeeze(-1)

        virtual = self.virtual_member_head(
            query_embeddings=query_embeddings,
            object_embeddings=object_embeddings,
            object_batch_indices=object_batch_indices,
            object_refs=object_refs,
            roles=frozenset({EvidenceRole.RCSD_NODE, EvidenceRole.RCSD_ROAD}),
        )
        return SurfaceHeadOutput(
            mode_logits=mode_logits,
            existing_object_logits=score(existing_indices, self.existing_head),
            existing_object_refs=tuple(object_refs[index] for index in existing_indices),
            virtual_member_logits=virtual.logits,
            virtual_member_refs=virtual.object_refs,
            virtual_member_batch_indices=virtual.object_batch_indices,
            virtual_cardinality=virtual.predicted_cardinality,
        )


def acceptable_set_cross_entropy(
    logits: torch.Tensor,
    acceptable_indices: Sequence[Sequence[int]],
    sample_weights: torch.Tensor,
) -> torch.Tensor:
    if logits.ndim != 2 or len(acceptable_indices) != int(logits.shape[0]):
        raise JunctionPredictionError("acceptable-set target shape differs from logits")
    if tuple(sample_weights.shape) != (int(logits.shape[0]),):
        raise JunctionPredictionError("sample_weights has the wrong shape")
    losses: list[torch.Tensor] = []
    weights: list[torch.Tensor] = []
    for row_index, indices in enumerate(acceptable_indices):
        normalized = tuple(sorted(set(int(index) for index in indices)))
        weight = sample_weights[row_index]
        if not normalized or float(weight) <= 0.0:
            continue
        if normalized[0] < 0 or normalized[-1] >= int(logits.shape[1]):
            raise JunctionPredictionError("acceptable-set class index is out of range")
        index_tensor = torch.tensor(
            normalized,
            dtype=torch.long,
            device=logits.device,
        )
        loss = torch.logsumexp(logits[row_index], dim=0) - torch.logsumexp(
            logits[row_index, index_tensor], dim=0
        )
        losses.append(loss * weight)
        weights.append(weight)
    if not losses:
        return logits.sum() * 0.0
    return torch.stack(losses).sum() / torch.stack(weights).sum().clamp_min(1e-12)


def masked_tristate_member_loss(
    logits: torch.Tensor,
    object_refs: Sequence[ObjectRef],
    constraints: Sequence[SurfaceConstraint],
) -> torch.Tensor:
    if tuple(logits.shape) != (len(object_refs),):
        raise JunctionPredictionError("member logits/object refs have different sizes")
    if len(set(object_refs)) != len(object_refs):
        raise JunctionPredictionError("member object refs contain duplicates")
    constraint_by_ref: dict[ObjectRef, SurfaceConstraint] = {}
    for constraint in constraints:
        constraint.validate()
        if constraint.object_ref in constraint_by_ref:
            raise JunctionPredictionError("duplicate virtual-surface constraint")
        constraint_by_ref[constraint.object_ref] = constraint
    loss_terms: list[torch.Tensor] = []
    weights: list[float] = []
    for index, object_ref in enumerate(object_refs):
        constraint = constraint_by_ref.get(object_ref)
        if constraint is None or constraint.state in {
            ConstraintState.UNKNOWN,
            ConstraintState.REVIEW,
        }:
            continue
        target = 1.0 if constraint.state == ConstraintState.REQUIRED else 0.0
        loss_terms.append(
            functional.binary_cross_entropy_with_logits(
                logits[index],
                logits.new_tensor(target),
                reduction="none",
            )
            * constraint.weight
        )
        weights.append(constraint.weight)
    if not loss_terms:
        return logits.sum() * 0.0
    return torch.stack(loss_terms).sum() / max(sum(weights), 1e-12)


@dataclass(frozen=True)
class FrozenSurfaceConstraintAudit:
    scope_count: int
    supervised_count: int
    review_count: int
    required_reachable_count: int
    required_denominator: int
    required_missing_object_count: int
    reference_only_unknown_object_count: int
    visible_forbidden_object_count: int
    sealed_test_row_count: int
    training_executed: bool


def audit_frozen_surface_constraint_summary(
    summary_path: Path,
) -> FrozenSurfaceConstraintAudit:
    payload = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    audit = FrozenSurfaceConstraintAudit(
        scope_count=int(payload["virtual_surface_constraint_scope_count"]),
        supervised_count=int(payload["constraint_supervised"]["count"]),
        review_count=int(payload["constraint_review_row_count"]),
        required_reachable_count=int(payload["required_reachable"]["count"]),
        required_denominator=int(payload["required_reachable"]["denominator"]),
        required_missing_object_count=int(payload["required_missing_object_count"]),
        reference_only_unknown_object_count=int(
            payload["no_evidence_reference_only_object_count"]
        ),
        visible_forbidden_object_count=int(
            payload["visible_hard_forbidden_object_count"]
        ),
        sealed_test_row_count=int(payload["sealed_test_row_count"]),
        training_executed=bool(payload["training_executed"]),
    )
    expected = {
        "scope_count": 1685,
        "supervised_count": 1680,
        "review_count": 5,
        "required_reachable_count": 1528,
        "required_denominator": 1528,
        "required_missing_object_count": 0,
        "reference_only_unknown_object_count": 6,
        "sealed_test_row_count": 106,
    }
    actual = {
        key: getattr(audit, key)
        for key in expected
    }
    if actual != expected:
        raise JunctionPredictionError(
            f"frozen virtual-surface constraint ledger changed: {actual}"
        )
    if audit.visible_forbidden_object_count <= 0:
        raise JunctionPredictionError("frozen ledger lost FORBIDDEN supervision")
    if audit.training_executed:
        raise JunctionPredictionError("constraint ledger unexpectedly executed training")
    return audit
