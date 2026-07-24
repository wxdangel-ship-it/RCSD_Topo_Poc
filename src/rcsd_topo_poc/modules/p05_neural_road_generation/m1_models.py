from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class M1DatasetConfig:
    m0_run_root: Path
    output_root: Path
    run_id: str
    seed: int = 20260721
    polyline_points: int = 16
    entity_guard_hops: int = 1
    neighbor_distance_m: float = 5.0
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.polyline_points < 4:
            raise ValueError("polyline_points must be at least 4")
        if self.entity_guard_hops < 1:
            raise ValueError("entity_guard_hops must be at least 1")
        if self.neighbor_distance_m < 0:
            raise ValueError("neighbor_distance_m must be non-negative")


@dataclass(frozen=True)
class M1TrainingConfig:
    dataset_run_root: Path
    output_root: Path
    run_id: str
    model_type: str = "graph"
    seed: int = 20260721
    hidden_dim: int = 384
    layers: int = 6
    dropout: float = 0.1
    epochs: int = 120
    learning_rate: float = 3.0e-4
    weight_decay: float = 1.0e-4
    patience: int = 30
    validation_fold: int | None = None
    holdout_sample_ids: tuple[str, ...] = ()
    train_all_development: bool = False
    zero_feature_ranges: tuple[tuple[int, int], ...] = ()
    min_train_label_weight: float = 0.0

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.model_type not in {"graph", "mlp"}:
            raise ValueError("model_type must be graph or mlp")
        if self.hidden_dim < 64:
            raise ValueError("hidden_dim must be at least 64")
        if self.layers < 2:
            raise ValueError("layers must be at least 2")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.epochs < 1:
            raise ValueError("epochs must be positive")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("learning_rate must be positive and weight_decay non-negative")
        if self.patience < 1:
            raise ValueError("patience must be positive")
        if self.validation_fold is not None and self.validation_fold not in {1, 2, 3, 4}:
            raise ValueError("validation_fold must be one of 1,2,3,4 or None")
        selected_views = sum(
            (
                self.validation_fold is not None,
                bool(self.holdout_sample_ids),
                self.train_all_development,
            )
        )
        if selected_views > 1:
            raise ValueError(
                "validation_fold, holdout_sample_ids, and train_all_development are mutually exclusive"
            )
        if len(set(self.holdout_sample_ids)) != len(self.holdout_sample_ids):
            raise ValueError("holdout_sample_ids must be unique")
        if not 0.0 <= self.min_train_label_weight <= 1.0:
            raise ValueError("min_train_label_weight must be in [0, 1]")
        if any(start < 0 or end <= start for start, end in self.zero_feature_ranges):
            raise ValueError("zero_feature_ranges must contain increasing non-negative ranges")


@dataclass(frozen=True)
class M1EvaluationConfig:
    dataset_run_root: Path
    output_root: Path
    run_id: str
    split: str
    prediction_mode: str = "model"
    model_run_root: Path | None = None
    allow_fixed_test: bool = False
    include_keep_all_baseline: bool = False
    seed: int = 20260721

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.split not in {"validation", "test"}:
            raise ValueError("split must be validation or test")
        if self.prediction_mode not in {"model", "keep_all"}:
            raise ValueError("prediction_mode must be model or keep_all")
        if self.prediction_mode == "model" and self.model_run_root is None:
            raise ValueError("model_run_root is required for model prediction")
        if self.prediction_mode != "model" and self.include_keep_all_baseline:
            raise ValueError("include_keep_all_baseline requires prediction_mode=model")
        if self.split == "test" and not self.allow_fixed_test:
            raise ValueError("fixed test requires allow_fixed_test=True")


__all__ = ["M1DatasetConfig", "M1EvaluationConfig", "M1TrainingConfig"]
