from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


EXPECTED_POC_DATA_ROOT = Path(r"E:\TestData\POC_Data")
REGISTERED_FAMILIES = (
    "T03",
    "T03_Error",
    "T04",
    "T04_Error",
    "T10",
    "T10-Error",
    "T10-Error-2",
)


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class ApprovedExclusion:
    family: str
    business_id: str
    reason: str
    decision_source: str = "user_confirmation"

    def __post_init__(self) -> None:
        if not self.family.strip() or not self.business_id.strip() or not self.reason.strip():
            raise ValueError("approved exclusion family, business_id and reason must not be empty")

    @property
    def key(self) -> tuple[str, str]:
        return self.family, self.business_id

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class M0Config:
    poc_data_root: Path
    baseline_roots: tuple[Path, ...]
    output_root: Path
    run_id: str
    split_seed: str = "p05-m0-v1"
    enforce_poc_scope: bool = True
    approved_exclusions: tuple[ApprovedExclusion, ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if not self.split_seed:
            raise ValueError("split_seed must not be empty")
        keys = [exclusion.key for exclusion in self.approved_exclusions]
        if len(keys) != len(set(keys)):
            raise ValueError("approved exclusions must be unique by family and business_id")


@dataclass(frozen=True)
class TrainingSample:
    sample_id: str
    family: str
    business_id: str
    sample_group_id: str
    scope_type: str
    case_root: str
    manifest_path: str
    manifest_sha256: str
    target_weight: float
    context_weight: float
    task_mask: dict[str, bool] = field(default_factory=dict)
    task_mask_reasons: dict[str, str] = field(default_factory=dict)
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LabelArtifact:
    sample_id: str
    family: str
    business_id: str
    role: str
    artifact_path: str
    artifact_sha256: str
    baseline_id: str
    repo_head: str
    baseline_summary_path: str
    case_run_summary_path: str
    source_case_root: str
    target_selector: str
    target_weight: float
    context_weight: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DataAnomaly:
    severity: str
    category: str
    detail: str
    family: str = ""
    business_id: str = ""
    path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SplitAssignment:
    sample_id: str
    sample_group_id: str
    fold: int
    split: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


__all__ = [
    "DataAnomaly",
    "ApprovedExclusion",
    "EXPECTED_POC_DATA_ROOT",
    "LabelArtifact",
    "M0Config",
    "REGISTERED_FAMILIES",
    "SplitAssignment",
    "TrainingSample",
    "sha256_file",
]
