from __future__ import annotations

from typing import Iterable, Sequence

from shapely.geometry import LineString
from shapely.geometry.base import BaseGeometry
from shapely.ops import nearest_points

from ._rcsd_selection_support import _normalize_geometry, _union_geometry
from .support_domain_common import _clip_to_drivezone
from .support_domain_scenario import (
    STEP5_BRIDGE_HALF_WIDTH_M,
    STEP5_FULL_FILL_BRIDGE_MAX_DISTANCE_M,
    STEP5_FULL_FILL_BRIDGE_MAX_EXISTING_OVERLAP_M2,
    STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M,
    STEP5_SUPPORT_GRAPH_PAD_M,
    STEP5_SUPPORT_ROAD_BUFFER_M,
)


def _geometry_or_empty_members(geometries: Iterable[BaseGeometry | None]) -> tuple[BaseGeometry, ...]:
    return tuple(
        geometry
        for geometry in (_normalize_geometry(item) for item in geometries)
        if geometry is not None
    )

def _nearest_bridge_patch(
    left: BaseGeometry,
    right: BaseGeometry,
    *,
    support_graph_geometry: BaseGeometry | None,
    drivezone_union: BaseGeometry | None,
    half_width_m: float = STEP5_BRIDGE_HALF_WIDTH_M,
    support_graph_pad_m: float = STEP5_SUPPORT_GRAPH_PAD_M,
) -> BaseGeometry | None:
    try:
        left_point, right_point = nearest_points(left, right)
    except Exception:
        return None
    if left_point is None or right_point is None:
        return None
    if left_point.distance(right_point) <= 1e-6:
        bridge = left_point.buffer(float(half_width_m))
    else:
        bridge = LineString([left_point, right_point]).buffer(
            float(half_width_m),
            cap_style=2,
            join_style=2,
        )
    if support_graph_geometry is not None and not support_graph_geometry.is_empty:
        bridge = bridge.intersection(
            support_graph_geometry.buffer(float(support_graph_pad_m))
        )
    return _clip_to_drivezone(bridge, drivezone_union)

def _multi_unit_full_fill_bridge_geometries(
    unit_results: Sequence[T04Step5UnitResult],
    *,
    support_graph_geometry: BaseGeometry | None,
    drivezone_union: BaseGeometry | None,
) -> list[BaseGeometry]:
    full_fill_geometries = [
        unit.junction_full_road_fill_domain
        for unit in unit_results
        if unit.junction_full_road_fill_domain is not None
        and not unit.junction_full_road_fill_domain.is_empty
    ]
    if len(full_fill_geometries) <= 1:
        return []

    bridges: list[BaseGeometry] = []
    current_geometry = full_fill_geometries[0]
    remaining = list(full_fill_geometries[1:])
    while remaining:
        best_index = 0
        best_distance = float("inf")
        for index, candidate in enumerate(remaining):
            distance = float(current_geometry.distance(candidate))
            if distance < best_distance:
                best_distance = distance
                best_index = index
        candidate = remaining.pop(best_index)
        overlap_area = float(current_geometry.intersection(candidate).area)
        if (
            best_distance <= STEP5_FULL_FILL_BRIDGE_MAX_DISTANCE_M
            and overlap_area < STEP5_FULL_FILL_BRIDGE_MAX_EXISTING_OVERLAP_M2
        ):
            bridge_geometry = _nearest_bridge_patch(
                current_geometry,
                candidate,
                support_graph_geometry=support_graph_geometry,
                drivezone_union=drivezone_union,
                half_width_m=STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M,
                support_graph_pad_m=STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M,
            )
            if bridge_geometry is not None and not bridge_geometry.is_empty:
                bridges.append(bridge_geometry)
        current_geometry = _clip_to_drivezone(
            _union_geometry([current_geometry, candidate, *bridges]),
            drivezone_union,
        ) or current_geometry
    return bridges

def _has_case_level_rcsd_bridge_support(unit_results: Sequence[T04Step5UnitResult]) -> bool:
    if len(unit_results) <= 1:
        return False
    supported_unit_count = sum(
        1
        for unit in unit_results
        if unit.required_rcsd_node
        or unit.positive_rcsd_road_ids
        or unit.fallback_rcsdroad_ids
        or unit.fallback_support_strip_geometry is not None
    )
    return supported_unit_count >= 2

def _case_level_rcsd_bridge_geometries(
    unit_results: Sequence[T04Step5UnitResult],
    *,
    support_graph_geometry: BaseGeometry | None,
    drivezone_union: BaseGeometry | None,
) -> list[BaseGeometry]:
    if not _has_case_level_rcsd_bridge_support(unit_results):
        return []
    components = [
        unit.unit_must_cover_domain
        for unit in unit_results
        if unit.unit_must_cover_domain is not None and not unit.unit_must_cover_domain.is_empty
    ]
    if len(components) <= 1:
        return []
    bridges: list[BaseGeometry] = []
    current_geometry = components[0]
    for candidate in components[1:]:
        bridge = _nearest_bridge_patch(
            current_geometry,
            candidate,
            support_graph_geometry=support_graph_geometry,
            drivezone_union=drivezone_union,
            half_width_m=STEP5_SUPPORT_ROAD_BUFFER_M,
            support_graph_pad_m=STEP5_FULL_ROAD_FILL_AXIS_HALF_WIDTH_M,
        )
        if bridge is not None and not bridge.is_empty:
            bridge = _clip_to_drivezone(bridge.buffer(0.25), drivezone_union) or bridge
            bridges.append(bridge)
        current_geometry = _clip_to_drivezone(
            _union_geometry([current_geometry, candidate, *bridges]),
            drivezone_union,
        ) or current_geometry
    return bridges
