from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw
from shapely.ops import unary_union

from rcsd_topo_poc.modules.t03_virtual_junction_anchor.legal_space_render import (
    BACKGROUND_COLOR,
    DRIVEZONE_EDGE,
    DRIVEZONE_FILL,
    FOREIGN_NODE_COLOR,
    GROUP_NODE_COLOR,
    IMAGE_SIZE,
    MAX_PATCH_SIZE_M,
    ROAD_COLOR,
    STATUS_STYLE,
    _draw_failure_overlay,
    _draw_line,
    _draw_point,
    _draw_polygon,
    _draw_text_with_shadow,
    _font,
    _project_xy,
)
from rcsd_topo_poc.modules.t03_virtual_junction_anchor.association_models import AssociationCaseResult, AssociationContext


ALLOWED_FILL = (255, 155, 74, 120)
ALLOWED_EDGE = (219, 119, 25, 255)
REQUIRED_FILL = (206, 18, 18, 120)
REQUIRED_EDGE = (161, 13, 13, 255)
SUPPORT_FILL = (232, 170, 45, 120)
SUPPORT_EDGE = (189, 124, 9, 255)
UTURN_EDGE = (38, 91, 167, 240)
EXCLUDED_FILL = (110, 26, 89, 72)
EXCLUDED_EDGE = (86, 19, 69, 255)
FOREIGN_SWSD_FILL = (102, 102, 102, 54)
FOREIGN_RCSD_FILL = (195, 79, 93, 42)


def _patch_bounds(context: AssociationContext, case_result: AssociationCaseResult) -> tuple[float, float, float, float]:
    step1 = context.step1_context
    reference = step1.representative_node.geometry
    drivezone_focus = context.current_swsd_surface_geometry or step1.drivezone_geometry
    focus = [reference.buffer(15.0), drivezone_focus]
    if context.step3_allowed_space_geometry is not None:
        focus.append(drivezone_focus.intersection(context.step3_allowed_space_geometry.buffer(40.0)))
        focus.append(context.step3_allowed_space_geometry)
    for geometry in (
        case_result.output_geometries.related_rcsdroad_geometry,
        case_result.output_geometries.u_turn_rcsdroad_geometry,
        case_result.output_geometries.required_rcsdroad_geometry,
        case_result.output_geometries.support_rcsdroad_geometry,
        case_result.output_geometries.excluded_rcsdroad_geometry,
        case_result.output_geometries.required_hook_zone_geometry,
        case_result.output_geometries.foreign_swsd_context_geometry,
        case_result.output_geometries.foreign_rcsd_context_geometry,
    ):
        if geometry is not None:
            focus.append(geometry)
    merged = unary_union([geometry for geometry in focus if geometry is not None and not geometry.is_empty])
    minx, miny, maxx, maxy = merged.bounds
    span = min(MAX_PATCH_SIZE_M, max(180.0, max(maxx - minx, maxy - miny) + 30.0))
    cx, cy = reference.x, reference.y
    half = span / 2.0
    return cx - half, cy - half, cx + half, cy + half


def render_association_review_png(
    *,
    out_path: Path,
    context: AssociationContext,
    case_result: AssociationCaseResult,
    debug_render: bool = False,
) -> None:
    step1 = context.step1_context
    current_surface = context.current_swsd_surface_geometry or step1.drivezone_geometry
    image = Image.new("RGBA", (IMAGE_SIZE, IMAGE_SIZE), BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image, "RGBA")
    bounds = _patch_bounds(context, case_result)

    _draw_polygon(draw, current_surface, bounds, fill=DRIVEZONE_FILL, outline=DRIVEZONE_EDGE, width=2)
    _draw_polygon(draw, case_result.output_geometries.foreign_swsd_context_geometry, bounds, fill=FOREIGN_SWSD_FILL)
    _draw_polygon(draw, case_result.output_geometries.foreign_rcsd_context_geometry, bounds, fill=FOREIGN_RCSD_FILL)
    _draw_polygon(draw, context.step3_allowed_space_geometry, bounds, fill=ALLOWED_FILL, outline=ALLOWED_EDGE, width=2)
    _draw_polygon(draw, case_result.output_geometries.required_hook_zone_geometry, bounds, fill=SUPPORT_FILL, outline=SUPPORT_EDGE, width=2)

    for road in step1.roads:
        if current_surface is not None and not road.geometry.intersects(current_surface.buffer(0.5)):
            continue
        fill = ROAD_COLOR if road.road_id in set(context.selected_road_ids) else (85, 85, 85, 170)
        width = 8 if road.road_id in set(context.selected_road_ids) else 5
        _draw_line(draw, road.geometry, bounds, fill=fill, width=width)

    _draw_line(draw, case_result.output_geometries.excluded_rcsdroad_geometry, bounds, fill=EXCLUDED_EDGE, width=5)
    _draw_line(draw, case_result.output_geometries.u_turn_rcsdroad_geometry, bounds, fill=UTURN_EDGE, width=5)
    _draw_line(draw, case_result.output_geometries.support_rcsdroad_geometry, bounds, fill=SUPPORT_EDGE, width=6)
    related_rcsdroad_geometry = case_result.output_geometries.related_rcsdroad_geometry
    if related_rcsdroad_geometry is None or related_rcsdroad_geometry.is_empty:
        related_rcsdroad_geometry = case_result.output_geometries.required_rcsdroad_geometry
    _draw_line(
        draw,
        related_rcsdroad_geometry,
        bounds,
        fill=REQUIRED_EDGE,
        width=7,
    )

    _draw_point(draw, case_result.output_geometries.excluded_rcsdnode_geometry, bounds, fill=EXCLUDED_EDGE, radius=5)
    _draw_point(draw, case_result.output_geometries.support_rcsdnode_geometry, bounds, fill=SUPPORT_EDGE, radius=6)
    _draw_point(draw, case_result.output_geometries.required_rcsdnode_geometry, bounds, fill=REQUIRED_EDGE, radius=7)
    _draw_point(draw, step1.representative_node.geometry, bounds, fill=GROUP_NODE_COLOR, radius=8, ring=(255, 255, 255, 255), ring_width=2)
    for group in step1.foreign_groups:
        for node in group.nodes:
            if current_surface is not None and not node.geometry.intersects(current_surface.buffer(0.5)):
                continue
            _draw_point(draw, node.geometry, bounds, fill=FOREIGN_NODE_COLOR, radius=4)

    focus_geometry = unary_union(
        [
            geometry
            for geometry in (
                context.step3_allowed_space_geometry,
                case_result.output_geometries.required_hook_zone_geometry,
                related_rcsdroad_geometry,
                step1.representative_node.geometry.buffer(10.0),
            )
            if geometry is not None
        ]
    )
    _draw_failure_overlay(
        image,
        bounds=bounds,
        focus_geometry=focus_geometry,
        step3_state=case_result.association_state,
    )

    banner_style = STATUS_STYLE[case_result.association_state]
    draw.rectangle((24, 24, IMAGE_SIZE - 24, 112), fill=banner_style["banner"])
    _draw_text_with_shadow(
        draw,
        xy=(44, 40),
        text=f"{banner_style['label']} / Association {case_result.association_class}",
        font=_font(32),
        fill=banner_style["text"],
        shadow=banner_style["text_shadow"],
    )
    _draw_text_with_shadow(
        draw,
        xy=(44, 78),
        text=f"case={case_result.case_id}  template={case_result.template_class}  reason={case_result.reason}",
        font=_font(18),
        fill=banner_style["text"],
        shadow=banner_style["text_shadow"],
    )
    if debug_render:
        _draw_text_with_shadow(
            draw,
            xy=(44, IMAGE_SIZE - 60),
            text=f"step3={context.step3_status_doc.get('step3_state')}  selected_roads={len(context.selected_road_ids)}",
            font=_font(16),
            fill=(20, 20, 20, 255),
            shadow=(255, 255, 255, 255),
        )
        minx, miny, maxx, maxy = bounds
        for x, y, label in (
            (minx, miny, "LL"),
            (maxx, miny, "LR"),
            (minx, maxy, "UL"),
            (maxx, maxy, "UR"),
        ):
            px, py = _project_xy(x, y, bounds)
            draw.text((px + 3, py + 3), label, font=_font(14), fill=(0, 0, 0, 255))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(out_path)
