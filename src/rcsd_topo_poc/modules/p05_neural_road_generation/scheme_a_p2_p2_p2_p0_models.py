from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEME_A_P2_P2_P2_P0_SCHEMA = "p05-scheme-a-p2-p2-p2-p0-v1"


@dataclass(frozen=True)
class SchemeAP2P2P2P0Config:
    dataset_p0_root: Path
    dataset_run_root: Path
    base_oof_run_a: Path
    base_oof_run_b: Path
    p2_p2_p0_run_root: Path
    p2_p2_p1_run_a: Path
    p2_p2_p1_run_b: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    probe_seed: int = 211
    probe_names: tuple[str, ...] = ("LINEAR", "SHALLOW_MLP")
    base_seeds: tuple[int, ...] = (17, 29, 43)
    expected_case_count: int = 51
    expected_fold_count: int = 5
    expected_segment_group_count: int = 8_863
    expected_agreed_wrong_count: int = 9
    expected_stable_false_use_count: int = 8
    expected_review_count: int = 40
    expected_roadgraph_failures: tuple[tuple[str, str, str], ...] = (
        ("T10:74155468", "953982", "953982->47348378"),
        ("T10:609214532", "987665", "987665->987661"),
    )
    hidden_dim: int = 64
    max_epochs: int = 80
    patience: int = 10
    learning_rate: float = 0.003
    weight_decay: float = 0.001
    inner_validation_ratio: float = 0.20
    minimum_safe_coverage: float = 0.50
    minimum_use_rcsd_safe_coverage: float = 0.50
    strict_hashes: bool = True
    torch_num_threads: int = 8

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.probe_names != ("LINEAR", "SHALLOW_MLP"):
            raise ValueError("the two preregistered probes must not change")
        if self.expected_case_count < 1 or self.expected_fold_count < 2:
            raise ValueError("invalid Case/fold expectation")
        if self.expected_segment_group_count < 1 or self.expected_agreed_wrong_count < 1:
            raise ValueError("invalid frozen denominator")
        if self.hidden_dim < 2 or self.max_epochs < 1 or self.patience < 1:
            raise ValueError("invalid probe training limit")
        if not 0.0 < self.inner_validation_ratio < 0.5:
            raise ValueError("inner_validation_ratio must be in (0, 0.5)")
        if len(self.base_seeds) != 3 or len(set(self.base_seeds)) != 3:
            raise ValueError("exactly three base seeds are required")


@dataclass(frozen=True)
class SafetyEvidenceExample:
    case_key: str
    fold: int
    group_id: str
    object_id: str
    proposal_candidate_id: str
    proposal_target: str
    truth_candidate_id: str
    truth_target: str
    features: tuple[float, ...]
    candidate_agreement: bool
    hard_unsafe: bool
    proposal_correct: bool
    anomaly_target: bool
    review_target: bool

    @property
    def unsafe(self) -> bool:
        return (
            not self.proposal_correct
            or self.anomaly_target
            or self.review_target
        )


__all__ = [
    "SCHEME_A_P2_P2_P2_P0_SCHEMA",
    "SafetyEvidenceExample",
    "SchemeAP2P2P2P0Config",
]
