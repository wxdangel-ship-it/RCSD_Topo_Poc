from __future__ import annotations

from collections import defaultdict, deque

from collections.abc import Iterable

from dataclasses import dataclass, field

from time import perf_counter

from typing import Any

from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

from shapely.geometry.base import BaseGeometry

from shapely.ops import nearest_points, substring, unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import NodeRecord, RoadRecord

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.finalization_models import (
    Step6OutputGeometries,
    Step6Result,
    FinalizationContext,
)

TARGET_NODE_BUFFER_M = 5.5

SUPPORT_ONLY_SEAM_BRIDGE_BUFFER_M = 9.0

SUPPORT_ONLY_TINY_FRAGMENT_MAX_AREA_M2 = 12.0

SUPPORT_ONLY_DOMINANT_COMPONENT_MIN_RATIO = 0.95

REQUIRED_NODE_BUFFER_M = 5.5

REQUIRED_ROAD_BUFFER_M = 6.0

SEMANTIC_INTRA_LINE_BUFFER_M = 5.5

FOREIGN_MASK_BUFFER_M = 1.0

LEGAL_SPACE_TOLERANCE_M = 0.6

NODE_COVER_TOLERANCE_M = 1.0

TARGET_NODE_INCIDENT_ROAD_COVER_TOLERANCE_M = 10.0

LINE_COVER_BUFFER_M = 2.0

LINE_COVER_MIN_RATIO = 0.68

SELECTED_ROAD_CORE_MIN_RATIO = 0.45

TARGET_NODE_CONNECTION_MIN_RATIO = 0.98

FOREIGN_OVERLAP_TOLERANCE_M2 = 0.05

FINAL_CLOSE_M = 1.6

DIRECTIONAL_CUT_DISTANCE_M = 20.0

DIRECTIONAL_WINDOW_MIN_HALF_WIDTH_M = 60.0

DIRECTIONAL_WINDOW_EXTENSION_FACTOR = 2.0

STEP3_TWO_NODE_T_BRIDGE_BUFFER_M = 8.0

CENTER_TWO_NODE_T_BRIDGE_MAX_LENGTH_M = 90.0

BRANCH_CLIP_HALF_WIDTH_M = 10.0

BRANCH_SPECIAL_CLIP_HALF_WIDTH_M = 6.0

BRANCH_CLIP_CENTER_RADIUS_M = 14.0

BRANCH_TRIM_HALF_WIDTH_M = 6.0

BRANCH_SPECIAL_TRIM_HALF_WIDTH_M = 4.0

SINGLE_SIDED_HORIZONTAL_EXTENSION_M = 5.0

SINGLE_SIDED_HORIZONTAL_ALIGNMENT_TOLERANCE_M = 8.0

SINGLE_SIDED_HORIZONTAL_MIN_REQUIRED_NODE_COUNT = 2

PRIMARY_INFEASIBLE = "infeasible_under_frozen_constraints"

PRIMARY_SOLVER_FAILED = "geometry_solver_failed"

SECONDARY_STEP1_STEP3_CONFLICT = "step1_step3_conflict"

SECONDARY_STAGE3_RC_GAP = "stage3_rc_gap"

SECONDARY_FOREIGN_CONFLICT = "foreign_exclusion_conflict"

SECONDARY_TEMPLATE_MISFIT = "template_misfit"

SECONDARY_CLOSURE_FAILURE = "geometry_closure_failure"

SECONDARY_CLEANUP_OVERTRIM = "cleanup_overtrim"

SECONDARY_CLEANUP_UNDERTRIM = "cleanup_undertrim"

SECONDARY_FOREIGN_REINTRODUCED = "foreign_reintroduced_by_cleanup"

SECONDARY_SHAPE_ARTIFACT = "shape_artifact_failure"

from .step6_geometry_models import (
    _DirectionalBranchWindow,
    _SingleSidedHorizontalTraceDecision,
    _Step6GeometryCache,
)

def _sorted_ids(values: Iterable[str]) -> list[str]:
    return sorted(set(values), key=lambda item: (0, int(item)) if item.isdigit() else (1, item))

def _accumulate_stage_timer(
    stage_timers: dict[str, float] | None,
    key: str,
    elapsed_seconds: float,
) -> None:
    if stage_timers is None:
        return
    stage_timers[key] = round(float(stage_timers.get(key, 0.0)) + max(float(elapsed_seconds), 0.0), 6)

def _geometry_cache_token(geometry: BaseGeometry | None) -> bytes | None:
    if geometry is None or geometry.is_empty:
        return None
    return geometry.wkb

def _clean_geometry(geometry: BaseGeometry | None) -> BaseGeometry | None:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, GeometryCollection):
        cleaned = [_clean_geometry(part) for part in geometry.geoms]
        cleaned = [part for part in cleaned if part is not None and not part.is_empty]
        if not cleaned:
            return None
        geometry = unary_union(cleaned)
    elif isinstance(geometry, (MultiPolygon, MultiLineString, MultiPoint)):
        parts = [part for part in geometry.geoms if part is not None and not part.is_empty]
        if not parts:
            return None
        geometry = unary_union(parts)
    if geometry.geom_type in {"Polygon", "MultiPolygon"}:
        geometry = geometry.buffer(0)
    return None if geometry.is_empty else geometry

def _iter_geometries(geometry: BaseGeometry | None) -> Iterable[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, (GeometryCollection, MultiPolygon, MultiLineString, MultiPoint)):
        for item in geometry.geoms:
            yield from _iter_geometries(item)
        return
    yield geometry

def _iter_polygons(geometry: BaseGeometry | None) -> Iterable[Polygon]:
    for item in _iter_geometries(geometry):
        if isinstance(item, Polygon):
            yield item

def _iter_lines(geometry: BaseGeometry | None) -> Iterable[LineString]:
    for item in _iter_geometries(geometry):
        if isinstance(item, LineString) and item.length > 0.0:
            yield item

def _union_geometries(geometries: Iterable[BaseGeometry | None]) -> BaseGeometry | None:
    parts = [part for geometry in geometries for part in _iter_geometries(geometry)]
    if not parts:
        return None
    return _clean_geometry(unary_union(parts))

def _point_buffers(nodes: Iterable[NodeRecord], distance: float) -> BaseGeometry | None:
    return _union_geometries(node.geometry.buffer(distance) for node in nodes)

def _line_buffers(geometry: BaseGeometry | None, distance: float) -> BaseGeometry | None:
    return _union_geometries(
        line.buffer(distance, cap_style=2, join_style=2)
        for line in _iter_lines(geometry)
    )

def _cached_line_buffers(
    geometry: BaseGeometry | None,
    distance: float,
    *,
    geometry_cache: _Step6GeometryCache | None,
) -> BaseGeometry | None:
    if geometry_cache is None:
        return _line_buffers(geometry, distance)
    cache_key = (_geometry_cache_token(geometry), round(float(distance), 6))
    if cache_key not in geometry_cache.line_buffer_cache:
        geometry_cache.line_buffer_cache[cache_key] = _line_buffers(geometry, distance)
    return geometry_cache.line_buffer_cache[cache_key]


def _cached_boundary_buffer(
    boundary_geometry: BaseGeometry | None,
    distance: float,
    *,
    geometry_cache: _Step6GeometryCache | None,
) -> BaseGeometry | None:
    boundary = _clean_geometry(boundary_geometry)
    if boundary is None:
        return None
    if geometry_cache is None:
        return _clean_geometry(boundary.buffer(distance))
    cache_key = (_geometry_cache_token(boundary), round(float(distance), 6))
    if cache_key not in geometry_cache.boundary_buffer_cache:
        geometry_cache.boundary_buffer_cache[cache_key] = _clean_geometry(boundary.buffer(distance))
    return geometry_cache.boundary_buffer_cache[cache_key]

def _road_union(roads: Iterable[RoadRecord]) -> BaseGeometry | None:
    return _union_geometries(road.geometry for road in roads)

def _build_foreign_mask_geometry(
    finalization_context: FinalizationContext,
    *,
    geometry_cache: _Step6GeometryCache | None = None,
) -> tuple[BaseGeometry | None, list[str]]:
    association_outputs = finalization_context.association_case_result.output_geometries
    sources: list[str] = []
    geometries: list[BaseGeometry | None] = []
    if association_outputs.excluded_rcsdroad_geometry is not None:
        geometries.append(
            _cached_line_buffers(
                association_outputs.excluded_rcsdroad_geometry,
                FOREIGN_MASK_BUFFER_M,
                geometry_cache=geometry_cache,
            )
        )
        sources.append("excluded_rcsdroad_geometry")
    return _union_geometries(geometries), sources

def _component_count(geometry: BaseGeometry | None) -> int:
    polygons = list(_iter_polygons(geometry))
    return len(polygons)

def _hole_count(geometry: BaseGeometry | None) -> int:
    return sum(len(polygon.interiors) for polygon in _iter_polygons(geometry))

def _shape_metrics(geometry: BaseGeometry | None) -> dict[str, Any]:
    cleaned = _clean_geometry(geometry)
    if cleaned is None:
        return {
            "area_m2": 0.0,
            "perimeter_m": 0.0,
            "bbox_width_m": 0.0,
            "bbox_height_m": 0.0,
            "aspect_ratio": None,
            "compactness": None,
            "bbox_fill_ratio": None,
            "component_count": 0,
            "hole_count": 0,
        }
    minx, miny, maxx, maxy = cleaned.bounds
    width = maxx - minx
    height = maxy - miny
    area = cleaned.area
    perimeter = cleaned.length
    aspect_ratio = None
    if width > 0.0 and height > 0.0:
        aspect_ratio = max(width, height) / min(width, height)
    compactness = None
    if perimeter > 0.0:
        compactness = 4.0 * 3.141592653589793 * area / (perimeter * perimeter)
    bbox_fill_ratio = None
    if width > 0.0 and height > 0.0:
        bbox_fill_ratio = area / (width * height)
    return {
        "area_m2": round(area, 6),
        "perimeter_m": round(perimeter, 6),
        "bbox_width_m": round(width, 6),
        "bbox_height_m": round(height, 6),
        "aspect_ratio": round(aspect_ratio, 6) if aspect_ratio is not None else None,
        "compactness": round(compactness, 6) if compactness is not None else None,
        "bbox_fill_ratio": round(bbox_fill_ratio, 6) if bbox_fill_ratio is not None else None,
        "component_count": _component_count(cleaned),
        "hole_count": _hole_count(cleaned),
    }

def _as_linestring(geometry: BaseGeometry | None) -> LineString | None:
    if geometry is None or geometry.is_empty:
        return None
    if isinstance(geometry, LineString):
        return geometry if geometry.length > 0.0 else None
    lines = sorted(_iter_lines(geometry), key=lambda item: item.length, reverse=True)
    return lines[0] if lines else None

def _reverse_line(line: LineString | None) -> LineString | None:
    if line is None:
        return None
    coords = list(line.coords)
    if len(coords) < 2:
        return None
    return LineString(list(reversed(coords)))

def _substring_line(line: LineString | None, start_distance: float, end_distance: float) -> LineString | None:
    if line is None or line.length <= 0.0:
        return None
    actual_start = max(0.0, min(line.length, start_distance))
    actual_end = max(0.0, min(line.length, end_distance))
    if actual_end - actual_start <= 1e-6:
        return None
    return _as_linestring(substring(line, actual_start, actual_end))

def _directional_window_half_width(allowed_space: BaseGeometry | None) -> float:
    cleaned = _clean_geometry(allowed_space)
    if cleaned is None:
        return DIRECTIONAL_WINDOW_MIN_HALF_WIDTH_M
    minx, miny, maxx, maxy = cleaned.bounds
    return max(DIRECTIONAL_WINDOW_MIN_HALF_WIDTH_M, max(maxx - minx, maxy - miny))

def _point_on_line(line: LineString | None, distance: float) -> Point | None:
    if line is None or line.length <= 0.0:
        return None
    return Point(line.interpolate(max(0.0, min(line.length, distance))))

def _unit_direction_at_distance(line: LineString | None, distance: float) -> tuple[float, float] | None:
    if line is None or line.length <= 1e-6:
        return None
    end_distance = max(0.0, min(line.length, distance))
    start_distance = max(0.0, end_distance - min(1.0, end_distance if end_distance > 0.0 else line.length))
    if end_distance - start_distance <= 1e-6:
        end_distance = min(line.length, max(1.0, distance))
        start_distance = max(0.0, end_distance - 1.0)
    start_point = _point_on_line(line, start_distance)
    end_point = _point_on_line(line, end_distance)
    if start_point is None or end_point is None:
        return None
    dx = end_point.x - start_point.x
    dy = end_point.y - start_point.y
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 1e-6:
        return None
    return dx / length, dy / length

def _half_plane_keep_polygon(
    line: LineString | None,
    keep_length: float,
    clip_extent: float,
) -> BaseGeometry | None:
    if line is None or keep_length <= 0.0:
        return None
    cut_point = _point_on_line(line, keep_length)
    direction = _unit_direction_at_distance(line, keep_length)
    if cut_point is None or direction is None:
        return None
    ux, uy = direction
    vx, vy = -uy, ux
    front_left = (cut_point.x + vx * clip_extent, cut_point.y + vy * clip_extent)
    front_right = (cut_point.x - vx * clip_extent, cut_point.y - vy * clip_extent)
    back_right = (
        cut_point.x - vx * clip_extent - ux * clip_extent,
        cut_point.y - vy * clip_extent - uy * clip_extent,
    )
    back_left = (
        cut_point.x + vx * clip_extent - ux * clip_extent,
        cut_point.y + vy * clip_extent - uy * clip_extent,
    )
    return _clean_geometry(Polygon([front_left, front_right, back_right, back_left]))

def _branch_local_sector_geometry(
    line: LineString | None,
    half_width_m: float,
    allowed_space: BaseGeometry | None,
) -> BaseGeometry | None:
    if line is None or line.length <= 1e-6 or allowed_space is None:
        return None
    branch_start = Point(line.coords[0])
    return _clean_geometry(
        _union_geometries(
            [
                line.buffer(
                    half_width_m,
                    cap_style=2,
                    join_style=2,
                ),
                branch_start.buffer(BRANCH_CLIP_CENTER_RADIUS_M, join_style=1),
            ]
        ).intersection(allowed_space)
    )

def _branch_local_overrun_mask(
    line: LineString | None,
    branch_length: float,
    keep_length: float,
    half_width_m: float,
    allowed_space: BaseGeometry | None,
) -> BaseGeometry | None:
    if line is None or branch_length <= 0.0 or keep_length >= branch_length - 1e-6:
        return None
    overrun_segment = _substring_line(line, keep_length, branch_length)
    if overrun_segment is None or allowed_space is None:
        return None
    return _clean_geometry(
        overrun_segment.buffer(
            half_width_m,
            cap_style=2,
            join_style=2,
        ).intersection(allowed_space)
    )

def _target_anchor_geometry(
    finalization_context: FinalizationContext,
    *,
    geometry_cache: _Step6GeometryCache | None = None,
) -> BaseGeometry | None:
    if geometry_cache is not None and geometry_cache.target_anchor_geometry_ready:
        return geometry_cache.target_anchor_geometry
    geometry = _union_geometries(
        node.geometry for node in finalization_context.association_context.step1_context.target_group.nodes
    )
    if geometry_cache is not None:
        geometry_cache.target_anchor_geometry = geometry
        geometry_cache.target_anchor_geometry_ready = True
    return geometry

def _step3_two_node_t_bridge_geometry(
    finalization_context: FinalizationContext,
    allowed_space: BaseGeometry | None,
) -> BaseGeometry | None:
    association_context = finalization_context.association_context
    association_case_result = finalization_context.association_case_result
    support_only_center_bridge_candidate = (
        association_case_result.association_class == "B"
        and association_case_result.template_class == "center_junction"
        and association_case_result.reason == "association_support_only"
        and len(association_case_result.extra_status_fields.get("support_rcsdroad_ids") or []) >= 4
    )
    if (
        association_case_result.association_class != "A"
        and association_case_result.template_class != "single_sided_t_mouth"
        and not support_only_center_bridge_candidate
    ):
        return None
    if not bool(association_context.step3_status_doc.get("two_node_t_bridge_applied")):
        return None
    target_nodes = tuple(
        sorted(
            association_context.step1_context.target_group.nodes,
            key=lambda item: item.node_id,
        )
    )
    if len(target_nodes) != 2 or allowed_space is None:
        return None
    start_point = target_nodes[0].geometry
    end_point = target_nodes[1].geometry
    raw_line = LineString([start_point, end_point])
    support_only_long_center_bridge = (
        support_only_center_bridge_candidate
        and raw_line.length > CENTER_TWO_NODE_T_BRIDGE_MAX_LENGTH_M
    )
    if support_only_center_bridge_candidate and not support_only_long_center_bridge:
        return None
    if (
        association_case_result.template_class != "single_sided_t_mouth"
        and not support_only_long_center_bridge
        and raw_line.length > CENTER_TWO_NODE_T_BRIDGE_MAX_LENGTH_M
    ):
        return None
    return _clean_geometry(
        raw_line.buffer(
            STEP3_TWO_NODE_T_BRIDGE_BUFFER_M,
            cap_style=2,
            join_style=2,
        ).intersection(allowed_space)
    )

def _target_node_connection_line_geometry(finalization_context: FinalizationContext) -> BaseGeometry | None:
    target_nodes = tuple(
        sorted(
            finalization_context.association_context.step1_context.target_group.nodes,
            key=lambda item: item.node_id,
        )
    )
    if len(target_nodes) < 2:
        return None
    points = [node.geometry for node in target_nodes if isinstance(node.geometry, Point)]
    if len(points) < 2:
        return None
    if len(points) == 2:
        line = LineString(points)
        return line if line.length > 1e-6 else None

    visited = {0}
    remaining = set(range(1, len(points)))
    edges: list[LineString] = []
    while remaining:
        best_pair: tuple[int, int] | None = None
        best_distance = float("inf")
        for left_index in visited:
            for right_index in remaining:
                distance = points[left_index].distance(points[right_index])
                if distance < best_distance:
                    best_distance = distance
                    best_pair = (left_index, right_index)
        if best_pair is None:
            break
        left_index, right_index = best_pair
        line = LineString([points[left_index], points[right_index]])
        if line.length > 1e-6:
            edges.append(line)
        visited.add(right_index)
        remaining.remove(right_index)
    return _union_geometries(edges)

def _support_only_seam_bridge_geometry(
    finalization_context: FinalizationContext,
    allowed_space_tolerance_geometry: BaseGeometry | None,
    *,
    geometry_cache: _Step6GeometryCache | None = None,
) -> BaseGeometry | None:
    if finalization_context.association_case_result.association_class != "B":
        return None
    bridge_geometry = _point_buffers(
        finalization_context.association_context.step1_context.target_group.nodes,
        SUPPORT_ONLY_SEAM_BRIDGE_BUFFER_M,
    )
    if bridge_geometry is not None and allowed_space_tolerance_geometry is not None:
        bridge_geometry = _clean_geometry(bridge_geometry.intersection(allowed_space_tolerance_geometry))
    return bridge_geometry

def _road_directional_branches(
    road: RoadRecord,
    anchor_geometry: BaseGeometry | None,
) -> list[tuple[int, LineString, float]]:
    line = _as_linestring(_clean_geometry(road.geometry))
    if line is None:
        return []
    if anchor_geometry is None:
        return [(1, line, 0.0)]
    anchor_point = nearest_points(anchor_geometry, line)[1]
    anchor_distance = float(anchor_geometry.distance(line))
    projection_distance = line.project(anchor_point)
    branches: list[tuple[int, LineString, float]] = []
    left_branch = _reverse_line(_substring_line(line, 0.0, projection_distance))
    if left_branch is not None and left_branch.length > 1e-6:
        branches.append((1, left_branch, anchor_distance))
    right_branch = _substring_line(line, projection_distance, line.length)
    if right_branch is not None and right_branch.length > 1e-6:
        branches.append((2 if branches else 1, right_branch, anchor_distance))
    return branches

def _contiguous_allowed_prefix(
    branch_geometry: LineString | None,
    allowed_space: BaseGeometry | None,
    *,
    allowed_space_tolerance_geometry: BaseGeometry | None = None,
) -> LineString | None:
    if branch_geometry is None or allowed_space is None:
        return None
    tolerance_geometry = (
        allowed_space_tolerance_geometry
        if allowed_space_tolerance_geometry is not None
        else _clean_geometry(allowed_space.buffer(LEGAL_SPACE_TOLERANCE_M))
    )
    clipped = _clean_geometry(branch_geometry.intersection(tolerance_geometry))
    if clipped is None:
        return None
    branch_start = Point(branch_geometry.coords[0])
    candidates = [
        line for line in _iter_lines(clipped) if line.distance(branch_start) <= NODE_COVER_TOLERANCE_M
    ]
    if not candidates:
        return None
    chosen = max(candidates, key=lambda line: line.length)
    start_distance = Point(chosen.coords[0]).distance(branch_start)
    end_distance = Point(chosen.coords[-1]).distance(branch_start)
    if end_distance < start_distance:
        chosen = _reverse_line(chosen)
    return chosen

def _retain_components_touching_keep_geometry(
    geometry: BaseGeometry | None,
    keep_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    cleaned = _clean_geometry(geometry)
    if cleaned is None:
        return None
    if keep_geometry is None:
        return cleaned
    kept = [
        polygon
        for polygon in _iter_polygons(cleaned)
        if polygon.intersects(keep_geometry)
    ]
    if not kept:
        return None
    return _clean_geometry(unary_union(kept))

def _prune_support_only_tiny_fragments(
    finalization_context: FinalizationContext,
    geometry: BaseGeometry | None,
    *,
    geometry_cache: _Step6GeometryCache | None = None,
) -> tuple[BaseGeometry | None, bool]:
    cleaned = _clean_geometry(geometry)
    if cleaned is None:
        return None, False
    case_result = finalization_context.association_case_result
    if (
        case_result.template_class != "single_sided_t_mouth"
        or case_result.reason != "association_support_only"
    ):
        return cleaned, False
    polygons = sorted(_iter_polygons(cleaned), key=lambda item: item.area, reverse=True)
    if len(polygons) < 3:
        return cleaned, False
    total_area = sum(polygon.area for polygon in polygons)
    if total_area <= 0.0:
        return cleaned, False
    dominant = polygons[0]
    fragment_area = total_area - dominant.area
    anchor = _target_anchor_geometry(finalization_context, geometry_cache=geometry_cache)
    if (
        dominant.area / total_area >= SUPPORT_ONLY_DOMINANT_COMPONENT_MIN_RATIO
        and fragment_area <= SUPPORT_ONLY_TINY_FRAGMENT_MAX_AREA_M2
        and anchor is not None
        and dominant.intersects(anchor.buffer(SUPPORT_ONLY_SEAM_BRIDGE_BUFFER_M))
    ):
        return _clean_geometry(dominant), True
    return cleaned, False

def _line_coverage_ratio(line_geometry: BaseGeometry | None, polygon_geometry: BaseGeometry | None) -> float:
    cover_geometry = _cached_boundary_buffer(
        polygon_geometry,
        LINE_COVER_BUFFER_M,
        geometry_cache=None,
    )
    return _line_coverage_ratio_with_cover_geometry(line_geometry, cover_geometry)

def _line_coverage_ratio_with_cover_geometry(
    line_geometry: BaseGeometry | None,
    cover_geometry: BaseGeometry | None,
) -> float:
    line = _clean_geometry(line_geometry)
    polygon_cover = _clean_geometry(cover_geometry)
    if line is None:
        return 1.0
    if polygon_cover is None:
        return 0.0
    total_length = sum(item.length for item in _iter_lines(line))
    if total_length <= 0.0:
        return 1.0
    covered_length = sum(
        item.intersection(polygon_cover).length
        for item in _iter_lines(line)
    )
    return max(0.0, min(1.0, covered_length / total_length))

def _node_cover_ratio(nodes: Iterable[NodeRecord], polygon_geometry: BaseGeometry | None) -> float:
    polygon_cover = _cached_boundary_buffer(
        polygon_geometry,
        NODE_COVER_TOLERANCE_M,
        geometry_cache=None,
    )
    return _node_cover_ratio_with_cover_geometry(nodes, polygon_cover)

def _node_cover_ratio_with_cover_geometry(
    nodes: Iterable[NodeRecord],
    polygon_cover: BaseGeometry | None,
) -> float:
    items = list(nodes)
    if not items:
        return 1.0
    if polygon_cover is None:
        return 0.0
    covered = 0
    for node in items:
        if polygon_cover.contains(node.geometry):
            covered += 1
    return covered / len(items)

def _target_node_has_incident_polygon_support(
    finalization_context: FinalizationContext,
    node: NodeRecord,
    polygon_cover: BaseGeometry,
) -> bool:
    if node.geometry.distance(polygon_cover) > TARGET_NODE_INCIDENT_ROAD_COVER_TOLERANCE_M:
        return False
    selected_road_ids = set(finalization_context.association_context.selected_road_ids)
    for road in finalization_context.association_context.step1_context.roads:
        if road.road_id not in selected_road_ids:
            continue
        if node.node_id not in {road.snodeid, road.enodeid}:
            continue
        return True
    return False

def _target_node_cover_ratio_with_cover_geometry(
    finalization_context: FinalizationContext,
    polygon_cover: BaseGeometry | None,
) -> float:
    items = list(finalization_context.association_context.step1_context.target_group.nodes)
    if not items:
        return 1.0
    if polygon_cover is None:
        return 0.0
    covered = 0
    for node in items:
        if polygon_cover.contains(node.geometry) or _target_node_has_incident_polygon_support(
            finalization_context,
            node,
            polygon_cover,
        ):
            covered += 1
    return covered / len(items)

def _road_core_cover_ratio(core_geometry: BaseGeometry | None, polygon_geometry: BaseGeometry | None) -> float:
    if core_geometry is None:
        return 1.0
    return _line_coverage_ratio(core_geometry, polygon_geometry)

def _cached_shape_metrics(
    geometry: BaseGeometry | None,
    *,
    geometry_cache: _Step6GeometryCache | None,
) -> dict[str, Any]:
    if geometry_cache is None:
        return _shape_metrics(geometry)
    cache_key = _geometry_cache_token(geometry)
    if cache_key not in geometry_cache.shape_metrics_cache:
        geometry_cache.shape_metrics_cache[cache_key] = _shape_metrics(geometry)
    return geometry_cache.shape_metrics_cache[cache_key]

def _required_node_records(finalization_context: FinalizationContext) -> list[NodeRecord]:
    step1 = finalization_context.association_context.step1_context
    required_ids = set(finalization_context.association_case_result.extra_status_fields.get("required_rcsdnode_ids") or [])
    return [node for node in step1.rcsd_nodes if node.node_id in required_ids]

def _semantic_group_id(node: NodeRecord) -> str:
    mainnodeid = None if node.mainnodeid in {None, "", "0"} else str(node.mainnodeid)
    return mainnodeid or node.node_id
