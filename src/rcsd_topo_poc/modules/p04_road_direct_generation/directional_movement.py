from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import substring

from .directional_config import DirectionalRoadV2Config
from .geometry import canonical_id, tangent_vector


@dataclass(frozen=True)
class DirectionalMovementResult:
    road_candidates: gpd.GeoDataFrame
    evidence_links: gpd.GeoDataFrame
    road_movements: gpd.GeoDataFrame
    endpoint_audit: gpd.GeoDataFrame
    summary: dict[str, Any]


_CROSS_OWNER_STATES = {
    "cross_owner_directed_node_supported",
    "cross_owner_shared_node_review",
    "cross_owner_semantic_unconnected_review",
}


def build_directional_movements(
    road_candidates: gpd.GeoDataFrame,
    lane_group_members: gpd.GeoDataFrame,
    lane_topology: gpd.GeoDataFrame,
    fit_stations: gpd.GeoDataFrame,
    parent_roads: gpd.GeoDataFrame,
    *,
    config: DirectionalRoadV2Config,
) -> DirectionalMovementResult:
    roads = road_candidates.copy().reset_index(drop=True)
    roads["directional_road_id"] = roads["directional_road_id"].astype(str)
    road_by_id = roads.set_index("directional_road_id", drop=False)
    parent_by_id = parent_roads.copy()
    parent_by_id["swsd_unit_id"] = parent_by_id["swsd_unit_id"].map(canonical_id)
    parent_by_id = parent_by_id.set_index("swsd_unit_id", drop=False)
    members = _member_index(lane_group_members)
    endpoint_support = _endpoint_support(fit_stations)

    evidence_rows: list[dict[str, Any]] = []
    selected_links = lane_topology[
        lane_topology["lane_topo_state"].astype(str).isin(_CROSS_OWNER_STATES)
    ]
    for link in selected_links.itertuples(index=False):
        source_owner = canonical_id(link.source_owner)
        target_owner = canonical_id(link.target_owner)
        source_members = members.get((canonical_id(link.lane_id), source_owner), [])
        target_members = members.get((canonical_id(link.next_lane_id), target_owner), [])
        source = source_members[0] if len(source_members) == 1 else None
        target = target_members[0] if len(target_members) == 1 else None
        source_id = "" if source is None else str(source["directional_road_id"])
        target_id = "" if target is None else str(target["directional_road_id"])
        source_road = road_by_id.loc[source_id] if source_id in road_by_id.index else None
        target_road = road_by_id.loc[target_id] if target_id in road_by_id.index else None
        semantic_ok = bool(
            source_road is not None
            and target_road is not None
            and canonical_id(source_road.semantic_enode_id)
            == canonical_id(target_road.semantic_snode_id)
        )
        physical_ok = bool(
            semantic_ok
            and canonical_id(source_road.enode_id) == canonical_id(target_road.snode_id)
        )
        source_quality = "" if source is None else str(source["evidence_quality_state"])
        target_quality = "" if target is None else str(target["evidence_quality_state"])
        projection_state, reason_codes = _projection_state(
            input_state=str(link.lane_topo_state),
            mapping_unique=source is not None and target is not None,
            semantic_ok=semantic_ok,
            quality_usable=source_quality == "usable" and target_quality == "usable",
        )
        evidence_rows.append(
            {
                "run_id": config.run_id,
                "link_id": canonical_id(link.link_id),
                "lane_id": canonical_id(link.lane_id),
                "next_lane_id": canonical_id(link.next_lane_id),
                "source_parent_swsd_unit_id": source_owner,
                "target_parent_swsd_unit_id": target_owner,
                "source_directional_road_id": source_id,
                "target_directional_road_id": target_id,
                "source_travel_side": "" if source is None else str(source["travel_side"]),
                "target_travel_side": "" if target is None else str(target["travel_side"]),
                "source_evidence_quality_state": source_quality,
                "target_evidence_quality_state": target_quality,
                "input_lane_topo_state": str(link.lane_topo_state),
                "projection_state": projection_state,
                "junction_relation": (
                    "same_physical_node"
                    if physical_ok
                    else "same_semantic_junction"
                    if semantic_ok
                    else "unresolved"
                ),
                "semantic_junction_id": (
                    "" if source_road is None else canonical_id(source_road.semantic_enode_id)
                ),
                "physical_node_id": (
                    "" if not physical_ok else canonical_id(source_road.enode_id)
                ),
                "source_endpoint_supported": endpoint_support.get((source_id, "e"), False),
                "target_endpoint_supported": endpoint_support.get((target_id, "s"), False),
                "reason_codes": reason_codes,
                "source_patch_ids": str(link.source_patch_ids),
                "source_object_ids": canonical_id(link.link_id),
                "geometry": link.geometry,
            }
        )
    evidence = gpd.GeoDataFrame(
        evidence_rows,
        geometry="geometry",
        crs=lane_topology.crs,
    )
    confirmed = evidence[evidence["projection_state"] == "confirmed"].copy()
    endpoint_targets, coordination_sources = _physical_endpoint_targets(
        roads,
        confirmed,
        endpoint_support,
        parent_by_id,
        snap_tolerance_m=config.physical_node_snap_tolerance_m,
    )
    coordinated_roads, endpoint_audit = _coordinate_road_endpoints(
        roads,
        endpoint_targets,
        coordination_sources,
        parent_by_id,
        transition_length_m=config.endpoint_transition_length_m,
        max_lateral_slope=config.max_lateral_slope,
        run_id=config.run_id,
    )
    movements = _build_road_movements(
        confirmed,
        coordinated_roads,
        evidence_geometry_max_distance_m=config.movement_evidence_geometry_max_distance_m,
        max_join_angle_deg=config.movement_max_join_angle_deg,
        curve_sample_spacing_m=config.movement_curve_sample_spacing_m,
        run_id=config.run_id,
    )
    summary = _summary(
        coordinated_roads,
        evidence,
        movements,
        endpoint_audit,
        physical_node_tolerance_m=config.physical_node_snap_tolerance_m,
        movement_join_angle_deg=config.movement_max_join_angle_deg,
    )
    return DirectionalMovementResult(
        road_candidates=coordinated_roads,
        evidence_links=evidence,
        road_movements=movements,
        endpoint_audit=endpoint_audit,
        summary=summary,
    )


def _member_index(frame: gpd.GeoDataFrame) -> dict[tuple[str | None, str | None], list[dict[str, Any]]]:
    result: dict[tuple[str | None, str | None], list[dict[str, Any]]] = {}
    columns = [
        "lane_id",
        "parent_swsd_unit_id",
        "directional_road_id",
        "travel_side",
        "evidence_quality_state",
    ]
    for row in frame[columns].drop_duplicates().to_dict("records"):
        key = (canonical_id(row["lane_id"]), canonical_id(row["parent_swsd_unit_id"]))
        result.setdefault(key, []).append(row)
    return result


def _endpoint_support(stations: gpd.GeoDataFrame) -> dict[tuple[str, str], bool]:
    result: dict[tuple[str, str], bool] = {}
    ordered = stations.sort_values(["directional_road_id", "travel_station_fraction"])
    for road_id, frame in ordered.groupby("directional_road_id", sort=False):
        result[(str(road_id), "s")] = bool(frame.iloc[0].support_at_station)
        result[(str(road_id), "e")] = bool(frame.iloc[-1].support_at_station)
    return result


def _projection_state(
    *,
    input_state: str,
    mapping_unique: bool,
    semantic_ok: bool,
    quality_usable: bool,
) -> tuple[str, str]:
    if not mapping_unique:
        return "review", "directional_lane_mapping_not_unique"
    if input_state == "cross_owner_shared_node_review":
        return "review", "input_direction_review_preserved"
    if input_state == "cross_owner_semantic_unconnected_review":
        return "review", "input_semantic_unconnected_review_preserved"
    if not quality_usable:
        return "review", "movement_endpoint_evidence_not_usable"
    if not semantic_ok:
        return "review", "directional_semantic_endpoint_conflict"
    return "confirmed", "lane_topo_directional_end_to_start_confirmed"


def _physical_endpoint_targets(
    roads: gpd.GeoDataFrame,
    confirmed: gpd.GeoDataFrame,
    endpoint_support: dict[tuple[str, str], bool],
    parent_by_id: gpd.GeoDataFrame,
    *,
    snap_tolerance_m: float,
) -> tuple[dict[tuple[str, str], Point], dict[tuple[str, str], str]]:
    road_by_id = roads.set_index("directional_road_id", drop=False)
    _ = confirmed
    components: dict[str, list[tuple[str, str]]] = {}
    for row in roads.itertuples(index=False):
        road_id = str(row.directional_road_id)
        components.setdefault(canonical_id(row.snode_id), []).append((road_id, "s"))
        components.setdefault(canonical_id(row.enode_id), []).append((road_id, "e"))

    targets: dict[tuple[str, str], Point] = {}
    sources: dict[tuple[str, str], str] = {}
    for keys in components.values():
        if len(keys) < 2:
            continue
        current_points = [_road_endpoint(road_by_id.loc[road_id].geometry, endpoint) for road_id, endpoint in keys]
        maximum_gap = max(
            (
                first.distance(second)
                for index, first in enumerate(current_points)
                for second in current_points[index + 1 :]
            ),
            default=0.0,
        )
        if maximum_gap <= snap_tolerance_m:
            continue
        unsupported = any(not endpoint_support.get(key, False) for key in keys)
        if unsupported:
            reference_points = [
                _parent_endpoint(road_by_id.loc[road_id], endpoint, parent_by_id)
                for road_id, endpoint in keys
            ]
            target = _median_point(reference_points)
            source = "swsd_physical_node_global_transition"
        else:
            target = _median_point(current_points)
            source = "physical_node_global_shared_portal"
        for key in keys:
            targets[key] = target
            sources[key] = source
    return targets, sources


def _coordinate_road_endpoints(
    roads: gpd.GeoDataFrame,
    targets: dict[tuple[str, str], Point],
    sources: dict[tuple[str, str], str],
    parent_by_id: gpd.GeoDataFrame,
    *,
    transition_length_m: float,
    max_lateral_slope: float,
    run_id: str,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    result = roads.copy()
    audit_rows: list[dict[str, Any]] = []
    geometries: list[LineString] = []
    start_sources: list[str] = []
    end_sources: list[str] = []
    start_shifts: list[float] = []
    end_shifts: list[float] = []
    coordination_states: list[str] = []
    for row in result.itertuples(index=False):
        road_id = str(row.directional_road_id)
        original = row.geometry
        start_target = targets.get((road_id, "s"))
        end_target = targets.get((road_id, "e"))
        start_source = sources.get((road_id, "s"), "road_geometry_retained")
        end_source = sources.get((road_id, "e"), "road_geometry_retained")
        adjusted = _retarget_geometry(
            original,
            start_target=start_target,
            end_target=end_target,
            transition_length_m=transition_length_m,
            max_lateral_slope=max_lateral_slope,
        )
        state = "coordinated" if start_target is not None or end_target is not None else "not_required"
        if not adjusted.is_valid or not adjusted.is_simple:
            adjusted = original
            state = "rejected_invalid_geometry"
            start_source = "endpoint_adjustment_rejected_invalid"
            end_source = "endpoint_adjustment_rejected_invalid"
        geometries.append(adjusted)
        start_shift = _road_endpoint(original, "s").distance(_road_endpoint(adjusted, "s"))
        end_shift = _road_endpoint(original, "e").distance(_road_endpoint(adjusted, "e"))
        start_sources.append(start_source)
        end_sources.append(end_source)
        start_shifts.append(float(start_shift))
        end_shifts.append(float(end_shift))
        coordination_states.append(state)
        for endpoint, source, shift in (
            ("s", start_source, start_shift),
            ("e", end_source, end_shift),
        ):
            point = _road_endpoint(adjusted, endpoint)
            audit_rows.append(
                {
                    "run_id": run_id,
                    "directional_road_id": road_id,
                    "parent_swsd_unit_id": str(row.parent_swsd_unit_id),
                    "endpoint": endpoint,
                    "physical_node_id": canonical_id(
                        row.snode_id if endpoint == "s" else row.enode_id
                    ),
                    "semantic_junction_id": canonical_id(
                        row.semantic_snode_id if endpoint == "s" else row.semantic_enode_id
                    ),
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
    result["endpoint_coordination_state"] = coordination_states
    result["candidate_length_m"] = result.geometry.length
    result["candidate_length_ratio"] = (
        result["candidate_length_m"]
        / result["swsd_reference_length_m"].astype(float).replace(0, np.nan)
    )
    result["geometry_valid"] = result.geometry.is_valid
    result["geometry_simple"] = result.geometry.is_simple
    start_parent_delta: list[float] = []
    end_parent_delta: list[float] = []
    for row in result.itertuples(index=False):
        start_parent_delta.append(
            _road_endpoint(row.geometry, "s").distance(
                _parent_endpoint(row, "s", parent_by_id)
            )
        )
        end_parent_delta.append(
            _road_endpoint(row.geometry, "e").distance(
                _parent_endpoint(row, "e", parent_by_id)
            )
        )
    result["start_parent_swsd_portal_delta_m"] = start_parent_delta
    result["end_parent_swsd_portal_delta_m"] = end_parent_delta
    audit = gpd.GeoDataFrame(audit_rows, geometry="geometry", crs=roads.crs)
    return result, audit


def _build_road_movements(
    confirmed: gpd.GeoDataFrame,
    roads: gpd.GeoDataFrame,
    *,
    evidence_geometry_max_distance_m: float,
    max_join_angle_deg: float,
    curve_sample_spacing_m: float,
    run_id: str,
) -> gpd.GeoDataFrame:
    road_by_id = roads.set_index("directional_road_id", drop=False)
    rows: list[dict[str, Any]] = []
    grouped = confirmed.groupby(
        ["source_directional_road_id", "target_directional_road_id"],
        sort=True,
    )
    for index, ((source_id, target_id), frame) in enumerate(grouped):
        source = road_by_id.loc[str(source_id)]
        target = road_by_id.loc[str(target_id)]
        source_point = _road_endpoint(source.geometry, "e")
        target_point = _road_endpoint(target.geometry, "s")
        evidence_geometry, evidence_distance = _best_evidence_geometry(
            frame,
            source_point,
            target_point,
        )
        relation = (
            "same_physical_node"
            if (frame["junction_relation"] == "same_physical_node").all()
            else "same_semantic_junction"
        )
        if relation == "same_physical_node":
            connector = _tangent_connector(
                source.geometry,
                target.geometry,
                sample_spacing_m=curve_sample_spacing_m,
            )
            geometry_source = "lane_topo_physical_shared_portal"
        elif evidence_geometry is not None and evidence_distance <= evidence_geometry_max_distance_m:
            connector = _evidence_connector(source_point, target_point, evidence_geometry)
            geometry_source = "lane_topo_geometry_portal_aligned"
            if (
                _connector_join_angle(source.geometry, target.geometry, connector)
                > max_join_angle_deg
            ):
                connector = _tangent_connector(
                    source.geometry,
                    target.geometry,
                    sample_spacing_m=curve_sample_spacing_m,
                )
                geometry_source = "lane_topo_geometry_tangent_fallback"
        else:
            connector = _tangent_connector(
                source.geometry,
                target.geometry,
                sample_spacing_m=curve_sample_spacing_m,
            )
            geometry_source = "lane_topo_relation_tangent_connector"
        if not connector.is_valid or not connector.is_simple:
            connector = _tangent_connector(
                source.geometry,
                target.geometry,
                sample_spacing_m=curve_sample_spacing_m,
            )
            geometry_source += ":non_simple_tangent_fallback"
        if not connector.is_valid or not connector.is_simple:
            connector = LineString(
                [
                    (float(source_point.x), float(source_point.y)),
                    (float(target_point.x), float(target_point.y)),
                ]
            )
            geometry_source += ":non_simple_straight_fallback"
        rows.append(
            {
                "run_id": run_id,
                "directional_movement_id": f"M{index + 1:06d}",
                "source_directional_road_id": str(source_id),
                "target_directional_road_id": str(target_id),
                "source_parent_swsd_unit_id": str(source.parent_swsd_unit_id),
                "target_parent_swsd_unit_id": str(target.parent_swsd_unit_id),
                "semantic_junction_id": ";".join(
                    sorted(set(frame["semantic_junction_id"].astype(str)))
                ),
                "junction_relation": relation,
                "lane_topo_link_count": int(len(frame)),
                "lane_topo_link_ids": ";".join(sorted(frame["link_id"].astype(str))),
                "source_lane_ids": ";".join(sorted(set(frame["lane_id"].astype(str)))),
                "target_lane_ids": ";".join(
                    sorted(set(frame["next_lane_id"].astype(str)))
                ),
                "support_state": "lane_topo_supported",
                "geometry_source": geometry_source,
                "evidence_geometry_portal_distance_m": float(evidence_distance),
                "decision": "published_directional_movement",
                "reason_codes": "lane_topo_links_aggregated_to_directional_movement",
                "geometry": connector,
            }
        )
    columns = [
        "run_id",
        "directional_movement_id",
        "source_directional_road_id",
        "target_directional_road_id",
        "source_parent_swsd_unit_id",
        "target_parent_swsd_unit_id",
        "semantic_junction_id",
        "junction_relation",
        "lane_topo_link_count",
        "lane_topo_link_ids",
        "source_lane_ids",
        "target_lane_ids",
        "support_state",
        "geometry_source",
        "evidence_geometry_portal_distance_m",
        "decision",
        "reason_codes",
        "geometry",
    ]
    return gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=roads.crs)


def _best_evidence_geometry(
    frame: gpd.GeoDataFrame,
    source: Point,
    target: Point,
) -> tuple[Any | None, float]:
    candidates: list[tuple[float, Any]] = []
    for geometry in frame.geometry:
        if geometry is None or geometry.is_empty:
            continue
        line = _as_line_string(geometry)
        if line is None:
            continue
        start = Point(line.coords[0])
        end = Point(line.coords[-1])
        distance = float(
            min(
                source.distance(start) + target.distance(end),
                source.distance(end) + target.distance(start),
            )
        )
        candidates.append((distance, geometry))
    if not candidates:
        return None, float("inf")
    return min(candidates, key=lambda item: item[0])[1], min(item[0] for item in candidates)


def _evidence_connector(source: Point, target: Point, evidence: Any) -> LineString:
    line = _as_line_string(evidence)
    if line is None:
        return LineString([(source.x, source.y), (target.x, target.y)])
    start_cost = source.distance(Point(line.coords[0])) + target.distance(Point(line.coords[-1]))
    reverse_cost = source.distance(Point(line.coords[-1])) + target.distance(Point(line.coords[0]))
    if reverse_cost < start_cost:
        line = LineString(list(line.coords)[::-1])
    source_station = float(line.project(source))
    target_station = float(line.project(target))
    if target_station < source_station:
        line = LineString(list(line.coords)[::-1])
        source_station = float(line.project(source))
        target_station = float(line.project(target))
    selected = substring(line, source_station, target_station)
    if selected.geom_type != "LineString" or selected.length <= 1e-8:
        selected = line
    coordinates = [(float(source.x), float(source.y))]
    sample_count = max(3, min(65, int(math.ceil(float(selected.length))) + 1))
    coordinates.extend(
        (float(point.x), float(point.y))
        for point in (
            selected.interpolate(value, normalized=True)
            for value in np.linspace(0.0, 1.0, sample_count)
        )
    )
    coordinates.append((float(target.x), float(target.y)))
    return LineString(_dedupe_coordinates(coordinates))


def _tangent_connector(
    source: LineString,
    target: LineString,
    *,
    sample_spacing_m: float = 1.0,
) -> LineString:
    start = _road_endpoint(source, "e")
    end = _road_endpoint(target, "s")
    gap = float(start.distance(end))
    if gap <= 1e-8:
        source_tail = _point_on_endpoint_segment(source, "e", 0.5)
        target_head = _point_on_endpoint_segment(target, "s", 0.5)
        return LineString(
            _dedupe_coordinates(
                [
                    (float(source_tail.x), float(source_tail.y)),
                    (float(start.x), float(start.y)),
                    (float(target_head.x), float(target_head.y)),
                ]
            )
        )
    source_tangent = _unit_vector(tangent_vector(source, float(source.length)))
    target_tangent = _unit_vector(tangent_vector(target, 0.0))
    control = min(15.0, max(2.0, gap * 0.35))
    p0 = np.asarray([start.x, start.y], dtype=float)
    p1 = p0 + np.asarray(source_tangent) * control
    p3 = np.asarray([end.x, end.y], dtype=float)
    p2 = p3 - np.asarray(target_tangent) * control
    coordinates = []
    sample_count = max(
        9,
        min(129, int(math.ceil(max(gap, control * 2.0) / max(sample_spacing_m, 1e-6))) + 1),
    )
    for value in np.linspace(0.0, 1.0, sample_count):
        point = (
            (1.0 - value) ** 3 * p0
            + 3.0 * (1.0 - value) ** 2 * value * p1
            + 3.0 * (1.0 - value) * value**2 * p2
            + value**3 * p3
        )
        coordinates.append((float(point[0]), float(point[1])))
    return LineString(_dedupe_coordinates(coordinates))


def _as_line_string(geometry: Any) -> LineString | None:
    if geometry is None or geometry.is_empty:
        return None
    if geometry.geom_type == "LineString":
        return geometry
    if hasattr(geometry, "geoms"):
        lines = [part for part in geometry.geoms if part.geom_type == "LineString" and not part.is_empty]
        return max(lines, key=lambda part: part.length) if lines else None
    return None


def _point_on_endpoint_segment(
    geometry: LineString,
    endpoint: str,
    requested_distance_m: float,
) -> Point:
    coordinates = list(geometry.coords)
    first, second = (
        (coordinates[-1], coordinates[-2])
        if endpoint == "e"
        else (coordinates[0], coordinates[1])
    )
    vector = np.asarray(second[:2], dtype=float) - np.asarray(first[:2], dtype=float)
    length = float(np.linalg.norm(vector))
    if length <= 1e-12:
        return Point(first[:2])
    distance = min(max(requested_distance_m, 1e-3), length * 0.5)
    point = np.asarray(first[:2], dtype=float) + vector / length * distance
    return Point(float(point[0]), float(point[1]))


def _connector_join_angle(
    source: LineString,
    target: LineString,
    connector: LineString,
) -> float:
    source_coordinates = list(source.coords)
    target_coordinates = list(target.coords)
    connector_coordinates = list(connector.coords)
    return max(
        _vector_angle(
            _vector(source_coordinates[-2], source_coordinates[-1]),
            _vector(connector_coordinates[0], connector_coordinates[1]),
        ),
        _vector_angle(
            _vector(connector_coordinates[-2], connector_coordinates[-1]),
            _vector(target_coordinates[0], target_coordinates[1]),
        ),
    )


def _vector(first: Any, second: Any) -> tuple[float, float]:
    return float(second[0] - first[0]), float(second[1] - first[1])


def _vector_angle(first: tuple[float, float], second: tuple[float, float]) -> float:
    first_norm = math.hypot(*first)
    second_norm = math.hypot(*second)
    if min(first_norm, second_norm) <= 1e-12:
        return 180.0
    cosine = (first[0] * second[0] + first[1] * second[1]) / (
        first_norm * second_norm
    )
    return math.degrees(math.acos(max(-1.0, min(1.0, cosine))))


def _retarget_geometry(
    geometry: LineString,
    *,
    start_target: Point | None,
    end_target: Point | None,
    transition_length_m: float,
    max_lateral_slope: float,
) -> LineString:
    if start_target is None and end_target is None:
        return geometry
    length = float(geometry.length)
    start = _road_endpoint(geometry, "s")
    end = _road_endpoint(geometry, "e")
    start_delta = np.asarray(
        [0.0, 0.0]
        if start_target is None
        else [start_target.x - start.x, start_target.y - start.y],
        dtype=float,
    )
    end_delta = np.asarray(
        [0.0, 0.0]
        if end_target is None
        else [end_target.x - end.x, end_target.y - end.y],
        dtype=float,
    )
    coordinates: list[tuple[float, float]] = []
    for coordinate in geometry.coords:
        point = Point(coordinate[:2])
        station = float(geometry.project(point))
        value = np.asarray(coordinate[:2], dtype=float)
        if start_target is not None and end_target is not None:
            ratio = min(max(station / max(length, 1e-6), 0.0), 1.0)
            blend = 3.0 * ratio**2 - 2.0 * ratio**3
            value += start_delta * (1.0 - blend) + end_delta * blend
        elif start_target is not None:
            required = 1.5 * float(np.linalg.norm(start_delta)) / max(
                max_lateral_slope,
                1e-6,
            )
            transition = min(
                max(float(transition_length_m), required, 1e-6),
                max(length, 1e-6),
            )
            ratio = min(max(station / transition, 0.0), 1.0)
            weight = 1.0 - (3.0 * ratio**2 - 2.0 * ratio**3)
            value += start_delta * weight
        else:
            required = 1.5 * float(np.linalg.norm(end_delta)) / max(
                max_lateral_slope,
                1e-6,
            )
            transition = min(
                max(float(transition_length_m), required, 1e-6),
                max(length, 1e-6),
            )
            ratio = min(max((length - station) / transition, 0.0), 1.0)
            weight = 1.0 - (3.0 * ratio**2 - 2.0 * ratio**3)
            value += end_delta * weight
        coordinates.append((float(value[0]), float(value[1])))
    if start_target is not None:
        coordinates[0] = (float(start_target.x), float(start_target.y))
    if end_target is not None:
        coordinates[-1] = (float(end_target.x), float(end_target.y))
    return LineString(_dedupe_coordinates(coordinates))


def _parent_endpoint(
    road: Any,
    endpoint: str,
    parent_by_id: gpd.GeoDataFrame,
) -> Point:
    parent = parent_by_id.loc[canonical_id(road.parent_swsd_unit_id)]
    node_id = canonical_id(road.snode_id if endpoint == "s" else road.enode_id)
    if node_id == canonical_id(parent.snode_id):
        return Point(parent.geometry.coords[0])
    if node_id == canonical_id(parent.enode_id):
        return Point(parent.geometry.coords[-1])
    return _road_endpoint(road.geometry, endpoint)


def _road_endpoint(geometry: Any, endpoint: str) -> Point:
    return Point(geometry.coords[0 if endpoint == "s" else -1])


def _median_point(points: list[Point]) -> Point:
    return Point(
        float(np.median([point.x for point in points])),
        float(np.median([point.y for point in points])),
    )


def _unit_vector(value: tuple[float, float]) -> tuple[float, float]:
    norm = math.hypot(*value)
    return (1.0, 0.0) if norm <= 1e-12 else (value[0] / norm, value[1] / norm)


def _dedupe_coordinates(values: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for value in values:
        if not result or Point(result[-1]).distance(Point(value)) > 1e-8:
            result.append(value)
    if len(result) == 1:
        result.append((result[0][0] + 1e-6, result[0][1]))
    return result


def _summary(
    roads: gpd.GeoDataFrame,
    evidence: gpd.GeoDataFrame,
    movements: gpd.GeoDataFrame,
    endpoint_audit: gpd.GeoDataFrame,
    *,
    physical_node_tolerance_m: float,
    movement_join_angle_deg: float,
) -> dict[str, Any]:
    confirmed = evidence[evidence["projection_state"] == "confirmed"]
    review = evidence[evidence["projection_state"] == "review"]
    physical = movements[movements["junction_relation"] == "same_physical_node"]
    road_by_id = roads.set_index("directional_road_id", drop=False)
    physical_gaps = [
        _road_endpoint(road_by_id.loc[row.source_directional_road_id].geometry, "e").distance(
            _road_endpoint(road_by_id.loc[row.target_directional_road_id].geometry, "s")
        )
        for row in physical.itertuples(index=False)
    ]
    movement_portal_deltas: list[float] = []
    movement_join_angles: list[float] = []
    unknown_road_references = 0
    for row in movements.itertuples(index=False):
        if (
            row.source_directional_road_id not in road_by_id.index
            or row.target_directional_road_id not in road_by_id.index
        ):
            unknown_road_references += 1
            continue
        source_point = _road_endpoint(
            road_by_id.loc[row.source_directional_road_id].geometry,
            "e",
        )
        target_point = _road_endpoint(
            road_by_id.loc[row.target_directional_road_id].geometry,
            "s",
        )
        movement_portal_deltas.extend(
            [source_point.distance(row.geometry), target_point.distance(row.geometry)]
        )
        movement_join_angles.append(
            _connector_join_angle(
                road_by_id.loc[row.source_directional_road_id].geometry,
                road_by_id.loc[row.target_directional_road_id].geometry,
                row.geometry,
            )
        )
    all_physical_node_max_gap = _all_physical_node_max_gap(roads)
    rejected = endpoint_audit[
        endpoint_audit["coordination_state"] == "rejected_invalid_geometry"
    ]
    gates = {
        "cross_owner_link_mapping_complete": bool(
            evidence["source_directional_road_id"].astype(bool).all()
            and evidence["target_directional_road_id"].astype(bool).all()
        ),
        "confirmed_link_conservation": int(movements["lane_topo_link_count"].sum())
        == int(len(confirmed)),
        "review_links_preserved": int(len(confirmed) + len(review)) == int(len(evidence)),
        "movement_road_references_valid": unknown_road_references == 0,
        "physical_node_movements_closed": max(physical_gaps, default=0.0) <= 1e-8,
        "all_physical_nodes_closed": all_physical_node_max_gap
        <= physical_node_tolerance_m,
        "movement_geometry_portal_closed": max(movement_portal_deltas, default=0.0)
        <= 1e-8,
        "movement_geometry_valid": bool(
            movements.empty or movements.geometry.is_valid.all()
        ),
        "movement_geometry_simple": bool(
            movements.empty or movements.geometry.is_simple.all()
        ),
        "movement_join_tangent": max(movement_join_angles, default=0.0)
        <= movement_join_angle_deg,
        "final_road_geometry_valid": bool(roads.geometry.is_valid.all()),
        "final_road_geometry_simple": bool(roads.geometry.is_simple.all()),
        "endpoint_adjustment_no_invalid_rejection": rejected.empty,
    }
    return {
        "input_cross_owner_link_count": int(len(evidence)),
        "projection_state_counts": dict(
            sorted(Counter(evidence["projection_state"]).items())
        ),
        "projection_reason_counts": dict(sorted(Counter(evidence["reason_codes"]).items())),
        "confirmed_lane_topo_link_count": int(len(confirmed)),
        "review_lane_topo_link_count": int(len(review)),
        "road_movement_count": int(len(movements)),
        "physical_node_movement_count": int(len(physical)),
        "semantic_junction_movement_count": int(len(movements) - len(physical)),
        "movement_geometry_source_counts": dict(
            sorted(Counter(movements.get("geometry_source", [])).items())
        ),
        "coordinated_endpoint_count": int(
            (endpoint_audit["coordinate_source"] != "road_geometry_retained").sum()
        ),
        "max_endpoint_coordination_shift_m": float(
            endpoint_audit["endpoint_shift_m"].max()
            if not endpoint_audit.empty
            else 0.0
        ),
        "confirmed_physical_movement_max_gap_m": float(
            max(physical_gaps, default=0.0)
        ),
        "all_physical_node_max_gap_m": float(all_physical_node_max_gap),
        "movement_portal_max_delta_m": float(
            max(movement_portal_deltas, default=0.0)
        ),
        "movement_join_angle_max_deg": float(
            max(movement_join_angles, default=0.0)
        ),
        "unknown_road_reference_count": int(unknown_road_references),
        "endpoint_adjustment_rejected_count": int(len(rejected)),
        "gates": gates,
        "movement_gate_pass": all(gates.values()),
    }


def _all_physical_node_max_gap(roads: gpd.GeoDataFrame) -> float:
    endpoints: dict[str, list[Point]] = {}
    for row in roads.itertuples(index=False):
        endpoints.setdefault(canonical_id(row.snode_id), []).append(
            _road_endpoint(row.geometry, "s")
        )
        endpoints.setdefault(canonical_id(row.enode_id), []).append(
            _road_endpoint(row.geometry, "e")
        )
    return max(
        (
            first.distance(second)
            for points in endpoints.values()
            for index, first in enumerate(points)
            for second in points[index + 1 :]
        ),
        default=0.0,
    )


__all__ = ["DirectionalMovementResult", "build_directional_movements"]
