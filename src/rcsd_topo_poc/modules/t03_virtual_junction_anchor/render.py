from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw
from shapely.geometry import MultiLineString, MultiPoint, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.models import Step1Context, Step3CaseResult


IMAGE_SIZE = 1024
BACKGROUND_COLOR = (255, 255, 255, 255)
DRIVEZONE_FILL = (229, 220, 192, 255)
DRIVEZONE_EDGE = (190, 176, 132, 255)
ALLOWED_FILL = (255, 140, 0, 170)
NEGATIVE_FILL = (138, 28, 42, 160)
ROAD_COLOR = (24, 24, 24, 255)
RC_ROAD_COLOR = (193, 18, 31, 255)
GROUP_NODE_COLOR = (0, 0, 0, 255)
FOREIGN_NODE_COLOR = (80, 80, 80, 255)


STATUS_STYLE = {
    "established": {
        "banner": (33, 33, 33, 220),
        "text": (255, 255, 255, 255),
        "border": None,
        "label": "ESTABLISHED",
    },
    "review": {
        "banner": (176, 96, 0, 235),
        "text": (255, 245, 220, 255),
        "border": (176, 96, 0, 255),
        "label": "REVIEW",
    },
    "not_established": {
        "banner": (164, 0, 0, 235),
        "text": (255, 238, 238, 255),
        "border": (164, 0, 0, 255),
        "label": "NOT ESTABLISHED",
    },
}


def _xy_pair(coord: tuple[float, ...]) -> tuple[float, float]:
    return float(coord[0]), float(coord[1])


def _flatten_bounds(geometries: Iterable[BaseGeometry]) -> tuple[float, float, float, float]:
    merged = unary_union([geometry for geometry in geometries if geometry is not None and not geometry.is_empty])
    minx, miny, maxx, maxy = merged.bounds
    pad_x = max(20.0, (maxx - minx) * 0.08)
    pad_y = max(20.0, (maxy - miny) * 0.08)
    return minx - pad_x, miny - pad_y, maxx + pad_x, maxy + pad_y


def _project_xy(x: float, y: float, bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    minx, miny, maxx, maxy = bounds
    width = max(1.0, maxx - minx)
    height = max(1.0, maxy - miny)
    px = ((x - minx) / width) * (IMAGE_SIZE - 1)
    py = (1.0 - (y - miny) / height) * (IMAGE_SIZE - 1)
    return px, py


def _draw_polygon(draw: ImageDraw.ImageDraw, geometry: BaseGeometry, bounds: tuple[float, float, float, float], fill: tuple[int, int, int, int], outline: tuple[int, int, int, int] | None = None, width: int = 1) -> None:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, MultiPolygon):
        for item in geometry.geoms:
            _draw_polygon(draw, item, bounds, fill=fill, outline=outline, width=width)
        return
    if geometry.geom_type != "Polygon":
        return
    exterior = [_project_xy(x, y, bounds) for x, y in map(_xy_pair, geometry.exterior.coords)]
    draw.polygon(exterior, fill=fill, outline=outline)
    if outline is not None and width > 1:
        draw.line(exterior, fill=outline, width=width, joint="curve")


def _draw_line(draw: ImageDraw.ImageDraw, geometry: BaseGeometry, bounds: tuple[float, float, float, float], fill: tuple[int, int, int, int], width: int) -> None:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, MultiLineString):
        for item in geometry.geoms:
            _draw_line(draw, item, bounds, fill=fill, width=width)
        return
    if geometry.geom_type != "LineString":
        return
    points = [_project_xy(x, y, bounds) for x, y in map(_xy_pair, geometry.coords)]
    if len(points) >= 2:
        draw.line(points, fill=fill, width=width, joint="curve")


def _draw_point(draw: ImageDraw.ImageDraw, geometry: BaseGeometry, bounds: tuple[float, float, float, float], fill: tuple[int, int, int, int], radius: int) -> None:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, MultiPoint):
        for item in geometry.geoms:
            _draw_point(draw, item, bounds, fill=fill, radius=radius)
        return
    if geometry.geom_type != "Point":
        return
    px, py = _project_xy(geometry.x, geometry.y, bounds)
    draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)


def _draw_status_banner(draw: ImageDraw.ImageDraw, step3_state: str, reason: str) -> None:
    style = STATUS_STYLE[step3_state]
    if style["border"] is not None:
        draw.rectangle((0, 0, IMAGE_SIZE - 1, IMAGE_SIZE - 1), outline=style["border"], width=8)
    draw.rectangle((0, 0, IMAGE_SIZE - 1, 74), fill=style["banner"])
    draw.text((18, 18), style["label"], fill=style["text"])
    draw.text((18, 46), reason[:72], fill=style["text"])


def render_step3_review_png(
    *,
    out_path: Path,
    context: Step1Context,
    case_result: Step3CaseResult,
) -> None:
    draw_geometries = [
        context.drivezone_geometry,
        case_result.allowed_space_geometry or context.representative_node.geometry.buffer(8.0),
        *[road.geometry for road in context.roads],
        *[road.geometry for road in context.rcsd_roads],
        *[node.geometry for node in context.all_nodes],
    ]
    bounds = _flatten_bounds(draw_geometries)
    image = Image.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image, "RGBA")
    _draw_polygon(draw, context.drivezone_geometry, bounds, fill=DRIVEZONE_FILL, outline=DRIVEZONE_EDGE, width=2)
    for geometry in (
        case_result.negative_masks.adjacent_junction_geometry,
        case_result.negative_masks.foreign_objects_geometry,
        case_result.negative_masks.foreign_mst_geometry,
    ):
        if geometry is None:
            continue
        _draw_polygon(draw, geometry, bounds, fill=NEGATIVE_FILL, outline=None)
    if case_result.allowed_space_geometry is not None:
        _draw_polygon(draw, case_result.allowed_space_geometry, bounds, fill=ALLOWED_FILL, outline=(255, 140, 0, 255), width=2)
    for road in context.roads:
        _draw_line(draw, road.geometry, bounds, fill=ROAD_COLOR, width=4)
    for road in context.rcsd_roads:
        _draw_line(draw, road.geometry, bounds, fill=RC_ROAD_COLOR, width=3)
    target_node_ids = {node.node_id for node in context.target_group.nodes}
    for node in context.all_nodes:
        _draw_point(
            draw,
            node.geometry,
            bounds,
            fill=GROUP_NODE_COLOR if node.node_id in target_node_ids else FOREIGN_NODE_COLOR,
            radius=7 if node.node_id == context.representative_node.node_id else 5,
        )
    _draw_status_banner(draw, case_result.step3_state, case_result.reason.replace("_", " "))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
