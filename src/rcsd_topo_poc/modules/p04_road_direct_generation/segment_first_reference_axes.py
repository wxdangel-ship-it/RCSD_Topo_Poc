from __future__ import annotations

from dataclasses import dataclass
import heapq
from typing import Iterable

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

from .segment_first_skeleton import canonical_id, parse_id_list


@dataclass(frozen=True)
class SegmentReferenceAxisResult:
    axes: gpd.GeoDataFrame
    audit: gpd.GeoDataFrame
    summary: dict[str, object]


def build_segment_reference_axes(
    segment_units: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    swsd_nodes: gpd.GeoDataFrame,
    *,
    run_id: str,
    junction_units: gpd.GeoDataFrame | None = None,
) -> SegmentReferenceAxisResult:
    required = segment_units[
        segment_units["target_required"].fillna(False).astype(bool)
    ].copy()
    roads = swsd_roads.copy()
    roads["canonical_road_id"] = roads["id"].map(canonical_id)
    road_by_id = roads.drop_duplicates("canonical_road_id").set_index(
        "canonical_road_id"
    )
    nodes = swsd_nodes.copy()
    nodes["canonical_node_id"] = nodes["id"].map(canonical_id)
    node_by_id = nodes.drop_duplicates("canonical_node_id").set_index(
        "canonical_node_id"
    )
    semantic_node_by_id = _ordinary_semantic_node_map(
        nodes,
        junction_units,
    )
    axis_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    for segment in required.itertuples(index=False):
        segment_id = canonical_id(segment.segment_id)
        endpoint_ids = parse_id_list(segment.pair_node_ids)
        member_ids = parse_id_list(segment.swsd_road_ids)
        path = _endpoint_road_path(
            endpoint_ids,
            member_ids,
            road_by_id,
        )
        mainnode_handoff = False
        if path is None and semantic_node_by_id:
            path = _endpoint_road_path(
                endpoint_ids,
                member_ids,
                road_by_id,
                semantic_node_by_id=semantic_node_by_id,
            )
            mainnode_handoff = path is not None
        if path is None:
            audit_rows.append(
                _audit_row(
                    segment,
                    run_id=run_id,
                    state="unresolved",
                    reason_code=(
                        "segment_endpoint_count_not_two"
                        if len(endpoint_ids) != 2
                        else "swsd_member_graph_endpoint_path_missing"
                    ),
                    path=(),
                    maximum_join_gap_m=None,
                    geometry=segment.geometry,
                )
            )
            continue
        geometry, maximum_join_gap_m = _path_geometry(
            path,
            road_by_id,
            node_by_id,
        )
        if geometry is None:
            audit_rows.append(
                _audit_row(
                    segment,
                    run_id=run_id,
                    state="unresolved",
                    reason_code="swsd_member_path_geometry_invalid",
                    path=path,
                    maximum_join_gap_m=maximum_join_gap_m,
                    geometry=segment.geometry,
                )
            )
            continue
        row = _audit_row(
            segment,
            run_id=run_id,
            state="resolved",
            reason_code=(
                "swsd_endpoint_mainnode_topology_chain_compiled"
                if mainnode_handoff
                else "swsd_endpoint_topology_chain_compiled"
            ),
            path=path,
            maximum_join_gap_m=maximum_join_gap_m,
            geometry=geometry,
        )
        axis_rows.append(row)
        audit_rows.append(row)
    axes = _frame(axis_rows, segment_units.crs)
    audit = _frame(audit_rows, segment_units.crs)
    resolved_count = len(axes)
    semantic_count = int(
        axes["reference_source"]
        .eq("swsd_endpoint_mainnode_topology_chain")
        .sum()
    ) if not axes.empty else 0
    return SegmentReferenceAxisResult(
        axes=axes,
        audit=audit,
        summary={
            "required_segment_count": int(len(required)),
            "resolved_axis_count": int(resolved_count),
            "exact_carrier_guidance_axis_count": int(
                resolved_count - semantic_count
            ),
            "semantic_audit_axis_count": semantic_count,
            "unresolved_axis_count": int(len(required) - resolved_count),
        },
    )


def _endpoint_road_path(
    endpoint_ids: tuple[str, ...],
    member_ids: tuple[str, ...],
    road_by_id: gpd.GeoDataFrame,
    *,
    semantic_node_by_id: dict[str, str] | None = None,
) -> tuple[tuple[str, str, str], ...] | None:
    if len(endpoint_ids) != 2:
        return None
    semantic_node_by_id = semantic_node_by_id or {}
    adjacency: dict[str, list[tuple[str, str, float]]] = {}
    for road_id in member_ids:
        if road_id not in road_by_id.index:
            continue
        road = road_by_id.loc[road_id]
        physical_start = canonical_id(road.get("snodeid"))
        physical_end = canonical_id(road.get("enodeid"))
        start = semantic_node_by_id.get(physical_start, physical_start)
        end = semantic_node_by_id.get(physical_end, physical_end)
        geometry = _line_geometry(road.geometry)
        if not start or not end or geometry is None:
            continue
        length = max(float(geometry.length), 1e-9)
        adjacency.setdefault(start, []).append((end, road_id, length))
        adjacency.setdefault(end, []).append((start, road_id, length))
    start_node, end_node = (
        semantic_node_by_id.get(node_id, node_id)
        for node_id in endpoint_ids
    )
    frontier: list[
        tuple[float, tuple[str, ...], str, tuple[str, ...]]
    ] = [(0.0, (), start_node, (start_node,))]
    best: dict[str, tuple[float, tuple[str, ...]]] = {}
    while frontier:
        distance, road_path, node_id, node_path = heapq.heappop(frontier)
        current = best.get(node_id)
        score = (distance, road_path)
        if current is not None and current <= score:
            continue
        best[node_id] = score
        if node_id == end_node:
            return tuple(
                (road_id, node_path[index], node_path[index + 1])
                for index, road_id in enumerate(road_path)
            )
        for next_node, road_id, length in sorted(
            adjacency.get(node_id, ()),
            key=lambda item: (item[1], item[0]),
        ):
            if next_node in node_path or road_id in road_path:
                continue
            heapq.heappush(
                frontier,
                (
                    distance + length,
                    (*road_path, road_id),
                    next_node,
                    (*node_path, next_node),
                ),
            )
    return None


def _ordinary_semantic_node_map(
    nodes: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame | None,
) -> dict[str, str]:
    if junction_units is None or junction_units.empty:
        return {}
    ordinary_groups = {
        canonical_id(row.junction_group_id)
        for row in junction_units.itertuples()
        if str(getattr(row, "topology_mode", "")) == "ordinary_semantic"
        and str(getattr(row, "junction_kind", "")) != "complex"
    }
    result: dict[str, str] = {}
    for row in nodes.itertuples():
        node_id = canonical_id(row.id)
        mainnode_id = canonical_id(getattr(row, "mainnodeid", ""))
        if node_id and mainnode_id in ordinary_groups:
            result[node_id] = mainnode_id
    return result


def _path_geometry(
    path: tuple[tuple[str, str, str], ...],
    road_by_id: gpd.GeoDataFrame,
    node_by_id: gpd.GeoDataFrame,
) -> tuple[LineString | None, float | None]:
    if not path:
        return None, None
    coordinates: list[tuple[float, ...]] = []
    maximum_join_gap_m = 0.0
    for index, (road_id, start_node, end_node) in enumerate(path):
        road = road_by_id.loc[road_id]
        geometry = _line_geometry(road.geometry)
        if geometry is None:
            return None, None
        oriented = _orient_geometry(
            geometry,
            start_node,
            end_node,
            node_by_id,
            previous=Point(coordinates[-1]) if coordinates else None,
        )
        part = list(oriented.coords)
        if not coordinates:
            coordinates.extend(part)
            continue
        join_gap = float(Point(coordinates[-1]).distance(Point(part[0])))
        maximum_join_gap_m = max(maximum_join_gap_m, join_gap)
        if join_gap > 1e-9:
            coordinates.append(part[0])
        coordinates.extend(part[1:])
    geometry = LineString(coordinates)
    if geometry.is_empty or not geometry.is_valid or geometry.length <= 1e-9:
        return None, maximum_join_gap_m
    return geometry, maximum_join_gap_m


def _orient_geometry(
    geometry: LineString,
    start_node: str,
    end_node: str,
    node_by_id: gpd.GeoDataFrame,
    *,
    previous: Point | None,
) -> LineString:
    forward = geometry
    reverse = LineString(list(geometry.coords)[::-1])
    if previous is not None:
        return min(
            (forward, reverse),
            key=lambda line: float(previous.distance(Point(line.coords[0]))),
        )
    start_geometry = _node_geometry(start_node, node_by_id)
    end_geometry = _node_geometry(end_node, node_by_id)
    if start_geometry is None and end_geometry is None:
        return forward
    forward_score = _endpoint_score(
        forward,
        start_geometry,
        end_geometry,
    )
    reverse_score = _endpoint_score(
        reverse,
        start_geometry,
        end_geometry,
    )
    return forward if forward_score <= reverse_score else reverse


def _endpoint_score(
    geometry: LineString,
    start_geometry: object | None,
    end_geometry: object | None,
) -> float:
    score = 0.0
    if start_geometry is not None:
        score += float(Point(geometry.coords[0]).distance(start_geometry))
    if end_geometry is not None:
        score += float(Point(geometry.coords[-1]).distance(end_geometry))
    return score


def _node_geometry(
    node_id: str,
    node_by_id: gpd.GeoDataFrame,
) -> object | None:
    if node_id not in node_by_id.index:
        return None
    geometry = node_by_id.loc[node_id].geometry
    return (
        geometry
        if geometry is not None and not geometry.is_empty
        else None
    )


def _line_geometry(geometry: object) -> LineString | None:
    if geometry is None or getattr(geometry, "is_empty", True):
        return None
    if geometry.geom_type == "LineString":
        return geometry
    if geometry.geom_type == "MultiLineString":
        lines = [line for line in geometry.geoms if not line.is_empty]
        return max(lines, key=lambda line: float(line.length)) if lines else None
    return None


def _audit_row(
    segment: object,
    *,
    run_id: str,
    state: str,
    reason_code: str,
    path: Iterable[tuple[str, str, str]],
    maximum_join_gap_m: float | None,
    geometry: object,
) -> dict[str, object]:
    path_rows = tuple(path)
    member_ids = parse_id_list(segment.swsd_road_ids)
    path_ids = tuple(row[0] for row in path_rows)
    return {
        "run_id": run_id,
        "segment_id": canonical_id(segment.segment_id),
        "reference_state": state,
        "reference_source": (
            "swsd_endpoint_mainnode_topology_chain"
            if reason_code == "swsd_endpoint_mainnode_topology_chain_compiled"
            else "swsd_endpoint_topology_chain"
            if state == "resolved"
            else ""
        ),
        "carrier_guidance_eligible": bool(
            state == "resolved"
            and reason_code == "swsd_endpoint_topology_chain_compiled"
        ),
        "endpoint_node_ids": ",".join(
            parse_id_list(segment.pair_node_ids)
        ),
        "member_swsd_road_ids": ",".join(member_ids),
        "path_swsd_road_ids": ",".join(path_ids),
        "excluded_swsd_road_ids": ",".join(
            road_id for road_id in member_ids if road_id not in set(path_ids)
        ),
        "path_road_count": len(path_ids),
        "maximum_join_gap_m": maximum_join_gap_m,
        "reason_codes": reason_code,
        "geometry": geometry,
    }


def _frame(
    rows: list[dict[str, object]],
    crs: object,
) -> gpd.GeoDataFrame:
    if rows:
        return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    return gpd.GeoDataFrame(
        {
            "run_id": pd.Series(dtype=str),
            "segment_id": pd.Series(dtype=str),
            "reference_state": pd.Series(dtype=str),
            "reference_source": pd.Series(dtype=str),
            "carrier_guidance_eligible": pd.Series(dtype=bool),
            "endpoint_node_ids": pd.Series(dtype=str),
            "member_swsd_road_ids": pd.Series(dtype=str),
            "path_swsd_road_ids": pd.Series(dtype=str),
            "excluded_swsd_road_ids": pd.Series(dtype=str),
            "path_road_count": pd.Series(dtype=int),
            "maximum_join_gap_m": pd.Series(dtype=float),
            "reason_codes": pd.Series(dtype=str),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


__all__ = [
    "SegmentReferenceAxisResult",
    "build_segment_reference_axes",
]
