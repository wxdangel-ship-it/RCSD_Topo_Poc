from __future__ import annotations

from collections import OrderedDict
import math
import weakref

import numpy as np
from shapely import STRtree, is_prepared, prepare
from shapely.geometry import MultiPolygon


_MAX_SAMPLE_TURN_CACHE_SIZE = 32768
_MAX_SAMPLE_TURN_CACHE: OrderedDict[tuple[bytes, float], float] = OrderedDict()
_SURFACE_COVERAGE_CACHE_SIZE = 131072
_SURFACE_COVERAGE_CACHE_WKB_BYTES_MAX = 256 * 1024**2
_SURFACE_COVERAGE_CACHE: OrderedDict[
    tuple[int, bytes],
    tuple[weakref.ReferenceType[object], float],
] = OrderedDict()
_SURFACE_COVERAGE_CACHE_WKB_BYTES = 0
_MIN_INDEXED_SURFACE_PARTS = 8
_SURFACE_PART_INDEX_CACHE: dict[
    int,
    tuple[
        weakref.ReferenceType[object],
        tuple[object, ...],
        STRtree,
    ],
] = {}
_SURFACE_VALIDITY_CACHE: dict[
    int,
    tuple[weakref.ReferenceType[object], bool],
] = {}
_SURFACE_COVERAGE_STATS = {
    "query_count": 0,
    "cache_hit_count": 0,
    "multipolygon_index_query_count": 0,
    "direct_query_count": 0,
    "terminal_covers_count": 0,
    "terminal_disjoint_count": 0,
    "threshold_query_count": 0,
    "threshold_cache_count": 0,
    "threshold_trivial_count": 0,
    "threshold_covers_count": 0,
    "threshold_disjoint_count": 0,
    "threshold_exact_fallback_count": 0,
    "unsafe_local_reconstruction_count": 0,
}


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

    return _surface_coverage_value(line, surface)[0]


def _surface_coverage_value(
    line: object,
    surface: object | None,
) -> tuple[float, str]:
    global _SURFACE_COVERAGE_CACHE_WKB_BYTES
    _SURFACE_COVERAGE_STATS["query_count"] += 1
    if line.length <= 1e-9:
        return 1.0, "degenerate"
    if surface is None or getattr(surface, "is_empty", True):
        return 0.0, "empty_surface"
    line_wkb = line.wkb
    key = (id(surface), line_wkb)
    cached = _SURFACE_COVERAGE_CACHE.get(key)
    if cached is not None and cached[0]() is surface:
        _SURFACE_COVERAGE_STATS["cache_hit_count"] += 1
        _SURFACE_COVERAGE_CACHE.move_to_end(key)
        return cached[1], "cache"

    terminal = _terminal_surface_coverage(line, surface)
    if terminal is None:
        coverage = float(
            _surface_intersection_length(line, surface) / line.length
        )
        mode = "exact_overlay"
    else:
        coverage, mode = terminal
        _SURFACE_COVERAGE_STATS[f"terminal_{mode}_count"] += 1
    try:
        surface_reference = weakref.ref(surface)
    except TypeError:
        return coverage, mode
    stale = _SURFACE_COVERAGE_CACHE.pop(key, None)
    if stale is not None:
        _SURFACE_COVERAGE_CACHE_WKB_BYTES -= len(line_wkb)
    _SURFACE_COVERAGE_CACHE[key] = (surface_reference, coverage)
    _SURFACE_COVERAGE_CACHE_WKB_BYTES += len(line_wkb)
    _SURFACE_COVERAGE_CACHE.move_to_end(key)
    while (
        len(_SURFACE_COVERAGE_CACHE) > _SURFACE_COVERAGE_CACHE_SIZE
        or _SURFACE_COVERAGE_CACHE_WKB_BYTES
        > _SURFACE_COVERAGE_CACHE_WKB_BYTES_MAX
    ):
        evicted_key, _ = _SURFACE_COVERAGE_CACHE.popitem(last=False)
        _SURFACE_COVERAGE_CACHE_WKB_BYTES -= len(evicted_key[1])
    return coverage, mode


def _terminal_surface_coverage(
    line: object,
    surface: object,
) -> tuple[float, str] | None:
    if _surface_part_index(surface) is not None:
        return None
    if not _surface_is_valid(surface):
        return None
    if not is_prepared(surface):
        prepare(surface)
    if surface.covers(line):
        return 1.0, "covers"
    if surface.disjoint(line):
        return 0.0, "disjoint"
    return None


def surface_coverage_at_least(
    line: object,
    surface: object | None,
    minimum_coverage: float,
    *,
    epsilon: float = 0.0,
) -> bool:
    """Apply one coverage threshold without changing exact P04 semantics.

    A prepared full-surface predicate can prove the two terminal cases exactly:
    a covered line has coverage 1 and a disjoint line has coverage 0.  Boundary
    cases still use :func:`surface_coverage`, so no locally reconstructed
    polygon can change a business decision.
    """

    _SURFACE_COVERAGE_STATS["threshold_query_count"] += 1
    threshold = float(minimum_coverage)
    tolerance = float(epsilon)
    if threshold <= tolerance:
        _SURFACE_COVERAGE_STATS["threshold_trivial_count"] += 1
        return True
    if threshold > 1.0 + tolerance:
        _SURFACE_COVERAGE_STATS["threshold_trivial_count"] += 1
        return False
    coverage, mode = _surface_coverage_value(line, surface)
    if mode == "covers":
        _SURFACE_COVERAGE_STATS["threshold_covers_count"] += 1
    elif mode == "disjoint":
        _SURFACE_COVERAGE_STATS["threshold_disjoint_count"] += 1
    elif mode == "cache":
        _SURFACE_COVERAGE_STATS["threshold_cache_count"] += 1
    else:
        _SURFACE_COVERAGE_STATS["threshold_exact_fallback_count"] += 1
    return coverage + tolerance >= threshold


def _surface_intersection_length(line: object, surface: object) -> float:
    indexed = _surface_part_index(surface)
    if indexed is not None:
        parts, tree = indexed
        _SURFACE_COVERAGE_STATS["multipolygon_index_query_count"] += 1
        candidate_indices = sorted(int(index) for index in tree.query(line))
        if not candidate_indices:
            return 0.0
        if len(candidate_indices) != len(parts):
            if len(candidate_indices) == 1:
                candidate_surface = parts[candidate_indices[0]]
            else:
                candidate_surface = MultiPolygon(
                    [parts[index] for index in candidate_indices]
                )
            return float(line.intersection(candidate_surface).length)

    _SURFACE_COVERAGE_STATS["direct_query_count"] += 1
    return float(line.intersection(surface).length)


def surface_coverage_runtime_stats() -> dict[str, int | float | str]:
    stats: dict[str, int | float | str] = dict(_SURFACE_COVERAGE_STATS)
    query_count = int(stats["query_count"])
    cache_hits = int(stats["cache_hit_count"])
    stats["cache_hit_ratio"] = (
        cache_hits / query_count if query_count else 0.0
    )
    threshold_queries = int(stats["threshold_query_count"])
    threshold_terminal = int(stats["threshold_covers_count"]) + int(
        stats["threshold_disjoint_count"]
    )
    stats["threshold_terminal_ratio"] = (
        threshold_terminal / threshold_queries if threshold_queries else 0.0
    )
    stats["coverage_cache_entries"] = len(_SURFACE_COVERAGE_CACHE)
    stats["coverage_cache_wkb_bytes"] = (
        _SURFACE_COVERAGE_CACHE_WKB_BYTES
    )
    stats["coverage_cache_wkb_bytes_max"] = (
        _SURFACE_COVERAGE_CACHE_WKB_BYTES_MAX
    )
    stats["multipolygon_index_count"] = len(_SURFACE_PART_INDEX_CACHE)
    stats["surface_validity_cache_entries"] = len(_SURFACE_VALIDITY_CACHE)
    stats["exactness_mode"] = "full_surface_predicate_or_exact_intersection"
    return stats


def _surface_part_index(
    surface: object,
) -> tuple[tuple[object, ...], STRtree] | None:
    if getattr(surface, "geom_type", "") != "MultiPolygon":
        return None
    key = id(surface)
    cached = _SURFACE_PART_INDEX_CACHE.get(key)
    if cached is not None and cached[0]() is surface:
        return cached[1], cached[2]

    parts = tuple(surface.geoms)
    if len(parts) < _MIN_INDEXED_SURFACE_PARTS or not _surface_is_valid(surface):
        return None
    tree = STRtree(parts)

    def remove(_: weakref.ReferenceType[object]) -> None:
        current = _SURFACE_PART_INDEX_CACHE.get(key)
        if current is not None and current[0]() is None:
            _SURFACE_PART_INDEX_CACHE.pop(key, None)

    try:
        surface_reference = weakref.ref(surface, remove)
    except TypeError:
        return None
    _SURFACE_PART_INDEX_CACHE[key] = (surface_reference, parts, tree)
    return parts, tree


def _surface_is_valid(surface: object) -> bool:
    key = id(surface)
    cached = _SURFACE_VALIDITY_CACHE.get(key)
    if cached is not None and cached[0]() is surface:
        return cached[1]
    valid = bool(getattr(surface, "is_valid", False))

    def remove(_: weakref.ReferenceType[object]) -> None:
        current = _SURFACE_VALIDITY_CACHE.get(key)
        if current is not None and current[0]() is None:
            _SURFACE_VALIDITY_CACHE.pop(key, None)

    try:
        reference = weakref.ref(surface, remove)
    except TypeError:
        return valid
    _SURFACE_VALIDITY_CACHE[key] = (reference, valid)
    return valid


__all__ = [
    "max_sample_turn",
    "surface_coverage",
    "surface_coverage_at_least",
    "surface_coverage_runtime_stats",
]
