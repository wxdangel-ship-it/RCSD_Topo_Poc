from __future__ import annotations

from typing import Any

import torch
from torch import Tensor, nn
from torch.nn import functional as F

from rcsd_topo_poc.modules.p05_neural_road_generation.m1_network import _SparseGraphBlock
from rcsd_topo_poc.modules.p05_neural_road_generation.m2r_network import _ConvStage, _UpStage
from rcsd_topo_poc.modules.p05_neural_road_generation.r2_models import R2SlotLimits


class _ResidualFFN(nn.Module):
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


class R2GraphGenerator(nn.Module):
    """Conditional slot generator; oracle payloads are targets, never inputs."""

    def __init__(
        self,
        road_input_dim: int,
        *,
        limits: R2SlotLimits,
        hidden_dim: int = 384,
        graph_layers: int = 4,
        query_layers: int = 2,
        polyline_points: int = 32,
        dropout: float = 0.05,
        include_scene: bool = True,
    ) -> None:
        super().__init__()
        if hidden_dim < 64 or graph_layers < 2 or query_layers < 1:
            raise ValueError("R2 model dimensions are below the supported minimum")
        self.limits = limits
        self.polyline_points = polyline_points
        self.include_scene = include_scene
        self.graph_stem = nn.Sequential(
            nn.Linear(road_input_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.GELU(),
        )
        self.graph_blocks = nn.ModuleList(_SparseGraphBlock(hidden_dim, dropout) for _ in range(graph_layers))
        self.context_blocks = nn.ModuleList(_ResidualFFN(hidden_dim, dropout) for _ in range(2))
        self.query_blocks = nn.ModuleList(_ResidualFFN(hidden_dim, dropout) for _ in range(query_layers))

        self.road_slots = nn.Embedding(limits.road_slots, hidden_dim)
        self.node_slots = nn.Embedding(limits.node_slots, hidden_dim)
        self.t05_node_slots = nn.Embedding(limits.t05_node_slots, hidden_dim)
        self.pointer_queries = nn.Embedding(limits.pointer_queries, hidden_dim)
        self.road_action_queries = nn.Embedding(limits.road_action_queries, hidden_dim)
        self.node_action_queries = nn.Embedding(limits.node_action_queries, hidden_dim)
        self.t05_action_queries = nn.Embedding(limits.t05_action_queries, hidden_dim)

        self.road_geometry_head = nn.Linear(hidden_dim, polyline_points * 2)
        self.road_direction_head = nn.Linear(hidden_dim, 2)
        self.road_source_head = nn.Linear(hidden_dim, 2)
        self.node_xy_head = nn.Linear(hidden_dim, 2)
        self.t05_node_xy_head = nn.Linear(hidden_dim, 2)
        self.road_start_query = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.road_end_query = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.node_key = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.pointer_query = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.t05_key = nn.Linear(hidden_dim, hidden_dim, bias=False)
        self.pointer_no_match = nn.Parameter(torch.zeros(hidden_dim))
        self.road_action_head = nn.Linear(hidden_dim, 5)
        self.node_action_head = nn.Linear(hidden_dim, 4)
        self.t05_action_head = nn.Linear(hidden_dim, 4)
        self.count_head = nn.Linear(hidden_dim, 4)

        if include_scene:
            self.scene_encoder = nn.Sequential(
                _ConvStage(8, 64),
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
            self.scene_module_head = nn.Linear(hidden_dim, 2)
            self.scene_accept_head = nn.Linear(hidden_dim, 2)
            self.t03_relation_head = nn.Linear(hidden_dim, 3)
            self.t04_relation_head = nn.Linear(hidden_dim, 2)

    @staticmethod
    def _indices(count: int, limit: int, device: torch.device) -> Tensor:
        if not 0 <= count <= limit:
            raise ValueError(f"query count {count} exceeds limit {limit}")
        return torch.arange(count, device=device)

    def _decode(self, bank: nn.Embedding, count: int, context: Tensor) -> Tensor:
        hidden = bank(self._indices(count, bank.num_embeddings, context.device)) + context
        for block in self.query_blocks:
            hidden = block(hidden)
        return hidden

    def _context(self, x: Tensor, edge_index: Tensor) -> Tensor:
        hidden = self.graph_stem(x)
        for block in self.graph_blocks:
            hidden = block(hidden, edge_index)
        context = hidden.mean(dim=0)
        for block in self.context_blocks:
            context = block(context)
        return context

    def forward_graph(
        self,
        x: Tensor,
        edge_index: Tensor,
        *,
        road_count: int,
        node_count: int,
        t05_node_count: int,
        pointer_count: int,
        road_action_count: int,
        node_action_count: int,
        t05_action_count: int,
    ) -> dict[str, Tensor]:
        context = self._context(x, edge_index)
        road = self._decode(self.road_slots, road_count, context)
        node = self._decode(self.node_slots, node_count, context)
        t05_node = self._decode(self.t05_node_slots, t05_node_count, context)
        pointer = self._decode(self.pointer_queries, pointer_count, context)
        road_action = self._decode(self.road_action_queries, road_action_count, context)
        node_action = self._decode(self.node_action_queries, node_action_count, context)
        t05_action = self._decode(self.t05_action_queries, t05_action_count, context)

        node_key = self.node_key(node)
        start = self.road_start_query(road) @ node_key.T
        end = self.road_end_query(road) @ node_key.T
        t05_keys = self.t05_key(t05_node)
        pointer_keys = torch.cat((t05_keys, self.pointer_no_match[None]), dim=0)
        return {
            "road_geometry": self.road_geometry_head(road).reshape(road_count, self.polyline_points, 2).tanh() / 2,
            "road_direction": self.road_direction_head(road),
            "road_source": self.road_source_head(road),
            "road_endpoint": torch.stack((start, end), dim=1),
            "node_xy": self.node_xy_head(node).tanh() / 2,
            "t05_node_xy": self.t05_node_xy_head(t05_node).tanh() / 2,
            "pointer": self.pointer_query(pointer) @ pointer_keys.T,
            "road_action": self.road_action_head(road_action),
            "node_action": self.node_action_head(node_action),
            "t05_action": self.t05_action_head(t05_action),
            "counts": self.count_head(context).sigmoid(),
        }

    def forward_scene(self, scene: Tensor) -> dict[str, Tensor]:
        if not self.include_scene:
            raise ValueError("scene branch is disabled")
        feature_map = self.scene_encoder(scene)
        context = feature_map.mean(dim=(-2, -1))
        for block in self.context_blocks:
            context = block(context)
        return {
            "surface": self.scene_decoder(feature_map)[:, 0],
            "module": self.scene_module_head(context),
            "accepted": self.scene_accept_head(context),
            "t03_relation": self.t03_relation_head(context),
            "t04_relation": self.t04_relation_head(context),
        }


def r2_graph_loss(prediction: dict[str, Tensor], batch: dict[str, Tensor]) -> tuple[Tensor, dict[str, Tensor]]:
    losses = {
        "road_geometry": F.mse_loss(prediction["road_geometry"], batch["road_geometry"]),
        "node_xy": F.mse_loss(prediction["node_xy"], batch["node_xy"]),
        "t05_node_xy": F.mse_loss(prediction["t05_node_xy"], batch["t05_node_xy"]),
        "road_direction": F.cross_entropy(prediction["road_direction"], batch["road_direction"]),
        "road_source": F.cross_entropy(prediction["road_source"], batch["road_source"]),
        "road_endpoint": F.cross_entropy(
            prediction["road_endpoint"].reshape(-1, prediction["road_endpoint"].shape[-1]),
            batch["road_endpoint"].reshape(-1),
        ),
        "pointer": F.cross_entropy(prediction["pointer"], batch["pointer"]),
        "road_action": F.cross_entropy(prediction["road_action"], batch["road_action"]),
        "node_action": F.cross_entropy(prediction["node_action"], batch["node_action"]),
        "t05_action": F.cross_entropy(prediction["t05_action"], batch["t05_action"]),
        "counts": F.mse_loss(prediction["counts"], batch["counts"]),
    }
    total = (
        50.0 * losses["road_geometry"]
        + 50.0 * losses["node_xy"]
        + 20.0 * losses["t05_node_xy"]
        + losses["road_direction"]
        + losses["road_source"]
        + 2.0 * losses["road_endpoint"]
        + losses["pointer"]
        + losses["road_action"]
        + losses["node_action"]
        + losses["t05_action"]
        + 10.0 * losses["counts"]
    )
    detached = {name: value.detach() for name, value in losses.items()}
    detached["total"] = total.detach()
    return total, detached


def parameter_count(model: nn.Module) -> int:
    return sum(parameter.numel() for parameter in model.parameters() if parameter.requires_grad)


__all__ = ["R2GraphGenerator", "parameter_count", "r2_graph_loss"]
