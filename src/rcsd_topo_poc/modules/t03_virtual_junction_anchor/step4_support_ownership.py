from __future__ import annotations

from typing import Any

from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from .case_models import NodeRecord, RoadRecord
from .id_utils import stable_id_key


def _largest_line(geometry: BaseGeometry) -> LineString | None:
    if isinstance(geometry, LineString):
        return geometry
    if hasattr(geometry, "geoms"):
        lines = [
            line
            for item in geometry.geoms
            if (line := _largest_line(item)) is not None
        ]
        return max(lines, key=lambda line: line.length) if lines else None
    return None


def _support_graph(
    roads: list[RoadRecord],
) -> tuple[dict[str, int], dict[str, int]]:
    node_to_roads: dict[str, set[str]] = {}
    road_by_id = {road.road_id: road for road in roads}
    for road in roads:
        for node_id in (road.snodeid, road.enodeid):
            if node_id not in (None, ""):
                node_to_roads.setdefault(str(node_id), set()).add(road.road_id)
    road_adjacency = {road_id: set() for road_id in road_by_id}
    for road_ids in node_to_roads.values():
        for road_id in road_ids:
            road_adjacency[road_id].update(road_ids - {road_id})
    component_by_road: dict[str, int] = {}
    for road_id in sorted(road_by_id, key=stable_id_key):
        if road_id in component_by_road:
            continue
        component_id = len(set(component_by_road.values()))
        pending = [road_id]
        while pending:
            current = pending.pop()
            if current in component_by_road:
                continue
            component_by_road[current] = component_id
            pending.extend(road_adjacency[current] - set(component_by_road))
    node_degree = {node_id: len(road_ids) for node_id, road_ids in node_to_roads.items()}
    return component_by_road, node_degree


def evaluate_class_b_support_ownership(
    *,
    target_nodes: list[NodeRecord],
    support_roads: list[RoadRecord],
    target_distance_tolerance_m: float,
    endpoint_tolerance_m: float,
    distributed_canonical_group_ids: list[str] | None = None,
) -> dict[str, Any]:
    component_by_road, node_degree = _support_graph(support_roads)
    target_rows: list[dict[str, Any]] = []
    issue_codes: set[str] = set()
    owned_components: set[int] = set()
    ordered_roads = sorted(support_roads, key=lambda road: stable_id_key(road.road_id))
    for node in target_nodes:
        if not ordered_roads:
            issue_codes.add("support_carrier_missing")
            target_rows.append(
                {
                    "target_node_id": node.node_id,
                    "nearest_road_id": None,
                    "distance_m": None,
                    "component_id": None,
                    "projection_mode": "missing",
                    "endpoint_node_id": None,
                    "endpoint_support_degree": None,
                    "owned": False,
                }
            )
            continue
        nearest_road = min(
            ordered_roads,
            key=lambda road: (road.geometry.distance(node.geometry), stable_id_key(road.road_id)),
        )
        distance_m = float(nearest_road.geometry.distance(node.geometry))
        component_id = component_by_road[nearest_road.road_id]
        owned_components.add(component_id)
        line = _largest_line(nearest_road.geometry)
        projection_mode = "interior"
        endpoint_node_id = None
        endpoint_support_degree = None
        if line is not None and not line.is_empty:
            projected = nearest_points(node.geometry, line)[1]
            start_point = Point(line.coords[0])
            end_point = Point(line.coords[-1])
            start_distance = float(projected.distance(start_point))
            end_distance = float(projected.distance(end_point))
            if min(start_distance, end_distance) <= endpoint_tolerance_m:
                if start_distance <= end_distance:
                    endpoint_node_id = nearest_road.snodeid
                else:
                    endpoint_node_id = nearest_road.enodeid
                endpoint_support_degree = node_degree.get(str(endpoint_node_id), 0)
                projection_mode = "shared_endpoint" if endpoint_support_degree >= 2 else "terminal_endpoint"
        target_rows.append(
            {
                "target_node_id": node.node_id,
                "nearest_road_id": nearest_road.road_id,
                "distance_m": round(distance_m, 6),
                "component_id": component_id,
                "projection_mode": projection_mode,
                "endpoint_node_id": endpoint_node_id,
                "endpoint_support_degree": endpoint_support_degree,
                "within_distance_audit_threshold": (
                    distance_m <= target_distance_tolerance_m
                ),
                "owned": True,
            }
        )
    support_component_count = len(set(component_by_road.values()))
    if (
        len(owned_components) > 1
        and support_component_count > max(2, len(target_nodes))
    ):
        issue_codes.add("targets_project_to_disconnected_support_components")
    if (
        support_component_count == 1
        and len(target_rows) >= 2
        and target_rows
        and not any(row["within_distance_audit_threshold"] for row in target_rows)
    ):
        issue_codes.add("target_outside_local_support_ownership")
    terminal_rows = [
        row for row in target_rows if row["projection_mode"] == "terminal_endpoint"
    ]
    terminal_endpoint_ids = {
        row["endpoint_node_id"]
        for row in terminal_rows
        if row["endpoint_node_id"] not in (None, "")
    }
    if (
        support_component_count == 1
        and len(target_rows) >= 2
        and len(terminal_rows) == len(target_rows)
        and len(terminal_endpoint_ids) == 1
    ):
        issue_codes.add("target_projects_to_terminal_support_endpoint")
        for row in target_rows:
            if row["projection_mode"] == "terminal_endpoint":
                row["owned"] = False
    raw_issue_codes = sorted(issue_codes)
    canonical_group_ids = sorted(
        set(distributed_canonical_group_ids or []),
        key=stable_id_key,
    )
    if (
        canonical_group_ids
        and issue_codes == {"targets_project_to_disconnected_support_components"}
    ):
        issue_codes.clear()
    owned = not issue_codes
    return {
        "mode": "class_b_local_support_ownership",
        "target_distance_tolerance_m": target_distance_tolerance_m,
        "target_distance_gate_role": "audit_only_except_single_component_without_local_target",
        "terminal_endpoint_gate_role": (
            "hard_only_when_multiple_target_aliases_collapse_to_one_terminal_endpoint"
        ),
        "endpoint_tolerance_m": endpoint_tolerance_m,
        "support_road_count": len(support_roads),
        "support_component_count": support_component_count,
        "support_component_by_road_id": component_by_road,
        "target_projection_rows": target_rows,
        "raw_issue_codes": raw_issue_codes,
        "issue_codes": sorted(issue_codes),
        "distributed_canonical_group_ids": canonical_group_ids,
        "ownership_basis": (
            "distributed_canonical_mainnode_external_arm_evidence"
            if canonical_group_ids and not issue_codes and raw_issue_codes
            else "raw_support_topology"
        ),
        "owned": owned,
        "silent_fix": False,
        "source_geometry_modified": False,
    }
