from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
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

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.models import NodeRecord, RoadRecord
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.step67_models import (
    Step6OutputGeometries,
    Step6Result,
    Step67Context,
)


TARGET_NODE_BUFFER_M = 5.5
REQUIRED_NODE_BUFFER_M = 5.5
REQUIRED_ROAD_BUFFER_M = 6.0
FOREIGN_MASK_BUFFER_M = 1.0
LEGAL_SPACE_TOLERANCE_M = 0.6
NODE_COVER_TOLERANCE_M = 1.0
LINE_COVER_BUFFER_M = 2.0
LINE_COVER_MIN_RATIO = 0.68
SELECTED_ROAD_CORE_MIN_RATIO = 0.45
FOREIGN_OVERLAP_TOLERANCE_M2 = 0.05
FINAL_CLOSE_M = 1.6
DIRECTIONAL_CUT_DISTANCE_M = 20.0
DIRECTIONAL_WINDOW_MIN_HALF_WIDTH_M = 60.0
DIRECTIONAL_WINDOW_EXTENSION_FACTOR = 2.0
STEP3_TWO_NODE_T_BRIDGE_BUFFER_M = 8.0
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


@dataclass(frozen=True)
class _DirectionalBranchWindow:
    road_id: str
    branch_index: int
    anchor_distance_m: float
    available_length_m: float
    cut_length_m: float
    preserve_candidate_boundary: bool
    special_rule_applied: bool
    semantic_extent_m: float | None
    core_geometry: BaseGeometry | None
    clip_geometry: BaseGeometry | None


@dataclass(frozen=True)
class _SingleSidedHorizontalTraceDecision:
    road_id: str
    branch_index: int
    trace_status: str
    vertical_seed_rcsdroad_ids: tuple[str, ...]
    traced_rcsdroad_ids: tuple[str, ...]
    traced_rcsdnode_ids: tuple[str, ...]
    semantic_extent_m: float | None
    requested_cut_length_m: float | None
    apply_special_rule: bool


def _sorted_ids(values: Iterable[str]) -> list[str]:
    return sorted(set(values), key=lambda item: (0, int(item)) if item.isdigit() else (1, item))


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


def _road_union(roads: Iterable[RoadRecord]) -> BaseGeometry | None:
    return _union_geometries(road.geometry for road in roads)


def _build_foreign_mask_geometry(step67_context: Step67Context) -> tuple[BaseGeometry | None, list[str]]:
    step45_outputs = step67_context.step45_case_result.output_geometries
    sources: list[str] = []
    geometries: list[BaseGeometry | None] = []
    if step45_outputs.excluded_rcsdroad_geometry is not None:
        geometries.append(_line_buffers(step45_outputs.excluded_rcsdroad_geometry, FOREIGN_MASK_BUFFER_M))
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


def _target_anchor_geometry(step67_context: Step67Context) -> BaseGeometry | None:
    return _union_geometries(
        node.geometry for node in step67_context.step45_context.step1_context.target_group.nodes
    )


def _step3_two_node_t_bridge_geometry(
    step67_context: Step67Context,
    allowed_space: BaseGeometry | None,
) -> BaseGeometry | None:
    step45_context = step67_context.step45_context
    if step45_context.template_result.template_class != "single_sided_t_mouth":
        return None
    if not bool(step45_context.step3_status_doc.get("two_node_t_bridge_applied")):
        return None
    target_nodes = tuple(
        sorted(
            step45_context.step1_context.target_group.nodes,
            key=lambda item: item.node_id,
        )
    )
    if len(target_nodes) != 2 or allowed_space is None:
        return None
    start_point = target_nodes[0].geometry
    end_point = target_nodes[1].geometry
    raw_line = LineString([start_point, end_point])
    return _clean_geometry(
        raw_line.buffer(
            STEP3_TWO_NODE_T_BRIDGE_BUFFER_M,
            cap_style=2,
            join_style=2,
        ).intersection(allowed_space)
    )


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
) -> LineString | None:
    if branch_geometry is None or allowed_space is None:
        return None
    clipped = _clean_geometry(branch_geometry.intersection(allowed_space.buffer(LEGAL_SPACE_TOLERANCE_M)))
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


def _retain_components_touching_anchors(
    geometry: BaseGeometry | None,
    anchor_geometries: Iterable[BaseGeometry | None],
) -> BaseGeometry | None:
    cleaned = _clean_geometry(geometry)
    if cleaned is None:
        return None
    anchors = _union_geometries(anchor_geometries)
    if anchors is None:
        return cleaned
    kept = [
        polygon
        for polygon in _iter_polygons(cleaned)
        if polygon.intersects(anchors.buffer(NODE_COVER_TOLERANCE_M))
    ]
    if not kept:
        return None
    return _clean_geometry(unary_union(kept))


def _line_coverage_ratio(line_geometry: BaseGeometry | None, polygon_geometry: BaseGeometry | None) -> float:
    line = _clean_geometry(line_geometry)
    polygon = _clean_geometry(polygon_geometry)
    if line is None:
        return 1.0
    if polygon is None:
        return 0.0
    total_length = sum(item.length for item in _iter_lines(line))
    if total_length <= 0.0:
        return 1.0
    covered_length = sum(
        item.intersection(polygon.buffer(LINE_COVER_BUFFER_M)).length
        for item in _iter_lines(line)
    )
    return max(0.0, min(1.0, covered_length / total_length))


def _node_cover_ratio(nodes: Iterable[NodeRecord], polygon_geometry: BaseGeometry | None) -> float:
    polygon = _clean_geometry(polygon_geometry)
    items = list(nodes)
    if not items:
        return 1.0
    if polygon is None:
        return 0.0
    covered = 0
    for node in items:
        if polygon.buffer(NODE_COVER_TOLERANCE_M).contains(node.geometry):
            covered += 1
    return covered / len(items)


def _road_core_cover_ratio(core_geometry: BaseGeometry | None, polygon_geometry: BaseGeometry | None) -> float:
    if core_geometry is None:
        return 1.0
    return _line_coverage_ratio(core_geometry, polygon_geometry)


def _required_node_records(step67_context: Step67Context) -> list[NodeRecord]:
    step1 = step67_context.step45_context.step1_context
    required_ids = set(step67_context.step45_case_result.extra_status_fields.get("required_rcsdnode_ids") or [])
    return [node for node in step1.rcsd_nodes if node.node_id in required_ids]


def _selected_road_records(step67_context: Step67Context) -> list[RoadRecord]:
    selected_ids = set(step67_context.step45_context.selected_road_ids)
    return [road for road in step67_context.step45_context.step1_context.roads if road.road_id in selected_ids]


def _single_sided_horizontal_pair_ids(step67_context: Step67Context) -> set[str]:
    step45_context = step67_context.step45_context
    if step45_context.template_result.template_class != "single_sided_t_mouth":
        return set()
    return {
        str(item)
        for item in (step45_context.step3_status_doc.get("single_sided_horizontal_pair_road_ids") or [])
        if item is not None and str(item) != ""
    }


def _required_road_records(step67_context: Step67Context) -> list[RoadRecord]:
    step1 = step67_context.step45_context.step1_context
    required_ids = set(step67_context.step45_case_result.extra_status_fields.get("required_rcsdroad_ids") or [])
    return [road for road in step1.rcsd_roads if road.road_id in required_ids]


def _single_sided_vertical_exit_geometry(step67_context: Step67Context) -> BaseGeometry | None:
    step45_context = step67_context.step45_context
    if step45_context.template_result.template_class != "single_sided_t_mouth":
        return None
    horizontal_pair_ids = _single_sided_horizontal_pair_ids(step67_context)
    exit_geometries = [
        road.geometry
        for road in step45_context.step1_context.roads
        if road.road_id in set(step45_context.selected_road_ids) and road.road_id not in horizontal_pair_ids
    ]
    return _union_geometries(exit_geometries)


def _local_required_node_records(
    step67_context: Step67Context,
    boundary_geometry: BaseGeometry | None,
) -> list[NodeRecord]:
    boundary = _clean_geometry(boundary_geometry)
    if boundary is None:
        return []
    boundary_buffer = boundary.buffer(NODE_COVER_TOLERANCE_M)
    return [
        node
        for node in _required_node_records(step67_context)
        if boundary_buffer.intersects(node.geometry)
    ]


def _local_required_road_records(
    step67_context: Step67Context,
    boundary_geometry: BaseGeometry | None,
) -> list[RoadRecord]:
    boundary = _clean_geometry(boundary_geometry)
    if boundary is None:
        return []
    boundary_buffer = boundary.buffer(LINE_COVER_BUFFER_M)
    return [
        road
        for road in _required_road_records(step67_context)
        if boundary_buffer.intersects(road.geometry)
    ]


def _local_required_road_geometry(
    step67_context: Step67Context,
    boundary_geometry: BaseGeometry | None,
) -> BaseGeometry | None:
    boundary = _clean_geometry(boundary_geometry)
    if boundary is None:
        return None
    required_geometry = _clean_geometry(
        step67_context.step45_case_result.output_geometries.required_rcsdroad_geometry
    )
    if required_geometry is None:
        return None
    return _clean_geometry(required_geometry.intersection(boundary.buffer(LINE_COVER_BUFFER_M)))


def _single_sided_trace_candidate_rcsdroad_records(
    step67_context: Step67Context,
) -> list[RoadRecord]:
    step45_context = step67_context.step45_context
    current_swsd_surface = _clean_geometry(step45_context.current_swsd_surface_geometry)
    allowed_space = _clean_geometry(step45_context.step3_allowed_space_geometry)
    if current_swsd_surface is None or allowed_space is None:
        return []
    u_turn_ids = set(step67_context.step45_case_result.extra_status_fields.get("u_turn_rcsdroad_ids") or [])
    return [
        road
        for road in step45_context.step1_context.rcsd_roads
        if road.road_id not in u_turn_ids
        and road.geometry.intersects(current_swsd_surface.buffer(FOREIGN_MASK_BUFFER_M))
        and road.geometry.intersects(allowed_space.buffer(FOREIGN_MASK_BUFFER_M))
    ]


def _single_sided_trace_reachable_endpoint_nodes(
    step67_context: Step67Context,
    candidate_roads: list[RoadRecord],
) -> tuple[tuple[str, ...], tuple[str, ...], list[NodeRecord]]:
    vertical_exit_geometry = _single_sided_vertical_exit_geometry(step67_context)
    if vertical_exit_geometry is None or vertical_exit_geometry.is_empty:
        return (), (), []

    roads_by_id = {road.road_id: road for road in candidate_roads}
    vertical_seed_ids = tuple(
        _sorted_ids(
            road.road_id
            for road in candidate_roads
            if road.geometry.intersects(vertical_exit_geometry.buffer(SINGLE_SIDED_HORIZONTAL_ALIGNMENT_TOLERANCE_M))
        )
    )
    if not vertical_seed_ids:
        return (), (), []

    node_to_roads: dict[str, set[str]] = defaultdict(set)
    for road in candidate_roads:
        if road.snodeid not in {None, ""}:
            node_to_roads[str(road.snodeid)].add(road.road_id)
        if road.enodeid not in {None, ""}:
            node_to_roads[str(road.enodeid)].add(road.road_id)

    road_adjacency: dict[str, set[str]] = defaultdict(set)
    for road_ids in node_to_roads.values():
        for road_id in road_ids:
            road_adjacency[road_id].update(road_ids - {road_id})

    reachable_ids: set[str] = set(vertical_seed_ids)
    queue: deque[str] = deque(vertical_seed_ids)
    while queue:
        road_id = queue.popleft()
        for other_id in road_adjacency.get(road_id, set()):
            if other_id in reachable_ids:
                continue
            reachable_ids.add(other_id)
            queue.append(other_id)

    endpoint_node_ids = {
        node_id
        for road_id in reachable_ids
        for node_id in [roads_by_id[road_id].snodeid, roads_by_id[road_id].enodeid]
        if node_id not in {None, ""}
    }
    endpoint_nodes = [
        node
        for node in step67_context.step45_context.step1_context.rcsd_nodes
        if node.node_id in endpoint_node_ids
    ]
    return vertical_seed_ids, tuple(_sorted_ids(reachable_ids)), endpoint_nodes


def _single_sided_horizontal_trace_decisions(
    step67_context: Step67Context,
    allowed_space: BaseGeometry | None,
) -> dict[tuple[str, int], _SingleSidedHorizontalTraceDecision]:
    step45_case_result = step67_context.step45_case_result
    if step45_case_result.template_class != "single_sided_t_mouth":
        return {}
    if step45_case_result.association_class != "A":
        return {}
    if allowed_space is None:
        return {}

    horizontal_pair_ids = _single_sided_horizontal_pair_ids(step67_context)
    if len(horizontal_pair_ids) < 2:
        return {}

    candidate_roads = _single_sided_trace_candidate_rcsdroad_records(step67_context)
    vertical_seed_ids, traced_road_ids, endpoint_nodes = _single_sided_trace_reachable_endpoint_nodes(
        step67_context,
        candidate_roads,
    )
    if not vertical_seed_ids or not traced_road_ids or not endpoint_nodes:
        return {}

    selected_roads = _selected_road_records(step67_context)
    anchor_geometry = _target_anchor_geometry(step67_context)
    branch_hits: dict[tuple[str, int], list[tuple[NodeRecord, float]]] = {}
    for road in selected_roads:
        if road.road_id not in horizontal_pair_ids:
            continue
        for branch_index, branch_geometry, _anchor_distance in _road_directional_branches(road, anchor_geometry):
            allowed_prefix = _contiguous_allowed_prefix(branch_geometry, allowed_space)
            if allowed_prefix is None or allowed_prefix.length <= 1e-6:
                continue
            hits: list[tuple[NodeRecord, float]] = []
            for node in endpoint_nodes:
                if allowed_prefix.distance(node.geometry) > SINGLE_SIDED_HORIZONTAL_ALIGNMENT_TOLERANCE_M:
                    continue
                nearest_point = nearest_points(node.geometry, allowed_prefix)[1]
                projection_distance = allowed_prefix.project(nearest_point)
                if projection_distance <= NODE_COVER_TOLERANCE_M:
                    continue
                hits.append((node, projection_distance))
            branch_hits[(road.road_id, branch_index)] = hits

    hit_road_ids = {
        road_id
        for (road_id, _branch_index), hits in branch_hits.items()
        if hits
    }
    pair_complete = len(hit_road_ids) >= 2
    decision_map: dict[tuple[str, int], _SingleSidedHorizontalTraceDecision] = {}
    for (road_id, branch_index), hits in branch_hits.items():
        if not pair_complete or not hits:
            decision_map[(road_id, branch_index)] = _SingleSidedHorizontalTraceDecision(
                road_id=road_id,
                branch_index=branch_index,
                trace_status="trace_pair_incomplete" if not pair_complete else "no_trace",
                vertical_seed_rcsdroad_ids=vertical_seed_ids,
                traced_rcsdroad_ids=traced_road_ids,
                traced_rcsdnode_ids=(),
                semantic_extent_m=None,
                requested_cut_length_m=None,
                apply_special_rule=False,
            )
            continue
        semantic_extent = max(projection_distance for _node, projection_distance in hits)
        requested_length = max(
            DIRECTIONAL_CUT_DISTANCE_M,
            semantic_extent + SINGLE_SIDED_HORIZONTAL_EXTENSION_M,
        )
        apply_special_rule = requested_length > DIRECTIONAL_CUT_DISTANCE_M + 1e-6
        decision_map[(road_id, branch_index)] = _SingleSidedHorizontalTraceDecision(
            road_id=road_id,
            branch_index=branch_index,
            trace_status=(
                "trace_selected_semantic_plus_5m"
                if apply_special_rule
                else "trace_at_or_below_20m"
            ),
            vertical_seed_rcsdroad_ids=vertical_seed_ids,
            traced_rcsdroad_ids=traced_road_ids,
            traced_rcsdnode_ids=tuple(
                _sorted_ids(node.node_id for node, _projection_distance in hits)
            ),
            semantic_extent_m=round(semantic_extent, 6),
            requested_cut_length_m=round(requested_length, 6),
            apply_special_rule=apply_special_rule,
        )
    return decision_map


def _build_directional_cut_geometry(
    step67_context: Step67Context,
    allowed_space: BaseGeometry | None,
    *,
    force_preserve_single_sided_horizontal_pair: bool = False,
    force_preserve_all_branches: bool = False,
) -> tuple[BaseGeometry | None, BaseGeometry | None, list[dict[str, Any]]]:
    selected_roads = _selected_road_records(step67_context)
    if not selected_roads:
        return None, None, []
    anchor_geometry = _target_anchor_geometry(step67_context)
    clip_extent = _directional_window_half_width(allowed_space) * DIRECTIONAL_WINDOW_EXTENSION_FACTOR
    target_road_ids = set(step67_context.step45_context.step1_context.target_road_ids)
    single_sided_horizontal_pair_ids = _single_sided_horizontal_pair_ids(step67_context)
    single_sided_trace_decisions = _single_sided_horizontal_trace_decisions(
        step67_context,
        allowed_space,
    )
    branch_windows: list[_DirectionalBranchWindow] = []
    branch_decisions: dict[tuple[str, int], _SingleSidedHorizontalTraceDecision] = {}
    keep_geometries: list[BaseGeometry] = []
    trim_geometries: list[BaseGeometry] = []

    for road in selected_roads:
        for branch_index, branch_geometry, anchor_distance in _road_directional_branches(road, anchor_geometry):
            allowed_prefix = _contiguous_allowed_prefix(branch_geometry, allowed_space)
            available_length = allowed_prefix.length if allowed_prefix is not None else 0.0
            trace_decision = single_sided_trace_decisions.get((road.road_id, branch_index))
            branch_decisions[(road.road_id, branch_index)] = trace_decision
            special_cut_length = (
                trace_decision.requested_cut_length_m
                if trace_decision is not None and trace_decision.apply_special_rule
                else None
            )
            special_rule_applied = bool(
                trace_decision is not None and trace_decision.apply_special_rule
            )
            semantic_extent = (
                trace_decision.semantic_extent_m
                if trace_decision is not None
                else None
            )
            force_preserve_horizontal_branch = (
                force_preserve_single_sided_horizontal_pair
                and road.road_id in single_sided_horizontal_pair_ids
            )
            force_preserve_branch = force_preserve_all_branches or force_preserve_horizontal_branch
            target_cut_length = (
                special_cut_length if special_cut_length is not None else DIRECTIONAL_CUT_DISTANCE_M
            )
            preserve_candidate_boundary = force_preserve_branch or (
                available_length < target_cut_length - 1e-6
            )
            cut_length = min(target_cut_length, available_length)
            if force_preserve_branch:
                cut_length = available_length
            core_geometry = _substring_line(allowed_prefix, 0.0, cut_length) if allowed_prefix is not None else None
            clip_geometry = None
            if allowed_prefix is not None and cut_length > 1e-6:
                branch_half_width = (
                    BRANCH_SPECIAL_CLIP_HALF_WIDTH_M
                    if special_rule_applied
                    else BRANCH_CLIP_HALF_WIDTH_M
                )
                local_sector_geometry = _branch_local_sector_geometry(
                    allowed_prefix,
                    branch_half_width,
                    allowed_space,
                )
                if preserve_candidate_boundary:
                    clip_geometry = local_sector_geometry
                else:
                    cut_half_plane = _half_plane_keep_polygon(allowed_prefix, cut_length, clip_extent)
                    clip_geometry = _clean_geometry(
                        local_sector_geometry.intersection(cut_half_plane)
                        if local_sector_geometry is not None and cut_half_plane is not None
                        else local_sector_geometry
                    )
                if clip_geometry is not None:
                    keep_geometries.append(clip_geometry)
                trim_geometry = _branch_local_overrun_mask(
                    allowed_prefix,
                    available_length,
                    cut_length,
                    (
                        BRANCH_SPECIAL_TRIM_HALF_WIDTH_M
                        if special_rule_applied
                        else BRANCH_TRIM_HALF_WIDTH_M
                    ),
                    allowed_space,
                )
                if trim_geometry is not None:
                    trim_geometries.append(trim_geometry)
            branch_windows.append(
                _DirectionalBranchWindow(
                    road_id=road.road_id,
                    branch_index=branch_index,
                    anchor_distance_m=round(anchor_distance, 6),
                    available_length_m=round(available_length, 6),
                    cut_length_m=round(cut_length, 6),
                    preserve_candidate_boundary=preserve_candidate_boundary,
                    special_rule_applied=special_rule_applied,
                    semantic_extent_m=round(semantic_extent, 6) if semantic_extent is not None else None,
                    core_geometry=core_geometry if road.road_id in target_road_ids else None,
                    clip_geometry=clip_geometry,
                )
            )

    direction_clip_geometry = _union_geometries(keep_geometries)
    if direction_clip_geometry is not None and trim_geometries:
        direction_clip_geometry = _clean_geometry(
            direction_clip_geometry.difference(_union_geometries(trim_geometries))
        )
    bridge_geometry = _step3_two_node_t_bridge_geometry(step67_context, allowed_space)
    if bridge_geometry is not None:
        direction_clip_geometry = _union_geometries([direction_clip_geometry, bridge_geometry])
    selected_core_geometry = _union_geometries(
        branch.core_geometry for branch in branch_windows if branch.core_geometry is not None
    )
    audit_rows = [
        {
            "road_id": branch.road_id,
            "branch_index": branch.branch_index,
            "anchor_distance_m": branch.anchor_distance_m,
            "available_length_m": branch.available_length_m,
            "cut_length_m": branch.cut_length_m,
            "preserve_candidate_boundary": branch.preserve_candidate_boundary,
            "special_rule_applied": branch.special_rule_applied,
            "semantic_extent_m": branch.semantic_extent_m,
            "trace_status": (
                branch_decisions[(branch.road_id, branch.branch_index)].trace_status
                if branch_decisions.get((branch.road_id, branch.branch_index)) is not None
                else "no_trace"
            ),
            "trace_vertical_seed_rcsdroad_ids": (
                list(branch_decisions[(branch.road_id, branch.branch_index)].vertical_seed_rcsdroad_ids)
                if branch_decisions.get((branch.road_id, branch.branch_index)) is not None
                else []
            ),
            "trace_traced_rcsdroad_ids": (
                list(branch_decisions[(branch.road_id, branch.branch_index)].traced_rcsdroad_ids)
                if branch_decisions.get((branch.road_id, branch.branch_index)) is not None
                else []
            ),
            "trace_traced_rcsdnode_ids": (
                list(branch_decisions[(branch.road_id, branch.branch_index)].traced_rcsdnode_ids)
                if branch_decisions.get((branch.road_id, branch.branch_index)) is not None
                else []
            ),
            "window_mode": (
                "target_connected_preserve_candidate_boundary"
                if force_preserve_all_branches
                else
                "single_sided_target_connected_preserve_candidate_boundary"
                if force_preserve_single_sided_horizontal_pair and branch.road_id in single_sided_horizontal_pair_ids
                else
                "single_sided_preserve_candidate_boundary"
                if branch.special_rule_applied and branch.preserve_candidate_boundary
                else "single_sided_semantic_plus_5m"
                if branch.special_rule_applied
                else "preserve_candidate_boundary"
                if branch.preserve_candidate_boundary
                else "cut_at_20m"
            ),
        }
        for branch in branch_windows
    ]
    return direction_clip_geometry, selected_core_geometry, audit_rows


def _step6_failure_result(
    *,
    step67_context: Step67Context,
    reason: str,
    primary_root_cause: str,
    secondary_root_cause: str,
    review_signals: Iterable[str] = (),
    output_geometries: Step6OutputGeometries | None = None,
    key_metrics: dict[str, Any] | None = None,
    audit_doc: dict[str, Any] | None = None,
    extra_status_fields: dict[str, Any] | None = None,
) -> Step6Result:
    return Step6Result(
        step6_state="not_established",
        geometry_established=False,
        problem_geometry=True,
        reason=reason,
        primary_root_cause=primary_root_cause,
        secondary_root_cause=secondary_root_cause,
        review_signals=tuple(review_signals),
        output_geometries=output_geometries
        or Step6OutputGeometries(
            polygon_seed_geometry=None,
            polygon_final_geometry=None,
            foreign_mask_geometry=None,
            must_cover_geometry=None,
        ),
        key_metrics=key_metrics or {},
        audit_doc=audit_doc or {},
        extra_status_fields=extra_status_fields or {},
    )


def build_step6_result(step67_context: Step67Context) -> Step6Result:
    step45_context = step67_context.step45_context
    step45_case_result = step67_context.step45_case_result
    step1 = step45_context.step1_context
    template_class = step45_case_result.template_class
    allowed_space = _clean_geometry(step45_context.step3_allowed_space_geometry)
    if allowed_space is None:
        return _step6_failure_result(
            step67_context=step67_context,
            reason="step6_missing_allowed_space",
            primary_root_cause=PRIMARY_INFEASIBLE,
            secondary_root_cause=SECONDARY_STEP1_STEP3_CONFLICT,
        )
    if step45_case_result.step45_state == "not_established":
        return _step6_failure_result(
            step67_context=step67_context,
            reason="step6_blocked_by_step45",
            primary_root_cause=PRIMARY_INFEASIBLE,
            secondary_root_cause=SECONDARY_STEP1_STEP3_CONFLICT,
            extra_status_fields={
                "step45_reason": step45_case_result.reason,
                "step45_state": step45_case_result.step45_state,
            },
        )
    target_cover_geometry = _point_buffers(step1.target_group.nodes, TARGET_NODE_BUFFER_M)
    foreign_mask_geometry, foreign_mask_sources = _build_foreign_mask_geometry(step67_context)
    step3_two_node_t_bridge_geometry = _step3_two_node_t_bridge_geometry(
        step67_context,
        allowed_space,
    )
    direction_clip_geometry, selected_road_core_geometry, directional_cut_branches = _build_directional_cut_geometry(
        step67_context,
        allowed_space,
    )
    polygon_seed_geometry = _clean_geometry(
        allowed_space.intersection(direction_clip_geometry) if direction_clip_geometry is not None else None
    )
    target_connected_boundary_fallback_applied = False
    if (
        step45_case_result.template_class == "single_sided_t_mouth"
        and _node_cover_ratio(step1.target_group.nodes, polygon_seed_geometry) < 1.0
    ):
        direction_clip_geometry, selected_road_core_geometry, directional_cut_branches = _build_directional_cut_geometry(
            step67_context,
            allowed_space,
            force_preserve_single_sided_horizontal_pair=True,
        )
        polygon_seed_geometry = _clean_geometry(
            allowed_space.intersection(direction_clip_geometry) if direction_clip_geometry is not None else None
        )
        target_connected_boundary_fallback_applied = True
    if (
        step45_case_result.template_class == "single_sided_t_mouth"
        and _node_cover_ratio(step1.target_group.nodes, polygon_seed_geometry) < 1.0
    ):
        direction_clip_geometry, selected_road_core_geometry, directional_cut_branches = _build_directional_cut_geometry(
            step67_context,
            allowed_space,
            force_preserve_all_branches=True,
        )
        polygon_seed_geometry = _clean_geometry(
            allowed_space.intersection(direction_clip_geometry) if direction_clip_geometry is not None else None
        )
        target_connected_boundary_fallback_applied = True
    if polygon_seed_geometry is None:
        return _step6_failure_result(
            step67_context=step67_context,
            reason="step6_polygon_seed_empty",
            primary_root_cause=PRIMARY_SOLVER_FAILED,
            secondary_root_cause=SECONDARY_CLOSURE_FAILURE,
            output_geometries=Step6OutputGeometries(
                polygon_seed_geometry=None,
                polygon_final_geometry=None,
                foreign_mask_geometry=foreign_mask_geometry,
                must_cover_geometry=target_cover_geometry,
            ),
        )

    direction_boundary_geometry = polygon_seed_geometry
    local_required_nodes = _local_required_node_records(step67_context, direction_boundary_geometry)
    local_required_road_records = _local_required_road_records(step67_context, direction_boundary_geometry)
    local_required_road_geometry = _local_required_road_geometry(step67_context, direction_boundary_geometry)
    required_node_cover_geometry = _point_buffers(local_required_nodes, REQUIRED_NODE_BUFFER_M)
    required_road_cover_geometry = _line_buffers(
        local_required_road_geometry,
        REQUIRED_ROAD_BUFFER_M,
    )
    must_cover_geometry = _union_geometries(
        [
            target_cover_geometry,
            required_node_cover_geometry,
            required_road_cover_geometry,
        ]
    )

    raw_polygon = _clean_geometry(
        _union_geometries(
            [
                polygon_seed_geometry,
                target_cover_geometry,
                required_node_cover_geometry,
                required_road_cover_geometry,
            ]
        )
    )
    raw_polygon = _clean_geometry(raw_polygon.intersection(allowed_space.buffer(LEGAL_SPACE_TOLERANCE_M)))
    raw_polygon = _clean_geometry(raw_polygon.intersection(direction_boundary_geometry))
    raw_polygon = _retain_components_touching_anchors(
        raw_polygon,
        [
            target_cover_geometry,
            required_node_cover_geometry,
            required_road_cover_geometry,
        ],
    )
    pre_cleanup_polygon = raw_polygon
    if raw_polygon is None:
        return _step6_failure_result(
            step67_context=step67_context,
            reason="step6_polygon_empty_after_legal_clip",
            primary_root_cause=PRIMARY_INFEASIBLE,
            secondary_root_cause=SECONDARY_STEP1_STEP3_CONFLICT,
            output_geometries=Step6OutputGeometries(
                polygon_seed_geometry=polygon_seed_geometry,
                polygon_final_geometry=None,
                foreign_mask_geometry=foreign_mask_geometry,
                must_cover_geometry=must_cover_geometry,
            ),
        )

    final_polygon = raw_polygon
    if foreign_mask_geometry is not None:
        final_polygon = _clean_geometry(final_polygon.difference(foreign_mask_geometry))
        final_polygon = _retain_components_touching_anchors(
            final_polygon,
            [
                target_cover_geometry,
                required_node_cover_geometry,
                required_road_cover_geometry,
            ],
        )
    final_polygon = _clean_geometry(final_polygon)
    if final_polygon is not None:
        final_polygon = _clean_geometry(
            final_polygon.buffer(FINAL_CLOSE_M).buffer(-FINAL_CLOSE_M)
        )
        final_polygon = _clean_geometry(final_polygon.intersection(allowed_space.buffer(LEGAL_SPACE_TOLERANCE_M)))
        final_polygon = _clean_geometry(final_polygon.intersection(direction_boundary_geometry))
        final_polygon = _retain_components_touching_anchors(
            final_polygon,
            [
                target_cover_geometry,
                required_node_cover_geometry,
                required_road_cover_geometry,
            ],
        )

    target_node_cover_ratio = _node_cover_ratio(step1.target_group.nodes, final_polygon)
    selected_core_cover_ratio = _road_core_cover_ratio(selected_road_core_geometry, final_polygon)
    semantic_junction_cover_ok = (
        target_node_cover_ratio >= 1.0
        and selected_core_cover_ratio >= SELECTED_ROAD_CORE_MIN_RATIO
    )
    required_rc_node_cover_ratio = _node_cover_ratio(local_required_nodes, final_polygon)
    required_rc_line_cover_ratio = _line_coverage_ratio(
        local_required_road_geometry,
        final_polygon,
    )
    required_rc_cover_ok = (
        required_rc_node_cover_ratio >= 1.0
        and required_rc_line_cover_ratio >= LINE_COVER_MIN_RATIO
    )
    within_legal_space_ok = bool(
        final_polygon is not None
        and final_polygon.difference(allowed_space.buffer(LEGAL_SPACE_TOLERANCE_M)).area <= 1e-6
    )
    within_direction_boundary_ok = bool(
        final_polygon is not None
        and final_polygon.difference(direction_boundary_geometry).area <= 1e-6
    )
    foreign_overlap_area_m2 = 0.0
    if final_polygon is not None and foreign_mask_geometry is not None:
        foreign_overlap_area_m2 = final_polygon.intersection(foreign_mask_geometry).area
    foreign_exclusion_ok = foreign_overlap_area_m2 <= FOREIGN_OVERLAP_TOLERANCE_M2

    raw_target_cover_ratio = _node_cover_ratio(step1.target_group.nodes, pre_cleanup_polygon)
    raw_required_rc_cover_ratio = _line_coverage_ratio(
        local_required_road_geometry,
        pre_cleanup_polygon,
    )
    review_signals: list[str] = []
    shape_metrics = _shape_metrics(final_polygon)
    if shape_metrics["hole_count"] > 0:
        review_signals.append("polygon_has_holes")
    if shape_metrics["component_count"] > 1:
        review_signals.append("polygon_multicomponent")

    base_audit_doc = {
        "inputs": {
            "template_class": template_class,
            "association_class": step45_case_result.association_class,
            "step45_state": step45_case_result.step45_state,
            "step45_reason": step45_case_result.reason,
            "step3_state": step45_context.step3_status_doc.get("step3_state"),
            "selected_road_ids": list(step45_context.selected_road_ids),
            "required_rcsdnode_ids": list(step45_case_result.extra_status_fields.get("required_rcsdnode_ids") or []),
            "required_rcsdroad_ids": list(step45_case_result.extra_status_fields.get("required_rcsdroad_ids") or []),
            "local_required_rcsdnode_ids": [node.node_id for node in local_required_nodes],
            "local_required_rcsdroad_ids": [road.road_id for road in local_required_road_records],
            "support_rcsdroad_ids": list(step45_case_result.extra_status_fields.get("support_rcsdroad_ids") or []),
            "excluded_rcsdroad_ids": list(step45_case_result.extra_status_fields.get("excluded_rcsdroad_ids") or []),
        },
        "assembly": {
            "geometry_mode": "directional_selected_road_cut",
            "polygon_seed_metrics": _shape_metrics(polygon_seed_geometry),
            "polygon_after_legal_clip_metrics": _shape_metrics(pre_cleanup_polygon),
            "polygon_final_metrics": shape_metrics,
            "direction_clip_metrics": _shape_metrics(direction_clip_geometry),
            "step3_two_node_t_bridge_inherited": step3_two_node_t_bridge_geometry is not None,
            "step3_two_node_t_bridge_metrics": _shape_metrics(step3_two_node_t_bridge_geometry),
            "directional_cut_rule": {
                "mode": "directional_selected_road_cut",
                "cut_distance_m": DIRECTIONAL_CUT_DISTANCE_M,
                "branch_count": len(directional_cut_branches),
            },
            "directional_cut_branches": directional_cut_branches,
            "target_connected_boundary_fallback_applied": target_connected_boundary_fallback_applied,
            "direction_boundary_hard_cap_applied": True,
            "final_close_m": FINAL_CLOSE_M,
            "foreign_mask_buffer_m": FOREIGN_MASK_BUFFER_M,
            "foreign_mask_mode": "road_like_1m_mask",
            "foreign_mask_sources": foreign_mask_sources,
        },
        "validation": {
            "semantic_junction_cover_ok": semantic_junction_cover_ok,
            "target_node_cover_ratio": round(target_node_cover_ratio, 6),
            "selected_road_core_cover_ratio": round(selected_core_cover_ratio, 6),
            "required_rc_cover_ok": required_rc_cover_ok,
            "required_rc_node_cover_ratio": round(required_rc_node_cover_ratio, 6),
            "required_rc_line_cover_ratio": round(required_rc_line_cover_ratio, 6),
            "within_legal_space_ok": within_legal_space_ok,
            "within_direction_boundary_ok": within_direction_boundary_ok,
            "foreign_exclusion_ok": foreign_exclusion_ok,
            "foreign_overlap_area_m2": round(foreign_overlap_area_m2, 6),
            "raw_target_node_cover_ratio": round(raw_target_cover_ratio, 6),
            "raw_required_rc_line_cover_ratio": round(raw_required_rc_cover_ratio, 6),
            "required_rc_cover_mode": "local_required_rc_within_direction_boundary",
        },
    }

    output_geometries = Step6OutputGeometries(
        polygon_seed_geometry=polygon_seed_geometry,
        polygon_final_geometry=final_polygon,
        foreign_mask_geometry=foreign_mask_geometry,
        must_cover_geometry=must_cover_geometry,
    )
    key_metrics = {
        **shape_metrics,
        "target_node_cover_ratio": round(target_node_cover_ratio, 6),
        "selected_road_core_cover_ratio": round(selected_core_cover_ratio, 6),
        "required_rc_node_cover_ratio": round(required_rc_node_cover_ratio, 6),
        "required_rc_line_cover_ratio": round(required_rc_line_cover_ratio, 6),
        "foreign_overlap_area_m2": round(foreign_overlap_area_m2, 6),
    }
    extra_status_fields = {
        "semantic_junction_cover_ok": semantic_junction_cover_ok,
        "required_rc_cover_ok": required_rc_cover_ok,
        "within_legal_space_ok": within_legal_space_ok,
        "within_direction_boundary_ok": within_direction_boundary_ok,
        "foreign_exclusion_ok": foreign_exclusion_ok,
        "target_node_cover_ratio": round(target_node_cover_ratio, 6),
        "selected_road_core_cover_ratio": round(selected_core_cover_ratio, 6),
        "required_rc_node_cover_ratio": round(required_rc_node_cover_ratio, 6),
        "required_rc_line_cover_ratio": round(required_rc_line_cover_ratio, 6),
        "foreign_overlap_area_m2": round(foreign_overlap_area_m2, 6),
    }

    if final_polygon is None:
        return _step6_failure_result(
            step67_context=step67_context,
            reason="step6_polygon_lost_after_cleanup",
            primary_root_cause=PRIMARY_SOLVER_FAILED,
            secondary_root_cause=SECONDARY_CLEANUP_OVERTRIM,
            output_geometries=output_geometries,
            key_metrics=key_metrics,
            audit_doc={
                **base_audit_doc,
                "decision": {
                    "reason": "step6_polygon_lost_after_cleanup",
                    "primary_root_cause": PRIMARY_SOLVER_FAILED,
                    "secondary_root_cause": SECONDARY_CLEANUP_OVERTRIM,
                },
            },
            extra_status_fields=extra_status_fields,
        )

    if not semantic_junction_cover_ok:
        secondary = (
            SECONDARY_CLEANUP_OVERTRIM
            if raw_target_cover_ratio >= 1.0
            else SECONDARY_STEP1_STEP3_CONFLICT
        )
        primary = (
            PRIMARY_SOLVER_FAILED
            if secondary == SECONDARY_CLEANUP_OVERTRIM
            else PRIMARY_INFEASIBLE
        )
        return _step6_failure_result(
            step67_context=step67_context,
            reason="step6_semantic_junction_not_covered",
            primary_root_cause=primary,
            secondary_root_cause=secondary,
            output_geometries=output_geometries,
            key_metrics=key_metrics,
            audit_doc={
                **base_audit_doc,
                "decision": {
                    "reason": "step6_semantic_junction_not_covered",
                    "primary_root_cause": primary,
                    "secondary_root_cause": secondary,
                },
            },
            extra_status_fields=extra_status_fields,
        )

    if not required_rc_cover_ok:
        secondary = (
            SECONDARY_CLEANUP_OVERTRIM
            if raw_required_rc_cover_ratio >= LINE_COVER_MIN_RATIO
            else SECONDARY_STAGE3_RC_GAP
        )
        primary = (
            PRIMARY_SOLVER_FAILED
            if secondary == SECONDARY_CLEANUP_OVERTRIM
            else PRIMARY_INFEASIBLE
        )
        return _step6_failure_result(
            step67_context=step67_context,
            reason="step6_required_rc_not_covered",
            primary_root_cause=primary,
            secondary_root_cause=secondary,
            output_geometries=output_geometries,
            key_metrics=key_metrics,
            audit_doc={
                **base_audit_doc,
                "decision": {
                    "reason": "step6_required_rc_not_covered",
                    "primary_root_cause": primary,
                    "secondary_root_cause": secondary,
                },
            },
            extra_status_fields=extra_status_fields,
        )

    if not within_legal_space_ok:
        return _step6_failure_result(
            step67_context=step67_context,
            reason="step6_escaped_legal_space",
            primary_root_cause=PRIMARY_INFEASIBLE,
            secondary_root_cause=SECONDARY_STEP1_STEP3_CONFLICT,
            output_geometries=output_geometries,
            key_metrics=key_metrics,
            audit_doc={
                **base_audit_doc,
                "decision": {
                    "reason": "step6_escaped_legal_space",
                    "primary_root_cause": PRIMARY_INFEASIBLE,
                    "secondary_root_cause": SECONDARY_STEP1_STEP3_CONFLICT,
                },
            },
            extra_status_fields=extra_status_fields,
        )

    if not foreign_exclusion_ok:
        secondary = (
            SECONDARY_FOREIGN_REINTRODUCED
            if pre_cleanup_polygon is not None
            and pre_cleanup_polygon.intersection(foreign_mask_geometry).area
            <= 1e-6
            else SECONDARY_FOREIGN_CONFLICT
        )
        return _step6_failure_result(
            step67_context=step67_context,
            reason="step6_foreign_intrusion_remains",
            primary_root_cause=PRIMARY_INFEASIBLE,
            secondary_root_cause=secondary,
            output_geometries=output_geometries,
            key_metrics=key_metrics,
            audit_doc={
                **base_audit_doc,
                "decision": {
                    "reason": "step6_foreign_intrusion_remains",
                    "primary_root_cause": PRIMARY_INFEASIBLE,
                    "secondary_root_cause": secondary,
                },
            },
            extra_status_fields=extra_status_fields,
        )

    severe_template_misfit = False
    severe_reason = None
    if template_class == "single_sided_t_mouth":
        # Boundary-first single-sided outputs can legitimately form two lobes while
        # still satisfying legal/foreign/must-cover constraints; keep this as a
        # visual review signal instead of a hard failure.
        severe_template_misfit = (
            (shape_metrics["compactness"] is not None and shape_metrics["compactness"] < 0.12)
            or (shape_metrics["bbox_fill_ratio"] is not None and shape_metrics["bbox_fill_ratio"] < 0.11)
        )
        severe_reason = "step6_single_sided_shape_artifact" if severe_template_misfit else None
    else:
        severe_template_misfit = (
            (shape_metrics["compactness"] is not None and shape_metrics["compactness"] < 0.14)
            or (shape_metrics["bbox_fill_ratio"] is not None and shape_metrics["bbox_fill_ratio"] < 0.12)
            or shape_metrics["component_count"] > 1
        )
        severe_reason = "step6_center_shape_artifact" if severe_template_misfit else None
    if severe_template_misfit:
        secondary = (
            SECONDARY_CLOSURE_FAILURE
            if shape_metrics["component_count"] > 1
            else SECONDARY_SHAPE_ARTIFACT
        )
        return _step6_failure_result(
            step67_context=step67_context,
            reason=severe_reason or "step6_shape_artifact",
            primary_root_cause=PRIMARY_SOLVER_FAILED,
            secondary_root_cause=secondary,
            review_signals=review_signals,
            output_geometries=output_geometries,
            key_metrics=key_metrics,
            audit_doc={
                **base_audit_doc,
                "decision": {
                    "reason": severe_reason or "step6_shape_artifact",
                    "primary_root_cause": PRIMARY_SOLVER_FAILED,
                    "secondary_root_cause": secondary,
                },
            },
            extra_status_fields=extra_status_fields,
        )

    return Step6Result(
        step6_state="established",
        geometry_established=True,
        problem_geometry=bool(review_signals),
        reason="step6_geometry_established",
        primary_root_cause=None,
        secondary_root_cause=None,
        review_signals=tuple(review_signals),
        output_geometries=output_geometries,
        key_metrics=key_metrics,
        audit_doc={
            **base_audit_doc,
            "decision": {
                "reason": "step6_geometry_established",
                "primary_root_cause": None,
                "secondary_root_cause": None,
                "review_signals": list(review_signals),
            },
        },
        extra_status_fields=extra_status_fields,
    )


def build_step6_status_doc(step67_context: Step67Context, step6_result: Step6Result) -> dict[str, Any]:
    step45_case_result = step67_context.step45_case_result
    return {
        "case_id": step67_context.step45_context.step1_context.case_spec.case_id,
        "template_class": step45_case_result.template_class,
        "association_class": step45_case_result.association_class,
        "step45_state": step45_case_result.step45_state,
        "step6_state": step6_result.step6_state,
        "geometry_established": step6_result.geometry_established,
        "problem_geometry": step6_result.problem_geometry,
        "reason": step6_result.reason,
        "primary_root_cause": step6_result.primary_root_cause,
        "secondary_root_cause": step6_result.secondary_root_cause,
        "review_signals": list(step6_result.review_signals),
        "key_metrics": step6_result.key_metrics,
        **step6_result.extra_status_fields,
    }
