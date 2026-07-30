from __future__ import annotations

from dataclasses import dataclass
import json
import math
import weakref

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points
from shapely.ops import substring, unary_union

from .segment_first_junctions import endpoint_surface_geometry
from .segment_first_surface_routing import interior_surface_target

_MIN_THROUGH_SPLIT_PART_LENGTH_M = 2.0
_JUNCTION_SURFACE_CACHE: dict[
    int,
    tuple[weakref.ReferenceType[gpd.GeoDataFrame], int, dict[str, object]],
] = {}


@dataclass(frozen=True)
class MovementSplitResult:
    carriers: gpd.GeoDataFrame
    audit: gpd.GeoDataFrame
    summary: dict[str, object]


def split_carriers_at_movement_anchors(
    carriers: gpd.GeoDataFrame,
    assignments: gpd.GeoDataFrame,
    explicit_pairs: pd.DataFrame,
    *,
    run_id: str,
    maximum_anchor_distance_m: float,
) -> MovementSplitResult:
    """Split assembled Roads only where a cross-Road movement lands mid-Road."""
    if carriers.empty or assignments.empty or explicit_pairs.empty:
        return MovementSplitResult(
            carriers.copy(),
            _empty_audit(carriers.crs),
            {"split_parent_count": 0, "split_part_count": 0, "rejected_anchor_count": 0},
        )
    patch_geometry = {
        str(patch_road_key): max(
            group.geometry,
            key=lambda geometry: float(geometry.length),
        )
        for patch_road_key, group in assignments.groupby(
            assignments["patch_road_key"].astype(str),
            sort=False,
        )
    }
    assignment_segments = {
        str(patch_road_key): {
            str(value)
            for value in group.get(
                "assigned_segment_id",
                pd.Series("", index=group.index),
            )
            if str(value) and str(value).lower() != "nan"
        }
        for patch_road_key, group in assignments.groupby(
            assignments["patch_road_key"].astype(str),
            sort=False,
        )
    }
    carrier_by_patch: dict[str, list[int]] = {}
    carriers_by_segment: dict[str, list[int]] = {}
    for index, carrier in carriers.iterrows():
        if str(carrier.get("realization", "")) != "built":
            continue
        carriers_by_segment.setdefault(
            str(carrier.get("segment_id", "")),
            [],
        ).append(int(index))
        for key in _split_keys(carrier.get("source_patch_road_keys", "")):
            carrier_by_patch.setdefault(key, []).append(int(index))

    split_requests: dict[int, list[dict[str, object]]] = {}
    audit_rows: list[dict[str, object]] = []
    for pair in explicit_pairs.itertuples():
        source_key = str(pair.source_patch_road_key)
        target_key = str(pair.target_patch_road_key)
        source_index = _select_movement_carrier(
            source_key,
            "end",
            carriers,
            patch_geometry,
            carrier_by_patch,
            carriers_by_segment,
            assignment_segments,
        )
        target_index = _select_movement_carrier(
            target_key,
            "start",
            carriers,
            patch_geometry,
            carrier_by_patch,
            carriers_by_segment,
            assignment_segments,
        )
        if source_index is None or target_index is None or source_index == target_index:
            continue
        surface_routing_peer = any(
            "endpoint_surface_constrained_routing"
            in str(carriers.loc[index].get("assembly_state", ""))
            for index in (source_index, target_index)
        )
        for role, key, index, endpoint_name in (
            ("source_end", source_key, source_index, "end"),
            ("target_start", target_key, target_index, "start"),
        ):
            carrier = carriers.loc[index]
            endpoint_keys = _split_keys(
                carrier.get(
                    "end_patch_road_keys" if endpoint_name == "end" else "start_patch_road_keys",
                    "",
                )
            )
            if key in endpoint_keys or key not in patch_geometry:
                continue
            patch_line = patch_geometry[key]
            anchor = patch_line.interpolate(1.0 if endpoint_name == "end" else 0.0, normalized=True)
            measure = float(carrier.geometry.project(anchor))
            distance = float(anchor.distance(carrier.geometry))
            interior = 1.0 < measure < float(carrier.geometry.length) - 1.0
            accepted = interior and distance <= maximum_anchor_distance_m
            audit_rows.append(
                {
                    "run_id": run_id,
                    "source_patch_road_key": source_key,
                    "target_patch_road_key": target_key,
                    "carrier_id": str(carrier.carrier_id),
                    "anchor_role": role,
                    "split_measure_m": measure,
                    "anchor_distance_m": distance,
                    "split_decision": "accepted" if accepted else "rejected",
                    "reason_codes": (
                        "cross_road_movement_internal_anchor"
                        if accepted
                        else "movement_anchor_not_internal"
                        if not interior
                        else "movement_anchor_distance_exceeded"
                    ),
                    "geometry": Point(anchor),
                }
            )
            if accepted:
                split_requests.setdefault(index, []).append(
                    {
                        "measure": measure,
                        "start_keys": {key} if role == "target_start" else set(),
                        "end_keys": {key} if role == "source_end" else set(),
                        "surface_routing_peer": surface_routing_peer,
                    }
                )

    output_rows: list[dict[str, object]] = []
    split_parent_count = 0
    for index, carrier in carriers.iterrows():
        requests = _merge_requests(split_requests.get(int(index), []))
        if not requests:
            row = carrier.to_dict()
            row["inherit_source_snodeid"] = _inherits_source_node(
                row.get("inherit_source_snodeid")
            )
            row["inherit_source_enodeid"] = _inherits_source_node(
                row.get("inherit_source_enodeid")
            )
            output_rows.append(row)
            continue
        split_parent_count += 1
        output_rows.extend(
            _split_carrier(carrier.to_dict(), requests, patch_geometry)
        )
    result = gpd.GeoDataFrame(output_rows, geometry="geometry", crs=carriers.crs)
    audit = (
        gpd.GeoDataFrame(audit_rows, geometry="geometry", crs=carriers.crs)
        if audit_rows
        else _empty_audit(carriers.crs)
    )
    return MovementSplitResult(
        result,
        audit,
        {
            "split_parent_count": int(split_parent_count),
            "split_part_count": int(len(result) - len(carriers) + split_parent_count),
            "accepted_anchor_count": int(audit["split_decision"].eq("accepted").sum()) if not audit.empty else 0,
            "rejected_anchor_count": int(audit["split_decision"].eq("rejected").sum()) if not audit.empty else 0,
        },
    )


def _select_movement_carrier(
    patch_key: str,
    endpoint_name: str,
    carriers: gpd.GeoDataFrame,
    patch_geometry: dict[str, LineString],
    carrier_by_patch: dict[str, list[int]],
    carriers_by_segment: dict[str, list[int]],
    assignment_segments: dict[str, set[str]],
) -> int | None:
    patch_line = patch_geometry.get(patch_key)
    if patch_line is None or patch_line.is_empty or patch_line.length <= 1e-9:
        return None
    candidates = set(carrier_by_patch.get(patch_key, ()))
    if not candidates:
        for segment_id in assignment_segments.get(patch_key, set()):
            candidates.update(carriers_by_segment.get(segment_id, ()))
    if not candidates:
        return None
    anchor = patch_line.interpolate(
        1.0 if endpoint_name == "end" else 0.0,
        normalized=True,
    )
    patch_vector = _line_tangent(
        patch_line,
        float(patch_line.project(anchor)),
    )
    scored: list[tuple[float, float, float, str, int]] = []
    for index in sorted(candidates):
        carrier = carriers.loc[index]
        geometry = carrier.geometry
        if geometry is None or geometry.is_empty or geometry.length <= 1e-9:
            continue
        carrier_measure = float(geometry.project(anchor))
        angle = _vector_angle_deg(
            patch_vector,
            _line_tangent(geometry, carrier_measure),
        )
        scored.append(
            (
                angle,
                float(anchor.distance(geometry)),
                float(patch_line.distance(geometry)),
                str(carrier.get("carrier_id", "")),
                int(index),
            )
        )
    if not scored:
        return None
    selected = min(scored)
    if selected[0] > 75.0 + 1e-9:
        return None
    return selected[-1]


def _line_tangent(
    geometry: LineString,
    measure: float,
) -> tuple[float, float]:
    epsilon = min(2.0, max(0.1, float(geometry.length) * 0.10))
    start = geometry.interpolate(max(0.0, measure - epsilon))
    end = geometry.interpolate(min(float(geometry.length), measure + epsilon))
    dx = float(end.x - start.x)
    dy = float(end.y - start.y)
    magnitude = math.hypot(dx, dy)
    if magnitude <= 1e-9:
        first = geometry.coords[0]
        last = geometry.coords[-1]
        dx = float(last[0] - first[0])
        dy = float(last[1] - first[1])
        magnitude = max(math.hypot(dx, dy), 1e-9)
    return dx / magnitude, dy / magnitude


def _vector_angle_deg(
    first: tuple[float, float],
    second: tuple[float, float],
) -> float:
    dot = max(-1.0, min(1.0, first[0] * second[0] + first[1] * second[1]))
    return math.degrees(math.acos(dot))


def split_carriers_at_segment_accesses(
    movement_result: MovementSplitResult,
    segment_accesses: gpd.GeoDataFrame,
    junction_units: gpd.GeoDataFrame,
    geometry_sources: gpd.GeoDataFrame,
    *,
    run_id: str,
    maximum_access_distance_m: float,
    endpoint_trim_segment_ids: set[str] | None = None,
    endpoint_surface_buffer_m: float = 0.0,
) -> MovementSplitResult:
    """Split Segment Roads at physical THROUGH JunctionUnit surfaces."""
    carriers = movement_result.carriers
    if carriers.empty or junction_units.empty:
        return movement_result
    surfaces = _junction_surfaces(junction_units)
    surface_sources = {
        str(group_id): str(
            getattr(group.iloc[0], "junction_source", "")
        )
        for group_id, group in junction_units.groupby("junction_group_id")
    }
    patch_geometry = {
        str(row.patch_road_key): row.geometry
        for row in geometry_sources.drop_duplicates("patch_road_key").itertuples()
    }
    carriers, endpoint_audit, endpoint_trimmed_count = (
        _trim_target_main_carriers_to_endpoint_surfaces(
            carriers,
            segment_accesses[
                segment_accesses["access_type"].astype(str).eq("ENDPOINT")
            ],
            surfaces,
            patch_geometry,
            run_id=run_id,
            allowed_segment_ids=endpoint_trim_segment_ids or set(),
            endpoint_surface_buffer_m=endpoint_surface_buffer_m,
        )
    )
    through = segment_accesses[
        segment_accesses["access_type"].astype(str).eq("THROUGH")
    ].copy()
    if through.empty:
        return _with_endpoint_trim_result(
            movement_result,
            carriers,
            endpoint_audit,
            endpoint_trimmed_count,
        )
    accesses_by_segment = {
        str(segment_id): group.copy()
        for segment_id, group in through.groupby("segment_id")
    }
    output_rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    split_parent_count = 0
    accepted_count = 0
    for _, carrier in carriers.iterrows():
        if str(carrier.get("realization", "")) != "built":
            output_rows.append(carrier.to_dict())
            continue
        accesses = accesses_by_segment.get(str(carrier.get("segment_id", "")))
        if accesses is None or accesses.empty:
            output_rows.append(carrier.to_dict())
            continue
        requests: list[dict[str, object]] = []
        for access in accesses.itertuples(index=False):
            surface = surfaces.get(str(access.junction_group_id))
            if surface is None or surface.is_empty:
                continue
            target_surface = interior_surface_target(
                surface,
                inset_m=endpoint_surface_buffer_m,
            )
            intersection = carrier.geometry.intersection(target_surface)
            if not intersection.is_empty:
                anchor = carrier.geometry.interpolate(
                    carrier.geometry.project(intersection.centroid)
                )
                distance = 0.0
            else:
                anchor, _ = nearest_points(
                    carrier.geometry,
                    target_surface,
                )
                distance = float(anchor.distance(target_surface))
            measure = float(carrier.geometry.project(anchor))
            terminal_distance = min(
                measure,
                float(carrier.geometry.length) - measure,
            )
            retained_lineage_anchor = (
                surface_sources.get(str(access.junction_group_id))
                == "swsd_retained"
                and distance <= maximum_access_distance_m + 1e-9
            )
            physical_anchor = (
                not intersection.is_empty
                or retained_lineage_anchor
            )
            terminal_equivalent = (
                physical_anchor
                and
                terminal_distance <= _MIN_THROUGH_SPLIT_PART_LENGTH_M
            )
            interior = (
                _MIN_THROUGH_SPLIT_PART_LENGTH_M
                < measure
                < float(carrier.geometry.length) - _MIN_THROUGH_SPLIT_PART_LENGTH_M
            )
            accepted = interior and physical_anchor
            decision = (
                "accepted"
                if accepted
                else "not_required"
                if terminal_equivalent
                else "rejected"
            )
            audit_rows.append(
                {
                    "run_id": run_id,
                    "source_patch_road_key": "",
                    "target_patch_road_key": "",
                    "carrier_id": str(carrier.carrier_id),
                    "anchor_role": "segment_through_access",
                    "access_id": str(access.access_id),
                    "junction_group_id": str(access.junction_group_id),
                    "split_measure_m": measure,
                    "anchor_distance_m": distance,
                    "split_decision": decision,
                    "reason_codes": (
                        "segment_through_retained_lineage_anchor"
                        if accepted and retained_lineage_anchor
                        else "segment_through_junction_surface_anchor"
                        if accepted
                        else "segment_through_terminal_equivalent"
                        if terminal_equivalent
                        else "segment_through_surface_not_intersected"
                        if intersection.is_empty
                        else "segment_through_anchor_not_internal"
                        if not interior
                        else "segment_through_surface_anchor_rejected"
                    ),
                    "geometry": Point(anchor),
                }
            )
            if accepted:
                accepted_count += 1
                requests.append(
                    {
                        "measure": measure,
                        "start_keys": set(),
                        "end_keys": set(),
                        "access_ids": {str(access.access_id)},
                        "junction_group_ids": {
                            str(access.junction_group_id)
                        },
                    }
                )
        requests = _merge_requests(requests)
        if not requests:
            output_rows.append(carrier.to_dict())
            continue
        split_parent_count += 1
        output_rows.extend(
            _split_carrier(carrier.to_dict(), requests, patch_geometry)
        )
    result = gpd.GeoDataFrame(output_rows, geometry="geometry", crs=carriers.crs)
    through_audit = (
        gpd.GeoDataFrame(audit_rows, geometry="geometry", crs=carriers.crs)
        if audit_rows
        else _empty_audit(carriers.crs)
    )
    audit = gpd.GeoDataFrame(
        pd.concat(
            [movement_result.audit, endpoint_audit, through_audit],
            ignore_index=True,
            sort=False,
        ),
        geometry="geometry",
        crs=carriers.crs,
    )
    summary = dict(movement_result.summary)
    summary.update(
        {
            "endpoint_trimmed_carrier_count": int(endpoint_trimmed_count),
            "through_split_parent_count": int(split_parent_count),
            "through_split_part_count": int(
                len(result) - len(carriers) + split_parent_count
            ),
            "through_accepted_anchor_count": int(accepted_count),
            "through_terminal_equivalent_count": int(
                through_audit["split_decision"].eq("not_required").sum()
            ),
            "through_rejected_anchor_count": int(
                through_audit["split_decision"].eq("rejected").sum()
            ),
        }
    )
    return MovementSplitResult(result, audit, summary)


def _junction_surfaces(
    junction_units: gpd.GeoDataFrame,
) -> dict[str, object]:
    key = id(junction_units)
    cached = _JUNCTION_SURFACE_CACHE.get(key)
    if (
        cached is not None
        and cached[0]() is junction_units
        and cached[1] == id(junction_units._mgr)
    ):
        return cached[2]
    result = {
        str(group_id): unary_union(
            [
                endpoint_surface_geometry(row)
                for row in group.itertuples(index=False)
            ]
        )
        for group_id, group in junction_units.groupby("junction_group_id")
    }

    def remove(_: weakref.ReferenceType[gpd.GeoDataFrame]) -> None:
        current = _JUNCTION_SURFACE_CACHE.get(key)
        if current is not None and current[0]() is None:
            _JUNCTION_SURFACE_CACHE.pop(key, None)

    _JUNCTION_SURFACE_CACHE[key] = (
        weakref.ref(junction_units, remove),
        id(junction_units._mgr),
        result,
    )
    return result


def _trim_target_main_carriers_to_endpoint_surfaces(
    carriers: gpd.GeoDataFrame,
    endpoint_accesses: gpd.GeoDataFrame,
    surfaces: dict[str, object],
    patch_geometry: dict[str, object],
    *,
    run_id: str,
    allowed_segment_ids: set[str],
    endpoint_surface_buffer_m: float,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame, int]:
    accesses_by_segment = {
        str(segment_id): group.drop_duplicates("junction_group_id").copy()
        for segment_id, group in endpoint_accesses.groupby("segment_id")
    } if not endpoint_accesses.empty else {}
    rows: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    trimmed_count = 0
    suppressed_indexes = _endpoint_surface_tail_indexes(
        carriers,
        accesses_by_segment,
        surfaces,
        allowed_segment_ids=allowed_segment_ids,
        endpoint_surface_buffer_m=endpoint_surface_buffer_m,
    )
    for index, carrier in carriers.iterrows():
        accesses = accesses_by_segment.get(str(carrier.get("segment_id", "")))
        if index in suppressed_indexes:
            access_ids = (
                sorted(accesses["access_id"].astype(str))
                if accesses is not None
                else []
            )
            group_ids = (
                sorted(accesses["junction_group_id"].astype(str))
                if accesses is not None
                else []
            )
            audit_rows.append(
                {
                    "run_id": run_id,
                    "source_patch_road_key": "",
                    "target_patch_road_key": "",
                    "carrier_id": str(carrier.carrier_id),
                    "anchor_role": "segment_endpoint_surface_tail_suppression",
                    "access_id": ",".join(access_ids),
                    "junction_group_id": ",".join(group_ids),
                    "split_measure_m": float(carrier.geometry.length),
                    "anchor_distance_m": 0.0,
                    "split_decision": "accepted",
                    "reason_codes": (
                        "segment_main_tail_outside_endpoint_corridor_suppressed"
                    ),
                    "geometry": carrier.geometry.interpolate(
                        0.5,
                        normalized=True,
                    ),
                }
            )
            continue
        if (
            str(carrier.get("segment_id", "")) not in allowed_segment_ids
            or
            str(carrier.get("realization", "")) != "built"
            or str(carrier.get("target_class", "")) not in {"core_trunk", "advance_right"}
            or not str(carrier.get("carrier_role", "")).startswith("main_")
            or accesses is None
            or len(accesses) != 2
        ):
            rows.append(carrier.to_dict())
            continue
        geometry = carrier.geometry
        ranges: list[tuple[float, float, str, str]] = []
        for access in accesses.itertuples(index=False):
            surface = surfaces.get(str(access.junction_group_id))
            protected_surface = (
                surface.buffer(endpoint_surface_buffer_m)
                if surface is not None and endpoint_surface_buffer_m > 0.0
                else surface
            )
            measures = _intersection_measure_range(
                geometry,
                protected_surface,
            )
            if measures is None:
                ranges = []
                break
            ranges.append(
                (
                    measures[0],
                    measures[1],
                    str(access.access_id),
                    str(access.junction_group_id),
                )
            )
        if len(ranges) != 2:
            rows.append(carrier.to_dict())
            continue
        ranges.sort(key=lambda value: (value[0] + value[1]) / 2.0)
        start_m = ranges[0][1]
        end_m = ranges[1][0]
        if end_m - start_m <= _MIN_THROUGH_SPLIT_PART_LENGTH_M:
            rows.append(carrier.to_dict())
            continue
        requests = []
        for measure, access in zip(
            (start_m, end_m),
            (ranges[0], ranges[1]),
            strict=True,
        ):
            if 1e-6 < measure < float(geometry.length) - 1e-6:
                requests.append(
                    {
                        "measure": measure,
                        "start_keys": set(),
                        "end_keys": set(),
                        "access_ids": {access[2]},
                        "junction_group_ids": {access[3]},
                    }
                )
        parts = _split_carrier(carrier.to_dict(), requests, patch_geometry)
        midpoint = geometry.interpolate((start_m + end_m) / 2.0)
        trimmed = min(parts, key=lambda row: float(row["geometry"].distance(midpoint)))
        trimmed["carrier_id"] = f"{carrier.carrier_id}:endpoint-trim"
        trimmed["road_part_index"] = 0
        trimmed["road_part_count"] = 1
        trimmed["assembly_state"] = (
            f"{carrier.get('assembly_state', '')}+endpoint_surface_trim"
        )
        rows.append(trimmed)
        trimmed_count += 1
        audit_rows.append(
            {
                "run_id": run_id,
                "source_patch_road_key": "",
                "target_patch_road_key": "",
                "carrier_id": str(carrier.carrier_id),
                "anchor_role": "segment_endpoint_surface_trim",
                "access_id": ",".join(value[2] for value in ranges),
                "junction_group_id": ",".join(value[3] for value in ranges),
                "split_measure_m": end_m - start_m,
                "anchor_distance_m": 0.0,
                "split_decision": "accepted",
                "reason_codes": "segment_main_trimmed_between_endpoint_surfaces",
                "geometry": midpoint,
            }
        )
    frame = gpd.GeoDataFrame(rows, geometry="geometry", crs=carriers.crs)
    audit = (
        gpd.GeoDataFrame(audit_rows, geometry="geometry", crs=carriers.crs)
        if audit_rows
        else _empty_audit(carriers.crs)
    )
    return frame, audit, trimmed_count


def _endpoint_surface_tail_indexes(
    carriers: gpd.GeoDataFrame,
    accesses_by_segment: dict[str, gpd.GeoDataFrame],
    surfaces: dict[str, object],
    *,
    allowed_segment_ids: set[str],
    endpoint_surface_buffer_m: float,
) -> set[object]:
    candidates: dict[tuple[str, str, str], list[object]] = {}
    for index, carrier in carriers.iterrows():
        segment_id = str(carrier.get("segment_id", ""))
        movement_parent = carrier.get("movement_parent_carrier_id", "")
        movement_parent = (
            ""
            if movement_parent is None or pd.isna(movement_parent)
            else str(movement_parent)
        )
        if (
            segment_id not in allowed_segment_ids
            or not movement_parent
            or str(carrier.get("realization", "")) != "built"
            or str(carrier.get("target_class", ""))
            not in {"core_trunk", "advance_right"}
            or not str(carrier.get("carrier_role", "")).startswith("main_")
        ):
            continue
        candidates.setdefault(
            (
                segment_id,
                str(carrier.get("carrier_role", "")),
                movement_parent,
            ),
            [],
        ).append(index)

    suppressed: set[object] = set()
    for (segment_id, _, _), indexes in candidates.items():
        if len(indexes) < 2:
            continue
        accesses = accesses_by_segment.get(segment_id)
        if accesses is None or len(accesses) != 2:
            continue
        terminal_surfaces = []
        for group_id in accesses["junction_group_id"]:
            surface = surfaces.get(str(group_id))
            terminal_surfaces.append(
                surface.buffer(endpoint_surface_buffer_m)
                if surface is not None and endpoint_surface_buffer_m > 0.0
                else surface
            )
        if any(
            surface is None or surface.is_empty
            for surface in terminal_surfaces
        ):
            continue
        spanning = [
            index
            for index in indexes
            if all(
                _intersection_measure_range(
                    carriers.loc[index].geometry,
                    surface,
                )
                is not None
                for surface in terminal_surfaces
            )
        ]
        if len(spanning) == 1:
            suppressed.update(set(indexes).difference(spanning))
    return suppressed


def _intersection_measure_range(
    geometry: LineString,
    surface: object | None,
) -> tuple[float, float] | None:
    if surface is None or surface.is_empty:
        return None
    intersection = geometry.intersection(surface)
    points = _geometry_vertices(intersection)
    if not points:
        return None
    measures = [float(geometry.project(point)) for point in points]
    return min(measures), max(measures)


def _geometry_vertices(geometry: object) -> list[Point]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Point):
        return [geometry]
    if isinstance(geometry, LineString):
        return [Point(coord) for coord in geometry.coords]
    return [
        point
        for part in getattr(geometry, "geoms", ())
        for point in _geometry_vertices(part)
    ]


def _with_endpoint_trim_result(
    movement_result: MovementSplitResult,
    carriers: gpd.GeoDataFrame,
    endpoint_audit: gpd.GeoDataFrame,
    endpoint_trimmed_count: int,
) -> MovementSplitResult:
    audit = gpd.GeoDataFrame(
        pd.concat(
            [movement_result.audit, endpoint_audit],
            ignore_index=True,
            sort=False,
        ),
        geometry="geometry",
        crs=carriers.crs,
    )
    summary = dict(movement_result.summary)
    summary["endpoint_trimmed_carrier_count"] = int(endpoint_trimmed_count)
    summary.update(
        {
            "through_split_parent_count": 0,
            "through_split_part_count": 0,
            "through_accepted_anchor_count": 0,
            "through_terminal_equivalent_count": 0,
            "through_rejected_anchor_count": 0,
        }
    )
    return MovementSplitResult(carriers, audit, summary)


def _split_carrier(
    carrier: dict[str, object],
    requests: list[dict[str, object]],
    patch_geometry: dict[str, object],
    patch_lane_ids: dict[str, tuple[str, ...]] | None = None,
    *,
    assign_keys_by_overlap: bool = False,
) -> list[dict[str, object]]:
    geometry = carrier["geometry"]
    boundaries = [0.0, *[float(row["measure"]) for row in requests], float(geometry.length)]
    source_keys = _split_keys(carrier.get("source_patch_road_keys", ""))
    key_ranges = {
        key: _projection_measure_range(geometry, patch_geometry[key])
        for key in source_keys
        if key in patch_geometry
    }
    key_measures = {
        key: (start + end) / 2.0
        for key, (start, end) in key_ranges.items()
    }
    parent_spans = _load_spans(carrier)
    rows: list[dict[str, object]] = []
    part_count = len(boundaries) - 1
    for part_index, (start_m, end_m) in enumerate(zip(boundaries, boundaries[1:])):
        part = dict(carrier)
        part_geometry = substring(geometry, start_m, end_m)
        if part_geometry.is_empty or part_geometry.length <= 1e-6:
            continue
        if assign_keys_by_overlap:
            part_keys = sorted(
                key
                for key, (key_start, key_end) in key_ranges.items()
                if min(end_m, key_end) - max(start_m, key_start) > 1e-6
            )
        else:
            part_keys = sorted(
                key
                for key, measure in key_measures.items()
                if start_m - 1e-6 <= measure <= end_m + 1e-6
            )
        start_keys = (
            _split_keys(carrier.get("start_patch_road_keys", ""))
            if part_index == 0
            else sorted(requests[part_index - 1]["start_keys"])
        )
        end_keys = (
            _split_keys(carrier.get("end_patch_road_keys", ""))
            if part_index == part_count - 1
            else sorted(requests[part_index]["end_keys"])
        )
        start_access_ids = (
            _split_keys(carrier.get("start_access_ids", ""))
            if part_index == 0
            else sorted(requests[part_index - 1].get("access_ids", set()))
        )
        end_access_ids = (
            _split_keys(carrier.get("end_access_ids", ""))
            if part_index == part_count - 1
            else sorted(requests[part_index].get("access_ids", set()))
        )
        start_junction_groups = (
            _split_keys(carrier.get("start_junction_group_ids", ""))
            if part_index == 0
            else sorted(
                requests[part_index - 1].get(
                    "junction_group_ids", set()
                )
            )
        )
        end_junction_groups = (
            _split_keys(carrier.get("end_junction_group_ids", ""))
            if part_index == part_count - 1
            else sorted(
                requests[part_index].get("junction_group_ids", set())
            )
        )
        part_keys = sorted(set(part_keys).union(start_keys).union(end_keys))
        movement_parent = str(
            carrier.get("movement_parent_carrier_id", "")
            or str(carrier["carrier_id"]).split(":part:", 1)[0]
        )
        part["carrier_id"] = f"{carrier['carrier_id']}:part:{part_index}"
        part["movement_parent_carrier_id"] = movement_parent
        part["road_part_index"] = part_index
        part["road_part_count"] = part_count
        part["patch_road_key"] = part_keys[0] if part_keys else str(carrier.get("patch_road_key", ""))
        part["source_patch_road_keys"] = ",".join(part_keys)
        part["start_patch_road_keys"] = ",".join(start_keys)
        part["end_patch_road_keys"] = ",".join(end_keys)
        part["start_access_ids"] = ",".join(start_access_ids)
        part["end_access_ids"] = ",".join(end_access_ids)
        part["start_junction_group_ids"] = ",".join(
            start_junction_groups
        )
        part["end_junction_group_ids"] = ",".join(
            end_junction_groups
        )
        part["source_patch_ids"] = ",".join(
            sorted({key.split(":", 1)[0] for key in part_keys if ":" in key})
        )
        if patch_lane_ids is not None:
            lane_ids = sorted(
                {
                    lane_id
                    for key in part_keys
                    for lane_id in patch_lane_ids.get(key, ())
                    if lane_id
                }
            )
            part["source_lane_ids"] = ",".join(lane_ids)
            part["center_lane_id"] = ",".join(lane_ids)
        part["inherit_source_snodeid"] = (
            _inherits_source_node(carrier.get("inherit_source_snodeid"))
            and part_index == 0
        )
        part["inherit_source_enodeid"] = (
            _inherits_source_node(carrier.get("inherit_source_enodeid"))
            and part_index == part_count - 1
        )
        part["endpoint_surface_routing_movement_split"] = bool(
            carrier.get(
                "endpoint_surface_routing_movement_split",
                False,
            )
        ) or any(
            bool(request.get("surface_routing_peer", False))
            for request in requests
        )
        part["assembly_state"] = f"{carrier.get('assembly_state', '')}+movement_split"
        part["evidence_spans_json"] = json.dumps(
            _clip_spans(parent_spans, start_m / geometry.length, end_m / geometry.length),
            sort_keys=True,
        )
        part["geometry"] = part_geometry
        rows.append(part)
    return rows


def _projection_measure_range(
    carrier_geometry: LineString,
    source_geometry: LineString,
) -> tuple[float, float]:
    sample_count = max(3, int(source_geometry.length / 5.0) + 2)
    measures = [
        float(
            carrier_geometry.project(
                source_geometry.interpolate(index / (sample_count - 1), normalized=True)
            )
        )
        for index in range(sample_count)
    ]
    return min(measures), max(measures)


def _patch_lane_ids(
    sources: gpd.GeoDataFrame,
) -> dict[str, tuple[str, ...]]:
    if sources.empty or "patch_road_key" not in sources.columns:
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for patch_key, group in sources.groupby(
        sources["patch_road_key"].astype(str),
        sort=False,
    ):
        lane_ids = {
            str(value)
            for column in ("center_lane_id", "lane_id")
            if column in group.columns
            for value in group[column].fillna("").astype(str)
            if value and value.lower() != "nan"
        }
        result[str(patch_key)] = tuple(sorted(lane_ids))
    return result


def _inherits_source_node(value: object) -> bool:
    if value is None or bool(pd.isna(value)):
        return True
    return bool(value)


def _merge_requests(requests: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for request in sorted(requests, key=lambda row: float(row["measure"])):
        if result and abs(float(request["measure"]) - float(result[-1]["measure"])) <= 1.0:
            result[-1]["start_keys"].update(request["start_keys"])
            result[-1]["end_keys"].update(request["end_keys"])
            result[-1]["access_ids"].update(
                request.get("access_ids", set())
            )
            result[-1]["junction_group_ids"].update(
                request.get("junction_group_ids", set())
            )
            result[-1]["surface_routing_peer"] = bool(
                result[-1].get("surface_routing_peer", False)
            ) or bool(request.get("surface_routing_peer", False))
        else:
            result.append(
                {
                    "measure": float(request["measure"]),
                    "start_keys": set(request["start_keys"]),
                    "end_keys": set(request["end_keys"]),
                    "access_ids": set(
                        request.get("access_ids", set())
                    ),
                    "junction_group_ids": set(
                        request.get("junction_group_ids", set())
                    ),
                    "surface_routing_peer": bool(
                        request.get("surface_routing_peer", False)
                    ),
                }
            )
    return result


def _load_spans(carrier: dict[str, object]) -> list[dict[str, object]]:
    raw = str(carrier.get("evidence_spans_json", "") or "")
    if raw:
        try:
            result = json.loads(raw)
            if result:
                return result
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return [
        {
            "geometry_source": str(carrier.get("geometry_source", "hp_observed")),
            "source_object_ids": str(carrier.get("source_patch_road_keys", "")),
            "start_fraction": 0.0,
            "end_fraction": 1.0,
        }
    ]


def _clip_spans(
    spans: list[dict[str, object]],
    part_start: float,
    part_end: float,
) -> list[dict[str, object]]:
    width = part_end - part_start
    result: list[dict[str, object]] = []
    for span in spans:
        start = max(part_start, float(span["start_fraction"]))
        end = min(part_end, float(span["end_fraction"]))
        if end - start <= 1e-9:
            continue
        result.append(
            {
                "geometry_source": str(span["geometry_source"]),
                "source_object_ids": str(span["source_object_ids"]),
                "start_fraction": (start - part_start) / width,
                "end_fraction": (end - part_start) / width,
            }
        )
    return result


def _split_keys(value: object) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _empty_audit(crs: object) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "run_id": pd.Series(dtype="object"),
            "source_patch_road_key": pd.Series(dtype="object"),
            "target_patch_road_key": pd.Series(dtype="object"),
            "carrier_id": pd.Series(dtype="object"),
            "anchor_role": pd.Series(dtype="object"),
            "split_measure_m": pd.Series(dtype="float64"),
            "anchor_distance_m": pd.Series(dtype="float64"),
            "split_decision": pd.Series(dtype="object"),
            "reason_codes": pd.Series(dtype="object"),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


__all__ = ["MovementSplitResult", "split_carriers_at_movement_anchors"]
