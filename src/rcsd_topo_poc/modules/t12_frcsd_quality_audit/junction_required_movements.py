from __future__ import annotations

from collections import defaultdict
import math
from typing import Any, Iterable, Mapping

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import unary_union

from .carrier_graph import (
    build_graph,
    build_raw_node_context,
    field_name,
    normalize_id,
    shortest_path_between_sets,
)


VALID_DIRECTIONS = frozenset({0, 1, 2, 3})


def audit_required_junction_movements(
    *,
    swsd_roads: gpd.GeoDataFrame,
    swsd_nodes: gpd.GeoDataFrame,
    frcsd_roads: gpd.GeoDataFrame,
    frcsd_nodes: gpd.GeoDataFrame,
    drivezone: gpd.GeoDataFrame | None,
    selected_road_ids: Iterable[str],
    target_node_ids: Iterable[str],
    representative_geometry: Point,
    local_radius_m: float,
    endpoint_tolerance_m: float,
    target_anchor_tolerance_m: float,
    boundary_match_tolerance_m: float,
    boundary_heading_tolerance_deg: float,
) -> dict[str, Any]:
    """Reverify SWSD-required Junction movements on raw directed FRCSD Roads."""
    selected_ids = {
        normalize_id(value) for value in selected_road_ids if normalize_id(value)
    }
    target_ids = {
        normalize_id(value) for value in target_node_ids if normalize_id(value)
    }
    selected = _select_roads(swsd_roads, selected_ids)
    target_points = _select_node_points(swsd_nodes, target_ids)
    target_geometry = unary_union(list(target_points.values()))
    local_frcsd = _valid_local_roads(
        frcsd_roads,
        representative_geometry=representative_geometry,
        radius_m=local_radius_m,
    )
    invalid_local_geometry_count = _local_invalid_geometry_count(
        frcsd_roads,
        representative_geometry=representative_geometry,
        radius_m=local_radius_m,
    )
    frcsd_point_lookup = _node_points(frcsd_nodes)
    canonical_lookup = _canonical_lookup(frcsd_nodes)
    swsd_point_lookup = _node_points(swsd_nodes)
    boundaries = _boundary_arms(
        selected,
        target_ids,
        swsd_point_lookup=swsd_point_lookup,
    )
    swsd_invalid_direction_ids = sorted(
        {
            row["road_id"]
            for row in boundaries
            if row["direction"] not in VALID_DIRECTIONS
        },
        key=_id_key,
    )
    required_movements = _required_movements(
        selected=selected,
        swsd_nodes=swsd_nodes,
        boundaries=boundaries,
    )
    arm_audits, candidate_rows_by_arm = _map_boundary_arms(
        boundaries=boundaries,
        local_frcsd=local_frcsd,
        frcsd_point_lookup=frcsd_point_lookup,
        target_geometry=target_geometry,
        target_anchor_tolerance_m=target_anchor_tolerance_m,
        boundary_match_tolerance_m=boundary_match_tolerance_m,
        boundary_heading_tolerance_deg=boundary_heading_tolerance_deg,
    )
    frcsd_raw_context, _, _ = build_raw_node_context(frcsd_nodes)
    frcsd_graph = build_graph(local_frcsd, frcsd_raw_context)
    drivezone_geometry = _drivezone_geometry(drivezone)
    movement_rows = [
        _evaluate_movement(
            movement=movement,
            candidate_rows_by_arm=candidate_rows_by_arm,
            graph=frcsd_graph,
            point_lookup=frcsd_point_lookup,
            canonical_lookup=canonical_lookup,
            target_geometry=target_geometry,
            drivezone_geometry=drivezone_geometry,
            endpoint_tolerance_m=endpoint_tolerance_m,
            target_anchor_tolerance_m=target_anchor_tolerance_m,
        )
        for movement in required_movements
    ]
    incomplete = [
        row
        for row in movement_rows
        if row["status"] == "insufficient_boundary_mapping"
    ]
    missing = [
        row for row in movement_rows if row["status"] == "missing"
    ]
    direction_invalid_ids = sorted(
        {
            *swsd_invalid_direction_ids,
            *(
                candidate["road_id"]
                for rows in candidate_rows_by_arm.values()
                for candidate in rows
                if candidate["direction"] not in VALID_DIRECTIONS
            ),
        },
        key=_id_key,
    )
    blockers: list[str] = []
    if not required_movements:
        blockers.append("no_swsd_required_junction_movements")
    if not target_points:
        blockers.append("target_group_geometry_missing")
    if invalid_local_geometry_count:
        blockers.append("invalid_local_frcsd_geometry")
    if direction_invalid_ids:
        blockers.append("invalid_required_movement_direction")
    # An unanchored movement remains unresolved, but it must not erase a
    # different movement whose two boundary carriers are locally anchored and
    # whose directed deficit is independently reproducible.
    if incomplete and not missing:
        blockers.append("boundary_carrier_not_locally_anchored")
    if blockers:
        status = "insufficient"
    elif missing:
        status = "confirmed_missing"
    else:
        status = "equivalent"
    return {
        "mode": "raw_directed_required_junction_movement_audit",
        "status": status,
        "selected_swsdroad_ids": sorted(selected_ids, key=_id_key),
        "target_node_ids": sorted(target_ids, key=_id_key),
        "local_radius_m": local_radius_m,
        "endpoint_tolerance_m": endpoint_tolerance_m,
        "target_anchor_tolerance_m": target_anchor_tolerance_m,
        "boundary_match_tolerance_m": boundary_match_tolerance_m,
        "boundary_heading_tolerance_deg": boundary_heading_tolerance_deg,
        "heading_sample_distance_m": 10.0,
        "distance_role": (
            "local_retrieval_and_high_confidence_ownership_eligibility;"
            "not_an_equivalence_rejection_after_anchor"
        ),
        "boundary_arm_count": len(boundaries),
        "boundary_arms": [_public_arm(row) for row in boundaries],
        "boundary_arm_audits": arm_audits,
        "required_movement_count": len(required_movements),
        "required_movements": movement_rows,
        "missing_movement_count": len(missing),
        "missing_movement_ids": [row["movement_id"] for row in missing],
        "incomplete_movement_count": len(incomplete),
        "blockers": blockers,
        "invalid_direction_road_ids": direction_invalid_ids,
        "local_frcsd_road_count": len(local_frcsd),
        "invalid_local_frcsd_geometry_count": invalid_local_geometry_count,
        "source_geometry_modified": False,
        "silent_fix": False,
    }


def _select_roads(
    roads: gpd.GeoDataFrame,
    road_ids: set[str],
) -> gpd.GeoDataFrame:
    road_id_field = field_name(roads, "id")
    return roads.loc[roads[road_id_field].map(normalize_id).isin(road_ids)].copy()


def _select_node_points(
    nodes: gpd.GeoDataFrame,
    node_ids: set[str],
) -> dict[str, Point]:
    node_id_field = field_name(nodes, "id")
    return {
        normalize_id(row[node_id_field]): Point(row.geometry)
        for _, row in nodes.iterrows()
        if normalize_id(row[node_id_field]) in node_ids
        and row.geometry is not None
        and not row.geometry.is_empty
    }


def _node_points(nodes: gpd.GeoDataFrame) -> dict[str, Point]:
    node_id_field = field_name(nodes, "id")
    return {
        normalize_id(row[node_id_field]): Point(row.geometry)
        for _, row in nodes.iterrows()
        if normalize_id(row[node_id_field])
        and row.geometry is not None
        and not row.geometry.is_empty
    }


def _canonical_lookup(nodes: gpd.GeoDataFrame) -> dict[str, str]:
    node_id_field = field_name(nodes, "id")
    main_field = _optional_field(nodes, "mainnodeid")
    output: dict[str, str] = {}
    for _, row in nodes.iterrows():
        node_id = normalize_id(row[node_id_field])
        if not node_id:
            continue
        main_id = normalize_id(row[main_field]) if main_field else ""
        output[node_id] = main_id if main_id not in {"", "0"} else node_id
    return output


def _valid_local_roads(
    roads: gpd.GeoDataFrame,
    *,
    representative_geometry: Point,
    radius_m: float,
) -> gpd.GeoDataFrame:
    window = representative_geometry.buffer(radius_m)
    mask = roads.geometry.map(
        lambda geometry: bool(
            geometry is not None
            and not geometry.is_empty
            and geometry.is_valid
            and geometry.intersects(window)
        )
    )
    return roads.loc[mask].copy()


def _local_invalid_geometry_count(
    roads: gpd.GeoDataFrame,
    *,
    representative_geometry: Point,
    radius_m: float,
) -> int:
    window = representative_geometry.buffer(radius_m)
    minx, miny, maxx, maxy = window.bounds
    count = 0
    for geometry in roads.geometry:
        if geometry is None or geometry.is_empty or geometry.is_valid:
            continue
        gx1, gy1, gx2, gy2 = geometry.bounds
        if gx2 >= minx and gx1 <= maxx and gy2 >= miny and gy1 <= maxy:
            count += 1
    return count


def _boundary_arms(
    selected: gpd.GeoDataFrame,
    target_ids: set[str],
    *,
    swsd_point_lookup: Mapping[str, Point],
) -> list[dict[str, Any]]:
    if selected.empty:
        return []
    road_id_field = field_name(selected, "id")
    start_field = field_name(selected, "snodeid")
    end_field = field_name(selected, "enodeid")
    direction_field = field_name(selected, "direction")
    output: list[dict[str, Any]] = []
    for _, row in selected.iterrows():
        road_id = normalize_id(row[road_id_field])
        start_id = normalize_id(row[start_field])
        end_id = normalize_id(row[end_field])
        inside = [node_id for node_id in (start_id, end_id) if node_id in target_ids]
        if len(inside) != 1:
            continue
        inside_id = inside[0]
        outside_id = end_id if inside_id == start_id else start_id
        direction = _direction(row[direction_field])
        incoming, outgoing = _node_roles(
            direction=direction,
            node_id=inside_id,
            start_id=start_id,
            end_id=end_id,
        )
        output.append(
            {
                "road_id": road_id,
                "inside_node_id": inside_id,
                "outside_node_id": outside_id,
                "direction": direction,
                "incoming": incoming,
                "outgoing": outgoing,
                "outward_heading_deg": _outward_heading_deg(
                    row.geometry,
                    swsd_point_lookup.get(inside_id),
                ),
                "geometry": row.geometry,
            }
        )
    return sorted(output, key=lambda row: _id_key(row["road_id"]))


def _required_movements(
    *,
    selected: gpd.GeoDataFrame,
    swsd_nodes: gpd.GeoDataFrame,
    boundaries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if selected.empty:
        return []
    raw_context, _, _ = build_raw_node_context(swsd_nodes)
    graph = build_graph(selected, raw_context)
    movements: list[dict[str, Any]] = []
    for incoming in boundaries:
        if not incoming["incoming"]:
            continue
        for outgoing in boundaries:
            if (
                not outgoing["outgoing"]
                or incoming["road_id"] == outgoing["road_id"]
            ):
                continue
            path = shortest_path_between_sets(
                graph.directed,
                [incoming["outside_node_id"]],
                [outgoing["outside_node_id"]],
            )
            if path is None:
                continue
            movements.append(
                {
                    "movement_id": (
                        f"{incoming['road_id']}->{outgoing['road_id']}"
                    ),
                    "incoming_arm_road_id": incoming["road_id"],
                    "outgoing_arm_road_id": outgoing["road_id"],
                    "swsd_path_road_ids": list(path.road_ids),
                }
            )
    return movements


def _map_boundary_arms(
    *,
    boundaries: list[dict[str, Any]],
    local_frcsd: gpd.GeoDataFrame,
    frcsd_point_lookup: Mapping[str, Point],
    target_geometry: Any,
    target_anchor_tolerance_m: float,
    boundary_match_tolerance_m: float,
    boundary_heading_tolerance_deg: float,
) -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    if local_frcsd.empty or target_geometry is None or target_geometry.is_empty:
        return (
            {
                row["road_id"]: {
                    "physical_candidate_count": 0,
                    "incoming_candidate_count": 0,
                    "outgoing_candidate_count": 0,
                    "candidates": [],
                }
                for row in boundaries
            },
            {row["road_id"]: [] for row in boundaries},
        )
    road_id_field = field_name(local_frcsd, "id")
    start_field = field_name(local_frcsd, "snodeid")
    end_field = field_name(local_frcsd, "enodeid")
    direction_field = field_name(local_frcsd, "direction")
    audits: dict[str, dict[str, Any]] = {}
    by_arm: dict[str, list[dict[str, Any]]] = {}
    for arm in boundaries:
        rows: list[dict[str, Any]] = []
        for _, road in local_frcsd.iterrows():
            start_id = normalize_id(road[start_field])
            end_id = normalize_id(road[end_field])
            if start_id not in frcsd_point_lookup or end_id not in frcsd_point_lookup:
                continue
            inner_id = min(
                (start_id, end_id),
                key=lambda node_id: (
                    float(frcsd_point_lookup[node_id].distance(target_geometry)),
                    _id_key(node_id),
                ),
            )
            geometry_gap_m = float(arm["geometry"].distance(road.geometry))
            target_anchor_gap_m = float(
                frcsd_point_lookup[inner_id].distance(target_geometry)
            )
            direction = _direction(road[direction_field])
            candidate_heading_deg = _outward_heading_deg(
                road.geometry,
                frcsd_point_lookup[inner_id],
            )
            heading_delta_deg = _heading_delta_deg(
                arm.get("outward_heading_deg"),
                candidate_heading_deg,
            )
            incoming, outgoing = _node_roles(
                direction=direction,
                node_id=inner_id,
                start_id=start_id,
                end_id=end_id,
            )
            rows.append(
                {
                    "road_id": normalize_id(road[road_id_field]),
                    "inner_node_id": inner_id,
                    "outer_node_id": (
                        end_id if inner_id == start_id else start_id
                    ),
                    "direction": direction,
                    "incoming": incoming,
                    "outgoing": outgoing,
                    "geometry_gap_m": round(geometry_gap_m, 6),
                    "target_anchor_gap_m": round(target_anchor_gap_m, 6),
                    "swsd_outward_heading_deg": arm.get(
                        "outward_heading_deg"
                    ),
                    "frcsd_outward_heading_deg": candidate_heading_deg,
                    "heading_delta_deg": heading_delta_deg,
                    "physical_match": bool(
                        geometry_gap_m <= boundary_match_tolerance_m
                        and target_anchor_gap_m <= target_anchor_tolerance_m
                        and heading_delta_deg is not None
                        and heading_delta_deg
                        <= boundary_heading_tolerance_deg
                    ),
                }
            )
        rows.sort(
            key=lambda row: (
                row["geometry_gap_m"],
                row["target_anchor_gap_m"],
                row["heading_delta_deg"]
                if row["heading_delta_deg"] is not None
                else float("inf"),
                _id_key(row["road_id"]),
            )
        )
        physical = [row for row in rows if row["physical_match"]]
        by_arm[arm["road_id"]] = physical
        audits[arm["road_id"]] = {
            "physical_candidate_count": len(physical),
            "incoming_candidate_count": sum(
                1 for row in physical if row["incoming"]
            ),
            "outgoing_candidate_count": sum(
                1 for row in physical if row["outgoing"]
            ),
            "candidates": (physical or rows[:3]),
        }
    return audits, by_arm


def _evaluate_movement(
    *,
    movement: dict[str, Any],
    candidate_rows_by_arm: Mapping[str, list[dict[str, Any]]],
    graph: Any,
    point_lookup: Mapping[str, Point],
    canonical_lookup: Mapping[str, str],
    target_geometry: Any,
    drivezone_geometry: Any,
    endpoint_tolerance_m: float,
    target_anchor_tolerance_m: float,
) -> dict[str, Any]:
    incoming_physical = candidate_rows_by_arm.get(
        movement["incoming_arm_road_id"], []
    )
    outgoing_physical = candidate_rows_by_arm.get(
        movement["outgoing_arm_road_id"], []
    )
    incoming = [row for row in incoming_physical if row["incoming"]]
    outgoing = [row for row in outgoing_physical if row["outgoing"]]
    output = dict(movement)
    output.update(
        {
            "incoming_physical_candidate_road_ids": [
                row["road_id"] for row in incoming_physical
            ],
            "outgoing_physical_candidate_road_ids": [
                row["road_id"] for row in outgoing_physical
            ],
            "incoming_role_candidate_road_ids": [
                row["road_id"] for row in incoming
            ],
            "outgoing_role_candidate_road_ids": [
                row["road_id"] for row in outgoing
            ],
            "frcsd_path_road_ids": [],
            "equivalence_basis": "",
            "missing_reason": "",
            "canonical_alias_portal": {},
        }
    )
    if not incoming_physical or not outgoing_physical:
        output["status"] = "insufficient_boundary_mapping"
        output["missing_reason"] = "boundary_carrier_not_locally_anchored"
        return output
    if not incoming or not outgoing:
        output["status"] = "missing"
        output["missing_reason"] = "boundary_direction_role_missing"
        return output
    path = shortest_path_between_sets(
        graph.directed,
        {row["inner_node_id"] for row in incoming},
        {row["inner_node_id"] for row in outgoing},
    )
    if path is not None:
        output["status"] = "equivalent"
        output["equivalence_basis"] = "raw_local_directed_carrier"
        output["frcsd_path_road_ids"] = list(path.road_ids)
        output["start_portal_node_id"] = path.start
        output["end_portal_node_id"] = path.end
        return output
    portal = _canonical_alias_portal(
        incoming=incoming,
        outgoing=outgoing,
        point_lookup=point_lookup,
        canonical_lookup=canonical_lookup,
        target_geometry=target_geometry,
        drivezone_geometry=drivezone_geometry,
        endpoint_tolerance_m=endpoint_tolerance_m,
        target_anchor_tolerance_m=target_anchor_tolerance_m,
    )
    output["canonical_alias_portal"] = portal
    if portal.get("accepted"):
        output["status"] = "equivalent"
        output["equivalence_basis"] = "canonical_raw_alias_portal"
        output["start_portal_node_id"] = portal["incoming_node_id"]
        output["end_portal_node_id"] = portal["outgoing_node_id"]
        return output
    output["status"] = "missing"
    output["missing_reason"] = "internal_directed_carrier_missing"
    return output


def _canonical_alias_portal(
    *,
    incoming: list[dict[str, Any]],
    outgoing: list[dict[str, Any]],
    point_lookup: Mapping[str, Point],
    canonical_lookup: Mapping[str, str],
    target_geometry: Any,
    drivezone_geometry: Any,
    endpoint_tolerance_m: float,
    target_anchor_tolerance_m: float,
) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for left in incoming:
        left_id = left["inner_node_id"]
        for right in outgoing:
            right_id = right["inner_node_id"]
            if (
                left_id == right_id
                or left_id not in point_lookup
                or right_id not in point_lookup
                or canonical_lookup.get(left_id) != canonical_lookup.get(right_id)
            ):
                continue
            left_point = point_lookup[left_id]
            right_point = point_lookup[right_id]
            gap_m = float(left_point.distance(right_point))
            target_gap_m = min(
                float(left_point.distance(target_geometry)),
                float(right_point.distance(target_geometry)),
            )
            connector = LineString(
                [left_point.coords[0], right_point.coords[0]]
            )
            drivezone_ratio = 0.0
            if (
                drivezone_geometry is not None
                and not drivezone_geometry.is_empty
                and connector.length > 0
            ):
                drivezone_ratio = float(
                    connector.intersection(drivezone_geometry).length
                    / connector.length
                )
            accepted = bool(
                gap_m <= endpoint_tolerance_m
                and target_gap_m <= target_anchor_tolerance_m
                and drivezone_ratio >= 0.999999
            )
            candidates.append(
                {
                    "incoming_node_id": left_id,
                    "outgoing_node_id": right_id,
                    "canonical_group_id": canonical_lookup.get(left_id, ""),
                    "gap_m": round(gap_m, 6),
                    "target_anchor_gap_m": round(target_gap_m, 6),
                    "drivezone_coverage_ratio": round(drivezone_ratio, 6),
                    "accepted": accepted,
                }
            )
    candidates.sort(
        key=lambda row: (
            not row["accepted"],
            row["gap_m"],
            _id_key(row["incoming_node_id"]),
            _id_key(row["outgoing_node_id"]),
        )
    )
    return candidates[0] if candidates else {"accepted": False}


def _drivezone_geometry(drivezone: gpd.GeoDataFrame | None) -> Any:
    if drivezone is None or drivezone.empty:
        return None
    valid = [
        geometry
        for geometry in drivezone.geometry
        if geometry is not None and not geometry.is_empty and geometry.is_valid
    ]
    return unary_union(valid) if valid else None


def _outward_heading_deg(
    geometry: Any,
    inner_point: Point | None,
    *,
    sample_distance_m: float = 10.0,
) -> float | None:
    if geometry is None or geometry.is_empty or inner_point is None:
        return None
    if geometry.geom_type == "LineString":
        lines = [geometry]
    elif geometry.geom_type == "MultiLineString":
        lines = list(geometry.geoms)
    else:
        return None
    valid_lines = [line for line in lines if line.length > 0]
    if not valid_lines:
        return None
    line = min(valid_lines, key=lambda item: float(item.distance(inner_point)))
    coordinates = list(line.coords)
    if len(coordinates) < 2:
        return None
    start = Point(coordinates[0])
    end = Point(coordinates[-1])
    from_start = start.distance(inner_point) <= end.distance(inner_point)
    if from_start:
        anchor = start
        sample = line.interpolate(min(sample_distance_m, float(line.length)))
    else:
        anchor = end
        sample = line.interpolate(
            max(float(line.length) - sample_distance_m, 0.0)
        )
    dx = float(sample.x - anchor.x)
    dy = float(sample.y - anchor.y)
    if math.isclose(dx, 0.0, abs_tol=1e-9) and math.isclose(
        dy, 0.0, abs_tol=1e-9
    ):
        return None
    return round(math.degrees(math.atan2(dy, dx)) % 360.0, 6)


def _heading_delta_deg(
    left: float | None,
    right: float | None,
) -> float | None:
    if left is None or right is None:
        return None
    delta = abs(float(left) - float(right)) % 360.0
    return round(min(delta, 360.0 - delta), 6)


def _node_roles(
    *,
    direction: int,
    node_id: str,
    start_id: str,
    end_id: str,
) -> tuple[bool, bool]:
    incoming = bool(
        direction in {0, 1}
        or (direction == 2 and node_id == end_id)
        or (direction == 3 and node_id == start_id)
    )
    outgoing = bool(
        direction in {0, 1}
        or (direction == 2 and node_id == start_id)
        or (direction == 3 and node_id == end_id)
    )
    return incoming, outgoing


def _direction(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return -1


def _optional_field(frame: pd.DataFrame, name: str) -> str:
    by_lower = {str(column).lower(): str(column) for column in frame.columns}
    return by_lower.get(name.lower(), "")


def _public_arm(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key != "geometry"
    }


def _id_key(value: str) -> tuple[int, int | str]:
    return (0, int(value)) if str(value).isdigit() else (1, str(value))
