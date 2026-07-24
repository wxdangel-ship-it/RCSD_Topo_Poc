from __future__ import annotations

import math
from collections.abc import Iterable
from typing import Any

import numpy as np
from shapely import force_2d
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.t01_data_preprocess.id_normalization import normalize_id


def canonical_id(value: Any) -> str | None:
    return normalize_id(value)


def parse_patch_membership(value: Any) -> frozenset[str]:
    if value is None:
        return frozenset()
    return frozenset(token.strip() for token in str(value).split(",") if token.strip())


def to_2d(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return geometry
    return force_2d(geometry)


def sample_distances(
    geometry: BaseGeometry,
    *,
    spacing_m: float,
    min_samples: int,
    max_samples: int,
) -> tuple[float, ...]:
    length = float(geometry.length)
    if length <= 0:
        return (0.0,)
    count = max(min_samples, min(max_samples, int(math.ceil(length / spacing_m)) + 1))
    inset = min(1.0, length * 0.05)
    start = inset
    end = max(start, length - inset)
    return tuple(float(value) for value in np.linspace(start, end, count))


def tangent_vector(geometry: BaseGeometry, distance_m: float, *, span_m: float = 1.5) -> tuple[float, float]:
    length = float(geometry.length)
    if length <= 0:
        return (0.0, 0.0)
    start = max(0.0, distance_m - span_m)
    end = min(length, distance_m + span_m)
    if end - start < 0.05:
        start, end = 0.0, length
    first = geometry.interpolate(start)
    second = geometry.interpolate(end)
    return (float(second.x - first.x), float(second.y - first.y))


def vector_angle_deg(first: tuple[float, float], second: tuple[float, float]) -> float:
    first_norm = math.hypot(*first)
    second_norm = math.hypot(*second)
    if first_norm <= 0 or second_norm <= 0:
        return 180.0
    cosine = (first[0] * second[0] + first[1] * second[1]) / (first_norm * second_norm)
    cosine = max(-1.0, min(1.0, cosine))
    return float(math.degrees(math.acos(cosine)))


def undirected_angle_deg(first: tuple[float, float], second: tuple[float, float]) -> float:
    raw = vector_angle_deg(first, second)
    return min(raw, 180.0 - raw)


def swsd_direction_delta_deg(
    lane_tangent: tuple[float, float],
    road_tangent: tuple[float, float],
    direction: int | None,
) -> float:
    raw = vector_angle_deg(lane_tangent, road_tangent)
    if direction == 3:
        return 180.0 - raw
    if direction in {0, 1}:
        return min(raw, 180.0 - raw)
    return raw


def quantile_or_none(values: Iterable[float], quantile: float) -> float | None:
    materialized = tuple(float(value) for value in values)
    if not materialized:
        return None
    return float(np.quantile(materialized, quantile))


def dominant_id(values: Iterable[str]) -> str | None:
    counts: dict[str, int] = {}
    for value in values:
        counts[value] = counts.get(value, 0) + 1
    if not counts:
        return None
    return min(counts, key=lambda value: (-counts[value], value))
