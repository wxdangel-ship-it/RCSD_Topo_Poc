from __future__ import annotations

from math import acos, degrees, hypot
from typing import Any, Optional

from rcsd_topo_poc.modules.t01_data_preprocess.step1_pair_poc import (
    RoadRecord,
    Step1GraphContext,
    _sort_key,
)
from rcsd_topo_poc.modules.t01_data_preprocess.step2_geometry_utils import (
    geometry_coords,
)


INTERNAL_TURN_ANGLE_CONFLICT_THRESHOLD_DEG = 60.0
INTERNAL_TURN_GATE_MIN_INCIDENT_ROAD_COUNT = 3
INTERNAL_TURN_GATE_JUNCTION_KIND_2 = {4, 64, 128, 2048}


def _bit_enabled(value: Optional[int], bit_index: int) -> bool:
    if value is None:
        return False
    return bool(value & (1 << bit_index))


def _road_matches_any_formway_bits(road: RoadRecord, bits: tuple[int, ...]) -> bool:
    if not bits or road.formway is None:
        return False
    return any(_bit_enabled(road.formway, bit_index) for bit_index in bits)


def _incident_road_ids(
    node_id: str,
    *,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    exclude_formway_bits_any: tuple[int, ...],
) -> tuple[str, ...]:
    road_ids: list[str] = []
    for road_id, endpoints in road_endpoints.items():
        if node_id not in endpoints:
            continue
        road = context.roads.get(road_id)
        if road is None:
            continue
        if _road_matches_any_formway_bits(road, exclude_formway_bits_any):
            continue
        road_ids.append(road_id)
    return tuple(sorted(set(road_ids), key=_sort_key))


def _is_turn_gate_node(
    node_id: str,
    *,
    context: Step1GraphContext,
    incident_road_ids: tuple[str, ...],
) -> bool:
    if len(incident_road_ids) < INTERNAL_TURN_GATE_MIN_INCIDENT_ROAD_COUNT:
        return False
    node = context.semantic_nodes.get(node_id)
    if node is None:
        return False
    kind_2 = int(node.kind_2 or 0)
    grade_2 = int(node.grade_2 or 0)
    closed_con = int(node.closed_con or 0)
    return kind_2 in INTERNAL_TURN_GATE_JUNCTION_KIND_2 and grade_2 >= 1 and closed_con in {2, 3}


def _oriented_road_coords(
    road: RoadRecord,
    *,
    from_node_id: str,
    to_node_id: str,
    road_endpoints: dict[str, tuple[str, str]],
) -> list[tuple[float, float]]:
    coords = geometry_coords(road.geometry)
    endpoints = road_endpoints.get(road.road_id)
    if endpoints is None:
        return coords
    semantic_snode_id, semantic_enode_id = endpoints
    if (from_node_id, to_node_id) == (semantic_snode_id, semantic_enode_id):
        return coords
    if (from_node_id, to_node_id) == (semantic_enode_id, semantic_snode_id):
        return list(reversed(coords))
    return coords


def _angle_between_vectors_deg(
    left: tuple[float, float],
    right: tuple[float, float],
) -> Optional[float]:
    left_len = hypot(left[0], left[1])
    right_len = hypot(right[0], right[1])
    if left_len <= 0.0 or right_len <= 0.0:
        return None
    dot = max(-1.0, min(1.0, ((left[0] * right[0]) + (left[1] * right[1])) / (left_len * right_len)))
    return degrees(acos(dot))


def _path_turn_angle_deg(
    path: Any,
    *,
    node_index: int,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
) -> Optional[float]:
    incoming_road_id = path.road_ids[node_index - 1]
    outgoing_road_id = path.road_ids[node_index]
    incoming_road = context.roads.get(incoming_road_id)
    outgoing_road = context.roads.get(outgoing_road_id)
    if incoming_road is None or outgoing_road is None:
        return None

    incoming_coords = _oriented_road_coords(
        incoming_road,
        from_node_id=path.node_ids[node_index - 1],
        to_node_id=path.node_ids[node_index],
        road_endpoints=road_endpoints,
    )
    outgoing_coords = _oriented_road_coords(
        outgoing_road,
        from_node_id=path.node_ids[node_index],
        to_node_id=path.node_ids[node_index + 1],
        road_endpoints=road_endpoints,
    )
    if len(incoming_coords) < 2 or len(outgoing_coords) < 2:
        return None

    incoming_vector = (
        incoming_coords[-1][0] - incoming_coords[-2][0],
        incoming_coords[-1][1] - incoming_coords[-2][1],
    )
    outgoing_vector = (
        outgoing_coords[1][0] - outgoing_coords[0][0],
        outgoing_coords[1][1] - outgoing_coords[0][1],
    )
    return _angle_between_vectors_deg(incoming_vector, outgoing_vector)


def _path_internal_turn_conflicts(
    path: Any,
    *,
    path_label: str,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    exclude_formway_bits_any: tuple[int, ...],
    threshold_deg: float,
) -> list[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    if len(path.node_ids) != len(path.road_ids) + 1:
        return conflicts
    for node_index in range(1, len(path.node_ids) - 1):
        node_id = path.node_ids[node_index]
        incident_road_ids = _incident_road_ids(
            node_id,
            context=context,
            road_endpoints=road_endpoints,
            exclude_formway_bits_any=exclude_formway_bits_any,
        )
        if not _is_turn_gate_node(node_id, context=context, incident_road_ids=incident_road_ids):
            continue
        turn_angle_deg = _path_turn_angle_deg(
            path,
            node_index=node_index,
            context=context,
            road_endpoints=road_endpoints,
        )
        if turn_angle_deg is None or turn_angle_deg <= threshold_deg:
            continue
        node = context.semantic_nodes.get(node_id)
        conflicts.append(
            {
                "path_label": path_label,
                "node_id": node_id,
                "incoming_road_id": path.road_ids[node_index - 1],
                "outgoing_road_id": path.road_ids[node_index],
                "turn_angle_deg": round(turn_angle_deg, 6),
                "turn_angle_threshold_deg": threshold_deg,
                "incident_road_count": len(incident_road_ids),
                "incident_road_ids": list(incident_road_ids),
                "node_grade_2": None if node is None else node.grade_2,
                "node_kind_2": None if node is None else node.kind_2,
                "node_closed_con": None if node is None else node.closed_con,
            }
        )
    return conflicts


def internal_turn_angle_gate_info(
    candidate: Any,
    *,
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    exclude_formway_bits_any: tuple[int, ...] = (),
    threshold_deg: float = INTERNAL_TURN_ANGLE_CONFLICT_THRESHOLD_DEG,
) -> Optional[dict[str, Any]]:
    conflicts: list[dict[str, Any]] = []
    conflicts.extend(
        _path_internal_turn_conflicts(
            candidate.forward_path,
            path_label="forward",
            context=context,
            road_endpoints=road_endpoints,
            exclude_formway_bits_any=exclude_formway_bits_any,
            threshold_deg=threshold_deg,
        )
    )
    conflicts.extend(
        _path_internal_turn_conflicts(
            candidate.reverse_path,
            path_label="reverse",
            context=context,
            road_endpoints=road_endpoints,
            exclude_formway_bits_any=exclude_formway_bits_any,
            threshold_deg=threshold_deg,
        )
    )
    if not conflicts:
        return None

    first = conflicts[0]
    return {
        "internal_turn_angle_blocked": True,
        "internal_turn_angle_threshold_deg": threshold_deg,
        "internal_turn_angle_conflict_count": len(conflicts),
        "internal_turn_angle_conflicts": conflicts,
        "internal_turn_angle_node_id": first["node_id"],
        "internal_turn_angle_deg": first["turn_angle_deg"],
        "internal_turn_angle_incoming_road_id": first["incoming_road_id"],
        "internal_turn_angle_outgoing_road_id": first["outgoing_road_id"],
        "internal_turn_angle_incident_road_count": first["incident_road_count"],
        "internal_turn_angle_incident_road_ids": first["incident_road_ids"],
    }


def split_internal_turn_angle_candidates(
    *,
    candidates: list[Any],
    context: Step1GraphContext,
    road_endpoints: dict[str, tuple[str, str]],
    exclude_formway_bits_any: tuple[int, ...],
) -> tuple[list[Any], list[tuple[Any, dict[str, Any]]]]:
    kept: list[Any] = []
    blocked: list[tuple[Any, dict[str, Any]]] = []
    for candidate in candidates:
        gate_info = internal_turn_angle_gate_info(
            candidate,
            context=context,
            road_endpoints=road_endpoints,
            exclude_formway_bits_any=exclude_formway_bits_any,
        )
        if gate_info is None:
            kept.append(candidate)
        else:
            blocked.append((candidate, gate_info))
    return kept, blocked
