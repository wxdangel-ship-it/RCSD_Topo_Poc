from __future__ import annotations

from collections import defaultdict, deque
from itertools import count
from typing import Iterable, Optional

from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import TraversalEdge, _sort_key


def _collect_road_node_ids(
    road_ids: Iterable[str],
    *,
    road_endpoints: dict[str, tuple[str, str]],
) -> set[str]:
    node_ids: set[str] = set()
    for road_id in road_ids:
        node_ids.update(road_endpoints.get(road_id, ()))
    return node_ids


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
