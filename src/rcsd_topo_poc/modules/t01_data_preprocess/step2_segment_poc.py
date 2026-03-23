from __future__ import annotations

import argparse
import gc
import inspect
import json
from collections import defaultdict, deque
from dataclasses import dataclass, replace
from datetime import datetime
from heapq import heappop, heappush
from itertools import count
from math import ceil, hypot
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Union

from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge

from rcsd_topo_poc.modules.t01_data_preprocess.endpoint_pool import (
    build_endpoint_pool_source_map,
    write_endpoint_pool_outputs,
)
from rcsd_topo_poc.modules.t01_data_preprocess.io_utils import write_csv, write_geojson, write_json
from rcsd_topo_poc.modules.t01_data_preprocess.step2_arbitration import (
    PairArbitrationDecision,
    PairArbitrationOption,
    PairArbitrationOutcome,
    arbitrate_pair_options,
)
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
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
    MAX_SIDE_ACCESS_DISTANCE_M,
    initialize_working_layers,
    is_allowed_road_kind,
)


DEFAULT_RUN_ID_PREFIX = "t01_step2_segment_poc_"
LEFT_TURN_FORMWAY_BIT = 8
MAX_PATHS_PER_DIRECTION = 12
MAX_PATH_DEPTH = 64
SIDE_ACCESS_SAMPLE_STEP_M = MAX_SIDE_ACCESS_DISTANCE_M / 2.0
VALIDATION_PROGRESS_CHECKPOINT_INTERVAL = 100
VALIDATION_PHASE_TRACE_PAIR_LIMIT = 50


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
    max_dual_carriageway_separation_m: float
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
    single_pair_legal: bool = False
    arbitration_status: str = "unresolved"
    arbitration_component_id: str = ""
    arbitration_option_id: Optional[str] = None
    lose_reason: str = ""


@dataclass(frozen=True)
class Step2StrategyResult:
    strategy: StrategySpec
    segment_summary: dict[str, Any]
    output_files: list[str]
    validations: list[PairValidationResult]


@dataclass(frozen=True)
class _TrunkEvaluationChoice:
    candidate: TrunkCandidate
    warning_codes: tuple[str, ...]
    support_info: dict[str, Any]


@dataclass(frozen=True)
class NonTrunkComponent:
    component_id: str
    road_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    attachment_node_ids: tuple[str, ...]
    internal_support_attachment_node_ids: tuple[str, ...]
    internal_t_support_attachment_node_ids: tuple[str, ...]
    component_directionality: str
    bidirectional_road_ids: tuple[str, ...]
    attachment_flow_status: str
    attachment_direction_labels: tuple[str, ...]
    parallel_corridor_directionality: str
    parallel_corridor_directions: tuple[str, ...]
    hits_other_terminate: bool
    terminate_node_ids: tuple[str, ...]
    contains_other_validated_trunk: bool
    conflicting_pair_ids: tuple[str, ...]
    blocked_by_transition_same_dir: bool
    transition_block_infos: tuple[dict[str, Any], ...]
    side_access_metric: str
    side_access_distance_m: Optional[float]
    side_access_gate_passed: bool
    kept_as_segment_body: bool
    moved_to_step3_residual: bool
    moved_to_branch_cut: bool
    decision_reason: str


Step2ProgressCallback = Callable[[str, dict[str, Any]], None]


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


def _emit_progress(
    progress_callback: Optional[Step2ProgressCallback],
    event: str,
    **payload: Any,
) -> None:
    if progress_callback is None:
        return
    progress_callback(event, payload)


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


def _line_geometry_from_coords(coords: list[tuple[float, float]]) -> Optional[BaseGeometry]:
    if len(coords) < 2:
        return None
    return LineString(coords)


def _line_geometry_from_road_ids(
    road_ids: tuple[str, ...],
    *,
    roads: dict[str, RoadRecord],
) -> Optional[BaseGeometry]:
    parts: list[LineString] = []
    for road_id in road_ids:
        coords = _geometry_coords(roads[road_id].geometry)
        if len(coords) < 2:
            continue
        parts.append(LineString(coords))
    if not parts:
        return None
    if len(parts) == 1:
        return parts[0]
    return MultiLineString(parts)


def _max_nearest_distance_m(
    source_geometry: Optional[BaseGeometry],
    target_geometry: Optional[BaseGeometry],
) -> Optional[float]:
    if source_geometry is None or target_geometry is None:
        return None
    if source_geometry.is_empty or target_geometry.is_empty:
        return None
    return float(source_geometry.hausdorff_distance(target_geometry))


def _iter_sample_points(geometry: Optional[BaseGeometry]) -> Iterable[Point]:
    if geometry is None or geometry.is_empty:
        return

    if isinstance(geometry, LineString):
        parts = (geometry,)
    elif isinstance(geometry, MultiLineString):
        parts = tuple(part for part in geometry.geoms if not part.is_empty)
    else:
        return

    for part in parts:
        coords = _geometry_coords(part)
        if len(coords) < 2:
            continue
        for start, end in zip(coords, coords[1:]):
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            segment_length = hypot(dx, dy)
            if segment_length <= 0.0:
                continue
            sample_count = max(3, ceil(segment_length / SIDE_ACCESS_SAMPLE_STEP_M) + 1)
            for sample_index in range(sample_count):
                fraction = sample_index / (sample_count - 1)
                yield Point(start[0] + dx * fraction, start[1] + dy * fraction)


def _max_sampled_distance_m(
    source_geometry: Optional[BaseGeometry],
    target_geometry: Optional[BaseGeometry],
) -> Optional[float]:
    if source_geometry is None or target_geometry is None:
        return None
    if source_geometry.is_empty or target_geometry.is_empty:
        return None

    max_distance_m: Optional[float] = None
    for sample_point in _iter_sample_points(source_geometry):
        distance_m = float(sample_point.distance(target_geometry))
        if max_distance_m is None or distance_m > max_distance_m:
            max_distance_m = distance_m
    return max_distance_m


def _collect_road_node_ids(
    road_ids: Iterable[str],
    *,
    road_endpoints: dict[str, tuple[str, str]],
) -> set[str]:
    node_ids: set[str] = set()
    for road_id in road_ids:
        node_ids.update(road_endpoints.get(road_id, ()))
    return node_ids


def _build_semantic_endpoints(
    context: Step1GraphContext,
) -> tuple[dict[str, tuple[str, str]], dict[str, tuple[TraversalEdge, ...]]]:
    road_endpoints: dict[str, tuple[str, str]] = {}
    undirected_lists: dict[str, list[TraversalEdge]] = defaultdict(list)

    for road in context.roads.values():
        if not is_allowed_road_kind(road.road_kind):
            continue
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


def _build_segment_body_candidate_channel(
    pair: PairRecord,
    *,
    trunk_road_ids: tuple[str, ...],
    undirected_adjacency: dict[str, tuple[TraversalEdge, ...]],
    boundary_node_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
    allowed_road_ids: Optional[set[str]] = None,
) -> set[str]:
    protected = {pair.a_node_id, pair.b_node_id}
    start_node_ids = _collect_road_node_ids(trunk_road_ids, road_endpoints=road_endpoints)
    candidate_road_ids: set[str] = set(trunk_road_ids)
    allowed_road_id_set = set(allowed_road_ids) if allowed_road_ids is not None else None

    for start_node_id in sorted(start_node_ids, key=_sort_key):
        for edge in undirected_adjacency.get(start_node_id, ()):
            if allowed_road_id_set is not None and edge.road_id not in allowed_road_id_set:
                continue
            if edge.road_id in candidate_road_ids:
                continue

            queue: deque[TraversalEdge] = deque([edge])
            while queue:
                current_edge = queue.popleft()
                if allowed_road_id_set is not None and current_edge.road_id not in allowed_road_id_set:
                    continue
                if current_edge.road_id in candidate_road_ids:
                    continue

                candidate_road_ids.add(current_edge.road_id)
                current_node_id = current_edge.to_node
                if current_node_id in boundary_node_ids and current_node_id not in protected:
                    continue

                for next_edge in undirected_adjacency.get(current_node_id, ()):
                    if allowed_road_id_set is not None and next_edge.road_id not in allowed_road_id_set:
                        continue
                    if next_edge.road_id in candidate_road_ids:
                        continue
                    queue.append(next_edge)

    non_trunk_candidate_road_ids = candidate_road_ids - set(trunk_road_ids)
    retained_non_trunk_road_ids: set[str] = set()
    for component_road_ids, component_node_ids in _collect_components(
        non_trunk_candidate_road_ids,
        road_endpoints=road_endpoints,
    ):
        attachment_node_ids = set(component_node_ids) & start_node_ids
        if len(attachment_node_ids) >= 2:
            retained_non_trunk_road_ids.update(component_road_ids)

    return set(trunk_road_ids) | retained_non_trunk_road_ids


def _expand_segment_body_allowed_road_ids(
    *,
    pruned_road_ids: set[str],
    branch_cut_infos: list[dict[str, Any]],
    undirected_adjacency: dict[str, tuple[TraversalEdge, ...]],
    boundary_node_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
) -> set[str]:
    """Recover local bridge roads between branch-backtrack-pruned fragments.

    Trunk search intentionally keeps a narrow candidate channel, and prune may
    cut side-corridor attachments as backtracking leaves. For segment_body
    recovery we only stitch short local bridge components between those pruned
    branch anchors, while avoiding an unrestricted walk over the whole graph.
    """

    allowed_road_ids = set(pruned_road_ids)
    backtrack_infos = [
        info
        for info in branch_cut_infos
        if str(info.get("cut_reason", "")) == "branch_backtrack_prune" and info.get("road_id") in road_endpoints
    ]
    if not backtrack_infos:
        return allowed_road_ids

    normalized_backtrack_infos = [
        (
            str(info["road_id"]),
            str(info["from_node_id"]),
            str(info["to_node_id"]),
        )
        for info in backtrack_infos
        if info.get("from_node_id") and info.get("to_node_id")
    ]
    if len(normalized_backtrack_infos) < 2:
        return allowed_road_ids

    max_bridge_depth = 6
    outer_anchor_node_ids = {anchor_node_id for _, anchor_node_id, _ in normalized_backtrack_infos}
    branch_anchor_road_ids = {road_id for road_id, _, _ in normalized_backtrack_infos}

    for index, (start_anchor_road_id, start_node_id, start_attach_node_id) in enumerate(normalized_backtrack_infos):
        for end_anchor_road_id, end_node_id, end_attach_node_id in normalized_backtrack_infos[index + 1 :]:
            if start_attach_node_id == end_attach_node_id:
                continue
            queue: deque[tuple[str, tuple[str, ...], tuple[str, ...]]] = deque(
                [(start_node_id, (), (start_node_id,))]
            )
            visited_states: set[tuple[str, int]] = {(start_node_id, 0)}
            bridge_path_road_ids: Optional[tuple[str, ...]] = None

            while queue:
                current_node_id, road_path, node_path = queue.popleft()
                if len(road_path) >= max_bridge_depth:
                    continue

                for edge in undirected_adjacency.get(current_node_id, ()):
                    road_id = edge.road_id
                    if road_id in allowed_road_ids:
                        continue
                    if road_id in branch_anchor_road_ids:
                        continue
                    next_node_id = edge.to_node
                    if next_node_id in node_path:
                        continue
                    if next_node_id in boundary_node_ids and next_node_id not in {start_node_id, end_node_id}:
                        continue
                    if next_node_id in outer_anchor_node_ids and next_node_id not in {start_node_id, end_node_id}:
                        continue

                    next_road_path = (*road_path, road_id)
                    if next_node_id == end_node_id:
                        bridge_path_road_ids = next_road_path
                        break

                    state = (next_node_id, len(next_road_path))
                    if state in visited_states:
                        continue
                    visited_states.add(state)
                    queue.append((next_node_id, next_road_path, (*node_path, next_node_id)))

                if bridge_path_road_ids is not None:
                    break

            if bridge_path_road_ids:
                allowed_road_ids.update((start_anchor_road_id, end_anchor_road_id))
                allowed_road_ids.update(bridge_path_road_ids)

    return allowed_road_ids


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


def _path_exists_directed(
    start_node_id: str,
    end_node_id: str,
    *,
    adjacency: dict[str, tuple[TraversalEdge, ...]],
) -> bool:
    if start_node_id == end_node_id:
        return True

    queue: deque[str] = deque([start_node_id])
    visited = {start_node_id}

    while queue:
        current_node_id = queue.popleft()
        for edge in adjacency.get(current_node_id, ()):
            next_node_id = edge.to_node
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
        "attachment_node_ids": list(component.attachment_node_ids),
        "internal_support_attachment_node_ids": list(component.internal_support_attachment_node_ids),
        "internal_t_support_attachment_node_ids": list(component.internal_t_support_attachment_node_ids),
        "component_directionality": component.component_directionality,
        "bidirectional_road_ids": list(component.bidirectional_road_ids),
        "attachment_flow_status": component.attachment_flow_status,
        "attachment_direction_labels": list(component.attachment_direction_labels),
        "parallel_corridor_directionality": component.parallel_corridor_directionality,
        "parallel_corridor_directions": list(component.parallel_corridor_directions),
        "hits_other_terminate": component.hits_other_terminate,
        "terminate_node_ids": list(component.terminate_node_ids),
        "contains_other_validated_trunk": component.contains_other_validated_trunk,
        "conflicting_pair_ids": list(component.conflicting_pair_ids),
        "blocked_by_transition_same_dir": component.blocked_by_transition_same_dir,
        "transition_block_infos": list(component.transition_block_infos),
        "side_access_metric": component.side_access_metric,
        "side_access_distance_m": component.side_access_distance_m,
        "side_access_gate_passed": component.side_access_gate_passed,
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
    validated_internal_support_owners_by_node: dict[str, set[str]] = defaultdict(set)
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        pair = pair_lookup.get(validation.pair_id)
        if pair is None:
            continue
        internal_support_node_ids = (
            set(pair.forward_path_node_ids[1:-1]) | set(pair.reverse_path_node_ids[1:-1])
        ) - {pair.a_node_id, pair.b_node_id}
        for node_id in internal_support_node_ids:
            validated_internal_support_owners_by_node[node_id].add(validation.pair_id)
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
        trunk_node_id_set = _collect_road_node_ids(validation.trunk_road_ids, road_endpoints=road_endpoints)
        internal_support_node_ids = tuple(
            sorted(
                (
                    (set(pair.forward_path_node_ids[1:-1]) | set(pair.reverse_path_node_ids[1:-1]))
                    - {pair.a_node_id, pair.b_node_id}
                ),
                key=_sort_key,
            )
        )
        internal_support_node_id_set = set(internal_support_node_ids)
        internal_t_support_node_ids = tuple(
            sorted(
                (
                    node_id
                    for node_id in (
                        (set(pair.forward_path_node_ids[1:-1]) | set(pair.reverse_path_node_ids[1:-1]))
                        - {pair.a_node_id, pair.b_node_id}
                    )
                    if node_id in context.semantic_nodes
                    and _bit_enabled(context.semantic_nodes[node_id].kind_2, 11)
                ),
                key=_sort_key,
            )
        )
        internal_t_support_node_id_set = set(internal_t_support_node_ids)
        pruned_road_id_set = set(validation.pruned_road_ids)
        trunk_geometry = _line_geometry_from_road_ids(validation.trunk_road_ids, roads=context.roads)

        if validation.trunk_mode == "through_collapsed_corridor":
            body_candidate_road_ids = set(validation.trunk_road_ids)
            refine_cut_infos: list[dict[str, Any]] = []
        elif "segment_body_candidate_road_ids" in support_info:
            body_candidate_road_ids = {
                str(road_id) for road_id in support_info.get("segment_body_candidate_road_ids", [])
            }
            refine_cut_infos = [dict(info) for info in support_info.get("segment_body_candidate_cut_infos", [])]
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

        pruned_non_trunk_road_ids = pruned_road_id_set - trunk_road_id_set
        refined_out_non_trunk_road_ids = pruned_non_trunk_road_ids - body_candidate_non_trunk_road_ids
        segment_body_non_trunk_road_ids: set[str] = set()
        residual_road_ids: set[str] = set()
        transition_same_dir_blocked = False

        component_queue: deque[tuple[tuple[str, ...], tuple[str, ...], bool]] = deque(
            [
                (*component, True)
                for component in _collect_components(
                    set(body_candidate_non_trunk_road_ids),
                    road_endpoints=road_endpoints,
                )
            ]
            + [
                (*component, False)
                for component in _collect_components(
                    refined_out_non_trunk_road_ids,
                    road_endpoints=road_endpoints,
                )
            ]
        )
        component_index = 0
        while component_queue:
            component_road_ids, component_node_ids, component_is_body_candidate = component_queue.popleft()
            if not component_road_ids:
                continue

            component_index += 1
            component_id = f"{validation.pair_id}:C{component_index}"
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
            conflicting_road_ids = {
                road_id
                for road_id in component_road_ids
                if road_id in validated_trunk_owner_by_road and validated_trunk_owner_by_road[road_id] != validation.pair_id
            }
            support_barrier_node_ids = tuple(
                sorted(
                    (
                        node_id
                        for node_id in set(component_node_ids)
                        if any(
                            owner_pair_id != validation.pair_id
                            for owner_pair_id in validated_internal_support_owners_by_node.get(node_id, set())
                        )
                    ),
                    key=_sort_key,
                )
            )
            support_barrier_road_ids = {
                road_id
                for road_id in component_road_ids
                if set(road_endpoints.get(road_id, ())) & set(support_barrier_node_ids)
            }
            terminate_cut_road_ids = {
                road_id
                for road_id in component_road_ids
                if set(road_endpoints.get(road_id, ())) & set(terminate_node_ids)
            }
            blocker_road_ids = terminate_cut_road_ids | conflicting_road_ids | support_barrier_road_ids
            if blocker_road_ids:
                for road_id in sorted(blocker_road_ids, key=_sort_key):
                    road_node_ids = set(road_endpoints.get(road_id, ()))
                    touched_terminate_node_ids = tuple(
                        sorted(road_node_ids & set(terminate_node_ids), key=_sort_key)
                    )
                    touched_support_barrier_node_ids = tuple(
                        sorted(road_node_ids & set(support_barrier_node_ids), key=_sort_key)
                    )
                    if touched_terminate_node_ids:
                        cut_reason = (
                            "hits_historical_boundary"
                            if set(touched_terminate_node_ids) & hard_stop_node_ids
                            else "hits_other_terminate"
                        )
                    elif touched_support_barrier_node_ids:
                        cut_reason = "hits_other_validated_support_node"
                    else:
                        cut_reason = "contains_other_validated_trunk"
                    key = (road_id, cut_reason)
                    if key in branch_cut_seen:
                        continue
                    branch_cut_infos.append(
                        {
                            "road_id": road_id,
                            "cut_reason": cut_reason,
                            "component_id": component_id,
                            "conflicting_pair_ids": list(conflicting_pair_ids),
                            "terminate_node_ids": list(terminate_node_ids),
                            "support_barrier_node_ids": list(support_barrier_node_ids),
                        }
                    )
                    branch_cut_seen.add(key)

                remaining_component_road_ids = component_road_id_set - blocker_road_ids
                if remaining_component_road_ids:
                    component_queue.extendleft(
                        [
                            (*component, component_is_body_candidate)
                            for component in reversed(
                                _collect_components(remaining_component_road_ids, road_endpoints=road_endpoints)
                            )
                        ]
                    )
                continue

            transition_block_infos = _collect_transition_same_dir_block_infos(
                component_road_ids=component_road_ids,
                component_node_ids=component_node_ids,
                trunk_road_ids=validation.trunk_road_ids,
                road_endpoints=road_endpoints,
                direction_support_index=direction_support_index,
            )
            attachment_node_ids = tuple(sorted((set(component_node_ids) & trunk_node_id_set), key=_sort_key))
            internal_support_attachment_node_ids = tuple(
                sorted((set(attachment_node_ids) & internal_support_node_id_set), key=_sort_key)
            )
            internal_t_support_attachment_node_ids = tuple(
                sorted((set(attachment_node_ids) & internal_t_support_node_id_set), key=_sort_key)
            )
            component_directed_adjacency = _build_filtered_directed_adjacency(
                context.roads,
                road_endpoints=road_endpoints,
                allowed_road_ids=component_road_id_set,
                exclude_left_turn=False,
                left_turn_formway_bit=LEFT_TURN_FORMWAY_BIT,
            )
            component_direction_support_index = _build_direction_support_index_from_adjacency(
                component_directed_adjacency
            )
            component_directionality, bidirectional_road_ids = _classify_component_directionality(
                component_road_ids,
                roads=context.roads,
            )
            attachment_flow_status, attachment_direction_labels = _classify_attachment_flow_status(
                component_road_ids=component_road_ids,
                attachment_node_ids=attachment_node_ids,
                road_endpoints=road_endpoints,
                direction_support_index=component_direction_support_index,
            )
            parallel_corridor_directionality, parallel_corridor_directions = _classify_parallel_corridor_directionality(
                attachment_node_ids=attachment_node_ids,
                directed_adjacency=component_directed_adjacency,
            )
            hits_other_terminate = bool(terminate_node_ids)
            contains_other_validated_trunk = bool(conflicting_pair_ids)
            blocked_by_transition_same_dir = bool(transition_block_infos)
            component_geometry = _line_geometry_from_road_ids(component_road_ids, roads=context.roads)
            side_access_metric = "component_to_trunk_sampled"
            side_access_distance_m = _max_sampled_distance_m(component_geometry, trunk_geometry)
            if len(attachment_node_ids) < 2:
                side_access_gate_passed = False
                side_access_failure_reason = "side_access_attachment_insufficient"
            else:
                side_access_gate_passed = (
                    side_access_distance_m is None or side_access_distance_m <= MAX_SIDE_ACCESS_DISTANCE_M
                )
                side_access_failure_reason = "side_access_distance_exceeded"

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
            elif (
                component_is_body_candidate
                and len(attachment_node_ids) >= 2
                and component_directionality != "one_way_only"
            ):
                moved_to_step3_residual = True
                decision_reason = "contains_bidirectional_side_road"
            elif component_is_body_candidate and parallel_corridor_directionality == "bidirectional_parallel":
                moved_to_step3_residual = True
                decision_reason = "bidirectional_parallel_corridor"
            elif component_is_body_candidate and attachment_flow_status != "single_departure_return":
                moved_to_step3_residual = True
                decision_reason = attachment_flow_status
            elif (
                component_is_body_candidate
                and parallel_corridor_directionality == "one_way_parallel"
                and attachment_node_ids
                and set(attachment_node_ids).issubset(internal_support_node_id_set)
            ):
                moved_to_step3_residual = True
                decision_reason = "internal_support_one_way_parallel"
            elif blocked_by_transition_same_dir:
                moved_to_step3_residual = True
                transition_same_dir_blocked = True
                decision_reason = "transition_same_dir_block"
            elif component_is_body_candidate and not side_access_gate_passed:
                moved_to_step3_residual = True
                decision_reason = side_access_failure_reason
            elif component_is_body_candidate:
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
                component_id=component_id,
                road_ids=component_road_ids,
                node_ids=component_node_ids,
                attachment_node_ids=attachment_node_ids,
                internal_support_attachment_node_ids=internal_support_attachment_node_ids,
                internal_t_support_attachment_node_ids=internal_t_support_attachment_node_ids,
                component_directionality=component_directionality,
                bidirectional_road_ids=bidirectional_road_ids,
                attachment_flow_status=attachment_flow_status,
                attachment_direction_labels=attachment_direction_labels,
                parallel_corridor_directionality=parallel_corridor_directionality,
                parallel_corridor_directions=parallel_corridor_directions,
                hits_other_terminate=hits_other_terminate,
                terminate_node_ids=terminate_node_ids,
                contains_other_validated_trunk=contains_other_validated_trunk,
                conflicting_pair_ids=conflicting_pair_ids,
                blocked_by_transition_same_dir=blocked_by_transition_same_dir,
                transition_block_infos=transition_block_infos,
                side_access_metric=side_access_metric,
                side_access_distance_m=side_access_distance_m,
                side_access_gate_passed=side_access_gate_passed,
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
                            "side_access_distance_m": side_access_distance_m,
                            "side_access_gate_passed": side_access_gate_passed,
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
    roads: dict[str, RoadRecord],
    *,
    road_endpoints: dict[str, tuple[str, str]],
    allowed_road_ids: set[str],
    exclude_left_turn: bool,
    left_turn_formway_bit: int,
    exclude_formway_bits_any: tuple[int, ...] = (),
) -> dict[str, tuple[TraversalEdge, ...]]:
    filtered_lists: dict[str, list[TraversalEdge]] = defaultdict(list)
    for road_id in sorted(allowed_road_ids, key=_sort_key):
        endpoints = road_endpoints.get(road_id)
        if endpoints is None:
            continue
        road = roads.get(road_id)
        if road is None:
            continue
        if exclude_left_turn and _road_matches_formway_bit(road, left_turn_formway_bit):
            continue
        if exclude_formway_bits_any and _road_matches_any_formway_bits(road, exclude_formway_bits_any):
            continue
        snode_id, enode_id = endpoints
        if road.direction in {0, 1, 2}:
            filtered_lists[snode_id].append(TraversalEdge(road_id, snode_id, enode_id))
        if road.direction in {0, 1, 3}:
            filtered_lists[enode_id].append(TraversalEdge(road_id, enode_id, snode_id))
    return {node_id: tuple(edges) for node_id, edges in filtered_lists.items()}


def _build_direction_support_index(
    context: Step1GraphContext,
) -> dict[str, dict[str, set[str]]]:
    return _build_direction_support_index_from_adjacency(context.directed)


def _build_direction_support_index_from_adjacency(
    adjacency: dict[str, tuple[TraversalEdge, ...]],
) -> dict[str, dict[str, set[str]]]:
    support_index: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for from_node_id, edges in adjacency.items():
        for edge in edges:
            support_index[from_node_id][edge.road_id].add("out")
            support_index[edge.to_node][edge.road_id].add("in")
    return {
        node_id: {road_id: set(directions) for road_id, directions in road_map.items()}
        for node_id, road_map in support_index.items()
    }


def _classify_component_directionality(
    component_road_ids: tuple[str, ...],
    *,
    roads: dict[str, RoadRecord],
) -> tuple[str, tuple[str, ...]]:
    bidirectional_road_ids = tuple(
        sorted(
            (
                road_id
                for road_id in component_road_ids
                if road_id in roads and roads[road_id].direction in {0, 1}
            ),
            key=_sort_key,
        )
    )
    if not component_road_ids:
        return "empty_component", ()
    if not bidirectional_road_ids:
        return "one_way_only", ()
    if len(bidirectional_road_ids) == len(component_road_ids):
        return "bidirectional_only", bidirectional_road_ids
    return "mixed_with_bidirectional", bidirectional_road_ids


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


def _classify_parallel_corridor_directionality(
    *,
    attachment_node_ids: tuple[str, ...],
    directed_adjacency: dict[str, tuple[TraversalEdge, ...]],
) -> tuple[str, tuple[str, ...]]:
    if len(attachment_node_ids) != 2:
        return "not_applicable", ()
    a_node_id, b_node_id = attachment_node_ids
    directions: list[str] = []
    if _path_exists_directed(a_node_id, b_node_id, adjacency=directed_adjacency):
        directions.append(f"{a_node_id}->{b_node_id}")
    if _path_exists_directed(b_node_id, a_node_id, adjacency=directed_adjacency):
        directions.append(f"{b_node_id}->{a_node_id}")

    if len(directions) == 2:
        return "bidirectional_parallel", tuple(directions)
    if len(directions) == 1:
        return "one_way_parallel", tuple(directions)
    return "no_directed_attachment_path", ()


def _classify_attachment_flow_status(
    *,
    component_road_ids: tuple[str, ...],
    attachment_node_ids: tuple[str, ...],
    road_endpoints: dict[str, tuple[str, str]],
    direction_support_index: dict[str, dict[str, set[str]]],
) -> tuple[str, tuple[str, ...]]:
    if len(attachment_node_ids) < 2:
        return "side_access_attachment_insufficient", ()

    direction_labels: list[str] = []
    departure_count = 0
    return_count = 0
    ambiguous = False

    component_road_id_set = set(component_road_ids)
    for node_id in attachment_node_ids:
        node_component_road_ids = sorted(
            (road_id for road_id in component_road_id_set if node_id in road_endpoints.get(road_id, ())),
            key=_sort_key,
        )
        node_dirs: set[str] = set()
        for road_id in node_component_road_ids:
            node_dirs.update(direction_support_index.get(node_id, {}).get(road_id, set()))
        if node_dirs == {"out"}:
            departure_count += 1
            direction_labels.append(f"{node_id}:out")
        elif node_dirs == {"in"}:
            return_count += 1
            direction_labels.append(f"{node_id}:in")
        elif node_dirs == {"in", "out"}:
            ambiguous = True
            direction_labels.append(f"{node_id}:both")
        else:
            ambiguous = True
            direction_labels.append(f"{node_id}:none")

    if ambiguous:
        return "single_side_attachment_flow_ambiguous", tuple(direction_labels)
    if len(attachment_node_ids) != 2:
        return "single_side_attachment_flow_not_two_attachments", tuple(direction_labels)
    if departure_count != 1 or return_count != 1:
        return "single_side_attachment_flow_direction_mismatch", tuple(direction_labels)
    return "single_departure_return", tuple(direction_labels)


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
            forward_geometry = _line_geometry_from_coords(ring_coords)
            reverse_geometry = _line_geometry_from_coords(reverse_coords)
            max_dual_carriageway_separation_m = _max_nearest_distance_m(forward_geometry, reverse_geometry) or 0.0
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
                max_dual_carriageway_separation_m=max_dual_carriageway_separation_m,
                is_bidirectional_minimal_loop=is_bidirectional_minimal_loop,
                is_semantic_node_group_closure=is_semantic_node_group_closure,
            )
            if signed_area > 0 or is_bidirectional_minimal_loop or is_semantic_node_group_closure:
                counterclockwise_candidates.append(candidate)
            else:
                clockwise_only_found = True

    counterclockwise_candidates.sort(key=lambda item: (abs(item.signed_area), item.total_length, len(item.road_ids)))
    return counterclockwise_candidates, clockwise_only_found


def _split_dual_separation_candidates(
    candidates: list[TrunkCandidate],
) -> tuple[list[TrunkCandidate], list[TrunkCandidate]]:
    passed: list[TrunkCandidate] = []
    failed: list[TrunkCandidate] = []
    for candidate in candidates:
        if candidate.max_dual_carriageway_separation_m <= MAX_DUAL_CARRIAGEWAY_SEPARATION_M:
            passed.append(candidate)
        else:
            failed.append(candidate)
    return passed, failed


def _best_dual_separation_failure(candidates: list[TrunkCandidate]) -> Optional[TrunkCandidate]:
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item.max_dual_carriageway_separation_m, item.total_length))


def _dual_separation_support_info(candidate: Optional[TrunkCandidate]) -> dict[str, Any]:
    return {
        "dual_carriageway_separation_gate_limit_m": MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
        "dual_carriageway_max_separation_m": (
            None if candidate is None else candidate.max_dual_carriageway_separation_m
        ),
    }


def _tjunction_node_kind(node: SemanticNodeRecord) -> int:
    kind_2 = int(getattr(node, "kind_2", 0) or 0)
    if kind_2 > 0:
        return kind_2
    raw_kind = int(node.raw_properties.get("kind") or node.raw_kind or 0)
    return raw_kind


def _semantic_node_grade(node: SemanticNodeRecord) -> int:
    grade_2 = int(getattr(node, "grade_2", 0) or 0)
    if grade_2 > 0:
        return grade_2
    raw_grade = int(node.raw_properties.get("grade") or node.raw_grade or 0)
    return raw_grade


def _is_tjunction_weak_connector_node(node: SemanticNodeRecord) -> bool:
    mainnodeid = node.raw_properties.get("mainnodeid")
    cross_flag = int(node.raw_properties.get("cross_flag") or 0)
    node_kind = _tjunction_node_kind(node)
    return mainnodeid in {None, ""} and len(node.member_node_ids) == 1 and node_kind == 1 and cross_flag == 0


def _is_tjunction_support_anchor_node(node: SemanticNodeRecord) -> bool:
    cross_flag = int(node.raw_properties.get("cross_flag") or 0)
    node_kind = _tjunction_node_kind(node)
    return node_kind == 2048 and cross_flag >= 2


def _tjunction_vertical_tracking_gate_info(
    pair: PairRecord,
    *,
    candidate: TrunkCandidate,
    context: Step1GraphContext,
) -> Optional[dict[str, Any]]:
    if not candidate.is_bidirectional_minimal_loop:
        return None
    if not pair.through_node_ids:
        return None

    internal_node_ids = (
        set(candidate.forward_path.node_ids[1:-1]) | set(candidate.reverse_path.node_ids[1:-1])
    ) - {pair.a_node_id, pair.b_node_id}
    if not internal_node_ids:
        return None

    weak_connector_node_ids: list[str] = []
    support_anchor_node_ids: list[str] = []
    for node_id in sorted(internal_node_ids, key=_sort_key):
        node = context.semantic_nodes.get(node_id)
        if node is None:
            continue
        if _is_tjunction_weak_connector_node(node):
            weak_connector_node_ids.append(node_id)
        if _is_tjunction_support_anchor_node(node):
            support_anchor_node_ids.append(node_id)

    if len(weak_connector_node_ids) < 2 or not support_anchor_node_ids:
        return None

    return {
        **_dual_separation_support_info(candidate),
        "t_junction_vertical_tracking_blocked": True,
        "t_junction_support_anchor_node_ids": support_anchor_node_ids,
        "t_junction_weak_connector_node_ids": weak_connector_node_ids,
        "t_junction_through_node_ids": list(pair.through_node_ids),
    }


def _split_tjunction_vertical_tracking_candidates(
    pair: PairRecord,
    *,
    candidates: list[TrunkCandidate],
    context: Step1GraphContext,
) -> tuple[list[TrunkCandidate], list[tuple[TrunkCandidate, dict[str, Any]]]]:
    kept: list[TrunkCandidate] = []
    blocked: list[tuple[TrunkCandidate, dict[str, Any]]] = []
    for candidate in candidates:
        gate_info = _tjunction_vertical_tracking_gate_info(pair, candidate=candidate, context=context)
        if gate_info is None:
            kept.append(candidate)
        else:
            blocked.append((candidate, gate_info))
    return kept, blocked


def _bidirectional_side_bypass_gate_info(
    pair: PairRecord,
    *,
    candidate: TrunkCandidate,
    context: Step1GraphContext,
) -> Optional[dict[str, Any]]:
    if not candidate.is_bidirectional_minimal_loop:
        return None
    if len(candidate.road_ids) < 6:
        return None

    road_kinds = {int(context.roads[road_id].road_kind or 0) for road_id in candidate.road_ids}
    if 2 not in road_kinds or not any(road_kind >= 3 for road_kind in road_kinds):
        return None

    internal_node_ids = (
        set(candidate.forward_path.node_ids[1:-1]) | set(candidate.reverse_path.node_ids[1:-1])
    ) - {pair.a_node_id, pair.b_node_id}
    if not internal_node_ids:
        return None

    high_grade_support_node_ids: list[str] = []
    weak_connector_node_ids: list[str] = []
    for node_id in sorted(internal_node_ids, key=_sort_key):
        node = context.semantic_nodes.get(node_id)
        if node is None:
            continue
        node_kind = _tjunction_node_kind(node)
        node_grade = _semantic_node_grade(node)
        if node_kind == 1 and node_grade >= 2:
            weak_connector_node_ids.append(node_id)
            continue
        if node_kind in {4, 64, 2048} and node_grade >= 2:
            high_grade_support_node_ids.append(node_id)

    if len(high_grade_support_node_ids) < 3 or len(weak_connector_node_ids) < 1:
        return None

    return {
        **_dual_separation_support_info(candidate),
        "bidirectional_side_bypass_blocked": True,
        "bidirectional_side_bypass_high_grade_node_ids": high_grade_support_node_ids,
        "bidirectional_side_bypass_weak_connector_node_ids": weak_connector_node_ids,
        "bidirectional_side_bypass_road_kind_mix": sorted(road_kinds),
    }


def _split_bidirectional_side_bypass_candidates(
    pair: PairRecord,
    *,
    candidates: list[TrunkCandidate],
    context: Step1GraphContext,
) -> tuple[list[TrunkCandidate], list[tuple[TrunkCandidate, dict[str, Any]]]]:
    kept: list[TrunkCandidate] = []
    blocked: list[tuple[TrunkCandidate, dict[str, Any]]] = []
    for candidate in candidates:
        gate_info = _bidirectional_side_bypass_gate_info(pair, candidate=candidate, context=context)
        if gate_info is None:
            kept.append(candidate)
        else:
            blocked.append((candidate, gate_info))
    return kept, blocked


def _evaluate_trunk_choices(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    pruned_road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
    through_rule: ThroughRuleSpec,
    formway_mode: str,
    left_turn_formway_bit: int,
) -> tuple[list[_TrunkEvaluationChoice], Optional[str], tuple[str, ...], dict[str, Any]]:
    collapsed_candidate: Optional[TrunkCandidate] = None
    collapsed_warnings: tuple[str, ...] = ()
    collapsed_failed_candidate: Optional[TrunkCandidate] = None
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
        if (
            collapsed_candidate is not None
            and collapsed_candidate.max_dual_carriageway_separation_m > MAX_DUAL_CARRIAGEWAY_SEPARATION_M
        ):
            collapsed_failed_candidate = collapsed_candidate
            collapsed_candidate = None
            collapsed_warnings = ("dual_carriageway_separation_exceeded",)

    base_adjacency = _build_filtered_directed_adjacency(
        context.roads,
        road_endpoints=road_endpoints,
        allowed_road_ids=pruned_road_ids,
        exclude_left_turn=False,
        left_turn_formway_bit=left_turn_formway_bit,
        exclude_formway_bits_any=through_rule.incident_degree_exclude_formway_bits_any,
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
            context.roads,
            road_endpoints=road_endpoints,
            allowed_road_ids=pruned_road_ids,
            exclude_left_turn=True,
            left_turn_formway_bit=left_turn_formway_bit,
            exclude_formway_bits_any=through_rule.incident_degree_exclude_formway_bits_any,
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
        strict_passed_candidates, strict_failed_candidates = _split_dual_separation_candidates(strict_candidates)
        base_passed_candidates, base_failed_candidates = _split_dual_separation_candidates(base_candidates)
        strict_passed_candidates, strict_blocked_candidates = _split_tjunction_vertical_tracking_candidates(
            pair,
            candidates=strict_passed_candidates,
            context=context,
        )
        strict_passed_candidates, strict_side_bypass_blocked_candidates = _split_bidirectional_side_bypass_candidates(
            pair,
            candidates=strict_passed_candidates,
            context=context,
        )
        base_passed_candidates, base_blocked_candidates = _split_tjunction_vertical_tracking_candidates(
            pair,
            candidates=base_passed_candidates,
            context=context,
        )
        base_passed_candidates, base_side_bypass_blocked_candidates = _split_bidirectional_side_bypass_candidates(
            pair,
            candidates=base_passed_candidates,
            context=context,
        )
        if collapsed_candidate is not None:
            return [
                _TrunkEvaluationChoice(
                    candidate=collapsed_candidate,
                    warning_codes=collapsed_warnings,
                    support_info=_dual_separation_support_info(collapsed_candidate),
                )
            ], None, collapsed_warnings, _dual_separation_support_info(collapsed_candidate)
        if strict_passed_candidates:
            choices = [
                _TrunkEvaluationChoice(
                    candidate=candidate,
                    warning_codes=(),
                    support_info=_dual_separation_support_info(candidate),
                )
                for candidate in strict_passed_candidates
            ]
            return choices, None, (), choices[0].support_info
        if base_passed_candidates:
            return [], "left_turn_only_polluted_trunk", (), _dual_separation_support_info(base_passed_candidates[0])
        if strict_blocked_candidates or base_blocked_candidates:
            blocked_candidate, blocked_gate_info = min(
                strict_blocked_candidates or base_blocked_candidates,
                key=lambda item: (item[0].total_length, len(item[0].road_ids)),
            )
            return [], "t_junction_vertical_tracking_blocked", (), {
                **_dual_separation_support_info(blocked_candidate),
                **blocked_gate_info,
            }
        if strict_side_bypass_blocked_candidates or base_side_bypass_blocked_candidates:
            blocked_candidate, blocked_gate_info = min(
                strict_side_bypass_blocked_candidates or base_side_bypass_blocked_candidates,
                key=lambda item: (item[0].total_length, len(item[0].road_ids)),
            )
            return [], "bidirectional_side_bypass_blocked", (), {
                **_dual_separation_support_info(blocked_candidate),
                **blocked_gate_info,
            }
        if strict_failed_candidates or base_failed_candidates or collapsed_failed_candidate is not None:
            failure_candidate = _best_dual_separation_failure(
                strict_failed_candidates or base_failed_candidates or ([collapsed_failed_candidate] if collapsed_failed_candidate else [])
            )
            return [], "dual_carriageway_separation_exceeded", (), _dual_separation_support_info(failure_candidate)
        if strict_clockwise_only or base_clockwise_only:
            return [], "only_clockwise_loop", (), _dual_separation_support_info(None)
        return [], "no_valid_trunk", (), _dual_separation_support_info(None)

    if collapsed_candidate is not None:
        return [
            _TrunkEvaluationChoice(
                candidate=collapsed_candidate,
                warning_codes=collapsed_warnings,
                support_info=_dual_separation_support_info(collapsed_candidate),
            )
        ], None, collapsed_warnings, _dual_separation_support_info(collapsed_candidate)
    base_passed_candidates, base_failed_candidates = _split_dual_separation_candidates(base_candidates)
    base_passed_candidates, base_blocked_candidates = _split_tjunction_vertical_tracking_candidates(
        pair,
        candidates=base_passed_candidates,
        context=context,
    )
    base_passed_candidates, base_side_bypass_blocked_candidates = _split_bidirectional_side_bypass_candidates(
        pair,
        candidates=base_passed_candidates,
        context=context,
    )
    if not base_passed_candidates:
        if base_blocked_candidates:
            blocked_candidate, blocked_gate_info = min(
                base_blocked_candidates,
                key=lambda item: (item[0].total_length, len(item[0].road_ids)),
            )
            return [], "t_junction_vertical_tracking_blocked", (), {
                **_dual_separation_support_info(blocked_candidate),
                **blocked_gate_info,
            }
        if base_side_bypass_blocked_candidates:
            blocked_candidate, blocked_gate_info = min(
                base_side_bypass_blocked_candidates,
                key=lambda item: (item[0].total_length, len(item[0].road_ids)),
            )
            return [], "bidirectional_side_bypass_blocked", (), {
                **_dual_separation_support_info(blocked_candidate),
                **blocked_gate_info,
            }
        if base_failed_candidates or collapsed_failed_candidate is not None:
            failure_candidate = _best_dual_separation_failure(
                base_failed_candidates or ([collapsed_failed_candidate] if collapsed_failed_candidate else [])
            )
            return [], "dual_carriageway_separation_exceeded", (), _dual_separation_support_info(failure_candidate)
        if base_clockwise_only:
            return [], "only_clockwise_loop", (), _dual_separation_support_info(None)
        return [], "no_valid_trunk", (), _dual_separation_support_info(None)

    warnings: tuple[str, ...] = ()
    choices = [
        _TrunkEvaluationChoice(
            candidate=candidate,
            warning_codes=("formway_unreliable_warning",) if formway_mode == "audit_only" and candidate.left_turn_road_ids else (),
            support_info=_dual_separation_support_info(candidate),
        )
        for candidate in base_passed_candidates
    ]
    if choices:
        warnings = choices[0].warning_codes
    return choices, None, warnings, choices[0].support_info


def _evaluate_trunk(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    pruned_road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
    through_rule: ThroughRuleSpec,
    formway_mode: str,
    left_turn_formway_bit: int,
) -> tuple[Optional[TrunkCandidate], Optional[str], tuple[str, ...], dict[str, Any]]:
    choices, reject_reason, warning_codes, support_info = _evaluate_trunk_choices(
        pair,
        context=context,
        pruned_road_ids=pruned_road_ids,
        road_endpoints=road_endpoints,
        through_rule=through_rule,
        formway_mode=formway_mode,
        left_turn_formway_bit=left_turn_formway_bit,
    )
    if not choices:
        return None, reject_reason, warning_codes, support_info
    first_choice = choices[0]
    return first_choice.candidate, reject_reason, first_choice.warning_codes, first_choice.support_info


def _alternative_trunk_only_road_ids(
    trunk_choices: list[_TrunkEvaluationChoice],
    *,
    current_choice_index: int,
) -> set[str]:
    if len(trunk_choices) <= 1:
        return set()
    current_road_ids = set(trunk_choices[current_choice_index].candidate.road_ids)
    alternative_road_ids: set[str] = set()
    for index, choice in enumerate(trunk_choices):
        if index == current_choice_index:
            continue
        alternative_road_ids.update(choice.candidate.road_ids)
    return alternative_road_ids - current_road_ids


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
        context.roads,
        road_endpoints=road_endpoints,
        allowed_road_ids=set(filtered_support_road_ids),
        exclude_left_turn=formway_mode == "strict",
        left_turn_formway_bit=left_turn_formway_bit,
        exclude_formway_bits_any=through_rule.incident_degree_exclude_formway_bits_any,
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
            max_dual_carriageway_separation_m=0.0,
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


def _iter_candidate_channel_features(
    *,
    context: Step1GraphContext,
    validations: Iterable[PairValidationResult],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        for road_id in validation.candidate_channel_road_ids:
            yield _road_feature(
                context.roads[road_id],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="candidate_channel",
            )


def _iter_working_graph_debug_features(
    *,
    context: Step1GraphContext,
    validations: Iterable[PairValidationResult],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        support_info = dict(validation.support_info)
        branch_cut_infos = list(support_info.get("branch_cut_infos", []))
        residual_infos = list(support_info.get("step3_residual_infos", []))

        for road_id in validation.candidate_channel_road_ids:
            yield _road_feature(
                context.roads[road_id],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="working_graph",
                extra_props={"debug_stage": "candidate_channel"},
            )

        for branch_cut_info in branch_cut_infos:
            branch_cut_props = {key: value for key, value in branch_cut_info.items() if key != "road_id"}
            yield _road_feature(
                context.roads[branch_cut_info["road_id"]],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="working_graph",
                extra_props={"debug_stage": "branch_cut", **branch_cut_props},
            )

        for road_id in validation.trunk_road_ids:
            yield _road_feature(
                context.roads[road_id],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="working_graph",
                extra_props={"debug_stage": "trunk"},
            )

        for road_id in validation.segment_road_ids:
            yield _road_feature(
                context.roads[road_id],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="working_graph",
                extra_props={"debug_stage": "segment_body"},
            )

        for residual_info in residual_infos:
            residual_props = {key: value for key, value in residual_info.items() if key != "road_id"}
            yield _road_feature(
                context.roads[residual_info["road_id"]],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="working_graph",
                extra_props={"debug_stage": "step3_residual", **residual_props},
            )


def _compact_execution_for_validation(execution: Step1StrategyExecution) -> Step1StrategyExecution:
    return replace(
        execution,
        seed_eval={},
        terminate_eval={},
        through_node_ids=set(),
        search_seed_ids=[],
        through_seed_pruned_count=0,
        search_results={},
        search_event_counts={},
        search_event_samples=[],
    )


def _compact_branch_cut_info(info: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "road_id": info.get("road_id"),
        "cut_reason": info.get("cut_reason"),
    }
    for key in (
        "component_id",
        "conflicting_pair_ids",
        "terminate_node_ids",
        "support_barrier_node_ids",
    ):
        value = info.get(key)
        if value not in (None, (), [], {}):
            compact[key] = value
    return compact


def _compact_component_info(info: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "component_id": info.get("component_id"),
        "road_ids": info.get("road_ids", []),
        "attachment_node_ids": info.get("attachment_node_ids", []),
        "internal_support_attachment_node_ids": info.get(
            "internal_support_attachment_node_ids",
            [],
        ),
        "internal_t_support_attachment_node_ids": info.get(
            "internal_t_support_attachment_node_ids",
            [],
        ),
        "component_directionality": info.get("component_directionality"),
        "bidirectional_road_ids": info.get("bidirectional_road_ids", []),
        "attachment_flow_status": info.get("attachment_flow_status"),
        "attachment_direction_labels": info.get("attachment_direction_labels", []),
        "parallel_corridor_directionality": info.get("parallel_corridor_directionality"),
        "parallel_corridor_directions": info.get("parallel_corridor_directions", []),
        "hits_other_terminate": bool(info.get("hits_other_terminate")),
        "terminate_node_ids": info.get("terminate_node_ids", []),
        "contains_other_validated_trunk": bool(info.get("contains_other_validated_trunk")),
        "conflicting_pair_ids": info.get("conflicting_pair_ids", []),
        "blocked_by_transition_same_dir": bool(info.get("blocked_by_transition_same_dir")),
        "side_access_metric": info.get("side_access_metric"),
        "side_access_distance_m": info.get("side_access_distance_m"),
        "side_access_gate_passed": info.get("side_access_gate_passed"),
        "kept_as_segment_body": bool(info.get("kept_as_segment_body")),
        "moved_to_step3_residual": bool(info.get("moved_to_step3_residual")),
        "moved_to_branch_cut": bool(info.get("moved_to_branch_cut")),
        "decision_reason": info.get("decision_reason"),
    }
    if info.get("transition_block_infos"):
        compact["transition_block_infos"] = info["transition_block_infos"]
    return compact


def _compact_residual_info(info: dict[str, Any]) -> dict[str, Any]:
    compact: dict[str, Any] = {
        "road_id": info.get("road_id"),
        "component_id": info.get("component_id"),
        "residual_reason": info.get("residual_reason"),
        "blocked_by_transition_same_dir": bool(info.get("blocked_by_transition_same_dir")),
        "conflicting_pair_ids": info.get("conflicting_pair_ids", []),
        "terminate_node_ids": info.get("terminate_node_ids", []),
        "side_access_distance_m": info.get("side_access_distance_m"),
        "side_access_gate_passed": info.get("side_access_gate_passed"),
    }
    if info.get("hint_cut_reasons"):
        compact["hint_cut_reasons"] = info["hint_cut_reasons"]
    return compact


def _compact_support_info_for_release(
    support_info: dict[str, Any],
    *,
    keep_tighten_fields: bool,
) -> dict[str, Any]:
    compact: dict[str, Any] = {}
    passthrough_keys = (
        "boundary_terminate_node_ids",
        "historical_boundary_node_ids",
        "trunk_signed_area",
        "trunk_mode",
        "bidirectional_minimal_loop",
        "semantic_node_group_closure",
        "dual_carriageway_separation_gate_limit_m",
        "dual_carriageway_max_separation_m",
    )
    for key in passthrough_keys:
        if key in support_info:
            compact[key] = support_info[key]

    branch_cut_infos = support_info.get("branch_cut_infos")
    if branch_cut_infos:
        compact["branch_cut_infos"] = [
            _compact_branch_cut_info(dict(info)) for info in branch_cut_infos
        ]

    if keep_tighten_fields:
        segment_candidate_road_ids = support_info.get("segment_body_candidate_road_ids")
        if segment_candidate_road_ids:
            compact["segment_body_candidate_road_ids"] = list(segment_candidate_road_ids)
        segment_candidate_cut_infos = support_info.get("segment_body_candidate_cut_infos")
        if segment_candidate_cut_infos:
            compact["segment_body_candidate_cut_infos"] = [
                _compact_branch_cut_info(dict(info)) for info in segment_candidate_cut_infos
            ]
    else:
        component_infos = support_info.get("non_trunk_components")
        if component_infos:
            compact["non_trunk_components"] = [
                _compact_component_info(dict(info)) for info in component_infos
            ]
        residual_infos = support_info.get("step3_residual_infos")
        if residual_infos:
            compact["step3_residual_infos"] = [
                _compact_residual_info(dict(info)) for info in residual_infos
            ]

    return compact


def _compact_validation_result_for_release(
    validation: PairValidationResult,
    *,
    keep_tighten_fields: bool,
) -> PairValidationResult:
    support_info = _compact_support_info_for_release(
        dict(validation.support_info),
        keep_tighten_fields=keep_tighten_fields,
    )
    support_info.setdefault("candidate_channel_road_count", len(validation.candidate_channel_road_ids))
    support_info.setdefault("pruned_road_count", len(validation.pruned_road_ids))
    support_info.setdefault("trunk_road_count", len(validation.trunk_road_ids))
    support_info.setdefault("segment_body_road_count", len(validation.segment_road_ids))
    support_info.setdefault("residual_road_count", len(validation.residual_road_ids))
    support_info.setdefault("branch_cut_road_count", len(validation.branch_cut_road_ids))
    support_info.setdefault("boundary_terminate_node_count", len(validation.boundary_terminate_node_ids))

    if keep_tighten_fields and validation.validated_status == "validated":
        pruned_road_ids = validation.pruned_road_ids
        trunk_road_ids = validation.trunk_road_ids
        segment_road_ids: tuple[str, ...] = ()
        residual_road_ids: tuple[str, ...] = ()
    elif validation.validated_status == "validated":
        pruned_road_ids = ()
        trunk_road_ids = validation.trunk_road_ids
        segment_road_ids = validation.segment_road_ids
        residual_road_ids = validation.residual_road_ids
    else:
        pruned_road_ids = ()
        trunk_road_ids = ()
        segment_road_ids = ()
        residual_road_ids = ()

    return replace(
        validation,
        candidate_channel_road_ids=(),
        pruned_road_ids=pruned_road_ids,
        trunk_road_ids=trunk_road_ids,
        segment_road_ids=segment_road_ids,
        residual_road_ids=residual_road_ids,
        branch_cut_road_ids=(),
        boundary_terminate_node_ids=(),
        support_info=support_info,
    )


def _road_length_index(context: Step1GraphContext) -> dict[str, float]:
    return {
        road_id: _geometry_length(road.geometry)
        for road_id, road in context.roads.items()
    }


def _road_node_index(road_endpoints: dict[str, tuple[str, str]]) -> dict[str, tuple[str, str]]:
    return dict(road_endpoints)


def _arbitration_boundary_node_ids(
    execution: Step1StrategyExecution,
    *,
    hard_stop_node_ids: set[str],
) -> set[str]:
    return set(execution.seed_ids) | set(execution.terminate_ids) | set(hard_stop_node_ids)


def _arbitration_semantic_conflict_node_ids(context: Step1GraphContext) -> set[str]:
    result: set[str] = set()
    for semantic_node_id, node in context.semantic_nodes.items():
        if node.kind_2 in {4, 64, 2048} and node.grade_2 in {1, 2, 3}:
            result.add(semantic_node_id)
    return result


def _arbitration_strong_anchor_node_ids(context: Step1GraphContext) -> set[str]:
    result: set[str] = set()
    for semantic_node_id, node in context.semantic_nodes.items():
        if node.kind_2 in {4, 64, 2048} and node.grade_2 >= 2:
            result.add(semantic_node_id)
    return result


def _arbitration_tjunction_anchor_node_ids(context: Step1GraphContext) -> set[str]:
    result: set[str] = set()
    for semantic_node_id, node in context.semantic_nodes.items():
        if _is_tjunction_support_anchor_node(node):
            result.add(semantic_node_id)
    return result


def _arbitration_weak_endpoint_node_ids(context: Step1GraphContext) -> set[str]:
    result: set[str] = set()
    for semantic_node_id, node in context.semantic_nodes.items():
        mainnodeid = node.raw_properties.get("mainnodeid")
        if mainnodeid in {None, ""} and len(node.member_node_ids) == 1:
            result.add(semantic_node_id)
    return result


def _pair_validation_from_option(
    option: PairArbitrationOption,
    *,
    decision: PairArbitrationDecision,
    conflict_pair_id: Optional[str],
    left_turn_excluded_mode: str,
    compact_release_payloads: bool,
) -> PairValidationResult:
    support_info = dict(option.support_info)
    support_info["arbitration"] = {
        "component_id": decision.component_id,
        "status": decision.arbitration_status,
        "selected_option_id": decision.selected_option_id,
        "endpoint_boundary_penalty": decision.endpoint_boundary_penalty,
        "strong_anchor_win_count": decision.strong_anchor_win_count,
        "corridor_naturalness_score": decision.corridor_naturalness_score,
        "contested_trunk_coverage_count": decision.contested_trunk_coverage_count,
        "contested_trunk_coverage_ratio": decision.contested_trunk_coverage_ratio,
        "internal_endpoint_penalty": decision.internal_endpoint_penalty,
        "body_connectivity_support": decision.body_connectivity_support,
        "semantic_conflict_penalty": decision.semantic_conflict_penalty,
        "lose_reason": decision.lose_reason,
    }
    result = PairValidationResult(
        pair_id=option.pair_id,
        a_node_id=option.a_node_id,
        b_node_id=option.b_node_id,
        candidate_status="candidate",
        validated_status="validated" if decision.arbitration_status == "win" else "rejected",
        reject_reason=None if decision.arbitration_status == "win" else decision.lose_reason,
        trunk_mode=option.trunk_mode,
        trunk_found=True,
        counterclockwise_ok=option.counterclockwise_ok,
        left_turn_excluded_mode=left_turn_excluded_mode,
        warning_codes=option.warning_codes,
        candidate_channel_road_ids=option.candidate_channel_road_ids,
        pruned_road_ids=option.pruned_road_ids,
        trunk_road_ids=option.trunk_road_ids,
        segment_road_ids=option.segment_road_ids if decision.arbitration_status == "win" else (),
        residual_road_ids=(),
        branch_cut_road_ids=option.branch_cut_road_ids,
        boundary_terminate_node_ids=option.boundary_terminate_node_ids,
        transition_same_dir_blocked=option.transition_same_dir_blocked,
        support_info=support_info,
        conflict_pair_id=conflict_pair_id,
        single_pair_legal=True,
        arbitration_status=decision.arbitration_status,
        arbitration_component_id=decision.component_id,
        arbitration_option_id=decision.selected_option_id,
        lose_reason=decision.lose_reason,
    )
    if compact_release_payloads:
        result = _compact_validation_result_for_release(
            result,
            keep_tighten_fields=decision.arbitration_status == "win",
        )
    return result


def _single_pair_illegal_validation(
    validation: PairValidationResult,
    *,
    decision: PairArbitrationDecision,
    compact_release_payloads: bool,
) -> PairValidationResult:
    current = replace(
        validation,
        single_pair_legal=False,
        arbitration_status="lose",
        arbitration_component_id="",
        arbitration_option_id=None,
        lose_reason=decision.lose_reason,
    )
    support_info = dict(current.support_info)
    support_info["arbitration"] = {
        "component_id": "",
        "status": "lose",
        "selected_option_id": None,
        "endpoint_boundary_penalty": 0,
        "strong_anchor_win_count": 0,
        "corridor_naturalness_score": 0,
        "contested_trunk_coverage_count": 0,
        "contested_trunk_coverage_ratio": 0.0,
        "internal_endpoint_penalty": 0,
        "body_connectivity_support": 0.0,
        "semantic_conflict_penalty": 0,
        "lose_reason": decision.lose_reason,
    }
    current = replace(current, support_info=support_info)
    if compact_release_payloads:
        current = _compact_validation_result_for_release(current, keep_tighten_fields=False)
    return current


def _empty_pair_arbitration_outcome() -> PairArbitrationOutcome:
    return PairArbitrationOutcome(
        selected_options_by_pair_id={},
        decisions=[],
        conflict_records=[],
        components=[],
    )


def _validation_road_count(
    road_ids: tuple[str, ...],
    support_info: dict[str, Any],
    count_key: str,
) -> int:
    value = support_info.get(count_key)
    if value is None:
        return len(road_ids)
    return int(value)


def _collect_validation_summary(validations: list[PairValidationResult]) -> dict[str, Any]:
    validated_pair_count = 0
    rejected_pair_count = 0
    total_branch_cut_count = 0
    clockwise_reject_count = 0
    left_turn_trunk_reject_count = 0
    disconnected_after_prune_count = 0
    shared_trunk_conflict_count = 0
    dual_carriageway_separation_reject_count = 0
    formway_warning_count = 0
    branch_cut_component_keys: set[tuple[str, str]] = set()
    other_terminate_cut_keys: set[tuple[str, str]] = set()
    other_trunk_conflict_keys: set[tuple[str, str]] = set()
    transition_same_dir_block_keys: set[tuple[str, str]] = set()
    residual_component_keys: set[tuple[str, str]] = set()
    side_access_distance_block_keys: set[tuple[str, str]] = set()

    for validation in validations:
        if validation.validated_status == "validated":
            validated_pair_count += 1
        else:
            rejected_pair_count += 1

        if validation.reject_reason == "only_clockwise_loop":
            clockwise_reject_count += 1
        if validation.reject_reason == "left_turn_only_polluted_trunk":
            left_turn_trunk_reject_count += 1
        if validation.reject_reason == "disconnected_after_prune":
            disconnected_after_prune_count += 1
        if validation.reject_reason == "shared_trunk_conflict":
            shared_trunk_conflict_count += 1
        if validation.reject_reason == "dual_carriageway_separation_exceeded":
            dual_carriageway_separation_reject_count += 1
        if "formway_unreliable_warning" in validation.warning_codes:
            formway_warning_count += 1

        branch_cut_infos = validation.support_info.get("branch_cut_infos", ())
        total_branch_cut_count += len(branch_cut_infos)
        for branch_cut_info in branch_cut_infos:
            cut_key = (
                validation.pair_id,
                str(
                    branch_cut_info.get("component_id")
                    or f"{branch_cut_info.get('cut_reason')}::{branch_cut_info.get('road_id')}"
                ),
            )
            branch_cut_component_keys.add(cut_key)
            if branch_cut_info.get("cut_reason") in {"hits_other_terminate", "branch_leads_to_other_terminate"}:
                other_terminate_cut_keys.add(cut_key)
            if branch_cut_info.get("cut_reason") == "contains_other_validated_trunk":
                other_trunk_conflict_keys.add(cut_key)

        for component_info in validation.support_info.get("non_trunk_components", ()):
            component_key = (validation.pair_id, str(component_info.get("component_id", "")))
            if component_info.get("moved_to_step3_residual"):
                residual_component_keys.add(component_key)
            if component_info.get("decision_reason") == "side_access_distance_exceeded":
                side_access_distance_block_keys.add(component_key)
            if component_info.get("blocked_by_transition_same_dir"):
                transition_same_dir_block_keys.add(component_key)

    return {
        "candidate_pair_count": len(validations),
        "validated_pair_count": validated_pair_count,
        "rejected_pair_count": rejected_pair_count,
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
        "dual_carriageway_separation_reject_count": dual_carriageway_separation_reject_count,
        "side_access_distance_block_count": len(side_access_distance_block_keys),
        "formway_warning_count": formway_warning_count,
    }


def _iter_validation_rows(validations: list[PairValidationResult]) -> Iterable[dict[str, Any]]:
    for validation in validations:
        yield {
            "pair_id": validation.pair_id,
            "a_node_id": validation.a_node_id,
            "b_node_id": validation.b_node_id,
            "candidate_status": validation.candidate_status,
            "validated_status": validation.validated_status,
            "reject_reason": validation.reject_reason or "",
            "trunk_mode": validation.trunk_mode,
            "trunk_found": validation.trunk_found,
            "counterclockwise_ok": validation.counterclockwise_ok,
            "segment_body_road_count": _validation_road_count(
                validation.segment_road_ids,
                validation.support_info,
                "segment_body_road_count",
            ),
            "residual_road_count": _validation_road_count(
                validation.residual_road_ids,
                validation.support_info,
                "residual_road_count",
            ),
            "transition_same_dir_blocked": validation.transition_same_dir_blocked,
            "left_turn_excluded_mode": validation.left_turn_excluded_mode,
            "support_info": _compact_json(dict(validation.support_info)),
        }


def _iter_validated_rows(validations: list[PairValidationResult]) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        yield {
            "pair_id": validation.pair_id,
            "a_node_id": validation.a_node_id,
            "b_node_id": validation.b_node_id,
            "trunk_mode": validation.trunk_mode,
            "left_turn_excluded_mode": validation.left_turn_excluded_mode,
            "warning_codes": ";".join(validation.warning_codes),
            "segment_body_road_count": _validation_road_count(
                validation.segment_road_ids,
                validation.support_info,
                "segment_body_road_count",
            ),
            "residual_road_count": _validation_road_count(
                validation.residual_road_ids,
                validation.support_info,
                "residual_road_count",
            ),
        }


def _iter_rejected_rows(validations: list[PairValidationResult]) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status == "validated":
            continue
        yield {
            "pair_id": validation.pair_id,
            "a_node_id": validation.a_node_id,
            "b_node_id": validation.b_node_id,
            "reject_reason": validation.reject_reason or "",
            "warning_codes": ";".join(validation.warning_codes),
            "conflict_pair_id": validation.conflict_pair_id or "",
        }


def _iter_validated_link_features(
    *,
    context: Step1GraphContext,
    validations: list[PairValidationResult],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        yield _line_feature(
            a_node=context.semantic_nodes[validation.a_node_id],
            b_node=context.semantic_nodes[validation.b_node_id],
            properties={
                "pair_id": validation.pair_id,
                "a_node_id": validation.a_node_id,
                "b_node_id": validation.b_node_id,
                "strategy_id": strategy_id,
                "validated_status": validation.validated_status,
                "trunk_mode": validation.trunk_mode,
            },
        )


def _iter_trunk_features(
    *,
    context: Step1GraphContext,
    validations: list[PairValidationResult],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        feature = _pair_multiline_feature(
            context=context,
            pair_id=validation.pair_id,
            a_node_id=validation.a_node_id,
            b_node_id=validation.b_node_id,
            strategy_id=strategy_id,
            layer_role="trunk",
            road_ids=validation.trunk_road_ids,
            extra_props={
                "validated_status": validation.validated_status,
                "trunk_mode": validation.trunk_mode,
                "warning_codes": list(validation.warning_codes),
                "left_turn_excluded_mode": validation.left_turn_excluded_mode,
                "dual_carriageway_max_separation_m": validation.support_info.get(
                    "dual_carriageway_max_separation_m"
                ),
            },
        )
        if feature is not None:
            yield feature


def _iter_segment_body_features(
    *,
    context: Step1GraphContext,
    validations: list[PairValidationResult],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        feature = _pair_multiline_feature(
            context=context,
            pair_id=validation.pair_id,
            a_node_id=validation.a_node_id,
            b_node_id=validation.b_node_id,
            strategy_id=strategy_id,
            layer_role="segment_body",
            road_ids=validation.segment_road_ids,
            extra_props={
                "validated_status": validation.validated_status,
                "trunk_mode": validation.trunk_mode,
                "warning_codes": list(validation.warning_codes),
                "left_turn_excluded_mode": validation.left_turn_excluded_mode,
            },
        )
        if feature is not None:
            yield feature


def _iter_step3_residual_features(
    *,
    context: Step1GraphContext,
    validations: list[PairValidationResult],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        feature = _pair_multiline_feature(
            context=context,
            pair_id=validation.pair_id,
            a_node_id=validation.a_node_id,
            b_node_id=validation.b_node_id,
            strategy_id=strategy_id,
            layer_role="step3_residual",
            road_ids=validation.residual_road_ids,
            extra_props={
                "validated_status": validation.validated_status,
                "trunk_mode": validation.trunk_mode,
                "warning_codes": list(validation.warning_codes),
                "left_turn_excluded_mode": validation.left_turn_excluded_mode,
            },
        )
        if feature is not None:
            yield feature


def _iter_branch_cut_features(
    *,
    context: Step1GraphContext,
    validations: list[PairValidationResult],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        for branch_cut_info in validation.support_info.get("branch_cut_infos", ()):
            branch_cut_props = {key: value for key, value in branch_cut_info.items() if key != "road_id"}
            yield _road_feature(
                context.roads[branch_cut_info["road_id"]],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="branch_cut",
                extra_props=branch_cut_props,
            )


def _iter_member_features(
    *,
    context: Step1GraphContext,
    validations: list[PairValidationResult],
    strategy_id: str,
    layer_role: str,
    road_ids_getter: Callable[[PairValidationResult], Iterable[str]],
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        for road_id in road_ids_getter(validation):
            yield _road_feature(
                context.roads[road_id],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role=layer_role,
            )


def _iter_step3_residual_member_features(
    *,
    context: Step1GraphContext,
    validations: list[PairValidationResult],
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        for residual_info in validation.support_info.get("step3_residual_infos", ()):
            residual_props = {key: value for key, value in residual_info.items() if key != "road_id"}
            yield _road_feature(
                context.roads[residual_info["road_id"]],
                pair_id=validation.pair_id,
                strategy_id=strategy_id,
                layer_role="step3_residual_member",
                extra_props=residual_props,
            )


def _iter_validated_final_rows(validations: list[PairValidationResult]) -> Iterable[dict[str, Any]]:
    for validation in validations:
        yield {
            "pair_id": validation.pair_id,
            "a_node_id": validation.a_node_id,
            "b_node_id": validation.b_node_id,
            "single_pair_legal": validation.single_pair_legal,
            "arbitration_status": validation.arbitration_status,
            "validated_status": validation.validated_status,
            "lose_reason": validation.lose_reason,
            "trunk_mode": validation.trunk_mode,
            "segment_body_road_count": _validation_road_count(
                validation.segment_road_ids,
                validation.support_info,
                "segment_body_road_count",
            ),
            "residual_road_count": _validation_road_count(
                validation.residual_road_ids,
                validation.support_info,
                "residual_road_count",
            ),
        }


def _iter_pair_conflict_rows(arbitration_outcome: PairArbitrationOutcome) -> Iterable[dict[str, Any]]:
    for record in arbitration_outcome.conflict_records:
        for conflict_type in record.conflict_types:
            yield {
                "pair_id": record.pair_id,
                "conflict_pair_id": record.conflict_pair_id,
                "conflict_type": conflict_type,
                "shared_road_count": len(record.shared_road_ids),
                "shared_trunk_road_count": len(record.shared_trunk_road_ids),
            }


def _pair_conflict_components_payload(arbitration_outcome: PairArbitrationOutcome) -> list[dict[str, Any]]:
    return [
        {
            "component_id": component.component_id,
            "pair_ids": list(component.pair_ids),
            "component_size": len(component.pair_ids),
            "contested_road_ids": list(component.contested_road_ids),
            "strong_anchor_node_ids": list(component.strong_anchor_node_ids),
            "exact_solver_used": component.exact_solver_used,
            "fallback_greedy_used": component.fallback_greedy_used,
            "selected_option_ids": list(component.selected_option_ids),
        }
        for component in arbitration_outcome.components
    ]


def _iter_pair_arbitration_rows(
    validations: list[PairValidationResult],
    arbitration_outcome: PairArbitrationOutcome,
) -> Iterable[dict[str, Any]]:
    validation_by_pair_id = {validation.pair_id: validation for validation in validations}
    for decision in arbitration_outcome.decisions:
        validation = validation_by_pair_id.get(decision.pair_id)
        if validation is None:
            continue
        yield {
            "pair_id": decision.pair_id,
            "component_id": decision.component_id,
            "single_pair_legal": decision.single_pair_legal,
            "arbitration_status": decision.arbitration_status,
            "endpoint_boundary_penalty": decision.endpoint_boundary_penalty,
            "strong_anchor_win_count": decision.strong_anchor_win_count,
            "corridor_naturalness_score": decision.corridor_naturalness_score,
            "contested_trunk_coverage_count": decision.contested_trunk_coverage_count,
            "contested_trunk_coverage_ratio": decision.contested_trunk_coverage_ratio,
            "internal_endpoint_penalty": decision.internal_endpoint_penalty,
            "body_connectivity_support": decision.body_connectivity_support,
            "semantic_conflict_penalty": decision.semantic_conflict_penalty,
            "lose_reason": decision.lose_reason,
        }


def _iter_corridor_conflict_features(
    *,
    context: Step1GraphContext,
    arbitration_outcome: PairArbitrationOutcome,
    strategy_id: str,
) -> Iterable[dict[str, Any]]:
    pair_ids_by_component_id = {
        component.component_id: component.pair_ids
        for component in arbitration_outcome.components
    }
    for component in arbitration_outcome.components:
        for road_id in component.contested_road_ids:
            road = context.roads.get(road_id)
            if road is None:
                continue
            yield _road_feature(
                road,
                pair_id="|".join(component.pair_ids),
                strategy_id=strategy_id,
                layer_role="corridor_conflict",
                extra_props={
                    "component_id": component.component_id,
                    "pair_ids": list(pair_ids_by_component_id[component.component_id]),
                    "road_id": road_id,
                },
            )


def _build_target_conflict_audit_xxxs7(
    *,
    validations: list[PairValidationResult],
    arbitration_outcome: PairArbitrationOutcome,
    road_to_node_ids: dict[str, tuple[str, str]],
) -> dict[str, Any]:
    target_pair_ids = ("S2:1019883__1026500", "S2:1026500__1026503")
    target_anchor_node_id = "500588029"
    validation_by_pair_id = {validation.pair_id: validation for validation in validations}
    decision_by_pair_id = {decision.pair_id: decision for decision in arbitration_outcome.decisions}
    pair_entries: dict[str, Any] = {}
    for pair_id in target_pair_ids:
        validation = validation_by_pair_id.get(pair_id)
        decision = decision_by_pair_id.get(pair_id)
        if validation is None or decision is None:
            pair_entries[pair_id] = {"present": False}
            continue
        arbitration_info = validation.support_info.get("arbitration", {})
        pair_entries[pair_id] = {
            "present": True,
            "single_pair_legal": validation.single_pair_legal,
            "arbitration_status": validation.arbitration_status,
            "validated_status": validation.validated_status,
            "lose_reason": validation.lose_reason,
            "component_id": validation.arbitration_component_id,
            "selected_option_id": validation.arbitration_option_id,
            "endpoint_boundary_penalty": arbitration_info.get("endpoint_boundary_penalty", 0),
            "strong_anchor_win_count": arbitration_info.get("strong_anchor_win_count", 0),
            "corridor_naturalness_score": arbitration_info.get("corridor_naturalness_score", 0),
            "contested_trunk_coverage_count": arbitration_info.get("contested_trunk_coverage_count", 0),
            "contested_trunk_coverage_ratio": arbitration_info.get("contested_trunk_coverage_ratio", 0.0),
            "internal_endpoint_penalty": arbitration_info.get("internal_endpoint_penalty", 0),
            "body_connectivity_support": arbitration_info.get("body_connectivity_support", 0.0),
            "semantic_conflict_penalty": arbitration_info.get("semantic_conflict_penalty", 0),
        }

    anchor_owner_pair_ids: list[str] = []
    for validation in validations:
        if validation.validated_status != "validated":
            continue
        candidate_road_ids = set(validation.support_info.get("segment_body_candidate_road_ids", ()))
        road_ids = (
            set(validation.trunk_road_ids)
            | set(validation.segment_road_ids)
            | set(validation.pruned_road_ids)
            | candidate_road_ids
        )
        node_ids: set[str] = set()
        for road_id in road_ids:
            endpoints = road_to_node_ids.get(road_id)
            if endpoints is None:
                continue
            node_ids.update(endpoints)
        if target_anchor_node_id in node_ids:
            anchor_owner_pair_ids.append(validation.pair_id)

    return {
        "target_pair_ids": list(target_pair_ids),
        "target_anchor_node_id": target_anchor_node_id,
        "pairs": pair_entries,
        "anchor_owner_pair_ids": anchor_owner_pair_ids,
        "target_anchor_winner_pair_ids": anchor_owner_pair_ids,
    }


def _write_step2_outputs(
    out_dir: Path,
    *,
    strategy: StrategySpec,
    run_id: str,
    context: Step1GraphContext,
    validations: list[PairValidationResult],
    arbitration_outcome: Optional[PairArbitrationOutcome] = None,
    road_to_node_ids: Optional[dict[str, tuple[str, str]]] = None,
    endpoint_pool_source_map: dict[str, tuple[str, ...]],
    formway_mode: str,
    debug: bool,
    retain_validation_details: bool,
    progress_callback: Optional[Step2ProgressCallback] = None,
) -> Step2StrategyResult:
    if arbitration_outcome is None:
        arbitration_outcome = _empty_pair_arbitration_outcome()
    if road_to_node_ids is None:
        road_to_node_ids = {}
    validation_summary = _collect_validation_summary(validations)

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
    validated_pairs_final_path = out_dir / "validated_pairs_final.csv"
    pair_conflict_table_path = out_dir / "pair_conflict_table.csv"
    pair_conflict_components_path = out_dir / "pair_conflict_components.json"
    pair_arbitration_table_path = out_dir / "pair_arbitration_table.csv"
    corridor_conflict_roads_path = out_dir / "corridor_conflict_roads.geojson"
    target_conflict_audit_path = out_dir / "target_conflict_audit_xxxs7.json"
    working_graph_debug_path = out_dir / "working_graph_debug.geojson"
    segment_summary_path = out_dir / "segment_summary.json"
    endpoint_pool_csv_path, endpoint_pool_summary_path, endpoint_pool_nodes_path = write_endpoint_pool_outputs(
        out_dir=out_dir,
        source_map=endpoint_pool_source_map,
        stage_id=strategy.strategy_id,
        semantic_nodes=context.semantic_nodes,
        debug=debug,
    )

    write_csv(
        validated_pairs_path,
        _iter_validated_rows(validations),
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
        _iter_rejected_rows(validations),
        ["pair_id", "a_node_id", "b_node_id", "reject_reason", "warning_codes", "conflict_pair_id"],
    )
    write_csv(
        validated_pairs_final_path,
        _iter_validated_final_rows(validations),
        [
            "pair_id",
            "a_node_id",
            "b_node_id",
            "single_pair_legal",
            "arbitration_status",
            "validated_status",
            "lose_reason",
            "trunk_mode",
            "segment_body_road_count",
            "residual_road_count",
        ],
    )
    write_csv(
        pair_conflict_table_path,
        _iter_pair_conflict_rows(arbitration_outcome),
        ["pair_id", "conflict_pair_id", "conflict_type", "shared_road_count", "shared_trunk_road_count"],
    )
    write_json(
        pair_conflict_components_path,
        _pair_conflict_components_payload(arbitration_outcome),
    )
    write_csv(
        pair_arbitration_table_path,
        _iter_pair_arbitration_rows(validations, arbitration_outcome),
        [
            "pair_id",
            "component_id",
            "single_pair_legal",
            "arbitration_status",
            "endpoint_boundary_penalty",
            "strong_anchor_win_count",
            "corridor_naturalness_score",
            "contested_trunk_coverage_count",
            "contested_trunk_coverage_ratio",
            "internal_endpoint_penalty",
            "body_connectivity_support",
            "semantic_conflict_penalty",
            "lose_reason",
        ],
    )
    write_geojson(
        trunk_roads_path,
        _iter_trunk_features(context=context, validations=validations, strategy_id=strategy.strategy_id),
    )
    write_geojson(
        segment_body_roads_path,
        _iter_segment_body_features(context=context, validations=validations, strategy_id=strategy.strategy_id),
    )
    write_geojson(
        step3_residual_roads_path,
        _iter_step3_residual_features(context=context, validations=validations, strategy_id=strategy.strategy_id),
    )
    write_geojson(
        corridor_conflict_roads_path,
        _iter_corridor_conflict_features(
            context=context,
            arbitration_outcome=arbitration_outcome,
            strategy_id=strategy.strategy_id,
        ),
    )
    write_csv(
        validation_table_path,
        _iter_validation_rows(validations),
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
    write_json(
        target_conflict_audit_path,
        _build_target_conflict_audit_xxxs7(
            validations=validations,
            arbitration_outcome=arbitration_outcome,
            road_to_node_ids=road_to_node_ids,
        ),
    )

    segment_summary = {
        "strategy_id": strategy.strategy_id,
        "run_id": run_id,
        "strategy_out_dir": str(out_dir.resolve()),
        "formway_mode": formway_mode,
        **validation_summary,
        "conflict_component_count": len(arbitration_outcome.components),
        "arbitration_winner_count": sum(
            1 for item in arbitration_outcome.decisions if item.arbitration_status == "win"
        ),
        "arbitration_loser_count": sum(
            1 for item in arbitration_outcome.decisions if item.arbitration_status == "lose"
        ),
        "arbitration_fallback_component_count": sum(
            1 for item in arbitration_outcome.components if item.fallback_greedy_used
        ),
        "dual_carriageway_separation_gate_limit_m": MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
        "side_access_distance_gate_limit_m": MAX_SIDE_ACCESS_DISTANCE_M,
        "debug": debug,
        "output_files": [
            endpoint_pool_csv_path.name,
            endpoint_pool_summary_path.name,
            validated_pairs_path.name,
            rejected_pairs_path.name,
            validated_pairs_final_path.name,
            pair_conflict_table_path.name,
            pair_conflict_components_path.name,
            pair_arbitration_table_path.name,
            trunk_roads_path.name,
            segment_body_roads_path.name,
            step3_residual_roads_path.name,
            corridor_conflict_roads_path.name,
            validation_table_path.name,
            target_conflict_audit_path.name,
            segment_summary_path.name,
        ],
    }
    if debug:
        write_geojson(
            pair_links_validated_path,
            _iter_validated_link_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
            ),
        )
        write_geojson(
            segment_roads_path,
            _iter_segment_body_features(context=context, validations=validations, strategy_id=strategy.strategy_id),
        )
        write_geojson(
            trunk_road_members_path,
            _iter_member_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
                layer_role="trunk_member",
                road_ids_getter=lambda validation: validation.trunk_road_ids,
            ),
        )
        write_geojson(
            segment_body_road_members_path,
            _iter_member_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
                layer_role="segment_body_member",
                road_ids_getter=lambda validation: validation.segment_road_ids,
            ),
        )
        write_geojson(
            step3_residual_road_members_path,
            _iter_step3_residual_member_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
            ),
        )
        write_geojson(
            segment_road_members_path,
            _iter_member_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
                layer_role="segment_body_member",
                road_ids_getter=lambda validation: validation.segment_road_ids,
            ),
        )
        write_geojson(
            branch_cut_roads_path,
            _iter_branch_cut_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
            ),
        )
        _emit_progress(
            progress_callback,
            "candidate_channel_write_started",
            output_file=candidate_channel_path.name,
            validation_count=len(validations),
        )
        write_geojson(
            candidate_channel_path,
            _iter_candidate_channel_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
            ),
        )
        _emit_progress(
            progress_callback,
            "candidate_channel_write_completed",
            output_file=candidate_channel_path.name,
        )
        _emit_progress(
            progress_callback,
            "working_graph_debug_write_started",
            output_file=working_graph_debug_path.name,
            validation_count=len(validations),
        )
        write_geojson(
            working_graph_debug_path,
            _iter_working_graph_debug_features(
                context=context,
                validations=validations,
                strategy_id=strategy.strategy_id,
            ),
        )
        _emit_progress(
            progress_callback,
            "working_graph_debug_write_completed",
            output_file=working_graph_debug_path.name,
        )
        debug_output_files = [
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
        if endpoint_pool_nodes_path is not None:
            debug_output_files.append(endpoint_pool_nodes_path.name)
        segment_summary["output_files"].extend(debug_output_files)
    write_json(segment_summary_path, segment_summary)

    return Step2StrategyResult(
        strategy=strategy,
        segment_summary=segment_summary,
        output_files=[str(path) for path in sorted(out_dir.iterdir()) if path.is_file()],
        validations=validations if retain_validation_details else [],
    )


def _validate_pair_candidates_greedy(
    execution: Step1StrategyExecution,
    *,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    undirected_adjacency: dict[str, tuple[TraversalEdge, ...]],
    formway_mode: str,
    left_turn_formway_bit: int,
    compact_release_payloads: bool = False,
    progress_callback: Optional[Step2ProgressCallback] = None,
) -> list[PairValidationResult]:
    terminate_ids = set(execution.terminate_ids)
    hard_stop_node_ids = set(execution.strategy.hard_stop_node_ids)
    boundary_node_ids = terminate_ids | hard_stop_node_ids
    used_trunk_road_ids: dict[str, str] = {}
    provisional_results: list[PairValidationResult] = []
    validation_count = len(execution.pair_candidates)

    _emit_progress(progress_callback, "validation_started", validation_count=validation_count)

    def _emit_validation_pair_phase(
        *,
        pair_index: int,
        pair: PairRecord,
        phase: str,
        checkpoint: bool = False,
        **extra_payload: Any,
    ) -> None:
        payload = {
            "pair_index": pair_index,
            "validation_count": validation_count,
            "pair_id": pair.pair_id,
            "a_node_id": pair.a_node_id,
            "b_node_id": pair.b_node_id,
            "phase": phase,
            **extra_payload,
        }
        perf_trace_enabled = pair_index <= VALIDATION_PHASE_TRACE_PAIR_LIMIT
        _emit_progress(
            progress_callback,
            "validation_pair_state",
            **payload,
            _perf_log=perf_trace_enabled,
            _stdout_log=False,
        )
        if checkpoint:
            _emit_progress(progress_callback, "validation_pair_checkpoint", **payload)

    for pair_index, pair in enumerate(execution.pair_candidates, start=1):
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="validation_pair_started",
        )
        if (
            pair_index == 1
            or pair_index == validation_count
            or pair_index % VALIDATION_PROGRESS_CHECKPOINT_INTERVAL == 0
        ):
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="validation_pair_started",
                checkpoint=True,
            )

        candidate_road_ids, boundary_terminate_ids = _build_candidate_channel(
            pair,
            undirected_adjacency=undirected_adjacency,
            boundary_node_ids=boundary_node_ids,
        )
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="candidate_channel_built",
            candidate_road_count=len(candidate_road_ids),
        )

        if not candidate_road_ids:
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="result_appended",
                validated_status="rejected",
                reject_reason="invalid_candidate_boundary",
                trunk_found=False,
            )
            result = PairValidationResult(
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
            if compact_release_payloads:
                result = _compact_validation_result_for_release(result, keep_tighten_fields=False)
            provisional_results.append(result)
            continue

        pruned_road_ids, branch_cut_infos, disconnected_after_prune = _prune_candidate_channel(
            pair,
            candidate_road_ids=candidate_road_ids,
            road_endpoints=road_endpoints,
            terminate_ids=terminate_ids,
            hard_stop_node_ids=hard_stop_node_ids,
        )
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="prune_completed",
            candidate_road_count=len(candidate_road_ids),
            pruned_road_count=len(pruned_road_ids),
        )
        if disconnected_after_prune:
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="result_appended",
                validated_status="rejected",
                reject_reason="disconnected_after_prune",
                trunk_found=False,
            )
            result = PairValidationResult(
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
            if compact_release_payloads:
                result = _compact_validation_result_for_release(result, keep_tighten_fields=False)
            provisional_results.append(result)
            continue

        trunk_candidate, reject_reason, warning_codes, trunk_gate_info = _evaluate_trunk(
            pair,
            context=context,
            pruned_road_ids=pruned_road_ids,
            road_endpoints=road_endpoints,
            through_rule=execution.strategy.through_rule,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
        )
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="trunk_evaluated",
            validated_status="validated" if trunk_candidate is not None else "rejected",
            reject_reason="" if reject_reason is None else reject_reason,
            trunk_found=trunk_candidate is not None,
        )
        if trunk_candidate is None:
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="result_appended",
                validated_status="rejected",
                reject_reason="" if reject_reason is None else reject_reason,
                trunk_found=False,
            )
            result = PairValidationResult(
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
                        **trunk_gate_info,
                    },
                )
            if compact_release_payloads:
                result = _compact_validation_result_for_release(result, keep_tighten_fields=False)
            provisional_results.append(result)
            continue

        internal_boundary_node_ids = _collect_internal_boundary_nodes(
            pair,
            candidate=trunk_candidate,
            hard_stop_node_ids=hard_stop_node_ids,
        )
        if internal_boundary_node_ids:
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="result_appended",
                validated_status="rejected",
                reject_reason="historical_boundary_blocked",
                trunk_found=False,
            )
            result = PairValidationResult(
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
            if compact_release_payloads:
                result = _compact_validation_result_for_release(result, keep_tighten_fields=False)
            provisional_results.append(result)
            continue

        trunk_mode = _trunk_candidate_mode(trunk_candidate)
        if trunk_mode == "through_collapsed_corridor":
            segment_road_ids = trunk_candidate.road_ids
            segment_cut_infos: list[dict[str, Any]] = []
        else:
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="segment_body_started",
                trunk_found=True,
            )
            segment_body_allowed_road_ids = _expand_segment_body_allowed_road_ids(
                pruned_road_ids=pruned_road_ids,
                branch_cut_infos=branch_cut_infos,
                undirected_adjacency=undirected_adjacency,
                boundary_node_ids=boundary_node_ids,
                road_endpoints=road_endpoints,
            )
            segment_candidate_road_ids = _build_segment_body_candidate_channel(
                pair,
                trunk_road_ids=trunk_candidate.road_ids,
                undirected_adjacency=undirected_adjacency,
                boundary_node_ids=boundary_node_ids,
                road_endpoints=road_endpoints,
                allowed_road_ids=segment_body_allowed_road_ids,
            )
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="segment_body_candidate_channel_built",
                candidate_road_count=len(segment_candidate_road_ids),
                trunk_found=True,
            )
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="segment_body_refine_started",
                candidate_road_count=len(segment_candidate_road_ids),
                trunk_found=True,
            )
            segment_road_ids, segment_cut_infos = _refine_segment_roads(
                pair,
                context=context,
                road_endpoints=road_endpoints,
                pruned_road_ids=segment_candidate_road_ids,
                trunk_road_ids=trunk_candidate.road_ids,
                through_rule=execution.strategy.through_rule,
            )
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="segment_body_refine_completed",
                candidate_road_count=len(segment_candidate_road_ids),
                segment_road_count=len(segment_road_ids),
                trunk_found=True,
            )
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="segment_body_completed",
                segment_road_count=len(segment_road_ids),
                trunk_found=True,
            )

        conflict_pair_id = None
        for road_id in trunk_candidate.road_ids:
            if road_id in used_trunk_road_ids:
                conflict_pair_id = used_trunk_road_ids[road_id]
                break
        if conflict_pair_id is not None:
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="result_appended",
                validated_status="rejected",
                reject_reason="shared_trunk_conflict",
                trunk_found=True,
                segment_road_count=len(segment_road_ids),
            )
            result = PairValidationResult(
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
                        **trunk_gate_info,
                        "segment_body_candidate_road_ids": list(segment_road_ids),
                        "segment_body_candidate_cut_infos": segment_cut_infos,
                    },
                    conflict_pair_id=conflict_pair_id,
                )
            if compact_release_payloads:
                result = _compact_validation_result_for_release(result, keep_tighten_fields=False)
            provisional_results.append(result)
            continue

        for road_id in trunk_candidate.road_ids:
            used_trunk_road_ids[road_id] = pair.pair_id

        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="result_appended",
            validated_status="validated",
            reject_reason="",
            trunk_found=True,
            segment_road_count=len(segment_road_ids),
        )
        result = PairValidationResult(
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
                    **trunk_gate_info,
                    "segment_body_candidate_road_ids": list(segment_road_ids),
                    "segment_body_candidate_cut_infos": segment_cut_infos,
                    "left_turn_road_ids": list(trunk_candidate.left_turn_road_ids),
                },
            )
        if compact_release_payloads:
            result = _compact_validation_result_for_release(result, keep_tighten_fields=True)
        provisional_results.append(result)

    provisional_validated_pair_count = sum(
        1 for item in provisional_results if item.validated_status == "validated"
    )
    _emit_progress(
        progress_callback,
        "validation_tighten_started",
        validation_count=validation_count,
        validated_pair_count=provisional_validated_pair_count,
    )
    if provisional_validated_pair_count:
        validated_results = [
            item for item in provisional_results if item.validated_status == "validated"
        ]
        tightened_validated = _tighten_validated_segment_components(
            validated_results,
            execution=execution,
            context=context,
            road_endpoints=road_endpoints,
        )
        if compact_release_payloads:
            tightened_validated = [
                _compact_validation_result_for_release(item, keep_tighten_fields=False)
                for item in tightened_validated
            ]
        tightened_by_pair_id = {item.pair_id: item for item in tightened_validated}
    else:
        tightened_by_pair_id = {}

    tightened = [
        tightened_by_pair_id.get(item.pair_id, item)
        for item in provisional_results
    ]
    _emit_progress(
        progress_callback,
        "validation_tighten_completed",
        validation_count=len(tightened),
        validated_pair_count=sum(1 for item in tightened if item.validated_status == "validated"),
    )
    return tightened


def _validate_pair_candidates(
    execution: Step1StrategyExecution,
    *,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    undirected_adjacency: dict[str, tuple[TraversalEdge, ...]],
    formway_mode: str,
    left_turn_formway_bit: int,
    compact_release_payloads: bool = False,
    progress_callback: Optional[Step2ProgressCallback] = None,
    return_arbitration_outcome: bool = False,
) -> Union[list[PairValidationResult], tuple[list[PairValidationResult], PairArbitrationOutcome]]:
    terminate_ids = set(execution.terminate_ids)
    hard_stop_node_ids = set(execution.strategy.hard_stop_node_ids)
    boundary_node_ids = terminate_ids | hard_stop_node_ids
    validation_count = len(execution.pair_candidates)
    road_lengths = _road_length_index(context)
    road_to_node_ids = _road_node_index(road_endpoints)
    arbitration_boundary_node_ids = _arbitration_boundary_node_ids(
        execution,
        hard_stop_node_ids=hard_stop_node_ids,
    )
    weak_endpoint_node_ids = _arbitration_weak_endpoint_node_ids(context)
    semantic_conflict_node_ids = _arbitration_semantic_conflict_node_ids(context)
    strong_anchor_node_ids = _arbitration_strong_anchor_node_ids(context)
    tjunction_anchor_node_ids = _arbitration_tjunction_anchor_node_ids(context)

    _emit_progress(progress_callback, "validation_started", validation_count=validation_count)

    def _emit_validation_pair_phase(
        *,
        pair_index: int,
        pair: PairRecord,
        phase: str,
        checkpoint: bool = False,
        **extra_payload: Any,
    ) -> None:
        payload = {
            "pair_index": pair_index,
            "validation_count": validation_count,
            "pair_id": pair.pair_id,
            "a_node_id": pair.a_node_id,
            "b_node_id": pair.b_node_id,
            "phase": phase,
            **extra_payload,
        }
        perf_trace_enabled = pair_index <= VALIDATION_PHASE_TRACE_PAIR_LIMIT
        _emit_progress(
            progress_callback,
            "validation_pair_state",
            **payload,
            _perf_log=perf_trace_enabled,
            _stdout_log=False,
        )
        if checkpoint:
            _emit_progress(progress_callback, "validation_pair_checkpoint", **payload)

    illegal_validations_by_pair_id: dict[str, PairValidationResult] = {}
    options_by_pair_id: dict[str, list[PairArbitrationOption]] = {}

    for pair_index, pair in enumerate(execution.pair_candidates, start=1):
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="validation_pair_started",
        )
        if (
            pair_index == 1
            or pair_index == validation_count
            or pair_index % VALIDATION_PROGRESS_CHECKPOINT_INTERVAL == 0
        ):
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="validation_pair_started",
                checkpoint=True,
            )

        candidate_road_ids, boundary_terminate_ids = _build_candidate_channel(
            pair,
            undirected_adjacency=undirected_adjacency,
            boundary_node_ids=boundary_node_ids,
        )
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="candidate_channel_built",
            candidate_road_count=len(candidate_road_ids),
        )

        if not candidate_road_ids:
            illegal_validations_by_pair_id[pair.pair_id] = PairValidationResult(
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
            continue

        pruned_road_ids, branch_cut_infos, disconnected_after_prune = _prune_candidate_channel(
            pair,
            candidate_road_ids=candidate_road_ids,
            road_endpoints=road_endpoints,
            terminate_ids=terminate_ids,
            hard_stop_node_ids=hard_stop_node_ids,
        )
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="prune_completed",
            candidate_road_count=len(candidate_road_ids),
            pruned_road_count=len(pruned_road_ids),
        )
        if disconnected_after_prune:
            illegal_validations_by_pair_id[pair.pair_id] = PairValidationResult(
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
            continue

        trunk_choices, reject_reason, warning_codes, trunk_gate_info = _evaluate_trunk_choices(
            pair,
            context=context,
            pruned_road_ids=pruned_road_ids,
            road_endpoints=road_endpoints,
            through_rule=execution.strategy.through_rule,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
        )
        _emit_validation_pair_phase(
            pair_index=pair_index,
            pair=pair,
            phase="trunk_evaluated",
            validated_status="validated" if trunk_choices else "rejected",
            reject_reason="" if reject_reason is None else reject_reason,
            trunk_found=bool(trunk_choices),
        )
        if not trunk_choices:
            illegal_validations_by_pair_id[pair.pair_id] = PairValidationResult(
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
                    **trunk_gate_info,
                },
            )
            continue

        pair_options: list[PairArbitrationOption] = []
        pair_fallback_validation: Optional[PairValidationResult] = None

        for zero_based_option_index, choice in enumerate(trunk_choices):
            option_index = zero_based_option_index + 1
            trunk_candidate = choice.candidate
            option_id = f"{pair.pair_id}::opt_{option_index:02d}"
            alternative_trunk_only_road_ids = _alternative_trunk_only_road_ids(
                trunk_choices,
                current_choice_index=zero_based_option_index,
            )
            internal_boundary_node_ids = _collect_internal_boundary_nodes(
                pair,
                candidate=trunk_candidate,
                hard_stop_node_ids=hard_stop_node_ids,
            )
            if internal_boundary_node_ids:
                pair_fallback_validation = PairValidationResult(
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
                    warning_codes=choice.warning_codes,
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
                continue

            trunk_mode = _trunk_candidate_mode(trunk_candidate)
            if trunk_mode == "through_collapsed_corridor":
                segment_candidate_road_ids = trunk_candidate.road_ids
                segment_road_ids = trunk_candidate.road_ids
                segment_cut_infos: list[dict[str, Any]] = []
            else:
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_started",
                    trunk_found=True,
                    option_id=option_id,
                )
                segment_body_allowed_road_ids = _expand_segment_body_allowed_road_ids(
                    pruned_road_ids=pruned_road_ids,
                    branch_cut_infos=branch_cut_infos,
                    undirected_adjacency=undirected_adjacency,
                    boundary_node_ids=boundary_node_ids,
                    road_endpoints=road_endpoints,
                )
                if alternative_trunk_only_road_ids:
                    segment_body_allowed_road_ids -= alternative_trunk_only_road_ids
                segment_candidate_road_ids = _build_segment_body_candidate_channel(
                    pair,
                    trunk_road_ids=trunk_candidate.road_ids,
                    undirected_adjacency=undirected_adjacency,
                    boundary_node_ids=boundary_node_ids,
                    road_endpoints=road_endpoints,
                    allowed_road_ids=segment_body_allowed_road_ids,
                )
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_candidate_channel_built",
                    candidate_road_count=len(segment_candidate_road_ids),
                    trunk_found=True,
                    option_id=option_id,
                )
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_refine_started",
                    candidate_road_count=len(segment_candidate_road_ids),
                    trunk_found=True,
                    option_id=option_id,
                )
                segment_road_ids, segment_cut_infos = _refine_segment_roads(
                    pair,
                    context=context,
                    road_endpoints=road_endpoints,
                    pruned_road_ids=segment_candidate_road_ids,
                    trunk_road_ids=trunk_candidate.road_ids,
                    through_rule=execution.strategy.through_rule,
                )
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_refine_completed",
                    candidate_road_count=len(segment_candidate_road_ids),
                    segment_road_count=len(segment_road_ids),
                    trunk_found=True,
                    option_id=option_id,
                )
                _emit_validation_pair_phase(
                    pair_index=pair_index,
                    pair=pair,
                    phase="segment_body_completed",
                    segment_road_count=len(segment_road_ids),
                    trunk_found=True,
                    option_id=option_id,
                )

            support_info = {
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
                **choice.support_info,
                **trunk_gate_info,
                "alternative_trunk_only_road_ids": sorted(alternative_trunk_only_road_ids, key=_sort_key),
                "segment_body_candidate_road_ids": list(segment_candidate_road_ids),
                "segment_body_candidate_cut_infos": segment_cut_infos,
                "left_turn_road_ids": list(trunk_candidate.left_turn_road_ids),
            }
            pair_options.append(
                PairArbitrationOption(
                    option_id=option_id,
                    pair_id=pair.pair_id,
                    a_node_id=pair.a_node_id,
                    b_node_id=pair.b_node_id,
                    trunk_mode=trunk_mode,
                    counterclockwise_ok=_trunk_candidate_counterclockwise_ok(trunk_candidate),
                    warning_codes=choice.warning_codes,
                    candidate_channel_road_ids=tuple(sorted(candidate_road_ids, key=_sort_key)),
                    pruned_road_ids=tuple(sorted(pruned_road_ids, key=_sort_key)),
                    trunk_road_ids=trunk_candidate.road_ids,
                    segment_candidate_road_ids=tuple(sorted(segment_candidate_road_ids, key=_sort_key)),
                    segment_road_ids=tuple(sorted(segment_road_ids, key=_sort_key)),
                    branch_cut_road_ids=tuple(sorted((info["road_id"] for info in branch_cut_infos), key=_sort_key)),
                    boundary_terminate_node_ids=tuple(sorted(boundary_terminate_ids, key=_sort_key)),
                    transition_same_dir_blocked=False,
                    support_info=support_info,
                )
            )

        if pair_options:
            options_by_pair_id[pair.pair_id] = pair_options
            continue

        if pair_fallback_validation is None:
            pair_fallback_validation = PairValidationResult(
                pair_id=pair.pair_id,
                a_node_id=pair.a_node_id,
                b_node_id=pair.b_node_id,
                candidate_status="candidate",
                validated_status="rejected",
                reject_reason="no_valid_segment_body_option",
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
        illegal_validations_by_pair_id[pair.pair_id] = pair_fallback_validation

    _emit_progress(
        progress_callback,
        "same_stage_arbitration_started",
        legal_pair_count=len(options_by_pair_id),
        illegal_pair_count=len(illegal_validations_by_pair_id),
    )
    arbitration_outcome = arbitrate_pair_options(
        options_by_pair=options_by_pair_id,
        single_pair_illegal_pair_ids=set(illegal_validations_by_pair_id),
        road_lengths=road_lengths,
        road_to_node_ids=road_to_node_ids,
        weak_endpoint_node_ids=weak_endpoint_node_ids,
        boundary_node_ids=arbitration_boundary_node_ids,
        semantic_conflict_node_ids=semantic_conflict_node_ids,
        strong_anchor_node_ids=strong_anchor_node_ids,
        tjunction_anchor_node_ids=tjunction_anchor_node_ids,
    )
    _emit_progress(
        progress_callback,
        "same_stage_arbitration_completed",
        component_count=len(arbitration_outcome.components),
        winner_count=len(arbitration_outcome.selected_options_by_pair_id),
        loser_count=sum(1 for item in arbitration_outcome.decisions if item.arbitration_status == "lose"),
    )

    decision_by_pair_id = {decision.pair_id: decision for decision in arbitration_outcome.decisions}
    option_by_id = {
        option.option_id: option
        for options in options_by_pair_id.values()
        for option in options
    }
    winning_pair_ids = {
        decision.pair_id
        for decision in arbitration_outcome.decisions
        if decision.arbitration_status == "win"
    }
    conflict_pair_ids_by_loser: dict[str, str] = {}
    for record in arbitration_outcome.conflict_records:
        left_wins = record.pair_id in winning_pair_ids
        right_wins = record.conflict_pair_id in winning_pair_ids
        if left_wins and not right_wins:
            conflict_pair_ids_by_loser.setdefault(record.conflict_pair_id, record.pair_id)
        elif right_wins and not left_wins:
            conflict_pair_ids_by_loser.setdefault(record.pair_id, record.conflict_pair_id)

    provisional_results_by_pair_id: dict[str, PairValidationResult] = {}
    for pair_index, pair in enumerate(execution.pair_candidates, start=1):
        decision = decision_by_pair_id[pair.pair_id]
        if pair.pair_id in options_by_pair_id:
            selected_option = option_by_id[decision.selected_option_id or options_by_pair_id[pair.pair_id][0].option_id]
            result = _pair_validation_from_option(
                selected_option,
                decision=decision,
                conflict_pair_id=conflict_pair_ids_by_loser.get(pair.pair_id),
                left_turn_excluded_mode=formway_mode,
                compact_release_payloads=compact_release_payloads,
            )
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="result_appended",
                validated_status=result.validated_status,
                reject_reason="" if result.reject_reason is None else result.reject_reason,
                trunk_found=result.trunk_found,
                segment_road_count=_validation_road_count(
                    result.segment_road_ids,
                    result.support_info,
                    "segment_body_road_count",
                ),
            )
            provisional_results_by_pair_id[pair.pair_id] = result
        else:
            result = _single_pair_illegal_validation(
                illegal_validations_by_pair_id[pair.pair_id],
                decision=decision,
                compact_release_payloads=compact_release_payloads,
            )
            _emit_validation_pair_phase(
                pair_index=pair_index,
                pair=pair,
                phase="result_appended",
                validated_status=result.validated_status,
                reject_reason="" if result.reject_reason is None else result.reject_reason,
                trunk_found=result.trunk_found,
            )
            provisional_results_by_pair_id[pair.pair_id] = result

    provisional_results = [provisional_results_by_pair_id[pair.pair_id] for pair in execution.pair_candidates]
    provisional_validated_pair_count = sum(
        1 for item in provisional_results if item.validated_status == "validated"
    )
    _emit_progress(
        progress_callback,
        "validation_tighten_started",
        validation_count=validation_count,
        validated_pair_count=provisional_validated_pair_count,
    )
    if provisional_validated_pair_count:
        validated_results = [item for item in provisional_results if item.validated_status == "validated"]
        tightened_validated = _tighten_validated_segment_components(
            validated_results,
            execution=execution,
            context=context,
            road_endpoints=road_endpoints,
        )
        if compact_release_payloads:
            tightened_validated = [
                _compact_validation_result_for_release(item, keep_tighten_fields=False)
                for item in tightened_validated
            ]
        tightened_by_pair_id = {item.pair_id: item for item in tightened_validated}
    else:
        tightened_by_pair_id = {}

    tightened = [tightened_by_pair_id.get(item.pair_id, item) for item in provisional_results]
    _emit_progress(
        progress_callback,
        "validation_tighten_completed",
        validation_count=len(tightened),
        validated_pair_count=sum(1 for item in tightened if item.validated_status == "validated"),
    )
    if return_arbitration_outcome:
        return tightened, arbitration_outcome
    return tightened


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
    retain_validation_details: bool = True,
    progress_callback: Optional[Step2ProgressCallback] = None,
    assume_working_layers: bool = False,
) -> list[Step2StrategyResult]:
    if formway_mode not in {"strict", "audit_only", "off"}:
        raise ValueError("formway_mode must be one of: strict, audit_only, off.")

    resolved_out_root = Path(out_root)
    resolved_out_root.mkdir(parents=True, exist_ok=True)
    working_road_path = road_path
    working_node_path = node_path
    if not assume_working_layers:
        bootstrap_artifacts = initialize_working_layers(
            road_path=road_path,
            node_path=node_path,
            out_root=resolved_out_root / "_bootstrap",
            road_layer=road_layer,
            road_crs=road_crs,
            node_layer=node_layer,
            node_crs=node_crs,
            debug=debug,
            progress_callback=lambda event, payload: _emit_progress(progress_callback, event, **payload),
        )
        working_road_path = bootstrap_artifacts.roads_path
        working_node_path = bootstrap_artifacts.nodes_path
    _emit_progress(progress_callback, "context_build_started")
    context = build_step1_graph_context(
        road_path=working_road_path,
        node_path=working_node_path,
    )
    _emit_progress(
        progress_callback,
        "context_build_completed",
        road_count=len(context.roads),
        physical_node_count=len(context.physical_nodes),
        semantic_node_count=len(context.semantic_nodes),
        orphan_ref_count=context.orphan_ref_count,
    )
    road_endpoints, undirected_adjacency = _build_semantic_endpoints(context)
    _emit_progress(
        progress_callback,
        "semantic_endpoints_completed",
        semantic_endpoint_road_count=len(road_endpoints),
        undirected_node_count=len(undirected_adjacency),
    )

    results: list[Step2StrategyResult] = []
    comparison_summary: list[dict[str, Any]] = []
    resolved_run_id = resolved_out_root.name if run_id is None else run_id
    strategy_count = len(strategy_config_paths)

    for strategy_index, strategy_path in enumerate(strategy_config_paths, start=1):
        _emit_progress(
            progress_callback,
            "strategy_started",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_path=str(strategy_path),
        )
        strategy = _load_strategy(strategy_path)
        _emit_progress(
            progress_callback,
            "strategy_loaded",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_id=strategy.strategy_id,
        )
        execution = run_step1_strategy(context, strategy)
        _emit_progress(
            progress_callback,
            "candidate_search_completed",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_id=strategy.strategy_id,
            candidate_pair_count=len(execution.pair_candidates),
            search_seed_count=len(execution.search_seed_ids),
            terminate_count=len(execution.terminate_ids),
        )
        strategy_out_dir = resolved_out_root / strategy.strategy_id

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
        _emit_progress(
            progress_callback,
            "candidate_outputs_written",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_id=strategy.strategy_id,
            output_dir=str(strategy_out_dir.resolve()),
        )

        execution = _compact_execution_for_validation(execution)
        gc.collect()
        compact_release_payloads = not debug and not retain_validation_details
        validation_result = _validate_pair_candidates(
            execution,
            context=context,
            road_endpoints=road_endpoints,
            undirected_adjacency=undirected_adjacency,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
            compact_release_payloads=compact_release_payloads,
            progress_callback=progress_callback,
            return_arbitration_outcome=True,
        )
        if isinstance(validation_result, tuple):
            validations, arbitration_outcome = validation_result
        else:
            validations = validation_result
            arbitration_outcome = _empty_pair_arbitration_outcome()
        endpoint_pool_source_map = build_endpoint_pool_source_map(
            node_ids=set(execution.seed_ids) | set(execution.terminate_ids),
            stage_id=strategy.strategy_id,
        )
        validated_pair_count = sum(1 for item in validations if item.validated_status == "validated")
        rejected_pair_count = len(validations) - validated_pair_count
        _emit_progress(
            progress_callback,
            "validation_completed",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_id=strategy.strategy_id,
            candidate_pair_count=len(validations),
            validated_pair_count=validated_pair_count,
            rejected_pair_count=rejected_pair_count,
        )
        write_outputs_kwargs = {
            "strategy": strategy,
            "run_id": resolved_run_id,
            "context": context,
            "validations": validations,
            "endpoint_pool_source_map": endpoint_pool_source_map,
            "formway_mode": formway_mode,
            "debug": debug,
            "retain_validation_details": retain_validation_details,
            "progress_callback": progress_callback,
        }
        if "road_to_node_ids" in inspect.signature(_write_step2_outputs).parameters:
            write_outputs_kwargs["road_to_node_ids"] = road_endpoints
        if "arbitration_outcome" in inspect.signature(_write_step2_outputs).parameters:
            write_outputs_kwargs["arbitration_outcome"] = arbitration_outcome
        step2_result = _write_step2_outputs(
            strategy_out_dir,
            **write_outputs_kwargs,
        )
        _emit_progress(
            progress_callback,
            "step2_outputs_written",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_id=strategy.strategy_id,
            output_dir=str(strategy_out_dir.resolve()),
            segment_summary=step2_result.segment_summary,
            retained_validation_details=retain_validation_details,
        )
        results.append(step2_result)
        comparison_summary.append(step2_result.segment_summary)
        del execution
        del validations
        del arbitration_outcome
        gc_collected = gc.collect()
        _emit_progress(
            progress_callback,
            "strategy_memory_released",
            strategy_index=strategy_index,
            strategy_count=strategy_count,
            strategy_id=strategy.strategy_id,
            gc_collected_objects=gc_collected,
            retained_validation_details=retain_validation_details,
        )

    write_json(resolved_out_root / "strategy_comparison.json", comparison_summary)
    _emit_progress(
        progress_callback,
        "comparison_summary_written",
        strategy_count=strategy_count,
        strategy_comparison_path=str((resolved_out_root / "strategy_comparison.json").resolve()),
    )
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
        debug=args.debug,
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
