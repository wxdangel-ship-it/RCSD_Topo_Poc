from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEME_A_P2_P3_P7_SCHEMA = (
    "p05-scheme-a-p2-p3-p7-pre-t06-representation-calibration-v1"
)
DECISION_REPRESENTATION_GO = (
    "P05_SCHEME_A_P2_P3_P7_REPRESENTATION_GO_NEXT_TRAINING_REVIEW"
)
DECISION_CURRENT_SOURCE_NO_GO = (
    "P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO"
)
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_P2_P3_P7_AUDIT_NO_GO"
EXPECTED_P6_DECISION = (
    "P05_SCHEME_A_P2_P3_P6_ATTRIBUTION_GO_DUAL_ROUTE_REQUIRED"
)
EXPECTED_P5_DECISION = "P05_SCHEME_A_P2_P3_P5_MODEL_NO_GO"


@dataclass(frozen=True)
class SchemeAP2P3P7Config:
    p6_run_root: Path
    dataset_p0_root: Path
    p2_p1_dataset_root: Path
    structural_evidence_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    expected_seeds: tuple[int, ...] = (311, 313, 317)
    expected_fold_count: int = 5
    expected_eligible_count: int = 6_275
    historical_base_dimension: int = 202
    movement_dimension_count: int = 14
    base_dimension: int = 188
    compatibility_dimension: int = 377
    geometry_dimension: int = 37
    representation_dimension: int = 602
    nearest_neighbor_count: int = 20
    calibration_min_positive: int = 500
    calibration_min_negative: int = 500
    required_clue_recall: float = 1.0
    required_clue_precision: float = 0.80
    required_clue_macro_f1: float = 0.85
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if len(self.expected_seeds) != 3 or len(set(self.expected_seeds)) != 3:
            raise ValueError("exactly three unique seeds are required")
        if self.expected_fold_count != 5:
            raise ValueError("P7 requires the frozen five-fold contract")
        if (
            self.historical_base_dimension - self.movement_dimension_count
            != self.base_dimension
        ):
            raise ValueError("movement-free base dimension differs")
        if self.compatibility_dimension != self.base_dimension * 2 + 1:
            raise ValueError("compatibility dimension differs")
        if (
            self.base_dimension
            + self.compatibility_dimension
            + self.geometry_dimension
            != self.representation_dimension
        ):
            raise ValueError("representation dimension differs")
        if self.nearest_neighbor_count < 1:
            raise ValueError("nearest_neighbor_count must be positive")


def choose_p7_decision(
    audit_gate_pass: bool,
    representation_gate_pass: bool,
    calibration_gate_pass: bool,
) -> str:
    if not audit_gate_pass:
        return DECISION_AUDIT_NO_GO
    if representation_gate_pass and calibration_gate_pass:
        return DECISION_REPRESENTATION_GO
    return DECISION_CURRENT_SOURCE_NO_GO


__all__ = [
    "DECISION_AUDIT_NO_GO",
    "DECISION_CURRENT_SOURCE_NO_GO",
    "DECISION_REPRESENTATION_GO",
    "EXPECTED_P5_DECISION",
    "EXPECTED_P6_DECISION",
    "SCHEME_A_P2_P3_P7_SCHEMA",
    "SchemeAP2P3P7Config",
    "choose_p7_decision",
]
