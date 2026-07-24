from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point

from .directional_movement import (
    _build_road_movements,
    _summary,
    build_directional_movements,
)
from .high_precision_config import HighPrecisionRoadV3Config


@dataclass(frozen=True)
class HighPrecisionMovementResult:
    road_candidates: gpd.GeoDataFrame
    evidence_links: gpd.GeoDataFrame
    road_movements: gpd.GeoDataFrame
    endpoint_audit: gpd.GeoDataFrame
    summary: dict[str, Any]


def build_high_precision_movements(
    road_candidates: gpd.GeoDataFrame,
    lane_group_members: gpd.GeoDataFrame,
    lane_topology: gpd.GeoDataFrame,
    fit_stations: gpd.GeoDataFrame,
    parent_roads: gpd.GeoDataFrame,
    *,
    config: HighPrecisionRoadV3Config,
) -> HighPrecisionMovementResult:
    roads = road_candidates.copy()
    roads["directional_road_id"] = roads["v3_road_id"].astype(str)
    parent_lengths = parent_roads.set_index("swsd_unit_id").geometry.length.to_dict()
    if "swsd_reference_length_m" not in roads.columns:
        roads["swsd_reference_length_m"] = roads["parent_swsd_unit_id"].map(
            lambda value: float(parent_lengths.get(str(value), 0.0))
        )

    members = lane_group_members.copy()
    members["directional_road_id"] = members["v3_road_id"].astype(str)

    stations = fit_stations.copy()
    stations["directional_road_id"] = stations["v3_road_id"].astype(str)
    stations["travel_station_fraction"] = stations["station_fraction"].astype(float)
    stations["support_at_station"] = (
        stations["geometry_source"].astype(str) != "swsd_fallback"
    )

    result = build_directional_movements(
        roads,
        members,
        lane_topology,
        stations,
        parent_roads,
        config=_movement_config(config),
    )
    coordinated, endpoint_audit = _local_endpoint_coordination(
        roads,
        result.endpoint_audit,
        config=config,
    )
    confirmed = result.evidence_links[
        result.evidence_links["projection_state"] == "confirmed"
    ].copy()
    road_movements = _build_road_movements(
        confirmed,
        coordinated,
        evidence_geometry_max_distance_m=config.movement_evidence_geometry_max_distance_m,
        max_join_angle_deg=config.movement_max_join_angle_deg,
        curve_sample_spacing_m=config.movement_curve_sample_spacing_m,
        run_id=config.run_id,
    )
    road_movements = _replace_physical_portal_connectors(
        road_movements,
        coordinated,
    )
    summary = _summary(
        coordinated,
        result.evidence_links,
        road_movements,
        endpoint_audit,
        physical_node_tolerance_m=config.physical_node_coordination_trigger_m,
        movement_join_angle_deg=config.movement_max_join_angle_deg,
    )
    coordinated = coordinated.drop(columns=["directional_road_id"]).copy()
    evidence = _rename_directional_columns(result.evidence_links)
    movements = _rename_directional_columns(road_movements)
    endpoint_audit = _rename_directional_columns(endpoint_audit)
    return HighPrecisionMovementResult(
        road_candidates=coordinated,
        evidence_links=evidence,
        road_movements=movements,
        endpoint_audit=endpoint_audit,
        summary={
            **summary,
            "movement_model": "v3_physical_road_lane_topo_projection",
        },
    )


def _local_endpoint_coordination(
    roads: gpd.GeoDataFrame,
    audit: gpd.GeoDataFrame,
    *,
    config: HighPrecisionRoadV3Config,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    targets: dict[tuple[str, str], tuple[Point, str]] = {}
    for row in audit.itertuples(index=False):
        source = str(row.coordinate_source)
        if source in {
            "physical_node_global_shared_portal",
            "swsd_physical_node_global_transition",
        }:
            targets[(str(row.directional_road_id), str(row.endpoint))] = (
                row.geometry,
                source,
            )
    result = roads.copy().reset_index(drop=True)
    geometries: list[LineString] = []
    start_sources: list[str] = []
    end_sources: list[str] = []
    start_shifts: list[float] = []
    end_shifts: list[float] = []
    states: list[str] = []
    audit_rows: list[dict[str, Any]] = []
    for row in result.itertuples(index=False):
        road_id = str(row.directional_road_id)
        original = row.geometry
        start = targets.get((road_id, "s"))
        end = targets.get((road_id, "e"))
        adjusted = _retarget_local(
            original,
            start_target=None if start is None else start[0],
            end_target=None if end is None else end[0],
            config=config,
        )
        state = "coordinated" if start is not None or end is not None else "not_required"
        if not adjusted.is_valid or not adjusted.is_simple:
            adjusted = original
            state = "rejected_invalid_geometry"
            start = None
            end = None
        start_source = "road_geometry_retained" if start is None else start[1]
        end_source = "road_geometry_retained" if end is None else end[1]
        start_shift = Point(original.coords[0]).distance(Point(adjusted.coords[0]))
        end_shift = Point(original.coords[-1]).distance(Point(adjusted.coords[-1]))
        geometries.append(adjusted)
        start_sources.append(start_source)
        end_sources.append(end_source)
        start_shifts.append(float(start_shift))
        end_shifts.append(float(end_shift))
        states.append(state)
        for endpoint, source, shift, point, node, semantic in (
            (
                "s",
                start_source,
                start_shift,
                Point(adjusted.coords[0]),
                row.snode_id,
                row.semantic_snode_id,
            ),
            (
                "e",
                end_source,
                end_shift,
                Point(adjusted.coords[-1]),
                row.enode_id,
                row.semantic_enode_id,
            ),
        ):
            audit_rows.append(
                {
                    "run_id": config.run_id,
                    "directional_road_id": road_id,
                    "parent_swsd_unit_id": str(row.parent_swsd_unit_id),
                    "endpoint": endpoint,
                    "physical_node_id": str(node),
                    "semantic_junction_id": str(semantic),
                    "coordination_state": state,
                    "coordinate_source": source,
                    "endpoint_shift_m": float(shift),
                    "geometry": point,
                }
            )
    result.geometry = geometries
    result["start_endpoint_source"] = start_sources
    result["end_endpoint_source"] = end_sources
    result["start_endpoint_coordination_shift_m"] = start_shifts
    result["end_endpoint_coordination_shift_m"] = end_shifts
    result["endpoint_coordination_state"] = states
    result["candidate_length_m"] = result.geometry.length
    result["candidate_length_ratio"] = result["candidate_length_m"] / result[
        "swsd_reference_length_m"
    ].astype(float).replace(0, np.nan)
    result["geometry_valid"] = result.geometry.is_valid
    result["geometry_simple"] = result.geometry.is_simple
    endpoint_audit = gpd.GeoDataFrame(
        audit_rows,
        geometry="geometry",
        crs=roads.crs,
    )
    return result, endpoint_audit


def _retarget_local(
    geometry: LineString,
    *,
    start_target: Point | None,
    end_target: Point | None,
    config: HighPrecisionRoadV3Config,
) -> LineString:
    if start_target is None and end_target is None:
        return geometry
    length = float(geometry.length)
    start_delta = np.asarray(
        [0.0, 0.0]
        if start_target is None
        else [start_target.x - geometry.coords[0][0], start_target.y - geometry.coords[0][1]],
        dtype=float,
    )
    end_delta = np.asarray(
        [0.0, 0.0]
        if end_target is None
        else [end_target.x - geometry.coords[-1][0], end_target.y - geometry.coords[-1][1]],
        dtype=float,
    )
    both = start_target is not None and end_target is not None
    cap_ratio = (
        config.endpoint_both_transition_cap_ratio
        if both
        else config.endpoint_single_transition_cap_ratio
    )
    start_transition = _transition_length(start_delta, length, cap_ratio, config)
    end_transition = _transition_length(end_delta, length, cap_ratio, config)
    sample_count = max(
        2,
        int(
            np.ceil(
                length / max(config.endpoint_geometry_sample_spacing_m, 0.1)
            )
        )
        + 1,
    )
    stations = sorted(
        set(float(value) for value in np.linspace(0.0, length, sample_count))
        | {
            float(geometry.project(Point(coordinate[:2])))
            for coordinate in geometry.coords
        }
    )
    coordinates: list[tuple[float, float]] = []
    for station in stations:
        coordinate = geometry.interpolate(station).coords[0]
        value = np.asarray(coordinate[:2], dtype=float)
        if start_target is not None and station <= start_transition:
            ratio = min(max(station / max(start_transition, 1e-9), 0.0), 1.0)
            value += start_delta * (1.0 - (3.0 * ratio**2 - 2.0 * ratio**3))
        if end_target is not None and length - station <= end_transition:
            ratio = min(
                max((length - station) / max(end_transition, 1e-9), 0.0),
                1.0,
            )
            value += end_delta * (1.0 - (3.0 * ratio**2 - 2.0 * ratio**3))
        coordinates.append((float(value[0]), float(value[1])))
    if start_target is not None:
        coordinates[0] = (float(start_target.x), float(start_target.y))
    if end_target is not None:
        coordinates[-1] = (float(end_target.x), float(end_target.y))
    return LineString(_dedupe(coordinates))


def _replace_physical_portal_connectors(
    movements: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    result = movements.copy()
    road_by_id = roads.set_index("directional_road_id", drop=False)
    geometries: list[LineString] = []
    sources: list[str] = []
    for movement in result.itertuples(index=False):
        physical = str(movement.junction_relation) == "same_physical_node"
        failed_semantic = (
            "non_simple_straight_fallback" in str(movement.geometry_source)
        )
        if not physical and not failed_semantic:
            geometries.append(movement.geometry)
            sources.append(str(movement.geometry_source))
            continue
        source = road_by_id.loc[str(movement.source_directional_road_id)].geometry
        target = road_by_id.loc[str(movement.target_directional_road_id)].geometry
        sample = min(0.5, float(source.length) * 0.25, float(target.length) * 0.25)
        source_inside = source.interpolate(max(0.0, float(source.length) - sample))
        source_portal = Point(source.coords[-1])
        target_portal = Point(target.coords[0])
        target_inside = target.interpolate(min(float(target.length), sample))
        coordinates = [
            (float(source_inside.x), float(source_inside.y)),
            (float(source_portal.x), float(source_portal.y)),
        ]
        if not physical or source_portal.distance(target_portal) > 1e-8:
            coordinates.append((float(target_portal.x), float(target_portal.y)))
        coordinates.append((float(target_inside.x), float(target_inside.y)))
        connector = LineString(_dedupe(coordinates))
        if connector.is_valid and connector.is_simple:
            geometries.append(connector)
            sources.append(
                "lane_topo_physical_portal_spanning_connector"
                if physical
                else "lane_topo_semantic_portal_spanning_fallback"
            )
        else:
            geometries.append(movement.geometry)
            sources.append(str(movement.geometry_source))
    result.geometry = geometries
    result["geometry_source"] = sources
    return result


def _transition_length(
    delta: np.ndarray,
    road_length: float,
    cap_ratio: float,
    config: HighPrecisionRoadV3Config,
) -> float:
    required = 1.5 * float(np.linalg.norm(delta)) / max(config.max_lateral_slope, 1e-6)
    return min(
        max(config.endpoint_transition_length_m, required),
        max(road_length * cap_ratio, 1e-6),
    )


def _dedupe(coordinates: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for coordinate in coordinates:
        if not result or Point(result[-1]).distance(Point(coordinate)) > 1e-9:
            result.append(coordinate)
    if len(result) == 1:
        result.append(result[0])
    return result


def _movement_config(config: HighPrecisionRoadV3Config) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=config.run_id,
        # V3 coordinates every non-coincident physical portal.  The looser
        # public QA tolerance remains a readback threshold, not a reason to
        # preserve a small LaneTopo movement gap in the published RoadGraph.
        physical_node_snap_tolerance_m=config.physical_node_coordination_trigger_m,
        endpoint_transition_length_m=config.endpoint_transition_length_m,
        max_lateral_slope=config.max_lateral_slope,
        movement_evidence_geometry_max_distance_m=config.movement_evidence_geometry_max_distance_m,
        movement_max_join_angle_deg=config.movement_max_join_angle_deg,
        movement_curve_sample_spacing_m=config.movement_curve_sample_spacing_m,
    )


def _rename_directional_columns(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    mapping = {
        column: column.replace("directional_road_id", "v3_road_id")
        for column in frame.columns
        if "directional_road_id" in column
    }
    return frame.rename(columns=mapping)


__all__ = ["HighPrecisionMovementResult", "build_high_precision_movements"]
