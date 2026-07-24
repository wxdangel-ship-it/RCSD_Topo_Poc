from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


DATASET_P0_SCHEMA_VERSION = "p05-scheme-a-dataset-p0-v1"
T07_DRIVEZONE_ONLY = "DRIVEZONE_ONLY"


@dataclass(frozen=True)
class SchemeADatasetP0Config:
    m0_run_root: Path
    m2r_supervision_run_root: Path
    scheme_a_baseline_run_root: Path
    pto_candidate_run_root: Path
    pto_solve_run_root: Path
    historical_p2_oracle_run_root: Path
    poc_data_root: Path
    output_root: Path
    run_id: str
    approved_excluded_business_ids: tuple[str, ...] = ("1213556_1263661",)
    expected_failure_case_keys: tuple[str, ...] = (
        "T10:74155468",
        "T10:609214532",
    )
    expected_sample_count: int = 741
    expected_case_count: int = 51
    expected_segment_count: int = 8863
    expected_task_target_count: int = 11856
    min_use_rcsd_reachability: float = 0.95
    min_joint_exact_coverage: float = 0.90
    t07_evidence_mode: str = T07_DRIVEZONE_ONLY
    strict_hashes: bool = True
    max_peak_rss_bytes: int = 16 * 1024**3
    max_wall_seconds: float = 2 * 60 * 60

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.t07_evidence_mode != T07_DRIVEZONE_ONLY:
            raise ValueError("Dataset-P0 requires T07 DriveZone-only")
        if self.expected_sample_count <= 0 or self.expected_case_count <= 0:
            raise ValueError("expected sample/case counts must be positive")
        if self.expected_segment_count <= 0 or self.expected_task_target_count <= 0:
            raise ValueError("expected Segment/task counts must be positive")
        for value in (self.min_use_rcsd_reachability, self.min_joint_exact_coverage):
            if not 0.0 <= value <= 1.0:
                raise ValueError("coverage thresholds must be within [0, 1]")
        if len(set(self.approved_excluded_business_ids)) != len(
            self.approved_excluded_business_ids
        ):
            raise ValueError("approved exclusions must be unique")
        if len(set(self.expected_failure_case_keys)) != len(self.expected_failure_case_keys):
            raise ValueError("expected failure Case keys must be unique")


__all__ = [
    "DATASET_P0_SCHEMA_VERSION",
    "SchemeADatasetP0Config",
    "T07_DRIVEZONE_ONLY",
]
