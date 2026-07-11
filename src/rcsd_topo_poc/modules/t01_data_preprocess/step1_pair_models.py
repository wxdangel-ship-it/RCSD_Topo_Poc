from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    mainnodeid: Optional[str]
    raw_kind: Optional[int]
    raw_grade: Optional[int]
    kind_2: Optional[int]
    grade_2: Optional[int]
    closed_con: Optional[int]
    geometry: BaseGeometry
    raw_properties: dict[str, Any]


@dataclass(frozen=True)
class RoadRecord:
    road_id: str
    snodeid: str
    enodeid: str
    direction: int
    formway: Optional[int]
    road_kind: Optional[int]
    geometry: BaseGeometry
    raw_properties: dict[str, Any]


@dataclass(frozen=True)
class RuleSpec:
    kind_bits_all: tuple[int, ...]
    grade_eq: Optional[int]
    closed_con_in: tuple[int, ...]
    kind_bits_any: tuple[int, ...] = ()
    kind_values_in: tuple[int, ...] = ()
    grade_in: tuple[int, ...] = ()


@dataclass(frozen=True)
class ThroughRuleSpec:
    incident_road_degree_eq: Optional[int] = 2
    incident_degree_exclude_formway_bits_any: tuple[int, ...] = ()
    disallow_seed_terminate_nodes: bool = False
    disallow_null_mainnode_singleton_seed_terminate_nodes: bool = False
    retain_seed_node_ids_as_through_node_ids: tuple[str, ...] = ()
    allow_seed_search_when_through: bool = False
    continue_after_terminal_candidate: bool = False


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: st
    description: st
    seed_rule: RuleSpec
    terminate_rule: RuleSpec
    through_rule: ThroughRuleSpec = ThroughRuleSpec()
    allow_mirrored_one_sided_reverse_confirm_for_force_terminate_nodes: bool = False
    force_seed_node_ids: tuple[str, ...] = ()
    force_terminate_node_ids: tuple[str, ...] = ()
    hard_stop_node_ids: tuple[str, ...] = ()
    explicit_seed_node_ids: tuple[str, ...] = ()
    explicit_terminate_node_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleEvaluation:
    matched: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SemanticNodeRecord:
    semantic_node_id: str
    representative_node_id: str
    member_node_ids: tuple[str, ...]
    raw_kind: Optional[int]
    raw_grade: Optional[int]
    kind_2: Optional[int]
    grade_2: Optional[int]
    closed_con: Optional[int]
    geometry: BaseGeometry
    raw_properties: dict[str, Any]
    uses_complex_kind_2_128_physical_semantics: bool = False


@dataclass(frozen=True)
class TraversalEdge:
    road_id: str
    from_node: str
    to_node: str


@dataclass(frozen=True)
class SearchCandidate:
    terminal_node_id: str
    path_node_ids: tuple[str, ...]
    path_road_ids: tuple[str, ...]
    through_node_ids: tuple[str, ...]


@dataclass(frozen=True)
class SearchResult:
    start_node_id: str
    candidates: dict[str, SearchCandidate]
    event_counts: dict[str, int]
    event_samples: list[dict[str, Any]]


@dataclass(frozen=True)
class PairRecord:
    pair_id: str
    a_node_id: str
    b_node_id: str
    strategy_id: str
    reverse_confirmed: bool
    forward_path_node_ids: tuple[str, ...]
    forward_path_road_ids: tuple[str, ...]
    reverse_path_node_ids: tuple[str, ...]
    reverse_path_road_ids: tuple[str, ...]
    through_node_ids: tuple[str, ...]
    used_mirrored_reverse_confirm_fallback: bool = False
    kind_2_128_node_ids: tuple[str, ...] = ()
    forward_kind_2_128_node_ids: tuple[str, ...] = ()
    reverse_kind_2_128_node_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Step1StrategyResult:
    strategy: StrategySpec
    seed_ids: list[str]
    terminate_ids: list[str]
    pairs: list[PairRecord]
    pair_summary: dict[str, Any]
    output_files: list[str]


@dataclass(frozen=True)
class Step1GraphContext:
    physical_nodes: dict[str, NodeRecord]
    roads: dict[str, RoadRecord]
    semantic_nodes: dict[str, SemanticNodeRecord]
    physical_to_semantic: dict[str, str]
    directed: dict[str, tuple[TraversalEdge, ...]]
    blocked: dict[str, tuple[TraversalEdge, ...]]
    orphan_ref_count: int
    graph_audit_events: list[dict[str, Any]]


@dataclass(frozen=True)
class Step1StrategyExecution:
    strategy: StrategySpec
    seed_eval: dict[str, RuleEvaluation]
    terminate_eval: dict[str, RuleEvaluation]
    seed_ids: list[str]
    terminate_ids: list[str]
    through_node_ids: set[str]
    search_seed_ids: list[str]
    through_seed_pruned_count: int
    search_results: dict[str, SearchResult]
    search_event_counts: dict[str, int]
    search_event_samples: list[dict[str, Any]]
    pair_candidates: list[PairRecord]
