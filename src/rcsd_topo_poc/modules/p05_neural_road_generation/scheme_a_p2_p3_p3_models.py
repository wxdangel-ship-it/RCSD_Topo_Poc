from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rcsd_topo_poc.modules.p05_neural_road_generation.scheme_a_p2_p3_p2_models import (
    SchemeAP2P3P2Config,
)


SCHEME_A_P2_P3_P3_SCHEMA = "p05-scheme-a-p2-p3-p3-safety-audit-v1"
DECISION_NEXT_REPRESENTATION = (
    "P05_SCHEME_A_P2_P3_P3_SAFETY_GATE_GO_NEXT_REPRESENTATION_REQUIRED"
)
DECISION_ARCHITECTURE_REQUIRED = (
    "P05_SCHEME_A_P2_P3_P3_SAFETY_GATE_GO_ARCHITECTURE_DECISION_REQUIRED"
)
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_P2_P3_P3_AUDIT_NO_GO"


@dataclass(frozen=True)
class SchemeAP2P3P3Config:
    p2_p3_p2_config: SchemeAP2P3P2Config
    p2_p3_p2_run_root: Path
    scheme_a_baseline_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    residual_group_id: str = (
        "SCHEME_A_P1:SEGMENT:T10-Error-2:89387685_507565991:"
        "89387685_507565991"
    )
    expected_eligible_count: int = 6_275
    expected_context_count: int = 2_588
    expected_review_count: int = 40
    expected_access_gate_count: int = 40
    expected_seed_count: int = 3
    expected_case_count: int = 51
    nearest_neighbor_count: int = 20
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_seed_count != len(
            self.p2_p3_p2_config.base_config.model_seeds
        ):
            raise ValueError("seed denominator differs from P2-P3-P2")
        if self.expected_eligible_count != self.p2_p3_p2_config.expected_eligible_count:
            raise ValueError("eligible denominator differs from P2-P3-P2")
        if self.expected_context_count != self.p2_p3_p2_config.expected_context_count:
            raise ValueError("context denominator differs from P2-P3-P2")
        if self.expected_review_count != self.p2_p3_p2_config.expected_review_count:
            raise ValueError("Review denominator differs from P2-P3-P2")
        if self.expected_case_count != self.p2_p3_p2_config.expected_case_count:
            raise ValueError("Case denominator differs from P2-P3-P2")
        if self.expected_access_gate_count != self.expected_review_count:
            raise ValueError("access gate and Review denominators differ")
        if self.nearest_neighbor_count < 1:
            raise ValueError("nearest_neighbor_count must be positive")
        if not self.residual_group_id.startswith("SCHEME_A_P1:SEGMENT:"):
            raise ValueError("residual group must be a Segment")


__all__ = [
    "DECISION_ARCHITECTURE_REQUIRED",
    "DECISION_AUDIT_NO_GO",
    "DECISION_NEXT_REPRESENTATION",
    "SCHEME_A_P2_P3_P3_SCHEMA",
    "SchemeAP2P3P3Config",
]
