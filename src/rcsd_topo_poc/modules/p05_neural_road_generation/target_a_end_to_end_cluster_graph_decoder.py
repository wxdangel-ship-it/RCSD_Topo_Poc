from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import torch
from torch import nn
from torch.nn import functional as F


@dataclass(frozen=True)
class TargetAClusterGraphSetDecoderConfig:
    signal_dim: int = 115
    relation_dim: int = 13
    hidden_dim: int = 96
    local_layer_count: int = 2
    cluster_layer_count: int = 2
    attention_head_count: int = 4
    maximum_road_cardinality: int = 66
    maximum_cluster_cardinality: int = 24
    dropout: float = 0.10

    def validate(self) -> None:
        if min(
            self.signal_dim,
            self.relation_dim,
            self.hidden_dim,
            self.local_layer_count,
            self.cluster_layer_count,
            self.attention_head_count,
            self.maximum_road_cardinality,
            self.maximum_cluster_cardinality,
        ) < 1:
            raise ValueError("cluster graph decoder config differs")
        if self.hidden_dim % self.attention_head_count:
            raise ValueError("cluster attention head dimension differs")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("cluster graph decoder dropout differs")


class TargetAClusterGraphSetDecoder(nn.Module):
    """Decode a complete Road set through endpoint-connected Road clusters."""

    def __init__(
        self,
        config: TargetAClusterGraphSetDecoderConfig = (
            TargetAClusterGraphSetDecoderConfig()
        ),
    ) -> None:
        super().__init__()
        config.validate()
        self.config = config
        self.road_stem = nn.Sequential(
            nn.Linear(config.signal_dim + 4, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        self.edge_stem = nn.Sequential(
            nn.Linear(config.relation_dim, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        self.local_layers = nn.ModuleList(
            _ClusterLocalMessageLayer(
                hidden_dim=config.hidden_dim,
                dropout=config.dropout,
            )
            for _ in range(config.local_layer_count)
        )
        self.cluster_stem = nn.Sequential(
            nn.Linear(config.hidden_dim * 2 + 2, config.hidden_dim),
            nn.GELU(),
            nn.LayerNorm(config.hidden_dim),
        )
        cluster_layer = nn.TransformerEncoderLayer(
            d_model=config.hidden_dim,
            nhead=config.attention_head_count,
            dim_feedforward=config.hidden_dim * 2,
            dropout=config.dropout,
            activation="gelu",
            batch_first=True,
            norm_first=True,
        )
        self.cluster_encoder = nn.TransformerEncoder(
            cluster_layer,
            num_layers=config.cluster_layer_count,
            enable_nested_tensor=False,
        )
        self.cluster_member_head = nn.Sequential(
            nn.Linear(config.hidden_dim, config.hidden_dim // 2),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim // 2, 1),
        )
        self.cluster_fraction_head = nn.Sequential(
            nn.Linear(config.hidden_dim, config.hidden_dim // 2),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim // 2, 1),
        )
        self.road_member_head = nn.Sequential(
            nn.Linear(config.hidden_dim * 2 + 2, config.hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim, 1),
        )
        self.road_cardinality_head = nn.Sequential(
            nn.Linear(config.hidden_dim * 4, config.hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(config.hidden_dim, config.maximum_road_cardinality + 1),
        )
        self.cluster_cardinality_head = nn.Sequential(
            nn.Linear(config.hidden_dim * 2, config.hidden_dim),
            nn.GELU(),
            nn.Dropout(config.dropout),
            nn.Linear(
                config.hidden_dim,
                config.maximum_cluster_cardinality + 1,
            ),
        )

    def forward(
        self,
        *,
        candidate_signals: torch.Tensor,
        road_relations: torch.Tensor,
        candidate_sources: torch.Tensor,
        candidate_mask: torch.Tensor,
        effective_decision: torch.Tensor,
        cluster_indices: torch.Tensor,
        cluster_mask: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        if candidate_signals.ndim != 3:
            raise ValueError("cluster graph candidate signal rank differs")
        batch_size, road_count, signal_dim = candidate_signals.shape
        cluster_count = cluster_mask.shape[-1]
        if (
            signal_dim != self.config.signal_dim
            or road_relations.shape
            != (
                batch_size,
                road_count,
                road_count,
                self.config.relation_dim,
            )
            or candidate_sources.shape != (batch_size, road_count)
            or candidate_mask.shape != (batch_size, road_count)
            or effective_decision.shape != (batch_size,)
            or cluster_indices.shape != (batch_size, road_count)
            or cluster_mask.shape != (batch_size, cluster_count)
        ):
            raise ValueError("cluster graph decoder input shape differs")
        if candidate_sources.dtype != torch.long:
            raise ValueError("cluster graph candidate source dtype differs")
        allowed = (
            candidate_mask
            & effective_decision.unsqueeze(1).lt(2)
            & candidate_sources.eq(effective_decision.unsqueeze(1))
        )
        invalid_cluster = allowed & (
            cluster_indices.lt(0) | cluster_indices.ge(cluster_count)
        )
        if invalid_cluster.any():
            raise ValueError("allowed Road lacks endpoint cluster")
        source_one_hot = F.one_hot(
            candidate_sources.clamp(min=0, max=1),
            num_classes=2,
        ).to(candidate_signals.dtype)
        decision_one_hot = F.one_hot(
            effective_decision.clamp(min=0, max=1),
            num_classes=2,
        ).to(candidate_signals.dtype)
        decision_values = decision_one_hot.unsqueeze(1).expand(
            -1, road_count, -1
        )
        hidden = self.road_stem(
            torch.cat(
                (candidate_signals, source_one_hot, decision_values),
                dim=-1,
            )
        )
        edge_hidden = self.edge_stem(road_relations)
        same_cluster = (
            cluster_indices.unsqueeze(1).eq(cluster_indices.unsqueeze(2))
            & cluster_indices.unsqueeze(1).ge(0)
            & allowed.unsqueeze(1)
            & allowed.unsqueeze(2)
        )
        for layer in self.local_layers:
            hidden = layer(
                hidden,
                edge_hidden=edge_hidden,
                pair_mask=same_cluster,
            )
        cluster_values, cluster_sizes = _pool_road_clusters(
            hidden,
            allowed=allowed,
            cluster_indices=cluster_indices,
            cluster_mask=cluster_mask,
        )
        cluster_hidden = self.cluster_stem(cluster_values)
        cluster_hidden = self.cluster_encoder(
            cluster_hidden,
            src_key_padding_mask=~cluster_mask,
        )
        cluster_hidden = cluster_hidden * cluster_mask.unsqueeze(-1)
        cluster_member_logits = self.cluster_member_head(
            cluster_hidden
        ).squeeze(-1)
        cluster_fraction_logits = self.cluster_fraction_head(
            cluster_hidden
        ).squeeze(-1)
        cluster_member_logits = cluster_member_logits.masked_fill(
            ~cluster_mask, -20.0
        )
        cluster_fraction_logits = cluster_fraction_logits.masked_fill(
            ~cluster_mask, -20.0
        )
        road_cluster_hidden = _gather_cluster_values(
            cluster_hidden,
            cluster_indices,
            allowed=allowed,
        )
        road_cluster_member = _gather_cluster_values(
            cluster_member_logits.unsqueeze(-1),
            cluster_indices,
            allowed=allowed,
        )
        road_cluster_fraction = _gather_cluster_values(
            cluster_fraction_logits.unsqueeze(-1),
            cluster_indices,
            allowed=allowed,
        )
        road_member_logits = self.road_member_head(
            torch.cat(
                (
                    hidden,
                    road_cluster_hidden,
                    road_cluster_member,
                    road_cluster_fraction,
                ),
                dim=-1,
            )
        ).squeeze(-1)
        road_member_logits = road_member_logits.masked_fill(~allowed, -20.0)
        road_pooled = torch.cat(
            (_masked_mean(hidden, allowed), _masked_max(hidden, allowed)),
            dim=-1,
        )
        cluster_pooled = torch.cat(
            (
                _masked_mean(cluster_hidden, cluster_mask),
                _masked_max(cluster_hidden, cluster_mask),
            ),
            dim=-1,
        )
        road_cardinality_logits = self.road_cardinality_head(
            torch.cat((road_pooled, cluster_pooled), dim=-1)
        )
        cluster_cardinality_logits = self.cluster_cardinality_head(
            cluster_pooled
        )
        return {
            "member_logits": road_member_logits,
            "cardinality_logits": road_cardinality_logits,
            "cluster_member_logits": cluster_member_logits,
            "cluster_fraction_logits": cluster_fraction_logits,
            "cluster_cardinality_logits": cluster_cardinality_logits,
            "allowed_mask": allowed,
            "cluster_mask": cluster_mask,
            "cluster_indices": cluster_indices,
            "cluster_sizes": cluster_sizes,
            "candidate_encoded": hidden,
            "cluster_encoded": cluster_hidden,
        }


class _ClusterLocalMessageLayer(nn.Module):
    def __init__(self, *, hidden_dim: int, dropout: float) -> None:
        super().__init__()
        self.query = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.key = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.value = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.edge_score = nn.Linear(hidden_dim, 1, bias=False)
        self.output = nn.Linear(hidden_dim, hidden_dim)
        self.message_norm = nn.LayerNorm(hidden_dim)
        self.feed_forward = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim * 2),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim * 2, hidden_dim),
        )
        self.feed_forward_norm = nn.LayerNorm(hidden_dim)
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        hidden: torch.Tensor,
        *,
        edge_hidden: torch.Tensor,
        pair_mask: torch.Tensor,
    ) -> torch.Tensor:
        scale = math.sqrt(hidden.shape[-1])
        logits = (
            self.query(hidden).unsqueeze(2)
            * self.key(hidden).unsqueeze(1)
        ).sum(dim=-1) / scale
        logits = logits + self.edge_score(edge_hidden).squeeze(-1)
        logits = logits.masked_fill(~pair_mask, -1e4)
        weights = torch.softmax(logits, dim=-1)
        weights = weights * pair_mask.to(weights.dtype)
        weights = weights / weights.sum(dim=-1, keepdim=True).clamp_min(1e-9)
        message = weights.matmul(self.value(hidden))
        hidden = self.message_norm(
            hidden + self.dropout(self.output(message))
        )
        return self.feed_forward_norm(
            hidden + self.dropout(self.feed_forward(hidden))
        )


def build_endpoint_cluster_indices(
    *,
    road_relations: torch.Tensor,
    candidate_sources: torch.Tensor,
    candidate_mask: torch.Tensor,
    effective_decision: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    """Build source-gated endpoint components without reading labels."""
    if (
        road_relations.ndim != 4
        or candidate_sources.shape != road_relations.shape[:2]
        or candidate_mask.shape != road_relations.shape[:2]
        or effective_decision.shape != road_relations.shape[:1]
        or road_relations.shape[-1] < 1
    ):
        raise ValueError("endpoint cluster input shape differs")
    batch_size, road_count = candidate_mask.shape
    indices = torch.full_like(candidate_sources, -1)
    cluster_counts = []
    for batch_index in range(batch_size):
        allowed = [
            index
            for index in range(road_count)
            if bool(candidate_mask[batch_index, index])
            and int(candidate_sources[batch_index, index])
            == int(effective_decision[batch_index])
            and int(effective_decision[batch_index]) in {0, 1}
        ]
        parent = {index: index for index in allowed}

        def find(value: int) -> int:
            while parent[value] != value:
                parent[value] = parent[parent[value]]
                value = parent[value]
            return value

        for left_index, left in enumerate(allowed):
            for right in allowed[left_index + 1 :]:
                if float(road_relations[batch_index, left, right, 0]) > 0.5:
                    left_root = find(left)
                    right_root = find(right)
                    if left_root != right_root:
                        parent[right_root] = left_root
        root_to_cluster: dict[int, int] = {}
        for road_index in allowed:
            root = find(road_index)
            if root not in root_to_cluster:
                root_to_cluster[root] = len(root_to_cluster)
            indices[batch_index, road_index] = root_to_cluster[root]
        cluster_counts.append(len(root_to_cluster))
    maximum = max(max(cluster_counts, default=0), 1)
    cluster_mask = torch.zeros(
        (batch_size, maximum),
        dtype=torch.bool,
        device=candidate_mask.device,
    )
    for batch_index, count in enumerate(cluster_counts):
        cluster_mask[batch_index, :count] = True
    return indices, cluster_mask


def compute_cluster_graph_set_loss(
    outputs: Mapping[str, torch.Tensor],
    *,
    member_targets: torch.Tensor,
    task_mask: torch.Tensor,
    sample_weights: torch.Tensor,
    road_member_weight: float = 1.0,
    road_dice_weight: float = 0.5,
    road_cardinality_weight: float = 0.5,
    cluster_member_weight: float = 0.5,
    cluster_fraction_weight: float = 0.5,
    cluster_cardinality_weight: float = 0.25,
    positive_weight_cap: float = 20.0,
) -> dict[str, torch.Tensor]:
    member_logits = outputs["member_logits"]
    allowed = outputs["allowed_mask"]
    cluster_mask = outputs["cluster_mask"]
    cluster_indices = outputs["cluster_indices"]
    if (
        member_targets.shape != member_logits.shape
        or member_targets.dtype != torch.bool
        or task_mask.shape != member_logits.shape[:1]
        or sample_weights.shape != member_logits.shape[:1]
    ):
        raise ValueError("cluster graph loss input differs")
    target_outside_source_gate = (member_targets & ~allowed).any(dim=-1)
    effective_task = task_mask & ~target_outside_source_gate & allowed.any(
        dim=-1
    )
    road_active = allowed & effective_task.unsqueeze(-1)
    road_bce, road_dice = _set_losses(
        member_logits,
        targets=member_targets,
        active=road_active,
        row_weights=sample_weights,
        effective_task=effective_task,
        positive_weight_cap=positive_weight_cap,
    )
    road_cardinality_targets = member_targets.sum(dim=-1).clamp(
        max=outputs["cardinality_logits"].shape[-1] - 1
    )
    road_cardinality = _weighted_row_loss(
        F.cross_entropy(
            outputs["cardinality_logits"],
            road_cardinality_targets,
            reduction="none",
        ),
        sample_weights,
        effective_task,
    )
    cluster_targets, cluster_fractions = _cluster_targets(
        member_targets,
        allowed=allowed,
        cluster_indices=cluster_indices,
        cluster_mask=cluster_mask,
    )
    cluster_active = cluster_mask & effective_task.unsqueeze(-1)
    cluster_bce, cluster_dice = _set_losses(
        outputs["cluster_member_logits"],
        targets=cluster_targets,
        active=cluster_active,
        row_weights=sample_weights,
        effective_task=effective_task,
        positive_weight_cap=positive_weight_cap,
    )
    cluster_fraction_rows = F.binary_cross_entropy_with_logits(
        outputs["cluster_fraction_logits"],
        cluster_fractions,
        reduction="none",
    )
    per_row_fraction = (
        cluster_fraction_rows * cluster_active
    ).sum(dim=-1) / cluster_active.sum(dim=-1).clamp_min(1)
    cluster_fraction = _weighted_row_loss(
        per_row_fraction,
        sample_weights,
        effective_task,
    )
    cluster_cardinality_targets = cluster_targets.sum(dim=-1).clamp(
        max=outputs["cluster_cardinality_logits"].shape[-1] - 1
    )
    cluster_cardinality = _weighted_row_loss(
        F.cross_entropy(
            outputs["cluster_cardinality_logits"],
            cluster_cardinality_targets,
            reduction="none",
        ),
        sample_weights,
        effective_task,
    )
    cluster_loss = 0.5 * (cluster_bce + cluster_dice)
    total = (
        road_member_weight * road_bce
        + road_dice_weight * road_dice
        + road_cardinality_weight * road_cardinality
        + cluster_member_weight * cluster_loss
        + cluster_fraction_weight * cluster_fraction
        + cluster_cardinality_weight * cluster_cardinality
    )
    return {
        "loss": total,
        "road_member_loss": road_bce,
        "road_dice_loss": road_dice,
        "road_cardinality_loss": road_cardinality,
        "cluster_member_loss": cluster_loss,
        "cluster_fraction_loss": cluster_fraction,
        "cluster_cardinality_loss": cluster_cardinality,
        "effective_task_mask": effective_task,
        "target_outside_source_gate": target_outside_source_gate,
        "cluster_targets": cluster_targets,
        "cluster_fractions": cluster_fractions,
    }


def decode_cluster_graph_set_proposals(
    outputs: Mapping[str, torch.Tensor],
    *,
    road_cardinality_width: int = 16,
    cluster_cardinality_width: int = 8,
    road_cardinality_score_weight: float = 0.5,
    cluster_cardinality_score_weight: float = 0.5,
) -> list[list[dict[str, Any]]]:
    if min(
        road_cardinality_width,
        cluster_cardinality_width,
        road_cardinality_score_weight,
        cluster_cardinality_score_weight,
    ) < 0.0:
        raise ValueError("cluster proposal score config differs")
    road_logits = outputs["member_logits"].detach().cpu()
    road_cardinality = outputs["cardinality_logits"].detach().cpu()
    cluster_logits = outputs["cluster_member_logits"].detach().cpu()
    cluster_fractions = torch.sigmoid(
        outputs["cluster_fraction_logits"].detach().cpu()
    )
    cluster_cardinality = outputs[
        "cluster_cardinality_logits"
    ].detach().cpu()
    allowed = outputs["allowed_mask"].detach().cpu()
    cluster_mask = outputs["cluster_mask"].detach().cpu()
    cluster_indices = outputs["cluster_indices"].detach().cpu()
    result = []
    for row_index in range(road_logits.shape[0]):
        road_allowed = allowed[row_index].nonzero(
            as_tuple=False
        ).flatten().tolist()
        cluster_allowed = cluster_mask[row_index].nonzero(
            as_tuple=False
        ).flatten().tolist()
        if not road_allowed or not cluster_allowed:
            result.append([])
            continue
        road_ranked = sorted(
            road_allowed,
            key=lambda index: (-float(road_logits[row_index, index]), index),
        )
        cluster_ranked = sorted(
            cluster_allowed,
            key=lambda index: (-float(cluster_logits[row_index, index]), index),
        )
        road_width = min(road_cardinality_width, len(road_ranked))
        road_counts = set(
            torch.topk(
                road_cardinality[row_index, 1 : len(road_ranked) + 1],
                road_width,
            ).indices.add(1).tolist()
        )
        cluster_width = min(
            cluster_cardinality_width, len(cluster_ranked)
        )
        cluster_counts = set(
            torch.topk(
                cluster_cardinality[
                    row_index, 1 : len(cluster_ranked) + 1
                ],
                cluster_width,
            ).indices.add(1).tolist()
        )
        proposals: dict[tuple[int, ...], tuple[float, str]] = {}
        road_log_probability = F.logsigmoid(road_logits[row_index])
        cluster_log_probability = F.logsigmoid(cluster_logits[row_index])
        road_cardinality_log_probability = F.log_softmax(
            road_cardinality[row_index], dim=-1
        )
        cluster_cardinality_log_probability = F.log_softmax(
            cluster_cardinality[row_index], dim=-1
        )

        def add(indices: Sequence[int], score: float, kind: str) -> None:
            selected = tuple(sorted(set(int(value) for value in indices)))
            if not selected:
                return
            previous = proposals.get(selected)
            if previous is None or score > previous[0]:
                proposals[selected] = (score, kind)

        for road_count in road_counts:
            selected = road_ranked[:road_count]
            add(
                selected,
                float(road_log_probability[selected].mean())
                + road_cardinality_score_weight
                * float(road_cardinality_log_probability[road_count]),
                "ROAD_CARDINALITY",
            )
        for cluster_count in cluster_counts:
            selected_clusters = set(cluster_ranked[:cluster_count])
            cluster_roads = [
                index
                for index in road_ranked
                if int(cluster_indices[row_index, index]) in selected_clusters
            ]
            cluster_score = float(
                cluster_log_probability[
                    list(selected_clusters)
                ].mean()
            ) + cluster_cardinality_score_weight * float(
                cluster_cardinality_log_probability[cluster_count]
            )
            for road_count in road_counts:
                selected = cluster_roads[:road_count]
                add(
                    selected,
                    cluster_score
                    + 0.5 * float(road_log_probability[selected].mean())
                    + road_cardinality_score_weight
                    * float(
                        road_cardinality_log_probability[len(selected)]
                    )
                    if selected
                    else -math.inf,
                    "CLUSTER_THEN_ROAD",
                )
            fraction_selected = []
            for cluster_index in sorted(selected_clusters):
                member_roads = [
                    index
                    for index in cluster_roads
                    if int(cluster_indices[row_index, index]) == cluster_index
                ]
                member_count = max(
                    1,
                    min(
                        len(member_roads),
                        round(
                            float(
                                cluster_fractions[row_index, cluster_index]
                            )
                            * len(member_roads)
                        ),
                    ),
                )
                fraction_selected.extend(member_roads[:member_count])
            add(
                fraction_selected,
                cluster_score
                + 0.5
                * float(road_log_probability[fraction_selected].mean())
                + road_cardinality_score_weight
                * float(
                    road_cardinality_log_probability[
                        len(fraction_selected)
                    ]
                )
                if fraction_selected
                else -math.inf,
                "CLUSTER_FRACTION",
            )
        result.append(
            [
                {
                    "selected_indices": list(selected),
                    "score": score,
                    "proposal_kind": kind,
                }
                for selected, (score, kind) in sorted(
                    proposals.items(),
                    key=lambda value: (-value[1][0], value[0]),
                )
            ]
        )
    return result


def _pool_road_clusters(
    hidden: torch.Tensor,
    *,
    allowed: torch.Tensor,
    cluster_indices: torch.Tensor,
    cluster_mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    batch_size, _, hidden_dim = hidden.shape
    cluster_count = cluster_mask.shape[-1]
    result = hidden.new_zeros((batch_size, cluster_count, hidden_dim * 2 + 2))
    sizes = hidden.new_zeros((batch_size, cluster_count))
    for batch_index in range(batch_size):
        total = allowed[batch_index].sum().clamp_min(1)
        for cluster_index in range(cluster_count):
            members = allowed[batch_index] & cluster_indices[batch_index].eq(
                cluster_index
            )
            if not bool(members.any()):
                continue
            values = hidden[batch_index, members]
            size = members.sum().to(hidden.dtype)
            sizes[batch_index, cluster_index] = size
            result[batch_index, cluster_index] = torch.cat(
                (
                    values.mean(dim=0),
                    values.amax(dim=0),
                    torch.log1p(size).reshape(1),
                    (size / total).reshape(1),
                )
            )
    return result, sizes


def _gather_cluster_values(
    values: torch.Tensor,
    cluster_indices: torch.Tensor,
    *,
    allowed: torch.Tensor,
) -> torch.Tensor:
    safe = cluster_indices.clamp(min=0, max=values.shape[1] - 1)
    gathered = values.gather(
        1,
        safe.unsqueeze(-1).expand(-1, -1, values.shape[-1]),
    )
    return gathered * allowed.unsqueeze(-1)


def _cluster_targets(
    targets: torch.Tensor,
    *,
    allowed: torch.Tensor,
    cluster_indices: torch.Tensor,
    cluster_mask: torch.Tensor,
) -> tuple[torch.Tensor, torch.Tensor]:
    cluster_targets = torch.zeros_like(cluster_mask)
    fractions = torch.zeros_like(cluster_mask, dtype=torch.float32)
    for batch_index in range(targets.shape[0]):
        for cluster_index in range(cluster_mask.shape[1]):
            members = allowed[batch_index] & cluster_indices[batch_index].eq(
                cluster_index
            )
            if not bool(members.any()):
                continue
            selected = targets[batch_index] & members
            cluster_targets[batch_index, cluster_index] = selected.any()
            fractions[batch_index, cluster_index] = (
                selected.sum().to(torch.float32)
                / members.sum().to(torch.float32)
            )
    return cluster_targets, fractions


def _set_losses(
    logits: torch.Tensor,
    *,
    targets: torch.Tensor,
    active: torch.Tensor,
    row_weights: torch.Tensor,
    effective_task: torch.Tensor,
    positive_weight_cap: float,
) -> tuple[torch.Tensor, torch.Tensor]:
    positive = (targets & active).sum().to(logits.dtype)
    negative = ((~targets) & active).sum().to(logits.dtype)
    positive_weight = torch.clamp(
        negative / positive.clamp_min(1.0),
        min=1.0,
        max=positive_weight_cap,
    )
    raw = F.binary_cross_entropy_with_logits(
        logits,
        targets.to(logits.dtype),
        reduction="none",
        pos_weight=positive_weight,
    )
    per_row_bce = (raw * active).sum(dim=-1) / active.sum(
        dim=-1
    ).clamp_min(1)
    probabilities = torch.sigmoid(logits) * active.to(logits.dtype)
    target_values = targets.to(logits.dtype)
    intersection = (probabilities * target_values).sum(dim=-1)
    per_row_dice = 1.0 - (
        2.0 * intersection + 1.0
    ) / (probabilities.sum(dim=-1) + target_values.sum(dim=-1) + 1.0)
    return (
        _weighted_row_loss(
            per_row_bce, row_weights, effective_task
        ),
        _weighted_row_loss(
            per_row_dice, row_weights, effective_task
        ),
    )


def _weighted_row_loss(
    rows: torch.Tensor,
    weights: torch.Tensor,
    task: torch.Tensor,
) -> torch.Tensor:
    active_weights = weights * task.to(weights.dtype)
    return (rows * active_weights).sum() / active_weights.sum().clamp_min(
        1e-9
    )


def _masked_mean(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    return (values * mask.unsqueeze(-1)).sum(dim=1) / mask.sum(
        dim=1, keepdim=True
    ).clamp_min(1)


def _masked_max(values: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    masked = values.masked_fill(~mask.unsqueeze(-1), -1e4)
    maximum = masked.amax(dim=1)
    return torch.where(mask.any(dim=1, keepdim=True), maximum, 0.0)


__all__ = [
    "TargetAClusterGraphSetDecoder",
    "TargetAClusterGraphSetDecoderConfig",
    "build_endpoint_cluster_indices",
    "compute_cluster_graph_set_loss",
    "decode_cluster_graph_set_proposals",
]
