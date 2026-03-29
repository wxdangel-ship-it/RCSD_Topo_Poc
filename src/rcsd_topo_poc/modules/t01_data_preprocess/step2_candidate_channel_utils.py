from __future__ import annotations

from collections import deque
from typing import Any, Optional

from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    PairRecord,
    Step1GraphContext,
    ThroughRuleSpec,
    TraversalEdge,
    _sort_key,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_graph_primitives import (
    _build_incident_map,
    _collect_component_road_ids,
    _collect_components,
    _collect_road_node_ids,
    _count_components,
    _find_bridge_road_ids,
    _other_endpoint,
    _path_exists_undirected,
    _remaining_degree,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_trunk_utils import (
    _collect_segment_path_road_ids,
    _road_matches_any_formway_bits,
)


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
        if str(info.get('cut_reason', '')) == 'branch_backtrack_prune' and info.get('road_id') in road_endpoints
    ]
    if not backtrack_infos:
        return allowed_road_ids

    normalized_backtrack_infos = [
        (
            str(info['road_id']),
            str(info['from_node_id']),
            str(info['to_node_id']),
        )
        for info in backtrack_infos
        if info.get('from_node_id') and info.get('to_node_id')
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
        current_connects_protected = _path_exists_undirected(
            pair.a_node_id,
            pair.b_node_id,
            road_ids=remaining_road_ids,
            road_endpoints=road_endpoints,
        )
        if current_connects_protected and not _path_exists_undirected(
            pair.a_node_id,
            pair.b_node_id,
            road_ids=remaining_road_ids - {road_id},
            road_endpoints=road_endpoints,
        ):
            continue
        if node_id in hard_stop_node_ids and node_id not in protected:
            cut_reason = 'branch_leads_to_historical_boundary'
        elif node_id in terminate_ids and node_id not in protected:
            cut_reason = 'branch_leads_to_other_terminate'
        else:
            cut_reason = 'branch_backtrack_prune'
        branch_cut_infos.append(
            {
                'road_id': road_id,
                'cut_reason': cut_reason,
                'from_node_id': node_id,
                'to_node_id': other_node_id,
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
                    'road_id': road_id,
                    'cut_reason': 'segment_exclude_formway',
                    'from_node_id': from_node_id,
                    'to_node_id': to_node_id,
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
                    'road_id': road_id,
                    'cut_reason': 'segment_backtrack_prune',
                    'from_node_id': node_id,
                    'to_node_id': other_node_id,
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
                        'road_id': road_id,
                        'cut_reason': 'segment_bridge_prune',
                        'from_node_id': from_node_id,
                        'to_node_id': to_node_id,
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
                'road_id': road_id,
                'cut_reason': 'segment_disconnected_component_prune',
                'from_node_id': from_node_id,
                'to_node_id': to_node_id,
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
                'road_id': road_id,
                'cut_reason': 'segment_non_path_prune',
                'from_node_id': from_node_id,
                'to_node_id': to_node_id,
            }
        )
    if path_road_ids:
        final_road_ids = path_road_ids | trunk_road_id_set

    return tuple(sorted(final_road_ids, key=_sort_key)), segment_cut_infos
