from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEME_A_P2_P1_DATASET_SCHEMA = "p05-scheme-a-p2-p1-dataset-v1"
SCHEME_A_P2_P1_SCORE_SCHEMA = "p05-scheme-a-p2-p1-score-v1"


@dataclass(frozen=True)
class SchemeAP2P1DatasetConfig:
    dataset_p0_run_root: Path
    p1_candidate_run_root: Path
    pto_candidate_run_root: Path
    pto_solve_run_root: Path
    scheme_a_baseline_run_root: Path
    output_root: Path
    run_id: str
    expected_case_count: int = 51
    expected_fold_count: int = 5
    expected_segment_group_count: int = 8_863
    expected_node_group_count: int = 0
    expected_missing_endpoint_nodes: tuple[tuple[str, str], ...] = (
        ("T10:609214532", "987665"),
        ("T10:74155468", "953982"),
    )
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_case_count < 1 or self.expected_fold_count < 2:
            raise ValueError("invalid Case/fold expectation")
        if self.expected_segment_group_count < 1 or self.expected_node_group_count < 0:
            raise ValueError("expected Segment groups must be positive and Node expectation non-negative")
        if len(self.expected_missing_endpoint_nodes) != len(
            set(self.expected_missing_endpoint_nodes)
        ) or any(not case_key or not node_id for case_key, node_id in self.expected_missing_endpoint_nodes):
            raise ValueError("invalid expected missing endpoint Node manifest")


@dataclass(frozen=True)
class SchemeAP2P1OOFConfig:
    dataset_run_root: Path
    output_root: Path
    run_id: str
    seeds: tuple[int, ...] = (17, 29, 43)
    expected_roadgraph_failures: tuple[tuple[str, str, str], ...] = (
        ("T10:74155468", "953982", "953982->47348378"),
        ("T10:609214532", "987665", "987665->987661"),
    )
    expected_case_count: int = 51
    expected_fold_count: int = 5
    embedding_dim: int = 160
    hidden_dim: int = 384
    type_embedding_dim: int = 48
    numeric_dim: int = 8
    dropout: float = 0.10
    learning_rate: float = 0.002
    weight_decay: float = 0.0001
    max_epochs: int = 40
    patience: int = 6
    inner_validation_ratio: float = 0.15
    anomaly_loss_weight: float = 0.5
    max_anomaly_threshold: float = 0.10
    batch_group_count: int = 512
    min_parameter_count: int = 1_000_000
    max_parameter_count: int = 5_000_000
    device: str = "auto"
    torch_num_threads: int = 8
    strict_hashes: bool = True
    minimum_segment_macro_f1: float = 0.98
    minimum_use_rcsd_recall: float = 0.85
    minimum_junction_node_exact: float = 0.90
    maximum_ece: float = 0.10
    minimum_safe_coverage: float = 0.50
    minimum_use_rcsd_safe_coverage: float = 0.50
    minimum_anomaly_precision: float = 0.80

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if not self.seeds or len(set(self.seeds)) != len(self.seeds):
            raise ValueError("seeds must be non-empty and unique")
        expected_failure_cases = [row[0] for row in self.expected_roadgraph_failures]
        if len(expected_failure_cases) != len(set(expected_failure_cases)) or any(
            not case_key or not node_id or not edge
            for case_key, node_id, edge in self.expected_roadgraph_failures
        ):
            raise ValueError("invalid expected RoadGraph failure manifest")
        if self.expected_case_count < 1 or self.expected_fold_count < 2:
            raise ValueError("invalid Case/fold expectation")
        if min(self.embedding_dim, self.hidden_dim, self.type_embedding_dim, self.numeric_dim) < 1:
            raise ValueError("model dimensions must be positive")
        if not 0.0 <= self.dropout < 1.0:
            raise ValueError("dropout must be in [0, 1)")
        if self.learning_rate <= 0 or self.weight_decay < 0:
            raise ValueError("invalid optimizer configuration")
        if self.max_epochs < 1 or self.patience < 1 or self.batch_group_count < 1:
            raise ValueError("training limits must be positive")
        if not 0.0 < self.inner_validation_ratio < 0.5:
            raise ValueError("inner_validation_ratio must be in (0, 0.5)")
        if not 0.0 < self.max_anomaly_threshold <= 1.0:
            raise ValueError("max_anomaly_threshold must be in (0, 1]")
        if not 0 < self.min_parameter_count <= self.max_parameter_count:
            raise ValueError("invalid parameter count bounds")
        if self.device not in {"auto", "cpu", "cuda"}:
            raise ValueError("device must be auto/cpu/cuda")


__all__ = [
    "SCHEME_A_P2_P1_DATASET_SCHEMA",
    "SCHEME_A_P2_P1_SCORE_SCHEMA",
    "SchemeAP2P1DatasetConfig",
    "SchemeAP2P1OOFConfig",
]
