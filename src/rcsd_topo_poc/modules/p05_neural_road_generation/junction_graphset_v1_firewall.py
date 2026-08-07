from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Mapping

import torch

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    JunctionEvidenceExample,
    JunctionPredictionError,
    ObjectTokenSpan,
    TOPOLOGY_EDGE_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
)


class EvidenceStage(str, Enum):
    STEP1 = "STEP1"
    SURFACE = "SURFACE"
    ANCHOR = "ANCHOR"
    STRUCTURED = "STRUCTURED"


STEP1_ALLOWED_ROLES = frozenset(
    {
        EvidenceRole.SWSD_JUNCTION,
        EvidenceRole.SWSD_NODE,
        EvidenceRole.SWSD_ROAD,
        EvidenceRole.DRIVEZONE,
    }
)
SURFACE_ALLOWED_ROLES = STEP1_ALLOWED_ROLES | {
    EvidenceRole.RCSD_INTERSECTION,
}
ANCHOR_ALLOWED_ROLES = frozenset(EvidenceRole)

STAGE_ALLOWED_ROLES: Mapping[EvidenceStage, frozenset[EvidenceRole]] = {
    EvidenceStage.STEP1: STEP1_ALLOWED_ROLES,
    EvidenceStage.SURFACE: SURFACE_ALLOWED_ROLES,
    EvidenceStage.ANCHOR: ANCHOR_ALLOWED_ROLES,
    EvidenceStage.STRUCTURED: ANCHOR_ALLOWED_ROLES,
}


@dataclass(frozen=True)
class StageEvidenceView:
    junction_key: str
    stage: EvidenceStage
    geometry_tokens: torch.Tensor
    object_spans: tuple[ObjectTokenSpan, ...]
    topology_edge_indices: torch.Tensor
    topology_edge_features: torch.Tensor
    cache_key: str

    @property
    def object_roles(self) -> tuple[EvidenceRole, ...]:
        return tuple(span.object_ref.role for span in self.object_spans)

    def validate(self) -> None:
        allowed_roles = STAGE_ALLOWED_ROLES[self.stage]
        unexpected = tuple(
            span.object_ref.key
            for span in self.object_spans
            if span.object_ref.role not in allowed_roles
        )
        if unexpected:
            raise JunctionPredictionError(
                f"{self.stage.value} contains forbidden roles: {unexpected}"
            )
        token_count = int(self.geometry_tokens.shape[0])
        cursor = 0
        for span in self.object_spans:
            span.validate(token_count)
            if span.start != cursor:
                raise JunctionPredictionError("stage object spans are not contiguous")
            cursor = span.end
        if cursor != token_count:
            raise JunctionPredictionError("stage spans do not cover every token")
        if tuple(self.topology_edge_indices.shape[:1]) != (2,):
            raise JunctionPredictionError("stage topology indices must have shape [2, E]")
        edge_count = int(self.topology_edge_indices.shape[1])
        if tuple(self.topology_edge_features.shape) != (
            edge_count,
            TOPOLOGY_EDGE_DIM,
        ):
            raise JunctionPredictionError("stage topology features must have shape [E, 8]")
        if edge_count and (
            int(self.topology_edge_indices.min()) < 0
            or int(self.topology_edge_indices.max()) >= token_count
        ):
            raise JunctionPredictionError("stage topology edge escapes its token view")


def _tensor_digest(tensor: torch.Tensor) -> bytes:
    normalized = tensor.detach().cpu().contiguous()
    return normalized.numpy().tobytes()


class StageFirewall:
    """Builds physically separate tensors for each business stage."""

    def build_view(
        self,
        example: JunctionEvidenceExample,
        stage: EvidenceStage,
    ) -> StageEvidenceView:
        example.validate()
        allowed_roles = STAGE_ALLOWED_ROLES[stage]
        old_to_new = torch.full(
            (int(example.geometry_tokens.shape[0]),),
            -1,
            dtype=torch.long,
            device=example.geometry_tokens.device,
        )
        token_parts: list[torch.Tensor] = []
        spans: list[ObjectTokenSpan] = []
        cursor = 0
        for span in example.object_spans:
            if span.object_ref.role not in allowed_roles:
                continue
            part = example.geometry_tokens[span.start : span.end].clone()
            token_parts.append(part)
            length = span.end - span.start
            old_indices = torch.arange(
                span.start,
                span.end,
                dtype=torch.long,
                device=example.geometry_tokens.device,
            )
            old_to_new[old_indices] = torch.arange(
                cursor,
                cursor + length,
                dtype=torch.long,
                device=example.geometry_tokens.device,
            )
            spans.append(ObjectTokenSpan(span.object_ref, cursor, cursor + length))
            cursor += length
        tokens = (
            torch.cat(token_parts, dim=0)
            if token_parts
            else example.geometry_tokens.new_zeros(
                (0, int(example.geometry_tokens.shape[1]))
            )
        )

        if int(example.topology_edge_indices.shape[1]):
            remapped = old_to_new[example.topology_edge_indices]
            keep = (remapped[0] >= 0) & (remapped[1] >= 0)
            edge_indices = remapped[:, keep].clone()
            edge_features = example.topology_edge_features[keep].clone()
        else:
            edge_indices = example.topology_edge_indices.clone()
            edge_features = example.topology_edge_features.clone()

        digest = hashlib.sha256()
        digest.update(example.junction_key.encode("utf-8"))
        digest.update(b"|")
        digest.update(stage.value.encode("ascii"))
        digest.update(b"\n")
        for span in spans:
            digest.update(
                f"{span.object_ref.key}|{span.start}|{span.end}\n".encode("utf-8")
            )
        digest.update(_tensor_digest(tokens))
        digest.update(_tensor_digest(edge_indices))
        digest.update(_tensor_digest(edge_features))
        view = StageEvidenceView(
            junction_key=example.junction_key,
            stage=stage,
            geometry_tokens=tokens,
            object_spans=tuple(spans),
            topology_edge_indices=edge_indices,
            topology_edge_features=edge_features,
            cache_key=digest.hexdigest(),
        )
        view.validate()
        return view
