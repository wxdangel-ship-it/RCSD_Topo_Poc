from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PIL import Image, ImageDraw, ImageFont
from shapely.geometry import GeometryCollection, MultiLineString, MultiPoint, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.case_models import Step1Context, Step3CaseResult


IMAGE_SIZE = 1024
DEFAULT_PATCH_SIZE_M = 200.0
MAX_PATCH_SIZE_M = 240.0
BACKGROUND_COLOR = (255, 255, 255, 255)
DRIVEZONE_FILL = (229, 220, 192, 255)
DRIVEZONE_EDGE = (190, 176, 132, 255)
ALLOWED_FILL = (255, 140, 0, 188)
ALLOWED_EDGE = (214, 111, 0, 255)
NEGATIVE_FILL = (138, 28, 42, 170)
NEGATIVE_EDGE = (108, 18, 30, 255)
ROAD_COLOR = (24, 24, 24, 255)
RC_ROAD_COLOR = (193, 18, 31, 255)
GROUP_NODE_COLOR = (24, 24, 24, 255)
FOREIGN_NODE_COLOR = (90, 90, 90, 255)
REPRESENTATIVE_RING = (255, 255, 255, 255)


STATUS_STYLE = {
    "established": {
        "banner": (33, 33, 33, 235),
        "text": (255, 255, 255, 255),
        "text_shadow": (0, 0, 0, 255),
        "border": None,
        "tint": None,
        "focus": None,
        "hatch": None,
        "label": "ESTABLISHED / 已成立",
    },
    "review": {
        "banner": (176, 96, 0, 235),
        "text": (255, 252, 245, 255),
        "text_shadow": (92, 49, 0, 255),
        "border": (176, 96, 0, 255),
        "tint": (241, 172, 51, 56),
        "focus": (214, 132, 34, 64),
        "hatch": (145, 78, 0, 185),
        "label": "REVIEW / 待复核",
    },
    "not_established": {
        "banner": (164, 0, 0, 235),
        "text": (255, 244, 244, 255),
        "text_shadow": (72, 0, 0, 255),
        "border": (164, 0, 0, 255),
        "tint": (220, 32, 32, 56),
        "focus": (186, 0, 0, 64),
        "hatch": (124, 0, 0, 185),
        "label": "NOT ESTABLISHED / 未成立",
    },
}


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size=size)
    except OSError:
        return ImageFont.load_default()


def _xy_pair(coord: tuple[float, ...]) -> tuple[float, float]:
    return float(coord[0]), float(coord[1])


def _iter_geometries(geometry: BaseGeometry | None) -> Iterable[BaseGeometry]:
    if geometry is None or geometry.is_empty:
        return
    if isinstance(geometry, (GeometryCollection, MultiPolygon, MultiLineString, MultiPoint)):
        for item in geometry.geoms:
            yield from _iter_geometries(item)
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


def _iter_points(geometry: BaseGeometry | None) -> Iterable[BaseGeometry]:
    for item in _iter_geometries(geometry):
        if item.geom_type == "Point":
            yield item


def _build_patch_size(context: Step1Context, case_result: Step3CaseResult) -> float:
    reference = context.representative_node.geometry
    focus_geometries: list[BaseGeometry] = [
        reference.buffer(12.0),
        *[node.geometry.buffer(10.0) for node in context.target_group.nodes],
    ]
    if case_result.allowed_space_geometry is not None:
        focus_geometries.append(case_result.allowed_space_geometry)
    for geometry in (
        case_result.negative_masks.adjacent_junction_geometry,
        case_result.negative_masks.foreign_objects_geometry,
        case_result.negative_masks.foreign_mst_geometry,
    ):
        if geometry is not None and geometry.distance(reference) <= 80.0:
            focus_geometries.append(geometry)
    for road in context.roads:
        if road.geometry.distance(reference) <= 70.0:
            focus_geometries.append(road.geometry.buffer(2.0, cap_style=2, join_style=2))
    merged = unary_union(focus_geometries)
    minx, miny, maxx, maxy = merged.bounds
    span = max(maxx - minx, maxy - miny)
    return max(DEFAULT_PATCH_SIZE_M, min(MAX_PATCH_SIZE_M, span + 30.0))


def _patch_bounds(context: Step1Context, case_result: Step3CaseResult) -> tuple[float, float, float, float]:
    patch_size_m = _build_patch_size(context, case_result)
    center = context.representative_node.geometry
    half_size = patch_size_m / 2.0
    return center.x - half_size, center.y - half_size, center.x + half_size, center.y + half_size


def _px_per_m(bounds: tuple[float, float, float, float]) -> float:
    minx, _miny, maxx, _maxy = bounds
    return IMAGE_SIZE / max(1.0, maxx - minx)


def _project_xy(x: float, y: float, bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    minx, miny, maxx, maxy = bounds
    width = max(1.0, maxx - minx)
    height = max(1.0, maxy - miny)
    px = ((x - minx) / width) * (IMAGE_SIZE - 1)
    py = (1.0 - (y - miny) / height) * (IMAGE_SIZE - 1)
    return px, py


def _draw_polygon(
    draw: ImageDraw.ImageDraw,
    geometry: BaseGeometry | None,
    bounds: tuple[float, float, float, float],
    *,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int] | None = None,
    width: int = 1,
) -> None:
    for polygon in _iter_polygons(geometry):
        exterior = [_project_xy(x, y, bounds) for x, y in map(_xy_pair, polygon.exterior.coords)]
        draw.polygon(exterior, fill=fill, outline=outline)
        if outline is not None and width > 1:
            draw.line(exterior, fill=outline, width=width, joint="curve")


def _draw_line(
    draw: ImageDraw.ImageDraw,
    geometry: BaseGeometry | None,
    bounds: tuple[float, float, float, float],
    *,
    fill: tuple[int, int, int, int],
    width: int,
) -> None:
    for line in _iter_lines(geometry):
        points = [_project_xy(x, y, bounds) for x, y in map(_xy_pair, line.coords)]
        if len(points) >= 2:
            draw.line(points, fill=fill, width=width, joint="curve")


def _draw_point(
    draw: ImageDraw.ImageDraw,
    geometry: BaseGeometry | None,
    bounds: tuple[float, float, float, float],
    *,
    fill: tuple[int, int, int, int],
    radius: int,
    ring: tuple[int, int, int, int] | None = None,
    ring_width: int = 0,
) -> None:
    for point in _iter_points(geometry):
        px, py = _project_xy(point.x, point.y, bounds)
        if ring is not None and ring_width > 0:
            outer = radius + ring_width
            draw.ellipse((px - outer, py - outer, px + outer, py + outer), fill=ring)
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=fill)


def _draw_text_with_shadow(
    draw: ImageDraw.ImageDraw,
    *,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    shadow: tuple[int, int, int, int],
) -> None:
    x, y = xy
    draw.text((x + 2, y + 2), text, font=font, fill=shadow)
    draw.text((x, y), text, font=font, fill=fill)


def _build_focus_geometry(context: Step1Context, case_result: Step3CaseResult) -> BaseGeometry:
    focus_geometries: list[BaseGeometry] = [
        context.representative_node.geometry.buffer(12.0),
        *[node.geometry.buffer(10.0) for node in context.target_group.nodes],
    ]
    if case_result.allowed_space_geometry is not None:
        focus_geometries.append(case_result.allowed_space_geometry)
    return unary_union(focus_geometries)


def _draw_failure_overlay(
    image: Image.Image,
    *,
    bounds: tuple[float, float, float, float],
    focus_geometry: BaseGeometry,
    step3_state: str,
) -> None:
    style = STATUS_STYLE[step3_state]
    if style["tint"] is None or style["border"] is None:
        return

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay, "RGBA")
    overlay_draw.rectangle((0, 0, IMAGE_SIZE, IMAGE_SIZE), fill=style["tint"])
    _draw_polygon(
        overlay_draw,
        focus_geometry,
        bounds,
        fill=style["focus"],
    )

    focus_mask = Image.new("L", image.size, 0)
    focus_draw = ImageDraw.Draw(focus_mask)
    _draw_polygon(focus_draw, focus_geometry, bounds, fill=255)

    hatch = Image.new("RGBA", image.size, (0, 0, 0, 0))
    hatch_draw = ImageDraw.Draw(hatch, "RGBA")
    stripe_step_px = 36
    stripe_width_px = 10
    for offset in range(-IMAGE_SIZE, IMAGE_SIZE * 2, stripe_step_px):
        hatch_draw.line(
            ((offset, 0), (offset + IMAGE_SIZE, IMAGE_SIZE)),
            fill=style["hatch"],
            width=stripe_width_px,
        )
    overlay.alpha_composite(Image.composite(hatch, Image.new("RGBA", image.size, (0, 0, 0, 0)), focus_mask))

    border_px = max(10, int(round(4.0 * _px_per_m(bounds))))
    overlay_draw.rectangle((0, 0, IMAGE_SIZE - 1, IMAGE_SIZE - 1), outline=style["border"], width=border_px)
    image.alpha_composite(overlay)


def _draw_status_banner(
    image: Image.Image,
    *,
    case_result: Step3CaseResult,
    patch_size_m: float,
) -> None:
    style = STATUS_STYLE[case_result.step3_state]
    draw = ImageDraw.Draw(image, "RGBA")
    banner_height = 114
    draw.rectangle((0, 0, IMAGE_SIZE - 1, banner_height), fill=style["banner"])
    label_font = _font(42)
    meta_font = _font(21)
    footer_font = _font(19)
    _draw_text_with_shadow(
        draw,
        xy=(26, 16),
        text=style["label"],
        font=label_font,
        fill=style["text"],
        shadow=style["text_shadow"],
    )
    meta = f"Case {case_result.case_id} | {case_result.template_class or 'unknown'}"
    _draw_text_with_shadow(
        draw,
        xy=(28, 64),
        text=meta,
        font=meta_font,
        fill=style["text"],
        shadow=style["text_shadow"],
    )
    reason = f"Reason: {case_result.reason.replace('_', ' ')}"
    _draw_text_with_shadow(
        draw,
        xy=(28, 88),
        text=reason[:84],
        font=footer_font,
        fill=style["text"],
        shadow=style["text_shadow"],
    )
    patch_label = f"Patch {patch_size_m:.0f}m"
    label_width = int(draw.textlength(patch_label, font=footer_font))
    _draw_text_with_shadow(
        draw,
        xy=(IMAGE_SIZE - label_width - 28, 88),
        text=patch_label,
        font=footer_font,
        fill=style["text"],
        shadow=style["text_shadow"],
    )


def render_step3_review_png(
    *,
    out_path: Path,
    context: Step1Context,
    case_result: Step3CaseResult,
) -> None:
    bounds = _patch_bounds(context, case_result)
    patch_size_m = bounds[2] - bounds[0]
    px_per_m = _px_per_m(bounds)
    road_width = max(4, int(round(1.0 * px_per_m)))
    rc_road_width = max(4, int(round(0.9 * px_per_m)))
    negative_edge_width = max(2, int(round(0.4 * px_per_m)))
    node_radius = max(7, int(round(2.0 * px_per_m)))
    representative_radius = max(node_radius + 2, int(round(2.6 * px_per_m)))
    representative_ring = max(2, int(round(0.8 * px_per_m)))

    image = Image.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image, "RGBA")

    _draw_polygon(draw, context.drivezone_geometry, bounds, fill=DRIVEZONE_FILL, outline=DRIVEZONE_EDGE, width=max(2, int(round(0.8 * px_per_m))))
    for geometry in (
        case_result.negative_masks.adjacent_junction_geometry,
        case_result.negative_masks.foreign_objects_geometry,
        case_result.negative_masks.foreign_mst_geometry,
    ):
        _draw_polygon(draw, geometry, bounds, fill=NEGATIVE_FILL, outline=NEGATIVE_EDGE, width=negative_edge_width)
    if case_result.allowed_space_geometry is not None:
        _draw_polygon(
            draw,
            case_result.allowed_space_geometry,
            bounds,
            fill=ALLOWED_FILL,
            outline=ALLOWED_EDGE,
            width=max(3, int(round(0.6 * px_per_m))),
        )
    for road in context.roads:
        _draw_line(draw, road.geometry, bounds, fill=ROAD_COLOR, width=road_width)
    for road in context.rcsd_roads:
        _draw_line(draw, road.geometry, bounds, fill=RC_ROAD_COLOR, width=rc_road_width)

    target_node_ids = {node.node_id for node in context.target_group.nodes}
    for node in context.all_nodes:
        _draw_point(
            draw,
            node.geometry,
            bounds,
            fill=GROUP_NODE_COLOR if node.node_id in target_node_ids else FOREIGN_NODE_COLOR,
            radius=node_radius if node.node_id in target_node_ids else max(5, node_radius - 2),
        )
    _draw_point(
        draw,
        context.representative_node.geometry,
        bounds,
        fill=GROUP_NODE_COLOR,
        radius=representative_radius,
        ring=REPRESENTATIVE_RING,
        ring_width=representative_ring,
    )

    _draw_failure_overlay(
        image,
        bounds=bounds,
        focus_geometry=_build_focus_geometry(context, case_result),
        step3_state=case_result.step3_state,
    )
    _draw_status_banner(image, case_result=case_result, patch_size_m=patch_size_m)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
