from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SchemeAP2CandidateConfig:
    scheme_a_baseline_run_root: Path
    p1_candidate_run_root: Path
    output_root: Path
    run_id: str
    poc_data_root: Path = Path(r"E:\TestData\POC_Data")
    excluded_business_ids: tuple[str, ...] = ("1213556_1263661",)
    expected_case_count: int = 51
    expected_segment_count: int = 8_863
    strict_hashes: bool = True
    enforce_poc_scope: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_case_count < 1 or self.expected_segment_count < 1:
            raise ValueError("expected Case/Segment counts must be positive")


@dataclass(frozen=True)
class SchemeAP2OracleConfig:
    candidate_run_root: Path
    p1_dataset_run_root: Path
    scheme_a_baseline_run_root: Path
    output_root: Path
    run_id: str
    expected_roadgraph_failures: tuple[tuple[str, str, str], ...] = (
        ("T10:74155468", "953982", "953982->47348378"),
        ("T10:609214532", "987665", "987665->987661"),
    )
    expected_case_count: int = 51
    expected_segment_count: int = 8_863
    min_joint_truth_exact_coverage: float = 0.50
    min_use_rcsd_retention: float = 0.50
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_case_count < 1 or self.expected_segment_count < 1:
            raise ValueError("expected Case/Segment counts must be positive")
        if not 0.0 <= self.min_joint_truth_exact_coverage <= 1.0:
            raise ValueError("invalid joint truth exact coverage threshold")
        if not 0.0 <= self.min_use_rcsd_retention <= 1.0:
            raise ValueError("invalid USE_RCSD retention threshold")
        cases = [row[0] for row in self.expected_roadgraph_failures]
        if len(cases) != len(set(cases)) or len(cases) >= self.expected_case_count:
            raise ValueError("invalid expected RoadGraph failure manifest")


__all__ = ["SchemeAP2CandidateConfig", "SchemeAP2OracleConfig"]
