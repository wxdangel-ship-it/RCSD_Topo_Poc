from __future__ import annotations

from typing import Any

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString


def compare_frozen_v2_roads(
    v3_roads: gpd.GeoDataFrame,
    frozen_v2_roads: gpd.GeoDataFrame,
    *,
    sample_spacing_m: float = 5.0,
) -> tuple[gpd.GeoDataFrame, dict[str, Any]]:
    """Build an audit-only per-Road V3-to-frozen-V2 geometry comparison."""

    if v3_roads.crs is None or frozen_v2_roads.crs is None:
        raise ValueError("V3 and frozen V2 Road CRS must be explicit")
    if v3_roads.crs != frozen_v2_roads.crs:
        raise ValueError(f"V3/V2 CRS mismatch: {v3_roads.crs} != {frozen_v2_roads.crs}")
    if sample_spacing_m <= 0:
        raise ValueError("sample_spacing_m must be positive")

    by_parent = {
        str(parent_id): frame
        for parent_id, frame in frozen_v2_roads.groupby(
            frozen_v2_roads["parent_swsd_unit_id"].astype(str), sort=False
        )
    }
    rows: list[dict[str, Any]] = []
    for road in v3_roads.itertuples(index=False):
        parent_id = str(road.parent_swsd_unit_id)
        travel_side = str(road.travel_side)
        candidates = by_parent.get(parent_id)
        if candidates is None or candidates.empty:
            rows.append(
                _unmatched_row(
                    road,
                    comparison_state="no_frozen_v2_parent_match",
                )
            )
            continue

        same_side = candidates[candidates["travel_side"].astype(str) == travel_side]
        eligible = same_side if not same_side.empty else candidates
        match_method = "same_parent_same_side" if not same_side.empty else "same_parent_nearest"
        scored: list[tuple[float, float, Any, list[float]]] = []
        for candidate in eligible.itertuples(index=False):
            distances = _sample_distances(
                road.geometry,
                candidate.geometry,
                spacing=sample_spacing_m,
            )
            mean_distance = float(np.mean(distances))
            hausdorff = float(road.geometry.hausdorff_distance(candidate.geometry))
            scored.append((mean_distance, hausdorff, candidate, distances))
        mean_distance, hausdorff, matched, distances = min(
            scored,
            key=lambda value: (value[0], value[1], str(value[2].directional_road_id)),
        )
        rows.append(
            {
                "v3_road_id": str(road.v3_road_id),
                "parent_swsd_unit_id": parent_id,
                "v3_travel_side": travel_side,
                "v3_road_representation": str(road.road_representation),
                "v3_support_state": str(road.support_state),
                "frozen_v2_road_id": str(matched.directional_road_id),
                "frozen_v2_travel_side": str(matched.travel_side),
                "match_method": match_method,
                "comparison_state": "matched_for_shape_audit",
                "sample_spacing_m": float(sample_spacing_m),
                "sample_count": len(distances),
                "mean_sample_distance_m": mean_distance,
                "p95_sample_distance_m": float(np.percentile(distances, 95)),
                "max_sample_distance_m": float(max(distances)),
                "hausdorff_distance_m": hausdorff,
                "v3_length_m": float(road.geometry.length),
                "frozen_v2_length_m": float(matched.geometry.length),
                "length_delta_m": float(road.geometry.length - matched.geometry.length),
                "decision": "comparison_only",
                "reason_codes": "frozen_v2_read_only_shape_audit",
                "geometry": road.geometry,
            }
        )

    result = gpd.GeoDataFrame(rows, geometry="geometry", crs=v3_roads.crs)
    matched = result[result["comparison_state"] == "matched_for_shape_audit"]
    summary = {
        "v3_road_count": int(len(result)),
        "matched_count": int(len(matched)),
        "unmatched_count": int(len(result) - len(matched)),
        "same_parent_same_side_count": int(
            (matched["match_method"] == "same_parent_same_side").sum()
        ),
        "same_parent_nearest_count": int(
            (matched["match_method"] == "same_parent_nearest").sum()
        ),
        "median_mean_sample_distance_m": _median(
            matched["mean_sample_distance_m"]
        ),
        "p95_sample_distance_m": _percentile(
            matched["p95_sample_distance_m"], 95
        ),
        "comparison_scope": "audit_only_same_parent_v3_to_frozen_v2",
    }
    return result, summary


def _sample_distances(
    source: LineString,
    target: LineString,
    *,
    spacing: float,
) -> list[float]:
    count = max(2, int(np.ceil(source.length / spacing)) + 1)
    stations = np.linspace(0.0, source.length, count)
    return [float(source.interpolate(float(station)).distance(target)) for station in stations]


def _unmatched_row(road: Any, *, comparison_state: str) -> dict[str, Any]:
    return {
        "v3_road_id": str(road.v3_road_id),
        "parent_swsd_unit_id": str(road.parent_swsd_unit_id),
        "v3_travel_side": str(road.travel_side),
        "v3_road_representation": str(road.road_representation),
        "v3_support_state": str(road.support_state),
        "frozen_v2_road_id": None,
        "frozen_v2_travel_side": None,
        "match_method": "none",
        "comparison_state": comparison_state,
        "sample_spacing_m": None,
        "sample_count": 0,
        "mean_sample_distance_m": None,
        "p95_sample_distance_m": None,
        "max_sample_distance_m": None,
        "hausdorff_distance_m": None,
        "v3_length_m": float(road.geometry.length),
        "frozen_v2_length_m": None,
        "length_delta_m": None,
        "decision": "comparison_only",
        "reason_codes": comparison_state,
        "geometry": road.geometry,
    }


def _median(values: Any) -> float | None:
    return float(values.median()) if len(values) else None


def _percentile(values: Any, percentile: float) -> float | None:
    return float(np.percentile(values, percentile)) if len(values) else None


__all__ = ["compare_frozen_v2_roads"]
