from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


REQUIRED_RCSD = "RCSD"
REQUIRED_SWSD = "SWSD"
REQUIRED_UNKNOWN = "UNKNOWN"

PLAN_RCSD_ONLY = "RCSD_ONLY"
PLAN_SWSD_ONLY = "SWSD_ONLY"
PLAN_MIXED_SPLICE = "MIXED_SPLICE"
PLAN_SAFE_SWSD_FALLBACK = "SAFE_SWSD_FALLBACK"
PLAN_REVIEW_FALLBACK = "REVIEW_FALLBACK"


@dataclass(frozen=True)
class P12RConfig:
    expected_advance_right_count: int = 474
    expected_case_count: int = 6
    expected_invalid_access_count: int = 40
    fold_count: int = 5
    max_candidate_distance_m: float = 5.0
    tie_epsilon_m: float = 1e-6
    max_wall_seconds: float = 300.0
    max_peak_rss_bytes: int = 1024**3

    def validate(self) -> None:
        if self.expected_advance_right_count <= 0:
            raise ValueError("expected_advance_right_count must be positive")
        if self.expected_case_count <= 0:
            raise ValueError("expected_case_count must be positive")
        if self.expected_invalid_access_count < 0:
            raise ValueError(
                "expected_invalid_access_count must be non-negative"
            )
        if self.fold_count <= 0:
            raise ValueError("fold_count must be positive")
        if self.max_candidate_distance_m <= 0:
            raise ValueError("max_candidate_distance_m must be positive")
        if self.tie_epsilon_m < 0:
            raise ValueError("tie_epsilon_m must be non-negative")


@dataclass(frozen=True)
class RoadRecord:
    road_id: str
    source: int
    snodeid: str
    enodeid: str
    formway: int
    segment_id: str
    source_road_id: str
    split_original_road_id: str
    mixed_advance_right: bool
    geometry: Any
    properties: Mapping[str, Any]

    @property
    def is_advance_right(self) -> bool:
        return bool(self.formway & 128) or (
            str(self.properties.get("segment_type") or "").lower()
            == "advance_right"
        )

    @property
    def endpoint_ids(self) -> tuple[str, ...]:
        return tuple(
            value
            for value in (self.snodeid, self.enodeid)
            if value
        )

    @property
    def lineage_ids(self) -> tuple[str, ...]:
        values = (
            self.road_id,
            self.source_road_id,
            self.split_original_road_id,
            self.road_id.split("__", maxsplit=1)[0],
        )
        return tuple(dict.fromkeys(value for value in values if value))


@dataclass(frozen=True)
class CasePaths:
    case_key: str
    family: str
    business_id: str
    frozen_skeleton: Path
    t01_roads: Path
    t01_nodes: Path
    raw_rcsd_roads: Path
    raw_rcsd_nodes: Path
    t06_relation: Path
    t06_attachment_audit: Path
    t06_closure_audit: Path
    t06_topology_audit: Path
    t06_final_roads: Path
    t06_final_nodes: Path

    def input_paths(self) -> tuple[Path, ...]:
        return (
            self.frozen_skeleton,
            self.t01_roads,
            self.t01_nodes,
            self.raw_rcsd_roads,
            self.raw_rcsd_nodes,
            self.t06_relation,
            self.t06_attachment_audit,
            self.t06_closure_audit,
            self.t06_topology_audit,
            self.t06_final_roads,
            self.t06_final_nodes,
        )
