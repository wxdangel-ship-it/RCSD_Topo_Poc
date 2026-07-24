from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEME_A_P2_P3_P6_SCHEMA = (
    "p05-scheme-a-p2-p3-p6-dual-layer-attribution-v1"
)
DECISION_ATTRIBUTION_GO = (
    "P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED"
)
DECISION_AUDIT_NO_GO = (
    "P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_AUDIT_NO_GO"
)
EXPECTED_P5_DECISION = "P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO"


@dataclass(frozen=True)
class SchemeAP2P3P6Config:
    p5_run_root: Path
    scope_first_dataset_root: Path
    structural_evidence_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    expected_seeds: tuple[int, ...] = (311, 313, 317)
    expected_fold_count: int = 5
    expected_eligible_count: int = 6_275
    expected_context_count: int = 2_588
    expected_review_count: int = 40
    expected_clue_target_count: int = 1_488
    expected_failure_case_counts: tuple[tuple[str, int], ...] = (
        ("T10:609214532", 1_795),
        ("T10:74155468", 159),
    )
    expected_scorer_wrong_counts: tuple[int, ...] = (1, 1, 1)
    expected_final_wrong_counts: tuple[int, ...] = (0, 0, 0)
    expected_clue_false_positive_counts: tuple[int, ...] = (747, 2, 2_629)
    expected_clue_false_negative_counts: tuple[int, ...] = (29, 174, 6)
    expected_scorer_safe_coverage: tuple[float, ...] = (
        0.6524458701,
        0.7951884523,
        0.3469125902,
    )
    expected_final_safe_coverage: tuple[float, ...] = (
        0.4290296712,
        0.5497995188,
        0.1374498797,
    )
    expected_stable_false_positive_count: int = 2
    expected_stable_false_negative_count: int = 4
    nearest_neighbor_count: int = 20
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        seed_count = len(self.expected_seeds)
        if seed_count != 3 or len(set(self.expected_seeds)) != seed_count:
            raise ValueError("exactly three unique seeds are required")
        aligned = (
            self.expected_scorer_wrong_counts,
            self.expected_final_wrong_counts,
            self.expected_clue_false_positive_counts,
            self.expected_clue_false_negative_counts,
            self.expected_scorer_safe_coverage,
            self.expected_final_safe_coverage,
        )
        if any(len(values) != seed_count for values in aligned):
            raise ValueError("per-seed expectations differ")
        if self.expected_fold_count != 5:
            raise ValueError("P6 requires the frozen five-fold contract")
        if self.expected_eligible_count < 1 or self.expected_context_count < 1:
            raise ValueError("invalid eligible/context denominator")
        if self.nearest_neighbor_count < 1:
            raise ValueError("nearest_neighbor_count must be positive")


def choose_p6_decision(
    audit_gate_pass: bool,
    calibration_problem_proven: bool,
    representation_problem_proven: bool,
) -> str:
    if (
        audit_gate_pass
        and calibration_problem_proven
        and representation_problem_proven
    ):
        return DECISION_ATTRIBUTION_GO
    return DECISION_AUDIT_NO_GO


__all__ = [
    "DECISION_ATTRIBUTION_GO",
    "DECISION_AUDIT_NO_GO",
    "EXPECTED_P5_DECISION",
    "SCHEME_A_P2_P3_P6_SCHEMA",
    "SchemeAP2P3P6Config",
    "choose_p6_decision",
]
