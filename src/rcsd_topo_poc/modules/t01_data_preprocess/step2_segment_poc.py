from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import datetime
from heapq import heappop, heappush
from itertools import count
from pathlib import Path
from typing import Any, Optional, Union

from shapely.geometry import LineString, MultiLineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge

from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_geojson, write_json
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    PairRecord,
    RoadRecord,
    SemanticNodeRecord,
    Step1GraphContext,
    Step1StrategyExecution,
    StrategySpec,
    ThroughRuleSpec,
    TraversalEdge,
    _bit_enabled,
    _find_repo_root,
    _load_strategy,
    _sort_key,
    build_step1_graph_context,
    run_step1_strategy,
    write_step1_candidate_outputs,
)


DEFAULT_RUN_ID_PREFIX = "t01_step2_segment_poc_"
LEFT_TURN_FORMWAY_BIT = 8
MAX_PATHS_PER_DIRECTION = 12
MAX_PATH_DEPTH = 64


@dataclass(frozen=True)
class DirectedPath:
    node_ids: tuple[str, ...]
    road_ids: tuple[str, ...]
    total_length: float


@dataclass(frozen=True)
class TrunkCandidate:
    forward_path: DirectedPath
    reverse_path: DirectedPath
    road_ids: tuple[str, ...]
    signed_area: float
    total_length: float
    left_turn_road_ids: tuple[str, ...]
    is_through_collapsed_corridor: bool = False
    is_bidirectional_minimal_loop: bool = False
    is_semantic_node_group_closure: bool = False


@dataclass(frozen=True)
class PairValidationResult:
    pair_id: str
    a_node_id: str
    b_node_id: str
    candidate_status: str
    validated_status: str
    reject_reason: Optional[str]
    trunk_mode: str
    trunk_found: bool
    counterclockwise_ok: bool
    left_turn_excluded_mode: str
    warning_codes: tuple[str, ...]
    candidate_channel_road_ids: tuple[str, ...]
    pruned_road_ids: tuple[str, ...]
    trunk_road_ids: tuple[str, ...]
    segment_road_ids: tuple[str, ...]
    residual_road_ids: tuple[str, ...]
    branch_cut_road_ids: tuple[str, ...]
    boundary_terminate_node_ids: tuple[str, ...]
    transition_same_dir_blocked: bool
    support_info: dict[str, Any]
    conflict_pair_id: Optional[str] = None


@dataclass(frozen=True)
class Step2StrategyResult:
    strategy: StrategySpec
    segment_summary: dict[str, Any]
    output_files: list[str]
    validations: list[PairValidationResult]


@dataclass(frozen=True)
class NonTrunkComponent:
    component_id: str
    road_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    hits_other_terminate: bool
    terminate_node_ids: tuple[str, ...]
    contains_other_validated_trunk: bool
    conflicting_pair_ids: tuple[str, ...]
    blocked_by_transition_same_dir: bool
    transition_block_infos: tuple[dict[str, Any], ...]
    kept_as_segment_body: bool
    moved_to_step3_residual: bool
    moved_to_branch_cut: bool
    decision_reason: str


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
    return repo_root / "outputs" / "_work" / "t01_step2_segment_poc" / resolved_run_id, resolved_run_id


def _compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _geometry_length(geometry: BaseGeometry) -> float:
    return float(geometry.length) if geometry is not None else 0.0


def _geometry_coords(geometry: BaseGeometry) -> list[tuple[float, float]]:
    if geometry.geom_type == "LineString":
        return [(float(x), float(y)) for x, y in geometry.coords]

    merged = linemerge(geometry)
    if merged.geom_type == "LineString":
        return [(float(x), float(y)) for x, y in merged.coords]

    coords: list[tuple[float, float]] = []
    for part in merged.geoms:
        part_coords = [(float(x), float(y)) for x, y in part.coords]
        if not coords:
            coords.extend(part_coords)
            continue
        if coords[-1] == part_coords[0]:
            coords.extend(part_coords[1:])
        else:
            coords.extend(part_coords)
    return coords


def _build_semantic_endpoints(
    context: Step1GraphContext,
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[TraversalEdge, ...]]]:
    road_endpoints: dict[str, tuple[str, str]] = {}
    undirected_lists: dict[str, list[TraversalEdge]] = defaultdict(list)

    for road in context.roads.values():
        if road.snodeid not in context.physical_nodes or road.enodeid not in context.physical_nodes:
            continue

        semantic_snode_id = context.physical_to_semantic.get(road.snodeid, road.snodeid)
        semantic_enode_id = context.physical_to_semantic.get(road.enodeid, road.enodeid)
        if semantic_snode_id == semantic_enode_id:
            continue

        road_endpoints[road.road_id] = (semantic_snode_id, semantic_enode_id)
        undirected_lists[semantic_snode_id].append(TraversalEdge(road.road_id, semantic_snode_id, semantic_enode_id))
        undirected_lists[semantic_enode_id].append(TraversalEdge(road.road_id, semantic_enode_id, semantic_snode_id))

    return road_endpoints, {node_id: tuple(edges) for node_id, edges in undirected_lists.items()}


def _road_matches_formway_bit(road: RoadRecord, bit_index: int) -> bool:
    if road.formway is None:
        return False
    return _bit_enabled(road.formway, bit_index)


def _road_matches_any_formway_bits(road: RoadRecord, bits: tuple[int, ...]) -> bool:
    if not bits or road.formway is None:
        return False
    return any(_bit_enabled(road.formway, bit_index) for bit_index in bits)


def _build_candidate_channel(
    pair: PairRecord,
    *,
    undirected_adjacency: dict[str, tuple[TraversalEdge, ...]],
    boundary_node_ids: set[str],
) -> tuple[set[str], set[str]]:
    protected = {pair.a_node_id, pair.b_node_id}
    support_node_ids = set(pair.forward_path_node_ids) | set(pair.reverse_path_node_ids)
    support_road_ids = set(pair.forward_path_road_ids) | set(pair.reverse_path_road_ids)
    candidate_road_ids: set[str] = set(support_road_ids)
    boundary_terminate_ids: set[str] = set()

    for start_node_id in sorted(support_node_ids, key=_sort_key):
        for edge in undirected_adjacency.get(start_node_id, ()):
            if edge.road_id in candidate_road_ids:
                continue

            previous_node_id = start_node_id
            current_node_id = edge.to_node
            current_road_id = edge.road_id
            candidate_road_ids.add(current_road_id)

            while True:
                if current_node_id in support_node_ids:
                    break
                if current_node_id in boundary_node_ids and current_node_id not in protected:
                    boundary_terminate_ids.add(current_node_id)
                    break

                next_edges = [
                    next_edge
                    for next_edge in undirected_adjacency.get(current_node_id, ())
                    if next_edge.to_node != previous_node_id and next_edge.road_id not in candidate_road_ids
                ]
                if not next_edges:
                    break
                if len(next_edges) > 1:
                    break

                next_edge = next_edges[0]
                candidate_road_ids.add(next_edge.road_id)
                previous_node_id = current_node_id
                current_node_id = next_edge.to_node

    return candidate_road_ids, boundary_terminate_ids


def _build_incident_map(
    road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
) -> dict[str, set[str]]:
    incident: dict[str, set[str]] = defaultdict(set)
    for road_id in road_ids:
        endpoints = road_endpoints.get(road_id)
        if endpoints is None:
            continue
        a_node_id, b_node_id = endpoints
        incident[a_node_id].add(road_id)
        incident[b_node_id].add(road_id)
    return incident


def _collect_components(
    road_ids: set[str],
    *,
    road_endpoints: dict[str, tuple[str, str]],
) -> list[tuple[tuple[str, ...], tuple[str, ...]]]:
    if not road_ids:
        return []

    incident = _build_incident_map(road_ids, road_endpoints)
    components: list[tuple[tuple[str, ...], tuple[str, ...]]] = []
    visited_nodes: set[str] = set()

    for start_node_id in sorted(incident.keys(), key=_sort_key):
        if start_node_id in visited_nodes:
            continue
        queue: deque[str] = deque([start_node_id])
        component_node_ids: set[str] = set()
        component_road_ids: set[str] = set()
        visited_nodes.add(start_node_id)

        while queue:
            node_id = queue.popleft()
            component_node_ids.add(node_id)
            for road_id in incident.get(node_id, set()):
                component_road_ids.add(road_id)
                other_node_id = _other_endpoint(road_id, node_id, road_endpoints)
                if other_node_id in visited_nodes:
                    continue
                visited_nodes.add(other_node_id)
                queue.append(other_node_id)

        if component_road_ids:
            components.append(
                (
                    tuple(sorted(component_road_ids, key=_sort_key)),
                    tuple(sorted(component_node_ids, key=_sort_key)),
                )
            )

    return components


def _other_endpoint(road_id: str, node_id: str, road_endpoints: dict[str, tuple[str, str]]) -> str:
    a_node_id, b_node_id = road_endpoints[road_id]
    return b_node_id if node_id == a_node_id else a_node_id


def _remaining_degree(node_id: str, incident: dict[str, set[str]], remaining_road_ids: set[str]) -> int:
    return sum(1 for road_id in incident.get(node_id, set()) if road_id in remaining_road_ids)


def _path_exists_undirected(
    start_node_id: str,
    end_node_id: str,
    *,
    road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
) -> bool:
    if start_node_id == end_node_id:
        return True
    if not road_ids:
        return False

    incident = _build_incident_map(road_ids, road_endpoints)
    queue: deque[str] = deque([start_node_id])
    visited = {start_node_id}

    while queue:
        current_node_id = queue.popleft()
        for road_id in incident.get(current_node_id, set()):
            next_node_id = _other_endpoint(road_id, current_node_id, road_endpoints)
            if next_node_id == end_node_id:
                return True
            if next_node_id in visited:
                continue
            visited.add(next_node_id)
            queue.append(next_node_id)

    return False


def _count_components(
    road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
) -> int:
    if not road_ids:
        return 0

    incident = _build_incident_map(road_ids, road_endpoints)
    remaining_nodes = {node_id for node_id, node_road_ids in incident.items() if node_road_ids}
    component_count = 0
    visited: set[str] = set()

    for node_id in sorted(remaining_nodes, key=_sort_key):
        if node_id in visited:
            continue
        component_count += 1
        queue: deque[str] = deque([node_id])
        visited.add(node_id)
        while queue:
            current_node_id = queue.popleft()
            for road_id in incident.get(current_node_id, set()):
                next_node_id = _other_endpoint(road_id, current_node_id, road_endpoints)
                if next_node_id in visited:
                    continue
                visited.add(next_node_id)
                queue.append(next_node_id)

    return component_count


def _collect_component_road_ids(
    start_node_id: str,
    *,
    road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
) -> set[str]:
    if not road_ids:
        return set()

    incident = _build_incident_map(road_ids, road_endpoints)
    if start_node_id not in incident:
        return set()

    component_road_ids: set[str] = set()
    visited_nodes: set[str] = {start_node_id}
    queue: deque[str] = deque([start_node_id])

    while queue:
        node_id = queue.popleft()
        for road_id in incident.get(node_id, set()):
            if road_id not in road_ids:
                continue
            component_road_ids.add(road_id)
            other_node_id = _other_endpoint(road_id, node_id, road_endpoints)
            if other_node_id in visited_nodes:
                continue
            visited_nodes.add(other_node_id)
            queue.append(other_node_id)

    return component_road_ids


def _find_bridge_road_ids(
    road_ids: set[str],
    *,
    road_endpoints: dict[str, tuple[str, str]],
) -> set[str]:
    if not road_ids:
        return set()

    adjacency: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for road_id in road_ids:
        snode_id, enode_id = road_endpoints[road_id]
        adjacency[snode_id].append((enode_id, road_id))
        adjacency[enode_id].append((snode_id, road_id))

    timer = count()
    disc: dict[str, int] = {}
    low: dict[str, int] = {}
    bridge_road_ids: set[str] = set()

    def dfs(node_id: str, parent_road_id: Optional[str]) -> None:
        disc[node_id] = next(timer)
        low[node_id] = disc[node_id]

        for next_node_id, road_id in adjacency.get(node_id, []):
            if road_id == parent_road_id:
                continue
            if next_node_id not in disc:
                dfs(next_node_id, road_id)
                low[node_id] = min(low[node_id], low[next_node_id])
                if low[next_node_id] > disc[node_id]:
                    bridge_road_ids.add(road_id)
            else:
                low[node_id] = min(low[node_id], disc[next_node_id])

    for node_id in sorted(adjacency.keys(), key=_sort_key):
        if node_id not in disc:
            dfs(node_id, None)

    return bridge_road_ids


def _prune_candidate_channel(
    pair: PairRecord,
    *,
    candidate_road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
    terminate_ids: set[str],
    hard_stop_node_ids: set[str],
) -> tuple[set[str], list[dict[str, Any]], bool]:
    protected = {pair.a_node_id, pair.b_node_id}
    remaining_road_ids = set(candidate_road_ids)
    incident = _build_incident_map(remaining_road_ids, road_endpoints)
    queue: deque[str] = deque(
        node_id
        for node_id in sorted(incident.keys(), key=_sort_key)
        if node_id not in protected and _remaining_degree(node_id, incident, remaining_road_ids) == 1
    )
    branch_cut_infos: list[dict[str, Any]] = []

    while queue:
        node_id = queue.popleft()
        if node_id in protected:
            continue
        if _remaining_degree(node_id, incident, remaining_road_ids) != 1:
            continue

        road_id = next(road_id for road_id in incident.get(node_id, set()) if road_id in remaining_road_ids)
        other_node_id = _other_endpoint(road_id, node_id, road_endpoints)
        if node_id in hard_stop_node_ids and node_id not in protected:
            cut_reason = "branch_leads_to_historical_boundary"
        elif node_id in terminate_ids and node_id not in protected:
            cut_reason = "branch_leads_to_other_terminate"
        else:
            cut_reason = "branch_backtrack_prune"
        branch_cut_infos.append(
            {
                "road_id": road_id,
                "cut_reason": cut_reason,
                "from_node_id": node_id,
                "to_node_id": other_node_id,
            }
        )
        remaining_road_ids.remove(road_id)
        incident[node_id].discard(road_id)
        incident[other_node_id].discard(road_id)

        if other_node_id not in protected and _remaining_degree(other_node_id, incident, remaining_road_ids) == 1:
            queue.append(other_node_id)

    disconnected_after_prune = True
    if remaining_road_ids:
        disconnected_after_prune = (
            _count_components(remaining_road_ids, road_endpoints) != 1
            or not _path_exists_undirected(
                pair.a_node_id,
                pair.b_node_id,
                road_ids=remaining_road_ids,
                road_endpoints=road_endpoints,
            )
        )

    return remaining_road_ids, branch_cut_infos, disconnected_after_prune


def _refine_segment_roads(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    pruned_road_ids: set[str],
    trunk_road_ids: tuple[str, ...],
    through_rule: ThroughRuleSpec,
) -> tuple[tuple[str, ...], list[dict[str, Any]]]:
    if not pruned_road_ids:
        return (), []

    remaining_road_ids = set(pruned_road_ids)
    trunk_road_id_set = set(trunk_road_ids)
    segment_cut_infos: list[dict[str, Any]] = []

    # Step1 uses these formway bits to collapse pseudo-intersection branches.
    # Step2 should not keep the same roads in final segment retention.
    if through_rule.incident_degree_exclude_formway_bits_any:
        for road_id in sorted(tuple(remaining_road_ids), key=_sort_key):
            if road_id in trunk_road_id_set:
                continue
            road = context.roads[road_id]
            if not _road_matches_any_formway_bits(road, through_rule.incident_degree_exclude_formway_bits_any):
                continue
            remaining_road_ids.remove(road_id)
            from_node_id, to_node_id = road_endpoints[road_id]
            segment_cut_infos.append(
                {
                    "road_id": road_id,
                    "cut_reason": "segment_exclude_formway",
                    "from_node_id": from_node_id,
                    "to_node_id": to_node_id,
                }
            )

    protected_nodes = {pair.a_node_id, pair.b_node_id}
    changed = True
    while changed and remaining_road_ids:
        changed = False
        incident = _build_incident_map(remaining_road_ids, road_endpoints)
        queue: deque[str] = deque(
            node_id
            for node_id in sorted(incident.keys(), key=_sort_key)
            if node_id not in protected_nodes and _remaining_degree(node_id, incident, remaining_road_ids) == 1
        )

        while queue:
            node_id = queue.popleft()
            if node_id in protected_nodes:
                continue
            if _remaining_degree(node_id, incident, remaining_road_ids) != 1:
                continue

            road_id = next(road_id for road_id in incident.get(node_id, set()) if road_id in remaining_road_ids)
            if road_id in trunk_road_id_set:
                continue

            other_node_id = _other_endpoint(road_id, node_id, road_endpoints)
            remaining_road_ids.remove(road_id)
            incident[node_id].discard(road_id)
            incident[other_node_id].discard(road_id)
            segment_cut_infos.append(
                {
                    "road_id": road_id,
                    "cut_reason": "segment_backtrack_prune",
                    "from_node_id": node_id,
                    "to_node_id": other_node_id,
                }
            )
            changed = True

            if other_node_id not in protected_nodes and _remaining_degree(other_node_id, incident, remaining_road_ids) == 1:
                queue.append(other_node_id)

        bridge_road_ids = _find_bridge_road_ids(remaining_road_ids, road_endpoints=road_endpoints)
        removable_bridge_road_ids = sorted(bridge_road_ids - trunk_road_id_set, key=_sort_key)
        if removable_bridge_road_ids:
            changed = True
            for road_id in removable_bridge_road_ids:
                if road_id not in remaining_road_ids:
                    continue
                from_node_id, to_node_id = road_endpoints[road_id]
                remaining_road_ids.remove(road_id)
                segment_cut_infos.append(
                    {
                        "road_id": road_id,
                        "cut_reason": "segment_bridge_prune",
                        "from_node_id": from_node_id,
                        "to_node_id": to_node_id,
                    }
                )

    component_road_ids = _collect_component_road_ids(
        pair.a_node_id,
        road_ids=remaining_road_ids,
        road_endpoints=road_endpoints,
    )
    for road_id in sorted(remaining_road_ids - component_road_ids, key=_sort_key):
        from_node_id, to_node_id = road_endpoints[road_id]
        segment_cut_infos.append(
            {
                "road_id": road_id,
                "cut_reason": "segment_disconnected_component_prune",
                "from_node_id": from_node_id,
                "to_node_id": to_node_id,
            }
        )

    final_road_ids = component_road_ids if component_road_ids else trunk_road_id_set
    if not trunk_road_id_set.issubset(final_road_ids):
        final_road_ids |= trunk_road_id_set

    path_road_ids = _collect_segment_path_road_ids(
        pair,
        context=context,
        road_endpoints=road_endpoints,
        allowed_road_ids=final_road_ids,
    )
    removable_non_path_road_ids = sorted((final_road_ids - path_road_ids) - trunk_road_id_set, key=_sort_key)
    for road_id in removable_non_path_road_ids:
        from_node_id, to_node_id = road_endpoints[road_id]
        segment_cut_infos.append(
            {
                "road_id": road_id,
                "cut_reason": "segment_non_path_prune",
                "from_node_id": from_node_id,
                "to_node_id": to_node_id,
            }
        )
    if path_road_ids:
        final_road_ids = path_road_ids | trunk_road_id_set

    return tuple(sorted(final_road_ids, key=_sort_key)), segment_cut_infos


def _collect_internal_boundary_nodes(
    pair: PairRecord,
    *,
    candidate: TrunkCandidate,
    hard_stop_node_ids: set[str],
) -> tuple[str, ...]:
    if not hard_stop_node_ids:
        return ()
    internal_nodes = (set(candidate.forward_path.node_ids[1:-1]) | set(candidate.reverse_path.node_ids[1:-1])) - {
        pair.a_node_id,
        pair.b_node_id,
    }
    return tuple(sorted((node_id for node_id in internal_nodes if node_id in hard_stop_node_ids), key=_sort_key))


def _component_to_dict(component: NonTrunkComponent) -> dict[str, Any]:
    return {
        "component_id": component.component_id,
        "road_ids": list(component.road_ids),
        "node_ids": list(component.node_ids),
        "hits_other_terminate": component.hits_other_terminate,
        "terminate_node_ids": list(component.terminate_node_ids),
        "contains_other_validated_trunk": component.contains_other_validated_trunk,
        "conflicting_pair_ids": list(component.conflicting_pair_ids),
        "blocked_by_transition_same_dir": component.blocked_by_transition_same_dir,
        "transition_block_infos": list(component.transition_block_infos),
        "kept_as_segment_body": component.kept_as_segment_body,
        "moved_to_step3_residual": component.moved_to_step3_residual,
        "moved_to_branch_cut": component.moved_to_branch_cut,
        "decision_reason": component.decision_reason,
    }


def _tighten_validated_segment_components(
    validations: list[PairValidationResult],
    *,
    execution: Step1StrategyExecution,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
) -> list[PairValidationResult]:
    pair_lookup = {pair.pair_id: pair for pair in execution.pair_candidates}
    terminate_ids = set(execution.terminate_ids)
    hard_stop_node_ids = set(execution.strategy.hard_stop_node_ids)
    boundary_node_ids = terminate_ids | hard_stop_node_ids
    validated_trunk_owner_by_road = {
        road_id: validation.pair_id
        for validation in validations
        if validation.validated_status == "validated"
        for road_id in validation.trunk_road_ids
    }
    direction_support_index = _build_direction_support_index(context)

    tightened: list[PairValidationResult] = []
    for validation in validations:
        if validation.validated_status != "validated":
            tightened.append(validation)
            continue

        pair = pair_lookup.get(validation.pair_id)
        if pair is None:
            tightened.append(validation)
            continue

        support_info = dict(validation.support_info)
        branch_cut_infos = list(support_info.get("branch_cut_infos", []))
        residual_infos: list[dict[str, Any]] = []
        component_infos: list[dict[str, Any]] = []
        branch_cut_seen = {(info.get("road_id"), info.get("cut_reason")) for info in branch_cut_infos}

        trunk_road_id_set = set(validation.trunk_road_ids)
        pruned_road_id_set = set(validation.pruned_road_ids)

        if validation.trunk_mode == "through_collapsed_corridor":
            body_candidate_road_ids = set(validation.trunk_road_ids)
            refine_cut_infos: list[dict[str, Any]] = []
        else:
            body_candidate_road_ids, refine_cut_infos = _refine_segment_roads(
                pair,
                context=context,
                road_endpoints=road_endpoints,
                pruned_road_ids=pruned_road_id_set,
                trunk_road_ids=validation.trunk_road_ids,
                through_rule=execution.strategy.through_rule,
            )
            body_candidate_road_ids = set(body_candidate_road_ids)

        body_candidate_non_trunk_road_ids = body_candidate_road_ids - trunk_road_id_set

        refine_cut_reason_by_road: dict[str, set[str]] = defaultdict(set)
        for info in refine_cut_infos:
            road_id = str(info["road_id"])
            refine_cut_reason_by_road[road_id].add(str(info["cut_reason"]))

        non_trunk_road_ids = pruned_road_id_set - trunk_road_id_set
        segment_body_non_trunk_road_ids: set[str] = set()
        residual_road_ids: set[str] = set()
        transition_same_dir_blocked = False

        components = _collect_components(non_trunk_road_ids, road_endpoints=road_endpoints)
        for component_index, (component_road_ids, component_node_ids) in enumerate(components, start=1):
            component_road_id_set = set(component_road_ids)
            terminate_node_ids = tuple(
                sorted((set(component_node_ids) & (boundary_node_ids - {pair.a_node_id, pair.b_node_id})), key=_sort_key)
            )
            hits_historical_boundary = bool(set(terminate_node_ids) & hard_stop_node_ids)
            conflicting_pair_ids = tuple(
                sorted(
                    {
                        validated_trunk_owner_by_road[road_id]
                        for road_id in component_road_ids
                        if road_id in validated_trunk_owner_by_road and validated_trunk_owner_by_road[road_id] != validation.pair_id
                    },
                    key=_sort_key,
                )
            )
            transition_block_infos = _collect_transition_same_dir_block_infos(
                component_road_ids=component_road_ids,
                component_node_ids=component_node_ids,
                trunk_road_ids=validation.trunk_road_ids,
                road_endpoints=road_endpoints,
                direction_support_index=direction_support_index,
            )
            hits_other_terminate = bool(terminate_node_ids)
            contains_other_validated_trunk = bool(conflicting_pair_ids)
            blocked_by_transition_same_dir = bool(transition_block_infos)

            kept_as_segment_body = False
            moved_to_step3_residual = False
            moved_to_branch_cut = False
            decision_reason = "weak_rule_residual"

            if hits_historical_boundary:
                moved_to_branch_cut = True
                decision_reason = "hits_historical_boundary"
            elif hits_other_terminate:
                moved_to_branch_cut = True
                decision_reason = "hits_other_terminate"
            elif contains_other_validated_trunk:
                moved_to_branch_cut = True
                decision_reason = "contains_other_validated_trunk"
            elif blocked_by_transition_same_dir:
                moved_to_step3_residual = True
                transition_same_dir_blocked = True
                decision_reason = "transition_same_dir_block"
            elif component_road_id_set.issubset(body_candidate_non_trunk_road_ids):
                kept_as_segment_body = True
                decision_reason = "segment_body"
            else:
                moved_to_step3_residual = True
                component_hint_reasons = {
                    reason
                    for road_id in component_road_ids
                    for reason in refine_cut_reason_by_road.get(road_id, set())
                }
                if "segment_exclude_formway" in component_hint_reasons:
                    decision_reason = "step1_formway_excluded"
                else:
                    decision_reason = "weak_rule_residual"

            component = NonTrunkComponent(
                component_id=f"{validation.pair_id}:C{component_index}",
                road_ids=component_road_ids,
                node_ids=component_node_ids,
                hits_other_terminate=hits_other_terminate,
                terminate_node_ids=terminate_node_ids,
                contains_other_validated_trunk=contains_other_validated_trunk,
                conflicting_pair_ids=conflicting_pair_ids,
                blocked_by_transition_same_dir=blocked_by_transition_same_dir,
                transition_block_infos=transition_block_infos,
                kept_as_segment_body=kept_as_segment_body,
                moved_to_step3_residual=moved_to_step3_residual,
                moved_to_branch_cut=moved_to_branch_cut,
                decision_reason=decision_reason,
            )
            component_infos.append(_component_to_dict(component))

            if kept_as_segment_body:
                segment_body_non_trunk_road_ids.update(component_road_ids)
            elif moved_to_step3_residual:
                residual_road_ids.update(component_road_ids)
                for road_id in component_road_ids:
                    residual_infos.append(
                        {
                            "road_id": road_id,
                            "component_id": component.component_id,
                            "residual_reason": decision_reason,
                            "blocked_by_transition_same_dir": blocked_by_transition_same_dir,
                            "conflicting_pair_ids": list(conflicting_pair_ids),
                            "terminate_node_ids": list(terminate_node_ids),
                            "hint_cut_reasons": sorted(refine_cut_reason_by_road.get(road_id, set()), key=_sort_key),
                        }
                    )
            elif moved_to_branch_cut:
                for road_id in component_road_ids:
                    key = (road_id, decision_reason)
                    if key in branch_cut_seen:
                        continue
                    branch_cut_infos.append(
                        {
                            "road_id": road_id,
                            "cut_reason": decision_reason,
                            "component_id": component.component_id,
                            "conflicting_pair_ids": list(conflicting_pair_ids),
                            "terminate_node_ids": list(terminate_node_ids),
                        }
                    )
                    branch_cut_seen.add(key)

        segment_body_road_ids = tuple(sorted(trunk_road_id_set | segment_body_non_trunk_road_ids, key=_sort_key))
        residual_road_ids_tuple = tuple(sorted(residual_road_ids, key=_sort_key))
        support_info["branch_cut_infos"] = branch_cut_infos
        support_info["non_trunk_components"] = component_infos
        support_info["step3_residual_infos"] = residual_infos
        support_info["segment_body_road_ids"] = list(segment_body_road_ids)
        support_info["residual_road_ids"] = list(residual_road_ids_tuple)

        tightened.append(
            replace(
                validation,
                segment_road_ids=segment_body_road_ids,
                residual_road_ids=residual_road_ids_tuple,
                branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                transition_same_dir_blocked=transition_same_dir_blocked,
                support_info=support_info,
            )
        )

    return tightened


def _build_filtered_directed_adjacency(
    context: Step1GraphContext,
    *,
    allowed_road_ids: set[str],
    exclude_left_turn: bool,
    left_turn_formway_bit: int,
) -> dict[str, tuple[TraversalEdge, ...]]:
    filtered_lists: dict[str, list[TraversalEdge]] = defaultdict(list)
    for node_id, edges in context.directed.items():
        for edge in edges:
            if edge.road_id not in allowed_road_ids:
                continue
            road = context.roads.get(edge.road_id)
            if road is None:
                continue
            if exclude_left_turn and _road_matches_formway_bit(road, left_turn_formway_bit):
                continue
            filtered_lists[node_id].append(edge)
    return {node_id: tuple(edges) for node_id, edges in filtered_lists.items()}


def _build_direction_support_index(
    context: Step1GraphContext,
) -> dict[str, dict[str, set[str]]]:
    support_index: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for from_node_id, edges in context.directed.items():
        for edge in edges:
            support_index[from_node_id][edge.road_id].add("out")
            support_index[edge.to_node][edge.road_id].add("in")
    return {
        node_id: {road_id: set(directions) for road_id, directions in road_map.items()}
        for node_id, road_map in support_index.items()
    }


def _collect_transition_same_dir_block_infos(
    *,
    component_road_ids: tuple[str, ...],
    component_node_ids: tuple[str, ...],
    trunk_road_ids: tuple[str, ...],
    road_endpoints: dict[str, tuple[str, str]],
    direction_support_index: dict[str, dict[str, set[str]]],
) -> tuple[dict[str, Any], ...]:
    component_road_id_set = set(component_road_ids)
    trunk_road_id_set = set(trunk_road_ids)
    block_infos: list[dict[str, Any]] = []

    for node_id in component_node_ids:
        node_component_road_ids = sorted(
            (road_id for road_id in component_road_id_set if node_id in road_endpoints.get(road_id, ())),
            key=_sort_key,
        )
        node_trunk_road_ids = sorted(
            (road_id for road_id in trunk_road_id_set if node_id in road_endpoints.get(road_id, ())),
            key=_sort_key,
        )
        if not node_component_road_ids or not node_trunk_road_ids:
            continue

        component_dirs: set[str] = set()
        trunk_dirs: set[str] = set()
        for road_id in node_component_road_ids:
            component_dirs.update(direction_support_index.get(node_id, {}).get(road_id, set()))
        for road_id in node_trunk_road_ids:
            trunk_dirs.update(direction_support_index.get(node_id, {}).get(road_id, set()))

        same_single_dir = len(component_dirs) == 1 and component_dirs == trunk_dirs
        mirrored_bidirectional = (
            component_dirs == {"in", "out"}
            and trunk_dirs == {"in", "out"}
            and len(node_component_road_ids) >= 2
            and len(node_trunk_road_ids) >= 2
        )

        if same_single_dir or mirrored_bidirectional:
            direction = "both" if mirrored_bidirectional else next(iter(component_dirs))
            block_infos.append(
                {
                    "node_id": node_id,
                    "direction": direction,
                    "component_road_ids": node_component_road_ids,
                    "trunk_road_ids": node_trunk_road_ids,
                    "message": (
                        "Transition expansion is blocked because component roads mirror the trunk direction signature "
                        "at the attachment node."
                    ),
                }
            )

    return tuple(block_infos)


def _enumerate_simple_paths(
    *,
    adjacency: dict[str, tuple[TraversalEdge, ...]],
    roads: dict[str, RoadRecord],
    start_node_id: str,
    end_node_id: str,
    max_paths: int = MAX_PATHS_PER_DIRECTION,
    max_depth: int = MAX_PATH_DEPTH,
) -> list[DirectedPath]:
    results: list[DirectedPath] = []
    sequence = count()
    heap: list[tuple[float, int, int, str, tuple[str, ...], tuple[str, ...], frozenset[str]]] = []
    heappush(
        heap,
        (
            0.0,
            0,
            next(sequence),
            start_node_id,
            (start_node_id,),
            (),
            frozenset({start_node_id}),
        ),
    )

    while heap and len(results) < max_paths:
        total_length, depth, _index, current_node_id, node_ids, road_ids, visited_nodes = heappop(heap)
        if current_node_id == end_node_id and road_ids:
            results.append(DirectedPath(node_ids=node_ids, road_ids=road_ids, total_length=total_length))
            continue
        if depth >= max_depth:
            continue

        for edge in adjacency.get(current_node_id, ()):
            if edge.to_node in visited_nodes:
                continue
            road = roads.get(edge.road_id)
            if road is None:
                continue
            heappush(
                heap,
                (
                    total_length + _geometry_length(road.geometry),
                    depth + 1,
                    next(sequence),
                    edge.to_node,
                    node_ids + (edge.to_node,),
                    road_ids + (edge.road_id,),
                    visited_nodes | {edge.to_node},
                ),
            )

    return results


def _build_filtered_undirected_adjacency(
    *,
    road_endpoints: dict[str, tuple[str, str]],
    allowed_road_ids: set[str],
) -> dict[str, tuple[TraversalEdge, ...]]:
    adjacency_lists: dict[str, list[TraversalEdge]] = defaultdict(list)
    for road_id in sorted(allowed_road_ids, key=_sort_key):
        if road_id not in road_endpoints:
            continue
        snode_id, enode_id = road_endpoints[road_id]
        adjacency_lists[snode_id].append(TraversalEdge(road_id, snode_id, enode_id))
        adjacency_lists[enode_id].append(TraversalEdge(road_id, enode_id, snode_id))
    return {node_id: tuple(edges) for node_id, edges in adjacency_lists.items()}


def _collect_segment_path_road_ids(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    allowed_road_ids: set[str],
) -> set[str]:
    adjacency = _build_filtered_undirected_adjacency(
        road_endpoints=road_endpoints,
        allowed_road_ids=allowed_road_ids,
    )
    paths = _enumerate_simple_paths(
        adjacency=adjacency,
        roads=context.roads,
        start_node_id=pair.a_node_id,
        end_node_id=pair.b_node_id,
    )
    path_road_ids: set[str] = set()
    for path in paths:
        path_road_ids.update(path.road_ids)
    return path_road_ids


def _oriented_road_coords(
    road: RoadRecord,
    *,
    from_node_id: str,
    to_node_id: str,
    road_endpoints: dict[str, tuple[str, str]],
) -> list[tuple[float, float]]:
    coords = _geometry_coords(road.geometry)
    semantic_snode_id, semantic_enode_id = road_endpoints[road.road_id]
    if (from_node_id, to_node_id) == (semantic_snode_id, semantic_enode_id):
        return coords
    if (from_node_id, to_node_id) == (semantic_enode_id, semantic_snode_id):
        return list(reversed(coords))
    return coords


def _path_coords(
    path: DirectedPath,
    *,
    roads: dict[str, RoadRecord],
    road_endpoints: dict[str, tuple[str, str]],
) -> list[tuple[float, float]]:
    coords: list[tuple[float, float]] = []
    for index, road_id in enumerate(path.road_ids):
        road = roads[road_id]
        part_coords = _oriented_road_coords(
            road,
            from_node_id=path.node_ids[index],
            to_node_id=path.node_ids[index + 1],
            road_endpoints=road_endpoints,
        )
        if not coords:
            coords.extend(part_coords)
            continue
        if coords[-1] == part_coords[0]:
            coords.extend(part_coords[1:])
        else:
            coords.extend(part_coords)
    return coords


def _signed_ring_area(coords: list[tuple[float, float]]) -> float:
    if len(coords) < 3:
        return 0.0
    ring = list(coords)
    if ring[0] != ring[-1]:
        ring.append(ring[0])

    twice_area = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        twice_area += (x1 * y2) - (x2 * y1)
    return twice_area / 2.0


def _path_oriented_edges(path: DirectedPath) -> tuple[tuple[str, str, str], ...]:
    if len(path.node_ids) != len(path.road_ids) + 1:
        return ()
    return tuple(
        (road_id, path.node_ids[index], path.node_ids[index + 1])
        for index, road_id in enumerate(path.road_ids)
    )


def _is_bidirectional_minimal_loop_candidate(
    *,
    forward_path: DirectedPath,
    reverse_path: DirectedPath,
    roads: dict[str, RoadRecord],
) -> bool:
    if not forward_path.road_ids or not reverse_path.road_ids:
        return False

    forward_edges = _path_oriented_edges(forward_path)
    reverse_edges = _path_oriented_edges(reverse_path)
    if not forward_edges or not reverse_edges:
        return False

    shared_road_ids = set(forward_path.road_ids) & set(reverse_path.road_ids)
    if not shared_road_ids:
        return False
    if any(roads[road_id].direction not in {0, 1} for road_id in shared_road_ids):
        return False
    if set(forward_edges) & set(reverse_edges):
        return False

    forward_orientations: dict[str, set[tuple[str, str]]] = defaultdict(set)
    reverse_orientations: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for road_id, from_node_id, to_node_id in forward_edges:
        forward_orientations[road_id].add((from_node_id, to_node_id))
    for road_id, from_node_id, to_node_id in reverse_edges:
        reverse_orientations[road_id].add((from_node_id, to_node_id))

    for road_id in shared_road_ids:
        if len(forward_orientations[road_id]) != 1 or len(reverse_orientations[road_id]) != 1:
            return False
        ((forward_from, forward_to),) = tuple(forward_orientations[road_id])
        ((reverse_from, reverse_to),) = tuple(reverse_orientations[road_id])
        if (forward_from, forward_to) != (reverse_to, reverse_from):
            return False

    indegree: dict[str, int] = defaultdict(int)
    outdegree: dict[str, int] = defaultdict(int)
    weak_adjacency: dict[str, set[str]] = defaultdict(set)
    active_nodes: set[str] = set()
    for _, from_node_id, to_node_id in forward_edges + reverse_edges:
        active_nodes.add(from_node_id)
        active_nodes.add(to_node_id)
        outdegree[from_node_id] += 1
        indegree[to_node_id] += 1
        weak_adjacency[from_node_id].add(to_node_id)
        weak_adjacency[to_node_id].add(from_node_id)

    if not active_nodes:
        return False
    if any(indegree[node_id] != outdegree[node_id] for node_id in active_nodes):
        return False

    queue: deque[str] = deque([next(iter(active_nodes))])
    visited: set[str] = set()
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        queue.extend(neighbor for neighbor in weak_adjacency.get(node_id, ()) if neighbor not in visited)
    return visited == active_nodes


def _is_semantic_node_group_loop_candidate(
    *,
    forward_path: DirectedPath,
    reverse_path: DirectedPath,
) -> bool:
    if not forward_path.road_ids or not reverse_path.road_ids:
        return False

    forward_edges = _path_oriented_edges(forward_path)
    reverse_edges = _path_oriented_edges(reverse_path)
    if not forward_edges or not reverse_edges:
        return False
    if set(forward_edges) & set(reverse_edges):
        return False

    indegree: dict[str, int] = defaultdict(int)
    outdegree: dict[str, int] = defaultdict(int)
    weak_adjacency: dict[str, set[str]] = defaultdict(set)
    active_nodes: set[str] = set()
    for _, from_node_id, to_node_id in forward_edges + reverse_edges:
        active_nodes.add(from_node_id)
        active_nodes.add(to_node_id)
        outdegree[from_node_id] += 1
        indegree[to_node_id] += 1
        weak_adjacency[from_node_id].add(to_node_id)
        weak_adjacency[to_node_id].add(from_node_id)

    if len(active_nodes) < 2:
        return False
    if any(indegree[node_id] != outdegree[node_id] for node_id in active_nodes):
        return False

    queue: deque[str] = deque([next(iter(active_nodes))])
    visited: set[str] = set()
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        queue.extend(neighbor for neighbor in weak_adjacency.get(node_id, ()) if neighbor not in visited)
    return visited == active_nodes


def _trunk_candidate_mode(candidate: TrunkCandidate) -> str:
    if candidate.is_through_collapsed_corridor:
        return "through_collapsed_corridor"
    return "counterclockwise_loop"


def _trunk_candidate_counterclockwise_ok(candidate: TrunkCandidate) -> bool:
    return (
        candidate.is_bidirectional_minimal_loop
        or candidate.is_semantic_node_group_closure
        or candidate.signed_area > 1e-6
    )


def _collect_trunk_candidates(
    *,
    forward_paths: list[DirectedPath],
    reverse_paths: list[DirectedPath],
    roads: dict[str, RoadRecord],
    road_endpoints: dict[str, tuple[str, str]],
    left_turn_formway_bit: int,
    allow_bidirectional_overlap: bool = False,
) -> tuple[list[TrunkCandidate], bool]:
    counterclockwise_candidates: list[TrunkCandidate] = []
    clockwise_only_found = False

    for forward_path in forward_paths:
        for reverse_path in reverse_paths:
            combined_road_ids = tuple(
                sorted(set(forward_path.road_ids + reverse_path.road_ids), key=_sort_key)
            )
            is_bidirectional_minimal_loop = False
            is_semantic_node_group_closure = False
            if len(combined_road_ids) != len(forward_path.road_ids) + len(reverse_path.road_ids):
                if not allow_bidirectional_overlap:
                    continue
                is_bidirectional_minimal_loop = _is_bidirectional_minimal_loop_candidate(
                    forward_path=forward_path,
                    reverse_path=reverse_path,
                    roads=roads,
                )
                if not is_bidirectional_minimal_loop:
                    continue

            ring_coords = _path_coords(forward_path, roads=roads, road_endpoints=road_endpoints)
            reverse_coords = _path_coords(reverse_path, roads=roads, road_endpoints=road_endpoints)
            if not ring_coords or not reverse_coords:
                continue
            ring_coords.extend(reverse_coords[1:])

            signed_area = _signed_ring_area(ring_coords)
            if abs(signed_area) <= 1e-6 and not is_bidirectional_minimal_loop:
                is_semantic_node_group_closure = _is_semantic_node_group_loop_candidate(
                    forward_path=forward_path,
                    reverse_path=reverse_path,
                )
                if not is_semantic_node_group_closure:
                    continue

            left_turn_road_ids = tuple(
                road_id
                for road_id in combined_road_ids
                if _road_matches_formway_bit(roads[road_id], left_turn_formway_bit)
            )
            candidate = TrunkCandidate(
                forward_path=forward_path,
                reverse_path=reverse_path,
                road_ids=combined_road_ids,
                signed_area=signed_area,
                total_length=forward_path.total_length + reverse_path.total_length,
                left_turn_road_ids=left_turn_road_ids,
                is_bidirectional_minimal_loop=is_bidirectional_minimal_loop,
                is_semantic_node_group_closure=is_semantic_node_group_closure,
            )
            if signed_area > 0 or is_bidirectional_minimal_loop or is_semantic_node_group_closure:
                counterclockwise_candidates.append(candidate)
            else:
                clockwise_only_found = True

    counterclockwise_candidates.sort(key=lambda item: (abs(item.signed_area), item.total_length, len(item.road_ids)))
    return counterclockwise_candidates, clockwise_only_found


def _evaluate_trunk(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    pruned_road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
    through_rule: ThroughRuleSpec,
    formway_mode: str,
    left_turn_formway_bit: int,
) -> tuple[Optional[TrunkCandidate], Optional[str], tuple[str, ...]]:
    collapsed_candidate: Optional[TrunkCandidate] = None
    collapsed_warnings: tuple[str, ...] = ()
    if pair.through_node_ids:
        collapsed_candidate, collapsed_warnings = _evaluate_through_collapsed_corridor(
            pair,
            context=context,
            pruned_road_ids=pruned_road_ids,
            road_endpoints=road_endpoints,
            through_rule=through_rule,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
        )

    base_adjacency = _build_filtered_directed_adjacency(
        context,
        allowed_road_ids=pruned_road_ids,
        exclude_left_turn=False,
        left_turn_formway_bit=left_turn_formway_bit,
    )
    base_forward_paths = _enumerate_simple_paths(
        adjacency=base_adjacency,
        roads=context.roads,
        start_node_id=pair.a_node_id,
        end_node_id=pair.b_node_id,
    )
    base_reverse_paths = _enumerate_simple_paths(
        adjacency=base_adjacency,
        roads=context.roads,
        start_node_id=pair.b_node_id,
        end_node_id=pair.a_node_id,
    )
    base_candidates, base_clockwise_only = _collect_trunk_candidates(
        forward_paths=base_forward_paths,
        reverse_paths=base_reverse_paths,
        roads=context.roads,
        road_endpoints=road_endpoints,
        left_turn_formway_bit=left_turn_formway_bit,
        allow_bidirectional_overlap=True,
    )

    if formway_mode == "strict":
        strict_adjacency = _build_filtered_directed_adjacency(
            context,
            allowed_road_ids=pruned_road_ids,
            exclude_left_turn=True,
            left_turn_formway_bit=left_turn_formway_bit,
        )
        strict_forward_paths = _enumerate_simple_paths(
            adjacency=strict_adjacency,
            roads=context.roads,
            start_node_id=pair.a_node_id,
            end_node_id=pair.b_node_id,
        )
        strict_reverse_paths = _enumerate_simple_paths(
            adjacency=strict_adjacency,
            roads=context.roads,
            start_node_id=pair.b_node_id,
            end_node_id=pair.a_node_id,
        )
        strict_candidates, strict_clockwise_only = _collect_trunk_candidates(
            forward_paths=strict_forward_paths,
            reverse_paths=strict_reverse_paths,
            roads=context.roads,
            road_endpoints=road_endpoints,
            left_turn_formway_bit=left_turn_formway_bit,
            allow_bidirectional_overlap=True,
        )
        if collapsed_candidate is not None:
            return collapsed_candidate, None, collapsed_warnings
        if strict_candidates:
            return strict_candidates[0], None, ()
        if base_candidates:
            return None, "left_turn_only_polluted_trunk", ()
        if strict_clockwise_only or base_clockwise_only:
            return None, "only_clockwise_loop", ()
        return None, "no_valid_trunk", ()

    if collapsed_candidate is not None:
        return collapsed_candidate, None, collapsed_warnings
    if not base_candidates:
        if base_clockwise_only:
            return None, "only_clockwise_loop", ()
        return None, "no_valid_trunk", ()

    warnings: tuple[str, ...] = ()
    chosen = base_candidates[0]
    if formway_mode == "audit_only" and chosen.left_turn_road_ids:
        warnings = ("formway_unreliable_warning",)
    return chosen, None, warnings


def _evaluate_through_collapsed_corridor(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    pruned_road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
    through_rule: ThroughRuleSpec,
    formway_mode: str,
    left_turn_formway_bit: int,
) -> tuple[Optional[TrunkCandidate], tuple[str, ...]]:
    if not pair.through_node_ids:
        return None, ()
    if through_rule.incident_road_degree_eq is None:
        return None, ()

    support_road_ids = tuple(sorted(set(pair.forward_path_road_ids + pair.reverse_path_road_ids), key=_sort_key))
    if not support_road_ids:
        return None, ()
    if any(road_id not in pruned_road_ids for road_id in support_road_ids):
        return None, ()
    if pair.forward_path_node_ids != tuple(reversed(pair.reverse_path_node_ids)):
        return None, ()
    if pair.forward_path_road_ids != tuple(reversed(pair.reverse_path_road_ids)):
        return None, ()

    for node_id in pair.through_node_ids:
        retained_degree = 0
        for road_id in pruned_road_ids:
            endpoints = road_endpoints.get(road_id)
            if endpoints is None or node_id not in endpoints:
                continue
            road = context.roads[road_id]
            if _road_matches_any_formway_bits(road, through_rule.incident_degree_exclude_formway_bits_any):
                continue
            retained_degree += 1
        if retained_degree != through_rule.incident_road_degree_eq:
            return None, ()

    if formway_mode == "strict":
        if any(_road_matches_formway_bit(context.roads[road_id], left_turn_formway_bit) for road_id in support_road_ids):
            return None, ()
        filtered_support_road_ids = support_road_ids
        warnings: tuple[str, ...] = ()
    else:
        filtered_support_road_ids = support_road_ids
        warnings = ()
        if formway_mode == "audit_only" and any(
            _road_matches_formway_bit(context.roads[road_id], left_turn_formway_bit) for road_id in support_road_ids
        ):
            warnings = ("formway_unreliable_warning",)

    support_adjacency = _build_filtered_directed_adjacency(
        context,
        allowed_road_ids=set(filtered_support_road_ids),
        exclude_left_turn=formway_mode == "strict",
        left_turn_formway_bit=left_turn_formway_bit,
    )
    forward_paths = _enumerate_simple_paths(
        adjacency=support_adjacency,
        roads=context.roads,
        start_node_id=pair.a_node_id,
        end_node_id=pair.b_node_id,
        max_paths=1,
        max_depth=max(4, len(pair.forward_path_node_ids) + 1),
    )
    reverse_paths = _enumerate_simple_paths(
        adjacency=support_adjacency,
        roads=context.roads,
        start_node_id=pair.b_node_id,
        end_node_id=pair.a_node_id,
        max_paths=1,
        max_depth=max(4, len(pair.reverse_path_node_ids) + 1),
    )
    if not forward_paths or not reverse_paths:
        return None, ()

    forward_path = forward_paths[0]
    reverse_path = reverse_paths[0]
    if tuple(sorted(set(forward_path.road_ids + reverse_path.road_ids), key=_sort_key)) != support_road_ids:
        return None, ()

    left_turn_road_ids = tuple(
        road_id
        for road_id in support_road_ids
        if _road_matches_formway_bit(context.roads[road_id], left_turn_formway_bit)
    )
    return (
        TrunkCandidate(
            forward_path=forward_path,
            reverse_path=reverse_path,
            road_ids=support_road_ids,
            signed_area=0.0,
            total_length=forward_path.total_length + reverse_path.total_length,
            left_turn_road_ids=left_turn_road_ids,
            is_through_collapsed_corridor=True,
        ),
        warnings,
    )


def _line_feature(
    *,
    a_node: SemanticNodeRecord,
    b_node: SemanticNodeRecord,
    properties: dict[str, Any],
) -> dict[str, Any]:
    return {
        "geometry": LineString([(a_node.geometry.x, a_node.geometry.y), (b_node.geometry.x, b_node.geometry.y)]),
        "properties": properties,
    }


def _road_feature(
    road: RoadRecord,
    *,
    pair_id: str,
    strategy_id: str,
    layer_role: str,
    extra_props: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    properties = {
        "road_id": road.road_id,
        "pair_id": pair_id,
        "strategy_id": strategy_id,
        "layer_role": layer_role,
        "direction": road.direction,
        "formway": road.formway,
    }
    if extra_props:
        properties.update(extra_props)
    return {"geometry": road.geometry, "properties": properties}


def _collect_multiline_parts(road_ids: tuple[str, ...], roads: dict[str, RoadRecord]) -> list[list[tuple[float, float]]]:
    parts: list[list[tuple[float, float]]] = []
    for road_id in road_ids:
        road = roads[road_id]
        geometry = road.geometry
        if geometry.geom_type == "LineString":
            parts.append([(float(x), float(y)) for x, y in geometry.coords])
            continue

        merged = linemerge(geometry)
        if merged.geom_type == "LineString":
            parts.append([(float(x), float(y)) for x, y in merged.coords])
            continue

        for part in merged.geoms:
            parts.append([(float(x), float(y)) for x, y in part.coords])
    return parts


def _pair_multiline_feature(
    *,
    context: Step1GraphContext,
    pair_id: str,
    a_node_id: str,
    b_node_id: str,
    strategy_id: str,
    layer_role: str,
    road_ids: tuple[str, ...],
    extra_props: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    if not road_ids:
        return None

    parts = _collect_multiline_parts(road_ids, context.roads)
    if not parts:
        return None

    properties = {
        "pair_id": pair_id,
        "a_node_id": a_node_id,
        "b_node_id": b_node_id,
        "strategy_id": strategy_id,
        "layer_role": layer_role,
        "road_count": len(road_ids),
        "road_ids": list(road_ids),
        "road_ids_text": ",".join(road_ids),
    }
    if extra_props:
        properties.update(extra_props)

    return {"geometry": MultiLineString(parts), "properties": properties}


def _write_step2_outputs(
    out_dir: Path,
    *,
    strategy: StrategySpec,
    run_id: str,
    context: Step1GraphContext,
    validations: list[PairValidationResult],
    formway_mode: str,
    debug: bool,
) -> Step2StrategyResult:
    validated_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    validated_link_features: list[dict[str, Any]] = []
    candidate_channel_features: list[dict[str, Any]] = []
    trunk_features: list[dict[str, Any]] = []
    segment_body_features: list[dict[str, Any]] = []
    step3_residual_features: list[dict[str, Any]] = []
    trunk_member_features: list[dict[str, Any]] = []
    segment_body_member_features: list[dict[str, Any]] = []
    step3_residual_member_features: list[dict[str, Any]] = []
    branch_cut_features: list[dict[str, Any]] = []
    working_graph_debug_features: list[dict[str, Any]] = []

    total_branch_cut_count = 0
    clockwise_reject_count = 0
    left_turn_trunk_reject_count = 0
    disconnected_after_prune_count = 0
    shared_trunk_conflict_count = 0
    formway_warning_count = 0
    branch_cut_component_keys: set[tuple[str, str]] = set()
    other_terminate_cut_keys: set[tuple[str, str]] = set()
    other_trunk_conflict_keys: set[tuple[str, str]] = set()
    transition_same_dir_block_keys: set[tuple[str, str]] = set()
    residual_component_keys: set[tuple[str, str]] = set()

    for validation in validations:
        support_info = dict(validation.support_info)
        branch_cut_infos = list(support_info.get("branch_cut_infos", []))
        residual_infos = list(support_info.get("step3_residual_infos", []))
        component_infos = list(support_info.get("non_trunk_components", []))
        validation_rows.append(
            {
                "pair_id": validation.pair_id,
                "a_node_id": validation.a_node_id,
                "b_node_id": validation.b_node_id,
                "candidate_status": validation.candidate_status,
                "validated_status": validation.validated_status,
                "reject_reason": validation.reject_reason or "",
                "trunk_mode": validation.trunk_mode,
                "trunk_found": validation.trunk_found,
                "counterclockwise_ok": validation.counterclockwise_ok,
                "segment_body_road_count": len(validation.segment_road_ids),
                "residual_road_count": len(validation.residual_road_ids),
                "transition_same_dir_blocked": validation.transition_same_dir_blocked,
                "left_turn_excluded_mode": validation.left_turn_excluded_mode,
                "support_info": _compact_json(support_info),
            }
        )

        if validation.validated_status == "validated":
            validated_rows.append(
                {
                    "pair_id": validation.pair_id,
                    "a_node_id": validation.a_node_id,
                    "b_node_id": validation.b_node_id,
                    "trunk_mode": validation.trunk_mode,
                    "left_turn_excluded_mode": validation.left_turn_excluded_mode,
                    "warning_codes": ";".join(validation.warning_codes),
                    "segment_body_road_count": len(validation.segment_road_ids),
                    "residual_road_count": len(validation.residual_road_ids),
                }
            )
            validated_link_features.append(
                _line_feature(
                    a_node=context.semantic_nodes[validation.a_node_id],
                    b_node=context.semantic_nodes[validation.b_node_id],
                    properties={
                        "pair_id": validation.pair_id,
                        "a_node_id": validation.a_node_id,
                        "b_node_id": validation.b_node_id,
                        "strategy_id": strategy.strategy_id,
                        "validated_status": validation.validated_status,
                        "trunk_mode": validation.trunk_mode,
                    },
                )
            )
        else:
            rejected_rows.append(
                {
                    "pair_id": validation.pair_id,
                    "a_node_id": validation.a_node_id,
                    "b_node_id": validation.b_node_id,
                    "reject_reason": validation.reject_reason or "",
                    "warning_codes": ";".join(validation.warning_codes),
                    "conflict_pair_id": validation.conflict_pair_id or "",
                }
            )

        if validation.reject_reason == "only_clockwise_loop":
            clockwise_reject_count += 1
        if validation.reject_reason == "left_turn_only_polluted_trunk":
            left_turn_trunk_reject_count += 1
        if validation.reject_reason == "disconnected_after_prune":
            disconnected_after_prune_count += 1
        if validation.reject_reason == "shared_trunk_conflict":
            shared_trunk_conflict_count += 1
        if "formway_unreliable_warning" in validation.warning_codes:
            formway_warning_count += 1

        total_branch_cut_count += len(branch_cut_infos)
        for branch_cut_info in branch_cut_infos:
            cut_key = (
                validation.pair_id,
                str(branch_cut_info.get("component_id") or f"{branch_cut_info.get('cut_reason')}::{branch_cut_info.get('road_id')}"),
            )
            branch_cut_component_keys.add(cut_key)
            if branch_cut_info.get("cut_reason") in {"hits_other_terminate", "branch_leads_to_other_terminate"}:
                other_terminate_cut_keys.add(cut_key)
            if branch_cut_info.get("cut_reason") == "contains_other_validated_trunk":
                other_trunk_conflict_keys.add(cut_key)

        for component_info in component_infos:
            component_key = (validation.pair_id, str(component_info.get("component_id", "")))
            if component_info.get("moved_to_step3_residual"):
                residual_component_keys.add(component_key)
            if component_info.get("blocked_by_transition_same_dir"):
                transition_same_dir_block_keys.add(component_key)

        if validation.validated_status == "validated":
            trunk_feature = _pair_multiline_feature(
                context=context,
                pair_id=validation.pair_id,
                a_node_id=validation.a_node_id,
                b_node_id=validation.b_node_id,
                strategy_id=strategy.strategy_id,
                layer_role="trunk",
                road_ids=validation.trunk_road_ids,
                extra_props={
                    "validated_status": validation.validated_status,
                    "trunk_mode": validation.trunk_mode,
                    "warning_codes": list(validation.warning_codes),
                    "left_turn_excluded_mode": validation.left_turn_excluded_mode,
                },
            )
            if trunk_feature is not None:
                trunk_features.append(trunk_feature)

            segment_body_feature = _pair_multiline_feature(
                context=context,
                pair_id=validation.pair_id,
                a_node_id=validation.a_node_id,
                b_node_id=validation.b_node_id,
                strategy_id=strategy.strategy_id,
                layer_role="segment_body",
                road_ids=validation.segment_road_ids,
                extra_props={
                    "validated_status": validation.validated_status,
                    "trunk_mode": validation.trunk_mode,
                    "warning_codes": list(validation.warning_codes),
                    "left_turn_excluded_mode": validation.left_turn_excluded_mode,
                },
            )
            if segment_body_feature is not None:
                segment_body_features.append(segment_body_feature)

            residual_feature = _pair_multiline_feature(
                context=context,
                pair_id=validation.pair_id,
                a_node_id=validation.a_node_id,
                b_node_id=validation.b_node_id,
                strategy_id=strategy.strategy_id,
                layer_role="step3_residual",
                road_ids=validation.residual_road_ids,
                extra_props={
                    "validated_status": validation.validated_status,
                    "trunk_mode": validation.trunk_mode,
                    "warning_codes": list(validation.warning_codes),
                    "left_turn_excluded_mode": validation.left_turn_excluded_mode,
                },
            )
            if residual_feature is not None:
                step3_residual_features.append(residual_feature)

        for road_id in validation.candidate_channel_road_ids:
            road = context.roads[road_id]
            candidate_channel_features.append(
                _road_feature(
                    road,
                    pair_id=validation.pair_id,
                    strategy_id=strategy.strategy_id,
                    layer_role="candidate_channel",
                )
            )
            working_graph_debug_features.append(
                _road_feature(
                    road,
                    pair_id=validation.pair_id,
                    strategy_id=strategy.strategy_id,
                    layer_role="working_graph",
                    extra_props={"debug_stage": "candidate_channel"},
                )
            )

        for branch_cut_info in branch_cut_infos:
            road = context.roads[branch_cut_info["road_id"]]
            branch_cut_props = {key: value for key, value in branch_cut_info.items() if key != "road_id"}
            branch_cut_features.append(
                _road_feature(
                    road,
                    pair_id=validation.pair_id,
                    strategy_id=strategy.strategy_id,
                    layer_role="branch_cut",
                    extra_props=branch_cut_props,
                )
            )
            working_graph_debug_features.append(
                _road_feature(
                    road,
                    pair_id=validation.pair_id,
                    strategy_id=strategy.strategy_id,
                    layer_role="working_graph",
                    extra_props={"debug_stage": "branch_cut", **branch_cut_props},
                )
            )

        for road_id in validation.trunk_road_ids:
            road = context.roads[road_id]
            if validation.validated_status == "validated":
                trunk_member_features.append(
                    _road_feature(
                        road,
                        pair_id=validation.pair_id,
                        strategy_id=strategy.strategy_id,
                        layer_role="trunk_member",
                    )
                )
            working_graph_debug_features.append(
                _road_feature(
                    road,
                    pair_id=validation.pair_id,
                    strategy_id=strategy.strategy_id,
                    layer_role="working_graph",
                    extra_props={"debug_stage": "trunk"},
                )
            )

        for road_id in validation.segment_road_ids:
            road = context.roads[road_id]
            if validation.validated_status == "validated":
                segment_body_member_features.append(
                    _road_feature(
                        road,
                        pair_id=validation.pair_id,
                        strategy_id=strategy.strategy_id,
                        layer_role="segment_body_member",
                    )
                )
            working_graph_debug_features.append(
                _road_feature(
                    road,
                    pair_id=validation.pair_id,
                    strategy_id=strategy.strategy_id,
                    layer_role="working_graph",
                    extra_props={"debug_stage": "segment_body"},
                )
            )

        for residual_info in residual_infos:
            road = context.roads[residual_info["road_id"]]
            residual_props = {key: value for key, value in residual_info.items() if key != "road_id"}
            if validation.validated_status == "validated":
                step3_residual_member_features.append(
                    _road_feature(
                        road,
                        pair_id=validation.pair_id,
                        strategy_id=strategy.strategy_id,
                        layer_role="step3_residual_member",
                        extra_props=residual_props,
                    )
                )
            working_graph_debug_features.append(
                _road_feature(
                    road,
                    pair_id=validation.pair_id,
                    strategy_id=strategy.strategy_id,
                    layer_role="working_graph",
                    extra_props={"debug_stage": "step3_residual", **residual_props},
                )
            )

    validated_pairs_path = out_dir / "validated_pairs.csv"
    rejected_pairs_path = out_dir / "rejected_pair_candidates.csv"
    pair_links_validated_path = out_dir / "pair_links_validated.geojson"
    trunk_roads_path = out_dir / "trunk_roads.geojson"
    segment_body_roads_path = out_dir / "segment_body_roads.geojson"
    step3_residual_roads_path = out_dir / "step3_residual_roads.geojson"
    segment_roads_path = out_dir / "segment_roads.geojson"
    trunk_road_members_path = out_dir / "trunk_road_members.geojson"
    segment_body_road_members_path = out_dir / "segment_body_road_members.geojson"
    step3_residual_road_members_path = out_dir / "step3_residual_road_members.geojson"
    segment_road_members_path = out_dir / "segment_road_members.geojson"
    branch_cut_roads_path = out_dir / "branch_cut_roads.geojson"
    candidate_channel_path = out_dir / "pair_candidate_channel.geojson"
    validation_table_path = out_dir / "pair_validation_table.csv"
    working_graph_debug_path = out_dir / "working_graph_debug.geojson"
    segment_summary_path = out_dir / "segment_summary.json"

    write_csv(
        validated_pairs_path,
        validated_rows,
        [
            "pair_id",
            "a_node_id",
            "b_node_id",
            "trunk_mode",
            "left_turn_excluded_mode",
            "warning_codes",
            "segment_body_road_count",
            "residual_road_count",
        ],
    )
    write_csv(
        rejected_pairs_path,
        rejected_rows,
        ["pair_id", "a_node_id", "b_node_id", "reject_reason", "warning_codes", "conflict_pair_id"],
    )
    write_geojson(trunk_roads_path, trunk_features)
    write_geojson(segment_body_roads_path, segment_body_features)
    write_geojson(step3_residual_roads_path, step3_residual_features)
    write_csv(
        validation_table_path,
        validation_rows,
        [
            "pair_id",
            "a_node_id",
            "b_node_id",
            "candidate_status",
            "validated_status",
            "reject_reason",
            "trunk_mode",
            "trunk_found",
            "counterclockwise_ok",
            "segment_body_road_count",
            "residual_road_count",
            "transition_same_dir_blocked",
            "left_turn_excluded_mode",
            "support_info",
        ],
    )

    segment_summary = {
        "strategy_id": strategy.strategy_id,
        "run_id": run_id,
        "strategy_out_dir": str(out_dir.resolve()),
        "formway_mode": formway_mode,
        "candidate_pair_count": len(validations),
        "validated_pair_count": len(validated_rows),
        "rejected_pair_count": len(rejected_rows),
        "branch_cut_component_count": len(branch_cut_component_keys),
        "other_terminate_cut_count": len(other_terminate_cut_keys),
        "other_trunk_conflict_count": len(other_trunk_conflict_keys),
        "transition_same_dir_block_count": len(transition_same_dir_block_keys),
        "residual_component_count": len(residual_component_keys),
        "clockwise_reject_count": clockwise_reject_count,
        "left_turn_trunk_reject_count": left_turn_trunk_reject_count,
        "prune_branch_count": total_branch_cut_count,
        "disconnected_after_prune_count": disconnected_after_prune_count,
        "shared_trunk_conflict_count": shared_trunk_conflict_count,
        "formway_warning_count": formway_warning_count,
        "debug": debug,
        "output_files": [
            validated_pairs_path.name,
            rejected_pairs_path.name,
            trunk_roads_path.name,
            segment_body_roads_path.name,
            step3_residual_roads_path.name,
            validation_table_path.name,
            segment_summary_path.name,
        ],
    }
    if debug:
        write_geojson(pair_links_validated_path, validated_link_features)
        write_geojson(segment_roads_path, segment_body_features)
        write_geojson(trunk_road_members_path, trunk_member_features)
        write_geojson(segment_body_road_members_path, segment_body_member_features)
        write_geojson(step3_residual_road_members_path, step3_residual_member_features)
        write_geojson(segment_road_members_path, segment_body_member_features)
        write_geojson(branch_cut_roads_path, branch_cut_features)
        write_geojson(candidate_channel_path, candidate_channel_features)
        write_geojson(working_graph_debug_path, working_graph_debug_features)
        segment_summary["output_files"].extend(
            [
                pair_links_validated_path.name,
                segment_roads_path.name,
                trunk_road_members_path.name,
                segment_body_road_members_path.name,
                step3_residual_road_members_path.name,
                segment_road_members_path.name,
                branch_cut_roads_path.name,
                candidate_channel_path.name,
                working_graph_debug_path.name,
            ]
        )
    write_json(segment_summary_path, segment_summary)

    return Step2StrategyResult(
        strategy=strategy,
        segment_summary=segment_summary,
        output_files=[str(path) for path in sorted(out_dir.iterdir()) if path.is_file()],
        validations=validations,
    )


def _validate_pair_candidates(
    execution: Step1StrategyExecution,
    *,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    undirected_adjacency: dict[str, tuple[TraversalEdge, ...]],
    formway_mode: str,
    left_turn_formway_bit: int,
) -> list[PairValidationResult]:
    terminate_ids = set(execution.terminate_ids)
    hard_stop_node_ids = set(execution.strategy.hard_stop_node_ids)
    boundary_node_ids = terminate_ids | hard_stop_node_ids
    used_trunk_road_ids: dict[str, str] = {}
    provisional_results: list[PairValidationResult] = []

    for pair in execution.pair_candidates:
        candidate_road_ids, boundary_terminate_ids = _build_candidate_channel(
            pair,
            undirected_adjacency=undirected_adjacency,
            boundary_node_ids=boundary_node_ids,
        )

        if not candidate_road_ids:
            provisional_results.append(
                PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason="invalid_candidate_boundary",
                    trunk_mode="none",
                    trunk_found=False,
                    counterclockwise_ok=False,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=(),
                    candidate_channel_road_ids=(),
                    pruned_road_ids=(),
                    trunk_road_ids=(),
                    segment_road_ids=(),
                    residual_road_ids=(),
                    branch_cut_road_ids=(),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    transition_same_dir_blocked=False,
                    support_info={"boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key)},
                )
            )
            continue

        pruned_road_ids, branch_cut_infos, disconnected_after_prune = _prune_candidate_channel(
            pair,
            candidate_road_ids=candidate_road_ids,
            road_endpoints=road_endpoints,
            terminate_ids=terminate_ids,
            hard_stop_node_ids=hard_stop_node_ids,
        )
        if disconnected_after_prune:
            provisional_results.append(
                PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason="disconnected_after_prune",
                    trunk_mode="none",
                    trunk_found=False,
                    counterclockwise_ok=False,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=(),
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=(),
                    segment_road_ids=(),
                    residual_road_ids=(),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    transition_same_dir_blocked=False,
                    support_info={
                        "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                        "branch_cut_infos": branch_cut_infos,
                        "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                        "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                    },
                )
            )
            continue

        trunk_candidate, reject_reason, warning_codes = _evaluate_trunk(
            pair,
            context=context,
            pruned_road_ids=pruned_road_ids,
            road_endpoints=road_endpoints,
            through_rule=execution.strategy.through_rule,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
        )
        if trunk_candidate is None:
            provisional_results.append(
                PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason=reject_reason,
                    trunk_mode="none",
                    trunk_found=False,
                    counterclockwise_ok=False,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=warning_codes,
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=(),
                    segment_road_ids=(),
                    residual_road_ids=(),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    transition_same_dir_blocked=False,
                    support_info={
                        "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                        "branch_cut_infos": branch_cut_infos,
                        "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                        "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                    },
                )
            )
            continue

        internal_boundary_node_ids = _collect_internal_boundary_nodes(
            pair,
            candidate=trunk_candidate,
            hard_stop_node_ids=hard_stop_node_ids,
        )
        if internal_boundary_node_ids:
            provisional_results.append(
                PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason="historical_boundary_blocked",
                    trunk_mode="none",
                    trunk_found=False,
                    counterclockwise_ok=False,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=warning_codes,
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=(),
                    segment_road_ids=(),
                    residual_road_ids=(),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    transition_same_dir_blocked=False,
                    support_info={
                        "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                        "branch_cut_infos": branch_cut_infos,
                        "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                        "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                        "historical_boundary_node_ids": list(internal_boundary_node_ids),
                    },
                )
            )
            continue

        trunk_mode = _trunk_candidate_mode(trunk_candidate)
        if trunk_mode == "through_collapsed_corridor":
            segment_road_ids = trunk_candidate.road_ids
            segment_cut_infos: list[dict[str, Any]] = []
        else:
            segment_road_ids, segment_cut_infos = _refine_segment_roads(
                pair,
                context=context,
                road_endpoints=road_endpoints,
                pruned_road_ids=pruned_road_ids,
                trunk_road_ids=trunk_candidate.road_ids,
                through_rule=execution.strategy.through_rule,
            )

        conflict_pair_id = None
        for road_id in trunk_candidate.road_ids:
            if road_id in used_trunk_road_ids:
                conflict_pair_id = used_trunk_road_ids[road_id]
                break
        if conflict_pair_id is not None:
            provisional_results.append(
                PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason="shared_trunk_conflict",
                    trunk_mode=trunk_mode,
                    trunk_found=True,
                    counterclockwise_ok=_trunk_candidate_counterclockwise_ok(trunk_candidate),
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=warning_codes,
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=trunk_candidate.road_ids,
                    segment_road_ids=segment_road_ids,
                    residual_road_ids=(),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    transition_same_dir_blocked=False,
                    support_info={
                        "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                        "branch_cut_infos": branch_cut_infos,
                        "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                        "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                        "trunk_signed_area": trunk_candidate.signed_area,
                        "trunk_mode": trunk_mode,
                        "bidirectional_minimal_loop": trunk_candidate.is_bidirectional_minimal_loop,
                        "semantic_node_group_closure": trunk_candidate.is_semantic_node_group_closure,
                        "segment_body_candidate_road_ids": list(segment_road_ids),
                        "segment_body_candidate_cut_infos": segment_cut_infos,
                    },
                    conflict_pair_id=conflict_pair_id,
                )
            )
            continue

        for road_id in trunk_candidate.road_ids:
            used_trunk_road_ids[road_id] = pair.pair_id

        provisional_results.append(
            PairValidationResult(
                pair_id=pair.pair_id,
                a_node_id=pair.a_node_id,
                b_node_id=pair.b_node_id,
                candidate_status="candidate",
                validated_status="validated",
                reject_reason=None,
                trunk_mode=trunk_mode,
                trunk_found=True,
                counterclockwise_ok=_trunk_candidate_counterclockwise_ok(trunk_candidate),
                left_turn_excluded_mode=formway_mode,
                warning_codes=warning_codes,
                candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                trunk_road_ids=trunk_candidate.road_ids,
                segment_road_ids=segment_road_ids,
                residual_road_ids=(),
                branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                transition_same_dir_blocked=False,
                support_info={
                    "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                    "branch_cut_infos": branch_cut_infos,
                    "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                    "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                    "forward_path_road_ids": list(trunk_candidate.forward_path.road_ids),
                    "reverse_path_road_ids": list(trunk_candidate.reverse_path.road_ids),
                    "trunk_signed_area": trunk_candidate.signed_area,
                    "trunk_mode": trunk_mode,
                    "bidirectional_minimal_loop": trunk_candidate.is_bidirectional_minimal_loop,
                    "semantic_node_group_closure": trunk_candidate.is_semantic_node_group_closure,
                    "segment_body_candidate_road_ids": list(segment_road_ids),
                    "segment_body_candidate_cut_infos": segment_cut_infos,
                    "left_turn_road_ids": list(trunk_candidate.left_turn_road_ids),
                },
            )
        )

    return _tighten_validated_segment_components(
        provisional_results,
        execution=execution,
        context=context,
        road_endpoints=road_endpoints,
    )


def run_step2_segment_poc(
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
    formway_mode: str = "strict",
    left_turn_formway_bit: int = LEFT_TURN_FORMWAY_BIT,
    debug: bool = True,
) -> list[Step2StrategyResult]:
    if formway_mode not in {"strict", "audit_only", "off"}:
        raise ValueError("formway_mode must be one of: strict, audit_only, off.")

    context = build_step1_graph_context(
        road_path=road_path,
        node_path=node_path,
        road_layer=road_layer,
        road_crs=road_crs,
        node_layer=node_layer,
        node_crs=node_crs,
    )
    road_endpoints, undirected_adjacency = _build_semantic_endpoints(context)

    results: list[Step2StrategyResult] = []
    comparison_summary: list[dict[str, Any]] = []
    resolved_run_id = Path(out_root).name if run_id is None else run_id

    for strategy_path in strategy_config_paths:
        strategy = _load_strategy(strategy_path)
        execution = run_step1_strategy(context, strategy)
        strategy_out_dir = Path(out_root) / strategy.strategy_id

        write_step1_candidate_outputs(
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
            debug=debug,
        )

        validations = _validate_pair_candidates(
            execution,
            context=context,
            road_endpoints=road_endpoints,
            undirected_adjacency=undirected_adjacency,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
        )
        step2_result = _write_step2_outputs(
            strategy_out_dir,
            strategy=strategy,
            run_id=resolved_run_id,
            context=context,
            validations=validations,
            formway_mode=formway_mode,
            debug=debug,
        )
        results.append(step2_result)
        comparison_summary.append(step2_result.segment_summary)

    write_json(Path(out_root) / "strategy_comparison.json", comparison_summary)
    return results


def run_step2_segment_poc_cli(args: argparse.Namespace) -> int:
    resolved_out_root, resolved_run_id = _resolve_out_root(out_root=args.out_root, run_id=args.run_id)
    results = run_step2_segment_poc(
        road_path=args.road_path,
        road_layer=args.road_layer,
        road_crs=args.road_crs,
        node_path=args.node_path,
        node_layer=args.node_layer,
        node_crs=args.node_crs,
        strategy_config_paths=list(args.strategy_config),
        out_root=resolved_out_root,
        run_id=resolved_run_id,
        formway_mode=args.formway_mode,
        left_turn_formway_bit=args.left_turn_formway_bit,
    )

    payload = {
        "run_id": resolved_run_id,
        "out_root": str(resolved_out_root.resolve()),
        "strategies": [
            {
                "strategy_id": result.strategy.strategy_id,
                "candidate_pair_count": result.segment_summary["candidate_pair_count"],
                "validated_pair_count": result.segment_summary["validated_pair_count"],
                "rejected_pair_count": result.segment_summary["rejected_pair_count"],
                "output_dir": str((resolved_out_root / result.strategy.strategy_id).resolve()),
            }
            for result in results
        ],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0
