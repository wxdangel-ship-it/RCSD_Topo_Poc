from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import read_vector_layer, write_csv, write_geojson, write_json


REQUIRED_ROAD_FIELDS = ("id", "snodeid", "enodeid", "direction")
REQUIRED_NODE_FIELDS = ("id", "kind", "grade", "closed_con")
DEFAULT_RUN_ID_PREFIX = "t01_step1_pair_poc_"


@dataclass(frozen=True)
class NodeRecord:
    node_id: str
    kind: int | None
    grade: int | None
    closed_con: int | None
    geometry: BaseGeometry
    raw_properties: dict[str, Any]


@dataclass(frozen=True)
class RoadRecord:
    road_id: str
    snodeid: str
    enodeid: str
    direction: int
    geometry: BaseGeometry
    raw_properties: dict[str, Any]


@dataclass(frozen=True)
class RuleSpec:
    kind_bits_all: tuple[int, ...]
    grade_eq: int | None
    closed_con_in: tuple[int, ...]


@dataclass(frozen=True)
class StrategySpec:
    strategy_id: str
    description: str
    seed_rule: RuleSpec
    terminate_rule: RuleSpec
    through_incident_road_degree: int = 2


@dataclass(frozen=True)
class RuleEvaluation:
    matched: bool
    reasons: tuple[str, ...]


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
    events: list[dict[str, Any]]


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


def _find_repo_root(start: Path) -> Path | None:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "SPEC.md").is_file() and (candidate / "docs").is_dir():
            return candidate
    return None


def _build_default_run_id(now: datetime | None = None) -> str:
    current = datetime.now() if now is None else now
    return f"{DEFAULT_RUN_ID_PREFIX}{current.strftime('%Y%m%d_%H%M%S')}"


def _resolve_out_root(
    *,
    out_root: str | Path | None,
    run_id: str | None,
    cwd: Path | None = None,
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


def _normalize_id(value: Any) -> str | None:
    normalized = _normalize_scalar(value)
    if normalized is None:
        return None
    return str(normalized)


def _coerce_int(value: Any) -> int | None:
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


def _sort_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except ValueError:
        return (1, value)


def _bit_enabled(value: int | None, bit_index: int) -> bool:
    if value is None:
        return False
    return bool(value & (1 << bit_index))


def _load_strategy(path: str | Path) -> StrategySpec:
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
        through_incident_road_degree=int(through_payload.get("incident_road_degree_eq", 2)),
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

        nodes[node_id] = NodeRecord(
            node_id=node_id,
            kind=kind,
            grade=grade,
            closed_con=closed_con,
            geometry=geometry,
            raw_properties=dict(props),
        )
    return nodes


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
            geometry=geometry,
            raw_properties=dict(props),
        )
    return roads


def _evaluate_rule(node: NodeRecord, rule: RuleSpec) -> RuleEvaluation:
    reasons: list[str] = []
    for bit_index in rule.kind_bits_all:
        if not _bit_enabled(node.kind, bit_index):
            reasons.append(f"kind_missing_bit_{bit_index}")
    if rule.grade_eq is not None and node.grade != rule.grade_eq:
        reasons.append(f"grade_not_eq_{rule.grade_eq}")
    if rule.closed_con_in and node.closed_con not in set(rule.closed_con_in):
        joined = "_".join(str(v) for v in rule.closed_con_in)
        reasons.append(f"closed_con_not_in_{joined}")
    return RuleEvaluation(matched=not reasons, reasons=tuple(reasons))


def _build_graph(
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    audit_events: list[dict[str, Any]],
) -> tuple[dict[str, list[TraversalEdge]], dict[str, list[TraversalEdge]], dict[str, set[str]], int]:
    directed: dict[str, list[TraversalEdge]] = defaultdict(list)
    undirected: dict[str, list[TraversalEdge]] = defaultdict(list)
    incident_roads: dict[str, set[str]] = defaultdict(set)
    orphan_ref_count = 0

    for road in roads.values():
        endpoints = []
        for endpoint_label, node_id in (("snodeid", road.snodeid), ("enodeid", road.enodeid)):
            if node_id not in nodes:
                orphan_ref_count += 1
                audit_events.append(
                    {
                        "event": "orphan_ref",
                        "road_id": road.road_id,
                        "endpoint": endpoint_label,
                        "node_id": node_id,
                        "message": "Road endpoint cannot be resolved to node.id",
                    }
                )
            else:
                endpoints.append(node_id)

        if len(endpoints) != 2:
            continue

        a_node, b_node = road.snodeid, road.enodeid
        incident_roads[a_node].add(road.road_id)
        incident_roads[b_node].add(road.road_id)
        undirected[a_node].append(TraversalEdge(road.road_id, a_node, b_node))
        undirected[b_node].append(TraversalEdge(road.road_id, b_node, a_node))

        if road.direction in {0, 1, 2}:
            directed[a_node].append(TraversalEdge(road.road_id, a_node, b_node))
        if road.direction in {0, 1, 3}:
            directed[b_node].append(TraversalEdge(road.road_id, b_node, a_node))

    return directed, undirected, incident_roads, orphan_ref_count


def _is_through_node(
    node_id: str,
    *,
    start_node_id: str,
    strategy: StrategySpec,
    incident_roads: dict[str, set[str]],
) -> bool:
    if node_id == start_node_id:
        return False
    return len(incident_roads.get(node_id, set())) == strategy.through_incident_road_degree


def _search_from_seed(
    start_node_id: str,
    *,
    strategy: StrategySpec,
    directed: dict[str, list[TraversalEdge]],
    undirected: dict[str, list[TraversalEdge]],
    incident_roads: dict[str, set[str]],
    seed_eval: dict[str, RuleEvaluation],
    terminate_eval: dict[str, RuleEvaluation],
) -> SearchResult:
    queue: deque[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = deque(
        [(start_node_id, (start_node_id,), tuple(), tuple())]
    )
    visited = {start_node_id}
    candidates: dict[str, SearchCandidate] = {}
    events: list[dict[str, Any]] = []
    blocked_seen: set[tuple[str, str, str]] = set()

    while queue:
        current_node_id, path_node_ids, path_road_ids, through_node_ids = queue.popleft()
        outgoing_edges = directed.get(current_node_id, [])
        outgoing_keys = {(edge.road_id, edge.to_node) for edge in outgoing_edges}

        for edge in undirected.get(current_node_id, []):
            blocked_key = (current_node_id, edge.road_id, edge.to_node)
            if (edge.road_id, edge.to_node) not in outgoing_keys and blocked_key not in blocked_seen:
                blocked_seen.add(blocked_key)
                events.append(
                    {
                        "event": "direction_blocked",
                        "seed_node_id": start_node_id,
                        "from_node_id": current_node_id,
                        "to_node_id": edge.to_node,
                        "road_id": edge.road_id,
                    }
                )

        for edge in outgoing_edges:
            next_node_id = edge.to_node
            if next_node_id in visited:
                continue

            visited.add(next_node_id)
            next_path_node_ids = (*path_node_ids, next_node_id)
            next_path_road_ids = (*path_road_ids, edge.road_id)
            terminate_ok = terminate_eval[next_node_id].matched
            seed_ok = seed_eval[next_node_id].matched
            through_node = _is_through_node(
                next_node_id,
                start_node_id=start_node_id,
                strategy=strategy,
                incident_roads=incident_roads,
            )

            if through_node:
                next_through = (*through_node_ids, next_node_id)
                events.append(
                    {
                        "event": "through_continue",
                        "seed_node_id": start_node_id,
                        "node_id": next_node_id,
                        "road_id": edge.road_id,
                    }
                )
                queue.append((next_node_id, next_path_node_ids, next_path_road_ids, next_through))
                continue

            if terminate_ok:
                if seed_ok and next_node_id != start_node_id:
                    candidates[next_node_id] = SearchCandidate(
                        terminal_node_id=next_node_id,
                        path_node_ids=tuple(next_path_node_ids),
                        path_road_ids=tuple(next_path_road_ids),
                        through_node_ids=tuple(through_node_ids),
                    )
                else:
                    events.append(
                        {
                            "event": "terminal_not_seed",
                            "seed_node_id": start_node_id,
                            "node_id": next_node_id,
                            "terminate_reasons": list(terminate_eval[next_node_id].reasons),
                            "seed_reasons": list(seed_eval[next_node_id].reasons),
                        }
                    )
                continue

            queue.append((next_node_id, next_path_node_ids, next_path_road_ids, through_node_ids))

    if not candidates:
        events.append({"event": "no_terminal_hit", "seed_node_id": start_node_id})

    return SearchResult(start_node_id=start_node_id, candidates=candidates, events=events)


def _pair_id(strategy_id: str, a_node_id: str, b_node_id: str) -> str:
    ordered = sorted((a_node_id, b_node_id), key=_sort_key)
    return f"{strategy_id}:{ordered[0]}__{ordered[1]}"


def _build_pair_records(
    strategy: StrategySpec,
    search_results: dict[str, SearchResult],
    audit_events: list[dict[str, Any]],
) -> list[PairRecord]:
    pairs: dict[str, PairRecord] = {}
    for start_node_id, search_result in search_results.items():
        for terminal_node_id, candidate in search_result.candidates.items():
            reverse_result = search_results.get(terminal_node_id)
            reverse_candidate = None if reverse_result is None else reverse_result.candidates.get(start_node_id)
            if reverse_candidate is None:
                audit_events.append(
                    {
                        "event": "reverse_confirm_fail",
                        "strategy_id": strategy.strategy_id,
                        "a_node_id": start_node_id,
                        "b_node_id": terminal_node_id,
                    }
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


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _road_feature(road: RoadRecord, *, pair_ids: list[str], strategy_id: str) -> dict[str, Any]:
    return {
        "geometry": road.geometry,
        "properties": {
            "road_id": road.road_id,
            "strategy_id": strategy_id,
            "pair_ids": ";".join(sorted(pair_ids)),
        },
    }


def _node_feature(node: NodeRecord, *, strategy_id: str, extra_props: dict[str, Any] | None = None) -> dict[str, Any]:
    properties = {
        "node_id": node.node_id,
        "kind": node.kind,
        "grade": node.grade,
        "closed_con": node.closed_con,
        "strategy_id": strategy_id,
    }
    if extra_props:
        properties.update(extra_props)
    return {"geometry": node.geometry, "properties": properties}


def _write_strategy_outputs(
    out_dir: Path,
    *,
    strategy: StrategySpec,
    run_id: str,
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    seed_eval: dict[str, RuleEvaluation],
    terminate_eval: dict[str, RuleEvaluation],
    pairs: list[PairRecord],
    search_events: list[dict[str, Any]],
    graph_audit_events: list[dict[str, Any]],
    orphan_ref_count: int,
) -> Step1StrategyResult:
    out_dir.mkdir(parents=True, exist_ok=True)

    seed_ids = sorted([node_id for node_id, eval_result in seed_eval.items() if eval_result.matched], key=_sort_key)
    terminate_ids = sorted(
        [node_id for node_id, eval_result in terminate_eval.items() if eval_result.matched],
        key=_sort_key,
    )

    seed_nodes_path = out_dir / "seed_nodes.geojson"
    terminate_nodes_path = out_dir / "terminate_nodes.geojson"
    pair_nodes_path = out_dir / "pair_nodes.geojson"
    pair_links_path = out_dir / "pair_links.geojson"
    pair_support_roads_path = out_dir / "pair_support_roads.geojson"
    pair_table_path = out_dir / "pair_table.csv"
    pair_summary_path = out_dir / "pair_summary.json"
    rule_audit_path = out_dir / "rule_audit.json"
    search_audit_path = out_dir / "search_audit.json"

    write_geojson(seed_nodes_path, [_node_feature(nodes[node_id], strategy_id=strategy.strategy_id) for node_id in seed_ids])
    write_geojson(
        terminate_nodes_path,
        [_node_feature(nodes[node_id], strategy_id=strategy.strategy_id) for node_id in terminate_ids],
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
                    nodes[node_id],
                    strategy_id=strategy.strategy_id,
                    extra_props={"pair_id": pair.pair_id, "role": role},
                )
            )

        pair_link_features.append(
            {
                "geometry": LineString(
                    [
                        (nodes[pair.a_node_id].geometry.x, nodes[pair.a_node_id].geometry.y),
                        (nodes[pair.b_node_id].geometry.x, nodes[pair.b_node_id].geometry.y),
                    ]
                ),
                "properties": {
                    "pair_id": pair.pair_id,
                    "a_node_id": pair.a_node_id,
                    "b_node_id": pair.b_node_id,
                    "strategy_id": pair.strategy_id,
                    "reverse_confirmed": pair.reverse_confirmed,
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

    write_geojson(pair_nodes_path, pair_node_features)
    write_geojson(pair_links_path, pair_link_features)
    write_geojson(
        pair_support_roads_path,
        [
            _road_feature(roads[road_id], pair_ids=pair_ids, strategy_id=strategy.strategy_id)
            for road_id, pair_ids in sorted(support_road_pairs.items(), key=lambda item: _sort_key(item[0]))
            if road_id in roads
        ],
    )
    write_csv(
        pair_table_path,
        pair_table_rows,
        ["pair_id", "a_node_id", "b_node_id", "strategy_id", "reverse_confirmed", "support_info"],
    )

    rule_audit_rows = []
    for node_id, node in sorted(nodes.items(), key=lambda item: _sort_key(item[0])):
        rule_audit_rows.append(
            {
                "node_id": node_id,
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
    write_json(search_audit_path, {"search_events": search_events, "graph_events": graph_audit_events})

    reverse_confirm_fail_count = sum(1 for event in search_events if event["event"] == "reverse_confirm_fail")
    no_terminal_hit_count = sum(1 for event in search_events if event["event"] == "no_terminal_hit")
    through_pass_count = sum(1 for event in search_events if event["event"] == "through_continue")
    direction_block_count = sum(1 for event in search_events if event["event"] == "direction_blocked")

    pair_summary = {
        "strategy_id": strategy.strategy_id,
        "run_id": run_id,
        "out_root": str(out_dir.parent.resolve()),
        "strategy_out_dir": str(out_dir.resolve()),
        "description": strategy.description,
        "total_nodes": len(nodes),
        "seed_count": len(seed_ids),
        "terminate_count": len(terminate_ids),
        "pair_count": len(pairs),
        "reverse_confirm_fail_count": reverse_confirm_fail_count,
        "no_terminal_hit_count": no_terminal_hit_count,
        "through_pass_count": through_pass_count,
        "orphan_ref_count": orphan_ref_count,
        "direction_block_count": direction_block_count,
        "output_files": [
            seed_nodes_path.name,
            terminate_nodes_path.name,
            pair_nodes_path.name,
            pair_links_path.name,
            pair_support_roads_path.name,
            pair_table_path.name,
            pair_summary_path.name,
            rule_audit_path.name,
            search_audit_path.name,
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
    road_path: str | Path,
    node_path: str | Path,
    strategy_config_paths: list[str | Path],
    out_root: str | Path,
    run_id: str | None = None,
    road_layer: str | None = None,
    road_crs: str | None = None,
    node_layer: str | None = None,
    node_crs: str | None = None,
) -> list[Step1StrategyResult]:
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

    nodes = _prepare_nodes(raw_node_features, graph_audit_events)
    roads = _prepare_roads(raw_road_features, graph_audit_events)
    directed, undirected, incident_roads, orphan_ref_count = _build_graph(nodes, roads, graph_audit_events)

    results: list[Step1StrategyResult] = []
    comparison_summary: list[dict[str, Any]] = []
    resolved_run_id = Path(out_root).name if run_id is None else run_id

    for strategy_path in strategy_config_paths:
        strategy = _load_strategy(strategy_path)
        seed_eval = {node_id: _evaluate_rule(node, strategy.seed_rule) for node_id, node in nodes.items()}
        terminate_eval = {node_id: _evaluate_rule(node, strategy.terminate_rule) for node_id, node in nodes.items()}
        seed_ids = [node_id for node_id, eval_result in seed_eval.items() if eval_result.matched]

        search_results = {
            seed_id: _search_from_seed(
                seed_id,
                strategy=strategy,
                directed=directed,
                undirected=undirected,
                incident_roads=incident_roads,
                seed_eval=seed_eval,
                terminate_eval=terminate_eval,
            )
            for seed_id in seed_ids
        }

        search_events: list[dict[str, Any]] = []
        for result in search_results.values():
            search_events.extend(result.events)

        pairs = _build_pair_records(strategy, search_results, search_events)
        strategy_out_dir = Path(out_root) / strategy.strategy_id
        strategy_result = _write_strategy_outputs(
            strategy_out_dir,
            strategy=strategy,
            run_id=resolved_run_id,
            nodes=nodes,
            roads=roads,
            seed_eval=seed_eval,
            terminate_eval=terminate_eval,
            pairs=pairs,
            search_events=search_events,
            graph_audit_events=graph_audit_events,
            orphan_ref_count=orphan_ref_count,
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
