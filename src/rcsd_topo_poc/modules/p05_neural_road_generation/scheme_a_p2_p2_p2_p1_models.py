from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEME_A_P2_P2_P2_P1_SCHEMA = "p05-scheme-a-p2-p2-p2-p1-v1"

INFERENCE_EVIDENCE_AVAILABLE = "INFERENCE_EVIDENCE_AVAILABLE"
SOURCE_FACT_BLOCKED = "SOURCE_FACT_BLOCKED"
UNOBSERVABLE_FALLBACK = "UNOBSERVABLE_FALLBACK"


@dataclass(frozen=True)
class SchemeAP2P2P2P1Config:
    p2_p2_p2_p0_run_root: Path
    p2_p1_dataset_run_root: Path
    p2_p1_oof_run_root: Path
    scheme_a_baseline_run_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    expected_case_count: int = 51
    expected_segment_count: int = 8_863
    expected_agreed_wrong_count: int = 9
    expected_review_count: int = 40
    expected_residual_unsafe_count: int = 13
    expected_base_seeds: tuple[int, ...] = (17, 29, 43)
    residual_probe: str = "SHALLOW_MLP"
    residual_probe_seed: int = 302
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_case_count < 1 or self.expected_segment_count < 1:
            raise ValueError("invalid frozen denominator")
        if self.expected_agreed_wrong_count < 1 or self.expected_review_count < 1:
            raise ValueError("invalid audit population denominator")
        if self.expected_residual_unsafe_count < 1:
            raise ValueError("invalid residual unsafe denominator")
        if len(self.expected_base_seeds) != 3 or len(set(self.expected_base_seeds)) != 3:
            raise ValueError("exactly three base seeds are required")
        if self.residual_probe != "SHALLOW_MLP":
            raise ValueError("the frozen residual probe must not change")


__all__ = [
    "INFERENCE_EVIDENCE_AVAILABLE",
    "SCHEME_A_P2_P2_P2_P1_SCHEMA",
    "SOURCE_FACT_BLOCKED",
    "SchemeAP2P2P2P1Config",
    "UNOBSERVABLE_FALLBACK",
]
