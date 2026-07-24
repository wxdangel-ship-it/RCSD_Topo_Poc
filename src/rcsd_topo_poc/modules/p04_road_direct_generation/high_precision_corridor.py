from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point
from shapely.ops import linemerge, unary_union

from .geometry import canonical_id
from .high_precision_config import HighPrecisionRoadV3Config


@dataclass(frozen=True)
class HighPrecisionCorridorResult:
    road_units: gpd.GeoDataFrame
    lane_group_members: gpd.GeoDataFrame
    center_anchors: gpd.GeoDataFrame
    corridor_decisions: gpd.GeoDataFrame
    summary: dict[str, Any]


def build_high_precision_corridors(
    parent_roads: gpd.GeoDataFrame,
    lane_segments: gpd.GeoDataFrame,
    lane_boundaries: gpd.GeoDataFrame,
    *,
    config: HighPrecisionRoadV3Config,
) -> HighPrecisionCorridorResult:
    roads = parent_roads.copy().reset_index(drop=True)
    roads["swsd_unit_id"] = roads["swsd_unit_id"].map(canonical_id)
    parent_by_id = roads.set_index("swsd_unit_id", drop=False)

    segments = lane_segments.copy().reset_index(drop=True)
    segments["lane_id"] = segments["lane_id"].map(canonical_id)
    segments["swsd_unit_id"] = segments["swsd_unit_id"].map(canonical_id)
    segments = segments[segments["swsd_unit_id"].isin(parent_by_id.index)].copy()
    segments["travel_side"] = segments.apply(
        lambda row: _travel_side(
            row.geometry, parent_by_id.loc[row.swsd_unit_id].geometry
        ),
        axis=1,
    )
    segments["hard_geometry_eligible"] = (
        segments["evidence_quality_state"].astype(str)
        == config.hard_evidence_quality_state
    )

    decisions: list[dict[str, Any]] = []
    unit_rows: list[dict[str, Any]] = []
    member_frames: list[gpd.GeoDataFrame] = []
    anchor_rows: list[dict[str, Any]] = []

    for road in roads.itertuples(index=False):
        parent_id = str(road.swsd_unit_id)
        parent_geometry = _line_geometry(road.geometry)
        group = segments[segments["swsd_unit_id"] == parent_id].copy()
        hard = group[group["hard_geometry_eligible"]].copy()
        by_side = {
            side: hard[hard["travel_side"] == side].copy()
            for side in ("forward", "reverse")
        }
        anchors = {
            side: _stable_side_anchor(frame, parent_geometry)
            for side, frame in by_side.items()
            if not frame.empty
        }
        coverage = {
            side: _longitudinal_coverage(frame, parent_geometry)
            for side, frame in by_side.items()
        }
        both_sides = set(anchors) == {"forward", "reverse"}
        shared_coverage = min(coverage.values()) if both_sides else 0.0
        separation = (
            _symmetric_distance(
                anchors["forward"]["geometry"],
                anchors["reverse"]["geometry"],
                config.cross_direction_sample_spacing_m,
            )
            if both_sides
            else math.nan
        )
        lane_width = _median_lane_width(hard)
        required = max(
            config.cross_direction_min_absolute_separation_m,
            config.cross_direction_min_lane_width_ratio * lane_width
            if lane_width is not None
            else config.cross_direction_min_absolute_separation_m,
        )
        original_direction = _coerce_int(getattr(road, "direction", None))
        bidirectional = original_direction in {0, 1}
        separation_pass = bool(both_sides and separation >= required)
        continuity_pass = bool(
            both_sides
            and shared_coverage >= config.physical_split_min_shared_coverage_ratio
        )
        split = bool(bidirectional and separation_pass and continuity_pass)
        if not hard.empty:
            decision = "split" if split else "shared"
        else:
            decision = "fallback"
        reasons = _decision_reasons(
            bidirectional=bidirectional,
            hard_empty=hard.empty,
            both_sides=both_sides,
            separation_pass=separation_pass,
            continuity_pass=continuity_pass,
            split=split,
        )
        decision_geometry = (
            unary_union([value["geometry"] for value in anchors.values()])
            if anchors
            else parent_geometry
        )
        decisions.append(
            {
                "run_id": config.run_id,
                "parent_swsd_unit_id": parent_id,
                "forward_usable": not by_side["forward"].empty,
                "reverse_usable": not by_side["reverse"].empty,
                "forward_anchor_id": anchors.get("forward", {}).get("anchor_source_id", ""),
                "reverse_anchor_id": anchors.get("reverse", {}).get("anchor_source_id", ""),
                "shared_longitudinal_coverage_ratio": shared_coverage,
                "anchor_median_separation_m": separation,
                "reference_lane_width_m": lane_width,
                "required_min_separation_m": required,
                "separation_gate_pass": separation_pass,
                "continuity_gate_pass": continuity_pass,
                "decision": decision,
                "reason_codes": ";".join(reasons),
                "geometry": decision_geometry,
            }
        )

        if split:
            sides = ("forward", "reverse")
        elif original_direction == 3 and not hard.empty:
            sides = ("reverse",)
        elif original_direction == 2 and not hard.empty:
            sides = ("forward",)
        else:
            sides = ("shared",)

        base = {
            key: value
            for key, value in road._asdict().items()
            if key != "geometry" and not key.startswith("_")
        }
        for side in sides:
            v3_id = parent_id if side == "shared" else f"{parent_id}:{side}"
            representation = (
                "sd_fallback"
                if hard.empty
                else "directional_carriageway"
                if split
                else "shared_physical"
            )
            reverse = side == "reverse"
            source_node = (
                _endpoint(base, "enode_id", "enodeid")
                if reverse
                else _endpoint(base, "snode_id", "snodeid")
            )
            target_node = (
                _endpoint(base, "snode_id", "snodeid")
                if reverse
                else _endpoint(base, "enode_id", "enodeid")
            )
            if split:
                # A physical carriageway split must not reuse the parent SWSD
                # physical-node key.  Reusing it makes the endpoint coordinator
                # translate both separated carriageways back onto one centerline.
                # Semantic junction ownership remains in semantic_*node_id.
                source_node = f"{source_node}:corridor:{side}"
                target_node = f"{target_node}:corridor:{side}"
            unit_rows.append(
                {
                    **base,
                    "run_id": config.run_id,
                    "v3_road_id": v3_id,
                    "parent_swsd_unit_id": parent_id,
                    "road_representation": representation,
                    "travel_side": side,
                    "split_decision": decision,
                    "split_reason_codes": ";".join(reasons),
                    "direction": 2 if split else original_direction,
                    "snode_id": source_node,
                    "enode_id": target_node,
                    "geometry": LineString(list(parent_geometry.coords)[::-1])
                    if reverse
                    else parent_geometry,
                }
            )
            members = (
                group[group["travel_side"] == side].copy()
                if split or side in {"forward", "reverse"}
                else group.copy()
            )
            if not members.empty:
                members["v3_road_id"] = v3_id
                members["parent_swsd_unit_id"] = parent_id
                members["geometry_role"] = np.where(
                    members["hard_geometry_eligible"],
                    "hard_geometry",
                    "review_only",
                )
            hard_members = members[members["hard_geometry_eligible"]]
            if not hard_members.empty:
                anchor = (
                    anchors[side]
                    if side in anchors
                    else _stable_shared_anchor(hard_members, parent_geometry)
                )
                members["center_anchor_member"] = (
                    members["lane_id"].astype(str)
                    == str(anchor["anchor_source_id"])
                )
                anchor_rows.append(
                    {
                        "run_id": config.run_id,
                        "v3_road_id": v3_id,
                        "parent_swsd_unit_id": parent_id,
                        "travel_side": side,
                        **anchor,
                    }
                )
            elif not members.empty:
                members["center_anchor_member"] = False
            if not members.empty:
                member_frames.append(members)

    road_units = gpd.GeoDataFrame(unit_rows, geometry="geometry", crs=roads.crs)
    corridor_decisions = gpd.GeoDataFrame(
        decisions, geometry="geometry", crs=roads.crs
    )
    center_anchors = gpd.GeoDataFrame(
        anchor_rows,
        geometry="geometry",
        crs=roads.crs,
        columns=(
            None
            if anchor_rows
            else [
                "run_id",
                "v3_road_id",
                "parent_swsd_unit_id",
                "travel_side",
                "anchor_kind",
                "anchor_source_id",
                "anchor_lane_count",
                "selection_reason",
                "geometry",
            ]
        ),
    )
    lane_group_members = _concat_geodataframes(member_frames, segments.crs)
    summary = {
        "parent_road_count": int(len(roads)),
        "road_unit_count": int(len(road_units)),
        "split_parent_count": int((corridor_decisions["decision"] == "split").sum()),
        "shared_parent_count": int((corridor_decisions["decision"] == "shared").sum()),
        "fallback_parent_count": int((corridor_decisions["decision"] == "fallback").sum()),
        "automatic_bidirectional_split_count": 0,
        "duplicate_parent_semantic_count": int(
            road_units.groupby("parent_swsd_unit_id").size().gt(2).sum()
        ),
    }
    return HighPrecisionCorridorResult(
        road_units=road_units,
        lane_group_members=lane_group_members,
        center_anchors=center_anchors,
        corridor_decisions=corridor_decisions,
        summary=summary,
    )


def _stable_side_anchor(frame: gpd.GeoDataFrame, parent: LineString) -> dict[str, Any]:
    candidates = _lane_candidates(frame, parent)
    candidates.sort(
        key=lambda item: (
            abs(item["lateral_rank"] - (len(candidates) - 1) / 2.0),
            -item["coverage_ratio"],
            item["curvature_instability"],
            item["lane_id"],
        )
    )
    chosen = candidates[0]
    return {
        "anchor_kind": "stable_lane",
        "anchor_source_id": chosen["lane_id"],
        "anchor_lane_count": len(candidates),
        "selection_reason": "stable_directional_center_lane",
        "geometry": chosen["geometry"],
    }


def _stable_shared_anchor(frame: gpd.GeoDataFrame, parent: LineString) -> dict[str, Any]:
    candidates = _lane_candidates(frame, parent)
    median_offset = float(np.median([item["median_offset"] for item in candidates]))
    chosen = min(
        candidates,
        key=lambda item: (
            abs(item["median_offset"] - median_offset),
            -item["coverage_ratio"],
            item["curvature_instability"],
            item["lane_id"],
        ),
    )
    return {
        "anchor_kind": "robust_shared_lane_center",
        "anchor_source_id": chosen["lane_id"],
        "anchor_lane_count": len(candidates),
        "selection_reason": "closest_lane_to_robust_cross_direction_center",
        "geometry": chosen["geometry"],
    }


def _lane_candidates(frame: gpd.GeoDataFrame, parent: LineString) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for lane_id, lane_frame in frame.groupby("lane_id"):
        geometry = _merge_lines(lane_frame.geometry)
        values.append(
            {
                "lane_id": str(lane_id),
                "coverage_ratio": _longitudinal_coverage(lane_frame, parent),
                "median_offset": _median_offset(parent, geometry),
                "curvature_instability": _curvature_instability(geometry),
                "geometry": geometry,
            }
        )
    for rank, item in enumerate(sorted(values, key=lambda value: value["median_offset"])):
        item["lateral_rank"] = rank
    return values


def _decision_reasons(
    *,
    bidirectional: bool,
    hard_empty: bool,
    both_sides: bool,
    separation_pass: bool,
    continuity_pass: bool,
    split: bool,
) -> list[str]:
    if hard_empty:
        return ["no_usable_high_precision_evidence"]
    if not bidirectional:
        return ["single_direction_parent_retained"]
    if split:
        return ["two_distinct_physical_directional_corridors"]
    reasons = ["single_physical_corridor_retained"]
    if not both_sides:
        reasons.append("one_sided_or_missing_direction_evidence")
    if both_sides and not separation_pass:
        reasons.append("cross_direction_separation_gate_failed")
    if both_sides and not continuity_pass:
        reasons.append("cross_direction_continuity_gate_failed")
    return reasons


def _longitudinal_coverage(frame: gpd.GeoDataFrame, parent: LineString) -> float:
    if frame.empty or parent.length <= 0:
        return 0.0
    intervals: list[tuple[float, float]] = []
    for geometry in frame.geometry:
        line = _line_geometry(geometry)
        positions = [parent.project(Point(line.coords[0])), parent.project(Point(line.coords[-1]))]
        intervals.append((min(positions), max(positions)))
    intervals.sort()
    merged: list[list[float]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return min(1.0, sum(end - start for start, end in merged) / parent.length)


def _symmetric_distance(first: Any, second: Any, spacing: float) -> float:
    samples = _sample_line(first, spacing) + _sample_line(second, spacing)
    distances = [
        point.distance(second if index < len(samples) / 2 else first)
        for index, point in enumerate(samples)
    ]
    return float(np.median(distances)) if distances else math.nan


def _sample_line(geometry: Any, spacing: float) -> list[Point]:
    line = _line_geometry(geometry)
    count = max(2, int(math.ceil(line.length / max(spacing, 0.1))) + 1)
    return [line.interpolate(index / (count - 1), normalized=True) for index in range(count)]


def _median_lane_width(frame: gpd.GeoDataFrame) -> float | None:
    values: list[float] = []
    for column in ("width_median_m", "inferred_lane_width_m"):
        if column not in frame.columns:
            continue
        for value in pd.to_numeric(frame[column], errors="coerce"):
            if math.isfinite(value) and value > 0:
                values.append(float(value))
    return float(np.median(values)) if values else None


def _travel_side(line: Any, reference: Any) -> str:
    lane = _line_geometry(line)
    road = _line_geometry(reference)
    start = Point(lane.coords[0])
    end = Point(lane.coords[-1])
    start_offset = road.project(start)
    end_offset = road.project(end)
    if not math.isclose(start_offset, end_offset, abs_tol=0.01):
        return "forward" if end_offset > start_offset else "reverse"
    lane_tangent = _local_tangent(lane, lane.length / 2.0)
    road_tangent = _local_tangent(road, road.length / 2.0)
    return (
        "forward"
        if lane_tangent[0] * road_tangent[0] + lane_tangent[1] * road_tangent[1]
        >= 0
        else "reverse"
    )


def _median_offset(parent: LineString, geometry: Any) -> float:
    values: list[float] = []
    for point in _sample_line(geometry, 10.0):
        station = parent.project(point)
        origin = parent.interpolate(station)
        tangent = _local_tangent(parent, station)
        normal = (-tangent[1], tangent[0])
        values.append((point.x - origin.x) * normal[0] + (point.y - origin.y) * normal[1])
    return float(np.median(values)) if values else 0.0


def _local_tangent(line: LineString, station: float) -> tuple[float, float]:
    delta = min(1.0, max(line.length / 100.0, 0.1))
    start = line.interpolate(max(0.0, station - delta))
    end = line.interpolate(min(line.length, station + delta))
    dx, dy = end.x - start.x, end.y - start.y
    length = math.hypot(dx, dy)
    return (dx / length, dy / length) if length else (1.0, 0.0)


def _curvature_instability(geometry: Any) -> float:
    coords = list(_line_geometry(geometry).coords)
    if len(coords) < 3:
        return 0.0
    changes: list[float] = []
    for first, middle, last in zip(coords, coords[1:], coords[2:]):
        a = math.atan2(middle[1] - first[1], middle[0] - first[0])
        b = math.atan2(last[1] - middle[1], last[0] - middle[0])
        changes.append(abs(math.atan2(math.sin(b - a), math.cos(b - a))))
    return float(np.mean(changes)) if changes else 0.0


def _merge_lines(geometries: Iterable[Any]) -> LineString:
    combined = unary_union(
        [geometry for geometry in geometries if geometry is not None]
    )
    if combined.geom_type == "LineString":
        return combined
    merged = linemerge(combined)
    return _line_geometry(merged)


def _line_geometry(geometry: Any) -> LineString:
    if geometry is None or geometry.is_empty:
        raise ValueError("line geometry is empty")
    if geometry.geom_type == "LineString":
        return geometry
    if geometry.geom_type == "MultiLineString":
        merged = linemerge(geometry)
        if merged.geom_type == "LineString":
            return merged
        return max(merged.geoms, key=lambda item: item.length)
    raise ValueError(f"expected line geometry, got {geometry.geom_type}")


def _endpoint(values: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = values.get(name)
        if value is not None and not (isinstance(value, float) and math.isnan(value)):
            return value
    return None


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _concat_geodataframes(
    frames: list[gpd.GeoDataFrame], crs: Any
) -> gpd.GeoDataFrame:
    if not frames:
        return gpd.GeoDataFrame(
            {"v3_road_id": [], "geometry": []}, geometry="geometry", crs=crs
        )
    return gpd.GeoDataFrame(
        pd.concat(frames, ignore_index=True), geometry="geometry", crs=crs
    )


__all__ = ["HighPrecisionCorridorResult", "build_high_precision_corridors"]
