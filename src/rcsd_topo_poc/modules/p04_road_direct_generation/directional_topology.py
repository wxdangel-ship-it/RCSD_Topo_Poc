from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import geopandas as gpd
from shapely.geometry import LineString, Point
from shapely.ops import substring


@dataclass(frozen=True)
class DirectionalTopologyResult:
    portals: gpd.GeoDataFrame
    arms: gpd.GeoDataFrame
    summary: dict[str, Any]


def build_directional_topology(
    road_candidates: gpd.GeoDataFrame,
    *,
    run_id: str,
    arm_length_m: float = 10.0,
) -> DirectionalTopologyResult:
    portal_rows: list[dict[str, Any]] = []
    arm_rows: list[dict[str, Any]] = []
    for road in road_candidates.itertuples(index=False):
        child_id = str(road.directional_road_id)
        length = float(road.geometry.length)
        for endpoint, coordinate_index, parent_junction, flow_role in (
            ("s", 0, road.semantic_snode_id, "outgoing"),
            ("e", -1, road.semantic_enode_id, "incoming"),
        ):
            point = Point(road.geometry.coords[coordinate_index])
            portal_id = f"{child_id}:{endpoint}"
            physical_node_id = getattr(
                road,
                "snode_id" if endpoint == "s" else "enode_id",
                "",
            )
            endpoint_source = getattr(
                road,
                "start_endpoint_source" if endpoint == "s" else "end_endpoint_source",
                "road_geometry_retained",
            )
            portal_rows.append(
                {
                    "run_id": run_id,
                    "directional_portal_id": portal_id,
                    "directional_road_id": child_id,
                    "parent_swsd_unit_id": str(road.parent_swsd_unit_id),
                    "parent_semantic_junction_id": ""
                    if parent_junction is None
                    else str(parent_junction),
                    "parent_physical_node_id": ""
                    if physical_node_id is None
                    else str(physical_node_id),
                    "endpoint": endpoint,
                    "travel_side": str(road.travel_side),
                    "flow_role": flow_role,
                    "decision": "directional_portal_v2",
                    "coordinate_source": str(endpoint_source),
                    "reason_codes": "coordinated_road_endpoint_portal",
                    "geometry": point,
                }
            )
            if endpoint == "s":
                arm_geometry = substring(road.geometry, 0.0, min(length, arm_length_m))
            else:
                arm_geometry = substring(road.geometry, max(0.0, length - arm_length_m), length)
            if arm_geometry.geom_type == "Point":
                arm_geometry = LineString([arm_geometry, arm_geometry])
            arm_rows.append(
                {
                    "run_id": run_id,
                    "directional_arm_id": portal_id,
                    "directional_portal_id": portal_id,
                    "directional_road_id": child_id,
                    "parent_swsd_unit_id": str(road.parent_swsd_unit_id),
                    "parent_semantic_junction_id": ""
                    if parent_junction is None
                    else str(parent_junction),
                    "parent_physical_node_id": ""
                    if physical_node_id is None
                    else str(physical_node_id),
                    "endpoint": endpoint,
                    "travel_side": str(road.travel_side),
                    "flow_role": flow_role,
                    "direction": int(road.direction) if road.direction is not None else None,
                    "decision": "directional_arm_v2",
                    "coordinate_source": str(endpoint_source),
                    "reason_codes": "coordinated_road_endpoint_arm",
                    "geometry": arm_geometry,
                }
            )
    portals = gpd.GeoDataFrame(portal_rows, geometry="geometry", crs=road_candidates.crs)
    arms = gpd.GeoDataFrame(arm_rows, geometry="geometry", crs=road_candidates.crs)
    return DirectionalTopologyResult(
        portals=portals,
        arms=arms,
        summary=_summary(road_candidates, portals, arms),
    )


def _summary(
    roads: gpd.GeoDataFrame,
    portals: gpd.GeoDataFrame,
    arms: gpd.GeoDataFrame,
) -> dict[str, Any]:
    expected = {
        (str(road_id), endpoint)
        for road_id in roads["directional_road_id"]
        for endpoint in ("s", "e")
    }
    portal_keys = list(zip(portals["directional_road_id"].astype(str), portals["endpoint"].astype(str)))
    arm_keys = list(zip(arms["directional_road_id"].astype(str), arms["endpoint"].astype(str)))
    road_by_id = roads.set_index("directional_road_id")
    portal_deltas = []
    arm_deltas = []
    for row in portals.itertuples(index=False):
        road = road_by_id.loc[str(row.directional_road_id)]
        point = Point(road.geometry.coords[0 if str(row.endpoint) == "s" else -1])
        portal_deltas.append(float(point.distance(row.geometry)))
    for row in arms.itertuples(index=False):
        road = road_by_id.loc[str(row.directional_road_id)]
        point = Point(road.geometry.coords[0 if str(row.endpoint) == "s" else -1])
        candidates = (Point(row.geometry.coords[0]), Point(row.geometry.coords[-1]))
        arm_deltas.append(min(float(point.distance(candidate)) for candidate in candidates))
    reverse = roads[roads["travel_side"] == "reverse"]
    reverse_direction_encoding_count = int((reverse["direction"] == 2).sum())
    gates = {
        "road_id_unique": bool(roads["directional_road_id"].is_unique),
        "portal_complete_unique": len(portal_keys) == len(expected) and set(portal_keys) == expected,
        "arm_complete_unique": len(arm_keys) == len(expected) and set(arm_keys) == expected,
        "portal_endpoint_closed": max(portal_deltas, default=float("inf")) <= 1e-8,
        "arm_endpoint_closed": max(arm_deltas, default=float("inf")) <= 1e-8,
        "reverse_single_direction_encoding": reverse_direction_encoding_count == len(reverse),
    }
    return {
        "road_count": int(len(roads)),
        "portal_count": int(len(portals)),
        "arm_count": int(len(arms)),
        "expected_portal_count": int(len(expected)),
        "duplicate_portal_key_count": int(len(portal_keys) - len(set(portal_keys))),
        "duplicate_arm_key_count": int(len(arm_keys) - len(set(arm_keys))),
        "road_portal_max_delta_m": max(portal_deltas, default=float("inf")),
        "road_arm_max_delta_m": max(arm_deltas, default=float("inf")),
        "reverse_road_count": int(len(reverse)),
        "reverse_single_direction_encoding_count": reverse_direction_encoding_count,
        "gates": gates,
        "road_topology_gate_pass": all(gates.values()),
        "gate_scope": "road_to_own_portal_and_arm_only; cross_road closure is gated by directional_movement",
    }


__all__ = ["DirectionalTopologyResult", "build_directional_topology"]
