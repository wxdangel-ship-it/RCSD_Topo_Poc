from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p1_training import (
    P1GroupExample,
)


SCHEME_A_P2_P3_P0_SCHEMA = "p05-scheme-a-p2-p3-p0-hierarchical-model-v1"
AUXILIARY_TARGET_NAMES = (
    "t03_has_evd_any",
    "t03_anchor_success_any",
    "t03_terminal_failure_any",
    "t04_anchor_transition_any",
    "t04_terminal_failure_any",
    "t05_relation_success_any",
    "t05_relation_success_all",
)


@dataclass(frozen=True)
class SchemeAP2P3P0Config:
    dataset_p0_root: Path
    dataset_run_root: Path
    base_oof_run_a: Path
    base_oof_run_b: Path
    p2_p2_p0_run_root: Path
    p2_p2_p1_run_a: Path
    p2_p2_p1_run_b: Path
    p2_p2_p2_p0_run_root: Path
    p2_p2_p2_p2_run_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    model_seeds: tuple[int, ...] = (311, 313, 317)
    base_seeds: tuple[int, ...] = (17, 29, 43)
    expected_case_count: int = 51
    expected_fold_count: int = 5
    expected_segment_group_count: int = 8_863
    expected_review_count: int = 40
    expected_evidence_dim: int = 202
    expected_clue_only_count: int = 13
    expected_roadgraph_failures: tuple[tuple[str, str, str], ...] = (
        ("T10:74155468", "953982", "953982->47348378"),
        ("T10:609214532", "987665", "987665->987661"),
    )
    embedding_dim: int = 96
    hidden_dim: int = 256
    type_embedding_dim: int = 24
    evidence_hidden_dim: int = 256
    numeric_dim: int = 8
    dropout: float = 0.10
    learning_rate: float = 0.0015
    weight_decay: float = 0.0002
    max_epochs: int = 40
    patience: int = 7
    inner_validation_ratio: float = 0.20
    candidate_correctness_loss_weight: float = 0.50
    clue_loss_weight: float = 1.50
    auxiliary_loss_weight: float = 0.25
    batch_group_count: int = 512
    target_min_parameter_count: int = 1_000_000
    target_max_parameter_count: int = 3_000_000
    hard_max_parameter_count: int = 5_000_000
    minimum_safe_coverage: float = 0.50
    minimum_use_rcsd_safe_coverage: float = 0.50
    minimum_clue_precision: float = 0.80
    minimum_clue_macro_f1: float = 0.85
    device: str = "auto"
    torch_num_threads: int = 8
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if len(self.model_seeds) != 3 or len(set(self.model_seeds)) != 3:
            raise ValueError("exactly three unique model seeds are required")
        if len(self.base_seeds) != 3 or len(set(self.base_seeds)) != 3:
            raise ValueError("exactly three unique base seeds are required")
        if self.expected_case_count < 1 or self.expected_fold_count < 2:
            raise ValueError("invalid Case/fold expectation")
        if self.expected_segment_group_count < 1 or self.expected_evidence_dim < 1:
            raise ValueError("invalid Segment/evidence expectation")
        dimensions = (
            self.embedding_dim,
            self.hidden_dim,
            self.type_embedding_dim,
            self.evidence_hidden_dim,
            self.numeric_dim,
        )
        if min(dimensions) < 1:
            raise ValueError("model dimensions must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.max_epochs < 1 or self.patience < 1 or self.batch_group_count < 1:
            raise ValueError("training limits must be positive")
        if not 0.0 < self.inner_validation_ratio < 0.5:
            raise ValueError("inner_validation_ratio must be in (0, 0.5)")
        if not (
            0
            < self.target_min_parameter_count
            <= self.target_max_parameter_count
            <= self.hard_max_parameter_count
        ):
            raise ValueError("invalid parameter-count contract")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto/cpu/cuda")
        failure_cases = [row[0] for row in self.expected_roadgraph_failures]
        if len(failure_cases) != len(set(failure_cases)):
            raise ValueError("expected RoadGraph failure Case keys must be unique")


@dataclass(frozen=True)
class HierarchicalTrainingExample:
    group: P1GroupExample
    evidence_features: tuple[float, ...]
    auxiliary_targets: tuple[bool, ...]

    def __post_init__(self) -> None:
        if len(self.auxiliary_targets) != len(AUXILIARY_TARGET_NAMES):
            raise ValueError("auxiliary target dimension differs from contract")


@dataclass(frozen=True)
class HierarchicalThresholds:
    carrier_threshold: float
    clue_threshold: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.carrier_threshold <= 1.0:
            raise ValueError("carrier_threshold must be in [0, 1]")
        if not 0.0 <= self.clue_threshold <= 1.0:
            raise ValueError("clue_threshold must be in [0, 1]")


__all__ = [
    "AUXILIARY_TARGET_NAMES",
    "HierarchicalThresholds",
    "HierarchicalTrainingExample",
    "SCHEME_A_P2_P3_P0_SCHEMA",
    "SchemeAP2P3P0Config",
]
