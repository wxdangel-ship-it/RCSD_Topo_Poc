from __future__ import annotations

import math
from collections import defaultdict
from itertools import permutations
from typing import Any

from rcsd_topo_poc.modules.t02_junction_anchor.stage4_step2_step3_contract import (
    Stage4BranchResult,
    Stage4ChainContext,
    Stage4SkeletonStability,
    Stage4TopologySkeleton,
    wrap_stage4_chain_context,
)
from rcsd_topo_poc.modules.t02_junction_anchor.shared import normalize_id
from rcsd_topo_poc.modules.t02_junction_anchor.virtual_intersection_poc import (
    MAIN_AXIS_ANGLE_TOLERANCE_DEG,
    ParsedNode,
    ParsedRoad,
    _build_road_branches_for_member_nodes,
    _select_main_pair,
)

from .stage4_geometry_utils import *

def _collect_stage4_passthrough_node_ids(
    *,
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    member_node_ids: set[str],
) -> tuple[str, ...]:
    degree_by_node_id: dict[str, set[str]] = defaultdict(set)
    for road in local_roads:
        degree_by_node_id[str(road.snodeid)].add(str(road.road_id))
        degree_by_node_id[str(road.enodeid)].add(str(road.road_id))
    passthrough_node_ids = [
        node.node_id
        for node in local_nodes
        if node.node_id not in member_node_ids
        and len(degree_by_node_id.get(node.node_id, set())) == 2
    ]
    return tuple(sorted(passthrough_node_ids))


def _build_continuous_chain_context(
    *,
    representative_node: ParsedNode,
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    enabled: bool = True,
) -> dict[str, Any]:
    representative_mainnodeid = normalize_id(representative_node.mainnodeid or representative_node.node_id)
    if not enabled:
        return {
            "chain_component_id": representative_mainnodeid,
            "related_mainnodeids": [],
            "is_in_continuous_chain": False,
            "chain_node_count": 1,
            "chain_node_offset_m": None,
            "sequential_ok": False,
            "related_seed_nodes": [],
        }

    chain_candidates, chain_trace = _chain_candidates_from_topology(
        representative_node_id=representative_node.node_id,
        representative_chain_kind_2=_stage4_chain_kind_2(representative_node),
        local_nodes=local_nodes,
        local_roads=local_roads,
        chain_span_limit_m=CHAIN_CONTEXT_EVENT_SPAN_M,
    )

    chain_candidates.sort(key=lambda item: item[1])
    related_mainnodeids = [normalize_id(candidate.mainnodeid or candidate.node_id) for candidate, _ in chain_candidates]
    nearest_offset_m = None if not chain_candidates else round(abs(chain_candidates[0][1]), 3)
    sequential_ok = any(abs(offset_m) <= CHAIN_SEQUENCE_DISTANCE_M for _, offset_m in chain_candidates)
    related_directions = [1 if offset_m >= 0.0 else -1 for _, offset_m in chain_candidates]
    has_forward_chain = any(sign > 0 for sign in related_directions)
    has_backward_chain = any(sign < 0 for sign in related_directions)
    chain_node_ids = [normalize_id(candidate.node_id) for candidate, _ in chain_candidates]
    chain_member_ids = [representative_mainnodeid, *related_mainnodeids]
    return {
        "chain_component_id": "__".join(sorted(chain_member_ids)) if len(chain_member_ids) > 1 else representative_mainnodeid,
        "related_mainnodeids": related_mainnodeids,
        "is_in_continuous_chain": bool(chain_candidates),
        "chain_node_count": 1 + len(chain_candidates),
        "chain_node_offset_m": nearest_offset_m,
        "sequential_ok": sequential_ok,
        "chain_bidirectional": has_forward_chain and has_backward_chain,
        "chain_node_ids": chain_node_ids,
        "chain_node_trace": chain_trace,
        "related_seed_nodes": [candidate for candidate, offset_m in chain_candidates if abs(offset_m) <= CHAIN_SEQUENCE_DISTANCE_M],
    }


def _build_stage4_topology_skeleton(
    *,
    representative_node: ParsedNode,
    group_nodes: list[ParsedNode],
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    drivezone_union,
    support_center,
) -> Stage4TopologySkeleton:
    raw_chain_context = _build_continuous_chain_context(
        representative_node=representative_node,
        local_nodes=local_nodes,
        local_roads=local_roads,
        enabled=True,
    )
    chain_context = wrap_stage4_chain_context(raw_chain_context)
    member_node_ids = {node.node_id for node in group_nodes}
    _, _, road_branches = _build_stage4_road_branches_for_member_nodes(
        local_roads,
        member_node_ids=member_node_ids,
        drivezone_union=drivezone_union,
        include_internal_roads=_is_complex_stage4_node(representative_node),
        support_center=support_center if _is_complex_stage4_node(representative_node) else None,
    )
    chain_augmented = False
    if _is_complex_stage4_node(representative_node):
        needs_augmented_complex_context = len(road_branches) < 2
        if not needs_augmented_complex_context:
            try:
                _select_main_pair(road_branches)
            except Exception:
                needs_augmented_complex_context = True
        if needs_augmented_complex_context:
            related_mainnodeids = {
                normalize_id(mainnodeid)
                for mainnodeid in chain_context.related_mainnodeids
                if normalize_id(mainnodeid) is not None
            }
            if not related_mainnodeids:
                fallback_candidates, _ = _chain_candidates_from_topology(
                    representative_node_id=representative_node.node_id,
                    representative_chain_kind_2=None,
                    local_nodes=local_nodes,
                    local_roads=local_roads,
                    chain_span_limit_m=CHAIN_CONTEXT_EVENT_SPAN_M,
                )
                related_mainnodeids = {
                    normalize_id(candidate.mainnodeid or candidate.node_id)
                    for candidate, _ in fallback_candidates
                    if normalize_id(candidate.mainnodeid or candidate.node_id) is not None
                }
            augmented_member_node_ids = set(member_node_ids)
            augmented_member_node_ids.update(
                node.node_id
                for node in local_nodes
                if normalize_id(node.mainnodeid or node.node_id) in related_mainnodeids
                and node.node_id not in member_node_ids
            )
            if len(augmented_member_node_ids) > len(member_node_ids):
                _, _, road_branches = _build_stage4_road_branches_for_member_nodes(
                    local_roads,
                    member_node_ids=augmented_member_node_ids,
                    drivezone_union=drivezone_union,
                    include_internal_roads=True,
                    support_center=support_center,
                )
                member_node_ids = augmented_member_node_ids
                chain_augmented = True

    road_to_branch: dict[str, Any] = {}
    for branch in road_branches:
        for road_id in branch.road_ids:
            road_to_branch[str(road_id)] = branch
    road_branches_by_id: dict[str, Any] = {
        str(branch.branch_id): branch
        for branch in road_branches
    }
    through_node_candidate_ids = _collect_stage4_passthrough_node_ids(
        local_nodes=local_nodes,
        local_roads=local_roads,
        member_node_ids=member_node_ids,
    )
    unstable_reasons: list[str] = []
    has_minimum_branches = len(road_branches) >= 2
    if not has_minimum_branches:
        unstable_reasons.append("insufficient_branch_count")
    main_branch_ids: tuple[str, ...] = ()
    main_pair_resolved = False
    if has_minimum_branches:
        try:
            main_branch_ids = tuple(sorted(_select_main_pair(road_branches)))
            main_pair_resolved = True
        except Exception:
            unstable_reasons.append("main_pair_unresolved")
    branch_result = Stage4BranchResult(
        member_node_ids=tuple(sorted(node.node_id for node in group_nodes)),
        augmented_member_node_ids=tuple(sorted(member_node_ids)),
        road_branches=tuple(road_branches),
        road_branch_ids=tuple(sorted(str(branch.branch_id) for branch in road_branches)),
        road_to_branch=road_to_branch,
        road_branches_by_id=road_branches_by_id,
        main_branch_ids=main_branch_ids,
        through_node_policy="degree2_passthrough_does_not_break_branch",
        through_node_candidate_ids=through_node_candidate_ids,
    )
    stability = Stage4SkeletonStability(
        has_minimum_branches=has_minimum_branches,
        main_pair_resolved=main_pair_resolved,
        branch_count=len(road_branches),
        chain_augmented=chain_augmented,
        unstable_reasons=tuple(unstable_reasons),
    )
    return Stage4TopologySkeleton(
        branch_result=branch_result,
        chain_context=chain_context,
        stability=stability,
    )

def _build_stage4_directed_road_graph(
    local_roads: list[ParsedRoad],
) -> tuple[dict[str, list[tuple[str, ParsedRoad]]], dict[str, list[tuple[str, ParsedRoad]]], dict[str, int]]:
    adjacency_out: dict[str, list[tuple[str, ParsedRoad]]] = defaultdict(list)
    adjacency_in: dict[str, list[tuple[str, ParsedRoad]]] = defaultdict(list)
    undirected_degree: dict[str, int] = defaultdict(int)

    for road in local_roads:
        if road.direction not in {2, 3}:
            continue
        if not road.road_id:
            continue
        src_node = road.snodeid
        dst_node = road.enodeid
        if not src_node or not dst_node:
            continue
        if road.direction == 2:
            src_node = road.snodeid
            dst_node = road.enodeid
        else:
            src_node = road.enodeid
            dst_node = road.snodeid

        adjacency_out[src_node].append((dst_node, road))
        adjacency_in[dst_node].append((src_node, road))
        undirected_degree[src_node] = int(undirected_degree.get(src_node, 0)) + 1
        undirected_degree[dst_node] = int(undirected_degree.get(dst_node, 0)) + 1

    return dict(adjacency_out), dict(adjacency_in), dict(undirected_degree)


def _is_chain_kind_compatible(
    lhs_kind_2: int | None,
    rhs_kind_2: int | None,
) -> bool:
    if lhs_kind_2 is None or rhs_kind_2 is None:
        return True
    if lhs_kind_2 == rhs_kind_2:
        return True
    if lhs_kind_2 == COMPLEX_JUNCTION_KIND or rhs_kind_2 == COMPLEX_JUNCTION_KIND:
        return True
    if lhs_kind_2 in STAGE4_KIND_2_VALUES and rhs_kind_2 in STAGE4_KIND_2_VALUES:
        return True
    return False


def _road_travel_angle_deg(
    road: ParsedRoad,
    *,
    from_node_id: str,
    to_node_id: str,
) -> float | None:
    if road.geometry is None or road.geometry.is_empty:
        return None
    line = road.geometry if getattr(road.geometry, "geom_type", None) == "LineString" else linemerge(road.geometry)
    line_components = [
        component
        for component in _explode_component_geometries(line)
        if getattr(component, "geom_type", None) == "LineString" and not component.is_empty
    ]
    if not line_components:
        return None
    centerline = max(line_components, key=lambda component: float(component.length))
    coords = list(centerline.coords)
    if len(coords) < 2:
        return None
    start_x, start_y = _coord_xy(coords[0])
    end_x, end_y = _coord_xy(coords[-1])
    vector = (float(end_x) - float(start_x), float(end_y) - float(start_y))
    if not vector[0] and not vector[1]:
        return None

    normalized_from = normalize_id(from_node_id) or str(from_node_id)
    normalized_to = normalize_id(to_node_id) or str(to_node_id)
    forward_src = normalize_id(road.snodeid) or road.snodeid
    forward_dst = normalize_id(road.enodeid) or road.enodeid
    if int(road.direction) == 3:
        forward_src, forward_dst = forward_dst, forward_src
    if normalized_from == forward_dst and normalized_to == forward_src:
        vector = (-float(vector[0]), -float(vector[1]))
    elif not (normalized_from == forward_src and normalized_to == forward_dst):
        return None

    normalized_vector = _normalize_axis_vector((float(vector[0]), float(vector[1])))
    if normalized_vector is None:
        return None
    return float(math.degrees(math.atan2(normalized_vector[1], normalized_vector[0])) % 360.0)


def _pick_chain_continuation_candidate(
    *,
    candidates: list[tuple[str, ParsedRoad]],
    prev_node_id: str,
    current_node_id: str,
    previous_road: ParsedRoad,
) -> tuple[str, ParsedRoad] | None:
    if len(candidates) == 1:
        return candidates[0]
    previous_angle = _road_travel_angle_deg(
        previous_road,
        from_node_id=prev_node_id,
        to_node_id=current_node_id,
    )
    if previous_angle is None:
        return None

    ranked_candidates: list[tuple[float, float, str, ParsedRoad]] = []
    for next_node_id, candidate_road in candidates:
        candidate_angle = _road_travel_angle_deg(
            candidate_road,
            from_node_id=current_node_id,
            to_node_id=next_node_id,
        )
        if candidate_angle is None:
            continue
        angle_gap = _branch_angle_gap_deg(
            {"angle_deg": previous_angle},
            {"angle_deg": candidate_angle},
        )
        ranked_candidates.append(
            (
                float(angle_gap),
                -float(candidate_road.geometry.length) if candidate_road.geometry is not None and not candidate_road.geometry.is_empty else 0.0,
                str(next_node_id),
                candidate_road,
            )
        )
    if not ranked_candidates:
        return None
    ranked_candidates.sort(key=lambda item: (float(item[0]), float(item[1]), item[2]))
    best_gap, _best_len, best_node_id, best_road = ranked_candidates[0]
    if float(best_gap) > CHAIN_CONTINUATION_MAX_TURN_DEG:
        return None
    if len(ranked_candidates) > 1:
        second_gap = float(ranked_candidates[1][0])
        if second_gap - float(best_gap) < CHAIN_CONTINUATION_MIN_MARGIN_DEG:
            return None
    return str(best_node_id), best_road


def _build_stage4_road_branches_for_member_nodes(
    local_roads: list[ParsedRoad],
    *,
    member_node_ids: set[str],
    drivezone_union: BaseGeometry,
    include_internal_roads: bool = False,
    support_center: Point | None = None,
) -> tuple[list[ParsedRoad], set[str], list[Any]]:
    incident_roads, internal_road_ids, road_branches = _build_road_branches_for_member_nodes(
        local_roads,
        member_node_ids=member_node_ids,
        drivezone_union=drivezone_union,
    )

    if (not include_internal_roads) or (len(road_branches) >= 2 and support_center is None):
        return incident_roads, internal_road_ids, road_branches

    road_candidates = []
    existing_candidate_road_ids: set[str] = set()
    for road in local_roads:
        touches_snode = road.snodeid in member_node_ids
        touches_enode = road.enodeid in member_node_ids
        if not touches_snode and not touches_enode:
            continue
        candidate = _branch_candidate_from_road(
            road,
            member_node_ids=member_node_ids,
            drivezone_union=drivezone_union,
        )
        if candidate is not None:
            road_candidates.append(candidate)
            existing_candidate_road_ids.add(str(candidate["road_id"]))

    if support_center is not None and len(road_branches) < 3:
        for road in local_roads:
            if road.road_id in existing_candidate_road_ids:
                continue
            candidate = _branch_candidate_from_center_proximity(
                road,
                center=support_center,
                drivezone_union=drivezone_union,
                max_distance_m=EVENT_COMPLEX_SUPPORT_BRANCH_PROXIMITY_M,
            )
            if candidate is None:
                continue
            road_candidates.append(candidate)
            existing_candidate_road_ids.add(str(candidate["road_id"]))

    road_branches = _cluster_branch_candidates(
        road_candidates,
        branch_type="road",
        angle_tolerance_deg=BRANCH_MATCH_TOLERANCE_DEG,
    )
    return incident_roads, internal_road_ids, road_branches


def _chain_candidates_from_topology(
    *,
    representative_node_id: str,
    representative_chain_kind_2: int | None,
    local_nodes: list[ParsedNode],
    local_roads: list[ParsedRoad],
    chain_span_limit_m: float,
) -> tuple[list[tuple[ParsedNode, float]], dict[str, Any]]:
    representative_mainnode = normalize_id(representative_node_id) or representative_node_id
    candidate_nodes = [
        node
        for node in local_nodes
        if _is_stage4_representative(node)
    ]
    candidate_nodes_by_id: dict[str, ParsedNode] = {
        normalize_id(node.node_id): node
        for node in candidate_nodes
        if normalize_id(node.node_id)
    }
    if not candidate_nodes_by_id:
        return [], {}

    adjacency_out, adjacency_in, undirected_degree = _build_stage4_directed_road_graph(local_roads)

    def _seed_candidates(direction_sign: int, seed_edges: list[tuple[str, ParsedRoad]]) -> list[tuple[str, float]]:
        traces: list[tuple[str, float]] = []
        for next_node, road in seed_edges:
            if road.geometry is None or road.geometry.is_empty:
                continue
            start_distance = float(road.geometry.length)
            if start_distance <= 0.0 or start_distance > chain_span_limit_m:
                continue
            current_id = normalize_id(next_node) or next_node
            prev_id = normalize_id(representative_mainnode) or representative_mainnode
            if current_id == prev_id:
                continue
            distance_m = start_distance
            visited: set[str] = {prev_id}
            previous_road = road

            while True:
                if distance_m > chain_span_limit_m:
                    break
                if current_id in visited:
                    break
                visited.add(current_id)
                if current_id in candidate_nodes_by_id and current_id != representative_mainnode:
                    traces.append((current_id, direction_sign * distance_m))
                current_edges = (
                    adjacency_out.get(current_id, [])
                    if direction_sign == 1
                    else adjacency_in.get(current_id, [])
                )
                candidates = [
                    (target_node, candidate_road)
                    for target_node, candidate_road in current_edges
                    if normalize_id(target_node) != prev_id
                ]
                if not candidates:
                    break
                if len(candidates) == 1:
                    next_node_id, next_road = candidates[0]
                else:
                    continuation = _pick_chain_continuation_candidate(
                        candidates=candidates,
                        prev_node_id=prev_id,
                        current_node_id=current_id,
                        previous_road=previous_road,
                    )
                    if continuation is None:
                        break
                    next_node_id, next_road = continuation
                if next_road.geometry is None or next_road.geometry.is_empty:
                    break
                seg_len = float(next_road.geometry.length)
                if seg_len <= 0.0:
                    break
                if distance_m + seg_len > chain_span_limit_m:
                    break
                prev_id = current_id
                current_id = normalize_id(next_node_id) or next_node_id
                distance_m += seg_len
                previous_road = next_road
        return traces

    traces: list[tuple[str, float]] = []
    traces.extend(
        _seed_candidates(
            direction_sign=1,
            seed_edges=adjacency_out.get(representative_mainnode, []) if representative_mainnode else [],
        )
    )
    traces.extend(
        _seed_candidates(
            direction_sign=-1,
            seed_edges=adjacency_in.get(representative_mainnode, []) if representative_mainnode else [],
        )
    )

    best_distance_by_nodeid: dict[str, float] = {}
    for node_id, distance_m in traces:
        if not node_id or normalize_id(node_id) not in candidate_nodes_by_id:
            continue
        normalized = normalize_id(node_id)
        if normalized is None:
            continue
        prev = best_distance_by_nodeid.get(normalized)
        if prev is None or abs(float(distance_m)) < abs(float(prev)):
            best_distance_by_nodeid[normalized] = distance_m

    chain_candidates: list[tuple[ParsedNode, float]] = []
    for node_id, distance_m in best_distance_by_nodeid.items():
        node = candidate_nodes_by_id.get(node_id)
        if node is None:
            continue
        if not _is_chain_kind_compatible(representative_chain_kind_2, _stage4_chain_kind_2(node)):
            continue
        chain_candidates.append((node, float(distance_m)))
    chain_candidates.sort(key=lambda item: abs(float(item[1])))

    return chain_candidates, {
        "chain_graph_node_count": len(undirected_degree),
        "chain_graph_edge_count": sum(1 for _edges in adjacency_out.values() for _ in _edges),
        "chain_seed_count": len(traces),
        "chain_seed_candidates": sorted(candidate_nodes_by_id.keys()),
    }
