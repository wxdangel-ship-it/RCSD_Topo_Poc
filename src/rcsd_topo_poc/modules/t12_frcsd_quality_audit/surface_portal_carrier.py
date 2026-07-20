from __future__ import annotations

import heapq
import math
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from rcsd_topo_poc.modules.t06_segment_fusion_precheck.graph_builders import (
    NodeCanonicalizer,
)

from .anchor_portals import AnchorRecord
from .carrier_graph import GraphBundle, GraphEdge, PathResult, path_metrics
from .models import AuditConfig


ROAD_SURFACE_TOPOLOGY_TOLERANCE_M = 1.0


@dataclass(frozen=True)
class SurfaceCarrierResult:
    path: PathResult | None
    evidence: dict[str, Any]


@dataclass(frozen=True)
class _Access:
    kind: str
    frontier_node: str
    support_road_ids: tuple[str, ...]
    surface_gap_m: float
    swsd_portal_gap_m: float
    travel_measure_m: float
    preferred_node_match: bool


@dataclass(frozen=True)
class _FoundPath:
    path: PathResult
    effective_length_m: float
    source_access: _Access
    target_access: _Access


def evaluate_t07_road_surface_carrier(
    *,
    graph: GraphBundle,
    canonicalizer: NodeCanonicalizer,
    raw_node_points: Mapping[str, Any],
    source_anchor: AnchorRecord,
    target_anchor: AnchorRecord,
    source_surface: Any | None,
    target_surface: Any | None,
    source_surface_id: str,
    target_surface_id: str,
    source_swsd_point: Any,
    target_swsd_point: Any,
    reference_geometry: Any,
    reference_length_m: float,
    config: AuditConfig,
    preferred_source_nodes: Iterable[str] = (),
) -> SurfaceCarrierResult:
    """Evaluate a physical directed Road path between two trusted T07 surfaces."""
    base = {
        "evaluated": True,
        "accepted_equivalent_carrier": False,
        "distance_gate_role": "audit_only",
        "source_surface_id": source_surface_id,
        "target_surface_id": target_surface_id,
        "source_access_kind": "",
        "target_access_kind": "",
        "source_access_frontier_node": "",
        "target_access_frontier_node": "",
        "source_access_road_ids": [],
        "target_access_road_ids": [],
        "source_preferred_node_match": False,
        "road_ids": [],
        "node_ids": [],
        "full_path_length_m": None,
        "effective_path_length_m": None,
        "length_m": None,
        "length_ratio": None,
        "path_length_additive_m": None,
        "max_corridor_distance_m": None,
        "source_road_surface_gap_m": None,
        "target_road_surface_gap_m": None,
        "source_road_swsd_portal_gap_m": None,
        "target_road_swsd_portal_gap_m": None,
        "internal_alias_transitions": [],
        "max_internal_alias_gap_m": None,
        "distance_risk_flags": [],
        "rejection_reason": "",
    }
    if source_anchor.source_module != "T07" or target_anchor.source_module != "T07":
        return SurfaceCarrierResult(
            path=None,
            evidence={**base, "rejection_reason": "t07_anchor_pair_required"},
        )
    if source_surface is None or target_surface is None:
        return SurfaceCarrierResult(
            path=None,
            evidence={**base, "rejection_reason": "unique_standard_surface_required"},
        )
    source_anchor_nodes = _anchor_nodes(canonicalizer, source_anchor)
    target_anchor_nodes = _anchor_nodes(canonicalizer, target_anchor)
    source_frontiers = _anchor_frontiers(
        graph,
        source_anchor_nodes,
        blocked_nodes=target_anchor_nodes,
        surface=source_surface,
    )
    target_frontiers = _anchor_frontiers(
        graph,
        target_anchor_nodes,
        blocked_nodes=source_anchor_nodes,
        surface=target_surface,
    )
    found = _shortest_surface_path(
        graph=graph,
        source_surface=source_surface,
        target_surface=target_surface,
        source_swsd_point=source_swsd_point,
        target_swsd_point=target_swsd_point,
        source_frontiers=source_frontiers,
        target_frontiers=target_frontiers,
        preferred_source_nodes=set(preferred_source_nodes),
    )
    if found is None:
        return SurfaceCarrierResult(
            path=None,
            evidence={**base, "rejection_reason": "surface_portal_path_missing"},
        )

    full_metrics = path_metrics(
        found.path,
        graph.edges,
        reference_geometry,
        reference_length_m,
        config,
    )
    effective_length = found.effective_length_m
    length_ratio = (
        effective_length / reference_length_m
        if reference_length_m > 0
        else math.inf
    )
    additive = effective_length - reference_length_m
    length_accepted = bool(
        length_ratio <= config.path_max_length_ratio
        and additive <= config.path_max_additive_m
    )
    aliases, max_alias_gap = _internal_alias_audit(
        found.path,
        graph.edges,
        raw_node_points,
    )
    risk_flags = _distance_risks(
        source_access=found.source_access,
        target_access=found.target_access,
        max_corridor_distance_m=full_metrics["max_corridor_distance_m"],
        max_internal_alias_gap_m=max_alias_gap,
        config=config,
    )
    evidence = {
        **base,
        "accepted_equivalent_carrier": length_accepted,
        "source_access_kind": found.source_access.kind,
        "target_access_kind": found.target_access.kind,
        "source_access_frontier_node": found.source_access.frontier_node,
        "target_access_frontier_node": found.target_access.frontier_node,
        "source_access_road_ids": list(found.source_access.support_road_ids),
        "target_access_road_ids": list(found.target_access.support_road_ids),
        "source_preferred_node_match": found.source_access.preferred_node_match,
        "road_ids": list(found.path.road_ids),
        "node_ids": list(found.path.node_ids),
        "full_path_length_m": found.path.length_m,
        "effective_path_length_m": effective_length,
        "length_m": effective_length,
        "length_ratio": length_ratio,
        "path_length_additive_m": additive,
        "max_corridor_distance_m": full_metrics["max_corridor_distance_m"],
        "source_road_surface_gap_m": found.source_access.surface_gap_m,
        "target_road_surface_gap_m": found.target_access.surface_gap_m,
        "source_road_swsd_portal_gap_m": found.source_access.swsd_portal_gap_m,
        "target_road_swsd_portal_gap_m": found.target_access.swsd_portal_gap_m,
        "internal_alias_transitions": aliases,
        "max_internal_alias_gap_m": max_alias_gap,
        "distance_risk_flags": risk_flags,
        "rejection_reason": (
            "" if length_accepted else "surface_portal_path_not_length_equivalent"
        ),
    }
    return SurfaceCarrierResult(path=found.path, evidence=evidence)


def not_evaluated_surface_carrier(reason: str) -> SurfaceCarrierResult:
    return SurfaceCarrierResult(
        path=None,
        evidence={
            "evaluated": False,
            "accepted_equivalent_carrier": False,
            "distance_gate_role": "audit_only",
            "road_ids": [],
            "rejection_reason": reason,
        },
    )


def _shortest_surface_path(
    *,
    graph: GraphBundle,
    source_surface: Any,
    target_surface: Any,
    source_swsd_point: Any,
    target_swsd_point: Any,
    source_frontiers: Mapping[str, tuple[str, ...]],
    target_frontiers: Mapping[str, tuple[str, ...]],
    preferred_source_nodes: set[str],
) -> _FoundPath | None:
    queue: list[
        tuple[
            int,
            float,
            tuple[str, ...],
            tuple[str, ...],
            float,
            _Access,
        ]
    ] = []
    best: dict[tuple[bool, str], float] = {}
    selected: _FoundPath | None = None
    selected_key: tuple[int, float, tuple[str, ...]] | None = None

    for start, end, road_id, length_m in _directed_transitions(graph):
        edge = graph.edges[road_id]
        source_access = _source_access(
            edge=edge,
            start=start,
            end=end,
            surface=source_surface,
            swsd_point=source_swsd_point,
            frontiers=source_frontiers,
            preferred_source_nodes=preferred_source_nodes,
        )
        if source_access is None:
            continue
        effective = max(0.0, length_m - source_access.travel_measure_m)
        path = PathResult(
            start=start,
            end=end,
            node_ids=(start, end),
            road_ids=(road_id,),
            length_m=length_m,
        )
        target_access = _target_access(
            edge=edge,
            start=start,
            end=end,
            surface=target_surface,
            swsd_point=target_swsd_point,
            frontiers=target_frontiers,
        )
        if target_access is not None:
            goal_length = _same_edge_effective_length(
                source_access,
                target_access,
                edge.length_m,
            )
            if goal_length is not None and _has_road_surface_contact(
                source_access,
                target_access,
            ):
                selected, selected_key = _prefer_found(
                    selected,
                    selected_key,
                    _FoundPath(path, goal_length, source_access, target_access),
                )
        best_key = (source_access.preferred_node_match, end)
        current = best.get(best_key, math.inf)
        if effective < current and not math.isclose(effective, current):
            best[best_key] = effective
            heapq.heappush(
                queue,
                (
                    int(not source_access.preferred_node_match),
                    effective,
                    path.road_ids,
                    path.node_ids,
                    path.length_m,
                    source_access,
                ),
            )

    while queue:
        (
            source_priority,
            effective,
            road_ids,
            node_ids,
            full_length,
            source_access,
        ) = heapq.heappop(queue)
        node = node_ids[-1]
        best_key = (source_access.preferred_node_match, node)
        if effective > best.get(best_key, math.inf) and not math.isclose(
            effective, best.get(best_key, math.inf)
        ):
            continue
        if selected_key is not None and (source_priority, effective) > (
            selected_key[0],
            selected_key[1],
        ):
            break
        frontier_roads = tuple(
            road_id
            for road_id in target_frontiers.get(node, ())
            if road_id != road_ids[-1]
        )
        if frontier_roads and source_access.kind == "road_surface_intersection":
            last_edge = graph.edges[road_ids[-1]]
            target_access = _frontier_access(
                kind="anchor_one_hop_frontier",
                frontier_node=node,
                support_road_ids=frontier_roads,
                edge=last_edge,
                surface=target_surface,
                swsd_point=target_swsd_point,
                travel_measure_m=last_edge.length_m,
            )
            path = PathResult(
                start=node_ids[0],
                end=node,
                node_ids=node_ids,
                road_ids=road_ids,
                length_m=full_length,
            )
            selected, selected_key = _prefer_found(
                selected,
                selected_key,
                _FoundPath(path, effective, source_access, target_access),
            )
        for next_node, road_id, edge_length in graph.directed.get(node, ()):
            if road_id in road_ids:
                continue
            edge = graph.edges[road_id]
            target_access = _target_access(
                edge=edge,
                start=node,
                end=next_node,
                surface=target_surface,
                swsd_point=target_swsd_point,
                frontiers=target_frontiers,
            )
            next_roads = (*road_ids, road_id)
            next_nodes = (*node_ids, next_node)
            next_full = full_length + float(edge_length)
            if target_access is not None and _has_road_surface_contact(
                source_access,
                target_access,
            ):
                goal_length = effective + (
                    target_access.travel_measure_m
                    if target_access.kind == "road_surface_intersection"
                    else float(edge_length)
                )
                goal_path = PathResult(
                    start=next_nodes[0],
                    end=next_node,
                    node_ids=next_nodes,
                    road_ids=next_roads,
                    length_m=next_full,
                )
                selected, selected_key = _prefer_found(
                    selected,
                    selected_key,
                    _FoundPath(goal_path, goal_length, source_access, target_access),
                )
            next_effective = effective + float(edge_length)
            next_best_key = (source_access.preferred_node_match, next_node)
            current = best.get(next_best_key, math.inf)
            if next_effective < current and not math.isclose(next_effective, current):
                best[next_best_key] = next_effective
                heapq.heappush(
                    queue,
                    (
                        source_priority,
                        next_effective,
                        next_roads,
                        next_nodes,
                        next_full,
                        source_access,
                    ),
                )
    return selected


def _source_access(
    *,
    edge: GraphEdge,
    start: str,
    end: str,
    surface: Any,
    swsd_point: Any,
    frontiers: Mapping[str, tuple[str, ...]],
    preferred_source_nodes: set[str],
) -> _Access | None:
    measures = _surface_travel_measures(edge, start, end, surface)
    if measures:
        return _frontier_access(
            kind="road_surface_intersection",
            frontier_node=start,
            support_road_ids=(),
            edge=edge,
            surface=surface,
            swsd_point=swsd_point,
            travel_measure_m=max(measures),
            preferred_node_match=start in preferred_source_nodes,
        )
    support = tuple(
        road_id for road_id in frontiers.get(start, ()) if road_id != edge.road_id
    )
    if support:
        return _frontier_access(
            kind="anchor_one_hop_frontier",
            frontier_node=start,
            support_road_ids=support,
            edge=edge,
            surface=surface,
            swsd_point=swsd_point,
            travel_measure_m=0.0,
            preferred_node_match=start in preferred_source_nodes,
        )
    return None


def _target_access(
    *,
    edge: GraphEdge,
    start: str,
    end: str,
    surface: Any,
    swsd_point: Any,
    frontiers: Mapping[str, tuple[str, ...]],
) -> _Access | None:
    measures = _surface_travel_measures(edge, start, end, surface)
    if measures:
        return _frontier_access(
            kind="road_surface_intersection",
            frontier_node=end,
            support_road_ids=(),
            edge=edge,
            surface=surface,
            swsd_point=swsd_point,
            travel_measure_m=min(measures),
            preferred_node_match=False,
        )
    support = tuple(
        road_id for road_id in frontiers.get(end, ()) if road_id != edge.road_id
    )
    if support:
        return _frontier_access(
            kind="anchor_one_hop_frontier",
            frontier_node=end,
            support_road_ids=support,
            edge=edge,
            surface=surface,
            swsd_point=swsd_point,
            travel_measure_m=edge.length_m,
            preferred_node_match=False,
        )
    return None


def _frontier_access(
    *,
    kind: str,
    frontier_node: str,
    support_road_ids: Iterable[str],
    edge: GraphEdge,
    surface: Any,
    swsd_point: Any,
    travel_measure_m: float,
    preferred_node_match: bool = False,
) -> _Access:
    return _Access(
        kind=kind,
        frontier_node=frontier_node,
        support_road_ids=tuple(sorted(set(support_road_ids))),
        surface_gap_m=float(edge.geometry.distance(surface)),
        swsd_portal_gap_m=float(edge.geometry.distance(swsd_point)),
        travel_measure_m=float(travel_measure_m),
        preferred_node_match=preferred_node_match,
    )


def _anchor_nodes(
    canonicalizer: NodeCanonicalizer,
    anchor: AnchorRecord,
) -> set[str]:
    return {
        canonicalizer.canonicalize(raw_id)
        for raw_id in (*anchor.grouped_node_ids, anchor.base_id)
        if raw_id
    }


def _anchor_frontiers(
    graph: GraphBundle,
    anchor_nodes: set[str],
    *,
    blocked_nodes: set[str],
    surface: Any,
) -> dict[str, tuple[str, ...]]:
    frontiers: dict[str, set[str]] = {}
    for anchor_node in anchor_nodes:
        for neighbor, road_id, _ in graph.directed.get(anchor_node, ()):
            if neighbor in anchor_nodes or neighbor in blocked_nodes:
                continue
            edge = graph.edges[road_id]
            if float(edge.geometry.distance(surface)) > (
                ROAD_SURFACE_TOPOLOGY_TOLERANCE_M
            ):
                continue
            frontiers.setdefault(neighbor, set()).add(road_id)
    return {
        node: tuple(sorted(road_ids))
        for node, road_ids in sorted(frontiers.items())
    }


def _surface_travel_measures(
    edge: GraphEdge,
    start: str,
    end: str,
    surface: Any,
) -> list[float]:
    geometry = edge.geometry
    if geometry is None or geometry.is_empty or not geometry.intersects(surface):
        return []
    forward = _is_forward(edge, start, end)
    length = float(geometry.length)
    measures = [
        float(geometry.project(point))
        for point in _intersection_points(geometry.intersection(surface))
    ]
    if not forward:
        measures = [length - measure for measure in measures]
    return sorted(max(0.0, min(length, measure)) for measure in measures)


def _intersection_points(geometry: Any) -> list[Any]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Point":
        return [geometry]
    if hasattr(geometry, "geoms"):
        return [
            point
            for part in geometry.geoms
            for point in _intersection_points(part)
        ]
    coordinates = list(geometry.coords)
    if not coordinates:
        return []
    from shapely.geometry import Point

    return [Point(coordinates[0]), Point(coordinates[-1])]


def _is_forward(edge: GraphEdge, start: str, end: str) -> bool:
    forward = start == edge.start and end == edge.end
    reverse = start == edge.end and end == edge.start
    if forward and not reverse:
        return True
    if reverse and not forward:
        return False
    return edge.direction != 3


def _same_edge_effective_length(
    source: _Access,
    target: _Access,
    edge_length_m: float,
) -> float | None:
    if source.kind == "road_surface_intersection" and target.kind == (
        "road_surface_intersection"
    ):
        if target.travel_measure_m < source.travel_measure_m:
            return None
        return target.travel_measure_m - source.travel_measure_m
    if source.kind == "road_surface_intersection":
        return max(0.0, edge_length_m - source.travel_measure_m)
    if target.kind == "road_surface_intersection":
        return max(0.0, target.travel_measure_m)
    return edge_length_m


def _has_road_surface_contact(source: _Access, target: _Access) -> bool:
    return "road_surface_intersection" in {source.kind, target.kind}


def _prefer_found(
    current: _FoundPath | None,
    current_key: tuple[int, float, tuple[str, ...]] | None,
    candidate: _FoundPath,
) -> tuple[_FoundPath, tuple[int, float, tuple[str, ...]]]:
    key = (
        int(not candidate.source_access.preferred_node_match),
        candidate.effective_length_m,
        candidate.path.road_ids,
    )
    if current is None or current_key is None or key < current_key:
        return candidate, key
    return current, current_key


def _directed_transitions(
    graph: GraphBundle,
) -> Iterable[tuple[str, str, str, float]]:
    for start in sorted(graph.directed):
        for end, road_id, length_m in graph.directed[start]:
            yield start, end, road_id, float(length_m)


def _internal_alias_audit(
    path: PathResult,
    edges: Mapping[str, GraphEdge],
    raw_node_points: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], float | None]:
    transitions: list[dict[str, Any]] = []
    gaps: list[float] = []
    oriented = [
        _oriented_raw_endpoints(
            edges[road_id],
            path.node_ids[index],
            path.node_ids[index + 1],
        )
        for index, road_id in enumerate(path.road_ids)
    ]
    for index in range(len(oriented) - 1):
        left_raw = oriented[index][1]
        right_raw = oriented[index + 1][0]
        left_point = raw_node_points.get(left_raw)
        right_point = raw_node_points.get(right_raw)
        gap = (
            float(left_point.distance(right_point))
            if left_point is not None and right_point is not None
            else None
        )
        if gap is not None:
            gaps.append(gap)
        transitions.append(
            {
                "from_road_id": path.road_ids[index],
                "to_road_id": path.road_ids[index + 1],
                "from_raw_node": left_raw,
                "to_raw_node": right_raw,
                "canonical_node": path.node_ids[index + 1],
                "gap_m": gap,
                "distance_gate_role": "audit_only",
            }
        )
    return transitions, max(gaps, default=None)


def _oriented_raw_endpoints(
    edge: GraphEdge,
    start: str,
    end: str,
) -> tuple[str, str]:
    if _is_forward(edge, start, end):
        return edge.raw_start, edge.raw_end
    return edge.raw_end, edge.raw_start


def _distance_risks(
    *,
    source_access: _Access,
    target_access: _Access,
    max_corridor_distance_m: float | None,
    max_internal_alias_gap_m: float | None,
    config: AuditConfig,
) -> list[str]:
    risks: list[str] = []
    if source_access.swsd_portal_gap_m > config.portal_radius_m:
        risks.append("source_swsd_portal_gap_exceeds_portal_radius")
    if target_access.swsd_portal_gap_m > config.portal_radius_m:
        risks.append("target_swsd_portal_gap_exceeds_portal_radius")
    if (
        max_internal_alias_gap_m is not None
        and max_internal_alias_gap_m > config.portal_radius_m
    ):
        risks.append("internal_alias_gap_exceeds_portal_radius")
    if (
        max_corridor_distance_m is not None
        and max_corridor_distance_m > config.path_max_corridor_distance_m
    ):
        risks.append("corridor_distance_exceeds_threshold")
    return risks
