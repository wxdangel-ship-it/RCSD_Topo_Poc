from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import linemerge

from .segment_first_skeleton import canonical_id, parse_id_list


@dataclass(frozen=True)
class SwsdDirectionalPathResult:
    audit: gpd.GeoDataFrame
    member_roles: dict[tuple[str, str, str], str]
    summary: dict[str, object]


@dataclass(frozen=True)
class _DirectedMember:
    target_group_id: str
    member_swsd_road_id: str
    member_direction_role: str
    geometry: LineString


def build_swsd_segment_directional_paths(
    segment_units: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    t01_nodes: gpd.GeoDataFrame,
    segment_accesses: gpd.GeoDataFrame,
    *,
    run_id: str,
    maximum_candidate_paths: int = 64,
) -> SwsdDirectionalPathResult:
    """Resolve the SWSD member-Road paths that implement each dual Segment.

    SWSD supplies the functional path contract.  The returned member-role map
    only labels unambiguous paths; it never changes the T01 Segment set.
    """

    node_groups = _node_group_map(t01_nodes)
    road_frame = swsd_roads.copy()
    road_frame["_canonical_road_id"] = road_frame["id"].map(canonical_id)
    road_by_id = road_frame.drop_duplicates("_canonical_road_id").set_index(
        "_canonical_road_id"
    )
    endpoint_groups = _endpoint_groups_by_segment(segment_accesses)
    rows: list[dict[str, object]] = []
    member_roles: dict[tuple[str, str, str], str] = {}
    conflicting_role_keys: set[tuple[str, str, str]] = set()
    required_segments = 0
    resolved_segments = 0
    missing_direction_count = 0
    ambiguous_direction_count = 0

    for segment in segment_units.itertuples(index=False):
        segment_id = canonical_id(segment.segment_id)
        if (
            not bool(getattr(segment, "target_required", False))
            or str(getattr(segment, "target_class", "")) != "core_trunk"
            or not str(getattr(segment, "sgrade", "") or "").endswith("双")
        ):
            continue
        required_segments += 1
        terminals = endpoint_groups.get(segment_id, ())
        member_ids = parse_id_list(getattr(segment, "swsd_road_ids", ""))
        adjacency = _member_adjacency(member_ids, road_by_id, node_groups)
        direction_specs = (
            ("main_forward", terminals[0], terminals[1]),
            ("main_reverse", terminals[1], terminals[0]),
        ) if len(terminals) == 2 else ()
        segment_resolved = len(direction_specs) == 2
        for path_role, start_group_id, end_group_id in direction_specs:
            candidates = _enumerate_paths(
                adjacency,
                start_group_id,
                end_group_id,
                maximum_depth=max(1, len(member_ids)),
                maximum_candidates=maximum_candidate_paths,
            )
            if len(candidates) != 1:
                segment_resolved = False
                if candidates:
                    ambiguous_direction_count += 1
                    state = "ambiguous"
                    reason = "multiple_swsd_directional_member_paths"
                else:
                    missing_direction_count += 1
                    state = "missing"
                    reason = "swsd_directional_member_path_missing"
                rows.append(
                    {
                        "run_id": run_id,
                        "segment_id": segment_id,
                        "path_role": path_role,
                        "path_state": state,
                        "candidate_path_count": len(candidates),
                        "path_member_count": 0,
                        "path_member_order": -1,
                        "member_swsd_road_id": "",
                        "member_direction_role": "",
                        "terminal_start_group_id": start_group_id,
                        "terminal_end_group_id": end_group_id,
                        "reason_codes": reason,
                        "geometry": _longest_line(segment.geometry),
                    }
                )
                continue
            path = candidates[0]
            for order, member in enumerate(path):
                key = (
                    segment_id,
                    member.member_swsd_road_id,
                    member.member_direction_role,
                )
                previous = member_roles.get(key)
                if previous is not None and previous != path_role:
                    conflicting_role_keys.add(key)
                else:
                    member_roles[key] = path_role
                rows.append(
                    {
                        "run_id": run_id,
                        "segment_id": segment_id,
                        "path_role": path_role,
                        "path_state": "unique",
                        "candidate_path_count": 1,
                        "path_member_count": len(path),
                        "path_member_order": order,
                        "member_swsd_road_id": member.member_swsd_road_id,
                        "member_direction_role": member.member_direction_role,
                        "terminal_start_group_id": start_group_id,
                        "terminal_end_group_id": end_group_id,
                        "reason_codes": "swsd_directional_member_path_resolved",
                        "geometry": member.geometry,
                    }
                )
        if segment_resolved:
            resolved_segments += 1

    for key in conflicting_role_keys:
        member_roles.pop(key, None)
    audit = (
        gpd.GeoDataFrame(rows, geometry="geometry", crs=segment_units.crs)
        if rows
        else _empty_audit(segment_units.crs)
    )
    summary = {
        "required_dual_core_segment_count": required_segments,
        "resolved_dual_core_segment_count": resolved_segments,
        "unresolved_dual_core_segment_count": required_segments - resolved_segments,
        "missing_direction_count": missing_direction_count,
        "ambiguous_direction_count": ambiguous_direction_count,
        "member_role_count": len(member_roles),
        "member_role_conflict_count": len(conflicting_role_keys),
    }
    return SwsdDirectionalPathResult(audit, member_roles, summary)


def _node_group_map(nodes: gpd.GeoDataFrame) -> dict[str, str]:
    groups: dict[str, str] = {}
    for node in nodes.itertuples(index=False):
        node_id = canonical_id(node.id)
        mainnodeid = canonical_id(getattr(node, "mainnodeid", ""))
        groups[node_id] = mainnodeid if mainnodeid and mainnodeid != "0" else node_id
    return groups


def _endpoint_groups_by_segment(
    segment_accesses: gpd.GeoDataFrame,
) -> dict[str, tuple[str, ...]]:
    if segment_accesses.empty:
        return {}
    endpoints = segment_accesses[
        segment_accesses["access_type"].astype(str).str.upper().eq("ENDPOINT")
    ].copy()
    endpoints["_segment_id"] = endpoints["segment_id"].map(canonical_id)
    endpoints["_ordinal"] = pd.to_numeric(
        endpoints.get("access_ordinal", 0),
        errors="coerce",
    ).fillna(0)
    return {
        segment_id: tuple(
            group.sort_values("_ordinal", kind="stable")["junction_group_id"].map(
                canonical_id
            )
        )
        for segment_id, group in endpoints.groupby("_segment_id", sort=False)
    }


def _member_adjacency(
    member_ids: tuple[str, ...],
    road_by_id: gpd.GeoDataFrame,
    node_groups: dict[str, str],
) -> dict[str, list[_DirectedMember]]:
    adjacency: dict[str, list[_DirectedMember]] = defaultdict(list)
    for member_id in member_ids:
        if member_id not in road_by_id.index:
            continue
        road = road_by_id.loc[member_id]
        geometry = _longest_line(road.geometry)
        if geometry is None:
            continue
        source_group = node_groups.get(
            canonical_id(road.snodeid),
            canonical_id(road.snodeid),
        )
        target_group = node_groups.get(
            canonical_id(road.enodeid),
            canonical_id(road.enodeid),
        )
        direction = int(road.get("direction", 1) or 1)
        if direction in {0, 1, 2}:
            adjacency[source_group].append(
                _DirectedMember(
                    target_group,
                    member_id,
                    "forward",
                    geometry,
                )
            )
        if direction in {0, 1, 3}:
            adjacency[target_group].append(
                _DirectedMember(
                    source_group,
                    member_id,
                    "reverse",
                    LineString(list(geometry.coords)[::-1]),
                )
            )
    for members in adjacency.values():
        members.sort(
            key=lambda member: (
                member.target_group_id,
                member.member_swsd_road_id,
                member.member_direction_role,
            )
        )
    return adjacency


def _enumerate_paths(
    adjacency: dict[str, list[_DirectedMember]],
    start_group_id: str,
    end_group_id: str,
    *,
    maximum_depth: int,
    maximum_candidates: int,
) -> list[tuple[_DirectedMember, ...]]:
    paths: list[tuple[_DirectedMember, ...]] = []

    def visit(
        group_id: str,
        visited_groups: set[str],
        visited_members: set[str],
        path: list[_DirectedMember],
    ) -> None:
        if len(paths) >= maximum_candidates or len(path) > maximum_depth:
            return
        if group_id == end_group_id:
            paths.append(tuple(path))
            return
        for member in adjacency.get(group_id, ()):
            if (
                member.target_group_id in visited_groups
                or member.member_swsd_road_id in visited_members
            ):
                continue
            visit(
                member.target_group_id,
                visited_groups | {member.target_group_id},
                visited_members | {member.member_swsd_road_id},
                [*path, member],
            )

    visit(start_group_id, {start_group_id}, set(), [])
    unique = {
        tuple(
            (
                member.member_swsd_road_id,
                member.member_direction_role,
            )
            for member in path
        ): path
        for path in paths
    }
    return [
        unique[key]
        for key in sorted(unique, key=lambda value: (len(value), value))
    ]


def _longest_line(geometry: object) -> LineString | None:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, LineString):
        return geometry
    merged = linemerge(geometry)
    if isinstance(merged, LineString):
        return merged
    lines = [
        part
        for part in getattr(merged, "geoms", ())
        if isinstance(part, LineString)
    ]
    return max(lines, key=lambda line: line.length) if lines else None


def _empty_audit(crs: object) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "run_id": pd.Series(dtype=str),
            "segment_id": pd.Series(dtype=str),
            "path_role": pd.Series(dtype=str),
            "path_state": pd.Series(dtype=str),
            "candidate_path_count": pd.Series(dtype=int),
            "path_member_count": pd.Series(dtype=int),
            "path_member_order": pd.Series(dtype=int),
            "member_swsd_road_id": pd.Series(dtype=str),
            "member_direction_role": pd.Series(dtype=str),
            "terminal_start_group_id": pd.Series(dtype=str),
            "terminal_end_group_id": pd.Series(dtype=str),
            "reason_codes": pd.Series(dtype=str),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


__all__ = [
    "SwsdDirectionalPathResult",
    "build_swsd_segment_directional_paths",
]
