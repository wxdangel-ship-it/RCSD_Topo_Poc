from __future__ import annotations

from collections import OrderedDict
import math
import weakref

import numpy as np


_MAX_SAMPLE_TURN_CACHE_SIZE = 32768
_MAX_SAMPLE_TURN_CACHE: OrderedDict[tuple[bytes, float], float] = OrderedDict()
_SURFACE_COVERAGE_CACHE_SIZE = 32768
_SURFACE_COVERAGE_CACHE: OrderedDict[
    tuple[int, bytes],
    tuple[weakref.ReferenceType[object], float],
] = OrderedDict()


def max_sample_turn(geometry: object, spacing: float) -> float:
    """Return the exact sampled turn while reusing identical line calculations."""

    if (
        geometry is None
        or geometry.is_empty
        or geometry.length <= spacing * 2
    ):
        return 0.0
    key = (geometry.wkb, float(spacing))
    cached = _MAX_SAMPLE_TURN_CACHE.get(key)
    if cached is not None:
        _MAX_SAMPLE_TURN_CACHE.move_to_end(key)
        return cached

    count = max(3, int(math.ceil(geometry.length / spacing)) + 1)
    points = [
        geometry.interpolate(value)
        for value in np.linspace(0.0, geometry.length, count)
    ]
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

    _MAX_SAMPLE_TURN_CACHE[key] = maximum
    _MAX_SAMPLE_TURN_CACHE.move_to_end(key)
    if len(_MAX_SAMPLE_TURN_CACHE) > _MAX_SAMPLE_TURN_CACHE_SIZE:
        _MAX_SAMPLE_TURN_CACHE.popitem(last=False)
    return maximum


def surface_coverage(line: object, surface: object | None) -> float:
    """Return exact line coverage while reusing identical surface intersections."""

    if line.length <= 1e-9:
        return 1.0
    if surface is None or getattr(surface, "is_empty", True):
        return 0.0
    key = (id(surface), line.wkb)
    cached = _SURFACE_COVERAGE_CACHE.get(key)
    if cached is not None and cached[0]() is surface:
        _SURFACE_COVERAGE_CACHE.move_to_end(key)
        return cached[1]

    coverage = float(line.intersection(surface).length / line.length)
    try:
        surface_reference = weakref.ref(surface)
    except TypeError:
        return coverage
    _SURFACE_COVERAGE_CACHE[key] = (surface_reference, coverage)
    _SURFACE_COVERAGE_CACHE.move_to_end(key)
    if len(_SURFACE_COVERAGE_CACHE) > _SURFACE_COVERAGE_CACHE_SIZE:
        _SURFACE_COVERAGE_CACHE.popitem(last=False)
    return coverage


__all__ = ["max_sample_turn", "surface_coverage"]
