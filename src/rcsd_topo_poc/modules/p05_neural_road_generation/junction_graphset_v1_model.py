from __future__ import annotations

import math
from dataclasses import dataclass
from itertools import combinations
from typing import Mapping, Sequence

import torch
import torch.nn.functional as functional
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_firewall import (
    EvidenceStage,
    StageEvidenceView,
    StageFirewall,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_object_decoder import (
    ObjectPointerScorer,
    PointerSetHead,
    RoadBreakSetHead,
    RoadBreakSetOutput,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_prediction import (
    AnchorNodeRef,
    AnchorState,
    CandidateBinding,
    CandidatePlan,
    JunctionEvidenceExample,
    JunctionPredictionError,
    QualityState,
    Step1DriveZoneState,
    SurfaceMode,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_store import (
    EvidenceRole,
    ObjectRef,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.junction_graphset_v1_surface import (
    ConstraintState,
    SurfaceBranchHeads,
    SurfaceConstraint,
    SurfaceHeadOutput,
    acceptable_set_cross_entropy,
    masked_tristate_member_loss,
)


ROLE_INDEX: Mapping[EvidenceRole, int] = {
    role: index for index, role in enumerate(EvidenceRole)
}
SWSD_ROLES = frozenset(
    {
        EvidenceRole.SWSD_JUNCTION,
        EvidenceRole.SWSD_NODE,
        EvidenceRole.SWSD_ROAD,
    }
)


@dataclass(frozen=True)
class EncodedStageBatch:
    stage: EvidenceStage
    junction_keys: tuple[str, ...]
    query_embeddings: torch.Tensor
    object_embeddings: torch.Tensor
    object_refs: tuple[ObjectRef, ...]
    object_batch_indices: torch.Tensor
    object_offsets: torch.Tensor


class GraphMessageBlock(nn.Module):
    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.edge_projection = nn.Linear(8, hidden_dim)
        self.message = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.norm = nn.LayerNorm(hidden_dim)

    def forward(
        self,
        object_embeddings: torch.Tensor,
        edge_object_indices: torch.Tensor,
        edge_features: torch.Tensor,
    ) -> torch.Tensor:
        if not int(edge_features.shape[0]) or not int(object_embeddings.shape[0]):
            return object_embeddings
        source = edge_object_indices[0]
        target = edge_object_indices[1]
        edge_embedding = self.edge_projection(edge_features)
        messages = self.message(
            torch.cat((object_embeddings[source], edge_embedding), dim=-1)
        )
        aggregated = torch.zeros_like(object_embeddings)
        aggregated.index_add_(0, target, messages)
        counts = object_embeddings.new_zeros((int(object_embeddings.shape[0]), 1))
        counts.index_add_(
            0,
            target,
            object_embeddings.new_ones((int(target.shape[0]), 1)),
        )
        return self.norm(object_embeddings + aggregated / counts.clamp_min(1.0))


class RoleSeparatedGraphSetEncoder(nn.Module):
    """Shared role-aware encoder invoked on physically isolated stage views."""

    def __init__(
        self,
        *,
        hidden_dim: int = 384,
        layers: int = 4,
        heads: int = 8,
        feedforward_dim: int = 1024,
        dropout: float = 0.1,
    ) -> None:
        super().__init__()
        if hidden_dim % heads:
            raise ValueError("hidden_dim must be divisible by heads")
        self.hidden_dim = hidden_dim
        self.token_projection = nn.Linear(21, hidden_dim)
        self.summary_kind_embedding = nn.Parameter(torch.zeros(5, hidden_dim))
        self.summary_score = nn.Linear(hidden_dim, 1)
        self.token_count_projection = nn.Linear(1, hidden_dim)
        self.role_embedding = nn.Embedding(len(EvidenceRole), hidden_dim)
        self.graph_message = GraphMessageBlock(hidden_dim)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim,
            nhead=heads,
            dim_feedforward=feedforward_dim,
            dropout=dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.set_encoder = nn.TransformerEncoder(
            encoder_layer,
            num_layers=layers,
            enable_nested_tensor=False,
        )
        self.cross_attention = nn.MultiheadAttention(
            hidden_dim,
            heads,
            dropout=dropout,
            batch_first=True,
        )
        self.query_norm = nn.LayerNorm(hidden_dim)
        self.object_relative_projection = nn.Linear(hidden_dim, hidden_dim)
        self.object_identity_norm = nn.LayerNorm(hidden_dim)
        self.empty_query = nn.Parameter(torch.zeros(hidden_dim))

    @property
    def parameter_count(self) -> int:
        return sum(parameter.numel() for parameter in self.parameters())

    def _encode_view(
        self,
        view: StageEvidenceView,
    ) -> tuple[torch.Tensor, torch.Tensor, tuple[ObjectRef, ...]]:
        view.validate()
        object_refs = tuple(span.object_ref for span in view.object_spans)
        if not object_refs:
            return self.empty_query, self.empty_query.new_zeros((0, self.hidden_dim)), ()

        token_to_object = torch.empty(
            (int(view.geometry_tokens.shape[0]),),
            dtype=torch.long,
            device=view.geometry_tokens.device,
        )
        for object_index, span in enumerate(view.object_spans):
            token_to_object[span.start : span.end] = object_index
        local_parts: list[torch.Tensor] = []
        for span in view.object_spans:
            tokens = view.geometry_tokens[span.start : span.end]
            summaries = torch.stack(
                (
                    tokens.mean(dim=0),
                    tokens.max(dim=0).values,
                    tokens[0],
                    tokens[-1],
                    tokens.std(dim=0, unbiased=False),
                )
            )
            summary_embeddings = (
                self.token_projection(summaries) + self.summary_kind_embedding
            )
            summary_weights = torch.softmax(
                self.summary_score(summary_embeddings).squeeze(-1),
                dim=0,
            )
            pooled = (summary_embeddings * summary_weights.unsqueeze(-1)).sum(dim=0)
            pooled = pooled + self.token_count_projection(
                pooled.new_tensor((math.log1p(int(tokens.shape[0])),))
            )
            role_index = torch.tensor(
                ROLE_INDEX[span.object_ref.role],
                dtype=torch.long,
                device=pooled.device,
            )
            local_parts.append(pooled + self.role_embedding(role_index))
        local_object_embeddings = torch.stack(local_parts)
        if int(view.topology_edge_indices.shape[1]):
            edge_object_indices = token_to_object[view.topology_edge_indices]
        else:
            edge_object_indices = view.topology_edge_indices
        graph_embeddings = self.graph_message(
            local_object_embeddings,
            edge_object_indices,
            view.topology_edge_features,
        )
        global_object_embeddings = self.set_encoder(
            graph_embeddings.unsqueeze(0)
        ).squeeze(0)

        swsd_indices = tuple(
            index
            for index, ref in enumerate(object_refs)
            if ref.role in SWSD_ROLES
        )
        if swsd_indices:
            query = global_object_embeddings[
                torch.tensor(
                    swsd_indices,
                    dtype=torch.long,
                    device=global_object_embeddings.device,
                )
            ].mean(dim=0)
        else:
            query = self.empty_query
        attended, _ = self.cross_attention(
            query.reshape(1, 1, -1),
            global_object_embeddings.unsqueeze(0),
            global_object_embeddings.unsqueeze(0),
            need_weights=False,
        )
        query = self.query_norm(query + attended.reshape(-1))
        relative = local_object_embeddings - query.unsqueeze(0)
        object_embeddings = self.object_identity_norm(
            global_object_embeddings
            + local_object_embeddings
            + self.object_relative_projection(relative)
        )
        return query, object_embeddings, object_refs

    def forward(self, views: Sequence[StageEvidenceView]) -> EncodedStageBatch:
        normalized = tuple(views)
        if normalized:
            stage = normalized[0].stage
            if any(view.stage != stage for view in normalized):
                raise JunctionPredictionError("one encoded batch cannot mix stages")
        else:
            stage = EvidenceStage.STRUCTURED
        queries: list[torch.Tensor] = []
        object_parts: list[torch.Tensor] = []
        object_refs: list[ObjectRef] = []
        object_batch_indices: list[int] = []
        offsets = [0]
        for batch_index, view in enumerate(normalized):
            query, objects, refs = self._encode_view(view)
            queries.append(query)
            object_parts.append(objects)
            object_refs.extend(refs)
            object_batch_indices.extend([batch_index] * len(refs))
            offsets.append(offsets[-1] + len(refs))
        device = self.empty_query.device
        query_embeddings = (
            torch.stack(queries)
            if queries
            else self.empty_query.new_zeros((0, self.hidden_dim))
        )
        object_embeddings = (
            torch.cat(object_parts, dim=0)
            if object_parts
            else self.empty_query.new_zeros((0, self.hidden_dim))
        )
        return EncodedStageBatch(
            stage=stage,
            junction_keys=tuple(view.junction_key for view in normalized),
            query_embeddings=query_embeddings,
            object_embeddings=object_embeddings,
            object_refs=tuple(object_refs),
            object_batch_indices=torch.tensor(
                object_batch_indices,
                dtype=torch.long,
                device=device,
            ),
            object_offsets=torch.tensor(offsets, dtype=torch.long, device=device),
        )


@dataclass(frozen=True)
class PairScoreOutput:
    pair_refs: tuple[tuple[ObjectRef, ObjectRef], ...]
    pair_batch_indices: torch.Tensor
    logits: torch.Tensor


@dataclass(frozen=True)
class CompletePlanScoreOutput:
    plan_ids: tuple[str, ...]
    plan_batch_indices: torch.Tensor
    logits: torch.Tensor


@dataclass(frozen=True)
class JunctionGraphSetRawOutput:
    junction_keys: tuple[str, ...]
    step1_logits: torch.Tensor
    conditioned_step1_indices: torch.Tensor
    surface: SurfaceHeadOutput
    conditioned_surface_mode_indices: torch.Tensor
    anchor_state_logits: torch.Tensor
    quality_logits: torch.Tensor
    anchor_member_refs: tuple[ObjectRef, ...]
    anchor_member_batch_indices: torch.Tensor
    anchor_member_logits: torch.Tensor
    anchor_member_cardinality_logits: torch.Tensor
    anchor_member_cardinality_valid_mask: torch.Tensor
    main_anchor_refs: tuple[AnchorNodeRef, ...]
    main_anchor_batch_indices: torch.Tensor
    main_anchor_logits: torch.Tensor
    node_equivalence: PairScoreOutput
    road_break: RoadBreakSetOutput
    complete_plan: CompletePlanScoreOutput

    @property
    def anchor_member_cardinality(self) -> torch.Tensor:
        masked = self.anchor_member_cardinality_logits.masked_fill(
            ~self.anchor_member_cardinality_valid_mask,
            -torch.inf,
        )
        return masked.argmax(dim=-1)


PLAN_SCALAR_DIM = (
    len(Step1DriveZoneState)
    + len(SurfaceMode)
    + len(AnchorState)
    + len(QualityState)
    + 8
)


class CompletePlanScorer(nn.Module):
    """Scores bound full plans, including variable Road-break point sets."""

    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.hidden_dim = hidden_dim
        self.break_point_encoder = nn.Sequential(
            nn.Linear(hidden_dim + 7, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.equivalence_group_encoder = nn.Sequential(
            nn.Linear(hidden_dim + 1, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.scalar_projection = nn.Sequential(
            nn.Linear(PLAN_SCALAR_DIM, hidden_dim),
            nn.GELU(),
        )
        self.plan_head = nn.Sequential(
            nn.Linear(hidden_dim * 7, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, 1),
        )

    @staticmethod
    def _one_hot(enum_value, enum_type, *, device: torch.device) -> torch.Tensor:
        values = tuple(enum_type)
        tensor = torch.zeros((len(values),), dtype=torch.float32, device=device)
        tensor[values.index(enum_value)] = 1.0
        return tensor

    @staticmethod
    def _fraction_features(
        fraction: float,
        *,
        reference: torch.Tensor,
    ) -> torch.Tensor:
        value = reference.new_tensor(float(fraction))
        frequencies = value.new_tensor((1.0, 2.0, 4.0))
        angles = math.pi * value * frequencies
        return torch.cat((value.reshape(1), torch.sin(angles), torch.cos(angles)))

    def _scalar_features(
        self,
        candidate: CandidatePlan,
        *,
        reference: torch.Tensor,
    ) -> torch.Tensor:
        anchor = candidate.anchor_result
        counts = reference.new_tensor(
            (
                len(anchor.associated_rcsd_node_refs),
                len(anchor.associated_rcsd_road_refs),
                len(candidate.surface_plan.selected_rcsdintersection_refs),
                len(candidate.surface_plan.virtual_member_refs),
                len(anchor.node_equivalence_classes),
                len(anchor.road_break_operations),
                sum(len(operation.fractions) for operation in anchor.road_break_operations),
                len(candidate.referenced_objects),
            )
        ).log1p()
        device = reference.device
        return torch.cat(
            (
                self._one_hot(
                    candidate.step1_drivezone_state,
                    Step1DriveZoneState,
                    device=device,
                ),
                self._one_hot(candidate.surface_plan.mode, SurfaceMode, device=device),
                self._one_hot(candidate.anchor_result.state, AnchorState, device=device),
                self._one_hot(candidate.quality_state, QualityState, device=device),
                counts,
            )
        )

    @staticmethod
    def _pool(
        embeddings: Sequence[torch.Tensor],
        *,
        reference: torch.Tensor,
    ) -> torch.Tensor:
        return (
            torch.stack(tuple(embeddings)).mean(dim=0)
            if embeddings
            else reference.new_zeros((int(reference.shape[-1]),))
        )

    @staticmethod
    def _anchor_node_embedding(
        node_ref: AnchorNodeRef,
        *,
        local_embeddings: Mapping[ObjectRef, torch.Tensor],
        break_embeddings: Mapping[AnchorNodeRef, torch.Tensor],
    ) -> torch.Tensor:
        if node_ref.node_ref is not None:
            return local_embeddings[node_ref.node_ref]
        return break_embeddings[node_ref]

    def forward(
        self,
        *,
        encoded: EncodedStageBatch,
        conditioned_queries: torch.Tensor,
        candidate_bindings: Sequence[CandidateBinding],
    ) -> CompletePlanScoreOutput:
        if len(candidate_bindings) != len(encoded.junction_keys):
            raise JunctionPredictionError("candidate binding count differs from batch")
        plan_ids: list[str] = []
        plan_batch_indices: list[int] = []
        plan_inputs: list[torch.Tensor] = []
        for batch_index, binding in enumerate(candidate_bindings):
            if binding.junction_key != encoded.junction_keys[batch_index]:
                raise JunctionPredictionError("candidate binding identities are not aligned")
            binding.validate()
            local_embeddings = {
                ref: encoded.object_embeddings[index]
                for index, ref in enumerate(encoded.object_refs)
                if int(encoded.object_batch_indices[index]) == batch_index
            }
            for candidate in binding.plans:
                if not candidate.referenced_objects.issubset(local_embeddings):
                    raise JunctionPredictionError(
                        "bound candidate object is absent from Anchor view"
                    )
                surface_refs = (
                    candidate.surface_plan.selected_rcsdintersection_refs
                    + candidate.surface_plan.virtual_member_refs
                )
                surface_pool = self._pool(
                    tuple(local_embeddings[ref] for ref in surface_refs),
                    reference=conditioned_queries,
                )
                anchor_refs = (
                    candidate.anchor_result.associated_rcsd_node_refs
                    + candidate.anchor_result.associated_rcsd_road_refs
                )
                anchor_pool = self._pool(
                    tuple(local_embeddings[ref] for ref in anchor_refs),
                    reference=conditioned_queries,
                )
                break_points: list[torch.Tensor] = []
                break_embeddings: dict[AnchorNodeRef, torch.Tensor] = {}
                for operation in candidate.anchor_result.road_break_operations:
                    road_embedding = local_embeddings[operation.road_ref]
                    for break_rank, fraction in enumerate(operation.fractions):
                        point_embedding = self.break_point_encoder(
                            torch.cat(
                                (
                                    road_embedding,
                                    self._fraction_features(
                                        fraction,
                                        reference=road_embedding,
                                    ),
                                )
                            )
                        )
                        node_ref = AnchorNodeRef.road_break_point(
                            operation.road_ref,
                            break_rank,
                        )
                        break_points.append(point_embedding)
                        break_embeddings[node_ref] = point_embedding
                break_pool = self._pool(
                    break_points,
                    reference=conditioned_queries,
                )
                main_ref = candidate.anchor_result.selected_main_anchor
                main_pool = (
                    self._anchor_node_embedding(
                        main_ref,
                        local_embeddings=local_embeddings,
                        break_embeddings=break_embeddings,
                    )
                    if main_ref is not None
                    else conditioned_queries.new_zeros((self.hidden_dim,))
                )
                equivalence_groups: list[torch.Tensor] = []
                for group in candidate.anchor_result.node_equivalence_classes:
                    member_pool = self._pool(
                        tuple(
                            self._anchor_node_embedding(
                                node_ref,
                                local_embeddings=local_embeddings,
                                break_embeddings=break_embeddings,
                            )
                            for node_ref in group.node_refs
                        ),
                        reference=conditioned_queries,
                    )
                    group_size = member_pool.new_tensor(
                        (math.log1p(len(group.node_refs)),)
                    )
                    equivalence_groups.append(
                        self.equivalence_group_encoder(
                            torch.cat((member_pool, group_size))
                        )
                    )
                equivalence_pool = self._pool(
                    equivalence_groups,
                    reference=conditioned_queries,
                )
                scalar_embedding = self.scalar_projection(
                    self._scalar_features(candidate, reference=conditioned_queries)
                )
                plan_inputs.append(
                    torch.cat(
                        (
                            conditioned_queries[batch_index],
                            surface_pool,
                            anchor_pool,
                            break_pool,
                            main_pool,
                            equivalence_pool,
                            scalar_embedding,
                        )
                    )
                )
                plan_ids.append(candidate.plan_id)
                plan_batch_indices.append(batch_index)
        logits = (
            self.plan_head(torch.stack(plan_inputs)).squeeze(-1)
            if plan_inputs
            else conditioned_queries.new_zeros((0,))
        )
        return CompletePlanScoreOutput(
            plan_ids=tuple(plan_ids),
            plan_batch_indices=torch.tensor(
                plan_batch_indices,
                dtype=torch.long,
                device=conditioned_queries.device,
            ),
            logits=logits,
        )


class StagedMultiTaskHeads(nn.Module):
    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.step1_head = nn.Linear(hidden_dim, len(Step1DriveZoneState))
        self.step1_condition_embedding = nn.Embedding(
            len(Step1DriveZoneState), hidden_dim
        )
        self.surface_condition = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.surface_heads = SurfaceBranchHeads(hidden_dim)
        self.surface_mode_condition_embedding = nn.Embedding(
            len(SurfaceMode), hidden_dim
        )
        self.anchor_condition = nn.Sequential(
            nn.Linear(hidden_dim * 3, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.anchor_state_head = nn.Linear(hidden_dim, len(AnchorState))
        self.quality_head = nn.Linear(hidden_dim, len(QualityState))
        self.member_head = PointerSetHead(hidden_dim)
        self.main_anchor_head = ObjectPointerScorer(hidden_dim)
        self.node_pair_head = nn.Sequential(
            nn.Linear(hidden_dim * 4, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, 1),
        )
        self.break_head = RoadBreakSetHead(hidden_dim, max_break_points=4)
        self.complete_plan_scorer = CompletePlanScorer(hidden_dim)

    @staticmethod
    def _condition_indices(
        *,
        logits: torch.Tensor,
        provided: torch.Tensor | None,
        class_count: int,
        name: str,
    ) -> torch.Tensor:
        if provided is None:
            return logits.detach().argmax(dim=-1)
        normalized = provided.to(device=logits.device)
        if normalized.dtype != torch.long or tuple(normalized.shape) != (
            int(logits.shape[0]),
        ):
            raise JunctionPredictionError(
                f"{name} teacher condition must be a LongTensor with batch shape"
            )
        if len(normalized) and (
            int(normalized.min()) < 0 or int(normalized.max()) >= class_count
        ):
            raise JunctionPredictionError(f"{name} teacher condition is out of range")
        return normalized

    def forward(
        self,
        *,
        step1: EncodedStageBatch,
        surface: EncodedStageBatch,
        anchor: EncodedStageBatch,
        candidate_bindings: Sequence[CandidateBinding],
        step1_state_indices: torch.Tensor | None,
        surface_mode_indices: torch.Tensor | None,
    ) -> JunctionGraphSetRawOutput:
        if not (
            step1.junction_keys == surface.junction_keys == anchor.junction_keys
        ):
            raise JunctionPredictionError("staged head identities are not aligned")
        step1_logits = self.step1_head(step1.query_embeddings)
        conditioned_step1_indices = self._condition_indices(
            logits=step1_logits,
            provided=step1_state_indices,
            class_count=len(Step1DriveZoneState),
            name="Step1",
        )
        surface_queries = self.surface_condition(
            torch.cat(
                (
                    surface.query_embeddings,
                    self.step1_condition_embedding(conditioned_step1_indices),
                ),
                dim=-1,
            )
        )
        surface_stage_output = self.surface_heads(
            query_embeddings=surface_queries,
            object_embeddings=surface.object_embeddings,
            object_batch_indices=surface.object_batch_indices,
            object_refs=surface.object_refs,
        )
        anchor_member_output = self.surface_heads(
            query_embeddings=surface_queries,
            object_embeddings=anchor.object_embeddings,
            object_batch_indices=anchor.object_batch_indices,
            object_refs=anchor.object_refs,
        )
        conditioned_surface_mode_indices = self._condition_indices(
            logits=surface_stage_output.mode_logits,
            provided=surface_mode_indices,
            class_count=len(SurfaceMode),
            name="Surface",
        )
        conditioned_queries = self.anchor_condition(
            torch.cat(
                (
                    anchor.query_embeddings,
                    surface_queries,
                    self.surface_mode_condition_embedding(
                        conditioned_surface_mode_indices
                    ),
                ),
                dim=-1,
            )
        )
        member_output = self.member_head(
            query_embeddings=conditioned_queries,
            object_embeddings=anchor.object_embeddings,
            object_batch_indices=anchor.object_batch_indices,
            object_refs=anchor.object_refs,
            roles=frozenset({EvidenceRole.RCSD_NODE, EvidenceRole.RCSD_ROAD}),
        )
        main_output = self.main_anchor_head(
            query_embeddings=conditioned_queries,
            object_embeddings=anchor.object_embeddings,
            object_batch_indices=anchor.object_batch_indices,
            object_refs=anchor.object_refs,
            roles=frozenset({EvidenceRole.RCSD_NODE}),
        )
        main_refs = tuple(
            AnchorNodeRef.source_node(ref) for ref in main_output.object_refs
        )
        road_break_output = self.break_head(
            query_embeddings=conditioned_queries,
            object_embeddings=anchor.object_embeddings,
            object_batch_indices=anchor.object_batch_indices,
            object_refs=anchor.object_refs,
        )

        pair_refs: list[tuple[ObjectRef, ObjectRef]] = []
        pair_batches: list[int] = []
        pair_inputs: list[torch.Tensor] = []
        for batch_index in range(len(anchor.junction_keys)):
            node_indices = tuple(
                index
                for index, ref in enumerate(anchor.object_refs)
                if ref.role == EvidenceRole.RCSD_NODE
                and int(anchor.object_batch_indices[index]) == batch_index
            )
            for left, right in combinations(node_indices, 2):
                left_embedding = anchor.object_embeddings[left]
                right_embedding = anchor.object_embeddings[right]
                pair_refs.append((anchor.object_refs[left], anchor.object_refs[right]))
                pair_batches.append(batch_index)
                pair_inputs.append(
                    torch.cat(
                        (
                            conditioned_queries[batch_index],
                            left_embedding,
                            right_embedding,
                            torch.abs(left_embedding - right_embedding),
                        )
                    )
                )
        pair_logits = (
            self.node_pair_head(torch.stack(pair_inputs)).squeeze(-1)
            if pair_inputs
            else conditioned_queries.new_zeros((0,))
        )
        combined_surface_output = SurfaceHeadOutput(
            mode_logits=surface_stage_output.mode_logits,
            existing_object_logits=surface_stage_output.existing_object_logits,
            existing_object_refs=surface_stage_output.existing_object_refs,
            virtual_member_logits=anchor_member_output.virtual_member_logits,
            virtual_member_refs=anchor_member_output.virtual_member_refs,
            virtual_member_batch_indices=(
                anchor_member_output.virtual_member_batch_indices
            ),
            virtual_cardinality_logits=(
                anchor_member_output.virtual_cardinality_logits
            ),
            virtual_cardinality_valid_mask=(
                anchor_member_output.virtual_cardinality_valid_mask
            ),
        )
        return JunctionGraphSetRawOutput(
            junction_keys=anchor.junction_keys,
            step1_logits=step1_logits,
            conditioned_step1_indices=conditioned_step1_indices,
            surface=combined_surface_output,
            conditioned_surface_mode_indices=conditioned_surface_mode_indices,
            anchor_state_logits=self.anchor_state_head(conditioned_queries),
            quality_logits=self.quality_head(conditioned_queries),
            anchor_member_refs=member_output.object_refs,
            anchor_member_batch_indices=member_output.object_batch_indices,
            anchor_member_logits=member_output.logits,
            anchor_member_cardinality_logits=member_output.cardinality_logits,
            anchor_member_cardinality_valid_mask=(
                member_output.cardinality_valid_mask
            ),
            main_anchor_refs=main_refs,
            main_anchor_batch_indices=main_output.object_batch_indices,
            main_anchor_logits=main_output.logits,
            node_equivalence=PairScoreOutput(
                pair_refs=tuple(pair_refs),
                pair_batch_indices=torch.tensor(
                    pair_batches,
                    dtype=torch.long,
                    device=conditioned_queries.device,
                ),
                logits=pair_logits,
            ),
            road_break=road_break_output,
            complete_plan=self.complete_plan_scorer(
                encoded=anchor,
                conditioned_queries=conditioned_queries,
                candidate_bindings=candidate_bindings,
            ),
        )


class JunctionGraphSetModel(nn.Module):
    def __init__(self, *, hidden_dim: int = 384, dropout: float = 0.1) -> None:
        super().__init__()
        self.firewall = StageFirewall()
        self.encoder = RoleSeparatedGraphSetEncoder(
            hidden_dim=hidden_dim,
            dropout=dropout,
        )
        self.heads = StagedMultiTaskHeads(hidden_dim)

    @property
    def parameter_count(self) -> int:
        return sum(parameter.numel() for parameter in self.parameters())

    def forward(
        self,
        examples: Sequence[JunctionEvidenceExample],
        *,
        step1_state_indices: torch.Tensor | None = None,
        surface_mode_indices: torch.Tensor | None = None,
    ) -> JunctionGraphSetRawOutput:
        normalized = tuple(examples)
        return self.forward_stage_views(
            step1_views=tuple(
                self.firewall.build_view(example, EvidenceStage.STEP1)
                for example in normalized
            ),
            surface_views=tuple(
                self.firewall.build_view(example, EvidenceStage.SURFACE)
                for example in normalized
            ),
            anchor_views=tuple(
                self.firewall.build_view(example, EvidenceStage.ANCHOR)
                for example in normalized
            ),
            candidate_bindings=tuple(
                example.candidate_binding for example in normalized
            ),
            step1_state_indices=step1_state_indices,
            surface_mode_indices=surface_mode_indices,
        )

    def forward_stage_views(
        self,
        *,
        step1_views: Sequence[StageEvidenceView],
        surface_views: Sequence[StageEvidenceView],
        anchor_views: Sequence[StageEvidenceView],
        candidate_bindings: Sequence[CandidateBinding],
        step1_state_indices: torch.Tensor | None = None,
        surface_mode_indices: torch.Tensor | None = None,
    ) -> JunctionGraphSetRawOutput:
        """Forward prebuilt firewall views without rebuilding their audit hashes."""

        normalized_step1 = tuple(step1_views)
        normalized_surface = tuple(surface_views)
        normalized_anchor = tuple(anchor_views)
        normalized_bindings = tuple(candidate_bindings)
        if not (
            len(normalized_step1)
            == len(normalized_surface)
            == len(normalized_anchor)
            == len(normalized_bindings)
        ):
            raise JunctionPredictionError("cached stage-view batch sizes are not aligned")
        step1 = self.encoder(normalized_step1)
        surface = self.encoder(normalized_surface)
        anchor = self.encoder(normalized_anchor)
        return self.heads(
            step1=step1,
            surface=surface,
            anchor=anchor,
            candidate_bindings=normalized_bindings,
            step1_state_indices=step1_state_indices,
            surface_mode_indices=surface_mode_indices,
        )


@dataclass(frozen=True)
class PairConstraint:
    left: ObjectRef
    right: ObjectRef
    state: ConstraintState
    weight: float

    def validate(self) -> None:
        if self.left == self.right or any(
            ref.role != EvidenceRole.RCSD_NODE for ref in (self.left, self.right)
        ):
            raise JunctionPredictionError(
                "Node-equivalence constraint requires two different RCSD Nodes"
            )
        if not math.isfinite(self.weight) or self.weight < 0.0:
            raise JunctionPredictionError("Node-equivalence weight is negative")
        if (
            self.state in {ConstraintState.UNKNOWN, ConstraintState.REVIEW}
            and self.weight != 0.0
        ):
            raise JunctionPredictionError(
                "UNKNOWN/REVIEW Node-equivalence constraint must have zero weight"
            )


@dataclass(frozen=True)
class RoadBreakTarget:
    road_ref: ObjectRef
    present: bool
    fraction: float | None
    weight: float

    def validate(self) -> None:
        if self.road_ref.role != EvidenceRole.RCSD_ROAD:
            raise JunctionPredictionError("Road-break target must refer to an RCSD Road")
        if not math.isfinite(self.weight) or self.weight < 0.0:
            raise JunctionPredictionError("Road-break weight is negative")
        if not self.present and self.fraction is not None:
            raise JunctionPredictionError("absent Road-break target cannot carry a fraction")
        if self.fraction is not None and (
            not math.isfinite(self.fraction) or not 0.0 < self.fraction < 1.0
        ):
            raise JunctionPredictionError("Road-break fraction must be within (0, 1)")


@dataclass(frozen=True)
class RoadBreakSetTarget:
    road_ref: ObjectRef
    fractions: tuple[float, ...]
    weight: float

    def validate(self) -> None:
        if self.road_ref.role != EvidenceRole.RCSD_ROAD:
            raise JunctionPredictionError(
                "Road-break set target must refer to an RCSD Road"
            )
        if not math.isfinite(self.weight) or self.weight < 0.0:
            raise JunctionPredictionError("Road-break set weight is negative")
        normalized = tuple(float(value) for value in self.fractions)
        if tuple(sorted(set(normalized))) != normalized:
            raise JunctionPredictionError(
                "Road-break set fractions must be unique and sorted"
            )
        if any(
            not math.isfinite(value) or not 0.0 < value < 1.0
            for value in normalized
        ):
            raise JunctionPredictionError(
                "Road-break set fraction must be within (0, 1)"
            )


@dataclass(frozen=True)
class JunctionTrainingOverlay:
    junction_key: str
    source_weight: float
    step1_acceptable_indices: tuple[int, ...] = ()
    surface_mode_acceptable_indices: tuple[int, ...] = ()
    anchor_state_acceptable_indices: tuple[int, ...] = ()
    quality_acceptable_indices: tuple[int, ...] = ()
    acceptable_complete_plan_ids: tuple[str, ...] = ()
    virtual_surface_constraints: tuple[SurfaceConstraint, ...] = ()
    virtual_surface_cardinality_target: int | None = None
    anchor_member_constraints: tuple[SurfaceConstraint, ...] = ()
    anchor_member_cardinality_target: int | None = None
    acceptable_main_anchor_refs: tuple[AnchorNodeRef, ...] = ()
    pair_constraints: tuple[PairConstraint, ...] = ()
    road_break_targets: tuple[RoadBreakTarget, ...] = ()
    road_break_set_targets: tuple[RoadBreakSetTarget, ...] = ()


def _class_loss(
    logits: torch.Tensor,
    acceptable: Sequence[Sequence[int]],
    weights: torch.Tensor,
) -> torch.Tensor:
    return acceptable_set_cross_entropy(logits, acceptable, weights)


def _grouped_object_loss(
    *,
    logits: torch.Tensor,
    refs: Sequence[ObjectRef],
    batch_indices: torch.Tensor,
    overlays: Sequence[JunctionTrainingOverlay],
    constraints_getter,
) -> torch.Tensor:
    terms: list[torch.Tensor] = []
    weights: list[float] = []
    for batch_index, overlay in enumerate(overlays):
        indices = tuple(
            index
            for index in range(len(refs))
            if int(batch_indices[index]) == batch_index
        )
        if not indices:
            continue
        index_tensor = torch.tensor(indices, dtype=torch.long, device=logits.device)
        local_refs = tuple(refs[index] for index in indices)
        constraints = constraints_getter(overlay)
        local_loss = masked_tristate_member_loss(
            logits[index_tensor], local_refs, constraints
        )
        if constraints:
            terms.append(local_loss * overlay.source_weight)
            weights.append(overlay.source_weight)
    if not terms:
        return logits.sum() * 0.0
    return torch.stack(terms).sum() / max(sum(weights), 1e-12)


def _cardinality_loss(
    logits: torch.Tensor,
    valid_mask: torch.Tensor,
    overlays: Sequence[JunctionTrainingOverlay],
    *,
    target_getter,
) -> torch.Tensor:
    if logits.ndim != 2 or valid_mask.shape != logits.shape:
        raise JunctionPredictionError("cardinality logits/mask shape is invalid")
    if int(logits.shape[0]) != len(overlays):
        raise JunctionPredictionError("cardinality batch differs from overlays")
    terms: list[torch.Tensor] = []
    weights: list[float] = []
    for batch_index, overlay in enumerate(overlays):
        target = target_getter(overlay)
        if target is None or overlay.source_weight <= 0.0:
            continue
        if int(target) < 0:
            raise JunctionPredictionError("set-cardinality target is negative")
        if int(target) >= int(logits.shape[1]) or not bool(
            valid_mask[batch_index, int(target)]
        ):
            raise JunctionPredictionError(
                "set-cardinality target exceeds the legal candidate count"
            )
        local_logits = logits[batch_index].masked_fill(
            ~valid_mask[batch_index],
            -torch.inf,
        )
        terms.append(
            functional.cross_entropy(
                local_logits.unsqueeze(0),
                torch.tensor(
                    (int(target),),
                    dtype=torch.long,
                    device=logits.device,
                ),
                reduction="none",
            )
            .squeeze(0)
            * overlay.source_weight
        )
        weights.append(overlay.source_weight)
    if not terms:
        return logits.masked_fill(~valid_mask, 0.0).sum() * 0.0
    return torch.stack(terms).sum() / max(sum(weights), 1e-12)


def _required_coverage_ranking_loss(
    *,
    logits: torch.Tensor,
    refs: Sequence[ObjectRef],
    batch_indices: torch.Tensor,
    overlays: Sequence[JunctionTrainingOverlay],
    constraints_getter,
    cardinality_getter,
    margin: float = 1.0,
) -> torch.Tensor:
    """Keep every REQUIRED object ahead of unresolved pointer competitors.

    UNKNOWN, REVIEW, and absent constraints remain outside the binary member
    target.  They only compete in the relative ranking needed to guarantee
    REQUIRED recall under the supervised top-k cardinality decoder.
    """

    terms: list[torch.Tensor] = []
    weights: list[float] = []
    for batch_index, overlay in enumerate(overlays):
        target_count = cardinality_getter(overlay)
        if target_count is None or overlay.source_weight <= 0.0:
            continue
        required_refs = {
            constraint.object_ref
            for constraint in constraints_getter(overlay)
            if constraint.state == ConstraintState.REQUIRED
        }
        if int(target_count) < len(required_refs):
            raise JunctionPredictionError(
                "set cardinality is smaller than REQUIRED object count"
            )
        if not required_refs:
            continue
        local_indices = tuple(
            index
            for index, ref in enumerate(refs)
            if int(batch_indices[index]) == batch_index
        )
        required_indices = tuple(
            index for index in local_indices if refs[index] in required_refs
        )
        if len(required_indices) != len(required_refs):
            raise JunctionPredictionError(
                "REQUIRED pointer object is absent from the candidate domain"
            )
        competitor_indices = tuple(
            index for index in local_indices if refs[index] not in required_refs
        )
        if not competitor_indices:
            continue
        required_tensor = torch.tensor(
            required_indices,
            dtype=torch.long,
            device=logits.device,
        )
        competitor_tensor = torch.tensor(
            competitor_indices,
            dtype=torch.long,
            device=logits.device,
        )
        pairwise_gap = (
            logits[competitor_tensor].unsqueeze(1)
            - logits[required_tensor].unsqueeze(0)
            + margin
        )
        terms.append(
            functional.softplus(pairwise_gap).mean() * overlay.source_weight
        )
        weights.append(overlay.source_weight)
    if not terms:
        return logits.sum() * 0.0
    return torch.stack(terms).sum() / max(sum(weights), 1e-12)


def compute_multitask_loss(
    output: JunctionGraphSetRawOutput,
    overlays: Sequence[JunctionTrainingOverlay],
) -> Mapping[str, torch.Tensor]:
    normalized = tuple(overlays)
    if tuple(overlay.junction_key for overlay in normalized) != output.junction_keys:
        raise JunctionPredictionError("training overlays are not aligned to model output")
    weights = output.step1_logits.new_tensor(
        [overlay.source_weight for overlay in normalized]
    )
    for overlay in normalized:
        if overlay.source_weight not in {0.0, 0.7, 1.0}:
            raise JunctionPredictionError("source weight must be 0, 0.7, or 1.0")
    losses: dict[str, torch.Tensor] = {
        "step1": _class_loss(
            output.step1_logits,
            [overlay.step1_acceptable_indices for overlay in normalized],
            weights,
        ),
        "surface_mode": _class_loss(
            output.surface.mode_logits,
            [overlay.surface_mode_acceptable_indices for overlay in normalized],
            weights,
        ),
        "anchor_state": _class_loss(
            output.anchor_state_logits,
            [overlay.anchor_state_acceptable_indices for overlay in normalized],
            weights,
        ),
        "quality": _class_loss(
            output.quality_logits,
            [overlay.quality_acceptable_indices for overlay in normalized],
            weights,
        ),
    }
    losses["virtual_surface_member"] = _grouped_object_loss(
        logits=output.surface.virtual_member_logits,
        refs=output.surface.virtual_member_refs,
        batch_indices=output.surface.virtual_member_batch_indices,
        overlays=normalized,
        constraints_getter=lambda overlay: overlay.virtual_surface_constraints,
    )
    losses["virtual_surface_cardinality"] = _cardinality_loss(
        output.surface.virtual_cardinality_logits,
        output.surface.virtual_cardinality_valid_mask,
        normalized,
        target_getter=lambda overlay: overlay.virtual_surface_cardinality_target,
    )
    losses["virtual_surface_required_coverage"] = _required_coverage_ranking_loss(
        logits=output.surface.virtual_member_logits,
        refs=output.surface.virtual_member_refs,
        batch_indices=output.surface.virtual_member_batch_indices,
        overlays=normalized,
        constraints_getter=lambda overlay: overlay.virtual_surface_constraints,
        cardinality_getter=lambda overlay: overlay.virtual_surface_cardinality_target,
    )
    losses["anchor_member"] = _grouped_object_loss(
        logits=output.anchor_member_logits,
        refs=output.anchor_member_refs,
        batch_indices=output.anchor_member_batch_indices,
        overlays=normalized,
        constraints_getter=lambda overlay: overlay.anchor_member_constraints,
    )
    losses["anchor_member_cardinality"] = _cardinality_loss(
        output.anchor_member_cardinality_logits,
        output.anchor_member_cardinality_valid_mask,
        normalized,
        target_getter=lambda overlay: overlay.anchor_member_cardinality_target,
    )

    main_terms: list[torch.Tensor] = []
    main_weights: list[float] = []
    for batch_index, overlay in enumerate(normalized):
        if not overlay.acceptable_main_anchor_refs or overlay.source_weight <= 0.0:
            continue
        indices = tuple(
            index
            for index in range(len(output.main_anchor_refs))
            if int(output.main_anchor_batch_indices[index]) == batch_index
        )
        if not indices:
            continue
        local_refs = tuple(output.main_anchor_refs[index] for index in indices)
        acceptable_indices = tuple(
            index
            for index, ref in enumerate(local_refs)
            if ref in overlay.acceptable_main_anchor_refs
        )
        if not acceptable_indices:
            raise JunctionPredictionError("acceptable main anchor is not in candidate refs")
        index_tensor = torch.tensor(indices, dtype=torch.long, device=weights.device)
        local_loss = acceptable_set_cross_entropy(
            output.main_anchor_logits[index_tensor].unsqueeze(0),
            (acceptable_indices,),
            weights.new_tensor([overlay.source_weight]),
        )
        main_terms.append(local_loss * overlay.source_weight)
        main_weights.append(overlay.source_weight)
    losses["main_anchor"] = (
        torch.stack(main_terms).sum() / max(sum(main_weights), 1e-12)
        if main_terms
        else output.main_anchor_logits.sum() * 0.0
    )

    pair_constraint_by_key: dict[tuple[int, frozenset[ObjectRef]], PairConstraint] = {}
    for batch_index, overlay in enumerate(normalized):
        for constraint in overlay.pair_constraints:
            constraint.validate()
            key = (batch_index, frozenset((constraint.left, constraint.right)))
            if key in pair_constraint_by_key:
                raise JunctionPredictionError("duplicate Node-equivalence constraint")
            pair_constraint_by_key[key] = constraint
    pair_terms: list[torch.Tensor] = []
    pair_weights: list[float] = []
    for index, pair in enumerate(output.node_equivalence.pair_refs):
        batch_index = int(output.node_equivalence.pair_batch_indices[index])
        constraint = pair_constraint_by_key.get((batch_index, frozenset(pair)))
        if constraint is None or constraint.state in {
            ConstraintState.UNKNOWN,
            ConstraintState.REVIEW,
        }:
            continue
        target = 1.0 if constraint.state == ConstraintState.REQUIRED else 0.0
        weight = constraint.weight * normalized[batch_index].source_weight
        pair_terms.append(
            functional.binary_cross_entropy_with_logits(
                output.node_equivalence.logits[index],
                output.node_equivalence.logits.new_tensor(target),
                reduction="none",
            )
            * weight
        )
        pair_weights.append(weight)
    losses["node_equivalence"] = (
        torch.stack(pair_terms).sum() / max(sum(pair_weights), 1e-12)
        if pair_terms
        else output.node_equivalence.logits.sum() * 0.0
    )

    break_target_by_key: dict[tuple[int, ObjectRef], RoadBreakTarget] = {}
    for batch_index, overlay in enumerate(normalized):
        for target in overlay.road_break_targets:
            target.validate()
            key = (batch_index, target.road_ref)
            if key in break_target_by_key:
                raise JunctionPredictionError("duplicate Road-break target")
            break_target_by_key[key] = target
    break_terms: list[torch.Tensor] = []
    fraction_terms: list[torch.Tensor] = []
    break_weights: list[float] = []
    fraction_weights: list[float] = []
    for index, road_ref in enumerate(output.road_break.road_refs):
        batch_index = int(output.road_break.road_batch_indices[index])
        target = break_target_by_key.get((batch_index, road_ref))
        if target is None:
            continue
        weight = target.weight * normalized[batch_index].source_weight
        break_terms.append(
            functional.binary_cross_entropy_with_logits(
                output.road_break.presence_logits[index],
                output.road_break.presence_logits.new_tensor(float(target.present)),
                reduction="none",
            )
            * weight
        )
        break_weights.append(weight)
        if target.present and target.fraction is not None:
            fraction_terms.append(
                functional.smooth_l1_loss(
                    output.road_break.fractions[index],
                    output.road_break.fractions.new_tensor(target.fraction),
                    reduction="none",
                )
                * weight
            )
            fraction_weights.append(weight)
    losses["road_break_presence"] = (
        torch.stack(break_terms).sum() / max(sum(break_weights), 1e-12)
        if break_terms
        else output.road_break.presence_logits.sum() * 0.0
    )
    losses["road_break_fraction"] = (
        torch.stack(fraction_terms).sum() / max(sum(fraction_weights), 1e-12)
        if fraction_terms
        else output.road_break.fractions.sum() * 0.0
    )
    break_set_by_key: dict[tuple[int, ObjectRef], RoadBreakSetTarget] = {}
    for batch_index, overlay in enumerate(normalized):
        for target in overlay.road_break_set_targets:
            target.validate()
            key = (batch_index, target.road_ref)
            if key in break_set_by_key:
                raise JunctionPredictionError("duplicate Road-break set target")
            break_set_by_key[key] = target
    count_terms: list[torch.Tensor] = []
    count_weights: list[float] = []
    set_fraction_terms: list[torch.Tensor] = []
    set_fraction_weights: list[float] = []
    for index, road_ref in enumerate(output.road_break.road_refs):
        batch_index = int(output.road_break.road_batch_indices[index])
        target = break_set_by_key.get((batch_index, road_ref))
        if target is None:
            continue
        weight = target.weight * normalized[batch_index].source_weight
        target_count = len(target.fractions)
        count_class = (
            target_count
            if target_count <= output.road_break.max_break_points
            else output.road_break.overflow_class_index
        )
        count_terms.append(
            functional.cross_entropy(
                output.road_break.count_logits[index].unsqueeze(0),
                torch.tensor(
                    (count_class,),
                    dtype=torch.long,
                    device=output.road_break.count_logits.device,
                ),
                reduction="none",
            ).squeeze(0)
            * weight
        )
        count_weights.append(weight)
        if 0 < target_count <= output.road_break.max_break_points:
            target_tensor = output.road_break.fraction_slots.new_tensor(
                target.fractions
            )
            set_fraction_terms.append(
                functional.smooth_l1_loss(
                    output.road_break.fraction_slots[index, :target_count],
                    target_tensor,
                    reduction="mean",
                )
                * weight
            )
            set_fraction_weights.append(weight)
    losses["road_break_count"] = (
        torch.stack(count_terms).sum() / max(sum(count_weights), 1e-12)
        if count_terms
        else output.road_break.count_logits.sum() * 0.0
    )
    losses["road_break_set_fraction"] = (
        torch.stack(set_fraction_terms).sum()
        / max(sum(set_fraction_weights), 1e-12)
        if set_fraction_terms
        else output.road_break.fraction_slots.sum() * 0.0
    )
    plan_terms: list[torch.Tensor] = []
    plan_weights: list[float] = []
    for batch_index, overlay in enumerate(normalized):
        if not overlay.acceptable_complete_plan_ids or overlay.source_weight <= 0.0:
            continue
        indices = tuple(
            index
            for index in range(len(output.complete_plan.plan_ids))
            if int(output.complete_plan.plan_batch_indices[index]) == batch_index
        )
        local_plan_ids = tuple(output.complete_plan.plan_ids[index] for index in indices)
        if len(set(local_plan_ids)) != len(local_plan_ids):
            raise JunctionPredictionError("duplicate complete plan IDs in one Junction")
        acceptable_indices = tuple(
            index
            for index, plan_id in enumerate(local_plan_ids)
            if plan_id in overlay.acceptable_complete_plan_ids
        )
        if len(acceptable_indices) != len(set(overlay.acceptable_complete_plan_ids)):
            raise JunctionPredictionError("acceptable complete plan is not bound")
        index_tensor = torch.tensor(indices, dtype=torch.long, device=weights.device)
        local_loss = acceptable_set_cross_entropy(
            output.complete_plan.logits[index_tensor].unsqueeze(0),
            (acceptable_indices,),
            weights.new_tensor([overlay.source_weight]),
        )
        plan_terms.append(local_loss * overlay.source_weight)
        plan_weights.append(overlay.source_weight)
    losses["complete_plan"] = (
        torch.stack(plan_terms).sum() / max(sum(plan_weights), 1e-12)
        if plan_terms
        else output.complete_plan.logits.sum() * 0.0
    )
    losses["total"] = torch.stack(tuple(losses.values())).sum()
    return losses
