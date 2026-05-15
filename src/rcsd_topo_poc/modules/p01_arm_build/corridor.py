from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

from rcsd_topo_poc.modules.p01_arm_build.io import normalise_id
from rcsd_topo_poc.modules.p01_arm_build.models import (
    ArmCorridorEvidence,
    FinalArm,
    LocalArmCandidate,
    NodeRecord,
    RoadRecord,
)
from rcsd_topo_poc.modules.p01_arm_build.special_roads import is_advance_right_turn_road


CORRIDOR_MAX_HOPS = 4
CORRIDOR_MAX_CONTINUATION_ANGLE_DEG = 55.0
CORRIDOR_AMBIGUOUS_MARGIN_DEG = 8.0


def _valid_mainnodeid(value: str | None) -> str | None:
    text = normalise_id(value)
    if not text or text.lower() in {"0", "0.0", "none", "null", "nan"}:
        return None
    return text


def _semantic_group_id(node: NodeRecord | None, fallback_node_id: str) -> str:
    if node is None:
        return normalise_id(fallback_node_id)
    return _valid_mainnodeid(node.mainnodeid) or node.node_id


def _point_xy(node: NodeRecord | None) -> tuple[float, float] | None:
    if node is None or node.geometry is None or node.geometry.is_empty:
        return None
    centroid = node.geometry.centroid
    return (float(centroid.x), float(centroid.y))


def _centroid(nodes: dict[str, NodeRecord], node_ids: set[str]) -> tuple[float, float] | None:
    points = [_point_xy(nodes.get(node_id)) for node_id in node_ids]
    points = [point for point in points if point is not None]
    if not points:
        return None
    return (sum(point[0] for point in points) / len(points), sum(point[1] for point in points) / len(points))


def _normalise(vector: tuple[float, float] | None) -> tuple[float, float] | None:
    if vector is None:
        return None
    length = math.hypot(vector[0], vector[1])
    if length <= 1e-9:
        return None
    return (vector[0] / length, vector[1] / length)


def _angle(vector: tuple[float, float] | None) -> float | None:
    unit = _normalise(vector)
    if unit is None:
        return None
    return math.degrees(math.atan2(unit[1], unit[0])) % 360.0


def _angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    au = _normalise(a)
    bu = _normalise(b)
    if au is None or bu is None:
        return 180.0
    dot = max(-1.0, min(1.0, au[0] * bu[0] + au[1] * bu[1]))
    return math.degrees(math.acos(dot))


def _mean_angle(angles: list[float]) -> float | None:
    if not angles:
        return None
    x = sum(math.cos(math.radians(angle)) for angle in angles)
    y = sum(math.sin(math.radians(angle)) for angle in angles)
    if math.hypot(x, y) <= 1e-9:
        return None
    return round(math.degrees(math.atan2(y, x)) % 360.0, 2)


def _ordered_unique(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        text = normalise_id(value)
        if text and text not in seen:
            seen.add(text)
            ordered.append(text)
    return tuple(ordered)


def _other_node_id(road: RoadRecord, node_id: str) -> str | None:
    if road.snodeid == node_id:
        return road.enodeid
    if road.enodeid == node_id:
        return road.snodeid
    return None


def _seed_outside_node(road: RoadRecord, current_member_node_ids: set[str]) -> str | None:
    snode_inside = road.snodeid in current_member_node_ids
    enode_inside = road.enodeid in current_member_node_ids
    if snode_inside and not enode_inside:
        return road.enodeid
    if enode_inside and not snode_inside:
        return road.snodeid
    return None


def _is_simple_passthrough_node(
    node_id: str,
    *,
    nodes: dict[str, NodeRecord],
    groups: dict[str, tuple[str, ...]],
) -> bool:
    node = nodes.get(node_id)
    if node is None:
        return False
    group_id = _semantic_group_id(node, node_id)
    if len(groups.get(group_id, (node_id,))) > 1:
        return False
    kind = normalise_id(node.kind)
    return kind in {"", "0", "1"}


def _node_vector(
    nodes: dict[str, NodeRecord],
    from_node_id: str,
    to_node_id: str,
) -> tuple[float, float] | None:
    start = _point_xy(nodes.get(from_node_id))
    end = _point_xy(nodes.get(to_node_id))
    if start is None or end is None:
        return None
    return (end[0] - start[0], end[1] - start[1])


def _continuation_anchor_node_ids(
    node_id: str,
    *,
    current_member_node_ids: set[str],
    nodes: dict[str, NodeRecord],
    groups: dict[str, tuple[str, ...]],
) -> tuple[str, ...]:
    group_id = _semantic_group_id(nodes.get(node_id), node_id)
    group_nodes = tuple(groups.get(group_id, (node_id,)))
    if any(member_node_id in current_member_node_ids for member_node_id in group_nodes):
        return (node_id,)
    return group_nodes


def _trace_seed_corridor(
    *,
    seed_road: RoadRecord,
    current_member_node_ids: set[str],
    current_centroid: tuple[float, float] | None,
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    incident_by_node: dict[str, tuple[str, ...]],
    groups: dict[str, tuple[str, ...]],
    preferred_road_ids: set[str] | None = None,
) -> dict[str, Any]:
    outside_node_id = _seed_outside_node(seed_road, current_member_node_ids)
    if outside_node_id is None:
        return {
            "road_ids": [seed_road.road_id],
            "node_ids": [],
            "angles": [],
            "terminal_id": None,
            "terminal_type": "no_outside_seed_node",
            "risk_flags": ["corridor_no_outside_seed_node"],
        }

    outside_point = _point_xy(nodes.get(outside_node_id))
    angles: list[float] = []
    if current_centroid is not None and outside_point is not None:
        seed_angle = _angle((outside_point[0] - current_centroid[0], outside_point[1] - current_centroid[1]))
        if seed_angle is not None:
            angles.append(seed_angle)

    road_ids = [seed_road.road_id]
    node_ids = [outside_node_id]
    risk_flags: list[str] = []
    terminal_id: str | None = None
    terminal_type = "seed_only"
    previous_road_id = seed_road.road_id
    previous_node_id: str | None = seed_road.snodeid if seed_road.enodeid == outside_node_id else seed_road.enodeid
    current_node_id = outside_node_id
    current_vector = (
        _node_vector(nodes, previous_node_id, current_node_id)
        if previous_node_id is not None
        else None
    )

    for _step in range(CORRIDOR_MAX_HOPS):
        simple_passthrough_node = _is_simple_passthrough_node(current_node_id, nodes=nodes, groups=groups)
        candidates: list[tuple[float, str, str, tuple[float, float], str]] = []
        for anchor_node_id in _continuation_anchor_node_ids(
            current_node_id,
            current_member_node_ids=current_member_node_ids,
            nodes=nodes,
            groups=groups,
        ):
            for road_id in incident_by_node.get(anchor_node_id, tuple()):
                if road_id == previous_road_id:
                    continue
                road = roads.get(road_id)
                if road is None or is_advance_right_turn_road(road):
                    continue
                next_node_id = _other_node_id(road, anchor_node_id)
                if not next_node_id or next_node_id in current_member_node_ids:
                    continue
                vector = _node_vector(nodes, anchor_node_id, next_node_id)
                if vector is None:
                    continue
                angle_delta = _angle_between(current_vector or vector, vector)
                if angle_delta <= CORRIDOR_MAX_CONTINUATION_ANGLE_DEG:
                    candidates.append((angle_delta, road_id, next_node_id, vector, anchor_node_id))
        preferred_candidates = [
            candidate for candidate in candidates if preferred_road_ids and candidate[1] in preferred_road_ids
        ]
        if preferred_candidates:
            candidates = preferred_candidates
        if not candidates:
            terminal_id = _semantic_group_id(nodes.get(current_node_id), current_node_id)
            terminal_type = "no_continuation" if simple_passthrough_node else "semantic_terminal"
            break
        candidates.sort(key=lambda item: (item[0], item[1]))
        if len(candidates) > 1 and candidates[1][0] - candidates[0][0] <= CORRIDOR_AMBIGUOUS_MARGIN_DEG:
            terminal_id = _semantic_group_id(nodes.get(current_node_id), current_node_id)
            terminal_type = "ambiguous_continuation"
            risk_flags.append("corridor_ambiguous_continuation")
            break
        _angle_delta, next_road_id, next_node_id, next_vector, anchor_node_id = candidates[0]
        road_ids.append(next_road_id)
        if anchor_node_id != current_node_id:
            node_ids.append(anchor_node_id)
        node_ids.append(next_node_id)
        next_angle = _angle(next_vector)
        if next_angle is not None:
            angles.append(next_angle)
        previous_road_id = next_road_id
        previous_node_id = current_node_id
        current_node_id = next_node_id
        current_vector = next_vector
    else:
        terminal_id = _semantic_group_id(nodes.get(current_node_id), current_node_id)
        terminal_type = "step_limit"
        risk_flags.append("corridor_step_limit")

    return {
        "road_ids": road_ids,
        "node_ids": node_ids,
        "angles": angles,
        "terminal_id": terminal_id,
        "terminal_type": terminal_type,
        "risk_flags": risk_flags,
    }


def build_arm_corridor_evidence(
    *,
    dataset: str,
    junction_id: str,
    current_member_node_ids: set[str],
    groups: dict[str, tuple[str, ...]],
    nodes: dict[str, NodeRecord],
    roads: dict[str, RoadRecord],
    final_arms: tuple[FinalArm, ...],
    local_arm_candidates: tuple[LocalArmCandidate, ...],
) -> tuple[ArmCorridorEvidence, ...]:
    incident_by_node: dict[str, list[str]] = defaultdict(list)
    for road_id, road in roads.items():
        incident_by_node[road.snodeid].append(road_id)
        incident_by_node[road.enodeid].append(road_id)
    incident_tuple = {node_id: tuple(sorted(road_ids)) for node_id, road_ids in incident_by_node.items()}
    current_centroid = _centroid(nodes, current_member_node_ids)
    candidates_by_initial: dict[str, list[LocalArmCandidate]] = defaultdict(list)
    for candidate in local_arm_candidates:
        for initial_id in candidate.source_initial_arm_ids:
            candidates_by_initial[str(initial_id)].append(candidate)

    evidence: list[ArmCorridorEvidence] = []
    for arm in final_arms:
        payload = dict(arm.initial_arm or {})
        seed_ids = [normalise_id(item) for item in payload.get("seed_road_ids", []) or []]
        support_road_ids: list[str] = []
        support_node_ids: list[str] = []
        angles: list[float] = []
        terminal_ids: list[str] = []
        terminal_types: list[str] = []
        risk_flags: list[str] = []

        for initial_id in arm.source_initial_arm_ids:
            for candidate in candidates_by_initial.get(str(initial_id), []):
                support_road_ids.extend(str(item) for item in candidate.local_stub_road_ids)
                if candidate.trend_angle_deg is not None:
                    angles.append(float(candidate.trend_angle_deg))

        for seed_id in seed_ids:
            seed_road = roads.get(seed_id)
            if seed_road is None:
                risk_flags.append("corridor_seed_road_missing")
                continue
            trace = _trace_seed_corridor(
                seed_road=seed_road,
                current_member_node_ids=current_member_node_ids,
                current_centroid=current_centroid,
                nodes=nodes,
                roads=roads,
                incident_by_node=incident_tuple,
                groups=groups,
                preferred_road_ids=set(str(item) for item in payload.get("member_road_ids", []) or []),
            )
            support_road_ids.extend(trace["road_ids"])
            support_node_ids.extend(trace["node_ids"])
            angles.extend(trace["angles"])
            if trace["terminal_id"]:
                terminal_ids.append(str(trace["terminal_id"]))
            terminal_types.append(str(trace["terminal_type"]))
            risk_flags.extend(str(item) for item in trace["risk_flags"])

        support_roads = _ordered_unique(support_road_ids)
        support_nodes = _ordered_unique(support_node_ids)
        unique_terminals = tuple(sorted(set(terminal_ids)))
        unique_terminal_types = tuple(sorted(set(terminal_types)))
        seed_set = set(seed_ids)
        has_extended = any(road_id not in seed_set for road_id in support_roads)
        if not seed_ids:
            status = "no_seed"
            risk_flags.append("corridor_no_seed")
        elif any(flag.startswith("corridor_ambiguous") for flag in risk_flags):
            status = "ambiguous"
        elif has_extended:
            status = "extended"
        else:
            status = "seed_only"
            risk_flags.append("corridor_seed_only")
        if len(unique_terminals) > 1:
            risk_flags.append("corridor_multiple_terminals")

        evidence.append(
            ArmCorridorEvidence(
                dataset=dataset,
                current_junction_id=junction_id,
                final_arm_id=arm.final_arm_id,
                source_seed_road_ids=tuple(sorted(set(seed_ids))),
                support_road_ids=support_roads,
                support_node_ids=support_nodes,
                corridor_terminal_junction_id=unique_terminals[0] if len(unique_terminals) == 1 else None,
                corridor_terminal_type=unique_terminal_types[0] if len(unique_terminal_types) == 1 else "mixed",
                corridor_angle_deg=_mean_angle(angles),
                corridor_length=round(sum(float(roads[road_id].geometry.length) for road_id in support_roads if road_id in roads), 3),
                corridor_status=status,
                risk_flags=tuple(sorted(set(risk_flags))),
            )
        )
    return tuple(evidence)
