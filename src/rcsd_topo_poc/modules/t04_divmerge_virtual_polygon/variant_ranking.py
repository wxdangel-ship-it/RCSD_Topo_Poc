from __future__ import annotations

import math
from typing import Any

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_shared import normalize_id
from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon._runtime_types_io import (
    ParsedRoad,
    _angle_diff_deg,
)

from .case_models import T04CaseBundle


def _road_other_node_id(road: ParsedRoad, node_id: str) -> str | None:
    if str(road.snodeid) == str(node_id):
        return str(road.enodeid)
    if str(road.enodeid) == str(node_id):
        return str(road.snodeid)
    return None


def _same_case_internal_member_node(*, node, mainnodeid: str, representative_node_id: str) -> bool:
    if node is None:
        return False
    if str(node.node_id) == str(representative_node_id):
        return False
    if node.has_evd != "yes" or node.is_anchor != "no":
        return False
    return normalize_id(node.mainnodeid or node.node_id) == normalize_id(mainnodeid)


def _angle_in_minor_arc(start_deg: float, end_deg: float, test_deg: float) -> bool:
    clockwise_span = (float(end_deg) - float(start_deg)) % 360.0
    counterclockwise_span = (float(start_deg) - float(end_deg)) % 360.0
    if clockwise_span <= counterclockwise_span:
        return ((float(test_deg) - float(start_deg)) % 360.0) <= clockwise_span + 1e-9
    return ((float(start_deg) - float(test_deg)) % 360.0) <= counterclockwise_span + 1e-9


def _terminal_external_angle_for_membership(
    *,
    branch_road_memberships: dict[str, tuple[str, ...]],
    scoped_roads: tuple[ParsedRoad, ...],
    case_bundle: T04CaseBundle,
    representative_node,
    mainnodeid: str,
    branch_id: str,
) -> float | None:
    road_ids = list(branch_road_memberships.get(str(branch_id), ()))
    if not road_ids:
        return None
    road_lookup = {str(road.road_id): road for road in scoped_roads}
    node_lookup = {str(node.node_id): node for node in case_bundle.nodes}
    terminal_road = road_lookup.get(str(road_ids[-1]))
    if terminal_road is None:
        return None
    representative_node_id = str(representative_node.node_id)
    if len(road_ids) == 1:
        external_node_id = _road_other_node_id(terminal_road, representative_node_id)
    else:
        previous_road = road_lookup.get(str(road_ids[-2]))
        if previous_road is None:
            return None
        shared_node_id = None
        for node_id in (str(terminal_road.snodeid), str(terminal_road.enodeid)):
            if node_id in {str(previous_road.snodeid), str(previous_road.enodeid)}:
                shared_node_id = node_id
                break
        if shared_node_id is None:
            return None
        external_node_id = _road_other_node_id(terminal_road, str(shared_node_id))
    if external_node_id is None:
        return None
    external_node = node_lookup.get(str(external_node_id))
    if external_node is None or external_node.geometry is None or external_node.geometry.is_empty:
        return None
    if _same_case_internal_member_node(
        node=external_node,
        mainnodeid=str(mainnodeid),
        representative_node_id=str(representative_node.node_id),
    ):
        return None
    anchor_x, anchor_y = representative_node.geometry.coords[0]
    target_x, target_y = external_node.geometry.coords[0]
    angle_deg = math.degrees(math.atan2(float(target_y) - float(anchor_y), float(target_x) - float(anchor_x)))
    while angle_deg < 0.0:
        angle_deg += 360.0
    while angle_deg >= 360.0:
        angle_deg -= 360.0
    return float(angle_deg)


def _pair_interval_variant_metrics_from_data(
    *,
    boundary_branch_ids: tuple[str, ...],
    scoped_branches: tuple[Any, ...],
    branch_road_memberships: dict[str, tuple[str, ...]],
    scoped_roads: tuple[ParsedRoad, ...],
    case_bundle: T04CaseBundle,
    representative_node,
    mainnodeid: str,
) -> tuple[int, int]:
    boundary_branch_ids = tuple(str(branch_id) for branch_id in boundary_branch_ids)
    if len(boundary_branch_ids) != 2:
        return 0, 0
    seed_angle_by_branch = {
        str(branch.branch_id): float(branch.angle_deg)
        for branch in scoped_branches
    }
    inside_count = 0
    gap_penalty_x10 = 0
    for branch_id, other_branch_id in (
        (boundary_branch_ids[0], boundary_branch_ids[1]),
        (boundary_branch_ids[1], boundary_branch_ids[0]),
    ):
        seed_angle = seed_angle_by_branch.get(str(branch_id))
        other_angle = seed_angle_by_branch.get(str(other_branch_id))
        terminal_angle = _terminal_external_angle_for_membership(
            branch_road_memberships=branch_road_memberships,
            scoped_roads=scoped_roads,
            case_bundle=case_bundle,
            representative_node=representative_node,
            mainnodeid=mainnodeid,
            branch_id=str(branch_id),
        )
        if seed_angle is None or other_angle is None or terminal_angle is None:
            continue
        if _angle_in_minor_arc(seed_angle, other_angle, terminal_angle):
            inside_count += 1
            continue
        gap_penalty_x10 += int(
            round(
                min(
                    float(_angle_diff_deg(seed_angle, terminal_angle)),
                    float(_angle_diff_deg(other_angle, terminal_angle)),
                )
                * 10.0
            )
        )
    return inside_count, gap_penalty_x10


def _pair_interval_variant_metrics(prepared: Any) -> tuple[int, int]:
    return _pair_interval_variant_metrics_from_data(
        boundary_branch_ids=prepared.boundary_branch_ids,
        scoped_branches=prepared.scoped_branches,
        branch_road_memberships=prepared.branch_road_memberships,
        scoped_roads=prepared.scoped_roads,
        case_bundle=prepared.case_bundle,
        representative_node=prepared.effective_representative_node,
        mainnodeid=str(prepared.unit_context.admission.mainnodeid),
    )


def _prepared_variant_rank(
    prepared: Any,
    evaluations: list[Any],
) -> tuple[int, ...]:
    best_priority = evaluations[0].priority_score if evaluations else -10_000
    degraded_reasons = list(prepared.pair_local_summary.get("degraded_reasons") or [])
    degraded_penalty = 0
    for reason in degraded_reasons:
        degraded_penalty += 80
        if reason in {"pair_local_scope_roads_empty", "pair_local_middle_missing"}:
            degraded_penalty += 160
    extra_road_count = sum(max(len(road_ids) - 1, 0) for road_ids in prepared.branch_road_memberships.values())
    bridge_count = sum(len(node_ids) for node_ids in prepared.branch_bridge_node_ids.values())
    best_priority -= int(extra_road_count) * 40
    best_priority -= int(bridge_count) * 40
    pair_scan_truncated_to_local = bool(prepared.pair_local_summary.get("pair_scan_truncated_to_local"))
    raw_inside_count, raw_gap_penalty_x10 = _pair_interval_variant_metrics(prepared)
    full_pair_interval = int(
        bool(prepared.boundary_branch_ids)
        and len(prepared.boundary_branch_ids) == 2
        and int(raw_inside_count) >= len(prepared.boundary_branch_ids)
        and int(raw_gap_penalty_x10) == 0
    )
    inside_count = int(raw_inside_count)
    gap_penalty_x10 = int(raw_gap_penalty_x10)
    if pair_scan_truncated_to_local:
        inside_count = 0
        gap_penalty_x10 = 0
    middle_area = int(round(float(prepared.pair_local_summary.get("pair_local_middle_area_m2", 0.0) or 0.0)))
    return (
        int(full_pair_interval),
        int(best_priority) - int(degraded_penalty),
        1 if not pair_scan_truncated_to_local else 0,
        -int(middle_area),
        int(inside_count),
        -int(gap_penalty_x10),
        1 if prepared.boundary_branch_ids else 0,
        -int(extra_road_count),
        -int(bridge_count),
    )
