from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class R2SlotLimits:
    road_slots: int
    node_slots: int
    t05_node_slots: int
    pointer_queries: int
    road_action_queries: int
    node_action_queries: int
    t05_action_queries: int

    def __post_init__(self) -> None:
        values = (
            self.road_slots,
            self.node_slots,
            self.t05_node_slots,
            self.pointer_queries,
            self.road_action_queries,
            self.node_action_queries,
            self.t05_action_queries,
        )
        if any(value < 1 for value in values):
            raise ValueError("all R2 slot limits must be positive")


@dataclass(frozen=True)
class R2Gate2Config:
    oracle_run_root: Path
    output_root: Path
    run_id: str
    initial_checkpoint_path: Path | None = None
    selected_sample_id: str = ""
    seed: int = 20260721
    hidden_dim: int = 384
    graph_layers: int = 4
    query_layers: int = 2
    polyline_points: int = 32
    max_epochs: int = 1500
    learning_rate: float = 1.0e-3
    weight_decay: float = 0.0

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.hidden_dim < 64 or self.graph_layers < 2 or self.query_layers < 1:
            raise ValueError("R2 Gate 2 model dimensions are below the supported minimum")
        if self.polyline_points < 8 or self.max_epochs < 1:
            raise ValueError("invalid R2 Gate 2 geometry/epoch configuration")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("invalid R2 Gate 2 optimizer configuration")


@dataclass(frozen=True)
class R2DatasetConfig:
    oracle_run_root: Path
    output_root: Path
    run_id: str
    polyline_points: int = 64
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.polyline_points < 8:
            raise ValueError("polyline_points must be at least 8")


@dataclass(frozen=True)
class R2OOFConfig:
    dataset_run_root: Path
    output_root: Path
    run_id: str
    initial_oof_run_root: Path | None = None
    folds: tuple[int, ...] = (0, 1, 2, 3, 4)
    seed: int = 20260721
    hidden_dim: int = 384
    graph_layers: int = 4
    query_layers: int = 2
    epochs: int = 30
    learning_rate: float = 2.0e-4
    weight_decay: float = 0.0

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.folds != (0, 1, 2, 3, 4):
            raise ValueError("R2 OOF folds must be exactly (0,1,2,3,4)")
        if self.hidden_dim < 64 or self.graph_layers < 2 or self.query_layers < 1:
            raise ValueError("R2 OOF model dimensions are below the supported minimum")
        if self.epochs < 1 or self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("invalid R2 OOF optimizer configuration")


@dataclass(frozen=True)
class R2OracleConfig:
    m2r_dataset_run_root: Path
    output_root: Path
    run_id: str
    strict_hashes: bool = True
    emit_reconstructed_gpkg: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")


__all__ = [
    "R2DatasetConfig",
    "R2Gate2Config",
    "R2OOFConfig",
    "R2OracleConfig",
    "R2SlotLimits",
]
