from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
import math
from typing import Any

from rcsd_topo_poc.modules.p01_arm_build.io import normalise_id
from rcsd_topo_poc.modules.p01_arm_build.models import (
    ArmTrace,
    FinalArm,
    FinalArmValidation,
    InitialArm,
    NodeRecord,
    RoadRecord,
)
from rcsd_topo_poc.modules.p01_arm_build.special_roads import is_advance_right_turn_road


RELAXABLE_STOP_TYPES = {
    "ambiguous_boundary",
    "semantic_boundary",
    "t_side_terminal",
    "dead_end",
}
NON_RELAXABLE_STOP_TYPES = {
    "patch_boundary",
    "loop_to_current_junction",
    "unresolved",
}
RELAXED_MAINLINE_MAX_ANGLE_DEG = 25.0
RELAXED_MAINLINE_MIN_MARGIN_DEG = 12.0


@dataclass(frozen=True)
class FinalArmValidationBuildResult:
    final_arms: tuple[FinalArm, ...]
    validations: tuple[FinalArmValidation, ...]
    issues: tuple[dict[str, Any], ...]
    metrics: dict[str, int]


@dataclass(frozen=True)
class RelaxedTraceResult:
    relaxed_trace_id: str
    initial_arm_id: str
    terminal_group_id: str | None
    terminal_type: str
    road_ids: tuple[str, ...]
    node_ids: tuple[str, ...]
    risk_flags: tuple[str, ...]
    issue_flags: tuple[str, ...]


@dataclass(frozen=True)
class RelaxedContinuationOption:
    road_id: str
    next_group_id: str
    angle_delta: float | None


@dataclass(frozen=True)
class RelaxedProbeResult:
    terminal_group_id: str
    terminal_type: str
    road_ids: tuple[str, ...]
    node_ids: tuple[str, ...]


def _valid_mainnodeid(value: str | None) -> str | None:
    text = normalise_id(value)
    if not text or text.lower() in {"0", "0.0", "none", "null", "nan"}:
        return None
    return text


def _semantic_group_id(node: NodeRecord | None, fallback_node_id: str) -> str:
    if node is None:
        return normalise_id(fallback_node_id)
    return _valid_mainnodeid(node.mainnodeid) or node.node_id


def _road_endpoint_groups(road: RoadRecord, nodes: dict[str, NodeRecord]) -> tuple[str, str]:
    return _semantic_group_id(nodes.get(road.snodeid), road.snodeid), _semantic_group_id(nodes.get(road.enodeid), road.enodeid)


_VALIDATION_INCIDENT_ROAD_IDS_BY_GROUP_CACHE: dict[tuple[int, int, str, int, int, str], dict[str, tuple[str, ...]]] = {}


def _road_group_cache_key(
    roads: dict[str, RoadRecord],
    nodes: dict[str, NodeRecord],
) -> tuple[int, int, str, int, int, str]:
    return (id(roads), len(roads), next(iter(roads), ""), id(nodes), len(nodes), next(iter(nodes), ""))


def _validation_incident_road_ids_by_group(
    roads: dict[str, RoadRecord],
    nodes: dict[str, NodeRecord],
) -> dict[str, tuple[str, ...]]:
    cache_key = _road_group_cache_key(roads, nodes)
    cached = _VALIDATION_INCIDENT_ROAD_IDS_BY_GROUP_CACHE.get(cache_key)
    if cached is not None:
        return cached
    by_group: dict[str, list[str]] = {}
    for road_id, road in roads.items():
        start_group, end_group = _road_endpoint_groups(road, nodes)
        if start_group == end_group:
            continue
        by_group.setdefault(start_group, []).append(road_id)
        by_group.setdefault(end_group, []).append(road_id)
    indexed = {group_id: tuple(sorted(road_ids)) for group_id, road_ids in by_group.items()}
    _VALIDATION_INCIDENT_ROAD_IDS_BY_GROUP_CACHE[cache_key] = indexed
    return indexed


def _other_group_for_road(road: RoadRecord, group_id: str, nodes: dict[str, NodeRecord]) -> str | None:
    start_group, end_group = _road_endpoint_groups(road, nodes)
    if start_group == group_id and end_group != group_id:
        return end_group
    if end_group == group_id and start_group != group_id:
        return start_group
    return None


def _node_ids_for_group(group_id: str, groups: dict[str, tuple[str, ...]]) -> tuple[str, ...]:
    return groups.get(group_id, (group_id,))


def _kind_category(group_id: str, groups: dict[str, tuple[str, ...]], nodes: dict[str, NodeRecord]) -> str:
    kinds = {
        normalise_id(nodes[node_id].kind)
        for node_id in _node_ids_for_group(group_id, groups)
        if node_id in nodes and normalise_id(nodes[node_id].kind)
    }
    if "2048" in kinds:
        return "kind_2048"
    if "4" in kinds:
        return "kind_4"
    return "kind_continue"


def _semantic_terminal_is_strong(
    *,
    group_id: str,
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
) -> bool:
    if _kind_category(group_id, groups, nodes) not in {"kind_4", "kind_2048"}:
        return False
    member_count = len(_node_ids_for_group(group_id, groups))
    incident_count = len(
        _incident_validation_roads(
            group_id=group_id,
            nodes=nodes,
            roads=roads,
            excluded_road_ids=excluded_road_ids,
            internal_road_ids=internal_road_ids,
        )
    )
    return member_count >= 3 or incident_count >= 6


def _line_coords(road: RoadRecord) -> tuple[tuple[float, float], ...]:
    geometry = road.geometry
    if hasattr(geometry, "coords"):
        return tuple((float(x), float(y)) for x, y, *_ in geometry.coords)
    if hasattr(geometry, "geoms"):
        for part in geometry.geoms:
            if hasattr(part, "coords"):
                coords = tuple((float(x), float(y)) for x, y, *_ in part.coords)
                if coords:
                    return coords
    return tuple()


def _node_xy(node_id: str, nodes: dict[str, NodeRecord]) -> tuple[float, float] | None:
    node = nodes.get(node_id)
    if not node:
        return None
    point = node.geometry
    if not hasattr(point, "x") or not hasattr(point, "y"):
        return None
    return float(point.x), float(point.y)


def _angle_between(start: tuple[float, float], end: tuple[float, float]) -> float | None:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return None
    return math.degrees(math.atan2(dy, dx)) % 360.0


def _angular_distance(a: float | None, b: float | None) -> float | None:
    if a is None or b is None:
        return None
    delta = abs((a - b + 180.0) % 360.0 - 180.0)
    return min(delta, 360.0 - delta)


def _trend_towards_group(road: RoadRecord, group_id: str, nodes: dict[str, NodeRecord]) -> float | None:
    start_group, end_group = _road_endpoint_groups(road, nodes)
    coords = _line_coords(road)
    if len(coords) >= 2:
        if end_group == group_id:
            return _angle_between(coords[-2], coords[-1])
        if start_group == group_id:
            return _angle_between(coords[1], coords[0])
    if end_group == group_id:
        start_xy = _node_xy(road.snodeid, nodes)
        end_xy = _node_xy(road.enodeid, nodes)
        return _angle_between(start_xy, end_xy) if start_xy and end_xy else None
    if start_group == group_id:
        start_xy = _node_xy(road.enodeid, nodes)
        end_xy = _node_xy(road.snodeid, nodes)
        return _angle_between(start_xy, end_xy) if start_xy and end_xy else None
    return None


def _trend_from_group(road: RoadRecord, group_id: str, nodes: dict[str, NodeRecord]) -> float | None:
    start_group, end_group = _road_endpoint_groups(road, nodes)
    coords = _line_coords(road)
    if len(coords) >= 2:
        if start_group == group_id:
            return _angle_between(coords[0], coords[1])
        if end_group == group_id:
            return _angle_between(coords[-1], coords[-2])
    if start_group == group_id:
        start_xy = _node_xy(road.snodeid, nodes)
        end_xy = _node_xy(road.enodeid, nodes)
        return _angle_between(start_xy, end_xy) if start_xy and end_xy else None
    if end_group == group_id:
        start_xy = _node_xy(road.enodeid, nodes)
        end_xy = _node_xy(road.snodeid, nodes)
        return _angle_between(start_xy, end_xy) if start_xy and end_xy else None
    return None


def _relaxed_continuation_options(
    *,
    group_id: str,
    previous_road_id: str,
    candidate_road_ids: list[str],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    seen_groups: set[str],
) -> tuple[tuple[RelaxedContinuationOption, ...], tuple[RelaxedContinuationOption, ...]]:
    incoming_angle = _trend_towards_group(roads[previous_road_id], group_id, nodes) if previous_road_id in roads else None
    non_loop_options: list[RelaxedContinuationOption] = []
    loop_options: list[RelaxedContinuationOption] = []
    for road_id in candidate_road_ids:
        next_group_id = _other_group_for_road(roads[road_id], group_id, nodes)
        if next_group_id is None:
            continue
        outgoing_angle = _trend_from_group(roads[road_id], group_id, nodes)
        option = RelaxedContinuationOption(
            road_id=road_id,
            next_group_id=next_group_id,
            angle_delta=_angular_distance(incoming_angle, outgoing_angle),
        )
        if next_group_id in seen_groups:
            loop_options.append(option)
        else:
            non_loop_options.append(option)
    non_loop_options.sort(key=lambda item: (999.0 if item.angle_delta is None else item.angle_delta, item.road_id))
    loop_options.sort(key=lambda item: (999.0 if item.angle_delta is None else item.angle_delta, item.road_id))
    return tuple(non_loop_options), tuple(loop_options)


def _select_relaxed_continuation(options: tuple[RelaxedContinuationOption, ...]) -> RelaxedContinuationOption | None:
    if not options:
        return None
    best = options[0]
    if best.angle_delta is not None and best.angle_delta > RELAXED_MAINLINE_MAX_ANGLE_DEG:
        return None
    if len(options) == 1:
        return best
    second = options[1]
    if best.angle_delta is None or second.angle_delta is None:
        return None
    if second.angle_delta - best.angle_delta < RELAXED_MAINLINE_MIN_MARGIN_DEG:
        return None
    return best


def _probe_relaxed_terminal(
    *,
    option: RelaxedContinuationOption,
    start_group_id: str,
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
    seen_groups: set[str],
    max_steps: int = 6,
) -> RelaxedProbeResult | None:
    road_ids = [option.road_id]
    node_ids: list[str] = []
    previous_road_id = option.road_id
    group_id = option.next_group_id
    seen = set(seen_groups) | {start_group_id}
    for step in range(max_steps):
        if group_id in seen:
            return None
        seen.add(group_id)
        for node_id in _node_ids_for_group(group_id, groups):
            if node_id not in node_ids:
                node_ids.append(node_id)
        semantic_candidate = _kind_category(group_id, groups, nodes) in {"kind_4", "kind_2048"}
        if semantic_candidate and _semantic_terminal_is_strong(
            group_id=group_id,
            groups=groups,
            nodes=nodes,
            roads=roads,
            excluded_road_ids=excluded_road_ids,
            internal_road_ids=internal_road_ids,
        ):
            return RelaxedProbeResult(
                terminal_group_id=group_id,
                terminal_type="semantic_junction",
                road_ids=tuple(road_ids),
                node_ids=tuple(node_ids),
            )
        incident_ids = _incident_validation_roads(
            group_id=group_id,
            nodes=nodes,
            roads=roads,
            excluded_road_ids=excluded_road_ids,
            internal_road_ids=internal_road_ids,
        )
        candidates = [road_id for road_id in incident_ids if road_id != previous_road_id]
        if not candidates:
            return RelaxedProbeResult(
                terminal_group_id=group_id,
                terminal_type="semantic_junction" if semantic_candidate else "terminal_boundary",
                road_ids=tuple(road_ids),
                node_ids=tuple(node_ids),
            )
        non_loop_options, loop_options = _relaxed_continuation_options(
            group_id=group_id,
            previous_road_id=previous_road_id,
            candidate_road_ids=candidates,
            nodes=nodes,
            roads=roads,
            seen_groups=seen,
        )
        selected = _select_relaxed_continuation(non_loop_options)
        if selected is None:
            if semantic_candidate:
                return RelaxedProbeResult(
                    terminal_group_id=group_id,
                    terminal_type="semantic_junction",
                    road_ids=tuple(road_ids),
                    node_ids=tuple(node_ids),
                )
            if loop_options and not non_loop_options:
                return None
            return None
        road_ids.append(selected.road_id)
        road = roads[selected.road_id]
        for node_id in (road.snodeid, road.enodeid):
            if node_id not in node_ids:
                node_ids.append(node_id)
        previous_road_id = selected.road_id
        group_id = selected.next_group_id
    return None


def _parallel_convergence_probe(
    *,
    group_id: str,
    options: tuple[RelaxedContinuationOption, ...],
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
    seen_groups: set[str],
) -> RelaxedProbeResult | None:
    if len(options) < 2:
        return None
    best_delta = options[0].angle_delta
    if best_delta is None or best_delta > RELAXED_MAINLINE_MAX_ANGLE_DEG:
        return None
    probe_options = tuple(
        option
        for option in options
        if option.angle_delta is not None
        and option.angle_delta <= RELAXED_MAINLINE_MAX_ANGLE_DEG
        and option.angle_delta - best_delta <= RELAXED_MAINLINE_MIN_MARGIN_DEG
    )
    if len(probe_options) < 2:
        return None
    probes = tuple(
        result
        for result in (
            _probe_relaxed_terminal(
                option=option,
                start_group_id=group_id,
                groups=groups,
                nodes=nodes,
                roads=roads,
                excluded_road_ids=excluded_road_ids,
                internal_road_ids=internal_road_ids,
                seen_groups=seen_groups,
            )
            for option in probe_options
        )
        if result is not None
    )
    if len(probes) != len(probe_options):
        return None
    terminal_ids = {probe.terminal_group_id for probe in probes}
    terminal_types = {probe.terminal_type for probe in probes}
    if len(terminal_ids) != 1 or terminal_types != {"semantic_junction"}:
        return None
    return RelaxedProbeResult(
        terminal_group_id=next(iter(terminal_ids)),
        terminal_type="semantic_junction",
        road_ids=tuple(sorted({road_id for probe in probes for road_id in probe.road_ids})),
        node_ids=tuple(sorted({node_id for probe in probes for node_id in probe.node_ids})),
    )


def _unique_nearby_strong_terminal(
    *,
    start_group_id: str,
    current_group_id: str,
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
    max_hops: int = 3,
) -> RelaxedProbeResult | None:
    """Resolve weak transition terminals to a unique nearby strong semantic junction.

    This is validation-only topology evidence. It does not create new topology,
    use RoadNextRoad, or replace the original ArmTrace decision.
    """
    if _semantic_terminal_is_strong(
        group_id=start_group_id,
        groups=groups,
        nodes=nodes,
        roads=roads,
        excluded_road_ids=excluded_road_ids,
        internal_road_ids=internal_road_ids,
    ):
        return RelaxedProbeResult(
            terminal_group_id=start_group_id,
            terminal_type="semantic_junction",
            road_ids=tuple(),
            node_ids=_node_ids_for_group(start_group_id, groups),
        )

    frontier: list[tuple[str, tuple[str, ...], tuple[str, ...], frozenset[str]]] = [
        (start_group_id, tuple(), tuple(_node_ids_for_group(start_group_id, groups)), frozenset({current_group_id, start_group_id}))
    ]
    for _hop in range(max_hops):
        next_frontier: list[tuple[str, tuple[str, ...], tuple[str, ...], frozenset[str]]] = []
        strong_hits: list[RelaxedProbeResult] = []
        for group_id, path_roads, path_nodes, seen_groups in frontier:
            incident_ids = _incident_validation_roads(
                group_id=group_id,
                nodes=nodes,
                roads=roads,
                excluded_road_ids=excluded_road_ids,
                internal_road_ids=internal_road_ids,
            )
            for road_id in incident_ids:
                road = roads[road_id]
                next_group_id = _other_group_for_road(road, group_id, nodes)
                if not next_group_id or next_group_id in seen_groups:
                    continue
                next_roads = path_roads + (road_id,)
                next_nodes = tuple(
                    dict.fromkeys(
                        path_nodes
                        + tuple(node_id for node_id in (road.snodeid, road.enodeid) if node_id)
                        + _node_ids_for_group(next_group_id, groups)
                    )
                )
                if _semantic_terminal_is_strong(
                    group_id=next_group_id,
                    groups=groups,
                    nodes=nodes,
                    roads=roads,
                    excluded_road_ids=excluded_road_ids,
                    internal_road_ids=internal_road_ids,
                ):
                    strong_hits.append(
                        RelaxedProbeResult(
                            terminal_group_id=next_group_id,
                            terminal_type="semantic_junction",
                            road_ids=next_roads,
                            node_ids=next_nodes,
                        )
                    )
                    continue
                next_frontier.append((next_group_id, next_roads, next_nodes, frozenset(set(seen_groups) | {next_group_id})))
        terminal_ids = {hit.terminal_group_id for hit in strong_hits}
        if len(terminal_ids) == 1:
            terminal_id = next(iter(terminal_ids))
            return RelaxedProbeResult(
                terminal_group_id=terminal_id,
                terminal_type="semantic_junction",
                road_ids=tuple(sorted({road_id for hit in strong_hits for road_id in hit.road_ids})),
                node_ids=tuple(sorted({node_id for hit in strong_hits for node_id in hit.node_ids})),
            )
        if len(terminal_ids) > 1:
            return None
        frontier = next_frontier
    return None


def _refine_result_terminal(
    *,
    result: RelaxedTraceResult,
    current_group_id: str,
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
) -> RelaxedTraceResult:
    if not result.terminal_group_id:
        return result
    if result.terminal_type == "semantic_junction" and _semantic_terminal_is_strong(
        group_id=result.terminal_group_id,
        groups=groups,
        nodes=nodes,
        roads=roads,
        excluded_road_ids=excluded_road_ids,
        internal_road_ids=internal_road_ids,
    ):
        return result
    refined = _unique_nearby_strong_terminal(
        start_group_id=result.terminal_group_id,
        current_group_id=current_group_id,
        groups=groups,
        nodes=nodes,
        roads=roads,
        excluded_road_ids=excluded_road_ids,
        internal_road_ids=internal_road_ids,
    )
    if refined is None or refined.terminal_group_id == result.terminal_group_id:
        return result
    return replace(
        result,
        terminal_group_id=refined.terminal_group_id,
        terminal_type=refined.terminal_type,
        road_ids=tuple(dict.fromkeys(result.road_ids + refined.road_ids)),
        node_ids=tuple(dict.fromkeys(result.node_ids + refined.node_ids)),
        risk_flags=tuple(sorted(set(result.risk_flags + ("relaxed_trace_weak_terminal_refined",)))),
        issue_flags=tuple(
            flag for flag in result.issue_flags if flag not in {"relaxed_trace_multiple_candidates", "relaxed_trace_step_limit_reached"}
        ),
    )


def _path_to_consensus_target(
    *,
    start_group_id: str,
    target_group_id: str,
    current_group_id: str,
    final_arm_road_ids: set[str],
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
    max_hops: int = 12,
) -> RelaxedProbeResult | None:
    if start_group_id == target_group_id:
        return RelaxedProbeResult(
            terminal_group_id=target_group_id,
            terminal_type="semantic_junction",
            road_ids=tuple(),
            node_ids=_node_ids_for_group(target_group_id, groups),
        )
    frontier: list[tuple[str, tuple[str, ...], tuple[str, ...], frozenset[str], int]] = [
        (start_group_id, tuple(), tuple(_node_ids_for_group(start_group_id, groups)), frozenset({start_group_id}), 0)
    ]
    for _hop in range(max_hops):
        next_frontier: list[tuple[str, tuple[str, ...], tuple[str, ...], frozenset[str], int]] = []
        for group_id, path_roads, path_nodes, seen_groups, current_cross_count in frontier:
            incident_ids = _incident_validation_roads(
                group_id=group_id,
                nodes=nodes,
                roads=roads,
                excluded_road_ids=excluded_road_ids,
                internal_road_ids=internal_road_ids,
            )
            for road_id in incident_ids:
                road = roads[road_id]
                next_group_id = _other_group_for_road(road, group_id, nodes)
                if not next_group_id:
                    continue
                next_current_cross_count = current_cross_count
                if next_group_id == current_group_id or group_id == current_group_id:
                    if road_id not in final_arm_road_ids or current_cross_count >= 2:
                        continue
                    next_current_cross_count += 1
                elif next_group_id in seen_groups:
                    continue
                next_roads = path_roads + (road_id,)
                next_nodes = tuple(
                    dict.fromkeys(
                        path_nodes
                        + tuple(node_id for node_id in (road.snodeid, road.enodeid) if node_id)
                        + _node_ids_for_group(next_group_id, groups)
                    )
                )
                if next_group_id == target_group_id:
                    return RelaxedProbeResult(
                        terminal_group_id=target_group_id,
                        terminal_type="semantic_junction",
                        road_ids=next_roads,
                        node_ids=next_nodes,
                    )
                next_seen = seen_groups if next_group_id == current_group_id else frozenset(set(seen_groups) | {next_group_id})
                next_frontier.append((next_group_id, next_roads, next_nodes, next_seen, next_current_cross_count))
        frontier = next_frontier
    return None


def _strong_terminal_target(
    *,
    result: RelaxedTraceResult,
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
) -> str | None:
    if not result.terminal_group_id:
        return None
    if not _semantic_terminal_is_strong(
        group_id=result.terminal_group_id,
        groups=groups,
        nodes=nodes,
        roads=roads,
        excluded_road_ids=excluded_road_ids,
        internal_road_ids=internal_road_ids,
    ):
        return None
    return result.terminal_group_id


def _terminal_strength(
    *,
    group_id: str,
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
) -> int:
    return len(
        _incident_validation_roads(
            group_id=group_id,
            nodes=nodes,
            roads=roads,
            excluded_road_ids=excluded_road_ids,
            internal_road_ids=internal_road_ids,
        )
    )


def _dominant_terminal_target(
    *,
    targets: set[str],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
) -> str | None:
    if len(targets) < 2:
        return next(iter(targets), None)
    ranked = sorted(
        (
            (
                _terminal_strength(
                    group_id=target,
                    nodes=nodes,
                    roads=roads,
                    excluded_road_ids=excluded_road_ids,
                    internal_road_ids=internal_road_ids,
                ),
                target,
            )
            for target in targets
        ),
        reverse=True,
    )
    if len(ranked) < 2 or ranked[0][0] - ranked[1][0] < 2:
        return None
    return ranked[0][1]


def _final_arm_member_road_ids(final_arm: FinalArm) -> tuple[str, ...]:
    value = final_arm.initial_arm.get("member_road_ids", tuple())
    if isinstance(value, (tuple, list)):
        return tuple(str(item) for item in value)
    return tuple()


def _refine_results_to_consensus_target(
    *,
    results_by_initial: dict[str, list[RelaxedTraceResult]],
    initial_by_id: dict[str, InitialArm],
    final_arm: FinalArm,
    current_group_id: str,
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
) -> dict[str, list[RelaxedTraceResult]]:
    original_strong_targets = {
        target
        for results in results_by_initial.values()
        for result in results
        if "relaxed_trace_weak_terminal_refined" not in result.risk_flags
        for target in (
            _strong_terminal_target(
                result=result,
                groups=groups,
                nodes=nodes,
                roads=roads,
                excluded_road_ids=excluded_road_ids,
                internal_road_ids=internal_road_ids,
            ),
        )
        if target
    }
    refined_strong_targets = {
        target
        for results in results_by_initial.values()
        for result in results
        for target in (
            _strong_terminal_target(
                result=result,
                groups=groups,
                nodes=nodes,
                roads=roads,
                excluded_road_ids=excluded_road_ids,
                internal_road_ids=internal_road_ids,
            ),
        )
        if target
    }
    if len(original_strong_targets) == 1:
        target_group_id = next(iter(original_strong_targets))
    elif len(original_strong_targets) > 1:
        target_group_id = _dominant_terminal_target(
            targets=original_strong_targets,
            nodes=nodes,
            roads=roads,
            excluded_road_ids=excluded_road_ids,
            internal_road_ids=internal_road_ids,
        )
        if target_group_id is None:
            return results_by_initial
    elif not original_strong_targets and len(refined_strong_targets) == 1:
        target_group_id = next(iter(refined_strong_targets))
    else:
        return results_by_initial

    final_arm_road_ids = set(_final_arm_member_road_ids(final_arm))
    updated: dict[str, list[RelaxedTraceResult]] = {}
    for initial_id, results in results_by_initial.items():
        arm = initial_by_id.get(initial_id)
        start_group_id = arm.terminal_junction_id if arm and arm.terminal_junction_id else None
        updated_results: list[RelaxedTraceResult] = []
        for result in results:
            if result.terminal_group_id == target_group_id:
                updated_results.append(
                    replace(
                        result,
                        terminal_type="semantic_junction",
                        risk_flags=tuple(
                            flag
                            for flag in result.risk_flags
                            if flag not in {"relaxed_trace_multiple_candidates", "relaxed_trace_step_limit_reached"}
                        ),
                        issue_flags=tuple(
                            flag
                            for flag in result.issue_flags
                            if flag not in {"relaxed_trace_multiple_candidates", "relaxed_trace_step_limit_reached"}
                        ),
                    )
                )
                continue
            if not start_group_id:
                updated_results.append(result)
                continue
            path = _path_to_consensus_target(
                start_group_id=start_group_id,
                target_group_id=target_group_id,
                current_group_id=current_group_id,
                final_arm_road_ids=final_arm_road_ids,
                groups=groups,
                nodes=nodes,
                roads=roads,
                excluded_road_ids=excluded_road_ids,
                internal_road_ids=internal_road_ids,
            )
            if path is None:
                updated_results.append(result)
                continue
            updated_results.append(
                replace(
                    result,
                    terminal_group_id=target_group_id,
                    terminal_type="semantic_junction",
                    road_ids=tuple(dict.fromkeys(result.road_ids + path.road_ids)),
                    node_ids=tuple(dict.fromkeys(result.node_ids + path.node_ids)),
                    risk_flags=tuple(
                        sorted(
                            set(
                                flag
                                for flag in result.risk_flags + ("relaxed_trace_consensus_target_convergence",)
                                if flag not in {"relaxed_trace_multiple_candidates", "relaxed_trace_step_limit_reached"}
                            )
                        )
                    ),
                    issue_flags=tuple(
                        flag
                        for flag in result.issue_flags
                        if flag not in {"relaxed_trace_multiple_candidates", "relaxed_trace_step_limit_reached"}
                    ),
                )
            )
        updated[initial_id] = updated_results
    return updated


def _incident_validation_roads(
    *,
    group_id: str,
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
) -> tuple[str, ...]:
    incident: list[str] = []
    for road_id in _validation_incident_road_ids_by_group(roads, nodes).get(group_id, tuple()):
        road = roads[road_id]
        if road_id in excluded_road_ids or road_id in internal_road_ids or is_advance_right_turn_road(road):
            continue
        incident.append(road_id)
    return tuple(sorted(incident))


def _terminal_from_trace(trace: ArmTrace, arm: InitialArm, nodes: dict[str, NodeRecord]) -> str | None:
    if arm.terminal_junction_id:
        return arm.terminal_junction_id
    if trace.traced_node_ids:
        last_node_id = trace.traced_node_ids[-1]
        return _semantic_group_id(nodes.get(last_node_id), last_node_id)
    return None


def _relaxed_trace(
    *,
    validation_id: str,
    trace_index: int,
    arm: InitialArm,
    trace: ArmTrace,
    current_group_id: str,
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
    max_steps: int = 8,
) -> RelaxedTraceResult:
    relaxed_trace_id = f"{validation_id}_relaxed_{trace_index:02d}_{arm.initial_arm_id}"
    road_ids = list(trace.traced_road_ids)
    node_ids = list(trace.traced_node_ids)
    risk_flags: list[str] = []
    issue_flags: list[str] = []
    terminal_group_id = _terminal_from_trace(trace, arm, nodes)
    terminal_type = trace.stop_type

    if trace.stop_type in NON_RELAXABLE_STOP_TYPES:
        if trace.stop_type == "patch_boundary":
            issue_flags.append("relaxed_trace_patch_boundary")
        elif trace.stop_type == "loop_to_current_junction":
            issue_flags.append("relaxed_trace_loop")
        else:
            issue_flags.append("relaxed_trace_missing_node")
        return RelaxedTraceResult(
            relaxed_trace_id=relaxed_trace_id,
            initial_arm_id=arm.initial_arm_id,
            terminal_group_id=terminal_group_id,
            terminal_type=terminal_type,
            road_ids=tuple(road_ids),
            node_ids=tuple(node_ids),
            risk_flags=tuple(sorted(set(risk_flags + issue_flags))),
            issue_flags=tuple(sorted(set(issue_flags))),
        )

    if trace.stop_type not in RELAXABLE_STOP_TYPES:
        return RelaxedTraceResult(
            relaxed_trace_id=relaxed_trace_id,
            initial_arm_id=arm.initial_arm_id,
            terminal_group_id=terminal_group_id,
            terminal_type=terminal_type,
            road_ids=tuple(road_ids),
            node_ids=tuple(node_ids),
            risk_flags=tuple(),
            issue_flags=tuple(),
        )

    if not terminal_group_id or not road_ids:
        issue_flags.append("relaxed_trace_missing_node")
        return RelaxedTraceResult(
            relaxed_trace_id=relaxed_trace_id,
            initial_arm_id=arm.initial_arm_id,
            terminal_group_id=terminal_group_id,
            terminal_type="unresolved",
            road_ids=tuple(road_ids),
            node_ids=tuple(node_ids),
            risk_flags=tuple(sorted(set(issue_flags))),
            issue_flags=tuple(sorted(set(issue_flags))),
        )

    group_id = terminal_group_id
    previous_road_id = road_ids[-1]
    seen_groups = {current_group_id}
    if group_id != current_group_id:
        seen_groups.add(group_id)

    for step in range(max_steps):
        for node_id in _node_ids_for_group(group_id, groups):
            if node_id not in node_ids:
                node_ids.append(node_id)
        semantic_terminal_candidate = _kind_category(group_id, groups, nodes) in {"kind_4", "kind_2048"} and (
            step > 0 or trace.stop_type == "semantic_boundary"
        )
        incident_ids = _incident_validation_roads(
            group_id=group_id,
            nodes=nodes,
            roads=roads,
            excluded_road_ids=excluded_road_ids,
            internal_road_ids=internal_road_ids,
        )
        if semantic_terminal_candidate and _semantic_terminal_is_strong(
            group_id=group_id,
            groups=groups,
            nodes=nodes,
            roads=roads,
            excluded_road_ids=excluded_road_ids,
            internal_road_ids=internal_road_ids,
        ):
            return RelaxedTraceResult(
                relaxed_trace_id=relaxed_trace_id,
                initial_arm_id=arm.initial_arm_id,
                terminal_group_id=group_id,
                terminal_type="semantic_junction",
                road_ids=tuple(road_ids),
                node_ids=tuple(node_ids),
                risk_flags=tuple(sorted(set(risk_flags))),
                issue_flags=tuple(sorted(set(issue_flags))),
            )
        candidates = [road_id for road_id in incident_ids if road_id != previous_road_id]
        if not candidates:
            terminal_type = "semantic_junction" if semantic_terminal_candidate else ("dead_end" if trace.stop_type == "dead_end" else "terminal_boundary")
            if trace.stop_type == "dead_end":
                risk_flags.append("relaxed_trace_dead_end_terminal")
            return RelaxedTraceResult(
                relaxed_trace_id=relaxed_trace_id,
                initial_arm_id=arm.initial_arm_id,
                terminal_group_id=group_id,
                terminal_type=terminal_type,
                road_ids=tuple(road_ids),
                node_ids=tuple(node_ids),
                risk_flags=tuple(sorted(set(risk_flags))),
                issue_flags=tuple(sorted(set(issue_flags))),
            )
        non_loop_options, loop_options = _relaxed_continuation_options(
            group_id=group_id,
            previous_road_id=previous_road_id,
            candidate_road_ids=candidates,
            nodes=nodes,
            roads=roads,
            seen_groups=seen_groups,
        )
        if not non_loop_options and not loop_options:
            issue_flags.append("relaxed_trace_missing_node")
            return RelaxedTraceResult(
                relaxed_trace_id=relaxed_trace_id,
                initial_arm_id=arm.initial_arm_id,
                terminal_group_id=group_id,
                terminal_type="unresolved",
                road_ids=tuple(road_ids),
                node_ids=tuple(node_ids),
                risk_flags=tuple(sorted(set(risk_flags + issue_flags))),
                issue_flags=tuple(sorted(set(issue_flags))),
            )
        selected = _select_relaxed_continuation(non_loop_options)
        if selected is None:
            convergence_probe = (
                _parallel_convergence_probe(
                    group_id=group_id,
                    options=non_loop_options,
                    groups=groups,
                    nodes=nodes,
                    roads=roads,
                    excluded_road_ids=excluded_road_ids,
                    internal_road_ids=internal_road_ids,
                    seen_groups=seen_groups,
                )
                if semantic_terminal_candidate
                else None
            )
            if convergence_probe is not None:
                for road_id in convergence_probe.road_ids:
                    if road_id not in road_ids:
                        road_ids.append(road_id)
                for node_id in convergence_probe.node_ids:
                    if node_id not in node_ids:
                        node_ids.append(node_id)
                return RelaxedTraceResult(
                    relaxed_trace_id=relaxed_trace_id,
                    initial_arm_id=arm.initial_arm_id,
                    terminal_group_id=convergence_probe.terminal_group_id,
                    terminal_type=convergence_probe.terminal_type,
                    road_ids=tuple(road_ids),
                    node_ids=tuple(node_ids),
                    risk_flags=tuple(sorted(set(risk_flags + ["relaxed_trace_parallel_convergence"]))),
                    issue_flags=tuple(sorted(set(issue_flags))),
                )
            if semantic_terminal_candidate and not non_loop_options and loop_options:
                return RelaxedTraceResult(
                    relaxed_trace_id=relaxed_trace_id,
                    initial_arm_id=arm.initial_arm_id,
                    terminal_group_id=group_id,
                    terminal_type="semantic_junction",
                    road_ids=tuple(road_ids),
                    node_ids=tuple(node_ids),
                    risk_flags=tuple(sorted(set(risk_flags))),
                    issue_flags=tuple(sorted(set(issue_flags))),
                )
            if semantic_terminal_candidate and non_loop_options:
                return RelaxedTraceResult(
                    relaxed_trace_id=relaxed_trace_id,
                    initial_arm_id=arm.initial_arm_id,
                    terminal_group_id=group_id,
                    terminal_type="semantic_junction",
                    road_ids=tuple(road_ids),
                    node_ids=tuple(node_ids),
                    risk_flags=tuple(sorted(set(risk_flags))),
                    issue_flags=tuple(sorted(set(issue_flags))),
                )
            issue_flags.append("relaxed_trace_loop" if loop_options and not non_loop_options else "relaxed_trace_multiple_candidates")
            terminal_type = "loop" if loop_options and not non_loop_options else ("semantic_junction" if semantic_terminal_candidate else "ambiguous_boundary")
            return RelaxedTraceResult(
                relaxed_trace_id=relaxed_trace_id,
                initial_arm_id=arm.initial_arm_id,
                terminal_group_id=group_id,
                terminal_type=terminal_type,
                road_ids=tuple(road_ids),
                node_ids=tuple(node_ids),
                risk_flags=tuple(sorted(set(risk_flags + issue_flags))),
                issue_flags=tuple(sorted(set(issue_flags))),
            )
        next_road_id, next_group_id = selected.road_id, selected.next_group_id
        road_ids.append(next_road_id)
        road = roads[next_road_id]
        for node_id in (road.snodeid, road.enodeid):
            if node_id not in node_ids:
                node_ids.append(node_id)
        previous_road_id = next_road_id
        group_id = next_group_id
        seen_groups.add(group_id)

    issue_flags.append("relaxed_trace_step_limit_reached")
    return RelaxedTraceResult(
        relaxed_trace_id=relaxed_trace_id,
        initial_arm_id=arm.initial_arm_id,
        terminal_group_id=group_id,
        terminal_type="step_limit",
        road_ids=tuple(road_ids),
        node_ids=tuple(node_ids),
        risk_flags=tuple(sorted(set(risk_flags + issue_flags))),
        issue_flags=tuple(sorted(set(issue_flags))),
    )


def _validation_status_for(results_by_initial: dict[str, list[RelaxedTraceResult]]) -> tuple[str, str, str, str, tuple[str, ...], tuple[str, ...]]:
    issue_flags = tuple(sorted({flag for results in results_by_initial.values() for result in results for flag in result.issue_flags}))
    risk_flags = tuple(sorted({flag for results in results_by_initial.values() for result in results for flag in result.risk_flags}))
    terminal_sets = {
        initial_id: {result.terminal_group_id for result in results if result.terminal_group_id}
        for initial_id, results in results_by_initial.items()
    }
    if not terminal_sets or any(not terminals for terminals in terminal_sets.values()):
        return "unvalidated", "no_convergence", "low", "relaxed trace terminal missing", risk_flags, tuple(sorted(set(issue_flags + ("final_arm_validation_unvalidated",))))
    if any(len(terminals) > 1 for terminals in terminal_sets.values()):
        return "unvalidated", "no_convergence", "low", "one source InitialArm has multiple relaxed terminals", risk_flags, tuple(sorted(set(issue_flags + ("final_arm_validation_unvalidated", "relaxed_trace_multiple_candidates"))))
    unique_terminals = {next(iter(terminals)) for terminals in terminal_sets.values()}
    terminal_types = {result.terminal_type for results in results_by_initial.values() for result in results}
    weak_terminal_types = {"ambiguous_boundary", "dead_end", "terminal_boundary", "step_limit", "unresolved", "loop"}
    if len(unique_terminals) > 1:
        if terminal_types & weak_terminal_types:
            return (
                "unvalidated",
                "no_convergence",
                "low",
                "relaxed traces do not converge to a common strong semantic terminal",
                risk_flags,
                tuple(sorted(set(issue_flags + ("final_arm_validation_unvalidated", "relaxed_trace_no_convergence")))),
            )
        return "conflict", "conflicting_terminals", "none", "source InitialArms converge to different relaxed terminals", risk_flags, tuple(sorted(set(issue_flags + ("final_arm_validation_conflict",))))
    weak_terminal = bool(terminal_types & {"dead_end", "terminal_boundary", "step_limit", "unresolved"})
    weak_issue = bool(issue_flags)
    if weak_terminal or weak_issue:
        convergence = "partial_same_corridor" if issue_flags else "same_terminal_boundary"
        return "weak_validated", convergence, "medium", "relaxed traces share terminal with weak evidence", risk_flags, tuple(sorted(set(issue_flags + ("final_arm_validation_weak",))))
    return "validated", "same_semantic_junction", "high", "relaxed traces converge to the same semantic terminal", risk_flags, issue_flags


def build_final_arm_validation(
    *,
    dataset: str,
    junction_id: str,
    current_group_id: str,
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    initial_arms: tuple[InitialArm, ...],
    final_arms: tuple[FinalArm, ...],
    traces: tuple[ArmTrace, ...],
    excluded_road_ids: set[str],
    internal_road_ids: set[str],
) -> FinalArmValidationBuildResult:
    initial_by_id = {arm.initial_arm_id: arm for arm in initial_arms}
    traces_by_initial: dict[str, list[ArmTrace]] = {}
    for trace in traces:
        if trace.assigned_initial_arm_id:
            traces_by_initial.setdefault(trace.assigned_initial_arm_id, []).append(trace)

    validations: list[FinalArmValidation] = []
    issues: list[dict[str, Any]] = []
    final_updates: list[FinalArm] = []
    for index, final_arm in enumerate(final_arms, start=1):
        validation_id = f"{dataset.lower()}_{junction_id}_final_arm_validation_{index:04d}"
        requires_validation = len(final_arm.source_initial_arm_ids) > 1
        if not requires_validation:
            validation = FinalArmValidation(
                validation_id=validation_id,
                dataset=dataset,
                current_junction_id=junction_id,
                final_arm_id=final_arm.final_arm_id,
                merge_status=final_arm.merge_status,
                source_initial_arm_ids=final_arm.source_initial_arm_ids,
                validation_status="not_required",
                convergence_status="not_evaluated",
                relaxed_trace_terminal_junction_ids=tuple(
                    sorted(
                        {
                            initial_by_id[arm_id].terminal_junction_id
                            for arm_id in final_arm.source_initial_arm_ids
                            if arm_id in initial_by_id and initial_by_id[arm_id].terminal_junction_id
                        }
                    )
                ),
                relaxed_trace_terminal_types=tuple(
                    sorted({initial_by_id[arm_id].terminal_type for arm_id in final_arm.source_initial_arm_ids if arm_id in initial_by_id})
                ),
                relaxed_trace_ids=tuple(),
                relaxed_trace_road_ids_by_initial_arm={},
                relaxed_trace_node_ids_by_initial_arm={},
                validation_reason="single source InitialArm does not require fallback validation",
                confidence="high",
                risk_flags=tuple(),
                issue_flags=tuple(),
            )
            validations.append(validation)
            final_updates.append(
                replace(
                    final_arm,
                    validation_status=validation.validation_status,
                    validation_id=validation.validation_id,
                    validation_confidence=validation.confidence,
                    validation_risk_flags=validation.risk_flags,
                )
            )
            continue

        results_by_initial: dict[str, list[RelaxedTraceResult]] = {}
        for source_index, initial_id in enumerate(final_arm.source_initial_arm_ids, start=1):
            arm = initial_by_id.get(initial_id)
            arm_traces = traces_by_initial.get(initial_id, [])
            if not arm or not arm_traces:
                synthetic = RelaxedTraceResult(
                    relaxed_trace_id=f"{validation_id}_relaxed_{source_index:02d}_{initial_id}",
                    initial_arm_id=initial_id,
                    terminal_group_id=arm.terminal_junction_id if arm else None,
                    terminal_type="unresolved",
                    road_ids=tuple(arm.member_road_ids if arm else tuple()),
                    node_ids=tuple(arm.terminal_member_node_ids if arm else tuple()),
                    risk_flags=("relaxed_trace_missing_node",),
                    issue_flags=("relaxed_trace_missing_node",),
                )
                results_by_initial[initial_id] = [synthetic]
                continue
            results_by_initial[initial_id] = [
                _refine_result_terminal(
                    result=_relaxed_trace(
                        validation_id=validation_id,
                        trace_index=source_index * 10 + trace_offset,
                        arm=arm,
                        trace=trace,
                        current_group_id=current_group_id,
                        groups=groups,
                        nodes=nodes,
                        roads=roads,
                        excluded_road_ids=excluded_road_ids,
                        internal_road_ids=internal_road_ids,
                    ),
                    current_group_id=current_group_id,
                    groups=groups,
                    nodes=nodes,
                    roads=roads,
                    excluded_road_ids=excluded_road_ids,
                    internal_road_ids=internal_road_ids,
                )
                for trace_offset, trace in enumerate(arm_traces, start=1)
            ]

        results_by_initial = _refine_results_to_consensus_target(
            results_by_initial=results_by_initial,
            initial_by_id=initial_by_id,
            final_arm=final_arm,
            current_group_id=current_group_id,
            groups=groups,
            nodes=nodes,
            roads=roads,
            excluded_road_ids=excluded_road_ids,
            internal_road_ids=internal_road_ids,
        )
        status, convergence, confidence, reason, risk_flags, issue_flags = _validation_status_for(results_by_initial)
        terminal_ids = tuple(
            sorted({str(result.terminal_group_id) for results in results_by_initial.values() for result in results if result.terminal_group_id})
        )
        terminal_types = tuple(sorted({result.terminal_type for results in results_by_initial.values() for result in results}))
        relaxed_trace_ids = tuple(result.relaxed_trace_id for results in results_by_initial.values() for result in results)
        road_ids_by_initial = {
            initial_id: tuple(sorted({road_id for result in results for road_id in result.road_ids}))
            for initial_id, results in results_by_initial.items()
        }
        node_ids_by_initial = {
            initial_id: tuple(sorted({node_id for result in results for node_id in result.node_ids}))
            for initial_id, results in results_by_initial.items()
        }
        validation = FinalArmValidation(
            validation_id=validation_id,
            dataset=dataset,
            current_junction_id=junction_id,
            final_arm_id=final_arm.final_arm_id,
            merge_status=final_arm.merge_status,
            source_initial_arm_ids=final_arm.source_initial_arm_ids,
            validation_status=status,
            convergence_status=convergence,
            relaxed_trace_terminal_junction_ids=terminal_ids,
            relaxed_trace_terminal_types=terminal_types,
            relaxed_trace_ids=relaxed_trace_ids,
            relaxed_trace_road_ids_by_initial_arm=road_ids_by_initial,
            relaxed_trace_node_ids_by_initial_arm=node_ids_by_initial,
            validation_reason=reason,
            confidence=confidence,
            risk_flags=risk_flags,
            issue_flags=issue_flags,
        )
        validations.append(validation)
        for issue_flag in issue_flags:
            issues.append(
                {
                    "issue_type": issue_flag,
                    "final_arm_id": final_arm.final_arm_id,
                    "validation_id": validation_id,
                    "validation_status": status,
                    "convergence_status": convergence,
                }
            )
        final_updates.append(
            replace(
                final_arm,
                validation_status=status,
                validation_id=validation_id,
                validation_confidence=confidence,
                validation_risk_flags=risk_flags,
            )
        )

    counts = Counter(validation.validation_status for validation in validations)
    metrics = {
        "final_arm_validation_count": len(validations),
        "final_arm_validated_count": counts.get("validated", 0),
        "final_arm_weak_validated_count": counts.get("weak_validated", 0),
        "final_arm_unvalidated_count": counts.get("unvalidated", 0),
        "final_arm_validation_conflict_count": counts.get("conflict", 0),
    }
    return FinalArmValidationBuildResult(
        final_arms=tuple(final_updates),
        validations=tuple(validations),
        issues=tuple(issues),
        metrics=metrics,
    )
