from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_anchor_evidence import (
    ANCHOR_ARM_FEATURE_DIM,
    ANCHOR_MEMBER_LOCAL_FEATURE_DIM,
    ANCHOR_MEMBER_RELATION_DIM,
)
from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_network import (
    TargetABatchTensors,
)


ANCHOR_RELATION_STATES = (
    "success_required_rcsd_junction",
    "rcsd_present_not_junction",
    "no_related_rcsd",
)
ANCHOR_OBJECT_TYPES = ("NODE", "ROAD")
ANCHOR_STRUCTURAL_MEMBER_FEATURE_DIM = (
    ANCHOR_MEMBER_LOCAL_FEATURE_DIM
    + 2 * ANCHOR_ARM_FEATURE_DIM
    + 1
    + len(ANCHOR_OBJECT_TYPES)
)


class AnchorRelationState(IntEnum):
    SUCCESS_REQUIRED_RCSD_JUNCTION = 0
    RCSD_PRESENT_NOT_JUNCTION = 1
    NO_RELATED_RCSD = 2


class AnchorObjectType(IntEnum):
    NODE = 0
    ROAD = 1


@dataclass(frozen=True)
class TargetAAnchorStructuralConfig:
    object_feature_dim: int
    hidden_dim: int = 128
    num_heads: int = 4
    feedforward_dim: int = 384
    graph_layers: int = 3
    set_layers: int = 2
    dropout: float = 0.10
    max_cardinality: int = 130

    def validate(self) -> None:
        if self.object_feature_dim < 1:
            raise ValueError("anchor object feature dimension must be positive")
        if self.hidden_dim < 1:
            raise ValueError("anchor hidden dimension must be positive")
        if self.num_heads < 1 or self.hidden_dim % self.num_heads:
            raise ValueError("anchor hidden dimension must divide by heads")
        if self.feedforward_dim < self.hidden_dim:
            raise ValueError("anchor feedforward dimension is too small")
        if self.graph_layers < 1 or self.set_layers < 1:
            raise ValueError("anchor structural decoder requires layers")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("anchor dropout must be in [0, 1)")
        if self.max_cardinality < 2:
            raise ValueError("anchor max cardinality must be at least two")


@dataclass(frozen=True)
class TargetAAnchorStructuralBatch:
    """Inference-time structural evidence; no label or terminal-state fields."""

    object_features: torch.Tensor
    member_features: torch.Tensor
    member_mask: torch.Tensor
    member_is_road: torch.Tensor
    edge_src: torch.Tensor
    edge_dst: torch.Tensor
    edge_features: torch.Tensor

    def validate(self, *, object_feature_dim: int) -> None:
        if (
            self.object_features.ndim != 2
            or self.object_features.shape[-1] != object_feature_dim
        ):
            raise ValueError("anchor object feature shape differs")
        if (
            self.member_features.ndim != 3
            or self.member_features.shape[-1]
            != ANCHOR_STRUCTURAL_MEMBER_FEATURE_DIM
        ):
            raise ValueError("anchor member feature shape differs")
        batch_size, member_count = self.member_features.shape[:2]
        if self.object_features.shape[0] != batch_size:
            raise ValueError("anchor object/member batch sizes differ")
        expected_member_shape = (batch_size, member_count)
        if (
            self.member_mask.shape != expected_member_shape
            or self.member_mask.dtype is not torch.bool
        ):
            raise ValueError("anchor member mask shape or dtype differs")
        if (
            self.member_is_road.shape != expected_member_shape
            or self.member_is_road.dtype is not torch.bool
        ):
            raise ValueError("anchor member type shape or dtype differs")
        if bool((~self.member_mask.any(dim=-1)).any()):
            raise ValueError("anchor structural input has no member")
        if (
            self.edge_src.ndim != 1
            or self.edge_dst.ndim != 1
            or self.edge_src.dtype is not torch.long
            or self.edge_dst.dtype is not torch.long
            or self.edge_src.shape != self.edge_dst.shape
        ):
            raise ValueError("anchor relation index shape or dtype differs")
        if self.edge_features.shape != (
            self.edge_src.numel(),
            ANCHOR_MEMBER_RELATION_DIM,
        ):
            raise ValueError("anchor relation feature shape differs")
        if self.edge_src.numel():
            flat_size = batch_size * member_count
            if bool(
                (
                    (self.edge_src < 0)
                    | (self.edge_src >= flat_size)
                    | (self.edge_dst < 0)
                    | (self.edge_dst >= flat_size)
                ).any()
            ):
                raise ValueError("anchor relation index is outside the batch")
            flat_mask = self.member_mask.reshape(-1)
            if bool(
                (
                    ~flat_mask[self.edge_src]
                    | ~flat_mask[self.edge_dst]
                ).any()
            ):
                raise ValueError("anchor relation references a padded member")
        if not bool(torch.isfinite(self.object_features).all()):
            raise ValueError("anchor object feature is not finite")
        if not bool(torch.isfinite(self.member_features).all()):
            raise ValueError("anchor member feature is not finite")
        if not bool(torch.isfinite(self.edge_features).all()):
            raise ValueError("anchor relation feature is not finite")

    def to(self, device: torch.device) -> "TargetAAnchorStructuralBatch":
        return TargetAAnchorStructuralBatch(
            **{
                name: value.to(device)
                for name, value in self.__dict__.items()
            }
        )


@dataclass(frozen=True)
class TargetAAnchorStructuralOutput:
    relation_logits: torch.Tensor
    object_type_logits: torch.Tensor
    cardinality_logits: torch.Tensor
    ordinal_cardinality_logits: torch.Tensor
    member_logits: torch.Tensor
    decision_context: torch.Tensor


@dataclass(frozen=True)
class TargetAAnchorStructuralJointOutput:
    relation_logits: torch.Tensor
    object_type_logits: torch.Tensor
    cardinality_logits: torch.Tensor
    ordinal_cardinality_logits: torch.Tensor
    member_logits: torch.Tensor
    decision_context: torch.Tensor


class _GraphMessageBlock(nn.Module):
    def __init__(self, hidden_dim: int) -> None:
        super().__init__()
        self.message = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.update = nn.Sequential(
            nn.Linear(hidden_dim * 2, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, hidden_dim),
        )
        self.norm = nn.LayerNorm(hidden_dim)

    def forward(
        self,
        values: torch.Tensor,
        edge_values: torch.Tensor,
        edge_src: torch.Tensor,
        edge_dst: torch.Tensor,
    ) -> torch.Tensor:
        if edge_src.numel() == 0:
            return values
        flat = values.reshape(-1, values.shape[-1])
        messages = self.message(
            torch.cat((flat[edge_src], edge_values), dim=-1)
        )
        aggregated = torch.zeros_like(flat)
        aggregated.index_add_(0, edge_dst, messages)
        counts = torch.zeros(
            flat.shape[0],
            1,
            dtype=flat.dtype,
            device=flat.device,
        )
        counts.index_add_(
            0,
            edge_dst,
            torch.ones(
                edge_dst.shape[0],
                1,
                dtype=flat.dtype,
                device=flat.device,
            ),
        )
        aggregated = aggregated / counts.clamp_min(1.0)
        updated = self.update(torch.cat((flat, aggregated), dim=-1))
        return self.norm(flat + updated).reshape_as(values)


class TargetAAnchorStructuralDecoder(nn.Module):
    """Jointly decode anchor evidence role, object type and exact member set."""

    def __init__(self, config: TargetAAnchorStructuralConfig) -> None:
        super().__init__()
        config.validate()
        self.config = config
        hidden_dim = config.hidden_dim
        self.object_stem = nn.Sequential(
            nn.Linear(config.object_feature_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.member_stem = nn.Sequential(
            nn.Linear(ANCHOR_STRUCTURAL_MEMBER_FEATURE_DIM, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.edge_stem = nn.Sequential(
            nn.Linear(ANCHOR_MEMBER_RELATION_DIM, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
        )
        self.graph_blocks = nn.ModuleList(
            _GraphMessageBlock(hidden_dim)
            for _ in range(config.graph_layers)
        )
        layer = nn.TransformerEncoderLayer(
            d_model=hidden_dim,
            nhead=config.num_heads,
            dim_feedforward=config.feedforward_dim,
            dropout=config.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.set_encoder = nn.TransformerEncoder(
            layer,
            num_layers=config.set_layers,
            enable_nested_tensor=False,
        )
        self.node_pool = nn.Linear(hidden_dim, 1)
        self.road_pool = nn.Linear(hidden_dim, 1)
        self.global_pool = nn.Linear(hidden_dim, 1)
        fused_dim = hidden_dim + 3 * hidden_dim
        decision_dim = hidden_dim + len(ANCHOR_RELATION_STATES)
        typed_decision_dim = decision_dim + len(ANCHOR_OBJECT_TYPES)
        self.fusion = nn.Sequential(
            nn.Linear(fused_dim, hidden_dim),
            nn.GELU(),
            nn.LayerNorm(hidden_dim),
            nn.Dropout(config.dropout),
        )
        self.relation_head = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, len(ANCHOR_RELATION_STATES)),
        )
        self.object_type_head = nn.Sequential(
            nn.Linear(decision_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, len(ANCHOR_OBJECT_TYPES)),
        )
        self.cardinality_head = nn.Sequential(
            nn.Linear(typed_decision_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, config.max_cardinality),
        )
        self.ordinal_cardinality_head = nn.Sequential(
            nn.Linear(typed_decision_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, config.max_cardinality - 1),
        )
        self.member_head = nn.Sequential(
            nn.Linear(hidden_dim + typed_decision_dim, hidden_dim),
            nn.GELU(),
            nn.Linear(hidden_dim, 1),
        )

    def forward(
        self,
        batch: TargetAAnchorStructuralBatch,
    ) -> TargetAAnchorStructuralOutput:
        batch.validate(object_feature_dim=self.config.object_feature_dim)
        object_values = self.object_stem(batch.object_features)
        member_values = self.member_stem(batch.member_features)
        edge_values = self.edge_stem(batch.edge_features)
        for block in self.graph_blocks:
            member_values = block(
                member_values,
                edge_values,
                batch.edge_src,
                batch.edge_dst,
            )
            member_values = member_values.masked_fill(
                ~batch.member_mask.unsqueeze(-1),
                0.0,
            )
        member_values = self.set_encoder(
            member_values,
            src_key_padding_mask=~batch.member_mask,
        )
        member_values = member_values.masked_fill(
            ~batch.member_mask.unsqueeze(-1),
            0.0,
        )
        node_context = _attention_pool(
            member_values,
            self.node_pool,
            batch.member_mask & ~batch.member_is_road,
        )
        road_context = _attention_pool(
            member_values,
            self.road_pool,
            batch.member_mask & batch.member_is_road,
        )
        global_context = _attention_pool(
            member_values,
            self.global_pool,
            batch.member_mask,
        )
        fused = self.fusion(
            torch.cat(
                (
                    object_values,
                    node_context,
                    road_context,
                    global_context,
                ),
                dim=-1,
            )
        )
        relation_logits = self.relation_head(fused)
        relation_context = torch.softmax(relation_logits, dim=-1)
        decision_context = torch.cat(
            (fused, relation_context),
            dim=-1,
        )
        object_type_logits = self.object_type_head(decision_context)
        valid_object_types = torch.stack(
            (
                (batch.member_mask & ~batch.member_is_road).any(dim=-1),
                (batch.member_mask & batch.member_is_road).any(dim=-1),
            ),
            dim=-1,
        )
        object_type_logits = object_type_logits.masked_fill(
            ~valid_object_types,
            float("-inf"),
        )
        object_type_context = torch.softmax(
            object_type_logits,
            dim=-1,
        )
        typed_decision_context = torch.cat(
            (decision_context, object_type_context),
            dim=-1,
        )
        expanded = typed_decision_context.unsqueeze(1).expand(
            -1,
            member_values.shape[1],
            -1,
        )
        member_logits = self.member_head(
            torch.cat((member_values, expanded), dim=-1)
        ).squeeze(-1)
        member_logits = member_logits.masked_fill(
            ~batch.member_mask,
            float("-inf"),
        )
        return TargetAAnchorStructuralOutput(
            relation_logits=relation_logits,
            object_type_logits=object_type_logits,
            cardinality_logits=self.cardinality_head(
                typed_decision_context
            ),
            ordinal_cardinality_logits=(
                self.ordinal_cardinality_head(typed_decision_context)
            ),
            member_logits=member_logits,
            decision_context=decision_context,
        )


class TargetAAnchorStructuralJointHead(nn.Module):
    """Decode every anchor from the joint network's shared object encoder."""

    def __init__(self, config: TargetAAnchorStructuralConfig) -> None:
        super().__init__()
        self.decoder = TargetAAnchorStructuralDecoder(config)

    def forward(
        self,
        batch: TargetABatchTensors,
        shared_object_embeddings: torch.Tensor,
    ) -> TargetAAnchorStructuralJointOutput:
        if batch.anchor_member_mask is None:
            raise ValueError("joint anchor batch lacks an atomic member mask")
        group_mask = batch.anchor_member_mask.any(dim=-1)
        group_indices = group_mask.reshape(-1).nonzero(
            as_tuple=False
        ).flatten()
        if not group_indices.numel():
            raise ValueError("joint anchor batch has no valid anchor group")
        structural = build_anchor_structural_batch_from_joint(
            batch,
            shared_object_embeddings=shared_object_embeddings,
        )
        decoded = self.decoder(structural)
        batch_size, anchor_count, member_count = (
            batch.anchor_member_mask.shape
        )

        def scatter(
            values: torch.Tensor,
            *,
            fill_value: float,
        ) -> torch.Tensor:
            result = torch.full(
                (
                    batch_size * anchor_count,
                    *values.shape[1:],
                ),
                fill_value,
                dtype=values.dtype,
                device=values.device,
            ).index_copy(0, group_indices, values)
            return result.reshape(
                batch_size,
                anchor_count,
                *values.shape[1:],
            )

        return TargetAAnchorStructuralJointOutput(
            relation_logits=scatter(
                decoded.relation_logits,
                fill_value=0.0,
            ),
            object_type_logits=scatter(
                decoded.object_type_logits,
                fill_value=0.0,
            ),
            cardinality_logits=scatter(
                decoded.cardinality_logits,
                fill_value=0.0,
            ),
            ordinal_cardinality_logits=scatter(
                decoded.ordinal_cardinality_logits,
                fill_value=0.0,
            ),
            member_logits=scatter(
                decoded.member_logits,
                fill_value=0.0,
            ),
            decision_context=scatter(
                decoded.decision_context,
                fill_value=0.0,
            ),
        )


def build_anchor_structural_batch_from_joint(
    batch: TargetABatchTensors,
    *,
    shared_object_embeddings: torch.Tensor,
) -> TargetAAnchorStructuralBatch:
    """Adapt truth-free joint tensors without repeating feature-store reads."""
    required = (
        batch.anchor_member_mask,
        batch.anchor_member_is_road,
        batch.anchor_member_arm_features,
        batch.anchor_member_arm_mask,
        batch.anchor_member_local_features,
        batch.anchor_member_relation_features,
        batch.anchor_member_relation_mask,
    )
    if any(value is None for value in required):
        raise ValueError("joint anchor batch lacks structural evidence")
    member_mask = batch.anchor_member_mask
    member_is_road = batch.anchor_member_is_road
    arm_features = batch.anchor_member_arm_features
    arm_mask = batch.anchor_member_arm_mask
    local_features = batch.anchor_member_local_features
    relation_features = batch.anchor_member_relation_features
    relation_mask = batch.anchor_member_relation_mask
    if (
        member_mask is None
        or member_is_road is None
        or arm_features is None
        or arm_mask is None
        or local_features is None
        or relation_features is None
        or relation_mask is None
    ):
        raise AssertionError("joint anchor structural narrowing failed")
    if member_mask.ndim != 3:
        raise ValueError("joint anchor member mask must be [B, A, M]")
    batch_size, anchor_count, member_count = member_mask.shape
    group_mask = member_mask.any(dim=-1)
    valid_group_indices = group_mask.reshape(-1).nonzero(
        as_tuple=False
    ).flatten()
    if not valid_group_indices.numel():
        raise ValueError("joint anchor batch has no valid anchor group")
    if (
        member_is_road.shape != member_mask.shape
        or member_is_road.dtype is not torch.bool
    ):
        raise ValueError("joint anchor member type shape or dtype differs")
    if (
        local_features.shape
        != (*member_mask.shape, ANCHOR_MEMBER_LOCAL_FEATURE_DIM)
    ):
        raise ValueError("joint anchor local feature shape differs")
    if (
        arm_features.ndim != 5
        or arm_features.shape[:3] != member_mask.shape
        or arm_features.shape[-1] != ANCHOR_ARM_FEATURE_DIM
        or arm_mask.shape != arm_features.shape[:-1]
    ):
        raise ValueError("joint anchor arm feature shape differs")
    if (
        relation_features.shape
        != (
            batch_size,
            anchor_count,
            member_count,
            member_count,
            ANCHOR_MEMBER_RELATION_DIM,
        )
        or relation_mask.shape != relation_features.shape[:-1]
    ):
        raise ValueError("joint anchor relation feature shape differs")
    if (
        shared_object_embeddings.ndim != 3
        or shared_object_embeddings.shape[0] != batch_size
    ):
        raise ValueError("joint shared object embedding shape differs")
    if batch.anchor_object_indices.shape != (batch_size, anchor_count):
        raise ValueError("joint anchor object index shape differs")
    valid_object_indices = batch.anchor_object_indices[group_mask]
    if bool(
        (
            (valid_object_indices < 0)
            | (
                valid_object_indices
                >= shared_object_embeddings.shape[1]
            )
        ).any()
    ):
        raise ValueError("joint anchor object index is outside the batch")

    arm_count = arm_mask.sum(dim=3)
    arm_weights = arm_mask.unsqueeze(-1).to(arm_features.dtype)
    arm_mean = (
        (arm_features * arm_weights).sum(dim=3)
        / arm_count.unsqueeze(-1).clamp_min(1).to(arm_features.dtype)
    )
    minimum = torch.finfo(arm_features.dtype).min
    arm_maximum = arm_features.masked_fill(
        ~arm_mask.unsqueeze(-1),
        minimum,
    ).amax(dim=3)
    arm_maximum = torch.where(
        arm_count.unsqueeze(-1) > 0,
        arm_maximum,
        torch.zeros_like(arm_maximum),
    )
    normalized_arm_count = (
        arm_count.clamp_max(16).to(arm_features.dtype) / 16.0
    ).unsqueeze(-1)
    member_type = torch.stack(
        (
            ~member_is_road,
            member_is_road,
        ),
        dim=-1,
    ).to(arm_features.dtype)
    member_features = torch.cat(
        (
            local_features,
            arm_mean,
            arm_maximum,
            normalized_arm_count,
            member_type,
        ),
        dim=-1,
    )

    object_batch_indices = (
        valid_group_indices // anchor_count
    )
    anchor_objects = shared_object_embeddings[
        object_batch_indices,
        valid_object_indices,
    ]
    valid_relations = (
        relation_mask
        & member_mask.unsqueeze(-1)
        & member_mask.unsqueeze(-2)
    )
    relation_indices = valid_relations.nonzero(as_tuple=False)
    if relation_indices.numel():
        group_index = (
            relation_indices[:, 0] * anchor_count
            + relation_indices[:, 1]
        )
        compact_group_index = torch.full(
            (batch_size * anchor_count,),
            -1,
            dtype=torch.long,
            device=member_mask.device,
        )
        compact_group_index[valid_group_indices] = torch.arange(
            valid_group_indices.numel(),
            device=member_mask.device,
        )
        group_index = compact_group_index[group_index]
        edge_src = (
            group_index * member_count + relation_indices[:, 2]
        )
        edge_dst = (
            group_index * member_count + relation_indices[:, 3]
        )
        edge_features = relation_features[
            valid_relations
        ]
    else:
        edge_src = torch.zeros(
            0,
            dtype=torch.long,
            device=member_mask.device,
        )
        edge_dst = edge_src.clone()
        edge_features = relation_features.new_zeros(
            (0, ANCHOR_MEMBER_RELATION_DIM)
        )
    result = TargetAAnchorStructuralBatch(
        object_features=anchor_objects.reshape(
            valid_group_indices.numel(),
            -1,
        ),
        member_features=member_features.reshape(
            batch_size * anchor_count,
            member_count,
            ANCHOR_STRUCTURAL_MEMBER_FEATURE_DIM,
        )[valid_group_indices],
        member_mask=member_mask.reshape(
            batch_size * anchor_count,
            member_count,
        )[valid_group_indices],
        member_is_road=member_is_road.reshape(
            batch_size * anchor_count,
            member_count,
        )[valid_group_indices],
        edge_src=edge_src,
        edge_dst=edge_dst,
        edge_features=edge_features,
    )
    result.validate(
        object_feature_dim=shared_object_embeddings.shape[-1]
    )
    return result


@dataclass(frozen=True)
class AnchorMemberReleaseProposal:
    """A completed model proposal; the safety gate must not rewrite it."""

    anchor_id: str
    relation_state: str
    object_type: str
    member_ids: tuple[str, ...]

    def validate(self) -> None:
        if not self.anchor_id:
            raise ValueError("anchor release proposal requires an anchor ID")
        if self.relation_state not in ANCHOR_RELATION_STATES:
            raise ValueError("anchor release proposal relation state differs")
        if self.object_type not in ANCHOR_OBJECT_TYPES:
            raise ValueError("anchor release proposal object type differs")
        if not self.member_ids or len(set(self.member_ids)) != len(
            self.member_ids
        ):
            raise ValueError("anchor release proposal members are invalid")
        prefix = f"{self.object_type}:"
        if any(not member_id.startswith(prefix) for member_id in self.member_ids):
            raise ValueError("anchor release proposal mixes object types")


@dataclass(frozen=True)
class AnchorCardinalityGateDecision:
    accepted: bool
    reason: str
    proposal: AnchorMemberReleaseProposal
    release_cardinality: int
    expected_floor_cardinality: int


def ordinal_cardinality_probabilities(
    ordinal_logits: torch.Tensor,
) -> torch.Tensor:
    """Return monotonic P(cardinality >= k) without using labels."""
    if ordinal_logits.ndim != 2 or ordinal_logits.shape[-1] < 1:
        raise ValueError("anchor ordinal logits must be [B, K-1]")
    return torch.cummin(
        torch.sigmoid(ordinal_logits),
        dim=-1,
    ).values


def decode_threshold_cardinality(
    probabilities: torch.Tensor,
    *,
    threshold: float,
    available_cardinality: torch.Tensor,
) -> torch.Tensor:
    if probabilities.ndim != 2:
        raise ValueError("anchor cardinality probabilities must be [B, K-1]")
    if not 0.0 < threshold < 1.0:
        raise ValueError("anchor cardinality threshold must be in (0, 1)")
    if available_cardinality.shape != probabilities.shape[:1]:
        raise ValueError("anchor available cardinality shape differs")
    decoded = 1 + probabilities.ge(threshold).sum(dim=-1)
    return torch.minimum(
        decoded,
        available_cardinality.clamp_min(1),
    )


def decode_expected_floor_cardinality(
    probabilities: torch.Tensor,
    *,
    available_cardinality: torch.Tensor,
) -> torch.Tensor:
    if probabilities.ndim != 2:
        raise ValueError("anchor cardinality probabilities must be [B, K-1]")
    if available_cardinality.shape != probabilities.shape[:1]:
        raise ValueError("anchor available cardinality shape differs")
    decoded = (1.0 + probabilities.sum(dim=-1)).floor().to(torch.long)
    return torch.minimum(
        decoded,
        available_cardinality.clamp_min(1),
    )


def apply_anchor_cardinality_consistency_gate(
    proposal: AnchorMemberReleaseProposal,
    *,
    expected_floor_cardinality: int,
    upstream_accepted: bool,
) -> AnchorCardinalityGateDecision:
    """Only downgrade an existing proposal when two decoders disagree."""
    proposal.validate()
    if expected_floor_cardinality < 1:
        raise ValueError("anchor expected cardinality must be positive")
    release_cardinality = len(proposal.member_ids)
    if not upstream_accepted:
        return AnchorCardinalityGateDecision(
            accepted=False,
            reason="UPSTREAM_NOT_ACCEPTED",
            proposal=proposal,
            release_cardinality=release_cardinality,
            expected_floor_cardinality=expected_floor_cardinality,
        )
    accepted = release_cardinality == expected_floor_cardinality
    return AnchorCardinalityGateDecision(
        accepted=accepted,
        reason=(
            "CARDINALITY_DECODERS_AGREE"
            if accepted
            else "CARDINALITY_DECODER_DISAGREEMENT"
        ),
        proposal=proposal,
        release_cardinality=release_cardinality,
        expected_floor_cardinality=expected_floor_cardinality,
    )


def _attention_pool(
    values: torch.Tensor,
    scorer: nn.Linear,
    mask: torch.Tensor,
) -> torch.Tensor:
    valid = mask.any(dim=-1)
    minimum = torch.finfo(values.dtype).min
    logits = scorer(values).squeeze(-1).masked_fill(~mask, minimum)
    logits = torch.where(
        valid.unsqueeze(-1),
        logits,
        torch.zeros_like(logits),
    )
    weights = torch.softmax(logits, dim=-1) * mask.to(values.dtype)
    weights = weights / weights.sum(dim=-1, keepdim=True).clamp_min(1.0)
    return (values * weights.unsqueeze(-1)).sum(dim=1)


__all__ = [
    "ANCHOR_OBJECT_TYPES",
    "ANCHOR_RELATION_STATES",
    "ANCHOR_STRUCTURAL_MEMBER_FEATURE_DIM",
    "AnchorCardinalityGateDecision",
    "AnchorMemberReleaseProposal",
    "AnchorObjectType",
    "AnchorRelationState",
    "TargetAAnchorStructuralBatch",
    "TargetAAnchorStructuralConfig",
    "TargetAAnchorStructuralDecoder",
    "TargetAAnchorStructuralJointHead",
    "TargetAAnchorStructuralJointOutput",
    "TargetAAnchorStructuralOutput",
    "apply_anchor_cardinality_consistency_gate",
    "build_anchor_structural_batch_from_joint",
    "decode_expected_floor_cardinality",
    "decode_threshold_cardinality",
    "ordinal_cardinality_probabilities",
]
