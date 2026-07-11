from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from typing import Any, Optional

from rcsd_topo_poc.modules.t01_data_preprocess.road_kind_continuity import (
    choose_preferred_continuation_edges,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_candidate_gates import (
    counterclockwise_mixed_kind_wedge_gate_info,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_geometry_utils import (
    geometry_coords as _geometry_coords,
    geometry_length as _geometry_length,
    line_geometry_from_coords as _line_geometry_from_coords,
    line_geometry_from_road_ids as _line_geometry_from_road_ids,
    max_nearest_distance_m as _max_nearest_distance_m,
    max_sampled_distance_m as _raw_max_sampled_distance_m,
    trimmed_line_body_geometry as _trimmed_line_body_geometry,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_internal_turn_gate import (
    internal_turn_angle_gate_info,
    split_internal_turn_angle_candidates,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    PairRecord,
    RoadRecord,
    SemanticNodeRecord,
    Step1GraphContext,
    ThroughRuleSpec,
    TraversalEdge,
    _bit_enabled,
    _sort_key,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_dual_separation_gate import (
    _dual_separation_gate_limit_m,
    _dual_separation_support_info,
    _semantic_group_node_id,
    _split_pair_support_near_gate_candidates,
)
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
    MAX_SIDE_ACCESS_DISTANCE_M,
)

LEFT_TURN_FORMWAY_BIT = 8
MAX_PATHS_PER_DIRECTION = 12
MAX_PATH_DEPTH = 64
SIDE_ACCESS_SAMPLE_STEP_M = MAX_SIDE_ACCESS_DISTANCE_M / 2.0
STEP5C_STRATEGY_ID = "STEP5C"
MAX_DIRECT_ONEWAY_TAIL_RELAXATION_M = 5.0
KIND2_128_LOCALIZED_SEARCH_MIN_NODE_COUNT = 24
KIND2_128_LOCALIZED_SEARCH_MIN_PRUNED_ROAD_COUNT = 192
KIND2_128_LOCALIZED_SEARCH_MAX_EXPANDED_STATES = 500
KIND2_128_LOCALIZED_SEARCH_MAX_FRONTIER_SIZE = 500
KIND2_128_LOCAL_CORRIDOR_TERMINAL_MIN_NODE_COUNT = 12
KIND2_128_LOCAL_CORRIDOR_TERMINAL_MIN_ROAD_COUNT = 48


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
    is_mirrored_one_sided_corridor: bool = False
    is_kind2_128_local_corridor: bool = False
    is_bidirectional_minimal_loop: bool = False
    is_semantic_node_group_closure: bool = False


@dataclass(frozen=True)
class _TrunkEvaluationChoice:
    candidate: TrunkCandidate
    warning_codes: tuple[str, ...]
    support_info: dict[str, Any]


@dataclass
class _PathSearchBudget:
    phase: str
    max_expanded_states: int
    max_frontier_size: int
    expanded_states: int = 0
    max_observed_frontier_size: int = 0
    exhausted: bool = False
    exhausted_reason: str = ""


def _max_sampled_distance_m(source_geometry: Any, target_geometry: Any) -> Optional[float]:
    return _raw_max_sampled_distance_m(
        source_geometry,
        target_geometry,
        sample_step_m=SIDE_ACCESS_SAMPLE_STEP_M,
    )


def _single_road_direct_oneway_pair_sampled_separation_m(
    *,
    forward_path: DirectedPath,
    reverse_path: DirectedPath,
    roads: dict[str, RoadRecord],
) -> Optional[float]:
    if len(forward_path.road_ids) != 1 or len(reverse_path.road_ids) != 1:
        return None
    if len(forward_path.node_ids) != 2 or len(reverse_path.node_ids) != 2:
        return None
    if forward_path.node_ids != tuple(reversed(reverse_path.node_ids)):
        return None

    forward_road_id = forward_path.road_ids[0]
    reverse_road_id = reverse_path.road_ids[0]
    if forward_road_id == reverse_road_id:
        return None

    forward_road = roads.get(forward_road_id)
    reverse_road = roads.get(reverse_road_id)
    if forward_road is None or reverse_road is None:
        return None
    if forward_road.direction in {0, 1} or reverse_road.direction in {0, 1}:
        return None

    forward_geometry = _line_geometry_from_road_ids((forward_road_id,), roads=roads)
    reverse_geometry = _line_geometry_from_road_ids((reverse_road_id,), roads=roads)
    if forward_geometry is None or reverse_geometry is None:
        return None

    forward_length = _geometry_length(forward_geometry)
    reverse_length = _geometry_length(reverse_geometry)
    if forward_length <= 0.0 or reverse_length <= 0.0:
        return None

    shorter_geometry, longer_geometry = (
        (forward_geometry, reverse_geometry)
        if forward_length <= reverse_length
        else (reverse_geometry, forward_geometry)
    )
    return _max_sampled_distance_m(shorter_geometry, longer_geometry)


def _dual_carriageway_separation_m(
    *,
    forward_path: DirectedPath,
    reverse_path: DirectedPath,
    roads: dict[str, RoadRecord],
) -> float:
    forward_geometry = _line_geometry_from_road_ids(forward_path.road_ids, roads=roads)
    reverse_geometry = _line_geometry_from_road_ids(reverse_path.road_ids, roads=roads)
    raw_distance_m = _max_nearest_distance_m(forward_geometry, reverse_geometry) or 0.0
    body_distance_m = _max_nearest_distance_m(
        _trimmed_line_body_geometry(forward_geometry, trim_m=MAX_DIRECT_ONEWAY_TAIL_RELAXATION_M),
        _trimmed_line_body_geometry(reverse_geometry, trim_m=MAX_DIRECT_ONEWAY_TAIL_RELAXATION_M),
    )
    distance_m = min(raw_distance_m, body_distance_m) if body_distance_m is not None else raw_distance_m

    special_case_distance_m = _single_road_direct_oneway_pair_sampled_separation_m(
        forward_path=forward_path,
        reverse_path=reverse_path,
        roads=roads,
    )
    if (
        special_case_distance_m is not None
        and raw_distance_m - special_case_distance_m <= MAX_DIRECT_ONEWAY_TAIL_RELAXATION_M
    ):
        return min(distance_m, special_case_distance_m)

    return distance_m


def _road_matches_formway_bit(road: RoadRecord, bit_index: int) -> bool:
    if road.formway is None:
        return False
    return _bit_enabled(road.formway, bit_index)


def _road_matches_any_formway_bits(road: RoadRecord, bits: tuple[int, ...]) -> bool:
    if not bits or road.formway is None:
        return False
    return any(_bit_enabled(road.formway, bit_index) for bit_index in bits)


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
    physical_to_semantic: Optional[dict[str, str]] = None,
    max_paths: int = MAX_PATHS_PER_DIRECTION,
    max_depth: int = MAX_PATH_DEPTH,
    budget: Optional[_PathSearchBudget] = None,
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
    if budget is not None:
        budget.max_observed_frontier_size = max(budget.max_observed_frontier_size, len(heap))

    while heap and len(results) < max_paths:
        if budget is not None and budget.expanded_states >= budget.max_expanded_states:
            budget.exhausted = True
            budget.exhausted_reason = "expanded_states"
            break
        total_length, depth, _index, current_node_id, node_ids, road_ids, visited_nodes = heappop(heap)
        if budget is not None:
            budget.expanded_states += 1
        if current_node_id == end_node_id and road_ids:
            results.append(DirectedPath(node_ids=node_ids, road_ids=road_ids, total_length=total_length))
            continue
        if depth >= max_depth:
            continue

        outgoing_edges = tuple(edge for edge in adjacency.get(current_node_id, ()) if edge.to_node not in visited_nodes)
        if road_ids and physical_to_semantic is not None and len(node_ids) >= 2:
            outgoing_edges = choose_preferred_continuation_edges(
                current_node_id=current_node_id,
                incoming_from_node_id=node_ids[-2],
                incoming_road_id=road_ids[-1],
                outgoing_edges=outgoing_edges,
                roads=roads,
                physical_to_semantic=physical_to_semantic,
            ).edges

        for edge in outgoing_edges:
            if budget is not None and len(heap) >= budget.max_frontier_size:
                budget.exhausted = True
                budget.exhausted_reason = "frontier_size"
                break
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
            if budget is not None:
                budget.max_observed_frontier_size = max(
                    budget.max_observed_frontier_size,
                    len(heap),
                )
        if budget is not None and budget.exhausted:
            break

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


def _collect_road_ids_on_any_simple_path(
    *,
    start_node_id: str,
    end_node_id: str,
    road_endpoints: dict[str, tuple[str, str]],
    allowed_road_ids: set[str],
) -> set[str]:
    if start_node_id == end_node_id or not allowed_road_ids:
        return set()

    adjacency = _build_filtered_undirected_adjacency(
        road_endpoints=road_endpoints,
        allowed_road_ids=allowed_road_ids,
    )
    if start_node_id not in adjacency or end_node_id not in adjacency:
        return set()

    timer = count()
    disc: dict[str, int] = {}
    low: dict[str, int] = {}
    edge_stack: list[tuple[str, str, str]] = []
    component_road_ids: list[set[str]] = []
    node_to_component_ids: dict[str, set[int]] = defaultdict(set)

    def _flush_component(stop_road_id: Optional[str]) -> None:
        component_nodes: set[str] = set()
        component_roads: set[str] = set()
        while edge_stack:
            from_node_id, to_node_id, road_id = edge_stack.pop()
            component_nodes.add(from_node_id)
            component_nodes.add(to_node_id)
            component_roads.add(road_id)
            if stop_road_id is not None and road_id == stop_road_id:
                break

        if not component_roads:
            return

        component_id = len(component_road_ids)
        component_road_ids.append(component_roads)
        for node_id in component_nodes:
            node_to_component_ids[node_id].add(component_id)

    def _dfs(node_id: str, parent_road_id: Optional[str]) -> None:
        disc[node_id] = next(timer)
        low[node_id] = disc[node_id]

        for edge in adjacency.get(node_id, ()):
            next_node_id = edge.to_node
            road_id = edge.road_id
            if road_id == parent_road_id:
                continue

            if next_node_id not in disc:
                edge_stack.append((node_id, next_node_id, road_id))
                _dfs(next_node_id, road_id)
                low[node_id] = min(low[node_id], low[next_node_id])
                if low[next_node_id] >= disc[node_id]:
                    _flush_component(road_id)
                continue

            if disc[next_node_id] < disc[node_id]:
                edge_stack.append((node_id, next_node_id, road_id))
                low[node_id] = min(low[node_id], disc[next_node_id])

    for node_id in sorted(adjacency.keys(), key=_sort_key):
        if node_id in disc:
            continue
        _dfs(node_id, None)
        if edge_stack:
            _flush_component(None)

    start_token = f"node:{start_node_id}"
    end_token = f"node:{end_node_id}"
    if start_node_id not in node_to_component_ids or end_node_id not in node_to_component_ids:
        return set()

    block_cut_adjacency: dict[str, set[str]] = defaultdict(set)
    for node_id, component_ids in node_to_component_ids.items():
        node_token = f"node:{node_id}"
        for component_id in component_ids:
            component_token = f"component:{component_id}"
            block_cut_adjacency[node_token].add(component_token)
            block_cut_adjacency[component_token].add(node_token)

    queue: deque[str] = deque([start_token])
    parents: dict[str, Optional[str]] = {start_token: None}
    while queue:
        token = queue.popleft()
        if token == end_token:
            break
        for next_token in sorted(block_cut_adjacency.get(token, ()), key=_sort_key):
            if next_token in parents:
                continue
            parents[next_token] = token
            queue.append(next_token)

    if end_token not in parents:
        return set()

    selected_component_ids: set[int] = set()
    current_token: Optional[str] = end_token
    while current_token is not None:
        if current_token.startswith("component:"):
            selected_component_ids.add(int(current_token.split(":", 1)[1]))
        current_token = parents[current_token]

    selected_road_ids: set[str] = set()
    for component_id in selected_component_ids:
        selected_road_ids.update(component_road_ids[component_id])
    return selected_road_ids


def _collect_segment_path_road_ids(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    allowed_road_ids: set[str],
) -> set[str]:
    _ = context
    return _collect_road_ids_on_any_simple_path(
        start_node_id=pair.a_node_id,
        end_node_id=pair.b_node_id,
        road_endpoints=road_endpoints,
        allowed_road_ids=allowed_road_ids,
    )


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
    context: Optional[Step1GraphContext] = None,
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
        if context is not None:
            from_node_id = _semantic_group_node_id(from_node_id, context)
            to_node_id = _semantic_group_node_id(to_node_id, context)
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


def _collapsed_candidate_undirected_adjacency(
    candidate: TrunkCandidate,
) -> dict[str, set[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    for path in (candidate.forward_path, candidate.reverse_path):
        if len(path.node_ids) != len(path.road_ids) + 1:
            continue
        for from_node_id, to_node_id in zip(path.node_ids, path.node_ids[1:]):
            if from_node_id == to_node_id:
                continue
            adjacency[from_node_id].add(to_node_id)
            adjacency[to_node_id].add(from_node_id)
    return {node_id: set(neighbors) for node_id, neighbors in adjacency.items()}


def _minimal_trunk_chain_gate_info(
    pair: PairRecord,
    *,
    candidate: TrunkCandidate,
) -> Optional[dict[str, Any]]:
    if candidate.is_bidirectional_minimal_loop:
        return None

    adjacency = _collapsed_candidate_undirected_adjacency(candidate)
    if not adjacency:
        return None

    active_node_ids = set(adjacency)
    queue: deque[str] = deque([next(iter(active_node_ids))])
    visited: set[str] = set()
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        queue.extend(neighbor for neighbor in adjacency.get(node_id, ()) if neighbor not in visited)

    endpoint_node_ids = sorted((node_id for node_id, neighbors in adjacency.items() if len(neighbors) == 1), key=_sort_key)
    branching_node_ids = sorted((node_id for node_id, neighbors in adjacency.items() if len(neighbors) > 2), key=_sort_key)

    topology_kind = "other"
    if visited != active_node_ids:
        topology_kind = "disconnected"
    elif branching_node_ids:
        topology_kind = "branching"
    elif len(endpoint_node_ids) == 0:
        topology_kind = "cycle"
    elif len(endpoint_node_ids) == 2:
        topology_kind = "path"

    if topology_kind == "cycle":
        return None
    if topology_kind == "path" and set(endpoint_node_ids) == {pair.a_node_id, pair.b_node_id}:
        return None

    return {
        **_dual_separation_support_info(candidate),
        "minimal_trunk_chain_blocked": True,
        "minimal_trunk_chain_topology_kind": topology_kind,
        "minimal_trunk_chain_endpoint_node_ids": endpoint_node_ids,
        "minimal_trunk_chain_branching_node_ids": branching_node_ids,
        "minimal_trunk_chain_active_node_ids": sorted(active_node_ids, key=_sort_key),
        "minimal_trunk_chain_node_degrees": {
            node_id: len(adjacency[node_id]) for node_id in sorted(adjacency, key=_sort_key)
        },
    }


def _bidirectional_minimal_loop_extra_branch_gate_info(
    pair: PairRecord,
    *,
    candidate: TrunkCandidate,
    candidate_road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
) -> Optional[dict[str, Any]]:
    if not candidate.is_bidirectional_minimal_loop:
        return None

    internal_node_ids = (
        set(candidate.forward_path.node_ids[1:-1]) | set(candidate.reverse_path.node_ids[1:-1])
    ) - {pair.a_node_id, pair.b_node_id}
    if not internal_node_ids:
        return None

    candidate_road_id_set = set(candidate.road_ids)
    extra_branch_road_infos: list[dict[str, Any]] = []
    for road_id in sorted(candidate_road_ids - candidate_road_id_set, key=_sort_key):
        endpoints = road_endpoints.get(road_id)
        if endpoints is None:
            continue
        touched_internal_node_ids = sorted(set(endpoints) & internal_node_ids, key=_sort_key)
        if not touched_internal_node_ids:
            continue
        extra_branch_road_infos.append(
            {
                "road_id": road_id,
                "from_node_id": endpoints[0],
                "to_node_id": endpoints[1],
                "touched_internal_node_ids": touched_internal_node_ids,
            }
        )

    if not extra_branch_road_infos:
        return None

    return {
        **_dual_separation_support_info(candidate),
        "bidirectional_minimal_loop_extra_branch_blocked": True,
        "bidirectional_minimal_loop_internal_node_ids": sorted(internal_node_ids, key=_sort_key),
        "bidirectional_minimal_loop_extra_branch_infos": extra_branch_road_infos,
    }


def _bidirectional_minimal_loop_lasso_gate_info(
    pair: PairRecord,
    *,
    candidate: TrunkCandidate,
) -> Optional[dict[str, Any]]:
    if not candidate.is_bidirectional_minimal_loop:
        return None

    adjacency = _collapsed_candidate_undirected_adjacency(candidate)
    if not adjacency:
        return None

    active_node_ids = set(adjacency)
    queue: deque[str] = deque([next(iter(active_node_ids))])
    visited: set[str] = set()
    while queue:
        node_id = queue.popleft()
        if node_id in visited:
            continue
        visited.add(node_id)
        queue.extend(neighbor for neighbor in adjacency.get(node_id, ()) if neighbor not in visited)
    if visited != active_node_ids:
        return None

    degree_by_node = {node_id: len(neighbors) for node_id, neighbors in adjacency.items()}
    if any(degree not in {1, 2, 3} for degree in degree_by_node.values()):
        return None

    leaf_node_ids = sorted((node_id for node_id, degree in degree_by_node.items() if degree == 1), key=_sort_key)
    branching_node_ids = sorted((node_id for node_id, degree in degree_by_node.items() if degree == 3), key=_sort_key)
    if len(leaf_node_ids) != 1 or len(branching_node_ids) != 1:
        return None

    leaf_node_id = leaf_node_ids[0]
    if leaf_node_id not in {pair.a_node_id, pair.b_node_id}:
        return None
    other_endpoint_node_id = pair.b_node_id if leaf_node_id == pair.a_node_id else pair.a_node_id
    if degree_by_node.get(other_endpoint_node_id) != 2:
        return None

    remaining_node_ids = active_node_ids - {leaf_node_id}
    if len(remaining_node_ids) < 3:
        return None

    remaining_adjacency = {
        node_id: {neighbor for neighbor in neighbors if neighbor != leaf_node_id}
        for node_id, neighbors in adjacency.items()
        if node_id != leaf_node_id
    }
    if any(len(remaining_adjacency[node_id]) != 2 for node_id in remaining_node_ids):
        return None

    remaining_queue: deque[str] = deque([next(iter(remaining_node_ids))])
    remaining_visited: set[str] = set()
    while remaining_queue:
        node_id = remaining_queue.popleft()
        if node_id in remaining_visited:
            continue
        remaining_visited.add(node_id)
        remaining_queue.extend(
            neighbor for neighbor in remaining_adjacency.get(node_id, ()) if neighbor not in remaining_visited
        )
    if remaining_visited != remaining_node_ids:
        return None

    return {
        **_dual_separation_support_info(candidate),
        "bidirectional_minimal_loop_lasso_blocked": True,
        "bidirectional_minimal_loop_lasso_leaf_node_id": leaf_node_id,
        "bidirectional_minimal_loop_lasso_branching_node_ids": branching_node_ids,
        "bidirectional_minimal_loop_lasso_node_degrees": {
            node_id: degree_by_node[node_id] for node_id in sorted(degree_by_node, key=_sort_key)
        },
    }


def _prefer_bidirectional_minimal_loop_candidates(
    candidates: list[TrunkCandidate],
) -> list[TrunkCandidate]:
    preferred = [candidate for candidate in candidates if candidate.is_bidirectional_minimal_loop]
    return preferred if preferred else candidates


def _is_same_endpoint_direct_bidirectional_candidate(
    pair: PairRecord,
    *,
    candidate: TrunkCandidate,
    roads: dict[str, RoadRecord],
) -> bool:
    if pair.through_node_ids:
        return False
    if not candidate.is_bidirectional_minimal_loop or len(candidate.road_ids) != 1:
        return False
    if len(pair.forward_path_road_ids) != 1 or tuple(pair.forward_path_road_ids) != tuple(pair.reverse_path_road_ids):
        return False

    road_id = pair.forward_path_road_ids[0]
    road = roads.get(road_id)
    if road is None or road.direction not in {0, 1}:
        return False
    if candidate.road_ids != (road_id,):
        return False
    return candidate.forward_path.road_ids == (road_id,) and candidate.reverse_path.road_ids == (road_id,)


def _prefer_same_endpoint_direct_bidirectional_candidates(
    pair: PairRecord,
    *,
    candidates: list[TrunkCandidate],
    roads: dict[str, RoadRecord],
) -> list[TrunkCandidate]:
    preferred = [
        candidate
        for candidate in candidates
        if _is_same_endpoint_direct_bidirectional_candidate(pair, candidate=candidate, roads=roads)
    ]
    return preferred if preferred else candidates


def _prefer_pair_support_aligned_minimal_candidates(
    pair: PairRecord,
    *,
    candidates: list[TrunkCandidate],
) -> list[TrunkCandidate]:
    if len(candidates) <= 1:
        return candidates

    pair_support_road_ids = set(pair.forward_path_road_ids) | set(pair.reverse_path_road_ids)
    if not pair_support_road_ids or len(pair_support_road_ids) > 4:
        return candidates

    overlap_counts = {
        id(candidate): len(set(candidate.road_ids) & pair_support_road_ids)
        for candidate in candidates
    }
    max_overlap_count = max(overlap_counts.values(), default=0)
    aligned_candidates = [
        candidate for candidate in candidates if overlap_counts.get(id(candidate), 0) == max_overlap_count
    ]
    base_candidates = aligned_candidates if max_overlap_count > 0 else candidates
    min_road_count = min(len(candidate.road_ids) for candidate in base_candidates)
    preferred = [candidate for candidate in base_candidates if len(candidate.road_ids) == min_road_count]
    return preferred if preferred else candidates


def _dedupe_trunk_candidates(
    candidates: list[TrunkCandidate],
) -> list[TrunkCandidate]:
    seen_keys: set[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]] = set()
    deduped: list[TrunkCandidate] = []
    for candidate in candidates:
        key = (
            tuple(candidate.forward_path.road_ids),
            tuple(candidate.reverse_path.road_ids),
            tuple(candidate.road_ids),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(candidate)
    return deduped


def _pair_support_seed_candidates(
    pair: PairRecord,
    *,
    context: Optional[Step1GraphContext] = None,
    roads: dict[str, RoadRecord],
    road_endpoints: dict[str, tuple[str, str]],
    pruned_road_ids: set[str],
    left_turn_formway_bit: int,
) -> list[TrunkCandidate]:
    pair_support_road_ids = set(pair.forward_path_road_ids) | set(pair.reverse_path_road_ids)
    if (
        pair.through_node_ids
        or not pair_support_road_ids
        or len(pair_support_road_ids) > 4
        or not pair_support_road_ids <= pruned_road_ids
    ):
        return []
    if len(pair.forward_path_node_ids) != len(pair.forward_path_road_ids) + 1:
        return []
    if len(pair.reverse_path_node_ids) != len(pair.reverse_path_road_ids) + 1:
        return []
    shared_internal_nodes = set(pair.forward_path_node_ids[1:-1]) & set(pair.reverse_path_node_ids[1:-1])

    def _build_seed_path(node_ids: tuple[str, ...], road_ids: tuple[str, ...]) -> Optional[DirectedPath]:
        total_length = 0.0
        for road_id in road_ids:
            road = roads.get(road_id)
            if road is None:
                return None
            total_length += _geometry_length(road.geometry)
        return DirectedPath(node_ids=node_ids, road_ids=road_ids, total_length=total_length)

    forward_path = _build_seed_path(pair.forward_path_node_ids, pair.forward_path_road_ids)
    reverse_path = _build_seed_path(pair.reverse_path_node_ids, pair.reverse_path_road_ids)
    if forward_path is None or reverse_path is None:
        return []

    is_bidirectional_minimal_loop = False
    if set(forward_path.road_ids) & set(reverse_path.road_ids):
        is_bidirectional_minimal_loop = _is_bidirectional_minimal_loop_candidate(
            forward_path=forward_path,
            reverse_path=reverse_path,
            roads=roads,
        )
    is_semantic_node_group_closure = _is_semantic_node_group_loop_candidate(
        forward_path=forward_path,
        reverse_path=reverse_path,
        context=context,
    )
    if not is_bidirectional_minimal_loop and not is_semantic_node_group_closure:
        return []
    if not shared_internal_nodes and not is_bidirectional_minimal_loop and len(pair_support_road_ids) > 2:
        if context is None:
            return []
        active_node_ids = set(forward_path.node_ids + reverse_path.node_ids)
        if len({_semantic_group_node_id(node_id, context) for node_id in active_node_ids}) == len(active_node_ids):
            return []

    left_turn_road_ids = tuple(
        road_id
        for road_id in tuple(sorted(pair_support_road_ids, key=_sort_key))
        if _road_matches_formway_bit(roads[road_id], left_turn_formway_bit)
    )
    if left_turn_road_ids:
        return []
    return [
        TrunkCandidate(
            forward_path=forward_path,
            reverse_path=reverse_path,
            road_ids=tuple(sorted(pair_support_road_ids, key=_sort_key)),
            signed_area=0.0,
            total_length=forward_path.total_length + reverse_path.total_length,
            left_turn_road_ids=left_turn_road_ids,
            max_dual_carriageway_separation_m=_dual_carriageway_separation_m(
                forward_path=forward_path,
                reverse_path=reverse_path,
                roads=roads,
            ),
            is_bidirectional_minimal_loop=is_bidirectional_minimal_loop,
            is_semantic_node_group_closure=is_semantic_node_group_closure,
        )
    ]


def _trunk_candidate_mode(candidate: TrunkCandidate) -> str:
    if candidate.is_through_collapsed_corridor:
        return "through_collapsed_corridor"
    if candidate.is_mirrored_one_sided_corridor:
        return "mirrored_one_sided_corridor"
    if candidate.is_kind2_128_local_corridor:
        return "kind2_128_local_corridor"
    return "counterclockwise_loop"


def _trunk_candidate_counterclockwise_ok(candidate: TrunkCandidate) -> bool:
    return (
        candidate.is_bidirectional_minimal_loop
        or candidate.is_semantic_node_group_closure
        or candidate.is_kind2_128_local_corridor
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
            max_dual_carriageway_separation_m = _dual_carriageway_separation_m(
                forward_path=forward_path,
                reverse_path=reverse_path,
                roads=roads,
            )
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
    *,
    gate_limit_m: float = MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
) -> tuple[list[TrunkCandidate], list[TrunkCandidate]]:
    passed: list[TrunkCandidate] = []
    failed: list[TrunkCandidate] = []
    for candidate in candidates:
        if candidate.max_dual_carriageway_separation_m <= gate_limit_m:
            passed.append(candidate)
        else:
            failed.append(candidate)
    return passed, failed


def _best_dual_separation_failure(candidates: list[TrunkCandidate]) -> Optional[TrunkCandidate]:
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item.max_dual_carriageway_separation_m, item.total_length))


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
    if len(candidate.road_ids) < 4:
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

    if len(high_grade_support_node_ids) < 1 or len(weak_connector_node_ids) < 1:
        return None

    return {
        **_dual_separation_support_info(candidate),
        "bidirectional_side_bypass_blocked": True,
        "bidirectional_side_bypass_high_grade_node_ids": high_grade_support_node_ids,
        "bidirectional_side_bypass_weak_connector_node_ids": weak_connector_node_ids,
        "bidirectional_side_bypass_road_kind_mix": sorted(road_kinds),
    }


def _minimal_loop_long_branch_gate_info(
    pair: PairRecord,
    *,
    candidate: TrunkCandidate,
    candidate_road_ids: set[str],
    pruned_road_ids: set[str],
    branch_cut_infos: list[dict[str, Any]],
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
) -> Optional[dict[str, Any]]:
    if not candidate.is_bidirectional_minimal_loop:
        return None
    if len(pruned_road_ids) != 2 or len(candidate_road_ids) != 4:
        return None

    pruned_node_ids: set[str] = set()
    for road_id in pruned_road_ids:
        pruned_node_ids.update(road_endpoints.get(road_id, ()))
    if pruned_node_ids != {pair.a_node_id, pair.b_node_id}:
        return None

    endpoint_node_ids = {pair.a_node_id, pair.b_node_id}
    long_branch_infos: list[dict[str, Any]] = []
    for info in branch_cut_infos:
        if str(info.get("cut_reason") or "") != "branch_backtrack_prune":
            continue
        road_id = str(info.get("road_id") or "")
        if not road_id or road_id in pruned_road_ids:
            continue
        endpoints = road_endpoints.get(road_id)
        if endpoints is None or not (set(endpoints) & endpoint_node_ids):
            continue
        road = context.roads.get(road_id)
        if road is None:
            continue
        road_length_m = _geometry_length(road.geometry)
        if road_length_m <= MAX_SIDE_ACCESS_DISTANCE_M:
            continue
        long_branch_infos.append(
            {
                "road_id": road_id,
                "branch_length_m": road_length_m,
                "from_node_id": endpoints[0],
                "to_node_id": endpoints[1],
            }
        )

    if not long_branch_infos:
        return None

    return {
        **_dual_separation_support_info(candidate),
        "minimal_loop_long_branch_blocked": True,
        "minimal_loop_long_branch_infos": sorted(
            long_branch_infos,
            key=lambda item: (_sort_key(item["road_id"]), item["branch_length_m"]),
        ),
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


def _split_minimal_trunk_chain_candidates(
    pair: PairRecord,
    *,
    candidates: list[TrunkCandidate],
) -> tuple[list[TrunkCandidate], list[tuple[TrunkCandidate, dict[str, Any]]]]:
    kept: list[TrunkCandidate] = []
    blocked: list[tuple[TrunkCandidate, dict[str, Any]]] = []
    for candidate in candidates:
        gate_info = _minimal_trunk_chain_gate_info(pair, candidate=candidate)
        if gate_info is None:
            kept.append(candidate)
        else:
            blocked.append((candidate, gate_info))
    return kept, blocked


def _split_bidirectional_minimal_loop_extra_branch_candidates(
    pair: PairRecord,
    *,
    candidates: list[TrunkCandidate],
    candidate_road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
) -> tuple[list[TrunkCandidate], list[tuple[TrunkCandidate, dict[str, Any]]]]:
    kept: list[TrunkCandidate] = []
    blocked: list[tuple[TrunkCandidate, dict[str, Any]]] = []
    for candidate in candidates:
        gate_info = _bidirectional_minimal_loop_extra_branch_gate_info(
            pair,
            candidate=candidate,
            candidate_road_ids=candidate_road_ids,
            road_endpoints=road_endpoints,
        )
        if gate_info is None:
            kept.append(candidate)
        else:
            blocked.append((candidate, gate_info))
    return kept, blocked


def _split_bidirectional_minimal_loop_lasso_candidates(
    pair: PairRecord,
    *,
    candidates: list[TrunkCandidate],
) -> tuple[list[TrunkCandidate], list[tuple[TrunkCandidate, dict[str, Any]]]]:
    kept: list[TrunkCandidate] = []
    blocked: list[tuple[TrunkCandidate, dict[str, Any]]] = []
    for candidate in candidates:
        gate_info = _bidirectional_minimal_loop_lasso_gate_info(pair, candidate=candidate)
        if gate_info is None:
            kept.append(candidate)
        else:
            blocked.append((candidate, gate_info))
    return kept, blocked


def _split_counterclockwise_mixed_kind_wedge_candidates(
    pair: PairRecord,
    *,
    candidates: list[TrunkCandidate],
    context: Step1GraphContext,
) -> tuple[list[TrunkCandidate], list[tuple[TrunkCandidate, dict[str, Any]]]]:
    kept: list[TrunkCandidate] = []
    blocked: list[tuple[TrunkCandidate, dict[str, Any]]] = []
    for candidate in candidates:
        gate_info = counterclockwise_mixed_kind_wedge_gate_info(pair, candidate=candidate, context=context)
        if gate_info is None:
            kept.append(candidate)
        else:
            blocked.append((candidate, {**_dual_separation_support_info(candidate), **gate_info}))
    return kept, blocked


def _split_internal_turn_angle_candidates(
    *,
    candidates: list[TrunkCandidate],
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    exclude_formway_bits_any: tuple[int, ...],
) -> tuple[list[TrunkCandidate], list[tuple[TrunkCandidate, dict[str, Any]]]]:
    kept, blocked = split_internal_turn_angle_candidates(
        candidates=candidates,
        context=context,
        road_endpoints=road_endpoints,
        exclude_formway_bits_any=exclude_formway_bits_any,
    )
    return kept, [(candidate, {**_dual_separation_support_info(candidate), **info}) for candidate, info in blocked]


def _split_minimal_loop_long_branch_candidates(
    pair: PairRecord,
    *,
    candidates: list[TrunkCandidate],
    candidate_road_ids: set[str],
    pruned_road_ids: set[str],
    branch_cut_infos: list[dict[str, Any]],
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
) -> tuple[list[TrunkCandidate], list[tuple[TrunkCandidate, dict[str, Any]]]]:
    kept: list[TrunkCandidate] = []
    blocked: list[tuple[TrunkCandidate, dict[str, Any]]] = []
    for candidate in candidates:
        gate_info = _minimal_loop_long_branch_gate_info(
            pair,
            candidate=candidate,
            candidate_road_ids=candidate_road_ids,
            pruned_road_ids=pruned_road_ids,
            branch_cut_infos=branch_cut_infos,
            context=context,
            road_endpoints=road_endpoints,
        )
        if gate_info is None:
            kept.append(candidate)
        else:
            blocked.append((candidate, gate_info))
    return kept, blocked

from .step2_trunk_evaluation import (
    _alternative_trunk_only_road_ids,
    _evaluate_kind_2_128_local_corridor,
    _evaluate_kind_2_128_local_corridor_choices,
    _evaluate_step5c_mirrored_one_sided_corridor,
    _evaluate_through_collapsed_corridor,
    _evaluate_trunk,
    _evaluate_trunk_choices,
    _kind_2_128_local_corridor_is_terminal,
    _kind_2_128_local_corridor_support_info,
    _kind_2_128_localized_search_enabled,
    _new_kind_2_128_search_budget,
    _pair_support_directed_path,
    _trunk_search_budget_audit,
)
