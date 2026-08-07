from __future__ import annotations

from dataclasses import dataclass

import torch
from torch import nn

from rcsd_topo_poc.modules.p05_neural_road_generation.target_a_junction_joint_store import (
    GEOMETRY_RADIUS_M,
    SURFACE_GRID_HALF_EXTENT_M,
    SURFACE_GRID_SIZE,
)


@dataclass(frozen=True)
class DriveZoneSurfaceOutput:
    surface_logits: torch.Tensor
    surface_features: torch.Tensor


class DriveZoneOnlySurfaceNetwork(nn.Module):
    """Predict the SWSD junction surface from DriveZone evidence only."""

    def __init__(
        self,
        *,
        base_channels: int = 32,
        dropout: float = 0.05,
    ) -> None:
        super().__init__()
        if base_channels < 8:
            raise ValueError("junction surface base channels are too small")
        self.base_channels = base_channels
        self.input_block = _ResidualBlock(4, base_channels, dropout)
        self.down1 = _DownBlock(base_channels, base_channels * 2, dropout)
        self.down2 = _DownBlock(base_channels * 2, base_channels * 4, dropout)
        self.down3 = _DownBlock(base_channels * 4, base_channels * 8, dropout)
        self.bottleneck = nn.Sequential(
            _ResidualBlock(base_channels * 8, base_channels * 8, dropout),
            _ResidualBlock(base_channels * 8, base_channels * 8, dropout),
        )
        self.up2 = _UpBlock(base_channels * 8, base_channels * 4, dropout)
        self.up1 = _UpBlock(base_channels * 4, base_channels * 2, dropout)
        self.up0 = _UpBlock(base_channels * 2, base_channels, dropout)
        self.feature_projection = nn.Sequential(
            _ResidualBlock(base_channels, base_channels, dropout),
            nn.Conv2d(base_channels, base_channels, kernel_size=1),
        )
        self.surface_head = nn.Sequential(
            nn.Conv2d(base_channels, base_channels, kernel_size=3, padding=1),
            nn.GELU(),
            nn.Conv2d(base_channels, 1, kernel_size=1),
        )

    def forward(self, drivezone_grid: torch.Tensor) -> DriveZoneSurfaceOutput:
        if drivezone_grid.ndim == 3:
            drivezone_grid = drivezone_grid.unsqueeze(1)
        if drivezone_grid.ndim != 4 or drivezone_grid.shape[1] != 1:
            raise ValueError("DriveZone surface input must be Bx1xHxW")
        if drivezone_grid.shape[-2:] != (SURFACE_GRID_SIZE, SURFACE_GRID_SIZE):
            raise ValueError("DriveZone surface grid size differs")
        inputs = torch.cat(
            (drivezone_grid.float(), _position_channels(drivezone_grid)), dim=1
        )
        level0 = self.input_block(inputs)
        level1 = self.down1(level0)
        level2 = self.down2(level1)
        level3 = self.down3(level2)
        hidden = self.bottleneck(level3)
        hidden = self.up2(hidden, level2)
        hidden = self.up1(hidden, level1)
        hidden = self.up0(hidden, level0)
        features = self.feature_projection(hidden)
        return DriveZoneSurfaceOutput(
            surface_logits=self.surface_head(features).squeeze(1),
            surface_features=features,
        )


def pool_surface_features_by_object(
    surface_features: torch.Tensor,
    surface_logits: torch.Tensor,
    raw_geometry_tokens: torch.Tensor,
    geometry_token_mask: torch.Tensor,
    geometry_token_object_index: torch.Tensor,
    *,
    object_count: int,
) -> torch.Tensor:
    """Sample the learned surface field at raw object geometry locations."""

    if surface_features.ndim != 4 or surface_logits.ndim != 3:
        raise ValueError("junction surface feature shapes differ")
    if raw_geometry_tokens.shape[:2] != geometry_token_mask.shape:
        raise ValueError("junction geometry token mask differs")
    if geometry_token_object_index.shape != geometry_token_mask.shape:
        raise ValueError("junction geometry token object index differs")
    normalized = raw_geometry_tokens[..., 7:9] * (
        GEOMETRY_RADIUS_M / SURFACE_GRID_HALF_EXTENT_M
    )
    sampling_grid = normalized.clamp(-1.0, 1.0).unsqueeze(2)
    field = torch.cat(
        (surface_features, surface_logits.sigmoid().unsqueeze(1)), dim=1
    )
    sampled = nn.functional.grid_sample(
        field,
        sampling_grid,
        mode="bilinear",
        padding_mode="zeros",
        align_corners=False,
    ).squeeze(-1).transpose(1, 2)
    inside = normalized.abs().le(1.0).all(dim=-1)
    valid = (
        geometry_token_mask
        & geometry_token_object_index.ge(0)
        & geometry_token_object_index.lt(object_count)
        & inside
    )
    batch, _, channels = sampled.shape
    indices = geometry_token_object_index.clamp(0, max(0, object_count - 1))
    expanded = indices.unsqueeze(-1).expand(-1, -1, channels)
    values = sampled * valid.unsqueeze(-1).to(sampled.dtype)
    sums = sampled.new_zeros(batch, object_count, channels)
    sums.scatter_add_(1, expanded, values)
    counts = sampled.new_zeros(batch, object_count, 1)
    counts.scatter_add_(
        1,
        indices.unsqueeze(-1),
        valid.unsqueeze(-1).to(sampled.dtype),
    )
    means = sums / counts.clamp_min(1.0)
    minimum = torch.finfo(sampled.dtype).min
    maxima = sampled.new_full((batch, object_count, channels), minimum)
    maxima.scatter_reduce_(
        1,
        expanded,
        sampled.masked_fill(~valid.unsqueeze(-1), minimum),
        reduce="amax",
        include_self=True,
    )
    maxima = torch.where(counts.gt(0), maxima, torch.zeros_like(maxima))
    return torch.cat((means, maxima), dim=-1)


def _position_channels(reference: torch.Tensor) -> torch.Tensor:
    height, width = reference.shape[-2:]
    y = torch.linspace(-1.0, 1.0, height, device=reference.device, dtype=reference.dtype)
    x = torch.linspace(-1.0, 1.0, width, device=reference.device, dtype=reference.dtype)
    yy, xx = torch.meshgrid(y, x, indexing="ij")
    radius = (xx.square() + yy.square()).sqrt().clamp_max(1.5)
    return torch.stack((xx, yy, radius), dim=0).unsqueeze(0).expand(
        reference.shape[0], -1, -1, -1
    )


class _ResidualBlock(nn.Module):
    def __init__(self, input_channels: int, output_channels: int, dropout: float) -> None:
        super().__init__()
        groups = _groups(output_channels)
        self.body = nn.Sequential(
            nn.Conv2d(input_channels, output_channels, 3, padding=1, bias=False),
            nn.GroupNorm(groups, output_channels),
            nn.GELU(),
            nn.Dropout2d(dropout),
            nn.Conv2d(output_channels, output_channels, 3, padding=1, bias=False),
            nn.GroupNorm(groups, output_channels),
        )
        self.skip = (
            nn.Identity()
            if input_channels == output_channels
            else nn.Conv2d(input_channels, output_channels, 1, bias=False)
        )
        self.activation = nn.GELU()

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.activation(self.body(values) + self.skip(values))


class _DownBlock(nn.Module):
    def __init__(self, input_channels: int, output_channels: int, dropout: float) -> None:
        super().__init__()
        self.down = nn.Conv2d(input_channels, output_channels, 3, stride=2, padding=1)
        self.block = _ResidualBlock(output_channels, output_channels, dropout)

    def forward(self, values: torch.Tensor) -> torch.Tensor:
        return self.block(self.down(values))


class _UpBlock(nn.Module):
    def __init__(self, input_channels: int, output_channels: int, dropout: float) -> None:
        super().__init__()
        self.projection = nn.Conv2d(input_channels, output_channels, 1)
        self.block = _ResidualBlock(output_channels * 2, output_channels, dropout)

    def forward(self, values: torch.Tensor, skip: torch.Tensor) -> torch.Tensor:
        values = nn.functional.interpolate(
            values, size=skip.shape[-2:], mode="bilinear", align_corners=False
        )
        return self.block(torch.cat((self.projection(values), skip), dim=1))


def _groups(channels: int) -> int:
    for groups in (8, 4, 2, 1):
        if channels % groups == 0:
            return groups
    return 1
