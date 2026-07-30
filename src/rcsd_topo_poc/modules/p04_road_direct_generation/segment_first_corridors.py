from __future__ import annotations

from dataclasses import dataclass
import json
import math

import geopandas as gpd
import numpy as np
from shapely import (
    get_x,
    get_y,
    line_interpolate_point,
    line_locate_point,
)
from shapely.geometry import LineString


@dataclass(frozen=True)
class CorridorAssembly:
    geometry: LineString
    direction_role: str
    observed_coverage_ratio: float
    completion_fraction: float
    source_patch_road_keys: tuple[str, ...]
    start_patch_road_keys: tuple[str, ...]
    end_patch_road_keys: tuple[str, ...]
    source_patch_ids: tuple[str, ...]
    source_lane_ids: tuple[str, ...]
    evidence_spans_json: str
    assembly_state: str


def evidence_direction_role(geometry: LineString, reference: LineString) -> str:
    """Classify travel orientation while using SWSD only as a semantic station axis."""
    start = geometry.interpolate(0.10, normalized=True)
    end = geometry.interpolate(0.90, normalized=True)
    delta = float(reference.project(end) - reference.project(start))
    if abs(delta) <= 1e-6:
        delta = float(
            reference.project(geometry.interpolate(1.0, normalized=True))
            - reference.project(geometry.interpolate(0.0, normalized=True))
        )
    return "forward" if delta >= 0.0 else "reverse"


def assemble_directional_corridor(
    evidence: gpd.GeoDataFrame,
    reference: LineString,
    *,
    direction_role: str,
    drivezone_surface: object | None,
    minimum_coverage: float,
    sample_spacing_m: float,
    completion_min_coverage: float,
) -> CorridorAssembly | None:
    """Build one physical Road corridor from Patch observations of one role.

    SWSD supplies ordering and direction only. Every output coordinate is a Patch
    observation or a connector between observed coordinates inside legal road area.
    """
    if evidence.empty or reference is None or reference.is_empty or reference.length <= 0.0:
        return None
    ordered = evidence.sort_values("patch_road_key", kind="stable").reset_index(drop=True)
    records = [_evidence_record(row, reference) for row in ordered.itertuples()]
    records = [record for record in records if record["end_m"] - record["start_m"] > 1e-6]
    if not records:
        return None
    coverage = _interval_coverage(
        [(float(record["start_m"]), float(record["end_m"])) for record in records],
        float(reference.length),
    )
    if coverage + 1e-9 < minimum_coverage:
        return None

    if len(records) == 1:
        record = records[0]
        geometry = record["geometry"]
        spans = [
            {
                "geometry_source": "hp_observed",
                "source_object_ids": record["patch_road_key"],
                "start_fraction": 0.0,
                "end_fraction": 1.0,
            }
        ]
        endpoint_keys = (str(record["patch_road_key"]),)
        return _assembly(
            geometry,
            direction_role,
            coverage,
            records,
            endpoint_keys,
            endpoint_keys,
            spans,
            "single_patch_observation",
        )

    spacing = max(0.5, float(sample_spacing_m))
    start_m = min(float(record["start_m"]) for record in records)
    end_m = max(float(record["end_m"]) for record in records)
    station_count = max(2, int(math.ceil((end_m - start_m) / spacing)) + 1)
    stations = np.linspace(start_m, end_m, station_count)
    point_rows: list[dict[str, object]] = []
    for station in stations:
        active = [
            record
            for record in records
            if float(record["start_m"]) - spacing * 0.55
            <= float(station)
            <= float(record["end_m"]) + spacing * 0.55
        ]
        if not active:
            continue
        reference_point = reference.interpolate(float(station))
        active_geometries = np.asarray(
            [record["geometry"] for record in active],
            dtype=object,
        )
        observed_points = line_interpolate_point(
            active_geometries,
            line_locate_point(active_geometries, reference_point),
        )
        point_rows.append(
            {
                "station": float(station),
                "coord": (
                    float(np.median(get_x(observed_points))),
                    float(np.median(get_y(observed_points))),
                ),
                "source_keys": tuple(
                    sorted(str(record["patch_road_key"]) for record in active)
                ),
            }
        )
    point_rows = _deduplicate_points(point_rows)
    if len(point_rows) < 2:
        return None

    segment_labels: list[str] = []
    for left, right in zip(point_rows, point_rows[1:]):
        station_gap = float(right["station"]) - float(left["station"])
        label = (
            "hp_observed"
            if station_gap <= spacing * 1.75
            else "hp_constrained_completion"
        )
        if label == "hp_constrained_completion":
            connector = LineString([left["coord"], right["coord"]])
            if _surface_coverage(connector, drivezone_surface) < completion_min_coverage:
                return None
        segment_labels.append(label)

    geometry = LineString([row["coord"] for row in point_rows])
    if geometry.is_empty:
        return None
    if (
        not geometry.is_valid
        or not geometry.is_simple
        or _max_sample_turn(geometry, spacing) > 75.0
    ):
        observed_chain = _observed_chain_assembly(
            records,
            direction_role,
            coverage,
            drivezone_surface=drivezone_surface,
            completion_min_coverage=completion_min_coverage,
        )
        if observed_chain is not None:
            return observed_chain
        return None
    spans = _span_records(geometry, point_rows, segment_labels)
    first_keys = tuple(point_rows[0]["source_keys"])
    last_keys = tuple(point_rows[-1]["source_keys"])
    if direction_role == "reverse":
        geometry = LineString(list(geometry.coords)[::-1])
        spans = _reverse_spans(spans)
        first_keys, last_keys = last_keys, first_keys
    constrained_length = sum(
        (float(span["end_fraction"]) - float(span["start_fraction"]))
        * float(geometry.length)
        for span in spans
        if span["geometry_source"] == "hp_constrained_completion"
    )
    return _assembly(
        geometry,
        direction_role,
        coverage,
        records,
        first_keys,
        last_keys,
        spans,
        (
            "multi_patch_observed_with_constrained_completion"
            if constrained_length > 1e-6
            else "multi_patch_median_corridor"
        ),
        completion_fraction=(constrained_length / geometry.length if geometry.length else 0.0),
    )


def _evidence_record(row: object, reference: LineString) -> dict[str, object]:
    geometry = row.geometry
    count = max(3, int(math.ceil(float(geometry.length) / 5.0)) + 1)
    sample_points = line_interpolate_point(
        geometry,
        np.linspace(0.0, float(geometry.length), count),
    )
    measures = line_locate_point(reference, sample_points)
    return {
        "geometry": geometry,
        "patch_road_key": str(row.patch_road_key),
        "source_patch_id": str(getattr(row, "source_patch_id", "")),
        "center_lane_id": str(getattr(row, "center_lane_id", "") or ""),
        "road_id": str(getattr(row, "road_id", "") or ""),
        "travel_start_m": float(reference.project(geometry.interpolate(0.0))),
        "start_m": float(np.min(measures)),
        "end_m": float(np.max(measures)),
    }


def _observed_chain_assembly(
    records: list[dict[str, object]],
    direction_role: str,
    coverage: float,
    *,
    drivezone_surface: object | None,
    completion_min_coverage: float,
) -> CorridorAssembly | None:
    preferred_road_ids = {
        str(record["road_id"])
        for record in records
        if str(record["road_id"]) and ":lane:" not in str(record["patch_road_key"])
    }
    remaining = [
        record
        for record in records
        if not (
            ":lane:" in str(record["patch_road_key"])
            and str(record["road_id"]) in preferred_road_ids
        )
    ]
    if not remaining:
        return None
    first = min(
        remaining,
        key=lambda record: (
            float(record["travel_start_m"])
            if direction_role == "forward"
            else -float(record["travel_start_m"]),
            str(record["patch_road_key"]),
        ),
    )
    ordered = [first]
    remaining.remove(first)
    while remaining:
        previous_end = LineString(ordered[-1]["geometry"]).interpolate(1.0, normalized=True)
        following = min(
            remaining,
            key=lambda record: (
                float(previous_end.distance(LineString(record["geometry"]).interpolate(0.0))),
                str(record["patch_road_key"]),
            ),
        )
        ordered.append(following)
        remaining.remove(following)

    pieces: list[tuple[str, str, LineString]] = []
    for index, record in enumerate(ordered):
        observed = LineString(record["geometry"])
        if index:
            previous = pieces[-1][2]
            connector = LineString([previous.coords[-1], observed.coords[0]])
            if connector.length > 1e-6:
                if _surface_coverage(connector, drivezone_surface) < completion_min_coverage:
                    return None
                pieces.append(
                    (
                        "hp_constrained_completion",
                        "",
                        connector,
                    )
                )
        pieces.append(("hp_observed", str(record["patch_road_key"]), observed))
    coords: list[tuple[float, float]] = []
    for _, _, piece in pieces:
        piece_coords = [(float(x), float(y)) for x, y in piece.coords]
        if coords and piece_coords[0] == coords[-1]:
            piece_coords = piece_coords[1:]
        coords.extend(piece_coords)
    if len(coords) < 2:
        return None
    geometry = LineString(coords)
    if (
        geometry.is_empty
        or not geometry.is_valid
        or not geometry.is_simple
        or _max_sample_turn(geometry, 2.0) > 75.0
    ):
        return None
    total_length = float(sum(piece.length for _, _, piece in pieces))
    cursor = 0.0
    spans: list[dict[str, object]] = []
    for source, source_id, piece in pieces:
        start = cursor / total_length if total_length else 0.0
        cursor += float(piece.length)
        spans.append(
            {
                "geometry_source": source,
                "source_object_ids": source_id,
                "start_fraction": start,
                "end_fraction": cursor / total_length if total_length else 1.0,
            }
        )
    completion_length = sum(
        piece.length for source, _, piece in pieces if source == "hp_constrained_completion"
    )
    return _assembly(
        geometry,
        direction_role,
        coverage,
        ordered,
        (str(ordered[0]["patch_road_key"]),),
        (str(ordered[-1]["patch_road_key"]),),
        spans,
        "observed_chain_with_constrained_completion",
        completion_fraction=(completion_length / total_length if total_length else 0.0),
    )


def _max_sample_turn(line: LineString, spacing: float) -> float:
    if line.length <= spacing * 2:
        return 0.0
    count = max(3, int(math.ceil(line.length / spacing)) + 1)
    points = [line.interpolate(value) for value in np.linspace(0.0, line.length, count)]
    maximum = 0.0
    for index in range(1, len(points) - 1):
        first = np.array(
            [
                points[index].x - points[index - 1].x,
                points[index].y - points[index - 1].y,
            ]
        )
        second = np.array(
            [
                points[index + 1].x - points[index].x,
                points[index + 1].y - points[index].y,
            ]
        )
        denominator = float(np.linalg.norm(first) * np.linalg.norm(second))
        if denominator <= 1e-9:
            continue
        cosine = float(np.clip(np.dot(first, second) / denominator, -1.0, 1.0))
        maximum = max(maximum, math.degrees(math.acos(cosine)))
    return maximum


def _assembly(
    geometry: LineString,
    direction_role: str,
    coverage: float,
    records: list[dict[str, object]],
    start_keys: tuple[str, ...],
    end_keys: tuple[str, ...],
    spans: list[dict[str, object]],
    state: str,
    *,
    completion_fraction: float = 0.0,
) -> CorridorAssembly:
    return CorridorAssembly(
        geometry=geometry,
        direction_role=direction_role,
        observed_coverage_ratio=float(coverage),
        completion_fraction=float(completion_fraction),
        source_patch_road_keys=tuple(sorted({str(row["patch_road_key"]) for row in records})),
        start_patch_road_keys=tuple(sorted(start_keys)),
        end_patch_road_keys=tuple(sorted(end_keys)),
        source_patch_ids=tuple(sorted({str(row["source_patch_id"]) for row in records if row["source_patch_id"]})),
        source_lane_ids=tuple(sorted({str(row["center_lane_id"]) for row in records if row["center_lane_id"]})),
        evidence_spans_json=json.dumps(spans, ensure_ascii=False, sort_keys=True),
        assembly_state=state,
    )


def _interval_coverage(intervals: list[tuple[float, float]], total: float) -> float:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + 1.0:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return min(1.0, sum(end - start for start, end in merged) / total) if total else 0.0


def _surface_coverage(line: LineString, surface: object | None) -> float:
    if line.length <= 1e-9:
        return 1.0
    if surface is None or getattr(surface, "is_empty", True):
        return 0.0
    return float(line.intersection(surface).length / line.length)


def _deduplicate_points(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for row in rows:
        if result and math.dist(result[-1]["coord"], row["coord"]) <= 1e-6:
            result[-1] = row
        else:
            result.append(row)
    return result


def _span_records(
    geometry: LineString,
    point_rows: list[dict[str, object]],
    labels: list[str],
) -> list[dict[str, object]]:
    segment_lengths = [
        math.dist(left["coord"], right["coord"])
        for left, right in zip(point_rows, point_rows[1:])
    ]
    total = sum(segment_lengths)
    if total <= 1e-9:
        return []
    spans: list[dict[str, object]] = []
    start = 0.0
    current = labels[0]
    current_sources: set[str] = set(point_rows[0]["source_keys"])
    cumulative = 0.0
    for index, (label, length) in enumerate(zip(labels, segment_lengths)):
        if label != current:
            spans.append(
                {
                    "geometry_source": current,
                    "source_object_ids": ",".join(sorted(current_sources)),
                    "start_fraction": start / total,
                    "end_fraction": cumulative / total,
                }
            )
            start = cumulative
            current = label
            current_sources = set()
        current_sources.update(point_rows[index]["source_keys"])
        current_sources.update(point_rows[index + 1]["source_keys"])
        cumulative += length
    spans.append(
        {
            "geometry_source": current,
            "source_object_ids": ",".join(sorted(current_sources)),
            "start_fraction": start / total,
            "end_fraction": 1.0,
        }
    )
    return spans


def _reverse_spans(spans: list[dict[str, object]]) -> list[dict[str, object]]:
    result = []
    for span in reversed(spans):
        item = dict(span)
        item["start_fraction"] = 1.0 - float(span["end_fraction"])
        item["end_fraction"] = 1.0 - float(span["start_fraction"])
        result.append(item)
    return result


__all__ = [
    "CorridorAssembly",
    "assemble_directional_corridor",
    "evidence_direction_role",
]
