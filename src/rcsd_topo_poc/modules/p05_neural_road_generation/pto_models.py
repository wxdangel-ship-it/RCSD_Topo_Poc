from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PTOStrategyReplay:
    family: str
    code_root: Path
    code_commit: str
    run_root: Path
    expected_case_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.family.strip():
            raise ValueError("strategy replay family must not be empty")
        if len(self.code_commit.strip()) != 40:
            raise ValueError("strategy replay code_commit must be a full 40-character commit")
        if len(set(self.expected_case_ids)) != len(self.expected_case_ids):
            raise ValueError("strategy replay expected_case_ids contains duplicates")


@dataclass(frozen=True)
class PTOCandidateConfig:
    strategy_replays: tuple[PTOStrategyReplay, ...]
    allowed_data_root: Path
    output_root: Path
    run_id: str
    excluded_business_ids: tuple[str, ...] = ()
    expected_case_count: int = 51
    strict_hashes: bool = True
    verify_git_commit: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if not self.strategy_replays:
            raise ValueError("at least one strategy replay is required")
        if self.expected_case_count < 1:
            raise ValueError("expected_case_count must be positive")


@dataclass(frozen=True)
class PTOOracleSolveConfig:
    candidate_run_root: Path
    r2_oracle_run_root: Path
    output_root: Path
    run_id: str
    expected_case_count: int = 51
    strict_hashes: bool = True
    emit_reconstructed_gpkg: bool = True

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if self.expected_case_count < 1:
            raise ValueError("expected_case_count must be positive")


__all__ = ["PTOCandidateConfig", "PTOOracleSolveConfig", "PTOStrategyReplay"]
