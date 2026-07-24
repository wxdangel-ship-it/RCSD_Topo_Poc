from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEME_A_P2_P2_P1_SCHEMA = "p05-scheme-a-p2-p2-p1-safety-head-v1"


@dataclass(frozen=True)
class SchemeAP2P2P1Config:
    dataset_run_root: Path
    base_oof_run_a: Path
    base_oof_run_b: Path
    p2_p2_p0_run_root: Path
    output_root: Path
    run_id: str
    safety_seeds: tuple[int, ...] = (101, 103, 107)
    base_seeds: tuple[int, ...] = (17, 29, 43)
    expected_case_count: int = 51
    expected_fold_count: int = 5
    expected_segment_group_count: int = 8_863
    expected_review_count: int = 40
    expected_stable_false_use_count: int = 8
    expected_roadgraph_failures: tuple[tuple[str, str, str], ...] = (
        ("T10:74155468", "953982", "953982->47348378"),
        ("T10:609214532", "987665", "987665->987661"),
    )
    embedding_dim: int = 64
    hidden_dim: int = 128
    type_embedding_dim: int = 16
    numeric_dim: int = 21
    dropout: float = 0.10
    learning_rate: float = 0.002
    weight_decay: float = 0.0001
    max_epochs: int = 35
    patience: int = 6
    inner_validation_ratio: float = 0.20
    anomaly_loss_weight: float = 1.5
    batch_group_count: int = 768
    min_parameter_count: int = 100_000
    max_parameter_count: int = 2_000_000
    device: str = "auto"
    torch_num_threads: int = 8
    minimum_safe_coverage: float = 0.50
    minimum_use_rcsd_safe_coverage: float = 0.50
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if not self.safety_seeds or len(set(self.safety_seeds)) != len(self.safety_seeds):
            raise ValueError("safety_seeds must be non-empty and unique")
        if len(self.base_seeds) != 3 or len(set(self.base_seeds)) != 3:
            raise ValueError("exactly three unique base seeds are required")
        if self.expected_case_count < 1 or self.expected_fold_count < 2:
            raise ValueError("invalid Case/fold expectation")
        if self.expected_segment_group_count < 1 or self.expected_review_count < 0:
            raise ValueError("invalid Segment/Review expectation")
        if min(self.embedding_dim, self.hidden_dim, self.type_embedding_dim, self.numeric_dim) < 1:
            raise ValueError("model dimensions must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.max_epochs < 1 or self.patience < 1 or self.batch_group_count < 1:
            raise ValueError("training limits must be positive")
        if not 0.0 < self.inner_validation_ratio < 0.5:
            raise ValueError("inner_validation_ratio must be in (0, 0.5)")
        if not 0 < self.min_parameter_count <= self.max_parameter_count:
            raise ValueError("invalid parameter count bounds")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto/cpu/cuda")
        failure_cases = [row[0] for row in self.expected_roadgraph_failures]
        if len(failure_cases) != len(set(failure_cases)):
            raise ValueError("expected RoadGraph failure Case keys must be unique")


__all__ = ["SCHEME_A_P2_P2_P1_SCHEMA", "SchemeAP2P2P1Config"]
