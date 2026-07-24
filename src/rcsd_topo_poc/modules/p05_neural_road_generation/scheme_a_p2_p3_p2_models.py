from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p0_models import (
    SchemeAP2P3P0Config,
)


SCHEME_A_P2_P3_P2_SCHEMA = "p05-scheme-a-p2-p3-p2-dataset-p1-scorer-v1"
DECISION_SCORER_GO = "P05_SCHEME_A_P2_P3_P2_DATASET_P1_SCORER_GO"
DECISION_MODEL_NO_GO = "P05_SCHEME_A_P2_P3_P2_MODEL_NO_GO"
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_P2_P3_P2_AUDIT_NO_GO"


@dataclass(frozen=True)
class SchemeAP2P3P2Config:
    base_config: SchemeAP2P3P0Config
    dataset_p1_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    expected_all_segment_count: int = 8_863
    expected_eligible_count: int = 6_275
    expected_context_count: int = 2_588
    expected_case_count: int = 51
    expected_review_count: int = 40
    expected_anomaly_count: int = 1_489
    expected_clue_only_eligible_count: int = 5
    expected_local_failure_count: int = 2
    expected_target_counts: tuple[tuple[str, int], ...] = (
        ("KEEP_SWSD", 4_487),
        ("REVIEW_FALLBACK", 40),
        ("USE_RCSD", 1_748),
    )
    expected_fold_eligible_counts: tuple[int, ...] = (5, 1_045, 2_672, 2_548, 5)

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_all_segment_count != (
            self.expected_eligible_count + self.expected_context_count
        ):
            raise ValueError("eligible/context denominator differs from all Segment count")
        if self.expected_case_count != self.base_config.expected_case_count:
            raise ValueError("P2-P3-P2 and base Case contracts differ")
        if len(self.expected_fold_eligible_counts) != self.base_config.expected_fold_count:
            raise ValueError("eligible fold denominator differs from base fold contract")
        if sum(self.expected_fold_eligible_counts) != self.expected_eligible_count:
            raise ValueError("eligible fold counts do not cover the eligible denominator")
        if sum(count for _, count in self.expected_target_counts) != (
            self.expected_eligible_count
        ):
            raise ValueError("eligible target counts do not cover the eligible denominator")


__all__ = [
    "DECISION_AUDIT_NO_GO",
    "DECISION_MODEL_NO_GO",
    "DECISION_SCORER_GO",
    "SCHEME_A_P2_P3_P2_SCHEMA",
    "SchemeAP2P3P2Config",
]
