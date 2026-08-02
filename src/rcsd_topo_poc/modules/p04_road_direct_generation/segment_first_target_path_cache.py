from __future__ import annotations

from collections import OrderedDict
import hashlib
import math
from threading import RLock
import weakref

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString

from .segment_first_path_scoring import (
    build_target_path_metrics,
    target_path_score,
)


_MAX_ENTRIES = 32768
_MAX_KEY_BYTES = 64 * 1024 * 1024
_CACHE: OrderedDict[
    tuple[object, ...],
    tuple[tuple[str, ...], int],
] = OrderedDict()
_PAIR_SIGNATURES: dict[
    int,
    tuple[weakref.ReferenceType[pd.DataFrame], bytes, int, int],
] = {}
_LOCK = RLock()
_KEY_BYTES = 0
_HITS = 0
_MISSES = 0
_EVICTIONS = 0


def select_directed_target_path(
    evidence: gpd.GeoDataFrame,
    reference: LineString,
    explicit_pairs: pd.DataFrame | None,
    *,
    required_surfaces: tuple[object, ...] = (),
    surface_max_distance_m: float = 20.0,
) -> gpd.GeoDataFrame:
    """Return the original path-selection result with a bounded value cache."""
    if evidence.empty or explicit_pairs is None or explicit_pairs.empty:
        return evidence
    key, key_bytes = _selection_key(
        evidence,
        reference,
        explicit_pairs,
        required_surfaces,
        surface_max_distance_m,
    )
    selected_keys = _lookup(key)
    if selected_keys is None:
        selected_keys = _selected_keys_uncached(
            evidence,
            reference,
            explicit_pairs,
            required_surfaces=required_surfaces,
            surface_max_distance_m=surface_max_distance_m,
        )
        _store(key, selected_keys, key_bytes)
    return evidence[
        evidence["patch_road_key"].astype(str).isin(selected_keys)
    ].copy()


def _selected_keys_uncached(
    evidence: gpd.GeoDataFrame,
    reference: LineString,
    explicit_pairs: pd.DataFrame,
    *,
    required_surfaces: tuple[object, ...],
    surface_max_distance_m: float,
) -> tuple[str, ...]:
    by_key = {
        str(key): group.copy()
        for key, group in evidence.groupby("patch_road_key", sort=True)
    }
    candidate_keys = set(by_key)
    surface_mask_by_key = {
        key: sum(
            1 << index
            for index, surface in enumerate(required_surfaces)
            if float(group.geometry.distance(surface).min())
            <= surface_max_distance_m
        )
        for key, group in by_key.items()
    }
    relevant = explicit_pairs[
        explicit_pairs["source_patch_road_key"].astype(str).isin(candidate_keys)
        & explicit_pairs["target_patch_road_key"].astype(str).isin(candidate_keys)
    ]
    adjacency: dict[str, set[str]] = {}
    for pair in relevant.itertuples():
        adjacency.setdefault(str(pair.source_patch_road_key), set()).add(
            str(pair.target_patch_road_key)
        )
    paths: list[tuple[str, ...]] = []

    def visit(path: tuple[str, ...]) -> None:
        if len(paths) >= 10000:
            return
        paths.append(path)
        for target in sorted(adjacency.get(path[-1], set())):
            if target not in path:
                visit((*path, target))

    for key in sorted(candidate_keys):
        visit((key,))
    if not paths:
        return tuple(sorted(candidate_keys))
    path_metrics = build_target_path_metrics(by_key, reference)
    best = max(
        paths,
        key=lambda path: target_path_score(
            path,
            path_metrics,
            float(reference.length),
            surface_mask_by_key,
            len(required_surfaces),
        ),
    )
    selected = evidence[
        evidence["patch_road_key"].astype(str).isin(best)
    ]
    if (
        required_surfaces
        and not _covers_required_surfaces(
            selected,
            required_surfaces,
            maximum_distance_m=surface_max_distance_m,
        )
        and _covers_required_surfaces(
            evidence,
            required_surfaces,
            maximum_distance_m=surface_max_distance_m,
        )
    ):
        return tuple(sorted(candidate_keys))
    return tuple(best)


def _covers_required_surfaces(
    evidence: gpd.GeoDataFrame,
    required_surfaces: tuple[object, ...],
    *,
    maximum_distance_m: float,
) -> bool:
    return not evidence.empty and all(
        float(evidence.geometry.distance(surface).min())
        <= maximum_distance_m + 1e-9
        for surface in required_surfaces
    )


def _selection_key(
    evidence: gpd.GeoDataFrame,
    reference: LineString,
    explicit_pairs: pd.DataFrame,
    required_surfaces: tuple[object, ...],
    surface_max_distance_m: float,
) -> tuple[tuple[object, ...], int]:
    scores = evidence.get(
        "assignment_score",
        pd.Series(math.nan, index=evidence.index),
    )
    supports = evidence.get(
        "full_rcsd_anchor_supported",
        pd.Series(pd.NA, index=evidence.index),
    )
    rows = tuple(
        sorted(
            (
                str(patch_key),
                _geometry_wkb(geometry),
                _finite_score(score),
                _truth_token(support),
            )
            for patch_key, geometry, score, support in zip(
                evidence["patch_road_key"].array,
                evidence.geometry.array,
                scores.array,
                supports.array,
            )
        )
    )
    pair_signature = _explicit_pair_signature(explicit_pairs)
    reference_wkb = _geometry_wkb(reference)
    surface_wkbs = tuple(_geometry_wkb(surface) for surface in required_surfaces)
    key = (
        rows,
        reference_wkb,
        surface_wkbs,
        (id(explicit_pairs), pair_signature[0], pair_signature[1]),
        float(surface_max_distance_m),
    )
    key_bytes = (
        sum(
            len(row[0].encode("utf-8")) + len(row[1]) + 24
            for row in rows
        )
        + len(reference_wkb)
        + sum(len(value) for value in surface_wkbs)
        + 96
    )
    return key, key_bytes


def _explicit_pair_signature(
    explicit_pairs: pd.DataFrame,
) -> tuple[bytes, int]:
    object_id = id(explicit_pairs)
    with _LOCK:
        cached = _PAIR_SIGNATURES.get(object_id)
        if cached is not None and cached[0]() is explicit_pairs:
            return cached[1], cached[3]
    pairs = tuple(
        sorted(
            {
                (str(source), str(target))
                for source, target in zip(
                    explicit_pairs["source_patch_road_key"].array,
                    explicit_pairs["target_patch_road_key"].array,
                )
            }
        )
    )
    digest = hashlib.sha256()
    size = 0
    for source, target in pairs:
        for value in (source, target):
            encoded = value.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
            size += len(encoded) + 8
    with _LOCK:
        _PAIR_SIGNATURES[object_id] = (
            weakref.ref(explicit_pairs),
            digest.digest(),
            size,
            len(pairs),
        )
    return digest.digest(), len(pairs)


def _geometry_wkb(geometry: object) -> bytes:
    if geometry is None:
        return b""
    try:
        return bytes(geometry.wkb)
    except (AttributeError, TypeError, ValueError):
        return b""


def _finite_score(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _truth_token(value: object) -> bool | None:
    missing = pd.isna(value)
    if isinstance(missing, (bool, np.bool_)) and bool(missing):
        return None
    return bool(value)


def _lookup(key: tuple[object, ...]) -> tuple[str, ...] | None:
    global _HITS
    global _MISSES
    with _LOCK:
        cached = _CACHE.pop(key, None)
        if cached is None:
            _MISSES += 1
            return None
        _CACHE[key] = cached
        _HITS += 1
        return cached[0]


def _store(
    key: tuple[object, ...],
    selected_keys: tuple[str, ...],
    key_bytes: int,
) -> None:
    global _EVICTIONS
    global _KEY_BYTES
    with _LOCK:
        previous = _CACHE.pop(key, None)
        if previous is not None:
            _KEY_BYTES -= previous[1]
        _CACHE[key] = (selected_keys, int(key_bytes))
        _KEY_BYTES += int(key_bytes)
        while len(_CACHE) > _MAX_ENTRIES or _KEY_BYTES > _MAX_KEY_BYTES:
            _, evicted = _CACHE.popitem(last=False)
            _KEY_BYTES -= evicted[1]
            _EVICTIONS += 1


def target_path_cache_stats() -> dict[str, int | float]:
    with _LOCK:
        query_count = _HITS + _MISSES
        return {
            "query_count": query_count,
            "hit_count": _HITS,
            "miss_count": _MISSES,
            "hit_ratio": _HITS / query_count if query_count else 0.0,
            "eviction_count": _EVICTIONS,
            "entry_count": len(_CACHE),
            "entry_count_max": _MAX_ENTRIES,
            "key_bytes": _KEY_BYTES,
            "key_bytes_max": _MAX_KEY_BYTES,
            "pair_signature_count": len(_PAIR_SIGNATURES),
            "pair_signature_bytes": sum(
                cached[2] for cached in _PAIR_SIGNATURES.values()
            ),
        }


def reset_target_path_cache() -> None:
    global _EVICTIONS
    global _HITS
    global _KEY_BYTES
    global _MISSES
    with _LOCK:
        _CACHE.clear()
        _PAIR_SIGNATURES.clear()
        _KEY_BYTES = 0
        _HITS = 0
        _MISSES = 0
        _EVICTIONS = 0


__all__ = [
    "reset_target_path_cache",
    "select_directed_target_path",
    "target_path_cache_stats",
]
