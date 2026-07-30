from __future__ import annotations

from dataclasses import dataclass
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import (
    distance as geometry_distance,
    get_x,
    get_y,
    line_interpolate_point,
    line_locate_point,
)
from shapely.geometry import LineString, Point
from shapely.ops import substring

from .segment_first_skeleton import canonical_id, parse_id_list


@dataclass(frozen=True)
class TargetFragmentResult:
    assignments: gpd.GeoDataFrame
    audit: gpd.GeoDataFrame
    summary: dict[str, object]


def build_target_carrier_fragments(
    centers: gpd.GeoDataFrame,
    baseline_assignments: gpd.GeoDataFrame,
    target_segments: gpd.GeoDataFrame,
    target_anchors: gpd.GeoDataFrame,
    swsd_roads: gpd.GeoDataFrame,
    *,
    sample_spacing_m: float,
    max_distance_m: float,
    max_angle_deg: float,
    run_id: str,
) -> TargetFragmentResult:
    required = target_segments[
        target_segments["target_required"].fillna(False).astype(bool)
    ].copy()
    if required.empty:
        return TargetFragmentResult(
            baseline_assignments.copy(),
            _empty_audit(centers.crs),
            _summary(False, 0, 0, 0, 0),
        )

    member_frame = swsd_roads.copy()
    member_frame["canonical_road_id"] = member_frame["id"].map(canonical_id)
    member_frame["canonical_segment_id"] = member_frame["segmentid"].map(
        canonical_id
    )
    target_ids = set(required["segment_id"].map(canonical_id))
    member_frame = member_frame[
        member_frame["canonical_segment_id"].isin(target_ids)
    ].copy()
    members_by_segment = {
        segment_id: group.copy()
        for segment_id, group in member_frame.groupby("canonical_segment_id")
    }
    axes = _target_axes(required, target_anchors, member_frame)
    if axes.empty:
        return TargetFragmentResult(
            baseline_assignments.copy(),
            _empty_audit(centers.crs),
            _summary(False, 0, 0, 0, 0),
        )

    spacing = max(1.0, float(sample_spacing_m))
    fragments: list[dict[str, object]] = []
    axes_sindex = axes.sindex
    for center in centers.itertuples(index=False):
        if center.geometry is None or center.geometry.is_empty:
            continue
        axis_indexes = list(axes_sindex.query(center.geometry.buffer(max_distance_m)))
        if not axis_indexes:
            continue
        candidates = axes.iloc[axis_indexes].copy()
        labels = _station_labels(
            center.geometry,
            candidates,
            members_by_segment,
            spacing=spacing,
            max_distance_m=max_distance_m,
            max_angle_deg=max_angle_deg,
        )
        for fragment_index, fragment in enumerate(
            _labelled_fragments(center.geometry, labels, minimum_length_m=spacing * 2.0)
        ):
            row = center._asdict()
            row.update(
                {
                    "run_id": run_id,
                    "assigned_segment_id": fragment["segment_id"],
                    "target_swsd_road_id": fragment["member_id"],
                    "assignment_fragment_id": (
                        f"{center.patch_road_key}@{fragment['segment_id']}"
                        f"@{fragment['member_id']}@{fragment_index}"
                    ),
                    "assignment_distance_m": fragment["distance_m"],
                    "assignment_angle_deg": fragment["angle_deg"],
                    "assignment_score": fragment["score"],
                    "assignment_margin": fragment["margin"],
                    "carrier_role": "directional_corridor",
                    "takeover_eligible": True,
                    "assignment_state": "target_segment_fragmented",
                    "assignment_source": "target_segment_fragment",
                    "target_anchor_source": fragment["anchor_source"],
                    "reason_codes": "patch_geometry_partitioned_by_target_segment",
                    "geometry": fragment["geometry"],
                }
            )
            fragments.append(row)

    if not fragments:
        return TargetFragmentResult(
            baseline_assignments.copy(),
            _empty_audit(centers.crs),
            _summary(True, 0, 0, 0, 0),
        )
    fragment_frame = gpd.GeoDataFrame(
        fragments,
        geometry="geometry",
        crs=centers.crs,
    )
    covered_segments = set(fragment_frame["assigned_segment_id"].astype(str))
    baseline_segment = baseline_assignments["assigned_segment_id"].map(canonical_id)
    keep_baseline = (
        ~baseline_segment.isin(covered_segments)
        | baseline_assignments["carrier_role"].eq("local_connector")
    )
    combined = gpd.GeoDataFrame(
        pd.concat(
            [baseline_assignments.loc[keep_baseline].copy(), fragment_frame],
            ignore_index=True,
        ),
        geometry="geometry",
        crs=centers.crs,
    )
    combined = combined.sort_values(
        ["assigned_segment_id", "patch_road_key", "target_swsd_road_id"],
        kind="stable",
    ).reset_index(drop=True)
    audit = fragment_frame.copy()
    patch_target_counts = fragment_frame.groupby("patch_road_key")[
        "assigned_segment_id"
    ].nunique()
    summary = _summary(
        True,
        int(len(fragment_frame)),
        int(fragment_frame["patch_road_key"].nunique()),
        int(fragment_frame["assigned_segment_id"].nunique()),
        int((patch_target_counts > 1).sum()),
    )
    return TargetFragmentResult(combined, audit, summary)


def _target_axes(
    required: gpd.GeoDataFrame,
    target_anchors: gpd.GeoDataFrame,
    members: gpd.GeoDataFrame,
) -> gpd.GeoDataFrame:
    rows: list[dict[str, object]] = []
    required_ids = set(required["segment_id"].map(canonical_id))
    if not target_anchors.empty:
        for anchor in target_anchors.explode(index_parts=False).itertuples(index=False):
            segment_id = canonical_id(anchor.segment_id)
            if segment_id not in required_ids or anchor.geometry.geom_type != "LineString":
                continue
            rows.append(
                {
                    "segment_id": segment_id,
                    "member_id": "",
                    "anchor_source": str(anchor.anchor_source),
                    "source_priority": 0,
                    "geometry": anchor.geometry,
                }
            )
    for member in members.itertuples(index=False):
        rows.append(
            {
                "segment_id": str(member.canonical_segment_id),
                "member_id": str(member.canonical_road_id),
                "anchor_source": "swsd_semantic_axis",
                "source_priority": 1,
                "geometry": member.geometry,
            }
        )
    return gpd.GeoDataFrame(rows, geometry="geometry", crs=required.crs)


def _station_labels(
    geometry: LineString,
    candidates: gpd.GeoDataFrame,
    members_by_segment: dict[str, gpd.GeoDataFrame],
    *,
    spacing: float,
    max_distance_m: float,
    max_angle_deg: float,
) -> list[dict[str, object]]:
    count = max(2, int(math.ceil(float(geometry.length) / spacing)) + 1)
    measures = np.linspace(0.0, float(geometry.length), count)
    axis_rows = list(candidates.itertuples(index=False))
    axis_geometries = np.asarray(
        [axis.geometry for axis in axis_rows],
        dtype=object,
    )
    axis_deltas = np.asarray(
        [_bearing_delta(axis.geometry) for axis in axis_rows],
        dtype=float,
    )
    axis_lengths = np.asarray(
        [float(axis.geometry.length) for axis in axis_rows],
        dtype=float,
    )
    labels: list[dict[str, object]] = []
    for measure in measures:
        point = geometry.interpolate(float(measure))
        source_bearing = _local_bearing(geometry, float(measure))
        segment_candidates: dict[str, tuple[float, float, float, pd.Series]] = {}
        distances = geometry_distance(axis_geometries, point)
        target_metrics = {
            axis.geometry: (float(distances[index]), None)
            for index, axis in enumerate(axis_rows)
        }
        eligible_indexes = np.flatnonzero(distances <= max_distance_m)
        eligible_geometries = axis_geometries[eligible_indexes]
        target_measures = line_locate_point(eligible_geometries, point)
        target_deltas = axis_deltas[eligible_indexes]
        target_starts = line_interpolate_point(
            eligible_geometries,
            np.maximum(0.0, target_measures - target_deltas),
        )
        target_ends = line_interpolate_point(
            eligible_geometries,
            np.minimum(
                axis_lengths[eligible_indexes],
                target_measures + target_deltas,
            ),
        )
        target_bearings = [
            math.degrees(
                math.atan2(
                    float(get_y(end) - get_y(start)),
                    float(get_x(end) - get_x(start)),
                )
            )
            % 180.0
            for start, end in zip(target_starts, target_ends)
        ]
        for position, axis_index in enumerate(eligible_indexes):
            axis = axis_rows[int(axis_index)]
            distance = float(distances[int(axis_index)])
            difference = abs(source_bearing - target_bearings[position]) % 180.0
            angle = min(difference, 180.0 - difference)
            target_metrics[axis.geometry] = (distance, angle)
            if angle > max_angle_deg:
                continue
            score = distance + angle * 0.08 + float(axis.source_priority) * 0.25
            segment_id = str(axis.segment_id)
            item = (score, distance, angle, axis)
            current = segment_candidates.get(segment_id)
            if current is None or item[:3] < current[:3]:
                segment_candidates[segment_id] = item
        if not segment_candidates:
            labels.append({"measure": float(measure), "label": None})
            continue
        ordered = sorted(
            (score, distance, angle, segment_id, axis)
            for segment_id, (score, distance, angle, axis) in segment_candidates.items()
        )
        best = ordered[0]
        member_id = _station_member(
            point,
            source_bearing,
            members_by_segment.get(best[3]),
            target_metrics,
        )
        if not member_id:
            labels.append({"measure": float(measure), "label": None})
            continue
        margin = ordered[1][0] - best[0] if len(ordered) > 1 else None
        labels.append(
            {
                "measure": float(measure),
                "label": (best[3], member_id),
                "segment_id": best[3],
                "member_id": member_id,
                "distance_m": best[1],
                "angle_deg": best[2],
                "score": best[0],
                "margin": margin,
                "anchor_source": str(best[4].anchor_source),
            }
        )
    return labels


def _station_member(
    point: Point,
    source_bearing: float,
    members: gpd.GeoDataFrame | None,
    target_metrics: dict[object, tuple[float, float | None]],
) -> str:
    if members is None or members.empty:
        return ""
    member_rows = list(members.itertuples(index=False))
    metrics: list[tuple[float, float | None]] = []
    for member in member_rows:
        metric = target_metrics.get(member.geometry)
        if metric is None:
            metric = float(point.distance(member.geometry)), None
        metrics.append(metric)
    nearest_index = min(
        range(len(member_rows)),
        key=lambda index: metrics[index][0],
    )
    nearest = member_rows[nearest_index]
    distance, angle = metrics[nearest_index]
    if angle is None:
        angle = _target_angle(point, source_bearing, nearest.geometry)
    best = (
        distance + angle * 0.08,
        distance,
        angle,
        nearest.canonical_road_id,
    )
    for index, member in enumerate(member_rows):
        if index == nearest_index:
            continue
        distance, angle = metrics[index]
        if distance > best[0]:
            continue
        if angle is None:
            angle = _target_angle(point, source_bearing, member.geometry)
        candidate = (
            (distance + angle * 0.08, distance, angle, member.canonical_road_id)
        )
        if candidate < best:
            best = candidate
    return str(best[3])


def _labelled_fragments(
    geometry: LineString,
    labels: list[dict[str, object]],
    *,
    minimum_length_m: float,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    start = 0
    while start < len(labels):
        label = labels[start]["label"]
        end = start
        while end + 1 < len(labels) and labels[end + 1]["label"] == label:
            end += 1
        if label is not None:
            start_measure = (
                0.0
                if start == 0
                else (float(labels[start - 1]["measure"]) + float(labels[start]["measure"]))
                / 2.0
            )
            end_measure = (
                float(geometry.length)
                if end == len(labels) - 1
                else (float(labels[end]["measure"]) + float(labels[end + 1]["measure"]))
                / 2.0
            )
            part = substring(geometry, start_measure, end_measure)
            if part.geom_type == "LineString" and part.length >= minimum_length_m:
                group = labels[start : end + 1]
                margins = [float(row["margin"]) for row in group if row.get("margin") is not None]
                rows.append(
                    {
                        "segment_id": label[0],
                        "member_id": label[1],
                        "distance_m": float(np.median([row["distance_m"] for row in group])),
                        "angle_deg": float(np.median([row["angle_deg"] for row in group])),
                        "score": float(np.median([row["score"] for row in group])),
                        "margin": float(np.median(margins)) if margins else None,
                        "anchor_source": _mode([str(row["anchor_source"]) for row in group]),
                        "geometry": part,
                    }
                )
        start = end + 1
    return rows


def _station_angle(source: LineString, measure: float, target: LineString) -> float:
    source_bearing = _local_bearing(source, measure)
    point = source.interpolate(measure)
    return _target_angle(point, source_bearing, target)


def _target_angle(
    point: Point,
    source_bearing: float,
    target: LineString,
) -> float:
    target_measure = float(target.project(point))
    target_bearing = _local_bearing(target, target_measure)
    difference = abs(source_bearing - target_bearing) % 180.0
    return min(difference, 180.0 - difference)


def _local_bearing(line: LineString, measure: float) -> float:
    delta = _bearing_delta(line)
    start = line.interpolate(max(0.0, measure - delta))
    end = line.interpolate(min(float(line.length), measure + delta))
    return math.degrees(math.atan2(end.y - start.y, end.x - start.x)) % 180.0


def _bearing_delta(line: LineString) -> float:
    return min(5.0, max(0.5, float(line.length) * 0.02))


def _mode(values: list[str]) -> str:
    return min(set(values), key=lambda value: (-values.count(value), value))


def _empty_audit(crs: object) -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {
            "run_id": pd.Series(dtype=str),
            "patch_road_key": pd.Series(dtype=str),
            "assigned_segment_id": pd.Series(dtype=str),
            "target_swsd_road_id": pd.Series(dtype=str),
            "assignment_fragment_id": pd.Series(dtype=str),
            "assignment_source": pd.Series(dtype=str),
            "geometry": gpd.GeoSeries([], crs=crs),
        },
        geometry="geometry",
        crs=crs,
    )


def _summary(
    enabled: bool,
    fragment_count: int,
    patch_road_count: int,
    segment_count: int,
    multi_target_count: int,
) -> dict[str, object]:
    return {
        "fragmentation_enabled": enabled,
        "fragment_count": fragment_count,
        "fragmented_patch_road_count": patch_road_count,
        "covered_target_segment_count": segment_count,
        "multi_target_patch_road_count": multi_target_count,
    }


__all__ = ["TargetFragmentResult", "build_target_carrier_fragments"]
