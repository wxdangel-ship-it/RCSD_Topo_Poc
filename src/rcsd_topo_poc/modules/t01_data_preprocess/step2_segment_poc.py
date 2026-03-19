from __future__ import annotations

import argparse
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime
from heapq import heappop, heappush
from itertools import count
from pathlib import Path
from typing import Any, Optional, Union

from shapely.geometry import LineString
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


@dataclass(frozen=True)
class PairValidationResult:
    pair_id: str
    a_node_id: str
    b_node_id: str
    candidate_status: str
    validated_status: str
    reject_reason: Optional[str]
    trunk_found: bool
    counterclockwise_ok: bool
    left_turn_excluded_mode: str
    warning_codes: tuple[str, ...]
    candidate_channel_road_ids: tuple[str, ...]
    pruned_road_ids: tuple[str, ...]
    trunk_road_ids: tuple[str, ...]
    segment_road_ids: tuple[str, ...]
    branch_cut_road_ids: tuple[str, ...]
    boundary_terminate_node_ids: tuple[str, ...]
    support_info: dict[str, Any]
    conflict_pair_id: Optional[str] = None


@dataclass(frozen=True)
class Step2StrategyResult:
    strategy: StrategySpec
    segment_summary: dict[str, Any]
    output_files: list[str]
    validations: list[PairValidationResult]


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


def _build_candidate_channel(
    pair: PairRecord,
    *,
    undirected_adjacency: dict[str, tuple[TraversalEdge, ...]],
    terminate_ids: set[str],
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
                if current_node_id in terminate_ids and current_node_id not in protected:
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


def _prune_candidate_channel(
    pair: PairRecord,
    *,
    candidate_road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
    terminate_ids: set[str],
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
        cut_reason = (
            "branch_leads_to_other_terminate"
            if node_id in terminate_ids and node_id not in protected
            else "branch_backtrack_prune"
        )
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


def _collect_trunk_candidates(
    *,
    forward_paths: list[DirectedPath],
    reverse_paths: list[DirectedPath],
    roads: dict[str, RoadRecord],
    road_endpoints: dict[str, tuple[str, str]],
    left_turn_formway_bit: int,
) -> tuple[list[TrunkCandidate], bool]:
    counterclockwise_candidates: list[TrunkCandidate] = []
    clockwise_only_found = False

    for forward_path in forward_paths:
        for reverse_path in reverse_paths:
            combined_road_ids = tuple(
                sorted(set(forward_path.road_ids + reverse_path.road_ids), key=_sort_key)
            )
            if len(combined_road_ids) != len(forward_path.road_ids) + len(reverse_path.road_ids):
                continue

            ring_coords = _path_coords(forward_path, roads=roads, road_endpoints=road_endpoints)
            reverse_coords = _path_coords(reverse_path, roads=roads, road_endpoints=road_endpoints)
            if not ring_coords or not reverse_coords:
                continue
            ring_coords.extend(reverse_coords[1:])

            signed_area = _signed_ring_area(ring_coords)
            if abs(signed_area) <= 1e-6:
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
            )
            if signed_area > 0:
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
    formway_mode: str,
    left_turn_formway_bit: int,
) -> tuple[Optional[TrunkCandidate], Optional[str], tuple[str, ...]]:
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
        )
        if strict_candidates:
            return strict_candidates[0], None, ()
        if base_candidates:
            return None, "left_turn_only_polluted_trunk", ()
        if strict_clockwise_only or base_clockwise_only:
            return None, "only_clockwise_loop", ()
        return None, "no_valid_trunk", ()

    if not base_candidates:
        if base_clockwise_only:
            return None, "only_clockwise_loop", ()
        return None, "no_valid_trunk", ()

    warnings: tuple[str, ...] = ()
    chosen = base_candidates[0]
    if formway_mode == "audit_only" and chosen.left_turn_road_ids:
        warnings = ("formway_unreliable_warning",)
    return chosen, None, warnings


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


def _write_step2_outputs(
    out_dir: Path,
    *,
    strategy: StrategySpec,
    run_id: str,
    context: Step1GraphContext,
    validations: list[PairValidationResult],
    formway_mode: str,
) -> Step2StrategyResult:
    validated_rows: list[dict[str, Any]] = []
    rejected_rows: list[dict[str, Any]] = []
    validation_rows: list[dict[str, Any]] = []
    validated_link_features: list[dict[str, Any]] = []
    candidate_channel_features: list[dict[str, Any]] = []
    trunk_features: list[dict[str, Any]] = []
    segment_features: list[dict[str, Any]] = []
    branch_cut_features: list[dict[str, Any]] = []
    working_graph_debug_features: list[dict[str, Any]] = []

    total_branch_cut_count = 0
    clockwise_reject_count = 0
    left_turn_trunk_reject_count = 0
    disconnected_after_prune_count = 0
    shared_trunk_conflict_count = 0
    formway_warning_count = 0

    for validation in validations:
        support_info = dict(validation.support_info)
        validation_rows.append(
            {
                "pair_id": validation.pair_id,
                "a_node_id": validation.a_node_id,
                "b_node_id": validation.b_node_id,
                "candidate_status": validation.candidate_status,
                "validated_status": validation.validated_status,
                "reject_reason": validation.reject_reason or "",
                "trunk_found": validation.trunk_found,
                "counterclockwise_ok": validation.counterclockwise_ok,
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
                    "left_turn_excluded_mode": validation.left_turn_excluded_mode,
                    "warning_codes": ";".join(validation.warning_codes),
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

        branch_cut_infos = support_info.get("branch_cut_infos", [])
        total_branch_cut_count += len(branch_cut_infos)

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
            branch_cut_features.append(
                _road_feature(
                    road,
                    pair_id=validation.pair_id,
                    strategy_id=strategy.strategy_id,
                    layer_role="branch_cut",
                    extra_props={"cut_reason": branch_cut_info["cut_reason"]},
                )
            )
            working_graph_debug_features.append(
                _road_feature(
                    road,
                    pair_id=validation.pair_id,
                    strategy_id=strategy.strategy_id,
                    layer_role="working_graph",
                    extra_props={"debug_stage": "branch_cut", "cut_reason": branch_cut_info["cut_reason"]},
                )
            )

        for road_id in validation.trunk_road_ids:
            road = context.roads[road_id]
            trunk_features.append(
                _road_feature(
                    road,
                    pair_id=validation.pair_id,
                    strategy_id=strategy.strategy_id,
                    layer_role="trunk",
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
            segment_features.append(
                _road_feature(
                    road,
                    pair_id=validation.pair_id,
                    strategy_id=strategy.strategy_id,
                    layer_role="segment",
                )
            )
            working_graph_debug_features.append(
                _road_feature(
                    road,
                    pair_id=validation.pair_id,
                    strategy_id=strategy.strategy_id,
                    layer_role="working_graph",
                    extra_props={"debug_stage": "segment"},
                )
            )

    validated_pairs_path = out_dir / "validated_pairs.csv"
    rejected_pairs_path = out_dir / "rejected_pair_candidates.csv"
    pair_links_validated_path = out_dir / "pair_links_validated.geojson"
    trunk_roads_path = out_dir / "trunk_roads.geojson"
    segment_roads_path = out_dir / "segment_roads.geojson"
    branch_cut_roads_path = out_dir / "branch_cut_roads.geojson"
    candidate_channel_path = out_dir / "pair_candidate_channel.geojson"
    validation_table_path = out_dir / "pair_validation_table.csv"
    working_graph_debug_path = out_dir / "working_graph_debug.geojson"
    segment_summary_path = out_dir / "segment_summary.json"

    write_csv(
        validated_pairs_path,
        validated_rows,
        ["pair_id", "a_node_id", "b_node_id", "left_turn_excluded_mode", "warning_codes"],
    )
    write_csv(
        rejected_pairs_path,
        rejected_rows,
        ["pair_id", "a_node_id", "b_node_id", "reject_reason", "warning_codes", "conflict_pair_id"],
    )
    write_geojson(pair_links_validated_path, validated_link_features)
    write_geojson(trunk_roads_path, trunk_features)
    write_geojson(segment_roads_path, segment_features)
    write_geojson(branch_cut_roads_path, branch_cut_features)
    write_geojson(candidate_channel_path, candidate_channel_features)
    write_geojson(working_graph_debug_path, working_graph_debug_features)
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
            "trunk_found",
            "counterclockwise_ok",
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
        "clockwise_reject_count": clockwise_reject_count,
        "left_turn_trunk_reject_count": left_turn_trunk_reject_count,
        "prune_branch_count": total_branch_cut_count,
        "disconnected_after_prune_count": disconnected_after_prune_count,
        "shared_trunk_conflict_count": shared_trunk_conflict_count,
        "formway_warning_count": formway_warning_count,
        "output_files": [
            validated_pairs_path.name,
            rejected_pairs_path.name,
            pair_links_validated_path.name,
            trunk_roads_path.name,
            segment_roads_path.name,
            branch_cut_roads_path.name,
            candidate_channel_path.name,
            validation_table_path.name,
            working_graph_debug_path.name,
            segment_summary_path.name,
        ],
    }
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
    used_trunk_road_ids: dict[str, str] = {}
    results: list[PairValidationResult] = []

    for pair in execution.pair_candidates:
        candidate_road_ids, boundary_terminate_ids = _build_candidate_channel(
            pair,
            undirected_adjacency=undirected_adjacency,
            terminate_ids=terminate_ids,
        )

        if not candidate_road_ids:
            results.append(
                PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason="invalid_candidate_boundary",
                    trunk_found=False,
                    counterclockwise_ok=False,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=(),
                    candidate_channel_road_ids=(),
                    pruned_road_ids=(),
                    trunk_road_ids=(),
                    segment_road_ids=(),
                    branch_cut_road_ids=(),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    support_info={"boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key)},
                )
            )
            continue

        pruned_road_ids, branch_cut_infos, disconnected_after_prune = _prune_candidate_channel(
            pair,
            candidate_road_ids=candidate_road_ids,
            road_endpoints=road_endpoints,
            terminate_ids=terminate_ids,
        )
        if disconnected_after_prune:
            results.append(
                PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason="disconnected_after_prune",
                    trunk_found=False,
                    counterclockwise_ok=False,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=(),
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=(),
                    segment_road_ids=(),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
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
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
        )
        if trunk_candidate is None:
            results.append(
                PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason=reject_reason,
                    trunk_found=False,
                    counterclockwise_ok=False,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=warning_codes,
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=(),
                    segment_road_ids=(),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    support_info={
                        "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                        "branch_cut_infos": branch_cut_infos,
                        "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                        "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                    },
                )
            )
            continue

        conflict_pair_id = None
        for road_id in trunk_candidate.road_ids:
            if road_id in used_trunk_road_ids:
                conflict_pair_id = used_trunk_road_ids[road_id]
                break
        if conflict_pair_id is not None:
            results.append(
                PairValidationResult(
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    candidate_status="candidate",
                    validated_status="rejected",
                    reject_reason="shared_trunk_conflict",
                    trunk_found=True,
                    counterclockwise_ok=True,
                    left_turn_excluded_mode=formway_mode,
                    warning_codes=warning_codes,
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=trunk_candidate.road_ids,
                    segment_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    support_info={
                        "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                        "branch_cut_infos": branch_cut_infos,
                        "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                        "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                        "trunk_signed_area": trunk_candidate.signed_area,
                    },
                    conflict_pair_id=conflict_pair_id,
                )
            )
            continue

        for road_id in trunk_candidate.road_ids:
            used_trunk_road_ids[road_id] = pair.pair_id

        results.append(
            PairValidationResult(
                pair_id=pair.pair_id,
                a_node_id=pair.a_node_id,
                b_node_id=pair.b_node_id,
                candidate_status="candidate",
                validated_status="validated",
                reject_reason=None,
                trunk_found=True,
                counterclockwise_ok=True,
                left_turn_excluded_mode=formway_mode,
                warning_codes=warning_codes,
                candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                trunk_road_ids=trunk_candidate.road_ids,
                segment_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                support_info={
                    "boundary_terminate_node_ids": sorted(boundary_terminate_ids, key=_sort_key),
                    "branch_cut_infos": branch_cut_infos,
                    "candidate_channel_road_ids": sorted(candidate_road_ids, key=_sort_key),
                    "pruned_road_ids": sorted(pruned_road_ids, key=_sort_key),
                    "forward_path_road_ids": list(trunk_candidate.forward_path.road_ids),
                    "reverse_path_road_ids": list(trunk_candidate.reverse_path.road_ids),
                    "trunk_signed_area": trunk_candidate.signed_area,
                    "left_turn_road_ids": list(trunk_candidate.left_turn_road_ids),
                },
            )
        )

    return results


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
