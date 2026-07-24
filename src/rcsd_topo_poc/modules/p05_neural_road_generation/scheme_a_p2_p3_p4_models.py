from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEME_A_P2_P3_P4_SCHEMA = "p05-scheme-a-p2-p3-p4-truth-rebaseline-v1"
DECISION_TRUTH_REBASELINE_GO = (
    "P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_GO_"
    "NO_RESIDUAL_REPRESENTATION_REQUIRED"
)
DECISION_TRUTH_REBASELINE_NO_GO = (
    "P05_SCHEME_A_P2_P3_P4_TRUTH_REBASELINE_NO_GO"
)


@dataclass(frozen=True)
class SchemeAP2P3P4Config:
    dataset_p1_root: Path
    scheme_a_baseline_root: Path
    p1_candidate_root: Path
    pto_candidate_root: Path
    p2_p1_dataset_root: Path
    p2_p3_p2_root: Path
    p2_p3_p3_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    model_seeds: tuple[int, ...] = (311, 313, 317)
    expected_case_count: int = 51
    expected_fold_count: int = 5
    expected_segment_count: int = 8_863
    expected_eligible_count: int = 6_275
    expected_context_count: int = 2_588
    expected_initial_node_conflict_count: int = 10
    expected_junction_fallback_segment_count: int = 21
    expected_junction_fallback_eligible_count: int = 10
    expected_node_label_count: int = 28_240
    expected_total_delta_count: int = 436
    expected_context_delta_count: int = 435
    expected_eligible_delta_count: int = 1
    expected_missing_endpoint_nodes: tuple[tuple[str, str], ...] = (
        ("T10:609214532", "987665"),
        ("T10:74155468", "953982"),
    )
    residual_group_id: str = (
        "SCHEME_A_P1:SEGMENT:T10-Error-2:89387685_507565991:"
        "89387685_507565991"
    )
    residual_truth_candidate_id: str = "sap1:918ffd80e766808f8a6b516c"
    minimum_safe_coverage: float = 0.50
    minimum_use_rcsd_safe_coverage: float = 0.50
    minimum_clue_precision: float = 0.80
    minimum_clue_macro_f1: float = 0.85
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if len(self.model_seeds) != 3 or len(set(self.model_seeds)) != 3:
            raise ValueError("exactly three unique model seeds are required")
        if self.expected_segment_count != (
            self.expected_eligible_count + self.expected_context_count
        ):
            raise ValueError("eligible/context denominators do not close")
        if self.expected_case_count < 1 or self.expected_fold_count < 2:
            raise ValueError("invalid Case/fold contract")
        if self.expected_eligible_delta_count != 1:
            raise ValueError("P4 residual contract requires exactly one eligible delta")
        if not self.residual_group_id.startswith("SCHEME_A_P1:SEGMENT:"):
            raise ValueError("residual group must be a Segment")
        thresholds = (
            self.minimum_safe_coverage,
            self.minimum_use_rcsd_safe_coverage,
            self.minimum_clue_precision,
            self.minimum_clue_macro_f1,
        )
        if any(not 0.0 <= value <= 1.0 for value in thresholds):
            raise ValueError("metric thresholds must be in [0, 1]")


__all__ = [
    "DECISION_TRUTH_REBASELINE_GO",
    "DECISION_TRUTH_REBASELINE_NO_GO",
    "SCHEME_A_P2_P3_P4_SCHEMA",
    "SchemeAP2P3P4Config",
]
