from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_models import (
    SchemeAP2P3P0Config,
)


SCHEME_A_P2_P3_P5_SCHEMA = "p05-scheme-a-p2-p3-p5-scope-first-oof-v1"
SCHEME_A_P2_P3_P5_DATASET_SCHEMA = (
    "p05-scheme-a-p2-p3-p5-scope-first-dataset-v1"
)
DECISION_DATASET_GO = "P05_SCHEME_A_P2_P3_P5_DATASET_GO"
DECISION_DATASET_NO_GO = "P05_SCHEME_A_P2_P3_P5_DATASET_NO_GO"
DECISION_MODEL_GO = "P05_SCHEME_A_P2_P3_P5_MODEL_GO"
DECISION_MODEL_NO_GO = "P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO"
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_P2_P3_P5_AUDIT_NO_GO"


@dataclass(frozen=True)
class SchemeAP2P3P5DatasetConfig:
    p4_truth_root: Path
    historical_p2_p1_dataset_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    expected_segment_count: int = 8_863
    expected_eligible_count: int = 6_275
    expected_context_count: int = 2_588
    expected_node_count: int = 28_240
    expected_anomaly_count: int = 1_488
    expected_target_counts: tuple[tuple[str, int], ...] = (
        ("KEEP_SWSD", 7_074),
        ("REVIEW_FALLBACK", 40),
        ("USE_RCSD", 1_749),
    )
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_segment_count != (
            self.expected_eligible_count + self.expected_context_count
        ):
            raise ValueError("eligible/context dataset denominators do not close")
        if sum(count for _, count in self.expected_target_counts) != (
            self.expected_segment_count
        ):
            raise ValueError("dataset target denominators do not close")


@dataclass(frozen=True)
class SchemeAP2P3P5Config:
    base_config: SchemeAP2P3P0Config
    dataset_p1_root: Path
    scope_first_dataset_root: Path
    scheme_a_baseline_root: Path
    output_root: Path
    engine_output_root: Path
    run_id: str
    engine_run_id: str
    reference_run_root: Path | None = None
    reference_engine_root: Path | None = None
    expected_all_segment_count: int = 8_863
    expected_eligible_count: int = 6_275
    expected_context_count: int = 2_588
    expected_case_count: int = 51
    expected_review_count: int = 40
    expected_access_gate_count: int = 40
    expected_anomaly_count: int = 1_488
    expected_clue_only_eligible_count: int = 5
    expected_local_failure_count: int = 2
    expected_target_counts: tuple[tuple[str, int], ...] = (
        ("KEEP_SWSD", 4_486),
        ("REVIEW_FALLBACK", 40),
        ("USE_RCSD", 1_749),
    )
    expected_fold_eligible_counts: tuple[int, ...] = (5, 1_045, 2_672, 2_548, 5)
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.engine_run_id.strip():
            raise ValueError("run_id and engine_run_id must not be empty")
        if self.expected_all_segment_count != (
            self.expected_eligible_count + self.expected_context_count
        ):
            raise ValueError("eligible/context OOF denominators do not close")
        if self.expected_case_count != self.base_config.expected_case_count:
            raise ValueError("P2-P3-P5 and base Case contracts differ")
        if len(self.expected_fold_eligible_counts) != (
            self.base_config.expected_fold_count
        ):
            raise ValueError("eligible fold denominator differs")
        if sum(self.expected_fold_eligible_counts) != self.expected_eligible_count:
            raise ValueError("eligible folds do not cover the training scope")
        if sum(count for _, count in self.expected_target_counts) != (
            self.expected_eligible_count
        ):
            raise ValueError("eligible targets do not cover the training scope")
        if self.expected_access_gate_count != self.expected_review_count:
            raise ValueError("access-gate and Review denominators differ")
        if self.base_config.device != "cpu":
            raise ValueError("P2-P3-P5 formal training must use CPU")


__all__ = [
    "DECISION_AUDIT_NO_GO",
    "DECISION_DATASET_GO",
    "DECISION_DATASET_NO_GO",
    "DECISION_MODEL_GO",
    "DECISION_MODEL_NO_GO",
    "SCHEME_A_P2_P3_P5_DATASET_SCHEMA",
    "SCHEME_A_P2_P3_P5_SCHEMA",
    "SchemeAP2P3P5Config",
    "SchemeAP2P3P5DatasetConfig",
]
