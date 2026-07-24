from __future__ import annotations

from typing import Any

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_network import (
    _PredictionHeads,
    _SparseGraphBlock,
    multitask_loss,
    trainable_parameter_count,
)


class _ConvStage(nn.Sequential):
    def __init__(self, input_channels: int, output_channels: int) -> None:
        groups = 8 if output_channels % 8 == 0 else 1
        super().__init__(
            nn.Conv2d(input_channels, output_channels, 3, stride=2, padding=1, bias=False),
            nn.GroupNorm(groups, output_channels),
            nn.GELU(),
            nn.Conv2d(output_channels, output_channels, 3, padding=1, bias=False),
            nn.GroupNorm(groups, output_channels),
            nn.GELU(),
        )


class _UpStage(nn.Sequential):
    def __init__(self, input_channels: int, output_channels: int) -> None:
        groups = 8 if output_channels % 8 == 0 else 1
        super().__init__(
            nn.ConvTranspose2d(input_channels, output_channels, 4, stride=2, padding=1, bias=False),
            nn.GroupNorm(groups, output_channels),
            nn.GELU(),
            nn.Conv2d(output_channels, output_channels, 3, padding=1, bias=False),
            nn.GroupNorm(groups, output_channels),
            nn.GELU(),
        )


class _SharedLatentBlock(nn.Module):
    def __init__(self, hidden_dim: int, dropout: float) -> None:
        super().__init__()
        self.norm = nn.LayerNorm(hidden_dim)
        self.ffn = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim * 4),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim * 4, hidden_dim),
            nn.Dropout(dropout),
        )

    def forward(self, hidden: Tensor) -> Tensor:
        return hidden + self.ffn(self.norm(hidden))


class JointM2RRoadNet(nn.Module):
    """One neural system with shared latent semantics and task-specific heads."""

    def __init__(
        self,
        road_input_dim: int,
        *,
        scene_channels: int = 8,
        hidden_dim: int = 384,
        graph_layers: int = 6,
        dropout: float = 0.1,
        polyline_points: int = 16,
        include_t07: bool = True,
    ) -> None:
        super().__init__()
        self.include_t07 = include_t07
        self.scene_encoder = nn.Sequential(
            _ConvStage(scene_channels, 64),
            _ConvStage(64, 128),
            _ConvStage(128, 256),
            _ConvStage(256, hidden_dim),
        )
        self.scene_decoder = nn.Sequential(
            _UpStage(hidden_dim, 256),
            _UpStage(256, 128),
            _UpStage(128, 64),
            _UpStage(64, 32),
            nn.Conv2d(32, 1, 1),
        )
        self.graph_stem = nn.Sequential(
            nn.Linear(road_input_dim, hidden_dim), nn.LayerNorm(hidden_dim), nn.GELU()
        )
        self.graph_blocks = nn.ModuleList(
            _SparseGraphBlock(hidden_dim, dropout) for _ in range(graph_layers)
        )
        self.shared_latent = _SharedLatentBlock(hidden_dim, dropout)
        self.scene_module_head = nn.Linear(hidden_dim, 2)
        self.scene_accept_head = nn.Linear(hidden_dim, 2)
        self.t03_relation_head = nn.Linear(hidden_dim, 3)
        self.t04_relation_head = nn.Linear(hidden_dim, 2)
        self.t06_heads = _PredictionHeads(hidden_dim, polyline_points)
        self.t05_endpoint_head = nn.Linear(hidden_dim, 4)
        self.t07_endpoint_head = nn.Linear(hidden_dim, 4) if include_t07 else None

    def forward_scene(self, scene: Tensor) -> dict[str, Tensor]:
        feature_map = self.scene_encoder(scene)
        pooled = self.shared_latent(feature_map.mean(dim=(-2, -1)))
        return {
            "surface": self.scene_decoder(feature_map)[:, 0],
            "module": self.scene_module_head(pooled),
            "accepted": self.scene_accept_head(pooled),
            "t03_relation": self.t03_relation_head(pooled),
            "t04_relation": self.t04_relation_head(pooled),
        }

    def forward_graph(self, x: Tensor, edge_index: Tensor) -> dict[str, Tensor]:
        hidden = self.graph_stem(x)
        for block in self.graph_blocks:
            hidden = block(hidden, edge_index)
        hidden = self.shared_latent(hidden)
        result = self.t06_heads(hidden)
        result["t05_endpoint"] = self.t05_endpoint_head(hidden).reshape(-1, 2, 2)
        if self.t07_endpoint_head is not None:
            result["t07_endpoint"] = self.t07_endpoint_head(hidden).reshape(-1, 2, 2)
        return result

    def forward(self, *, scene: Tensor | None = None, x: Tensor | None = None, edge_index: Tensor | None = None) -> dict[str, Tensor]:
        if scene is not None:
            if x is not None or edge_index is not None:
                raise ValueError("scene and graph inputs must be evaluated separately")
            return self.forward_scene(scene)
        if x is None or edge_index is None:
            raise ValueError("graph evaluation requires x and edge_index")
        return self.forward_graph(x, edge_index)


def _weighted_mean(values: Tensor, weights: Tensor, mask: Tensor | None = None) -> Tensor:
    if mask is not None:
        values = values[mask]
        weights = weights[mask]
    if values.numel() == 0:
        return weights.new_zeros(())
    return (values * weights).sum() / weights.sum().clamp_min(1.0e-8)


def m2r_scene_loss(
    prediction: dict[str, Tensor],
    batch: dict[str, Tensor],
    *,
    accepted_class_weights: Tensor | None = None,
    t03_class_weights: Tensor | None = None,
    t04_class_weights: Tensor | None = None,
) -> tuple[Tensor, dict[str, Tensor]]:
    weights = batch["weight"]
    surface_target = batch["surface"].float()
    surface_bce = F.binary_cross_entropy_with_logits(prediction["surface"], surface_target, reduction="none").mean(dim=(-2, -1))
    probabilities = prediction["surface"].sigmoid()
    intersection = (probabilities * surface_target).sum(dim=(-2, -1))
    dice_loss = 1.0 - (2.0 * intersection + 1.0) / (
        probabilities.sum(dim=(-2, -1)) + surface_target.sum(dim=(-2, -1)) + 1.0
    )
    surface_loss = _weighted_mean(surface_bce + dice_loss, weights)
    accepted_loss = _weighted_mean(
        F.cross_entropy(prediction["accepted"], batch["accepted"], weight=accepted_class_weights, reduction="none"), weights
    )
    module_loss = _weighted_mean(
        F.cross_entropy(prediction["module"], batch["module"], reduction="none"), weights
    )
    relation_weights = batch["relation_weight"]
    relation = batch["relation"]
    t03_mask = (batch["module"] == 0) & (relation >= 0)
    t04_mask = (batch["module"] == 1) & (relation >= 0)
    t03_loss = _weighted_mean(
        F.cross_entropy(prediction["t03_relation"], relation.clamp_min(0), weight=t03_class_weights, reduction="none"), relation_weights, t03_mask
    )
    t04_loss = _weighted_mean(
        F.cross_entropy(prediction["t04_relation"], relation.clamp(0, 1), weight=t04_class_weights, reduction="none"), relation_weights, t04_mask
    )
    total = surface_loss + 0.25 * accepted_loss + 0.2 * t03_loss + 0.2 * t04_loss + 0.05 * module_loss
    return total, {
        "surface": surface_loss.detach(),
        "accepted": accepted_loss.detach(),
        "t03_relation": t03_loss.detach(),
        "t04_relation": t04_loss.detach(),
        "module": module_loss.detach(),
        "total": total.detach(),
    }


def _endpoint_loss(logits: Tensor, target: Tensor, class_weights: Tensor | None = None) -> Tensor:
    mask = target >= 0
    if not mask.any():
        return logits.new_zeros(())
    return F.cross_entropy(logits[mask], target[mask], weight=class_weights)


def m2r_graph_loss(
    prediction: dict[str, Tensor],
    batch: dict[str, Tensor],
    *,
    operation_class_weights: Tensor,
    include_t07: bool,
    t05_class_weights: Tensor | None = None,
    t07_class_weights: Tensor | None = None,
) -> tuple[Tensor, dict[str, Tensor]]:
    t06_total, t06_losses = multitask_loss(
        prediction, batch, operation_class_weights=operation_class_weights
    )
    t05_loss = _endpoint_loss(prediction["t05_endpoint"], batch["t05_endpoint_relation"], t05_class_weights)
    t07_loss = prediction["operation"].new_zeros(())
    if include_t07:
        if "t07_endpoint" not in prediction:
            raise ValueError("include_t07=True but the model has no T07 head")
        t07_loss = _endpoint_loss(prediction["t07_endpoint"], batch["t07_endpoint_member"], t07_class_weights)
    total = t06_total + 0.2 * t05_loss + 0.1 * t07_loss
    losses = {f"t06_{name}": value for name, value in t06_losses.items() if name != "total"}
    losses.update({"t05_endpoint": t05_loss.detach(), "t07_endpoint": t07_loss.detach(), "total": total.detach()})
    return total, losses


def parameter_count(model: nn.Module) -> int:
    return trainable_parameter_count(model)


__all__ = [
    "JointM2RRoadNet",
    "m2r_graph_loss",
    "m2r_scene_loss",
    "parameter_count",
]
