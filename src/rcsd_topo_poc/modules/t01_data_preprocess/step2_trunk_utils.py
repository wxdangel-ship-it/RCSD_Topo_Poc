from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from math import ceil, hypot
from typing import Any, Iterable, Optional

from shapely.geometry import LineString, MultiLineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import linemerge

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
from rcsd_topo_poc.modules.t01_data_preprocess.working_layers import (
    MAX_DUAL_CARRIAGEWAY_SEPARATION_M,
    MAX_SIDE_ACCESS_DISTANCE_M,
)


LEFT_TURN_FORMWAY_BIT = 8
MAX_PATHS_PER_DIRECTION = 12
MAX_PATH_DEPTH = 64
SIDE_ACCESS_SAMPLE_STEP_M = MAX_SIDE_ACCESS_DISTANCE_M / 2.0
STEP5C_STRATEGY_ID = "STEP5C"


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
    is_bidirectional_minimal_loop: bool = False
    is_semantic_node_group_closure: bool = False


@dataclass(frozen=True)
class _TrunkEvaluationChoice:
    candidate: TrunkCandidate
    warning_codes: tuple[str, ...]
    support_info: dict[str, Any]


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


def _counterclockwise_mixed_kind_wedge_gate_info(
    pair: PairRecord,
    *,
    candidate: TrunkCandidate,
    context: Step1GraphContext,
) -> Optional[dict[str, Any]]:
    if candidate.is_bidirectional_minimal_loop or candidate.is_semantic_node_group_closure:
        return None
    if len(candidate.road_ids) != 3:
        return None

    path_lengths = sorted((len(candidate.forward_path.road_ids), len(candidate.reverse_path.road_ids)))
    if path_lengths != [1, 2]:
        return None

    short_path = candidate.forward_path if len(candidate.forward_path.road_ids) == 1 else candidate.reverse_path
    long_path = candidate.reverse_path if short_path is candidate.forward_path else candidate.forward_path
    if len(long_path.node_ids) != 3 or len(set(long_path.node_ids[1:-1])) != 1:
        return None

    short_road_id = short_path.road_ids[0]
    short_road = context.roads.get(short_road_id)
    if short_road is None:
        return None
    short_kind = int(short_road.road_kind or 0)
    if short_kind < 3:
        return None

    long_road_ids = tuple(long_path.road_ids)
    long_road_kinds = []
    for road_id in long_road_ids:
        road = context.roads.get(road_id)
        if road is None:
            return None
        long_road_kinds.append(int(road.road_kind or 0))
    if set(long_road_kinds) != {2}:
        return None

    internal_node_id = long_path.node_ids[1]
    return {
        **_dual_separation_support_info(candidate),
        "counterclockwise_mixed_kind_wedge_blocked": True,
        "counterclockwise_mixed_kind_wedge_direct_road_id": short_road_id,
        "counterclockwise_mixed_kind_wedge_direct_road_kind": short_kind,
        "counterclockwise_mixed_kind_wedge_detour_road_ids": list(long_road_ids),
        "counterclockwise_mixed_kind_wedge_detour_road_kinds": long_road_kinds,
        "counterclockwise_mixed_kind_wedge_internal_node_id": internal_node_id,
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
    if not (set(pair.forward_path_node_ids[1:-1]) & set(pair.reverse_path_node_ids[1:-1])):
        return []

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
    )
    if not is_bidirectional_minimal_loop and not is_semantic_node_group_closure:
        return []

    left_turn_road_ids = tuple(
        road_id
        for road_id in tuple(sorted(pair_support_road_ids, key=_sort_key))
        if _road_matches_formway_bit(roads[road_id], left_turn_formway_bit)
    )
    if left_turn_road_ids:
        return []
    forward_geometry = _line_geometry_from_road_ids(forward_path.road_ids, roads=roads)
    reverse_geometry = _line_geometry_from_road_ids(reverse_path.road_ids, roads=roads)
    return [
        TrunkCandidate(
            forward_path=forward_path,
            reverse_path=reverse_path,
            road_ids=tuple(sorted(pair_support_road_ids, key=_sort_key)),
            signed_area=0.0,
            total_length=forward_path.total_length + reverse_path.total_length,
            left_turn_road_ids=left_turn_road_ids,
            max_dual_carriageway_separation_m=_max_nearest_distance_m(forward_geometry, reverse_geometry) or 0.0,
            is_bidirectional_minimal_loop=is_bidirectional_minimal_loop,
            is_semantic_node_group_closure=is_semantic_node_group_closure,
        )
    ]


def _trunk_candidate_mode(candidate: TrunkCandidate) -> str:
    if candidate.is_through_collapsed_corridor:
        return "through_collapsed_corridor"
    if candidate.is_mirrored_one_sided_corridor:
        return "mirrored_one_sided_corridor"
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
            candidate.max_dual_carriageway_separation_m if candidate is not None else None
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
        gate_info = _counterclockwise_mixed_kind_wedge_gate_info(pair, candidate=candidate, context=context)
        if gate_info is None:
            kept.append(candidate)
        else:
            blocked.append((candidate, gate_info))
    return kept, blocked


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


def _evaluate_trunk_choices(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    candidate_road_ids: set[str],
    pruned_road_ids: set[str],
    branch_cut_infos: list[dict[str, Any]],
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
    mirrored_candidate: Optional[TrunkCandidate] = None
    mirrored_warnings: tuple[str, ...] = ()
    if collapsed_candidate is None:
        mirrored_candidate, mirrored_warnings = _evaluate_step5c_mirrored_one_sided_corridor(
            pair,
            context=context,
            pruned_road_ids=pruned_road_ids,
            road_endpoints=road_endpoints,
            through_rule=through_rule,
            formway_mode=formway_mode,
            left_turn_formway_bit=left_turn_formway_bit,
        )

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
    base_candidates = _dedupe_trunk_candidates(
        _pair_support_seed_candidates(
            pair,
            roads=context.roads,
            road_endpoints=road_endpoints,
            pruned_road_ids=pruned_road_ids,
            left_turn_formway_bit=left_turn_formway_bit,
        )
        + base_candidates
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
        strict_passed_candidates = _prefer_same_endpoint_direct_bidirectional_candidates(
            pair,
            candidates=strict_passed_candidates,
            roads=context.roads,
        )
        strict_passed_candidates = _prefer_pair_support_aligned_minimal_candidates(
            pair,
            candidates=strict_passed_candidates,
        )
        base_passed_candidates = _prefer_same_endpoint_direct_bidirectional_candidates(
            pair,
            candidates=base_passed_candidates,
            roads=context.roads,
        )
        base_passed_candidates = _prefer_pair_support_aligned_minimal_candidates(
            pair,
            candidates=base_passed_candidates,
        )
        strict_passed_candidates = _prefer_bidirectional_minimal_loop_candidates(strict_passed_candidates)
        base_passed_candidates = _prefer_bidirectional_minimal_loop_candidates(base_passed_candidates)
        strict_passed_candidates, strict_lasso_blocked = _split_bidirectional_minimal_loop_lasso_candidates(
            pair,
            candidates=strict_passed_candidates,
        )
        base_passed_candidates, base_lasso_blocked = _split_bidirectional_minimal_loop_lasso_candidates(
            pair,
            candidates=base_passed_candidates,
        )
        strict_passed_candidates, strict_mixed_kind_wedge_blocked = _split_counterclockwise_mixed_kind_wedge_candidates(
            pair,
            candidates=strict_passed_candidates,
            context=context,
        )
        base_passed_candidates, base_mixed_kind_wedge_blocked = _split_counterclockwise_mixed_kind_wedge_candidates(
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
        if mirrored_candidate is not None:
            return [
                _TrunkEvaluationChoice(
                    candidate=mirrored_candidate,
                    warning_codes=mirrored_warnings,
                    support_info=_dual_separation_support_info(mirrored_candidate),
                )
            ], None, mirrored_warnings, _dual_separation_support_info(mirrored_candidate)
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
        if strict_lasso_blocked or base_lasso_blocked:
            support_info = (strict_lasso_blocked or base_lasso_blocked)[0][1]
            return [], "bidirectional_minimal_loop_lasso", (), support_info
        if strict_mixed_kind_wedge_blocked or base_mixed_kind_wedge_blocked:
            support_info = (strict_mixed_kind_wedge_blocked or base_mixed_kind_wedge_blocked)[0][1]
            return [], "counterclockwise_mixed_kind_wedge", (), support_info
        if strict_failed_candidates or base_failed_candidates or collapsed_failed_candidate is not None:
            failure_candidate = _best_dual_separation_failure(
                strict_failed_candidates
                or base_failed_candidates
                or ([collapsed_failed_candidate] if collapsed_failed_candidate else [])
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
    if mirrored_candidate is not None:
        return [
            _TrunkEvaluationChoice(
                candidate=mirrored_candidate,
                warning_codes=mirrored_warnings,
                support_info=_dual_separation_support_info(mirrored_candidate),
            )
        ], None, mirrored_warnings, _dual_separation_support_info(mirrored_candidate)
    base_passed_candidates, base_failed_candidates = _split_dual_separation_candidates(base_candidates)
    base_passed_candidates = _prefer_same_endpoint_direct_bidirectional_candidates(
        pair,
        candidates=base_passed_candidates,
        roads=context.roads,
    )
    base_passed_candidates = _prefer_pair_support_aligned_minimal_candidates(
        pair,
        candidates=base_passed_candidates,
    )
    base_passed_candidates = _prefer_bidirectional_minimal_loop_candidates(base_passed_candidates)
    base_passed_candidates, base_lasso_blocked = _split_bidirectional_minimal_loop_lasso_candidates(
        pair,
        candidates=base_passed_candidates,
    )
    base_passed_candidates, base_mixed_kind_wedge_blocked = _split_counterclockwise_mixed_kind_wedge_candidates(
        pair,
        candidates=base_passed_candidates,
        context=context,
    )
    if not base_passed_candidates:
        if base_lasso_blocked:
            return [], "bidirectional_minimal_loop_lasso", (), base_lasso_blocked[0][1]
        if base_mixed_kind_wedge_blocked:
            return [], "counterclockwise_mixed_kind_wedge", (), base_mixed_kind_wedge_blocked[0][1]
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
    candidate_road_ids: set[str],
    pruned_road_ids: set[str],
    branch_cut_infos: list[dict[str, Any]],
    road_endpoints: dict[str, tuple[str, str]],
    through_rule: ThroughRuleSpec,
    formway_mode: str,
    left_turn_formway_bit: int,
) -> tuple[Optional[TrunkCandidate], Optional[str], tuple[str, ...], dict[str, Any]]:
    choices, reject_reason, warning_codes, support_info = _evaluate_trunk_choices(
        pair,
        context=context,
        candidate_road_ids=candidate_road_ids,
        pruned_road_ids=pruned_road_ids,
        branch_cut_infos=branch_cut_infos,
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

    return (
        TrunkCandidate(
            forward_path=forward_path,
            reverse_path=reverse_path,
            road_ids=support_road_ids,
            signed_area=0.0,
            total_length=forward_path.total_length + reverse_path.total_length,
            left_turn_road_ids=tuple(
                road_id
                for road_id in support_road_ids
                if _road_matches_formway_bit(context.roads[road_id], left_turn_formway_bit)
            ),
            max_dual_carriageway_separation_m=0.0,
            is_through_collapsed_corridor=True,
        ),
        warnings,
    )


def _evaluate_step5c_mirrored_one_sided_corridor(
    pair: PairRecord,
    *,
    context: Step1GraphContext,
    pruned_road_ids: set[str],
    road_endpoints: dict[str, tuple[str, str]],
    through_rule: ThroughRuleSpec,
    formway_mode: str,
    left_turn_formway_bit: int,
) -> tuple[Optional[TrunkCandidate], tuple[str, ...]]:
    if pair.strategy_id != STEP5C_STRATEGY_ID:
        return None, ()
    if not pair.used_mirrored_reverse_confirm_fallback:
        return None, ()
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
    if not forward_paths and not reverse_paths:
        return None, ()
    actual_path = forward_paths[0] if forward_paths else reverse_paths[0]
    if tuple(sorted(set(actual_path.road_ids), key=_sort_key)) != support_road_ids:
        return None, ()
    forward_path = DirectedPath(
        node_ids=tuple(pair.forward_path_node_ids),
        road_ids=tuple(pair.forward_path_road_ids),
        total_length=actual_path.total_length,
    )
    reverse_path = DirectedPath(
        node_ids=tuple(pair.reverse_path_node_ids),
        road_ids=tuple(pair.reverse_path_road_ids),
        total_length=actual_path.total_length,
    )

    return (
        TrunkCandidate(
            forward_path=forward_path,
            reverse_path=reverse_path,
            road_ids=support_road_ids,
            signed_area=0.0,
            total_length=forward_path.total_length + reverse_path.total_length,
            left_turn_road_ids=tuple(
                road_id
                for road_id in support_road_ids
                if _road_matches_formway_bit(context.roads[road_id], left_turn_formway_bit)
            ),
            max_dual_carriageway_separation_m=0.0,
            is_mirrored_one_sided_corridor=True,
        ),
        warnings,
    )
