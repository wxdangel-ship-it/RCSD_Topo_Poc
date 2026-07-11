from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class PairArbitrationOption:
    option_id: str
    pair_id: str
    a_node_id: str
    b_node_id: str
    trunk_mode: str
    counterclockwise_ok: bool
    warning_codes: tuple[str, ...]
    candidate_channel_road_ids: tuple[str, ...]
    pruned_road_ids: tuple[str, ...]
    trunk_road_ids: tuple[str, ...]
    segment_candidate_road_ids: tuple[str, ...]
    segment_road_ids: tuple[str, ...]
    branch_cut_road_ids: tuple[str, ...]
    boundary_terminate_node_ids: tuple[str, ...]
    transition_same_dir_blocked: bool
    support_info: dict[str, Any]


@dataclass(frozen=True)
class PairConflictRecord:
    pair_id: str
    conflict_pair_id: str
    conflict_types: tuple[str, ...]
    shared_road_ids: tuple[str, ...]
    shared_trunk_road_ids: tuple[str, ...]


@dataclass(frozen=True)
class PairArbitrationMetrics:
    endpoint_grade_priority_major: int
    endpoint_grade_priority_minor: int
    endpoint_boundary_penalty: int
    strong_anchor_win_count: int
    corridor_naturalness_score: int
    contested_trunk_coverage_count: int
    contested_trunk_coverage_ratio: float
    pair_support_expansion_penalty: int
    internal_endpoint_penalty: int
    body_connectivity_support: float
    semantic_conflict_penalty: int


@dataclass(frozen=True)
class PairArbitrationDecision:
    pair_id: str
    component_id: str
    single_pair_legal: bool
    arbitration_status: str
    endpoint_boundary_penalty: int
    strong_anchor_win_count: int
    corridor_naturalness_score: int
    contested_trunk_coverage_count: int
    contested_trunk_coverage_ratio: float
    pair_support_expansion_penalty: int
    internal_endpoint_penalty: int
    body_connectivity_support: float
    semantic_conflict_penalty: int
    lose_reason: str
    selected_option_id: Optional[str]


@dataclass(frozen=True)
class ConflictComponentSummary:
    component_id: str
    pair_ids: tuple[str, ...]
    contested_road_ids: tuple[str, ...]
    strong_anchor_node_ids: tuple[str, ...]
    exact_solver_used: bool
    fallback_greedy_used: bool
    selected_option_ids: tuple[str, ...]


@dataclass(frozen=True)
class PairArbitrationOutcome:
    selected_options_by_pair_id: dict[str, PairArbitrationOption]
    decisions: list[PairArbitrationDecision]
    conflict_records: list[PairConflictRecord]
    components: list[ConflictComponentSummary]
