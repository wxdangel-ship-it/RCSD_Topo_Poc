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
from .geometry import tangent_vector


@dataclass(frozen=True)
class DirectionalGeometryResult:
    road_candidates: gpd.GeoDataFrame
    geometry_segments: gpd.GeoDataFrame
    fit_stations: gpd.GeoDataFrame
    summary: dict[str, Any]


def instantiate_directional_geometries(
    directional_units: gpd.GeoDataFrame,
    lane_segments: gpd.GeoDataFrame,
    anchors: gpd.GeoDataFrame,
    support_intervals: gpd.GeoDataFrame,
    *,
    config: DirectionalRoadV2Config,
) -> DirectionalGeometryResult:
    segments_by_child = {
        str(child_id): frame.reset_index(drop=True)
        for child_id, frame in lane_segments[
            lane_segments["hard_geometry_eligible"]
            & (lane_segments["directional_road_id"] != "")
        ].groupby("directional_road_id")
    }
    anchors_by_child = {
        str(row.directional_road_id): row
        for row in anchors.itertuples(index=False)
    }
    intervals_by_child = {
        str(child_id): frame.sort_values("interval_index").reset_index(drop=True)
        for child_id, frame in support_intervals.groupby("directional_road_id")
    }

    road_rows: list[dict[str, Any]] = []
    station_rows: list[dict[str, Any]] = []
    geometry_segment_rows: list[dict[str, Any]] = []
    for unit in directional_units.itertuples(index=False):
        child_id = str(unit.directional_road_id)
        hard_segments = segments_by_child.get(child_id)
        anchor = anchors_by_child.get(child_id)
        intervals = intervals_by_child[child_id]
        geometry, stations, fit_state = _fit_one_directional_road(
            unit.geometry,
            hard_segments,
            anchor,
            intervals,
            travel_side=str(unit.travel_side),
            support_state=str(unit.directional_support_state),
            child_id=child_id,
            config=config,
        )
        station_rows.extend(stations)
        base = {
            key: value
            for key, value in unit._asdict().items()
            if key != "geometry" and not key.startswith("_")
        }
        reference_start = Point(unit.geometry.coords[-1 if str(unit.travel_side) == "reverse" else 0])
        reference_end = Point(unit.geometry.coords[0 if str(unit.travel_side) == "reverse" else -1])
        start_parent_portal_delta = Point(geometry.coords[0]).distance(reference_start)
        end_parent_portal_delta = Point(geometry.coords[-1]).distance(reference_end)
        applied = np.asarray([float(row["applied_lateral_shift_m"]) for row in stations])
        adjacent = np.abs(np.diff(applied)) if len(applied) > 1 else np.asarray([0.0])
        hp_station_mask = np.asarray(
            [
                str(row["station_geometry_source"])
                in {
                    "directional_anchor_supported",
                    "directional_lane_group_center_supported",
                }
                for row in stations
            ],
            dtype=bool,
        )
        hp_pair_mask = (
            hp_station_mask[:-1] & hp_station_mask[1:]
            if len(hp_station_mask) > 1
            else np.asarray([], dtype=bool)
        )
        station_offsets = np.asarray(
            [float(row["parent_station_offset_m"]) for row in stations],
            dtype=float,
        )
        hp_distance = float(
            np.diff(station_offsets)[hp_pair_mask].sum()
            if len(station_offsets) > 1
            else 0.0
        )
        hp_total_variation = float(
            adjacent[hp_pair_mask].sum() if len(hp_pair_mask) else 0.0
        )
        hp_oscillation, hp_oscillation_distance = _hp_oscillation(stations, config)
        length = max(float(unit.geometry.length), 1e-8)
        total_variation = float(adjacent.sum())
        length_ratio = float(geometry.length) / length
        envelope_violations = sum(bool(row["envelope_violation"]) for row in stations)
        base.update(
            {
                "run_id": config.run_id,
                "source_object_type": "SWSDRoad+DirectionalLaneGroup",
                "source_object_ids": str(unit.source_lane_ids) or str(unit.parent_swsd_unit_id),
                "decision": "published_directional_v2_candidate",
                "reason_codes": str(unit.support_reason),
                "evidence_state": "directional_road_v2",
                "input_manifest_ref": "p04_input_manifest.json",
                "support_state": str(unit.directional_support_state),
                "geometry_source": _geometry_source(unit, fit_state),
                "geometry_fit_state": fit_state,
                "anchor_kind": "" if pd.isna(unit.anchor_kind) else str(unit.anchor_kind),
                "anchor_source_id": ""
                if pd.isna(unit.anchor_source_id)
                else str(unit.anchor_source_id),
                "anchor_switch_count": 0,
                "swsd_reference_length_m": float(unit.geometry.length),
                "candidate_length_m": float(geometry.length),
                "candidate_length_ratio": length_ratio,
                "max_adjacent_lateral_shift_m": float(adjacent.max(initial=0.0)),
                "lateral_total_variation_m": total_variation,
                "lateral_total_variation_per_100m": total_variation / length * 100.0,
                "hp_lateral_total_variation_m": hp_total_variation,
                "hp_lateral_total_variation_per_100m": hp_total_variation
                / max(hp_distance, 1e-8)
                * 100.0,
                "hp_lateral_oscillation_m": hp_oscillation,
                "hp_lateral_oscillation_per_100m": hp_oscillation
                / max(hp_oscillation_distance, 1e-8)
                * 100.0,
                "median_lateral_shift_m": float(np.median(np.abs(applied))) if len(applied) else 0.0,
                "max_lateral_shift_m": float(np.abs(applied).max(initial=0.0)),
                "lane_group_envelope_violation_count": int(envelope_violations),
                "start_parent_swsd_portal_delta_m": float(start_parent_portal_delta),
                "end_parent_swsd_portal_delta_m": float(end_parent_portal_delta),
                "geometry_valid": bool(geometry.is_valid),
                "geometry_simple": bool(geometry.is_simple),
                "geometry": geometry,
            }
        )
        road_rows.append(base)
        geometry_segment_rows.extend(
            _geometry_segments(
                geometry,
                intervals,
                stations,
                child_id=child_id,
                parent_id=str(unit.parent_swsd_unit_id),
                travel_side=str(unit.travel_side),
                run_id=config.run_id,
                fit_state=fit_state,
            )
        )
    candidates = gpd.GeoDataFrame(road_rows, geometry="geometry", crs=directional_units.crs)
    geometry_segments = gpd.GeoDataFrame(
        geometry_segment_rows, geometry="geometry", crs=directional_units.crs
    )
    fit_stations = gpd.GeoDataFrame(
        station_rows, geometry="geometry", crs=directional_units.crs
    )
    return DirectionalGeometryResult(
        road_candidates=candidates,
        geometry_segments=geometry_segments,
        fit_stations=fit_stations,
        summary=_summary(candidates, fit_stations, config=config),
    )


def _fit_one_directional_road(
    reference: Any,
    lane_segments: gpd.GeoDataFrame | None,
    anchor: Any | None,
    intervals: gpd.GeoDataFrame,
    *,
    travel_side: str,
    support_state: str,
    child_id: str,
    config: DirectionalRoadV2Config,
) -> tuple[LineString, list[dict[str, Any]], str]:
    offsets = _station_offsets(reference, intervals, config.fit_station_spacing_m)
    support_ranges = [
        (float(row.parent_start_m), float(row.parent_end_m))
        for row in intervals.itertuples(index=False)
        if str(row.interval_state) == "hp_supported"
    ]
    envelope_rows = [
        _lane_envelope(reference, offset, lane_segments, config.anchor_max_distance_m)
        for offset in offsets
    ]
    support_mask = np.asarray(
        [_contains(float(offset), support_ranges) for offset in offsets],
        dtype=bool,
    )
    anchor_observations: list[float | None] = [None] * len(offsets)
    raw_sources = ["swsd_gap_retained"] * len(offsets)
    if support_state == "sd_only" or anchor is None:
        raw = np.zeros(len(offsets), dtype=float)
        fit_state = (
            "pure_swsd_parent_retained"
            if travel_side == "sd_parent"
            else "directional_sd_only_parent_centerline"
        )
    else:
        raw = np.zeros(len(offsets), dtype=float)
        anchor_observation_count = 0
        local_center_count = 0
        for index, offset in enumerate(offsets):
            if not support_mask[index]:
                continue
            value = _anchor_offset_at_station(
                reference,
                float(offset),
                anchor.geometry,
                config.anchor_max_distance_m,
                config.fit_station_spacing_m,
            )
            envelope = envelope_rows[index]
            if (
                value is not None
                and envelope is not None
                and not (
                    envelope[0] - config.lane_group_envelope_tolerance_m
                    <= value
                    <= envelope[1] + config.lane_group_envelope_tolerance_m
                )
            ):
                value = None
            if value is not None:
                anchor_observations[index] = value
                raw[index] = value
                raw_sources[index] = "stable_anchor_observation"
                anchor_observation_count += 1
            elif envelope is not None:
                raw[index] = (float(envelope[0]) + float(envelope[1])) / 2.0
                raw_sources[index] = "local_lane_group_center"
                local_center_count += 1
            else:
                raw_sources[index] = "supported_without_local_geometry"
        if anchor_observation_count and local_center_count:
            fit_state = "stable_anchor_with_local_group_fallback"
        elif anchor_observation_count:
            fit_state = (
                "stable_boundary_centerline"
                if str(anchor.anchor_kind) == "lane_boundary"
                else "stable_lane_centerline"
            )
        elif local_center_count:
            fit_state = "lane_group_center_fallback_anchor_unavailable"
        else:
            fit_state = "swsd_retained_supported_geometry_missing"
    effective_envelopes = [
        _effective_envelope(
            envelope,
            float(raw[index]),
            anchor_observations[index],
            tolerance=config.lane_group_envelope_tolerance_m,
        )
        for index, envelope in enumerate(envelope_rows)
    ]
    applied = _smooth_and_constrain(
        raw,
        offsets,
        effective_envelopes,
        fixed_zero_mask=~support_mask,
        config=config,
    )
    coordinates = [
        _offset_coordinate(reference, float(station), float(shift))
        for station, shift in zip(offsets, applied, strict=True)
    ]
    coordinates = _dedupe_coordinates(coordinates)
    if len(coordinates) < 2:
        coordinates = [tuple(reference.coords[0][:2]), tuple(reference.coords[-1][:2])]
    if travel_side == "reverse":
        coordinates.reverse()
    geometry = LineString(coordinates)
    if not geometry.is_simple:
        simplified = geometry.simplify(
            config.non_simple_simplify_tolerance_m,
            preserve_topology=True,
        )
        if simplified.geom_type == "LineString" and simplified.is_simple:
            geometry = simplified
            fit_state += ":non_simple_simplified"
    station_rows = []
    for index, (station, raw_shift, applied_shift, envelope) in enumerate(
        zip(offsets, raw, applied, envelope_rows, strict=True)
    ):
        effective_envelope = effective_envelopes[index]
        if not support_mask[index]:
            effective_envelope = None
        transition_from_swsd = bool(
            abs(float(applied_shift) - float(raw_shift))
            > config.lane_group_envelope_tolerance_m
            or
            effective_envelope is not None
            and (
                applied_shift
                < effective_envelope[0] - config.lane_group_envelope_tolerance_m
                or applied_shift
                > effective_envelope[1] + config.lane_group_envelope_tolerance_m
            )
        )
        if transition_from_swsd:
            effective_envelope = None
        lower = None if envelope is None else float(envelope[0])
        upper = None if envelope is None else float(envelope[1])
        violation = bool(
            effective_envelope is not None
            and (
                applied_shift
                < effective_envelope[0] - config.lane_group_envelope_tolerance_m
                or applied_shift
                > effective_envelope[1] + config.lane_group_envelope_tolerance_m
            )
        )
        point = Point(_offset_coordinate(reference, float(station), float(applied_shift)))
        station_rows.append(
            {
                "run_id": config.run_id,
                "directional_road_id": child_id,
                "parent_station_index": index,
                "parent_station_offset_m": float(station),
                "parent_station_fraction": float(station) / max(float(reference.length), 1e-8),
                "travel_station_fraction": 1.0 - float(station) / max(float(reference.length), 1e-8)
                if travel_side == "reverse"
                else float(station) / max(float(reference.length), 1e-8),
                "support_at_station": bool(support_mask[index]),
                "anchor_kind": "" if anchor is None else str(anchor.anchor_kind),
                "anchor_source_id": "" if anchor is None else str(anchor.anchor_source_id),
                "anchor_observed_at_station": anchor_observations[index] is not None,
                "raw_fit_source": raw_sources[index],
                "raw_lateral_shift_m": float(raw_shift),
                "applied_lateral_shift_m": float(applied_shift),
                "lane_group_min_offset_m": lower,
                "lane_group_max_offset_m": upper,
                "envelope_gate_applicable": effective_envelope is not None,
                "envelope_violation": violation,
                "station_geometry_source": _station_geometry_source(
                    support_state=support_state,
                    support_at_station=bool(support_mask[index]),
                    raw_source=raw_sources[index],
                    raw_shift=float(raw_shift),
                    applied_shift=float(applied_shift),
                    transition_from_swsd=transition_from_swsd,
                ),
                "geometry": point,
            }
        )
    return geometry, station_rows, fit_state


def _lane_envelope(
    reference: Any,
    station_offset: float,
    lane_segments: gpd.GeoDataFrame | None,
    max_distance_m: float,
) -> tuple[float, float] | None:
    if lane_segments is None or lane_segments.empty:
        return None
    selected = lane_segments[
        lane_segments["road_start_m"].le(station_offset + 1e-6)
        & lane_segments["road_end_m"].ge(station_offset - 1e-6)
    ]
    reference_point = reference.interpolate(station_offset)
    values = []
    for row in selected.itertuples(index=False):
        nearest = row.geometry.interpolate(row.geometry.project(reference_point))
        if reference_point.distance(nearest) <= max_distance_m:
            values.append(_signed_offset(reference, station_offset, nearest))
    if not values:
        return None
    return min(values), max(values)


def _anchor_offset_at_station(
    reference: Any,
    station_offset: float,
    geometry: Any,
    max_distance_m: float,
    station_spacing_m: float,
) -> float | None:
    if geometry is None or geometry.is_empty:
        return None
    reference_point = reference.interpolate(station_offset)
    lines = list(geometry.geoms) if hasattr(geometry, "geoms") else [geometry]
    choices: list[tuple[float, Any]] = []
    for line in lines:
        if line is None or line.is_empty or not hasattr(line, "project"):
            continue
        nearest = line.interpolate(line.project(reference_point))
        distance = float(reference_point.distance(nearest))
        projected = float(reference.project(nearest))
        if distance <= max_distance_m and abs(projected - station_offset) <= max(2.0, station_spacing_m * 1.5):
            choices.append((distance, nearest))
    if not choices:
        return None
    _, nearest = min(choices, key=lambda item: item[0])
    return _signed_offset(reference, station_offset, nearest)


def _effective_envelope(
    envelope: tuple[float, float] | None,
    raw_shift: float,
    anchor_observation: float | None,
    *,
    tolerance: float,
) -> tuple[float, float] | None:
    if envelope is None:
        return None
    lower, upper = envelope
    if anchor_observation is not None:
        return envelope
    if lower - tolerance <= raw_shift <= upper + tolerance:
        return envelope
    return None


def _smooth_and_constrain(
    raw: np.ndarray,
    stations: list[float],
    envelopes: list[tuple[float, float] | None],
    *,
    fixed_zero_mask: np.ndarray,
    config: DirectionalRoadV2Config,
) -> np.ndarray:
    values = np.asarray(raw, dtype=float).copy()
    fixed_zero = np.asarray(fixed_zero_mask, dtype=bool)
    kernel = np.asarray([1.0, 2.0, 3.0, 2.0, 1.0], dtype=float)
    kernel /= kernel.sum()
    for _ in range(max(0, int(config.smoothing_passes))):
        for start, end in _true_runs(~fixed_zero):
            if end - start >= 3:
                padded = np.pad(values[start:end], (2, 2), mode="edge")
                values[start:end] = np.convolve(padded, kernel, mode="valid")
        values[fixed_zero] = 0.0
    tolerance = config.lane_group_envelope_tolerance_m
    for _ in range(20):
        for index, envelope in enumerate(envelopes):
            if envelope is not None:
                values[index] = min(
                    max(values[index], envelope[0] - tolerance),
                    envelope[1] + tolerance,
                )
        values[fixed_zero] = 0.0
        for index in range(1, len(values)):
            if fixed_zero[index]:
                continue
            distance = max(float(stations[index] - stations[index - 1]), 0.0)
            limit = min(
                config.max_adjacent_lateral_shift_m,
                config.max_lateral_slope * distance,
            )
            values[index] = min(max(values[index], values[index - 1] - limit), values[index - 1] + limit)
        values[fixed_zero] = 0.0
        for index in range(len(values) - 2, -1, -1):
            if fixed_zero[index]:
                continue
            distance = max(float(stations[index + 1] - stations[index]), 0.0)
            limit = min(
                config.max_adjacent_lateral_shift_m,
                config.max_lateral_slope * distance,
            )
            values[index] = min(max(values[index], values[index + 1] - limit), values[index + 1] + limit)
        values[fixed_zero] = 0.0
    values[fixed_zero] = 0.0
    return values


def _true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(mask):
        if value and start is None:
            start = index
        elif not value and start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(mask)))
    return runs


def _station_geometry_source(
    *,
    support_state: str,
    support_at_station: bool,
    raw_source: str,
    raw_shift: float,
    applied_shift: float,
    transition_from_swsd: bool,
) -> str:
    if support_state == "sd_only":
        return "swsd_parent"
    if not support_at_station:
        return "swsd_gap_retained"
    if transition_from_swsd:
        return "directional_transition_supported"
    if raw_source == "stable_anchor_observation":
        return "directional_anchor_supported"
    if raw_source == "local_lane_group_center":
        return "directional_lane_group_center_supported"
    if abs(applied_shift - raw_shift) > 1e-8:
        return "directional_transition_supported"
    return "swsd_supported_geometry_missing"


def _hp_oscillation(
    stations: list[dict[str, Any]],
    config: DirectionalRoadV2Config,
) -> tuple[float, float]:
    sources = [str(row["station_geometry_source"]) for row in stations]
    values = np.asarray(
        [float(row["applied_lateral_shift_m"]) for row in stations],
        dtype=float,
    )
    offsets = np.asarray(
        [float(row["parent_station_offset_m"]) for row in stations],
        dtype=float,
    )
    hp_mask = np.asarray(
        [
            source
            in {
                "directional_anchor_supported",
                "directional_lane_group_center_supported",
            }
            for source in sources
        ],
        dtype=bool,
    )
    oscillation = 0.0
    distance = 0.0
    minimum_length = max(config.fit_station_spacing_m * 2.0, 1e-8)
    for start, end in _true_runs(hp_mask):
        if end - start < 2:
            continue
        run_distance = float(offsets[end - 1] - offsets[start])
        if run_distance < minimum_length:
            continue
        run = values[start:end]
        total_variation = float(np.abs(np.diff(run)).sum())
        net_shift = abs(float(run[-1] - run[0]))
        oscillation += max(0.0, total_variation - net_shift)
        distance += run_distance
    return oscillation, distance


def _station_offsets(reference: Any, intervals: gpd.GeoDataFrame, spacing: float) -> list[float]:
    length = float(reference.length)
    count = max(2, int(math.ceil(length / max(spacing, 1e-8))) + 1)
    # Geometry is built on one uniform longitudinal grid.  Interval boundaries
    # and every parent vertex used to be inserted as additional stations; when
    # two of them were only centimetres apart, the lateral limiter still
    # allowed a visible jump.  Support membership remains evaluated against the
    # exact intervals, while the output geometry keeps stable station spacing.
    _ = intervals
    return [float(value) for value in np.linspace(0.0, length, count)]


def _offset_coordinate(reference: Any, station: float, shift: float) -> tuple[float, float]:
    point = reference.interpolate(station)
    tangent = tangent_vector(reference, station)
    norm = math.hypot(*tangent)
    if norm <= 1e-12:
        return float(point.x), float(point.y)
    normal = (-tangent[1] / norm, tangent[0] / norm)
    return float(point.x + normal[0] * shift), float(point.y + normal[1] * shift)


def _signed_offset(reference: Any, station: float, point: Point) -> float:
    base = reference.interpolate(station)
    tangent = tangent_vector(reference, station)
    norm = math.hypot(*tangent)
    if norm <= 1e-12:
        return float(base.distance(point))
    vector = (float(point.x - base.x), float(point.y - base.y))
    return float((tangent[0] * vector[1] - tangent[1] * vector[0]) / norm)


def _contains(station: float, ranges: list[tuple[float, float]]) -> bool:
    return any(start - 1e-6 <= station <= end + 1e-6 for start, end in ranges)


def _dedupe_coordinates(values: list[tuple[float, float]]) -> list[tuple[float, float]]:
    result: list[tuple[float, float]] = []
    for value in values:
        if not result or Point(result[-1]).distance(Point(value)) > 1e-8:
            result.append(value)
    return result


def _geometry_segments(
    road: LineString,
    intervals: gpd.GeoDataFrame,
    stations: list[dict[str, Any]],
    *,
    child_id: str,
    parent_id: str,
    travel_side: str,
    run_id: str,
    fit_state: str,
) -> list[dict[str, Any]]:
    del road
    ordered = list(reversed(stations)) if travel_side == "reverse" else list(stations)
    edge_rows: list[dict[str, Any]] = []
    for index, (first, second) in enumerate(zip(ordered, ordered[1:], strict=False)):
        first_state = _station_segment_state(str(first["station_geometry_source"]))
        second_state = _station_segment_state(str(second["station_geometry_source"]))
        state = first_state if first_state == second_state else "transition"
        coordinates = [
            tuple(first["geometry"].coords[0][:2]),
            tuple(second["geometry"].coords[0][:2]),
        ]
        if Point(coordinates[0]).distance(Point(coordinates[1])) <= 1e-8:
            continue
        parent_start = min(
            float(first["parent_station_offset_m"]),
            float(second["parent_station_offset_m"]),
        )
        parent_end = max(
            float(first["parent_station_offset_m"]),
            float(second["parent_station_offset_m"]),
        )
        evidence = intervals[
            (intervals["interval_state"] == "hp_supported")
            & intervals["parent_end_m"].ge(parent_start - 1e-6)
            & intervals["parent_start_m"].le(parent_end + 1e-6)
        ]
        edge_rows.append(
            {
                "edge_index": index,
                "state": state,
                "travel_start_fraction": float(first["travel_station_fraction"]),
                "travel_end_fraction": float(second["travel_station_fraction"]),
                "source_lane_ids": ";".join(
                    sorted(
                        {
                            value
                            for item in evidence.get("source_lane_ids", [])
                            for value in str(item).split(";")
                            if value
                        }
                    )
                ),
                "source_patch_ids": ";".join(
                    sorted(
                        {
                            value
                            for item in evidence.get("source_patch_ids", [])
                            for value in str(item).split(";")
                            if value
                        }
                    )
                ),
                "coordinates": coordinates,
            }
        )

    rows: list[dict[str, Any]] = []
    groups: list[list[dict[str, Any]]] = []
    for edge in edge_rows:
        if not groups or groups[-1][-1]["state"] != edge["state"]:
            groups.append([edge])
        else:
            groups[-1].append(edge)
    for index, group in enumerate(groups):
        state = str(group[0]["state"])
        coordinates = [tuple(group[0]["coordinates"][0])]
        coordinates.extend(tuple(edge["coordinates"][1]) for edge in group)
        rows.append(
            {
                "run_id": run_id,
                "directional_road_id": child_id,
                "parent_swsd_unit_id": parent_id,
                "travel_side": travel_side,
                "interval_id": f"{child_id}:fit:{index}",
                "interval_state": _segment_interval_state(state),
                "travel_start_fraction": float(group[0]["travel_start_fraction"]),
                "travel_end_fraction": float(group[-1]["travel_end_fraction"]),
                "source_lane_ids": ";".join(
                    sorted(
                        {
                            value
                            for edge in group
                            for value in str(edge["source_lane_ids"]).split(";")
                            if value
                        }
                    )
                ),
                "source_patch_ids": ";".join(
                    sorted(
                        {
                            value
                            for edge in group
                            for value in str(edge["source_patch_ids"]).split(";")
                            if value
                        }
                    )
                ),
                "geometry_source": _segment_geometry_source(state),
                "geometry_fit_state": fit_state,
                "geometry": LineString(coordinates),
            }
        )
    return rows


def _station_segment_state(source: str) -> str:
    if source in {
        "directional_anchor_supported",
        "directional_lane_group_center_supported",
    }:
        return "hp_fitted"
    if source in {
        "swsd_parent",
        "swsd_gap_retained",
        "swsd_supported_geometry_missing",
    }:
        return "swsd_retained"
    return "transition"


def _segment_interval_state(state: str) -> str:
    if state == "hp_fitted":
        return "hp_supported"
    if state == "swsd_retained":
        return "sd_gap"
    return "transition"


def _segment_geometry_source(state: str) -> str:
    if state == "hp_fitted":
        return "directional_hp_centerline"
    if state == "swsd_retained":
        return "directional_sd_gap_swsd_retained"
    return "directional_hp_to_swsd_transition"


def _geometry_source(unit: Any, fit_state: str) -> str:
    if str(unit.travel_side) == "sd_parent":
        return "swsd_parent_retained"
    if str(unit.directional_support_state) == "sd_only":
        return "directional_sd_only_parent_centerline"
    return "directional_centerline_v2:" + fit_state


def _summary(
    candidates: gpd.GeoDataFrame,
    stations: gpd.GeoDataFrame,
    *,
    config: DirectionalRoadV2Config,
) -> dict[str, Any]:
    max_jump = float(candidates["max_adjacent_lateral_shift_m"].max())
    max_tv = float(candidates["lateral_total_variation_per_100m"].max())
    max_hp_tv = float(candidates["hp_lateral_total_variation_per_100m"].max())
    max_hp_oscillation = float(candidates["hp_lateral_oscillation_per_100m"].max())
    max_ratio = float(candidates["candidate_length_ratio"].max())
    envelope_violations = int(candidates["lane_group_envelope_violation_count"].sum())
    non_sd_bidirectional = int(
        (
            (candidates["support_state"] != "sd_only")
            & candidates["direction"].isin([0, 1])
        ).sum()
    )
    supported = stations[stations["support_at_station"].astype(bool)]
    unsupported = stations[~stations["support_at_station"].astype(bool)]
    unsupported_shift = unsupported["applied_lateral_shift_m"].astype(float).abs()
    endpoint_rows = stations.sort_values(
        ["directional_road_id", "parent_station_index"]
    ).groupby("directional_road_id", sort=False).nth([0, -1])
    unsupported_endpoints = endpoint_rows[
        ~endpoint_rows["support_at_station"].astype(bool)
    ]
    unsupported_endpoint_shift = (
        unsupported_endpoints["applied_lateral_shift_m"].astype(float).abs()
    )
    source_counts = dict(sorted(Counter(stations["station_geometry_source"]).items()))
    audited_sources = {
        "swsd_parent",
        "swsd_gap_retained",
        "directional_anchor_supported",
        "directional_lane_group_center_supported",
        "directional_transition_supported",
        "swsd_supported_geometry_missing",
    }
    gates = {
        "geometry_nonempty": bool(candidates.geometry.notna().all() and (~candidates.geometry.is_empty).all()),
        "geometry_valid": bool(candidates.geometry.is_valid.all()),
        "geometry_simple": bool(candidates.geometry.is_simple.all()),
        "no_non_sd_bidirectional_object": non_sd_bidirectional == 0,
        "anchor_switch_zero": int(candidates["anchor_switch_count"].sum()) == 0,
        "lane_group_envelope": envelope_violations == 0,
        "adjacent_lateral_shift": max_jump <= config.max_adjacent_lateral_shift_m + 1e-8,
        "hp_lateral_oscillation": max_hp_oscillation
        <= config.max_total_variation_per_100m + 1e-8,
        "candidate_length_ratio": max_ratio <= config.max_candidate_length_ratio + 1e-8,
        "unsupported_gap_retained_on_swsd": bool(
            unsupported_shift.empty or unsupported_shift.max() <= 1e-8
        ),
        "unsupported_endpoint_retained_on_swsd": bool(
            unsupported_endpoint_shift.empty
            or unsupported_endpoint_shift.max() <= 1e-8
        ),
        "station_geometry_source_audited": set(source_counts).issubset(audited_sources),
    }
    return {
        "road_candidate_count": int(len(candidates)),
        "support_state_counts": dict(sorted(Counter(candidates["support_state"]).items())),
        "geometry_fit_state_counts": dict(sorted(Counter(candidates["geometry_fit_state"]).items())),
        "fit_station_count": int(len(stations)),
        "nonempty_geometry_count": int((~candidates.geometry.is_empty).sum()),
        "valid_geometry_count": int(candidates.geometry.is_valid.sum()),
        "simple_geometry_count": int(candidates.geometry.is_simple.sum()),
        "non_sd_bidirectional_object_count": non_sd_bidirectional,
        "lane_group_envelope_violation_count": envelope_violations,
        "max_adjacent_lateral_shift_m": max_jump,
        "max_lateral_total_variation_per_100m": max_tv,
        "max_hp_lateral_total_variation_per_100m": max_hp_tv,
        "max_hp_lateral_oscillation_per_100m": max_hp_oscillation,
        "max_candidate_length_ratio": max_ratio,
        "p95_candidate_length_ratio": float(candidates["candidate_length_ratio"].quantile(0.95)),
        "max_parent_swsd_portal_delta_m": float(
            max(
                candidates["start_parent_swsd_portal_delta_m"].max(),
                candidates["end_parent_swsd_portal_delta_m"].max(),
            )
        ),
        "station_geometry_source_counts": source_counts,
        "supported_station_count": int(len(supported)),
        "direct_anchor_observed_station_count": int(
            supported["anchor_observed_at_station"].astype(bool).sum()
        ),
        "supported_without_direct_anchor_count": int(
            len(supported)
            - supported["anchor_observed_at_station"].astype(bool).sum()
        ),
        "unsupported_station_count": int(len(unsupported)),
        "unsupported_station_shift_count": int((unsupported_shift > 1e-8).sum()),
        "unsupported_station_max_shift_m": float(
            unsupported_shift.max() if not unsupported_shift.empty else 0.0
        ),
        "unsupported_endpoint_count": int(len(unsupported_endpoints)),
        "unsupported_endpoint_shift_count": int(
            (unsupported_endpoint_shift > 1e-8).sum()
        ),
        "unsupported_endpoint_max_shift_m": float(
            unsupported_endpoint_shift.max()
            if not unsupported_endpoint_shift.empty
            else 0.0
        ),
        "gates": gates,
        "road_geometry_gate_pass": all(gates.values()),
    }


__all__ = ["DirectionalGeometryResult", "instantiate_directional_geometries"]
