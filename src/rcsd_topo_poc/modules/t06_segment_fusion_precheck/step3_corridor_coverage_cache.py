from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from hashlib import blake2b
from weakref import ReferenceType, ref

from shapely.geometry.base import BaseGeometry


CoverageDecision = tuple[bool, bool]
CoverageDecisionKey = tuple[bytes, tuple[bytes, ...], bytes | None, float]

_MAX_COVERAGE_DECISIONS = 50_000
_COVERAGE_DECISION_CACHE_DEPTH = 0
_COVERAGE_DECISION_CACHE: dict[CoverageDecisionKey, CoverageDecision] = {}
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


def _clear_corridor_coverage_decisions() -> None:
    _COVERAGE_DECISION_CACHE.clear()
    _GEOMETRY_FINGERPRINT_CACHE.clear()
