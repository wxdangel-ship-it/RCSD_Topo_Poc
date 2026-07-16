from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from hashlib import blake2b
from weakref import ReferenceType, ref

from shapely.geometry.base import BaseGeometry


CoverageDecision = tuple[bool, bool]
CoverageDecisionKey = tuple[bytes, tuple[bytes, ...], bytes | None, float]
BufferedCorridorKey = tuple[tuple[bytes, ...], float]

_MAX_COVERAGE_DECISIONS = 50_000
_MAX_BUFFERED_CORRIDORS = 256
_COVERAGE_DECISION_CACHE_DEPTH = 0
_COVERAGE_DECISION_CACHE: dict[CoverageDecisionKey, CoverageDecision] = {}
_BUFFERED_CORRIDOR_CACHE: OrderedDict[BufferedCorridorKey, BaseGeometry] = OrderedDict()
_GEOMETRY_FINGERPRINT_CACHE: dict[int, tuple[ReferenceType[BaseGeometry], bytes]] = {}


@contextmanager
def preserve_corridor_coverage_decisions() -> Iterator[None]:
    """Reuse scalar corridor decisions within one Step3 orchestration only."""

    global _COVERAGE_DECISION_CACHE_DEPTH
    if _COVERAGE_DECISION_CACHE_DEPTH == 0:
        _clear_corridor_coverage_decisions()
    _COVERAGE_DECISION_CACHE_DEPTH += 1
    try:
        yield
    finally:
        _COVERAGE_DECISION_CACHE_DEPTH -= 1
        if _COVERAGE_DECISION_CACHE_DEPTH == 0:
            _clear_corridor_coverage_decisions()


def cached_corridor_coverage_decision(
    *,
    line: BaseGeometry,
    road_geometries: Iterable[BaseGeometry],
    allowed_surface: BaseGeometry | None,
    buffer_m: float,
    compute: Callable[[], CoverageDecision],
) -> CoverageDecision:
    if _COVERAGE_DECISION_CACHE_DEPTH <= 0:
        return compute()
    key = (
        _geometry_fingerprint(line),
        tuple(sorted(_geometry_fingerprint(geometry) for geometry in road_geometries)),
        _geometry_fingerprint(allowed_surface) if allowed_surface is not None else None,
        float(buffer_m),
    )
    cached = _COVERAGE_DECISION_CACHE.get(key)
    if cached is not None:
        return cached
    result = compute()
    if len(_COVERAGE_DECISION_CACHE) < _MAX_COVERAGE_DECISIONS:
        _COVERAGE_DECISION_CACHE[key] = result
    return result


def cached_buffered_road_corridor(
    *,
    road_geometries: Iterable[BaseGeometry],
    buffer_m: float,
    compute: Callable[[], BaseGeometry],
) -> BaseGeometry:
    if _COVERAGE_DECISION_CACHE_DEPTH <= 0:
        return compute()
    key = (
        tuple(sorted(_geometry_fingerprint(geometry) for geometry in road_geometries)),
        float(buffer_m),
    )
    cached = _BUFFERED_CORRIDOR_CACHE.get(key)
    if cached is not None:
        _BUFFERED_CORRIDOR_CACHE.move_to_end(key)
        return cached
    result = compute()
    _BUFFERED_CORRIDOR_CACHE[key] = result
    if len(_BUFFERED_CORRIDOR_CACHE) > _MAX_BUFFERED_CORRIDORS:
        _BUFFERED_CORRIDOR_CACHE.popitem(last=False)
    return result


def _geometry_fingerprint(geometry: BaseGeometry) -> bytes:
    identity = id(geometry)
    cached = _GEOMETRY_FINGERPRINT_CACHE.get(identity)
    if cached is not None and cached[0]() is geometry:
        return cached[1]
    fingerprint = blake2b(geometry.wkb, digest_size=16).digest()
    _GEOMETRY_FINGERPRINT_CACHE[identity] = (ref(geometry), fingerprint)
    return fingerprint


def _corridor_coverage_decision_cache_size() -> int:
    return len(_COVERAGE_DECISION_CACHE)


def _buffered_corridor_cache_size() -> int:
    return len(_BUFFERED_CORRIDOR_CACHE)


def _clear_corridor_coverage_decisions() -> None:
    _COVERAGE_DECISION_CACHE.clear()
    _BUFFERED_CORRIDOR_CACHE.clear()
    _GEOMETRY_FINGERPRINT_CACHE.clear()
