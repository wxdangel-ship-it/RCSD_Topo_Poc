from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "2026-07-19.t12_frcsd_quality_audit.v3"

REVIEW_STATUSES = frozenset(
    {
        "confirmed_frcsd_quality_issue",
        "excluded_false_positive",
        "manual_review_required",
    }
)

ISSUE_TYPES = frozenset(
    {
        "directed_carrier_missing",
        "required_local_connectivity_missing",
    }
)


class T12ContractError(ValueError):
    """Raised when an input or review contract cannot be audited safely."""


@dataclass(frozen=True)
class AuditConfig:
    local_corridor_m: float = 50.0
    portal_radius_m: float = 50.0
    crop_inner_margin_m: float = 500.0
    path_max_length_ratio: float = 1.5
    path_max_additive_m: float = 100.0
    path_max_corridor_distance_m: float = 50.0
    sample_spacing_m: float = 5.0
    processing_crs: str | None = None
    allow_unverified_t06_evidence: bool = False

    def validate(self) -> None:
        positive = {
            "local_corridor_m": self.local_corridor_m,
            "portal_radius_m": self.portal_radius_m,
            "crop_inner_margin_m": self.crop_inner_margin_m,
            "path_max_length_ratio": self.path_max_length_ratio,
            "path_max_additive_m": self.path_max_additive_m,
            "path_max_corridor_distance_m": self.path_max_corridor_distance_m,
            "sample_spacing_m": self.sample_spacing_m,
        }
        invalid = [name for name, value in positive.items() if value <= 0]
        if invalid:
            raise T12ContractError(f"T12 parameters must be positive: {', '.join(invalid)}")
        if self.portal_radius_m < self.local_corridor_m:
            raise T12ContractError(
                "portal_radius_m must be greater than or equal to local_corridor_m"
            )

    def as_dict(self) -> dict[str, Any]:
        return {
            "local_corridor_m": self.local_corridor_m,
            "portal_radius_m": self.portal_radius_m,
            "crop_inner_margin_m": self.crop_inner_margin_m,
            "path_max_length_ratio": self.path_max_length_ratio,
            "path_max_additive_m": self.path_max_additive_m,
            "path_max_corridor_distance_m": self.path_max_corridor_distance_m,
            "sample_spacing_m": self.sample_spacing_m,
            "processing_crs": self.processing_crs,
            "allow_unverified_t06_evidence": self.allow_unverified_t06_evidence,
        }


@dataclass(frozen=True)
class PathResult:
    start: str
    end: str
    node_ids: tuple[str, ...]
    road_ids: tuple[str, ...]
    length_m: float


@dataclass(frozen=True)
class T12Artifacts:
    run_root: Path
    manifest_json: Path
    summary_json: Path
    candidates_csv: Path
    candidates_gpkg: Path
    carrier_evidence_gpkg: Path
    confirmed_csv: Path
    confirmed_gpkg: Path
    exclusions_csv: Path
    manual_review_csv: Path
    report_md: Path
    candidate_count: int
    confirmed_count: int
    exclusion_count: int
    manual_review_count: int


@dataclass
class EvidenceLayers:
    candidate_segments: list[dict[str, Any]] = field(default_factory=list)
    anchor_portals: list[dict[str, Any]] = field(default_factory=list)
    swsd_required_carriers: list[dict[str, Any]] = field(default_factory=list)
    frcsd_carrier_paths: list[dict[str, Any]] = field(default_factory=list)
