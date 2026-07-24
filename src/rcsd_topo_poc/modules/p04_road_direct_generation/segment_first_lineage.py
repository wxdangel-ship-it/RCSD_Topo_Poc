from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import hashlib

import geopandas as gpd
import pandas as pd
from shapely.ops import substring

from .segment_first_movements import (
    _patch_lane_ids,
    _projection_measure_range,
    _split_keys,
)
from .segment_first_nodes import NodeBuildResult
from .segment_first_skeleton import canonical_id


@dataclass(frozen=True)
class RoadLineageSplitResult:
    roads: gpd.GeoDataFrame
    geometry_sources: gpd.GeoDataFrame
    internal_nodes: gpd.GeoDataFrame
    audit: gpd.GeoDataFrame
    summary: dict[str, object]


def split_roads_at_stable_lineage_boundaries(
    roads: gpd.GeoDataFrame,
    base_geometry_sources: gpd.GeoDataFrame,
    evidence_sources: gpd.GeoDataFrame,
    *,
    run_id: str,
    minimum_part_length_m: float,
    maximum_handoff_gap_m: float,
    maximum_handoff_overlap_m: float,
    lane_group_relations: gpd.GeoDataFrame | None = None,
    maximum_lane_group_distance_m: float = 20.0,
    protected_split_surface: object | None = None,
    existing_node_ids: set[int] | None = None,
) -> RoadLineageSplitResult:
    """Split accepted, smoothed Roads without changing their union geometry.

    LaneGroup/Road identity is only a Road-lineage boundary candidate. It never
    creates or changes a business Segment, direction role, or Junction relation.
    """
    if roads.empty or evidence_sources.empty:
        return RoadLineageSplitResult(
            roads.copy(),
            base_geometry_sources.copy(),
            _empty_nodes(roads.crs),
            _empty_audit(roads.crs),
            _summary(0, 0, 0, 0, 0, minimum_part_length_m,
                     maximum_handoff_gap_m, maximum_handoff_overlap_m),
        )
    sources = evidence_sources.drop_duplicates("patch_road_key").copy()
    source_geometry = {
        str(row.patch_road_key): row.geometry for row in sources.itertuples()
    }
    source_lineage = {
        str(row.patch_road_key): _lineage_id(row)
        for row in sources.itertuples()
    }
    patch_lane_ids = _patch_lane_ids(sources)
    base_by_road = {
        str(road_id): group.copy()
        for road_id, group in base_geometry_sources.groupby(
            base_geometry_sources["road_id"].astype(str),
            sort=False,
        )
    } if not base_geometry_sources.empty else {}
    used_ids = {int(value) for value in roads["id"]}
    used_node_ids = set(existing_node_ids or ())

    output_rows: list[dict[str, object]] = []
    source_rows: list[dict[str, object]] = []
    internal_node_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    split_parent_count = 0
    split_part_count = 0
    protected_boundary_count = 0
    lane_group_boundary_count = 0
    for road in roads.itertuples(index=False):
        row = road._asdict()
        if (
            str(getattr(road, "realization", "")) != "built"
            or str(getattr(road, "owner_type", "")) != "SEGMENT"
        ):
            output_rows.append(row)
            source_rows.extend(
                _unchanged_sources(base_by_road.get(str(road.id)))
            )
            continue
        keys = _split_keys(getattr(road, "source_patch_road_keys", ""))
        intervals = _lineage_intervals(
            road.geometry,
            keys,
            source_geometry,
            source_lineage,
        )
        candidates = _stable_boundaries(
            intervals,
            float(road.geometry.length),
            minimum_part_length_m=minimum_part_length_m,
            maximum_handoff_gap_m=maximum_handoff_gap_m,
            maximum_handoff_overlap_m=maximum_handoff_overlap_m,
        )
        lane_group_intervals, lane_group_lane_ids = (
            _lane_group_intervals(
                road.geometry,
                keys,
                _split_keys(getattr(road, "source_lane_ids", "")),
                lane_group_relations,
                maximum_distance_m=maximum_lane_group_distance_m,
            )
        )
        lane_group_candidates = [
            (
                measure,
                f"lane_group:{left_lineage}",
                f"lane_group:{right_lineage}",
            )
            for measure, left_lineage, right_lineage in _stable_boundaries(
                lane_group_intervals,
                float(road.geometry.length),
                minimum_part_length_m=minimum_part_length_m,
                maximum_handoff_gap_m=maximum_handoff_gap_m,
                maximum_handoff_overlap_m=maximum_handoff_overlap_m,
            )
        ]
        candidates = _merge_boundary_candidates(
            candidates,
            lane_group_candidates,
            minimum_part_length_m=minimum_part_length_m,
            total_length_m=float(road.geometry.length),
        )
        boundaries = []
        for boundary in candidates:
            point = road.geometry.interpolate(boundary[0])
            if (
                protected_split_surface is not None
                and not protected_split_surface.is_empty
                and protected_split_surface.covers(point)
            ):
                protected_boundary_count += 1
                audit_rows.append(
                    _audit_row(
                        road,
                        boundary,
                        point,
                        run_id=run_id,
                        decision="rejected",
                        reason="junction_relation_scope_protected",
                    )
                )
            else:
                boundaries.append(boundary)
                if _is_lane_group_boundary(boundary):
                    lane_group_boundary_count += 1
        if not boundaries:
            output_rows.append(row)
            source_rows.extend(
                _unchanged_sources(base_by_road.get(str(road.id)))
            )
            continue
        split_parent_count += 1
        measures = [0.0, *[value[0] for value in boundaries], road.geometry.length]
        boundary_node_ids = [
            _stable_node_id(
                int(road.id),
                boundary_index,
                boundary[0],
                used_node_ids,
            )
            for boundary_index, boundary in enumerate(boundaries)
        ]
        for node_id, boundary in zip(boundary_node_ids, boundaries):
            point = road.geometry.interpolate(boundary[0])
            internal_node_rows.append(
                _internal_node_row(node_id, point, run_id)
            )
        parent_sources = base_by_road.get(str(road.id))
        part_count = len(measures) - 1
        split_part_count += part_count
        key_ranges = {
            key: _projection_measure_range(road.geometry, source_geometry[key])
            for key in keys
            if key in source_geometry
        }
        key_ranges.update(
            {
                str(interval["patch_road_key"]): (
                    float(interval["start_m"]),
                    float(interval["end_m"]),
                )
                for interval in lane_group_intervals
            }
        )
        for part_index, (start_m, end_m) in enumerate(
            zip(measures, measures[1:])
        ):
            part = dict(row)
            part_id = (
                int(road.id)
                if part_index == 0
                else _stable_part_id(
                    int(road.id),
                    part_index,
                    start_m,
                    end_m,
                    used_ids,
                )
            )
            part_geometry = substring(road.geometry, start_m, end_m)
            part_keys = sorted(
                key
                for key, (key_start, key_end) in key_ranges.items()
                if min(end_m, key_end) - max(start_m, key_start) > 1e-6
            )
            if not part_keys:
                part_keys = keys
            lane_ids = sorted(
                {
                    lane_id
                    for key in part_keys
                    for lane_id in (
                        set(patch_lane_ids.get(key, ()))
                        | set(lane_group_lane_ids.get(key, ()))
                    )
                    if lane_id
                }
            )
            part.update(
                {
                    "id": part_id,
                    "carrier_id": (
                        f"lineage-road:{int(road.id)}:part:{part_index}"
                    ),
                    "lineage_parent_road_id": int(road.id),
                    "lineage_part_index": part_index,
                    "snodeid": (
                        getattr(road, "snodeid", 0)
                        if part_index == 0
                        else boundary_node_ids[part_index - 1]
                    ),
                    "enodeid": (
                        getattr(road, "enodeid", 0)
                        if part_index == part_count - 1
                        else boundary_node_ids[part_index]
                    ),
                    "source_snodeid": (
                        getattr(road, "source_snodeid", "")
                        if part_index == 0
                        else ""
                    ),
                    "source_enodeid": (
                        getattr(road, "source_enodeid", "")
                        if part_index == part_count - 1
                        else ""
                    ),
                    "length": float(part_geometry.length),
                    "base_geometry_length_m": float(part_geometry.length),
                    "patch_road_key": part_keys[0] if part_keys else "",
                    "source_road_id": ",".join(part_keys),
                    "source_patch_road_keys": ",".join(part_keys),
                    "source_patch_ids": ",".join(
                        sorted(
                            {
                                key.split(":", 1)[0]
                                for key in part_keys
                                if ":" in key
                            }
                        )
                    ),
                    "patchid": ",".join(
                        sorted(
                            {
                                key.split(":", 1)[0]
                                for key in part_keys
                                if ":" in key
                            }
                        )
                    ),
                    "start_patch_road_keys": (
                        str(getattr(road, "start_patch_road_keys", ""))
                        if part_index == 0
                        else ""
                    ),
                    "end_patch_road_keys": (
                        str(getattr(road, "end_patch_road_keys", ""))
                        if part_index == part_count - 1
                        else ""
                    ),
                    "start_access_ids": (
                        str(getattr(road, "start_access_ids", ""))
                        if part_index == 0
                        else ""
                    ),
                    "end_access_ids": (
                        str(getattr(road, "end_access_ids", ""))
                        if part_index == part_count - 1
                        else ""
                    ),
                    "start_junction_group_ids": (
                        str(
                            getattr(
                                road,
                                "start_junction_group_ids",
                                "",
                            )
                        )
                        if part_index == 0
                        else ""
                    ),
                    "end_junction_group_ids": (
                        str(
                            getattr(
                                road,
                                "end_junction_group_ids",
                                "",
                            )
                        )
                        if part_index == part_count - 1
                        else ""
                    ),
                    "source_lane_ids": ",".join(lane_ids),
                    "lineage_internal_start": part_index > 0,
                    "lineage_internal_end": part_index < part_count - 1,
                    "assembly_state": (
                        f"{getattr(road, 'assembly_state', '')}"
                        "+stable_lineage_split"
                    ),
                    "geometry": part_geometry,
                }
            )
            output_rows.append(part)
            source_rows.extend(
                _clip_sources(
                    parent_sources,
                    parent_length_m=float(road.geometry.length),
                    part_start_m=start_m,
                    part_end_m=end_m,
                    part_id=part_id,
                    segment_id=str(getattr(road, "segment_id", "")),
                    part_geometry=part_geometry,
                    run_id=run_id,
                )
            )
        for measure, left_lineage, right_lineage in boundaries:
            audit_rows.append(
                _audit_row(
                    road,
                    (measure, left_lineage, right_lineage),
                    road.geometry.interpolate(measure),
                    run_id=run_id,
                    decision="accepted",
                    reason=(
                        "stable_lane_group_handoff"
                        if _is_lane_group_boundary(
                            (measure, left_lineage, right_lineage)
                        )
                        else "stable_longitudinal_lineage_handoff"
                    ),
                )
            )

    output = gpd.GeoDataFrame(output_rows, geometry="geometry", crs=roads.crs)
    geometry_sources = (
        gpd.GeoDataFrame(
            source_rows,
            geometry="geometry",
            crs=base_geometry_sources.crs,
        )
        if source_rows
        else base_geometry_sources.iloc[0:0].copy()
    )
    internal_nodes = (
        gpd.GeoDataFrame(internal_node_rows, geometry="geometry", crs=roads.crs)
        if internal_node_rows
        else _empty_nodes(roads.crs)
    )
    audit = (
        gpd.GeoDataFrame(audit_rows, geometry="geometry", crs=roads.crs)
        if audit_rows
        else _empty_audit(roads.crs)
    )
    return RoadLineageSplitResult(
        output,
        geometry_sources,
        internal_nodes,
        audit,
        _summary(
            split_parent_count,
            sum(row["split_decision"] == "accepted" for row in audit_rows),
            split_part_count,
            protected_boundary_count,
            lane_group_boundary_count,
            minimum_part_length_m,
            maximum_handoff_gap_m,
            maximum_handoff_overlap_m,
        ),
    )


def attach_lineage_split_to_node_build(
    node_build: NodeBuildResult,
    split: RoadLineageSplitResult,
    *,
    run_id: str,
) -> NodeBuildResult:
    """Insert split-only Nodes without recompiling established portal Nodes."""
    if not split.summary["split_boundary_count"]:
        return node_build
    nodes = gpd.GeoDataFrame(
        pd.concat([node_build.nodes, split.internal_nodes], ignore_index=True),
        geometry="geometry",
        crs=node_build.nodes.crs,
    )
    part_rows = split.roads.loc[
        split.roads["lineage_parent_road_id"].notna()
    ].copy()
    parts_by_parent = {
        str(int(parent_id)): frame.sort_values("lineage_part_index")
        for parent_id, frame in part_rows.groupby("lineage_parent_road_id")
    }
    endpoint_audit = _remap_endpoint_audit(
        node_build.endpoint_audit,
        parts_by_parent,
        nodes,
        run_id,
    )
    completions = _remap_endpoint_records(
        node_build.completion_sources,
        parts_by_parent,
    )
    connection_evidence = _remap_connection_evidence(
        node_build.connection_evidence,
        parts_by_parent,
    )
    summary = dict(node_build.summary)
    summary.update(
        {
            "node_count": int(len(nodes)),
            "road_endpoint_count": int(len(split.roads) * 2),
            "constrained_completion_count": int(len(completions)),
            "max_endpoint_shift_m": float(
                endpoint_audit["endpoint_shift_m"].max()
            ),
            "missing_node_reference_count": int(
                (~split.roads["snodeid"].isin(nodes["id"])).sum()
                + (~split.roads["enodeid"].isin(nodes["id"])).sum()
            ),
        }
    )
    return NodeBuildResult(
        split.roads,
        nodes,
        endpoint_audit,
        completions,
        connection_evidence,
        summary,
    )


def _remap_endpoint_audit(
    audit: gpd.GeoDataFrame,
    parts_by_parent: dict[str, gpd.GeoDataFrame],
    nodes: gpd.GeoDataFrame,
    run_id: str,
) -> gpd.GeoDataFrame:
    split_ids = set(parts_by_parent)
    rows = [
        row._asdict()
        for row in audit.itertuples(index=False)
        if str(row.road_id) not in split_ids
    ]
    node_by_id = {str(row.id): row for row in nodes.itertuples(index=False)}
    for parent_id, parts in parts_by_parent.items():
        old = audit.loc[audit["road_id"].astype(str) == parent_id]
        templates = {
            str(row.endpoint): row._asdict()
            for row in old.itertuples(index=False)
        }
        part_records = list(parts.itertuples(index=False))
        for index, part in enumerate(part_records):
            for endpoint in ("start", "end"):
                outer = (
                    endpoint == "start" and index == 0
                ) or (
                    endpoint == "end" and index == len(part_records) - 1
                )
                node_id = (
                    getattr(part, "snodeid")
                    if endpoint == "start"
                    else getattr(part, "enodeid")
                )
                node = node_by_id[str(node_id)]
                row = dict(templates.get(endpoint, {})) if outer else {}
                row.update(
                    {
                        "run_id": run_id,
                        "road_id": part.id,
                        "endpoint": endpoint,
                        "node_id": node_id,
                        "mainnodeid": node.mainnodeid,
                        "geometry": node.geometry,
                    }
                )
                if not outer:
                    row.update(
                        {
                            "junction_group_id": "",
                            "junction_membership_source": (
                                "stable_lineage_internal_node"
                            ),
                            "junction_surface_distance_m": None,
                            "junction_access_distance_m": None,
                            "endpoint_shift_m": 0.0,
                            "connection_state": "unchanged",
                            "review_required": False,
                            "reason_codes": "stable_lineage_internal_node",
                        }
                    )
                rows.append(row)
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=audit.crs)


def _remap_endpoint_records(
    records: gpd.GeoDataFrame,
    parts_by_parent: dict[str, gpd.GeoDataFrame],
) -> gpd.GeoDataFrame:
    if records.empty:
        return records.copy()
    output = records.copy()
    for index, row in output.iterrows():
        parts = parts_by_parent.get(str(row["road_id"]))
        if parts is None:
            continue
        target = parts.iloc[-1] if str(row.get("endpoint", "")) == "end" else parts.iloc[0]
        output.at[index, "road_id"] = target["id"]
        output.at[index, "source_span_id"] = (
            f"{target['id']}:{row.get('endpoint', '')}:completion"
        )
    return output


def _remap_connection_evidence(
    records: gpd.GeoDataFrame,
    parts_by_parent: dict[str, gpd.GeoDataFrame],
) -> gpd.GeoDataFrame:
    if records.empty:
        return records.copy()
    output = records.copy()
    for field, take_last in (
        ("source_road_id", True),
        ("target_road_id", False),
    ):
        for index, value in output[field].items():
            parts = parts_by_parent.get(str(value))
            if parts is not None:
                output.at[index, field] = parts.iloc[-1 if take_last else 0]["id"]
    return output


def _unchanged_sources(
    sources: gpd.GeoDataFrame | None,
) -> list[dict[str, object]]:
    return (
        [row._asdict() for row in sources.itertuples(index=False)]
        if sources is not None
        else []
    )


def _audit_row(
    road: object,
    boundary: tuple[float, str, str],
    point: object,
    *,
    run_id: str,
    decision: str,
    reason: str,
) -> dict[str, object]:
    measure, left_lineage, right_lineage = boundary
    return {
        "run_id": run_id,
        "parent_road_id": str(road.id),
        "segment_id": str(getattr(road, "segment_id", "")),
        "carrier_role": str(getattr(road, "carrier_role", "")),
        "left_lineage_id": left_lineage,
        "right_lineage_id": right_lineage,
        "split_measure_m": measure,
        "split_decision": decision,
        "reason_codes": reason,
        "geometry": point,
    }


def _clip_sources(
    sources: gpd.GeoDataFrame | None,
    *,
    parent_length_m: float,
    part_start_m: float,
    part_end_m: float,
    part_id: int,
    segment_id: str,
    part_geometry: object,
    run_id: str,
) -> list[dict[str, object]]:
    if sources is None or sources.empty or parent_length_m <= 1e-9:
        return []
    part_start = part_start_m / parent_length_m
    part_end = part_end_m / parent_length_m
    part_width = part_end - part_start
    rows: list[dict[str, object]] = []
    for source in sources.itertuples(index=False):
        start = max(part_start, float(source.start_fraction))
        end = min(part_end, float(source.end_fraction))
        if end - start <= 1e-9:
            continue
        relative_start = (start - part_start) / part_width
        relative_end = (end - part_start) / part_width
        row = source._asdict()
        row.update(
            {
                "run_id": run_id,
                "road_id": part_id,
                "segment_id": segment_id,
                "source_span_id": f"{part_id}:{len(rows)}",
                "start_fraction": relative_start,
                "end_fraction": relative_end,
                "length_m": float(
                    (relative_end - relative_start) * part_geometry.length
                ),
                "geometry": substring(
                    part_geometry,
                    relative_start * part_geometry.length,
                    relative_end * part_geometry.length,
                ),
            }
        )
        rows.append(row)
    return rows


def _lineage_intervals(
    road_geometry: object,
    source_keys: list[str],
    source_geometry: dict[str, object],
    source_lineage: dict[str, str],
) -> list[dict[str, object]]:
    grouped: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for key in source_keys:
        geometry = source_geometry.get(key)
        lineage = source_lineage.get(key, key)
        if geometry is None or not lineage:
            continue
        grouped[lineage].append(
            _projection_measure_range(road_geometry, geometry)
        )
    return [
        {
            "lineage_id": lineage,
            "start_m": min(start for start, _ in ranges),
            "end_m": max(end for _, end in ranges),
        }
        for lineage, ranges in grouped.items()
        if max(end for _, end in ranges) - min(start for start, _ in ranges)
        > 1e-6
    ]


def _lane_group_intervals(
    road_geometry: object,
    source_keys: list[str],
    source_lane_ids: list[str],
    relations: gpd.GeoDataFrame | None,
    *,
    maximum_distance_m: float,
) -> tuple[list[dict[str, object]], dict[str, set[str]]]:
    if relations is None or relations.empty:
        return [], {}
    keys = set(source_keys)
    lane_ids = set(source_lane_ids)
    selected = relations[
        relations["patch_road_key"].astype(str).isin(keys)
        | relations["lane_id"].astype(str).isin(lane_ids)
    ].copy()
    if selected.empty:
        return [], {}
    intervals: list[dict[str, object]] = []
    lane_ids_by_group: dict[str, set[str]] = {}
    for patch_road_key, group in selected.groupby(
        selected["patch_road_key"].astype(str),
        sort=True,
    ):
        ranges: list[tuple[float, float]] = []
        for row in group.itertuples():
            geometry = row.geometry
            if (
                geometry is None
                or geometry.is_empty
                or float(road_geometry.distance(geometry))
                > maximum_distance_m + 1e-9
            ):
                continue
            ranges.append(
                _projection_measure_range(road_geometry, geometry)
            )
        if not ranges:
            continue
        start_m = min(start for start, _ in ranges)
        end_m = max(end for _, end in ranges)
        if end_m - start_m <= 1e-6:
            continue
        intervals.append(
            {
                "lineage_id": str(patch_road_key),
                "patch_road_key": str(patch_road_key),
                "start_m": start_m,
                "end_m": end_m,
            }
        )
        lane_ids_by_group[str(patch_road_key)] = {
            canonical_id(value)
            for value in group["lane_id"]
            if canonical_id(value) in lane_ids
        }
    return intervals, lane_ids_by_group


def _merge_boundary_candidates(
    primary: list[tuple[float, str, str]],
    lane_group: list[tuple[float, str, str]],
    *,
    minimum_part_length_m: float,
    total_length_m: float,
) -> list[tuple[float, str, str]]:
    selected = sorted(primary)
    for candidate in sorted(lane_group):
        if any(
            abs(candidate[0] - existing[0])
            < minimum_part_length_m - 1e-6
            for existing in selected
        ):
            continue
        selected.append(candidate)
    output: list[tuple[float, str, str]] = []
    for candidate in sorted(selected):
        if (
            candidate[0] < minimum_part_length_m - 1e-6
            or total_length_m - candidate[0]
            < minimum_part_length_m - 1e-6
            or (
                output
                and candidate[0] - output[-1][0]
                < minimum_part_length_m - 1e-6
            )
        ):
            continue
        output.append(candidate)
    return output


def _is_lane_group_boundary(
    boundary: tuple[float, str, str],
) -> bool:
    return str(boundary[1]).startswith("lane_group:") or str(
        boundary[2]
    ).startswith("lane_group:")


def _stable_boundaries(
    intervals: list[dict[str, object]],
    total_length_m: float,
    *,
    minimum_part_length_m: float,
    maximum_handoff_gap_m: float,
    maximum_handoff_overlap_m: float,
) -> list[tuple[float, str, str]]:
    ordered = sorted(
        intervals,
        key=lambda row: (
            float(row["start_m"]),
            float(row["end_m"]),
            str(row["lineage_id"]),
        ),
    )
    candidates: list[tuple[float, str, str]] = []
    for left, right in zip(ordered, ordered[1:]):
        left_start = float(left["start_m"])
        left_end = float(left["end_m"])
        right_start = float(right["start_m"])
        right_end = float(right["end_m"])
        if left_end >= right_end - 1e-6:
            continue
        if min(left_end - left_start, right_end - right_start) + 1e-6 < (
            minimum_part_length_m
        ):
            continue
        handoff_delta = right_start - left_end
        if handoff_delta > maximum_handoff_gap_m + 1e-6:
            continue
        if handoff_delta < -maximum_handoff_overlap_m - 1e-6:
            continue
        boundary = (left_end + right_start) / 2.0
        if not (
            minimum_part_length_m - 1e-6
            <= boundary
            <= total_length_m - minimum_part_length_m + 1e-6
        ):
            continue
        if _is_spanned_by_third_lineage(
            ordered,
            boundary,
            {str(left["lineage_id"]), str(right["lineage_id"])},
            minimum_part_length_m,
        ):
            continue
        candidates.append(
            (
                boundary,
                str(left["lineage_id"]),
                str(right["lineage_id"]),
            )
        )

    selected: list[tuple[float, str, str]] = []
    for candidate in sorted(candidates):
        if (
            selected
            and candidate[0] - selected[-1][0] < minimum_part_length_m - 1e-6
        ):
            continue
        if total_length_m - candidate[0] < minimum_part_length_m - 1e-6:
            continue
        selected.append(candidate)
    return selected


def _is_spanned_by_third_lineage(
    intervals: list[dict[str, object]],
    boundary_m: float,
    adjacent_lineages: set[str],
    minimum_part_length_m: float,
) -> bool:
    flank = minimum_part_length_m / 2.0
    return any(
        str(row["lineage_id"]) not in adjacent_lineages
        and float(row["start_m"]) <= boundary_m - flank
        and float(row["end_m"]) >= boundary_m + flank
        for row in intervals
    )


def _stable_part_id(
    parent_id: int,
    part_index: int,
    start_m: float,
    end_m: float,
    used_ids: set[int],
) -> int:
    salt = 0
    while True:
        payload = (
            f"p04-lineage-part|{parent_id}|{part_index}|"
            f"{start_m:.6f}|{end_m:.6f}|{salt}"
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        candidate = 7_000_000_000_000_000 + (
            int(digest[:16], 16) % 1_900_000_000_000_000
        )
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate
        salt += 1


def _stable_node_id(
    parent_id: int,
    boundary_index: int,
    measure_m: float,
    used_ids: set[int],
) -> int:
    salt = 0
    while True:
        payload = (
            f"p04-lineage-node|{parent_id}|{boundary_index}|"
            f"{measure_m:.6f}|{salt}"
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        candidate = 8_000_000_000_000_000 + (
            int(digest[:16], 16) % 900_000_000_000_000
        )
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate
        salt += 1


def _internal_node_row(
    node_id: int,
    point: object,
    run_id: str,
) -> dict[str, object]:
    return {
        "id": node_id,
        "mapid": 0,
        "kind": 0,
        "cross_flag": 0,
        "light_flag": 0,
        "cross_lid": "",
        "mainnodeid": node_id,
        "subnodeid": "",
        "adjoin_mid": "",
        "adjoind_nid": "",
        "node_lid": "",
        "source": 1,
        "city_code": "",
        "layer": 0,
        "city_patch_ids": "",
        "park_patch_ids": "",
        "junction_group_ids": "",
        "junction_kind": "",
        "run_id": run_id,
        "geometry": point,
    }


def _lineage_id(row: object) -> str:
    patch_id = canonical_id(getattr(row, "source_patch_id", ""))
    road_id = canonical_id(getattr(row, "road_id", ""))
    if patch_id and road_id:
        return f"{patch_id}:road:{road_id}"
    return str(getattr(row, "patch_road_key", "") or "")


def _summary(
    parent_count: int,
    boundary_count: int,
    part_count: int,
    protected_boundary_count: int,
    lane_group_boundary_count: int,
    minimum_part_length_m: float,
    maximum_handoff_gap_m: float,
    maximum_handoff_overlap_m: float,
) -> dict[str, object]:
    return {
        "split_parent_count": int(parent_count),
        "split_boundary_count": int(boundary_count),
        "split_part_count": int(part_count),
        "protected_boundary_rejection_count": int(protected_boundary_count),
        "lane_group_split_boundary_count": int(
            lane_group_boundary_count
        ),
        "minimum_part_length_m": float(minimum_part_length_m),
        "maximum_handoff_gap_m": float(maximum_handoff_gap_m),
        "maximum_handoff_overlap_m": float(maximum_handoff_overlap_m),
    }


def _empty_audit(crs: object) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "run_id": pd.Series(dtype="object"),
            "parent_road_id": pd.Series(dtype="object"),
            "segment_id": pd.Series(dtype="object"),
            "carrier_role": pd.Series(dtype="object"),
            "left_lineage_id": pd.Series(dtype="object"),
            "right_lineage_id": pd.Series(dtype="object"),
            "split_measure_m": pd.Series(dtype="float64"),
            "split_decision": pd.Series(dtype="object"),
            "reason_codes": pd.Series(dtype="object"),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


def _empty_nodes(crs: object) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "id": pd.Series(dtype="int64"),
            "mapid": pd.Series(dtype="int64"),
            "kind": pd.Series(dtype="int64"),
            "cross_flag": pd.Series(dtype="int64"),
            "light_flag": pd.Series(dtype="int64"),
            "cross_lid": pd.Series(dtype="object"),
            "mainnodeid": pd.Series(dtype="int64"),
            "subnodeid": pd.Series(dtype="object"),
            "adjoin_mid": pd.Series(dtype="object"),
            "adjoind_nid": pd.Series(dtype="object"),
            "node_lid": pd.Series(dtype="object"),
            "source": pd.Series(dtype="int64"),
            "city_code": pd.Series(dtype="object"),
            "layer": pd.Series(dtype="int64"),
            "city_patch_ids": pd.Series(dtype="object"),
            "park_patch_ids": pd.Series(dtype="object"),
            "junction_group_ids": pd.Series(dtype="object"),
            "junction_kind": pd.Series(dtype="object"),
            "run_id": pd.Series(dtype="object"),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


__all__ = [
    "RoadLineageSplitResult",
    "attach_lineage_split_to_node_build",
    "split_roads_at_stable_lineage_boundaries",
]
