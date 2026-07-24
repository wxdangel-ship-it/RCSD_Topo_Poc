from __future__ import annotations

from collections.abc import Callable
import json
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import substring


def build_partial_member_carriers(
    segment_id: str,
    member_id: str,
    member: pd.Series,
    evidence: gpd.GeoDataFrame,
    *,
    run_id: str,
    drivezone_surface: object | None,
    full_minimum_coverage: float,
    sample_spacing_m: float,
    completion_min_coverage: float,
    member_carrier_builder: Callable[..., list[dict[str, object]]],
    carrier_roles_by_direction: dict[str, str] | None = None,
    partial_minimum_coverage: float = 0.50,
    maximum_endpoint_completion_m: float = 20.0,
    minimum_retained_part_length_m: float = 1.0,
) -> list[dict[str, object]]:
    """Realize one-way Road evidence without mixing SWSD into a built Road.

    The observed span becomes a built Road.  A short endpoint gap may be
    completed only by a straight connector inside DriveZone.  Every remaining
    unsupported span is published as a separate retained Road.
    """

    direction = int(member.get("direction", 1) or 1)
    reference = member.geometry
    if (
        direction not in {2, 3}
        or evidence.empty
        or reference is None
        or reference.is_empty
        or reference.length <= 0.0
    ):
        return []
    partial_threshold = min(
        float(partial_minimum_coverage),
        float(full_minimum_coverage),
    )
    built_rows = member_carrier_builder(
        segment_id,
        member_id,
        member,
        evidence,
        run_id=run_id,
        drivezone_surface=drivezone_surface,
        minimum_member_coverage=partial_threshold,
        sample_spacing_m=sample_spacing_m,
        completion_min_coverage=completion_min_coverage,
        carrier_roles_by_direction=carrier_roles_by_direction or {},
        allow_surface_inferred_counterpart=False,
    )
    if len(built_rows) != 1:
        return []
    built = dict(built_rows[0])
    coverage = float(built.get("observed_coverage_ratio", 0.0) or 0.0)
    if (
        coverage + 1e-9 < partial_threshold
        or coverage + 1e-9 >= full_minimum_coverage
    ):
        return []

    observed = built.get("geometry")
    if observed is None or observed.is_empty or observed.length <= 0.0:
        return []
    stations = _projected_stations(observed, reference)
    low_m = max(0.0, min(stations))
    high_m = min(float(reference.length), max(stations))
    if high_m - low_m <= 1e-6:
        return []

    low_connector = LineString(
        [
            reference.interpolate(0.0),
            _geometry_endpoint_for_station(observed, reference, low_m),
        ]
    )
    high_connector = LineString(
        [
            _geometry_endpoint_for_station(observed, reference, high_m),
            reference.interpolate(1.0, normalized=True),
        ]
    )
    low_completed = _completion_supported(
        low_connector,
        drivezone_surface,
        maximum_length_m=maximum_endpoint_completion_m,
        minimum_surface_coverage=completion_min_coverage,
    )
    high_completed = _completion_supported(
        high_connector,
        drivezone_surface,
        maximum_length_m=maximum_endpoint_completion_m,
        minimum_surface_coverage=completion_min_coverage,
    )
    low_missing = low_m if not low_completed else 0.0
    high_missing = (
        float(reference.length) - high_m if not high_completed else 0.0
    )
    for missing in (low_missing, high_missing):
        if 1e-6 < missing < minimum_retained_part_length_m:
            return []

    direction_role = str(built.get("direction_role", "forward"))
    built_geometry, completion_spans = _extend_observed_geometry(
        observed,
        reference,
        direction_role=direction_role,
        low_completed=low_completed,
        high_completed=high_completed,
        source_object_ids=str(
            built.get("source_patch_road_keys", "")
            or built.get("patch_road_key", "")
        ),
    )
    completion_length = sum(
        float(span["length_m"])
        for span in completion_spans
        if span["geometry_source"] == "hp_constrained_completion"
    )
    built.update(
        {
            "geometry": built_geometry,
            "geometry_source": (
                "hp_observed+hp_constrained_completion"
                if completion_length > 1e-6
                else "hp_observed"
            ),
            "internal_completion_fraction": (
                completion_length / built_geometry.length
                if built_geometry.length
                else 0.0
            ),
            "assembly_state": (
                "partial_member_observed_with_endpoint_completion"
                if completion_length > 1e-6
                else "partial_member_observed"
            ),
            "evidence_spans_json": json.dumps(
                [
                    {
                        "geometry_source": str(span["geometry_source"]),
                        "source_object_ids": str(span["source_object_ids"]),
                        "start_fraction": float(span["start_m"])
                        / built_geometry.length,
                        "end_fraction": float(span["end_m"])
                        / built_geometry.length,
                    }
                    for span in completion_spans
                ],
                sort_keys=True,
            ),
            "inherit_source_snodeid": (
                low_completed
                if direction_role == "forward"
                else high_completed
            ),
            "inherit_source_enodeid": (
                high_completed
                if direction_role == "forward"
                else low_completed
            ),
            "reason_codes": "partial_member_hp_observed",
        }
    )

    retained_intervals: list[tuple[float, float, str]] = []
    if low_missing >= minimum_retained_part_length_m:
        retained_intervals.append((0.0, low_m, "prefix"))
    if high_missing >= minimum_retained_part_length_m:
        retained_intervals.append(
            (high_m, float(reference.length), "suffix")
        )
    if not retained_intervals:
        return [built]
    retained = [
        _retained_part(
            member,
            segment_id,
            member_id,
            run_id,
            start_m,
            end_m,
            label,
            index=index,
            count=len(retained_intervals),
        )
        for index, (start_m, end_m, label) in enumerate(retained_intervals)
    ]
    return [built, *retained]


def _projected_stations(
    geometry: LineString,
    reference: LineString,
) -> list[float]:
    count = max(3, int(math.ceil(float(geometry.length) / 5.0)) + 1)
    return [
        float(reference.project(geometry.interpolate(distance)))
        for distance in np.linspace(0.0, float(geometry.length), count)
    ]


def _geometry_endpoint_for_station(
    geometry: LineString,
    reference: LineString,
    station: float,
) -> object:
    endpoints = [
        geometry.interpolate(0.0),
        geometry.interpolate(1.0, normalized=True),
    ]
    return min(
        endpoints,
        key=lambda point: abs(float(reference.project(point)) - station),
    )


def _completion_supported(
    connector: LineString,
    surface: object | None,
    *,
    maximum_length_m: float,
    minimum_surface_coverage: float,
) -> bool:
    if connector.length <= 1e-6:
        return True
    if connector.length > maximum_length_m or surface is None or surface.is_empty:
        return False
    return (
        float(connector.intersection(surface).length / connector.length)
        + 1e-9
        >= minimum_surface_coverage
    )


def _extend_observed_geometry(
    observed: LineString,
    reference: LineString,
    *,
    direction_role: str,
    low_completed: bool,
    high_completed: bool,
    source_object_ids: str,
) -> tuple[LineString, list[dict[str, object]]]:
    coords = list(observed.coords)
    pieces: list[tuple[str, str, float]] = []
    if direction_role == "forward":
        if low_completed:
            start = reference.interpolate(0.0)
            coords.insert(0, (float(start.x), float(start.y)))
            pieces.append(("hp_constrained_completion", "DriveZone", 0.0))
        pieces.append(("hp_observed", source_object_ids, float(observed.length)))
        if high_completed:
            end = reference.interpolate(1.0, normalized=True)
            coords.append((float(end.x), float(end.y)))
            pieces.append(("hp_constrained_completion", "DriveZone", 0.0))
    else:
        if high_completed:
            end = reference.interpolate(1.0, normalized=True)
            coords.insert(0, (float(end.x), float(end.y)))
            pieces.append(("hp_constrained_completion", "DriveZone", 0.0))
        pieces.append(("hp_observed", source_object_ids, float(observed.length)))
        if low_completed:
            start = reference.interpolate(0.0)
            coords.append((float(start.x), float(start.y)))
            pieces.append(("hp_constrained_completion", "DriveZone", 0.0))
    geometry = LineString(coords)
    cursor = 0.0
    spans: list[dict[str, object]] = []
    for index, (source, object_ids, declared_length) in enumerate(pieces):
        if source == "hp_observed":
            length = declared_length
        elif index == 0:
            length = float(
                geometry.interpolate(0.0).distance(
                    observed.interpolate(0.0)
                )
            )
        else:
            length = float(
                geometry.interpolate(1.0, normalized=True).distance(
                    observed.interpolate(1.0, normalized=True)
                )
            )
        spans.append(
            {
                "geometry_source": source,
                "source_object_ids": object_ids,
                "start_m": cursor,
                "end_m": cursor + length,
                "length_m": length,
            }
        )
        cursor += length
    if spans:
        spans[-1]["end_m"] = float(geometry.length)
        spans[-1]["length_m"] = float(geometry.length) - float(
            spans[-1]["start_m"]
        )
    return geometry, spans


def _retained_part(
    member: pd.Series,
    segment_id: str,
    member_id: str,
    run_id: str,
    start_m: float,
    end_m: float,
    label: str,
    *,
    index: int,
    count: int,
) -> dict[str, object]:
    geometry = substring(member.geometry, start_m, end_m)
    carrier_id = (
        f"retained-part:{member_id}:{label}:"
        f"{round(start_m, 3)}:{round(end_m, 3)}"
    )
    return {
        **member.to_dict(),
        "run_id": run_id,
        "segment_id": segment_id,
        "member_swsd_road_id": member_id,
        "patch_road_key": "",
        "source_patch_road_keys": "",
        "start_patch_road_keys": "",
        "end_patch_road_keys": "",
        "carrier_id": carrier_id,
        "carrier_role": "semantic_carrier",
        "realization": "retained",
        "geometry_source": "swsd_retained_partial",
        "source_object_type": "SWSD_ROAD_RETAINED_PARTIAL",
        "observed_coverage_ratio": 0.0,
        "internal_completion_fraction": 0.0,
        "surface_inferred_fraction": 0.0,
        "assembly_state": "retained_partial_after_hp_observation",
        "evidence_spans_json": json.dumps(
            [
                {
                    "geometry_source": "swsd_retained_partial",
                    "source_object_ids": member_id,
                    "start_fraction": 0.0,
                    "end_fraction": 1.0,
                }
            ],
            sort_keys=True,
        ),
        "inherit_source_snodeid": start_m <= 1e-6,
        "inherit_source_enodeid": (
            end_m >= float(member.geometry.length) - 1e-6
        ),
        "retained_part_index": index,
        "retained_part_count": count,
        "reason_codes": "partial_member_missing_patch_retained",
        "geometry": geometry,
    }


__all__ = ["build_partial_member_carriers"]
