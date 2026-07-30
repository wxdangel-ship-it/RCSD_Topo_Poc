from __future__ import annotations

from dataclasses import dataclass
import math

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely import line_interpolate_point, line_locate_point
from shapely.geometry import LineString


@dataclass(frozen=True)
class TargetPathKeyMetrics:
    intervals: tuple[tuple[float, float], ...]
    finite_assignment_scores: tuple[float, ...]
    full_rcsd_anchor_supported: bool


def build_target_path_metrics(
    by_key: dict[str, gpd.GeoDataFrame],
    reference: LineString,
) -> dict[str, TargetPathKeyMetrics]:
    """Precompute immutable per-key metrics reused by up to 10k path scores."""
    result: dict[str, TargetPathKeyMetrics] = {}
    for key, frame in by_key.items():
        intervals = tuple(
            _reference_interval(geometry, reference)
            for geometry in frame.geometry
        )
        finite_scores = _finite_numeric_values(
            frame["assignment_score"].array
            if "assignment_score" in frame
            else ()
        )
        result[key] = TargetPathKeyMetrics(
            intervals=intervals,
            finite_assignment_scores=finite_scores,
            full_rcsd_anchor_supported=_any_truthy_nonmissing(
                frame["full_rcsd_anchor_supported"].array
                if "full_rcsd_anchor_supported" in frame
                else ()
            ),
        )
    return result


def _finite_numeric_values(values: object) -> tuple[float, ...]:
    result: list[float] = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            result.append(number)
    return tuple(result)


def _any_truthy_nonmissing(values: object) -> bool:
    for value in values:
        missing = pd.isna(value)
        if isinstance(missing, (bool, np.bool_)) and bool(missing):
            continue
        if bool(value):
            return True
    return False


def target_path_score(
    path: tuple[str, ...],
    metrics_by_key: dict[str, TargetPathKeyMetrics],
    reference_length: float,
    surface_mask_by_key: dict[str, int],
    required_surface_count: int,
) -> tuple[float, float, int, float]:
    intervals = [
        interval
        for key in path
        for interval in metrics_by_key[key].intervals
    ]
    coverage = _interval_coverage_ratio(intervals, reference_length)
    minimum = min(start for start, _ in intervals)
    maximum = max(end for _, end in intervals)
    total = max(reference_length, 1e-9)
    endpoint_gap = minimum / total + max(0.0, total - maximum) / total
    finite_scores = [
        value
        for key in path
        for value in metrics_by_key[key].finite_assignment_scores
    ]
    mean_assignment = (
        sum(finite_scores) / len(finite_scores)
        if finite_scores
        else 100.0
    )
    support_fraction = sum(
        metrics_by_key[key].full_rcsd_anchor_supported
        for key in path
    ) / len(path)
    surface_mask = 0
    for key in path:
        surface_mask |= surface_mask_by_key.get(key, 0)
    surface_fraction = (
        surface_mask.bit_count() / required_surface_count
        if required_surface_count
        else 0.0
    )
    return (
        surface_fraction,
        coverage
        - 0.5 * endpoint_gap
        - 0.01 * mean_assignment
        + 0.30 * support_fraction,
        len(path),
        -mean_assignment,
    )


def _reference_interval(
    geometry: LineString,
    reference: LineString,
) -> tuple[float, float]:
    sample_count = max(3, int(math.ceil(float(geometry.length) / 5.0)) + 1)
    fractions = np.fromiter(
        (index / (sample_count - 1) for index in range(sample_count)),
        dtype=float,
        count=sample_count,
    )
    sample_points = line_interpolate_point(
        geometry,
        fractions,
        normalized=True,
    )
    measures = line_locate_point(reference, sample_points)
    return float(np.min(measures)), float(np.max(measures))


def _interval_coverage_ratio(
    intervals: list[tuple[float, float]],
    total: float,
) -> float:
    merged: list[list[float]] = []
    for start, end in sorted(intervals):
        if not merged or start > merged[-1][1] + 1.0:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    return (
        min(1.0, sum(end - start for start, end in merged) / total)
        if total
        else 0.0
    )


__all__ = [
    "TargetPathKeyMetrics",
    "build_target_path_metrics",
    "target_path_score",
]
