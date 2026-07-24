from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import substring

from .geometry import canonical_id, tangent_vector
from .road_config import MilestoneTwoConfig


@dataclass(frozen=True)
class RoadGeometryResult:
    road_candidates: gpd.GeoDataFrame
    geometry_segments: gpd.GeoDataFrame
    fit_stations: gpd.GeoDataFrame
    summary: dict[str, Any]


def instantiate_road_geometries(
    swsd_roads: gpd.GeoDataFrame,
    lane_segments: gpd.GeoDataFrame,
    support_intervals: gpd.GeoDataFrame,
    road_audit: pd.DataFrame,
    *,
    config: MilestoneTwoConfig,
) -> RoadGeometryResult:
    roads = swsd_roads.copy().reset_index(drop=True)
    roads["swsd_unit_id"] = roads["swsd_unit_id"].map(canonical_id)
    audit_by_road = road_audit.set_index("swsd_unit_id", drop=False)
    segments_by_road = {
        str(road_id): frame.reset_index(drop=True)
        for road_id, frame in lane_segments.groupby("swsd_unit_id")
    }
    intervals_by_road = {
        str(road_id): frame.sort_values("interval_index").reset_index(drop=True)
        for road_id, frame in support_intervals.groupby("swsd_unit_id")
    }

    candidate_rows: list[dict[str, Any]] = []
    station_rows: list[dict[str, Any]] = []
    geometry_segment_rows: list[dict[str, Any]] = []
    for road in roads.itertuples(index=False):
        road_id = str(road.swsd_unit_id)
        audit = audit_by_road.loc[road_id]
        source_segments = segments_by_road.get(road_id)
        intervals = intervals_by_road[road_id]
        attempted_geometry, stations = _fit_one_road(
            road.geometry,
            source_segments,
            intervals,
            support_state=str(audit["support_state"]),
            road_id=road_id,
            config=config,
        )
        attempted_simple = bool(attempted_geometry.is_simple)
        if not attempted_simple and road.geometry.is_simple:
            geometry = road.geometry
            fit_state = "fit_rejected_non_simple_swsd_retained"
            for station in stations:
                station["attempted_lateral_shift_m"] = station["applied_lateral_shift_m"]
                station["applied_lateral_shift_m"] = 0.0
                station["station_geometry_source"] = "swsd_fit_rejected_non_simple"
                station["geometry"] = road.geometry.interpolate(station["station_offset_m"])
        else:
            geometry = attempted_geometry
            fit_state = _fit_state(str(audit["support_state"]), attempted_simple)
            for station in stations:
                station["attempted_lateral_shift_m"] = station["applied_lateral_shift_m"]
        start_anchor_delta_m = Point(geometry.coords[0]).distance(
            Point(road.geometry.coords[0])
        )
        end_anchor_delta_m = Point(geometry.coords[-1]).distance(
            Point(road.geometry.coords[-1])
        )
        station_rows.extend(stations)
        shifts = [abs(float(row["applied_lateral_shift_m"])) for row in stations]
        attempted_shifts = [abs(float(row["attempted_lateral_shift_m"])) for row in stations]
        base = {
            key: value
            for key, value in road._asdict().items()
            if key != "geometry" and not key.startswith("_")
        }
        base.update(
            {
                "run_id": config.run_id,
                "source_object_type": "SWSDRoad+LaneEvidenceSegment",
                "source_object_ids": audit["source_lane_ids"] or road_id,
                "swsd_unit_id": road_id,
                "decision": "published_poc_candidate",
                "reason_codes": str(audit["support_reason"]),
                "evidence_state": "road_geometry_candidate",
                "input_manifest_ref": "p04_input_manifest.json",
                "support_state": str(audit["support_state"]),
                "evidence_quality_state": str(audit["evidence_quality_state"]),
                "geometry_source": _road_geometry_source(
                    str(audit["support_state"]), fit_state=fit_state
                ),
                "geometry_fit_state": fit_state,
                "attempted_geometry_simple": attempted_simple,
                "support_coverage_ratio": float(audit["support_coverage_ratio"]),
                "support_length_m": float(audit["support_length_m"]),
                "gap_length_m": float(audit["gap_length_m"]),
                "max_gap_m": float(audit["max_gap_m"]),
                "source_lane_count": int(audit["source_lane_count"]),
                "lane_segment_count": int(audit["lane_segment_count"]),
                "swsd_reference_length_m": float(road.geometry.length),
                "candidate_length_m": float(geometry.length),
                "fit_station_count": len(stations),
                "median_lateral_shift_m": float(np.median(shifts)) if shifts else 0.0,
                "max_lateral_shift_m": max(shifts, default=0.0),
                "attempted_max_lateral_shift_m": max(attempted_shifts, default=0.0),
                "start_anchor_delta_m": float(start_anchor_delta_m),
                "end_anchor_delta_m": float(end_anchor_delta_m),
                "geometry": geometry,
            }
        )
        candidate_rows.append(base)
        geometry_segment_rows.extend(
            _candidate_interval_geometries(
                geometry,
                intervals,
                road_id=road_id,
                run_id=config.run_id,
                fit_state=fit_state,
            )
        )

    candidates = gpd.GeoDataFrame(candidate_rows, geometry="geometry", crs=roads.crs)
    geometry_segments = gpd.GeoDataFrame(
        geometry_segment_rows, geometry="geometry", crs=roads.crs
    )
    fit_stations = gpd.GeoDataFrame(station_rows, geometry="geometry", crs=roads.crs)
    summary = _geometry_summary(candidates, geometry_segments, fit_stations)
    return RoadGeometryResult(
        road_candidates=candidates,
        geometry_segments=geometry_segments,
        fit_stations=fit_stations,
        summary=summary,
    )


def _fit_one_road(
    reference: Any,
    lane_segments: gpd.GeoDataFrame | None,
    intervals: gpd.GeoDataFrame,
    *,
    support_state: str,
    road_id: str,
    config: MilestoneTwoConfig,
) -> tuple[LineString, list[dict[str, Any]]]:
    length = float(reference.length)
    station_offsets = _station_offsets(
        reference,
        intervals,
        spacing_m=config.fit_station_spacing_m,
    )
    support_ranges = [
        (float(row.start_m), float(row.end_m))
        for row in intervals.itertuples()
        if str(row.interval_state) == "hp_supported"
    ]
    coordinates: list[tuple[float, float]] = []
    station_rows: list[dict[str, Any]] = []
    for station_index, station_offset in enumerate(station_offsets):
        reference_point = reference.interpolate(station_offset)
        supported_range = _containing_range(station_offset, support_ranges)
        candidate_offsets = _lane_offsets_at_station(
            reference,
            reference_point,
            station_offset,
            lane_segments,
            max_distance_m=config.fit_max_lane_distance_m,
        )
        if support_state == "conflict_retained" or supported_range is None or not candidate_offsets:
            raw_shift = 0.0
            applied_shift = 0.0
            source_lane_ids = ""
            station_source = (
                "conflict_swsd_retained"
                if support_state == "conflict_retained"
                else ("swsd_gap" if supported_range is None else "swsd_fit_fallback")
            )
        else:
            raw_shift = weighted_median(
                [row["lateral_offset_m"] for row in candidate_offsets],
                [row["fit_weight"] for row in candidate_offsets],
            )
            blend = _blend_factor(
                station_offset,
                supported_range,
                road_length=length,
                transition_length_m=config.fit_transition_length_m,
            )
            applied_shift = raw_shift * blend
            source_lane_ids = ";".join(sorted({row["lane_id"] for row in candidate_offsets}))
            station_source = "hp_lane_median"
        tangent = _unit_tangent(reference, station_offset)
        normal = (-tangent[1], tangent[0])
        coordinate = (
            float(reference_point.x + normal[0] * applied_shift),
            float(reference_point.y + normal[1] * applied_shift),
        )
        if not coordinates or coordinate != coordinates[-1]:
            coordinates.append(coordinate)
        station_rows.append(
            {
                "run_id": config.run_id,
                "swsd_unit_id": road_id,
                "station_index": station_index,
                "station_offset_m": station_offset,
                "station_fraction": station_offset / length if length > 1e-8 else 0.0,
                "support_at_station": supported_range is not None,
                "fit_candidate_count": len(candidate_offsets),
                "source_lane_ids": source_lane_ids,
                "raw_lateral_shift_m": raw_shift,
                "applied_lateral_shift_m": applied_shift,
                "station_geometry_source": station_source,
                "geometry": Point(coordinate),
            }
        )
    if len(coordinates) < 2:
        coordinates = [tuple(reference.coords[0][:2]), tuple(reference.coords[-1][:2])]
    return LineString(coordinates), station_rows


def _lane_offsets_at_station(
    reference: Any,
    reference_point: Point,
    station_offset: float,
    lane_segments: gpd.GeoDataFrame | None,
    *,
    max_distance_m: float,
) -> list[dict[str, Any]]:
    if lane_segments is None or lane_segments.empty:
        return []
    tolerance = 1e-6
    selected = lane_segments[
        lane_segments["road_start_m"].le(station_offset + tolerance)
        & lane_segments["road_end_m"].ge(station_offset - tolerance)
    ]
    tangent = _unit_tangent(reference, station_offset)
    result: list[dict[str, Any]] = []
    for segment in selected.itertuples():
        nearest_offset = float(segment.geometry.project(reference_point))
        nearest = segment.geometry.interpolate(nearest_offset)
        distance = float(reference_point.distance(nearest))
        if distance > max_distance_m:
            continue
        vector = (float(nearest.x - reference_point.x), float(nearest.y - reference_point.y))
        lateral_offset = tangent[0] * vector[1] - tangent[1] * vector[0]
        result.append(
            {
                "lane_id": str(segment.lane_id),
                "lateral_offset_m": float(lateral_offset),
                "fit_weight": float(segment.fit_weight),
            }
        )
    return result


def weighted_median(values: Iterable[float], weights: Iterable[float]) -> float:
    pairs = sorted((float(value), max(float(weight), 0.0)) for value, weight in zip(values, weights))
    if not pairs:
        return 0.0
    total = sum(weight for _, weight in pairs)
    if total <= 0.0:
        return float(np.median([value for value, _ in pairs]))
    threshold = total / 2.0
    cumulative = 0.0
    for index, (value, weight) in enumerate(pairs):
        cumulative += weight
        if math.isclose(cumulative, threshold) and index + 1 < len(pairs):
            return (value + pairs[index + 1][0]) / 2.0
        if cumulative >= threshold:
            return value
    return pairs[-1][0]


def _station_offsets(reference: Any, intervals: gpd.GeoDataFrame, *, spacing_m: float) -> list[float]:
    length = float(reference.length)
    count = max(2, int(math.ceil(max(length, 0.0) / spacing_m)) + 1)
    offsets = set(float(value) for value in np.linspace(0.0, length, count))
    for interval in intervals.itertuples():
        offsets.add(float(interval.start_m))
        offsets.add(float(interval.end_m))
    for coordinate in reference.coords:
        offsets.add(float(reference.project(Point(coordinate[:2]))))
    return sorted(max(0.0, min(length, value)) for value in offsets)


def _containing_range(
    station_offset: float,
    ranges: list[tuple[float, float]],
) -> tuple[float, float] | None:
    for start, end in ranges:
        if start - 1e-6 <= station_offset <= end + 1e-6:
            return start, end
    return None


def _blend_factor(
    station_offset: float,
    support_range: tuple[float, float],
    *,
    road_length: float,
    transition_length_m: float,
) -> float:
    start, end = support_range
    start_factor = (
        1.0
        if start <= 1e-8
        else min(1.0, max(0.0, station_offset - start) / transition_length_m)
    )
    end_factor = (
        1.0
        if end >= road_length - 1e-8
        else min(1.0, max(0.0, end - station_offset) / transition_length_m)
    )
    road_start_factor = min(
        1.0, max(0.0, station_offset) / transition_length_m
    )
    road_end_factor = min(
        1.0, max(0.0, road_length - station_offset) / transition_length_m
    )
    return min(start_factor, end_factor, road_start_factor, road_end_factor)


def _candidate_interval_geometries(
    road_candidate: LineString,
    intervals: gpd.GeoDataFrame,
    *,
    road_id: str,
    run_id: str,
    fit_state: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    candidate_length = float(road_candidate.length)
    for interval in intervals.itertuples():
        start = candidate_length * float(interval.start_fraction)
        end = candidate_length * float(interval.end_fraction)
        interval_state = str(interval.interval_state)
        if fit_state == "fit_rejected_non_simple_swsd_retained":
            geometry_source = "swsd_retained_fit_rejected"
        else:
            geometry_source = (
                "hp_fitted"
                if interval_state == "hp_supported"
                else (
                    "conflict_retained"
                    if interval_state == "conflict_retained"
                    else "swsd_retained"
                )
            )
        rows.append(
            {
                "run_id": run_id,
                "swsd_unit_id": road_id,
                "interval_id": str(interval.interval_id),
                "interval_index": int(interval.interval_index),
                "interval_state": interval_state,
                "start_fraction": float(interval.start_fraction),
                "end_fraction": float(interval.end_fraction),
                "source_lane_ids": str(interval.source_lane_ids),
                "source_patch_ids": str(interval.source_patch_ids),
                "geometry_source": geometry_source,
                "geometry": _line_part(road_candidate, start, end),
            }
        )
    return rows


def _road_geometry_source(support_state: str, *, fit_state: str) -> str:
    if fit_state == "fit_rejected_non_simple_swsd_retained":
        return "swsd_retained_fit_rejected"
    return {
        "hp_supported": "hp_fitted",
        "partial_hp_supported": "hybrid_hp_swsd",
        "sd_only": "swsd_retained",
        "conflict_retained": "swsd_conflict_retained",
    }[support_state]


def _fit_state(support_state: str, attempted_simple: bool) -> str:
    if not attempted_simple:
        return "reference_or_candidate_non_simple"
    return {
        "hp_supported": "hp_fitted",
        "partial_hp_supported": "hybrid_fitted",
        "sd_only": "swsd_retained_no_evidence",
        "conflict_retained": "swsd_retained_conflict",
    }[support_state]


def _unit_tangent(line: Any, distance: float) -> tuple[float, float]:
    tangent = tangent_vector(line, distance)
    norm = math.hypot(*tangent)
    if norm <= 1e-12:
        return 0.0, 0.0
    return tangent[0] / norm, tangent[1] / norm


def _line_part(line: Any, start: float, end: float) -> Any:
    if end - start <= 1e-8:
        point = line.interpolate(start)
        return LineString([point, point])
    return substring(line, start, end)


def _geometry_summary(
    candidates: gpd.GeoDataFrame,
    geometry_segments: gpd.GeoDataFrame,
    fit_stations: gpd.GeoDataFrame,
) -> dict[str, Any]:
    states = Counter(candidates["support_state"])
    fit_states = Counter(candidates["geometry_fit_state"])
    sd = candidates[candidates["support_state"] == "sd_only"]
    endpoint_anchor_max_delta_m = float(
        max(
            candidates["start_anchor_delta_m"].max(),
            candidates["end_anchor_delta_m"].max(),
        )
    )
    endpoint_anchor_gate_pass = endpoint_anchor_max_delta_m <= 1e-8
    return {
        "road_candidate_count": int(len(candidates)),
        "support_state_counts": dict(sorted(states.items())),
        "nonempty_geometry_count": int((~candidates.geometry.is_empty).sum()),
        "valid_geometry_count": int(candidates.geometry.is_valid.sum()),
        "simple_geometry_count": int(candidates.geometry.is_simple.sum()),
        "attempted_non_simple_geometry_count": int(
            (~candidates["attempted_geometry_simple"]).sum()
        ),
        "fit_rejected_non_simple_count": int(
            (candidates["geometry_fit_state"] == "fit_rejected_non_simple_swsd_retained").sum()
        ),
        "geometry_fit_state_counts": dict(sorted(fit_states.items())),
        "geometry_segment_count": int(len(geometry_segments)),
        "fit_station_count": int(len(fit_stations)),
        "fit_station_source_counts": dict(
            sorted(Counter(fit_stations["station_geometry_source"]).items())
        ),
        "max_lateral_shift_m": float(candidates["max_lateral_shift_m"].max()),
        "p95_max_lateral_shift_m": float(candidates["max_lateral_shift_m"].quantile(0.95)),
        "attempted_max_lateral_shift_m": float(
            candidates["attempted_max_lateral_shift_m"].max()
        ),
        "endpoint_anchor_max_delta_m": endpoint_anchor_max_delta_m,
        "endpoint_anchor_gate_pass": endpoint_anchor_gate_pass,
        "sd_only_zero_shift_gate_pass": bool(
            sd.empty or sd["max_lateral_shift_m"].abs().max() <= 1e-8
        ),
        "road_geometry_gate_pass": bool(
            candidates.geometry.notna().all()
            and (~candidates.geometry.is_empty).all()
            and candidates.geometry.is_valid.all()
            and candidates.geometry.is_simple.all()
            and endpoint_anchor_gate_pass
        ),
    }


__all__ = [
    "RoadGeometryResult",
    "instantiate_road_geometries",
    "weighted_median",
]
