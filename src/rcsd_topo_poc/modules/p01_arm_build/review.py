from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import LineString, Point
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p01_arm_build.models import DatasetBuildResult, LoadedDataset


ROAD_GREY = (160, 160, 160, 255)
INTERNAL_ORANGE = (245, 147, 66, 255)
EXCLUDED_RED = (210, 45, 45, 255)
ADVANCE_LEFT_PURPLE = (126, 63, 178, 255)
ADVANCE_RIGHT_MAGENTA = (214, 39, 135, 255)
TRUNK_DARK = (25, 25, 25, 255)
CORRIDOR_CYAN = (38, 146, 170, 255)
NODE_BLUE = (35, 95, 190, 255)
TEXT = (20, 20, 20, 255)
ARM_COLORS = [
    (31, 119, 180, 255),
    (44, 160, 44, 255),
    (148, 103, 189, 255),
    (255, 127, 14, 255),
    (23, 190, 207, 255),
    (214, 39, 40, 255),
]
TURN_COLORS = {
    "straight": (44, 160, 44, 255),
    "left": (255, 127, 14, 255),
    "right": (31, 119, 180, 255),
    "unknown": (110, 110, 110, 255),
}
MOVEMENT_AUDIT_HALF_WIDTH_METERS = 200.0
PASS_AUDIT_HALF_WIDTH_METERS = 60.0


def _geometry_bounds(geometries: list[BaseGeometry]) -> tuple[float, float, float, float]:
    non_empty = [geom for geom in geometries if geom is not None and not geom.is_empty]
    if not non_empty:
        return (-1.0, -1.0, 1.0, 1.0)
    minx = min(geom.bounds[0] for geom in non_empty)
    miny = min(geom.bounds[1] for geom in non_empty)
    maxx = max(geom.bounds[2] for geom in non_empty)
    maxy = max(geom.bounds[3] for geom in non_empty)
    if minx == maxx:
        minx -= 1.0
        maxx += 1.0
    if miny == maxy:
        miny -= 1.0
        maxy += 1.0
    pad_x = (maxx - minx) * 0.12
    pad_y = (maxy - miny) * 0.12
    return (minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y)


def _projector(
    bounds: tuple[float, float, float, float],
    *,
    left: int,
    top: int,
    width: int,
    height: int,
    margin: int = 24,
):
    minx, miny, maxx, maxy = bounds
    sx = (width - margin * 2) / max(maxx - minx, 1e-9)
    sy = (height - margin * 2) / max(maxy - miny, 1e-9)
    scale = min(sx, sy)
    used_w = (maxx - minx) * scale
    used_h = (maxy - miny) * scale
    x0 = left + (width - used_w) / 2
    y0 = top + (height - used_h) / 2

    def project(x: float, y: float) -> tuple[int, int]:
        px = x0 + (x - minx) * scale
        py = y0 + (maxy - y) * scale
        return int(round(px)), int(round(py))

    return project


def _line_points(geometry: BaseGeometry, project) -> list[tuple[int, int]]:
    if geometry.geom_type == "LineString":
        return [_project_coord(coord, project) for coord in geometry.coords]
    if geometry.geom_type == "MultiLineString":
        points: list[tuple[int, int]] = []
        for part in geometry.geoms:
            points.extend(_project_coord(coord, project) for coord in part.coords)
        return points
    center = geometry.centroid
    return [project(float(center.x), float(center.y))]


def _project_coord(coord, project) -> tuple[int, int]:
    return project(float(coord[0]), float(coord[1]))


def _draw_line(draw: ImageDraw.ImageDraw, geometry: BaseGeometry, project, *, fill, width: int = 3) -> None:
    points = _line_points(geometry, project)
    if len(points) >= 2:
        draw.line(points, fill=fill, width=width, joint="curve")


def _draw_point(draw: ImageDraw.ImageDraw, point: BaseGeometry, project, *, fill, radius: int = 5) -> None:
    center = point if point.geom_type == "Point" else point.centroid
    x, y = project(float(center.x), float(center.y))
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=fill, outline=(255, 255, 255, 255), width=1)


def _text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, font, fill=TEXT) -> None:
    x, y = xy
    bbox = draw.textbbox((x, y), text, font=font)
    draw.rectangle((bbox[0] - 2, bbox[1] - 1, bbox[2] + 2, bbox[3] + 1), fill=(255, 255, 255, 210))
    draw.text((x, y), text, font=font, fill=fill)


def _is_geographic_dataset(loaded: LoadedDataset) -> bool:
    text = f"{loaded.road_layer.crs or ''} {loaded.road_layer.crs_wkt or ''} {loaded.node_layer.crs or ''} {loaded.node_layer.crs_wkt or ''}".lower()
    return "4326" in text or "crs84" in text or "longlat" in text or "degree" in text


def _junction_center(loaded: LoadedDataset, result: DatasetBuildResult) -> Point:
    points = [
        loaded.nodes[node_id].geometry.centroid
        for node_id in result.context.member_node_ids
        if node_id in loaded.nodes and loaded.nodes[node_id].geometry is not None and not loaded.nodes[node_id].geometry.is_empty
    ]
    if points:
        return Point(sum(point.x for point in points) / len(points), sum(point.y for point in points) / len(points))
    geometries = [road.geometry for road in loaded.roads.values() if road.geometry is not None and not road.geometry.is_empty]
    if geometries:
        centroid = geometries[0].centroid
        return Point(float(centroid.x), float(centroid.y))
    return Point(0.0, 0.0)


def _local_meter_bounds(
    loaded: LoadedDataset,
    result: DatasetBuildResult,
    *,
    half_width_meters: float,
    aspect_width: int,
    aspect_height: int,
) -> tuple[float, float, float, float]:
    center = _junction_center(loaded, result)
    aspect = aspect_height / max(aspect_width, 1)
    if _is_geographic_dataset(loaded):
        lat_rad = math.radians(float(center.y))
        half_x = half_width_meters / max(111_320.0 * max(math.cos(lat_rad), 0.1), 1e-9)
        half_y = half_width_meters * aspect / 110_540.0
    else:
        half_x = half_width_meters
        half_y = half_width_meters * aspect
    return (float(center.x) - half_x, float(center.y) - half_y, float(center.x) + half_x, float(center.y) + half_y)


def _point_in_bounds(point: Point, bounds: tuple[float, float, float, float]) -> bool:
    minx, miny, maxx, maxy = bounds
    return minx <= float(point.x) <= maxx and miny <= float(point.y) <= maxy


def _road_midpoint(loaded: LoadedDataset, road_id: str) -> Point | None:
    road = loaded.roads.get(road_id)
    if road is None or road.geometry is None or road.geometry.is_empty:
        return None
    return road.geometry.interpolate(0.5, normalized=True)


def _road_local_point(loaded: LoadedDataset, road_id: str, center: Point, *, offset_ratio: float = 0.14) -> Point | None:
    road = loaded.roads.get(road_id)
    if road is None or road.geometry is None or road.geometry.is_empty or road.geometry.geom_type != "LineString":
        return _road_midpoint(loaded, road_id)
    coords = list(road.geometry.coords)
    if len(coords) < 2:
        return _road_midpoint(loaded, road_id)
    start = Point(float(coords[0][0]), float(coords[0][1]))
    end = Point(float(coords[-1][0]), float(coords[-1][1]))
    near, far = (start, end) if start.distance(center) <= end.distance(center) else (end, start)
    return Point(
        float(near.x) + (float(far.x) - float(near.x)) * offset_ratio,
        float(near.y) + (float(far.y) - float(near.y)) * offset_ratio,
    )


def _road_endpoints(loaded: LoadedDataset, road_id: str) -> tuple[Point, Point] | None:
    road = loaded.roads.get(road_id)
    if road is None or road.geometry is None or road.geometry.is_empty:
        return None
    geometry = road.geometry
    if geometry.geom_type == "LineString":
        coords = list(geometry.coords)
    elif geometry.geom_type == "MultiLineString":
        parts = [part for part in geometry.geoms if not part.is_empty and len(part.coords) >= 2]
        if not parts:
            return None
        longest = max(parts, key=lambda item: item.length)
        coords = list(longest.coords)
    else:
        return None
    if len(coords) < 2:
        return None
    return Point(float(coords[0][0]), float(coords[0][1])), Point(float(coords[-1][0]), float(coords[-1][1]))


def _road_junction_endpoint(loaded: LoadedDataset, road_id: str, center: Point) -> Point | None:
    endpoints = _road_endpoints(loaded, road_id)
    if endpoints is None:
        return _road_midpoint(loaded, road_id)
    start, end = endpoints
    return start if start.distance(center) <= end.distance(center) else end


def _road_near_segment(
    loaded: LoadedDataset,
    road_id: str,
    center: Point,
    *,
    ratio: float = 1.0,
    max_length_meters: float = 50.0,
) -> LineString | None:
    endpoints = _road_endpoints(loaded, road_id)
    if endpoints is None:
        return None
    start, end = endpoints
    near, far = (start, end) if start.distance(center) <= end.distance(center) else (end, start)
    if _is_geographic_dataset(loaded):
        lat_rad = math.radians(float(near.y))
        dx_m = (float(far.x) - float(near.x)) * 111_320.0 * max(math.cos(lat_rad), 0.1)
        dy_m = (float(far.y) - float(near.y)) * 110_540.0
        length_for_clip = max(math.hypot(dx_m, dy_m), 1e-9)
    else:
        length_for_clip = max(near.distance(far), 1e-9)
    clip_ratio = min(ratio, max_length_meters / length_for_clip)
    clipped = Point(
        float(near.x) + (float(far.x) - float(near.x)) * clip_ratio,
        float(near.y) + (float(far.y) - float(near.y)) * clip_ratio,
    )
    return LineString([near, clipped])


def _final_arm_road_ids(arm: Any) -> tuple[str, ...]:
    payload = arm.initial_arm if hasattr(arm, "initial_arm") else {}
    return tuple(str(item) for item in (payload.get("member_road_ids", []) or arm.trunk_road_ids or payload.get("seed_road_ids", [])))


def _final_arm_display_road_ids(arm: Any) -> tuple[str, ...]:
    payload = arm.initial_arm if hasattr(arm, "initial_arm") else {}
    values: list[str] = []
    for key in (
        "member_road_ids",
        "seed_road_ids",
        "connector_road_ids",
        "inbound_member_road_ids",
        "outbound_member_road_ids",
        "bidirectional_member_road_ids",
    ):
        values.extend(str(item) for item in payload.get(key, []) or ())
    values.extend(str(item) for item in getattr(arm, "trunk_road_ids", tuple()) or ())
    values.extend(str(item) for item in getattr(arm, "non_trunk_member_road_ids", tuple()) or ())
    return tuple(dict.fromkeys(values))


def _final_arm_color_map(result: DatasetBuildResult) -> dict[str, tuple[int, int, int, int]]:
    return {arm.final_arm_id: ARM_COLORS[index % len(ARM_COLORS)] for index, arm in enumerate(result.final_arms)}


def _draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    fill: tuple[int, int, int, int],
    width: int,
    dashed: bool = False,
    label: str | None = None,
) -> None:
    sx, sy = start
    ex, ey = end
    if math.hypot(ex - sx, ey - sy) < 8:
        return
    if dashed:
        total = math.hypot(ex - sx, ey - sy)
        dash_len = 10
        gap_len = 7
        pos = 0.0
        while pos < total:
            end_pos = min(pos + dash_len, total)
            t1 = pos / total
            t2 = end_pos / total
            draw.line(
                (sx + (ex - sx) * t1, sy + (ey - sy) * t1, sx + (ex - sx) * t2, sy + (ey - sy) * t2),
                fill=fill,
                width=width,
            )
            pos += dash_len + gap_len
    else:
        draw.line((sx, sy, ex, ey), fill=fill, width=width)
    angle = math.atan2(ey - sy, ex - sx)
    size = 7
    left = (ex - size * math.cos(angle - math.pi / 6), ey - size * math.sin(angle - math.pi / 6))
    right = (ex - size * math.cos(angle + math.pi / 6), ey - size * math.sin(angle + math.pi / 6))
    draw.polygon([(ex, ey), left, right], fill=fill)
    if label:
        mx, my = (sx + ex) / 2, (sy + ey) / 2
        draw.text((mx + 4, my + 4), label, font=ImageFont.load_default(), fill=fill)


def _offset_segment(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    offset_px: float,
) -> tuple[tuple[int, int], tuple[int, int]]:
    sx, sy = start
    ex, ey = end
    length = math.hypot(ex - sx, ey - sy)
    if length < 1e-6 or abs(offset_px) < 1e-6:
        return start, end
    nx = -(ey - sy) / length
    ny = (ex - sx) / length
    return (
        (round(sx + nx * offset_px), round(sy + ny * offset_px)),
        (round(ex + nx * offset_px), round(ey + ny * offset_px)),
    )


def _segment_overlap_key(start: tuple[int, int], end: tuple[int, int]) -> tuple[tuple[int, int], tuple[int, int]]:
    a = (round(start[0] / 2) * 2, round(start[1] / 2) * 2)
    b = (round(end[0] / 2) * 2, round(end[1] / 2) * 2)
    return (a, b) if a <= b else (b, a)


def _draw_same_endpoint_marker(
    draw: ImageDraw.ImageDraw,
    point: tuple[int, int],
    *,
    fill: tuple[int, int, int, int],
    index: int,
    total: int,
    dashed: bool,
    label: str | None = None,
) -> None:
    cx, cy = point
    if total <= 1:
        angle = -math.pi / 4
    else:
        angle = -math.pi / 2 + (2 * math.pi * index / total)
    inner = 7
    outer = 20 + (index // 8) * 6
    start = (round(cx + math.cos(angle) * inner), round(cy + math.sin(angle) * inner))
    end = (round(cx + math.cos(angle) * outer), round(cy + math.sin(angle) * outer))
    draw.ellipse((cx - 5, cy - 5, cx + 5, cy + 5), outline=fill, width=2)
    _draw_arrow(draw, start, end, fill=fill, width=2, dashed=dashed, label=label)


def _draw_final_arm_near_roads(
    draw: ImageDraw.ImageDraw,
    loaded: LoadedDataset,
    result: DatasetBuildResult,
    *,
    project,
    bounds: tuple[float, float, float, float],
    width: int,
    label: bool,
    font,
) -> dict[str, tuple[int, int, int, int]]:
    colors = _final_arm_color_map(result)
    center = _junction_center(loaded, result)
    corridor_by_arm = {item.final_arm_id: item.support_road_ids for item in result.arm_corridor_evidence}
    for arm in result.final_arms:
        color = colors[arm.final_arm_id]
        road_ids = tuple(dict.fromkeys(_final_arm_display_road_ids(arm) + tuple(corridor_by_arm.get(arm.final_arm_id, tuple()))))
        label_point = None
        for road_id in road_ids:
            segment = _road_near_segment(loaded, road_id, center)
            if segment is None or not segment.intersects(LineString([(bounds[0], bounds[1]), (bounds[2], bounds[1]), (bounds[2], bounds[3]), (bounds[0], bounds[3])]).envelope):
                continue
            _draw_line(draw, segment, project, fill=color, width=width)
            label_point = label_point or segment.interpolate(0.85, normalized=True)
        if label and label_point is not None:
            _text(draw, project(float(label_point.x), float(label_point.y)), arm.final_arm_id, font=font)
    return colors


def _draw_final_arm_roads(
    draw: ImageDraw.ImageDraw,
    loaded: LoadedDataset,
    result: DatasetBuildResult,
    *,
    project,
    bounds: tuple[float, float, float, float],
    width: int,
    label: bool,
    font,
) -> dict[str, tuple[int, int, int, int]]:
    colors = _final_arm_color_map(result)
    corridor_by_arm = {item.final_arm_id: item.support_road_ids for item in result.arm_corridor_evidence}
    for arm in result.final_arms:
        color = colors[arm.final_arm_id]
        road_ids = tuple(dict.fromkeys(_final_arm_road_ids(arm) + tuple(corridor_by_arm.get(arm.final_arm_id, tuple()))))
        label_point = None
        for road_id in road_ids:
            road = loaded.roads.get(road_id)
            if road is None or road.geometry is None or road.geometry.is_empty or not road.geometry.intersects(LineString([(bounds[0], bounds[1]), (bounds[2], bounds[1]), (bounds[2], bounds[3]), (bounds[0], bounds[3])]).envelope):
                continue
            _draw_line(draw, road.geometry, project, fill=color, width=width)
            label_point = label_point or road.geometry.interpolate(0.55, normalized=True)
        if label and label_point is not None:
            _text(draw, project(float(label_point.x), float(label_point.y)), arm.final_arm_id, font=font)
    return colors


def _arm_color_map(result: DatasetBuildResult) -> dict[str, tuple[int, int, int, int]]:
    colors: dict[str, tuple[int, int, int, int]] = {}
    for idx, arm in enumerate(result.initial_arms):
        color = ARM_COLORS[idx % len(ARM_COLORS)]
        for road_id in arm.member_road_ids:
            colors[road_id] = color
    return colors


def _role_by_seed(result: DatasetBuildResult) -> dict[str, str]:
    roles: dict[str, str] = {}
    for trace in result.traces:
        roles[trace.seed_road_id] = {"inbound": "IN", "outbound": "OUT", "bidirectional": "BI"}.get(trace.seed_role, trace.seed_role)
    return roles


def _draw_dataset_panel(
    draw: ImageDraw.ImageDraw,
    loaded: LoadedDataset,
    result: DatasetBuildResult,
    *,
    bounds: tuple[float, float, float, float],
    road_ids: set[str],
    node_ids: set[str],
    panel: tuple[int, int, int, int],
    title: str,
    font,
) -> None:
    left, top, width, height = panel
    project = _projector(bounds, left=left, top=top + 28, width=width, height=height - 28)
    draw.rectangle((left, top, left + width - 1, top + height - 1), outline=(210, 210, 210, 255), width=1)
    _text(draw, (left + 8, top + 6), title, font=font)

    arm_colors = _arm_color_map(result)
    seed_roles = _role_by_seed(result)
    internal_ids = set(result.context.internal_road_ids)
    excluded_ids = set(result.context.excluded_right_turn_road_ids)
    advance_left_ids = set(result.context.advance_left_turn_road_ids)
    advance_right_ids = set(result.context.advance_right_turn_road_ids)
    trunk_ids = {road_id for arm in result.initial_arms for road_id in arm.trunk_road_ids}
    corridor_ids = {road_id for evidence in result.arm_corridor_evidence for road_id in evidence.support_road_ids}
    corrected_trunk_ids = {road_id for correction in result.trunk_corrections for road_id in correction.corrected_trunk_road_ids}
    movement_excluded_ids = {
        road_id for correction in result.trunk_corrections for road_id in correction.movement_excluded_receiving_road_ids
    }
    member_nodes = set(result.context.member_node_ids)

    for road_id in sorted(road_ids):
        road = loaded.roads.get(road_id)
        if road is None:
            continue
        color = ROAD_GREY
        width_px = 2
        if road.road_id in advance_right_ids:
            color = ADVANCE_RIGHT_MAGENTA
            width_px = 5
        elif road.road_id in advance_left_ids:
            color = ADVANCE_LEFT_PURPLE
            width_px = 5
        elif road.road_id in trunk_ids:
            color = TRUNK_DARK
            width_px = 6
        elif road.road_id in corrected_trunk_ids:
            color = TRUNK_DARK
            width_px = 5
        elif road.road_id in internal_ids:
            color = INTERNAL_ORANGE
            width_px = 5
        elif road.road_id in excluded_ids:
            color = EXCLUDED_RED
            width_px = 4
        elif road.road_id in arm_colors:
            color = arm_colors[road.road_id]
            width_px = 4
        elif road.road_id in corridor_ids:
            color = CORRIDOR_CYAN
            width_px = 3
        _draw_line(draw, road.geometry, project, fill=color, width=width_px)

    for node_id in sorted(node_ids & member_nodes):
        node = loaded.nodes.get(node_id)
        if node:
            _draw_point(draw, node.geometry, project, fill=NODE_BLUE, radius=6)
            center = node.geometry.centroid
            _text(draw, project(float(center.x), float(center.y)), "J", font=font)

    for arm in result.initial_arms:
        first_road = loaded.roads.get(arm.seed_road_ids[0]) if arm.seed_road_ids else None
        if first_road:
            center = first_road.geometry.interpolate(0.5, normalized=True)
            _text(
                draw,
                project(float(center.x), float(center.y)),
                f"{arm.initial_arm_id} {arm.terminal_type}",
                font=font,
            )

    for candidate in result.local_arm_candidates:
        first_road = loaded.roads.get(candidate.source_seed_road_ids[0]) if candidate.source_seed_road_ids else None
        if first_road:
            center = first_road.geometry.interpolate(0.7, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), candidate.local_arm_candidate_id, font=font)

    for road_id, role in seed_roles.items():
        road = loaded.roads.get(road_id)
        if road:
            center = road.geometry.interpolate(0.25, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), role, font=font)

    for road_id in sorted(trunk_ids):
        road = loaded.roads.get(road_id)
        if road and road_id in road_ids:
            center = road.geometry.interpolate(0.55, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), "TRUNK", font=font)
    for road_id in sorted(corrected_trunk_ids - trunk_ids):
        road = loaded.roads.get(road_id)
        if road and road_id in road_ids:
            center = road.geometry.interpolate(0.5, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), "Corrected trunk", font=font)
    for road_id in sorted(movement_excluded_ids):
        road = loaded.roads.get(road_id)
        if road and road_id in road_ids:
            center = road.geometry.interpolate(0.45, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), "AdvL-only recv", font=font, fill=EXCLUDED_RED)

    for road_id in sorted(advance_left_ids):
        road = loaded.roads.get(road_id)
        if road and road_id in road_ids:
            center = road.geometry.interpolate(0.62, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), "AdvL", font=font, fill=ADVANCE_LEFT_PURPLE)

    relation_by_road = {
        road_id: relation
        for relation in result.advance_right_turn_relations
        for road_id in relation.advance_right_turn_road_ids
    }
    for road_id in sorted(advance_right_ids):
        road = loaded.roads.get(road_id)
        if road and road_id in road_ids:
            relation = relation_by_road.get(road_id)
            label = "R7:?"
            if relation and relation.from_arm_id and relation.to_arm_id:
                label = f"R7:{relation.from_arm_id}->{relation.to_arm_id}"
            center = road.geometry.interpolate(0.7, normalized=True)
            _text(draw, project(float(center.x), float(center.y)), label, font=font, fill=ADVANCE_RIGHT_MAGENTA)

    decision_labels = {
        "simple_through": "S",
        "t_mainline_through": "T",
        "t_side_terminal": "TS",
        "ambiguous_boundary": "?",
        "semantic_boundary": "X",
        "patch_boundary": "P",
        "dead_end": "D",
        "loop_to_current_junction": "L",
    }
    for decision in result.decisions:
        for node_id in decision.member_node_ids[:1]:
            if node_id not in node_ids:
                continue
            node = loaded.nodes.get(node_id)
            if node:
                center = node.geometry.centroid
                _text(draw, project(float(center.x), float(center.y)), decision_labels.get(decision.status, decision.status), font=font)


def render_dataset_review_png(path: Path, loaded: LoadedDataset, result: DatasetBuildResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1000, 760
    image = Image.new("RGBA", (width, height), (250, 250, 248, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    geometries, road_ids, node_ids = _dataset_review_context(loaded, result)
    bounds = _geometry_bounds(geometries)
    metrics = result.metrics
    title = (
        f"{result.dataset} junction={result.junction_id} "
        f"arms={metrics['initial_arm_count']} stable={metrics['stable_arm_count']} "
        f"issue={metrics['issue_count']} R7={metrics['advance_right_turn_road_count']} "
        f"L8={metrics['advance_left_turn_road_count']} mov={metrics['arm_movement_count']} "
        f"corr={metrics['trunk_correction_count']} "
        f"valC={metrics['final_arm_validation_conflict_count']}"
    )
    _draw_dataset_panel(
        draw,
        loaded,
        result,
        bounds=bounds,
        road_ids=road_ids,
        node_ids=node_ids,
        panel=(0, 0, width, height),
        title=title,
        font=font,
    )
    image.convert("RGB").save(path)


def render_movement_turn_audit_png(path: Path, loaded: LoadedDataset, result: DatasetBuildResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1220, 760
    legend_w = 390
    map_w = width - legend_w
    image = Image.new("RGBA", (width, height), (250, 250, 248, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    bounds = _local_meter_bounds(
        loaded,
        result,
        half_width_meters=MOVEMENT_AUDIT_HALF_WIDTH_METERS,
        aspect_width=map_w,
        aspect_height=height,
    )
    project = _projector(bounds, left=0, top=32, width=map_w, height=height - 32, margin=26)
    draw.rectangle((0, 0, map_w - 1, height - 1), outline=(210, 210, 210, 255), width=1)
    _text(draw, (8, 8), f"{result.dataset} movement turn audit junction={result.junction_id}", font=font)
    arm_colors = _draw_final_arm_roads(draw, loaded, result, project=project, bounds=bounds, width=7, label=True, font=font)
    center = _junction_center(loaded, result)
    if _point_in_bounds(center, bounds):
        _draw_point(draw, center, project, fill=(0, 0, 0, 255), radius=4)

    legend_left = map_w + 14
    draw.rectangle((map_w, 0, width - 1, height - 1), fill=(255, 255, 255, 255), outline=(210, 210, 210, 255))
    _text(draw, (legend_left, 10), "Arm color", font=font)
    y = 34
    for arm_id, color in arm_colors.items():
        draw.rectangle((legend_left, y + 2, legend_left + 18, y + 14), fill=color)
        draw.text((legend_left + 26, y), arm_id, font=font, fill=TEXT)
        y += 20
    y += 8
    _text(draw, (legend_left, y), "Turn legend", font=font)
    y += 24
    movements = [
        movement
        for movement in result.arm_movements
        if movement.from_arm_id != movement.to_arm_id and movement.movement_type in {"straight", "left", "right", "unknown"}
    ]
    for movement in sorted(movements, key=lambda item: (item.from_arm_id, item.to_arm_id))[:30]:
        from_color = arm_colors.get(movement.from_arm_id, ROAD_GREY)
        to_color = arm_colors.get(movement.to_arm_id, ROAD_GREY)
        turn_color = TURN_COLORS.get(movement.movement_type, TURN_COLORS["unknown"])
        draw.rectangle((legend_left, y + 3, legend_left + 15, y + 15), fill=from_color)
        draw.text((legend_left + 19, y), "->", font=font, fill=TEXT)
        draw.rectangle((legend_left + 38, y + 3, legend_left + 53, y + 15), fill=to_color)
        unknown_mark = "? " if movement.movement_type == "unknown" else ""
        label = (
            f"{movement.from_arm_id}->{movement.to_arm_id} {unknown_mark}{movement.movement_type} "
            f"{movement.permission_evidence_status}"
        )
        draw.text((legend_left + 60, y), label[:48], font=font, fill=turn_color)
        y += 19
        if y > height - 28:
            draw.text((legend_left, y), "...", font=font, fill=TEXT)
            break
    image.convert("RGB").save(path)


def render_pass_capability_audit_png(
    path: Path,
    loaded_frcsd: LoadedDataset,
    result_frcsd: DatasetBuildResult,
    final_result: Any,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1100, 900
    image = Image.new("RGBA", (width, height), (250, 250, 248, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    bounds = _local_meter_bounds(
        loaded_frcsd,
        result_frcsd,
        half_width_meters=PASS_AUDIT_HALF_WIDTH_METERS,
        aspect_width=width,
        aspect_height=height,
    )
    project = _projector(bounds, left=0, top=40, width=width, height=height - 40, margin=32)
    _text(
        draw,
        (8, 10),
        f"FRCSD pass capability audit junction={result_frcsd.junction_id} generated={final_result.metrics.get('frcsd_generated_road_next_road_count', 0)}",
        font=font,
    )
    arm_colors = _draw_final_arm_near_roads(
        draw,
        loaded_frcsd,
        result_frcsd,
        project=project,
        bounds=bounds,
        width=12,
        label=True,
        font=font,
    )
    center = _junction_center(loaded_frcsd, result_frcsd)
    if _point_in_bounds(center, bounds):
        _draw_point(draw, center, project, fill=(0, 0, 0, 255), radius=5)

    drawable_items: list[dict[str, Any]] = []
    overlap_groups: dict[tuple[tuple[int, int], tuple[int, int]], list[int]] = {}
    for item in final_result.audit:
        if item.permission_status != "allowed" or item.movement_type == "uturn":
            continue
        from_point = _road_junction_endpoint(loaded_frcsd, item.f_road_id, center)
        to_point = _road_junction_endpoint(loaded_frcsd, item.f_next_road_id, center)
        if from_point is None or to_point is None:
            continue
        if not (_point_in_bounds(from_point, bounds) and _point_in_bounds(to_point, bounds)):
            continue
        start = project(float(from_point.x), float(from_point.y))
        end = project(float(to_point.x), float(to_point.y))
        color = arm_colors.get(item.from_arm_id, TURN_COLORS.get(item.movement_type, TURN_COLORS["unknown"]))
        index = len(drawable_items)
        drawable_items.append(
            {
                "start": start,
                "end": end,
                "color": color,
                "movement_type": item.movement_type,
            }
        )
        overlap_groups.setdefault(_segment_overlap_key(start, end), []).append(index)

    parallel_count = sum(max(0, len(indexes) - 1) for indexes in overlap_groups.values())
    same_endpoint_count = 0
    for indexes in overlap_groups.values():
        group_size = len(indexes)
        for position, item_index in enumerate(indexes):
            item = drawable_items[item_index]
            if math.hypot(item["end"][0] - item["start"][0], item["end"][1] - item["start"][1]) < 8:
                _draw_same_endpoint_marker(
                    draw,
                    item["start"],
                    fill=item["color"],
                    index=position,
                    total=group_size,
                    dashed=item["movement_type"] == "unknown",
                    label="?" if item["movement_type"] == "unknown" else None,
                )
                same_endpoint_count += 1
                continue
            offset = 0.0 if group_size == 1 else (position - (group_size - 1) / 2) * 7.0
            start, end = _offset_segment(item["start"], item["end"], offset_px=offset)
            _draw_arrow(
                draw,
                start,
                end,
                fill=item["color"],
                width=2,
                dashed=item["movement_type"] == "unknown",
                label="?" if item["movement_type"] == "unknown" else None,
            )
    if same_endpoint_count:
        _text(draw, (8, 26), f"same-endpoint pass markers={same_endpoint_count}; parallel={parallel_count}", font=font)
    image.convert("RGB").save(path)


def render_compare_png(
    path: Path,
    loaded_by_dataset: dict[str, LoadedDataset],
    result_by_dataset: dict[str, DatasetBuildResult],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    panel_w, height = 520, 600
    image = Image.new("RGBA", (panel_w * 3, height), (250, 250, 248, 255))
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    contexts: dict[str, tuple[list[BaseGeometry], set[str], set[str]]] = {}
    geometries: list[BaseGeometry] = []
    for dataset in ("SWSD", "RCSD", "FRCSD"):
        contexts[dataset] = _dataset_review_context(loaded_by_dataset[dataset], result_by_dataset[dataset])
        geometries.extend(contexts[dataset][0])
    bounds = _geometry_bounds(geometries)
    for idx, dataset in enumerate(("SWSD", "RCSD", "FRCSD")):
        loaded = loaded_by_dataset[dataset]
        result = result_by_dataset[dataset]
        metrics = result.metrics
        title = (
            f"{dataset} arms={metrics['initial_arm_count']} stable={metrics['stable_arm_count']} "
            f"partial={metrics['partial_arm_count']} issue={metrics['issue_count']} "
            f"R7={metrics['advance_right_turn_road_count']} L8={metrics['advance_left_turn_road_count']}"
        )
        _draw_dataset_panel(
            draw,
            loaded,
            result,
            bounds=bounds,
            road_ids=contexts[dataset][1],
            node_ids=contexts[dataset][2],
            panel=(idx * panel_w, 0, panel_w, height),
            title=title,
            font=font,
        )
    image.convert("RGB").save(path)


def _dataset_review_context(
    loaded: LoadedDataset,
    result: DatasetBuildResult,
) -> tuple[list[BaseGeometry], set[str], set[str]]:
    context_node_ids = set(result.context.member_node_ids)
    context_road_ids = set(result.context.internal_road_ids)
    context_road_ids.update(result.context.excluded_right_turn_road_ids)
    context_road_ids.update(result.context.advance_left_turn_road_ids)
    context_road_ids.update(result.context.advance_right_turn_road_ids)
    for arm in result.initial_arms:
        context_road_ids.update(arm.trunk_road_ids)
    for relation in result.advance_right_turn_relations:
        context_road_ids.update(relation.trace_road_ids)
        context_node_ids.update(relation.trace_node_ids[:2])
    for evidence in result.road_movement_evidence:
        context_road_ids.add(evidence.road_id)
        context_road_ids.add(evidence.next_road_id)
    for correction in result.trunk_corrections:
        context_road_ids.update(correction.corrected_trunk_road_ids)
        context_road_ids.update(correction.movement_excluded_receiving_road_ids)
    for validation in result.final_arm_validation:
        for road_ids in validation.relaxed_trace_road_ids_by_initial_arm.values():
            context_road_ids.update(road_ids)
        for node_ids in validation.relaxed_trace_node_ids_by_initial_arm.values():
            context_node_ids.update(node_ids[-1:])

    seed_road_ids = {trace.seed_road_id for trace in result.traces}
    context_road_ids.update(seed_road_ids)
    for candidate in result.local_arm_candidates:
        context_road_ids.update(candidate.local_stub_road_ids)

    for trace in result.traces:
        context_node_ids.update(trace.traced_node_ids[:1])

    first_decisions: dict[str, Any] = {}
    for decision in result.decisions:
        first_decisions.setdefault(decision.trace_id, decision)
    for decision in first_decisions.values():
        context_node_ids.update(decision.member_node_ids)
        context_road_ids.update(decision.incident_road_ids)

    geometries: list[BaseGeometry] = []
    for road_id in sorted(context_road_ids):
        road = loaded.roads.get(road_id)
        if road:
            geometries.append(road.geometry)
            context_node_ids.add(road.snodeid)
            context_node_ids.add(road.enodeid)
    for node_id in sorted(context_node_ids):
        node = loaded.nodes.get(node_id)
        if node:
            geometries.append(node.geometry)
    return geometries, context_road_ids, context_node_ids


def build_dataset_review_layers(
    loaded: LoadedDataset,
    result: DatasetBuildResult,
) -> list[tuple[str, str, list[tuple[BaseGeometry, dict[str, Any]]]]]:
    member_nodes = [
        (loaded.nodes[node_id].geometry, {"node_id": node_id, "dataset": result.dataset})
        for node_id in result.context.member_node_ids
        if node_id in loaded.nodes
    ]
    internal_roads = [
        (loaded.roads[road_id].geometry, {"road_id": road_id, "dataset": result.dataset})
        for road_id in result.context.internal_road_ids
        if road_id in loaded.roads
    ]
    arm_roads = []
    for arm in result.initial_arms:
        for road_id in arm.member_road_ids:
            road = loaded.roads.get(road_id)
            if road:
                arm_roads.append((road.geometry, {"road_id": road_id, "arm_id": arm.initial_arm_id, "terminal_type": arm.terminal_type}))
    arm_trunk_roads = []
    for arm in result.initial_arms:
        for road_id in arm.trunk_road_ids:
            road = loaded.roads.get(road_id)
            if road:
                arm_trunk_roads.append(
                    (
                        road.geometry,
                        {
                            "dataset": result.dataset,
                            "junction_id": result.junction_id,
                            "arm_id": arm.initial_arm_id,
                            "road_id": road_id,
                            "trunk_status": arm.trunk_status,
                        },
                    )
                )
    local_candidate_roads = []
    for candidate in result.local_arm_candidates:
        for road_id in candidate.local_stub_road_ids:
            road = loaded.roads.get(road_id)
            if road:
                local_candidate_roads.append(
                    (
                        road.geometry,
                        {
                            "road_id": road_id,
                            "candidate_id": candidate.local_arm_candidate_id,
                            "source_seeds": ",".join(candidate.source_seed_road_ids),
                            "status": candidate.build_status,
                        },
                    )
                )
    arm_corridor_support_roads = []
    for evidence in result.arm_corridor_evidence:
        for road_id in evidence.support_road_ids:
            road = loaded.roads.get(road_id)
            if road:
                arm_corridor_support_roads.append(
                    (
                        road.geometry,
                        {
                            "dataset": result.dataset,
                            "junction_id": result.junction_id,
                            "final_arm_id": evidence.final_arm_id,
                            "road_id": road_id,
                            "corridor_status": evidence.corridor_status,
                            "corridor_angle_deg": evidence.corridor_angle_deg,
                            "terminal_junction_id": evidence.corridor_terminal_junction_id or "",
                            "risk_flags": ",".join(evidence.risk_flags),
                        },
                    )
                )
    traces = []
    for trace in result.traces:
        for road_id in trace.traced_road_ids:
            road = loaded.roads.get(road_id)
            if road:
                traces.append((road.geometry, {"trace_id": trace.trace_id, "road_id": road_id, "stop_type": trace.stop_type}))
    terminal_nodes = []
    for arm in result.initial_arms:
        for node_id in arm.terminal_member_node_ids:
            node = loaded.nodes.get(node_id)
            if node:
                terminal_nodes.append((node.geometry, {"arm_id": arm.initial_arm_id, "node_id": node_id, "terminal_type": arm.terminal_type}))
    decision_nodes = []
    for decision in result.decisions:
        for node_id in decision.member_node_ids[:1]:
            node = loaded.nodes.get(node_id)
            if node:
                decision_nodes.append((node.geometry, {"trace_id": decision.trace_id, "status": decision.status, "node_group_id": decision.node_group_id}))
    excluded_roads = [
        (loaded.roads[road_id].geometry, {"road_id": road_id, "dataset": result.dataset, "reason": "right_turn"})
        for road_id in result.context.excluded_right_turn_road_ids
        if road_id in loaded.roads
    ]
    road_to_arm = {road_id: arm.initial_arm_id for arm in result.initial_arms for road_id in arm.member_road_ids}
    advance_left_roads = [
        (
            loaded.roads[road_id].geometry,
            {
                "dataset": result.dataset,
                "junction_id": result.junction_id,
                "road_id": road_id,
                "arm_id": road_to_arm.get(road_id, ""),
                "formway": loaded.roads[road_id].formway,
                "in_trunk": road_id in {item for arm in result.initial_arms for item in arm.trunk_road_ids},
            },
        )
        for road_id in result.context.advance_left_turn_road_ids
        if road_id in loaded.roads
    ]
    relation_by_road = {
        road_id: relation
        for relation in result.advance_right_turn_relations
        for road_id in relation.advance_right_turn_road_ids
    }
    advance_right_roads = [
        (
            loaded.roads[road_id].geometry,
            {
                "dataset": result.dataset,
                "junction_id": result.junction_id,
                "road_id": road_id,
                "formway": loaded.roads[road_id].formway,
                "relation_id": relation_by_road[road_id].relation_id if road_id in relation_by_road else "",
                "trace_status": relation_by_road[road_id].trace_status if road_id in relation_by_road else "target_arm_not_found",
            },
        )
        for road_id in result.context.advance_right_turn_road_ids
        if road_id in loaded.roads
    ]
    advance_right_relations = []
    for relation in result.advance_right_turn_relations:
        for road_id in relation.trace_road_ids:
            road = loaded.roads.get(road_id)
            if road:
                advance_right_relations.append(
                    (
                        road.geometry,
                        {
                            "relation_id": relation.relation_id,
                            "from_arm_id": relation.from_arm_id or "",
                            "to_arm_id": relation.to_arm_id or "",
                            "trace_status": relation.trace_status,
                            "confidence": relation.confidence,
                        },
                    )
                )
    arm_anchor: dict[str, Point] = {}
    for arm in result.final_arms:
        road_ids = list(arm.trunk_road_ids) or list(arm.initial_arm.get("seed_road_ids", []))
        points = [loaded.roads[road_id].geometry.centroid for road_id in road_ids if road_id in loaded.roads]
        if points:
            arm_anchor[arm.final_arm_id] = Point(
                sum(point.x for point in points) / len(points),
                sum(point.y for point in points) / len(points),
            )
    arm_movements = []
    for movement in result.arm_movements:
        from_point = arm_anchor.get(movement.from_arm_id)
        to_point = arm_anchor.get(movement.to_arm_id)
        if from_point and to_point:
            arm_movements.append(
                (
                    LineString([from_point, to_point]),
                    {
                        "movement_id": movement.movement_id,
                        "from_arm_id": movement.from_arm_id,
                        "to_arm_id": movement.to_arm_id,
                        "movement_type": movement.movement_type,
                        "permission": movement.permission_evidence_status,
                    },
                )
            )
    road_movement_evidence = []
    for evidence in result.road_movement_evidence:
        from_road = loaded.roads.get(evidence.road_id)
        to_road = loaded.roads.get(evidence.next_road_id)
        from_point = from_road.geometry.centroid if from_road else None
        to_point = to_road.geometry.centroid if to_road else None
        if from_point and to_point:
            road_movement_evidence.append(
                (
                    LineString([from_point, to_point]),
                    {
                        "evidence_id": evidence.evidence_id,
                        "from_arm_id": evidence.from_arm_id or "",
                        "to_arm_id": evidence.to_arm_id or "",
                        "mapping_status": evidence.mapping_status,
                    },
                )
            )
    straight_receiving_roads = []
    advance_left_receiving_roads = []
    for role in result.arm_receiving_road_roles:
        road = loaded.roads.get(role.road_id)
        if not road:
            continue
        record = (
            road.geometry,
            {
                "target_arm": role.target_arm_id,
                "road_id": role.road_id,
                "roles": ",".join(role.receiving_roles),
                "exclude": role.exclude_from_trunk,
                "reason": role.exclude_reason,
            },
        )
        if role.straight_evidence_count > 0:
            straight_receiving_roads.append(record)
        if role.advance_left_evidence_count > 0:
            advance_left_receiving_roads.append(record)
    trunk_excluded_by_movement_roads = [
        (
            loaded.roads[road_id].geometry,
            {
                "target_arm": correction.arm_id,
                "road_id": road_id,
                "reason": "advance_left_receiving_only_not_straight_receiving",
            },
        )
        for correction in result.trunk_corrections
        for road_id in correction.movement_excluded_receiving_road_ids
        if road_id in loaded.roads
    ]
    corrected_trunk_roads = [
        (
            loaded.roads[road_id].geometry,
            {
                "arm_id": correction.arm_id,
                "road_id": road_id,
                "status": correction.trunk_correction_status,
                "reason": correction.trunk_correction_reason,
            },
        )
        for correction in result.trunk_corrections
        for road_id in correction.corrected_trunk_road_ids
        if road_id in loaded.roads
    ]
    fallback_point = None
    if result.context.member_node_ids:
        node = loaded.nodes.get(result.context.member_node_ids[0])
        fallback_point = node.geometry if node else None
    final_arm_validation = []
    relaxed_trace_roads = []
    relaxed_trace_terminals = []
    for validation in result.final_arm_validation:
        anchor_point = None
        arm = next((item for item in result.final_arms if item.final_arm_id == validation.final_arm_id), None)
        if arm:
            anchor_ids = list(arm.trunk_road_ids) or list(arm.initial_arm.get("seed_road_ids", []))
            anchor_points = [loaded.roads[road_id].geometry.centroid for road_id in anchor_ids if road_id in loaded.roads]
            if anchor_points:
                anchor_point = Point(
                    sum(point.x for point in anchor_points) / len(anchor_points),
                    sum(point.y for point in anchor_points) / len(anchor_points),
                )
        if anchor_point is None:
            anchor_point = fallback_point or Point(0.0, 0.0)
        final_arm_validation.append(
            (
                anchor_point,
                {
                    "validation_id": validation.validation_id,
                    "final_arm_id": validation.final_arm_id,
                    "validation_status": validation.validation_status,
                    "convergence_status": validation.convergence_status,
                    "source_initial_arm_ids": ",".join(validation.source_initial_arm_ids),
                    "terminal_ids": ",".join(validation.relaxed_trace_terminal_junction_ids),
                    "risk_flags": ",".join(validation.risk_flags),
                },
            )
        )
        for initial_id, road_ids in validation.relaxed_trace_road_ids_by_initial_arm.items():
            for road_id in road_ids:
                road = loaded.roads.get(road_id)
                if road:
                    relaxed_trace_roads.append(
                        (
                            road.geometry,
                            {
                                "validation_id": validation.validation_id,
                                "final_arm_id": validation.final_arm_id,
                                "initial_arm_id": initial_id,
                                "validation_status": validation.validation_status,
                                "road_id": road_id,
                            },
                        )
                    )
        for initial_id, node_ids in validation.relaxed_trace_node_ids_by_initial_arm.items():
            terminal_node_id = node_ids[-1] if node_ids else ""
            node = loaded.nodes.get(terminal_node_id)
            if node:
                relaxed_trace_terminals.append(
                    (
                        node.geometry,
                        {
                            "validation_id": validation.validation_id,
                            "final_arm_id": validation.final_arm_id,
                            "initial_arm_id": initial_id,
                            "validation_status": validation.validation_status,
                            "terminal_node_id": terminal_node_id,
                        },
                    )
                )
    issue_points = []
    special_issue_points = []
    for issue in result.issue_report.issues:
        point = fallback_point
        node_id = issue.get("node_id") or issue.get("missing_node_id")
        if node_id and node_id in loaded.nodes:
            point = loaded.nodes[node_id].geometry
        road_id = issue.get("road_id")
        if road_id and road_id in loaded.roads:
            point = loaded.roads[road_id].geometry.centroid
        if point is None:
            point = Point(0.0, 0.0)
        issue_points.append((point, {"issue_type": issue.get("issue_type", ""), "detail": str(issue)[:180]}))
        if str(issue.get("issue_type", "")).startswith(("formway_", "advance_right_turn_", "trunk_", "final_arm_validation_", "relaxed_trace_")):
            special_issue_points.append((point, {"issue_type": issue.get("issue_type", ""), "detail": str(issue)[:180]}))
    return [
        ("current_junction_nodes", "Point", member_nodes),
        ("current_junction_internal_roads", "LineString", internal_roads),
        ("arm_roads", "LineString", arm_roads),
        ("arm_trunk_roads", "LineString", arm_trunk_roads),
        ("local_arm_candidate_roads", "LineString", local_candidate_roads),
        ("arm_corridor_support_roads", "LineString", arm_corridor_support_roads),
        ("arm_traces", "LineString", traces),
        ("terminal_nodes", "Point", terminal_nodes),
        ("through_decision_nodes", "Point", decision_nodes),
        ("excluded_right_turn_roads", "LineString", excluded_roads),
        ("advance_left_turn_roads", "LineString", advance_left_roads),
        ("advance_right_turn_roads", "LineString", advance_right_roads),
        ("advance_right_turn_relations", "LineString", advance_right_relations),
        ("arm_movements", "LineString", arm_movements),
        ("road_movement_evidence", "LineString", road_movement_evidence),
        ("straight_receiving_roads", "LineString", straight_receiving_roads),
        ("advance_left_receiving_roads", "LineString", advance_left_receiving_roads),
        ("trunk_excluded_by_movement_roads", "LineString", trunk_excluded_by_movement_roads),
        ("corrected_trunk_roads", "LineString", corrected_trunk_roads),
        ("final_arm_validation", "Point", final_arm_validation),
        ("relaxed_trace_roads", "LineString", relaxed_trace_roads),
        ("relaxed_trace_terminals", "Point", relaxed_trace_terminals),
        ("special_formway_issue_points", "Point", special_issue_points),
        ("issue_points", "Point", issue_points),
    ]


def build_compare_layers(
    loaded_by_dataset: dict[str, LoadedDataset],
    result_by_dataset: dict[str, DatasetBuildResult],
) -> list[tuple[str, str, list[tuple[BaseGeometry, dict[str, Any]]]]]:
    records: list[tuple[BaseGeometry, dict[str, Any]]] = []
    corridor_records: list[tuple[BaseGeometry, dict[str, Any]]] = []
    for dataset, result in result_by_dataset.items():
        loaded = loaded_by_dataset[dataset]
        for arm in result.initial_arms:
            for road_id in arm.member_road_ids:
                road = loaded.roads.get(road_id)
                if road:
                    records.append((road.geometry, {"dataset": dataset, "arm_id": arm.initial_arm_id, "road_id": road_id, "status": arm.build_status}))
        for evidence in result.arm_corridor_evidence:
            for road_id in evidence.support_road_ids:
                road = loaded.roads.get(road_id)
                if road:
                    corridor_records.append(
                        (
                            road.geometry,
                            {
                                "dataset": dataset,
                                "final_arm_id": evidence.final_arm_id,
                                "road_id": road_id,
                                "corridor_status": evidence.corridor_status,
                            },
                        )
                    )
    return [("compare_arm_roads", "LineString", records), ("compare_arm_corridor_support_roads", "LineString", corridor_records)]
