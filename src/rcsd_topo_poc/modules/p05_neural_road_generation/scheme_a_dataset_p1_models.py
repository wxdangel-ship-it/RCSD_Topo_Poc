from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEME_A_DATASET_P1_SCHEMA = "p05-scheme-a-dataset-p1-segment-scope-v1"

DECISION_GO = "P05_SCHEME_A_DATASET_P1_GO"
DECISION_MAPPING_NO_GO = "P05_SCHEME_A_DATASET_P1_MAPPING_NO_GO"
DECISION_SCOPE_NO_GO = "P05_SCHEME_A_DATASET_P1_SCOPE_NO_GO"
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_DATASET_P1_AUDIT_NO_GO"


@dataclass(frozen=True)
class SchemeADatasetP1Config:
    dataset_p0_run_root: Path
    scheme_a_baseline_run_root: Path
    p2_p3_p0_run_root: Path
    poc_data_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    approved_exclusions: tuple[str, ...] = ("T10-Error:1213556_1263661",)
    expected_sample_count: int = 741
    expected_case_count: int = 51
    expected_segment_count: int = 8_863
    expected_t10_segment_count: int = 6_207
    expected_enabled_segment_package_count: int = 45
    expected_partition_package_count: int = 4
    expected_partition_descendant_counts: tuple[int, ...] = (3, 4, 7, 13)
    expected_direct_road_drift_count: int = 5
    expected_failure_case_count: int = 2
    expected_seed_count: int = 3
    max_wall_seconds: float = 600.0
    max_peak_rss_bytes: int = 4 * 1024**3
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        frozen = (
            self.expected_sample_count,
            self.expected_case_count,
            self.expected_segment_count,
            self.expected_t10_segment_count,
            self.expected_enabled_segment_package_count,
            self.expected_partition_package_count,
            self.expected_direct_road_drift_count,
            self.expected_failure_case_count,
            self.expected_seed_count,
        )
        if min(frozen) < 1:
            raise ValueError("all frozen denominators must be positive")
        if any(value < 1 for value in self.expected_partition_descendant_counts):
            raise ValueError("partition descendant counts must be positive")
        if self.max_wall_seconds <= 0 or self.max_peak_rss_bytes <= 0:
            raise ValueError("resource limits must be positive")
        if len(self.approved_exclusions) != len(set(self.approved_exclusions)):
            raise ValueError("approved exclusions must be unique")


__all__ = [
    "DECISION_AUDIT_NO_GO",
    "DECISION_GO",
    "DECISION_MAPPING_NO_GO",
    "DECISION_SCOPE_NO_GO",
    "SCHEME_A_DATASET_P1_SCHEMA",
    "SchemeADatasetP1Config",
]
