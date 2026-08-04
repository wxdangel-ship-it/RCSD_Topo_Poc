from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
import time
from typing import Callable, TypeVar
import weakref

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, box

from .segment_first_skeleton import canonical_id


@dataclass(frozen=True)
class AssignmentPlanningContext:
    eligible: gpd.GeoDataFrame
    recovery_candidates: gpd.GeoDataFrame
    access_reservation_buffers: gpd.GeoDataFrame
    evidence_by_member: dict[tuple[str, str], gpd.GeoDataFrame]
    eligible_by_segment: dict[str, gpd.GeoDataFrame]
    recovery_by_segment: dict[str, gpd.GeoDataFrame]
    empty_eligible: gpd.GeoDataFrame
    empty_recovery: gpd.GeoDataFrame


@dataclass
class _FrameCacheEntry:
    frame_ref: weakref.ReferenceType[pd.DataFrame]
    manager_id: int
    value: object


T = TypeVar("T")

_LOCK = RLock()
_FRAME_CACHE: dict[str, _FrameCacheEntry] = {}
_STATS: dict[str, int | float] = {
    "carrier_context_cache_hit_count": 0,
    "carrier_context_cache_miss_count": 0,
    "carrier_context_prepare_seconds": 0.0,
}


def prepare_road_by_id(swsd_roads: gpd.GeoDataFrame) -> pd.DataFrame:
    def build() -> pd.DataFrame:
        road_frame = swsd_roads.copy()
        road_frame["canonical_road_id"] = road_frame["id"].map(canonical_id)
        return road_frame.drop_duplicates("canonical_road_id").set_index(
            "canonical_road_id"
        )

    return _cached_frame_value("road_by_id", swsd_roads, build)


def prepare_assignment_context(
    assignments: gpd.GeoDataFrame,
) -> AssignmentPlanningContext:
    def build() -> AssignmentPlanningContext:
        eligible = (
            assignments[
                assignments.get("takeover_eligible", True)
                .fillna(False)
                .astype(bool)
            ].copy()
            if not assignments.empty
            else assignments.copy()
        )
        recovery_candidates = (
            assignments[
                assignments.get(
                    "assignment_source",
                    pd.Series(index=assignments.index, dtype=str),
                )
                .fillna("")
                .isin(
                    {
                        "target_baseline_recovery_candidate",
                        "target_access_surface_candidate",
                    }
                )
            ].copy()
            if not assignments.empty
            else assignments.copy()
        )
        access_reservations = (
            recovery_candidates[
                recovery_candidates["assignment_source"]
                .fillna("")
                .eq("target_access_surface_candidate")
            ].copy()
            if not recovery_candidates.empty
            else recovery_candidates.copy()
        )
        access_reservation_buffers = access_reservations.copy()
        if not access_reservation_buffers.empty:
            access_reservation_buffers.geometry = (
                access_reservation_buffers.geometry.buffer(1.0)
            )
            access_reservation_buffers["_reservation_segment_id"] = (
                access_reservation_buffers["assigned_segment_id"].astype(str)
            )
        if not eligible.empty and "carrier_role" not in eligible:
            eligible["carrier_role"] = "directional_corridor"
        evidence_by_member = (
            {
                (str(segment_id), str(road_id)): group.copy()
                for (segment_id, road_id), group in eligible.groupby(
                    ["assigned_segment_id", "target_swsd_road_id"]
                )
            }
            if not eligible.empty
            else {}
        )
        eligible_by_segment = (
            {
                str(segment_id): group.copy()
                for segment_id, group in eligible.groupby(
                    eligible["assigned_segment_id"].astype(str),
                    sort=False,
                )
            }
            if not eligible.empty
            else {}
        )
        recovery_by_segment = (
            {
                str(segment_id): group.copy()
                for segment_id, group in recovery_candidates.groupby(
                    recovery_candidates["assigned_segment_id"].astype(str),
                    sort=False,
                )
            }
            if not recovery_candidates.empty
            else {}
        )
        return AssignmentPlanningContext(
            eligible=eligible,
            recovery_candidates=recovery_candidates,
            access_reservation_buffers=access_reservation_buffers,
            evidence_by_member=evidence_by_member,
            eligible_by_segment=eligible_by_segment,
            recovery_by_segment=recovery_by_segment,
            empty_eligible=eligible.iloc[0:0],
            empty_recovery=recovery_candidates.iloc[0:0],
        )

    return _cached_frame_value("assignment_context", assignments, build)


def prepare_reference_by_segment(
    target_reference_axes: gpd.GeoDataFrame | None,
) -> dict[str, LineString | None]:
    if target_reference_axes is None:
        return {}

    def build() -> dict[str, LineString | None]:
        if target_reference_axes.empty:
            return {}
        return {
            str(segment_id): longest_line(group.geometry.union_all())
            for segment_id, group in target_reference_axes.groupby("segment_id")
        }

    return _cached_frame_value("reference_by_segment", target_reference_axes, build)


def prepare_through_surfaces_by_segment(
    required_through_surfaces: gpd.GeoDataFrame | None,
) -> dict[str, tuple[tuple[str, object], ...]]:
    if required_through_surfaces is None:
        return {}

    def build() -> dict[str, tuple[tuple[str, object], ...]]:
        if required_through_surfaces.empty:
            return {}
        return {
            str(segment_id): tuple(
                (
                    str(getattr(row, "access_id", f"surface:{index}")),
                    row.geometry,
                )
                for index, row in enumerate(group.itertuples(index=False))
            )
            for segment_id, group in required_through_surfaces.groupby("segment_id")
        }

    return _cached_frame_value(
        "through_surfaces_by_segment",
        required_through_surfaces,
        build,
    )


def prepare_endpoint_surfaces_by_segment(
    required_endpoint_surfaces: gpd.GeoDataFrame | None,
) -> dict[str, tuple[object, ...]]:
    if required_endpoint_surfaces is None:
        return {}

    def build() -> dict[str, tuple[object, ...]]:
        if required_endpoint_surfaces.empty:
            return {}
        return {
            str(segment_id): tuple(group.geometry)
            for segment_id, group in required_endpoint_surfaces.groupby("segment_id")
        }

    return _cached_frame_value(
        "endpoint_surfaces_by_segment",
        required_endpoint_surfaces,
        build,
    )


def reservation_overlap_fraction(
    geometry: LineString,
    reservations: gpd.GeoDataFrame | None,
    *,
    excluded_segment_id: str = "",
    prebuffered: bool = False,
    buffer_m: float = 1.0,
) -> float:
    if reservations is None or reservations.empty:
        return 0.0
    if prebuffered:
        query_geometry = geometry
    else:
        minimum_x, minimum_y, maximum_x, maximum_y = geometry.bounds
        query_geometry = box(
            minimum_x - buffer_m,
            minimum_y - buffer_m,
            maximum_x + buffer_m,
            maximum_y + buffer_m,
        )
    candidate_indexes = reservations.sindex.query(query_geometry)
    maximum = 0.0
    for candidate_index in candidate_indexes:
        reservation = reservations.iloc[int(candidate_index)]
        reservation_segment_id = str(
            reservation.get(
                "_reservation_segment_id",
                reservation.get("assigned_segment_id", ""),
            )
        )
        if excluded_segment_id and reservation_segment_id == excluded_segment_id:
            continue
        reservation_geometry = reservation.geometry
        if reservation_geometry is None or reservation_geometry.is_empty:
            continue
        if not prebuffered:
            reservation_geometry = reservation_geometry.buffer(buffer_m)
        overlap = float(geometry.intersection(reservation_geometry).length) / float(
            geometry.length
        )
        maximum = max(maximum, overlap)
    return maximum


def longest_line(geometry: object) -> LineString | None:
    if geometry is None or getattr(geometry, "is_empty", True):
        return None
    if geometry.geom_type == "LineString":
        return geometry
    parts = [part for part in geometry.geoms if part.geom_type == "LineString"]
    return max(parts, key=lambda part: float(part.length)) if parts else None


def carrier_context_cache_stats() -> dict[str, int | float]:
    with _LOCK:
        stats = dict(_STATS)
        stats["carrier_context_cache_entry_count"] = len(_FRAME_CACHE)
    return stats


def reset_carrier_context_cache() -> None:
    with _LOCK:
        _FRAME_CACHE.clear()
        for key in _STATS:
            _STATS[key] = 0.0 if key.endswith("_seconds") else 0


def _cached_frame_value(
    role: str,
    frame: pd.DataFrame,
    builder: Callable[[], T],
) -> T:
    with _LOCK:
        cached = _FRAME_CACHE.get(role)
        if (
            cached is not None
            and cached.frame_ref() is frame
            and cached.manager_id == id(frame._mgr)
        ):
            _STATS["carrier_context_cache_hit_count"] += 1
            return cached.value  # type: ignore[return-value]
        _FRAME_CACHE.pop(role, None)
        _STATS["carrier_context_cache_miss_count"] += 1
    started = time.perf_counter()
    value = builder()
    elapsed = time.perf_counter() - started

    def remove(_: weakref.ReferenceType[pd.DataFrame]) -> None:
        with _LOCK:
            current = _FRAME_CACHE.get(role)
            if current is not None and current.frame_ref() is None:
                _FRAME_CACHE.pop(role, None)

    with _LOCK:
        _FRAME_CACHE[role] = _FrameCacheEntry(
            weakref.ref(frame, remove),
            id(frame._mgr),
            value,
        )
        _STATS["carrier_context_prepare_seconds"] += elapsed
    return value


__all__ = [
    "AssignmentPlanningContext",
    "carrier_context_cache_stats",
    "longest_line",
    "prepare_assignment_context",
    "prepare_endpoint_surfaces_by_segment",
    "prepare_reference_by_segment",
    "prepare_road_by_id",
    "prepare_through_surfaces_by_segment",
    "reservation_overlap_fraction",
    "reset_carrier_context_cache",
]
