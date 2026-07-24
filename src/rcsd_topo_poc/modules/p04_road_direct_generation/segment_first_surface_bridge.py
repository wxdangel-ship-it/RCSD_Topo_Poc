from __future__ import annotations

from collections.abc import Callable
import json
import math

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

from .segment_first_corridors import CorridorAssembly


def build_endpoint_surface_bridge_assembly(
    evidence: gpd.GeoDataFrame,
    *,
    direction_role: str,
    required_surfaces: tuple[object, ...],
    completion_surface: object | None,
    maximum_distance_m: float,
    minimum_observed_fraction: float,
    minimum_surface_coverage: float,
    assembly_completer: Callable[..., CorridorAssembly | None],
) -> tuple[gpd.GeoDataFrame, CorridorAssembly] | None:
    """Accept a certified Patch bridge when SWSD overstates Junction length."""
    if (
        evidence.empty
        or len(required_surfaces) != 2
        or completion_surface is None
        or "assignment_source" not in evidence
        or "recovery_eligible" not in evidence
    ):
        return None
    if float(required_surfaces[0].distance(required_surfaces[1])) <= 1e-9:
        return None
    candidates = evidence[
        evidence["assignment_source"]
        .fillna("")
        .eq("target_access_surface_candidate")
        & evidence["recovery_eligible"].fillna(False).astype(bool)
    ].copy()
    if candidates.empty:
        return None
    coverage = pd.to_numeric(
        candidates.get(
            "access_surface_coverage",
            pd.Series(math.nan, index=candidates.index),
        ),
        errors="coerce",
    )
    candidates = candidates[
        coverage.ge(minimum_surface_coverage - 1e-9)
    ].copy()
    assembled: list[
        tuple[float, float, str, gpd.GeoDataFrame, CorridorAssembly]
    ] = []
    for index, row in candidates.iterrows():
        geometry = _longest_line(row.geometry)
        if (
            geometry is None
            or geometry.is_empty
            or not geometry.is_valid
            or not geometry.is_simple
        ):
            continue
        key = str(row.get("patch_road_key", ""))
        raw_assembly = CorridorAssembly(
            geometry=geometry,
            direction_role=direction_role,
            observed_coverage_ratio=1.0,
            completion_fraction=0.0,
            source_patch_road_keys=(key,),
            start_patch_road_keys=(key,),
            end_patch_road_keys=(key,),
            source_patch_ids=_split_values(
                row.get("source_patch_ids", ""),
                row.get("source_patch_id", ""),
            ),
            source_lane_ids=_split_values(
                row.get("source_lane_ids", ""),
                row.get("center_lane_id", ""),
            ),
            evidence_spans_json=json.dumps(
                [
                    {
                        "geometry_source": "hp_observed",
                        "source_object_ids": key,
                        "start_fraction": 0.0,
                        "end_fraction": 1.0,
                    }
                ],
                sort_keys=True,
            ),
            assembly_state="endpoint_surface_bridge_observed",
        )
        completed = assembly_completer(
            raw_assembly,
            required_surfaces,
            completion_surface=completion_surface,
            maximum_distance_m=maximum_distance_m,
            minimum_surface_coverage=minimum_surface_coverage,
        )
        if (
            completed is None
            or completed.observed_coverage_ratio + 1e-9
            < minimum_observed_fraction
            or not _touches_distinct_terminal_surfaces(
                completed.geometry,
                required_surfaces,
            )
        ):
            continue
        assembled.append(
            (
                completed.completion_fraction,
                -float(geometry.length),
                key,
                candidates.loc[[index]].copy(),
                completed,
            )
        )
    if not assembled:
        return None
    _, _, _, selected, assembly = min(
        assembled,
        key=lambda item: item[:3],
    )
    return selected, assembly


def _split_values(*raw_values: object) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                value
                for raw in raw_values
                for value in str(raw or "").split(",")
                if value and value.lower() != "nan"
            }
        )
    )


def _touches_distinct_terminal_surfaces(
    geometry: LineString,
    surfaces: tuple[object, ...],
) -> bool:
    start = Point(geometry.coords[0])
    end = Point(geometry.coords[-1])
    first, second = surfaces
    direct = (
        float(start.distance(first)) <= 1e-9
        and float(end.distance(second)) <= 1e-9
    )
    reverse = (
        float(start.distance(second)) <= 1e-9
        and float(end.distance(first)) <= 1e-9
    )
    return direct or reverse


def _longest_line(geometry: object) -> LineString | None:
    if isinstance(geometry, LineString):
        return geometry
    parts = [
        part
        for part in getattr(geometry, "geoms", ())
        if isinstance(part, LineString)
    ]
    return max(parts, key=lambda part: float(part.length)) if parts else None


__all__ = ["build_endpoint_surface_bridge_assembly"]
