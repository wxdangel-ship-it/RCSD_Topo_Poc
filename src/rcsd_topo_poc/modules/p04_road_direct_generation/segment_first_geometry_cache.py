from __future__ import annotations

import weakref

import geopandas as gpd
from shapely.geometry import GeometryCollection


_BUFFERED_UNION_CACHE: dict[
    tuple[int, float],
    tuple[weakref.ReferenceType[gpd.GeoDataFrame], int, object],
] = {}


def buffered_union(
    frame: gpd.GeoDataFrame | None,
    buffer_m: float,
) -> object:
    """Return one exact buffered union per live GeoDataFrame identity."""

    if frame is None or frame.empty:
        return GeometryCollection()
    key = (id(frame), float(buffer_m))
    entry = _BUFFERED_UNION_CACHE.get(key)
    if (
        entry is not None
        and entry[0]() is frame
        and entry[1] == id(frame._mgr)
    ):
        return entry[2]

    value = frame.geometry.union_all().buffer(buffer_m)

    def remove(_: weakref.ReferenceType[gpd.GeoDataFrame]) -> None:
        current = _BUFFERED_UNION_CACHE.get(key)
        if current is not None and current[0]() is None:
            _BUFFERED_UNION_CACHE.pop(key, None)

    _BUFFERED_UNION_CACHE[key] = (
        weakref.ref(frame, remove),
        id(frame._mgr),
        value,
    )
    return value
