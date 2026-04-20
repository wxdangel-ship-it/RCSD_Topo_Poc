from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import GeometryCollection, MultiLineString, MultiPoint, MultiPolygon, Point
from shapely.geometry.base import BaseGeometry

from .case_models import T04CaseResult, T04EventUnitResult


CANVAS_WIDTH = 1400
CANVAS_HEIGHT = 1000
MAP_LEFT = 20
MAP_TOP = 20
MAP_SIZE = 960
PANEL_LEFT = 1020
PANEL_TOP = 20
BACKGROUND = (250, 248, 242, 255)
DRIVEZONE_FILL = (236, 223, 194, 255)
DRIVEZONE_EDGE = (193, 170, 123, 255)
DIVSTRIP_FILL = (194, 204, 212, 105)
DIVSTRIP_SELECTED = (29, 78, 137, 188)
ROAD_COLOR = (42, 42, 42, 255)
MAIN_ROAD_COLOR = (0, 0, 0, 255)
EVENT_ROAD_COLOR = (32, 103, 170, 255)
RCSD_ROAD_COLOR = (175, 33, 61, 255)
ANCHOR_COLOR = (0, 143, 122, 255)
REFERENCE_COLOR = (214, 45, 32, 255)
NODE_COLOR = (48, 48, 48, 255)
GROUP_NODE_COLOR = (0, 0, 0, 255)
REP_RING_COLOR = (255, 255, 255, 255)

STATE_STYLE = {
    "STEP4_OK": {"banner": (38, 122, 72, 240), "label": "STEP4_OK"},
    "STEP4_REVIEW": {"banner": (185, 122, 17, 240), "label": "STEP4_REVIEW"},
    "STEP4_FAIL": {"banner": (170, 38, 38, 240), "label": "STEP4_FAIL"},
}


def _font(size: int):
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def _iter_geometries(geometry: BaseGeometry | None) -> Iterable[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, (GeometryCollection, MultiPolygon, MultiLineString, MultiPoint)):
        for child in geometry.geoms:
            yield from _iter_geometries(child)
        return
    yield geometry


def _iter_polygons(geometry: BaseGeometry | None) -> Iterable[BaseGeometry]:
    for item in _iter_geometries(geometry):
        if item.geom_type == "Polygon":
            yield item


def _iter_lines(geometry: BaseGeometry | None) -> Iterable[BaseGeometry]:
    for item in _iter_geometries(geometry):
        if item.geom_type == "LineString":
            yield item


def _iter_points(geometry: BaseGeometry | None) -> Iterable[Point]:
    for item in _iter_geometries(geometry):
        if item.geom_type == "Point":
            yield item


def _project(bounds, x: float, y: float) -> tuple[float, float]:
    minx, miny, maxx, maxy = bounds
    width = max(1.0, maxx - minx)
    height = max(1.0, maxy - miny)
    px = MAP_LEFT + ((x - minx) / width) * (MAP_SIZE - 1)
    py = MAP_TOP + (1.0 - (y - miny) / height) * (MAP_SIZE - 1)
    return px, py


def _coord_xy(coord) -> tuple[float, float]:
    return float(coord[0]), float(coord[1])


def _draw_polygon(draw, geometry, bounds, *, fill, outline=None, width=1):
    for polygon in _iter_polygons(geometry):
        coords = [_project(bounds, *_coord_xy(coord)) for coord in polygon.exterior.coords]
        draw.polygon(coords, fill=fill, outline=outline)
        if outline is not None and width > 1:
            draw.line(coords, fill=outline, width=width, joint="curve")


def _draw_line(draw, geometry, bounds, *, fill, width):
    for line in _iter_lines(geometry):
        points = [_project(bounds, *_coord_xy(coord)) for coord in line.coords]
        if len(points) >= 2:
            draw.line(points, fill=fill, width=width, joint="curve")


def _draw_point(draw, geometry, bounds, *, fill, radius, ring=None):
    for point in _iter_points(geometry):
        px, py = _project(bounds, float(point.x), float(point.y))
        if ring is not None:
            draw.ellipse((px - radius - 3, py - radius - 3, px + radius + 3, py + radius + 3), fill=ring)
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)


def _draw_panel(draw, *, state: str, title: str, lines: list[str]):
    style = STATE_STYLE[state]
    draw.rounded_rectangle((PANEL_LEFT, PANEL_TOP, CANVAS_WIDTH - 20, CANVAS_HEIGHT - 20), radius=18, fill=(255, 255, 255, 235), outline=(220, 214, 203, 255), width=2)
    draw.rounded_rectangle((PANEL_LEFT + 16, PANEL_TOP + 16, CANVAS_WIDTH - 36, PANEL_TOP + 86), radius=16, fill=style["banner"])
    draw.text((PANEL_LEFT + 32, PANEL_TOP + 30), style["label"], font=_font(28), fill=(255, 255, 255, 255))
    draw.text((PANEL_LEFT + 32, PANEL_TOP + 100), title, font=_font(24), fill=(28, 28, 28, 255))
    cursor_y = PANEL_TOP + 150
    for line in lines:
        draw.text((PANEL_LEFT + 28, cursor_y), line, font=_font(18), fill=(52, 52, 52, 255))
        cursor_y += 30


def _base_bounds(unit: T04EventUnitResult):
    patch_polygon = unit.unit_context.local_context.grid.patch_polygon
    minx, miny, maxx, maxy = patch_polygon.bounds
    return float(minx), float(miny), float(maxx), float(maxy)


def render_event_unit_review_png(out_path: Path, event_unit: T04EventUnitResult) -> None:
    image = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image, "RGBA")
    bounds = _base_bounds(event_unit)
    local_context = event_unit.unit_context.local_context
    road_lookup = {road.road_id: road for road in local_context.patch_roads}

    _draw_polygon(draw, local_context.patch_drivezone_union, bounds, fill=DRIVEZONE_FILL, outline=DRIVEZONE_EDGE, width=2)
    _draw_polygon(draw, local_context.patch_divstrip_union, bounds, fill=DIVSTRIP_FILL, outline=None)
    _draw_polygon(draw, event_unit.selected_divstrip_geometry, bounds, fill=DIVSTRIP_SELECTED, outline=(16, 52, 103, 255), width=3)

    for road in local_context.patch_roads:
        _draw_line(draw, road.geometry, bounds, fill=ROAD_COLOR, width=3)
    for branch_id in event_unit.selected_branch_ids:
        branch = event_unit.unit_context.topology_skeleton.branch_result.road_branches_by_id.get(branch_id)
        if branch is None:
            continue
        color = MAIN_ROAD_COLOR if branch_id in event_unit.unit_context.topology_skeleton.branch_result.main_branch_ids else EVENT_ROAD_COLOR
        for road_id in branch.road_ids:
            road = road_lookup.get(road_id)
            if road is not None:
                _draw_line(draw, road.geometry, bounds, fill=color, width=7 if color == MAIN_ROAD_COLOR else 6)
    _draw_line(draw, event_unit.positive_rcsd_geometry, bounds, fill=RCSD_ROAD_COLOR, width=5)
    _draw_polygon(draw, event_unit.event_anchor_geometry, bounds, fill=(0, 0, 0, 0), outline=ANCHOR_COLOR, width=4)
    _draw_point(draw, event_unit.event_reference_point, bounds, fill=REFERENCE_COLOR, radius=7, ring=(255, 255, 255, 255))
    for node in local_context.local_nodes:
        _draw_point(draw, node.geometry, bounds, fill=NODE_COLOR, radius=3)
    for node in event_unit.unit_context.group_nodes:
        _draw_point(draw, node.geometry, bounds, fill=GROUP_NODE_COLOR, radius=5)
    _draw_point(draw, event_unit.unit_context.representative_node.geometry, bounds, fill=GROUP_NODE_COLOR, radius=6, ring=REP_RING_COLOR)

    lines = [
        f"case_id: {event_unit.unit_context.admission.mainnodeid}",
        f"event_unit_id: {event_unit.spec.event_unit_id}",
        f"event_type: {event_unit.spec.event_type}",
        f"evidence_source: {event_unit.evidence_source}",
        f"position_source: {event_unit.position_source}",
        f"reverse_tip_used: {event_unit.reverse_tip_used}",
        f"rcsd_consistency: {event_unit.rcsd_consistency_result}",
    ]
    if event_unit.all_review_reasons():
        lines.append(f"reasons: {', '.join(event_unit.all_review_reasons())}")
    _draw_panel(
        draw,
        state=event_unit.review_state,
        title="Step4 Event Unit Review",
        lines=lines,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)


def render_case_overview_png(out_path: Path, case_result: T04CaseResult) -> None:
    image = Image.new("RGBA", (CANVAS_WIDTH, CANVAS_HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(image, "RGBA")
    bounds = _base_bounds(case_result.event_units[0])
    local_context = case_result.base_context.local_context
    road_lookup = {road.road_id: road for road in local_context.patch_roads}

    _draw_polygon(draw, local_context.patch_drivezone_union, bounds, fill=DRIVEZONE_FILL, outline=DRIVEZONE_EDGE, width=2)
    _draw_polygon(draw, local_context.patch_divstrip_union, bounds, fill=DIVSTRIP_FILL, outline=None)
    for road in local_context.patch_roads:
        _draw_line(draw, road.geometry, bounds, fill=ROAD_COLOR, width=3)
    for node in local_context.local_nodes:
        _draw_point(draw, node.geometry, bounds, fill=NODE_COLOR, radius=3)
    for branch_id in case_result.base_context.topology_skeleton.branch_result.main_branch_ids:
        branch = case_result.base_context.topology_skeleton.branch_result.road_branches_by_id.get(branch_id)
        if branch is None:
            continue
        for road_id in branch.road_ids:
            road = road_lookup.get(road_id)
            if road is not None:
                _draw_line(draw, road.geometry, bounds, fill=MAIN_ROAD_COLOR, width=7)

    overview_lines = [
        f"case_id: {case_result.case_spec.case_id}",
        f"mainnodeid: {case_result.case_spec.mainnodeid}",
        f"event_unit_count: {len(case_result.event_units)}",
    ]
    for index, event_unit in enumerate(case_result.event_units, start=1):
        color = STATE_STYLE[event_unit.review_state]["banner"]
        _draw_polygon(draw, event_unit.selected_divstrip_geometry, bounds, fill=(color[0], color[1], color[2], 72), outline=color, width=2)
        _draw_point(draw, event_unit.event_reference_point, bounds, fill=color, radius=6, ring=(255, 255, 255, 255))
        if event_unit.event_reference_point is not None and not event_unit.event_reference_point.is_empty:
            point = next(_iter_points(event_unit.event_reference_point), None)
            if point is not None:
                px, py = _project(bounds, float(point.x), float(point.y))
                draw.text((px + 8, py - 10), str(index), font=_font(18), fill=(24, 24, 24, 255))
        overview_lines.append(f"{index}. {event_unit.spec.event_unit_id} / {event_unit.spec.event_type} / {event_unit.review_state}")

    _draw_panel(
        draw,
        state=case_result.case_review_state,
        title="Step4 Case Overview",
        lines=overview_lines[:20],
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
