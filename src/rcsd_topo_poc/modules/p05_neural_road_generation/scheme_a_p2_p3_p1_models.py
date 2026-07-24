from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEME_A_P2_P3_P1_SCHEMA = "p05-scheme-a-p2-p3-p1-evidence-audit-v1"

INFERENCE_ALLOWED = "INFERENCE_ALLOWED"
LABEL_ONLY = "LABEL_ONLY"
FORBIDDEN_LEAKAGE = "FORBIDDEN_LEAKAGE"
UNAVAILABLE = "UNAVAILABLE"
FIELD_ROLES = frozenset(
    {INFERENCE_ALLOWED, LABEL_ONLY, FORBIDDEN_LEAKAGE, UNAVAILABLE}
)

DECISION_MODEL_RESTART_GO = "P05_SCHEME_A_P2_P3_P1_MODEL_RESTART_GO"
DECISION_EVIDENCE_NO_GO = "P05_SCHEME_A_P2_P3_P1_EVIDENCE_NO_GO"
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_P2_P3_P1_AUDIT_NO_GO"


@dataclass(frozen=True)
class SchemeAP2P3P1Config:
    p2_p3_p0_run_root: Path
    p2_p2_p2_p2_run_root: Path
    dataset_p0_run_root: Path
    poc_data_root: Path
    repository_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    expected_case_count: int = 51
    expected_segment_count: int = 8_863
    expected_seed_count: int = 3
    expected_fold_count: int = 5
    expected_fold2_segment_count: int = 3_037
    expected_stable_false_use_count: int = 1
    expected_clue_only_count: int = 13
    minimum_safe_coverage: float = 0.50
    max_wall_seconds: float = 1_800.0
    max_peak_rss_bytes: int = 8 * 1024**3
    max_case_p95_seconds: float = 5.0
    max_case_seconds: float = 20.0
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        frozen = (
            self.expected_case_count,
            self.expected_segment_count,
            self.expected_seed_count,
            self.expected_fold_count,
            self.expected_fold2_segment_count,
            self.expected_stable_false_use_count,
            self.expected_clue_only_count,
        )
        if min(frozen) < 1:
            raise ValueError("all frozen denominators must be positive")
        if not 0.0 < self.minimum_safe_coverage <= 1.0:
            raise ValueError("minimum_safe_coverage must be in (0, 1]")
        if min(
            self.max_wall_seconds,
            float(self.max_peak_rss_bytes),
            self.max_case_p95_seconds,
            self.max_case_seconds,
        ) <= 0:
            raise ValueError("resource limits must be positive")
        if self.max_case_p95_seconds > self.max_case_seconds:
            raise ValueError("case p95 limit must not exceed case max limit")


__all__ = [
    "DECISION_AUDIT_NO_GO",
    "DECISION_EVIDENCE_NO_GO",
    "DECISION_MODEL_RESTART_GO",
    "FIELD_ROLES",
    "FORBIDDEN_LEAKAGE",
    "INFERENCE_ALLOWED",
    "LABEL_ONLY",
    "SCHEME_A_P2_P3_P1_SCHEMA",
    "SchemeAP2P3P1Config",
    "UNAVAILABLE",
]
