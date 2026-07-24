from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SCHEME_A_P2_P3_P8_SCHEMA = (
    "p05-scheme-a-p2-p3-p8-t03-t04-inference-source-contract-v1"
)
DECISION_SOURCE_GO = (
    "P05_SCHEME_A_P2_P3_P8_T03_T04_SOURCE_GO_PROMOTION_REVIEW"
)
DECISION_PARTIAL_GO = (
    "P05_SCHEME_A_P2_P3_P8_PARTIAL_GO_"
    "CARRIER_ONLY_CLUE_SOURCE_BLOCKED"
)
DECISION_SOURCE_NO_GO = "P05_SCHEME_A_P2_P3_P8_T03_T04_SOURCE_NO_GO"
DECISION_AUDIT_NO_GO = "P05_SCHEME_A_P2_P3_P8_AUDIT_NO_GO"
EXPECTED_P7_DECISION = "P05_SCHEME_A_P2_P3_P7_CURRENT_SOURCE_NO_GO"
EXPECTED_DATASET_P0_DECISION = "P05_SCHEME_A_DATASET_P0_GO"


@dataclass(frozen=True)
class SchemeAP2P3P8Config:
    p7_run_root: Path
    p6_run_root: Path
    dataset_p0_root: Path
    repository_root: Path
    output_root: Path
    run_id: str
    reference_run_root: Path | None = None
    expected_eligible_count: int = 6_275
    expected_case_count: int = 51
    expected_stable_group_count: int = 6
    expected_carrier_peer_count: int = 2
    stable_carrier_wrong_group: str = (
        "SCHEME_A_P1:SEGMENT:T10:609214532:505101583_506183080"
    )
    strict_hashes: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_eligible_count < 1 or self.expected_case_count < 1:
            raise ValueError("invalid expected scope")
        if self.expected_stable_group_count != 6:
            raise ValueError("P8 freezes the six P7 stable groups")
        if self.expected_carrier_peer_count < 2:
            raise ValueError("carrier peer gate requires at least two peers")


def choose_p8_decision(
    audit_gate_pass: bool,
    carrier_source_gate_pass: bool,
    clue_source_gate_pass: bool,
) -> str:
    if not audit_gate_pass:
        return DECISION_AUDIT_NO_GO
    if carrier_source_gate_pass and clue_source_gate_pass:
        return DECISION_SOURCE_GO
    if carrier_source_gate_pass:
        return DECISION_PARTIAL_GO
    return DECISION_SOURCE_NO_GO


__all__ = [
    "DECISION_AUDIT_NO_GO",
    "DECISION_PARTIAL_GO",
    "DECISION_SOURCE_GO",
    "DECISION_SOURCE_NO_GO",
    "EXPECTED_DATASET_P0_DECISION",
    "EXPECTED_P7_DECISION",
    "SCHEME_A_P2_P3_P8_SCHEMA",
    "SchemeAP2P3P8Config",
    "choose_p8_decision",
]
