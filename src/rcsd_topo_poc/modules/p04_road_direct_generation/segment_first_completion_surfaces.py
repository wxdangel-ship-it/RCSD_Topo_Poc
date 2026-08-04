from __future__ import annotations

from collections import OrderedDict
from typing import Iterable, Mapping
import weakref

import geopandas as gpd
from shapely import STRtree
from shapely.geometry import GeometryCollection, Point
from shapely.ops import unary_union

from .segment_first_geometry_cache import buffered_union
from .segment_first_progress import (
    advance_progress,
    begin_progress_stage,
    finish_progress_stage,
)


_ACCEPTED_JUNCTION_SOURCES = frozenset(
    {"t07_accepted", "t03_accepted", "t04_accepted"}
)
_BUFFER_CACHE_MAX_ENTRIES = 2048
_COMPLETION_SURFACE_CACHE: dict[
    tuple[int, float],
    tuple[
        weakref.ReferenceType[gpd.GeoDataFrame],
        Mapping[str, object],
        Mapping[str, Mapping[str, str]],
        "IndexedCompletionSurface",
    ],
] = {}


class IndexedCompletionSurface:
    """Exact local view of DriveZone plus buffered accepted Junction surfaces.

    The former implementation materialized one city-scale Junction union, its
    buffer, and a second union with DriveZone at the same time.  This object
    keeps the already grouped Junction geometries and creates only the pieces
    intersecting the current endpoint or short completion query.
    """

    __slots__ = (
        "drivezone_surface",
        "junction_surfaces",
        "buffer_m",
        "_tree",
        "_buffer_cache",
    )

    def __init__(
        self,
        drivezone_surface: object,
        junction_surfaces: Iterable[object],
        *,
        buffer_m: float,
    ) -> None:
        self.drivezone_surface = drivezone_surface
        self.junction_surfaces = tuple(
            geometry
            for geometry in junction_surfaces
            if geometry is not None and not geometry.is_empty
        )
        self.buffer_m = float(buffer_m)
        self._tree = (
            STRtree(self.junction_surfaces)
            if self.junction_surfaces
            else None
        )
        self._buffer_cache: OrderedDict[int, object] = OrderedDict()

    @property
    def is_empty(self) -> bool:
        return bool(
            getattr(self.drivezone_surface, "is_empty", True)
            and not self.junction_surfaces
        )

    def covers_point(self, point: Point, *, epsilon: float = 1e-9) -> bool:
        if self.is_empty or point is None or point.is_empty:
            return False
        if (
            not getattr(self.drivezone_surface, "is_empty", True)
            and float(point.distance(self.drivezone_surface)) <= epsilon
        ):
            return True
        if self._tree is None:
            return False
        return bool(
            len(
                self._tree.query(
                    point,
                    predicate="dwithin",
                    distance=max(0.0, self.buffer_m + epsilon),
                )
            )
        )

    def distance(self, geometry: object) -> float:
        if geometry is None or geometry.is_empty or self.is_empty:
            return float("inf")
        distances: list[float] = []
        if not getattr(self.drivezone_surface, "is_empty", True):
            distances.append(float(geometry.distance(self.drivezone_surface)))
        if self._tree is not None:
            nearest_index = int(self._tree.nearest(geometry))
            distances.append(
                max(
                    0.0,
                    float(
                        geometry.distance(
                            self.junction_surfaces[nearest_index]
                        )
                    )
                    - self.buffer_m,
                )
            )
        return min(distances) if distances else float("inf")

    def local_surface_for(self, geometry: object) -> object:
        if geometry is None or geometry.is_empty:
            return GeometryCollection()
        scope = geometry.envelope.buffer(max(self.buffer_m, 1e-6))
        return self.local_geometry(scope)

    def local_geometry(
        self,
        scope: object,
        *,
        extra_surfaces: Iterable[object] = (),
    ) -> object:
        if scope is None or scope.is_empty:
            return GeometryCollection()
        parts: list[object] = []
        if not getattr(self.drivezone_surface, "is_empty", True):
            drivezone_part = self.drivezone_surface.intersection(scope)
            if not drivezone_part.is_empty:
                parts.append(drivezone_part)
        if self._tree is not None:
            candidate_indexes = sorted(
                int(index)
                for index in self._tree.query(
                    scope,
                    predicate="dwithin",
                    distance=max(0.0, self.buffer_m),
                )
            )
            for index in candidate_indexes:
                candidate = self._buffered_junction(index).intersection(scope)
                if not candidate.is_empty:
                    parts.append(candidate)
        for surface in extra_surfaces:
            if surface is None or surface.is_empty:
                continue
            candidate = surface.intersection(scope)
            if not candidate.is_empty:
                parts.append(candidate)
        if not parts:
            return GeometryCollection()
        if len(parts) == 1:
            return parts[0]
        return unary_union(parts)

    def _buffered_junction(self, index: int) -> object:
        cached = self._buffer_cache.get(index)
        if cached is not None:
            self._buffer_cache.move_to_end(index)
            return cached
        value = self.junction_surfaces[index].buffer(self.buffer_m)
        self._buffer_cache[index] = value
        self._buffer_cache.move_to_end(index)
        while len(self._buffer_cache) > _BUFFER_CACHE_MAX_ENTRIES:
            self._buffer_cache.popitem(last=False)
        return value


def build_completion_surfaces(
    drivezones: gpd.GeoDataFrame,
    junction_surface_by_group: Mapping[str, object],
    junction_context_by_group: Mapping[str, Mapping[str, str]],
    *,
    buffer_m: float,
) -> tuple[object, IndexedCompletionSurface]:
    key = (id(drivezones), float(buffer_m))
    entry = _COMPLETION_SURFACE_CACHE.get(key)
    if (
        entry is not None
        and entry[0]() is drivezones
        and entry[1] is junction_surface_by_group
        and entry[2] is junction_context_by_group
    ):
        begin_progress_stage(
            "node_completion_surface",
            1,
            detail="reuse indexed DriveZone and accepted Junction surfaces",
            counters={"cache_hit": 1},
        )
        advance_progress(
            "node_completion_surface",
            last_unit="cached",
            counters={"cache_hit": 1},
        )
        finish_progress_stage(
            "node_completion_surface",
            counters={"cache_hit": 1},
        )
        return entry[3].drivezone_surface, entry[3]

    accepted_group_ids = sorted(
        group_id
        for group_id, context in junction_context_by_group.items()
        if str(context.get("junction_source", ""))
        in _ACCEPTED_JUNCTION_SOURCES
        and group_id in junction_surface_by_group
    )
    begin_progress_stage(
        "node_completion_surface",
        len(accepted_group_ids) + 2,
        detail="index DriveZone and accepted Junction surfaces",
        counters={
            "accepted_group_count": len(accepted_group_ids),
            "cache_hit": 0,
        },
    )
    drivezone_surface = (
        buffered_union(drivezones, buffer_m)
        if not drivezones.empty
        else GeometryCollection()
    )
    advance_progress(
        "node_completion_surface",
        last_unit="drivezone",
        counters={"indexed_junction_count": 0},
    )
    accepted_surfaces: list[object] = []
    for group_id in accepted_group_ids:
        geometry = junction_surface_by_group[group_id]
        if geometry is not None and not geometry.is_empty:
            accepted_surfaces.append(geometry)
        advance_progress(
            "node_completion_surface",
            last_unit=group_id,
            counters={"indexed_junction_count": len(accepted_surfaces)},
        )
    completion_surface = IndexedCompletionSurface(
        drivezone_surface,
        accepted_surfaces,
        buffer_m=buffer_m,
    )
    advance_progress(
        "node_completion_surface",
        last_unit="spatial_index",
        counters={"indexed_junction_count": len(accepted_surfaces)},
    )
    finish_progress_stage(
        "node_completion_surface",
        counters={
            "accepted_group_count": len(accepted_group_ids),
            "indexed_junction_count": len(accepted_surfaces),
            "cache_hit": 0,
        },
    )

    def remove(_: weakref.ReferenceType[gpd.GeoDataFrame]) -> None:
        current = _COMPLETION_SURFACE_CACHE.get(key)
        if current is not None and current[0]() is None:
            _COMPLETION_SURFACE_CACHE.pop(key, None)

    _COMPLETION_SURFACE_CACHE[key] = (
        weakref.ref(drivezones, remove),
        junction_surface_by_group,
        junction_context_by_group,
        completion_surface,
    )
    return drivezone_surface, completion_surface


def completion_surface_covers_point(
    completion_surface: object | None,
    point: Point,
    *,
    epsilon: float = 1e-9,
) -> bool:
    if completion_surface is None:
        return True
    if isinstance(completion_surface, IndexedCompletionSurface):
        return completion_surface.covers_point(point, epsilon=epsilon)
    return bool(
        not getattr(completion_surface, "is_empty", True)
        and float(point.distance(completion_surface)) <= epsilon
    )


def completion_surface_local_geometry(
    completion_surface: object,
    scope: object,
    *,
    extra_surfaces: Iterable[object] = (),
) -> object:
    if isinstance(completion_surface, IndexedCompletionSurface):
        return completion_surface.local_geometry(
            scope,
            extra_surfaces=extra_surfaces,
        )
    parts = [completion_surface, *extra_surfaces]
    return unary_union(
        [part for part in parts if part is not None and not part.is_empty]
    ).intersection(scope)


__all__ = [
    "IndexedCompletionSurface",
    "build_completion_surfaces",
    "completion_surface_covers_point",
    "completion_surface_local_geometry",
]
