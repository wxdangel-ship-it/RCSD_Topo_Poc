from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class M2RDatasetConfig:
    supervision_run_root: Path
    output_root: Path
    run_id: str
    folds: tuple[int, ...] = (0, 1, 2, 3, 4)
    include_t07: bool = True
    image_size: int = 64
    polyline_points: int = 16
    entity_guard_hops: int = 1
    neighbor_distance_m: float = 5.0
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if not self.folds or any(fold not in {0, 1, 2, 3, 4} for fold in self.folds):
            raise ValueError("folds must be a non-empty subset of 0..4")
        if len(set(self.folds)) != len(self.folds):
            raise ValueError("folds must be unique")
        if self.image_size < 32 or self.image_size % 16:
            raise ValueError("image_size must be at least 32 and divisible by 16")
        if self.polyline_points < 4:
            raise ValueError("polyline_points must be at least 4")
        if self.entity_guard_hops < 1:
            raise ValueError("entity_guard_hops must be at least 1")
        if self.neighbor_distance_m < 0:
            raise ValueError("neighbor_distance_m must be non-negative")


@dataclass(frozen=True)
class M2RTrainingConfig:
    dataset_run_root: Path
    output_root: Path
    run_id: str
    held_out_fold: int
    seed: int = 20260721
    include_t07: bool = True
    small_batch_overfit: bool = False
    hidden_dim: int = 384
    graph_layers: int = 6
    dropout: float = 0.1
    epochs: int = 80
    learning_rate: float = 3.0e-4
    weight_decay: float = 1.0e-4
    patience: int = 20

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.held_out_fold not in {0, 1, 2, 3, 4}:
            raise ValueError("held_out_fold must be in 0..4")
        if self.hidden_dim < 64 or self.graph_layers < 2:
            raise ValueError("hidden_dim/layers are below the M2R minimum")
        if not 0 <= self.dropout < 1:
            raise ValueError("dropout must be in [0,1)")
        if self.epochs < 1 or self.patience < 1:
            raise ValueError("epochs and patience must be positive")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("invalid optimizer configuration")


@dataclass(frozen=True)
class M2REvaluationConfig:
    dataset_run_root: Path
    checkpoint_roots: tuple[Path, ...]
    output_root: Path
    run_id: str
    include_t07: bool = True
    seed: int = 20260721

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if not self.checkpoint_roots:
            raise ValueError("checkpoint_roots must not be empty")


__all__ = ["M2RDatasetConfig", "M2REvaluationConfig", "M2RTrainingConfig"]
