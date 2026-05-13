from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


SOURCE_DATASETS = ("SWSD", "RCSD")
ALIGNMENT_DATASETS = ("SWSD", "RCSD", "FRCSD")
PAIR_DEFINITIONS = (("FRCSD", "SWSD"), ("FRCSD", "RCSD"), ("SWSD", "RCSD"))

PRIORITY_RANK = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}


@dataclass(frozen=True)
class ArmProfile:
    dataset: str
    junction_group_id: str
    current_junction_id: str
    arm_id: str
    source_final_arm_id: str
    source_initial_arm_ids: tuple[str, ...]
    member_road_ids: tuple[str, ...]
    seed_road_ids: tuple[str, ...]
    connector_road_ids: tuple[str, ...]
    inbound_seed_road_ids: tuple[str, ...]
    outbound_seed_road_ids: tuple[str, ...]
    bidirectional_seed_road_ids: tuple[str, ...]
    terminal_type: str
    terminal_junction_id: str | None
    terminal_member_node_ids: tuple[str, ...]
    build_status: str
    risk_flags: tuple[str, ...]
    merge_status: str
    merge_reason: str
    local_candidate_ids: tuple[str, ...]
    local_trend_angle_deg: float | None
    local_stub_road_ids: tuple[str, ...]
    trace_ids: tuple[str, ...]
    trace_stop_types: tuple[str, ...]
    through_decision_summary: dict[str, int]
    geometry_summary: dict[str, Any]
    lineage_summary: dict[str, Any] = field(default_factory=dict)
    corridor_angle_deg: float | None = None
    corridor_support_road_ids: tuple[str, ...] = tuple()
    corridor_status: str = ""


@dataclass(frozen=True)
class ArmAlignmentCandidate:
    candidate_id: str
    junction_group_id: str
    left_dataset: str
    right_dataset: str
    left_arm_id: str
    right_arm_id: str
    score: float
    confidence: str
    seed_role_score: float
    local_candidate_score: float
    trace_terminal_score: float
    road_coverage_score: float
    geometry_score: float
    evidence_flags: tuple[str, ...]
    conflict_flags: tuple[str, ...]
    rank_for_left_arm: int = 0
    rank_for_right_arm: int = 0
    selected: bool = False
    selection_reason: str = ""

    def arm_id_for(self, dataset: str) -> str:
        if dataset == self.left_dataset:
            return self.left_arm_id
        if dataset == self.right_dataset:
            return self.right_arm_id
        raise ValueError(f"Candidate {self.candidate_id} does not contain dataset {dataset}")


@dataclass(frozen=True)
class LogicalArmGroup:
    logical_arm_group_id: str
    junction_group_id: str
    frcsd_arm_ids: tuple[str, ...]
    swsd_arm_ids: tuple[str, ...]
    rcsd_arm_ids: tuple[str, ...]
    group_status: str
    acceptable_for_downstream: bool
    missing_datasets: tuple[str, ...]
    partial_datasets: tuple[str, ...]
    over_split_datasets: tuple[str, ...]
    over_merged_datasets: tuple[str, ...]
    evidence_summary: dict[str, Any]
    risk_flags: tuple[str, ...]
    review_priority: str


@dataclass(frozen=True)
class RawArmAlignment:
    alignment_id: str
    junction_group_id: str
    source_dataset: str
    target_dataset: str
    f_arm_id: str
    source_arm_ids: tuple[str, ...]
    match_type: str
    coverage_status: str
    confidence: str
    candidate_score: float
    source_initial_arm_ids: tuple[str, ...]
    f_source_initial_arm_ids: tuple[str, ...]
    evidence_summary: dict[str, Any]
    reason_codes: tuple[str, ...]
    conflict_flags: tuple[str, ...]
    review_priority: str
    logical_arm_group_id: str


@dataclass(frozen=True)
class ArmBuildFeedback:
    feedback_id: str
    junction_group_id: str
    dataset: str
    feedback_type: str
    source_arm_ids: tuple[str, ...]
    supporting_datasets: tuple[str, ...]
    supporting_logical_arm_group_ids: tuple[str, ...]
    reason: str
    confidence: str
    review_priority: str
    evidence_summary: dict[str, Any]


@dataclass(frozen=True)
class SourceExtraArm:
    dataset: str
    source_arm_id: str
    reason: str
    nearest_f_arm_candidates: tuple[dict[str, Any], ...]
    review_priority: str


@dataclass(frozen=True)
class CaseAlignmentResult:
    group_id: str
    profiles_by_dataset: dict[str, tuple[ArmProfile, ...]]
    candidates: tuple[ArmAlignmentCandidate, ...]
    logical_arm_groups: tuple[LogicalArmGroup, ...]
    raw_alignments_by_source: dict[str, tuple[RawArmAlignment, ...]]
    feedback: tuple[ArmBuildFeedback, ...]
    source_extra_arms: tuple[SourceExtraArm, ...]
    issue_reports_by_source: dict[str, dict[str, Any]]
    metrics: dict[str, Any]
    review_priority: str


def confidence_from_score(score: float, conflict_flags: tuple[str, ...], *, non_geometry_score: float) -> str:
    if conflict_flags:
        return "conflict"
    if score >= 80.0:
        return "medium" if non_geometry_score < 55.0 else "high"
    if score >= 60.0:
        return "medium"
    if score >= 40.0:
        return "low"
    return "reject"


def priority_min(current: str, candidate: str) -> str:
    return candidate if PRIORITY_RANK[candidate] < PRIORITY_RANK[current] else current
