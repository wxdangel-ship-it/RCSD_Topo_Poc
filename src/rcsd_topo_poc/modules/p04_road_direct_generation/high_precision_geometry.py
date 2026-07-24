from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import substring, unary_union

from .high_precision_config import HighPrecisionRoadV3Config


@dataclass(frozen=True)
class HighPrecisionGeometryResult:
    road_candidates: gpd.GeoDataFrame
    center_observations: gpd.GeoDataFrame
    control_spans: gpd.GeoDataFrame
    geometry_segments: gpd.GeoDataFrame
    fit_stations: gpd.GeoDataFrame
    summary: dict[str, Any]


def instantiate_high_precision_geometries(
    road_units: gpd.GeoDataFrame,
    lane_group_members: gpd.GeoDataFrame,
    drivezones: gpd.GeoDataFrame,
    *,
    config: HighPrecisionRoadV3Config,
) -> HighPrecisionGeometryResult:
    drivezone = unary_union(
        [geometry for geometry in drivezones.geometry if geometry is not None and not geometry.is_empty]
    )
    road_rows: list[dict[str, Any]] = []
    observation_rows: list[dict[str, Any]] = []
    span_rows: list[dict[str, Any]] = []
    segment_rows: list[dict[str, Any]] = []
    station_rows: list[dict[str, Any]] = []

    for unit in road_units.itertuples(index=False):
        road_id = str(unit.v3_road_id)
        reference = _line_geometry(unit.geometry)
        members = lane_group_members[
            lane_group_members["v3_road_id"].astype(str) == road_id
        ].copy()
        if "geometry_role" in members.columns:
            members = members[members["geometry_role"] == "hard_geometry"]
        if "evidence_quality_state" in members.columns:
            members = members[
                members["evidence_quality_state"].astype(str)
                == config.hard_evidence_quality_state
            ]
        stations = _station_offsets(reference.length, config.fit_station_spacing_m)
        observed: list[float | None] = []
        envelopes: list[tuple[float | None, float | None]] = []
        observation_sources: list[str] = []
        for index, station in enumerate(stations):
            value = _station_observation(
                reference,
                station,
                members,
                longitudinal_tolerance=config.observation_longitudinal_tolerance_m,
                max_distance=config.anchor_max_distance_m,
            )
            if value is None:
                observed.append(None)
                envelopes.append((None, None))
                observation_sources.append("")
                continue
            offset, minimum, maximum, source_ids, point = value
            observed.append(offset)
            envelopes.append((minimum, maximum))
            observation_sources.append(source_ids)
            observation_rows.append(
                {
                    "run_id": config.run_id,
                    "v3_road_id": road_id,
                    "parent_swsd_unit_id": str(unit.parent_swsd_unit_id),
                    "station_index": index,
                    "station_offset_m": station,
                    "station_fraction": station / reference.length if reference.length else 0.0,
                    "observation_kind": "robust_lane_center",
                    "source_lane_ids": source_ids,
                    "lateral_offset_m": offset,
                    "lane_envelope_min_m": minimum,
                    "lane_envelope_max_m": maximum,
                    "drivezone_contained": _point_in_zone(point, drivezone, config.drivezone_tolerance_m),
                    "observation_quality_state": "usable",
                    "geometry": point,
                }
            )

        applied, sources, reasons = _fill_offsets(
            reference,
            stations,
            observed,
            drivezone,
            config=config,
        )
        applied = _smooth_offsets(
            stations,
            applied,
            envelopes,
            sources,
            config=config,
        )
        applied = _enforce_slope(stations, applied, sources, config.max_lateral_slope)
        coordinates = [
            _shifted_point(reference, station, offset).coords[0]
            for station, offset in zip(stations, applied)
        ]
        candidate = LineString(coordinates)
        if not candidate.is_valid or not candidate.is_simple:
            candidate = reference
            applied = [0.0] * len(stations)
            sources = ["swsd_fallback"] * len(stations)
            reasons = ["candidate_invalid_or_non_simple"] * len(stations)
        if candidate.length > reference.length * config.max_candidate_length_ratio:
            candidate = reference
            applied = [0.0] * len(stations)
            sources = ["swsd_fallback"] * len(stations)
            reasons = ["candidate_length_ratio_gate_failed"] * len(stations)

        runs = _source_runs(stations, sources, reasons, reference.length)
        source_lengths = {source: 0.0 for source in _SOURCE_VALUES}
        for run_index, run in enumerate(runs):
            geometry = substring(
                candidate,
                run["start_fraction"],
                run["end_fraction"],
                normalized=True,
            )
            if geometry.geom_type == "Point":
                continue
            length = float(geometry.length)
            source_lengths[run["geometry_source"]]
            source_lengths[run["geometry_source"]] += length
            row = {
                "run_id": config.run_id,
                "v3_road_id": road_id,
                "parent_swsd_unit_id": str(unit.parent_swsd_unit_id),
                "segment_id": f"{road_id}:{run_index}",
                "start_fraction": run["start_fraction"],
                "end_fraction": run["end_fraction"],
                "length_m": length,
                "geometry_source": run["geometry_source"],
                "control_kind": run["control_kind"],
                "reason_codes": run["reason_codes"],
                "geometry": geometry,
            }
            segment_rows.append(row)
            span_rows.append({**row, "span_id": row["segment_id"]})

        observed_length = source_lengths["hp_observed"]
        constrained_length = source_lengths["hp_constrained_interpolation"]
        fallback_length = source_lengths["swsd_fallback"]
        total_length = max(float(candidate.length), 1e-9)
        control_ratio = min(1.0, (observed_length + constrained_length) / total_length)
        fallback_ratio = min(1.0, fallback_length / total_length)
        support_state = (
            "sd_only"
            if observed_length <= 1e-9
            else "hp_supported"
            if fallback_length <= 1e-9 and constrained_length <= 1e-9
            else "partial_hp_supported"
        )
        claim_scope = (
            "none"
            if support_state == "sd_only"
            else "full_road_direct_observation"
            if support_state == "hp_supported"
            else "observed_and_constrained_full_road"
            if fallback_length <= 1e-9
            else "observed_and_constrained_intervals_only"
        )
        base = {
            key: value
            for key, value in unit._asdict().items()
            if key != "geometry" and not key.startswith("_")
        }
        road_rows.append(
            {
                **base,
                "support_state": support_state,
                "high_precision_claim_scope": claim_scope,
                "observed_length_m": observed_length,
                "constrained_length_m": constrained_length,
                "swsd_fallback_length_m": fallback_length,
                "high_precision_control_ratio": control_ratio,
                "swsd_fallback_ratio": fallback_ratio,
                "geometry_fit_state": "high_precision_skeleton_v3",
                "geometry_reason_codes": ";".join(sorted(set(reasons) - {""})),
                "geometry_valid": bool(candidate.is_valid),
                "geometry_simple": bool(candidate.is_simple),
                "candidate_length_ratio": float(candidate.length / reference.length)
                if reference.length
                else math.nan,
                "geometry": candidate,
            }
        )
        for index, (station, raw, offset, source, reason, source_ids, envelope) in enumerate(
            zip(
                stations,
                observed,
                applied,
                sources,
                reasons,
                observation_sources,
                envelopes,
            )
        ):
            point = _shifted_point(reference, station, offset)
            station_rows.append(
                {
                    "run_id": config.run_id,
                    "v3_road_id": road_id,
                    "parent_swsd_unit_id": str(unit.parent_swsd_unit_id),
                    "station_index": index,
                    "station_offset_m": station,
                    "station_fraction": station / reference.length if reference.length else 0.0,
                    "direct_observation": raw is not None,
                    "source_lane_ids": source_ids,
                    "raw_lateral_shift_m": raw,
                    "applied_lateral_shift_m": offset,
                    "lane_envelope_min_m": envelope[0],
                    "lane_envelope_max_m": envelope[1],
                    "geometry_source": source,
                    "reason_codes": reason,
                    "geometry": point,
                }
            )

    roads = gpd.GeoDataFrame(road_rows, geometry="geometry", crs=road_units.crs)
    observations = _frame(observation_rows, road_units.crs, "center_observation_id")
    control_spans = _frame(span_rows, road_units.crs, "span_id")
    geometry_segments = _frame(segment_rows, road_units.crs, "segment_id")
    fit_stations = _frame(station_rows, road_units.crs, "station_index")
    total = float(roads.geometry.length.sum()) if not roads.empty else 0.0
    observed_total = float(roads["observed_length_m"].sum()) if not roads.empty else 0.0
    constrained_total = float(roads["constrained_length_m"].sum()) if not roads.empty else 0.0
    fallback_total = float(roads["swsd_fallback_length_m"].sum()) if not roads.empty else 0.0
    evidence_roads = roads[roads["observed_length_m"] > 0]
    evidence_length = float(evidence_roads.geometry.length.sum())
    evidence_controlled = float(
        evidence_roads["observed_length_m"].sum()
        + evidence_roads["constrained_length_m"].sum()
    )
    summary = {
        "road_candidate_count": int(len(roads)),
        "support_state_counts": roads["support_state"].value_counts().to_dict(),
        "network_length_m": total,
        "observed_length_m": observed_total,
        "constrained_length_m": constrained_total,
        "swsd_fallback_length_m": fallback_total,
        "observed_ratio": observed_total / total if total else 0.0,
        "high_precision_control_ratio": (observed_total + constrained_total) / total
        if total
        else 0.0,
        "swsd_fallback_ratio": fallback_total / total if total else 0.0,
        "evidence_road_control_ratio": evidence_controlled / evidence_length
        if evidence_length
        else 0.0,
        "geometry_nonempty_count": int((~roads.geometry.is_empty).sum()),
        "geometry_valid_count": int(roads.geometry.is_valid.sum()),
        "geometry_simple_count": int(roads.geometry.is_simple.sum()),
    }
    return HighPrecisionGeometryResult(
        road_candidates=roads,
        center_observations=observations,
        control_spans=control_spans,
        geometry_segments=geometry_segments,
        fit_stations=fit_stations,
        summary=summary,
    )


def reconcile_final_road_geometries(
    result: HighPrecisionGeometryResult,
    final_roads: gpd.GeoDataFrame,
    *,
    config: HighPrecisionRoadV3Config,
) -> HighPrecisionGeometryResult:
    """Rebuild source intervals on endpoint-coordinated published geometries.

    Direct observations remain at their raw evidence locations.  Any interval
    moved by portal coordination is downgraded to constrained interpolation
    when the target is HP-supported, otherwise to explicit SWSD fallback.
    """

    roads = final_roads.copy().reset_index(drop=True)
    original_segments = result.geometry_segments.copy()
    segment_rows: list[dict[str, Any]] = []
    station_frames: list[gpd.GeoDataFrame] = []
    for road_index, road in roads.iterrows():
        road_id = str(road["v3_road_id"])
        geometry = _line_geometry(road.geometry)
        source_frame = original_segments[
            original_segments["v3_road_id"].astype(str) == road_id
        ].sort_values(["start_fraction", "end_fraction"])
        adjustments = _coordination_intervals(road, geometry.length, config)
        cuts = {0.0, 1.0}
        cuts.update(source_frame["start_fraction"].astype(float))
        cuts.update(source_frame["end_fraction"].astype(float))
        for start, end, _ in adjustments:
            cuts.update((start, end))
        ordered = sorted(min(1.0, max(0.0, value)) for value in cuts)
        road_rows: list[dict[str, Any]] = []
        for start, end in zip(ordered, ordered[1:]):
            if end - start <= 1e-9:
                continue
            midpoint = (start + end) / 2.0
            original = source_frame[
                (source_frame["start_fraction"].astype(float) <= midpoint + 1e-9)
                & (source_frame["end_fraction"].astype(float) >= midpoint - 1e-9)
            ]
            if original.empty:
                source = "swsd_fallback"
                control_kind = "missing_precoordination_source"
                reasons = "source_partition_missing_after_coordination"
            else:
                source = str(original.iloc[0].geometry_source)
                control_kind = str(original.iloc[0].control_kind)
                reasons = str(original.iloc[0].reason_codes)
            adjusted_source = _coordination_source(midpoint, adjustments)
            if adjusted_source is not None:
                source = (
                    "hp_constrained_interpolation"
                    if source != "swsd_fallback"
                    else adjusted_source
                )
                control_kind = "endpoint_coordination"
                reasons = ";".join(
                    value
                    for value in (
                        reasons,
                        "published_endpoint_coordination",
                        "swsd_portal_to_hp_interior_transition"
                        if adjusted_source == "swsd_fallback"
                        and source == "hp_constrained_interpolation"
                        else "",
                    )
                    if value
                )
            piece = substring(geometry, start, end, normalized=True)
            if piece.geom_type == "Point":
                continue
            road_rows.append(
                {
                    "run_id": config.run_id,
                    "v3_road_id": road_id,
                    "parent_swsd_unit_id": str(road.parent_swsd_unit_id),
                    "start_fraction": start,
                    "end_fraction": end,
                    "geometry_source": source,
                    "control_kind": control_kind,
                    "reason_codes": reasons,
                    "geometry": piece,
                }
            )
        original_stations = result.fit_stations[
            result.fit_stations["v3_road_id"].astype(str) == road_id
        ]
        retained_direct_fractions = [
            float(station.station_fraction)
            for station in original_stations.itertuples(index=False)
            if bool(station.direct_observation)
            and _coordination_source(float(station.station_fraction), adjustments)
            is None
        ]
        for row in road_rows:
            if row["geometry_source"] != "hp_observed":
                continue
            backed = any(
                float(row["start_fraction"]) - 1e-9
                <= fraction
                <= float(row["end_fraction"]) + 1e-9
                for fraction in retained_direct_fractions
            )
            if not backed:
                row["geometry_source"] = "hp_constrained_interpolation"
                row["control_kind"] = "observation_bridging_interpolation"
                row["reason_codes"] = ";".join(
                    value
                    for value in (
                        str(row["reason_codes"]),
                        "no_unmoved_direct_station_inside_final_interval",
                    )
                    if value
                )
        for segment_index, row in enumerate(road_rows):
            row["segment_id"] = f"{road_id}:final:{segment_index}"
            row["length_m"] = float(row["geometry"].length)
            segment_rows.append(row)

        lengths = {
            source: sum(
                float(row["geometry"].length)
                for row in road_rows
                if row["geometry_source"] == source
            )
            for source in _SOURCE_VALUES
        }
        total = max(float(geometry.length), 1e-9)
        observed = lengths["hp_observed"]
        constrained = lengths["hp_constrained_interpolation"]
        fallback = lengths["swsd_fallback"]
        support_state = (
            "sd_only"
            if observed <= 1e-9 and constrained <= 1e-9
            else "hp_supported"
            if constrained <= 1e-9 and fallback <= 1e-9
            else "partial_hp_supported"
        )
        roads.at[road_index, "observed_length_m"] = observed
        roads.at[road_index, "constrained_length_m"] = constrained
        roads.at[road_index, "swsd_fallback_length_m"] = fallback
        roads.at[road_index, "high_precision_control_ratio"] = min(
            1.0, (observed + constrained) / total
        )
        roads.at[road_index, "swsd_fallback_ratio"] = min(1.0, fallback / total)
        roads.at[road_index, "support_state"] = support_state
        roads.at[road_index, "high_precision_claim_scope"] = (
            "none"
            if support_state == "sd_only"
            else "full_road_direct_observation"
            if support_state == "hp_supported"
            else "observed_and_constrained_full_road"
            if fallback <= 1e-9
            else "observed_and_constrained_intervals_only"
        )

        station_frame = result.fit_stations[
            result.fit_stations["v3_road_id"].astype(str) == road_id
        ].copy()
        if not station_frame.empty:
            station_frame["precoordination_direct_observation"] = station_frame[
                "direct_observation"
            ]
            for station_index, station in station_frame.iterrows():
                fraction = float(station["station_fraction"])
                station_frame.at[station_index, "geometry"] = geometry.interpolate(
                    fraction, normalized=True
                )
                adjusted_source = _coordination_source(fraction, adjustments)
                if adjusted_source is not None:
                    station_frame.at[station_index, "direct_observation"] = False
                    station_frame.at[station_index, "geometry_source"] = adjusted_source
                    station_frame.at[station_index, "reason_codes"] = ";".join(
                        value
                        for value in (
                            str(station.get("reason_codes", "")),
                            "published_endpoint_coordination",
                        )
                        if value
                    )
            station_frames.append(station_frame)

    segments = gpd.GeoDataFrame(segment_rows, geometry="geometry", crs=roads.crs)
    stations = _concat_frames(station_frames, result.fit_stations.crs)
    total = float(roads.geometry.length.sum())
    observed_total = float(roads["observed_length_m"].sum())
    constrained_total = float(roads["constrained_length_m"].sum())
    fallback_total = float(roads["swsd_fallback_length_m"].sum())
    evidence_roads = roads[roads["observed_length_m"] > 0]
    evidence_length = float(evidence_roads.geometry.length.sum())
    evidence_controlled = float(
        evidence_roads["observed_length_m"].sum()
        + evidence_roads["constrained_length_m"].sum()
    )
    summary = {
        "road_candidate_count": int(len(roads)),
        "support_state_counts": roads["support_state"].value_counts().to_dict(),
        "network_length_m": total,
        "observed_length_m": observed_total,
        "constrained_length_m": constrained_total,
        "swsd_fallback_length_m": fallback_total,
        "observed_ratio": observed_total / total if total else 0.0,
        "high_precision_control_ratio": (observed_total + constrained_total) / total
        if total
        else 0.0,
        "swsd_fallback_ratio": fallback_total / total if total else 0.0,
        "evidence_road_control_ratio": evidence_controlled / evidence_length
        if evidence_length
        else 0.0,
        "geometry_nonempty_count": int((~roads.geometry.is_empty).sum()),
        "geometry_valid_count": int(roads.geometry.is_valid.sum()),
        "geometry_simple_count": int(roads.geometry.is_simple.sum()),
        "endpoint_reconciled_road_count": int(
            sum(
                bool(_coordination_intervals(row, row.geometry.length, config))
                for _, row in roads.iterrows()
            )
        ),
    }
    return HighPrecisionGeometryResult(
        road_candidates=roads,
        center_observations=result.center_observations,
        control_spans=segments.copy(),
        geometry_segments=segments,
        fit_stations=stations,
        summary=summary,
    )


def _coordination_intervals(
    road: Any,
    length: float,
    config: HighPrecisionRoadV3Config,
) -> list[tuple[float, float, str]]:
    start_shift = float(road.get("start_endpoint_coordination_shift_m", 0.0) or 0.0)
    end_shift = float(road.get("end_endpoint_coordination_shift_m", 0.0) or 0.0)
    start_source = str(road.get("start_endpoint_source", "road_geometry_retained"))
    end_source = str(road.get("end_endpoint_source", "road_geometry_retained"))
    epsilon = config.physical_node_coordination_trigger_m
    if start_shift <= epsilon and end_shift <= epsilon:
        return []
    rows: list[tuple[float, float, str]] = []
    both = start_shift > epsilon and end_shift > epsilon
    cap_ratio = (
        config.endpoint_both_transition_cap_ratio
        if both
        else config.endpoint_single_transition_cap_ratio
    )
    for endpoint, shift, source in (
        ("s", start_shift, start_source),
        ("e", end_shift, end_source),
    ):
        if shift <= epsilon:
            continue
        required = 1.5 * shift / max(config.max_lateral_slope, 1e-6)
        transition = min(
            max(config.endpoint_transition_length_m, required),
            max(length * cap_ratio, 1e-9),
        )
        fraction = min(1.0, transition / max(length, 1e-9))
        geometry_source = (
            "hp_constrained_interpolation"
            if source == "physical_node_global_shared_portal"
            else "swsd_fallback"
        )
        rows.append(
            (0.0, fraction, geometry_source)
            if endpoint == "s"
            else (1.0 - fraction, 1.0, geometry_source)
        )
    return rows


def _coordination_source(
    fraction: float,
    intervals: list[tuple[float, float, str]],
) -> str | None:
    values = [source for start, end, source in intervals if start - 1e-9 <= fraction <= end + 1e-9]
    if "swsd_fallback" in values:
        return "swsd_fallback"
    if "hp_constrained_interpolation" in values:
        return "hp_constrained_interpolation"
    return None


def _concat_frames(
    frames: list[gpd.GeoDataFrame],
    crs: Any,
) -> gpd.GeoDataFrame:
    if not frames:
        return gpd.GeoDataFrame(columns=["geometry"], geometry="geometry", crs=crs)
    return gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True),
        geometry="geometry",
        crs=crs,
    )


_SOURCE_VALUES = (
    "hp_observed",
    "hp_constrained_interpolation",
    "swsd_fallback",
)


def _station_offsets(length: float, spacing: float) -> list[float]:
    if length <= 0:
        return [0.0]
    count = max(1, int(math.ceil(length / max(spacing, 0.1))))
    return [length * index / count for index in range(count + 1)]


def _station_observation(
    reference: LineString,
    station: float,
    members: gpd.GeoDataFrame,
    *,
    longitudinal_tolerance: float,
    max_distance: float,
) -> tuple[float, float, float, str, Point] | None:
    if members.empty:
        return None
    origin = reference.interpolate(station)
    tangent = _local_tangent(reference, station)
    normal = (-tangent[1], tangent[0])
    preferred = (
        members[members["center_anchor_member"].map(bool)]
        if "center_anchor_member" in members.columns
        else members.iloc[0:0]
    )
    values = _station_member_offsets(
        preferred,
        reference,
        origin,
        station,
        normal,
        longitudinal_tolerance,
        max_distance,
    )
    if not values:
        values = _station_member_offsets(
            members,
            reference,
            origin,
            station,
            normal,
            longitudinal_tolerance,
            max_distance,
        )
    if not values:
        return None
    offsets = [value[0] for value in values]
    offset = float(np.median(offsets))
    point = Point(origin.x + normal[0] * offset, origin.y + normal[1] * offset)
    return (
        offset,
        float(min(offsets)),
        float(max(offsets)),
        ";".join(sorted({value[1] for value in values if value[1]})),
        point,
    )


def _station_member_offsets(
    members: gpd.GeoDataFrame,
    reference: LineString,
    origin: Point,
    station: float,
    normal: tuple[float, float],
    longitudinal_tolerance: float,
    max_distance: float,
) -> list[tuple[float, str]]:
    values: list[tuple[float, str]] = []
    for row in members.itertuples(index=False):
        geometry = _line_geometry(row.geometry)
        nearest = geometry.interpolate(geometry.project(origin))
        projected_station = reference.project(nearest)
        if abs(projected_station - station) > longitudinal_tolerance:
            continue
        if origin.distance(nearest) > max_distance:
            continue
        offset = (
            (nearest.x - origin.x) * normal[0]
            + (nearest.y - origin.y) * normal[1]
        )
        values.append((float(offset), str(getattr(row, "lane_id", ""))))
    return values


def _fill_offsets(
    reference: LineString,
    stations: list[float],
    observed: list[float | None],
    drivezone: Any,
    *,
    config: HighPrecisionRoadV3Config,
) -> tuple[list[float], list[str], list[str]]:
    applied = [0.0 if value is None else float(value) for value in observed]
    sources = ["swsd_fallback" if value is None else "hp_observed" for value in observed]
    reasons = ["no_direct_center_observation" if value is None else "direct_lane_center_observation" for value in observed]
    observed_indices = [index for index, value in enumerate(observed) if value is not None]
    if not observed_indices:
        return applied, sources, reasons

    gap_runs = _missing_runs(observed)
    for start, end in gap_runs:
        left = start - 1 if start > 0 and observed[start - 1] is not None else None
        right = end + 1 if end + 1 < len(observed) and observed[end + 1] is not None else None
        candidate: dict[int, float] = {}
        kind = ""
        if left is not None and right is not None:
            kind = "bounded_interpolation"
            span = stations[right] - stations[left]
            for index in range(start, end + 1):
                ratio = (stations[index] - stations[left]) / span if span else 0.0
                candidate[index] = float(observed[left]) + ratio * (
                    float(observed[right]) - float(observed[left])
                )
        elif right is not None:
            kind = "constrained_leading_extension"
            for index in range(start, end + 1):
                candidate[index] = float(observed[right])
        elif left is not None:
            kind = "constrained_trailing_extension"
            for index in range(start, end + 1):
                candidate[index] = float(observed[left])
        if not candidate:
            continue
        points = [
            _shifted_point(reference, stations[index], value)
            for index, value in candidate.items()
        ]
        zone_pass = bool(points) and all(
            _point_in_zone(point, drivezone, config.drivezone_tolerance_m)
            for point in points
        )
        slope_pass = _candidate_slope_pass(
            stations, candidate, observed, left, right, config.max_lateral_slope
        )
        if not zone_pass or not slope_pass:
            reason = (
                "drivezone_constraint_failed"
                if not zone_pass
                else "lateral_slope_constraint_failed"
            )
            for index in range(start, end + 1):
                reasons[index] = reason
            continue
        for index, value in candidate.items():
            applied[index] = value
            sources[index] = "hp_constrained_interpolation"
            reasons[index] = kind
    return applied, sources, reasons


def _candidate_slope_pass(
    stations: list[float],
    candidate: dict[int, float],
    observed: list[float | None],
    left: int | None,
    right: int | None,
    maximum: float,
) -> bool:
    values = {index: value for index, value in candidate.items()}
    if left is not None:
        values[left] = float(observed[left])
    if right is not None:
        values[right] = float(observed[right])
    ordered = sorted(values)
    for first, second in zip(ordered, ordered[1:]):
        distance = stations[second] - stations[first]
        if distance <= 0:
            continue
        if abs(values[second] - values[first]) / distance > maximum:
            return False
    return True


def _smooth_offsets(
    stations: list[float],
    offsets: list[float],
    envelopes: list[tuple[float | None, float | None]],
    sources: list[str],
    *,
    config: HighPrecisionRoadV3Config,
) -> list[float]:
    values = np.asarray(offsets, dtype=float)
    fixed = np.asarray([source == "swsd_fallback" for source in sources], dtype=bool)
    kernel = np.asarray([1.0, 2.0, 3.0, 2.0, 1.0], dtype=float)
    kernel /= kernel.sum()
    for _ in range(max(0, int(config.smoothing_passes))):
        for start, end in _boolean_runs(~fixed):
            if end - start >= 3:
                padded = np.pad(values[start:end], (2, 2), mode="edge")
                values[start:end] = np.convolve(padded, kernel, mode="valid")
        values[fixed] = 0.0
    tolerance = config.lane_group_envelope_tolerance_m
    for _ in range(20):
        for index, envelope in enumerate(envelopes):
            lower, upper = envelope
            if lower is not None and upper is not None and not fixed[index]:
                values[index] = min(
                    max(values[index], float(lower) - tolerance),
                    float(upper) + tolerance,
                )
        values[fixed] = 0.0
        for index in range(1, len(values)):
            if fixed[index]:
                continue
            distance = max(float(stations[index] - stations[index - 1]), 0.0)
            limit = min(
                config.max_adjacent_lateral_shift_m,
                config.max_lateral_slope * distance,
            )
            values[index] = min(
                max(values[index], values[index - 1] - limit),
                values[index - 1] + limit,
            )
        values[fixed] = 0.0
        for index in range(len(values) - 2, -1, -1):
            if fixed[index]:
                continue
            distance = max(float(stations[index + 1] - stations[index]), 0.0)
            limit = min(
                config.max_adjacent_lateral_shift_m,
                config.max_lateral_slope * distance,
            )
            values[index] = min(
                max(values[index], values[index + 1] - limit),
                values[index + 1] + limit,
            )
        values[fixed] = 0.0
    return [float(value) for value in values]


def _boolean_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    rows: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(mask):
        if value and start is None:
            start = index
        if start is not None and (not value or index == len(mask) - 1):
            end = index + 1 if value and index == len(mask) - 1 else index
            rows.append((start, end))
            start = None
    return rows


def _enforce_slope(
    stations: list[float],
    offsets: list[float],
    sources: list[str],
    maximum: float,
) -> list[float]:
    values = list(offsets)
    for index in range(1, len(values)):
        distance = stations[index] - stations[index - 1]
        limit = maximum * distance
        delta = values[index] - values[index - 1]
        if abs(delta) > limit and sources[index] != "hp_observed":
            values[index] = values[index - 1] + math.copysign(limit, delta)
    for index in range(len(values) - 2, -1, -1):
        distance = stations[index + 1] - stations[index]
        limit = maximum * distance
        delta = values[index] - values[index + 1]
        if abs(delta) > limit and sources[index] != "hp_observed":
            values[index] = values[index + 1] + math.copysign(limit, delta)
    return values


def _missing_runs(values: list[float | None]) -> list[tuple[int, int]]:
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, value in enumerate(values):
        if value is None and start is None:
            start = index
        if value is not None and start is not None:
            runs.append((start, index - 1))
            start = None
    if start is not None:
        runs.append((start, len(values) - 1))
    return runs


def _source_runs(
    stations: list[float],
    sources: list[str],
    reasons: list[str],
    reference_length: float,
) -> list[dict[str, Any]]:
    if len(stations) == 1:
        return [
            {
                "start_fraction": 0.0,
                "end_fraction": 1.0,
                "geometry_source": sources[0],
                "control_kind": _control_kind(sources[0], reasons[0]),
                "reason_codes": reasons[0],
            }
        ]
    boundaries = [0.0]
    boundaries.extend(
        (stations[index] + stations[index + 1]) / 2.0
        for index in range(len(stations) - 1)
    )
    boundaries.append(reference_length)
    rows: list[dict[str, Any]] = []
    start_index = 0
    for index in range(1, len(sources) + 1):
        if index < len(sources) and sources[index] == sources[start_index] and reasons[index] == reasons[start_index]:
            continue
        rows.append(
            {
                "start_fraction": boundaries[start_index] / reference_length
                if reference_length
                else 0.0,
                "end_fraction": boundaries[index] / reference_length
                if reference_length
                else 1.0,
                "geometry_source": sources[start_index],
                "control_kind": _control_kind(sources[start_index], reasons[start_index]),
                "reason_codes": reasons[start_index],
            }
        )
        start_index = index
    return rows


def _control_kind(source: str, reason: str) -> str:
    if source == "hp_observed":
        return "observed"
    if source == "hp_constrained_interpolation":
        return reason
    return "fallback"


def _shifted_point(reference: LineString, station: float, offset: float) -> Point:
    origin = reference.interpolate(station)
    tangent = _local_tangent(reference, station)
    normal = (-tangent[1], tangent[0])
    return Point(origin.x + normal[0] * offset, origin.y + normal[1] * offset)


def _local_tangent(line: LineString, station: float) -> tuple[float, float]:
    delta = min(1.0, max(line.length / 100.0, 0.1))
    start = line.interpolate(max(0.0, station - delta))
    end = line.interpolate(min(line.length, station + delta))
    dx, dy = end.x - start.x, end.y - start.y
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length else (1.0, 0.0)


def _point_in_zone(point: Point, drivezone: Any, tolerance: float) -> bool:
    if drivezone is None or drivezone.is_empty:
        return False
    return bool(drivezone.covers(point) or point.distance(drivezone) <= tolerance)


def _line_geometry(geometry: Any) -> LineString:
    if geometry.geom_type == "LineString":
        return geometry
    if geometry.geom_type == "MultiLineString":
        return max(geometry.geoms, key=lambda item: item.length)
    raise ValueError(f"expected line geometry, got {geometry.geom_type}")


def _frame(rows: list[dict[str, Any]], crs: Any, id_column: str) -> gpd.GeoDataFrame:
    if rows:
        return gpd.GeoDataFrame(rows, geometry="geometry", crs=crs)
    return gpd.GeoDataFrame(
        {id_column: [], "geometry": []}, geometry="geometry", crs=crs
    )


__all__ = [
    "HighPrecisionGeometryResult",
    "instantiate_high_precision_geometries",
    "reconcile_final_road_geometries",
]
