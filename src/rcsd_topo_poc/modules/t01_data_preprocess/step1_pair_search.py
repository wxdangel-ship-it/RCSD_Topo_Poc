from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Optional

from rcsd_topo_poc.modules.t01_data_preprocess import step1_pair_poc as _facade
from rcsd_topo_poc.modules.t01_data_preprocess.road_kind_continuity import (
    choose_preferred_continuation_edges,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_models import (
    NodeRecord,
    PairRecord,
    RoadRecord,
    RuleEvaluation,
    SearchCandidate,
    SearchResult,
    SemanticNodeRecord,
    StrategySpec,
    ThroughRuleSpec,
    TraversalEdge,
)


COMPLEX_JUNCTION_KIND_2 = 128


def _bit_enabled(*args: Any, **kwargs: Any) -> bool:
    return _facade._bit_enabled(*args, **kwargs)


def _complex_junction_mainnode_ids(*args: Any, **kwargs: Any) -> set[str]:
    return _facade._complex_junction_mainnode_ids(*args, **kwargs)


def _normalize_mainnodeid(*args: Any, **kwargs: Any) -> Optional[str]:
    return _facade._normalize_mainnodeid(*args, **kwargs)


def _sort_key(*args: Any, **kwargs: Any) -> tuple[int, Any]:
    return _facade._sort_key(*args, **kwargs)


def _uses_complex_junction_physical_semantics(*args: Any, **kwargs: Any) -> bool:
    return _facade._uses_complex_junction_physical_semantics(*args, **kwargs)


def _append_capped_event_sample(
    event_samples: list[dict[str, Any]],
    sample_counts: dict[str, int],
    payload: dict[str, Any],
) -> None:
    event_name = str(payload["event"])
    if sample_counts.get(event_name, 0) >= _facade.SEARCH_EVENT_SAMPLE_LIMIT_PER_TYPE:
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


def _build_candidate_to_terminal(
    *,
    start_node_id: str,
    reached_node_id: str,
    terminal_node_id: str,
    parent_node_ids: dict[str, Optional[str]],
    parent_road_ids: dict[str, str],
    through_node_ids: set[str],
) -> SearchCandidate:
    candidate = _build_candidate_from_parents(
        start_node_id=start_node_id,
        terminal_node_id=reached_node_id,
        parent_node_ids=parent_node_ids,
        parent_road_ids=parent_road_ids,
        through_node_ids=through_node_ids,
    )
    return _canonicalize_candidate_terminal(candidate, terminal_node_id)


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


def _is_complex_junction_semantic_node(
    node: SemanticNodeRecord,
    *,
    physical_nodes: dict[str, NodeRecord],
) -> bool:
    if node.kind_2 == COMPLEX_JUNCTION_KIND_2:
        return True
    complex_mainnode_ids = _complex_junction_mainnode_ids(physical_nodes)
    for member_node_id in node.member_node_ids:
        member = physical_nodes.get(member_node_id)
        if member is not None and member.kind_2 == COMPLEX_JUNCTION_KIND_2:
            return True
        if member is not None and _uses_complex_junction_physical_semantics(member, complex_mainnode_ids):
            return True
    return False


def _complex_junction_semantic_node_ids(
    semantic_nodes: dict[str, SemanticNodeRecord],
    *,
    physical_nodes: dict[str, NodeRecord],
) -> set[str]:
    return {
        node_id
        for node_id, node in semantic_nodes.items()
        if _is_complex_junction_semantic_node(node, physical_nodes=physical_nodes)
    }


def _complex_junction_equivalent_node_ids(
    semantic_nodes: dict[str, SemanticNodeRecord],
    *,
    physical_nodes: dict[str, NodeRecord],
) -> dict[str, tuple[str, ...]]:
    complex_node_ids = _complex_junction_semantic_node_ids(semantic_nodes, physical_nodes=physical_nodes)
    grouped: dict[str, set[str]] = defaultdict(set)
    for node_id in complex_node_ids:
        node = semantic_nodes[node_id]
        source_mainnodeid = _normalize_mainnodeid(node.raw_properties.get("mainnodeid"))
        group_id = source_mainnodeid or node_id
        grouped[group_id].add(node_id)

    equivalent: dict[str, tuple[str, ...]] = {}
    for member_ids in grouped.values():
        if len(member_ids) < 2:
            continue
        ordered = tuple(sorted(member_ids, key=_sort_key))
        for node_id in ordered:
            equivalent[node_id] = ordered
    return equivalent


def _road_matches_any_formway_bit(road: RoadRecord, bits: tuple[int, ...]) -> bool:
    if not bits or road.formway is None:
        return False
    return any(_bit_enabled(road.formway, bit_index) for bit_index in bits)


def _is_null_mainnode_singleton_semantic_node(node: SemanticNodeRecord) -> bool:
    if len(node.member_node_ids) != 1:
        return False
    return _normalize_mainnodeid(node.raw_properties.get("mainnodeid")) is None


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


def _equivalent_complex_terminal_node_id(
    node_id: str,
    *,
    start_node_id: str,
    seed_eval: dict[str, RuleEvaluation],
    terminate_eval: dict[str, RuleEvaluation],
    complex_junction_equivalent_node_ids: dict[str, tuple[str, ...]],
) -> Optional[str]:
    for equivalent_node_id in complex_junction_equivalent_node_ids.get(node_id, ()):
        if equivalent_node_id in {node_id, start_node_id}:
            continue
        if seed_eval[equivalent_node_id].matched and terminate_eval[equivalent_node_id].matched:
            return equivalent_node_id
    return None


def _search_from_seed(
    start_node_id: str,
    *,
    directed: dict[str, tuple[TraversalEdge, ...]],
    blocked: dict[str, tuple[TraversalEdge, ...]],
    roads: dict[str, RoadRecord],
    physical_to_semantic: dict[str, str],
    through_node_ids: set[str],
    hard_stop_node_ids: set[str],
    seed_eval: dict[str, RuleEvaluation],
    terminate_eval: dict[str, RuleEvaluation],
    continue_after_terminal_candidate: bool = False,
    complex_junction_equivalent_node_ids: Optional[dict[str, tuple[str, ...]]] = None,
    prefer_exact_kind_token: bool = True,
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

        outgoing_edges = tuple(edge for edge in directed.get(current_node_id, ()) if edge.to_node not in visited)
        previous_node_id = parent_node_ids.get(current_node_id)
        incoming_road_id = parent_road_ids.get(current_node_id)
        if previous_node_id is not None and incoming_road_id is not None:
            decision = choose_preferred_continuation_edges(
                current_node_id=current_node_id,
                incoming_from_node_id=previous_node_id,
                incoming_road_id=incoming_road_id,
                outgoing_edges=outgoing_edges,
                roads=roads,
                physical_to_semantic=physical_to_semantic,
                prefer_exact_kind_token=prefer_exact_kind_token,
            )
            if decision.pruned_edges:
                _record_search_event(
                    event_counts,
                    event_samples,
                    sample_counts,
                    {
                        "event": "road_kind_continuity_pruned",
                        "seed_node_id": start_node_id,
                        "node_id": current_node_id,
                        "incoming_road_id": incoming_road_id,
                        "kept_road_ids": [edge.road_id for edge in decision.edges],
                        "pruned_road_ids": [edge.road_id for edge in decision.pruned_edges],
                        "same_level_applied": decision.same_level_applied,
                        "angle_applied": decision.angle_applied,
                        "best_angle_deg": decision.best_angle_deg,
                        "kept_angle_limit_deg": decision.kept_angle_limit_deg,
                    },
                )
            outgoing_edges = decision.edges

        for edge in outgoing_edges:
            next_node_id = edge.to_node

            visited.add(next_node_id)
            parent_node_ids[next_node_id] = current_node_id
            parent_road_ids[next_node_id] = edge.road_id
            terminate_ok = terminate_eval[next_node_id].matched
            seed_ok = seed_eval[next_node_id].matched
            candidate_terminal_node_id = next_node_id if terminate_ok and seed_ok else None
            equivalent_terminal_node_id = _equivalent_complex_terminal_node_id(
                next_node_id,
                start_node_id=start_node_id,
                seed_eval=seed_eval,
                terminate_eval=terminate_eval,
                complex_junction_equivalent_node_ids=complex_junction_equivalent_node_ids or {},
            )
            if candidate_terminal_node_id is None and equivalent_terminal_node_id is not None:
                candidate_terminal_node_id = equivalent_terminal_node_id
            through_node = next_node_id != start_node_id and next_node_id in through_node_ids
            hard_stop_node = next_node_id != start_node_id and next_node_id in hard_stop_node_ids

            if hard_stop_node:
                _record_search_event(
                    event_counts,
                    event_samples,
                    sample_counts,
                    {
                        "event": "hard_stop_boundary",
                        "seed_node_id": start_node_id,
                        "node_id": next_node_id,
                        "road_id": edge.road_id,
                    },
                )
                if candidate_terminal_node_id is not None and next_node_id != start_node_id:
                    candidates[candidate_terminal_node_id] = _build_candidate_to_terminal(
                        start_node_id=start_node_id,
                        reached_node_id=next_node_id,
                        terminal_node_id=candidate_terminal_node_id,
                        parent_node_ids=parent_node_ids,
                        parent_road_ids=parent_road_ids,
                        through_node_ids=through_node_ids,
                    )
                    _record_search_event(
                        event_counts,
                        event_samples,
                        sample_counts,
                        {
                            "event": "hard_stop_terminal_candidate",
                            "seed_node_id": start_node_id,
                            "node_id": candidate_terminal_node_id,
                            "road_id": edge.road_id,
                        },
                    )
                    if equivalent_terminal_node_id is not None:
                        _record_search_event(
                            event_counts,
                            event_samples,
                            sample_counts,
                            {
                                "event": "equivalent_complex_terminal_candidate",
                                "seed_node_id": start_node_id,
                                "node_id": equivalent_terminal_node_id,
                                "reached_node_id": next_node_id,
                                "road_id": edge.road_id,
                            },
                        )
                elif terminate_ok:
                    _record_search_event(
                        event_counts,
                        event_samples,
                        sample_counts,
                        {
                            "event": "hard_stop_terminal_not_seed",
                            "seed_node_id": start_node_id,
                            "node_id": next_node_id,
                            "terminate_reasons": list(terminate_eval[next_node_id].reasons),
                            "seed_reasons": list(seed_eval[next_node_id].reasons),
                        },
                    )
                continue

            if through_node and equivalent_terminal_node_id is None:
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

            if candidate_terminal_node_id is not None and next_node_id != start_node_id:
                candidates[candidate_terminal_node_id] = _build_candidate_to_terminal(
                    start_node_id=start_node_id,
                    reached_node_id=next_node_id,
                    terminal_node_id=candidate_terminal_node_id,
                    parent_node_ids=parent_node_ids,
                    parent_road_ids=parent_road_ids,
                    through_node_ids=through_node_ids,
                )
                if continue_after_terminal_candidate:
                    _record_search_event(
                        event_counts,
                        event_samples,
                        sample_counts,
                        {
                            "event": "terminal_candidate_continued",
                            "seed_node_id": start_node_id,
                            "node_id": candidate_terminal_node_id,
                            "road_id": edge.road_id,
                        },
                    )
                    queue.append(next_node_id)
                if equivalent_terminal_node_id is not None:
                    _record_search_event(
                        event_counts,
                        event_samples,
                        sample_counts,
                        {
                            "event": "equivalent_complex_terminal_candidate",
                            "seed_node_id": start_node_id,
                            "node_id": equivalent_terminal_node_id,
                            "reached_node_id": next_node_id,
                            "road_id": edge.road_id,
                        },
                    )
                continue

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


def _canonicalize_candidate_terminal(candidate: SearchCandidate, terminal_node_id: str) -> SearchCandidate:
    if candidate.terminal_node_id == terminal_node_id:
        return candidate
    return SearchCandidate(
        terminal_node_id=terminal_node_id,
        path_node_ids=tuple(candidate.path_node_ids),
        path_road_ids=tuple(candidate.path_road_ids),
        through_node_ids=tuple(candidate.through_node_ids),
    )


def _find_reverse_candidate(
    reverse_result: Optional[SearchResult],
    *,
    start_node_id: str,
    complex_junction_equivalent_node_ids: dict[str, tuple[str, ...]],
) -> tuple[Optional[SearchCandidate], Optional[str]]:
    if reverse_result is None:
        return None, None
    reverse_candidate = reverse_result.candidates.get(start_node_id)
    if reverse_candidate is not None:
        return reverse_candidate, start_node_id

    for equivalent_node_id in complex_junction_equivalent_node_ids.get(start_node_id, ()):
        if equivalent_node_id == start_node_id:
            continue
        equivalent_candidate = reverse_result.candidates.get(equivalent_node_id)
        if equivalent_candidate is not None:
            return _canonicalize_candidate_terminal(equivalent_candidate, start_node_id), equivalent_node_id
    return None, None


def _build_pair_records(
    strategy: StrategySpec,
    search_results: dict[str, SearchResult],
    event_counts: dict[str, int],
    event_samples: list[dict[str, Any]],
    sample_counts: dict[str, int],
    *,
    complex_junction_node_ids: set[str],
    complex_junction_equivalent_node_ids: dict[str, tuple[str, ...]],
) -> list[PairRecord]:
    pairs: dict[str, PairRecord] = {}
    force_terminate_node_ids = set(strategy.force_terminate_node_ids)
    for start_node_id, search_result in search_results.items():
        for terminal_node_id, candidate in search_result.candidates.items():
            reverse_result = search_results.get(terminal_node_id)
            reverse_candidate, reverse_confirm_node_id = _find_reverse_candidate(
                reverse_result,
                start_node_id=start_node_id,
                complex_junction_equivalent_node_ids=complex_junction_equivalent_node_ids,
            )
            if reverse_candidate is not None and reverse_confirm_node_id != start_node_id:
                _record_search_event(
                    event_counts,
                    event_samples,
                    sample_counts,
                    {
                        "event": "reverse_confirm_equivalent_complex_port",
                        "strategy_id": strategy.strategy_id,
                        "a_node_id": start_node_id,
                        "b_node_id": terminal_node_id,
                        "reverse_confirm_node_id": reverse_confirm_node_id,
                    },
                )
            used_mirrored_reverse_confirm_fallback = False
            if reverse_candidate is None:
                if (
                    strategy.allow_mirrored_one_sided_reverse_confirm_for_force_terminate_nodes
                    and start_node_id in force_terminate_node_ids
                    and terminal_node_id in force_terminate_node_ids
                ):
                    reversed_path_node_ids = tuple(reversed(candidate.path_node_ids))
                    reversed_path_road_ids = tuple(reversed(candidate.path_road_ids))
                    reversed_through_node_ids = tuple(
                        node_id
                        for node_id in reversed_path_node_ids[1:-1]
                        if node_id in set(candidate.through_node_ids)
                    )
                    reverse_candidate = SearchCandidate(
                        terminal_node_id=start_node_id,
                        path_node_ids=reversed_path_node_ids,
                        path_road_ids=reversed_path_road_ids,
                        through_node_ids=reversed_through_node_ids,
                    )
                    used_mirrored_reverse_confirm_fallback = True
                    _record_search_event(
                        event_counts,
                        event_samples,
                        sample_counts,
                        {
                            "event": "reverse_confirm_fallback_mirrored",
                            "strategy_id": strategy.strategy_id,
                            "a_node_id": start_node_id,
                            "b_node_id": terminal_node_id,
                        },
                    )
                else:
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

            forward_complex_junction_node_ids = tuple(
                node_id
                for node_id in forward_candidate.path_node_ids[1:-1]
                if node_id in complex_junction_node_ids
            )
            reverse_complex_junction_node_ids = tuple(
                node_id
                for node_id in backward_candidate.path_node_ids[1:-1]
                if node_id in complex_junction_node_ids
            )

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
                used_mirrored_reverse_confirm_fallback=used_mirrored_reverse_confirm_fallback,
                kind_2_128_node_ids=tuple(
                    sorted(
                        set(forward_complex_junction_node_ids + reverse_complex_junction_node_ids),
                        key=_sort_key,
                    )
                ),
                forward_kind_2_128_node_ids=forward_complex_junction_node_ids,
                reverse_kind_2_128_node_ids=reverse_complex_junction_node_ids,
            )

    return sorted(pairs.values(), key=lambda pair: (_sort_key(pair.a_node_id), _sort_key(pair.b_node_id)))
