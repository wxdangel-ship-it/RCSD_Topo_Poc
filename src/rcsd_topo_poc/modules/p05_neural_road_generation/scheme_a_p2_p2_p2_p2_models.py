from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEME_A_P2_P2_P2_P2_SCHEMA = "p05-scheme-a-p2-p2-p2-p2-v1"

ROAD_CARRIER_UNSAFE = "ROAD_CARRIER_UNSAFE"
CLUE_MISS_ONLY = "CLUE_MISS_ONLY"
SAFE_AND_VISIBLE = "SAFE_AND_VISIBLE"

DECISION_HIERARCHICAL_ROUTE_GO = "P05_SCHEME_A_P2_P2_P2_P2_HIERARCHICAL_ROUTE_GO"
DECISION_PARTIAL_ROUTE_NO_MODEL_GO = (
    "P05_SCHEME_A_P2_P2_P2_P2_PARTIAL_ROUTE_NO_MODEL_GO"
)
DECISION_SOURCE_CONTRACT_BLOCKED = (
    "P05_SCHEME_A_P2_P2_P2_P2_SOURCE_CONTRACT_BLOCKED"
)
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_P2_P2_P2_P2_AUDIT_NO_GO"


@dataclass(frozen=True)
class SchemeAP2P2P2P2Config:
    p2_p2_p2_p0_run_root: Path
    p2_p2_p2_p1_run_root: Path
    p2_p1_dataset_run_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    expected_case_count: int = 51
    expected_segment_count: int = 8_863
    expected_blocked_object_count: int = 22
    expected_carrier_error_count: int = 9
    expected_clue_miss_only_count: int = 13
    expected_initial_node_conflict_count: int = 26
    expected_junction_fallback_segment_count: int = 57
    expected_fold_count: int = 5
    minimum_safe_coverage: float = 0.50
    minimum_use_rcsd_safe_coverage: float = 0.50
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if min(
            self.expected_case_count,
            self.expected_segment_count,
            self.expected_blocked_object_count,
            self.expected_carrier_error_count,
            self.expected_clue_miss_only_count,
            self.expected_initial_node_conflict_count,
            self.expected_junction_fallback_segment_count,
            self.expected_fold_count,
        ) < 1:
            raise ValueError("all frozen denominators must be positive")
        if (
            self.expected_carrier_error_count + self.expected_clue_miss_only_count
            != self.expected_blocked_object_count
        ):
            raise ValueError("blocked-object business classes must exhaust the denominator")
        if not 0.0 < self.minimum_safe_coverage <= 1.0:
            raise ValueError("minimum_safe_coverage must be in (0, 1]")
        if not 0.0 < self.minimum_use_rcsd_safe_coverage <= 1.0:
            raise ValueError("minimum_use_rcsd_safe_coverage must be in (0, 1]")


__all__ = [
    "CLUE_MISS_ONLY",
    "DECISION_AUDIT_NO_GO",
    "DECISION_HIERARCHICAL_ROUTE_GO",
    "DECISION_PARTIAL_ROUTE_NO_MODEL_GO",
    "DECISION_SOURCE_CONTRACT_BLOCKED",
    "ROAD_CARRIER_UNSAFE",
    "SAFE_AND_VISIBLE",
    "SCHEME_A_P2_P2_P2_P2_SCHEMA",
    "SchemeAP2P2P2P2Config",
]
