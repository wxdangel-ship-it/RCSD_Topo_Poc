from __future__ import annotations

from typing import Any

import torch
from torch import Tensor, nn
from torch.nn import functional as F


class _PredictionHeads(nn.Module):
    def __init__(self, hidden_dim: int, polyline_points: int) -> None:
        super().__init__()
        self.polyline_points = polyline_points
        self.operation = nn.Linear(hidden_dim, 5)
        self.direction = nn.Linear(hidden_dim, 4)
        self.source = nn.Linear(hidden_dim, 3)
        self.split_fraction = nn.Linear(hidden_dim, 2)
        self.child_geometry = nn.Linear(hidden_dim, 3 * polyline_points * 2)

    def forward(self, hidden: Tensor) -> dict[str, Tensor]:
        return {
            "operation": self.operation(hidden),
            "direction": self.direction(hidden),
            "source": self.source(hidden),
            "split_fraction": torch.sigmoid(self.split_fraction(hidden)),
            "child_geometry": self.child_geometry(hidden).reshape(-1, 3, self.polyline_points, 2),
        }


class _SparseGraphBlock(nn.Module):
    def __init__(self, hidden_dim: int, dropout: float) -> None:
        super().__init__()
        self.self_projection = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.neighbor_projection = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.gate = nn.Linear(hidden_dim * 2, hidden_dim)
        self.norm1 = nn.LayerNorm(hidden_dim)
        self.ffn = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim * 4),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden_dim * 4, hidden_dim),
        )
        self.norm2 = nn.LayerNorm(hidden_dim)
        self.dropout = nn.Dropout(dropout)

    def forward(self, hidden: Tensor, edge_index: Tensor) -> Tensor:
        aggregate = torch.zeros_like(hidden)
        degree = torch.zeros((hidden.shape[0], 1), dtype=hidden.dtype, device=hidden.device)
        if edge_index.numel():
            source, destination = edge_index[0], edge_index[1]
            aggregate.index_add_(0, destination, hidden[source])
            degree.index_add_(0, destination, torch.ones((len(destination), 1), dtype=hidden.dtype, device=hidden.device))
        aggregate = aggregate / degree.clamp_min(1.0)
        candidate = self.self_projection(hidden) + self.neighbor_projection(aggregate)
        gate = torch.sigmoid(self.gate(torch.cat((hidden, aggregate), dim=-1)))
        hidden = self.norm1(hidden + self.dropout(gate * candidate))
        return self.norm2(hidden + self.dropout(self.ffn(hidden)))


class RoadOperationGraphNet(nn.Module):
    def __init__(
        self,
        input_dim: int,
        *,
        hidden_dim: int = 384,
        layers: int = 6,
        dropout: float = 0.1,
        polyline_points: int = 16,
    ) -> None:
        super().__init__()
        self.encoder = nn.Sequential(nn.Linear(input_dim, hidden_dim), nn.LayerNorm(hidden_dim), nn.GELU())
        self.blocks = nn.ModuleList(_SparseGraphBlock(hidden_dim, dropout) for _ in range(layers))
        self.heads = _PredictionHeads(hidden_dim, polyline_points)

    def forward(self, x: Tensor, edge_index: Tensor) -> dict[str, Tensor]:
        hidden = self.encoder(x)
        for block in self.blocks:
            hidden = block(hidden, edge_index)
        return self.heads(hidden)


class RoadOperationMLP(nn.Module):
    def __init__(
        self,
        input_dim: int,
        *,
        hidden_dim: int = 384,
        layers: int = 4,
        dropout: float = 0.1,
        polyline_points: int = 16,
    ) -> None:
        super().__init__()
        modules: list[nn.Module] = [nn.Linear(input_dim, hidden_dim), nn.LayerNorm(hidden_dim), nn.GELU()]
        for _ in range(max(1, layers - 1)):
            modules.extend((nn.Linear(hidden_dim, hidden_dim), nn.GELU(), nn.Dropout(dropout)))
        self.encoder = nn.Sequential(*modules)
        self.heads = _PredictionHeads(hidden_dim, polyline_points)

    def forward(self, x: Tensor, edge_index: Tensor) -> dict[str, Tensor]:
        del edge_index
        return self.heads(self.encoder(x))


def build_model(
    model_type: str,
    input_dim: int,
    *,
    hidden_dim: int,
    layers: int,
    dropout: float,
    polyline_points: int,
) -> nn.Module:
    if model_type == "graph":
        return RoadOperationGraphNet(input_dim, hidden_dim=hidden_dim, layers=layers, dropout=dropout, polyline_points=polyline_points)
    if model_type == "mlp":
        return RoadOperationMLP(input_dim, hidden_dim=hidden_dim, layers=min(layers, 4), dropout=dropout, polyline_points=polyline_points)
    raise ValueError(f"unknown model_type: {model_type}")


def _weighted_mean(values: Tensor, weights: Tensor, mask: Tensor | None = None) -> Tensor:
    if mask is not None:
        values = values[mask]
        weights = weights[mask]
    if values.numel() == 0:
        return weights.new_zeros(())
    return (values * weights).sum() / weights.sum().clamp_min(1.0e-8)


def multitask_loss(
    prediction: dict[str, Tensor],
    batch: dict[str, Tensor],
    *,
    operation_class_weights: Tensor,
) -> tuple[Tensor, dict[str, Tensor]]:
    weights = batch["weight"]
    operation_per_item = F.cross_entropy(
        prediction["operation"], batch["operation"], weight=operation_class_weights, reduction="none"
    )
    operation_loss = _weighted_mean(operation_per_item, weights)
    direction_mask = (batch["direction"] >= 0) & (batch["direction"] < prediction["direction"].shape[1])
    source_mask = (batch["source"] >= 0) & (batch["source"] < prediction["source"].shape[1])
    direction_loss = _weighted_mean(
        F.cross_entropy(prediction["direction"], batch["direction"].clamp_min(0), reduction="none"), weights, direction_mask
    )
    source_loss = _weighted_mean(
        F.cross_entropy(prediction["source"], batch["source"].clamp_min(0), reduction="none"), weights, source_mask
    )
    split_error = F.smooth_l1_loss(prediction["split_fraction"], batch["split_fractions"], reduction="none")
    split_weight = batch["split_fraction_mask"] * weights[:, None]
    split_loss = (split_error * split_weight).sum() / split_weight.sum().clamp_min(1.0)
    geometry_error = F.smooth_l1_loss(prediction["child_geometry"], batch["child_geometry"], reduction="none")
    geometry_weight = batch["child_mask"][:, :, None, None] * weights[:, None, None, None]
    geometry_loss = (geometry_error * geometry_weight).sum() / geometry_weight.sum().clamp_min(1.0)
    total = operation_loss + 0.2 * direction_loss + 0.2 * source_loss + 0.1 * split_loss + 0.05 * geometry_loss
    return total, {
        "operation": operation_loss.detach(),
        "direction": direction_loss.detach(),
        "source": source_loss.detach(),
        "split_fraction": split_loss.detach(),
        "child_geometry": geometry_loss.detach(),
        "total": total.detach(),
    }


def trainable_parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)


__all__ = [
    "RoadOperationGraphNet",
    "RoadOperationMLP",
    "build_model",
    "multitask_loss",
    "trainable_parameter_count",
]
