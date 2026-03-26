from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, replace
from typing import Any, Optional


EXACT_COMPONENT_PAIR_LIMIT = 18
EXACT_COMPONENT_OPTION_LIMIT = 48
EXACT_SINGLE_OPTION_COMPONENT_PAIR_LIMIT = 24
CORRIDOR_OVERLAP_MIN_TRUNK_COVERAGE_RATIO = 0.5


@dataclass(frozen=True)
class PairArbitrationOption:
    option_id: str
    pair_id: str
    a_node_id: str
    b_node_id: str
    trunk_mode: str
    counterclockwise_ok: bool
    warning_codes: tuple[str, ...]
    candidate_channel_road_ids: tuple[str, ...]
    pruned_road_ids: tuple[str, ...]
    trunk_road_ids: tuple[str, ...]
    segment_candidate_road_ids: tuple[str, ...]
    segment_road_ids: tuple[str, ...]
    branch_cut_road_ids: tuple[str, ...]
    boundary_terminate_node_ids: tuple[str, ...]
    transition_same_dir_blocked: bool
    support_info: dict[str, Any]


@dataclass(frozen=True)
class PairConflictRecord:
    pair_id: str
    conflict_pair_id: str
    conflict_types: tuple[str, ...]
    shared_road_ids: tuple[str, ...]
    shared_trunk_road_ids: tuple[str, ...]


@dataclass(frozen=True)
class PairArbitrationMetrics:
    endpoint_grade_priority_major: int
    endpoint_grade_priority_minor: int
    endpoint_boundary_penalty: int
    strong_anchor_win_count: int
    corridor_naturalness_score: int
    contested_trunk_coverage_count: int
    contested_trunk_coverage_ratio: float
    pair_support_expansion_penalty: int
    internal_endpoint_penalty: int
    body_connectivity_support: float
    semantic_conflict_penalty: int


@dataclass(frozen=True)
class PairArbitrationDecision:
    pair_id: str
    component_id: str
    single_pair_legal: bool
    arbitration_status: str
    endpoint_boundary_penalty: int
    strong_anchor_win_count: int
    corridor_naturalness_score: int
    contested_trunk_coverage_count: int
    contested_trunk_coverage_ratio: float
    pair_support_expansion_penalty: int
    internal_endpoint_penalty: int
    body_connectivity_support: float
    semantic_conflict_penalty: int
    lose_reason: str
    selected_option_id: Optional[str]


@dataclass(frozen=True)
class ConflictComponentSummary:
    component_id: str
    pair_ids: tuple[str, ...]
    contested_road_ids: tuple[str, ...]
    strong_anchor_node_ids: tuple[str, ...]
    exact_solver_used: bool
    fallback_greedy_used: bool
    selected_option_ids: tuple[str, ...]


@dataclass(frozen=True)
class PairArbitrationOutcome:
    selected_options_by_pair_id: dict[str, PairArbitrationOption]
    decisions: list[PairArbitrationDecision]
    conflict_records: list[PairConflictRecord]
    components: list[ConflictComponentSummary]


def _sorted_tuple(values: set[str]) -> tuple[str, ...]:
    return tuple(sorted(values))


def _option_corridor_road_ids(option: PairArbitrationOption) -> set[str]:
    return set(option.pruned_road_ids) | set(option.segment_candidate_road_ids) | set(option.trunk_road_ids)


def _option_conflict_details(
    left: PairArbitrationOption,
    right: PairArbitrationOption,
) -> tuple[set[str], set[str], set[str]]:
    shared_trunk = set(left.trunk_road_ids) & set(right.trunk_road_ids)
    shared_segment = set(left.segment_road_ids) & set(right.segment_road_ids)
    shared_corridor = _option_corridor_road_ids(left) & _option_corridor_road_ids(right)
    key_corridor = shared_corridor & (set(left.trunk_road_ids) | set(right.trunk_road_ids))
    if key_corridor:
        left_trunk_overlap_ratio = len(key_corridor & set(left.trunk_road_ids)) / float(
            max(1, len(left.trunk_road_ids))
        )
        right_trunk_overlap_ratio = len(key_corridor & set(right.trunk_road_ids)) / float(
            max(1, len(right.trunk_road_ids))
        )
        min_overlap_ratio = min(left_trunk_overlap_ratio, right_trunk_overlap_ratio)
        if shared_trunk:
            if min_overlap_ratio < CORRIDOR_OVERLAP_MIN_TRUNK_COVERAGE_RATIO:
                key_corridor = set()
        elif min_overlap_ratio <= CORRIDOR_OVERLAP_MIN_TRUNK_COVERAGE_RATIO:
            key_corridor = set()
    return shared_trunk, shared_segment, key_corridor


def _is_weak_support_overlap(
    *,
    shared_trunk_road_ids: set[str],
    shared_corridor_road_ids: set[str],
    shared_road_ids: set[str],
    road_to_node_ids: Optional[dict[str, tuple[str, str]]] = None,
    strong_anchor_node_ids: Optional[set[str]] = None,
    tjunction_anchor_node_ids: Optional[set[str]] = None,
    pair_endpoint_node_ids: Optional[set[str]] = None,
) -> bool:
    if shared_corridor_road_ids:
        return False
    if len(shared_trunk_road_ids) != 1:
        return False
    if not road_to_node_ids or not strong_anchor_node_ids:
        return False
    shared_trunk_endpoint_anchor_node_ids: set[str] = set()
    shared_trunk_endpoint_tjunction_anchor_node_ids: set[str] = set()
    if pair_endpoint_node_ids:
        for road_id in shared_trunk_road_ids:
            endpoints = road_to_node_ids.get(road_id)
            if endpoints is None:
                continue
            endpoint_node_ids = set(endpoints)
            shared_trunk_endpoint_anchor_node_ids.update(endpoint_node_ids & strong_anchor_node_ids)
            if tjunction_anchor_node_ids:
                shared_trunk_endpoint_tjunction_anchor_node_ids.update(
                    endpoint_node_ids & tjunction_anchor_node_ids
                )
            if endpoint_node_ids & pair_endpoint_node_ids:
                return False
    else:
        for road_id in shared_trunk_road_ids:
            endpoints = road_to_node_ids.get(road_id)
            if endpoints is None:
                continue
            endpoint_node_ids = set(endpoints)
            shared_trunk_endpoint_anchor_node_ids.update(endpoint_node_ids & strong_anchor_node_ids)
            if tjunction_anchor_node_ids:
                shared_trunk_endpoint_tjunction_anchor_node_ids.update(
                    endpoint_node_ids & tjunction_anchor_node_ids
                )
    if len(shared_trunk_endpoint_anchor_node_ids) == 1:
        pass
    elif not (
        len(shared_trunk_endpoint_anchor_node_ids) == 2
        and len(shared_trunk_endpoint_tjunction_anchor_node_ids) == 1
    ):
        return False
    touched_anchor_node_ids: set[str] = set()
    for road_id in shared_road_ids:
        endpoints = road_to_node_ids.get(road_id)
        if endpoints is None:
            continue
        touched_anchor_node_ids.update(set(endpoints) & strong_anchor_node_ids)
    return bool(touched_anchor_node_ids)


def _requires_tjunction_weak_support_conflict(
    left: PairArbitrationOption,
    right: PairArbitrationOption,
    *,
    shared_trunk_road_ids: set[str],
    shared_corridor_road_ids: set[str],
    shared_road_ids: set[str],
    road_to_node_ids: Optional[dict[str, tuple[str, str]]] = None,
    tjunction_anchor_node_ids: Optional[set[str]] = None,
    strong_anchor_node_ids: Optional[set[str]] = None,
) -> bool:
    if shared_corridor_road_ids:
        return False
    if len(shared_trunk_road_ids) != 1:
        return False
    if not road_to_node_ids or not tjunction_anchor_node_ids:
        return False
    if not (
        bool(left.support_info.get("bidirectional_minimal_loop"))
        or bool(right.support_info.get("bidirectional_minimal_loop"))
    ):
        return False
    shared_trunk_road_id = next(iter(shared_trunk_road_ids))
    endpoints = road_to_node_ids.get(shared_trunk_road_id)
    if endpoints is None:
        return False
    endpoint_node_ids = set(endpoints)
    touched_tjunction_anchor_node_ids = endpoint_node_ids & tjunction_anchor_node_ids
    if len(touched_tjunction_anchor_node_ids) != 1:
        return False
    other_endpoint_node_ids = endpoint_node_ids - touched_tjunction_anchor_node_ids
    if strong_anchor_node_ids and other_endpoint_node_ids & strong_anchor_node_ids:
        return False
    return True


def _shared_roads_touch_strong_anchor(
    shared_road_ids: set[str],
    *,
    road_to_node_ids: Optional[dict[str, tuple[str, str]]] = None,
    strong_anchor_node_ids: Optional[set[str]] = None,
) -> bool:
    if not shared_road_ids or not road_to_node_ids or not strong_anchor_node_ids:
        return False
    for road_id in shared_road_ids:
        endpoints = road_to_node_ids.get(road_id)
        if endpoints is None:
            continue
        if set(endpoints) & strong_anchor_node_ids:
            return True
    return False


def _is_serial_terminal_triangle_overlap(
    left: PairArbitrationOption,
    right: PairArbitrationOption,
    *,
    shared_trunk_road_ids: set[str],
    candidate_shared_road_ids: set[str],
    road_to_node_ids: Optional[dict[str, tuple[str, str]]] = None,
    strong_anchor_node_ids: Optional[set[str]] = None,
) -> bool:
    if shared_trunk_road_ids or road_to_node_ids is None:
        return False
    if len(left.trunk_road_ids) != 1 or len(right.trunk_road_ids) != 1:
        return False
    if set(left.trunk_road_ids) == set(right.trunk_road_ids):
        return False
    if len(candidate_shared_road_ids) != 3:
        return False
    if strong_anchor_node_ids and _shared_roads_touch_strong_anchor(
        candidate_shared_road_ids,
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids=strong_anchor_node_ids,
    ):
        return False

    touched_node_ids: set[str] = set()
    for road_id in candidate_shared_road_ids:
        endpoints = road_to_node_ids.get(road_id)
        if endpoints is None:
            return False
        touched_node_ids.update(endpoints)
    if len(touched_node_ids) != 3:
        return False

    endpoint_node_ids = {left.a_node_id, left.b_node_id, right.a_node_id, right.b_node_id}
    return endpoint_node_ids <= touched_node_ids


def _build_pair_conflicts(
    options_by_pair: dict[str, list[PairArbitrationOption]],
    *,
    road_to_node_ids: Optional[dict[str, tuple[str, str]]] = None,
    strong_anchor_node_ids: Optional[set[str]] = None,
    tjunction_anchor_node_ids: Optional[set[str]] = None,
) -> tuple[list[PairConflictRecord], dict[str, set[str]]]:
    pair_ids = sorted(options_by_pair)
    records: list[PairConflictRecord] = []
    adjacency: dict[str, set[str]] = {pair_id: set() for pair_id in pair_ids}

    for index, pair_id in enumerate(pair_ids):
        left_options = options_by_pair[pair_id]
        for other_pair_id in pair_ids[index + 1 :]:
            right_options = options_by_pair[other_pair_id]
            shared_trunk_road_ids: set[str] = set()
            shared_segment_road_ids: set[str] = set()
            shared_corridor_road_ids: set[str] = set()
            preserve_tjunction_conflict = False
            for left_option in left_options:
                for right_option in right_options:
                    shared_trunk, shared_segment, shared_corridor = _option_conflict_details(left_option, right_option)
                    candidate_shared_road_ids = _option_corridor_road_ids(left_option) & _option_corridor_road_ids(
                        right_option
                    )
                    if candidate_shared_road_ids and _is_serial_terminal_triangle_overlap(
                        left_option,
                        right_option,
                        shared_trunk_road_ids=shared_trunk,
                        candidate_shared_road_ids=candidate_shared_road_ids,
                        road_to_node_ids=road_to_node_ids,
                        strong_anchor_node_ids=strong_anchor_node_ids,
                    ):
                        continue
                    if _requires_tjunction_weak_support_conflict(
                        left_option,
                        right_option,
                        shared_trunk_road_ids=shared_trunk,
                        shared_corridor_road_ids=shared_corridor,
                        shared_road_ids=candidate_shared_road_ids,
                        road_to_node_ids=road_to_node_ids,
                        tjunction_anchor_node_ids=tjunction_anchor_node_ids,
                        strong_anchor_node_ids=strong_anchor_node_ids,
                    ):
                        preserve_tjunction_conflict = True
                    shared_trunk_road_ids.update(shared_trunk)
                    shared_segment_road_ids.update(shared_segment)
                    shared_corridor_road_ids.update(shared_corridor)

            if not shared_corridor_road_ids and not shared_segment_road_ids and not shared_trunk_road_ids:
                continue
            shared_road_ids = shared_corridor_road_ids | shared_segment_road_ids | shared_trunk_road_ids
            if not shared_trunk_road_ids and not shared_corridor_road_ids:
                continue
            if _is_weak_support_overlap(
                shared_trunk_road_ids=shared_trunk_road_ids,
                shared_corridor_road_ids=shared_corridor_road_ids,
                shared_road_ids=shared_road_ids,
                road_to_node_ids=road_to_node_ids,
                strong_anchor_node_ids=strong_anchor_node_ids,
                tjunction_anchor_node_ids=tjunction_anchor_node_ids,
                pair_endpoint_node_ids={
                    left_options[0].a_node_id,
                    left_options[0].b_node_id,
                    right_options[0].a_node_id,
                    right_options[0].b_node_id,
                },
            ) and not preserve_tjunction_conflict:
                continue

            conflict_types: list[str] = []
            if shared_trunk_road_ids:
                conflict_types.append("trunk_overlap")
            if shared_segment_road_ids:
                conflict_types.append("segment_body_overlap")
            if shared_corridor_road_ids:
                conflict_types.append("corridor_overlap")
            records.append(
                PairConflictRecord(
                    pair_id=pair_id,
                    conflict_pair_id=other_pair_id,
                    conflict_types=tuple(conflict_types),
                    shared_road_ids=_sorted_tuple(shared_road_ids),
                    shared_trunk_road_ids=_sorted_tuple(shared_trunk_road_ids),
                )
            )
            adjacency[pair_id].add(other_pair_id)
            adjacency[other_pair_id].add(pair_id)

    return records, adjacency


def _build_conflict_components(
    pair_ids: list[str],
    adjacency: dict[str, set[str]],
) -> list[tuple[str, ...]]:
    components: list[tuple[str, ...]] = []
    remaining = set(pair_ids)
    while remaining:
        seed = min(remaining)
        queue = deque([seed])
        component: set[str] = set()
        while queue:
            pair_id = queue.popleft()
            if pair_id in component:
                continue
            component.add(pair_id)
            for neighbor in adjacency.get(pair_id, ()):
                if neighbor not in component:
                    queue.append(neighbor)
        remaining -= component
        components.append(tuple(sorted(component)))
    return components


def _component_contested_road_ids(
    component_pair_ids: tuple[str, ...],
    options_by_pair: dict[str, list[PairArbitrationOption]],
) -> set[str]:
    road_to_pairs: dict[str, set[str]] = defaultdict(set)
    for pair_id in component_pair_ids:
        component_roads: set[str] = set()
        for option in options_by_pair[pair_id]:
            component_roads.update(_option_corridor_road_ids(option))
        for road_id in component_roads:
            road_to_pairs[road_id].add(pair_id)
    return {road_id for road_id, pair_ids in road_to_pairs.items() if len(pair_ids) >= 2}


def _option_internal_node_ids(
    option: PairArbitrationOption,
    *,
    road_to_node_ids: dict[str, tuple[str, str]],
    road_ids: Optional[tuple[str, ...]] = None,
) -> set[str]:
    node_ids: set[str] = set()
    selected_road_ids = road_ids or option.segment_candidate_road_ids or option.pruned_road_ids or option.trunk_road_ids
    for road_id in selected_road_ids:
        endpoints = road_to_node_ids.get(road_id)
        if endpoints is None:
            continue
        node_ids.update(endpoints)
    node_ids.discard(option.a_node_id)
    node_ids.discard(option.b_node_id)
    return node_ids


def _option_pair_support_road_ids(option: PairArbitrationOption) -> set[str]:
    explicit_pair_support_road_ids = {
        str(road_id)
        for road_id in option.support_info.get("pair_support_road_ids", ())
        if str(road_id)
    }
    if explicit_pair_support_road_ids:
        return explicit_pair_support_road_ids

    return {
        str(road_id)
        for road_id in (
            tuple(option.support_info.get("forward_path_road_ids", ()))
            + tuple(option.support_info.get("reverse_path_road_ids", ()))
        )
        if str(road_id)
    }


def _option_endpoint_priority_grades(option: PairArbitrationOption) -> tuple[int, int]:
    raw_value = option.support_info.get("endpoint_priority_grades", ())
    if not isinstance(raw_value, (list, tuple)):
        return (0, 0)
    grades = [int(value or 0) for value in raw_value[:2]]
    while len(grades) < 2:
        grades.append(0)
    grades.sort(reverse=True)
    return grades[0], grades[1]


def _option_metrics(
    option: PairArbitrationOption,
    *,
    contested_road_ids: set[str],
    road_lengths: dict[str, float],
    road_to_node_ids: dict[str, tuple[str, str]],
    weak_endpoint_node_ids: set[str],
    boundary_node_ids: set[str],
    semantic_conflict_node_ids: set[str],
) -> PairArbitrationMetrics:
    endpoint_grade_priority_major, endpoint_grade_priority_minor = _option_endpoint_priority_grades(option)
    pair_support_road_ids = _option_pair_support_road_ids(option)
    pair_support_expansion_penalty = len(set(option.trunk_road_ids) - pair_support_road_ids)
    endpoint_boundary_penalty = int(option.a_node_id in weak_endpoint_node_ids) + int(
        option.b_node_id in weak_endpoint_node_ids
    )
    corridor_naturalness_score = 1 if float(option.support_info.get("trunk_signed_area", 0.0)) > 1e-6 else 0
    internal_node_ids = _option_internal_node_ids(option, road_to_node_ids=road_to_node_ids)
    internal_endpoint_penalty = len(internal_node_ids & boundary_node_ids)
    contested_trunk_coverage_count = len(set(option.trunk_road_ids) & contested_road_ids)
    if (
        pair_support_expansion_penalty > 0
        and internal_endpoint_penalty > 0
        and contested_trunk_coverage_count > 0
    ):
        # Down-rank over-extended contested options that both swallow a boundary
        # node and pull in extra roads beyond the pair's direct support.
        contested_trunk_coverage_count -= 1
    contested_trunk_coverage_ratio = (
        0.0
        if not contested_road_ids
        else contested_trunk_coverage_count / float(len(contested_road_ids))
    )
    semantic_conflict_penalty = len(internal_node_ids & semantic_conflict_node_ids)
    support_road_ids = option.segment_road_ids or option.trunk_road_ids
    body_connectivity_support = float(sum(road_lengths.get(road_id, 0.0) for road_id in support_road_ids))
    return PairArbitrationMetrics(
        endpoint_grade_priority_major=endpoint_grade_priority_major,
        endpoint_grade_priority_minor=endpoint_grade_priority_minor,
        endpoint_boundary_penalty=endpoint_boundary_penalty,
        strong_anchor_win_count=0,
        corridor_naturalness_score=corridor_naturalness_score,
        contested_trunk_coverage_count=contested_trunk_coverage_count,
        contested_trunk_coverage_ratio=contested_trunk_coverage_ratio,
        pair_support_expansion_penalty=pair_support_expansion_penalty,
        internal_endpoint_penalty=internal_endpoint_penalty,
        body_connectivity_support=body_connectivity_support,
        semantic_conflict_penalty=semantic_conflict_penalty,
    )


def _component_strong_anchor_node_ids(
    component_pair_ids: tuple[str, ...],
    *,
    options_by_pair: dict[str, list[PairArbitrationOption]],
    road_to_node_ids: dict[str, tuple[str, str]],
    strong_anchor_node_ids: set[str],
) -> set[str]:
    road_to_pairs: dict[str, set[str]] = defaultdict(set)
    for pair_id in component_pair_ids:
        component_roads: set[str] = set()
        for option in options_by_pair[pair_id]:
            component_roads.update(_option_corridor_road_ids(option))
        for road_id in component_roads:
            road_to_pairs[road_id].add(pair_id)

    component_anchor_node_ids: set[str] = set()
    for road_id, pair_ids in road_to_pairs.items():
        if len(pair_ids) < 2:
            continue
        endpoints = road_to_node_ids.get(road_id)
        if endpoints is None:
            continue
        for node_id in endpoints:
            if node_id in strong_anchor_node_ids:
                component_anchor_node_ids.add(node_id)
    return component_anchor_node_ids


def _prefer_pair_support_aligned_minimal_options(
    pair_options: list[PairArbitrationOption],
    *,
    road_to_node_ids: dict[str, tuple[str, str]],
    strong_anchor_node_ids: set[str],
) -> list[PairArbitrationOption]:
    if len(pair_options) <= 1 or not strong_anchor_node_ids:
        return pair_options

    anchor_touching_options = [
        option
        for option in pair_options
        if _option_internal_node_ids(
            option,
            road_to_node_ids=road_to_node_ids,
            road_ids=_option_anchor_relevant_road_ids(option),
        )
        & strong_anchor_node_ids
    ]
    if not anchor_touching_options:
        return pair_options

    pair_support_road_ids: set[str] = set()
    for option in anchor_touching_options:
        pair_support_road_ids = _option_pair_support_road_ids(option)
        if pair_support_road_ids:
            break
    overlap_counts = {
        option.option_id: len(set(option.trunk_road_ids) & _option_pair_support_road_ids(option))
        for option in anchor_touching_options
    }
    compact_pair_support_scope = 0 < len(pair_support_road_ids) <= 4
    if compact_pair_support_scope:
        max_overlap_count = max(overlap_counts.values(), default=0)
        if max_overlap_count > 0:
            base_options = [
                option
                for option in anchor_touching_options
                if overlap_counts.get(option.option_id, 0) == max_overlap_count
            ]
        else:
            base_options = anchor_touching_options
    else:
        aligned_options = [
            option for option in anchor_touching_options if overlap_counts.get(option.option_id, 0) > 0
        ]
        base_options = aligned_options if aligned_options else anchor_touching_options
    min_trunk_road_count = min(len(option.trunk_road_ids) for option in base_options)
    preferred = [
        option for option in base_options if len(option.trunk_road_ids) == min_trunk_road_count
    ]
    return preferred if preferred else pair_options


def _ordered_trunk_node_ids(
    option: PairArbitrationOption,
    *,
    road_to_node_ids: dict[str, tuple[str, str]],
    road_ids: Optional[tuple[str, ...]] = None,
) -> tuple[str, ...]:
    ordered_road_ids = road_ids
    if ordered_road_ids is None:
        ordered_road_ids = tuple(str(road_id) for road_id in option.support_info.get("forward_path_road_ids", ()))
    if not ordered_road_ids:
        ordered_road_ids = option.trunk_road_ids
    if not ordered_road_ids:
        return ()

    ordered_node_ids = [option.a_node_id]
    current_node_id = option.a_node_id
    remaining_road_ids = list(ordered_road_ids)
    while remaining_road_ids:
        progress = False
        for index, road_id in enumerate(remaining_road_ids):
            endpoints = road_to_node_ids.get(road_id)
            if endpoints is None:
                continue
            left_node_id, right_node_id = endpoints
            if current_node_id == left_node_id:
                next_node_id = right_node_id
            elif current_node_id == right_node_id:
                next_node_id = left_node_id
            else:
                continue
            ordered_node_ids.append(next_node_id)
            current_node_id = next_node_id
            del remaining_road_ids[index]
            progress = True
            break
        if not progress:
            return ()
    return tuple(ordered_node_ids)


def _option_anchor_relevant_road_ids(option: PairArbitrationOption) -> tuple[str, ...]:
    pair_support_road_ids = _option_pair_support_road_ids(option)
    if not pair_support_road_ids:
        return option.trunk_road_ids
    support_trunk_road_ids = tuple(
        road_id for road_id in option.trunk_road_ids if road_id in pair_support_road_ids
    )
    return support_trunk_road_ids or option.trunk_road_ids


def _anchor_balance(
    option: PairArbitrationOption,
    *,
    anchor_node_id: str,
    road_to_node_ids: dict[str, tuple[str, str]],
) -> float:
    ordered_node_ids = _ordered_trunk_node_ids(
        option,
        road_to_node_ids=road_to_node_ids,
        road_ids=_option_anchor_relevant_road_ids(option),
    )
    if not ordered_node_ids:
        return 0.0

    best_balance = 0.0
    for index, node_id in enumerate(ordered_node_ids):
        if node_id != anchor_node_id:
            continue
        distance_from_start = index
        distance_from_end = len(ordered_node_ids) - 1 - index
        if distance_from_start <= 0 or distance_from_end <= 0:
            continue
        best_balance = max(best_balance, 1.0 / float(max(distance_from_start, distance_from_end)))
    return best_balance


def _anchor_priority_key(
    option: PairArbitrationOption,
    *,
    anchor_node_id: str,
    metrics: PairArbitrationMetrics,
    road_lengths: dict[str, float],
    road_to_node_ids: dict[str, tuple[str, str]],
) -> tuple[float, ...]:
    trunk_total_length = float(sum(road_lengths.get(road_id, 0.0) for road_id in option.trunk_road_ids))
    return (
        _anchor_balance(option, anchor_node_id=anchor_node_id, road_to_node_ids=road_to_node_ids),
        float(metrics.endpoint_grade_priority_major),
        float(metrics.endpoint_grade_priority_minor),
        float(-metrics.endpoint_boundary_penalty),
        float(-metrics.internal_endpoint_penalty),
        float(-metrics.pair_support_expansion_penalty),
        float(metrics.contested_trunk_coverage_count),
        float(-len(option.trunk_road_ids)),
        float(-trunk_total_length),
    )


def _strong_anchor_win_counts(
    component_pair_ids: tuple[str, ...],
    *,
    options_by_pair: dict[str, list[PairArbitrationOption]],
    metrics_by_option_id: dict[str, PairArbitrationMetrics],
    road_lengths: dict[str, float],
    road_to_node_ids: dict[str, tuple[str, str]],
    strong_anchor_node_ids: set[str],
) -> dict[str, int]:
    option_win_counts: dict[str, int] = defaultdict(int)
    if not strong_anchor_node_ids:
        return option_win_counts

    component_options = [
        option
        for pair_id in component_pair_ids
        for option in options_by_pair[pair_id]
    ]
    for anchor_node_id in sorted(strong_anchor_node_ids):
        best_key: Optional[tuple[float, ...]] = None
        best_option_ids: list[str] = []
        for option in component_options:
            priority_key = _anchor_priority_key(
                option,
                anchor_node_id=anchor_node_id,
                metrics=metrics_by_option_id[option.option_id],
                road_lengths=road_lengths,
                road_to_node_ids=road_to_node_ids,
            )
            if priority_key[0] <= 0.0:
                continue
            if best_key is None or priority_key > best_key:
                best_key = priority_key
                best_option_ids = [option.option_id]
                continue
            if priority_key == best_key:
                best_option_ids.append(option.option_id)
        if not best_option_ids:
            continue
        option_win_counts[min(best_option_ids)] += 1
    return option_win_counts


def _option_priority_key(
    option: PairArbitrationOption,
    metrics: PairArbitrationMetrics,
) -> tuple[float, ...]:
    return (
        float(metrics.endpoint_grade_priority_major),
        float(metrics.endpoint_grade_priority_minor),
        float(metrics.contested_trunk_coverage_count),
        metrics.contested_trunk_coverage_ratio,
        float(metrics.strong_anchor_win_count),
        float(-metrics.pair_support_expansion_penalty),
        float(-metrics.endpoint_boundary_penalty),
        float(-metrics.internal_endpoint_penalty),
        metrics.body_connectivity_support,
        float(-metrics.semantic_conflict_penalty),
        float(metrics.corridor_naturalness_score),
        float(-len(option.trunk_road_ids)),
        float(-len(option.segment_candidate_road_ids)),
    )


def _selection_score(
    option_ids: tuple[str, ...],
    *,
    metrics_by_option_id: dict[str, PairArbitrationMetrics],
    strong_anchor_priority_enabled: bool,
) -> tuple[float, ...]:
    endpoint_grade_major = 0
    endpoint_grade_minor = 0
    endpoint_penalty = 0
    strong_anchor_wins = 0
    corridor_naturalness = 0
    contested_count = 0
    contested_ratio = 0.0
    pair_support_expansion_penalty = 0
    internal_penalty = 0
    body_support = 0.0
    semantic_penalty = 0
    for option_id in option_ids:
        metrics = metrics_by_option_id[option_id]
        endpoint_grade_major += metrics.endpoint_grade_priority_major
        endpoint_grade_minor += metrics.endpoint_grade_priority_minor
        endpoint_penalty += metrics.endpoint_boundary_penalty
        strong_anchor_wins += metrics.strong_anchor_win_count
        corridor_naturalness += metrics.corridor_naturalness_score
        contested_count += metrics.contested_trunk_coverage_count
        contested_ratio += metrics.contested_trunk_coverage_ratio
        pair_support_expansion_penalty += metrics.pair_support_expansion_penalty
        internal_penalty += metrics.internal_endpoint_penalty
        body_support += metrics.body_connectivity_support
        semantic_penalty += metrics.semantic_conflict_penalty
    if strong_anchor_priority_enabled:
        return (
            float(endpoint_grade_major),
            float(endpoint_grade_minor),
            float(contested_count),
            contested_ratio,
            float(strong_anchor_wins),
            float(-pair_support_expansion_penalty),
            float(-endpoint_penalty),
            float(-internal_penalty),
            body_support,
            float(-semantic_penalty),
            float(corridor_naturalness),
            float(len(option_ids)),
        )
    return (
        float(endpoint_grade_major),
        float(endpoint_grade_minor),
        float(len(option_ids)),
        float(-pair_support_expansion_penalty),
        float(-endpoint_penalty),
        float(-internal_penalty),
        float(-semantic_penalty),
        float(contested_count),
        contested_ratio,
        body_support,
        float(corridor_naturalness),
    )


def _prefer_subset_dominated_same_pair_options(
    pair_options: list[PairArbitrationOption],
    *,
    metrics_by_option_id: dict[str, PairArbitrationMetrics],
) -> list[PairArbitrationOption]:
    if len(pair_options) <= 1:
        return pair_options

    pruned_options: list[PairArbitrationOption] = []
    for option in pair_options:
        option_metrics = metrics_by_option_id.get(option.option_id)
        option_trunk_road_ids = set(option.trunk_road_ids)
        if option_metrics is None or not option_trunk_road_ids:
            pruned_options.append(option)
            continue

        dominated = False
        for other in pair_options:
            if other.option_id == option.option_id:
                continue
            other_metrics = metrics_by_option_id.get(other.option_id)
            other_trunk_road_ids = set(other.trunk_road_ids)
            if other_metrics is None or not other_trunk_road_ids:
                continue
            if not other_trunk_road_ids < option_trunk_road_ids:
                continue
            if other_metrics.endpoint_boundary_penalty > option_metrics.endpoint_boundary_penalty:
                continue
            if other_metrics.internal_endpoint_penalty > option_metrics.internal_endpoint_penalty:
                continue
            if other_metrics.semantic_conflict_penalty > option_metrics.semantic_conflict_penalty:
                continue
            if other_metrics.pair_support_expansion_penalty >= option_metrics.pair_support_expansion_penalty:
                continue
            dominated = True
            break

        if not dominated:
            pruned_options.append(option)

    return pruned_options if pruned_options else pair_options


def _should_use_exact_solver(
    component_pair_ids: tuple[str, ...],
    *,
    options_by_pair: dict[str, list[PairArbitrationOption]],
) -> bool:
    if len(component_pair_ids) <= 1:
        return False

    total_option_count = sum(len(options_by_pair[pair_id]) for pair_id in component_pair_ids)
    if (
        len(component_pair_ids) <= EXACT_COMPONENT_PAIR_LIMIT
        and total_option_count <= EXACT_COMPONENT_OPTION_LIMIT
    ):
        return True

    if len(component_pair_ids) > EXACT_SINGLE_OPTION_COMPONENT_PAIR_LIMIT:
        return False

    return all(len(options_by_pair[pair_id]) == 1 for pair_id in component_pair_ids)


def _is_better_selection(
    *,
    score: tuple[float, ...],
    signature: tuple[str, ...],
    best_score: Optional[tuple[float, ...]],
    best_signature: Optional[tuple[str, ...]],
) -> bool:
    if best_score is None or best_signature is None:
        return True
    if score != best_score:
        return score > best_score
    return signature < best_signature


def _solve_component_exact(
    component_pair_ids: tuple[str, ...],
    *,
    options_by_pair: dict[str, list[PairArbitrationOption]],
    option_conflicts: dict[str, set[str]],
    metrics_by_option_id: dict[str, PairArbitrationMetrics],
    strong_anchor_priority_enabled: bool,
) -> dict[str, PairArbitrationOption]:
    pair_order = tuple(sorted(component_pair_ids, key=lambda pair_id: (len(options_by_pair[pair_id]), pair_id)))
    best_signature: Optional[tuple[str, ...]] = None
    best_score: Optional[tuple[float, ...]] = None
    best_option_ids: tuple[str, ...] = ()

    def _search(index: int, selected_option_ids: tuple[str, ...], blocked_option_ids: set[str]) -> None:
        nonlocal best_signature, best_score, best_option_ids
        if index >= len(pair_order):
            signature = tuple(sorted(selected_option_ids))
            score = _selection_score(
                signature,
                metrics_by_option_id=metrics_by_option_id,
                strong_anchor_priority_enabled=strong_anchor_priority_enabled,
            )
            if _is_better_selection(
                score=score,
                signature=signature,
                best_score=best_score,
                best_signature=best_signature,
            ):
                best_signature = signature
                best_score = score
                best_option_ids = signature
            return

        pair_id = pair_order[index]
        _search(index + 1, selected_option_ids, blocked_option_ids)

        options = sorted(
            options_by_pair[pair_id],
            key=lambda option: (
                _option_priority_key(option, metrics_by_option_id[option.option_id]),
                tuple(-ord(char) for char in option.option_id),
            ),
            reverse=True,
        )
        for option in options:
            if option.option_id in blocked_option_ids:
                continue
            next_blocked = set(blocked_option_ids)
            next_blocked.add(option.option_id)
            next_blocked.update(option_conflicts.get(option.option_id, set()))
            _search(index + 1, selected_option_ids + (option.option_id,), next_blocked)

    _search(0, (), set())

    option_by_id = {
        option.option_id: option
        for pair_id in component_pair_ids
        for option in options_by_pair[pair_id]
    }
    return {option_by_id[option_id].pair_id: option_by_id[option_id] for option_id in best_option_ids}


def _solve_component_greedy(
    component_pair_ids: tuple[str, ...],
    *,
    options_by_pair: dict[str, list[PairArbitrationOption]],
    option_conflicts: dict[str, set[str]],
    metrics_by_option_id: dict[str, PairArbitrationMetrics],
    initial_selected_options_by_pair_id: Optional[dict[str, PairArbitrationOption]] = None,
) -> dict[str, PairArbitrationOption]:
    selected_options_by_pair_id: dict[str, PairArbitrationOption] = (
        {} if initial_selected_options_by_pair_id is None else dict(initial_selected_options_by_pair_id)
    )
    blocked_option_ids: set[str] = set()
    for option in selected_options_by_pair_id.values():
        blocked_option_ids.add(option.option_id)
        blocked_option_ids.update(option_conflicts.get(option.option_id, set()))
    flattened_options = [
        option
        for pair_id in component_pair_ids
        for option in options_by_pair[pair_id]
    ]
    flattened_options.sort(
        key=lambda option: (
            _option_priority_key(option, metrics_by_option_id[option.option_id]),
            tuple(-ord(char) for char in option.option_id),
        ),
        reverse=True,
    )
    for option in flattened_options:
        if option.pair_id in selected_options_by_pair_id:
            continue
        if option.option_id in blocked_option_ids:
            continue
        selected_options_by_pair_id[option.pair_id] = option
        blocked_option_ids.add(option.option_id)
        blocked_option_ids.update(option_conflicts.get(option.option_id, set()))
    return selected_options_by_pair_id


def _solve_anchor_priority_subset(
    component_pair_ids: tuple[str, ...],
    *,
    options_by_pair: dict[str, list[PairArbitrationOption]],
    option_conflicts: dict[str, set[str]],
    metrics_by_option_id: dict[str, PairArbitrationMetrics],
) -> dict[str, PairArbitrationOption]:
    priority_pair_ids = tuple(
        sorted(
            pair_id
            for pair_id in component_pair_ids
            if any(metrics_by_option_id[option.option_id].strong_anchor_win_count > 0 for option in options_by_pair[pair_id])
        )
    )
    if not priority_pair_ids:
        return {}

    total_option_count = sum(len(options_by_pair[pair_id]) for pair_id in priority_pair_ids)
    if len(priority_pair_ids) <= EXACT_COMPONENT_PAIR_LIMIT and total_option_count <= EXACT_COMPONENT_OPTION_LIMIT:
        return _solve_component_exact(
            priority_pair_ids,
            options_by_pair=options_by_pair,
            option_conflicts=option_conflicts,
            metrics_by_option_id=metrics_by_option_id,
            strong_anchor_priority_enabled=True,
        )

    return _solve_component_greedy(
        priority_pair_ids,
        options_by_pair=options_by_pair,
        option_conflicts=option_conflicts,
        metrics_by_option_id=metrics_by_option_id,
    )


def _build_option_conflicts(
    component_pair_ids: tuple[str, ...],
    *,
    options_by_pair: dict[str, list[PairArbitrationOption]],
    road_to_node_ids: Optional[dict[str, tuple[str, str]]] = None,
    strong_anchor_node_ids: Optional[set[str]] = None,
    tjunction_anchor_node_ids: Optional[set[str]] = None,
) -> dict[str, set[str]]:
    option_conflicts: dict[str, set[str]] = defaultdict(set)
    component_options = [
        option
        for pair_id in component_pair_ids
        for option in options_by_pair[pair_id]
    ]
    for index, option in enumerate(component_options):
        for other_option in component_options[index + 1 :]:
            if option.pair_id == other_option.pair_id:
                option_conflicts[option.option_id].add(other_option.option_id)
                option_conflicts[other_option.option_id].add(option.option_id)
                continue
            shared_trunk, shared_segment, shared_corridor = _option_conflict_details(option, other_option)
            if not shared_trunk and not shared_segment and not shared_corridor:
                continue
            shared_road_ids = shared_trunk | shared_segment | shared_corridor
            candidate_shared_road_ids = _option_corridor_road_ids(option) & _option_corridor_road_ids(other_option)
            if _is_serial_terminal_triangle_overlap(
                option,
                other_option,
                shared_trunk_road_ids=shared_trunk,
                candidate_shared_road_ids=candidate_shared_road_ids,
                road_to_node_ids=road_to_node_ids,
                strong_anchor_node_ids=strong_anchor_node_ids,
            ):
                continue
            if not shared_trunk and not shared_corridor:
                continue
            preserve_tjunction_conflict = _requires_tjunction_weak_support_conflict(
                option,
                other_option,
                shared_trunk_road_ids=shared_trunk,
                shared_corridor_road_ids=shared_corridor,
                shared_road_ids=candidate_shared_road_ids,
                road_to_node_ids=road_to_node_ids,
                tjunction_anchor_node_ids=tjunction_anchor_node_ids,
                strong_anchor_node_ids=strong_anchor_node_ids,
            )
            if _is_weak_support_overlap(
                shared_trunk_road_ids=shared_trunk,
                shared_corridor_road_ids=shared_corridor,
                shared_road_ids=shared_road_ids,
                road_to_node_ids=road_to_node_ids,
                strong_anchor_node_ids=strong_anchor_node_ids,
                tjunction_anchor_node_ids=tjunction_anchor_node_ids,
                pair_endpoint_node_ids={
                    option.a_node_id,
                    option.b_node_id,
                    other_option.a_node_id,
                    other_option.b_node_id,
                },
            ) and not preserve_tjunction_conflict:
                continue
            option_conflicts[option.option_id].add(other_option.option_id)
            option_conflicts[other_option.option_id].add(option.option_id)
    return option_conflicts


def _build_decision(
    *,
    pair_id: str,
    component_id: str,
    single_pair_legal: bool,
    arbitration_status: str,
    metrics: PairArbitrationMetrics,
    lose_reason: str,
    selected_option_id: Optional[str],
) -> PairArbitrationDecision:
    return PairArbitrationDecision(
        pair_id=pair_id,
        component_id=component_id,
        single_pair_legal=single_pair_legal,
        arbitration_status=arbitration_status,
        endpoint_boundary_penalty=metrics.endpoint_boundary_penalty,
        strong_anchor_win_count=metrics.strong_anchor_win_count,
        corridor_naturalness_score=metrics.corridor_naturalness_score,
        contested_trunk_coverage_count=metrics.contested_trunk_coverage_count,
        contested_trunk_coverage_ratio=metrics.contested_trunk_coverage_ratio,
        pair_support_expansion_penalty=metrics.pair_support_expansion_penalty,
        internal_endpoint_penalty=metrics.internal_endpoint_penalty,
        body_connectivity_support=metrics.body_connectivity_support,
        semantic_conflict_penalty=metrics.semantic_conflict_penalty,
        lose_reason=lose_reason,
        selected_option_id=selected_option_id,
    )


def _infer_lose_reason(
    *,
    losing_metrics: PairArbitrationMetrics,
    winning_metrics: PairArbitrationMetrics,
    fallback_greedy_used: bool,
) -> str:
    if fallback_greedy_used:
        return "component_solver_fallback_lost"
    if (
        losing_metrics.endpoint_grade_priority_major < winning_metrics.endpoint_grade_priority_major
        or (
            losing_metrics.endpoint_grade_priority_major == winning_metrics.endpoint_grade_priority_major
            and losing_metrics.endpoint_grade_priority_minor < winning_metrics.endpoint_grade_priority_minor
        )
    ):
        return "endpoint_grade_priority_lower"
    if losing_metrics.endpoint_boundary_penalty > winning_metrics.endpoint_boundary_penalty:
        return "endpoint_boundary_penalty_higher"
    if losing_metrics.strong_anchor_win_count < winning_metrics.strong_anchor_win_count:
        return "corridor_ownership_weaker"
    if losing_metrics.pair_support_expansion_penalty > winning_metrics.pair_support_expansion_penalty:
        return "pair_support_expansion_higher"
    if losing_metrics.corridor_naturalness_score < winning_metrics.corridor_naturalness_score:
        return "corridor_naturalness_weaker"
    if losing_metrics.internal_endpoint_penalty > winning_metrics.internal_endpoint_penalty:
        return "internal_endpoint_penalty_higher"
    if losing_metrics.semantic_conflict_penalty > winning_metrics.semantic_conflict_penalty:
        return "semantic_conflict_penalty_higher"
    if (
        losing_metrics.contested_trunk_coverage_count < winning_metrics.contested_trunk_coverage_count
        or losing_metrics.contested_trunk_coverage_ratio < winning_metrics.contested_trunk_coverage_ratio
    ):
        return "corridor_ownership_weaker"
    return "lost_to_higher_priority_pair"


def arbitrate_pair_options(
    *,
    options_by_pair: dict[str, list[PairArbitrationOption]],
    single_pair_illegal_pair_ids: set[str],
    road_lengths: dict[str, float],
    road_to_node_ids: dict[str, tuple[str, str]],
    weak_endpoint_node_ids: set[str],
    boundary_node_ids: set[str],
    semantic_conflict_node_ids: set[str],
    strong_anchor_node_ids: set[str],
    tjunction_anchor_node_ids: Optional[set[str]] = None,
) -> PairArbitrationOutcome:
    legal_pair_ids = sorted(options_by_pair)
    conflict_records, adjacency = _build_pair_conflicts(
        options_by_pair,
        road_to_node_ids=road_to_node_ids,
        strong_anchor_node_ids=strong_anchor_node_ids,
        tjunction_anchor_node_ids=tjunction_anchor_node_ids,
    )
    components = _build_conflict_components(legal_pair_ids, adjacency)
    selected_options_by_pair_id: dict[str, PairArbitrationOption] = {}
    decisions: list[PairArbitrationDecision] = []
    component_summaries: list[ConflictComponentSummary] = []

    for component_index, component_pair_ids in enumerate(components, start=1):
        component_id = f"component_{component_index:04d}"
        contested_road_ids = _component_contested_road_ids(component_pair_ids, options_by_pair)
        component_strong_anchor_node_ids = _component_strong_anchor_node_ids(
            component_pair_ids,
            options_by_pair=options_by_pair,
            road_to_node_ids=road_to_node_ids,
            strong_anchor_node_ids=strong_anchor_node_ids,
        )
        component_options_by_pair = dict(options_by_pair)
        if component_strong_anchor_node_ids:
            component_options_by_pair.update(
                {
                    pair_id: _prefer_pair_support_aligned_minimal_options(
                        options_by_pair[pair_id],
                        road_to_node_ids=road_to_node_ids,
                        strong_anchor_node_ids=component_strong_anchor_node_ids,
                    )
                    for pair_id in component_pair_ids
                }
            )
        metrics_by_option_id: dict[str, PairArbitrationMetrics] = {}

        def _rebuild_metrics() -> tuple[set[str], dict[str, PairArbitrationMetrics]]:
            refreshed_contested_road_ids = _component_contested_road_ids(component_pair_ids, component_options_by_pair)
            refreshed_metrics_by_option_id: dict[str, PairArbitrationMetrics] = {}
            for rebuilt_pair_id in component_pair_ids:
                for rebuilt_option in component_options_by_pair[rebuilt_pair_id]:
                    refreshed_metrics_by_option_id[rebuilt_option.option_id] = _option_metrics(
                        rebuilt_option,
                        contested_road_ids=refreshed_contested_road_ids,
                        road_lengths=road_lengths,
                        road_to_node_ids=road_to_node_ids,
                        weak_endpoint_node_ids=weak_endpoint_node_ids,
                        boundary_node_ids=boundary_node_ids,
                        semantic_conflict_node_ids=semantic_conflict_node_ids,
                    )
            return refreshed_contested_road_ids, refreshed_metrics_by_option_id

        contested_road_ids, metrics_by_option_id = _rebuild_metrics()
        subset_pruned = False
        for pair_id in component_pair_ids:
            preferred_options = _prefer_subset_dominated_same_pair_options(
                component_options_by_pair[pair_id],
                metrics_by_option_id=metrics_by_option_id,
            )
            if len(preferred_options) != len(component_options_by_pair[pair_id]):
                component_options_by_pair[pair_id] = preferred_options
                subset_pruned = True
        if subset_pruned:
            contested_road_ids, metrics_by_option_id = _rebuild_metrics()
        strong_anchor_win_counts = _strong_anchor_win_counts(
            component_pair_ids,
            options_by_pair=component_options_by_pair,
            metrics_by_option_id=metrics_by_option_id,
            road_lengths=road_lengths,
            road_to_node_ids=road_to_node_ids,
            strong_anchor_node_ids=component_strong_anchor_node_ids,
        )
        if component_strong_anchor_node_ids:
            for option_id, metrics in tuple(metrics_by_option_id.items()):
                metrics_by_option_id[option_id] = replace(
                    metrics,
                    strong_anchor_win_count=strong_anchor_win_counts.get(option_id, 0),
                    corridor_naturalness_score=strong_anchor_win_counts.get(option_id, 0),
                )

        option_conflicts = _build_option_conflicts(
            component_pair_ids,
            options_by_pair=component_options_by_pair,
            road_to_node_ids=road_to_node_ids,
            strong_anchor_node_ids=component_strong_anchor_node_ids,
            tjunction_anchor_node_ids=tjunction_anchor_node_ids,
        )
        use_exact_solver = _should_use_exact_solver(
            component_pair_ids,
            options_by_pair=component_options_by_pair,
        )
        if len(component_pair_ids) == 1:
            pair_id = component_pair_ids[0]
            chosen_option = component_options_by_pair[pair_id][0]
            component_selected = {pair_id: chosen_option}
            fallback_greedy_used = False
            exact_solver_used = False
        elif use_exact_solver:
            component_selected = _solve_component_exact(
                component_pair_ids,
                options_by_pair=component_options_by_pair,
                option_conflicts=option_conflicts,
                metrics_by_option_id=metrics_by_option_id,
                strong_anchor_priority_enabled=bool(component_strong_anchor_node_ids),
            )
            fallback_greedy_used = False
            exact_solver_used = True
        else:
            anchor_priority_selected = _solve_anchor_priority_subset(
                component_pair_ids,
                options_by_pair=component_options_by_pair,
                option_conflicts=option_conflicts,
                metrics_by_option_id=metrics_by_option_id,
            )
            component_selected = _solve_component_greedy(
                component_pair_ids,
                options_by_pair=component_options_by_pair,
                option_conflicts=option_conflicts,
                metrics_by_option_id=metrics_by_option_id,
                initial_selected_options_by_pair_id=anchor_priority_selected,
            )
            fallback_greedy_used = len(component_pair_ids) > 1
            exact_solver_used = False

        selected_options_by_pair_id.update(component_selected)
        component_summaries.append(
            ConflictComponentSummary(
                component_id=component_id,
                pair_ids=component_pair_ids,
                contested_road_ids=_sorted_tuple(contested_road_ids),
                strong_anchor_node_ids=_sorted_tuple(component_strong_anchor_node_ids),
                exact_solver_used=exact_solver_used,
                fallback_greedy_used=fallback_greedy_used,
                selected_option_ids=tuple(sorted(option.option_id for option in component_selected.values())),
            )
        )

        for pair_id in component_pair_ids:
            if pair_id in component_selected:
                option = component_selected[pair_id]
                metrics = metrics_by_option_id[option.option_id]
                decisions.append(
                    _build_decision(
                        pair_id=pair_id,
                        component_id=component_id,
                        single_pair_legal=True,
                        arbitration_status="win",
                        metrics=metrics,
                        lose_reason="",
                        selected_option_id=option.option_id,
                    )
                )
                continue

            candidate_options = component_options_by_pair[pair_id]
            fallback_option = max(
                candidate_options,
                key=lambda option: (
                    _option_priority_key(option, metrics_by_option_id[option.option_id]),
                    tuple(-ord(char) for char in option.option_id),
                ),
            )
            fallback_metrics = metrics_by_option_id[fallback_option.option_id]
            winning_conflicts = [
                option
                for option in component_selected.values()
                if option.option_id in option_conflicts.get(fallback_option.option_id, set())
            ]
            if winning_conflicts:
                strongest_winner = max(
                    winning_conflicts,
                    key=lambda option: (
                        _option_priority_key(option, metrics_by_option_id[option.option_id]),
                        tuple(-ord(char) for char in option.option_id),
                    ),
                )
                lose_reason = _infer_lose_reason(
                    losing_metrics=fallback_metrics,
                    winning_metrics=metrics_by_option_id[strongest_winner.option_id],
                    fallback_greedy_used=fallback_greedy_used,
                )
            else:
                lose_reason = "lost_to_higher_priority_pair"

            decisions.append(
                _build_decision(
                    pair_id=pair_id,
                    component_id=component_id,
                    single_pair_legal=True,
                    arbitration_status="lose",
                    metrics=fallback_metrics,
                    lose_reason=lose_reason,
                    selected_option_id=fallback_option.option_id,
                )
            )

    for pair_id in sorted(single_pair_illegal_pair_ids):
        decisions.append(
            _build_decision(
                pair_id=pair_id,
                component_id="",
                single_pair_legal=False,
                arbitration_status="lose",
                metrics=PairArbitrationMetrics(
                    endpoint_grade_priority_major=0,
                    endpoint_grade_priority_minor=0,
                    endpoint_boundary_penalty=0,
                    strong_anchor_win_count=0,
                    corridor_naturalness_score=0,
                    contested_trunk_coverage_count=0,
                    contested_trunk_coverage_ratio=0.0,
                    pair_support_expansion_penalty=0,
                    internal_endpoint_penalty=0,
                    body_connectivity_support=0.0,
                    semantic_conflict_penalty=0,
                ),
                lose_reason="single_pair_illegal",
                selected_option_id=None,
            )
        )

    decisions.sort(key=lambda item: item.pair_id)
    return PairArbitrationOutcome(
        selected_options_by_pair_id=selected_options_by_pair_id,
        decisions=decisions,
        conflict_records=conflict_records,
        components=component_summaries,
    )
