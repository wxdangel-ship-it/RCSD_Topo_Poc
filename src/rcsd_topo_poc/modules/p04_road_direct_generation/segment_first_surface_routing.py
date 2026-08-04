from __future__ import annotations

from collections import OrderedDict
import heapq
import math
from threading import RLock

from shapely.geometry import LineString, Point
from shapely.ops import nearest_points, unary_union

from .segment_first_completion_surfaces import (
    IndexedCompletionSurface,
    completion_surface_local_geometry,
)
from .segment_first_geometry_metrics import surface_coverage_at_least


_INTERIOR_TARGET_CACHE_ENTRY_MAX = 8192
_INTERIOR_TARGET_CACHE_KEY_BYTES_MAX = 32 * 1024 * 1024
_INTERIOR_TARGET_CACHE: OrderedDict[
    tuple[bytes, float],
    tuple[object, int],
] = OrderedDict()
_INTERIOR_TARGET_CACHE_KEY_BYTES = 0
_INTERIOR_TARGET_CACHE_QUERY_COUNT = 0
_INTERIOR_TARGET_CACHE_HIT_COUNT = 0
_INTERIOR_TARGET_CACHE_EVICTION_COUNT = 0
_INTERIOR_TARGET_CACHE_LOCK = RLock()


def interior_surface_target(
    surface: object,
    *,
    inset_m: float,
) -> object:
    """Return a target whose boundary is strictly inside the source surface."""

    if surface is None or surface.is_empty:
        return surface
    inset = max(float(inset_m), 1e-3)
    key, key_bytes = _interior_target_cache_key(surface, inset)
    if key is not None:
        cached = _interior_target_cache_get(key)
        if cached is not None:
            return cached
    core = surface.buffer(-inset)
    result = core if not core.is_empty else surface.representative_point()
    if key is not None:
        _interior_target_cache_put(key, result, key_bytes)
    return result


def interior_target_cache_stats() -> dict[str, int | float]:
    with _INTERIOR_TARGET_CACHE_LOCK:
        query_count = _INTERIOR_TARGET_CACHE_QUERY_COUNT
        return {
            "query_count": query_count,
            "hit_count": _INTERIOR_TARGET_CACHE_HIT_COUNT,
            "hit_ratio": (
                _INTERIOR_TARGET_CACHE_HIT_COUNT / query_count
                if query_count
                else 0.0
            ),
            "eviction_count": _INTERIOR_TARGET_CACHE_EVICTION_COUNT,
            "entry_count": len(_INTERIOR_TARGET_CACHE),
            "entry_count_max": _INTERIOR_TARGET_CACHE_ENTRY_MAX,
            "key_bytes": _INTERIOR_TARGET_CACHE_KEY_BYTES,
            "key_bytes_max": _INTERIOR_TARGET_CACHE_KEY_BYTES_MAX,
        }


def reset_interior_target_cache() -> None:
    global _INTERIOR_TARGET_CACHE_KEY_BYTES
    global _INTERIOR_TARGET_CACHE_QUERY_COUNT
    global _INTERIOR_TARGET_CACHE_HIT_COUNT
    global _INTERIOR_TARGET_CACHE_EVICTION_COUNT
    with _INTERIOR_TARGET_CACHE_LOCK:
        _INTERIOR_TARGET_CACHE.clear()
        _INTERIOR_TARGET_CACHE_KEY_BYTES = 0
        _INTERIOR_TARGET_CACHE_QUERY_COUNT = 0
        _INTERIOR_TARGET_CACHE_HIT_COUNT = 0
        _INTERIOR_TARGET_CACHE_EVICTION_COUNT = 0


def _interior_target_cache_key(
    surface: object,
    inset: float,
) -> tuple[tuple[bytes, float] | None, int]:
    try:
        geometry_wkb = bytes(surface.wkb)
    except (AttributeError, TypeError, ValueError):
        return None, 0
    key_bytes = len(geometry_wkb) + 8
    if key_bytes > _INTERIOR_TARGET_CACHE_KEY_BYTES_MAX:
        return None, key_bytes
    return (geometry_wkb, inset), key_bytes


def _interior_target_cache_get(
    key: tuple[bytes, float],
) -> object | None:
    global _INTERIOR_TARGET_CACHE_QUERY_COUNT
    global _INTERIOR_TARGET_CACHE_HIT_COUNT
    with _INTERIOR_TARGET_CACHE_LOCK:
        _INTERIOR_TARGET_CACHE_QUERY_COUNT += 1
        cached = _INTERIOR_TARGET_CACHE.get(key)
        if cached is None:
            return None
        _INTERIOR_TARGET_CACHE_HIT_COUNT += 1
        _INTERIOR_TARGET_CACHE.move_to_end(key)
        return cached[0]


def _interior_target_cache_put(
    key: tuple[bytes, float],
    value: object,
    key_bytes: int,
) -> None:
    global _INTERIOR_TARGET_CACHE_KEY_BYTES
    global _INTERIOR_TARGET_CACHE_EVICTION_COUNT
    with _INTERIOR_TARGET_CACHE_LOCK:
        existing = _INTERIOR_TARGET_CACHE.pop(key, None)
        if existing is not None:
            _INTERIOR_TARGET_CACHE_KEY_BYTES -= existing[1]
        while _INTERIOR_TARGET_CACHE and (
            len(_INTERIOR_TARGET_CACHE) >= _INTERIOR_TARGET_CACHE_ENTRY_MAX
            or _INTERIOR_TARGET_CACHE_KEY_BYTES + key_bytes
            > _INTERIOR_TARGET_CACHE_KEY_BYTES_MAX
        ):
            _, (_, evicted_key_bytes) = _INTERIOR_TARGET_CACHE.popitem(
                last=False
            )
            _INTERIOR_TARGET_CACHE_KEY_BYTES -= evicted_key_bytes
            _INTERIOR_TARGET_CACHE_EVICTION_COUNT += 1
        _INTERIOR_TARGET_CACHE[key] = (value, key_bytes)
        _INTERIOR_TARGET_CACHE_KEY_BYTES += key_bytes


def route_tangent_endpoint_to_surface(
    geometry: LineString,
    endpoint_name: str,
    target_surface: object,
    completion_surface: object,
    *,
    maximum_distance_m: float,
    minimum_coverage: float,
    tangent_sample_m: float = 12.0,
    maximum_detour_ratio: float = 1.25,
) -> LineString | None:
    """Extend the observed centreline tangent to any valid surface portal."""

    if (
        geometry is None
        or geometry.is_empty
        or geometry.length <= 1e-6
        or endpoint_name not in {"start", "end"}
        or target_surface is None
        or target_surface.is_empty
        or completion_surface is None
        or completion_surface.is_empty
    ):
        return None
    at_start = endpoint_name == "start"
    endpoint = Point(
        geometry.coords[0] if at_start else geometry.coords[-1]
    )
    direct_distance = float(endpoint.distance(target_surface))
    if (
        direct_distance <= 1e-9
        or direct_distance > maximum_distance_m + 1e-9
    ):
        return None
    sample_distance = min(
        max(2.0, tangent_sample_m),
        max(1.0, float(geometry.length) * 0.25),
    )
    interior = geometry.interpolate(
        min(sample_distance, float(geometry.length))
        if at_start
        else max(0.0, float(geometry.length) - sample_distance)
    )
    outward_x = float(endpoint.x - interior.x)
    outward_y = float(endpoint.y - interior.y)
    norm = math.hypot(outward_x, outward_y)
    if norm <= 1e-9:
        return None
    scale = maximum_distance_m / norm
    ray = LineString(
        [
            endpoint,
            Point(
                endpoint.x + outward_x * scale,
                endpoint.y + outward_y * scale,
            ),
        ]
    )
    intersection = ray.intersection(target_surface)
    if intersection.is_empty:
        return None
    portal = nearest_points(endpoint, intersection)[1]
    completion = LineString([endpoint, portal])
    if (
        completion.length <= 1e-9
        or completion.length > maximum_distance_m + 1e-9
        or completion.length
        > direct_distance * maximum_detour_ratio + 1e-9
        or not _coverage_at_least(
            completion,
            completion_surface,
            minimum_coverage,
            epsilon=1e-9,
        )
    ):
        return None
    return completion


def route_endpoint_to_surface(
    endpoint: Point,
    target_surface: object,
    completion_surface: object,
    *,
    maximum_distance_m: float,
    minimum_coverage: float,
    maximum_detour_ratio: float = 1.75,
) -> LineString | None:
    """Route one observed endpoint to a Junction surface inside local RoadSurface.

    The returned coordinates come only from the observed endpoint, the accepted
    target surface, and the supporting RoadSurface boundary.  No SWSD coordinate
    is used as a geometric carrier.
    """
    if (
        endpoint is None
        or endpoint.is_empty
        or target_surface is None
        or target_surface.is_empty
        or completion_surface is None
        or completion_surface.is_empty
        or maximum_distance_m <= 0.0
    ):
        return None
    direct_distance = float(endpoint.distance(target_surface))
    if direct_distance <= 1e-9 or direct_distance > maximum_distance_m + 1e-9:
        return None
    direct_target = nearest_points(endpoint, target_surface)[1]
    direct = LineString([endpoint, direct_target])
    if isinstance(completion_surface, IndexedCompletionSurface):
        direct_support = completion_surface_local_geometry(
            completion_surface,
            direct.envelope.buffer(1e-6),
            extra_surfaces=(target_surface,),
        )
        support = None
    else:
        support = completion_surface.union(target_surface)
        direct_support = support
    if _coverage_at_least(
        direct,
        direct_support,
        minimum_coverage,
        epsilon=1e-9,
    ):
        return direct

    scope_buffer = min(
        maximum_distance_m,
        max(2.0, direct_distance * 0.75),
    )
    local_scope = unary_union([endpoint, target_surface]).convex_hull.buffer(
        scope_buffer
    )
    local_support = (
        completion_surface_local_geometry(
            completion_surface,
            local_scope,
            extra_surfaces=(target_surface,),
        )
        if isinstance(completion_surface, IndexedCompletionSurface)
        else support.intersection(local_scope)
    )
    maximum_route_length = min(
        maximum_distance_m * 1.50,
        direct_distance * maximum_detour_ratio + 2.0,
    )
    candidates: list[tuple[float, LineString]] = []
    for component in _polygon_parts(local_support):
        if (
            not component.buffer(0.05).covers(endpoint)
            or component.intersection(target_surface).is_empty
        ):
            continue
        portal = component.intersection(target_surface)
        target = nearest_points(endpoint, portal)[1]
        routed = _visibility_shortest_path(component, endpoint, target)
        if routed is not None:
            routed = _inset_intermediate_vertices(
                routed,
                component,
                clearance_m=0.75,
            )
        if (
            routed is None
            or not routed.is_valid
            or not routed.is_simple
            or float(routed.length) > maximum_route_length + 1e-9
            or not _coverage_at_least(
                routed,
                local_support,
                minimum_coverage,
                epsilon=1e-9,
            )
        ):
            continue
        candidates.append((float(routed.length), routed))
    return min(candidates, key=lambda item: item[0])[1] if candidates else None


def _inset_intermediate_vertices(
    routed: LineString,
    support_component: object,
    *,
    clearance_m: float,
) -> LineString:
    core = support_component.buffer(-clearance_m)
    if core.is_empty or len(routed.coords) <= 2:
        return routed
    coordinates = [routed.coords[0]]
    for coordinate in list(routed.coords)[1:-1]:
        point = Point(coordinate)
        inset = point if core.covers(point) else nearest_points(point, core)[1]
        coordinates.append(inset.coords[0])
    coordinates.append(routed.coords[-1])
    candidate = LineString(coordinates)
    if (
        not candidate.is_valid
        or not candidate.is_simple
        or not _coverage_at_least(
            candidate,
            support_component,
            1.0 - 1e-9,
        )
    ):
        return routed
    return candidate


def _polygon_parts(geometry: object) -> list[object]:
    if geometry is None or geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [
        part
        for child in getattr(geometry, "geoms", ())
        for part in _polygon_parts(child)
    ]


def _visibility_shortest_path(
    polygon: object,
    start: Point,
    end: Point,
) -> LineString | None:
    coordinates: list[tuple[float, float]] | None = None
    for tolerance in (0.05, 0.10, 0.25, 0.50, 1.00):
        simplified = polygon.simplify(tolerance, preserve_topology=True)
        values = [start.coords[0], end.coords[0]]
        values.extend(list(simplified.exterior.coords)[:-1])
        for interior in simplified.interiors:
            values.extend(list(interior.coords)[:-1])
        coordinates = _unique_coordinates(values)
        if len(coordinates) <= 384:
            break
    if coordinates is None or len(coordinates) > 384:
        return None

    visible_surface = polygon.buffer(0.05)
    adjacency: dict[int, list[tuple[float, int]]] = {
        index: [] for index in range(len(coordinates))
    }
    for left in range(len(coordinates)):
        for right in range(left + 1, len(coordinates)):
            edge = LineString([coordinates[left], coordinates[right]])
            if not visible_surface.covers(edge):
                continue
            distance = float(edge.length)
            adjacency[left].append((distance, right))
            adjacency[right].append((distance, left))

    distances = {0: 0.0}
    previous: dict[int, int] = {}
    queue: list[tuple[float, int]] = [(0.0, 0)]
    while queue:
        distance, current = heapq.heappop(queue)
        if distance > distances.get(current, math.inf) + 1e-9:
            continue
        if current == 1:
            break
        for weight, target in adjacency[current]:
            candidate = distance + weight
            if candidate + 1e-9 < distances.get(target, math.inf):
                distances[target] = candidate
                previous[target] = current
                heapq.heappush(queue, (candidate, target))
    if 1 not in distances:
        return None
    indexes = [1]
    while indexes[-1] != 0:
        indexes.append(previous[indexes[-1]])
    indexes.reverse()
    return LineString([coordinates[index] for index in indexes])


def _unique_coordinates(
    coordinates: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    unique: list[tuple[float, float]] = []
    seen: set[tuple[float, float]] = set()
    for coordinate in coordinates:
        key = (round(float(coordinate[0]), 6), round(float(coordinate[1]), 6))
        if key in seen:
            continue
        seen.add(key)
        unique.append((float(coordinate[0]), float(coordinate[1])))
    return unique


def _coverage_at_least(
    line: LineString,
    surface: object,
    minimum_coverage: float,
    *,
    epsilon: float = 0.0,
) -> bool:
    if line.length <= 1e-9:
        return epsilon >= minimum_coverage
    return surface_coverage_at_least(
        line,
        surface,
        minimum_coverage,
        epsilon=epsilon,
    )


__all__ = [
    "interior_target_cache_stats",
    "interior_surface_target",
    "reset_interior_target_cache",
    "route_endpoint_to_surface",
    "route_tangent_endpoint_to_surface",
]
