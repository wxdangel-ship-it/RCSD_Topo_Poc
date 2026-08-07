from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

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


@dataclass(frozen=True)
class AnchorRoadSetConfig:
    """Conditional Road-set head used after the anchor type is locked."""

    feature_dim: int = 64
    hidden_dim: int = 128
    num_heads: int = 4
    set_layers: int = 2
    feedforward_dim: int = 384
    dropout: float = 0.10
    corridor_feature_start: int = 36
    corridor_feature_dim: int = 9
    use_explicit_corridor_boundary: bool = False
    cardinality_mode: str = "categorical"
    use_relation_messages: bool = False
    relation_message_layers: int = 1
    use_arm_coverage_boundary: bool = False
    use_geometric_arm_coverage: bool = False
    use_relation_degree_scaling: bool = False

    def validate(self) -> None:
        integer_values = (
            self.feature_dim,
            self.hidden_dim,
            self.num_heads,
            self.set_layers,
            self.feedforward_dim,
            self.corridor_feature_dim,
            self.relation_message_layers,
        )
        if min(integer_values) <= 0:
            raise ValueError("anchor Road-set dimensions must be positive")
        if self.hidden_dim % self.num_heads:
            raise ValueError(
                "anchor Road-set hidden_dim must divide num_heads"
            )
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("anchor Road-set dropout must be in [0, 1)")
        if (
            self.corridor_feature_start < 0
            or self.corridor_feature_start + self.corridor_feature_dim
            > self.feature_dim
        ):
            raise ValueError(
                "anchor Road-set corridor feature slice is invalid"
            )
        if self.cardinality_mode not in {"categorical", "ordinal"}:
            raise ValueError(
                "anchor Road-set cardinality_mode must be categorical or ordinal"
            )


@dataclass(frozen=True)
class AnchorRoadSetSelection:
    selected_members: torch.Tensor
    cardinality: torch.Tensor
    cardinality_probability: torch.Tensor
    minimum_included_probability: torch.Tensor
    maximum_excluded_probability: torch.Tensor
    inclusion_margin: torch.Tensor
    confidence: torch.Tensor


class AnchorRoadSetNetwork(nn.Module):
    """Arm-conditioned set encoder with a learned member boundary."""

    def __init__(self, config: AnchorRoadSetConfig) -> None:
        super().__init__()
        config.validate()
        self.config = config
        hidden = config.hidden_dim
        self.object_stem = _stem(config.feature_dim, hidden)
        self.member_stem = _stem(
            config.feature_dim + ANCHOR_MEMBER_LOCAL_FEATURE_DIM,
            hidden,
        )
        self.arm_stem = _stem(ANCHOR_ARM_FEATURE_DIM, hidden)
        self.arm_match_fusion = _stem(hidden * 4, hidden)
        self.relation_stem = _stem(ANCHOR_MEMBER_RELATION_DIM, hidden)
        self.relation_neighbor = (
            nn.Sequential(
                nn.Linear(hidden, hidden),
                nn.GELU(),
            )
            if config.use_relation_messages
            else None
        )
        self.relation_message_norm = (
            nn.LayerNorm(hidden)
            if config.use_relation_messages
            else None
        )
        self.relation_extra_neighbors = nn.ModuleList(
            nn.Sequential(
                nn.Linear(hidden, hidden),
                nn.GELU(),
            )
            for _ in range(
                max(config.relation_message_layers - 1, 0)
                if config.use_relation_messages
                else 0
            )
        )
        self.relation_extra_norms = nn.ModuleList(
            nn.LayerNorm(hidden)
            for _ in range(
                max(config.relation_message_layers - 1, 0)
                if config.use_relation_messages
                else 0
            )
        )
        self.member_fusion = _stem(hidden * 4, hidden)
        layer = nn.TransformerEncoderLayer(
            d_model=hidden,
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
        self.member_head = nn.Sequential(
            nn.Linear(hidden * 2, hidden),
            nn.GELU(),
            nn.LayerNorm(hidden),
            nn.Linear(hidden, 1),
        )
        self.boundary_head = nn.Sequential(
            nn.Linear(
                hidden * 2
                + 9
                + (
                    config.corridor_feature_dim * 5
                    if config.use_explicit_corridor_boundary
                    else 0
                )
                + (5 if config.use_arm_coverage_boundary else 0),
                hidden,
            ),
            nn.GELU(),
            nn.LayerNorm(hidden),
            nn.Linear(hidden, 1),
        )

    def forward(
        self,
        batch: TargetABatchTensors,
    ) -> dict[str, torch.Tensor]:
        _validate_inputs(batch, self.config.feature_dim)
        if (
            batch.anchor_member_features is None
            or batch.anchor_member_mask is None
            or batch.anchor_member_is_road is None
            or batch.anchor_member_local_features is None
            or batch.anchor_swsd_arm_features is None
            or batch.anchor_swsd_arm_mask is None
            or batch.anchor_member_arm_features is None
            or batch.anchor_member_arm_mask is None
            or batch.anchor_member_relation_features is None
            or batch.anchor_member_relation_mask is None
        ):
            raise ValueError("anchor Road-set input evidence is incomplete")
        road_mask = (
            batch.anchor_member_mask & batch.anchor_member_is_road
        )
        if bool((~road_mask.any(dim=-1)).any()):
            raise ValueError(
                "anchor Road-set batch contains no Road candidate"
            )

        objects = self.object_stem(batch.object_features)
        anchor_objects = _gather_anchor_objects(
            objects,
            batch.anchor_object_indices,
        )
        members = self.member_stem(
            torch.cat(
                (
                    batch.anchor_member_features,
                    batch.anchor_member_local_features,
                ),
                dim=-1,
            )
        )
        arm_context, arm_coverage = self._arm_context(batch)
        relation_context = self._relation_context(batch, members)
        object_context = anchor_objects.unsqueeze(2).expand_as(members)
        values = self.member_fusion(
            torch.cat(
                (
                    members,
                    arm_context,
                    relation_context,
                    object_context,
                ),
                dim=-1,
            )
        )
        flat_values = values.flatten(0, 1)
        flat_mask = road_mask.flatten(0, 1)
        encoded = self.set_encoder(
            flat_values,
            src_key_padding_mask=~flat_mask,
        ).reshape_as(values)
        encoded = encoded * road_mask.unsqueeze(-1).to(encoded.dtype)
        road_count = road_mask.sum(dim=-1, keepdim=True).clamp_min(1)
        pooled = (
            encoded * road_mask.unsqueeze(-1).to(encoded.dtype)
        ).sum(dim=2) / road_count.to(encoded.dtype)
        member_logits = self.member_head(
            torch.cat(
                (
                    encoded,
                    pooled.unsqueeze(2).expand_as(encoded),
                ),
                dim=-1,
            )
        ).squeeze(-1)
        member_logits = member_logits.masked_fill(~road_mask, float("-inf"))
        cardinality_logits = self._boundary_logits(
            member_logits,
            encoded,
            pooled,
            anchor_objects,
            road_mask,
            batch.anchor_member_local_features[..., 1],
            batch.anchor_member_features[
                ...,
                self.config.corridor_feature_start : (
                    self.config.corridor_feature_start
                    + self.config.corridor_feature_dim
                ),
            ],
            arm_coverage,
            batch.anchor_swsd_arm_mask,
        )
        return {
            "road_member_logits": member_logits,
            "road_cardinality_logits": cardinality_logits,
            "road_member_mask": road_mask,
        }

    def _arm_context(
        self,
        batch: TargetABatchTensors,
    ) -> tuple[torch.Tensor, torch.Tensor]:
        swsd = self.arm_stem(batch.anchor_swsd_arm_features)
        member = self.arm_stem(batch.anchor_member_arm_features)
        scores = torch.einsum(
            "bamrh,bash->bamrs",
            member,
            swsd,
        ) / (self.config.hidden_dim**0.5)
        pair_mask = (
            batch.anchor_member_arm_mask.unsqueeze(-1)
            & batch.anchor_swsd_arm_mask.unsqueeze(2).unsqueeze(2)
        )
        weights = _masked_softmax(scores, pair_mask, dim=-1)
        coverage = torch.sigmoid(
            scores.masked_fill(~pair_mask, -20.0).amax(dim=3)
        ) * batch.anchor_swsd_arm_mask.unsqueeze(2).to(scores.dtype)
        if self.config.use_geometric_arm_coverage:
            raw_member = batch.anchor_member_arm_features
            raw_swsd = batch.anchor_swsd_arm_features
            bearing_similarity = (
                torch.einsum(
                    "bamrd,basd->bamrs",
                    raw_member[..., :2],
                    raw_swsd[..., :2],
                )
                + 1.0
            ) * 0.5
            function_class_similarity = 1.0 - (
                raw_member[..., 2].unsqueeze(-1)
                - raw_swsd[..., 2].unsqueeze(2).unsqueeze(2)
            ).abs()
            direction_similarity = torch.einsum(
                "bamrd,basd->bamrs",
                raw_member[..., 3:],
                raw_swsd[..., 3:],
            )
            geometric = (
                0.65 * bearing_similarity
                + 0.15 * function_class_similarity
                + 0.20 * direction_similarity
            ).clamp(0.0, 1.0)
            coverage = geometric.masked_fill(
                ~pair_mask,
                0.0,
            ).amax(dim=3)
        matched = torch.einsum(
            "bamrs,bash->bamrh",
            weights,
            swsd,
        )
        relations = self.arm_match_fusion(
            torch.cat(
                (
                    member,
                    matched,
                    (member - matched).abs(),
                    member * matched,
                ),
                dim=-1,
            )
        )
        mask = batch.anchor_member_arm_mask.unsqueeze(-1)
        context = (
            relations * mask.to(relations.dtype)
        ).sum(dim=3) / mask.sum(dim=3).clamp_min(1).to(relations.dtype)
        return context, coverage

    def _relation_context(
        self,
        batch: TargetABatchTensors,
        members: torch.Tensor,
    ) -> torch.Tensor:
        relations = self.relation_stem(
            batch.anchor_member_relation_features
        )
        if self.config.use_relation_messages:
            if (
                self.relation_neighbor is None
                or self.relation_message_norm is None
            ):
                raise RuntimeError(
                    "anchor Road-set relation message modules are absent"
                )
            context = self._relation_message_context(
                relations,
                batch.anchor_member_relation_mask,
                members,
                self.relation_neighbor,
                self.relation_message_norm,
            )
            state = members + context
            for neighbor_module, norm_module in zip(
                self.relation_extra_neighbors,
                self.relation_extra_norms,
            ):
                context = self._relation_message_context(
                    relations,
                    batch.anchor_member_relation_mask,
                    state,
                    neighbor_module,
                    norm_module,
                )
                state = state + context
            return context
        mask = batch.anchor_member_relation_mask.unsqueeze(-1)
        degree = mask.sum(dim=3).clamp_min(1).to(relations.dtype)
        normalizer = (
            degree.sqrt()
            if self.config.use_relation_degree_scaling
            else degree
        )
        return (
            relations * mask.to(relations.dtype)
        ).sum(dim=3) / normalizer

    def _relation_message_context(
        self,
        relations: torch.Tensor,
        relation_mask: torch.Tensor,
        members: torch.Tensor,
        neighbor_module: nn.Module,
        norm_module: nn.Module,
    ) -> torch.Tensor:
        neighbor = neighbor_module(members).unsqueeze(2)
        messages = norm_module(
            torch.nn.functional.gelu(relations + neighbor)
        )
        mask = relation_mask.unsqueeze(-1)
        degree = mask.sum(dim=3).clamp_min(1).to(messages.dtype)
        normalizer = (
            degree.sqrt()
            if self.config.use_relation_degree_scaling
            else degree
        )
        return (
            messages * mask.to(messages.dtype)
        ).sum(dim=3) / normalizer

    def _boundary_logits(
        self,
        member_logits: torch.Tensor,
        encoded: torch.Tensor,
        pooled: torch.Tensor,
        anchor_objects: torch.Tensor,
        road_mask: torch.Tensor,
        distances: torch.Tensor,
        corridor_features: torch.Tensor,
        arm_coverage: torch.Tensor,
        swsd_arm_mask: torch.Tensor,
    ) -> torch.Tensor:
        member_count = member_logits.shape[-1]
        available = road_mask.sum(dim=-1)
        ranks = torch.arange(
            member_count,
            device=member_logits.device,
        )
        valid_rank = ranks < available.unsqueeze(-1)
        ranked = member_logits.argsort(dim=-1, descending=True)
        sorted_scores = torch.gather(member_logits, -1, ranked)
        finite_scores = sorted_scores.masked_fill(~valid_rank, 0.0)
        prefix_sum = finite_scores.cumsum(dim=-1)
        prefix_count = (ranks + 1).view(
            *((1,) * (member_logits.ndim - 1)),
            member_count,
        )
        prefix_mean = prefix_sum / prefix_count
        total_sum = finite_scores.sum(dim=-1, keepdim=True)
        remaining_count = (
            available.unsqueeze(-1) - prefix_count
        ).clamp_min(1)
        suffix_mean = (
            total_sum - prefix_sum
        ) / remaining_count.to(finite_scores.dtype)
        next_scores = torch.cat(
            (
                finite_scores[..., 1:],
                torch.full_like(finite_scores[..., :1], -8.0),
            ),
            dim=-1,
        )
        score_gap = finite_scores - next_scores

        ranked_distances = torch.gather(distances, -1, ranked).masked_fill(
            ~valid_rank,
            4.0,
        )
        selected_max_distance = ranked_distances.cummax(dim=-1).values
        reverse_min = torch.flip(
            torch.flip(ranked_distances, dims=(-1,)).cummin(dim=-1).values,
            dims=(-1,),
        )
        excluded_min_distance = torch.cat(
            (
                reverse_min[..., 1:],
                torch.full_like(reverse_min[..., :1], 4.0),
            ),
            dim=-1,
        )
        distance_gap = (
            excluded_min_distance - selected_max_distance
        )
        ranked_corridor = torch.gather(
            corridor_features,
            2,
            ranked.unsqueeze(-1).expand(
                *ranked.shape,
                corridor_features.shape[-1],
            ),
        ).masked_fill(~valid_rank.unsqueeze(-1), 0.0)
        corridor_prefix_sum = ranked_corridor.cumsum(dim=2)
        corridor_prefix_mean = (
            corridor_prefix_sum
            / prefix_count.unsqueeze(-1).to(ranked_corridor.dtype)
        )
        corridor_total = ranked_corridor.sum(dim=2, keepdim=True)
        corridor_suffix_mean = (
            corridor_total - corridor_prefix_sum
        ) / remaining_count.unsqueeze(-1).to(ranked_corridor.dtype)
        next_corridor = torch.cat(
            (
                ranked_corridor[..., 1:, :],
                torch.zeros_like(ranked_corridor[..., :1, :]),
            ),
            dim=2,
        )
        corridor_gap = ranked_corridor - next_corridor
        rank_fraction = prefix_count.to(finite_scores.dtype) / (
            available.unsqueeze(-1).clamp_min(1).to(finite_scores.dtype)
        )
        boundary = torch.stack(
            (
                finite_scores,
                next_scores,
                score_gap,
                prefix_mean,
                suffix_mean,
                selected_max_distance,
                excluded_min_distance,
                distance_gap,
                rank_fraction,
            ),
            dim=-1,
        )
        if self.config.use_explicit_corridor_boundary:
            boundary = torch.cat(
                (
                    boundary,
                    ranked_corridor,
                    next_corridor,
                    corridor_gap,
                    corridor_prefix_mean,
                    corridor_suffix_mean,
                ),
                dim=-1,
            )
        if self.config.use_arm_coverage_boundary:
            ranked_arm_coverage = torch.gather(
                arm_coverage,
                2,
                ranked.unsqueeze(-1).expand(
                    *ranked.shape,
                    arm_coverage.shape[-1],
                ),
            ).masked_fill(~valid_rank.unsqueeze(-1), 0.0)
            prefix_arm_coverage = ranked_arm_coverage.cummax(dim=2).values
            previous_arm_coverage = torch.cat(
                (
                    torch.zeros_like(prefix_arm_coverage[..., :1, :]),
                    prefix_arm_coverage[..., :-1, :],
                ),
                dim=2,
            )
            arm_gain = prefix_arm_coverage - previous_arm_coverage
            arm_mask = swsd_arm_mask.unsqueeze(2)
            arm_count = arm_mask.sum(dim=-1).clamp_min(1).to(
                prefix_arm_coverage.dtype
            )
            arm_mean = (
                prefix_arm_coverage
                * arm_mask.to(prefix_arm_coverage.dtype)
            ).sum(dim=-1) / arm_count
            arm_min = prefix_arm_coverage.masked_fill(
                ~arm_mask,
                1.0,
            ).amin(dim=-1)
            arm_max = prefix_arm_coverage.masked_fill(
                ~arm_mask,
                0.0,
            ).amax(dim=-1)
            arm_gain_mean = (
                arm_gain * arm_mask.to(arm_gain.dtype)
            ).sum(dim=-1) / arm_count
            current_arm_mean = (
                ranked_arm_coverage
                * arm_mask.to(ranked_arm_coverage.dtype)
            ).sum(dim=-1) / arm_count
            boundary = torch.cat(
                (
                    boundary,
                    torch.stack(
                        (
                            arm_mean,
                            arm_min,
                            arm_max,
                            arm_gain_mean,
                            current_arm_mean,
                        ),
                        dim=-1,
                    ),
                ),
                dim=-1,
            )
        context = torch.cat((pooled, anchor_objects), dim=-1)
        logits = self.boundary_head(
            torch.cat(
                (
                    context.unsqueeze(2).expand(
                        *context.shape[:2],
                        member_count,
                        context.shape[-1],
                    ),
                    boundary,
                ),
                dim=-1,
            )
        ).squeeze(-1)
        return logits.masked_fill(~valid_rank, float("-inf"))


def decode_anchor_road_sets(
    outputs: Mapping[str, torch.Tensor],
    *,
    cardinality_mode: str = "categorical",
) -> AnchorRoadSetSelection:
    member_logits = outputs["road_member_logits"]
    cardinality_logits = outputs["road_cardinality_logits"]
    road_mask = outputs["road_member_mask"]
    if (
        member_logits.shape != road_mask.shape
        or cardinality_logits.shape != road_mask.shape
    ):
        raise ValueError("anchor Road-set output shapes differ")
    if cardinality_mode == "categorical":
        cardinality_probabilities = torch.softmax(
            cardinality_logits,
            dim=-1,
        )
        cardinality = cardinality_logits.argmax(dim=-1) + 1
        cardinality_probability = torch.gather(
            cardinality_probabilities,
            -1,
            cardinality.sub(1).unsqueeze(-1),
        ).squeeze(-1)
    elif cardinality_mode == "ordinal":
        available = road_mask.sum(dim=-1)
        rank_indices = torch.arange(
            cardinality_logits.shape[-1],
            device=cardinality_logits.device,
        )
        valid_rank = rank_indices < available.unsqueeze(-1)
        ordinal_probabilities = torch.sigmoid(
            cardinality_logits
        ).masked_fill(~valid_rank, 0.0)
        cardinality = (
            (ordinal_probabilities >= 0.5).sum(dim=-1)
            .clamp_min(1)
            .minimum(available)
        )
        selected_rank = rank_indices < cardinality.unsqueeze(-1)
        boundary_correct_probability = torch.where(
            selected_rank,
            ordinal_probabilities,
            1.0 - ordinal_probabilities,
        ).masked_fill(~valid_rank, 1.0)
        cardinality_probability = boundary_correct_probability.amin(dim=-1)
    else:
        raise ValueError(
            "anchor Road-set cardinality_mode must be categorical or ordinal"
        )
    ranked = member_logits.argsort(dim=-1, descending=True)
    ranks = torch.arange(
        member_logits.shape[-1],
        device=member_logits.device,
    )
    rank_selected = ranks < cardinality.unsqueeze(-1)
    selected = torch.zeros_like(road_mask)
    selected.scatter_(-1, ranked, rank_selected)
    selected &= road_mask
    probabilities = torch.sigmoid(member_logits).masked_fill(
        ~road_mask,
        0.0,
    )
    minimum_included = probabilities.masked_fill(
        ~selected,
        1.0,
    ).amin(dim=-1)
    maximum_excluded = probabilities.masked_fill(
        ~road_mask | selected,
        0.0,
    ).amax(dim=-1)
    confidence = torch.minimum(
        cardinality_probability,
        torch.sigmoid(
            minimum_included - maximum_excluded
        ),
    )
    return AnchorRoadSetSelection(
        selected_members=selected,
        cardinality=cardinality,
        cardinality_probability=cardinality_probability,
        minimum_included_probability=minimum_included,
        maximum_excluded_probability=maximum_excluded,
        inclusion_margin=minimum_included - maximum_excluded,
        confidence=confidence,
    )


def _stem(input_dim: int, hidden_dim: int) -> nn.Sequential:
    return nn.Sequential(
        nn.Linear(input_dim, hidden_dim),
        nn.GELU(),
        nn.LayerNorm(hidden_dim),
        nn.Linear(hidden_dim, hidden_dim),
        nn.GELU(),
    )


def _gather_anchor_objects(
    objects: torch.Tensor,
    indices: torch.Tensor,
) -> torch.Tensor:
    if objects.ndim != 3 or indices.ndim != 2:
        raise ValueError("anchor Road-set object/index shapes differ")
    if bool(((indices < 0) | (indices >= objects.shape[1])).any()):
        raise ValueError("anchor Road-set object index is invalid")
    return torch.gather(
        objects,
        1,
        indices.unsqueeze(-1).expand(
            *indices.shape,
            objects.shape[-1],
        ),
    )


def _masked_softmax(
    values: torch.Tensor,
    mask: torch.Tensor,
    *,
    dim: int,
) -> torch.Tensor:
    if values.shape != mask.shape:
        raise ValueError("anchor Road-set attention shapes differ")
    masked = values.masked_fill(~mask, -1.0e4)
    result = torch.softmax(masked, dim=dim) * mask.to(values.dtype)
    return result / result.sum(dim=dim, keepdim=True).clamp_min(1.0e-8)


def _validate_inputs(
    batch: TargetABatchTensors,
    feature_dim: int,
) -> None:
    if (
        batch.object_features.ndim != 3
        or batch.object_features.shape[-1] != feature_dim
    ):
        raise ValueError("anchor Road-set object features differ")
    if (
        batch.anchor_member_features is None
        or batch.anchor_member_features.ndim != 4
        or batch.anchor_member_features.shape[-1] != feature_dim
    ):
        raise ValueError("anchor Road-set member features differ")


__all__ = [
    "AnchorRoadSetConfig",
    "AnchorRoadSetNetwork",
    "AnchorRoadSetSelection",
    "decode_anchor_road_sets",
]
