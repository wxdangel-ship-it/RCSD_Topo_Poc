from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple, Union

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer, write_csv, write_geojson, write_json


REQUIRED_ROAD_FIELDS = ("id", "snodeid", "enodeid", "direction", "formway")
REQUIRED_NODE_FIELDS = ("id", "kind", "grade", "closed_con")
DEFAULT_RUN_ID_PREFIX = "t01_step1_pair_poc_"
SEARCH_EVENT_SAMPLE_LIMIT_PER_TYPE = 100


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    mainnodeid: Optional[str]
    kind: Optional[int]
    grade: Optional[int]
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
    geometry: BaseGeometry
    raw_properties: dict[str, Any]


@dataclass(frozen=True)
class RuleSpec:
    kind_bits_all: tuple[int, ...]
    grade_eq: Optional[int]
    closed_con_in: tuple[int, ...]


@dataclass(frozen=True)
class ThroughRuleSpec:
    incident_road_degree_eq: Optional[int] = 2
    incident_degree_exclude_formway_bits_any: tuple[int, ...] = ()


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    description: str
    seed_rule: RuleSpec
    terminate_rule: RuleSpec
    through_rule: ThroughRuleSpec = ThroughRuleSpec()


@dataclass(frozen=True)
class RuleEvaluation:
    matched: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SemanticNodeRecord:
    semantic_node_id: str
    representative_node_id: str
    member_node_ids: tuple[str, ...]
    kind: Optional[int]
    grade: Optional[int]
    closed_con: Optional[int]
    geometry: BaseGeometry
    raw_properties: dict[str, Any]


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


def _find_repo_root(start: Path) -> Optional[Path]:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "docs").is_dir():
            return candidate
    return None


def _build_default_run_id(now: Optional[datetime] = None) -> str:
    current = datetime.now() if now is None else now
    return f"{DEFAULT_RUN_ID_PREFIX}{current.strftime('%Y%m%d_%H%M%S')}"


def _resolve_out_root(
    *,
    out_root: Optional[Union[str, Path]],
    run_id: Optional[str],
    cwd: Optional[Path] = None,
) -> tuple[Path, str]:
    resolved_run_id = run_id or _build_default_run_id()
    if out_root is not None:
        return Path(out_root), resolved_run_id

    start = Path.cwd() if cwd is None else cwd
    repo_root = _find_repo_root(start)
    if repo_root is None:
        raise ValueError("Cannot infer default out_root because repo root was not found; please pass --out-root.")
    return repo_root / "outputs" / "_work" / "t01_step1_pair_poc" / resolved_run_id, resolved_run_id


def _normalize_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        if stripped == "":
            return None
        return stripped
    return value


def _normalize_id(value: Any) -> Optional[str]:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return None
    if isinstance(normalized, int):
        return str(normalized)
    if isinstance(normalized, float) and normalized.is_integer():
        return str(int(normalized))
    return str(normalized)


def _coerce_int(value: Any) -> Optional[int]:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return None
    if isinstance(normalized, bool):
        return int(normalized)
    if isinstance(normalized, int):
        return normalized
    if isinstance(normalized, float):
        return int(normalized)
    return int(str(normalized), 10)


def _normalize_mainnodeid(value: Any) -> Optional[str]:
    normalized = _normalize_id(value)
    if normalized in {None, "0"}:
        return None
    return normalized


def _sort_key(value: str) -> Tuple[int, Union[int, str]]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _bit_enabled(value: Optional[int], bit_index: int) -> bool:
    if value is None:
        return False
    return bool(value & (1 << bit_index))


def _load_strategy(path: Union[str, Path]) -> StrategySpec:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))

    def _load_rule(payload: dict[str, Any]) -> RuleSpec:
        return RuleSpec(
            kind_bits_all=tuple(int(v) for v in payload.get("kind_bits_all", [])),
            grade_eq=None if payload.get("grade_eq") is None else int(payload["grade_eq"]),
            closed_con_in=tuple(int(v) for v in payload.get("closed_con_in", [])),
        )

    through_payload = doc.get("through_node_rule") or {}
    return StrategySpec(
        strategy_id=str(doc["strategy_id"]),
        description=str(doc.get("description") or ""),
        seed_rule=_load_rule(doc["seed_rule"]),
        terminate_rule=_load_rule(doc["terminate_rule"]),
        through_rule=ThroughRuleSpec(
            incident_road_degree_eq=(
                None
                if through_payload.get("incident_road_degree_eq") is None
                else int(through_payload["incident_road_degree_eq"])
            ),
            incident_degree_exclude_formway_bits_any=tuple(
                int(v) for v in through_payload.get("incident_degree_exclude_formway_bits_any", [])
            ),
        ),
    )


def _validate_required_fields(
    features: list[dict[str, Any]],
    required_fields: tuple[str, ...],
    *,
    layer_label: str,
) -> list[str]:
    issues: list[str] = []
    for index, feature in enumerate(features):
        properties = feature["properties"]
        missing = [field for field in required_fields if field not in properties]
        if missing:
            issues.append(
                f"{layer_label} feature[{index}] missing required fields: {', '.join(sorted(missing))}"
            )
    return issues


def _prepare_nodes(raw_features: list[dict[str, Any]], audit_events: list[dict[str, Any]]) -> dict[str, NodeRecord]:
    nodes: dict[str, NodeRecord] = {}
    for index, feature in enumerate(raw_features):
        props = feature["properties"]
        geometry = feature["geometry"]
        if geometry.geom_type != "Point":
            audit_events.append(
                {
                    "event": "input_geometry_issue",
                    "layer": "node",
                    "feature_index": index,
                    "message": f"Expected Point but got {geometry.geom_type}",
                }
            )
            continue

        node_id = _normalize_id(props.get("id"))
        if node_id is None:
            audit_events.append(
                {
                    "event": "input_field_issue",
                    "layer": "node",
                    "feature_index": index,
                    "message": "Node id is null/empty after normalization",
                }
            )
            continue

        try:
            kind = _coerce_int(props.get("kind"))
            grade = _coerce_int(props.get("grade"))
            closed_con = _coerce_int(props.get("closed_con"))
        except ValueError as exc:
            audit_events.append(
                {
                    "event": "input_field_issue",
                    "layer": "node",
                    "feature_index": index,
                    "node_id": node_id,
                    "message": f"Failed to coerce integer field: {exc}",
                }
            )
            continue

        mainnodeid = _normalize_mainnodeid(props.get("mainnodeid"))

        nodes[node_id] = NodeRecord(
            node_id=node_id,
            mainnodeid=mainnodeid,
            kind=kind,
            grade=grade,
            closed_con=closed_con,
            geometry=geometry,
            raw_properties=dict(props),
        )
    return nodes


def _build_semantic_nodes(
    physical_nodes: dict[str, NodeRecord],
    audit_events: list[dict[str, Any]],
) -> tuple[dict[str, SemanticNodeRecord], dict[str, str]]:
    group_members: dict[str, list[str]] = defaultdict(list)
    for node in physical_nodes.values():
        semantic_node_id = node.mainnodeid or node.node_id
        group_members[semantic_node_id].append(node.node_id)

    semantic_nodes: dict[str, SemanticNodeRecord] = {}
    physical_to_semantic: dict[str, str] = {}

    for semantic_node_id, member_node_ids in group_members.items():
        sorted_member_ids = tuple(sorted(member_node_ids, key=_sort_key))
        for member_node_id in sorted_member_ids:
            physical_to_semantic[member_node_id] = semantic_node_id

        representative_node = physical_nodes.get(semantic_node_id)
        if representative_node is None or representative_node.node_id not in sorted_member_ids:
            representative_node = physical_nodes[sorted_member_ids[0]]
            audit_events.append(
                {
                    "event": "mainnodeid_representative_fallback",
                    "semantic_node_id": semantic_node_id,
                    "representative_node_id": representative_node.node_id,
                    "member_node_ids": list(sorted_member_ids),
                    "message": "Semantic intersection representative node is missing or not part of the member set; falling back to the first member node.",
                }
            )
        elif len(sorted_member_ids) > 1:
            audit_events.append(
                {
                    "event": "semantic_intersection_grouped",
                    "semantic_node_id": semantic_node_id,
                    "representative_node_id": representative_node.node_id,
                    "member_node_ids": list(sorted_member_ids),
                    "message": "mainnodeid group is handled as one semantic intersection in Step1.",
                }
            )

        semantic_nodes[semantic_node_id] = SemanticNodeRecord(
            semantic_node_id=semantic_node_id,
            representative_node_id=representative_node.node_id,
            member_node_ids=sorted_member_ids,
            kind=representative_node.kind,
            grade=representative_node.grade,
            closed_con=representative_node.closed_con,
            geometry=representative_node.geometry,
            raw_properties=dict(representative_node.raw_properties),
        )

    return semantic_nodes, physical_to_semantic


def _prepare_roads(raw_features: list[dict[str, Any]], audit_events: list[dict[str, Any]]) -> dict[str, RoadRecord]:
    roads: dict[str, RoadRecord] = {}
    for index, feature in enumerate(raw_features):
        props = feature["properties"]
        geometry = feature["geometry"]
        if geometry.geom_type not in {"LineString", "MultiLineString"}:
            audit_events.append(
                {
                    "event": "input_geometry_issue",
                    "layer": "road",
                    "feature_index": index,
                    "message": f"Expected LineString/MultiLineString but got {geometry.geom_type}",
                }
            )
            continue

        road_id = _normalize_id(props.get("id"))
        snodeid = _normalize_id(props.get("snodeid"))
        enodeid = _normalize_id(props.get("enodeid"))
        if road_id is None or snodeid is None or enodeid is None:
            audit_events.append(
                {
                    "event": "input_field_issue",
                    "layer": "road",
                    "feature_index": index,
                    "message": "Road id/snodeid/enodeid is null/empty after normalization",
                }
            )
            continue

        try:
            direction = _coerce_int(props.get("direction"))
            formway = _coerce_int(props.get("formway"))
        except ValueError as exc:
            audit_events.append(
                {
                    "event": "input_field_issue",
                    "layer": "road",
                    "feature_index": index,
                    "road_id": road_id,
                    "message": f"Failed to coerce direction: {exc}",
                }
            )
            continue

        if direction not in {0, 1, 2, 3}:
            audit_events.append(
                {
                    "event": "input_field_issue",
                    "layer": "road",
                    "feature_index": index,
                    "road_id": road_id,
                    "message": f"Unsupported direction value: {direction}",
                }
            )
            continue

        roads[road_id] = RoadRecord(
            road_id=road_id,
            snodeid=snodeid,
            enodeid=enodeid,
            direction=direction,
            formway=formway,
            geometry=geometry,
            raw_properties=dict(props),
        )
    return roads


def _evaluate_rule(node: Union[NodeRecord, SemanticNodeRecord], rule: RuleSpec) -> RuleEvaluation:
    reasons: list[str] = []
    for bit_index in rule.kind_bits_all:
        if not _bit_enabled(node.kind, bit_index):
            reasons.append(f"kind_missing_bit_{bit_index}")
    if rule.grade_eq is not None and node.grade != rule.grade_eq:
        reasons.append(f"grade_not_eq_{rule.grade_eq}")
    if rule.closed_con_in and node.closed_con not in rule.closed_con_in:
        joined = "_".join(str(v) for v in rule.closed_con_in)
        reasons.append(f"closed_con_not_in_{joined}")
    return RuleEvaluation(matched=not reasons, reasons=tuple(reasons))


def _build_graph(
    physical_nodes: dict[str, NodeRecord],
    physical_to_semantic: dict[str, str],
    roads: dict[str, RoadRecord],
    audit_events: list[dict[str, Any]],
) -> tuple[dict[str, tuple[TraversalEdge, ...]], dict[str, tuple[TraversalEdge, ...]], dict[str, int], int]:
    directed_lists: dict[str, list[TraversalEdge]] = defaultdict(list)
    directed_lookup: dict[str, set[tuple[str, str]]] = defaultdict(set)
    undirected: dict[str, list[TraversalEdge]] = defaultdict(list)
    road_degree: dict[str, int] = defaultdict(int)
    orphan_ref_count = 0

    for road in roads.values():
        resolved_endpoints: list[tuple[str, str, str]] = []
        for endpoint_label, physical_node_id in (("snodeid", road.snodeid), ("enodeid", road.enodeid)):
            if physical_node_id not in physical_nodes:
                orphan_ref_count += 1
                audit_events.append(
                    {
                        "event": "orphan_ref",
                        "road_id": road.road_id,
                        "endpoint": endpoint_label,
                        "node_id": physical_node_id,
                        "message": "Road endpoint cannot be resolved to node.id",
                    }
                )
            else:
                resolved_endpoints.append(
                    (
                        endpoint_label,
                        physical_node_id,
                        physical_to_semantic.get(physical_node_id, physical_node_id),
                    )
                )

        if len(resolved_endpoints) != 2:
            continue

        a_node = resolved_endpoints[0][2]
        b_node = resolved_endpoints[1][2]
        if a_node == b_node:
            audit_events.append(
                {
                    "event": "internal_semantic_road",
                    "road_id": road.road_id,
                    "semantic_node_id": a_node,
                    "physical_snodeid": road.snodeid,
                    "physical_enodeid": road.enodeid,
                    "message": "Road stays within one semantic intersection after mainnodeid aggregation; Step1 graph ignores it as an external channel edge.",
                }
            )
            continue

        road_degree[a_node] += 1
        road_degree[b_node] += 1
        undirected[a_node].append(TraversalEdge(road.road_id, a_node, b_node))
        undirected[b_node].append(TraversalEdge(road.road_id, b_node, a_node))

        if road.direction in {0, 1, 2}:
            directed_lists[a_node].append(TraversalEdge(road.road_id, a_node, b_node))
            directed_lookup[a_node].add((road.road_id, b_node))
        if road.direction in {0, 1, 3}:
            directed_lists[b_node].append(TraversalEdge(road.road_id, b_node, a_node))
            directed_lookup[b_node].add((road.road_id, a_node))

    directed = {node_id: tuple(edges) for node_id, edges in directed_lists.items()}
    blocked = {
        node_id: tuple(
            edge for edge in edges if (edge.road_id, edge.to_node) not in directed_lookup.get(node_id, set())
        )
        for node_id, edges in undirected.items()
    }
    blocked = {node_id: edges for node_id, edges in blocked.items() if edges}
    return directed, blocked, dict(road_degree), orphan_ref_count


def _append_capped_event_sample(
    event_samples: list[dict[str, Any]],
    sample_counts: dict[str, int],
    payload: dict[str, Any],
) -> None:
    event_name = str(payload["event"])
    if sample_counts.get(event_name, 0) >= SEARCH_EVENT_SAMPLE_LIMIT_PER_TYPE:
        return
    event_samples.append(payload)
    sample_counts[event_name] = sample_counts.get(event_name, 0) + 1


def _record_search_event(
    event_counts: dict[str, int],
    event_samples: list[dict[str, Any]],
    sample_counts: dict[str, int],
    payload: dict[str, Any],
) -> None:
    event_name = str(payload["event"])
    event_counts[event_name] = event_counts.get(event_name, 0) + 1
    _append_capped_event_sample(event_samples, sample_counts, payload)


def _build_candidate_from_parents(
    *,
    start_node_id: str,
    terminal_node_id: str,
    parent_node_ids: dict[str, Optional[str]],
    parent_road_ids: dict[str, str],
    through_node_ids: set[str],
) -> SearchCandidate:
    reverse_node_ids: list[str] = [terminal_node_id]
    reverse_road_ids: list[str] = []
    current_node_id = terminal_node_id

    while current_node_id != start_node_id:
        parent_node_id = parent_node_ids.get(current_node_id)
        road_id = parent_road_ids.get(current_node_id)
        if parent_node_id is None or road_id is None:
            raise ValueError(
                f"Cannot reconstruct path from '{start_node_id}' to '{terminal_node_id}' due to missing parent state."
            )
        reverse_road_ids.append(road_id)
        current_node_id = parent_node_id
        reverse_node_ids.append(current_node_id)

    path_node_ids = tuple(reversed(reverse_node_ids))
    path_road_ids = tuple(reversed(reverse_road_ids))
    through_path_node_ids = tuple(node_id for node_id in path_node_ids[1:-1] if node_id in through_node_ids)
    return SearchCandidate(
        terminal_node_id=terminal_node_id,
        path_node_ids=path_node_ids,
        path_road_ids=path_road_ids,
        through_node_ids=through_path_node_ids,
    )


def _matches_through_rule(
    *,
    road_degree: int,
    through_rule: ThroughRuleSpec,
) -> bool:
    if (
        through_rule.incident_road_degree_eq is not None
        and road_degree == through_rule.incident_road_degree_eq
    ):
        return True

    return False


def _road_matches_any_formway_bit(road: RoadRecord, bits: tuple[int, ...]) -> bool:
    if not bits or road.formway is None:
        return False
    return any(_bit_enabled(road.formway, bit_index) for bit_index in bits)


def _build_incident_road_degree(
    *,
    roads: dict[str, RoadRecord],
    physical_nodes: dict[str, NodeRecord],
    physical_to_semantic: dict[str, str],
    through_rule: ThroughRuleSpec,
) -> dict[str, int]:
    incident_road_degree: dict[str, int] = defaultdict(int)

    for road in roads.values():
        if _road_matches_any_formway_bit(road, through_rule.incident_degree_exclude_formway_bits_any):
            continue

        if road.snodeid not in physical_nodes or road.enodeid not in physical_nodes:
            continue

        a_node = physical_to_semantic.get(road.snodeid, road.snodeid)
        b_node = physical_to_semantic.get(road.enodeid, road.enodeid)
        if a_node == b_node:
            continue

        incident_road_degree[a_node] += 1
        incident_road_degree[b_node] += 1

    return dict(incident_road_degree)


def _search_from_seed(
    start_node_id: str,
    *,
    directed: dict[str, tuple[TraversalEdge, ...]],
    blocked: dict[str, tuple[TraversalEdge, ...]],
    through_node_ids: set[str],
    seed_eval: dict[str, RuleEvaluation],
    terminate_eval: dict[str, RuleEvaluation],
) -> SearchResult:
    queue: deque[str] = deque([start_node_id])
    visited = {start_node_id}
    parent_node_ids: dict[str, Optional[str]] = {start_node_id: None}
    parent_road_ids: dict[str, str] = {}
    candidates: dict[str, SearchCandidate] = {}
    event_counts: dict[str, int] = {}
    event_samples: list[dict[str, Any]] = []
    sample_counts: dict[str, int] = {}

    while queue:
        current_node_id = queue.popleft()

        for edge in blocked.get(current_node_id, ()):
            _record_search_event(
                event_counts,
                event_samples,
                sample_counts,
                {
                    "event": "direction_blocked",
                    "seed_node_id": start_node_id,
                    "from_node_id": current_node_id,
                    "to_node_id": edge.to_node,
                    "road_id": edge.road_id,
                },
            )

        for edge in directed.get(current_node_id, ()):
            next_node_id = edge.to_node
            if next_node_id in visited:
                continue

            visited.add(next_node_id)
            parent_node_ids[next_node_id] = current_node_id
            parent_road_ids[next_node_id] = edge.road_id
            terminate_ok = terminate_eval[next_node_id].matched
            seed_ok = seed_eval[next_node_id].matched
            through_node = next_node_id != start_node_id and next_node_id in through_node_ids

            if through_node:
                _record_search_event(
                    event_counts,
                    event_samples,
                    sample_counts,
                    {
                        "event": "through_continue",
                        "seed_node_id": start_node_id,
                        "node_id": next_node_id,
                        "road_id": edge.road_id,
                    },
                )
                queue.append(next_node_id)
                continue

            if terminate_ok:
                if seed_ok and next_node_id != start_node_id:
                    candidates[next_node_id] = _build_candidate_from_parents(
                        start_node_id=start_node_id,
                        terminal_node_id=next_node_id,
                        parent_node_ids=parent_node_ids,
                        parent_road_ids=parent_road_ids,
                        through_node_ids=through_node_ids,
                    )
                else:
                    _record_search_event(
                        event_counts,
                        event_samples,
                        sample_counts,
                        {
                            "event": "terminal_not_seed",
                            "seed_node_id": start_node_id,
                            "node_id": next_node_id,
                            "terminate_reasons": list(terminate_eval[next_node_id].reasons),
                            "seed_reasons": list(seed_eval[next_node_id].reasons),
                        },
                    )
                continue

            queue.append(next_node_id)

    if not candidates:
        _record_search_event(
            event_counts,
            event_samples,
            sample_counts,
            {"event": "no_terminal_hit", "seed_node_id": start_node_id},
        )

    return SearchResult(
        start_node_id=start_node_id,
        candidates=candidates,
        event_counts=event_counts,
        event_samples=event_samples,
    )


def _pair_id(strategy_id: str, a_node_id: str, b_node_id: str) -> str:
    ordered = sorted((a_node_id, b_node_id), key=_sort_key)
    return f"{strategy_id}:{ordered[0]}__{ordered[1]}"


def _build_pair_records(
    strategy: StrategySpec,
    search_results: dict[str, SearchResult],
    event_counts: dict[str, int],
    event_samples: list[dict[str, Any]],
    sample_counts: dict[str, int],
) -> list[PairRecord]:
    pairs: dict[str, PairRecord] = {}
    for start_node_id, search_result in search_results.items():
        for terminal_node_id, candidate in search_result.candidates.items():
            reverse_result = search_results.get(terminal_node_id)
            reverse_candidate = None if reverse_result is None else reverse_result.candidates.get(start_node_id)
            if reverse_candidate is None:
                _record_search_event(
                    event_counts,
                    event_samples,
                    sample_counts,
                    {
                        "event": "reverse_confirm_fail",
                        "strategy_id": strategy.strategy_id,
                        "a_node_id": start_node_id,
                        "b_node_id": terminal_node_id,
                    },
                )
                continue

            a_node_id, b_node_id = sorted((start_node_id, terminal_node_id), key=_sort_key)
            pair_id = _pair_id(strategy.strategy_id, a_node_id, b_node_id)
            if pair_id in pairs:
                continue

            if start_node_id == a_node_id:
                forward_candidate = candidate
                backward_candidate = reverse_candidate
            else:
                forward_candidate = reverse_candidate
                backward_candidate = candidate

            pairs[pair_id] = PairRecord(
                pair_id=pair_id,
                a_node_id=a_node_id,
                b_node_id=b_node_id,
                strategy_id=strategy.strategy_id,
                reverse_confirmed=True,
                forward_path_node_ids=tuple(forward_candidate.path_node_ids),
                forward_path_road_ids=tuple(forward_candidate.path_road_ids),
                reverse_path_node_ids=tuple(backward_candidate.path_node_ids),
                reverse_path_road_ids=tuple(backward_candidate.path_road_ids),
                through_node_ids=tuple(
                    sorted(
                        set(forward_candidate.through_node_ids + backward_candidate.through_node_ids),
                        key=_sort_key,
                    )
                ),
            )

    return sorted(pairs.values(), key=lambda pair: (_sort_key(pair.a_node_id), _sort_key(pair.b_node_id)))


def build_step1_graph_context(
    *,
    road_path: Union[str, Path],
    node_path: Union[str, Path],
    road_layer: Optional[str] = None,
    road_crs: Optional[str] = None,
    node_layer: Optional[str] = None,
    node_crs: Optional[str] = None,
) -> Step1GraphContext:
    graph_audit_events: list[dict[str, Any]] = []

    road_layer_result = read_vector_layer(road_path, layer_name=road_layer, crs_override=road_crs)
    node_layer_result = read_vector_layer(node_path, layer_name=node_layer, crs_override=node_crs)

    raw_road_features = [
        {"properties": feature.properties, "geometry": feature.geometry} for feature in road_layer_result.features
    ]
    raw_node_features = [
        {"properties": feature.properties, "geometry": feature.geometry} for feature in node_layer_result.features
    ]

    validation_issues = _validate_required_fields(raw_road_features, REQUIRED_ROAD_FIELDS, layer_label="road")
    validation_issues += _validate_required_fields(raw_node_features, REQUIRED_NODE_FIELDS, layer_label="node")
    if validation_issues:
        raise ValueError("; ".join(validation_issues))

    physical_nodes = _prepare_nodes(raw_node_features, graph_audit_events)
    roads = _prepare_roads(raw_road_features, graph_audit_events)
    semantic_nodes, physical_to_semantic = _build_semantic_nodes(physical_nodes, graph_audit_events)
    directed, blocked, _road_degree, orphan_ref_count = _build_graph(
        physical_nodes,
        physical_to_semantic,
        roads,
        graph_audit_events,
    )

    return Step1GraphContext(
        physical_nodes=physical_nodes,
        roads=roads,
        semantic_nodes=semantic_nodes,
        physical_to_semantic=physical_to_semantic,
        directed=directed,
        blocked=blocked,
        orphan_ref_count=orphan_ref_count,
        graph_audit_events=graph_audit_events,
    )


def run_step1_strategy(
    context: Step1GraphContext,
    strategy: StrategySpec,
) -> Step1StrategyExecution:
    seed_eval = {
        node_id: _evaluate_rule(node, strategy.seed_rule) for node_id, node in context.semantic_nodes.items()
    }
    terminate_eval = {
        node_id: _evaluate_rule(node, strategy.terminate_rule) for node_id, node in context.semantic_nodes.items()
    }
    seed_ids = sorted(
        [node_id for node_id, eval_result in seed_eval.items() if eval_result.matched],
        key=_sort_key,
    )
    terminate_ids = sorted(
        [node_id for node_id, eval_result in terminate_eval.items() if eval_result.matched],
        key=_sort_key,
    )
    incident_road_degree = _build_incident_road_degree(
        roads=context.roads,
        physical_nodes=context.physical_nodes,
        physical_to_semantic=context.physical_to_semantic,
        through_rule=strategy.through_rule,
    )
    through_node_ids = {
        node_id
        for node_id in context.semantic_nodes
        if _matches_through_rule(
            road_degree=incident_road_degree.get(node_id, 0),
            through_rule=strategy.through_rule,
        )
    }
    search_seed_ids = [node_id for node_id in seed_ids if node_id not in through_node_ids]
    through_seed_pruned_count = len(seed_ids) - len(search_seed_ids)

    search_results: dict[str, SearchResult] = {}
    search_event_counts: dict[str, int] = {}
    search_event_samples: list[dict[str, Any]] = []
    search_event_sample_counts: dict[str, int] = {}

    for seed_id in search_seed_ids:
        search_result = _search_from_seed(
            seed_id,
            directed=context.directed,
            blocked=context.blocked,
            through_node_ids=through_node_ids,
            seed_eval=seed_eval,
            terminate_eval=terminate_eval,
        )
        search_results[seed_id] = search_result
        for event_name, count in search_result.event_counts.items():
            search_event_counts[event_name] = search_event_counts.get(event_name, 0) + count
        for payload in search_result.event_samples:
            _append_capped_event_sample(search_event_samples, search_event_sample_counts, payload)

    pair_candidates = _build_pair_records(
        strategy,
        search_results,
        search_event_counts,
        search_event_samples,
        search_event_sample_counts,
    )

    return Step1StrategyExecution(
        strategy=strategy,
        seed_eval=seed_eval,
        terminate_eval=terminate_eval,
        seed_ids=seed_ids,
        terminate_ids=terminate_ids,
        through_node_ids=through_node_ids,
        search_seed_ids=search_seed_ids,
        through_seed_pruned_count=through_seed_pruned_count,
        search_results=search_results,
        search_event_counts=search_event_counts,
        search_event_samples=search_event_samples,
        pair_candidates=pair_candidates,
    )


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _road_feature(
    road: RoadRecord,
    *,
    pair_ids: list[str],
    strategy_id: str,
    semantic_snode_id: Optional[str] = None,
    semantic_enode_id: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "geometry": road.geometry,
        "properties": {
            "road_id": road.road_id,
            "strategy_id": strategy_id,
            "pair_ids": ";".join(sorted(pair_ids)),
            "physical_snodeid": road.snodeid,
            "physical_enodeid": road.enodeid,
            "semantic_snode_id": semantic_snode_id,
            "semantic_enodeid": semantic_enode_id,
        },
    }


def _node_feature(
    node: SemanticNodeRecord,
    *,
    strategy_id: str,
    extra_props: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    properties = {
        "node_id": node.semantic_node_id,
        "semantic_node_id": node.semantic_node_id,
        "representative_node_id": node.representative_node_id,
        "member_node_ids": ";".join(node.member_node_ids),
        "member_node_count": len(node.member_node_ids),
        "kind": node.kind,
        "grade": node.grade,
        "closed_con": node.closed_con,
        "strategy_id": strategy_id,
    }
    if extra_props:
        properties.update(extra_props)
    return {"geometry": node.geometry, "properties": properties}


def write_step1_candidate_outputs(
    out_dir: Path,
    *,
    strategy: StrategySpec,
    run_id: str,
    semantic_nodes: dict[str, SemanticNodeRecord],
    physical_nodes: dict[str, NodeRecord],
    physical_to_semantic: dict[str, str],
    roads: dict[str, RoadRecord],
    seed_eval: dict[str, RuleEvaluation],
    terminate_eval: dict[str, RuleEvaluation],
    pairs: list[PairRecord],
    search_event_counts: dict[str, int],
    search_event_samples: list[dict[str, Any]],
    graph_audit_events: list[dict[str, Any]],
    orphan_ref_count: int,
    search_seed_count: int,
    through_seed_pruned_count: int,
) -> Step1StrategyResult:
    out_dir.mkdir(parents=True, exist_ok=True)

    seed_ids = sorted([node_id for node_id, eval_result in seed_eval.items() if eval_result.matched], key=_sort_key)
    terminate_ids = sorted(
        [node_id for node_id, eval_result in terminate_eval.items() if eval_result.matched],
        key=_sort_key,
    )

    seed_nodes_path = out_dir / "seed_nodes.geojson"
    terminate_nodes_path = out_dir / "terminate_nodes.geojson"
    pair_candidate_nodes_path = out_dir / "pair_candidate_nodes.geojson"
    pair_links_candidates_path = out_dir / "pair_links_candidates.geojson"
    pair_support_roads_path = out_dir / "pair_support_roads.geojson"
    pair_candidates_path = out_dir / "pair_candidates.csv"
    pair_summary_path = out_dir / "pair_summary.json"
    rule_audit_path = out_dir / "rule_audit.json"
    search_audit_path = out_dir / "search_audit.json"

    write_geojson(
        seed_nodes_path,
        [_node_feature(semantic_nodes[node_id], strategy_id=strategy.strategy_id) for node_id in seed_ids],
    )
    write_geojson(
        terminate_nodes_path,
        [_node_feature(semantic_nodes[node_id], strategy_id=strategy.strategy_id) for node_id in terminate_ids],
    )

    pair_node_features: list[dict[str, Any]] = []
    pair_link_features: list[dict[str, Any]] = []
    support_road_pairs: dict[str, list[str]] = defaultdict(list)
    pair_table_rows: list[dict[str, Any]] = []
    pair_node_seen: set[tuple[str, str]] = set()

    for pair in pairs:
        for role, node_id in (("A", pair.a_node_id), ("B", pair.b_node_id)):
            key = (pair.pair_id, node_id)
            if key in pair_node_seen:
                continue
            pair_node_seen.add(key)
            pair_node_features.append(
                _node_feature(
                    semantic_nodes[node_id],
                    strategy_id=strategy.strategy_id,
                    extra_props={"pair_id": pair.pair_id, "role": role, "pair_stage": "candidate"},
                )
            )

        pair_link_features.append(
            {
                "geometry": LineString(
                    [
                        (semantic_nodes[pair.a_node_id].geometry.x, semantic_nodes[pair.a_node_id].geometry.y),
                        (semantic_nodes[pair.b_node_id].geometry.x, semantic_nodes[pair.b_node_id].geometry.y),
                    ]
                ),
                "properties": {
                    "pair_id": pair.pair_id,
                    "a_node_id": pair.a_node_id,
                    "b_node_id": pair.b_node_id,
                    "a_representative_node_id": semantic_nodes[pair.a_node_id].representative_node_id,
                    "b_representative_node_id": semantic_nodes[pair.b_node_id].representative_node_id,
                    "strategy_id": pair.strategy_id,
                    "reverse_confirmed": pair.reverse_confirmed,
                    "pair_stage": "candidate",
                },
            }
        )

        road_ids = sorted(set(pair.forward_path_road_ids + pair.reverse_path_road_ids), key=_sort_key)
        for road_id in road_ids:
            support_road_pairs[road_id].append(pair.pair_id)

        pair_table_rows.append(
            {
                "pair_id": pair.pair_id,
                "a_node_id": pair.a_node_id,
                "b_node_id": pair.b_node_id,
                "strategy_id": pair.strategy_id,
                "candidate_status": "candidate",
                "reverse_confirmed": pair.reverse_confirmed,
                "support_info": _compact_json(
                    {
                        "forward_path_node_ids": pair.forward_path_node_ids,
                        "forward_path_road_ids": pair.forward_path_road_ids,
                        "reverse_path_node_ids": pair.reverse_path_node_ids,
                        "reverse_path_road_ids": pair.reverse_path_road_ids,
                        "through_node_ids": pair.through_node_ids,
                    }
                ),
            }
        )

    write_geojson(pair_candidate_nodes_path, pair_node_features)
    write_geojson(pair_links_candidates_path, pair_link_features)
    write_geojson(
        pair_support_roads_path,
        [
            _road_feature(
                roads[road_id],
                pair_ids=pair_ids,
                strategy_id=strategy.strategy_id,
                semantic_snode_id=physical_to_semantic.get(roads[road_id].snodeid),
                semantic_enode_id=physical_to_semantic.get(roads[road_id].enodeid),
            )
            for road_id, pair_ids in sorted(support_road_pairs.items(), key=lambda item: _sort_key(item[0]))
            if road_id in roads
        ],
    )
    write_csv(
        pair_candidates_path,
        pair_table_rows,
        ["pair_id", "a_node_id", "b_node_id", "strategy_id", "candidate_status", "reverse_confirmed", "support_info"],
    )
    write_geojson(out_dir / "pair_nodes.geojson", pair_node_features)
    write_geojson(out_dir / "pair_links.geojson", pair_link_features)
    write_csv(
        out_dir / "pair_table.csv",
        pair_table_rows,
        ["pair_id", "a_node_id", "b_node_id", "strategy_id", "candidate_status", "reverse_confirmed", "support_info"],
    )

    rule_audit_rows = []
    for node_id, node in sorted(semantic_nodes.items(), key=lambda item: _sort_key(item[0])):
        rule_audit_rows.append(
            {
                "node_id": node_id,
                "semantic_node_id": node.semantic_node_id,
                "representative_node_id": node.representative_node_id,
                "member_node_ids": list(node.member_node_ids),
                "member_node_count": len(node.member_node_ids),
                "strategy_id": strategy.strategy_id,
                "seed_match": seed_eval[node_id].matched,
                "seed_reasons": list(seed_eval[node_id].reasons),
                "terminate_match": terminate_eval[node_id].matched,
                "terminate_reasons": list(terminate_eval[node_id].reasons),
                "kind": node.kind,
                "grade": node.grade,
                "closed_con": node.closed_con,
            }
        )

    write_json(rule_audit_path, rule_audit_rows)
    write_json(
        search_audit_path,
        {
            "search_event_counts": dict(sorted(search_event_counts.items())),
            "search_events": search_event_samples,
            "search_event_sample_limit_per_type": SEARCH_EVENT_SAMPLE_LIMIT_PER_TYPE,
            "graph_events": graph_audit_events,
        },
    )

    reverse_confirm_fail_count = search_event_counts.get("reverse_confirm_fail", 0)
    no_terminal_hit_count = search_event_counts.get("no_terminal_hit", 0)
    through_pass_count = search_event_counts.get("through_continue", 0)
    direction_block_count = search_event_counts.get("direction_blocked", 0)

    pair_summary = {
        "strategy_id": strategy.strategy_id,
        "run_id": run_id,
        "out_root": str(out_dir.parent.resolve()),
        "strategy_out_dir": str(out_dir.resolve()),
        "description": strategy.description,
        "step1_output_semantics": "pair_candidates",
        "total_nodes": len(semantic_nodes),
        "total_semantic_nodes": len(semantic_nodes),
        "total_physical_nodes": len(physical_nodes),
        "seed_count": len(seed_ids),
        "search_seed_count": search_seed_count,
        "through_seed_pruned_count": through_seed_pruned_count,
        "terminate_count": len(terminate_ids),
        "candidate_pair_count": len(pairs),
        "pair_count": len(pairs),
        "reverse_confirm_fail_count": reverse_confirm_fail_count,
        "no_terminal_hit_count": no_terminal_hit_count,
        "through_pass_count": through_pass_count,
        "orphan_ref_count": orphan_ref_count,
        "direction_block_count": direction_block_count,
        "search_event_sample_limit_per_type": SEARCH_EVENT_SAMPLE_LIMIT_PER_TYPE,
        "output_files": [
            seed_nodes_path.name,
            terminate_nodes_path.name,
            pair_candidate_nodes_path.name,
            pair_links_candidates_path.name,
            pair_support_roads_path.name,
            pair_candidates_path.name,
            pair_summary_path.name,
            rule_audit_path.name,
            search_audit_path.name,
            "pair_nodes.geojson",
            "pair_links.geojson",
            "pair_table.csv",
        ],
    }
    write_json(pair_summary_path, pair_summary)

    return Step1StrategyResult(
        strategy=strategy,
        seed_ids=seed_ids,
        terminate_ids=terminate_ids,
        pairs=pairs,
        pair_summary=pair_summary,
        output_files=[str(path) for path in sorted(out_dir.iterdir()) if path.is_file()],
    )


def run_step1_pair_poc(
    *,
    road_path: Union[str, Path],
    node_path: Union[str, Path],
    strategy_config_paths: list[Union[str, Path]],
    out_root: Union[str, Path],
    run_id: Optional[str] = None,
    road_layer: Optional[str] = None,
    road_crs: Optional[str] = None,
    node_layer: Optional[str] = None,
    node_crs: Optional[str] = None,
) -> list[Step1StrategyResult]:
    context = build_step1_graph_context(
        road_path=road_path,
        node_path=node_path,
        road_layer=road_layer,
        road_crs=road_crs,
        node_layer=node_layer,
        node_crs=node_crs,
    )

    results: list[Step1StrategyResult] = []
    comparison_summary: list[dict[str, Any]] = []
    resolved_run_id = Path(out_root).name if run_id is None else run_id

    for strategy_path in strategy_config_paths:
        strategy = _load_strategy(strategy_path)
        execution = run_step1_strategy(context, strategy)
        strategy_out_dir = Path(out_root) / strategy.strategy_id
        strategy_result = write_step1_candidate_outputs(
            strategy_out_dir,
            strategy=strategy,
            run_id=resolved_run_id,
            semantic_nodes=context.semantic_nodes,
            physical_nodes=context.physical_nodes,
            physical_to_semantic=context.physical_to_semantic,
            roads=context.roads,
            seed_eval=execution.seed_eval,
            terminate_eval=execution.terminate_eval,
            pairs=execution.pair_candidates,
            search_event_counts=execution.search_event_counts,
            search_event_samples=execution.search_event_samples,
            graph_audit_events=context.graph_audit_events,
            orphan_ref_count=context.orphan_ref_count,
            search_seed_count=len(execution.search_seed_ids),
            through_seed_pruned_count=execution.through_seed_pruned_count,
        )
        results.append(strategy_result)
        comparison_summary.append(strategy_result.pair_summary)

    write_json(Path(out_root) / "strategy_comparison.json", comparison_summary)
    return results


def run_step1_pair_poc_cli(args: argparse.Namespace) -> int:
    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=args.out_root, run_id=args.run_id)
    results = run_step1_pair_poc(
        road_path=args.road_path,
        road_layer=args.road_layer,
        road_crs=args.road_crs,
        node_path=args.node_path,
        node_layer=args.node_layer,
        node_crs=args.node_crs,
        strategy_config_paths=list(args.strategy_config),
        out_root=resolved_out_root,
        run_id=resolved_run_id,
    )

    payload = {
        "run_id": resolved_run_id,
        "out_root": str(resolved_out_root.resolve()),
        "strategies": [
            {
                "strategy_id": result.strategy.strategy_id,
                "candidate_pair_count": result.pair_summary["candidate_pair_count"],
                "pair_count": result.pair_summary["pair_count"],
                "seed_count": result.pair_summary["seed_count"],
                "terminate_count": result.pair_summary["terminate_count"],
                "output_dir": str((resolved_out_root / result.strategy.strategy_id).resolve()),
            }
            for result in results
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
